"""Tests for invoice handler (aragora/server/handlers/invoices.py).

Covers all routes and behavior of the InvoiceHandler class:
- can_handle() routing for all static and dynamic ROUTES
- GET /api/v1/accounting/invoices - List invoices with filters
- GET /api/v1/accounting/invoices/{id} - Get invoice by ID
- GET /api/v1/accounting/invoices/pending - Get pending approvals
- GET /api/v1/accounting/invoices/overdue - Get overdue invoices
- GET /api/v1/accounting/invoices/stats - Get statistics
- GET /api/v1/accounting/invoices/status - Get handler status
- GET /api/v1/accounting/invoices/{id}/anomalies - Get anomalies
- GET /api/v1/accounting/payments/scheduled - Get scheduled payments
- POST /api/v1/accounting/invoices/upload - Upload and extract invoice
- POST /api/v1/accounting/invoices - Create invoice manually
- POST /api/v1/accounting/invoices/{id}/approve - Approve invoice
- POST /api/v1/accounting/invoices/{id}/reject - Reject invoice
- POST /api/v1/accounting/invoices/{id}/match - Match to PO
- POST /api/v1/accounting/invoices/{id}/schedule - Schedule payment
- POST /api/v1/accounting/purchase-orders - Create purchase order
- Circuit breaker integration
- Error handling (not found, invalid data, processor errors)
- Edge cases (pagination, filtering, date parsing, base64 decode)
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.invoices import (
    InvoiceHandler,
    get_invoice_circuit_breaker,
    reset_invoice_circuit_breaker,
    handle_upload_invoice,
    handle_create_invoice,
    handle_list_invoices,
    handle_get_invoice,
    handle_approve_invoice,
    handle_reject_invoice,
    handle_get_pending_approvals,
    handle_match_to_po,
    handle_get_anomalies,
    handle_schedule_payment,
    handle_get_scheduled_payments,
    handle_create_purchase_order,
    handle_get_invoice_stats,
    handle_get_overdue_invoices,
    handle_get_invoice_handler_status,
)


# ---------------------------------------------------------------------------
# Mock data classes
# ---------------------------------------------------------------------------


@dataclass
class MockInvoice:
    """Mock invoice object."""

    invoice_id: str = "inv-001"
    vendor_name: str = "Acme Corp"
    total_amount: float = 1500.00
    invoice_number: str = "INV-2026-001"
    status: str = "pending"
    invoice_date: str = "2026-01-15"
    due_date: str = "2026-02-15"

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_id": self.invoice_id,
            "vendor_name": self.vendor_name,
            "total_amount": self.total_amount,
            "invoice_number": self.invoice_number,
            "status": self.status,
            "invoice_date": self.invoice_date,
            "due_date": self.due_date,
        }


@dataclass
class MockAnomaly:
    """Mock anomaly object."""

    anomaly_id: str = "anom-001"
    anomaly_type: str = "duplicate_invoice"
    severity: str = "high"
    description: str = "Potential duplicate invoice detected"

    def to_dict(self) -> dict[str, Any]:
        return {
            "anomaly_id": self.anomaly_id,
            "anomaly_type": self.anomaly_type,
            "severity": self.severity,
            "description": self.description,
        }


@dataclass
class MockPOMatch:
    """Mock purchase order match."""

    match_id: str = "match-001"
    po_number: str = "PO-2026-001"
    confidence: float = 0.95

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "po_number": self.po_number,
            "confidence": self.confidence,
        }


@dataclass
class MockPaymentSchedule:
    """Mock payment schedule."""

    schedule_id: str = "sched-001"
    pay_date: str = "2026-02-20"
    payment_method: str = "ach"
    amount: float = 1500.00

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "pay_date": self.pay_date,
            "payment_method": self.payment_method,
            "amount": self.amount,
        }


@dataclass
class MockPurchaseOrder:
    """Mock purchase order."""

    po_id: str = "po-001"
    po_number: str = "PO-2026-001"
    vendor_name: str = "Acme Corp"
    total_amount: float = 1500.00

    def to_dict(self) -> dict[str, Any]:
        return {
            "po_id": self.po_id,
            "po_number": self.po_number,
            "vendor_name": self.vendor_name,
            "total_amount": self.total_amount,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw_body(result) -> dict:
    """Extract raw JSON body dict from a HandlerResult (includes envelope)."""
    if isinstance(result, dict):
        return result
    raw = result.body
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _body(result) -> dict:
    """Extract the data payload from a success response.

    success_response wraps in {"success": true, "data": {...}}.
    This helper returns the inner data dict for convenience.
    For error responses, returns the raw body (which has {"error": "..."}).
    """
    raw = _raw_body(result)
    if "data" in raw:
        return raw["data"]
    return raw


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


def _error_msg(result) -> str:
    """Extract error message from an error response."""
    raw = _raw_body(result)
    return raw.get("error", "")


def _make_mock_processor():
    """Create a fully mocked invoice processor."""
    processor = AsyncMock()
    processor.extract_invoice_data = AsyncMock(return_value=MockInvoice())
    processor.detect_anomalies = AsyncMock(return_value=[MockAnomaly()])
    processor.create_manual_invoice = AsyncMock(return_value=MockInvoice())
    processor.list_invoices = AsyncMock(return_value=([MockInvoice()], 1))
    processor.get_invoice = AsyncMock(return_value=MockInvoice())
    processor.approve_invoice = AsyncMock(return_value=MockInvoice())
    processor.reject_invoice = AsyncMock(return_value=MockInvoice())
    processor.get_pending_approvals = AsyncMock(return_value=[MockInvoice()])
    processor.match_to_po = AsyncMock(return_value=MockPOMatch())
    processor.schedule_payment = AsyncMock(return_value=MockPaymentSchedule())
    processor.get_scheduled_payments = AsyncMock(return_value=[MockPaymentSchedule()])
    processor.add_purchase_order = AsyncMock(return_value=MockPurchaseOrder())
    processor.get_stats = MagicMock(
        return_value={
            "total_invoices": 42,
            "total_amount": 125000.50,
            "pending_count": 5,
        }
    )
    processor.get_overdue_invoices = AsyncMock(return_value=[MockInvoice(total_amount=500.0)])
    return processor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create an InvoiceHandler with minimal context."""
    return InvoiceHandler({})


