"""Canonical DecisionReceipt binding for outcome-backed team results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any

from aragora.evaluation.outcome_backed_conditions import ARAGORA_TEAM
from aragora.evaluation.outcome_backed_corpus import BENCHMARK_ID
from aragora.gauntlet.receipt_models import (
    RECEIPT_SCHEMA_VERSION_EVIDENCE,
    DecisionReceipt,
)


TEAM_RECEIPT_BINDING_SCHEMA = "outcome-backed-team-receipt-binding/1.0"
RECEIPT_VERIFIED = "verified"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SPLITS = frozenset({"development", "holdout"})


class OutcomeBackedReceiptError(ValueError):
    """Raised when a team receipt cannot be created or verified fail-closed."""


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OutcomeBackedReceiptError(f"{field} must be a non-empty string")
    return value


def _sha256(value: object, field: str) -> str:
    text = _required_text(value, field)
    if not _SHA256_RE.fullmatch(text):
        raise OutcomeBackedReceiptError(f"{field} must be a lowercase SHA-256")
    return text


@dataclass(frozen=True)
class OutcomeBackedReceiptBinding:
    """Frozen execution inputs that a team DecisionReceipt must bind.

    ``result_sha256`` is the digest of the successful benchmark result payload
    before its receipt reference is attached. Keeping that digest external to
    the receipt avoids a circular hash while still letting an independent
    verifier bind the receipt to the exact execution record.
    """

    case_id: str
    split: str
    repetition: int
    manifest_sha256: str
    implementation_sha: str
    packet_sha256: str
    packet_set_sha256: str
    prompt_sha256: str
    roster_sha256: str
    result_sha256: str
    benchmark_id: str = BENCHMARK_ID
    condition_id: str = ARAGORA_TEAM

    def validate(self) -> None:
        if self.benchmark_id != BENCHMARK_ID:
            raise OutcomeBackedReceiptError("binding benchmark_id does not match the benchmark")
        if self.condition_id != ARAGORA_TEAM:
            raise OutcomeBackedReceiptError(
                "only the frozen Aragora team condition may mint a team receipt"
            )
        _required_text(self.case_id, "binding.case_id")
        if self.split not in _SPLITS:
            raise OutcomeBackedReceiptError("binding.split must be development or holdout")
        if isinstance(self.repetition, bool) or not isinstance(self.repetition, int):
            raise OutcomeBackedReceiptError("binding.repetition must be an integer")
        maximum_repetition = 1 if self.split == "development" else 2
        if not 1 <= self.repetition <= maximum_repetition:
            raise OutcomeBackedReceiptError(
                f"binding.repetition must be between 1 and {maximum_repetition} for {self.split}"
            )
        if not _GIT_SHA_RE.fullmatch(self.implementation_sha):
            raise OutcomeBackedReceiptError(
                "binding.implementation_sha must be a 40-character lowercase Git SHA"
            )
        for field in (
            "manifest_sha256",
            "packet_sha256",
            "packet_set_sha256",
            "prompt_sha256",
            "roster_sha256",
            "result_sha256",
        ):
            _sha256(getattr(self, field), f"binding.{field}")

    def to_dict(self) -> dict[str, str | int]:
        self.validate()
        return {
            "schema_version": TEAM_RECEIPT_BINDING_SCHEMA,
            "benchmark_id": self.benchmark_id,
            "case_id": self.case_id,
            "split": self.split,
            "repetition": self.repetition,
            "condition_id": self.condition_id,
            "manifest_sha256": self.manifest_sha256,
            "implementation_sha": self.implementation_sha,
            "packet_sha256": self.packet_sha256,
            "packet_set_sha256": self.packet_set_sha256,
            "prompt_sha256": self.prompt_sha256,
            "roster_sha256": self.roster_sha256,
            "result_sha256": self.result_sha256,
        }


@dataclass(frozen=True)
class VerifiedOutcomeBackedReceipt:
    """Serialized receipt plus the compact reference expected by result rows."""

    receipt: dict[str, Any]
    receipt_hash: str
    verification: str = RECEIPT_VERIFIED

    def result_reference(self) -> dict[str, str]:
        return {"hash": self.receipt_hash, "verification": self.verification}


def _decision_payload(binding: OutcomeBackedReceiptBinding) -> dict[str, object]:
    return {
        "schema_version": TEAM_RECEIPT_BINDING_SCHEMA,
        "benchmark_binding": binding.to_dict(),
    }


def verify_team_receipt(
    receipt_data: Mapping[str, Any],
    *,
    expected_binding: OutcomeBackedReceiptBinding,
) -> VerifiedOutcomeBackedReceipt:
    """Independently round-trip and verify one benchmark team receipt."""

    expected_binding.validate()
    try:
        receipt = DecisionReceipt.from_dict(dict(receipt_data))
    except (TypeError, ValueError) as exc:
        raise OutcomeBackedReceiptError(f"receipt cannot be decoded: {exc}") from exc

    if receipt.schema_version != RECEIPT_SCHEMA_VERSION_EVIDENCE:
        raise OutcomeBackedReceiptError("receipt must use the evidence-linked schema")
    if not receipt.verify_integrity():
        raise OutcomeBackedReceiptError("receipt integrity verification failed")
    if receipt.input_hash != expected_binding.prompt_sha256:
        raise OutcomeBackedReceiptError("receipt input_hash does not bind the exact prompt")
    if receipt.decision_payload != _decision_payload(expected_binding):
        raise OutcomeBackedReceiptError(
            "receipt decision payload does not match the expected binding"
        )
    if receipt.verdict not in {"PASS", "CONDITIONAL"}:
        raise OutcomeBackedReceiptError("team receipt does not contain a successful verdict")
    if receipt.consensus_proof is None or receipt.consensus_proof.reached is not True:
        raise OutcomeBackedReceiptError("team receipt does not prove consensus")
    if not _SHA256_RE.fullmatch(receipt.artifact_hash):
        raise OutcomeBackedReceiptError("receipt artifact_hash must be a lowercase SHA-256")

    serialized = receipt.to_dict()
    return VerifiedOutcomeBackedReceipt(
        receipt=serialized,
        receipt_hash=receipt.artifact_hash,
    )


def build_team_receipt(
    debate_result: Any,
    *,
    binding: OutcomeBackedReceiptBinding,
    cost_summary: dict[str, Any] | None = None,
) -> VerifiedOutcomeBackedReceipt:
    """Create and independently verify a canonical receipt for a team result."""

    binding.validate()
    if not bool(getattr(debate_result, "consensus_reached", False)):
        raise OutcomeBackedReceiptError("team result must reach consensus before receipt creation")

    receipt = DecisionReceipt.from_debate_result(
        debate_result,
        input_hash=binding.prompt_sha256,
        cost_summary=cost_summary,
        decision_payload=_decision_payload(binding),
    )
    return verify_team_receipt(receipt.to_dict(), expected_binding=binding)


__all__ = [
    "RECEIPT_VERIFIED",
    "TEAM_RECEIPT_BINDING_SCHEMA",
    "OutcomeBackedReceiptBinding",
    "OutcomeBackedReceiptError",
    "VerifiedOutcomeBackedReceipt",
    "build_team_receipt",
    "verify_team_receipt",
]
