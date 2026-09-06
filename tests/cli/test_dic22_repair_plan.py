"""Tests for the ``aragora repair-plan`` CLI command (DIC-22 / #6033).

All tests run offline: no subprocess calls, no network, no queue mutation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

for _stub in ["yaml", "pydantic", "pydantic.fields", "pydantic_settings", "pydantic_settings.main"]:
    if _stub not in sys.modules:
        sys.modules[_stub] = MagicMock()

from aragora.cli.commands.dic22_repair_plan import cmd_repair_plan  # noqa: E402


def _ns(input_path: str, *, repair_kind: str = "report_only", json_output: bool = False):
    ns = argparse.Namespace()
    ns.input = input_path
    ns.repair_kind = repair_kind
    ns.json = json_output
    return ns


def _write_signal(tmp_path: Path, code_unit_id: str = "proof.unit.alpha") -> Path:
    p = tmp_path / "signal.json"
    p.write_text(
        json.dumps(
            {
                "code_unit_id": code_unit_id,
                "integrity_score": 0.4,
                "reasons": [{"kind": "failed_claim", "detail": "stale", "claim_id": "b0.truth"}],
                "recommended_action": "repair_required",
            }
        ),
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# Flag gating
# ---------------------------------------------------------------------------


def test_report_only_no_flag_required(tmp_path, capsys):
    p = _write_signal(tmp_path)
    with patch.dict("os.environ", {"ARAGORA_REPAIR_PIPELINE_ENABLED": ""}):
        rc = cmd_repair_plan(_ns(str(p), json_output=True))
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["repair_kind"] == "report_only"


def test_shadow_candidate_requires_flag(tmp_path, capsys):
    p = _write_signal(tmp_path)
    with patch.dict("os.environ", {"ARAGORA_REPAIR_PIPELINE_ENABLED": ""}):
        rc = cmd_repair_plan(_ns(str(p), repair_kind="shadow_candidate"))
    assert rc == 1
    assert "ARAGORA_REPAIR_PIPELINE_ENABLED" in capsys.readouterr().err


def test_shadow_candidate_with_flag(tmp_path, capsys):
    p = _write_signal(tmp_path)
    with patch.dict("os.environ", {"ARAGORA_REPAIR_PIPELINE_ENABLED": "1"}):
        rc = cmd_repair_plan(_ns(str(p), repair_kind="shadow_candidate", json_output=True))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["repair_kind"] == "shadow_candidate"
    assert len(out["provenance_hash"]) == 64


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_missing_file_exits_2(tmp_path, capsys):
    rc = cmd_repair_plan(_ns(str(tmp_path / "absent.json")))
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_bad_json_exits_2(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json}", encoding="utf-8")
    rc = cmd_repair_plan(_ns(str(p)))
    assert rc == 2
    assert "failed to read" in capsys.readouterr().err


def test_missing_code_unit_id_exits_2(tmp_path, capsys):
    p = tmp_path / "missing_id.json"
    p.write_text(json.dumps({"integrity_score": 0.5}), encoding="utf-8")
    rc = cmd_repair_plan(_ns(str(p)))
    assert rc == 2
    assert "malformed" in capsys.readouterr().err


def test_array_input_exits_2(tmp_path, capsys):
    p = tmp_path / "list.json"
    p.write_text(json.dumps([{"code_unit_id": "x"}]), encoding="utf-8")
    rc = cmd_repair_plan(_ns(str(p)))
    assert rc == 2


# ---------------------------------------------------------------------------
# JSON output shape
# ---------------------------------------------------------------------------


def test_json_has_required_keys(tmp_path, capsys):
    p = _write_signal(tmp_path)
    with patch.dict("os.environ", {}, clear=False):
        cmd_repair_plan(_ns(str(p), json_output=True))
    out = json.loads(capsys.readouterr().out)
    assert {
        "spec_id",
        "code_unit_id",
        "repair_kind",
        "linked_claims",
        "linked_crux_ids",
        "created_at",
        "provenance_hash",
        "decay_signal",
    } <= out.keys()


def test_report_only_provenance_hash_empty(tmp_path, capsys):
    p = _write_signal(tmp_path)
    with patch.dict("os.environ", {}, clear=False):
        cmd_repair_plan(_ns(str(p), json_output=True))
    assert json.loads(capsys.readouterr().out)["provenance_hash"] == ""


def test_linked_claims_auto_extracted(tmp_path, capsys):
    p = _write_signal(tmp_path)
    with patch.dict("os.environ", {}, clear=False):
        cmd_repair_plan(_ns(str(p), json_output=True))
    assert "b0.truth" in json.loads(capsys.readouterr().out)["linked_claims"]


def test_spec_id_has_repair_prefix(tmp_path, capsys):
    p = _write_signal(tmp_path)
    with patch.dict("os.environ", {}, clear=False):
        cmd_repair_plan(_ns(str(p), json_output=True))
    assert json.loads(capsys.readouterr().out)["spec_id"].startswith("repair-")


def test_parser_registers_repair_plan():
    from aragora.cli.parser import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if hasattr(a, "_name_parser_map"))
    assert "repair-plan" in sub._name_parser_map
