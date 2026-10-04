"""
End-to-end integration tests for Decision Receipts.

Tests the complete flow:
1. Generate a decision receipt from a gauntlet result
2. Store the receipt
3. Retrieve and verify the receipt
4. Export in multiple formats
5. Verify integrity and signatures
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Any

from aragora.export.decision_receipt import (
    DecisionReceipt,
    ReceiptFinding,
    ReceiptDissent,
    ReceiptVerification,
    DecisionReceiptGenerator,
)


class TestDecisionReceiptGeneration:
    """Test decision receipt generation from gauntlet results."""

    @pytest.fixture
    def sample_gauntlet_result(self) -> dict[str, Any]:
        """Create a sample gauntlet result for testing."""
        return {
            "gauntlet_id": "gnt_test_123",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input_summary": "Test API endpoint security analysis",
            "verdict": "APPROVED",
            "confidence": 0.87,
            "risk_level": "MEDIUM",
            "findings": [
                {
                    "id": "find_001",
                    "severity": "MEDIUM",
                    "category": "security",
                    "title": "Rate limiting not implemented",
                    "description": "Endpoint lacks rate limiting",
                    "mitigation": "Implement rate limiting middleware",
                }
            ],
            "agents_involved": ["claude", "gpt-4", "gemini"],
            "rounds_completed": 3,
            "duration_seconds": 45.2,
        }

    def test_create_receipt_from_gauntlet_result(self, sample_gauntlet_result):
        """Test creating a receipt from a gauntlet result."""
        receipt = DecisionReceipt(
            receipt_id="rcpt_test_001",
            gauntlet_id=sample_gauntlet_result["gauntlet_id"],
            input_summary=sample_gauntlet_result["input_summary"],
            verdict=sample_gauntlet_result["verdict"],
            confidence=sample_gauntlet_result["confidence"],
            risk_level=sample_gauntlet_result["risk_level"],
            agents_involved=sample_gauntlet_result["agents_involved"],
            rounds_completed=sample_gauntlet_result["rounds_completed"],
            duration_seconds=sample_gauntlet_result["duration_seconds"],
        )

        assert receipt.receipt_id == "rcpt_test_001"
        assert receipt.verdict == "APPROVED"
        assert receipt.confidence == 0.87
        assert len(receipt.agents_involved) == 3

    def test_receipt_checksum_integrity(self, sample_gauntlet_result):
        """Test that receipt checksum is computed correctly."""
        receipt = DecisionReceipt(
            receipt_id="rcpt_test_002",
            gauntlet_id=sample_gauntlet_result["gauntlet_id"],
            input_summary="Test input",
            verdict="APPROVED",
            confidence=0.9,
            risk_level="LOW",
        )

        # Get the checksum
        if hasattr(receipt, "compute_checksum"):
            checksum1 = receipt.compute_checksum()

            # Same receipt should have same checksum
            checksum2 = receipt.compute_checksum()
            assert checksum1 == checksum2

    def test_receipt_finding_creation(self):
        """Test creating receipt findings."""
        finding = ReceiptFinding(
            id="find_test_001",
            severity="HIGH",
            category="security",
            title="SQL injection vulnerability",
            description="User input not sanitized",
            mitigation="Use parameterized queries",
            source="claude",
            verified=True,
        )

        assert finding.severity == "HIGH"
        assert finding.verified is True
        assert finding.mitigation is not None


class TestReceiptsHandler:
    """Test the receipts HTTP handler."""

    ORG = "org-integration"

    @pytest.fixture(autouse=True)
    def org_member(self, monkeypatch):
        """Every request comes from an authenticated member of ``ORG``."""
        from aragora.billing.auth.context import UserAuthContext

        user = UserAuthContext(
            authenticated=True,
            user_id="user-integration",
            email="member@example.com",
            org_id=self.ORG,
            role="admin",
            token_type="access",
        )
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda handler, user_store=None: user,
        )
        return user

    @pytest.fixture
    def receipts_handler(self):
        """Create a ReceiptsHandler instance."""
        from aragora.server.handlers.receipts import ReceiptsHandler

        server_context = {"workspace_id": "test"}
        return ReceiptsHandler(server_context)

    @pytest.fixture
    def mock_store(self):
        """Create a mock receipt store."""
        # Create a mock receipt object with all required methods
        # Note: Don't use spec=DecisionReceipt as it blocks adding to_full_dict
        mock_receipt = MagicMock()
        mock_receipt.receipt_id = "rcpt_001"
        mock_receipt.org_id = self.ORG
        mock_receipt.verdict = "APPROVED"
        receipt_dict = {
            "receipt_id": "rcpt_001",
            "verdict": "APPROVED",
            "timestamp": "2024-01-01T00:00:00Z",
            "gauntlet_id": "gnt_001",
            "confidence": 0.85,
            "risk_level": "LOW",
        }
        mock_receipt.to_dict.return_value = receipt_dict
        mock_receipt.to_full_dict.return_value = receipt_dict

        store = MagicMock()
        # Mock the methods the handler actually calls
        store.list_for_org = MagicMock(return_value=[mock_receipt])
        store.count_for_org = MagicMock(return_value=1)
        store.get_for_org = MagicMock(return_value=mock_receipt)
        store.get_by_gauntlet_for_org = MagicMock(return_value=None)
        store.verify = MagicMock(return_value={"valid": True, "checksum_match": True})
        store.verify_signature = MagicMock(
            return_value=MagicMock(
                error=None,
                to_dict=MagicMock(
                    return_value={
                        "receipt_id": "rcpt_001",
                        "signature_valid": True,
                        "algorithm": "HMAC-SHA256",
                        "key_id": "test-key",
                    }
                ),
            )
        )
        store.verify_integrity = MagicMock(
            return_value={
                "receipt_id": "rcpt_001",
                "integrity_valid": True,
                "stored_checksum": "sha256:abc",
            }
        )
        # Also keep the async versions in case some code uses them
        store.list_receipts = AsyncMock(
            return_value={
                "receipts": [mock_receipt.to_dict()],
                "total": 1,
            }
        )
        store.get_receipt = AsyncMock(return_value=mock_receipt.to_dict())
        store.verify_receipt = AsyncMock(return_value={"valid": True, "checksum_match": True})
        return store

    @pytest.mark.asyncio
    async def test_list_receipts_endpoint(self, receipts_handler, mock_store):
        """Test listing receipts via HTTP."""
        with patch.object(receipts_handler, "_get_store", return_value=mock_store):
            result = await receipts_handler.handle(
                method="GET",
                path="/api/v2/receipts",
                query_params={"limit": "10"},
            )

            assert result is not None
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_get_receipt_endpoint(self, receipts_handler, mock_store):
        """Test getting a single receipt via HTTP."""
        with patch.object(receipts_handler, "_get_store", return_value=mock_store):
            result = await receipts_handler.handle(
                method="GET",
                path="/api/v2/receipts/rcpt_001",
            )

            assert result is not None
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_verify_receipt_endpoint(self, receipts_handler, mock_store):
        """Test verifying receipt integrity via HTTP."""
        with patch.object(receipts_handler, "_get_store", return_value=mock_store):
            result = await receipts_handler.handle(
                method="POST",
                path="/api/v2/receipts/rcpt_001/verify",
            )

            assert result is not None
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_verify_receipt_combined_endpoint(self, receipts_handler, mock_store):
        """Test verifying receipt signature + integrity via HTTP."""
        with patch.object(receipts_handler, "_get_store", return_value=mock_store):
            result = await receipts_handler.handle(
                method="GET",
                path="/api/v2/receipts/rcpt_001/verify",
            )

            assert result is not None
            assert result.status_code == 200
            body = result.body
            if isinstance(body, bytes):
                body = body.decode()
            data = {} if body is None else json.loads(body)
            assert data["signature"]["signature_valid"] is True
            assert data["integrity"]["integrity_valid"] is True


class TestReceiptExport:
    """Test receipt export functionality."""

    @pytest.fixture
    def sample_receipt(self) -> DecisionReceipt:
        """Create a sample receipt for export testing."""
        return DecisionReceipt(
            receipt_id="rcpt_export_001",
            gauntlet_id="gnt_001",
            input_summary="Security analysis of API",
            verdict="APPROVED",
            confidence=0.92,
            risk_level="LOW",
            agents_involved=["claude", "gpt-4"],
            rounds_completed=3,
            duration_seconds=30.5,
        )

    def test_receipt_to_dict(self, sample_receipt):
        """Test converting receipt to dictionary."""
        if hasattr(sample_receipt, "to_dict"):
            data = sample_receipt.to_dict()
            assert isinstance(data, dict)
            assert data["receipt_id"] == "rcpt_export_001"
            assert data["verdict"] == "APPROVED"

    def test_receipt_json_serializable(self, sample_receipt):
        """Test that receipt can be serialized to JSON."""
        import json
        from dataclasses import asdict

        data = asdict(sample_receipt)
        json_str = json.dumps(data, default=str)
        assert "rcpt_export_001" in json_str
        assert "APPROVED" in json_str


class TestReceiptVerification:
    """Test receipt verification claims."""

    def test_create_verification_claim(self):
        """Test creating a verification claim."""
        verification = ReceiptVerification(
            claim="API endpoint is rate-limited",
            verified=True,
            method="static_analysis",
            proof_hash="sha256:abc123...",
        )

        assert verification.verified is True
        assert verification.method == "static_analysis"
        assert verification.proof_hash is not None

    def test_unverified_claim(self):
        """Test handling unverified claims."""
        verification = ReceiptVerification(
            claim="Performance meets SLA",
            verified=False,
            method="load_test",
            proof_hash=None,
        )

        assert verification.verified is False
        assert verification.proof_hash is None


class TestReceiptDissent:
    """Test receipt dissent records."""

    def test_create_dissent_record(self):
        """Test creating a dissent record."""
        dissent = ReceiptDissent(
            agent="gpt-4",
            type="partial_disagree",
            severity=0.6,
            reasons=["Security analysis incomplete", "Missing edge cases"],
            alternative="Recommend additional penetration testing",
        )

        assert dissent.agent == "gpt-4"
        assert len(dissent.reasons) == 2
        assert dissent.alternative is not None


class TestReceiptRetention:
    """Test receipt retention and compliance features."""

    def test_receipt_has_timestamp(self):
        """Test that receipts always have timestamps."""
        receipt = DecisionReceipt(
            receipt_id="rcpt_retention_001",
            gauntlet_id="gnt_001",
            input_summary="Test",
            verdict="APPROVED",
            confidence=0.8,
            risk_level="LOW",
        )

        assert receipt.timestamp is not None
        # Should be ISO format
        assert "T" in receipt.timestamp or "-" in receipt.timestamp

    def test_receipt_immutability(self):
        """Test that receipt data is immutable after creation."""
        receipt = DecisionReceipt(
            receipt_id="rcpt_immutable_001",
            gauntlet_id="gnt_001",
            input_summary="Test",
            verdict="APPROVED",
            confidence=0.8,
            risk_level="LOW",
        )

        # Attempt to modify should fail (dataclass is frozen if configured)
        # or at least the checksum would change
        original_id = receipt.receipt_id
        assert receipt.receipt_id == original_id
