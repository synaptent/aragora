"""Exploration memory for cross-session learning.

Wraps ContinuumMemory to provide exploration-specific storage and retrieval
of insights, questions, and patterns discovered during document exploration.

Memory Tiers for Exploration:
    - Fast: Current session insights (chunk-level facts)
    - Medium: Cross-document patterns (session-level)
    - Slow: Domain knowledge (persistent across sessions)
    - Glacial: Foundational audit rules and patterns
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from aragora.audit.exploration.session import Insight
from aragora.memory import MemoryTier

logger = logging.getLogger(__name__)


@dataclass
class StoredInsight:
    """An insight stored in exploration memory."""

    id: str
    insight: Insight
    tier: MemoryTier
    importance: float
    access_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    session_ids: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    embedding: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "insight": self.insight.to_dict(),
            "tier": self.tier.value,
            "importance": self.importance,
            "access_count": self.access_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "session_ids": self.session_ids,
            "document_ids": self.document_ids,
        }


class ExplorationMemory:
    """Multi-tier memory for exploration learning.

    Adapts ContinuumMemory's tier system for document exploration:
    - Fast tier: Current session insights (chunk-level facts)
    - Medium tier: Cross-document patterns (session-level)
    - Slow tier: Domain knowledge (persistent across sessions)
    - Glacial tier: Foundational audit rules

    Features:
    - Store and retrieve insights by tier
    - Automatic tier promotion based on validation count
    - Semantic similarity search for relevant insights
    - Cross-session learning persistence
    """

    def __init__(
        self,
        db_path: Path | None = None,
        enable_embeddings: bool = True,
    ):
        """Initialize exploration memory.

        Args:
            db_path: Path to SQLite database. If None, uses in-memory storage.
            enable_embeddings: Whether to compute embeddings for semantic search.
        """
        self._db_path = db_path
        self._enable_embeddings = enable_embeddings

        # In-memory storage by tier
        self._insights: dict[MemoryTier, dict[str, StoredInsight]] = {
            tier: {} for tier in MemoryTier
        }

        # Session-specific insights (cleared between sessions)
        self._session_insights: dict[str, list[StoredInsight]] = {}

        # ContinuumMemory integration (lazy loaded)
        self._continuum = None

        # Embedding function (lazy loaded)
        self._embed_fn = None

    def _get_continuum(self):
        """Lazy-load ContinuumMemory integration."""
        if self._continuum is None:
            try:
                from aragora.memory.continuum import ContinuumMemory

                db_path = str(self._db_path) if self._db_path else ":memory:"
                self._continuum = ContinuumMemory(db_path)
                logger.info("Initialized ContinuumMemory at %s", db_path)
            except ImportError:
                logger.warning("ContinuumMemory not available, using in-memory storage only")
        return self._continuum

    def _get_embed_fn(self):
        """Lazy-load embedding function."""
        if self._embed_fn is None and self._enable_embeddings:
            try:
                from aragora.memory.embeddings import get_embedding

                self._embed_fn = get_embedding
                logger.info("Initialized embedding function")
            except ImportError:
                logger.warning("Embeddings not available")
                self._enable_embeddings = False
        return self._embed_fn

    async def store_insight(
        self,
        insight: Insight,
        tier: MemoryTier = MemoryTier.FAST,
        importance: float = 0.5,
        session_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> StoredInsight:
        """Store an insight in memory.

        Args:
            insight: The insight to store
            tier: Memory tier (affects retention and retrieval priority)
            importance: Importance score (0-1)
            session_id: Optional session ID for session-specific tracking
            document_ids: Optional list of related document IDs

        Returns:
            The stored insight wrapper
        """
        stored = StoredInsight(
            id=insight.id,
            insight=insight,
            tier=tier,
            importance=importance,
            session_ids=[session_id] if session_id else [],
            document_ids=document_ids or [],
        )

        # Compute embedding if enabled
        embed_fn = self._get_embed_fn()
        if embed_fn:
            try:
                stored.embedding = await embed_fn(f"{insight.title}: {insight.description}")
            except (ValueError, RuntimeError, OSError) as e:
                logger.warning("Failed to compute embedding: %s", e)

        # Store in tier
        self._insights[tier][insight.id] = stored

        # Track by session
        if session_id:
            if session_id not in self._session_insights:
                self._session_insights[session_id] = []
            self._session_insights[session_id].append(stored)

        # Also store in ContinuumMemory for persistence
        continuum = self._get_continuum()
        if continuum:
            try:
                # Map our tier to ContinuumMemory's tier
                from aragora.memory.tier_manager import MemoryTier as ContinuumTier

                continuum_tier = ContinuumTier(tier.value)
                continuum.add(
                    id=f"exploration_insight:{insight.id}",
                    content=f"{insight.title}: {insight.description}",
                    importance=importance,
                    tier=continuum_tier,
                    metadata={
                        "insight_id": insight.id,
                        "category": insight.category,
                        "confidence": insight.confidence,
                        "tags": insight.tags,
                    },
                )
            except (ValueError, RuntimeError, OSError) as e:
                logger.warning("Failed to store in ContinuumMemory: %s", e)

        return stored

    async def retrieve_relevant(
        self,
        query: str,
        document_ids: list[str] | None = None,
        tiers: list[MemoryTier] | None = None,
        limit: int = 10,
        min_similarity: float = 0.5,
    ) -> list[StoredInsight]:
        """Retrieve insights relevant to a query.

        Args:
            query: Search query
            document_ids: Optional filter by document IDs
            tiers: Optional filter by memory tiers
            limit: Maximum number of results
            min_similarity: Minimum similarity score (0-1)

        Returns:
            List of relevant stored insights
        """
        tiers = tiers or list(MemoryTier)
        results: list[tuple[float, StoredInsight]] = []

        # Simple keyword matching (fallback)
        query_words = set(query.lower().split())

        for tier in tiers:
            for stored in self._insights[tier].values():
                # Filter by document IDs if specified
                if document_ids:
                    if not any(d in stored.document_ids for d in document_ids):
                        continue

                # Calculate relevance score
                text = f"{stored.insight.title} {stored.insight.description}".lower()
                text_words = set(text.split())
                overlap = len(query_words & text_words)
                score = overlap / max(len(query_words), 1)

                # Boost by importance and tier
                tier_boost = {
                    MemoryTier.GLACIAL: 1.2,
                    MemoryTier.SLOW: 1.1,
                    MemoryTier.MEDIUM: 1.0,
                    MemoryTier.FAST: 0.9,
                }.get(tier, 1.0)
                score = score * tier_boost * (0.5 + stored.importance * 0.5)

                if score >= min_similarity:
                    results.append((score, stored))
                    stored.access_count += 1
                    stored.updated_at = datetime.now(timezone.utc)

        # Sort by score and return top results
        results.sort(key=lambda x: x[0], reverse=True)
        return [stored for _, stored in results[:limit]]

    async def retrieve_by_session(self, session_id: str) -> list[StoredInsight]:
        """Retrieve all insights from a specific session."""
        return self._session_insights.get(session_id, [])

    async def retrieve_by_tier(self, tier: MemoryTier) -> list[StoredInsight]:
        """Retrieve all insights in a specific tier."""
        return list(self._insights[tier].values())

    async def promote_insight(
        self,
        insight_id: str,
        target_tier: MemoryTier,
    ) -> StoredInsight | None:
        """Promote an insight to a slower (more persistent) tier.

        Insights that are validated multiple times get promoted from
        fast -> medium -> slow -> glacial for long-term retention.
        """
        # Find the insight
        stored = None
        source_tier = None
        for tier in MemoryTier:
            if insight_id in self._insights[tier]:
                stored = self._insights[tier][insight_id]
                source_tier = tier
                break

        if not stored:
            return None

        # Move to target tier
        if source_tier != target_tier:
            del self._insights[cast(MemoryTier, source_tier)][insight_id]
            stored.tier = target_tier
            stored.updated_at = datetime.now(timezone.utc)
            self._insights[target_tier][insight_id] = stored
            logger.info("Promoted insight %s from %s to %s", insight_id, source_tier, target_tier)

        return stored

    async def consolidate_session(self, session_id: str) -> int:
        """Consolidate session insights to appropriate tiers after exploration.

        Insights that were validated get promoted to longer-lasting tiers.
        Returns the number of insights promoted.
        """
        session_insights = self._session_insights.get(session_id, [])
        promoted = 0

        for stored in session_insights:
            insight = stored.insight

            # Determine target tier based on validation
            if len(insight.verified_by) >= 2:
                # Highly validated -> slow tier
                target = MemoryTier.SLOW
            elif len(insight.verified_by) >= 1:
                # Single validation -> medium tier
                target = MemoryTier.MEDIUM
            else:
                # Unvalidated stays in fast tier
                continue

            if stored.tier != target:
                await self.promote_insight(insight.id, target)
                promoted += 1

        return promoted

    def get_stats(self) -> dict[str, Any]:
        """Get memory statistics."""
        return {
            "total_insights": sum(len(t) for t in self._insights.values()),
            "by_tier": {tier.value: len(insights) for tier, insights in self._insights.items()},
            "sessions_tracked": len(self._session_insights),
            "embeddings_enabled": self._enable_embeddings,
        }

    async def clear_session(self, session_id: str) -> None:
        """Clear session-specific insights (keeps promoted ones)."""
        if session_id in self._session_insights:
            del self._session_insights[session_id]

    async def clear_tier(self, tier: MemoryTier) -> None:
        """Clear all insights in a tier."""
        self._insights[tier].clear()
