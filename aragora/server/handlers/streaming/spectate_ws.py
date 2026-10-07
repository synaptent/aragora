"""WebSocket/SSE handler for real-time spectate events.

Endpoints:
- GET /api/v1/spectate/recent  - Get recent buffered spectate events
- GET /api/v1/spectate/status  - Get bridge status (active, subscribers, buffer size)
- GET /api/v1/spectate/stream  - Live SSE on the unified server, JSON/snapshot fallback here
"""

from __future__ import annotations

__all__ = [
    "SpectateStreamHandler",
    "SpectateVisibility",
    "authorize_spectate_request",
    "iter_live_spectate_sse_frames",
]

import json
import logging
import queue
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from aragora.tenancy.debate_access import (
    authorize_debate_write,
    debate_visible_to_org,
    find_debate_access,
)
from aragora.tenancy.record_scope import AUTH_REQUIRED, record_not_found, require_org_scope

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)

logger = logging.getLogger(__name__)

_RECENT_ACTIVITY_WINDOW_SECONDS = 300  # 5 min — matches demo loop interval
_STATUS_ACTIVITY_SCAN_LIMIT = 200
_DEFAULT_SPECTATE_EVENT_COUNT = 50
_MAX_SPECTATE_EVENT_COUNT = 500
_LIVE_SSE_HEARTBEAT_SECONDS = 15.0
_LIVE_SSE_QUEUE_SIZE = 256
_LIVE_SSE_RESYNC_SENTINEL = object()
_PUBLIC_PLAYGROUND_DEBATE_PREFIX = "playground_"
_SPECTATE_CACHE_CONTROL = "no-cache"


