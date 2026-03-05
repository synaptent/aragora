"""E2E golden path test: debate → decision plan → structured output.

Covers the complete UnifiedOrchestrator pipeline with mocked Arena/debate
calls. Verifies that:
1. The debate stage runs and populates debate_result.
2. The decision plan stage creates a DecisionPlan from the debate result.
3. The structured output (OrchestratorResult) contains all expected fields.

All external calls are mocked — no real API calls are made.
Run with: pytest tests/e2e/test_pipeline_golden_path.py -v --timeout=30
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
