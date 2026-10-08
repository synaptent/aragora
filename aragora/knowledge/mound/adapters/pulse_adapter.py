"""
PulseAdapter - Bridges the Pulse system to the Knowledge Mound.

This adapter enables bidirectional integration between the Pulse
(trending topics and scheduled debates) system and the Knowledge Mound:

- Data flow IN: Trending topics, scheduled debates, and outcomes stored in KM
- Data flow OUT: Past debates on topic retrieved for deduplication
- Reverse flow: KM patterns inform trend detection thresholds

The adapter provides:
- Trending topic storage with quality filtering
- Scheduled debate record persistence
- Debate outcome tracking for analytics
- Topic deduplication via historical lookup

ID Prefix: pl_
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter
from aragora.knowledge.mound.adapters._fusion_mixin import FusionMixin
from aragora.knowledge.mound.adapters._semantic_mixin import SemanticSearchMixin

if TYPE_CHECKING:
    from aragora.knowledge.unified.types import KnowledgeItem
    from aragora.pulse.ingestor import TrendingTopic, TrendingTopicOutcome
    from aragora.pulse.store import ScheduledDebateRecord

EventCallback = Callable[[str, dict[str, Any]], None]

logger = logging.getLogger(__name__)


# =============================================================================
# Reverse Flow Dataclasses (KM → Pulse)
# =============================================================================


@dataclass
class KMQualityThresholdUpdate:
    """Result of updating quality thresholds from KM patterns."""

    old_min_quality: float
    new_min_quality: float
    old_category_bonuses: dict[str, float] = field(default_factory=dict)
    new_category_bonuses: dict[str, float] = field(default_factory=dict)
    patterns_analyzed: int = 0
    adjustments_made: int = 0
    confidence: float = 0.7
    recommendation: str = "keep"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KMTopicCoverage:
    """Analysis of KM coverage for a potential debate topic."""

    topic_text: str
    coverage_score: float = 0.0
    related_debates_count: int = 0
    avg_outcome_confidence: float = 0.0
    consensus_rate: float = 0.0
    km_items_found: int = 0
    recommendation: str = "proceed"  # proceed, skip, defer
    priority_adjustment: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KMSchedulingRecommendation:
    """Recommendation for scheduling adjustments from KM."""

    topic_id: str
    original_priority: float = 0.5
    adjusted_priority: float = 0.5
    reason: str = "no_change"
    km_confidence: float = 0.7
    coverage: KMTopicCoverage | None = None
    was_applied: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KMTopicValidation:
    """Validation result for a topic from KM patterns."""

    topic_id: str
    km_confidence: float = 0.7
    outcome_success_rate: float = 0.0
    similar_debates_count: int = 0
    avg_rounds_needed: float = 0.0
    recommendation: str = "keep"  # keep, boost, demote, skip
    priority_adjustment: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PulseKMSyncResult:
    """Result of batch sync from KM validations."""

    topics_analyzed: int = 0
    topics_adjusted: int = 0
    threshold_updates: int = 0
    scheduling_changes: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TopicSearchResult:
    """Wrapper for topic search results with adapter metadata."""

    topic: dict[str, Any]
    relevance_score: float = 0.0


class PulseAdapter(FusionMixin, SemanticSearchMixin, KnowledgeMoundAdapter):
    """
    Adapter that bridges Pulse system to the Knowledge Mound.

    Provides methods for the Knowledge Mound's federated query system:
    - store_trending_topic: Store quality trending topics
    - store_scheduled_debate: Store scheduled debate records
    - store_outcome: Store debate outcome for analytics
    - search_past_debates: Find historical debates on topic
    - get_trending_patterns: Find recurring trending patterns

    Usage:
        from aragora.pulse.store import ScheduledDebateStore
        from aragora.knowledge.mound.adapters import PulseAdapter

        store = ScheduledDebateStore()
        adapter = PulseAdapter(store)

        # Store quality trending topic
        adapter.store_trending_topic(topic)

        # Check for duplicates before scheduling
        past = adapter.search_past_debates(topic.topic, hours=48)
    """

    ID_PREFIX = "pl_"

    # Mixin configuration
    adapter_name = "pulse"
    source_type = "pulse"

    # Thresholds from plan
    MIN_TOPIC_QUALITY = 0.6  # Only store quality topics (volume/relevance weighted)

    # ========================================================================
    # FusionMixin required method implementations
    # ========================================================================

    def _get_fusion_sources(self) -> list[str]:
        """Return list of source adapters this adapter can fuse data from."""
        return ["consensus", "evidence", "insights", "elo"]

    def _extract_fusible_data(
        self,
        km_item: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Extract fusible data from a KM item."""
        metadata = km_item.get("metadata", {})
        confidence = km_item.get("confidence") or metadata.get("confidence")
        if confidence is None:
            return None
        return {
            "confidence": float(confidence),
            "is_valid": float(confidence) >= 0.5,
            "source_id": km_item.get("id") or metadata.get("source_id"),
            "quality_score": metadata.get("quality_score", confidence),
            "sources": metadata.get("sources", []),
            "reasoning": metadata.get("reasoning"),
        }

    def _apply_fusion_result(
        self,
        record: Any,
        fusion_result: Any,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Apply a fusion result to a pulse record."""
        try:
            fused_confidence = getattr(fusion_result, "fused_confidence", None)
            if fused_confidence is None:
                return False
            if isinstance(record, dict):
                record["km_fused"] = True
                record["km_fused_confidence"] = fused_confidence
                if metadata:
                    record["fusion_metadata"] = metadata
                logger.debug(
                    f"Applied fusion result to pulse record: "
                    f"fused_confidence={fused_confidence:.3f}"
                )
                return True
            return False
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to apply fusion result to pulse: %s", e)
            return False

    # ========================================================================
    # SemanticSearchMixin required method implementations
    # ========================================================================

    def _get_record_by_id(self, record_id: str) -> Any | None:
        """Get a topic, debate, or outcome record by ID.

        Searches topics, debates, and outcomes. Handles the pl_ prefix
        from the SemanticStore.
        """
        raw_id = record_id
        if record_id.startswith(self.ID_PREFIX):
            raw_id = record_id[len(self.ID_PREFIX) :]

        for storage in (self._topics, self._debates, self._outcomes):
            if record_id in storage:
                return storage[record_id]
            if raw_id in storage:
                return storage[raw_id]
            prefixed = f"{self.ID_PREFIX}{raw_id}"
            if prefixed in storage:
                return storage[prefixed]

        return None

    def _record_to_dict(self, record: Any, similarity: float = 0.0) -> dict[str, Any]:
        """Convert a pulse record to dict."""
        if isinstance(record, dict):
            result = dict(record)
            result["similarity"] = similarity
            return result
        return {
            "id": getattr(record, "id", None),
            "content": getattr(record, "topic", getattr(record, "title", "")),
            "confidence": getattr(record, "quality_score", 0.0),
            "similarity": similarity,
            "metadata": getattr(record, "metadata", {}),
        }

    def _extract_record_id(self, source_id: str) -> str:
        """Extract record ID from prefixed source ID."""
        if source_id.startswith(self.ID_PREFIX):
            return source_id[len(self.ID_PREFIX) :]
        return source_id

    # ========================================================================
    # Initialization
    # ========================================================================

    def __init__(
        self,
        debate_store: Any | None = None,
        enable_dual_write: bool = False,
        event_callback: EventCallback | None = None,
        enable_resilience: bool = True,
    ):
        """
        Initialize the adapter.

        Args:
            debate_store: Optional ScheduledDebateStore instance
            enable_dual_write: If True, writes go to both systems during migration
            event_callback: Optional callback for emitting events (event_type, data)
            enable_resilience: If True, enables circuit breaker and bulkhead protection
        """
        # Initialize base adapter (handles dual_write, event_callback, resilience, metrics, tracing)
        super().__init__(
            enable_dual_write=enable_dual_write,
            event_callback=event_callback,
            enable_resilience=enable_resilience,
        )

        self._debate_store = debate_store

        # In-memory storage for queries (will be replaced by KM backend)
        self._topics: dict[str, dict[str, Any]] = {}
        self._debates: dict[str, dict[str, Any]] = {}
        self._outcomes: dict[str, dict[str, Any]] = {}

        # Indices for fast lookup
        self._platform_topics: dict[str, list[str]] = {}  # platform -> [topic_ids]
        self._category_topics: dict[str, list[str]] = {}  # category -> [topic_ids]
        self._topic_hash_map: dict[str, str] = {}  # topic_hash -> topic_id

    # set_event_callback, _emit_event inherited from KnowledgeMoundAdapter

    @property
    def debate_store(self) -> Any | None:
        """Access the underlying ScheduledDebateStore."""
        return self._debate_store

    def _calculate_quality_score(
        self,
        volume: int,
        category: str,
    ) -> float:
        """
        Calculate quality score for a trending topic.

        Higher volume and certain categories (tech, science) get higher scores.

        Args:
            volume: Engagement volume
            category: Topic category

        Returns:
            Quality score 0-1
        """
        # Volume scoring: log scale, max 1000000
        import math

        volume_score = min(1.0, math.log10(max(1, volume)) / 6)

        # Category bonus
        category_bonuses = {
            "tech": 0.2,
            "science": 0.2,
            "business": 0.1,
            "politics": 0.0,  # No bonus, but not penalized
            "entertainment": -0.1,
        }
        cat_bonus = category_bonuses.get(category.lower(), 0.0)

        return min(1.0, max(0.0, volume_score + cat_bonus))

    def store_trending_topic(
        self,
        topic: TrendingTopic,
        min_quality: float | None = None,
    ) -> str | None:
        """
        Store a trending topic in the Knowledge Mound.

        Args:
            topic: The TrendingTopic to store
            min_quality: Minimum quality threshold

        Returns:
            The topic ID if stored, None if below threshold
        """
        min_q = min_quality or self.MIN_TOPIC_QUALITY
        quality = self._calculate_quality_score(topic.volume, topic.category)

        if quality < min_q:
            logger.debug(f"Topic '{topic.topic[:50]}' below quality threshold: {quality:.2f}")
            return None

        import hashlib

        topic_hash = hashlib.sha256(topic.topic.lower().encode()).hexdigest()[:16]
        topic_id = f"{self.ID_PREFIX}topic_{topic_hash}"

        topic_data = {
            "id": topic_id,
            "topic_hash": topic_hash,
            "topic": topic.topic,
            "platform": topic.platform,
            "volume": topic.volume,
            "category": topic.category,
            "quality_score": quality,
            "raw_data": topic.raw_data,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        self._topics[topic_id] = topic_data
        self._topic_hash_map[topic_hash] = topic_id

        # Update indices
        if topic.platform not in self._platform_topics:
            self._platform_topics[topic.platform] = []
        self._platform_topics[topic.platform].append(topic_id)

        if topic.category:
            if topic.category not in self._category_topics:
                self._category_topics[topic.category] = []
            self._category_topics[topic.category].append(topic_id)

        logger.info(f"Stored trending topic: {topic_id} (quality={quality:.2f})")
        return topic_id

    def store_scheduled_debate(
        self,
        record: ScheduledDebateRecord,
    ) -> str:
        """
        Store a scheduled debate record in the Knowledge Mound.

        Args:
            record: The ScheduledDebateRecord to store

        Returns:
            The debate record ID
        """
        debate_id = f"{self.ID_PREFIX}debate_{record.id}"

        debate_data = {
            "id": debate_id,
            "original_id": record.id,
            "topic_hash": record.topic_hash,
            "topic_text": record.topic_text,
            "platform": record.platform,
            "category": record.category,
            "volume": record.volume,
            "debate_id": record.debate_id,
            "created_at": record.created_at,
            "consensus_reached": record.consensus_reached,
            "confidence": record.confidence,
            "rounds_used": record.rounds_used,
            "scheduler_run_id": record.scheduler_run_id,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }

        self._debates[debate_id] = debate_data

        logger.info("Stored scheduled debate: %s", debate_id)
        return debate_id

    def store_outcome(
        self,
        outcome: TrendingTopicOutcome,
    ) -> str:
        """
        Store a debate outcome for a trending topic.

        This is always stored (for analytics) regardless of consensus.

        Args:
            outcome: The TrendingTopicOutcome to store

        Returns:
            The outcome ID
        """
        import hashlib

        topic_hash = hashlib.sha256(outcome.topic.lower().encode()).hexdigest()[:16]
        outcome_id = f"{self.ID_PREFIX}outcome_{outcome.debate_id}"

        outcome_data = {
            "id": outcome_id,
            "topic": outcome.topic,
            "topic_hash": topic_hash,
            "platform": outcome.platform,
            "debate_id": outcome.debate_id,
            "consensus_reached": outcome.consensus_reached,
            "confidence": outcome.confidence,
            "rounds_used": outcome.rounds_used,
            "timestamp": outcome.timestamp,
            "category": outcome.category,
            "volume": outcome.volume,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }

        self._outcomes[outcome_id] = outcome_data

        logger.info("Stored outcome: %s (consensus=%s)", outcome_id, outcome.consensus_reached)
        return outcome_id

    def store_debate_outcome(
        self,
        debate_id: str,
        topic: str,
        platform: str,
        consensus_reached: bool,
        confidence: float,
        rounds_used: int,
        category: str = "",
        volume: int = 0,
    ) -> str:
        """
        Store a debate outcome from the scheduler (convenience method).

        This is called by the PulseDebateScheduler after a debate completes.
        It creates a TrendingTopicOutcome and stores it.

        Args:
            debate_id: ID of the completed debate
            topic: The topic text
            platform: Source platform (hackernews, reddit, etc.)
            consensus_reached: Whether consensus was achieved
            confidence: Confidence score (0.0-1.0)
            rounds_used: Number of debate rounds used
            category: Topic category
            volume: Engagement volume

        Returns:
            The outcome ID
        """
        from aragora.pulse.ingestor import TrendingTopicOutcome

        outcome = TrendingTopicOutcome(
            topic=topic,
            platform=platform,
            debate_id=debate_id,
            consensus_reached=consensus_reached,
            confidence=confidence,
            rounds_used=rounds_used,
            timestamp=time.time(),
            category=category,
            volume=volume,
        )

        outcome_id = self.store_outcome(outcome)

        # Also record for KM reverse flow analysis
        self.record_outcome_for_km(
            topic_id=f"{self.ID_PREFIX}topic_{debate_id}",
            debate_id=debate_id,
            outcome_success=consensus_reached,
            confidence=confidence,
            rounds_used=rounds_used,
            category=category,
        )

        return outcome_id

    def get_topic(self, topic_id: str) -> dict[str, Any] | None:
        """
        Get a specific topic by ID.

        Args:
            topic_id: The topic ID (may be prefixed with "pl_topic_")

        Returns:
            Topic dict or None
        """
        if not topic_id.startswith(self.ID_PREFIX):
            topic_id = f"{self.ID_PREFIX}topic_{topic_id}"
        return self._topics.get(topic_id)

    def get_debate(self, debate_id: str) -> dict[str, Any] | None:
        """
        Get a specific debate record by ID.

        Args:
            debate_id: The debate ID

        Returns:
            Debate dict or None
        """
        if not debate_id.startswith(self.ID_PREFIX):
            debate_id = f"{self.ID_PREFIX}debate_{debate_id}"
        return self._debates.get(debate_id)

    def search_past_debates(
        self,
        topic_text: str,
        hours: int = 48,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Find historical debates on a similar topic.

        This is the key deduplication query for the scheduler.

        Args:
            topic_text: Topic to search for
            hours: Look back this many hours
            limit: Maximum results

        Returns:
            List of debate dicts
        """
        import time
        import hashlib

        topic_hash = hashlib.sha256(topic_text.lower().encode()).hexdigest()[:16]
        cutoff = time.time() - (hours * 3600)

        results = []
        query_words = set(topic_text.lower().split())

        for debate in self._debates.values():
            # Check time window
            created_at = debate.get("created_at", 0)
            if isinstance(created_at, str):
                continue  # Skip if not unix timestamp
            if created_at < cutoff:
                continue

            # Check exact hash match
            if debate.get("topic_hash") == topic_hash:
                results.append({**debate, "match_type": "exact"})
                continue

            # Check keyword overlap
            debate_words = set(debate.get("topic_text", "").lower().split())
            overlap = len(query_words & debate_words)
            if overlap >= 2:  # At least 2 words in common
                results.append(
                    {
                        **debate,
                        "match_type": "similar",
                        "overlap_count": overlap,
                    }
                )

        # Sort by created_at descending
        results.sort(key=lambda x: x.get("created_at", 0), reverse=True)

        return results[:limit]

    def get_platform_topics(
        self,
        platform: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Get trending topics from a specific platform.

        Args:
            platform: Platform name (twitter, reddit, etc.)
            limit: Maximum results

        Returns:
            List of topic dicts
        """
        topic_ids = self._platform_topics.get(platform, [])
        results = []

        for topic_id in topic_ids[:limit]:
            topic = self._topics.get(topic_id)
            if topic:
                results.append(topic)

        return results

    def get_category_topics(
        self,
        category: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Get trending topics from a specific category.

        Args:
            category: Category name
            limit: Maximum results

        Returns:
            List of topic dicts
        """
        topic_ids = self._category_topics.get(category, [])
        results = []

        for topic_id in topic_ids[:limit]:
            topic = self._topics.get(topic_id)
            if topic:
                results.append(topic)

        return results

    def get_trending_patterns(
        self,
        min_occurrences: int = 3,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Find recurring trending patterns across topics.

        Args:
            min_occurrences: Minimum times a pattern must appear
            limit: Maximum patterns to return

        Returns:
            List of pattern dicts
        """
        # Extract keywords from all topics
        keyword_counts: dict[str, int] = {}
        keyword_topics: dict[str, list[str]] = {}

        for topic in self._topics.values():
            words = topic.get("topic", "").lower().split()
            for word in words:
                if len(word) < 3:  # Skip short words
                    continue
                keyword_counts[word] = keyword_counts.get(word, 0) + 1
                if word not in keyword_topics:
                    keyword_topics[word] = []
                keyword_topics[word].append(topic["id"])

        # Filter by min occurrences
        patterns = [
            {
                "keyword": kw,
                "occurrence_count": count,
                "topic_ids": keyword_topics[kw][:10],  # Sample topics
            }
            for kw, count in keyword_counts.items()
            if count >= min_occurrences
        ]

        def _sort_key(x: dict[str, Any]) -> int:
            val = x.get("occurrence_count", 0)
            return int(val) if isinstance(val, (int, float, str)) else 0

        patterns.sort(key=_sort_key, reverse=True)

        return patterns[:limit]

    def get_outcome_analytics(
        self,
        platform: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """
        Get analytics on debate outcomes.

        Args:
            platform: Optional platform filter
            category: Optional category filter

        Returns:
            Analytics dict with success rates, etc.
        """
        outcomes = list(self._outcomes.values())

        if platform:
            outcomes = [o for o in outcomes if o.get("platform") == platform]
        if category:
            outcomes = [o for o in outcomes if o.get("category") == category]

        if not outcomes:
            return {
                "total_debates": 0,
                "consensus_rate": 0.0,
                "avg_confidence": 0.0,
                "avg_rounds": 0.0,
            }

        consensus_count = sum(1 for o in outcomes if o.get("consensus_reached"))
        total_confidence = sum(o.get("confidence", 0) or 0 for o in outcomes)
        total_rounds = sum(o.get("rounds_used", 0) or 0 for o in outcomes)

        return {
            "total_debates": len(outcomes),
            "consensus_rate": consensus_count / len(outcomes),
            "avg_confidence": total_confidence / len(outcomes),
            "avg_rounds": total_rounds / len(outcomes),
            "platform": platform,
            "category": category,
        }

    def to_knowledge_item(self, topic: dict[str, Any]) -> KnowledgeItem:
        """
        Convert a topic dict to a KnowledgeItem.

        Args:
            topic: The topic dictionary

        Returns:
            KnowledgeItem for unified knowledge mound API
        """
        from aragora.knowledge.unified.types import (
            ConfidenceLevel,
            KnowledgeItem,
            KnowledgeSource,
        )

        quality = topic.get("quality_score", 0.5)
        if quality >= 0.8:
            confidence = ConfidenceLevel.HIGH
        elif quality >= 0.6:
            confidence = ConfidenceLevel.MEDIUM
        elif quality >= 0.4:
            confidence = ConfidenceLevel.LOW
        else:
            confidence = ConfidenceLevel.UNVERIFIED

        created_at = topic.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                created_at = datetime.now(timezone.utc)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)

        return KnowledgeItem(
            id=topic["id"],
            content=topic.get("topic", ""),
            source=KnowledgeSource.PULSE,
            source_id=topic.get("topic_hash", topic["id"]),
            confidence=confidence,
            created_at=created_at,
            updated_at=created_at,
            metadata={
                "platform": topic.get("platform", ""),
                "category": topic.get("category", ""),
                "volume": topic.get("volume", 0),
                "quality_score": quality,
            },
            importance=quality,
        )

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about stored Pulse data."""
        return {
            "total_topics": len(self._topics),
            "total_debates": len(self._debates),
            "total_outcomes": len(self._outcomes),
            "platforms_tracked": len(self._platform_topics),
            "categories_tracked": len(self._category_topics),
        }

    # =========================================================================
    # Reverse Flow Methods (KM → Pulse)
    # =========================================================================

    def _init_reverse_flow_state(self) -> None:
        """Initialize reverse flow state if not already done."""
        if not hasattr(self, "_outcome_history"):
            self._outcome_history: list[dict[str, Any]] = []
        if not hasattr(self, "_km_validations"):
            self._km_validations: dict[str, KMTopicValidation] = {}
        if not hasattr(self, "_km_coverage_cache"):
            self._km_coverage_cache: dict[str, KMTopicCoverage] = {}
        if not hasattr(self, "_km_priority_adjustments"):
            self._km_priority_adjustments = 0
        if not hasattr(self, "_km_threshold_updates"):
            self._km_threshold_updates = 0
        if not hasattr(self, "_adjusted_min_quality"):
            self._adjusted_min_quality = self.MIN_TOPIC_QUALITY
        if not hasattr(self, "_adjusted_category_bonuses"):
            self._adjusted_category_bonuses = {
                "tech": 0.2,
                "science": 0.2,
                "business": 0.1,
                "politics": 0.0,
                "entertainment": -0.1,
            }

    def record_outcome_for_km(
        self,
        topic_id: str,
        debate_id: str,
        outcome_success: bool,
        confidence: float = 0.0,
        rounds_used: int = 0,
        category: str | None = None,
    ) -> None:
        """
        Record an outcome for KM reverse flow analysis.

        This tracks outcomes to analyze patterns and improve thresholds.

        Args:
            topic_id: The topic ID
            debate_id: The debate ID
            outcome_success: Whether the debate reached consensus
            confidence: Confidence score of the outcome
            rounds_used: Number of rounds used
            category: Topic category
        """
        self._init_reverse_flow_state()

        self._outcome_history.append(
            {
                "topic_id": topic_id,
                "debate_id": debate_id,
                "outcome_success": outcome_success,
                "confidence": confidence,
                "rounds_used": rounds_used,
                "category": category,
                "timestamp": time.time(),
            }
        )

    async def update_quality_thresholds_from_km(
        self,
        km_items: list[dict[str, Any]],
        min_items: int = 10,
    ) -> KMQualityThresholdUpdate:
        """
        Reverse flow: KM patterns improve quality thresholds.

        Analyzes KM outcome patterns to:
        - Adjust MIN_TOPIC_QUALITY based on success rates
        - Tune category bonuses based on category-specific success
        - Identify categories that consistently produce good debates

        Args:
            km_items: KM items with outcome data
            min_items: Minimum items needed for adjustment

        Returns:
            KMQualityThresholdUpdate with changes made
        """
        self._init_reverse_flow_state()

        old_min_quality = self._adjusted_min_quality
        old_category_bonuses = dict(self._adjusted_category_bonuses)

        if len(km_items) < min_items:
            return KMQualityThresholdUpdate(
                old_min_quality=old_min_quality,
                new_min_quality=old_min_quality,
                old_category_bonuses=old_category_bonuses,
                new_category_bonuses=old_category_bonuses,
                patterns_analyzed=len(km_items),
                adjustments_made=0,
                recommendation="insufficient_data",
                metadata={"reason": f"Need {min_items} items, got {len(km_items)}"},
            )

        # Analyze outcomes by category
        category_outcomes: dict[str, list[bool]] = {}
        quality_outcomes: dict[str, list[bool]] = {}  # quality_bucket -> outcomes

        for item in km_items:
            metadata = item.get("metadata", {})
            category = metadata.get("category", "unknown")
            quality = metadata.get("quality_score", 0.5)
            outcome = metadata.get("outcome_success", False)

            # Track category outcomes
            if category not in category_outcomes:
                category_outcomes[category] = []
            category_outcomes[category].append(outcome)

            # Track quality bucket outcomes
            if quality >= 0.8:
                bucket = "high"
            elif quality >= 0.6:
                bucket = "medium"
            elif quality >= 0.4:
                bucket = "low"
            else:
                bucket = "very_low"

            if bucket not in quality_outcomes:
                quality_outcomes[bucket] = []
            quality_outcomes[bucket].append(outcome)

        adjustments_made = 0

        # Adjust MIN_TOPIC_QUALITY based on quality bucket success rates
        bucket_success_rates = {}
        for bucket, outcomes in quality_outcomes.items():
            if outcomes:
                bucket_success_rates[bucket] = sum(outcomes) / len(outcomes)

        # If low quality topics still succeed often, lower threshold
        if "low" in bucket_success_rates:
            low_success = bucket_success_rates["low"]
            if low_success >= 0.7:
                self._adjusted_min_quality = max(0.3, old_min_quality - 0.1)
                adjustments_made += 1
            elif low_success < 0.4:
                self._adjusted_min_quality = min(0.8, old_min_quality + 0.1)
                adjustments_made += 1

        # Adjust category bonuses based on category-specific success
        for category, outcomes in category_outcomes.items():
            if len(outcomes) >= 5:
                success_rate = sum(outcomes) / len(outcomes)
                current_bonus = self._adjusted_category_bonuses.get(category, 0.0)

                if success_rate >= 0.8:
                    # High success rate, increase bonus
                    new_bonus = min(0.3, current_bonus + 0.05)
                elif success_rate < 0.4:
                    # Low success rate, decrease bonus
                    new_bonus = max(-0.2, current_bonus - 0.05)
                else:
                    new_bonus = current_bonus

                if new_bonus != current_bonus:
                    self._adjusted_category_bonuses[category] = new_bonus
                    adjustments_made += 1

        if adjustments_made > 0:
            self._km_threshold_updates += 1

        # Determine recommendation
        if adjustments_made == 0:
            recommendation = "keep"
        elif self._adjusted_min_quality < old_min_quality:
            recommendation = "lower_threshold"
        else:
            recommendation = "raise_threshold"

        return KMQualityThresholdUpdate(
            old_min_quality=old_min_quality,
            new_min_quality=self._adjusted_min_quality,
            old_category_bonuses=old_category_bonuses,
            new_category_bonuses=dict(self._adjusted_category_bonuses),
            patterns_analyzed=len(km_items),
            adjustments_made=adjustments_made,
            confidence=0.7 + (0.1 if len(km_items) >= 50 else 0.0),
            recommendation=recommendation,
            metadata={
                "bucket_success_rates": bucket_success_rates,
                "category_success_rates": {
                    cat: sum(outcomes) / len(outcomes)
                    for cat, outcomes in category_outcomes.items()
                    if outcomes
                },
            },
        )

    async def get_km_topic_coverage(
        self,
        topic_text: str,
        km_items: list[dict[str, Any]],
    ) -> KMTopicCoverage:
        """
        Analyze KM coverage of a potential debate topic.

        Checks how well-covered a topic is in KM to determine:
        - Whether this topic has been debated before
        - What outcomes similar debates had
        - Whether to proceed, skip, or defer

        Args:
            topic_text: The topic to analyze
            km_items: Related KM items from search

        Returns:
            KMTopicCoverage with coverage analysis
        """
        self._init_reverse_flow_state()

        import hashlib

        topic_hash = hashlib.sha256(topic_text.lower().encode()).hexdigest()[:16]

        if not km_items:
            coverage = KMTopicCoverage(
                topic_text=topic_text,
                coverage_score=0.0,
                recommendation="proceed",
                priority_adjustment=0.0,
                metadata={"topic_hash": topic_hash},
            )
            self._km_coverage_cache[topic_hash] = coverage
            return coverage

        # Analyze related debates
        debate_outcomes = []
        confidence_sum = 0.0
        rounds_sum = 0
        consensus_count = 0

        for item in km_items:
            metadata = item.get("metadata", {})
            if "outcome_success" in metadata:
                debate_outcomes.append(metadata["outcome_success"])
                if metadata.get("confidence"):
                    confidence_sum += metadata["confidence"]
                if metadata.get("rounds_used"):
                    rounds_sum += metadata["rounds_used"]
                if metadata.get("outcome_success"):
                    consensus_count += 1

        related_count = len(debate_outcomes)
        avg_confidence = confidence_sum / related_count if related_count else 0.0
        consensus_rate = consensus_count / related_count if related_count else 0.0
        avg_rounds = rounds_sum / related_count if related_count else 0.0

        # Calculate coverage score (0-1)
        # Higher coverage = more past debates found
        coverage_score = min(1.0, related_count / 10.0)

        # Determine recommendation
        if coverage_score >= 0.8 and consensus_rate >= 0.7:
            # Well-covered with good consensus, might be redundant
            recommendation = "skip"
            priority_adjustment = -0.2
        elif coverage_score >= 0.5 and consensus_rate < 0.5:
            # Partially covered but low consensus, worth revisiting
            recommendation = "proceed"
            priority_adjustment = 0.1
        elif coverage_score < 0.2:
            # Novel topic
            recommendation = "proceed"
            priority_adjustment = 0.15
        else:
            recommendation = "proceed"
            priority_adjustment = 0.0

        coverage = KMTopicCoverage(
            topic_text=topic_text,
            coverage_score=coverage_score,
            related_debates_count=related_count,
            avg_outcome_confidence=avg_confidence,
            consensus_rate=consensus_rate,
            km_items_found=len(km_items),
            recommendation=recommendation,
            priority_adjustment=priority_adjustment,
            metadata={
                "topic_hash": topic_hash,
                "avg_rounds": avg_rounds,
            },
        )

        self._km_coverage_cache[topic_hash] = coverage
        return coverage

    async def validate_topic_from_km(
        self,
        topic_id: str,
        km_cross_refs: list[dict[str, Any]],
    ) -> KMTopicValidation:
        """
        Validate a topic against KM patterns.

        Analyzes cross-references to determine:
        - How similar topics performed in debates
        - Expected success rate based on patterns
        - Recommended priority adjustment

        Args:
            topic_id: The topic ID to validate
            km_cross_refs: Cross-references from KM

        Returns:
            KMTopicValidation with validation results
        """
        self._init_reverse_flow_state()

        # Get internal outcome history for this topic
        internal_outcomes = [o for o in self._outcome_history if o.get("topic_id") == topic_id]

        # Combine with KM cross-refs
        all_outcomes = []
        total_rounds = 0
        total_confidence = 0.0

        for outcome in internal_outcomes:
            all_outcomes.append(outcome.get("outcome_success", False))
            total_rounds += outcome.get("rounds_used", 0)
            total_confidence += outcome.get("confidence", 0)

        for ref in km_cross_refs:
            metadata = ref.get("metadata", {})
            if "outcome_success" in metadata:
                all_outcomes.append(metadata["outcome_success"])
                total_rounds += metadata.get("rounds_used", 0)
                total_confidence += metadata.get("confidence", 0)

        if not all_outcomes:
            validation = KMTopicValidation(
                topic_id=topic_id,
                km_confidence=0.5,
                outcome_success_rate=0.0,
                recommendation="keep",
            )
            self._km_validations[topic_id] = validation
            return validation

        success_rate = sum(all_outcomes) / len(all_outcomes)
        avg_rounds = total_rounds / len(all_outcomes) if all_outcomes else 0.0
        avg_confidence = total_confidence / len(all_outcomes) if all_outcomes else 0.0

        # Confidence increases with more data
        km_confidence = min(0.95, 0.5 + (len(all_outcomes) * 0.05))

        # Determine recommendation
        if success_rate >= 0.8:
            recommendation = "boost"
            priority_adjustment = 0.1
        elif success_rate < 0.3:
            recommendation = "demote"
            priority_adjustment = -0.1
        else:
            recommendation = "keep"
            priority_adjustment = 0.0

        validation = KMTopicValidation(
            topic_id=topic_id,
            km_confidence=km_confidence,
            outcome_success_rate=success_rate,
            similar_debates_count=len(all_outcomes),
            avg_rounds_needed=avg_rounds,
            recommendation=recommendation,
            priority_adjustment=priority_adjustment,
            metadata={
                "avg_confidence": avg_confidence,
                "internal_outcomes": len(internal_outcomes),
                "km_outcomes": len(km_cross_refs),
            },
        )

        self._km_validations[topic_id] = validation
        return validation

    async def apply_scheduling_recommendation(
        self,
        validation: KMTopicValidation,
    ) -> KMSchedulingRecommendation:
        """
        Apply a scheduling recommendation based on KM validation.

        Args:
            validation: The validation to apply

        Returns:
            KMSchedulingRecommendation with results
        """
        self._init_reverse_flow_state()

        topic = self._topics.get(validation.topic_id)
        if not topic:
            return KMSchedulingRecommendation(
                topic_id=validation.topic_id,
                reason="topic_not_found",
                was_applied=False,
                metadata={"error": "topic_not_found"},
            )

        original_quality = topic.get("quality_score", 0.5)

        if validation.recommendation == "keep":
            return KMSchedulingRecommendation(
                topic_id=validation.topic_id,
                original_priority=original_quality,
                adjusted_priority=original_quality,
                reason="no_change",
                km_confidence=validation.km_confidence,
                was_applied=False,
            )

        # Apply priority adjustment
        adjusted = original_quality + validation.priority_adjustment
        adjusted = max(0.0, min(1.0, adjusted))

        # Update topic's quality score
        topic["quality_score"] = adjusted
        topic["km_validated"] = True
        topic["km_validation_time"] = time.time()

        self._km_priority_adjustments += 1

        return KMSchedulingRecommendation(
            topic_id=validation.topic_id,
            original_priority=original_quality,
            adjusted_priority=adjusted,
            reason=validation.recommendation,
            km_confidence=validation.km_confidence,
            was_applied=True,
            metadata={
                "adjustment": validation.priority_adjustment,
                "success_rate": validation.outcome_success_rate,
            },
        )

    async def sync_validations_from_km(
        self,
        km_items: list[dict[str, Any]],
        min_confidence: float = 0.7,
    ) -> PulseKMSyncResult:
        """
        Batch sync KM validations back to Pulse.

        Processes KM items to:
        - Update quality thresholds
        - Validate topics
        - Apply scheduling recommendations

        Args:
            km_items: KM items with validation data
            min_confidence: Minimum confidence for applying changes

        Returns:
            PulseKMSyncResult with sync results
        """
        self._init_reverse_flow_state()
        start_time = time.time()

        result = PulseKMSyncResult()
        errors = []

        # Group items by topic
        topic_items: dict[str, list[dict[str, Any]]] = {}
        for item in km_items:
            metadata = item.get("metadata", {})
            topic_id = metadata.get("topic_id")
            if topic_id:
                if topic_id not in topic_items:
                    topic_items[topic_id] = []
                topic_items[topic_id].append(item)

        # Process threshold updates
        try:
            threshold_update = await self.update_quality_thresholds_from_km(km_items)
            result.threshold_updates = threshold_update.adjustments_made
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            errors.append(f"Threshold update error: {e}")

        # Process each topic
        for topic_id, items in topic_items.items():
            try:
                validation = await self.validate_topic_from_km(topic_id, items)
                result.topics_analyzed += 1

                if validation.km_confidence >= min_confidence:
                    rec = await self.apply_scheduling_recommendation(validation)
                    if rec.was_applied:
                        result.topics_adjusted += 1
                        result.scheduling_changes += 1
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                errors.append(f"Topic {topic_id} error: {e}")

        result.errors = errors
        result.duration_ms = int((time.time() - start_time) * 1000)
        result.metadata = {
            "total_items": len(km_items),
            "unique_topics": len(topic_items),
            "min_confidence": min_confidence,
        }

        return result

    def get_reverse_flow_stats(self) -> dict[str, Any]:
        """
        Get statistics about reverse flow operations.

        Returns:
            Dict with reverse flow metrics
        """
        self._init_reverse_flow_state()

        return {
            "outcome_history_count": len(self._outcome_history),
            "validations_stored": len(self._km_validations),
            "coverage_cache_size": len(self._km_coverage_cache),
            "km_priority_adjustments": self._km_priority_adjustments,
            "km_threshold_updates": self._km_threshold_updates,
            "current_min_quality": self._adjusted_min_quality,
            "current_category_bonuses": dict(self._adjusted_category_bonuses),
        }

    def clear_reverse_flow_state(self) -> None:
        """Clear all reverse flow state."""
        self._outcome_history = []
        self._km_validations = {}
        self._km_coverage_cache = {}
        self._km_priority_adjustments = 0
        self._km_threshold_updates = 0
        self._adjusted_min_quality = self.MIN_TOPIC_QUALITY
        self._adjusted_category_bonuses = {
            "tech": 0.2,
            "science": 0.2,
            "business": 0.1,
            "politics": 0.0,
            "entertainment": -0.1,
        }


__all__ = [
    "PulseAdapter",
    "TopicSearchResult",
    # Reverse flow dataclasses
    "KMQualityThresholdUpdate",
    "KMTopicCoverage",
    "KMSchedulingRecommendation",
    "KMTopicValidation",
    "PulseKMSyncResult",
]
