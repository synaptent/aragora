"""Inspection validates display fields before emitting any receipt output."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from aragora.cli.commands.receipt import cmd_receipt_inspect

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("value", ["label\nSigned: Yes\u001b[2J\u009b\u202e", "x" * 121, "\ud800"])
@pytest.mark.parametrize(
    "field",
    [
        "receipt_id",
        "gauntlet_id",
        "debate_id",
        "timestamp",
        "verdict",
        "consensus_proof.method",
        "consensus_proof.supporting_agents.0",
        "consensus_proof.dissenting_agents.0",
        "signature_algorithm",
        "signature_key_id",
        "agent_responses.0.agent_name",
        "agent_responses.0.role",
        "agent_responses.0.llm_label",
        "config_used.critique_summaries.0.critic",
        "config_used.critique_summaries.0.target",
        "config_used.critique_summaries.0.issues.0",
        "dissenting_views.0",
    ],
)
def test_all_display_text_uses_escaped_capped_rendering(
    field: str, value: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data: dict[str, Any] = {"signature": "present"}
    cursor: Any = data
    parts = field.split(".")
    for index, part in enumerate(parts[:-1]):
        child: Any = [] if parts[index + 1].isdigit() else {}
        if isinstance(cursor, list):
            cursor.append(child)
        else:
            cursor[part] = child
        cursor = child
    if isinstance(cursor, list):
        cursor.append(value)
    else:
        cursor[parts[-1]] = value
    source = tmp_path / "receipt.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    cmd_receipt_inspect(argparse.Namespace(receipt=str(source)))
    captured = capsys.readouterr()
    assert value not in captured.out
    if value == "\ud800":
        assert "(unrenderable)" in captured.out
        assert captured.err.count("Warning:") == 1
    else:
        expected = (
            "x" * 117 + "..."
            if value.startswith("x")
            else r"label\nSigned: Yes\u001b[2J\u009b\u202e"
        )
        assert expected in captured.out
        assert captured.err == ""


def test_numeric_risk_strings_escape_whitespace_in_real_cli(tmp_path: Path) -> None:
    result = inspect_process({"risk_summary": {"high": "\n\t2\r"}}, tmp_path)
    assert result.returncode == 0, result.stderr
    assert r"High:          \n\t2\r" in result.stdout
    assert "\n\t2\n" not in result.stdout


def inspect_process(data: dict[str, Any], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "receipt.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "aragora.cli.main", "receipt", "inspect", str(source)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize(
    "data,field",
    [
        ({"confidence": "oops"}, "confidence"),
        ({"confidence": float("nan")}, "confidence"),
        ({"verdict": None}, "verdict"),
        ({"risk_summary": ["oops"]}, "risk_summary"),
        ({"agent_responses": ["oops"]}, "agent_responses[0]"),
        ({"config_used": None}, "config_used"),
    ],
)
def test_malformed_inspection_through_cli(data: dict[str, Any], field: str, tmp_path: Path) -> None:
    result = inspect_process(data, tmp_path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Error:" in result.stderr
    assert field in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "data,field",
    [
        ({"confidence": True}, "confidence"),
        ({"confidence": None}, "confidence"),
        ({"confidence": 10**400}, "confidence"),
        ({"confidence": 1e308}, "confidence"),
        ({"robustness_score": float("inf")}, "robustness_score"),
        ({"verdict": []}, "verdict"),
        ({"risk_summary": {"total": "many"}}, "risk_summary.total"),
        ({"consensus_proof": []}, "consensus_proof"),
        ({"consensus_proof": {"reached": "undetermined"}}, "consensus_proof.reached"),
        ({"consensus_proof": {"reached": []}}, "consensus_proof.reached"),
        ({"consensus_proof": {"supporting_agents": "alice"}}, "supporting_agents"),
        ({"consensus_proof": {"dissenting_agents": [1]}}, "dissenting_agents[0]"),
        ({"agent_responses": {}}, "agent_responses"),
        ({"agent_responses": [{"content": None}]}, "agent_responses[0].content"),
        ({"agent_responses": [{"content": []}]}, "agent_responses[0].content"),
        ({"agent_responses": [{}] * 10 + [False]}, "agent_responses[10]"),
        ({"cost_summary": []}, "cost_summary"),
        ({"config_used": {"critique_summaries": {}}}, "critique_summaries"),
        ({"config_used": {"critique_summaries": [None]}}, "critique_summaries[0]"),
        (
            {"config_used": {"critique_summaries": [{"issues": None}]}},
            "critique_summaries[0].issues",
        ),
        ({"dissenting_views": "one view"}, "dissenting_views"),
    ],
)
def test_invalid_fields_never_emit_partial_receipt(
    data: dict[str, Any], field: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "receipt.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cmd_receipt_inspect(argparse.Namespace(receipt=str(source)))
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Error:" in captured.err
    assert field in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("verdict", ["PASS", "pass", "CONDITIONAL", "FAIL", "legacy-verdict"])
def test_supported_receipt_inspection(verdict: str, tmp_path: Path) -> None:
    data = {
        "receipt_id": "legacy-1",
        "verdict": verdict,
        "confidence": 0.75,
        "robustness_score": 1,
        "risk_summary": {"total": 2, "high": 1},
        "consensus_proof": {"reached": False, "supporting_agents": ["alice", "bob"]},
        "signature": "present-but-not-verified",
        "artifact_hash": "a" * 64,
        "agent_responses": [{"agent_name": "alice", "content": "hello"}],
        "cost_summary": {"total": "0.0123"},
        "config_used": {
            "critique_summaries": [{"critic": "bob", "severity": 0.5, "issues": ["risk"]}]
        },
        "dissenting_views": ["wait"],
    }
    result = inspect_process(data, tmp_path)
    assert result.returncode == 0, result.stderr
    for expected in (
        "Receipt ID:    legacy-1",
        verdict,
        "Confidence:    75.0%",
        "Robustness:    100.0%",
        "Reached:       No",
        "Supporting:    alice, bob",
        "Signed:        Yes",
        "alice: 5 chars",
        "Total: $0.0123",
        "severity: 0.5",
        "- risk",
        "- wait",
    ):
        assert expected in result.stdout
    assert "VALID" not in result.stdout
    assert "cryptographic signature verified" not in result.stdout.lower()


def test_missing_and_nullable_optional_fields_preserve_defaults(tmp_path: Path) -> None:
    empty = inspect_process({}, tmp_path)
    nullable = inspect_process({"consensus_proof": None, "cost_summary": None}, tmp_path)
    assert empty.returncode == nullable.returncode == 0
    assert empty.stdout == nullable.stdout
    assert "? UNKNOWN" in empty.stdout
    assert "Confidence:    0.0%" in empty.stdout


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "No"),
        (1, "Yes"),
        (False, "No"),
        (True, "Yes"),
        ("false", "No"),
        ("true", "Yes"),
        ("0", "No"),
        ("1", "Yes"),
        ("no", "No"),
        ("yes", "Yes"),
        ("off", "No"),
        (" ON ", "Yes"),
        ("", "No"),
        (None, "No"),
        (2, "Yes"),
        (-1, "Yes"),
        (0.0, "No"),
        (-0.0, "No"),
        (0.5, "Yes"),
        (-0.5, "Yes"),
        (10**400, "Yes"),
        (" Y ", "Yes"),
        (" N ", "No"),
    ],
)
def test_legacy_consensus_boolean_forms(value: Any, expected: str, tmp_path: Path) -> None:
    result = inspect_process({"consensus_proof": {"reached": value}}, tmp_path)
    assert result.returncode == 0, result.stderr
    assert f"Reached:       {expected}" in result.stdout


def test_model_generated_receipt_remains_inspectable(tmp_path: Path) -> None:
    from aragora.gauntlet.receipt_models import AgentResponseRecord, DecisionReceipt

    receipt = DecisionReceipt(
        receipt_id="native-1",
        gauntlet_id="g1",
        timestamp="2026-09-12T00:00:00Z",
        input_summary="example",
        input_hash="a" * 64,
        risk_summary={},
        attacks_attempted=0,
        attacks_successful=0,
        probes_run=0,
        vulnerabilities_found=0,
        verdict="PASS",
        confidence=0.8,
        robustness_score=0.9,
        agent_responses=[AgentResponseRecord(agent="alice", response="hello")],
    )
    result = inspect_process(receipt.to_dict(), tmp_path)
    assert result.returncode == 0, result.stderr
    assert "native-1" in result.stdout


@pytest.mark.parametrize(
    "flag", ["true", "1", "yes", "y", "on", "false", "0", "no", "n", "off", ""]
)
def test_strict_model_boolean_strings(flag: str) -> None:
    from aragora.gauntlet.receipt_models import _normalize_receipt_boolean

    for value in (flag, flag.upper(), f"  {flag.upper()}  "):
        assert _normalize_receipt_boolean(value, strict=True) == _normalize_receipt_boolean(value)
    assert _normalize_receipt_boolean(None, strict=True, default=True) is False
    assert _normalize_receipt_boolean(None, default=True) is True


@pytest.mark.parametrize(
    "value",
    [
        "unknown",
        "2",
        "none",
        "false-ish",
        [],
        {},
        [True],
        float("nan"),
        float("inf"),
        -float("inf"),
    ],
)
def test_unknown_boolean_never_defaults(value: Any, tmp_path: Path) -> None:
    from aragora.gauntlet.receipt_models import _normalize_receipt_boolean

    with pytest.raises(ValueError):
        _normalize_receipt_boolean(value, strict=True)
    assert _normalize_receipt_boolean(value, default=True) is True
    result = inspect_process({"consensus_proof": {"reached": value}}, tmp_path)
    assert result.returncode == 1 and result.stdout == ""
    assert "consensus_proof.reached" in result.stderr and "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "value", [0, 2.5, "0", " 2.5 ", "1e2", "NaN", "Infinity", "many", float("nan"), float("inf")]
)
def test_numeric_risk_count_contract(value: Any, tmp_path: Path) -> None:
    import math

    result = inspect_process({"risk_summary": {"total": value}}, tmp_path)
    valid = value != "many" and math.isfinite(float(value))
    assert result.returncode == (0 if valid else 1), result.stderr
    if valid:
        assert f"Total:         {value}" in result.stdout
    else:
        assert result.stdout == "" and "risk_summary.total" in result.stderr


@pytest.mark.parametrize(
    "field",
    [
        "signature",
        "artifact_hash",
        "input_hash",
        "verdict_reasoning",
        "total_cost",
        "total",
        "severity",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        "legacy",
        "caf\u00e9",
        "x" * 1000,
        "a\nb\r\t\x1b[31m\x07\x7f\x85\u202e",
        0,
        42.5,
        pytest.param(10**2000, id="large-positive-int"),
        pytest.param(-(10**3000), id="large-negative-int"),
        {},
        [],
        {"key": "x" * 140},
        ["a\nb"],
        float("inf"),
        True,
        None,
        {"bad": float("nan")},
        "\ud800",
    ],
)
def test_cosmetic_values_are_display_only(
    field: str, value: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = {field: value}
    if field in ("total_cost", "total"):
        data = {"cost_summary": {field: value}}
    elif field == "severity":
        data = {"config_used": {"critique_summaries": [{field: value}]}}
    source = tmp_path / "cosmetic.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    cmd_receipt_inspect(argparse.Namespace(receipt=str(source)))
    captured = capsys.readouterr()
    if (
        value == "\ud800"
        or value is None
        or value is True
        or value == float("inf")
        or isinstance(value, dict)
        and "bad" in value
    ):
        assert "(unrenderable)" in captured.out
        assert captured.err.count("Warning:") == 1
    else:
        expected = (
            json.dumps(value, separators=(",", ":"))
            if isinstance(value, (dict, list))
            else str(value)
        )
        if value == "a\nb\r\t\x1b[31m\x07\x7f\x85\u202e":
            expected = r"a\nb\r\t\u001b[31m\u0007\u007f\u0085\u202e"
        expected = expected[:117] + "..." if len(expected) > 120 else expected
        labels = {
            "signature": "Signature:     ",
            "artifact_hash": "Artifact Hash: ",
            "input_hash": "Input Hash:    ",
            "verdict_reasoning": "  ",
            "total_cost": "  Total: $",
            "total": "  Total: $",
            "severity": "severity: ",
        }
        assert labels[field] + expected in captured.out
        assert captured.err == ""
    assert "Traceback" not in captured.err and "[PASS]" not in captured.out


@pytest.mark.parametrize("length", [119, 120, 121, 1000])
def test_cosmetic_cap_applies_after_escaping(length: int) -> None:
    from aragora.cli.commands.receipt import _inspection_cosmetic

    value = "\n" * length
    assert _inspection_cosmetic(value, "signature") == (r"\n" * length)[:117] + "..."
    expected = "x" * length if length <= 120 else "x" * 117 + "..."
    assert _inspection_cosmetic("x" * length, "signature") == expected


@pytest.mark.parametrize("length", [119, 120, 121, 3000])
def test_numeric_display_cap_boundaries(length: int) -> None:
    from aragora.cli.commands.receipt import _inspection_cosmetic

    value = int("1" * length)
    expected = str(value) if length <= 120 else "1" * 117 + "..."
    assert _inspection_cosmetic(value, "numeric") == expected


def test_escaped_cosmetics_through_cli(tmp_path: Path) -> None:
    result = inspect_process({"signature": "\x1b[31m\nForged", "input_hash": "h" * 1000}, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Cannot render receipt field" not in result.stderr and "Traceback" not in result.stderr
    assert r"Signature:     \u001b[31m\nForged" in result.stdout
    assert "Input Hash:    " + "h" * 117 + "..." in result.stdout
    assert "\x1b" not in result.stdout and "\nForged" not in result.stdout


def test_pre_validator_legacy_fixture(tmp_path: Path) -> None:
    # Checked in on 2026-02-12, before this campaign's inspection validator.
    data = json.loads((ROOT / "examples/sample_receipt.json").read_text())
    result = inspect_process(data, tmp_path)
    assert result.returncode == 0, result.stderr
    assert data["receipt_id"] in result.stdout
