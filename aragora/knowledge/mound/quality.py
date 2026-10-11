"""
Knowledge Mound Quality Scoring System

Provides automated quality scoring for knowledge items to enable
tier-based auto-curation and lifecycle management.

Quality is assessed across multiple dimensions:
- Freshness: How recently created/updated
- Confidence: Source reliability and verification status
- Usage: Access frequency and citation count
- Relevance: Query match frequency and user feedback
- Relationships: Connection density in knowledge graph
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QualityWeights:
    """Configurable weights for quality score components.

    Weights should sum to 1.0 for normalized scoring.
    """

    freshness: float = 0.2
    confidence: float = 0.3
    usage: float = 0.25
    relevance: float = 0.15
    relationships: float = 0.1

    def __post_init__(self):
        total = self.freshness + self.confidence + self.usage + self.relevance + self.relationships
        if abs(total - 1.0) > 0.01:
            logger.warning("Quality weights sum to %.2f, not 1.0", total)


@dataclass
class TierThresholds:
    """Thresholds for tier assignment based on quality score."""

    tier1_min: float = 0.8  # High quality - hot storage
    tier2_min: float = 0.5  # Medium quality - warm storage
    tier3_min: float = 0.2  # Low quality - cold storage
    # Below tier3_min -> archive


@dataclass
class QualityScore:
    """Quality score breakdown for a knowledge item."""

    item_id: str = ""
    total_score: float = 0.0
    freshness_score: float = 0.0
    confidence_score: float = 0.0
    usage_score: float = 0.0
    relevance_score: float = 0.0
    relationships_score: float = 0.0
    computed_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "total_score": self.total_score,
            "freshness_score": self.freshness_score,
            "confidence_score": self.confidence_score,
            "usage_score": self.usage_score,
            "relevance_score": self.relevance_score,
            "relationships_score": self.relationships_score,
            "computed_at": self.computed_at,
        }


class QualityScorer:
    """Computes quality scores for knowledge items.

    The scorer evaluates items across multiple dimensions and produces
    a normalized score between 0 and 1.

    Example:
        scorer = QualityScorer()
        score = scorer.score(item)
        tier = scorer.assign_tier(score)
    """

    def __init__(
        self,
        weights: QualityWeights | None = None,
        thresholds: TierThresholds | None = None,
        freshness_decay_days: int = 365,
        usage_cap: int = 1000,
        relationship_cap: int = 50,
    ):
        """Initialize the quality scorer.

        Args:
            weights: Component weights for scoring
            thresholds: Tier assignment thresholds
            freshness_decay_days: Days after which freshness score is 0
            usage_cap: Access count that gives max usage score
            relationship_cap: Relationship count that gives max score
        """
        self.weights = weights or QualityWeights()
        self.thresholds = thresholds or TierThresholds()
        self.freshness_decay_days = freshness_decay_days
        self.usage_cap = usage_cap
        self.relationship_cap = relationship_cap

    def score(self, item: dict[str, Any]) -> QualityScore:
        """Compute quality score for an item.

        Args:
            item: Knowledge item with metadata

        Returns:
            QualityScore with component breakdown
        """
        item_id = item.get("id", "")

        # Compute individual component scores
        freshness = self._score_freshness(item)
        confidence = self._score_confidence(item)
        usage = self._score_usage(item)
        relevance = self._score_relevance(item)
        relationships = self._score_relationships(item)

        # Weighted total
        total = (
            freshness * self.weights.freshness
            + confidence * self.weights.confidence
            + usage * self.weights.usage
            + relevance * self.weights.relevance
            + relationships * self.weights.relationships
        )

        return QualityScore(
            item_id=item_id,
            total_score=total,
            freshness_score=freshness,
            confidence_score=confidence,
            usage_score=usage,
            relevance_score=relevance,
            relationships_score=relationships,
        )

    def _score_freshness(self, item: dict[str, Any]) -> float:
        """Score based on item age.

        Newer items get higher scores, decaying linearly.
        """
        # Use updated_at if available, otherwise created_at
        timestamp_str = item.get("updated_at") or item.get("created_at")
        if not timestamp_str:
            return 0.5  # Default for missing timestamp

        try:
            # Handle various ISO format variations
            if isinstance(timestamp_str, datetime):
                timestamp = timestamp_str
            else:
                timestamp_str = timestamp_str.replace("Z", "+00:00")
                timestamp = datetime.fromisoformat(timestamp_str)
                if timestamp.tzinfo:
                    timestamp = timestamp.replace(tzinfo=None)

            age_days = (datetime.now() - timestamp).days
            score = max(0, 1 - age_days / self.freshness_decay_days)
            return score

        except (ValueError, TypeError) as e:
            logger.debug("Failed to parse timestamp: %s", e)
            return 0.5

    def _score_confidence(self, item: dict[str, Any]) -> float:
        """Score based on source reliability and verification."""
        # Direct confidence score if available
        confidence = item.get("confidence", 0.5)

        # Boost for verified items
        if item.get("verified"):
            confidence = min(1.0, confidence * 1.2)

        # Consider source reliability
        source_reliability = item.get("source_reliability", 1.0)
        confidence *= source_reliability

        return min(1.0, max(0, confidence))

    def _score_usage(self, item: dict[str, Any]) -> float:
        """Score based on access frequency and citations."""
        access_count = item.get("access_count", 0)
        citation_count = item.get("citation_count", 0)

        # Combine access and citations
        usage_signal = access_count + citation_count * 5  # Citations weighted higher

        # Normalize with diminishing returns
        score = min(1.0, usage_signal / self.usage_cap)

        # Consider recency of access
        accessed_at = item.get("accessed_at")
        if accessed_at:
            try:
                if isinstance(accessed_at, datetime):
                    last_access = accessed_at
                else:
                    accessed_at = accessed_at.replace("Z", "+00:00")
                    last_access = datetime.fromisoformat(accessed_at)
                    if last_access.tzinfo:
                        last_access = last_access.replace(tzinfo=None)

                days_since_access = (datetime.now() - last_access).days
                if days_since_access > 30:
                    # Decay score for items not accessed recently
                    score *= max(0.5, 1 - days_since_access / 365)

            except (ValueError, TypeError) as e:
                logger.warning("Failed to parse datetime value: %s", e)

        return score

    def _score_relevance(self, item: dict[str, Any]) -> float:
        """Score based on query matches and user feedback."""
        # Query match count
        query_matches = item.get("query_match_count", 0)
        query_score = min(1.0, query_matches / 100)

        # User feedback
        positive_feedback = item.get("positive_feedback", 0)
        negative_feedback = item.get("negative_feedback", 0)
        total_feedback = positive_feedback + negative_feedback

        if total_feedback > 0:
            feedback_score = positive_feedback / total_feedback
        else:
            feedback_score = 0.5  # Neutral default

        # Combine signals
        return 0.6 * query_score + 0.4 * feedback_score

    def _score_relationships(self, item: dict[str, Any]) -> float:
        """Score based on knowledge graph connectivity."""
        relationship_count = item.get("relationship_count", 0)

        # Items with more connections are more valuable
        score = min(1.0, relationship_count / self.relationship_cap)

        # Bonus for being highly connected
        if relationship_count > self.relationship_cap * 0.8:
            score = min(1.0, score * 1.1)

        return score

    def assign_tier(self, score: QualityScore) -> str:
        """Assign storage tier based on quality score.

        Args:
            score: QualityScore to evaluate

        Returns:
            Tier name: "tier1", "tier2", "tier3", or "archive"
        """
        total = score.total_score

        if total >= self.thresholds.tier1_min:
            return "tier1"
        elif total >= self.thresholds.tier2_min:
            return "tier2"
        elif total >= self.thresholds.tier3_min:
            return "tier3"
        else:
            return "archive"

    def batch_score(
        self,
        items: list[dict[str, Any]],
        max_workers: int = 4,
    ) -> list[QualityScore]:
        """Score multiple items efficiently.

        Args:
            items: List of knowledge items
            max_workers: Parallelism (not used in sync version)

        Returns:
            List of QualityScore objects
        """
        return [self.score(item) for item in items]


# Singleton scorer instance
_default_scorer: QualityScorer | None = None


def get_scorer() -> QualityScorer:
    """Get or create the default quality scorer."""
    global _default_scorer
    if _default_scorer is None:
        _default_scorer = QualityScorer()
    return _default_scorer


def score_item(item: dict[str, Any]) -> QualityScore:
    """Score a single item using the default scorer."""
    return get_scorer().score(item)


def assign_tier(item: dict[str, Any]) -> str:
    """Get tier assignment for an item using default scorer."""
    score = get_scorer().score(item)
    return get_scorer().assign_tier(score)


__all__ = [
    "QualityWeights",
    "TierThresholds",
    "QualityScore",
    "QualityScorer",
    "get_scorer",
    "score_item",
    "assign_tier",
]
