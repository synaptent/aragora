"""Self-Improvement Pipeline -- Aragora improving itself.

Chains: MetaPlanner -> TaskDecomposer -> WorktreeManager -> Execution ->
        BranchCoordinator -> OutcomeTracker -> CycleLearningStore

Usage:
    pipeline = SelfImprovePipeline()
    result = await pipeline.run("Make Aragora better for SMEs")

Dry-run (preview without executing):
    plan = await pipeline.dry_run("Improve test coverage")
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
import types
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from aragora.nomic.self_improve_execution import BudgetExceededError, SelfImproveExecutionMixin

logger = logging.getLogger(__name__)


@dataclass
class SelfImproveConfig:
    """Configuration for the self-improvement pipeline."""

    # Planning
    use_meta_planner: bool = True  # Debate-driven prioritization
    quick_mode: bool = False  # Skip debate, use heuristics
    scan_mode: bool = True  # Use codebase signals, no LLM calls
    max_goals: int = 5

    # Execution
    use_worktrees: bool = True  # Isolated worktrees per subtask
    max_parallel: int = 4  # Max parallel worktrees
    coordination_managed_worktrees: bool = True  # Allocate via autopilot-managed sessions
    coordination_managed_dir: str = ".worktrees/codex-auto"
    coordination_managed_strategy: str = "merge"
    coordination_managed_agent: str = "nomic-self-improve"
    budget_limit_usd: float = 10.0  # Total budget cap
    require_approval: bool = True  # Human approval at checkpoints
    autonomous: bool = False  # Skip approval gates for fully autonomous runs
    auto_mode: bool = False  # Risk-based auto-execution (low=execute, high=defer)
    approval_callback_url: str | None = None  # URL for API approval mode
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None

    # Verification
    run_tests: bool = True
    run_review: bool = True  # PRReviewRunner on diffs
    capture_metrics: bool = True  # Before/after debate quality

    # Codebase metrics (before/after measurement)
    enable_codebase_metrics: bool = True
    metrics_test_scope: list[str] = field(default_factory=list)
    metrics_test_timeout: int = 120

    # Codebase knowledge indexing (semantic module summaries + dependency graph)
    enable_codebase_indexing: bool = True

    # Debug loop: iterative test-failure-feedback-retry execution
    enable_debug_loop: bool = True
    debug_loop_max_retries: int = 3

    # Risk-scored safe mode
    safe_mode: bool = True  # Enable risk-based execution gating
    risk_threshold: float = 0.5  # Auto-execute below this score

    # Curriculum: SOAR stepping stones for failed tasks
    enable_curriculum: bool = True
    curriculum_min_failures: int = 2  # Min failed subtasks to trigger curriculum

    # Gauntlet: adversarial validation of changes
    enable_gauntlet_validation: bool = True
    gauntlet_min_files: int = 3  # Min files changed to trigger gauntlet

    # Feedback
    persist_outcomes: bool = True  # Save to CycleLearningStore
    auto_revert_on_regression: bool = True
    degradation_threshold: float = 0.05


# Domain tag mapping: path prefix → domain tag
_DOMAIN_TAG_MAP: list[tuple[str, str]] = [
    ("aragora/debate/", "debate"),
    ("aragora/server/", "server"),
    ("aragora/nomic/", "nomic"),
    ("aragora/knowledge/", "knowledge"),
    ("aragora/pipeline/", "pipeline"),
    ("aragora/agents/", "agents"),
    ("aragora/memory/", "memory"),
    ("aragora/ranking/", "ranking"),
    ("aragora/connectors/", "connectors"),
    ("aragora/resilience/", "resilience"),
    ("aragora/security/", "security"),
    ("aragora/auth/", "auth"),
    ("aragora/rbac/", "rbac"),
    ("aragora/workflow/", "workflow"),
    ("aragora/analytics/", "analytics"),
    ("aragora/live/", "frontend"),
    ("tests/", "tests"),
]


def _infer_domain_tags(files_changed: list[str]) -> list[str]:
    """Infer domain tags from changed file paths.

    Maps file paths to domain categories for cross-cycle search boosting.
    """
    tags: set[str] = set()
    for fpath in files_changed:
        # Normalize to relative path
        normalized = fpath.replace("\\", "/")
        for prefix, tag in _DOMAIN_TAG_MAP:
            if prefix in normalized:
                tags.add(tag)
                break
    return sorted(tags)


@dataclass
class SelfImproveResult:
    """Result of a self-improvement cycle."""

    cycle_id: str
    objective: str
    goals_planned: int = 0
    subtasks_total: int = 0
    subtasks_completed: int = 0
    subtasks_failed: int = 0
    files_changed: list[str] = field(default_factory=list)
    tests_passed: int = 0
    tests_failed: int = 0
    regressions_detected: bool = False
    reverted: bool = False
    duration_seconds: float = 0.0
    # Codebase metrics delta (from MetricsCollector)
    metrics_delta: dict[str, Any] = field(default_factory=dict)
    improvement_score: float = 0.0
    # Budget tracking
    total_cost_usd: float = 0.0
    # KnowledgeMound persistence
    km_persisted: bool = False
    # Risk assessment results
    risk_assessments: list[dict[str, Any]] = field(default_factory=list)
    goals_blocked: int = 0
    goals_auto_approved: int = 0
    goals_needs_review: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to a plain dictionary."""
        return {
            "cycle_id": self.cycle_id,
            "objective": self.objective,
            "goals_planned": self.goals_planned,
            "subtasks_total": self.subtasks_total,
            "subtasks_completed": self.subtasks_completed,
            "subtasks_failed": self.subtasks_failed,
            "files_changed": self.files_changed,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "regressions_detected": self.regressions_detected,
            "reverted": self.reverted,
            "duration_seconds": self.duration_seconds,
            "metrics_delta": self.metrics_delta,
            "improvement_score": self.improvement_score,
            "total_cost_usd": self.total_cost_usd,
            "km_persisted": self.km_persisted,
            "risk_assessments": self.risk_assessments,
            "goals_blocked": self.goals_blocked,
            "goals_auto_approved": self.goals_auto_approved,
            "goals_needs_review": self.goals_needs_review,
        }


class _SelfImproveOrchestrationAdapter:
    """Adapter to make SelfImproveResult look like OrchestrationResult for NomicPipelineBridge.

    NomicPipelineBridge.create_pipeline_from_cycle() expects an OrchestrationResult
    with .goal, .summary, .assignments, .success, .duration_seconds, .improvement_score.
    This adapter wraps a SelfImproveResult to provide that interface.
    """

    def __init__(self, cycle_id: str, result: SelfImproveResult) -> None:
        self.goal = result.objective
        self.summary = f"Cycle {cycle_id}: {result.subtasks_completed}/{result.subtasks_total} subtasks completed"
        self.success = result.subtasks_completed > 0 and not result.regressions_detected
        self.duration_seconds = result.duration_seconds
        self.improvement_score = result.improvement_score
        # Build minimal assignment-like objects from result data
        self.assignments = _build_assignments_from_result(result)


def _build_assignments_from_result(result: SelfImproveResult) -> list[Any]:
    """Build minimal assignment-like objects for pipeline bridge consumption."""
    assignments = []
    for i, f in enumerate(result.files_changed[:20]):  # Cap at 20 for visualization
        assignment = types.SimpleNamespace(
            status="completed",
            agent_type="self_improve",
            track=types.SimpleNamespace(value="core"),
            subtask=types.SimpleNamespace(
                id=f"si-{i}",
                title=f"Modified: {f}",
                description="File changed during self-improvement cycle",
                file_scope=[f],
                estimated_complexity="medium",
                dependencies=[],
            ),
        )
        assignments.append(assignment)
    return assignments


