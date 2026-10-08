"""
Pipeline module for aragora - Decision-to-implementation artifacts.

Transforms debate outcomes into actionable development artifacts:
- DecisionPlan: Full gold-path bridge from DebateResult to executable workflow
- DecisionMemo: Summary of debate conclusions
- RiskRegister: Identified risks and mitigations
- VerificationPlan: Verification strategy
- PatchPlan: Implementation steps
- DecisionIntegrityPackage: Receipt + implementation plan bundle
- UniversalNode/UniversalGraph: Unified schema spanning IDEAS→GOALS→ACTIONS→ORCHESTRATION
- GraphStore: SQLite persistence for universal graphs
- Stage transitions: Promote nodes across pipeline stages with provenance
- Adapters: Bidirectional conversion between Canvas/Goal models and UniversalNode
"""

from aragora.pipeline.decision_integrity import (
    ContextSnapshot,
    DecisionIntegrityPackage,
    build_decision_integrity_package,
    capture_context_snapshot,
)
from aragora.pipeline.decision_plan import (
    ApprovalMode,
    ApprovalRecord,
    BudgetAllocation,
    DecisionPlan,
    DecisionPlanFactory,
    PlanOutcome,
    PlanStatus,
    record_plan_outcome,
)
from aragora.pipeline.execution_notifier import ExecutionNotifier, ExecutionProgress
from aragora.pipeline.notifications import (
    notify_plan_created,
    notify_plan_approved,
    notify_plan_rejected,
    notify_execution_started,
    notify_execution_completed,
    notify_execution_failed,
)
from aragora.pipeline.executor import PlanExecutor, get_plan, list_plans, store_plan
from aragora.pipeline.idea_to_execution import (
    IdeaToExecutionPipeline,
    PipelineConfig,
    PipelineResult,
    StageResult,
)
from aragora.pipeline.pr_generator import DecisionMemo, PatchPlan, PRGenerator
from aragora.pipeline.risk_register import Risk, RiskRegister
from aragora.pipeline.adapters import (
    canvas_to_universal_graph,
    from_argument_node,
    from_canvas_node,
    from_goal_node,
    to_canvas_node,
    to_goal_node,
    universal_graph_to_canvas,
)
from aragora.pipeline.graph_store import GraphStore, get_graph_store
from aragora.pipeline.dag_model import (
    PipelineDAGDependency,
    PipelineDAGSnapshot,
    PipelineDAGStage,
    PipelineStageDependency,
    PipelineLiveUpdate,
    PipelineNodeRuntime,
)
from aragora.pipeline.stage_transitions import (
    actions_to_orchestration,
    goals_to_actions,
    ideas_to_goals,
    promote_node,
)
from aragora.pipeline.templates import (
    PipelineTemplate,
    TEMPLATE_REGISTRY,
    get_template,
    get_template_config,
    list_templates,
)
from aragora.pipeline.unified_orchestrator import (
    OrchestratorConfig,
    OrchestratorResult,
    UnifiedOrchestrator,
)
from aragora.pipeline.universal_node import UniversalEdge, UniversalGraph, UniversalNode
from aragora.pipeline.verification_plan import (
    VerificationCase,
    VerificationPlan,
    VerificationPlanGenerator,
)

# Backward compatibility aliases (old names triggered pytest discovery)
TestPlan = VerificationPlan
TestCase = VerificationCase
TestPlanGenerator = VerificationPlanGenerator

__all__ = [
    # Gold path
    "DecisionPlan",
    "DecisionPlanFactory",
    "PlanStatus",
    "PlanOutcome",
    "ApprovalMode",
    "ApprovalRecord",
    "BudgetAllocation",
    "record_plan_outcome",
    # Execution notifications
    "ExecutionNotifier",
    "ExecutionProgress",
    # Plan lifecycle notifications
    "notify_plan_created",
    "notify_plan_approved",
    "notify_plan_rejected",
    "notify_execution_started",
    "notify_execution_completed",
    "notify_execution_failed",
    # Executor
    "PlanExecutor",
    "get_plan",
    "list_plans",
    "store_plan",
    # Decision integrity
    "ContextSnapshot",
    "DecisionIntegrityPackage",
    "build_decision_integrity_package",
    "capture_context_snapshot",
    "PRGenerator",
    "DecisionMemo",
    "PatchPlan",
    "RiskRegister",
    "Risk",
    "VerificationPlan",
    "VerificationCase",
    # Idea-to-Execution pipeline
    "IdeaToExecutionPipeline",
    "PipelineConfig",
    "PipelineResult",
    "StageResult",
    # Universal graph schema
    "UniversalNode",
    "UniversalEdge",
    "UniversalGraph",
    "PipelineNodeRuntime",
    "PipelineDAGDependency",
    "PipelineDAGStage",
    "PipelineDAGSnapshot",
    "PipelineStageDependency",
    "PipelineLiveUpdate",
    # Graph persistence
    "GraphStore",
    "get_graph_store",
    # Stage transitions
    "promote_node",
    "ideas_to_goals",
    "goals_to_actions",
    "actions_to_orchestration",
    # Adapters
    "from_canvas_node",
    "to_canvas_node",
    "from_goal_node",
    "to_goal_node",
    "from_argument_node",
    "canvas_to_universal_graph",
    "universal_graph_to_canvas",
    # Templates
    "PipelineTemplate",
    "TEMPLATE_REGISTRY",
    "get_template",
    "get_template_config",
    "list_templates",
    # Unified orchestrator
    "UnifiedOrchestrator",
    "OrchestratorConfig",
    "OrchestratorResult",
    # Backward compatibility
    "TestPlan",
    "TestCase",
]

# The core decision router builds decision-integrity payloads through this registration.
from aragora.core.decision_route_hooks import (
    register_decision_integrity_builder as _register_decision_integrity_builder,
)
from aragora.pipeline.decision_integrity_utils import (
    build_decision_integrity_payload as _build_decision_integrity_payload,
)

_register_decision_integrity_builder(_build_decision_integrity_payload)
