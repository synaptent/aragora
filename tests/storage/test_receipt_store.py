"""
Tests for ReceiptStore - Decision receipt storage with signature support.

Tests cover:
- CRUD operations (save, get, list, count)
- Signature operations (update_signature, verify_signature, verify_batch)
- Integrity verification
- Retention/cleanup
- PostgreSQL and SQLite backends
- Filtering and pagination
"""

import importlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aragora.storage.receipt_store import (
    DEFAULT_RETENTION_DAYS,
    ReceiptStore,
    SignatureVerificationResult,
    StoredReceipt,
    _compute_receipt_checksum,
    close_receipt_store,
    get_receipt_store,
    set_receipt_store,
)


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(cwd, "git", *args)


def _make_git_repo_with_linked_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("hello\n")
    (repo / ".nomic").mkdir()
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")

    linked = tmp_path / "linked-worktree"
    _git(repo, "worktree", "add", "-b", "feature/test", str(linked), "main")
    return repo, linked


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_receipts.db"


@pytest.fixture
def receipt_store(temp_db_path):
    """Create a receipt store for testing.

    Passes file_receipt_dirs=[] to disable file-based fallback scanning
    so that real .aragora/receipts/ files in the working directory do
    not interfere with DB-focused tests.
    """
    store = ReceiptStore(db_path=temp_db_path, backend="sqlite", file_receipt_dirs=[])
    yield store
    store.close()


@pytest.fixture
def sample_receipt_dict():
    """Create a sample receipt dictionary."""
    return {
        "receipt_id": "receipt-001",
        "gauntlet_id": "gauntlet-001",
        "debate_id": "debate-001",
        "timestamp": time.time(),
        "verdict": "APPROVED",
        "confidence": 0.85,
        "risk_level": "MEDIUM",
        "risk_score": 0.35,
        "checksum": "sha256:abc123def456",
        "audit_trail_id": "audit-001",
        "statement": "Test statement for receipt",
        "findings": [],
    }


