"""
Debate intervention and reasoning endpoint handlers.

Provides real-time user intervention capabilities and reasoning visibility
for live debates.

Endpoints:
- POST /api/v1/debates/{debate_id}/intervene - Submit a mid-debate intervention
- GET  /api/v1/debates/{debate_id}/reasoning - Get per-agent reasoning summary
"""

from __future__ import annotations

__all__ = [
    "DebateInterventionHandler",
]

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

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

# Rate limiter: interventions are low-volume but sensitive (30 requests/min)
_intervention_limiter = RateLimiter(requests_per_minute=30)

# Lazy module references
get_intervention_queue: Any = None
try:
    from aragora.debate.intervention import get_intervention_queue as _get_intervention_queue

    get_intervention_queue = _get_intervention_queue
except ImportError:
    pass


class DebateInterventionHandler(BaseHandler):
    """Handler for debate intervention and reasoning endpoints."""

    ROUTES: list[str] = []

    DYNAMIC_ROUTES = [
        "/api/v1/debates/{debate_id}/intervene",
        "/api/v1/debates/{debate_id}/reasoning",
    ]

    # Pattern for debate-specific routes
    DEBATE_ACTION_PATTERN = re.compile(r"^/api/v1/debates/([a-zA-Z0-9_-]+)/(intervene|reasoning)$")

    def __init__(self, storage: Any = None):
        """Initialize with optional storage backend."""
        super().__init__(storage)
        self._queue: Any = None
        self._queue_loaded = False

    @property
    def queue(self) -> Any:
        """Lazy-load intervention queue."""
        if self._queue is None and not self._queue_loaded:
            queue_fn = get_intervention_queue
            if queue_fn is not None:
                self._queue = queue_fn()
            self._queue_loaded = True
        return self._queue

    @queue.setter
    def queue(self, value: Any) -> None:
        self._queue = value
        self._queue_loaded = True

    @queue.deleter
    def queue(self) -> None:
        self._queue = None
        self._queue_loaded = False

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return bool(self.DEBATE_ACTION_PATTERN.match(path))

    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route GET requests to appropriate methods."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _intervention_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for intervention endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        match = self.DEBATE_ACTION_PATTERN.match(path)
        if not match:
            return None

        debate_id, action = match.groups()

        # Validate debate ID
        is_valid, err = validate_path_segment(debate_id, "debate_id", SAFE_ID_PATTERN)
        if not is_valid:
            return error_response(err, 400)

        if action == "reasoning":
            return self._get_reasoning_summary(debate_id)

        if action == "intervene":
            # POST only for intervene
            return error_response(
                "Use POST to submit interventions",
                405,
                headers={"Allow": "POST"},
            )

        return None

    @handle_errors("debate intervention")
    @require_permission("debates:update")
    def handle_post(self, path: str, body: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle POST requests for debate intervention.

        Accepts:
            {
                "type": "redirect"|"constraint"|"challenge"|"evidence_request",
                "content": "...",
                "apply_at_round": N  (optional, 0 = next available)
            }

        Returns:
            {
                "intervention_id": "...",
                "status": "queued",
                "apply_at_round": N
            }
        """
        match = self.DEBATE_ACTION_PATTERN.match(path)
        if not match:
            return None

        debate_id, action = match.groups()

        # Validate debate ID
        is_valid, err = validate_path_segment(debate_id, "debate_id", SAFE_ID_PATTERN)
        if not is_valid:
            return error_response(err, 400)

        if action == "intervene":
            return self._submit_intervention(debate_id, body, handler)

        return None

    def _submit_intervention(self, debate_id: str, body: Any, handler: Any) -> HandlerResult:
        """Submit a mid-debate intervention.

        Args:
            debate_id: ID of the target debate
            body: Request body with type, content, and optional apply_at_round
            handler: HTTP request handler for auth context

        Returns:
            JSON response with intervention details
        """
        if not self.queue:
            return error_response("Intervention module not available", 503)

        if not isinstance(body, dict):
            return error_response("Request body must be a JSON object", 400)

        # Validate required fields
        intervention_type = body.get("type")
        if intervention_type is None:
            return error_response("Missing required field: type", 400)
        if not isinstance(intervention_type, str) or not intervention_type.strip():
            return error_response("Field 'type' must be a non-empty string", 400)
        intervention_type = intervention_type.strip()

        valid_types = ["redirect", "constraint", "challenge", "evidence_request"]
        if intervention_type not in valid_types:
            return error_response(
                f"Invalid type: {intervention_type}. Must be one of: {valid_types}",
                400,
            )

        content = body.get("content")
        if content is None:
            return error_response("Missing required field: content", 400)
        if not isinstance(content, str) or not content.strip():
            return error_response("Field 'content' must be a non-empty string", 400)

        # Sanitize content length
        content = content.strip()[:2000]

        apply_at_round = body.get("apply_at_round", 0)
        if apply_at_round is None:
            apply_at_round = 0
        elif (
            isinstance(apply_at_round, bool)
            or not isinstance(apply_at_round, int)
            or apply_at_round < 0
        ):
            return error_response("Field 'apply_at_round' must be a non-negative integer", 400)

        metadata = body.get("metadata", {})
        if metadata is None:
            metadata = {}
        elif not isinstance(metadata, dict):
            return error_response("Field 'metadata' must be an object", 400)

        # Extract user info from auth context if available
        user_id = body.get("user_id", "")
        if user_id is None:
            user_id = ""
        elif not isinstance(user_id, str):
            return error_response("Field 'user_id' must be a string", 400)

        if not user_id:
            try:
                from aragora.billing.jwt_auth import extract_user_from_request

                auth_ctx = extract_user_from_request(handler)
                if hasattr(auth_ctx, "user_id"):
                    user_id = auth_ctx.user_id or ""
            except (ImportError, AttributeError, TypeError, RuntimeError):
                pass

        try:
            intervention = self.queue.queue_intervention(
                debate_id=debate_id,
                intervention_type=intervention_type,
                content=content,
                user_id=user_id,
                apply_at_round=apply_at_round,
                metadata=metadata,
            )

            return json_response(
                {
                    "intervention_id": intervention.intervention_id,
                    "status": intervention.status.value,
                    "apply_at_round": intervention.apply_at_round,
                    "type": intervention.intervention_type.value,
                    "debate_id": debate_id,
                },
                status=201,
            )

        except ValueError as e:
            logger.warning("Invalid intervention request for debate %s: %s", debate_id, e)
            return error_response("Invalid intervention request", 400)
        except (AttributeError, RuntimeError, TypeError) as e:
            logger.exception("Failed to queue intervention: %s", e)
            return error_response(safe_error_message(e, "queue intervention"), 500)

    def _get_reasoning_summary(self, debate_id: str) -> HandlerResult:
        """Get per-agent reasoning chains, key cruxes, and unresolved disagreements.

        Combines data from multiple sources:
        - Intervention queue: applied/pending interventions and effects
        - Debate state: agent reasoning chains, crux points
        - Belief network: unresolved disagreements

        Args:
            debate_id: ID of the debate

        Returns:
            JSON response with reasoning summary
        """
        summary: dict[str, Any] = {
            "debate_id": debate_id,
            "agents": [],
            "cruxes": [],
            "unresolved_disagreements": [],
            "interventions": {},
        }

        # Intervention data
        if self.queue:
            try:
                summary["interventions"] = self.queue.get_reasoning_summary(debate_id)
            except (AttributeError, RuntimeError, TypeError) as e:
                logger.debug("Failed to get intervention summary: %s", e)

        # Try to fetch active debate state for reasoning chains
        try:
            from aragora.server.stream.state_manager import get_active_debates

            active_debates = get_active_debates()
            debate_state = active_debates.get(debate_id)

            if debate_state and isinstance(debate_state, dict):
                # Extract per-agent reasoning from debate metadata
                agents_data = debate_state.get("agents", [])
                if isinstance(agents_data, list):
                    for agent_info in agents_data:
                        if isinstance(agent_info, dict):
                            summary["agents"].append(
                                {
                                    "name": agent_info.get("name", "unknown"),
                                    "role": agent_info.get("role", ""),
                                    "last_position": agent_info.get("last_position", ""),
                                    "confidence": agent_info.get("confidence", 0.0),
                                }
                            )

                # Extract crux points from debate metadata
                cruxes = debate_state.get("cruxes", [])
                if isinstance(cruxes, list):
                    summary["cruxes"] = cruxes[:20]  # Limit to 20 crux points

                # Extract unresolved disagreements
                disagreements = debate_state.get("unresolved_disagreements", [])
                if isinstance(disagreements, list):
                    summary["unresolved_disagreements"] = disagreements[:20]

        except (ImportError, AttributeError, TypeError, RuntimeError) as e:
            logger.debug("Failed to fetch debate state for reasoning: %s", e)

        # Try to fetch crux data from belief network
        try:
            from aragora.reasoning.belief import get_belief_network

            belief_net = get_belief_network()
            if belief_net:
                crux_claims = belief_net.get_crux_claims(debate_id)
                if crux_claims and not summary["cruxes"]:
                    summary["cruxes"] = [
                        {
                            "claim": c.text if hasattr(c, "text") else str(c),
                            "confidence": getattr(c, "confidence", 0.5),
                            "contested_by": getattr(c, "contested_by", []),
                        }
                        for c in crux_claims[:20]
                    ]
        except (ImportError, AttributeError, TypeError, RuntimeError) as e:
            logger.debug("Failed to fetch belief network data: %s", e)

        return json_response({"data": summary})
