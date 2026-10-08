"""
Public Spectator Share Handler.

Allows debate owners to generate public share links for the public debate viewer,
and provides a public SSE endpoint for shared debates.

Routes:
    POST   /api/v1/debates/{id}/share             - Enable public sharing (debate's org only)
    DELETE /api/v1/debates/{id}/share             - Revoke public sharing (debate's org only)
    GET    /api/v1/debates/{id}/spectate/public   - Public SSE stream (no auth, rate-limited)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.tenancy.debate_access import (
    authorize_debate_read,
    authorize_debate_write,
    note_public_revoked,
)
from aragora.tenancy.record_scope import record_not_found, scope_denial_first

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State: which debates are publicly shared + concurrent spectator tracking
# ---------------------------------------------------------------------------

# debate_id -> True if publicly shared
_shared_debates: dict[str, bool] = {}

# debate_id -> set of active SSE queues
_public_collectors: dict[str, set[asyncio.Queue]] = {}  # type: ignore[type-arg]

# Maximum concurrent public spectators per debate
_MAX_PUBLIC_SPECTATORS = 10

# Default host for share URLs
_DEFAULT_HOST = os.environ.get("ARAGORA_DEFAULT_HOST", "localhost:8080")


def get_shared_debates() -> dict[str, bool]:
    """Return the shared debates registry. Used by tests."""
    return _shared_debates


def get_public_collectors() -> dict[str, set[asyncio.Queue]]:  # type: ignore[type-arg]
    """Return the public collectors registry. Used by tests and event bridge."""
    return _public_collectors


def is_publicly_shared(debate_id: str) -> bool:
    """Check whether a debate is publicly shared."""
    return _shared_debates.get(debate_id, False)


def set_public_spectate(debate_id: str, enabled: bool = True) -> None:
    """Mark a debate as publicly shared or revoke sharing.

    Called from playground handler to auto-enable sharing for live debates.
    """
    if enabled:
        _shared_debates[debate_id] = True
    else:
        _shared_debates.pop(debate_id, None)
        note_public_revoked()
        # Clean up any active collectors
        collectors = _public_collectors.pop(debate_id, None)
        if collectors:
            for q in collectors:
                try:
                    q.put_nowait({"type": "share_revoked", "timestamp": time.time()})
                except asyncio.QueueFull:
                    pass


def push_public_spectator_event(
    debate_id: str,
    event_type: str,
    agent: str = "",
    details: str = "",
    metric: float | None = None,
    round_number: int | None = None,
) -> int:
    """Push an event to all public SSE spectators of a debate.

    Returns the number of clients the event was pushed to.
    """
    if not is_publicly_shared(debate_id):
        return 0

    queues = _public_collectors.get(debate_id)
    if not queues:
        return 0

    event = {
        "type": event_type,
        "timestamp": time.time(),
        "agent": agent or None,
        "details": details or None,
        "metric": metric,
        "round": round_number,
    }

    pushed = 0
    dead: list[asyncio.Queue] = []  # type: ignore[type-arg]
    for q in queues:
        try:
            q.put_nowait(event)
            pushed += 1
        except asyncio.QueueFull:
            try:
                q.get_nowait()
                q.put_nowait(event)
                pushed += 1
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                dead.append(q)

    for q in dead:
        queues.discard(q)

    return pushed


def _reset_share_state() -> None:
    """Reset all share state. Used by tests."""
    _shared_debates.clear()
    _public_collectors.clear()
    note_public_revoked()


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class DebateShareHandler(BaseHandler):
    """Handler for public debate sharing and spectating."""

    ROUTES = [
        "/api/v1/debates/*/share",
        "/api/v1/debates/*/spectate/public",
    ]

    def __init__(self, ctx: dict | None = None):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        parts = path.split("/")
        # /api/v1/debates/{id}/share -> 6 parts
        # /api/v1/debates/{id}/spectate/public -> 7 parts
        if len(parts) == 6 and parts[5] == "share":
            return parts[1] == "api" and parts[2] == "v1" and parts[3] == "debates"
        if len(parts) == 7 and parts[5] == "spectate" and parts[6] == "public":
            return parts[1] == "api" and parts[2] == "v1" and parts[3] == "debates"
        return False

    def _extract_debate_id(self, path: str) -> str | None:
        """Extract debate ID from path."""
        parts = path.split("/")
        if len(parts) >= 5:
            return parts[4]
        return None

    def _get_storage(self) -> Any | None:
        storage = self.ctx.get("storage")
        if storage is not None:
            return storage
        try:
            from aragora.server.storage import get_debates_db

            return get_debates_db()
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            logger.debug("Debate storage unavailable while updating share state: %s", exc)
            return None

    def _set_public_storage_flag(
        self, storage: Any, debate_id: str, enabled: bool, org_id: str
    ) -> None:
        """Best-effort persistence for public share state."""
        setter = getattr(storage, "set_public", None)
        if not callable(setter):
            return

        try:
            setter(debate_id, enabled, org_id=org_id)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("Failed to persist public state for debate %s: %s", debate_id, exc)

    def _set_share(self, path: str, handler: Any, enabled: bool) -> HandlerResult:
        """Share or unshare the debate ``path`` names, for the debate's own org only.

        Another org's debate (public or not), one with no recorded org and a
        missing id all get the 404 of a missing debate, and nothing changes.
        """
        debate_ref = self._extract_debate_id(path)
        if not debate_ref:
            return error_response("Missing debate ID", 400)

        storage = self._get_storage()
        write, write_error = authorize_debate_write(handler, storage, debate_ref)
        if write is None:
            return write_error

        set_public_spectate(write.debate_id, enabled)
        self._set_public_storage_flag(storage, write.debate_id, enabled, write.scope.org_id)

        if not enabled:
            # Again after the stored flag: a stream may have re-read it in between.
            note_public_revoked()
            return json_response({"debate_id": write.debate_id, "public_spectate": False})

        host = _DEFAULT_HOST
        if handler and hasattr(handler, "headers"):
            host = handler.headers.get("Host", _DEFAULT_HOST)

        # Share links should land on the public debate viewer page. The
        # spectate API endpoint remains available separately via `sse_url`.
        share_url = f"/debate/{write.debate_id}"

        return json_response(
            {
                "debate_id": write.debate_id,
                "public_spectate": True,
                "share_url": share_url,
                "full_url": f"https://{host}{share_url}",
            }
        )

    # ------------------------------------------------------------------
    # GET /api/v1/debates/{id}/spectate/public
    # ------------------------------------------------------------------

    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        parts = path.split("/")
        if len(parts) == 7 and parts[5] == "spectate" and parts[6] == "public":
            debate_id = self._extract_debate_id(path)
            if not debate_id:
                return error_response("Missing debate ID", 400)
            return self._handle_public_spectate(debate_id)
        if len(parts) == 6 and parts[5] == "share":
            # Share state has no read route; give the read gate's answer, then
            # the missing-debate 404 (the registry turns None into a 500).
            debate_id, access_error = authorize_debate_read(handler, self._get_storage(), parts[4])
            if debate_id is None:
                return access_error
            return record_not_found("Debate")
        return None

    def _handle_public_spectate(self, debate_id: str) -> HandlerResult:
        """Handle public spectate request (non-streaming fallback)."""
        if not is_publicly_shared(debate_id):
            return json_response(
                {
                    "error": "This debate is not publicly shared",
                    "code": "not_shared",
                },
                status=403,
            )

        # Check concurrent spectator limit
        current = len(_public_collectors.get(debate_id, set()))
        if current >= _MAX_PUBLIC_SPECTATORS:
            return json_response(
                {
                    "error": "Maximum spectators reached for this debate",
                    "code": "spectator_limit",
                    "max_spectators": _MAX_PUBLIC_SPECTATORS,
                },
                status=429,
            )

        return json_response(
            {
                "debate_id": debate_id,
                "spectate_available": True,
                "public": True,
                "active_viewers": current,
                "max_viewers": _MAX_PUBLIC_SPECTATORS,
                "sse_url": f"/api/v1/debates/{debate_id}/spectate/public",
            }
        )

    # ------------------------------------------------------------------
    # POST /api/v1/debates/{id}/share
    # ------------------------------------------------------------------

    @handle_errors("debate share creation")
    @scope_denial_first
    @require_permission("debates:update")
    def handle_post(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        parts = path.split("/")
        if not (len(parts) == 6 and parts[5] == "share"):
            return None
        return self._set_share(path, handler, enabled=True)

    # ------------------------------------------------------------------
    # DELETE /api/v1/debates/{id}/share
    # ------------------------------------------------------------------

    @handle_errors("debate share deletion")
    @scope_denial_first
    @require_permission("debates:update")
    def handle_delete(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        parts = path.split("/")
        if not (len(parts) == 6 and parts[5] == "share"):
            return None
        return self._set_share(path, handler, enabled=False)


# ---------------------------------------------------------------------------
# Public SSE generator (mirrors spectate.py pattern)
# ---------------------------------------------------------------------------


async def public_spectate_sse_generator(
    debate_id: str,
    *,
    heartbeat_interval: float = 15.0,
    max_queue_size: int = 256,
):
    """Async generator yielding SSE-formatted event strings for public spectators.

    Only works if the debate has ``public_spectate`` enabled.
    Enforces a per-debate concurrent spectator limit.

    Args:
        debate_id: The debate to observe.
        heartbeat_interval: Seconds between keep-alive comments.
        max_queue_size: Max buffered events per client.
    """
    if not is_publicly_shared(debate_id):
        yield _sse_frame("error", {"error": "Debate is not publicly shared"})
        return

    # Check concurrent limit
    if debate_id not in _public_collectors:
        _public_collectors[debate_id] = set()

    if len(_public_collectors[debate_id]) >= _MAX_PUBLIC_SPECTATORS:
        yield _sse_frame("error", {"error": "Maximum spectators reached"})
        return

    queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
    _public_collectors[debate_id].add(queue)

    try:
        yield _sse_frame("connected", {"debate_id": debate_id, "public": True})

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                event_type = event.get("type", "event")
                if event_type == "share_revoked":
                    yield _sse_frame("share_revoked", {"debate_id": debate_id})
                    break
                yield _sse_frame(event_type, event)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
    finally:
        collectors = _public_collectors.get(debate_id)
        if collectors is not None:
            collectors.discard(queue)
            if not collectors:
                del _public_collectors[debate_id]


def _sse_frame(event_type: str, data: Any) -> str:
    """Format a single SSE frame."""
    payload = json.dumps(data, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


__all__ = [
    "DebateShareHandler",
    "get_public_collectors",
    "get_shared_debates",
    "is_publicly_shared",
    "public_spectate_sse_generator",
    "push_public_spectator_event",
    "set_public_spectate",
]
