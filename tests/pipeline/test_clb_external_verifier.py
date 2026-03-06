"""Tests for CLB-012: external-verifier insertion point for high-impact actions."""

from __future__ import annotations

import pytest

from aragora.pipeline.external_verifier import (
    ExternalVerificationResult,
    ExternalVerifier,
    HighImpactPolicy,
    requires_external_verification,
)


def test_requires_external_verification_true_for_high_impact() -> None:
    """CLB-012: High-impact action triggers external verification requirement."""
    action = {"type": "deploy", "scope": "production", "files_changed": 50}
    assert requires_external_verification(action) is True


def test_requires_external_verification_false_for_low_impact() -> None:
    """CLB-012: Low-impact action does not require external verification."""
    action = {"type": "doc_update", "scope": "internal", "files_changed": 1}
    assert requires_external_verification(action) is False


def test_requires_external_verification_respects_policy_threshold() -> None:
    """CLB-012: Custom policy threshold controls the high-impact boundary."""
    policy = HighImpactPolicy(files_changed_threshold=5)
    action = {"type": "refactor", "scope": "internal", "files_changed": 6}
    assert requires_external_verification(action, policy=policy) is True

    action_low = {"type": "refactor", "scope": "internal", "files_changed": 3}
    assert requires_external_verification(action_low, policy=policy) is False


def test_external_verification_result_approved() -> None:
    """CLB-012: Approved result carries verdict and verifier identity."""
    result = ExternalVerificationResult(
        verifier_id="ci-gate",
        verdict="approved",
        rationale="All checks passed",
    )
    assert result.approved is True
    assert result.to_policy_dict()["external_verifier"] == "ci-gate"
    assert result.to_policy_dict()["verdict"] == "approved"


def test_external_verification_result_rejected() -> None:
    """CLB-012: Rejected result marks approved as False."""
    result = ExternalVerificationResult(
        verifier_id="security-scan",
        verdict="rejected",
        rationale="Vulnerability detected",
    )
    assert result.approved is False
    assert result.to_policy_dict()["allowed"] is False


def test_external_verifier_passthrough_when_not_high_impact() -> None:
    """CLB-012: Verifier approves immediately when action is not high-impact."""
    verifier = ExternalVerifier()
    action = {"type": "doc_update", "scope": "internal", "files_changed": 1}
    result = verifier.check(action)
    assert result.approved is True
    assert result.verdict == "not_required"


def test_external_verifier_invokes_hook_for_high_impact() -> None:
    """CLB-012: Verifier invokes the registered hook for high-impact actions."""
    hook_calls = []

    def my_hook(action: dict) -> ExternalVerificationResult:
        hook_calls.append(action)
        return ExternalVerificationResult(verifier_id="my-hook", verdict="approved")

    verifier = ExternalVerifier(hook=my_hook)
    action = {"type": "deploy", "scope": "production", "files_changed": 50}
    result = verifier.check(action)

    assert len(hook_calls) == 1
    assert result.approved is True


def test_external_verifier_no_hook_defaults_pending_for_high_impact() -> None:
    """CLB-012: Without a hook, high-impact actions get verdict=pending."""
    verifier = ExternalVerifier()
    action = {"type": "deploy", "scope": "production", "files_changed": 50}
    result = verifier.check(action)
    assert result.verdict == "pending"
    assert result.approved is False


def test_receipt_envelope_carries_external_verification() -> None:
    """CLB-012: policy_gate_result in ReceiptEnvelope carries verifier identity and verdict."""
    from aragora.pipeline.backbone_contracts import ReceiptEnvelope

    verifier_result = ExternalVerificationResult(
        verifier_id="pipeline-gate",
        verdict="approved",
        rationale="Budget within limits",
    )

    receipt = {
        "receipt_id": "r-verify-001",
        "pipeline_id": "pipe-verify",
        "content_hash": "abc",
        "provenance": {},
        "execution": {"status": "completed"},
    }

    envelope = ReceiptEnvelope.from_pipeline_receipt(
        receipt,
        policy_gate_result=verifier_result.to_policy_dict(),
    )

    assert envelope.policy_gate_result["external_verifier"] == "pipeline-gate"
    assert envelope.policy_gate_result["verdict"] == "approved"
    assert envelope.policy_gate_result["allowed"] is True
