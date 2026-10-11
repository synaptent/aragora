"""
Local Gateway Server - Device-local routing and auth daemon.

Pattern: Local-first Gateway
Inspired by: OpenClaw (formerly Moltbot)
Aragora adaptation: Unified inbox routing with Agent Fabric integration

A lightweight service that runs on the user's device, routing incoming
messages from any channel to the right agent, enforcing local auth,
and proxying to Aragora cloud services when needed.

Endpoints:
- GET  /health              - Health check
- GET  /stats               - Gateway statistics
- GET  /inbox               - Get inbox messages
- POST /route               - Route a message to an agent
- POST /device              - Register a device
- GET  /device/{device_id}  - Get device info
- WS   /ws                  - Real-time inbox updates

Production Hardening:
- Request timeouts (configurable per-request type)
- Graceful shutdown with drain period
- Rate limiting per client IP
- Connection limits
- Structured logging with correlation IDs
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web, WSMsgType

from aragora.gateway.inbox import InboxAggregator, InboxMessage
from aragora.gateway.device_registry import DeviceNode, DeviceRegistry
from aragora.gateway.router import AgentRouter
from aragora.gateway.persistence import get_gateway_store_from_env
from aragora.stores import get_canonical_gateway_stores

logger = logging.getLogger(__name__)


# =============================================================================
# Rate Limiting
# =============================================================================


class GatewayRateLimiter:
    """Simple in-memory rate limiter for the gateway."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        burst_allowance: int = 10,
    ):
        self._rpm = requests_per_minute
        self._burst = burst_allowance
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def is_allowed(self, client_id: str) -> bool:
        """Check if a request from client_id is allowed."""
        now = time.time()
        window_start = now - 60.0

        async with self._lock:
            # Clean old entries
            self._requests[client_id] = [t for t in self._requests[client_id] if t > window_start]

            # Check limit (allow burst over base rate)
            if len(self._requests[client_id]) >= self._rpm + self._burst:
                return False

            self._requests[client_id].append(now)
            return True

    def get_remaining(self, client_id: str) -> int:
        """Get remaining requests for client."""
        now = time.time()
        window_start = now - 60.0
        recent = [t for t in self._requests.get(client_id, []) if t > window_start]
        return max(0, self._rpm + self._burst - len(recent))


@dataclass
class GatewayConfig:
    """Configuration for the Local Gateway.

    Production settings are loaded from environment variables when not
    explicitly configured:
    - ARAGORA_GATEWAY_HOST: Bind host (default: 127.0.0.1)
    - ARAGORA_GATEWAY_PORT: Bind port (default: 8090)
    - ARAGORA_GATEWAY_API_KEY: API key for authentication
    - ARAGORA_GATEWAY_ENABLE_AUTH: Enable auth (default: true)
    - ARAGORA_GATEWAY_REQUEST_TIMEOUT: Request timeout in seconds (default: 30)
    - ARAGORA_GATEWAY_SHUTDOWN_TIMEOUT: Graceful shutdown timeout (default: 30)
    - ARAGORA_GATEWAY_RATE_LIMIT_RPM: Requests per minute (default: 60)
    - ARAGORA_GATEWAY_MAX_CONNECTIONS: Max concurrent connections (default: 100)
    """

    host: str = "127.0.0.1"
    port: int = 8090
    api_key: str = ""
    enable_auth: bool = True
    cloud_proxy_url: str | None = None
    max_inbox_size: int = 10000
    allowed_channels: list[str] = field(default_factory=list)

    # Production hardening settings
    request_timeout_seconds: float = 30.0
    shutdown_timeout_seconds: float = 30.0
    rate_limit_rpm: int = 60
    rate_limit_burst: int = 10
    max_connections: int = 100
    enable_cors: bool = False
    cors_origins: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> GatewayConfig:
        """Create config from environment variables."""

        def get_bool(key: str, default: bool) -> bool:
            val = os.environ.get(key, "").lower()
            if val in ("1", "true", "yes"):
                return True
            if val in ("0", "false", "no"):
                return False
            return default

        def get_int(key: str, default: int) -> int:
            try:
                return int(os.environ.get(key, default))
            except ValueError:
                return default

        def get_float(key: str, default: float) -> float:
            try:
                return float(os.environ.get(key, default))
            except ValueError:
                return default

        return cls(
            host=os.environ.get("ARAGORA_GATEWAY_HOST", "127.0.0.1"),
            port=get_int("ARAGORA_GATEWAY_PORT", 8090),
            api_key=os.environ.get("ARAGORA_GATEWAY_API_KEY", ""),
            enable_auth=get_bool("ARAGORA_GATEWAY_ENABLE_AUTH", True),
            cloud_proxy_url=os.environ.get("ARAGORA_GATEWAY_CLOUD_PROXY_URL"),
            max_inbox_size=get_int("ARAGORA_GATEWAY_MAX_INBOX_SIZE", 10000),
            request_timeout_seconds=get_float("ARAGORA_GATEWAY_REQUEST_TIMEOUT", 30.0),
            shutdown_timeout_seconds=get_float("ARAGORA_GATEWAY_SHUTDOWN_TIMEOUT", 30.0),
            rate_limit_rpm=get_int("ARAGORA_GATEWAY_RATE_LIMIT_RPM", 60),
            rate_limit_burst=get_int("ARAGORA_GATEWAY_RATE_LIMIT_BURST", 10),
            max_connections=get_int("ARAGORA_GATEWAY_MAX_CONNECTIONS", 100),
            enable_cors=get_bool("ARAGORA_GATEWAY_ENABLE_CORS", False),
        )


