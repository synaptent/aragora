"""
Shared caching utilities.

This module provides access to caching utilities from a central location.

Available caches:
- TTLCache: Generic LRU cache with TTL expiry (from aragora.utils.cache)
- EmbeddingCache: Specialized cache for numpy embeddings (from aragora.shared.embedding_cache)

For general-purpose caching, use TTLCache:
    from aragora.shared.caching import TTLCache
    cache = TTLCache[str](maxsize=100, ttl_seconds=300)

For embedding-specific caching with persistence, pass the database path:
    from aragora.shared.caching import EmbeddingCache
    cache = EmbeddingCache(max_size=1024, persist=True, db_path=path)

A persistent manager or global cache requested without ``db_path`` uses the
resolver registered by ``aragora.debate.cache`` (the persistence embeddings
database) and raises ``RuntimeError`` when that package has not been imported;
this package never imports the debate or persistence layers itself.
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
