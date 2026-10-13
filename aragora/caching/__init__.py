"""
Aragora Caching Module

Provides decorators for caching function results with TTL-based expiration,
LRU eviction, and async compatibility.

Usage:
    from aragora.caching import cached, async_cached, memoize, cache_key

    @cached(ttl_seconds=300, maxsize=128)
    def expensive_computation(x: int) -> int:
        return x * x

    @async_cached(ttl_seconds=60)
    async def fetch_data(url: str) -> dict:
        ...

    @memoize
    def pure_function(n: int) -> int:
        return fibonacci(n)

    @cache_key("user_id", "action")
    @cached(ttl_seconds=600)
    def get_user_action(user_id: int, action: str, metadata: dict) -> dict:
        ...

Two intentionally-distinct CacheStats APIs:
    This package exposes more than one ``CacheStats`` dataclass and they are not
    interchangeable:

    - ``aragora.caching.CacheStats`` is the decorator-layer class from
      ``aragora.caching.decorators``: fields ``hits``, ``misses``, ``size``,
      ``maxsize``, ``evictions``, with ``hit_rate`` as a computed property
      returning a 0-100 percentage. ``get_global_cache_stats()`` returns these.
    - ``aragora.caching.registry.CacheStats`` is the registry/backend class:
      fields ``size``, ``maxsize``, ``ttl_seconds``, ``hits``, ``misses``,
      ``hit_rate`` and an optional ``extra`` mapping, where ``hit_rate`` is a
      plain field copied from the backend's own ``stats`` mapping (a 0.0-1.0
      fraction, not a percentage) and there is no ``evictions``.
      ``get_all_cache_stats()`` returns these, even though this package
      re-exports it right beside the decorator ``CacheStats``.
    - ``aragora.caching.adaptive.CacheStats`` is a third, separate class for
      adaptive-TTL caches.

    Because the package-level ``CacheStats`` name is bound to the decorator
    class, ``isinstance(value, CacheStats)`` applied to ``get_all_cache_stats()``
    results is always False. Import the class you mean from its own module and
    check against that instead of the package-level name. The three classes are
    pinned as distinct by
    ``tests/caching/test_consolidation_shims.py::test_distinct_cachestats_apis_preserved``;
    they must not be merged or renamed.
"""

from aragora.caching.adaptive import AccessPattern, AdaptiveTTLCache, CacheOptimizer
from aragora.caching.decorators import (
    cached,
    async_cached,
    memoize,
    cache_key,
    CacheStats,
    CacheEntry,
    get_global_cache_stats,
    clear_all_caches,
)
from aragora.caching.redis import HybridTTLCache, RedisTTLCache
from aragora.caching.registry import (
    CacheBackend,
    get_all_cache_stats,
    get_cache,
    list_caches,
    make_cache_key,
    make_content_hash,
    register_cache,
)
from aragora.caching.ttl import (
    CacheManager,
    CachePreset,
    TTLCache,
    async_ttl_cache,
    cached_property_ttl,
    get_cache_manager,
    get_cache_stats,
    get_handler_cache,
    get_method_cache,
    get_query_cache,
    invalidate_cache,
    invalidate_method_cache,
    lru_cache_with_ttl,
    ttl_cache,
)

__all__ = [
    # Decorators (function-result caching)
    "cached",
    "async_cached",
    "memoize",
    "cache_key",
    "CacheStats",
    "CacheEntry",
    "get_global_cache_stats",
    "clear_all_caches",
    # Cache registry + backend protocol
    "CacheBackend",
    "register_cache",
    "get_cache",
    "get_all_cache_stats",
    "list_caches",
    "make_cache_key",
    "make_content_hash",
    # In-memory TTL cache primitives
    "TTLCache",
    "CacheManager",
    "CachePreset",
    "ttl_cache",
    "async_ttl_cache",
    "lru_cache_with_ttl",
    "cached_property_ttl",
    "get_cache_manager",
    "get_cache_stats",
    "get_handler_cache",
    "get_method_cache",
    "get_query_cache",
    "invalidate_cache",
    "invalidate_method_cache",
    # Redis-backed cache
    "RedisTTLCache",
    "HybridTTLCache",
    # Adaptive cache
    "AdaptiveTTLCache",
    "AccessPattern",
    "CacheOptimizer",
]
