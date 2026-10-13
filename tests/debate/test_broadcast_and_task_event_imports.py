"""The feedback phase and debate extensions reach broadcast and task events without upper imports.

``aragora.debate`` (domain layer) must not import ``aragora.broadcast`` or
``aragora.control_plane`` (application layer). The feedback phase hands the broadcast
pipeline no options, so the pipeline applies its own defaults, which are the options the
phase used to build; the debate extensions emit task events through
``aragora.events.task_events``. Without a configured dispatcher they still fall back to the
control plane's default dispatcher, which the control plane registers through the
``aragora.task_event_dispatchers`` entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKED_FILES = ("aragora/debate/phases/feedback_phase.py", "aragora/debate/extensions.py")
UPPER_PACKAGES = ("aragora.broadcast", "aragora.control_plane")
CONTROL_PLANE_DISPATCHER_REGISTRATION = (
    "control_plane",
    "aragora.control_plane.event_registry:register_task_event_dispatcher",
)


def test_the_pipeline_defaults_equal_the_options_the_phase_used_to_build():
    from aragora.broadcast.pipeline import BroadcastOptions

    assert BroadcastOptions() == BroadcastOptions(audio_enabled=True, generate_rss_episode=True)


@pytest.mark.asyncio
async def test_the_feedback_phase_runs_the_pipeline_with_its_default_options():
    from aragora.debate.phases.feedback_phase import FeedbackPhase

    pipeline = SimpleNamespace(
        run=AsyncMock(return_value=SimpleNamespace(success=True, audio_path="/tmp/a.mp3"))
    )
    phase = FeedbackPhase(broadcast_pipeline=pipeline, auto_broadcast=True)

    await phase._broadcast_async(SimpleNamespace(debate_id="debate-1"))

    pipeline.run.assert_awaited_once_with("debate-1")


def _imported_names(path: Path) -> list[tuple[int, str]]:
    names: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.append((node.lineno, node.module or ""))
        elif isinstance(node, ast.Call) and node.args:
            callee = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            first = node.args[0]
            if callee in {"import_module", "__import__"} and isinstance(first, ast.Constant):
                names.append((node.lineno, str(first.value)))
    return names


@pytest.mark.parametrize("relative", CHECKED_FILES)
def test_the_file_holds_no_import_of_broadcast_or_the_control_plane(relative):
    offenders = [
        f"{relative}:{lineno}: {name}"
        for lineno, name in _imported_names(REPO_ROOT / relative)
        if any(name == pkg or name.startswith(pkg + ".") for pkg in UPPER_PACKAGES)
    ]
    assert offenders == []


@pytest.fixture
def isolated_task_events(monkeypatch, tmp_path):
    """Task events with no dispatcher, no provider and declared registrations from a test only."""
    from aragora.events import task_events

    monkeypatch.setattr(task_events, "_dispatcher", None)
    monkeypatch.setattr(task_events, "_default_dispatcher_provider", None)
    monkeypatch.setattr(
        task_events,
        "_declared_registrations",
        DeclaredRegistrations(
            task_events.TASK_EVENT_DISPATCHERS_ENTRY_POINT_GROUP,
            source_pyproject=tmp_path / "missing.toml",
        ),
    )
    return task_events


def test_loading_the_declared_dispatchers_runs_them_once(isolated_task_events, monkeypatch):
    task_events = isolated_task_events
    calls = []

    def register():
        calls.append("register")
        task_events.register_default_task_event_dispatcher_provider(lambda: None)

    declared = [SimpleNamespace(name="d0", value="tests.declared:d0", load=lambda: register)]
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: (
            declared if group == task_events.TASK_EVENT_DISPATCHERS_ENTRY_POINT_GROUP else []
        ),
    )

    assert task_events.registered_count() == 0
    assert task_events.load_declared_task_event_dispatcher_providers() == 1
    assert task_events.load_declared_task_event_dispatcher_providers() == 1
    assert calls == ["register"]


def test_pyproject_declares_the_control_plane_task_event_dispatcher():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    from aragora.events import task_events

    declared = DeclaredRegistrations(
        task_events.TASK_EVENT_DISPATCHERS_ENTRY_POINT_GROUP
    )._source_declarations()
    assert [(ep.name, ep.value) for ep in declared] == [CONTROL_PLANE_DISPATCHER_REGISTRATION]


def test_a_configured_dispatcher_skips_the_declared_registrations(isolated_task_events):
    from aragora.debate.extensions import ArenaExtensions

    extensions = ArenaExtensions(
        auto_notify=True, notify_min_confidence=0.0, notification_dispatcher=SimpleNamespace()
    )
    extensions._emit_debate_notifications(
        SimpleNamespace(debate_id="debate-1", metadata={}),
        SimpleNamespace(consensus_confidence=0.5, winner="a", consensus_reached=False),
    )

    assert not isolated_task_events._declared_registrations.loaded


def test_a_debate_only_process_falls_back_to_the_control_plane_dispatcher():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "import sys\n"
        "from types import SimpleNamespace\n"
        "from aragora.debate.extensions import ArenaExtensions\n"
        "from aragora.events import task_events\n"
        "assert not any(m.startswith('aragora.control_plane') for m in sys.modules), 'preloaded'\n"
        "ArenaExtensions(auto_notify=True, notify_min_confidence=0.0)._emit_debate_notifications(\n"
        "    SimpleNamespace(debate_id='debate-1', metadata={}),\n"
        "    SimpleNamespace(consensus_confidence=0.5, winner='a', consensus_reached=False),\n"
        ")\n"
        "registered = task_events.registered_count()\n"
        "from aragora.control_plane import event_registry, notifications\n"
        "sentinel = object()\n"
        "notifications.set_default_notification_dispatcher(sentinel)\n"
        "print(registered,\n"
        "      task_events._default_dispatcher_provider is event_registry.default_task_event_dispatcher,\n"
        "      task_events.get_task_event_dispatcher() is sentinel)\n"
    )
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.split()[-3:] == ["1", "True", "True"]
