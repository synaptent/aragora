"""Tests for aragora.cli.commands.dic24_genealogy.cmd_genealogy_report (DIC-24 / #6218).

Run with:
    pytest tests/cli/test_dic24_genealogy_report.py --noconftest

All tests are hermetic; tmpdir for JSONL files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from aragora.cli.commands.dic24_genealogy import (
    _FLAG,
    cmd_genealogy_report,
)

_A = {
    "code_unit_id": "proof_first.shift",
    "entry_kind": "decay_signal",
    "entry_id": "decay-001",
    "checksum": "aabbcc",
    "timestamp": "2026-04-25T10:00:00Z",
}
_B = {
    "code_unit_id": "proof_first.shift",
    "entry_kind": "repair_proposal",
    "entry_id": "repair-001",
    "checksum": "ddeeff",
    "timestamp": "2026-04-26T12:00:00Z",
}
_C = {
    "code_unit_id": "core.consensus",
    "entry_kind": "decision_receipt",
    "entry_id": "receipt-007",
    "checksum": "112233",
    "timestamp": "2026-04-27T08:00:00Z",
}


def _store(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "gen.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return p


def _ns(**kw) -> argparse.Namespace:
    d = {
        "store_file": ".aragora_genealogy.jsonl",
        "json": False,
        "code_unit_ids": [],
        "all": False,
    }
    d.update(kw)
    return argparse.Namespace(**d)


# -- Flag gating --


class TestFlagGating:
    def test_exits_1_when_flag_off(self, monkeypatch, tmp_path) -> None:
        monkeypatch.delenv(_FLAG, raising=False)
        args = _ns(store_file=str(_store(tmp_path, [_A])), code_unit_ids=["proof_first.shift"])
        assert cmd_genealogy_report(args) == 1

    def test_error_message_names_flag(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.delenv(_FLAG, raising=False)
        args = _ns(store_file=str(_store(tmp_path, [_A])), code_unit_ids=["proof_first.shift"])
        cmd_genealogy_report(args)
        assert _FLAG in capsys.readouterr().err

    @pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
    def test_flag_truthy_values_accepted(self, monkeypatch, tmp_path, val: str) -> None:
        monkeypatch.setenv(_FLAG, val)
        args = _ns(
            code_unit_ids=["proof_first.shift"],
            store_file=str(_store(tmp_path, [_A])),
        )
        assert cmd_genealogy_report(args) == 0


# -- Text output --


class TestReportText:
    def test_shows_unit_id_and_entry_count(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setenv(_FLAG, "1")
        args = _ns(
            code_unit_ids=["proof_first.shift"],
            store_file=str(_store(tmp_path, [_A, _B])),
        )
        cmd_genealogy_report(args)
        out = capsys.readouterr().out
        assert "proof_first.shift" in out and "2" in out

    def test_empty_id_list_shows_no_units(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setenv(_FLAG, "1")
        args = _ns(code_unit_ids=[], store_file=str(_store(tmp_path, [_A])))
        assert cmd_genealogy_report(args) == 0
        assert "no units" in capsys.readouterr().out

    def test_missing_store_file_returns_0(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setenv(_FLAG, "1")
        args = _ns(code_unit_ids=["x"], store_file=str(tmp_path / "missing.jsonl"))
        assert cmd_genealogy_report(args) == 0


# -- JSON output --


class TestReportJson:
    def test_json_has_correct_top_level_fields(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setenv(_FLAG, "1")
        args = _ns(
            code_unit_ids=["proof_first.shift"],
            store_file=str(_store(tmp_path, [_A, _B])),
            json=True,
        )
        cmd_genealogy_report(args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["unit_count"] == 1
        assert payload["total_entries"] == 2
        assert "summaries" in payload
        assert "generated_at" in payload

    def test_json_summary_has_chain_checksum(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setenv(_FLAG, "1")
        args = _ns(
            code_unit_ids=["proof_first.shift"],
            store_file=str(_store(tmp_path, [_A])),
            json=True,
        )
        cmd_genealogy_report(args)
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["summaries"][0]["chain_checksum"]) == 64

    def test_json_multi_unit_total_entries(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setenv(_FLAG, "1")
        args = _ns(
            code_unit_ids=["proof_first.shift", "core.consensus"],
            store_file=str(_store(tmp_path, [_A, _B, _C])),
            json=True,
        )
        cmd_genealogy_report(args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["unit_count"] == 2
        assert payload["total_entries"] == 3

    def test_json_empty_ids_returns_zero_counts(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setenv(_FLAG, "1")
        args = _ns(
            code_unit_ids=[],
            store_file=str(_store(tmp_path, [_A])),
            json=True,
        )
        cmd_genealogy_report(args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["unit_count"] == 0
        assert payload["total_entries"] == 0


# -- --all mode --


class TestReportAll:
    def test_all_discovers_every_unit_in_store(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setenv(_FLAG, "1")
        args = _ns(
            all=True,
            store_file=str(_store(tmp_path, [_A, _B, _C])),
            json=True,
        )
        cmd_genealogy_report(args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["unit_count"] == 2
        assert payload["total_entries"] == 3

    def test_all_empty_store_returns_zero(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setenv(_FLAG, "1")
        args = _ns(all=True, store_file=str(tmp_path / "missing.jsonl"), json=True)
        cmd_genealogy_report(args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["unit_count"] == 0

    def test_all_overrides_explicit_ids(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setenv(_FLAG, "1")
        args = _ns(
            all=True,
            code_unit_ids=["proof_first.shift"],
            store_file=str(_store(tmp_path, [_A, _C])),
            json=True,
        )
        cmd_genealogy_report(args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["unit_count"] == 2
