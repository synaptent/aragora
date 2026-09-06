from __future__ import annotations

import json
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from aragora.evaluation.outcome_decision_quality import (
    CostEntry,
    CostLedger,
    REQUIRED_CONDITIONS,
    build_model_visible_request,
    crux_recall,
    ensure_holdout_lock,
    execute_batch,
    load_benchmark_bundle,
    render_markdown,
    request_contains_outcome_data,
    run_subprocess_runner,
    score_results,
    validate_runner_response,
    verify_receipt,
)
from aragora.evaluation.decision_quality_corpus import canonical_json_bytes
from aragora.gauntlet.receipt_models import DecisionReceipt

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/benchmarks/decision_quality/benchmark-manifest.json"
IMPLEMENTATION_SHA = "a" * 40


@pytest.fixture(scope="module")
def bundle():
    loaded, report = load_benchmark_bundle(MANIFEST)
    assert report.ok and loaded is not None
    return loaded


def _response(request: dict[str, Any], *, receipt_path: str | None = None) -> dict[str, Any]:
    condition = request["roster"]
    calls = [
        {
            "family": member["family"],
            "requested_model": member["requested_model"],
            "resolved_model": member["allowed_resolved_models"][0],
            "transport": member["transport"],
            "billing_class": member["billing_class"],
            "latency_ms": 10.0,
            "cost_usd": 0.0,
        }
        for member in condition["members"]
    ]
    response: dict[str, Any] = {
        "ok": True,
        "calls": calls,
        "output": {
            "selected_option_id": request["case"]["options"][0]["option_id"],
            "forecast_probability": 0.6,
            "cruxes": ["schedule credibility and implementation readiness"],
            "source_ids": [request["case"]["sources"][0]["source_id"]],
            "rationale": "Bounded rationale.",
        },
    }
    if receipt_path is not None:
        response["receipt_path"] = receipt_path
    return response


def _receipt(
    path: Path,
    *,
    input_hash: str = "1" * 64,
    output: dict[str, Any] | None = None,
) -> None:
    receipt = DecisionReceipt(
        receipt_id="receipt-1",
        gauntlet_id="gauntlet-1",
        timestamp="2026-08-30T00:00:00Z",
        input_summary="Decision quality case",
        input_hash=input_hash,
        risk_summary={"critical": 0, "high": 0, "medium": 0, "low": 0},
        attacks_attempted=0,
        attacks_successful=0,
        probes_run=0,
        vulnerabilities_found=0,
        verdict="PASS",
        confidence=0.8,
        robustness_score=0.8,
        decision_payload=output,
    )
    path.write_text(json.dumps(receipt.to_dict(), indent=2), encoding="utf-8")


def test_model_request_excludes_outcome_sidecar(bundle) -> None:
    case = bundle.cases[0]
    outcome = next(
        item for item in bundle.outcomes["outcomes"] if item["case_id"] == case["case_id"]
    )

    request = build_model_visible_request(
        bundle,
        case,
        "single_claude",
        repetition=1,
        implementation_sha=IMPLEMENTATION_SHA,
    )

    assert not request_contains_outcome_data(request, outcome)
    assert "correct_option_id" not in json.dumps(request)
    assert "resolution_summary" not in json.dumps(request)


def test_outcome_leakage_detector_rejects_resolution_text(bundle) -> None:
    case = bundle.cases[0]
    outcome = next(
        item for item in bundle.outcomes["outcomes"] if item["case_id"] == case["case_id"]
    )
    request = build_model_visible_request(
        bundle,
        case,
        "single_claude",
        repetition=1,
        implementation_sha=IMPLEMENTATION_SHA,
    )
    request["leak"] = outcome["resolution_summary"]

    assert request_contains_outcome_data(request, outcome)


def test_outcome_leakage_detector_rejects_preregistered_crux_description(bundle) -> None:
    case = bundle.cases[0]
    outcome = next(
        item for item in bundle.outcomes["outcomes"] if item["case_id"] == case["case_id"]
    )
    request = build_model_visible_request(
        bundle,
        case,
        "single_claude",
        repetition=1,
        implementation_sha=IMPLEMENTATION_SHA,
    )
    request["leak"] = outcome["cruxes"][0]["description"]

    assert request_contains_outcome_data(request, outcome)


