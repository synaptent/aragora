"""Embedding-based semantic similarity for IdeaCloud auto-linking.

Provides optional embedding support for higher-quality semantic
similarity between ideas. Falls back gracefully to keyword-based
similarity when no embedding provider is configured.

Supported providers:
  - OpenAI (text-embedding-3-small, text-embedding-ada-002)
  - Sentence-Transformers (local, no API key needed)
  - Custom callable

Usage:
    from aragora.ideacloud.graph.embeddings import EmbeddingProvider

    # OpenAI
    provider = EmbeddingProvider.from_openai()

    # Local sentence-transformers
    provider = EmbeddingProvider.from_sentence_transformers()

    # Use in auto-link
    similarity = provider.similarity(text_a, text_b)
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)


class EmbeddingFunction(Protocol):
    """Protocol for embedding functions."""

    def __call__(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class EmbeddingProvider:
    """Manages text embedding generation and caching.

    Wraps various embedding backends behind a uniform interface.
    Includes an in-memory cache to avoid re-computing embeddings.
    """

    _embed_fn: EmbeddingFunction | None = None
    _cache: dict[str, list[float]] = field(default_factory=dict)
    _dimension: int = 0
    provider_name: str = "none"

    @classmethod
    def from_openai(
        cls,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
    ) -> EmbeddingProvider:
        """Create provider using OpenAI embeddings.

        Requires ``openai`` package and OPENAI_API_KEY.
        """
        try:
            import openai

            client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()

            def embed_fn(texts: list[str]) -> list[list[float]]:
                response = client.embeddings.create(input=texts, model=model)
                return [d.embedding for d in response.data]

            provider = cls(_embed_fn=embed_fn, provider_name=f"openai:{model}")
            logger.info("Initialized OpenAI embedding provider: %s", model)
            return provider

        except ImportError:
            logger.warning("openai package not installed; embedding provider unavailable")
            return cls(provider_name="none")
        except Exception as exc:
            logger.warning("Failed to initialize OpenAI embeddings: %s", exc)
            return cls(provider_name="none")

    @classmethod
    def from_sentence_transformers(
        cls,
        model_name: str = "all-MiniLM-L6-v2",
    ) -> EmbeddingProvider:
        """Create provider using local sentence-transformers.

        Requires ``sentence-transformers`` package. No API key needed.
        """
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_name)

            def embed_fn(texts: list[str]) -> list[list[float]]:
                embeddings = model.encode(texts, convert_to_numpy=True)
                return [e.tolist() for e in embeddings]

            provider = cls(_embed_fn=embed_fn, provider_name=f"st:{model_name}")
            logger.info("Initialized sentence-transformers provider: %s", model_name)
            return provider

        except ImportError:
            logger.warning(
                "sentence-transformers package not installed; embedding provider unavailable"
            )
            return cls(provider_name="none")
        except Exception as exc:
            logger.warning("Failed to initialize sentence-transformers: %s", exc)
            return cls(provider_name="none")

    @classmethod
    def from_callable(
        cls,
        fn: EmbeddingFunction,
        name: str = "custom",
    ) -> EmbeddingProvider:
        """Create provider from a custom embedding function.

        Args:
            fn: Callable that takes list[str] and returns list[list[float]].
            name: Provider name for logging.
        """
        return cls(_embed_fn=fn, provider_name=name)

    @property
    def available(self) -> bool:
        """Whether this provider can generate embeddings."""
        return self._embed_fn is not None

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Uses cache for previously seen texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors.

        Raises:
            RuntimeError: If no embedding function is configured.
        """
        if not self._embed_fn:
            raise RuntimeError("No embedding provider configured")

        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            key = self._cache_key(text)
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        if uncached_texts:
            new_embeddings = self._embed_fn(uncached_texts)
            for idx, emb in zip(uncached_indices, new_embeddings):
                key = self._cache_key(texts[idx])
                self._cache[key] = emb
                results[idx] = emb
                if not self._dimension:
                    self._dimension = len(emb)

        return results  # type: ignore[return-value]

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text string."""
        return self.embed([text])[0]

    def similarity(self, text_a: str, text_b: str) -> float:
        """Compute cosine similarity between two texts.

        Returns:
            Cosine similarity in range [-1, 1], typically [0, 1] for
            most embedding models.
        """
        if not self._embed_fn:
            return 0.0

        try:
            emb_a, emb_b = self.embed([text_a, text_b])
            return cosine_similarity(emb_a, emb_b)
        except Exception as exc:
            logger.warning("Embedding similarity failed: %s", exc)
            return 0.0

    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        """Number of cached embeddings."""
        return len(self._cache)

    @staticmethod
    def _cache_key(text: str) -> str:
        """Generate cache key from text content."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine similarity in range [-1, 1].
    """
    if len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)
