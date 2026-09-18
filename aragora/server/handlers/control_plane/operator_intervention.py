"""
Operator Intervention HTTP Handler.

Provides REST API endpoints for operator control of running debates:
- POST /api/v1/debates/{id}/pause            -- Pause a running debate
- POST /api/v1/debates/{id}/resume           -- Resume a paused debate
- POST /api/v1/debates/{id}/restart          -- Restart from beginning or round
- POST /api/v1/debates/{id}/inject           -- Inject additional context
- GET  /api/v1/debates/{id}/intervention-status -- Get intervention state
- GET  /api/v1/interventions/active          -- List all active interventions

All write endpoints require ``debates:manage`` permission.

Follows existing handler patterns: BaseHandler subclass, can_handle routing,
@handle_errors decorator, RBAC via @require_permission.
"""

from __future__ import annotations

__all__ = [
    "OperatorInterventionHandler",
]

import logging
import re
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import (
    SAFE_ID_PATTERN,
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    validate_path_segment,
)
from aragora.server.handlers.utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter: operator interventions are low-volume (30 requests/min)
_operator_limiter = RateLimiter(requests_per_minute=30)

# Lazy reference to avoid import errors if debate module not available
_get_operator_manager: Any = None
try:
    from aragora.debate.operator_intervention import get_operator_manager as _get_operator_manager
except ImportError:
    pass

# Route patterns for static and parameterized endpoints
_DEBATE_ACTION_PATTERN = re.compile(
    r"^/api/v1/debates/([a-zA-Z0-9_-]+)/"
    r"(pause|resume|restart|inject|intervention-status)$"
)
_ACTIVE_PATTERN = "/api/v1/interventions/active"


def _strip_version_prefix(path: str) -> str:
    """Normalize versioned paths for consistent matching."""
    return path.replace("/api/v1/", "/api/").replace("/api/v2/", "/api/")


