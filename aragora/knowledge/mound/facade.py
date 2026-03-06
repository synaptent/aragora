"""
Knowledge Mound Facade - Unified knowledge storage with production backends.

This is the main entry point for the enhanced Knowledge Mound system,
providing a unified API over multiple storage backends (SQLite, PostgreSQL, Redis)
and integrating staleness detection and culture accumulation.

The facade is composed from modular mixins:
- core.py: Initialization, lifecycle, storage adapters
- api/crud.py: Create, read, update, delete operations
- api/query.py: Query and search operations
- api/rlm.py: RLM (Recursive Language Models) integration
- ops/staleness.py: Staleness detection and revalidation
- ops/culture.py: Culture accumulation and management
- ops/sync.py: Cross-system synchronization

Phase A2 Operations:
- ops/contradiction.py: Contradiction detection and resolution
- ops/confidence_decay.py: Dynamic confidence adjustment over time
- ops/governance.py: RBAC and audit trail logging
- ops/analytics.py: Coverage, usage, and quality analytics
- ops/extraction.py: Knowledge extraction from debates

Usage:
    from aragora.knowledge.mound import KnowledgeMound, MoundConfig

    config = MoundConfig(
        backend=MoundBackend.POSTGRES,
        postgres_url="postgresql://user:pass@localhost/aragora",
        redis_url="redis://localhost:6379",
    )

    mound = KnowledgeMound(config, workspace_id="enterprise_team")
    await mound.initialize()

    # Store knowledge with provenance
    result = await mound.store(IngestionRequest(
        content="All contracts must have 90-day notice periods",
        source_type=KnowledgeSource.DEBATE,
        debate_id="debate_123",
        confidence=0.95,
        workspace_id="enterprise_team",
    ))

    # Query semantically
    results = await mound.query("contract notice requirements", limit=10)

    # Check staleness
    stale = await mound.get_stale_knowledge(threshold=0.7)

    # Get culture profile
    culture = await mound.get_culture_profile()
"""

from __future__ import annotations

from aragora.knowledge.mound.core import KnowledgeMoundCore
from aragora.knowledge.mound.api.crud import CRUDOperationsMixin
from aragora.knowledge.mound.api.query import QueryOperationsMixin
from aragora.knowledge.mound.api.rlm import RLMOperationsMixin
from aragora.knowledge.mound.ops.staleness import StalenessOperationsMixin
from aragora.knowledge.mound.ops.culture import CultureOperationsMixin
from aragora.knowledge.mound.ops.sync import SyncOperationsMixin
from aragora.knowledge.mound.ops.global_knowledge import GlobalKnowledgeMixin
from aragora.knowledge.mound.ops.sharing import KnowledgeSharingMixin
from aragora.knowledge.mound.ops.federation import KnowledgeFederationMixin
from aragora.knowledge.mound.ops.dedup import DedupOperationsMixin
from aragora.knowledge.mound.ops.pruning import PruningOperationsMixin
from aragora.knowledge.mound.ops.auto_curation import AutoCurationMixin

# Phase A2 Operations
from aragora.knowledge.mound.ops.contradiction import ContradictionOperationsMixin
from aragora.knowledge.mound.ops.confidence_decay import ConfidenceDecayMixin
from aragora.knowledge.mound.ops.governance import GovernanceMixin
from aragora.knowledge.mound.ops.analytics import AnalyticsMixin
from aragora.knowledge.mound.ops.extraction import ExtractionMixin
from aragora.knowledge.mound.types import MoundConfig

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.types.protocols import EventEmitterProtocol


