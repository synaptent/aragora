"""The feedback phase and debate extensions reach broadcast and task events without upper imports.

``aragora.debate`` (domain layer) must not import ``aragora.broadcast`` or
``aragora.control_plane`` (application layer). The feedback phase hands the broadcast
pipeline no options, so the pipeline applies its own defaults, which are the options the
phase used to build; the debate extensions emit task events through
``aragora.events.task_events``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKED_FILES = ("aragora/debate/phases/feedback_phase.py", "aragora/debate/extensions.py")
UPPER_PACKAGES = ("aragora.broadcast", "aragora.control_plane")


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
