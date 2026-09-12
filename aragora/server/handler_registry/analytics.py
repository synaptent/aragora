"""
Analytics and metrics handler imports and registry entries.

This module contains imports and registry entries for:
- Analytics handlers (AnalyticsHandler, AnalyticsDashboardHandler, etc.)
- Metrics handlers (MetricsHandler, UnifiedMetricsHandler, etc.)
- SLO handlers
- Memory analytics
- Pulse and trending handlers
"""

from __future__ import annotations

from .core import _safe_import

# =============================================================================
# Analytics Handler Imports
# =============================================================================

# Core analytics handlers
AnalyticsHandler = _safe_import("aragora.server.handlers", "AnalyticsHandler")
AnalyticsDashboardHandler = _safe_import("aragora.server.handlers", "AnalyticsDashboardHandler")
EndpointAnalyticsHandler = _safe_import("aragora.server.handlers", "EndpointAnalyticsHandler")
AnalyticsMetricsHandler = _safe_import("aragora.server.handlers", "AnalyticsMetricsHandler")
AnalyticsPerformanceHandler = _safe_import("aragora.server.handlers", "AnalyticsPerformanceHandler")
OutcomeAnalyticsHandler = _safe_import("aragora.server.handlers", "OutcomeAnalyticsHandler")

# Memory analytics
MemoryAnalyticsHandler = _safe_import("aragora.server.handlers", "MemoryAnalyticsHandler")

# Cross-platform analytics
CrossPlatformAnalyticsHandler = _safe_import(
    "aragora.server.handlers.features.cross_platform_analytics", "CrossPlatformAnalyticsHandler"
)

# Analytics platforms integration
AnalyticsPlatformsHandler = _safe_import(
    "aragora.server.handlers.features", "AnalyticsPlatformsHandler"
)

# =============================================================================
# Metrics Handler Imports
# =============================================================================

MetricsHandler = _safe_import("aragora.server.handlers", "MetricsHandler")
UnifiedMetricsHandler = _safe_import(
    "aragora.server.handlers.metrics.metrics_endpoint", "UnifiedMetricsHandler"
)
SLOHandler = _safe_import("aragora.server.handlers", "SLOHandler")

# =============================================================================
# Pulse & Trending Handler Imports
# =============================================================================

PulseHandler = _safe_import("aragora.server.handlers", "PulseHandler")

# =============================================================================
# Cost Handler
# =============================================================================

CostHandler = _safe_import("aragora.server.handlers.costs", "CostHandler")

# =============================================================================
# Usage Metering
# =============================================================================

UsageMeteringHandler = _safe_import(
    "aragora.server.handlers.usage_metering", "UsageMeteringHandler"
)

# =============================================================================
# Canvas Pipeline
# =============================================================================

CanvasPipelineHandler = _safe_import(
    "aragora.server.handlers.canvas_pipeline", "CanvasPipelineHandler"
)

# Idea Canvas
IdeaCanvasHandler = _safe_import("aragora.server.handlers.idea_canvas", "IdeaCanvasHandler")

# Goal Canvas
GoalCanvasHandler = _safe_import("aragora.server.handlers.goal_canvas", "GoalCanvasHandler")

# Action Canvas
ActionCanvasHandler = _safe_import("aragora.server.handlers.action_canvas", "ActionCanvasHandler")

# Orchestration Canvas
OrchestrationCanvasHandler = _safe_import(
    "aragora.server.handlers.orchestration_canvas", "OrchestrationCanvasHandler"
)

# Universal Graph Pipeline
UniversalGraphHandler = _safe_import(
    "aragora.server.handlers.pipeline.universal_graph", "UniversalGraphHandler"
)

# Pipeline Stage Transitions
PipelineTransitionsHandler = _safe_import(
    "aragora.server.handlers.pipeline.transitions", "PipelineTransitionsHandler"
)

# Provenance Explorer (serves /api/v1/pipeline/graph/ for the React component)
ProvenanceExplorerHandler = _safe_import(
    "aragora.server.handlers.pipeline.provenance_explorer", "ProvenanceExplorerHandler"
)

# DAG Operations
DAGOperationsHandler = _safe_import(
    "aragora.server.handlers.dag_operations", "DAGOperationsHandler"
)

