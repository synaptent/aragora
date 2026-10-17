"""Debate prompts read operational-mode system prompts through ``aragora.debate.mode_prompts``.

``aragora.debate`` (domain layer) must not import ``aragora.modes`` (application layer) at
runtime. ``aragora.cli.mode_prompt_registration`` registers the mode registry through the
``aragora.debate_mode_prompts`` entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aragora.debate import mode_prompts as hook
from aragora.debate.prompt_builder import PromptBuilder
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
MODES_REGISTRATION = ("modes", "aragora.cli.mode_prompt_registration:register_mode_prompts")


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(hook, "_provider", None)
    monkeypatch.setattr(
        hook,
        "_declared",
        DeclaredRegistrations(
            hook.MODE_PROMPTS_ENTRY_POINT_GROUP, source_pyproject=tmp_path / "missing.toml"
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return hook


def _builder(mode_name):
    protocol = MagicMock()
    protocol.rounds = 3
    protocol.stances = None
    protocol.asymmetric_stances = False
    protocol.agreement_intensity = None
    protocol.enable_privacy_anonymization = False
    protocol.cognitive_phases = None
    protocol.enforce_language = False
    protocol.language = "english"
    builder = PromptBuilder(protocol=protocol, env=SimpleNamespace(task="t", context=""))
    builder._active_mode_name = mode_name
    return builder


def test_an_unregistered_provider_raises(isolated_hook):
    with pytest.raises(hook.ModePromptProviderNotRegisteredError, match="aragora.debate_mode"):
        hook.mode_system_prompt("architect")


def test_without_a_provider_the_prompt_builder_adds_no_mode_prompt(isolated_hook):
    assert _builder("architect").get_mode_prompt() == ""


def test_the_prompt_builder_asks_the_provider_for_the_active_mode(isolated_hook):
    asked = []

    def provider(name):
        asked.append(name)
        return {"architect": "You are the architect."}.get(name)

    hook.register_mode_prompt_provider(provider)
    assert _builder("architect").get_mode_prompt() == "You are the architect."
    assert _builder("unknown").get_mode_prompt() == ""
    assert _builder(None).get_mode_prompt() == ""
    assert asked == ["architect", "unknown"]


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        hook.register_mode_prompt_provider(lambda name: f"prompt:{name}")

    entry_point = SimpleNamespace(name="m0", value="tests.declared:m0", load=lambda: register)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: [entry_point] if group == hook.MODE_PROMPTS_ENTRY_POINT_GROUP else [],
    )
    assert hook.mode_system_prompt("a") == "prompt:a"
    assert hook.mode_system_prompt("b") == "prompt:b"
    assert calls == ["register"]


def test_pyproject_declares_the_modes_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(hook.MODE_PROMPTS_ENTRY_POINT_GROUP)
    assert [(ep.name, ep.value) for ep in declared._source_declarations()] == [MODES_REGISTRATION]


def test_the_registered_provider_reads_the_mode_registry_at_call_time(isolated_hook, monkeypatch):
    from aragora.cli.mode_prompt_registration import register_mode_prompts
    from aragora.modes.base import ModeRegistry

    register_mode_prompts()
    mode = SimpleNamespace(name="probe", get_system_prompt=lambda: "Probe Mode prompt")
    monkeypatch.setitem(ModeRegistry._modes, "probe", mode)
    assert hook.mode_system_prompt("Probe") == "Probe Mode prompt"
    assert hook.mode_system_prompt("no-such-mode") is None


def test_a_debate_only_process_gets_the_builtin_mode_prompts():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "from aragora.debate.mode_prompts import mode_system_prompt\n"
        "print('Architect Mode' in (mode_system_prompt('architect') or ''))\n"
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
    assert result.stdout.split()[-1] == "True"


def _runtime_imports(tree):
    """Absolute imports outside ``if TYPE_CHECKING:`` blocks."""
    type_only = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            type_only.update(id(child) for stmt in node.body for child in ast.walk(stmt))
    for node in ast.walk(tree):
        if id(node) in type_only:
            continue
        if isinstance(node, ast.Import):
            yield from ((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module


def test_debate_holds_no_runtime_import_of_modes():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "debate").rglob("*.py"))
        for line, name in _runtime_imports(ast.parse(path.read_text(encoding="utf-8")))
        if name == "aragora.modes" or name.startswith("aragora.modes.")
    ]
    assert offenders == []
