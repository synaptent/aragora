"""
HTTP API Handlers for Expense Tracking.

Stability: STABLE

Provides REST APIs for expense management:
- Receipt upload and processing
- Expense CRUD operations
- Auto-categorization
- Duplicate detection
- QBO sync integration
- Expense reporting and stats

Endpoints:
- POST /api/v1/accounting/expenses/upload - Upload and process receipt
- POST /api/v1/accounting/expenses - Create expense manually
- GET /api/v1/accounting/expenses - List expenses with filters
- GET /api/v1/accounting/expenses/{id} - Get expense by ID
- PUT /api/v1/accounting/expenses/{id} - Update expense
- DELETE /api/v1/accounting/expenses/{id} - Delete expense
- POST /api/v1/accounting/expenses/{id}/approve - Approve expense
- POST /api/v1/accounting/expenses/{id}/reject - Reject expense
- POST /api/v1/accounting/expenses/categorize - Auto-categorize expenses
- POST /api/v1/accounting/expenses/sync - Sync expenses to QBO
- GET /api/v1/accounting/expenses/stats - Get expense statistics
- GET /api/v1/accounting/expenses/pending - Get pending approvals
- GET /api/v1/accounting/expenses/export - Export expenses
"""

from __future__ import annotations

import base64
import binascii
import logging
import threading
from datetime import datetime
from typing import Any, TypeAlias
from collections.abc import Awaitable

from aragora.resilience import CircuitBreaker
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.validation.query_params import safe_query_int

logger = logging.getLogger(__name__)

# =============================================================================
# Circuit Breaker Configuration
# =============================================================================

# Circuit breaker for expense tracker service
# Opens after 5 consecutive failures, recovers after 30 seconds
_expense_circuit_breaker = CircuitBreaker(
    name="expense_handler",
    failure_threshold=5,
    cooldown_seconds=30.0,
    half_open_success_threshold=2,
    half_open_max_calls=3,
)
_expense_circuit_breaker_lock = threading.Lock()


def get_expense_circuit_breaker() -> CircuitBreaker:
    """Get the global circuit breaker for expense operations."""
    return _expense_circuit_breaker


def reset_expense_circuit_breaker() -> None:
    """Reset the global circuit breaker (for testing)."""
    with _expense_circuit_breaker_lock:
        _expense_circuit_breaker._single_failures = 0
        _expense_circuit_breaker._single_open_at = 0.0
        _expense_circuit_breaker._single_successes = 0
        _expense_circuit_breaker._single_half_open_calls = 0


# Type alias for handler methods that can return async or sync results
MaybeAsyncHandlerResult: TypeAlias = HandlerResult | None | Awaitable[HandlerResult | None]

# Thread-safe service instance
_expense_tracker: Any | None = None
_expense_tracker_lock = threading.Lock()


def get_expense_tracker():
    """Get or create expense tracker (thread-safe singleton)."""
    global _expense_tracker
    if _expense_tracker is not None:
        return _expense_tracker

    with _expense_tracker_lock:
        if _expense_tracker is None:
            from aragora.services.expense_tracker import ExpenseTracker

            _expense_tracker = ExpenseTracker()
        return _expense_tracker


# =============================================================================
# Receipt Upload and Processing
# =============================================================================


