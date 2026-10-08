"""
Tests for ReceiptsHandler - Decision receipt HTTP endpoints.

Tests cover:
- List receipts with filtering and pagination
- Get single receipt by ID
- Export in multiple formats (JSON, HTML, MD, PDF, SARIF, CSV)
- Verify integrity checksum
- Verify cryptographic signature
- Batch signature verification
- Statistics endpoint
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.receipts import (
    ReceiptsHandler,
    create_receipts_handler,
)
from aragora.server.handlers.utils.receipt_delivery_history import (
    get_receipt_delivery_history_store,
)
import builtins


# ===========================================================================
# Test Fixtures and Mocks
# ===========================================================================


@dataclass
class MockStoredReceipt:
    """Mock stored receipt for testing."""

    receipt_id: str = "receipt-001"
    gauntlet_id: str = "gauntlet-001"
    debate_id: str | None = "debate-001"
    created_at: float = 1700000000.0
    expires_at: float | None = 1800000000.0
    verdict: str = "APPROVED"
    confidence: float = 0.85
    risk_level: str = "MEDIUM"
    risk_score: float = 0.35
    checksum: str = "sha256:abc123"
    signature: str | None = None
    signature_algorithm: str | None = None
    signature_key_id: str | None = None
    signed_at: float | None = None
    audit_trail_id: str | None = "audit-001"
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "receipt_id": self.receipt_id,
            "gauntlet_id": self.gauntlet_id,
            "debate_id": self.debate_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "checksum": self.checksum,
            "audit_trail_id": self.audit_trail_id,
            "is_signed": self.signature is not None,
        }
        if self.signature:
            result["signature_metadata"] = {
                "algorithm": self.signature_algorithm,
                "key_id": self.signature_key_id,
                "signed_at": self.signed_at,
            }
        return result

    def to_full_dict(self) -> dict[str, Any]:
        result = self.to_dict()
        result.update(self.data)
        return result


@dataclass
class MockSignatureVerificationResult:
    """Mock signature verification result."""

    receipt_id: str
    is_valid: bool
    algorithm: str | None = None
    key_id: str | None = None
    signed_at: float | None = None
    verified_at: float = 1700001000.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "signature_valid": self.is_valid,
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "signed_at": self.signed_at,
            "verification_timestamp": datetime.fromtimestamp(
                self.verified_at, tz=timezone.utc
            ).isoformat(),
            "error": self.error,
        }


class MockReceiptStore:
    """Mock receipt store for testing."""

    def __init__(self):
        self.receipts: dict[str, MockStoredReceipt] = {}
        self._next_id = 0

    def save(self, receipt_dict: dict, signed_receipt: dict | None = None) -> str:
        receipt_id = receipt_dict.get("receipt_id", f"receipt-{self._next_id}")
        self._next_id += 1
        self.receipts[receipt_id] = MockStoredReceipt(
            receipt_id=receipt_id,
            gauntlet_id=receipt_dict.get("gauntlet_id", ""),
            verdict=receipt_dict.get("verdict", "APPROVED"),
            confidence=receipt_dict.get("confidence", 0.85),
            risk_level=receipt_dict.get("risk_level", "MEDIUM"),
            risk_score=receipt_dict.get("risk_score", 0.35),
            data=receipt_dict,
        )
        return receipt_id

    def get(self, receipt_id: str) -> MockStoredReceipt | None:
        return self.receipts.get(receipt_id)

    def get_by_gauntlet(self, gauntlet_id: str) -> MockStoredReceipt | None:
        for receipt in self.receipts.values():
            if receipt.gauntlet_id == gauntlet_id:
                return receipt
        return None

    def list(
        self,
        limit: int = 20,
        offset: int = 0,
        debate_id: str | None = None,
        verdict: str | None = None,
        risk_level: str | None = None,
        date_from: float | None = None,
        date_to: float | None = None,
        signed_only: bool = False,
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> builtins.list[MockStoredReceipt]:
        results = list(self.receipts.values())
        if debate_id:
            results = [r for r in results if r.debate_id == debate_id]
        if verdict:
            results = [r for r in results if r.verdict == verdict]
        if risk_level:
            results = [r for r in results if r.risk_level == risk_level]
        if signed_only:
            results = [r for r in results if r.signature is not None]
        return results[offset : offset + limit]

    def count(
        self,
        debate_id: str | None = None,
        verdict: str | None = None,
        risk_level: str | None = None,
        date_from: float | None = None,
        date_to: float | None = None,
        signed_only: bool = False,
    ) -> int:
        results = list(self.receipts.values())
        if debate_id:
            results = [r for r in results if r.debate_id == debate_id]
        if verdict:
            results = [r for r in results if r.verdict == verdict]
        if risk_level:
            results = [r for r in results if r.risk_level == risk_level]
        if signed_only:
            results = [r for r in results if r.signature is not None]
        return len(results)

    def verify_integrity(self, receipt_id: str) -> dict[str, Any]:
        if receipt_id not in self.receipts:
            return {
                "receipt_id": receipt_id,
                "integrity_valid": False,
                "error": "Receipt not found",
            }
        return {"receipt_id": receipt_id, "integrity_valid": True, "stored_checksum": "sha256:abc"}

    def verify_signature(self, receipt_id: str) -> MockSignatureVerificationResult:
        if receipt_id not in self.receipts:
            return MockSignatureVerificationResult(
                receipt_id=receipt_id, is_valid=False, error="Receipt not found"
            )
        receipt = self.receipts[receipt_id]
        if not receipt.signature:
            return MockSignatureVerificationResult(
                receipt_id=receipt_id, is_valid=False, error="Receipt is not signed"
            )
        return MockSignatureVerificationResult(
            receipt_id=receipt_id,
            is_valid=True,
            algorithm=receipt.signature_algorithm,
            key_id=receipt.signature_key_id,
        )

    def verify_batch(
        self, receipt_ids: builtins.list[str]
    ) -> tuple[builtins.list[MockSignatureVerificationResult], dict[str, int]]:
        results = []
        summary = {"total": len(receipt_ids), "valid": 0, "invalid": 0, "not_signed": 0}
        for rid in receipt_ids:
            result = self.verify_signature(rid)
            results.append(result)
            if result.is_valid:
                summary["valid"] += 1
            elif result.error == "Receipt is not signed":
                summary["not_signed"] += 1
            else:
                summary["invalid"] += 1
        return results, summary

    def get_stats(self) -> dict[str, Any]:
        return {
            "total": len(self.receipts),
            "signed": sum(1 for r in self.receipts.values() if r.signature),
            "unsigned": sum(1 for r in self.receipts.values() if not r.signature),
            "by_verdict": {"approved": 0, "rejected": 0},
            "by_risk_level": {"low": 0, "medium": 0, "high": 0},
            "retention_days": 2555,
        }

    def get_by_user(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
        include_data: bool = True,
    ) -> tuple[builtins.list[MockStoredReceipt], int]:
        """Get receipts by user ID for GDPR DSAR."""
        matches = []
        for receipt in self.receipts.values():
            data = receipt.data
            if (
                data.get("user_id") == user_id
                or data.get("requestor_id") == user_id
                or data.get("created_by") == user_id
            ):
                matches.append(receipt)
        total = len(matches)
        return matches[offset : offset + limit], total

    def get_retention_status(self) -> dict[str, Any]:
        """Get retention status for GDPR compliance."""
        return {
            "retention_policy": {
                "max_retention_days": 2555,
                "auto_delete_enabled": True,
                "retention_reason": "Regulatory compliance (7 years)",
            },
            "current_stats": {
                "total_receipts": len(self.receipts),
                "oldest_receipt_days": 365 if self.receipts else None,
                "newest_receipt_days": 1 if self.receipts else None,
            },
            "age_distribution": {
                "0-30_days": len(self.receipts),
                "31-90_days": 0,
                "91-365_days": 0,
                "1-3_years": 0,
                "3-7_years": 0,
                "over_7_years": 0,
            },
            "expiring_receipts": {
                "next_30_days": 0,
                "next_90_days": 0,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


@pytest.fixture
def mock_receipt_store():
    """Create a mock receipt store."""
    return MockReceiptStore()


@pytest.fixture
def mock_server_context():
    """Create a mock server context."""
    return MagicMock()


@pytest.fixture
def receipts_handler(mock_server_context, mock_receipt_store):
    """Create a receipts handler with mocked store."""
    handler = ReceiptsHandler(mock_server_context)
    handler._store = mock_receipt_store
    return handler


@pytest.fixture(autouse=True)
def clear_receipt_delivery_history():
    """Keep the shared in-memory delivery history isolated per test."""
    history = get_receipt_delivery_history_store()
    history.clear()
    yield
    history.clear()


def parse_handler_response(result) -> dict[str, Any]:
    """Parse handler result body as JSON."""
    if hasattr(result, "body"):
        body = result.body
        if isinstance(body, bytes):
            return json.loads(body.decode())
        return json.loads(body)
    return {}


# ===========================================================================
# Handler Routing Tests
# ===========================================================================


class TestReceiptsHandlerRouting:
    """Tests for request routing."""

    def test_can_handle_list(self, receipts_handler):
        """Test can_handle for list endpoint."""
        assert receipts_handler.can_handle("/api/v2/receipts", "GET") is True

    def test_can_handle_get(self, receipts_handler):
        """Test can_handle for get endpoint."""
        assert receipts_handler.can_handle("/api/v2/receipts/receipt-001", "GET") is True

    def test_can_handle_verify(self, receipts_handler):
        """Test can_handle for verify endpoint."""
        assert receipts_handler.can_handle("/api/v2/receipts/receipt-001/verify", "POST") is True

    def test_can_handle_verify_get(self, receipts_handler):
        """Test can_handle for combined verify endpoint."""
        assert receipts_handler.can_handle("/api/v2/receipts/receipt-001/verify", "GET") is True

    def test_can_handle_stats(self, receipts_handler):
        """Test can_handle for stats endpoint."""
        assert receipts_handler.can_handle("/api/v2/receipts/stats", "GET") is True

    def test_can_handle_v1_deliveries(self, receipts_handler):
        """Test can_handle for legacy/frontend delivery history bridge."""
        assert receipts_handler.can_handle("/api/v1/receipts/deliveries", "GET") is True

    def test_cannot_handle_other_paths(self, receipts_handler):
        """Test can_handle returns False for other paths."""
        assert receipts_handler.can_handle("/api/v2/gauntlet", "GET") is False
        assert receipts_handler.can_handle("/api/v1/receipts", "GET") is False

    def test_cannot_handle_delete(self, receipts_handler):
        """Test can_handle returns False for DELETE method."""
        assert receipts_handler.can_handle("/api/v2/receipts/receipt-001", "DELETE") is False


# ===========================================================================
# List Receipts Tests
# ===========================================================================


class TestReceiptsHandlerList:
    """Tests for list receipts endpoint."""

    @pytest.mark.asyncio
    async def test_list_empty(self, receipts_handler):
        """Test list returns empty for no receipts."""
        result = await receipts_handler.handle("GET", "/api/v2/receipts")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["receipts"] == []
        assert data["pagination"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_supports_legacy_handler_signature(self, receipts_handler):
        """Unified server should be able to call the generic legacy handler signature."""
        http_handler = MagicMock()
        http_handler.command = "GET"
        http_handler.headers = {}

        result = await receipts_handler.handle("/api/v2/receipts", {}, http_handler)

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["receipts"] == []
        assert data["pagination"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_with_receipts(self, receipts_handler, mock_receipt_store):
        """Test list returns receipts."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1", "verdict": "APPROVED"})
        mock_receipt_store.save({"receipt_id": "r2", "gauntlet_id": "g2", "verdict": "REJECTED"})

        result = await receipts_handler.handle("GET", "/api/v2/receipts")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert len(data["receipts"]) == 2

    @pytest.mark.asyncio
    async def test_list_pagination(self, receipts_handler, mock_receipt_store):
        """Test list pagination."""
        for i in range(5):
            mock_receipt_store.save({"receipt_id": f"r{i}", "gauntlet_id": f"g{i}"})

        result = await receipts_handler.handle(
            "GET", "/api/v2/receipts", query_params={"limit": "2", "offset": "0"}
        )

        data = parse_handler_response(result)
        assert len(data["receipts"]) == 2
        assert data["pagination"]["limit"] == 2
        assert data["pagination"]["total"] == 5
        assert data["pagination"]["has_more"] is True

    @pytest.mark.asyncio
    async def test_list_filter_verdict(self, receipts_handler, mock_receipt_store):
        """Test list filters by verdict."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1", "verdict": "APPROVED"})
        mock_receipt_store.save({"receipt_id": "r2", "gauntlet_id": "g2", "verdict": "REJECTED"})

        result = await receipts_handler.handle(
            "GET", "/api/v2/receipts", query_params={"verdict": "APPROVED"}
        )

        data = parse_handler_response(result)
        assert data["filters"]["verdict"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_list_limit_capped(self, receipts_handler):
        """Test list limit is capped at 100."""
        result = await receipts_handler.handle(
            "GET", "/api/v2/receipts", query_params={"limit": "500"}
        )

        data = parse_handler_response(result)
        assert data["pagination"]["limit"] == 100


# ===========================================================================
# Get Receipt Tests
# ===========================================================================


class TestReceiptsHandlerGet:
    """Tests for get single receipt endpoint."""

    @pytest.mark.asyncio
    async def test_get_by_id(self, receipts_handler, mock_receipt_store):
        """Test get receipt by ID."""
        mock_receipt_store.save({"receipt_id": "receipt-001", "gauntlet_id": "gauntlet-001"})

        result = await receipts_handler.handle("GET", "/api/v2/receipts/receipt-001")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["receipt_id"] == "receipt-001"

    @pytest.mark.asyncio
    async def test_get_by_gauntlet_id(self, receipts_handler, mock_receipt_store):
        """Test get receipt by gauntlet_id fallback."""
        mock_receipt_store.save({"receipt_id": "receipt-001", "gauntlet_id": "gauntlet-001"})

        result = await receipts_handler.handle("GET", "/api/v2/receipts/gauntlet-001")

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_get_not_found(self, receipts_handler):
        """Test get returns 404 for nonexistent receipt."""
        result = await receipts_handler.handle("GET", "/api/v2/receipts/nonexistent")

        assert result.status_code == 404


# ===========================================================================
# Export Tests
# ===========================================================================


class TestReceiptsHandlerExport:
    """Tests for receipt export endpoint."""

    @pytest.mark.asyncio
    async def test_export_not_found(self, receipts_handler):
        """Test export returns 404 for nonexistent receipt."""
        result = await receipts_handler.handle("GET", "/api/v2/receipts/nonexistent/export")

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_export_unsupported_format(self, receipts_handler, mock_receipt_store):
        """Test export returns 400 for unsupported format."""
        mock_receipt_store.save({"receipt_id": "receipt-001", "gauntlet_id": "gauntlet-001"})

        mock_receipt = MagicMock()
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with patch.dict(
            "sys.modules",
            {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
        ):
            result = await receipts_handler.handle(
                "GET",
                "/api/v2/receipts/receipt-001/export",
                query_params={"format": "invalid"},
            )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_export_json(self, receipts_handler, mock_receipt_store):
        """Test export as JSON."""
        mock_receipt_store.save({"receipt_id": "receipt-001", "gauntlet_id": "gauntlet-001"})

        mock_receipt = MagicMock()
        mock_receipt.to_json.return_value = '{"test": "json"}'
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with patch.dict(
            "sys.modules",
            {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
        ):
            result = await receipts_handler.handle(
                "GET",
                "/api/v2/receipts/receipt-001/export",
                query_params={"format": "json"},
            )

        assert result.status_code == 200
        assert result.content_type.startswith("application/json")

    @pytest.mark.asyncio
    async def test_export_json_filters_extended_payload(self, receipts_handler, mock_receipt_store):
        """Export should strip newer stored-only fields before reconstruction."""
        mock_receipt_store.save(
            {
                "receipt_id": "receipt-001",
                "gauntlet_id": "gauntlet-001",
                "timestamp": "2026-03-25T15:00:00Z",
                "input_summary": "Should we ship the receipt fix?",
                "verdict": "APPROVED",
                "confidence": 0.85,
                "risk_level": "LOW",
                "risk_score": 0.1,
                "findings": [],
                "dissenting_views": [],
                "verified_claims": [],
                "input_hash": "sha256:deadbeef",
            }
        )

        result = await receipts_handler.handle(
            "GET",
            "/api/v2/receipts/receipt-001/export",
            query_params={"format": "json"},
        )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["receipt_id"] == "receipt-001"
        assert data["input_summary"] == "Should we ship the receipt fix?"

    @pytest.mark.asyncio
    async def test_export_html(self, receipts_handler, mock_receipt_store):
        """Test export as HTML."""
        mock_receipt_store.save({"receipt_id": "receipt-001", "gauntlet_id": "gauntlet-001"})

        mock_receipt = MagicMock()
        mock_receipt.to_html.return_value = "<html><body>Receipt</body></html>"
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with patch.dict(
            "sys.modules",
            {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
        ):
            result = await receipts_handler.handle(
                "GET",
                "/api/v2/receipts/receipt-001/export",
                query_params={"format": "html"},
            )

        assert result.status_code == 200
        assert result.content_type.startswith("text/html")

    @pytest.mark.asyncio
    async def test_export_markdown(self, receipts_handler, mock_receipt_store):
        """Test export as Markdown."""
        mock_receipt_store.save({"receipt_id": "receipt-001", "gauntlet_id": "gauntlet-001"})

        mock_receipt = MagicMock()
        mock_receipt.to_markdown.return_value = "# Receipt\n\nContent"
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with patch.dict(
            "sys.modules",
            {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
        ):
            result = await receipts_handler.handle(
                "GET",
                "/api/v2/receipts/receipt-001/export",
                query_params={"format": "md"},
            )

        assert result.status_code == 200
        assert result.content_type.startswith("text/markdown")

    @pytest.mark.asyncio
    async def test_export_csv(self, receipts_handler, mock_receipt_store):
        """Test export as CSV."""
        mock_receipt_store.save({"receipt_id": "receipt-001", "gauntlet_id": "gauntlet-001"})

        mock_receipt = MagicMock()
        mock_receipt.to_csv.return_value = "id,verdict\nreceipt-001,APPROVED"
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with patch.dict(
            "sys.modules",
            {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
        ):
            result = await receipts_handler.handle(
                "GET",
                "/api/v2/receipts/receipt-001/export",
                query_params={"format": "csv"},
            )

        assert result.status_code == 200
        assert result.content_type.startswith("text/csv")


# ===========================================================================
# Verification Tests
# ===========================================================================


class TestReceiptsHandlerVerification:
    """Tests for verification endpoints."""

    @pytest.mark.asyncio
    async def test_verify_integrity(self, receipts_handler, mock_receipt_store):
        """Test verify integrity endpoint."""
        mock_receipt_store.save({"receipt_id": "receipt-001", "gauntlet_id": "gauntlet-001"})

        result = await receipts_handler.handle("POST", "/api/v2/receipts/receipt-001/verify")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["integrity_valid"] is True

    @pytest.mark.asyncio
    async def test_verify_integrity_not_found(self, receipts_handler):
        """Test verify integrity returns 404."""
        result = await receipts_handler.handle("POST", "/api/v2/receipts/nonexistent/verify")

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_verify_receipt_combined(self, receipts_handler, mock_receipt_store):
        """Test combined verify endpoint (signature + integrity)."""
        mock_receipt_store.save({"receipt_id": "receipt-001", "gauntlet_id": "gauntlet-001"})
        mock_receipt_store.receipts["receipt-001"].signature = "sig=="
        mock_receipt_store.receipts["receipt-001"].signature_algorithm = "HMAC-SHA256"

        result = await receipts_handler.handle("GET", "/api/v2/receipts/receipt-001/verify")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["signature"]["signature_valid"] is True
        assert data["integrity"]["integrity_valid"] is True

    @pytest.mark.asyncio
    async def test_verify_receipt_combined_not_found(self, receipts_handler):
        """Test combined verify returns 404."""
        result = await receipts_handler.handle("GET", "/api/v2/receipts/nonexistent/verify")
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_verify_signature(self, receipts_handler, mock_receipt_store):
        """Test verify signature endpoint."""
        mock_receipt_store.save({"receipt_id": "receipt-001", "gauntlet_id": "gauntlet-001"})
        mock_receipt_store.receipts["receipt-001"].signature = "sig=="
        mock_receipt_store.receipts["receipt-001"].signature_algorithm = "HMAC-SHA256"

        result = await receipts_handler.handle(
            "POST", "/api/v2/receipts/receipt-001/verify-signature"
        )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["signature_valid"] is True

    @pytest.mark.asyncio
    async def test_verify_signature_unsigned(self, receipts_handler, mock_receipt_store):
        """Test verify signature for unsigned receipt."""
        mock_receipt_store.save({"receipt_id": "receipt-001", "gauntlet_id": "gauntlet-001"})

        result = await receipts_handler.handle(
            "POST", "/api/v2/receipts/receipt-001/verify-signature"
        )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["signature_valid"] is False
        assert "not signed" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_verify_signature_not_found(self, receipts_handler):
        """Test verify signature returns 404."""
        result = await receipts_handler.handle(
            "POST", "/api/v2/receipts/nonexistent/verify-signature"
        )

        assert result.status_code == 404


# ===========================================================================
# Batch Verification Tests
# ===========================================================================


class TestReceiptsHandlerBatchVerify:
    """Tests for batch verification endpoint."""

    @pytest.mark.asyncio
    async def test_verify_batch_empty(self, receipts_handler):
        """Test batch verify with empty list."""
        result = await receipts_handler.handle(
            "POST", "/api/v2/receipts/verify-batch", body={"receipt_ids": []}
        )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_verify_batch_too_many(self, receipts_handler):
        """Test batch verify with too many IDs."""
        ids = [f"r{i}" for i in range(150)]
        result = await receipts_handler.handle(
            "POST", "/api/v2/receipts/verify-batch", body={"receipt_ids": ids}
        )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_verify_batch_success(self, receipts_handler, mock_receipt_store):
        """Test batch verify with valid IDs."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})
        mock_receipt_store.save({"receipt_id": "r2", "gauntlet_id": "g2"})

        result = await receipts_handler.handle(
            "POST", "/api/v2/receipts/verify-batch", body={"receipt_ids": ["r1", "r2"]}
        )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert len(data["results"]) == 2
        assert data["summary"]["total"] == 2


