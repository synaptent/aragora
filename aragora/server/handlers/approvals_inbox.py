"""Unified approvals inbox handler."""

from __future__ import annotations

import logging
from typing import Any

from aragora.server.handlers.base import BaseHandler, HandlerResult, error_response, json_response
from aragora.server.validation.query_params import safe_query_int

logger = logging.getLogger(__name__)


class UnifiedApprovalsHandler(BaseHandler):
    """Aggregate approval requests across subsystems."""

    ROUTES = [
        "/api/v1/approvals",
        "/api/v1/approvals/pending",
    ]

    def can_handle(self, path: str) -> bool:
        return path in self.ROUTES

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        if handler.command != "GET":
            return error_response("Method not allowed", 405)

        return self._handle_list(query_params, handler)

    def _handle_list(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        user, perm_err = self.require_permission_or_error(handler, "approval:read")
        if perm_err:
            return perm_err

        status = (query_params.get("status") or "pending").lower()
        if status != "pending":
            return error_response("Only pending approvals are supported", 400)

        limit = safe_query_int(query_params, "limit", default=100, min_val=1, max_val=500)

        sources_raw = query_params.get("source") or query_params.get("sources")
        sources = None
        if sources_raw:
            sources = [s.strip() for s in str(sources_raw).split(",") if s.strip()]

        try:
            from aragora.approvals.inbox import DEFAULT_APPROVAL_SOURCES, collect_pending_approvals

            approvals = collect_pending_approvals(limit=limit, sources=sources)
        except (
            ImportError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OSError,
            RuntimeError,
        ) as exc:
            logger.error("Failed to collect approvals: %s", exc)
            return error_response("Failed to collect approvals", 500)

        return json_response(
            {
                "approvals": approvals,
                "count": len(approvals),
                "requested_by": getattr(user, "user_id", None),
                "sources": sources or DEFAULT_APPROVAL_SOURCES,
            }
        )


__all__ = ["UnifiedApprovalsHandler"]
