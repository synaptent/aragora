"""
Autonomous Development Orchestrator.

Coordinates heterogeneous agents to develop specs, implement features,
and maintain the Aragora codebase with minimal human intervention.

This module ties together:
- TaskDecomposer: Break high-level goals into subtasks
- WorkflowEngine: Execute multi-step workflows with checkpoints
- NomicLoop: Run improvement cycles on individual tasks
- Gates: Approval checkpoints for safety

Usage:
    from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

    orchestrator = AutonomousOrchestrator()

    # High-level goal with track hints
    result = await orchestrator.execute_goal(
        goal="Maximize utility for SME SMB users",
        tracks=["sme", "qa"],
        max_cycles=5,
    )
"""

from __future__ import annotations

import asyncio
import inspect
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Callable

from aragora.nomic.task_decomposer import (
    TaskDecomposer,
    TaskDecomposition,
    SubTask,
    DecomposerConfig,
)
from aragora.workflow.engine import WorkflowEngine, get_workflow_engine
from aragora.workflow.types import (
    WorkflowDefinition,
    StepDefinition,
)
from aragora.observability import get_logger

# Re-export extracted types for backward compatibility
from aragora.nomic.types import (  # noqa: F401
    AgentAssignment,
    AGENTS_WITH_CODING_HARNESS,
    BudgetExceededError,
    DEFAULT_TRACK_CONFIGS,
    HierarchyConfig,
    KILOCODE_PROVIDER_MAPPING,
    OrchestrationResult,
    Track,
    TrackConfig,
)
from aragora.nomic.agent_router import AgentRouter  # noqa: F401
from aragora.nomic.feedback_loop import FeedbackLoop  # noqa: F401

logger = get_logger(__name__)

_UNSET = object()  # sentinel: distinguish "not provided" from explicit None


