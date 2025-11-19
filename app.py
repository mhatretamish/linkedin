import logging
import time
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl, field_validator
import uvicorn

from config import config
from cache_manager import initialize_cache, get_cache_manager
from scraper import initialize_scraper, get_scraper
from universal_scraper import UniversalJobScraper
from concurrent_handler import ConcurrentRequestHandler, async_process_batch

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Pydantic models for request/response
class ScrapeRequest(BaseModel):
    url: HttpUrl
    bypass_cache: bool = Field(default=False, description="Bypass cache and fetch fresh data")

    @field_validator('url')
    @classmethod
    def validate_job_url(cls, v):
        url_str = str(v)
        supported_sites = ["linkedin.com", "internshala.com", "indeed.com"]
        if not any(site in url_str for site in supported_sites):
            raise ValueError(f"URL must be from a supported job site: {', '.join(supported_sites)}")
        return v

class BatchScrapeRequest(BaseModel):
    urls: List[HttpUrl] = Field(..., min_items=1, max_items=config.BATCH_MAX_SIZE, description="List of job URLs to scrape")
    bypass_cache: bool = Field(default=False, description="Bypass cache for all URLs")
    concurrent: bool = Field(default=True, description="Process URLs concurrently")

    @field_validator('urls')
    @classmethod
    def validate_job_urls(cls, v):
        supported_sites = ["linkedin.com", "internshala.com", "indeed.com"]
        for url in v:
            url_str = str(url)
            if not any(site in url_str for site in supported_sites):
                raise ValueError(f"All URLs must be from supported job sites: {', '.join(supported_sites)}. Invalid: {url}")
        return v

class ScrapeResponse(BaseModel):
    success: bool
    type: str
    platform: str = Field(default="unknown", description="Platform/site that was scraped")
    url: str
    content: Dict[str, Any]
    cached: bool = False
    cache_age_seconds: Optional[float] = None
    timestamp: float
    processing_time_ms: float

class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None
    timestamp: float


# Application lifespan manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing Universal Job Resolver API Server...")

    # Initialize cache manager
    cache = initialize_cache(
        max_size=config.CACHE_MAX_SIZE,
        ttl=config.CACHE_TTL_SECONDS
    )
    logger.info(f"Cache initialized: max_size={config.CACHE_MAX_SIZE}, ttl={config.CACHE_TTL_SECONDS}s")

    # Initialize LinkedIn scraper (for backward compatibility and concurrent handler)
    linkedin_scraper = initialize_scraper()
    logger.info("LinkedIn scraper initialized with session management")

    # Initialize universal scraper
    universal_scraper = UniversalJobScraper()
    logger.info(f"Universal scraper initialized with support for: {', '.join(universal_scraper.get_supported_sites())}")

    # Initialize concurrent handler (using LinkedIn scraper for now, will update later)
    concurrent_handler = ConcurrentRequestHandler(
        scraper=linkedin_scraper,
        cache_manager=cache,
        max_workers=config.MAX_WORKERS,
        max_queue_size=config.MAX_QUEUE_SIZE,
        rate_limit=config.MAX_REQUESTS_PER_MINUTE,
        rate_window=60
    )
    logger.info(f"Concurrent handler initialized with {config.MAX_WORKERS} workers")

    # Store in app state
    app.state.cache = cache
    app.state.scraper = linkedin_scraper  # Keep for concurrent handler
    app.state.universal_scraper = universal_scraper  # New universal scraper
    app.state.concurrent_handler = concurrent_handler

    logger.info(f"API Server started on {config.HOST}:{config.PORT}")
    logger.info(f"Supported job sites: {', '.join(universal_scraper.get_supported_sites())}")

    yield

    # Shutdown
    logger.info("Shutting down Universal Job Scraper API Server...")

    # Shutdown concurrent handler
    if hasattr(app.state, 'concurrent_handler'):
        app.state.concurrent_handler.shutdown(wait=True)

    # Close scraper session
    if app.state.scraper and app.state.scraper.session:
        try:
            app.state.scraper.session.close()
        except Exception:
            pass