def test_outcome_leakage_detector_allows_incidental_generic_alias_overlap(bundle) -> None:
    case = next(
        item for item in bundle.cases if item["case_id"] == "policy-dev-sec-cyber-disclosure-2023"
    )
    outcome = next(
        item for item in bundle.outcomes["outcomes"] if item["case_id"] == case["case_id"]
    )
    request = build_model_visible_request(
        bundle,
        case,
        "single_claude",
        repetition=1,
        implementation_sha=IMPLEMENTATION_SHA,
    )

    assert "compliance readiness" in canonical_json_bytes(request).decode("utf-8")
    assert "compliance readiness" in outcome["cruxes"][2]["aliases"]
    assert not request_contains_outcome_data(request, outcome)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda response: response.update(calls=[]), "missing claude"),
        (
            lambda response: response["calls"][0].update(resolved_model="other-owner/model"),
            "resolved model identity mismatch",
        ),
        (
            lambda response: response["calls"][0].update(family="openai"),
            "unexpected family",
        ),
        (
            lambda response: response["calls"].append(dict(response["calls"][0])),
            "duplicate family claude",
        ),
    ],
)
def test_family_integrity_rejects_absent_mismatched_and_ambiguous_roster(
    bundle, mutation, message: str
) -> None:
    request = build_model_visible_request(
        bundle,
        bundle.cases[0],
        "single_claude",
        repetition=1,
        implementation_sha=IMPLEMENTATION_SHA,
    )
    response = _response(request)
    mutation(response)

    errors = validate_runner_response(response, request["roster"])

    assert any(message in error for error in errors)


def test_family_integrity_accepts_exact_frozen_owner(bundle) -> None:
    request = build_model_visible_request(
        bundle,
        bundle.cases[0],
        "single_claude",
        repetition=1,
        implementation_sha=IMPLEMENTATION_SHA,
    )
    assert not validate_runner_response(_response(request), request["roster"])


def test_crux_recall_is_deterministic() -> None:
    expected = [
        {
            "description": "Whether the published schedule remains credible",
            "aliases": ["schedule credibility"],
        },
        {
            "description": "Whether a replacement implementation is ready",
            "aliases": ["replacement readiness"],
        },
    ]
    assert crux_recall(["schedule credibility is uncertain"], expected) == 0.5


def test_cost_ledger_enforces_paid_api_utc_cap(tmp_path: Path) -> None:
    ledger = CostLedger(tmp_path / "costs.jsonl", daily_cap_usd=25.0)
    entry = CostEntry(
        recorded_at="2026-08-30T12:00:00Z",
        run_id="run-1",
        case_id="case-1",
        condition="single_openai",
        family="openai",
        model="model",
        transport="api",
        billing_class="paid_api",
        cost_usd=24.5,
    )
    ledger.append([entry])
    ledger.require_capacity("2026-08-30", 0.5)
    with pytest.raises(RuntimeError, match="budget exhausted"):
        ledger.require_capacity("2026-08-30", 0.51)


def test_holdout_lock_rejects_implementation_drift(bundle, tmp_path: Path) -> None:
    lock = tmp_path / "lock.json"
    ensure_holdout_lock(lock, bundle, IMPLEMENTATION_SHA)
    with pytest.raises(RuntimeError, match="holdout lock mismatch"):
        ensure_holdout_lock(lock, bundle, "b" * 40)


