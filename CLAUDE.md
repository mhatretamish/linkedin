# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A high-performance FastAPI server for scraping job content from LinkedIn, Internshala, and Indeed with intelligent caching, session management, and anti-detection features.

## Running the Application

Start the API server:
```bash
python app.py
```

The server runs on `http://localhost:8000` by default. API documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Configuration

Before running, add LinkedIn session cookies to `cookies.json`. Use a browser extension to export cookies from an authenticated LinkedIn session.

All configuration is centralized in `config.py`:
- Cache TTL and size limits
- Rate limiting parameters (default: 30 requests/minute)
- Retry logic and backoff factors
- Session timeouts
- Proxy configuration (optional)
- TLS client identifiers
- Threading configuration for concurrent processing

## Architecture

### Core Components

**app.py** - FastAPI application entry point
- Manages application lifespan (startup/shutdown)
- Initializes three key components: cache manager, scraper instances, and concurrent handler
- Defines all API endpoints and request/response models
- Coordinates between cache, scrapers, and concurrent processing

**universal_scraper.py** - Multi-platform scraping orchestration
- `UniversalJobScraper` class detects URL platform and routes to appropriate scraper
- Three specialized scrapers: `LinkedInScraper`, `InternshalaJobScraper`, `IndeedJobScraper`
- Each scraper implements `BaseScraper` interface with `detect_url()`, `normalize_url()`, and `scrape()` methods
- Handles platform-specific URL normalization and content extraction

**scraper.py** - LinkedIn-specific scraper implementation
- Uses `tls_client` library for browser-like TLS fingerprinting
- Maintains persistent session with cookie authentication
- Advanced URL normalization handles collection URLs, search URLs, path-based URLs, and regional domains
- Multi-method content extraction: meta tags → JSON-LD → HTML selectors → embedded JSON → pattern matching
- Automatic retry logic with exponential backoff
- Proxy support with automatic fallback to direct connection

**cache_manager.py** - TTL-based in-memory caching
- Thread-safe `TTLCache` implementation
- MD5-based cache key generation
- Tracks hit/miss statistics and cache performance metrics
- Methods: `get()`, `set()`, `invalidate()`, `clear()`, `get_stats()`

**concurrent_handler.py** - Threaded batch processing
- `ThreadPoolExecutor` for concurrent scraping with configurable worker pool
- `RateLimiter` class implements sliding window rate limiting
- Processes URLs concurrently while respecting rate limits
- Supports batch processing, async batch with webhooks, and streaming
- Returns `RequestResult` objects with success/error status and timing metrics

**config.py** - Centralized configuration
- All tunable parameters in one place
- Methods for random user agent generation and TLS identifier selection

### Request Flow

1. Request arrives at API endpoint in `app.py`
2. Cache manager checks for cached response (if not bypassed)
3. If cache miss, `UniversalJobScraper` detects platform from URL
4. Platform-specific scraper normalizes URL and fetches content:
   - LinkedIn: Uses TLS client with cookies, handles complex URL formats
   - Internshala/Indeed: Uses TLS client with standard headers
5. Scraper extracts job data using multiple fallback methods
6. Successful result is cached with timestamp
7. Response returned with metadata (cached status, processing time, etc.)

For batch requests:
1. `ConcurrentRequestHandler` receives URL list
2. Submits tasks to thread pool executor
3. Each worker independently processes URLs with rate limiting
4. Results collected as futures complete
5. Returns array of `RequestResult` objects

### Key Design Patterns

**Session Management**: TLS client sessions are initialized at startup and maintained throughout application lifecycle. Sessions include cookie management, custom headers, and optional proxy configuration. Session health is checked before requests with automatic reinitialization on timeout.

**Multi-Method Extraction**: Content extraction uses a waterfall approach with 8+ methods for LinkedIn (meta tags, JSON-LD, HTML selectors, embedded code blocks, pattern matching) to maximize success rate. Each method is tried in order until sufficient content is found.

**Error Recovery**: All scrapers implement retry logic with exponential backoff. LinkedIn scraper specifically handles 429 rate limits, 403 forbidden (cookie refresh), and 404 not found errors. Proxy failures automatically fall back to direct connections.

**Caching Strategy**: Cache uses URL as key with TTL expiration. Cache hits return immediately with age metadata. Bypass cache option forces fresh fetches. Cache statistics track hit rate and performance.

## API Endpoints

### Scraping
- `POST /api/v1/scrape` - Single URL scraping with cache support
- `POST /api/v1/batch` - Batch scraping (up to 50 URLs) with concurrent processing
- `POST /api/v1/batch/async` - Async batch with optional webhook callback

### Cache Management
- `GET /api/v1/cache/stats` - Cache performance statistics
- `GET /api/v1/cache/items` - List cached URLs with expiration
- `DELETE /api/v1/cache` - Clear all cache
- `DELETE /api/v1/cache/item?url=<url>` - Invalidate specific URL

### System
- `GET /health` - Health check with scraper and cache status
- `GET /api/v1/config` - View current configuration (non-sensitive)
- `GET /api/v1/supported-sites` - List supported job sites
- `GET /api/v1/session/stats` - LinkedIn session statistics
- `POST /api/v1/session/refresh` - Force LinkedIn session refresh
- `GET /api/v1/concurrent/stats` - Concurrent handler statistics

## Adding New Platforms

To add support for a new job site:

1. Create new scraper class in `universal_scraper.py` inheriting from `BaseScraper`:
```python
class NewSiteScraper(BaseScraper):
    def detect_url(self, url: str) -> bool:
        # Return True if URL is from this site

    def normalize_url(self, url: str) -> str:
        # Extract job ID and create canonical URL

    def scrape(self, url: str) -> Dict[str, Any]:
        # Fetch and extract job content
        # Return dict with: success, type, platform, url, content, timestamp, processing_time_ms
```

2. Initialize session in `__init__()` using `tls_client.Session()`

3. Implement `_extract_job_info()` method for site-specific HTML parsing

4. Add scraper instance to `UniversalJobScraper.__init__()` scrapers list

5. Update `UniversalJobScraper.get_supported_sites()` to include new site

6. Add site domain to URL validation in `app.py` request models

## Important Implementation Details

**LinkedIn URL Normalization**: The scraper handles 7+ different LinkedIn URL formats by extracting job IDs from `currentJobId` parameters, path patterns like `/jobs/view/title-123456`, and regex matching for 10+ digit job IDs. Regional domains (in.linkedin.com, uk.linkedin.com, etc.) are normalized to www.linkedin.com.

**Content Extraction Priority**: For LinkedIn, the extraction order is: (1) Meta tags (most reliable), (2) JSON-LD structured data, (3) HTML selectors (20+ variants tried), (4) JSON-LD scripts, (5) Embedded code blocks with JSON, (6) Fallback selectors, (7) Pattern matching. Each method includes validation to filter config/metadata and ensure clean job descriptions.

**Proxy Strategy**: LinkedIn scraper uses proxy for first 2 attempts. On proxy authentication failure (407), switches to direct connection for remaining attempts. This balances anti-detection with reliability.

**Thread Safety**: Cache manager and rate limiter use threading locks for all state modifications. Concurrent handler tracks active tasks with locks. Statistics updates are atomic within lock context.

**Response Format**: All endpoints return consistent format with `success`, `type`, `platform`, `url`, `content`, `cached`, `timestamp`, and `processing_time_ms` fields. Errors include `error` field with message.
