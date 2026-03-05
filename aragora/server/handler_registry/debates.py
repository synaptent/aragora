"""
Debate-related handler imports and registry entries.

This module contains imports and registry entries for:
- Core debate handlers (DebatesHandler, ConsensusHandler, etc.)
- Tournament and replay handlers
- Verification and auditing handlers
- Decision and critique handlers
"""

from __future__ import annotations

from .core import _safe_import

# =============================================================================
# Debate Handler Imports
# =============================================================================

# Core debate handlers
DebatesHandler = _safe_import("aragora.server.handlers", "DebatesHandler")
GraphDebatesHandler = _safe_import("aragora.server.handlers", "GraphDebatesHandler")
MatrixDebatesHandler = _safe_import("aragora.server.handlers", "MatrixDebatesHandler")
ConsensusHandler = _safe_import("aragora.server.handlers", "ConsensusHandler")
GenesisHandler = _safe_import("aragora.server.handlers", "GenesisHandler")
ReplaysHandler = _safe_import("aragora.server.handlers", "ReplaysHandler")
TournamentHandler = _safe_import("aragora.server.handlers", "TournamentHandler")
DeliberationsHandler = _safe_import("aragora.server.handlers", "DeliberationsHandler")
OrchestrationHandler = _safe_import("aragora.server.handlers", "OrchestrationHandler")

# Decision handlers
DecisionExplainHandler = _safe_import("aragora.server.handlers", "DecisionExplainHandler")
DecisionPipelineHandler = _safe_import("aragora.server.handlers", "DecisionPipelineHandler")
DecisionHandler = _safe_import("aragora.server.handlers", "DecisionHandler")
CritiqueHandler = _safe_import("aragora.server.handlers", "CritiqueHandler")
ExplainabilityHandler = _safe_import("aragora.server.handlers", "ExplainabilityHandler")
UncertaintyHandler = _safe_import("aragora.server.handlers", "UncertaintyHandler")

# Verification & auditing handlers
VerificationHandler = _safe_import("aragora.server.handlers", "VerificationHandler")
AuditingHandler = _safe_import("aragora.server.handlers", "AuditingHandler")
FormalVerificationHandler = _safe_import("aragora.server.handlers", "FormalVerificationHandler")
GauntletHandler = _safe_import("aragora.server.handlers", "GauntletHandler")

# Gauntlet v1 sub-handlers
GauntletSecureHandler = _safe_import("aragora.server.handlers.gauntlet_v1", "GauntletSecureHandler")
GauntletSchemaHandler = _safe_import("aragora.server.handlers.gauntlet_v1", "GauntletSchemaHandler")
GauntletTemplateHandler = _safe_import(
    "aragora.server.handlers.gauntlet_v1", "GauntletTemplateHandler"
)
GauntletValidateReceiptHandler = _safe_import(
    "aragora.server.handlers.gauntlet_v1", "GauntletValidateReceiptHandler"
)
GauntletAllSchemasHandler = _safe_import(
    "aragora.server.handlers.gauntlet_v1", "GauntletAllSchemasHandler"
)
GauntletTemplatesListHandler = _safe_import(
    "aragora.server.handlers.gauntlet_v1", "GauntletTemplatesListHandler"
)
GauntletReceiptExportHandler = _safe_import(
    "aragora.server.handlers.gauntlet_v1", "GauntletReceiptExportHandler"
)
GauntletHeatmapExportHandler = _safe_import(
    "aragora.server.handlers.gauntlet_v1", "GauntletHeatmapExportHandler"
)

# Review & evaluation handlers
ReviewsHandler = _safe_import("aragora.server.handlers", "ReviewsHandler")
EvaluationHandler = _safe_import("aragora.server.handlers", "EvaluationHandler")

# Receipts handler
ReceiptsHandler = _safe_import("aragora.server.handlers.receipts", "ReceiptsHandler")

# Hybrid debates
HybridDebateHandler = _safe_import(
    "aragora.server.handlers.hybrid_debate_handler", "HybridDebateHandler"
)

# Email debate handler
EmailDebateHandler = _safe_import("aragora.server.handlers.email_debate", "EmailDebateHandler")

# Security debate handler
SecurityDebateHandler = _safe_import(
    "aragora.server.handlers.security_debate", "SecurityDebateHandler"
)

# Template discovery handler
TemplateDiscoveryHandler = _safe_import(
    "aragora.server.handlers.template_discovery", "TemplateDiscoveryHandler"
)

# Composite, stats, share, interventions, settlement, spectate, receipt export
CompositeHandler = _safe_import("aragora.server.handlers.composite", "CompositeHandler")
DebateStatsHandler = _safe_import("aragora.server.handlers.debate_stats", "DebateStatsHandler")
DebateShareHandler = _safe_import("aragora.server.handlers.debates.share", "DebateShareHandler")
PublicDebateViewerHandler = _safe_import(
    "aragora.server.handlers.debates.public_viewer", "PublicDebateViewerHandler"
)
DebateInterventionsHandler = _safe_import(
    "aragora.server.handlers.debates.interventions", "DebateInterventionsHandler"
)
DecisionPackageHandler = _safe_import(
    "aragora.server.handlers.debates.decision_package", "DecisionPackageHandler"
)
SettlementHandler = _safe_import("aragora.server.handlers.settlements", "SettlementHandler")
SpectateStreamHandler = _safe_import("aragora.server.handlers.spectate_ws", "SpectateStreamHandler")
ReceiptExportHandler = _safe_import(
    "aragora.server.handlers.receipt_export", "ReceiptExportHandler"
)