# Create FastAPI application
app = FastAPI(
    title="Universal Job Scraper API",
    description="High-performance job content scraping API supporting LinkedIn, Internshala, and Indeed with caching and session management",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Custom exception handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.detail,
            timestamp=time.time()
        ).dict()
    )


# Health check endpoint
@app.get("/health", tags=["System"])
async def health_check():
    """Check API health status"""
    scraper = get_scraper()
    cache = get_cache_manager()

    return {
        "status": "healthy",
        "timestamp": time.time(),
        "scraper": {
            "initialized": scraper is not None,
            "stats": scraper.get_session_stats() if scraper else None
        },
        "cache": {
            "initialized": cache is not None,
            "stats": cache.get_stats() if cache else None
        }
    }


# Main scraping endpoint
@app.post(f"{config.API_PREFIX}/scrape", response_model=ScrapeResponse, tags=["Scraping"])
async def scrape_job_content(request: ScrapeRequest):
    """
    Scrape job content from supported job sites (LinkedIn, Internshala, Indeed)

    - Automatically detects platform and content type
    - Uses in-memory caching for faster responses
    - Maintains persistent sessions for optimal performance
    - Returns job descriptions and metadata in standardized format
    """
    start_time = time.time()
    url_str = str(request.url)

    cache = get_cache_manager()
    scraper = get_scraper()

    if not scraper:
        raise HTTPException(status_code=500, detail="Scraper not initialized")

    # Check cache unless bypassed
    cached_data = None
    cache_age = None
    if not request.bypass_cache and cache:
        cached_result = cache.get(url_str)
        if cached_result:
            cached_data, timestamp = cached_result
            cache_age = time.time() - timestamp
            logger.info(f"Cache hit for {url_str[:50]}... (age: {cache_age:.1f}s)")

    if cached_data:
        # Return cached data
        processing_time = (time.time() - start_time) * 1000
        
        # Handle processing time for cached data
        if 'processing_time_ms' not in cached_data:
            cached_data['processing_time_ms'] = processing_time
        
        # Create response dict with proper fields
        response_data = dict(cached_data)
        response_data.update({
            'cached': True,
            'cache_age_seconds': cache_age
        })
            
        return ScrapeResponse(**response_data)

    # Fetch fresh data
    try:
        logger.info(f"Fetching fresh data for {url_str[:50]}...")
        # Use universal scraper instead of LinkedIn-only scraper
        universal_scraper = app.state.universal_scraper
        
        # Run synchronous function in thread pool to avoid blocking
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            universal_scraper.scrape,
            url_str
        )

        # Cache the successful result
        if cache and result["success"]:
            cache.set(url_str, result)

        processing_time = (time.time() - start_time) * 1000
        
        # Handle processing time - use scraper's time if available, otherwise use our calculation
        if 'processing_time_ms' not in result:
            result['processing_time_ms'] = processing_time
        
        # Create response dict with proper fields  
        response_data = dict(result)
        response_data.update({
            'cached': False
        })
        
        return ScrapeResponse(**response_data)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")


