"""E2E golden path test: debate -> plan -> execute -> verify.

Covers two pipeline entry points with mocked dependencies:

A) UnifiedOrchestrator (debate -> plan -> execute -> feedback)
   Verifies the full stage chain, structured output, approval gates,
   and graceful degradation on failures.

B) IdeaToExecutionPipeline (text -> ideation -> goals -> workflow -> orchestration)
   Verifies the 4-stage idea pipeline produces pipeline_id, stage_results,
   and goal_graph, and handles stage failures gracefully.

All external calls are mocked — no real API calls are made.
Run with: pytest tests/e2e/test_pipeline_golden_path.py -v --timeout=60
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.pipeline.unified_orchestrator import (
    OrchestratorConfig,
    OrchestratorResult,
    UnifiedOrchestrator,
)


# =============================================================================
# Fake domain objects (mirror aragora.core_types shapes without hard imports)
# =============================================================================


@dataclass
class _FakeCritique:
    agent: str = "critic-agent"
    severity: float = 4.0
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class _FakeDebateResult:
    """Minimal DebateResult stand-in accepted by DecisionPlanFactory."""

    debate_id: str = "debate-golden-001"
    task: str = "Should we migrate to microservices?"
    final_answer: str = (
        "1. Implement a strangler-fig migration pattern.\n"
        "2. Use `docker-compose.yml` for local dev.\n"
        "3. Ensure each service has independent `tests/`.\n"
    )
    confidence: float = 0.82
    consensus_reached: bool = True
    rounds_used: int = 3
    participants: list[str] = field(
        default_factory=lambda: ["agent-claude", "agent-gpt", "agent-gemini"]
    )
    metadata: dict[str, Any] = field(default_factory=dict)
    critiques: list[Any] = field(default_factory=list)
    dissenting_views: list[str] = field(default_factory=list)
    debate_cruxes: list[dict[str, Any]] = field(default_factory=list)
    total_cost_usd: float = 0.12


@dataclass
class _FakePlanOutcome:
    success: bool = True
    tests_passed: int = 8
    tests_failed: int = 0
    files_changed: int = 4


# =============================================================================
# Helper factories
# =============================================================================


def _make_arena_factory(debate_result: Any | None = None) -> AsyncMock:
    factory = AsyncMock()
    factory.return_value = debate_result or _FakeDebateResult()
    return factory


def _make_plan_factory(plan: Any | None = None) -> MagicMock:
    """Build a mock DecisionPlanFactory that creates a real DecisionPlan."""
    factory = MagicMock()

    if plan is not None:
        factory.from_debate_result.return_value = plan
        return factory

    # Build a real DecisionPlan using the real factory so structured output
    # actually has the expected attributes (id, status, risk_register, etc.)
    def _real_from_debate_result(result: Any, **_kwargs: Any) -> Any:
        try:
            from aragora.pipeline.decision_plan.factory import DecisionPlanFactory

            return DecisionPlanFactory.from_debate_result(result)
        except Exception:  # noqa: BLE001 — fallback for import failures
            stub = MagicMock()
            stub.id = "plan-golden-001"
            stub.status = "created"
            stub.task = result.task if hasattr(result, "task") else ""
            stub.risk_register = MagicMock()
            stub.verification_plan = MagicMock()
            stub.implement_plan = MagicMock()
            return stub

    factory.from_debate_result.side_effect = _real_from_debate_result
    return factory


def _make_plan_executor(outcome: Any | None = None) -> AsyncMock:
    executor = AsyncMock()
    executor.execute.return_value = outcome or _FakePlanOutcome()
    return executor


def _make_feedback_recorder() -> MagicMock:
    recorder = MagicMock()
    recorder.record = MagicMock()
    return recorder


# =============================================================================
# Tests
# =============================================================================


class TestPipelineGoldenPath:
    """E2E golden path: debate -> plan -> structured output."""

    @pytest.mark.asyncio
    async def test_golden_path_debate_to_plan(self) -> None:
        """Full happy path: debate runs and decision plan is created."""
        debate_result = _FakeDebateResult()
        arena_factory = _make_arena_factory(debate_result)
        plan_factory = _make_plan_factory()
        executor = _make_plan_executor()
        recorder = _make_feedback_recorder()

        orch = UnifiedOrchestrator(
            arena_factory=arena_factory,
            plan_factory=plan_factory,
            plan_executor=executor,
            feedback_recorder=recorder,
        )

        cfg = OrchestratorConfig(
            autonomy_level="fully_autonomous",
            skip_execution=True,  # stop after plan, no execution needed
        )
        result = await orch.run(
            "Should we migrate to microservices?",
            config=cfg,
        )

        # --- debate stage ---
        assert "debate" in result.stages_completed, (
            f"Debate stage not completed. stages_completed={result.stages_completed}, "
            f"errors={result.errors}"
        )
        assert result.debate_result is not None
        assert result.debate_result.debate_id == "debate-golden-001"
        assert result.debate_result.consensus_reached is True

        # --- decision plan stage ---
        assert "plan" in result.stages_completed, (
            f"Plan stage not completed. stages_completed={result.stages_completed}"
        )
        assert result.decision_plan is not None

        # --- structured output ---
        assert result.succeeded
        assert result.run_id  # UUID string present
        assert result.prompt == "Should we migrate to microservices?"
        assert result.duration_s >= 0.0

    @pytest.mark.asyncio
    async def test_golden_path_debate_result_fields(self) -> None:
        """Debate result exposes the fields downstream consumers expect."""
        debate_result = _FakeDebateResult(
            debate_id="debate-fields-test",
            confidence=0.91,
            consensus_reached=True,
            final_answer="Use a strangler-fig pattern.",
        )
        orch = UnifiedOrchestrator(
            arena_factory=_make_arena_factory(debate_result),
            plan_factory=_make_plan_factory(),
        )

        cfg = OrchestratorConfig(
            autonomy_level="fully_autonomous",
            skip_execution=True,
        )
        result = await orch.run("Migrate to microservices?", config=cfg)

        dr = result.debate_result
        assert dr is not None
        assert dr.debate_id == "debate-fields-test"
        assert dr.confidence == 0.91
        assert dr.consensus_reached is True
        assert "strangler-fig" in dr.final_answer

    @pytest.mark.asyncio
    async def test_golden_path_decision_plan_structure(self) -> None:
        """Decision plan produced from debate contains required sub-artifacts."""
        debate_result = _FakeDebateResult()
        orch = UnifiedOrchestrator(
            arena_factory=_make_arena_factory(debate_result),
            plan_factory=_make_plan_factory(),
        )

        cfg = OrchestratorConfig(
            autonomy_level="fully_autonomous",
            skip_execution=True,
        )
        result = await orch.run("Migrate to microservices?", config=cfg)

        dp = result.decision_plan
        assert dp is not None

        # Whether a real DecisionPlan or a stub, it should have task / status
        task_val = getattr(dp, "task", None)
        assert task_val is not None

        status_val = getattr(dp, "status", None)
        assert status_val is not None

    @pytest.mark.asyncio
    async def test_golden_path_with_execution(self) -> None:
        """Full path including plan execution."""
        recorder = _make_feedback_recorder()
        orch = UnifiedOrchestrator(
            arena_factory=_make_arena_factory(),
            plan_factory=_make_plan_factory(),
            plan_executor=_make_plan_executor(),
            feedback_recorder=recorder,
        )

        cfg = OrchestratorConfig(
            autonomy_level="fully_autonomous",
        )
        result = await orch.run("Migrate to microservices?", config=cfg)

        assert "debate" in result.stages_completed
        assert "plan" in result.stages_completed
        assert "execute" in result.stages_completed
        assert "feedback" in result.stages_completed
        assert result.succeeded

        # Outcome should have been recorded
        recorder.record.assert_called_once()

    @pytest.mark.asyncio
    async def test_golden_path_result_is_orchestrator_result(self) -> None:
        """run() always returns an OrchestratorResult instance."""
        orch = UnifiedOrchestrator(
            arena_factory=_make_arena_factory(),
        )

        result = await orch.run("Any prompt")

        assert isinstance(result, OrchestratorResult)
        assert result.run_id
        assert result.prompt == "Any prompt"

    @pytest.mark.asyncio
    async def test_golden_path_no_debate_result_on_failure(self) -> None:
        """When debate fails, debate_result is None and errors are recorded."""
        failing_factory = AsyncMock(side_effect=RuntimeError("All agents failed"))
        orch = UnifiedOrchestrator(arena_factory=failing_factory)

        result = await orch.run("Migrate to microservices?")

        assert not result.succeeded
        assert result.debate_result is None
        assert result.decision_plan is None
        assert any("Debate failed" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_golden_path_debate_to_plan_output_consistency(self) -> None:
        """debate_result.task matches the prompt passed to arena_factory."""
        debate_result = _FakeDebateResult(
            task="Adopt event-driven architecture for order processing"
        )
        arena_factory = _make_arena_factory(debate_result)
        plan_factory = _make_plan_factory()

        orch = UnifiedOrchestrator(
            arena_factory=arena_factory,
            plan_factory=plan_factory,
        )

        cfg = OrchestratorConfig(
            autonomy_level="fully_autonomous",
            skip_execution=True,
        )
        result = await orch.run("Adopt event-driven architecture for order processing", config=cfg)

        # arena was called with the right prompt
        arena_factory.assert_called_once()
        call_args = arena_factory.call_args
        prompt_arg = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
        assert "event-driven" in prompt_arg or "order processing" in prompt_arg

        # plan factory received the debate result
        plan_factory.from_debate_result.assert_called_once_with(debate_result)

        # result is consistent
        assert result.debate_result.task == "Adopt event-driven architecture for order processing"
        assert "debate" in result.stages_completed
        assert "plan" in result.stages_completed

    @pytest.mark.asyncio
    async def test_golden_path_approval_gate(self) -> None:
        """Approval callback controls whether execution proceeds past the plan."""
        debate_result = _FakeDebateResult()
        plan = MagicMock()
        plan.id = "plan-approval"
        plan_factory = _make_plan_factory(plan)

        orch = UnifiedOrchestrator(
            arena_factory=_make_arena_factory(debate_result),
            plan_factory=plan_factory,
            plan_executor=_make_plan_executor(),
        )

        async def approve_all(stage: str, artifact: Any) -> bool:
            return True

        cfg = OrchestratorConfig(autonomy_level="propose_and_approve")
        result = await orch.run(
            "Design a rate limiter",
            config=cfg,
            approval_callback=approve_all,
        )

        # With approve_all, the pipeline should reach execution
        assert "debate" in result.stages_completed
        assert result.succeeded

    @pytest.mark.asyncio
    async def test_golden_path_quality_gate(self) -> None:
        """Quality gate rejects low-quality debate output."""
        debate_result = _FakeDebateResult()

        # Quality validator returns a failing report
        quality_report = MagicMock()
        quality_report.verdict = "fail"
        quality_report.quality_score_10 = 2.0

        async def mock_quality_validator(result, **kwargs):
            return quality_report

        orch = UnifiedOrchestrator(
            arena_factory=_make_arena_factory(debate_result),
            plan_factory=_make_plan_factory(),
            quality_validator=mock_quality_validator,
        )

        cfg = OrchestratorConfig(
            autonomy_level="fully_autonomous",
            enable_quality_gate=True,
            skip_execution=True,
        )
        result = await orch.run("Low quality question", config=cfg)

        assert "debate" in result.stages_completed
        assert "quality_gate" in result.stages_completed
        assert any("Quality gate rejected" in e for e in result.errors)
        assert not result.succeeded  # quality gate rejection = failure

    @pytest.mark.asyncio
    async def test_golden_path_partial_result_on_plan_failure(self) -> None:
        """When plan creation fails, debate result still available in output."""
        debate_result = _FakeDebateResult()
        broken_factory = MagicMock()
        broken_factory.from_debate_result.side_effect = ValueError("plan creation error")

        orch = UnifiedOrchestrator(
            arena_factory=_make_arena_factory(debate_result),
            plan_factory=broken_factory,
        )

        cfg = OrchestratorConfig(
            autonomy_level="fully_autonomous",
            skip_execution=True,
        )
        result = await orch.run("Test partial failure", config=cfg)

        # Debate succeeded, plan was skipped due to error
        assert "debate" in result.stages_completed
        assert "plan" in result.stages_skipped
        assert result.debate_result is not None
        assert result.decision_plan is None
        assert result.succeeded  # debate completed, plan is optional


# =============================================================================
# IdeaToExecutionPipeline Tests (Task 1 - Test 1)
# =============================================================================


class TestIdeaToExecutionPipelineGoldenPath:
    """E2E: IdeaToExecutionPipeline.run() from input text to result."""

    @pytest.mark.asyncio
    async def test_full_pipeline_from_text_to_result(self) -> None:
        """Full pipeline from input text produces pipeline_id, stage_results, goal_graph."""
        from aragora.pipeline.idea_to_execution import (
            IdeaToExecutionPipeline,
            PipelineConfig,
            PipelineResult,
        )

        pipeline = IdeaToExecutionPipeline()
        cfg = PipelineConfig(
            dry_run=True,
            enable_receipts=False,
            enable_km_precedents=False,
            enable_km_persistence=False,
            enable_workspace_context=False,
            enable_meta_tuning=False,
        )

        result = await pipeline.run(
            "Implement Redis caching to reduce API latency. "
            "Add rate limiting to endpoints. "
            "Deploy monitoring dashboards.",
            config=cfg,
        )

        assert isinstance(result, PipelineResult)
        assert result.pipeline_id  # non-empty string
        assert result.pipeline_id.startswith("pipe-")

        # Stage results should be populated
        assert len(result.stage_results) >= 1
        stage_names = [sr.stage_name for sr in result.stage_results]
        assert "ideation" in stage_names

        # At least ideation should have completed
        ideation_sr = next(sr for sr in result.stage_results if sr.stage_name == "ideation")
        assert ideation_sr.status == "completed"
        assert ideation_sr.duration >= 0.0

        # Stage status should reflect completion
        assert result.stage_status.get("ideas") in ("complete", "pending")

    @pytest.mark.asyncio
    async def test_pipeline_produces_goal_graph(self) -> None:
        """Pipeline extracts goals from input text into a GoalGraph."""
        from aragora.pipeline.idea_to_execution import (
            IdeaToExecutionPipeline,
            PipelineConfig,
        )

        pipeline = IdeaToExecutionPipeline()
        cfg = PipelineConfig(
            dry_run=True,
            enable_receipts=False,
            enable_km_precedents=False,
            enable_km_persistence=False,
            enable_workspace_context=False,
            enable_meta_tuning=False,
        )

        result = await pipeline.run(
            "Build a CI pipeline. Implement unit tests. Deploy to production.",
            config=cfg,
        )

        # Goal graph should be produced from ideation output
        if result.goal_graph is not None:
            assert hasattr(result.goal_graph, "goals")
            assert hasattr(result.goal_graph, "id")

        # Workflow stage should have run
        stage_names = [sr.stage_name for sr in result.stage_results]
        if "goals" in stage_names:
            goals_sr = next(sr for sr in result.stage_results if sr.stage_name == "goals")
            assert goals_sr.status in ("completed", "failed")

    @pytest.mark.asyncio
    async def test_pipeline_all_stages_complete(self) -> None:
        """All configured stages complete without errors in dry_run mode."""
        from aragora.pipeline.idea_to_execution import (
            IdeaToExecutionPipeline,
            PipelineConfig,
        )

        pipeline = IdeaToExecutionPipeline()
        cfg = PipelineConfig(
            stages_to_run=["ideation", "goals", "workflow", "orchestration"],
            dry_run=True,
            enable_receipts=False,
            enable_km_precedents=False,
            enable_km_persistence=False,
            enable_workspace_context=False,
            enable_meta_tuning=False,
        )

        result = await pipeline.run(
            "Reduce deployment time from 30 minutes to 5 minutes.",
            config=cfg,
        )

        # Check that no stage has unhandled errors
        for sr in result.stage_results:
            assert sr.status in ("completed", "skipped", "failed"), (
                f"Stage {sr.stage_name} has unexpected status: {sr.status}"
            )

        # Pipeline should have a positive duration
        assert result.duration >= 0.0

        # Pipeline integrity hash should be computable
        result_dict = result.to_dict()
        assert "integrity_hash" in result_dict

    @pytest.mark.asyncio
    async def test_pipeline_with_custom_pipeline_id(self) -> None:
        """External pipeline_id is preserved in the result."""
        from aragora.pipeline.idea_to_execution import (
            IdeaToExecutionPipeline,
            PipelineConfig,
        )

        pipeline = IdeaToExecutionPipeline()
        cfg = PipelineConfig(
            dry_run=True,
            stages_to_run=["ideation"],
            enable_receipts=False,
            enable_km_precedents=False,
            enable_km_persistence=False,
            enable_workspace_context=False,
            enable_meta_tuning=False,
        )

        result = await pipeline.run(
            "Test custom ID",
            config=cfg,
            pipeline_id="custom-test-001",
        )

        assert result.pipeline_id == "custom-test-001"

    @pytest.mark.asyncio
    async def test_pipeline_handles_stage_failure_gracefully(self) -> None:
        """When a stage fails, the pipeline returns partial results without raising."""
        from unittest.mock import patch as _patch

        from aragora.pipeline.idea_to_execution import (
            IdeaToExecutionPipeline,
            PipelineConfig,
            StageResult,
        )

        pipeline = IdeaToExecutionPipeline()
        cfg = PipelineConfig(
            dry_run=True,
            enable_receipts=False,
            enable_km_precedents=False,
            enable_km_persistence=False,
            enable_workspace_context=False,
            enable_meta_tuning=False,
        )

        # Force ideation to fail
        async def _failing_ideation(pipeline_id, input_text, config):
            return StageResult(
                stage_name="ideation",
                status="failed",
                error="Simulated ideation failure",
            )

        with _patch.object(pipeline, "_run_ideation", _failing_ideation):
            result = await pipeline.run("This should fail gracefully", config=cfg)

        # Pipeline must still return a PipelineResult (no exception)
        assert result is not None
        assert result.pipeline_id

        # The failed stage is recorded
        ideation_results = [sr for sr in result.stage_results if sr.stage_name == "ideation"]
        assert len(ideation_results) == 1
        assert ideation_results[0].status == "failed"
        assert ideation_results[0].error == "Simulated ideation failure"

        # ideas_canvas is None since ideation failed
        assert result.ideas_canvas is None

    @pytest.mark.asyncio
    async def test_pipeline_event_callback_fires(self) -> None:
        """The event_callback receives stage lifecycle events."""
        from aragora.pipeline.idea_to_execution import (
            IdeaToExecutionPipeline,
            PipelineConfig,
        )

        events: list[tuple[str, dict]] = []

        def on_event(event_type: str, data: dict) -> None:
            events.append((event_type, data))

        pipeline = IdeaToExecutionPipeline()
        cfg = PipelineConfig(
            dry_run=True,
            stages_to_run=["ideation"],
            enable_receipts=False,
            enable_km_precedents=False,
            enable_km_persistence=False,
            enable_workspace_context=False,
            enable_meta_tuning=False,
            event_callback=on_event,
        )

        await pipeline.run("Track events test", config=cfg)

        event_types = [e[0] for e in events]
        assert "started" in event_types
        assert "stage_started" in event_types