class OperatorInterventionHandler(BaseHandler):
    """Handler for operator intervention control endpoints.

    Provides pause, resume, restart, and context injection for
    running debates, plus status inspection and listing of
    active interventions.
    """

    ROUTES = [
        "/api/v1/interventions/active",
    ]

    DYNAMIC_ROUTES = [
        "/api/v1/debates/{debate_id}/pause",
        "/api/v1/debates/{debate_id}/resume",
        "/api/v1/debates/{debate_id}/restart",
        "/api/v1/debates/{debate_id}/inject",
        "/api/v1/debates/{debate_id}/intervention-status",
    ]

    def __init__(
        self, ctx: dict[str, Any] | None = None, server_context: dict[str, Any] | None = None
    ):
        """Initialize handler.

        Args:
            ctx: Server context dict.
            server_context: Alternative server context key (for BaseHandler compatibility).
        """
        if server_context is not None:
            self.ctx = server_context
        else:
            self.ctx = ctx or {}

    # ------------------------------------------------------------------
    # Route matching
    # ------------------------------------------------------------------

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        if path == _ACTIVE_PATTERN:
            return True
        return bool(_DEBATE_ACTION_PATTERN.match(path))

    # ------------------------------------------------------------------
    # GET handler
    # ------------------------------------------------------------------

    @handle_errors("operator intervention GET")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests."""
        # Rate limit
        client_ip = get_client_ip(handler)
        if not _operator_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == _ACTIVE_PATTERN:
            return self._list_active()

        match = _DEBATE_ACTION_PATTERN.match(path)
        if match:
            debate_id, action = match.groups()

            is_valid, err = validate_path_segment(debate_id, "debate_id", SAFE_ID_PATTERN)
            if not is_valid:
                return error_response(err, 400)

            if action == "intervention-status":
                return self._get_status(debate_id)

        return None

    # ------------------------------------------------------------------
    # POST handler
    # ------------------------------------------------------------------

    @handle_errors("operator intervention POST")
    @require_permission("debates:manage")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route POST requests to intervention methods."""
        # Rate limit
        client_ip = get_client_ip(handler)
        if not _operator_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        match = _DEBATE_ACTION_PATTERN.match(path)
        if not match:
            return None

        debate_id, action = match.groups()

        is_valid, err = validate_path_segment(debate_id, "debate_id", SAFE_ID_PATTERN)
        if not is_valid:
            return error_response(err, 400)

        body = self.read_json_body(handler)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return error_response("Request body must be a JSON object", 400)

        if action == "pause":
            return self._pause_debate(debate_id, body)
        if action == "resume":
            return self._resume_debate(debate_id)
        if action == "restart":
            return self._restart_debate(debate_id, body)
        if action == "inject":
            return self._inject_context(debate_id, body)

        return None

    # ------------------------------------------------------------------
    # Endpoint implementations
    # ------------------------------------------------------------------

    def _get_manager(self) -> Any:
        """Get the DebateInterventionManager singleton."""
        if _get_operator_manager is None:
            return None
        return _get_operator_manager()

    def _pause_debate(self, debate_id: str, body: dict[str, Any]) -> HandlerResult:
        """Pause a running debate.

        Body:
            {"reason": "optional reason string"}
        """
        manager = self._get_manager()
        if manager is None:
            return error_response("Operator intervention module not available", 503)

        reason_value = body.get("reason", "")
        if reason_value is not None and not isinstance(reason_value, str):
            return error_response("reason must be a string", 400)
        reason = reason_value.strip() if isinstance(reason_value, str) else ""
        if len(reason) > 1000:
            return error_response("reason must not exceed 1000 characters", 400)

        success = manager.pause(debate_id, reason=reason)
        if not success:
            status = manager.get_status(debate_id)
            if status is None:
                return error_response(f"Debate not found: {debate_id}", 404)
            return error_response(f"Cannot pause debate in state: {status.state}", 409)

        status = manager.get_status(debate_id)
        return json_response(
            {
                "success": True,
                "debate_id": debate_id,
                "state": "paused",
                "paused_at": status.paused_at if status else None,
                "reason": reason or None,
            }
        )

    def _resume_debate(self, debate_id: str) -> HandlerResult:
        """Resume a paused debate."""
        manager = self._get_manager()
        if manager is None:
            return error_response("Operator intervention module not available", 503)

        success = manager.resume(debate_id)
        if not success:
            status = manager.get_status(debate_id)
            if status is None:
                return error_response(f"Debate not found: {debate_id}", 404)
            return error_response(f"Cannot resume debate in state: {status.state}", 409)

        return json_response(
            {
                "success": True,
                "debate_id": debate_id,
                "state": "running",
            }
        )

    def _restart_debate(self, debate_id: str, body: dict[str, Any]) -> HandlerResult:
        """Restart a debate from the beginning or a specific round.

        Body:
            {"from_round": 0}  -- optional, defaults to 0 (beginning)
        """
        manager = self._get_manager()
        if manager is None:
            return error_response("Operator intervention module not available", 503)

        from_round = body.get("from_round", 0)
        if isinstance(from_round, bool) or not isinstance(from_round, int) or from_round < 0:
            return error_response("from_round must be a non-negative integer", 400)
        if from_round > 10000:
            return error_response("from_round exceeds maximum allowed value", 400)

        success = manager.restart(debate_id, from_round=from_round)
        if not success:
            status = manager.get_status(debate_id)
            if status is None:
                return error_response(f"Debate not found: {debate_id}", 404)
            return error_response(f"Cannot restart debate in state: {status.state}", 409)

        return json_response(
            {
                "success": True,
                "debate_id": debate_id,
                "state": "running",
                "from_round": from_round,
            }
        )

    def _inject_context(self, debate_id: str, body: dict[str, Any]) -> HandlerResult:
        """Inject additional context into a debate.

        Body:
            {"context": "The additional context text to inject"}
        """
        manager = self._get_manager()
        if manager is None:
            return error_response("Operator intervention module not available", 503)

        if "context" not in body:
            return error_response("Missing required field: context", 400)
        context = body["context"]
        if not isinstance(context, str) or not context.strip():
            return error_response("context must be a non-empty string", 400)

        # Sanitize: limit to 5000 chars
        context = context.strip()[:5000]

        success = manager.inject_context(debate_id, context)
        if not success:
            status = manager.get_status(debate_id)
            if status is None:
                return error_response(f"Debate not found: {debate_id}", 404)
            return error_response(
                f"Cannot inject context into debate in state: {status.state}", 409
            )

        return json_response(
            {
                "success": True,
                "debate_id": debate_id,
                "context_length": len(context),
            }
        )

    def _get_status(self, debate_id: str) -> HandlerResult:
        """Get intervention status for a debate."""
        manager = self._get_manager()
        if manager is None:
            return error_response("Operator intervention module not available", 503)

        status = manager.get_status(debate_id)
        if status is None:
            return error_response(f"Debate not found: {debate_id}", 404)

        return json_response({"data": status.to_dict()})

    def _list_active(self) -> HandlerResult:
        """List all active intervention-tracked debates."""
        manager = self._get_manager()
        if manager is None:
            return error_response("Operator intervention module not available", 503)

        active = manager.list_active()
        return json_response(
            {
                "data": [s.to_dict() for s in active],
                "count": len(active),
            }
        )
