"""
Unified OAuth Wizard Handler for SME Onboarding.

Provides a single API for discovering, configuring, and managing all platform
integrations through a unified wizard interface.

Endpoints:
- GET  /api/v2/integrations/wizard              - Get wizard configuration
- GET  /api/v2/integrations/wizard/providers    - List all available providers
- GET  /api/v2/integrations/wizard/status       - Get status of all integrations
- POST /api/v2/integrations/wizard/validate     - Validate configuration before connecting

This handler simplifies the onboarding experience for SMEs by providing:
1. Discovery of available integrations
2. Configuration validation
3. Pre-flight checks
4. Unified status overview
"""

from __future__ import annotations

import logging
import inspect
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
)
from aragora.server.handlers.secure import SecureHandler, UnauthorizedError
from aragora.rbac.decorators import PermissionDeniedError, RoleRequiredError
from aragora.server.handlers.utils.rate_limit import rate_limit

# RBAC Permissions for OAuth wizard operations
CONNECTOR_READ = "connector:read"
CONNECTOR_CREATE = "connector:create"
CONNECTOR_DELETE = "connector:delete"

logger = logging.getLogger(__name__)

# Provider configurations
PROVIDERS: dict[str, dict[str, Any]] = {
    "slack": {
        "name": "Slack",
        "description": "Connect Aragora to Slack workspaces for AI-powered debates in your channels",
        "category": "communication",
        "setup_time_minutes": 5,
        "features": [
            "Send debate results to channels",
            "Interactive slash commands",
            "Thread-based discussions",
            "Scheduled digests",
        ],
        "required_env_vars": ["SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"],
        "optional_env_vars": ["SLACK_REDIRECT_URI", "SLACK_SCOPES"],
        "oauth_scopes": [
            "channels:history",
            "chat:write",
            "commands",
            "users:read",
            "team:read",
            "channels:read",
        ],
        "install_url": "/api/integrations/slack/install",
        "docs_url": "https://docs.aragora.ai/integrations/slack",
    },
    "teams": {
        "name": "Microsoft Teams",
        "description": "Connect Aragora to Microsoft Teams for enterprise collaboration",
        "category": "communication",
        "setup_time_minutes": 10,
        "features": [
            "Send debate results to channels",
            "Adaptive Cards for rich content",
            "Tab integration",
            "Bot messaging",
        ],
        "required_env_vars": ["TEAMS_CLIENT_ID", "TEAMS_CLIENT_SECRET"],
        "optional_env_vars": ["TEAMS_REDIRECT_URI", "TEAMS_SCOPES"],
        "oauth_scopes": ["https://graph.microsoft.com/.default", "offline_access"],
        "install_url": "/api/integrations/teams/install",
        "docs_url": "https://docs.aragora.ai/integrations/teams",
    },
    "discord": {
        "name": "Discord",
        "description": "Connect Aragora to Discord servers for community engagement",
        "category": "communication",
        "setup_time_minutes": 5,
        "features": [
            "Bot commands",
            "Embed messages",
            "Server invites",
            "Role-based access",
        ],
        "required_env_vars": ["DISCORD_BOT_TOKEN"],
        "optional_env_vars": ["DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET"],
        "oauth_scopes": ["bot", "applications.commands"],
        "install_url": "/api/integrations/discord/install",
        "docs_url": "https://docs.aragora.ai/integrations/discord",
    },
    "email": {
        "name": "Email (SMTP)",
        "description": "Send debate results and notifications via email",
        "category": "communication",
        "setup_time_minutes": 3,
        "features": [
            "HTML and plain text emails",
            "Scheduled digests",
            "Team notifications",
            "Custom templates",
        ],
        "required_env_vars": ["SMTP_HOST"],
        "optional_env_vars": ["SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"],
        "oauth_scopes": [],
        "install_url": None,  # No OAuth, direct configuration
        "docs_url": "https://docs.aragora.ai/integrations/email",
    },
    "gmail": {
        "name": "Gmail",
        "description": "Connect to Gmail for email integration with OAuth",
        "category": "communication",
        "setup_time_minutes": 5,
        "features": [
            "Send emails via Gmail",
            "Read inbox for triggers",
            "OAuth authentication",
            "No SMTP configuration needed",
        ],
        "required_env_vars": ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"],
        "optional_env_vars": ["GOOGLE_OAUTH_REDIRECT_URI"],
        "oauth_scopes": [
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
        ],
        "install_url": "/api/integrations/gmail/install",
        "docs_url": "https://docs.aragora.ai/integrations/gmail",
    },
    "github": {
        "name": "GitHub",
        "description": "Connect to GitHub for code review debates and PR automation",
        "category": "development",
        "setup_time_minutes": 5,
        "features": [
            "PR review debates",
            "Issue triage",
            "Code analysis",
            "Automated comments",
        ],
        # Webhook delivery is the required live integration surface today.
        # API credentials unlock deeper GitHub automation but are optional.
        "required_env_vars": ["GITHUB_WEBHOOK_SECRET"],
        "optional_env_vars": ["GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_TOKEN"],
        "oauth_scopes": ["repo", "read:org", "write:discussion"],
        "install_url": "/api/integrations/github/install",
        "docs_url": "https://docs.aragora.ai/integrations/github",
    },
}

