"""Unit tests for the ExecutableClaim manifest model (DIC-13 / #6023)."""

from __future__ import annotations
from pathlib import Path

import pytest

from aragora.epistemic.executable_claim import (
    ClaimConfidence,
    ClaimEvidence,
    ClaimFailurePolicy,
    ClaimManifest,
    ClaimReceipt,
    ClaimTruthState,
    ClaimTruthStatus,
    ClaimVerification,
    ExecutableClaim,
    FailureAction,
    FailureSeverity,
    VerificationKind,
    load_claims_from_dir,
)

REPO_ROOT = Path(__file__).parent.parent.parent
CLAIMS_DIR = REPO_ROOT / "docs" / "status" / "claims"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal() -> dict:
    return {
        "claim_id": "test.claim.one",
        "statement": "Tests are passing.",
        "owner": "test-suite",
        "scope": "repo",
        "confidence": "high",
        "evidence": [{"path": "tests/epistemic/test_executable_claim.py"}],
        "freshness_sla_hours": 24,
        "verification": {"kind": "command", "command": "pytest tests/epistemic/ -q"},
        "failure": {"severity": "info", "allowed_action": "report_only"},
        "receipts": [{"type": "test_run"}],
    }


# ---------------------------------------------------------------------------
# ClaimEvidence
# ---------------------------------------------------------------------------


def test_evidence_requires_one_field() -> None:
    with pytest.raises(ValueError, match="at least one"):
        ClaimEvidence()


def test_evidence_round_trip() -> None:
    d = {"path": "docs/status/B0.md", "workflow": "BTP"}
    assert ClaimEvidence.from_dict(d).to_dict() == d


def test_evidence_issue_field() -> None:
    assert ClaimEvidence(issue=6023).to_dict() == {"issue": 6023}


# ---------------------------------------------------------------------------
# ClaimVerification
# ---------------------------------------------------------------------------


def test_verification_round_trip() -> None:
    v = ClaimVerification.from_dict({"kind": "command", "command": "pytest -q"})
    assert v.kind == VerificationKind.COMMAND
    assert "expected_result" not in v.to_dict()


def test_verification_unknown_kind_raises() -> None:
    with pytest.raises(ValueError):
        ClaimVerification.from_dict({"kind": "unknown", "command": "ls"})


# ---------------------------------------------------------------------------
# ClaimFailurePolicy
# ---------------------------------------------------------------------------


def test_failure_policy_round_trip() -> None:
    fp = ClaimFailurePolicy.from_dict(
        {"severity": "blocking", "allowed_action": "report_only", "repair_note": "Fix it."}
    )
    assert fp.severity == FailureSeverity.BLOCKING
    assert fp.to_dict()["repair_note"] == "Fix it."
    fp2 = ClaimFailurePolicy.from_dict({"severity": "info", "allowed_action": "report_only"})
    assert "repair_note" not in fp2.to_dict()


# ---------------------------------------------------------------------------
# ClaimReceipt
# ---------------------------------------------------------------------------


def test_receipt_round_trip_and_missing_type() -> None:
    r = ClaimReceipt.from_dict({"type": "benchmark_truth", "path": "docs/status/foo.json"})
    assert r.to_dict() == {"type": "benchmark_truth", "path": "docs/status/foo.json"}
    with pytest.raises(KeyError):
        ClaimReceipt.from_dict({})


# ---------------------------------------------------------------------------
# ExecutableClaim
# ---------------------------------------------------------------------------


def test_claim_round_trip() -> None:
    claim = ExecutableClaim.from_dict(_minimal())
    assert claim.confidence == ClaimConfidence.HIGH
    assert claim.freshness_sla_hours == 24
    assert claim.to_dict()["confidence"] == "high"


def test_claim_truth_status_is_optional_and_round_trips() -> None:
    claim = ExecutableClaim.from_dict(
        {
            **_minimal(),
            "truth_status": {
                "state": "live",
                "last_verified_at": "2026-07-11T06:30:00Z",
                "note": "Checked locally.",
            },
        }
    )
    assert claim.truth_status == ClaimTruthStatus(
        state=ClaimTruthState.LIVE,
        last_verified_at="2026-07-11T06:30:00Z",
        note="Checked locally.",
    )
    assert claim.to_dict()["truth_status"]["state"] == "live"
    assert "truth_status" not in ExecutableClaim.from_dict(_minimal()).to_dict()


def test_live_truth_status_requires_timezone_aware_verification_time() -> None:
    with pytest.raises(ValueError, match="requires last_verified_at"):
        ClaimTruthStatus(state=ClaimTruthState.LIVE)
    with pytest.raises(ValueError, match="include a timezone"):
        ClaimTruthStatus(
            state=ClaimTruthState.LIVE,
            last_verified_at="2026-07-11T06:30:00",
        )


def test_claim_validation_errors() -> None:
    with pytest.raises(ValueError, match="claim_id"):
        ExecutableClaim.from_dict({**_minimal(), "claim_id": ".bad"})
    with pytest.raises(ValueError, match="statement"):
        ExecutableClaim.from_dict({**_minimal(), "statement": ""})
    with pytest.raises(ValueError, match="freshness"):
        ExecutableClaim.from_dict({**_minimal(), "freshness_sla_hours": 0})


def test_claim_missing_required_field_raises() -> None:
    d = _minimal()
    del d["owner"]
    with pytest.raises(KeyError):
        ExecutableClaim.from_dict(d)


# ---------------------------------------------------------------------------
# ClaimManifest
# ---------------------------------------------------------------------------


def test_manifest_round_trip_and_bad_version() -> None:
    m = ClaimManifest.from_dict(
        {"schema_version": 1, "manifest_id": "test", "description": "D", "claims": [_minimal()]}
    )
    assert m.manifest_id == "test"
    assert m.to_dict()["description"] == "D"
    with pytest.raises(ValueError, match="schema_version"):
        ClaimManifest.from_dict({"schema_version": 2, "manifest_id": "x", "claims": []})


def test_manifest_from_real_yaml() -> None:
    """Smoke-test against the committed proof_first_claims.yaml."""
    m = ClaimManifest.from_yaml_file(CLAIMS_DIR / "proof_first_claims.yaml")
    assert m.schema_version == 1
    assert m.manifest_id == "proof_first_claims"
    assert m.claims[0].confidence == ClaimConfidence.HIGH
    assert m.claims[0].freshness_sla_hours >= 1


# ---------------------------------------------------------------------------
# Flag gate and directory scanner
# ---------------------------------------------------------------------------


def test_load_claims_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARAGORA_EPISTEMIC_CLAIMS_ENABLED", raising=False)
    assert load_claims_from_dir(CLAIMS_DIR) == []


def test_load_claims_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARAGORA_EPISTEMIC_CLAIMS_ENABLED", "1")
    result = load_claims_from_dir(CLAIMS_DIR)
    assert len(result) >= 1
    assert {manifest.manifest_id for manifest in result} >= {"proof_first_claims"}


def test_load_claims_accepts_true_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARAGORA_EPISTEMIC_CLAIMS_ENABLED", "true")
    result = load_claims_from_dir(CLAIMS_DIR)
    assert {manifest.manifest_id for manifest in result} >= {"proof_first_claims"}
