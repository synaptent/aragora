"""
MFA Compliance Dashboard endpoint handler.

Endpoints:
- GET /api/v1/admin/mfa-compliance - Aggregate MFA status for all admin users

SOC 2 Control: CC5-01 - Enforce MFA for administrative access.
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.auth.mfa_enforcement import DEFAULT_MFA_REQUIRED_ROLES

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from aragora.rbac.decorators import require_permission

logger = logging.getLogger(__name__)


def _enumerate_users(user_store: Any) -> list[Any]:
    """Return all users from the supported store interfaces."""
    list_all_fn = getattr(user_store, "list_all_users", None)
    if callable(list_all_fn):
        limit = 1000
        offset = 0
        users: list[Any] = []
        while True:
            batch_result = list_all_fn(limit=limit, offset=offset)
            if isinstance(batch_result, tuple) and len(batch_result) == 2:
                batch, total = batch_result
            else:
                batch, total = batch_result, None
            batch_users = list(batch)
            users.extend(batch_users)
            if not batch_users:
                break
            if total is not None and len(users) >= int(total):
                break
            if total is None and len(batch_users) < limit:
                break
            offset += limit
        return users

    list_fn = getattr(user_store, "list_users", None) or getattr(user_store, "get_all_users", None)
    if list_fn is None:
        raise AttributeError("User listing not supported")

    result = list_fn()
    if isinstance(result, tuple) and len(result) == 2:
        result, _ = result
    return list(result)


class MFAComplianceHandler(BaseHandler):
    """Handler for MFA compliance dashboard endpoints."""

    ROUTES = [
        "/api/v1/admin/mfa-compliance",
    ]

    def __init__(self, ctx: dict[str, Any] | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES

    @handle_errors("mfa compliance GET")
    @require_permission("admin:security:read")
    def handle(
        self, path: str, query_params: dict[str, Any], handler: Any, user: Any = None
    ) -> HandlerResult | None:
        """Handle GET requests for MFA compliance endpoint."""
        if path == "/api/v1/admin/mfa-compliance":
            return self._get_compliance(handler)
        return None

    def _get_compliance(self, handler: Any) -> HandlerResult:
        """Aggregate MFA status for all admin users.

        Returns compliance summary with per-admin details.
        """
        user_store = self.ctx.get("user_store")
        if not user_store:
            return error_response("User store not available", 503)

        try:
            all_users = _enumerate_users(user_store)
        except AttributeError:
            return error_response("User listing not supported", 501)
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.warning("Failed to list users for MFA compliance: %s", e)
            return error_response("Failed to retrieve user list", 500)

        # Filter to admin users
        admin_users = []
        for u in all_users:
            role = getattr(u, "role", None)
            if role and role in DEFAULT_MFA_REQUIRED_ROLES:
                admin_users.append(u)

        total_admins = len(admin_users)
        mfa_enabled = 0
        mfa_disabled = 0
        in_grace_period = 0
        details = []

        for u in admin_users:
            enabled = bool(getattr(u, "mfa_enabled", False))
            grace = bool(getattr(u, "mfa_grace_period_started_at", None))
            if enabled:
                mfa_enabled += 1
                status = "compliant"
            elif grace:
                in_grace_period += 1
                status = "grace_period"
            else:
                mfa_disabled += 1
                status = "non_compliant"

            details.append(
                {
                    "user_id": getattr(u, "id", "unknown"),
                    "role": getattr(u, "role", "unknown"),
                    "mfa_enabled": enabled,
                    "status": status,
                }
            )

        compliance_rate = (mfa_enabled / total_admins * 100.0) if total_admins > 0 else 100.0

        return json_response(
            {
                "data": {
                    "total_admins": total_admins,
                    "mfa_enabled": mfa_enabled,
                    "mfa_disabled": mfa_disabled,
                    "in_grace_period": in_grace_period,
                    "compliance_rate": round(compliance_rate, 2),
                    "details": details,
                }
            }
        )


__all__ = ["MFAComplianceHandler"]
