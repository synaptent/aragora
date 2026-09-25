"""
HTTP API Handlers for Accounts Payable Automation.

Stability: STABLE

Provides REST APIs for AP workflows:
- Invoice management
- Payment optimization
- Batch payment processing
- Cash flow forecasting
- Discount opportunity tracking

Features:
- Circuit breaker pattern for AP service resilience
- Rate limiting (30-120 requests/minute depending on endpoint)
- RBAC permission checks (ap:read, finance:write, finance:approve)
- Comprehensive input validation

Endpoints:
- POST /api/v1/accounting/ap/invoices - Add payable invoice
- GET /api/v1/accounting/ap/invoices - List payable invoices
- GET /api/v1/accounting/ap/invoices/{id} - Get invoice by ID
- POST /api/v1/accounting/ap/invoices/{id}/payment - Record payment
- POST /api/v1/accounting/ap/optimize - Optimize payment timing
- POST /api/v1/accounting/ap/batch - Create batch payment
- GET /api/v1/accounting/ap/forecast - Get cash flow forecast
- GET /api/v1/accounting/ap/discounts - Get discount opportunities
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from decimal import Decimal
from typing import Any

from aragora.resilience import CircuitBreaker
from aragora.resilience import CircuitOpenError  # noqa: F401 - used in exception handling
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    success_response,
)
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.handlers.utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)

# =============================================================================
# Resilience Configuration
# =============================================================================

# Circuit breaker for AP automation service
_ap_circuit_breaker = CircuitBreaker(
    name="ap_automation_handler",
    failure_threshold=5,
    cooldown_seconds=30.0,
)


def get_ap_circuit_breaker() -> CircuitBreaker:
    """Get the circuit breaker for AP automation service."""
    return _ap_circuit_breaker


def get_ap_circuit_breaker_status() -> dict[str, Any]:
    """Get current status of the AP automation circuit breaker."""
    return _ap_circuit_breaker.to_dict()


# Thread-safe service instance
_ap_automation: Any | None = None
_ap_automation_lock = threading.Lock()


def get_ap_automation():
    """Get or create AP automation service (thread-safe singleton)."""
    global _ap_automation
    if _ap_automation is not None:
        return _ap_automation

    with _ap_automation_lock:
        if _ap_automation is None:
            from aragora.services.ap_automation import APAutomation

            _ap_automation = APAutomation()
        return _ap_automation


# =============================================================================
# Invoice Management
# =============================================================================


@rate_limit(requests_per_minute=60)
@require_permission("finance:write")
async def handle_add_invoice(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Add a payable invoice.

    POST /api/v1/accounting/ap/invoices
    Body: {
        vendor_id: str (required),
        vendor_name: str (required),
        invoice_number: str (optional),
        invoice_date: str (optional, ISO format),
        due_date: str (optional, ISO format),
        total_amount: float (required),
        payment_terms: str (optional, default "Net 30"),
        early_pay_discount: float (optional, e.g. 0.02 for 2%),
        discount_deadline: str (optional, ISO format),
        priority: str (optional - critical, high, normal, low, hold),
        preferred_payment_method: str (optional - ach, wire, check, credit_card)
    }
    """
    # Validate required fields
    vendor_id = data.get("vendor_id")
    vendor_name = data.get("vendor_name")
    total_amount = data.get("total_amount")

    if not vendor_id:
        return error_response("vendor_id is required", status=400)
    if not isinstance(vendor_id, str) or not vendor_id.strip():
        return error_response("vendor_id must be a non-empty string", status=400)

    if not vendor_name:
        return error_response("vendor_name is required", status=400)
    if not isinstance(vendor_name, str) or not vendor_name.strip():
        return error_response("vendor_name must be a non-empty string", status=400)

    if total_amount is None:
        return error_response("total_amount is required", status=400)

    try:
        amount_decimal = Decimal(str(total_amount))
        if amount_decimal <= 0:
            return error_response("total_amount must be positive", status=400)
    except (ValueError, TypeError, ArithmeticError):
        return error_response("total_amount must be a valid number", status=400)

    # Parse and validate dates
    invoice_date = None
    due_date = None
    discount_deadline = None

    try:
        if data.get("invoice_date"):
            invoice_date = datetime.fromisoformat(data["invoice_date"])
        if data.get("due_date"):
            due_date = datetime.fromisoformat(data["due_date"])
        if data.get("discount_deadline"):
            discount_deadline = datetime.fromisoformat(data["discount_deadline"])
    except ValueError:
        return error_response("Dates must be in ISO format", status=400)

    # Check circuit breaker before processing
    if not _ap_circuit_breaker.can_proceed():
        remaining = _ap_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AP service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ap = get_ap_automation()

        async with _ap_circuit_breaker.protected_call():
            invoice = await ap.add_invoice(
                vendor_id=vendor_id.strip(),
                vendor_name=vendor_name.strip(),
                invoice_number=data.get("invoice_number", ""),
                invoice_date=invoice_date,
                due_date=due_date,
                total_amount=amount_decimal,
                payment_terms=data.get("payment_terms", "Net 30"),
                early_pay_discount=data.get("early_pay_discount", 0),
                discount_deadline=discount_deadline,
                priority=data.get("priority"),
                preferred_payment_method=data.get("preferred_payment_method"),
            )

        return success_response(
            {
                "invoice": invoice.to_dict(),
                "message": "Invoice added successfully",
            }
        )

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AP service temporarily unavailable", status=503)
    except (ValueError, TypeError, KeyError, AttributeError):
        logger.exception("Error adding invoice")
        return error_response("Invoice creation failed", status=500)