# =============================================================================
# Debate Handler Registry Entries
# =============================================================================

DEBATE_HANDLER_REGISTRY: list[tuple[str, object]] = [
    ("_debates_handler", DebatesHandler),
    ("_consensus_handler", ConsensusHandler),
    ("_decision_explain_handler", DecisionExplainHandler),
    ("_decision_pipeline_handler", DecisionPipelineHandler),
    ("_decision_handler", DecisionHandler),
    ("_deliberations_handler", DeliberationsHandler),
    ("_critique_handler", CritiqueHandler),
    ("_genesis_handler", GenesisHandler),
    ("_replays_handler", ReplaysHandler),
    ("_tournament_handler", TournamentHandler),
    ("_verification_handler", VerificationHandler),
    ("_auditing_handler", AuditingHandler),
    ("_graph_debates_handler", GraphDebatesHandler),
    ("_matrix_debates_handler", MatrixDebatesHandler),
    ("_gauntlet_handler", GauntletHandler),
    ("_formal_verification_handler", FormalVerificationHandler),
    ("_reviews_handler", ReviewsHandler),
    ("_evaluation_handler", EvaluationHandler),
    ("_orchestration_handler", OrchestrationHandler),
    ("_uncertainty_handler", UncertaintyHandler),
    ("_explainability_handler", ExplainabilityHandler),
    ("_receipts_handler", ReceiptsHandler),
    ("_hybrid_debate_handler", HybridDebateHandler),
    ("_email_debate_handler", EmailDebateHandler),
    # Gauntlet v1 sub-handlers
    ("_gauntlet_schema_handler", GauntletSchemaHandler),
    ("_gauntlet_template_handler", GauntletTemplateHandler),
    ("_gauntlet_validate_receipt_handler", GauntletValidateReceiptHandler),
    ("_gauntlet_all_schemas_handler", GauntletAllSchemasHandler),
    ("_gauntlet_templates_list_handler", GauntletTemplatesListHandler),
    ("_gauntlet_receipt_export_handler", GauntletReceiptExportHandler),
    ("_gauntlet_heatmap_export_handler", GauntletHeatmapExportHandler),
    # NOTE: GauntletSecureHandler is an ABC -- only concrete subclasses above are registered
    # Security debate
    ("_security_debate_handler", SecurityDebateHandler),
    # Template discovery
    ("_template_discovery_handler", TemplateDiscoveryHandler),
    # Composite debate
    ("_composite_handler", CompositeHandler),
    # Debate stats, share, interventions
    ("_debate_stats_handler", DebateStatsHandler),
    ("_debate_share_handler", DebateShareHandler),
    ("_public_debate_viewer_handler", PublicDebateViewerHandler),
    ("_debate_interventions_handler", DebateInterventionsHandler),
    # Decision package
    ("_decision_package_handler", DecisionPackageHandler),
    # Settlements
    ("_settlement_handler", SettlementHandler),
    # Spectate stream
    ("_spectate_stream_handler", SpectateStreamHandler),
    # Receipt export
    ("_receipt_export_handler", ReceiptExportHandler),
]

__all__ = [
    # Debate handlers
    "DebatesHandler",
    "GraphDebatesHandler",
    "MatrixDebatesHandler",
    "ConsensusHandler",
    "GenesisHandler",
    "ReplaysHandler",
    "TournamentHandler",
    "DeliberationsHandler",
    "OrchestrationHandler",
    # Decision handlers
    "DecisionExplainHandler",
    "DecisionPipelineHandler",
    "DecisionHandler",
    "CritiqueHandler",
    "ExplainabilityHandler",
    "UncertaintyHandler",
    # Verification handlers
    "VerificationHandler",
    "AuditingHandler",
    "FormalVerificationHandler",
    "GauntletHandler",
    # Gauntlet v1 handlers
    "GauntletSecureHandler",
    "GauntletSchemaHandler",
    "GauntletTemplateHandler",
    "GauntletValidateReceiptHandler",
    "GauntletAllSchemasHandler",
    "GauntletTemplatesListHandler",
    "GauntletReceiptExportHandler",
    "GauntletHeatmapExportHandler",
    # Review handlers
    "ReviewsHandler",
    "EvaluationHandler",
    "ReceiptsHandler",
    # Other debate handlers
    "HybridDebateHandler",
    "EmailDebateHandler",
    "SecurityDebateHandler",
    "TemplateDiscoveryHandler",
    "CompositeHandler",
    "DebateStatsHandler",
    "DebateShareHandler",
    "PublicDebateViewerHandler",
    "DebateInterventionsHandler",
    "DecisionPackageHandler",
    "SettlementHandler",
    "SpectateStreamHandler",
    "ReceiptExportHandler",
    # Registry
    "DEBATE_HANDLER_REGISTRY",
]
