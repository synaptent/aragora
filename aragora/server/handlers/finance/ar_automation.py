"""
HTTP API Handlers for Accounts Receivable Automation.

Stability: STABLE

Provides REST APIs for AR workflows:
- Invoice generation and management
- Payment reminder scheduling
- AR aging reports
- Collection action suggestions
- Customer management

Features:
- Circuit breaker pattern for AR service resilience
- Rate limiting (20-60 requests/minute depending on endpoint)
- RBAC permission checks (ar:read, finance:write)
- Comprehensive input validation

Endpoints:
- POST /api/v1/accounting/ar/invoices - Create invoice
- GET /api/v1/accounting/ar/invoices - List invoices
- GET /api/v1/accounting/ar/invoices/{id} - Get invoice by ID
- POST /api/v1/accounting/ar/invoices/{id}/send - Send invoice to customer
- POST /api/v1/accounting/ar/invoices/{id}/reminder - Send payment reminder
- POST /api/v1/accounting/ar/invoices/{id}/payment - Record payment
- GET /api/v1/accounting/ar/aging - Get AR aging report
- GET /api/v1/accounting/ar/collections - Get collection suggestions
- POST /api/v1/accounting/ar/customers - Add customer
- GET /api/v1/accounting/ar/customers/{id}/balance - Get customer balance
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from decimal import Decimal
from typing import Any

from aragora.resilience import CircuitBreaker, CircuitOpenError
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

# Circuit breaker for AR automation service
_ar_circuit_breaker = CircuitBreaker(
    name="ar_automation_handler",
    failure_threshold=5,
    cooldown_seconds=30.0,
)


def get_ar_circuit_breaker() -> CircuitBreaker:
    """Get the circuit breaker for AR automation service."""
    return _ar_circuit_breaker


def get_ar_circuit_breaker_status() -> dict[str, Any]:
    """Get current status of the AR automation circuit breaker."""
    return _ar_circuit_breaker.to_dict()


# Thread-safe service instance
_ar_automation: Any | None = None
_ar_automation_lock = threading.Lock()


def get_ar_automation():
    """Get or create AR automation service (thread-safe singleton)."""
    global _ar_automation
    if _ar_automation is not None:
        return _ar_automation

    with _ar_automation_lock:
        if _ar_automation is None:
            from aragora.services.ar_automation import ARAutomation

            _ar_automation = ARAutomation()
        return _ar_automation


# =============================================================================
# Invoice Management
# =============================================================================


@rate_limit(requests_per_minute=20)  # Write operation
@require_permission("finance:write")
async def handle_create_invoice(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Create a new AR invoice.

    POST /api/v1/accounting/ar/invoices
    Body: {
        customer_id: str (required),
        customer_name: str (required),
        customer_email: str (optional),
        line_items: list[{description, quantity, unit_price, amount}] (required),
        payment_terms: str (optional, default "Net 30"),
        memo: str (optional),
        tax_rate: float (optional, default 0)
    }
    """
    # Check circuit breaker before processing
    if not _ar_circuit_breaker.can_proceed():
        remaining = _ar_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AR service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ar = get_ar_automation()

        customer_id = data.get("customer_id")
        customer_name = data.get("customer_name")
        line_items = data.get("line_items", [])

        if not customer_id:
            return error_response("customer_id is required", status=400)
        if not customer_name:
            return error_response("customer_name is required", status=400)
        if not line_items:
            return error_response("line_items is required", status=400)

        # Validate line items
        for item in line_items:
            if "description" not in item or "amount" not in item:
                return error_response("Each line item must have description and amount", status=400)

        async with _ar_circuit_breaker.protected_call():
            invoice = await ar.generate_invoice(
                customer_id=customer_id,
                customer_name=customer_name,
                customer_email=data.get("customer_email"),
                line_items=line_items,
                payment_terms=data.get("payment_terms", "Net 30"),
                memo=data.get("memo", ""),
                tax_rate=data.get("tax_rate", 0),
            )

        return success_response(
            {
                "invoice": invoice.to_dict(),
                "message": "Invoice created successfully",
            }
        )

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AR service temporarily unavailable", status=503)
    except (TypeError, ValueError, AttributeError, OSError):
        logger.exception("Error creating invoice")
        return error_response("Invoice creation failed", status=500)