@rate_limit(requests_per_minute=30)
@require_permission("expenses:write")
async def handle_upload_receipt(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Upload and process a receipt image.

    POST /api/v1/accounting/expenses/upload
    Body: {
        receipt_data: str (base64 encoded image),
        content_type: str (image/png, image/jpeg, application/pdf),
        employee_id: str (optional),
        payment_method: str (optional, default credit_card)
    }
    """
    cb = get_expense_circuit_breaker()

    # Check circuit breaker before proceeding
    if not cb.can_proceed():
        logger.warning("Expense circuit breaker is open, rejecting upload request")
        return error_response(
            "Service temporarily unavailable. Please try again later.", status=503
        )

    try:
        tracker = get_expense_tracker()

        receipt_b64 = data.get("receipt_data")
        if not receipt_b64:
            return error_response("receipt_data is required", status=400)

        # Validate receipt_data type
        if not isinstance(receipt_b64, str):
            return error_response("receipt_data must be a string", status=400)

        # Decode base64 image
        try:
            image_data = base64.b64decode(receipt_b64)
        except (ValueError, binascii.Error):
            return error_response("Invalid base64 receipt_data", status=400)

        # Validate content_type if provided
        content_type = data.get("content_type")
        if content_type and content_type not in (
            "image/png",
            "image/jpeg",
            "image/jpg",
            "application/pdf",
        ):
            return error_response(
                "content_type must be image/png, image/jpeg, or application/pdf",
                status=400,
            )

        employee_id = data.get("employee_id")
        # Validate employee_id type if provided
        if employee_id is not None and not isinstance(employee_id, str):
            return error_response("employee_id must be a string", status=400)

        payment_method_str = data.get("payment_method", "credit_card")

        # Parse payment method
        from aragora.services.expense_tracker import PaymentMethod

        try:
            payment_method = PaymentMethod(payment_method_str)
        except ValueError:
            payment_method = PaymentMethod.CREDIT_CARD

        # Process receipt
        expense = await tracker.process_receipt(
            image_data=image_data,
            employee_id=employee_id,
            payment_method=payment_method,
        )

        cb.record_success()
        return json_response(
            {
                "expense": expense.to_dict(),
                "message": "Receipt processed successfully",
            }
        )

    except (RuntimeError, OSError, ValueError, TypeError):
        cb.record_failure()
        logger.exception("Error processing receipt")
        return error_response("Receipt processing failed", status=500)


# =============================================================================
# Expense CRUD Operations
# =============================================================================


@rate_limit(requests_per_minute=60)
@require_permission("expenses:write")
async def handle_create_expense(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Create an expense manually.

    POST /api/v1/accounting/expenses
    Body: {
        vendor_name: str (required),
        amount: float (required),
        date: str (ISO format, optional),
        category: str (optional),
        payment_method: str (optional),
        description: str (optional),
        employee_id: str (optional),
        is_reimbursable: bool (optional),
        tags: list[str] (optional)
    }
    """
    cb = get_expense_circuit_breaker()

    # Check circuit breaker before proceeding
    if not cb.can_proceed():
        logger.warning("Expense circuit breaker is open, rejecting create request")
        return error_response(
            "Service temporarily unavailable. Please try again later.", status=503
        )

    try:
        tracker = get_expense_tracker()

        vendor_name = data.get("vendor_name")
        amount = data.get("amount")

        if not vendor_name:
            return error_response("vendor_name is required", status=400)
        # Validate vendor_name type and length
        if not isinstance(vendor_name, str):
            return error_response("vendor_name must be a string", status=400)
        if len(vendor_name) > 500:
            return error_response("vendor_name must be 500 characters or less", status=400)

        if amount is None:
            return error_response("amount is required", status=400)

        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return error_response("amount must be a number", status=400)

        # Validate amount range
        if amount < 0:
            return error_response("amount must be non-negative", status=400)
        if amount > 1_000_000_000:  # 1 billion cap for sanity
            return error_response("amount exceeds maximum allowed value", status=400)

        # Parse date
        date = None
        date_str = data.get("date")
        if date_str:
            if not isinstance(date_str, str):
                return error_response("date must be a string", status=400)
            try:
                date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                return error_response("Invalid date format", status=400)

        # Parse category
        from aragora.services.expense_tracker import ExpenseCategory, PaymentMethod

        category = None
        category_str = data.get("category")
        if category_str:
            try:
                category = ExpenseCategory(category_str)
            except ValueError:
                logger.debug("Invalid category '%s', will auto-categorize", category_str)

        # Parse payment method
        payment_method = PaymentMethod.CREDIT_CARD
        payment_method_str = data.get("payment_method")
        if payment_method_str:
            try:
                payment_method = PaymentMethod(payment_method_str)
            except ValueError:
                logger.debug(
                    "Invalid payment_method '%s', defaulting to CREDIT_CARD", payment_method_str
                )

        # Validate description length if provided
        description = data.get("description", "")
        if description and len(description) > 5000:
            return error_response("description must be 5000 characters or less", status=400)

        # Validate tags if provided
        tags = data.get("tags")
        if tags is not None:
            if not isinstance(tags, list):
                return error_response("tags must be a list", status=400)
            if len(tags) > 50:
                return error_response("tags must contain 50 items or less", status=400)
            for tag in tags:
                if not isinstance(tag, str) or len(tag) > 100:
                    return error_response(
                        "each tag must be a string of 100 characters or less", status=400
                    )

        expense = await tracker.create_expense(
            vendor_name=vendor_name,
            amount=amount,
            date=date,
            category=category,
            payment_method=payment_method,
            description=description,
            employee_id=data.get("employee_id"),
            is_reimbursable=data.get("is_reimbursable", False),
            tags=tags,
        )

        cb.record_success()
        return json_response(
            {
                "expense": expense.to_dict(),
                "message": "Expense created successfully",
            }
        )

    except (RuntimeError, OSError, ValueError, TypeError):
        cb.record_failure()
        logger.exception("Error creating expense")
        return error_response("Expense creation failed", status=500)


@rate_limit(requests_per_minute=120)
@require_permission("expenses:read")
async def handle_list_expenses(
    query_params: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    List expenses with filters.

    GET /api/v1/accounting/expenses
    Query params:
        category: str
        vendor: str
        start_date: str (ISO format)
        end_date: str (ISO format)
        status: str
        employee_id: str
        limit: int (default 100)
        offset: int (default 0)
    """
    cb = get_expense_circuit_breaker()

    # Check circuit breaker before proceeding
    if not cb.can_proceed():
        logger.warning("Expense circuit breaker is open, rejecting list request")
        return error_response(
            "Service temporarily unavailable. Please try again later.", status=503
        )

    try:
        tracker = get_expense_tracker()

        # Parse filters
        from aragora.services.expense_tracker import ExpenseCategory, ExpenseStatus

        category = None
        category_str = query_params.get("category")
        if category_str:
            try:
                category = ExpenseCategory(category_str)
            except ValueError:
                logger.debug("Invalid category filter '%s', ignoring", category_str)

        status = None
        status_str = query_params.get("status")
        if status_str:
            try:
                status = ExpenseStatus(status_str)
            except ValueError:
                logger.debug("Invalid status filter '%s', ignoring", status_str)

        start_date = None
        start_date_str = query_params.get("start_date")
        if start_date_str:
            try:
                start_date = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
            except ValueError:
                logger.debug("Invalid start_date format '%s', ignoring", start_date_str)

        end_date = None
        end_date_str = query_params.get("end_date")
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            except ValueError:
                logger.debug("Invalid end_date format '%s', ignoring", end_date_str)

        limit = safe_query_int(query_params, "limit", default=100, max_val=1000)
        offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=100000)

        expenses, total = await tracker.list_expenses(
            category=category,
            vendor=query_params.get("vendor"),
            start_date=start_date,
            end_date=end_date,
            status=status,
            employee_id=query_params.get("employee_id"),
            limit=limit,
            offset=offset,
        )

        cb.record_success()
        return json_response(
            {
                "expenses": [e.to_dict() for e in expenses],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    except (RuntimeError, OSError, LookupError, ValueError, TypeError):
        cb.record_failure()
        logger.exception("Error listing expenses")
        return error_response("Failed to list expenses", status=500)


@rate_limit(requests_per_minute=120)
@require_permission("expenses:read")
async def handle_get_expense(
    expense_id: str,
    user_id: str = "default",
) -> HandlerResult:
    """
    Get expense by ID.

    GET /api/v1/accounting/expenses/{id}
    """
    # Validate expense_id format
    if not expense_id or not isinstance(expense_id, str):
        return error_response("expense_id is required", status=400)
    if len(expense_id) > 100:
        return error_response("expense_id is too long", status=400)

    cb = get_expense_circuit_breaker()

    # Check circuit breaker before proceeding
    if not cb.can_proceed():
        logger.warning("Expense circuit breaker is open, rejecting get request")
        return error_response(
            "Service temporarily unavailable. Please try again later.", status=503
        )

    try:
        tracker = get_expense_tracker()

        expense = await tracker.get_expense(expense_id)
        if not expense:
            return error_response("Expense not found", status=404)

        cb.record_success()
        return json_response({"expense": expense.to_dict()})

    except (RuntimeError, OSError, LookupError):
        cb.record_failure()
        logger.exception("Error getting expense")
        return error_response("Failed to retrieve expense", status=500)


@rate_limit(requests_per_minute=60)
@require_permission("expenses:write")
async def handle_update_expense(
    expense_id: str,
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Update an expense.

    PUT /api/v1/accounting/expenses/{id}
    Body: {
        vendor_name: str (optional),
        amount: float (optional),
        category: str (optional),
        description: str (optional),
        status: str (optional),
        is_reimbursable: bool (optional),
        tags: list[str] (optional)
    }
    """
    # Validate expense_id format
    if not expense_id or not isinstance(expense_id, str):
        return error_response("expense_id is required", status=400)
    if len(expense_id) > 100:
        return error_response("expense_id is too long", status=400)

    cb = get_expense_circuit_breaker()

    # Check circuit breaker before proceeding
    if not cb.can_proceed():
        logger.warning("Expense circuit breaker is open, rejecting update request")
        return error_response(
            "Service temporarily unavailable. Please try again later.", status=503
        )

    try:
        tracker = get_expense_tracker()

        # Validate vendor_name if provided
        vendor_name = data.get("vendor_name")
        if vendor_name is not None:
            if not isinstance(vendor_name, str):
                return error_response("vendor_name must be a string", status=400)
            if len(vendor_name) > 500:
                return error_response("vendor_name must be 500 characters or less", status=400)

        # Validate amount if provided
        amount = data.get("amount")
        if amount is not None:
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                return error_response("amount must be a number", status=400)
            if amount < 0:
                return error_response("amount must be non-negative", status=400)
            if amount > 1_000_000_000:
                return error_response("amount exceeds maximum allowed value", status=400)

        # Validate description if provided
        description = data.get("description")
        if description is not None and len(str(description)) > 5000:
            return error_response("description must be 5000 characters or less", status=400)

        # Validate tags if provided
        tags = data.get("tags")
        if tags is not None:
            if not isinstance(tags, list):
                return error_response("tags must be a list", status=400)
            if len(tags) > 50:
                return error_response("tags must contain 50 items or less", status=400)
            for tag in tags:
                if not isinstance(tag, str) or len(tag) > 100:
                    return error_response(
                        "each tag must be a string of 100 characters or less", status=400
                    )

        # Parse category
        from aragora.services.expense_tracker import ExpenseCategory, ExpenseStatus

        category = None
        category_str = data.get("category")
        if category_str:
            try:
                category = ExpenseCategory(category_str)
            except ValueError:
                logger.debug("Invalid category '%s' in update, ignoring", category_str)

        status = None
        status_str = data.get("status")
        if status_str:
            try:
                status = ExpenseStatus(status_str)
            except ValueError:
                logger.debug("Invalid status '%s' in update, ignoring", status_str)

        expense = await tracker.update_expense(
            expense_id=expense_id,
            vendor_name=vendor_name,
            amount=amount,
            category=category,
            description=description,
            status=status,
            is_reimbursable=data.get("is_reimbursable"),
            tags=tags,
        )

        if not expense:
            return error_response("Expense not found", status=404)

        cb.record_success()
        return json_response(
            {
                "expense": expense.to_dict(),
                "message": "Expense updated successfully",
            }
        )

    except (RuntimeError, OSError, ValueError, TypeError):
        cb.record_failure()
        logger.exception("Error updating expense")
        return error_response("Expense update failed", status=500)


@rate_limit(requests_per_minute=30)
@require_permission("admin:audit")
async def handle_delete_expense(
    expense_id: str,
    user_id: str = "default",
) -> HandlerResult:
    """
    Delete an expense.

    DELETE /api/v1/accounting/expenses/{id}
    """
    # Validate expense_id format
    if not expense_id or not isinstance(expense_id, str):
        return error_response("expense_id is required", status=400)
    if len(expense_id) > 100:
        return error_response("expense_id is too long", status=400)

    cb = get_expense_circuit_breaker()

    # Check circuit breaker before proceeding
    if not cb.can_proceed():
        logger.warning("Expense circuit breaker is open, rejecting delete request")
        return error_response(
            "Service temporarily unavailable. Please try again later.", status=503
        )

    try:
        tracker = get_expense_tracker()

        deleted = await tracker.delete_expense(expense_id)
        if not deleted:
            return error_response("Expense not found", status=404)

        cb.record_success()
        return json_response({"message": "Expense deleted successfully"})

    except (RuntimeError, OSError, LookupError):
        cb.record_failure()
        logger.exception("Error deleting expense")
        return error_response("Expense deletion failed", status=500)


# =============================================================================
# Approval Workflow
# =============================================================================


@rate_limit(requests_per_minute=60)
@require_permission("expenses:approve")
async def handle_approve_expense(
    expense_id: str,
    user_id: str = "default",
) -> HandlerResult:
    """
    Approve an expense for sync.

    POST /api/v1/accounting/expenses/{id}/approve
    """
    # Validate expense_id format
    if not expense_id or not isinstance(expense_id, str):
        return error_response("expense_id is required", status=400)
    if len(expense_id) > 100:
        return error_response("expense_id is too long", status=400)

    cb = get_expense_circuit_breaker()

    # Check circuit breaker before proceeding
    if not cb.can_proceed():
        logger.warning("Expense circuit breaker is open, rejecting approve request")
        return error_response(
            "Service temporarily unavailable. Please try again later.", status=503
        )

    try:
        tracker = get_expense_tracker()

        expense = await tracker.approve_expense(expense_id)
        if not expense:
            return error_response("Expense not found", status=404)

        cb.record_success()
        return json_response(
            {
                "expense": expense.to_dict(),
                "message": "Expense approved successfully",
            }
        )

    except (RuntimeError, OSError, LookupError):
        cb.record_failure()
        logger.exception("Error approving expense")
        return error_response("Expense approval failed", status=500)


@rate_limit(requests_per_minute=60)
@require_permission("expenses:approve")
async def handle_reject_expense(
    expense_id: str,
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Reject an expense.

    POST /api/v1/accounting/expenses/{id}/reject
    Body: {
        reason: str (optional)
    }
    """
    # Validate expense_id format
    if not expense_id or not isinstance(expense_id, str):
        return error_response("expense_id is required", status=400)
    if len(expense_id) > 100:
        return error_response("expense_id is too long", status=400)

    cb = get_expense_circuit_breaker()

    # Check circuit breaker before proceeding
    if not cb.can_proceed():
        logger.warning("Expense circuit breaker is open, rejecting reject request")
        return error_response(
            "Service temporarily unavailable. Please try again later.", status=503
        )

    try:
        tracker = get_expense_tracker()

        reason = data.get("reason", "")
        # Validate reason length
        if reason and len(reason) > 1000:
            return error_response("reason must be 1000 characters or less", status=400)

        expense = await tracker.reject_expense(expense_id, reason)
        if not expense:
            return error_response("Expense not found", status=404)

        cb.record_success()
        return json_response(
            {
                "expense": expense.to_dict(),
                "message": "Expense rejected",
            }
        )

    except (RuntimeError, OSError, LookupError):
        cb.record_failure()
        logger.exception("Error rejecting expense")
        return error_response("Expense rejection failed", status=500)


@rate_limit(requests_per_minute=120)
@require_permission("expenses:read")
async def handle_get_pending_approvals(
    user_id: str = "default",
) -> HandlerResult:
    """
    Get expenses pending approval.

    GET /api/v1/accounting/expenses/pending
    """
    cb = get_expense_circuit_breaker()

    # Check circuit breaker before proceeding
    if not cb.can_proceed():
        logger.warning("Expense circuit breaker is open, rejecting pending approvals request")
        return error_response(
            "Service temporarily unavailable. Please try again later.", status=503
        )

    try:
        tracker = get_expense_tracker()

        expenses = await tracker.get_pending_approval()

        cb.record_success()
        return json_response(
            {
                "expenses": [e.to_dict() for e in expenses],
                "count": len(expenses),
            }
        )

    except (RuntimeError, OSError, LookupError):
        cb.record_failure()
        logger.exception("Error getting pending approvals")
        return error_response("Failed to retrieve pending approvals", status=500)


# =============================================================================
# Categorization
# =============================================================================


@rate_limit(requests_per_minute=30)
@require_permission("expenses:write")
async def handle_categorize_expenses(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Auto-categorize expenses.

    POST /api/v1/accounting/expenses/categorize
    Body: {
        expense_ids: list[str] (optional, categorize all uncategorized if empty)
    }
    """
    cb = get_expense_circuit_breaker()

    # Check circuit breaker before proceeding
    if not cb.can_proceed():
        logger.warning("Expense circuit breaker is open, rejecting categorize request")
        return error_response(
            "Service temporarily unavailable. Please try again later.", status=503
        )

    try:
        tracker = get_expense_tracker()

        expense_ids = data.get("expense_ids")
        # Validate expense_ids if provided
        if expense_ids is not None:
            if not isinstance(expense_ids, list):
                return error_response("expense_ids must be a list", status=400)
            if len(expense_ids) > 1000:
                return error_response("expense_ids must contain 1000 items or less", status=400)
            for eid in expense_ids:
                if not isinstance(eid, str) or len(eid) > 100:
                    return error_response(
                        "each expense_id must be a string of 100 characters or less", status=400
                    )

        results = await tracker.bulk_categorize(expense_ids)

        # Handle both enum values and string values
        categorized = {}
        for eid, cat in results.items():
            if hasattr(cat, "value"):
                categorized[eid] = cat.value
            else:
                categorized[eid] = cat

        cb.record_success()
        return json_response(
            {
                "categorized": categorized,
                "count": len(results),
                "message": f"Categorized {len(results)} expenses",
            }
        )

    except (RuntimeError, OSError, ValueError, TypeError):
        cb.record_failure()
        logger.exception("Error categorizing expenses")
        return error_response("Expense categorization failed", status=500)


# =============================================================================
# QBO Sync
# =============================================================================


@rate_limit(requests_per_minute=10)
@require_permission("finance:write")
async def handle_sync_to_qbo(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Sync expenses to QuickBooks Online.

    POST /api/v1/accounting/expenses/sync
    Body: {
        expense_ids: list[str] (optional, sync all approved if empty)
    }
    """
    cb = get_expense_circuit_breaker()

    # Check circuit breaker before proceeding
    if not cb.can_proceed():
        logger.warning("Expense circuit breaker is open, rejecting QBO sync request")
        return error_response(
            "Service temporarily unavailable. Please try again later.", status=503
        )

    try:
        tracker = get_expense_tracker()

        expense_ids = data.get("expense_ids")
        # Validate expense_ids if provided
        if expense_ids is not None:
            if not isinstance(expense_ids, list):
                return error_response("expense_ids must be a list", status=400)
            if len(expense_ids) > 500:
                return error_response(
                    "expense_ids must contain 500 items or less for sync", status=400
                )
            for eid in expense_ids:
                if not isinstance(eid, str) or len(eid) > 100:
                    return error_response(
                        "each expense_id must be a string of 100 characters or less", status=400
                    )

        result = await tracker.sync_to_qbo(expense_ids=expense_ids)

        # Handle both object with to_dict() and plain dict
        if hasattr(result, "to_dict"):
            result_data = result.to_dict()
            success_count = getattr(result, "success_count", 0)
        else:
            result_data = result
            success_count = result.get("synced", 0)

        cb.record_success()
        return json_response(
            {
                "result": result_data,
                "message": f"Synced {success_count} expenses to QBO",
            }
        )

    except (RuntimeError, OSError, ConnectionError, TimeoutError):
        cb.record_failure()
        logger.exception("Error syncing to QBO")
        return error_response("QBO sync failed", status=500)


# =============================================================================
# Statistics and Export
# =============================================================================


@rate_limit(requests_per_minute=120)
@require_permission("expenses:read")
async def handle_get_expense_stats(
    query_params: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get expense statistics.

    GET /api/v1/accounting/expenses/stats
    Query params:
        start_date: str (ISO format)
        end_date: str (ISO format)
    """
    cb = get_expense_circuit_breaker()

    # Check circuit breaker before proceeding
    if not cb.can_proceed():
        logger.warning("Expense circuit breaker is open, rejecting stats request")
        return error_response(
            "Service temporarily unavailable. Please try again later.", status=503
        )

    try:
        tracker = get_expense_tracker()

        start_date = None
        start_date_str = query_params.get("start_date")
        if start_date_str:
            try:
                start_date = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
            except ValueError:
                logger.debug("Invalid start_date format '%s' in stats, ignoring", start_date_str)

        end_date = None
        end_date_str = query_params.get("end_date")
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            except ValueError:
                logger.debug("Invalid end_date format '%s' in stats, ignoring", end_date_str)

        stats = await tracker.get_stats(start_date=start_date, end_date=end_date)

        # Handle both dict and object with to_dict()
        if hasattr(stats, "to_dict"):
            stats_data = stats.to_dict()
        else:
            stats_data = stats

        cb.record_success()
        return json_response({"stats": stats_data})

    except (RuntimeError, OSError, LookupError):
        cb.record_failure()
        logger.exception("Error getting expense stats")
        return error_response("Failed to retrieve expense statistics", status=500)


@rate_limit(requests_per_minute=30)
@require_permission("admin:audit")
async def handle_export_expenses(
    query_params: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Export expenses to CSV or JSON.

    GET /api/v1/accounting/expenses/export
    Query params:
        format: str (csv or json, default csv)
        start_date: str (ISO format)
        end_date: str (ISO format)
    """
    cb = get_expense_circuit_breaker()

    # Check circuit breaker before proceeding
    if not cb.can_proceed():
        logger.warning("Expense circuit breaker is open, rejecting export request")
        return error_response(
            "Service temporarily unavailable. Please try again later.", status=503
        )

    try:
        tracker = get_expense_tracker()

        export_format = query_params.get("format", "csv")
        if export_format not in ["csv", "json"]:
            return error_response("format must be 'csv' or 'json'", status=400)

        start_date = None
        start_date_str = query_params.get("start_date")
        if start_date_str:
            try:
                start_date = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
            except ValueError:
                logger.debug("Invalid start_date format '%s' in export, ignoring", start_date_str)

        end_date = None
        end_date_str = query_params.get("end_date")
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            except ValueError:
                logger.debug("Invalid end_date format '%s' in export, ignoring", end_date_str)

        data = await tracker.export_expenses(
            format=export_format,
            start_date=start_date,
            end_date=end_date,
        )

        cb.record_success()
        return json_response(
            {
                "data": data,
                "format": export_format,
            }
        )

    except (RuntimeError, OSError, LookupError):
        cb.record_failure()
        logger.exception("Error exporting expenses")
        return error_response("Expense export failed", status=500)


# =============================================================================
# Handler Class for Router Registration
# =============================================================================


class ExpenseHandler(BaseHandler):
    """Handler for expense-related routes.

    Stability: STABLE

    Features:
    - Circuit breaker pattern for fault tolerance
    - Rate limiting on all endpoints
    - Comprehensive input validation
    - RBAC permission checks
    """

    @staticmethod
    def _extract_request_body(query_params: Any) -> dict[str, Any]:
        """Extract request body from query_params for backwards compatibility."""
        return query_params if isinstance(query_params, dict) else {}

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}
        self._circuit_breaker = get_expense_circuit_breaker()

    # RBAC permission keys
    EXPENSE_READ_PERMISSION = "expense.read"
    EXPENSE_WRITE_PERMISSION = "expense.write"
    EXPENSE_APPROVE_PERMISSION = "expense.approve"

    ROUTES = {
        "/api/v1/accounting/expenses/upload": ["POST"],
        "/api/v1/accounting/expenses": ["GET", "POST"],
        "/api/v1/accounting/expenses/categorize": ["POST"],
        "/api/v1/accounting/expenses/sync": ["POST"],
        "/api/v1/accounting/expenses/stats": ["GET"],
        "/api/v1/accounting/expenses/pending": ["GET"],
        "/api/v1/accounting/expenses/export": ["GET"],
    }

    # Contract discovery reads list-shaped metadata; the dynamic-ID canary
    # cannot distinguish this collection from a broad prefix match.
    GET_ROUTES = ["/api/v1/accounting/expenses"]

    # Dynamic routes with path params
    DYNAMIC_ROUTES = {
        "/api/v1/accounting/expenses/{expense_id}": ["GET", "PUT", "DELETE"],
        "/api/v1/accounting/expenses/{expense_id}/approve": ["POST"],
        "/api/v1/accounting/expenses/{expense_id}/reject": ["POST"],
    }

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        if path in self.ROUTES:
            return True
        # Check dynamic routes
        for route_pattern in self.DYNAMIC_ROUTES:
            if self._matches_pattern(path, route_pattern):
                return True
        return False

    def _matches_pattern(self, path: str, pattern: str) -> bool:
        """Check if path matches a route pattern with {param}."""
        pattern_parts = pattern.split("/")
        path_parts = path.split("/")

        if len(pattern_parts) != len(path_parts):
            return False

        for pattern_part, path_part in zip(pattern_parts, path_parts):
            if pattern_part.startswith("{") and pattern_part.endswith("}"):
                continue
            if pattern_part != path_part:
                return False

        return True

    def _extract_expense_id(self, path: str) -> str | None:
        """Extract expense_id from path."""
        parts = path.split("/")
        # /api/v1/accounting/expenses/{expense_id}/...
        # parts[0]="", [1]="api", [2]="v1", [3]="accounting", [4]="expenses", [5]=expense_id
        if len(parts) >= 6:
            return parts[5]
        return None

    def _check_auth(self, handler: Any) -> HandlerResult | None:
        """Check authentication and return error response if not authenticated."""
        try:
            from aragora.billing.jwt_auth import extract_user_from_request

            user_ctx = extract_user_from_request(handler, None)
            if not user_ctx or not user_ctx.is_authenticated:
                return error_response("Authentication required", status=401)
            return None
        except (ImportError, AttributeError, ValueError) as e:
            logger.debug("Auth check failed: %s", e)
            return error_response("Authentication required", status=401)

    def _check_permission(self, handler: Any, permission: str) -> HandlerResult | None:
        """Check RBAC permission and return error response if denied."""
        try:
            from aragora.billing.jwt_auth import extract_user_from_request
            from aragora.rbac.checker import get_permission_checker
            from aragora.rbac.models import AuthorizationContext

            user_ctx = extract_user_from_request(handler, None)
            if not user_ctx or not user_ctx.is_authenticated:
                return error_response("Authentication required", status=401)

            auth_ctx = AuthorizationContext(
                user_id=user_ctx.user_id,
                user_email=user_ctx.email,
                org_id=user_ctx.org_id,
                workspace_id=None,
                roles={user_ctx.role} if user_ctx.role else {"member"},
            )
            checker = get_permission_checker()
            decision = checker.check_permission(auth_ctx, permission)
            if not decision.allowed:
                logger.warning("Permission denied: %s", permission)
                return error_response("Permission denied", status=403)
            return None
        except (ImportError, AttributeError, ValueError) as e:
            logger.debug("Permission check failed: %s", e)
            return error_response("Authentication required", status=401)

    async def handle(  # type: ignore[override]
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> MaybeAsyncHandlerResult:
        """Handle GET requests."""
        # Check authentication for all GET requests
        if handler:
            auth_error = self._check_auth(handler)
            if auth_error:
                return auth_error

        if path == "/api/v1/accounting/expenses":
            return await handle_list_expenses(query_params)

        if path == "/api/v1/accounting/expenses/stats":
            return await handle_get_expense_stats(query_params)

        if path == "/api/v1/accounting/expenses/pending":
            return await handle_get_pending_approvals()

        if path == "/api/v1/accounting/expenses/export":
            return await handle_export_expenses(query_params)

        # Dynamic: /api/v1/accounting/expenses/{expense_id}
        expense_id = self._extract_expense_id(path)
        if expense_id and "/approve" not in path and "/reject" not in path:
            return await handle_get_expense(expense_id)

        return error_response("Route not found", status=404)

    @require_permission("finance:read")
    async def handle_get(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any | None = None,
    ) -> MaybeAsyncHandlerResult:
        """Compatibility wrapper for GET handlers."""
        return await self.handle(path, query_params, handler)

    @handle_errors("expense creation")
    async def handle_post(  # type: ignore[override]
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any = None,
    ) -> MaybeAsyncHandlerResult:
        """Handle POST requests."""
        # Extract data from query_params for backwards compatibility
        data = self._extract_request_body(query_params)

        # Check write permission for all POST requests
        if handler:
            # Approve/reject need special permission
            if "/approve" in path or "/reject" in path:
                perm_error = self._check_permission(handler, self.EXPENSE_APPROVE_PERMISSION)
            else:
                perm_error = self._check_permission(handler, self.EXPENSE_WRITE_PERMISSION)
            if perm_error:
                return perm_error

        if path == "/api/v1/accounting/expenses/upload":
            return await handle_upload_receipt(data)

        if path == "/api/v1/accounting/expenses":
            return await handle_create_expense(data)

        if path == "/api/v1/accounting/expenses/categorize":
            return await handle_categorize_expenses(data)

        if path == "/api/v1/accounting/expenses/sync":
            return await handle_sync_to_qbo(data)

        # Dynamic routes
        expense_id = self._extract_expense_id(path)
        if expense_id:
            if "/approve" in path:
                return await handle_approve_expense(expense_id)
            if "/reject" in path:
                return await handle_reject_expense(expense_id, data)

        return error_response("Route not found", status=404)

    @handle_errors("expense update")
    async def handle_put(  # type: ignore[override]
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any = None,
    ) -> MaybeAsyncHandlerResult:
        """Handle PUT requests."""
        # Extract data from query_params for backwards compatibility
        data = self._extract_request_body(query_params)

        # Check write permission for all PUT requests
        if handler:
            perm_error = self._check_permission(handler, self.EXPENSE_WRITE_PERMISSION)
            if perm_error:
                return perm_error

        expense_id = self._extract_expense_id(path)
        if expense_id:
            return await handle_update_expense(expense_id, data)

        return error_response("Route not found", status=404)

    @handle_errors("expense deletion")
    async def handle_delete(  # type: ignore[override]
        self,
        path: str,
        query_params: dict[str, Any] | None = None,
        handler: Any = None,
    ) -> MaybeAsyncHandlerResult:
        """Handle DELETE requests."""
        _ = query_params  # retained for signature compatibility
        # Note: handle_delete_expense already has @require_permission("admin:audit")
        # But we also check at handler level for consistency
        if handler:
            perm_error = self._check_permission(handler, "admin:audit")
            if perm_error:
                return perm_error

        expense_id = self._extract_expense_id(path)
        if expense_id:
            return await handle_delete_expense(expense_id)

        return error_response("Route not found", status=404)
