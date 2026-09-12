from __future__ import annotations

from typing import Any

import pytest

from aragora.evaluation.outcome_backed_contract import (
    CONDITION_IDS,
    FROZEN_CORPUS_DIGESTS,
    MANIFEST_SCHEMA,
    RESULT_SCHEMA,
    validate_benchmark_manifest,
    validate_result_batch,
    validate_result_record,
)
from aragora.evaluation.outcome_backed_corpus import BENCHMARK_ID
from aragora.evaluation.outcome_backed_scoring import SCORER_CONTRACT_VERSION


SHA256 = "a" * 64
IMPLEMENTATION_SHA = "b" * 40


def _member(family: str) -> dict[str, str]:
    return {
        "family": family,
        "requested_model": f"{family}-requested-v1",
        "resolved_model": f"{family}-resolved-v1",
        "transport": f"{family}-subscription",
    }


def _manifest() -> dict[str, Any]:
    conditions = [
        {
            "condition_id": f"{family}_single",
            "kind": "single_model",
            "members": [_member(family)],
            "adversarial_rounds": 0,
            "syntheses": 0,
        }
        for family in ("claude", "openai", "gemini")
    ]
    conditions.append(
        {
            "condition_id": "aragora_team",
            "kind": "aragora_team",
            "members": [_member(family) for family in ("claude", "openai", "gemini")],
            "adversarial_rounds": 1,
            "syntheses": 1,
        }
    )
    return {
        "schema_version": MANIFEST_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "revision": "decision-quality-v1-r1",
        "frozen_at": "2026-08-30T00:00:00Z",
        "corpus": {
            "visible_sha256": FROZEN_CORPUS_DIGESTS["visible_sha256"],
            "outcomes_sha256": FROZEN_CORPUS_DIGESTS["outcomes_sha256"],
            "case_count": 24,
            "development_count": 16,
            "holdout_count": 8,
        },
        "scorer_contract_version": SCORER_CONTRACT_VERSION,
        "prompt_sha256": {
            "single": "e" * 64,
            "team_proposal": "f" * 64,
            "team_adversarial": "1" * 64,
            "team_synthesis": "2" * 64,
        },
        "implementation_sha": IMPLEMENTATION_SHA,
        "policy": {
            "daily_cost_cap_usd": 25.0,
            "max_infrastructure_retries_per_call": 1,
            "holdout_repetitions": 2,
        },
        "conditions": conditions,
    }


def _attempt(attempt: int = 1, status: str = "success", cost: float = 0.1) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "status": status,
        "occurred_at": "2026-08-30T00:00:01Z",
        "latency_ms": 100,
        "cost_usd": cost,
        "error_class": None if status == "success" else "transport_unavailable",
    }


def _call(call_id: str, role: str, family: str, *, cost: float = 0.1) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "role": role,
        **_member(family),
        "attempts": [_attempt(cost=cost)],
    }


def _output() -> dict[str, Any]:
    return {
        "selected_option_id": "ship",
        "forecast_probability": 0.75,
        "cruxes": ["compatibility", "reliability", "rollback"],
        "source_ids": ["release-notes"],
        "text": "Ship because the preregistered cruxes are satisfied.",
    }


def _record(
    condition_id: str = "claude_single",
    *,
    case_id: str = "case-001",
    split: str = "development",
    repetition: int = 1,
    cost: float = 0.1,
) -> dict[str, Any]:
    manifest = _manifest()
    if condition_id == "aragora_team":
        calls = [
            _call(f"proposal-{family}", "proposal", family, cost=cost)
            for family in ("claude", "openai", "gemini")
        ]
        calls += [
            _call(f"adversarial-{family}", "adversarial", family, cost=cost)
            for family in ("claude", "openai", "gemini")
        ]
        calls.append(_call("synthesis", "synthesis", "claude", cost=cost))
        receipt = {"hash": SHA256, "verification": "verified"}
    else:
        family = condition_id.removesuffix("_single")
        calls = [_call("decision", "decision", family, cost=cost)]
        receipt = {"hash": None, "verification": "missing"}
    return {
        "schema_version": RESULT_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "manifest_sha256": validate_benchmark_manifest(manifest),
        "implementation_sha": IMPLEMENTATION_SHA,
        "case_id": case_id,
        "split": split,
        "repetition": repetition,
        "condition_id": condition_id,
        "started_at": "2026-08-30T00:00:00Z",
        "completed_at": "2026-08-30T00:01:00Z",
        "calls": calls,
        "output": _output(),
        "receipt": receipt,
        "error": None,
    }


