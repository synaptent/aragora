"""
Consensus Predictor for Debate Outcome Estimation.

Predicts likelihood of consensus before full debate completion.
Uses features from agent responses to estimate convergence probability.

Usage:
    from aragora.ml import ConsensusPredictor, get_consensus_predictor

    predictor = get_consensus_predictor()
    prediction = predictor.predict(responses, task_description)

    if prediction.likely_consensus:
        # Can potentially terminate early
        pass

    # Track prediction accuracy over time
    predictor.record_outcome(debate_id, actual_reached_consensus=True)
"""

from __future__ import annotations

import importlib
import logging
import threading
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any
from collections.abc import Sequence
from collections import defaultdict

try:
    np: ModuleType | None = importlib.import_module("numpy")
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

logger = logging.getLogger(__name__)


@dataclass
class ConsensusPrediction:
    """Prediction of consensus likelihood."""

    probability: float  # 0.0 - 1.0 probability of consensus
    confidence: float  # Prediction confidence
    estimated_rounds: int  # Estimated rounds to consensus
    convergence_trend: str  # "converging", "diverging", "stable"
    key_factors: list[str]  # Factors influencing prediction
    features: dict[str, float] = field(default_factory=dict)

    @property
    def likely_consensus(self) -> bool:
        """Check if consensus is likely (>70% probability)."""
        return self.probability >= 0.7 and self.confidence >= 0.5

    @property
    def early_termination_safe(self) -> bool:
        """Check if safe to terminate debate early."""
        return self.probability >= 0.85 and self.confidence >= 0.7

    @property
    def needs_intervention(self) -> bool:
        """Check if debate needs intervention (diverging)."""
        return self.convergence_trend == "diverging" and self.probability < 0.3

    def to_dict(self) -> dict[str, Any]:
        return {
            "probability": round(self.probability, 3),
            "confidence": round(self.confidence, 3),
            "estimated_rounds": self.estimated_rounds,
            "convergence_trend": self.convergence_trend,
            "likely_consensus": self.likely_consensus,
            "key_factors": self.key_factors,
        }


@dataclass
class ConsensusPredictorConfig:
    """Configuration for consensus predictor."""

    # Feature weights
    weight_semantic_similarity: float = 0.35
    weight_stance_alignment: float = 0.25
    weight_quality_variance: float = 0.15
    weight_historical: float = 0.15
    weight_round_progress: float = 0.10

    # Thresholds
    high_similarity_threshold: float = 0.8
    low_variance_threshold: float = 0.1
    convergence_delta_threshold: float = 0.05

    # Use embeddings for semantic similarity
    use_embeddings: bool = True


@dataclass
class ResponseFeatures:
    """Features extracted from a single response."""

    agent_id: str
    text: str
    stance: str | None = None  # "agree", "disagree", "neutral"
    confidence: float = 0.5
    quality_score: float = 0.5
    embedding: list[float] | None = None


