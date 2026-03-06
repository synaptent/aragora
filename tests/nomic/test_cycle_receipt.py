"""Tests for Nomic cycle receipts and receipt store.

Covers:
- Receipt creation and field defaults
- to_dict / from_dict round-trip fidelity
- Integrity hash verification (tamper detection)
- HMAC signing and verification
- NomicReceiptStore CRUD operations
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aragora.nomic.cycle_receipt import (
    ApprovalRecord,
    NomicCycleReceipt,
    create_cycle_receipt,
)
from aragora.nomic.stores.receipt_store import NomicReceiptStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_approval(
    gate_id: str = "gate-1",
    gate_type: str = "plan_approval",
    approver: str = "human",
    decision: str = "approved",
) -> ApprovalRecord:
    return ApprovalRecord(
        gate_id=gate_id,
        gate_type=gate_type,
        approver=approver,
        decision=decision,
        timestamp="2026-03-01T00:00:00+00:00",
        metadata={"reason": "looks good"},
    )


def _make_receipt(**overrides) -> NomicCycleReceipt:
    defaults = dict(
        receipt_id="nr-test001",
        cycle_id="cycle-42",
        goal="Improve test coverage",
        tracks_executed=["qa", "developer"],
        subtasks_completed=5,
        subtasks_failed=1,
        files_changed=["aragora/foo.py", "aragora/bar.py"],
        commit_shas=["deadbeef", "cafebabe"],
        branch_names=["nomic/improve-coverage"],
        quality_before={"test_coverage": 0.80},
        quality_after={"test_coverage": 0.87},
        quality_delta=0.07,
        cost_usd=1.23,
        approval_records=[_make_approval()],
        gauntlet_verdict="PASS",
        canary_token_clean=True,
        output_validation_passed=True,
    )
    defaults.update(overrides)
    return NomicCycleReceipt(**defaults)


# ---------------------------------------------------------------------------
# ApprovalRecord
# ---------------------------------------------------------------------------


class TestApprovalRecord:
    def test_to_dict(self) -> None:
        record = _make_approval()
        d = record.to_dict()
        assert d["gate_id"] == "gate-1"
        assert d["gate_type"] == "plan_approval"
        assert d["decision"] == "approved"
        assert d["metadata"]["reason"] == "looks good"

    def test_round_trip(self) -> None:
        record = _make_approval(gate_type="merge_gate", decision="rejected")
        d = record.to_dict()
        restored = ApprovalRecord.from_dict(d)
        assert restored.gate_type == "merge_gate"
        assert restored.decision == "rejected"
        assert restored.metadata == record.metadata

    def test_from_dict_missing_metadata(self) -> None:
        d = {
            "gate_id": "g1",
            "gate_type": "review_gate",
            "approver": "bot",
            "decision": "approved",
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
        record = ApprovalRecord.from_dict(d)
        assert record.metadata == {}


# ---------------------------------------------------------------------------
# NomicCycleReceipt — creation and defaults
# ---------------------------------------------------------------------------


class TestNomicCycleReceiptCreation:
    def test_defaults(self) -> None:
        receipt = NomicCycleReceipt(receipt_id="nr-1", cycle_id="c-1")
        assert receipt.receipt_id == "nr-1"
        assert receipt.timestamp  # auto-populated
        assert receipt.artifact_hash  # auto-calculated
        assert receipt.schema_version == "1.0"
        assert receipt.signature is None
        assert receipt.canary_token_clean is True
        assert receipt.output_validation_passed is True

    def test_create_cycle_receipt_factory(self) -> None:
        receipt = create_cycle_receipt(
            "cycle-99",
            "Add logging",
            tracks_executed=["infra"],
            cost_usd=0.50,
        )
        assert receipt.receipt_id.startswith("nr-")
        assert receipt.cycle_id == "cycle-99"
        assert receipt.goal == "Add logging"
        assert receipt.cost_usd == 0.50


# ---------------------------------------------------------------------------
# NomicCycleReceipt — to_dict / from_dict round-trip
# ---------------------------------------------------------------------------


class TestNomicCycleReceiptRoundTrip:
    def test_full_round_trip(self) -> None:
        original = _make_receipt()
        d = original.to_dict()
        restored = NomicCycleReceipt.from_dict(d)

        assert restored.receipt_id == original.receipt_id
        assert restored.cycle_id == original.cycle_id
        assert restored.goal == original.goal
        assert restored.tracks_executed == original.tracks_executed
        assert restored.subtasks_completed == original.subtasks_completed
        assert restored.subtasks_failed == original.subtasks_failed
        assert restored.files_changed == original.files_changed
        assert restored.commit_shas == original.commit_shas
        assert restored.branch_names == original.branch_names
        assert restored.quality_before == original.quality_before
        assert restored.quality_after == original.quality_after
        assert restored.quality_delta == pytest.approx(original.quality_delta)
        assert restored.cost_usd == pytest.approx(original.cost_usd)
        assert restored.gauntlet_verdict == original.gauntlet_verdict
        assert restored.canary_token_clean == original.canary_token_clean
        assert restored.output_validation_passed == original.output_validation_passed
        assert restored.artifact_hash == original.artifact_hash
        assert restored.schema_version == original.schema_version

    def test_approval_records_survive_round_trip(self) -> None:
        original = _make_receipt()
        d = original.to_dict()
        restored = NomicCycleReceipt.from_dict(d)

        assert len(restored.approval_records) == 1
        ar = restored.approval_records[0]
        assert ar.gate_id == "gate-1"
        assert ar.approver == "human"
        assert ar.metadata == {"reason": "looks good"}

    def test_json_serializable(self) -> None:
        receipt = _make_receipt()
        text = json.dumps(receipt.to_dict())
        restored = NomicCycleReceipt.from_dict(json.loads(text))
        assert restored.receipt_id == receipt.receipt_id


# ---------------------------------------------------------------------------
# Integrity hash verification
# ---------------------------------------------------------------------------


class TestIntegrityVerification:
    def test_intact_receipt_passes(self) -> None:
        receipt = _make_receipt()
        assert receipt.verify_integrity() is True

    def test_tampered_goal_fails(self) -> None:
        receipt = _make_receipt()
        receipt.goal = "TAMPERED"
        assert receipt.verify_integrity() is False

    def test_tampered_subtask_count_fails(self) -> None:
        receipt = _make_receipt()
        receipt.subtasks_completed = 999
        assert receipt.verify_integrity() is False

    def test_tampered_cost_fails(self) -> None:
        receipt = _make_receipt()
        receipt.cost_usd = 0.0
        assert receipt.verify_integrity() is False

    def test_tampered_files_changed_fails(self) -> None:
        receipt = _make_receipt()
        receipt.files_changed = ["evil.py"]
        assert receipt.verify_integrity() is False

    def test_tampered_gauntlet_verdict_fails(self) -> None:
        receipt = _make_receipt()
        receipt.gauntlet_verdict = "FAIL"
        assert receipt.verify_integrity() is False

    def test_tampered_canary_token_fails(self) -> None:
        receipt = _make_receipt()
        receipt.canary_token_clean = False
        assert receipt.verify_integrity() is False

    def test_restored_receipt_passes(self) -> None:
        """A receipt restored via from_dict preserves its original hash."""
        receipt = _make_receipt()
        d = receipt.to_dict()
        restored = NomicCycleReceipt.from_dict(d)
        assert restored.verify_integrity() is True


# ---------------------------------------------------------------------------
# Signing and signature verification
# ---------------------------------------------------------------------------


class TestSigning:
    def test_sign_populates_fields(self) -> None:
        from aragora.gauntlet.signing import HMACSigner, ReceiptSigner

        signer = ReceiptSigner(backend=HMACSigner())
        receipt = _make_receipt()

        receipt.sign(signer)

        assert receipt.signature is not None
        assert receipt.signature_algorithm == "HMAC-SHA256"
        assert receipt.signed_at is not None

    def test_verify_signature_valid(self) -> None:
        from aragora.gauntlet.signing import HMACSigner, ReceiptSigner

        signer = ReceiptSigner(backend=HMACSigner())
        receipt = _make_receipt()
        receipt.sign(signer)

        assert receipt.verify_signature(signer) is True

    def test_verify_signature_wrong_key_fails(self) -> None:
        from aragora.gauntlet.signing import HMACSigner, ReceiptSigner

        signer_a = ReceiptSigner(backend=HMACSigner())
        signer_b = ReceiptSigner(backend=HMACSigner())

        receipt = _make_receipt()
        receipt.sign(signer_a)

        assert receipt.verify_signature(signer_b) is False

    def test_verify_unsigned_receipt_returns_false(self) -> None:
        from aragora.gauntlet.signing import HMACSigner, ReceiptSigner

        signer = ReceiptSigner(backend=HMACSigner())
        receipt = _make_receipt()

        assert receipt.verify_signature(signer) is False

    def test_tampered_after_signing_fails(self) -> None:
        from aragora.gauntlet.signing import HMACSigner, ReceiptSigner

        signer = ReceiptSigner(backend=HMACSigner())
        receipt = _make_receipt()
        receipt.sign(signer)

        # Tamper after signing
        receipt.cost_usd = 999.99
        assert receipt.verify_signature(signer) is False


# ---------------------------------------------------------------------------
# NomicReceiptStore
# ---------------------------------------------------------------------------


class TestNomicReceiptStore:
    def test_save_and_get(self, tmp_path: Path) -> None:
        store = NomicReceiptStore(data_dir=tmp_path)
        receipt = _make_receipt()
        store.save_receipt(receipt)

        retrieved = store.get_receipt("nr-test001")
        assert retrieved is not None
        assert retrieved.goal == "Improve test coverage"

    def test_get_missing_returns_none(self, tmp_path: Path) -> None:
        store = NomicReceiptStore(data_dir=tmp_path)
        assert store.get_receipt("nonexistent") is None

    def test_list_receipts_ordering(self, tmp_path: Path) -> None:
        store = NomicReceiptStore(data_dir=tmp_path)

        r1 = _make_receipt(receipt_id="nr-1", timestamp="2026-01-01T00:00:00+00:00")
        r2 = _make_receipt(receipt_id="nr-2", timestamp="2026-03-01T00:00:00+00:00")
        r3 = _make_receipt(receipt_id="nr-3", timestamp="2026-02-01T00:00:00+00:00")

        store.save_receipt(r1)
        store.save_receipt(r2)
        store.save_receipt(r3)

        receipts = store.list_receipts()
        assert [r.receipt_id for r in receipts] == ["nr-2", "nr-3", "nr-1"]

    def test_list_receipts_limit_and_offset(self, tmp_path: Path) -> None:
        store = NomicReceiptStore(data_dir=tmp_path)
        for i in range(5):
            r = _make_receipt(
                receipt_id=f"nr-{i}",
                timestamp=f"2026-01-0{i + 1}T00:00:00+00:00",
            )
            store.save_receipt(r)

        page = store.list_receipts(limit=2, offset=1)
        assert len(page) == 2

    def test_verify_receipt_intact(self, tmp_path: Path) -> None:
        store = NomicReceiptStore(data_dir=tmp_path)
        receipt = _make_receipt()
        store.save_receipt(receipt)

        assert store.verify_receipt("nr-test001") is True

    def test_verify_receipt_missing(self, tmp_path: Path) -> None:
        store = NomicReceiptStore(data_dir=tmp_path)
        assert store.verify_receipt("ghost") is None

    def test_persistence_across_instances(self, tmp_path: Path) -> None:
        store1 = NomicReceiptStore(data_dir=tmp_path)
        receipt = _make_receipt()
        store1.save_receipt(receipt)

        # New instance should load from disk
        store2 = NomicReceiptStore(data_dir=tmp_path)
        assert store2.get_receipt("nr-test001") is not None
        assert store2.count() == 1

    def test_count(self, tmp_path: Path) -> None:
        store = NomicReceiptStore(data_dir=tmp_path)
        assert store.count() == 0

        store.save_receipt(_make_receipt(receipt_id="nr-a"))
        store.save_receipt(_make_receipt(receipt_id="nr-b"))
        assert store.count() == 2

    def test_update_overwrites(self, tmp_path: Path) -> None:
        store = NomicReceiptStore(data_dir=tmp_path)
        receipt = _make_receipt()
        store.save_receipt(receipt)

        # Update the same receipt
        receipt.goal = "Updated goal"
        receipt.artifact_hash = receipt._calculate_hash()
        store.save_receipt(receipt)

        assert store.count() == 1
        retrieved = store.get_receipt("nr-test001")
        assert retrieved is not None
        assert retrieved.goal == "Updated goal"
