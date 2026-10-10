"""``HardenedOrchestrator`` inherits agent selection and work routing from ``AgentPoolMixin``.

Callers importing from ``aragora.nomic.hardened_orchestrator`` are unaffected, and
every other attribute still resolves to the class it resolved to before the move.
"""

from __future__ import annotations

import inspect
import types
import typing
from typing import Any

import pytest

from aragora.nomic import hardened_agent_pool
from aragora.nomic import hardened_orchestrator as ho_module
from aragora.nomic.hardened_agent_pool import AgentPoolMixin
from aragora.nomic.hardened_budget import BudgetMixin
from aragora.nomic.hardened_orchestrator import HardenedOrchestrator
from aragora.nomic.risk_scorer import RiskScorer

MOVED_FUNCTIONS = (
    "_select_best_agent",
    "_task_to_elo_domain",
    "_cross_agent_review",
    "_find_stealable_work",
    "_is_computer_use_task",
    "_execute_computer_use",
)
MOVED_MEMBERS = (*MOVED_FUNCTIONS, "_COMPUTER_USE_KEYWORDS")

MRO_WITHOUT_AGENT_POOL_MIXIN = [
    "HardenedOrchestrator",
    "BudgetMixin",
    "GauntletMixin",
    "AuditMixin",
    "SafetyMixin",
    "AutonomousOrchestrator",
    "AutonomousWorkflowMixin",
    "AutonomousFeedbackMixin",
    "AutonomousCoordinationMixin",
    "object",
]


@pytest.mark.parametrize("name", MOVED_MEMBERS)
def test_member_is_defined_on_the_agent_pool_mixin(name: str) -> None:
    assert name in vars(AgentPoolMixin)
    assert name not in vars(HardenedOrchestrator)
    assert inspect.getattr_static(HardenedOrchestrator, name) is vars(AgentPoolMixin)[name]


def test_agent_pool_mixin_sits_after_the_safety_mixin() -> None:
    names = [cls.__name__ for cls in HardenedOrchestrator.__mro__]
    assert names.index("AgentPoolMixin") == names.index("SafetyMixin") + 1
    names.remove("AgentPoolMixin")
    assert names == MRO_WITHOUT_AGENT_POOL_MIXIN


def test_agent_pool_mixin_defines_only_the_moved_functions_at_runtime() -> None:
    defined = {
        name
        for name, value in vars(AgentPoolMixin).items()
        if inspect.isfunction(value) or isinstance(value, (staticmethod, classmethod))
    }
    assert defined == set(MOVED_FUNCTIONS)


@pytest.mark.parametrize("name", MOVED_MEMBERS)
def test_no_other_class_in_the_mro_defines_a_moved_member(name: str) -> None:
    owners = [cls for cls in HardenedOrchestrator.__mro__ if name in vars(cls)]
    assert owners == [AgentPoolMixin]


def test_method_kinds_are_unchanged() -> None:
    assert isinstance(vars(AgentPoolMixin)["_task_to_elo_domain"], staticmethod)
    assert isinstance(vars(AgentPoolMixin)["_is_computer_use_task"], classmethod)
    assert inspect.iscoroutinefunction(HardenedOrchestrator._cross_agent_review)
    assert inspect.iscoroutinefunction(HardenedOrchestrator._execute_computer_use)


@pytest.mark.parametrize(
    "name", ["_cross_agent_review", "_find_stealable_work", "_execute_computer_use"]
)
def test_assignment_annotations_resolve_at_runtime(name: str) -> None:
    hints = typing.get_type_hints(getattr(HardenedOrchestrator, name))
    assert "assignment" in hints or "assignments" in hints


def test_budget_outcome_recorder_still_wins() -> None:
    assert HardenedOrchestrator._record_agent_outcome is BudgetMixin._record_agent_outcome


def test_mixin_logs_under_the_orchestrator_logger() -> None:
    assert hardened_agent_pool.logger is ho_module.logger


def test_new_module_scores_like_its_facade() -> None:
    def weight(path: str) -> float:
        result = RiskScorer().score_goal("Tidy helper names", file_scope=[path])
        return next(f.weight for f in result.factors if f.name == "file_scope")

    assert weight("aragora/nomic/hardened_agent_pool.py") == pytest.approx(
        weight("aragora/nomic/hardened_orchestrator.py")
    )


def test_subtask_classification_through_the_facade_class() -> None:
    def subtask(title: str, description: str = "") -> Any:
        return types.SimpleNamespace(title=title, description=description)

    assert HardenedOrchestrator._task_to_elo_domain(subtask("Fix auth token refresh")) == "security"
    assert HardenedOrchestrator._task_to_elo_domain(subtask("Rename a variable")) == "general"
    assert HardenedOrchestrator._is_computer_use_task(subtask("Click the browser button"))
    assert not HardenedOrchestrator._is_computer_use_task(subtask("Refactor the parser"))


def test_work_stealing_skips_blocked_assignments() -> None:
    orchestrator = HardenedOrchestrator.__new__(HardenedOrchestrator)
    setattr(orchestrator, "_check_agent_circuit_breaker", lambda agent_type: True)
    setattr(orchestrator, "_emit_event", lambda event_type, **data: None)

    def assignment(task_id: str, status: str, deps: list[str]) -> Any:
        return types.SimpleNamespace(
            status=status, subtask=types.SimpleNamespace(id=task_id, dependencies=deps)
        )

    blocked = assignment("b", "pending", ["a"])
    ready = assignment("c", "pending", [])
    running = assignment("a", "running", [])
    stolen = orchestrator._find_stealable_work("claude", [running, blocked, ready])
    assert stolen is ready
