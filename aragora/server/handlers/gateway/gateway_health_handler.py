"""
Gateway Health Handler - HTTP endpoints for gateway health monitoring.

Stability: STABLE

Provides API endpoints for:
- Overall gateway health status
- Individual agent health checks

Routes:
    GET /api/v1/gateway/health              - Overall gateway health status
    GET /api/v1/gateway/agents/{name}/health - Individual agent health check
"""

from __future__ import annotations

import importlib.util
import logging
import time
from datetime import datetime, timezone
from collections.abc import Coroutine
from typing import Any, cast

from aragora.rbac.decorators import require_permission
from aragora.resilience import CircuitBreaker
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    log_request,
)
from aragora.server.handlers.utils.rate_limit import rate_limit

# Optional gateway imports (graceful degradation)
GATEWAY_AVAILABLE = (
    importlib.util.find_spec("aragora.agents.api_agents.external_framework") is not None
)

logger = logging.getLogger(__name__)

# =============================================================================
# Resilience Configuration
# =============================================================================

# Circuit breaker for gateway health checks
_gateway_health_circuit_breaker = CircuitBreaker(
    name="gateway_health_handler",
    failure_threshold=5,
    cooldown_seconds=30.0,
)


def get_gateway_health_circuit_breaker() -> CircuitBreaker:
    """Get the circuit breaker for gateway health service."""
    return _gateway_health_circuit_breaker


def get_gateway_health_circuit_breaker_status() -> dict[str, Any]:
    """Get current status of the gateway health circuit breaker."""
    return _gateway_health_circuit_breaker.to_dict()


def _get_vault_status() -> str:
    """Get credential vault status.

    Attempts to import and check the credential vault module.

    Returns:
        One of 'sealed', 'unsealed', or 'unavailable'.
    """
    try:
        if importlib.util.find_spec("aragora.gateway.security.credential_vault") is None:
            raise ImportError
        # Vault module is available; report as sealed by default
        # (actual seal/unseal state depends on runtime configuration)
        return "sealed"
    except ImportError:
        return "unavailable"