@pytest.fixture
def signed_receipt_dict():
    """Create a sample signed receipt."""
    return {
        "signature": "base64encodedSignature==",
        "signature_metadata": {
            "algorithm": "HMAC-SHA256",
            "key_id": "key-001",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


# ===========================================================================
# StoredReceipt Dataclass Tests
# ===========================================================================


class TestStoredReceipt:
    """Tests for StoredReceipt dataclass."""

    def test_to_dict_basic_fields(self):
        """Test to_dict includes all basic fields."""
        receipt = StoredReceipt(
            receipt_id="receipt-001",
            gauntlet_id="gauntlet-001",
            debate_id="debate-001",
            created_at=1700000000.0,
            expires_at=1800000000.0,
            verdict="APPROVED",
            confidence=0.85,
            risk_level="MEDIUM",
            risk_score=0.35,
            checksum="sha256:abc123",
        )

        result = receipt.to_dict()

        assert result["receipt_id"] == "receipt-001"
        assert result["gauntlet_id"] == "gauntlet-001"
        assert result["verdict"] == "APPROVED"
        assert result["confidence"] == 0.85
        assert result["is_signed"] is False
        assert "signature_metadata" not in result

    def test_to_dict_with_signature(self):
        """Test to_dict includes signature metadata when signed."""
        receipt = StoredReceipt(
            receipt_id="receipt-001",
            gauntlet_id="gauntlet-001",
            debate_id=None,
            created_at=1700000000.0,
            expires_at=None,
            verdict="REJECTED",
            confidence=0.95,
            risk_level="HIGH",
            risk_score=0.75,
            checksum="sha256:xyz789",
            signature="base64sig==",
            signature_algorithm="HMAC-SHA256",
            signature_key_id="key-001",
            signed_at=1700001000.0,
        )

        result = receipt.to_dict()

        assert result["is_signed"] is True
        assert result["signature_metadata"]["algorithm"] == "HMAC-SHA256"
        assert result["signature_metadata"]["key_id"] == "key-001"
        assert result["signature_metadata"]["signed_at"] == 1700001000.0

    def test_to_full_dict_includes_data(self):
        """Test to_full_dict includes data payload."""
        receipt = StoredReceipt(
            receipt_id="receipt-001",
            gauntlet_id="gauntlet-001",
            debate_id=None,
            created_at=1700000000.0,
            expires_at=None,
            verdict="APPROVED",
            confidence=0.85,
            risk_level="LOW",
            risk_score=0.15,
            checksum="sha256:abc",
            data={"statement": "Test", "extra_field": "value"},
        )

        result = receipt.to_full_dict()

        assert result["statement"] == "Test"
        assert result["extra_field"] == "value"
        assert result["receipt_id"] == "receipt-001"

    def test_to_full_dict_structured_fields_win_over_stale_data(self):
        """Authoritative DB column values must override stale data_json blob values.

        When a receipt is signed after initial save, the structured
        ``verdict``/``confidence`` columns may differ from the original
        ``data_json`` blob.  ``to_full_dict()`` must prefer the column
        values so callers always see the authoritative state.
        """
        receipt = StoredReceipt(
            receipt_id="receipt-002",
            gauntlet_id="gauntlet-002",
            debate_id="debate-002",
            created_at=1700000000.0,
            expires_at=1700086400.0,
            verdict="APPROVED",  # authoritative column value
            confidence=0.95,  # updated after initial save
            risk_level="LOW",
            risk_score=0.05,
            checksum="sha256:xyz",
            data={
                # Stale blob values from original save
                "verdict": "NEEDS_REVIEW",
                "confidence": 0.5,
                "risk_level": "HIGH",
                "timestamp": "2023-11-15T00:00:00Z",
                "input_summary": "Original question",
            },
        )

        result = receipt.to_full_dict()

        # Structured fields must win
        assert result["verdict"] == "APPROVED"
        assert result["confidence"] == 0.95
        assert result["risk_level"] == "LOW"
        assert result["receipt_id"] == "receipt-002"
        assert result["debate_id"] == "debate-002"
        # Data-only fields are preserved
        assert result["timestamp"] == "2023-11-15T00:00:00Z"
        assert result["input_summary"] == "Original question"

    def test_to_full_dict_clamps_stale_confidence_fields(self):
        """Out-of-range confidence from stale rows is normalized on read."""
        receipt = StoredReceipt(
            receipt_id="receipt-003",
            gauntlet_id="gauntlet-003",
            debate_id="debate-003",
            created_at=1700000000.0,
            expires_at=None,
            verdict="PASS",
            confidence=1.2,
            risk_level="LOW",
            risk_score=0.05,
            checksum="sha256:stale",
            data={
                "confidence": 1.2,
                "consensus_proof": {
                    "reached": True,
                    "confidence": 1.4,
                },
            },
        )

        result = receipt.to_full_dict()

        assert receipt.confidence == pytest.approx(1.0)
        assert result["confidence"] == pytest.approx(1.0)
        assert result["consensus_proof"]["confidence"] == pytest.approx(1.0)


class TestSignatureVerificationResult:
    """Tests for SignatureVerificationResult dataclass."""

    def test_to_dict_valid(self):
        """Test to_dict for valid signature."""
        result = SignatureVerificationResult(
            receipt_id="receipt-001",
            is_valid=True,
            algorithm="HMAC-SHA256",
            key_id="key-001",
            signed_at=1700000000.0,
        )

        dict_result = result.to_dict()

        assert dict_result["receipt_id"] == "receipt-001"
        assert dict_result["signature_valid"] is True
        assert dict_result["algorithm"] == "HMAC-SHA256"
        assert dict_result["error"] is None

    def test_to_dict_with_error(self):
        """Test to_dict for invalid signature with error."""
        result = SignatureVerificationResult(
            receipt_id="receipt-001",
            is_valid=False,
            error="Receipt not signed",
        )

        dict_result = result.to_dict()

        assert dict_result["signature_valid"] is False
        assert dict_result["error"] == "Receipt not signed"


# ===========================================================================
# ReceiptStore CRUD Tests
# ===========================================================================


class TestReceiptStoreCRUD:
    """Tests for ReceiptStore CRUD operations."""

    def test_save_and_get(self, receipt_store, sample_receipt_dict):
        """Test save and retrieve a receipt."""
        receipt_id = receipt_store.save(sample_receipt_dict)

        assert receipt_id == "receipt-001"

        receipt = receipt_store.get(receipt_id)
        assert receipt is not None
        assert receipt.receipt_id == "receipt-001"
        assert receipt.gauntlet_id == "gauntlet-001"
        assert receipt.verdict == "APPROVED"
        assert receipt.confidence == 0.85

    def test_save_with_signature(self, receipt_store, sample_receipt_dict, signed_receipt_dict):
        """Test save receipt with signature data."""
        receipt_store.save(sample_receipt_dict, signed_receipt=signed_receipt_dict)

        receipt = receipt_store.get("receipt-001")
        assert receipt is not None
        assert receipt.signature == "base64encodedSignature=="
        assert receipt.signature_algorithm == "HMAC-SHA256"
        assert receipt.signature_key_id == "key-001"

    def test_get_nonexistent(self, receipt_store):
        """Test get returns None for nonexistent receipt."""
        result = receipt_store.get("nonexistent-id")
        assert result is None

    def test_get_by_gauntlet(self, receipt_store, sample_receipt_dict):
        """Test retrieve by gauntlet_id."""
        receipt_store.save(sample_receipt_dict)

        receipt = receipt_store.get_by_gauntlet("gauntlet-001")
        assert receipt is not None
        assert receipt.receipt_id == "receipt-001"

    def test_get_by_gauntlet_nonexistent(self, receipt_store):
        """Test get_by_gauntlet returns None for nonexistent."""
        result = receipt_store.get_by_gauntlet("nonexistent")
        assert result is None

    def test_save_updates_existing(self, receipt_store, sample_receipt_dict):
        """Test save updates existing receipt (upsert)."""
        receipt_store.save(sample_receipt_dict)

        # Update verdict
        sample_receipt_dict["verdict"] = "REJECTED"
        sample_receipt_dict["confidence"] = 0.95
        receipt_store.save(sample_receipt_dict)

        receipt = receipt_store.get("receipt-001")
        assert receipt.verdict == "REJECTED"
        assert receipt.confidence == 0.95

    def test_save_clamps_out_of_range_confidence(self, receipt_store, sample_receipt_dict):
        """Persisted receipts should normalize confidence into the canonical range."""
        sample_receipt_dict["confidence"] = 1.2
        sample_receipt_dict["consensus_proof"] = {
            "reached": True,
            "confidence": 1.4,
        }

        receipt_store.save(sample_receipt_dict)

        receipt = receipt_store.get("receipt-001")
        assert receipt is not None
        payload = receipt.to_full_dict()
        assert receipt.confidence == pytest.approx(1.0)
        assert payload["confidence"] == pytest.approx(1.0)
        assert payload["consensus_proof"]["confidence"] == pytest.approx(1.0)


def test_default_receipt_db_path_uses_repo_shared_nomic_for_linked_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, linked = _make_git_repo_with_linked_worktree(tmp_path)
    monkeypatch.delenv("ARAGORA_RECEIPT_DB_PATH", raising=False)
    monkeypatch.delenv("ARAGORA_DATA_DIR", raising=False)
    monkeypatch.delenv("ARAGORA_NOMIC_DIR", raising=False)
    monkeypatch.chdir(linked)

    import aragora.storage.receipt_store as receipt_store_module

    receipt_store_module = importlib.reload(receipt_store_module)
    assert receipt_store_module.DEFAULT_DB_PATH == repo / ".nomic" / "receipts.db"


def test_default_receipt_db_path_respects_explicit_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom_dir = tmp_path / "custom-data"
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(custom_dir))
    monkeypatch.delenv("ARAGORA_RECEIPT_DB_PATH", raising=False)

    import aragora.storage.receipt_store as receipt_store_module

    receipt_store_module = importlib.reload(receipt_store_module)
    assert receipt_store_module.DEFAULT_DB_PATH == custom_dir / "receipts.db"

    def test_save_with_iso_timestamp(self, receipt_store, sample_receipt_dict):
        """Test save handles ISO timestamp format."""
        sample_receipt_dict["timestamp"] = "2024-01-15T10:30:00+00:00"
        receipt_store.save(sample_receipt_dict)

        receipt = receipt_store.get("receipt-001")
        assert receipt is not None
        assert receipt.created_at > 0

    def test_save_with_datetime_in_payload(self, receipt_store, sample_receipt_dict):
        """Test save serializes datetime objects embedded in receipt payload."""
        sample_receipt_dict["generated_at"] = datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc)
        receipt_store.save(sample_receipt_dict)

        receipt = receipt_store.get("receipt-001")
        assert receipt is not None
        assert isinstance(receipt.data.get("generated_at"), str)
        assert receipt.data["generated_at"].startswith("2026-02-24T12:00:00")


