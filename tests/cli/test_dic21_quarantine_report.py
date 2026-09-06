"""Tests for ``aragora quarantine-report`` CLI command (DIC-21 / #6032)."""

from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

if "yaml" not in sys.modules:
    sys.modules["yaml"] = MagicMock()  # type: ignore[assignment]


@dataclass
class _Signal:
    code_unit_id: str = "test.unit"
    integrity_score: float = 0.9
    recommended_action: str = "report_only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_unit_id": self.code_unit_id,
            "integrity_score": self.integrity_score,
            "recommended_action": self.recommended_action,
            "reasons": [],
        }


def _args(**kw) -> argparse.Namespace:
    return argparse.Namespace(
        **{
            "input": "-",
            "code_unit_class": "default",
            "request_live_swap": False,
            "json": False,
            **kw,
        }
    )


def _run(monkeypatch, *, sig: _Signal | None = None, **kw):
    from aragora.cli.commands.dic21_quarantine_report import cmd_quarantine_report

    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps((sig or _Signal()).to_dict())))
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    return cmd_quarantine_report(_args(**kw)), out.getvalue(), err.getvalue()


@pytest.fixture()
def flag_on(monkeypatch):
    monkeypatch.setenv("ARAGORA_QUARANTINE_POLICY_ENABLED", "1")


def test_flag_off_exits_1(monkeypatch):
    monkeypatch.delenv("ARAGORA_QUARANTINE_POLICY_ENABLED", raising=False)
    rc, _, err = _run(monkeypatch)
    assert rc == 1 and "ARAGORA_QUARANTINE_POLICY_ENABLED" in err


def test_flag_on_exits_0(monkeypatch):
    monkeypatch.setenv("ARAGORA_QUARANTINE_POLICY_ENABLED", "1")
    assert _run(monkeypatch)[0] == 0


def test_healthy_unit_report_only(monkeypatch, flag_on):
    rc, out, _ = _run(monkeypatch)
    assert rc == 0 and "report_only" in out


def test_low_integrity_fail_closed(monkeypatch, flag_on):
    rc, out, _ = _run(monkeypatch, sig=_Signal(integrity_score=0.2))
    assert rc == 0 and "fail_closed" in out


def test_fail_closed_json_field(monkeypatch, flag_on):
    rc, out, _ = _run(monkeypatch, sig=_Signal(integrity_score=0.15), json=True)
    assert rc == 0 and json.loads(out)["fail_closed"] is True


def test_report_only_empty_provenance(monkeypatch, flag_on):
    rc, out, _ = _run(monkeypatch, json=True)
    assert rc == 0 and json.loads(out)["provenance_hash"] == ""


def test_repair_required_has_64char_hash(monkeypatch, flag_on):
    rc, out, _ = _run(
        monkeypatch,
        sig=_Signal(integrity_score=0.7, recommended_action="repair_required"),
        json=True,
    )
    assert rc == 0 and len(json.loads(out)["provenance_hash"]) == 64


def test_live_swap_always_blocked(monkeypatch, flag_on):
    rc, out, _ = _run(monkeypatch, request_live_swap=True, json=True)
    assert rc == 0 and json.loads(out)["live_swap_blocked"] is True


def test_live_dispatch_higher_threshold(monkeypatch, flag_on):
    # live_dispatch fail_closed_threshold=0.6; score 0.5 < 0.6 → fail_closed
    rc, out, _ = _run(
        monkeypatch, sig=_Signal(integrity_score=0.5), code_unit_class="live_dispatch", json=True
    )
    assert rc == 0 and json.loads(out)["fail_closed"] is True


def test_default_class_not_fail_closed_at_0_5(monkeypatch, flag_on):
    # default fail_closed_threshold=0.4; score 0.5 > 0.4 → not fail_closed
    rc, out, _ = _run(monkeypatch, sig=_Signal(integrity_score=0.5), json=True)
    assert rc == 0 and json.loads(out)["fail_closed"] is False


def test_reads_from_file(monkeypatch, tmp_path, flag_on):
    from aragora.cli.commands.dic21_quarantine_report import cmd_quarantine_report

    p = tmp_path / "sig.json"
    p.write_text(json.dumps(_Signal().to_dict()))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    assert cmd_quarantine_report(_args(input=str(p))) == 0
    assert "report_only" in out.getvalue()


def test_missing_file_exits_2(monkeypatch, flag_on):
    from aragora.cli.commands.dic21_quarantine_report import cmd_quarantine_report

    err = io.StringIO()
    monkeypatch.setattr("sys.stderr", err)
    assert cmd_quarantine_report(_args(input="/no/such.json")) == 2
    assert "not found" in err.getvalue()


def test_bad_json_exits_2(monkeypatch, flag_on):
    from aragora.cli.commands.dic21_quarantine_report import cmd_quarantine_report

    err = io.StringIO()
    monkeypatch.setattr("sys.stdin", io.StringIO("bad {{{"))
    monkeypatch.setattr("sys.stderr", err)
    assert cmd_quarantine_report(_args()) == 2 and "invalid JSON" in err.getvalue()


def test_missing_code_unit_id_exits_2(monkeypatch, flag_on):
    from aragora.cli.commands.dic21_quarantine_report import cmd_quarantine_report

    err = io.StringIO()
    monkeypatch.setattr("sys.stdin", io.StringIO('{"integrity_score": 0.9}'))
    monkeypatch.setattr("sys.stderr", err)
    assert cmd_quarantine_report(_args()) == 2


def test_text_has_key_fields(monkeypatch, flag_on):
    rc, out, _ = _run(monkeypatch)
    assert rc == 0 and all(f in out for f in ("code_unit_id", "policy_action", "rationale"))


def test_json_has_all_required_keys(monkeypatch, flag_on):
    rc, out, _ = _run(monkeypatch, json=True)
    assert rc == 0
    assert all(
        k in json.loads(out)
        for k in (
            "code_unit_id",
            "policy_action",
            "fail_closed",
            "live_swap_blocked",
            "integrity_score",
            "provenance_hash",
        )
    )
