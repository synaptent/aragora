"""Debate statistics handler for aggregate debate metrics.

Endpoints:
- GET /api/v1/debates/stats - Get aggregate debate statistics
- GET /api/v1/debates/stats/agents - Get per-agent statistics
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import BaseHandler, HandlerResult, error_response, json_response
from aragora.server.validation.query_params import safe_query_int
from aragora.server.versioning.compat import strip_version_prefix

logger = logging.getLogger(__name__)


async def _await_awaitable(value: Any) -> Any:
    """Await generic awaitables while presenting a concrete coroutine type."""
    return await value


def _resolve(maybe_coro: Any) -> Any:
    """Resolve a value that may be a coroutine (from async def) to its result."""
    if inspect.isawaitable(maybe_coro):
        try:
            loop = asyncio.get_running_loop()
            return loop.run_until_complete(_await_awaitable(maybe_coro))
        except RuntimeError:
            return asyncio.run(_await_awaitable(maybe_coro))
    return maybe_coro


class DebateStatsHandler(BaseHandler):
    """Handle aggregate debate statistics endpoints.

    All endpoints require ``debates:read`` permission.
    """

    ROUTES = [
        "/api/v1/debates/stats",
        "/api/v1/debates/stats/agents",
    ]

    def can_handle(self, path: str) -> bool:
        stripped = strip_version_prefix(path)
        return stripped in ("/api/debates/stats", "/api/debates/stats/agents")

    @require_permission("debates:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        if handler.command != "GET":
            return error_response("Method not allowed", 405)

        stripped = strip_version_prefix(path)

        if stripped == "/api/debates/stats":
            return self._get_stats(query_params, handler)
        if stripped == "/api/debates/stats/agents":
            return self._get_agent_stats(query_params, handler)

        return None

    def _get_stats(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        period = query_params.get("period", "all")
        _period_to_days = {"all": 3650, "day": 1, "week": 7, "month": 30}
        if period not in _period_to_days:
            return error_response("period must be one of: all, day, week, month", 400)

        try:
            from aragora.analytics.debate_analytics import DebateAnalytics

            storage = self.ctx.get("storage")
            if storage is None:
                return error_response("Storage not available", 503)

            service = DebateAnalytics(storage)
            stats = _resolve(service.get_debate_stats(days_back=_period_to_days[period]))
            return json_response(stats.to_dict())
        except (
            ImportError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OSError,
            RuntimeError,
        ) as exc:
            logger.error("Failed to get debate stats: %s", exc)
            return error_response("Failed to get debate stats", 500)

    def _get_agent_stats(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        limit = safe_query_int(query_params, "limit", default=20, min_val=1, max_val=100)

        try:
            from aragora.analytics.debate_analytics import DebateAnalytics

            storage = self.ctx.get("storage")
            if storage is None:
                return error_response("Storage not available", 503)

            service = DebateAnalytics(storage)
            agents = _resolve(service.get_agent_leaderboard(limit=limit))
            return json_response(
                {
                    "agents": [a.to_dict() if hasattr(a, "to_dict") else a for a in agents]
                    if agents
                    else [],
                    "count": len(agents),
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
            IndexError,
        ) as exc:
            logger.error("Failed to get agent stats: %s", exc)
            return error_response("Failed to get agent stats", 500)


__all__ = ["DebateStatsHandler"]