@dataclass
class AgentResponse:
    """Response from an agent for a routed message."""

    message_id: str
    agent_id: str
    channel: str
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str | None = None


class LocalGateway:
    """
    Device-local HTTP/WebSocket gateway for message routing.

    Provides:
    - Message routing from any channel to the right agent
    - Local auth enforcement (API key or device certificate)
    - Unified inbox access
    - Device registration and capability management
    - Cloud proxy for remote services

    Usage:
        gw = LocalGateway(config=GatewayConfig(port=8090))
        await gw.start()
        response = await gw.route_message("slack", message)
        inbox = await gw.get_inbox()
        await gw.stop()
    """

    def __init__(self, config: GatewayConfig | None = None) -> None:
        self._config = config or GatewayConfig()
        self._store = None
        self._session_store = None
        self._canonical_stores = None
        store = self._get_gateway_store()
        self._inbox = InboxAggregator(max_size=self._config.max_inbox_size, store=store)
        self._devices = DeviceRegistry(store=store)
        self._router = AgentRouter(store=store)
        self._running = False
        self._shutting_down = False
        self._started_at: float | None = None
        self._messages_routed = 0
        self._messages_failed = 0
        self._active_connections = 0
        self._rate_limiter = GatewayRateLimiter(
            requests_per_minute=self._config.rate_limit_rpm,
            burst_allowance=self._config.rate_limit_burst,
        )

    def _get_gateway_store(self):
        if self._store is not None:
            return self._store
        if self._canonical_stores is None:
            self._canonical_stores = get_canonical_gateway_stores(allow_disabled=True)
        self._store = self._canonical_stores.gateway_store()
        return self._store

    def _get_session_store(self):
        if self._session_store is not None:
            return self._session_store
        self._session_store = get_gateway_store_from_env(
            backend_env="ARAGORA_GATEWAY_SESSION_STORE",
            fallback_backend_env="ARAGORA_GATEWAY_STORE",
            path_env="ARAGORA_GATEWAY_SESSION_PATH",
            redis_env="ARAGORA_GATEWAY_SESSION_REDIS_URL",
            default_backend="memory",
            allow_disabled=True,
        )
        return self._session_store

    @property
    def is_running(self) -> bool:
        """Check if the gateway is running."""
        return self._running

    async def start(
        self,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        """
        Start the gateway server.

        Args:
            host: Override host (defaults to config).
            port: Override port (defaults to config).
        """
        if self._running:
            logger.warning("Gateway already running")
            return

        actual_host = host or self._config.host
        actual_port = port or self._config.port

        self._running = True
        self._started_at = time.time()
        logger.info("Local gateway started on %s:%s", actual_host, actual_port)
        await self._hydrate_state()

    async def stop(self) -> None:
        """Stop the gateway server."""
        if not self._running:
            return
        store = self._store
        session_store = self._session_store
        if store:
            await store.close()
        if session_store and session_store is not store:
            await session_store.close()
        self._store = None
        self._session_store = None
        self._running = False
        logger.info("Local gateway stopped")

    async def _hydrate_state(self) -> None:
        if self._store is None:
            return
        await self._inbox.hydrate()
        await self._devices.hydrate()
        await self._router.hydrate()

    async def route_message(
        self,
        channel: str,
        message: InboxMessage,
    ) -> AgentResponse:
        """
        Route an incoming message to the appropriate agent.

        Args:
            channel: Source channel (e.g., "slack", "telegram").
            message: The incoming message.

        Returns:
            AgentResponse from the handling agent.
        """
        if not self._running:
            return AgentResponse(
                message_id=message.message_id,
                agent_id="",
                channel=channel,
                content="",
                success=False,
                error="Gateway not running",
            )

        # Auth check
        if self._config.enable_auth and self._config.api_key:
            if message.metadata.get("api_key") != self._config.api_key:
                self._messages_failed += 1
                return AgentResponse(
                    message_id=message.message_id,
                    agent_id="",
                    channel=channel,
                    content="",
                    success=False,
                    error="Authentication failed",
                )

        # Add to inbox
        await self._inbox.add_message(message)

        # Route to agent
        agent_id = await self._router.route(channel, message)

        self._messages_routed += 1

        return AgentResponse(
            message_id=message.message_id,
            agent_id=agent_id or "default",
            channel=channel,
            content=f"Routed to agent {agent_id or 'default'}",
            success=True,
        )

    async def register_device(self, device: DeviceNode) -> str:
        """Register a device with the gateway."""
        return await self._devices.register(device)

    async def get_inbox(
        self,
        channel: str | None = None,
        limit: int = 50,
    ) -> list[InboxMessage]:
        """Get messages from the unified inbox."""
        return await self._inbox.get_messages(channel=channel, limit=limit)

    async def get_stats(self) -> dict[str, Any]:
        """Get gateway statistics."""
        return {
            "running": self._running,
            "started_at": self._started_at,
            "messages_routed": self._messages_routed,
            "messages_failed": self._messages_failed,
            "inbox_size": await self._inbox.get_size(),
            "devices_registered": await self._devices.count(),
            "routing_rules": await self._router.count_rules(),
        }

    # =========================================================================
    # HTTP Server Infrastructure
    # =========================================================================

    def _create_app(self) -> web.Application:
        """Create the aiohttp web application with routes."""
        middlewares = [
            self._shutdown_middleware,
            self._connection_limit_middleware,
            self._rate_limit_middleware,
            self._timeout_middleware,
            self._auth_middleware,
        ]
        app = web.Application(middlewares=middlewares)
        app["gateway"] = self

        # Health and stats (always available)
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/ready", self._handle_ready)
        app.router.add_get("/stats", self._handle_stats)

        # Inbox operations
        app.router.add_get("/inbox", self._handle_get_inbox)

        # Message routing
        app.router.add_post("/route", self._handle_route)

        # Device management
        app.router.add_post("/device", self._handle_register_device)
        app.router.add_get("/device/{device_id}", self._handle_get_device)

        # WebSocket for real-time updates
        app.router.add_get("/ws", self._handle_websocket)

        return app

    @web.middleware
    async def _shutdown_middleware(
        self,
        request: web.Request,
        handler: Any,
    ) -> web.Response:
        """Reject new requests when shutting down (except health checks)."""
        if self._shutting_down and request.path not in ("/health", "/ready"):
            return web.json_response(
                {"error": "Service shutting down", "code": "SHUTTING_DOWN"},
                status=503,
                headers={"Retry-After": "5"},
            )
        return await handler(request)

    @web.middleware
    async def _connection_limit_middleware(
        self,
        request: web.Request,
        handler: Any,
    ) -> web.Response:
        """Enforce maximum concurrent connections."""
        if self._active_connections >= self._config.max_connections:
            return web.json_response(
                {"error": "Too many connections", "code": "CONNECTION_LIMIT"},
                status=503,
                headers={"Retry-After": "1"},
            )

        self._active_connections += 1
        try:
            return await handler(request)
        finally:
            self._active_connections -= 1

    @web.middleware
    async def _rate_limit_middleware(
        self,
        request: web.Request,
        handler: Any,
    ) -> web.Response:
        """Enforce rate limiting per client IP."""
        # Skip rate limiting for health endpoints
        if request.path in ("/health", "/ready"):
            return await handler(request)

        client_ip = self._get_client_ip(request)
        if not await self._rate_limiter.is_allowed(client_ip):
            remaining = self._rate_limiter.get_remaining(client_ip)
            return web.json_response(
                {"error": "Rate limit exceeded", "code": "RATE_LIMITED"},
                status=429,
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Remaining": str(remaining),
                },
            )
        return await handler(request)

    @web.middleware
    async def _timeout_middleware(
        self,
        request: web.Request,
        handler: Any,
    ) -> web.Response:
        """Apply request timeout."""
        # Skip timeout for WebSocket upgrades and long-polling endpoints
        if request.path == "/ws":
            return await handler(request)

        try:
            return await asyncio.wait_for(
                handler(request),
                timeout=self._config.request_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("Request timeout: %s %s", request.method, request.path)
            return web.json_response(
                {"error": "Request timeout", "code": "TIMEOUT"},
                status=504,
            )

    def _get_client_ip(self, request: web.Request) -> str:
        """Extract client IP from request, handling proxies."""
        # Check X-Forwarded-For header first
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            # Take the first IP (original client)
            return forwarded.split(",")[0].strip()

        # Check X-Real-IP header
        real_ip = request.headers.get("X-Real-IP", "")
        if real_ip:
            return real_ip.strip()

        # Fall back to peer address
        peername = request.transport.get_extra_info("peername") if request.transport else None
        if peername:
            return peername[0]

        return "unknown"

    @web.middleware
    async def _auth_middleware(
        self,
        request: web.Request,
        handler: Any,
    ) -> web.Response:
        """Middleware to enforce API key authentication."""
        # Skip auth for health endpoint
        if request.path == "/health":
            return await handler(request)

        if self._config.enable_auth and self._config.api_key:
            auth_header = request.headers.get("Authorization", "")
            api_key = request.headers.get("X-API-Key", "")

            # Check Bearer token or X-API-Key header
            if auth_header.startswith("Bearer "):
                provided_key = auth_header[7:]
            else:
                provided_key = api_key

            if provided_key != self._config.api_key:
                return web.json_response(
                    {"error": "Authentication failed", "code": "AUTH_FAILED"},
                    status=401,
                )

        return await handler(request)

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint (liveness probe)."""
        # Liveness: Is the process alive and can respond?
        status = "healthy" if self._running and not self._shutting_down else "unhealthy"
        status_code = 200 if status == "healthy" else 503

        return web.json_response(
            {
                "status": status,
                "service": "aragora-gateway",
                "uptime_seconds": time.time() - self._started_at if self._started_at else 0,
                "shutting_down": self._shutting_down,
            },
            status=status_code,
        )

    async def _handle_ready(self, request: web.Request) -> web.Response:
        """Readiness check endpoint (readiness probe)."""
        # Readiness: Is the service ready to accept traffic?
        if self._shutting_down:
            return web.json_response(
                {"status": "not_ready", "reason": "shutting_down"},
                status=503,
            )

        if not self._running:
            return web.json_response(
                {"status": "not_ready", "reason": "not_started"},
                status=503,
            )

        return web.json_response(
            {
                "status": "ready",
                "active_connections": self._active_connections,
                "messages_routed": self._messages_routed,
            }
        )

    async def _handle_stats(self, request: web.Request) -> web.Response:
        """Get gateway statistics."""
        stats = await self.get_stats()
        return web.json_response(stats)

    async def _handle_get_inbox(self, request: web.Request) -> web.Response:
        """Get inbox messages."""
        channel = request.query.get("channel")
        limit = int(request.query.get("limit", "50"))
        unread_only = request.query.get("unread_only", "false").lower() == "true"

        messages = await self._inbox.get_messages(
            channel=channel,
            limit=limit,
            is_read=False if unread_only else None,
        )

        return web.json_response(
            {
                "messages": [
                    {
                        "message_id": m.message_id,
                        "channel": m.channel,
                        "sender": m.sender,
                        "content": m.content,
                        "timestamp": m.timestamp,
                        "is_read": m.is_read,
                        "is_replied": m.is_replied,
                        "priority": m.priority.value
                        if hasattr(m.priority, "value")
                        else m.priority,
                        "thread_id": m.thread_id,
                    }
                    for m in messages
                ],
                "total": len(messages),
            }
        )

    async def _handle_route(self, request: web.Request) -> web.Response:
        """Route a message to an agent."""
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"error": "Invalid JSON", "code": "INVALID_JSON"},
                status=400,
            )

        # Validate required fields
        required = ["channel", "sender", "content"]
        missing = [f for f in required if f not in data]
        if missing:
            return web.json_response(
                {"error": f"Missing fields: {missing}", "code": "MISSING_FIELDS"},
                status=400,
            )

        # Create inbox message
        message = InboxMessage(
            message_id=data.get("message_id", f"msg-{uuid.uuid4().hex[:12]}"),
            channel=data["channel"],
            sender=data["sender"],
            content=data["content"],
            thread_id=data.get("thread_id"),
            metadata=data.get("metadata", {}),
        )

        # Route the message
        response = await self.route_message(data["channel"], message)

        # Notify WebSocket subscribers
        await self._notify_subscribers(message)

        return web.json_response(
            {
                "message_id": response.message_id,
                "agent_id": response.agent_id,
                "channel": response.channel,
                "success": response.success,
                "error": response.error,
            }
        )

    async def _handle_register_device(self, request: web.Request) -> web.Response:
        """Register a new device."""
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"error": "Invalid JSON", "code": "INVALID_JSON"},
                status=400,
            )

        if "name" not in data:
            return web.json_response(
                {"error": "Missing 'name' field", "code": "MISSING_NAME"},
                status=400,
            )

        device = DeviceNode(
            device_id=data.get("device_id"),
            name=data["name"],
            device_type=data.get("device_type", "unknown"),
            capabilities=data.get("capabilities", []),
        )

        device_id = await self.register_device(device)

        return web.json_response(
            {
                "device_id": device_id,
                "status": "registered",
            },
            status=201,
        )

    async def _handle_get_device(self, request: web.Request) -> web.Response:
        """Get device information."""
        device_id = request.match_info["device_id"]
        device = await self._devices.get(device_id)

        if not device:
            return web.json_response(
                {"error": "Device not found", "code": "NOT_FOUND"},
                status=404,
            )

        return web.json_response(
            {
                "device_id": device.device_id,
                "name": device.name,
                "device_type": device.device_type,
                "status": device.status.value
                if hasattr(device.status, "value")
                else str(device.status),
                "capabilities": device.capabilities,
                "last_seen": device.last_seen,
            }
        )

    # =========================================================================
    # WebSocket Support
    # =========================================================================

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """WebSocket endpoint for real-time inbox updates."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        from aragora.gateway.protocol import GatewayProtocolAdapter, GatewayWebSocketProtocol

        store = self._get_session_store()
        protocol = GatewayWebSocketProtocol(GatewayProtocolAdapter(self, store=store))

        # Send protocol challenge to align with OpenClaw connection flow.
        try:
            await ws.send_json(protocol.create_challenge_event())
        except (OSError, ConnectionError, RuntimeError) as e:
            logger.debug("Failed to send WebSocket challenge: %s", e)

        # Add to subscribers
        if not hasattr(self, "_ws_subscribers"):
            self._ws_subscribers: set[web.WebSocketResponse] = set()
        self._ws_subscribers.add(ws)

        logger.debug("WebSocket client connected")

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        await ws.send_json(
                            {
                                "type": "error",
                                "error": {"code": "invalid_json", "message": "invalid JSON"},
                            }
                        )
                        continue

                    response = await protocol.handle_message(data)
                    if response is not None:
                        await ws.send_json(response)
                    close_request = protocol.consume_close_request()
                    if close_request:
                        await ws.close(
                            code=close_request.code,
                            message=close_request.reason.encode(),
                        )
                        break
                elif msg.type == WSMsgType.ERROR:
                    logger.warning("WebSocket error: %s", ws.exception())
        finally:
            self._ws_subscribers.discard(ws)
            logger.debug("WebSocket client disconnected")

        return ws

    async def _notify_subscribers(self, message: InboxMessage) -> None:
        """Notify WebSocket subscribers of new message."""
        if not hasattr(self, "_ws_subscribers"):
            return

        event = {
            "type": "new_message",
            "message": {
                "message_id": message.message_id,
                "channel": message.channel,
                "sender": message.sender,
                "content": message.content[:100],  # Truncate for notification
                "timestamp": message.timestamp,
            },
        }

        # Send to all subscribers (fire and forget)
        for ws in list(self._ws_subscribers):
            if not ws.closed:
                try:
                    await ws.send_json(event)
                except (OSError, ConnectionError, RuntimeError) as e:
                    logger.debug(
                        "Failed to send to WebSocket subscriber: %s: %s", type(e).__name__, e
                    )
                    self._ws_subscribers.discard(ws)

    # =========================================================================
    # Server Lifecycle with HTTP
    # =========================================================================

    async def start_http(
        self,
        host: str | None = None,
        port: int | None = None,
        setup_signals: bool = True,
    ) -> web.AppRunner:
        """
        Start the gateway as an HTTP server.

        Args:
            host: Override host (defaults to config).
            port: Override port (defaults to config).
            setup_signals: Whether to register signal handlers for graceful shutdown.

        Returns:
            AppRunner for managing the server lifecycle.
        """
        actual_host = host or self._config.host
        actual_port = port or self._config.port

        app = self._create_app()
        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, actual_host, actual_port)
        await site.start()

        self._running = True
        self._shutting_down = False
        self._started_at = time.time()
        self._runner = runner

        # Setup signal handlers for graceful shutdown
        if setup_signals:
            self._setup_signal_handlers()

        await self._hydrate_state()

        logger.info(
            "Local gateway HTTP server started on %s:%s (timeout=%ss, rate_limit=%s/min)",
            actual_host,
            actual_port,
            self._config.request_timeout_seconds,
            self._config.rate_limit_rpm,
        )
        return runner

    def _setup_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        def handle_signal(sig: signal.Signals) -> None:
            logger.info("Received %s, initiating graceful shutdown...", sig.name)
            asyncio.create_task(self.graceful_shutdown())

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))  # type: ignore[misc]  # Lambda default captures loop variable
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

    async def graceful_shutdown(self) -> dict[str, Any]:
        """
        Perform graceful shutdown of the gateway.

        1. Stop accepting new requests (set shutting_down flag)
        2. Wait for in-flight requests to complete (with timeout)
        3. Close WebSocket connections
        4. Flush pending data
        5. Stop the HTTP server

        Returns:
            Dict with shutdown statistics.
        """
        if self._shutting_down:
            logger.warning("Graceful shutdown already in progress")
            return {"status": "already_shutting_down"}

        start_time = time.time()
        self._shutting_down = True
        logger.info("Starting graceful shutdown...")

        # Phase 1: Drain active connections
        drain_timeout = min(self._config.shutdown_timeout_seconds / 2, 15.0)
        drain_start = time.time()
        while self._active_connections > 0 and (time.time() - drain_start) < drain_timeout:
            logger.debug("Draining %s active connection(s)...", self._active_connections)
            await asyncio.sleep(0.5)

        if self._active_connections > 0:
            logger.warning(
                "%s connection(s) still active after drain timeout", self._active_connections
            )

        # Phase 2: Close WebSocket subscribers
        if hasattr(self, "_ws_subscribers"):
            ws_count = len(self._ws_subscribers)
            for ws in list(self._ws_subscribers):
                if not ws.closed:
                    try:
                        await ws.close(code=1001, message=b"Server shutting down")
                    except (OSError, ConnectionError, RuntimeError) as exc:
                        logger.debug("Cleanup failed during shutdown: %s", exc)
            logger.info("Closed %s WebSocket connection(s)", ws_count)

        # Phase 3: Flush stores
        try:
            store = self._store
            session_store = self._session_store
            if store:
                await store.close()
            if session_store and session_store is not store:
                await session_store.close()
        except (OSError, ConnectionError, RuntimeError) as e:
            logger.warning("Error closing stores: %s", e)

        # Phase 4: Stop HTTP server
        await self.stop_http()

        elapsed = time.time() - start_time
        logger.info("Graceful shutdown completed in %.1fs", elapsed)

        return {
            "status": "shutdown_complete",
            "elapsed_seconds": elapsed,
            "connections_drained": self._active_connections == 0,
        }

    async def stop_http(self) -> None:
        """Stop the HTTP server."""
        if hasattr(self, "_runner") and self._runner:
            await self._runner.cleanup()
            self._runner = None

        self._store = None
        self._session_store = None
        self._running = False
        logger.info("Local gateway HTTP server stopped")
