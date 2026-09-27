"""
Local Embedding Service using Sentence Transformers.

Provides fast, local embeddings without external API dependencies.
Supports multiple model sizes for different speed/quality tradeoffs.

Usage:
    from aragora.ml import LocalEmbeddingService, EmbeddingModel

    # Fast embeddings (384 dimensions)
    service = LocalEmbeddingService(model=EmbeddingModel.MINILM)
    embeddings = await service.embed_batch(["text1", "text2"])

    # High quality embeddings (768 dimensions)
    service = LocalEmbeddingService(model=EmbeddingModel.MPNET)

    # Search for similar texts
    results = await service.search(query, documents, top_k=5)
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from collections.abc import Sequence

import numpy as np

try:
    SentenceTransformer: Any = importlib.import_module("sentence_transformers").SentenceTransformer
except ImportError:  # pragma: no cover - optional dependency
    SentenceTransformer = None

logger = logging.getLogger(__name__)


class EmbeddingModel(str, Enum):
    """Available embedding models with different speed/quality tradeoffs."""

    # Fast, small models (good for most use cases)
    MINILM = "all-MiniLM-L6-v2"  # 384 dim, 22M params, fast
    MINILM_L12 = "all-MiniLM-L12-v2"  # 384 dim, 33M params, better quality

    # High quality models (larger, slower)
    MPNET = "all-mpnet-base-v2"  # 768 dim, 110M params, best quality

    # Multilingual models
    MULTILINGUAL = "paraphrase-multilingual-MiniLM-L12-v2"  # 384 dim, 50+ languages

    # Code-specific models
    CODE = "flax-sentence-embeddings/st-codesearch-distilroberta-base"  # For code


@dataclass
class EmbeddingResult:
    """Result of an embedding operation."""

    text: str
    embedding: list[float]
    model: str
    dimension: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text[:100] + "..." if len(self.text) > 100 else self.text,
            "model": self.model,
            "dimension": self.dimension,
            "embedding_preview": self.embedding[:5],
        }


@dataclass
class SearchResult:
    """Result of a similarity search."""

    text: str
    score: float
    index: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LocalEmbeddingConfig:
    """Configuration for local embedding service."""

    model: EmbeddingModel = EmbeddingModel.MINILM
    device: str = "cpu"  # "cpu", "cuda", "mps"
    normalize: bool = True
    batch_size: int = 32
    show_progress: bool = False
    cache_folder: str | None = None


class LocalEmbeddingService:
    """Local embedding service using Sentence Transformers.

    Provides fast, offline embeddings with no API costs.
    Models are downloaded on first use and cached locally.

    Features:
    - Multiple model options (speed vs quality)
    - Batch processing
    - Similarity search
    - Async support
    - GPU acceleration (if available)
    """

    def __init__(self, config: LocalEmbeddingConfig | None = None):
        """Initialize the embedding service.

        Args:
            config: Service configuration. Uses defaults if not provided.
        """
        self.config = config or LocalEmbeddingConfig()
        self._model: SentenceTransformer | None = None
        self._dimension: int | None = None
        self._lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        """Get the model name."""
        return self.config.model.value

    @property
    def dimension(self) -> int:
        """Get embedding dimension (lazy loaded)."""
        if self._dimension is None:
            self._ensure_model_loaded()
            if self._model is None:
                raise RuntimeError("Model not initialized - _ensure_model_loaded() failed")
            dim = self._model.get_sentence_embedding_dimension()
            # get_sentence_embedding_dimension can return None, but standard models always have a dimension
            if dim is None:
                raise RuntimeError(f"Model {self.model_name} returned None for embedding dimension")
            self._dimension = dim
        return self._dimension

    def _ensure_model_loaded(self) -> None:
        """Load the model if not already loaded."""
        if self._model is None:
            if SentenceTransformer is None:
                raise ImportError(
                    "sentence-transformers is required for LocalEmbeddingService. "
                    "Install with: pip install sentence-transformers"
                )
            logger.info("Loading embedding model: %s", self.model_name)
            self._model = SentenceTransformer(
                self.model_name,
                device=self.config.device,
                cache_folder=self.config.cache_folder,
            )
            self._dimension = self._model.get_sentence_embedding_dimension()
            logger.info("Model loaded: %s (%s dimensions)", self.model_name, self._dimension)

    def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats
        """
        self._ensure_model_loaded()
        if self._model is None:
            raise RuntimeError("Model not initialized - _ensure_model_loaded() failed")
        embedding = self._model.encode(
            text,
            normalize_embeddings=self.config.normalize,
            show_progress_bar=False,
        )
        # encode() returns np.ndarray when convert_to_numpy=True (default)
        return np.asarray(embedding).tolist()

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: Texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        self._ensure_model_loaded()
        if self._model is None:
            raise RuntimeError("Model not initialized - _ensure_model_loaded() failed")
        embeddings = self._model.encode(
            list(texts),
            normalize_embeddings=self.config.normalize,
            batch_size=self.config.batch_size,
            show_progress_bar=self.config.show_progress,
        )
        # encode() returns np.ndarray when convert_to_numpy=True (default)
        return np.asarray(embeddings).tolist()

    async def embed_async(self, text: str) -> list[float]:
        """Async version of embed."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.embed, text)

    async def embed_batch_async(self, texts: Sequence[str]) -> list[list[float]]:
        """Async version of embed_batch."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.embed_batch, texts)

    def similarity(self, embedding1: list[float], embedding2: list[float]) -> float:
        """Compute cosine similarity between two embeddings.

        Args:
            embedding1: First embedding
            embedding2: Second embedding

        Returns:
            Cosine similarity score (0-1 for normalized embeddings)
        """
        a = np.array(embedding1)
        b = np.array(embedding2)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    def search(
        self,
        query: str,
        documents: Sequence[str],
        top_k: int = 5,
        threshold: float = 0.0,
    ) -> list[SearchResult]:
        """Search for most similar documents to query.

        Args:
            query: Query text
            documents: Documents to search
            top_k: Number of results to return
            threshold: Minimum similarity score

        Returns:
            List of search results sorted by similarity
        """
        if not documents:
            return []

        # Embed query and documents
        query_embedding = self.embed(query)
        doc_embeddings = self.embed_batch(documents)

        # Calculate similarities
        query_vec = np.array(query_embedding)
        doc_matrix = np.array(doc_embeddings)

        # Cosine similarity (embeddings are already normalized)
        if self.config.normalize:
            similarities = np.dot(doc_matrix, query_vec)
        else:
            similarities = np.dot(doc_matrix, query_vec) / (
                np.linalg.norm(doc_matrix, axis=1) * np.linalg.norm(query_vec)
            )

        # Get top-k results
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for idx in top_indices:
            score = float(similarities[idx])
            if score >= threshold:
                results.append(
                    SearchResult(
                        text=documents[idx],
                        score=score,
                        index=int(idx),
                    )
                )

        return results

    async def search_async(
        self,
        query: str,
        documents: Sequence[str],
        top_k: int = 5,
        threshold: float = 0.0,
    ) -> list[SearchResult]:
        """Async version of search."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, lambda: self.search(query, documents, top_k, threshold)
            )

    def cluster(
        self,
        texts: Sequence[str],
        n_clusters: int = 5,
    ) -> list[int]:
        """Cluster texts by semantic similarity.

        Args:
            texts: Texts to cluster
            n_clusters: Number of clusters

        Returns:
            Cluster labels for each text
        """
        if len(texts) < n_clusters:
            return list(range(len(texts)))

        embeddings = self.embed_batch(texts)

        from sklearn.cluster import KMeans

        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(embeddings)

        return labels.tolist()


# Global instance cache
_embedding_services: dict[str, LocalEmbeddingService] = {}


def get_embedding_service(
    model: EmbeddingModel = EmbeddingModel.MINILM,
    device: str = "cpu",
) -> LocalEmbeddingService:
    """Get or create a cached embedding service.

    Args:
        model: Model to use
        device: Device to run on

    Returns:
        Cached embedding service instance
    """
    key = f"{model.value}:{device}"
    if key not in _embedding_services:
        config = LocalEmbeddingConfig(model=model, device=device)
        _embedding_services[key] = LocalEmbeddingService(config)
    return _embedding_services[key]
