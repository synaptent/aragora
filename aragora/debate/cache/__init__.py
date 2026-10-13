"""Cache utilities for debate module."""

from aragora.debate.cache.embeddings_lru import (
    EmbeddingCache,
    get_embedding_cache,
    reset_embedding_cache,
)
from aragora.persistence.db_config import DatabaseType, get_db_path_str
from aragora.shared.embedding_cache import register_default_db_path_resolver


def _embeddings_db_path() -> str:
    return get_db_path_str(DatabaseType.EMBEDDINGS)


register_default_db_path_resolver(_embeddings_db_path)

__all__ = [
    "EmbeddingCache",
    "get_embedding_cache",
    "reset_embedding_cache",
]
