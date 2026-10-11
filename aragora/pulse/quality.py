"""
Topic Quality Filter for Pulse System.

Filters and scores topics based on content quality signals,
removing spam, clickbait, and low-value content.

Quality signals:
- Text length and substance
- Clickbait patterns
- Information density
- Question/statement structure
- Hashtag/mention spam
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from aragora.pulse.ingestor import TrendingTopic

logger = logging.getLogger(__name__)


@dataclass
class QualityScore:
    """Quality assessment for a topic."""

    topic: TrendingTopic
    overall_score: float  # 0.0 - 1.0 (higher = better quality)
    is_acceptable: bool  # Meets minimum quality threshold
    signals: dict[str, float] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


# Clickbait patterns
CLICKBAIT_PATTERNS = [
    r"\bwon'?t believe\b",
    r"\bshocked\b",
    r"\bone weird trick\b",
    r"\bdoctors hate\b",
    r"\byou'?ll never guess\b",
    r"\bthis is why\b",
    r"\bbreaking\s*:\s*",
    r"\bwaiting for you\b",
    r"\bfind out\b.*\bnow\b",
    r"\bnumber \d+ will\b",
    r"\bmust see\b",
    r"\binsane\b",
    r"\bcannot unsee\b",
    r"\bliterally crying\b",
    r"\bi'?m dead\b",
]

# Spam indicators
SPAM_INDICATORS = [
    r"bit\.ly/",
    r"tinyurl\.com/",
    r"goo\.gl/",
    r"FREE\s*\$",
    r"WIN\s*\$",
    r"click here",
    r"act now",
    r"limited time",
    r"🚀{3,}",  # Excessive rocket emojis
    r"💰{3,}",  # Excessive money emojis
    r"#\w+\s*#\w+\s*#\w+\s*#\w+\s*#\w+",  # 5+ consecutive hashtags
]

# Low-value content patterns
LOW_VALUE_PATTERNS = [
    r"^\s*\.\.\.\s*$",  # Just ellipsis
    r"^[\W\s]+$",  # Only punctuation/whitespace
    r"^(lol|lmao|rofl|omg)[\s!]*$",  # Just reactions
    r"^same\s*$",  # Just "same"
    r"^this\s*$",  # Just "this"
    r"^👆|^👇|^☝️",  # Just pointing emojis
]

# Quality indicator patterns (positive signals)
QUALITY_INDICATORS = [
    r"\banalysis\b",
    r"\bresearch\b",
    r"\bstudy\b",
    r"\bdata\b",
    r"\bevidence\b",
    r"\breport\b",
    r"\bexplain(s|ed|ing)?\b",
    r"\bcompare\b",
    r"\bversus\b|\bvs\.?\b",
    r"\bpros and cons\b",
    r"\badvantages?\b",
    r"\bdisadvantages?\b",
    r"\bimplications?\b",
    r"\bconsequences?\b",
]


class TopicQualityFilter:
    """
    Filters and scores topics based on content quality.

    Usage:
        filter = TopicQualityFilter()
        scored = filter.score_topic(topic)
        if scored.is_acceptable:
            print(f"Quality: {scored.overall_score:.2f}")

        # Filter a batch
        filtered = filter.filter_topics(topics, min_quality=0.5)
    """

    def __init__(
        self,
        min_quality_threshold: float = 0.40,
        min_text_length: int = 10,
        max_hashtag_ratio: float = 0.30,
        max_emoji_ratio: float = 0.20,
        additional_blocklist: set[str] | None = None,
    ):
        """
        Initialize the quality filter.

        Args:
            min_quality_threshold: Minimum quality score to be acceptable
            min_text_length: Minimum topic text length
            max_hashtag_ratio: Max ratio of hashtags to words
            max_emoji_ratio: Max ratio of emojis to characters
            additional_blocklist: Additional terms to filter
        """
        self.min_quality_threshold = min_quality_threshold
        self.min_text_length = min_text_length
        self.max_hashtag_ratio = max_hashtag_ratio
        self.max_emoji_ratio = max_emoji_ratio
        self.blocklist = additional_blocklist or set()

        # Compile patterns for efficiency
        self._clickbait_patterns = [re.compile(p, re.IGNORECASE) for p in CLICKBAIT_PATTERNS]
        self._spam_patterns = [re.compile(p, re.IGNORECASE) for p in SPAM_INDICATORS]
        self._low_value_patterns = [re.compile(p, re.IGNORECASE) for p in LOW_VALUE_PATTERNS]
        self._quality_patterns = [re.compile(p, re.IGNORECASE) for p in QUALITY_INDICATORS]

    def score_topic(self, topic: TrendingTopic) -> QualityScore:
        """
        Calculate quality score for a topic.

        Args:
            topic: TrendingTopic to evaluate

        Returns:
            QualityScore with overall score and signals
        """
        text = topic.topic
        signals: dict[str, float] = {}
        issues: list[str] = []

        # Length check
        length_score = self._score_length(text)
        signals["length"] = length_score
        if length_score < 0.3:
            issues.append(f"Text too short ({len(text)} chars)")

        # Clickbait check
        clickbait_score = self._score_clickbait(text)
        signals["clickbait"] = clickbait_score
        if clickbait_score < 0.5:
            issues.append("Contains clickbait patterns")

        # Spam check
        spam_score = self._score_spam(text)
        signals["spam"] = spam_score
        if spam_score < 0.5:
            issues.append("Contains spam indicators")

        # Low-value check
        substance_score = self._score_substance(text)
        signals["substance"] = substance_score
        if substance_score < 0.3:
            issues.append("Low substance content")

        # Quality indicators (positive)
        quality_boost = self._score_quality_indicators(text)
        signals["quality_indicators"] = quality_boost

        # Hashtag/emoji spam
        structure_score = self._score_structure(text)
        signals["structure"] = structure_score
        if structure_score < 0.5:
            issues.append("Excessive hashtags or emojis")

        # Blocklist check
        blocklist_score = self._score_blocklist(text)
        signals["blocklist"] = blocklist_score
        if blocklist_score < 1.0:
            issues.append("Contains blocked terms")

        # Calculate overall score (weighted average)
        weights = {
            "length": 0.10,
            "clickbait": 0.20,
            "spam": 0.25,
            "substance": 0.15,
            "quality_indicators": 0.10,
            "structure": 0.10,
            "blocklist": 0.10,
        }

        overall = sum(signals[k] * weights[k] for k in weights)

        # Apply quality boost
        overall = min(1.0, overall + quality_boost * 0.1)

        return QualityScore(
            topic=topic,
            overall_score=overall,
            is_acceptable=overall >= self.min_quality_threshold,
            signals=signals,
            issues=issues,
        )

    def filter_topics(
        self,
        topics: list[TrendingTopic],
        min_quality: float | None = None,
    ) -> list[QualityScore]:
        """
        Filter topics by quality, returning only acceptable ones.

        Args:
            topics: List of TrendingTopic objects
            min_quality: Optional override for minimum quality threshold

        Returns:
            List of QualityScore objects that meet threshold
        """
        threshold = min_quality if min_quality is not None else self.min_quality_threshold

        scored = [self.score_topic(t) for t in topics]
        filtered = [s for s in scored if s.overall_score >= threshold]

        # Sort by quality descending
        filtered.sort(key=lambda x: x.overall_score, reverse=True)

        logger.debug(
            "Quality filter: %s topics -> %s acceptable (threshold=%.2f)",
            len(topics),
            len(filtered),
            threshold,
        )

        return filtered

    def _score_length(self, text: str) -> float:
        """Score based on text length."""
        length = len(text.strip())
        if length < self.min_text_length:
            return 0.0
        if length < 20:
            return 0.3
        if length < 50:
            return 0.6
        if length < 100:
            return 0.8
        return 1.0

    def _score_clickbait(self, text: str) -> float:
        """Score based on clickbait patterns (higher = less clickbait)."""
        matches = sum(1 for p in self._clickbait_patterns if p.search(text))
        if matches >= 3:
            return 0.0
        if matches >= 2:
            return 0.3
        if matches >= 1:
            return 0.6
        return 1.0

    def _score_spam(self, text: str) -> float:
        """Score based on spam indicators (higher = less spam)."""
        matches = sum(1 for p in self._spam_patterns if p.search(text))
        if matches >= 2:
            return 0.0
        if matches >= 1:
            return 0.4
        return 1.0

    def _score_substance(self, text: str) -> float:
        """Score based on content substance."""
        # Check for low-value patterns
        for pattern in self._low_value_patterns:
            if pattern.match(text.strip()):
                return 0.0

        # Count actual words (not hashtags or mentions)
        words = re.findall(r"\b[a-zA-Z]{2,}\b", text)
        if len(words) < 3:
            return 0.2
        if len(words) < 5:
            return 0.5
        if len(words) < 10:
            return 0.7
        return 1.0

    def _score_quality_indicators(self, text: str) -> float:
        """Score based on quality indicator presence."""
        matches = sum(1 for p in self._quality_patterns if p.search(text))
        return min(1.0, matches * 0.25)

    def _score_structure(self, text: str) -> float:
        """Score based on structural quality (hashtags, emojis, etc.)."""
        # Count hashtags
        hashtags = len(re.findall(r"#\w+", text))
        words = len(re.findall(r"\b\w+\b", text))
        hashtag_ratio = hashtags / max(1, words)

        # Count emojis (basic pattern)
        emoji_pattern = re.compile(
            "["
            "\U0001f600-\U0001f64f"  # emoticons
            "\U0001f300-\U0001f5ff"  # symbols & pictographs
            "\U0001f680-\U0001f6ff"  # transport & map symbols
            "\U0001f1e0-\U0001f1ff"  # flags
            "\U00002702-\U000027b0"  # dingbats
            "\U000024c2-\U0001f251"
            "]+",
            flags=re.UNICODE,
        )
        emojis = len(emoji_pattern.findall(text))
        emoji_ratio = emojis / max(1, len(text))

        score = 1.0

        if hashtag_ratio > self.max_hashtag_ratio:
            score -= 0.3
        if emoji_ratio > self.max_emoji_ratio:
            score -= 0.3

        # Check for ALL CAPS (shouting)
        upper_ratio = sum(1 for c in text if c.isupper()) / max(1, len(text))
        if upper_ratio > 0.7 and len(text) > 10:
            score -= 0.2

        return max(0.0, score)

    def _score_blocklist(self, text: str) -> float:
        """Score based on blocklist terms."""
        text_lower = text.lower()
        for term in self.blocklist:
            if term.lower() in text_lower:
                return 0.0
        return 1.0

    def add_to_blocklist(self, terms: list[str]) -> None:
        """Add terms to the blocklist."""
        self.blocklist.update(terms)
        logger.info("Added %s terms to quality blocklist", len(terms))

    def get_stats(self) -> dict[str, Any]:
        """Get filter configuration stats."""
        return {
            "min_quality_threshold": self.min_quality_threshold,
            "min_text_length": self.min_text_length,
            "max_hashtag_ratio": self.max_hashtag_ratio,
            "max_emoji_ratio": self.max_emoji_ratio,
            "blocklist_size": len(self.blocklist),
            "clickbait_pattern_count": len(self._clickbait_patterns),
            "spam_pattern_count": len(self._spam_patterns),
        }


__all__ = [
    "QualityScore",
    "TopicQualityFilter",
    "CLICKBAIT_PATTERNS",
    "SPAM_INDICATORS",
    "LOW_VALUE_PATTERNS",
    "QUALITY_INDICATORS",
]