@pytest.fixture(autouse=True)
def _reset_cb():
    """Reset the circuit breaker between tests."""
    reset_invoice_circuit_breaker()
    yield
    reset_invoice_circuit_breaker()


@pytest.fixture
def mock_processor():
    """Create a mock invoice processor."""
    return _make_mock_processor()


@pytest.fixture
def patch_processor(mock_processor):
    """Patch get_invoice_processor to return the mock."""
    with patch(
        "aragora.server.handlers.invoices.get_invoice_processor",
        return_value=mock_processor,
    ):
        yield mock_processor


# ============================================================================
# can_handle() routing
# ============================================================================


class TestCanHandle:
    """Verify that can_handle correctly accepts or rejects paths."""

    # Static routes
    def test_invoices_upload(self, handler):
        assert handler.can_handle("/api/v1/accounting/invoices/upload")

    def test_invoices_list(self, handler):
        assert handler.can_handle("/api/v1/accounting/invoices")

    def test_invoices_pending(self, handler):
        assert handler.can_handle("/api/v1/accounting/invoices/pending")

    def test_invoices_overdue(self, handler):
        assert handler.can_handle("/api/v1/accounting/invoices/overdue")

    def test_invoices_stats(self, handler):
        assert handler.can_handle("/api/v1/accounting/invoices/stats")

    def test_invoices_status(self, handler):
        assert handler.can_handle("/api/v1/accounting/invoices/status")

    def test_purchase_orders(self, handler):
        assert handler.can_handle("/api/v1/accounting/purchase-orders")

    def test_payments_scheduled(self, handler):
        assert handler.can_handle("/api/v1/accounting/payments/scheduled")

    # Dynamic routes
    def test_invoice_by_id(self, handler):
        assert handler.can_handle("/api/v1/accounting/invoices/inv-123")

    def test_invoice_approve(self, handler):
        assert handler.can_handle("/api/v1/accounting/invoices/inv-123/approve")

    def test_invoice_reject(self, handler):
        assert handler.can_handle("/api/v1/accounting/invoices/inv-123/reject")

    def test_invoice_match(self, handler):
        assert handler.can_handle("/api/v1/accounting/invoices/inv-123/match")

    def test_invoice_schedule(self, handler):
        assert handler.can_handle("/api/v1/accounting/invoices/inv-123/schedule")

    def test_invoice_anomalies(self, handler):
        assert handler.can_handle("/api/v1/accounting/invoices/inv-123/anomalies")

    # Rejected paths
    def test_rejects_unrelated_path(self, handler):
        assert not handler.can_handle("/api/v1/billing/invoices")

    def test_rejects_partial_path(self, handler):
        assert not handler.can_handle("/api/v1/accounting")

    def test_rejects_wrong_version(self, handler):
        assert not handler.can_handle("/api/v2/accounting/invoices")

    def test_rejects_extra_nested_path(self, handler):
        assert not handler.can_handle("/api/v1/accounting/invoices/inv-123/approve/extra")


# ============================================================================
# handle_get routing
# ============================================================================