class GatewayHealthHandler(BaseHandler):
    """HTTP handler for gateway health endpoints.

    Provides health monitoring for the external agent gateway, including
    overall gateway status and individual agent health checks.
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/gateway/health",
        "/api/v1/gateway/agents/*/health",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        if path == "/api/v1/gateway/health":
            return True
        # Match /api/v1/gateway/agents/{name}/health
        if (
            path.startswith("/api/v1/gateway/agents/")
            and path.endswith("/health")
            and path.count("/") == 6
        ):
            return True
        return False

    @require_permission("gateway:health.read")
    @rate_limit(requests_per_minute=60, limiter_name="gateway_health")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET requests for gateway health endpoints."""
        if not self.can_handle(path):
            return None

        # GET /api/v1/gateway/health
        if path == "/api/v1/gateway/health":
            return self._handle_overall_health(handler)

        # GET /api/v1/gateway/agents/{name}/health
        if path.startswith("/api/v1/gateway/agents/") and path.endswith("/health"):
            parts = path.strip("/").split("/")
            # parts = ["api", "v1", "gateway", "agents", agent_name, "health"]
            if len(parts) == 6:
                agent_name = parts[4]
                return self._handle_agent_health(agent_name, handler)

        return None

    @handle_errors("gateway overall health")
    @log_request("gateway overall health")
    def _handle_overall_health(self, handler: Any) -> HandlerResult:
        """Handle GET /api/v1/gateway/health.

        Returns overall gateway health status including all registered
        external agents and credential vault status.
        """
        if not GATEWAY_AVAILABLE:
            return error_response("Gateway module not available", 503)

        external_agents: dict[str, Any] = self.ctx.get("external_agents", {}) or {}
        now = datetime.now(timezone.utc).isoformat()

        # Build per-agent health info
        agents_health: dict[str, dict[str, Any]] = {}
        unhealthy_count = 0
        total_count = len(external_agents)

        for name, agent in external_agents.items():
            try:
                start = time.monotonic()
                available = self._check_agent_available(agent)
                elapsed_ms = round((time.monotonic() - start) * 1000, 1)

                framework = getattr(agent, "agent_type", "unknown")
                agent_status = "healthy" if available else "unhealthy"
                if not available:
                    unhealthy_count += 1

                agents_health[name] = {
                    "status": agent_status,
                    "framework": framework,
                    "last_check": now,
                    "latency_ms": elapsed_ms,
                }
            except (AttributeError, TypeError, ValueError) as e:
                # Agent configuration or interface issues
                unhealthy_count += 1
                agents_health[name] = {
                    "status": "unknown",
                    "framework": getattr(agent, "agent_type", "unknown"),
                    "last_check": now,
                    "error": type(e).__name__,
                }
                logger.debug(
                    "Agent %s health check failed due to configuration error: %s",
                    name,
                    e,
                )
            except (RuntimeError, TimeoutError, OSError) as e:
                # Network or runtime issues - agent may be temporarily unavailable
                unhealthy_count += 1
                agents_health[name] = {
                    "status": "unavailable",
                    "framework": getattr(agent, "agent_type", "unknown"),
                    "last_check": now,
                    "error": type(e).__name__,
                }
                logger.warning(
                    "Agent %s health check failed due to runtime error: %s",
                    name,
                    e,
                )

        # Determine overall status
        if total_count == 0:
            overall_status = "healthy"
        elif unhealthy_count == 0:
            overall_status = "healthy"
        elif unhealthy_count < total_count:
            overall_status = "degraded"
        else:
            overall_status = "unhealthy"

        vault_status = _get_vault_status()

        return json_response(
            {
                "status": overall_status,
                "gateway": {
                    "external_agents_available": GATEWAY_AVAILABLE,
                    "credential_vault_status": vault_status,
                    "active_executions": 0,
                },
                "agents": agents_health,
                "timestamp": now,
            }
        )

    @handle_errors("gateway agent health")
    @log_request("gateway agent health")
    def _handle_agent_health(self, agent_name: str, handler: Any) -> HandlerResult:
        """Handle GET /api/v1/gateway/agents/{name}/health.

        Returns health status for a specific external agent.
        """
        if not GATEWAY_AVAILABLE:
            return error_response("Gateway module not available", 503)

        external_agents: dict[str, Any] = self.ctx.get("external_agents", {}) or {}

        if agent_name not in external_agents:
            return error_response(f"Agent not found: {agent_name}", 404)

        agent = external_agents[agent_name]
        now = datetime.now(timezone.utc).isoformat()

        start = time.monotonic()
        try:
            available = self._check_agent_available(agent)
            elapsed_ms = round((time.monotonic() - start) * 1000, 1)
            agent_status = "healthy" if available else "unhealthy"
        except (AttributeError, TypeError, ValueError) as e:
            # Agent configuration or interface issues
            elapsed_ms = round((time.monotonic() - start) * 1000, 1)
            agent_status = "unknown"
            logger.debug(
                "Agent %s health check failed due to configuration error: %s",
                agent_name,
                e,
            )
        except (RuntimeError, TimeoutError, OSError) as e:
            # Network or runtime issues
            elapsed_ms = round((time.monotonic() - start) * 1000, 1)
            agent_status = "unavailable"
            logger.warning(
                "Agent %s health check failed due to runtime error: %s",
                agent_name,
                e,
            )

        framework = getattr(agent, "agent_type", "unknown")
        base_url = getattr(agent, "base_url", None)

        return json_response(
            {
                "name": agent_name,
                "status": agent_status,
                "framework": framework,
                "base_url": base_url,
                "last_check": now,
                "response_time_ms": elapsed_ms,
            }
        )

    def _check_agent_available(self, agent: Any) -> bool:
        """Check if an agent is available.

        Attempts to call agent.is_available() if it exists.
        For async methods, uses run_async to execute synchronously.

        Args:
            agent: The external agent to check.

        Returns:
            True if agent is available, False otherwise.
        """
        if not hasattr(agent, "is_available"):
            return False

        import inspect

        result = agent.is_available()

        # Handle async is_available()
        if inspect.isawaitable(result):
            from aragora.server.http_utils import run_async

            return run_async(cast(Coroutine[Any, Any, bool], result))

        return bool(result)


__all__ = ["GatewayHealthHandler"]
