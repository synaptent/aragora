"""
Route registration and server lifecycle mixin for AiohttpUnifiedServer.

Extracts the optional handler imports, route registration logic, and
start()/stop() methods into a dedicated mixin class.

This keeps the core server class focused on initialization and state management.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

# =============================================================================
# Optional handler imports (Phase 2+)
# Each handler is independently guarded so missing dependencies don't break startup.
# =============================================================================

try:
    from aragora.server.handlers.inbox_command import (
        register_routes as register_inbox_routes,
    )

    INBOX_HANDLER_AVAILABLE = True
except ImportError:
    INBOX_HANDLER_AVAILABLE = False

try:
    from aragora.server.handlers.codebase.quick_scan import (
        register_routes as register_codebase_routes,
    )

    CODEBASE_HANDLER_AVAILABLE = True
except ImportError:
    CODEBASE_HANDLER_AVAILABLE = False

try:
    from aragora.server.handlers.accounting import register_accounting_routes

    ACCOUNTING_HANDLER_AVAILABLE = True
except ImportError:
    ACCOUNTING_HANDLER_AVAILABLE = False

try:
    from aragora.server.handlers.payments import register_payment_routes

    PAYMENT_HANDLER_AVAILABLE = True
except ImportError:
    PAYMENT_HANDLER_AVAILABLE = False

try:
    from aragora.server.handlers.costs import register_routes as register_cost_routes

    COST_HANDLER_AVAILABLE = True
except ImportError:
    COST_HANDLER_AVAILABLE = False

try:
    from aragora.server.handlers.features.integrations import (
        IntegrationsHandler,
        register_integration_routes,
    )

    INTEGRATIONS_HANDLER_AVAILABLE = True
except ImportError:
    INTEGRATIONS_HANDLER_AVAILABLE = False

try:
    from aragora.server.handlers.integrations.email_webhook import (
        register_email_webhook_routes,
    )

    EMAIL_WEBHOOK_HANDLER_AVAILABLE = True
except ImportError:
    EMAIL_WEBHOOK_HANDLER_AVAILABLE = False

try:
    from aragora.server.handlers.security.threat_intel import register_threat_intel_routes

    THREAT_INTEL_HANDLER_AVAILABLE = True
except ImportError:
    THREAT_INTEL_HANDLER_AVAILABLE = False

try:
    from aragora.server.handlers.admin.credits import (
        CreditsAdminHandler,
        register_credits_admin_routes,
    )

    CREDITS_ADMIN_HANDLER_AVAILABLE = True
except ImportError:
    CREDITS_ADMIN_HANDLER_AVAILABLE = False

try:
    from aragora.server.handlers.autonomous.alerts import AlertHandler
    from aragora.server.handlers.autonomous.triggers import TriggerHandler
    from aragora.server.handlers.autonomous.approvals import ApprovalHandler
    from aragora.server.handlers.autonomous.monitoring import MonitoringHandler
    from aragora.server.handlers.autonomous.learning import LearningHandler

    AUTONOMOUS_HANDLERS_AVAILABLE = True
except ImportError:
    AUTONOMOUS_HANDLERS_AVAILABLE = False

try:
    from aragora.server.stream.pipeline_stream import register_pipeline_stream_routes

    PIPELINE_STREAM_AVAILABLE = True
except ImportError:
    PIPELINE_STREAM_AVAILABLE = False

try:
    from aragora.server.stream.workflow_stream import register_workflow_stream_routes

    WORKFLOW_STREAM_AVAILABLE = True
except ImportError:
    WORKFLOW_STREAM_AVAILABLE = False

try:
    from aragora.server.stream.oracle_stream import register_oracle_stream_routes

    ORACLE_STREAM_AVAILABLE = True
except ImportError:
    ORACLE_STREAM_AVAILABLE = False

try:
    from aragora.server.handlers.debates.intervention import register_intervention_routes

    INTERVENTION_HANDLER_AVAILABLE = True
except ImportError:
    INTERVENTION_HANDLER_AVAILABLE = False


def _register_optional_routes(app: Any) -> None:
    """Register optional handler routes on the aiohttp application.

    Each handler registration is independently guarded so that missing
    optional dependencies do not prevent the server from starting.
    """
    if INBOX_HANDLER_AVAILABLE:
        register_inbox_routes(app)
        logger.info("Registered inbox command center routes")
    if CODEBASE_HANDLER_AVAILABLE:
        register_codebase_routes(app)
        logger.info("Registered codebase analysis routes")
    if ACCOUNTING_HANDLER_AVAILABLE:
        register_accounting_routes(app)
        logger.info("Registered accounting routes")
    if PAYMENT_HANDLER_AVAILABLE:
        register_payment_routes(app)
        logger.info("Registered payment routes")
    if COST_HANDLER_AVAILABLE:
        register_cost_routes(app)
        logger.info("Registered cost routes")
    if INTEGRATIONS_HANDLER_AVAILABLE:
        server_context: dict[str, Any] = {}
        integrations_handler = IntegrationsHandler(server_context)
        register_integration_routes(app, integrations_handler)
        logger.info("Registered integration status routes")
    if EMAIL_WEBHOOK_HANDLER_AVAILABLE:
        register_email_webhook_routes(app)
        logger.info("Registered email webhook routes")
    if THREAT_INTEL_HANDLER_AVAILABLE:
        register_threat_intel_routes(app)
        logger.info("Registered threat intel routes")
    if CREDITS_ADMIN_HANDLER_AVAILABLE:
        credits_handler = CreditsAdminHandler()
        register_credits_admin_routes(app, credits_handler)
        logger.info("Registered credits admin routes")
    if AUTONOMOUS_HANDLERS_AVAILABLE:
        AlertHandler.register_routes(app)
        TriggerHandler.register_routes(app)
        ApprovalHandler.register_routes(app)
        MonitoringHandler.register_routes(app)
        LearningHandler.register_routes(app)
        logger.info("Registered autonomous agent routes")
    if INTERVENTION_HANDLER_AVAILABLE:
        register_intervention_routes(app.router)
        logger.info("Registered debate intervention routes")


class RouteRegistrationMixin:
    """
    Mixin class providing route registration and server lifecycle for AiohttpUnifiedServer.

    This mixin expects the following attributes/methods from the parent class:
    - host: str
    - port: int
    - _running: bool
    - _stop_event: asyncio.Event | None
    - _handle_options: handler method
    - _handle_leaderboard: handler method
    - _handle_matches_recent: handler method
    - _handle_insights_recent: handler method
    - _handle_flips_summary: handler method
    - _handle_flips_recent: handler method
    - _handle_tournaments: handler method
    - _handle_tournament_details: handler method
    - _handle_agent_consistency: handler method
    - _handle_agent_network: handler method
    - _handle_memory_tier_stats: handler method
    - _handle_laboratory_emergent_traits: handler method
    - _handle_laboratory_cross_pollinations: handler method
    - _handle_health: handler method
    - _handle_nomic_state: handler method
    - _handle_graph_json: handler method
    - _handle_graph_mermaid: handler method
    - _handle_graph_stats: handler method
    - _handle_audience_clusters: handler method
    - _handle_replays: handler method
    - _handle_replay_html: handler method
    - _handle_start_debate: handler method
    - _handle_metrics: handler method
    - _websocket_handler: handler method
    - _handle_spectate_websocket: handler method
    - _handle_voice_websocket: handler method
    - _drain_loop: coroutine
    """

    # Attributes provided by the host class (declared for type checking)
    if TYPE_CHECKING:
        _handle_options: Any
        _handle_leaderboard: Any
        _handle_matches_recent: Any
        _handle_insights_recent: Any
        _handle_flips_summary: Any
        _handle_flips_recent: Any
        _handle_tournaments: Any
        _handle_tournament_details: Any
        _handle_agent_consistency: Any
        _handle_agent_network: Any
        _handle_memory_tier_stats: Any
        _handle_laboratory_emergent_traits: Any
        _handle_laboratory_cross_pollinations: Any
        _handle_health: Any
        _handle_nomic_state: Any
        _handle_graph_json: Any
        _handle_graph_mermaid: Any
        _handle_graph_stats: Any
        _handle_audience_clusters: Any
        _handle_replays: Any
        _handle_replay_html: Any
        _handle_start_debate: Any
        _websocket_handler: Any
        _handle_spectate_websocket: Any
        _handle_voice_websocket: Any
        _handle_metrics: Any
        _drain_loop: Any
        _running: Any
        _stop_event: Any
        host: Any
        port: Any

    def _add_versioned_routes(self, app: Any, routes: list) -> None:
        """Add both versioned (/api/v1/) and legacy (/api/) routes.

        This enables API versioning while maintaining backwards compatibility.
        Routes registered:
        - /api/v1/{path} - Versioned (preferred)
        - /api/{path}    - Legacy (deprecated, for backwards compatibility)

        Args:
            app: aiohttp Application
            routes: List of (method, path, handler) tuples where path is without prefix
        """
        for method, path, handler in routes:
            # Add versioned route (preferred)
            v1_path = f"/api/v1{path}"
            # Add legacy route (backwards compatible)
            legacy_path = f"/api{path}"

            if method == "GET":
                app.router.add_get(v1_path, handler)
                app.router.add_get(legacy_path, handler)
            elif method == "POST":
                app.router.add_post(v1_path, handler)
                app.router.add_post(legacy_path, handler)
            elif method == "PUT":
                app.router.add_put(v1_path, handler)
                app.router.add_put(legacy_path, handler)
            elif method == "DELETE":
                app.router.add_delete(v1_path, handler)
                app.router.add_delete(legacy_path, handler)

    async def start(self) -> None:
        """Start the unified HTTP+WebSocket server."""
        import aiohttp.web as web

        # Initialize error monitoring (no-op if SENTRY_DSN not set)
        try:
            from aragora.server.error_monitoring import init_monitoring

            if init_monitoring():
                logger.info("Error monitoring enabled (Sentry)")
        except ImportError:
            pass  # sentry-sdk not installed

        self._running = True

        # Create aiohttp app
        app = web.Application()

        # Add OPTIONS handler for CORS preflight
        app.router.add_route("OPTIONS", "/{path:.*}", self._handle_options)

        # Define API routes (path suffix after /api or /api/v1)
        api_routes = [
            ("GET", "/leaderboard", self._handle_leaderboard),
            ("GET", "/matches/recent", self._handle_matches_recent),
            ("GET", "/insights/recent", self._handle_insights_recent),
            ("GET", "/flips/summary", self._handle_flips_summary),
            ("GET", "/flips/recent", self._handle_flips_recent),
            ("GET", "/tournaments", self._handle_tournaments),
            ("GET", "/tournaments/{tournament_id}", self._handle_tournament_details),
            ("GET", "/agent/{name}/consistency", self._handle_agent_consistency),
            ("GET", "/agent/{name}/network", self._handle_agent_network),
            ("GET", "/memory/tier-stats", self._handle_memory_tier_stats),
            ("GET", "/laboratory/emergent-traits", self._handle_laboratory_emergent_traits),
            (
                "GET",
                "/laboratory/cross-pollinations/suggest",
                self._handle_laboratory_cross_pollinations,
            ),
            ("GET", "/health", self._handle_health),
            ("GET", "/nomic/state", self._handle_nomic_state),
            ("GET", "/debate/{loop_id}/graph", self._handle_graph_json),
            ("GET", "/debate/{loop_id}/graph/mermaid", self._handle_graph_mermaid),
            ("GET", "/debate/{loop_id}/graph/stats", self._handle_graph_stats),
            ("GET", "/debate/{loop_id}/audience/clusters", self._handle_audience_clusters),
            ("GET", "/replays", self._handle_replays),
            ("GET", "/replays/{replay_id}/html", self._handle_replay_html),
            ("POST", "/debate", self._handle_start_debate),
        ]

        # Add routes with both versioned and legacy paths
        self._add_versioned_routes(app, api_routes)

        # WebSocket handlers (not versioned)
        app.router.add_get("/", self._websocket_handler)
        app.router.add_get("/ws", self._websocket_handler)
        app.router.add_get("/ws/voice/{debate_id}", self._handle_voice_websocket)
        app.router.add_get("/ws/spectate", self._handle_spectate_websocket)
        app.router.add_get("/ws/spectate/{debate_id}", self._handle_spectate_websocket)
        app.router.add_get("/spectate/{debate_id}", self._handle_spectate_websocket)
        if PIPELINE_STREAM_AVAILABLE:
            register_pipeline_stream_routes(app)
            logger.info("Registered pipeline stream WebSocket route at /ws/pipeline")
        if WORKFLOW_STREAM_AVAILABLE:
            register_workflow_stream_routes(app)
            logger.info("Registered workflow stream WebSocket route at /ws/workflow")
        if ORACLE_STREAM_AVAILABLE:
            register_oracle_stream_routes(app)
            logger.info("Registered oracle stream WebSocket route at /ws/oracle")

        # Prometheus metrics endpoint (not under /api/)
        app.router.add_get("/metrics", self._handle_metrics)

        # Register Phase 2+ optional handlers
        _register_optional_routes(app)

        # Start drain loop
        _drain_task = asyncio.create_task(self._drain_loop())
        _drain_task.add_done_callback(
            lambda t: logger.critical("Server drain loop crashed: %s", t.exception())
            if not t.cancelled() and t.exception()
            else None
        )

        # Run server
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)

        logger.info("Unified server (HTTP+WS) running on http://%s:%s", self.host, self.port)
        logger.info("  WebSocket: ws://%s:%s/", self.host, self.port)
        logger.info("  Voice WS:  ws://%s:%s/ws/voice/{debate_id}", self.host, self.port)
        logger.info("  Spectate:  ws://%s:%s/spectate/{debate_id}", self.host, self.port)
        logger.info("  HTTP API:  http://%s:%s/api/v1/* (preferred)", self.host, self.port)
        logger.info("  Legacy:    http://%s:%s/api/* (deprecated)", self.host, self.port)

        await site.start()

        # Create stop event for graceful shutdown
        self._stop_event = asyncio.Event()

        # Keep running until shutdown signal
        try:
            await self._stop_event.wait()
        finally:
            self._running = False
            await runner.cleanup()

    def stop(self) -> None:
        """Stop the server."""
        self._running = False
        if self._stop_event:
            self._stop_event.set()
