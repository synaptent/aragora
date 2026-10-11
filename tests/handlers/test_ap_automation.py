"""Tests for AP automation handler (aragora/server/handlers/ap_automation.py).

Covers all routes and behavior of the AP automation handler:
- POST /api/v1/accounting/ap/invoices       - Add payable invoice
- GET  /api/v1/accounting/ap/invoices        - List payable invoices
- GET  /api/v1/accounting/ap/invoices/{id}   - Get invoice by ID
- POST /api/v1/accounting/ap/invoices/{id}/payment - Record payment
- POST /api/v1/accounting/ap/optimize        - Optimize payment timing
- POST /api/v1/accounting/ap/batch           - Create batch payment
- GET  /api/v1/accounting/ap/forecast        - Get cash flow forecast
- GET  /api/v1/accounting/ap/discounts       - Get discount opportunities
- Circuit breaker integration
- Rate limiter resets
- Validation and error paths
- Handler class registration
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.ap_automation import (
    APAutomationHandler,
    _ap_circuit_breaker,
    get_ap_automation,
    get_ap_circuit_breaker,
    get_ap_circuit_breaker_status,
    handle_add_invoice,
    handle_batch_payments,
    handle_get_discounts,
    handle_get_forecast,
    handle_get_invoice,
    handle_list_invoices,
    handle_optimize_payments,
    handle_record_payment,
)
from aragora.server.handlers.base import HandlerResult
from aragora.services.ap_automation import PaymentMethod


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
# Mock AP service objects
# ---------------------------------------------------------------------------


class MockInvoice:
    """Mock invoice object returned by the AP service."""

    def __init__(self, invoice_id="inv-001", vendor_id="v-001", amount=100.0):
        self.invoice_id = invoice_id
        self.vendor_id = vendor_id
        self.amount = amount
        self.amount_paid = Decimal("0.00")
        self.invoice_date = datetime(2026, 1, 15)

    def to_dict(self):
        return {
            "invoice_id": self.invoice_id,
            "vendor_id": self.vendor_id,
            "amount": float(self.amount),
        }


class MockSchedule:
    """Mock payment schedule from optimization."""

    def to_dict(self):
        return {
            "payments": [{"invoice_id": "inv-001", "pay_date": "2026-03-01"}],
            "total_savings": 150.0,
        }


class MockBatch:
    """Mock batch payment result."""

    def to_dict(self):
        return {
            "batch_id": "batch-001",
            "invoice_count": 2,
            "total_amount": 500.0,
        }


class MockForecast:
    """Mock forecast result."""

    def to_dict(self):
        return {
            "total_due": 10000.0,
            "periods": [{"week": 1, "amount": 3000.0}],
        }


def _make_mock_ap():
    """Create a fully-mocked AP automation service."""
    ap = AsyncMock()
    ap.add_invoice = AsyncMock(return_value=MockInvoice())
    ap.list_invoices = AsyncMock(return_value=[MockInvoice("inv-1"), MockInvoice("inv-2")])
    ap.get_invoice = AsyncMock(return_value=MockInvoice())
    ap.record_payment = AsyncMock(return_value=MockInvoice())
    ap.optimize_payment_timing = AsyncMock(return_value=MockSchedule())
    ap.batch_payments = AsyncMock(return_value=MockBatch())
    ap.forecast_cash_needs = AsyncMock(return_value=MockForecast())
    ap.get_discount_opportunities = AsyncMock(
        return_value=[
            {"invoice_id": "inv-1", "discount": 0.02, "savings": 50.0},
            {"invoice_id": "inv-2", "discount": 0.01, "savings": 25.0},
        ]
    )
    return ap


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_circuit_breaker():
    """Reset circuit breaker between tests."""
    _ap_circuit_breaker.reset()
    yield
    _ap_circuit_breaker.reset()


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Reset rate limiters between tests."""
    from aragora.server.handlers.utils.rate_limit import clear_all_limiters

    clear_all_limiters()
    yield
    clear_all_limiters()


@pytest.fixture(autouse=True)
def _reset_ap_singleton():
    """Reset the module-level AP automation singleton between tests."""
    import aragora.server.handlers.ap_automation as mod

    original = mod._ap_automation
    mod._ap_automation = None
    yield
    mod._ap_automation = original


@pytest.fixture
def mock_ap():
    """Provide a mocked AP automation service and patch get_ap_automation."""
    ap = _make_mock_ap()
    with patch("aragora.server.handlers.ap_automation.get_ap_automation", return_value=ap):
        yield ap


# ============================================================================
# Handler Class & Registration
# ============================================================================


class TestAPAutomationHandlerClass:
    """Test APAutomationHandler class initialization and route maps."""

    def test_init_with_no_context(self):
        handler = APAutomationHandler()
        assert handler.ctx == {}

    def test_init_with_context(self):
        ctx = {"key": "value"}
        handler = APAutomationHandler(ctx=ctx)
        assert handler.ctx == ctx

    def test_route_map_contains_all_static_routes(self):
        expected_routes = [
            "POST /api/v1/accounting/ap/invoices",
            "GET /api/v1/accounting/ap/invoices",
            "POST /api/v1/accounting/ap/optimize",
            "POST /api/v1/accounting/ap/batch",
            "GET /api/v1/accounting/ap/forecast",
            "GET /api/v1/accounting/ap/discounts",
        ]
        for route in expected_routes:
            assert route in APAutomationHandler._ROUTE_MAP, f"Missing route: {route}"

    def test_dynamic_routes_contain_parameterized_endpoints(self):
        assert (
            "GET /api/v1/accounting/ap/invoices/{invoice_id}" in APAutomationHandler.DYNAMIC_ROUTES
        )
        assert (
            "POST /api/v1/accounting/ap/invoices/{invoice_id}/payment"
            in APAutomationHandler.DYNAMIC_ROUTES
        )

    def test_routes_list_has_entries(self):
        assert len(APAutomationHandler.ROUTES) > 0
        assert "/api/v1/accounting/ap/invoices" in APAutomationHandler.ROUTES

    def test_route_map_points_to_correct_handlers(self):
        rm = APAutomationHandler._ROUTE_MAP
        assert rm["POST /api/v1/accounting/ap/invoices"] is handle_add_invoice
        assert rm["GET /api/v1/accounting/ap/invoices"] is handle_list_invoices
        assert rm["POST /api/v1/accounting/ap/optimize"] is handle_optimize_payments
        assert rm["POST /api/v1/accounting/ap/batch"] is handle_batch_payments
        assert rm["GET /api/v1/accounting/ap/forecast"] is handle_get_forecast
        assert rm["GET /api/v1/accounting/ap/discounts"] is handle_get_discounts

    def test_dynamic_routes_point_to_correct_handlers(self):
        dr = APAutomationHandler.DYNAMIC_ROUTES
        assert dr["GET /api/v1/accounting/ap/invoices/{invoice_id}"] is handle_get_invoice
        assert (
            dr["POST /api/v1/accounting/ap/invoices/{invoice_id}/payment"] is handle_record_payment
        )


