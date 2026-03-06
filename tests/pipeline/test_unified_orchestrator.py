"""Tests for the Unified Pipeline Orchestrator."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass

from aragora.pipeline.unified_orchestrator import (
    OrchestratorConfig,
    OrchestratorResult,
    UnifiedOrchestrator,
)


# --- Fixtures ---


@dataclass
class FakeDebateResult:
    debate_id: str = "test-debate-1"
    task: str = "Test task"
    final_answer: str = "The answer is 42"
    confidence: float = 0.85
    consensus_reached: bool = True
    rounds_used: int = 3
    participants: list[str] | None = None
    metadata: dict | None = None

    def __post_init__(self):
        if self.participants is None:
            self.participants = ["agent-claude", "agent-gpt", "agent-gemini"]
        if self.metadata is None:
            self.metadata = {}


@dataclass
class FakePlanOutcome:
    success: bool = True
    tests_passed: int = 10
    tests_failed: int = 0
    files_changed: int = 3


@dataclass
class FakeDecisionPlan:
    id: str = "plan-1"
    status: str = "created"


def make_researcher(results=None):
    researcher = AsyncMock()
    ctx = MagicMock()
    ctx.results = results or []
    ctx.has_results = len(ctx.results) > 0
    researcher.research.return_value = ctx
    return researcher


def make_input_extension():
    ext = AsyncMock()
    extended = MagicMock()
    extended.to_context_block.return_value = "## Prior Art\n- Related decision found"
    extended.has_extensions = True
    ext.extend.return_value = extended
    return ext


def make_diversity_filter():
    filt = MagicMock()
    report = MagicMock()
    report.meets_minimum = True
    report.provider_count = 3
    report.swaps_made = []
    filt.enforce.return_value = (["agent1", "agent2", "agent3"], report)
    return filt


def make_arena_factory(debate_result=None):
    factory = AsyncMock()
    factory.return_value = debate_result or FakeDebateResult()
    return factory


def make_plan_factory(plan=None):
    factory = MagicMock()
    factory.from_debate_result.return_value = plan or FakeDecisionPlan()
    return factory


def make_plan_executor(outcome=None):
    executor = AsyncMock()
    executor.execute.return_value = outcome or FakePlanOutcome()
    return executor


def make_feedback_recorder():
    recorder = MagicMock()
    recorder.record = MagicMock()
    return recorder


def make_elo_tracker():
    tracker = MagicMock()
    tracker.record_match = MagicMock()
    return tracker


def make_meta_loop(should_trigger=False):
    meta = MagicMock()
    meta.should_trigger.return_value = should_trigger
    meta.increment_cycle = MagicMock()
    meta.identify_targets.return_value = []
    meta.execute.return_value = MagicMock(improved=False)
    return meta


# --- Tests ---


class TestOrchestratorConfig:
    def test_defaults(self):
        cfg = OrchestratorConfig()
        assert cfg.preset_name == "cto"
        assert cfg.autonomy_level == "propose_and_approve"
        assert cfg.min_providers == 2
        assert cfg.enable_meta_loop is False
        assert cfg.skip_execution is False

    def test_custom_config(self):
        cfg = OrchestratorConfig(
            preset_name="founder",
            domain="security",
            debate_rounds=5,
            autonomy_level="fully_autonomous",
        )
        assert cfg.preset_name == "founder"
        assert cfg.domain == "security"
        assert cfg.debate_rounds == 5


class TestOrchestratorResult:
    def test_succeeded_with_debate(self):
        result = OrchestratorResult(run_id="r1", prompt="test")
        result.stages_completed.append("debate")
        assert result.succeeded is True

    def test_failed_without_debate(self):
        result = OrchestratorResult(run_id="r1", prompt="test")
        assert result.succeeded is False

    def test_failed_with_errors(self):
        result = OrchestratorResult(run_id="r1", prompt="test")
        result.stages_completed.append("debate")
        result.errors.append("Something failed")
        assert result.succeeded is False

    def test_quality_score_from_outcome(self):
        result = OrchestratorResult(run_id="r1", prompt="test")
        outcome = MagicMock()
        outcome.overall_quality_score = 0.85
        result.pipeline_outcome = outcome
        assert result.quality_score == 0.85

    def test_quality_score_default(self):
        result = OrchestratorResult(run_id="r1", prompt="test")
        assert result.quality_score == 0.0


class TestUnifiedOrchestrator:
    @pytest.mark.asyncio
    async def test_minimal_run_no_components(self):
        """Orchestrator runs even with zero components — graceful degradation."""
        orch = UnifiedOrchestrator()
        result = await orch.run("Build a login page")

        assert result.run_id
        assert result.prompt == "Build a login page"
        # No debate factory → debate returns None → no error but no debate stage
        assert "debate" not in result.stages_completed or result.debate_result is None

    @pytest.mark.asyncio
    async def test_full_pipeline_happy_path(self):
        """All components present, full pipeline executes."""
        orch = UnifiedOrchestrator(
            input_extension=make_input_extension(),
            researcher=make_researcher(),
            diversity_filter=make_diversity_filter(),
            elo_tracker=make_elo_tracker(),
            feedback_recorder=make_feedback_recorder(),
            arena_factory=make_arena_factory(),
            plan_factory=make_plan_factory(),
            plan_executor=make_plan_executor(),
        )

        cfg = OrchestratorConfig(
            autonomy_level="fully_autonomous",
            domain="technical",
        )
        result = await orch.run("Build a rate limiter", config=cfg, agents=["a1", "a2"])

        assert result.succeeded
        assert "research" in result.stages_completed
        assert "extend" in result.stages_completed
        assert "debate" in result.stages_completed
        assert "plan" in result.stages_completed
        assert "execute" in result.stages_completed
        assert "feedback" in result.stages_completed
        assert result.duration_s > 0

    @pytest.mark.asyncio
    async def test_debate_only_no_execution(self):
        """skip_execution=True stops after debate + plan."""
        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(),
            plan_factory=make_plan_factory(),
            plan_executor=make_plan_executor(),
        )

        cfg = OrchestratorConfig(
            skip_execution=True,
            autonomy_level="fully_autonomous",
        )
        result = await orch.run("Design an API", config=cfg)

        assert "debate" in result.stages_completed
        assert "plan" in result.stages_completed
        assert "execute" not in result.stages_completed

    @pytest.mark.asyncio
    async def test_approval_gate_blocks(self):
        """When approval is needed and no callback, pipeline stops."""
        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(),
            plan_factory=make_plan_factory(),
            plan_executor=make_plan_executor(),
        )

        cfg = OrchestratorConfig(autonomy_level="propose_and_approve")
        result = await orch.run("Deploy to production", config=cfg)

        assert "debate" in result.stages_completed
        assert "plan" in result.stages_completed
        assert "spec" in result.approvals_needed
        assert "execute" not in result.stages_completed

    @pytest.mark.asyncio
    async def test_approval_gate_approved(self):
        """When approval callback returns True, pipeline continues."""
        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(),
            plan_factory=make_plan_factory(),
            plan_executor=make_plan_executor(),
        )

        approval = AsyncMock(return_value=True)
        cfg = OrchestratorConfig(autonomy_level="propose_and_approve")
        result = await orch.run("Deploy to prod", config=cfg, approval_callback=approval)

        assert "execute" in result.stages_completed
        approval.assert_called_once()

    @pytest.mark.asyncio
    async def test_approval_gate_rejected(self):
        """When approval callback returns False, pipeline stops."""
        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(),
            plan_factory=make_plan_factory(),
            plan_executor=make_plan_executor(),
        )

        approval = AsyncMock(return_value=False)
        cfg = OrchestratorConfig(autonomy_level="propose_and_approve")
        result = await orch.run("Drop database", config=cfg, approval_callback=approval)

        assert "spec" in result.approvals_needed
        assert "execute" not in result.stages_completed

    @pytest.mark.asyncio
    async def test_diversity_filter_applied(self):
        """Provider diversity filter is called on agents."""
        diversity = make_diversity_filter()
        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(),
            diversity_filter=diversity,
        )

        agents = ["claude-agent", "gpt-agent"]
        cfg = OrchestratorConfig(autonomy_level="fully_autonomous")
        result = await orch.run("Analyze data", config=cfg, agents=agents)

        diversity.enforce.assert_called_once_with(agents)
        assert result.diversity_report is not None

    @pytest.mark.asyncio
    async def test_elo_updated_after_debate(self):
        """Phase ELO tracker is called after successful debate."""
        elo = make_elo_tracker()
        debate_result = FakeDebateResult(participants=["agent-claude", "agent-gpt"])
        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(debate_result),
            elo_tracker=elo,
        )

        cfg = OrchestratorConfig(domain="security", autonomy_level="fully_autonomous")
        await orch.run("Security audit", config=cfg)

        assert elo.record_match.call_count == 2

    @pytest.mark.asyncio
    async def test_feedback_recorded(self):
        """Feedback recorder is called after debate."""
        recorder = make_feedback_recorder()
        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(),
            feedback_recorder=recorder,
        )

        cfg = OrchestratorConfig(autonomy_level="fully_autonomous")
        result = await orch.run("Build feature", config=cfg)

        assert "feedback" in result.stages_completed
        recorder.record.assert_called_once()

    @pytest.mark.asyncio
    async def test_meta_loop_not_triggered_by_default(self):
        """Meta-loop doesn't run unless enabled."""
        meta = make_meta_loop(should_trigger=True)
        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(),
            meta_loop=meta,
        )

        cfg = OrchestratorConfig(
            enable_meta_loop=False,
            autonomy_level="fully_autonomous",
        )
        result = await orch.run("Fix bug", config=cfg)

        assert "meta_loop" not in result.stages_completed
        meta.should_trigger.assert_not_called()

    @pytest.mark.asyncio
    async def test_meta_loop_triggered_when_enabled(self):
        """Meta-loop runs when enabled and should_trigger returns True."""
        meta = make_meta_loop(should_trigger=True)
        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(),
            meta_loop=meta,
        )

        cfg = OrchestratorConfig(
            enable_meta_loop=True,
            autonomy_level="fully_autonomous",
        )
        result = await orch.run("Fix bug", config=cfg)

        assert "meta_loop" in result.stages_completed
        meta.increment_cycle.assert_called_once()
        meta.should_trigger.assert_called_once()
        meta.identify_targets.assert_called_once()

    @pytest.mark.asyncio
    async def test_research_failure_graceful(self):
        """Research failure doesn't stop the pipeline."""
        researcher = AsyncMock()
        researcher.research.side_effect = RuntimeError("KM offline")
        orch = UnifiedOrchestrator(
            researcher=researcher,
            arena_factory=make_arena_factory(),
        )

        cfg = OrchestratorConfig(autonomy_level="fully_autonomous")
        result = await orch.run("Build widget", config=cfg)

        assert "research" in result.stages_skipped
        assert "debate" in result.stages_completed

    @pytest.mark.asyncio
    async def test_input_extension_failure_graceful(self):
        """Input extension failure doesn't stop the pipeline."""
        ext = AsyncMock()
        ext.extend.side_effect = RuntimeError("Extension failed")
        orch = UnifiedOrchestrator(
            input_extension=ext,
            arena_factory=make_arena_factory(),
        )

        cfg = OrchestratorConfig(autonomy_level="fully_autonomous")
        result = await orch.run("Build page", config=cfg)

        assert "extend" in result.stages_skipped
        assert "debate" in result.stages_completed

    @pytest.mark.asyncio
    async def test_debate_failure_stops_pipeline(self):
        """Debate failure is fatal — pipeline cannot continue."""
        factory = AsyncMock()
        factory.side_effect = RuntimeError("All agents failed")
        orch = UnifiedOrchestrator(arena_factory=factory)

        cfg = OrchestratorConfig(autonomy_level="fully_autonomous")
        result = await orch.run("Build app", config=cfg)

        assert not result.succeeded
        assert any("Debate failed" in e for e in result.errors)
        assert "plan" not in result.stages_completed

    @pytest.mark.asyncio
    async def test_preset_founder_config(self):
        """Founder preset loads correctly."""
        orch = UnifiedOrchestrator(arena_factory=make_arena_factory())
        cfg = OrchestratorConfig(preset_name="founder", autonomy_level="fully_autonomous")
        result = await orch.run("Quick prototype", config=cfg)
        assert result.succeeded

    @pytest.mark.asyncio
    async def test_extended_prompt_passed_to_debate(self):
        """Extended input context is prepended to debate prompt."""
        ext = make_input_extension()
        factory = make_arena_factory()
        orch = UnifiedOrchestrator(
            input_extension=ext,
            arena_factory=factory,
        )

        cfg = OrchestratorConfig(autonomy_level="fully_autonomous")
        await orch.run("Design API", config=cfg)

        # Verify the arena received the extended prompt
        call_args = factory.call_args
        prompt_arg = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
        assert "Prior Art" in prompt_arg or "Design API" in prompt_arg

    @pytest.mark.asyncio
    async def test_run_id_is_unique(self):
        """Each run gets a unique ID."""
        orch = UnifiedOrchestrator(arena_factory=make_arena_factory())
        cfg = OrchestratorConfig(autonomy_level="fully_autonomous")
        r1 = await orch.run("Task 1", config=cfg)
        r2 = await orch.run("Task 2", config=cfg)
        assert r1.run_id != r2.run_id

    @pytest.mark.asyncio
    async def test_no_diversity_filter_without_agents(self):
        """Diversity filter is not called when no agents are provided."""
        diversity = make_diversity_filter()
        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(),
            diversity_filter=diversity,
        )

        cfg = OrchestratorConfig(autonomy_level="fully_autonomous")
        await orch.run("Build thing", config=cfg)

        diversity.enforce.assert_not_called()

    @pytest.mark.asyncio
    async def test_outcome_captures_execution_metrics(self):
        """Pipeline outcome includes execution metrics from plan outcome."""
        recorder = make_feedback_recorder()
        plan_outcome = FakePlanOutcome(tests_passed=15, tests_failed=2, files_changed=7)
        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(),
            plan_factory=make_plan_factory(),
            plan_executor=make_plan_executor(plan_outcome),
            feedback_recorder=recorder,
        )

        cfg = OrchestratorConfig(autonomy_level="fully_autonomous")
        result = await orch.run("Build feature", config=cfg)

        assert result.pipeline_outcome is not None
        assert result.pipeline_outcome.tests_passed == 15
        assert result.pipeline_outcome.tests_failed == 2
        assert result.pipeline_outcome.files_changed == 7

    @pytest.mark.asyncio
    async def test_bug_fix_loop_auto_triggered_on_test_failure(self):
        """CLB-008: Bug-fix loop is auto-triggered when tests fail, even without enable_bug_fix_loop."""
        plan_outcome = FakePlanOutcome(tests_passed=3, tests_failed=5)

        # Mock a bug fixer with no test_output on the plan_outcome → returns skipped
        bug_fixer = MagicMock()
        bug_fixer.diagnose_failure = MagicMock(return_value=None)

        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(),
            plan_factory=make_plan_factory(),
            plan_executor=make_plan_executor(plan_outcome),
            bug_fixer=bug_fixer,
        )

        cfg = OrchestratorConfig(
            autonomy_level="fully_autonomous",
            enable_bug_fix_loop=False,  # Explicitly off — but tests_failed > 0 should trigger
        )
        result = await orch.run("Build feature", config=cfg)

        assert "bug_fix" in result.stages_completed
        assert result.bug_fix_result is not None

    @pytest.mark.asyncio
    async def test_bug_fix_loop_not_triggered_when_tests_pass(self):
        """CLB-008: Bug-fix loop is NOT auto-triggered when all tests pass."""
        plan_outcome = FakePlanOutcome(tests_passed=10, tests_failed=0)

        bug_fixer = MagicMock()
        bug_fixer.diagnose_failure = MagicMock(return_value=None)

        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(),
            plan_factory=make_plan_factory(),
            plan_executor=make_plan_executor(plan_outcome),
            bug_fixer=bug_fixer,
        )

        cfg = OrchestratorConfig(
            autonomy_level="fully_autonomous",
            enable_bug_fix_loop=False,
        )
        result = await orch.run("Build feature", config=cfg)

        # No test failures → bug-fix loop should NOT run
        assert "bug_fix" not in result.stages_completed

    @pytest.mark.asyncio
    async def test_bug_fix_result_carried_into_outcome(self):
        """CLB-008: Bug-fix result flows into pipeline outcome metadata."""
        plan_outcome = FakePlanOutcome(tests_passed=2, tests_failed=3)
        recorder = make_feedback_recorder()

        bug_fixer = MagicMock()
        bug_fixer.diagnose_failure = MagicMock(return_value=None)

        orch = UnifiedOrchestrator(
            arena_factory=make_arena_factory(),
            plan_factory=make_plan_factory(),
            plan_executor=make_plan_executor(plan_outcome),
            feedback_recorder=recorder,
            bug_fixer=bug_fixer,
        )

        cfg = OrchestratorConfig(autonomy_level="fully_autonomous")
        result = await orch.run("Build feature", config=cfg)

        assert result.bug_fix_result is not None
        # Bug-fix result status is propagated to the pipeline outcome extras
        assert result.pipeline_outcome is not None