# Batch scraping endpoint
@app.post(f"{config.API_PREFIX}/batch", tags=["Scraping"])
async def batch_scrape(request: BatchScrapeRequest):
    """
    Scrape multiple job URLs in batch from supported sites

    - Process up to 50 URLs in a single request from any supported platform
    - Concurrent processing with configurable workers  
    - Automatic rate limiting between requests
    - Returns results for all URLs, including failures
    """
    if not hasattr(app.state, 'concurrent_handler'):
        raise HTTPException(status_code=500, detail="Concurrent handler not initialized")

    urls = [str(url) for url in request.urls]
    start_time = time.time()

    if request.concurrent:
        # Use concurrent processing
        handler = app.state.concurrent_handler
        results = await async_process_batch(
            handler,
            urls,
            bypass_cache=request.bypass_cache
        )

        # Convert RequestResult objects to dicts
        results_dict = []
        for result in results:
            if result.success:
                results_dict.append({
                    **result.data,
                    "cached": result.cached,
                    "cache_age_seconds": result.cache_age_seconds,
                    "processing_time_ms": result.processing_time * 1000
                })
            else:
                results_dict.append({
                    "success": False,
                    "url": result.url,
                    "error": result.error,
                    "timestamp": time.time()
                })
    else:
        # Fallback to sequential processing
        scraper = get_scraper()
        cache = get_cache_manager()

        if not scraper:
            raise HTTPException(status_code=500, detail="Scraper not initialized")

        results_dict = []
        for url in urls:
            try:
                # Check cache first
                cached_data = None
                if not request.bypass_cache and cache:
                    cached_result = cache.get(url)
                    if cached_result:
                        cached_data, timestamp = cached_result
                        cache_age = time.time() - timestamp

                if cached_data:
                    results_dict.append({
                        **cached_data,
                        "cached": True,
                        "cache_age_seconds": cache_age
                    })
                else:
                    # Run synchronous function in thread pool
                    import asyncio
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None,
                        scraper.fetch_content,
                        url,
                        request.bypass_cache
                    )
                    if cache and result["success"]:
                        cache.set(url, result)
                    results_dict.append({**result, "cached": False})

            except Exception as e:
                results_dict.append({
                    "success": False,
                    "url": url,
                    "error": str(e),
                    "timestamp": time.time()
                })

    processing_time = (time.time() - start_time) * 1000

    return {
        "success": True,
        "total_urls": len(urls),
        "successful": sum(1 for r in results_dict if r.get("success", False)),
        "failed": sum(1 for r in results_dict if not r.get("success", False)),
        "results": results_dict,
        "processing_time_ms": processing_time,
        "concurrent": request.concurrent
    }


# Cache management endpoints
@app.get(f"{config.API_PREFIX}/cache/stats", tags=["Cache"])
async def get_cache_stats():
    """Get cache statistics"""
    cache = get_cache_manager()
    if not cache:
        raise HTTPException(status_code=500, detail="Cache not initialized")

    return cache.get_stats()


@app.get(f"{config.API_PREFIX}/cache/items", tags=["Cache"])
async def get_cached_items():
    """List all cached URLs with expiration info"""
    cache = get_cache_manager()
    if not cache:
        raise HTTPException(status_code=500, detail="Cache not initialized")

    return {
        "items": cache.get_cached_urls(),
        "total": len(cache.cache)
    }


@app.delete(f"{config.API_PREFIX}/cache", tags=["Cache"])
async def clear_cache():
    """Clear all cached data"""
    cache = get_cache_manager()
    if not cache:
        raise HTTPException(status_code=500, detail="Cache not initialized")

    count = cache.clear()
    return {
        "success": True,
        "cleared_items": count,
        "message": f"Cleared {count} items from cache"
    }


@app.delete(f"{config.API_PREFIX}/cache/item", tags=["Cache"])
async def invalidate_cache_item(url: str = Query(..., description="URL to invalidate from cache")):
    """Invalidate specific URL from cache"""
    cache = get_cache_manager()
    if not cache:
        raise HTTPException(status_code=500, detail="Cache not initialized")

    success = cache.invalidate(url)
    if success:
        return {"success": True, "message": f"Invalidated cache for {url}"}
    else:
        return {"success": False, "message": f"URL not found in cache: {url}"}


# Session management endpoints
@app.get(f"{config.API_PREFIX}/session/stats", tags=["Session"])
async def get_session_stats():
    """Get current session statistics"""
    scraper = get_scraper()
    if not scraper:
        raise HTTPException(status_code=500, detail="Scraper not initialized")

    return scraper.get_session_stats()


