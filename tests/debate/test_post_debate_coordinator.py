"""Tests for PostDebateCoordinator pipeline (C4).

Verifies that:
1. Steps run in order: explain -> plan -> notify -> execute
2. Plan receives explanation context
3. Notification includes approval URL when plan exists
4. Failure in one step doesn't cascade to others
5. Configuration toggles steps on/off
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from aragora.debate.post_debate_coordinator import (
    PostDebateConfig,
    PostDebateCoordinator,
    PostDebateResult,
)


def _make_debate_result(consensus=True, confidence=0.85, task="Test task"):
    """Create a mock debate result."""
    result = MagicMock()
    result.consensus = "majority" if consensus else None
    result.confidence = confidence
    result.task = task
    result.domain = "general"
    result.messages = []
    result.winner = "claude"
    result.agents = ["claude", "gpt4"]
    result.debate_id = "test-debate"
    return result


class TestPostDebateResult:
    """Test PostDebateResult dataclass."""

    def test_defaults(self):
        r = PostDebateResult()
        assert r.debate_id == ""
        assert r.explanation is None
        assert r.plan is None
        assert r.notification_sent is False
        assert r.execution_result is None
        assert r.errors == []

    def test_success_when_no_errors(self):
        r = PostDebateResult(debate_id="d1")
        assert r.success is True

    def test_not_success_when_errors(self):
        r = PostDebateResult(debate_id="d1", errors=["step failed"])
        assert r.success is False


class TestPostDebateConfig:
    """Test PostDebateConfig defaults."""

    def test_defaults(self):
        config = PostDebateConfig()
        assert config.auto_explain is True
        assert config.auto_create_plan is True
        assert config.auto_notify is True
        assert config.auto_execute_plan is False
        assert config.plan_min_confidence == 0.7


class TestStepOrdering:
    """Test that pipeline steps execute in correct order."""

    def test_all_steps_disabled_returns_empty_result(self):
        config = PostDebateConfig(
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_execute_plan=False,
            auto_persist_receipt=False,
            auto_execution_bridge=False,
        )
        coordinator = PostDebateCoordinator(config=config)
        result = coordinator.run("d1", _make_debate_result())

        assert result.debate_id == "d1"
        assert result.explanation is None
        assert result.plan is None
        assert result.notification_sent is False
        assert result.execution_result is None

    def test_explain_only(self):
        config = PostDebateConfig(
            auto_explain=True,
            auto_create_plan=False,
            auto_notify=False,
        )
        coordinator = PostDebateCoordinator(config=config)

        with patch.object(coordinator, "_step_explain", return_value={"test": True}) as mock:
            result = coordinator.run("d1", _make_debate_result(), task="test task")
            mock.assert_called_once()
            assert result.explanation == {"test": True}

    def test_plan_skipped_below_confidence(self):
        config = PostDebateConfig(
            auto_create_plan=True,
            plan_min_confidence=0.9,
            auto_notify=False,
        )
        coordinator = PostDebateCoordinator(config=config)

        with patch.object(coordinator, "_step_create_plan") as mock:
            # confidence=0.5 < threshold 0.9
            result = coordinator.run("d1", _make_debate_result(), confidence=0.5)
            mock.assert_not_called()
            assert result.plan is None

    def test_plan_runs_above_confidence(self):
        config = PostDebateConfig(
            auto_create_plan=True,
            plan_min_confidence=0.7,
            auto_notify=False,
        )
        coordinator = PostDebateCoordinator(config=config)

        with patch.object(coordinator, "_step_create_plan", return_value={"plan": "test"}) as mock:
            result = coordinator.run("d1", _make_debate_result(), confidence=0.85)
            mock.assert_called_once()
            assert result.plan == {"plan": "test"}

    def test_execute_requires_plan(self):
        config = PostDebateConfig(
            auto_execute_plan=True,
            auto_notify=False,
        )
        coordinator = PostDebateCoordinator(config=config)

        # No plan created → no execution
        result = coordinator.run("d1", _make_debate_result())
        assert result.execution_result is None


class TestPlanReceivesExplanation:
    """Test that plan creation receives explanation context."""

    def test_plan_gets_explanation_when_available(self):
        config = PostDebateConfig(
            auto_explain=True,
            auto_create_plan=True,
            plan_min_confidence=0.5,
            auto_notify=False,
        )
        coordinator = PostDebateCoordinator(config=config)

        explanation = {"explanation": "test reason", "debate_id": "d1", "task": "t"}

        with patch.object(coordinator, "_step_explain", return_value=explanation):
            with patch.object(coordinator, "_step_create_plan") as plan_mock:
                plan_mock.return_value = {"plan": "test"}
                coordinator.run("d1", _make_debate_result(), confidence=0.8, task="t")
                # Check that explanation was passed to plan step
                call_args = plan_mock.call_args
                assert call_args[0][3] == explanation  # 4th positional arg is explanation


class TestNotificationContext:
    """Test that notifications include context from prior steps."""

    def test_notification_called_with_defaults(self):
        config = PostDebateConfig(auto_notify=True)
        coordinator = PostDebateCoordinator(config=config)

        with patch.object(coordinator, "_step_notify", return_value=True) as mock:
            result = coordinator.run("d1", _make_debate_result())
            mock.assert_called_once()
            assert result.notification_sent is True

    def test_notification_receives_explanation_and_plan(self):
        config = PostDebateConfig(
            auto_explain=True,
            auto_create_plan=True,
            auto_notify=True,
            plan_min_confidence=0.5,
        )
        coordinator = PostDebateCoordinator(config=config)

        expl = {"explanation": "reason"}
        plan = {"plan": "test_plan"}

        with patch.object(coordinator, "_step_explain", return_value=expl):
            with patch.object(coordinator, "_step_create_plan", return_value=plan):
                with patch.object(coordinator, "_step_notify") as notify_mock:
                    notify_mock.return_value = True
                    coordinator.run("d1", _make_debate_result(), confidence=0.9)
                    # Notification receives explanation and plan
                    call_args = notify_mock.call_args
                    assert call_args[0][2] == expl  # explanation
                    assert call_args[0][3] == plan  # plan


class TestFailureIsolation:
    """Test that failures in one step don't cascade."""

    def test_explain_failure_doesnt_prevent_notify(self):
        config = PostDebateConfig(
            auto_explain=True,
            auto_notify=True,
        )
        coordinator = PostDebateCoordinator(config=config)

        with patch.object(coordinator, "_step_explain", return_value=None):
            with patch.object(coordinator, "_step_notify", return_value=True) as notify:
                result = coordinator.run("d1", _make_debate_result())
                notify.assert_called_once()
                assert result.notification_sent is True
                assert result.explanation is None

    def test_plan_failure_doesnt_prevent_notify(self):
        config = PostDebateConfig(
            auto_create_plan=True,
            auto_notify=True,
            plan_min_confidence=0.5,
        )
        coordinator = PostDebateCoordinator(config=config)

        with patch.object(coordinator, "_step_create_plan", return_value=None):
            with patch.object(coordinator, "_step_notify", return_value=True) as notify:
                result = coordinator.run("d1", _make_debate_result(), confidence=0.9)
                notify.assert_called_once()
                assert result.plan is None

    def test_execute_skipped_without_plan(self):
        config = PostDebateConfig(
            auto_create_plan=True,
            auto_execute_plan=True,
            auto_notify=False,
            plan_min_confidence=0.5,
        )
        coordinator = PostDebateCoordinator(config=config)

        with patch.object(coordinator, "_step_create_plan", return_value=None):
            with patch.object(coordinator, "_step_execute_plan") as exec_mock:
                result = coordinator.run("d1", _make_debate_result(), confidence=0.9)
                exec_mock.assert_not_called()