@rate_limit(requests_per_minute=120)
@require_permission("ap:read")
async def handle_list_invoices(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    List payable invoices with filters.

    GET /api/v1/accounting/ap/invoices
    Query params: {
        vendor_id: str (optional),
        status: str (optional - unpaid, partial, paid),
        priority: str (optional),
        start_date: str (optional, ISO format),
        end_date: str (optional, ISO format),
        limit: int (optional, default 100),
        offset: int (optional, default 0)
    }
    """
    # Parse and validate filters
    vendor_id = data.get("vendor_id")
    status = data.get("status")
    priority = data.get("priority")
    start_date = None
    end_date = None

    try:
        if data.get("start_date"):
            start_date = datetime.fromisoformat(data["start_date"])
        if data.get("end_date"):
            end_date = datetime.fromisoformat(data["end_date"])
    except ValueError:
        return error_response("Dates must be in ISO format", status=400)

    try:
        limit = int(data.get("limit", 100))
        offset = int(data.get("offset", 0))
        if limit < 1 or limit > 1000:
            return error_response("limit must be 1-1000", status=400)
        if offset < 0:
            return error_response("offset must be non-negative", status=400)
    except (ValueError, TypeError):
        return error_response("limit and offset must be integers", status=400)

    # Check circuit breaker before processing
    if not _ap_circuit_breaker.can_proceed():
        remaining = _ap_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AP service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ap = get_ap_automation()

        async with _ap_circuit_breaker.protected_call():
            invoices = await ap.list_invoices(
                vendor_id=vendor_id,
                status=status,
                priority=priority,
                start_date=start_date,
                end_date=end_date,
            )

        # Apply pagination
        paginated = invoices[offset : offset + limit]

        return success_response(
            {
                "invoices": [inv.to_dict() for inv in paginated],
                "total": len(invoices),
                "limit": limit,
                "offset": offset,
            }
        )

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AP service temporarily unavailable", status=503)
    except (ValueError, TypeError, KeyError, AttributeError):
        logger.exception("Error listing invoices")
        return error_response("Failed to list invoices", status=500)


@rate_limit(requests_per_minute=120)
@require_permission("ap:read")
async def handle_get_invoice(
    data: dict[str, Any],
    invoice_id: str,
    user_id: str = "default",
) -> HandlerResult:
    """
    Get a payable invoice by ID.

    GET /api/v1/accounting/ap/invoices/{invoice_id}
    """
    # Validate invoice_id
    if not invoice_id or not invoice_id.strip():
        return error_response("invoice_id is required", status=400)

    # Check circuit breaker before processing
    if not _ap_circuit_breaker.can_proceed():
        remaining = _ap_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AP service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ap = get_ap_automation()

        async with _ap_circuit_breaker.protected_call():
            invoice = await ap.get_invoice(invoice_id)

        if not invoice:
            return error_response(f"Invoice {invoice_id} not found", status=404)

        return success_response({"invoice": invoice.to_dict()})

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AP service temporarily unavailable", status=503)
    except (ValueError, TypeError, KeyError, AttributeError):
        logger.exception("Error getting invoice %s", invoice_id)
        return error_response("Failed to retrieve invoice", status=500)


@rate_limit(requests_per_minute=60)
@require_permission("finance:write")
async def handle_record_payment(
    data: dict[str, Any],
    invoice_id: str,
    user_id: str = "default",
) -> HandlerResult:
    """
    Record a payment for a payable invoice.

    POST /api/v1/accounting/ap/invoices/{invoice_id}/payment
    Body: {
        amount: float (required),
        payment_date: str (optional, ISO format),
        payment_method: str (optional),
        reference: str (optional)
    }
    """
    # Validate invoice_id
    if not invoice_id or not invoice_id.strip():
        return error_response("invoice_id is required", status=400)

    # Validate amount
    amount = data.get("amount")
    if amount is None:
        return error_response("amount is required", status=400)

    try:
        amount_decimal = Decimal(str(amount))
        if amount_decimal <= 0:
            return error_response("amount must be positive", status=400)
    except (ValueError, TypeError, ArithmeticError):
        return error_response("amount must be a valid number", status=400)

    # Validate payment_date if provided
    payment_date = None
    if data.get("payment_date"):
        try:
            payment_date = datetime.fromisoformat(data["payment_date"])
        except ValueError:
            return error_response("payment_date must be in ISO format", status=400)

    # Check circuit breaker before processing
    if not _ap_circuit_breaker.can_proceed():
        remaining = _ap_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AP service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ap = get_ap_automation()

        async with _ap_circuit_breaker.protected_call():
            invoice = await ap.get_invoice(invoice_id)
            if not invoice:
                return error_response(f"Invoice {invoice_id} not found", status=404)

            updated_invoice = await ap.record_payment(
                invoice_id=invoice_id,
                amount=amount_decimal,
                payment_date=payment_date,
                payment_method=data.get("payment_method"),
                reference=data.get("reference"),
            )

        return success_response(
            {
                "invoice": updated_invoice.to_dict(),
                "message": f"Payment of {amount} recorded successfully",
            }
        )

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AP service temporarily unavailable", status=503)
    except (ValueError, TypeError, KeyError, AttributeError):
        logger.exception("Error recording payment for invoice %s", invoice_id)
        return error_response("Payment recording failed", status=500)


# =============================================================================
# Payment Optimization
# =============================================================================


@rate_limit(requests_per_minute=30)
@require_permission("finance:approve")
async def handle_optimize_payments(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Optimize payment timing for outstanding invoices.

    POST /api/v1/accounting/ap/optimize
    Body: {
        invoice_ids: list[str] (optional, defaults to all unpaid),
        available_cash: float (optional),
        prioritize_discounts: bool (optional, default true)
    }
    """
    # Validate available_cash if provided
    available_cash = data.get("available_cash")
    cash_decimal = None
    if available_cash is not None:
        try:
            cash_decimal = Decimal(str(available_cash))
            if cash_decimal < 0:
                return error_response("available_cash must be non-negative", status=400)
        except (ValueError, TypeError, ArithmeticError):
            return error_response("available_cash must be a valid number", status=400)

    invoice_ids = data.get("invoice_ids")
    prioritize_discounts = data.get("prioritize_discounts", True)

    # Check circuit breaker before processing
    if not _ap_circuit_breaker.can_proceed():
        remaining = _ap_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AP service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ap = get_ap_automation()

        async with _ap_circuit_breaker.protected_call():
            # Get invoices to optimize
            if invoice_ids:
                invoices = []
                for inv_id in invoice_ids:
                    inv = await ap.get_invoice(inv_id)
                    if inv:
                        invoices.append(inv)
            else:
                # Get all unpaid invoices
                invoices = await ap.list_invoices(status="unpaid")

            if not invoices:
                return success_response(
                    {
                        "schedule": [],
                        "message": "No invoices to optimize",
                    }
                )

            schedule = await ap.optimize_payment_timing(
                invoices=invoices,
                available_cash=cash_decimal,
                prioritize_discounts=prioritize_discounts,
            )

        return success_response(
            {
                "schedule": schedule.to_dict(),
                "total_invoices": len(invoices),
                "message": "Payment schedule optimized",
            }
        )

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AP service temporarily unavailable", status=503)
    except (ValueError, TypeError, KeyError, AttributeError):
        logger.exception("Error optimizing payments")
        return error_response("Payment optimization failed", status=500)


@rate_limit(requests_per_minute=30)
@require_permission("finance:approve")
async def handle_batch_payments(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Create a batch payment for multiple invoices.

    POST /api/v1/accounting/ap/batch
    Body: {
        invoice_ids: list[str] (required),
        payment_date: str (optional, ISO format),
        payment_method: str (optional)
    }
    """
    # Validate invoice_ids
    invoice_ids = data.get("invoice_ids")
    if not invoice_ids:
        return error_response("invoice_ids is required", status=400)
    if not isinstance(invoice_ids, list) or len(invoice_ids) == 0:
        return error_response("invoice_ids must be a non-empty list", status=400)

    # Validate payment_date if provided
    payment_date = None
    if data.get("payment_date"):
        try:
            payment_date = datetime.fromisoformat(data["payment_date"])
        except ValueError:
            return error_response("payment_date must be in ISO format", status=400)

    # Check circuit breaker before processing
    if not _ap_circuit_breaker.can_proceed():
        remaining = _ap_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AP service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ap = get_ap_automation()

        async with _ap_circuit_breaker.protected_call():
            # Get invoices
            invoices = []
            for inv_id in invoice_ids:
                inv = await ap.get_invoice(inv_id)
                if inv:
                    invoices.append(inv)
                else:
                    return error_response(f"Invoice {inv_id} not found", status=404)

            batch = await ap.batch_payments(
                invoices=invoices,
                payment_date=payment_date,
                payment_method=data.get("payment_method"),
            )

        return success_response(
            {
                "batch": batch.to_dict(),
                "message": f"Batch payment created for {len(invoices)} invoices",
            }
        )

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AP service temporarily unavailable", status=503)
    except (ValueError, TypeError, KeyError, AttributeError):
        logger.exception("Error creating batch payment")
        return error_response("Batch creation failed", status=500)


# =============================================================================
# Forecasting and Analysis
# =============================================================================


@rate_limit(requests_per_minute=60)
@require_permission("ap:read")
async def handle_get_forecast(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get cash flow forecast.

    GET /api/v1/accounting/ap/forecast
    Query params: {
        days_ahead: int (optional, default 30)
    }
    """
    # Validate days_ahead
    try:
        days_ahead = int(data.get("days_ahead", 30))
    except (ValueError, TypeError):
        return error_response("days_ahead must be an integer", status=400)

    if days_ahead < 1 or days_ahead > 365:
        return error_response("days_ahead must be 1-365", status=400)

    # Check circuit breaker before processing
    if not _ap_circuit_breaker.can_proceed():
        remaining = _ap_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AP service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ap = get_ap_automation()

        async with _ap_circuit_breaker.protected_call():
            forecast = await ap.forecast_cash_needs(days_ahead=days_ahead)

        return success_response(
            {
                "forecast": forecast.to_dict(),
                "days_ahead": days_ahead,
                "generated_at": datetime.now().isoformat(),
            }
        )

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AP service temporarily unavailable", status=503)
    except (ValueError, TypeError, KeyError, AttributeError):
        logger.exception("Error generating forecast")
        return error_response("Forecast generation failed", status=500)


@rate_limit(requests_per_minute=60)
@require_permission("ap:read")
async def handle_get_discounts(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get early payment discount opportunities.

    GET /api/v1/accounting/ap/discounts
    """
    # Check circuit breaker before processing
    if not _ap_circuit_breaker.can_proceed():
        remaining = _ap_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AP service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ap = get_ap_automation()

        async with _ap_circuit_breaker.protected_call():
            opportunities = await ap.get_discount_opportunities()

        return success_response(
            {
                "opportunities": opportunities,
                "total": len(opportunities),
            }
        )

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AP service temporarily unavailable", status=503)
    except (ValueError, TypeError, KeyError, AttributeError):
        logger.exception("Error getting discount opportunities")
        return error_response("Failed to retrieve discounts", status=500)


# =============================================================================
# Handler Registration
# =============================================================================


class APAutomationHandler(BaseHandler):
    """Handler class for AP automation endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    _ROUTE_MAP: dict[str, Any] = {
        "POST /api/v1/accounting/ap/invoices": handle_add_invoice,
        "GET /api/v1/accounting/ap/invoices": handle_list_invoices,
        "POST /api/v1/accounting/ap/optimize": handle_optimize_payments,
        "POST /api/v1/accounting/ap/batch": handle_batch_payments,
        "GET /api/v1/accounting/ap/forecast": handle_get_forecast,
        "GET /api/v1/accounting/ap/discounts": handle_get_discounts,
    }

    ROUTES = [
        "/api/v1/accounting/ap/invoices",
        "/api/v1/accounting/ap/optimize",
        "/api/v1/accounting/ap/batch",
        "/api/v1/accounting/ap/forecast",
        "/api/v1/accounting/ap/discounts",
        "/api/v1/accounting/connect",
        "/api/v1/accounting/customers",
        "/api/v1/accounting/disconnect",
        "/api/v1/accounting/expenses",
        "/api/v1/accounting/expenses/categorize",
        "/api/v1/accounting/expenses/export",
        "/api/v1/accounting/expenses/pending",
        "/api/v1/accounting/expenses/stats",
        "/api/v1/accounting/expenses/sync",
        "/api/v1/accounting/expenses/upload",
        "/api/v1/accounting/invoices",
        "/api/v1/accounting/invoices/overdue",
        "/api/v1/accounting/invoices/pending",
        "/api/v1/accounting/invoices/stats",
        "/api/v1/accounting/invoices/status",
        "/api/v1/accounting/invoices/upload",
        "/api/v1/accounting/payments/scheduled",
        "/api/v1/accounting/purchase-orders",
        "/api/v1/accounting/reports",
        "/api/v1/accounting/status",
        "/api/v1/accounting/transactions",
        "/api/v1/accounting/gusto/employees",
        "/api/v1/accounting/gusto/payrolls",
        "/api/v1/accounting/gusto/status",
        "/api/v1/gusto/connect",
        "/api/v1/gusto/disconnect",
        "/api/v1/gusto/employees",
        "/api/v1/gusto/payrolls",
        "/api/v1/gusto/status",
        "/api/v1/ap/batch-payments",
        "/api/v1/ap/cash-flow",
        "/api/v1/ap/discount-opportunities",
        "/api/v1/ap/invoices",
        "/api/v1/ap/optimize",
    ]

    DYNAMIC_ROUTES: dict[str, Any] = {
        "GET /api/v1/accounting/ap/invoices/{invoice_id}": handle_get_invoice,
        "POST /api/v1/accounting/ap/invoices/{invoice_id}/payment": handle_record_payment,
    }
