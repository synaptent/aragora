"""
Moderation API Handler.

Provides API endpoints for spam moderation configuration and review queue:
- GET  /api/moderation/config
- PUT  /api/moderation/config
- GET  /api/moderation/stats
- GET  /api/moderation/queue
- POST /api/moderation/items/{id}/approve
- POST /api/moderation/items/{id}/reject
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.moderation import (
    get_spam_moderation,
    list_review_queue,
    pop_review_item,
    review_queue_size,
)
from aragora.server.handlers.base import HandlerResult, json_response, error_response, handle_errors
from aragora.server.handlers.secure import SecureHandler
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.http_utils import run_async
from aragora.server.validation import safe_query_int
from aragora.server.versioning.compat import strip_version_prefix

logger = logging.getLogger(__name__)


class ModerationHandler(SecureHandler):
    """Handler for moderation configuration and review queue."""

    RESOURCE_TYPE = "moderation"

    ROUTES = [
        "/api/moderation/config",
        "/api/moderation/stats",
        "/api/moderation/queue",
        "/api/moderation/items/*/approve",
        "/api/moderation/items/*/reject",
    ]

    def can_handle(self, path: str) -> bool:
        return strip_version_prefix(path).startswith("/api/moderation/")

    def _get_moderation(self):
        moderation = get_spam_moderation()
        if not moderation._initialized:
            try:
                run_async(moderation.initialize())
            except (RuntimeError, OSError, ConnectionError, TimeoutError) as exc:
                logger.warning("Moderation init failed: %s", exc)
        return moderation

    @require_permission("admin.security")
    def _handle_get_config(self, handler: Any) -> HandlerResult:
        moderation = self._get_moderation()
        return json_response(moderation.config.to_dict())

    @require_permission("admin.metrics")
    def _handle_get_stats(self, handler: Any) -> HandlerResult:
        moderation = self._get_moderation()
        stats = dict(moderation.statistics)
        stats["queue_size"] = review_queue_size()
        return json_response(stats)

    @require_permission("admin.security")
    def _handle_get_queue(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        limit = safe_query_int(query_params, "limit", default=50, max_val=200)
        offset = safe_query_int(query_params, "offset", default=0, max_val=5000)
        items = list_review_queue(limit=limit, offset=offset)
        return json_response({"items": [item.to_dict() for item in items]})

    @require_permission("admin.security")
    def _handle_update_config(self, handler: Any) -> HandlerResult:
        data, err = self.read_json_body_validated(handler)
        if err is not None:
            return err
        if not isinstance(data, dict):
            return error_response("Request body must be a JSON object", status=400)
        moderation = self._get_moderation()
        moderation.update_config(data)
        return json_response(moderation.config.to_dict())

    @require_permission("admin.security")
    def _handle_queue_action(self, item_id: str, action: str) -> HandlerResult:
        if not isinstance(item_id, str) or not item_id.strip():
            return error_response("Invalid item ID", status=400)
        if not isinstance(action, str) or action not in ("approved", "rejected"):
            return error_response("Invalid action", status=400)
        item = pop_review_item(item_id)
        if not item:
            return error_response("Item not found", status=404)
        return json_response({"status": action, "item_id": item_id})

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        path = strip_version_prefix(path)
        if path == "/api/moderation/config":
            return self._handle_get_config(handler)
        if path == "/api/moderation/stats":
            return self._handle_get_stats(handler)
        if path == "/api/moderation/queue":
            return self._handle_get_queue(query_params, handler)
        return None

    @handle_errors("moderation update")
    def handle_put(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        path = strip_version_prefix(path)
        if path == "/api/moderation/config":
            return self._handle_update_config(handler)
        return None

    @handle_errors("moderation creation")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        path = strip_version_prefix(path)
        if path.startswith("/api/moderation/items/") and path.endswith("/approve"):
            item_id = path.split("/")[-2]
            return self._handle_queue_action(item_id, "approved")
        if path.startswith("/api/moderation/items/") and path.endswith("/reject"):
            item_id = path.split("/")[-2]
            return self._handle_queue_action(item_id, "rejected")
        return None


__all__ = ["ModerationHandler"]
