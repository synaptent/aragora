from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from scripts import outcome_decision_quality_benchmark as cli

ROOT = Path(__file__).resolve().parents[2]


def test_validate_corpus_cli_reports_frozen_contract(capsys) -> None:
    exit_code = cli.main(["validate-corpus"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["case_count"] == 24


def test_validate_corpus_cli_returns_structured_error_for_invalid_utf8(
    tmp_path: Path, capsys
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"\xff\xfe")

    exit_code = cli.main(["validate-corpus", "--manifest", str(manifest)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["issues"][0]["code"] == "invalid_utf8"


def test_render_cli_is_deterministic(tmp_path: Path, capsys) -> None:
    score: dict[str, Any] = {
        "benchmark_id": "benchmark",
        "revision": "v1",
        "manifest_sha256": "1" * 64,
        "decision": "incomplete",
        "best_single_condition": None,
        "team_brier_improvement": None,
        "incomplete_results": [],
        "uncertainty_note": "Descriptive only.",
        "conditions": {
            condition: {
                "n": 0,
                "mean_brier": None,
                "directional_accuracy": None,
                "crux_recall": None,
                "provenance_completeness": None,
                "receipt_verification_rate": None,
                "model_calls": 0,
                "cost_usd": 0.0,
            }
            for condition in (
                "single_claude",
                "single_openai",
                "single_gemini",
                "aragora_team",
            )
        },
    }
    score_path = tmp_path / "score.json"
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    score_path.write_text(json.dumps(score), encoding="utf-8")

    assert cli.main(["render", "--score", str(score_path), "--output", str(first)]) == 0
    capsys.readouterr()
    assert cli.main(["render", "--score", str(score_path), "--output", str(second)]) == 0
    capsys.readouterr()
    assert first.read_bytes() == second.read_bytes()


def test_result_schema_covers_required_proof_fields() -> None:
    schema = json.loads((ROOT / "docs/benchmarks/decision_quality/result.schema.json").read_text())
    required = set(schema["required"])

    assert {
        "case_id",
        "condition",
        "requested_model",
        "resolved_model",
        "transport",
        "output",
        "latency_ms",
        "cost_usd",
        "errors",
        "receipt_hash",
        "receipt_verification",
    } <= required
    Draft202012Validator.check_schema(schema)