class TestHandleGetRouting:
    """Test that handle_get dispatches to correct handlers."""

    @pytest.mark.asyncio
    async def test_list_invoices(self, handler, patch_processor):
        result = await handler.handle_get("/api/v1/accounting/invoices", {})
        assert _status(result) == 200
        body = _body(result)
        assert "invoices" in body

    @pytest.mark.asyncio
    async def test_pending_approvals(self, handler, patch_processor):
        result = await handler.handle_get("/api/v1/accounting/invoices/pending", {})
        assert _status(result) == 200
        body = _body(result)
        assert "invoices" in body
        assert "count" in body

    @pytest.mark.asyncio
    async def test_overdue_invoices(self, handler, patch_processor):
        result = await handler.handle_get("/api/v1/accounting/invoices/overdue", {})
        assert _status(result) == 200
        body = _body(result)
        assert "invoices" in body
        assert "totalAmount" in body

    @pytest.mark.asyncio
    async def test_invoice_stats(self, handler, patch_processor):
        result = await handler.handle_get("/api/v1/accounting/invoices/stats", {})
        assert _status(result) == 200
        body = _body(result)
        assert "stats" in body

    @pytest.mark.asyncio
    async def test_handler_status(self, handler):
        result = await handler.handle_get("/api/v1/accounting/invoices/status", {})
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "healthy"
        assert body["stability"] == "STABLE"

    @pytest.mark.asyncio
    async def test_scheduled_payments(self, handler, patch_processor):
        result = await handler.handle_get("/api/v1/accounting/payments/scheduled", {})
        assert _status(result) == 200
        body = _body(result)
        assert "payments" in body
        assert "totalAmount" in body

    @pytest.mark.asyncio
    async def test_get_invoice_by_id(self, handler, patch_processor):
        result = await handler.handle_get("/api/v1/accounting/invoices/inv-001", {})
        assert _status(result) == 200
        body = _body(result)
        assert "invoice" in body

    @pytest.mark.asyncio
    async def test_get_invoice_anomalies(self, handler, patch_processor):
        result = await handler.handle_get("/api/v1/accounting/invoices/inv-001/anomalies", {})
        assert _status(result) == 200
        body = _body(result)
        assert "anomalies" in body
        assert "count" in body

    @pytest.mark.asyncio
    async def test_unknown_get_route(self, handler):
        result = await handler.handle_get("/api/v1/accounting/unknown", {})
        assert _status(result) == 404


# ============================================================================
# handle_post routing
# ============================================================================


class TestHandlePostRouting:
    """Test that handle_post dispatches to correct handlers."""

    @pytest.mark.asyncio
    async def test_upload_invoice(self, handler, patch_processor):
        doc_b64 = base64.b64encode(b"fake-pdf-data").decode()
        data = {"document_data": doc_b64}
        result = await handler.handle_post("/api/v1/accounting/invoices/upload", data)
        assert _status(result) == 200
        body = _body(result)
        assert "invoice" in body

    @pytest.mark.asyncio
    async def test_create_invoice(self, handler, patch_processor):
        data = {"vendor_name": "Acme Corp", "total_amount": 1500.00}
        result = await handler.handle_post("/api/v1/accounting/invoices", data)
        assert _status(result) == 200
        body = _body(result)
        assert "invoice" in body

    @pytest.mark.asyncio
    async def test_create_purchase_order(self, handler, patch_processor):
        data = {
            "po_number": "PO-001",
            "vendor_name": "Acme Corp",
            "total_amount": 1500.00,
        }
        result = await handler.handle_post("/api/v1/accounting/purchase-orders", data)
        assert _status(result) == 200
        body = _body(result)
        assert "purchaseOrder" in body

    @pytest.mark.asyncio
    async def test_approve_invoice(self, handler, patch_processor):
        result = await handler.handle_post("/api/v1/accounting/invoices/inv-001/approve", {})
        assert _status(result) == 200
        body = _body(result)
        assert "invoice" in body

    @pytest.mark.asyncio
    async def test_reject_invoice(self, handler, patch_processor):
        result = await handler.handle_post(
            "/api/v1/accounting/invoices/inv-001/reject",
            {"reason": "Incorrect amount"},
        )
        assert _status(result) == 200
        body = _body(result)
        assert "invoice" in body

    @pytest.mark.asyncio
    async def test_match_to_po(self, handler, patch_processor):
        result = await handler.handle_post("/api/v1/accounting/invoices/inv-001/match", {})
        assert _status(result) == 200
        body = _body(result)
        assert "match" in body

    @pytest.mark.asyncio
    async def test_schedule_payment(self, handler, patch_processor):
        result = await handler.handle_post(
            "/api/v1/accounting/invoices/inv-001/schedule",
            {"payment_method": "wire"},
        )
        assert _status(result) == 200
        body = _body(result)
        assert "schedule" in body

    @pytest.mark.asyncio
    async def test_unknown_post_route(self, handler):
        result = await handler.handle_post("/api/v1/accounting/unknown", {})
        assert _status(result) == 404


