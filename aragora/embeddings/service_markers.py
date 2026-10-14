"""Service registry marker types for the embedding services.

Registered with :mod:`aragora.runtime.service_registry` as keys for the
embedding cache (``aragora.memory.embeddings``) and the embedding provider
reference (``aragora.memory.streams``). ``aragora.services`` re-exports both.
"""

from __future__ import annotations


class EmbeddingCacheService:
    """Marker type for the embedding cache (memory/embeddings.py)."""

    pass


class EmbeddingProviderService:
    """Marker type for the embedding provider reference (memory/streams.py)."""

    pass


__all__ = ["EmbeddingCacheService", "EmbeddingProviderService"]