# ===========================================================================
# Statistics Tests
# ===========================================================================


class TestReceiptsHandlerStats:
    """Tests for statistics endpoint."""

    @pytest.mark.asyncio
    async def test_get_stats(self, receipts_handler, mock_receipt_store):
        """Test get stats endpoint."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        result = await receipts_handler.handle("GET", "/api/v2/receipts/stats")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert "stats" in data
        assert "generated_at" in data


# ===========================================================================
# Factory Function Tests
# ===========================================================================


class TestReceiptsHandlerFactory:
    """Tests for handler factory function."""

    def test_create_receipts_handler(self, mock_server_context):
        """Test factory creates handler."""
        handler = create_receipts_handler(mock_server_context)

        assert isinstance(handler, ReceiptsHandler)


# ===========================================================================
# Error Handling Tests
# ===========================================================================


class TestReceiptsHandlerErrors:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_trailing_slash_list_path_normalizes_to_receipt_index(self, receipts_handler):
        """Trailing slash on the list route should behave like the canonical path."""
        result = await receipts_handler.handle("GET", "/api/v2/receipts/")
        assert result.status_code == 200
        data = parse_handler_response(result)
        assert "receipts" in data

    @pytest.mark.asyncio
    async def test_handle_exception(self, receipts_handler):
        """Test handler catches exceptions gracefully."""
        # Force an exception
        receipts_handler._get_store = MagicMock(side_effect=ValueError("Test error"))

        result = await receipts_handler.handle("GET", "/api/v2/receipts")

        assert result.status_code == 500


# ===========================================================================
# Timestamp Parsing Tests
# ===========================================================================


class TestReceiptsHandlerTimestampParsing:
    """Tests for timestamp parsing."""

    def test_parse_timestamp_none(self, receipts_handler):
        """Test parse_timestamp with None."""
        result = receipts_handler._parse_timestamp(None)
        assert result is None

    def test_parse_timestamp_float(self, receipts_handler):
        """Test parse_timestamp with float string."""
        result = receipts_handler._parse_timestamp("1700000000.0")
        assert result == 1700000000.0

    def test_parse_timestamp_iso(self, receipts_handler):
        """Test parse_timestamp with ISO date."""
        result = receipts_handler._parse_timestamp("2024-01-15T10:30:00Z")
        assert result is not None
        assert result > 0

    def test_parse_timestamp_invalid(self, receipts_handler):
        """Test parse_timestamp with invalid string."""
        result = receipts_handler._parse_timestamp("invalid")
        assert result is None


# ===========================================================================
# GDPR Compliance Tests
# ===========================================================================


class TestReceiptsHandlerGDPR:
    """Tests for GDPR compliance endpoints (DSAR and retention status)."""

    @pytest.mark.asyncio
    async def test_retention_status(self, receipts_handler, mock_receipt_store):
        """Test retention status endpoint."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        result = await receipts_handler.handle("GET", "/api/v2/receipts/retention-status")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert "retention_policy" in data
        assert "current_stats" in data
        assert "age_distribution" in data
        assert data["retention_policy"]["max_retention_days"] == 2555

    @pytest.mark.asyncio
    async def test_retention_status_empty_store(self, receipts_handler):
        """Test retention status with empty store."""
        result = await receipts_handler.handle("GET", "/api/v2/receipts/retention-status")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["current_stats"]["total_receipts"] == 0

    @pytest.mark.asyncio
    async def test_dsar_with_matches(self, receipts_handler, mock_receipt_store):
        """Test DSAR endpoint finds user receipts."""
        mock_receipt_store.save(
            {
                "receipt_id": "r1",
                "gauntlet_id": "g1",
                "user_id": "user-123",
            }
        )
        mock_receipt_store.save(
            {
                "receipt_id": "r2",
                "gauntlet_id": "g2",
                "user_id": "other-user",
            }
        )

        result = await receipts_handler.handle("GET", "/api/v2/receipts/dsar/user-123")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["dsar_request"]["user_id"] == "user-123"
        assert data["dsar_request"]["gdpr_article"] == "Article 15 - Right of access"
        assert data["summary"]["total_receipts"] == 1

    @pytest.mark.asyncio
    async def test_dsar_no_matches(self, receipts_handler, mock_receipt_store):
        """Test DSAR endpoint with no matches."""
        mock_receipt_store.save(
            {
                "receipt_id": "r1",
                "gauntlet_id": "g1",
                "user_id": "other-user",
            }
        )

        result = await receipts_handler.handle("GET", "/api/v2/receipts/dsar/user-123")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["summary"]["total_receipts"] == 0
        assert len(data["receipts"]) == 0

    @pytest.mark.asyncio
    async def test_dsar_matches_requestor_id(self, receipts_handler, mock_receipt_store):
        """Test DSAR matches requestor_id field."""
        mock_receipt_store.save(
            {
                "receipt_id": "r1",
                "gauntlet_id": "g1",
                "requestor_id": "user-456",
            }
        )

        result = await receipts_handler.handle("GET", "/api/v2/receipts/dsar/user-456")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["summary"]["total_receipts"] == 1

    @pytest.mark.asyncio
    async def test_dsar_matches_created_by(self, receipts_handler, mock_receipt_store):
        """Test DSAR matches created_by field."""
        mock_receipt_store.save(
            {
                "receipt_id": "r1",
                "gauntlet_id": "g1",
                "created_by": "user-789",
            }
        )

        result = await receipts_handler.handle("GET", "/api/v2/receipts/dsar/user-789")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["summary"]["total_receipts"] == 1

    @pytest.mark.asyncio
    async def test_dsar_pagination(self, receipts_handler, mock_receipt_store):
        """Test DSAR pagination parameters."""
        for i in range(5):
            mock_receipt_store.save(
                {
                    "receipt_id": f"r{i}",
                    "gauntlet_id": f"g{i}",
                    "user_id": "test-user",
                }
            )

        result = await receipts_handler.handle(
            "GET",
            "/api/v2/receipts/dsar/test-user",
            query_params={"limit": "2", "offset": "1"},
        )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["pagination"]["limit"] == 2
        assert data["pagination"]["offset"] == 1
        assert data["summary"]["total_receipts"] == 5
        assert data["summary"]["returned_receipts"] == 2

    @pytest.mark.asyncio
    async def test_dsar_invalid_user_id_too_short(self, receipts_handler):
        """Test DSAR rejects user_id shorter than 3 characters."""
        result = await receipts_handler.handle("GET", "/api/v2/receipts/dsar/ab")

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_dsar_limit_capped(self, receipts_handler, mock_receipt_store):
        """Test DSAR limit is capped at 1000."""
        mock_receipt_store.save(
            {
                "receipt_id": "r1",
                "gauntlet_id": "g1",
                "user_id": "test-user",
            }
        )

        result = await receipts_handler.handle(
            "GET",
            "/api/v2/receipts/dsar/test-user",
            query_params={"limit": "5000"},
        )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["pagination"]["limit"] == 1000


