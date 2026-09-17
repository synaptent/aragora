"""
Bindings endpoint handlers.

Endpoints:
- GET /api/bindings - List all message bindings
- GET /api/bindings/:provider - List bindings for a provider
- POST /api/bindings - Create a new binding
- PUT /api/bindings/:id - Update a binding
- DELETE /api/bindings/:id - Remove a binding
- POST /api/bindings/resolve - Resolve binding for a message
- GET /api/bindings/stats - Get router statistics
"""

from __future__ import annotations

__all__ = [
    "BindingsHandler",
]

import logging
from typing import Any

from aiohttp import web

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..openapi_decorator import api_endpoint, path_param, query_param
from aragora.rbac.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip
from ..utils import parse_json_body

logger = logging.getLogger(__name__)

# Rate limiter for bindings endpoints (60 requests per minute)
_bindings_limiter = RateLimiter(requests_per_minute=60)

# Lazy imports for bindings system
# Pre-declare with Any to avoid no-redef errors in except branch
get_binding_router: Any
BindingRouter: Any
BindingType: Any
MessageBinding: Any

try:
    from aragora.server.bindings import (
        BindingRouter as _BindingRouter,
        BindingType as _BindingType,
        MessageBinding as _MessageBinding,
        get_binding_router as _get_binding_router,
    )

    BindingRouter = _BindingRouter
    BindingType = _BindingType
    MessageBinding = _MessageBinding
    get_binding_router = _get_binding_router
    BINDINGS_AVAILABLE = True
except ImportError:
    BINDINGS_AVAILABLE = False
    get_binding_router = None
    BindingRouter = None
    BindingType = None
    MessageBinding = None


def _web_response_to_handler_result(response: web.Response) -> HandlerResult:
    body = response.body if response.body is not None else b""  # type: ignore[arg-type]
    content_type = response.content_type or "application/json"
    headers = dict(response.headers) if response.headers else {}
    return HandlerResult(
        status_code=response.status,
        content_type=content_type,
        body=body,  # type: ignore[arg-type]
        headers=headers,
    )