class TestReceiptStoreList:
    """Tests for ReceiptStore list and filtering."""

    def test_list_empty(self, receipt_store):
        """Test list returns empty for empty store."""
        receipts = receipt_store.list()
        assert receipts == []

    def test_list_multiple(self, receipt_store, sample_receipt_dict):
        """Test list returns multiple receipts."""
        for i in range(5):
            sample_receipt_dict["receipt_id"] = f"receipt-{i:03d}"
            sample_receipt_dict["gauntlet_id"] = f"gauntlet-{i:03d}"
            receipt_store.save(sample_receipt_dict)

        receipts = receipt_store.list(limit=10)
        assert len(receipts) == 5

    def test_list_pagination(self, receipt_store, sample_receipt_dict):
        """Test list pagination with limit and offset."""
        for i in range(10):
            sample_receipt_dict["receipt_id"] = f"receipt-{i:03d}"
            sample_receipt_dict["gauntlet_id"] = f"gauntlet-{i:03d}"
            receipt_store.save(sample_receipt_dict)

        page1 = receipt_store.list(limit=3, offset=0)
        page2 = receipt_store.list(limit=3, offset=3)

        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0].receipt_id != page2[0].receipt_id

    def test_list_filter_by_verdict(self, receipt_store, sample_receipt_dict):
        """Test list filters by verdict."""
        # Add APPROVED receipts
        for i in range(3):
            sample_receipt_dict["receipt_id"] = f"approved-{i}"
            sample_receipt_dict["gauntlet_id"] = f"gauntlet-a-{i}"
            sample_receipt_dict["verdict"] = "APPROVED"
            receipt_store.save(sample_receipt_dict)

        # Add REJECTED receipts
        for i in range(2):
            sample_receipt_dict["receipt_id"] = f"rejected-{i}"
            sample_receipt_dict["gauntlet_id"] = f"gauntlet-r-{i}"
            sample_receipt_dict["verdict"] = "REJECTED"
            receipt_store.save(sample_receipt_dict)

        approved = receipt_store.list(verdict="APPROVED")
        rejected = receipt_store.list(verdict="REJECTED")

        assert len(approved) == 3
        assert len(rejected) == 2
        assert all(r.verdict == "APPROVED" for r in approved)
        assert all(r.verdict == "REJECTED" for r in rejected)

    def test_list_filter_by_risk_level(self, receipt_store, sample_receipt_dict):
        """Test list filters by risk level."""
        risk_levels = ["LOW", "MEDIUM", "HIGH"]
        for i, level in enumerate(risk_levels):
            sample_receipt_dict["receipt_id"] = f"receipt-{level}"
            sample_receipt_dict["gauntlet_id"] = f"gauntlet-{level}"
            sample_receipt_dict["risk_level"] = level
            receipt_store.save(sample_receipt_dict)

        high_risk = receipt_store.list(risk_level="HIGH")
        assert len(high_risk) == 1
        assert high_risk[0].risk_level == "HIGH"

    def test_list_filter_signed_only(self, receipt_store, sample_receipt_dict, signed_receipt_dict):
        """Test list filters signed receipts only."""
        # Add unsigned receipt
        sample_receipt_dict["receipt_id"] = "unsigned"
        sample_receipt_dict["gauntlet_id"] = "gauntlet-unsigned"
        receipt_store.save(sample_receipt_dict)

        # Add signed receipt
        sample_receipt_dict["receipt_id"] = "signed"
        sample_receipt_dict["gauntlet_id"] = "gauntlet-signed"
        receipt_store.save(sample_receipt_dict, signed_receipt=signed_receipt_dict)

        all_receipts = receipt_store.list()
        signed_only = receipt_store.list(signed_only=True)

        assert len(all_receipts) == 2
        assert len(signed_only) == 1
        assert signed_only[0].receipt_id == "signed"

    def test_list_date_range(self, receipt_store, sample_receipt_dict):
        """Test list filters by date range."""
        now = time.time()

        # Old receipt
        sample_receipt_dict["receipt_id"] = "old"
        sample_receipt_dict["gauntlet_id"] = "gauntlet-old"
        sample_receipt_dict["timestamp"] = now - 86400 * 10  # 10 days ago
        receipt_store.save(sample_receipt_dict)

        # Recent receipt
        sample_receipt_dict["receipt_id"] = "recent"
        sample_receipt_dict["gauntlet_id"] = "gauntlet-recent"
        sample_receipt_dict["timestamp"] = now
        receipt_store.save(sample_receipt_dict)

        recent = receipt_store.list(date_from=now - 86400)  # Last day
        assert len(recent) == 1
        assert recent[0].receipt_id == "recent"

    def test_list_sorting(self, receipt_store, sample_receipt_dict):
        """Test list sorting by different fields."""
        confidences = [0.5, 0.9, 0.7]
        for i, conf in enumerate(confidences):
            sample_receipt_dict["receipt_id"] = f"receipt-{i}"
            sample_receipt_dict["gauntlet_id"] = f"gauntlet-{i}"
            sample_receipt_dict["confidence"] = conf
            receipt_store.save(sample_receipt_dict)

        desc = receipt_store.list(sort_by="confidence", order="desc")
        asc = receipt_store.list(sort_by="confidence", order="asc")

        assert desc[0].confidence == 0.9
        assert asc[0].confidence == 0.5

    def test_count(self, receipt_store, sample_receipt_dict):
        """Test count receipts."""
        assert receipt_store.count() == 0

        for i in range(5):
            sample_receipt_dict["receipt_id"] = f"receipt-{i}"
            sample_receipt_dict["gauntlet_id"] = f"gauntlet-{i}"
            receipt_store.save(sample_receipt_dict)

        assert receipt_store.count() == 5

    def test_count_with_filters(self, receipt_store, sample_receipt_dict):
        """Test count with filters."""
        for i in range(3):
            sample_receipt_dict["receipt_id"] = f"approved-{i}"
            sample_receipt_dict["gauntlet_id"] = f"gauntlet-a-{i}"
            sample_receipt_dict["verdict"] = "APPROVED"
            receipt_store.save(sample_receipt_dict)

        for i in range(2):
            sample_receipt_dict["receipt_id"] = f"rejected-{i}"
            sample_receipt_dict["gauntlet_id"] = f"gauntlet-r-{i}"
            sample_receipt_dict["verdict"] = "REJECTED"
            receipt_store.save(sample_receipt_dict)

        assert receipt_store.count(verdict="APPROVED") == 3
        assert receipt_store.count(verdict="REJECTED") == 2


