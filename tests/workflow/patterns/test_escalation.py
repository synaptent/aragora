"""Tests for EscalationWorkflowPattern."""

import pytest
from datetime import datetime, timezone

from aragora.workflow.patterns.escalation import (
    EscalationStep,
    EscalationPathConfig,
    EscalationWorkflowPattern,
    STANDARD_ESCALATION_PATH,
)


@pytest.fixture
def pattern():
    return EscalationWorkflowPattern()


class TestEscalationStep:
    """Tests for the EscalationStep data class."""

    def test_create_step(self):
        step = EscalationStep(
            level=1,
            delay_minutes=15,
            notify_channels=["slack"],
            action="notify",
        )
        assert step.level == 1
        assert step.delay_minutes == 15
        assert step.notify_channels == ["slack"]
        assert step.action == "notify"

    def test_step_actions(self):
        for action in ("notify", "reassign", "executive_summary"):
            step = EscalationStep(
                level=1,
                delay_minutes=10,
                notify_channels=["email"],
                action=action,
            )
            assert step.action == action


class TestEscalationPathConfig:
    """Tests for EscalationPathConfig."""

    def test_default_empty(self):
        cfg = EscalationPathConfig()
        assert cfg.steps == []

    def test_with_steps(self):
        steps = [
            EscalationStep(level=1, delay_minutes=5, notify_channels=["slack"], action="notify"),
            EscalationStep(level=2, delay_minutes=15, notify_channels=["email"], action="reassign"),
        ]
        cfg = EscalationPathConfig(steps=steps)
        assert len(cfg.steps) == 2
        assert cfg.steps[0].level == 1
        assert cfg.steps[1].level == 2


class TestStandardEscalationPath:
    """Tests for the STANDARD_ESCALATION_PATH constant."""

    def test_has_three_levels(self):
        assert len(STANDARD_ESCALATION_PATH.steps) == 3

    def test_level_order(self):
        levels = [s.level for s in STANDARD_ESCALATION_PATH.steps]
        assert levels == [1, 2, 3]

    def test_delays_increasing(self):
        delays = [s.delay_minutes for s in STANDARD_ESCALATION_PATH.steps]
        assert delays == [15, 30, 60]

    def test_actions(self):
        actions = [s.action for s in STANDARD_ESCALATION_PATH.steps]
        assert actions == ["notify", "reassign", "executive_summary"]

    def test_channels_expand(self):
        # Each level should have at least as many channels as the previous
        for i in range(1, len(STANDARD_ESCALATION_PATH.steps)):
            prev = len(STANDARD_ESCALATION_PATH.steps[i - 1].notify_channels)
            curr = len(STANDARD_ESCALATION_PATH.steps[i].notify_channels)
            assert curr >= prev


class TestCreateWorkflow:
    """Tests for EscalationWorkflowPattern.create_workflow."""

    def test_returns_workflow_dict(self, pattern):
        wf = pattern.create_workflow("debate-1")
        assert isinstance(wf, dict)
        assert wf["debate_id"] == "debate-1"
        assert "id" in wf
        assert wf["id"].startswith("escalation_")

    def test_uses_standard_path_by_default(self, pattern):
        wf = pattern.create_workflow("debate-1")
        assert wf["total_levels"] == 3
        assert len(wf["steps"]) == 3

    def test_custom_config(self, pattern):
        custom = EscalationPathConfig(
            steps=[
                EscalationStep(
                    level=1,
                    delay_minutes=10,
                    notify_channels=["webhook"],
                    action="notify",
                ),
            ]
        )
        wf = pattern.create_workflow("debate-2", config=custom)
        assert wf["total_levels"] == 1
        assert wf["steps"][0]["notify_channels"] == ["webhook"]

    def test_step_ids_contain_level(self, pattern):
        wf = pattern.create_workflow("debate-1")
        for step in wf["steps"]:
            assert "escalation_level_" in step["id"]

    def test_workflow_name_contains_debate_id(self, pattern):
        wf = pattern.create_workflow("debate-42")
        assert "debate-42" in wf["name"]


class TestTriggerEscalation:
    """Tests for EscalationWorkflowPattern.trigger_escalation."""

    def test_returns_escalation_event(self, pattern):
        result = pattern.trigger_escalation("debate-1", level=1, context={"reason": "sla"})
        assert result["debate_id"] == "debate-1"
        assert result["level"] == 1
        assert result["status"] == "triggered"
        assert result["context"] == {"reason": "sla"}

    def test_triggered_at_is_iso(self, pattern):
        result = pattern.trigger_escalation("debate-1", level=2)
        # Should be parseable
        dt = datetime.fromisoformat(result["triggered_at"])
        assert dt.tzinfo is not None

    def test_default_empty_context(self, pattern):
        result = pattern.trigger_escalation("debate-1", level=1)
        assert result["context"] == {}

    def test_different_levels(self, pattern):
        for lvl in (1, 2, 3):
            result = pattern.trigger_escalation("d", level=lvl)
            assert result["level"] == lvl