class TestStepImplementations:
    """Test individual step implementations with mocked dependencies."""

    def test_step_explain_import_error(self):
        coordinator = PostDebateCoordinator()
        with patch.dict("sys.modules", {"aragora.explainability.builder": None}):
            result = coordinator._step_explain("d1", _make_debate_result(), "task")
            assert result is None

    def test_step_explain_uses_async_builder_signature(self):
        coordinator = PostDebateCoordinator()

        class _Decision:
            def to_dict(self):
                return {"decision_id": "dec-1"}

        class _Builder:
            async def build(self, result, context=None, include_counterfactuals=True):
                assert result is not None
                return _Decision()

            def generate_summary(self, decision):
                assert isinstance(decision, _Decision)
                return "summary"

        with patch("aragora.explainability.builder.ExplanationBuilder", _Builder):
            result = coordinator._step_explain("d1", _make_debate_result(), "task")

        assert result is not None
        assert result["explanation"] == "summary"
        assert result["decision"] == {"decision_id": "dec-1"}

    def test_run_async_callable_when_loop_already_running(self):
        coordinator = PostDebateCoordinator()

        async def _returns_value(value):
            return value

        async def _inside_loop():
            return coordinator._run_async_callable(_returns_value, 7)

        assert asyncio.run(_inside_loop()) == 7

    def test_step_notify_import_error(self):
        coordinator = PostDebateCoordinator()
        with patch.dict("sys.modules", {"aragora.notifications.service": None}):
            result = coordinator._step_notify("d1", _make_debate_result(), None, None)
            assert result is False

    def test_step_execute_import_error(self):
        coordinator = PostDebateCoordinator()
        with patch.dict("sys.modules", {"aragora.pipeline.executor": None}):
            result = coordinator._step_execute_plan({"plan": MagicMock()}, None)
            assert result is None

    def test_step_execute_skips_non_approved(self):
        coordinator = PostDebateCoordinator()
        plan_obj = MagicMock()
        plan_obj.status = "draft"
        plan_data = {"plan": plan_obj}

        with patch("aragora.pipeline.executor.PlanExecutor", create=True):
            result = coordinator._step_execute_plan(plan_data, None)
            assert result is not None
            assert result.get("skipped") is True

    def test_default_config(self):
        coordinator = PostDebateCoordinator()
        assert coordinator.config.auto_explain is True
        assert coordinator.config.auto_notify is True