# ===========================================================================
# Signature Operations Tests
# ===========================================================================


class TestReceiptStoreSignatures:
    """Tests for signature operations."""

    def test_update_signature(self, receipt_store, sample_receipt_dict):
        """Test update_signature adds signature to receipt."""
        receipt_store.save(sample_receipt_dict)

        updated = receipt_store.update_signature(
            receipt_id="receipt-001",
            signature="newSignature==",
            algorithm="Ed25519",
            key_id="key-002",
        )

        assert updated is True

        receipt = receipt_store.get("receipt-001")
        assert receipt.signature == "newSignature=="
        assert receipt.signature_algorithm == "Ed25519"
        assert receipt.signature_key_id == "key-002"
        assert receipt.signed_at is not None

    def test_update_signature_nonexistent(self, receipt_store):
        """Test update_signature returns False for nonexistent receipt."""
        updated = receipt_store.update_signature(
            receipt_id="nonexistent",
            signature="sig",
            algorithm="HMAC-SHA256",
            key_id="key",
        )
        assert updated is False

    def test_verify_signature_not_found(self, receipt_store):
        """Test verify_signature for nonexistent receipt."""
        result = receipt_store.verify_signature("nonexistent")

        assert result.is_valid is False
        assert "not found" in result.error.lower()

    def test_verify_signature_unsigned(self, receipt_store, sample_receipt_dict):
        """Test verify_signature for unsigned receipt."""
        receipt_store.save(sample_receipt_dict)

        result = receipt_store.verify_signature("receipt-001")

        assert result.is_valid is False
        assert "not signed" in result.error.lower()

    def test_verify_signature_valid(self, receipt_store, sample_receipt_dict, signed_receipt_dict):
        """Test verify_signature for validly signed receipt."""
        receipt_store.save(sample_receipt_dict, signed_receipt=signed_receipt_dict)

        # Mock the signing module
        mock_signer = MagicMock()
        mock_signer.verify.return_value = True

        with patch.dict(
            "sys.modules",
            {
                "aragora.storage.receipt_signing": MagicMock(
                    ReceiptSigner=MagicMock(return_value=mock_signer),
                    SignatureMetadata=MagicMock(),
                    SignedReceipt=MagicMock(),
                )
            },
        ):
            result = receipt_store.verify_signature("receipt-001")

        assert result.is_valid is True
        assert result.algorithm == "HMAC-SHA256"

    def test_verify_batch(self, receipt_store, sample_receipt_dict, signed_receipt_dict):
        """Test batch signature verification."""
        # Add unsigned
        sample_receipt_dict["receipt_id"] = "unsigned"
        sample_receipt_dict["gauntlet_id"] = "gauntlet-unsigned"
        receipt_store.save(sample_receipt_dict)

        # Add signed
        sample_receipt_dict["receipt_id"] = "signed"
        sample_receipt_dict["gauntlet_id"] = "gauntlet-signed"
        receipt_store.save(sample_receipt_dict, signed_receipt=signed_receipt_dict)

        results, summary = receipt_store.verify_batch(["unsigned", "signed", "nonexistent"])

        assert len(results) == 3
        assert summary["total"] == 3
        assert summary["not_signed"] >= 1  # At least the unsigned one


# ===========================================================================
# Integrity Verification Tests
# ===========================================================================


