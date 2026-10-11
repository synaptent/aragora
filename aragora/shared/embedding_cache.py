"""LRU cache for text embeddings with optional persistence.

This module provides EmbeddingCache, which caches embeddings at the text
level to avoid redundant model.encode() calls.

Performance impact:
    - Without cache: O(n²) encode calls for n texts
    - With cache: O(n) encode calls (amortized)
    - Expected speedup: 10-100x for repeated text comparisons

Note: For generic caching with TTL expiry, see aragora.utils.cache.TTLCache.
EmbeddingCache is specialized for numpy arrays with database persistence
and does not use TTL (embeddings don't expire).

MIGRATION NOTE:
    New code should use aragora.core.embeddings for embedding operations.
    This module remains for numpy-specific caching in convergence detection.

Persistence:
    This module sits in the foundation layer and does not know where the
    embeddings database lives. A persistent cache created without an explicit
    ``db_path`` asks the resolver installed with
    :func:`register_default_db_path_resolver`; the debate cache package
    (``aragora.debate.cache``) installs one that points at the persistence
    database. Without a resolver such a request raises ``RuntimeError``.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore[assignment]  # Necessary: np typed as module but None when unavailable; guarded by HAS_NUMPY
    HAS_NUMPY = False

logger = logging.getLogger(__name__)


def _require_numpy(operation: str) -> None:
    """Raise ImportError with helpful message if numpy is not available."""
    if not HAS_NUMPY:
        raise ImportError(f"numpy is required for {operation}. Install with: pip install numpy")


_default_db_path_resolver: Callable[[], str] | None = None


def register_default_db_path_resolver(resolver: Callable[[], str]) -> None:
    """Install the callable that returns the default embeddings database path.

    It is used when a persistent cache is requested without ``db_path``. A new
    registration replaces the previous one.
    """
    global _default_db_path_resolver
    _default_db_path_resolver = resolver


def _resolve_default_db_path() -> str:
    resolver = _default_db_path_resolver
    if resolver is None:
        raise RuntimeError(
            "No default embeddings database path resolver is registered. Pass "
            "db_path explicitly, or import aragora.debate.cache, which registers "
            "the persistence database path."
        )
    return resolver()


class EmbeddingCache:
    """
    LRU cache for text embeddings with optional persistence.

    Caches embeddings at the text level, so the same text encoded in
    different pairs only requires one model.encode() call.

    Performance impact:
        - Without cache: O(n²) encode calls for n texts
        - With cache: O(n) encode calls (amortized)
        - Expected speedup: 10-100x for repeated text comparisons
    """

    def __init__(
        self,
        max_size: int = 1024,
        persist: bool = False,
        db_path: str | None = None,
    ):
        """
        Initialize embedding cache.

        Args:
            max_size: Maximum entries in memory cache (default 1024)
            persist: Whether to persist to database (default False)
            db_path: Path to embeddings database (uses core.db if None)

        Raises:
            ImportError: If numpy is not installed
        """
        _require_numpy("EmbeddingCache")
        self.max_size = max_size
        self.persist = persist
        self.db_path = db_path
        # Use OrderedDict for O(1) LRU operations (vs O(n) with list)
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def _hash_text(self, text: str) -> str:
        """Generate hash key for text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]

    def get(self, text: str) -> np.ndarray | None:
        """Get embedding from cache."""
        key = self._hash_text(text)

        with self._lock:
            if key in self._cache:
                self._hits += 1
                # Move to end for LRU (O(1) with OrderedDict)
                self._cache.move_to_end(key)
                return self._cache[key]

        # Try persistent cache
        if self.persist:
            embedding = self._load_from_db(key)
            if embedding is not None:
                self._hits += 1
                with self._lock:
                    self._store_in_memory(key, embedding)
                return embedding

        self._misses += 1
        return None

    def put(self, text: str, embedding: np.ndarray) -> None:
        """Store embedding in cache."""
        key = self._hash_text(text)

        with self._lock:
            self._store_in_memory(key, embedding)

        if self.persist:
            self._save_to_db(key, text[:1000], embedding)  # Truncate text

    def _store_in_memory(self, key: str, embedding: np.ndarray) -> None:
        """Store in memory cache with LRU eviction."""
        # Evict oldest entries if at capacity (O(1) with OrderedDict.popitem)
        while len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)

        # If key exists, move to end; otherwise add at end
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = embedding

    def _load_from_db(self, key: str) -> np.ndarray | None:
        """Load embedding from database."""
        if not self.db_path:
            return None

        try:
            import sqlite3

            conn = sqlite3.connect(self.db_path, timeout=10.0)
            cursor = conn.execute("SELECT embedding FROM embeddings WHERE text_hash = ?", (key,))
            row = cursor.fetchone()
            conn.close()

            if row and row[0]:
                return np.frombuffer(row[0], dtype=np.float32)
        except (OSError, sqlite3.Error) as e:
            # Expected: DB file issues, permissions, OperationalError
            logger.debug("Failed to load embedding from DB: %s", e)
        except (RuntimeError, ValueError, TypeError, AttributeError, KeyError) as e:
            # Unexpected: log at warning for visibility
            logger.warning("Unexpected error loading embedding: %s: %s", type(e).__name__, e)

        return None

    def _save_to_db(self, key: str, text: str, embedding: np.ndarray) -> None:
        """Save embedding to database."""
        if not self.db_path:
            return

        try:
            import sqlite3
            import uuid

            conn = sqlite3.connect(self.db_path, timeout=10.0)
            conn.execute(
                """
                INSERT OR REPLACE INTO embeddings (id, text_hash, text, embedding, provider, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    str(uuid.uuid4()),
                    key,
                    text,
                    embedding.astype(np.float32).tobytes(),
                    "sentence-transformer",
                ),
            )
            conn.commit()
            conn.close()
        except (OSError, sqlite3.Error) as e:
            # Expected: DB file issues, disk full, permissions, OperationalError
            logger.debug("Failed to save embedding to DB: %s", e)
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            # Unexpected: log at warning for visibility
            logger.warning("Unexpected error saving embedding: %s: %s", type(e).__name__, e)

    def get_stats(self) -> dict:
        """Get cache statistics."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
            "size": len(self._cache),
            "max_size": self.max_size,
        }

    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0


