from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from aragora.core_types import DebateResult
from aragora.debate.execution_safety import (
    ExecutionSafetyPolicy,
    evaluate_auto_execution_safety,
)


def _make_result() -> DebateResult:
    return DebateResult(
        debate_id="debate-safe-001",
        task="Design a secure deployment plan",
        final_answer="Use staged rollout with explicit rollback and monitoring.",
        confidence=0.86,
        consensus_reached=True,
        rounds_used=3,
        rounds_completed=3,
        participants=["a1", "a2"],
        metadata={},
    )


def test_allows_auto_execution_for_signed_diverse_consensus() -> None:
    result = _make_result()
    agents = [
        SimpleNamespace(name="claude", model="claude-opus-4-1", agent_type="anthropic-api"),
        SimpleNamespace(name="gpt", model="gpt-4.1", agent_type="openai-api"),
    ]
    policy = ExecutionSafetyPolicy(
        require_verified_signed_receipt=True,
        min_provider_diversity=2,
        min_model_family_diversity=2,
    )

    decision = evaluate_auto_execution_safety(result, agents=agents, policy=policy)

    assert decision.allow_auto_execution is True
    assert decision.receipt_signed is True
    assert decision.receipt_integrity_valid is True
    assert decision.receipt_signature_valid is True
    assert decision.provider_diversity >= 2
    assert decision.model_family_diversity >= 2


def test_blocks_obliteratus_style_low_diversity_ensemble() -> None:
    result = _make_result()
    # Simulate compromised homogeneous open-weight ensemble.
    agents = [
        SimpleNamespace(
            name="llama_a", model="meta-llama/llama-3.3-70b-instruct", agent_type="openrouter"
        ),
        SimpleNamespace(
            name="llama_b", model="meta-llama/llama-3.3-70b-instruct", agent_type="openrouter"
        ),
        SimpleNamespace(
            name="llama_c", model="meta-llama/llama-3.3-70b-instruct", agent_type="openrouter"
        ),
    ]
    policy = ExecutionSafetyPolicy(
        require_verified_signed_receipt=True,
        min_provider_diversity=2,
        min_model_family_diversity=2,
    )

    decision = evaluate_auto_execution_safety(result, agents=agents, policy=policy)

    assert decision.allow_auto_execution is False
    assert "provider_diversity_below_minimum" in decision.reason_codes
    assert "model_family_diversity_below_minimum" in decision.reason_codes


def test_blocks_brainworm_style_context_taint_signal() -> None:
    result = _make_result()
    result.metadata = {
        "context_taint_detected": True,
        "context_taint_patterns": ["ignore_previous_instructions"],
    }
    agents = [
        SimpleNamespace(name="claude", model="claude-opus-4-1", agent_type="anthropic-api"),
        SimpleNamespace(name="gpt", model="gpt-4.1", agent_type="openai-api"),
    ]
    policy = ExecutionSafetyPolicy(block_on_context_taint=True)

    decision = evaluate_auto_execution_safety(result, agents=agents, policy=policy)

    assert decision.allow_auto_execution is False
    assert decision.context_taint_detected is True
    assert "tainted_context_detected" in decision.reason_codes


@pytest.mark.parametrize(
    ("signed_at", "expected_reason"),
    [
        ("", "receipt_missing_signed_timestamp"),
        (
            (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            "receipt_stale",
        ),
        (
            (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            "receipt_timestamp_in_future",
        ),
    ],
)
def test_receipt_timestamp_guards_block_untrusted_receipts(
    monkeypatch: pytest.MonkeyPatch,
    signed_at: str,
    expected_reason: str,
) -> None:
    result = _make_result()
    agents = [
        SimpleNamespace(name="claude", model="claude-opus-4-1", agent_type="anthropic-api"),
        SimpleNamespace(name="gpt", model="gpt-4.1", agent_type="openai-api"),
    ]
    policy = ExecutionSafetyPolicy(
        require_signed_receipt_timestamp=True,
        receipt_max_age_seconds=300,
        receipt_max_future_skew_seconds=60,
        min_provider_diversity=2,
        min_model_family_diversity=2,
    )

    fake_receipt = SimpleNamespace(
        receipt_id="r-1",
        signature_key_id="hmac-test-key",
        signed_at=signed_at,
        to_dict=lambda: {"receipt_id": "r-1"},
    )
    monkeypatch.setattr(
        "aragora.debate.execution_safety._build_signed_receipt",
        lambda _result: (fake_receipt, True, True, True),
    )

    decision = evaluate_auto_execution_safety(result, agents=agents, policy=policy)

    assert decision.allow_auto_execution is False
    assert expected_reason in decision.reason_codes


def test_receipt_signer_allowlist_blocks_unapproved_key(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _make_result()
    agents = [
        SimpleNamespace(name="claude", model="claude-opus-4-1", agent_type="anthropic-api"),
        SimpleNamespace(name="gpt", model="gpt-4.1", agent_type="openai-api"),
    ]
    policy = ExecutionSafetyPolicy(
        require_receipt_signer_allowlist=True,
        allowed_receipt_signer_keys=("hmac-approved",),
        min_provider_diversity=2,
        min_model_family_diversity=2,
    )

    fake_receipt = SimpleNamespace(
        receipt_id="r-2",
        signature_key_id="hmac-rotated-but-unapproved",
        signed_at=datetime.now(timezone.utc).isoformat(),
        to_dict=lambda: {"receipt_id": "r-2"},
    )
    monkeypatch.setattr(
        "aragora.debate.execution_safety._build_signed_receipt",
        lambda _result: (fake_receipt, True, True, True),
    )

    decision = evaluate_auto_execution_safety(result, agents=agents, policy=policy)

    assert decision.allow_auto_execution is False
    assert "receipt_signer_not_allowlisted" in decision.reason_codes