class TestExecutionSafetyGate:
    """Test execution gate wiring inside PostDebateCoordinator.run()."""

    def test_execution_plan_blocked_when_gate_denies(self):
        config = PostDebateConfig(
            auto_explain=False,
            auto_create_plan=True,
            auto_notify=False,
            auto_execute_plan=True,
            auto_persist_receipt=False,
            auto_execution_bridge=False,
            plan_min_confidence=0.5,
            enforce_execution_safety_gate=True,
        )
        coordinator = PostDebateCoordinator(config=config)
        plan_obj = MagicMock()
        plan_obj.status = "approved"

        with patch.object(coordinator, "_step_create_plan", return_value={"plan": plan_obj}):
            with patch.object(coordinator, "_step_execution_gate") as gate_mock:
                gate_mock.return_value = {
                    "allow_auto_execution": False,
                    "reason_codes": ["provider_diversity_below_minimum"],
                }
                with patch.object(coordinator, "_step_execute_plan") as exec_mock:
                    result = coordinator.run("d1", _make_debate_result(), confidence=0.9)

        exec_mock.assert_not_called()
        assert result.execution_result is not None
        assert result.execution_result.get("skipped") is True
        assert result.execution_result.get("reason") == "execution_gate_blocked"

    def test_plan_forced_to_human_approval_when_gate_denies(self):
        config = PostDebateConfig(
            auto_explain=False,
            auto_create_plan=True,
            auto_notify=False,
            auto_execute_plan=False,
            auto_persist_receipt=False,
            auto_execution_bridge=False,
            plan_min_confidence=0.5,
            enforce_execution_safety_gate=True,
        )
        coordinator = PostDebateCoordinator(config=config)

        class _Plan:
            def __init__(self):
                self.metadata = {}
                self.approval_mode = None
                self.status = None

        plan_obj = _Plan()
        with patch.object(coordinator, "_step_create_plan", return_value={"plan": plan_obj}):
            with patch.object(coordinator, "_step_execution_gate") as gate_mock:
                gate_mock.return_value = {
                    "allow_auto_execution": False,
                    "reason_codes": ["tainted_context_detected"],
                }
                result = coordinator.run("d1", _make_debate_result(), confidence=0.9)

        assert result.plan is not None
        assert plan_obj.metadata.get("execution_gate") is not None
        assert str(plan_obj.status).lower().endswith("awaiting_approval")
