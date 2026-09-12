"""
Moderation Analytics Dashboard Handler.

Provides API endpoints for moderation analytics:
- GET /api/v1/moderation/stats  (block rate, review queue size, false positive rate)
- GET /api/v1/moderation/queue  (pending review items)
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    handle_errors,
    json_response,
)

logger = logging.getLogger(__name__)


def _get_moderation():
    """Lazy-load moderation singleton."""
    try:
        from aragora.moderation import get_spam_moderation

        return get_spam_moderation()
    except ImportError:
        return None


def _get_queue_size():
    """Get review queue size."""
    try:
        from aragora.moderation import review_queue_size

        return review_queue_size()
    except ImportError:
        return 0


def _list_queue(limit=50, offset=0):
    """List review queue items."""
    try:
        from aragora.moderation import list_review_queue

        return list_review_queue(limit=limit, offset=offset)
    except ImportError:
        return []


class ModerationAnalyticsHandler(BaseHandler):
    """Handler for moderation analytics dashboard endpoints."""

    ROUTES = [
        "/api/v1/moderation/stats",
        "/api/v1/moderation/queue",
    ]

    def __init__(self, ctx: dict[str, Any] | None = None, **kwargs: Any):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        return path in self.ROUTES

    @require_permission("admin:read")
    @handle_errors("get moderation stats")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        if path == "/api/v1/moderation/stats":
            return self._handle_stats()
        if path == "/api/v1/moderation/queue":
            return self._handle_queue(query_params)
        return None

    def _handle_stats(self) -> HandlerResult:
        """Return moderation statistics."""
        moderation = _get_moderation()
        if moderation is None:
            return json_response(
                {
                    "total_checks": 0,
                    "blocked_count": 0,
                    "flagged_count": 0,
                    "clean_count": 0,
                    "block_rate": 0.0,
                    "false_positive_rate": 0.0,
                    "queue_size": 0,
                    "available": False,
                }
            )

        stats = dict(getattr(moderation, "statistics", {}))
        total = stats.get("total_checks", 0) or 0
        blocked = stats.get("blocked", 0) or stats.get("blocked_count", 0) or 0
        flagged = stats.get("flagged", 0) or stats.get("flagged_count", 0) or 0
        clean = stats.get("clean", 0) or stats.get("clean_count", 0) or 0
        false_positives = stats.get("false_positives", 0) or 0

        block_rate = blocked / total if total > 0 else 0.0
        fp_rate = false_positives / blocked if blocked > 0 else 0.0
        queue_size = _get_queue_size()

        return json_response(
            {
                "total_checks": total,
                "blocked_count": blocked,
                "flagged_count": flagged,
                "clean_count": clean,
                "block_rate": round(block_rate, 4),
                "false_positive_rate": round(fp_rate, 4),
                "queue_size": queue_size,
                "available": True,
            }
        )

    def _handle_queue(self, query_params: dict[str, Any]) -> HandlerResult:
        """Return pending review items."""
        try:
            limit = min(int(query_params.get("limit", 50)), 200)
        except (ValueError, TypeError):
            limit = 50
        try:
            offset = max(int(query_params.get("offset", 0)), 0)
        except (ValueError, TypeError):
            offset = 0

        items = _list_queue(limit=limit, offset=offset)

        serialized = []
        for item in items:
            if hasattr(item, "to_dict"):
                serialized.append(item.to_dict())
            elif isinstance(item, dict):
                serialized.append(item)
            else:
                serialized.append(str(item))

        return json_response(
            {
                "items": serialized,
                "count": len(serialized),
                "limit": limit,
                "offset": offset,
            }
        )


__all__ = ["ModerationAnalyticsHandler"]
