"""
Vetted Decisionmaking (Deliberations) API Handler.

Provides endpoints for the vetted decisionmaking dashboard:
- List active vetted decisionmaking sessions
- Get vetted decisionmaking statistics
- WebSocket stream for real-time updates

Usage:
    GET    /api/v1/deliberations/active    - List active vetted decisionmaking sessions
    GET    /api/v1/deliberations/stats     - Get aggregate statistics
    GET    /api/v1/deliberations/{id}      - Get vetted decisionmaking details
    WS     /api/v1/deliberations/stream    - Real-time event stream
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from aragora.config import DEFAULT_ROUNDS
from aragora.memory.debate_store import get_debate_store
from aragora.server.handlers.base import BaseHandler
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.handlers.utils.responses import error_dict

# RBAC imports - graceful fallback if not available
AuthorizationContext: Any
check_permission: Any
try:
    from aragora.rbac import AuthorizationContext as _AuthorizationContext
    from aragora.rbac import check_permission as _check_permission

    AuthorizationContext = _AuthorizationContext
    check_permission = _check_permission
    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False
    AuthorizationContext = None
    check_permission = None

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

# JWT auth import for extracting user context
extract_user_from_request: Any
try:
    from aragora.billing.jwt_auth import extract_user_from_request as _extract_user_from_request

    extract_user_from_request = _extract_user_from_request
    JWT_AUTH_AVAILABLE = True
except ImportError:
    JWT_AUTH_AVAILABLE = False
    extract_user_from_request = None

logger = logging.getLogger(__name__)

# In-memory deliberation tracking
_active_deliberations: dict[str, dict[str, Any]] = {}
_stream_clients: list[asyncio.Queue[dict[str, Any]]] = []
_stats: dict[str, Any] = {
    "active_count": 0,
    "completed_today": 0,
    "average_consensus_time": 0,
    "average_rounds": 0,
    "top_agents": [],
}


class DeliberationsHandler(BaseHandler):
    """
    Handler for vetted decisionmaking dashboard endpoints.

    Provides visibility into multi-agent vetted decisionmaking sessions across the system.

    RBAC Permissions:
    - analytics.read - View active deliberations, stats, and details
    - analytics.read - Subscribe to deliberation stream
    """

    ROUTES = [
        "/api/v1/deliberations/active",
        "/api/v1/deliberations/stats",
        "/api/v1/deliberations/stream",
        "/api/v1/deliberations/{deliberation_id}",
    ]

    def _get_auth_context(self, request: Any) -> AuthorizationContext | None:
        """Build RBAC authorization context from request.

        Returns None if RBAC/JWT auth is not available (allows request in dev mode).
        """
        if not RBAC_AVAILABLE or not JWT_AUTH_AVAILABLE or AuthorizationContext is None:
            return None

        try:
            # Extract user from JWT token
            auth_ctx = extract_user_from_request(request, user_store=None)
            if not auth_ctx or not auth_ctx.is_authenticated:
                return None

            # Build RBAC context
            roles = set([auth_ctx.role]) if hasattr(auth_ctx, "role") and auth_ctx.role else set()

            return AuthorizationContext(
                user_id=auth_ctx.user_id,
                roles=roles,
                org_id=getattr(auth_ctx, "org_id", None),
            )
        except (ValueError, TypeError, AttributeError, KeyError) as e:
            logger.debug("Failed to extract auth context: %s", e)
            return None

    def _check_rbac_permission(
        self, request: Any, permission_key: str
    ) -> tuple[dict[str, Any], int] | None:
        """Check RBAC permission.

        Returns None if allowed, or an error response tuple if denied.
        If RBAC is not available, allows the request (development mode).
        In production, denies access when RBAC is unavailable (fail-closed).
        """
        if not RBAC_AVAILABLE or check_permission is None:
            if rbac_fail_closed():
                return ({"error": "Service unavailable: access control module not loaded"}, 503)
            return None

        rbac_ctx = self._get_auth_context(request)
        if not rbac_ctx:
            # No auth context - in dev mode, allow request
            return None

        decision = check_permission(rbac_ctx, permission_key)
        if not decision.allowed:
            logger.warning(
                "RBAC denied: user=%s permission=%s reason=%s",
                rbac_ctx.user_id,
                permission_key,
                decision.reason,
            )
            return (error_dict("Permission denied", code="FORBIDDEN"), 403)

        return None

    @require_permission("debates:read")
    async def handle_request(self, request: Any) -> Any:
        """Route request to appropriate handler."""
        path = request.path
        method = request.method

        # Active deliberations - requires analytics.read
        if path == "/api/v1/deliberations/active" and method == "GET":
            if rbac_error := self._check_rbac_permission(request, "analytics.read"):
                return rbac_error
            return await self._get_active_deliberations(request)

        # Stats - requires analytics.read
        if path == "/api/v1/deliberations/stats" and method == "GET":
            if rbac_error := self._check_rbac_permission(request, "analytics.read"):
                return rbac_error
            return await self._get_stats(request)

        # WebSocket stream - requires analytics.read for subscribing to updates
        if path == "/api/v1/deliberations/stream":
            if rbac_error := self._check_rbac_permission(request, "analytics.read"):
                return rbac_error
            return await self._handle_stream(request)

        # Single deliberation - requires analytics.read
        if path.startswith("/api/v1/deliberations/") and method == "GET":
            deliberation_id = path.split("/")[-1]
            if deliberation_id not in ("active", "stats", "stream"):
                if rbac_error := self._check_rbac_permission(request, "analytics.read"):
                    return rbac_error
                return await self._get_deliberation(request, deliberation_id)

        return (error_dict("Not found", code="NOT_FOUND"), 404)

    async def _get_active_deliberations(self, request: Any) -> tuple[dict[str, Any], int]:
        """Get list of active vetted decisionmaking sessions."""
        try:
            # Try to get real deliberations from debate store
            deliberations = await self._fetch_active_from_store()

            return {
                "deliberations": deliberations,
                "count": len(deliberations),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, 200
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Error fetching deliberations: %s", e)
            return (error_dict("Internal server error", code="INTERNAL_ERROR"), 500)

    async def _fetch_active_from_store(self) -> list[dict[str, Any]]:
        """Fetch active vetted decisionmaking sessions from the debate store."""
        deliberations = []

        try:
            # Try to get from debate store
            store = get_debate_store()
            if store:
                # Get recent debates
                recent = store.get_recent(limit=50)
                for debate in recent:
                    status = self._map_debate_status(debate.get("status", "unknown"))
                    if status in ("active", "consensus_forming", "initializing"):
                        deliberations.append(self._format_deliberation(debate))
        except ImportError:
            pass

        # Fall back to in-memory tracking
        for delib_id, delib in _active_deliberations.items():
            deliberations.append(delib)

        return deliberations

    def _map_debate_status(self, status: str) -> str:
        """Map debate status to deliberation status."""
        status_map = {
            "pending": "initializing",
            "running": "active",
            "streaming": "active",
            "voting": "consensus_forming",
            "complete": "complete",
            "completed": "complete",
            "failed": "failed",
            "error": "failed",
        }
        return status_map.get(status, status)

    def _format_deliberation(self, debate: dict[str, Any]) -> dict[str, Any]:
        """Format a debate as a deliberation."""
        agents = debate.get("agents", [])
        if isinstance(agents, str):
            agents = [agents]

        messages = debate.get("messages", [])
        current_round = debate.get("current_round", 0)
        if not current_round and messages:
            current_round = max((m.get("round", 0) for m in messages), default=0)

        return {
            "id": debate.get("id", debate.get("debate_id", "")),
            "task": debate.get("task", debate.get("question", "")),
            "status": self._map_debate_status(debate.get("status", "unknown")),
            "agents": agents,
            "current_round": current_round,
            "total_rounds": debate.get("total_rounds", debate.get("rounds", DEFAULT_ROUNDS)),
            "consensus_score": debate.get("consensus_score", 0),
            "started_at": debate.get("started_at", debate.get("created_at", "")),
            "updated_at": debate.get("updated_at", debate.get("started_at", "")),
            "message_count": len(messages),
            "votes": debate.get("votes", {}),
        }

    async def _get_stats(self, request: Any) -> tuple[dict[str, Any], int]:
        """Get deliberation statistics."""
        try:
            # Calculate live stats
            active = await self._fetch_active_from_store()
            active_count = len(
                [d for d in active if d["status"] in ("active", "consensus_forming")]
            )

            # Get completed today
            completed_today = 0
            try:
                store = get_debate_store()
                if store:
                    today = datetime.now(timezone.utc).date()
                    recent = store.get_recent(limit=100)
                    for debate in recent:
                        if debate.get("status") in ("complete", "completed"):
                            completed_at = debate.get("completed_at", debate.get("updated_at", ""))
                            if completed_at:
                                try:
                                    completed_date = datetime.fromisoformat(
                                        completed_at.replace("Z", "+00:00")
                                    ).date()
                                    if completed_date == today:
                                        completed_today += 1
                                except (ValueError, AttributeError):
                                    pass
            except ImportError:
                pass

            return {
                "active_count": active_count,
                "completed_today": completed_today,
                "average_consensus_time": _stats.get("average_consensus_time", 420),
                "average_rounds": _stats.get("average_rounds", 4.2),
                "top_agents": _stats.get("top_agents", []),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, 200
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Error fetching stats: %s", e)
            return (error_dict("Internal server error", code="INTERNAL_ERROR"), 500)

    async def _get_deliberation(
        self, request: Any, deliberation_id: str
    ) -> tuple[dict[str, Any], int]:
        """Get a single deliberation by ID."""
        try:
            # Check in-memory first
            if deliberation_id in _active_deliberations:
                return _active_deliberations[deliberation_id], 200

            # Try debate store
            try:
                store = get_debate_store()
                if store:
                    debate = store.get(deliberation_id)
                    if debate:
                        return self._format_deliberation(debate), 200
            except ImportError:
                pass

            return (error_dict("Deliberation not found", code="NOT_FOUND"), 404)
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Error fetching deliberation %s: %s", deliberation_id, e)
            return (error_dict("Internal server error", code="INTERNAL_ERROR"), 500)

    async def _handle_stream(self, request: Any) -> Any:
        """Handle WebSocket stream for real-time updates."""
        # WebSocket handling would be done at the server level
        # This returns the stream configuration
        return {
            "type": "websocket",
            "path": "/api/v1/deliberations/stream",
            "events": [
                "agent_message",
                "vote",
                "consensus_progress",
                "round_complete",
                "deliberation_complete",
            ],
        }, 200


# Module-level functions for event broadcasting
async def broadcast_deliberation_event(event: dict[str, Any]) -> None:
    """Broadcast an event to all connected stream clients."""
    for queue in _stream_clients:
        try:
            await queue.put(event)
        except (ValueError, TypeError, OSError) as e:
            logger.debug("Failed to broadcast event to stream client: %s", e)


def register_deliberation(deliberation_id: str, data: dict[str, Any]) -> None:
    """Register an active deliberation."""
    _active_deliberations[deliberation_id] = {
        "id": deliberation_id,
        **data,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def update_deliberation(deliberation_id: str, updates: dict[str, Any]) -> None:
    """Update a deliberation's data."""
    if deliberation_id in _active_deliberations:
        _active_deliberations[deliberation_id].update(updates)
        _active_deliberations[deliberation_id]["updated_at"] = datetime.now(
            timezone.utc
        ).isoformat()


def complete_deliberation(deliberation_id: str) -> None:
    """Mark a deliberation as complete and remove from active."""
    if deliberation_id in _active_deliberations:
        _active_deliberations[deliberation_id]["status"] = "complete"
        # Update stats
        _stats["completed_today"] = _stats.get("completed_today", 0) + 1


# Handler instance (lazy initialization - instantiated by unified_server.py)
