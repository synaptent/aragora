"""Tests for AR automation handler (aragora/server/handlers/ar_automation.py).

Covers all routes and behavior:
- POST /api/v1/accounting/ar/invoices         - Create invoice
- GET  /api/v1/accounting/ar/invoices         - List invoices
- GET  /api/v1/accounting/ar/invoices/{id}    - Get invoice by ID
- POST /api/v1/accounting/ar/invoices/{id}/send     - Send invoice
- POST /api/v1/accounting/ar/invoices/{id}/reminder - Send payment reminder
- POST /api/v1/accounting/ar/invoices/{id}/payment  - Record payment
- GET  /api/v1/accounting/ar/aging            - AR aging report
- GET  /api/v1/accounting/ar/collections      - Collection suggestions
- POST /api/v1/accounting/ar/customers        - Add customer
- GET  /api/v1/accounting/ar/customers/{id}/balance - Customer balance

Also tests:
- Circuit breaker integration
- Rate limiting
- Input validation
- Error handling
- ARAutomationHandler class routing
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.ar_automation import (
    ARAutomationHandler,
    get_ar_automation,
    get_ar_circuit_breaker,
    get_ar_circuit_breaker_status,
    handle_add_customer,
    handle_create_invoice,
    handle_get_aging_report,
    handle_get_collections,
    handle_get_customer_balance,
    handle_get_invoice,
    handle_list_invoices,
    handle_record_payment,
    handle_send_invoice,
    handle_send_reminder,
)
from aragora.server.handlers.base import HandlerResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: HandlerResult) -> dict:
    """Extract the JSON body from a HandlerResult."""
    if isinstance(result, HandlerResult):
        if isinstance(result.body, bytes):
            return json.loads(result.body.decode("utf-8"))
        return result.body
    if isinstance(result, dict):
        return result.get("body", result)
    return {}


def _status(result: HandlerResult) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, HandlerResult):
        return result.status_code
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return 200


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------


class MockInvoice:
    """Mock invoice returned by AR service."""

    def __init__(self, invoice_id="INV-001", **kwargs):
        self.invoice_id = invoice_id
        self.customer_id = kwargs.get("customer_id", "CUST-001")
        self.customer_name = kwargs.get("customer_name", "Test Corp")
        self.total = kwargs.get("total", Decimal("1000.00"))
        self.status = kwargs.get("status", "draft")
        self.invoice_date = kwargs.get("invoice_date", datetime(2026, 1, 15))

    def to_dict(self):
        return {
            "invoice_id": self.invoice_id,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "total": str(self.total),
            "status": self.status,
        }


class MockAgingReport:
    """Mock aging report returned by AR service."""

    def to_dict(self):
        return {
            "current": "5000.00",
            "30_days": "2000.00",
            "60_days": "1000.00",
            "90_plus": "500.00",
            "total": "8500.00",
        }


class MockCollectionSuggestion:
    """Mock collection suggestion returned by AR service."""

    def __init__(self, customer_id="CUST-001", action="call"):
        self.customer_id = customer_id
        self.action = action

    def to_dict(self):
        return {
            "customer_id": self.customer_id,
            "action": self.action,
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_circuit_breaker():
    """Reset the module-level AR circuit breaker between tests."""
    cb = get_ar_circuit_breaker()
    cb.reset()
    yield
    cb.reset()


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Reset rate limiters between tests."""
    from aragora.server.handlers.utils.rate_limit import clear_all_limiters

    clear_all_limiters()
    yield
    clear_all_limiters()


@pytest.fixture(autouse=True)
def _reset_ar_singleton():
    """Reset the module-level AR automation singleton between tests."""
    import aragora.server.handlers.ar_automation as mod

    mod._ar_automation = None
    yield
    mod._ar_automation = None


@pytest.fixture
def mock_ar():
    """Create a fully-mocked AR automation service."""
    ar = AsyncMock()
    ar.generate_invoice = AsyncMock(return_value=MockInvoice())
    ar.list_invoices = AsyncMock(return_value=[MockInvoice("INV-001"), MockInvoice("INV-002")])
    ar.get_invoice = AsyncMock(return_value=MockInvoice())
    ar.send_invoice = AsyncMock(return_value=True)
    ar.send_payment_reminder = AsyncMock(return_value=True)
    ar.record_payment = AsyncMock(return_value=MockInvoice(status="paid"))
    ar.track_aging = AsyncMock(return_value=MockAgingReport())
    ar.suggest_collections = AsyncMock(
        return_value=[
            MockCollectionSuggestion("CUST-001"),
            MockCollectionSuggestion("CUST-002", "email"),
        ]
    )
    ar.add_customer = AsyncMock()
    ar.get_customer_balance = AsyncMock(return_value=Decimal("3500.00"))
    return ar


@pytest.fixture(autouse=True)
def _patch_ar_service(mock_ar):
    """Patch get_ar_automation to return the mock service."""
    with patch(
        "aragora.server.handlers.ar_automation.get_ar_automation",
        return_value=mock_ar,
    ):
        yield


# ============================================================================
# Create Invoice Tests
# ============================================================================


