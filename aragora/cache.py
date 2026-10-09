"""Deprecated import location for Aragora's caching substrate.

The unified caching implementation now lives under :mod:`aragora.caching`.
Importing from ``aragora.cache`` still works but is deprecated. Migrate to the
matching ``aragora.caching`` submodules. In particular, replace ``cached`` with
``aragora.caching.ttl.ttl_cache`` and ``async_cached`` with
``aragora.caching.ttl.async_ttl_cache``. Other legacy names retain their names
under ``aragora.caching.ttl`` (TTL primitives), ``aragora.caching.registry``
(cache registry APIs), or ``aragora.caching.redis`` (Redis-backed caches).

Note: the top-level ``aragora.caching`` names ``cached`` / ``async_cached`` /
``CacheStats`` / ``clear_all_caches`` are the decorator-layer API and are *not*
drop-in replacements for the same names re-exported here (which preserve the
historical ``aragora.cache`` behaviour). Import from the submodules above to
migrate safely.
"""

from __future__ import annotations

import warnings

from aragora.caching.redis import HybridTTLCache, RedisTTLCache
from aragora.caching.registry import (
    CacheBackend,
    CacheStats,
    get_all_cache_stats,
    get_cache,
    list_caches,
    make_cache_key,
    make_content_hash,
    register_cache,
)
from aragora.caching.ttl import (
    TTLCache,
    async_ttl_cache as async_cached,
    cached_property_ttl,
    clear_all_caches,
    get_cache_stats,
    get_method_cache,
    get_query_cache,
    invalidate_cache,
    invalidate_method_cache,
    lru_cache_with_ttl,
    ttl_cache as cached,
)

warnings.warn(
    "aragora.cache is deprecated; replace cached with "
    "aragora.caching.ttl.ttl_cache and async_cached with "
    "aragora.caching.ttl.async_ttl_cache. Import other legacy names from their "
    "matching submodules: aragora.caching.ttl.TTLCache and "
    "aragora.caching.ttl.clear_all_caches, aragora.caching.registry.get_cache and "
    "aragora.caching.registry.CacheStats, or aragora.caching.redis.RedisTTLCache "
    "and aragora.caching.redis.HybridTTLCache. The aragora.caching top-level "
    "cached, async_cached, CacheStats, and clear_all_caches names are the "
    "decorator-layer API and are not drop-in replacements for these legacy "
    "names.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "CacheBackend",
    "CacheStats",
    "TTLCache",
    "RedisTTLCache",
    "HybridTTLCache",
    "cached",
    "async_cached",
    "lru_cache_with_ttl",
    "cached_property_ttl",
    "register_cache",
    "get_cache",
    "get_all_cache_stats",
    "list_caches",
    "get_method_cache",
    "get_query_cache",
    "get_cache_stats",
    "invalidate_cache",
    "invalidate_method_cache",
    "clear_all_caches",
    "make_cache_key",
    "make_content_hash",
]
