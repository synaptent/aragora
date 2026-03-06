"""SwarmCommander: interrogate -> spec -> dispatch -> merge -> report.

Top-level orchestrator that wraps HardenedOrchestrator with user-facing
interrogation and plain-English reporting phases.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from aragora.swarm.config import SwarmCommanderConfig
from aragora.swarm.interrogator import SwarmInterrogator
from aragora.swarm.reconciler import SwarmReconciler
from aragora.swarm.reporter import SwarmReport, SwarmReporter
from aragora.swarm.spec import SwarmSpec
from aragora.swarm.supervisor import SupervisorRun, SwarmApprovalPolicy, SwarmSupervisor

logger = logging.getLogger(__name__)


class SwarmCommander:
    """Top-level orchestrator: interrogate -> spec -> dispatch -> merge -> report.

    Wraps HardenedOrchestrator with user-facing phases. The user interacts
    only with the interrogation and reporting phases; the dispatch phase
    delegates entirely to the existing orchestration infrastructure.

    Usage:
        commander = SwarmCommander()
        report = await commander.run("Make the dashboard faster")
        print(report.to_plain_text())

    Or with a pre-built spec:
        spec = SwarmSpec.from_yaml(Path("my-spec.yaml").read_text())
        report = await commander.run_from_spec(spec)
    """

    def __init__(self, config: SwarmCommanderConfig | None = None) -> None:
        self.config = config or SwarmCommanderConfig()
        self._interrogator = SwarmInterrogator(self.config.interrogator)
        self._reporter = SwarmReporter()
        self._spec: SwarmSpec | None = None
        self._result: Any = None

    async def run(
        self,
        initial_goal: str,
        input_fn: Any | None = None,
        print_fn: Any | None = None,
    ) -> SwarmReport:
        """Full swarm lifecycle: interrogate -> dispatch -> report.

        Args:
            initial_goal: The user's goal in plain language.
            input_fn: Custom input function (default: builtin input).
            print_fn: Custom print function (default: builtin print).

        Returns:
            SwarmReport with plain-English summary.
        """
        _print = print_fn or print

        self._spec = await self.prepare_spec(
            initial_goal,
            input_fn=input_fn,
            print_fn=print_fn,
        )

        # Phase 2: Dispatch
        _print("\n[Phase 2/4] Dispatching agents...\n")
        start_time = time.monotonic()
        self._result = await self._dispatch(self._spec)
        duration = time.monotonic() - start_time

        # Phase 2.5: Truth-seeking validation
        if self.config.enable_epistemic_scoring:
            self._result = await self._validate_results(self._result, self._spec)

        # Phase 3: Report
        _print("\n[Phase 3/4] Generating report...\n")
        report = await self._reporter.generate(
            spec=self._spec,
            result=self._result,
            duration_seconds=duration,
        )

        _print(report.to_plain_text())

        # Phase 4: Write receipt to Obsidian if configured
        await self._write_receipt_to_obsidian(report)

        return report

    async def prepare_spec(
        self,
        initial_goal: str,
        input_fn: Any | None = None,
        print_fn: Any | None = None,
    ) -> SwarmSpec:
        """Build a SwarmSpec from a raw goal without dispatching workers."""
        _print = print_fn or print
        _print("\n[Phase 1/3] Gathering requirements...\n")
        spec = await self._interrogator.interrogate(
            initial_goal, input_fn=input_fn, print_fn=print_fn
        )
        if self.config.enable_research_pipeline:
            _print("\n[Phase 1.5/4] Researching and enriching spec...\n")
            spec = await self._research(spec)
        self._spec = spec
        return spec

    async def run_from_spec(
        self,
        spec: SwarmSpec,
        print_fn: Any | None = None,
    ) -> SwarmReport:
        """Skip interrogation, run from a pre-built spec.

        Args:
            spec: A pre-built SwarmSpec (from YAML, JSON, or previous run).
            print_fn: Custom print function.

        Returns:
            SwarmReport with plain-English summary.
        """
        _print = print_fn or print
        self._spec = spec

        _print("\n[Phase 1/2] Dispatching agents...\n")
        start_time = time.monotonic()
        self._result = await self._dispatch(spec)
        duration = time.monotonic() - start_time

        _print("\n[Phase 2/2] Generating report...\n")
        report = await self._reporter.generate(
            spec=spec,
            result=self._result,
            duration_seconds=duration,
        )

        _print(report.to_plain_text())
        return report

    async def dry_run(
        self,
        initial_goal: str,
        input_fn: Any | None = None,
        print_fn: Any | None = None,
    ) -> SwarmSpec:
        """Run interrogation only, produce a spec without executing.

        Args:
            initial_goal: The user's goal in plain language.
            input_fn: Custom input function.
            print_fn: Custom print function.

        Returns:
            The produced SwarmSpec (no execution).
        """
        _print = print_fn or print
        _print("\n[DRY RUN] Gathering requirements only (no agents will be dispatched)...\n")
        spec = await self.prepare_spec(
            initial_goal,
            input_fn=input_fn,
            print_fn=print_fn,
        )

        _print("\n" + "=" * 60)
        _print("SPEC (would be used for dispatch)")
        _print("=" * 60)
        _print(spec.to_json(indent=2))
        _print("")

        return spec

    async def run_supervised(
        self,
        initial_goal: str,
        *,
        repo_path: Path | None = None,
        target_branch: str = "main",
        max_concurrency: int = 8,
        managed_dir_pattern: str = ".worktrees/{agent}-auto",
        approval_policy: SwarmApprovalPolicy | None = None,
        dispatch: bool = True,
        wait: bool = True,
        interval_seconds: float = 5.0,
        max_ticks: int | None = None,
        input_fn: Any | None = None,
        print_fn: Any | None = None,
    ) -> SupervisorRun:
        """Prepare a spec, then dispatch it through the Codex/Claude supervisor path."""
        spec = await self.prepare_spec(
            initial_goal,
            input_fn=input_fn,
            print_fn=print_fn,
        )
        return await self.run_supervised_from_spec(
            spec,
            repo_path=repo_path,
            target_branch=target_branch,
            max_concurrency=max_concurrency,
            managed_dir_pattern=managed_dir_pattern,
            approval_policy=approval_policy,
            dispatch=dispatch,
            wait=wait,
            interval_seconds=interval_seconds,
            max_ticks=max_ticks,
        )

    async def run_supervised_from_spec(
        self,
        spec: SwarmSpec,
        *,
        repo_path: Path | None = None,
        target_branch: str = "main",
        max_concurrency: int = 8,
        managed_dir_pattern: str = ".worktrees/{agent}-auto",
        approval_policy: SwarmApprovalPolicy | None = None,
        dispatch: bool = True,
        wait: bool = True,
        interval_seconds: float = 5.0,
        max_ticks: int | None = None,
    ) -> SupervisorRun:
        """Dispatch a spec through the supervisor-backed Codex/Claude worker pool.

        Args:
            dispatch: If True, spawn CLI worker processes after provisioning.
            wait: If True, reconcile until the run reaches a stable stop condition.
        """
        self._spec = spec
        supervisor = SwarmSupervisor(repo_root=repo_path or Path.cwd())
        run = supervisor.start_run(
            spec=spec,
            target_branch=target_branch,
            max_concurrency=max_concurrency,
            managed_dir_pattern=managed_dir_pattern,
            approval_policy=approval_policy,
        )
        if dispatch:
            launched = await supervisor.dispatch_workers(run.run_id)
            if wait and launched:
                reconciler = SwarmReconciler(supervisor=supervisor)
                return await reconciler.watch_run(
                    run.run_id,
                    interval_seconds=interval_seconds,
                    max_ticks=max_ticks,
                )
            return supervisor.refresh_run(run.run_id)

        return supervisor.refresh_run(run.run_id)

    async def _dispatch(self, spec: SwarmSpec) -> Any:
        """Dispatch the swarm using HardenedOrchestrator.

        Translates the SwarmSpec into HardenedOrchestrator parameters
        and executes the goal.
        """
        orchestrator = self._build_orchestrator(spec)

        context: dict[str, Any] = {}
        if spec.acceptance_criteria:
            context["acceptance_criteria"] = spec.acceptance_criteria
        if spec.constraints:
            context["constraints"] = spec.constraints
        if spec.user_expertise:
            context["user_expertise"] = spec.user_expertise
        if spec.file_scope_hints:
            context["file_scope_hints"] = spec.file_scope_hints

        tracks = spec.track_hints if spec.track_hints else None

        try:
            result = await orchestrator.execute_goal_coordinated(
                goal=spec.refined_goal or spec.raw_goal,
                tracks=tracks,
                max_cycles=self.config.max_cycles,
                context=context if context else None,
            )
            return result
        except Exception as exc:
            logger.error("Swarm dispatch failed: %s", exc)
            # Return a minimal result so reporting still works
            return _ErrorResult(str(exc))

    async def run_iterative(
        self,
        initial_goal: str,
        input_fn: Any | None = None,
        print_fn: Any | None = None,
    ) -> list[SwarmReport]:
        """Run the swarm in an iterative loop: run -> report -> 'what next?' -> repeat.

        Args:
            initial_goal: The user's first goal in plain language.
            input_fn: Custom input function (default: builtin input).
            print_fn: Custom print function (default: builtin print).

        Returns:
            List of SwarmReports from each cycle.
        """
        _input = input_fn or input
        _print = print_fn or print
        reports: list[SwarmReport] = []
        goal = initial_goal
        cycle = 1

        while True:
            sep = "=" * 60
            _print(f"\n{sep}")
            _print(f"  Cycle {cycle}")
            _print(sep)

            report = await self.run(goal, input_fn=input_fn, print_fn=print_fn)
            reports.append(report)

            if not self.config.iterative_mode:
                break

            _print("\n" + "-" * 60)
            _print("What would you like to do next?")
            _print('(Type "done", "quit", or "exit" to finish)')
            _print("-" * 60)
            next_input = _input("> ")

            # Phase 6: Persist cycle learnings
            if self.config.enable_cross_cycle_learning:
                await self._persist_cycle_learnings(report, cycle)

            if next_input.strip().lower() in ("done", "quit", "exit", ""):
                _print("\nAll done! Here's a summary of what was accomplished:\n")
                for i, r in enumerate(reports, 1):
                    _print(f"  Cycle {i}: {r.summary}")
                break

            # Phase 6: MetaPlanner suggestion in metrics-driven mode
            if self.config.autonomy_level.value == "metrics" and not next_input.strip():
                try:
                    from aragora.nomic.meta_planner import MetaPlanner

                    planner = MetaPlanner()
                    suggestion = await planner.suggest_next_goal([r.summary for r in reports])
                    if suggestion:
                        _print(f"\nSuggested next goal: {suggestion}")
                        goal = suggestion
                    else:
                        goal = next_input.strip()
                except (ImportError, Exception):
                    goal = next_input.strip()
            else:
                goal = next_input.strip()

            # Reset interrogator for new goal
            self._interrogator = SwarmInterrogator(self.config.interrogator)
            cycle += 1

        return reports

    async def _research(self, spec: SwarmSpec) -> SwarmSpec:
        """Enrich spec with pipeline research (Phase 3)."""
        if not self.config.enable_research_pipeline:
            return spec
        try:
            from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

            pipeline = IdeaToExecutionPipeline()
            result = pipeline.from_ideas([spec.refined_goal or spec.raw_goal])
            spec.research_context = {
                "goal_graph": (
                    result.goal_graph.to_dict()
                    if hasattr(result, "goal_graph") and result.goal_graph
                    else {}
                ),
                "stage": "ideas_to_goals",
            }
            spec.pipeline_stage = "enriched"
            logger.info("Research pipeline enriched spec with goal graph")
        except (ImportError, Exception):
            logger.debug("Research pipeline unavailable, skipping enrichment")
        return spec

    async def _load_from_obsidian(self, vault_path: str) -> list[str]:
        """Read goals from tagged Obsidian notes (Phase 4)."""
        try:
            from aragora.connectors.knowledge.obsidian import (
                ObsidianConfig,
                ObsidianConnector,
            )

            config = ObsidianConfig(
                vault_path=vault_path,
                watch_tags=["#aragora", "#swarm"],
            )
            connector = ObsidianConnector(config)
            notes = list(connector.search_notes(tags=["#swarm"]))
            return [note.content for note in notes if note.content]
        except (ImportError, Exception):
            logger.debug("Obsidian connector unavailable")
            return []

    async def _write_receipt_to_obsidian(self, report: SwarmReport) -> None:
        """Write decision receipt back to Obsidian vault (Phase 4)."""
        if not self.config.obsidian_vault_path or not self.config.obsidian_write_receipts:
            return
        try:
            from aragora.connectors.knowledge.obsidian import (
                ObsidianConfig,
                ObsidianConnector,
            )

            config = ObsidianConfig(vault_path=self.config.obsidian_vault_path)
            connector = ObsidianConnector(config)
            receipt_md = report.to_markdown()
            goal_slug = (report.spec.raw_goal[:50] if report.spec else "unknown").strip()
            connector.write_note(
                title=f"Swarm Receipt - {goal_slug}",
                content=receipt_md,
                tags=["#aragora", "#receipt"],
                folder="aragora-receipts",
            )
            logger.info("Decision receipt written to Obsidian vault")
        except (ImportError, Exception):
            logger.debug("Obsidian receipt write failed, skipping")

    async def _validate_results(self, result: Any, spec: SwarmSpec) -> Any:
        """Post-dispatch truth-seeking validation (Phase 5)."""
        if not self.config.enable_epistemic_scoring:
            return result
        try:
            from aragora.reasoning.epistemic_scorer import EpistemicScorer

            scorer = EpistemicScorer()
            scores = []
            for assignment in getattr(result, "assignments", []):
                if getattr(assignment, "status", "") == "completed":
                    output = getattr(assignment, "output", "")
                    if output:
                        score = scorer.score(output)
                        if hasattr(assignment, "__dict__"):
                            assignment.__dict__["epistemic_score"] = score
                        scores.append(score.overall if hasattr(score, "overall") else 0.0)
            if scores:
                spec.epistemic_scores = {
                    "average": sum(scores) / len(scores),
                    "min": min(scores),
                    "max": max(scores),
                    "count": len(scores),
                }
        except (ImportError, Exception):
            logger.debug("Epistemic scoring unavailable")
        return result

    async def _persist_cycle_learnings(self, report: SwarmReport, cycle: int) -> None:
        """Store cycle results in KnowledgeMound for cross-cycle learning (Phase 6)."""
        try:
            from aragora.knowledge.mound.core import KnowledgeMound

            mound = KnowledgeMound()
            mound.ingest(
                {
                    "type": "swarm_cycle",
                    "cycle": cycle,
                    "goal": report.spec.raw_goal if report.spec else "",
                    "success": report.success,
                    "duration": report.duration_seconds,
                    "cost": report.budget_spent_usd,
                }
            )
            logger.info("Cycle %d learnings persisted to KnowledgeMound", cycle)
        except (ImportError, Exception):
            logger.debug("KnowledgeMound unavailable for cross-cycle learning")

    def _build_orchestrator(self, spec: SwarmSpec) -> Any:
        """Configure HardenedOrchestrator from spec and config."""
        from aragora.nomic.hardened_orchestrator import HardenedOrchestrator

        orchestrator = HardenedOrchestrator(
            require_human_approval=spec.requires_approval or self.config.require_approval,
            budget_limit_usd=spec.budget_limit_usd or self.config.budget_limit_usd,
            use_worktree_isolation=self.config.use_worktree_isolation,
            enable_gauntlet_validation=self.config.enable_gauntlet_validation,
            enable_mode_enforcement=self.config.enable_mode_enforcement,
            enable_meta_planning=self.config.enable_meta_planning,
            generate_receipts=self.config.generate_receipts,
            spectate_stream=self.config.spectate_stream,
            max_parallel_tasks=self.config.max_parallel_tasks,
        )

        # Post-configure task decomposer if available
        if hasattr(orchestrator, "task_decomposer"):
            decomposer = orchestrator.task_decomposer
            if hasattr(decomposer, "config") and hasattr(decomposer.config, "max_subtasks"):
                decomposer.config.max_subtasks = self.config.max_subtasks

        return orchestrator

    @property
    def spec(self) -> SwarmSpec | None:
        """The spec from the last run."""
        return self._spec

    @property
    def result(self) -> Any:
        """The orchestration result from the last run."""
        return self._result


class _ErrorResult:
    """Minimal result object for when dispatch fails entirely."""

    def __init__(self, error: str) -> None:
        self.error = error
        self.total_subtasks = 0
        self.completed_subtasks = 0
        self.failed_subtasks = 1
        self.skipped_subtasks = 0
        self.assignments: list[Any] = []
        self.total_cost_usd = 0.0
