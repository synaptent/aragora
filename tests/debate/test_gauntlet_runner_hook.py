"""The post-debate coordinator reaches the gauntlet through ``aragora.debate.gauntlet_runners``.

``aragora.debate`` (domain layer) must not import ``aragora.gauntlet`` (application layer),
whose ``GauntletRunner`` stress-tests a decision. The gauntlet package registers that runner
through the ``aragora.debate_gauntlet_runners`` entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from aragora.debate import gauntlet_runners as hook
from aragora.debate.post_debate_coordinator import PostDebateConfig, PostDebateCoordinator
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
GAUNTLET_REGISTRATION = (
    "gauntlet",
    "aragora.gauntlet.debate_registration:register_debate_gauntlet_runner",
)


class RecordingRunner:
    def __init__(self, verdict=None, error=None):
        self.calls = []
        self._verdict, self._error = verdict, error

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._verdict


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(hook, "_factory", None)
    monkeypatch.setattr(
        hook,
        "_declared",
        DeclaredRegistrations(
            hook.GAUNTLET_RUNNERS_ENTRY_POINT_GROUP, source_pyproject=tmp_path / "missing.toml"
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return hook


def _validate(coordinator=None):
    coordinator = coordinator or PostDebateCoordinator(
        config=PostDebateConfig(auto_gauntlet_validate=True)
    )
    result = SimpleNamespace(final_answer="Ship it")
    return coordinator._step_gauntlet_validate("d1", result, "the task", 0.9)


def test_an_unregistered_runner_raises(isolated_hook):
    with pytest.raises(hook.GauntletRunnerNotRegisteredError, match="aragora.debate_gauntlet"):
        hook.create_gauntlet_runner()


def test_without_a_runner_the_step_returns_nothing(isolated_hook):
    assert _validate() is None


def test_the_step_runs_a_new_registered_runner_on_the_decision(isolated_hook):
    runners = []

    def factory():
        runners.append(RecordingRunner(verdict="passed"))
        return runners[-1]

    hook.register_gauntlet_runner_factory(factory)
    assert _validate() == {"debate_id": "d1", "verdict": "passed"}
    assert _validate() == {"debate_id": "d1", "verdict": "passed"}
    assert [runner.calls for runner in runners] == [
        [{"input_content": "Ship it", "context": "the task"}],
        [{"input_content": "Ship it", "context": "the task"}],
    ]


def test_a_failing_runner_returns_nothing(isolated_hook):
    hook.register_gauntlet_runner_factory(lambda: RecordingRunner(error=RuntimeError("boom")))
    assert _validate() is None


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        hook.register_gauntlet_runner_factory(object)

    entry_point = SimpleNamespace(name="g0", value="tests.declared:g0", load=lambda: register)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: [entry_point] if group == hook.GAUNTLET_RUNNERS_ENTRY_POINT_GROUP else [],
    )
    assert hook.create_gauntlet_runner() is not hook.create_gauntlet_runner()
    assert calls == ["register"]


def test_pyproject_declares_the_gauntlet_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(hook.GAUNTLET_RUNNERS_ENTRY_POINT_GROUP)._source_declarations()
    assert [(ep.name, ep.value) for ep in declared] == [GAUNTLET_REGISTRATION]


def test_the_registration_reads_the_runner_class_at_call_time(isolated_hook, monkeypatch):
    from aragora.gauntlet import runner
    from aragora.gauntlet.debate_registration import register_debate_gauntlet_runner

    register_debate_gauntlet_runner()
    register_debate_gauntlet_runner()
    assert type(hook.create_gauntlet_runner()) is runner.GauntletRunner
    monkeypatch.setattr(runner, "GauntletRunner", RecordingRunner)
    assert type(hook.create_gauntlet_runner()) is RecordingRunner


def test_a_debate_only_process_reaches_the_gauntlet_runner():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "from aragora.debate.gauntlet_runners import create_gauntlet_runner\n"
        "import aragora.debate.post_debate_coordinator\n"
        "runner = create_gauntlet_runner()\n"
        "print(type(runner).__module__, type(runner).__name__)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-2:] == ["aragora.gauntlet.runner", "GauntletRunner"]


def test_debate_holds_no_import_of_gauntlet_at_any_scope():
    offenders = []
    for path in sorted((REPO_ROOT / "aragora" / "debate").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            offenders += [
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {name}"
                for name in names
                if name == "aragora.gauntlet" or name.startswith("aragora.gauntlet.")
            ]
    assert offenders == []
