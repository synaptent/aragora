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
        ({"consensus_proof": {"reached": "false"}}, "consensus_proof.reached"),
        ({"consensus_proof": {"supporting_agents": "alice"}}, "supporting_agents"),
        ({"consensus_proof": {"dissenting_agents": [1]}}, "dissenting_agents[0]"),
        ({"signature": {}}, "signature"),
        ({"artifact_hash": 42}, "artifact_hash"),
        ({"input_hash": []}, "input_hash"),
        ({"verdict_reasoning": {}}, "verdict_reasoning"),
        ({"agent_responses": {}}, "agent_responses"),
        ({"agent_responses": [{"content": None}]}, "agent_responses[0].content"),
        ({"agent_responses": [{"content": []}]}, "agent_responses[0].content"),
        ({"agent_responses": [{}] * 10 + [False]}, "agent_responses[10]"),
        ({"cost_summary": []}, "cost_summary"),
        ({"cost_summary": {"total_cost": "oops"}}, "cost_summary.total_cost"),
        ({"cost_summary": {"total": "NaN"}}, "cost_summary.total"),
        ({"cost_summary": {"total_cost": True}}, "cost_summary.total_cost"),
        ({"config_used": {"critique_summaries": {}}}, "critique_summaries"),
        ({"config_used": {"critique_summaries": [None]}}, "critique_summaries[0]"),
        (
            {"config_used": {"critique_summaries": [{"severity": "high"}]}},
            "critique_summaries[0].severity",
        ),
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
    assert "verified" not in result.stdout.lower()


def test_missing_and_nullable_optional_fields_preserve_defaults(tmp_path: Path) -> None:
    empty = inspect_process({}, tmp_path)
    nullable = inspect_process(
        {"consensus_proof": None, "cost_summary": None, "signature": None}, tmp_path
    )
    assert empty.returncode == nullable.returncode == 0
    assert empty.stdout == nullable.stdout
    assert "? UNKNOWN" in empty.stdout
    assert "Confidence:    0.0%" in empty.stdout


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
