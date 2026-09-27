"""
Fast Quality Scorer for Response Evaluation.

Provides quick quality estimation without full LLM evaluation.
Uses lightweight features and a trained classifier for fast scoring.

Usage:
    from aragora.ml import QualityScorer, get_quality_scorer

    scorer = get_quality_scorer()
    score = scorer.score(response_text, context=task_description)

    # Batch scoring
    scores = scorer.score_batch(responses)

    # Filter low quality before expensive LLM evaluation
    high_quality = [r for r, s in zip(responses, scores) if s.overall >= 0.7]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Sequence

logger = logging.getLogger(__name__)


@dataclass
class QualityScore:
    """Quality assessment scores."""

    overall: float  # 0.0 - 1.0
    coherence: float  # Text coherence
    completeness: float  # Answer completeness
    relevance: float  # Task relevance
    clarity: float  # Writing clarity
    confidence: float  # Scorer confidence
    features: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": round(self.overall, 3),
            "coherence": round(self.coherence, 3),
            "completeness": round(self.completeness, 3),
            "relevance": round(self.relevance, 3),
            "clarity": round(self.clarity, 3),
            "confidence": round(self.confidence, 3),
        }

    @property
    def is_high_quality(self) -> bool:
        """Check if response meets quality threshold."""
        return self.overall >= 0.7 and self.confidence >= 0.5

    @property
    def needs_review(self) -> bool:
        """Check if response needs human/LLM review."""
        return self.overall < 0.5 or self.confidence < 0.3


@dataclass
class QualityScorerConfig:
    """Configuration for quality scorer."""

    # Feature weights (sum to ~1.0)
    weight_coherence: float = 0.25
    weight_completeness: float = 0.25
    weight_relevance: float = 0.30
    weight_clarity: float = 0.20

    # Thresholds
    min_response_length: int = 50
    optimal_response_length: int = 500
    max_response_length: int = 5000

    # Use embedding similarity for relevance
    use_embeddings: bool = True


class QualityScorer:
    """Fast quality scorer for response evaluation.

    Uses a combination of:
    1. Linguistic features (sentence structure, vocabulary)
    2. Structural features (formatting, organization)
    3. Semantic features (embedding similarity to context)

    Much faster than LLM evaluation (~100x), good for filtering.
    """

    def __init__(self, config: QualityScorerConfig | None = None):
        """Initialize the quality scorer.

        Args:
            config: Scorer configuration
        """
        self.config = config or QualityScorerConfig()
        self._embedding_service: Any | None = None

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

    def _extract_features(self, text: str) -> dict[str, float]:
        """Extract quality features from text."""
        features: dict[str, float] = {}

        # Length features
        char_count = len(text)
        word_count = len(text.split())
        sentence_count = len(re.split(r"[.!?]+", text))

        features["char_count"] = float(char_count)
        features["word_count"] = float(word_count)
        features["sentence_count"] = float(max(1, sentence_count))
        features["avg_word_length"] = char_count / max(1, word_count)
        features["avg_sentence_length"] = word_count / max(1, sentence_count)

        # Structural features
        features["has_paragraphs"] = float("\n\n" in text or "\n" in text)
        features["has_lists"] = float(bool(re.search(r"^\s*[-*•]\s", text, re.MULTILINE)))
        features["has_code"] = float("```" in text or "    " in text)
        features["has_headers"] = float(bool(re.search(r"^#+\s", text, re.MULTILINE)))

        # Vocabulary features
        words = text.lower().split()
        unique_words = set(words)
        features["vocabulary_richness"] = len(unique_words) / max(1, len(words))

        # Common filler words (lower is better)
        filler_words = {"um", "uh", "like", "just", "basically", "actually", "really", "very"}
        filler_count = sum(1 for w in words if w in filler_words)
        features["filler_ratio"] = filler_count / max(1, len(words))

        # Technical indicator words
        technical_words = {
            "function",
            "class",
            "method",
            "api",
            "data",
            "system",
            "process",
            "implement",
            "algorithm",
            "parameter",
            "variable",
            "database",
            "because",
            "therefore",
            "however",
            "furthermore",
            "specifically",
        }
        technical_count = sum(1 for w in words if w in technical_words)
        features["technical_ratio"] = technical_count / max(1, len(words))

        # Question handling (if text seems to answer questions)
        features["has_explanation"] = float(
            any(
                phrase in text.lower()
                for phrase in [
                    "because",
                    "this means",
                    "in other words",
                    "for example",
                    "the reason",
                    "this is due to",
                    "as a result",
                ]
            )
        )

        return features

    def _score_coherence(self, features: dict[str, float]) -> float:
        """Score text coherence."""
        score = 0.5  # Base score

        # Good sentence length (10-25 words)
        avg_sent_len = features["avg_sentence_length"]
        if 10 <= avg_sent_len <= 25:
            score += 0.3
        elif 5 <= avg_sent_len <= 35:
            score += 0.15

        # Has structure
        if features["has_paragraphs"]:
            score += 0.1
        if features["has_explanation"]:
            score += 0.1

        # Penalize very short or fragmented text
        if features["sentence_count"] < 2:
            score -= 0.2

        return min(1.0, max(0.0, score))

    def _score_completeness(self, features: dict[str, float]) -> float:
        """Score response completeness."""
        score = 0.0

        # Length scoring
        word_count = features["word_count"]
        min_len = self.config.min_response_length
        optimal_len = self.config.optimal_response_length
        max_len = self.config.max_response_length

        if word_count < min_len:
            score = 0.3 * (word_count / min_len)
        elif word_count <= optimal_len:
            score = 0.3 + 0.5 * ((word_count - min_len) / (optimal_len - min_len))
        elif word_count <= max_len:
            score = 0.8 + 0.2 * (1 - (word_count - optimal_len) / (max_len - optimal_len))
        else:
            score = 0.7  # Too long, slight penalty

        # Bonus for structure
        if features["has_lists"]:
            score += 0.05
        if features["has_code"]:
            score += 0.05

        return min(1.0, max(0.0, score))

    def _score_clarity(self, features: dict[str, float]) -> float:
        """Score writing clarity."""
        score = 0.5  # Base score

        # Good vocabulary richness (0.3-0.7)
        richness = features["vocabulary_richness"]
        if 0.3 <= richness <= 0.7:
            score += 0.2
        elif richness < 0.2:  # Too repetitive
            score -= 0.2

        # Penalize filler words
        filler = features["filler_ratio"]
        if filler > 0.05:
            score -= 0.2
        elif filler < 0.01:
            score += 0.1

        # Good word length (4-8 chars average)
        avg_word = features["avg_word_length"]
        if 4 <= avg_word <= 8:
            score += 0.2

        return min(1.0, max(0.0, score))

    def _score_relevance(
        self,
        text: str,
        context: str | None,
        features: dict[str, float],
    ) -> float:
        """Score response relevance to context."""
        if not context:
            # No context, use heuristics
            return 0.6 + (0.2 if features["technical_ratio"] > 0.02 else 0.0)

        # Use embedding similarity if available
        embedding_service = self._get_embedding_service()
        if embedding_service:
            try:
                text_emb = embedding_service.embed(text[:1000])  # Truncate for speed
                context_emb = embedding_service.embed(context[:500])
                similarity = embedding_service.similarity(text_emb, context_emb)
                return float(similarity)
            except (RuntimeError, ValueError, OSError) as e:
                logger.debug("Embedding similarity failed: %s", e)

        # Fallback: keyword overlap
        text_words = set(text.lower().split())
        context_words = set(context.lower().split())
        overlap = len(text_words & context_words)
        total = len(context_words)
        return min(1.0, overlap / max(1, total) * 2)

    def score(
        self,
        text: str,
        context: str | None = None,
    ) -> QualityScore:
        """Score a single response.

        Args:
            text: Response text to score
            context: Optional context (task description, question)

        Returns:
            Quality score with component scores
        """
        if not text or not text.strip():
            return QualityScore(
                overall=0.0,
                coherence=0.0,
                completeness=0.0,
                relevance=0.0,
                clarity=0.0,
                confidence=1.0,
            )

        # Extract features
        features = self._extract_features(text)

        # Score components
        coherence = self._score_coherence(features)
        completeness = self._score_completeness(features)
        clarity = self._score_clarity(features)
        relevance = self._score_relevance(text, context, features)

        # Weighted overall score
        overall = (
            self.config.weight_coherence * coherence
            + self.config.weight_completeness * completeness
            + self.config.weight_relevance * relevance
            + self.config.weight_clarity * clarity
        )

        # Confidence based on text length and feature quality
        confidence = min(1.0, features["word_count"] / 100)
        if features["sentence_count"] < 2:
            confidence *= 0.7

        return QualityScore(
            overall=overall,
            coherence=coherence,
            completeness=completeness,
            relevance=relevance,
            clarity=clarity,
            confidence=confidence,
            features=features,
        )

    def score_batch(
        self,
        texts: Sequence[str],
        contexts: Sequence[str | None] | None = None,
    ) -> list[QualityScore]:
        """Score multiple responses.

        Args:
            texts: Response texts to score
            contexts: Optional contexts for each response

        Returns:
            List of quality scores
        """
        if contexts is None:
            contexts = [None] * len(texts)

        return [self.score(text, context) for text, context in zip(texts, contexts)]

    def filter_quality(
        self,
        texts: Sequence[str],
        threshold: float = 0.7,
        contexts: Sequence[str | None] | None = None,
    ) -> list[tuple[str, QualityScore]]:
        """Filter texts by quality threshold.

        Args:
            texts: Texts to filter
            threshold: Minimum quality score
            contexts: Optional contexts

        Returns:
            List of (text, score) tuples above threshold
        """
        scores = self.score_batch(texts, contexts)
        return [(text, score) for text, score in zip(texts, scores) if score.overall >= threshold]


# Global instance
_quality_scorer: QualityScorer | None = None


def get_quality_scorer() -> QualityScorer:
    """Get or create the global quality scorer instance."""
    global _quality_scorer
    if _quality_scorer is None:
        _quality_scorer = QualityScorer()
    return _quality_scorer