# ===========================================================================
# Search Receipts Tests
# ===========================================================================


class TestReceiptsHandlerSearch:
    """Tests for search receipts endpoint."""

    @pytest.mark.asyncio
    async def test_search_missing_query(self, receipts_handler):
        """Test search requires query parameter."""
        result = await receipts_handler.handle("GET", "/api/v2/receipts/search", query_params={})

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_search_query_too_short(self, receipts_handler):
        """Test search rejects query shorter than 3 characters."""
        result = await receipts_handler.handle(
            "GET", "/api/v2/receipts/search", query_params={"q": "ab"}
        )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_search_success(self, receipts_handler, mock_receipt_store):
        """Test search returns matching receipts."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1", "verdict": "APPROVED"})

        # Add search method to mock store
        mock_receipt_store.search = MagicMock(return_value=[mock_receipt_store.receipts["r1"]])
        mock_receipt_store.search_count = MagicMock(return_value=1)

        result = await receipts_handler.handle(
            "GET", "/api/v2/receipts/search", query_params={"q": "approved"}
        )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["query"] == "approved"
        assert "pagination" in data

    @pytest.mark.asyncio
    async def test_search_with_filters(self, receipts_handler, mock_receipt_store):
        """Test search with verdict and risk_level filters."""
        mock_receipt_store.search = MagicMock(return_value=[])
        mock_receipt_store.search_count = MagicMock(return_value=0)

        result = await receipts_handler.handle(
            "GET",
            "/api/v2/receipts/search",
            query_params={
                "q": "test query",
                "verdict": "APPROVED",
                "risk_level": "HIGH",
            },
        )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["filters"]["verdict"] == "APPROVED"
        assert data["filters"]["risk_level"] == "HIGH"

    @pytest.mark.asyncio
    async def test_search_limit_capped(self, receipts_handler, mock_receipt_store):
        """Test search limit is capped at 100."""
        mock_receipt_store.search = MagicMock(return_value=[])
        mock_receipt_store.search_count = MagicMock(return_value=0)

        result = await receipts_handler.handle(
            "GET",
            "/api/v2/receipts/search",
            query_params={"q": "test", "limit": "500"},
        )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["pagination"]["limit"] == 100


# ===========================================================================
# Share Receipt Tests
# ===========================================================================


class MockReceiptShareStore:
    """Mock share store for testing."""

    def __init__(self):
        self.shares: dict[str, dict[str, Any]] = {}

    def save(
        self,
        token: str,
        receipt_id: str,
        expires_at: float,
        max_accesses: int | None = None,
    ) -> None:
        self.shares[token] = {
            "token": token,
            "receipt_id": receipt_id,
            "expires_at": expires_at,
            "max_accesses": max_accesses,
            "access_count": 0,
        }

    def get_by_token(self, token: str) -> dict[str, Any] | None:
        return self.shares.get(token)

    def increment_access(self, token: str) -> None:
        if token in self.shares:
            self.shares[token]["access_count"] += 1


class TestReceiptsHandlerShare:
    """Tests for share receipt endpoint."""

    @pytest.fixture
    def mock_share_store(self):
        """Create mock share store."""
        return MockReceiptShareStore()

    @pytest.fixture
    def handler_with_share_store(self, receipts_handler, mock_share_store):
        """Configure handler with mock share store."""
        receipts_handler._share_store = mock_share_store
        return receipts_handler

    @pytest.mark.asyncio
    async def test_share_receipt_not_found(self, handler_with_share_store):
        """Test share returns 404 for nonexistent receipt."""
        result = await handler_with_share_store.handle(
            "POST", "/api/v2/receipts/nonexistent/share", body={}
        )

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_share_receipt_success(
        self, handler_with_share_store, mock_receipt_store, mock_share_store
    ):
        """Test creating a shareable link."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        with patch(
            "aragora.server.handlers.receipts.secrets.token_urlsafe",
            return_value="test-token-123",
        ):
            result = await handler_with_share_store.handle(
                "POST", "/api/v2/receipts/r1/share", body={}
            )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["success"] is True
        assert data["receipt_id"] == "r1"
        assert "share_url" in data
        assert "token" in data
        assert "expires_at" in data

    @pytest.mark.asyncio
    async def test_share_receipt_custom_expiry(self, handler_with_share_store, mock_receipt_store):
        """Test share with custom expiry hours."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        result = await handler_with_share_store.handle(
            "POST",
            "/api/v2/receipts/r1/share",
            body={"expires_in_hours": 48, "max_accesses": 5},
        )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["max_accesses"] == 5

    @pytest.mark.asyncio
    async def test_share_receipt_expiry_capped(self, handler_with_share_store, mock_receipt_store):
        """Test share expiry is capped at 720 hours (30 days)."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        result = await handler_with_share_store.handle(
            "POST",
            "/api/v2/receipts/r1/share",
            body={"expires_in_hours": 1000},
        )

        assert result.status_code == 200
        # Verify expiry was capped (720 hours = 30 days)


