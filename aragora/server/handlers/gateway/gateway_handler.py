"""
Gateway Handler - HTTP endpoints for device gateway management.

Stability: STABLE
Graduated from EXPERIMENTAL on 2026-02-02.

Provides API endpoints for:
- Device registration and management
- Channel listing and configuration
- Routing statistics and rules
- Message routing

Routes:
    GET    /api/v1/gateway/devices          - List registered devices
    POST   /api/v1/gateway/devices          - Register a device
    GET    /api/v1/gateway/devices/{id}     - Get device details
    DELETE /api/v1/gateway/devices/{id}     - Unregister a device
    POST   /api/v1/gateway/devices/{id}/heartbeat - Device heartbeat
    GET    /api/v1/gateway/channels         - List active channels
    GET    /api/v1/gateway/routing/stats    - Routing statistics
    GET    /api/v1/gateway/routing/rules    - List routing rules
    POST   /api/v1/gateway/messages/route   - Route a message
"""

from __future__ import annotations

import inspect
import logging
import threading
from typing import Any, cast
from collections.abc import Callable, Coroutine

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
from aragora.server.http_utils import run_async

# RBAC imports (fail-closed in production)
from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

AuthorizationContext: Any = None
try:
    from aragora.rbac import AuthorizationContext, check_permission  # type: ignore[no-redef]
    from aragora.billing.jwt_auth import extract_user_from_request

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False

# Gateway imports
DeviceRegistry: Any = None
get_canonical_gateway_stores: Any = None
try:
    from aragora.gateway import (  # type: ignore[no-redef]
        DeviceRegistry,
        DeviceNode,
        DeviceStatus,
        AgentRouter,
    )
    from aragora.stores import get_canonical_gateway_stores  # type: ignore[no-redef]

    GATEWAY_AVAILABLE = True
except ImportError:
    GATEWAY_AVAILABLE = False

logger = logging.getLogger(__name__)


# =============================================================================
# Circuit Breaker Configuration
# =============================================================================

# Circuit breaker for gateway operations
# Opens after 5 consecutive failures, recovers after 30 seconds
_gateway_circuit_breaker = CircuitBreaker(
    name="gateway_handler",
    failure_threshold=5,
    cooldown_seconds=30.0,
    half_open_success_threshold=2,
    half_open_max_calls=3,
)
_gateway_circuit_breaker_lock = threading.Lock()


def get_gateway_circuit_breaker() -> CircuitBreaker:
    """Get the global circuit breaker for gateway operations."""
    return _gateway_circuit_breaker


def get_gateway_circuit_breaker_status() -> dict[str, Any]:
    """Get current status of the gateway circuit breaker."""
    return _gateway_circuit_breaker.to_dict()


def reset_gateway_circuit_breaker() -> None:
    """Reset the global circuit breaker (for testing)."""
    with _gateway_circuit_breaker_lock:
        _gateway_circuit_breaker._single_failures = 0
        _gateway_circuit_breaker._single_open_at = 0.0
        _gateway_circuit_breaker._single_successes = 0
        _gateway_circuit_breaker._single_half_open_calls = 0