# ============================================================================
# POST /api/v1/accounting/invoices/upload
# ============================================================================


class TestUploadInvoice:
    """Tests for invoice upload and extraction."""

    @pytest.mark.asyncio
    async def test_successful_upload(self, patch_processor):
        doc_b64 = base64.b64encode(b"fake-pdf-content").decode()
        result = await handle_upload_invoice({"document_data": doc_b64, "vendor_hint": "Acme"})
        assert _status(result) == 200
        body = _body(result)
        assert "invoice" in body
        assert "anomalies" in body
        assert body["message"] == "Invoice extracted successfully"

    @pytest.mark.asyncio
    async def test_missing_document_data(self, patch_processor):
        result = await handle_upload_invoice({})
        assert _status(result) == 400
        assert "document_data is required" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_invalid_base64(self, patch_processor):
        result = await handle_upload_invoice({"document_data": "!!!not-b64!!!"})
        assert _status(result) == 400
        assert "Invalid base64" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_processor_error_returns_500(self):
        mock_proc = _make_mock_processor()
        mock_proc.extract_invoice_data = AsyncMock(side_effect=RuntimeError("Extraction failed"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            doc_b64 = base64.b64encode(b"data").decode()
            result = await handle_upload_invoice({"document_data": doc_b64})
            assert _status(result) == 500
            assert "Invoice processing failed" in _body(result).get("error", "")


# ============================================================================
# POST /api/v1/accounting/invoices
# ============================================================================


class TestCreateInvoice:
    """Tests for manual invoice creation."""

    @pytest.mark.asyncio
    async def test_successful_creation(self, patch_processor):
        result = await handle_create_invoice(
            {
                "vendor_name": "Acme Corp",
                "total_amount": 2500.00,
                "invoice_number": "INV-100",
                "po_number": "PO-200",
            }
        )
        assert _status(result) == 200
        body = _body(result)
        assert body["message"] == "Invoice created successfully"

    @pytest.mark.asyncio
    async def test_missing_vendor_name(self, patch_processor):
        result = await handle_create_invoice({"total_amount": 100.0})
        assert _status(result) == 400
        assert "vendor_name is required" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_missing_total_amount(self, patch_processor):
        result = await handle_create_invoice({"vendor_name": "Acme"})
        assert _status(result) == 400
        assert "total_amount is required" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_invalid_total_amount(self, patch_processor):
        result = await handle_create_invoice(
            {"vendor_name": "Acme", "total_amount": "not-a-number"}
        )
        assert _status(result) == 400
        assert "total_amount must be a number" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_invalid_invoice_date(self, patch_processor):
        result = await handle_create_invoice(
            {
                "vendor_name": "Acme",
                "total_amount": 100.0,
                "invoice_date": "not-a-date",
            }
        )
        assert _status(result) == 400
        assert "Invalid invoice_date format" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_invalid_due_date(self, patch_processor):
        result = await handle_create_invoice(
            {
                "vendor_name": "Acme",
                "total_amount": 100.0,
                "due_date": "bad-date",
            }
        )
        assert _status(result) == 400
        assert "Invalid due_date format" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_valid_dates(self, patch_processor):
        result = await handle_create_invoice(
            {
                "vendor_name": "Acme",
                "total_amount": 100.0,
                "invoice_date": "2026-01-15",
                "due_date": "2026-02-15",
            }
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_iso_date_with_z_suffix(self, patch_processor):
        result = await handle_create_invoice(
            {
                "vendor_name": "Acme",
                "total_amount": 100.0,
                "invoice_date": "2026-01-15T00:00:00Z",
            }
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_processor_error_returns_500(self):
        mock_proc = _make_mock_processor()
        mock_proc.create_manual_invoice = AsyncMock(side_effect=ValueError("DB error"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_create_invoice({"vendor_name": "Acme", "total_amount": 100.0})
            assert _status(result) == 500


# ============================================================================
# GET /api/v1/accounting/invoices
# ============================================================================


class TestListInvoices:
    """Tests for listing invoices with filters."""

    @pytest.mark.asyncio
    async def test_successful_list(self, patch_processor):
        result = await handle_list_invoices({})
        assert _status(result) == 200
        body = _body(result)
        assert "invoices" in body
        assert "total" in body
        assert "limit" in body
        assert "offset" in body

    @pytest.mark.asyncio
    async def test_default_pagination(self, patch_processor):
        result = await handle_list_invoices({})
        body = _body(result)
        assert body["limit"] == 100
        assert body["offset"] == 0

    @pytest.mark.asyncio
    async def test_custom_pagination(self, patch_processor):
        result = await handle_list_invoices({"limit": "50", "offset": "10"})
        body = _body(result)
        assert body["limit"] == 50
        assert body["offset"] == 10

    @pytest.mark.asyncio
    async def test_with_vendor_filter(self, patch_processor):
        result = await handle_list_invoices({"vendor": "Acme"})
        assert _status(result) == 200
        patch_processor.list_invoices.assert_called_once()
        call_kwargs = patch_processor.list_invoices.call_args[1]
        assert call_kwargs["vendor"] == "Acme"

    @pytest.mark.asyncio
    async def test_with_date_filters(self, patch_processor):
        result = await handle_list_invoices({"start_date": "2026-01-01", "end_date": "2026-02-01"})
        assert _status(result) == 200
        call_kwargs = patch_processor.list_invoices.call_args[1]
        assert call_kwargs["start_date"] is not None
        assert call_kwargs["end_date"] is not None

    @pytest.mark.asyncio
    async def test_invalid_date_rejected(self, patch_processor):
        result = await handle_list_invoices({"start_date": "not-a-date"})
        assert _status(result) == 400
        assert "start_date" in _error_msg(result)
        patch_processor.list_invoices.assert_not_called()

    @pytest.mark.asyncio
    async def test_processor_error_returns_500(self):
        mock_proc = _make_mock_processor()
        mock_proc.list_invoices = AsyncMock(side_effect=RuntimeError("DB error"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_list_invoices({})
            assert _status(result) == 500


# ============================================================================
# GET /api/v1/accounting/invoices/{id}
# ============================================================================


class TestGetInvoice:
    """Tests for getting a single invoice by ID."""

    @pytest.mark.asyncio
    async def test_successful_get(self, patch_processor):
        result = await handle_get_invoice("inv-001")
        assert _status(result) == 200
        body = _body(result)
        assert "invoice" in body

    @pytest.mark.asyncio
    async def test_not_found(self, patch_processor):
        patch_processor.get_invoice = AsyncMock(return_value=None)
        result = await handle_get_invoice("nonexistent")
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_processor_error(self):
        mock_proc = _make_mock_processor()
        mock_proc.get_invoice = AsyncMock(side_effect=KeyError("missing"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_get_invoice("inv-001")
            assert _status(result) == 500


# ============================================================================
# POST /api/v1/accounting/invoices/{id}/approve
# ============================================================================


class TestApproveInvoice:
    """Tests for approving an invoice."""

    @pytest.mark.asyncio
    async def test_successful_approval(self, patch_processor):
        result = await handle_approve_invoice("inv-001", {})
        assert _status(result) == 200
        body = _body(result)
        assert body["message"] == "Invoice approved successfully"

    @pytest.mark.asyncio
    async def test_approval_with_approver_id(self, patch_processor):
        result = await handle_approve_invoice("inv-001", {"approver_id": "user-mgr-001"})
        assert _status(result) == 200
        patch_processor.approve_invoice.assert_called_once_with("inv-001", "user-mgr-001")

    @pytest.mark.asyncio
    async def test_approval_not_found(self, patch_processor):
        patch_processor.approve_invoice = AsyncMock(return_value=None)
        result = await handle_approve_invoice("nonexistent", {})
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_approval_error(self):
        mock_proc = _make_mock_processor()
        mock_proc.approve_invoice = AsyncMock(side_effect=RuntimeError("Approval failed"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_approve_invoice("inv-001", {})
            assert _status(result) == 500


# ============================================================================
# POST /api/v1/accounting/invoices/{id}/reject
# ============================================================================


class TestRejectInvoice:
    """Tests for rejecting an invoice."""

    @pytest.mark.asyncio
    async def test_successful_rejection(self, patch_processor):
        result = await handle_reject_invoice("inv-001", {"reason": "Duplicate invoice"})
        assert _status(result) == 200
        body = _body(result)
        assert body["message"] == "Invoice rejected"

    @pytest.mark.asyncio
    async def test_rejection_without_reason(self, patch_processor):
        result = await handle_reject_invoice("inv-001", {})
        assert _status(result) == 200
        patch_processor.reject_invoice.assert_called_once_with("inv-001", "")

    @pytest.mark.asyncio
    async def test_rejection_not_found(self, patch_processor):
        patch_processor.reject_invoice = AsyncMock(return_value=None)
        result = await handle_reject_invoice("nonexistent", {})
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_rejection_error(self):
        mock_proc = _make_mock_processor()
        mock_proc.reject_invoice = AsyncMock(side_effect=TypeError("bad type"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_reject_invoice("inv-001", {})
            assert _status(result) == 500


# ============================================================================
# GET /api/v1/accounting/invoices/pending
# ============================================================================


class TestPendingApprovals:
    """Tests for getting pending approvals."""

    @pytest.mark.asyncio
    async def test_successful_get(self, patch_processor):
        result = await handle_get_pending_approvals()
        assert _status(result) == 200
        body = _body(result)
        assert "invoices" in body
        assert body["count"] == 1

    @pytest.mark.asyncio
    async def test_empty_pending(self, patch_processor):
        patch_processor.get_pending_approvals = AsyncMock(return_value=[])
        result = await handle_get_pending_approvals()
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 0
        assert body["invoices"] == []

    @pytest.mark.asyncio
    async def test_processor_error(self):
        mock_proc = _make_mock_processor()
        mock_proc.get_pending_approvals = AsyncMock(side_effect=OSError("connection lost"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_get_pending_approvals()
            assert _status(result) == 500


# ============================================================================
# POST /api/v1/accounting/invoices/{id}/match
# ============================================================================


class TestMatchToPO:
    """Tests for matching invoice to purchase order."""

    @pytest.mark.asyncio
    async def test_successful_match(self, patch_processor):
        result = await handle_match_to_po("inv-001")
        assert _status(result) == 200
        body = _body(result)
        assert "match" in body
        assert "invoice" in body

    @pytest.mark.asyncio
    async def test_match_invoice_not_found(self, patch_processor):
        patch_processor.get_invoice = AsyncMock(return_value=None)
        result = await handle_match_to_po("nonexistent")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_match_error(self):
        mock_proc = _make_mock_processor()
        mock_proc.match_to_po = AsyncMock(side_effect=AttributeError("no PO data"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_match_to_po("inv-001")
            assert _status(result) == 500


# ============================================================================
# GET /api/v1/accounting/invoices/{id}/anomalies
# ============================================================================


class TestGetAnomalies:
    """Tests for anomaly detection on invoices."""

    @pytest.mark.asyncio
    async def test_successful_anomaly_detection(self, patch_processor):
        result = await handle_get_anomalies("inv-001")
        assert _status(result) == 200
        body = _body(result)
        assert "anomalies" in body
        assert body["count"] == 1

    @pytest.mark.asyncio
    async def test_no_anomalies(self, patch_processor):
        patch_processor.detect_anomalies = AsyncMock(return_value=[])
        result = await handle_get_anomalies("inv-001")
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 0

    @pytest.mark.asyncio
    async def test_anomaly_invoice_not_found(self, patch_processor):
        patch_processor.get_invoice = AsyncMock(return_value=None)
        result = await handle_get_anomalies("nonexistent")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_anomaly_detection_error(self):
        mock_proc = _make_mock_processor()
        mock_proc.detect_anomalies = AsyncMock(side_effect=ValueError("detection failed"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_get_anomalies("inv-001")
            assert _status(result) == 500


# ============================================================================
# POST /api/v1/accounting/invoices/{id}/schedule
# ============================================================================


class TestSchedulePayment:
    """Tests for payment scheduling."""

    @pytest.mark.asyncio
    async def test_successful_schedule(self, patch_processor):
        result = await handle_schedule_payment("inv-001", {})
        assert _status(result) == 200
        body = _body(result)
        assert "schedule" in body
        assert "invoice" in body
        assert body["message"] == "Payment scheduled successfully"

    @pytest.mark.asyncio
    async def test_schedule_with_pay_date(self, patch_processor):
        result = await handle_schedule_payment("inv-001", {"pay_date": "2026-03-01"})
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_schedule_with_payment_method(self, patch_processor):
        result = await handle_schedule_payment("inv-001", {"payment_method": "wire"})
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_schedule_invalid_pay_date(self, patch_processor):
        result = await handle_schedule_payment("inv-001", {"pay_date": "not-a-date"})
        assert _status(result) == 400
        assert "Invalid pay_date format" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_schedule_invoice_not_found(self, patch_processor):
        patch_processor.get_invoice = AsyncMock(return_value=None)
        result = await handle_schedule_payment("nonexistent", {})
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_schedule_value_error_returns_400(self):
        """ValueError in schedule_payment returns 400 (special case in handler)."""
        mock_proc = _make_mock_processor()
        mock_proc.schedule_payment = AsyncMock(side_effect=ValueError("Invalid payment state"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_schedule_payment("inv-001", {})
            assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_schedule_runtime_error_returns_500(self):
        mock_proc = _make_mock_processor()
        mock_proc.schedule_payment = AsyncMock(side_effect=RuntimeError("DB error"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_schedule_payment("inv-001", {})
            assert _status(result) == 500


# ============================================================================
# GET /api/v1/accounting/payments/scheduled
# ============================================================================


class TestScheduledPayments:
    """Tests for getting scheduled payments."""

    @pytest.mark.asyncio
    async def test_successful_get(self, patch_processor):
        result = await handle_get_scheduled_payments({})
        assert _status(result) == 200
        body = _body(result)
        assert "payments" in body
        assert body["count"] == 1
        assert body["totalAmount"] == 1500.00

    @pytest.mark.asyncio
    async def test_with_date_filters(self, patch_processor):
        result = await handle_get_scheduled_payments(
            {"start_date": "2026-01-01", "end_date": "2026-03-01"}
        )
        assert _status(result) == 200
        call_kwargs = patch_processor.get_scheduled_payments.call_args[1]
        assert call_kwargs["start_date"] is not None
        assert call_kwargs["end_date"] is not None

    @pytest.mark.asyncio
    async def test_invalid_dates_rejected(self, patch_processor):
        result = await handle_get_scheduled_payments({"start_date": "bad", "end_date": "worse"})
        assert _status(result) == 400
        assert "start_date" in _error_msg(result)
        patch_processor.get_scheduled_payments.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_payments(self, patch_processor):
        patch_processor.get_scheduled_payments = AsyncMock(return_value=[])
        result = await handle_get_scheduled_payments({})
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 0
        assert body["totalAmount"] == 0.0

    @pytest.mark.asyncio
    async def test_processor_error(self):
        mock_proc = _make_mock_processor()
        mock_proc.get_scheduled_payments = AsyncMock(side_effect=ImportError("missing module"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_get_scheduled_payments({})
            assert _status(result) == 500


# ============================================================================
# POST /api/v1/accounting/purchase-orders
# ============================================================================


class TestCreatePurchaseOrder:
    """Tests for creating purchase orders."""

    @pytest.mark.asyncio
    async def test_successful_creation(self, patch_processor):
        result = await handle_create_purchase_order(
            {
                "po_number": "PO-001",
                "vendor_name": "Acme",
                "total_amount": 5000.00,
            }
        )
        assert _status(result) == 200
        body = _body(result)
        assert "purchaseOrder" in body
        assert body["message"] == "Purchase order created successfully"

    @pytest.mark.asyncio
    async def test_missing_po_number(self, patch_processor):
        result = await handle_create_purchase_order({"vendor_name": "Acme", "total_amount": 100.0})
        assert _status(result) == 400
        assert "po_number is required" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_missing_vendor_name(self, patch_processor):
        result = await handle_create_purchase_order({"po_number": "PO-001", "total_amount": 100.0})
        assert _status(result) == 400
        assert "vendor_name is required" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_missing_total_amount(self, patch_processor):
        result = await handle_create_purchase_order({"po_number": "PO-001", "vendor_name": "Acme"})
        assert _status(result) == 400
        assert "total_amount is required" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_with_optional_dates(self, patch_processor):
        result = await handle_create_purchase_order(
            {
                "po_number": "PO-001",
                "vendor_name": "Acme",
                "total_amount": 5000.00,
                "order_date": "2026-01-10",
                "expected_delivery": "2026-02-10",
            }
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_invalid_dates_ignored(self, patch_processor):
        """Invalid dates in PO creation are silently ignored (not an error)."""
        result = await handle_create_purchase_order(
            {
                "po_number": "PO-001",
                "vendor_name": "Acme",
                "total_amount": 5000.00,
                "order_date": "invalid",
                "expected_delivery": "invalid",
            }
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_processor_error(self):
        mock_proc = _make_mock_processor()
        mock_proc.add_purchase_order = AsyncMock(side_effect=RuntimeError("storage error"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_create_purchase_order(
                {
                    "po_number": "PO-001",
                    "vendor_name": "Acme",
                    "total_amount": 100.0,
                }
            )
            assert _status(result) == 500


# ============================================================================
# GET /api/v1/accounting/invoices/stats
# ============================================================================


class TestInvoiceStats:
    """Tests for invoice statistics."""

    @pytest.mark.asyncio
    async def test_successful_stats(self, patch_processor):
        result = await handle_get_invoice_stats()
        assert _status(result) == 200
        body = _body(result)
        assert "stats" in body
        assert body["stats"]["total_invoices"] == 42

    @pytest.mark.asyncio
    async def test_stats_error(self):
        mock_proc = _make_mock_processor()
        mock_proc.get_stats = MagicMock(side_effect=AttributeError("no stats"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_get_invoice_stats()
            assert _status(result) == 500


# ============================================================================
# GET /api/v1/accounting/invoices/overdue
# ============================================================================


class TestOverdueInvoices:
    """Tests for overdue invoice retrieval."""

    @pytest.mark.asyncio
    async def test_successful_overdue(self, patch_processor):
        result = await handle_get_overdue_invoices()
        assert _status(result) == 200
        body = _body(result)
        assert "invoices" in body
        assert body["count"] == 1
        assert body["totalAmount"] == 500.0

    @pytest.mark.asyncio
    async def test_no_overdue(self, patch_processor):
        patch_processor.get_overdue_invoices = AsyncMock(return_value=[])
        result = await handle_get_overdue_invoices()
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 0
        assert body["totalAmount"] == 0

    @pytest.mark.asyncio
    async def test_overdue_error(self):
        mock_proc = _make_mock_processor()
        mock_proc.get_overdue_invoices = AsyncMock(side_effect=TypeError("bad data"))
        with patch(
            "aragora.server.handlers.invoices.get_invoice_processor",
            return_value=mock_proc,
        ):
            result = await handle_get_overdue_invoices()
            assert _status(result) == 500


# ============================================================================
# GET /api/v1/accounting/invoices/status (handler status)
# ============================================================================


class TestHandlerStatus:
    """Tests for the handler status endpoint."""

    @pytest.mark.asyncio
    async def test_healthy_status(self):
        result = await handle_get_invoice_handler_status()
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "healthy"
        assert body["stability"] == "STABLE"
        assert "circuit_breaker" in body

    @pytest.mark.asyncio
    async def test_degraded_when_circuit_open(self):
        cb = get_invoice_circuit_breaker()
        # Force the circuit breaker open by recording many failures
        for _ in range(20):
            cb.record_failure()
        result = await handle_get_invoice_handler_status()
        body = _body(result)
        assert body["status"] == "degraded"


# ============================================================================
# Circuit Breaker Integration
# ============================================================================


class TestCircuitBreaker:
    """Tests for circuit breaker behavior across endpoints."""

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_upload(self, patch_processor):
        cb = get_invoice_circuit_breaker()
        for _ in range(20):
            cb.record_failure()
        doc_b64 = base64.b64encode(b"data").decode()
        result = await handle_upload_invoice({"document_data": doc_b64})
        assert _status(result) == 503
        assert "circuit breaker" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_create(self, patch_processor):
        cb = get_invoice_circuit_breaker()
        for _ in range(20):
            cb.record_failure()
        result = await handle_create_invoice({"vendor_name": "Acme", "total_amount": 100.0})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_list(self, patch_processor):
        cb = get_invoice_circuit_breaker()
        for _ in range(20):
            cb.record_failure()
        result = await handle_list_invoices({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_get(self, patch_processor):
        cb = get_invoice_circuit_breaker()
        for _ in range(20):
            cb.record_failure()
        result = await handle_get_invoice("inv-001")
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_approve(self, patch_processor):
        cb = get_invoice_circuit_breaker()
        for _ in range(20):
            cb.record_failure()
        result = await handle_approve_invoice("inv-001", {})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_stats(self, patch_processor):
        cb = get_invoice_circuit_breaker()
        for _ in range(20):
            cb.record_failure()
        result = await handle_get_invoice_stats()
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_reset_allows_requests(self, patch_processor):
        cb = get_invoice_circuit_breaker()
        for _ in range(20):
            cb.record_failure()
        reset_invoice_circuit_breaker()
        result = await handle_list_invoices({})
        assert _status(result) == 200


# ============================================================================
# _extract_invoice_id
# ============================================================================


class TestExtractInvoiceId:
    """Tests for invoice ID extraction from path."""

    def test_simple_id(self, handler):
        assert handler._extract_invoice_id("/api/v1/accounting/invoices/inv-123") == "inv-123"

    def test_uuid_id(self, handler):
        assert (
            handler._extract_invoice_id(
                "/api/v1/accounting/invoices/550e8400-e29b-41d4-a716-446655440000"
            )
            == "550e8400-e29b-41d4-a716-446655440000"
        )

    def test_path_with_action(self, handler):
        assert (
            handler._extract_invoice_id("/api/v1/accounting/invoices/inv-001/approve") == "inv-001"
        )

    def test_short_path_returns_none(self, handler):
        assert handler._extract_invoice_id("/api/v1/accounting") is None


# ============================================================================
# _matches_pattern
# ============================================================================


class TestMatchesPattern:
    """Tests for route pattern matching."""

    def test_exact_match(self, handler):
        assert handler._matches_pattern(
            "/api/v1/accounting/invoices/123",
            "/api/v1/accounting/invoices/{invoice_id}",
        )

    def test_with_action(self, handler):
        assert handler._matches_pattern(
            "/api/v1/accounting/invoices/123/approve",
            "/api/v1/accounting/invoices/{invoice_id}/approve",
        )

    def test_length_mismatch(self, handler):
        assert not handler._matches_pattern(
            "/api/v1/accounting/invoices",
            "/api/v1/accounting/invoices/{invoice_id}",
        )

    def test_segment_mismatch(self, handler):
        assert not handler._matches_pattern(
            "/api/v1/billing/invoices/123",
            "/api/v1/accounting/invoices/{invoice_id}",
        )
