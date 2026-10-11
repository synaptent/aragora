"""``AutonomousOrchestrator`` inherits its feedback and coordination helpers from mixins.

Callers importing from ``aragora.nomic.autonomous_orchestrator`` are unaffected.
"""

from __future__ import annotations

import inspect
import typing
from pathlib import Path

import pytest

from aragora.nomic import autonomous_coordination as coordination
from aragora.nomic import autonomous_feedback as feedback
from aragora.nomic import autonomous_orchestrator as ao_module
from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator
from aragora.nomic.feedback_loop import FeedbackLoop
from aragora.nomic.hardened_budget import BudgetMixin
from aragora.nomic.hardened_orchestrator import HardenedOrchestrator
from aragora.nomic.task_decomposer import SubTask
from aragora.nomic.types import AgentAssignment, Track

FEEDBACK_METHODS = (
    "_record_agent_outcome",
    "_select_alternative_agent",
    "_enqueue_regression_goals",
    "_apply_self_correction",
    "_store_priority_adjustments",
)
COORDINATION_METHODS = (
    "_create_branches_for_assignments",
    "_merge_and_cleanup",
    "_create_convoy_for_goal",
    "_update_bead_status",
    "_complete_convoy",
    "_fabric_register_agent",
    "_fabric_track_usage",
    "_fabric_complete_task",
    "_fabric_notify_agents",
    "get_fabric_stats",
)
MOVED = [(feedback.AutonomousFeedbackMixin, n) for n in FEEDBACK_METHODS] + [
    (coordination.AutonomousCoordinationMixin, n) for n in COORDINATION_METHODS
]


@pytest.mark.parametrize(("mixin", "name"), MOVED)
def test_method_is_defined_on_its_mixin(mixin: type, name: str) -> None:
    assert issubclass(AutonomousOrchestrator, mixin)
    assert name in vars(mixin)
    assert name not in vars(AutonomousOrchestrator)
    assert inspect.getattr_static(AutonomousOrchestrator, name) is vars(mixin)[name]
    typing.get_type_hints(getattr(AutonomousOrchestrator, name))


def test_class_annotations_resolve_at_runtime() -> None:
    hints = typing.get_type_hints(HardenedOrchestrator)
    assert hints["aragora_path"] is Path
    assert hints["feedback_loop"] is FeedbackLoop
    assert hints["_bead_ids"] == dict[str, str]


def test_hardened_orchestrator_keeps_the_budget_outcome_recorder() -> None:
    assert HardenedOrchestrator._record_agent_outcome is BudgetMixin._record_agent_outcome


@pytest.mark.parametrize("module", [feedback, coordination])
def test_mixins_log_under_the_orchestrator_logger(module) -> None:
    assert module.logger is ao_module.logger


def test_alternative_agent_comes_from_the_track_config(tmp_path: Path) -> None:
    orchestrator = AutonomousOrchestrator(aragora_path=tmp_path)
    subtask = SubTask(id="s1", title="Add tests", description="cover the planner")

    def pick(agent_type: str) -> str | None:
        assignment = AgentAssignment(subtask=subtask, track=Track.QA, agent_type=agent_type)
        return orchestrator._select_alternative_agent(assignment)

    assert pick("claude") == "gemini"
    assert pick("gemini") == "claude"
