"""Backbone coverage inventory for persisted or executable DecisionPlan seams."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

BackboneCoverage = Literal["green", "reuse_only", "legacy_bypass"]
BackboneLifecycle = Literal["create", "execute", "mixed"]
BackboneWiringMode = Literal[
    "canonical_queue",
    "manual_seed",
    "manual_run",
    "execution_bridge_only",
    "legacy_create",
    "direct_execute",
]


@dataclass(frozen=True)
class BackboneEntrypoint:
    file_path: str
    qualname: str
    lifecycle: BackboneLifecycle
    coverage: BackboneCoverage
    wiring_mode: BackboneWiringMode
    signals: tuple[str, ...]

    @property
    def identifier(self) -> str:
        return f"{self.file_path}::{self.qualname}"


ENTRYPOINT_INVENTORY: Final[tuple[BackboneEntrypoint, ...]] = (
    BackboneEntrypoint(
        file_path="aragora/pipeline/decision_integrity_utils.py",
        qualname="ensure_decision_plan_backbone_run",
        lifecycle="create",
        coverage="green",
        wiring_mode="manual_seed",
        signals=("run_ledger_create",),
    ),
    BackboneEntrypoint(
        file_path="aragora/pipeline/decision_integrity_utils.py",
        qualname="execute_decision_plan_with_backbone",
        lifecycle="execute",
        coverage="green",
        wiring_mode="canonical_queue",
        signals=("bridge_execute_approved_plan", "queue_plan_execution"),
    ),
    BackboneEntrypoint(
        file_path="aragora/pipeline/decision_integrity_utils.py",
        qualname="build_decision_integrity_payload",
        lifecycle="mixed",
        coverage="green",
        wiring_mode="manual_seed",
        signals=(
            "decision_plan_factory",
            "ensure_decision_plan_backbone_run",
            "execute_decision_plan_with_backbone",
            "store_plan",
        ),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/debates/implementation.py",
        qualname="_persist_plan",
        lifecycle="create",
        coverage="green",
        wiring_mode="manual_seed",
        signals=("decision_plan_factory", "ensure_decision_plan_backbone_run", "store_plan"),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/debates/implementation.py",
        qualname="ImplementationOperationsMixin._persist_artifacts",
        lifecycle="create",
        coverage="green",
        wiring_mode="manual_seed",
        signals=(
            "decision_plan_factory",
            "ensure_decision_plan_backbone_run",
            "store_plan",
        ),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/debates/implementation.py",
        qualname="ImplementationOperationsMixin._handle_workflow_mode",
        lifecycle="mixed",
        coverage="green",
        wiring_mode="manual_seed",
        signals=(
            "decision_plan_factory",
            "ensure_decision_plan_backbone_run",
            "execute_decision_plan_with_backbone",
            "store_plan",
        ),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/debates/implementation.py",
        qualname="ImplementationOperationsMixin._execute_computer_use",
        lifecycle="execute",
        coverage="green",
        wiring_mode="canonical_queue",
        signals=("execute_decision_plan_with_backbone", "store_plan"),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/prompt_engine/handler.py",
        qualname="PromptEngineHandler._handle_run",
        lifecycle="mixed",
        coverage="green",
        wiring_mode="manual_run",
        signals=(
            "bridge_schedule_execution",
            "decision_plan_factory",
            "plan_store_create",
            "run_ledger_create",
            "store_plan",
        ),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/pipeline/execute.py",
        qualname="PipelineExecuteHandler.handle_post",
        lifecycle="execute",
        coverage="green",
        wiring_mode="canonical_queue",
        signals=("queue_plan_execution",),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/pipeline/execute.py",
        qualname="PipelineExecuteHandler._execute_pipeline",
        lifecycle="execute",
        coverage="green",
        wiring_mode="canonical_queue",
        signals=("queue_plan_execution",),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/canvas/canvas_pipeline.py",
        qualname="CanvasPipelineHandler.handle_execute",
        lifecycle="execute",
        coverage="green",
        wiring_mode="canonical_queue",
        signals=("queue_plan_execution",),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/canvas/orchestration_canvas.py",
        qualname="OrchestrationCanvasHandler._execute_pipeline",
        lifecycle="execute",
        coverage="green",
        wiring_mode="canonical_queue",
        signals=("queue_plan_execution",),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/fastapi/routes/canvas_pipeline.py",
        qualname="execute_pipeline",
        lifecycle="execute",
        coverage="green",
        wiring_mode="canonical_queue",
        signals=("queue_plan_execution",),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/decisions/plans.py",
        qualname="PlansHandler._create_plan",
        lifecycle="create",
        coverage="green",
        wiring_mode="manual_seed",
        signals=("decision_plan_ctor", "ensure_decision_plan_backbone_run", "plan_store_create"),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/decisions/plans.py",
        qualname="PlansHandler._approve_plan",
        lifecycle="execute",
        coverage="green",
        wiring_mode="canonical_queue",
        signals=("queue_plan_execution",),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/decisions/plans.py",
        qualname="PlansHandler._execute_plan",
        lifecycle="execute",
        coverage="green",
        wiring_mode="canonical_queue",
        signals=("queue_plan_execution",),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/decisions/pipeline.py",
        qualname="DecisionPipelineHandler._handle_create_plan",
        lifecycle="create",
        coverage="green",
        wiring_mode="manual_seed",
        signals=("decision_plan_factory", "ensure_decision_plan_backbone_run", "store_plan"),
    ),
    BackboneEntrypoint(
        file_path="aragora/server/handlers/decisions/pipeline.py",
        qualname="DecisionPipelineHandler._handle_execute_plan",
        lifecycle="execute",
        coverage="green",
        wiring_mode="canonical_queue",
        signals=("execute_decision_plan_with_backbone",),
    ),
    BackboneEntrypoint(
        file_path="aragora/cli/commands/decide.py",
        qualname="run_decide",
        lifecycle="mixed",
        coverage="green",
        wiring_mode="canonical_queue",
        signals=("decision_plan_factory", "execute_decision_plan_with_backbone"),
    ),
    BackboneEntrypoint(
        file_path="aragora/cli/commands/decide.py",
        qualname="cmd_plans_execute",
        lifecycle="execute",
        coverage="green",
        wiring_mode="canonical_queue",
        signals=("execute_decision_plan_with_backbone",),
    ),
    BackboneEntrypoint(
        file_path="aragora/debate/orchestrator_runner.py",
        qualname="_auto_execute_plan",
        lifecycle="mixed",
        coverage="green",
        wiring_mode="manual_seed",
        signals=(
            "decision_plan_factory",
            "ensure_decision_plan_backbone_run",
            "execute_decision_plan_with_backbone",
            "store_plan",
        ),
    ),
    BackboneEntrypoint(
        file_path="aragora/debate/post_debate_coordinator.py",
        qualname="PostDebateCoordinator.run",
        lifecycle="mixed",
        coverage="green",
        wiring_mode="manual_run",
        signals=("run_ledger_create",),
    ),
    BackboneEntrypoint(
        file_path="aragora/debate/hook_handlers.py",
        qualname="HookHandlerRegistry._register_decision_plan_handlers.handle_auto_plan_creation",
        lifecycle="create",
        coverage="green",
        wiring_mode="manual_seed",
        signals=("decision_plan_factory", "ensure_decision_plan_backbone_run", "store_plan"),
    ),
    BackboneEntrypoint(
        file_path="aragora/nomic/pipeline_bridge.py",
        qualname="NomicPipelineBridge.execute_via_pipeline",
        lifecycle="execute",
        coverage="green",
        wiring_mode="canonical_queue",
        signals=("execute_decision_plan_with_backbone",),
    ),
    BackboneEntrypoint(
        file_path="aragora/swarm/boss_worker_lifecycle.py",
        qualname="dispatch_issue",
        lifecycle="mixed",
        coverage="green",
        wiring_mode="manual_run",
        signals=("run_ledger_create",),
    ),
)

INTERNAL_BACKBONE_HELPERS: Final[dict[str, str]] = {
    "aragora/pipeline/canonical_execution.py::_ensure_backbone_run": (
        "internal canonical queue run-seeding helper"
    ),
    "aragora/pipeline/canonical_execution.py::execute_queued_plan": (
        "internal canonical queue execution helper"
    ),
    "aragora/pipeline/execution_bridge.py::ExecutionBridge.schedule_execution._run": (
        "nested bridge thread target behind the public scheduling seam"
    ),
    "aragora/pipeline/unified_orchestrator.py::UnifiedOrchestrator._create_backbone_run": (
        "internal orchestrator run-seeding helper"
    ),
    "aragora/cli/commands/decide.py::_seed_cli_backbone_run": (
        "internal CLI helper for run-ledger seeding and receipt sync"
    ),
    "aragora/debate/post_debate_coordinator.py::PostDebateCoordinator._seed_backbone_run": (
        "internal post-debate helper that seeds the backbone run before pipeline execution"
    ),
}

_GREEN_SIGNAL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "bridge_execute_approved_plan",
        "bridge_schedule_execution",
        "ensure_decision_plan_backbone_run",
        "execute_decision_plan_with_backbone",
        "plan_executor_execute",
        "queue_plan_execution",
        "run_ledger_create",
    }
)
_BUILD_SIGNAL_NAMES: Final[frozenset[str]] = frozenset(
    {"decision_plan_ctor", "decision_plan_factory"}
)
_PERSISTENCE_SIGNAL_NAMES: Final[frozenset[str]] = frozenset({"plan_store_create", "store_plan"})


def _walk_non_nested(node: ast.AST) -> list[ast.AST]:
    children: list[ast.AST] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        children.append(child)
        children.extend(_walk_non_nested(child))
    return children


def _assigned_names(targets: list[ast.expr]) -> set[str]:
    names: set[str] = set()
    for target in targets:
        if isinstance(target, ast.Name):
            names.add(target.id)
    return names


def _collect_function_signals(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    plan_executor_vars: set[str] = set()
    plan_store_vars: set[str] = set()
    runtime_vars: set[str] = set()
    signals: set[str] = set()

    for child in _walk_non_nested(node):
        if isinstance(child, (ast.Assign, ast.AnnAssign)):
            value = getattr(child, "value", None)
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            if isinstance(value, ast.Call):
                func = value.func
                if isinstance(func, ast.Name):
                    assigned = _assigned_names(targets)
                    if func.id == "PlanExecutor":
                        plan_executor_vars.update(assigned)
                    elif func.id in {"_get_plan_store", "get_plan_store", "PlanStore"}:
                        plan_store_vars.update(assigned)
                    elif func.id == "BackboneRuntime":
                        runtime_vars.update(assigned)

        if not isinstance(child, ast.Call):
            continue

        func = child.func
        if isinstance(func, ast.Name):
            if func.id == "DecisionPlan":
                signals.add("decision_plan_ctor")
            elif func.id == "RunLedger":
                signals.add("run_ledger_create")
            elif func.id == "ensure_decision_plan_backbone_run":
                signals.add("ensure_decision_plan_backbone_run")
            elif func.id == "execute_decision_plan_with_backbone":
                signals.add("execute_decision_plan_with_backbone")
            elif func.id == "queue_plan_execution":
                signals.add("queue_plan_execution")
            elif func.id == "store_plan":
                signals.add("store_plan")
            continue

        if not isinstance(func, ast.Attribute):
            continue

        if (
            func.attr.startswith("from_")
            and isinstance(func.value, ast.Name)
            and func.value.id == "DecisionPlanFactory"
        ):
            signals.add("decision_plan_factory")
            continue

        if func.attr == "create":
            value = func.value
            if isinstance(value, ast.Name) and value.id in plan_store_vars:
                signals.add("plan_store_create")
            continue

        if func.attr == "create_run":
            value = func.value
            if isinstance(value, ast.Name) and value.id in runtime_vars:
                signals.add("run_ledger_create")
            continue

        if func.attr == "execute":
            value = func.value
            if isinstance(value, ast.Name) and value.id in plan_executor_vars:
                signals.add("plan_executor_execute")
            elif (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "PlanExecutor"
            ):
                signals.add("plan_executor_execute")
            continue

        if func.attr == "execute_approved_plan":
            signals.add("bridge_execute_approved_plan")
            continue

        if func.attr == "schedule_execution":
            signals.add("bridge_schedule_execution")

    return tuple(sorted(signals))


class _EntrypointVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str) -> None:
        self._file_path = file_path
        self._stack: list[str] = []
        self.discovered: dict[str, tuple[str, ...]] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_callable(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_callable(node)

    def _visit_callable(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._stack.append(node.name)
        qualname = ".".join(self._stack)
        signals = _collect_function_signals(node)
        signal_set = set(signals)
        if signal_set & _GREEN_SIGNAL_NAMES or (
            signal_set & _BUILD_SIGNAL_NAMES
            and (signal_set & _PERSISTENCE_SIGNAL_NAMES or signal_set & _GREEN_SIGNAL_NAMES)
        ):
            self.discovered[f"{self._file_path}::{qualname}"] = signals

        for child in node.body:
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                self.visit(child)
        self._stack.pop()


def discover_backbone_entrypoints(repo_root: Path) -> dict[str, tuple[str, ...]]:
    """Return all repo callables that match the backbone entrypoint contract scan."""
    discovered: dict[str, tuple[str, ...]] = {}
    for path in sorted((repo_root / "aragora").rglob("*.py")):
        file_path = str(path.relative_to(repo_root))
        visitor = _EntrypointVisitor(file_path)
        visitor.visit(ast.parse(path.read_text()))
        discovered.update(visitor.discovered)
    return discovered
