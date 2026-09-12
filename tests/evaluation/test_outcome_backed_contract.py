from __future__ import annotations

import copy

import pytest

from aragora.evaluation.outcome_backed_batch import build_development_plan
from aragora.evaluation.outcome_backed_conditions import (
    ARAGORA_TEAM,
    CLAUDE_SINGLE,
    FROZEN_CONDITION_ROSTER,
)
from aragora.evaluation.outcome_backed_contract import (
    CONDITION_IDS,
    PHASE_IDS,
    OutcomeBackedContractError,
    build_execution_manifest,
    sanitize_error_message,
    validate_execution_manifest,
    validate_normalized_output,
    validate_result_batch,
    validate_result_record,
)
from aragora.evaluation.outcome_backed_corpus import BENCHMARK_ID, canonical_json_sha256
from aragora.evaluation.outcome_backed_packets import PACKET_SET_SCHEMA, SOURCE_PACKET_SCHEMA


def _cases() -> list[dict[str, str]]:
    return [{"case_id": f"dev-{index:02d}", "split": "development"} for index in range(16)] + [
        {"case_id": f"hold-{index:02d}", "split": "holdout"} for index in range(8)
    ]


def _packet(case_id: str, index: int) -> dict[str, object]:
    packet: dict[str, object] = {
        "schema_version": SOURCE_PACKET_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "case": {
            "case_id": case_id,
            "split": "development",
            "forecast_option_id": "yes",
            "options": [
                {"option_id": "yes", "label": "Yes"},
                {"option_id": "no", "label": "No"},
            ],
        },
        "sources": [{"source_id": f"source-{index:02d}", "title": "Source", "text": "Evidence"}],
    }
    packet["packet_sha256"] = canonical_json_sha256(packet)
    return packet


def _packet_set() -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    packets = {
        _id: _packet(_id, index) for index, _id in enumerate(f"dev-{i:02d}" for i in range(16))
    }
    manifest: dict[str, object] = {
        "schema_version": PACKET_SET_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "split": "development",
        "packet_count": 16,
        "source_count": 16,
        "packets": [
            {"case_id": case_id, "packet_sha256": packet["packet_sha256"]}
            for case_id, packet in packets.items()
        ],
    }
    manifest["packet_set_sha256"] = canonical_json_sha256(manifest)
    return manifest, packets


def _manifest() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, dict[str, object]],
]:
    packet_set, packets = _packet_set()
    plan = build_development_plan(_cases(), packet_set)
    manifest = build_execution_manifest(
        revision="test-v2",
        frozen_at="2026-08-31T00:00:00Z",
        corpus_sha256="a" * 64,
        packet_set=packet_set,
        development_plan=plan,
        phase_template_sha256={phase: f"{index + 1:064x}" for index, phase in enumerate(PHASE_IDS)},
        implementation_sha="b" * 40,
    )
    return manifest, packet_set, plan, packets


def _output() -> dict[str, object]:
    return {
        "selected_option_id": "yes",
        "forecast_probability": 0.75,
        "confidence": 0.7,
        "cruxes": ["regulatory approval", "financing closes", "integration succeeds"],
        "source_ids": ["source-00"],
        "summary": "The evidence favors closing.",
    }


def _critique(target_call_id: str, source_id: str) -> dict[str, object]:
    return {
        "target_call_id": target_call_id,
        "summary": "The proposal underweights execution risk.",
        "source_ids": [source_id],
    }


def _member(family: str):
    return next(
        member
        for condition in FROZEN_CONDITION_ROSTER
        for member in condition.members
        if member.family == family
    )