def test_valid_manifest_is_deterministic_and_frozen() -> None:
    assert validate_benchmark_manifest(_manifest()) == validate_benchmark_manifest(_manifest())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["conditions"].pop(), "exactly 4 conditions"),
        (lambda value: value["conditions"][-1]["members"].pop(), "three fixed model families"),
        (
            lambda value: value["policy"].update({"max_infrastructure_retries_per_call": 2}),
            "must be 1",
        ),
        (
            lambda value: value["corpus"].update({"visible_sha256": "0" * 64}),
            "does not match frozen corpus",
        ),
    ],
)
def test_manifest_rejects_incomplete_or_drifted_contract(mutate: Any, message: str) -> None:
    manifest = _manifest()
    mutate(manifest)

    with pytest.raises(ValueError, match=message):
        validate_benchmark_manifest(manifest)


def test_valid_single_and_team_results_bind_exact_roster() -> None:
    manifest = _manifest()

    assert validate_result_record(_record(), manifest) == {"2026-08-30": 0.1}
    assert validate_result_record(_record("aragora_team"), manifest)["2026-08-30"] == pytest.approx(
        0.7
    )


def test_rejects_model_family_or_transport_substitution() -> None:
    record = _record()
    record["calls"][0]["resolved_model"] = "claude-silent-substitute"

    with pytest.raises(ValueError, match="frozen model roster"):
        validate_result_record(record, _manifest())


def test_allows_one_infrastructure_retry_and_rejects_other_retries() -> None:
    record = _record()
    record["calls"][0]["attempts"] = [
        _attempt(status="infrastructure_error"),
        _attempt(attempt=2),
    ]
    validate_result_record(record, _manifest())

    record["calls"][0]["attempts"][0] = _attempt(status="model_error")
    with pytest.raises(ValueError, match="only after an infrastructure_error"):
        validate_result_record(record, _manifest())

    record = _record()
    record["calls"][0]["attempts"] *= 3
    with pytest.raises(ValueError, match="one-infrastructure-retry"):
        validate_result_record(record, _manifest())


def test_failed_call_is_recorded_without_fabricated_output() -> None:
    record = _record()
    record["calls"][0]["attempts"] = [_attempt(status="credential_error")]
    record["output"] = None
    record["error"] = {"error_class": "credential_error", "message": "provider rejected auth"}

    validate_result_record(record, _manifest())

    record["output"] = _output()
    record["error"] = None
    with pytest.raises(ValueError, match="every logical call to succeed"):
        validate_result_record(record, _manifest())


def test_team_success_requires_complete_topology_and_verified_receipt() -> None:
    record = _record("aragora_team")
    record["calls"].pop()
    with pytest.raises(ValueError, match="frozen team topology"):
        validate_result_record(record, _manifest())

    record = _record("aragora_team")
    record["receipt"] = {"hash": None, "verification": "missing"}
    with pytest.raises(ValueError, match="independently verified receipt"):
        validate_result_record(record, _manifest())


def test_result_rejects_manifest_or_holdout_freeze_drift() -> None:
    record = _record(split="holdout", repetition=2)
    validate_result_record(record, _manifest())

    record["manifest_sha256"] = "9" * 64
    with pytest.raises(ValueError, match="does not bind the frozen manifest"):
        validate_result_record(record, _manifest())

    record = _record(split="holdout", repetition=3)
    with pytest.raises(ValueError, match="holdout repetition"):
        validate_result_record(record, _manifest())


def test_complete_batch_enforces_matrix_and_daily_cost_cap() -> None:
    manifest = _manifest()
    case_ids = [f"case-{index:03d}" for index in range(1, 17)]
    records = [
        _record(condition, case_id=case_id, cost=0.01)
        for case_id in case_ids
        for condition in CONDITION_IDS
    ]

    assert validate_result_batch(
        records,
        manifest,
        expected_case_ids=case_ids,
        split="development",
        repetition=1,
    ) == {"2026-08-30": pytest.approx(1.6)}

    with pytest.raises(ValueError, match="incomplete"):
        validate_result_batch(
            records[:-1],
            manifest,
            expected_case_ids=case_ids,
            split="development",
            repetition=1,
        )

    expensive = [
        _record(condition, case_id=case_id, cost=3.0)
        for case_id in case_ids
        for condition in CONDITION_IDS
    ]
    with pytest.raises(ValueError, match="cost cap exceeded"):
        validate_result_batch(
            expensive,
            manifest,
            expected_case_ids=case_ids,
            split="development",
            repetition=1,
        )

    with pytest.raises(ValueError, match="exactly 16 development cases"):
        validate_result_batch(
            records[:4],
            manifest,
            expected_case_ids=["case-001"],
            split="development",
            repetition=1,
        )
