"""Hierarchical Coordinator for Planner/Worker/Judge cycle.

Implements a structured plan-execute-judge loop where:
1. Planner decomposes the goal into tasks (via TaskDecomposer)
2. Workers execute tasks in parallel (via WorkflowEngine)
3. Judge reviews results via a mini Arena debate
4. On rejection: revision cycle replans only failed tasks

Reuses existing infrastructure:
- TaskDecomposer from aragora.nomic.task_decomposer
- AgentRouter/FeedbackLoop from aragora.nomic.autonomous_orchestrator
- WorkflowEngine from aragora.workflow.engine
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aragora.nomic.task_decomposer import (
    TaskDecomposer,
    TaskDecomposition,
    SubTask,
)
from aragora.workflow.engine import WorkflowEngine, get_workflow_engine

logger = logging.getLogger(__name__)


class CoordinationPhase(Enum):
    """Phases of the hierarchical coordination cycle."""

    PLANNING = "planning"
    DISPATCHING = "dispatching"
    EXECUTING = "executing"
    JUDGING = "judging"
    REVISING = "revising"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class CoordinatorConfig:
    """Configuration for the hierarchical coordinator."""

    # Planner settings
    use_debate_decomposition: bool = False
    max_plan_revisions: int = 2

    # Worker settings
    max_parallel_workers: int = 4
    worker_timeout_seconds: int = 300

    # Judge settings
    judge_agent: str = "claude"
    judge_rounds: int = 2
    quality_threshold: float = 0.6

    # Lifecycle
    max_cycles: int = 3
    enable_checkpointing: bool = False


@dataclass
class WorkerReport:
    """Report from a single worker execution."""

    assignment_id: str
    subtask_title: str
    success: bool
    output: dict[str, Any] | None = None
    duration_seconds: float = 0.0
    error: str | None = None


@dataclass
class JudgeVerdict:
    """Verdict from the judge phase."""

    approved: bool
    confidence: float
    feedback: str = ""
    revision_instructions: list[str] = field(default_factory=list)
    partial_approvals: dict[str, bool] = field(default_factory=dict)


@dataclass
class HierarchicalResult:
    """Result of a hierarchical coordination run."""

    goal: str
    phase: CoordinationPhase
    cycles_used: int
    worker_reports: list[WorkerReport]
    verdict: JudgeVerdict | None
    success: bool
    duration_seconds: float = 0.0
    total_cost: float = 0.0


class HierarchicalCoordinator:
    """Coordinates a Planner/Worker/Judge cycle for goal execution.

    The coordination loop:
    1. Plan: Decompose goal into subtasks via TaskDecomposer
    2. Execute: Run subtasks in parallel via WorkflowEngine
    3. Judge: Evaluate results (Arena debate or heuristic fallback)
    4. Revise: On rejection, replan only failed tasks and repeat

    Example::

        coordinator = HierarchicalCoordinator()
        result = await coordinator.coordinate("Improve test coverage")
        if result.success:
            print(f"Completed in {result.cycles_used} cycles")
    """

    def __init__(
        self,
        config: CoordinatorConfig | None = None,
        task_decomposer: TaskDecomposer | None = None,
        workflow_engine: WorkflowEngine | None = None,
    ):
        self.config = config or CoordinatorConfig()
        self.task_decomposer = task_decomposer or TaskDecomposer()
        self.workflow_engine = workflow_engine or get_workflow_engine()
        self._phase = CoordinationPhase.PLANNING
        self._cycle = 0

    @property
    def phase(self) -> CoordinationPhase:
        """Current coordination phase."""
        return self._phase

    @property
    def cycle(self) -> int:
        """Current cycle number."""
        return self._cycle

    async def coordinate(
        self,
        goal: str,
        tracks: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> HierarchicalResult:
        """Main coordination loop: plan -> execute -> judge -> revise.

        Args:
            goal: High-level goal to accomplish.
            tracks: Optional track names to focus decomposition.
            context: Additional context for planning.

        Returns:
            HierarchicalResult with final status and all worker reports.
        """
        start_time = time.time()
        context = context or {}
        all_reports: list[WorkerReport] = []
        verdict: JudgeVerdict | None = None
        prior_verdict: JudgeVerdict | None = None

        logger.info(
            "hierarchical_coordination_started goal=%s tracks=%s max_cycles=%d",
            goal[:80],
            tracks,
            self.config.max_cycles,
        )

        for cycle in range(self.config.max_cycles):
            self._cycle = cycle + 1

            # Plan
            self._phase = CoordinationPhase.PLANNING
            decomposition = await self._plan(goal, tracks, prior_verdict)

            if not decomposition.subtasks:
                logger.info("hierarchical_no_subtasks cycle=%d", self._cycle)
                self._phase = CoordinationPhase.COMPLETED
                return HierarchicalResult(
                    goal=goal,
                    phase=CoordinationPhase.COMPLETED,
                    cycles_used=self._cycle,
                    worker_reports=all_reports,
                    verdict=None,
                    success=True,
                    duration_seconds=time.time() - start_time,
                )

            # Execute
            self._phase = CoordinationPhase.DISPATCHING
            reports = await self._dispatch_and_execute(decomposition)
            all_reports.extend(reports)

            # Judge
            self._phase = CoordinationPhase.JUDGING
            verdict = await self._judge(goal, decomposition, reports)

            if verdict.approved:
                logger.info(
                    "hierarchical_approved cycle=%d confidence=%.2f",
                    self._cycle,
                    verdict.confidence,
                )
                self._phase = CoordinationPhase.COMPLETED
                return HierarchicalResult(
                    goal=goal,
                    phase=CoordinationPhase.COMPLETED,
                    cycles_used=self._cycle,
                    worker_reports=all_reports,
                    verdict=verdict,
                    success=True,
                    duration_seconds=time.time() - start_time,
                )

            # Rejected: prepare for revision
            logger.info(
                "hierarchical_rejected cycle=%d feedback=%s",
                self._cycle,
                verdict.feedback[:100],
            )
            self._phase = CoordinationPhase.REVISING
            prior_verdict = verdict

        # Max cycles exhausted
        logger.warning(
            "hierarchical_max_cycles_reached max_cycles=%d",
            self.config.max_cycles,
        )
        self._phase = CoordinationPhase.FAILED
        return HierarchicalResult(
            goal=goal,
            phase=CoordinationPhase.FAILED,
            cycles_used=self.config.max_cycles,
            worker_reports=all_reports,
            verdict=verdict,
            success=False,
            duration_seconds=time.time() - start_time,
        )

    # =========================================================================
    # Plan Phase
    # =========================================================================

    async def _plan(
        self,
        goal: str,
        tracks: list[str] | None,
        prior_verdict: JudgeVerdict | None = None,
    ) -> TaskDecomposition:
        """Decompose goal into subtasks. On revision, only replan rejected tasks."""
        if prior_verdict is not None:
            return self._replan_rejected(goal, prior_verdict)

        enriched_goal = goal
        if tracks:
            enriched_goal = f"{goal}\n\nFocus tracks: {', '.join(tracks)}"

        if self.config.use_debate_decomposition:
            return await self.task_decomposer.analyze_with_debate(enriched_goal)

        return self.task_decomposer.analyze(enriched_goal)

    def _replan_rejected(
        self,
        goal: str,
        verdict: JudgeVerdict,
    ) -> TaskDecomposition:
        """Replan only the rejected tasks from the prior cycle."""
        rejected_ids = [
            task_id for task_id, approved in verdict.partial_approvals.items() if not approved
        ]

        # Build a focused goal from revision instructions
        revision_context = verdict.feedback
        if verdict.revision_instructions:
            revision_context += "\nRevision instructions:\n" + "\n".join(
                f"- {inst}" for inst in verdict.revision_instructions
            )

        focused_goal = f"{goal}\n\nRevise the following areas:\n{revision_context}"

        decomposition = self.task_decomposer.analyze(focused_goal)

        # Tag subtasks with rejected IDs for traceability
        for i, subtask in enumerate(decomposition.subtasks):
            if i < len(rejected_ids):
                subtask.id = f"revision_{rejected_ids[i]}"

        return decomposition

    # =========================================================================
    # Execute Phase
    # =========================================================================

    async def _dispatch_and_execute(
        self,
        decomposition: TaskDecomposition,
    ) -> list[WorkerReport]:
        """Create assignments and execute subtasks in parallel."""
        self._phase = CoordinationPhase.EXECUTING
        reports: list[WorkerReport] = []
        semaphore = asyncio.Semaphore(self.config.max_parallel_workers)

        async def run_worker(subtask: SubTask) -> WorkerReport:
            async with semaphore:
                return await self._execute_subtask(subtask)

        tasks = [run_worker(st) for st in decomposition.subtasks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                subtask = decomposition.subtasks[i]
                reports.append(
                    WorkerReport(
                        assignment_id=f"assign_{subtask.id}",
                        subtask_title=subtask.title,
                        success=False,
                        error=str(result),
                    )
                )
            else:
                reports.append(result)

        return reports

    async def _execute_subtask(self, subtask: SubTask) -> WorkerReport:
        """Execute a single subtask via the workflow engine."""
        assignment_id = f"assign_{subtask.id}"
        start_time = time.time()

        try:
            from aragora.workflow.types import WorkflowDefinition, StepDefinition

            workflow = WorkflowDefinition(
                id=f"hc_{subtask.id}_{uuid.uuid4().hex[:8]}",
                name=f"Execute: {subtask.title}",
                description=subtask.description,
                steps=[
                    StepDefinition(
                        id="implement",
                        name="Implement",
                        step_type="implementation",
                        config={
                            "task_id": subtask.id,
                            "description": subtask.description,
                            "files": subtask.file_scope,
                            "complexity": subtask.estimated_complexity,
                        },
                        timeout_seconds=self.config.worker_timeout_seconds,
                    ),
                ],
                entry_step="implement",
            )

            result = await asyncio.wait_for(
                self.workflow_engine.execute(workflow),
                timeout=self.config.worker_timeout_seconds,
            )

            duration = time.time() - start_time
            return WorkerReport(
                assignment_id=assignment_id,
                subtask_title=subtask.title,
                success=result.success,
                output={"workflow_result": result.final_output} if result.success else None,
                duration_seconds=duration,
                error=result.error,
            )

        except asyncio.TimeoutError:
            return WorkerReport(
                assignment_id=assignment_id,
                subtask_title=subtask.title,
                success=False,
                duration_seconds=time.time() - start_time,
                error=f"Worker timed out after {self.config.worker_timeout_seconds}s",
            )
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("Worker assignment %s failed: %s", assignment_id, e)
            return WorkerReport(
                assignment_id=assignment_id,
                subtask_title=subtask.title,
                success=False,
                duration_seconds=time.time() - start_time,
                error=f"Worker execution failed: {type(e).__name__}",
            )

    # =========================================================================
    # Judge Phase
    # =========================================================================

    async def _judge(
        self,
        goal: str,
        decomposition: TaskDecomposition,
        reports: list[WorkerReport],
    ) -> JudgeVerdict:
        """Judge results. Try Arena debate; fallback to heuristic scoring."""
        try:
            from aragora.debate.orchestrator import Arena
            from aragora.core import Environment
            from aragora.debate.protocol import DebateProtocol

            prompt = self._build_judge_prompt(goal, decomposition, reports)

            env = Environment(
                task=prompt,
                max_rounds=self.config.judge_rounds,
                require_consensus=True,
                consensus_threshold=self.config.quality_threshold,
            )

            protocol = DebateProtocol(
                rounds=self.config.judge_rounds,
                consensus="majority",
            )

            # Get judge agent
            from aragora.config.secrets import get_secret

            anthropic_key = get_secret("ANTHROPIC_API_KEY")
            if not anthropic_key:
                logger.debug("No API key for Arena judge, using heuristic")
                return self._heuristic_judge(goal, reports)

            from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

            agents: list[Any] = [
                AnthropicAPIAgent(
                    name="judge-1",
                    model="claude-opus-5",
                    api_key=anthropic_key,
                ),
                AnthropicAPIAgent(
                    name="judge-2",
                    model="claude-opus-5",
                    api_key=anthropic_key,
                ),
            ]

            arena = Arena(env, agents, protocol)
            result = await arena.run()

            return self._parse_arena_verdict(result, reports)

        except ImportError:
            logger.debug("Arena not available for judging, using heuristic")
            return self._heuristic_judge(goal, reports)
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("Arena judge failed: %s, using heuristic", e)
            return self._heuristic_judge(goal, reports)

    def _heuristic_judge(
        self,
        goal: str,
        reports: list[WorkerReport],
    ) -> JudgeVerdict:
        """Fallback judge when Arena is not available."""
        if not reports:
            return JudgeVerdict(
                approved=False,
                confidence=0.0,
                feedback="No worker reports to evaluate",
            )

        success_count = sum(1 for r in reports if r.success)
        success_rate = success_count / len(reports)
        approved = success_rate >= self.config.quality_threshold

        # Build partial approvals
        partial_approvals: dict[str, bool] = {}
        revision_instructions: list[str] = []
        for report in reports:
            task_id = report.assignment_id.replace("assign_", "")
            partial_approvals[task_id] = report.success
            if not report.success and report.error:
                revision_instructions.append(f"Fix {report.subtask_title}: {report.error}")

        feedback = f"Heuristic: {success_rate:.0%} success rate ({success_count}/{len(reports)})"

        return JudgeVerdict(
            approved=approved,
            confidence=success_rate,
            feedback=feedback,
            revision_instructions=revision_instructions,
            partial_approvals=partial_approvals,
        )

    def _build_judge_prompt(
        self,
        goal: str,
        decomposition: TaskDecomposition,
        reports: list[WorkerReport],
    ) -> str:
        """Build prompt for judge debate."""
        lines = [
            "Evaluate whether the following goal has been satisfactorily achieved:\n",
            f"GOAL: {goal}\n",
            f"SUBTASKS ({len(decomposition.subtasks)}):",
        ]

        for st in decomposition.subtasks:
            lines.append(f"  - {st.title}: {st.description}")

        lines.append(f"\nWORKER REPORTS ({len(reports)}):")
        for report in reports:
            status = "SUCCESS" if report.success else "FAILED"
            lines.append(f"  - [{status}] {report.subtask_title}")
            if report.error:
                lines.append(f"    Error: {report.error}")
            lines.append(f"    Duration: {report.duration_seconds:.1f}s")

        lines.append("\nProvide your verdict: APPROVE or REJECT with reasoning.")

        return "\n".join(lines)

    def _parse_arena_verdict(
        self,
        arena_result: Any,
        reports: list[WorkerReport],
    ) -> JudgeVerdict:
        """Parse Arena debate result into a JudgeVerdict."""
        final_answer = getattr(arena_result, "final_answer", "") or ""
        confidence = getattr(arena_result, "confidence", 0.5)
        answer_lower = final_answer.lower()

        approved = "approve" in answer_lower and "reject" not in answer_lower

        # Build partial approvals from reports
        partial_approvals: dict[str, bool] = {}
        for report in reports:
            task_id = report.assignment_id.replace("assign_", "")
            partial_approvals[task_id] = report.success

        revision_instructions: list[str] = []
        if not approved:
            for report in reports:
                if not report.success and report.error:
                    revision_instructions.append(f"Fix {report.subtask_title}: {report.error}")

        return JudgeVerdict(
            approved=approved,
            confidence=confidence,
            feedback=final_answer[:500],
            revision_instructions=revision_instructions,
            partial_approvals=partial_approvals,
        )
