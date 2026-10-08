"""CLI exit semantics for scripts/work_mix_gate.py (#9048 openai [P2])."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "work_mix_gate.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("work_mix_gate_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeLedger:
    def __init__(self, root):
        self.root = root

    def records(self):
        return []


def _force_budget_breach(mod, monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "ThroughputLedger", _FakeLedger)
    monkeypatch.setattr(
        mod,
        "mix_from_records",
        lambda records, *, window_days: SimpleNamespace(
            total=3,
            product_share=0.2,
            substrate_share=0.8,
        ),
    )
    monkeypatch.setattr(
        mod,
        "evaluate_budget",
        lambda mix, budget: SimpleNamespace(
            ok=False,
            substrate_breach=True,
            product_shortfall=True,
            freeze_recommended=True,
            reasons=["substrate over budget"],
        ),
    )
    writes = []
    monkeypatch.setattr(
        mod,
        "write_freeze_marker",
        lambda repo_root, *, reason: writes.append((repo_root, reason)) or tmp_path / "marker",
    )
    return writes


def test_check_is_advisory_by_default_even_on_budget_breach(mod, monkeypatch, tmp_path):
    writes = _force_budget_breach(mod, monkeypatch, tmp_path)

    rc = mod.main(["--repo-root", str(tmp_path), "check"])

    assert rc == 0
    assert writes == []


def test_check_enforce_returns_nonzero_and_writes_marker_on_budget_breach(
    mod, monkeypatch, tmp_path
):
    writes = _force_budget_breach(mod, monkeypatch, tmp_path)

    rc = mod.main(["--repo-root", str(tmp_path), "check", "--enforce"])

    assert rc == 1
    assert writes == [(str(tmp_path), "substrate over budget")]