# ============================================================================
# Circuit Breaker Utilities
# ============================================================================


class TestCircuitBreakerUtilities:
    """Test circuit breaker utility functions."""

    def test_get_ap_circuit_breaker_returns_singleton(self):
        cb = get_ap_circuit_breaker()
        assert cb is _ap_circuit_breaker

    def test_get_ap_circuit_breaker_status_returns_dict(self):
        status = get_ap_circuit_breaker_status()
        assert isinstance(status, dict)
        assert "config" in status

    def test_circuit_breaker_name(self):
        assert _ap_circuit_breaker.name == "ap_automation_handler"

    def test_circuit_breaker_failure_threshold(self):
        assert _ap_circuit_breaker.failure_threshold == 5

    def test_circuit_breaker_cooldown(self):
        assert _ap_circuit_breaker.cooldown_seconds == 30.0


# ============================================================================
# AP Singleton
# ============================================================================


class TestAPSingleton:
    """Test the thread-safe AP automation singleton."""

    def test_get_ap_automation_creates_instance(self):
        with patch("aragora.services.ap_automation.APAutomation") as mock_cls:
            mock_cls.return_value = MagicMock()
            result = get_ap_automation()
            assert result is not None
            mock_cls.assert_called_once()

    def test_get_ap_automation_returns_cached(self):
        import aragora.server.handlers.ap_automation as mod

        sentinel = object()
        mod._ap_automation = sentinel
        try:
            assert get_ap_automation() is sentinel
        finally:
            mod._ap_automation = None


# ============================================================================
# POST /api/v1/accounting/ap/invoices - Add Invoice
# ============================================================================


