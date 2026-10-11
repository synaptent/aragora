"""
Source Weighting System for Pulse Topics.

Assigns credibility weights to topics based on their source platform,
enabling quality-based ranking and filtering of trending content.

Features:
- Configurable per-platform credibility scores
- Source-specific weight adjustments
- Historical performance tracking
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from aragora.pulse.ingestor import TrendingTopic

logger = logging.getLogger(__name__)


@dataclass
class SourceWeight:
    """Weight configuration for a source platform."""

    platform: str
    base_credibility: float  # 0.0 - 1.0
    authority_score: float  # 0.0 - 1.0
    volume_multiplier: float = 1.0  # Adjust how volume affects final score
    freshness_weight: float = 1.0  # How much freshness matters for this source
    description: str = ""


# Default source weights (can be overridden)
DEFAULT_SOURCE_WEIGHTS: dict[str, SourceWeight] = {
    "hackernews": SourceWeight(
        platform="hackernews",
        base_credibility=0.85,
        authority_score=0.90,
        volume_multiplier=0.5,  # HN points are lower scale than Twitter volume
        freshness_weight=1.2,  # Tech news gets stale quickly
        description="Hacker News - tech-focused, high-quality curation",
    ),
    "reddit": SourceWeight(
        platform="reddit",
        base_credibility=0.70,
        authority_score=0.65,
        volume_multiplier=0.3,  # Reddit upvotes inflate quickly
        freshness_weight=1.0,
        description="Reddit - community-driven, variable quality",
    ),
    "twitter": SourceWeight(
        platform="twitter",
        base_credibility=0.60,
        authority_score=0.55,
        volume_multiplier=0.1,  # Twitter volume can be massive but noisy
        freshness_weight=1.5,  # Tweets get stale fastest
        description="Twitter/X - real-time but noisy, needs filtering",
    ),
    "github": SourceWeight(
        platform="github",
        base_credibility=0.90,
        authority_score=0.95,
        volume_multiplier=1.0,  # Stars are a good quality signal
        freshness_weight=0.8,  # Code projects stay relevant longer
        description="GitHub - high signal for tech/dev topics",
    ),
}


@dataclass
class WeightedTopic:
    """A trending topic with calculated weights."""

    topic: TrendingTopic
    source_weight: SourceWeight
    weighted_score: float
    components: dict[str, float] = field(default_factory=dict)

    @property
    def platform(self) -> str:
        return self.topic.platform

    @property
    def credibility(self) -> float:
        return self.source_weight.base_credibility

    @property
    def authority(self) -> float:
        return self.source_weight.authority_score


class SourceWeightingSystem:
    """
    Calculates weighted scores for trending topics based on source credibility.

    Usage:
        weighting = SourceWeightingSystem()
        weighted = weighting.weight_topic(topic)
        print(f"Score: {weighted.weighted_score}, Credibility: {weighted.credibility}")

        # Or weight multiple topics at once
        weighted_list = weighting.weight_topics(topics)
        ranked = weighting.rank_by_weighted_score(weighted_list)
    """

    def __init__(
        self,
        source_weights: dict[str, SourceWeight] | None = None,
        default_credibility: float = 0.50,
        default_authority: float = 0.50,
    ):
        """
        Initialize the weighting system.

        Args:
            source_weights: Custom source weight configurations
            default_credibility: Default credibility for unknown sources
            default_authority: Default authority for unknown sources
        """
        self.source_weights = source_weights or DEFAULT_SOURCE_WEIGHTS.copy()
        self.default_credibility = default_credibility
        self.default_authority = default_authority

        # Track historical performance by source
        self._source_performance: dict[str, list[float]] = {}
        self._max_history = 100

    def get_source_weight(self, platform: str) -> SourceWeight:
        """Get weight configuration for a platform.

        Args:
            platform: Platform name (lowercase)

        Returns:
            SourceWeight for the platform (or default if unknown)
        """
        platform_lower = platform.lower()
        if platform_lower in self.source_weights:
            return self.source_weights[platform_lower]

        # Return default for unknown sources
        return SourceWeight(
            platform=platform_lower,
            base_credibility=self.default_credibility,
            authority_score=self.default_authority,
            description="Unknown source - using default weights",
        )

    def weight_topic(self, topic: TrendingTopic) -> WeightedTopic:
        """
        Calculate weighted score for a single topic.

        The weighted score combines:
        - Source credibility (40%)
        - Volume-adjusted engagement (30%)
        - Authority score (30%)

        Args:
            topic: TrendingTopic to weight

        Returns:
            WeightedTopic with calculated scores
        """
        source_weight = self.get_source_weight(topic.platform)

        # Calculate component scores
        credibility_component = source_weight.base_credibility * 0.40

        # Normalize volume using platform-specific multiplier
        # Log scale to handle large volume differences
        import math

        normalized_volume = math.log10(max(1, topic.volume) + 1) / 6  # 6 = log10(1M)
        volume_component = min(1.0, normalized_volume * source_weight.volume_multiplier) * 0.30

        authority_component = source_weight.authority_score * 0.30

        # Final weighted score
        weighted_score = credibility_component + volume_component + authority_component

        components = {
            "credibility": credibility_component,
            "volume": volume_component,
            "authority": authority_component,
            "raw_volume": float(topic.volume),
            "normalized_volume": normalized_volume,
        }

        return WeightedTopic(
            topic=topic,
            source_weight=source_weight,
            weighted_score=weighted_score,
            components=components,
        )

    def weight_topics(self, topics: list[TrendingTopic]) -> list[WeightedTopic]:
        """
        Calculate weighted scores for multiple topics.

        Args:
            topics: List of TrendingTopic objects

        Returns:
            List of WeightedTopic objects
        """
        return [self.weight_topic(t) for t in topics]

    def rank_by_weighted_score(
        self,
        weighted_topics: list[WeightedTopic],
        min_credibility: float = 0.0,
        min_score: float = 0.0,
    ) -> list[WeightedTopic]:
        """
        Rank topics by weighted score with optional filtering.

        Args:
            weighted_topics: List of WeightedTopic objects
            min_credibility: Minimum credibility threshold (0-1)
            min_score: Minimum weighted score threshold (0-1)

        Returns:
            Filtered and sorted list of WeightedTopic objects
        """
        # Apply filters
        filtered = [
            wt
            for wt in weighted_topics
            if wt.credibility >= min_credibility and wt.weighted_score >= min_score
        ]

        # Sort by weighted score descending
        filtered.sort(key=lambda x: x.weighted_score, reverse=True)

        return filtered

    def update_source_weight(
        self,
        platform: str,
        credibility: float | None = None,
        authority: float | None = None,
        volume_multiplier: float | None = None,
        freshness_weight: float | None = None,
    ) -> SourceWeight:
        """
        Update weight configuration for a source.

        Args:
            platform: Platform name
            credibility: New base credibility (0-1)
            authority: New authority score (0-1)
            volume_multiplier: New volume multiplier
            freshness_weight: New freshness weight

        Returns:
            Updated SourceWeight
        """
        current = self.get_source_weight(platform)

        updated = SourceWeight(
            platform=platform.lower(),
            base_credibility=credibility if credibility is not None else current.base_credibility,
            authority_score=authority if authority is not None else current.authority_score,
            volume_multiplier=(
                volume_multiplier if volume_multiplier is not None else current.volume_multiplier
            ),
            freshness_weight=(
                freshness_weight if freshness_weight is not None else current.freshness_weight
            ),
            description=current.description,
        )

        self.source_weights[platform.lower()] = updated
        logger.info(
            "Updated source weight for %s: credibility=%.2f", platform, updated.base_credibility
        )

        return updated

    def record_topic_performance(
        self,
        platform: str,
        debate_quality_score: float,
    ) -> None:
        """
        Record debate performance for adaptive weight adjustment.

        Call this after debates to track which sources produce quality topics.

        Args:
            platform: Source platform
            debate_quality_score: Quality score from debate (0-1)
        """
        platform_lower = platform.lower()
        if platform_lower not in self._source_performance:
            self._source_performance[platform_lower] = []

        self._source_performance[platform_lower].append(debate_quality_score)

        # Trim to max history
        if len(self._source_performance[platform_lower]) > self._max_history:
            self._source_performance[platform_lower] = self._source_performance[platform_lower][
                -self._max_history :
            ]

    def get_adaptive_credibility(self, platform: str) -> float:
        """
        Get adaptive credibility based on historical performance.

        Blends base credibility with historical debate quality.

        Args:
            platform: Platform name

        Returns:
            Adaptive credibility score (0-1)
        """
        base_weight = self.get_source_weight(platform)
        history = self._source_performance.get(platform.lower(), [])

        if not history:
            return base_weight.base_credibility

        # Calculate average historical performance
        avg_performance = sum(history) / len(history)

        # Blend: 70% base credibility, 30% historical performance
        adaptive = base_weight.base_credibility * 0.7 + avg_performance * 0.3

        return min(1.0, max(0.0, adaptive))

    def get_source_stats(self) -> dict[str, Any]:
        """
        Get statistics for all configured sources.

        Returns:
            Dictionary with source statistics
        """
        stats = {}
        for platform, weight in self.source_weights.items():
            history = self._source_performance.get(platform, [])
            stats[platform] = {
                "base_credibility": weight.base_credibility,
                "authority_score": weight.authority_score,
                "volume_multiplier": weight.volume_multiplier,
                "freshness_weight": weight.freshness_weight,
                "adaptive_credibility": self.get_adaptive_credibility(platform),
                "debate_count": len(history),
                "avg_debate_quality": sum(history) / len(history) if history else None,
            }
        return stats


__all__ = [
    "SourceWeight",
    "WeightedTopic",
    "SourceWeightingSystem",
    "DEFAULT_SOURCE_WEIGHTS",
]
