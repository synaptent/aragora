"""Tests for expense handler (aragora/server/handlers/expenses.py).

Covers all routes and behavior of the ExpenseHandler class:
- can_handle() routing for all static and dynamic routes
- GET /api/v1/accounting/expenses - List expenses with filters
- GET /api/v1/accounting/expenses/{id} - Get expense by ID
- GET /api/v1/accounting/expenses/stats - Get expense statistics
- GET /api/v1/accounting/expenses/pending - Get pending approvals
- GET /api/v1/accounting/expenses/export - Export expenses
- POST /api/v1/accounting/expenses - Create expense manually
- POST /api/v1/accounting/expenses/upload - Upload and process receipt
- POST /api/v1/accounting/expenses/categorize - Auto-categorize expenses
- POST /api/v1/accounting/expenses/sync - Sync expenses to QBO
- POST /api/v1/accounting/expenses/{id}/approve - Approve expense
- POST /api/v1/accounting/expenses/{id}/reject - Reject expense
- PUT /api/v1/accounting/expenses/{id} - Update expense
- DELETE /api/v1/accounting/expenses/{id} - Delete expense
- Circuit breaker behavior
- Input validation and error handling
- Edge cases (invalid base64, long IDs, excessive tags)
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.expenses import (
    ExpenseHandler,
    get_expense_circuit_breaker,
    reset_expense_circuit_breaker,
    handle_upload_receipt,
    handle_create_expense,
    handle_list_expenses,
    handle_get_expense,
    handle_update_expense,
    handle_delete_expense,
    handle_approve_expense,
    handle_reject_expense,
    handle_categorize_expenses,
    handle_sync_to_qbo,
    handle_get_expense_stats,
    handle_get_pending_approvals,
    handle_export_expenses,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


class MockHTTPHandler:
    """Lightweight mock for the HTTP handler passed to ExpenseHandler."""

    def __init__(
        self,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        client_address: tuple[str, int] | None = None,
    ):
        self.command = method
        self.headers: dict[str, str] = {"Content-Length": "0", "User-Agent": "test-agent"}
        self.rfile = MagicMock()
        self.client_address = client_address or ("127.0.0.1", 12345)

        if body is not None:
            raw = json.dumps(body).encode()
            self.rfile.read.return_value = raw
            self.headers = {
                "Content-Length": str(len(raw)),
                "Content-Type": "application/json",
                "User-Agent": "test-agent",
            }
        else:
            self.rfile.read.return_value = b"{}"
            self.headers = {"Content-Length": "2", "User-Agent": "test-agent"}


@dataclass
class MockExpenseRecord:
    """Mock expense record for testing."""

    id: str = "exp-001"
    vendor_name: str = "Acme Corp"
    amount: Decimal = Decimal("150.00")
    currency: str = "USD"
    date: datetime = field(default_factory=datetime.now)
    category: str = "office_supplies"
    status: str = "pending"
    payment_method: str = "credit_card"
    description: str = "Office supplies purchase"
    is_reimbursable: bool = False
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "vendorName": self.vendor_name,
            "amount": float(self.amount),
            "currency": self.currency,
            "date": self.date.isoformat(),
            "category": self.category,
            "status": self.status,
            "paymentMethod": self.payment_method,
            "description": self.description,
            "isReimbursable": self.is_reimbursable,
            "tags": self.tags,
        }


@dataclass
class MockSyncResult:
    """Mock sync result for QBO sync."""

    success_count: int = 3
    failed_count: int = 0
    synced_ids: list[str] = field(default_factory=lambda: ["exp-001", "exp-002", "exp-003"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "successCount": self.success_count,
            "failedCount": self.failed_count,
            "syncedIds": self.synced_ids,
        }


@dataclass
class MockExpenseStats:
    """Mock expense statistics."""

    total_expenses: int = 42
    total_amount: float = 12345.67

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalExpenses": self.total_expenses,
            "totalAmount": self.total_amount,
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create an ExpenseHandler."""
    return ExpenseHandler(ctx={})