class TestReceiptStoreIntegrity:
    """Tests for integrity verification."""

    def test_checksum_matches_decision_receipt_contract(self):
        """Storage checksum calculation stays aligned with the receipt model."""
        from aragora.export.decision_receipt import DecisionReceipt

        receipt_data = {
            "receipt_id": "receipt-contract",
            "gauntlet_id": "gauntlet-contract",
            "timestamp": "2026-07-12T12:00:00+00:00",
            "verdict": "APPROVED",
            "confidence": 0.9,
            "findings": [],
            "critical_count": 0,
            "audit_trail_id": "audit-contract",
        }
        receipt = DecisionReceipt.from_dict(receipt_data)

        assert _compute_receipt_checksum(receipt_data) == receipt._compute_checksum()

    def test_verify_integrity_not_found(self, receipt_store):
        """Test verify_integrity for nonexistent receipt."""
        result = receipt_store.verify_integrity("nonexistent")

        assert result["integrity_valid"] is False
        assert "not found" in result["error"].lower()

    def test_verify_integrity_valid(self, receipt_store, sample_receipt_dict):
        """Test verify_integrity for valid checksum."""
        expected_checksum = _compute_receipt_checksum(sample_receipt_dict)
        sample_receipt_dict["checksum"] = expected_checksum
        receipt_store.save(sample_receipt_dict)

        result = receipt_store.verify_integrity("receipt-001")

        assert result["integrity_valid"] is True
        assert result["stored_checksum"] == expected_checksum

    def test_verify_integrity_invalid(self, receipt_store, sample_receipt_dict):
        """Test verify_integrity for mismatched checksum."""
        computed_checksum = _compute_receipt_checksum(sample_receipt_dict)
        sample_receipt_dict["checksum"] = "tampered"
        receipt_store.save(sample_receipt_dict)

        result = receipt_store.verify_integrity("receipt-001")

        assert result["integrity_valid"] is False
        assert result["stored_checksum"] == "tampered"
        assert result["computed_checksum"] == computed_checksum


# ===========================================================================
# Retention and Cleanup Tests
# ===========================================================================


class TestReceiptStoreRetention:
    """Tests for retention and cleanup."""

    def test_cleanup_expired(self, receipt_store, sample_receipt_dict):
        """Test cleanup_expired removes old receipts."""
        now = time.time()

        # Add old receipt
        sample_receipt_dict["receipt_id"] = "old"
        sample_receipt_dict["gauntlet_id"] = "gauntlet-old"
        sample_receipt_dict["timestamp"] = now - 86400 * 100  # 100 days ago
        receipt_store.save(sample_receipt_dict)

        # Add recent receipt
        sample_receipt_dict["receipt_id"] = "recent"
        sample_receipt_dict["gauntlet_id"] = "gauntlet-recent"
        sample_receipt_dict["timestamp"] = now
        receipt_store.save(sample_receipt_dict)

        assert receipt_store.count() == 2

        # Cleanup with 50 day retention
        removed = receipt_store.cleanup_expired(retention_days=50)

        assert removed == 1
        assert receipt_store.count() == 1
        assert receipt_store.get("recent") is not None
        assert receipt_store.get("old") is None

    def test_cleanup_no_expired(self, receipt_store, sample_receipt_dict):
        """Test cleanup when no receipts are expired."""
        receipt_store.save(sample_receipt_dict)

        removed = receipt_store.cleanup_expired(retention_days=365)

        assert removed == 0
        assert receipt_store.count() == 1


# ===========================================================================
# Statistics Tests
# ===========================================================================


class TestReceiptStoreStats:
    """Tests for receipt statistics."""

    def test_get_stats_empty(self, receipt_store):
        """Test get_stats for empty store."""
        stats = receipt_store.get_stats()

        assert stats["total"] == 0
        assert stats["signed"] == 0

    def test_get_stats_with_data(self, receipt_store, sample_receipt_dict, signed_receipt_dict):
        """Test get_stats with receipts."""
        # Add various receipts
        verdicts = ["APPROVED", "REJECTED", "APPROVED"]
        risks = ["LOW", "HIGH", "MEDIUM"]

        for i, (verdict, risk) in enumerate(zip(verdicts, risks)):
            sample_receipt_dict["receipt_id"] = f"receipt-{i}"
            sample_receipt_dict["gauntlet_id"] = f"gauntlet-{i}"
            sample_receipt_dict["verdict"] = verdict
            sample_receipt_dict["risk_level"] = risk
            if i == 0:
                receipt_store.save(sample_receipt_dict, signed_receipt=signed_receipt_dict)
            else:
                receipt_store.save(sample_receipt_dict)

        stats = receipt_store.get_stats()

        assert stats["total"] == 3
        assert stats["signed"] == 1
        assert stats["unsigned"] == 2
        assert stats["by_verdict"]["approved"] == 2
        assert stats["by_verdict"]["rejected"] == 1
        assert stats["by_risk_level"]["high"] == 1


# ===========================================================================
# Singleton Pattern Tests
# ===========================================================================


class TestReceiptStoreSingleton:
    """Tests for singleton pattern."""

    def test_get_receipt_store_singleton(self, temp_db_path):
        """Test get_receipt_store returns singleton."""
        set_receipt_store(None)  # Reset

        with patch.dict("os.environ", {"ARAGORA_DATA_DIR": str(temp_db_path.parent)}):
            store1 = get_receipt_store()
            store2 = get_receipt_store()

        assert store1 is store2

        set_receipt_store(None)  # Cleanup

    def test_set_receipt_store(self, temp_db_path):
        """Test set_receipt_store replaces singleton."""
        custom_store = ReceiptStore(db_path=temp_db_path)

        set_receipt_store(custom_store)
        retrieved = get_receipt_store()

        assert retrieved is custom_store

        set_receipt_store(None)  # Cleanup

    def test_set_receipt_store_closes_previous(self, temp_db_path):
        """Replacing singleton closes previously registered store."""
        first = ReceiptStore(db_path=temp_db_path)
        second = ReceiptStore(db_path=temp_db_path.parent / "other.db")
        first.close = MagicMock()  # type: ignore[method-assign]
        second.close = MagicMock()  # type: ignore[method-assign]

        set_receipt_store(first)
        set_receipt_store(second)

        first.close.assert_called_once()
        second.close.assert_not_called()
        set_receipt_store(None)
        second.close.assert_called_once()

    def test_close_receipt_store_resets_singleton(self, temp_db_path):
        """close_receipt_store() closes and clears global singleton."""
        store = ReceiptStore(db_path=temp_db_path)
        store.close = MagicMock()  # type: ignore[method-assign]

        set_receipt_store(store)
        close_receipt_store()

        store.close.assert_called_once()

        with patch.dict("os.environ", {"ARAGORA_DATA_DIR": str(temp_db_path.parent)}):
            replacement = get_receipt_store()
        assert replacement is not store
        set_receipt_store(None)


