"""The control-plane task status and priority enums live in ``aragora.types``.

``aragora.agents`` and ``aragora.knowledge`` build and read these values when they hand
work to the control-plane scheduler, and must not import ``aragora.control_plane``
(application layer) to do so. The scheduler and the control-plane package re-export
the same enum objects from :mod:`aragora.types.task_scheduling`.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from aragora.types import task_scheduling

REPO_ROOT = Path(__file__).resolve().parents[2]
OLD_PATHS = ("aragora.control_plane.scheduler", "aragora.control_plane")


@pytest.mark.parametrize("old_path", OLD_PATHS)
@pytest.mark.parametrize("name", task_scheduling.__all__)
def test_the_control_plane_paths_hold_the_same_enums(old_path, name):
    assert getattr(importlib.import_module(old_path), name) is getattr(task_scheduling, name)


@pytest.mark.parametrize("name", task_scheduling.__all__)
def test_the_enums_are_defined_in_the_types_package(name):
    assert getattr(task_scheduling, name).__module__ == "aragora.types.task_scheduling"


def test_the_member_values_are_unchanged():
    assert {m.name: m.value for m in task_scheduling.TaskStatus} == {
        "PENDING": "pending",
        "ASSIGNED": "assigned",
        "RUNNING": "running",
        "COMPLETED": "completed",
        "FAILED": "failed",
        "CANCELLED": "cancelled",
        "TIMEOUT": "timeout",
    }
    assert {m.name: m.value for m in task_scheduling.TaskPriority} == {
        "LOW": 0,
        "NORMAL": 50,
        "HIGH": 75,
        "URGENT": 100,
    }


def test_a_task_built_with_the_types_enums_round_trips_through_the_scheduler_record():
    from aragora.control_plane.scheduler import Task

    task = Task(
        task_type="knowledge_revalidation",
        payload={"node_id": "n1"},
        priority=task_scheduling.TaskPriority.HIGH,
        status=task_scheduling.TaskStatus.ASSIGNED,
    )
    record = task.to_dict()
    assert (record["priority"], record["status"]) == (75, "assigned")

    restored = Task.from_dict(record)
    assert restored.priority is task_scheduling.TaskPriority.HIGH
    assert restored.status is task_scheduling.TaskStatus.ASSIGNED


def test_the_types_module_imports_nothing_from_aragora():
    tree = ast.parse((REPO_ROOT / "aragora/types/task_scheduling.py").read_text(encoding="utf-8"))
    imported = [
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert [name for name in imported if name.startswith("aragora")] == []