def _parse_event_timestamp(timestamp: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp into an aware UTC datetime."""
    if not timestamp:
        return None

    normalized = timestamp.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _summarize_bridge_activity(events: list[Any], *, bridge_running: bool) -> dict[str, Any]:
    """Summarize recent bridge activity for truthful spectate readiness."""
    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(seconds=_RECENT_ACTIVITY_WINDOW_SECONDS)

    last_event_at: str | None = None
    last_event_dt: datetime | None = None
    recent_events: list[Any] = []
    live_debate_summaries: dict[str, dict[str, Any]] = {}

    for event in events:
        event_timestamp = getattr(event, "timestamp", None)
        event_dt = _parse_event_timestamp(event_timestamp)

        if event_dt and (last_event_dt is None or event_dt > last_event_dt):
            last_event_dt = event_dt
            last_event_at = event_timestamp

        if event_dt is None or event_dt < recent_cutoff:
            continue

        recent_events.append(event)
        debate_id = getattr(event, "debate_id", None)
        if not debate_id:
            continue

        summary = live_debate_summaries.setdefault(
            debate_id,
            {
                "debate_id": debate_id,
                "recent_event_count": 0,
                "last_event_at": event_timestamp,
                "_last_event_dt": event_dt,
                "_event_types": set(),
            },
        )
        summary["recent_event_count"] += 1
        if event_dt >= summary["_last_event_dt"]:
            summary["last_event_at"] = event_timestamp
            summary["_last_event_dt"] = event_dt
        summary["_event_types"].add(getattr(event, "event_type", "event"))

    live_debates = [
        {
            "debate_id": debate_id,
            "recent_event_count": summary["recent_event_count"],
            "last_event_at": summary["last_event_at"],
            "event_types": sorted(summary["_event_types"]),
        }
        for debate_id, summary in live_debate_summaries.items()
    ]
    live_debates.sort(
        key=lambda summary: _parse_event_timestamp(summary["last_event_at"])
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    if not bridge_running:
        bridge_state = "inactive"
    elif live_debates:
        bridge_state = "live_debates_available"
    elif recent_events:
        bridge_state = "activity_unattributed"
    else:
        bridge_state = "idle"

    activity_age_seconds = None
    if last_event_dt is not None:
        activity_age_seconds = max((now - last_event_dt).total_seconds(), 0.0)

    return {
        "bridge_state": bridge_state,
        "last_event_at": last_event_at,
        "activity_age_seconds": activity_age_seconds,
        "recent_activity_window_seconds": _RECENT_ACTIVITY_WINDOW_SECONDS,
        "recent_event_count": len(recent_events),
        "live_debate_count": len(live_debates),
        "live_debate_ids": [summary["debate_id"] for summary in live_debates],
        "live_debates": live_debates,
        "unattributed_recent_event_count": len(recent_events)
        - sum(summary["recent_event_count"] for summary in live_debates),
    }


def _redact_live_debate_details(
    summary: dict[str, Any], can_view: Callable[[str], bool]
) -> dict[str, Any]:
    """Keep the live debates the caller may see; count the rest as unattributed."""
    redacted = dict(summary)
    live_debates = [item for item in summary.get("live_debates", []) if can_view(item["debate_id"])]
    if redacted.get("bridge_state") == "live_debates_available" and not live_debates:
        redacted["bridge_state"] = "activity_unattributed"
    redacted["live_debate_count"] = len(live_debates)
    redacted["live_debate_ids"] = [item["debate_id"] for item in live_debates]
    redacted["live_debates"] = live_debates
    redacted["unattributed_recent_event_count"] = redacted.get("recent_event_count", 0) - sum(
        item["recent_event_count"] for item in live_debates
    )
    return redacted


def _resolve_debates_storage(storage: Any | None) -> Any | None:
    if storage is not None:
        return storage
    try:
        from aragora.server.storage import get_debates_db

        return get_debates_db()
    except (ImportError, RuntimeError, ValueError, OSError, sqlite3.Error):
        return None


def _is_public_spectate_debate(
    debate_id: str | None,
    *,
    storage: Any | None = None,
    visibility_cache: dict[str, bool] | None = None,
) -> bool:
    """Return True when debate-linked spectate events are safe for public callers."""
    if not debate_id:
        return True

    if visibility_cache is not None and debate_id in visibility_cache:
        return visibility_cache[debate_id]

    is_public = debate_id.startswith(_PUBLIC_PLAYGROUND_DEBATE_PREFIX)

    if not is_public:
        try:
            from aragora.server.handlers.debates.share import is_publicly_shared

            is_public = is_publicly_shared(debate_id)
        except (ImportError, RuntimeError, ValueError):
            is_public = False

    if not is_public:
        is_public_method = getattr(_resolve_debates_storage(storage), "is_public", None)
        if callable(is_public_method):
            try:
                is_public = bool(is_public_method(debate_id))
            except (RuntimeError, ValueError, OSError, sqlite3.Error):
                is_public = False

    if visibility_cache is not None:
        visibility_cache[debate_id] = is_public
    return is_public


class SpectateVisibility:
    """Which debates' spectate events one caller may see.

    Events of a public debate, and events not linked to any debate, are visible
    to everyone. Any other debate's events are visible only to callers acting
    for the org that owns it; a debate with no recorded org is visible to no
    one. Decisions are cached for one request or stream.
    """

    def __init__(self, org_id: str | None = None, *, storage: Any | None = None) -> None:
        self.org_id = org_id if isinstance(org_id, str) and org_id else None
        self._storage = storage
        self._storage_resolved = storage is not None
        self._public: dict[str, bool] = {}
        self._visible: dict[str, bool] = {}

    def _get_storage(self) -> Any | None:
        if not self._storage_resolved:
            self._storage = _resolve_debates_storage(None)
            self._storage_resolved = True
        return self._storage

    def is_public(self, debate_id: Any) -> bool:
        if not isinstance(debate_id, str) or not debate_id:
            return False
        return _is_public_spectate_debate(
            debate_id, storage=self._get_storage(), visibility_cache=self._public
        )

    def can_view(self, debate_id: Any) -> bool:
        if debate_id is None or debate_id == "":
            return True
        if not isinstance(debate_id, str):
            return False
        cached = self._visible.get(debate_id)
        if cached is not None:
            return cached
        if self.is_public(debate_id):
            self._visible[debate_id] = True
            return True
        if self.org_id is None:
            self._visible[debate_id] = False
            return False
        access = find_debate_access(self._get_storage(), debate_id)
        if access is None:
            # Not cached: a debate can be registered after its first events.
            return False
        visible = access.debate_id == debate_id and debate_visible_to_org(access, self.org_id)
        self._visible[debate_id] = visible
        return visible

    def can_view_event(self, event: Any) -> bool:
        return self.can_view(getattr(event, "debate_id", None))

    def filter_events(self, events: list[Any]) -> list[Any]:
        return [event for event in events if self.can_view_event(event)]


def authorize_spectate_request(
    handler: Any | None,
    query_params: dict[str, Any] | None,
    *,
    storage: Any | None = None,
) -> SpectateVisibility | HandlerResult:
    """The caller's :class:`SpectateVisibility`, or the error when the request
    names a debate (``?debate_id=``) that is neither public nor the caller's org's.

    Anonymous callers and callers without an org still get a visibility (public
    events only) when no private debate is named.
    """
    if handler is None:
        scope, denial = None, json_response(AUTH_REQUIRED.body(), status=AUTH_REQUIRED.status)
    else:
        scope, denial = require_org_scope(handler)
    visibility = SpectateVisibility(scope.org_id if scope else None, storage=storage)
    debate_id = query_params.get("debate_id") if query_params else None
    if debate_id and not visibility.is_public(debate_id):
        if denial is not None:
            return denial
        if not visibility.can_view(debate_id):
            return record_not_found("Debate")
    return visibility


def _sse_frame(event_type: str, data: Any) -> str:
    """Format a single SSE frame."""
    payload = json.dumps(data, default=str, separators=(",", ":"))
    return f"event: {event_type}\ndata: {payload}\n\n"


def _spectate_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    """Build headers shared by non-cacheable spectate responses."""
    return {"Cache-Control": _SPECTATE_CACHE_CONTROL, **(headers or {})}


def _get_requested_count(query_params: dict[str, Any] | None) -> int:
    """Return the bounded recent-event count requested by the caller."""
    count_str = (
        query_params.get("count", str(_DEFAULT_SPECTATE_EVENT_COUNT))
        if query_params
        else str(_DEFAULT_SPECTATE_EVENT_COUNT)
    )
    try:
        return min(int(count_str), _MAX_SPECTATE_EVENT_COUNT)
    except (ValueError, TypeError):
        return _DEFAULT_SPECTATE_EVENT_COUNT


def _event_matches_scope(
    event: Any,
    *,
    debate_id: str | None,
    pipeline_id: str | None,
) -> bool:
    """Return True when a spectate event belongs to the requested scope."""
    if debate_id and getattr(event, "debate_id", None) != debate_id:
        return False
    if pipeline_id and getattr(event, "pipeline_id", None) != pipeline_id:
        return False
    return True


def _filter_spectate_events(events: list[Any], query_params: dict[str, Any] | None) -> list[Any]:
    """Filter buffered spectate events using the shared query semantics."""
    debate_id = query_params.get("debate_id") if query_params else None
    pipeline_id = query_params.get("pipeline_id") if query_params else None
    return [
        event
        for event in events
        if _event_matches_scope(event, debate_id=debate_id, pipeline_id=pipeline_id)
    ]


def iter_live_spectate_sse_frames(
    query_params: dict[str, Any],
    *,
    heartbeat_interval: float = _LIVE_SSE_HEARTBEAT_SECONDS,
    bridge: Any | None = None,
    org_id: str | None = None,
    storage: Any | None = None,
):
    """Yield a live SSE stream with an initial buffered snapshot and heartbeats.

    Only events visible to a caller acting for ``org_id`` are sent (public
    events only when it is None); see :class:`SpectateVisibility`. Callers must
    authorize a named ``debate_id`` first with :func:`authorize_spectate_request`.
    """
    visibility = SpectateVisibility(org_id, storage=storage)
    if bridge is None:
        from aragora.spectate.ws_bridge import get_spectate_bridge

        bridge = get_spectate_bridge()

    if not bridge.running:
        bridge.start()

    debate_id = query_params.get("debate_id")
    pipeline_id = query_params.get("pipeline_id")
    backlog = visibility.filter_events(
        _filter_spectate_events(
            bridge.get_recent_events(_get_requested_count(query_params)),
            query_params,
        )
    )
    metadata: dict[str, Any] = {
        "mode": "live",
        "transport": "sse_live",
        "readiness": "live",
        "streaming_ready": True,
        "message": (
            "Spectate events are being delivered as a live SSE stream with an initial "
            "buffered snapshot."
        ),
        "count": len(backlog),
    }
    if debate_id:
        metadata["debate_id"] = debate_id
    if pipeline_id:
        metadata["pipeline_id"] = pipeline_id

    event_queue: queue.Queue[Any] = queue.Queue(maxsize=_LIVE_SSE_QUEUE_SIZE)
    resync_state = {"pending": False, "dropped_events": 0}

    def enqueue(event: Any) -> None:
        if not _event_matches_scope(event, debate_id=debate_id, pipeline_id=pipeline_id):
            return
        if not visibility.can_view_event(event):
            return
        if resync_state["pending"]:
            resync_state["dropped_events"] += 1
            return
        try:
            event_queue.put_nowait(event)
        except queue.Full:
            dropped_events = 1
            while True:
                try:
                    event_queue.get_nowait()
                    dropped_events += 1
                except queue.Empty:
                    break
            resync_state["pending"] = True
            resync_state["dropped_events"] += dropped_events
            try:
                # Stop the live stream as soon as possible so clients can resync
                # from /recent instead of silently rendering a truncated transcript.
                event_queue.put_nowait(_LIVE_SSE_RESYNC_SENTINEL)
            except queue.Full:
                logger.debug("spectate_live_sse_resync_enqueue_failed", exc_info=True)

    bridge.subscribe(enqueue)
    try:
        yield _sse_frame("connected", metadata).encode("utf-8")
        for event in backlog:
            yield _sse_frame("spectate", event.to_dict()).encode("utf-8")
        yield _sse_frame("snapshot_complete", metadata).encode("utf-8")

        while True:
            try:
                event = event_queue.get(timeout=heartbeat_interval)
            except queue.Empty:
                yield b": heartbeat\n\n"
                continue
            if event is _LIVE_SSE_RESYNC_SENTINEL:
                yield _sse_frame(
                    "resync_required",
                    {
                        **metadata,
                        "reason": "queue_overflow",
                        "dropped_events": resync_state["dropped_events"],
                        "message": (
                            "Live spectate delivery fell behind and needs a recent-event resync."
                        ),
                    },
                ).encode("utf-8")
                break
            yield _sse_frame("spectate", event.to_dict()).encode("utf-8")
    finally:
        bridge.unsubscribe(enqueue)


class SpectateStreamHandler(BaseHandler):
    """Handler for spectate stream endpoints.

    Serves buffered SpectatorStream preview data over HTTP.

    The unified HTTP server upgrades SSE callers on this same endpoint to a
    long-lived live stream via ``iter_live_spectate_sse_frames()``. This
    handler remains the JSON/finite-snapshot fallback for compatibility.
    """

    ROUTES = [
        "/api/v1/spectate/recent",
        "/api/v1/spectate/status",
        "/api/v1/spectate/stream",
        "/api/v1/spectate/emit",
    ]

    STREAM_MODE = "snapshot"
    STREAM_READINESS = "partial"
    STREAM_JSON_TRANSPORT = "json_preview"
    STREAM_SSE_TRANSPORT = "sse_snapshot"
    STREAM_JSON_MESSAGE = (
        "Buffered spectate events are available as a JSON preview on this endpoint. "
        "Request Accept: text/event-stream or ?format=sse for live SSE delivery on the "
        "unified server."
    )
    STREAM_SSE_MESSAGE = (
        "Buffered spectate events are being delivered as a finite SSE fallback here; "
        "the unified server serves live SSE on this endpoint."
    )

    @handle_errors("spectate")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests to the appropriate sub-handler."""
        if not path.startswith("/api/v1/spectate"):
            return None

        if path.endswith("/recent"):
            return self._handle_recent(query_params, handler)
        if path.endswith("/status"):
            return self._handle_status(handler)
        if path.endswith("/stream"):
            return self._handle_stream(query_params, handler)

        return None

    @handle_errors("spectate")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """POST /api/v1/spectate/emit — inject events for a debate of the caller's org."""
        if path != "/api/v1/spectate/emit":
            return None
        body = self.read_json_body(handler) if handler else {}
        if not body:
            return error_response("Missing JSON body", 400)
        write, denial = authorize_debate_write(
            handler, self.get_storage(), str(body.get("debate_id", "")).strip()
        )
        if write is None:
            return denial
        try:
            from aragora.spectate.ws_bridge import get_spectate_bridge, bind_spectate_context

            bridge = get_spectate_bridge()
            if not bridge.running:
                return json_response(
                    {"error": "Bridge not running"},
                    status=503,
                    headers=_spectate_headers(),
                )
            debate_id = write.debate_id
            events = body.get("events", [])
            if not events:
                events = [body]
            emitted = 0
            with bind_spectate_context(debate_id=debate_id):
                for event in events:
                    bridge._forward_event(
                        event_type=str(event.get("event_type", "info")),
                        agent=str(event.get("agent", "")),
                        details=str(event.get("details", "")),
                        round_number=event.get("round_number"),
                    )
                    emitted += 1
            return json_response(
                {"emitted": emitted, "debate_id": debate_id},
                headers=_spectate_headers(),
            )
        except ImportError:
            return json_response(
                {"error": "Bridge module unavailable"},
                status=503,
                headers=_spectate_headers(),
            )

    def _handle_recent(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        """GET /api/v1/spectate/recent -- get recent events from the buffer."""
        visibility = authorize_spectate_request(handler, query_params, storage=self.get_storage())
        if isinstance(visibility, HandlerResult):
            return visibility
        events = visibility.filter_events(self._get_recent_events(query_params))
        return json_response(self._recent_payload(events), headers=_spectate_headers())

    def _handle_stream(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        """GET /api/v1/spectate/stream -- finite SSE snapshot or JSON preview."""
        visibility = authorize_spectate_request(handler, query_params, storage=self.get_storage())
        if isinstance(visibility, HandlerResult):
            return visibility
        events = visibility.filter_events(self._get_recent_events(query_params))
        if self._wants_sse(query_params, handler):
            metadata = self._stream_metadata(
                query_params,
                count=len(events),
                transport=self.STREAM_SSE_TRANSPORT,
                message=self.STREAM_SSE_MESSAGE,
            )
            return HandlerResult(
                status_code=200,
                content_type="text/event-stream",
                body=self._build_sse_snapshot_body(events, metadata),
                headers=_spectate_headers(
                    {
                        "Connection": "keep-alive",
                        "Vary": "Accept",
                        "X-Accel-Buffering": "no",
                        "X-Aragora-Endpoint-State": self.STREAM_READINESS,
                        "X-Aragora-Stream-Mode": self.STREAM_MODE,
                        "X-Aragora-Stream-Transport": self.STREAM_SSE_TRANSPORT,
                    }
                ),
            )

        payload = self._recent_payload(events)
        payload.update(
            self._stream_metadata(
                query_params,
                count=len(events),
                transport=self.STREAM_JSON_TRANSPORT,
                message=self.STREAM_JSON_MESSAGE,
            )
        )
        return json_response(
            payload,
            headers=_spectate_headers(
                {
                    "Vary": "Accept",
                    "X-Aragora-Endpoint-State": self.STREAM_READINESS,
                    "X-Aragora-Stream-Mode": self.STREAM_MODE,
                    "X-Aragora-Stream-Transport": self.STREAM_JSON_TRANSPORT,
                }
            ),
        )

    def _get_recent_events(self, query_params: dict[str, Any]) -> list[Any]:
        """Return filtered recent spectate events from the bridge buffer."""
        try:
            from aragora.spectate.ws_bridge import get_spectate_bridge

            bridge = get_spectate_bridge()
            events = bridge.get_recent_events(_get_requested_count(query_params))
            return _filter_spectate_events(events, query_params)
        except ImportError:
            return []

    def _recent_payload(self, events: list[Any]) -> dict[str, Any]:
        """Build the recent-events payload shared by snapshot endpoints."""
        return {
            "events": [e.to_dict() for e in events],
            "count": len(events),
        }

    def _stream_metadata(
        self,
        query_params: dict[str, Any],
        *,
        count: int,
        transport: str,
        message: str,
    ) -> dict[str, Any]:
        """Build stream metadata shared across JSON and SSE snapshot responses."""
        metadata: dict[str, Any] = {
            "mode": self.STREAM_MODE,
            "transport": transport,
            "readiness": self.STREAM_READINESS,
            "streaming_ready": False,
            "message": message,
            "count": count,
        }
        if query_params.get("debate_id"):
            metadata["debate_id"] = query_params["debate_id"]
        if query_params.get("pipeline_id"):
            metadata["pipeline_id"] = query_params["pipeline_id"]
        return metadata

    def _build_sse_snapshot_body(self, events: list[Any], metadata: dict[str, Any]) -> bytes:
        """Serialize buffered spectate events into a finite SSE snapshot body."""
        frames = [_sse_frame("connected", metadata)]
        for event in events:
            event_type = getattr(event, "event_type", None) or "event"
            frames.append(_sse_frame(event_type, event.to_dict()))
        frames.append(_sse_frame("snapshot_complete", metadata))
        return "".join(frames).encode("utf-8")

    def _wants_sse(self, query_params: dict[str, Any], handler: Any) -> bool:
        """Return True when the caller requested an SSE response."""
        if (query_params.get("format") or "").lower() == "sse":
            return True
        headers = getattr(handler, "headers", {}) or {}
        accept = headers.get("Accept") or headers.get("accept") or ""
        return "text/event-stream" in accept

    def _handle_status(self, handler: Any) -> HandlerResult:
        """GET /api/v1/spectate/status -- bridge status."""
        try:
            from aragora.spectate.ws_bridge import get_spectate_bridge

            bridge = get_spectate_bridge()
            summary = _summarize_bridge_activity(
                bridge.get_recent_events(_STATUS_ACTIVITY_SCAN_LIMIT),
                bridge_running=bridge.running,
            )
            visibility = authorize_spectate_request(handler, None, storage=self.get_storage())
            if isinstance(visibility, HandlerResult):
                return visibility
            summary = _redact_live_debate_details(summary, visibility.can_view)
            return json_response(
                {
                    "active": bridge.running,
                    "subscribers": bridge.subscriber_count,
                    "buffer_size": bridge.buffer_size,
                    **summary,
                },
                headers=_spectate_headers(),
            )
        except ImportError:
            return json_response(
                {
                    "active": False,
                    "subscribers": 0,
                    "buffer_size": 0,
                    "bridge_state": "inactive",
                    "last_event_at": None,
                    "activity_age_seconds": None,
                    "recent_activity_window_seconds": _RECENT_ACTIVITY_WINDOW_SECONDS,
                    "recent_event_count": 0,
                    "live_debate_count": 0,
                    "live_debate_ids": [],
                    "live_debates": [],
                    "unattributed_recent_event_count": 0,
                },
                headers=_spectate_headers(),
            )