def _call(
    *,
    case_id: str,
    condition_id: str,
    sequence: int,
    role: str,
    family: str,
    input_call_ids: list[str],
    normalized_output: dict[str, object] | None,
    status: str = "success",
) -> dict[str, object]:
    member = _member(family)
    call_id = f"{case_id}:{condition_id}:{role}:{family}"
    success = status == "success"
    attempt = {
        "attempt": 1,
        "status": status,
        "occurred_at": "2026-08-31T00:00:01Z",
        "latency_ms": 10.0,
        "response_sha256": "d" * 64 if success else None,
        "usage": {
            "input_tokens": 2 if success else 0,
            "output_tokens": 3 if success else 0,
            "total_tokens": 5 if success else 0,
        },
        "billable_cost_usd": "0",
        "provider_equivalent_cost_usd": "0.001" if success else "0",
        "error_class": None if success else status,
    }
    return {
        "call_id": call_id,
        "sequence": sequence,
        "role": role,
        "family": family,
        "requested_model": member.requested_model,
        "resolved_model": member.expected_resolved_model,
        "transport": member.transport,
        "protocol": member.protocol,
        "catalog_owner": member.catalog_owner,
        "input_call_ids": input_call_ids,
        "prompt_sha256": "c" * 64,
        "response_sha256": attempt["response_sha256"],
        "attempts": [attempt],
        "usage": dict(attempt["usage"]),
        "billable_cost_usd": attempt["billable_cost_usd"],
        "provider_equivalent_cost_usd": attempt["provider_equivalent_cost_usd"],
        "latency_ms": attempt["latency_ms"],
        "normalized_output": normalized_output,
        "error": None if success else {"error_class": status, "message": "sanitized failure"},
    }


def _calls(case_id: str, condition_id: str) -> list[dict[str, object]]:
    if condition_id != ARAGORA_TEAM:
        family = condition_id.removesuffix("-single")
        output = _output()
        output["source_ids"] = [f"source-{int(case_id[-2:]):02d}"]
        return [
            _call(
                case_id=case_id,
                condition_id=condition_id,
                sequence=1,
                role="decision",
                family=family,
                input_call_ids=[],
                normalized_output=output,
            )
        ]
    prefix = f"{case_id}:{condition_id}"
    families = ("claude", "openai", "gemini")
    calls: list[dict[str, object]] = []
    for family in families:
        output = _output()
        output["source_ids"] = [f"source-{int(case_id[-2:]):02d}"]
        calls.append(
            _call(
                case_id=case_id,
                condition_id=condition_id,
                sequence=len(calls) + 1,
                role="proposal",
                family=family,
                input_call_ids=[],
                normalized_output=output,
            )
        )
    targets = {"claude": "openai", "openai": "gemini", "gemini": "claude"}
    for family in families:
        target_id = f"{prefix}:proposal:{targets[family]}"
        calls.append(
            _call(
                case_id=case_id,
                condition_id=condition_id,
                sequence=len(calls) + 1,
                role="critique",
                family=family,
                input_call_ids=[target_id],
                normalized_output=_critique(target_id, f"source-{int(case_id[-2:]):02d}"),
            )
        )
    output = _output()
    output["source_ids"] = [f"source-{int(case_id[-2:]):02d}"]
    calls.append(
        _call(
            case_id=case_id,
            condition_id=condition_id,
            sequence=7,
            role="synthesis",
            family="claude",
            input_call_ids=[str(call["call_id"]) for call in calls],
            normalized_output=output,
        )
    )
    return calls


def _result(
    manifest: dict[str, object], case_id: str, condition_id: str, packet: dict[str, object]
) -> dict[str, object]:
    calls = _calls(case_id, condition_id)
    result: dict[str, object] = {
        "schema_version": "outcome-backed-decision-quality-result/2.0",
        "benchmark_id": BENCHMARK_ID,
        "manifest_sha256": manifest["manifest_sha256"],
        "implementation_sha": manifest["implementation_sha"],
        "development_plan_sha256": manifest["development_plan_sha256"],
        "batch_id": "development-01",
        "case_id": case_id,
        "packet_sha256": packet["packet_sha256"],
        "split": "development",
        "repetition": 1,
        "condition_id": condition_id,
        "started_at": "2026-08-31T00:00:00Z",
        "completed_at": "2026-08-31T00:01:00Z",
        "calls": calls,
        "output": calls[-1]["normalized_output"],
        "receipt": {
            "receipt_hash": "e" * 64 if condition_id == ARAGORA_TEAM else None,
            "verification": "verified" if condition_id == ARAGORA_TEAM else "missing",
        },
        "error": None,
    }
    _rehash(result)
    return result


