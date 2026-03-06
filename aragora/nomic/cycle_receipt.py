"""
Signed receipts for Nomic self-improvement cycles.

Provides cryptographic audit trails for every self-improvement cycle,
recording what changed, who approved it, quality deltas, and cost.

Each NomicCycleReceipt is:
- Content-addressed via SHA-256 artifact hash
- Signable via ReceiptSigner (HMAC-SHA256, RSA, Ed25519)
- Round-trippable through to_dict / from_dict for JSONL persistence

Part of Epic #295 Stream 1: Signed receipts for self-improvement audit.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.gauntlet.signing import ReceiptSigner


@dataclass
class ApprovalRecord:
    """A single approval gate decision during a Nomic cycle.

    Captures who approved (or rejected) at each gate in the
    self-improvement pipeline, providing a full audit chain.
    """

    gate_id: str
    gate_type: str  # "plan_approval", "review_gate", "merge_gate"
    approver: str
    decision: str  # "approved", "rejected", "skipped"
    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "gate_type": self.gate_type,
            "approver": self.approver,
            "decision": self.decision,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRecord:
        return cls(
            gate_id=data["gate_id"],
            gate_type=data["gate_type"],
            approver=data["approver"],
            decision=data["decision"],
            timestamp=data["timestamp"],
            metadata=data.get("metadata", {}),
        )


@dataclass
class NomicCycleReceipt:
    """Audit-ready receipt for a Nomic self-improvement cycle.

    Contains:
    - Cycle identification and goal
    - Track execution summary (subtasks completed/failed)
    - Code changes (files, commits, branches)
    - Quality metrics before/after with delta
    - Cost tracking in USD
    - Full approval chain from every gate
    - Safety checks (gauntlet, canary tokens, output validation)
    - Content-addressable artifact hash
    - Optional cryptographic signature

    Example::

        receipt = NomicCycleReceipt(
            receipt_id="nr-abc123",
            cycle_id="cycle-001",
            goal="Improve test coverage",
            tracks_executed=["qa"],
            subtasks_completed=3,
            subtasks_failed=0,
            files_changed=["aragora/foo.py"],
            commit_shas=["deadbeef"],
            branch_names=["nomic/improve-coverage"],
            quality_before={"test_coverage": 0.80},
            quality_after={"test_coverage": 0.85},
            quality_delta=0.05,
            cost_usd=0.42,
        )
        assert receipt.verify_integrity()
    """

    # Identification
    receipt_id: str
    cycle_id: str
    timestamp: str = ""
    goal: str = ""

    # Execution summary
    tracks_executed: list[str] = field(default_factory=list)
    subtasks_completed: int = 0
    subtasks_failed: int = 0

    # Code changes
    files_changed: list[str] = field(default_factory=list)
    commit_shas: list[str] = field(default_factory=list)
    branch_names: list[str] = field(default_factory=list)

    # Quality metrics
    quality_before: dict[str, Any] = field(default_factory=dict)
    quality_after: dict[str, Any] = field(default_factory=dict)
    quality_delta: float = 0.0

    # Cost
    cost_usd: float = 0.0

    # Approval chain
    approval_records: list[ApprovalRecord] = field(default_factory=list)

    # Safety checks
    gauntlet_verdict: str | None = None
    canary_token_clean: bool = True
    output_validation_passed: bool = True

    # Integrity
    artifact_hash: str = ""
    schema_version: str = "1.0"

    # Signature fields
    signature: str | None = None
    signature_algorithm: str | None = None
    signed_at: str | None = None

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.artifact_hash:
            self.artifact_hash = self._calculate_hash()

    def _calculate_hash(self) -> str:
        """Calculate content-addressable SHA-256 hash of core fields."""
        content = json.dumps(
            {
                "receipt_id": self.receipt_id,
                "cycle_id": self.cycle_id,
                "goal": self.goal,
                "tracks_executed": self.tracks_executed,
                "subtasks_completed": self.subtasks_completed,
                "subtasks_failed": self.subtasks_failed,
                "files_changed": self.files_changed,
                "commit_shas": self.commit_shas,
                "quality_delta": self.quality_delta,
                "cost_usd": self.cost_usd,
                "gauntlet_verdict": self.gauntlet_verdict,
                "canary_token_clean": self.canary_token_clean,
                "output_validation_passed": self.output_validation_passed,
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def verify_integrity(self) -> bool:
        """Verify receipt has not been tampered with."""
        return self._calculate_hash() == self.artifact_hash

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "cycle_id": self.cycle_id,
            "timestamp": self.timestamp,
            "goal": self.goal,
            "tracks_executed": self.tracks_executed,
            "subtasks_completed": self.subtasks_completed,
            "subtasks_failed": self.subtasks_failed,
            "files_changed": self.files_changed,
            "commit_shas": self.commit_shas,
            "branch_names": self.branch_names,
            "quality_before": self.quality_before,
            "quality_after": self.quality_after,
            "quality_delta": self.quality_delta,
            "cost_usd": self.cost_usd,
            "approval_records": [r.to_dict() for r in self.approval_records],
            "gauntlet_verdict": self.gauntlet_verdict,
            "canary_token_clean": self.canary_token_clean,
            "output_validation_passed": self.output_validation_passed,
            "artifact_hash": self.artifact_hash,
            "schema_version": self.schema_version,
            "signature": self.signature,
            "signature_algorithm": self.signature_algorithm,
            "signed_at": self.signed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NomicCycleReceipt:
        d = dict(data)
        # Deserialize nested ApprovalRecords
        raw_approvals = d.pop("approval_records", [])
        approvals = [ApprovalRecord.from_dict(a) for a in raw_approvals]
        # Only pass known dataclass fields
        known = cls.__dataclass_fields__
        filtered = {k: v for k, v in d.items() if k in known}
        filtered["approval_records"] = approvals
        return cls(**filtered)

    def _to_dict_for_signing(self) -> dict[str, Any]:
        """Return dict without signature fields for signing/verification."""
        data = self.to_dict()
        data.pop("signature", None)
        data.pop("signature_algorithm", None)
        data.pop("signed_at", None)
        return data

    def sign(self, signer: ReceiptSigner | None = None) -> NomicCycleReceipt:
        """Sign this receipt with the given (or default) ReceiptSigner.

        Populates ``signature``, ``signature_algorithm``, and ``signed_at``.

        Args:
            signer: Optional ReceiptSigner. Uses default signer if not provided.

        Returns:
            Self with signature fields populated.
        """
        from aragora.gauntlet.signing import get_default_signer

        signer = signer or get_default_signer()
        signed = signer.sign(self._to_dict_for_signing())

        self.signature = signed.signature
        self.signature_algorithm = signed.signature_metadata.algorithm
        self.signed_at = signed.signature_metadata.timestamp

        return self

    def verify_signature(self, signer: ReceiptSigner | None = None) -> bool:
        """Verify the cryptographic signature on this receipt.

        Args:
            signer: Optional ReceiptSigner. Uses default signer if not provided.

        Returns:
            True if signature is valid, False otherwise.
        """
        if not self.signature:
            return False

        from aragora.gauntlet.signing import (
            SignatureMetadata,
            SignedReceipt,
            get_default_signer,
        )

        signer = signer or get_default_signer()

        receipt_data = self._to_dict_for_signing()
        metadata = SignatureMetadata(
            algorithm=self.signature_algorithm or "",
            timestamp=self.signed_at or "",
            key_id=signer.key_id,
        )
        signed_receipt = SignedReceipt(
            receipt_data=receipt_data,
            signature=self.signature,
            signature_metadata=metadata,
        )

        return signer.verify(signed_receipt)


def create_cycle_receipt(
    cycle_id: str,
    goal: str,
    *,
    tracks_executed: list[str] | None = None,
    subtasks_completed: int = 0,
    subtasks_failed: int = 0,
    files_changed: list[str] | None = None,
    commit_shas: list[str] | None = None,
    branch_names: list[str] | None = None,
    quality_before: dict[str, Any] | None = None,
    quality_after: dict[str, Any] | None = None,
    quality_delta: float = 0.0,
    cost_usd: float = 0.0,
    approval_records: list[ApprovalRecord] | None = None,
    gauntlet_verdict: str | None = None,
    canary_token_clean: bool = True,
    output_validation_passed: bool = True,
) -> NomicCycleReceipt:
    """Convenience factory for creating a NomicCycleReceipt."""
    return NomicCycleReceipt(
        receipt_id=f"nr-{uuid.uuid4().hex[:12]}",
        cycle_id=cycle_id,
        goal=goal,
        tracks_executed=tracks_executed or [],
        subtasks_completed=subtasks_completed,
        subtasks_failed=subtasks_failed,
        files_changed=files_changed or [],
        commit_shas=commit_shas or [],
        branch_names=branch_names or [],
        quality_before=quality_before or {},
        quality_after=quality_after or {},
        quality_delta=quality_delta,
        cost_usd=cost_usd,
        approval_records=approval_records or [],
        gauntlet_verdict=gauntlet_verdict,
        canary_token_clean=canary_token_clean,
        output_validation_passed=output_validation_passed,
    )