@pytest.fixture
def mock_tracker():
    """Create a mock expense tracker with common method stubs."""
    tracker = AsyncMock()
    tracker.process_receipt = AsyncMock(return_value=MockExpenseRecord())
    tracker.create_expense = AsyncMock(return_value=MockExpenseRecord())
    tracker.list_expenses = AsyncMock(return_value=([MockExpenseRecord()], 1))
    tracker.get_expense = AsyncMock(return_value=MockExpenseRecord())
    tracker.update_expense = AsyncMock(return_value=MockExpenseRecord())
    tracker.delete_expense = AsyncMock(return_value=True)
    tracker.approve_expense = AsyncMock(return_value=MockExpenseRecord())
    tracker.reject_expense = AsyncMock(return_value=MockExpenseRecord())
    tracker.bulk_categorize = AsyncMock(return_value={"exp-001": "travel"})
    tracker.sync_to_qbo = AsyncMock(return_value=MockSyncResult())
    tracker.get_stats = AsyncMock(return_value=MockExpenseStats())
    tracker.get_pending_approval = AsyncMock(return_value=[MockExpenseRecord()])
    tracker.export_expenses = AsyncMock(return_value="id,vendor,amount\n1,Acme,150.00")
    return tracker


@pytest.fixture(autouse=True)
def _reset_circuit_breaker():
    """Reset circuit breaker state before each test."""
    reset_expense_circuit_breaker()
    yield
    reset_expense_circuit_breaker()


@pytest.fixture(autouse=True)
def _reset_tracker_singleton():
    """Reset the expense tracker singleton before each test."""
    import aragora.server.handlers.expenses as mod

    mod._expense_tracker = None
    yield
    mod._expense_tracker = None


