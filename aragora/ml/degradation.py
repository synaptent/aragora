"""
Graceful ML Degradation for Aragora.

Provides automatic fallback mechanisms when ML features are unavailable,
slow, or experiencing errors. Ensures the system continues operating
with reduced functionality rather than failing completely.

Usage:
    from aragora.ml.degradation import (
        get_ml_fallback,
        MLFeature,
        DegradationLevel,
    )

    # Get fallback-aware service
    fallback = get_ml_fallback()

    # Compute similarity with automatic degradation
    similarity = await fallback.compute_similarity(text1, text2)

    # Check current degradation status
    status = fallback.get_status()
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, TypeVar
from collections.abc import Sequence

from aragora.resilience import CircuitBreaker, get_circuit_breaker

if TYPE_CHECKING:
    from aragora.ml.embeddings import LocalEmbeddingService
    from aragora.ml.consensus_predictor import ConsensusPredictor
    from aragora.ml.quality_scorer import QualityScorer

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Degradation thresholds
LATENCY_WARNING_MS = 500  # Start degradation planning
LATENCY_DEGRADE_MS = 2000  # Force degradation
ERROR_RATE_THRESHOLD = 0.20  # 20% error rate triggers degradation


class MLFeature(str, Enum):
    """ML features that support graceful degradation."""

    EMBEDDINGS = "embeddings"
    CONSENSUS_PREDICTION = "consensus_prediction"
    QUALITY_SCORING = "quality_scoring"
    AGENT_ROUTING = "agent_routing"
    SEMANTIC_SEARCH = "semantic_search"
    SENTIMENT_ANALYSIS = "sentiment_analysis"


class DegradationLevel(str, Enum):
    """Levels of ML degradation."""

    FULL = "full"  # Full ML features available
    LIGHTWEIGHT = "lightweight"  # Use lightweight/local models
    HEURISTIC = "heuristic"  # Use heuristic fallbacks only
    DISABLED = "disabled"  # Feature temporarily disabled


@dataclass
class FeatureStatus:
    """Status of a single ML feature."""

    feature: MLFeature
    level: DegradationLevel
    available: bool
    last_check: float
    latency_ms: float = 0.0
    error_count: int = 0
    success_count: int = 0
    reason: str = ""

    @property
    def error_rate(self) -> float:
        """Calculate error rate."""
        total = self.error_count + self.success_count
        if total == 0:
            return 0.0
        return self.error_count / total

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature.value,
            "level": self.level.value,
            "available": self.available,
            "latency_ms": round(self.latency_ms, 2),
            "error_rate": round(self.error_rate, 3),
            "reason": self.reason,
        }


@dataclass
class DegradationEvent:
    """Record of a degradation event."""

    feature: MLFeature
    from_level: DegradationLevel
    to_level: DegradationLevel
    timestamp: float
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)


class MLDegradationManager:
    """
    Manages graceful degradation of ML features.

    Monitors ML feature health and automatically degrades when issues occur.
    Provides fallback implementations for all ML features.
    """

    def __init__(self):
        self._feature_status: dict[MLFeature, FeatureStatus] = {}
        self._degradation_history: list[DegradationEvent] = []
        self._circuit_breakers: dict[MLFeature, CircuitBreaker] = {}
        self._initialize_features()

    def _initialize_features(self) -> None:
        """Initialize feature status tracking."""
        now = time.time()
        for feature in MLFeature:
            self._feature_status[feature] = FeatureStatus(
                feature=feature,
                level=DegradationLevel.FULL,
                available=True,
                last_check=now,
            )
            self._circuit_breakers[feature] = get_circuit_breaker(
                f"ml_{feature.value}",
                failure_threshold=3,
                cooldown_seconds=60.0,
            )

    def get_level(self, feature: MLFeature) -> DegradationLevel:
        """Get current degradation level for a feature."""
        return self._feature_status[feature].level

    def set_level(
        self,
        feature: MLFeature,
        level: DegradationLevel,
        reason: str = "",
    ) -> None:
        """Set degradation level for a feature."""
        status = self._feature_status[feature]
        if status.level != level:
            event = DegradationEvent(
                feature=feature,
                from_level=status.level,
                to_level=level,
                timestamp=time.time(),
                reason=reason,
                metrics={
                    "latency_ms": status.latency_ms,
                    "error_rate": status.error_rate,
                },
            )
            self._degradation_history.append(event)

            # Keep history bounded
            if len(self._degradation_history) > 1000:
                self._degradation_history = self._degradation_history[-500:]

            logger.info(
                "ML degradation: %s %s -> %s: %s",
                feature.value,
                status.level.value,
                level.value,
                reason,
            )

        status.level = level
        status.reason = reason
        status.last_check = time.time()

    def record_success(
        self,
        feature: MLFeature,
        latency_ms: float,
    ) -> None:
        """Record a successful ML operation."""
        status = self._feature_status[feature]
        status.success_count += 1
        status.latency_ms = latency_ms
        status.last_check = time.time()

        # Auto-upgrade if consistently healthy
        if status.level != DegradationLevel.FULL:
            if (
                status.success_count > 10
                and status.error_rate < 0.05
                and latency_ms < LATENCY_WARNING_MS
            ):
                self.set_level(feature, DegradationLevel.FULL, "recovered")

    def record_error(
        self,
        feature: MLFeature,
        error: Exception,
    ) -> None:
        """Record an ML operation error."""
        status = self._feature_status[feature]
        status.error_count += 1
        status.last_check = time.time()

        # Auto-degrade on errors
        if status.error_rate > ERROR_RATE_THRESHOLD:
            if status.level == DegradationLevel.FULL:
                self.set_level(
                    feature,
                    DegradationLevel.LIGHTWEIGHT,
                    f"error_rate={status.error_rate:.2%}",
                )
            elif status.level == DegradationLevel.LIGHTWEIGHT:
                self.set_level(
                    feature,
                    DegradationLevel.HEURISTIC,
                    f"error_rate={status.error_rate:.2%}",
                )

        logger.warning("ML error in %s: %s", feature.value, error)

    def record_latency(
        self,
        feature: MLFeature,
        latency_ms: float,
    ) -> None:
        """Record latency and potentially degrade based on slowness."""
        status = self._feature_status[feature]
        status.latency_ms = latency_ms

        if latency_ms > LATENCY_DEGRADE_MS:
            if status.level == DegradationLevel.FULL:
                self.set_level(
                    feature,
                    DegradationLevel.LIGHTWEIGHT,
                    f"latency={latency_ms:.0f}ms",
                )
            elif status.level == DegradationLevel.LIGHTWEIGHT:
                self.set_level(
                    feature,
                    DegradationLevel.HEURISTIC,
                    f"latency={latency_ms:.0f}ms",
                )

    def get_status(self) -> dict[str, Any]:
        """Get overall degradation status."""
        return {
            "features": {f.value: self._feature_status[f].to_dict() for f in MLFeature},
            "degraded_count": sum(
                1 for s in self._feature_status.values() if s.level != DegradationLevel.FULL
            ),
            "recent_events": [
                {
                    "feature": e.feature.value,
                    "from": e.from_level.value,
                    "to": e.to_level.value,
                    "reason": e.reason,
                    "timestamp": e.timestamp,
                }
                for e in self._degradation_history[-10:]
            ],
        }


# ============================================================================
# Heuristic Fallback Implementations
# ============================================================================


def _tokenize(text: str) -> list[str]:
    """Simple word tokenization."""
    return re.findall(r"\b\w+\b", text.lower())


def _get_word_counts(text: str) -> Counter:
    """Get word frequency counts."""
    return Counter(_tokenize(text))


def heuristic_similarity(text1: str, text2: str) -> float:
    """
    Heuristic text similarity using word overlap (Jaccard-like).

    Falls back when embedding service is unavailable.

    Returns:
        Similarity score between 0.0 and 1.0
    """
    words1 = set(_tokenize(text1))
    words2 = set(_tokenize(text2))

    if not words1 and not words2:
        return 1.0  # Both empty = identical
    if not words1 or not words2:
        return 0.0

    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return intersection / union


def heuristic_tfidf_similarity(text1: str, text2: str) -> float:
    """
    TF-IDF inspired similarity without external dependencies.

    More sophisticated than simple word overlap.

    Returns:
        Similarity score between 0.0 and 1.0
    """
    counts1 = _get_word_counts(text1)
    counts2 = _get_word_counts(text2)

    if not counts1 or not counts2:
        return 0.0 if counts1 != counts2 else 1.0

    # Get all words
    all_words = set(counts1.keys()) | set(counts2.keys())

    # Create vectors
    vec1 = [counts1.get(w, 0) for w in all_words]
    vec2 = [counts2.get(w, 0) for w in all_words]

    # Cosine similarity
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)


def heuristic_consensus_prediction(
    responses: Sequence[str],
    task: str = "",
) -> dict[str, Any]:
    """
    Heuristic consensus prediction based on text similarity.

    Falls back when ML-based predictor is unavailable.

    Returns:
        Prediction dict with probability and confidence
    """
    if len(responses) < 2:
        return {
            "probability": 1.0 if responses else 0.0,
            "confidence": 0.3,
            "convergence_trend": "stable",
            "key_factors": ["single_response"],
        }

    # Calculate pairwise similarities
    similarities = []
    for i in range(len(responses)):
        for j in range(i + 1, len(responses)):
            sim = heuristic_tfidf_similarity(responses[i], responses[j])
            similarities.append(sim)

    avg_similarity = sum(similarities) / len(similarities) if similarities else 0.0

    # Map similarity to consensus probability
    # High similarity (>0.6) suggests likely consensus
    probability = min(1.0, avg_similarity * 1.5)

    # Determine trend based on similarity variance
    variance = (
        sum((s - avg_similarity) ** 2 for s in similarities) / len(similarities)
        if len(similarities) > 1
        else 0.0
    )

    if variance < 0.05:
        trend = "stable"
    elif avg_similarity > 0.5:
        trend = "converging"
    else:
        trend = "diverging"

    return {
        "probability": round(probability, 3),
        "confidence": 0.5,  # Lower confidence for heuristic
        "convergence_trend": trend,
        "key_factors": ["heuristic_similarity", f"avg_sim={avg_similarity:.2f}"],
        "estimated_rounds": 3 if probability > 0.7 else 5,
    }


def heuristic_quality_score(text: str) -> float:
    """
    Heuristic quality scoring based on text features.

    Falls back when ML-based scorer is unavailable.

    Returns:
        Quality score between 0.0 and 1.0
    """
    if not text or not text.strip():
        return 0.0

    words = _tokenize(text)
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    # Factor 1: Length (prefer medium-length responses)
    word_count = len(words)
    length_score = (
        min(1.0, word_count / 100)
        if word_count < 500
        else max(0.5, 1.0 - (word_count - 500) / 1000)
    )

    # Factor 2: Sentence structure
    avg_sentence_len = word_count / max(1, len(sentences))
    structure_score = 1.0 if 10 <= avg_sentence_len <= 25 else 0.7

    # Factor 3: Vocabulary diversity
    unique_ratio = len(set(words)) / max(1, len(words))
    diversity_score = min(1.0, unique_ratio * 2)

    # Factor 4: Presence of reasoning indicators
    reasoning_words = {
        "because",
        "therefore",
        "however",
        "although",
        "since",
        "thus",
        "hence",
        "moreover",
        "furthermore",
    }
    reasoning_count = sum(1 for w in words if w in reasoning_words)
    reasoning_score = min(1.0, reasoning_count * 0.2)

    # Weighted combination
    score = (
        0.25 * length_score
        + 0.25 * structure_score
        + 0.25 * diversity_score
        + 0.25 * reasoning_score
    )

    return round(score, 3)


def heuristic_sentiment(text: str) -> dict[str, Any]:
    """
    Heuristic sentiment analysis using word lists.

    Falls back when ML sentiment analyzer is unavailable.

    Returns:
        Sentiment dict with label and confidence
    """
    positive_words = {
        "good",
        "great",
        "excellent",
        "agree",
        "correct",
        "right",
        "yes",
        "positive",
        "beneficial",
        "helpful",
        "improve",
        "success",
        "best",
        "optimal",
    }
    negative_words = {
        "bad",
        "wrong",
        "incorrect",
        "disagree",
        "no",
        "negative",
        "harmful",
        "worse",
        "fail",
        "problem",
        "issue",
        "concern",
        "risk",
        "danger",
    }

    words = set(_tokenize(text))

    pos_count = len(words & positive_words)
    neg_count = len(words & negative_words)
    total = pos_count + neg_count

    if total == 0:
        return {
            "label": "neutral",
            "confidence": 0.3,
            "scores": {"positive": 0.33, "negative": 0.33, "neutral": 0.34},
        }

    pos_ratio = pos_count / total
    neg_ratio = neg_count / total

    if pos_ratio > 0.6:
        label = "positive"
        confidence = min(0.8, pos_ratio)
    elif neg_ratio > 0.6:
        label = "negative"
        confidence = min(0.8, neg_ratio)
    else:
        label = "neutral"
        confidence = 0.5

    return {
        "label": label,
        "confidence": round(confidence, 3),
        "scores": {
            "positive": round(pos_ratio, 3),
            "negative": round(neg_ratio, 3),
            "neutral": round(1.0 - pos_ratio - neg_ratio, 3),
        },
    }


# ============================================================================
# Fallback Service
# ============================================================================


class MLFallbackService:
    """
    ML service with automatic fallback to heuristics.

    Attempts ML operations first, falls back to heuristics on failure.
    """

    _embedding_service: LocalEmbeddingService | None
    _consensus_predictor: ConsensusPredictor | None
    _quality_scorer: QualityScorer | None

    def __init__(self, manager: MLDegradationManager | None = None):
        self._manager = manager or get_ml_manager()
        self._embedding_service = None
        self._consensus_predictor = None
        self._quality_scorer = None

    async def compute_similarity(
        self,
        text1: str,
        text2: str,
        use_ml: bool = True,
    ) -> float:
        """
        Compute text similarity with automatic fallback.

        Args:
            text1: First text
            text2: Second text
            use_ml: Whether to attempt ML-based similarity

        Returns:
            Similarity score between 0.0 and 1.0
        """
        level = self._manager.get_level(MLFeature.EMBEDDINGS)

        if use_ml and level == DegradationLevel.FULL:
            try:
                start = time.perf_counter()
                # Try ML-based similarity
                if self._embedding_service is None:
                    from aragora.ml.embeddings import LocalEmbeddingService

                    self._embedding_service = LocalEmbeddingService()

                emb1 = self._embedding_service.embed(text1)
                emb2 = self._embedding_service.embed(text2)

                # Cosine similarity
                dot = sum(a * b for a, b in zip(emb1, emb2))
                norm1 = math.sqrt(sum(a * a for a in emb1))
                norm2 = math.sqrt(sum(b * b for b in emb2))
                similarity = dot / (norm1 * norm2) if norm1 and norm2 else 0.0

                latency = (time.perf_counter() - start) * 1000
                self._manager.record_success(MLFeature.EMBEDDINGS, latency)

                return similarity

            except (RuntimeError, ValueError, OSError) as e:
                self._manager.record_error(MLFeature.EMBEDDINGS, e)
                # Fall through to heuristic

        # Use heuristic fallback
        if level in (DegradationLevel.LIGHTWEIGHT, DegradationLevel.HEURISTIC):
            return heuristic_tfidf_similarity(text1, text2)
        else:
            return heuristic_similarity(text1, text2)

    async def predict_consensus(
        self,
        responses: Sequence[str],
        task: str = "",
        use_ml: bool = True,
    ) -> dict[str, Any]:
        """
        Predict consensus likelihood with automatic fallback.

        Args:
            responses: Agent responses
            task: Task description
            use_ml: Whether to attempt ML-based prediction

        Returns:
            Prediction dict with probability and confidence
        """
        level = self._manager.get_level(MLFeature.CONSENSUS_PREDICTION)

        if use_ml and level == DegradationLevel.FULL:
            try:
                start = time.perf_counter()

                if self._consensus_predictor is None:
                    from aragora.ml.consensus_predictor import ConsensusPredictor

                    self._consensus_predictor = ConsensusPredictor()

                # Try ML prediction - predict expects Sequence[tuple[str, str]] (agent_id, text)
                prediction = self._consensus_predictor.predict(
                    [("agent", r) for r in responses],
                    task,
                )

                latency = (time.perf_counter() - start) * 1000
                self._manager.record_success(MLFeature.CONSENSUS_PREDICTION, latency)

                return prediction.to_dict()

            except (RuntimeError, ValueError, OSError, ImportError) as e:
                self._manager.record_error(MLFeature.CONSENSUS_PREDICTION, e)

        # Use heuristic fallback
        return heuristic_consensus_prediction(responses, task)

    async def score_quality(
        self,
        text: str,
        use_ml: bool = True,
    ) -> float:
        """
        Score text quality with automatic fallback.

        Args:
            text: Text to score
            use_ml: Whether to attempt ML-based scoring

        Returns:
            Quality score between 0.0 and 1.0
        """
        level = self._manager.get_level(MLFeature.QUALITY_SCORING)

        if use_ml and level == DegradationLevel.FULL:
            try:
                start = time.perf_counter()

                if self._quality_scorer is None:
                    from aragora.ml.quality_scorer import QualityScorer

                    self._quality_scorer = QualityScorer()

                quality_result = self._quality_scorer.score(text)

                latency = (time.perf_counter() - start) * 1000
                self._manager.record_success(MLFeature.QUALITY_SCORING, latency)

                return quality_result.overall

            except (RuntimeError, ValueError, OSError, ImportError) as e:
                self._manager.record_error(MLFeature.QUALITY_SCORING, e)

        # Use heuristic fallback
        return heuristic_quality_score(text)

    async def analyze_sentiment(
        self,
        text: str,
        use_ml: bool = True,
    ) -> dict[str, Any]:
        """
        Analyze sentiment with automatic fallback.

        Args:
            text: Text to analyze
            use_ml: Whether to attempt ML-based analysis

        Returns:
            Sentiment dict with label and confidence
        """
        _level = self._manager.get_level(MLFeature.SENTIMENT_ANALYSIS)

        # For now, always use heuristic (no ML sentiment model integrated)
        # Level check reserved for future ML sentiment model integration
        return heuristic_sentiment(text)

    def get_status(self) -> dict[str, Any]:
        """Get degradation status."""
        return self._manager.get_status()


# ============================================================================
# Global Instances
# ============================================================================

_global_manager: MLDegradationManager | None = None
_global_fallback: MLFallbackService | None = None


def get_ml_manager() -> MLDegradationManager:
    """Get or create global degradation manager."""
    global _global_manager
    if _global_manager is None:
        _global_manager = MLDegradationManager()
    return _global_manager


def get_ml_fallback() -> MLFallbackService:
    """Get or create global fallback service."""
    global _global_fallback
    if _global_fallback is None:
        _global_fallback = MLFallbackService(get_ml_manager())
    return _global_fallback


def force_degradation(
    feature: MLFeature,
    level: DegradationLevel,
    reason: str = "manual",
) -> None:
    """Force degradation of a feature (for testing or emergency)."""
    get_ml_manager().set_level(feature, level, reason)


def reset_degradation() -> None:
    """Reset all features to full ML (for testing)."""
    manager = get_ml_manager()
    for feature in MLFeature:
        manager.set_level(feature, DegradationLevel.FULL, "reset")


__all__ = [
    "MLFeature",
    "DegradationLevel",
    "FeatureStatus",
    "DegradationEvent",
    "MLDegradationManager",
    "MLFallbackService",
    "get_ml_manager",
    "get_ml_fallback",
    "force_degradation",
    "reset_degradation",
    # Heuristic fallbacks
    "heuristic_similarity",
    "heuristic_tfidf_similarity",
    "heuristic_consensus_prediction",
    "heuristic_quality_score",
    "heuristic_sentiment",
]