class TestAddInvoice:
    """Test adding a payable invoice."""

    @pytest.mark.asyncio
    async def test_add_invoice_success(self, mock_ap):
        data = {
            "vendor_id": "v-001",
            "vendor_name": "Acme Corp",
            "total_amount": 1000.50,
        }
        result = await handle_add_invoice(data)
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["message"] == "Invoice added successfully"
        assert "invoice" in body["data"]

    @pytest.mark.asyncio
    async def test_add_invoice_with_all_fields(self, mock_ap):
        data = {
            "vendor_id": "v-002",
            "vendor_name": "Widgets Inc",
            "invoice_number": "INV-2026-001",
            "invoice_date": "2026-02-01",
            "due_date": "2026-03-01",
            "total_amount": 5000.00,
            "payment_terms": "Net 60",
            "early_pay_discount": 0.02,
            "discount_deadline": "2026-02-15",
            "priority": "high",
            "preferred_payment_method": "ach",
        }
        result = await handle_add_invoice(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_add_invoice_missing_vendor_id(self, mock_ap):
        data = {"vendor_name": "Acme", "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 400
        assert "vendor_id" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_add_invoice_empty_vendor_id(self, mock_ap):
        data = {"vendor_id": "", "vendor_name": "Acme", "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_invoice_whitespace_vendor_id(self, mock_ap):
        data = {"vendor_id": "   ", "vendor_name": "Acme", "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 400
        assert "non-empty" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_add_invoice_non_string_vendor_id(self, mock_ap):
        data = {"vendor_id": 123, "vendor_name": "Acme", "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 400
        assert "non-empty string" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_add_invoice_missing_vendor_name(self, mock_ap):
        data = {"vendor_id": "v-001", "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 400
        assert "vendor_name" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_add_invoice_empty_vendor_name(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "", "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_invoice_whitespace_vendor_name(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "   ", "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_invoice_non_string_vendor_name(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": 456, "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_invoice_missing_total_amount(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "Acme"}
        result = await handle_add_invoice(data)
        assert _status(result) == 400
        assert "total_amount" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_add_invoice_zero_amount(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 0}
        result = await handle_add_invoice(data)
        assert _status(result) == 400
        assert "positive" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_add_invoice_negative_amount(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": -100}
        result = await handle_add_invoice(data)
        assert _status(result) == 400
        assert "positive" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_add_invoice_invalid_amount_string(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": "not_a_number"}
        result = await handle_add_invoice(data)
        assert _status(result) == 400
        assert "valid number" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_add_invoice_invalid_amount_none_explicit(self, mock_ap):
        # total_amount key is present but None
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": None}
        result = await handle_add_invoice(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_invoice_invalid_invoice_date(self, mock_ap):
        data = {
            "vendor_id": "v-001",
            "vendor_name": "Acme",
            "total_amount": 100,
            "invoice_date": "not-a-date",
        }
        result = await handle_add_invoice(data)
        assert _status(result) == 400
        assert "ISO format" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_add_invoice_invalid_due_date(self, mock_ap):
        data = {
            "vendor_id": "v-001",
            "vendor_name": "Acme",
            "total_amount": 100,
            "due_date": "bad-date",
        }
        result = await handle_add_invoice(data)
        assert _status(result) == 400
        assert "ISO format" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_add_invoice_invalid_discount_deadline(self, mock_ap):
        data = {
            "vendor_id": "v-001",
            "vendor_name": "Acme",
            "total_amount": 100,
            "discount_deadline": "yesterday",
        }
        result = await handle_add_invoice(data)
        assert _status(result) == 400
        assert "ISO format" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_add_invoice_circuit_breaker_open(self, mock_ap):
        with patch.object(_ap_circuit_breaker, "can_proceed", return_value=False):
            with patch.object(_ap_circuit_breaker, "cooldown_remaining", return_value=15.0):
                data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 100}
                result = await handle_add_invoice(data)
                assert _status(result) == 503
                assert "temporarily unavailable" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_add_invoice_service_value_error(self, mock_ap):
        mock_ap.add_invoice.side_effect = ValueError("bad data")
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 500
        assert "failed" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_add_invoice_service_type_error(self, mock_ap):
        mock_ap.add_invoice.side_effect = TypeError("wrong type")
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_add_invoice_service_attribute_error(self, mock_ap):
        mock_ap.add_invoice.side_effect = AttributeError("missing attr")
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_add_invoice_default_payment_terms(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 100}
        await handle_add_invoice(data)
        call_kwargs = mock_ap.add_invoice.call_args.kwargs
        assert call_kwargs["payment_terms"] == "Net 30"

    @pytest.mark.asyncio
    async def test_add_invoice_strips_vendor_id(self, mock_ap):
        data = {"vendor_id": "  v-001  ", "vendor_name": "  Acme  ", "total_amount": 100}
        await handle_add_invoice(data)
        call_kwargs = mock_ap.add_invoice.call_args.kwargs
        assert call_kwargs["vendor_id"] == "v-001"
        assert call_kwargs["vendor_name"] == "Acme"

    @pytest.mark.asyncio
    async def test_add_invoice_decimal_amount(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 99.99}
        await handle_add_invoice(data)
        call_kwargs = mock_ap.add_invoice.call_args.kwargs
        assert call_kwargs["total_amount"] == Decimal("99.99")

    @pytest.mark.asyncio
    async def test_add_invoice_circuit_open_error(self, mock_ap):
        from aragora.resilience import CircuitOpenError

        mock_ap.add_invoice.side_effect = CircuitOpenError("ap", 10.0)
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 503


# ============================================================================
# GET /api/v1/accounting/ap/invoices - List Invoices
# ============================================================================


class TestListInvoices:
    """Test listing payable invoices."""

    @pytest.mark.asyncio
    async def test_list_invoices_success(self, mock_ap):
        result = await handle_list_invoices({})
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["total"] == 2
        assert len(body["data"]["invoices"]) == 2

    @pytest.mark.asyncio
    async def test_list_invoices_with_filters(self, mock_ap):
        data = {"vendor_id": "v-001", "status": "unpaid", "priority": "high"}
        result = await handle_list_invoices(data)
        assert _status(result) == 200
        # The service takes no status or date arguments; the handler filters those locally.
        mock_ap.list_invoices.assert_called_once_with(vendor_id="v-001", priority="high")
        assert _body(result)["data"]["total"] == 2

    @pytest.mark.asyncio
    async def test_list_invoices_with_dates(self, mock_ap):
        data = {"start_date": "2026-01-01", "end_date": "2026-12-31"}
        result = await handle_list_invoices(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_list_invoices_invalid_start_date(self, mock_ap):
        data = {"start_date": "invalid"}
        result = await handle_list_invoices(data)
        assert _status(result) == 400
        assert "ISO format" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_list_invoices_invalid_end_date(self, mock_ap):
        data = {"end_date": "bad"}
        result = await handle_list_invoices(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_list_invoices_custom_limit(self, mock_ap):
        data = {"limit": 50}
        result = await handle_list_invoices(data)
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["limit"] == 50

    @pytest.mark.asyncio
    async def test_list_invoices_custom_offset(self, mock_ap):
        data = {"offset": 10}
        result = await handle_list_invoices(data)
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["offset"] == 10

    @pytest.mark.asyncio
    async def test_list_invoices_limit_zero(self, mock_ap):
        data = {"limit": 0}
        result = await handle_list_invoices(data)
        assert _status(result) == 400
        assert "1-1000" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_list_invoices_limit_exceeds_max(self, mock_ap):
        data = {"limit": 1001}
        result = await handle_list_invoices(data)
        assert _status(result) == 400
        assert "1-1000" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_list_invoices_negative_offset(self, mock_ap):
        data = {"offset": -1}
        result = await handle_list_invoices(data)
        assert _status(result) == 400
        assert "non-negative" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_list_invoices_invalid_limit(self, mock_ap):
        data = {"limit": "abc"}
        result = await handle_list_invoices(data)
        assert _status(result) == 400
        assert "integers" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_list_invoices_invalid_offset(self, mock_ap):
        data = {"offset": "xyz"}
        result = await handle_list_invoices(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_list_invoices_pagination_applied(self, mock_ap):
        # Return 5 invoices, but request limit=2, offset=1
        mock_ap.list_invoices.return_value = [MockInvoice(f"inv-{i}") for i in range(5)]
        data = {"limit": 2, "offset": 1}
        result = await handle_list_invoices(data)
        body = _body(result)
        assert body["data"]["total"] == 5
        assert len(body["data"]["invoices"]) == 2
        assert body["data"]["offset"] == 1

    @pytest.mark.asyncio
    async def test_list_invoices_circuit_breaker_open(self, mock_ap):
        with patch.object(_ap_circuit_breaker, "can_proceed", return_value=False):
            with patch.object(_ap_circuit_breaker, "cooldown_remaining", return_value=5.0):
                result = await handle_list_invoices({})
                assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_list_invoices_service_error(self, mock_ap):
        mock_ap.list_invoices.side_effect = ValueError("service error")
        result = await handle_list_invoices({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_list_invoices_boundary_limit_1(self, mock_ap):
        data = {"limit": 1}
        result = await handle_list_invoices(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_list_invoices_boundary_limit_1000(self, mock_ap):
        data = {"limit": 1000}
        result = await handle_list_invoices(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_list_invoices_circuit_open_error(self, mock_ap):
        from aragora.resilience import CircuitOpenError

        mock_ap.list_invoices.side_effect = CircuitOpenError("ap", 10.0)
        result = await handle_list_invoices({})
        assert _status(result) == 503


# ============================================================================
# GET /api/v1/accounting/ap/invoices/{id} - Get Invoice
# ============================================================================


class TestGetInvoice:
    """Test getting a single invoice by ID."""

    @pytest.mark.asyncio
    async def test_get_invoice_success(self, mock_ap):
        result = await handle_get_invoice({}, invoice_id="inv-001")
        assert _status(result) == 200
        body = _body(result)
        assert "invoice" in body["data"]

    @pytest.mark.asyncio
    async def test_get_invoice_not_found(self, mock_ap):
        mock_ap.get_invoice.return_value = None
        result = await handle_get_invoice({}, invoice_id="nonexistent")
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_get_invoice_empty_id(self, mock_ap):
        result = await handle_get_invoice({}, invoice_id="")
        assert _status(result) == 400
        assert "required" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_get_invoice_whitespace_id(self, mock_ap):
        result = await handle_get_invoice({}, invoice_id="   ")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_get_invoice_circuit_breaker_open(self, mock_ap):
        with patch.object(_ap_circuit_breaker, "can_proceed", return_value=False):
            with patch.object(_ap_circuit_breaker, "cooldown_remaining", return_value=20.0):
                result = await handle_get_invoice({}, invoice_id="inv-001")
                assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_get_invoice_service_error(self, mock_ap):
        mock_ap.get_invoice.side_effect = KeyError("missing")
        result = await handle_get_invoice({}, invoice_id="inv-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_get_invoice_circuit_open_error(self, mock_ap):
        from aragora.resilience import CircuitOpenError

        mock_ap.get_invoice.side_effect = CircuitOpenError("ap", 5.0)
        result = await handle_get_invoice({}, invoice_id="inv-001")
        assert _status(result) == 503


# ============================================================================
# POST /api/v1/accounting/ap/invoices/{id}/payment - Record Payment
# ============================================================================


class TestRecordPayment:
    """Test recording a payment on an invoice."""

    @pytest.mark.asyncio
    async def test_record_payment_success(self, mock_ap):
        data = {"amount": 500.0}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 200
        body = _body(result)
        assert "recorded successfully" in body["data"]["message"]

    @pytest.mark.asyncio
    async def test_record_payment_with_all_fields(self, mock_ap):
        data = {
            "amount": 250.0,
            "payment_date": "2026-02-15",
            "payment_method": "ach",
            "reference": "REF-001",
        }
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_record_payment_empty_invoice_id(self, mock_ap):
        data = {"amount": 100}
        result = await handle_record_payment(data, invoice_id="")
        assert _status(result) == 400
        assert "required" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_record_payment_whitespace_invoice_id(self, mock_ap):
        data = {"amount": 100}
        result = await handle_record_payment(data, invoice_id="   ")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_record_payment_missing_amount(self, mock_ap):
        data = {}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 400
        assert "amount" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_record_payment_zero_amount(self, mock_ap):
        data = {"amount": 0}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 400
        assert "positive" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_record_payment_negative_amount(self, mock_ap):
        data = {"amount": -50}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 400
        assert "positive" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_record_payment_invalid_amount(self, mock_ap):
        data = {"amount": "abc"}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 400
        assert "valid number" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_record_payment_invalid_payment_date(self, mock_ap):
        data = {"amount": 100, "payment_date": "not-a-date"}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 400
        assert "ISO format" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_record_payment_invoice_not_found(self, mock_ap):
        mock_ap.get_invoice.return_value = None
        data = {"amount": 100}
        result = await handle_record_payment(data, invoice_id="nonexistent")
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_record_payment_circuit_breaker_open(self, mock_ap):
        with patch.object(_ap_circuit_breaker, "can_proceed", return_value=False):
            with patch.object(_ap_circuit_breaker, "cooldown_remaining", return_value=10.0):
                data = {"amount": 100}
                result = await handle_record_payment(data, invoice_id="inv-001")
                assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_record_payment_service_error(self, mock_ap):
        mock_ap.record_payment.side_effect = ValueError("payment error")
        data = {"amount": 100}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_record_payment_decimal_amount(self, mock_ap):
        data = {"amount": 199.99}
        await handle_record_payment(data, invoice_id="inv-001")
        call_kwargs = mock_ap.record_payment.call_args.kwargs
        assert call_kwargs["amount"] == Decimal("199.99")

    @pytest.mark.asyncio
    async def test_record_payment_circuit_open_error(self, mock_ap):
        from aragora.resilience import CircuitOpenError

        mock_ap.get_invoice.side_effect = CircuitOpenError("ap", 5.0)
        data = {"amount": 100}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 503


# ============================================================================
# POST /api/v1/accounting/ap/optimize - Optimize Payments
# ============================================================================


class TestOptimizePayments:
    """Test payment optimization."""

    @pytest.mark.asyncio
    async def test_optimize_success(self, mock_ap):
        data = {}
        result = await handle_optimize_payments(data)
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["message"] == "Payment schedule optimized"
        assert "schedule" in body["data"]
        assert body["data"]["total_invoices"] == 2

    @pytest.mark.asyncio
    async def test_optimize_with_invoice_ids(self, mock_ap):
        data = {"invoice_ids": ["inv-1", "inv-2"]}
        result = await handle_optimize_payments(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_optimize_with_available_cash(self, mock_ap):
        data = {"available_cash": 5000.0}
        result = await handle_optimize_payments(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_optimize_negative_cash(self, mock_ap):
        data = {"available_cash": -100}
        result = await handle_optimize_payments(data)
        assert _status(result) == 400
        assert "non-negative" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_optimize_invalid_cash(self, mock_ap):
        data = {"available_cash": "lots"}
        result = await handle_optimize_payments(data)
        assert _status(result) == 400
        assert "valid number" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_optimize_zero_cash(self, mock_ap):
        data = {"available_cash": 0}
        result = await handle_optimize_payments(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_optimize_no_invoices_found(self, mock_ap):
        mock_ap.list_invoices.return_value = []
        data = {}
        result = await handle_optimize_payments(data)
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["schedule"] == []
        assert "No invoices" in body["data"]["message"]

    @pytest.mark.asyncio
    async def test_optimize_with_invoice_ids_some_missing(self, mock_ap):
        # get_invoice returns None for missing invoices
        mock_ap.get_invoice.side_effect = [MockInvoice("inv-1"), None]
        data = {"invoice_ids": ["inv-1", "inv-missing"]}
        result = await handle_optimize_payments(data)
        # It should still work with the found invoice
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_optimize_with_invoice_ids_all_missing(self, mock_ap):
        mock_ap.get_invoice.return_value = None
        data = {"invoice_ids": ["inv-missing"]}
        result = await handle_optimize_payments(data)
        assert _status(result) == 200
        body = _body(result)
        assert "No invoices" in body["data"]["message"]

    @pytest.mark.asyncio
    async def test_optimize_passes_only_service_arguments(self, mock_ap):
        # APAutomation.optimize_payment_timing takes no prioritize_discounts argument.
        await handle_optimize_payments({"prioritize_discounts": False})
        call_kwargs = mock_ap.optimize_payment_timing.call_args.kwargs
        assert set(call_kwargs) == {"invoices", "available_cash"}

    @pytest.mark.asyncio
    async def test_optimize_circuit_breaker_open(self, mock_ap):
        with patch.object(_ap_circuit_breaker, "can_proceed", return_value=False):
            with patch.object(_ap_circuit_breaker, "cooldown_remaining", return_value=10.0):
                result = await handle_optimize_payments({})
                assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_optimize_service_error(self, mock_ap):
        mock_ap.optimize_payment_timing.side_effect = AttributeError("missing")
        result = await handle_optimize_payments({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_optimize_circuit_open_error(self, mock_ap):
        from aragora.resilience import CircuitOpenError

        mock_ap.list_invoices.side_effect = CircuitOpenError("ap", 5.0)
        result = await handle_optimize_payments({})
        assert _status(result) == 503


# ============================================================================
# POST /api/v1/accounting/ap/batch - Batch Payments
# ============================================================================


class TestBatchPayments:
    """Test batch payment creation."""

    @pytest.mark.asyncio
    async def test_batch_success(self, mock_ap):
        data = {"invoice_ids": ["inv-1", "inv-2"]}
        result = await handle_batch_payments(data)
        assert _status(result) == 200
        body = _body(result)
        assert "batch" in body["data"]
        assert "2 invoices" in body["data"]["message"]

    @pytest.mark.asyncio
    async def test_batch_with_payment_date(self, mock_ap):
        data = {"invoice_ids": ["inv-1"], "payment_date": "2026-03-01"}
        result = await handle_batch_payments(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_batch_with_payment_method(self, mock_ap):
        data = {"invoice_ids": ["inv-1"], "payment_method": "wire"}
        result = await handle_batch_payments(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_batch_missing_invoice_ids(self, mock_ap):
        data = {}
        result = await handle_batch_payments(data)
        assert _status(result) == 400
        assert "invoice_ids" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_batch_empty_invoice_ids_list(self, mock_ap):
        data = {"invoice_ids": []}
        result = await handle_batch_payments(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_invoice_ids_not_a_list(self, mock_ap):
        data = {"invoice_ids": "inv-1"}
        result = await handle_batch_payments(data)
        assert _status(result) == 400
        assert "non-empty list" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_batch_invalid_payment_date(self, mock_ap):
        data = {"invoice_ids": ["inv-1"], "payment_date": "bad-date"}
        result = await handle_batch_payments(data)
        assert _status(result) == 400
        assert "ISO format" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_batch_invoice_not_found(self, mock_ap):
        mock_ap.get_invoice.return_value = None
        data = {"invoice_ids": ["inv-missing"]}
        result = await handle_batch_payments(data)
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_batch_partial_invoices_not_found(self, mock_ap):
        # First invoice found, second not
        mock_ap.get_invoice.side_effect = [MockInvoice("inv-1"), None]
        data = {"invoice_ids": ["inv-1", "inv-missing"]}
        result = await handle_batch_payments(data)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_batch_circuit_breaker_open(self, mock_ap):
        with patch.object(_ap_circuit_breaker, "can_proceed", return_value=False):
            with patch.object(_ap_circuit_breaker, "cooldown_remaining", return_value=10.0):
                data = {"invoice_ids": ["inv-1"]}
                result = await handle_batch_payments(data)
                assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_batch_service_error(self, mock_ap):
        mock_ap.batch_payments.side_effect = TypeError("bad input")
        data = {"invoice_ids": ["inv-1"]}
        result = await handle_batch_payments(data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_batch_circuit_open_error(self, mock_ap):
        from aragora.resilience import CircuitOpenError

        mock_ap.get_invoice.side_effect = CircuitOpenError("ap", 5.0)
        data = {"invoice_ids": ["inv-1"]}
        result = await handle_batch_payments(data)
        assert _status(result) == 503


# ============================================================================
# GET /api/v1/accounting/ap/forecast - Cash Flow Forecast
# ============================================================================


class TestGetForecast:
    """Test cash flow forecast endpoint."""

    @pytest.mark.asyncio
    async def test_forecast_success(self, mock_ap):
        result = await handle_get_forecast({})
        assert _status(result) == 200
        body = _body(result)
        assert "forecast" in body["data"]
        assert body["data"]["days_ahead"] == 30
        assert "generated_at" in body["data"]

    @pytest.mark.asyncio
    async def test_forecast_custom_days(self, mock_ap):
        data = {"days_ahead": 90}
        result = await handle_get_forecast(data)
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["days_ahead"] == 90

    @pytest.mark.asyncio
    async def test_forecast_days_zero(self, mock_ap):
        data = {"days_ahead": 0}
        result = await handle_get_forecast(data)
        assert _status(result) == 400
        assert "1-365" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_forecast_days_negative(self, mock_ap):
        data = {"days_ahead": -5}
        result = await handle_get_forecast(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_forecast_days_too_large(self, mock_ap):
        data = {"days_ahead": 366}
        result = await handle_get_forecast(data)
        assert _status(result) == 400
        assert "1-365" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_forecast_days_invalid_string(self, mock_ap):
        data = {"days_ahead": "abc"}
        result = await handle_get_forecast(data)
        assert _status(result) == 400
        assert "integer" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_forecast_boundary_1_day(self, mock_ap):
        data = {"days_ahead": 1}
        result = await handle_get_forecast(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_forecast_boundary_365_days(self, mock_ap):
        data = {"days_ahead": 365}
        result = await handle_get_forecast(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_forecast_circuit_breaker_open(self, mock_ap):
        with patch.object(_ap_circuit_breaker, "can_proceed", return_value=False):
            with patch.object(_ap_circuit_breaker, "cooldown_remaining", return_value=10.0):
                result = await handle_get_forecast({})
                assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_forecast_service_error(self, mock_ap):
        mock_ap.forecast_cash_needs.side_effect = ValueError("forecast error")
        result = await handle_get_forecast({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_forecast_circuit_open_error(self, mock_ap):
        from aragora.resilience import CircuitOpenError

        mock_ap.forecast_cash_needs.side_effect = CircuitOpenError("ap", 5.0)
        result = await handle_get_forecast({})
        assert _status(result) == 503


# ============================================================================
# GET /api/v1/accounting/ap/discounts - Discount Opportunities
# ============================================================================


class TestGetDiscounts:
    """Test discount opportunities endpoint."""

    @pytest.mark.asyncio
    async def test_discounts_success(self, mock_ap):
        result = await handle_get_discounts({})
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["total"] == 2
        assert len(body["data"]["opportunities"]) == 2

    @pytest.mark.asyncio
    async def test_discounts_empty(self, mock_ap):
        mock_ap.get_discount_opportunities.return_value = []
        result = await handle_get_discounts({})
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["total"] == 0
        assert body["data"]["opportunities"] == []

    @pytest.mark.asyncio
    async def test_discounts_circuit_breaker_open(self, mock_ap):
        with patch.object(_ap_circuit_breaker, "can_proceed", return_value=False):
            with patch.object(_ap_circuit_breaker, "cooldown_remaining", return_value=10.0):
                result = await handle_get_discounts({})
                assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_discounts_service_error(self, mock_ap):
        mock_ap.get_discount_opportunities.side_effect = KeyError("err")
        result = await handle_get_discounts({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_discounts_circuit_open_error(self, mock_ap):
        from aragora.resilience import CircuitOpenError

        mock_ap.get_discount_opportunities.side_effect = CircuitOpenError("ap", 5.0)
        result = await handle_get_discounts({})
        assert _status(result) == 503


# ============================================================================
# Circuit Breaker Integration Across Handlers
# ============================================================================


class TestCircuitBreakerIntegration:
    """Test circuit breaker patterns across all handlers."""

    @pytest.mark.asyncio
    async def test_cb_cooldown_message_includes_time(self, mock_ap):
        with patch.object(_ap_circuit_breaker, "can_proceed", return_value=False):
            with patch.object(_ap_circuit_breaker, "cooldown_remaining", return_value=25.3):
                result = await handle_add_invoice(
                    {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 100}
                )
                assert "25.3" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_cb_status_dict_has_expected_fields(self):
        status = get_ap_circuit_breaker_status()
        assert "config" in status
        assert "single_mode" in status

    @pytest.mark.asyncio
    async def test_all_handlers_return_503_on_cb_open(self, mock_ap):
        """Verify all handlers correctly check circuit breaker."""
        with patch.object(_ap_circuit_breaker, "can_proceed", return_value=False):
            with patch.object(_ap_circuit_breaker, "cooldown_remaining", return_value=10.0):
                # Add invoice
                r1 = await handle_add_invoice(
                    {"vendor_id": "v", "vendor_name": "n", "total_amount": 1}
                )
                assert _status(r1) == 503

                # List invoices
                r2 = await handle_list_invoices({})
                assert _status(r2) == 503

                # Get invoice
                r3 = await handle_get_invoice({}, invoice_id="inv-1")
                assert _status(r3) == 503

                # Record payment
                r4 = await handle_record_payment({"amount": 100}, invoice_id="inv-1")
                assert _status(r4) == 503

                # Optimize payments
                r5 = await handle_optimize_payments({})
                assert _status(r5) == 503

                # Batch payments
                r6 = await handle_batch_payments({"invoice_ids": ["inv-1"]})
                assert _status(r6) == 503

                # Get forecast
                r7 = await handle_get_forecast({})
                assert _status(r7) == 503

                # Get discounts
                r8 = await handle_get_discounts({})
                assert _status(r8) == 503


# ============================================================================
# Edge Cases and Additional Validation
# ============================================================================


class TestEdgeCases:
    """Test edge cases and unusual inputs."""

    @pytest.mark.asyncio
    async def test_add_invoice_amount_inf(self, mock_ap):
        # Decimal("Infinity") > 0 is True, so this passes validation
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": "Infinity"}
        result = await handle_add_invoice(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_add_invoice_amount_nan(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": "NaN"}
        result = await handle_add_invoice(data)
        # Decimal("NaN") > 0 raises InvalidOperation, caught as ArithmeticError
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_invoice_amount_as_int(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_add_invoice_amount_as_string_number(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": "100.50"}
        result = await handle_add_invoice(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_record_payment_amount_inf(self, mock_ap):
        # Decimal("Infinity") > 0 is True, passes validation
        data = {"amount": "Infinity"}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_optimize_cash_inf(self, mock_ap):
        # Decimal("Infinity") >= 0 is True, passes validation
        data = {"available_cash": "Infinity"}
        result = await handle_optimize_payments(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_list_invoices_offset_zero(self, mock_ap):
        data = {"offset": 0}
        result = await handle_list_invoices(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_batch_single_invoice(self, mock_ap):
        data = {"invoice_ids": ["inv-1"]}
        result = await handle_batch_payments(data)
        assert _status(result) == 200
        body = _body(result)
        assert "1 invoices" in body["data"]["message"]

    @pytest.mark.asyncio
    async def test_empty_data_dict(self, mock_ap):
        """Several handlers should work fine with empty data."""
        # Forecast defaults days_ahead to 30
        r = await handle_get_forecast({})
        assert _status(r) == 200

    @pytest.mark.asyncio
    async def test_add_invoice_with_valid_dates(self, mock_ap):
        data = {
            "vendor_id": "v-001",
            "vendor_name": "Acme",
            "total_amount": 100,
            "invoice_date": "2026-02-01T10:00:00",
            "due_date": "2026-03-01T10:00:00",
            "discount_deadline": "2026-02-15T10:00:00",
        }
        result = await handle_add_invoice(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_record_payment_with_valid_date(self, mock_ap):
        data = {"amount": 100, "payment_date": "2026-02-20T14:30:00"}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_batch_with_valid_date(self, mock_ap):
        data = {"invoice_ids": ["inv-1"], "payment_date": "2026-03-01T09:00:00"}
        result = await handle_batch_payments(data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_add_invoice_amount_list_type(self, mock_ap):
        """Lists cannot be converted to Decimal."""
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": [1, 2, 3]}
        result = await handle_add_invoice(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_invoice_amount_dict_type(self, mock_ap):
        """Dicts cannot be converted to Decimal."""
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": {"val": 1}}
        result = await handle_add_invoice(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_record_payment_amount_none_explicit(self, mock_ap):
        """amount=None should fail validation."""
        data = {"amount": None}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_record_payment_amount_nan(self, mock_ap):
        """Decimal('NaN') comparison raises ArithmeticError."""
        data = {"amount": "NaN"}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_optimize_available_cash_nan(self, mock_ap):
        """NaN for available_cash should fail."""
        data = {"available_cash": "NaN"}
        result = await handle_optimize_payments(data)
        # Decimal("NaN") >= 0 raises ArithmeticError
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_forecast_days_float_string(self, mock_ap):
        """Float string should fail int() conversion."""
        data = {"days_ahead": "3.5"}
        result = await handle_get_forecast(data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_list_invoices_limit_float_string(self, mock_ap):
        """Float string should fail int() conversion."""
        data = {"limit": "3.5"}
        result = await handle_list_invoices(data)
        assert _status(result) == 400


# ============================================================================
# Parameter Pass-Through Verification
# ============================================================================


class TestParameterPassThrough:
    """Verify that handler functions correctly pass parameters to the AP service."""

    @pytest.mark.asyncio
    async def test_add_invoice_passes_optional_fields(self, mock_ap):
        data = {
            "vendor_id": "v-001",
            "vendor_name": "Acme",
            "total_amount": 500,
            "invoice_number": "INV-999",
            "payment_terms": "Net 60",
            "early_pay_discount": 0.05,
            "priority": "critical",
            "preferred_payment_method": "wire",
        }
        await handle_add_invoice(data)
        kw = mock_ap.add_invoice.call_args.kwargs
        assert kw["invoice_number"] == "INV-999"
        assert kw["payment_terms"] == "Net 60"
        assert kw["early_pay_discount"] == 0.05
        assert kw["priority"] == "critical"
        assert "preferred_payment_method" not in kw  # APAutomation.add_invoice has no such argument

    @pytest.mark.asyncio
    async def test_add_invoice_default_early_discount(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 100}
        await handle_add_invoice(data)
        kw = mock_ap.add_invoice.call_args.kwargs
        assert kw["early_pay_discount"] == 0

    @pytest.mark.asyncio
    async def test_add_invoice_default_invoice_number(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 100}
        await handle_add_invoice(data)
        kw = mock_ap.add_invoice.call_args.kwargs
        assert kw["invoice_number"] == ""

    @pytest.mark.asyncio
    async def test_record_payment_passes_only_service_arguments(self, mock_ap):
        # APAutomation.record_payment takes no payment_method or reference argument.
        data = {
            "amount": 100,
            "payment_method": "check",
            "reference": "REF-123",
        }
        await handle_record_payment(data, invoice_id="inv-001")
        kw = mock_ap.record_payment.call_args.kwargs
        assert set(kw) == {"invoice_id", "amount", "payment_date"}

    @pytest.mark.asyncio
    async def test_record_payment_none_optional_fields(self, mock_ap):
        data = {"amount": 100}
        await handle_record_payment(data, invoice_id="inv-001")
        kw = mock_ap.record_payment.call_args.kwargs
        assert kw["payment_date"] is None

    @pytest.mark.asyncio
    async def test_list_invoices_passes_all_filters(self, mock_ap):
        data = {
            "vendor_id": "v-x",
            "status": "partial",
            "priority": "low",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
        }
        result = await handle_list_invoices(data)
        assert _status(result) == 200
        kw = mock_ap.list_invoices.call_args.kwargs
        assert kw == {"vendor_id": "v-x", "priority": "low"}
        # status and dates are applied by the handler, not the service.
        assert _body(result)["data"]["total"] == 0

    @pytest.mark.asyncio
    async def test_optimize_passes_cash_decimal(self, mock_ap):
        data = {"available_cash": 1234.56}
        await handle_optimize_payments(data)
        kw = mock_ap.optimize_payment_timing.call_args.kwargs
        assert kw["available_cash"] == Decimal("1234.56")

    @pytest.mark.asyncio
    async def test_optimize_no_cash_passes_none(self, mock_ap):
        data = {}
        await handle_optimize_payments(data)
        kw = mock_ap.optimize_payment_timing.call_args.kwargs
        assert kw["available_cash"] is None

    @pytest.mark.asyncio
    async def test_batch_passes_payment_method(self, mock_ap):
        data = {"invoice_ids": ["inv-1"], "payment_method": "credit_card"}
        await handle_batch_payments(data)
        kw = mock_ap.batch_payments.call_args.kwargs
        assert kw["payment_method"] == "credit_card"

    @pytest.mark.asyncio
    async def test_batch_no_payment_method_defaults_to_ach(self, mock_ap):
        data = {"invoice_ids": ["inv-1"]}
        await handle_batch_payments(data)
        kw = mock_ap.batch_payments.call_args.kwargs
        assert kw["payment_method"] is PaymentMethod.ACH

    @pytest.mark.asyncio
    async def test_forecast_passes_days_ahead(self, mock_ap):
        data = {"days_ahead": 60}
        await handle_get_forecast(data)
        kw = mock_ap.forecast_cash_needs.call_args.kwargs
        assert kw["days_ahead"] == 60

    @pytest.mark.asyncio
    async def test_optimize_gets_invoices_by_id(self, mock_ap):
        """When invoice_ids is provided, get_invoice is called per ID."""
        data = {"invoice_ids": ["inv-a", "inv-b"]}
        await handle_optimize_payments(data)
        assert mock_ap.get_invoice.call_count == 2

    @pytest.mark.asyncio
    async def test_optimize_fetches_all_unpaid_when_no_ids(self, mock_ap):
        """When no invoice_ids, all outstanding invoices are listed."""
        data = {}
        await handle_optimize_payments(data)
        mock_ap.list_invoices.assert_called_once_with()


# ============================================================================
# RBAC Permission Enforcement
# ============================================================================


class TestRBACPermissions:
    """Test RBAC permission decorators on handler functions.

    These tests verify the @require_permission decorators are wired correctly.
    With auto-auth bypassed, calling the handlers without an HTTP handler
    argument triggers the 'no handler' code path which returns 401 when
    the test override is not set.
    """

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_add_invoice_requires_finance_write(self):
        """handle_add_invoice has @require_permission('finance:write')."""
        # Without the auto-auth fixture, the decorator checks for a handler
        # argument. When none is found AND no test override set, it returns 401.
        from aragora.server.handlers.utils import decorators as handler_decorators

        original = handler_decorators._test_user_context_override
        handler_decorators._test_user_context_override = None
        try:
            data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 100}
            result = await handle_add_invoice(data)
            assert _status(result) == 401
        finally:
            handler_decorators._test_user_context_override = original

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_list_invoices_requires_ap_read(self):
        """handle_list_invoices has @require_permission('ap:read')."""
        from aragora.server.handlers.utils import decorators as handler_decorators

        original = handler_decorators._test_user_context_override
        handler_decorators._test_user_context_override = None
        try:
            result = await handle_list_invoices({})
            assert _status(result) == 401
        finally:
            handler_decorators._test_user_context_override = original

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_get_invoice_requires_ap_read(self):
        """handle_get_invoice has @require_permission('ap:read')."""
        from aragora.server.handlers.utils import decorators as handler_decorators

        original = handler_decorators._test_user_context_override
        handler_decorators._test_user_context_override = None
        try:
            result = await handle_get_invoice({}, invoice_id="inv-001")
            assert _status(result) == 401
        finally:
            handler_decorators._test_user_context_override = original

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_record_payment_requires_finance_write(self):
        """handle_record_payment has @require_permission('finance:write')."""
        from aragora.server.handlers.utils import decorators as handler_decorators

        original = handler_decorators._test_user_context_override
        handler_decorators._test_user_context_override = None
        try:
            result = await handle_record_payment({"amount": 100}, invoice_id="inv-001")
            assert _status(result) == 401
        finally:
            handler_decorators._test_user_context_override = original

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_optimize_requires_finance_approve(self):
        """handle_optimize_payments has @require_permission('finance:approve')."""
        from aragora.server.handlers.utils import decorators as handler_decorators

        original = handler_decorators._test_user_context_override
        handler_decorators._test_user_context_override = None
        try:
            result = await handle_optimize_payments({})
            assert _status(result) == 401
        finally:
            handler_decorators._test_user_context_override = original

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_batch_requires_finance_approve(self):
        """handle_batch_payments has @require_permission('finance:approve')."""
        from aragora.server.handlers.utils import decorators as handler_decorators

        original = handler_decorators._test_user_context_override
        handler_decorators._test_user_context_override = None
        try:
            result = await handle_batch_payments({"invoice_ids": ["inv-1"]})
            assert _status(result) == 401
        finally:
            handler_decorators._test_user_context_override = original

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_forecast_requires_ap_read(self):
        """handle_get_forecast has @require_permission('ap:read')."""
        from aragora.server.handlers.utils import decorators as handler_decorators

        original = handler_decorators._test_user_context_override
        handler_decorators._test_user_context_override = None
        try:
            result = await handle_get_forecast({})
            assert _status(result) == 401
        finally:
            handler_decorators._test_user_context_override = original

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_discounts_requires_ap_read(self):
        """handle_get_discounts has @require_permission('ap:read')."""
        from aragora.server.handlers.utils import decorators as handler_decorators

        original = handler_decorators._test_user_context_override
        handler_decorators._test_user_context_override = None
        try:
            result = await handle_get_discounts({})
            assert _status(result) == 401
        finally:
            handler_decorators._test_user_context_override = original


# ============================================================================
# Singleton Thread Safety
# ============================================================================


class TestSingletonThreadSafety:
    """Test the AP automation singleton in concurrent scenarios."""

    def test_singleton_reset_works(self):
        """Verify _reset_ap_singleton fixture properly resets state."""
        import aragora.server.handlers.ap_automation as mod

        assert mod._ap_automation is None

    def test_singleton_lock_is_threading_lock(self):
        """Verify the lock is a proper threading.Lock."""
        import aragora.server.handlers.ap_automation as mod

        assert isinstance(mod._ap_automation_lock, type(threading.Lock()))

    def test_get_ap_automation_double_check_locking(self):
        """Verify the double-check locking pattern: fast path returns cached."""
        import aragora.server.handlers.ap_automation as mod

        sentinel = MagicMock()
        mod._ap_automation = sentinel
        try:
            # Fast path: should return immediately without lock
            result = get_ap_automation()
            assert result is sentinel
        finally:
            mod._ap_automation = None


# ============================================================================
# Response Format Verification
# ============================================================================


class TestResponseFormat:
    """Verify the structure of success and error responses."""

    @pytest.mark.asyncio
    async def test_success_response_has_data_key(self, mock_ap):
        result = await handle_get_discounts({})
        body = _body(result)
        assert "data" in body
        assert body.get("success") is True

    @pytest.mark.asyncio
    async def test_error_response_has_error_key(self, mock_ap):
        result = await handle_add_invoice({})
        body = _body(result)
        assert "error" in body

    @pytest.mark.asyncio
    async def test_add_invoice_response_shape(self, mock_ap):
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 100}
        result = await handle_add_invoice(data)
        body = _body(result)
        assert "data" in body
        assert "invoice" in body["data"]
        assert "message" in body["data"]

    @pytest.mark.asyncio
    async def test_list_invoices_response_shape(self, mock_ap):
        result = await handle_list_invoices({})
        body = _body(result)["data"]
        assert "invoices" in body
        assert "total" in body
        assert "limit" in body
        assert "offset" in body

    @pytest.mark.asyncio
    async def test_get_invoice_response_shape(self, mock_ap):
        result = await handle_get_invoice({}, invoice_id="inv-001")
        body = _body(result)["data"]
        assert "invoice" in body

    @pytest.mark.asyncio
    async def test_record_payment_response_shape(self, mock_ap):
        result = await handle_record_payment({"amount": 50}, invoice_id="inv-001")
        body = _body(result)["data"]
        assert "invoice" in body
        assert "message" in body

    @pytest.mark.asyncio
    async def test_optimize_response_shape(self, mock_ap):
        result = await handle_optimize_payments({})
        body = _body(result)["data"]
        assert "schedule" in body
        assert "total_invoices" in body
        assert "message" in body

    @pytest.mark.asyncio
    async def test_batch_response_shape(self, mock_ap):
        data = {"invoice_ids": ["inv-1"]}
        result = await handle_batch_payments(data)
        body = _body(result)["data"]
        assert "batch" in body
        assert "message" in body

    @pytest.mark.asyncio
    async def test_forecast_response_shape(self, mock_ap):
        result = await handle_get_forecast({})
        body = _body(result)["data"]
        assert "forecast" in body
        assert "days_ahead" in body
        assert "generated_at" in body

    @pytest.mark.asyncio
    async def test_discounts_response_shape(self, mock_ap):
        result = await handle_get_discounts({})
        body = _body(result)["data"]
        assert "opportunities" in body
        assert "total" in body


# ============================================================================
# Additional Service Error Handling
# ============================================================================


class TestServiceErrorHandling:
    """Test all exception types caught by handlers."""

    @pytest.mark.asyncio
    async def test_add_invoice_key_error(self, mock_ap):
        mock_ap.add_invoice.side_effect = KeyError("missing key")
        data = {"vendor_id": "v-001", "vendor_name": "Acme", "total_amount": 100}
        result = await handle_add_invoice(data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_list_invoices_attribute_error(self, mock_ap):
        mock_ap.list_invoices.side_effect = AttributeError("bad attr")
        result = await handle_list_invoices({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_list_invoices_type_error(self, mock_ap):
        mock_ap.list_invoices.side_effect = TypeError("bad type")
        result = await handle_list_invoices({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_get_invoice_value_error(self, mock_ap):
        mock_ap.get_invoice.side_effect = ValueError("bad value")
        result = await handle_get_invoice({}, invoice_id="inv-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_get_invoice_type_error(self, mock_ap):
        mock_ap.get_invoice.side_effect = TypeError("bad type")
        result = await handle_get_invoice({}, invoice_id="inv-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_get_invoice_attribute_error(self, mock_ap):
        mock_ap.get_invoice.side_effect = AttributeError("bad attr")
        result = await handle_get_invoice({}, invoice_id="inv-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_record_payment_key_error(self, mock_ap):
        mock_ap.record_payment.side_effect = KeyError("missing")
        data = {"amount": 100}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_record_payment_type_error(self, mock_ap):
        mock_ap.record_payment.side_effect = TypeError("wrong type")
        data = {"amount": 100}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_record_payment_attribute_error(self, mock_ap):
        mock_ap.record_payment.side_effect = AttributeError("bad attr")
        data = {"amount": 100}
        result = await handle_record_payment(data, invoice_id="inv-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_optimize_value_error(self, mock_ap):
        mock_ap.optimize_payment_timing.side_effect = ValueError("bad")
        result = await handle_optimize_payments({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_optimize_type_error(self, mock_ap):
        mock_ap.optimize_payment_timing.side_effect = TypeError("bad")
        result = await handle_optimize_payments({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_optimize_key_error(self, mock_ap):
        mock_ap.optimize_payment_timing.side_effect = KeyError("bad")
        result = await handle_optimize_payments({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_batch_key_error(self, mock_ap):
        mock_ap.batch_payments.side_effect = KeyError("missing")
        data = {"invoice_ids": ["inv-1"]}
        result = await handle_batch_payments(data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_batch_value_error(self, mock_ap):
        mock_ap.batch_payments.side_effect = ValueError("bad")
        data = {"invoice_ids": ["inv-1"]}
        result = await handle_batch_payments(data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_batch_attribute_error(self, mock_ap):
        mock_ap.batch_payments.side_effect = AttributeError("bad")
        data = {"invoice_ids": ["inv-1"]}
        result = await handle_batch_payments(data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_forecast_type_error(self, mock_ap):
        mock_ap.forecast_cash_needs.side_effect = TypeError("bad")
        result = await handle_get_forecast({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_forecast_key_error(self, mock_ap):
        mock_ap.forecast_cash_needs.side_effect = KeyError("bad")
        result = await handle_get_forecast({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_forecast_attribute_error(self, mock_ap):
        mock_ap.forecast_cash_needs.side_effect = AttributeError("bad")
        result = await handle_get_forecast({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_discounts_value_error(self, mock_ap):
        mock_ap.get_discount_opportunities.side_effect = ValueError("bad")
        result = await handle_get_discounts({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_discounts_type_error(self, mock_ap):
        mock_ap.get_discount_opportunities.side_effect = TypeError("bad")
        result = await handle_get_discounts({})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_discounts_attribute_error(self, mock_ap):
        mock_ap.get_discount_opportunities.side_effect = AttributeError("bad")
        result = await handle_get_discounts({})
        assert _status(result) == 500
