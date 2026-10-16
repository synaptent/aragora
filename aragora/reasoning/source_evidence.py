"""Evidence records gathered from external sources.

``aragora.connectors.base`` re-exports :class:`Evidence` for the connectors that build it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from aragora.reasoning.provenance import SourceType

__all__ = ["Evidence"]


@dataclass
class Evidence:
    """
    A piece of evidence from an external source.

    Contains the content and metadata needed for
    provenance tracking and reliability scoring.
    """

    id: str
    source_type: SourceType
    source_id: str  # URL, file path, issue number, etc.
    content: str
    title: str = ""

    # Metadata
    created_at: str | None = None
    author: str | None = None
    url: str | None = None

    # Reliability indicators
    confidence: float = 0.5  # Base confidence in source
    freshness: float = 1.0  # How recent (1.0 = current, decays over time)
    authority: float = 0.5  # Source authority (0-1)

    # Additional context
    metadata: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """Compute content hash."""
        return hashlib.sha256(self.content.encode()).hexdigest()[:16]

    @property
    def reliability_score(self) -> float:
        """Combined reliability score."""
        # Weighted combination of factors
        return 0.4 * self.confidence + 0.3 * self.freshness + 0.3 * self.authority

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_type": self.source_type.value,
            "source_id": self.source_id,
            "content": self.content,
            "title": self.title,
            "created_at": self.created_at,
            "author": self.author,
            "url": self.url,
            "confidence": self.confidence,
            "freshness": self.freshness,
            "authority": self.authority,
            "reliability_score": self.reliability_score,
            "content_hash": self.content_hash,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Evidence:
        """Reconstruct Evidence from dictionary (for cache deserialization)."""
        # Handle source_type as either string or SourceType enum
        source_type = data.get("source_type", "web_search")
        if isinstance(source_type, str):
            try:
                source_type = SourceType(source_type)
            except ValueError:
                source_type = SourceType.WEB_SEARCH

        return cls(
            id=data["id"],
            source_type=source_type,
            source_id=data["source_id"],
            content=data["content"],
            title=data.get("title", ""),
            created_at=data.get("created_at"),
            author=data.get("author"),
            url=data.get("url"),
            confidence=data.get("confidence", 0.5),
            freshness=data.get("freshness", 1.0),
            authority=data.get("authority", 0.5),
            metadata=data.get("metadata", {}),
        )
