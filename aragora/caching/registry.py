"""
Unified caching infrastructure for Aragora.

This module provides a single entry point for all caching needs, with a common
protocol that all cache backends implement.

Usage:
    from aragora.caching import (
        # Protocol and types
        CacheBackend,
        CacheStats,
        # Implementations
        TTLCache,
        RedisTTLCache,
        HybridTTLCache,
        # Decorators
        cached,
        async_cached,
        lru_cache_with_ttl,
        cached_property_ttl,
        # Registry
        get_cache,
        register_cache,
        get_all_cache_stats,
        # Global caches
        get_method_cache,
        get_query_cache,
        # Utilities
        invalidate_cache,
        clear_all_caches,
    )

    # Using the cached decorator
    @cached(ttl_seconds=300, key_prefix="users")
    def get_user(user_id: str) -> dict:
        return expensive_lookup(user_id)

    # Using a specific cache instance
    cache = TTLCache(maxsize=1000, ttl_seconds=600)
    cache.set("key", {"data": "value"})
    result = cache.get("key")

    # Using the cache registry
    register_cache("users", cache)
    stats = get_all_cache_stats()

Cache Implementations:
    - TTLCache: In-memory LRU cache with TTL expiry (thread-safe)
    - RedisTTLCache: Redis-backed cache with in-memory fallback
    - HybridTTLCache: Factory that returns best available cache
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable

logger = logging.getLogger(__name__)

T = TypeVar("T")

# =============================================================================
# Cache Protocol
# =============================================================================


@dataclass
class CacheStats:
    """Statistics for a cache instance."""

    size: int
    maxsize: int
    ttl_seconds: float
    hits: int
    misses: int
    hit_rate: float
    extra: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CacheStats:
        """Create CacheStats from a dictionary."""
        return cls(
            size=d.get("size", 0),
            maxsize=d.get("maxsize", 0),
            ttl_seconds=d.get("ttl_seconds", 0),
            hits=d.get("hits", 0),
            misses=d.get("misses", 0),
            hit_rate=d.get("hit_rate", 0.0),
            extra={
                k: v
                for k, v in d.items()
                if k not in {"size", "maxsize", "ttl_seconds", "hits", "misses", "hit_rate"}
            }
            or None,
        )


@runtime_checkable
class CacheBackend(Protocol[T]):
    """Protocol defining the interface for cache backends.

    All cache implementations should conform to this protocol to ensure
    consistent behavior across the codebase.
    """

    def get(self, key: str) -> T | None:
        """Get a value from cache if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        ...

    def set(self, key: str, value: T) -> None:
        """Store a value in cache.

        Args:
            key: Cache key
            value: Value to store
        """
        ...

    def invalidate(self, key: str) -> bool:
        """Invalidate a specific key.

        Args:
            key: Cache key to invalidate

        Returns:
            True if key was found and removed
        """
        ...

    def clear(self) -> int:
        """Clear all entries.

        Returns:
            Number of entries cleared
        """
        ...

    def clear_prefix(self, prefix: str) -> int:
        """Clear entries with keys starting with prefix.

        Args:
            prefix: Key prefix to match

        Returns:
            Number of entries cleared
        """
        ...

    @property
    def stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with size, maxsize, ttl_seconds, hits, misses, hit_rate
        """
        ...


# =============================================================================
# Cache Registry
# =============================================================================

_cache_registry: dict[str, CacheBackend] = {}
_registry_lock = threading.Lock()


def register_cache(name: str, cache: CacheBackend) -> None:
    """Register a cache instance in the global registry.

    Args:
        name: Unique name for the cache
        cache: Cache instance implementing CacheBackend
    """
    with _registry_lock:
        _cache_registry[name] = cache
        logger.debug("Registered cache: %s", name)


def get_cache(name: str) -> CacheBackend | None:
    """Get a cache instance from the registry.

    Args:
        name: Name of the cache to retrieve

    Returns:
        Cache instance or None if not found
    """
    with _registry_lock:
        return _cache_registry.get(name)


def get_all_cache_stats() -> dict[str, CacheStats]:
    """Get statistics for all registered caches.

    The values are ``aragora.caching.registry.CacheStats``, which is a different
    class from the decorator-layer ``aragora.caching.CacheStats`` re-exported
    beside this function, so ``isinstance`` checks against the package-level name
    always fail. See the ``aragora.caching`` package docstring.

    Returns:
        Dictionary mapping cache names to their statistics
    """
    with _registry_lock:
        result = {}
        for name, cache in _cache_registry.items():
            try:
                stats_dict = cache.stats
                result[name] = CacheStats.from_dict(stats_dict)
            except (AttributeError, KeyError, TypeError, ValueError) as e:
                logger.warning("Failed to get stats for cache %s: %s", name, e)
        return result


def list_caches() -> list[str]:
    """List all registered cache names.

    Returns:
        List of cache names
    """
    with _registry_lock:
        return list(_cache_registry.keys())


# =============================================================================
# Auto-register global caches
# =============================================================================

from aragora.utils.cache import get_method_cache, get_query_cache


def _auto_register_global_caches() -> None:
    """Auto-register the global caches from utils.cache."""
    try:
        register_cache("method", get_method_cache())
        register_cache("query", get_query_cache())
    except (ImportError, AttributeError, RuntimeError) as e:
        logger.debug("Failed to auto-register global caches: %s", e)


# Register on import
_auto_register_global_caches()


# =============================================================================
# Cache Key Utilities
# =============================================================================


def make_cache_key(*parts: str, separator: str = ":", max_length: int = 250) -> str:
    """Generate a collision-safe cache key from multiple parts.

    This function creates cache keys that are:
    - Properly namespaced using the separator
    - Safe for use with Redis (no spaces, limited length)
    - Deterministic (same inputs always produce same output)

    Args:
        *parts: Components of the cache key (e.g., "users", user_id, "profile")
        separator: Character to join parts (default ":")
        max_length: Maximum key length (default 250, safe for Redis)

    Returns:
        A safe cache key string

    Example:
        >>> make_cache_key("users", user_id, "profile")
        "users:abc123:profile"

        >>> make_cache_key("search", very_long_query)  # Auto-hashes if too long
        "search:sha256_abc123..."
    """
    import hashlib

    # Filter out empty parts and convert to strings
    clean_parts = [str(p).strip() for p in parts if p is not None and str(p).strip()]

    if not clean_parts:
        raise ValueError("At least one non-empty cache key part is required")

    # Replace problematic characters (spaces, newlines)
    clean_parts = [p.replace(" ", "_").replace("\n", "_") for p in clean_parts]

    key = separator.join(clean_parts)

    # If key is too long, hash the variable parts
    if len(key) > max_length:
        # Keep prefix for debugging, hash the rest
        prefix = clean_parts[0][:50] if clean_parts else ""
        content_hash = hashlib.sha256(key.encode()).hexdigest()[:32]
        key = f"{prefix}{separator}hash_{content_hash}"

    return key


def make_content_hash(content: str, length: int = 16) -> str:
    """Generate a short hash for content-based cache keys.

    Uses SHA-256 (not MD5) for better collision resistance, even when truncated.
    For a 16-character hex hash (64 bits), collision probability is ~1 in 2^32
    after 2^32 items (birthday paradox).

    Args:
        content: Content to hash
        length: Length of hash to return (default 16, max 64)

    Returns:
        Hexadecimal hash string

    Example:
        >>> make_content_hash("some long document text")
        "a1b2c3d4e5f67890"
    """
    import hashlib

    if length < 8:
        raise ValueError("Hash length must be at least 8 for reasonable collision resistance")
    if length > 64:
        length = 64

    return hashlib.sha256(content.encode()).hexdigest()[:length]


__all__ = [
    "CacheBackend",
    "CacheStats",
    "register_cache",
    "get_cache",
    "get_all_cache_stats",
    "list_caches",
    "make_cache_key",
    "make_content_hash",
]
