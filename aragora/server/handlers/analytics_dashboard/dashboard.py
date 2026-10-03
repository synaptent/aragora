"""
HTTP API Handlers for Dashboard.

Provides REST APIs for the main dashboard:
- Overview stats and metrics
- Quick actions
- Recent activity
- Inbox summary
- Team status

Endpoints:
- GET /api/v1/dashboard - Get dashboard overview
- GET /api/v1/dashboard/stats - Get detailed stats
- GET /api/v1/dashboard/activity - Get recent activity
- GET /api/v1/dashboard/inbox-summary - Get inbox summary
- GET /api/v1/dashboard/quick-actions - Get available quick actions
- POST /api/v1/dashboard/quick-actions/{action} - Execute quick action
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.rbac.models import AuthorizationContext
from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    success_response,
)
from aragora.utils.cache import TTLCache

logger = logging.getLogger(__name__)

# Cache TTL (30 seconds for real-time feel)
CACHE_TTL = 30

# Bounded LRU cache for dashboard data (max 1000 entries to prevent memory leaks)
_dashboard_cache: TTLCache[dict[str, Any]] = TTLCache(maxsize=1000, ttl_seconds=CACHE_TTL)


def _get_cached_data(user_id: str, key: str) -> dict[str, Any] | None:
    """Get cached dashboard data if not expired."""
    cache_key = f"{user_id}:{key}"
    return _dashboard_cache.get(cache_key)


def _set_cached_data(user_id: str, key: str, data: dict[str, Any]) -> None:
    """Cache dashboard data."""
    cache_key = f"{user_id}:{key}"
    _dashboard_cache.set(cache_key, data)


# =============================================================================
# Dashboard Overview
# =============================================================================


@require_permission("dashboard:read")
async def handle_get_dashboard(
    context: AuthorizationContext,
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get dashboard overview.

    GET /api/v1/dashboard
    Query params:
        refresh: bool (optional) - Force refresh cache
    """
    try:
        force_refresh = data.get("refresh", False)
        if isinstance(force_refresh, str):
            force_refresh = force_refresh.lower() == "true"

        # Check cache
        if not force_refresh:
            cached = _get_cached_data(user_id, "overview")
            if cached:
                return success_response(cached)

        now = datetime.now(timezone.utc)

        # Build overview data
        overview = {
            "user_id": user_id,
            "generated_at": now.isoformat(),
            # Inbox Stats
            "inbox": {
                "total_unread": 42,
                "high_priority": 7,
                "needs_response": 12,
                "snoozed": 5,
                "assigned_to_me": 8,
            },
            # Today's Activity
            "today": {
                "emails_received": 28,
                "emails_sent": 15,
                "emails_archived": 23,
                "meetings_scheduled": 3,
                "action_items_completed": 5,
                "action_items_created": 8,
            },
            # Team Stats (for team inbox)
            "team": {
                "active_members": 5,
                "open_tickets": 34,
                "avg_response_time_mins": 45,
                "resolved_today": 12,
            },
            # AI Stats
            "ai": {
                "emails_categorized": 156,
                "auto_responses_suggested": 23,
                "priority_predictions": 89,
                "debates_run": 3,
            },
            # Quick Stats Cards
            "cards": [
                {
                    "id": "unread",
                    "title": "Unread Emails",
                    "value": "42",
                    "change": "-8",
                    "change_type": "decrease",
                    "icon": "mail",
                },
                {
                    "id": "high_priority",
                    "title": "High Priority",
                    "value": "7",
                    "change": "+2",
                    "change_type": "increase",
                    "icon": "alert",
                },
                {
                    "id": "response_time",
                    "title": "Avg Response",
                    "value": "45m",
                    "change": "-12m",
                    "change_type": "decrease",
                    "icon": "clock",
                },
                {
                    "id": "resolved",
                    "title": "Resolved Today",
                    "value": "12",
                    "change": "+5",
                    "change_type": "increase",
                    "icon": "check",
                },
            ],
        }

        _set_cached_data(user_id, "overview", overview)

        return success_response(overview)

    except (TypeError, ValueError, KeyError, AttributeError):
        logger.exception("Failed to get dashboard")
        return error_response("Dashboard loading failed", status=500)


# =============================================================================
# Detailed Stats
# =============================================================================


