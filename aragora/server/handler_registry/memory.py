"""
Memory and knowledge handler imports and registry entries.

This module contains imports and registry entries for:
- Memory handlers (MemoryHandler, CheckpointHandler, etc.)
- Knowledge handlers (KnowledgeHandler, KnowledgeMoundHandler, etc.)
- Belief and evidence handlers
- Document handlers
- Learning and insights handlers
"""

from __future__ import annotations

from .core import _safe_import

# =============================================================================
# Memory Handler Imports
# =============================================================================

# Core memory handlers
MemoryHandler = _safe_import("aragora.server.handlers", "MemoryHandler")
CheckpointHandler = _safe_import("aragora.server.handlers", "CheckpointHandler")

# Memory coordinator
CoordinatorHandler = _safe_import(
    "aragora.server.handlers.memory.coordinator", "CoordinatorHandler"
)

# KM checkpoint handler
KMCheckpointHandler = _safe_import(
    "aragora.server.handlers.knowledge.checkpoints", "KMCheckpointHandler"
)

# KM adapter status handler
KMAdapterStatusHandler = _safe_import(
    "aragora.server.handlers.knowledge.adapters", "KMAdapterStatusHandler"
)

# KM velocity handler
KnowledgeVelocityHandler = _safe_import(
    "aragora.server.handlers.knowledge.velocity", "KnowledgeVelocityHandler"
)

# KM gap detection handler
KnowledgeGapHandler = _safe_import("aragora.server.handlers.knowledge.gaps", "KnowledgeGapHandler")

# =============================================================================
# Knowledge Handler Imports
# =============================================================================

# Core knowledge handlers
KnowledgeHandler = _safe_import("aragora.server.handlers", "KnowledgeHandler")
KnowledgeMoundHandler = _safe_import("aragora.server.handlers", "KnowledgeMoundHandler")
KnowledgeChatHandler = _safe_import("aragora.server.handlers", "KnowledgeChatHandler")

# Belief and evidence handlers
BeliefHandler = _safe_import("aragora.server.handlers", "BeliefHandler")
EvidenceHandler = _safe_import("aragora.server.handlers", "EvidenceHandler")

# Learning handler
LearningHandler = _safe_import("aragora.server.handlers", "LearningHandler")

# Autonomous learning handler
AutonomousLearningHandler = _safe_import(
    "aragora.server.handlers.autonomous_learning", "AutonomousLearningHandler"
)

# Evidence enrichment
EvidenceEnrichmentHandler = _safe_import(
    "aragora.server.handlers.features.evidence_enrichment", "EvidenceEnrichmentHandler"
)

# =============================================================================
# Document Handler Imports
# =============================================================================

DocumentHandler = _safe_import("aragora.server.handlers", "DocumentHandler")
DocumentBatchHandler = _safe_import("aragora.server.handlers", "DocumentBatchHandler")
FolderUploadHandler = _safe_import("aragora.server.handlers", "FolderUploadHandler")
DocumentQueryHandler = _safe_import(
    "aragora.server.handlers.features.document_query", "DocumentQueryHandler"
)

# =============================================================================
# Insights Handler Imports
# =============================================================================

InsightsHandler = _safe_import("aragora.server.handlers", "InsightsHandler")
MomentsHandler = _safe_import("aragora.server.handlers", "MomentsHandler")

# =============================================================================
# Cross-pollination handlers (Knowledge Mound federation)
# =============================================================================

CrossPollinationBridgeHandler = _safe_import(
    "aragora.server.handlers.evolution.cross_pollination", "CrossPollinationBridgeHandler"
)
CrossPollinationStatsHandler = _safe_import(
    "aragora.server.handlers.evolution.cross_pollination", "CrossPollinationStatsHandler"
)
CrossPollinationSubscribersHandler = _safe_import(
    "aragora.server.handlers.evolution.cross_pollination", "CrossPollinationSubscribersHandler"
)
CrossPollinationMetricsHandler = _safe_import(
    "aragora.server.handlers.evolution.cross_pollination", "CrossPollinationMetricsHandler"
)
CrossPollinationResetHandler = _safe_import(
    "aragora.server.handlers.evolution.cross_pollination", "CrossPollinationResetHandler"
)
CrossPollinationKMHandler = _safe_import(
    "aragora.server.handlers.evolution.cross_pollination", "CrossPollinationKMHandler"
)
CrossPollinationKMSyncHandler = _safe_import(
    "aragora.server.handlers.evolution.cross_pollination", "CrossPollinationKMSyncHandler"
)
CrossPollinationKMStalenessHandler = _safe_import(
    "aragora.server.handlers.evolution.cross_pollination", "CrossPollinationKMStalenessHandler"
)
CrossPollinationKMCultureHandler = _safe_import(
    "aragora.server.handlers.evolution.cross_pollination", "CrossPollinationKMCultureHandler"
)

# =============================================================================
# Unified memory handler
# =============================================================================

UnifiedMemoryHandler = _safe_import(
    "aragora.server.handlers.memory.unified_handler", "UnifiedMemoryHandler"
)