class EmbeddingCacheManager:
    """
    Manager for per-debate embedding caches.

    Prevents cross-debate contamination by providing isolated caches
    for each debate_id. This fixes topic mixing caused by shared
    convergence detection embeddings.
    """

    def __init__(self):
        self._caches: dict[str, EmbeddingCache] = {}
        self._lock = threading.Lock()
        self._default_max_size = 1024
        self._default_persist = False
        self._default_db_path: str | None = None

    def configure(
        self,
        max_size: int = 1024,
        persist: bool = False,
        db_path: str | None = None,
    ) -> None:
        """Configure default settings for new caches."""
        with self._lock:
            self._default_max_size = max_size
            self._default_persist = persist
            self._default_db_path = db_path

    def get_cache(self, debate_id: str) -> EmbeddingCache:
        """
        Get or create cache for a specific debate.

        Args:
            debate_id: Unique identifier for the debate

        Returns:
            EmbeddingCache instance isolated to this debate
        """
        with self._lock:
            if debate_id not in self._caches:
                db_path = self._default_db_path
                if self._default_persist and db_path is None:
                    db_path = _resolve_default_db_path()

                self._caches[debate_id] = EmbeddingCache(
                    max_size=self._default_max_size,
                    persist=self._default_persist,
                    db_path=db_path,
                )
                logger.debug("Created new embedding cache for debate %s", debate_id)

            return self._caches[debate_id]

    def cleanup(self, debate_id: str) -> None:
        """
        Remove and clear cache for a completed debate.

        Should be called when a debate ends to free memory.

        Args:
            debate_id: Debate ID to cleanup
        """
        with self._lock:
            if debate_id in self._caches:
                self._caches[debate_id].clear()
                del self._caches[debate_id]
                logger.debug("Cleaned up embedding cache for debate %s", debate_id)

    def get_stats(self) -> dict:
        """Get statistics for all active caches."""
        with self._lock:
            return {
                "active_debates": len(self._caches),
                "debates": {
                    debate_id: cache.get_stats() for debate_id, cache in self._caches.items()
                },
            }

    def clear_all(self) -> None:
        """Clear all caches (for testing)."""
        with self._lock:
            for cache in self._caches.values():
                cache.clear()
            self._caches.clear()


# Global cache manager instance
_cache_manager = EmbeddingCacheManager()

# Legacy: Global embedding cache instance (deprecated, use get_scoped_embedding_cache)
_embedding_cache: EmbeddingCache | None = None
_embedding_cache_lock = threading.Lock()


def get_scoped_embedding_cache(debate_id: str) -> EmbeddingCache:
    """
    Get embedding cache scoped to a specific debate.

    This is the preferred method for getting caches in debate context.
    It prevents cross-debate contamination.

    Args:
        debate_id: Unique identifier for the debate

    Returns:
        EmbeddingCache instance isolated to this debate
    """
    return _cache_manager.get_cache(debate_id)


def cleanup_embedding_cache(debate_id: str) -> None:
    """
    Cleanup embedding cache for a completed debate.

    Should be called when a debate ends.

    Args:
        debate_id: Debate ID to cleanup
    """
    _cache_manager.cleanup(debate_id)


def get_embedding_cache(
    max_size: int = 1024,
    persist: bool = False,
    db_path: str | None = None,
) -> EmbeddingCache:
    """
    Get or create global embedding cache.

    DEPRECATED: Use get_scoped_embedding_cache(debate_id) instead.
    This function exists for backward compatibility.

    Args:
        max_size: Maximum cache entries
        persist: Enable database persistence
        db_path: Database path for persistence

    Returns:
        EmbeddingCache instance
    """
    global _embedding_cache

    with _embedding_cache_lock:
        if _embedding_cache is None:
            if persist and db_path is None:
                db_path = _resolve_default_db_path()

            _embedding_cache = EmbeddingCache(
                max_size=max_size,
                persist=persist,
                db_path=db_path,
            )
            logger.warning(
                "Using global embedding cache. For debate context, "
                "use get_scoped_embedding_cache(debate_id) to prevent contamination.",
                extra={
                    "triage_diag_code": "global_embedding_cache",
                    "triage_diag_severity": "diagnostic",
                },
            )

        return _embedding_cache


def reset_embedding_cache() -> None:
    """Reset the global embedding cache (for testing)."""
    global _embedding_cache
    with _embedding_cache_lock:
        if _embedding_cache is not None:
            _embedding_cache.clear()
        _embedding_cache = None
    # Also clear manager caches
    _cache_manager.clear_all()


__all__ = [
    "EmbeddingCache",
    "EmbeddingCacheManager",
    "get_embedding_cache",
    "get_scoped_embedding_cache",
    "cleanup_embedding_cache",
    "reset_embedding_cache",
    "register_default_db_path_resolver",
]
