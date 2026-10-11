"""
Request-Scoped Query Cache for Knowledge Mound.

Provides caching of query results within a single request lifecycle
to avoid repeated identical queries (common in permission checks, node lookups).

Usage:
    from aragora.knowledge.mound.query_cache import (
        RequestScopedCache,
        request_cache_context,
        get_or_compute,
    )

    # As context manager
    with request_cache_context():
        # All queries within this block use the cache
        node1 = get_or_compute("node:123", lambda: db.get_node("123"))
        node2 = get_or_compute("node:123", lambda: db.get_node("123"))  # Cache hit
        assert node1 is node2

    # Manual usage
    cache = RequestScopedCache()
    with cache:
        result = cache.get_or_compute("key", expensive_computation)

Configuration:
    ARAGORA_QUERY_CACHE_ENABLED: bool (default: true)
    ARAGORA_QUERY_CACHE_MAX_SIZE: int (default: 1000)
"""

from __future__ import annotations

import contextvars
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar
from collections.abc import Callable, Generator

logger = logging.getLogger(__name__)

# Configuration
CACHE_ENABLED = os.environ.get("ARAGORA_QUERY_CACHE_ENABLED", "true").lower() == "true"
CACHE_MAX_SIZE = int(os.environ.get("ARAGORA_QUERY_CACHE_MAX_SIZE", "1000"))

# Context variable for request-scoped cache
_cache_context: contextvars.ContextVar[RequestScopedCache | None] = contextvars.ContextVar(
    "request_cache", default=None
)

T = TypeVar("T")


