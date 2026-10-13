"""
FastAPI v2 routes for Inbox Command Center.

Migrated from aragora.server.handlers.inbox_command.InboxCommandHandler.
Provides endpoints for prioritized inbox, quick actions, bulk operations,
sender profiles, daily digest, and AI re-prioritization.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["Inbox"])


# ---------------------------------------------------------------------------
# Security constants (mirrored from legacy handler)
# ---------------------------------------------------------------------------

ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        "archive",
        "snooze",
        "reply",
        "forward",
        "spam",
        "mark_important",
        "mark_vip",
        "block",
        "delete",
    }
)

ALLOWED_BULK_FILTERS: frozenset[str] = frozenset({"low", "deferred", "spam", "read", "all"})

ALLOWED_PRIORITY_FILTERS: frozenset[str] = frozenset({"critical", "high", "medium", "low", "defer"})

ALLOWED_FORCE_TIERS: frozenset[str] = frozenset(
    {"tier_1_rules", "tier_2_lightweight", "tier_3_debate"}
)

MAX_EMAIL_ID_LENGTH = 256
MAX_EMAIL_IDS_PER_REQUEST = 200
MAX_EMAIL_ADDRESS_LENGTH = 320

_EMAIL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
_EMAIL_ADDRESS_PATTERN = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~\-]+@[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
)


def _validate_email_id(email_id: Any) -> str | None:
    if not isinstance(email_id, str):
        return None
    email_id = email_id.strip()
    if not email_id or len(email_id) > MAX_EMAIL_ID_LENGTH:
        return None
    if not _EMAIL_ID_PATTERN.match(email_id):
        return None
    return email_id


def _validate_email_address(address: Any) -> str | None:
    if not isinstance(address, str):
        return None
    address = address.strip()
    if not address or len(address) > MAX_EMAIL_ADDRESS_LENGTH:
        return None
    if not _EMAIL_ADDRESS_PATTERN.match(address):
        return None
    return address


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class QuickActionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: str
    emailIds: list[str]
    params: dict[str, Any] = {}


class BulkActionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: str
    filter: str
    params: dict[str, Any] = {}


class ReprioritizeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    emailIds: list[str] | None = None
    force_tier: str | None = None


# ---------------------------------------------------------------------------
# Inbox handler singleton
# ---------------------------------------------------------------------------


def _get_inbox_handler():
    """Get or create an InboxCommandHandler instance."""
    try:
        from aragora.server.handlers.inbox.inbox_command import InboxCommandHandler

        return InboxCommandHandler()
    except (ImportError, TypeError, RuntimeError) as e:
        logger.warning("InboxCommandHandler not available: %s", e)
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/inbox/command")
async def get_inbox(
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0, le=100000),
    priority: str | None = Query(default=None),
    unread_only: bool = Query(default=False),
):
    """Fetch prioritized inbox with stats."""
    if priority is not None:
        priority = priority.strip().lower()
        if priority not in ALLOWED_PRIORITY_FILTERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid priority filter. Allowed: {', '.join(sorted(ALLOWED_PRIORITY_FILTERS))}",
            )

    handler = _get_inbox_handler()
    if not handler:
        raise HTTPException(status_code=503, detail="Inbox service not available")

    try:
        emails = await handler._fetch_prioritized_emails(
            limit=limit,
            offset=offset,
            priority_filter=priority,
            unread_only=unread_only,
        )
        stats = await handler._calculate_inbox_stats(emails)

        return {
            "data": {
                "emails": emails,
                "total": stats["total"],
                "stats": stats,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        }
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.error("Failed to fetch inbox: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch inbox")


@router.post("/inbox/actions")
async def quick_action(body: QuickActionRequest):
    """Execute quick action on email(s)."""
    action = body.action.strip().lower()
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{action}'. Allowed: {', '.join(sorted(ALLOWED_ACTIONS))}",
        )

    if not body.emailIds:
        raise HTTPException(status_code=400, detail="emailIds must be non-empty")

    if len(body.emailIds) > MAX_EMAIL_IDS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"emailIds exceeds maximum of {MAX_EMAIL_IDS_PER_REQUEST}",
        )

    email_ids: list[str] = []
    for raw_id in body.emailIds:
        validated = _validate_email_id(raw_id)
        if validated is None:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid email ID: must be alphanumeric (max {MAX_EMAIL_ID_LENGTH} chars)",
            )
        email_ids.append(validated)

    handler = _get_inbox_handler()
    if not handler:
        raise HTTPException(status_code=503, detail="Inbox service not available")

    try:
        params = handler._sanitize_action_params(action, body.params)
        results = await handler._execute_action(action, email_ids, params)

        return {
            "data": {
                "action": action,
                "processed": len(email_ids),
                "results": results,
            }
        }
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.error("Failed to execute action: %s", e)
        raise HTTPException(status_code=500, detail="Failed to execute action")


@router.post("/inbox/bulk-actions")
async def bulk_action(body: BulkActionRequest):
    """Execute bulk action based on filter."""
    action = body.action.strip().lower()
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{action}'. Allowed: {', '.join(sorted(ALLOWED_ACTIONS))}",
        )

    filter_type = body.filter.strip().lower()
    if filter_type not in ALLOWED_BULK_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid filter '{filter_type}'. Allowed: {', '.join(sorted(ALLOWED_BULK_FILTERS))}",
        )

    handler = _get_inbox_handler()
    if not handler:
        raise HTTPException(status_code=503, detail="Inbox service not available")

    try:
        email_ids = await handler._get_emails_by_filter(filter_type)

        if not email_ids:
            return {
                "data": {
                    "action": action,
                    "processed": 0,
                    "message": "No emails matched the filter",
                }
            }

        params = handler._sanitize_action_params(action, body.params)
        results = await handler._execute_action(action, email_ids, params)

        return {
            "data": {
                "action": action,
                "filter": filter_type,
                "processed": len(email_ids),
                "results": results,
            }
        }
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.error("Failed to execute bulk action: %s", e)
        raise HTTPException(status_code=500, detail="Failed to execute bulk action")


@router.get("/inbox/sender-profile")
async def get_sender_profile(email: str = Query(...)):
    """Get profile information for a sender."""
    validated = _validate_email_address(email)
    if validated is None:
        raise HTTPException(status_code=400, detail="Invalid email address format")

    handler = _get_inbox_handler()
    if not handler:
        raise HTTPException(status_code=503, detail="Inbox service not available")

    try:
        profile = await handler._get_sender_profile(validated)
        return {"data": {"profile": profile}}
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.error("Failed to get sender profile: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get sender profile")


@router.get("/inbox/daily-digest")
async def get_daily_digest():
    """Get daily digest statistics."""
    handler = _get_inbox_handler()
    if not handler:
        raise HTTPException(status_code=503, detail="Inbox service not available")

    try:
        digest = await handler._calculate_daily_digest()
        return {"data": {"digest": digest}}
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.error("Failed to get daily digest: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get daily digest")


@router.post("/inbox/reprioritize")
async def reprioritize(body: ReprioritizeRequest):
    """Trigger AI re-prioritization of inbox."""
    email_ids: list[str] | None = None
    if body.emailIds is not None:
        if len(body.emailIds) > MAX_EMAIL_IDS_PER_REQUEST:
            raise HTTPException(
                status_code=400,
                detail=f"emailIds exceeds maximum of {MAX_EMAIL_IDS_PER_REQUEST}",
            )
        email_ids = []
        for raw_id in body.emailIds:
            validated = _validate_email_id(raw_id)
            if validated is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid email ID: must be alphanumeric (max {MAX_EMAIL_ID_LENGTH} chars)",
                )
            email_ids.append(validated)

    force_tier = body.force_tier
    if force_tier is not None:
        force_tier = force_tier.strip().lower()
        if force_tier not in ALLOWED_FORCE_TIERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid force_tier. Allowed: {', '.join(sorted(ALLOWED_FORCE_TIERS))}",
            )

    handler = _get_inbox_handler()
    if not handler:
        raise HTTPException(status_code=503, detail="Inbox service not available")

    try:
        result = await handler._reprioritize_emails(email_ids, force_tier)
        return {
            "data": {
                "reprioritized": result["count"],
                "changes": result["changes"],
                "tier_used": result.get("tier_used"),
            }
        }
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.error("Failed to reprioritize: %s", e)
        raise HTTPException(status_code=500, detail="Failed to reprioritize")