# Memory unified gateway handler (fan-out, retention, dedup)
MemoryUnifiedGatewayHandler = _safe_import(
    "aragora.server.handlers.memory.memory_unified", "MemoryUnifiedHandler"
)

# =============================================================================
# Knowledge sharing handlers
# =============================================================================

SharingHandler = _safe_import("aragora.server.handlers.social.sharing", "SharingHandler")
SharingNotificationsHandler = _safe_import(
    "aragora.server.handlers.knowledge.sharing_notifications", "SharingNotificationsHandler"
)

# Context budget handler
ContextBudgetHandler = _safe_import(
    "aragora.server.handlers.debates.context_budget", "ContextBudgetHandler"
)

# =============================================================================
# Memory/Knowledge Handler Registry Entries
# =============================================================================

MEMORY_HANDLER_REGISTRY: list[tuple[str, object]] = [
    ("_memory_handler", MemoryHandler),
    ("_checkpoint_handler", CheckpointHandler),
    ("_coordinator_handler", CoordinatorHandler),
    ("_km_checkpoint_handler", KMCheckpointHandler),
    ("_km_adapter_status_handler", KMAdapterStatusHandler),
    ("_km_velocity_handler", KnowledgeVelocityHandler),
    ("_km_gap_handler", KnowledgeGapHandler),
    ("_knowledge_handler", KnowledgeHandler),
    ("_knowledge_mound_handler", KnowledgeMoundHandler),
    ("_knowledge_chat_handler", KnowledgeChatHandler),
    ("_belief_handler", BeliefHandler),
    ("_evidence_handler", EvidenceHandler),
    ("_learning_handler", LearningHandler),
    ("_evidence_enrichment_handler", EvidenceEnrichmentHandler),
    ("_document_handler", DocumentHandler),
    ("_document_batch_handler", DocumentBatchHandler),
    ("_folder_upload_handler", FolderUploadHandler),
    ("_document_query_handler", DocumentQueryHandler),
    ("_insights_handler", InsightsHandler),
    ("_moments_handler", MomentsHandler),
    # Cross-pollination handlers
    ("_cross_pollination_bridge_handler", CrossPollinationBridgeHandler),
    ("_cross_pollination_stats_handler", CrossPollinationStatsHandler),
    ("_cross_pollination_subscribers_handler", CrossPollinationSubscribersHandler),
    ("_cross_pollination_metrics_handler", CrossPollinationMetricsHandler),
    ("_cross_pollination_reset_handler", CrossPollinationResetHandler),
    ("_cross_pollination_km_handler", CrossPollinationKMHandler),
    ("_cross_pollination_km_sync_handler", CrossPollinationKMSyncHandler),
    ("_cross_pollination_km_staleness_handler", CrossPollinationKMStalenessHandler),
    ("_cross_pollination_km_culture_handler", CrossPollinationKMCultureHandler),
    # Knowledge sharing
    ("_sharing_handler", SharingHandler),
    ("_sharing_notifications_handler", SharingNotificationsHandler),
    # Autonomous learning
    ("_autonomous_learning_handler", AutonomousLearningHandler),
    # Unified memory
    ("_unified_memory_handler", UnifiedMemoryHandler),
    # Memory unified gateway (fan-out, retention, dedup)
    ("_memory_unified_handler", MemoryUnifiedGatewayHandler),
    # Context budget
    ("_context_budget_handler", ContextBudgetHandler),
]

__all__ = [
    # Memory handlers
    "MemoryHandler",
    "CheckpointHandler",
    "CoordinatorHandler",
    "KMCheckpointHandler",
    "KMAdapterStatusHandler",
    "KnowledgeVelocityHandler",
    "KnowledgeGapHandler",
    # Knowledge handlers
    "KnowledgeHandler",
    "KnowledgeMoundHandler",
    "KnowledgeChatHandler",
    "BeliefHandler",
    "EvidenceHandler",
    "LearningHandler",
    "EvidenceEnrichmentHandler",
    # Document handlers
    "DocumentHandler",
    "DocumentBatchHandler",
    "FolderUploadHandler",
    "DocumentQueryHandler",
    # Insights handlers
    "InsightsHandler",
    "MomentsHandler",
    # Cross-pollination handlers
    "CrossPollinationBridgeHandler",
    "CrossPollinationStatsHandler",
    "CrossPollinationSubscribersHandler",
    "CrossPollinationMetricsHandler",
    "CrossPollinationResetHandler",
    "CrossPollinationKMHandler",
    "CrossPollinationKMSyncHandler",
    "CrossPollinationKMStalenessHandler",
    "CrossPollinationKMCultureHandler",
    # Sharing handlers
    "SharingHandler",
    "SharingNotificationsHandler",
    # Autonomous learning
    "AutonomousLearningHandler",
    # Unified memory
    "UnifiedMemoryHandler",
    # Memory unified gateway
    "MemoryUnifiedGatewayHandler",
    # Registry
    "MEMORY_HANDLER_REGISTRY",
]