def _rehash(value: dict[str, object], field: str = "result_sha256") -> None:
    value[field] = canonical_json_sha256({key: item for key, item in value.items() if key != field})


def test_manifest_binds_current_roster_plan_packets_and_policy() -> None:
    manifest, packet_set, plan, packets = _manifest()

    assert CONDITION_IDS == ("claude-single", "openai-single", "gemini-single", "aragora-team")
    assert (
        validate_execution_manifest(manifest, packet_set=packet_set, development_plan=plan)
        == manifest["manifest_sha256"]
    )
    assert manifest["policy"] == {
        "daily_paid_spend_cap_usd": "25",
        "max_infrastructure_retries_per_call": 1,
        "allowed_transport": "vibeproxy-required",
        "paid_fallback_allowed": False,
    }
    assert set(packets) == {f"dev-{index:02d}" for index in range(16)}


def test_manifest_rejects_rehashed_roster_or_phase_drift() -> None:
    manifest, _, _, _ = _manifest()
    manifest["condition_roster_sha256"] = "f" * 64
    _rehash(manifest, "manifest_sha256")
    with pytest.raises(OutcomeBackedContractError, match="exact frozen roster"):
        validate_execution_manifest(manifest)

    manifest, _, _, _ = _manifest()
    del manifest["phase_template_sha256"]["team-critique"]
    _rehash(manifest, "manifest_sha256")
    with pytest.raises(OutcomeBackedContractError, match="four exact phase templates"):
        validate_execution_manifest(manifest)


def test_validates_single_result_and_team_topology() -> None:
    manifest, _, _, packets = _manifest()
    single = _result(manifest, "dev-00", CLAUDE_SINGLE, packets["dev-00"])
    team = _result(manifest, "dev-00", ARAGORA_TEAM, packets["dev-00"])

    assert validate_result_record(single, manifest, packets["dev-00"]) == {
        "billable_cost_usd": "0",
        "provider_equivalent_cost_usd": "0.001",
    }
    assert (
        validate_result_record(team, manifest, packets["dev-00"])["provider_equivalent_cost_usd"]
        == "0.007"
    )


def test_complete_first_batch_contains_exactly_40_logical_calls() -> None:
    manifest, packet_set, plan, packets = _manifest()
    records = [
        _result(manifest, case_id, condition_id, packets[case_id])
        for case_id in ("dev-00", "dev-01", "dev-02", "dev-03")
        for condition_id in CONDITION_IDS
    ]

    summary = validate_result_batch(
        records,
        manifest,
        packet_set,
        plan,
        batch_id="development-01",
        packets_by_case=packets,
    )

    assert summary["result_count"] == 16
    assert summary["logical_call_count"] == 40
    assert summary["billable_cost_usd"] == "0"


def test_success_rejects_model_or_catalog_owner_mismatch() -> None:
    manifest, _, _, packets = _manifest()
    result = _result(manifest, "dev-00", CLAUDE_SINGLE, packets["dev-00"])
    result["calls"][0]["resolved_model"] = "claude-alias"
    _rehash(result)

    with pytest.raises(OutcomeBackedContractError, match="model/owner mismatch"):
        validate_result_record(result, manifest, packets["dev-00"])


def test_identity_failure_can_record_observed_mismatch_without_fabricating_success() -> None:
    manifest, _, _, packets = _manifest()
    call = _call(
        case_id="dev-00",
        condition_id=CLAUDE_SINGLE,
        sequence=1,
        role="decision",
        family="claude",
        input_call_ids=[],
        normalized_output=None,
        status="identity_error",
    )
    call["resolved_model"] = "unexpected-model"
    result = _result(manifest, "dev-00", CLAUDE_SINGLE, packets["dev-00"])
    result.update(
        calls=[call],
        output=None,
        receipt={"receipt_hash": None, "verification": "missing"},
        error={"error_class": "identity_error", "message": "model owner mismatch"},
    )
    _rehash(result)

    assert validate_result_record(result, manifest, packets["dev-00"])["billable_cost_usd"] == "0"