class AutonomousOrchestrator:
    """
    Orchestrates autonomous development across multiple agents and tracks.

    Coordinates:
    - Goal decomposition into track-aligned subtasks
    - Agent assignment based on domain expertise
    - Parallel execution with conflict detection
    - Feedback loops for failed tasks
    - Human approval checkpoints
    """

    def __init__(
        self,
        aragora_path: Path | None = None,
        track_configs: dict[Track, TrackConfig] | None = None,
        workflow_engine: WorkflowEngine | None = None,
        task_decomposer: TaskDecomposer | None = None,
        require_human_approval: bool = True,
        max_parallel_tasks: int = 4,
        on_checkpoint: Callable[[str, dict[str, Any]], None] | None = None,
        use_debate_decomposition: bool = False,
        enable_curriculum: bool = True,
        curriculum_config: Any | None = None,
        branch_coordinator: Any = _UNSET,
        hierarchy: HierarchyConfig | None = None,
        hierarchical_coordinator: Any | None = None,
        enable_gauntlet_gate: bool = False,
        use_decision_plan: bool = False,
        enable_convoy_tracking: bool = False,
        workspace_manager: Any | None = None,
        agent_fabric: Any | None = None,
        use_harness: bool = False,
        event_emitter: Any | None = None,
        enable_outcome_tracking: bool = False,
        outcome_tracker: Any | None = None,
        enable_metrics: bool = False,
        metrics_collector: Any | None = None,
        enable_preflight: bool = False,
        enable_stuck_detection: bool = False,
        stuck_detector: Any | None = None,
        enable_cost_forecast: bool = False,
        cost_forecaster: Any | None = None,
        cost_alert_callback: Callable[[Any], None] | None = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            aragora_path: Path to the aragora project
            track_configs: Custom track configurations
            workflow_engine: Custom workflow engine
            task_decomposer: Custom task decomposer
            require_human_approval: Whether to require approval at gates
            max_parallel_tasks: Maximum concurrent tasks across all tracks
            on_checkpoint: Callback for checkpoint events
            use_debate_decomposition: Use multi-agent debate for goal decomposition
                (slower but better for abstract goals)
            enable_curriculum: Enable SOAR curriculum for failed tasks
            curriculum_config: Optional curriculum configuration
            branch_coordinator: Optional BranchCoordinator for worktree isolation
            hierarchy: Optional Planner/Worker/Judge hierarchy configuration
            hierarchical_coordinator: Optional HierarchicalCoordinator for
                plan-execute-judge cycle delegation
            enable_gauntlet_gate: Insert adversarial gauntlet step between
                design and implement phases
            use_decision_plan: Use DecisionPlanFactory to generate risk-aware
                workflows from debate results (falls back to standard workflow)
            enable_convoy_tracking: Track orchestration lifecycle with
                Convoy/Bead persistence for crash recovery
            workspace_manager: Optional WorkspaceManager for convoy/bead tracking
            agent_fabric: Optional AgentFabric for enhanced scheduling,
                budget tracking, and inter-agent messaging
            event_emitter: Optional event emitter for IMPROVEMENT_CYCLE_* events
            enable_outcome_tracking: Run debate quality benchmarks before/after
                execution to detect silent regressions
            outcome_tracker: Optional NomicOutcomeTracker instance. Created
                automatically when enable_outcome_tracking is True and no
                tracker is provided.
            enable_metrics: Collect test/lint/size metrics before and after
                execution to objectively measure improvement
            metrics_collector: Optional MetricsCollector instance. Created
                automatically when enable_metrics is True and no collector
                is provided.
            enable_preflight: Run preflight health checks (API key validation,
                circuit breaker state, agent availability) before execution
                to fail fast instead of wasting budget on doomed runs.
            enable_stuck_detection: Monitor running tasks for stalls during
                execution and trigger automatic recovery (reassign, escalate,
                or cancel) based on configurable time thresholds.
            stuck_detector: Optional StuckDetector instance. Created
                automatically when enable_stuck_detection is True and no
                detector is provided.
            enable_cost_forecast: Run pre-execution cost estimation and
                mid-run budget monitoring. Warns when projected spend
                approaches or exceeds the budget limit.
            cost_forecaster: Optional NomicCostForecaster instance. Created
                automatically when enable_cost_forecast is True and no
                forecaster is provided.
            cost_alert_callback: Optional callback invoked with a
                BudgetCheckResult whenever a mid-run budget check returns
                warning or critical status.
        """
        self.aragora_path = aragora_path or Path.cwd()
        self.track_configs = track_configs or DEFAULT_TRACK_CONFIGS
        self.branch_coordinator = None if branch_coordinator is _UNSET else branch_coordinator
        self._branch_coordinator_explicit = branch_coordinator is not _UNSET
        self.agent_fabric = agent_fabric
        self.use_harness = use_harness
        self.workflow_engine = workflow_engine or get_workflow_engine()
        self.task_decomposer = task_decomposer or TaskDecomposer(
            config=DecomposerConfig(complexity_threshold=4)
        )
        self.require_human_approval = require_human_approval
        self.max_parallel_tasks = max_parallel_tasks
        self.on_checkpoint = on_checkpoint
        self.use_debate_decomposition = use_debate_decomposition
        self.enable_gauntlet_gate = enable_gauntlet_gate
        self.use_decision_plan = use_decision_plan
        self.enable_convoy_tracking = enable_convoy_tracking
        self.workspace_manager = workspace_manager
        self.event_emitter = event_emitter

        # Self-correction engine for cross-cycle pattern analysis
        self._self_correction = None
        try:
            from aragora.nomic.self_correction import SelfCorrectionEngine

            self._self_correction = SelfCorrectionEngine()
        except ImportError:
            pass

        self.hierarchy = hierarchy or HierarchyConfig()
        self.hierarchical_coordinator = hierarchical_coordinator
        self.router = AgentRouter(self.track_configs)
        self.feedback_loop = FeedbackLoop(repo_path=self.aragora_path)
        if enable_curriculum:
            try:
                from aragora.nomic.curriculum.integration import CurriculumAwareFeedbackLoop

                self.feedback_loop = CurriculumAwareFeedbackLoop(  # type: ignore[assignment]
                    max_iterations=self.feedback_loop.max_iterations,
                    config=curriculum_config,
                )
                logger.info("SOAR curriculum enabled for autonomous orchestrator")
            except (ImportError, RuntimeError) as e:
                logger.debug("SOAR curriculum unavailable: %s" % e)

        # Concurrency semaphore for parallel task execution
        self._semaphore = asyncio.Semaphore(max_parallel_tasks)

        # File-based approval gate
        self._auto_approve = not require_human_approval
        self._approval_gate_dir = self.aragora_path / ".aragora_beads" / "approval_gates"

        # Budget enforcement
        self.budget_limit: float | None = None
        self._total_cost_usd: float = 0.0

        # State
        self._active_assignments: list[AgentAssignment] = []
        self._completed_assignments: list[AgentAssignment] = []
        self._orchestration_id: str | None = None
        # Outcome tracking: debate quality regression detection
        self.enable_outcome_tracking = enable_outcome_tracking
        self._outcome_tracker = outcome_tracker
        if enable_outcome_tracking and outcome_tracker is None:
            try:
                from aragora.nomic.outcome_tracker import NomicOutcomeTracker

                self._outcome_tracker = NomicOutcomeTracker()
            except ImportError:
                logger.debug("Outcome tracker unavailable")

        # Preflight health checks before execution
        self.enable_preflight = enable_preflight

        # Metrics collection for objective improvement measurement
        self.enable_metrics = enable_metrics
        self._metrics_collector = metrics_collector
        if enable_metrics and metrics_collector is None:
            try:
                from aragora.nomic.metrics_collector import MetricsCollector

                self._metrics_collector = MetricsCollector()
            except ImportError:
                logger.debug("MetricsCollector unavailable")

        # Stuck detection for hung tasks
        self.enable_stuck_detection = enable_stuck_detection
        self._stuck_detector = stuck_detector
        if enable_stuck_detection and stuck_detector is None:
            try:
                from aragora.nomic.stuck_detector import StuckDetector

                self._stuck_detector = StuckDetector()
            except ImportError:
                logger.debug("StuckDetector unavailable")

        # Cost forecasting — initialized after _cycle_telemetry (see below)
        self.enable_cost_forecast = enable_cost_forecast
        self._cost_forecaster = cost_forecaster
        self._cost_alert_callback = cost_alert_callback

        # Convoy/bead IDs for tracking (populated when convoy tracking enabled)
        self._convoy_id: str | None = None
        self._bead_ids: dict[str, str] = {}  # subtask_id -> bead_id

        # Evolution audit: tracks agent prompt modifications for safety audit trail
        self._evolution_audit = None
        try:
            from aragora.nomic.evolution_audit import EvolutionAudit

            self._evolution_audit = EvolutionAudit(base_path=self.aragora_path)
        except ImportError:
            pass

        # --- Production instrumentation ---
        # Cycle telemetry: records per-cycle metrics for dashboards and stopping rules
        self._cycle_telemetry = None
        try:
            from aragora.nomic.cycle_telemetry import CycleTelemetryCollector

            self._cycle_telemetry = CycleTelemetryCollector()
        except ImportError:
            pass

        # Stopping rules: evaluated before each cycle to decide whether to halt
        self._stopping_engine = None
        try:
            from aragora.nomic.stopping_rules import StoppingRuleEngine

            self._stopping_engine = StoppingRuleEngine()
        except ImportError:
            pass

        # Goal proposer: data-driven goal generation when no explicit goal given
        self._goal_proposer = None
        try:
            from aragora.nomic.goal_proposer import GoalProposer

            self._goal_proposer = GoalProposer(
                telemetry=self._cycle_telemetry,
            )
        except ImportError:
            pass

        # Cost forecaster auto-init (after _cycle_telemetry is available)
        if self.enable_cost_forecast and self._cost_forecaster is None:
            try:
                from aragora.nomic.cost_forecast import NomicCostForecaster

                self._cost_forecaster = NomicCostForecaster(
                    telemetry=self._cycle_telemetry,
                )
            except ImportError:
                logger.debug("NomicCostForecaster unavailable")

        # KM feedback bridge: cross-cycle learning via Knowledge Mound
        self._km_feedback_bridge = None
        try:
            from aragora.nomic.km_feedback_bridge import KMFeedbackBridge

            self._km_feedback_bridge = KMFeedbackBridge()
        except ImportError:
            pass

        # ExecutionBridge: structured instruction generation + KM result ingestion
        self._execution_bridge: Any | None = None
        try:
            from aragora.nomic.execution_bridge import ExecutionBridge

            self._execution_bridge = ExecutionBridge(
                enable_km_ingestion=True,
                enable_verification=True,
            )
        except ImportError:
            pass

        # DebugLoop: test-failure-retry cycle for agent execution
        self._debug_loop: Any | None = None
        try:
            from aragora.nomic.debug_loop import DebugLoop, DebugLoopConfig

            self._debug_loop = DebugLoop(config=DebugLoopConfig(max_retries=3))
        except ImportError:
            pass

        # Default to BranchCoordinator for worktree isolation if not explicitly set
        if self.branch_coordinator is None and not self._branch_coordinator_explicit:
            try:
                from aragora.nomic.branch_coordinator import (
                    BranchCoordinator,
                    BranchCoordinatorConfig,
                )

                self.branch_coordinator = BranchCoordinator(
                    repo_path=self.aragora_path,
                    config=BranchCoordinatorConfig(
                        base_branch="main",
                        auto_merge_safe=True,
                        require_tests_pass=True,
                        use_worktrees=True,
                    ),
                )
            except (ImportError, subprocess.SubprocessError, OSError):
                pass

    async def _log_prompt_change(
        self,
        agent: str,
        field: str,
        before: str,
        after: str,
        reason: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log an agent prompt or configuration modification to the evolution audit trail.

        This should be called whenever the orchestrator autonomously modifies
        agent prompts or configuration so that every change is auditable.

        Args:
            agent: Agent name whose prompt/config was changed.
            field: The specific field that changed (e.g. "system_prompt").
            before: Original value.
            after: New value.
            reason: Human-readable rationale for the change.
            extra: Optional additional metadata.
        """
        if self._evolution_audit is None:
            logger.debug("_log_prompt_change: evolution audit not available, skipping")
            return
        try:
            await self._evolution_audit.log_modification(
                agent=agent,
                field=field,
                before=before,
                after=after,
                reason=reason,
                extra=extra,
            )
            logger.info(
                "evolution_audit agent=%s field=%s reason=%s",
                agent,
                field,
                reason[:80],
            )
        except (OSError, RuntimeError, AttributeError) as exc:
            logger.warning("Failed to log prompt change to evolution audit: %s", exc)

    def assert_production_gate(self) -> None:
        """Assert that the Nomic Loop production gate is enabled.

        This is an explicit opt-in safety control. The Nomic Loop can autonomously
        modify agent prompts and code. It must not run in production unless
        the operator has consciously opted in by setting ENABLE_NOMIC_LOOP=true.

        Raises:
            RuntimeError: If ENABLE_NOMIC_LOOP is not set to a truthy value.
        """
        import os

        value = os.environ.get("ENABLE_NOMIC_LOOP", "").strip().lower()
        if value not in ("true", "1", "yes"):
            raise RuntimeError(
                "Nomic Loop production gate is OFF. "
                "Set ENABLE_NOMIC_LOOP=true to enable autonomous self-improvement. "
                "This is an explicit opt-in safety control."
            )

    async def execute_goal(
        self,
        goal: str,
        tracks: list[str] | None = None,
        max_cycles: int = 5,
        context: dict[str, Any] | None = None,
    ) -> OrchestrationResult:
        """
        Execute a high-level goal by decomposing and orchestrating subtasks.

        Args:
            goal: High-level goal description
            tracks: Optional list of track names to focus on
            max_cycles: Maximum improvement cycles per subtask
            context: Additional context for the orchestration

        Returns:
            OrchestrationResult with completion status
        """
        self.assert_production_gate()

        self._orchestration_id = f"orch_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now(timezone.utc)
        context = context or {}

        logger.info(
            "orchestration_started",
            orchestration_id=self._orchestration_id,
            goal=goal[:100],
            tracks=tracks,
        )

        self._checkpoint("started", {"goal": goal, "tracks": tracks})
        self._emit_improvement_event(
            "IMPROVEMENT_CYCLE_START",
            {
                "goal": goal[:200],
                "tracks": tracks or [],
            },
        )

        # Step 0: Preflight health check — validate environment before spending budget
        if self.enable_preflight:
            try:
                from aragora.nomic.preflight import PreflightHealthCheck

                preflight = PreflightHealthCheck(min_required_agents=1)
                preflight_result = await preflight.run(timeout=10.0)
                if not preflight_result.passed:
                    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                    issues = "; ".join(preflight_result.blocking_issues)
                    logger.warning("preflight_failed issues=%s", issues)
                    return OrchestrationResult(
                        goal=goal,
                        total_subtasks=0,
                        completed_subtasks=0,
                        failed_subtasks=0,
                        skipped_subtasks=0,
                        assignments=[],
                        duration_seconds=duration,
                        success=False,
                        error=f"Preflight check failed: {issues}",
                    )
                if preflight_result.warnings:
                    for w in preflight_result.warnings:
                        logger.info("preflight_warning: %s", w)
            except ImportError:
                pass
            except (RuntimeError, OSError, ValueError, asyncio.TimeoutError) as e:
                logger.debug("preflight_check_skipped: %s", e)

        # Step 0b: Check stopping rules before spending budget
        if self._stopping_engine is not None and self._cycle_telemetry is not None:
            try:
                from aragora.nomic.stopping_rules import StoppingConfig

                stop_config = StoppingConfig(
                    budget_limit=self.budget_limit or 0,
                )
                should_stop, stop_reason = self._stopping_engine.should_stop(
                    telemetry=self._cycle_telemetry,
                    config=stop_config,
                    goal_proposer=self._goal_proposer,
                    start_time=start_time.timestamp(),
                )
                if should_stop:
                    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                    logger.info("stopping_rule_halted reason=%s", stop_reason)
                    return OrchestrationResult(
                        goal=goal,
                        total_subtasks=0,
                        completed_subtasks=0,
                        failed_subtasks=0,
                        skipped_subtasks=0,
                        assignments=[],
                        duration_seconds=duration,
                        success=False,
                        error=f"Stopped: {stop_reason}",
                    )
            except ImportError:
                pass
            except (RuntimeError, OSError, ValueError) as e:
                logger.debug("stopping_rule_check_skipped: %s", e)

        # Delegate to HierarchicalCoordinator if provided
        if self.hierarchical_coordinator is not None:
            h_result = await self.hierarchical_coordinator.coordinate(
                goal=goal,
                tracks=tracks,
                context=context,
            )
            return self._hierarchical_to_orchestration_result(h_result, goal, start_time)

        try:
            # Step 1: Decompose the goal
            decomposition = await self._decompose_goal(goal, tracks)
            self._checkpoint("decomposed", {"subtask_count": len(decomposition.subtasks)})

            if not decomposition.subtasks:
                return OrchestrationResult(
                    goal=goal,
                    total_subtasks=0,
                    completed_subtasks=0,
                    failed_subtasks=0,
                    skipped_subtasks=0,
                    assignments=[],
                    duration_seconds=0,
                    success=True,
                    summary="Goal decomposed to zero subtasks (may be trivial)",
                )

            # Step 2: Create assignments
            assignments = self._create_assignments(decomposition, tracks)
            self._checkpoint("assigned", {"assignment_count": len(assignments)})

            # Step 2b: Create convoy for tracking if enabled
            if self.enable_convoy_tracking:
                await self._create_convoy_for_goal(goal, assignments)

            # Step 2c: Pre-run cost forecast
            if self.enable_cost_forecast and self._cost_forecaster is not None:
                try:
                    track_names = [a.track.value for a in assignments]
                    cost_estimate = self._cost_forecaster.estimate_run_cost(
                        subtask_count=len(assignments),
                        tracks=track_names,
                        max_cycles=max_cycles,
                        budget_limit=self.budget_limit,
                    )
                    logger.info(
                        "cost_forecast_prerun estimated=%.2f budget=%.2f confidence=%.2f",
                        cost_estimate.estimated_total_usd,
                        self.budget_limit or 0.0,
                        cost_estimate.confidence,
                    )
                    if cost_estimate.will_exceed_budget and cost_estimate.warning_message:
                        logger.warning(
                            "cost_forecast_will_exceed: %s",
                            cost_estimate.warning_message,
                        )
                    self._checkpoint(
                        "cost_forecast",
                        {
                            "estimated_total_usd": cost_estimate.estimated_total_usd,
                            "will_exceed_budget": cost_estimate.will_exceed_budget,
                            "confidence": cost_estimate.confidence,
                        },
                    )
                except (RuntimeError, OSError, ValueError, TypeError) as e:
                    logger.debug("cost_forecast_prerun_failed: %s", e)

            # Step 2d: Capture outcome baseline if tracking enabled
            _outcome_baseline = None
            if self.enable_outcome_tracking and self._outcome_tracker is not None:
                try:
                    _outcome_baseline = await self._outcome_tracker.capture_baseline()
                except (
                    RuntimeError,
                    OSError,
                    ValueError,
                    ConnectionError,
                    asyncio.TimeoutError,
                ) as e:
                    logger.debug("outcome_baseline_capture_failed: %s", e)

            # Step 2d: Collect metrics baseline for objective improvement measurement
            _metrics_baseline = None
            if self.enable_metrics and self._metrics_collector is not None:
                try:
                    # Scope metrics to the files touched by all subtasks
                    file_scope = []
                    for a in assignments:
                        file_scope.extend(a.subtask.file_scope or [])
                    _metrics_baseline = await self._metrics_collector.collect_baseline(
                        goal,
                        file_scope=file_scope or None,
                    )
                except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as e:
                    logger.debug("metrics_baseline_collection_failed: %s", e)

            # Step 3: Execute assignments
            await self._execute_assignments(assignments, max_cycles)

            # Step 4: Compute result
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            completed = sum(1 for a in assignments if a.status == "completed")
            failed = sum(1 for a in assignments if a.status == "failed")
            skipped = sum(1 for a in assignments if a.status == "skipped")

            result = OrchestrationResult(
                goal=goal,
                total_subtasks=len(assignments),
                completed_subtasks=completed,
                failed_subtasks=failed,
                skipped_subtasks=skipped,
                assignments=assignments,
                duration_seconds=duration,
                success=failed == 0,
                summary=self._generate_summary(assignments),
            )

            # Step 4b: Complete convoy tracking
            if self.enable_convoy_tracking and self._convoy_id:
                await self._complete_convoy(failed == 0)

            # Step 5: Run self-correction analysis for cross-cycle learning
            self._apply_self_correction(assignments, result)

            # Step 5b: Outcome tracking - compare debate quality before/after
            if (
                self.enable_outcome_tracking
                and self._outcome_tracker is not None
                and _outcome_baseline is not None
            ):
                try:
                    _outcome_after = await self._outcome_tracker.capture_after()
                    _outcome_comparison = self._outcome_tracker.compare(
                        _outcome_baseline, _outcome_after
                    )
                    if self._orchestration_id:
                        self._outcome_tracker.record_cycle_outcome(
                            self._orchestration_id, _outcome_comparison
                        )
                    if not _outcome_comparison.improved:
                        logger.warning(
                            "outcome_regression_detected recommendation=%s",
                            _outcome_comparison.recommendation,
                        )
                        # Auto-replan: queue regression-fix goals for next cycle
                        self._enqueue_regression_goals(_outcome_comparison, goal)
                except (
                    RuntimeError,
                    OSError,
                    ValueError,
                    ConnectionError,
                    asyncio.TimeoutError,
                ) as e:
                    logger.debug("outcome_tracking_failed: %s", e)

            # Step 5c: Metrics comparison - objective improvement measurement
            if (
                self.enable_metrics
                and self._metrics_collector is not None
                and _metrics_baseline is not None
            ):
                try:
                    file_scope = []
                    for a in assignments:
                        file_scope.extend(a.subtask.file_scope or [])
                    _metrics_after = await self._metrics_collector.collect_after(
                        goal,
                        file_scope=file_scope or None,
                    )
                    _metrics_delta = self._metrics_collector.compare(
                        _metrics_baseline,
                        _metrics_after,
                    )
                    result.baseline_metrics = _metrics_baseline.to_dict()
                    result.after_metrics = _metrics_after.to_dict()
                    result.metrics_delta = _metrics_delta.to_dict()
                    result.improvement_score = _metrics_delta.improvement_score

                    # Check success criteria from subtasks
                    all_criteria: dict[str, Any] = {}
                    for a in assignments:
                        if a.subtask.success_criteria:
                            all_criteria.update(a.subtask.success_criteria)
                    if all_criteria:
                        met, unmet = self._metrics_collector.check_success_criteria(
                            _metrics_after,
                            all_criteria,
                        )
                        result.success_criteria_met = met
                        if not met:
                            logger.info("success_criteria_unmet: %s", "; ".join(unmet))

                    if _metrics_delta.improved:
                        logger.info(
                            f"metrics_improvement_detected score={_metrics_delta.improvement_score:.2f} "
                            f"summary={_metrics_delta.summary}"
                        )
                    elif not _metrics_delta.improved and _metrics_delta.improvement_score < 0.3:
                        logger.warning(
                            f"metrics_no_improvement score={_metrics_delta.improvement_score:.2f} "
                            f"summary={_metrics_delta.summary}"
                        )
                except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as e:
                    logger.debug("metrics_comparison_failed: %s", e)

            # Step 5d: Record pipeline outcome for cross-cycle learning
            self._record_pipeline_outcome(result)

            # Step 6: Record cycle telemetry
            if self._cycle_telemetry is not None:
                try:
                    from aragora.nomic.cycle_telemetry import CycleRecord

                    agents_used = list({a.agent_type for a in assignments if a.agent_type})
                    quality_delta = getattr(result, "improvement_score", 0.0) or 0.0
                    cycle_record = CycleRecord(
                        cycle_id=self._orchestration_id or "",
                        goal=goal,
                        cycle_time_seconds=duration,
                        success=failed == 0,
                        quality_delta=quality_delta,
                        cost_usd=self._total_cost_usd,
                        agents_used=agents_used,
                        branch_name="",
                    )
                    self._cycle_telemetry.record_cycle(cycle_record)

                    # Persist learnings to KM for cross-cycle learning
                    if self._km_feedback_bridge is not None and cycle_record.success:
                        try:
                            self._km_feedback_bridge.persist_cycle_learnings(cycle_record)
                        except (RuntimeError, OSError, ValueError, TypeError) as e:
                            logger.debug("km_feedback_persist_skipped: %s", e)
                except ImportError:
                    pass
                except (RuntimeError, OSError, ValueError) as e:
                    logger.debug("cycle_telemetry_record_failed: %s", e)

            self._checkpoint("completed", {"result": result.summary})
            self._emit_improvement_event(
                "IMPROVEMENT_CYCLE_COMPLETE",
                {
                    "goal": goal[:200],
                    "completed": completed,
                    "failed": failed,
                    "skipped": skipped,
                    "duration_seconds": duration,
                    "success": failed == 0,
                },
            )
            logger.info(
                "orchestration_completed",
                orchestration_id=self._orchestration_id,
                completed=completed,
                failed=failed,
                duration_seconds=duration,
            )

            return result

        except (RuntimeError, OSError, ValueError, ConnectionError, asyncio.TimeoutError) as e:
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.warning(
                "orchestration_failed",
                orchestration_id=self._orchestration_id,
                error_type=type(e).__name__,
            )
            self._emit_improvement_event(
                "IMPROVEMENT_CYCLE_FAILED",
                {
                    "goal": goal[:200],
                    "error": type(e).__name__,
                    "duration_seconds": duration,
                },
            )

            # Fail the convoy on exception
            if self.enable_convoy_tracking and self._convoy_id:
                try:
                    await self._complete_convoy(
                        success=False, error=f"Orchestration failed: {type(e).__name__}"
                    )
                except (RuntimeError, OSError, ValueError, ConnectionError, asyncio.TimeoutError):
                    logger.debug("Failed to update convoy on error")

            return OrchestrationResult(
                goal=goal,
                total_subtasks=len(self._active_assignments),
                completed_subtasks=0,
                failed_subtasks=len(self._active_assignments),
                skipped_subtasks=0,
                assignments=self._active_assignments,
                duration_seconds=duration,
                success=False,
                error=f"Orchestration failed: {type(e).__name__}",
            )

    async def _decompose_goal(
        self,
        goal: str,
        tracks: list[str] | None = None,
    ) -> TaskDecomposition:
        """Decompose a high-level goal into subtasks."""
        # Enrich goal with track context if provided
        if tracks:
            track_context = f"\n\nFocus tracks: {', '.join(tracks)}"
            enriched_goal = f"{goal}{track_context}"
        else:
            enriched_goal = goal

        # Use debate-based decomposition for abstract goals
        if self.use_debate_decomposition:
            logger.info("Using debate-based decomposition for goal")
            return await self.task_decomposer.analyze_with_debate(enriched_goal)

        return self.task_decomposer.analyze(enriched_goal)

    def _create_assignments(
        self,
        decomposition: TaskDecomposition,
        tracks: list[str] | None = None,
    ) -> list[AgentAssignment]:
        """Create agent assignments from decomposed subtasks."""
        assignments = []
        allowed_tracks = {Track(t.lower()) for t in tracks} if tracks else set(Track)

        for i, subtask in enumerate(decomposition.subtasks):
            track = self.router.determine_track(subtask)

            # Skip if track not in allowed list
            if track not in allowed_tracks:
                logger.debug("Skipping subtask %s: track %s not allowed", subtask.id, track)
                continue

            agent_type = self.router.select_agent_type(subtask, track)

            assignments.append(
                AgentAssignment(
                    subtask=subtask,
                    track=track,
                    agent_type=agent_type,
                    priority=len(decomposition.subtasks) - i,  # Higher index = lower priority
                )
            )

        # Sort by priority (highest first)
        assignments.sort(key=lambda a: a.priority, reverse=True)
        return assignments

    async def _execute_assignments(
        self,
        assignments: list[AgentAssignment],
        max_cycles: int,
    ) -> None:
        """Execute assignments with parallel coordination.

        When a BranchCoordinator is configured, creates isolated worktree
        branches before execution and merges completed branches afterward.
        """
        # Create worktree branches for isolation if coordinator is available
        if self.branch_coordinator is not None:
            await self._create_branches_for_assignments(assignments)

        # Start stuck detection monitoring if enabled
        if self.enable_stuck_detection and self._stuck_detector is not None:
            try:
                await self._stuck_detector.initialize()
                await self._stuck_detector.start_monitoring()
                logger.info("stuck_detection_started")
            except (RuntimeError, OSError, ValueError, ConnectionError, asyncio.TimeoutError) as e:
                logger.debug("stuck_detection_start_failed: %s", e)

        pending = list(assignments)
        running: list[asyncio.Task] = []

        while pending or running:
            # Start new tasks up to max parallel (semaphore enforces limit)
            while pending and len(running) < self.max_parallel_tasks:
                # Budget hard cutoff: don't start new tasks if budget exceeded
                if self.budget_limit is not None and self._total_cost_usd > self.budget_limit:
                    logger.warning(
                        f"budget_exceeded limit={self.budget_limit:.2f} spent={self._total_cost_usd:.2f} remaining_tasks={len(pending)}"
                    )
                    for p in pending:
                        p.status = "skipped"
                    pending.clear()
                    break

                assignment = pending.pop(0)

                # Check for conflicts
                conflicts = self.router.check_conflicts(
                    assignment.subtask,
                    [a for a in assignments if a.status == "running"],
                )

                if conflicts:
                    logger.warning(
                        "assignment_delayed",
                        subtask_id=assignment.subtask.id,
                        conflicts=conflicts,
                    )
                    pending.append(assignment)  # Re-queue
                    break  # Wait for running tasks to complete

                # Start the assignment
                assignment.status = "running"
                assignment.started_at = datetime.now(timezone.utc)
                self._active_assignments.append(assignment)

                task = asyncio.create_task(self._execute_with_semaphore(assignment, max_cycles))
                running.append(task)

            if not running:
                break

            # Wait for at least one task to complete
            done, pending_tasks = await asyncio.wait(
                running,
                return_when=asyncio.FIRST_COMPLETED,
            )
            running = list(pending_tasks)

            # Process completed tasks
            for task in done:
                try:
                    await task
                except (
                    RuntimeError,
                    OSError,
                    ValueError,
                    ConnectionError,
                    asyncio.TimeoutError,
                ) as e:
                    logger.exception("Task failed: %s", e)

            # Mid-run cost forecast check after each batch of completions
            if (
                self.enable_cost_forecast
                and self._cost_forecaster is not None
                and self.budget_limit is not None
                and pending
            ):
                try:
                    budget_check = self._cost_forecaster.check_mid_run_budget(
                        spent_so_far=self._total_cost_usd,
                        remaining_subtasks=len(pending),
                        budget_limit=self.budget_limit,
                    )
                    if budget_check.status in ("warning", "critical"):
                        logger.warning(
                            "cost_forecast_midrun status=%s msg=%s",
                            budget_check.status,
                            budget_check.message,
                        )
                        if self._cost_alert_callback is not None:
                            try:
                                self._cost_alert_callback(budget_check)
                            except (RuntimeError, TypeError, ValueError) as cb_err:
                                logger.debug("cost_alert_callback_failed: %s", cb_err)
                except (RuntimeError, OSError, ValueError, TypeError) as e:
                    logger.debug("cost_forecast_midrun_failed: %s", e)

        # Stop stuck detection monitoring
        if self.enable_stuck_detection and self._stuck_detector is not None:
            try:
                await self._stuck_detector.stop_monitoring()
                health = await self._stuck_detector.get_health_summary()
                if health.red_count > 0:
                    logger.warning(
                        "stuck_detection_summary red=%s yellow=%s recovered=%s",
                        health.red_count,
                        health.yellow_count,
                        health.recovered_count,
                    )
                else:
                    logger.info(
                        f"stuck_detection_clean total={health.total_items} "
                        f"health={health.health_percentage:.0f}%"
                    )
            except (RuntimeError, OSError, ValueError, ConnectionError, asyncio.TimeoutError) as e:
                logger.debug("stuck_detection_shutdown_failed: %s", e)

        # Merge completed branches and cleanup worktrees
        if self.branch_coordinator is not None:
            await self._merge_and_cleanup(assignments)

    async def _execute_with_semaphore(
        self,
        assignment: AgentAssignment,
        max_cycles: int,
    ) -> None:
        """Acquire the concurrency semaphore then execute the assignment."""
        async with self._semaphore:
            await self._execute_single_assignment(assignment, max_cycles)

    async def _check_plan_approval(
        self,
        assignment: AgentAssignment,
    ) -> bool:
        """Check plan approval gate before implementation.

        When ``HierarchyConfig.plan_gate_blocking`` is True, the orchestrator
        requests approval (via the file-based gate) before allowing a subtask
        to proceed to implementation.

        Returns True if approved (or gate is not blocking), False otherwise.
        """
        gate_id = f"plan_{assignment.subtask.id}"
        return await self.request_approval(
            gate_id=gate_id,
            description=(
                f"Plan approval for subtask: {assignment.subtask.title}\n"
                f"Track: {assignment.track.value}\n"
                f"Agent: {assignment.agent_type}\n"
                f"Description: {assignment.subtask.description[:200]}"
            ),
            metadata={
                "subtask_id": assignment.subtask.id,
                "track": assignment.track.value,
                "gate": "plan_approval",
            },
        )

    async def _check_final_review(
        self,
        assignment: AgentAssignment,
        result: Any,
    ) -> bool:
        """Check final review gate after verification.

        When ``HierarchyConfig.final_review_blocking`` is True, the orchestrator
        requests approval before marking a subtask as completed.

        Returns True if approved (or gate is not blocking), False otherwise.
        """
        gate_id = f"review_{assignment.subtask.id}"
        return await self.request_approval(
            gate_id=gate_id,
            description=(
                f"Final review for subtask: {assignment.subtask.title}\n"
                f"Track: {assignment.track.value}\n"
                f"Result: {'success' if result.success else 'failed'}"
            ),
            metadata={
                "subtask_id": assignment.subtask.id,
                "track": assignment.track.value,
                "gate": "final_review",
                "result_success": result.success,
            },
        )

    async def _run_gauntlet_gate(
        self,
        assignment: AgentAssignment,
        workflow_result: Any,
    ) -> Any:
        """Run the Gauntlet approval gate after verification succeeds.

        Performs a lightweight adversarial benchmark against the implementation
        output.  If the Gauntlet finds CRITICAL or HIGH severity findings that
        exceed configured thresholds, the returned result will have
        ``blocked=True``.

        Args:
            assignment: The current agent assignment.
            workflow_result: The workflow execution result (used as context).

        Returns:
            A ``GauntletGateResult``, or ``None`` if the gate could not run.
        """
        try:
            from aragora.nomic.gauntlet_gate import (
                GauntletApprovalGate,
                GauntletGateConfig,
            )
        except ImportError:
            logger.debug("gauntlet_gate module unavailable, skipping")
            return None

        subtask = assignment.subtask
        content = (
            f"Subtask: {subtask.title}\n"
            f"Description: {subtask.description}\n"
            f"Track: {assignment.track.value}\n"
            f"Agent: {assignment.agent_type}\n"
            f"Files: {', '.join(subtask.file_scope[:10]) if subtask.file_scope else 'N/A'}"
        )
        context = f"Workflow output: {str(workflow_result.final_output)[:1000]}"

        gate = GauntletApprovalGate(
            config=GauntletGateConfig(enabled=True),
        )

        logger.info(
            "gauntlet_gate_started subtask_id=%s track=%s",
            subtask.id,
            assignment.track.value,
        )

        gate_result = await gate.evaluate(content=content, context=context)

        self._checkpoint(
            "gauntlet_gate",
            {
                "subtask_id": subtask.id,
                "blocked": gate_result.blocked,
                "critical": gate_result.critical_count,
                "high": gate_result.high_count,
                "total": gate_result.total_findings,
                "gauntlet_id": gate_result.gauntlet_id,
            },
        )

        return gate_result

    async def _execute_single_assignment(
        self,
        assignment: AgentAssignment,
        max_cycles: int,
    ) -> None:
        """Execute a single assignment with retry logic."""
        subtask = assignment.subtask

        logger.info(
            "assignment_started",
            subtask_id=subtask.id,
            track=assignment.track.value,
            agent=assignment.agent_type,
        )

        # Budget check before each assignment
        if self.budget_limit is not None and self._total_cost_usd > self.budget_limit:
            assignment.status = "skipped"
            logger.warning(
                "assignment_skipped_budget subtask_id=%s spent=%.2f limit=%.2f",
                subtask.id,
                self._total_cost_usd,
                self.budget_limit,
            )
            return

        # Plan approval gate (blocking)
        if self.hierarchy.enabled and self.hierarchy.plan_gate_blocking:
            approved = await self._check_plan_approval(assignment)
            if not approved:
                assignment.status = "blocked"
                logger.info("assignment_blocked_plan_gate subtask_id=%s", subtask.id)
                return

        # Update bead status to RUNNING
        await self._update_bead_status(subtask.id, "running")

        # Register agent with Fabric for lifecycle + budget tracking
        await self._fabric_register_agent(assignment)

        try:
            # Build workflow for this subtask
            workflow = self._build_subtask_workflow(assignment)

            # ExecutionBridge: generate structured instruction for the agent
            if self._execution_bridge is not None:
                try:
                    instruction = self._execution_bridge.create_instruction(
                        subtask=subtask,
                        debate_context=f"Track: {assignment.track.value}, Agent: {assignment.agent_type}",
                        worktree_path=self._get_worktree_for_assignment(assignment),
                    )
                    # Enrich the subtask description with the structured prompt
                    enriched_description = instruction.to_agent_prompt()
                except (RuntimeError, ValueError, TypeError, AttributeError) as e:
                    logger.debug("ExecutionBridge instruction skipped: %s", e)
                    enriched_description = subtask.description
            else:
                enriched_description = subtask.description

            # Execute workflow — include retry hints from prior failures
            inputs: dict[str, Any] = {
                "subtask": enriched_description,
                "files": subtask.file_scope,
                "complexity": subtask.estimated_complexity,
                "max_cycles": max_cycles,
            }
            if assignment.retry_hints:
                hint_block = "\n".join(f"- {h}" for h in assignment.retry_hints)
                inputs["subtask"] = (
                    f"{enriched_description}\n\n"
                    f"RETRY CONTEXT (attempt {assignment.attempt_count + 1}, "
                    f"prior attempt failed):\n{hint_block}"
                )

            result = await self.workflow_engine.execute(workflow, inputs=inputs)

            if result.success:
                # Gauntlet approval gate (blocking on CRITICAL/HIGH findings)
                if self.enable_gauntlet_gate:
                    gate_result = await self._run_gauntlet_gate(assignment, result)
                    if gate_result is not None and gate_result.blocked:
                        assignment.status = "rejected"
                        assignment.result = {
                            "workflow_result": result.final_output,
                            "gauntlet_gate": gate_result.to_dict(),
                        }
                        logger.info(
                            "assignment_blocked_gauntlet subtask_id=%s reason=%s",
                            subtask.id,
                            gate_result.reason,
                        )
                        await self._update_bead_status(
                            subtask.id,
                            "failed",
                            error=f"Blocked by Gauntlet gate: {gate_result.reason}",
                        )
                        return

                # Final review gate (blocking)
                if self.hierarchy.enabled and self.hierarchy.final_review_blocking:
                    approved = await self._check_final_review(assignment, result)
                    if not approved:
                        assignment.status = "rejected"
                        logger.info("assignment_rejected_review subtask_id=%s", subtask.id)
                        await self._update_bead_status(
                            subtask.id, "failed", error="Rejected at review gate"
                        )
                        return

                assignment.status = "completed"
                assignment.result = {"workflow_result": result.final_output}
                await self._update_bead_status(subtask.id, "done")
                self._emit_improvement_event(
                    "IMPROVEMENT_CYCLE_VERIFIED",
                    {
                        "subtask_id": subtask.id,
                        "track": assignment.track.value,
                        "agent": assignment.agent_type,
                    },
                )

                # Record agent success in ELO + KM for learning
                await self._record_agent_outcome(
                    assignment,
                    success=True,
                    domain=assignment.track.value,
                )
            else:
                # DebugLoop: attempt test-driven retry before falling back to feedback
                if self._debug_loop is not None:
                    try:
                        worktree_path = self._get_worktree_for_assignment(assignment)
                        if worktree_path:
                            test_scope = self._infer_test_paths(subtask.file_scope)
                            debug_result = await self._debug_loop.execute_with_retry(
                                instruction=subtask.description,
                                worktree_path=worktree_path,
                                test_scope=test_scope or None,
                                subtask_id=subtask.id,
                            )
                            if debug_result.success:
                                assignment.status = "completed"
                                assignment.result = {
                                    "workflow_result": result.final_output,
                                    "debug_loop_fixed": True,
                                    "debug_attempts": debug_result.total_attempts,
                                }
                                await self._update_bead_status(subtask.id, "done")
                                await self._record_agent_outcome(
                                    assignment,
                                    success=True,
                                    domain=assignment.track.value,
                                )
                                logger.info(
                                    "debug_loop_recovered subtask=%s attempts=%d",
                                    subtask.id,
                                    debug_result.total_attempts,
                                )
                                return
                    except (RuntimeError, OSError, ValueError, AttributeError) as e:
                        logger.debug("DebugLoop retry skipped: %s", e)

                # Extract structured TestResult from verify step if available
                error_info: dict[str, Any] = {
                    "type": "workflow_failure",
                    "message": result.error or "",
                }
                verify_step = result.get_step_result("verify")
                if verify_step and isinstance(verify_step.output, dict):
                    test_result_obj = verify_step.output.get("test_result")
                    if test_result_obj is not None:
                        error_info["type"] = "test_failure"
                        error_info["test_result"] = test_result_obj

                # Try targeted fix for small, high-confidence test-side failures
                if error_info.get("test_result") is not None:
                    fixed = await self._attempt_targeted_fix(assignment, error_info["test_result"])
                    if fixed:
                        assignment.status = "completed"
                        assignment.result = {
                            "workflow_result": result.final_output,
                            "targeted_fix": True,
                        }
                        await self._update_bead_status(subtask.id, "done")
                        await self._record_agent_outcome(
                            assignment,
                            success=True,
                            domain=assignment.track.value,
                        )
                        return

                # Handle failure with feedback loop
                feedback = self.feedback_loop.analyze_failure(
                    assignment,
                    error_info,
                )
                if inspect.isawaitable(feedback):
                    feedback = await feedback

                if feedback["action"] == "escalate":
                    assignment.status = "failed"
                    assignment.result = {"error": result.error, "feedback": feedback}
                    await self._update_bead_status(subtask.id, "failed", error=result.error)
                    await self._record_agent_outcome(
                        assignment,
                        success=False,
                        domain=assignment.track.value,
                    )
                elif feedback["action"] == "reassign_agent":
                    # Anti-fragile: try a different agent type
                    alt_agent = self._select_alternative_agent(assignment)
                    if alt_agent and alt_agent != assignment.agent_type:
                        logger.info(
                            "reassigning_agent",
                            subtask_id=subtask.id,
                            from_agent=assignment.agent_type,
                            to_agent=alt_agent,
                        )
                        assignment.agent_type = alt_agent
                    # Propagate failure reason to next attempt
                    assignment.retry_hints = self._extract_hints(feedback)
                    assignment.attempt_count += 1
                    if assignment.attempt_count < assignment.max_attempts:
                        await self._execute_single_assignment(assignment, max_cycles)
                    else:
                        assignment.status = "failed"
                        await self._update_bead_status(subtask.id, "failed")
                else:
                    # Retry based on feedback — pass hints to next attempt
                    assignment.retry_hints = self._extract_hints(feedback)
                    assignment.attempt_count += 1
                    if assignment.attempt_count < assignment.max_attempts:
                        await self._execute_single_assignment(assignment, max_cycles)
                    else:
                        assignment.status = "failed"
                        await self._update_bead_status(subtask.id, "failed")

        except (RuntimeError, OSError, ValueError, ConnectionError, asyncio.TimeoutError) as e:
            logger.warning("assignment_failed", subtask_id=subtask.id, error_type=type(e).__name__)
            assignment.status = "failed"
            assignment.result = {"error": f"Assignment execution failed: {type(e).__name__}"}
            await self._update_bead_status(
                subtask.id, "failed", error=f"Assignment failed: {type(e).__name__}"
            )

        finally:
            assignment.completed_at = datetime.now(timezone.utc)
            if assignment not in self._completed_assignments:
                self._completed_assignments.append(assignment)
            try:
                self._active_assignments.remove(assignment)
            except ValueError:
                pass  # Already removed (e.g., during retry)

            # ExecutionBridge: ingest result into Knowledge Mound for feedback
            self._bridge_ingest_result(assignment)

            # Notify Fabric of task completion for cleanup
            await self._fabric_complete_task(assignment, success=assignment.status == "completed")

    async def _attempt_targeted_fix(
        self,
        assignment: AgentAssignment,
        test_result: Any,
    ) -> bool:
        """Attempt a targeted fix using TestFixerOrchestrator for small failures.

        Guards:
        - Only attempt if <= 5 failures
        - At least one failure has heuristic confidence >= 0.7
        - At least one failure targets test file or config (not impl)

        Returns True if fix succeeded and verification passes.
        """
        try:
            from aragora.nomic.testfixer.analyzer import (
                categorize_by_heuristics,
                determine_fix_target,
                FixTarget,
            )
            from aragora.nomic.testfixer.orchestrator import (
                TestFixerOrchestrator,
                FixLoopConfig,
                LoopStatus,
            )
        except ImportError:
            logger.debug("testfixer unavailable, skipping targeted fix")
            return False

        failures = getattr(test_result, "failures", [])
        if not failures or len(failures) > 5:
            return False

        # Check guard: at least one high-confidence test-side fix
        has_eligible = False
        for failure in failures:
            category, confidence = categorize_by_heuristics(failure)
            fix_target = determine_fix_target(category, failure)
            if confidence >= 0.7 and fix_target in (FixTarget.TEST_FILE, FixTarget.CONFIG):
                has_eligible = True
                break

        if not has_eligible:
            return False

        logger.info(
            "targeted_fix_attempt subtask_id=%s failures=%d",
            assignment.subtask.id,
            len(failures),
        )

        # Scope tests to only the failing test files
        failing_files = list({f.test_file for f in failures if f.test_file})
        if not failing_files:
            return False

        test_command = f"python -m pytest {' '.join(failing_files)} -x --tb=short -q"

        try:
            fixer = TestFixerOrchestrator(
                repo_path=self.aragora_path,
                test_command=test_command,
                config=FixLoopConfig(
                    max_iterations=3,
                    min_confidence_to_apply=0.7,
                    revert_on_failure=True,
                    stop_on_first_success=False,
                ),
            )
            fix_result = await fixer.run_fix_loop()

            if fix_result.status == LoopStatus.SUCCESS:
                logger.info(
                    "targeted_fix_success subtask_id=%s fixes=%d",
                    assignment.subtask.id,
                    fix_result.fixes_successful,
                )
                return True

            logger.info(
                "targeted_fix_incomplete subtask_id=%s status=%s",
                assignment.subtask.id,
                fix_result.status.value,
            )
            return False

        except (RuntimeError, OSError, ValueError) as e:
            logger.warning(
                "targeted_fix_error subtask_id=%s error=%s",
                assignment.subtask.id,
                type(e).__name__,
            )
            return False

    async def _record_agent_outcome(
        self,
        assignment: AgentAssignment,
        success: bool,
        domain: str,
    ) -> None:
        """Record agent implementation performance in ELO and Knowledge Mound.

        This closes the self-improvement feedback loop: agents that succeed
        at implementation tasks get ELO boosts, agents that fail get penalties.
        Over time, the system learns which agents are best for which tracks.
        """
        agent_name = assignment.agent_type

        # Record in ELO system
        try:
            from aragora.ranking.elo import get_elo_store

            elo = get_elo_store()
            # Use a synthetic match: agent vs "baseline" where success = win
            elo.record_match(
                debate_id=f"impl-{assignment.subtask.id}",
                participants=[agent_name, "_baseline"],
                scores={agent_name: 1.0 if success else 0.0, "_baseline": 0.5},
                domain=domain,
            )
            logger.info(
                "agent_outcome_elo agent=%s success=%s domain=%s", agent_name, success, domain
            )
        except (ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.debug("ELO recording failed for %s: %s", agent_name, e)

        # Record in Knowledge Mound
        try:
            from aragora.knowledge.mound.adapters.factory import get_adapter

            adapter = get_adapter("nomic_cycle")
            if adapter and hasattr(adapter, "record"):
                await adapter.record(
                    {
                        "type": "agent_implementation_outcome",
                        "agent": agent_name,
                        "track": domain,
                        "subtask_id": assignment.subtask.id,
                        "success": success,
                        "attempt": assignment.attempt_count,
                    }
                )
        except (ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.debug("KM recording failed for %s: %s", agent_name, e)

    def _select_alternative_agent(self, assignment: AgentAssignment) -> str | None:
        """Select an alternative agent type for reassignment on failure.

        Picks the next available agent from the track's preferred list,
        skipping the current agent. Falls back to 'claude' as the most
        capable general-purpose agent.
        """
        config = self.track_configs.get(
            assignment.track,
            DEFAULT_TRACK_CONFIGS[Track.DEVELOPER],
        )
        candidates = [a for a in config.agent_types if a != assignment.agent_type]
        if candidates:
            return candidates[0]
        # Fallback: if current agent isn't claude, try claude
        if assignment.agent_type != "claude":
            return "claude"
        return None

    @staticmethod
    def _extract_hints(feedback: dict[str, Any]) -> list[str]:
        """Extract actionable hints from a FeedbackLoop analysis result.

        Normalizes hints into a flat list of strings so they can be injected
        into the next retry's workflow inputs.
        """
        hints: list[str] = []
        raw = feedback.get("hints", [])
        if isinstance(raw, str):
            hints.append(raw)
        elif isinstance(raw, list):
            for h in raw:
                if isinstance(h, str):
                    hints.append(h)
                elif isinstance(h, dict):
                    # Rich hint from testfixer (has file, line, error, suggestion)
                    parts = []
                    if h.get("file"):
                        parts.append(h["file"])
                    if h.get("line"):
                        parts.append(f"line {h['line']}")
                    if h.get("error"):
                        parts.append(h["error"])
                    if h.get("suggestion"):
                        parts.append(f"Fix: {h['suggestion']}")
                    hints.append(": ".join(parts) if parts else str(h))
        if feedback.get("reason"):
            hints.insert(0, feedback["reason"])
        return hints

    def _build_subtask_workflow(self, assignment: AgentAssignment) -> WorkflowDefinition:
        """Build a workflow definition for a subtask.

        Uses the gold path: agent(design) -> implementation -> verification.

        The "implementation" step type bridges to HybridExecutor which spawns
        Claude/Codex subprocesses to write code. The "verification" step type
        runs pytest against the changed files.
        """
        subtask = assignment.subtask

        # Check if agent needs a coding harness (e.g., KiloCode for Gemini)
        coding_harness = self.router.get_coding_harness(
            assignment.agent_type,
            assignment.track,
        )

        # Resolve repo path: prefer worktree path for isolation
        repo_path = self.aragora_path
        if self.branch_coordinator is not None:
            # Look up if this assignment's track has a worktree
            for branch, wt_path in getattr(self.branch_coordinator, "_worktree_paths", {}).items():
                if assignment.track.value in branch:
                    repo_path = wt_path
                    break

        # Build implementation step config matching ImplementationStep's expected format
        implement_config: dict[str, Any] = {
            "task_id": subtask.id,
            "description": subtask.description,
            "files": subtask.file_scope,
            "complexity": subtask.estimated_complexity,
            "repo_path": str(repo_path),
        }

        # If agent needs a coding harness, add it to the config
        if coding_harness:
            implement_config["coding_harness"] = coding_harness
            logger.info(
                "subtask_using_kilocode agent=%s provider=%s track=%s",
                assignment.agent_type,
                coding_harness["provider_id"],
                assignment.track.value,
            )

        # Derive test paths from file scope for verification
        test_paths = self._infer_test_paths(subtask.file_scope)

        # Create workflow with phases aligned to nomic loop gold path
        #
        # With hierarchy enabled, the workflow becomes:
        #   design (planner) -> plan_approval (judge) -> [gauntlet] -> implement (worker)
        #   -> verify -> judge_review (judge)
        #
        # With gauntlet gate enabled (no hierarchy):
        #   design -> gauntlet -> implement -> verify
        #
        # Without either:
        #   design -> implement -> verify

        hierarchy_enabled = self.hierarchy.enabled

        # Determine the step that follows design (before implement)
        # Priority: plan_approval (hierarchy) > gauntlet > implement
        if hierarchy_enabled:
            design_next = ["plan_approval"]
        elif self.enable_gauntlet_gate:
            design_next = ["gauntlet"]
        else:
            design_next = ["implement"]

        # The step that feeds into implement
        if self.enable_gauntlet_gate and hierarchy_enabled:
            plan_approval_next = ["gauntlet"]
        elif hierarchy_enabled:
            plan_approval_next = ["implement"]
        else:
            plan_approval_next = ["implement"]

        # Override agent types when hierarchy is active
        design_agent = self.hierarchy.planner_agent if hierarchy_enabled else assignment.agent_type
        implement_agent = assignment.agent_type
        if hierarchy_enabled and self.hierarchy.worker_agents:
            # Pick the first worker agent that matches the track, or fallback to first
            implement_agent = self.hierarchy.worker_agents[0]
            for wa in self.hierarchy.worker_agents:
                if wa in (
                    config.agent_types
                    if (config := self.track_configs.get(assignment.track))
                    else []
                ):
                    implement_agent = wa
                    break

        steps = [
            StepDefinition(
                id="design",
                name="Design Solution",
                step_type="agent",
                config={
                    "agent_type": design_agent,
                    "prompt_template": "design",
                    "task": subtask.description,
                },
                next_steps=design_next,
            ),
        ]

        if hierarchy_enabled:
            steps.append(
                StepDefinition(
                    id="plan_approval",
                    name="Plan Approval Gate",
                    step_type="agent",
                    config={
                        "agent_type": self.hierarchy.judge_agent,
                        "prompt_template": "review",
                        "task": (
                            f"Review the design plan for: {subtask.description}\n\n"
                            "Evaluate the plan for:\n"
                            "1. Feasibility: Can this be implemented as described?\n"
                            "2. Completeness: Are all edge cases addressed?\n"
                            "3. Risk: Are there security or correctness risks?\n\n"
                            "Respond with APPROVE or REJECT (with reasons)."
                        ),
                        "gate": True,
                        "blocking": self.hierarchy.plan_gate_blocking,
                        "max_revisions": self.hierarchy.max_plan_revisions,
                    },
                    next_steps=plan_approval_next,
                )
            )

        # Insert gauntlet adversarial validation step between design and implement
        if self.enable_gauntlet_gate:
            # Use stricter threshold for high-complexity subtasks
            severity_threshold = "medium" if subtask.estimated_complexity == "high" else "high"
            steps.append(
                StepDefinition(
                    id="gauntlet",
                    name="Adversarial Validation",
                    step_type="gauntlet",
                    config={
                        "input_key": "content",
                        "severity_threshold": severity_threshold,
                        "require_passing": True,
                        "attack_categories": [
                            "prompt_injection",
                            "hallucination",
                            "safety",
                        ],
                        "probe_categories": [
                            "reasoning",
                            "consistency",
                        ],
                    },
                    next_steps=["implement"],
                )
            )

        steps.append(
            StepDefinition(
                id="implement",
                name="Implement Changes",
                step_type="implementation",
                config={
                    **implement_config,
                    "agent_type": implement_agent,
                },
                next_steps=["verify"],
            ),
        )

        verify_next = (
            ["harness_scan"]
            if self.use_harness
            else (["judge_review"] if hierarchy_enabled else [])
        )
        steps.append(
            StepDefinition(
                id="verify",
                name="Verify Changes",
                step_type="verification",
                config={
                    "run_tests": True,
                    "test_paths": test_paths,
                    "test_count": len(test_paths),
                },
                next_steps=verify_next,
            ),
        )

        # Harness scan: run code analysis for security/quality after tests pass
        if self.use_harness:
            harness_next = ["judge_review"] if hierarchy_enabled else []
            steps.append(
                StepDefinition(
                    id="harness_scan",
                    name="Harness Security/Quality Scan",
                    step_type="harness_analysis",
                    config={
                        "analysis_types": ["security", "quality"],
                        "file_scope": subtask.file_scope or [],
                        "fail_on_critical": True,
                    },
                    next_steps=harness_next,
                ),
            )

        if hierarchy_enabled:
            steps.append(
                StepDefinition(
                    id="judge_review",
                    name="Judge Final Review",
                    step_type="agent",
                    config={
                        "agent_type": self.hierarchy.judge_agent,
                        "prompt_template": "review",
                        "task": (
                            f"Final review for: {subtask.description}\n\n"
                            "Review the implementation and verification results.\n"
                            "Check that the implementation matches the approved plan.\n"
                            "Respond with APPROVE or REJECT (with reasons)."
                        ),
                        "gate": True,
                        "blocking": self.hierarchy.final_review_blocking,
                    },
                    next_steps=[],
                )
            )

        return WorkflowDefinition(
            id=f"subtask_{subtask.id}",
            name=f"Execute: {subtask.title}",
            description=subtask.description,
            steps=steps,
            entry_step="design",
        )

    @staticmethod
    def _infer_test_paths(file_scope: list[str]) -> list[str]:
        """Infer test file paths from source file paths.

        Maps source files like ``aragora/foo/bar.py`` to
        ``tests/foo/test_bar.py`` if no explicit test paths are provided.
        """
        test_paths: list[str] = []
        for path in file_scope:
            if path.startswith("tests/"):
                test_paths.append(path)
                continue
            # aragora/foo/bar.py -> tests/foo/test_bar.py
            if path.startswith("aragora/"):
                rel = path[len("aragora/") :]
                parts = rel.rsplit("/", 1)
                if len(parts) == 2:
                    directory, filename = parts
                    if filename.endswith(".py"):
                        test_file = f"tests/{directory}/test_{filename}"
                        test_paths.append(test_file)
        return test_paths

    def _enqueue_regression_goals(
        self,
        comparison: Any,
        original_goal: str,
    ) -> None:
        """Convert detected regressions into improvement goals for next cycle.

        When OutcomeTracker detects a regression, this method generates
        targeted fix goals and pushes them to the ImprovementQueue so
        MetaPlanner picks them up automatically in the next planning cycle.
        """
        try:
            from aragora.nomic.feedback_orchestrator import ImprovementGoal, ImprovementQueue
        except ImportError:
            logger.debug("feedback_orchestrator unavailable for auto-replan")
            return

        try:
            queue = ImprovementQueue()
            metrics_delta = getattr(comparison, "metrics_delta", {}) or {}
            recommendation = getattr(comparison, "recommendation", "review")

            # Generate a goal for each regressed metric
            regressed = [(k, v) for k, v in metrics_delta.items() if v is not None]
            if not regressed:
                # No specific metrics — generate a generic regression-fix goal
                queue.push(
                    ImprovementGoal(
                        goal=f"Fix regression caused by: {original_goal}",
                        source="outcome_tracker_regression",
                        priority=0.9,  # High priority
                        context={
                            "recommendation": recommendation,
                            "original_goal": original_goal,
                            "auto_replan": True,
                        },
                    )
                )
                logger.info("auto_replan: queued generic regression-fix goal")
                return

            for metric_name, delta_value in regressed:
                priority = 0.95 if recommendation == "revert" else 0.8
                queue.push(
                    ImprovementGoal(
                        goal=(
                            f"Fix {metric_name} regression "
                            f"(delta={delta_value:+.3f}) "
                            f"after: {original_goal}"
                        ),
                        source="outcome_tracker_regression",
                        priority=priority,
                        context={
                            "regressed_metric": metric_name,
                            "delta": delta_value,
                            "recommendation": recommendation,
                            "original_goal": original_goal,
                            "auto_replan": True,
                        },
                    )
                )

            logger.info(
                "auto_replan: queued %d regression-fix goals (recommendation=%s)",
                len(regressed),
                recommendation,
            )

            # Emit spectate event for regression visibility
            if hasattr(self, "_emit_event"):
                self._emit_event(
                    "regression_detected",
                    goal=original_goal[:100],
                    recommendation=recommendation,
                    regressed_metrics=len(regressed),
                    goals_queued=len(regressed) or 1,
                )
        except (RuntimeError, OSError, ValueError) as e:
            logger.debug("auto_replan_failed: %s", e)

    def _apply_self_correction(
        self,
        assignments: list[AgentAssignment],
        result: OrchestrationResult,
    ) -> None:
        """Apply self-correction analysis from past outcomes.

        Converts completed assignments to outcome dicts, runs pattern
        analysis, computes priority adjustments and strategy recommendations,
        and stores them for the next orchestration cycle.
        """
        if self._self_correction is None:
            return

        try:
            # Convert assignments to outcome dicts for analysis
            outcomes: list[dict[str, Any]] = []
            for a in assignments:
                if a.status in ("completed", "failed"):
                    outcomes.append(
                        {
                            "track": a.track.value,
                            "success": a.status == "completed",
                            "agent": a.agent_type,
                            "description": a.subtask.title,
                            "timestamp": (
                                a.completed_at.isoformat()
                                if a.completed_at
                                else datetime.now(timezone.utc).isoformat()
                            ),
                        }
                    )

            if not outcomes:
                return

            # Analyze patterns across this cycle's outcomes
            report = self._self_correction.analyze_patterns(outcomes)

            # Compute priority adjustments for next cycle
            adjustments = self._self_correction.compute_priority_adjustments(report)
            if adjustments:
                # Store on the result for callers to inspect
                if result.after_metrics is None:
                    result.after_metrics = {}
                result.after_metrics["self_correction_adjustments"] = adjustments

            # Compute strategy recommendations
            recommendations = self._self_correction.recommend_strategy_change(report)
            if recommendations:
                if result.after_metrics is None:
                    result.after_metrics = {}
                result.after_metrics["self_correction_recommendations"] = [
                    {
                        "track": r.track,
                        "action": r.action_type,
                        "recommendation": r.recommendation,
                        "confidence": r.confidence,
                    }
                    for r in recommendations
                ]

            # Feed adjustments into MetaPlanner for next cycle
            self._store_priority_adjustments(adjustments)

            # Feed strategy recommendations into FeedbackLoop for next cycle
            if recommendations and self.feedback_loop is not None:
                self.feedback_loop.apply_strategy_recommendations(recommendations)

            logger.info(
                "self_correction_applied outcomes=%s adjustments=%s recommendations=%s",
                len(outcomes),
                len(adjustments),
                len(recommendations),
            )
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Self-correction analysis failed: %s", e)

    def _store_priority_adjustments(self, adjustments: dict[str, float]) -> None:
        """Store priority adjustments for the next MetaPlanner cycle.

        Persists to the Knowledge Mound so the MetaPlanner can query them
        when prioritizing work in the next orchestration cycle.
        """
        if not adjustments:
            return
        try:
            from aragora.knowledge.mound.adapters.factory import get_adapter

            adapter = get_adapter("nomic_cycle")
            if adapter and hasattr(adapter, "record"):
                import asyncio

                coro = adapter.record(
                    {
                        "type": "self_correction_adjustments",
                        "adjustments": adjustments,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "orchestration_id": self._orchestration_id,
                    }
                )
                # Fire-and-forget if we can't await
                if inspect.isawaitable(coro):
                    try:
                        asyncio.ensure_future(coro)
                    except RuntimeError:
                        pass
        except (ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.debug("Failed to persist priority adjustments: %s", e)

    def _get_worktree_for_assignment(self, assignment: AgentAssignment) -> str | None:
        """Get the worktree path for an assignment's track, if available."""
        if self.branch_coordinator is None:
            return None
        worktree_paths = getattr(self.branch_coordinator, "_worktree_paths", {})
        for branch, wt_path in worktree_paths.items():
            if assignment.track.value in branch:
                return str(wt_path)
        return None

    def _bridge_ingest_result(self, assignment: AgentAssignment) -> None:
        """Use ExecutionBridge to ingest assignment result into Knowledge Mound."""
        if self._execution_bridge is None:
            return
        try:
            from aragora.nomic.execution_bridge import ExecutionResult

            files_changed: list[str] = []
            if assignment.result and isinstance(assignment.result, dict):
                files_changed = assignment.result.get("files_changed", [])

            exec_result = ExecutionResult(
                subtask_id=assignment.subtask.id,
                success=assignment.status == "completed",
                files_changed=files_changed,
                error=str(assignment.result.get("error", ""))[:500]
                if assignment.result and isinstance(assignment.result, dict)
                else None,
            )
            self._execution_bridge.ingest_result(exec_result)
        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("ExecutionBridge result ingestion skipped: %s", e)

    def _record_pipeline_outcome(self, result: OrchestrationResult) -> None:
        """Record pipeline outcome to KnowledgeMound for cross-cycle learning.

        Feeds the completed pipeline result back to the KM so the next
        improvement cycle can learn from successes and failures.
        """
        if self._km_feedback_bridge is None:
            return
        try:
            self._km_feedback_bridge.record_pipeline_outcome(
                goal=result.goal,
                success=result.success,
                completed=result.completed_subtasks,
                failed=result.failed_subtasks,
                duration_seconds=result.duration_seconds,
                orchestration_id=self._orchestration_id or "",
            )
            logger.info(
                "pipeline_outcome_recorded goal=%s success=%s",
                result.goal[:60],
                result.success,
            )
        except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as e:
            logger.debug("pipeline_outcome_recording_skipped: %s", e)

    def _checkpoint(self, phase: str, data: dict[str, Any]) -> None:
        """Create a checkpoint for the orchestration."""
        if self.on_checkpoint:
            self.on_checkpoint(
                phase,
                {
                    "orchestration_id": self._orchestration_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **data,
                },
            )

    def _emit_improvement_event(self, event_name: str, data: dict[str, Any]) -> None:
        """Emit IMPROVEMENT_CYCLE_* events for real-time monitoring."""
        if not self.event_emitter:
            return
        try:
            from aragora.events.types import StreamEvent, StreamEventType

            event_type = getattr(StreamEventType, event_name, None)
            if event_type is not None:
                self.event_emitter.emit(
                    StreamEvent(
                        type=event_type,
                        data={
                            "orchestration_id": self._orchestration_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            **data,
                        },
                    )
                )
        except (ImportError, AttributeError, TypeError):
            logger.debug("Event recording unavailable, skipping")

    def _generate_summary(self, assignments: list[AgentAssignment]) -> str:
        """Generate a summary of the orchestration."""
        by_track: dict[str, list[str]] = {}
        for a in assignments:
            track_name = a.track.value
            if track_name not in by_track:
                by_track[track_name] = []
            status_icon = "+" if a.status == "completed" else "-"
            by_track[track_name].append(f"{status_icon} {a.subtask.title}")

        lines = ["Orchestration Summary:"]
        for track, tasks in by_track.items():
            lines.append(f"\n{track.upper()}:")
            for task in tasks:
                lines.append(f"  {task}")

        return "\n".join(lines)

    # =========================================================================
    # File-based approval gate
    # =========================================================================

    async def request_approval(
        self,
        gate_id: str,
        description: str,
        metadata: dict[str, Any] | None = None,
        poll_interval: float = 2.0,
        timeout: float = 300.0,
    ) -> bool:
        """Request human approval via a file-based gate.

        Writes a JSON request to ``.aragora_beads/approval_gates/<gate_id>.json``.
        Polls for a ``.approved`` or ``.rejected`` marker file.

        If ``--auto-approve`` / ``self._auto_approve`` is True, returns
        immediately without waiting.

        Args:
            gate_id: Unique identifier for this approval gate
            description: Human-readable description of what's being approved
            metadata: Additional context for the reviewer
            poll_interval: Seconds between polls
            timeout: Maximum seconds to wait

        Returns:
            True if approved, False if rejected or timed out
        """
        if self._auto_approve:
            logger.info("approval_auto_approved", gate=gate_id)
            return True

        import json as _json
        import time as _time

        gate_dir = self._approval_gate_dir
        gate_dir.mkdir(parents=True, exist_ok=True)

        request_file = gate_dir / f"{gate_id}.json"
        approved_file = gate_dir / f"{gate_id}.approved"
        rejected_file = gate_dir / f"{gate_id}.rejected"

        # Write request
        request_data = {
            "gate_id": gate_id,
            "description": description,
            "metadata": metadata or {},
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "orchestration_id": self._orchestration_id,
        }
        request_file.write_text(_json.dumps(request_data, indent=2))

        logger.info("approval_requested", gate=gate_id, file=str(request_file))

        # Poll for approval/rejection
        start = _time.monotonic()
        while (_time.monotonic() - start) < timeout:
            if approved_file.exists():
                logger.info("approval_granted", gate=gate_id)
                # Clean up marker
                approved_file.unlink(missing_ok=True)
                request_file.unlink(missing_ok=True)
                return True

            if rejected_file.exists():
                logger.warning("approval_rejected", gate=gate_id)
                rejected_file.unlink(missing_ok=True)
                request_file.unlink(missing_ok=True)
                return False

            await asyncio.sleep(poll_interval)

        logger.warning("approval_timeout", gate=gate_id, seconds=timeout)
        request_file.unlink(missing_ok=True)
        return False

    # =========================================================================
    # Branch coordination helpers
    # =========================================================================

    async def _create_branches_for_assignments(
        self,
        assignments: list[AgentAssignment],
    ) -> None:
        """Create worktree branches for each unique track in the assignments.

        Groups assignments by track and creates one branch per track so
        multiple assignments targeting the same track share a worktree.
        """
        if self.branch_coordinator is None:
            return

        from aragora.nomic.meta_planner import Track as MetaTrack

        seen_tracks: set[str] = set()
        for assignment in assignments:
            track_value = assignment.track.value
            if track_value in seen_tracks:
                continue
            seen_tracks.add(track_value)

            # Map orchestrator Track to meta_planner Track
            try:
                meta_track = MetaTrack(track_value)
            except ValueError:
                meta_track = MetaTrack.DEVELOPER

            await self.branch_coordinator.create_track_branch(
                track=meta_track,
                goal=assignment.subtask.description[:60],
            )
            logger.info(
                "worktree_created",
                track=track_value,
                subtask_id=assignment.subtask.id,
            )

    async def _merge_and_cleanup(
        self,
        assignments: list[AgentAssignment],
    ) -> None:
        """Merge completed branches back to base and cleanup worktrees."""
        if self.branch_coordinator is None:
            return

        completed_tracks: set[str] = set()
        failed_tracks: set[str] = set()
        for assignment in assignments:
            if assignment.status == "completed":
                completed_tracks.add(assignment.track.value)
            elif assignment.status == "failed":
                failed_tracks.add(assignment.track.value)

        # Merge branches where all assignments in the track completed
        for branch, wt_path in dict(
            getattr(self.branch_coordinator, "_worktree_paths", {})
        ).items():
            # Check if any track in this branch completed and none failed
            track_value = None
            for t in completed_tracks:
                if t in branch:
                    track_value = t
                    break

            if track_value and track_value not in failed_tracks:
                # Scope guard: warn about cross-track file modifications before merging
                try:
                    from aragora.nomic.scope_guard import ScopeGuard

                    guard = ScopeGuard(repo_path=self.aragora_path, mode="warn")
                    track_name = f"{track_value}-track"
                    changed = guard.get_changed_files(
                        base_branch=self.branch_coordinator.config.base_branch
                    )
                    if changed:
                        violations = guard.check_files(changed, track=track_name)
                        if violations:
                            for v in violations[:5]:
                                logger.info("scope_violation branch=%s %s", branch, v.message)
                except (ImportError, OSError, ValueError) as e:
                    logger.debug("scope_guard_skipped: %s", e)

                # CI feedback: check latest CI result for the branch before merging
                try:
                    from aragora.nomic.ci_feedback import CIResultCollector

                    ci_collector = CIResultCollector()
                    ci_result = ci_collector.get_latest_result(branch)
                    if ci_result is not None:
                        if ci_result.conclusion == "success":
                            logger.info("ci_check_passed branch=%s", branch)
                        else:
                            logger.warning(
                                "ci_check_failed branch=%s conclusion=%s",
                                branch,
                                ci_result.conclusion,
                            )
                            # Don't block merge on CI — just warn
                except (ImportError, OSError, RuntimeError) as e:
                    logger.debug("ci_check_skipped: %s", e)

                # Use safe_merge_with_gate for test-gated merges when available
                if hasattr(self.branch_coordinator, "safe_merge_with_gate"):
                    merge_result = await self.branch_coordinator.safe_merge_with_gate(
                        branch,
                        auto_revert=True,
                    )
                else:
                    merge_result = await self.branch_coordinator.safe_merge(branch)
                if merge_result.success:
                    logger.info(
                        "branch_merged",
                        branch=branch,
                        commit_sha=merge_result.commit_sha,
                    )
                else:
                    logger.warning(
                        "branch_merge_failed",
                        branch=branch,
                        error=merge_result.error,
                    )

        # Cleanup all worktrees
        if hasattr(self.branch_coordinator, "cleanup_all_worktrees"):
            removed = self.branch_coordinator.cleanup_all_worktrees()
        elif hasattr(self.branch_coordinator, "cleanup_worktrees"):
            removed = self.branch_coordinator.cleanup_worktrees()
        else:
            removed = 0
        if removed:
            logger.info("worktrees_cleaned", count=removed)

    # =========================================================================
    # DecisionPlan integration
    # =========================================================================

    def _build_workflow_from_plan(
        self,
        assignment: AgentAssignment,
        debate_result: Any,
    ) -> WorkflowDefinition | None:
        """Build a risk-aware workflow using DecisionPlanFactory.

        When ``use_decision_plan`` is enabled and a debate result is available,
        creates a DecisionPlan which includes risk assessment, verification
        plan, and approval routing based on risk level.

        Returns None if the factory is unavailable or the debate result is
        missing, in which case the caller should fall back to
        ``_build_subtask_workflow``.
        """
        if not self.use_decision_plan or debate_result is None:
            return None

        try:
            from aragora.pipeline.decision_plan.factory import DecisionPlanFactory
            from aragora.pipeline.decision_plan.core import ApprovalMode

            plan = DecisionPlanFactory.from_debate_result(
                debate_result,
                approval_mode=ApprovalMode.RISK_BASED,
                repo_path=self.aragora_path,
            )

            # Convert the plan's implement tasks to workflow steps
            steps: list[StepDefinition] = []
            if plan.implement_plan and plan.implement_plan.tasks:
                for i, task in enumerate(plan.implement_plan.tasks):
                    step_id = f"plan_task_{task.id}"
                    next_id = (
                        f"plan_task_{plan.implement_plan.tasks[i + 1].id}"
                        if i + 1 < len(plan.implement_plan.tasks)
                        else "verify"
                    )
                    steps.append(
                        StepDefinition(
                            id=step_id,
                            name=f"Implement: {task.description[:50]}",
                            step_type="implementation",
                            config={
                                "task_id": task.id,
                                "description": task.description,
                                "files": task.files,
                                "complexity": task.complexity,
                                "repo_path": str(self.aragora_path),
                                "agent_type": assignment.agent_type,
                            },
                            next_steps=[next_id],
                        )
                    )

            # Add verification step
            test_paths = self._infer_test_paths(assignment.subtask.file_scope)
            steps.append(
                StepDefinition(
                    id="verify",
                    name="Verify Changes",
                    step_type="verification",
                    config={
                        "run_tests": True,
                        "test_paths": test_paths,
                    },
                    next_steps=[],
                ),
            )

            # Add approval gate if plan requires human approval
            if plan.requires_human_approval:
                # Insert approval step before implementation
                approval_step = StepDefinition(
                    id="risk_approval",
                    name="Risk-Based Approval Gate",
                    step_type="agent",
                    config={
                        "agent_type": "claude",
                        "prompt_template": "review",
                        "task": (
                            f"Risk review for: {assignment.subtask.description}\n"
                            f"Risk level: {plan.risk_register.get_critical_risks()[0].level.value if plan.risk_register and plan.risk_register.get_critical_risks() else 'unknown'}\n"
                            "Review and approve/reject."
                        ),
                        "gate": True,
                        "blocking": True,
                    },
                    next_steps=[steps[0].id] if steps else [],
                )
                steps.insert(0, approval_step)

            entry = steps[0].id if steps else "verify"
            return WorkflowDefinition(
                id=f"plan_{assignment.subtask.id}",
                name=f"DecisionPlan: {assignment.subtask.title}",
                description=assignment.subtask.description,
                steps=steps,
                entry_step=entry,
            )

        except ImportError:
            logger.debug("DecisionPlanFactory not available, using standard workflow")
            return None
        except (RuntimeError, ValueError, KeyError) as e:
            logger.warning("Failed to build DecisionPlan workflow: %s", e)
            return None

    # =========================================================================
    # Convoy/Bead tracking helpers
    # =========================================================================

    async def _create_convoy_for_goal(
        self,
        goal: str,
        assignments: list[AgentAssignment],
    ) -> None:
        """Create a convoy and beads for tracking the orchestration lifecycle."""
        if not self.enable_convoy_tracking or self.workspace_manager is None:
            return

        try:
            # Create a rig for this orchestration
            rig = await self.workspace_manager.create_rig(
                name=f"orch-{self._orchestration_id}",
            )

            # Create bead specs from assignments
            bead_specs = [
                {
                    "title": a.subtask.title,
                    "description": a.subtask.description,
                    "payload": {
                        "subtask_id": a.subtask.id,
                        "track": a.track.value,
                        "agent_type": a.agent_type,
                    },
                }
                for a in assignments
            ]

            convoy = await self.workspace_manager.create_convoy(
                rig_id=rig.rig_id,
                name=f"Goal: {goal[:50]}",
                description=goal,
                bead_specs=bead_specs,
            )

            self._convoy_id = convoy.convoy_id
            await self.workspace_manager.start_convoy(convoy.convoy_id)

            # Map subtask IDs to bead IDs for status updates
            beads = await self.workspace_manager._bead_manager.list_beads(
                convoy_id=convoy.convoy_id,
            )
            for bead in beads:
                subtask_id = bead.payload.get("subtask_id", "")
                if subtask_id:
                    self._bead_ids[subtask_id] = bead.bead_id

            logger.info(
                "convoy_created",
                convoy_id=convoy.convoy_id,
                bead_count=len(beads),
            )

        except (RuntimeError, OSError, ValueError, ConnectionError, asyncio.TimeoutError) as e:
            logger.warning("Failed to create convoy: %s", e)

    async def _update_bead_status(
        self,
        subtask_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        """Update bead status for a subtask."""
        if not self.enable_convoy_tracking or self.workspace_manager is None:
            return

        bead_id = self._bead_ids.get(subtask_id)
        if not bead_id:
            return

        try:
            if status == "running":
                await self.workspace_manager._bead_manager.start_bead(bead_id)
            elif status == "done":
                await self.workspace_manager.complete_bead(bead_id)
            elif status == "failed":
                await self.workspace_manager.fail_bead(bead_id, error or "Unknown error")
        except (RuntimeError, OSError, ValueError, ConnectionError, asyncio.TimeoutError) as e:
            logger.debug("Failed to update bead %s: %s", bead_id, e)

    async def _complete_convoy(
        self,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Mark the convoy as completed or failed."""
        if not self.enable_convoy_tracking or self.workspace_manager is None:
            return
        if not self._convoy_id:
            return

        try:
            if success:
                await self.workspace_manager.complete_convoy(self._convoy_id)
            else:
                tracker = self.workspace_manager._convoy_tracker
                await tracker.fail_convoy(self._convoy_id, error or "Orchestration failed")
        except (RuntimeError, OSError, ValueError, ConnectionError, asyncio.TimeoutError) as e:
            logger.debug("Failed to complete convoy: %s", e)

    def _hierarchical_to_orchestration_result(
        self,
        h_result: Any,
        goal: str,
        start_time: datetime,
    ) -> OrchestrationResult:
        """Convert HierarchicalResult to OrchestrationResult for backward compat."""
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        # Convert worker reports to AgentAssignments
        assignments: list[AgentAssignment] = []
        for report in h_result.worker_reports:
            subtask = SubTask(
                id=report.assignment_id,
                title=report.subtask_title,
                description="",
            )
            assignment = AgentAssignment(
                subtask=subtask,
                track=Track.DEVELOPER,
                agent_type=self.config.judge_agent
                if hasattr(self, "config") and hasattr(self.config, "judge_agent")
                else "claude",
                status="completed" if report.success else "failed",
                result=report.output,
            )
            assignments.append(assignment)

        completed = sum(1 for r in h_result.worker_reports if r.success)
        failed = sum(1 for r in h_result.worker_reports if not r.success)

        return OrchestrationResult(
            goal=goal,
            total_subtasks=len(h_result.worker_reports),
            completed_subtasks=completed,
            failed_subtasks=failed,
            skipped_subtasks=0,
            assignments=assignments,
            duration_seconds=duration,
            success=h_result.success,
            summary=f"Hierarchical coordination: {completed}/{len(h_result.worker_reports)} tasks completed "
            f"in {h_result.cycles_used} cycles",
        )

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    async def execute_track(
        self,
        track: str,
        focus_areas: list[str] | None = None,
        max_cycles: int = 3,
    ) -> OrchestrationResult:
        """
        Execute work for a specific track.

        Args:
            track: Track name (sme, developer, self_hosted, qa, core, security)
            focus_areas: Optional list of focus areas within the track
            max_cycles: Maximum cycles per subtask

        Returns:
            OrchestrationResult
        """
        goal = f"Improve {track} track capabilities"
        if focus_areas:
            goal += f", focusing on: {', '.join(focus_areas)}"

        return await self.execute_goal(
            goal=goal,
            tracks=[track],
            max_cycles=max_cycles,
        )

    def get_active_assignments(self) -> list[AgentAssignment]:
        """Get currently active assignments."""
        return self._active_assignments.copy()

    def get_completed_assignments(self) -> list[AgentAssignment]:
        """Get completed assignments."""
        return self._completed_assignments.copy()

    # =========================================================================
    # Agent Fabric integration
    # =========================================================================

    async def _fabric_register_agent(self, assignment: AgentAssignment) -> str | None:
        """Register an agent with the Fabric for lifecycle management.

        Returns the Fabric agent_id if registered, None otherwise.
        """
        if not self.agent_fabric:
            return None

        try:
            from aragora.fabric.models import AgentConfig as FabricAgentConfig

            config = FabricAgentConfig(
                id=f"{assignment.agent_type}-{assignment.subtask.id[:8]}",
                model=assignment.agent_type,
                tools=["code", "test", "lint"],
                max_concurrent_tasks=1,
            )
            handle = await self.agent_fabric.spawn(config)
            fabric_id = handle.agent_id if hasattr(handle, "agent_id") else str(handle)
            logger.debug(
                "[fabric] Spawned agent %s for subtask %s",
                fabric_id,
                assignment.subtask.id,
            )
            return fabric_id
        except (ImportError, TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[fabric] Agent registration failed: %s", e)
            return None

    async def _fabric_track_usage(
        self,
        assignment: AgentAssignment,
        cost_usd: float = 0.0,
        tokens: int = 0,
    ) -> None:
        """Track usage in Fabric's BudgetManager for cost enforcement."""
        if not self.agent_fabric:
            return

        try:
            from aragora.fabric.models import Usage

            agent_id = f"{assignment.agent_type}-{assignment.subtask.id[:8]}"
            usage = Usage(
                agent_id=agent_id,
                tokens_input=tokens,
                cost_usd=cost_usd,
                task_id=f"subtask:{assignment.subtask.id}",
            )
            await self.agent_fabric.track_usage(usage)
        except (ImportError, TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[fabric] Usage tracking failed: %s", e)

    async def _fabric_complete_task(
        self,
        assignment: AgentAssignment,
        success: bool,
    ) -> None:
        """Notify Fabric that a task completed (for scheduler cleanup)."""
        if not self.agent_fabric:
            return

        try:
            task_id = f"task-{assignment.subtask.id}"
            error = None if success else "Task failed"
            await self.agent_fabric.complete_task(task_id, result=None, error=error)
            # Terminate the agent after task completion
            agent_id = f"{assignment.agent_type}-{assignment.subtask.id[:8]}"
            await self.agent_fabric.terminate(agent_id, graceful=True)
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[fabric] Task completion notification failed: %s", e)

    async def _fabric_notify_agents(
        self,
        message: str,
        exclude_agent: str | None = None,
    ) -> None:
        """Broadcast a message to all active agents via Fabric's NudgeRouter."""
        if not self.agent_fabric:
            return

        try:
            from aragora.fabric.nudge import NudgeRouter  # noqa: F401

            router = getattr(self.agent_fabric, "_nudge_router", None)
            if router:
                await router.broadcast(
                    sender="orchestrator",
                    content=message,
                    exclude=[exclude_agent] if exclude_agent else None,
                )
        except (ImportError, TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[fabric] Agent notification failed: %s", e)

    async def get_fabric_stats(self) -> dict[str, Any] | None:
        """Get Fabric orchestration statistics for dashboard display."""
        if not self.agent_fabric:
            return None

        try:
            return await self.agent_fabric.get_fabric_stats()
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[fabric] Stats retrieval failed: %s", e)
            return None

    async def schedule_scan(
        self,
        interval_hours: float = 24,
        max_cycles: int = 0,
        auto_execute_low_risk: bool = False,
    ) -> None:
        """Run periodic MetaPlanner scan cycles on a timer.

        Each cycle runs MetaPlanner in ``scan_mode`` to gather codebase signals
        (git log, test failures, lint violations, TODOs) and queue discovered
        goals to the ImprovementQueue. No goals are auto-executed unless
        ``auto_execute_low_risk`` is explicitly set.

        Args:
            interval_hours: Hours between scan cycles (default 24).
            max_cycles: Stop after this many cycles (0 = run forever).
            auto_execute_low_risk: When True, low-risk goals (test fixes,
                lint, doc updates) are executed immediately without approval.
        """
        from aragora.nomic.meta_planner import MetaPlanner, MetaPlannerConfig

        config = MetaPlannerConfig(
            scan_mode=True,
            auto_execute_low_risk=auto_execute_low_risk,
            quick_mode=False,
        )
        planner = MetaPlanner(config)
        interval_seconds = interval_hours * 3600
        cycle_count = 0

        logger.info(
            "schedule_scan_started interval_hours=%.1f max_cycles=%d auto_low_risk=%s",
            interval_hours,
            max_cycles,
            auto_execute_low_risk,
        )

        while True:
            cycle_count += 1
            logger.info("scan_cycle_start cycle=%d", cycle_count)

            try:
                goals = await planner.prioritize_work(
                    objective=None,  # Self-directing scan mode
                    available_tracks=list(Track),
                )

                if not goals:
                    logger.info("scan_cycle_no_goals cycle=%d", cycle_count)
                else:
                    # Queue goals for future execution
                    try:
                        from aragora.nomic.improvement_queue import (
                            get_improvement_queue,
                            ImprovementSuggestion,
                        )

                        queue = get_improvement_queue()
                        for goal in goals:
                            queue.enqueue(
                                ImprovementSuggestion(
                                    debate_id=f"scan-cycle-{cycle_count}",
                                    task=goal.description,
                                    suggestion=goal.description,
                                    category=goal.track.value,
                                    confidence=0.8 if goal.estimated_impact == "high" else 0.5,
                                )
                            )
                        logger.info(
                            "scan_cycle_queued cycle=%d goals=%d",
                            cycle_count,
                            len(goals),
                        )
                    except ImportError:
                        logger.debug("ImprovementQueue not available, goals not queued")

                    # Auto-execute low-risk goals if enabled
                    if auto_execute_low_risk:
                        auto_goals, _ = planner.filter_auto_executable(goals)
                        for goal in auto_goals:
                            try:
                                await self.execute_goal(
                                    goal=goal.description,
                                    tracks=[goal.track.value],
                                    max_cycles=3,
                                )
                                logger.info(
                                    "scan_auto_executed goal=%s track=%s",
                                    goal.description[:60],
                                    goal.track.value,
                                )
                            except (RuntimeError, ValueError, OSError) as exc:
                                logger.warning(
                                    "scan_auto_execute_failed goal=%s: %s",
                                    goal.description[:60],
                                    exc,
                                )

            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("scan_cycle_failed cycle=%d: %s", cycle_count, exc)

            if max_cycles > 0 and cycle_count >= max_cycles:
                logger.info("scan_schedule_complete cycles=%d", cycle_count)
                break

            await asyncio.sleep(interval_seconds)


# Singleton instance
_orchestrator_instance: AutonomousOrchestrator | None = None


def get_orchestrator(
    **kwargs: Any,
) -> AutonomousOrchestrator:
    """Get or create the singleton orchestrator instance."""
    global _orchestrator_instance

    if _orchestrator_instance is None:
        _orchestrator_instance = AutonomousOrchestrator(**kwargs)

    return _orchestrator_instance


def reset_orchestrator() -> None:
    """Reset the singleton (for testing)."""
    global _orchestrator_instance
    _orchestrator_instance = None


__all__ = [
    "AutonomousOrchestrator",
    "AgentRouter",
    "BudgetExceededError",
    "FeedbackLoop",
    "HierarchyConfig",
    "Track",
    "TrackConfig",
    "AgentAssignment",
    "OrchestrationResult",
    "get_orchestrator",
    "reset_orchestrator",
]
