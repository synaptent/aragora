from __future__ import annotations

from copy import deepcopy

import pytest

from aragora.core_types import DebateResult, Message
from aragora.evaluation.outcome_backed_conditions import ARAGORA_TEAM
from aragora.evaluation.outcome_backed_corpus import BENCHMARK_ID
from aragora.evaluation.outcome_backed_receipt import (
    TEAM_RECEIPT_BINDING_SCHEMA,
    OutcomeBackedReceiptBinding,
    OutcomeBackedReceiptError,
    build_team_receipt,
    verify_team_receipt,
)


def _binding(**overrides: object) -> OutcomeBackedReceiptBinding:
    values: dict[str, object] = {
        "case_id": "se-dev-01",
        "split": "development",
        "repetition": 1,
        "manifest_sha256": "1" * 64,
        "implementation_sha": "2" * 40,
        "packet_sha256": "3" * 64,
        "packet_set_sha256": "4" * 64,
        "prompt_sha256": "5" * 64,
        "roster_sha256": "6" * 64,
        "result_sha256": "7" * 64,
    }
    values.update(overrides)
    return OutcomeBackedReceiptBinding(**values)  # type: ignore[arg-type]


def _team_result(*, final_answer: str | None = None, consensus: bool = True) -> DebateResult:
    answer = final_answer or (
        '{"case_id":"se-dev-01","selected_option_id":"option-a",'
        '"probability_forecast":{"option_id":"option-a","probability":0.72}}'
    )
    participants = ["claude", "openai", "gemini"]
    return DebateResult(
        debate_id="outcome-backed-se-dev-01",
        task="Choose one action using only the frozen source packet.",
        final_answer=answer,
        confidence=0.82,
        consensus_reached=consensus,
        rounds_used=1,
        participants=participants,
        messages=[
            Message(role="proposal", agent=agent, content=f"{agent} supports option A.")
            for agent in participants
        ],
        proposals={agent: f"{agent} proposal" for agent in participants},
        winner="openai",
    )


def test_builds_canonical_verified_team_receipt() -> None:
    binding = _binding()

    proof = build_team_receipt(_team_result(), binding=binding)

    assert proof.verification == "verified"
    assert proof.result_reference() == {
        "hash": proof.receipt_hash,
        "verification": "verified",
    }
    assert proof.receipt["artifact_hash"] == proof.receipt_hash
    assert proof.receipt["input_hash"] == binding.prompt_sha256
    assert proof.receipt["decision_payload"] == {
        "schema_version": TEAM_RECEIPT_BINDING_SCHEMA,
        "benchmark_binding": binding.to_dict(),
    }
    assert proof.receipt["decision_payload_hash"]


def test_independent_round_trip_verifies_the_same_receipt() -> None:
    binding = _binding()
    built = build_team_receipt(_team_result(), binding=binding)

    verified = verify_team_receipt(deepcopy(built.receipt), expected_binding=binding)

    assert verified.receipt_hash == built.receipt_hash
    assert verified.receipt == built.receipt


def test_tampered_binding_fails_integrity_verification() -> None:
    binding = _binding()
    built = build_team_receipt(_team_result(), binding=binding)
    tampered = deepcopy(built.receipt)
    tampered["decision_payload"]["benchmark_binding"]["case_id"] = "tampered"

    with pytest.raises(OutcomeBackedReceiptError, match="integrity verification failed"):
        verify_team_receipt(tampered, expected_binding=binding)


def test_wrong_expected_execution_binding_is_rejected() -> None:
    built = build_team_receipt(_team_result(), binding=_binding())

    with pytest.raises(OutcomeBackedReceiptError, match="does not match the expected binding"):
        verify_team_receipt(
            built.receipt,
            expected_binding=_binding(result_sha256="8" * 64),
        )


@pytest.mark.parametrize("reached", ["false", "true", 1])
def test_non_boolean_consensus_proof_is_rejected(reached: object) -> None:
    binding = _binding()
    built = build_team_receipt(_team_result(), binding=binding)
    tampered = deepcopy(built.receipt)
    tampered["consensus_proof"]["reached"] = reached

    with pytest.raises(OutcomeBackedReceiptError, match="does not prove consensus"):
        verify_team_receipt(tampered, expected_binding=binding)


def test_zero_evidence_and_non_consensus_results_fail_closed() -> None:
    placeholder = _team_result(final_answer="anthropic-api got confused and needs to recalibrate.")
    placeholder.messages = []
    placeholder.proposals = {}
    with pytest.raises(OutcomeBackedReceiptError, match="successful verdict"):
        build_team_receipt(placeholder, binding=_binding())

    with pytest.raises(OutcomeBackedReceiptError, match="must reach consensus"):
        build_team_receipt(_team_result(consensus=False), binding=_binding())


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"benchmark_id": "other"}, "benchmark_id"),
        ({"condition_id": "claude-single"}, "Aragora team condition"),
        ({"split": "other"}, "development or holdout"),
        ({"repetition": 2}, "between 1 and 1"),
        ({"implementation_sha": "not-a-sha"}, "implementation_sha"),
        ({"prompt_sha256": "not-a-hash"}, "prompt_sha256"),
    ],
)
def test_invalid_bindings_are_rejected(overrides: dict[str, object], message: str) -> None:
    binding = _binding(**overrides)

    with pytest.raises(OutcomeBackedReceiptError, match=message):
        build_team_receipt(_team_result(), binding=binding)


def test_binding_defaults_to_frozen_benchmark_and_team_condition() -> None:
    binding = _binding(split="holdout", repetition=2)

    assert binding.benchmark_id == BENCHMARK_ID
    assert binding.condition_id == ARAGORA_TEAM
    assert binding.to_dict()["schema_version"] == TEAM_RECEIPT_BINDING_SCHEMA