class GatewayHandler(BaseHandler):
    """
    HTTP request handler for gateway API endpoints.

    Provides REST API for managing devices, channels, and message routing
    through the local gateway.
    """

    ROUTES = [
        "/api/v1/gateway/devices",
        "/api/v1/gateway/devices/*",
        "/api/v1/gateway/channels",
        "/api/v1/gateway/routing",
        "/api/v1/gateway/routing/*",
        "/api/v1/gateway/routing/rules",
        "/api/v1/gateway/routing/stats",
        "/api/v1/gateway/messages",
        "/api/v1/gateway/messages/*",
        "/api/v1/gateway/messages/route",
    ]

    def __init__(self, server_context):
        super().__init__(server_context)
        self._device_registry: DeviceRegistry | None = None
        self._agent_router: AgentRouter | None = None
        self._gateway_stores = None

    def _get_gateway_stores(self) -> Any:
        if not GATEWAY_AVAILABLE or get_canonical_gateway_stores is None:
            return None
        if self._gateway_stores is None:
            self._gateway_stores = get_canonical_gateway_stores()
        return self._gateway_stores

    def _get_device_registry(self) -> DeviceRegistry | None:
        """Get or create device registry."""
        if not GATEWAY_AVAILABLE:
            return None
        if self._device_registry is None:
            stores = self._get_gateway_stores()
            store = stores.gateway_store() if stores else None
            self._device_registry = DeviceRegistry(store=store)
        return self._device_registry

    def _get_agent_router(self) -> AgentRouter | None:
        """Get or create agent router."""
        if not GATEWAY_AVAILABLE:
            return None
        if self._agent_router is None:
            stores = self._get_gateway_stores()
            store = stores.gateway_store() if stores else None
            self._agent_router = AgentRouter(store=store)
        return self._agent_router

    def _get_user_store(self) -> Any:
        """Get user store from context."""
        return self.ctx.get("user_store")

    def _get_auth_context(self, handler: Any) -> AuthorizationContext | None:
        """Build AuthorizationContext from request."""
        if not RBAC_AVAILABLE or AuthorizationContext is None:
            return None

        user_store = self._get_user_store()
        auth_ctx = extract_user_from_request(handler, user_store)

        if not auth_ctx.is_authenticated:
            return None

        user = user_store.get_user_by_id(auth_ctx.user_id) if user_store else None
        roles = set([user.role]) if user and user.role else set()

        return AuthorizationContext(
            user_id=auth_ctx.user_id,
            roles=roles,
            org_id=auth_ctx.org_id,
        )

    def _check_rbac_permission(self, handler: Any, permission_key: str) -> HandlerResult | None:
        """Check RBAC permission. Returns None if allowed, error response if denied."""
        if not RBAC_AVAILABLE:
            # SECURITY: Fail closed in production when RBAC module is unavailable
            if rbac_fail_closed():
                return error_response("Service unavailable: access control module not loaded", 503)
            return None

        rbac_ctx = self._get_auth_context(handler)
        if not rbac_ctx:
            return error_response("Not authenticated", 401)

        decision = check_permission(rbac_ctx, permission_key)
        if not decision.allowed:
            logger.warning("RBAC denied: user=%s permission=%s", rbac_ctx.user_id, permission_key)
            return error_response("Permission denied", 403)

        return None

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        return path.startswith("/api/v1/gateway/")

    @require_permission("gateway:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET requests."""
        if not self.can_handle(path):
            return None

        if not GATEWAY_AVAILABLE:
            return error_response("Gateway module not available", 503)

        # GET /api/v1/gateway/devices
        if path == "/api/v1/gateway/devices":
            return self._handle_list_devices(query_params, handler)

        # GET /api/v1/gateway/devices/{id}
        if path.startswith("/api/v1/gateway/devices/"):
            device_id = path.split("/")[-1]
            if device_id and device_id != "devices":
                return self._handle_get_device(device_id, handler)

        # GET /api/v1/gateway/channels
        if path == "/api/v1/gateway/channels":
            return self._handle_list_channels(query_params, handler)

        # GET /api/v1/gateway/routing/stats
        if path == "/api/v1/gateway/routing/stats":
            return self._handle_routing_stats(handler)

        # GET /api/v1/gateway/routing/rules
        if path == "/api/v1/gateway/routing/rules":
            return self._handle_list_rules(query_params, handler)

        return None

    @handle_errors("gateway creation")
    @require_permission("gateway:write")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests."""
        if not self.can_handle(path):
            return None

        if not GATEWAY_AVAILABLE:
            return error_response("Gateway module not available", 503)

        # POST /api/v1/gateway/devices
        if path == "/api/v1/gateway/devices":
            return self._handle_register_device(handler)

        # POST /api/v1/gateway/devices/{id}/heartbeat
        if "/heartbeat" in path:
            parts = path.strip("/").split("/")
            # parts = ["api", "v1", "gateway", "devices", device_id, "heartbeat"]
            if len(parts) >= 6 and parts[5] == "heartbeat":
                device_id = parts[4]
                return self._handle_heartbeat(device_id, handler)

        # POST /api/v1/gateway/messages/route
        if path == "/api/v1/gateway/messages/route":
            return self._handle_route_message(handler)

        return None

    @handle_errors("gateway deletion")
    @require_permission("gateway:delete")
    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle DELETE requests."""
        if not self.can_handle(path):
            return None

        if not GATEWAY_AVAILABLE:
            return error_response("Gateway module not available", 503)

        # DELETE /api/v1/gateway/devices/{id}
        if path.startswith("/api/v1/gateway/devices/"):
            device_id = path.split("/")[-1]
            if device_id and device_id != "devices":
                return self._handle_unregister_device(device_id, handler)

        return None

    # =========================================================================
    # Device Handlers
    # =========================================================================

    @rate_limit(requests_per_minute=60, limiter_name="gateway_list_devices")
    @handle_errors("list devices")
    def _handle_list_devices(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        """Handle GET /api/v1/gateway/devices."""
        # RBAC check
        if error := self._check_rbac_permission(handler, "gateway:devices:read"):
            return error

        registry = self._get_device_registry()
        if not registry:
            return error_response("Device registry not available", 503)

        # Parse filters
        status_str = query_params.get("status")
        device_type = query_params.get("type")

        status = None
        if status_str:
            try:
                status = DeviceStatus(status_str)
            except ValueError:
                pass

        devices = run_async(registry.list_devices(status=status, device_type=device_type))

        return json_response(
            {
                "devices": [
                    {
                        "device_id": d.device_id,
                        "name": d.name,
                        "device_type": d.device_type,
                        "capabilities": d.capabilities,
                        "status": d.status.value,
                        "paired_at": d.paired_at,
                        "last_seen": d.last_seen,
                    }
                    for d in devices
                ],
                "total": len(devices),
            }
        )

    @rate_limit(requests_per_minute=60, limiter_name="gateway_get_device")
    @handle_errors("get device")
    def _handle_get_device(self, device_id: str, handler: Any) -> HandlerResult:
        """Handle GET /api/v1/gateway/devices/{id}."""
        # RBAC check
        if error := self._check_rbac_permission(handler, "gateway:devices:read"):
            return error

        registry = self._get_device_registry()
        if not registry:
            return error_response("Device registry not available", 503)

        device = run_async(registry.get(device_id))
        if not device:
            return error_response(f"Device not found: {device_id}", 404)

        return json_response(
            {
                "device": {
                    "device_id": device.device_id,
                    "name": device.name,
                    "device_type": device.device_type,
                    "capabilities": device.capabilities,
                    "status": device.status.value,
                    "paired_at": device.paired_at,
                    "last_seen": device.last_seen,
                    "allowed_channels": device.allowed_channels,
                    "metadata": device.metadata,
                }
            }
        )

    @rate_limit(requests_per_minute=30, limiter_name="gateway_register")
    @handle_errors("register device")
    @log_request("register device")
    def _handle_register_device(self, handler: Any) -> HandlerResult:
        """Handle POST /api/v1/gateway/devices."""
        # RBAC check
        if error := self._check_rbac_permission(handler, "gateway:devices:create"):
            return error

        registry = self._get_device_registry()
        if not registry:
            return error_response("Device registry not available", 503)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        name = body.get("name")
        if not name:
            return error_response("name is required", 400)

        device = DeviceNode(
            device_id=body.get("device_id", ""),
            name=name,
            device_type=body.get("device_type", "unknown"),
            capabilities=body.get("capabilities", []),
            allowed_channels=body.get("allowed_channels", []),
            metadata=body.get("metadata", {}),
        )

        device_id = run_async(registry.register(device))

        logger.info("Registered device: %s (%s)", device_id, name)

        return json_response(
            {
                "device_id": device_id,
                "message": "Device registered successfully",
            },
            status=201,
        )

    @rate_limit(requests_per_minute=10, limiter_name="gateway_unregister")
    @handle_errors("unregister device")
    @log_request("unregister device")
    def _handle_unregister_device(self, device_id: str, handler: Any) -> HandlerResult:
        """Handle DELETE /api/v1/gateway/devices/{id}."""
        # RBAC check
        if error := self._check_rbac_permission(handler, "gateway:devices:delete"):
            return error

        registry = self._get_device_registry()
        if not registry:
            return error_response("Device registry not available", 503)

        success = run_async(registry.unregister(device_id))
        if not success:
            return error_response(f"Device not found: {device_id}", 404)

        logger.info("Unregistered device: %s", device_id)

        return json_response({"message": "Device unregistered successfully"})

    @rate_limit(requests_per_minute=120, limiter_name="gateway_heartbeat")
    @handle_errors("device heartbeat")
    def _handle_heartbeat(self, device_id: str, handler: Any) -> HandlerResult:
        """Handle POST /api/v1/gateway/devices/{id}/heartbeat."""
        # RBAC check
        if error := self._check_rbac_permission(handler, "gateway:devices:read"):
            return error

        registry = self._get_device_registry()
        if not registry:
            return error_response("Device registry not available", 503)

        success = run_async(registry.heartbeat(device_id))
        if not success:
            return error_response(f"Device not found: {device_id}", 404)

        return json_response({"status": "ok"})

    # =========================================================================
    # Channel Handlers
    # =========================================================================

    @rate_limit(requests_per_minute=60, limiter_name="gateway_list_channels")
    @handle_errors("list channels")
    def _handle_list_channels(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        """Handle GET /api/v1/gateway/channels."""
        # RBAC check
        if error := self._check_rbac_permission(handler, "gateway:channels:read"):
            return error

        # Return configured channels from context or defaults
        channels = [
            {"name": "slack", "status": "available"},
            {"name": "email", "status": "available"},
            {"name": "telegram", "status": "available"},
            {"name": "whatsapp", "status": "available"},
        ]

        return json_response(
            {
                "channels": channels,
                "total": len(channels),
            }
        )

    # =========================================================================
    # Routing Handlers
    # =========================================================================

    @rate_limit(requests_per_minute=60, limiter_name="gateway_routing_stats")
    @handle_errors("routing stats")
    def _handle_routing_stats(self, handler: Any) -> HandlerResult:
        """Handle GET /api/v1/gateway/routing/stats."""
        # RBAC check
        if error := self._check_rbac_permission(handler, "gateway:routing:read"):
            return error

        router = self._get_agent_router()
        if not router:
            return error_response("Agent router not available", 503)

        # Return basic stats
        return json_response(
            {
                "stats": {
                    "total_rules": 0,
                    "messages_routed": 0,
                    "routing_errors": 0,
                }
            }
        )

    @rate_limit(requests_per_minute=60, limiter_name="gateway_list_rules")
    @handle_errors("list rules")
    def _handle_list_rules(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        """Handle GET /api/v1/gateway/routing/rules."""
        # RBAC check
        if error := self._check_rbac_permission(handler, "gateway:routing:read"):
            return error

        router = self._get_agent_router()
        if not router:
            return error_response("Agent router not available", 503)

        rules_result: Any = []
        if hasattr(router, "list_rules"):
            maybe_result = router.list_rules()
            rules_result = (
                run_async(maybe_result) if inspect.isawaitable(maybe_result) else maybe_result
            )
        rules: list[Any] = list(rules_result) if rules_result else []

        return json_response(
            {
                "rules": [
                    {
                        "id": getattr(r, "id", str(i)),
                        "channel": getattr(r, "channel", ""),
                        "pattern": getattr(r, "pattern", ""),
                        "agent_id": getattr(r, "agent_id", ""),
                    }
                    for i, r in enumerate(rules)
                ],
                "total": len(rules),
            }
        )

    # =========================================================================
    # Message Routing
    # =========================================================================

    @rate_limit(requests_per_minute=60, limiter_name="gateway_route")
    @handle_errors("route message")
    def _handle_route_message(self, handler: Any) -> HandlerResult:
        """Handle POST /api/v1/gateway/messages/route."""
        # RBAC check
        if error := self._check_rbac_permission(handler, "gateway:messages:route"):
            return error

        router = self._get_agent_router()
        if not router:
            return error_response("Agent router not available", 503)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        channel = body.get("channel")
        content = body.get("content")

        if not channel:
            return error_response("channel is required", 400)
        if not content:
            return error_response("content is required", 400)

        # Route the message - cast route method to accept flexible kwargs
        # since the actual router implementation may vary
        route_method = cast(
            Callable[..., Coroutine[Any, Any, Any]],
            router.route,
        )
        result = run_async(route_method(channel=channel, content=content))

        return json_response(
            {
                "routed": True,
                "agent_id": getattr(result, "agent_id", None),
                "rule_id": getattr(result, "rule_id", None),
            }
        )


__all__ = [
    "GatewayHandler",
    "get_gateway_circuit_breaker",
    "get_gateway_circuit_breaker_status",
    "reset_gateway_circuit_breaker",
]