# ===========================================================================
# Backend Configuration Tests
# ===========================================================================


class TestReceiptStoreBackends:
    """Tests for backend configuration."""

    @pytest.mark.parametrize("backend_type", ["sqlite", "postgresql"])
    def test_schema_creates_table_then_migrates_then_indexes(self, backend_type):
        store = ReceiptStore.__new__(ReceiptStore)
        store.backend_type = backend_type
        store._backend = MagicMock()
        schema = getattr(store, f"SCHEMA_STATEMENTS_{backend_type.upper()}")
        migrations = getattr(store, f"MIGRATION_STATEMENTS_{backend_type.upper()}")

        store._init_schema()

        statements = [call.args[0] for call in store._backend.execute_write.call_args_list]
        assert statements == [schema[0], *migrations, *schema[1:]]

    @pytest.mark.parametrize("backend_type", ["sqlite", "postgresql"])
    def test_table_creation_failure_is_not_reported_as_initialized(self, backend_type):
        store = ReceiptStore.__new__(ReceiptStore)
        store.backend_type = backend_type
        store._backend = MagicMock()
        store._backend.execute_write.side_effect = RuntimeError("database unavailable")

        with pytest.raises(RuntimeError, match="database unavailable"):
            store._init_schema()
        assert store._backend.execute_write.call_count == 1

    @pytest.mark.parametrize("legacy", [False, True])
    def test_sqlite_bootstrap_and_reopen_preserve_receipt(
        self, temp_db_path, sample_receipt_dict, legacy
    ):
        if legacy:
            # The old schema predates timestamp and legal-hold columns/indexes.
            old_schema = "\n".join(
                line
                for line in ReceiptStore.SCHEMA_STATEMENTS_SQLITE[0].splitlines()
                if not line.strip().startswith(("timestamp_", "legal_hold"))
            )
            with sqlite3.connect(temp_db_path) as connection:
                connection.execute(old_schema)
                connection.execute(
                    "INSERT INTO receipts (receipt_id, gauntlet_id, created_at, verdict, "
                    "confidence, risk_level, checksum, data_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("old", "old-gauntlet", 1.0, "APPROVED", 0.8, "LOW", "old", "{}"),
                )

        store = ReceiptStore(db_path=temp_db_path, backend="sqlite", file_receipt_dirs=[])
        try:
            if legacy:
                assert store.get("old") is not None
            store.save(sample_receipt_dict)
        finally:
            store.close()

        reopened = ReceiptStore(db_path=temp_db_path, backend="sqlite", file_receipt_dirs=[])
        try:
            receipt = reopened.get(sample_receipt_dict["receipt_id"])
            assert receipt is not None
            assert receipt.data["statement"] == sample_receipt_dict["statement"]
            if legacy:
                assert reopened.get("old") is not None
            with sqlite3.connect(temp_db_path) as connection:
                indexes = {row[1] for row in connection.execute("PRAGMA index_list(receipts)")}
            assert "idx_receipts_legal_hold" in indexes
        finally:
            reopened.close()

    def test_sqlite_backend(self, temp_db_path):
        """Test SQLite backend initialization."""
        store = ReceiptStore(db_path=temp_db_path, backend="sqlite")

        assert store.backend_type == "sqlite"
        assert store._backend is not None

    def test_postgresql_requires_url(self):
        """Test PostgreSQL backend requires DATABASE_URL."""
        with pytest.raises(ValueError, match="requires DATABASE_URL"):
            ReceiptStore(backend="postgresql")

    def test_default_retention_days(self, temp_db_path):
        """Test default retention days from environment."""
        store = ReceiptStore(db_path=temp_db_path)
        assert store.retention_days == DEFAULT_RETENTION_DAYS

    def test_custom_retention_days(self, temp_db_path):
        """Test custom retention days."""
        store = ReceiptStore(db_path=temp_db_path, retention_days=365)
        assert store.retention_days == 365


# ===========================================================================
# GDPR Compliance Tests
# ===========================================================================


