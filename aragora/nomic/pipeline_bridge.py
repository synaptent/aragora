"""Pipeline Bridge - Route Nomic Loop output through the DecisionPlan pipeline.

Converts Nomic Loop debate output (goal, subtasks, consensus) into a
DecisionPlan, then executes it via PlanExecutor. This gives self-improvement
access to risk registers, verification plans, execution receipts, and KM
ingestion for free.

Also provides conversion from Nomic Loop results into UniversalGraph format
for visual monitoring of self-improvement through the /pipeline UI.

Usage:
    from aragora.nomic.pipeline_bridge import NomicPipelineBridge

    bridge = NomicPipelineBridge(repo_path=Path.cwd())
    outcome = await bridge.execute_via_pipeline(
        goal="Improve error handling",
        subtasks=decomposition.subtasks,
        consensus_result=debate_result,  # Optional DebateResult
        execution_mode="hybrid",
    )

    # Convert cycle result to pipeline visualization
    graph = bridge.create_pipeline_from_cycle(orchestration_result)

The bridge is intentionally thin -- it transforms Nomic types to Pipeline
types and delegates execution to PlanExecutor.

Stability: ALPHA
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from aragora.pipeline.execution_mode import ExecutionMode as SafetyMode

from aragora.nomic.task_decomposer import SubTask, TaskDecomposition

if TYPE_CHECKING:
    from aragora.nomic.autonomous_orchestrator import OrchestrationResult
    from aragora.pipeline.universal_node import UniversalGraph

logger = logging.getLogger(__name__)


class ExecutionTarget(str, Enum):
    """First-class agent targets for bounded work execution."""

    CODEX = "codex"
    CLAUDE = "claude"


@dataclass
class BoundedWorkOrder:
    """Execution-bounded work order derived from a Nomic subtask.

    This is the product-side analogue of the dev-swarm WorkLease. It gives
    downstream pipeline stages an explicit unit of work with owned scope,
    dependencies, and success criteria.
    """

    work_order_id: str
    pipeline_task_id: str
    title: str
    description: str
    file_scope: list[str] = field(default_factory=list)
    dependency_ids: list[str] = field(default_factory=list)
    success_criteria: dict[str, Any] = field(default_factory=dict)
    expected_tests: list[str] = field(default_factory=list)
    estimated_complexity: str = "medium"
    risk_level: str = "review"
    target_agent: str = ExecutionTarget.CODEX.value
    reviewer_agent: str = ExecutionTarget.CLAUDE.value
    approval_required: bool = False
    mission_id: str = ""
    stage_id: str = ""
    assertion_ids: list[str] = field(default_factory=list)
    roadmap_refs: list[str] = field(default_factory=list)
    evidence_expectations: list[str] = field(default_factory=list)
    gate_expectations: dict[str, Any] = field(default_factory=dict)
    mission_context_policies: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        from aragora.swarm.mission import normalize_context_policies

        self.mission_id = str(self.mission_id or "").strip()
        self.stage_id = str(self.stage_id or "").strip()
        self.assertion_ids = _dedupe_nonempty(self.assertion_ids)
        self.roadmap_refs = _dedupe_nonempty(self.roadmap_refs)
        self.evidence_expectations = _dedupe_nonempty(self.evidence_expectations)
        self.gate_expectations = dict(self.gate_expectations or {})
        self.mission_context_policies = normalize_context_policies(
            self.mission_context_policies,
            file_scope=list(self.file_scope),
            evidence_expectations=list(self.evidence_expectations),
        )
        self.metadata = dict(self.metadata or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "pipeline_task_id": self.pipeline_task_id,
            "title": self.title,
            "description": self.description,
            "file_scope": list(self.file_scope),
            "dependency_ids": list(self.dependency_ids),
            "success_criteria": dict(self.success_criteria),
            "expected_tests": list(self.expected_tests),
            "estimated_complexity": self.estimated_complexity,
            "risk_level": self.risk_level,
            "target_agent": self.target_agent,
            "reviewer_agent": self.reviewer_agent,
            "approval_required": self.approval_required,
            "mission_id": self.mission_id,
            "stage_id": self.stage_id,
            "assertion_ids": list(self.assertion_ids),
            "roadmap_refs": list(self.roadmap_refs),
            "evidence_expectations": list(self.evidence_expectations),
            "gate_expectations": dict(self.gate_expectations),
            "mission_context_policies": dict(self.mission_context_policies),
            "metadata": dict(self.metadata),
        }


def _extract_expected_tests(success_criteria: dict[str, Any]) -> list[str]:
    """Extract normalized test commands from success criteria."""
    tests_value = success_criteria.get("tests")
    if isinstance(tests_value, str) and tests_value.strip():
        return [tests_value.strip()]
    if isinstance(tests_value, list):
        return [str(item).strip() for item in tests_value if str(item).strip()]
    return []


def _risk_level_for_complexity(complexity: str) -> str:
    """Map estimated complexity into a coarse approval risk tier."""
    level = str(complexity).strip().lower()
    if level == "high":
        return "critical"
    if level == "low":
        return "info"
    return "review"


def _target_pair_for_index(index: int) -> tuple[str, str]:
    """Alternate primary/reviewer targets across Codex and Claude."""
    if index % 2 == 0:
        return ExecutionTarget.CODEX.value, ExecutionTarget.CLAUDE.value
    return ExecutionTarget.CLAUDE.value, ExecutionTarget.CODEX.value


def _dedupe_nonempty(values: list[str]) -> list[str]:
    """Keep non-empty strings in insertion order."""
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _build_assessment_refresh_context(
    work_orders: list[BoundedWorkOrder],
) -> dict[str, Any]:
    """Summarize what the next assessment should explicitly refresh."""
    files_to_reassess = _dedupe_nonempty(
        [path for work_order in work_orders for path in work_order.file_scope]
    )
    test_commands = _dedupe_nonempty(
        [test for work_order in work_orders for test in work_order.expected_tests]
    )
    work_order_ids = _dedupe_nonempty([work_order.work_order_id for work_order in work_orders])

    return {
        "required": bool(work_orders),
        "reason": (
            "bounded_work_orders_changed_repo_truth" if work_orders else "no_bounded_work_orders"
        ),
        "files_to_reassess": files_to_reassess,
        "test_commands": test_commands,
        "work_order_ids": work_order_ids,
        "approval_required": any(work_order.approval_required for work_order in work_orders),
    }


def _stringify_success_target(key: str, value: Any) -> list[str]:
    """Flatten success-criteria values into human-readable lines."""
    if value is None:
        return []
    if isinstance(value, dict):
        lines: list[str] = []
        for nested_key, nested_value in value.items():
            nested_label = f"{key}.{nested_key}".strip(".")
            lines.extend(_stringify_success_target(nested_label, nested_value))
        return lines
    if isinstance(value, list):
        return [f"{key}: {text}" for text in [str(item).strip() for item in value] if text]
    text = str(value).strip()
    if not text:
        return []
    return [f"{key}: {text}"]


def _acceptance_criteria_for_work_order(work_order: BoundedWorkOrder) -> list[str]:
    """Translate bounded success criteria into SwarmSpec acceptance criteria."""
    criteria: list[str] = []
    for key, value in work_order.success_criteria.items():
        if str(key).strip().lower() == "tests":
            continue
        criteria.extend(_stringify_success_target(str(key).strip(), value))
    criteria.extend(f"Run and satisfy: {command}" for command in work_order.expected_tests)
    return _dedupe_nonempty(criteria)


def _constraints_for_work_order(work_order: BoundedWorkOrder) -> list[str]:
    """Translate a bounded work order into explicit dispatch constraints."""
    constraints: list[str] = []
    if work_order.file_scope:
        constraints.append(f"Stay within file scope: {', '.join(work_order.file_scope)}")
    if work_order.dependency_ids:
        constraints.append(
            f"Respect upstream dependencies before dispatch: {', '.join(work_order.dependency_ids)}"
        )
    if work_order.approval_required:
        constraints.append("Requires approval before risky execution or merge.")
    return _dedupe_nonempty(constraints)


def _estimated_cost_for_complexity(complexity: str) -> float:
    """Budget hint used for handoff manifests."""
    lowered = str(complexity or "").strip().lower()
    return {"low": 0.5, "medium": 1.0, "high": 2.0}.get(lowered, 1.0)


def _campaign_id_for_work_order(goal: str, work_order: BoundedWorkOrder) -> str:
    """Build a stable campaign id for a single dispatched work order."""
    seed = "|".join(
        [
            goal.strip(),
            work_order.work_order_id,
            work_order.pipeline_task_id,
            work_order.target_agent,
            work_order.reviewer_agent,
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"nomic-ralph-{digest}"


def _text_or_none(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _path_text(value: Path | str | None) -> str | None:
    if value is None:
        return None
    return _text_or_none(value)


def _subtask_to_implement_task(
    subtask: SubTask,
    index: int,
) -> Any:
    """Convert a Nomic SubTask to a pipeline ImplementTask.

    Args:
        subtask: The Nomic SubTask from task decomposition.
        index: 1-based index for generating task IDs.

    Returns:
        An ImplementTask ready for the pipeline.
    """
    from aragora.implement.types import ImplementTask

    # Map Nomic complexity levels to pipeline complexity levels
    complexity_map = {
        "low": "simple",
        "medium": "moderate",
        "high": "complex",
    }
    complexity = complexity_map.get(subtask.estimated_complexity, "moderate")

    # Convert Nomic dependency IDs to pipeline task IDs
    # Nomic subtasks use their own ID scheme; we remap to task-N format
    dependencies: list[str] = []
    # Dependencies will be resolved after all tasks are created

    return ImplementTask(
        id=f"task-{index}",
        description=subtask.description,
        files=subtask.file_scope,
        complexity=cast(Literal["simple", "moderate", "complex"], complexity),
        dependencies=dependencies,
    )


def _build_synthetic_debate_result(
    goal: str,
    subtasks: list[SubTask],
    dissent: list[str] | None = None,
) -> Any:
    """Build a minimal DebateResult for the DecisionPlanFactory.

    When the Nomic Loop debate phase does not produce a full DebateResult
    (e.g., when using heuristic decomposition), this constructs a synthetic
    one with enough data for the factory to generate useful risk registers
    and verification plans.

    Args:
        goal: The high-level goal that was debated/decomposed.
        subtasks: The decomposed subtasks.
        dissent: Optional dissenting views from the debate.

    Returns:
        A DebateResult populated with synthetic data.
    """
    from aragora.core_types import DebateResult

    debate_id = f"nomic-{uuid.uuid4().hex[:12]}"

    # Build a final answer from the subtask descriptions
    final_answer_lines = [f"Implementation plan for: {goal}\n"]
    for i, st in enumerate(subtasks, 1):
        files_str = ""
        if st.file_scope:
            files_str = " (" + ", ".join(f"`{f}`" for f in st.file_scope[:3]) + ")"
            final_answer_lines.append(f"{i}. {st.description}{files_str}")
        else:
            final_answer_lines.append(f"{i}. {st.description}")

    return DebateResult(
        debate_id=debate_id,
        task=goal,
        final_answer="\n".join(final_answer_lines),
        confidence=0.75,  # Moderate confidence for synthetic results
        consensus_reached=True,
        rounds_used=1,
        status="completed",
        participants=["nomic-orchestrator"],
        dissenting_views=dissent or [],
    )


def _resolve_dependencies(
    subtasks: list[SubTask],
    implement_tasks: list[Any],
) -> None:
    """Resolve Nomic subtask dependencies to pipeline task IDs.

    Modifies implement_tasks in-place to set dependency references.

    Args:
        subtasks: Original Nomic subtasks (with their ID scheme).
        implement_tasks: Pipeline ImplementTasks (with task-N IDs).
    """
    # Build a mapping from Nomic subtask ID to pipeline task ID
    nomic_to_pipeline: dict[str, str] = {}
    for i, st in enumerate(subtasks):
        nomic_to_pipeline[st.id] = f"task-{i + 1}"

    # Resolve dependencies
    for i, st in enumerate(subtasks):
        deps: list[str] = []
        for dep_id in st.dependencies:
            pipeline_id = nomic_to_pipeline.get(dep_id)
            if pipeline_id:
                deps.append(pipeline_id)
        implement_tasks[i].dependencies = deps


class NomicPipelineBridge:
    """Bridge between Nomic Loop and the DecisionPlan execution pipeline.

    Transforms Nomic subtasks and debate output into a DecisionPlan,
    then executes it via PlanExecutor to get risk registers, verification
    plans, receipts, and KM ingestion.

    Args:
        repo_path: Path to the repository root.
        budget_limit_usd: Optional budget cap for execution.
        execution_mode: Execution mode for PlanExecutor
            ("workflow", "hybrid", "fabric", "computer_use").
    """

    def __init__(
        self,
        repo_path: Path | None = None,
        budget_limit_usd: float | None = None,
        execution_mode: str = "hybrid",
    ) -> None:
        self._repo_path = repo_path or Path.cwd()
        self._budget_limit_usd = budget_limit_usd
        self._execution_mode = execution_mode

    def build_work_orders(self, subtasks: list[SubTask]) -> list[BoundedWorkOrder]:
        """Build bounded work orders from decomposed subtasks."""
        pipeline_id_by_subtask = {st.id: f"task-{i + 1}" for i, st in enumerate(subtasks)}
        work_orders: list[BoundedWorkOrder] = []
        for i, subtask in enumerate(subtasks, 1):
            target_agent, reviewer_agent = _target_pair_for_index(i - 1)
            risk_level = _risk_level_for_complexity(subtask.estimated_complexity)
            work_orders.append(
                BoundedWorkOrder(
                    work_order_id=subtask.id,
                    pipeline_task_id=f"task-{i}",
                    title=subtask.title,
                    description=subtask.description,
                    file_scope=list(subtask.file_scope),
                    dependency_ids=[
                        pipeline_id_by_subtask[dep_id]
                        for dep_id in subtask.dependencies
                        if dep_id in pipeline_id_by_subtask
                    ],
                    success_criteria=dict(subtask.success_criteria),
                    expected_tests=_extract_expected_tests(subtask.success_criteria),
                    estimated_complexity=subtask.estimated_complexity,
                    risk_level=risk_level,
                    target_agent=target_agent,
                    reviewer_agent=reviewer_agent,
                    approval_required=risk_level == "critical",
                    metadata={
                        "source": "nomic_subtask",
                        "depth": subtask.depth,
                        "parent_id": subtask.parent_id,
                    },
                )
            )
        return work_orders

    def build_plan_metadata(self, goal: str, subtasks: list[SubTask]) -> dict[str, Any]:
        """Build execution metadata for DecisionPlanFactory handoff."""
        work_orders = self.build_work_orders(subtasks)
        return {
            "source": "nomic_loop",
            "goal": goal,
            "subtask_count": len(subtasks),
            "work_order_protocol": "bounded-work-order/v1",
            "bounded_work_orders": [item.to_dict() for item in work_orders],
            "assessment_refresh": _build_assessment_refresh_context(work_orders),
            "dispatch_handoff": self.build_ralph_handoff(goal, subtasks),
        }

    @staticmethod
    def _select_ralph_work_order(
        work_orders: list[BoundedWorkOrder],
        preferred_work_order_id: str | None = None,
    ) -> tuple[BoundedWorkOrder | None, str]:
        """Choose one work order to route through the single-project Ralph path."""
        preferred = _text_or_none(preferred_work_order_id)
        if preferred:
            for work_order in work_orders:
                if preferred in {work_order.work_order_id, work_order.pipeline_task_id}:
                    return work_order, "preferred_work_order"
        for work_order in work_orders:
            if not work_order.dependency_ids:
                return work_order, "first_dependency_free_work_order"
        if work_orders:
            return work_orders[0], "first_work_order"
        return None, "no_work_orders"

    def _build_ralph_manifest_for_work_order(
        self,
        goal: str,
        work_order: BoundedWorkOrder,
        *,
        source_ref: str | None = None,
    ) -> Any:
        """Build a real CampaignManifest for one bounded work order.

        Imports are intentionally delayed because campaign planning also imports
        this bridge module.
        """
        from aragora.swarm.campaign import (
            CampaignDependency,
            CampaignManifest,
            CampaignProject,
            CampaignReviewGate,
        )
        from aragora.swarm.spec import SwarmSpec

        source_label = _text_or_none(source_ref) or goal
        project_id = work_order.pipeline_task_id
        spec = SwarmSpec(
            raw_goal=goal,
            refined_goal=work_order.title or goal,
            acceptance_criteria=_acceptance_criteria_for_work_order(work_order),
            constraints=_constraints_for_work_order(work_order),
            budget_limit_usd=self._budget_limit_usd,
            file_scope_hints=list(work_order.file_scope),
            work_orders=[work_order.to_dict()],
            mission_id=work_order.mission_id,
            stage_id=work_order.stage_id,
            assertion_ids=list(work_order.assertion_ids),
            roadmap_refs=list(work_order.roadmap_refs),
            evidence_expectations=list(work_order.evidence_expectations),
            gate_expectations=dict(work_order.gate_expectations),
            mission_context_policies=dict(work_order.mission_context_policies),
            estimated_complexity=work_order.estimated_complexity,
            requires_approval=work_order.approval_required,
            research_context={
                "dispatch_target": "ralph",
                "work_order_id": work_order.work_order_id,
                "pipeline_task_id": work_order.pipeline_task_id,
                "goal": goal,
            },
            pipeline_stage="orchestration",
            user_expertise="system",
        )
        project = CampaignProject(
            project_id=project_id,
            title=work_order.title or project_id,
            source_refs=_dedupe_nonempty(
                [
                    source_label,
                    f"work_order:{work_order.work_order_id}",
                    f"pipeline_task:{work_order.pipeline_task_id}",
                ]
            ),
            spec=spec,
            file_scope_hints=list(work_order.file_scope),
            acceptance_criteria=list(spec.acceptance_criteria),
            constraints=list(spec.constraints),
            dependencies=[
                CampaignDependency(project_id=dep_id, reason="Pipeline work-order dependency")
                for dep_id in work_order.dependency_ids
            ],
            estimated_cost_usd=_estimated_cost_for_complexity(work_order.estimated_complexity),
            review=CampaignReviewGate(
                required=True,
                review_model=work_order.reviewer_agent,
            ),
        )
        return CampaignManifest(
            campaign_id=_campaign_id_for_work_order(goal, work_order),
            created_at=datetime.now(timezone.utc).isoformat(),
            source_kind="nomic_pipeline_spec",
            source_ref=source_label,
            planner_model=work_order.reviewer_agent,
            planner_strategy="heuristic",
            worker_model=work_order.target_agent,
            review_model=work_order.reviewer_agent,
            enforce_cross_model_review=work_order.target_agent != work_order.reviewer_agent,
            max_parallel_ready_projects=1,
            max_retries_per_project=2,
            budget_limit_usd=float(self._budget_limit_usd or 5.0),
            time_limit_hours=4.0,
            projects=[project],
            planning_findings=[
                "dispatch_target=ralph",
                "handoff_protocol=nomic-ralph-handoff/v1",
                "work_order_protocol=bounded-work-order/v1",
                f"selected_work_order_id={work_order.work_order_id}",
                f"selected_pipeline_task_id={work_order.pipeline_task_id}",
            ],
        )

    def _ralph_receipt_metadata(
        self,
        *,
        work_order: BoundedWorkOrder | None,
        selection_reason: str,
        manifest: Any | None,
        manifest_path: Path | str | None = None,
        state_path: Path | str | None = None,
        supervisor_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Truthful receipt metadata for a compiled, written, or dispatched handoff."""
        manifest_text = _path_text(manifest_path)
        state_text = _path_text(state_path)
        supervisor_id = _text_or_none((supervisor_state or {}).get("supervisor_id"))
        ralph_status = _text_or_none((supervisor_state or {}).get("status"))
        manifest_dict = manifest.to_dict() if manifest is not None else {}
        project_ids = [
            str(item.get("project_id", "")).strip()
            for item in manifest_dict.get("projects", [])
            if str(item.get("project_id", "")).strip()
        ]
        project_receipt_paths = (
            [
                f"docs/receipts/{manifest_dict['campaign_id']}/{project_id}.yaml"
                for project_id in project_ids
            ]
            if manifest_dict.get("campaign_id")
            else []
        )
        if work_order is None:
            handoff_status = "not_dispatchable"
        elif supervisor_id or ralph_status:
            handoff_status = "dispatched"
        elif manifest_text:
            handoff_status = "blocked_on_dependencies" if work_order.dependency_ids else "ready"
        else:
            handoff_status = "compiled"
        return {
            "receipt_metadata_version": "dispatch-handoff/v1",
            "dispatch_target": "ralph",
            "handoff_status": handoff_status,
            "selection_reason": selection_reason,
            "selected_work_order_id": work_order.work_order_id if work_order is not None else None,
            "selected_pipeline_task_id": (
                work_order.pipeline_task_id if work_order is not None else None
            ),
            "blocked_dependency_ids": (
                list(work_order.dependency_ids) if work_order is not None else []
            ),
            "campaign_id": manifest_dict.get("campaign_id"),
            "manifest_path": manifest_text,
            "state_path": state_text,
            "supervisor_id": supervisor_id,
            "ralph_status": ralph_status,
            "project_ids": project_ids,
            "expected_project_receipts": project_receipt_paths,
            "worker_receipt_ids": [],
            "campaign_receipt_id": None,
            "truth": {
                "handoff_compiled": work_order is not None,
                "manifest_written": bool(manifest_text),
                "dispatch_started": bool(supervisor_id or ralph_status),
                "worker_receipts_recorded": False,
                "campaign_receipt_recorded": False,
            },
        }

    def build_ralph_handoff(
        self,
        goal: str,
        subtasks: list[SubTask],
        *,
        source_ref: str | None = None,
        preferred_work_order_id: str | None = None,
        manifest_path: Path | str | None = None,
        state_path: Path | str | None = None,
        supervisor_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a Ralph-ready single-project handoff for one generated pipeline spec."""
        work_orders = self.build_work_orders(subtasks)
        selected_work_order, selection_reason = self._select_ralph_work_order(
            work_orders,
            preferred_work_order_id=preferred_work_order_id,
        )
        manifest = None
        manifest_payload: dict[str, Any] | None = None
        if selected_work_order is not None:
            manifest = self._build_ralph_manifest_for_work_order(
                goal,
                selected_work_order,
                source_ref=source_ref,
            )
            manifest_payload = manifest.to_dict()
        return {
            "target": "ralph",
            "protocol": "nomic-ralph-handoff/v1",
            "selection": {
                "reason": selection_reason,
                "work_order_id": (
                    selected_work_order.work_order_id if selected_work_order is not None else None
                ),
                "pipeline_task_id": (
                    selected_work_order.pipeline_task_id
                    if selected_work_order is not None
                    else None
                ),
            },
            "manifest": manifest_payload,
            "receipt_metadata": self._ralph_receipt_metadata(
                work_order=selected_work_order,
                selection_reason=selection_reason,
                manifest=manifest,
                manifest_path=manifest_path,
                state_path=state_path,
                supervisor_state=supervisor_state,
            ),
        }

    def write_ralph_handoff(
        self,
        goal: str,
        subtasks: list[SubTask],
        *,
        output_dir: Path,
        source_ref: str | None = None,
        preferred_work_order_id: str | None = None,
        start_supervisor: bool = False,
        merge_policy: str = "manual_review_required",
        max_repair_attempts: int = 2,
    ) -> dict[str, Any]:
        """Persist a Ralph-ready handoff and optionally start the supervisor."""
        handoff = self.build_ralph_handoff(
            goal,
            subtasks,
            source_ref=source_ref,
            preferred_work_order_id=preferred_work_order_id,
        )
        manifest_payload = handoff.get("manifest")
        if not isinstance(manifest_payload, dict):
            return handoff

        from aragora.swarm.campaign import CampaignManifest, save_campaign_manifest

        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "campaign_manifest.yaml"
        save_campaign_manifest(manifest_path, CampaignManifest.from_dict(manifest_payload))

        supervisor_state: dict[str, Any] | None = None
        state_path: Path | None = None
        if start_supervisor:
            from aragora.ralph.supervisor import RalphSupervisor

            state_path = output_dir / "supervisor_state.yaml"
            supervisor = RalphSupervisor.start(
                manifest_path=manifest_path,
                state_path=state_path,
                repo_root=self._repo_path,
                merge_policy=merge_policy,
                max_repair_attempts=max(0, int(max_repair_attempts)),
            )
            supervisor_state = supervisor.status()

        handoff["manifest_path"] = str(manifest_path)
        if state_path is not None:
            handoff["state_path"] = str(state_path)
        handoff["receipt_metadata"] = self._ralph_receipt_metadata(
            work_order=next(
                (
                    work_order
                    for work_order in self.build_work_orders(subtasks)
                    if work_order.work_order_id == handoff["selection"].get("work_order_id")
                ),
                None,
            ),
            selection_reason=str(handoff["selection"].get("reason", "")).strip() or "unknown",
            manifest=CampaignManifest.from_dict(manifest_payload),
            manifest_path=manifest_path,
            state_path=state_path,
            supervisor_state=supervisor_state,
        )
        return handoff

    def build_decision_plan(
        self,
        goal: str,
        subtasks: list[SubTask],
        debate_result: Any | None = None,
        dissent: list[str] | None = None,
    ) -> Any:
        """Build a DecisionPlan from Nomic Loop output.

        Args:
            goal: The high-level goal.
            subtasks: Decomposed subtasks from TaskDecomposer.
            debate_result: Optional DebateResult from the debate phase.
                If None, a synthetic one is constructed.
            dissent: Optional dissenting views (used when debate_result
                is None to populate the risk register).

        Returns:
            A DecisionPlan ready for approval and execution.
        """
        from aragora.implement.types import ImplementPlan
        from aragora.pipeline.decision_plan.core import ApprovalMode
        from aragora.pipeline.decision_plan.factory import DecisionPlanFactory

        # Convert Nomic subtasks to ImplementTasks
        implement_tasks = [_subtask_to_implement_task(st, i + 1) for i, st in enumerate(subtasks)]

        # Resolve cross-task dependencies
        _resolve_dependencies(subtasks, implement_tasks)

        # Build the ImplementPlan
        design_text = f"Nomic Loop plan for: {goal}"
        design_hash = hashlib.sha256(design_text.encode()).hexdigest()
        implement_plan = ImplementPlan(
            design_hash=design_hash,
            tasks=implement_tasks,
        )

        # Use real debate result or build synthetic one
        result = debate_result
        if result is None:
            result = _build_synthetic_debate_result(goal, subtasks, dissent)

        # Create the DecisionPlan via the factory
        plan = DecisionPlanFactory.from_debate_result(
            result,
            budget_limit_usd=self._budget_limit_usd,
            approval_mode=ApprovalMode.NEVER,  # Self-improvement is automated
            repo_path=self._repo_path,
            implement_plan=implement_plan,
            metadata=self.build_plan_metadata(goal, subtasks),
        )

        logger.info(
            "Built DecisionPlan %s from %d Nomic subtasks (risks=%d, verifications=%d)",
            plan.id,
            len(subtasks),
            len(plan.risk_register.risks) if plan.risk_register else 0,
            len(plan.verification_plan.test_cases) if plan.verification_plan else 0,
        )

        return plan

    async def execute_via_pipeline(
        self,
        goal: str,
        subtasks: list[SubTask],
        debate_result: Any | None = None,
        dissent: list[str] | None = None,
        execution_mode: str | None = None,
    ) -> Any:
        """Build a DecisionPlan and execute it via PlanExecutor.

        This is the main entry point for routing Nomic Loop output through
        the production pipeline.

        Args:
            goal: The high-level goal.
            subtasks: Decomposed subtasks from TaskDecomposer.
            debate_result: Optional DebateResult from the debate phase.
            dissent: Optional dissenting views for risk analysis.
            execution_mode: Override the default execution mode.

        Returns:
            A PlanOutcome with execution results, receipt ID, and lessons.
        """
        from aragora.pipeline.executor import PlanExecutor
        from aragora.pipeline.decision_integrity_utils import execute_decision_plan_with_backbone

        plan = self.build_decision_plan(
            goal=goal,
            subtasks=subtasks,
            debate_result=debate_result,
            dissent=dissent,
        )
        plan_metadata = dict(getattr(plan, "metadata", {}) or {})
        for key in ("backbone_entrypoint", "backbone_run_id", "source_id", "source_surface"):
            plan_metadata.pop(key, None)
        plan_metadata["source_surface"] = "nomic_pipeline_bridge"
        plan_metadata["source_id"] = str(getattr(plan, "debate_id", "") or plan.id)
        plan.metadata = plan_metadata

        mode = execution_mode or self._execution_mode

        executor = PlanExecutor(
            execution_mode=mode,  # type: ignore[arg-type]
            repo_path=self._repo_path,
        )

        logger.info(
            "Executing DecisionPlan %s via PlanExecutor (mode=%s, tasks=%d)",
            plan.id,
            mode,
            len(plan.implement_plan.tasks) if plan.implement_plan else 0,
        )

        launch, outcome = await execute_decision_plan_with_backbone(
            plan,
            executor=executor,
            auth_context=None,
            execution_mode=mode,
            safety_mode=SafetyMode.AUTONOMOUS,
        )

        logger.info(
            "PlanExecutor completed: success=%s, tasks=%d/%d, receipt=%s, run_id=%s, execution_id=%s",
            outcome.success,
            outcome.tasks_completed,
            outcome.tasks_total,
            outcome.receipt_id or "none",
            launch.get("run_id"),
            launch.get("execution_id"),
        )

        return outcome

    async def execute_decomposition_via_pipeline(
        self,
        goal: str,
        decomposition: TaskDecomposition,
        debate_result: Any | None = None,
        dissent: list[str] | None = None,
        execution_mode: str | None = None,
    ) -> Any:
        """Convenience method: execute a full TaskDecomposition via pipeline.

        Args:
            goal: The high-level goal.
            decomposition: The TaskDecomposition from TaskDecomposer.
            debate_result: Optional DebateResult from debate phase.
            dissent: Optional dissenting views for risk analysis.
            execution_mode: Override the default execution mode.

        Returns:
            A PlanOutcome with execution results.
        """
        return await self.execute_via_pipeline(
            goal=goal,
            subtasks=decomposition.subtasks,
            debate_result=debate_result,
            dissent=dissent,
            execution_mode=execution_mode,
        )

    # -- UniversalGraph conversion (for /pipeline UI visualization) --------

    def cycle_result_to_ideas(self, cycle_result: OrchestrationResult) -> list[dict[str, Any]]:
        """Convert an OrchestrationResult into pipeline idea dicts.

        Extracts proposals from completed assignments and surfaces them as
        ideas suitable for the Ideas stage of the Idea-to-Execution Pipeline.

        Args:
            cycle_result: Result from AutonomousOrchestrator.execute_goal().

        Returns:
            List of idea dicts with keys: id, label, description, idea_type.
        """
        ideas: list[dict[str, Any]] = []

        # The top-level goal becomes the primary insight
        ideas.append(
            {
                "id": f"nomic-idea-{uuid.uuid4().hex[:8]}",
                "label": cycle_result.goal,
                "description": cycle_result.summary or cycle_result.goal,
                "idea_type": "insight",
            }
        )

        # Each assignment becomes a concept idea
        for assignment in cycle_result.assignments:
            subtask = assignment.subtask
            idea_type = "concept"
            if subtask.file_scope:
                idea_type = "evidence"  # Grounded in specific files

            ideas.append(
                {
                    "id": f"nomic-idea-{uuid.uuid4().hex[:8]}",
                    "label": subtask.title,
                    "description": subtask.description,
                    "idea_type": idea_type,
                }
            )

        return ideas

    def design_phase_to_goals(self, design_output: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert Nomic design phase output to goal dicts.

        Maps design decisions to SMART-style goals for the Goals stage
        of the pipeline.

        Args:
            design_output: Dictionary from the design phase, expected keys:
                - "goal": The high-level goal string.
                - "subtasks": List of SubTask-like dicts or SubTask objects.
                - "rationale": Optional design rationale.

        Returns:
            List of goal dicts with keys: id, label, description, goal_type,
            confidence.
        """
        goals: list[dict[str, Any]] = []

        # Primary goal from the design
        goal_text = design_output.get("goal", "")
        if goal_text:
            goals.append(
                {
                    "id": f"nomic-goal-{uuid.uuid4().hex[:8]}",
                    "label": goal_text,
                    "description": design_output.get("rationale", goal_text),
                    "goal_type": "goal",
                    "confidence": 0.8,
                }
            )

        # Each subtask becomes a milestone
        subtasks = design_output.get("subtasks", [])
        for st in subtasks:
            if isinstance(st, SubTask):
                title, desc, complexity = st.title, st.description, st.estimated_complexity
            else:
                title = st.get("title", "")
                desc = st.get("description", "")
                complexity = st.get("estimated_complexity", "medium")

            confidence_map = {"low": 0.9, "medium": 0.7, "high": 0.5}
            goals.append(
                {
                    "id": f"nomic-goal-{uuid.uuid4().hex[:8]}",
                    "label": title,
                    "description": desc,
                    "goal_type": "milestone",
                    "confidence": confidence_map.get(complexity, 0.7),
                }
            )

        return goals

    def create_pipeline_from_cycle(self, cycle_result: OrchestrationResult) -> UniversalGraph:
        """Convert an OrchestrationResult into a populated UniversalGraph.

        Produces a graph with:
        - IDEAS stage: one node per proposal/assignment from the cycle
        - GOALS stage: milestone nodes from completed assignments
        - ACTIONS stage: task nodes for each subtask with file scope
        - Cross-stage DERIVED_FROM edges linking goals to ideas, actions to goals

        Args:
            cycle_result: Result from AutonomousOrchestrator.execute_goal().

        Returns:
            A UniversalGraph ready for /pipeline visualization.
        """
        from aragora.canvas.stages import PipelineStage, StageEdgeType
        from aragora.pipeline.universal_node import UniversalEdge, UniversalGraph, UniversalNode

        graph = UniversalGraph(
            id=f"nomic-pipeline-{uuid.uuid4().hex[:8]}",
            name=f"Nomic: {cycle_result.goal[:60]}",
            metadata={
                "source": "nomic_loop",
                "goal": cycle_result.goal,
                "success": cycle_result.success,
                "duration_seconds": cycle_result.duration_seconds,
                "improvement_score": cycle_result.improvement_score,
            },
        )

        # Track node IDs for cross-stage edges
        idea_node_ids: list[str] = []
        goal_node_ids: list[str] = []

        # -- Stage 1: IDEAS (from proposals/assignments) --
        y_offset = 0.0
        for i, assignment in enumerate(cycle_result.assignments):
            subtask = assignment.subtask
            node_id = f"nomic-idea-{i}"
            idea_type = "concept"
            if subtask.file_scope:
                idea_type = "evidence"

            node = UniversalNode(
                id=node_id,
                stage=PipelineStage.IDEAS,
                node_subtype=idea_type,
                label=subtask.title,
                description=subtask.description,
                position_x=0.0,
                position_y=y_offset,
                confidence=0.75 if assignment.status == "completed" else 0.4,
                status="completed" if assignment.status == "completed" else "active",
                data={"agent_type": assignment.agent_type, "track": assignment.track.value},
            )
            graph.add_node(node)
            idea_node_ids.append(node_id)
            y_offset += 120.0

        # -- Stage 2: GOALS (milestones from completed assignments) --
        y_offset = 0.0
        for i, assignment in enumerate(cycle_result.assignments):
            if assignment.status != "completed":
                continue
            subtask = assignment.subtask
            node_id = f"nomic-goal-{i}"
            complexity_confidence = {"low": 0.9, "medium": 0.7, "high": 0.5}

            node = UniversalNode(
                id=node_id,
                stage=PipelineStage.GOALS,
                node_subtype="milestone",
                label=f"Complete: {subtask.title}",
                description=subtask.description,
                position_x=300.0,
                position_y=y_offset,
                confidence=complexity_confidence.get(subtask.estimated_complexity, 0.7),
                status="completed",
                parent_ids=[f"nomic-idea-{i}"],
                source_stage=PipelineStage.IDEAS,
            )
            graph.add_node(node)
            goal_node_ids.append(node_id)

            # Cross-stage edge: idea -> goal
            edge = UniversalEdge(
                id=f"nomic-edge-idea-goal-{i}",
                source_id=f"nomic-idea-{i}",
                target_id=node_id,
                edge_type=StageEdgeType.DERIVED_FROM,
                label="derived from",
            )
            graph.add_edge(edge)
            y_offset += 120.0

        # -- Stage 3: ACTIONS (tasks with file scope) --
        y_offset = 0.0
        action_idx = 0
        for i, assignment in enumerate(cycle_result.assignments):
            subtask = assignment.subtask
            if not subtask.file_scope:
                continue
            node_id = f"nomic-action-{action_idx}"

            node = UniversalNode(
                id=node_id,
                stage=PipelineStage.ACTIONS,
                node_subtype="task",
                label=subtask.title,
                description=f"Files: {', '.join(subtask.file_scope[:5])}",
                position_x=600.0,
                position_y=y_offset,
                confidence=0.8 if assignment.status == "completed" else 0.5,
                status="completed" if assignment.status == "completed" else "active",
                data={"files": subtask.file_scope, "complexity": subtask.estimated_complexity},
            )
            graph.add_node(node)

            # Cross-stage edge: goal -> action (if the goal exists)
            goal_id = f"nomic-goal-{i}"
            if goal_id in graph.nodes:
                edge = UniversalEdge(
                    id=f"nomic-edge-goal-action-{action_idx}",
                    source_id=goal_id,
                    target_id=node_id,
                    edge_type=StageEdgeType.IMPLEMENTS,
                    label="implements",
                )
                graph.add_edge(edge)

            y_offset += 120.0
            action_idx += 1

        # -- Intra-stage dependency edges --
        # Map subtask IDs to idea node IDs for dependency resolution
        subtask_to_node: dict[str, str] = {}
        for i, assignment in enumerate(cycle_result.assignments):
            subtask_to_node[assignment.subtask.id] = f"nomic-idea-{i}"

        for i, assignment in enumerate(cycle_result.assignments):
            for dep_id in assignment.subtask.dependencies:
                dep_node = subtask_to_node.get(dep_id)
                if dep_node and dep_node in graph.nodes:
                    edge = UniversalEdge(
                        id=f"nomic-edge-dep-{i}-{dep_id[:8]}",
                        source_id=dep_node,
                        target_id=f"nomic-idea-{i}",
                        edge_type=StageEdgeType.REQUIRES,
                        label="requires",
                    )
                    graph.add_edge(edge)

        logger.info(
            "Created UniversalGraph %s from cycle result: %d nodes, %d edges",
            graph.id,
            len(graph.nodes),
            len(graph.edges),
        )

        return graph