# Multiple inheritance with 17 mixins causes mypy to report complex MRO issues.
# The class is correctly composed and functions at runtime.
class KnowledgeMound(  # type: ignore[misc]
    CRUDOperationsMixin,
    QueryOperationsMixin,
    RLMOperationsMixin,
    StalenessOperationsMixin,
    CultureOperationsMixin,
    SyncOperationsMixin,
    GlobalKnowledgeMixin,
    KnowledgeSharingMixin,
    KnowledgeFederationMixin,
    DedupOperationsMixin,
    PruningOperationsMixin,
    AutoCurationMixin,
    # Phase A2 Mixins
    ContradictionOperationsMixin,
    ConfidenceDecayMixin,
    GovernanceMixin,
    AnalyticsMixin,
    ExtractionMixin,
    KnowledgeMoundCore,
):
    """Unified knowledge facade for the Aragora multi-agent control plane."""

    def __init__(
        self,
        config: MoundConfig | None = None,
        workspace_id: str | None = None,
        event_emitter: EventEmitterProtocol | None = None,
    ) -> None:
        """Initialize the Knowledge Mound.

        Explicit __init__ required because Protocol classes in the MRO
        (from DedupOperationsMixin and AutoCurationMixin) can interfere
        with __init__ resolution.

        Args:
            config: Mound configuration. Defaults to SQLite backend.
            workspace_id: Default workspace for queries.
            event_emitter: Optional event emitter for cross-subsystem events.
        """
        # Directly call KnowledgeMoundCore.__init__ because Protocol classes
        # in the MRO intercept super().__init__() before it reaches the core
        KnowledgeMoundCore.__init__(
            self, config=config, workspace_id=workspace_id, event_emitter=event_emitter
        )

    # Explicit override to resolve MRO conflict between
    # ConfidenceDecayMixin.apply_confidence_decay(workspace_id, force) -> DecayReport
    # and PruningOperationsMixin.apply_confidence_decay(workspace_id, decay_rate, min_confidence) -> int
    async def apply_confidence_decay(self, *args: Any, **kwargs: Any) -> Any:
        """Apply confidence decay - delegates to ConfidenceDecayMixin."""
        return await ConfidenceDecayMixin.apply_confidence_decay(self, *args, **kwargs)

    async def ingest(self, item: Any) -> Any:
        """Ingest a knowledge item (alias for store).

        If ``enable_data_classification`` is set on the MoundConfig and the
        item carries no ``_classification`` metadata, the item is automatically
        tagged with a classification level before storage.

        Args:
            item: Knowledge item or IngestionRequest to store

        Returns:
            IngestionResult with stored item details
        """
        if getattr(self.config, "enable_data_classification", False):
            try:
                item_dict: dict[str, Any] | None = None
                if isinstance(item, dict):
                    item_dict = item
                elif hasattr(item, "metadata") and isinstance(item.metadata, dict):
                    item_dict = item.metadata

                if item_dict is not None and "_classification" not in item_dict:
                    from aragora.compliance.data_classification import PolicyEnforcer

                    enforcer = PolicyEnforcer()
                    classified = enforcer.classify_knowledge_item(item_dict)
                    item_dict["_classification"] = classified.get("_classification", {})
            except (ImportError, RuntimeError, TypeError, ValueError) as e:
                import logging

                logging.getLogger(__name__).debug(
                    "[data_classification] Classification failed (non-critical): %s", e
                )
        return await self.store(item)

    """
    Unified knowledge facade for the Aragora multi-agent control plane.

    The Knowledge Mound implements the "termite mound" architecture where
    all agents contribute to and query from a shared knowledge superstructure.

    Features:
    - Unified API across SQLite (dev), PostgreSQL (prod), and Redis (cache)
    - Cross-system queries across ContinuumMemory, ConsensusMemory, FactStore
    - Provenance tracking for audit and compliance
    - Staleness detection with automatic revalidation scheduling
    - Culture accumulation for organizational learning
    - Multi-tenant workspace isolation
    - RLM integration for hierarchical context navigation

    This class composes functionality from modular mixins:
    - CRUDOperationsMixin: store, get, update, delete, add, add_node, get_node
    - QueryOperationsMixin: query, query_semantic, query_graph, export_graph_*, query_with_visibility
    - RLMOperationsMixin: query_with_rlm, is_rlm_available
    - StalenessOperationsMixin: get_stale_knowledge, mark_validated, schedule_revalidation
    - CultureOperationsMixin: get_culture_profile, observe_debate, recommend_agents, org culture
    - SyncOperationsMixin: sync_from_*, sync_all
    - GlobalKnowledgeMixin: store_verified_fact, query_global_knowledge, promote_to_global
    - KnowledgeSharingMixin: share_with_workspace, share_with_user, get_shared_with_me, revoke_share
    - KnowledgeFederationMixin: register_federated_region, sync_to_region, pull_from_region
    - DedupOperationsMixin: find_duplicates, merge_duplicates, get_dedup_report
    - PruningOperationsMixin: prune_workspace, get_prunable_items, set_pruning_policy
    - AutoCurationMixin: run_curation, set_curation_policy, calculate_quality_score

    Phase A2 Mixins:
    - ContradictionOperationsMixin: detect_contradictions, resolve_contradiction
    - ConfidenceDecayMixin: apply_confidence_decay, record_confidence_event
    - GovernanceMixin: create_role, assign_role, check_permission, log_audit
    - AnalyticsMixin: analyze_coverage, analyze_usage, capture_quality_snapshot
    - ExtractionMixin: extract_from_debate, promote_extracted_knowledge

    - KnowledgeMoundCore: initialize, close, session, get_stats, storage adapters
    """
