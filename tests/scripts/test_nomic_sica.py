"""Tests for SICA integration in scripts.nomic_loop."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest


def _import_nomic_loop_fresh(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # scripts.nomic_loop takes its NOMIC_SICA_* flags from scripts.nomic.config, which
    # reads the environment once at import time. Reloading nomic_loop alone keeps a
    # config module cached by an earlier test, so import both fresh; monkeypatch puts
    # the original modules and package attributes back at teardown.
    for name in ("scripts.nomic.config", "scripts.nomic_loop"):
        parent_name, _, child = name.rpartition(".")
        parent = importlib.import_module(parent_name)
        monkeypatch.setattr(parent, child, getattr(parent, child, None), raising=False)
        monkeypatch.delitem(sys.modules, name, raising=False)
    return importlib.import_module("scripts.nomic_loop")


@pytest.mark.asyncio
async def test_run_sica_cycle_parses_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NOMIC_SICA_ENABLED", "1")
    monkeypatch.setenv("NOMIC_SICA_IMPROVEMENT_TYPES", "reliability,readability")
    monkeypatch.setenv("NOMIC_SICA_GENERATOR_MODEL", "claude")
    monkeypatch.setenv("NOMIC_SICA_REQUIRE_APPROVAL", "0")
    monkeypatch.setenv("NOMIC_SICA_RUN_TESTS", "0")
    monkeypatch.setenv("NOMIC_SICA_RUN_TYPECHECK", "0")
    monkeypatch.setenv("NOMIC_SICA_RUN_LINT", "1")
    monkeypatch.setenv("NOMIC_SICA_TEST_COMMAND", "pytest -q")
    monkeypatch.setenv("NOMIC_SICA_TYPECHECK_COMMAND", "mypy .")
    monkeypatch.setenv("NOMIC_SICA_LINT_COMMAND", "ruff check")
    monkeypatch.setenv("NOMIC_SICA_VALIDATION_TIMEOUT", "123")
    monkeypatch.setenv("NOMIC_SICA_MAX_OPPORTUNITIES", "2")
    monkeypatch.setenv("NOMIC_SICA_MAX_ROLLBACKS", "1")

    nomic_loop = _import_nomic_loop_fresh(monkeypatch)

    captured: dict[str, object] = {}

    class DummyResult:
        patches_successful = 1

        def summary(self) -> str:
            return "ok"

        def to_dict(self) -> dict:
            return {"cycle_id": "dummy"}

    class DummyImprover:
        def __init__(self, repo_path, config, query_fn=None):
            captured["repo_path"] = repo_path
            captured["config"] = config
            captured["query_fn"] = query_fn

        async def run_improvement_cycle(self):
            return DummyResult()

    class DummyAgent:
        async def generate(self, prompt: str, context=None):
            return "ok"

    import aragora.nomic.sica_improver as sica_mod

    monkeypatch.setattr(sica_mod, "SICAImprover", DummyImprover)

    loop = object.__new__(nomic_loop.NomicLoop)
    loop.aragora_path = str(tmp_path)
    loop.codex = None
    loop.claude = DummyAgent()
    loop.gemini = None
    loop.grok = None
    loop._log = lambda *_args, **_kwargs: None
    result = await loop._run_sica_cycle()

    assert result["status"] == "success"

    config = captured["config"]
    assert [t.value for t in config.improvement_types] == ["reliability", "readability"]
    assert config.generator_model == "claude"
    assert config.require_human_approval is False
    assert config.run_tests is False
    assert config.run_typecheck is False
    assert config.run_lint is True
    assert config.test_command == "pytest -q"
    assert config.typecheck_command == "mypy ."
    assert config.lint_command == "ruff check"
    assert config.validation_timeout_seconds == 123
    assert config.max_opportunities_per_cycle == 2
    assert config.max_rollbacks_per_cycle == 1
