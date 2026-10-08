"""
Gateway Agents Handler - HTTP endpoints for external agent registration.

Stability: STABLE
Graduated from EXPERIMENTAL on 2026-02-02.

Provides API endpoints for managing external framework agents that can
participate in Aragora debates via the gateway.

Routes:
    POST   /api/v1/gateway/agents          - Register a new external agent
    GET    /api/v1/gateway/agents          - List registered agents
    GET    /api/v1/gateway/agents/{name}   - Get agent details
    DELETE /api/v1/gateway/agents/{name}   - Unregister an agent
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import threading
from typing import Any

from aragora.resilience import CircuitBreaker
from aragora.rbac.decorators import require_permission

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    log_request,
)
from aragora.server.handlers.utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)


# =============================================================================
# Circuit Breaker Configuration
# =============================================================================

# Circuit breaker for gateway agents operations
# Opens after 5 consecutive failures, recovers after 30 seconds
_gateway_agents_circuit_breaker = CircuitBreaker(
    name="gateway_agents_handler",
    failure_threshold=5,
    cooldown_seconds=30.0,
    half_open_success_threshold=2,
    half_open_max_calls=3,
)
_gateway_agents_circuit_breaker_lock = threading.Lock()


def get_gateway_agents_circuit_breaker() -> CircuitBreaker:
    """Get the global circuit breaker for gateway agents operations."""
    return _gateway_agents_circuit_breaker


def get_gateway_agents_circuit_breaker_status() -> dict[str, Any]:
    """Get current status of the gateway agents circuit breaker."""
    return _gateway_agents_circuit_breaker.to_dict()


def reset_gateway_agents_circuit_breaker() -> None:
    """Reset the global circuit breaker (for testing)."""
    with _gateway_agents_circuit_breaker_lock:
        _gateway_agents_circuit_breaker._single_failures = 0
        _gateway_agents_circuit_breaker._single_open_at = 0.0
        _gateway_agents_circuit_breaker._single_successes = 0
        _gateway_agents_circuit_breaker._single_half_open_calls = 0


# Optional dependencies for graceful degradation
GATEWAY_AVAILABLE = (
    importlib.util.find_spec("aragora.agents.api_agents.external_framework") is not None
)
SSRF_AVAILABLE = importlib.util.find_spec("aragora.security.ssrf_protection") is not None

# Validation constants
AGENT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
ALLOWED_FRAMEWORKS = {"openclaw", "crewai", "autogen", "langgraph", "custom"}
DEFAULT_TIMEOUT = 30


class GatewayAgentsHandler(BaseHandler):
    """
    HTTP request handler for external agent registration endpoints.

    Provides REST API for registering, listing, and unregistering
    external framework agents that can participate in debates.
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/gateway/agents",
        "/api/v1/gateway/agents/*",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        return path.startswith("/api/v1/gateway/agents")

    def _get_external_agents(self) -> dict[str, Any]:
        """Get or initialize the external agents registry from context."""
        agents = self.ctx.get("external_agents")
        if agents is None:
            agents = {}
            self.ctx["external_agents"] = agents
        return agents

    def _validate_base_url(self, base_url: str) -> HandlerResult | None:
        """Validate base_url for security concerns.

        Returns None if valid, error HandlerResult if invalid.
        """
        if not base_url:
            return error_response("base_url is required", 400)

        # Check protocol
        allow_insecure = os.environ.get("ARAGORA_ALLOW_INSECURE_AGENTS", "").lower() in (
            "1",
            "true",
            "yes",
        )

        if not allow_insecure and not base_url.startswith("https://"):
            return error_response(
                "base_url must use HTTPS. Set ARAGORA_ALLOW_INSECURE_AGENTS=true to allow HTTP.",
                400,
            )

        if allow_insecure and not (
            base_url.startswith("https://") or base_url.startswith("http://")
        ):
            return error_response("base_url must use HTTP or HTTPS", 400)

        # SSRF validation
        if SSRF_AVAILABLE:
            from aragora.security.ssrf_protection import validate_url

            result = validate_url(base_url, resolve_dns=True)
            if not result.is_safe:
                logger.warning(
                    "SSRF validation failed for agent base_url: %s - %s",
                    base_url,
                    result.error,
                )
                return error_response(
                    f"base_url failed security validation: {result.error}",
                    400,
                )

        return None

    def _extract_agent_name(self, path: str) -> str | None:
        """Extract agent name from path like /api/v1/gateway/agents/{name}."""
        parts = path.rstrip("/").split("/")
        # Expected: ["", "api", "v1", "gateway", "agents", "{name}"]
        if len(parts) >= 6 and parts[4] == "agents":
            name = parts[5]
            if name and name != "agents":
                return name
        return None

    @require_permission("gateway:agent.read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET requests."""
        if not self.can_handle(path):
            return None

        if not GATEWAY_AVAILABLE:
            return error_response("Gateway agents module not available", 503)

        # GET /api/v1/gateway/agents/{name}
        agent_name = self._extract_agent_name(path)
        if agent_name:
            return self._handle_get_agent(agent_name, handler)

        # GET /api/v1/gateway/agents
        if path.rstrip("/") == "/api/v1/gateway/agents":
            return self._handle_list_agents(query_params, handler)

        return None

    @handle_errors("gateway agents creation")
    @require_permission("gateway:agent.create")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests."""
        if not self.can_handle(path):
            return None

        if not GATEWAY_AVAILABLE:
            return error_response("Gateway agents module not available", 503)

        # POST /api/v1/gateway/agents
        if path.rstrip("/") == "/api/v1/gateway/agents":
            return self._handle_register_agent(handler)

        return None

    @handle_errors("gateway agents deletion")
    @require_permission("gateway:agent.delete")
    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle DELETE requests."""
        if not self.can_handle(path):
            return None

        if not GATEWAY_AVAILABLE:
            return error_response("Gateway agents module not available", 503)

        # DELETE /api/v1/gateway/agents/{name}
        agent_name = self._extract_agent_name(path)
        if agent_name:
            return self._handle_delete_agent(agent_name, handler)

        return None

    # =========================================================================
    # Agent Handlers
    # =========================================================================

    @rate_limit(requests_per_minute=60, limiter_name="gateway_agents_list")
    @handle_errors("list gateway agents")
    def _handle_list_agents(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        """Handle GET /api/v1/gateway/agents."""
        agents = self._get_external_agents()

        agent_list = []
        for name, info in agents.items():
            agent_list.append(
                {
                    "name": name,
                    "framework_type": info.get("framework_type", "custom"),
                    "base_url": info.get("base_url", ""),
                    "timeout": info.get("timeout", DEFAULT_TIMEOUT),
                    "status": "registered",
                }
            )

        return json_response(
            {
                "agents": agent_list,
                "total": len(agent_list),
            }
        )

    @rate_limit(requests_per_minute=60, limiter_name="gateway_agents_get")
    @handle_errors("get gateway agent")
    def _handle_get_agent(self, agent_name: str, handler: Any) -> HandlerResult:
        """Handle GET /api/v1/gateway/agents/{name}."""
        agents = self._get_external_agents()

        if agent_name not in agents:
            return error_response(f"Agent not found: {agent_name}", 404)

        info = agents[agent_name]

        return json_response(
            {
                "name": agent_name,
                "framework_type": info.get("framework_type", "custom"),
                "base_url": info.get("base_url", ""),
                "timeout": info.get("timeout", DEFAULT_TIMEOUT),
                "status": "registered",
                "config": info.get("config", {}),
            }
        )

    @rate_limit(requests_per_minute=10, limiter_name="gateway_agents_register")
    @handle_errors("register gateway agent")
    @log_request("register gateway agent")
    def _handle_register_agent(self, handler: Any) -> HandlerResult:
        """Handle POST /api/v1/gateway/agents."""
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        # Validate required fields
        name = body.get("name")
        if not name:
            return error_response("name is required", 400)

        base_url = body.get("base_url")
        if not base_url:
            return error_response("base_url is required", 400)

        framework_type = body.get("framework_type")
        if not framework_type:
            return error_response("framework_type is required", 400)

        # Validate name format
        if not AGENT_NAME_PATTERN.match(name):
            return error_response(
                "Invalid agent name. Must be alphanumeric with hyphens/underscores, "
                "start with alphanumeric, and be at most 64 characters.",
                400,
            )

        # Validate framework type
        if framework_type not in ALLOWED_FRAMEWORKS:
            return error_response(
                f"Invalid framework_type: {framework_type}. "
                f"Must be one of: {', '.join(sorted(ALLOWED_FRAMEWORKS))}",
                400,
            )

        # Validate base_url
        url_error = self._validate_base_url(base_url)
        if url_error:
            return url_error

        # Check for duplicate
        agents = self._get_external_agents()
        if name in agents:
            return error_response(f"Agent with name '{name}' already exists", 409)

        # Store agent info
        timeout = body.get("timeout", DEFAULT_TIMEOUT)
        config = body.get("config", {})
        api_key_env = body.get("api_key_env")

        agent_info: dict[str, Any] = {
            "name": name,
            "framework_type": framework_type,
            "base_url": base_url,
            "timeout": timeout,
            "config": config,
        }
        if api_key_env:
            agent_info["api_key_env"] = api_key_env

        agents[name] = agent_info

        logger.info("Registered external agent: %s (framework=%s)", name, framework_type)

        return json_response(
            {
                "name": name,
                "framework_type": framework_type,
                "base_url": base_url,
                "registered": True,
                "message": "Agent registered successfully",
            },
            status=201,
        )

    @rate_limit(requests_per_minute=10, limiter_name="gateway_agents_delete")
    @handle_errors("delete gateway agent")
    @log_request("delete gateway agent")
    def _handle_delete_agent(self, agent_name: str, handler: Any) -> HandlerResult:
        """Handle DELETE /api/v1/gateway/agents/{name}."""
        agents = self._get_external_agents()

        if agent_name not in agents:
            return error_response(f"Agent not found: {agent_name}", 404)

        del agents[agent_name]

        logger.info("Unregistered external agent: %s", agent_name)

        return json_response(
            {
                "name": agent_name,
                "message": "Agent unregistered successfully",
            }
        )


__all__ = [
    "GatewayAgentsHandler",
    "get_gateway_agents_circuit_breaker",
    "get_gateway_agents_circuit_breaker_status",
    "reset_gateway_agents_circuit_breaker",
]
