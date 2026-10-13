"""Layer-boundary and structural-ledger tests for ``aragora.evaluation``.

``aragora.evaluation`` sits below ``aragora.connectors`` and ``aragora.swarm``
in the import-linter layer contract, so no evaluation module may import either
package at any scope (including ``TYPE_CHECKING`` blocks). VIAH therefore
depends on the evaluation-owned ``ViahLedger`` / ``ViahLedgerEntry`` protocols;
these tests pin that real ``ShiftLedger`` instances still satisfy them and
produce exactly the same results as any other structurally compatible ledger.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import aragora.evaluation as evaluation_pkg
from aragora.evaluation.viah import (
    VIAH_SNAPSHOT_ENTRY_TYPE,
    VIAH_TREND_FLAG,
    ViahLedger,
    ViahLedgerEntry,
    compute_viah,
    persist_viah_snapshot,
    read_viah_snapshots,
    rolling_viah_trend,
)
from aragora.evaluation.viah_status import generate_viah_status_report
from aragora.swarm.shift_ledger import LedgerEntry, ShiftLedger

_FORBIDDEN_PACKAGES = ("aragora.connectors", "aragora.swarm")
_REF = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
            if node.module == "aragora":
                found.extend((node.lineno, f"aragora.{alias.name}") for alias in node.names)
    return found


def _is_forbidden(module: str) -> bool:
    return any(module == pkg or module.startswith(f"{pkg}.") for pkg in _FORBIDDEN_PACKAGES)


def test_evaluation_package_never_imports_connectors_or_swarm() -> None:
    package_dir = Path(evaluation_pkg.__file__).parent
    offenders: list[str] = []
    for source in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for lineno, module in _imported_modules(tree):
            if _is_forbidden(module):
                offenders.append(
                    f"{source.relative_to(package_dir.parent.parent)}:{lineno} {module}"
                )
    assert offenders == []


class _InMemoryEntry:
    def __init__(self, entry_type: str, timestamp: str, payload: dict[str, Any]) -> None:
        self.entry_type = entry_type
        self.timestamp = timestamp
        self.payload = payload


class _InMemoryLedger:
    """Ledger that satisfies ``ViahLedger`` without touching ``aragora.swarm``."""

    def __init__(self, entries: list[_InMemoryEntry], path: Path) -> None:
        self._entries = list(entries)
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def read_all(self) -> list[_InMemoryEntry]:
        return list(self._entries)

    def read_by_type(self, entry_type: str) -> list[_InMemoryEntry]:
        return [e for e in self._entries if e.entry_type == entry_type]

    def append(self, entry_type: str, **payload: Any) -> _InMemoryEntry:
        entry = _InMemoryEntry(entry_type, _REF.strftime("%Y-%m-%dT%H:%M:%SZ"), dict(payload))
        self._entries.append(entry)
        return entry


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for week in range(3):
        start = _REF - timedelta(days=7 * week + 2)
        rows.append(
            {
                "entry_type": "shift_start",
                "timestamp": _iso(start),
                "payload": {"shift_id": f"s{week}"},
            }
        )
        for pr in range(week + 1):
            rows.append(
                {
                    "entry_type": "pr_merged",
                    "timestamp": _iso(start + timedelta(hours=1 + pr)),
                    "payload": {"pr_number": 100 * week + pr},
                }
            )
        rows.append(
            {
                "entry_type": "cycle_tick",
                "timestamp": _iso(start + timedelta(hours=4)),
                "payload": {"rescue_count": week},
            }
        )
        rows.append(
            {
                "entry_type": "shift_stop",
                "timestamp": _iso(start + timedelta(hours=6)),
                "payload": {"shift_id": f"s{week}", "reason": "completed"},
            }
        )
    return rows


@pytest.fixture()
def shift_ledger(tmp_path: Path) -> ShiftLedger:
    path = tmp_path / "shift_ledger.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in _seed_rows()), encoding="utf-8")
    return ShiftLedger(path=path)


@pytest.fixture()
def memory_ledger(tmp_path: Path) -> _InMemoryLedger:
    entries = [_InMemoryEntry(r["entry_type"], r["timestamp"], r["payload"]) for r in _seed_rows()]
    return _InMemoryLedger(entries, tmp_path / "memory_ledger.jsonl")


@pytest.fixture()
def trend_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VIAH_TREND_FLAG, "1")


def test_shift_ledger_satisfies_viah_protocols(shift_ledger: ShiftLedger) -> None:
    assert isinstance(shift_ledger, ViahLedger)
    entries = shift_ledger.read_all()
    assert entries
    assert all(isinstance(entry, ViahLedgerEntry) for entry in entries)


def test_in_memory_ledger_satisfies_viah_protocols(memory_ledger: _InMemoryLedger) -> None:
    assert isinstance(memory_ledger, ViahLedger)
    assert all(isinstance(entry, ViahLedgerEntry) for entry in memory_ledger.read_all())


def test_compute_viah_matches_between_shift_and_structural_ledgers(
    shift_ledger: ShiftLedger, memory_ledger: _InMemoryLedger
) -> None:
    real = compute_viah(ledger=shift_ledger, now=_REF).to_dict()
    structural = compute_viah(ledger=memory_ledger, now=_REF).to_dict()

    assert real["inputs"].pop("ledger_path") == str(shift_ledger.path)
    assert structural["inputs"].pop("ledger_path") == str(memory_ledger.path)
    assert real == structural
    assert real["merged_autonomous_prs"] == 1
    assert real["rescues_required"] == 0
    assert real["agent_hours"] == pytest.approx(6.0)


@pytest.mark.usefixtures("trend_enabled")
def test_trend_and_status_report_match_between_ledgers(
    shift_ledger: ShiftLedger, memory_ledger: _InMemoryLedger
) -> None:
    real_trend = rolling_viah_trend(ledger=shift_ledger, weeks=3, now=_REF)
    structural_trend = rolling_viah_trend(ledger=memory_ledger, weeks=3, now=_REF)
    assert real_trend.to_dict() == structural_trend.to_dict()
    assert [p.merged_autonomous_prs for p in real_trend.points] == [3, 2, 1]

    real_report = generate_viah_status_report(shift_ledger, weeks=3, now=_REF)
    assert real_report == generate_viah_status_report(memory_ledger, weeks=3, now=_REF)
    assert "# VIAH Status" in real_report


@pytest.mark.usefixtures("trend_enabled")
def test_persist_returns_the_ledger_append_result(
    shift_ledger: ShiftLedger, memory_ledger: _InMemoryLedger
) -> None:
    report = compute_viah(ledger=shift_ledger, now=_REF)

    persisted = persist_viah_snapshot(ledger=shift_ledger, report=report)
    assert type(persisted) is LedgerEntry
    assert persisted.entry_type == VIAH_SNAPSHOT_ENTRY_TYPE
    assert shift_ledger.read_by_type(VIAH_SNAPSHOT_ENTRY_TYPE)[-1].to_dict() == persisted.to_dict()

    structural = persist_viah_snapshot(ledger=memory_ledger, report=report)
    assert memory_ledger.read_all()[-1] is structural
    assert structural.payload == persisted.payload

    assert read_viah_snapshots(ledger=shift_ledger) == read_viah_snapshots(ledger=memory_ledger)
    assert read_viah_snapshots(ledger=shift_ledger) == [persisted.payload]
