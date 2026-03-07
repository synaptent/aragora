"""
Real-time debate streaming via WebSocket.

The SyncEventEmitter bridges synchronous Arena code with async WebSocket broadcasts.
Events are queued synchronously and consumed by an async drain loop.

This module also supports unified HTTP+WebSocket serving on a single port via aiohttp.

Note: Core components are now in submodules for better organization:
- aragora.server.stream.events - StreamEventType, StreamEvent, AudienceMessage
- aragora.server.stream.emitter - SyncEventEmitter, TokenBucket, AudienceInbox
- aragora.server.stream.state_manager - DebateStateManager, BoundedDebateDict
- aragora.server.stream.arena_hooks - create_arena_hooks, wrap_agent_for_streaming
- aragora.server.stream.servers_ws_handler - WebSocketHandlerMixin (WS connection handling)
- aragora.server.stream.servers_route_registration - RouteRegistrationMixin (route setup, start/stop)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import aiohttp.web

# Configure module logger
logger = logging.getLogger(__name__)

# Import from sibling modules (core streaming components)
from .arena_hooks import wrap_agent_for_streaming
from .client_sender import TimeoutSender
from .events import (
    StreamEvent,
    StreamEventType,
)
from .server_base import ServerBase
from .voice_stream import VoiceStreamHandler
from .state_manager import (
    LoopInstance,
    cleanup_stale_debates,
    get_active_debates,
    get_active_debates_lock,
    get_debate_executor,
    get_debate_executor_lock,
    increment_cleanup_counter,
    set_debate_executor,
)
from .stream_handlers import StreamAPIHandlersMixin

# Import debate execution logic (extracted module)
from .debate_executor import (
    DEBATE_AVAILABLE,
    execute_debate_thread,
    fetch_trending_topic_async,
    parse_debate_request,
)

# Import mixin classes (extracted from this module)
from .servers_ws_handler import WebSocketHandlerMixin
from .servers_route_registration import RouteRegistrationMixin

# Import centralized config
from aragora.config import (
    DB_INSIGHTS_PATH,
    DB_PERSONAS_PATH,
    MAX_CONCURRENT_DEBATES,
)

# Backward compatibility aliases
_active_debates = get_active_debates()
_active_debates_lock = get_active_debates_lock()
_debate_executor_lock = get_debate_executor_lock()

# TTL for completed debates (24 hours)
_DEBATE_TTL_SECONDS = 86400


def _cleanup_stale_debates_stream() -> None:
    """Remove completed/errored debates older than TTL."""
    cleanup_stale_debates()


# Backward compatibility alias - use wrap_agent_for_streaming from arena_hooks
_wrap_agent_for_streaming = wrap_agent_for_streaming

# Import auth for WebSocket authentication
from aragora.server.auth import auth_config
from aragora.server.cors_config import WS_ALLOWED_ORIGINS

# Trusted proxies for X-Forwarded-For header validation
# Only trust X-Forwarded-For if request comes from these IPs
TRUSTED_PROXIES = frozenset(
    p.strip() for p in os.getenv("ARAGORA_TRUSTED_PROXIES", "127.0.0.1,::1,localhost").split(",")
)

# =============================================================================
# WebSocket Security Configuration
# =============================================================================

# Connection rate limiting per IP (bounds: 1-1000)
_raw_conn_rate = int(os.getenv("ARAGORA_WS_CONN_RATE", "30"))
if _raw_conn_rate < 1 or _raw_conn_rate > 1000:
    logger.warning("ARAGORA_WS_CONN_RATE=%d out of bounds [1, 1000], clamping", _raw_conn_rate)
WS_CONNECTIONS_PER_IP_PER_MINUTE = max(1, min(_raw_conn_rate, 1000))

# Token revalidation interval for long-lived connections (5 minutes)
WS_TOKEN_REVALIDATION_INTERVAL = 300.0

# Maximum connections per IP (concurrent, bounds: 1-100)
_raw_max_per_ip = int(os.getenv("ARAGORA_WS_MAX_PER_IP", "10"))
if _raw_max_per_ip < 1 or _raw_max_per_ip > 100:
    logger.warning("ARAGORA_WS_MAX_PER_IP=%d out of bounds [1, 100], clamping", _raw_max_per_ip)
WS_MAX_CONNECTIONS_PER_IP = max(1, min(_raw_max_per_ip, 100))


# =============================================================================
# Unified HTTP + WebSocket Server (aiohttp-based)
#
# Method resolution order:
# 1. AiohttpUnifiedServer (this class) - init, stores, loop/cartographer mgmt, debate lifecycle
# 2. WebSocketHandlerMixin - WS connection handler, validation helpers, drain loop
# 3. RouteRegistrationMixin - route registration, start(), stop()
# 4. ServerBase - base rate limiting, state caching
# 5. StreamAPIHandlersMixin - HTTP API endpoint handlers
# =============================================================================


# Mixin method signatures intentionally differ from ServerBase
class AiohttpUnifiedServer(  # type: ignore[override]
    ServerBase,
    StreamAPIHandlersMixin,
    WebSocketHandlerMixin,
    RouteRegistrationMixin,
):
    """
    Unified server using aiohttp to handle both HTTP API and WebSocket on a single port.

    This is the recommended server for production as it avoids CORS issues with
    separate ports for HTTP and WebSocket.

    Inherits common functionality from:
    - ServerBase: rate limiting, state caching
    - StreamAPIHandlersMixin: HTTP API endpoint handlers
    - WebSocketHandlerMixin: WebSocket connection handler, validation, drain loop
    - RouteRegistrationMixin: route registration, start(), stop()

    Usage:
        from aragora.persistence.db_config import get_nomic_dir
        server = AiohttpUnifiedServer(port=8080, nomic_dir=get_nomic_dir())
        await server.start()
    """

    def __init__(
        self,
        port: int = 8080,
        host: str = os.environ.get("ARAGORA_BIND_HOST", "127.0.0.1"),
        nomic_dir: Path | None = None,
    ):
        # Initialize base class with common functionality
        super().__init__()

        self.port = port
        self.host = host
        self.nomic_dir = nomic_dir

        # ArgumentCartographer registry - Lock hierarchy level 4 (acquire last)
        self.cartographers: dict[str, Any] = {}
        self._cartographers_lock = threading.Lock()

        # Optional stores (initialized from nomic_dir)
        self.elo_system = None
        self.insight_store = None
        self.flip_detector = None
        self.persona_manager = None
        self.debate_embeddings = None

        # Initialize stores from nomic_dir
        if nomic_dir:
            self._init_stores(nomic_dir)

        # Track which debate each client is subscribed to (for stream isolation)
        # Key: ws_id (int), Value: debate_id (str)
        # SECURITY: Prevents data leakage between concurrent debates
        self._client_subscriptions: dict[int, str] = {}
        self._client_subscriptions_lock = threading.Lock()

        # Voice streaming handler for speech-to-text
        self._voice_handler = VoiceStreamHandler(self)

        # Stop event for graceful shutdown
        self._stop_event: asyncio.Event | None = None

        # Timeout-safe sender for WebSocket broadcasts (prevents slow clients from blocking)
        self._timeout_sender = TimeoutSender(
            timeout=2.0,  # 2 second timeout per client
            max_failures=3,  # Quarantine after 3 consecutive failures
            quarantine_duration=10.0,  # Quarantine for 10 seconds
        )

        # Wire TTS integration to voice handler
        self._wire_tts_integration()

    def _wire_tts_integration(self) -> None:
        """Wire the voice handler to the TTS integration for live voice responses.

        This enables agent messages to be automatically synthesized to speech
        and sent to connected voice clients.
        """
        try:
            from aragora.server.stream.tts_integration import (
                get_tts_integration,
                set_tts_integration,
                TTSIntegration,
            )

            # Get existing integration or create a new one
            integration = get_tts_integration()
            if integration is None:
                integration = TTSIntegration(self._voice_handler)
                set_tts_integration(integration)
                logger.info("[AiohttpUnifiedServer] Created new TTS integration")
            else:
                integration.set_voice_handler(self._voice_handler)
                logger.info("[AiohttpUnifiedServer] Wired voice handler to TTS integration")

        except ImportError as e:
            logger.debug("[AiohttpUnifiedServer] TTS integration not available: %s", e)
        except (AttributeError, TypeError, ValueError) as e:
            logger.warning("[AiohttpUnifiedServer] Failed to wire TTS integration: %s", e)

    def _init_stores(self, nomic_dir: Path) -> None:
        """Initialize optional stores from nomic directory."""
        # EloSystem for leaderboard
        try:
            from aragora.ranking.elo import EloSystem

            elo_path = nomic_dir / "agent_elo.db"
            if elo_path.exists():
                self.elo_system = EloSystem(str(elo_path))
                logger.info("[server] EloSystem loaded")
        except ImportError:
            logger.debug("[server] EloSystem not available (optional dependency)")

        # InsightStore for insights
        try:
            from aragora.insights.store import InsightStore

            insights_path = nomic_dir / DB_INSIGHTS_PATH
            if insights_path.exists():
                self.insight_store = InsightStore(str(insights_path))
                logger.info("[server] InsightStore loaded")
        except ImportError:
            logger.debug("[server] InsightStore not available (optional dependency)")

        # FlipDetector for position reversals
        try:
            from aragora.insights.flip_detector import FlipDetector

            positions_path = nomic_dir / "aragora_positions.db"
            if positions_path.exists():
                self.flip_detector = FlipDetector(str(positions_path))
                logger.info("[server] FlipDetector loaded")
        except ImportError:
            logger.debug("[server] FlipDetector not available (optional dependency)")

        # PersonaManager for agent specialization
        try:
            from aragora.personas.manager import PersonaManager

            personas_path = nomic_dir / DB_PERSONAS_PATH
            if personas_path.exists():
                self.persona_manager = PersonaManager(str(personas_path))
                logger.info("[server] PersonaManager loaded")
        except ImportError:
            logger.debug("[server] PersonaManager not available (optional dependency)")

        # DebateEmbeddingsDatabase for memory
        try:
            from aragora.debate.embeddings import DebateEmbeddingsDatabase

            embeddings_path = nomic_dir / "debate_embeddings.db"
            if embeddings_path.exists():
                self.debate_embeddings = DebateEmbeddingsDatabase(str(embeddings_path))
                logger.info("[server] DebateEmbeddings loaded")
        except ImportError:
            logger.debug("[server] DebateEmbeddings not available (optional dependency)")

    def _cleanup_stale_entries(self) -> None:
        """Remove stale entries from all tracking dicts.

        Delegates to ServerBase.cleanup_all().
        """
        results = self.cleanup_all()
        total = sum(results.values())
        if total > 0:
            logger.debug("Cleaned up %s stale entries", total)

    def _update_debate_state(self, event: StreamEvent) -> None:
        """Update cached debate state based on emitted events.

        Overrides ServerBase._update_debate_state with StreamEvent-specific handling.
        """
        loop_id = event.loop_id
        with self._debate_states_lock:
            if event.type == StreamEventType.DEBATE_START:
                # Enforce max size with LRU eviction (only evict ended debates)
                if len(self.debate_states) >= self.config.max_debate_states:
                    ended_states = [
                        (k, self._debate_states_last_access.get(k, 0))
                        for k, v in self.debate_states.items()
                        if v.get("ended")
                    ]
                    if ended_states:
                        oldest = min(ended_states, key=lambda x: x[1])[0]
                        self.debate_states.pop(oldest, None)
                        self._debate_states_last_access.pop(oldest, None)
                self.debate_states[loop_id] = {
                    "id": loop_id,
                    "task": event.data.get("task"),
                    "agents": event.data.get("agents"),
                    "started_at": event.timestamp,
                    "ended": False,
                }
                self._debate_states_last_access[loop_id] = time.time()
            elif event.type == StreamEventType.DEBATE_END:
                if loop_id in self.debate_states:
                    self.debate_states[loop_id]["ended"] = True
                    self._debate_states_last_access[loop_id] = time.time()
            elif event.type == StreamEventType.LOOP_UNREGISTER:
                self.debate_states.pop(loop_id, None)
                self._debate_states_last_access.pop(loop_id, None)

    def register_loop(self, loop_id: str, name: str, path: str = "") -> None:
        """Register a new nomic loop instance."""
        # Trigger periodic cleanup using base class config
        self._rate_limiter_cleanup_counter += 1
        if self._rate_limiter_cleanup_counter >= self.config.rate_limiter_cleanup_interval:
            self._rate_limiter_cleanup_counter = 0
            self._cleanup_stale_entries()

        instance = LoopInstance(
            loop_id=loop_id,
            name=name,
            started_at=time.time(),
            path=path,
        )
        # Use base class method for active loop management
        self.set_active_loop(loop_id, instance)
        # Broadcast loop registration
        self._emitter.emit(
            StreamEvent(
                type=StreamEventType.LOOP_REGISTER,
                data={
                    "loop_id": loop_id,
                    "name": name,
                    "started_at": instance.started_at,
                    "path": path,
                },
                loop_id=loop_id,
            )
        )

    def unregister_loop(self, loop_id: str) -> None:
        """Unregister a nomic loop instance."""
        self.remove_active_loop(loop_id)
        # Also cleanup associated cartographer to prevent memory leak
        self.unregister_cartographer(loop_id)
        # Broadcast loop unregistration
        self._emitter.emit(
            StreamEvent(
                type=StreamEventType.LOOP_UNREGISTER,
                data={"loop_id": loop_id},
                loop_id=loop_id,
            )
        )

    def update_loop_state(
        self, loop_id: str, cycle: int | None = None, phase: str | None = None
    ) -> None:
        """Update loop state (cycle/phase)."""
        with self._active_loops_lock:
            if loop_id in self.active_loops:
                if cycle is not None:
                    self.active_loops[loop_id].cycle = cycle
                if phase is not None:
                    self.active_loops[loop_id].phase = phase

    def register_cartographer(self, loop_id: str, cartographer: Any) -> None:
        """Register an ArgumentCartographer instance for a loop."""
        with self._cartographers_lock:
            self.cartographers[loop_id] = cartographer

    def unregister_cartographer(self, loop_id: str) -> None:
        """Unregister an ArgumentCartographer instance."""
        with self._cartographers_lock:
            self.cartographers.pop(loop_id, None)

    def _get_loops_data(self) -> list[dict[str, Any]]:
        """Get serializable list of active loops. Thread-safe."""
        with self._active_loops_lock:
            return [
                {
                    "loop_id": loop.loop_id,
                    "name": loop.name,
                    "started_at": loop.started_at,
                    "cycle": loop.cycle,
                    "phase": loop.phase,
                    "path": loop.path,
                }
                for loop in self.active_loops.values()
            ]

    def _cors_headers(self, origin: str | None = None) -> dict[str, str]:
        """Generate CORS headers with proper origin validation.

        Only allows origins in the whitelist. Does NOT fallback to first
        origin for unauthorized requests (that would be a security issue).
        """
        headers = {
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, Accept, Origin, X-Requested-With",
            "Access-Control-Max-Age": "3600",
        }
        # Only add Allow-Origin for whitelisted origins or same-origin requests
        if origin and origin in WS_ALLOWED_ORIGINS:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Credentials"] = "true"
        elif not origin:
            # Same-origin request - no CORS headers needed
            pass
        # For unauthorized origins, don't add Allow-Origin (browser will block)
        return headers

    async def _check_usage_limit(self, headers: dict[str, Any]) -> dict[str, Any] | None:
        """Check if user has remaining debate quota.

        Returns None if within limits, or error dict if limit exceeded.
        """
        try:
            from aragora.billing.jwt_auth import validate_access_token
            from aragora.billing.usage import UsageTracker
            from aragora.storage import UserStore

            # Extract JWT from Authorization header
            auth_header = headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return None  # No JWT, skip check

            token = auth_header[7:]
            if token.startswith("ara_"):
                return None  # API key, skip JWT-based check

            # Validate JWT and get payload (returns JWTPayload dataclass)
            payload = validate_access_token(token)
            if not payload:
                return None  # Invalid token, skip check

            org_id = payload.org_id
            if not org_id:
                return None  # No org in token, skip check

            # Require nomic_dir for UserStore initialization
            if not self.nomic_dir:
                return None

            user_store = UserStore(self.nomic_dir / "users.db")
            org = user_store.get_organization_by_id(org_id)
            if not org:
                return None

            # Get usage for current period
            tracker = UsageTracker()
            usage = tracker.get_summary(org.id)

            # Check tier limits
            tier_limits = {
                "free": 10,
                "starter": 50,
                "professional": 200,
                "enterprise": 999999,
            }
            tier_value = org.tier.value if hasattr(org.tier, "value") else str(org.tier)
            limit = tier_limits.get(tier_value, 10)
            debates_used = usage.total_debates

            if debates_used >= limit:
                return {
                    "error": "Debate limit reached for this billing period",
                    "debates_used": debates_used,
                    "debates_limit": limit,
                    "tier": tier_value,
                    "upgrade_url": "/pricing",
                }

            return None

        except ImportError:
            # Billing module not available, skip check
            return None
        except (AttributeError, TypeError, KeyError, ValueError, OSError) as e:
            logger.debug("Usage limit check failed: %s", e)
            return None  # Fail open to not block debates

    # NOTE: HTTP API handlers (_handle_options, _handle_leaderboard, etc.)
    # are provided by StreamAPIHandlersMixin from stream_handlers.py

    # NOTE: WebSocket handlers (_websocket_handler, _handle_voice_websocket, _drain_loop)
    # are provided by WebSocketHandlerMixin from servers_ws_handler.py

    # NOTE: Route registration and lifecycle (start, stop, _add_versioned_routes)
    # are provided by RouteRegistrationMixin from servers_route_registration.py

    # NOTE: Debate execution methods are delegated to debate_executor module:
    # - parse_debate_request() -> debate_executor.parse_debate_request()
    # - _fetch_trending_topic_async() -> debate_executor.fetch_trending_topic_async()
    # - _execute_debate_thread() -> debate_executor.execute_debate_thread()

    async def _fetch_trending_topic_async(self, category: str | None = None) -> Any | None:
        """Fetch a trending topic for the debate. Delegates to debate_executor."""
        return await fetch_trending_topic_async(category)

    def _execute_debate_thread(
        self,
        debate_id: str,
        question: str,
        agents_str: str,
        rounds: int,
        consensus: str,
        trending_topic: Any | None,
        user_id: str = "",
        org_id: str = "",
    ) -> None:
        """Execute a debate in a background thread. Delegates to debate_executor."""
        execute_debate_thread(
            debate_id=debate_id,
            question=question,
            agents_str=agents_str,
            rounds=rounds,
            consensus=consensus,
            trending_topic=trending_topic,
            emitter=self.emitter,
            user_id=user_id,
            org_id=org_id,
            on_arena_created=self._on_arena_created,
            on_arena_finished=self._on_arena_finished,
        )

    def _on_arena_created(self, arena: Any) -> None:
        """Wire the TTS event bridge to the arena's event bus.

        Called from the debate thread after the Arena is constructed but before
        ``arena.run()`` begins.  Connects the TTS bridge so agent messages are
        synthesized to speech for any active voice sessions.
        """
        event_bus = getattr(arena, "event_bus", None)
        if event_bus is None:
            return

        try:
            from aragora.server.stream.tts_integration import get_tts_integration

            tts_integration = get_tts_integration()
            if tts_integration is None:
                return

            # Use the DebateStreamServer's start_tts_bridge if available,
            # otherwise register TTSIntegration directly on the event bus
            if hasattr(self, "_debate_stream_server") and self._debate_stream_server is not None:
                self._debate_stream_server.start_tts_bridge(
                    event_bus, tts_integration, self._voice_handler
                )
            else:
                tts_integration.register(event_bus)

            logger.info("[server] TTS bridge wired to arena event_bus")
        except (ImportError, RuntimeError, TypeError) as e:
            logger.debug("[server] TTS bridge wiring skipped: %s", e)

    def _on_arena_finished(self, arena: Any) -> None:
        """Clean up the TTS event bridge after a debate completes.

        Called from the debate thread after ``arena.run()`` finishes (success
        or failure).  Schedules asynchronous TTS bridge shutdown.
        """
        if hasattr(self, "_debate_stream_server") and self._debate_stream_server is not None:
            try:
                import asyncio as _aio

                try:
                    loop = _aio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop is not None and loop.is_running():
                    loop.call_soon_threadsafe(
                        _aio.ensure_future, self._debate_stream_server.stop_tts_bridge()
                    )
                else:
                    _aio.run(self._debate_stream_server.stop_tts_bridge())
            except (RuntimeError, OSError) as e:
                logger.debug("[server] TTS bridge cleanup skipped: %s", e)
        logger.debug("[server] Arena finished callback completed")

    async def _handle_start_debate(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """POST /api/debate - Start an ad-hoc debate with specified question.

        Accepts JSON body with:
            question: The topic/question to debate (required)
            agents: Comma-separated agent list (optional, default: "anthropic-api,openai-api,gemini,grok")
            rounds: Number of debate rounds (optional, default: 3)
            consensus: Consensus method (optional, default: "majority")
            use_trending: If true, fetch a trending topic to seed the debate (optional)
            trending_category: Filter trending topics by category (optional)

        All agents participate as proposers for full participation in all rounds.

        Requires authentication when ARAGORA_API_TOKEN is set.
        """
        global _active_debates, _debate_executor
        import aiohttp.web as web

        from aragora.server.auth import check_auth

        origin = request.headers.get("Origin")

        # Authenticate if auth is enabled (starting debates uses compute resources)
        if auth_config.enabled:
            headers = dict(request.headers)
            client_ip = request.remote or ""
            if client_ip in TRUSTED_PROXIES:
                forwarded = request.headers.get("X-Forwarded-For", "")
                if forwarded:
                    client_ip = forwarded.split(",")[0].strip()

            authenticated, remaining = check_auth(headers, "", loop_id="", ip_address=client_ip)
            if not authenticated:
                status = 429 if remaining == 0 else 401
                msg = (
                    "Rate limit exceeded"
                    if remaining == 0
                    else "Authentication required to start debates"
                )
                return web.json_response(
                    {"error": msg}, status=status, headers=self._cors_headers(origin)
                )

            # Check usage limits for authenticated users
            usage_error = await self._check_usage_limit(headers)
            if usage_error:
                return web.json_response(
                    usage_error, status=402, headers=self._cors_headers(origin)
                )

        if not DEBATE_AVAILABLE:
            return web.json_response(
                {"error": "Debate orchestrator not available"},
                status=500,
                headers=self._cors_headers(origin),
            )

        # Parse JSON body
        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
            logger.debug("Invalid JSON in request: %s", e)
            return web.json_response(
                {"error": "Invalid JSON"}, status=400, headers=self._cors_headers(origin)
            )

        # Parse and validate request
        config, error = parse_debate_request(data)
        if error or config is None:
            return web.json_response(
                {"error": error or "Invalid request"},
                status=400,
                headers=self._cors_headers(origin),
            )

        question = config["question"]
        agents_str = config["agents_str"]
        rounds = config["rounds"]
        consensus = config["consensus"]

        # Fetch trending topic if requested
        trending_topic = None
        if config["use_trending"]:
            trending_topic = await self._fetch_trending_topic_async(config["trending_category"])

        # Extract user/org context from JWT for usage tracking
        user_id = ""
        org_id = ""
        try:
            from aragora.billing.jwt_auth import validate_access_token

            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer ") and not auth_header[7:].startswith("ara_"):
                payload = validate_access_token(auth_header[7:])
                if payload:
                    # JWTPayload is a dataclass, use attribute access not dict
                    user_id = payload.sub or ""
                    org_id = payload.org_id or ""
        except ImportError:
            pass

        # Generate debate ID
        debate_id = f"adhoc_{uuid.uuid4().hex[:8]}"

        # Track this debate (thread-safe)
        with _active_debates_lock:
            _active_debates[debate_id] = {
                "id": debate_id,
                "question": question,
                "status": "starting",
                "agents": agents_str,
                "rounds": rounds,
            }

        # Periodic cleanup of stale debates (every 100 debates)
        if increment_cleanup_counter():
            _cleanup_stale_debates_stream()

        # Set loop_id on emitter so events are tagged
        self.emitter.set_loop_id(debate_id)

        # Use thread pool to prevent unbounded thread creation
        executor = get_debate_executor()
        with _debate_executor_lock:
            if executor is None:
                executor = ThreadPoolExecutor(
                    max_workers=MAX_CONCURRENT_DEBATES, thread_name_prefix="debate-"
                )
                set_debate_executor(executor)

        try:
            executor.submit(
                self._execute_debate_thread,
                debate_id,
                question,
                agents_str,
                rounds,
                consensus,
                trending_topic,
                user_id,
                org_id,
            )
        except RuntimeError:
            return web.json_response(
                {
                    "success": False,
                    "error": "Server at capacity. Please try again later.",
                },
                status=503,
                headers=self._cors_headers(origin),
            )

        # Return immediately with debate ID
        return web.json_response(
            {
                "success": True,
                "debate_id": debate_id,
                "question": question,
                "agents": agents_str.split(","),
                "rounds": rounds,
                "status": "starting",
                "message": "Debate started. Connect to WebSocket to receive events.",
            },
            headers=self._cors_headers(origin),
        )
