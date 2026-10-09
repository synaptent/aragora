"""``AutonomousOrchestrator`` workflow construction lives in ``autonomous_workflow``.

The four workflow-building methods are defined on ``AutonomousWorkflowMixin``
and reach ``AutonomousOrchestrator`` (and ``HardenedOrchestrator``) through
inheritance, so attribute lookups, ``super()`` calls and the static
``AutonomousOrchestrator._infer_test_paths`` call in ``branch_coordinator``
keep resolving to the same functions.
"""

from __future__ import annotations

import typing
from pathlib import Path

import pytest

from aragora.nomic import autonomous_orchestrator as ao_module
from aragora.nomic import autonomous_workflow
from aragora.nomic.agent_router import AgentRouter
from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator
from aragora.nomic.hardened_orchestrator import HardenedOrchestrator
from aragora.nomic.types import HierarchyConfig

MOVED_METHODS = (
    "_extract_hints",
    "_build_subtask_workflow",
    "_infer_test_paths",
    "_build_workflow_from_plan",
)


@pytest.mark.parametrize("name", MOVED_METHODS)
def test_method_is_defined_on_the_workflow_mixin(name: str) -> None:
    mixin = autonomous_workflow.AutonomousWorkflowMixin
    assert name in vars(mixin)
    assert name not in vars(AutonomousOrchestrator)
    assert getattr(AutonomousOrchestrator, name) is getattr(mixin, name)


def test_orchestrator_inherits_the_mixin() -> None:
    assert issubclass(AutonomousOrchestrator, autonomous_workflow.AutonomousWorkflowMixin)


def test_hardened_override_reaches_the_mixin_through_super() -> None:
    owners = [c for c in HardenedOrchestrator.__mro__ if "_build_subtask_workflow" in vars(c)]
    assert owners == [HardenedOrchestrator, autonomous_workflow.AutonomousWorkflowMixin]


def test_class_annotations_resolve_at_runtime() -> None:
    hints = typing.get_type_hints(AutonomousOrchestrator)
    assert hints["aragora_path"] is Path
    assert hints["router"] is AgentRouter
    assert typing.get_type_hints(HardenedOrchestrator)["hierarchy"] is HierarchyConfig


def test_mixin_logs_under_the_orchestrator_logger() -> None:
    assert autonomous_workflow.logger is ao_module.logger


def test_infer_test_paths_maps_sources_and_keeps_tests() -> None:
    assert AutonomousOrchestrator._infer_test_paths(
        [
            "aragora/nomic/meta_planner.py",
            "tests/nomic/test_x.py",
            "aragora/top_level.py",
            "docs/readme.md",
            "aragora/nomic/data.json",
        ]
    ) == ["tests/nomic/test_meta_planner.py", "tests/nomic/test_x.py"]


def test_extract_hints_flattens_strings_and_rich_hints() -> None:
    feedback = {
        "reason": "tests failed",
        "hints": [
            "check imports",
            {"file": "a.py", "line": 3, "error": "NameError", "suggestion": "import x"},
            {},
        ],
    }
    assert AutonomousOrchestrator._extract_hints(feedback) == [
        "tests failed",
        "check imports",
        "a.py: line 3: NameError: Fix: import x",
        "{}",
    ]
    assert AutonomousOrchestrator._extract_hints({"hints": "single"}) == ["single"]
