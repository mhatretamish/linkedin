import hashlib
import json
import time
from typing import Any, Dict, Optional, Tuple
from cachetools import TTLCache
from threading import Lock
import logging

logger = logging.getLogger(__name__)


class CacheManager:
    def __init__(self, max_size: int = 1000, ttl: int = 1800):
        """
        Initialize cache manager with TTL-based caching

        Args:
            max_size: Maximum number of items in cache
            ttl: Time-to-live for cache items in seconds
        """
        self.cache = TTLCache(maxsize=max_size, ttl=ttl)
        self.lock = Lock()
        self.stats = {
            "hits": 0,
            "misses": 0,
            "total_requests": 0,
            "cache_size": 0,
            "evictions": 0
        }
        self.ttl = ttl
        logger.info(f"Cache initialized with max_size={max_size}, ttl={ttl}s")

    def _generate_cache_key(self, url: str, params: Optional[Dict] = None) -> str:
        """Generate a unique cache key based on URL and parameters"""
        key_data = {"url": url}
        if params:
            key_data.update(params)

        # Create a deterministic hash
        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_string.encode()).hexdigest()

    def get(self, url: str, params: Optional[Dict] = None) -> Optional[Tuple[Any, float]]:
        """
        Get item from cache if exists and not expired

        Returns:
            Tuple of (cached_data, timestamp) or None if not found
        """
        cache_key = self._generate_cache_key(url, params)

        with self.lock:
            self.stats["total_requests"] += 1

            if cache_key in self.cache:
                self.stats["hits"] += 1
                data, timestamp = self.cache[cache_key]
                age = time.time() - timestamp
                logger.debug(f"Cache hit for {url[:50]}... (age: {age:.1f}s)")
                return data, timestamp
            else:
                self.stats["misses"] += 1
                logger.debug(f"Cache miss for {url[:50]}...")
                return None

    def set(self, url: str, data: Any, params: Optional[Dict] = None) -> None:
        """Store item in cache with current timestamp"""
        cache_key = self._generate_cache_key(url, params)

        with self.lock:
            # Check if we're replacing an existing item
            was_full = len(self.cache) >= self.cache.maxsize

            self.cache[cache_key] = (data, time.time())

            # Track evictions
            if was_full and cache_key not in self.cache:
                self.stats["evictions"] += 1

            self.stats["cache_size"] = len(self.cache)
            logger.debug(f"Cached data for {url[:50]}... (size: {len(str(data))} bytes)")

    def invalidate(self, url: str, params: Optional[Dict] = None) -> bool:
        """Remove specific item from cache"""
        cache_key = self._generate_cache_key(url, params)

        with self.lock:
            if cache_key in self.cache:
                del self.cache[cache_key]
                self.stats["cache_size"] = len(self.cache)
                logger.info(f"Invalidated cache for {url[:50]}...")
                return True
            return False

    def clear(self) -> int:
        """Clear all cached items"""
        with self.lock:
            count = len(self.cache)
            self.cache.clear()
            self.stats["cache_size"] = 0
            logger.info(f"Cleared {count} items from cache")
            return count

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self.lock:
            self.stats["cache_size"] = len(self.cache)
            hit_rate = (self.stats["hits"] / self.stats["total_requests"] * 100) if self.stats["total_requests"] > 0 else 0

            return {
                **self.stats,
                "hit_rate": f"{hit_rate:.2f}%",
                "max_size": self.cache.maxsize,
                "ttl_seconds": self.ttl
            }

    def get_cached_urls(self) -> list:
        """Get list of all cached URLs"""
        with self.lock:
            cached_items = []
            for key in self.cache:
                data, timestamp = self.cache[key]
                age = time.time() - timestamp
                cached_items.append({
                    "key": key,
                    "age_seconds": round(age, 2),
                    "expires_in": round(self.ttl - age, 2)
                })
            return cached_items

    def is_expired(self, url: str, params: Optional[Dict] = None) -> bool:
        """Check if a cached item is expired"""
        cache_key = self._generate_cache_key(url, params)

        with self.lock:
            if cache_key in self.cache:
                _, timestamp = self.cache[cache_key]
                age = time.time() - timestamp
                return age >= self.ttl
            return True

# Global cache instance (will be initialized in main app)
cache_manager: Optional[CacheManager] = None

def initialize_cache(max_size: int, ttl: int) -> CacheManager:
    """Initialize the global cache manager"""
    global cache_manager
    cache_manager = CacheManager(max_size=max_size, ttl=ttl)
    return cache_manager

def get_cache_manager() -> Optional[CacheManager]:
    """Get the global cache manager instance"""
    return cache_manager