PROVIDER_ENV_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "github": {
        "GITHUB_APP_PRIVATE_KEY": ("GITHUB_PRIVATE_KEY",),
    }
}


class OAuthWizardHandler(SecureHandler):
    """
    Unified OAuth wizard handler for SME onboarding.

    Provides a single API for discovering and configuring all integrations.

    RBAC Protection:
    - GET endpoints: Requires connector:read permission
    - POST validate/test: Requires connector:create permission
    - POST disconnect: Requires connector:delete permission
    """

    RESOURCE_TYPE = "connector"

    ROUTES = [
        "/api/v2/integrations/wizard",
        "/api/v2/integrations/wizard/*",
    ]

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        return path.startswith("/api/v2/integrations/wizard")

    @rate_limit(requests_per_minute=60)
    async def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route request to appropriate handler method.

        RBAC:
        - GET endpoints: connector:read
        - POST validate/test: connector:create
        - POST disconnect: connector:delete
        """
        method = getattr(handler, "command", "GET") if handler else "GET"
        query_params = query_params or {}
        body: dict[str, Any] = {}
        if handler is not None and method in {"POST", "PUT", "PATCH"}:
            body = self.read_json_body(handler) or {}

        # All wizard endpoints require authentication
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
        except (UnauthorizedError, PermissionDeniedError, ValueError, RuntimeError) as e:
            logger.debug("OAuth wizard auth failed: %s", e)
            return error_response("Authentication required", 401)

        try:
            # Determine required permission based on method and path
            required_permission = CONNECTOR_READ  # Default for GET
            if method == "POST":
                if "disconnect" in path:
                    required_permission = CONNECTOR_DELETE
                else:
                    required_permission = CONNECTOR_CREATE

            # Check permission
            try:
                self.check_permission(auth_context, required_permission)
            except (PermissionDeniedError, RoleRequiredError):
                return error_response("Permission denied", 403)

            # Main wizard endpoint
            if path == "/api/v2/integrations/wizard" and method == "GET":
                return await self._get_wizard_config(query_params)

            # List providers
            if path == "/api/v2/integrations/wizard/providers" and method == "GET":
                return await self._list_providers(query_params)

            # Get overall status
            if path == "/api/v2/integrations/wizard/status" and method == "GET":
                return await self._get_status(query_params)

            # Validate configuration
            if path == "/api/v2/integrations/wizard/validate" and method == "POST":
                return await self._validate_config(body)

            # Provider-specific routes: /wizard/{provider}/{action}
            parts = path.split("/")
            if len(parts) >= 6 and parts[4] == "wizard":
                provider_id = parts[5]

                # Test connection
                if len(parts) == 7 and parts[6] == "test" and method == "POST":
                    return await self._test_connection(provider_id)

                # List workspaces/tenants
                if len(parts) == 7 and parts[6] == "workspaces" and method == "GET":
                    return await self._list_workspaces(provider_id)

                # Disconnect
                if len(parts) == 7 and parts[6] == "disconnect" and method == "POST":
                    return await self._disconnect_provider(provider_id, body, auth_context)

            return error_response("Not found", 404)

        except (ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
            logger.exception("Error in OAuth wizard handler: %s", e)
            return error_response("Internal server error", 500)

    async def _get_wizard_config(self, query_params: dict[str, str]) -> HandlerResult:
        """
        Get the complete wizard configuration.

        Returns all provider information, configuration status, and next steps.
        """
        providers_status: list[dict[str, Any]] = []

        for provider_id, provider in PROVIDERS.items():
            status = self._check_provider_config(provider_id, provider)
            providers_status.append(
                {
                    "id": provider_id,
                    **provider,
                    "status": status,
                }
            )

        # Sort by category and configuration status
        providers_status.sort(key=lambda p: (p["category"], not p["status"]["configured"]))

        # Calculate overall readiness
        configured_count = sum(1 for p in providers_status if p["status"]["configured"])
        total_count = len(providers_status)

        return json_response(
            {
                "wizard": {
                    "version": "1.0",
                    "providers": providers_status,
                    "summary": {
                        "total_providers": total_count,
                        "configured": configured_count,
                        "ready_to_use": sum(
                            1
                            for p in providers_status
                            if p["status"]["configured"] and not p["status"]["errors"]
                        ),
                    },
                    "recommended_order": [
                        "slack",  # Most common for SMEs
                        "teams",  # Enterprise alternative
                        "email",  # Easiest to configure
                        "github",  # For dev teams
                        "discord",  # For communities
                        "gmail",  # Alternative email
                    ],
                },
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    async def _list_providers(self, query_params: dict[str, str]) -> HandlerResult:
        """
        List all available providers.

        Query params:
            category: Filter by category (communication, development)
            configured: Filter by configuration status (true, false)
        """
        filter_category = query_params.get("category")
        filter_configured = query_params.get("configured")

        providers_list = []

        for provider_id, provider in PROVIDERS.items():
            # Apply category filter
            if filter_category and provider["category"] != filter_category:
                continue

            status = self._check_provider_config(provider_id, provider)

            # Apply configured filter
            if filter_configured is not None:
                is_configured = filter_configured.lower() == "true"
                if status["configured"] != is_configured:
                    continue

            providers_list.append(
                {
                    "id": provider_id,
                    "name": provider["name"],
                    "description": provider["description"],
                    "category": provider["category"],
                    "setup_time_minutes": provider["setup_time_minutes"],
                    "features": provider["features"],
                    "configured": status["configured"],
                    "install_url": provider["install_url"],
                    "docs_url": provider["docs_url"],
                }
            )

        return json_response(
            {
                "providers": providers_list,
                "total": len(providers_list),
            }
        )

    async def _get_status(self, query_params: dict[str, str]) -> HandlerResult:
        """
        Get detailed status of all integrations.

        Includes configuration status, health checks, and connection details.
        """
        statuses: list[dict[str, Any]] = []

        for provider_id, provider in PROVIDERS.items():
            config_status = self._check_provider_config(provider_id, provider)

            # Get connection status if configured
            connection_status = None
            if config_status["configured"]:
                connection_status = await self._check_connection(provider_id)

            statuses.append(
                {
                    "provider_id": provider_id,
                    "name": provider["name"],
                    "category": provider["category"],
                    "configuration": config_status,
                    "connection": connection_status,
                }
            )

        # Summary
        configured = sum(1 for s in statuses if s["configuration"]["configured"])
        connected = sum(
            1 for s in statuses if s["connection"] and s["connection"].get("status") == "connected"
        )

        return json_response(
            {
                "statuses": statuses,
                "summary": {
                    "total": len(statuses),
                    "configured": configured,
                    "connected": connected,
                    "needs_attention": sum(
                        1
                        for s in statuses
                        if s["configuration"]["errors"]
                        or (s["connection"] and s["connection"].get("status") == "error")
                    ),
                },
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    async def _validate_config(self, body: dict[str, Any]) -> HandlerResult:
        """
        Validate configuration for a provider before connecting.

        Body:
            provider: Provider ID to validate
            config: Optional configuration values to validate
        """
        provider_id = body.get("provider")
        config = body.get("config", {})

        if not provider_id:
            return error_response("Provider ID is required", 400)

        if provider_id not in PROVIDERS:
            return error_response(
                f"Unknown provider: {provider_id}. Available: {', '.join(PROVIDERS.keys())}",
                400,
            )

        provider = PROVIDERS[provider_id]
        validation_results: dict[str, Any] = {
            "provider": provider_id,
            "valid": True,
            "checks": [],
        }

        # Check required environment variables
        for env_var in provider["required_env_vars"]:
            value, resolved_from = self._resolve_provider_env_value(provider_id, env_var, config)
            check = {
                "name": env_var,
                "type": "env_var",
                "required": True,
                "present": bool(value),
            }
            if resolved_from and resolved_from != env_var:
                check["resolved_from"] = resolved_from
            if not value:
                check["error"] = f"Missing required environment variable: {env_var}"
                validation_results["valid"] = False
            validation_results["checks"].append(check)

        # Check optional environment variables
        for env_var in provider["optional_env_vars"]:
            value, resolved_from = self._resolve_provider_env_value(provider_id, env_var, config)
            check = {
                "name": env_var,
                "type": "env_var",
                "required": False,
                "present": bool(value),
            }
            if resolved_from and resolved_from != env_var:
                check["resolved_from"] = resolved_from
            validation_results["checks"].append(check)

        # Add recommendations
        validation_results["recommendations"] = []
        if validation_results["valid"]:
            validation_results["recommendations"].append(
                f"Configuration looks good! Visit {provider['install_url']} to complete setup."
            )
        else:
            missing = [
                c["name"]
                for c in validation_results["checks"]
                if c["required"] and not c["present"]
            ]
            validation_results["recommendations"].append(
                f"Set the following environment variables: {', '.join(missing)}"
            )
            validation_results["recommendations"].append(
                f"See {provider['docs_url']} for detailed setup instructions."
            )

        return json_response(validation_results)

    def _check_provider_config(self, provider_id: str, provider: dict[str, Any]) -> dict[str, Any]:
        """Check if a provider is properly configured."""
        errors: list[str] = []
        warnings: list[str] = []

        # Check required env vars
        missing_required = []
        for env_var in provider["required_env_vars"]:
            value, _ = self._resolve_provider_env_value(provider_id, env_var)
            if not value:
                missing_required.append(env_var)

        if missing_required:
            errors.append(f"Missing required: {', '.join(missing_required)}")

        # Check optional env vars
        missing_optional = []
        for env_var in provider["optional_env_vars"]:
            value, _ = self._resolve_provider_env_value(provider_id, env_var)
            if not value:
                missing_optional.append(env_var)

        if missing_optional:
            warnings.append(f"Optional not set: {', '.join(missing_optional)}")

        return {
            "configured": len(missing_required) == 0,
            "errors": errors,
            "warnings": warnings,
            "required_vars_present": len(provider["required_env_vars"]) - len(missing_required),
            "required_vars_total": len(provider["required_env_vars"]),
        }

    async def _check_connection(self, provider_id: str) -> dict[str, Any] | None:
        """Check the connection status for a configured provider."""
        try:
            if provider_id == "slack":
                return await self._check_slack_connection()
            elif provider_id == "teams":
                return await self._check_teams_connection()
            elif provider_id == "discord":
                return await self._check_discord_connection()
            elif provider_id == "github":
                return await self._check_github_connection()
            elif provider_id == "gmail":
                return await self._check_gmail_connection()
            elif provider_id == "email":
                return await self._check_email_connection()
            else:
                return {"status": "unchecked", "reason": "No health check available"}
        except (ImportError, ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.warning("Connection check failed for provider: %s", e)
            return {"status": "error", "error": "Connection check failed"}

    async def _maybe_await(self, value: Any) -> Any:
        """Await a value when it is awaitable, otherwise return it."""
        if inspect.isawaitable(value):
            try:
                return await value
            except TypeError:
                return value
        return value

    def _record_value(self, record: Any, *field_names: str, default: Any = None) -> Any:
        """Return the first matching field from a dict-like or attribute-based record."""
        if isinstance(record, dict):
            for field_name in field_names:
                if field_name in record:
                    return record[field_name]
            return default

        for field_name in field_names:
            if hasattr(record, field_name):
                return getattr(record, field_name)
        return default

    def _provider_env_candidates(self, provider_id: str, env_var: str) -> tuple[str, ...]:
        """Return the preferred env var name followed by any supported aliases."""
        aliases = PROVIDER_ENV_ALIASES.get(provider_id, {}).get(env_var, ())
        return (env_var, *aliases)

    def _resolve_provider_env_value(
        self,
        provider_id: str,
        env_var: str,
        config: dict[str, Any] | None = None,
    ) -> tuple[str | None, str | None]:
        """Resolve a provider value from config/env, honoring provider-specific aliases."""
        config = config or {}
        for candidate in self._provider_env_candidates(provider_id, env_var):
            value = config.get(candidate) or os.environ.get(candidate)
            if value:
                return value, candidate
        return None, None

    @staticmethod
    def _looks_like_private_key(value: str) -> bool:
        """Cheap PEM-format sanity check for GitHub App keys."""
        return "BEGIN" in value and "PRIVATE KEY" in value and "END" in value

    def _normalize_mock_side_effect(self, func: Any) -> None:
        """Ensure mock side_effect lists behave as iterators for AsyncMock."""
        side_effect = getattr(func, "side_effect", None)
        if isinstance(side_effect, list):
            func.side_effect = iter(side_effect)

    async def _check_slack_connection(self) -> dict[str, Any]:
        """Check Slack connection status."""
        try:
            from aragora.storage.slack_workspace_store import get_slack_workspace_store

            store = await self._maybe_await(get_slack_workspace_store())
            self._normalize_mock_side_effect(store.list_active)
            workspaces = await self._maybe_await(store.list_active(limit=1))
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            RuntimeError,
            AttributeError,
        ) as e:
            logger.warning("Slack connection check failed: %s", e)
            return {"status": "error", "error": "Slack connection check failed"}

        if workspaces:
            try:
                self._normalize_mock_side_effect(store.list_active)
                count = await self._maybe_await(store.list_active(limit=100))
                total = len(count)
            except (TypeError, AttributeError, RuntimeError):
                total = len(workspaces)
            return {
                "status": "connected",
                "workspaces": total,
            }

        return {"status": "not_connected", "reason": "No active workspaces"}

    async def _check_teams_connection(self) -> dict[str, Any]:
        """Check Teams connection status."""
        try:
            from aragora.storage.teams_tenant_store import get_teams_tenant_store

            store = await self._maybe_await(get_teams_tenant_store())
            self._normalize_mock_side_effect(store.list_active)
            workspaces = await self._maybe_await(store.list_active(limit=1))
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            RuntimeError,
            AttributeError,
        ) as e:
            logger.warning("Teams connection check failed: %s", e)
            return {"status": "error", "error": "Teams connection check failed"}

        if workspaces:
            try:
                self._normalize_mock_side_effect(store.list_active)
                count = await self._maybe_await(store.list_active(limit=100))
                total = len(count)
            except (TypeError, AttributeError, RuntimeError):
                total = len(workspaces)
            return {
                "status": "connected",
                "tenants": total,
            }

        return {"status": "not_connected", "reason": "No active tenants"}

    async def _check_discord_connection(self) -> dict[str, Any]:
        """Check Discord connection status."""
        bot_token = os.environ.get("DISCORD_BOT_TOKEN")
        if not bot_token:
            return {"status": "not_configured"}

        return {"status": "configured", "note": "Bot token present"}

    async def _check_github_connection(self) -> dict[str, Any]:
        """Check GitHub integration readiness against the live webhook/runtime contract."""
        webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
        if not webhook_secret:
            return {"status": "not_configured", "reason": "Missing GITHUB_WEBHOOK_SECRET"}

        github_token = os.environ.get("GITHUB_TOKEN")
        app_id = os.environ.get("GITHUB_APP_ID")
        private_key, key_source = self._resolve_provider_env_value(
            "github", "GITHUB_APP_PRIVATE_KEY"
        )

        base_status: dict[str, Any] = {
            "webhook_endpoint": "/api/v1/webhooks/github",
            "webhook_secret_configured": True,
        }

        if github_token:
            return {
                **base_status,
                "status": "connected",
                "auth_mode": "personal_token",
            }

        if app_id and private_key:
            if not self._looks_like_private_key(private_key):
                return {
                    **base_status,
                    "status": "error",
                    "error": "GitHub App private key is not PEM formatted",
                }
            return {
                **base_status,
                "status": "connected",
                "auth_mode": "github_app",
                "app_id": app_id,
                "private_key_source": key_source or "GITHUB_APP_PRIVATE_KEY",
            }

        if app_id or private_key:
            missing = []
            if not app_id:
                missing.append("GITHUB_APP_ID")
            if not private_key:
                missing.append("GITHUB_APP_PRIVATE_KEY")
            return {
                **base_status,
                "status": "degraded",
                "auth_mode": "webhook_only",
                "reason": "GitHub App API access is only partially configured",
                "missing": missing,
            }

        return {
            **base_status,
            "status": "configured",
            "auth_mode": "webhook_only",
            "note": "Webhook delivery is configured; API credentials are optional.",
        }

    async def _check_email_connection(self) -> dict[str, Any]:
        """Check email/SMTP connection status."""
        import socket

        smtp_host = os.environ.get("SMTP_HOST")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))

        if not smtp_host:
            return {"status": "not_configured"}

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((smtp_host, smtp_port))
            sock.close()

            if result == 0:
                return {"status": "connected", "smtp_host": smtp_host, "smtp_port": smtp_port}
            else:
                return {"status": "unreachable", "smtp_host": smtp_host, "smtp_port": smtp_port}
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Email connection check failed: %s", e)
            return {"status": "error", "error": "SMTP connection check failed"}

    async def _check_gmail_connection(self) -> dict[str, Any]:
        """Check Gmail connection status from the persisted token store."""
        from aragora.storage.gmail_token_store import get_gmail_token_store

        store = get_gmail_token_store()
        states = await self._maybe_await(store.list_all())
        if not states:
            return {"status": "not_connected", "reason": "No Gmail accounts connected"}

        connected_states = [
            state
            for state in states
            if self._record_value(state, "refresh_token")
            or self._record_value(state, "access_token")
        ]
        if not connected_states:
            return {"status": "not_connected", "reason": "No active Gmail tokens available"}

        primary = connected_states[0]
        return {
            "status": "connected",
            "accounts": len(connected_states),
            "email": self._record_value(primary, "email_address"),
            "user_id": self._record_value(primary, "user_id"),
        }

    async def _test_connection(self, provider_id: str) -> HandlerResult:
        """
        Test connection to a provider with an actual API call.

        POST /api/v2/integrations/wizard/{provider}/test
        """
        if provider_id not in PROVIDERS:
            return error_response(f"Unknown provider: {provider_id}", 404)

        try:
            if provider_id == "slack":
                result = await self._test_slack_api()
            elif provider_id == "teams":
                result = await self._test_teams_api()
            elif provider_id == "discord":
                result = await self._test_discord_api()
            elif provider_id == "github":
                result = await self._test_github_api()
            elif provider_id == "gmail":
                result = await self._test_gmail_api()
            elif provider_id == "email":
                result = await self._test_email_connection()
            else:
                result = {"success": False, "error": f"Test not implemented for {provider_id}"}

            return json_response(
                {
                    "provider": provider_id,
                    "test_result": result,
                    "tested_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except (ImportError, ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.exception("Connection test failed for %s: %s", provider_id, e)
            return json_response(
                {
                    "provider": provider_id,
                    "test_result": {"success": False, "error": "Connection test failed"},
                    "tested_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    async def _test_slack_api(self) -> dict[str, Any]:
        """Test Slack API connectivity with auth.test call."""
        try:
            from aragora.storage.slack_workspace_store import get_slack_workspace_store

            store = get_slack_workspace_store()
            workspaces = store.list_active(limit=1)
            if not workspaces:
                return {"success": False, "error": "No active workspaces configured"}

            workspace = workspaces[0]
            token = self._record_value(workspace, "access_token")
            if not token:
                return {"success": False, "error": "No access token available"}

            from aragora.server.http_client_pool import get_http_pool

            pool = get_http_pool()
            async with pool.get_session("slack") as client:
                response = await client.post(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                )
                data = response.json()
                if data.get("ok"):
                    return {
                        "success": True,
                        "team": data.get("team"),
                        "user": data.get("user"),
                        "team_id": data.get("team_id"),
                    }
                return {"success": False, "error": data.get("error", "Unknown")}
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            RuntimeError,
        ) as e:
            logger.warning("Slack API test failed: %s", e)
            return {"success": False, "error": "Slack API test failed"}

    async def _test_teams_api(self) -> dict[str, Any]:
        """Test Teams API connectivity with Graph API call."""
        try:
            from aragora.storage.teams_tenant_store import get_teams_tenant_store

            store = get_teams_tenant_store()
            tenants = store.list_active(limit=1)
            if not tenants:
                return {"success": False, "error": "No active tenants configured"}

            tenant = tenants[0]
            token = self._record_value(tenant, "access_token")
            if not token:
                return {"success": False, "error": "No access token available"}

            from aragora.server.http_client_pool import get_http_pool

            pool = get_http_pool()
            async with pool.get_session("teams") as client:
                response = await client.get(
                    "https://graph.microsoft.com/v1.0/me",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                )
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "display_name": data.get("displayName"),
                    }
                elif response.status_code == 401:
                    return {"success": False, "error": "Token expired"}
                return {"success": False, "error": f"API returned {response.status_code}"}
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            RuntimeError,
        ) as e:
            logger.warning("Teams API test failed: %s", e)
            return {"success": False, "error": "Teams API test failed"}

    async def _test_discord_api(self) -> dict[str, Any]:
        """Test Discord API connectivity."""
        bot_token = os.environ.get("DISCORD_BOT_TOKEN")
        if not bot_token:
            return {"success": False, "error": "DISCORD_BOT_TOKEN not configured"}

        try:
            from aragora.server.http_client_pool import get_http_pool

            pool = get_http_pool()
            async with pool.get_session("discord") as client:
                response = await client.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": f"Bot {bot_token}"},
                    timeout=10,
                )
                if response.status_code == 200:
                    data = response.json()
                    return {"success": True, "bot_name": data.get("username")}
                return {"success": False, "error": f"API returned {response.status_code}"}
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            RuntimeError,
        ) as e:
            logger.warning("Discord API test failed: %s", e)
            return {"success": False, "error": "Discord API test failed"}

    async def _test_email_connection(self) -> dict[str, Any]:
        """Test SMTP connectivity using the same low-level socket check as status."""
        status = await self._check_email_connection()
        state = status.get("status")
        if state == "connected":
            return {
                "success": True,
                "smtp_host": status.get("smtp_host"),
                "smtp_port": status.get("smtp_port"),
            }
        if state == "not_configured":
            return {"success": False, "error": "SMTP is not configured"}
        if state == "unreachable":
            return {
                "success": False,
                "error": "SMTP host is unreachable",
                "smtp_host": status.get("smtp_host"),
                "smtp_port": status.get("smtp_port"),
            }
        return {"success": False, "error": status.get("error", "SMTP connection check failed")}

    async def _test_github_api(self) -> dict[str, Any]:
        """Test GitHub integration readiness without requiring a live outbound API call."""
        status = await self._check_github_connection()
        state = status.get("status")
        if state in {"not_configured", "degraded", "error"}:
            return {
                "success": False,
                "error": status.get("error")
                or status.get("reason", "GitHub integration not ready"),
                "auth_mode": status.get("auth_mode"),
            }

        return {
            "success": True,
            "auth_mode": status.get("auth_mode", "webhook_only"),
            "webhook_endpoint": status.get("webhook_endpoint"),
        }

    async def _test_gmail_api(self) -> dict[str, Any]:
        """Test Gmail connectivity using the first persisted Gmail account."""
        from aragora.connectors.enterprise.communication.gmail import GmailConnector
        from aragora.storage.gmail_token_store import get_gmail_token_store

        store = get_gmail_token_store()
        states = await self._maybe_await(store.list_all())
        if not states:
            return {"success": False, "error": "No Gmail accounts connected"}

        state = next(
            (
                candidate
                for candidate in states
                if self._record_value(candidate, "refresh_token")
                or self._record_value(candidate, "access_token")
            ),
            None,
        )
        if state is None:
            return {"success": False, "error": "No Gmail tokens available"}

        connector = GmailConnector()
        connector._refresh_token = self._record_value(state, "refresh_token")
        connector._access_token = self._record_value(state, "access_token")

        token_expiry = self._record_value(state, "token_expiry")
        if isinstance(token_expiry, datetime):
            connector._token_expiry = token_expiry
        elif connector._access_token:
            connector._token_expiry = datetime.now(timezone.utc) + timedelta(minutes=5)

        if not connector._refresh_token and not connector._access_token:
            return {"success": False, "error": "No Gmail tokens available"}

        try:
            profile = await connector.get_user_info()
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            RuntimeError,
            KeyError,
        ) as e:
            logger.warning("Gmail API test failed: %s", e)
            return {"success": False, "error": "Gmail API test failed"}

        return {
            "success": True,
            "email": profile.get("emailAddress") or self._record_value(state, "email_address"),
            "messages_total": profile.get("messagesTotal"),
            "user_id": self._record_value(state, "user_id"),
        }

    async def _list_workspaces(self, provider_id: str) -> HandlerResult:
        """
        List connected workspaces/tenants for a provider.

        GET /api/v2/integrations/wizard/{provider}/workspaces
        """
        if provider_id not in PROVIDERS:
            return error_response(f"Unknown provider: {provider_id}", 404)

        try:
            if provider_id == "slack":
                workspaces = await self._get_slack_workspaces()
            elif provider_id == "teams":
                workspaces = await self._get_teams_tenants()
            elif provider_id == "github":
                return json_response(
                    {
                        "provider": provider_id,
                        "workspaces": [],
                        "count": 0,
                        "message": (
                            "GitHub App installations are managed in GitHub; Aragora does not "
                            "persist a local workspace inventory."
                        ),
                    }
                )
            else:
                return json_response(
                    {
                        "provider": provider_id,
                        "workspaces": [],
                        "message": f"Workspace listing not available for {provider_id}",
                    }
                )

            return json_response(
                {
                    "provider": provider_id,
                    "workspaces": workspaces,
                    "count": len(workspaces),
                }
            )
        except (ImportError, ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.exception("Failed to list workspaces for %s: %s", provider_id, e)
            return error_response("Failed to list workspaces", 500)

    async def _get_slack_workspaces(self) -> list[dict[str, Any]]:
        """Get list of connected Slack workspaces."""
        from aragora.storage.slack_workspace_store import get_slack_workspace_store

        store = get_slack_workspace_store()
        workspaces = store.list_active(limit=100)
        return [
            {
                "id": self._record_value(ws, "workspace_id", "id"),
                "name": self._record_value(ws, "workspace_name", "name", default="Unknown"),
                "is_active": self._record_value(ws, "is_active", default=True),
                "connected_at": self._record_value(ws, "created_at", "installed_at"),
            }
            for ws in workspaces
        ]

    async def _get_teams_tenants(self) -> list[dict[str, Any]]:
        """Get list of connected Teams tenants."""
        from aragora.storage.teams_tenant_store import get_teams_tenant_store

        store = get_teams_tenant_store()
        tenants = store.list_active(limit=100)
        return [
            {
                "id": self._record_value(t, "tenant_id", "id"),
                "name": self._record_value(t, "tenant_name", "name", default="Unknown"),
                "is_active": self._record_value(t, "is_active", default=True),
                "connected_at": self._record_value(t, "created_at", "installed_at"),
            }
            for t in tenants
        ]

    async def _disconnect_provider(
        self,
        provider_id: str,
        body: dict[str, Any],
        auth_context: Any,
    ) -> HandlerResult:
        """
        Disconnect a workspace/tenant from a provider.

        POST /api/v2/integrations/wizard/{provider}/disconnect
        Body: { "workspace_id": "..." } or { "tenant_id": "..." }
        """
        if provider_id not in PROVIDERS:
            return error_response(f"Unknown provider: {provider_id}", 404)

        try:
            if provider_id == "slack":
                workspace_id = body.get("workspace_id")
                if not workspace_id:
                    return error_response("workspace_id is required", 400)
                result = await self._disconnect_slack_workspace(workspace_id)
            elif provider_id == "teams":
                tenant_id = body.get("tenant_id")
                if not tenant_id:
                    return error_response("tenant_id is required", 400)
                result = await self._disconnect_teams_tenant(tenant_id)
            elif provider_id == "discord":
                guild_id = body.get("guild_id")
                if not guild_id:
                    return error_response("guild_id is required", 400)
                result = await self._disconnect_discord_guild(guild_id)
            elif provider_id == "gmail":
                user_id = body.get("user_id", "default")
                result = await self._disconnect_gmail_account(user_id)
            elif provider_id == "email":
                workspace_id = body.get("workspace_id", "default")
                user_id = getattr(auth_context, "user_id", "default")
                result = await self._disconnect_email_config(user_id, workspace_id)
            elif provider_id == "github":
                result = await self._disconnect_github_installation()
            else:
                return error_response(
                    f"Disconnect not implemented for provider '{provider_id}'. "
                    "Supported providers: slack, teams, discord, gmail, email, github.",
                    501,
                )

            return json_response(
                {
                    "provider": provider_id,
                    "disconnected": result.get("success", False),
                    "message": result.get("message", ""),
                }
            )
        except (ImportError, ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.exception("Failed to disconnect %s: %s", provider_id, e)
            return error_response("Disconnect operation failed", 500)

    async def _disconnect_slack_workspace(self, workspace_id: str) -> dict[str, Any]:
        """Disconnect a Slack workspace."""
        from aragora.storage.slack_workspace_store import get_slack_workspace_store

        store = get_slack_workspace_store()
        store.deactivate(workspace_id)
        logger.info("Disconnected Slack workspace: %s", workspace_id)
        return {"success": True, "message": f"Workspace {workspace_id} disconnected"}

    async def _disconnect_teams_tenant(self, tenant_id: str) -> dict[str, Any]:
        """Disconnect a Teams tenant."""
        from aragora.storage.teams_tenant_store import get_teams_tenant_store

        store = get_teams_tenant_store()
        store.deactivate(tenant_id)
        logger.info("Disconnected Teams tenant: %s", tenant_id)
        return {"success": True, "message": f"Tenant {tenant_id} disconnected"}

    async def _disconnect_discord_guild(self, guild_id: str) -> dict[str, Any]:
        """Disconnect a Discord guild (server)."""
        from aragora.storage.discord_guild_store import get_discord_guild_store

        store = get_discord_guild_store()
        success = store.deactivate(guild_id)
        if success:
            logger.info("Disconnected Discord guild: %s", guild_id)
            return {"success": True, "message": f"Guild {guild_id} disconnected"}
        else:
            return {"success": False, "message": f"Guild {guild_id} not found"}

    async def _disconnect_gmail_account(self, user_id: str) -> dict[str, Any]:
        """Disconnect a Gmail account integration."""
        from aragora.storage.integration_store import get_integration_store

        store = get_integration_store()
        success = await store.delete("gmail", user_id)
        if success:
            logger.info("Disconnected Gmail account for user: %s", user_id)
            return {"success": True, "message": f"Gmail disconnected for user {user_id}"}
        else:
            return {"success": False, "message": f"Gmail integration not found for user {user_id}"}

    async def _disconnect_email_config(self, user_id: str, workspace_id: str) -> dict[str, Any]:
        """Disconnect SMTP email by deleting the persisted email config."""
        from aragora.storage.email_store import get_email_store

        store = get_email_store()
        deleted = store.delete_user_config(user_id, workspace_id)
        if deleted:
            logger.info(
                "Disconnected email config for user=%s workspace=%s",
                user_id,
                workspace_id,
            )
            return {
                "success": True,
                "message": f"Email configuration cleared for workspace {workspace_id}",
            }
        return {
            "success": False,
            "message": f"No email configuration found for workspace {workspace_id}",
        }

    async def _disconnect_github_installation(self) -> dict[str, Any]:
        """Explain how GitHub app installs are disconnected truthfully."""
        return {
            "success": False,
            "message": (
                "GitHub integrations are managed through GitHub App installations. "
                "Uninstall the Aragora GitHub App in GitHub to disconnect it."
            ),
        }


# Handler factory function for registration
def create_oauth_wizard_handler(server_context: dict[str, Any]) -> OAuthWizardHandler:
    """Factory function for handler registration."""
    return OAuthWizardHandler(server_context)