@dataclass
class CacheStats:
    """Statistics for cache usage."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    compute_time_ms: float = 0.0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": round(self.hit_rate, 4),
            "compute_time_ms": round(self.compute_time_ms, 2),
        }


@dataclass
class CacheEntry:
    """A single cache entry."""

    value: Any
    created_at: float = field(default_factory=time.time)
    access_count: int = 0


class RequestScopedCache:
    """
    Request-scoped cache for query results.

    Caches computation results within a single request/context to avoid
    repeated identical queries. Automatically cleared when the context exits.

    Thread-safe via contextvars (each async task gets its own cache).
    """

    def __init__(
        self,
        max_size: int | None = None,
        enabled: bool | None = None,
    ):
        """
        Initialize the request-scoped cache.

        Args:
            max_size: Maximum number of entries (default from env)
            enabled: Whether caching is enabled (default from env)
        """
        self.max_size = max_size or CACHE_MAX_SIZE
        self.enabled = enabled if enabled is not None else CACHE_ENABLED
        self._cache: dict[str, CacheEntry] = {}
        self._stats = CacheStats()
        self._token: contextvars.Token | None = None

    def get(self, key: str) -> Any | None:
        """
        Get a value from the cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        if not self.enabled:
            return None

        entry = self._cache.get(key)
        if entry is not None:
            entry.access_count += 1
            self._stats.hits += 1
            return entry.value

        self._stats.misses += 1
        return None

    def set(self, key: str, value: Any) -> None:
        """
        Set a value in the cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        if not self.enabled:
            return

        # Evict if at capacity
        if len(self._cache) >= self.max_size:
            self._evict_lru()

        self._cache[key] = CacheEntry(value=value)

    def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], T],
        skip_cache: bool = False,
    ) -> T:
        """
        Get a cached value or compute and cache it.

        Args:
            key: Cache key
            compute_fn: Function to compute the value if not cached
            skip_cache: If True, always compute (but still cache result)

        Returns:
            Cached or newly computed value
        """
        if not self.enabled or skip_cache:
            start = time.time()
            result = compute_fn()
            self._stats.compute_time_ms += (time.time() - start) * 1000
            if self.enabled:
                self.set(key, result)
            return result

        # Check cache first
        entry = self._cache.get(key)
        if entry is not None:
            entry.access_count += 1
            self._stats.hits += 1
            return entry.value

        # Compute and cache
        self._stats.misses += 1
        start = time.time()
        result = compute_fn()
        self._stats.compute_time_ms += (time.time() - start) * 1000

        # Evict if at capacity
        if len(self._cache) >= self.max_size:
            self._evict_lru()

        self._cache[key] = CacheEntry(value=result)
        return result

    async def get_or_compute_async(
        self,
        key: str,
        compute_fn: Callable[[], Any],
        skip_cache: bool = False,
    ) -> Any:
        """
        Async version of get_or_compute.

        Args:
            key: Cache key
            compute_fn: Async function to compute the value if not cached
            skip_cache: If True, always compute (but still cache result)

        Returns:
            Cached or newly computed value
        """

        if not self.enabled or skip_cache:
            start = time.time()
            result = await compute_fn()
            self._stats.compute_time_ms += (time.time() - start) * 1000
            if self.enabled:
                self.set(key, result)
            return result

        # Check cache first
        entry = self._cache.get(key)
        if entry is not None:
            entry.access_count += 1
            self._stats.hits += 1
            return entry.value

        # Compute and cache
        self._stats.misses += 1
        start = time.time()
        result = await compute_fn()
        self._stats.compute_time_ms += (time.time() - start) * 1000

        # Evict if at capacity
        if len(self._cache) >= self.max_size:
            self._evict_lru()

        self._cache[key] = CacheEntry(value=result)
        return result

    def _evict_lru(self) -> None:
        """Evict the least recently used entry."""
        if not self._cache:
            return

        # Find entry with lowest access count (simple LRU approximation)
        min_key = min(self._cache.keys(), key=lambda k: self._cache[k].access_count)
        del self._cache[min_key]
        self._stats.evictions += 1

    def invalidate(self, key: str) -> bool:
        """
        Invalidate a specific cache entry.

        Args:
            key: Cache key to invalidate

        Returns:
            True if entry was found and removed
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def invalidate_prefix(self, prefix: str) -> int:
        """
        Invalidate all entries with a given key prefix.

        Args:
            prefix: Key prefix to match

        Returns:
            Number of entries invalidated
        """
        keys_to_remove = [k for k in self._cache.keys() if k.startswith(prefix)]
        for key in keys_to_remove:
            del self._cache[key]
        return len(keys_to_remove)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._stats

    @property
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)

    def __enter__(self) -> RequestScopedCache:
        """Enter the cache context."""
        self._token = _cache_context.set(self)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the cache context and clear the cache."""
        if self._token is not None:
            _cache_context.reset(self._token)
            self._token = None

        # Log stats if significant cache usage
        if self._stats.hits + self._stats.misses > 10:
            logger.debug(
                "Request cache stats: %s hits, %s misses, %.1f%% hit rate, %.1fms compute time",
                self._stats.hits,
                self._stats.misses,
                self._stats.hit_rate * 100,
                self._stats.compute_time_ms,
            )

        self.clear()


# =============================================================================
# Global Access Functions
# =============================================================================


def get_current_cache() -> RequestScopedCache | None:
    """Get the current request-scoped cache, if any."""
    return _cache_context.get()


def get_or_compute(key: str, compute_fn: Callable[[], T], skip_cache: bool = False) -> T:
    """
    Get a cached value or compute and cache it using the current cache.

    If no cache context is active, computes directly without caching.

    Args:
        key: Cache key
        compute_fn: Function to compute the value
        skip_cache: If True, always compute

    Returns:
        Cached or computed value
    """
    cache = get_current_cache()
    if cache is not None:
        return cache.get_or_compute(key, compute_fn, skip_cache)
    return compute_fn()


async def get_or_compute_async(
    key: str,
    compute_fn: Callable[[], Any],
    skip_cache: bool = False,
) -> Any:
    """
    Async version of get_or_compute.

    If no cache context is active, computes directly without caching.
    """
    cache = get_current_cache()
    if cache is not None:
        return await cache.get_or_compute_async(key, compute_fn, skip_cache)
    return await compute_fn()


@contextmanager
def request_cache_context(
    max_size: int | None = None,
    enabled: bool | None = None,
) -> Generator[RequestScopedCache, None, None]:
    """
    Context manager for request-scoped caching.

    Args:
        max_size: Maximum cache entries
        enabled: Whether caching is enabled

    Yields:
        RequestScopedCache instance
    """
    cache = RequestScopedCache(max_size=max_size, enabled=enabled)
    with cache:
        yield cache


# =============================================================================
# Cache Key Builders
# =============================================================================


def node_key(node_id: str) -> str:
    """Build cache key for a node lookup."""
    return f"node:{node_id}"


def permission_key(item_id: str, grantee_id: str, permission: str) -> str:
    """Build cache key for a permission check."""
    return f"perm:{item_id}:{grantee_id}:{permission}"


def relationship_key(from_node: str, to_node: str) -> str:
    """Build cache key for a relationship lookup."""
    return f"rel:{from_node}:{to_node}"


def workspace_nodes_key(workspace_id: str, node_type: str | None = None) -> str:
    """Build cache key for workspace nodes query."""
    if node_type:
        return f"ws_nodes:{workspace_id}:{node_type}"
    return f"ws_nodes:{workspace_id}"


__all__ = [
    # Core classes
    "RequestScopedCache",
    "CacheStats",
    "CacheEntry",
    # Global functions
    "get_current_cache",
    "get_or_compute",
    "get_or_compute_async",
    "request_cache_context",
    # Key builders
    "node_key",
    "permission_key",
    "relationship_key",
    "workspace_nodes_key",
    # Configuration
    "CACHE_ENABLED",
    "CACHE_MAX_SIZE",
]
