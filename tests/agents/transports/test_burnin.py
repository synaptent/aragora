from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from aragora.agents.transports.burnin import (
    BurninRecorder,
    BurninRecordError,
    CallOutcome,
    PROOF_SCHEMA_VERSION,
    RECORD_SCHEMA_VERSION,
    build_proof_artifact,
    load_records,
    verify_family_identity,
)


def test_append_preserves_alias_disclosure_and_hash_chain(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    recorder = BurninRecorder(path)

    first = recorder.append(
        CallOutcome(
            family="claude",
            requested_model="claude-opus-4-8",
            resolved_model="anthropic/claude-opus-4.8",
            response_model="anthropic/claude-opus-4.8",
            alias_source="ARAGORA_VIBEPROXY_MODEL_MAP",
            latency_ms=125.25,
            ok=True,
        )
    )
    second = recorder.append(
        CallOutcome(
            family="openai",
            requested_model="gpt-5.5",
            resolved_model="gpt-5.5",
            response_model="gpt-5.5",
            latency_ms=44,
            ok=True,
        )
    )

    assert first["schema_version"] == RECORD_SCHEMA_VERSION
    assert first["countable"] is False
    assert first["alias_disclosure"] == {
        "applied": True,
        "source": "ARAGORA_VIBEPROXY_MODEL_MAP",
        "preserved": True,
    }
    assert first["clean"] is True
    assert second["previous_record_hash"] == first["record_hash"]
    assert load_records(path) == [first, second]


def test_append_round_trips_unexpected_alias_family(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    record = BurninRecorder(path).append(
        CallOutcome(
            family="openai",
            requested_model="gpt-5.4-mini-2026-03-17",
            resolved_model="gpt-5.4-mini-2026-03-17",
            response_model="gpt-5.4-mini-2026-03-17",
            alias_source="ARAGORA_VIBEPROXY_MODEL_MAP",
            alias_family="openai",
            latency_ms=10,
            ok=True,
        )
    )

    assert record["alias_disclosure"]["family"] == "openai"
    assert record["alias_disclosure"]["preserved"] is False
    assert record["clean"] is False
    assert record["error_class"] == "family_identity_error"
    assert record["identity_errors"] == ["unexpected_alias_family"]
    assert load_records(path) == [record]


def test_family_mismatch_is_recorded_fail_closed(tmp_path: Path) -> None:
    record = BurninRecorder(tmp_path / "calls.jsonl").append(
        CallOutcome(
            family="claude",
            requested_model="claude-opus-4-8",
            resolved_model="gpt-5.5",
            response_model="gpt-5.5",
            alias_source="ARAGORA_VIBEPROXY_MODEL_MAP",
            latency_ms=10,
            ok=True,
        )
    )

    assert record["clean"] is False
    assert record["family_identity_ok"] is False
    assert record["error_class"] == "family_identity_error"
    assert "resolved_model_family_mismatch" in record["identity_errors"]
    assert "response_model_family_mismatch" in record["identity_errors"]


def test_alias_requires_disclosure() -> None:
    identity_ok, alias_ok, errors = verify_family_identity(
        family="claude",
        requested_model="claude-opus-4-8",
        resolved_model="anthropic/claude-opus-4.8",
        response_model="anthropic/claude-opus-4.8",
        alias_source=None,
        ok=True,
    )

    assert identity_ok is False
    assert alias_ok is False
    assert errors == ("missing_alias_disclosure",)


def test_owner_bound_unknown_response_model_fails_closed() -> None:
    identity_ok, alias_ok, errors = verify_family_identity(
        family="kimi",
        requested_model="kimi-k2",
        resolved_model="k2",
        response_model="k2",
        alias_source="VibeProxy /v1/models owned_by=moonshot",
        alias_family="kimi",
        ok=True,
    )

    assert identity_ok is False
    assert alias_ok is True
    assert errors == (
        "resolved_model_family_mismatch",
        "response_model_family_mismatch",
    )


def test_owner_binding_cannot_override_known_cross_family_response() -> None:
    identity_ok, alias_ok, errors = verify_family_identity(
        family="grok",
        requested_model="grok-3-mini-fast",
        resolved_model="gpt-5.5",
        response_model="gpt-5.5",
        alias_source="VibeProxy /v1/models owned_by=xai",
        alias_family="grok",
        ok=True,
    )

    assert identity_ok is False
    assert alias_ok is True
    assert "resolved_model_family_mismatch" in errors
    assert "response_model_family_mismatch" in errors


def test_refuses_to_append_to_damaged_log(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    path.write_text('{"schema_version":"tampered"}\n', encoding="utf-8")

    with pytest.raises(BurninRecordError, match="invalid record hash"):
        BurninRecorder(path).append(
            CallOutcome(
                family="claude",
                requested_model="claude-opus-4-8",
                resolved_model="claude-opus-4-8",
                response_model="claude-opus-4-8",
                latency_ms=1,
                ok=True,
            )
        )


def test_proof_artifact_meets_exact_issue_9409_thresholds(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    recorder = BurninRecorder(path)
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    family_models = (
        ("claude", "claude-opus-4-8"),
        ("openai", "gpt-5.5"),
        ("gemini", "gemini-3.1-pro-preview"),
    )
    for index in range(100):
        family, model = family_models[index % len(family_models)]
        shadow = index < 20
        recorder.append(
            CallOutcome(
                family=family,
                requested_model=model,
                resolved_model=model,
                response_model=model,
                latency_ms=50 + index,
                ok=True,
                call_kind="shadow_review" if shadow else "inference",
                pr_number=9000 + index if shadow else None,
                pr_head_sha=f"{'a' * 39}{index % 10}" if shadow else None,
                head_stable=True if shadow else None,
                review_verdict="PASS" if shadow else None,
                review_digest=f"{'b' * 63}{index % 10}" if shadow else None,
                recorded_at=start + timedelta(days=7 * index / 99),
            )
        )

    artifact = build_proof_artifact(
        load_records(path), source_path=path, generated_at=start + timedelta(days=8)
    )

    assert artifact["schema_version"] == PROOF_SCHEMA_VERSION
    assert artifact["issue"] == 9409
    assert artifact["transport_prerequisite_pr"] == 9483
    assert artifact["total_records"] == 100
    assert artifact["ready"] is True
    assert artifact["gates"] == {
        "seven_day_span": {"required": 7, "observed": 7.0, "met": True},
        "clean_calls": {"required": 100, "observed": 100, "met": True},
        "provider_families": {
            "required": 3,
            "observed": 3,
            "families": ["claude", "gemini", "openai"],
            "met": True,
        },
        "credential_errors": {"required_maximum": 0, "observed": 0, "met": True},
        "family_identity_errors": {
            "required_maximum": 0,
            "observed": 0,
            "met": True,
        },
        "shadow_reviews": {"required": 20, "observed": 20, "met": True},
    }


def test_proof_counts_identity_and_credential_errors(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    recorder = BurninRecorder(path)
    recorder.append(
        CallOutcome(
            family="claude",
            requested_model="claude-opus-4-8",
            resolved_model="claude-opus-4-8",
            response_model=None,
            latency_ms=1,
            ok=False,
            error_class="http_401",
        )
    )
    recorder.append(
        CallOutcome(
            family="claude",
            requested_model="claude-opus-4-8",
            resolved_model="gpt-5.5",
            response_model="gpt-5.5",
            alias_source="map",
            latency_ms=1,
            ok=True,
        )
    )

    artifact = build_proof_artifact(load_records(path), source_path=path)

    assert artifact["ready"] is False
    assert artifact["gates"]["credential_errors"]["observed"] == 1
    assert artifact["gates"]["family_identity_errors"]["observed"] == 1


def test_log_is_plain_jsonl_with_no_reviewer_body(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    BurninRecorder(path).append(
        CallOutcome(
            family="claude",
            requested_model="claude-opus-4-8",
            resolved_model="claude-opus-4-8",
            response_model="claude-opus-4-8",
            latency_ms=1,
            ok=True,
            call_kind="shadow_review",
            pr_number=9409,
            pr_head_sha="a" * 40,
            head_stable=True,
            review_verdict="PASS",
            review_digest="b" * 64,
        )
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["shadow_review"]["posted"] is False
    assert payload["shadow_review"]["evidence_composed"] is False
    assert "body" not in payload["shadow_review"]