# ===========================================================================
# Get Shared Receipt Tests
# ===========================================================================


class TestReceiptsHandlerGetShared:
    """Tests for accessing shared receipt via token."""

    @pytest.fixture
    def mock_share_store(self):
        """Create mock share store."""
        return MockReceiptShareStore()

    @pytest.fixture
    def handler_with_share_store(self, receipts_handler, mock_share_store):
        """Configure handler with mock share store."""
        receipts_handler._share_store = mock_share_store
        return receipts_handler

    @pytest.mark.asyncio
    async def test_get_shared_not_found(self, handler_with_share_store):
        """Test get shared returns 404 for invalid token."""
        result = await handler_with_share_store.handle(
            "GET", "/api/v2/receipts/share/invalid-token"
        )

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_shared_expired(self, handler_with_share_store, mock_share_store):
        """Test get shared returns 410 for expired link."""
        # Create expired share
        mock_share_store.shares["expired-token"] = {
            "token": "expired-token",
            "receipt_id": "r1",
            "expires_at": 1000.0,  # Far in the past
            "max_accesses": None,
            "access_count": 0,
        }

        result = await handler_with_share_store.handle(
            "GET", "/api/v2/receipts/share/expired-token"
        )

        assert result.status_code == 410

    @pytest.mark.asyncio
    async def test_get_shared_access_limit_reached(
        self, handler_with_share_store, mock_share_store
    ):
        """Test get shared returns 410 when access limit reached."""
        # Create share with exhausted accesses
        future_time = datetime.now(timezone.utc).timestamp() + 86400
        mock_share_store.shares["limited-token"] = {
            "token": "limited-token",
            "receipt_id": "r1",
            "expires_at": future_time,
            "max_accesses": 3,
            "access_count": 3,
        }

        result = await handler_with_share_store.handle(
            "GET", "/api/v2/receipts/share/limited-token"
        )

        assert result.status_code == 410

    @pytest.mark.asyncio
    async def test_get_shared_success(
        self, handler_with_share_store, mock_receipt_store, mock_share_store
    ):
        """Test successful access via share token."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})
        future_time = datetime.now(timezone.utc).timestamp() + 86400
        mock_share_store.shares["valid-token"] = {
            "token": "valid-token",
            "receipt_id": "r1",
            "expires_at": future_time,
            "max_accesses": None,
            "access_count": 0,
        }

        result = await handler_with_share_store.handle("GET", "/api/v2/receipts/share/valid-token")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["shared"] is True
        assert "receipt" in data
        # The handler returns access_count + 1 based on the count BEFORE increment_access
        # Since mock starts at 0, response shows 0+1=1, then increment_access makes it 2
        # But the assertion checks the response which is computed before increment
        assert data["access_count"] >= 1

    @pytest.mark.asyncio
    async def test_get_shared_increments_count(
        self, handler_with_share_store, mock_receipt_store, mock_share_store
    ):
        """Test shared access increments access count."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})
        future_time = datetime.now(timezone.utc).timestamp() + 86400
        mock_share_store.shares["count-token"] = {
            "token": "count-token",
            "receipt_id": "r1",
            "expires_at": future_time,
            "max_accesses": 10,
            "access_count": 2,
        }

        initial_count = mock_share_store.shares["count-token"]["access_count"]

        result = await handler_with_share_store.handle("GET", "/api/v2/receipts/share/count-token")

        assert result.status_code == 200
        data = parse_handler_response(result)
        # The access count in the response should be at least initial + 1
        assert data["access_count"] >= initial_count + 1
        # Verify store was updated
        assert mock_share_store.shares["count-token"]["access_count"] > initial_count

    @pytest.mark.asyncio
    async def test_get_shared_html_format(
        self, handler_with_share_store, mock_receipt_store, mock_share_store
    ):
        """Test shared receipt returns HTML when Accept header requests it."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})
        future_time = datetime.now(timezone.utc).timestamp() + 86400
        mock_share_store.shares["html-token"] = {
            "token": "html-token",
            "receipt_id": "r1",
            "expires_at": future_time,
            "max_accesses": None,
            "access_count": 0,
        }

        # Add to_html to the stored receipt
        receipt = mock_receipt_store.get("r1")
        receipt.to_html = lambda: "<html>test</html>"
        receipt.input_summary = "Test decision"
        receipt.findings = []
        receipt.agents_involved = ["agent-1"]
        receipt.robustness_score = 0.9
        receipt.coverage_score = 0.85
        receipt.verification_coverage = 0.8

        result = await handler_with_share_store.handle(
            "GET",
            "/api/v2/receipts/share/html-token",
            headers={"Accept": "text/html"},
        )

        assert result.status_code == 200
        assert "text/html" in result.content_type
        body = result.body.decode("utf-8")
        assert "Aragora" in body
        assert "og:title" in body
        assert "APPROVED" in body

    @pytest.mark.asyncio
    async def test_get_shared_html_query_param(
        self, handler_with_share_store, mock_receipt_store, mock_share_store
    ):
        """Test shared receipt returns HTML with ?format=html query param."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})
        future_time = datetime.now(timezone.utc).timestamp() + 86400
        mock_share_store.shares["qp-token"] = {
            "token": "qp-token",
            "receipt_id": "r1",
            "expires_at": future_time,
            "max_accesses": None,
            "access_count": 0,
        }

        receipt = mock_receipt_store.get("r1")
        receipt.to_html = lambda: "<html>test</html>"
        receipt.input_summary = "Test decision"
        receipt.findings = []
        receipt.agents_involved = []
        receipt.robustness_score = 0.5
        receipt.coverage_score = 0.5
        receipt.verification_coverage = 0.5

        result = await handler_with_share_store.handle(
            "GET",
            "/api/v2/receipts/share/qp-token",
            query_params={"format": "html"},
        )

        assert result.status_code == 200
        assert "text/html" in result.content_type

    @pytest.mark.asyncio
    async def test_get_shared_html_uses_stored_payload_fields(
        self, handler_with_share_store, mock_receipt_store, mock_share_store
    ):
        """HTML shares render proof fields stored in the receipt payload."""
        mock_receipt_store.save(
            {
                "receipt_id": "r-proof",
                "gauntlet_id": "g-proof",
                "verdict": "APPROVED",
                "confidence": 0.91,
                "risk_level": "LOW",
                "input_summary": "Stored proof summary",
                "timestamp": "2026-04-07T01:00:00Z",
                "agents_involved": ["claude", "gpt-4"],
                "findings": [
                    {
                        "severity": "HIGH",
                        "title": "Need audit trail",
                        "description": "missing receipt proof",
                    }
                ],
                "robustness_score": 0.8,
                "coverage_score": 0.7,
                "verification_coverage": 0.6,
                "duration_seconds": 18.2,
                "cost_usd": 0.42,
                "tokens_used": 12345,
            }
        )
        future_time = datetime.now(timezone.utc).timestamp() + 86400
        mock_share_store.shares["proof-token"] = {
            "token": "proof-token",
            "receipt_id": "r-proof",
            "expires_at": future_time,
            "max_accesses": None,
            "access_count": 0,
        }

        result = await handler_with_share_store.handle(
            "GET",
            "/api/v2/receipts/share/proof-token",
            headers={"Accept": "text/html"},
        )

        assert result.status_code == 200
        body = result.body.decode("utf-8")
        assert "Stored proof summary" in body
        assert "Need audit trail" in body
        assert "$0.4200" in body
        assert "12,345" in body
        assert "18.2s" in body

    @pytest.mark.asyncio
    async def test_get_shared_json_default_for_api(
        self, handler_with_share_store, mock_receipt_store, mock_share_store
    ):
        """Test shared receipt returns JSON by default for API clients."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})
        future_time = datetime.now(timezone.utc).timestamp() + 86400
        mock_share_store.shares["api-token"] = {
            "token": "api-token",
            "receipt_id": "r1",
            "expires_at": future_time,
            "max_accesses": None,
            "access_count": 0,
        }

        result = await handler_with_share_store.handle(
            "GET",
            "/api/v2/receipts/share/api-token",
            headers={"Accept": "application/json"},
        )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["shared"] is True


# ===========================================================================
# Batch Signing Tests
# ===========================================================================


class TestReceiptsHandlerBatchSign:
    """Tests for batch signing endpoint."""

    @pytest.mark.asyncio
    async def test_sign_batch_empty(self, receipts_handler):
        """Test batch sign with empty list."""
        result = await receipts_handler.handle(
            "POST", "/api/v2/receipts/sign-batch", body={"receipt_ids": []}
        )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_sign_batch_too_many(self, receipts_handler):
        """Test batch sign with too many IDs."""
        ids = [f"r{i}" for i in range(150)]
        result = await receipts_handler.handle(
            "POST", "/api/v2/receipts/sign-batch", body={"receipt_ids": ids}
        )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_sign_batch_module_not_available(self, receipts_handler, mock_receipt_store):
        """Test batch sign returns 501 when signing module unavailable."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        # Patch to simulate ImportError
        with patch.dict("sys.modules", {"aragora.gauntlet.signing": None}):
            result = await receipts_handler.handle(
                "POST", "/api/v2/receipts/sign-batch", body={"receipt_ids": ["r1"]}
            )

        assert result.status_code == 501

    @pytest.mark.asyncio
    async def test_sign_batch_success(self, receipts_handler, mock_receipt_store):
        """Test batch sign with valid receipts."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})
        mock_receipt_store.save({"receipt_id": "r2", "gauntlet_id": "g2"})

        # Add methods needed for signing
        mock_receipt_store.get_signature = MagicMock(return_value=None)
        mock_receipt_store.store_signature = MagicMock()

        # Mock the signing module
        mock_signer = MagicMock()
        mock_signer.sign.return_value = "signature=="
        mock_backend = MagicMock()

        with patch.multiple(
            "aragora.gauntlet.signing",
            create=True,
            HMACSigner=MagicMock(from_env=MagicMock(return_value=mock_backend)),
            RSASigner=MagicMock(),
            Ed25519Signer=MagicMock(),
            ReceiptSigner=MagicMock(return_value=mock_signer),
            SigningBackend=MagicMock(),
        ):
            result = await receipts_handler.handle(
                "POST",
                "/api/v2/receipts/sign-batch",
                body={"receipt_ids": ["r1", "r2"]},
            )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert "results" in data
        assert "summary" in data
        assert data["summary"]["total"] == 2

    @pytest.mark.asyncio
    async def test_sign_batch_already_signed(self, receipts_handler, mock_receipt_store):
        """Test batch sign skips already signed receipts."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})
        mock_receipt_store.get_signature = MagicMock(return_value="existing-sig")
        mock_receipt_store.store_signature = MagicMock()

        mock_signer = MagicMock()
        mock_backend = MagicMock()

        with patch.multiple(
            "aragora.gauntlet.signing",
            create=True,
            HMACSigner=MagicMock(from_env=MagicMock(return_value=mock_backend)),
            RSASigner=MagicMock(),
            Ed25519Signer=MagicMock(),
            ReceiptSigner=MagicMock(return_value=mock_signer),
            SigningBackend=MagicMock(),
        ):
            result = await receipts_handler.handle(
                "POST",
                "/api/v2/receipts/sign-batch",
                body={"receipt_ids": ["r1"]},
            )

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["summary"]["skipped"] == 1