class TestReceiptStoreGDPR:
    """Tests for GDPR compliance features."""

    def test_get_by_user_no_matches(self, receipt_store, sample_receipt_dict):
        """Test get_by_user returns empty for no matches."""
        receipt_store.save(sample_receipt_dict)

        receipts, total = receipt_store.get_by_user("nonexistent-user")

        assert receipts == []
        assert total == 0

    def test_get_by_user_matches_user_id(self, receipt_store, sample_receipt_dict):
        """Test get_by_user matches user_id field in data."""
        sample_receipt_dict["user_id"] = "user-123"
        receipt_store.save(sample_receipt_dict)

        receipts, total = receipt_store.get_by_user("user-123")

        assert total == 1
        assert len(receipts) == 1
        assert receipts[0].receipt_id == "receipt-001"

    def test_get_by_user_matches_created_by(self, receipt_store, sample_receipt_dict):
        """Test get_by_user matches created_by field in data."""
        sample_receipt_dict["created_by"] = "admin-user-456"
        receipt_store.save(sample_receipt_dict)

        receipts, total = receipt_store.get_by_user("admin-user-456")

        assert total == 1
        assert len(receipts) == 1

    def test_get_by_user_matches_requestor_id(self, receipt_store, sample_receipt_dict):
        """Test get_by_user matches requestor_id field in data."""
        sample_receipt_dict["requestor_id"] = "requestor-789"
        receipt_store.save(sample_receipt_dict)

        receipts, total = receipt_store.get_by_user("requestor-789")

        assert total == 1
        assert len(receipts) == 1

    def test_get_by_user_pagination(self, receipt_store, sample_receipt_dict):
        """Test get_by_user pagination."""
        for i in range(5):
            sample_receipt_dict["receipt_id"] = f"receipt-{i}"
            sample_receipt_dict["gauntlet_id"] = f"gauntlet-{i}"
            sample_receipt_dict["user_id"] = "paginated-user"
            receipt_store.save(sample_receipt_dict.copy())

        receipts, total = receipt_store.get_by_user("paginated-user", limit=2, offset=0)

        assert total == 5
        assert len(receipts) == 2

        receipts2, _ = receipt_store.get_by_user("paginated-user", limit=2, offset=2)
        assert len(receipts2) == 2

    def test_get_retention_status_empty(self, receipt_store):
        """Test get_retention_status with no receipts."""
        status = receipt_store.get_retention_status()

        assert status["total_receipts"] == 0
        assert "retention_policy" in status
        assert status["retention_policy"]["retention_days"] == DEFAULT_RETENTION_DAYS

    def test_get_retention_status_with_receipts(self, receipt_store, sample_receipt_dict):
        """Test get_retention_status with some receipts."""
        for i in range(3):
            sample_receipt_dict["receipt_id"] = f"retention-{i}"
            sample_receipt_dict["gauntlet_id"] = f"gauntlet-ret-{i}"
            receipt_store.save(sample_receipt_dict.copy())

        status = receipt_store.get_retention_status()

        assert status["total_receipts"] == 3
        assert "age_distribution" in status
        assert "expiring_receipts" in status
        assert "timestamps" in status
        assert status["timestamps"]["newest_receipt"] is not None

    def test_get_retention_status_includes_all_fields(self, receipt_store, sample_receipt_dict):
        """Test get_retention_status returns all required fields."""
        receipt_store.save(sample_receipt_dict)

        status = receipt_store.get_retention_status()

        # Check required fields exist
        assert "retention_policy" in status
        assert "retention_days" in status["retention_policy"]
        assert "retention_years" in status["retention_policy"]
        assert "age_distribution" in status
        assert "expiring_receipts" in status
        assert "already_expired" in status
        assert "timestamps" in status
        assert "generated_at" in status


class TestReceiptStoreLegalHold:
    """Tests for legal hold listing behavior."""

    def test_list_under_legal_hold_raises_on_corrupt_data_json(
        self,
        temp_db_path,
        sample_receipt_dict,
    ):
        """Legal-hold listing should fail closed on the same corruption as get()."""
        store = ReceiptStore(db_path=temp_db_path, backend="sqlite", file_receipt_dirs=[])
        try:
            store.save(sample_receipt_dict)
            assert store.place_legal_hold(
                sample_receipt_dict["receipt_id"],
                "litigation",
                "tester",
                matter_id="matter-123",
            )

            conn = sqlite3.connect(temp_db_path)
            try:
                conn.execute(
                    "UPDATE receipts SET data_json = ? WHERE receipt_id = ?",
                    ("{bad json", sample_receipt_dict["receipt_id"]),
                )
                conn.commit()
            finally:
                conn.close()

            with pytest.raises(json.JSONDecodeError):
                store.get(sample_receipt_dict["receipt_id"])

            with pytest.raises(json.JSONDecodeError):
                store.list_under_legal_hold()
        finally:
            store.close()


# ===========================================================================
# File-based receipt fallback tests (issue #1638)
# ===========================================================================


