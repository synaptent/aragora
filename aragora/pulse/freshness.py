"""
Freshness Decay System for Pulse Topics.

Calculates time-based relevance decay for trending topics,
ensuring recent content is prioritized over stale trends.

Decay models:
- Exponential: Rapid initial decay, long tail
- Linear: Steady decay over time
- Step: Binary fresh/stale threshold
- Platform-aware: Different decay rates per source
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from aragora.pulse.ingestor import TrendingTopic

logger = logging.getLogger(__name__)


class DecayModel(str, Enum):
    """Freshness decay model types."""

    EXPONENTIAL = "exponential"  # f(t) = e^(-λt)
    LINEAR = "linear"  # f(t) = max(0, 1 - kt)
    STEP = "step"  # f(t) = 1 if t < threshold else 0
    LOGARITHMIC = "logarithmic"  # f(t) = 1 / (1 + ln(1 + kt))


@dataclass
class FreshnessConfig:
    """Configuration for freshness calculation."""

    decay_model: DecayModel = DecayModel.EXPONENTIAL
    half_life_hours: float = 6.0  # Time for relevance to halve
    max_age_hours: float = 48.0  # Maximum age before zero relevance
    min_freshness: float = 0.05  # Minimum freshness floor

    # Platform-specific half-lives (override global)
    platform_half_lives: dict[str, float] | None = None


# Default platform-specific half-lives (in hours)
DEFAULT_PLATFORM_HALF_LIVES = {
    "twitter": 3.0,  # Twitter trends fade fastest
    "hackernews": 8.0,  # HN stories stay relevant longer
    "reddit": 12.0,  # Reddit threads have longer life
    "github": 24.0,  # Code repos stay fresh longest
}


@dataclass
class FreshnessScore:
    """Freshness calculation result."""

    topic: TrendingTopic
    freshness: float  # 0.0 - 1.0 (1.0 = completely fresh)
    age_hours: float
    decay_model: DecayModel
    half_life_hours: float

    @property
    def is_stale(self) -> bool:
        """Check if topic is considered stale."""
        return self.freshness < 0.1


class FreshnessCalculator:
    """
    Calculates time-based freshness scores for trending topics.

    Usage:
        calculator = FreshnessCalculator()
        score = calculator.calculate_freshness(topic, topic_timestamp)
        print(f"Freshness: {score.freshness:.2f}, Age: {score.age_hours:.1f}h")

        # Apply freshness to a list of topics
        scored = calculator.score_topics(topics, timestamps)
        fresh_only = [s for s in scored if not s.is_stale]
    """

    def __init__(self, config: FreshnessConfig | None = None):
        """
        Initialize the freshness calculator.

        Args:
            config: Optional FreshnessConfig (uses defaults if not provided)
        """
        self.config = config or FreshnessConfig()
        self._platform_half_lives = (
            self.config.platform_half_lives or DEFAULT_PLATFORM_HALF_LIVES.copy()
        )

    def calculate_freshness(
        self,
        topic: TrendingTopic,
        created_at: float | None = None,
        reference_time: float | None = None,
    ) -> FreshnessScore:
        """
        Calculate freshness score for a topic.

        Args:
            topic: TrendingTopic to evaluate
            created_at: Unix timestamp when topic was created/fetched
                       (defaults to current time if not provided)
            reference_time: Reference time for age calculation
                           (defaults to current time)

        Returns:
            FreshnessScore with freshness value and metadata
        """
        now = reference_time or time.time()
        topic_time = created_at or now

        # Calculate age in hours
        age_seconds = max(0, now - topic_time)
        age_hours = age_seconds / 3600

        # Get platform-specific half-life
        half_life = self._get_half_life(topic.platform)

        # Check max age cutoff
        if age_hours >= self.config.max_age_hours:
            return FreshnessScore(
                topic=topic,
                freshness=0.0,
                age_hours=age_hours,
                decay_model=self.config.decay_model,
                half_life_hours=half_life,
            )

        # Calculate freshness based on decay model
        freshness = self._apply_decay(age_hours, half_life)

        # Apply minimum floor
        freshness = max(self.config.min_freshness, freshness)

        return FreshnessScore(
            topic=topic,
            freshness=freshness,
            age_hours=age_hours,
            decay_model=self.config.decay_model,
            half_life_hours=half_life,
        )

    def score_topics(
        self,
        topics: list[TrendingTopic],
        timestamps: dict[str, float] | None = None,
        reference_time: float | None = None,
    ) -> list[FreshnessScore]:
        """
        Calculate freshness for multiple topics.

        Args:
            topics: List of TrendingTopic objects
            timestamps: Dict mapping topic text to creation timestamp
            reference_time: Reference time for age calculation

        Returns:
            List of FreshnessScore objects
        """
        timestamps = timestamps or {}
        now = reference_time or time.time()

        scores = []
        for topic in topics:
            created_at = timestamps.get(topic.topic) or self._extract_timestamp(topic)
            score = self.calculate_freshness(topic, created_at, now)
            scores.append(score)

        return scores

    def filter_stale(
        self,
        topics: list[TrendingTopic],
        timestamps: dict[str, float] | None = None,
        min_freshness: float = 0.1,
    ) -> list[FreshnessScore]:
        """
        Filter out stale topics.

        Args:
            topics: List of TrendingTopic objects
            timestamps: Dict mapping topic text to creation timestamp
            min_freshness: Minimum freshness to include

        Returns:
            List of FreshnessScore objects for fresh topics only
        """
        scores = self.score_topics(topics, timestamps)
        fresh = [s for s in scores if s.freshness >= min_freshness]

        # Sort by freshness descending
        fresh.sort(key=lambda x: x.freshness, reverse=True)

        logger.debug(
            "Freshness filter: %s topics -> %s fresh (min_freshness=%.2f)",
            len(topics),
            len(fresh),
            min_freshness,
        )

        return fresh

    def _get_half_life(self, platform: str) -> float:
        """Get half-life for a platform."""
        return self._platform_half_lives.get(platform.lower(), self.config.half_life_hours)

    def _apply_decay(self, age_hours: float, half_life_hours: float) -> float:
        """Apply decay model to calculate freshness."""
        model = self.config.decay_model

        if model == DecayModel.EXPONENTIAL:
            # Exponential decay: f(t) = e^(-λt) where λ = ln(2)/half_life
            decay_constant = math.log(2) / half_life_hours
            return math.exp(-decay_constant * age_hours)

        elif model == DecayModel.LINEAR:
            # Linear decay: f(t) = max(0, 1 - t/max_age)
            return max(0.0, 1.0 - age_hours / self.config.max_age_hours)

        elif model == DecayModel.STEP:
            # Step function: 1 if fresh, 0 if stale
            return 1.0 if age_hours < half_life_hours else 0.0

        elif model == DecayModel.LOGARITHMIC:
            # Logarithmic decay: 1 / (1 + ln(1 + kt))
            k = 0.5  # Decay rate
            return 1.0 / (1.0 + math.log(1.0 + k * age_hours))

        else:
            # Default to exponential
            decay_constant = math.log(2) / half_life_hours
            return math.exp(-decay_constant * age_hours)

    def _extract_timestamp(self, topic: TrendingTopic) -> float | None:
        """Try to extract timestamp from topic raw_data."""
        raw = topic.raw_data

        # Check common timestamp fields
        for field in ["created_at", "timestamp", "time", "date", "published_at"]:
            if field in raw:
                val = raw[field]
                if isinstance(val, (int, float)):
                    return float(val)
                if isinstance(val, str):
                    return self._parse_timestamp(val)

        return None

    def _parse_timestamp(self, timestamp_str: str) -> float | None:
        """Parse a timestamp string to Unix time."""
        from datetime import datetime

        # Try common formats
        formats = [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(timestamp_str, fmt)
                return dt.timestamp()
            except ValueError:
                continue

        return None

    def set_platform_half_life(self, platform: str, half_life_hours: float) -> None:
        """Set custom half-life for a platform."""
        self._platform_half_lives[platform.lower()] = half_life_hours
        logger.info("Set half-life for %s: %.1fh", platform, half_life_hours)

    def get_decay_curve(
        self,
        platform: str = "default",
        max_hours: float = 48.0,
        points: int = 50,
    ) -> list[dict[str, float]]:
        """
        Get decay curve data points for visualization.

        Args:
            platform: Platform to get curve for
            max_hours: Maximum hours to plot
            points: Number of data points

        Returns:
            List of {hours, freshness} dicts
        """
        half_life = self._get_half_life(platform)
        step = max_hours / points

        curve = []
        for i in range(points + 1):
            hours = i * step
            freshness = max(self.config.min_freshness, self._apply_decay(hours, half_life))
            curve.append({"hours": hours, "freshness": freshness})

        return curve

    def get_stats(self) -> dict[str, Any]:
        """Get calculator configuration and stats."""
        return {
            "decay_model": self.config.decay_model.value,
            "half_life_hours": self.config.half_life_hours,
            "max_age_hours": self.config.max_age_hours,
            "min_freshness": self.config.min_freshness,
            "platform_half_lives": self._platform_half_lives.copy(),
        }


__all__ = [
    "DecayModel",
    "FreshnessConfig",
    "FreshnessScore",
    "FreshnessCalculator",
    "DEFAULT_PLATFORM_HALF_LIVES",
]
