"""
Similarity Backend Factory with registration and auto-selection.

Provides a unified factory for similarity backends with:
- Backend registration for custom implementations
- Auto-selection based on input size
- FAISS-backed ANN for large-scale similarity
- Unified configuration

Usage:
    from aragora.debate.similarity.factory import SimilarityFactory, get_backend

    # Get best backend for use case
    backend = get_backend(preferred="auto", input_size=100)

    # Register custom backend
    SimilarityFactory.register("custom", CustomBackend)

    # List available backends
    backends = SimilarityFactory.list_backends()
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from aragora.debate.similarity.backends import (
    JaccardBackend,
    SentenceTransformerBackend,
    SimilarityBackend,
    TFIDFBackend,
)

logger = logging.getLogger(__name__)


@dataclass
class BackendInfo:
    """Information about a registered backend."""

    name: str
    backend_class: type[SimilarityBackend]
    description: str
    requires: list[str]  # Required packages
    min_input_size: int = 0  # Minimum recommended input size
    max_input_size: int = 10000  # Maximum recommended input size
    accuracy: str = "medium"  # low, medium, high
    speed: str = "medium"  # slow, medium, fast


class SimilarityFactory:
    """
    Factory for creating and managing similarity backends.

    Provides:
    - Backend registration for extensibility
    - Auto-selection based on input characteristics
    - Unified configuration management
    """

    _registry: dict[str, BackendInfo] = {}
    _initialized: bool = False

    @classmethod
    def _ensure_initialized(cls) -> None:
        """Initialize default backends if not already done."""
        if cls._initialized:
            return

        # Register built-in backends
        cls.register(
            "jaccard",
            JaccardBackend,
            description="Simple Jaccard similarity (token overlap)",
            requires=[],
            min_input_size=0,
            max_input_size=1000,
            accuracy="low",
            speed="fast",
        )

        cls.register(
            "tfidf",
            TFIDFBackend,
            description="TF-IDF cosine similarity",
            requires=["sklearn"],
            min_input_size=0,
            max_input_size=5000,
            accuracy="medium",
            speed="medium",
        )

        cls.register(
            "sentence-transformer",
            SentenceTransformerBackend,
            description="Neural embedding similarity (best accuracy)",
            requires=["sentence-transformers"],
            min_input_size=0,
            max_input_size=10000,
            accuracy="high",
            speed="slow",
        )

        # Register FAISS backend if available
        try:
            from aragora.debate.similarity.ann import FAISSIndex  # noqa: F401

            cls.register(
                "faiss",
                _FAISSBackendWrapper,
                description="FAISS approximate nearest neighbor (large-scale)",
                requires=["faiss-cpu"],
                min_input_size=50,
                max_input_size=100000,
                accuracy="high",
                speed="fast",
            )
        except ImportError:
            logger.debug("FAISS not available, skipping registration")

        cls._initialized = True

    @classmethod
    def register(
        cls,
        name: str,
        backend_class: type[SimilarityBackend],
        description: str = "",
        requires: list[str] | None = None,
        min_input_size: int = 0,
        max_input_size: int = 10000,
        accuracy: str = "medium",
        speed: str = "medium",
    ) -> None:
        """
        Register a similarity backend.

        Args:
            name: Backend identifier
            backend_class: Backend class (must extend SimilarityBackend)
            description: Human-readable description
            requires: List of required packages
            min_input_size: Minimum recommended input size
            max_input_size: Maximum recommended input size
            accuracy: Accuracy level (low, medium, high)
            speed: Speed level (slow, medium, fast)
        """
        cls._registry[name] = BackendInfo(
            name=name,
            backend_class=backend_class,
            description=description,
            requires=requires or [],
            min_input_size=min_input_size,
            max_input_size=max_input_size,
            accuracy=accuracy,
            speed=speed,
        )
        logger.debug("Registered similarity backend: %s", name)

    @classmethod
    def unregister(cls, name: str) -> bool:
        """Unregister a backend."""
        if name in cls._registry:
            del cls._registry[name]
            return True
        return False

    @classmethod
    def list_backends(cls) -> list[BackendInfo]:
        """List all registered backends."""
        cls._ensure_initialized()
        return list(cls._registry.values())

    @classmethod
    def get_backend_info(cls, name: str) -> BackendInfo | None:
        """Get information about a specific backend."""
        cls._ensure_initialized()
        return cls._registry.get(name)

    @classmethod
    def is_available(cls, name: str) -> bool:
        """Check if a backend is available (dependencies installed).

        Uses importlib.util.find_spec to check package availability without
        importing heavy libraries (e.g. sentence-transformers → torch).
        """
        import importlib.util

        cls._ensure_initialized()
        info = cls._registry.get(name)
        if not info:
            return False

        # Check that all required packages are installed without importing them
        for pkg in info.requires:
            # Convert pip names to importable module names
            module_name = pkg.replace("-", "_")
            try:
                if importlib.util.find_spec(module_name) is None:
                    logger.debug("Backend %s unavailable: missing %s", name, pkg)
                    return False
            except (ValueError, ModuleNotFoundError):
                # ValueError: __spec__ is None (e.g. test-injected fake module)
                logger.debug("Backend %s unavailable: %s spec check failed", name, pkg)
                return False
        return True

    @classmethod
    def create(
        cls,
        name: str,
        debate_id: str | None = None,
        **kwargs: Any,
    ) -> SimilarityBackend:
        """
        Create a backend instance by name.

        Args:
            name: Backend name
            debate_id: Optional debate ID for scoped caching
            **kwargs: Additional backend-specific arguments

        Returns:
            Backend instance

        Raises:
            ValueError: If backend not found
            ImportError: If backend dependencies not installed
        """
        cls._ensure_initialized()

        info = cls._registry.get(name)
        if not info:
            available = ", ".join(cls._registry.keys())
            raise ValueError(f"Unknown backend: {name}. Available: {available}")

        # Handle debate_id for backends that support it
        if name == "sentence-transformer" and debate_id:
            kwargs["debate_id"] = debate_id

        return info.backend_class(**kwargs)

    @classmethod
    def auto_select(
        cls,
        input_size: int = 10,
        prefer_accuracy: bool = True,
        debate_id: str | None = None,
    ) -> SimilarityBackend:
        """
        Auto-select best backend based on input characteristics.

        Args:
            input_size: Expected number of texts to compare
            prefer_accuracy: If True, prefer accuracy over speed
            debate_id: Optional debate ID for scoped caching

        Returns:
            Best available backend for the use case
        """
        cls._ensure_initialized()

        # Check environment override
        env_backend = os.getenv("ARAGORA_SIMILARITY_BACKEND", "").lower()
        if env_backend and env_backend in cls._registry:
            if cls.is_available(env_backend):
                return cls.create(env_backend, debate_id=debate_id)

        # For large inputs, prefer FAISS if available
        if input_size >= 50 and cls.is_available("faiss"):
            return cls.create("faiss", debate_id=debate_id)

        # For accuracy, prefer sentence-transformer — but only if already
        # imported (avoids 30+s cold import of torch/transformers at startup).
        import sys

        if (
            prefer_accuracy
            and "sentence_transformers" in sys.modules
            and cls.is_available("sentence-transformer")
        ):
            return cls.create("sentence-transformer", debate_id=debate_id)

        # Fall back to TF-IDF
        if cls.is_available("tfidf"):
            return cls.create("tfidf")

        # Ultimate fallback
        return cls.create("jaccard")


class _FAISSBackendWrapper(SimilarityBackend):
    """
    FAISS-backed similarity backend for large-scale comparisons.

    Uses approximate nearest neighbor search for O(log n) similarity
    computation instead of O(n²) pairwise comparison.
    """

    def __init__(self, dimension: int = 384, use_gpu: bool = False):
        """
        Initialize FAISS backend.

        Args:
            dimension: Embedding dimension (default 384 for MiniLM)
            use_gpu: Use GPU acceleration if available
        """
        from aragora.debate.similarity.ann import FAISSIndex

        self._index = FAISSIndex(dimension=dimension, use_gpu=use_gpu)
        self._embedder: Any | None = None
        self._dimension = dimension

    def _get_embedder(self) -> Any:
        """Lazy-load sentence transformer for embeddings."""
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
        return self._embedder

    def _embed(self, text: str) -> Any:
        """Get embedding for text."""
        import numpy as np

        embedder = self._get_embedder()
        return embedder.encode([text], convert_to_numpy=True).astype(np.float32)

    def compute_similarity(self, text1: str, text2: str) -> float:
        """Compute similarity between two texts using embeddings."""
        import numpy as np

        if not text1 or not text2:
            return 0.0

        # Get embeddings
        emb1 = self._embed(text1)
        emb2 = self._embed(text2)

        # Normalize for cosine similarity
        emb1 = emb1 / np.linalg.norm(emb1)
        emb2 = emb2 / np.linalg.norm(emb2)

        # Cosine similarity
        return float(np.dot(emb1.flatten(), emb2.flatten()))

    def compute_batch_similarity(self, texts: list[str]) -> float:
        """Compute average pairwise similarity for a batch of texts."""
        import numpy as np

        from aragora.debate.similarity.ann import compute_batch_similarity_fast

        if len(texts) < 2:
            return 1.0

        # Get all embeddings
        embedder = self._get_embedder()
        embeddings = embedder.encode(texts, convert_to_numpy=True).astype(np.float32)

        # Use optimized batch computation
        return compute_batch_similarity_fast(embeddings)


def get_backend(
    preferred: str = "auto",
    input_size: int = 10,
    debate_id: str | None = None,
    **kwargs: Any,
) -> SimilarityBackend:
    """
    Get a similarity backend with smart selection.

    This is the recommended entry point for getting a similarity backend.

    Args:
        preferred: Backend preference ("auto", "jaccard", "tfidf",
                   "sentence-transformer", "faiss")
        input_size: Expected number of texts (for auto-selection)
        debate_id: Optional debate ID for scoped caching
        **kwargs: Additional backend-specific arguments

    Returns:
        Best available similarity backend

    Examples:
        # Auto-select best for small comparison
        backend = get_backend()

        # Force specific backend
        backend = get_backend(preferred="tfidf")

        # Optimize for large-scale comparison
        backend = get_backend(input_size=1000)
    """
    if preferred == "auto":
        return SimilarityFactory.auto_select(
            input_size=input_size,
            debate_id=debate_id,
        )

    return SimilarityFactory.create(preferred, debate_id=debate_id, **kwargs)


__all__ = [
    "SimilarityFactory",
    "BackendInfo",
    "get_backend",
]
