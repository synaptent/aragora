"""
Cross-Source Consensus Detection for Pulse Topics.

Detects when similar topics trend across multiple platforms,
indicating higher confidence in topic relevance and importance.

Features:
- Fuzzy text matching for topic similarity
- Multi-platform correlation detection
- Consensus scoring and confidence boost
- Topic clustering for related trends
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from aragora.pulse.ingestor import TrendingTopic

logger = logging.getLogger(__name__)


@dataclass
class TopicCluster:
    """A cluster of similar topics from multiple sources."""

    id: str
    canonical_topic: str  # Representative topic text
    topics: list[TrendingTopic] = field(default_factory=list)
    platforms: set[str] = field(default_factory=set)
    total_volume: int = 0
    consensus_score: float = 0.0

    @property
    def platform_count(self) -> int:
        return len(self.platforms)

    @property
    def is_cross_platform(self) -> bool:
        return self.platform_count >= 2

    def add_topic(self, topic: TrendingTopic) -> None:
        """Add a topic to this cluster."""
        self.topics.append(topic)
        self.platforms.add(topic.platform)
        self.total_volume += topic.volume


@dataclass
class ConsensusResult:
    """Result of cross-source consensus detection."""

    clusters: list[TopicCluster]
    cross_platform_count: int
    single_platform_count: int
    consensus_topics: list[TrendingTopic]  # Topics with cross-platform consensus
    confidence_boosts: dict[str, float]  # topic_text -> confidence boost


class CrossSourceConsensus:
    """
    Detects consensus across multiple source platforms.

    When the same topic trends on multiple platforms (e.g., HackerNews AND Reddit),
    it indicates higher confidence that the topic is genuinely important.

    Usage:
        consensus = CrossSourceConsensus()
        result = consensus.detect_consensus(topics)

        for cluster in result.clusters:
            if cluster.is_cross_platform:
                print(f"Cross-platform trend: {cluster.canonical_topic}")
                print(f"  Platforms: {cluster.platforms}")
                print(f"  Consensus: {cluster.consensus_score:.2f}")
    """

    def __init__(
        self,
        similarity_threshold: float = 0.60,
        min_platforms_for_consensus: int = 2,
        consensus_confidence_boost: float = 0.20,
        keyword_weight: float = 0.40,
    ):
        """
        Initialize the consensus detector.

        Args:
            similarity_threshold: Minimum similarity for topics to cluster (0-1)
            min_platforms_for_consensus: Minimum platforms for consensus boost
            consensus_confidence_boost: Confidence boost for cross-platform topics
            keyword_weight: Weight given to keyword overlap vs text similarity
        """
        self.similarity_threshold = similarity_threshold
        self.min_platforms_for_consensus = min_platforms_for_consensus
        self.consensus_confidence_boost = consensus_confidence_boost
        self.keyword_weight = keyword_weight
        self._similarity_backend = None

        # Common words to ignore in comparison
        self._stopwords = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "need",
            "dare",
            "ought",
            "used",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "as",
            "into",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "between",
            "under",
            "again",
            "further",
            "then",
            "once",
            "here",
            "there",
            "when",
            "where",
            "why",
            "how",
            "all",
            "each",
            "few",
            "more",
            "most",
            "other",
            "some",
            "such",
            "no",
            "nor",
            "not",
            "only",
            "own",
            "same",
            "so",
            "than",
            "too",
            "very",
            "just",
            "and",
            "but",
            "if",
            "or",
            "because",
            "until",
            "while",
            "about",
            "against",
            "this",
            "that",
        }

    def detect_consensus(
        self,
        topics: list[TrendingTopic],
        min_cluster_size: int = 1,
    ) -> ConsensusResult:
        """
        Detect cross-source consensus among topics.

        Args:
            topics: List of TrendingTopic from multiple platforms
            min_cluster_size: Minimum topics per cluster to include

        Returns:
            ConsensusResult with clusters and consensus metrics
        """
        if not topics:
            return ConsensusResult(
                clusters=[],
                cross_platform_count=0,
                single_platform_count=0,
                consensus_topics=[],
                confidence_boosts={},
            )

        # Build clusters
        clusters = self._cluster_topics(topics)

        # Filter by minimum size
        clusters = [c for c in clusters if len(c.topics) >= min_cluster_size]

        # Calculate consensus scores
        for cluster in clusters:
            cluster.consensus_score = self._calculate_consensus_score(cluster)

        # Sort by consensus score
        clusters.sort(key=lambda c: c.consensus_score, reverse=True)

        # Count cross-platform vs single-platform
        cross_platform = [c for c in clusters if c.is_cross_platform]
        single_platform = [c for c in clusters if not c.is_cross_platform]

        # Get topics with consensus and their confidence boosts
        consensus_topics = []
        confidence_boosts = {}

        for cluster in cross_platform:
            boost = self._calculate_confidence_boost(cluster)
            for topic in cluster.topics:
                consensus_topics.append(topic)
                confidence_boosts[topic.topic] = boost

        return ConsensusResult(
            clusters=clusters,
            cross_platform_count=len(cross_platform),
            single_platform_count=len(single_platform),
            consensus_topics=consensus_topics,
            confidence_boosts=confidence_boosts,
        )

    def get_consensus_boost(
        self,
        topic: TrendingTopic,
        all_topics: list[TrendingTopic],
    ) -> float:
        """
        Get confidence boost for a single topic based on cross-platform presence.

        Args:
            topic: The topic to check
            all_topics: All trending topics to compare against

        Returns:
            Confidence boost value (0.0 if no consensus)
        """
        # Find similar topics on other platforms
        similar_platforms = set()
        similar_platforms.add(topic.platform)

        for other in all_topics:
            if other.platform == topic.platform:
                continue

            similarity = self._calculate_similarity(topic.topic, other.topic)
            if similarity >= self.similarity_threshold:
                similar_platforms.add(other.platform)

        if len(similar_platforms) >= self.min_platforms_for_consensus:
            # Scale boost by number of platforms
            platform_factor = min(1.0, (len(similar_platforms) - 1) / 3)
            return self.consensus_confidence_boost * platform_factor

        return 0.0

    def find_related_topics(
        self,
        target: TrendingTopic,
        candidates: list[TrendingTopic],
        max_results: int = 5,
    ) -> list[tuple[TrendingTopic, float]]:
        """
        Find topics related to a target topic.

        Args:
            target: Target topic to find relations for
            candidates: List of candidate topics
            max_results: Maximum related topics to return

        Returns:
            List of (topic, similarity) tuples sorted by similarity
        """
        related = []

        for candidate in candidates:
            if candidate.topic == target.topic:
                continue

            similarity = self._calculate_similarity(target.topic, candidate.topic)
            if similarity >= self.similarity_threshold * 0.7:  # Lower threshold for relations
                related.append((candidate, similarity))

        # Sort by similarity descending
        related.sort(key=lambda x: x[1], reverse=True)

        return related[:max_results]

    def _cluster_topics(self, topics: list[TrendingTopic]) -> list[TopicCluster]:
        """Cluster similar topics together."""
        clusters: list[TopicCluster] = []
        assigned: set[int] = set()

        for i, topic in enumerate(topics):
            if i in assigned:
                continue

            # Start a new cluster with this topic
            cluster = TopicCluster(
                id=f"cluster-{len(clusters)}",
                canonical_topic=topic.topic,
            )
            cluster.add_topic(topic)
            assigned.add(i)

            # Find similar topics
            for j, other in enumerate(topics):
                if j in assigned or j == i:
                    continue

                similarity = self._calculate_similarity(topic.topic, other.topic)
                if similarity >= self.similarity_threshold:
                    cluster.add_topic(other)
                    assigned.add(j)

            clusters.append(cluster)

        return clusters

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate similarity between two topic texts.

        Combines text sequence matching with keyword overlap.
        """
        # Normalize texts
        norm1 = self._normalize_text(text1)
        norm2 = self._normalize_text(text2)

        # Text sequence similarity (embedding-based)
        if self._similarity_backend is None:
            from aragora.debate.similarity.factory import get_backend

            self._similarity_backend = get_backend(preferred="auto")
        sequence_sim = self._similarity_backend.compute_similarity(norm1, norm2)

        # Keyword overlap
        keywords1 = self._extract_keywords(text1)
        keywords2 = self._extract_keywords(text2)

        if keywords1 and keywords2:
            intersection = keywords1 & keywords2
            union = keywords1 | keywords2
            keyword_sim = len(intersection) / len(union) if union else 0
        else:
            keyword_sim = 0

        # Weighted combination
        combined = sequence_sim * (1 - self.keyword_weight) + keyword_sim * self.keyword_weight

        return combined

    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison."""
        # Lowercase
        text = text.lower()
        # Remove special characters
        text = re.sub(r"[^\w\s]", " ", text)
        # Remove extra whitespace
        text = " ".join(text.split())
        return text

    def _extract_keywords(self, text: str) -> set[str]:
        """Extract meaningful keywords from text."""
        # Normalize and split
        words = self._normalize_text(text).split()

        # Remove stopwords and short words
        keywords = {w for w in words if w not in self._stopwords and len(w) >= 3}

        return keywords

    def _calculate_consensus_score(self, cluster: TopicCluster) -> float:
        """Calculate consensus score for a cluster."""
        if not cluster.topics:
            return 0.0

        # Base score from platform diversity
        platform_score = min(1.0, cluster.platform_count / 4)

        # Volume factor (log scale)
        import math

        volume_score = min(1.0, math.log10(max(1, cluster.total_volume) + 1) / 6)

        # Topic count factor
        count_score = min(1.0, len(cluster.topics) / 5)

        # Weighted combination
        consensus = platform_score * 0.50 + volume_score * 0.30 + count_score * 0.20

        return consensus

    def _calculate_confidence_boost(self, cluster: TopicCluster) -> float:
        """Calculate confidence boost for a consensus cluster."""
        if not cluster.is_cross_platform:
            return 0.0

        # Scale by platform count (max boost at 4+ platforms)
        platform_factor = min(1.0, (cluster.platform_count - 1) / 3)

        return self.consensus_confidence_boost * platform_factor

    def get_stats(self) -> dict[str, Any]:
        """Get detector configuration stats."""
        return {
            "similarity_threshold": self.similarity_threshold,
            "min_platforms_for_consensus": self.min_platforms_for_consensus,
            "consensus_confidence_boost": self.consensus_confidence_boost,
            "keyword_weight": self.keyword_weight,
            "stopword_count": len(self._stopwords),
        }


__all__ = [
    "TopicCluster",
    "ConsensusResult",
    "CrossSourceConsensus",
]
