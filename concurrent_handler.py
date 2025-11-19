import asyncio
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional, Callable
from queue import Queue
from threading import Lock, Semaphore
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RequestTask:
    """Container for individual request task"""
    url: str
    bypass_cache: bool = False
    priority: int = 0  # Higher priority = processed first
    created_at: float = field(default_factory=time.time)
    callback: Optional[Callable] = None
    task_id: Optional[str] = None


@dataclass
class RequestResult:
    """Container for request result"""
    url: str
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    cached: bool = False
    cache_age_seconds: Optional[float] = None
    processing_time: float = 0
    task_id: Optional[str] = None


class RateLimiter:
    """Thread-safe rate limiter using sliding window algorithm"""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = []
        self.lock = Lock()

    def can_make_request(self) -> bool:
        """Check if a request can be made within rate limits"""
        with self.lock:
            now = time.time()
            # Clean old requests outside the window
            self.requests = [
                req_time for req_time in self.requests
                if req_time > now - self.window_seconds
            ]
            return len(self.requests) < self.max_requests

    def add_request(self):
        """Record a new request"""
        with self.lock:
            self.requests.append(time.time())

    def wait_time_until_next_request(self) -> float:
        """Calculate wait time until next request can be made"""
        with self.lock:
            if len(self.requests) < self.max_requests:
                return 0

            # Find the oldest request in window
            now = time.time()
            self.requests = [
                req_time for req_time in self.requests
                if req_time > now - self.window_seconds
            ]

            if len(self.requests) < self.max_requests:
                return 0

            # Calculate wait time until oldest request exits window
            oldest_request = min(self.requests)
            wait_time = (oldest_request + self.window_seconds) - now
            return max(0, wait_time)


