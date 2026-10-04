"""
Feedback Hub endpoint handlers.

Provides REST API visibility into the unified feedback routing hub
that ties together all self-improvement feedback loops.

Endpoints:
    GET /api/v1/feedback-hub/stats   - Routing statistics
    GET /api/v1/feedback-hub/history - Recent routing history
"""

from __future__ import annotations

__all__ = [
    "FeedbackHubHandler",
]

import logging
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
)
from aragora.server.handlers.utils.decorators import handle_errors
from aragora.server.versioning.compat import strip_version_prefix

logger = logging.getLogger(__name__)


class FeedbackHubHandler(BaseHandler):
    """Handler for feedback hub visibility endpoints."""

    ROUTES = [
        "/api/feedback-hub/stats",
        "/api/feedback-hub/history",
        "/api/v1/feedback-hub/stats",
        "/api/v1/feedback-hub/history",
    ]

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if method != "GET":
            return False
        normalized = strip_version_prefix(path)
        return normalized in (
            "/api/feedback-hub/stats",
            "/api/feedback-hub/history",
        )

    def handle_get(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Dispatch GET requests to the appropriate handler method."""
        normalized = strip_version_prefix(path)

        if normalized == "/api/feedback-hub/stats":
            return self._handle_stats()
        if normalized == "/api/feedback-hub/history":
            return self._handle_history(query_params)

        return None

    @handle_errors("feedback hub stats")
    @require_permission("admin:read")
    def _handle_stats(self) -> HandlerResult:
        """GET /api/v1/feedback-hub/stats -- Return routing statistics."""
        try:
            from aragora.nomic.feedback_hub import get_feedback_hub

            hub = get_feedback_hub()
            stats = hub.stats()
        except ImportError:
            return error_response("Feedback hub module not available", 503)

        return json_response({"data": stats})

    @handle_errors("feedback hub history")
    @require_permission("admin:read")
    def _handle_history(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/feedback-hub/history -- Return recent routing history."""
        limit = min(int(query_params.get("limit", 50)), 200)

        try:
            from aragora.nomic.feedback_hub import get_feedback_hub

            hub = get_feedback_hub()
            entries = hub.history(limit=limit)
        except ImportError:
            return error_response("Feedback hub module not available", 503)

        return json_response({"data": entries})