# ---------------------------------------------------------------------------
# can_handle() routing
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for route matching via can_handle()."""

    # Static routes
    def test_expenses_list_route(self, handler):
        assert handler.can_handle("/api/v1/accounting/expenses")

    def test_upload_route(self, handler):
        assert handler.can_handle("/api/v1/accounting/expenses/upload")

    def test_categorize_route(self, handler):
        assert handler.can_handle("/api/v1/accounting/expenses/categorize")

    def test_sync_route(self, handler):
        assert handler.can_handle("/api/v1/accounting/expenses/sync")

    def test_stats_route(self, handler):
        assert handler.can_handle("/api/v1/accounting/expenses/stats")

    def test_pending_route(self, handler):
        assert handler.can_handle("/api/v1/accounting/expenses/pending")

    def test_export_route(self, handler):
        assert handler.can_handle("/api/v1/accounting/expenses/export")

    # Dynamic routes
    def test_expense_by_id_route(self, handler):
        assert handler.can_handle("/api/v1/accounting/expenses/exp-123")

    def test_approve_route(self, handler):
        assert handler.can_handle("/api/v1/accounting/expenses/exp-123/approve")

    def test_reject_route(self, handler):
        assert handler.can_handle("/api/v1/accounting/expenses/exp-123/reject")

    # Rejected routes
    def test_rejects_unrelated_path(self, handler):
        assert not handler.can_handle("/api/v1/debates")

    def test_rejects_partial_path(self, handler):
        assert not handler.can_handle("/api/v1/accounting")

    def test_rejects_v2_path(self, handler):
        assert not handler.can_handle("/api/v2/accounting/expenses")

    def test_rejects_extra_segment(self, handler):
        assert not handler.can_handle("/api/v1/accounting/expenses/exp-1/approve/extra")


# ---------------------------------------------------------------------------
# Handler initialization
# ---------------------------------------------------------------------------


class TestHandlerInit:
    """Tests for handler construction."""

    def test_default_context_is_empty_dict(self):
        h = ExpenseHandler()
        assert h.ctx == {}

    def test_context_passed_through(self):
        ctx = {"key": "value"}
        h = ExpenseHandler(ctx=ctx)
        assert h.ctx is ctx

    def test_circuit_breaker_available(self):
        h = ExpenseHandler()
        assert h._circuit_breaker is not None


# ---------------------------------------------------------------------------
# Pattern matching and expense_id extraction
# ---------------------------------------------------------------------------


class TestPathExtraction:
    """Tests for _matches_pattern and _extract_expense_id."""

    def test_extract_expense_id_from_detail_path(self, handler):
        eid = handler._extract_expense_id("/api/v1/accounting/expenses/exp-abc-123")
        assert eid == "exp-abc-123"

    def test_extract_expense_id_from_approve_path(self, handler):
        eid = handler._extract_expense_id("/api/v1/accounting/expenses/exp-456/approve")
        assert eid == "exp-456"

    def test_extract_expense_id_from_short_path(self, handler):
        eid = handler._extract_expense_id("/api/v1/accounting/expenses")
        # Index 5 is out of range for a 5-element split
        assert eid is None

    def test_matches_pattern_exact_static(self, handler):
        assert handler._matches_pattern(
            "/api/v1/accounting/expenses/upload",
            "/api/v1/accounting/expenses/upload",
        )

    def test_matches_pattern_with_param(self, handler):
        assert handler._matches_pattern(
            "/api/v1/accounting/expenses/exp-1",
            "/api/v1/accounting/expenses/{expense_id}",
        )

    def test_matches_pattern_length_mismatch(self, handler):
        assert not handler._matches_pattern(
            "/api/v1/accounting/expenses/exp-1/extra",
            "/api/v1/accounting/expenses/{expense_id}",
        )


# ---------------------------------------------------------------------------
# GET /api/v1/accounting/expenses (list)
# ---------------------------------------------------------------------------


class TestListExpenses:
    """Tests for listing expenses."""

    @pytest.mark.asyncio
    async def test_list_expenses_success(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_list_expenses({})
        body = _body(result)
        assert _status(result) == 200
        assert "expenses" in body
        assert body["total"] == 1

    @pytest.mark.asyncio
    async def test_list_expenses_with_filters(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_list_expenses(
                {
                    "category": "travel",
                    "status": "pending",
                    "vendor": "Acme",
                    "start_date": "2025-01-01",
                    "end_date": "2025-12-31",
                    "employee_id": "emp-1",
                    "limit": "50",
                    "offset": "10",
                }
            )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_list_expenses_invalid_date_rejected(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_list_expenses(
                {
                    "start_date": "not-a-date",
                    "end_date": "also-not-a-date",
                }
            )
        assert _status(result) == 400
        assert "start_date" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_list_expenses_invalid_category_ignored(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_list_expenses({"category": "nonexistent"})
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_list_expenses_invalid_status_ignored(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_list_expenses({"status": "nonexistent"})
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_list_expenses_service_error(self, mock_tracker):
        mock_tracker.list_expenses.side_effect = RuntimeError("DB down")
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_list_expenses({})
        assert _status(result) == 500

    async def test_list_via_handler_get(self, handler, mock_tracker):
        """Test list expenses via the handler.handle() GET dispatch."""
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle("/api/v1/accounting/expenses", {}, None)
        assert _status(result) == 200
        body = _body(result)
        assert "expenses" in body


# ---------------------------------------------------------------------------
# GET /api/v1/accounting/expenses/{id} (detail)
# ---------------------------------------------------------------------------


class TestGetExpense:
    """Tests for getting a single expense by ID."""

    @pytest.mark.asyncio
    async def test_get_expense_success(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_get_expense("exp-001")
        body = _body(result)
        assert _status(result) == 200
        assert "expense" in body

    @pytest.mark.asyncio
    async def test_get_expense_not_found(self, mock_tracker):
        mock_tracker.get_expense.return_value = None
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_get_expense("exp-nonexistent")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_expense_empty_id(self):
        result = await handle_get_expense("")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_get_expense_id_too_long(self):
        result = await handle_get_expense("x" * 101)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_get_expense_service_error(self, mock_tracker):
        mock_tracker.get_expense.side_effect = RuntimeError("Service error")
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_get_expense("exp-001")
        assert _status(result) == 500

    async def test_get_expense_via_handler(self, handler, mock_tracker):
        """Test getting expense via handler.handle() GET dispatch."""
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle("/api/v1/accounting/expenses/exp-001", {}, None)
        assert _status(result) == 200
        body = _body(result)
        assert "expense" in body


# ---------------------------------------------------------------------------
# GET /api/v1/accounting/expenses/stats
# ---------------------------------------------------------------------------


class TestGetExpenseStats:
    """Tests for expense statistics."""

    @pytest.mark.asyncio
    async def test_get_stats_success(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_get_expense_stats({})
        body = _body(result)
        assert _status(result) == 200
        assert "stats" in body

    @pytest.mark.asyncio
    async def test_get_stats_with_date_range(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_get_expense_stats(
                {
                    "start_date": "2025-01-01",
                    "end_date": "2025-12-31",
                }
            )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_stats_invalid_date_rejected(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_get_expense_stats(
                {
                    "start_date": "bad-date",
                }
            )
        assert _status(result) == 400
        assert "start_date" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_get_stats_dict_result(self, mock_tracker):
        """When get_stats returns a plain dict (no to_dict)."""
        mock_tracker.get_stats.return_value = {"totalExpenses": 10}
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_get_expense_stats({})
        body = _body(result)
        assert body["stats"]["totalExpenses"] == 10

    @pytest.mark.asyncio
    async def test_get_stats_service_error(self, mock_tracker):
        mock_tracker.get_stats.side_effect = RuntimeError("DB error")
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_get_expense_stats({})
        assert _status(result) == 500

    async def test_get_stats_via_handler(self, handler, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle("/api/v1/accounting/expenses/stats", {}, None)
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# GET /api/v1/accounting/expenses/pending
# ---------------------------------------------------------------------------


class TestGetPendingApprovals:
    """Tests for getting pending approvals."""

    @pytest.mark.asyncio
    async def test_get_pending_success(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_get_pending_approvals()
        body = _body(result)
        assert _status(result) == 200
        assert "expenses" in body
        assert body["count"] == 1

    @pytest.mark.asyncio
    async def test_get_pending_service_error(self, mock_tracker):
        mock_tracker.get_pending_approval.side_effect = RuntimeError("Error")
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_get_pending_approvals()
        assert _status(result) == 500

    async def test_get_pending_via_handler(self, handler, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle("/api/v1/accounting/expenses/pending", {}, None)
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# GET /api/v1/accounting/expenses/export
# ---------------------------------------------------------------------------


class TestExportExpenses:
    """Tests for exporting expenses."""

    @pytest.mark.asyncio
    async def test_export_csv_success(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_export_expenses({"format": "csv"})
        body = _body(result)
        assert _status(result) == 200
        assert body["format"] == "csv"

    @pytest.mark.asyncio
    async def test_export_json_success(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_export_expenses({"format": "json"})
        body = _body(result)
        assert _status(result) == 200
        assert body["format"] == "json"

    @pytest.mark.asyncio
    async def test_export_default_format_is_csv(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_export_expenses({})
        body = _body(result)
        assert body["format"] == "csv"

    @pytest.mark.asyncio
    async def test_export_invalid_format(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_export_expenses({"format": "xml"})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_export_with_date_range(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_export_expenses(
                {
                    "start_date": "2025-01-01",
                    "end_date": "2025-12-31",
                }
            )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_export_service_error(self, mock_tracker):
        mock_tracker.export_expenses.side_effect = RuntimeError("Error")
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_export_expenses({})
        assert _status(result) == 500

    async def test_export_via_handler(self, handler, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle("/api/v1/accounting/expenses/export", {}, None)
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# POST /api/v1/accounting/expenses/upload (receipt upload)
# ---------------------------------------------------------------------------


class TestUploadReceipt:
    """Tests for receipt upload and processing."""

    @pytest.mark.asyncio
    async def test_upload_success(self, mock_tracker):
        receipt_data = base64.b64encode(b"fake-image-data").decode()
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_upload_receipt(
                {
                    "receipt_data": receipt_data,
                    "content_type": "image/png",
                }
            )
        body = _body(result)
        assert _status(result) == 200
        assert "expense" in body
        assert body["message"] == "Receipt processed successfully"

    @pytest.mark.asyncio
    async def test_upload_missing_receipt_data(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_upload_receipt({})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_upload_non_string_receipt_data(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_upload_receipt({"receipt_data": 12345})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_upload_invalid_base64(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_upload_receipt(
                {
                    "receipt_data": "not!valid!base64!!!",
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_upload_invalid_content_type(self, mock_tracker):
        receipt_data = base64.b64encode(b"fake-image-data").decode()
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_upload_receipt(
                {
                    "receipt_data": receipt_data,
                    "content_type": "text/html",
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_upload_non_string_employee_id(self, mock_tracker):
        receipt_data = base64.b64encode(b"fake-image-data").decode()
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_upload_receipt(
                {
                    "receipt_data": receipt_data,
                    "employee_id": 999,
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_upload_valid_content_types(self, mock_tracker):
        receipt_data = base64.b64encode(b"fake-image-data").decode()
        for ct in ("image/png", "image/jpeg", "image/jpg", "application/pdf"):
            with patch(
                "aragora.server.handlers.expenses.get_expense_tracker",
                return_value=mock_tracker,
            ):
                result = await handle_upload_receipt(
                    {
                        "receipt_data": receipt_data,
                        "content_type": ct,
                    }
                )
            assert _status(result) == 200, f"Failed for content_type={ct}"

    @pytest.mark.asyncio
    async def test_upload_invalid_payment_method_defaults(self, mock_tracker):
        receipt_data = base64.b64encode(b"data").decode()
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_upload_receipt(
                {
                    "receipt_data": receipt_data,
                    "payment_method": "bitcoin",
                }
            )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_upload_service_error(self, mock_tracker):
        receipt_data = base64.b64encode(b"data").decode()
        mock_tracker.process_receipt.side_effect = RuntimeError("OCR failed")
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_upload_receipt({"receipt_data": receipt_data})
        assert _status(result) == 500

    async def test_upload_via_handler_post(self, handler, mock_tracker):
        receipt_data = base64.b64encode(b"data").decode()
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle_post(
                "/api/v1/accounting/expenses/upload",
                {"receipt_data": receipt_data},
                None,
            )
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# POST /api/v1/accounting/expenses (create)
# ---------------------------------------------------------------------------


class TestCreateExpense:
    """Tests for creating expenses manually."""

    @pytest.mark.asyncio
    async def test_create_success(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Office Depot",
                    "amount": 99.99,
                }
            )
        body = _body(result)
        assert _status(result) == 200
        assert "expense" in body
        assert body["message"] == "Expense created successfully"

    @pytest.mark.asyncio
    async def test_create_missing_vendor_name(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense({"amount": 50.00})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_non_string_vendor_name(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense({"vendor_name": 123, "amount": 50.00})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_vendor_name_too_long(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "x" * 501,
                    "amount": 50.00,
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_missing_amount(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense({"vendor_name": "Acme"})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_invalid_amount(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": "not-a-number",
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_negative_amount(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": -10.0,
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_amount_exceeds_max(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": 2_000_000_000,
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_invalid_date(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": 50.0,
                    "date": "not-a-date",
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_non_string_date(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": 50.0,
                    "date": 12345,
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_description_too_long(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": 50.0,
                    "description": "x" * 5001,
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_tags_not_list(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": 50.0,
                    "tags": "not-a-list",
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_too_many_tags(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": 50.0,
                    "tags": [f"tag-{i}" for i in range(51)],
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_tag_too_long(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": 50.0,
                    "tags": ["x" * 101],
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_tag_non_string(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": 50.0,
                    "tags": [123],
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_with_valid_category(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": 50.0,
                    "category": "travel",
                }
            )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_create_invalid_category_falls_through(self, mock_tracker):
        """Invalid category is silently ignored (auto-categorize later)."""
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": 50.0,
                    "category": "invalid_category",
                }
            )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_create_invalid_payment_method_defaults(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": 50.0,
                    "payment_method": "gold_bullion",
                }
            )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_create_with_all_fields(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Office Depot",
                    "amount": 99.99,
                    "date": "2025-06-15T10:00:00Z",
                    "category": "office_supplies",
                    "payment_method": "credit_card",
                    "description": "Monthly supplies",
                    "employee_id": "emp-001",
                    "is_reimbursable": True,
                    "tags": ["monthly", "supplies"],
                }
            )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_create_service_error(self, mock_tracker):
        mock_tracker.create_expense.side_effect = RuntimeError("DB error")
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_create_expense(
                {
                    "vendor_name": "Acme",
                    "amount": 50.0,
                }
            )
        assert _status(result) == 500

    async def test_create_via_handler_post(self, handler, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle_post(
                "/api/v1/accounting/expenses",
                {"vendor_name": "Acme", "amount": 50.0},
                None,
            )
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# PUT /api/v1/accounting/expenses/{id} (update)
# ---------------------------------------------------------------------------


class TestUpdateExpense:
    """Tests for updating expenses."""

    @pytest.mark.asyncio
    async def test_update_success(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense(
                "exp-001",
                {
                    "vendor_name": "New Vendor",
                    "amount": 200.0,
                },
            )
        body = _body(result)
        assert _status(result) == 200
        assert body["message"] == "Expense updated successfully"

    @pytest.mark.asyncio
    async def test_update_not_found(self, mock_tracker):
        mock_tracker.update_expense.return_value = None
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense("exp-missing", {"amount": 100})
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_update_empty_id(self):
        result = await handle_update_expense("", {})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_id_too_long(self):
        result = await handle_update_expense("x" * 101, {})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_invalid_vendor_name_type(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense("exp-001", {"vendor_name": 123})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_vendor_name_too_long(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense(
                "exp-001",
                {
                    "vendor_name": "x" * 501,
                },
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_invalid_amount(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense("exp-001", {"amount": "bad"})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_negative_amount(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense("exp-001", {"amount": -5})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_amount_exceeds_max(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense("exp-001", {"amount": 2_000_000_000})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_description_too_long(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense(
                "exp-001",
                {
                    "description": "x" * 5001,
                },
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_tags_not_list(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense("exp-001", {"tags": "not-a-list"})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_too_many_tags(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense(
                "exp-001",
                {
                    "tags": [f"tag-{i}" for i in range(51)],
                },
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_tag_too_long(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense(
                "exp-001",
                {
                    "tags": ["x" * 101],
                },
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_invalid_category_ignored(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense(
                "exp-001",
                {
                    "category": "nonexistent",
                },
            )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_update_invalid_status_ignored(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense(
                "exp-001",
                {
                    "status": "nonexistent",
                },
            )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_update_service_error(self, mock_tracker):
        mock_tracker.update_expense.side_effect = RuntimeError("Error")
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_update_expense("exp-001", {"amount": 100})
        assert _status(result) == 500

    async def test_update_via_handler_put(self, handler, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle_put(
                "/api/v1/accounting/expenses/exp-001",
                {"amount": 200.0},
                None,
            )
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# DELETE /api/v1/accounting/expenses/{id}
# ---------------------------------------------------------------------------


class TestDeleteExpense:
    """Tests for deleting expenses."""

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_delete_expense("exp-001")
        body = _body(result)
        assert _status(result) == 200
        assert body["message"] == "Expense deleted successfully"

    @pytest.mark.asyncio
    async def test_delete_not_found(self, mock_tracker):
        mock_tracker.delete_expense.return_value = False
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_delete_expense("exp-missing")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_delete_empty_id(self):
        result = await handle_delete_expense("")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_delete_id_too_long(self):
        result = await handle_delete_expense("x" * 101)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_delete_service_error(self, mock_tracker):
        mock_tracker.delete_expense.side_effect = RuntimeError("Error")
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_delete_expense("exp-001")
        assert _status(result) == 500

    async def test_delete_via_handler_delete(self, handler, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle_delete(
                "/api/v1/accounting/expenses/exp-001",
                {},
                None,
            )
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# POST /api/v1/accounting/expenses/{id}/approve
# ---------------------------------------------------------------------------


class TestApproveExpense:
    """Tests for approving expenses."""

    @pytest.mark.asyncio
    async def test_approve_success(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_approve_expense("exp-001")
        body = _body(result)
        assert _status(result) == 200
        assert body["message"] == "Expense approved successfully"

    @pytest.mark.asyncio
    async def test_approve_not_found(self, mock_tracker):
        mock_tracker.approve_expense.return_value = None
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_approve_expense("exp-missing")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_approve_empty_id(self):
        result = await handle_approve_expense("")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_approve_id_too_long(self):
        result = await handle_approve_expense("x" * 101)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_approve_service_error(self, mock_tracker):
        mock_tracker.approve_expense.side_effect = RuntimeError("Error")
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_approve_expense("exp-001")
        assert _status(result) == 500

    async def test_approve_via_handler_post(self, handler, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle_post(
                "/api/v1/accounting/expenses/exp-001/approve",
                {},
                None,
            )
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# POST /api/v1/accounting/expenses/{id}/reject
# ---------------------------------------------------------------------------


class TestRejectExpense:
    """Tests for rejecting expenses."""

    @pytest.mark.asyncio
    async def test_reject_success(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_reject_expense("exp-001", {"reason": "Duplicate"})
        body = _body(result)
        assert _status(result) == 200
        assert body["message"] == "Expense rejected"

    @pytest.mark.asyncio
    async def test_reject_without_reason(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_reject_expense("exp-001", {})
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_reject_not_found(self, mock_tracker):
        mock_tracker.reject_expense.return_value = None
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_reject_expense("exp-missing", {})
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_reject_reason_too_long(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_reject_expense(
                "exp-001",
                {
                    "reason": "x" * 1001,
                },
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_reject_empty_id(self):
        result = await handle_reject_expense("", {})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_reject_service_error(self, mock_tracker):
        mock_tracker.reject_expense.side_effect = RuntimeError("Error")
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_reject_expense("exp-001", {})
        assert _status(result) == 500

    async def test_reject_via_handler_post(self, handler, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle_post(
                "/api/v1/accounting/expenses/exp-001/reject",
                {"reason": "Not valid"},
                None,
            )
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# POST /api/v1/accounting/expenses/categorize
# ---------------------------------------------------------------------------


class TestCategorizeExpenses:
    """Tests for auto-categorization."""

    @pytest.mark.asyncio
    async def test_categorize_success(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_categorize_expenses(
                {
                    "expense_ids": ["exp-001"],
                }
            )
        body = _body(result)
        assert _status(result) == 200
        assert body["count"] == 1
        assert "exp-001" in body["categorized"]

    @pytest.mark.asyncio
    async def test_categorize_all_uncategorized(self, mock_tracker):
        """When no expense_ids provided, categorize all uncategorized."""
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_categorize_expenses({})
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_categorize_enum_values_handled(self, mock_tracker):
        """Test that enum category values get their .value extracted."""
        from aragora.services.expense_tracker import ExpenseCategory

        mock_tracker.bulk_categorize.return_value = {
            "exp-001": ExpenseCategory.TRAVEL,
        }
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_categorize_expenses({"expense_ids": ["exp-001"]})
        body = _body(result)
        assert body["categorized"]["exp-001"] == "travel"

    @pytest.mark.asyncio
    async def test_categorize_ids_not_list(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_categorize_expenses({"expense_ids": "not-a-list"})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_categorize_too_many_ids(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_categorize_expenses(
                {
                    "expense_ids": [f"exp-{i}" for i in range(1001)],
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_categorize_invalid_id_in_list(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_categorize_expenses(
                {
                    "expense_ids": [123],
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_categorize_id_too_long_in_list(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_categorize_expenses(
                {
                    "expense_ids": ["x" * 101],
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_categorize_service_error(self, mock_tracker):
        mock_tracker.bulk_categorize.side_effect = RuntimeError("Error")
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_categorize_expenses({})
        assert _status(result) == 500

    async def test_categorize_via_handler_post(self, handler, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle_post(
                "/api/v1/accounting/expenses/categorize",
                {"expense_ids": ["exp-001"]},
                None,
            )
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# POST /api/v1/accounting/expenses/sync (QBO)
# ---------------------------------------------------------------------------


class TestSyncToQBO:
    """Tests for QBO sync."""

    @pytest.mark.asyncio
    async def test_sync_success(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_sync_to_qbo(
                {
                    "expense_ids": ["exp-001", "exp-002"],
                }
            )
        body = _body(result)
        assert _status(result) == 200
        assert "result" in body
        assert "Synced 3 expenses" in body["message"]

    @pytest.mark.asyncio
    async def test_sync_all_approved(self, mock_tracker):
        """When no expense_ids provided, sync all approved."""
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_sync_to_qbo({})
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_sync_dict_result(self, mock_tracker):
        """When sync returns a plain dict (no to_dict method)."""
        mock_tracker.sync_to_qbo.return_value = {"synced": 5, "failed": 1}
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_sync_to_qbo({})
        body = _body(result)
        assert "Synced 5 expenses" in body["message"]

    @pytest.mark.asyncio
    async def test_sync_ids_not_list(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_sync_to_qbo({"expense_ids": "not-a-list"})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_sync_too_many_ids(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_sync_to_qbo(
                {
                    "expense_ids": [f"exp-{i}" for i in range(501)],
                }
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_sync_invalid_id_in_list(self, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_sync_to_qbo({"expense_ids": [999]})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_sync_service_error(self, mock_tracker):
        mock_tracker.sync_to_qbo.side_effect = ConnectionError("QBO down")
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handle_sync_to_qbo({})
        assert _status(result) == 500

    async def test_sync_via_handler_post(self, handler, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle_post(
                "/api/v1/accounting/expenses/sync",
                {},
                None,
            )
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# Circuit Breaker behavior
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """Tests for circuit breaker integration."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_upload(self):
        cb = get_expense_circuit_breaker()
        # Force circuit breaker open by recording many failures
        for _ in range(10):
            cb.record_failure()

        receipt_data = base64.b64encode(b"data").decode()
        result = await handle_upload_receipt({"receipt_data": receipt_data})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_create(self):
        cb = get_expense_circuit_breaker()
        for _ in range(10):
            cb.record_failure()

        result = await handle_create_expense({"vendor_name": "Test", "amount": 10})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_list(self):
        cb = get_expense_circuit_breaker()
        for _ in range(10):
            cb.record_failure()

        result = await handle_list_expenses({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_get(self):
        cb = get_expense_circuit_breaker()
        for _ in range(10):
            cb.record_failure()

        result = await handle_get_expense("exp-001")
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_delete(self):
        cb = get_expense_circuit_breaker()
        for _ in range(10):
            cb.record_failure()

        result = await handle_delete_expense("exp-001")
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_approve(self):
        cb = get_expense_circuit_breaker()
        for _ in range(10):
            cb.record_failure()

        result = await handle_approve_expense("exp-001")
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_reject(self):
        cb = get_expense_circuit_breaker()
        for _ in range(10):
            cb.record_failure()

        result = await handle_reject_expense("exp-001", {})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_stats(self):
        cb = get_expense_circuit_breaker()
        for _ in range(10):
            cb.record_failure()

        result = await handle_get_expense_stats({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_pending(self):
        cb = get_expense_circuit_breaker()
        for _ in range(10):
            cb.record_failure()

        result = await handle_get_pending_approvals()
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_export(self):
        cb = get_expense_circuit_breaker()
        for _ in range(10):
            cb.record_failure()

        result = await handle_export_expenses({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_categorize(self):
        cb = get_expense_circuit_breaker()
        for _ in range(10):
            cb.record_failure()

        result = await handle_categorize_expenses({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_sync(self):
        cb = get_expense_circuit_breaker()
        for _ in range(10):
            cb.record_failure()

        result = await handle_sync_to_qbo({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_update(self):
        cb = get_expense_circuit_breaker()
        for _ in range(10):
            cb.record_failure()

        result = await handle_update_expense("exp-001", {})
        assert _status(result) == 503

    def test_reset_circuit_breaker(self):
        cb = get_expense_circuit_breaker()
        for _ in range(10):
            cb.record_failure()
        reset_expense_circuit_breaker()
        assert cb.can_proceed()


# ---------------------------------------------------------------------------
# Handler dispatch routing (GET routes not found)
# ---------------------------------------------------------------------------


class TestHandlerRouteNotFound:
    """Tests for 404 on unmatched routes."""

    async def test_get_unknown_route(self, handler):
        result = await handler.handle("/api/v1/accounting/expenses/exp-1/unknown", {}, None)
        assert _status(result) == 404

    async def test_post_unknown_route(self, handler, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle_post(
                "/api/v1/accounting/expenses/exp-1/unknown", {}, None
            )
        assert _status(result) == 404

    async def test_put_no_expense_id(self, handler, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle_put("/api/v1/accounting", {}, None)
        assert _status(result) == 404

    async def test_delete_no_expense_id(self, handler, mock_tracker):
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle_delete("/api/v1/accounting", {}, None)
        assert _status(result) == 404

    async def test_get_approve_path_returns_404(self, handler, mock_tracker):
        """GET on /approve path should return 404 (not a GET route)."""
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle("/api/v1/accounting/expenses/exp-001/approve", {}, None)
        assert _status(result) == 404

    async def test_get_reject_path_returns_404(self, handler, mock_tracker):
        """GET on /reject path should return 404 (not a GET route)."""
        with patch(
            "aragora.server.handlers.expenses.get_expense_tracker",
            return_value=mock_tracker,
        ):
            result = await handler.handle("/api/v1/accounting/expenses/exp-001/reject", {}, None)
        assert _status(result) == 404