@app.post(f"{config.API_PREFIX}/session/refresh", tags=["Session"])
async def refresh_session():
    """Force refresh the scraper session"""
    scraper = get_scraper()
    if not scraper:
        raise HTTPException(status_code=500, detail="Scraper not initialized")

    try:
        scraper.initialize_session()
        return {
            "success": True,
            "message": "Session refreshed successfully",
            "stats": scraper.get_session_stats()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh session: {str(e)}")


# Configuration endpoint
@app.get(f"{config.API_PREFIX}/config", tags=["System"])
async def get_configuration():
    """Get current API configuration (non-sensitive)"""
    return {
        "cache_ttl_seconds": config.CACHE_TTL_SECONDS,
        "cache_max_size": config.CACHE_MAX_SIZE,
        "max_requests_per_minute": config.MAX_REQUESTS_PER_MINUTE,
        "session_timeout": config.SESSION_TIMEOUT,
        "max_retries": config.MAX_RETRIES,
        "max_workers": config.MAX_WORKERS,
        "batch_max_size": config.BATCH_MAX_SIZE,
        "api_version": "2.0.0"
    }


# Supported sites endpoint
@app.get(f"{config.API_PREFIX}/supported-sites", tags=["System"])
async def get_supported_sites():
    """Get list of supported job sites for scraping"""
    if not hasattr(app.state, 'universal_scraper'):
        raise HTTPException(status_code=500, detail="Universal scraper not initialized")
    
    universal_scraper = app.state.universal_scraper
    return {
        "supported_sites": universal_scraper.get_supported_sites(),
        "description": "Job sites supported by the Universal Job Scraper API",
        "usage": "URLs must contain one of the supported domains"
    }


# Concurrent handler statistics
@app.get(f"{config.API_PREFIX}/concurrent/stats", tags=["System"])
async def get_concurrent_stats():
    """Get concurrent handler statistics"""
    if not hasattr(app.state, 'concurrent_handler'):
        raise HTTPException(status_code=500, detail="Concurrent handler not initialized")

    return app.state.concurrent_handler.get_statistics()


# Async batch processing endpoint
class AsyncBatchRequest(BaseModel):
    urls: List[HttpUrl] = Field(..., min_items=1, max_items=config.BATCH_MAX_SIZE)
    bypass_cache: bool = Field(default=False)
    webhook_url: Optional[HttpUrl] = Field(default=None, description="URL to POST results when complete")


@app.post(f"{config.API_PREFIX}/batch/async", tags=["Scraping"])
async def async_batch_scrape(request: AsyncBatchRequest, background_tasks: BackgroundTasks):
    """
    Submit batch of URLs for asynchronous processing

    - Returns immediately with batch ID
    - Process URLs in background with concurrent workers
    - Optional webhook notification when complete
    """
    if not hasattr(app.state, 'concurrent_handler'):
        raise HTTPException(status_code=500, detail="Concurrent handler not initialized")

    urls = [str(url) for url in request.urls]
    handler = app.state.concurrent_handler

    # Generate batch ID
    batch_id = f"batch_{int(time.time() * 1000)}_{len(urls)}"

    def process_and_notify():
        """Process batch and send webhook if configured"""
        results = handler.process_batch(urls, request.bypass_cache)

        if request.webhook_url:
            import requests
            try:
                payload = {
                    "batch_id": batch_id,
                    "total_urls": len(urls),
                    "successful": sum(1 for r in results if r.success),
                    "failed": sum(1 for r in results if not r.success),
                    "results": [
                        {
                            "url": r.url,
                            "success": r.success,
                            "data": r.data if r.success else None,
                            "error": r.error if not r.success else None,
                            "cached": r.cached,
                            "processing_time": r.processing_time
                        }
                        for r in results
                    ]
                }
                requests.post(str(request.webhook_url), json=payload, timeout=30)
            except Exception as e:
                logger.error(f"Failed to send webhook for batch {batch_id}: {e}")

    # Add to background tasks
    background_tasks.add_task(process_and_notify)

    return {
        "success": True,
        "batch_id": batch_id,
        "total_urls": len(urls),
        "status": "processing",
        "message": f"Batch {batch_id} submitted for processing"
    }


# Stream processing endpoint
class StreamRequest(BaseModel):
    urls: List[HttpUrl] = Field(..., min_items=1)
    max_concurrent: Optional[int] = Field(default=None, description="Max concurrent requests")
    stop_on_error: bool = Field(default=False)


# Root endpoint
@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "name": "LinkedIn Resolver API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "api_prefix": config.API_PREFIX
    }


def main():
    """Run the application"""
    uvicorn.run(
        "app:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.DEBUG,
        log_level="info",
        access_log=True
    )


if __name__ == "__main__":
    main()