"""
InsightsAdapter - Bridges Insights/Trickster to the Knowledge Mound.

This adapter enables bidirectional integration between the Insights system
(including Trickster flip detection) and the Knowledge Mound:

- Data flow IN: Insights, FlipEvents, and PatternClusters stored in KM
- Data flow OUT: Similar insights and flip history retrieved for context
- Reverse flow: KM patterns inform flip detection thresholds

The adapter provides:
- Insight storage after debate extraction
- FlipEvent persistence for Trickster tracking
- Pattern cluster aggregation
- Historical flip retrieval for consistency prediction

ID Prefixes:
- in_: Insights
- fl_: Flip events
- pt_: Pattern clusters
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.knowledge.unified.types import KnowledgeItem
    from aragora.insights.extractor import DebateInsights, Insight
    from aragora.insights.flip_detector import FlipEvent

EventCallback = Callable[[str, dict[str, Any]], None]

logger = logging.getLogger(__name__)

# Import mixins for semantic search and fusion functionality
from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter
from aragora.knowledge.mound.adapters._semantic_mixin import SemanticSearchMixin
from aragora.knowledge.mound.adapters._fusion_mixin import FusionMixin

# ============================================================================
# Reverse Flow Dataclasses (KM → InsightStore/FlipDetector)
# ============================================================================


@dataclass
class KMFlipThresholdUpdate:
    """Result of updating flip detection thresholds from KM patterns."""

    old_similarity_threshold: float
    new_similarity_threshold: float
    old_confidence_threshold: float
    new_confidence_threshold: float
    patterns_analyzed: int = 0
    adjustments_made: int = 0
    confidence: float = 0.7
    recommendation: str = "keep"  # "increase", "decrease", "keep"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KMAgentFlipBaseline:
    """KM-validated flip baseline for an agent."""

    agent_name: str
    expected_flip_rate: float  # 0.0-1.0 expected flips per debate
    flip_type_distribution: dict[str, float] = field(default_factory=dict)
    domain_flip_rates: dict[str, float] = field(default_factory=dict)
    sample_count: int = 0
    confidence: float = 0.7
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KMFlipValidation:
    """Validation result from KM for a flip event."""

    flip_id: str
    km_confidence: float  # 0.0-1.0 how confident KM is about this flip
    is_expected: bool = False  # Whether flip was expected based on patterns
    pattern_match_score: float = 0.0  # How well it matches known patterns
    recommendation: str = "keep"  # "flag", "ignore", "keep"
    adjustment: float = 0.0  # Adjustment to agent consistency score
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class InsightThresholdSyncResult:
    """Result of syncing thresholds from KM patterns."""

    flips_analyzed: int = 0
    insights_analyzed: int = 0
    threshold_updates: list[KMFlipThresholdUpdate] = field(default_factory=list)
    baseline_updates: list[KMAgentFlipBaseline] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class InsightSearchResult:
    """Wrapper for insight search results with adapter metadata."""

    insight: dict[str, Any]
    relevance_score: float = 0.0
    matched_topics: list[str] = field(default_factory=list)


@dataclass
class FlipSearchResult:
    """Wrapper for flip event search results."""

    flip: dict[str, Any]
    relevance_score: float = 0.0


class InsightsAdapter(FusionMixin, SemanticSearchMixin, KnowledgeMoundAdapter):
    """
    Adapter that bridges InsightStore and FlipDetector to the Knowledge Mound.

    Provides methods for the Knowledge Mound's federated query system:
    - store_insight: Store individual insights with confidence filtering
    - store_debate_insights: Store all insights from a debate
    - store_flip: Store flip events for Trickster tracking
    - store_pattern: Store recurring pattern clusters
    - search_similar_insights: Find insights on similar topics
    - get_agent_flip_history: Retrieve flip history for an agent

    Usage:
        from aragora.insights.store import InsightStore
        from aragora.knowledge.mound.adapters import InsightsAdapter

        store = InsightStore()
        adapter = InsightsAdapter(store)

        # Store insights from debate
        adapter.store_debate_insights(debate_insights)

        # Store flip events
        for flip in detected_flips:
            adapter.store_flip(flip)
    """

    INSIGHT_PREFIX = "in_"
    FLIP_PREFIX = "fl_"
    PATTERN_PREFIX = "pt_"

    # Mixin configuration
    adapter_name = "insights"
    source_type = "insights"

    # Thresholds from plan
    MIN_INSIGHT_CONFIDENCE = 0.7  # Only store high-confidence insights
    MIN_PATTERN_OCCURRENCES = 3  # Store patterns with 3+ occurrences

    # ========================================================================
    # FusionMixin required method implementations
    # ========================================================================

    def _get_fusion_sources(self) -> list[str]:
        """Return list of source adapters this adapter can fuse data from."""
        return ["consensus", "belief", "evidence", "elo"]

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
            "insight_type": metadata.get("type", metadata.get("insight_type")),
            "sources": metadata.get("sources", []),
            "reasoning": metadata.get("reasoning"),
        }

    def _apply_fusion_result(
        self,
        record: Any,
        fusion_result: Any,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Apply a fusion result to an insight or flip record."""
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
                    f"Applied fusion result to insights record: "
                    f"fused_confidence={fused_confidence:.3f}"
                )
                return True
            return False
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to apply fusion result to insights: %s", e)
            return False

    # ========================================================================
    # SemanticSearchMixin required method implementations
    # ========================================================================

    def _get_record_by_id(self, record_id: str) -> Any | None:
        """Get an insight, flip, or pattern record by ID.

        Searches insights, flips, and patterns. Handles prefixed IDs
        (in_, fl_, pt_) from the SemanticStore.
        """
        # Try with known prefixes first
        if record_id.startswith(self.INSIGHT_PREFIX):
            result = self._insights.get(record_id)
            if result is not None:
                return result
            return self._insights.get(record_id[len(self.INSIGHT_PREFIX) :])

        if record_id.startswith(self.FLIP_PREFIX):
            result = self._flips.get(record_id)
            if result is not None:
                return result
            return self._flips.get(record_id[len(self.FLIP_PREFIX) :])

        if record_id.startswith(self.PATTERN_PREFIX):
            result = self._patterns.get(record_id)
            if result is not None:
                return result
            return self._patterns.get(record_id[len(self.PATTERN_PREFIX) :])

        # No prefix: try all storage dicts
        for prefix, storage in [
            (self.INSIGHT_PREFIX, self._insights),
            (self.FLIP_PREFIX, self._flips),
            (self.PATTERN_PREFIX, self._patterns),
        ]:
            if record_id in storage:
                return storage[record_id]
            prefixed = f"{prefix}{record_id}"
            if prefixed in storage:
                return storage[prefixed]

        return None

    def _record_to_dict(self, record: Any, similarity: float = 0.0) -> dict[str, Any]:
        """Convert an insight/flip/pattern record to dict."""
        if isinstance(record, dict):
            result = dict(record)
            result["similarity"] = similarity
            return result
        return {
            "id": getattr(record, "id", None),
            "content": getattr(record, "description", getattr(record, "title", "")),
            "confidence": getattr(record, "confidence", 0.0),
            "similarity": similarity,
            "metadata": getattr(record, "metadata", {}),
        }

    def _extract_record_id(self, source_id: str) -> str:
        """Extract record ID from prefixed source ID."""
        for prefix in (self.INSIGHT_PREFIX, self.FLIP_PREFIX, self.PATTERN_PREFIX):
            if source_id.startswith(prefix):
                return source_id[len(prefix) :]
        return source_id

    # ========================================================================
    # Initialization
    # ========================================================================

    def __init__(
        self,
        insight_store: Any | None = None,
        flip_detector: Any | None = None,
        enable_dual_write: bool = False,
        event_callback: EventCallback | None = None,
        enable_resilience: bool = True,
    ):
        """
        Initialize the adapter.

        Args:
            insight_store: Optional InsightStore instance
            flip_detector: Optional FlipDetector instance
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

        self._insight_store = insight_store
        self._flip_detector = flip_detector

        # In-memory storage for queries (will be replaced by KM backend)
        self._insights: dict[str, dict[str, Any]] = {}
        self._flips: dict[str, dict[str, Any]] = {}
        self._patterns: dict[str, dict[str, Any]] = {}

        # Indices for fast lookup
        self._debate_insights: dict[str, list[str]] = {}  # debate_id -> [insight_ids]
        self._type_insights: dict[str, list[str]] = {}  # type -> [insight_ids]
        self._agent_flips: dict[str, list[str]] = {}  # agent_name -> [flip_ids]
        self._domain_flips: dict[str, list[str]] = {}  # domain -> [flip_ids]

    # set_event_callback, _emit_event inherited from KnowledgeMoundAdapter

    @property
    def insight_store(self) -> Any | None:
        """Access the underlying InsightStore."""
        return self._insight_store

    @property
    def flip_detector(self) -> Any | None:
        """Access the underlying FlipDetector."""
        return self._flip_detector

    def store_insight(
        self,
        insight: Insight,
        min_confidence: float | None = None,
    ) -> str | None:
        """
        Store an insight in the Knowledge Mound.

        Args:
            insight: The Insight to store
            min_confidence: Minimum confidence threshold (default: MIN_INSIGHT_CONFIDENCE)

        Returns:
            The insight ID if stored, None if below threshold
        """
        min_conf = min_confidence or self.MIN_INSIGHT_CONFIDENCE

        if insight.confidence < min_conf:
            logger.debug(
                f"Insight {insight.id} below confidence threshold: {insight.confidence:.2f}"
            )
            return None

        insight_id = f"{self.INSIGHT_PREFIX}{insight.id}"

        insight_data = {
            "id": insight_id,
            "original_id": insight.id,
            "type": insight.type.value if hasattr(insight.type, "value") else str(insight.type),
            "title": insight.title,
            "description": insight.description,
            "confidence": insight.confidence,
            "debate_id": insight.debate_id,
            "agents_involved": insight.agents_involved,
            "evidence": insight.evidence,
            "created_at": insight.created_at,
            "metadata": insight.metadata,
        }

        self._insights[insight_id] = insight_data

        # Update indices
        if insight.debate_id:
            if insight.debate_id not in self._debate_insights:
                self._debate_insights[insight.debate_id] = []
            self._debate_insights[insight.debate_id].append(insight_id)

        insight_type: str = str(insight_data.get("type", "unknown"))
        if insight_type not in self._type_insights:
            self._type_insights[insight_type] = []
        self._type_insights[insight_type].append(insight_id)

        logger.info(f"Stored insight: {insight_id} (confidence={insight.confidence:.2f})")
        return insight_id

    def store_debate_insights(
        self,
        debate_insights: DebateInsights,
        min_confidence: float | None = None,
    ) -> list[str]:
        """
        Store all insights from a debate above the threshold.

        Args:
            debate_insights: The DebateInsights collection
            min_confidence: Minimum confidence threshold

        Returns:
            List of stored insight IDs
        """
        stored_ids = []

        for insight in debate_insights.all_insights():
            insight_id = self.store_insight(insight, min_confidence)
            if insight_id:
                stored_ids.append(insight_id)

        logger.info("Stored %s insights from debate %s", len(stored_ids), debate_insights.debate_id)
        return stored_ids

    def store_flip(
        self,
        flip: FlipEvent,
    ) -> str:
        """
        Store a flip event in the Knowledge Mound.

        Flip events are always stored (meta-learning) regardless of threshold.

        Args:
            flip: The FlipEvent to store

        Returns:
            The flip ID
        """
        flip_id = f"{self.FLIP_PREFIX}{flip.id}"

        flip_data = {
            "id": flip_id,
            "original_id": flip.id,
            "agent_name": flip.agent_name,
            "original_claim": flip.original_claim,
            "new_claim": flip.new_claim,
            "original_confidence": flip.original_confidence,
            "new_confidence": flip.new_confidence,
            "original_debate_id": flip.original_debate_id,
            "new_debate_id": flip.new_debate_id,
            "original_position_id": flip.original_position_id,
            "new_position_id": flip.new_position_id,
            "similarity_score": flip.similarity_score,
            "flip_type": flip.flip_type,
            "domain": flip.domain,
            "detected_at": flip.detected_at,
        }

        self._flips[flip_id] = flip_data

        # Update indices
        if flip.agent_name not in self._agent_flips:
            self._agent_flips[flip.agent_name] = []
        self._agent_flips[flip.agent_name].append(flip_id)

        if flip.domain:
            if flip.domain not in self._domain_flips:
                self._domain_flips[flip.domain] = []
            self._domain_flips[flip.domain].append(flip_id)

        logger.info("Stored flip event: %s (type=%s)", flip_id, flip.flip_type)
        return flip_id

    def store_flips_batch(
        self,
        flips: list[FlipEvent],
    ) -> list[str]:
        """
        Store multiple flip events.

        Args:
            flips: List of FlipEvents to store

        Returns:
            List of stored flip IDs
        """
        return [self.store_flip(flip) for flip in flips]

    def store_pattern(
        self,
        category: str,
        pattern_text: str,
        occurrence_count: int,
        avg_severity: float = 0.5,
        debate_ids: list[str] | None = None,
    ) -> str | None:
        """
        Store a pattern cluster in the Knowledge Mound.

        Args:
            category: Pattern category
            pattern_text: The pattern description
            occurrence_count: Number of occurrences
            avg_severity: Average severity (0-1)
            debate_ids: List of debate IDs where pattern appeared

        Returns:
            The pattern ID if stored, None if below threshold
        """
        if occurrence_count < self.MIN_PATTERN_OCCURRENCES:
            logger.debug(
                "Pattern '%s' below occurrence threshold: %s", pattern_text[:50], occurrence_count
            )
            return None

        import hashlib

        pattern_hash = hashlib.sha256(f"{category}:{pattern_text}".encode()).hexdigest()[:12]
        pattern_id = f"{self.PATTERN_PREFIX}{pattern_hash}"

        pattern_data = {
            "id": pattern_id,
            "category": category,
            "pattern_text": pattern_text,
            "occurrence_count": occurrence_count,
            "avg_severity": avg_severity,
            "debate_ids": debate_ids or [],
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }

        # Update if exists, otherwise create
        if pattern_id in self._patterns:
            existing = self._patterns[pattern_id]
            pattern_data["first_seen"] = existing["first_seen"]
            pattern_data["occurrence_count"] = existing["occurrence_count"] + occurrence_count
            pattern_data["debate_ids"] = list(set(existing["debate_ids"] + (debate_ids or [])))

        self._patterns[pattern_id] = pattern_data

        logger.info(
            "Stored pattern: %s (occurrences=%s)", pattern_id, pattern_data["occurrence_count"]
        )
        return pattern_id

    def get_insight(self, insight_id: str) -> dict[str, Any] | None:
        """
        Get a specific insight by ID.

        Args:
            insight_id: The insight ID (may be prefixed with "in_")

        Returns:
            Insight dict or None
        """
        if not insight_id.startswith(self.INSIGHT_PREFIX):
            insight_id = f"{self.INSIGHT_PREFIX}{insight_id}"
        return self._insights.get(insight_id)

    def get_flip(self, flip_id: str) -> dict[str, Any] | None:
        """
        Get a specific flip event by ID.

        Args:
            flip_id: The flip ID (may be prefixed with "fl_")

        Returns:
            Flip dict or None
        """
        if not flip_id.startswith(self.FLIP_PREFIX):
            flip_id = f"{self.FLIP_PREFIX}{flip_id}"
        return self._flips.get(flip_id)

    def search_similar_insights(
        self,
        query: str,
        limit: int = 10,
        insight_type: str | None = None,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Find insights similar to the query.

        Args:
            query: Search query (keywords from title/description)
            limit: Maximum results
            insight_type: Optional filter by insight type
            min_confidence: Minimum confidence threshold

        Returns:
            List of matching insight dicts
        """
        results = []
        query_lower = query.lower()
        query_words = set(query_lower.split())

        for insight in self._insights.values():
            if insight["confidence"] < min_confidence:
                continue

            if insight_type and insight["type"] != insight_type:
                continue

            # Combine title and description for matching
            text = f"{insight['title']} {insight['description']}".lower()
            text_words = set(text.split())

            overlap = len(query_words & text_words)
            if overlap > 0:
                relevance = overlap / max(len(query_words), 1)
                results.append(
                    {
                        **insight,
                        "relevance_score": relevance,
                    }
                )

        results.sort(
            key=lambda x: x["relevance_score"] * x["confidence"],
            reverse=True,
        )

        return results[:limit]

    def get_insights_by_type(
        self,
        insight_type: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Get insights of a specific type.

        Args:
            insight_type: The insight type to filter by
            limit: Maximum results

        Returns:
            List of insight dicts
        """
        insight_ids = self._type_insights.get(insight_type, [])
        results = []

        for insight_id in insight_ids[:limit]:
            insight = self._insights.get(insight_id)
            if insight:
                results.append(insight)

        return results

    def get_debate_insights(
        self,
        debate_id: str,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Get all insights from a specific debate.

        Args:
            debate_id: The debate ID
            min_confidence: Minimum confidence filter

        Returns:
            List of insight dicts
        """
        insight_ids = self._debate_insights.get(debate_id, [])
        results = []

        for insight_id in insight_ids:
            insight = self._insights.get(insight_id)
            if insight and insight.get("confidence", 0) >= min_confidence:
                results.append(insight)

        return results

    def get_agent_flip_history(
        self,
        agent_name: str,
        limit: int = 50,
        flip_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get flip history for a specific agent.

        This is the key query for Trickster consistency tracking.

        Args:
            agent_name: The agent name
            limit: Maximum results
            flip_type: Optional filter by flip type

        Returns:
            List of flip dicts ordered by detected_at (newest first)
        """
        flip_ids = self._agent_flips.get(agent_name, [])
        results = []

        for flip_id in flip_ids:
            flip = self._flips.get(flip_id)
            if flip:
                if flip_type and flip["flip_type"] != flip_type:
                    continue
                results.append(flip)

        # Sort by detected_at descending
        results.sort(key=lambda x: x.get("detected_at", ""), reverse=True)

        return results[:limit]

    def get_domain_flips(
        self,
        domain: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Get all flips in a specific domain.

        Args:
            domain: The domain to filter by
            limit: Maximum results

        Returns:
            List of flip dicts
        """
        flip_ids = self._domain_flips.get(domain, [])
        results = []

        for flip_id in flip_ids[:limit]:
            flip = self._flips.get(flip_id)
            if flip:
                results.append(flip)

        return results

    def get_common_patterns(
        self,
        min_occurrences: int = 3,
        category: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Get recurring patterns above occurrence threshold.

        Args:
            min_occurrences: Minimum occurrence count
            category: Optional category filter
            limit: Maximum results

        Returns:
            List of pattern dicts sorted by occurrence count
        """
        results = []

        for pattern in self._patterns.values():
            if pattern["occurrence_count"] < min_occurrences:
                continue
            if category and pattern["category"] != category:
                continue
            results.append(pattern)

        results.sort(key=lambda x: x["occurrence_count"], reverse=True)

        return results[:limit]

    def to_knowledge_item(self, insight: dict[str, Any]) -> KnowledgeItem:
        """
        Convert an insight dict to a KnowledgeItem.

        Args:
            insight: The insight dictionary

        Returns:
            KnowledgeItem for unified knowledge mound API
        """
        from aragora.knowledge.unified.types import (
            ConfidenceLevel,
            KnowledgeItem,
            KnowledgeSource,
        )

        confidence_val = insight.get("confidence", 0.5)
        if confidence_val >= 0.9:
            confidence = ConfidenceLevel.VERIFIED
        elif confidence_val >= 0.7:
            confidence = ConfidenceLevel.HIGH
        elif confidence_val >= 0.5:
            confidence = ConfidenceLevel.MEDIUM
        elif confidence_val >= 0.3:
            confidence = ConfidenceLevel.LOW
        else:
            confidence = ConfidenceLevel.UNVERIFIED

        created_at = insight.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                created_at = datetime.now(timezone.utc)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)

        return KnowledgeItem(
            id=insight["id"],
            content=f"{insight.get('title', '')}: {insight.get('description', '')}",
            source=KnowledgeSource.INSIGHT,
            source_id=insight.get("original_id", insight["id"]),
            confidence=confidence,
            created_at=created_at,
            updated_at=created_at,
            metadata={
                "type": insight.get("type", ""),
                "debate_id": insight.get("debate_id", ""),
                "agents_involved": insight.get("agents_involved", []),
                "evidence": insight.get("evidence", []),
            },
            importance=confidence_val,
        )

    def flip_to_knowledge_item(self, flip: dict[str, Any]) -> KnowledgeItem:
        """
        Convert a flip dict to a KnowledgeItem.

        Args:
            flip: The flip dictionary

        Returns:
            KnowledgeItem for unified knowledge mound API
        """
        from aragora.knowledge.unified.types import (
            ConfidenceLevel,
            KnowledgeItem,
            KnowledgeSource,
        )

        # Flip confidence based on similarity score (higher = more confident detection)
        similarity = flip.get("similarity_score", 0.5)
        if similarity >= 0.9:
            confidence = ConfidenceLevel.VERIFIED
        elif similarity >= 0.7:
            confidence = ConfidenceLevel.HIGH
        elif similarity >= 0.5:
            confidence = ConfidenceLevel.MEDIUM
        else:
            confidence = ConfidenceLevel.LOW

        detected_at = flip.get("detected_at")
        if isinstance(detected_at, str):
            try:
                detected_at = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
            except ValueError:
                detected_at = datetime.now(timezone.utc)
        elif detected_at is None:
            detected_at = datetime.now(timezone.utc)

        content = (
            f"Agent {flip.get('agent_name', 'unknown')} flipped from "
            f"'{flip.get('original_claim', '')[:100]}' to "
            f"'{flip.get('new_claim', '')[:100]}'"
        )

        return KnowledgeItem(
            id=flip["id"],
            content=content,
            source=KnowledgeSource.FLIP,
            source_id=flip.get("original_id", flip["id"]),
            confidence=confidence,
            created_at=detected_at,
            updated_at=detected_at,
            metadata={
                "agent_name": flip.get("agent_name", ""),
                "flip_type": flip.get("flip_type", ""),
                "domain": flip.get("domain", ""),
                "original_debate_id": flip.get("original_debate_id", ""),
                "new_debate_id": flip.get("new_debate_id", ""),
                "similarity_score": similarity,
            },
            importance=similarity,
        )

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about stored insights and flips."""
        self.__init_reverse_flow_state()

        flip_types: dict[str, int] = {}
        for flip in self._flips.values():
            ft = flip.get("flip_type", "unknown")
            flip_types[ft] = flip_types.get(ft, 0) + 1

        return {
            "total_insights": len(self._insights),
            "total_flips": len(self._flips),
            "total_patterns": len(self._patterns),
            "debates_with_insights": len(self._debate_insights),
            "agents_with_flips": len(self._agent_flips),
            "domains_with_flips": len(self._domain_flips),
            "insight_types": dict((t, len(ids)) for t, ids in self._type_insights.items()),
            "flip_types": flip_types,
            # Reverse flow stats
            "km_validations_applied": self._km_validations_applied,
            "km_threshold_updates": self._km_threshold_updates,
            "km_baselines_computed": len(self._km_agent_baselines),
        }

    # ========================================================================
    # Reverse Flow Methods (KM → InsightStore/FlipDetector)
    # ========================================================================

    def __init_reverse_flow_state(self) -> None:
        """Initialize reverse flow state if not already done."""
        if not hasattr(self, "_km_validations_applied"):
            self._km_validations_applied = 0
        if not hasattr(self, "_km_threshold_updates"):
            self._km_threshold_updates = 0
        if not hasattr(self, "_km_agent_baselines"):
            self._km_agent_baselines: dict[str, KMAgentFlipBaseline] = {}
        if not hasattr(self, "_km_flip_validations"):
            self._km_flip_validations: list[KMFlipValidation] = []
        if not hasattr(self, "_outcome_history"):
            self._outcome_history: dict[str, list[dict[str, Any]]] = {}
        if not hasattr(self, "_similarity_threshold"):
            self._similarity_threshold = 0.7  # Default
        if not hasattr(self, "_confidence_threshold"):
            self._confidence_threshold = 0.6  # Default

    def record_outcome(
        self,
        flip_id: str,
        debate_id: str,
        was_accurate: bool,
        confidence: float = 0.7,
    ) -> None:
        """
        Record an outcome for a flip detection.

        This enables outcome-based validation of flip detections.

        Args:
            flip_id: The flip ID
            debate_id: The debate where this flip was detected
            was_accurate: Whether the flip detection was accurate
            confidence: Confidence in the outcome assessment
        """
        self.__init_reverse_flow_state()

        if flip_id not in self._outcome_history:
            self._outcome_history[flip_id] = []

        self._outcome_history[flip_id].append(
            {
                "debate_id": debate_id,
                "was_accurate": was_accurate,
                "confidence": confidence,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    async def update_flip_thresholds_from_km(
        self,
        km_items: list[dict[str, Any]],
        min_confidence: float = 0.7,
    ) -> KMFlipThresholdUpdate:
        """
        Reverse flow: Analyze KM patterns to update flip detection thresholds.

        Examines KM flip patterns to determine optimal thresholds for:
        - Similarity threshold: What similarity score indicates a real flip?
        - Confidence threshold: What confidence level is reliable?

        Args:
            km_items: KM items with flip metadata to analyze
            min_confidence: Minimum confidence for threshold updates

        Returns:
            KMFlipThresholdUpdate with recommended threshold changes
        """
        self.__init_reverse_flow_state()

        old_similarity = self._similarity_threshold
        old_confidence = self._confidence_threshold

        # Analyze accuracy at different similarity levels
        similarity_buckets: dict[str, list[bool]] = {
            "0.5-0.6": [],
            "0.6-0.7": [],
            "0.7-0.8": [],
            "0.8-0.9": [],
            "0.9-1.0": [],
        }

        for item in km_items:
            meta = item.get("metadata", {})
            similarity = meta.get("similarity_score", item.get("similarity_score", 0.5))
            was_accurate = meta.get("was_accurate", meta.get("outcome_success", False))

            # Bucket by similarity
            if 0.5 <= similarity < 0.6:
                similarity_buckets["0.5-0.6"].append(was_accurate)
            elif 0.6 <= similarity < 0.7:
                similarity_buckets["0.6-0.7"].append(was_accurate)
            elif 0.7 <= similarity < 0.8:
                similarity_buckets["0.7-0.8"].append(was_accurate)
            elif 0.8 <= similarity < 0.9:
                similarity_buckets["0.8-0.9"].append(was_accurate)
            elif similarity >= 0.9:
                similarity_buckets["0.9-1.0"].append(was_accurate)

        # Compute accuracy rates per bucket
        def accuracy_rate(bucket: list[bool]) -> float | None:
            if len(bucket) < 3:  # Need minimum samples
                return None
            return sum(bucket) / len(bucket)

        # Find optimal similarity threshold
        new_similarity = old_similarity
        new_confidence = old_confidence
        recommendation = "keep"
        adjustments_made = 0

        rates = {
            0.55: accuracy_rate(similarity_buckets["0.5-0.6"]),
            0.65: accuracy_rate(similarity_buckets["0.6-0.7"]),
            0.75: accuracy_rate(similarity_buckets["0.7-0.8"]),
            0.85: accuracy_rate(similarity_buckets["0.8-0.9"]),
            0.95: accuracy_rate(similarity_buckets["0.9-1.0"]),
        }

        # Find threshold where accuracy is acceptable (>= 70%)
        valid_rates = {k: v for k, v in rates.items() if v is not None and v >= 0.7}
        if valid_rates:
            # Use lowest threshold that still gives good accuracy
            new_similarity = min(valid_rates.keys())
            if new_similarity != old_similarity:
                recommendation = "decrease" if new_similarity < old_similarity else "increase"
                adjustments_made += 1

        # Compute confidence for this update
        computed_confidence = min(len(km_items) / 50, 1.0)

        # Apply new thresholds if confidence is high enough
        if computed_confidence >= min_confidence:
            self._similarity_threshold = new_similarity
            self._km_threshold_updates += 1

        update = KMFlipThresholdUpdate(
            old_similarity_threshold=old_similarity,
            new_similarity_threshold=new_similarity,
            old_confidence_threshold=old_confidence,
            new_confidence_threshold=new_confidence,
            patterns_analyzed=len(km_items),
            adjustments_made=adjustments_made,
            confidence=computed_confidence,
            recommendation=recommendation,
            metadata={
                "similarity_rates": {k: v for k, v in rates.items() if v is not None},
            },
        )

        logger.info(
            f"Flip threshold update: similarity {old_similarity:.2f} → {new_similarity:.2f} "
            f"({recommendation})"
        )

        return update

    async def get_agent_flip_baselines(
        self,
        agent_name: str,
        km_items: list[dict[str, Any]] | None = None,
    ) -> KMAgentFlipBaseline:
        """
        Get KM-validated flip baseline for an agent.

        Analyzes historical flip patterns to determine expected flip rates
        and type distributions for this agent.

        Args:
            agent_name: Name of the agent
            km_items: Optional KM items to analyze (uses cached if not provided)

        Returns:
            KMAgentFlipBaseline with expected rates
        """
        self.__init_reverse_flow_state()

        # Check cache first
        if agent_name in self._km_agent_baselines and km_items is None:
            return self._km_agent_baselines[agent_name]

        # Also use locally stored flips
        agent_flips = self.get_agent_flip_history(agent_name, limit=1000)

        # Analyze items for this agent
        flip_count = len(agent_flips)
        debate_ids = set()
        flip_type_counts: dict[str, int] = {}
        domain_flip_counts: dict[str, int] = {}

        for flip in agent_flips:
            # Count debates
            if orig_debate := flip.get("original_debate_id"):
                debate_ids.add(orig_debate)
            if new_debate := flip.get("new_debate_id"):
                debate_ids.add(new_debate)

            # Count flip types
            flip_type = flip.get("flip_type", "unknown")
            flip_type_counts[flip_type] = flip_type_counts.get(flip_type, 0) + 1

            # Count domains
            domain = flip.get("domain")
            if domain:
                domain_flip_counts[domain] = domain_flip_counts.get(domain, 0) + 1

        # Also analyze KM items if provided
        if km_items:
            for item in km_items:
                meta = item.get("metadata", {})
                if meta.get("agent_name") == agent_name:
                    flip_count += 1
                    if debate_id := meta.get("debate_id"):
                        debate_ids.add(debate_id)
                    flip_type = meta.get("flip_type", "unknown")
                    flip_type_counts[flip_type] = flip_type_counts.get(flip_type, 0) + 1

        # Compute expected flip rate
        num_debates = len(debate_ids) if debate_ids else 1
        expected_flip_rate = flip_count / num_debates if num_debates > 0 else 0.0

        # Compute type distribution
        total_flips = sum(flip_type_counts.values()) or 1
        flip_type_distribution = {k: v / total_flips for k, v in flip_type_counts.items()}

        # Compute domain flip rates
        domain_flip_rates = {k: v / num_debates for k, v in domain_flip_counts.items()}

        # Confidence based on sample size
        sample_confidence = min(flip_count / 20, 1.0)

        baseline = KMAgentFlipBaseline(
            agent_name=agent_name,
            expected_flip_rate=expected_flip_rate,
            flip_type_distribution=flip_type_distribution,
            domain_flip_rates=domain_flip_rates,
            sample_count=flip_count,
            confidence=sample_confidence,
            metadata={
                "num_debates": num_debates,
                "total_flips": flip_count,
            },
        )

        # Cache the result
        self._km_agent_baselines[agent_name] = baseline

        return baseline

    async def validate_flip_from_km(
        self,
        flip_id: str,
        km_patterns: list[dict[str, Any]],
    ) -> KMFlipValidation:
        """
        Validate a flip based on KM patterns.

        Examines how this flip relates to known patterns to determine
        if it's expected behavior or should be flagged.

        Args:
            flip_id: The flip ID to validate
            km_patterns: Related KM patterns for cross-referencing

        Returns:
            KMFlipValidation with recommendation
        """
        self.__init_reverse_flow_state()

        flip = self.get_flip(flip_id)
        if not flip:
            return KMFlipValidation(
                flip_id=flip_id,
                km_confidence=0.0,
                recommendation="keep",
                metadata={"error": "flip_not_found"},
            )

        agent_name = flip.get("agent_name", "")
        flip_type = flip.get("flip_type", "")
        domain = flip.get("domain", "")
        similarity_score = flip.get("similarity_score", 0.5)

        # Get agent baseline
        baseline = await self.get_agent_flip_baselines(agent_name)

        # Check if this flip type is expected for this agent
        expected_type_rate = baseline.flip_type_distribution.get(flip_type, 0.0)
        expected_domain_rate = baseline.domain_flip_rates.get(domain, 0.0) if domain else 0.0

        # Analyze patterns
        pattern_match_count = 0
        pattern_support_count = 0

        for pattern in km_patterns:
            meta = pattern.get("metadata", {})
            if meta.get("flip_type") == flip_type:
                pattern_match_count += 1
            if meta.get("relationship") == "supports":
                pattern_support_count += 1

        # Determine if flip is expected
        is_expected = (
            expected_type_rate >= 0.1  # Agent commonly has this flip type
            or pattern_match_count >= 2  # Multiple pattern matches
            or similarity_score >= 0.9  # Very high confidence detection
        )

        # Pattern match score
        pattern_match_score = min(pattern_match_count / 5, 1.0) if pattern_match_count > 0 else 0.0

        # Determine recommendation
        if similarity_score < self._similarity_threshold:
            recommendation = "ignore"
            adjustment = 0.0  # Don't penalize agent
        elif is_expected and pattern_support_count > 0:
            recommendation = "keep"
            adjustment = -0.02  # Small penalty for expected flip
        elif not is_expected and expected_type_rate < 0.05:
            recommendation = "flag"
            adjustment = -0.1  # Larger penalty for unexpected flip
        else:
            recommendation = "keep"
            adjustment = -0.05

        # KM confidence based on evidence
        km_confidence = 0.5
        if pattern_match_count > 0:
            km_confidence += 0.1 * min(pattern_match_count / 3, 1.0)
        if similarity_score >= 0.8:
            km_confidence += 0.2
        km_confidence = min(km_confidence, 1.0)

        validation = KMFlipValidation(
            flip_id=flip_id,
            km_confidence=km_confidence,
            is_expected=is_expected,
            pattern_match_score=pattern_match_score,
            recommendation=recommendation,
            adjustment=adjustment,
            metadata={
                "expected_type_rate": expected_type_rate,
                "expected_domain_rate": expected_domain_rate,
                "pattern_match_count": pattern_match_count,
                "pattern_support_count": pattern_support_count,
            },
        )

        self._km_flip_validations.append(validation)
        self._km_validations_applied += 1

        return validation

    async def apply_km_validation(
        self,
        validation: KMFlipValidation,
    ) -> bool:
        """
        Apply a KM validation to update the flip's metadata.

        Args:
            validation: The validation result to apply

        Returns:
            True if applied successfully
        """
        self.__init_reverse_flow_state()

        flip = self._flips.get(validation.flip_id)
        if not flip:
            # Try with prefix
            prefixed_id = f"{self.FLIP_PREFIX}{validation.flip_id}"
            flip = self._flips.get(prefixed_id)
            if not flip:
                return False

        # Update flip metadata
        flip["km_validated"] = True
        flip["km_validation_time"] = datetime.now(timezone.utc).isoformat()
        flip["km_confidence"] = validation.km_confidence
        flip["km_is_expected"] = validation.is_expected
        flip["km_recommendation"] = validation.recommendation

        logger.info(
            "Applied KM validation to flip %s: expected=%s, recommendation=%s",
            validation.flip_id,
            validation.is_expected,
            validation.recommendation,
        )

        return True

    async def sync_validations_from_km(
        self,
        km_items: list[dict[str, Any]],
        min_confidence: float = 0.7,
    ) -> InsightThresholdSyncResult:
        """
        Batch sync KM validations to insights/flips.

        Args:
            km_items: KM items with validation data
            min_confidence: Minimum confidence for applying validations

        Returns:
            InsightThresholdSyncResult with sync details
        """
        import time

        self.__init_reverse_flow_state()

        start_time = time.time()
        result = InsightThresholdSyncResult()
        errors = []

        # Group items by flip_id
        items_by_flip: dict[str, list[dict[str, Any]]] = {}
        for item in km_items:
            meta = item.get("metadata", {})
            flip_id = meta.get("flip_id") or meta.get("source_id")
            if flip_id:
                if flip_id not in items_by_flip:
                    items_by_flip[flip_id] = []
                items_by_flip[flip_id].append(item)

        # Validate each flip
        for flip_id, patterns in items_by_flip.items():
            try:
                result.flips_analyzed += 1

                validation = await self.validate_flip_from_km(flip_id, patterns)

                # Apply if confidence is high enough
                if validation.km_confidence >= min_confidence:
                    await self.apply_km_validation(validation)

            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                errors.append(f"Error validating {flip_id}: {e}")

        # Also update thresholds
        try:
            flip_items = [
                item
                for item in km_items
                if item.get("metadata", {}).get("similarity_score") is not None
            ]
            if flip_items:
                threshold_update = await self.update_flip_thresholds_from_km(
                    flip_items, min_confidence
                )
                result.threshold_updates.append(threshold_update)
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            errors.append(f"Error updating thresholds: {e}")

        # Update agent baselines
        agents_seen = set()
        for item in km_items:
            meta = item.get("metadata", {})
            if agent_name := meta.get("agent_name"):
                agents_seen.add(agent_name)

        for agent_name in agents_seen:
            try:
                baseline = await self.get_agent_flip_baselines(agent_name, km_items)
                result.baseline_updates.append(baseline)
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                errors.append(f"Error computing baseline for {agent_name}: {e}")

        result.errors = errors
        result.duration_ms = (time.time() - start_time) * 1000

        return result

    def get_reverse_flow_stats(self) -> dict[str, Any]:
        """Get statistics about reverse flow operations."""
        self.__init_reverse_flow_state()

        return {
            "km_validations_applied": self._km_validations_applied,
            "km_threshold_updates": self._km_threshold_updates,
            "km_baselines_computed": len(self._km_agent_baselines),
            "validations_stored": len(self._km_flip_validations),
            "outcome_history_size": sum(len(v) for v in self._outcome_history.values()),
            "current_similarity_threshold": self._similarity_threshold,
            "current_confidence_threshold": self._confidence_threshold,
        }

    def clear_reverse_flow_state(self) -> None:
        """Clear all reverse flow state (for testing)."""
        self._km_validations_applied = 0
        self._km_threshold_updates = 0
        self._km_agent_baselines = {}
        self._km_flip_validations = []
        self._outcome_history = {}
        # Reset thresholds to defaults
        self._similarity_threshold = 0.7
        self._confidence_threshold = 0.6


__all__ = [
    "InsightsAdapter",
    "InsightSearchResult",
    "FlipSearchResult",
    # Reverse flow dataclasses
    "KMFlipThresholdUpdate",
    "KMAgentFlipBaseline",
    "KMFlipValidation",
    "InsightThresholdSyncResult",
]