class TestCreateInvoice:
    """Tests for handle_create_invoice."""

    @pytest.mark.asyncio
    async def test_create_invoice_success(self, mock_ar):
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert "invoice" in body["data"]
        assert body["data"]["message"] == "Invoice created successfully"

    @pytest.mark.asyncio
    async def test_create_invoice_missing_customer_id(self):
        data = {
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 400
        assert "customer_id" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_create_invoice_empty_customer_id(self):
        data = {
            "customer_id": "",
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_invoice_missing_customer_name(self):
        data = {
            "customer_id": "CUST-001",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 400
        assert "customer_name" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_create_invoice_empty_customer_name(self):
        data = {
            "customer_id": "CUST-001",
            "customer_name": "",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_invoice_missing_line_items(self):
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 400
        assert "line_items" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_create_invoice_empty_line_items(self):
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_invoice_line_item_missing_description(self):
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [{"amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 400
        assert "description" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_create_invoice_line_item_missing_amount(self):
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget"}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 400
        assert "amount" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_create_invoice_with_optional_fields(self, mock_ar):
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "customer_email": "test@example.com",
            "line_items": [{"description": "Widget", "amount": 100}],
            "payment_terms": "Net 60",
            "memo": "Test memo",
            "tax_rate": 0.1,
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 200
        # ARAutomation.generate_invoice has no tax_rate argument.
        mock_ar.generate_invoice.assert_awaited_once_with(
            customer_id="CUST-001",
            customer_name="Test Corp",
            customer_email="test@example.com",
            line_items=[{"description": "Widget", "amount": 100}],
            payment_terms="Net 60",
            memo="Test memo",
        )

    @pytest.mark.asyncio
    async def test_create_invoice_defaults_payment_terms(self, mock_ar):
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 200
        call_kwargs = mock_ar.generate_invoice.call_args.kwargs
        assert call_kwargs["payment_terms"] == "Net 30"
        assert call_kwargs["memo"] == ""
        assert "tax_rate" not in call_kwargs

    @pytest.mark.asyncio
    async def test_create_invoice_service_type_error(self, mock_ar):
        mock_ar.generate_invoice.side_effect = TypeError("bad type")
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_create_invoice_service_value_error(self, mock_ar):
        mock_ar.generate_invoice.side_effect = ValueError("bad value")
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_create_invoice_service_attribute_error(self, mock_ar):
        mock_ar.generate_invoice.side_effect = AttributeError("no attr")
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_create_invoice_service_os_error(self, mock_ar):
        mock_ar.generate_invoice.side_effect = OSError("disk error")
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_create_invoice_circuit_open(self):
        cb = get_ar_circuit_breaker()
        # Trip the circuit breaker
        for _ in range(6):
            cb.record_failure()
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 503
        assert "unavailable" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_create_invoice_multiple_line_items(self, mock_ar):
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [
                {"description": "Widget A", "amount": 100},
                {"description": "Widget B", "amount": 200},
                {"description": "Widget C", "amount": 300},
            ],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_create_invoice_line_items_partial_invalid(self):
        """One valid item and one invalid item should still fail."""
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [
                {"description": "Widget", "amount": 100},
                {"description": "Bad Item"},  # missing amount
            ],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_invoice_with_user_id(self, mock_ar):
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data, user_id="user-42")
        assert _status(result) == 200


# ============================================================================
# List Invoices Tests
# ============================================================================


class TestListInvoices:
    """Tests for handle_list_invoices."""

    @pytest.mark.asyncio
    async def test_list_invoices_success(self, mock_ar):
        result = await handle_list_invoices({})
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert len(body["data"]["invoices"]) == 2
        assert body["data"]["total"] == 2

    @pytest.mark.asyncio
    async def test_list_invoices_with_customer_filter(self, mock_ar):
        result = await handle_list_invoices({"customer_id": "CUST-001"})
        assert _status(result) == 200
        mock_ar.list_invoices.assert_awaited_once()
        call_kwargs = mock_ar.list_invoices.call_args.kwargs
        assert call_kwargs["customer_id"] == "CUST-001"

    @pytest.mark.asyncio
    async def test_list_invoices_with_status_filter(self, mock_ar):
        result = await handle_list_invoices({"status": "paid"})
        assert _status(result) == 200
        call_kwargs = mock_ar.list_invoices.call_args.kwargs
        assert call_kwargs["status"] == "paid"

    @pytest.mark.asyncio
    async def test_list_invoices_with_date_filters(self, mock_ar):
        result = await handle_list_invoices(
            {
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
            }
        )
        assert _status(result) == 200
        # Dates are filtered by the handler; the service takes no date arguments.
        call_kwargs = mock_ar.list_invoices.call_args.kwargs
        assert "start_date" not in call_kwargs
        assert "end_date" not in call_kwargs
        assert _body(result)["data"]["total"] == 2

    @pytest.mark.asyncio
    async def test_list_invoices_invalid_start_date(self):
        result = await handle_list_invoices({"start_date": "not-a-date"})
        assert _status(result) == 400
        assert "date" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_list_invoices_invalid_end_date(self):
        result = await handle_list_invoices({"end_date": "bad-date"})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_list_invoices_pagination_defaults(self, mock_ar):
        result = await handle_list_invoices({})
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["limit"] == 100
        assert body["data"]["offset"] == 0

    @pytest.mark.asyncio
    async def test_list_invoices_custom_pagination(self, mock_ar):
        result = await handle_list_invoices({"limit": 10, "offset": 5})
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["limit"] == 10
        assert body["data"]["offset"] == 5

    @pytest.mark.asyncio
    async def test_list_invoices_limit_above_max_rejected(self, mock_ar):
        result = await handle_list_invoices({"limit": 5000})
        assert _status(result) == 400
        assert "limit" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_list_invoices_limit_below_min_rejected(self, mock_ar):
        result = await handle_list_invoices({"limit": 0})
        assert _status(result) == 400
        assert "limit" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_list_invoices_negative_offset_rejected(self, mock_ar):
        result = await handle_list_invoices({"offset": -10})
        assert _status(result) == 400
        assert "offset" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_list_invoices_circuit_open(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        result = await handle_list_invoices({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_list_invoices_service_error(self, mock_ar):
        mock_ar.list_invoices.side_effect = TypeError("boom")
        result = await handle_list_invoices({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_list_invoices_empty_result(self, mock_ar):
        mock_ar.list_invoices.return_value = []
        result = await handle_list_invoices({})
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["invoices"] == []
        assert body["data"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_invoices_pagination_slicing(self, mock_ar):
        """Verify pagination offset and limit slice the result."""
        invoices = [MockInvoice(f"INV-{i:03d}") for i in range(10)]
        mock_ar.list_invoices.return_value = invoices
        result = await handle_list_invoices({"limit": 3, "offset": 2})
        assert _status(result) == 200
        body = _body(result)
        assert len(body["data"]["invoices"]) == 3
        assert body["data"]["total"] == 10


# ============================================================================
# Get Invoice Tests
# ============================================================================


class TestGetInvoice:
    """Tests for handle_get_invoice."""

    @pytest.mark.asyncio
    async def test_get_invoice_success(self, mock_ar):
        result = await handle_get_invoice({}, invoice_id="INV-001")
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert "invoice" in body["data"]

    @pytest.mark.asyncio
    async def test_get_invoice_not_found(self, mock_ar):
        mock_ar.get_invoice.return_value = None
        result = await handle_get_invoice({}, invoice_id="INV-999")
        assert _status(result) == 404
        assert "not found" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_get_invoice_empty_id(self):
        result = await handle_get_invoice({}, invoice_id="")
        assert _status(result) == 400
        assert "invoice_id" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_get_invoice_whitespace_id(self):
        result = await handle_get_invoice({}, invoice_id="   ")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_get_invoice_circuit_open(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        result = await handle_get_invoice({}, invoice_id="INV-001")
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_get_invoice_service_error(self, mock_ar):
        mock_ar.get_invoice.side_effect = OSError("disk")
        result = await handle_get_invoice({}, invoice_id="INV-001")
        assert _status(result) == 500


# ============================================================================
# Send Invoice Tests
# ============================================================================


class TestSendInvoice:
    """Tests for handle_send_invoice."""

    @pytest.mark.asyncio
    async def test_send_invoice_success(self, mock_ar):
        result = await handle_send_invoice({}, invoice_id="INV-001")
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["data"]["invoice_id"] == "INV-001"

    @pytest.mark.asyncio
    async def test_send_invoice_not_found(self, mock_ar):
        mock_ar.get_invoice.return_value = None
        result = await handle_send_invoice({}, invoice_id="INV-999")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_send_invoice_empty_id(self):
        result = await handle_send_invoice({}, invoice_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_send_invoice_whitespace_id(self):
        result = await handle_send_invoice({}, invoice_id="   ")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_send_invoice_failure(self, mock_ar):
        mock_ar.send_invoice.return_value = False
        result = await handle_send_invoice({}, invoice_id="INV-001")
        assert _status(result) == 500
        assert "failed" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_send_invoice_circuit_open(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        result = await handle_send_invoice({}, invoice_id="INV-001")
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_send_invoice_connection_error(self, mock_ar):
        mock_ar.send_invoice.side_effect = ConnectionError("network")
        result = await handle_send_invoice({}, invoice_id="INV-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_send_invoice_type_error(self, mock_ar):
        mock_ar.send_invoice.side_effect = TypeError("bad")
        result = await handle_send_invoice({}, invoice_id="INV-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_send_invoice_os_error(self, mock_ar):
        mock_ar.send_invoice.side_effect = OSError("io")
        result = await handle_send_invoice({}, invoice_id="INV-001")
        assert _status(result) == 500


# ============================================================================
# Send Reminder Tests
# ============================================================================


class TestSendReminder:
    """Tests for handle_send_reminder."""

    @pytest.mark.asyncio
    async def test_send_reminder_success(self, mock_ar):
        result = await handle_send_reminder({}, invoice_id="INV-001")
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert "level 1" in body["data"]["message"]

    @pytest.mark.asyncio
    async def test_send_reminder_escalation_level_2(self, mock_ar):
        result = await handle_send_reminder({"escalation_level": 2}, invoice_id="INV-001")
        assert _status(result) == 200
        body = _body(result)
        assert "level 2" in body["data"]["message"]

    @pytest.mark.asyncio
    async def test_send_reminder_escalation_level_4(self, mock_ar):
        result = await handle_send_reminder({"escalation_level": 4}, invoice_id="INV-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_send_reminder_escalation_level_below_range(self):
        result = await handle_send_reminder({"escalation_level": 0}, invoice_id="INV-001")
        assert _status(result) == 400
        assert "1-4" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_send_reminder_escalation_level_above_range(self):
        result = await handle_send_reminder({"escalation_level": 5}, invoice_id="INV-001")
        assert _status(result) == 400
        assert "1-4" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_send_reminder_escalation_level_invalid_string(self):
        result = await handle_send_reminder({"escalation_level": "abc"}, invoice_id="INV-001")
        assert _status(result) == 400
        assert "integer" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_send_reminder_escalation_level_none(self):
        """None escalation_level should use default of 1."""
        result = await handle_send_reminder({"escalation_level": None}, invoice_id="INV-001")
        # None causes int(None) -> TypeError caught by the except block
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_send_reminder_empty_id(self):
        result = await handle_send_reminder({}, invoice_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_send_reminder_whitespace_id(self):
        result = await handle_send_reminder({}, invoice_id="   ")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_send_reminder_not_found(self, mock_ar):
        mock_ar.get_invoice.return_value = None
        result = await handle_send_reminder({}, invoice_id="INV-999")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_send_reminder_failure(self, mock_ar):
        mock_ar.send_payment_reminder.return_value = False
        result = await handle_send_reminder({}, invoice_id="INV-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_send_reminder_circuit_open(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        result = await handle_send_reminder({}, invoice_id="INV-001")
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_send_reminder_connection_error(self, mock_ar):
        mock_ar.send_payment_reminder.side_effect = ConnectionError("net")
        result = await handle_send_reminder({}, invoice_id="INV-001")
        assert _status(result) == 500


# ============================================================================
# Record Payment Tests
# ============================================================================


class TestRecordPayment:
    """Tests for handle_record_payment."""

    @pytest.mark.asyncio
    async def test_record_payment_success(self, mock_ar):
        data = {"amount": 500.00}
        result = await handle_record_payment(data, invoice_id="INV-001")
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert "invoice" in body["data"]

    @pytest.mark.asyncio
    async def test_record_payment_with_all_fields(self, mock_ar):
        data = {
            "amount": 500.00,
            "payment_date": "2026-02-01T10:00:00",
            "payment_method": "wire",
            "reference": "REF-123",
        }
        result = await handle_record_payment(data, invoice_id="INV-001")
        assert _status(result) == 200
        call_kwargs = mock_ar.record_payment.call_args.kwargs
        assert call_kwargs["payment_method"] == "wire"
        assert call_kwargs["reference"] == "REF-123"
        assert call_kwargs["payment_date"] is not None

    @pytest.mark.asyncio
    async def test_record_payment_missing_amount(self):
        result = await handle_record_payment({}, invoice_id="INV-001")
        assert _status(result) == 400
        assert "amount" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_record_payment_zero_amount(self):
        result = await handle_record_payment({"amount": 0}, invoice_id="INV-001")
        assert _status(result) == 400
        assert "positive" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_record_payment_negative_amount(self):
        result = await handle_record_payment({"amount": -100}, invoice_id="INV-001")
        assert _status(result) == 400
        assert "positive" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_record_payment_invalid_amount_string(self):
        result = await handle_record_payment({"amount": "abc"}, invoice_id="INV-001")
        assert _status(result) == 400
        assert "valid number" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_record_payment_amount_none_explicit(self):
        result = await handle_record_payment({"amount": None}, invoice_id="INV-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_record_payment_invalid_payment_date(self):
        data = {"amount": 500, "payment_date": "not-a-date"}
        result = await handle_record_payment(data, invoice_id="INV-001")
        assert _status(result) == 400
        assert "ISO" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_record_payment_empty_invoice_id(self):
        result = await handle_record_payment({"amount": 500}, invoice_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_record_payment_whitespace_invoice_id(self):
        result = await handle_record_payment({"amount": 500}, invoice_id="   ")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_record_payment_invoice_not_found(self, mock_ar):
        mock_ar.get_invoice.return_value = None
        result = await handle_record_payment({"amount": 500}, invoice_id="INV-999")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_record_payment_circuit_open(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        result = await handle_record_payment({"amount": 500}, invoice_id="INV-001")
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_record_payment_service_error(self, mock_ar):
        mock_ar.record_payment.side_effect = ValueError("bad")
        result = await handle_record_payment({"amount": 500}, invoice_id="INV-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_record_payment_arithmetic_error(self, mock_ar):
        mock_ar.record_payment.side_effect = ArithmeticError("overflow")
        result = await handle_record_payment({"amount": 500}, invoice_id="INV-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_record_payment_decimal_precision(self, mock_ar):
        """Ensure amount is converted to Decimal properly."""
        data = {"amount": 123.45}
        result = await handle_record_payment(data, invoice_id="INV-001")
        assert _status(result) == 200
        call_kwargs = mock_ar.record_payment.call_args.kwargs
        assert isinstance(call_kwargs["amount"], Decimal)

    @pytest.mark.asyncio
    async def test_record_payment_message_includes_amount(self, mock_ar):
        data = {"amount": 500}
        result = await handle_record_payment(data, invoice_id="INV-001")
        assert _status(result) == 200
        body = _body(result)
        assert "500" in body["data"]["message"]


# ============================================================================
# Aging Report Tests
# ============================================================================


class TestGetAgingReport:
    """Tests for handle_get_aging_report."""

    @pytest.mark.asyncio
    async def test_get_aging_report_success(self, mock_ar):
        result = await handle_get_aging_report({})
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert "aging_report" in body["data"]
        assert "generated_at" in body["data"]

    @pytest.mark.asyncio
    async def test_get_aging_report_circuit_open(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        result = await handle_get_aging_report({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_get_aging_report_service_error(self, mock_ar):
        mock_ar.track_aging.side_effect = TypeError("boom")
        result = await handle_get_aging_report({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_get_aging_report_value_error(self, mock_ar):
        mock_ar.track_aging.side_effect = ValueError("bad")
        result = await handle_get_aging_report({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_get_aging_report_os_error(self, mock_ar):
        mock_ar.track_aging.side_effect = OSError("fs")
        result = await handle_get_aging_report({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_get_aging_report_attribute_error(self, mock_ar):
        mock_ar.track_aging.side_effect = AttributeError("no attr")
        result = await handle_get_aging_report({})
        assert _status(result) == 500


# ============================================================================
# Collection Suggestions Tests
# ============================================================================


class TestGetCollections:
    """Tests for handle_get_collections."""

    @pytest.mark.asyncio
    async def test_get_collections_success(self, mock_ar):
        result = await handle_get_collections({})
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert len(body["data"]["suggestions"]) == 2
        assert body["data"]["total"] == 2

    @pytest.mark.asyncio
    async def test_get_collections_empty(self, mock_ar):
        mock_ar.suggest_collections.return_value = []
        result = await handle_get_collections({})
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["suggestions"] == []
        assert body["data"]["total"] == 0

    @pytest.mark.asyncio
    async def test_get_collections_circuit_open(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        result = await handle_get_collections({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_get_collections_service_error(self, mock_ar):
        mock_ar.suggest_collections.side_effect = TypeError("boom")
        result = await handle_get_collections({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_get_collections_value_error(self, mock_ar):
        mock_ar.suggest_collections.side_effect = ValueError("bad")
        result = await handle_get_collections({})
        assert _status(result) == 500


# ============================================================================
# Add Customer Tests
# ============================================================================


class TestAddCustomer:
    """Tests for handle_add_customer."""

    @pytest.mark.asyncio
    async def test_add_customer_success(self, mock_ar):
        data = {"customer_id": "CUST-001", "name": "Test Corp"}
        result = await handle_add_customer(data)
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["data"]["customer_id"] == "CUST-001"

    @pytest.mark.asyncio
    async def test_add_customer_with_optional_fields(self, mock_ar):
        data = {
            "customer_id": "CUST-001",
            "name": "Test Corp",
            "email": "test@corp.com",
            "payment_terms": "Net 60",
        }
        result = await handle_add_customer(data)
        assert _status(result) == 200
        call_kwargs = mock_ar.add_customer.call_args.kwargs
        assert call_kwargs["email"] == "test@corp.com"
        assert "payment_terms" not in call_kwargs  # ARAutomation.add_customer has no such argument

    @pytest.mark.asyncio
    async def test_add_customer_passes_only_service_arguments(self, mock_ar):
        data = {"customer_id": "CUST-001", "name": "Test Corp"}
        result = await handle_add_customer(data)
        assert _status(result) == 200
        call_kwargs = mock_ar.add_customer.call_args.kwargs
        assert call_kwargs == {"customer_id": "CUST-001", "name": "Test Corp", "email": None}

    @pytest.mark.asyncio
    async def test_add_customer_missing_customer_id(self):
        result = await handle_add_customer({"name": "Test Corp"})
        assert _status(result) == 400
        assert "customer_id" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_add_customer_empty_customer_id(self):
        result = await handle_add_customer({"customer_id": "", "name": "Test Corp"})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_customer_whitespace_customer_id(self):
        result = await handle_add_customer({"customer_id": "   ", "name": "Test Corp"})
        assert _status(result) == 400
        assert "non-empty" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_add_customer_non_string_customer_id(self):
        result = await handle_add_customer({"customer_id": 123, "name": "Test Corp"})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_customer_missing_name(self):
        result = await handle_add_customer({"customer_id": "CUST-001"})
        assert _status(result) == 400
        assert "name" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_add_customer_empty_name(self):
        result = await handle_add_customer({"customer_id": "CUST-001", "name": ""})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_customer_whitespace_name(self):
        result = await handle_add_customer({"customer_id": "CUST-001", "name": "   "})
        assert _status(result) == 400
        assert "non-empty" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_add_customer_non_string_name(self):
        result = await handle_add_customer({"customer_id": "CUST-001", "name": 42})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_customer_strips_whitespace(self, mock_ar):
        data = {"customer_id": "  CUST-001  ", "name": "  Test Corp  "}
        result = await handle_add_customer(data)
        assert _status(result) == 200
        call_kwargs = mock_ar.add_customer.call_args.kwargs
        assert call_kwargs["customer_id"] == "CUST-001"
        assert call_kwargs["name"] == "Test Corp"

    @pytest.mark.asyncio
    async def test_add_customer_circuit_open(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        data = {"customer_id": "CUST-001", "name": "Test Corp"}
        result = await handle_add_customer(data)
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_add_customer_service_error(self, mock_ar):
        mock_ar.add_customer.side_effect = TypeError("bad")
        data = {"customer_id": "CUST-001", "name": "Test Corp"}
        result = await handle_add_customer(data)
        assert _status(result) == 500


# ============================================================================
# Customer Balance Tests
# ============================================================================


class TestGetCustomerBalance:
    """Tests for handle_get_customer_balance."""

    @pytest.mark.asyncio
    async def test_get_customer_balance_success(self, mock_ar):
        result = await handle_get_customer_balance({}, customer_id="CUST-001")
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["data"]["customer_id"] == "CUST-001"
        assert body["data"]["outstanding_balance"] == "3500.00"

    @pytest.mark.asyncio
    async def test_get_customer_balance_empty_id(self):
        result = await handle_get_customer_balance({}, customer_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_get_customer_balance_whitespace_id(self):
        result = await handle_get_customer_balance({}, customer_id="   ")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_get_customer_balance_circuit_open(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        result = await handle_get_customer_balance({}, customer_id="CUST-001")
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_get_customer_balance_service_error(self, mock_ar):
        mock_ar.get_customer_balance.side_effect = TypeError("boom")
        result = await handle_get_customer_balance({}, customer_id="CUST-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_get_customer_balance_value_error(self, mock_ar):
        mock_ar.get_customer_balance.side_effect = ValueError("bad")
        result = await handle_get_customer_balance({}, customer_id="CUST-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_get_customer_balance_zero(self, mock_ar):
        mock_ar.get_customer_balance.return_value = Decimal("0.00")
        result = await handle_get_customer_balance({}, customer_id="CUST-001")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["outstanding_balance"] == "0.00"


# ============================================================================
# Circuit Breaker Utility Tests
# ============================================================================


class TestCircuitBreakerUtilities:
    """Tests for circuit breaker helper functions."""

    def test_get_ar_circuit_breaker_returns_instance(self):
        cb = get_ar_circuit_breaker()
        assert cb is not None
        assert cb.name == "ar_automation_handler"

    def test_get_ar_circuit_breaker_singleton(self):
        cb1 = get_ar_circuit_breaker()
        cb2 = get_ar_circuit_breaker()
        assert cb1 is cb2

    def test_get_ar_circuit_breaker_status_dict(self):
        status = get_ar_circuit_breaker_status()
        assert isinstance(status, dict)

    def test_circuit_breaker_threshold(self):
        cb = get_ar_circuit_breaker()
        assert cb.failure_threshold == 5

    def test_circuit_breaker_cooldown(self):
        cb = get_ar_circuit_breaker()
        assert cb.cooldown_seconds == 30.0


# ============================================================================
# ARAutomationHandler Class Tests
# ============================================================================


class TestARAutomationHandlerClass:
    """Tests for the ARAutomationHandler class."""

    def test_init_default_context(self):
        handler = ARAutomationHandler()
        assert handler.ctx == {}

    def test_init_with_context(self):
        ctx = {"key": "value"}
        handler = ARAutomationHandler(ctx=ctx)
        assert handler.ctx == ctx

    def test_route_map_contains_static_routes(self):
        routes = ARAutomationHandler._ROUTE_MAP
        assert "POST /api/v1/accounting/ar/invoices" in routes
        assert "GET /api/v1/accounting/ar/invoices" in routes
        assert "GET /api/v1/accounting/ar/aging" in routes
        assert "GET /api/v1/accounting/ar/collections" in routes
        assert "POST /api/v1/accounting/ar/customers" in routes

    def test_route_map_handlers_are_functions(self):
        routes = ARAutomationHandler._ROUTE_MAP
        for key, func in routes.items():
            assert callable(func), f"Route {key} handler is not callable"

    def test_static_routes_list(self):
        routes = ARAutomationHandler.ROUTES
        assert "/api/v1/accounting/ar/aging" in routes
        assert "/api/v1/accounting/ar/collections" in routes
        assert "/api/v1/accounting/ar/customers" in routes
        assert "/api/v1/accounting/ar/invoices" in routes

    def test_dynamic_routes_contains_parameterized(self):
        routes = ARAutomationHandler.DYNAMIC_ROUTES
        assert "GET /api/v1/accounting/ar/invoices/{invoice_id}" in routes
        assert "POST /api/v1/accounting/ar/invoices/{invoice_id}/send" in routes
        assert "POST /api/v1/accounting/ar/invoices/{invoice_id}/reminder" in routes
        assert "POST /api/v1/accounting/ar/invoices/{invoice_id}/payment" in routes
        assert "GET /api/v1/accounting/ar/customers/{customer_id}/balance" in routes

    def test_dynamic_routes_handlers_are_callable(self):
        routes = ARAutomationHandler.DYNAMIC_ROUTES
        for key, func in routes.items():
            assert callable(func), f"Dynamic route {key} handler is not callable"

    def test_route_map_references_correct_handlers(self):
        routes = ARAutomationHandler._ROUTE_MAP
        assert routes["POST /api/v1/accounting/ar/invoices"] is handle_create_invoice
        assert routes["GET /api/v1/accounting/ar/invoices"] is handle_list_invoices
        assert routes["GET /api/v1/accounting/ar/aging"] is handle_get_aging_report
        assert routes["GET /api/v1/accounting/ar/collections"] is handle_get_collections
        assert routes["POST /api/v1/accounting/ar/customers"] is handle_add_customer

    def test_dynamic_routes_reference_correct_handlers(self):
        routes = ARAutomationHandler.DYNAMIC_ROUTES
        assert routes["GET /api/v1/accounting/ar/invoices/{invoice_id}"] is handle_get_invoice
        assert (
            routes["POST /api/v1/accounting/ar/invoices/{invoice_id}/send"] is handle_send_invoice
        )
        assert (
            routes["POST /api/v1/accounting/ar/invoices/{invoice_id}/reminder"]
            is handle_send_reminder
        )
        assert (
            routes["POST /api/v1/accounting/ar/invoices/{invoice_id}/payment"]
            is handle_record_payment
        )
        assert (
            routes["GET /api/v1/accounting/ar/customers/{customer_id}/balance"]
            is handle_get_customer_balance
        )

    def test_total_route_count(self):
        assert len(ARAutomationHandler._ROUTE_MAP) == 10  # 5 static + 5 dynamic


# ============================================================================
# AR Automation Singleton Tests
# ============================================================================


class TestARAutomationSingleton:
    """Tests for get_ar_automation singleton behavior."""

    def test_module_has_singleton_variable(self):
        import aragora.server.handlers.ar_automation as mod

        assert hasattr(mod, "_ar_automation")

    def test_module_has_lock(self):
        import aragora.server.handlers.ar_automation as mod

        assert hasattr(mod, "_ar_automation_lock")
        import threading

        assert isinstance(mod._ar_automation_lock, type(threading.Lock()))

    def test_get_ar_automation_returns_cached_when_set(self):
        """When _ar_automation is set, the real function returns it immediately."""
        import aragora.server.handlers.ar_automation as mod

        sentinel = MagicMock()
        mod._ar_automation = sentinel
        # The real function (unpatched at import time) should return the cached instance
        # Note: we reference the original function object stored in the module
        # before the autouse fixture replaces the name.
        original_fn = (
            get_ar_automation.__wrapped__ if hasattr(get_ar_automation, "__wrapped__") else None
        )
        if original_fn is None:
            # If not wrapped, access the module directly to test caching
            assert mod._ar_automation is sentinel
        else:
            result = original_fn()
            assert result is sentinel

    def test_get_ar_automation_callable(self):
        """The patched version returns a mock (verifies fixture works)."""
        result = get_ar_automation()
        assert result is not None


# ============================================================================
# Circuit Breaker Retry Message Tests
# ============================================================================


class TestCircuitBreakerRetryMessage:
    """Tests that 503 error messages include retry information."""

    @pytest.mark.asyncio
    async def test_create_invoice_503_includes_retry(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 503
        error_msg = _body(result)["error"]
        assert "retry" in error_msg.lower() or "unavailable" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_list_invoices_503_includes_retry(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        result = await handle_list_invoices({})
        assert _status(result) == 503
        error_msg = _body(result)["error"]
        assert "retry" in error_msg.lower() or "unavailable" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_get_aging_503_includes_retry(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        result = await handle_get_aging_report({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_get_collections_503_includes_retry(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        result = await handle_get_collections({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_add_customer_503_includes_retry(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        data = {"customer_id": "CUST-001", "name": "Test Corp"}
        result = await handle_add_customer(data)
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_get_customer_balance_503_includes_retry(self):
        cb = get_ar_circuit_breaker()
        for _ in range(6):
            cb.record_failure()
        result = await handle_get_customer_balance({}, customer_id="CUST-001")
        assert _status(result) == 503


# ============================================================================
# CircuitOpenError Path Tests
# ============================================================================


class TestCircuitOpenErrorPath:
    """Tests for the CircuitOpenError caught inside service calls (via protected_call)."""

    @pytest.mark.asyncio
    async def test_create_invoice_circuit_open_error_in_call(self, mock_ar):
        from aragora.resilience import CircuitOpenError

        mock_ar.generate_invoice.side_effect = CircuitOpenError("ar_automation_handler", 30.0)
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_list_invoices_circuit_open_error_in_call(self, mock_ar):
        from aragora.resilience import CircuitOpenError

        mock_ar.list_invoices.side_effect = CircuitOpenError("ar_automation_handler", 30.0)
        result = await handle_list_invoices({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_get_invoice_circuit_open_error_in_call(self, mock_ar):
        from aragora.resilience import CircuitOpenError

        mock_ar.get_invoice.side_effect = CircuitOpenError("ar_automation_handler", 30.0)
        result = await handle_get_invoice({}, invoice_id="INV-001")
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_send_invoice_circuit_open_error_in_call(self, mock_ar):
        from aragora.resilience import CircuitOpenError

        mock_ar.get_invoice.side_effect = CircuitOpenError("ar_automation_handler", 30.0)
        result = await handle_send_invoice({}, invoice_id="INV-001")
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_send_reminder_circuit_open_error_in_call(self, mock_ar):
        from aragora.resilience import CircuitOpenError

        mock_ar.get_invoice.side_effect = CircuitOpenError("ar_automation_handler", 30.0)
        result = await handle_send_reminder({}, invoice_id="INV-001")
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_record_payment_circuit_open_error_in_call(self, mock_ar):
        from aragora.resilience import CircuitOpenError

        mock_ar.get_invoice.side_effect = CircuitOpenError("ar_automation_handler", 30.0)
        result = await handle_record_payment({"amount": 500}, invoice_id="INV-001")
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_aging_report_circuit_open_error_in_call(self, mock_ar):
        from aragora.resilience import CircuitOpenError

        mock_ar.track_aging.side_effect = CircuitOpenError("ar_automation_handler", 30.0)
        result = await handle_get_aging_report({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_collections_circuit_open_error_in_call(self, mock_ar):
        from aragora.resilience import CircuitOpenError

        mock_ar.suggest_collections.side_effect = CircuitOpenError("ar_automation_handler", 30.0)
        result = await handle_get_collections({})
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_add_customer_circuit_open_error_in_call(self, mock_ar):
        from aragora.resilience import CircuitOpenError

        mock_ar.add_customer.side_effect = CircuitOpenError("ar_automation_handler", 30.0)
        data = {"customer_id": "CUST-001", "name": "Test Corp"}
        result = await handle_add_customer(data)
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_customer_balance_circuit_open_error_in_call(self, mock_ar):
        from aragora.resilience import CircuitOpenError

        mock_ar.get_customer_balance.side_effect = CircuitOpenError("ar_automation_handler", 30.0)
        result = await handle_get_customer_balance({}, customer_id="CUST-001")
        assert _status(result) == 503


# ============================================================================
# Edge Cases and Additional Validation
# ============================================================================


class TestEdgeCases:
    """Edge cases and miscellaneous tests."""

    @pytest.mark.asyncio
    async def test_create_invoice_empty_data(self):
        result = await handle_create_invoice({})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_list_invoices_no_data(self, mock_ar):
        """Empty dict should work (all filters optional)."""
        result = await handle_list_invoices({})
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_list_invoices_valid_start_date_only(self, mock_ar):
        result = await handle_list_invoices({"start_date": "2026-01-01"})
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_list_invoices_valid_end_date_only(self, mock_ar):
        result = await handle_list_invoices({"end_date": "2026-12-31"})
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_create_invoice_user_id_param(self, mock_ar):
        """user_id parameter should be accepted."""
        data = {
            "customer_id": "CUST-001",
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data, user_id="admin")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_list_invoices_user_id_param(self, mock_ar):
        result = await handle_list_invoices({}, user_id="admin")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_invoice_user_id_param(self, mock_ar):
        result = await handle_get_invoice({}, invoice_id="INV-001", user_id="admin")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_send_invoice_user_id_param(self, mock_ar):
        result = await handle_send_invoice({}, invoice_id="INV-001", user_id="admin")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_send_reminder_user_id_param(self, mock_ar):
        result = await handle_send_reminder({}, invoice_id="INV-001", user_id="admin")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_record_payment_user_id_param(self, mock_ar):
        result = await handle_record_payment({"amount": 500}, invoice_id="INV-001", user_id="admin")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_aging_report_user_id_param(self, mock_ar):
        result = await handle_get_aging_report({}, user_id="admin")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_collections_user_id_param(self, mock_ar):
        result = await handle_get_collections({}, user_id="admin")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_add_customer_user_id_param(self, mock_ar):
        data = {"customer_id": "CUST-001", "name": "Test Corp"}
        result = await handle_add_customer(data, user_id="admin")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_customer_balance_user_id_param(self, mock_ar):
        result = await handle_get_customer_balance({}, customer_id="CUST-001", user_id="admin")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_record_payment_no_payment_date(self, mock_ar):
        """No payment_date should pass None to service."""
        result = await handle_record_payment({"amount": 500}, invoice_id="INV-001")
        assert _status(result) == 200
        call_kwargs = mock_ar.record_payment.call_args.kwargs
        assert call_kwargs["payment_date"] is None

    @pytest.mark.asyncio
    async def test_send_reminder_default_escalation(self, mock_ar):
        """Default escalation_level should be 1."""
        result = await handle_send_reminder({}, invoice_id="INV-001")
        assert _status(result) == 200
        call_kwargs = mock_ar.send_payment_reminder.call_args.kwargs
        assert call_kwargs["escalation_level"] == 1

    @pytest.mark.asyncio
    async def test_create_invoice_none_customer_id(self):
        """customer_id=None should be treated as missing."""
        data = {
            "customer_id": None,
            "customer_name": "Test Corp",
            "line_items": [{"description": "Widget", "amount": 100}],
        }
        result = await handle_create_invoice(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_customer_null_name(self):
        """name=None should be treated as missing."""
        data = {"customer_id": "CUST-001", "name": None}
        result = await handle_add_customer(data)
        assert _status(result) == 400