# Outcome Tracking
OutcomeHandler = _safe_import("aragora.server.handlers.governance.outcomes", "OutcomeHandler")

# Decision Benchmarking
BenchmarkingHandler = _safe_import("aragora.server.handlers.benchmarking", "BenchmarkingHandler")

# Decision Playbooks
PlaybookHandler = _safe_import("aragora.server.handlers.playbooks", "PlaybookHandler")

# Knowledge Flow (flywheel visualization)
KnowledgeFlowHandler = _safe_import(
    "aragora.server.handlers.knowledge_flow", "KnowledgeFlowHandler"
)

# Decision Analytics (issue #281)
DecisionAnalyticsHandler = _safe_import(
    "aragora.server.handlers.analytics.decision_analytics", "DecisionAnalyticsHandler"
)

# Outcome Dashboard (issue #281 - consolidated dashboard)
OutcomeDashboardHandler = _safe_import(
    "aragora.server.handlers.analytics_dashboard.outcome_dashboard", "OutcomeDashboardHandler"
)

# Spend Analytics Dashboard
SpendAnalyticsDashboardHandler = _safe_import(
    "aragora.server.handlers.analytics_dashboard.spend_analytics_dashboard",
    "SpendAnalyticsDashboardHandler",
)

# Agent Evolution Dashboard (issue #307)
AgentEvolutionDashboardHandler = _safe_import(
    "aragora.server.handlers.analytics_dashboard.agent_evolution_dashboard",
    "AgentEvolutionDashboardHandler",
)

# Pipeline handlers
PipelineExecuteHandler = _safe_import(
    "aragora.server.handlers.pipeline.execute", "PipelineExecuteHandler"
)
PipelineGraphHandler = _safe_import(
    "aragora.server.handlers.pipeline_graph", "PipelineGraphHandler"
)
PlanManagementHandler = _safe_import(
    "aragora.server.handlers.pipeline.plans", "PlanManagementHandler"
)
ReceiptExplorerHandler = _safe_import(
    "aragora.server.handlers.pipeline.receipts", "ReceiptExplorerHandler"
)
DecompositionHandler = _safe_import(
    "aragora.server.handlers.pipeline.decomposition", "DecompositionHandler"
)
RunsHandler = _safe_import("aragora.server.handlers.runs", "RunsHandler")

# Differentiation and moderation analytics
DifferentiationHandler = _safe_import(
    "aragora.server.handlers.analytics_dashboard.differentiation", "DifferentiationHandler"
)
ModerationAnalyticsHandler = _safe_import(
    "aragora.server.handlers.analytics.moderation_analytics", "ModerationAnalyticsHandler"
)

# Ralph campaign observability dashboard
RalphDashboardHandler = _safe_import(
    "aragora.server.handlers.ralph_dashboard", "RalphDashboardHandler"
)

# =============================================================================
# Analytics Handler Registry Entries
# =============================================================================