class ConcurrentRequestHandler:
    """Handles concurrent LinkedIn profile scraping with threading"""

    def __init__(
        self,
        scraper,
        cache_manager,
        max_workers: int = 5,
        max_queue_size: int = 100,
        rate_limit: int = 30,
        rate_window: int = 60
    ):
        self.scraper = scraper
        self.cache = cache_manager
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size

        # Threading components
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.request_queue = Queue(maxsize=max_queue_size)
        self.result_queue = Queue()

        # Rate limiting
        self.rate_limiter = RateLimiter(rate_limit, rate_window)

        # Synchronization
        self.shutdown_event = threading.Event()
        self.active_tasks = 0
        self.tasks_lock = Lock()

        # Statistics
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'cache_hits': 0,
            'avg_processing_time': 0,
            'active_workers': 0
        }
        self.stats_lock = Lock()

        logger.info(
            f"ConcurrentRequestHandler initialized: "
            f"max_workers={max_workers}, rate_limit={rate_limit}/{rate_window}s"
        )

    def _process_single_request(self, task: RequestTask) -> RequestResult:
        """Process a single scraping request"""
        start_time = time.time()
        result_obj = None

        try:
            # Check cache first
            if not task.bypass_cache and self.cache:
                cached_result = self.cache.get(task.url)
                if cached_result:
                    cached_data, timestamp = cached_result
                    cache_age = time.time() - timestamp

                    with self.stats_lock:
                        self.stats['cache_hits'] += 1

                    result_obj = RequestResult(
                        url=task.url,
                        success=True,
                        data=cached_data,
                        cached=True,
                        cache_age_seconds=cache_age,
                        processing_time=time.time() - start_time,
                        task_id=task.task_id
                    )
                    return result_obj

            # Wait for rate limit if needed
            wait_time = self.rate_limiter.wait_time_until_next_request()
            if wait_time > 0:
                logger.debug(f"Rate limit reached, waiting {wait_time:.2f}s")
                time.sleep(wait_time)

            # Make the actual request
            self.rate_limiter.add_request()
            result = self.scraper.fetch_content(task.url, task.bypass_cache)

            # Cache successful results
            if self.cache and result.get("success"):
                self.cache.set(task.url, result)

            result_obj = RequestResult(
                url=task.url,
                success=result.get("success", False),
                data=result if result.get("success") else None,
                error=result.get("error") if not result.get("success") else None,
                cached=False,
                processing_time=time.time() - start_time,
                task_id=task.task_id
            )
            return result_obj

        except Exception as e:
            logger.error(f"Error processing {task.url}: {e}")
            result_obj = RequestResult(
                url=task.url,
                success=False,
                error=str(e),
                processing_time=time.time() - start_time,
                task_id=task.task_id
            )
            return result_obj
        finally:
            # Update statistics
            with self.stats_lock:
                self.stats['total_requests'] += 1
                if result_obj and result_obj.success:
                    self.stats['successful_requests'] += 1
                else:
                    self.stats['failed_requests'] += 1

                # Update average processing time
                current_avg = self.stats['avg_processing_time']
                total_requests = self.stats['total_requests']
                processing_time = time.time() - start_time
                self.stats['avg_processing_time'] = (
                    (current_avg * (total_requests - 1) + processing_time) / total_requests
                )

    def process_batch(
        self,
        urls: List[str],
        bypass_cache: bool = False,
        priority: int = 0,
        return_partial: bool = True
    ) -> List[RequestResult]:
        """
        Process multiple URLs concurrently

        Args:
            urls: List of URLs to process
            bypass_cache: Whether to bypass cache for all URLs
            priority: Priority level for the batch
            return_partial: Return partial results if some fail

        Returns:
            List of RequestResult objects
        """
        futures = []
        results = []

        # Submit all tasks to executor
        for url in urls:
            task = RequestTask(
                url=url,
                bypass_cache=bypass_cache,
                priority=priority,
                task_id=f"batch_{time.time()}_{len(futures)}"
            )

            future = self.executor.submit(self._process_single_request, task)
            futures.append((future, url))

        # Collect results as they complete
        for future, url in futures:
            try:
                result = future.result(timeout=30)  # 30 second timeout per request
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to process {url}: {e}")
                if not return_partial:
                    raise
                results.append(RequestResult(
                    url=url,
                    success=False,
                    error=str(e),
                    task_id=f"batch_error_{time.time()}"
                ))

        return results

    def process_batch_async(
        self,
        urls: List[str],
        bypass_cache: bool = False,
        callback: Optional[Callable] = None
    ) -> str:
        """
        Process batch asynchronously and return immediately with batch ID

        Args:
            urls: List of URLs to process
            bypass_cache: Whether to bypass cache
            callback: Optional callback function to call with results

        Returns:
            Batch ID for tracking
        """
        batch_id = f"batch_{int(time.time() * 1000)}"

        def batch_processor():
            results = self.process_batch(urls, bypass_cache)
            if callback:
                callback(batch_id, results)
            return results

        # Submit batch processing task
        self.executor.submit(batch_processor)
        return batch_id

    def process_stream(
        self,
        url_generator,
        max_concurrent: Optional[int] = None,
        stop_on_error: bool = False
    ):
        """
        Process URLs from a generator/iterator with concurrent execution

        Args:
            url_generator: Generator or iterator yielding URLs
            max_concurrent: Maximum concurrent requests (defaults to max_workers)
            stop_on_error: Stop processing on first error

        Yields:
            RequestResult objects as they complete
        """
        max_concurrent = max_concurrent or self.max_workers
        semaphore = Semaphore(max_concurrent)
        futures = []

        def submit_task(url):
            semaphore.acquire()
            task = RequestTask(url=url, task_id=f"stream_{time.time()}")
            future = self.executor.submit(
                lambda t: (self._process_single_request(t), semaphore.release())[0],
                task
            )
            return future

        # Submit initial batch
        for i, url in enumerate(url_generator):
            if i >= max_concurrent:
                # Start yielding results before submitting more
                break
            futures.append(submit_task(url))

        # Process results and submit new tasks
        url_iter = iter(url_generator)
        while futures:
            # Wait for any future to complete
            for future in as_completed(futures):
                try:
                    result = future.result()
                    yield result

                    if not result.success and stop_on_error:
                        logger.warning("Stopping stream due to error")
                        return

                except Exception as e:
                    logger.error(f"Stream processing error: {e}")
                    if stop_on_error:
                        return
                finally:
                    futures.remove(future)

                # Submit next URL if available
                try:
                    next_url = next(url_iter)
                    futures.append(submit_task(next_url))
                except StopIteration:
                    pass

    def get_statistics(self) -> Dict[str, Any]:
        """Get current handler statistics"""
        with self.stats_lock:
            return {
                **self.stats.copy(),
                'active_workers': self.executor._threads.__len__() if hasattr(self.executor, '_threads') else 0,
                'queue_size': self.request_queue.qsize() if self.request_queue else 0,
                'rate_limit_status': {
                    'can_make_request': self.rate_limiter.can_make_request(),
                    'wait_time': self.rate_limiter.wait_time_until_next_request()
                }
            }

    def shutdown(self, wait: bool = True):
        """Shutdown the handler and cleanup resources"""
        logger.info("Shutting down ConcurrentRequestHandler")
        self.shutdown_event.set()

        if self.executor:
            self.executor.shutdown(wait=wait)

        logger.info("ConcurrentRequestHandler shutdown complete")


async def async_process_batch(
    handler: ConcurrentRequestHandler,
    urls: List[str],
    bypass_cache: bool = False
) -> List[RequestResult]:
    """
    Async wrapper for batch processing

    Args:
        handler: ConcurrentRequestHandler instance
        urls: List of URLs to process
        bypass_cache: Whether to bypass cache

    Returns:
        List of RequestResult objects
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        handler.process_batch,
        urls,
        bypass_cache
    )