class SelfImprovePipeline(SelfImproveExecutionMixin):
    """The full self-improvement pipeline.

    Orchestrates the complete cycle:
    1. Plan: MetaPlanner debates priorities -> TaskDecomposer breaks into subtasks
    2. Baseline: OutcomeTracker captures pre-change debate quality metrics
    3. Execute: WorktreeManager creates isolation -> agents implement subtasks
    4. Verify: Run tests + PRReviewRunner on each branch
    5. Merge: BranchCoordinator merges passing branches
    6. Measure: OutcomeTracker captures post-change metrics, compares
    7. Learn: CycleLearningStore persists outcomes for next cycle
    """

    def __init__(self, config: SelfImproveConfig | None = None):
        self.config = config or SelfImproveConfig()
        self._total_spend_usd: float = 0.0

    def _emit_progress(self, event: str, data: dict[str, Any]) -> None:
        """Emit a progress event via the configured callback."""
        if self.config.progress_callback:
            try:
                self.config.progress_callback(event, data)
            except (TypeError, ValueError, RuntimeError, AttributeError):
                logger.debug("progress_callback failed")

    async def run(self, objective: str | None = None) -> SelfImproveResult:
        """Run a full self-improvement cycle.

        Args:
            objective: High-level objective like "Improve test coverage".
                       None for self-directing mode (scan generates goals).

        Returns:
            SelfImproveResult with cycle outcomes
        """
        cycle_id = f"cycle_{uuid.uuid4().hex[:12]}"
        start_time = time.time()
        effective_objective = objective or "self-directed codebase improvement"
        result = SelfImproveResult(cycle_id=cycle_id, objective=effective_objective)

        logger.info(
            "self_improve_started cycle=%s objective=%s self_directing=%s",
            cycle_id,
            effective_objective[:100],
            objective is None,
        )
        self._emit_progress(
            "cycle_started", {"cycle_id": cycle_id, "objective": effective_objective}
        )

        # Step 0: Index codebase for richer planning context
        if self.config.enable_codebase_indexing:
            await self._index_codebase()

        # Step 1: Plan (None objective triggers scan-based goal synthesis)
        goals = await self._plan(objective)
        result.goals_planned = len(goals)
        self._emit_progress("planning_complete", {"goals": len(goals)})

        # In self-directing mode, synthesize objective from top goal
        if objective is None and goals:
            top_desc = getattr(goals[0], "description", str(goals[0]))
            effective_objective = f"[scan] {top_desc[:100]}"
            result.objective = effective_objective

        if not goals:
            logger.warning("self_improve_no_goals cycle=%s", cycle_id)
            result.duration_seconds = time.time() - start_time
            return result

        # Step 2: Decompose goals into subtasks
        subtasks = await self._decompose(goals)
        result.subtasks_total = len(subtasks)
        self._emit_progress("decomposition_complete", {"subtasks": len(subtasks)})

        # Step 2b: Risk scoring (when safe_mode is enabled)
        if self.config.safe_mode:
            subtasks = self._apply_risk_scoring(subtasks, result)
            if not subtasks:
                logger.warning("self_improve_all_blocked cycle=%s", cycle_id)
                result.duration_seconds = time.time() - start_time
                return result

        # Step 3: Capture baseline metrics
        baseline = None
        if self.config.capture_metrics:
            baseline = await self._capture_baseline()

        # Step 4: Execute subtasks (in worktrees if configured)
        execution_results = await self._execute(subtasks, cycle_id)

        for er in execution_results:
            if er.get("success"):
                result.subtasks_completed += 1
                result.files_changed.extend(er.get("files_changed", []))
                result.tests_passed += er.get("tests_passed", 0)
            else:
                result.subtasks_failed += 1
                result.tests_failed += er.get("tests_failed", 0)

        self._emit_progress(
            "execution_complete",
            {
                "completed": result.subtasks_completed,
                "failed": result.subtasks_failed,
            },
        )

        # Step 4b: Curriculum — generate SOAR stepping stones for repeated failures
        if (
            self.config.enable_curriculum
            and result.subtasks_failed >= self.config.curriculum_min_failures
        ):
            self._generate_curriculum_stepping_stones(cycle_id, result, subtasks)

        # Step 4c: Gauntlet — adversarial validation of changes with >= N files
        if (
            self.config.enable_gauntlet_validation
            and len(result.files_changed) >= self.config.gauntlet_min_files
        ):
            gauntlet_passed = await self._run_gauntlet_validation(
                cycle_id, result, effective_objective
            )
            if not gauntlet_passed:
                logger.warning(
                    "self_improve_gauntlet_rejected cycle=%s files=%d",
                    cycle_id,
                    len(result.files_changed),
                )
                result.regressions_detected = True

        # Step 5: Capture post-change metrics and compare
        outcome_comparison = None  # OutcomeComparison for feedback loop
        after = None
        if self.config.capture_metrics and baseline is not None:
            after = await self._capture_after()
            if after is not None:
                comparison = self._compare_metrics(baseline, after)

                if comparison:
                    result.metrics_delta = comparison.get("deltas", {})
                    result.improvement_score = comparison.get("improvement_score", 0.0)
                    outcome_comparison = comparison.get("_outcome_comparison")

                    if not comparison.get("improved", True):
                        result.regressions_detected = True
                        if self.config.auto_revert_on_regression:
                            logger.warning(
                                "self_improve_regression cycle=%s recommendation=%s",
                                cycle_id,
                                comparison.get("recommendation"),
                            )
                            # Don't auto-revert yet -- log and let human decide
                            # result.reverted = True

        # Step 5b: Semantic goal evaluation
        goal_eval = self._evaluate_goal(effective_objective, subtasks, result, baseline, after)
        if goal_eval is not None:
            result.metrics_delta["goal_achievement"] = goal_eval.achievement_score
            result.metrics_delta["goal_scope_coverage"] = goal_eval.scope_coverage
            result.metrics_delta["goal_diff_relevance"] = goal_eval.diff_relevance
            if not goal_eval.achieved:
                logger.warning(
                    "self_improve_goal_not_achieved cycle=%s score=%.2f",
                    cycle_id,
                    goal_eval.achievement_score,
                )

        # Step 6: Persist outcomes (with OutcomeComparison for feedback loop)
        if self.config.persist_outcomes:
            self._persist_outcome(cycle_id, result, outcome_comparison)

        # Step 7: Run feedback orchestrator (6-step audit→active bridge)
        self._run_feedback_orchestrator(cycle_id, execution_results)

        # Step 8: Publish to pipeline visualization graph
        self._publish_to_pipeline_graph(cycle_id, result)

        result.duration_seconds = time.time() - start_time
        result.total_cost_usd = self._total_spend_usd
        logger.info(
            "self_improve_completed cycle=%s goals=%d subtasks=%d/%d duration=%.1fs cost=$%.4f",
            cycle_id,
            result.goals_planned,
            result.subtasks_completed,
            result.subtasks_total,
            result.duration_seconds,
            result.total_cost_usd,
        )
        self._emit_progress(
            "cycle_complete",
            {
                "completed": result.subtasks_completed,
                "failed": result.subtasks_failed,
                "duration": result.duration_seconds,
            },
        )

        return result

    async def dry_run(self, objective: str | None = None) -> dict[str, Any]:
        """Preview what the pipeline would do without executing.

        Returns the plan (goals + subtasks) without making any changes.
        """
        goals = await self._plan(objective)
        subtasks = await self._decompose(goals)

        # Synthesize objective label from top goal in self-directing mode
        effective_objective = objective
        if effective_objective is None and goals:
            top_desc = getattr(goals[0], "description", str(goals[0]))
            effective_objective = f"[scan] {top_desc[:100]}"
        elif effective_objective is None:
            effective_objective = "self-directed codebase improvement"

        # Risk assessments for dry-run preview
        risk_assessments: list[dict[str, Any]] = []
        if self.config.safe_mode:
            try:
                from aragora.nomic.risk_scorer import RiskScorer

                scorer = RiskScorer(
                    threshold=self.config.risk_threshold,
                )
                for s in subtasks:
                    assessment = scorer.score_subtask(s)
                    risk_assessments.append(assessment.to_dict())
            except ImportError:
                logger.debug("RiskScorer unavailable for dry-run preview")
            except (RuntimeError, ValueError, TypeError) as exc:
                logger.debug("Risk scoring failed in dry-run: %s", exc)

        return {
            "objective": effective_objective,
            "goals": [
                {
                    "description": getattr(g, "description", str(g)),
                    "track": (
                        g.track.value
                        if hasattr(g, "track") and hasattr(g.track, "value")
                        else str(getattr(g, "track", "core"))
                    ),
                    "priority": getattr(g, "priority", 0),
                    "estimated_impact": getattr(g, "estimated_impact", "unknown"),
                    "rationale": getattr(g, "rationale", ""),
                }
                for g in goals
            ],
            "subtasks": [
                {
                    "title": getattr(s, "title", None) or getattr(s, "original_task", str(s)),
                    "description": getattr(s, "description", str(s)),
                    "scope": getattr(s, "scope", "unknown"),
                    "file_hints": getattr(s, "file_scope", []),
                    "success_criteria": getattr(s, "success_criteria", {}),
                }
                for s in subtasks
            ],
            "risk_assessments": risk_assessments,
            "config": {
                "use_worktrees": self.config.use_worktrees,
                "max_parallel": self.config.max_parallel,
                "budget_limit_usd": self.config.budget_limit_usd,
                "safe_mode": self.config.safe_mode,
                "risk_threshold": self.config.risk_threshold,
            },
        }

    # --- Private pipeline steps ---

    def _apply_risk_scoring(self, subtasks: list[Any], result: SelfImproveResult) -> list[Any]:
        """Score subtasks for risk and filter based on safe_mode thresholds.

        Returns the subset of subtasks that are approved for execution.
        Blocked subtasks are logged and their assessments stored in the result.
        """
        try:
            from aragora.nomic.risk_scorer import RiskScorer
        except ImportError:
            logger.debug("RiskScorer unavailable, skipping risk scoring")
            return subtasks

        scorer = RiskScorer(
            threshold=self.config.risk_threshold,
        )

        approved: list[Any] = []
        for subtask in subtasks:
            assessment = scorer.score_subtask(subtask)
            assessment_dict = assessment.to_dict()
            result.risk_assessments.append(assessment_dict)

            if assessment.recommendation == "block":
                result.goals_blocked += 1
                title = getattr(subtask, "title", str(subtask))
                logger.warning(
                    "risk_blocked subtask=%s score=%.3f category=%s",
                    title[:60],
                    assessment.score,
                    assessment.category.value,
                )
                self._emit_progress(
                    "risk_blocked",
                    {
                        "subtask": title[:80],
                        "score": assessment.score,
                        "category": assessment.category.value,
                    },
                )
            elif assessment.recommendation == "review":
                result.goals_needs_review += 1
                title = getattr(subtask, "title", str(subtask))
                logger.info(
                    "risk_review_needed subtask=%s score=%.3f category=%s",
                    title[:60],
                    assessment.score,
                    assessment.category.value,
                )
                self._emit_progress(
                    "risk_review_needed",
                    {
                        "subtask": title[:80],
                        "score": assessment.score,
                        "category": assessment.category.value,
                    },
                )
                approved.append(subtask)
            else:
                result.goals_auto_approved += 1
                approved.append(subtask)

        self._emit_progress(
            "risk_assessment_complete",
            {
                "total": len(subtasks),
                "auto_approved": result.goals_auto_approved,
                "needs_review": result.goals_needs_review,
                "blocked": result.goals_blocked,
            },
        )

        logger.info(
            "risk_scoring_complete total=%d auto=%d review=%d blocked=%d",
            len(subtasks),
            result.goals_auto_approved,
            result.goals_needs_review,
            result.goals_blocked,
        )

        return approved

    async def _index_codebase(self) -> None:
        """Index codebase structure into MemoryFabric for planning context.

        Runs CodebaseKnowledgeBuilder to ingest module summaries and
        dependency graph. Non-fatal: failures are logged and swallowed.
        """
        try:
            from pathlib import Path as P

            from aragora.memory.codebase_builder import CodebaseKnowledgeBuilder
            from aragora.memory.fabric import MemoryFabric

            fabric = MemoryFabric()
            builder = CodebaseKnowledgeBuilder(fabric, P.cwd())

            summary_stats = await builder.ingest_module_summaries(max_modules=30)
            dep_stats = await builder.ingest_dependency_graph(max_files=100)

            logger.info(
                "codebase_indexed summaries=%d deps=%d errors=%d",
                summary_stats.items_ingested,
                dep_stats.items_ingested,
                summary_stats.errors + dep_stats.errors,
            )
        except ImportError as exc:
            logger.debug("CodebaseKnowledgeBuilder unavailable: %s", exc)
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Codebase indexing failed: %s", exc)

    async def _plan(self, objective: str | None) -> list[Any]:
        """Step 1: Use MetaPlanner to prioritize goals.

        When objective is None (self-directing mode), MetaPlanner uses
        scan_mode to derive goals purely from codebase signals.
        """
        if not self.config.use_meta_planner:
            if objective is None:
                # Can't do direct objective mode without an objective
                logger.warning("self_directing requires use_meta_planner=True, enabling scan")
                self.config.use_meta_planner = True
                self.config.scan_mode = True
            else:
                # Return a single goal: the objective itself
                try:
                    from aragora.nomic.meta_planner import PrioritizedGoal, Track

                    return [
                        PrioritizedGoal(
                            id="direct",
                            track=Track.CORE,
                            description=objective,
                            rationale="Direct objective (no meta-planning)",
                            estimated_impact="high",
                            priority=1,
                        )
                    ]
                except ImportError:
                    logger.warning("PrioritizedGoal not importable, returning raw goal")
                    return [objective]

        try:
            from aragora.nomic.meta_planner import MetaPlanner, MetaPlannerConfig

            config = MetaPlannerConfig(
                quick_mode=self.config.quick_mode,
                scan_mode=self.config.scan_mode,
                max_goals=self.config.max_goals,
            )
            planner = MetaPlanner(config)
            # objective=None triggers self-directing scan in MetaPlanner
            goals = await planner.prioritize_work(objective=objective)
            return goals
        except ImportError as exc:
            logger.warning("MetaPlanner unavailable: %s", exc)
        except (RuntimeError, ValueError, OSError) as exc:
            logger.warning("MetaPlanner failed, using direct objective: %s", exc)

        # Fallback: wrap objective as a single PrioritizedGoal
        try:
            from aragora.nomic.meta_planner import PrioritizedGoal, Track

            return [
                PrioritizedGoal(
                    id="fallback",
                    track=Track.CORE,
                    description=objective,
                    rationale="MetaPlanner fallback",
                    estimated_impact="medium",
                    priority=1,
                )
            ]
        except ImportError:
            return [objective]

    async def _decompose(self, goals: list[Any]) -> list[Any]:
        """Step 2: Use TaskDecomposer to break goals into subtasks."""
        all_subtasks: list[Any] = []
        try:
            from aragora.nomic.task_decomposer import TaskDecomposer

            decomposer = TaskDecomposer()
            for goal in goals:
                desc = getattr(goal, "description", str(goal))
                decomposition = decomposer.analyze(desc)
                if decomposition.should_decompose:
                    subtasks = decomposition.subtasks
                    # Enrich with KM learnings (async overlay)
                    try:
                        subtasks = await decomposer.enrich_subtasks_from_km(desc, subtasks)
                    except (RuntimeError, ValueError, OSError) as km_exc:
                        logger.debug("KM enrichment skipped: %s", km_exc)
                    all_subtasks.extend(subtasks)
                else:
                    # Simple enough to be its own subtask
                    all_subtasks.append(decomposition)
        except ImportError as exc:
            logger.warning("TaskDecomposer unavailable: %s", exc)
            # Fall back to treating each goal as a single task
            for goal in goals:
                all_subtasks.append(goal)
        except (RuntimeError, ValueError) as exc:
            logger.warning("TaskDecomposer failed: %s", exc)
            for goal in goals:
                all_subtasks.append(goal)

        # Enrich subtasks with file_scope from CodebaseIndexer
        if all_subtasks and self.config.enable_codebase_indexing:
            await self._enrich_file_scope(all_subtasks)

        return all_subtasks

    async def _enrich_file_scope(self, subtasks: list[Any]) -> None:
        """Populate empty file_scope on subtasks using CodebaseIndexer.

        For each subtask with an empty ``file_scope``, queries the
        CodebaseIndexer for modules matching the subtask's title and
        description, then sets ``file_scope`` to the matching paths.
        """
        try:
            from aragora.nomic.codebase_indexer import CodebaseIndexer

            indexer = CodebaseIndexer(repo_path=".", max_modules=50)
            await indexer.index()

            for subtask in subtasks:
                scope = getattr(subtask, "file_scope", None)
                if scope is not None and len(scope) == 0:
                    title = getattr(subtask, "title", "")
                    desc = getattr(subtask, "description", str(subtask))
                    query = f"{title} {desc}".strip()
                    if query:
                        matches = await indexer.query(query, limit=5)
                        subtask.file_scope = [str(m.path) for m in matches]

            logger.info(
                "file_scope_enrichment subtasks=%d",
                sum(1 for s in subtasks if getattr(s, "file_scope", None)),
            )
        except ImportError:
            logger.debug("CodebaseIndexer unavailable, skipping file scope enrichment")
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("File scope enrichment failed: %s", exc)

    async def _capture_baseline(self) -> Any:
        """Step 3: Capture pre-change metrics (debate quality + codebase health)."""
        combined: dict[str, Any] = {"debate": None, "codebase": None}

        # Debate quality baseline
        try:
            from aragora.nomic.outcome_tracker import NomicOutcomeTracker

            tracker = NomicOutcomeTracker()
            combined["debate"] = await tracker.capture_baseline()
        except ImportError as exc:
            logger.debug("Outcome tracker unavailable for baseline: %s", exc)
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Debate baseline capture failed: %s", exc)

        # Codebase health baseline
        if self.config.enable_codebase_metrics:
            try:
                from aragora.nomic.metrics_collector import (
                    MetricsCollector,
                    MetricsCollectorConfig,
                )

                mc_config = MetricsCollectorConfig(
                    test_timeout=self.config.metrics_test_timeout,
                    test_scope_dirs=list(self.config.metrics_test_scope),
                )
                collector = MetricsCollector(mc_config)
                snapshot = await collector.collect_baseline("self-improve")
                combined["codebase"] = snapshot.to_dict()
                # Stash collector for reuse in _capture_after
                self._metrics_collector = collector
            except ImportError as exc:
                logger.debug("MetricsCollector unavailable for baseline: %s", exc)
            except (RuntimeError, ValueError, OSError) as exc:
                logger.debug("Codebase baseline capture failed: %s", exc)

        if combined["debate"] is None and combined["codebase"] is None:
            return None
        return combined

    async def _capture_after(self) -> Any:
        """Step 5a: Capture post-change metrics (debate quality + codebase health)."""
        combined: dict[str, Any] = {"debate": None, "codebase": None}

        # Debate quality after
        try:
            from aragora.nomic.outcome_tracker import NomicOutcomeTracker

            tracker = NomicOutcomeTracker()
            combined["debate"] = await tracker.capture_after()
        except ImportError as exc:
            logger.debug("Outcome tracker unavailable for after: %s", exc)
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Debate after capture failed: %s", exc)

        # Codebase health after (reuse collector from baseline for consistent config)
        if self.config.enable_codebase_metrics:
            try:
                collector = getattr(self, "_metrics_collector", None)
                if collector is None:
                    from aragora.nomic.metrics_collector import (
                        MetricsCollector,
                        MetricsCollectorConfig,
                    )

                    mc_config = MetricsCollectorConfig(
                        test_timeout=self.config.metrics_test_timeout,
                        test_scope_dirs=list(self.config.metrics_test_scope),
                    )
                    collector = MetricsCollector(mc_config)

                snapshot = await collector.collect_after("self-improve")
                combined["codebase"] = snapshot.to_dict()
            except ImportError as exc:
                logger.debug("MetricsCollector unavailable for after: %s", exc)
            except (RuntimeError, ValueError, OSError) as exc:
                logger.debug("Codebase after capture failed: %s", exc)

        if combined["debate"] is None and combined["codebase"] is None:
            return None
        return combined

    def _compare_metrics(self, baseline: Any, after: Any) -> dict[str, Any] | None:
        """Step 5b: Compare baseline and after metrics (debate + codebase)."""
        if baseline is None or after is None:
            return None

        result: dict[str, Any] = {"improved": True, "recommendation": None, "deltas": {}}

        # Compare debate quality
        debate_baseline = baseline.get("debate") if isinstance(baseline, dict) else baseline
        debate_after = after.get("debate") if isinstance(after, dict) else after

        if debate_baseline is not None and debate_after is not None:
            try:
                from aragora.nomic.outcome_tracker import NomicOutcomeTracker

                tracker = NomicOutcomeTracker(
                    degradation_threshold=self.config.degradation_threshold,
                )
                comparison = tracker.compare(debate_baseline, debate_after)
                result["improved"] = comparison.improved
                result["recommendation"] = comparison.recommendation
                result["deltas"]["debate"] = comparison.metrics_delta
                # Stash the OutcomeComparison for the feedback loop
                result["_outcome_comparison"] = comparison
            except ImportError as exc:
                logger.debug("Outcome comparison unavailable: %s", exc)
            except (RuntimeError, ValueError, TypeError) as exc:
                logger.debug("Outcome comparison failed: %s", exc)

        # Compare codebase health
        codebase_baseline = baseline.get("codebase") if isinstance(baseline, dict) else None
        codebase_after = after.get("codebase") if isinstance(after, dict) else None

        if codebase_baseline is not None and codebase_after is not None:
            try:
                from aragora.nomic.metrics_collector import MetricSnapshot

                base_snap = MetricSnapshot.from_dict(codebase_baseline)
                after_snap = MetricSnapshot.from_dict(codebase_after)

                collector = getattr(self, "_metrics_collector", None)
                if collector is None:
                    from aragora.nomic.metrics_collector import MetricsCollector

                    collector = MetricsCollector()

                delta = collector.compare(base_snap, after_snap)
                result["deltas"]["codebase"] = delta.to_dict()
                result["codebase_improved"] = delta.improved
                result["improvement_score"] = delta.improvement_score

                # If codebase regressed, mark as not improved
                if not delta.improved and delta.improvement_score < 0.3:
                    result["improved"] = False
                    if not result["recommendation"]:
                        result["recommendation"] = delta.summary
            except ImportError as exc:
                logger.debug("MetricsCollector comparison unavailable: %s", exc)
            except (RuntimeError, ValueError, TypeError) as exc:
                logger.debug("Codebase comparison failed: %s", exc)

        return result

    def _evaluate_goal(
        self,
        objective: str,
        subtasks: list[Any],
        result: SelfImproveResult,
        baseline: Any,
        after: Any,
    ) -> Any:
        """Step 5b: Semantic evaluation of whether the goal was achieved.

        Uses GoalEvaluator to score scope coverage, test delta, and diff
        relevance. Returns a GoalEvaluation or None if the evaluator is
        unavailable.
        """
        try:
            from aragora.nomic.goal_evaluator import GoalEvaluator

            evaluator = GoalEvaluator()

            # Collect intended file scope from all subtasks
            file_scope: list[str] = []
            for st in subtasks:
                for f in getattr(st, "file_scope", []):
                    if f not in file_scope:
                        file_scope.append(f)

            # Test counts (before/after from codebase metrics if available)
            tests_before: dict[str, int] = {}
            tests_after: dict[str, int] = {}
            if isinstance(baseline, dict) and baseline.get("codebase"):
                cb = baseline["codebase"]
                tests_before = {
                    "passed": cb.get("test_pass_count", 0),
                    "failed": cb.get("test_fail_count", 0),
                }
            if isinstance(after, dict) and after.get("codebase"):
                ca = after["codebase"]
                tests_after = {
                    "passed": ca.get("test_pass_count", 0),
                    "failed": ca.get("test_fail_count", 0),
                }

            # Build diff summary from files changed (just the list for now)
            diff_summary = " ".join(result.files_changed)

            return evaluator.evaluate(
                goal=objective,
                file_scope=file_scope,
                files_changed=result.files_changed,
                diff_summary=diff_summary,
                tests_before=tests_before,
                tests_after=tests_after,
            )
        except ImportError:
            logger.debug("GoalEvaluator not available")
            return None
        except (RuntimeError, ValueError, TypeError) as exc:
            logger.debug("Goal evaluation failed: %s", exc)
            return None

    async def _execute(
        self,
        subtasks: list[Any],
        cycle_id: str,
    ) -> list[dict[str, Any]]:
        """Step 4: Execute subtasks, respecting dependency order.

        Groups subtasks into dependency waves using ``SubTask.dependencies``.
        Subtasks within a wave (no unmet dependencies) execute in parallel;
        waves execute sequentially.
        """
        waves = self._group_dependency_waves(subtasks)

        if self.config.use_worktrees:
            all_results: list[dict[str, Any]] = []
            for wave in waves:
                wave_results = await self._execute_in_worktrees(wave, cycle_id)
                all_results.extend(wave_results)
            return all_results

        # Sequential execution respecting wave order
        results: list[dict[str, Any]] = []
        for wave in waves:
            for subtask in wave:
                result = await self._execute_single(subtask, cycle_id)
                results.append(result)
        return results

    @staticmethod
    def _group_dependency_waves(subtasks: list[Any]) -> list[list[Any]]:
        """Group subtasks into dependency waves for ordered execution.

        Wave 0: subtasks with no dependencies (or no dependency field).
        Wave N: subtasks whose dependencies are all in waves 0..N-1.

        Falls back to a single wave (all parallel) if dependency data is
        missing or if a cycle is detected.
        """
        # Build id -> subtask map
        by_id: dict[str, Any] = {}
        for st in subtasks:
            st_id = getattr(st, "id", None)
            if st_id:
                by_id[st_id] = st

        # If no subtask has dependencies, return single wave
        has_deps = any(getattr(st, "dependencies", None) for st in subtasks)
        if not has_deps:
            return [subtasks]

        assigned: set[str] = set()
        waves: list[list[Any]] = []
        remaining = list(subtasks)
        max_iterations = len(subtasks) + 1  # cycle guard

        for _ in range(max_iterations):
            if not remaining:
                break

            wave: list[Any] = []
            still_remaining: list[Any] = []

            for st in remaining:
                deps = getattr(st, "dependencies", None) or []
                # A subtask is ready if all its deps are already assigned
                # or if the dep ID doesn't exist in the subtask set
                unmet = [d for d in deps if d in by_id and d not in assigned]
                if not unmet:
                    wave.append(st)
                else:
                    still_remaining.append(st)

            if not wave:
                # All remaining have unmet deps (cycle) — flush them
                wave = still_remaining
                still_remaining = []

            waves.append(wave)
            for st in wave:
                st_id = getattr(st, "id", None)
                if st_id:
                    assigned.add(st_id)
            remaining = still_remaining

        return waves

    async def _execute_with_coordination(
        self,
        subtasks: list[Any],
        cycle_id: str,
    ) -> list[dict[str, Any]] | None:
        """Execute subtasks using the coordination module with health monitoring.

        Uses TaskDispatcher for priority-based scheduling, WorktreeManager for
        health-tracked worktrees, HealthWatchdog for stall detection, and
        GitReconciler for conflict-aware merging.

        Returns None if the coordination module is unavailable, signaling
        fallback to BranchCoordinator.
        """
        try:
            from aragora.coordination import (
                TaskDispatcher,
                DispatcherConfig,
                WorktreeManager,
                WorktreeManagerConfig,
                HealthWatchdog,
                WatchdogConfig,
                GitReconciler,
                ReconcilerConfig,
            )
        except ImportError:
            return None

        from pathlib import Path as P

        repo_path = P.cwd()

        # Initialize coordination components
        dispatcher = TaskDispatcher(
            DispatcherConfig(
                max_retries=getattr(self.config, "debug_loop_max_retries", 2),
                max_concurrent=self.config.max_parallel,
            )
        )
        wt_manager = WorktreeManager(
            repo_path=repo_path,
            config=WorktreeManagerConfig(max_worktrees=self.config.max_parallel * 2),
        )
        watchdog = HealthWatchdog(
            worktree_manager=wt_manager,
            task_dispatcher=dispatcher,
            config=WatchdogConfig(
                check_interval_seconds=30.0,
                auto_reassign_stalled=True,
                auto_cleanup_abandoned=True,
            ),
        )
        reconciler = GitReconciler(
            repo_path=repo_path,
            config=ReconcilerConfig(),
        )

        base_branch = getattr(self.config, "base_branch", "main")
        managed_enabled = bool(getattr(self.config, "coordination_managed_worktrees", True))
        managed_dir = str(getattr(self.config, "coordination_managed_dir", ".worktrees/codex-auto"))
        managed_strategy = str(getattr(self.config, "coordination_managed_strategy", "merge"))
        managed_agent = str(
            getattr(self.config, "coordination_managed_agent", "nomic-self-improve")
        )
        try:
            maint_preflight = wt_manager.maintain_managed_sessions(
                base_branch=base_branch,
                strategy="merge",
                ttl_hours=24,
                include_active=False,
                reconcile_only=True,
                delete_branches=False,
            )
            logger.info(
                "coordination_worktree_preflight managed_total=%d processed=%d skipped_active=%d failures=%d",
                maint_preflight.get("directories_total", 0),
                maint_preflight.get("processed", 0),
                maint_preflight.get("skipped_active", 0),
                maint_preflight.get("failures", 0),
            )
        except (RuntimeError, OSError, ValueError) as exc:
            logger.debug("coordination_worktree_preflight_skipped: %s", exc)

        # Submit all subtasks to the dispatcher
        task_id_map: dict[str, Any] = {}  # dispatcher task_id -> original subtask
        for i, subtask in enumerate(subtasks):
            desc = self._extract_subtask_desc(subtask)
            track = getattr(subtask, "track", None)
            if isinstance(track, str):
                track_str = track
            elif hasattr(track, "value"):
                track_str = str(getattr(track, "value", "core") or "core")
            else:
                track_str = "core"

            # Extract dependency IDs if present
            deps = getattr(subtask, "dependencies", []) or []

            task = dispatcher.submit(
                title=desc[:200],
                description=desc,
                priority=i + 1,
                track=track_str,
                depends_on=deps,
            )
            task_id_map[task.task_id] = subtask

        # Start the health watchdog background loop
        await watchdog.start()

        results: list[dict[str, Any]] = []
        worktree_branches: list[str] = []  # track branches for merge

        try:
            while dispatcher.pending_tasks or dispatcher.running_tasks:
                # Check budget
                if self._total_spend_usd > self.config.budget_limit_usd:
                    logger.warning(
                        "coordination_budget_exceeded spend=%.2f limit=%.2f",
                        self._total_spend_usd,
                        self.config.budget_limit_usd,
                    )
                    break

                # Get next available task
                task = dispatcher.get_next()
                if task is None:
                    # All remaining tasks are blocked or running; wait briefly
                    await asyncio.sleep(1)
                    continue

                # Create a worktree for this task
                create_name = f"si-{cycle_id[:8]}-{task.task_id}"
                create_common_kwargs: dict[str, Any] = {
                    "name": create_name,
                    "track": task.track,
                    "agent_id": f"self-improve-{cycle_id}",
                }
                try:
                    if managed_enabled:
                        wt_state = await wt_manager.create(
                            **create_common_kwargs,
                            managed_dir=managed_dir,
                            managed_agent=managed_agent,
                            managed_session_id=create_name,
                            reconcile=True,
                            strategy=managed_strategy,
                            force_new=False,
                        )
                    else:
                        wt_state = await wt_manager.create(**create_common_kwargs)
                except RuntimeError as exc:
                    if managed_enabled:
                        logger.warning(
                            "managed_worktree_allocation_failed task=%s dir=%s: %s; falling back",
                            task.task_id,
                            managed_dir,
                            exc,
                        )
                        try:
                            wt_state = await wt_manager.create(**create_common_kwargs)
                        except RuntimeError as fallback_exc:
                            logger.warning(
                                "worktree_create_failed task=%s: %s", task.task_id, fallback_exc
                            )
                            dispatcher.fail(task.task_id, str(fallback_exc))
                            results.append(
                                {
                                    "success": False,
                                    "subtask": task.title[:100],
                                    "files_changed": [],
                                    "tests_passed": 0,
                                    "tests_failed": 0,
                                }
                            )
                            continue
                    else:
                        logger.warning("worktree_create_failed task=%s: %s", task.task_id, exc)
                        dispatcher.fail(task.task_id, str(exc))
                        results.append(
                            {
                                "success": False,
                                "subtask": task.title[:100],
                                "files_changed": [],
                                "tests_passed": 0,
                                "tests_failed": 0,
                            }
                        )
                        continue

                # Assign and start the task
                dispatcher.assign(task.task_id, wt_state.worktree_id)
                dispatcher.start(task.task_id)

                # Execute the subtask in the worktree
                original_subtask = task_id_map[task.task_id]
                # Set worktree path on subtask for downstream use
                if hasattr(original_subtask, "__dict__"):
                    original_subtask.worktree_path = str(wt_state.path)

                exec_result = await self._execute_single(original_subtask, cycle_id)

                # Update dispatcher and track results
                if exec_result.get("success"):
                    dispatcher.complete(task.task_id, exec_result)
                    worktree_branches.append(wt_state.branch_name)
                else:
                    dispatcher.fail(task.task_id, exec_result.get("error", "execution failed"))

                # Update worktree activity
                wt_manager.record_activity(wt_state.worktree_id)

                results.append(exec_result)

                # Track cost
                cost = exec_result.get("cost_usd", 0.0)
                self._total_spend_usd += cost

        finally:
            # Stop the watchdog
            await watchdog.stop()

            # Reconcile: merge successful branches back
            for branch in worktree_branches:
                try:
                    merge_result = await reconciler.safe_merge(branch)
                    if not merge_result.success:
                        logger.warning(
                            "coordination_merge_failed branch=%s conflicts=%d",
                            branch,
                            len(merge_result.conflicts),
                        )
                except (RuntimeError, subprocess.CalledProcessError) as exc:
                    logger.warning("coordination_merge_error branch=%s: %s", branch, exc)

            # Clean up worktrees
            for wt_state in list(wt_manager.worktrees.values()):
                try:
                    await wt_manager.destroy(wt_state.worktree_id)
                except (RuntimeError, OSError) as exc:
                    logger.debug("worktree_cleanup_failed: %s", exc)

            try:
                maint_post = wt_manager.maintain_managed_sessions(
                    base_branch=base_branch,
                    strategy="merge",
                    ttl_hours=24,
                    include_active=False,
                    reconcile_only=False,
                    delete_branches=False,
                )
                logger.info(
                    "coordination_worktree_postflight managed_total=%d processed=%d skipped_active=%d failures=%d",
                    maint_post.get("directories_total", 0),
                    maint_post.get("processed", 0),
                    maint_post.get("skipped_active", 0),
                    maint_post.get("failures", 0),
                )
            except (RuntimeError, OSError, ValueError) as exc:
                logger.debug("coordination_worktree_postflight_skipped: %s", exc)

        logger.info(
            "coordination_execution_complete cycle=%s tasks=%d/%d branches_merged=%d",
            cycle_id,
            len([r for r in results if r.get("success")]),
            len(results),
            len(worktree_branches),
        )
        return results

    @staticmethod
    def _extract_subtask_desc(subtask: Any) -> str:
        """Extract a description string from various subtask types."""
        if isinstance(subtask, str):
            return subtask
        if hasattr(subtask, "goal") and hasattr(subtask.goal, "description"):
            return str(subtask.goal.description)
        if hasattr(subtask, "original_task"):
            return str(subtask.original_task)
        if hasattr(subtask, "description"):
            return str(subtask.description)
        if hasattr(subtask, "title"):
            return str(subtask.title)
        return str(subtask)

    async def _execute_in_worktrees(
        self,
        subtasks: list[Any],
        cycle_id: str,
    ) -> list[dict[str, Any]]:
        """Execute subtasks in isolated worktrees.

        Prefers the coordination module (TaskDispatcher + WorktreeManager +
        HealthWatchdog + GitReconciler) when available. Falls back to
        BranchCoordinator, then to wave-based parallel execution.
        """
        # Prefer coordination module (health-tracked, priority-scheduled)
        coordination_result = await self._execute_with_coordination(subtasks, cycle_id)
        if coordination_result is not None:
            return coordination_result

        try:
            from aragora.nomic.branch_coordinator import (
                BranchCoordinator,
                TrackAssignment,
            )
            from aragora.nomic.meta_planner import PrioritizedGoal, Track

            coordinator = BranchCoordinator()

            assignments = []
            for i, subtask in enumerate(subtasks[: self.config.max_parallel]):
                # Determine track
                track_name = getattr(subtask, "track", "core")
                try:
                    track = Track(track_name) if isinstance(track_name, str) else track_name
                except ValueError:
                    track = Track.CORE

                desc = getattr(subtask, "description", str(subtask))

                # TrackAssignment.goal expects a PrioritizedGoal
                goal_obj = PrioritizedGoal(
                    id=f"subtask_{i}",
                    track=track,
                    description=desc[:200],
                    rationale=f"Subtask from cycle {cycle_id}",
                    estimated_impact="medium",
                    priority=i + 1,
                )

                assignments.append(TrackAssignment(goal=goal_obj))

            async def execute_fn(assignment: TrackAssignment) -> dict[str, Any]:
                return await self._execute_single(assignment, cycle_id)

            branch_result = await coordinator.coordinate_parallel_work(
                assignments=assignments,
                run_nomic_fn=execute_fn,
            )

            results: list[dict[str, Any]] = []
            for a in branch_result.assignments:
                success = a.status in ("completed", "merged")
                result_data = a.result if isinstance(a.result, dict) else {}
                results.append(
                    {
                        "success": success,
                        "files_changed": result_data.get("files_changed", []),
                        "tests_passed": result_data.get("tests_passed", 0),
                        "tests_failed": result_data.get("tests_failed", 0),
                    }
                )
            return results

        except ImportError as exc:
            logger.warning("Worktree execution unavailable, falling back to sequential: %s", exc)
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            logger.warning("Worktree execution failed, falling back to sequential: %s", exc)

        # Fallback: wave-based parallel execution
        fallback_results: list[dict[str, Any]] = []
        waves = self._dependency_waves(subtasks)
        for wave in waves:
            wave_results = await asyncio.gather(
                *[self._execute_single(st, cycle_id) for st in wave],
                return_exceptions=True,
            )
            for r in wave_results:
                if isinstance(r, BaseException):
                    logger.warning("Subtask in wave failed: %s", r)
                    fallback_results.append(
                        {
                            "success": False,
                            "files_changed": [],
                            "tests_passed": 0,
                            "tests_failed": 0,
                        }
                    )
                else:
                    fallback_results.append(r)

            # Check budget after each wave
            wave_cost = sum(r.get("cost_usd", 0.0) for r in fallback_results if isinstance(r, dict))
            self._total_spend_usd += wave_cost
            if self._total_spend_usd > self.config.budget_limit_usd:
                logger.warning(
                    "budget_exceeded spend=%.2f limit=%.2f",
                    self._total_spend_usd,
                    self.config.budget_limit_usd,
                )
                break
        return fallback_results

    def _dependency_waves(self, subtasks: list[Any]) -> list[list[Any]]:
        """Group subtasks into dependency waves for parallel execution.

        Subtasks without explicit dependencies go in wave 0, etc.
        Currently all subtasks are treated as independent and batched
        by ``max_parallel``.

        Returns:
            List of waves, each wave is a list of subtasks to run concurrently.
        """
        max_p = max(self.config.max_parallel, 1)
        waves: list[list[Any]] = []
        batch: list[Any] = []
        for st in subtasks:
            batch.append(st)
            if len(batch) >= max_p:
                waves.append(batch)
                batch = []
        if batch:
            waves.append(batch)
        return waves

    def _persist_outcome(
        self,
        cycle_id: str,
        result: SelfImproveResult,
        outcome_comparison: Any = None,
    ) -> None:
        """Step 6: Persist cycle outcome to CycleLearningStore.

        Args:
            cycle_id: The cycle identifier.
            result: The pipeline result.
            outcome_comparison: Optional OutcomeComparison from debate metrics
                comparison. When provided, also records to OutcomeTracker for
                the cross-cycle feedback loop.
        """
        try:
            from aragora.nomic.cycle_record import NomicCycleRecord
            from aragora.nomic.cycle_store import get_cycle_store

            store = get_cycle_store()
            record = NomicCycleRecord(
                cycle_id=cycle_id,
                started_at=time.time() - result.duration_seconds,
            )
            record.mark_complete(
                success=result.subtasks_completed > 0 and result.subtasks_failed == 0,
            )

            # Add metadata as evidence quality scores
            record.evidence_quality_scores = {
                "subtasks_completed": float(result.subtasks_completed),
                "subtasks_failed": float(result.subtasks_failed),
                "files_changed": float(len(result.files_changed)),
                "regressions": 1.0 if result.regressions_detected else 0.0,
                "improvement_score": result.improvement_score,
            }
            if result.metrics_delta:
                record.evidence_quality_scores["has_metrics"] = 1.0

            store.save_cycle(record)
            logger.info("cycle_outcome_persisted cycle=%s", cycle_id)

            # Record OutcomeComparison to close the feedback loop
            if outcome_comparison is not None:
                try:
                    from aragora.nomic.outcome_tracker import NomicOutcomeTracker

                    tracker = NomicOutcomeTracker()
                    tracker.record_cycle_outcome(cycle_id, outcome_comparison)
                    logger.info(
                        "outcome_comparison_recorded cycle=%s improved=%s",
                        cycle_id,
                        outcome_comparison.improved,
                    )
                except (ImportError, RuntimeError, ValueError, OSError) as exc:
                    logger.debug("Failed to record outcome comparison: %s", exc)

            # Feed outcomes to MetaPlanner for cross-cycle learning
            try:
                from aragora.nomic.meta_planner import MetaPlanner

                goal_outcomes = []
                # Build goal outcomes from result
                if result.subtasks_completed > 0 or result.subtasks_failed > 0:
                    goal_outcomes.append(
                        {
                            "track": "core",
                            "success": result.subtasks_completed > 0
                            and result.subtasks_failed == 0,
                            "description": result.objective,
                        }
                    )

                if goal_outcomes:
                    planner = MetaPlanner()
                    planner.record_outcome(
                        goal_outcomes=goal_outcomes,
                        objective=result.objective,
                    )
                    logger.info(
                        "meta_planner_outcome_recorded cycle=%s goals=%d",
                        cycle_id,
                        len(goal_outcomes),
                    )
            except (ImportError, RuntimeError, ValueError, TypeError) as exc:
                logger.debug("MetaPlanner outcome recording skipped: %s", exc)

            # Persist to KnowledgeMound for cross-cycle learning
            try:
                from aragora.pipeline.km_bridge import PipelineKMBridge

                bridge = PipelineKMBridge()
                if bridge.available:
                    stored = bridge.store_pipeline_result(
                        {
                            "cycle_id": cycle_id,
                            "objective": result.objective,
                            "success": (
                                result.subtasks_completed > 0 and result.subtasks_failed == 0
                            ),
                            "subtasks_completed": result.subtasks_completed,
                            "subtasks_failed": result.subtasks_failed,
                            "files_changed": result.files_changed,
                            "improvement_score": result.improvement_score,
                            "metrics_delta": result.metrics_delta,
                            "duration_seconds": result.duration_seconds,
                            "total_cost_usd": result.total_cost_usd,
                        }
                    )
                    if stored:
                        result.km_persisted = True
                        logger.info("km_bridge_persisted cycle=%s", cycle_id)
            except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
                logger.debug("KM bridge persistence skipped: %s", exc)

            # Infer domain tags from changed files for cross-cycle search boosting
            domain_tags = _infer_domain_tags(result.files_changed)

            # Also persist via NomicCycleAdapter for cross-cycle learning.
            # HardenedOrchestrator uses this adapter via find_similar_cycles()
            # and MetaPlanner._enrich_context_with_history().
            try:
                from datetime import datetime, timezone

                from aragora.knowledge.mound.adapters.nomic_cycle_adapter import (
                    CycleStatus as _CycleStatus,
                    NomicCycleOutcome,
                    get_nomic_cycle_adapter,
                )

                adapter = get_nomic_cycle_adapter()

                if result.subtasks_completed > 0 and result.subtasks_failed == 0:
                    _status = _CycleStatus.SUCCESS
                elif result.subtasks_completed > 0:
                    _status = _CycleStatus.PARTIAL
                else:
                    _status = _CycleStatus.FAILED

                now = datetime.now(timezone.utc)
                cycle_outcome = NomicCycleOutcome(
                    cycle_id=cycle_id,
                    objective=result.objective[:500],
                    status=_status,
                    started_at=now,
                    completed_at=now,
                    goals_attempted=result.subtasks_total,
                    goals_succeeded=result.subtasks_completed,
                    goals_failed=result.subtasks_failed,
                    total_files_changed=len(result.files_changed),
                    total_tests_passed=result.tests_passed,
                    total_tests_failed=result.tests_failed,
                    metrics_delta=result.metrics_delta,
                    improvement_score=result.improvement_score,
                    domain_tags=domain_tags,
                )
                # ingest_cycle_outcome may be sync or async; handle both
                _ingest = adapter.ingest_cycle_outcome(cycle_outcome)
                if hasattr(_ingest, "__await__"):
                    import asyncio

                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    if loop and loop.is_running():
                        # Already in an async context — schedule as task
                        loop.create_task(_ingest)
                    else:
                        asyncio.run(_ingest)
                # else: sync call already completed
                logger.info("nomic_cycle_adapter_persisted cycle=%s", cycle_id)
            except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
                logger.debug("NomicCycleAdapter persistence skipped: %s", exc)

        except ImportError as exc:
            logger.debug("Failed to persist cycle outcome (import): %s", exc)
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Failed to persist cycle outcome: %s", exc)

    def _run_feedback_orchestrator(
        self,
        cycle_id: str,
        execution_results: list[dict[str, Any]],
    ) -> None:
        """Step 7: Run the feedback orchestrator (6-step audit -> active bridge).

        Bridges Gauntlet, Introspection, Genesis, Learning, Workspace,
        and Pulse into active feedback goals persisted to ImprovementQueue.
        Next cycle's scan mode reads these as Signal 8/10.
        """
        try:
            from pathlib import Path as _P

            from aragora.nomic.feedback_orchestrator import SelfImproveFeedbackOrchestrator

            orchestrator = SelfImproveFeedbackOrchestrator(_P.cwd())
            feedback_report = orchestrator.run(cycle_id, execution_results)

            logger.info(
                "feedback_orchestrator_complete",
                extra={"goals": len(feedback_report.improvement_goals)},
            )
        except ImportError:
            logger.debug("FeedbackOrchestrator not available")
        except Exception:  # noqa: BLE001 — best-effort step, must not crash pipeline
            logger.warning("feedback_orchestrator_failed")

    def _publish_to_pipeline_graph(
        self,
        cycle_id: str,
        result: SelfImproveResult,
    ) -> None:
        """Publish cycle results as a pipeline visualization graph.

        Creates a UniversalGraph from the cycle results and persists it
        to GraphStore, making self-improvement cycles visible in the
        /pipeline canvas UI.
        """
        try:
            from aragora.nomic.pipeline_bridge import NomicPipelineBridge
            from aragora.pipeline.graph_store import get_graph_store

            # Build a minimal OrchestrationResult-like object for the bridge
            # We use a lightweight wrapper since SelfImproveResult doesn't
            # have the same shape as OrchestrationResult
            cycle_data = _SelfImproveOrchestrationAdapter(cycle_id, result)

            bridge = NomicPipelineBridge()
            graph = bridge.create_pipeline_from_cycle(cycle_data)  # type: ignore[arg-type]  # duck-type adapter

            store = get_graph_store()
            store.create(graph)

            logger.info(
                "pipeline_graph_published cycle=%s graph_id=%s nodes=%d",
                cycle_id,
                graph.id,
                len(graph.nodes),
            )
        except Exception as e:  # noqa: BLE001 — best-effort visualization, must not crash pipeline
            logger.debug("Pipeline graph publication skipped: %s", e)

    def _generate_curriculum_stepping_stones(
        self,
        cycle_id: str,
        result: SelfImproveResult,
        subtasks: list[Any],
    ) -> None:
        """Generate SOAR curriculum stepping stones for failed subtasks.

        When multiple subtasks fail, creates a curriculum of simpler tasks
        to build capability incrementally, rather than retrying the same
        difficult tasks.
        """
        try:
            from aragora.nomic.curriculum.integration import (
                CurriculumAwareFeedbackLoop,
                CurriculumConfig,
            )

            config = CurriculumConfig(
                enable_curriculum=True,
                min_failures_for_curriculum=self.config.curriculum_min_failures,
            )
            feedback_loop = CurriculumAwareFeedbackLoop(config=config)

            # Get curriculum summary for failed tasks
            summary = feedback_loop.get_curriculum_summary()
            if summary.get("curricula_created", 0) > 0 or result.subtasks_failed > 0:
                logger.info(
                    "curriculum_stepping_stones cycle=%s failed=%d curricula=%d",
                    cycle_id,
                    result.subtasks_failed,
                    summary.get("curricula_created", 0),
                )
                self._emit_progress(
                    "curriculum_generated",
                    {
                        "failed_subtasks": result.subtasks_failed,
                        "stepping_stones": summary.get("stones_attempted", 0),
                    },
                )
        except ImportError:
            logger.debug("CurriculumAwareFeedbackLoop not available")
        except (RuntimeError, ValueError, TypeError) as exc:
            logger.debug("Curriculum stepping stone generation failed: %s", exc)

    async def _run_gauntlet_validation(
        self,
        cycle_id: str,
        result: SelfImproveResult,
        objective: str,
    ) -> bool:
        """Run GauntletRunner on changes to adversarially validate them.

        Returns True if changes pass validation, False if rejected.
        """
        try:
            from aragora.gauntlet.runner import GauntletRunner

            runner = GauntletRunner()
            claim = (
                f"Self-improvement cycle {cycle_id}: {objective[:200]}. "
                f"Changed {len(result.files_changed)} files, "
                f"{result.subtasks_completed}/{result.subtasks_total} subtasks completed."
            )
            gauntlet_result = await runner.run(
                input_content=claim,
                context=f"Files changed: {', '.join(result.files_changed[:20])}",
            )

            verdict = getattr(gauntlet_result, "verdict", "unknown")
            logger.info(
                "gauntlet_validation cycle=%s verdict=%s vulnerabilities=%d",
                cycle_id,
                verdict,
                len(getattr(gauntlet_result, "vulnerabilities", [])),
            )

            # Reject if critical vulnerabilities found
            critical = sum(
                1
                for v in getattr(gauntlet_result, "vulnerabilities", [])
                if getattr(v, "severity", None)
                and str(getattr(v.severity, "value", "")).lower() == "critical"
            )
            if critical > 0:
                logger.warning(
                    "gauntlet_critical_findings cycle=%s critical=%d",
                    cycle_id,
                    critical,
                )
                return False

            return True
        except ImportError:
            logger.debug("GauntletRunner not available for self-improve validation")
            return True
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            logger.debug("Gauntlet validation failed: %s", exc)
            return True  # Don't block on gauntlet errors


__all__ = [
    "BudgetExceededError",
    "SelfImproveConfig",
    "SelfImprovePipeline",
    "SelfImproveResult",
]
