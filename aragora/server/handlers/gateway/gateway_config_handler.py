"""
Gateway Configuration Handler - HTTP endpoints for gateway configuration management.

Provides API endpoints for:
- Retrieving current gateway configuration
- Updating gateway configuration
- Getting default configuration values

Routes:
    GET    /api/v1/gateway/config          - Get current gateway configuration
    POST   /api/v1/gateway/config          - Update gateway configuration
    GET    /api/v1/gateway/config/defaults - Get default configuration values
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

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


# Configuration validation rules
CONFIG_VALIDATORS = {
    "agent_timeout": lambda v: isinstance(v, (int, float)) and 1 <= v <= 300,
    "max_concurrent_agents": lambda v: isinstance(v, int) and 1 <= v <= 100,
    "consensus_threshold": lambda v: isinstance(v, (int, float)) and 0.0 <= v <= 1.0,
    "min_verification_quorum": lambda v: isinstance(v, int) and 1 <= v <= 10,
    "rate_limit_requests_per_minute": lambda v: isinstance(v, int) and 1 <= v <= 1000,
    "credential_cache_ttl_seconds": lambda v: isinstance(v, int) and 0 <= v <= 3600,
    "circuit_breaker_failure_threshold": lambda v: isinstance(v, int) and 1 <= v <= 20,
    "circuit_breaker_recovery_timeout": lambda v: isinstance(v, int) and 1 <= v <= 600,
    "allow_http_agents": lambda v: isinstance(v, bool),
    "require_ssrf_validation": lambda v: isinstance(v, bool),
}

# Human-readable validation error messages
CONFIG_VALIDATION_MESSAGES = {
    "agent_timeout": "agent_timeout must be between 1 and 300 seconds",
    "max_concurrent_agents": "max_concurrent_agents must be between 1 and 100",
    "consensus_threshold": "consensus_threshold must be between 0.0 and 1.0",
    "min_verification_quorum": "min_verification_quorum must be between 1 and 10",
    "rate_limit_requests_per_minute": "rate_limit_requests_per_minute must be between 1 and 1000",
    "credential_cache_ttl_seconds": "credential_cache_ttl_seconds must be between 0 and 3600",
    "circuit_breaker_failure_threshold": "circuit_breaker_failure_threshold must be between 1 and 20",
    "circuit_breaker_recovery_timeout": "circuit_breaker_recovery_timeout must be between 1 and 600",
    "allow_http_agents": "allow_http_agents must be a boolean",
    "require_ssrf_validation": "require_ssrf_validation must be a boolean",
}


class GatewayConfigHandler(BaseHandler):
    """HTTP handler for gateway configuration endpoints."""

    ROUTES = [
        "/api/v1/gateway/config",
        "/api/v1/gateway/config/defaults",
    ]

    # Default configuration values
    DEFAULT_CONFIG = {
        "agent_timeout": 30,
        "max_concurrent_agents": 10,
        "consensus_threshold": 0.7,
        "min_verification_quorum": 2,
        "rate_limit_requests_per_minute": 60,
        "credential_cache_ttl_seconds": 300,
        "circuit_breaker_failure_threshold": 5,
        "circuit_breaker_recovery_timeout": 60,
        "allow_http_agents": False,
        "require_ssrf_validation": True,
    }

    def __init__(self, server_context):
        super().__init__(server_context)
        # Configuration stored in server context
        if "gateway_config" not in self.ctx:
            self.ctx["gateway_config"] = dict(self.DEFAULT_CONFIG)
        if "gateway_config_updated_at" not in self.ctx:
            self.ctx["gateway_config_updated_at"] = datetime.now(timezone.utc).isoformat()

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        return path in (
            "/api/v1/gateway/config",
            "/api/v1/gateway/config/defaults",
        )

    @require_permission("gateway:configure")
    @rate_limit(requests_per_minute=30, limiter_name="gateway_config_read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET requests."""
        if not self.can_handle(path):
            return None

        # GET /api/v1/gateway/config/defaults
        if path == "/api/v1/gateway/config/defaults":
            return self._handle_get_defaults(handler)

        # GET /api/v1/gateway/config
        if path == "/api/v1/gateway/config":
            return self._handle_get_config(handler)

        return None

    @handle_errors("gateway config creation")
    @require_permission("gateway:admin")
    @rate_limit(requests_per_minute=5, limiter_name="gateway_config_write")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests."""
        if path != "/api/v1/gateway/config":
            return None

        return self._handle_update_config(handler)

    # =========================================================================
    # Handler Methods
    # =========================================================================

    @handle_errors("get gateway config")
    def _handle_get_config(self, handler: Any) -> HandlerResult:
        """Handle GET /api/v1/gateway/config."""
        config = self.ctx.get("gateway_config", dict(self.DEFAULT_CONFIG))
        updated_at = self.ctx.get(
            "gateway_config_updated_at",
            datetime.now(timezone.utc).isoformat(),
        )

        return json_response(
            {
                "config": config,
                "updated_at": updated_at,
            }
        )

    @handle_errors("get gateway config defaults")
    def _handle_get_defaults(self, handler: Any) -> HandlerResult:
        """Handle GET /api/v1/gateway/config/defaults."""
        return json_response(
            {
                "defaults": dict(self.DEFAULT_CONFIG),
            }
        )

    @handle_errors("update gateway config")
    @log_request("update gateway config")
    def _handle_update_config(self, handler: Any) -> HandlerResult:
        """Handle POST /api/v1/gateway/config."""
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        # Get current config
        current_config = self.ctx.get("gateway_config", dict(self.DEFAULT_CONFIG))

        # Track changes
        changes: list[str] = []
        new_config = dict(current_config)

        # Validate and apply updates
        for key, value in body.items():
            # Skip unknown keys
            if key not in CONFIG_VALIDATORS:
                logger.debug("Ignoring unknown config key: %s", key)
                continue

            # Validate the value
            validator = CONFIG_VALIDATORS[key]
            if not validator(value):
                error_msg = CONFIG_VALIDATION_MESSAGES.get(key, f"Invalid value for {key}")
                return error_response(error_msg, 400)

            # Track the change if value differs
            old_value = current_config.get(key)
            if old_value != value:
                changes.append(f"{key}: {old_value} -> {value}")
                new_config[key] = value

        # Update the config in context
        updated_at = datetime.now(timezone.utc).isoformat()
        self.ctx["gateway_config"] = new_config
        self.ctx["gateway_config_updated_at"] = updated_at

        # Log changes for audit
        if changes:
            logger.info("Gateway config updated: %s", ", ".join(changes))
        else:
            logger.debug("Gateway config POST with no changes")

        return json_response(
            {
                "config": new_config,
                "updated_at": updated_at,
                "changes": changes,
                "message": "Configuration updated successfully",
            }
        )


__all__ = ["GatewayConfigHandler"]
