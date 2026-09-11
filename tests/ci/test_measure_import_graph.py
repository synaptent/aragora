"""Unit tests for scripts/ci/measure_import_graph.py.

The metric functions are exercised against a tiny in-memory grimp graph and the
``--check``/``--freeze`` ratchet logic against monkeypatched measurements, so the
tests are fast and never build the real ~4,100-module graph. End-to-end behavior
against the real ``aragora`` package (three extractable integers, handlers
cross-check, anchors) is covered by the VAL-P0-007 acceptance check.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

grimp = pytest.importorskip("grimp")

REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOL_PATH = REPO_ROOT / "scripts" / "ci" / "measure_import_graph.py"

_spec = importlib.util.spec_from_file_location("measure_import_graph", _TOOL_PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def _synthetic_graph() -> "grimp.ImportGraph":
    """a<->b is a mutual cycle; a and c.sub import the server subtree."""
    graph = grimp.ImportGraph()
    for module in (
        "aragora",
        "aragora.a",
        "aragora.b",
        "aragora.c",
        "aragora.c.sub",
        "aragora.server",
        "aragora.server.x",
    ):
        graph.add_module(module)
    graph.add_import(importer="aragora.a", imported="aragora.b")
    graph.add_import(importer="aragora.b", imported="aragora.a")  # mutual cycle
    graph.add_import(importer="aragora.a", imported="aragora.server.x")
    graph.add_import(importer="aragora.c.sub", imported="aragora.server")
    return graph


# --- pure metric functions --------------------------------------------------


def test_count_mutual_cycles():
    assert mig.count_mutual_cycles(_synthetic_graph()) == 1


def test_count_server_imported_by_counts_distinct_top_level_outside_server():
    # importers of the server subtree: aragora.a and aragora.c.sub -> tops {a, c}
    assert mig.count_server_imported_by(_synthetic_graph()) == 2


def test_count_handlers_flat_root_is_non_recursive(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("x = 2\n", encoding="utf-8")
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "notpy.txt").write_text("nope\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.py").write_text("x = 3\n", encoding="utf-8")  # nested: must NOT count
    assert mig.count_handlers_flat_root(tmp_path) == 3


def test_evaluate_cycle_growth():
    assert mig.evaluate_cycle_growth(141, 140) is True
    assert mig.evaluate_cycle_growth(140, 140) is False
    assert mig.evaluate_cycle_growth(139, 140) is False


# --- CLI: --check ratchet ---------------------------------------------------


def test_check_exits_nonzero_on_plus_one_growth(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mig, "build_aragora_graph", lambda *a, **k: _synthetic_graph())
    baseline = tmp_path / "cyc.json"
    baseline.write_text(json.dumps({"value": 0}), encoding="utf-8")  # current=1 -> +1 growth
    assert mig.main(["--check", "--baseline", str(baseline)]) == 1
    assert "grew" in capsys.readouterr().out


def test_check_ok_when_not_grown(tmp_path, monkeypatch):
    monkeypatch.setattr(mig, "build_aragora_graph", lambda *a, **k: _synthetic_graph())
    baseline = tmp_path / "cyc.json"
    baseline.write_text(json.dumps({"value": 1}), encoding="utf-8")  # current=1 == baseline
    assert mig.main(["--check", "--baseline", str(baseline)]) == 0


def test_check_ok_when_cycles_shrank(tmp_path, monkeypatch):
    monkeypatch.setattr(mig, "build_aragora_graph", lambda *a, **k: _synthetic_graph())
    baseline = tmp_path / "cyc.json"
    baseline.write_text(json.dumps({"value": 9}), encoding="utf-8")  # current=1 < baseline
    assert mig.main(["--check", "--baseline", str(baseline)]) == 0


def test_check_missing_baseline_is_usage_error(tmp_path, monkeypatch):
    monkeypatch.setattr(mig, "build_aragora_graph", lambda *a, **k: _synthetic_graph())
    assert mig.main(["--check", "--baseline", str(tmp_path / "nope.json")]) == 2


# --- CLI: --freeze (shrink-only) -------------------------------------------


def test_freeze_refuses_to_raise_without_adopt(tmp_path, monkeypatch):
    monkeypatch.setattr(mig, "build_aragora_graph", lambda *a, **k: _synthetic_graph())
    baseline = tmp_path / "cyc.json"
    baseline.write_text(json.dumps({"value": 0}), encoding="utf-8")  # current=1 > 0
    assert mig.main(["--freeze", "--baseline", str(baseline)]) == 2
    assert json.loads(baseline.read_text())["value"] == 0  # unchanged


def test_freeze_adopt_writes_current_value(tmp_path, monkeypatch):
    monkeypatch.setattr(mig, "build_aragora_graph", lambda *a, **k: _synthetic_graph())
    baseline = tmp_path / "cyc.json"
    assert mig.main(["--freeze", "--adopt", "--baseline", str(baseline)]) == 0
    written = json.loads(baseline.read_text())
    assert written["value"] == 1
    assert written["exclude_type_checking_imports"] is True


def test_list_cycles_returns_sorted_pairs():
    pairs = mig.list_mutual_cycles(_synthetic_graph())
    assert pairs == [["aragora.a", "aragora.b"]]
    assert len(pairs) == mig.count_mutual_cycles(_synthetic_graph())


def test_list_cycles_pairs_are_ordered_and_unique():
    graph = grimp.ImportGraph()
    for module in ("aragora", "aragora.z", "aragora.y", "aragora.m", "aragora.n"):
        graph.add_module(module)
    graph.add_import(importer="aragora.z", imported="aragora.y")
    graph.add_import(importer="aragora.y", imported="aragora.z")
    graph.add_import(importer="aragora.n", imported="aragora.m")
    graph.add_import(importer="aragora.m", imported="aragora.n")
    graph.add_import(importer="aragora.z", imported="aragora.m")  # one-way: not a cycle
    pairs = mig.list_mutual_cycles(graph)
    assert pairs == [["aragora.m", "aragora.n"], ["aragora.y", "aragora.z"]]
    assert all(a < b for a, b in pairs)
    assert pairs == sorted(pairs)


def test_list_cycles_cli_prints_json_matching_count(monkeypatch, capsys):
    monkeypatch.setattr(mig, "build_aragora_graph", lambda *a, **k: _synthetic_graph())
    assert mig.main(["--list-cycles"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cycles"] == [["aragora.a", "aragora.b"]]
    assert out["exclude_type_checking_imports"] is True
    assert len(out["cycles"]) == mig.count_mutual_cycles(_synthetic_graph())


def test_list_cycles_flag_is_documented_alongside_existing_flags(capsys):
    with pytest.raises(SystemExit) as exc:
        mig.main(["--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    for flag in ("--list-cycles", "--check", "--freeze", "--adopt", "--baseline", "--json"):
        assert flag in text


def test_default_output_has_three_integer_metrics(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mig, "build_aragora_graph", lambda *a, **k: _synthetic_graph())
    monkeypatch.setattr(mig, "count_handlers_flat_root", lambda *a, **k: 187)
    assert mig.main([]) == 0
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out["mutual_import_cycles"], int)
    assert isinstance(out["server_imported_by"], int)
    assert out["handlers_flat_root"] == 187
    assert out["exclude_type_checking_imports"] is True