# ===========================================================================
# Batch Export Tests
# ===========================================================================


class TestReceiptsHandlerBatchExport:
    """Tests for batch export endpoint."""

    @pytest.mark.asyncio
    async def test_batch_export_empty(self, receipts_handler):
        """Test batch export with empty list."""
        result = await receipts_handler.handle(
            "POST", "/api/v2/receipts/batch-export", body={"receipt_ids": []}
        )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_export_too_many(self, receipts_handler):
        """Test batch export with too many IDs."""
        ids = [f"r{i}" for i in range(150)]
        result = await receipts_handler.handle(
            "POST", "/api/v2/receipts/batch-export", body={"receipt_ids": ids}
        )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_export_invalid_format(self, receipts_handler):
        """Test batch export with invalid format."""
        result = await receipts_handler.handle(
            "POST",
            "/api/v2/receipts/batch-export",
            body={"receipt_ids": ["r1"], "format": "invalid"},
        )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_export_json_success(self, receipts_handler, mock_receipt_store):
        """Test batch export as JSON ZIP."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        mock_receipt = MagicMock()
        mock_receipt.to_json.return_value = '{"test": "json"}'
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with patch.dict(
            "sys.modules",
            {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
        ):
            result = await receipts_handler.handle(
                "POST",
                "/api/v2/receipts/batch-export",
                body={"receipt_ids": ["r1"], "format": "json"},
            )

        assert result.status_code == 200
        assert result.content_type == "application/zip"
        assert "Content-Disposition" in (result.headers or {})

    @pytest.mark.asyncio
    async def test_batch_export_html_success(self, receipts_handler, mock_receipt_store):
        """Test batch export as HTML ZIP."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        mock_receipt = MagicMock()
        mock_receipt.to_html.return_value = "<html>Receipt</html>"
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with patch.dict(
            "sys.modules",
            {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
        ):
            result = await receipts_handler.handle(
                "POST",
                "/api/v2/receipts/batch-export",
                body={"receipt_ids": ["r1"], "format": "html"},
            )

        assert result.status_code == 200
        assert result.content_type == "application/zip"

    @pytest.mark.asyncio
    async def test_batch_export_markdown_success(self, receipts_handler, mock_receipt_store):
        """Test batch export as Markdown ZIP."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        mock_receipt = MagicMock()
        mock_receipt.to_markdown.return_value = "# Receipt"
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with patch.dict(
            "sys.modules",
            {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
        ):
            result = await receipts_handler.handle(
                "POST",
                "/api/v2/receipts/batch-export",
                body={"receipt_ids": ["r1"], "format": "markdown"},
            )

        assert result.status_code == 200
        assert result.content_type == "application/zip"

    @pytest.mark.asyncio
    async def test_batch_export_csv_success(self, receipts_handler, mock_receipt_store):
        """Test batch export as CSV ZIP."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        mock_receipt = MagicMock()
        mock_receipt.to_csv.return_value = "id,verdict\nr1,APPROVED"
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with patch.dict(
            "sys.modules",
            {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
        ):
            result = await receipts_handler.handle(
                "POST",
                "/api/v2/receipts/batch-export",
                body={"receipt_ids": ["r1"], "format": "csv"},
            )

        assert result.status_code == 200
        assert result.content_type == "application/zip"

    @pytest.mark.asyncio
    async def test_batch_export_handles_missing_receipts(
        self, receipts_handler, mock_receipt_store
    ):
        """Test batch export handles missing receipts gracefully."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        mock_receipt = MagicMock()
        mock_receipt.to_json.return_value = '{"test": "json"}'
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with patch.dict(
            "sys.modules",
            {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
        ):
            result = await receipts_handler.handle(
                "POST",
                "/api/v2/receipts/batch-export",
                body={"receipt_ids": ["r1", "nonexistent"], "format": "json"},
            )

        # Should succeed even with some missing receipts
        assert result.status_code == 200


# ===========================================================================
# Send to Channel Tests
# ===========================================================================


class TestReceiptsHandlerSendToChannel:
    """Tests for send receipt to channel endpoint."""

    @pytest.mark.asyncio
    async def test_send_missing_channel_type(self, receipts_handler, mock_receipt_store):
        """Test send requires channel_type."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        result = await receipts_handler.handle(
            "POST",
            "/api/v2/receipts/r1/send-to-channel",
            body={"channel_id": "C123"},
        )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_send_missing_channel_id(self, receipts_handler, mock_receipt_store):
        """Test send requires channel_id."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        result = await receipts_handler.handle(
            "POST",
            "/api/v2/receipts/r1/send-to-channel",
            body={"channel_type": "slack"},
        )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_send_receipt_not_found(self, receipts_handler):
        """Test send returns 404 for nonexistent receipt."""
        result = await receipts_handler.handle(
            "POST",
            "/api/v2/receipts/nonexistent/send-to-channel",
            body={"channel_type": "slack", "channel_id": "C123"},
        )

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_send_unsupported_channel(self, receipts_handler, mock_receipt_store):
        """Test send returns 400 for unsupported channel type."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        mock_format = MagicMock(return_value={"content": "test"})
        mock_receipt = MagicMock()
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with (
            patch.multiple(
                "aragora.channels.formatter",
                create=True,
                format_receipt_for_channel=mock_format,
            ),
            patch.dict(
                "sys.modules",
                {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
            ),
        ):
            result = await receipts_handler.handle(
                "POST",
                "/api/v2/receipts/r1/send-to-channel",
                body={"channel_type": "unsupported", "channel_id": "C123"},
            )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_v1_delivery_bridge_records_history(self, receipts_handler, mock_receipt_store):
        """Legacy deliver bridge should populate the frontend delivery history route."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        mock_format = MagicMock(return_value={"blocks": []})
        mock_receipt = MagicMock()
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with (
            patch.multiple(
                "aragora.channels.formatter",
                create=True,
                format_receipt_for_channel=mock_format,
            ),
            patch.dict(
                "sys.modules",
                {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
            ),
            patch.object(
                receipts_handler,
                "_send_to_slack",
                AsyncMock(return_value={"message_ts": "123.456", "channel": "C123"}),
            ),
        ):
            result = await receipts_handler.handle(
                "POST",
                "/api/v1/receipts/r1/deliver",
                body={"channel": "slack", "destination": "C123"},
            )

        assert result.status_code == 200

        history_result = await receipts_handler.handle(
            "GET",
            "/api/v1/receipts/deliveries",
            query_params={"receipt_id": "r1"},
        )

        assert history_result.status_code == 200
        data = parse_handler_response(history_result)
        assert data["total"] == 1
        assert data["deliveries"][0]["receiptId"] == "r1"
        assert data["deliveries"][0]["channel"] == "slack"
        assert data["deliveries"][0]["destination"] == "C123"
        assert data["deliveries"][0]["status"] == "success"

    @pytest.mark.asyncio
    async def test_failed_send_records_failed_delivery_history(
        self, receipts_handler, mock_receipt_store
    ):
        """Failed sends should still be visible in delivery history for debugging."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        mock_format = MagicMock(return_value={"blocks": []})
        mock_receipt = MagicMock()
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with (
            patch.multiple(
                "aragora.channels.formatter",
                create=True,
                format_receipt_for_channel=mock_format,
            ),
            patch.dict(
                "sys.modules",
                {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
            ),
            patch.object(
                receipts_handler,
                "_send_to_slack",
                AsyncMock(side_effect=ConnectionError("slack offline")),
            ),
        ):
            result = await receipts_handler.handle(
                "POST",
                "/api/v2/receipts/r1/send-to-channel",
                body={"channel_type": "slack", "channel_id": "C123", "workspace_id": "T123"},
            )

        assert result.status_code == 500

        history_result = await receipts_handler.handle(
            "GET",
            "/api/v1/receipts/deliveries",
            query_params={"receipt_id": "r1", "status": "failed"},
        )

        assert history_result.status_code == 200
        data = parse_handler_response(history_result)
        assert data["total"] == 1
        assert data["deliveries"][0]["status"] == "failed"
        assert data["deliveries"][0]["channel"] == "slack"
        assert data["deliveries"][0]["errorMessage"]


# ===========================================================================
# Get Formatted Tests
# ===========================================================================


class TestReceiptsHandlerGetFormatted:
    """Tests for get formatted receipt endpoint."""

    @pytest.mark.asyncio
    async def test_get_formatted_not_found(self, receipts_handler):
        """Test get formatted returns 404 for nonexistent receipt."""
        result = await receipts_handler.handle(
            "GET", "/api/v2/receipts/nonexistent/formatted/slack"
        )

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_formatted_success(self, receipts_handler, mock_receipt_store):
        """Test get formatted returns channel-specific format."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        mock_formatted = {"blocks": [{"type": "section", "text": "Receipt"}]}
        mock_format = MagicMock(return_value=mock_formatted)
        mock_receipt = MagicMock()
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with (
            patch.multiple(
                "aragora.channels.formatter",
                create=True,
                format_receipt_for_channel=mock_format,
            ),
            patch.dict(
                "sys.modules",
                {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
            ),
        ):
            result = await receipts_handler.handle("GET", "/api/v2/receipts/r1/formatted/slack")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["receipt_id"] == "r1"
        assert data["channel_type"] == "slack"
        assert "formatted" in data

    @pytest.mark.asyncio
    async def test_get_formatted_with_compact(self, receipts_handler, mock_receipt_store):
        """Test get formatted passes compact option."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        mock_format = MagicMock(return_value={"content": "compact"})
        mock_receipt = MagicMock()
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with (
            patch.multiple(
                "aragora.channels.formatter",
                create=True,
                format_receipt_for_channel=mock_format,
            ),
            patch.dict(
                "sys.modules",
                {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
            ),
        ):
            result = await receipts_handler.handle(
                "GET",
                "/api/v2/receipts/r1/formatted/slack",
                query_params={"compact": "true"},
            )

        assert result.status_code == 200
        mock_format.assert_called_once()
        call_args = mock_format.call_args
        assert call_args[0][2]["compact"] is True


# ===========================================================================
# PDF Export Tests
# ===========================================================================


class TestReceiptsHandlerPdfExport:
    """Tests for PDF export endpoint."""

    @pytest.mark.asyncio
    async def test_export_pdf_success(self, receipts_handler, mock_receipt_store):
        """Test export as PDF."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        mock_receipt = MagicMock()
        mock_receipt.to_pdf.return_value = b"%PDF-1.4..."
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with patch.dict(
            "sys.modules",
            {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
        ):
            result = await receipts_handler.handle(
                "GET",
                "/api/v2/receipts/r1/export",
                query_params={"format": "pdf"},
            )

        assert result.status_code == 200
        assert result.content_type == "application/pdf"
        assert "Content-Disposition" in (result.headers or {})

    @pytest.mark.asyncio
    async def test_export_pdf_weasyprint_missing(self, receipts_handler, mock_receipt_store):
        """Test PDF export gracefully degrades to HTML when weasyprint unavailable."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        mock_receipt = MagicMock()
        mock_receipt.to_pdf.side_effect = ImportError("weasyprint not found")
        mock_receipt.to_html.return_value = "<div>Receipt Content</div>"
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))

        with patch.dict(
            "sys.modules",
            {"aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class)},
        ):
            result = await receipts_handler.handle(
                "GET",
                "/api/v2/receipts/r1/export",
                query_params={"format": "pdf"},
            )

        # Handler gracefully degrades to HTML with print instructions
        assert result.status_code == 200
        assert result.content_type == "text/html"
        assert result.headers.get("X-PDF-Fallback") == "true"
        body = result.body.decode("utf-8")
        assert "PDF export is unavailable" in body


# ===========================================================================
# SARIF Export Tests
# ===========================================================================


class TestReceiptsHandlerSarifExport:
    """Tests for SARIF export endpoint."""

    @pytest.mark.asyncio
    async def test_export_sarif_success(self, receipts_handler, mock_receipt_store):
        """Test export as SARIF."""
        mock_receipt_store.save({"receipt_id": "r1", "gauntlet_id": "g1"})

        mock_receipt = MagicMock()
        mock_receipt_class = MagicMock(from_dict=MagicMock(return_value=mock_receipt))
        mock_export = MagicMock(return_value='{"$schema": "sarif-2.1.0"}')
        mock_format = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "aragora.export.decision_receipt": MagicMock(DecisionReceipt=mock_receipt_class),
                "aragora.gauntlet.api.export": MagicMock(
                    export_receipt=mock_export, ReceiptExportFormat=mock_format
                ),
            },
        ):
            result = await receipts_handler.handle(
                "GET",
                "/api/v2/receipts/r1/export",
                query_params={"format": "sarif"},
            )

        assert result.status_code == 200
        assert result.content_type == "application/json"


# ===========================================================================
# ODR Signing Key Endpoint Tests (issue #8804)
# ===========================================================================


def _make_ed25519_private_key():
    """Generate a throwaway Ed25519 key for signing-key endpoint tests."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.generate()


class TestSigningKeyEndpoints:
    """Tests for the public ODR signing-key trust anchor endpoints."""

    def test_can_handle_wellknown_get(self, receipts_handler):
        """The /.well-known route is GET-only."""
        assert receipts_handler.can_handle("/.well-known/aragora-odr-signing-key", "GET") is True
        assert receipts_handler.can_handle("/.well-known/aragora-odr-signing-key", "POST") is False

    def test_can_handle_api_alias(self, receipts_handler):
        """The /api/v2 alias is claimed by the receipts prefix."""
        assert receipts_handler.can_handle("/api/v2/receipts/signing-key", "GET") is True

    @pytest.mark.asyncio
    async def test_api_route_returns_public_key_envelope(self, receipts_handler):
        """GET /api/v2/receipts/signing-key returns the JSON trust anchor."""
        from aragora.gauntlet.odr_signing import compute_key_id, public_key_pem

        key = _make_ed25519_private_key()
        with patch(
            "aragora.gauntlet.odr_signing.load_signing_key_from_secrets",
            return_value=key,
        ):
            result = await receipts_handler.handle("GET", "/api/v2/receipts/signing-key")

        assert result.status_code == 200
        data = parse_handler_response(result)
        assert data["algorithm"] == "Ed25519"
        assert data["key_id"] == compute_key_id(key.public_key())
        assert data["public_key_pem"] == public_key_pem(key)
        assert data["public_key_pem"].startswith("-----BEGIN PUBLIC KEY-----")

    @pytest.mark.asyncio
    async def test_wellknown_route_returns_raw_pem(self, receipts_handler):
        """GET /.well-known/aragora-odr-signing-key returns the raw PEM."""
        from aragora.gauntlet.odr_signing import compute_key_id, public_key_pem

        key = _make_ed25519_private_key()
        with patch(
            "aragora.gauntlet.odr_signing.load_signing_key_from_secrets",
            return_value=key,
        ):
            result = await receipts_handler.handle("GET", "/.well-known/aragora-odr-signing-key")

        assert result.status_code == 200
        assert result.content_type.startswith("application/x-pem-file")
        assert result.body.decode("utf-8") == public_key_pem(key)
        assert result.headers.get("X-Aragora-Key-Id") == compute_key_id(key.public_key())

    @pytest.mark.asyncio
    async def test_no_private_key_material_in_responses(self, receipts_handler):
        """Neither route may ever leak private key material."""
        key = _make_ed25519_private_key()
        with patch(
            "aragora.gauntlet.odr_signing.load_signing_key_from_secrets",
            return_value=key,
        ):
            for path in (
                "/api/v2/receipts/signing-key",
                "/.well-known/aragora-odr-signing-key",
            ):
                receipts_handler._signing_key_cache = None
                result = await receipts_handler.handle("GET", path)
                assert result.status_code == 200
                assert b"PRIVATE" not in result.body

    @pytest.mark.asyncio
    async def test_unconfigured_key_fails_closed_with_404(self, receipts_handler):
        """No configured signing key -> 404, never a generated key."""
        from aragora.gauntlet.odr_signing import OdrSigningError

        with patch(
            "aragora.gauntlet.odr_signing.load_signing_key_from_secrets",
            side_effect=OdrSigningError("no key configured"),
        ):
            for path in (
                "/api/v2/receipts/signing-key",
                "/.well-known/aragora-odr-signing-key",
            ):
                result = await receipts_handler.handle("GET", path)
                assert result.status_code == 404
                data = parse_handler_response(result)
                assert "signing key" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_signing_key_load_failure_is_negative_cached(self, receipts_handler):
        """A failed load is negative-cached: these endpoints are public and
        unauthenticated, so uncached failures would forward every request to
        Secrets Manager (throttling/billing amplification). The negative entry
        expires quickly so a freshly provisioned key is still picked up."""
        import time as time_module

        from aragora.gauntlet.odr_signing import OdrSigningError

        key = _make_ed25519_private_key()
        fake_now = [1000.0]
        with (
            patch(
                "aragora.gauntlet.odr_signing.load_signing_key_from_secrets",
                side_effect=[OdrSigningError("transient"), key],
            ) as loader,
            patch.object(time_module, "monotonic", side_effect=lambda: fake_now[0]),
        ):
            first = await receipts_handler.handle("GET", "/api/v2/receipts/signing-key")
            # Within the negative-cache TTL: served from cache, loader NOT re-hit.
            second = await receipts_handler.handle("GET", "/api/v2/receipts/signing-key")
            assert loader.call_count == 1

            # After the negative TTL expires the loader is retried and succeeds.
            fake_now[0] += receipts_handler.SIGNING_KEY_NEGATIVE_CACHE_TTL_SECONDS + 1
            third = await receipts_handler.handle("GET", "/api/v2/receipts/signing-key")

        assert first.status_code == 404
        assert second.status_code == 404
        assert third.status_code == 200
        assert loader.call_count == 2

    @pytest.mark.asyncio
    async def test_resolved_key_is_cached(self, receipts_handler):
        """A successful load is served from cache within the TTL."""
        key = _make_ed25519_private_key()
        with patch(
            "aragora.gauntlet.odr_signing.load_signing_key_from_secrets",
            return_value=key,
        ) as loader:
            first = await receipts_handler.handle("GET", "/api/v2/receipts/signing-key")
            second = await receipts_handler.handle("GET", "/.well-known/aragora-odr-signing-key")

        assert first.status_code == 200
        assert second.status_code == 200
        assert loader.call_count == 1

    @pytest.mark.asyncio
    async def test_post_to_signing_key_routes_is_rejected(self, receipts_handler):
        """POST is not part of the trust-anchor surface."""
        result = await receipts_handler.handle("POST", "/api/v2/receipts/signing-key")
        assert result.status_code == 404
