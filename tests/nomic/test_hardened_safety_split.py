"""``HardenedOrchestrator`` inherits its prompt defense and safety gates from ``SafetyMixin``.

Callers importing from ``aragora.nomic.hardened_orchestrator`` are unaffected, and
every other attribute still resolves to the class it resolved to before the move.
"""

from __future__ import annotations

import inspect
import typing

import pytest

from aragora.nomic import hardened_orchestrator as ho_module
from aragora.nomic import hardened_safety
from aragora.nomic.hardened_budget import BudgetMixin
from aragora.nomic.hardened_orchestrator import HardenedOrchestrator
from aragora.nomic.hardened_safety import SafetyMixin
from aragora.nomic.risk_scorer import RiskScorer

MOVED_METHODS = (
    "_scan_for_injection",
    "get_canary_directive",
    "_check_canary_leak",
    "_validate_output",
    "_run_review_gate",
    "_run_sandbox_validation",
)

MRO_WITHOUT_SAFETY_MIXIN = [
    "HardenedOrchestrator",
    "BudgetMixin",
    "GauntletMixin",
    "AuditMixin",
    "AutonomousOrchestrator",
    "AutonomousWorkflowMixin",
    "AutonomousFeedbackMixin",
    "AutonomousCoordinationMixin",
    "object",
]


@pytest.mark.parametrize("name", MOVED_METHODS)
def test_method_is_defined_on_the_safety_mixin(name: str) -> None:
    assert name in vars(SafetyMixin)
    assert name not in vars(HardenedOrchestrator)
    assert inspect.getattr_static(HardenedOrchestrator, name) is vars(SafetyMixin)[name]
    typing.get_type_hints(getattr(HardenedOrchestrator, name))


def test_safety_mixin_sits_after_the_existing_mixins() -> None:
    names = [cls.__name__ for cls in HardenedOrchestrator.__mro__]
    assert names.index("SafetyMixin") == names.index("AuditMixin") + 1
    names.remove("SafetyMixin")
    assert names == MRO_WITHOUT_SAFETY_MIXIN


def test_safety_mixin_defines_only_the_moved_methods_at_runtime() -> None:
    defined = {name for name, value in vars(SafetyMixin).items() if inspect.isfunction(value)}
    assert defined == set(MOVED_METHODS)


@pytest.mark.parametrize("name", MOVED_METHODS)
def test_no_other_class_in_the_mro_defines_a_moved_method(name: str) -> None:
    owners = [cls for cls in HardenedOrchestrator.__mro__ if name in vars(cls)]
    assert owners == [SafetyMixin]


def test_budget_outcome_recorder_still_wins() -> None:
    assert HardenedOrchestrator._record_agent_outcome is BudgetMixin._record_agent_outcome


def test_class_annotations_resolve_at_runtime() -> None:
    hints = typing.get_type_hints(HardenedOrchestrator)
    assert hints["_canary_token"] is str


def test_mixin_logs_under_the_orchestrator_logger() -> None:
    assert hardened_safety.logger is ho_module.logger


def test_new_module_scores_like_its_facade() -> None:
    def weight(path: str) -> float:
        result = RiskScorer().score_goal("Tidy helper names", file_scope=[path])
        return next(f.weight for f in result.factors if f.name == "file_scope")

    assert weight("aragora/nomic/hardened_safety.py") == pytest.approx(
        weight("aragora/nomic/hardened_orchestrator.py")
    )


def test_canary_round_trip_through_the_facade_class() -> None:
    orchestrator = HardenedOrchestrator.__new__(HardenedOrchestrator)
    orchestrator._canary_token = "CANARY-abc123"
    assert "CANARY-abc123" in orchestrator.get_canary_directive()
    assert orchestrator._check_canary_leak("output with CANARY-abc123 inside") is True
    assert orchestrator._check_canary_leak("clean output") is False
    orchestrator._canary_token = ""
    assert orchestrator.get_canary_directive() == ""
    assert orchestrator._check_canary_leak("CANARY-abc123") is False
