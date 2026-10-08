"""
WebSocket connection handling mixin for AiohttpUnifiedServer.

Extracts the WebSocket handler, voice WebSocket handler, event drain loop,
and all supporting validation methods into a dedicated mixin class.

This keeps the core server class focused on initialization, state management,
and debate lifecycle, while this mixin handles the real-time client connections.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import secrets
import time
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import aiohttp.web

from .emitter import TokenBucket
from .events import (
    AudienceMessage,
    StreamEvent,
    StreamEventType,
)

# Import WebSocket config from centralized location
from aragora.config import WS_MAX_MESSAGE_SIZE
from aragora.server.cors_config import WS_ALLOWED_ORIGINS
from aragora.server.security.request_limits import check_json_depth
from aragora.spectate.redaction import redact_spectator_payload

# RFC 6455 close codes
WS_CLOSE_UNSUPPORTED_DATA = 1003  # Unsupported data (e.g., invalid JSON)
WS_CLOSE_MESSAGE_TOO_BIG = 1009  # Message too big

# Maximum JSON nesting depth allowed in WebSocket messages.
# Prevents JSON bomb attacks where deeply nested structures exhaust CPU/stack.
WS_MAX_JSON_DEPTH = 20

_SPECTATE_REVOKED = object()

logger = logging.getLogger(__name__)


class WebSocketHandlerMixin:
    """
    Mixin class providing WebSocket connection handling for the streaming server.

    This mixin expects the following attributes/methods from the parent class:
    - clients: set of WebSocket connections
    - _client_ids: dict mapping ws_id to client_id
    - _client_subscriptions: dict mapping ws_id to debate_id
    - _client_subscriptions_lock: threading.Lock
    - _active_loops_lock: threading.Lock
    - active_loops: dict of active loops
    - _rate_limiters: dict of rate limiters
    - _rate_limiters_lock: threading.Lock
    - _rate_limiter_last_access: dict
    - _debate_states_lock: threading.Lock
    - debate_states: dict
    - _emitter: SyncEventEmitter
    - _voice_handler: VoiceStreamHandler
    - _timeout_sender: TimeoutSender
    - _running: bool
    - config: ServerConfig
    - audience_inbox: AudienceInbox
    - emitter: SyncEventEmitter (property)
    - is_ws_authenticated(ws_id) -> bool
    - should_revalidate_ws_token(ws_id) -> bool
    - get_ws_token(ws_id) -> str | None
    - revoke_ws_auth(ws_id, reason) -> None
    - mark_ws_token_validated(ws_id) -> None
    - set_ws_auth_state(ws_id, authenticated, token, ip_address) -> None
    - remove_ws_auth_state(ws_id) -> None
    - _get_loops_data() -> list[dict]
    - update_loop_state(loop_id, cycle, phase) -> None
    """

    # Attributes provided by the host class (declared for type checking)
    if TYPE_CHECKING:
        is_ws_authenticated: Any
        should_revalidate_ws_token: Any
        get_ws_token: Any
        get_ws_auth_state: Any
        revoke_ws_auth: Any
        mark_ws_token_validated: Any
        set_ws_auth_state: Any
        remove_ws_auth_state: Any
        _active_loops_lock: Any
        active_loops: Any
        _rate_limiters_lock: Any
        _rate_limiter_last_access: Any
        _rate_limiters: Any
        audience_inbox: Any
        _emitter: Any
        clients: Any
        _client_ids: Any
        config: Any
        _get_loops_data: Any
        _client_subscriptions_lock: Any
        _client_subscriptions: Any
        _debate_states_lock: Any
        debate_states: Any
        get_debate_state: Any
        _timeout_sender: Any
        _running: Any
        update_loop_state: Any
        _voice_handler: Any

    def _validate_audience_payload(self, data: dict) -> tuple[dict | None, str | None]:
        """Validate audience message payload.

        Returns:
            Tuple of (validated_payload, error_message). If error, payload is None.
        """
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            return None, "Invalid payload format"

        # Limit payload size to 10KB (DoS protection)
        try:
            payload_str = json.dumps(payload)
            if len(payload_str) > 10240:
                return None, "Payload too large (max 10KB)"
        except (TypeError, ValueError):
            return None, "Invalid payload structure"

        return payload, None

    async def _validate_ws_auth_for_write(
        self,
        ws_id: int,
        ws: Any,
    ) -> tuple[bool, dict | None]:
        """Validate WebSocket authentication for write operations.

        Returns:
            Tuple of (is_authorized, error_response). If not authorized, error_response
            contains the JSON response to send to the client.
        """
        try:
            from aragora.server.auth import auth_config

            if not auth_config.enabled:
                return True, None

            # Check basic authentication
            if not self.is_ws_authenticated(ws_id):
                return False, {
                    "type": "error",
                    "data": {
                        "message": "Authentication required for voting/suggestions",
                        "code": 401,
                    },
                }

            # Periodic token revalidation for long-lived connections
            if self.should_revalidate_ws_token(ws_id):
                stored_token = self.get_ws_token(ws_id)
                if stored_token and not auth_config.validate_token(stored_token):
                    self.revoke_ws_auth(ws_id, "Token expired or revoked")
                    return False, {
                        "type": "auth_revoked",
                        "data": {"message": "Token has been revoked or expired", "code": 401},
                    }
                self.mark_ws_token_validated(ws_id)

            return True, None
        except ImportError:
            return True, None  # Auth module not available

    def _validate_loop_id_access(
        self,
        ws_id: int,
        loop_id: str,
    ) -> tuple[bool, dict | None]:
        """Validate loop_id exists and client has access.

        Returns:
            Tuple of (is_valid, error_response). If not valid, error_response
            contains the JSON response to send to the client.
        """
        # Validate loop_id exists and is active
        with self._active_loops_lock:
            loop_valid = loop_id and loop_id in self.active_loops

        if not loop_valid:
            return False, {
                "type": "error",
                "data": {"message": f"Invalid or inactive loop_id: {loop_id}"},
            }

        # Validate token is authorized for this specific loop_id
        try:
            from aragora.server.auth import auth_config

            if auth_config.enabled:
                stored_token = self.get_ws_token(ws_id)
                if stored_token:
                    is_valid, err_msg = auth_config.validate_token_for_loop(stored_token, loop_id)
                    if not is_valid:
                        return False, {"type": "error", "data": {"message": err_msg, "code": 403}}
        except ImportError:
            pass

        return True, None

    def _check_audience_rate_limit(
        self,
        client_id: str,
    ) -> tuple[bool, dict | None]:
        """Check rate limit for audience messages.

        Returns:
            Tuple of (is_allowed, error_response). If not allowed, error_response
            contains the JSON response to send to the client.
        """
        with self._rate_limiters_lock:
            self._rate_limiter_last_access[client_id] = time.time()
            rate_limiter = self._rate_limiters.get(client_id)

        if rate_limiter is None or not rate_limiter.consume(1):
            return False, {
                "type": "error",
                "data": {"message": "Rate limit exceeded, try again later"},
            }

        return True, None

    def _process_audience_message(
        self,
        msg_type: str,
        loop_id: str,
        payload: dict,
        client_id: str,
    ) -> None:
        """Process validated audience vote/suggestion message."""
        audience_msg = AudienceMessage(
            type="vote" if msg_type == "user_vote" else "suggestion",
            loop_id=loop_id,
            payload=payload,
            user_id=client_id,
        )
        self.audience_inbox.put(audience_msg)

        # Emit event for dashboard visibility
        event_type = (
            StreamEventType.USER_VOTE
            if msg_type == "user_vote"
            else StreamEventType.USER_SUGGESTION
        )
        self._emitter.emit(
            StreamEvent(
                type=event_type,
                data=audience_msg.payload,
                loop_id=loop_id,
            )
        )

        # Emit updated audience metrics after each vote
        if msg_type == "user_vote":
            metrics = self.audience_inbox.get_summary(loop_id=loop_id)
            self._emitter.emit(
                StreamEvent(
                    type=StreamEventType.AUDIENCE_METRICS,
                    data=metrics,
                    loop_id=loop_id,
                )
            )

    @staticmethod
    def _spectate_timestamp_to_epoch(timestamp: str | None) -> float:
        """Convert an ISO-8601 timestamp into epoch seconds for live clients."""
        if not timestamp:
            return time.time()

        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return time.time()

    @staticmethod
    def _spectate_scope_matches(event: Any, debate_id: str | None, pipeline_id: str | None) -> bool:
        """Return whether a spectate event matches the requested scope."""
        if debate_id:
            return getattr(event, "debate_id", None) == debate_id
        if pipeline_id:
            return getattr(event, "pipeline_id", None) == pipeline_id
        return False

    @staticmethod
    def _spectate_event_signature(event: Any) -> str:
        """Build a stable signature for de-duplicating backlog and live delivery."""
        data = getattr(event, "data", {}) or {}
        details = data.get("details")
        return "|".join(
            [
                str(getattr(event, "event_type", "")),
                str(getattr(event, "timestamp", "")),
                str(getattr(event, "debate_id", "")),
                str(getattr(event, "pipeline_id", "")),
                str(getattr(event, "agent_name", "")),
                str(getattr(event, "round_number", "")),
                str(details),
            ]
        )

    def _build_spectate_metadata(
        self,
        *,
        debate_id: str | None,
        pipeline_id: str | None,
    ) -> dict[str, Any]:
        """Build the initial metadata payload for spectate WebSocket clients."""
        payload: dict[str, Any] = {"type": "metadata"}
        if debate_id:
            payload["debate_id"] = debate_id
        if pipeline_id:
            payload["pipeline_id"] = pipeline_id

        if debate_id:
            state = self.get_debate_state(debate_id)
            if state:
                if state.get("task"):
                    payload["task"] = state["task"]
                if state.get("agents"):
                    payload["agents"] = state["agents"]
                if state.get("status"):
                    payload["status"] = state["status"]
                payload["current_round"] = state.get("current_round", 0)
                payload["message_count"] = len(state.get("messages", []))

        return redact_spectator_payload(payload)

    def _serialize_spectate_event(self, event: Any) -> dict[str, Any]:
        """Translate buffered spectate bridge events into the live client protocol."""
        data = redact_spectator_payload(getattr(event, "data", {}) or {})
        payload: dict[str, Any] = {
            "type": getattr(event, "event_type", "system"),
            "timestamp": self._spectate_timestamp_to_epoch(getattr(event, "timestamp", None)),
            "agent": getattr(event, "agent_name", None),
            "details": data.get("details"),
            "metric": data.get("metric"),
            "round": getattr(event, "round_number", None),
        }

        debate_id = getattr(event, "debate_id", None)
        if debate_id:
            payload["debate_id"] = debate_id

        pipeline_id = getattr(event, "pipeline_id", None)
        if pipeline_id:
            payload["pipeline_id"] = pipeline_id

        for key in ("task", "agents", "status"):
            if key in data:
                payload[key] = data[key]

        return redact_spectator_payload(payload)

    @staticmethod
    def _spectate_caller(request: Any) -> SimpleNamespace:
        """The socket's caller as ``require_org_scope`` reads it.

        Browsers cannot set headers on a WebSocket, so ``?token=`` stands in
        for the Authorization header, as on the main socket. No user store is
        attached, so an ``ara_`` API key is not resolved and its caller only
        sees public debates here.
        """
        authorization = request.headers.get("Authorization", "")
        token = request.query.get("token")
        if not authorization and token:
            authorization = f"Bearer {token}"
        return SimpleNamespace(
            headers={"Authorization": authorization} if authorization else {},
            client_address=(request.remote or "", 0),
        )

    async def _handle_spectate_websocket(self, request) -> aiohttp.web.StreamResponse:
        """Handle debate or pipeline spectate sockets used by the live UI.

        The caller sees what the spectate SSE route shows them: a named debate
        must be public or their org's (else 401/403/404 before the upgrade),
        and only events they may view are sent. A debate socket is closed with
        ``share_revoked`` once the caller may no longer view the debate.
        """
        import aiohttp
        import aiohttp.web as web

        from aragora.server.handlers.streaming.spectate_ws import (
            SpectateVisibility,
            authorize_spectate_request,
        )
        from aragora.spectate.ws_bridge import get_spectate_bridge

        origin = request.headers.get("Origin", "")
        if origin and origin not in WS_ALLOWED_ORIGINS:
            return web.Response(status=403, text="Origin not allowed")

        debate_id = request.match_info.get("debate_id") or request.query.get("debate_id")
        pipeline_id = request.query.get("pipeline_id")

        if debate_id and pipeline_id:
            return web.Response(status=400, text="Provide either debate_id or pipeline_id")
        if not debate_id and not pipeline_id:
            return web.Response(status=400, text="Missing debate_id or pipeline_id")

        visibility = await asyncio.to_thread(
            authorize_spectate_request,
            self._spectate_caller(request),
            {"debate_id": debate_id} if debate_id else None,
        )
        if not isinstance(visibility, SpectateVisibility):
            return web.Response(
                status=visibility.status_code,
                body=visibility.body,
                content_type="application/json",
            )

        bridge = get_spectate_bridge()
        if not bridge.running:
            bridge.start()

        ws = web.WebSocketResponse(
            max_msg_size=WS_MAX_MESSAGE_SIZE,
            compress=True,
        )
        await ws.prepare(request)

        loop = asyncio.get_running_loop()
        event_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=256)
        seen_signatures: set[str] = set()

        def _revoke() -> None:
            while not event_queue.empty():
                event_queue.get_nowait()
            event_queue.put_nowait(_SPECTATE_REVOKED)

        def enqueue(event: Any) -> None:
            if not self._spectate_scope_matches(event, debate_id, pipeline_id):
                return
            if not visibility.can_view_event(event):
                if debate_id and visibility.lost_access(debate_id):
                    loop.call_soon_threadsafe(_revoke)
                return

            def _push() -> None:
                if event_queue.full():
                    try:
                        event_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    event_queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.debug("spectate_ws_queue_full", exc_info=True)

            loop.call_soon_threadsafe(_push)

        async def pump_events() -> None:
            while True:
                event = await event_queue.get()
                if event is _SPECTATE_REVOKED:
                    await ws.send_json({"type": "share_revoked", "debate_id": debate_id})
                    await ws.close()
                    return
                signature = self._spectate_event_signature(event)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                await ws.send_json(self._serialize_spectate_event(event))

        bridge.subscribe(enqueue)
        sender_task = asyncio.create_task(pump_events())

        try:
            await ws.send_json(
                self._build_spectate_metadata(
                    debate_id=debate_id,
                    pipeline_id=pipeline_id,
                )
            )

            for event in bridge.get_recent_events(200):
                if not self._spectate_scope_matches(event, debate_id, pipeline_id):
                    continue
                if not visibility.can_view_event(event):
                    continue
                signature = self._spectate_event_signature(event)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                await ws.send_json(self._serialize_spectate_event(event))

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    if payload.get("type") == "ping":
                        await ws.send_json({"type": "pong", "timestamp": time.time()})
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        except (ConnectionResetError, OSError) as exc:
            logger.debug("spectate_websocket_closed: %s", exc)
        finally:
            bridge.unsubscribe(enqueue)
            sender_task.cancel()
            await asyncio.gather(sender_task, return_exceptions=True)
            if not ws.closed:
                await ws.close()

        return ws

    async def _handle_voice_websocket(self, request) -> aiohttp.web.StreamResponse:
        """Handle voice streaming WebSocket connections.

        Route: /ws/voice/{debate_id}
        Receives audio chunks, transcribes via Whisper, returns transcripts.
        """
        import aiohttp.web as web

        # Extract debate_id from URL
        debate_id = request.match_info.get("debate_id", "")
        if not debate_id:
            return web.Response(status=400, text="Missing debate_id")

        # Validate origin for security
        origin = request.headers.get("Origin", "")
        if origin and origin not in WS_ALLOWED_ORIGINS:
            return web.Response(status=403, text="Origin not allowed")

        # Create WebSocket response
        ws = web.WebSocketResponse(max_msg_size=WS_MAX_MESSAGE_SIZE)
        await ws.prepare(request)

        # Delegate to voice handler
        try:
            await self._voice_handler.handle_websocket(request, ws, debate_id)
        except (OSError, ConnectionError, RuntimeError) as e:
            # WebSocket/network errors during voice streaming
            logger.error("[voice] WebSocket error for debate %s: %s", debate_id, e)
        finally:
            if not ws.closed:
                await ws.close()

        return ws

    async def _websocket_handler(self, request) -> aiohttp.web.StreamResponse:
        """Handle WebSocket connections with security validation and optional auth."""
        import aiohttp
        import aiohttp.web as web

        from .servers import TRUSTED_PROXIES

        # Validate origin for security (match websockets handler behavior)
        origin = request.headers.get("Origin", "")
        if origin and origin not in WS_ALLOWED_ORIGINS:
            # Reject connection from unauthorized origin
            return web.Response(status=403, text="Origin not allowed")

        # Extract client IP (validate proxy headers for security)
        remote_ip = request.remote or ""
        client_ip = remote_ip  # Default to direct connection IP
        if remote_ip in TRUSTED_PROXIES:
            # Only trust X-Forwarded-For from trusted proxies
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                first_ip = forwarded.split(",")[0].strip()
                if first_ip:
                    client_ip = first_ip

        # Extract token for authentication tracking
        is_authenticated = False
        ws_token = None

        # Optional authentication (controlled by ARAGORA_API_TOKEN env var)
        try:
            from aragora.server.auth import auth_config, check_auth

            # Convert headers to dict for check_auth
            headers = dict(request.headers)

            # Extract token from Authorization header or query param for tracking
            auth_header = headers.get("Authorization", "")
            token_param = request.query.get("token")
            if not auth_header and token_param:
                auth_header = f"Bearer {token_param}"
                headers["Authorization"] = auth_header
            if auth_header.startswith("Bearer "):
                ws_token = auth_header[7:]

            if auth_config.enabled:
                authenticated, remaining = check_auth(headers, "", loop_id="", ip_address=client_ip)

                if not authenticated:
                    if remaining == 0:
                        return web.Response(status=429, text="Rate limit exceeded")
                    # Allow unauthenticated read-only connections; write ops remain gated
                    is_authenticated = False
                else:
                    is_authenticated = True
            else:
                # Auth disabled - still track token if provided for optional validation
                is_authenticated = True  # Everyone is "authenticated" when auth is disabled
        except ImportError:
            # Log warning if auth is required but module unavailable
            if os.getenv("ARAGORA_AUTH_REQUIRED"):
                logger.warning("[ws] Auth required but module unavailable - rejecting connection")
                return web.Response(status=500, text="Authentication system unavailable")
            is_authenticated = True  # Auth module not available, allow connection

        # Enable permessage-deflate compression for reduced bandwidth
        # compress=15 uses 15-bit window (32KB) for good compression ratio
        ws = web.WebSocketResponse(
            max_msg_size=WS_MAX_MESSAGE_SIZE,
            compress=True,  # Enable permessage-deflate compression
        )
        await ws.prepare(request)

        # Initialize tracking variables before any operations that could fail
        ws_id = id(ws)
        client_id = secrets.token_hex(16)
        self.clients.add(ws)
        # Enforce max size with LRU eviction
        if len(self._client_ids) >= self.config.max_client_ids:
            self._client_ids.popitem(last=False)  # Remove oldest
        self._client_ids[ws_id] = client_id

        # Track authentication state using ServerBase method
        self.set_ws_auth_state(
            ws_id=ws_id,
            authenticated=is_authenticated,
            token=ws_token,
            ip_address=client_ip,
        )

        # Initialize rate limiter for this client (thread-safe)
        with self._rate_limiters_lock:
            self._rate_limiters[client_id] = TokenBucket(
                rate_per_minute=10.0,
                burst_size=5,  # 10 messages per minute  # Allow burst of 5
            )
            self._rate_limiter_last_access[client_id] = time.time()

        logger.info(
            "[ws] Client %s... connected from %s (authenticated=%s, total_clients=%s)",
            client_id[:8],
            client_ip,
            is_authenticated,
            len(self.clients),
        )

        # Send connection info including auth status
        try:
            from aragora.server.auth import auth_config as _auth_config

            write_access = is_authenticated or not _auth_config.enabled
        except ImportError:
            write_access = True

        await ws.send_json(
            {
                "type": "connection_info",
                "data": {
                    "authenticated": is_authenticated,
                    "client_id": client_id[:8] + "...",  # Partial for privacy
                    "write_access": write_access,
                },
            }
        )

        # Send initial loop list
        loops_data = self._get_loops_data()
        await ws.send_json(
            {
                "type": "loop_list",
                "data": {"loops": loops_data, "count": len(loops_data)},
            }
        )

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    # Defense-in-depth: check message size before parsing
                    # Close with RFC 6455 code 1009 (Message Too Big)
                    msg_data = msg.data
                    if len(msg_data) > WS_MAX_MESSAGE_SIZE:
                        logger.warning(
                            "WebSocket message too large: %d bytes (max %d) from %s",
                            len(msg_data),
                            WS_MAX_MESSAGE_SIZE,
                            client_id,
                        )
                        await ws.close(
                            code=WS_CLOSE_MESSAGE_TOO_BIG,
                            message=b"Message too large",
                        )
                        break

                    try:
                        data = json.loads(msg_data)

                        # Validate JSON nesting depth to prevent JSON bomb attacks
                        depth_ok, depth_err = check_json_depth(data, WS_MAX_JSON_DEPTH)
                        if not depth_ok:
                            logger.warning(
                                "WebSocket JSON depth exceeded from %s: %s",
                                client_id,
                                depth_err,
                            )
                            await ws.close(
                                code=WS_CLOSE_UNSUPPORTED_DATA,
                                message=b"Unsupported data",
                            )
                            break

                        msg_type = data.get("type")

                        if msg_type == "get_loops":
                            loops_data = self._get_loops_data()
                            await ws.send_json(
                                {
                                    "type": "loop_list",
                                    "data": {"loops": loops_data, "count": len(loops_data)},
                                }
                            )

                        elif msg_type == "subscribe":
                            # SECURITY: Track client subscription for stream isolation
                            # This ensures clients only receive events for debates they subscribed to
                            debate_id = data.get("debate_id") or data.get("loop_id")
                            if debate_id:
                                # SECURITY: Verify RBAC permission before subscribing
                                subscribe_allowed = True
                                try:
                                    from aragora.rbac.checker import check_permission as rbac_check
                                    from aragora.rbac.models import AuthorizationContext

                                    if self.is_ws_authenticated(ws_id):
                                        auth_state = self.get_ws_auth_state(ws_id) or {}  # type: ignore[attr-defined]
                                        auth_ctx = AuthorizationContext(
                                            user_id=auth_state.get("user_id", client_id),
                                            roles=auth_state.get("roles", {"viewer"}),
                                        )
                                        decision = rbac_check(auth_ctx, "debates.read", debate_id)
                                        if not decision.allowed:
                                            subscribe_allowed = False
                                            await ws.send_json(
                                                {
                                                    "type": "error",
                                                    "data": {
                                                        "message": "Permission denied: debates:read required",
                                                        "code": 403,
                                                    },
                                                }
                                            )
                                except ImportError:
                                    pass  # RBAC module not available, allow subscription

                                # Also check tenant isolation
                                if subscribe_allowed:
                                    try:
                                        from .tenant_filter import get_tenant_filter

                                        tf = get_tenant_filter()
                                        tenant_ok, tenant_msg = tf.validate_subscription(
                                            ws_id, debate_id
                                        )
                                        if not tenant_ok:
                                            subscribe_allowed = False
                                            await ws.send_json(
                                                {
                                                    "type": "error",
                                                    "data": {
                                                        "message": tenant_msg,
                                                        "code": 403,
                                                    },
                                                }
                                            )
                                    except ImportError:
                                        pass

                                if subscribe_allowed:
                                    with self._client_subscriptions_lock:
                                        self._client_subscriptions[ws_id] = debate_id
                                    setattr(ws, "_bound_loop_id", debate_id)
                                    logger.info(
                                        "[ws] Client %s... subscribed to %s",
                                        client_id[:8],
                                        debate_id,
                                    )
                                    # Send current debate state if available
                                    with self._debate_states_lock:
                                        state = self.debate_states.get(debate_id)
                                    if state:
                                        await ws.send_json(
                                            {
                                                "type": "sync",
                                                "data": state,
                                                "debate_id": debate_id,
                                            }
                                        )
                                    else:
                                        await ws.send_json(
                                            {
                                                "type": "subscribed",
                                                "data": {"debate_id": debate_id},
                                            }
                                        )
                            else:
                                await ws.send_json(
                                    {
                                        "type": "error",
                                        "data": {"message": "subscribe requires debate_id"},
                                    }
                                )

                        elif msg_type in ("user_vote", "user_suggestion"):
                            # Validate authentication for write operations
                            is_auth, auth_error = await self._validate_ws_auth_for_write(ws_id, ws)
                            if not is_auth:
                                await ws.send_json(auth_error)
                                continue

                            # Get loop_id (use ws-bound as fallback for proprioceptive socket)
                            loop_id = data.get("loop_id") or getattr(ws, "_bound_loop_id", "")

                            # Optional per-message token validation
                            msg_token = data.get("token")
                            if msg_token:
                                try:
                                    from aragora.server.auth import auth_config

                                    if not auth_config.validate_token(msg_token, loop_id):
                                        await ws.send_json(
                                            {
                                                "type": "error",
                                                "data": {
                                                    "code": "AUTH_FAILED",
                                                    "message": "Invalid or revoked token",
                                                },
                                            }
                                        )
                                        continue
                                except ImportError:
                                    pass

                            # Validate loop_id and access
                            is_valid, loop_error = self._validate_loop_id_access(ws_id, loop_id)
                            if not is_valid:
                                await ws.send_json(loop_error)
                                continue

                            # Bind loop_id to WebSocket for future reference (proprioceptive socket)
                            setattr(ws, "_bound_loop_id", loop_id)

                            # Validate payload
                            payload, error = self._validate_audience_payload(data)
                            if error or payload is None:
                                await ws.send_json(
                                    {
                                        "type": "error",
                                        "data": {"message": error or "Invalid payload"},
                                    }
                                )
                                continue

                            # Check rate limit
                            is_allowed, rate_error = self._check_audience_rate_limit(client_id)
                            if not is_allowed:
                                await ws.send_json(rate_error)
                                continue

                            # Process the message
                            self._process_audience_message(msg_type, loop_id, payload, client_id)
                            await ws.send_json(
                                {
                                    "type": "ack",
                                    "data": {"message": "Message received", "msg_type": msg_type},
                                }
                            )

                    except json.JSONDecodeError as e:
                        logger.warning(
                            "WebSocket invalid JSON from %s: %s at pos %s",
                            client_id,
                            e.msg,
                            e.pos,
                        )
                        await ws.close(
                            code=WS_CLOSE_UNSUPPORTED_DATA,
                            message=b"Unsupported data",
                        )
                        break

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error("[ws] Error: %s", ws.exception())
                    break

                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    logger.debug("[ws] Client %s... closed connection", client_id[:8])
                    break

                elif msg.type == aiohttp.WSMsgType.BINARY:
                    logger.warning("[ws] Binary message rejected from %s...", client_id[:8])
                    await ws.send_json(
                        {
                            "type": "error",
                            "data": {
                                "code": "BINARY_NOT_SUPPORTED",
                                "message": "Binary messages not supported",
                            },
                        }
                    )

                # PING/PONG handled automatically by aiohttp, but log if we see them
                elif msg.type in (aiohttp.WSMsgType.PING, aiohttp.WSMsgType.PONG):
                    pass  # Handled by aiohttp automatically

                else:
                    logger.warning("[ws] Unhandled message type: %s", msg.type)

        finally:
            self.clients.discard(ws)
            self._client_ids.pop(ws_id, None)
            # Clean up subscription tracking (SECURITY: prevent stale entries)
            with self._client_subscriptions_lock:
                self._client_subscriptions.pop(ws_id, None)
            # Clean up rate limiter for this client (thread-safe)
            with self._rate_limiters_lock:
                self._rate_limiters.pop(client_id, None)
                self._rate_limiter_last_access.pop(client_id, None)
            # Clean up auth state
            self.remove_ws_auth_state(ws_id)
            logger.info(
                "[ws] Client %s... disconnected from %s (remaining_clients=%s)",
                client_id[:8],
                client_ip,
                len(self.clients),
            )

        return ws

    async def _drain_loop(self) -> None:
        """Drain events from the sync emitter and broadcast to WebSocket clients."""

        while self._running:
            try:
                event = self._emitter._queue.get(timeout=0.1)

                # Update loop state for cycle/phase events
                if event.type == StreamEventType.CYCLE_START:
                    self.update_loop_state(event.loop_id, cycle=event.data.get("cycle"))
                elif event.type == StreamEventType.PHASE_START:
                    self.update_loop_state(event.loop_id, phase=event.data.get("phase"))

                # Serialize event
                event_dict = {
                    "type": event.type.value,
                    "data": event.data,
                    "timestamp": event.timestamp,
                    "round": event.round,
                    "agent": event.agent,
                    "loop_id": event.loop_id,
                }
                message = json.dumps(event_dict)

                # SECURITY: Broadcast only to clients subscribed to this debate
                # This prevents data leakage between concurrent debates
                event_loop_id = event.loop_id

                # Take snapshot of subscriptions to avoid holding lock during I/O
                with self._client_subscriptions_lock:
                    subscriptions_snapshot = dict(self._client_subscriptions)

                # Filter clients to send to based on subscription
                clients_to_send = []
                for client in list(self.clients):
                    client_ws_id = id(client)
                    subscribed_id = subscriptions_snapshot.get(client_ws_id)

                    # Send if:
                    # 1. Event has no loop_id (system-wide events like heartbeat)
                    # 2. Client is subscribed to this specific debate
                    # SECURITY: Unsubscribed clients (subscribed_id is None) do NOT
                    # receive debate-scoped events to prevent data leakage.
                    should_send = (
                        not event_loop_id  # System events go to all
                        or subscribed_id == event_loop_id  # Subscribed to this debate
                    )

                    if should_send:
                        clients_to_send.append(client)

                # Use timeout sender to broadcast with per-client timeouts
                # This prevents slow clients from blocking the entire drain loop
                sent_count, dead_clients = await self._timeout_sender.send_many(
                    clients_to_send, message
                )

                if dead_clients:
                    logger.info("Removed %d dead/slow WebSocket client(s)", len(dead_clients))
                    for client in dead_clients:
                        self.clients.discard(client)
                        # Cleanup subscription and sender tracking
                        with self._client_subscriptions_lock:
                            self._client_subscriptions.pop(id(client), None)
                        self._timeout_sender.remove_client(client)

            except queue.Empty:
                await asyncio.sleep(0.01)
            except (OSError, RuntimeError, ValueError) as e:
                # Network/serialization errors during event processing
                logger.error("[ws] Drain loop error: %s", e)
                await asyncio.sleep(0.1)
