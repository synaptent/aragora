"""
Legal Hold Management Handler.

Provides legal hold operations including:
- Create legal holds
- List legal holds
- Release legal holds
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
)
from aragora.rbac.decorators import require_permission
from aragora.observability.metrics import track_handler
from aragora.storage.audit_store import get_audit_store as _base_get_audit_store
from aragora.privacy.deletion import get_legal_hold_manager as _base_get_legal_hold_manager

logger = logging.getLogger(__name__)


def get_legal_hold_manager():  # type: ignore[override]
    """Indirection for tests that patch compliance_handler.get_legal_hold_manager."""
    try:
        from aragora.server.handlers.compliance import handler as compat

        return compat.get_legal_hold_manager()
    except (ImportError, AttributeError):
        return _base_get_legal_hold_manager()


def get_audit_store():  # type: ignore[override]
    """Indirection for tests that patch compliance_handler.get_audit_store."""
    try:
        from aragora.server.handlers.compliance import handler as compat

        return compat.get_audit_store()
    except (ImportError, AttributeError):
        return _base_get_audit_store()


def _extract_user_id_from_headers(headers: dict[str, str] | None) -> str:
    """
    Extract user ID from Authorization header.

    Falls back to 'compliance_api' if no valid auth is present.
    This ensures audit trails identify the actual user making compliance requests.
    """
    if not headers:
        return "compliance_api"

    auth_header = headers.get("Authorization", "") or headers.get("authorization", "")
    if not auth_header or not auth_header.startswith("Bearer "):
        return "compliance_api"

    token = auth_header[7:]

    # Check if it's an API key (ara_xxx format)
    if token.startswith("ara_"):
        # API keys don't contain user info directly, use key prefix as identifier
        return f"api_key:{token[:12]}..."

    # Try to decode JWT to get user_id
    try:
        from aragora.billing.auth.tokens import validate_access_token

        payload = validate_access_token(token)
        if payload and payload.user_id:
            return payload.user_id
    except (ImportError, ValueError, AttributeError):
        pass

    return "compliance_api"


class LegalHoldMixin:
    """Mixin providing legal hold management methods."""

    @require_permission("compliance:legal")
    async def _list_legal_holds(self, query_params: dict[str, str]) -> HandlerResult:
        """
        List legal holds.

        Query params:
            active_only: If true, only show active holds (default: true)
        """
        active_only = query_params.get("active_only", "true").lower() == "true"

        try:
            hold_manager = get_legal_hold_manager()

            if active_only:
                holds = hold_manager.get_active_holds()
            else:
                # Get all holds from the store
                holds = list(hold_manager._store._holds.values())

            return json_response(
                {
                    "legal_holds": [h.to_dict() for h in holds],
                    "count": len(holds),
                    "filters": {"active_only": active_only},
                }
            )

        except (RuntimeError, AttributeError, KeyError) as e:
            logger.exception("Error listing legal holds: %s", e)
            return error_response("Failed to list legal holds", 500)

    @track_handler("compliance/legal-hold-create", method="POST")
    @require_permission("compliance:legal")
    async def _create_legal_hold(
        self,
        body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> HandlerResult:
        """
        Create a new legal hold.

        Body:
            user_ids: List of user IDs to place on hold (required)
            reason: Reason for the hold (required)
            case_reference: External case reference (optional)
            expires_at: Expiration date ISO string (optional)
        """
        user_ids = body.get("user_ids", [])
        reason = body.get("reason")
        case_reference = body.get("case_reference")
        expires_at_str = body.get("expires_at")

        if not user_ids:
            return error_response("user_ids is required", 400)
        if not reason:
            return error_response("reason is required", 400)

        expires_at = None
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            except ValueError:
                return error_response("Invalid expires_at format", 400)

        # Extract authenticated user from request headers for audit trail
        created_by = _extract_user_id_from_headers(headers)

        try:
            hold_manager = get_legal_hold_manager()
            hold = hold_manager.create_hold(
                user_ids=user_ids,
                reason=reason,
                created_by=created_by,
                case_reference=case_reference,
                expires_at=expires_at,
            )

            # Log the hold creation
            try:
                store = get_audit_store()
                store.log_event(
                    action="legal_hold_created",
                    resource_type="legal_hold",
                    resource_id=hold.hold_id,
                    metadata={
                        "user_ids": user_ids,
                        "reason": reason,
                        "case_reference": case_reference,
                    },
                )
            except (RuntimeError, OSError, ValueError) as log_err:
                logger.warning("Failed to log legal hold creation: %s", log_err)

            return json_response(
                {
                    "message": "Legal hold created successfully",
                    "legal_hold": hold.to_dict(),
                },
                status=201,
            )

        except (RuntimeError, ValueError, TypeError) as e:
            logger.exception("Error creating legal hold: %s", e)
            return error_response("Legal hold creation failed", 500)

    @require_permission("compliance:legal")
    async def _release_legal_hold(
        self,
        hold_id: str,
        body: dict[str, Any],
    ) -> HandlerResult:
        """
        Release a legal hold.

        Path params:
            hold_id: The legal hold ID to release

        Body:
            released_by: Who is releasing the hold (optional)
        """
        released_by = body.get("released_by", "compliance_api")

        try:
            hold_manager = get_legal_hold_manager()
            released = hold_manager.release_hold(hold_id, released_by)

            if not released:
                return error_response("Legal hold not found", 404)

            # Log the release
            try:
                store = get_audit_store()
                store.log_event(
                    action="legal_hold_released",
                    resource_type="legal_hold",
                    resource_id=hold_id,
                    metadata={
                        "released_by": released_by,
                        "released_at": released.released_at.isoformat()
                        if released.released_at
                        else None,
                        "user_ids": released.user_ids,
                    },
                )
            except (RuntimeError, OSError, ValueError) as log_err:
                logger.warning("Failed to log legal hold release: %s", log_err)

            return json_response(
                {
                    "message": "Legal hold released successfully",
                    "legal_hold": released.to_dict(),
                }
            )

        except (RuntimeError, ValueError, KeyError) as e:
            logger.exception("Error releasing legal hold: %s", e)
            return error_response("Legal hold release failed", 500)