class ConsensusPredictor:
    """Predicts consensus likelihood in multi-agent debates.

    Uses a combination of:
    1. Semantic similarity between responses
    2. Stance alignment detection
    3. Quality score variance
    4. Historical debate outcomes
    5. Round progression patterns

    Can help decide when to terminate debates early or intervene.
    """

    def __init__(self, config: ConsensusPredictorConfig | None = None):
        """Initialize the consensus predictor.

        Args:
            config: Predictor configuration
        """
        self.config = config or ConsensusPredictorConfig()
        self._embedding_service: Any | None = None
        self._quality_scorer: Any | None = None
        self._historical_outcomes: dict[str, bool] = {}
        self._prediction_accuracy: list[tuple[float, bool]] = []

    def _get_embedding_service(self):
        """Lazy load embedding service."""
        if self._embedding_service is None and self.config.use_embeddings:
            try:
                from aragora.ml.embeddings import get_embedding_service

                self._embedding_service = get_embedding_service()
            except (ImportError, RuntimeError, OSError, ValueError) as e:
                logger.warning("Could not load embedding service: %s", e)
                self.config.use_embeddings = False
        return self._embedding_service

    def _get_quality_scorer(self):
        """Lazy load quality scorer."""
        if self._quality_scorer is None:
            try:
                from aragora.ml.quality_scorer import get_quality_scorer

                self._quality_scorer = get_quality_scorer()
            except (ImportError, RuntimeError, ValueError) as e:
                logger.warning("Could not load quality scorer: %s", e)
        return self._quality_scorer

    def _extract_response_features(
        self,
        responses: Sequence[tuple[str, str]],  # (agent_id, text) pairs
        context: str | None = None,
    ) -> list[ResponseFeatures]:
        """Extract features from responses."""
        features = []
        embedding_service = self._get_embedding_service()
        quality_scorer = self._get_quality_scorer()

        for agent_id, text in responses:
            rf = ResponseFeatures(agent_id=agent_id, text=text)

            # Get quality score
            if quality_scorer:
                try:
                    score = quality_scorer.score(text, context)
                    rf.quality_score = score.overall
                    rf.confidence = score.confidence
                except (RuntimeError, ValueError, TypeError) as e:
                    logger.debug("Quality scoring failed: %s", e)

            # Get embedding
            if embedding_service:
                try:
                    rf.embedding = embedding_service.embed(text[:1000])
                except (RuntimeError, ValueError, OSError) as e:
                    logger.debug("Embedding failed: %s", e)

            # Detect stance (simple heuristic)
            rf.stance = self._detect_stance(text)

            features.append(rf)

        return features

    def _detect_stance(self, text: str) -> str:
        """Detect stance from text (simple heuristic)."""
        text_lower = text.lower()

        agree_indicators = [
            "i agree",
            "correct",
            "that's right",
            "exactly",
            "good point",
            "well said",
            "i concur",
            "absolutely",
            "building on",
            "in addition to",
            "furthermore",
        ]
        disagree_indicators = [
            "i disagree",
            "incorrect",
            "that's wrong",
            "however",
            "on the contrary",
            "actually",
            "but",
            "not quite",
            "i would argue",
            "the issue with",
            "problem with",
        ]

        agree_count = sum(1 for phrase in agree_indicators if phrase in text_lower)
        disagree_count = sum(1 for phrase in disagree_indicators if phrase in text_lower)

        if agree_count > disagree_count + 1:
            return "agree"
        elif disagree_count > agree_count + 1:
            return "disagree"
        return "neutral"

    def _calculate_semantic_similarity(
        self,
        features: list[ResponseFeatures],
    ) -> float:
        """Calculate pairwise semantic similarity between responses."""
        embeddings = [f.embedding for f in features if f.embedding is not None]

        if len(embeddings) < 2:
            return 0.5  # Default when embeddings unavailable

        numpy = np
        if numpy is None:
            return 0.5

        # Calculate pairwise cosine similarities
        similarities = []
        for i in range(len(embeddings)):
            for j in range(i + 1, len(embeddings)):
                a = numpy.array(embeddings[i])
                b = numpy.array(embeddings[j])
                sim = float(numpy.dot(a, b) / (numpy.linalg.norm(a) * numpy.linalg.norm(b)))
                similarities.append(sim)

        return float(numpy.mean(similarities)) if similarities else 0.5

    def _calculate_stance_alignment(
        self,
        features: list[ResponseFeatures],
    ) -> float:
        """Calculate stance alignment score."""
        if not features:
            return 0.5

        stances = [f.stance or "neutral" for f in features]
        stance_counts: dict[str, int] = defaultdict(int)
        for s in stances:
            stance_counts[s] += 1

        # If most agents agree or are neutral, higher alignment
        total = len(stances)
        if total == 0:
            return 0.5

        # Majority stance ratio
        max_count = max(stance_counts.values())
        majority_ratio = max_count / total

        # Penalize disagreement
        disagree_ratio = stance_counts.get("disagree", 0) / total

        return max(0.0, min(1.0, majority_ratio - disagree_ratio * 0.5))

    def _calculate_quality_variance(
        self,
        features: list[ResponseFeatures],
    ) -> float:
        """Calculate variance in quality scores (lower is better for consensus)."""
        scores = [f.quality_score for f in features]
        if len(scores) < 2:
            return 0.0

        numpy = np
        if numpy is not None:
            variance = float(numpy.var(scores))
        else:
            mean = sum(scores) / len(scores)
            variance = sum((score - mean) ** 2 for score in scores) / len(scores)
        # Normalize to 0-1 (assuming max variance of 0.25)
        normalized = min(1.0, variance / 0.25)
        return normalized

    def _estimate_convergence_trend(
        self,
        current_similarity: float,
        previous_similarities: list[float] | None = None,
    ) -> str:
        """Estimate convergence trend."""
        if previous_similarities is None or len(previous_similarities) < 2:
            return "stable"

        # Add current to history
        history = previous_similarities + [current_similarity]

        # Calculate trend
        recent_values = history[-3:] if len(history) >= 3 else history[-1:]
        older_values = history[:-3] if len(history) > 3 else history[:1]
        numpy = np
        if numpy is not None:
            recent = float(numpy.mean(recent_values))
            older = float(numpy.mean(older_values))
        else:
            recent = sum(recent_values) / len(recent_values)
            older = sum(older_values) / len(older_values)

        delta = recent - older

        if delta > self.config.convergence_delta_threshold:
            return "converging"
        elif delta < -self.config.convergence_delta_threshold:
            return "diverging"
        return "stable"

    def _get_historical_factor(self, task_type: str | None = None) -> float:
        """Get historical consensus rate factor."""
        if not self._prediction_accuracy:
            return 0.5

        # Use recent predictions
        recent = self._prediction_accuracy[-100:]
        if not recent:
            return 0.5

        # Calculate accuracy-weighted factor
        correct = sum(1 for pred, actual in recent if (pred >= 0.5) == actual)
        return correct / len(recent)

    def predict(
        self,
        responses: Sequence[tuple[str, str]],
        context: str | None = None,
        current_round: int = 1,
        total_rounds: int = 3,
        previous_similarities: list[float] | None = None,
    ) -> ConsensusPrediction:
        """Predict consensus likelihood.

        Args:
            responses: List of (agent_id, response_text) tuples
            context: Optional task/debate context
            current_round: Current debate round (1-indexed)
            total_rounds: Total planned rounds
            previous_similarities: Similarity scores from previous rounds

        Returns:
            Consensus prediction with probability and confidence
        """
        if not responses:
            return ConsensusPrediction(
                probability=0.0,
                confidence=0.0,
                estimated_rounds=total_rounds,
                convergence_trend="stable",
                key_factors=["no_responses"],
            )

        # Extract features
        features = self._extract_response_features(responses, context)

        # Calculate component scores
        semantic_sim = self._calculate_semantic_similarity(features)
        stance_align = self._calculate_stance_alignment(features)
        quality_var = self._calculate_quality_variance(features)
        historical = self._get_historical_factor()

        # Round progress factor (later rounds more likely to have consensus)
        round_progress = current_round / total_rounds

        # Combine scores
        probability = (
            self.config.weight_semantic_similarity * semantic_sim
            + self.config.weight_stance_alignment * stance_align
            + self.config.weight_quality_variance * (1 - quality_var)  # Invert variance
            + self.config.weight_historical * historical
            + self.config.weight_round_progress * round_progress
        )

        # Determine convergence trend
        convergence_trend = self._estimate_convergence_trend(semantic_sim, previous_similarities)

        # Adjust probability based on trend
        if convergence_trend == "converging":
            probability = min(1.0, probability * 1.15)
        elif convergence_trend == "diverging":
            probability = max(0.0, probability * 0.85)

        # Estimate rounds to consensus
        if probability >= 0.9:
            estimated_rounds = current_round
        elif probability >= 0.7:
            estimated_rounds = min(current_round + 1, total_rounds)
        elif probability >= 0.5:
            estimated_rounds = min(current_round + 2, total_rounds)
        else:
            estimated_rounds = total_rounds

        # Calculate confidence
        confidence = min(1.0, len(responses) / 3)  # More responses = more confident
        if current_round > 1:
            confidence *= 1.1  # More confident after first round
        confidence = min(1.0, confidence)

        # Identify key factors
        key_factors = []
        if semantic_sim >= self.config.high_similarity_threshold:
            key_factors.append("high_semantic_similarity")
        if semantic_sim < 0.4:
            key_factors.append("low_semantic_similarity")
        if stance_align >= 0.7:
            key_factors.append("stance_agreement")
        if stance_align < 0.3:
            key_factors.append("stance_disagreement")
        if quality_var < self.config.low_variance_threshold:
            key_factors.append("consistent_quality")
        if convergence_trend == "converging":
            key_factors.append("converging_trend")
        if convergence_trend == "diverging":
            key_factors.append("diverging_trend")

        return ConsensusPrediction(
            probability=probability,
            confidence=confidence,
            estimated_rounds=estimated_rounds,
            convergence_trend=convergence_trend,
            key_factors=key_factors,
            features={
                "semantic_similarity": semantic_sim,
                "stance_alignment": stance_align,
                "quality_variance": quality_var,
                "round_progress": round_progress,
                "historical_factor": historical,
            },
        )

    def predict_batch(
        self,
        debate_states: Sequence[dict[str, Any]],
    ) -> list[ConsensusPrediction]:
        """Predict consensus for multiple debates.

        Args:
            debate_states: List of debate state dicts with:
                - responses: List of (agent_id, text) tuples
                - context: Optional task context
                - current_round: Current round number
                - total_rounds: Total rounds
                - previous_similarities: Optional similarity history

        Returns:
            List of consensus predictions
        """
        return [
            self.predict(
                responses=state.get("responses", []),
                context=state.get("context"),
                current_round=state.get("current_round", 1),
                total_rounds=state.get("total_rounds", 3),
                previous_similarities=state.get("previous_similarities"),
            )
            for state in debate_states
        ]

    def record_outcome(
        self,
        debate_id: str,
        reached_consensus: bool,
        prediction: ConsensusPrediction | None = None,
    ) -> None:
        """Record actual debate outcome for calibration.

        Args:
            debate_id: Unique debate identifier
            reached_consensus: Whether consensus was actually reached
            prediction: The prediction made for this debate
        """
        self._historical_outcomes[debate_id] = reached_consensus

        if prediction is not None:
            self._prediction_accuracy.append((prediction.probability, reached_consensus))

            # Keep only recent history
            if len(self._prediction_accuracy) > 1000:
                self._prediction_accuracy = self._prediction_accuracy[-1000:]

        logger.debug("Recorded outcome for %s: consensus=%s", debate_id, reached_consensus)

    def get_calibration_stats(self) -> dict[str, float]:
        """Get calibration statistics.

        Returns:
            Dict with accuracy, precision, recall metrics
        """
        if not self._prediction_accuracy:
            return {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "samples": 0}

        predictions = [(p >= 0.5, actual) for p, actual in self._prediction_accuracy]

        tp = sum(1 for pred, actual in predictions if pred and actual)
        fp = sum(1 for pred, actual in predictions if pred and not actual)
        tn = sum(1 for pred, actual in predictions if not pred and not actual)
        fn = sum(1 for pred, actual in predictions if not pred and actual)

        total = len(predictions)
        accuracy = (tp + tn) / total if total > 0 else 0.0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        return {
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "samples": total,
        }


# Global instance
_consensus_predictor: ConsensusPredictor | None = None
_consensus_predictor_lock = threading.Lock()  # Protects singleton initialization


def get_consensus_predictor() -> ConsensusPredictor:
    """Get or create the global consensus predictor instance.

    Thread-safe singleton pattern using double-checked locking.
    """
    global _consensus_predictor
    # Fast path: return existing instance without lock
    if _consensus_predictor is not None:
        return _consensus_predictor

    # Slow path: acquire lock for initialization
    with _consensus_predictor_lock:
        # Double-check after acquiring lock
        if _consensus_predictor is None:
            _consensus_predictor = ConsensusPredictor()
        return _consensus_predictor
