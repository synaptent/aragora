"""
Breakpoints endpoint handlers for human-in-the-loop intervention.

Endpoints:
- GET /api/breakpoints/pending - List pending breakpoints awaiting resolution
- POST /api/breakpoints/{id}/resolve - Resolve a pending breakpoint
- GET /api/breakpoints/{id}/status - Get status of a specific breakpoint
"""

from __future__ import annotations

__all__ = [
    "BreakpointsHandler",
]

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.debate.breakpoints import BreakpointManager as DebateBreakpointManager

logger = logging.getLogger(__name__)

from ..base import (
    SAFE_ID_PATTERN,
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    safe_error_message,
    validate_path_segment,
    handle_errors,
)
from aragora.rbac.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

# Rate limiter for breakpoints endpoints (60 requests per minute - debug feature)
_breakpoints_limiter = RateLimiter(requests_per_minute=60)

_breakpoints_module: Any = None

try:
    from aragora.debate import breakpoints as _loaded_breakpoints_module
except ImportError:
    pass
else:
    _breakpoints_module = _loaded_breakpoints_module

HumanGuidance: Any = getattr(_breakpoints_module, "HumanGuidance", None)
BreakpointManager: Any = getattr(_breakpoints_module, "BreakpointManager", None)


class BreakpointsHandler(BaseHandler):
    """Handler for breakpoint management endpoints."""

    ROUTES = [
        "/api/v1/breakpoints",
        "/api/v1/breakpoints/pending",
    ]

    DYNAMIC_ROUTES = [
        "/api/v1/breakpoints/{breakpoint_id}/status",
        "/api/v1/breakpoints/{breakpoint_id}/resolve",
    ]

    # Pattern for breakpoint-specific routes
    BREAKPOINT_PATTERN = re.compile(r"^/api/v1/breakpoints/([a-zA-Z0-9_-]+)/(resolve|status)$")

    def __init__(self, storage: Any = None):
        """Initialize with optional storage backend."""
        super().__init__(storage)
        self._breakpoint_manager: DebateBreakpointManager | None = None
        self._breakpoint_manager_loaded = False

    @property
    def breakpoint_manager(self) -> DebateBreakpointManager | None:
        """Lazy-load breakpoint manager."""
        if self._breakpoint_manager is None and not self._breakpoint_manager_loaded:
            manager_cls = BreakpointManager
            if manager_cls is not None:
                self._breakpoint_manager = manager_cls()
            self._breakpoint_manager_loaded = True
        return self._breakpoint_manager

    @breakpoint_manager.setter
    def breakpoint_manager(self, value: DebateBreakpointManager | None) -> None:
        self._breakpoint_manager = value
        self._breakpoint_manager_loaded = True

    @breakpoint_manager.deleter
    def breakpoint_manager(self) -> None:
        self._breakpoint_manager = None
        self._breakpoint_manager_loaded = False

    @staticmethod
    def _serialize_snapshot(snapshot: object | None) -> dict[str, Any] | None:
        """Serialize debate snapshot objects from real dataclasses or test doubles."""
        if snapshot is None:
            return None

        round_num = getattr(snapshot, "round_num", getattr(snapshot, "current_round", 0))
        confidence = getattr(
            snapshot,
            "current_confidence",
            getattr(snapshot, "confidence", None),
        )
        agents = getattr(snapshot, "agent_names", None)
        if agents is None:
            positions = getattr(snapshot, "agent_positions", None)
            if isinstance(positions, dict):
                agents = list(positions.keys())
            else:
                agents = []
        elif not isinstance(agents, (list, tuple, set)):
            agents = []

        return {
            "debate_id": getattr(snapshot, "debate_id", ""),
            "round_num": round_num,
            "task": getattr(snapshot, "task", ""),
            "confidence": confidence,
            "agents": [str(agent) for agent in agents],
        }

    @staticmethod
    def _breakpoint_message(bp: object) -> str:
        """Return an operator-facing message for real breakpoints and test doubles."""
        message = getattr(bp, "message", None)
        if isinstance(message, str) and message:
            return message
        trigger = getattr(getattr(bp, "trigger", None), "value", "unknown")
        return f"Breakpoint triggered: {trigger}"

    @staticmethod
    def _breakpoint_created_at(bp: object) -> str | None:
        created_at = getattr(bp, "created_at", None)
        if isinstance(created_at, str):
            return created_at
        triggered_at = getattr(bp, "triggered_at", None)
        return triggered_at if isinstance(triggered_at, str) else None

    @staticmethod
    def _breakpoint_status(bp: object) -> str:
        status = getattr(bp, "status", None)
        if isinstance(status, str) and status:
            return status
        resolved = getattr(bp, "resolved", False)
        return "resolved" if resolved else "pending"

    @staticmethod
    def _breakpoint_snapshot(bp: object) -> object | None:
        if hasattr(bp, "snapshot"):
            return getattr(bp, "snapshot")
        return getattr(bp, "debate_snapshot", None)

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        if path in self.ROUTES:
            return True
        return bool(self.BREAKPOINT_PATTERN.match(path))

    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route breakpoint requests to appropriate methods (public dashboard data)."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _breakpoints_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for breakpoints endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/v1/breakpoints":
            return self._get_pending_breakpoints()

        if path == "/api/v1/breakpoints/pending":
            return self._get_pending_breakpoints()

        match = self.BREAKPOINT_PATTERN.match(path)
        if match:
            breakpoint_id, action = match.groups()

            # Validate breakpoint ID
            is_valid, err = validate_path_segment(breakpoint_id, "breakpoint_id", SAFE_ID_PATTERN)
            if not is_valid:
                return error_response(err or "Invalid breakpoint_id", 400)

            if action == "status":
                return self._get_breakpoint_status(breakpoint_id)
            elif action == "resolve":
                # POST only
                return error_response(
                    "Use POST to resolve breakpoints",
                    405,
                    headers={"Allow": "POST"},
                )

        return None

    @handle_errors("breakpoints creation")
    @require_permission("breakpoints:update")
    def handle_post(self, path: str, body: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle POST requests for breakpoint resolution."""
        match = self.BREAKPOINT_PATTERN.match(path)
        if not match:
            return None

        breakpoint_id, action = match.groups()

        # Validate breakpoint ID
        is_valid, err = validate_path_segment(breakpoint_id, "breakpoint_id", SAFE_ID_PATTERN)
        if not is_valid:
            return error_response(err or "Invalid breakpoint_id", 400)

        if action == "resolve":
            return self._resolve_breakpoint(breakpoint_id, body)

        return None

    def _get_pending_breakpoints(self) -> HandlerResult:
        """Get all pending breakpoints awaiting human resolution.

        Returns:
            List of pending breakpoints with their triggers and snapshots
        """
        if not self.breakpoint_manager:
            return error_response("Breakpoints module not available", 503)

        try:
            pending = self.breakpoint_manager.get_pending_breakpoints()

            return json_response(
                {
                    "breakpoints": [
                        {
                            "breakpoint_id": bp.breakpoint_id,
                            "trigger": bp.trigger.value,
                            "message": self._breakpoint_message(bp),
                            "created_at": self._breakpoint_created_at(bp),
                            "timeout_minutes": bp.timeout_minutes,
                            "snapshot": self._serialize_snapshot(self._breakpoint_snapshot(bp)),
                        }
                        for bp in pending
                    ],
                    "count": len(pending),
                }
            )

        except (AttributeError, RuntimeError, TypeError) as e:
            logger.exception("Failed to get pending breakpoints: %s", e)
            return error_response(safe_error_message(e, "get pending breakpoints"), 500)

    def _get_breakpoint_status(self, breakpoint_id: str) -> HandlerResult:
        """Get status of a specific breakpoint.

        Args:
            breakpoint_id: ID of the breakpoint to check

        Returns:
            Breakpoint status and details
        """
        if not self.breakpoint_manager:
            return error_response("Breakpoints module not available", 503)

        try:
            bp = self.breakpoint_manager.get_breakpoint(breakpoint_id)

            if not bp:
                return json_response(
                    {"error": "Breakpoint not found", "breakpoint_id": breakpoint_id},
                    status=404,
                )

            return json_response(
                {
                    "breakpoint_id": bp.breakpoint_id,
                    "trigger": bp.trigger.value,
                    "message": self._breakpoint_message(bp),
                    "status": self._breakpoint_status(bp),
                    "created_at": self._breakpoint_created_at(bp),
                    "resolved_at": bp.resolved_at if hasattr(bp, "resolved_at") else None,
                    "snapshot": self._serialize_snapshot(self._breakpoint_snapshot(bp)),
                }
            )

        except (AttributeError, RuntimeError, TypeError) as e:
            logger.exception("Failed to get breakpoint status: %s", e)
            return error_response(safe_error_message(e, "get breakpoint status"), 500)

    def _resolve_breakpoint(self, breakpoint_id: str, body: dict[str, Any]) -> HandlerResult:
        """Resolve a pending breakpoint with human guidance.

        Args:
            breakpoint_id: ID of the breakpoint to resolve
            body: Request body with resolution details:
                - action: "continue" | "abort" | "redirect" | "inject"
                - message: Human guidance message
                - redirect_task: New task if redirecting (required for "redirect")

        Returns:
            Resolution confirmation
        """
        if not self.breakpoint_manager:
            return error_response("Breakpoints module not available", 503)

        if not isinstance(body, dict):
            return error_response("Request body must be a JSON object", 400)

        # Validate required fields
        action = body.get("action")
        if not isinstance(action, str) or not action:
            return error_response("Missing required field: action", 400)

        valid_actions = ["continue", "abort", "redirect", "inject"]
        if action not in valid_actions:
            return error_response(f"Invalid action: {action}. Must be one of: {valid_actions}", 400)

        message = body.get("message", "")
        redirect_task = body.get("redirect_task")
        reviewer_id = body.get("reviewer_id", "api_user")
        if not isinstance(message, str):
            return error_response("Field 'message' must be a string", 400)
        if redirect_task is not None and not isinstance(redirect_task, str):
            return error_response("Field 'redirect_task' must be a string", 400)
        if isinstance(redirect_task, str):
            redirect_task = redirect_task.strip() or None
        if not isinstance(reviewer_id, str) or not reviewer_id.strip():
            return error_response("Field 'reviewer_id' must be a non-empty string", 400)

        try:
            import uuid

            guidance_cls = HumanGuidance
            if guidance_cls is None:
                return error_response("Breakpoints module not available", 503)

            guidance = guidance_cls(
                guidance_id=str(uuid.uuid4()),
                debate_id=breakpoint_id.split("_")[0] if "_" in breakpoint_id else "",
                human_id=reviewer_id,
                action=action,
                reasoning=message,
                preferred_direction=redirect_task,
            )

            # Resolve the breakpoint
            success = self.breakpoint_manager.resolve_breakpoint(breakpoint_id, guidance)

            if not success:
                return json_response(
                    {
                        "error": "Failed to resolve breakpoint",
                        "breakpoint_id": breakpoint_id,
                        "message": "Breakpoint may not exist or already resolved",
                    },
                    status=404,
                )

            return json_response(
                {
                    "breakpoint_id": breakpoint_id,
                    "status": "resolved",
                    "action": action,
                    "message": message,
                }
            )

        except ImportError:
            return error_response("Breakpoints module not available", 503)
        except (AttributeError, RuntimeError, TypeError, ValueError) as e:
            logger.exception("Failed to resolve breakpoint: %s", e)
            return error_response(safe_error_message(e, "resolve breakpoint"), 500)
