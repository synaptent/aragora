"""Audience suggestion handler for debate audience input.

Endpoints:
- GET /api/v1/audience/suggestions - List clustered suggestions for a debate
- POST /api/v1/audience/suggestions - Submit a new audience suggestion
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.server.handlers.base import BaseHandler, HandlerResult, error_response, json_response
from aragora.server.validation.query_params import safe_query_int

logger = logging.getLogger(__name__)


class AudienceSuggestionsHandler(BaseHandler):
    """Handle audience suggestion submission and retrieval."""

    ROUTES = [
        "/api/v1/audience/suggestions",
    ]

    def can_handle(self, path: str) -> bool:
        return path in self.ROUTES

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        if handler.command == "GET":
            return self._list_suggestions(query_params, handler)
        if handler.command == "POST":
            return self._submit_suggestion(handler)
        return error_response("Method not allowed", 405)

    def _list_suggestions(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        user, perm_err = self.require_permission_or_error(handler, "audience:read")
        if perm_err:
            return perm_err

        debate_id = query_params.get("debate_id")
        if not isinstance(debate_id, str) or not debate_id.strip():
            return error_response("debate_id query parameter is required", 400)
        debate_id = debate_id.strip()

        max_clusters = safe_query_int(
            query_params, "max_clusters", default=5, min_val=1, max_val=20
        )
        try:
            threshold = float(query_params.get("threshold", "0.6"))
        except (ValueError, TypeError):
            return error_response("Invalid threshold value", 400)
        if not (0.0 <= threshold <= 1.0):
            return error_response("threshold must be between 0.0 and 1.0", 400)

        try:
            from aragora.audience.suggestions import cluster_suggestions

            storage = self.ctx.get("storage")
            if storage is None:
                return error_response("Storage not available", 503)

            raw_suggestions = storage.get_audience_suggestions(debate_id)
            clusters = cluster_suggestions(
                raw_suggestions,
                similarity_threshold=threshold,
                max_clusters=max_clusters,
            )
            return json_response(
                {
                    "debate_id": debate_id,
                    "clusters": [
                        {
                            "representative": c.representative,
                            "count": c.count,
                            "user_ids": c.user_ids,
                        }
                        for c in clusters
                    ],
                    "total_clusters": len(clusters),
                }
            )
        except (
            ImportError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OSError,
            RuntimeError,
        ) as exc:
            logger.error("Failed to list audience suggestions: %s", exc)
            return error_response("Failed to list audience suggestions", 500)

    def _submit_suggestion(self, handler: Any) -> HandlerResult:
        user, perm_err = self.require_permission_or_error(handler, "audience:write")
        if perm_err:
            return perm_err

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)
        if not isinstance(body, dict):
            return error_response("JSON body must be an object", 400)

        debate_id = body.get("debate_id")
        suggestion_value = body.get("suggestion", "")

        if not isinstance(debate_id, str) or not debate_id.strip():
            return error_response("debate_id is required", 400)
        if not isinstance(suggestion_value, str):
            return error_response("suggestion text is required", 400)

        debate_id = debate_id.strip()
        suggestion_text = suggestion_value.strip()
        if not suggestion_text:
            return error_response("suggestion text is required", 400)
        if len(suggestion_text) > 500:
            return error_response("suggestion text exceeds 500 characters", 400)

        try:
            from aragora.audience.suggestions import sanitize_suggestion

            sanitized = sanitize_suggestion(suggestion_text)
            storage = self.ctx.get("storage")
            if storage is None:
                return error_response("Storage not available", 503)

            storage.save_audience_suggestion(
                debate_id=debate_id,
                user_id=getattr(user, "user_id", "anonymous"),
                suggestion=sanitized,
            )
            return json_response(
                {
                    "status": "accepted",
                    "debate_id": debate_id,
                    "sanitized_text": sanitized,
                },
                status=201,
            )
        except (
            ImportError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OSError,
            RuntimeError,
        ) as exc:
            logger.error("Failed to submit suggestion: %s", exc)
            return error_response("Failed to submit suggestion", 500)


__all__ = ["AudienceSuggestionsHandler"]
