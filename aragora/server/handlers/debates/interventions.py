"""
Debate intervention endpoint handlers.

Provides HTTP endpoints for human intervention in live debates:
- POST /api/v1/debates/{id}/pause      -- Pause a running debate
- POST /api/v1/debates/{id}/resume     -- Resume a paused debate
- POST /api/v1/debates/{id}/nudge      -- Send a nudge/hint to agents
- POST /api/v1/debates/{id}/challenge  -- Inject a counterargument
- POST /api/v1/debates/{id}/inject-evidence -- Inject evidence
- GET  /api/v1/debates/{id}/intervention-log -- Retrieve intervention log

Follows existing debate handler patterns (BaseHandler mixin, @handle_errors,
strip_version_prefix, RBAC decorators).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from aragora.rbac.decorators import require_permission
from aragora.server.validation import validate_debate_id

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..openapi_decorator import api_endpoint

logger = logging.getLogger(__name__)

# Statuses under which a debate accepts interventions. Reuses the canonical
# active-status set (aragora.server.handlers.admin.dashboard_metrics), plus
# "paused" so a paused debate can still be resumed/nudged. Anything else
# (completed / cancelled / error / failed) is finished: POST actions refuse.
from ..admin.dashboard_metrics import ACTIVE_DEBATE_STATUSES

_INTERVENTION_LIVE_STATUSES = frozenset(ACTIVE_DEBATE_STATUSES | {"paused"})

# Route patterns managed by DebateInterventionsHandler
INTERVENTION_ROUTES = [
    "/api/v1/debates/*/pause",
    "/api/v1/debates/*/resume",
    "/api/v1/debates/*/nudge",
    "/api/v1/debates/*/challenge",
    "/api/v1/debates/*/inject-evidence",
    "/api/v1/debates/*/intervention-log",
]


def _strip_version_prefix(path: str) -> str:
    """Normalize versioned paths to unversioned for consistent matching."""
    return path.replace("/api/v1/", "/api/").replace("/api/v2/", "/api/")


def _extract_debate_id_from_path(path: str) -> tuple[str | None, str | None]:
    """Extract and validate debate ID from intervention path.

    Handles paths like /api/v1/debates/{id}/pause or /api/debates/{id}/pause.

    Returns:
        (debate_id, error_message) -- error_message is set if invalid.
    """
    normalized = _strip_version_prefix(path)
    # ['', 'api', 'debates', '{id}', 'pause'] — EXACTLY five segments.
    # A `<` check would let /api/debates/{id}/anything/pause through and
    # act on {id}; extra segments are rejected outright.
    parts = normalized.split("/")
    if len(parts) != 5:
        return None, "Invalid path"

    debate_id = parts[3]
    is_valid, err = validate_debate_id(debate_id)
    if not is_valid:
        return None, err

    return debate_id, None


class _HandlerProtocol(Protocol):
    """Protocol for type-checking the mixin composition."""

    ctx: dict[str, Any]

    def read_json_body(
        self, handler: Any, max_size: int | None = None
    ) -> dict[str, Any] | None: ...

    def get_current_user(self, handler: Any) -> Any: ...


class DebateInterventionsHandler(BaseHandler):
    """Handler for debate intervention endpoints.

    Manages pause/resume, nudges, challenges, and evidence injection
    for live debates.
    """

    ROUTES = INTERVENTION_ROUTES

    # RouteIndex.build() stores ROUTES entries as literal exact-match keys, so
    # the wildcard strings above can never match a real request path. Prefix
    # registration is what makes these routes reachable: RouteIndex consults
    # can_handle() for every prefix candidate, and ExplainabilityHandler (the
    # earlier-registered handler sharing this prefix) rejects intervention
    # suffixes, so dispatch lands here deterministically. Only the versioned
    # form is registered — unversioned /api/debates/{id}/* paths are claimed
    # by DebatesHandler's /api/debates prefix before this handler is scanned.
    ROUTE_PREFIXES = ["/api/v1/debates/"]

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        if server_context is not None:
            self.ctx = server_context
        else:
            self.ctx = ctx or {}

    # ------------------------------------------------------------------
    # Route matching
    # ------------------------------------------------------------------

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path.

        Enforces the exact shape /api/debates/{id}/{action} (post version
        strip). Suffix matching alone would claim malformed paths like
        /api/v1/debates/{id}/anything/pause and act on {id}; those must
        instead fall through to DebatesHandler's slug lookup (404).
        """
        normalized = _strip_version_prefix(path)
        if not normalized.startswith("/api/debates/"):
            return False
        parts = normalized.split("/")
        if len(parts) != 5:
            return False
        return parts[4] in (
            "pause",
            "resume",
            "nudge",
            "challenge",
            "inject-evidence",
            "intervention-log",
        )

    # ------------------------------------------------------------------
    # GET handler
    # ------------------------------------------------------------------

    @handle_errors("debate interventions")
    @require_permission("debates:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests.

        Gated by debates:read like every sibling debate read (evidence,
        checkpoints, analysis): the intervention log contains intervener
        user_ids and nudge/challenge/injected-evidence text.
        """
        normalized = _strip_version_prefix(path)
        if normalized.endswith("/intervention-log"):
            return self._get_intervention_log(path, handler)
        return None

    # ------------------------------------------------------------------
    # POST handler
    # ------------------------------------------------------------------

    @handle_errors("debate interventions")
    @require_permission("debates:update")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route POST requests to intervention methods."""
        normalized = _strip_version_prefix(path)

        if normalized.endswith("/pause"):
            return self._pause_debate(path, handler)
        if normalized.endswith("/resume"):
            return self._resume_debate(path, handler)
        if normalized.endswith("/nudge"):
            return self._nudge_debate(path, handler)
        if normalized.endswith("/challenge"):
            return self._challenge_debate(path, handler)
        if normalized.endswith("/inject-evidence"):
            return self._inject_evidence(path, handler)

        return None

    # ------------------------------------------------------------------
    # Endpoint implementations
    # ------------------------------------------------------------------

    @api_endpoint(
        method="POST",
        path="/api/v1/debates/{id}/pause",
        summary="Pause a running debate",
        description="Pause a live debate. The debate must be in a running state.",
        tags=["Debate Interventions"],
        parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
        responses={
            "200": {"description": "Debate paused successfully"},
            "400": {"description": "Debate cannot be paused (wrong state)"},
            "404": {"description": "Debate not found"},
        },
    )
    @handle_errors("pause debate")
    def _pause_debate(self, path: str, handler: Any) -> HandlerResult:
        debate_id, err = _extract_debate_id_from_path(path)
        if err or debate_id is None:
            return error_response(err or "Invalid path", 400)

        manager, refusal = self._acquire_live_manager(debate_id, handler)
        if refusal is not None:
            return refusal

        user_id = self._extract_user_id(handler)

        try:
            entry = manager.pause(user_id=user_id)
        except ValueError as exc:
            return error_response(str(exc), 400)

        return json_response(
            {
                "success": True,
                "debate_id": debate_id,
                "state": "paused",
                "intervention": entry.to_dict(),
            }
        )

    @api_endpoint(
        method="POST",
        path="/api/v1/debates/{id}/resume",
        summary="Resume a paused debate",
        description="Resume a debate that was previously paused.",
        tags=["Debate Interventions"],
        parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
        responses={
            "200": {"description": "Debate resumed successfully"},
            "400": {"description": "Debate cannot be resumed (wrong state)"},
            "404": {"description": "Debate not found"},
        },
    )
    @handle_errors("resume debate")
    def _resume_debate(self, path: str, handler: Any) -> HandlerResult:
        debate_id, err = _extract_debate_id_from_path(path)
        if err or debate_id is None:
            return error_response(err or "Invalid path", 400)

        manager, refusal = self._acquire_live_manager(debate_id, handler)
        if refusal is not None:
            return refusal

        user_id = self._extract_user_id(handler)

        try:
            entry = manager.resume(user_id=user_id)
        except ValueError as exc:
            return error_response(str(exc), 400)

        return json_response(
            {
                "success": True,
                "debate_id": debate_id,
                "state": "running",
                "intervention": entry.to_dict(),
            }
        )

    @api_endpoint(
        method="POST",
        path="/api/v1/debates/{id}/nudge",
        summary="Send a nudge to the debate",
        description="Send a nudge/hint message to steer the debate. Optionally target a specific agent.",
        tags=["Debate Interventions"],
        parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
        responses={
            "200": {"description": "Nudge delivered successfully"},
            "400": {"description": "Invalid request or debate completed"},
            "404": {"description": "Debate not found"},
        },
    )
    @handle_errors("nudge debate")
    def _nudge_debate(self, path: str, handler: Any) -> HandlerResult:
        debate_id, err = _extract_debate_id_from_path(path)
        if err or debate_id is None:
            return error_response(err or "Invalid path", 400)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid or missing JSON body", 400)

        message = (body.get("message") or "").strip()
        if not message:
            return error_response("Missing required field: message", 400)

        target_agent = body.get("target_agent")
        user_id = self._extract_user_id(handler)

        manager, refusal = self._acquire_live_manager(debate_id, handler)
        if refusal is not None:
            return refusal

        try:
            entry = manager.nudge(
                message=message,
                user_id=user_id,
                target_agent=target_agent,
            )
        except ValueError as exc:
            return error_response(str(exc), 400)

        return json_response(
            {
                "success": True,
                "debate_id": debate_id,
                "intervention": entry.to_dict(),
            }
        )

    @api_endpoint(
        method="POST",
        path="/api/v1/debates/{id}/challenge",
        summary="Inject a challenge into the debate",
        description="Inject a counterargument or challenge that agents must address.",
        tags=["Debate Interventions"],
        parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
        responses={
            "200": {"description": "Challenge injected successfully"},
            "400": {"description": "Invalid request or debate completed"},
            "404": {"description": "Debate not found"},
        },
    )
    @handle_errors("challenge debate")
    def _challenge_debate(self, path: str, handler: Any) -> HandlerResult:
        debate_id, err = _extract_debate_id_from_path(path)
        if err or debate_id is None:
            return error_response(err or "Invalid path", 400)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid or missing JSON body", 400)

        challenge_text = (body.get("challenge") or "").strip()
        if not challenge_text:
            return error_response("Missing required field: challenge", 400)

        user_id = self._extract_user_id(handler)

        manager, refusal = self._acquire_live_manager(debate_id, handler)
        if refusal is not None:
            return refusal

        try:
            entry = manager.challenge(
                challenge_text=challenge_text,
                user_id=user_id,
            )
        except ValueError as exc:
            return error_response(str(exc), 400)

        return json_response(
            {
                "success": True,
                "debate_id": debate_id,
                "intervention": entry.to_dict(),
            }
        )

    @api_endpoint(
        method="POST",
        path="/api/v1/debates/{id}/inject-evidence",
        summary="Inject evidence into the debate",
        description="Inject external evidence with optional source citation into the debate.",
        tags=["Debate Interventions"],
        parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
        responses={
            "200": {"description": "Evidence injected successfully"},
            "400": {"description": "Invalid request or debate completed"},
            "404": {"description": "Debate not found"},
        },
    )
    @handle_errors("inject evidence")
    def _inject_evidence(self, path: str, handler: Any) -> HandlerResult:
        debate_id, err = _extract_debate_id_from_path(path)
        if err or debate_id is None:
            return error_response(err or "Invalid path", 400)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid or missing JSON body", 400)

        evidence = (body.get("evidence") or "").strip()
        if not evidence:
            return error_response("Missing required field: evidence", 400)

        source = body.get("source")
        user_id = self._extract_user_id(handler)

        manager, refusal = self._acquire_live_manager(debate_id, handler)
        if refusal is not None:
            return refusal

        try:
            entry = manager.inject_evidence(
                evidence=evidence,
                source=source,
                user_id=user_id,
            )
        except ValueError as exc:
            return error_response(str(exc), 400)

        return json_response(
            {
                "success": True,
                "debate_id": debate_id,
                "intervention": entry.to_dict(),
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/{id}/intervention-log",
        summary="Get intervention history",
        description="Retrieve the full intervention log for a debate.",
        tags=["Debate Interventions"],
        parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
        responses={
            "200": {"description": "Intervention log retrieved"},
            "400": {"description": "Invalid debate ID"},
        },
    )
    @handle_errors("get intervention log")
    def _get_intervention_log(self, path: str, handler: Any) -> HandlerResult:
        debate_id, err = _extract_debate_id_from_path(path)
        if err or debate_id is None:
            return error_response(err or "Invalid path", 400)

        from aragora.debate.intervention import get_intervention_manager

        manager = get_intervention_manager(debate_id, create=False)
        if manager is None:
            # Distinguish "real debate, no interventions yet" (empty log)
            # from "debate does not exist" (404) — same existence gate as
            # the POST actions.
            if not self._debate_exists(debate_id):
                return error_response(f"Debate not found: {debate_id}", 404)
            return json_response(
                {
                    "debate_id": debate_id,
                    "state": "unknown",
                    "entry_count": 0,
                    "entries": [],
                }
            )

        log = manager.get_log()
        result = log.to_dict()
        result["state"] = manager.state.value
        return json_response(result)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _debate_exists(self, debate_id: str) -> bool:
        """Return True if the debate is real: known intervention manager,
        active debate state, or durable storage.

        Checked BEFORE creating an intervention manager so that arbitrary
        valid-looking IDs cannot mint global intervention state for
        nonexistent debates (which would also poison a future debate that
        reuses the ID). Mirrors the existence resolution used by sibling
        debates handlers (create.py cancel, costs.py): active state first,
        then storage.get_debate().
        """
        from aragora.debate.intervention import get_intervention_manager

        # An existing manager implies a previously validated debate
        # (managers are only created after this check passes) — keeps
        # resume/log working even if state and storage have moved on.
        if get_intervention_manager(debate_id, create=False) is not None:
            return True

        try:
            from aragora.server.state import get_state_manager

            if get_state_manager().get_debate(debate_id) is not None:
                return True
        except ImportError:
            pass  # minimal deployments without the state manager

        storage = self.get_storage()
        if storage is None:
            return False
        return storage.get_debate(debate_id) is not None

    def _debate_liveness(self, debate_id: str) -> tuple[str, str | None]:
        """Classify a debate for intervention eligibility.

        Returns (verdict, status) with verdict one of:
        - "live":     interventions may act (active server state or a stored
                      status in the live set — including "paused" so resume
                      keeps working)
        - "finished": the debate exists but has terminated (completed /
                      cancelled / error); actions must be refused even though
                      the log stays readable
        - "missing":  no trace of the debate anywhere

        Storage status is consulted even when an intervention manager already
        exists, so a manager left over from a debate that has since completed
        refuses new actions. The manager-only fast path applies only when
        both state and storage are silent (keeps legacy resume working).
        """
        from aragora.debate.intervention import get_intervention_manager

        def _verdict(status: str | None) -> tuple[str, str | None]:
            # Fail CLOSED: an absent/unparseable status is NOT proof of
            # liveness — treat it as finished rather than minting
            # intervention state for a debate of unknown standing.
            if status is not None and status in _INTERVENTION_LIVE_STATUSES:
                return ("live", status)
            return ("finished", status if status is not None else "unknown")

        try:
            from aragora.server.state import get_state_manager

            state = get_state_manager().get_debate(debate_id)
        except ImportError:
            state = None  # minimal deployments without the state manager
        if state is not None:
            raw = getattr(state, "status", None)
            return _verdict(str(raw) if raw is not None else None)

        storage = self.get_storage()
        if storage is not None:
            debate = storage.get_debate(debate_id)
            if debate is not None:
                raw = debate.get("status") if isinstance(debate, dict) else None
                return _verdict(str(raw) if raw is not None else None)

        if get_intervention_manager(debate_id, create=False) is not None:
            return ("live", None)

        return ("missing", None)

    def _acquire_live_manager(self, debate_id: str, handler: Any) -> tuple[Any, Any]:
        """Return (manager, None) for a live debate, else (None, error result).

        POST actions gate on LIVENESS, not mere existence: a completed stored
        debate must not mint a fresh InterventionManager (which starts in
        RUNNING state) and get "paused". Finished debates get the sibling
        cancel-on-completed convention (create.py): 400 with the status named.
        """
        from aragora.debate.intervention import get_intervention_manager

        verdict, status = self._debate_liveness(debate_id)
        if verdict == "missing":
            return None, error_response(f"Debate not found: {debate_id}", 404)
        if verdict == "finished":
            return None, error_response(
                f"Debate {debate_id} is not live (status: {status}); "
                "interventions are not available",
                400,
            )

        # Try to get the stream emitter from the handler for WebSocket events
        emitter = getattr(handler, "stream_emitter", None)
        fresh = get_intervention_manager(debate_id, create=False) is None
        manager = get_intervention_manager(debate_id, emitter=emitter, create=True)
        if manager is None:  # pragma: no cover - create=True always yields one
            return None, error_response(f"Debate not found: {debate_id}", 404)
        if fresh and status == "paused":
            # A manager reconstructed for a stored-paused debate (e.g. the
            # in-memory manager was lost on restart) must not start RUNNING,
            # or resume() would 400. Existing managers are the in-memory
            # truth and are never overridden.
            manager.restore_paused()
        return manager, None

    def _extract_user_id(self, handler: Any) -> str | None:
        """Extract user ID from the request handler, if available."""
        try:
            user = self.get_current_user(handler)
            if user:
                return getattr(user, "user_id", None)
        except (AttributeError, TypeError, ValueError):
            pass
        return None


__all__ = [
    "DebateInterventionsHandler",
    "INTERVENTION_ROUTES",
]
