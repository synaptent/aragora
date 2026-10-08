"""Tests for SICA integration in scripts.nomic_loop."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator, MutableMapping
from types import ModuleType
from typing import Any

import pytest


def _put_back(mapping: MutableMapping[str, Any], key: str, value: ModuleType | None) -> None:
    if value is None:
        mapping.pop(key, None)
    else:
        mapping[key] = value


@pytest.fixture
def fresh_nomic_modules() -> Iterator[None]:
    """Make the test import scripts.nomic.config and scripts.nomic_loop under its own env.

    scripts.nomic_loop takes its NOMIC_SICA_* flags from scripts.nomic.config, which
    reads the environment once at import time, so a config module cached by an earlier
    test would win over the env the test sets. Both modules are dropped before the test
    body runs; afterwards the previous modules and package attributes are put back, or
    removed again when they had not been imported before.
    """
    saved = []
    for name in ("scripts.nomic.config", "scripts.nomic_loop"):
        parent_name, _, child = name.rpartition(".")
        parent = importlib.import_module(parent_name)
        saved.append((name, parent, child, sys.modules.pop(name, None), vars(parent).get(child)))
    yield
    for name, parent, child, module, attribute in saved:
        _put_back(sys.modules, name, module)
        _put_back(vars(parent), child, attribute)


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_nomic_modules")
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

    import scripts.nomic_loop as nomic_loop

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