class BindingsHandler(BaseHandler):
    """Handler for message bindings management endpoints."""

    ROUTES: list[str] = [
        "/api/bindings",
        "/api/bindings/resolve",
        "/api/bindings/stats",
        "/api/bindings/*",  # Must be last due to wildcard
    ]

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        self._router: BindingRouter | None = None

    def _get_router(self) -> BindingRouter | None:
        """Get or create the binding router singleton."""
        if self._router is None and BINDINGS_AVAILABLE and get_binding_router:
            self._router = get_binding_router()
        return self._router

    @api_endpoint(
        path="/api/bindings",
        method="GET",
        summary="List all message bindings",
        tags=["Bindings"],
        operation_id="listBindings",
        description="Retrieve all registered message bindings or filter by provider.",
        parameters=[
            query_param(
                "provider",
                "Filter bindings by provider name",
                schema_type="string",
                required=False,
            ),
        ],
        responses={
            "200": {
                "description": "List of bindings",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "bindings": {
                                    "type": "array",
                                    "items": {"type": "object"},
                                },
                                "total": {"type": "integer"},
                            },
                        },
                    },
                },
            },
            "429": {"description": "Rate limit exceeded"},
            "503": {"description": "Bindings system not available"},
        },
        auth_required=True,
    )
    @handle_errors("bindings GET request")
    @require_permission("debates:read")
    async def handle_get(self, path: str, request: Any) -> HandlerResult:
        """Handle GET requests for bindings endpoints."""
        path = strip_version_prefix(path)

        if not BINDINGS_AVAILABLE:
            return error_response(
                "Bindings system not available",
                503,
                code="BINDINGS_UNAVAILABLE",
            )

        # Rate limit check
        client_ip = get_client_ip(request)
        if not _bindings_limiter.is_allowed(client_ip):
            return error_response(
                "Rate limit exceeded for bindings endpoints",
                429,
                code="RATE_LIMITED",
            )

        # GET /api/bindings - List all bindings
        if path == "/api/bindings":
            return await self._list_bindings(request)

        # GET /api/bindings/stats - Get router statistics
        if path == "/api/bindings/stats":
            return await self._get_stats(request)

        # GET /api/bindings/:provider - List bindings for provider
        parts = path.split("/")
        if len(parts) >= 4:
            provider = parts[3]
            return await self._list_bindings_by_provider(provider, request)

        return error_response(f"Unknown bindings endpoint: {path}", 404)

    @api_endpoint(
        path="/api/bindings",
        method="POST",
        summary="Create a new message binding",
        tags=["Bindings"],
        operation_id="createBinding",
        description="Register a new message binding to route messages from a provider/account to an agent.",
        request_body={
            "description": "Binding configuration",
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["provider", "account_id", "peer_pattern", "agent_binding"],
                        "properties": {
                            "provider": {
                                "type": "string",
                                "description": "Message provider (e.g., telegram, whatsapp)",
                            },
                            "account_id": {
                                "type": "string",
                                "description": "Provider account identifier",
                            },
                            "peer_pattern": {
                                "type": "string",
                                "description": "Pattern to match peer/chat IDs",
                            },
                            "agent_binding": {
                                "type": "string",
                                "description": "Agent or debate to route to",
                            },
                            "binding_type": {
                                "type": "string",
                                "enum": ["default", "direct", "broadcast"],
                                "default": "default",
                            },
                            "priority": {"type": "integer", "default": 0},
                            "name": {"type": "string", "description": "Optional binding name"},
                            "description": {
                                "type": "string",
                                "description": "Optional description",
                            },
                            "enabled": {"type": "boolean", "default": True},
                        },
                    },
                },
            },
        },
        responses={
            "201": {
                "description": "Binding created successfully",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "status": {"type": "string"},
                                "binding": {"type": "object"},
                            },
                        },
                    },
                },
            },
            "400": {"description": "Invalid request body"},
            "429": {"description": "Rate limit exceeded"},
            "503": {"description": "Bindings system not available"},
        },
        auth_required=True,
    )
    @handle_errors("bindings POST request")
    @require_permission("debates:write")
    async def handle_post(self, path: str, request: Any) -> HandlerResult | web.Response:
        """Handle POST requests for bindings endpoints."""
        path = strip_version_prefix(path)

        if not BINDINGS_AVAILABLE:
            return error_response(
                "Bindings system not available",
                503,
                code="BINDINGS_UNAVAILABLE",
            )

        # Rate limit check
        client_ip = get_client_ip(request)
        if not _bindings_limiter.is_allowed(client_ip):
            return error_response(
                "Rate limit exceeded for bindings endpoints",
                429,
                code="RATE_LIMITED",
            )

        # POST /api/bindings/resolve
        if path == "/api/bindings/resolve":
            return await self._resolve_binding(request)

        # POST /api/bindings - Create binding
        if path == "/api/bindings":
            return await self._create_binding(request)

        return error_response(f"Unknown bindings endpoint: {path}", 404)

    @api_endpoint(
        path="/api/bindings/{provider}/{account_id}/{peer_pattern}",
        method="DELETE",
        summary="Delete a message binding",
        tags=["Bindings"],
        operation_id="deleteBinding",
        description="Remove a message binding by provider, account, and peer pattern.",
        parameters=[
            path_param("provider", "Message provider name"),
            path_param("account_id", "Provider account identifier"),
            path_param("peer_pattern", "Peer pattern to match"),
        ],
        responses={
            "200": {
                "description": "Binding deleted",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "status": {"type": "string", "example": "deleted"},
                            },
                        },
                    },
                },
            },
            "404": {"description": "Binding not found"},
            "429": {"description": "Rate limit exceeded"},
            "503": {"description": "Bindings system not available"},
        },
        auth_required=True,
    )
    @handle_errors("bindings DELETE request")
    @require_permission("debates:delete")
    async def handle_delete(self, path: str, request: Any) -> HandlerResult:
        """Handle DELETE requests for bindings endpoints."""
        path = strip_version_prefix(path)

        if not BINDINGS_AVAILABLE:
            return error_response(
                "Bindings system not available",
                503,
                code="BINDINGS_UNAVAILABLE",
            )

        # Rate limit check
        client_ip = get_client_ip(request)
        if not _bindings_limiter.is_allowed(client_ip):
            return error_response(
                "Rate limit exceeded for bindings endpoints",
                429,
                code="RATE_LIMITED",
            )

        # DELETE /api/bindings/:provider/:account/:pattern
        return await self._delete_binding(path, request)

    @require_permission("bindings:read")
    async def _list_bindings(self, request: Any) -> HandlerResult:
        """List all registered bindings."""
        router = self._get_router()
        if not router:
            return error_response(
                "Binding router not available",
                503,
                code="ROUTER_UNAVAILABLE",
            )

        bindings = router.list_bindings()
        return json_response(
            {
                "bindings": [b.to_dict() for b in bindings],
                "total": len(bindings),
            }
        )

    @require_permission("bindings:read")
    async def _list_bindings_by_provider(self, provider: str, request: Any) -> HandlerResult:
        """List bindings for a specific provider."""
        router = self._get_router()
        if not router:
            return error_response(
                "Binding router not available",
                503,
                code="ROUTER_UNAVAILABLE",
            )

        bindings = router.list_bindings(provider=provider)
        return json_response(
            {
                "provider": provider,
                "bindings": [b.to_dict() for b in bindings],
                "total": len(bindings),
            }
        )

    @require_permission("bindings:read")
    async def _get_stats(self, request: Any) -> HandlerResult:
        """Get router statistics."""
        router = self._get_router()
        if not router:
            return error_response(
                "Binding router not available",
                503,
                code="ROUTER_UNAVAILABLE",
            )

        stats = router.get_stats()
        return json_response(stats)

    @require_permission("bindings:create")
    async def _create_binding(self, request: Any) -> HandlerResult | web.Response:
        """Create a new message binding."""
        router = self._get_router()
        if not router:
            return error_response(
                "Binding router not available",
                503,
                code="ROUTER_UNAVAILABLE",
            )

        # Parse request body
        body, err = await parse_json_body(request, context="create_binding")
        if err:
            if isinstance(err, web.Response):
                return _web_response_to_handler_result(err)
            return err

        # Validate required fields
        required = ["provider", "account_id", "peer_pattern", "agent_binding"]
        missing = [f for f in required if f not in body]
        if missing:
            return error_response(f"Missing required fields: {', '.join(missing)}", 400)

        # Create binding
        try:
            binding_type = BindingType(body.get("binding_type", "default"))
        except ValueError:
            return error_response(
                f"Invalid binding_type: {body.get('binding_type')}",
                400,
            )

        binding = MessageBinding(
            provider=body["provider"],
            account_id=body["account_id"],
            peer_pattern=body["peer_pattern"],
            agent_binding=body["agent_binding"],
            binding_type=binding_type,
            priority=body.get("priority", 0),
            time_window_start=body.get("time_window_start"),
            time_window_end=body.get("time_window_end"),
            allowed_users=set(body["allowed_users"]) if body.get("allowed_users") else None,
            blocked_users=set(body["blocked_users"]) if body.get("blocked_users") else None,
            config_overrides=body.get("config_overrides", {}),
            name=body.get("name"),
            description=body.get("description"),
            enabled=body.get("enabled", True),
        )

        router.add_binding(binding)

        logger.info(
            "Created binding: %s for %s/%s",
            binding.name or binding.peer_pattern,
            binding.provider,
            binding.account_id,
        )

        return json_response(
            {
                "status": "created",
                "binding": binding.to_dict(),
            },
            status=201,
        )

    @require_permission("bindings:read")
    async def _resolve_binding(self, request: Any) -> HandlerResult | web.Response:
        """Resolve which binding applies to a message."""
        router = self._get_router()
        if not router:
            return error_response(
                "Binding router not available",
                503,
                code="ROUTER_UNAVAILABLE",
            )

        # Parse request body
        body, err = await parse_json_body(request, context="resolve_binding")
        if err:
            if isinstance(err, web.Response):
                return _web_response_to_handler_result(err)
            return err

        # Validate required fields
        required = ["provider", "account_id", "peer_id"]
        missing = [f for f in required if f not in body]
        if missing:
            return error_response(f"Missing required fields: {', '.join(missing)}", 400)

        # Resolve binding
        resolution = router.resolve(
            provider=body["provider"],
            account_id=body["account_id"],
            peer_id=body["peer_id"],
            user_id=body.get("user_id"),
            hour=body.get("hour"),
        )

        return json_response(
            {
                "matched": resolution.matched,
                "agent_binding": resolution.agent_binding,
                "binding_type": resolution.binding_type.value if resolution.binding_type else None,
                "config_overrides": resolution.config_overrides,
                "match_reason": resolution.match_reason,
                "candidates_checked": resolution.candidates_checked,
                "binding": resolution.binding.to_dict() if resolution.binding else None,
            }
        )

    @require_permission("bindings:delete")
    async def _delete_binding(self, path: str, request: Any) -> HandlerResult:
        """Delete a message binding."""
        router = self._get_router()
        if not router:
            return error_response(
                "Binding router not available",
                503,
                code="ROUTER_UNAVAILABLE",
            )

        # Parse path: /api/bindings/:provider/:account/:pattern
        parts = path.split("/")
        if len(parts) < 6:
            return error_response(
                "Delete path must be /api/bindings/:provider/:account/:pattern",
                400,
            )

        provider = parts[3]
        account_id = parts[4]
        peer_pattern = "/".join(parts[5:])  # Pattern may contain /

        removed = router.remove_binding(provider, account_id, peer_pattern)
        if removed:
            logger.info("Removed binding: %s/%s/%s", provider, account_id, peer_pattern)
            return json_response({"status": "deleted"})
        else:
            return error_response(
                f"Binding not found: {provider}/{account_id}/{peer_pattern}",
                404,
                code="BINDING_NOT_FOUND",
            )
