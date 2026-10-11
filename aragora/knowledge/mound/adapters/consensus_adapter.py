"""
ConsensusAdapter - Bridges ConsensusMemory to the Knowledge Mound.

This adapter enables the Knowledge Mound to query debate outcomes and
dissenting views stored in ConsensusMemory.

The adapter provides:
- Unified search interface (search_by_topic)
- Consensus-to-KnowledgeItem conversion
- Dissent tracking for organizational learning
- Domain-based filtering
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.memory.consensus import (
        ConsensusMemory,
        ConsensusRecord,
        DissentRecord,
    )
    from aragora.knowledge.mound.types import KnowledgeItem

# Type alias for event callback
EventCallback = Callable[[str, dict[str, Any]], None]


logger = logging.getLogger(__name__)

# Import mixins for shared adapter functionality
from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter
from aragora.knowledge.mound.adapters._semantic_mixin import SemanticSearchMixin
from aragora.knowledge.mound.adapters._reverse_flow_base import ReverseFlowMixin
from aragora.knowledge.mound.adapters._fusion_mixin import FusionMixin
from aragora.knowledge.mound.adapters._types import SyncResult, ValidationSyncResult


@dataclass
class ConsensusSearchResult:
    """Wrapper for consensus search results with similarity metadata."""

    record: ConsensusRecord
    similarity: float = 0.0
    dissents: list[DissentRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.dissents is None:
            self.dissents = []


class ConsensusAdapter(FusionMixin, ReverseFlowMixin, SemanticSearchMixin, KnowledgeMoundAdapter):
    """
    Adapter that bridges ConsensusMemory to the Knowledge Mound.

    Provides methods that the Knowledge Mound expects for federated queries:
    - search_by_topic: Find similar debates and consensus outcomes
    - to_knowledge_item: Convert records to unified format
    - get_dissents: Retrieve dissenting views for a topic
    - semantic_search: Vector-based similarity search (via SemanticSearchMixin)

    Resilience Features:
    - Circuit breaker protection for external service calls
    - Bulkhead isolation to prevent cascading failures
    - Automatic retry with exponential backoff

    Usage:
        from aragora.memory.consensus import ConsensusMemory
        from aragora.knowledge.mound.adapters import ConsensusAdapter

        consensus = ConsensusMemory()
        adapter = ConsensusAdapter(consensus)

        # Search for similar debates
        results = await adapter.search_by_topic("rate limiting", limit=10)

        # Convert to knowledge items
        items = [adapter.to_knowledge_item(r) for r in results]
    """

    # SemanticSearchMixin configuration
    adapter_name = "consensus"
    source_type = "consensus"

    def __init__(
        self,
        consensus: ConsensusMemory,
        enable_dual_write: bool = False,
        event_callback: EventCallback | None = None,
        enable_resilience: bool = True,
    ):
        """
        Initialize the adapter.

        Args:
            consensus: The ConsensusMemory instance to wrap
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

        self._consensus = consensus

    # set_event_callback, _emit_event, _record_metric inherited from KnowledgeMoundAdapter

    @property
    def consensus(self) -> ConsensusMemory:
        """Access the underlying ConsensusMemory."""
        return self._consensus

    # SemanticSearchMixin required methods
    def _get_record_by_id(self, record_id: str) -> Any | None:
        """Get a consensus record by ID (required by SemanticSearchMixin)."""
        # Handle prefixed IDs from SemanticStore
        if record_id.startswith("cs_"):
            record_id = record_id[3:]
        return self._consensus.get_consensus(record_id)

    def _record_to_dict(self, record: Any, similarity: float = 0.0) -> dict[str, Any]:
        """Convert a consensus record to dict (required by SemanticSearchMixin)."""
        return {
            "id": record.id,
            "topic": record.topic,
            "conclusion": record.conclusion,
            "strength": record.strength.value
            if hasattr(record.strength, "value")
            else record.strength,
            "confidence": record.confidence,
            "domain": record.domain,
            "similarity": similarity,
            "timestamp": (
                record.timestamp.isoformat()
                if hasattr(record.timestamp, "isoformat")
                else str(record.timestamp)
            ),
            "metadata": record.metadata,
        }

    def _extract_record_id(self, source_id: str) -> str:
        """Extract record ID from prefixed source ID (override for SemanticSearchMixin)."""
        if source_id.startswith("cs_"):
            return source_id[3:]
        return source_id

    # ReverseFlowMixin required methods
    def _get_record_for_validation(self, source_id: str) -> Any | None:
        """Get a consensus record for validation (required by ReverseFlowMixin)."""
        return self.get(source_id)

    def _apply_km_validation(
        self,
        record: Any,
        km_confidence: float,
        cross_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Apply KM validation to a consensus record (required by ReverseFlowMixin)."""
        record.metadata["km_validated"] = True
        record.metadata["km_validation_confidence"] = km_confidence
        if metadata:
            for key, value in metadata.items():
                record.metadata[key] = value
        if cross_refs:
            record.metadata["km_cross_references"] = cross_refs
        return True

    def _extract_source_id(self, item: dict[str, Any]) -> str | None:
        """Extract source ID from KM item (override for ReverseFlowMixin)."""
        meta = item.get("metadata", {})
        return meta.get("source_id") or meta.get("consensus_id") or item.get("id")

    async def search_by_topic(
        self,
        query: str,
        limit: int = 10,
        domain: str | None = None,
        min_confidence: float = 0.0,
        include_dissents: bool = True,
    ) -> list[ConsensusSearchResult]:
        """
        Search consensus memory by topic.

        This method wraps ConsensusMemory.find_similar_debates() to provide
        the interface expected by KnowledgeMound._query_consensus().

        Args:
            query: Topic to search for
            limit: Maximum results to return
            domain: Optional domain filter
            min_confidence: Minimum confidence threshold
            include_dissents: Whether to include dissenting views

        Returns:
            List of ConsensusSearchResult with records and dissents
        """
        # Use ConsensusMemory's find_similar_debates method
        similar = self._consensus.find_similar_debates(
            topic=query,
            domain=domain,
            min_confidence=min_confidence,
            limit=limit,
        )

        results = []
        for debate in similar:
            # SimilarDebate has: consensus, dissents, similarity
            result = ConsensusSearchResult(
                record=debate.consensus,
                similarity=debate.similarity,
                dissents=debate.dissents if include_dissents else [],
            )
            results.append(result)

        return results

    def get(self, record_id: str) -> ConsensusRecord | None:
        """
        Get a specific consensus record by ID.

        Args:
            record_id: The record ID (may be prefixed with "cs_" from mound)

        Returns:
            ConsensusRecord or None
        """
        # Strip mound prefix if present
        if record_id.startswith("cs_"):
            record_id = record_id[3:]

        return self._consensus.get_consensus(record_id)

    async def get_async(self, record_id: str) -> ConsensusRecord | None:
        """Async version of get for compatibility."""
        return self.get(record_id)

    def to_knowledge_item(
        self,
        record: ConsensusRecord | ConsensusSearchResult,
    ) -> KnowledgeItem:
        """
        Convert a ConsensusRecord to a KnowledgeItem.

        Args:
            record: The consensus record or search result

        Returns:
            KnowledgeItem for unified knowledge mound API
        """
        from aragora.knowledge.mound.types import (
            ConfidenceLevel,
            KnowledgeItem,
            KnowledgeSource,
        )

        # Handle both ConsensusRecord and ConsensusSearchResult
        if isinstance(record, ConsensusSearchResult):
            consensus = record.record
            similarity = record.similarity
        else:
            consensus = record
            similarity = 1.0

        # Map consensus strength to confidence level
        strength_to_confidence = {
            "unanimous": ConfidenceLevel.VERIFIED,
            "strong": ConfidenceLevel.HIGH,
            "moderate": ConfidenceLevel.MEDIUM,
            "weak": ConfidenceLevel.LOW,
            "split": ConfidenceLevel.LOW,
            "contested": ConfidenceLevel.UNVERIFIED,
        }
        confidence = strength_to_confidence.get(consensus.strength.value, ConfidenceLevel.MEDIUM)

        # Use conclusion as content, with topic as fallback
        content = consensus.conclusion or consensus.topic

        # Build metadata
        metadata: dict[str, Any] = {
            "topic": consensus.topic,
            "strength": consensus.strength.value,
            "domain": consensus.domain,
            "tags": consensus.tags,
            "participating_agents": consensus.participating_agents,
            "agreeing_agents": consensus.agreeing_agents,
            "dissenting_agents": consensus.dissenting_agents,
            "key_claims": consensus.key_claims,
            "supporting_evidence": consensus.supporting_evidence,
            "dissent_ids": consensus.dissent_ids,
            "rounds": consensus.rounds,
            "debate_duration_seconds": consensus.debate_duration_seconds,
            "agreement_ratio": consensus.compute_agreement_ratio(),
            "similarity": similarity,
        }

        if consensus.supersedes:
            metadata["supersedes"] = consensus.supersedes
        if consensus.superseded_by:
            metadata["superseded_by"] = consensus.superseded_by

        return KnowledgeItem(
            id=f"cs_{consensus.id}",
            content=content,
            source=KnowledgeSource.CONSENSUS,
            source_id=consensus.id,
            confidence=confidence,
            created_at=consensus.timestamp,
            updated_at=consensus.timestamp,
            metadata=metadata,
            importance=consensus.confidence,
        )

    def dissent_to_knowledge_item(
        self,
        dissent: DissentRecord,
    ) -> KnowledgeItem:
        """
        Convert a DissentRecord to a KnowledgeItem.

        Dissenting views are valuable organizational knowledge that can
        inform future decisions and reveal edge cases.

        Args:
            dissent: The dissent record

        Returns:
            KnowledgeItem for the dissenting view
        """
        from aragora.knowledge.mound.types import (
            ConfidenceLevel,
            KnowledgeItem,
            KnowledgeSource,
        )

        # All dissents are initially low confidence since they're minority views
        # but they can be valuable for edge case detection
        confidence = ConfidenceLevel.LOW
        if dissent.dissent_type.value == "risk_warning":
            confidence = ConfidenceLevel.MEDIUM  # Risk warnings deserve attention

        metadata: dict[str, Any] = {
            "debate_id": dissent.debate_id,
            "agent_id": dissent.agent_id,
            "dissent_type": dissent.dissent_type.value,
            "reasoning": dissent.reasoning,
            "acknowledged": dissent.acknowledged,
            "rebuttal": dissent.rebuttal,
        }

        return KnowledgeItem(
            id=f"ds_{dissent.id}",
            content=dissent.content,
            source=KnowledgeSource.CONSENSUS,  # Dissent is part of consensus process
            source_id=dissent.id,
            confidence=confidence,
            created_at=dissent.timestamp,
            updated_at=dissent.timestamp,
            metadata=metadata,
            importance=dissent.confidence,
        )

    def get_dissents_for_topic(
        self,
        topic: str,
        limit: int = 20,
    ) -> list[DissentRecord]:
        """
        Get dissenting views related to a topic.

        Args:
            topic: Topic to search for dissents
            limit: Maximum dissents to return

        Returns:
            List of DissentRecord objects
        """
        return self._consensus.find_relevant_dissent(topic=topic, limit=limit)

    def get_risk_warnings(
        self,
        topic: str | None = None,
        limit: int = 10,
    ) -> list[DissentRecord]:
        """
        Get risk warnings from debates.

        Risk warnings are particularly valuable for organizational learning
        as they capture potential issues identified during debates.

        Args:
            topic: Optional topic filter
            limit: Maximum warnings to return

        Returns:
            List of DissentRecord with type RISK_WARNING
        """
        from aragora.memory.consensus import DissentType

        if topic:
            return self._consensus.find_relevant_dissent(
                topic=topic,
                dissent_types=[DissentType.RISK_WARNING, DissentType.EDGE_CASE_CONCERN],
                limit=limit,
            )
        # Without topic, search broadly using a generic query
        return self._consensus.find_relevant_dissent(
            topic="risk warning concern edge case",
            dissent_types=[DissentType.RISK_WARNING, DissentType.EDGE_CASE_CONCERN],
            limit=limit,
        )

    def get_contrarian_views(
        self,
        limit: int = 10,
    ) -> list[DissentRecord]:
        """
        Get fundamental disagreements from debates.

        These represent strongly held alternative views that may indicate
        areas of genuine uncertainty or multiple valid approaches.

        Args:
            limit: Maximum views to return

        Returns:
            List of DissentRecord with type FUNDAMENTAL_DISAGREEMENT
        """
        from aragora.memory.consensus import DissentType

        # Search for fundamental disagreements and alternative approaches
        return self._consensus.find_relevant_dissent(
            topic="fundamental disagreement alternative approach",
            dissent_types=[
                DissentType.FUNDAMENTAL_DISAGREEMENT,
                DissentType.ALTERNATIVE_APPROACH,
            ],
            limit=limit,
        )

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the consensus memory."""
        return self._consensus.get_statistics()

    def search_similar(
        self,
        topic: str,
        limit: int = 5,
        min_confidence: float = 0.7,
    ) -> list[dict[str, Any]]:
        """
        Find similar consensus records for deduplication (reverse flow).

        Args:
            topic: Topic to find similar consensus for
            limit: Maximum results
            min_confidence: Minimum confidence threshold

        Returns:
            List of similar consensus records as dicts
        """
        import time

        start = time.time()
        success = False

        try:
            similar = self._consensus.find_similar_debates(
                topic=topic,
                min_confidence=min_confidence,
                limit=limit,
            )

            # Convert to dict format for consistency
            results = [
                {
                    "id": d.consensus.id,
                    "topic": d.consensus.topic,
                    "conclusion": d.consensus.conclusion,
                    "strength": d.consensus.strength.value,
                    "confidence": d.consensus.confidence,
                    "domain": d.consensus.domain,
                    "similarity": d.similarity,
                    "timestamp": (
                        d.consensus.timestamp.isoformat()
                        if hasattr(d.consensus.timestamp, "isoformat")
                        else str(d.consensus.timestamp)
                    ),
                }
                for d in similar
            ]

            # Emit dashboard event for reverse flow query
            self._emit_event(
                "km_adapter_reverse_query",
                {
                    "source": "consensus",
                    "topic_preview": topic[:50] + "..." if len(topic) > 50 else topic,
                    "results_count": len(results),
                    "limit": limit,
                },
            )

            success = True
            return results
        finally:
            self._record_metric("search", success, time.time() - start)

    def store_consensus(self, record: ConsensusRecord) -> None:
        """
        Mark a consensus record for KM sync (forward flow).

        This is called by ConsensusMemory when a high-confidence consensus
        is stored and should be synced to KM for cross-session learning.

        Args:
            record: The ConsensusRecord to mark for sync
        """
        from datetime import datetime

        logger.debug(
            f"Consensus marked for KM sync: {record.id} "
            f"(topic={record.topic[:50]}..., confidence={record.confidence:.2f})"
        )
        # Mark the record as pending KM sync in metadata
        if not record.metadata.get("km_sync_pending"):
            record.metadata["km_sync_pending"] = True
            record.metadata["km_sync_requested_at"] = datetime.now().isoformat()

        # Emit dashboard event for forward sync
        self._emit_event(
            "km_adapter_forward_sync",
            {
                "source": "consensus",
                "consensus_id": record.id,
                "topic_preview": (
                    record.topic[:50] + "..." if len(record.topic) > 50 else record.topic
                ),
                "confidence": record.confidence,
                "strength": record.strength.value,
            },
        )

    def _get_all_consensus_records(self) -> list[ConsensusRecord]:
        """Get all consensus records from the underlying ConsensusMemory.

        This helper method provides access to all records for sync operations
        by querying the database directly.

        Returns:
            List of all ConsensusRecord objects
        """
        from aragora.memory.consensus import ConsensusRecord
        from aragora.utils.json_helpers import safe_json_loads

        records: list[ConsensusRecord] = []
        with self._consensus.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data FROM consensus ORDER BY timestamp DESC")
            for row in cursor.fetchall():
                data: dict[str, Any] = safe_json_loads(row[0], {}, context="consensus:get_all")
                if data:
                    records.append(ConsensusRecord.from_dict(data))
        return records

    async def sync_to_km(
        self,
        mound: Any,
        min_confidence: float = 0.7,
        batch_size: int = 50,
    ) -> SyncResult:
        """
        Sync pending consensus records to Knowledge Mound (forward flow).

        This method finds all records marked with km_sync_pending=True,
        converts them to KnowledgeItems, and stores them in the mound.

        Args:
            mound: The KnowledgeMound instance to sync to
            min_confidence: Minimum confidence threshold for syncing
            batch_size: Maximum records to sync in one call

        Returns:
            Dict with sync statistics:
            - records_synced: Number of records successfully synced
            - records_skipped: Number skipped (already synced or low confidence)
            - records_failed: Number that failed to sync
            - errors: List of error messages
        """
        import time
        from datetime import datetime

        start = time.time()
        result = SyncResult()

        # Find all pending records
        pending_records: list[ConsensusRecord] = []
        for record in self._get_all_consensus_records():
            if record.metadata.get("km_sync_pending") and record.confidence >= min_confidence:
                pending_records.append(record)
            elif record.confidence < min_confidence:
                result.records_skipped += 1

        if not pending_records:
            logger.debug("No pending consensus records to sync to KM")
            result.duration_ms = (time.time() - start) * 1000
            return result

        logger.info("Syncing %s consensus records to KM", len(pending_records[:batch_size]))

        # Batch process records
        for record in pending_records[:batch_size]:
            try:
                # Convert to KnowledgeItem
                km_item = self.to_knowledge_item(record)

                # Store in mound
                if hasattr(mound, "store_item"):
                    await mound.store_item(km_item)
                elif hasattr(mound, "store"):
                    await mound.store(km_item)
                else:
                    # Fallback: use mound's semantic store directly
                    if hasattr(mound, "_semantic_store"):
                        await mound._semantic_store.store(km_item)

                # Clear pending flag and record sync time
                record.metadata["km_sync_pending"] = False
                record.metadata["km_synced_at"] = datetime.now().isoformat()
                record.metadata["km_item_id"] = km_item.id

                result.records_synced += 1

                # Emit event for successful sync
                self._emit_event(
                    "km_adapter_forward_sync_complete",
                    {
                        "source": "consensus",
                        "consensus_id": record.id,
                        "km_item_id": km_item.id,
                        "confidence": record.confidence,
                    },
                )

            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                result.records_failed += 1
                logger.warning("Failed to sync consensus %s: %s", record.id, e)
                result.errors.append(f"Failed to sync consensus {record.id}")

                # Mark as failed but keep pending for retry
                record.metadata["km_sync_error"] = f"Sync failed: {type(e).__name__}"
                record.metadata["km_sync_failed_at"] = datetime.now().isoformat()

        result.duration_ms = (time.time() - start) * 1000

        # Record metrics
        self._record_metric(
            "sync",
            result.records_failed == 0,
            result.duration_ms / 1000,
        )

        logger.info(
            "Consensus KM sync complete: synced=%s, skipped=%s, failed=%s",
            result.records_synced,
            result.records_skipped,
            result.records_failed,
        )

        return result

    # Override has different signature than base class - intentionally accepts
    # km_items list instead of generic interface for consensus-specific sync.
    async def sync_validations_from_km(  # type: ignore[override]
        self,
        km_items: list[dict[str, Any]],
        min_confidence: float = 0.7,
        batch_size: int = 100,
    ) -> ValidationSyncResult:
        """
        Sync KM validations back to ConsensusMemory (reverse flow).

        When KM validates or cross-references consensus records, this method
        updates the source records with validation metadata.

        Args:
            km_items: KM items with validation data
            min_confidence: Minimum confidence for applying changes

        Returns:
            Dict with sync statistics
        """
        import time
        from datetime import datetime

        start_time = time.time()
        result: dict[str, Any] = {
            "records_analyzed": 0,
            "records_updated": 0,
            "records_skipped": 0,
            "errors": [],
            "duration_ms": 0.0,
        }

        for item in km_items:
            meta = item.get("metadata", {})
            source_id = meta.get("source_id") or meta.get("consensus_id")

            if not source_id:
                continue

            result["records_analyzed"] += 1

            try:
                # Get the consensus record
                record = self.get(source_id)
                if record is None:
                    result["records_skipped"] += 1
                    continue

                # Extract KM validation data
                km_confidence = item.get("confidence", 0.0)
                if isinstance(km_confidence, str):
                    # Handle confidence level strings
                    km_confidence = {"low": 0.3, "medium": 0.6, "high": 0.9}.get(
                        km_confidence.lower(), 0.5
                    )

                if km_confidence < min_confidence:
                    result["records_skipped"] += 1
                    continue

                # Update metadata with KM validation info
                record.metadata["km_validated"] = True
                record.metadata["km_validation_confidence"] = km_confidence
                record.metadata["km_validation_timestamp"] = datetime.now().isoformat()

                if cross_refs := meta.get("cross_references"):
                    record.metadata["km_cross_references"] = cross_refs

                result["records_updated"] += 1

                # Emit event for reverse sync
                self._emit_event(
                    "km_adapter_reverse_sync",
                    {
                        "source": "consensus",
                        "consensus_id": source_id,
                        "km_confidence": km_confidence,
                        "action": "validated",
                    },
                )

            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.warning("Reverse sync failed for consensus %s: %s", source_id, e)
                result["errors"].append(f"Failed to update {source_id}")

        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            "Consensus reverse sync complete: analyzed=%s, updated=%s",
            result["records_analyzed"],
            result["records_updated"],
        )

        return ValidationSyncResult(
            records_analyzed=result["records_analyzed"],
            records_updated=result["records_updated"],
            records_skipped=result["records_skipped"],
            errors=result["errors"],
            duration_ms=duration_ms,
        )

    # =========================================================================
    # FusionMixin Implementation
    # =========================================================================

    def _get_fusion_sources(self) -> list[str]:
        """Return list of adapter names this adapter can fuse data from.

        ConsensusAdapter can fuse validations from ELO (agent performance),
        Evidence (supporting data), and Belief (claim confidence) adapters.
        """
        return ["elo", "evidence", "belief", "continuum"]

    def _extract_fusible_data(self, km_item: dict[str, Any]) -> dict[str, Any] | None:
        """Extract data from a KM item that can be used for fusion.

        Args:
            km_item: Knowledge Mound item dict

        Returns:
            Dict with fusible fields, or None if not fusible
        """
        metadata = km_item.get("metadata", {})

        # Extract consensus-relevant fields
        item_id = metadata.get("source_id") or metadata.get("consensus_id") or km_item.get("id")

        if not item_id:
            return None

        confidence = km_item.get("confidence", 0.5)
        if isinstance(confidence, str):
            confidence = {"low": 0.3, "medium": 0.6, "high": 0.9}.get(confidence.lower(), 0.5)

        return {
            "item_id": item_id,
            "confidence": confidence,
            "source_adapter": metadata.get("source_adapter", "unknown"),
            "consensus_strength": metadata.get("consensus_strength"),
            "validation_count": metadata.get("validation_count", 1),
        }

    def _apply_fusion_result(
        self,
        record: Any,
        fusion_result: Any,  # FusedValidation from ops.fusion
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Apply a fusion result to a consensus record.

        Args:
            record: The ConsensusRecord to update
            fusion_result: FusedValidation with fused confidence/validity
            metadata: Optional additional metadata

        Returns:
            True if successfully applied, False otherwise
        """
        from datetime import datetime

        try:
            # Update record metadata with fusion results
            record.metadata["fusion_applied"] = True
            record.metadata["fused_confidence"] = fusion_result.fused_confidence
            record.metadata["fusion_is_valid"] = fusion_result.is_valid
            record.metadata["fusion_strategy"] = fusion_result.strategy_used.value
            record.metadata["fusion_source_count"] = len(fusion_result.source_validations)
            record.metadata["fusion_timestamp"] = datetime.now().isoformat()

            if metadata:
                record.metadata["fusion_metadata"] = metadata

            # Emit event for fusion application
            self._emit_event(
                "km_adapter_fusion_applied",
                {
                    "adapter": "consensus",
                    "record_id": getattr(record, "id", None)
                    or getattr(record, "debate_id", "unknown"),
                    "fused_confidence": fusion_result.fused_confidence,
                    "is_valid": fusion_result.is_valid,
                    "source_count": len(fusion_result.source_validations),
                },
            )

            logger.debug(
                f"Applied fusion to consensus record: "
                f"confidence={fusion_result.fused_confidence:.2f}, "
                f"sources={len(fusion_result.source_validations)}"
            )

            return True

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to apply fusion result: %s", e)
            return False
