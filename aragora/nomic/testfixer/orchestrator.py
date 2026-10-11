"""
TestFixerOrchestrator - Main loop for automated test fixing.

Coordinates:
1. Running tests
2. Analyzing failures
3. Proposing and debating fixes
4. Applying fixes and retesting
5. Learning from results

Continues until tests pass or maximum iterations reached.
"""

from __future__ import annotations

import json
import inspect
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Callable, Awaitable

if TYPE_CHECKING:
    from typing import TypeAlias

    from aragora.nomic.testfixer.batch import BatchFixResult

    LLMAnalyzerConfig: TypeAlias = Any
    ArenaValidatorConfig: TypeAlias = Any
    RedTeamValidatorConfig: TypeAlias = Any

from aragora.nomic.testfixer.runner import TestRunner, TestResult, TestFailure
from aragora.nomic.testfixer.analyzer import FailureAnalyzer, FailureAnalysis, FixTarget
from aragora.nomic.testfixer.proposer import (
    PatchProposer,
    PatchProposal,
    PatchStatus,
    CodeGenerator,
)
from aragora.nomic.testfixer.store import TestFixerAttemptStore
from aragora.events.types import StreamEvent, StreamEventType


logger = logging.getLogger(__name__)


class LoopStatus(str, Enum):
    """Status of the fix loop."""

    RUNNING = "running"
    SUCCESS = "success"  # All tests pass
    MAX_ITERATIONS = "max_iterations"  # Hit iteration limit
    STUCK = "stuck"  # Same failure repeating
    HUMAN_REQUIRED = "human_required"  # Need human intervention
    ERROR = "error"  # Unexpected error


@dataclass
class FixAttempt:
    """Record of a single fix attempt."""

    iteration: int
    failure: TestFailure
    analysis: FailureAnalysis
    proposal: PatchProposal
    applied: bool
    test_result_after: TestResult | None
    success: bool
    run_id: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    duration_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass
class FixLoopResult:
    """Result of a complete fix loop."""

    status: LoopStatus
    started_at: datetime
    finished_at: datetime = field(default_factory=datetime.now)
    run_id: str | None = None

    # Stats
    total_iterations: int = 0
    fixes_applied: int = 0
    fixes_successful: int = 0
    fixes_reverted: int = 0

    # Details
    attempts: list[FixAttempt] = field(default_factory=list)
    final_test_result: TestResult | None = None

    # Learning data
    successful_patterns: list[dict[str, Any]] = field(default_factory=list)
    failed_patterns: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable summary."""
        duration = (self.finished_at - self.started_at).total_seconds()
        return (
            f"TestFixer {self.status.value}: "
            f"{self.fixes_successful}/{self.fixes_applied} fixes successful "
            f"in {self.total_iterations} iterations ({duration:.1f}s)"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "total_iterations": self.total_iterations,
            "fixes_applied": self.fixes_applied,
            "fixes_successful": self.fixes_successful,
            "fixes_reverted": self.fixes_reverted,
            "attempts": [
                {
                    "iteration": a.iteration,
                    "failure": a.failure.test_name,
                    "category": a.analysis.category.value,
                    "applied": a.applied,
                    "success": a.success,
                }
                for a in self.attempts
            ],
        }


@dataclass
class FixLoopConfig:
    """Configuration for the fix loop."""

    # Iteration limits
    max_iterations: int = 10
    max_same_failure: int = 3  # Stop if same failure repeats this many times

    # Confidence thresholds
    min_confidence_to_apply: float = 0.5
    min_confidence_for_auto: float = 0.7  # Higher threshold for fully auto

    # LLM analysis & validation
    use_llm_analyzer: bool = False
    llm_analyzer_config: LLMAnalyzerConfig | None = None
    enable_arena_validation: bool = False
    arena_validator_config: ArenaValidatorConfig | None = None
    enable_redteam_validation: bool = False
    redteam_validator_config: RedTeamValidatorConfig | None = None
    enable_pattern_learning: bool = False
    pattern_store_path: Path | None = None
    generation_timeout_seconds: float | None = None
    critique_timeout_seconds: float | None = None

    # Behavior
    revert_on_failure: bool = True
    require_debate_consensus: bool = False
    stop_on_first_success: bool = False

    # Callbacks
    on_fix_proposed: Callable[[PatchProposal], Awaitable[bool]] | None = (
        None  # Return False to skip
    )
    on_fix_applied: Callable[[FixAttempt], Awaitable[None]] | None = None
    on_iteration_complete: Callable[[int, TestResult], Awaitable[None]] | None = None

    # Batch mode
    enable_batch_mode: bool = False
    max_batch_size: int = 5
    enable_elo_selection: bool = False
    elo_fallback_agents: list[str] | None = None
    enable_bug_check: bool = False
    enable_impact_analysis: bool = False
    batch_test_command: str | None = None

    # Persistence
    save_attempts: bool = True
    attempts_dir: Path | None = None
    attempt_store: TestFixerAttemptStore | None = None
    run_id: str | None = None
    artifacts_dir: Path | None = None
    enable_diagnostics: bool = True


class TestFixerOrchestrator:
    """Main orchestrator for the automated test fixing loop.

    Example:
        fixer = TestFixerOrchestrator(
            repo_path=Path("/path/to/repo"),
            test_command="pytest tests/ -q --maxfail=1",
        )

        result = await fixer.run_fix_loop()

        if result.status == LoopStatus.SUCCESS:
            print("All tests pass!")
        else:
            print(f"Stopped: {result.status.value}")
            for attempt in result.attempts:
                print(f"  {attempt.failure.test_name}: {attempt.success}")
    """

    def __init__(
        self,
        repo_path: Path,
        test_command: str,
        config: FixLoopConfig | None = None,
        generators: list[CodeGenerator] | None = None,
        test_timeout: float = 300.0,
        event_emitter: Callable[[StreamEvent], Any] | None = None,
    ):
        """Initialize the orchestrator.

        Args:
            repo_path: Path to repository root
            test_command: Command to run tests
            config: Loop configuration
            generators: AI code generators for proposals
            test_timeout: Timeout for test execution
            event_emitter: Optional callback for StreamEvent notifications
        """
        self.repo_path = Path(repo_path)
        self.test_command = test_command
        self.config = config or FixLoopConfig()
        self.run_id = self.config.run_id or uuid.uuid4().hex
        self._event_emitter = event_emitter

        # Initialize components
        self.runner = TestRunner(
            repo_path=self.repo_path,
            test_command=test_command,
            timeout_seconds=test_timeout,
            run_id=self.run_id,
            artifacts_dir=self.config.artifacts_dir,
            enable_diagnostics=self.config.enable_diagnostics,
        )
        ai_analyzer = None
        if self.config.use_llm_analyzer:
            try:
                from aragora.nomic.testfixer.analyzers import LLMAnalyzerConfig, LLMFailureAnalyzer

                llm_config = self.config.llm_analyzer_config or LLMAnalyzerConfig()
                ai_analyzer = LLMFailureAnalyzer(llm_config)
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("testfixer.llm_analyzer_unavailable error=%s", exc)

        self.analyzer = FailureAnalyzer(repo_path=self.repo_path, ai_analyzer=ai_analyzer)
        self.proposer = PatchProposer(
            repo_path=self.repo_path,
            generators=generators,
            require_consensus=self.config.require_debate_consensus,
            generation_timeout_seconds=self.config.generation_timeout_seconds,
            critique_timeout_seconds=self.config.critique_timeout_seconds,
        )

        self.arena_validator = None
        if self.config.enable_arena_validation:
            try:
                from aragora.nomic.testfixer.validators import ArenaValidator, ArenaValidatorConfig

                arena_config = self.config.arena_validator_config or ArenaValidatorConfig()
                self.arena_validator = ArenaValidator(arena_config)
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("testfixer.arena_validator_unavailable error=%s", exc)

        self.redteam_validator = None
        if self.config.enable_redteam_validation:
            try:
                from aragora.nomic.testfixer.validators import (
                    RedTeamValidator,
                    RedTeamValidatorConfig,
                )

                redteam_config = self.config.redteam_validator_config or RedTeamValidatorConfig()
                self.redteam_validator = RedTeamValidator(redteam_config)
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("testfixer.redteam_validator_unavailable error=%s", exc)

        self.pattern_learner = None
        if self.config.enable_pattern_learning:
            try:
                from aragora.nomic.testfixer.learning import PatternLearner

                store_path = self.config.pattern_store_path
                if store_path is None:
                    store_path = self.repo_path / ".testfixer" / "patterns.json"
                self.pattern_learner = PatternLearner(store_path)
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("testfixer.pattern_learner_unavailable error=%s", exc)

        # State
        self._failure_history: list[str] = []  # Track failure patterns to detect loops
        self._applied_patches: list[tuple[PatchProposal, Path]] = []

    async def _emit_event(self, event_type: StreamEventType, data: dict[str, Any]) -> None:
        """Emit TestFixer event if emitter is configured."""
        if not self._event_emitter:
            return
        payload = dict(data)
        payload.setdefault("run_id", self.run_id)
        payload.setdefault("timestamp", datetime.now().isoformat())
        event = StreamEvent(
            type=event_type,
            data=payload,
            loop_id=self.run_id,
        )
        try:
            maybe_awaitable = self._event_emitter(event)
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
        except (RuntimeError, OSError, ValueError) as exc:
            logger.warning("testfixer.event_emit_failed run_id=%s error=%s", self.run_id, exc)

    async def run_fix_loop(
        self,
        max_iterations: int | None = None,
    ) -> FixLoopResult:
        """Run the main fix loop.

        Args:
            max_iterations: Override config max_iterations

        Returns:
            FixLoopResult with complete history
        """
        max_iter = max_iterations or self.config.max_iterations
        started_at = datetime.now()

        result = FixLoopResult(
            status=LoopStatus.RUNNING,
            started_at=started_at,
        )
        result.run_id = self.run_id

        logger.info(
            "testfixer.start run_id=%s repo=%s test_command=%s max_iter=%s",
            self.run_id,
            self.repo_path,
            self.test_command,
            max_iter,
        )

        try:
            for iteration in range(1, max_iter + 1):
                result.total_iterations = iteration

                logger.info(
                    "testfixer.iteration.start run_id=%s iteration=%s/%s",
                    self.run_id,
                    iteration,
                    max_iter,
                )

                # Run tests
                test_result = await self.runner.run()
                result.final_test_result = test_result
                logger.info(
                    "testfixer.test_result run_id=%s iteration=%s exit_code=%s summary=%s",
                    self.run_id,
                    iteration,
                    test_result.exit_code,
                    test_result.summary(),
                )
                if test_result.diagnostics:
                    logger.info(
                        "testfixer.diagnostics run_id=%s iteration=%s classification=%s exit_signal=%s run_dir=%s",
                        self.run_id,
                        iteration,
                        test_result.diagnostics.classification,
                        test_result.diagnostics.exit_signal,
                        test_result.diagnostics.run_dir,
                    )

                # Callback
                if self.config.on_iteration_complete:
                    await self.config.on_iteration_complete(iteration, test_result)

                # Check for success
                if test_result.success:
                    result.status = LoopStatus.SUCCESS
                    logger.info(
                        "testfixer.success run_id=%s iteration=%s",
                        self.run_id,
                        iteration,
                    )
                    break

                # Get first failure
                failure = test_result.first_failure
                if not failure:
                    logger.warning(
                        "testfixer.no_failure_details run_id=%s iteration=%s",
                        self.run_id,
                        iteration,
                    )
                    result.status = LoopStatus.ERROR
                    break
                logger.info(
                    "testfixer.first_failure run_id=%s iteration=%s test=%s file=%s error_type=%s",
                    self.run_id,
                    iteration,
                    failure.test_name,
                    failure.test_file,
                    failure.error_type,
                )
                await self._emit_event(
                    StreamEventType.TESTFIXER_FAILURE_DETECTED,
                    {
                        "iteration": iteration,
                        "test_name": failure.test_name,
                        "test_file": failure.test_file,
                        "error_type": failure.error_type,
                        "error_message": failure.error_message,
                    },
                )

                # Check for stuck loop
                failure_sig = f"{failure.test_file}::{failure.test_name}::{failure.error_type}"
                self._failure_history.append(failure_sig)

                recent = self._failure_history[-self.config.max_same_failure :]
                if len(recent) == self.config.max_same_failure and len(set(recent)) == 1:
                    logger.warning(
                        "testfixer.stuck run_id=%s iteration=%s signature=%s",
                        self.run_id,
                        iteration,
                        failure_sig,
                    )
                    result.status = LoopStatus.STUCK
                    break

                # Analyze failure
                analysis = await self.analyzer.analyze(failure)

                # Enrich analysis with pattern learner suggestions
                if self.pattern_learner:
                    try:
                        suggestion = self.pattern_learner.suggest_heuristic(analysis)
                    except (RuntimeError, ValueError, OSError) as exc:
                        logger.warning("testfixer.pattern_suggest_error error=%s", exc)
                        suggestion = None
                    if suggestion:
                        analysis.suggested_approach = (
                            f"{analysis.suggested_approach}\n\n{suggestion}"
                        )
                        analysis.analysis_notes.append("pattern_suggestion")

                logger.info(
                    "testfixer.analysis run_id=%s iteration=%s category=%s fix_target=%s confidence=%.2f root_file=%s",
                    self.run_id,
                    iteration,
                    analysis.category.value,
                    analysis.fix_target.value,
                    analysis.confidence,
                    analysis.root_cause_file,
                )
                await self._emit_event(
                    StreamEventType.TESTFIXER_ANALYSIS_COMPLETE,
                    {
                        "iteration": iteration,
                        "category": analysis.category.value,
                        "fix_target": analysis.fix_target.value,
                        "confidence": analysis.confidence,
                        "root_cause_file": analysis.root_cause_file,
                    },
                )

                # Check if human needed
                if analysis.fix_target == FixTarget.HUMAN:
                    logger.info(
                        "testfixer.human_required run_id=%s iteration=%s",
                        self.run_id,
                        iteration,
                    )
                    result.status = LoopStatus.HUMAN_REQUIRED
                    result.attempts.append(
                        FixAttempt(
                            iteration=iteration,
                            run_id=self.run_id,
                            failure=failure,
                            analysis=analysis,
                            proposal=PatchProposal(
                                id=f"human_{iteration}",
                                analysis=analysis,
                                status=PatchStatus.REJECTED,
                                description="Requires human intervention",
                            ),
                            applied=False,
                            test_result_after=None,
                            success=False,
                            notes=["Analysis determined human intervention needed"],
                        )
                    )
                    break

                # Propose fix
                proposal = await self.proposer.propose_fix(analysis)
                logger.info(
                    "testfixer.proposal run_id=%s iteration=%s proposal_id=%s confidence=%.2f patches=%s",
                    self.run_id,
                    iteration,
                    proposal.id,
                    proposal.post_debate_confidence,
                    len(proposal.patches),
                )
                await self._emit_event(
                    StreamEventType.TESTFIXER_FIX_PROPOSED,
                    {
                        "iteration": iteration,
                        "proposal_id": proposal.id,
                        "confidence": proposal.post_debate_confidence,
                        "patch_count": len(proposal.patches),
                        "description": proposal.description,
                    },
                )

                # Check confidence
                if proposal.post_debate_confidence < self.config.min_confidence_to_apply:
                    logger.info(
                        "Proposal confidence %.0f%% below threshold %.0f%%, skipping",
                        proposal.post_debate_confidence * 100,
                        self.config.min_confidence_to_apply * 100,
                    )
                    result.attempts.append(
                        FixAttempt(
                            iteration=iteration,
                            run_id=self.run_id,
                            failure=failure,
                            analysis=analysis,
                            proposal=proposal,
                            applied=False,
                            test_result_after=None,
                            success=False,
                            notes=["Confidence below threshold"],
                        )
                    )
                    continue

                # Callback for approval
                if self.config.on_fix_proposed:
                    approved = await self.config.on_fix_proposed(proposal)
                    if not approved:
                        logger.info(
                            "testfixer.proposal.rejected run_id=%s iteration=%s",
                            self.run_id,
                            iteration,
                        )
                        result.attempts.append(
                            FixAttempt(
                                iteration=iteration,
                                run_id=self.run_id,
                                failure=failure,
                                analysis=analysis,
                                proposal=proposal,
                                applied=False,
                                test_result_after=None,
                                success=False,
                                notes=["Rejected by approval callback"],
                            )
                        )
                        continue

                # Apply fix
                if not proposal.patches:
                    logger.info(
                        "testfixer.proposal.no_patches run_id=%s iteration=%s",
                        self.run_id,
                        iteration,
                    )
                    result.attempts.append(
                        FixAttempt(
                            iteration=iteration,
                            run_id=self.run_id,
                            failure=failure,
                            analysis=analysis,
                            proposal=proposal,
                            applied=False,
                            test_result_after=None,
                            success=False,
                            notes=["No patches generated"],
                        )
                    )
                    continue

                logger.info(
                    "testfixer.apply.start run_id=%s iteration=%s description=%s",
                    self.run_id,
                    iteration,
                    proposal.description,
                )
                applied = proposal.apply_all(self.repo_path)
                result.fixes_applied += 1
                await self._emit_event(
                    StreamEventType.TESTFIXER_FIX_APPLIED,
                    {
                        "iteration": iteration,
                        "proposal_id": proposal.id,
                        "applied": applied,
                        "test_name": failure.test_name,
                    },
                )

                if not applied:
                    logger.error(
                        "testfixer.apply.failed run_id=%s iteration=%s",
                        self.run_id,
                        iteration,
                    )
                    result.attempts.append(
                        FixAttempt(
                            iteration=iteration,
                            run_id=self.run_id,
                            failure=failure,
                            analysis=analysis,
                            proposal=proposal,
                            applied=False,
                            test_result_after=None,
                            success=False,
                            notes=["Failed to apply patches"],
                        )
                    )
                    continue

                self._applied_patches.append((proposal, self.repo_path))

                # Retest — targeted first, then full suite only if targeted passes
                targeted_test_id = f"{failure.test_file}::{failure.test_name}"
                targeted_result = await self.runner.run_single_test(targeted_test_id)

                if targeted_result.success:
                    retest_result = await self.runner.run()  # full suite for regressions
                else:
                    retest_result = targeted_result  # skip full suite — fix didn't work

                logger.info(
                    "testfixer.retest run_id=%s iteration=%s summary=%s",
                    self.run_id,
                    iteration,
                    retest_result.summary(),
                )
                if retest_result.diagnostics:
                    logger.info(
                        "testfixer.retest.diagnostics run_id=%s iteration=%s classification=%s exit_signal=%s run_dir=%s",
                        self.run_id,
                        iteration,
                        retest_result.diagnostics.classification,
                        retest_result.diagnostics.exit_signal,
                        retest_result.diagnostics.run_dir,
                    )

                # Check if fix worked
                fix_worked = bool(
                    retest_result.success
                    or (
                        retest_result.first_failure
                        and retest_result.first_failure.test_name != failure.test_name
                    )
                )

                attempt = FixAttempt(
                    iteration=iteration,
                    run_id=self.run_id,
                    failure=failure,
                    analysis=analysis,
                    proposal=proposal,
                    applied=True,
                    test_result_after=retest_result,
                    success=fix_worked,
                )

                if fix_worked:
                    logger.info(
                        "testfixer.fix.success run_id=%s iteration=%s test=%s",
                        self.run_id,
                        iteration,
                        failure.test_name,
                    )
                    result.fixes_successful += 1
                    result.successful_patterns.append(
                        {
                            "category": analysis.category.value,
                            "fix_target": analysis.fix_target.value,
                            "diff": proposal.as_diff(),
                        }
                    )
                else:
                    logger.info(
                        "testfixer.fix.failed run_id=%s iteration=%s test=%s",
                        self.run_id,
                        iteration,
                        failure.test_name,
                    )
                    result.failed_patterns.append(
                        {
                            "category": analysis.category.value,
                            "fix_target": analysis.fix_target.value,
                            "diff": proposal.as_diff(),
                        }
                    )

                    # Revert if configured
                    if self.config.revert_on_failure:
                        logger.info(
                            "testfixer.revert run_id=%s iteration=%s",
                            self.run_id,
                            iteration,
                        )
                        proposal.revert_all(self.repo_path)
                        result.fixes_reverted += 1
                        await self._emit_event(
                            StreamEventType.TESTFIXER_FIX_REVERTED,
                            {
                                "iteration": iteration,
                                "proposal_id": proposal.id,
                                "test_name": failure.test_name,
                            },
                        )

                if self.config.on_fix_applied:
                    await self.config.on_fix_applied(attempt)
                if self.config.attempt_store:
                    self.config.attempt_store.record_attempt(attempt)
                self._learn_from_attempt(attempt)

                if fix_worked and self.config.stop_on_first_success:
                    result.attempts.append(attempt)
                    result.status = LoopStatus.SUCCESS
                    result.final_test_result = retest_result
                    break

                result.attempts.append(attempt)
                if self.config.attempt_store:
                    self.config.attempt_store.record_attempt(attempt)
                self._learn_from_attempt(attempt)

                # Save attempt if configured
                if self.config.save_attempts and self.config.attempts_dir:
                    await self._save_attempt(attempt)

                await self._emit_event(
                    StreamEventType.TESTFIXER_ITERATION_COMPLETE,
                    {
                        "iteration": iteration,
                        "fix_worked": fix_worked,
                        "fixes_applied": result.fixes_applied,
                        "fixes_successful": result.fixes_successful,
                    },
                )

            else:
                # Loop completed without success
                result.status = LoopStatus.MAX_ITERATIONS

        except (RuntimeError, ValueError, OSError) as e:
            logger.exception("Error in fix loop")
            result.status = LoopStatus.ERROR
            if result.attempts:
                result.attempts[-1].notes.append(f"Error: {e}")

        result.finished_at = datetime.now()
        logger.info(
            "testfixer.finish run_id=%s status=%s attempts=%s fixes_applied=%s fixes_successful=%s",
            self.run_id,
            result.status.value,
            result.total_iterations,
            result.fixes_applied,
            result.fixes_successful,
        )
        await self._emit_event(
            StreamEventType.TESTFIXER_LOOP_COMPLETE,
            {
                "status": result.status.value,
                "total_iterations": result.total_iterations,
                "fixes_applied": result.fixes_applied,
                "fixes_successful": result.fixes_successful,
                "failed_patterns": result.failed_patterns,
                "successful_patterns": result.successful_patterns,
            },
        )
        if self.config.attempt_store:
            self.config.attempt_store.record_run(result)
        return result

    async def run_single_fix(
        self,
        failure: TestFailure,
    ) -> FixAttempt:
        """Attempt to fix a single failure.

        Args:
            failure: The failure to fix

        Returns:
            FixAttempt with result
        """
        analysis = await self.analyzer.analyze(failure)
        if self.pattern_learner:
            try:
                suggestion = self.pattern_learner.suggest_heuristic(analysis)
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("testfixer.pattern_suggest_error error=%s", exc)
                suggestion = None
            if suggestion:
                analysis.suggested_approach = f"{analysis.suggested_approach}\n\n{suggestion}"
                analysis.analysis_notes.append("pattern_suggestion")
        proposal = await self.proposer.propose_fix(analysis)

        if proposal.post_debate_confidence < self.config.min_confidence_to_apply:
            return FixAttempt(
                iteration=0,
                run_id=self.run_id,
                failure=failure,
                analysis=analysis,
                proposal=proposal,
                applied=False,
                test_result_after=None,
                success=False,
                notes=["Confidence below threshold"],
            )

        if not proposal.patches:
            return FixAttempt(
                iteration=0,
                run_id=self.run_id,
                failure=failure,
                analysis=analysis,
                proposal=proposal,
                applied=False,
                test_result_after=None,
                success=False,
                notes=["No patches generated"],
            )

        validation_notes: list[str] = []
        if self.arena_validator:
            try:
                arena_result = await self.arena_validator.validate(proposal, analysis)
                validation_notes.append(f"Arena validation: {arena_result.summary()}")
                if not arena_result.is_valid:
                    return FixAttempt(
                        iteration=0,
                        run_id=self.run_id,
                        failure=failure,
                        analysis=analysis,
                        proposal=proposal,
                        applied=False,
                        test_result_after=None,
                        success=False,
                        notes=validation_notes + ["Arena validator rejected fix"],
                    )
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("testfixer.arena.error error=%s", exc)
                validation_notes.append(f"Arena validator error: {exc}")
                self.arena_validator = None

        if self.redteam_validator:
            try:
                redteam_result = await self.redteam_validator.validate(proposal, analysis)
                validation_notes.append(f"RedTeam validation: {redteam_result.summary()}")
                if not redteam_result.passes:
                    return FixAttempt(
                        iteration=0,
                        run_id=self.run_id,
                        failure=failure,
                        analysis=analysis,
                        proposal=proposal,
                        applied=False,
                        test_result_after=None,
                        success=False,
                        notes=validation_notes + ["Red team validator rejected fix"],
                    )
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("testfixer.redteam.error error=%s", exc)
                validation_notes.append(f"Red team validator error: {exc}")
                self.redteam_validator = None

        applied = proposal.apply_all(self.repo_path)
        if not applied:
            return FixAttempt(
                iteration=0,
                run_id=self.run_id,
                failure=failure,
                analysis=analysis,
                proposal=proposal,
                applied=False,
                test_result_after=None,
                success=False,
                notes=validation_notes + ["Failed to apply patches"],
            )

        # Run single test to verify
        retest = await self.runner.run_single_test(f"{failure.test_file}::{failure.test_name}")

        success = retest.success
        if not success and self.config.revert_on_failure:
            proposal.revert_all(self.repo_path)

        attempt = FixAttempt(
            iteration=0,
            run_id=self.run_id,
            failure=failure,
            analysis=analysis,
            proposal=proposal,
            applied=True,
            test_result_after=retest,
            success=success,
            notes=validation_notes,
        )
        self._learn_from_attempt(attempt)
        return attempt

    async def run_batch_fix_loop(
        self,
        max_iterations: int | None = None,
    ) -> "BatchFixResult":
        """Run the batch fix loop.

        Collects all failures, groups them into batches, and processes
        each batch with optional ELO selection, bug checking, and
        impact analysis.

        Args:
            max_iterations: Override config max_iterations.

        Returns:
            BatchFixResult with complete batch history.
        """
        from aragora.nomic.testfixer.batch import BatchOrchestrator

        batch_orch = BatchOrchestrator(self, self.config)
        return await batch_orch.run(max_iterations)

    def _learn_from_attempt(self, attempt: FixAttempt) -> None:
        if not self.pattern_learner:
            return
        try:
            learned = self.pattern_learner.learn_from_attempt(attempt)
            if learned:
                attempt.notes.append(f"pattern_learned:{learned.id}")
                if self._event_emitter:
                    import asyncio

                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(
                            self._emit_event(
                                StreamEventType.TESTFIXER_PATTERN_LEARNED,
                                {
                                    "pattern_id": learned.id,
                                    "category": attempt.analysis.category.value,
                                    "success": attempt.success,
                                },
                            )
                        )
                    except RuntimeError:
                        pass
        except (RuntimeError, ValueError, OSError) as exc:
            logger.warning("testfixer.pattern_learn_error error=%s", exc)

    async def _save_attempt(self, attempt: FixAttempt) -> None:
        """Save attempt to disk for learning."""
        if not self.config.attempts_dir:
            return

        self.config.attempts_dir.mkdir(parents=True, exist_ok=True)
        filepath = (
            self.config.attempts_dir
            / f"attempt_{attempt.iteration}_{attempt.timestamp.strftime('%Y%m%d_%H%M%S')}.json"
        )

        data = {
            "iteration": attempt.iteration,
            "failure": {
                "test_name": attempt.failure.test_name,
                "test_file": attempt.failure.test_file,
                "error_type": attempt.failure.error_type,
                "error_message": attempt.failure.error_message,
            },
            "analysis": {
                "category": attempt.analysis.category.value,
                "fix_target": attempt.analysis.fix_target.value,
                "confidence": attempt.analysis.confidence,
                "root_cause": attempt.analysis.root_cause,
            },
            "proposal": {
                "id": attempt.proposal.id,
                "description": attempt.proposal.description,
                "confidence": attempt.proposal.post_debate_confidence,
                "diff": attempt.proposal.as_diff(),
            },
            "applied": attempt.applied,
            "success": attempt.success,
            "notes": attempt.notes,
            "timestamp": attempt.timestamp.isoformat(),
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)


async def run_test_fixer(
    repo_path: str | Path,
    test_command: str,
    max_iterations: int = 10,
    min_confidence: float = 0.5,
) -> FixLoopResult:
    """Convenience function to run the test fixer.

    Args:
        repo_path: Path to repository
        test_command: Command to run tests
        max_iterations: Maximum fix attempts
        min_confidence: Minimum confidence to apply fixes

    Returns:
        FixLoopResult
    """
    fixer = TestFixerOrchestrator(
        repo_path=Path(repo_path),
        test_command=test_command,
        config=FixLoopConfig(
            max_iterations=max_iterations,
            min_confidence_to_apply=min_confidence,
        ),
    )
    return await fixer.run_fix_loop()