def test_transport_failure_can_record_observed_mismatch() -> None:
    manifest, _, _, packets = _manifest()
    call = _call(
        case_id="dev-00",
        condition_id=CLAUDE_SINGLE,
        sequence=1,
        role="decision",
        family="claude",
        input_call_ids=[],
        normalized_output=None,
        status="transport_error",
    )
    call["transport"] = "unexpected-transport"
    result = _result(manifest, "dev-00", CLAUDE_SINGLE, packets["dev-00"])
    result.update(
        calls=[call],
        output=None,
        receipt={"receipt_hash": None, "verification": "missing"},
        error={"error_class": "transport_error", "message": "transport mismatch"},
    )
    _rehash(result)

    assert validate_result_record(result, manifest, packets["dev-00"])["billable_cost_usd"] == "0"


def test_dual_mismatch_uses_transport_error_precedence() -> None:
    manifest, _, _, packets = _manifest()
    call = _call(
        case_id="dev-00",
        condition_id=CLAUDE_SINGLE,
        sequence=1,
        role="decision",
        family="claude",
        input_call_ids=[],
        normalized_output=None,
        status="transport_error",
    )
    call["resolved_model"] = "unexpected-model"
    call["transport"] = "unexpected-transport"
    result = _result(manifest, "dev-00", CLAUDE_SINGLE, packets["dev-00"])
    result.update(
        calls=[call],
        output=None,
        receipt={"receipt_hash": None, "verification": "missing"},
        error={"error_class": "transport_error", "message": "transport and identity mismatch"},
    )
    _rehash(result)

    assert validate_result_record(result, manifest, packets["dev-00"])["billable_cost_usd"] == "0"

    call["attempts"][0]["status"] = "identity_error"
    call["attempts"][0]["error_class"] = "identity_error"
    call["error"] = {"error_class": "identity_error", "message": "identity mismatch"}
    result["error"] = {"error_class": "identity_error", "message": "identity mismatch"}
    _rehash(result)
    with pytest.raises(OutcomeBackedContractError, match="transport mismatch must fail"):
        validate_result_record(result, manifest, packets["dev-00"])


@pytest.mark.parametrize("status", ["identity_error", "transport_error"])
def test_identity_and_transport_failures_require_recorded_mismatch(status: str) -> None:
    manifest, _, _, packets = _manifest()
    call = _call(
        case_id="dev-00",
        condition_id=CLAUDE_SINGLE,
        sequence=1,
        role="decision",
        family="claude",
        input_call_ids=[],
        normalized_output=None,
        status=status,
    )
    result = _result(manifest, "dev-00", CLAUDE_SINGLE, packets["dev-00"])
    result.update(
        calls=[call],
        output=None,
        receipt={"receipt_hash": None, "verification": "missing"},
        error={"error_class": status, "message": "sanitized failure"},
    )
    _rehash(result)

    with pytest.raises(OutcomeBackedContractError, match=f"{status} requires an observed"):
        validate_result_record(result, manifest, packets["dev-00"])


def test_clean_success_matches_frozen_identity_and_transport() -> None:
    manifest, _, _, packets = _manifest()
    result = _result(manifest, "dev-00", CLAUDE_SINGLE, packets["dev-00"])

    assert validate_result_record(result, manifest, packets["dev-00"])["billable_cost_usd"] == "0"


def test_single_success_cannot_self_attest_a_verified_receipt() -> None:
    manifest, _, _, packets = _manifest()
    result = _result(manifest, "dev-00", CLAUDE_SINGLE, packets["dev-00"])
    result["receipt"] = {"receipt_hash": "e" * 64, "verification": "verified"}
    _rehash(result)

    with pytest.raises(OutcomeBackedContractError, match="must not claim a receipt"):
        validate_result_record(result, manifest, packets["dev-00"])