def test_receipt_verification_is_independent_and_detects_tampering(tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    _receipt(receipt_path)
    digest, status = verify_receipt(receipt_path)
    assert digest and status == "verified"
    payload = json.loads(receipt_path.read_text())
    payload["verdict"] = "FAIL"
    receipt_path.write_text(json.dumps(payload))
    _, status = verify_receipt(receipt_path)
    assert status == "failed"


def test_receipt_verification_binds_request_and_decision(tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    output = {"selected_option_id": "a"}
    _receipt(receipt_path, input_hash="a" * 64, output=output)

    _, status = verify_receipt(
        receipt_path,
        expected_input_hash="a" * 64,
        expected_output=output,
    )
    assert status == "verified"
    _, status = verify_receipt(receipt_path, expected_input_hash="b" * 64)
    assert status == "input_mismatch"
    _, status = verify_receipt(receipt_path, expected_output={"selected_option_id": "b"})
    assert status == "decision_mismatch"


def test_execute_batch_retries_infrastructure_once_and_records_failures(
    bundle, tmp_path: Path
) -> None:
    attempts: dict[str, int] = {}
    receipt_path = tmp_path / "team-receipt.json"
    _receipt(receipt_path)

    def runner(request: dict[str, Any]) -> dict[str, Any]:
        key = f"{request['case']['case_id']}:{request['condition']}"
        attempts[key] = attempts.get(key, 0) + 1
        if attempts[key] == 1:
            return {"ok": False, "infrastructure_failure": True, "error_class": "transient"}
        response = _response(request)
        if request["condition"] == "aragora_team":
            _receipt(
                receipt_path,
                input_hash=hashlib.sha256(canonical_json_bytes(request)).hexdigest(),
                output=response["output"],
            )
            response["receipt_path"] = str(receipt_path)
        return response

    summary = execute_batch(
        bundle,
        runner,
        split="development",
        repetition=1,
        implementation_sha=IMPLEMENTATION_SHA,
        run_id="retry-run",
        results_path=tmp_path / "results.jsonl",
        cost_ledger=CostLedger(tmp_path / "costs.jsonl", 25.0),
        recorded_at=datetime(2026, 8, 30, tzinfo=UTC),
        max_cases=1,
    )

    assert summary["completed"] == 4
    assert summary["infrastructure_retries"] == 4
    assert all(count == 2 for count in attempts.values())


def test_execute_batch_never_retries_model_failure(bundle, tmp_path: Path) -> None:
    calls = 0

    def runner(_: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"ok": False, "infrastructure_failure": False, "error_class": "model_refusal"}

    summary = execute_batch(
        bundle,
        runner,
        split="development",
        repetition=1,
        implementation_sha=IMPLEMENTATION_SHA,
        run_id="failure-run",
        results_path=tmp_path / "results.jsonl",
        cost_ledger=CostLedger(tmp_path / "costs.jsonl", 25.0),
        recorded_at=datetime(2026, 8, 30, tzinfo=UTC),
        max_cases=1,
    )

    assert summary["failures"] == 4
    assert calls == 4


def test_execute_batch_records_malformed_runner_numerics(bundle, tmp_path: Path) -> None:
    results_path = tmp_path / "results.jsonl"

    def runner(request: dict[str, Any]) -> dict[str, Any]:
        response = _response(request)
        response["calls"][0]["cost_usd"] = None
        response["calls"][0]["latency_ms"] = "fast"
        return response

    summary = execute_batch(
        bundle,
        runner,
        split="development",
        repetition=1,
        implementation_sha=IMPLEMENTATION_SHA,
        run_id="malformed-numeric-run",
        results_path=results_path,
        cost_ledger=CostLedger(tmp_path / "costs.jsonl", 25.0),
        recorded_at=datetime(2026, 8, 30, tzinfo=UTC),
        max_cases=1,
    )
    results = [json.loads(line) for line in results_path.read_text().splitlines()]

    assert summary["failures"] == 4
    assert len(results) == 4
    assert all(result["latency_ms"] >= 0 for result in results)
    assert all(result["cost_usd"] >= 0 for result in results)
    assert all("calls[0] invalid latency" in result["errors"] for result in results)
    assert all("calls[0] invalid cost" in result["errors"] for result in results)


def test_subprocess_runner_does_not_persist_secret_output() -> None:
    secret = "sk-do-not-persist-this"
    response = run_subprocess_runner(
        [sys.executable, "-c", f"import sys; sys.stderr.write('{secret}'); sys.exit(2)"],
        {"request": "safe"},
        timeout=5,
    )

    assert response["error_class"] == "runner_nonzero_exit"
    assert secret not in json.dumps(response)


def test_scoring_and_rendering_are_deterministic(bundle) -> None:
    case = bundle.cases[0]
    outcome = next(
        item for item in bundle.outcomes["outcomes"] if item["case_id"] == case["case_id"]
    )
    results = []
    for condition in REQUIRED_CONDITIONS:
        results.append(
            {
                "schema_version": "decision-quality-result/1.0",
                "benchmark_id": bundle.manifest["benchmark_id"],
                "revision": bundle.manifest["revision"],
                "manifest_sha256": bundle.manifest_sha256,
                "implementation_sha": IMPLEMENTATION_SHA,
                "case_id": case["case_id"],
                "condition": condition,
                "split": case["split"],
                "repetition": 1,
                "errors": [],
                "output": {
                    "selected_option_id": outcome["correct_option_id"],
                    "forecast_probability": 0.9
                    if outcome["correct_option_id"] == case["forecast_option_id"]
                    else 0.1,
                    "cruxes": [outcome["cruxes"][0]["description"]],
                    "source_ids": [source["source_id"] for source in case["sources"]],
                },
                "receipt_verification": "verified"
                if condition == "aragora_team"
                else "not_applicable",
                "latency_ms": 10.0,
                "cost_usd": 0.0,
                "calls": [{}],
            }
        )
    score = score_results(bundle, results, implementation_sha=IMPLEMENTATION_SHA)
    first = render_markdown(score)
    second = render_markdown(score)

    assert score["conditions"]["single_claude"]["mean_brier"] == pytest.approx(0.01)
    assert first == second
    assert "no statistical-significance claim" in first
    assert score["decision"] == "incomplete"
    assert score["team_brier_improvement"] is None
    assert "Holdout team Brier improvement" in first


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("benchmark_id", "stale-benchmark"),
        ("revision", "stale-revision"),
        ("manifest_sha256", "b" * 64),
        ("implementation_sha", "b" * 40),
    ],
)
def test_scoring_rejects_stale_or_mixed_result_bindings(
    bundle, field_name: str, value: str
) -> None:
    case = bundle.cases[0]
    result = {
        "schema_version": "decision-quality-result/1.0",
        "benchmark_id": bundle.manifest["benchmark_id"],
        "revision": bundle.manifest["revision"],
        "manifest_sha256": bundle.manifest_sha256,
        "implementation_sha": IMPLEMENTATION_SHA,
        "case_id": case["case_id"],
        "condition": "single_claude",
        "split": case["split"],
        "repetition": 1,
        "errors": [],
        "output": {},
        "receipt_verification": "not_applicable",
        "latency_ms": 0.0,
        "cost_usd": 0.0,
        "calls": [],
    }
    result[field_name] = value

    with pytest.raises(ValueError, match=field_name):
        score_results(bundle, [result], implementation_sha=IMPLEMENTATION_SHA)
