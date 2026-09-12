"""
GDPR Self-Service Deletion Handler.

Provides self-service endpoints for users to manage their data deletion requests
in compliance with GDPR Article 17 (Right to Erasure).

Endpoints:
- POST   /api/v1/users/self/deletion-request  (schedule with grace period)
- GET    /api/v1/users/self/deletion-request   (check status)
- DELETE /api/v1/users/self/deletion-request   (cancel during grace period)
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from aragora.server.handlers.utils.decorators import require_permission

logger = logging.getLogger(__name__)

# Default grace period in days before data is actually deleted
DEFAULT_GRACE_PERIOD_DAYS = 30


def _get_scheduler():
    """Get the GDPR deletion scheduler (lazy import to avoid circular deps)."""
    from aragora.privacy.deletion import get_deletion_scheduler

    return get_deletion_scheduler()


def _get_user_id_from_handler(handler: Any) -> str | None:
    """Extract user ID from the authenticated request handler."""
    try:
        from aragora.billing.jwt_auth import extract_user_from_request

        auth_ctx = extract_user_from_request(handler, None)
        if auth_ctx.is_authenticated:
            return auth_ctx.user_id
    except (ImportError, AttributeError):
        pass
    return None


class GDPRDeletionHandler(BaseHandler):
    """Handler for GDPR self-service deletion endpoints."""

    ROUTES = [
        "/api/v1/users/self/deletion-request",
    ]

    def __init__(self, ctx: dict[str, Any] | None = None, **kwargs: Any):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        return path in self.ROUTES

    @handle_errors("get deletion request status")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        if path != "/api/v1/users/self/deletion-request":
            return None

        user_id = _get_user_id_from_handler(handler)
        if not user_id:
            return error_response("Authentication required", 401)

        scheduler = _get_scheduler()
        requests = scheduler.store.get_requests_for_user(user_id)

        if not requests:
            return json_response(
                {
                    "has_pending_request": False,
                    "requests": [],
                }
            )

        return json_response(
            {
                "has_pending_request": any(
                    r.status.value in ("pending", "in_progress") for r in requests
                ),
                "requests": [r.to_dict() for r in requests],
            }
        )

    @require_permission("privacy:request_deletion")
    @handle_errors("schedule deletion request")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        if path != "/api/v1/users/self/deletion-request":
            return None

        user_id = _get_user_id_from_handler(handler)
        if not user_id:
            return error_response("Authentication required", 401)

        body = self.read_json_body(handler) or {}
        reason = body.get("reason", "User-initiated deletion request")
        grace_period = body.get("grace_period_days", DEFAULT_GRACE_PERIOD_DAYS)

        if not isinstance(grace_period, int) or grace_period < 1:
            return error_response("grace_period_days must be a positive integer", 400)

        if grace_period > 365:
            return error_response("grace_period_days cannot exceed 365", 400)

        scheduler = _get_scheduler()

        # Check for existing pending request
        existing = scheduler.store.get_requests_for_user(user_id)
        pending = [r for r in existing if r.status.value in ("pending", "in_progress")]
        if pending:
            return error_response(
                "A deletion request is already pending for this account",
                409,
            )

        try:
            request = scheduler.schedule_deletion(
                user_id=user_id,
                grace_period_days=grace_period,
                reason=reason,
            )
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Conflict", 409)

        logger.info(
            "Deletion request scheduled for user %s (request_id=%s, grace=%d days)",
            user_id,
            request.request_id,
            grace_period,
        )

        return json_response(request.to_dict(), status=201)

    @require_permission("privacy:cancel_deletion")
    @handle_errors("cancel deletion request")
    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        if path != "/api/v1/users/self/deletion-request":
            return None

        user_id = _get_user_id_from_handler(handler)
        if not user_id:
            return error_response("Authentication required", 401)

        body = self.read_json_body(handler) or {}
        reason = body.get("reason", "User cancelled deletion request")

        scheduler = _get_scheduler()
        requests = scheduler.store.get_requests_for_user(user_id)
        pending = [r for r in requests if r.status.value == "pending"]

        if not pending:
            return error_response("No pending deletion request found", 404)

        try:
            cancelled = scheduler.cancel_deletion(
                request_id=pending[0].request_id,
                reason=reason,
            )
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Conflict", 409)

        if not cancelled:
            return error_response("Failed to cancel deletion request", 500)

        logger.info(
            "Deletion request cancelled for user %s (request_id=%s)",
            user_id,
            cancelled.request_id,
        )

        return json_response(cancelled.to_dict())


__all__ = ["GDPRDeletionHandler"]
