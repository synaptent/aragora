"""The agent lifecycle status enum lives in ``aragora.types.agent_status``.

``aragora.debate`` (team selection health scoring) reads it without importing the
control plane; ``aragora.control_plane.registry`` and ``aragora.control_plane`` re-export
the same enum.
"""

from __future__ import annotations

import ast
import importlib
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("old_path", ["aragora.control_plane.registry", "aragora.control_plane"])
def test_the_control_plane_paths_hold_the_same_enum(old_path):
    from aragora.types.agent_status import AgentStatus

    assert importlib.import_module(old_path).AgentStatus is AgentStatus


def test_the_enum_is_defined_in_the_types_package():
    from aragora.types.agent_status import AgentStatus

    assert AgentStatus.__module__ == "aragora.types.agent_status"


def test_the_member_values_are_unchanged():
    from aragora.types.agent_status import AgentStatus

    assert {member.name: member.value for member in AgentStatus} == {
        "STARTING": "starting",
        "READY": "ready",
        "BUSY": "busy",
        "DRAINING": "draining",
        "OFFLINE": "offline",
        "FAILED": "failed",
    }


def test_an_agent_record_built_with_the_types_enum_round_trips_through_the_registry_record():
    from aragora.control_plane.registry import AgentInfo
    from aragora.types.agent_status import AgentStatus

    info = AgentInfo(
        agent_id="a1",
        capabilities={"debate"},
        model="m",
        provider="p",
        status=AgentStatus.READY,
        last_heartbeat=time.time(),
    )
    restored = AgentInfo.from_dict(info.to_dict())

    assert restored.status is AgentStatus.READY
    assert restored.is_available()


def test_the_types_module_imports_nothing_from_aragora():
    tree = ast.parse((REPO_ROOT / "aragora/types/agent_status.py").read_text(encoding="utf-8"))
    imported = [
        name
        for node in ast.walk(tree)
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else []
        )
    ]
    assert [name for name in imported if name.startswith("aragora")] == []
