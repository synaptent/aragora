"""
Vector Index for Memory Backends.

Provides efficient similarity search using FAISS (Approximate Nearest Neighbor)
with automatic fallback to numpy brute-force when FAISS is unavailable.

Features:
- Lazy index building on first search
- Automatic index invalidation on data changes
- O(log n) search with FAISS vs O(n) brute-force fallback
- Thread-safe through asyncio locks

Usage:
    from aragora.memory.backends.vector_index import VectorIndex

    index = VectorIndex(dimension=384)
    index.add("entry_id", embedding)
    results = index.search(query_embedding, k=10, min_similarity=0.7)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, cast

logger = logging.getLogger(__name__)

# Optional numpy/faiss imports with graceful fallback
try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore[assignment]  # optional import fallback: module -> None when numpy unavailable
    HAS_NUMPY = False

try:
    import faiss

    HAS_FAISS = True
except ImportError:
    faiss = None  # type: ignore[assignment]  # optional import fallback: module -> None when faiss unavailable
    HAS_FAISS = False


@dataclass
class VectorIndexConfig:
    """Configuration for vector index behavior."""

    # Minimum entries before building FAISS index (below this, use brute-force)
    faiss_threshold: int = 100
    # Index type: "flat" (exact), "ivf" (approximate), "hnsw" (graph-based)
    index_type: str = "flat"
    # For IVF indexes: number of clusters (nlist)
    nlist: int = 100
    # For IVF indexes: number of clusters to probe (nprobe)
    nprobe: int = 10
    # Use GPU if available (requires faiss-gpu)
    use_gpu: bool = False


@dataclass
class SearchResult:
    """Result from a vector similarity search."""

    entry_id: str
    similarity: float


class VectorIndex:
    """
    Vector index for efficient similarity search in memory backends.

    Wraps FAISS for O(log n) or O(1) search complexity, with automatic
    fallback to numpy brute-force O(n) when FAISS is unavailable.

    The index is lazily built on first search and automatically invalidated
    when entries are added or removed.

    Example:
        index = VectorIndex(dimension=384)

        # Add entries
        for entry in entries:
            index.add(entry.id, entry.embedding)

        # Search (index built lazily on first search)
        results = index.search(query_embedding, k=10)

        # Results are (entry_id, similarity) tuples
        for entry_id, similarity in results:
            print(f"{entry_id}: {similarity:.3f}")
    """

    def __init__(
        self,
        dimension: int,
        config: VectorIndexConfig | None = None,
    ):
        """
        Initialize vector index.

        Args:
            dimension: Embedding dimension (e.g., 384 for MiniLM, 1536 for OpenAI)
            config: Optional configuration for index behavior
        """
        self.dimension = dimension
        self.config = config or VectorIndexConfig()

        # Storage for embeddings and IDs
        self._embeddings: dict[str, list[float]] = {}
        self._id_to_idx: dict[str, int] = {}
        self._idx_to_id: dict[int, str] = {}

        # FAISS index (built lazily)
        self._faiss_index: Any | None = None
        self._index_dirty = True

        # Lock for thread safety
        self._lock = asyncio.Lock()

    @property
    def size(self) -> int:
        """Return number of indexed entries."""
        return len(self._embeddings)

    @property
    def is_faiss_available(self) -> bool:
        """Check if FAISS is available."""
        return HAS_FAISS

    @property
    def is_using_faiss(self) -> bool:
        """Check if currently using FAISS (vs brute-force)."""
        return (
            HAS_FAISS and self._faiss_index is not None and self.size >= self.config.faiss_threshold
        )

    def add(self, entry_id: str, embedding: list[float]) -> None:
        """
        Add an entry to the index.

        If the entry already exists, its embedding is updated.

        Args:
            entry_id: Unique identifier for the entry
            embedding: Vector embedding (must match dimension)
        """
        if len(embedding) != self.dimension:
            raise ValueError(
                f"Embedding dimension {len(embedding)} != index dimension {self.dimension}"
            )

        self._embeddings[entry_id] = embedding
        self._index_dirty = True

    def remove(self, entry_id: str) -> bool:
        """
        Remove an entry from the index.

        Args:
            entry_id: The entry to remove

        Returns:
            True if entry was removed, False if not found
        """
        if entry_id not in self._embeddings:
            return False

        del self._embeddings[entry_id]
        self._index_dirty = True
        return True

    def clear(self) -> None:
        """Clear all entries from the index."""
        self._embeddings.clear()
        self._id_to_idx.clear()
        self._idx_to_id.clear()
        self._faiss_index = None
        self._index_dirty = True

    def _build_index(self) -> None:
        """
        Build or rebuild the FAISS index.

        Called automatically on first search or when index is dirty.
        """
        if not HAS_NUMPY:
            logger.warning("NumPy not available, vector search disabled")
            return

        n = len(self._embeddings)
        if n == 0:
            self._faiss_index = None
            self._index_dirty = False
            return

        # Rebuild ID mappings
        self._id_to_idx.clear()
        self._idx_to_id.clear()

        ids = list(self._embeddings.keys())
        embeddings_list = [self._embeddings[id] for id in ids]

        for idx, entry_id in enumerate(ids):
            self._id_to_idx[entry_id] = idx
            self._idx_to_id[idx] = entry_id

        # Convert to numpy array
        embeddings_array = np.array(embeddings_list, dtype=np.float32)

        # Normalize for cosine similarity
        norms = np.linalg.norm(embeddings_array, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        normalized = embeddings_array / norms

        # Build FAISS index if available and above threshold
        if HAS_FAISS and n >= self.config.faiss_threshold:
            try:
                self._faiss_index = self._create_faiss_index(normalized)
                logger.debug("Built FAISS index with %s entries", n)
            except (RuntimeError, ValueError, TypeError, OSError) as e:
                logger.warning("Failed to build FAISS index: %s, using fallback", e)
                self._faiss_index = None
        else:
            # Store normalized embeddings for brute-force search
            self._normalized_embeddings = normalized
            self._faiss_index = None

        self._index_dirty = False

    def _create_faiss_index(self, embeddings: np.ndarray) -> Any:
        """Create appropriate FAISS index based on config."""
        n = len(embeddings)

        if self.config.index_type == "flat" or n < 1000:
            # Exact search - best for smaller datasets
            index = faiss.IndexFlatIP(self.dimension)
        elif self.config.index_type == "ivf":
            # IVF index - good for medium datasets (1k-1M)
            nlist = min(self.config.nlist, n // 10)
            nlist = max(nlist, 1)
            quantizer = faiss.IndexFlatIP(self.dimension)
            index = faiss.IndexIVFFlat(quantizer, self.dimension, nlist)
            index.train(embeddings)
            index.nprobe = min(self.config.nprobe, nlist)
        else:
            # Default to flat index
            index = faiss.IndexFlatIP(self.dimension)

        # Move to GPU if requested and available
        if self.config.use_gpu and faiss.get_num_gpus() > 0:
            res = faiss.StandardGpuResources()
            index = faiss.index_cpu_to_gpu(res, 0, index)
            logger.info("FAISS index using GPU")

        # Add embeddings to index
        index.add(embeddings)

        return index

    def search(
        self,
        query_embedding: list[float],
        k: int = 10,
        min_similarity: float = 0.0,
    ) -> list[SearchResult]:
        """
        Search for similar entries.

        Args:
            query_embedding: Query vector
            k: Maximum number of results
            min_similarity: Minimum similarity threshold (0-1 for normalized)

        Returns:
            List of SearchResult with entry_id and similarity, sorted by similarity desc
        """
        if not HAS_NUMPY:
            return []

        if len(self._embeddings) == 0:
            return []

        if len(query_embedding) != self.dimension:
            raise ValueError(
                f"Query dimension {len(query_embedding)} != index dimension {self.dimension}"
            )

        # Rebuild index if dirty
        if self._index_dirty:
            self._build_index()

        # Normalize query
        query = np.array(query_embedding, dtype=np.float32)
        norm = np.linalg.norm(query)
        if norm > 0:
            query = query / norm
        query = query.reshape(1, -1)

        # Use FAISS if available
        if self._faiss_index is not None:
            return self._search_faiss(query, k, min_similarity)
        else:
            return self._search_brute_force(query, k, min_similarity)

    def _search_faiss(
        self,
        query: np.ndarray,
        k: int,
        min_similarity: float,
    ) -> list[SearchResult]:
        """Search using FAISS index."""
        k = min(k, len(self._embeddings))

        # FAISS search returns (distances, indices)
        # For IndexFlatIP, distances are inner products (cosine sim for normalized)
        distances, indices = cast(Any, self._faiss_index).search(query, k)

        results = []
        for i, (sim, idx) in enumerate(zip(distances[0], indices[0])):
            if idx < 0:  # FAISS returns -1 for not found
                continue
            if sim < min_similarity:
                continue

            entry_id = self._idx_to_id.get(idx)
            if entry_id is not None:
                results.append(SearchResult(entry_id=entry_id, similarity=float(sim)))

        return results

    def _search_brute_force(
        self,
        query: np.ndarray,
        k: int,
        min_similarity: float,
    ) -> list[SearchResult]:
        """Search using brute-force numpy operations."""
        if not hasattr(self, "_normalized_embeddings"):
            self._build_index()

        # Compute cosine similarities via dot product (already normalized)
        similarities = np.dot(self._normalized_embeddings, query.T).flatten()

        # Get top-k indices
        if k >= len(similarities):
            top_indices = np.argsort(-similarities)
        else:
            # Use argpartition for efficiency when k << n
            partition_indices = np.argpartition(-similarities, k)[:k]
            top_indices = partition_indices[np.argsort(-similarities[partition_indices])]

        results = []
        for idx in top_indices:
            sim = similarities[idx]
            if sim < min_similarity:
                break  # Since sorted, all remaining are below threshold

            entry_id = self._idx_to_id.get(idx)
            if entry_id is not None:
                results.append(SearchResult(entry_id=entry_id, similarity=float(sim)))

            if len(results) >= k:
                break

        return results

    async def search_async(
        self,
        query_embedding: list[float],
        k: int = 10,
        min_similarity: float = 0.0,
    ) -> list[SearchResult]:
        """
        Async-safe search with locking.

        Use this when multiple coroutines may access the index concurrently.
        """
        async with self._lock:
            return self.search(query_embedding, k, min_similarity)

    def rebuild(self) -> None:
        """Force rebuild of the index."""
        self._index_dirty = True
        self._build_index()

    def get_stats(self) -> dict[str, Any]:
        """Get index statistics."""
        return {
            "size": self.size,
            "dimension": self.dimension,
            "faiss_available": HAS_FAISS,
            "using_faiss": self.is_using_faiss,
            "index_dirty": self._index_dirty,
            "index_type": self.config.index_type,
            "faiss_threshold": self.config.faiss_threshold,
        }


__all__ = [
    "VectorIndex",
    "VectorIndexConfig",
    "SearchResult",
    "HAS_FAISS",
    "HAS_NUMPY",
]
