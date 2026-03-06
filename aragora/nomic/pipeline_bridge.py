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
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from aragora.nomic.task_decomposer import SubTask, TaskDecomposition

if TYPE_CHECKING:
    from aragora.nomic.autonomous_orchestrator import OrchestrationResult
    from aragora.pipeline.universal_node import UniversalGraph

logger = logging.getLogger(__name__)


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
    estimated_complexity: str = "medium"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "pipeline_task_id": self.pipeline_task_id,
            "title": self.title,
            "description": self.description,
            "file_scope": list(self.file_scope),
            "dependency_ids": list(self.dependency_ids),
            "success_criteria": dict(self.success_criteria),
            "estimated_complexity": self.estimated_complexity,
            "metadata": dict(self.metadata),
        }


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
                    estimated_complexity=subtask.estimated_complexity,
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
        }

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

        plan = self.build_decision_plan(
            goal=goal,
            subtasks=subtasks,
            debate_result=debate_result,
            dissent=dissent,
        )

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

        outcome = await executor.execute(plan, execution_mode=mode)  # type: ignore[arg-type]

        logger.info(
            "PlanExecutor completed: success=%s, tasks=%d/%d, receipt=%s",
            outcome.success,
            outcome.tasks_completed,
            outcome.tasks_total,
            outcome.receipt_id or "none",
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
