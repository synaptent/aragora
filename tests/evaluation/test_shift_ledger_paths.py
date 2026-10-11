"""Old and new import paths of the shift ledger share one implementation."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import aragora.evaluation.shift_ledger as new
import aragora.swarm.shift_ledger as old

REPO_ROOT = Path(__file__).resolve().parents[2]

PUBLIC_NAMES = (
    "DEFAULT_LEDGER_PATH",
    "FAILURE_THRESHOLDS",
    "GREEN_SHIFT_REQUIRED_HOURS",
    "HEALTHY_STOP_PREFIXES",
    "LedgerEntry",
    "ShiftLedger",
)


@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_old_path_reexports_identical_object(name: str) -> None:
    assert getattr(old, name) is getattr(new, name)


def test_old_path_all_matches_public_names() -> None:
    assert sorted(old.__all__) == sorted(PUBLIC_NAMES)


def test_implementation_lives_in_evaluation() -> None:
    module = inspect.getmodule(old.ShiftLedger)
    assert module is not None
    assert module.__name__ == "aragora.evaluation.shift_ledger"
    assert old.DEFAULT_LEDGER_PATH == ".aragora/proof_first_shift/shift_ledger.jsonl"
    assert old.GREEN_SHIFT_REQUIRED_HOURS == 12.0


def test_entry_written_via_old_path_reads_via_new_path(tmp_path: Path) -> None:
    ledger_path = tmp_path / "shift_ledger.jsonl"
    old.ShiftLedger(path=ledger_path).record_shift_start(
        shift_id="shift-1", max_hours=4.0, benchmark_mode="off", queue_size=3
    )
    entries = new.ShiftLedger(path=str(ledger_path)).read_by_type("shift_start")
    assert len(entries) == 1
    assert isinstance(entries[0], old.LedgerEntry)
    assert entries[0].payload == {
        "shift_id": "shift-1",
        "max_hours": 4.0,
        "benchmark_mode": "off",
        "queue_size": 3,
    }


def test_ledger_entry_round_trip_is_path_independent() -> None:
    data = {"entry_type": "cycle_tick", "timestamp": "2026-10-04T00:00:00Z", "payload": {"n": 1}}
    assert old.LedgerEntry.from_dict(data) == new.LedgerEntry.from_dict(data)
    assert new.LedgerEntry.from_dict(data).to_dict() == data


def test_moved_module_has_no_aragora_imports() -> None:
    path = REPO_ROOT / "aragora/evaluation/shift_ledger.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
    ]
    assert [name for name in imported if name.startswith("aragora")] == []