class TestFileReceiptFallback:
    """Tests for the .aragora/receipts/ JSON file-based fallback."""

    @pytest.fixture
    def receipts_dir(self, tmp_path):
        """Create a .aragora/receipts directory with sample JSON files."""
        d = tmp_path / ".aragora" / "receipts"
        d.mkdir(parents=True)
        return d

    @pytest.fixture
    def sample_file_receipt(self):
        """Return a quickstart-style receipt dict."""
        return {
            "receipt_id": "quickstart-abc123",
            "gauntlet_id": "quickstart-abc123",
            "timestamp": "2026-03-20T12:00:00+00:00",
            "verdict": "PASS",
            "confidence": 0.85,
            "risk_level": "LOW",
            "risk_score": 0.1,
            "checksum": "sha256:deadbeef",
            "input_summary": "Should we migrate?",
            "receipt": {
                "id": "quickstart-abc123",
                "artifact_hash": "sha256:deadbeef",
            },
        }

    @pytest.fixture
    def store_with_file_receipts(self, tmp_path, receipts_dir, sample_file_receipt):
        """Create a ReceiptStore that scans receipts_dir for JSON files."""
        # Write sample receipt to file
        (receipts_dir / "quickstart-demo-receipt.json").write_text(
            json.dumps(sample_file_receipt, indent=2)
        )
        # Create DB-backed store pointing to the temp receipts dir
        store = ReceiptStore(
            db_path=tmp_path / "test.db",
            backend="sqlite",
            file_receipt_dirs=[receipts_dir],
        )
        yield store
        store.close()

    def test_parse_file_receipt_basic(self, tmp_path, sample_file_receipt):
        """Test _parse_file_receipt converts a quickstart JSON dict correctly."""
        fake_path = tmp_path / "receipt.json"
        fake_path.write_text("{}")  # just so stat() works

        sr = ReceiptStore._parse_file_receipt(sample_file_receipt, fake_path)

        assert sr.receipt_id == "quickstart-abc123"
        assert sr.gauntlet_id == "quickstart-abc123"
        assert sr.verdict == "PASS"
        assert sr.confidence == 0.85
        assert sr.risk_level == "LOW"
        assert sr.checksum == "sha256:deadbeef"
        assert sr.data == sample_file_receipt

    def test_parse_file_receipt_clamps_out_of_range_confidence(self, tmp_path, sample_file_receipt):
        """File-backed receipts should normalize stale confidence values on read."""
        fake_path = tmp_path / "receipt.json"
        fake_path.write_text("{}")
        sample_file_receipt["confidence"] = 1.3
        sample_file_receipt["consensus_proof"] = {
            "reached": True,
            "confidence": 1.5,
        }

        sr = ReceiptStore._parse_file_receipt(sample_file_receipt, fake_path)

        assert sr.confidence == pytest.approx(1.0)
        assert sr.data["confidence"] == pytest.approx(1.0)
        assert sr.data["consensus_proof"]["confidence"] == pytest.approx(1.0)

    def test_parse_file_receipt_missing_receipt_id_uses_nested(self, tmp_path):
        """Test _parse_file_receipt falls back to receipt.id."""
        fake_path = tmp_path / "receipt.json"
        fake_path.write_text("{}")
        data = {"receipt": {"id": "nested-id"}, "verdict": "FAIL", "confidence": 0.3}

        sr = ReceiptStore._parse_file_receipt(data, fake_path)

        assert sr.receipt_id == "nested-id"

    def test_parse_file_receipt_falls_back_to_filename(self, tmp_path):
        """Test _parse_file_receipt uses filename stem when no IDs present."""
        fake_path = tmp_path / "my-receipt-file.json"
        fake_path.write_text("{}")
        data = {"verdict": "PASS", "confidence": 0.9}

        sr = ReceiptStore._parse_file_receipt(data, fake_path)

        assert sr.receipt_id == "my-receipt-file"

    def test_get_falls_back_to_file(self, store_with_file_receipts):
        """Test that get() finds receipts from .aragora/receipts/ when not in DB."""
        result = store_with_file_receipts.get("quickstart-abc123")
        assert result is not None
        assert result.receipt_id == "quickstart-abc123"
        assert result.verdict == "PASS"

    def test_get_prefers_db_over_file(self, store_with_file_receipts, sample_file_receipt):
        """Test that DB results take priority over file results."""
        store = store_with_file_receipts

        # Save to DB with different verdict
        db_receipt = dict(sample_file_receipt)
        db_receipt["verdict"] = "APPROVED"
        db_receipt["risk_level"] = "MEDIUM"
        store.save(db_receipt)

        result = store.get("quickstart-abc123")
        assert result is not None
        # DB result wins
        assert result.verdict == "APPROVED"

    def test_list_includes_file_receipts(self, store_with_file_receipts):
        """Test that list() includes file-based receipts."""
        results = store_with_file_receipts.list(limit=50)
        assert len(results) >= 1
        ids = [r.receipt_id for r in results]
        assert "quickstart-abc123" in ids

    def test_list_deduplicates_file_and_db(self, store_with_file_receipts, sample_file_receipt):
        """Test that list() does not duplicate receipts present in both DB and file."""
        store = store_with_file_receipts

        # Save to DB as well
        store.save(sample_file_receipt)

        results = store.list(limit=50)
        ids = [r.receipt_id for r in results]
        assert ids.count("quickstart-abc123") == 1

    def test_count_includes_file_receipts(self, store_with_file_receipts):
        """Test that count() includes file-based receipts."""
        total = store_with_file_receipts.count()
        assert total >= 1

    def test_count_deduplicates(self, store_with_file_receipts, sample_file_receipt):
        """Test that count() does not double-count file+DB receipts."""
        store = store_with_file_receipts
        store.save(sample_file_receipt)

        total = store.count()
        # Should be 1, not 2
        assert total == 1

    def test_list_filters_file_receipts_by_verdict(self, store_with_file_receipts):
        """Test that list() filters file-based receipts by verdict."""
        store = store_with_file_receipts

        # Receipt has verdict PASS - filtering for FAIL should exclude it
        results = store.list(verdict="FAIL")
        ids = [r.receipt_id for r in results]
        assert "quickstart-abc123" not in ids

        # Filtering for PASS should include it
        results = store.list(verdict="PASS")
        ids = [r.receipt_id for r in results]
        assert "quickstart-abc123" in ids

    def test_get_by_gauntlet_falls_back_to_file(self, store_with_file_receipts):
        """Test that get_by_gauntlet() finds file-based receipts."""
        result = store_with_file_receipts.get_by_gauntlet("quickstart-abc123")
        assert result is not None
        assert result.receipt_id == "quickstart-abc123"

    def test_malformed_json_file_skipped(self, store_with_file_receipts, receipts_dir):
        """Test that malformed JSON files are gracefully skipped."""
        # Write a malformed file alongside the good one
        (receipts_dir / "broken.json").write_text("not valid json{{{")

        # Should still return the valid receipt without errors
        results = store_with_file_receipts.list(limit=50)
        assert len(results) >= 1

    def test_non_dict_json_file_skipped(self, store_with_file_receipts, receipts_dir):
        """Test that JSON files containing non-dict values are skipped."""
        # Write a JSON array instead of object
        (receipts_dir / "array.json").write_text("[1, 2, 3]")

        results = store_with_file_receipts.list(limit=50)
        # Only the valid receipt should appear
        ids = [r.receipt_id for r in results]
        assert "quickstart-abc123" in ids

    def test_multiple_file_receipts(self, store_with_file_receipts, receipts_dir):
        """Test that multiple JSON receipt files are loaded."""
        # Add a second receipt file
        second = {
            "receipt_id": "quickstart-def456",
            "gauntlet_id": "quickstart-def456",
            "timestamp": "2026-03-21T12:00:00+00:00",
            "verdict": "FAIL",
            "confidence": 0.3,
            "risk_level": "HIGH",
        }
        (receipts_dir / "quickstart-live-receipt.json").write_text(json.dumps(second, indent=2))

        store = store_with_file_receipts
        results = store.list(limit=50)
        ids = [r.receipt_id for r in results]
        assert "quickstart-abc123" in ids
        assert "quickstart-def456" in ids
        assert store.count() == 2