@rate_limit(requests_per_minute=60)  # Read operation
@require_permission("ar:read")
async def handle_list_invoices(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    List AR invoices with filters.

    GET /api/v1/accounting/ar/invoices
    Query params: {
        customer_id: str (optional),
        status: str (optional - draft, sent, paid, overdue),
        start_date: str (optional, ISO format),
        end_date: str (optional, ISO format),
        limit: int (optional, default 100),
        offset: int (optional, default 0)
    }
    """
    # Check circuit breaker before processing
    if not _ar_circuit_breaker.can_proceed():
        remaining = _ar_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AR service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ar = get_ar_automation()

        # Parse filters
        customer_id = data.get("customer_id")
        status = data.get("status")
        start_date = None
        end_date = None

        try:
            if data.get("start_date"):
                start_date = datetime.fromisoformat(data["start_date"])
            if data.get("end_date"):
                end_date = datetime.fromisoformat(data["end_date"])
        except ValueError:
            return error_response("Invalid date format. Use ISO 8601.", 400)

        limit = max(1, min(int(data.get("limit", 100)), 1000))
        offset = max(0, int(data.get("offset", 0)))

        async with _ar_circuit_breaker.protected_call():
            invoices = await ar.list_invoices(
                customer_id=customer_id,
                status=status,
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
        return error_response("AR service temporarily unavailable", status=503)
    except (TypeError, ValueError, AttributeError, OSError):
        logger.exception("Error listing invoices")
        return error_response("Failed to list invoices", status=500)


@rate_limit(requests_per_minute=60)  # Read operation
@require_permission("ar:read")
async def handle_get_invoice(
    data: dict[str, Any],
    invoice_id: str,
    user_id: str = "default",
) -> HandlerResult:
    """
    Get an invoice by ID.

    GET /api/v1/accounting/ar/invoices/{invoice_id}
    """
    # Validate invoice_id
    if not invoice_id or not invoice_id.strip():
        return error_response("invoice_id is required", status=400)

    # Check circuit breaker before processing
    if not _ar_circuit_breaker.can_proceed():
        remaining = _ar_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AR service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ar = get_ar_automation()

        async with _ar_circuit_breaker.protected_call():
            invoice = await ar.get_invoice(invoice_id)

        if not invoice:
            return error_response(f"Invoice {invoice_id} not found", status=404)

        return success_response({"invoice": invoice.to_dict()})

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AR service temporarily unavailable", status=503)
    except (TypeError, ValueError, AttributeError, OSError):
        logger.exception("Error getting invoice %s", invoice_id)
        return error_response("Failed to retrieve invoice", status=500)


@rate_limit(requests_per_minute=20)  # Write operation
@require_permission("finance:write")
async def handle_send_invoice(
    data: dict[str, Any],
    invoice_id: str,
    user_id: str = "default",
) -> HandlerResult:
    """
    Send an invoice to the customer.

    POST /api/v1/accounting/ar/invoices/{invoice_id}/send
    """
    # Validate invoice_id
    if not invoice_id or not invoice_id.strip():
        return error_response("invoice_id is required", status=400)

    # Check circuit breaker before processing
    if not _ar_circuit_breaker.can_proceed():
        remaining = _ar_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AR service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ar = get_ar_automation()

        async with _ar_circuit_breaker.protected_call():
            invoice = await ar.get_invoice(invoice_id)
            if not invoice:
                return error_response(f"Invoice {invoice_id} not found", status=404)

            success = await ar.send_invoice(invoice_id)

        if success:
            return success_response(
                {
                    "message": "Invoice sent successfully",
                    "invoice_id": invoice_id,
                }
            )
        else:
            return error_response("Failed to send invoice", status=500)

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AR service temporarily unavailable", status=503)
    except (TypeError, ValueError, AttributeError, ConnectionError, OSError):
        logger.exception("Error sending invoice %s", invoice_id)
        return error_response("Invoice delivery failed", status=500)


@rate_limit(requests_per_minute=20)  # Write operation (sends email)
@require_permission("ar:read")
async def handle_send_reminder(
    data: dict[str, Any],
    invoice_id: str,
    user_id: str = "default",
) -> HandlerResult:
    """
    Send a payment reminder for an invoice.

    POST /api/v1/accounting/ar/invoices/{invoice_id}/reminder
    Body: {
        escalation_level: int (optional, 1-4)
    }
    """
    # Validate invoice_id
    if not invoice_id or not invoice_id.strip():
        return error_response("invoice_id is required", status=400)

    # Validate escalation_level before service call
    try:
        escalation_level = int(data.get("escalation_level", 1))
    except (ValueError, TypeError):
        return error_response("escalation_level must be an integer", status=400)

    if escalation_level < 1 or escalation_level > 4:
        return error_response("escalation_level must be 1-4", status=400)

    # Check circuit breaker before processing
    if not _ar_circuit_breaker.can_proceed():
        remaining = _ar_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AR service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ar = get_ar_automation()

        async with _ar_circuit_breaker.protected_call():
            invoice = await ar.get_invoice(invoice_id)
            if not invoice:
                return error_response(f"Invoice {invoice_id} not found", status=404)

            success = await ar.send_payment_reminder(
                invoice_id=invoice_id,
                escalation_level=escalation_level,
            )

        if success:
            return success_response(
                {
                    "message": f"Reminder (level {escalation_level}) sent successfully",
                    "invoice_id": invoice_id,
                }
            )
        else:
            return error_response("Failed to send reminder", status=500)

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AR service temporarily unavailable", status=503)
    except (TypeError, ValueError, AttributeError, ConnectionError, OSError):
        logger.exception("Error sending reminder for invoice %s", invoice_id)
        return error_response("Reminder delivery failed", status=500)


@rate_limit(requests_per_minute=20)  # Write operation
@require_permission("finance:write")
async def handle_record_payment(
    data: dict[str, Any],
    invoice_id: str,
    user_id: str = "default",
) -> HandlerResult:
    """
    Record a payment against an invoice.

    POST /api/v1/accounting/ar/invoices/{invoice_id}/payment
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

    # Validate amount before service call
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
    if not _ar_circuit_breaker.can_proceed():
        remaining = _ar_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AR service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ar = get_ar_automation()

        async with _ar_circuit_breaker.protected_call():
            invoice = await ar.get_invoice(invoice_id)
            if not invoice:
                return error_response(f"Invoice {invoice_id} not found", status=404)

            updated_invoice = await ar.record_payment(
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
        return error_response("AR service temporarily unavailable", status=503)
    except (TypeError, ValueError, AttributeError, ArithmeticError, OSError):
        logger.exception("Error recording payment for invoice %s", invoice_id)
        return error_response("Payment recording failed", status=500)


# =============================================================================
# AR Reporting
# =============================================================================


@rate_limit(requests_per_minute=60)  # Read operation
@require_permission("ar:read")
async def handle_get_aging_report(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get AR aging report.

    GET /api/v1/accounting/ar/aging
    """
    # Check circuit breaker before processing
    if not _ar_circuit_breaker.can_proceed():
        remaining = _ar_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AR service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ar = get_ar_automation()

        async with _ar_circuit_breaker.protected_call():
            report = await ar.track_aging()

        return success_response(
            {
                "aging_report": report.to_dict(),
                "generated_at": datetime.now().isoformat(),
            }
        )

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AR service temporarily unavailable", status=503)
    except (TypeError, ValueError, AttributeError, OSError):
        logger.exception("Error generating aging report")
        return error_response("Aging report generation failed", status=500)


@rate_limit(requests_per_minute=60)  # Read operation
@require_permission("ar:read")
async def handle_get_collections(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get collection action suggestions.

    GET /api/v1/accounting/ar/collections
    """
    # Check circuit breaker before processing
    if not _ar_circuit_breaker.can_proceed():
        remaining = _ar_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AR service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ar = get_ar_automation()

        async with _ar_circuit_breaker.protected_call():
            suggestions = await ar.suggest_collections()

        return success_response(
            {
                "suggestions": [s.to_dict() for s in suggestions],
                "total": len(suggestions),
            }
        )

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AR service temporarily unavailable", status=503)
    except (TypeError, ValueError, AttributeError, OSError):
        logger.exception("Error getting collection suggestions")
        return error_response("Failed to retrieve suggestions", status=500)


# =============================================================================
# Customer Management
# =============================================================================


@rate_limit(requests_per_minute=20)  # Write operation
@require_permission("finance:write")
async def handle_add_customer(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Add a new customer.

    POST /api/v1/accounting/ar/customers
    Body: {
        customer_id: str (required),
        name: str (required),
        email: str (optional),
        phone: str (optional),
        address: str (optional),
        payment_terms: str (optional, default "Net 30")
    }
    """
    # Validate required fields before service call
    customer_id = data.get("customer_id")
    name = data.get("name")

    if not customer_id:
        return error_response("customer_id is required", status=400)
    if not isinstance(customer_id, str) or not customer_id.strip():
        return error_response("customer_id must be a non-empty string", status=400)

    if not name:
        return error_response("name is required", status=400)
    if not isinstance(name, str) or not name.strip():
        return error_response("name must be a non-empty string", status=400)

    # Check circuit breaker before processing
    if not _ar_circuit_breaker.can_proceed():
        remaining = _ar_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AR service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ar = get_ar_automation()

        async with _ar_circuit_breaker.protected_call():
            await ar.add_customer(
                customer_id=customer_id.strip(),
                name=name.strip(),
                email=data.get("email"),
                payment_terms=data.get("payment_terms", "Net 30"),
            )

        return success_response(
            {
                "message": "Customer added successfully",
                "customer_id": customer_id,
            }
        )

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AR service temporarily unavailable", status=503)
    except (TypeError, ValueError, AttributeError, OSError):
        logger.exception("Error adding customer")
        return error_response("Customer creation failed", status=500)


@rate_limit(requests_per_minute=60)  # Read operation
@require_permission("ar:read")
async def handle_get_customer_balance(
    data: dict[str, Any],
    customer_id: str,
    user_id: str = "default",
) -> HandlerResult:
    """
    Get outstanding balance for a customer.

    GET /api/v1/accounting/ar/customers/{customer_id}/balance
    """
    # Validate customer_id
    if not customer_id or not customer_id.strip():
        return error_response("customer_id is required", status=400)

    # Check circuit breaker before processing
    if not _ar_circuit_breaker.can_proceed():
        remaining = _ar_circuit_breaker.cooldown_remaining()
        return error_response(
            f"AR service temporarily unavailable. Retry in {remaining:.1f}s",
            status=503,
        )

    try:
        ar = get_ar_automation()

        async with _ar_circuit_breaker.protected_call():
            balance = await ar.get_customer_balance(customer_id)

        return success_response(
            {
                "customer_id": customer_id,
                "outstanding_balance": str(balance),
            }
        )

    except CircuitOpenError as e:
        logger.warning("Handler error: %s", e)
        return error_response("AR service temporarily unavailable", status=503)
    except (TypeError, ValueError, AttributeError, OSError):
        logger.exception("Error getting balance for customer %s", customer_id)
        return error_response("Failed to retrieve balance", status=500)


# =============================================================================
# Handler Registration
# =============================================================================


class ARAutomationHandler(BaseHandler):
    """Handler class for AR automation endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    _ROUTE_MAP: dict[str, Any] = {
        "POST /api/v1/accounting/ar/invoices": handle_create_invoice,
        "GET /api/v1/accounting/ar/invoices": handle_list_invoices,
        "GET /api/v1/accounting/ar/aging": handle_get_aging_report,
        "GET /api/v1/accounting/ar/collections": handle_get_collections,
        "POST /api/v1/accounting/ar/customers": handle_add_customer,
    }

    ROUTES = [
        "/api/v1/accounting/ar/aging",
        "/api/v1/accounting/ar/collections",
        "/api/v1/accounting/ar/customers",
        "/api/v1/accounting/ar/invoices",
    ]

    DYNAMIC_ROUTES: dict[str, Any] = {
        "GET /api/v1/accounting/ar/invoices/{invoice_id}": handle_get_invoice,
        "POST /api/v1/accounting/ar/invoices/{invoice_id}/send": handle_send_invoice,
        "POST /api/v1/accounting/ar/invoices/{invoice_id}/reminder": handle_send_reminder,
        "POST /api/v1/accounting/ar/invoices/{invoice_id}/payment": handle_record_payment,
        "GET /api/v1/accounting/ar/customers/{customer_id}/balance": handle_get_customer_balance,
    }