def test_retry_is_allowed_only_after_infrastructure_error() -> None:
    manifest, _, _, packets = _manifest()
    result = _result(manifest, "dev-00", CLAUDE_SINGLE, packets["dev-00"])
    call = result["calls"][0]
    first = copy.deepcopy(call["attempts"][0])
    first.update(
        status="model_error",
        response_sha256=None,
        usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        provider_equivalent_cost_usd="0",
        error_class="model_error",
    )
    second = copy.deepcopy(call["attempts"][0])
    second["attempt"] = 2
    call["attempts"] = [first, second]
    call["usage"] = second["usage"]
    call["latency_ms"] = 20.0
    _rehash(result)

    with pytest.raises(OutcomeBackedContractError, match="only after infrastructure_error"):
        validate_result_record(result, manifest, packets["dev-00"])


def test_normalized_output_validates_options_forecasts_sources_and_shared_cruxes() -> None:
    output = _output()
    output["selected_option_id"] = "unknown"
    with pytest.raises(OutcomeBackedContractError, match="case option"):
        validate_normalized_output(output, option_ids=("yes", "no"), source_ids=("source-00",))

    output = _output()
    output["cruxes"] = ["one", "two"]
    with pytest.raises(OutcomeBackedContractError, match="must contain 3 to 5"):
        validate_normalized_output(output, option_ids=("yes", "no"), source_ids=("source-00",))


def test_rejects_unsanitized_errors_and_incomplete_batches() -> None:
    assert sanitize_error_message("token=secret-value failed") == "<redacted> failed"
    manifest, packet_set, plan, packets = _manifest()
    result = _result(manifest, "dev-00", CLAUDE_SINGLE, packets["dev-00"])
    result.update(output=None, error={"error_class": "model_error", "message": "token=secret"})
    result["calls"][0] = _call(
        case_id="dev-00",
        condition_id=CLAUDE_SINGLE,
        sequence=1,
        role="decision",
        family="claude",
        input_call_ids=[],
        normalized_output=None,
        status="model_error",
    )
    _rehash(result)
    with pytest.raises(OutcomeBackedContractError, match="must be sanitized"):
        validate_result_record(result, manifest, packets["dev-00"])

    records = [
        _result(manifest, "dev-00", condition_id, packets["dev-00"])
        for condition_id in CONDITION_IDS
    ]
    with pytest.raises(OutcomeBackedContractError, match="incomplete"):
        validate_result_batch(
            records,
            manifest,
            packet_set,
            plan,
            batch_id="development-01",
            packets_by_case=packets,
        )


def test_successful_team_result_requires_synthesis_call() -> None:
    manifest, _, _, packets = _manifest()
    result = _result(manifest, "dev-00", ARAGORA_TEAM, packets["dev-00"])
    result["calls"] = result["calls"][:-1]
    result["output"] = copy.deepcopy(result["calls"][2]["normalized_output"])
    _rehash(result)

    with pytest.raises(OutcomeBackedContractError, match="requires the synthesis call"):
        validate_result_record(result, manifest, packets["dev-00"])


def test_batch_rejects_packet_not_bound_to_frozen_packet_set() -> None:
    manifest, packet_set, plan, packets = _manifest()
    records = [
        _result(manifest, case_id, condition_id, packets[case_id])
        for case_id in ("dev-00", "dev-01", "dev-02", "dev-03")
        for condition_id in CONDITION_IDS
    ]
    substituted = copy.deepcopy(packets)
    substituted["dev-00"]["sources"][0]["text"] = "Substituted evidence"
    substituted["dev-00"]["packet_sha256"] = canonical_json_sha256(
        {key: value for key, value in substituted["dev-00"].items() if key != "packet_sha256"}
    )

    with pytest.raises(OutcomeBackedContractError, match="frozen packet set"):
        validate_result_batch(
            records,
            manifest,
            packet_set,
            plan,
            batch_id="development-01",
            packets_by_case=substituted,
        )
