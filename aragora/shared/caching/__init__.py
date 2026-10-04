"""
Shared caching utilities.

This module provides access to caching utilities from a central location.

Available caches:
- TTLCache: Generic LRU cache with TTL expiry (from aragora.utils.cache)
- EmbeddingCache: Specialized cache for numpy embeddings (from aragora.shared.embedding_cache)

For general-purpose caching, use TTLCache:
    from aragora.shared.caching import TTLCache
    cache = TTLCache[str](maxsize=100, ttl_seconds=300)

For embedding-specific caching with persistence:
    from aragora.shared.caching import EmbeddingCache
    cache = EmbeddingCache(max_size=1024, persist=True)
"""

# Re-export from canonical locations
from aragora.utils.cache import TTLCache, lru_cache_with_ttl, ttl_cache, async_ttl_cache
from aragora.shared.embedding_cache import (
    EmbeddingCache,
    EmbeddingCacheManager,
    get_scoped_embedding_cache,
    cleanup_embedding_cache,
)

__all__ = [
    # Generic caching
    "TTLCache",
    "lru_cache_with_ttl",
    "ttl_cache",
    "async_ttl_cache",
    # Embedding-specific
    "EmbeddingCache",
    "EmbeddingCacheManager",
    "get_scoped_embedding_cache",
    "cleanup_embedding_cache",
]
