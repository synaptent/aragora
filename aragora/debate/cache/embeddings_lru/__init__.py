"""Debate-layer import path for the embedding cache.

The implementation lives in :mod:`aragora.shared.embedding_cache`; this module
re-exports the same objects, so both paths share one cache and one manager.
Importing it through :mod:`aragora.debate.cache` also registers the persistence
database as the default location for persistent caches.
"""

from __future__ import annotations

from aragora.shared.embedding_cache import (
    EmbeddingCache,
    EmbeddingCacheManager,
    cleanup_embedding_cache,
    get_embedding_cache,
    get_scoped_embedding_cache,
    reset_embedding_cache,
)

__all__ = [
    "EmbeddingCache",
    "EmbeddingCacheManager",
    "get_embedding_cache",
    "get_scoped_embedding_cache",
    "cleanup_embedding_cache",
    "reset_embedding_cache",
]