ANALYTICS_HANDLER_REGISTRY: list[tuple[str, object]] = [
    ("_pulse_handler", PulseHandler),
    ("_analytics_handler", AnalyticsHandler),
    ("_analytics_dashboard_handler", AnalyticsDashboardHandler),
    ("_endpoint_analytics_handler", EndpointAnalyticsHandler),
    ("_analytics_metrics_handler", AnalyticsMetricsHandler),
    ("_analytics_performance_handler", AnalyticsPerformanceHandler),
    ("_outcome_analytics_handler", OutcomeAnalyticsHandler),
    ("_metrics_handler", MetricsHandler),
    ("_unified_metrics_handler", UnifiedMetricsHandler),
    ("_slo_handler", SLOHandler),
    ("_memory_analytics_handler", MemoryAnalyticsHandler),
    ("_cross_platform_analytics_handler", CrossPlatformAnalyticsHandler),
    ("_analytics_platforms_handler", AnalyticsPlatformsHandler),
    ("_cost_handler", CostHandler),
    ("_usage_metering_handler", UsageMeteringHandler),
    # Canvas pipeline
    ("_canvas_pipeline_handler", CanvasPipelineHandler),
    # Idea canvas
    ("_idea_canvas_handler", IdeaCanvasHandler),
    # Goal canvas
    ("_goal_canvas_handler", GoalCanvasHandler),
    # Action canvas
    ("_action_canvas_handler", ActionCanvasHandler),
    # Orchestration canvas
    ("_orchestration_canvas_handler", OrchestrationCanvasHandler),
    # Universal graph pipeline
    ("_universal_graph_handler", UniversalGraphHandler),
    # Pipeline stage transitions
    ("_pipeline_transitions_handler", PipelineTransitionsHandler),
    # Provenance explorer
    ("_provenance_explorer_handler", ProvenanceExplorerHandler),
    # DAG operations
    ("_dag_operations_handler", DAGOperationsHandler),
    # Outcome tracking
    ("_outcome_handler", OutcomeHandler),
    # Decision benchmarking
    ("_benchmarking_handler", BenchmarkingHandler),
    # Decision playbooks
    ("_playbook_handler", PlaybookHandler),
    # Knowledge flow (flywheel visualization)
    ("_knowledge_flow_handler", KnowledgeFlowHandler),
    # Decision analytics (issue #281)
    ("_decision_analytics_handler", DecisionAnalyticsHandler),
    # Outcome dashboard (issue #281 - consolidated)
    ("_outcome_dashboard_handler", OutcomeDashboardHandler),
    # Spend analytics dashboard
    ("_spend_analytics_dashboard_handler", SpendAnalyticsDashboardHandler),
    # Pipeline handlers
    ("_pipeline_execute_handler", PipelineExecuteHandler),
    ("_pipeline_graph_handler", PipelineGraphHandler),
    ("_plan_management_handler", PlanManagementHandler),
    ("_receipt_explorer_handler", ReceiptExplorerHandler),
    ("_decomposition_handler", DecompositionHandler),
    ("_runs_handler", RunsHandler),
    # Differentiation and moderation analytics
    ("_differentiation_handler", DifferentiationHandler),
    ("_moderation_analytics_handler", ModerationAnalyticsHandler),
    # Agent evolution dashboard (issue #307)
    ("_agent_evolution_dashboard_handler", AgentEvolutionDashboardHandler),
    # Ralph campaign observability dashboard
    ("_ralph_dashboard_handler", RalphDashboardHandler),
]

__all__ = [
    # Analytics handlers
    "AnalyticsHandler",
    "AnalyticsDashboardHandler",
    "EndpointAnalyticsHandler",
    "AnalyticsMetricsHandler",
    "AnalyticsPerformanceHandler",
    "OutcomeAnalyticsHandler",
    "MemoryAnalyticsHandler",
    "CrossPlatformAnalyticsHandler",
    "AnalyticsPlatformsHandler",
    # Metrics handlers
    "MetricsHandler",
    "UnifiedMetricsHandler",
    "SLOHandler",
    # Pulse handlers
    "PulseHandler",
    # Cost handlers
    "CostHandler",
    "UsageMeteringHandler",
    # Canvas pipeline
    "CanvasPipelineHandler",
    "IdeaCanvasHandler",
    "GoalCanvasHandler",
    "ActionCanvasHandler",
    "OrchestrationCanvasHandler",
    "UniversalGraphHandler",
    "PipelineTransitionsHandler",
    "ProvenanceExplorerHandler",
    "DAGOperationsHandler",
    # Outcome tracking
    "OutcomeHandler",
    # Decision benchmarking
    "BenchmarkingHandler",
    # Knowledge flow
    "KnowledgeFlowHandler",
    # Decision analytics
    "DecisionAnalyticsHandler",
    # Outcome dashboard
    "OutcomeDashboardHandler",
    # Spend analytics dashboard
    "SpendAnalyticsDashboardHandler",
    # Pipeline handlers
    "PipelineExecuteHandler",
    "PipelineGraphHandler",
    "PlanManagementHandler",
    "ReceiptExplorerHandler",
    "DecompositionHandler",
    "RunsHandler",
    # Differentiation and moderation analytics
    "DifferentiationHandler",
    "ModerationAnalyticsHandler",
    # Agent evolution dashboard
    "AgentEvolutionDashboardHandler",
    # Ralph campaign observability dashboard
    "RalphDashboardHandler",
    # Registry
    "ANALYTICS_HANDLER_REGISTRY",
]