@require_permission("dashboard:read")
async def handle_get_stats(
    context: AuthorizationContext,
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get detailed statistics.

    GET /api/v1/dashboard/stats
    Query params:
        period: str (optional - day, week, month, default week)
    """
    try:
        period = data.get("period", "week")

        if period not in {"day", "week", "month"}:
            return error_response("Invalid period. Use: day, week, month", status=400)

        now = datetime.now(timezone.utc)

        # Generate time-series data based on period
        if period == "day":
            labels = [f"{i:02d}:00" for i in range(24)]
            data_points = 24
        elif period == "week":
            labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            data_points = 7
        else:  # month
            labels = [str(i + 1) for i in range(30)]
            data_points = 30

        # Generate sample data
        stats = {
            "period": period,
            "generated_at": now.isoformat(),
            # Email volume over time
            "email_volume": {
                "labels": labels,
                "received": [random.randint(5, 30) for _ in range(data_points)],  # noqa: S311 -- mock data generation
                "sent": [random.randint(2, 15) for _ in range(data_points)],  # noqa: S311 -- mock data generation
                "archived": [random.randint(10, 40) for _ in range(data_points)],  # noqa: S311 -- mock data generation
            },
            # Response time distribution
            "response_time": {
                "labels": ["<15m", "15-30m", "30-60m", "1-2h", "2-4h", ">4h"],
                "values": [45, 32, 18, 12, 8, 5],
            },
            # Priority distribution
            "priority_distribution": {
                "labels": ["Critical", "High", "Medium", "Low"],
                "values": [5, 18, 42, 35],
            },
            # Category breakdown
            "categories": {
                "labels": ["Work", "Personal", "Newsletter", "Promotional", "Other"],
                "values": [45, 12, 20, 15, 8],
            },
            # Team performance
            "team_performance": [
                {"name": "Alice", "resolved": 28, "avg_response": 32},
                {"name": "Bob", "resolved": 24, "avg_response": 45},
                {"name": "Charlie", "resolved": 31, "avg_response": 28},
                {"name": "Diana", "resolved": 19, "avg_response": 52},
            ],
            # Top senders
            "top_senders": [
                {"email": "ceo@company.com", "count": 12, "priority": "high"},
                {"email": "team@slack.com", "count": 45, "priority": "medium"},
                {"email": "support@vendor.com", "count": 8, "priority": "medium"},
                {"email": "newsletter@news.com", "count": 30, "priority": "low"},
            ],
            # Summary metrics
            "summary": {
                "total_emails": 342,
                "avg_daily_emails": 49,
                "response_rate": 0.87,
                "avg_response_time_mins": 45,
                "ai_accuracy": 0.94,
            },
        }

        return success_response(stats)

    except (TypeError, ValueError, KeyError):
        logger.exception("Failed to get stats")
        return error_response("Statistics retrieval failed", status=500)


# =============================================================================
# Activity Feed
# =============================================================================


@require_permission("dashboard:read")
async def handle_get_activity(
    context: AuthorizationContext,
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get recent activity.

    GET /api/v1/dashboard/activity
    Query params:
        limit: int (optional, default 20)
        offset: int (optional, default 0)
        type: str (optional) - Filter by activity type
    """
    try:
        limit = max(1, min(int(data.get("limit", 20)), 100))
        offset = max(0, int(data.get("offset", 0)))
        activity_type = data.get("type")

        now = datetime.now(timezone.utc)

        # Generate sample activity items
        activities = [
            {
                "id": "act_001",
                "type": "email_received",
                "title": "New email from CEO",
                "description": "Q4 Planning Discussion",
                "timestamp": (now - timedelta(minutes=5)).isoformat(),
                "priority": "high",
                "icon": "mail",
            },
            {
                "id": "act_002",
                "type": "email_sent",
                "title": "Reply sent",
                "description": "Re: Project Update",
                "timestamp": (now - timedelta(minutes=15)).isoformat(),
                "priority": "medium",
                "icon": "send",
            },
            {
                "id": "act_003",
                "type": "action_completed",
                "title": "Action item completed",
                "description": "Review budget proposal",
                "timestamp": (now - timedelta(minutes=30)).isoformat(),
                "priority": "medium",
                "icon": "check",
            },
            {
                "id": "act_004",
                "type": "mention",
                "title": "@mentioned by Alice",
                "description": "In: Client meeting notes",
                "timestamp": (now - timedelta(hours=1)).isoformat(),
                "priority": "high",
                "icon": "at",
            },
            {
                "id": "act_005",
                "type": "assignment",
                "title": "Ticket assigned to you",
                "description": "Support request #1234",
                "timestamp": (now - timedelta(hours=2)).isoformat(),
                "priority": "medium",
                "icon": "user",
            },
            {
                "id": "act_006",
                "type": "email_archived",
                "title": "Batch archived",
                "description": "12 emails archived",
                "timestamp": (now - timedelta(hours=3)).isoformat(),
                "priority": "low",
                "icon": "archive",
            },
            {
                "id": "act_007",
                "type": "meeting_scheduled",
                "title": "Meeting scheduled",
                "description": "Team sync at 3pm",
                "timestamp": (now - timedelta(hours=4)).isoformat(),
                "priority": "medium",
                "icon": "calendar",
            },
            {
                "id": "act_008",
                "type": "ai_suggestion",
                "title": "AI suggestion",
                "description": "3 emails ready for auto-response",
                "timestamp": (now - timedelta(hours=5)).isoformat(),
                "priority": "low",
                "icon": "sparkles",
            },
        ]

        # Filter by type if specified
        if activity_type:
            activities = [a for a in activities if a["type"] == activity_type]

        # Apply pagination
        total = len(activities)
        activities = activities[offset : offset + limit]

        return success_response(
            {
                "activities": activities,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total,
            }
        )

    except (TypeError, ValueError, KeyError):
        logger.exception("Failed to get activity")
        return error_response("Activity retrieval failed", status=500)


# =============================================================================
# Inbox Summary
# =============================================================================


@require_permission("dashboard:read")
async def handle_get_inbox_summary(
    context: AuthorizationContext,
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get inbox summary for dashboard.

    GET /api/v1/dashboard/inbox-summary
    """
    try:
        now = datetime.now(timezone.utc)

        summary = {
            "generated_at": now.isoformat(),
            # Counts by status
            "counts": {
                "unread": 42,
                "starred": 15,
                "snoozed": 5,
                "drafts": 3,
                "trash": 28,
            },
            # Priority breakdown
            "by_priority": {
                "critical": 2,
                "high": 7,
                "medium": 25,
                "low": 8,
            },
            # Category breakdown
            "by_category": {
                "inbox": 42,
                "updates": 28,
                "promotions": 15,
                "social": 8,
                "forums": 5,
            },
            # Top labels
            "top_labels": [
                {"name": "Work", "count": 34, "color": "#4285f4"},
                {"name": "Personal", "count": 12, "color": "#34a853"},
                {"name": "Urgent", "count": 7, "color": "#ea4335"},
                {"name": "Follow-up", "count": 9, "color": "#fbbc05"},
            ],
            # Recent high-priority emails
            "urgent_emails": [
                {
                    "id": "msg_001",
                    "subject": "Urgent: Q4 Budget Approval",
                    "from": "cfo@company.com",
                    "received_at": (now - timedelta(hours=1)).isoformat(),
                    "snippet": "Please review and approve the Q4 budget by EOD...",
                },
                {
                    "id": "msg_002",
                    "subject": "Re: Client escalation",
                    "from": "support@company.com",
                    "received_at": (now - timedelta(hours=2)).isoformat(),
                    "snippet": "The client is requesting an urgent call...",
                },
            ],
            # Action items from emails
            "pending_actions": [
                {
                    "id": "action_001",
                    "title": "Review contract",
                    "deadline": (now + timedelta(days=1)).isoformat(),
                    "from_email": "legal@company.com",
                },
                {
                    "id": "action_002",
                    "title": "Submit expense report",
                    "deadline": (now + timedelta(days=3)).isoformat(),
                    "from_email": "hr@company.com",
                },
            ],
        }

        return success_response(summary)

    except (TypeError, ValueError, KeyError):
        logger.exception("Failed to get inbox summary")
        return error_response("Inbox summary failed", status=500)


# =============================================================================
# Quick Actions
# =============================================================================


@require_permission("dashboard:read")
async def handle_get_quick_actions(
    context: AuthorizationContext,
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get available quick actions.

    GET /api/v1/dashboard/quick-actions
    """
    try:
        actions = [
            {
                "id": "archive_read",
                "name": "Archive All Read",
                "description": "Archive all read emails older than 24 hours",
                "icon": "archive",
                "available": True,
                "estimated_count": 45,
            },
            {
                "id": "snooze_low",
                "name": "Snooze Low Priority",
                "description": "Snooze all low priority emails until tomorrow",
                "icon": "clock",
                "available": True,
                "estimated_count": 12,
            },
            {
                "id": "mark_spam",
                "name": "Mark Bulk as Spam",
                "description": "Mark selected promotional emails as spam",
                "icon": "slash",
                "available": True,
                "estimated_count": 8,
            },
            {
                "id": "complete_actions",
                "name": "Complete Done Actions",
                "description": "Mark action items you've completed",
                "icon": "check-circle",
                "available": True,
                "estimated_count": 3,
            },
            {
                "id": "ai_respond",
                "name": "AI Auto-Respond",
                "description": "Let AI draft responses for simple emails",
                "icon": "sparkles",
                "available": True,
                "estimated_count": 5,
            },
            {
                "id": "sync_inbox",
                "name": "Sync Inbox",
                "description": "Force sync with email provider",
                "icon": "refresh",
                "available": True,
                "estimated_count": None,
            },
        ]

        return success_response(
            {
                "actions": actions,
                "count": len(actions),
            }
        )

    except (TypeError, ValueError, KeyError):
        logger.exception("Failed to get quick actions")
        return error_response("Failed to retrieve actions", status=500)


@require_permission("dashboard:write")
async def handle_execute_quick_action(
    context: AuthorizationContext,
    data: dict[str, Any],
    action_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Execute a quick action.

    POST /api/v1/dashboard/quick-actions/{action}
    Body: {
        confirm: bool (optional) - Confirm execution
        options: dict (optional) - Action-specific options
    }
    """
    try:
        if not action_id:
            action_id = data.get("action_id", "")
        if not action_id:
            return error_response("action_id is required", status=400)

        data.get("confirm", False)
        data.get("options", {})

        valid_actions = {
            "archive_read",
            "snooze_low",
            "mark_spam",
            "complete_actions",
            "ai_respond",
            "sync_inbox",
        }

        if action_id not in valid_actions:
            return error_response(f"Unknown action: {action_id}", status=400)

        # Simulate action execution
        result = {
            "action_id": action_id,
            "executed": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if action_id == "archive_read":
            result["affected_count"] = 45
            result["message"] = "Archived 45 read emails"

        elif action_id == "snooze_low":
            result["affected_count"] = 12
            result["snooze_until"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
            result["message"] = "Snoozed 12 low priority emails until tomorrow"

        elif action_id == "mark_spam":
            result["affected_count"] = 8
            result["message"] = "Marked 8 emails as spam"

        elif action_id == "complete_actions":
            result["affected_count"] = 3
            result["message"] = "Completed 3 action items"

        elif action_id == "ai_respond":
            result["affected_count"] = 5
            result["drafts_created"] = 5
            result["message"] = "Created 5 AI draft responses"

        elif action_id == "sync_inbox":
            result["affected_count"] = 0
            result["sync_status"] = "completed"
            result["new_emails"] = 3
            result["message"] = "Inbox synced, 3 new emails"

        logger.info("Quick action executed: %s by %s", action_id, user_id)

        return success_response(result)

    except (TypeError, ValueError, KeyError):
        logger.exception("Failed to execute quick action")
        return error_response("Action execution failed", status=500)


# =============================================================================
# Handler Registration
# =============================================================================


def get_dashboard_handlers() -> dict[str, Any]:
    """Get all dashboard handlers for registration."""
    return {
        "get_dashboard": handle_get_dashboard,
        "get_stats": handle_get_stats,
        "get_activity": handle_get_activity,
        "get_inbox_summary": handle_get_inbox_summary,
        "get_quick_actions": handle_get_quick_actions,
        "execute_quick_action": handle_execute_quick_action,
    }


def get_dashboard_routes() -> list[tuple[str, str, Any]]:
    """
    Get route definitions for dashboard handlers.

    Returns list of (method, path, handler) tuples.
    """
    return [
        ("GET", "/api/v1/dashboard", handle_get_dashboard),
        ("GET", "/api/v1/dashboard/stats", handle_get_stats),
        ("GET", "/api/v1/dashboard/activity", handle_get_activity),
        ("GET", "/api/v1/dashboard/inbox-summary", handle_get_inbox_summary),
        ("GET", "/api/v1/dashboard/quick-actions", handle_get_quick_actions),
        ("POST", "/api/v1/dashboard/quick-actions/{action}", handle_execute_quick_action),
    ]


__all__ = [
    "handle_get_dashboard",
    "handle_get_stats",
    "handle_get_activity",
    "handle_get_inbox_summary",
    "handle_get_quick_actions",
    "handle_execute_quick_action",
    "get_dashboard_handlers",
    "get_dashboard_routes",
]
