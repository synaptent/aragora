"""
ContinuumAdapter - Bridges ContinuumMemory to the Knowledge Mound.

This adapter enables bidirectional integration between ContinuumMemory's
multi-tier system and the Knowledge Mound:

- Data flow IN: ContinuumMemory entries with importance scores are stored in KM
- Data flow OUT: Similar memories are retrieved for context/grounding
- Reverse flow: KM validation feeds back to memory tier promotions/demotions

The adapter provides:
- Unified search interface (search_by_keyword)
- Bidirectional sync (store to both systems)
- Tier-to-importance mapping
- Cross-reference tracking
- **KM validation → tier adjustment (reverse flow)**
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.memory.continuum import ContinuumMemory, ContinuumMemoryEntry
    from aragora.knowledge.mound.types import KnowledgeItem, IngestionRequest

# Type alias for event callback
EventCallback = Callable[[str, dict[str, Any]], None]

logger = logging.getLogger(__name__)

# Import mixins for semantic search and fusion functionality
from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter
from aragora.knowledge.mound.adapters._semantic_mixin import SemanticSearchMixin
from aragora.knowledge.mound.adapters._fusion_mixin import FusionMixin


@dataclass
class KMValidationResult:
    """Result of Knowledge Mound validation for a memory item.

    This represents feedback from KM analysis that can improve
    ContinuumMemory tier placement and importance scores.
    """

    memory_id: str
    km_confidence: float  # 0.0-1.0 KM's confidence in the memory
    cross_debate_utility: float = 0.0  # How useful across debates (0.0-1.0)
    validation_count: int = 1  # Number of validations/uses
    was_contradicted: bool = False  # If KM found contradicting evidence
    was_supported: bool = False  # If KM found supporting evidence
    recommendation: str = "keep"  # "promote", "demote", "keep", "review"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationSyncResult:
    """Result of batch syncing KM validations to ContinuumMemory."""

    total_processed: int = 0
    promoted: int = 0
    demoted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0


@dataclass
class ContinuumSearchResult:
    """Wrapper for continuum memory search results with adapter metadata."""

    entry: ContinuumMemoryEntry
    relevance_score: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.matched_keywords is None:
            self.matched_keywords = []


class ContinuumAdapter(FusionMixin, SemanticSearchMixin, KnowledgeMoundAdapter):
    """
    Adapter that bridges ContinuumMemory to the Knowledge Mound.

    Provides methods that the Knowledge Mound expects for federated queries:
    - search_by_keyword: Text-based search across tiers
    - to_knowledge_item: Convert entries to unified format
    - sync_from_mound: Store mound items in continuum memory
    - semantic_search: Vector-based similarity search (via SemanticSearchMixin)

    Usage:
        from aragora.memory.continuum import ContinuumMemory
        from aragora.knowledge.mound.adapters import ContinuumAdapter

        continuum = ContinuumMemory()
        adapter = ContinuumAdapter(continuum)

        # Search for memories
        results = adapter.search_by_keyword("type errors", limit=10)

        # Convert to knowledge items
        items = [adapter.to_knowledge_item(r) for r in results]
    """

    # SemanticSearchMixin configuration
    adapter_name = "continuum"
    source_type = "continuum"

    # FusionMixin abstract method implementations
    def _get_fusion_sources(self) -> list[str]:
        """Return list of source adapters this adapter can fuse data from."""
        return ["consensus", "elo", "evidence", "belief", "insights"]

    def _extract_fusible_data(
        self,
        km_item: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Extract fusible data from a KM item.

        Args:
            km_item: A Knowledge Mound item with validation data.

        Returns:
            Dictionary of extracted data suitable for fusion.
        """
        metadata = km_item.get("metadata", {})
        confidence = km_item.get("confidence") or metadata.get("confidence", 0.5)

        # Extract tier information
        tier = metadata.get("tier") or metadata.get("continuum_tier")

        return {
            "confidence": float(confidence) if confidence else 0.5,
            "source_id": km_item.get("id") or metadata.get("source_id"),
            "tier": tier,
            "importance": km_item.get("importance", confidence),
            "is_valid": float(confidence) >= 0.5 if confidence else True,
            "sources": metadata.get("sources", []),
            "reasoning": metadata.get("reasoning"),
        }

    def _apply_fusion_result(
        self,
        record: Any,
        fusion_result: Any,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Apply a fusion result to a continuum memory entry.

        Args:
            record: The ContinuumMemoryEntry to update.
            fusion_result: The fused validation result with fused_confidence.
            metadata: Optional additional metadata.

        Returns:
            True if the record was updated.
        """
        try:
            # Get fused confidence from result
            fused_confidence = getattr(fusion_result, "fused_confidence", None)
            if fused_confidence is None:
                return False

            # Update the record's importance based on fused confidence
            record_id = record.id if hasattr(record, "id") else str(record)

            # Update metadata with fusion information
            record_metadata = record.metadata.copy() if hasattr(record, "metadata") else {}
            record_metadata["km_fused"] = True
            record_metadata["km_fused_confidence"] = fused_confidence
            if metadata:
                record_metadata["fusion_metadata"] = metadata

            # Update the entry in continuum memory
            self._continuum.update(
                record_id,
                importance=fused_confidence,
                metadata=record_metadata,
            )

            logger.debug(
                f"Applied fusion result to continuum entry {record_id}: "
                f"fused_confidence={fused_confidence:.3f}"
            )
            return True
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to apply fusion result: %s", e)
            return False

    def __init__(
        self,
        continuum: ContinuumMemory,
        enable_dual_write: bool = False,
        event_callback: EventCallback | None = None,
        enable_resilience: bool = True,
    ):
        """
        Initialize the adapter.

        Args:
            continuum: The ContinuumMemory instance to wrap
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

        self._continuum = continuum

    # set_event_callback inherited from KnowledgeMoundAdapter

    # SemanticSearchMixin required methods
    def _get_record_by_id(self, record_id: str) -> Any | None:
        """Get a memory entry by ID (required by SemanticSearchMixin)."""
        if record_id.startswith("cm_"):
            record_id = record_id[3:]
        return self._continuum.get(record_id)

    def _record_to_dict(self, record: Any, similarity: float = 0.0) -> dict[str, Any]:
        """Convert a memory entry to dict (required by SemanticSearchMixin)."""
        return {
            "id": record.id,
            "content": record.content,
            "tier": record.tier.value if hasattr(record.tier, "value") else record.tier,
            "importance": record.importance,
            "similarity": similarity,
            "domain": getattr(record, "domain", None),
            "created_at": (
                record.created_at.isoformat()
                if hasattr(record.created_at, "isoformat")
                else str(record.created_at)
            ),
            "updated_at": (
                record.updated_at.isoformat()
                if hasattr(record.updated_at, "isoformat")
                else str(record.updated_at)
            ),
            "metadata": record.metadata,
        }

    def _extract_record_id(self, source_id: str) -> str:
        """Extract record ID from prefixed source ID."""
        if source_id.startswith("cm_"):
            return source_id[3:]
        return source_id

    # _emit_event, _record_metric inherited from KnowledgeMoundAdapter

    @property
    def continuum(self) -> ContinuumMemory:
        """Access the underlying ContinuumMemory."""
        return self._continuum

    def search_by_keyword(
        self,
        query: str,
        limit: int = 10,
        tiers: list[str] | None = None,
        min_importance: float = 0.0,
    ) -> list[ContinuumMemoryEntry]:
        """
        Search continuum memory by keyword query.

        This method wraps ContinuumMemory.retrieve() to provide the interface
        expected by KnowledgeMound._query_continuum().

        Args:
            query: Search query (keywords are OR'd)
            limit: Maximum results to return
            tiers: Optional list of tier names to filter (e.g., ["fast", "medium"])
            min_importance: Minimum importance threshold

        Returns:
            List of ContinuumMemoryEntry objects matching the query
        """
        from aragora.memory.tier_manager import MemoryTier

        # Convert tier names to MemoryTier enums
        tier_enums = None
        if tiers:
            tier_enums = []
            for tier_name in tiers:
                try:
                    tier_enums.append(MemoryTier(tier_name))
                except ValueError:
                    logger.warning("Unknown tier: %s, skipping", tier_name)

        # Use ContinuumMemory's retrieve method
        entries = self._continuum.retrieve(
            query=query,
            tiers=tier_enums,
            limit=limit,
            min_importance=min_importance,
        )

        return list(entries)

    def get(self, entry_id: str) -> ContinuumMemoryEntry | None:
        """
        Get a specific entry by ID.

        Args:
            entry_id: The entry ID (may be prefixed with "cm_" from mound)

        Returns:
            ContinuumMemoryEntry or None
        """
        # Strip mound prefix if present
        if entry_id.startswith("cm_"):
            entry_id = entry_id[3:]

        return self._continuum.get(entry_id)

    async def get_async(self, entry_id: str) -> ContinuumMemoryEntry | None:
        """Async version of get for compatibility."""
        # Strip mound prefix if present
        if entry_id.startswith("cm_"):
            entry_id = entry_id[3:]

        return await self._continuum.get_async(entry_id)

    def to_knowledge_item(self, entry: ContinuumMemoryEntry) -> KnowledgeItem:
        """
        Convert a ContinuumMemoryEntry to a KnowledgeItem.

        Args:
            entry: The continuum memory entry

        Returns:
            KnowledgeItem for unified knowledge mound API
        """
        from aragora.knowledge.mound.types import (
            ConfidenceLevel,
            KnowledgeItem,
            KnowledgeSource,
        )

        # Map tier to confidence level
        tier_to_confidence = {
            "fast": ConfidenceLevel.LOW,  # Fast tier is volatile
            "medium": ConfidenceLevel.MEDIUM,
            "slow": ConfidenceLevel.HIGH,
            "glacial": ConfidenceLevel.VERIFIED,  # Glacial is most stable
        }
        confidence = tier_to_confidence.get(entry.tier.value, ConfidenceLevel.MEDIUM)

        # Build metadata
        metadata: dict[str, Any] = {
            "tier": entry.tier.value,
            "surprise_score": entry.surprise_score,
            "consolidation_score": entry.consolidation_score,
            "update_count": entry.update_count,
            "success_rate": entry.success_rate,
        }
        if entry.red_line:
            metadata["red_line"] = True
            metadata["red_line_reason"] = entry.red_line_reason
        if entry.tags:
            metadata["tags"] = entry.tags
        if entry.cross_references:
            metadata["cross_references"] = entry.cross_references

        return KnowledgeItem(
            id=entry.knowledge_mound_id,  # Uses "cm_" prefix
            content=entry.content,
            source=KnowledgeSource.CONTINUUM,
            source_id=entry.id,
            confidence=confidence,
            created_at=datetime.fromisoformat(entry.created_at),
            updated_at=datetime.fromisoformat(entry.updated_at),
            metadata=metadata,
            importance=entry.importance,
        )

    def from_ingestion_request(
        self,
        request: IngestionRequest,
        entry_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Convert an IngestionRequest to ContinuumMemory add() parameters.

        Args:
            request: The ingestion request from Knowledge Mound
            entry_id: Optional ID to use (generates one if not provided)

        Returns:
            Dict of parameters for ContinuumMemory.add()
        """
        import uuid
        from aragora.memory.tier_manager import MemoryTier

        # Map KnowledgeMound tier to ContinuumMemory tier
        tier_mapping: dict[str, MemoryTier] = {
            "fast": MemoryTier.FAST,
            "medium": MemoryTier.MEDIUM,
            "slow": MemoryTier.SLOW,
            "glacial": MemoryTier.GLACIAL,
        }
        tier = tier_mapping.get(request.tier, MemoryTier.SLOW)

        return {
            "id": entry_id or f"mound_{uuid.uuid4().hex[:12]}",
            "content": request.content,
            "tier": tier,
            "importance": request.confidence,
            "metadata": {
                "source_type": request.source_type.value,
                "debate_id": request.debate_id,
                "document_id": request.document_id,
                "agent_id": request.agent_id,
                "user_id": request.user_id,
                "owner_id": request.user_id,
                "workspace_id": request.workspace_id,
                "tenant_id": (
                    request.metadata.get("tenant_id")
                    if isinstance(request.metadata, dict)
                    else None
                ),
                "org_id": (
                    request.metadata.get("org_id") if isinstance(request.metadata, dict) else None
                ),
                "topics": request.topics,
                "mound_metadata": request.metadata,
            },
        }

    def store(
        self,
        content: str,
        importance: float = 0.5,
        tier: str = "slow",
        entry_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Store content in continuum memory.

        Args:
            content: The content to store
            importance: Importance score (0-1)
            tier: Tier name ("fast", "medium", "slow", "glacial")
            entry_id: Optional ID (generated if not provided)
            metadata: Optional metadata dict

        Returns:
            The entry ID
        """
        import uuid
        from aragora.memory.tier_manager import MemoryTier

        if entry_id is None:
            entry_id = f"mound_{uuid.uuid4().hex[:12]}"

        tier_enum = MemoryTier(tier)

        self._continuum.add(
            id=entry_id,
            content=content,
            tier=tier_enum,
            importance=importance,
            metadata=metadata or {},
        )

        return entry_id

    def link_to_mound(
        self,
        entry_id: str,
        mound_node_id: str,
    ) -> None:
        """
        Link a continuum entry to a knowledge mound node.

        Creates a cross-reference from the continuum entry to the mound node,
        enabling bidirectional navigation.

        Args:
            entry_id: The continuum entry ID
            mound_node_id: The knowledge mound node ID
        """
        entry = self._continuum.get(entry_id)
        if entry:
            entry.add_cross_reference(mound_node_id)
            # Save the updated entry
            self._continuum.update(
                entry_id,
                metadata=entry.metadata,
            )

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the continuum memory."""
        return self._continuum.get_stats()

    def get_tier_metrics(self) -> dict[str, Any]:
        """Get per-tier metrics."""
        return self._continuum.get_tier_metrics()

    def search_similar(
        self,
        content: str,
        limit: int = 5,
        min_similarity: float = 0.7,
    ) -> list[dict[str, Any]]:
        """
        Find similar memory entries for deduplication.

        Args:
            content: Content to find similar entries for
            limit: Maximum results
            min_similarity: Minimum similarity threshold (currently uses keyword match)

        Returns:
            List of similar memory entries as dicts
        """
        import time

        start = time.time()
        success = False

        try:
            # Extract key terms for search (first 10 words)
            words = content.split()[:10]
            query = " ".join(words)

            entries = self.search_by_keyword(query, limit=limit)

            # Convert to dict format for consistency with other adapters
            results = [
                {
                    "id": e.id,
                    "content": e.content,
                    "tier": e.tier.value,
                    "importance": e.importance,
                    "surprise_score": e.surprise_score,
                    "consolidation_score": e.consolidation_score,
                    "update_count": e.update_count,
                    "success_rate": e.success_rate,
                    "created_at": e.created_at,
                    "updated_at": e.updated_at,
                    "metadata": e.metadata,
                }
                for e in entries
            ]

            # Emit dashboard event for reverse flow query
            self._emit_event(
                "km_adapter_reverse_query",
                {
                    "source": "continuum",
                    "query_preview": query[:50] + "..." if len(query) > 50 else query,
                    "results_count": len(results),
                    "limit": limit,
                },
            )

            success = True
            return results
        finally:
            self._record_metric("search", success, time.time() - start)

    def store_memory(self, entry: ContinuumMemoryEntry) -> None:
        """
        Store a memory entry in the Knowledge Mound (forward flow).

        This is called by ContinuumMemory when a high-importance memory
        is added and should be synced to KM for cross-session persistence.

        Args:
            entry: The ContinuumMemoryEntry to store in KM
        """
        # This method is a hook for KM sync. The actual KM storage happens
        # when sync_memory_to_mound is called with a mound instance.
        # For now, we just log the intent - actual sync requires mound reference.
        logger.debug(
            f"Memory marked for KM sync: {entry.id} "
            f"(tier={entry.tier.value}, importance={entry.importance:.2f})"
        )
        # Mark the entry as pending KM sync in metadata
        if not entry.metadata.get("km_sync_pending"):
            entry.metadata["km_sync_pending"] = True
            entry.metadata["km_sync_requested_at"] = datetime.now().isoformat()
            # Update the entry in the store
            self._continuum.update(
                entry.id,
                metadata=entry.metadata,
            )

        # Emit dashboard event for forward sync
        self._emit_event(
            "km_adapter_forward_sync",
            {
                "source": "continuum",
                "memory_id": entry.id,
                "tier": entry.tier.value,
                "importance": entry.importance,
                "content_preview": (
                    entry.content[:100] + "..." if len(entry.content) > 100 else entry.content
                ),
            },
        )

    # =========================================================================
    # Reverse Flow Methods (KM → ContinuumMemory)
    # =========================================================================

    async def update_continuum_from_km(
        self,
        memory_id: str,
        km_validation: KMValidationResult,
    ) -> bool:
        """
        Update continuum memory entry based on KM validation feedback.

        This is the reverse flow: KM validation improves continuum memory placement.

        If KM determines an item has high cross-debate utility:
        - Promote to higher tier (FAST→MEDIUM→SLOW→GLACIAL)
        - Increase importance score
        - Mark as KM-validated

        If KM determines an item is low-value or contradicted:
        - Demote to lower tier
        - Decrease importance
        - Mark for review

        Args:
            memory_id: The continuum memory entry ID
            km_validation: Validation data from Knowledge Mound

        Returns:
            True if the entry was updated, False if not found or skipped
        """
        from aragora.memory.tier_manager import MemoryTier

        # Strip mound prefix if present
        if memory_id.startswith("cm_"):
            memory_id = memory_id[3:]

        # Get current entry
        entry = self._continuum.get(memory_id)
        if not entry:
            logger.warning("Continuum entry not found for KM validation: %s", memory_id)
            return False

        # Calculate new importance based on KM feedback
        current_importance = entry.importance
        km_confidence = km_validation.km_confidence
        validation_count = km_validation.validation_count
        cross_debate_utility = km_validation.cross_debate_utility

        # Weighted average: more validations = more weight on KM confidence
        # Also factor in cross-debate utility
        weight = min(0.5, validation_count * 0.1)  # Max 50% weight
        utility_boost = cross_debate_utility * 0.1  # Up to 10% boost

        new_importance = current_importance * (1 - weight) + km_confidence * weight + utility_boost
        new_importance = min(1.0, max(0.0, new_importance))  # Clamp to [0, 1]

        # Determine if tier change is needed based on recommendation
        recommendation = km_validation.recommendation
        tier_changed = False

        if recommendation == "promote" and entry.tier != MemoryTier.GLACIAL:
            # Promote to a more permanent tier
            tier_order = [MemoryTier.FAST, MemoryTier.MEDIUM, MemoryTier.SLOW, MemoryTier.GLACIAL]
            current_idx = tier_order.index(entry.tier)
            if current_idx < len(tier_order) - 1:
                new_tier = tier_order[current_idx + 1]
                tier_changed = self._continuum.promote_entry(memory_id, new_tier)
                if tier_changed:
                    logger.info(
                        "Promoted continuum entry from KM validation: %s %s -> %s",
                        memory_id,
                        entry.tier.value,
                        new_tier.value,
                    )

        elif recommendation == "demote" and entry.tier != MemoryTier.FAST:
            # Demote to a less permanent tier
            tier_order = [MemoryTier.FAST, MemoryTier.MEDIUM, MemoryTier.SLOW, MemoryTier.GLACIAL]
            current_idx = tier_order.index(entry.tier)
            if current_idx > 0:
                new_tier = tier_order[current_idx - 1]
                tier_changed = self._continuum.demote_entry(memory_id, new_tier)
                if tier_changed:
                    logger.info(
                        "Demoted continuum entry from KM validation: %s %s -> %s",
                        memory_id,
                        entry.tier.value,
                        new_tier.value,
                    )

        # Check if importance changed significantly
        importance_changed = abs(new_importance - current_importance) > 0.01

        # Always update metadata to mark as KM-validated
        # Even if importance/tier don't change, we want to track validation
        metadata = entry.metadata.copy()
        metadata["km_validated"] = True
        metadata["km_validation_count"] = validation_count
        metadata["km_confidence"] = km_confidence
        metadata["km_cross_debate_utility"] = cross_debate_utility
        if km_validation.was_contradicted:
            metadata["km_contradicted"] = True
        if km_validation.was_supported:
            metadata["km_supported"] = True

        # Update the entry via direct method
        self._continuum.update(
            memory_id,
            importance=new_importance if importance_changed else None,
            metadata=metadata,
        )

        if importance_changed:
            logger.info(
                f"Updated continuum entry from KM: {memory_id} "
                f"importance {current_importance:.2f} -> {new_importance:.2f}"
            )
        else:
            logger.debug(
                f"Updated continuum metadata from KM: {memory_id} "
                f"(importance unchanged at {current_importance:.2f})"
            )

        # Return True if any meaningful update was made
        return True

    async def sync_validations_to_continuum(
        self,
        workspace_id: str,
        validations: list[KMValidationResult],
        min_confidence: float = 0.7,
    ) -> ValidationSyncResult:
        """
        Batch sync KM validations back to ContinuumMemory.

        Processes a list of KM validations and updates the corresponding
        continuum memory entries. High-confidence validations can trigger
        tier promotions; low-confidence or contradicted items can trigger demotions.

        Args:
            workspace_id: Workspace ID for filtering
            validations: List of KM validation results
            min_confidence: Minimum confidence to apply changes (default 0.7)

        Returns:
            ValidationSyncResult with counts of promotions, demotions, and updates
        """
        import time

        start_time = time.time()
        result = ValidationSyncResult()
        result.total_processed = len(validations)

        for validation in validations:
            try:
                # Skip low-confidence validations
                if validation.km_confidence < min_confidence:
                    result.skipped += 1
                    continue

                # Apply validation
                updated = await self.update_continuum_from_km(
                    validation.memory_id,
                    validation,
                )

                if updated:
                    if validation.recommendation == "promote":
                        result.promoted += 1
                    elif validation.recommendation == "demote":
                        result.demoted += 1
                    else:
                        result.updated += 1
                else:
                    result.skipped += 1

            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                error_msg = f"Error validating {validation.memory_id}: {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)

        result.duration_ms = int((time.time() - start_time) * 1000)

        logger.info(
            "KM validation sync complete: promoted=%s, demoted=%s, updated=%s, skipped=%s, errors=%s, duration=%sms",
            result.promoted,
            result.demoted,
            result.updated,
            result.skipped,
            len(result.errors),
            result.duration_ms,
        )

        return result

    async def get_km_validated_entries(
        self,
        limit: int = 50,
        min_km_confidence: float = 0.7,
    ) -> list[ContinuumMemoryEntry]:
        """
        Get continuum entries that have been validated by KM.

        Useful for:
        - Finding high-quality memories for context injection
        - Auditing which memories have KM validation
        - Building training data from validated examples

        Args:
            limit: Maximum entries to return
            min_km_confidence: Minimum KM confidence score

        Returns:
            List of validated continuum memory entries
        """
        # Retrieve all entries and filter by KM validation
        all_entries = self._continuum.retrieve(limit=limit * 2)

        validated = []
        for entry in all_entries:
            km_validated = entry.metadata.get("km_validated", False)
            km_confidence = entry.metadata.get("km_confidence", 0.0)

            if km_validated and km_confidence >= min_km_confidence:
                validated.append(entry)

            if len(validated) >= limit:
                break

        return validated

    async def sync_memory_to_mound(
        self,
        mound: Any,
        workspace_id: str,
        min_importance: float = 0.7,
        limit: int = 100,
        tiers: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Sync high-importance continuum memories to the Knowledge Mound.

        This is the forward flow: significant memories are stored in KM for
        long-term persistence, semantic search, and cross-debate retrieval.

        Args:
            mound: KnowledgeMound instance to sync to
            workspace_id: Workspace ID for the KM entries
            min_importance: Minimum importance threshold (default 0.7)
            limit: Maximum entries to sync
            tiers: Optional list of tier names to filter

        Returns:
            Dict with sync statistics (synced, skipped, errors)
        """
        from aragora.knowledge.mound.types import (
            IngestionRequest,
            SourceType,
        )

        result: dict[str, Any] = {
            "synced": 0,
            "skipped": 0,
            "already_synced": 0,
            "errors": [],
        }

        # Get high-importance memories
        entries = self.search_by_keyword(
            query="",  # Empty query returns all
            limit=limit,
            tiers=tiers,
            min_importance=min_importance,
        )

        for entry in entries:
            try:
                # Check if already synced to KM
                if entry.metadata.get("km_synced"):
                    result["already_synced"] += 1
                    continue

                # Skip if below importance threshold
                if entry.importance < min_importance:
                    result["skipped"] += 1
                    continue

                # Create ingestion request
                request = IngestionRequest(
                    content=entry.content,
                    source_type=SourceType.CONTINUUM,
                    workspace_id=workspace_id,
                    confidence=entry.importance,
                    tier=entry.tier.value,
                    metadata={
                        "continuum_id": entry.id,
                        "continuum_tier": entry.tier.value,
                        "surprise_score": entry.surprise_score,
                        "consolidation_score": entry.consolidation_score,
                        "tags": entry.tags,
                    },
                )

                # Ingest into KM
                km_id = await mound.ingest(request)

                # Mark entry as synced in continuum
                entry_metadata = entry.metadata.copy()
                entry_metadata["km_synced"] = True
                entry_metadata["km_node_id"] = km_id
                self._continuum.update(entry.id, metadata=entry_metadata)

                # Create bidirectional link
                self.link_to_mound(entry.id, km_id)

                result["synced"] += 1
                logger.debug("Synced continuum entry to KM: %s -> %s", entry.id, km_id)

            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                error_msg = f"Error syncing {entry.id}: {e}"
                logger.warning(error_msg)
                result["errors"].append(error_msg)

        logger.info(
            "Memory to KM sync complete: synced=%s, skipped=%s, already_synced=%s, errors=%s",
            result["synced"],
            result["skipped"],
            result["already_synced"],
            len(result["errors"]),
        )

        return result

    def get_reverse_sync_stats(self) -> dict[str, Any]:
        """
        Get statistics about reverse sync (KM → ContinuumMemory).

        Returns counts of KM-validated entries by tier and validation status.
        """
        stats: dict[str, Any] = {
            "total_km_validated": 0,
            "km_validated_by_tier": {},
            "km_supported": 0,
            "km_contradicted": 0,
            "avg_km_confidence": 0.0,
            "avg_cross_debate_utility": 0.0,
        }

        # Sample entries to compute stats
        all_entries = self._continuum.retrieve(limit=1000)

        confidence_sum = 0.0
        utility_sum = 0.0
        validated_count = 0

        for entry in all_entries:
            if entry.metadata.get("km_validated"):
                validated_count += 1
                stats["total_km_validated"] += 1

                tier = entry.tier.value
                stats["km_validated_by_tier"][tier] = stats["km_validated_by_tier"].get(tier, 0) + 1

                if entry.metadata.get("km_supported"):
                    stats["km_supported"] += 1
                if entry.metadata.get("km_contradicted"):
                    stats["km_contradicted"] += 1

                confidence_sum += entry.metadata.get("km_confidence", 0.0)
                utility_sum += entry.metadata.get("km_cross_debate_utility", 0.0)

        if validated_count > 0:
            stats["avg_km_confidence"] = round(confidence_sum / validated_count, 3)
            stats["avg_cross_debate_utility"] = round(utility_sum / validated_count, 3)

        return stats
