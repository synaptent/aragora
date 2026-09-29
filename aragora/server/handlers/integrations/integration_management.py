"""
Integration Management HTTP Handlers for Aragora.

Provides REST API endpoints for managing platform integrations:
- List connected integrations for a workspace/tenant
- Disconnect integrations
- Get integration status and health
- Manage integration settings

Endpoints:
    GET  /api/v2/integrations                    - List all integrations
    GET  /api/v2/integrations/:type              - Get specific integration status
    DELETE /api/v2/integrations/:type            - Disconnect integration
    POST /api/v2/integrations/:type/test         - Test integration connectivity
    GET  /api/v2/integrations/stats              - Integration statistics

Supports Slack, Teams, Discord, and Email integrations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aragora.server.errors import safe_error_message
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    json_response,
)
from aragora.server.handlers.utils.rate_limit import rate_limit, RateLimiter, get_client_ip
from aragora.server.handlers.utils.tenant_validation import validate_tenant_access
from aragora.server.validation.query_params import safe_query_int
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.utils.lazy_stores import LazyStoreFactory

logger = logging.getLogger(__name__)


def _legacy_error_response(
    message: str,
    status: int,
    code: str | None = None,
    headers: dict[str, str] | None = None,
) -> HandlerResult:
    payload: dict[str, Any] = {"error": message}
    if code:
        payload["code"] = code
    return json_response(payload, status=status, headers=headers)


# Supported integration types
SUPPORTED_INTEGRATIONS = {"slack", "teams", "discord", "email"}

# Rate limiter for stats endpoint (30 requests per minute per user)
_stats_limiter = RateLimiter(requests_per_minute=30)


class IntegrationsHandler(BaseHandler):
    """
    HTTP handler for managing platform integrations.

    Provides REST API access to view, manage, and test integrations
    with external platforms like Slack, Teams, Discord, and Email.
    """

    ROUTES = [
        "/api/v2/integrations",
        "/api/v2/integrations/*",
    ]

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        self._slack_store_factory = LazyStoreFactory(
            store_name="slack_workspace_store",
            import_path="aragora.storage.slack_workspace_store",
            factory_name="get_slack_workspace_store",
            logger_context="IntegrationMgmt",
        )
        self._teams_store_factory = LazyStoreFactory(
            store_name="teams_workspace_store",
            import_path="aragora.storage.teams_workspace_store",
            factory_name="get_teams_workspace_store",
            logger_context="IntegrationMgmt",
        )
        self._slack_store = None  # Set by tests or lazy init
        self._teams_store = None  # Set by tests or lazy init

    def _get_slack_store(self):
        """Get Slack workspace store (lazy initialization)."""
        if self._slack_store is None:
            self._slack_store = self._slack_store_factory.get()
        return self._slack_store

    def _get_teams_store(self):
        """Get Teams workspace store (lazy initialization)."""
        if self._teams_store is None:
            self._teams_store = self._teams_store_factory.get()
        return self._teams_store

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if path.startswith("/api/v2/integrations"):
            return method in ("GET", "POST", "DELETE")
        return False

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Collapse optional trailing slashes on integration routes."""
        if path == "/api/v2/integrations/" or path.startswith("/api/v2/integrations/"):
            return path.rstrip("/") or path
        return path

    @rate_limit(requests_per_minute=60)
    async def handle(self, *args: Any, **kwargs: Any) -> HandlerResult | None:
        """Route request to appropriate handler method.

        Supports both (path, query_params, handler) and (method, path, ...) call signatures.
        """
        method = kwargs.pop("method", None)
        path = kwargs.pop("path", None)
        query_params = kwargs.pop("query_params", None)
        handler = kwargs.pop("handler", None)
        headers = kwargs.pop("headers", None)
        body = kwargs.pop("body", None)

        if args:
            first = args[0]
            http_methods = {"GET", "POST", "DELETE", "PATCH", "PUT"}
            if isinstance(first, str) and first.upper() in http_methods:
                method = first.upper()
                path = args[1] if len(args) > 1 else path
                if query_params is None and len(args) > 2 and isinstance(args[2], dict):
                    query_params = args[2]
                elif handler is None and len(args) > 2:
                    handler = args[2]
                if handler is None and len(args) > 3:
                    handler = args[3]
            else:
                path = first
                if query_params is None and len(args) > 1 and isinstance(args[1], dict):
                    query_params = args[1]
                if handler is None and len(args) > 2:
                    handler = args[2]

        if method is None:
            method = getattr(handler, "command", "GET") if handler else "GET"
        if path is None:
            return _legacy_error_response(
                "Invalid integration request path", 400, code="INVALID_PATH"
            )
        path = self._normalize_path(path)
        if query_params is None:
            query_params = {}

        # Require authentication for all integration management endpoints
        user, auth_err = self.require_auth_or_error(handler)
        if auth_err:
            return auth_err

        # Extract method, body, and headers from the request handler
        if body is None:
            body = (self.read_json_body(handler) or {}) if handler else {}
        if not isinstance(body, dict):
            return _legacy_error_response("Invalid request body", 400, code="INVALID_REQUEST_BODY")
        if headers is None:
            headers = dict(handler.headers) if handler and hasattr(handler, "headers") else {}

        # Extract tenant ID from auth context (header or query param)
        tenant_id = (headers.get("X-Tenant-ID") if headers else None) or query_params.get(
            "tenant_id"
        )

        # SECURITY: Validate user has access to requested tenant
        tenant_access_err = await validate_tenant_access(
            user=user,
            requested_tenant_id=tenant_id,
            endpoint=path,
            ip_address=get_client_ip(handler),
            allow_none=True,  # Allow None tenant_id (defaults to user's tenant)
        )
        if tenant_access_err:
            return tenant_access_err

        try:
            # Stats endpoint (stricter rate limit: 30/min)
            if path == "/api/v2/integrations/stats" and method == "GET":
                return await self._get_stats(tenant_id, handler)

            # List all integrations
            if path == "/api/v2/integrations" and method == "GET":
                return await self._list_integrations(tenant_id, query_params)

            # Integration-specific routes
            if path.startswith("/api/v2/integrations/"):
                parts = path.split("/")
                if len(parts) < 5:
                    return _legacy_error_response(
                        "Invalid integration path", 400, code="INVALID_PATH"
                    )

                integration_type = parts[4]

                if integration_type not in SUPPORTED_INTEGRATIONS:
                    return _legacy_error_response(
                        f"Unknown integration: {integration_type}. "
                        f"Supported: {', '.join(sorted(SUPPORTED_INTEGRATIONS))}",
                        400,
                        code="UNSUPPORTED_INTEGRATION",
                    )

                if len(parts) > 5:
                    subpath = parts[5]
                    # Health endpoint (GET)
                    if subpath == "health" and method == "GET":
                        workspace_id = query_params.get("workspace_id")
                        return await self._get_health(integration_type, workspace_id, tenant_id)

                    # Test endpoint (POST - legacy, calls health check)
                    if subpath == "test" and method == "POST":
                        workspace_id = body.get("workspace_id") or query_params.get("workspace_id")
                        return await self._test_integration(
                            integration_type, workspace_id, tenant_id
                        )

                    return _legacy_error_response(
                        "Invalid integration path", 400, code="INVALID_PATH"
                    )

                # Get specific integration
                if method == "GET":
                    workspace_id = query_params.get("workspace_id")
                    return await self._get_integration(integration_type, workspace_id, tenant_id)

                # Disconnect integration
                if method == "DELETE":
                    workspace_id = body.get("workspace_id") or query_params.get("workspace_id")
                    return await self._disconnect_integration(
                        integration_type, workspace_id, tenant_id
                    )

            return _legacy_error_response("Not found", 404, code="NOT_FOUND")

        except (KeyError, ValueError, TypeError, AttributeError, OSError, RuntimeError) as e:
            logger.exception("Error handling integration request: %s", e)
            return _legacy_error_response(
                f"Internal error: {safe_error_message(e, 'integration management')}",
                500,
                code="INTERNAL_ERROR",
            )

    @require_permission("integrations.read")
    async def _list_integrations(
        self, tenant_id: str | None, query_params: dict[str, str]
    ) -> HandlerResult:
        """
        List all integrations for a tenant.

        Query params:
            limit: Max results (default 20, max 100)
            offset: Pagination offset
            type: Filter by integration type
            status: Filter by status (active, inactive)
        """
        limit = safe_query_int(query_params, "limit", default=20, min_val=1, max_val=100)
        offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=10000)
        filter_type = query_params.get("type")
        filter_status = query_params.get("status")

        integrations: list[dict[str, Any]] = []

        # Get Slack integrations
        if not filter_type or filter_type == "slack":
            slack_store = self._get_slack_store()
            if tenant_id:
                slack_workspaces = slack_store.get_by_tenant(tenant_id)
            else:
                slack_workspaces = slack_store.list_active(limit=limit, offset=offset)

            for ws in slack_workspaces:
                if filter_status:
                    if filter_status == "active" and not ws.is_active:
                        continue
                    if filter_status == "inactive" and ws.is_active:
                        continue

                integrations.append(
                    {
                        "type": "slack",
                        "workspace_id": ws.workspace_id,
                        "workspace_name": ws.workspace_name,
                        "status": "active" if ws.is_active else "inactive",
                        "installed_at": ws.installed_at,
                        "installed_by": ws.installed_by,
                        "scopes": ws.scopes,
                        "has_refresh_token": bool(ws.refresh_token),
                        "token_expires_at": ws.token_expires_at,
                    }
                )

        # Get Teams integrations
        if not filter_type or filter_type == "teams":
            teams_store = self._get_teams_store()
            if tenant_id:
                teams_workspaces = teams_store.get_by_aragora_tenant(tenant_id)
            else:
                teams_workspaces = teams_store.list_active(limit=limit, offset=offset)

            for ws in teams_workspaces:
                if filter_status:
                    if filter_status == "active" and not ws.is_active:
                        continue
                    if filter_status == "inactive" and ws.is_active:
                        continue

                integrations.append(
                    {
                        "type": "teams",
                        "tenant_id": ws.tenant_id,
                        "tenant_name": ws.tenant_name,
                        "status": "active" if ws.is_active else "inactive",
                        "installed_at": ws.installed_at,
                        "installed_by": ws.installed_by,
                        "scopes": ws.scopes,
                        "has_refresh_token": bool(ws.refresh_token),
                        "token_expires_at": ws.token_expires_at,
                    }
                )

        # Apply pagination
        total = len(integrations)
        integrations = integrations[offset : offset + limit]

        return json_response(
            {
                "integrations": integrations,
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "total": total,
                    "has_more": offset + len(integrations) < total,
                },
            }
        )

    @require_permission("integrations.read")
    async def _get_integration(
        self,
        integration_type: str,
        workspace_id: str | None,
        tenant_id: str | None,
    ) -> HandlerResult:
        """Get specific integration details."""
        if integration_type == "slack":
            store = self._get_slack_store()

            if workspace_id:
                workspace = store.get(workspace_id)
                if not workspace:
                    return _legacy_error_response(
                        "Slack workspace not found", 404, code="SLACK_WORKSPACE_NOT_FOUND"
                    )

                return json_response(
                    {
                        "type": "slack",
                        "connected": True,
                        "workspace": workspace.to_dict(),
                        "health": await self._check_slack_health(workspace),
                    }
                )

            # List all for tenant
            workspaces = (
                store.get_by_tenant(tenant_id) if tenant_id else store.list_active(limit=10)
            )

            return json_response(
                {
                    "type": "slack",
                    "connected": len(workspaces) > 0,
                    "workspaces": [ws.to_dict() for ws in workspaces],
                    "count": len(workspaces),
                }
            )

        elif integration_type == "teams":
            store = self._get_teams_store()

            if workspace_id:
                workspace = store.get(workspace_id)
                if not workspace:
                    return _legacy_error_response(
                        "Teams tenant not found", 404, code="TEAMS_TENANT_NOT_FOUND"
                    )

                return json_response(
                    {
                        "type": "teams",
                        "connected": True,
                        "workspace": workspace.to_dict(),
                        "health": await self._check_teams_health(workspace),
                    }
                )

            # List all for tenant
            workspaces = (
                store.get_by_aragora_tenant(tenant_id) if tenant_id else store.list_active(limit=10)
            )

            return json_response(
                {
                    "type": "teams",
                    "connected": len(workspaces) > 0,
                    "workspaces": [ws.to_dict() for ws in workspaces],
                    "count": len(workspaces),
                }
            )

        elif integration_type == "discord":
            import os

            has_token = bool(os.environ.get("DISCORD_BOT_TOKEN"))
            return json_response(
                {
                    "type": "discord",
                    "connected": has_token,
                    "configured": has_token,
                    "note": "Discord uses bot token authentication",
                }
            )

        elif integration_type == "email":
            import os

            smtp_configured = bool(os.environ.get("SMTP_HOST"))
            return json_response(
                {
                    "type": "email",
                    "connected": smtp_configured,
                    "configured": smtp_configured,
                    "smtp_host": os.environ.get("SMTP_HOST", "not configured"),
                }
            )

        return _legacy_error_response(
            f"Unknown integration type: {integration_type}", 400, code="UNKNOWN_INTEGRATION_TYPE"
        )

    @require_permission("integrations.delete")
    async def _disconnect_integration(
        self,
        integration_type: str,
        workspace_id: str | None,
        tenant_id: str | None,
    ) -> HandlerResult:
        """Disconnect an integration."""
        if not workspace_id:
            return _legacy_error_response(
                "workspace_id is required", 400, code="MISSING_WORKSPACE_ID"
            )

        if integration_type == "slack":
            store = self._get_slack_store()
            workspace = store.get(workspace_id)

            if not workspace:
                return _legacy_error_response(
                    "Slack workspace not found", 404, code="SLACK_WORKSPACE_NOT_FOUND"
                )

            # Deactivate (soft delete)
            success = store.deactivate(workspace_id)

            if success:
                logger.info("Disconnected Slack workspace: %s", workspace_id)
                return json_response(
                    {
                        "disconnected": True,
                        "type": "slack",
                        "workspace_id": workspace_id,
                        "workspace_name": workspace.workspace_name,
                    }
                )

            return _legacy_error_response(
                "Failed to disconnect Slack workspace", 500, code="DISCONNECT_FAILED"
            )

        elif integration_type == "teams":
            store = self._get_teams_store()
            workspace = store.get(workspace_id)

            if not workspace:
                return _legacy_error_response(
                    "Teams tenant not found", 404, code="TEAMS_TENANT_NOT_FOUND"
                )

            success = store.deactivate(workspace_id)

            if success:
                logger.info("Disconnected Teams tenant: %s", workspace_id)
                return json_response(
                    {
                        "disconnected": True,
                        "type": "teams",
                        "tenant_id": workspace_id,
                        "tenant_name": workspace.tenant_name,
                    }
                )

            return _legacy_error_response(
                "Failed to disconnect Teams tenant", 500, code="DISCONNECT_FAILED"
            )

        return _legacy_error_response(
            f"Cannot disconnect {integration_type}: not supported",
            400,
            code="UNSUPPORTED_DISCONNECT",
        )

    @require_permission("integrations.read")
    async def _test_integration(
        self,
        integration_type: str,
        workspace_id: str | None,
        tenant_id: str | None,
    ) -> HandlerResult:
        """Test integration connectivity."""
        if integration_type == "slack":
            if not workspace_id:
                return _legacy_error_response(
                    "workspace_id is required for Slack test", 400, code="MISSING_WORKSPACE_ID"
                )

            store = self._get_slack_store()
            workspace = store.get(workspace_id)

            if not workspace:
                return _legacy_error_response(
                    "Slack workspace not found", 404, code="SLACK_WORKSPACE_NOT_FOUND"
                )

            health = await self._check_slack_health(workspace)
            return json_response(
                {
                    "type": "slack",
                    "workspace_id": workspace_id,
                    "test_result": health,
                    "tested_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        elif integration_type == "teams":
            if not workspace_id:
                return _legacy_error_response(
                    "workspace_id is required for Teams test", 400, code="MISSING_WORKSPACE_ID"
                )

            store = self._get_teams_store()
            workspace = store.get(workspace_id)

            if not workspace:
                return _legacy_error_response(
                    "Teams tenant not found", 404, code="TEAMS_TENANT_NOT_FOUND"
                )

            health = await self._check_teams_health(workspace)
            return json_response(
                {
                    "type": "teams",
                    "tenant_id": workspace_id,
                    "test_result": health,
                    "tested_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        elif integration_type == "discord":
            health = await self._check_discord_health()
            return json_response(
                {
                    "type": "discord",
                    "test_result": health,
                    "tested_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        elif integration_type == "email":
            health = await self._check_email_health()
            return json_response(
                {
                    "type": "email",
                    "test_result": health,
                    "tested_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        return _legacy_error_response(
            f"Cannot test {integration_type}", 400, code="UNSUPPORTED_TEST"
        )

    @require_permission("integrations.read")
    async def _get_health(
        self,
        integration_type: str,
        workspace_id: str | None,
        tenant_id: str | None,
    ) -> HandlerResult:
        """
        Get health status for an integration.

        Returns detailed health information including:
        - Connection status
        - Token validity
        - Last successful operation
        - Error details if unhealthy
        """
        if integration_type == "slack":
            if not workspace_id:
                # Return aggregate health for all Slack workspaces
                store = self._get_slack_store()
                workspaces = (
                    store.get_by_tenant(tenant_id) if tenant_id else store.list_active(limit=10)
                )

                if not workspaces:
                    return json_response(
                        {
                            "type": "slack",
                            "status": "not_configured",
                            "healthy": False,
                            "workspaces": [],
                        }
                    )

                workspace_health = []
                all_healthy = True
                for ws in workspaces:
                    health = await self._check_slack_health(ws)
                    is_healthy = health.get("status") == "healthy"
                    all_healthy = all_healthy and is_healthy
                    workspace_health.append(
                        {
                            "workspace_id": ws.workspace_id,
                            "workspace_name": ws.workspace_name,
                            **health,
                        }
                    )

                return json_response(
                    {
                        "type": "slack",
                        "status": "healthy" if all_healthy else "degraded",
                        "healthy": all_healthy,
                        "workspaces": workspace_health,
                    }
                )

            # Health for specific workspace
            store = self._get_slack_store()
            workspace = store.get(workspace_id)
            if not workspace:
                return _legacy_error_response(
                    "Slack workspace not found", 404, code="SLACK_WORKSPACE_NOT_FOUND"
                )

            health = await self._check_slack_health(workspace)
            return json_response(
                {
                    "type": "slack",
                    "workspace_id": workspace_id,
                    "workspace_name": workspace.workspace_name,
                    "healthy": health.get("status") == "healthy",
                    **health,
                }
            )

        elif integration_type == "teams":
            if not workspace_id:
                store = self._get_teams_store()
                workspaces = (
                    store.get_by_aragora_tenant(tenant_id)
                    if tenant_id
                    else store.list_active(limit=10)
                )

                if not workspaces:
                    return json_response(
                        {
                            "type": "teams",
                            "status": "not_configured",
                            "healthy": False,
                            "workspaces": [],
                        }
                    )

                workspace_health = []
                all_healthy = True
                for ws in workspaces:
                    health = await self._check_teams_health(ws)
                    is_healthy = health.get("status") == "healthy"
                    all_healthy = all_healthy and is_healthy
                    workspace_health.append(
                        {"tenant_id": ws.tenant_id, "tenant_name": ws.tenant_name, **health}
                    )

                return json_response(
                    {
                        "type": "teams",
                        "status": "healthy" if all_healthy else "degraded",
                        "healthy": all_healthy,
                        "workspaces": workspace_health,
                    }
                )

            store = self._get_teams_store()
            workspace = store.get(workspace_id)
            if not workspace:
                return _legacy_error_response(
                    "Teams tenant not found", 404, code="TEAMS_TENANT_NOT_FOUND"
                )

            health = await self._check_teams_health(workspace)
            return json_response(
                {
                    "type": "teams",
                    "tenant_id": workspace_id,
                    "tenant_name": workspace.tenant_name,
                    "healthy": health.get("status") == "healthy",
                    **health,
                }
            )

        elif integration_type == "discord":
            health = await self._check_discord_health()
            return json_response(
                {"type": "discord", "healthy": health.get("status") == "healthy", **health}
            )

        elif integration_type == "email":
            health = await self._check_email_health()
            return json_response(
                {"type": "email", "healthy": health.get("status") == "healthy", **health}
            )

        return _legacy_error_response(
            f"Unknown integration type: {integration_type}", 400, code="UNKNOWN_INTEGRATION_TYPE"
        )

    @require_permission("integrations.read")
    async def _get_stats(self, tenant_id: str | None, handler: Any = None) -> HandlerResult:
        """Get integration statistics.

        Rate limited to 30 requests per minute per user/tenant.
        """
        # Apply stricter rate limit for stats endpoint (30/min vs 60/min for other endpoints)
        rate_key = tenant_id if tenant_id else (get_client_ip(handler) if handler else "unknown")

        if not _stats_limiter.is_allowed(rate_key):
            remaining = _stats_limiter.get_remaining(rate_key)
            logger.warning("Rate limit exceeded for stats endpoint: %s", rate_key)
            headers = {
                "X-RateLimit-Limit": "30",
                "X-RateLimit-Remaining": str(remaining),
                "Retry-After": "60",
            }
            return _legacy_error_response(
                "Rate limit exceeded. Please try again later.",
                429,
                code="RATE_LIMIT_EXCEEDED",
                headers=headers,
            )

        slack_store = self._get_slack_store()
        teams_store = self._get_teams_store()

        slack_stats = slack_store.get_stats()
        teams_stats = teams_store.get_stats()

        return json_response(
            {
                "stats": {
                    "slack": slack_stats,
                    "teams": teams_stats,
                    "total_integrations": (
                        slack_stats.get("active_workspaces", 0)
                        + teams_stats.get("active_workspaces", 0)
                    ),
                },
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    async def _check_slack_health(self, workspace) -> dict[str, Any]:
        """Check Slack workspace health."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {workspace.access_token}"},
                )
                result = resp.json()

            if result.get("ok"):
                return {
                    "status": "healthy",
                    "team": result.get("team"),
                    "bot_id": result.get("bot_id"),
                }
            else:
                return {
                    "status": "unhealthy",
                    "error": result.get("error", "unknown"),
                }

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Slack health check failed: %s", e, exc_info=True)
            return {"status": "error", "error": "Health check failed"}

    async def _check_teams_health(self, workspace) -> dict[str, Any]:
        """Check Teams workspace health."""
        try:
            import httpx

            # Test Graph API access
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://graph.microsoft.com/v1.0/me",
                    headers={"Authorization": f"Bearer {workspace.access_token}"},
                )

            if resp.status_code == 401:
                return {"status": "token_expired", "error": "Token needs refresh"}

            if resp.status_code >= 400:
                return {"status": "unhealthy", "error": f"HTTP {resp.status_code}"}

            result = resp.json()
            return {
                "status": "healthy",
                "display_name": result.get("displayName"),
            }

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Teams health check failed: %s", e, exc_info=True)
            return {"status": "error", "error": "Health check failed"}

    async def _check_discord_health(self) -> dict[str, Any]:
        """Check Discord bot health."""
        import os

        bot_token = os.environ.get("DISCORD_BOT_TOKEN")
        if not bot_token:
            return {"status": "not_configured", "error": "No bot token"}

        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": f"Bot {bot_token}"},
                )
                result = resp.json()

            if resp.status_code >= 400:
                return {"status": "unhealthy", "error": f"HTTP {resp.status_code}"}

            return {
                "status": "healthy",
                "bot_name": result.get("username"),
                "bot_id": result.get("id"),
            }

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Discord health check failed: %s", e, exc_info=True)
            return {"status": "error", "error": "Health check failed"}

    async def _check_email_health(self) -> dict[str, Any]:
        """Check email/SMTP health."""
        import os
        import socket

        smtp_host = os.environ.get("SMTP_HOST")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))

        if not smtp_host:
            return {"status": "not_configured", "error": "No SMTP host"}

        try:
            # Test TCP connection to SMTP
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((smtp_host, smtp_port))
            sock.close()

            if result == 0:
                return {
                    "status": "healthy",
                    "smtp_host": smtp_host,
                    "smtp_port": smtp_port,
                }
            else:
                return {
                    "status": "unreachable",
                    "error": f"Cannot connect to {smtp_host}:{smtp_port}",
                }

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Email health check failed: %s", e, exc_info=True)
            return {"status": "error", "error": "Health check failed"}


# Handler factory function for registration
def create_integrations_handler(server_context: dict[str, Any]) -> IntegrationsHandler:
    """Factory function for handler registration."""
    return IntegrationsHandler(server_context)


# Alias for backwards compatibility with lazy import system
IntegrationManagementHandler = IntegrationsHandler
