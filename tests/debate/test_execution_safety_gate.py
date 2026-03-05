from __future__ import annotations

from types import SimpleNamespace

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
