"""
External Integrations API Handler.

Provides REST API endpoints for managing external automation integrations:
- Zapier: REST Hook triggers and actions
- Make (Integromat): Webhook modules and actions
- n8n: Custom nodes and webhooks

Endpoints:
- POST   /api/integrations/zapier/apps              - Create Zapier app
- GET    /api/integrations/zapier/apps              - List Zapier apps
- DELETE /api/integrations/zapier/apps/:id          - Delete Zapier app
- POST   /api/integrations/zapier/triggers          - Subscribe to trigger
- DELETE /api/integrations/zapier/triggers/:id      - Unsubscribe trigger
- GET    /api/integrations/zapier/triggers          - List trigger types

- POST   /api/integrations/make/connections         - Create Make connection
- GET    /api/integrations/make/connections         - List Make connections
- DELETE /api/integrations/make/connections/:id     - Delete Make connection
- POST   /api/integrations/make/webhooks            - Register webhook
- DELETE /api/integrations/make/webhooks/:id        - Unregister webhook
- GET    /api/integrations/make/modules             - List available modules

- POST   /api/integrations/n8n/credentials          - Create n8n credential
- GET    /api/integrations/n8n/credentials          - List n8n credentials
- DELETE /api/integrations/n8n/credentials/:id      - Delete n8n credential
- POST   /api/integrations/n8n/webhooks             - Register webhook
- DELETE /api/integrations/n8n/webhooks/:id         - Unregister webhook
- GET    /api/integrations/n8n/nodes                - Get node definitions
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.audit.unified import audit_data
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.openapi_decorator import api_endpoint

from aragora.integrations.zapier import ZapierIntegration, get_zapier_integration
from aragora.integrations.make import MakeIntegration, get_make_integration
from aragora.integrations.n8n import N8nIntegration, get_n8n_integration
from aragora.server.handlers.base import (
    SAFE_ID_PATTERN,
    error_response,
    handle_errors,
    json_response,
    safe_error_message,
)
from aragora.server.handlers.secure import SecureHandler
from aragora.server.handlers.utils.rate_limit import RateLimiter, get_client_ip
from aragora.server.handlers.utils.url_security import validate_webhook_url
from aragora.server.handlers.utils.responses import HandlerResult
from aragora.server.versioning.compat import strip_version_prefix

logger = logging.getLogger(__name__)

# RBAC imports (optional - graceful degradation if not available)
try:
    from aragora.rbac import (
        AuthorizationContext,
        check_permission,
        PermissionDeniedError,
    )
    from aragora.billing.auth import extract_user_from_request

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

# Metrics imports (optional)
try:
    from aragora.observability.metrics import record_rbac_check

    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False

    def record_rbac_check(*args, **kwargs):
        pass

# =============================================================================
# Rate Limits for External Integrations
# =============================================================================

# Rate limits for integration operations
INTEGRATION_CREATE_RPM = 10  # Max 10 creates per minute
INTEGRATION_LIST_RPM = 60  # Max 60 list operations per minute
INTEGRATION_DELETE_RPM = 20  # Max 20 deletes per minute
INTEGRATION_TEST_RPM = 5  # Max 5 tests per minute

# Rate limiter instances
_create_limiter = RateLimiter(requests_per_minute=INTEGRATION_CREATE_RPM)
_list_limiter = RateLimiter(requests_per_minute=INTEGRATION_LIST_RPM)
_delete_limiter = RateLimiter(requests_per_minute=INTEGRATION_DELETE_RPM)
_test_limiter = RateLimiter(requests_per_minute=INTEGRATION_TEST_RPM)

# =============================================================================
# External Integrations Handler
# =============================================================================


class ExternalIntegrationsHandler(SecureHandler):
    """Handler for external integration management.

    Extends SecureHandler for JWT-based authentication and audit logging.
    """

    RESOURCE_TYPE = "external_integration"

    """Handler for external integrations API endpoints."""

    # Routes this handler responds to
    routes = [
        # Zapier
        "POST /api/integrations/zapier/apps",
        "GET /api/integrations/zapier/apps",
        "DELETE /api/integrations/zapier/apps/:id",
        "POST /api/integrations/zapier/triggers",
        "DELETE /api/integrations/zapier/triggers/:id",
        "GET /api/integrations/zapier/triggers",
        # Make
        "POST /api/integrations/make/connections",
        "GET /api/integrations/make/connections",
        "DELETE /api/integrations/make/connections/:id",
        "POST /api/integrations/make/webhooks",
        "DELETE /api/integrations/make/webhooks/:id",
        "GET /api/integrations/make/modules",
        # n8n
        "POST /api/integrations/n8n/credentials",
        "GET /api/integrations/n8n/credentials",
        "DELETE /api/integrations/n8n/credentials/:id",
        "POST /api/integrations/n8n/webhooks",
        "DELETE /api/integrations/n8n/webhooks/:id",
        "GET /api/integrations/n8n/nodes",
        # Test endpoints
        "POST /api/integrations/:platform/test",
    ]

    ROUTES = [
        "/api/v1/integrations/zapier/apps",
        "/api/v1/integrations/zapier/triggers",
        "/api/v1/integrations/make/connections",
        "/api/v1/integrations/make/webhooks",
        "/api/v1/integrations/make/modules",
        "/api/v1/integrations/n8n/credentials",
        "/api/v1/integrations/n8n/webhooks",
        "/api/v1/integrations/n8n/nodes",
        # Integration wizard endpoints
        "/api/v1/integrations/wizard/preflight",
        "/api/v1/integrations/wizard/recommendations",
        # V2 integration endpoints
        "/api/v2/integrations/stats",
        "/api/v2/integrations/wizard/providers",
        "/api/v2/integrations/wizard/status",
        "/api/v2/integrations/wizard/validate",
    ]

    @staticmethod
    def can_handle(path: str) -> bool:
        """Check if this handler can handle the given path."""
        normalized = strip_version_prefix(path)
        if not normalized.startswith("/api/integrations/"):
            return False
        segments = normalized.strip("/").split("/")
        return len(segments) >= 3 and segments[2] in {"zapier", "make", "n8n"}

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        self._zapier: ZapierIntegration | None = None
        self._make: MakeIntegration | None = None
        self._n8n: N8nIntegration | None = None

    def _read_json_object_body(self, handler: Any) -> tuple[dict[str, Any] | None, HandlerResult]:
        """Read and validate a JSON request body."""
        body, err = self.read_json_body_validated(handler)
        if err or body is None:
            return None, err
        if not isinstance(body, dict):
            return None, error_response(
                "Request body must be a JSON object", 400, code="INVALID_REQUEST_BODY"
            )
        return body, None

    def _require_string_field(
        self, body: dict[str, Any], field_name: str, missing_code: str, invalid_code: str
    ) -> tuple[str | None, HandlerResult]:
        """Validate that a required field is a non-empty string."""
        value = body.get(field_name)
        if value is None:
            return None, error_response(f"{field_name} is required", 400, code=missing_code)
        if not isinstance(value, str):
            return None, error_response(f"{field_name} must be a string", 400, code=invalid_code)
        value = value.strip()
        if not value:
            return None, error_response(
                f"{field_name} must be a non-empty string", 400, code=invalid_code
            )
        return value, None

    def _optional_string_field(
        self,
        body: dict[str, Any],
        field_name: str,
        invalid_code: str,
        *,
        allow_empty_string: bool = False,
    ) -> tuple[str | None, HandlerResult]:
        """Validate that an optional field is a non-empty string when provided."""
        value = body.get(field_name)
        if value is None:
            return None, None
        if not isinstance(value, str):
            return None, error_response(f"{field_name} must be a string", 400, code=invalid_code)
        if allow_empty_string and value == "":
            return None, None
        value = value.strip()
        if not value:
            return None, error_response(
                f"{field_name} must be a non-empty string", 400, code=invalid_code
            )
        return value, None

    def _require_string_list_field(
        self, body: dict[str, Any], field_name: str, missing_code: str, invalid_code: str
    ) -> tuple[list[str] | None, HandlerResult]:
        """Validate that a required field is a non-empty list of non-empty strings."""
        value = body.get(field_name)
        if value is None:
            return None, error_response(f"{field_name} is required", 400, code=missing_code)
        if not isinstance(value, list) or not value:
            return None, error_response(
                f"{field_name} must be a non-empty list of strings", 400, code=invalid_code
            )

        normalized_values: list[str] = []
        for index, item in enumerate(value):
            if not isinstance(item, str):
                return None, error_response(
                    f"{field_name}[{index}] must be a string", 400, code=invalid_code
                )
            item = item.strip()
            if not item:
                return None, error_response(
                    f"{field_name}[{index}] must be a non-empty string",
                    400,
                    code=invalid_code,
                )
            normalized_values.append(item)

        return normalized_values, None

    def _optional_string_list_field(
        self, body: dict[str, Any], field_name: str, invalid_code: str
    ) -> tuple[list[str] | None, HandlerResult]:
        """Validate that an optional field is a non-empty list of non-empty strings."""
        value = body.get(field_name)
        if value is None:
            return None, None
        if not isinstance(value, list) or not value:
            return None, error_response(
                f"{field_name} must be a non-empty list of strings", 400, code=invalid_code
            )

        normalized_values: list[str] = []
        for index, item in enumerate(value):
            if not isinstance(item, str):
                return None, error_response(
                    f"{field_name}[{index}] must be a string", 400, code=invalid_code
                )
            item = item.strip()
            if not item:
                return None, error_response(
                    f"{field_name}[{index}] must be a non-empty string",
                    400,
                    code=invalid_code,
                )
            normalized_values.append(item)

        return normalized_values, None

    def _optional_number_field(
        self,
        body: dict[str, Any],
        field_name: str,
        invalid_code: str,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> tuple[float | int | None, HandlerResult]:
        """Validate that an optional field is a number within an optional range."""
        value = body.get(field_name)
        if value is None:
            return None, None
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None, error_response(f"{field_name} must be a number", 400, code=invalid_code)
        if minimum is not None and value < minimum:
            return None, error_response(
                f"{field_name} must be greater than or equal to {minimum}",
                400,
                code=invalid_code,
            )
        if maximum is not None and value > maximum:
            return None, error_response(
                f"{field_name} must be less than or equal to {maximum}",
                400,
                code=invalid_code,
            )
        return value, None

    def _optional_object_field(
        self, body: dict[str, Any], field_name: str, invalid_code: str
    ) -> tuple[dict[str, Any] | None, HandlerResult]:
        """Validate that an optional field is a JSON object when provided."""
        value = body.get(field_name)
        if value is None:
            return None, None
        if isinstance(value, dict):
            return value, None
        return None, error_response(f"{field_name} must be an object", 400, code=invalid_code)

    def _optional_query_string_param(
        self, query_params: dict[str, Any], param_name: str, invalid_code: str
    ) -> tuple[str | None, HandlerResult]:
        """Validate that an optional query parameter is a non-empty string when provided."""
        value = query_params.get(param_name)
        if value is None:
            return None, None
        if isinstance(value, list):
            if not value:
                return None, None
            value = value[0]
        if not isinstance(value, str):
            return None, error_response(
                f"{param_name} query parameter must be a string", 400, code=invalid_code
            )
        value = value.strip()
        if not value:
            return None, error_response(
                f"{param_name} query parameter must be a non-empty string",
                400,
                code=invalid_code,
            )
        return value, None

    def _require_query_string_param(
        self,
        query_params: dict[str, Any],
        param_name: str,
        missing_code: str,
        invalid_code: str,
    ) -> tuple[str | None, HandlerResult]:
        """Validate that a required query parameter is a non-empty string."""
        value, err = self._optional_query_string_param(query_params, param_name, invalid_code)
        if err:
            return None, err
        if value is None:
            return None, error_response(
                f"{param_name} query parameter is required", 400, code=missing_code
            )
        return value, None

    # =========================================================================
    # RBAC Helper Methods
    # =========================================================================

    def _get_auth_context(self, handler: Any) -> AuthorizationContext | None:
        """Extract authorization context from the request."""
        if not RBAC_AVAILABLE:
            # Fail closed in production - caller must handle None with rbac_fail_closed()
            return None

        try:
            # Try to get user info from request
            user_info = extract_user_from_request(handler)
            if not user_info:
                return None

            roles = {user_info.role} if user_info.role else {"member"}
            permissions: set[str] = set()
            try:
                from aragora.rbac.defaults import get_role_permissions

                for role in roles:
                    permissions |= get_role_permissions(role, include_inherited=True)
            except (ImportError, Exception) as exc:
                logger.debug("Could not resolve RBAC permissions: %s", exc)

            return AuthorizationContext(
                user_id=user_info.user_id or "anonymous",
                roles=roles,
                permissions=permissions,
                org_id=user_info.org_id,
            )
        except (AttributeError, ValueError, TypeError, KeyError) as e:
            logger.debug("Could not extract auth context: %s", e)
            return None

    def _check_permission(
        self, handler: Any, permission_key: str, resource_id: str | None = None
    ) -> HandlerResult | None:
        """
        Check if current user has permission. Returns error response if denied.

        Args:
            handler: The HTTP handler
            permission_key: Permission like "connectors.read" or "connectors.create"
            resource_id: Optional resource ID for resource-specific permissions

        Returns:
            None if allowed, error HandlerResult if denied
        """
        if not RBAC_AVAILABLE:
            if rbac_fail_closed():
                return error_response("Service unavailable: access control module not loaded", 503)
            logger.debug("RBAC not available, allowing %s", permission_key)
            return None

        context = self._get_auth_context(handler)
        if context is None:
            # No auth context means RBAC not configured for this request
            return None

        try:
            decision = check_permission(context, permission_key, resource_id)
            if not decision.allowed:
                logger.warning(
                    "Permission denied: %s for user %s: %s",
                    permission_key,
                    context.user_id,
                    decision.reason,
                )
                record_rbac_check(permission_key, granted=False)
                return error_response("Permission denied", 403)
            record_rbac_check(permission_key, granted=True)
        except PermissionDeniedError as e:
            logger.warning(
                "Permission denied: %s for user %s: %s", permission_key, context.user_id, e
            )
            record_rbac_check(permission_key, granted=False)
            return error_response(safe_error_message(e, "integration permission"), 403)

        return None

    def _get_zapier(self) -> ZapierIntegration:
        """Get or create Zapier integration instance."""
        if self._zapier is None:
            self._zapier = get_zapier_integration()
        return self._zapier

    def _get_make(self) -> MakeIntegration:
        """Get or create Make integration instance."""
        if self._make is None:
            self._make = get_make_integration()
        return self._make

    def _get_n8n(self) -> N8nIntegration:
        """Get or create n8n integration instance."""
        if self._n8n is None:
            self._n8n = get_n8n_integration()
        return self._n8n

    # =========================================================================
    # GET Handlers
    # =========================================================================

    @require_permission("integrations:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET requests for external integrations endpoints."""
        # Rate limit check for list operations
        client_ip = get_client_ip(handler)
        if not _list_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for integrations list: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # Zapier endpoints
        if path == "/api/v1/integrations/zapier/apps":
            return self._handle_list_zapier_apps(query_params, handler)
        if path == "/api/v1/integrations/zapier/triggers":
            return self._handle_list_zapier_trigger_types(handler)

        # Make endpoints
        if path == "/api/v1/integrations/make/connections":
            return self._handle_list_make_connections(query_params, handler)
        if path == "/api/v1/integrations/make/modules":
            return self._handle_list_make_modules(handler)

        # n8n endpoints
        if path == "/api/v1/integrations/n8n/credentials":
            return self._handle_list_n8n_credentials(query_params, handler)
        if path == "/api/v1/integrations/n8n/nodes":
            return self._handle_get_n8n_nodes(handler)

        return None

    # =========================================================================
    # POST Handlers
    # =========================================================================

    @handle_errors("external integration creation")
    @require_permission("integrations:write")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests for external integrations endpoints."""

        # Zapier endpoints
        if path == "/api/v1/integrations/zapier/apps":
            body, err = self._read_json_object_body(handler)
            if err or body is None:
                return err
            return self._handle_create_zapier_app(body, handler)

        if path == "/api/v1/integrations/zapier/triggers":
            body, err = self._read_json_object_body(handler)
            if err or body is None:
                return err
            return self._handle_subscribe_zapier_trigger(body, handler)

        # Make endpoints
        if path == "/api/v1/integrations/make/connections":
            body, err = self._read_json_object_body(handler)
            if err or body is None:
                return err
            return self._handle_create_make_connection(body, handler)

        if path == "/api/v1/integrations/make/webhooks":
            body, err = self._read_json_object_body(handler)
            if err or body is None:
                return err
            return self._handle_register_make_webhook(body, handler)

        # n8n endpoints
        if path == "/api/v1/integrations/n8n/credentials":
            body, err = self._read_json_object_body(handler)
            if err or body is None:
                return err
            return self._handle_create_n8n_credential(body, handler)

        if path == "/api/v1/integrations/n8n/webhooks":
            body, err = self._read_json_object_body(handler)
            if err or body is None:
                return err
            return self._handle_register_n8n_webhook(body, handler)

        # Test endpoints
        # Path: /api/v1/integrations/{platform}/test
        # Split (with leading empty): ["", "api", "v1", "integrations", "{platform}", "test"]
        if path.endswith("/test"):
            parts = path.split("/")
            if len(parts) >= 6:
                platform = parts[4]
                return self._handle_test_integration(platform, handler)

        return None

    # =========================================================================
    # DELETE Handlers
    # =========================================================================

    @handle_errors("external integration deletion")
    @require_permission("integrations:delete")
    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle DELETE requests for external integrations endpoints."""

        # Zapier app deletion
        if path.startswith("/api/v1/integrations/zapier/apps/"):
            # Path: /api/v1/integrations/zapier/apps/{app_id}
            # Split: ["", "api", "v1", "integrations", "zapier", "apps", "{app_id}"]
            app_id, err = self.extract_path_param(path, 6, "app_id", SAFE_ID_PATTERN)
            if err or app_id is None:
                return err
            return self._handle_delete_zapier_app(app_id, handler)

        # Zapier trigger unsubscribe
        if path.startswith("/api/v1/integrations/zapier/triggers/"):
            # Path: /api/v1/integrations/zapier/triggers/{trigger_id}
            # Split (with leading empty): ["", "api", "v1", "integrations", "zapier", "triggers", "{trigger_id}"]
            trigger_id, err = self.extract_path_param(path, 6, "trigger_id", SAFE_ID_PATTERN)
            if err or trigger_id is None:
                return err
            app_id, err = self._require_query_string_param(
                query_params, "app_id", "MISSING_APP_ID", "INVALID_APP_ID"
            )
            if err or app_id is None:
                return err
            return self._handle_unsubscribe_zapier_trigger(app_id, trigger_id, handler)

        # Make connection deletion
        if path.startswith("/api/v1/integrations/make/connections/"):
            # Path: /api/v1/integrations/make/connections/{conn_id}
            # Split: ["", "api", "v1", "integrations", "make", "connections", "{conn_id}"]
            conn_id, err = self.extract_path_param(path, 6, "conn_id", SAFE_ID_PATTERN)
            if err or conn_id is None:
                return err
            return self._handle_delete_make_connection(conn_id, handler)

        # Make webhook unregister
        if path.startswith("/api/v1/integrations/make/webhooks/"):
            # Path: /api/v1/integrations/make/webhooks/{webhook_id}
            # Split (with leading empty): ["", "api", "v1", "integrations", "make", "webhooks", "{webhook_id}"]
            webhook_id, err = self.extract_path_param(path, 6, "webhook_id", SAFE_ID_PATTERN)
            if err or webhook_id is None:
                return err
            conn_id, err = self._require_query_string_param(
                query_params,
                "connection_id",
                "MISSING_CONNECTION_ID",
                "INVALID_CONNECTION_ID",
            )
            if err or conn_id is None:
                return err
            return self._handle_unregister_make_webhook(conn_id, webhook_id, handler)

        # n8n credential deletion
        if path.startswith("/api/v1/integrations/n8n/credentials/"):
            # Path: /api/v1/integrations/n8n/credentials/{cred_id}
            # Split: ["", "api", "v1", "integrations", "n8n", "credentials", "{cred_id}"]
            cred_id, err = self.extract_path_param(path, 6, "cred_id", SAFE_ID_PATTERN)
            if err or cred_id is None:
                return err
            return self._handle_delete_n8n_credential(cred_id, handler)

        # n8n webhook unregister
        if path.startswith("/api/v1/integrations/n8n/webhooks/"):
            # Path: /api/v1/integrations/n8n/webhooks/{webhook_id}
            # Split (with leading empty): ["", "api", "v1", "integrations", "n8n", "webhooks", "{webhook_id}"]
            webhook_id, err = self.extract_path_param(path, 6, "webhook_id", SAFE_ID_PATTERN)
            if err or webhook_id is None:
                return err
            cred_id, err = self._require_query_string_param(
                query_params,
                "credential_id",
                "MISSING_CREDENTIAL_ID",
                "INVALID_CREDENTIAL_ID",
            )
            if err or cred_id is None:
                return err
            return self._handle_unregister_n8n_webhook(cred_id, webhook_id, handler)

        return None

    # =========================================================================
    # Zapier Handlers
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/integrations/zapier/apps",
        summary="List Zapier apps",
        tags=["Integrations"],
    )
    def _handle_list_zapier_apps(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        """Handle GET /api/integrations/zapier/apps - list Zapier apps."""
        # Check RBAC permission
        perm_error = self._check_permission(handler, "connectors.read")
        if perm_error:
            return perm_error

        self.get_current_user(handler)
        workspace_id, field_error = self._optional_query_string_param(
            query_params, "workspace_id", "INVALID_WORKSPACE_ID"
        )
        if field_error:
            return field_error

        zapier = self._get_zapier()
        apps = zapier.list_apps(workspace_id)

        return json_response(
            {
                "apps": [
                    {
                        "id": app.id,
                        "workspace_id": app.workspace_id,
                        "created_at": app.created_at,
                        "active": app.active,
                        "trigger_count": app.trigger_count,
                        "action_count": app.action_count,
                    }
                    for app in apps
                ],
                "count": len(apps),
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/integrations/zapier/triggers",
        summary="List Zapier trigger types",
        tags=["Integrations"],
    )
    def _handle_list_zapier_trigger_types(self, handler: Any) -> HandlerResult:
        """Handle GET /api/integrations/zapier/triggers - list trigger types."""
        # Check RBAC permission
        perm_error = self._check_permission(handler, "connectors.read")
        if perm_error:
            return perm_error

        zapier = self._get_zapier()

        return json_response(
            {
                "triggers": zapier.TRIGGER_TYPES,
                "actions": zapier.ACTION_TYPES,
            }
        )

    @api_endpoint(
        method="POST",
        path="/api/v1/integrations/zapier/apps",
        summary="Create Zapier app",
        tags=["Integrations"],
    )
    def _handle_create_zapier_app(self, body: dict, handler: Any) -> HandlerResult:
        """Handle POST /api/integrations/zapier/apps - create Zapier app."""
        # Check RBAC permission - creating integrations exposes API keys
        perm_error = self._check_permission(handler, "connectors.create")
        if perm_error:
            return perm_error

        workspace_id, field_error = self._require_string_field(
            body, "workspace_id", "MISSING_WORKSPACE_ID", "INVALID_WORKSPACE_ID"
        )
        if field_error:
            return field_error

        zapier = self._get_zapier()
        app = zapier.create_app(workspace_id)

        auth_ctx = self._get_auth_context(handler)
        user_id = auth_ctx.user_id if auth_ctx else "system"
        audit_data(
            user_id=user_id,
            resource_type="zapier_app",
            resource_id=app.id,
            action="create",
            workspace_id=workspace_id,
        )

        return json_response(
            {
                "app": {
                    "id": app.id,
                    "workspace_id": app.workspace_id,
                    "api_key": app.api_key,
                    "api_secret": app.api_secret,
                    "created_at": app.created_at,
                },
                "message": "Zapier app created. Save the api_key and api_secret - they won't be shown again.",
            },
            status=201,
        )

    @api_endpoint(
        method="DELETE",
        path="/api/v1/integrations/zapier/apps/{app_id}",
        summary="Delete Zapier app",
        tags=["Integrations"],
    )
    def _handle_delete_zapier_app(self, app_id: str, handler: Any) -> HandlerResult:
        """Handle DELETE /api/integrations/zapier/apps/:id - delete Zapier app."""
        # Check RBAC permission
        perm_error = self._check_permission(handler, "connectors.delete", app_id)
        if perm_error:
            return perm_error

        zapier = self._get_zapier()

        if zapier.delete_app(app_id):
            auth_ctx = self._get_auth_context(handler)
            user_id = auth_ctx.user_id if auth_ctx else "system"
            audit_data(
                user_id=user_id,
                resource_type="zapier_app",
                resource_id=app_id,
                action="delete",
            )
            return json_response({"deleted": True, "app_id": app_id})
        else:
            return error_response(
                f"Zapier app not found: {app_id}", 404, code="ZAPIER_APP_NOT_FOUND"
            )

    @api_endpoint(
        method="POST",
        path="/api/v1/integrations/zapier/triggers",
        summary="Subscribe to Zapier trigger",
        tags=["Integrations"],
    )
    def _handle_subscribe_zapier_trigger(self, body: dict, handler: Any) -> HandlerResult:
        """Handle POST /api/integrations/zapier/triggers - subscribe to trigger."""
        # Check RBAC permission - subscribing creates webhooks
        perm_error = self._check_permission(handler, "connectors.create")
        if perm_error:
            return perm_error

        app_id, field_error = self._require_string_field(
            body, "app_id", "MISSING_APP_ID", "INVALID_APP_ID"
        )
        if field_error:
            return field_error
        trigger_type, field_error = self._require_string_field(
            body, "trigger_type", "MISSING_TRIGGER_TYPE", "INVALID_TRIGGER_TYPE"
        )
        if field_error:
            return field_error
        webhook_url, field_error = self._require_string_field(
            body, "webhook_url", "MISSING_WEBHOOK_URL", "INVALID_WEBHOOK_URL"
        )
        if field_error:
            return field_error
        workspace_id, field_error = self._optional_string_field(
            body, "workspace_id", "INVALID_WORKSPACE_ID"
        )
        if field_error:
            return field_error
        debate_tags, field_error = self._optional_string_list_field(
            body, "debate_tags", "INVALID_DEBATE_TAGS"
        )
        if field_error:
            return field_error
        min_confidence, field_error = self._optional_number_field(
            body,
            "min_confidence",
            "INVALID_MIN_CONFIDENCE",
            minimum=0.0,
            maximum=1.0,
        )
        if field_error:
            return field_error

        is_valid, url_error = validate_webhook_url(webhook_url, allow_localhost=False)
        if not is_valid:
            return error_response(f"Invalid webhook URL: {url_error}", 400)

        zapier = self._get_zapier()
        trigger = zapier.subscribe_trigger(
            app_id=app_id,
            trigger_type=trigger_type,
            webhook_url=webhook_url,
            workspace_id=workspace_id,
            debate_tags=debate_tags,
            min_confidence=min_confidence,
        )

        if trigger:
            return json_response(
                {
                    "trigger": {
                        "id": trigger.id,
                        "trigger_type": trigger.trigger_type,
                        "webhook_url": trigger.webhook_url,
                        "created_at": trigger.created_at,
                    }
                },
                status=201,
            )
        else:
            return error_response(
                "Failed to subscribe trigger", 400, code="TRIGGER_SUBSCRIBE_FAILED"
            )

    @api_endpoint(
        method="DELETE",
        path="/api/v1/integrations/zapier/triggers/{trigger_id}",
        summary="Unsubscribe from Zapier trigger",
        tags=["Integrations"],
    )
    def _handle_unsubscribe_zapier_trigger(
        self, app_id: str, trigger_id: str, handler: Any
    ) -> HandlerResult:
        """Handle DELETE /api/integrations/zapier/triggers/:id - unsubscribe."""
        # Check RBAC permission
        perm_error = self._check_permission(handler, "connectors.delete", trigger_id)
        if perm_error:
            return perm_error

        if not app_id:
            return error_response("app_id query parameter is required", 400, code="MISSING_APP_ID")

        zapier = self._get_zapier()

        if zapier.unsubscribe_trigger(app_id, trigger_id):
            return json_response({"deleted": True, "trigger_id": trigger_id})
        else:
            return error_response(f"Trigger not found: {trigger_id}", 404, code="TRIGGER_NOT_FOUND")

    # =========================================================================
    # Make Handlers
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/integrations/make/connections",
        summary="List Make connections",
        tags=["Integrations"],
    )
    def _handle_list_make_connections(
        self, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult:
        """Handle GET /api/integrations/make/connections - list connections."""
        # Check RBAC permission
        perm_error = self._check_permission(handler, "connectors.read")
        if perm_error:
            return perm_error

        workspace_id, field_error = self._optional_query_string_param(
            query_params, "workspace_id", "INVALID_WORKSPACE_ID"
        )
        if field_error:
            return field_error

        make = self._get_make()
        connections = make.list_connections(workspace_id)

        return json_response(
            {
                "connections": [
                    {
                        "id": conn.id,
                        "workspace_id": conn.workspace_id,
                        "created_at": conn.created_at,
                        "active": conn.active,
                        "total_operations": conn.total_operations,
                        "webhooks_count": len(conn.webhooks),
                    }
                    for conn in connections
                ],
                "count": len(connections),
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/integrations/make/modules",
        summary="List Make modules",
        tags=["Integrations"],
    )
    def _handle_list_make_modules(self, handler: Any) -> HandlerResult:
        # Check RBAC permission
        perm_error = self._check_permission(handler, "connectors.read")
        if perm_error:
            return perm_error

        """Handle GET /api/integrations/make/modules - list available modules."""
        make = self._get_make()

        return json_response(
            {
                "modules": make.MODULE_TYPES,
            }
        )

    @api_endpoint(
        method="POST",
        path="/api/v1/integrations/make/connections",
        summary="Create Make connection",
        tags=["Integrations"],
    )
    def _handle_create_make_connection(self, body: dict, handler: Any) -> HandlerResult:
        """Handle POST /api/integrations/make/connections - create connection."""
        # Check RBAC permission - creating integrations exposes API keys
        perm_error = self._check_permission(handler, "connectors.create")
        if perm_error:
            return perm_error

        workspace_id, field_error = self._require_string_field(
            body, "workspace_id", "MISSING_WORKSPACE_ID", "INVALID_WORKSPACE_ID"
        )
        if field_error:
            return field_error

        make = self._get_make()
        connection = make.create_connection(workspace_id)

        auth_ctx = self._get_auth_context(handler)
        user_id = auth_ctx.user_id if auth_ctx else "system"
        audit_data(
            user_id=user_id,
            resource_type="make_connection",
            resource_id=connection.id,
            action="create",
            workspace_id=workspace_id,
        )

        return json_response(
            {
                "connection": {
                    "id": connection.id,
                    "workspace_id": connection.workspace_id,
                    "api_key": connection.api_key,
                    "created_at": connection.created_at,
                },
                "message": "Make connection created. Save the api_key - it won't be shown again.",
            },
            status=201,
        )

    @api_endpoint(
        method="DELETE",
        path="/api/v1/integrations/make/connections/{connection_id}",
        summary="Delete Make connection",
        tags=["Integrations"],
    )
    def _handle_delete_make_connection(self, conn_id: str, handler: Any) -> HandlerResult:
        """Handle DELETE /api/integrations/make/connections/:id - delete."""
        # Check RBAC permission
        perm_error = self._check_permission(handler, "connectors.delete", conn_id)
        if perm_error:
            return perm_error

        make = self._get_make()

        if make.delete_connection(conn_id):
            auth_ctx = self._get_auth_context(handler)
            user_id = auth_ctx.user_id if auth_ctx else "system"
            audit_data(
                user_id=user_id,
                resource_type="make_connection",
                resource_id=conn_id,
                action="delete",
            )
            return json_response({"deleted": True, "connection_id": conn_id})
        else:
            return error_response(
                f"Make connection not found: {conn_id}", 404, code="MAKE_CONNECTION_NOT_FOUND"
            )

    @api_endpoint(
        method="POST",
        path="/api/v1/integrations/make/webhooks",
        summary="Register Make webhook",
        tags=["Integrations"],
    )
    def _handle_register_make_webhook(self, body: dict, handler: Any) -> HandlerResult:
        """Handle POST /api/integrations/make/webhooks - register webhook."""
        # Check RBAC permission - registering webhooks exposes external URLs
        perm_error = self._check_permission(handler, "connectors.create")
        if perm_error:
            return perm_error

        conn_id, field_error = self._require_string_field(
            body, "connection_id", "MISSING_CONNECTION_ID", "INVALID_CONNECTION_ID"
        )
        if field_error:
            return field_error
        module_type, field_error = self._require_string_field(
            body, "module_type", "MISSING_MODULE_TYPE", "INVALID_MODULE_TYPE"
        )
        if field_error:
            return field_error
        webhook_url, field_error = self._require_string_field(
            body, "webhook_url", "MISSING_WEBHOOK_URL", "INVALID_WEBHOOK_URL"
        )
        if field_error:
            return field_error
        workspace_id, field_error = self._optional_string_field(
            body, "workspace_id", "INVALID_WORKSPACE_ID"
        )
        if field_error:
            return field_error
        event_filter, field_error = self._optional_object_field(
            body, "event_filter", "INVALID_EVENT_FILTER"
        )
        if field_error:
            return field_error

        is_valid, url_error = validate_webhook_url(webhook_url, allow_localhost=False)
        if not is_valid:
            return error_response(f"Invalid webhook URL: {url_error}", 400)

        make = self._get_make()
        webhook = make.register_webhook(
            conn_id=conn_id,
            module_type=module_type,
            webhook_url=webhook_url,
            workspace_id=workspace_id,
            event_filter=event_filter,
        )

        if webhook:
            return json_response(
                {
                    "webhook": {
                        "id": webhook.id,
                        "module_type": webhook.module_type,
                        "webhook_url": webhook.webhook_url,
                        "created_at": webhook.created_at,
                    }
                },
                status=201,
            )
        else:
            return error_response("Failed to register webhook", 400, code="WEBHOOK_REGISTER_FAILED")

    @api_endpoint(
        method="DELETE",
        path="/api/v1/integrations/make/webhooks/{webhook_id}",
        summary="Unregister Make webhook",
        tags=["Integrations"],
    )
    def _handle_unregister_make_webhook(
        self, conn_id: str, webhook_id: str, handler: Any
    ) -> HandlerResult:
        """Handle DELETE /api/integrations/make/webhooks/:id - unregister."""
        # Check RBAC permission
        perm_error = self._check_permission(handler, "connectors.delete", webhook_id)
        if perm_error:
            return perm_error

        if not conn_id:
            return error_response(
                "connection_id query parameter is required", 400, code="MISSING_CONNECTION_ID"
            )

        make = self._get_make()

        if make.unregister_webhook(conn_id, webhook_id):
            return json_response({"deleted": True, "webhook_id": webhook_id})
        else:
            return error_response(f"Webhook not found: {webhook_id}", 404, code="WEBHOOK_NOT_FOUND")

    # =========================================================================
    # n8n Handlers
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/integrations/n8n/credentials",
        summary="List n8n credentials",
        tags=["Integrations"],
    )
    def _handle_list_n8n_credentials(
        self, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult:
        """Handle GET /api/integrations/n8n/credentials - list credentials."""
        # Check RBAC permission
        perm_error = self._check_permission(handler, "connectors.read")
        if perm_error:
            return perm_error

        workspace_id, field_error = self._optional_query_string_param(
            query_params, "workspace_id", "INVALID_WORKSPACE_ID"
        )
        if field_error:
            return field_error

        n8n = self._get_n8n()
        credentials = n8n.list_credentials(workspace_id)

        return json_response(
            {
                "credentials": [
                    {
                        "id": cred.id,
                        "workspace_id": cred.workspace_id,
                        "api_url": cred.api_url,
                        "created_at": cred.created_at,
                        "active": cred.active,
                        "operation_count": cred.operation_count,
                        "webhooks_count": len(cred.webhooks),
                    }
                    for cred in credentials
                ],
                "count": len(credentials),
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/integrations/n8n/nodes",
        summary="Get n8n node definitions",
        tags=["Integrations"],
    )
    def _handle_get_n8n_nodes(self, handler: Any) -> HandlerResult:
        """Handle GET /api/integrations/n8n/nodes - get node definitions."""
        # Check RBAC permission
        perm_error = self._check_permission(handler, "connectors.read")
        if perm_error:
            return perm_error

        n8n = self._get_n8n()

        return json_response(
            {
                "node": n8n.get_node_definition(),
                "trigger": n8n.get_trigger_node_definition(),
                "credential": n8n.get_credential_definition(),
                "events": n8n.EVENT_TYPES,
            }
        )

    @api_endpoint(
        method="POST",
        path="/api/v1/integrations/n8n/credentials",
        summary="Create n8n credential",
        tags=["Integrations"],
    )
    def _handle_create_n8n_credential(self, body: dict, handler: Any) -> HandlerResult:
        """Handle POST /api/integrations/n8n/credentials - create credential."""
        # Check RBAC permission - creating credentials exposes API keys
        perm_error = self._check_permission(handler, "connectors.create")
        if perm_error:
            return perm_error

        workspace_id, field_error = self._require_string_field(
            body, "workspace_id", "MISSING_WORKSPACE_ID", "INVALID_WORKSPACE_ID"
        )
        if field_error:
            return field_error

        api_url, field_error = self._optional_string_field(
            body,
            "api_url",
            "INVALID_API_URL",
            allow_empty_string=True,
        )
        if field_error:
            return field_error
        if api_url is not None:
            is_valid, url_error = validate_webhook_url(api_url, allow_localhost=False)
            if not is_valid:
                return error_response(f"Invalid api_url: {url_error}", 400)

        n8n = self._get_n8n()
        credential = n8n.create_credential(
            workspace_id=workspace_id,
            api_url=api_url,
        )

        auth_ctx = self._get_auth_context(handler)
        user_id = auth_ctx.user_id if auth_ctx else "system"
        audit_data(
            user_id=user_id,
            resource_type="n8n_credential",
            resource_id=credential.id,
            action="create",
            workspace_id=workspace_id,
        )

        return json_response(
            {
                "credential": {
                    "id": credential.id,
                    "workspace_id": credential.workspace_id,
                    "api_key": credential.api_key,
                    "api_url": credential.api_url,
                    "created_at": credential.created_at,
                },
                "message": "n8n credential created. Save the api_key - it won't be shown again.",
            },
            status=201,
        )

    @api_endpoint(
        method="DELETE",
        path="/api/v1/integrations/n8n/credentials/{credential_id}",
        summary="Delete n8n credential",
        tags=["Integrations"],
    )
    def _handle_delete_n8n_credential(self, cred_id: str, handler: Any) -> HandlerResult:
        """Handle DELETE /api/integrations/n8n/credentials/:id - delete."""
        # Check RBAC permission
        perm_error = self._check_permission(handler, "connectors.delete", cred_id)
        if perm_error:
            return perm_error

        n8n = self._get_n8n()

        if n8n.delete_credential(cred_id):
            auth_ctx = self._get_auth_context(handler)
            user_id = auth_ctx.user_id if auth_ctx else "system"
            audit_data(
                user_id=user_id,
                resource_type="n8n_credential",
                resource_id=cred_id,
                action="delete",
            )
            return json_response({"deleted": True, "credential_id": cred_id})
        else:
            return error_response(
                f"n8n credential not found: {cred_id}", 404, code="N8N_CREDENTIAL_NOT_FOUND"
            )

    @api_endpoint(
        method="POST",
        path="/api/v1/integrations/n8n/webhooks",
        summary="Register n8n webhook",
        tags=["Integrations"],
    )
    def _handle_register_n8n_webhook(self, body: dict, handler: Any) -> HandlerResult:
        """Handle POST /api/integrations/n8n/webhooks - register webhook."""
        # Check RBAC permission - registering webhooks creates external endpoints
        perm_error = self._check_permission(handler, "connectors.create")
        if perm_error:
            return perm_error

        cred_id, field_error = self._require_string_field(
            body, "credential_id", "MISSING_CREDENTIAL_ID", "INVALID_CREDENTIAL_ID"
        )
        if field_error:
            return field_error
        events, field_error = self._require_string_list_field(
            body, "events", "MISSING_EVENTS", "INVALID_EVENTS"
        )
        if field_error:
            return field_error
        workflow_id, field_error = self._optional_string_field(
            body, "workflow_id", "INVALID_WORKFLOW_ID"
        )
        if field_error:
            return field_error
        node_id, field_error = self._optional_string_field(body, "node_id", "INVALID_NODE_ID")
        if field_error:
            return field_error
        workspace_id, field_error = self._optional_string_field(
            body, "workspace_id", "INVALID_WORKSPACE_ID"
        )
        if field_error:
            return field_error

        n8n = self._get_n8n()
        webhook = n8n.register_webhook(
            cred_id=cred_id,
            events=events,
            workflow_id=workflow_id,
            node_id=node_id,
            workspace_id=workspace_id,
        )

        if webhook:
            return json_response(
                {
                    "webhook": {
                        "id": webhook.id,
                        "webhook_path": webhook.webhook_path,
                        "events": webhook.events,
                        "created_at": webhook.created_at,
                    }
                },
                status=201,
            )
        else:
            return error_response("Failed to register webhook", 400, code="WEBHOOK_REGISTER_FAILED")

    @api_endpoint(
        method="DELETE",
        path="/api/v1/integrations/n8n/webhooks/{webhook_id}",
        summary="Unregister n8n webhook",
        tags=["Integrations"],
    )
    def _handle_unregister_n8n_webhook(
        self, cred_id: str, webhook_id: str, handler: Any
    ) -> HandlerResult:
        """Handle DELETE /api/integrations/n8n/webhooks/:id - unregister."""
        # Check RBAC permission
        perm_error = self._check_permission(handler, "connectors.delete", webhook_id)
        if perm_error:
            return perm_error

        if not cred_id:
            return error_response(
                "credential_id query parameter is required", 400, code="MISSING_CREDENTIAL_ID"
            )

        n8n = self._get_n8n()

        if n8n.unregister_webhook(cred_id, webhook_id):
            return json_response({"deleted": True, "webhook_id": webhook_id})
        else:
            return error_response(f"Webhook not found: {webhook_id}", 404, code="WEBHOOK_NOT_FOUND")

    # =========================================================================
    # Test Handler
    # =========================================================================

    @api_endpoint(
        method="POST",
        path="/api/v1/integrations/{platform}/test",
        summary="Test integration connection",
        tags=["Integrations"],
    )
    def _handle_test_integration(self, platform: str, handler: Any) -> HandlerResult:
        """Handle POST /api/integrations/:platform/test - test integration."""
        # Check RBAC permission - testing requires read access
        perm_error = self._check_permission(handler, "connectors.read")
        if perm_error:
            return perm_error

        if platform == "zapier":
            zapier = self._get_zapier()
            return json_response(
                {
                    "platform": "zapier",
                    "status": "ok",
                    "apps_count": len(zapier._apps),
                    "trigger_types": list(zapier.TRIGGER_TYPES.keys()),
                    "action_types": list(zapier.ACTION_TYPES.keys()),
                }
            )

        elif platform == "make":
            make = self._get_make()
            return json_response(
                {
                    "platform": "make",
                    "status": "ok",
                    "connections_count": len(make._connections),
                    "module_types": list(make.MODULE_TYPES.keys()),
                }
            )

        elif platform == "n8n":
            n8n = self._get_n8n()
            return json_response(
                {
                    "platform": "n8n",
                    "status": "ok",
                    "credentials_count": len(n8n._credentials),
                    "event_types": list(n8n.EVENT_TYPES.keys()),
                }
            )

        else:
            return error_response(f"Unknown platform: {platform}", 400, code="UNKNOWN_PLATFORM")


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "ExternalIntegrationsHandler",
]
