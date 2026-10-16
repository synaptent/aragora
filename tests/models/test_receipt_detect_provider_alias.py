"""``aragora.gauntlet.receipt_models._detect_provider`` after the detector moved to the agents package.

#10594 moved the gauntlet facade's private provider detector to
``aragora.agents.receipt_hooks.detect_provider``. The facade path resolves to the
foundation module :mod:`aragora.models.receipts.gauntlet`, which serves the old
name from the detector registered through :mod:`aragora.models.receipts.operations`
instead of importing the agents package.
"""

from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aragora.agents import receipt_hooks
from aragora.models.receipts import gauntlet, operations


@pytest.fixture
def no_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    """No receipt operation adapter is registered, as before any facade import."""
    monkeypatch.setattr(operations, "_adapters", {})


def test_old_facade_path_is_the_registered_agents_detector() -> None:
    receipt_models = importlib.import_module("aragora.gauntlet.receipt_models")
    receipt_hooks.register_receipt_agent_hooks()

    assert receipt_models is gauntlet
    assert hasattr(receipt_models, "_detect_provider")
    assert receipt_models._detect_provider is receipt_hooks.detect_provider
    from aragora.gauntlet.receipt_models import _detect_provider

    assert _detect_provider is receipt_hooks.detect_provider
    assert _detect_provider("gpt-4") == receipt_hooks.detect_provider("gpt-4")


def test_alias_follows_whichever_detector_is_registered(no_adapters: None) -> None:
    def detector(model: str) -> str:
        return "stub"

    operations.register_provider_detector(detector)

    assert getattr(gauntlet, "_detect_provider", None) is detector


def test_unregistered_detector_reads_as_a_missing_attribute(no_adapters: None) -> None:
    assert not hasattr(gauntlet, "_detect_provider")
    with pytest.raises(AttributeError, match="no adapter registered") as excinfo:
        gauntlet._detect_provider  # noqa: B018
    assert isinstance(excinfo.value.__cause__, operations.ReceiptOperationNotRegisteredError)
    with pytest.raises(AttributeError, match="no_such_receipt_helper"):
        gauntlet.no_such_receipt_helper  # noqa: B018


@pytest.mark.parametrize("module", [gauntlet, operations], ids=lambda m: m.__name__)
def test_foundation_modules_never_import_the_agents_package(module: object) -> None:
    tree = ast.parse(Path(str(getattr(module, "__file__"))).read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not [name for name in imported if name and name.split(".")[:2] == ["aragora", "agents"]]


def test_fresh_interpreter_resolves_the_alias_without_loading_upper_layers() -> None:
    code = """
import importlib, sys
import aragora.models.receipts.gauntlet as G
from aragora.models.receipts import operations as OP
upper = ("aragora.agents", "aragora.debate", "aragora.gauntlet", "aragora.receipts", "aragora.export")
assert not hasattr(G, "_detect_provider")
def stub(model):
    return "stub"
OP.register_provider_detector(stub)
assert getattr(G, "_detect_provider", None) is stub
loaded = sorted(m for m in sys.modules if m.startswith(upper))
assert not loaded, loaded
facade = importlib.import_module("aragora.gauntlet.receipt_models")
from aragora.agents.receipt_hooks import detect_provider
assert facade is G and facade._detect_provider is detect_provider
print("ok")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=dict(os.environ),
        cwd=Path(operations.__file__).resolve().parents[3],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "ok"
