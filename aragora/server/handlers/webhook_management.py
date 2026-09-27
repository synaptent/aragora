"""
Webhook API Handler.

Provides REST API endpoints for webhook management:
- POST   /api/webhooks              - Register a new webhook
- GET    /api/webhooks              - List registered webhooks
- GET    /api/webhooks/:id          - Get specific webhook
- DELETE /api/webhooks/:id          - Delete a webhook
- POST   /api/webhooks/:id/test     - Send a test event to webhook
- GET    /api/webhooks/events       - List available event types

Webhooks receive HTTP POST requests when subscribed events occur.
All webhook payloads include HMAC-SHA256 signatures for verification.

Webhook configurations are persisted to SQLite (default) or Redis+SQLite for
multi-instance deployments. This ensures webhooks survive server restarts.
"""

from __future__ import annotations

import hmac
import logging
import time
import warnings
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from aragora.security.webhook_signing import generate_signature as _generate_signature
from aragora.server.handlers.base import (
    SAFE_ID_PATTERN,
    error_response,
    json_response,
    handle_errors,
)
from aragora.server.handlers.openapi_decorator import api_endpoint, path_param, query_param
from aragora.server.handlers.utils.rate_limit import RateLimiter, get_client_ip
from aragora.server.handlers.utils.responses import HandlerResult
from aragora.server.handlers.secure import SecureHandler
from aragora.server.handlers.utils.url_security import validate_webhook_url
from aragora.server.validation.query_params import safe_query_int

if TYPE_CHECKING:
    from aragora.rbac import AuthorizationContext

# RBAC imports - graceful fallback if not available
_AuthorizationContext: Any = None
check_permission: Any = None
try:
    import aragora.rbac as _rbac
except ImportError:
    RBAC_AVAILABLE = False
else:
    try:
        _AuthorizationContext = _rbac.AuthorizationContext
        check_permission = _rbac.check_permission
    except AttributeError:
        RBAC_AVAILABLE = False
    else:
        RBAC_AVAILABLE = True

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

# Import durable storage from storage module
from aragora.storage.webhook_config_store import (
    WEBHOOK_EVENTS,
    WebhookConfig,
    WebhookConfigStoreBackend,
    get_webhook_config_store,
)

# Unified audit logging
try:
    from aragora.audit.unified import audit_data

    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False
    audit_data = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Rate limits for webhook operations
WEBHOOK_REGISTER_RPM = 10  # Max 10 webhook registrations per minute
WEBHOOK_TEST_RPM = 5  # Max 5 test deliveries per minute
WEBHOOK_LIST_RPM = 60  # Max 60 list operations per minute

# Rate limiter instances
_register_limiter = RateLimiter(requests_per_minute=WEBHOOK_REGISTER_RPM)
_test_limiter = RateLimiter(requests_per_minute=WEBHOOK_TEST_RPM)
_list_limiter = RateLimiter(requests_per_minute=WEBHOOK_LIST_RPM)

# Backward compatibility alias - the old WebhookStore interface is now provided
# by WebhookConfigStoreBackend from aragora.storage.webhook_config_store
WebhookStore: TypeAlias = WebhookConfigStoreBackend


def get_webhook_store() -> WebhookConfigStoreBackend:
    """Get or create the webhook store.

    Returns a durable storage backend (SQLite by default, Redis+SQLite for
    multi-instance deployments). Webhooks survive server restarts.

    Configure via environment:
    - ARAGORA_WEBHOOK_CONFIG_STORE_BACKEND: "sqlite" (default), "redis", or "memory"
    - ARAGORA_DATA_DIR: Directory for SQLite database
    - ARAGORA_REDIS_URL: Redis connection URL (for redis backend)
    """
    return get_webhook_config_store()


# =============================================================================
# Webhook Signature Utilities
# =============================================================================


def generate_signature(payload: str, secret: str) -> str:
    """Deprecated compatibility wrapper for the shared webhook signer."""
    warnings.warn(
        "aragora.server.handlers.webhooks.generate_signature is deprecated; "
        "use aragora.security.webhook_signing.generate_signature instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _generate_signature(payload, secret)


def verify_signature(payload: str, signature: str, secret: str) -> bool:
    """
    Verify webhook signature.

    Args:
        payload: JSON string payload
        signature: Signature header value (sha256=...)
        secret: Webhook secret key

    Returns:
        True if signature is valid
    """
    expected = _generate_signature(payload, secret)
    return hmac.compare_digest(signature, expected)


# =============================================================================
# Webhook Handler
# =============================================================================


class WebhookHandler(SecureHandler):
    """Handler for webhook management API endpoints.

    Extends SecureHandler for JWT-based authentication, RBAC permission
    enforcement, and security audit logging.
    """

    # Resource type for audit logging
    RESOURCE_TYPE = "webhook"

    # Routes this handler responds to
    routes = [
        "POST /api/webhooks",
        "GET /api/webhooks",
        "GET /api/webhooks/events",
        "GET /api/webhooks/slo/status",
        "POST /api/webhooks/slo/test",
        "GET /api/webhooks/:id",
        "DELETE /api/webhooks/:id",
        "PATCH /api/webhooks/:id",
        "POST /api/webhooks/:id/test",
        # Dead-letter queue endpoints
        "GET /api/webhooks/dead-letter",
        "GET /api/webhooks/dead-letter/:id",
        "POST /api/webhooks/dead-letter/:id/retry",
        "DELETE /api/webhooks/dead-letter/:id",
        "GET /api/webhooks/queue/stats",
    ]

    ROUTES = [
        "/api/v1/webhooks",
        "/api/v1/webhooks/events",
        "/api/v1/webhooks/events/categories",
        "/api/v1/webhooks/slo/status",
        "/api/v1/webhooks/slo/test",
        "/api/v1/webhooks/dead-letter",
        "/api/v1/webhooks/queue/stats",
        "/api/v1/webhooks/bulk",
        "/api/v1/webhooks/pause-all",
        "/api/v1/webhooks/resume-all",
    ]

    @staticmethod
    def _normalize_path(path: str) -> str:
        if path == "/api/v1/webhook-configs" or path.startswith("/api/v1/webhook-configs/"):
            return path.replace("/api/v1/webhook-configs", "/api/v1/webhooks", 1)
        return path

    @staticmethod
    def can_handle(path: str) -> bool:
        """Check if this handler can handle the given path."""
        return (
            path.startswith("/api/v1/webhooks")
            or path == "/api/v1/webhook-configs"
            or path.startswith("/api/v1/webhook-configs/")
        )

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        self._webhook_store: WebhookStore | None = None

    def _get_webhook_store(self) -> WebhookStore:
        """Get or create webhook store instance."""
        if self._webhook_store is None:
            if "webhook_store" in self.ctx:
                self._webhook_store = self.ctx["webhook_store"]
            else:
                self._webhook_store = get_webhook_store()
                self.ctx["webhook_store"] = self._webhook_store
        return self._webhook_store

    def _get_auth_context(self, handler) -> AuthorizationContext | None:
        """Build RBAC authorization context from request."""
        if not RBAC_AVAILABLE or _AuthorizationContext is None:
            return None

        user = self.get_current_user(handler)
        if not user:
            return None

        # User context has user_id and potentially role info
        return _AuthorizationContext(
            user_id=user.user_id,
            roles=set([user.role]) if hasattr(user, "role") and user.role else set(),
            org_id=getattr(user, "org_id", None),
        )

    def _check_rbac_permission(self, handler, permission_key: str) -> HandlerResult | None:
        """
        Check RBAC permission.

        Returns None if allowed, or an error response if denied.
        """
        _user, auth_error = self.require_auth_or_error(handler)
        if auth_error:
            return auth_error

        if not RBAC_AVAILABLE:
            if rbac_fail_closed():
                return error_response("Service unavailable: access control module not loaded", 503)
            return None

        rbac_ctx = self._get_auth_context(handler)
        if not rbac_ctx:
            return error_response("Authentication required", 401)

        decision = check_permission(rbac_ctx, permission_key)
        if not decision.allowed:
            logger.warning(
                "RBAC denied: user=%s permission=%s reason=%s",
                rbac_ctx.user_id,
                permission_key,
                decision.reason,
            )
            return error_response(
                "Permission denied",
                403,
            )

        return None

    @staticmethod
    def _is_webhook_access_denied(webhook: WebhookConfig, user: Any | None) -> bool:
        """Check whether the authenticated requester may access this webhook."""
        if user is None:
            return True
        # Fail closed on orphaned rows: without either an owning user or an
        # owning workspace, the record has no legitimate caller-scoped owner.
        if not webhook.user_id and not webhook.workspace_id:
            return True
        user_id = str(getattr(user, "user_id", "") or "").strip()
        org_id = str(getattr(user, "org_id", "") or "").strip()
        if webhook.user_id and webhook.user_id != user_id:
            return True
        if webhook.workspace_id and (not org_id or webhook.workspace_id != org_id):
            return True
        return False

    @staticmethod
    def _should_hide_webhook_access(webhook: WebhookConfig, user: Any | None) -> bool:
        """Return True when access should fail closed as not-found.

        Workspace-scoped or ownerless records should not reveal whether they exist
        outside the caller's org context. Explicit user ownership mismatches keep
        the older forbidden response.
        """
        if not webhook.user_id and not webhook.workspace_id:
            return True
        if user is None:
            return False
        org_id = str(getattr(user, "org_id", "") or "").strip()
        return bool(webhook.workspace_id and (not org_id or webhook.workspace_id != org_id))

    @staticmethod
    def _forbidden_webhook_access() -> HandlerResult:
        """Hide non-owned webhook records to avoid cross-tenant leaks."""
        return error_response("Webhook not found", 404)

    @classmethod
    def _webhook_access_denied_response(
        cls, webhook: WebhookConfig, user: Any | None
    ) -> HandlerResult:
        """Return the correct fail-closed response for a denied webhook read/write."""
        if cls._should_hide_webhook_access(webhook, user):
            return error_response("Webhook not found", 404)
        return cls._forbidden_webhook_access()

    @staticmethod
    def _parse_events_field(raw_events: Any) -> list[str] | None:
        """Normalize webhook events while rejecting malformed non-list payloads."""
        if not isinstance(raw_events, (list, tuple, set)):
            return None
        events: list[str] = []
        for raw_event in raw_events:
            if not isinstance(raw_event, str):
                return None
            event = raw_event.strip()
            if not event:
                return None
            events.append(event)
        return events

    @staticmethod
    def _parse_optional_text_field(raw_value: Any, field_name: str) -> str | None:
        """Normalize optional text fields while rejecting malformed non-string payloads."""
        if raw_value is None:
            return None
        if not isinstance(raw_value, str):
            raise ValueError(f"{field_name} must be a string")
        return raw_value.strip()

    @api_endpoint(
        path="/api/v1/webhooks",
        method="GET",
        summary="List registered webhooks",
        tags=["Webhooks"],
        operation_id="listRegisteredWebhooks",
        description="Retrieve all webhooks registered by the authenticated user. Supports filtering by active status.",
        parameters=[
            query_param(
                "active_only",
                "Filter to only active webhooks",
                schema_type="boolean",
                required=False,
                default=False,
            ),
        ],
        responses={
            "200": {
                "description": "List of webhooks",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "webhooks": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "url": {"type": "string", "format": "uri"},
                                            "events": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                            "name": {"type": "string"},
                                            "active": {"type": "boolean"},
                                            "created_at": {"type": "string", "format": "date-time"},
                                        },
                                    },
                                },
                                "count": {"type": "integer"},
                            },
                        },
                    },
                },
            },
            "429": {"description": "Rate limit exceeded"},
        },
        auth_required=True,
    )
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle GET requests for webhook endpoints."""
        path = self._normalize_path(path)
        # GET /api/webhooks/events - list available event types
        if path == "/api/v1/webhooks/events":
            return self._handle_list_events(handler)

        # GET /api/webhooks/slo/status - get SLO webhook status
        if path == "/api/v1/webhooks/slo/status":
            return self._handle_slo_status(handler)

        # GET /api/webhooks/dead-letter - list dead-letter queue
        if path == "/api/v1/webhooks/dead-letter":
            return await self._handle_list_dead_letters(query_params, handler)

        # GET /api/webhooks/dead-letter/:id - get specific dead-letter delivery
        if path.startswith("/api/v1/webhooks/dead-letter/") and not path.endswith("/retry"):
            delivery_id, err = self.extract_path_param(path, 5, "delivery_id", SAFE_ID_PATTERN)
            if err:
                return err
            return await self._handle_get_dead_letter(cast(str, delivery_id), handler)

        # GET /api/webhooks/queue/stats - get queue statistics
        if path == "/api/v1/webhooks/queue/stats":
            return await self._handle_queue_stats(handler)

        # GET /api/webhooks/:id
        if path.startswith("/api/v1/webhooks/") and path.count("/") == 4:
            webhook_id, err = self.extract_path_param(path, 4, "webhook_id", SAFE_ID_PATTERN)
            if err:
                return err
            return self._handle_get_webhook(cast(str, webhook_id), handler)

        # GET /api/webhooks - list all webhooks
        if path == "/api/v1/webhooks":
            return self._handle_list_webhooks(query_params, handler)

        return None

    @handle_errors("webhook creation")
    @api_endpoint(
        path="/api/v1/webhooks",
        method="POST",
        summary="Register a new webhook",
        tags=["Webhooks"],
        operation_id="registerWebhook",
        description="""Register a new webhook to receive HTTP POST notifications when subscribed events occur.
All webhook payloads include HMAC-SHA256 signatures for verification.
The webhook secret is only returned once on creation - save it securely.""",
        request_body={
            "description": "Webhook configuration",
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["url", "events"],
                        "properties": {
                            "url": {
                                "type": "string",
                                "format": "uri",
                                "description": "HTTPS URL to receive webhook events",
                            },
                            "events": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Event types to subscribe to (use '*' for all events)",
                            },
                            "name": {"type": "string", "description": "Optional webhook name"},
                            "description": {
                                "type": "string",
                                "description": "Optional description",
                            },
                        },
                    },
                },
            },
        },
        responses={
            "201": {
                "description": "Webhook created successfully",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "webhook": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "url": {"type": "string"},
                                        "events": {"type": "array", "items": {"type": "string"}},
                                        "secret": {
                                            "type": "string",
                                            "description": "HMAC secret (only shown once)",
                                        },
                                    },
                                },
                                "message": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "400": {
                "description": "Invalid request (missing URL, invalid events, or SSRF protection triggered)"
            },
            "429": {"description": "Rate limit exceeded"},
        },
        auth_required=True,
    )
    @handle_errors
    async def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests for webhook endpoints."""
        path = self._normalize_path(path)
        # POST /api/webhooks/slo/test - send test SLO violation notification
        if path == "/api/v1/webhooks/slo/test":
            return self._handle_slo_test(handler)

        # POST /api/webhooks/dead-letter/:id/retry - retry dead-letter delivery
        if path.endswith("/retry") and "/dead-letter/" in path:
            delivery_id, err = self.extract_path_param(path, 5, "delivery_id", SAFE_ID_PATTERN)
            if err:
                return err
            return await self._handle_retry_dead_letter(cast(str, delivery_id), handler)

        # POST /api/v1/webhooks/:id/test
        if path.endswith("/test") and path.count("/") == 5:
            webhook_id, err = self.extract_path_param(path, 4, "webhook_id", SAFE_ID_PATTERN)
            if err:
                return err
            return self._handle_test_webhook(cast(str, webhook_id), handler)

        # POST /api/webhooks - register new webhook
        if path == "/api/v1/webhooks":
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_register_webhook(cast(dict[str, Any], body), handler)

        return None

    @handle_errors("webhook deletion")
    @api_endpoint(
        path="/api/v1/webhooks/{webhook_id}",
        method="DELETE",
        summary="Delete a webhook",
        tags=["Webhooks"],
        operation_id="deleteRegisteredWebhook",
        description="Remove a registered webhook. Only the webhook owner can delete it.",
        parameters=[
            path_param("webhook_id", "The webhook ID to delete"),
        ],
        responses={
            "200": {
                "description": "Webhook deleted",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "deleted": {"type": "boolean"},
                                "webhook_id": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "403": {"description": "Access denied - not the webhook owner"},
            "404": {"description": "Webhook not found"},
        },
        auth_required=True,
    )
    @handle_errors
    async def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle DELETE requests for webhook endpoints."""
        path = self._normalize_path(path)
        # DELETE /api/webhooks/dead-letter/:id - remove from dead-letter queue
        if "/dead-letter/" in path:
            delivery_id, err = self.extract_path_param(path, 5, "delivery_id", SAFE_ID_PATTERN)
            if err:
                return err
            return await self._handle_delete_dead_letter(cast(str, delivery_id), handler)

        # DELETE /api/webhooks/:id
        if path.startswith("/api/v1/webhooks/") and path.count("/") == 4:
            webhook_id, err = self.extract_path_param(path, 4, "webhook_id", SAFE_ID_PATTERN)
            if err:
                return err
            return self._handle_delete_webhook(cast(str, webhook_id), handler)

        return None

    @handle_errors("webhook modification")
    def handle_patch(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle PATCH requests for webhook endpoints."""
        path = self._normalize_path(path)
        # PATCH /api/webhooks/:id
        if path.startswith("/api/v1/webhooks/") and path.count("/") == 4:
            webhook_id, err = self.extract_path_param(path, 4, "webhook_id", SAFE_ID_PATTERN)
            if err:
                return err
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_update_webhook(
                cast(str, webhook_id), cast(dict[str, Any], body), handler
            )

        return None

    # =========================================================================
    # Handler Methods
    # =========================================================================

    def _handle_list_events(self, handler: Any = None) -> HandlerResult:
        """Handle GET /api/webhooks/events - list available event types."""
        # RBAC permission check (read access for event types)
        if handler:
            rbac_error = self._check_rbac_permission(handler, "webhooks.read")
            if rbac_error:
                return rbac_error

        events = sorted(WEBHOOK_EVENTS)
        return json_response(
            {
                "events": events,
                "count": len(events),
                "description": {
                    "debate_start": "Fired when a debate begins",
                    "debate_end": "Fired when a debate completes",
                    "consensus": "Fired when consensus is reached",
                    "round_start": "Fired at the start of each debate round",
                    "agent_message": "Fired when an agent sends a message",
                    "vote": "Fired when a vote is cast",
                    "insight_extracted": "Fired when a new insight is extracted",
                    "memory_stored": "Fired when memory is stored",
                    "memory_retrieved": "Fired when memory is retrieved",
                    "claim_verification_result": "Fired when a claim is verified",
                    "formal_verification_result": "Fired when formal verification completes",
                    "gauntlet_complete": "Fired when gauntlet stress-test completes",
                    "gauntlet_verdict": "Fired when gauntlet verdict is determined",
                    "receipt_ready": "Fired when a receipt is ready",
                    "receipt_exported": "Fired when a receipt is exported",
                    "graph_branch_created": "Fired when a graph debate branches",
                    "graph_branch_merged": "Fired when graph branches merge",
                    "genesis_evolution": "Fired when agent population evolves",
                    "breakpoint": "Fired when a human intervention breakpoint triggers",
                    "breakpoint_resolved": "Fired when a breakpoint is resolved",
                    "agent_elo_updated": "Fired when agent ELO rating is updated",
                    "knowledge_indexed": "Fired when knowledge is indexed",
                    "knowledge_queried": "Fired when knowledge is queried",
                    "mound_updated": "Fired when knowledge mound is updated",
                    "calibration_update": "Fired when calibration data is updated",
                    "evidence_found": "Fired when evidence is found",
                    "agent_calibration_changed": "Fired when agent calibration changes",
                    "agent_fallback_triggered": "Fired when agent fallback is triggered",
                    "explanation_ready": "Fired when an explanation is ready",
                },
            }
        )

    def _handle_list_webhooks(self, query_params: dict, handler: Any) -> HandlerResult:
        """Handle GET /api/webhooks - list all webhooks."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _list_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for webhook list: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "webhooks.read")
        if rbac_error:
            return rbac_error

        # Get optional user context for filtering
        user = self.get_current_user(handler)
        user_id = user.user_id if user else None

        active_only = query_params.get("active_only", ["false"])[0].lower() == "true"

        store = self._get_webhook_store()
        webhooks = store.list(user_id=user_id, active_only=active_only)
        webhooks = [
            webhook for webhook in webhooks if not self._is_webhook_access_denied(webhook, user)
        ]

        return json_response(
            {
                "webhooks": [w.to_dict(include_secret=False) for w in webhooks],
                "count": len(webhooks),
            }
        )

    def _handle_get_webhook(self, webhook_id: str, handler: Any) -> HandlerResult:
        """Handle GET /api/webhooks/:id - get specific webhook."""
        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "webhooks.read")
        if rbac_error:
            return rbac_error

        store = self._get_webhook_store()
        webhook = store.get(webhook_id)

        if not webhook:
            return error_response(f"Webhook not found: {webhook_id}", 404)

        # Check ownership
        user = self.get_current_user(handler)
        if self._is_webhook_access_denied(webhook, user):
            return self._webhook_access_denied_response(webhook, user)

        return json_response({"webhook": webhook.to_dict(include_secret=False)})

    def _handle_register_webhook(self, body: dict, handler: Any) -> HandlerResult:
        """Handle POST /api/webhooks - register new webhook."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _register_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for webhook registration: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "webhooks.create")
        if rbac_error:
            return rbac_error

        raw_url = body.get("url", "")
        if not isinstance(raw_url, str):
            return error_response("URL must be a non-empty string", 400)
        url = raw_url.strip()
        if not url:
            return error_response("URL must be a non-empty string", 400)

        # Validate URL format and check for SSRF
        is_valid, error_msg = validate_webhook_url(url, allow_localhost=False)
        if not is_valid:
            return error_response(f"Invalid webhook URL: {error_msg}", 400)

        events = self._parse_events_field(body.get("events", []))
        if events is None:
            return error_response("Events must be a list of strings", 400)
        if not events:
            return error_response("At least one event type is required", 400)

        # Validate events
        invalid_events = [e for e in events if e != "*" and e not in WEBHOOK_EVENTS]
        if invalid_events:
            return error_response(
                f"Invalid event types: {', '.join(invalid_events)}. "
                f"Use GET /api/webhooks/events for available types.",
                400,
            )

        # Get user context
        user = self.get_current_user(handler)
        user_id = user.user_id if user else None
        try:
            name = self._parse_optional_text_field(body.get("name"), "Name")
            description = self._parse_optional_text_field(body.get("description"), "Description")
        except ValueError as exc:
            return error_response(str(exc), 400)

        store = self._get_webhook_store()
        webhook = store.register(
            url=url,
            events=events,
            name=name,
            description=description,
            user_id=user_id,
            workspace_id=getattr(user, "org_id", None),
        )

        # Audit log: webhook created
        if AUDIT_AVAILABLE and audit_data:
            audit_data(
                user_id=user_id or "anonymous",
                resource_type="webhook",
                resource_id=webhook.id,
                action="create",
                events=events,
            )

        # Return with secret (only on creation)
        return json_response(
            {
                "webhook": webhook.to_dict(include_secret=True),
                "message": "Webhook registered successfully. Save the secret - it won't be shown again.",
            },
            status=201,
        )

    def _handle_delete_webhook(self, webhook_id: str, handler: Any) -> HandlerResult:
        """Handle DELETE /api/webhooks/:id - delete webhook."""
        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "webhooks.delete")
        if rbac_error:
            return rbac_error

        store = self._get_webhook_store()
        webhook = store.get(webhook_id)

        if not webhook:
            return error_response(f"Webhook not found: {webhook_id}", 404)

        # Check ownership
        user = self.get_current_user(handler)
        if self._is_webhook_access_denied(webhook, user):
            return self._webhook_access_denied_response(webhook, user)

        store.delete(webhook_id)

        # Audit log: webhook deleted
        if AUDIT_AVAILABLE and audit_data:
            audit_data(
                user_id=cast(str, user.user_id) if user else "anonymous",
                resource_type="webhook",
                resource_id=webhook_id,
                action="delete",
            )

        return json_response(
            {
                "deleted": True,
                "webhook_id": webhook_id,
            }
        )

    def _handle_update_webhook(self, webhook_id: str, body: dict, handler: Any) -> HandlerResult:
        """Handle PATCH /api/webhooks/:id - update webhook."""
        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "webhooks.update")
        if rbac_error:
            return rbac_error

        store = self._get_webhook_store()
        webhook = store.get(webhook_id)

        if not webhook:
            return error_response(f"Webhook not found: {webhook_id}", 404)

        # Check ownership
        user = self.get_current_user(handler)
        if self._is_webhook_access_denied(webhook, user):
            return self._webhook_access_denied_response(webhook, user)

        # Validate URL if provided (SSRF check)
        new_url = None
        if "url" in body:
            raw_url = body.get("url")
            if not isinstance(raw_url, str):
                return error_response("URL must be a non-empty string", 400)
            new_url = raw_url.strip()
            if not new_url:
                return error_response("URL must be a non-empty string", 400)
            is_valid, error_msg = validate_webhook_url(new_url, allow_localhost=False)
            if not is_valid:
                return error_response(f"Invalid webhook URL: {error_msg}", 400)

        # Validate events if provided
        events = None
        if "events" in body:
            events = self._parse_events_field(body.get("events"))
            if events is None:
                return error_response("Events must be a list of strings", 400)
            if not events:
                return error_response("At least one event type is required", 400)
        if events is not None:
            invalid_events = [e for e in events if e != "*" and e not in WEBHOOK_EVENTS]
            if invalid_events:
                return error_response(f"Invalid event types: {', '.join(invalid_events)}", 400)

        active = None
        if "active" in body:
            raw_active = body.get("active")
            if not isinstance(raw_active, bool):
                return error_response("Active must be a boolean", 400)
            active = raw_active
        try:
            name = self._parse_optional_text_field(body.get("name"), "Name")
            description = self._parse_optional_text_field(body.get("description"), "Description")
        except ValueError as exc:
            return error_response(str(exc), 400)

        updated = store.update(
            webhook_id=webhook_id,
            url=new_url,
            events=events,
            active=active,
            name=name,
            description=description,
        )

        # Audit log: webhook updated
        if AUDIT_AVAILABLE and audit_data:
            audit_data(
                user_id=cast(str, user.user_id) if user else "anonymous",
                resource_type="webhook",
                resource_id=webhook_id,
                action="update",
            )

        return json_response(
            {"webhook": cast(WebhookConfig, updated).to_dict(include_secret=False)}
        )

    def _handle_test_webhook(self, webhook_id: str, handler: Any) -> HandlerResult:
        """Handle POST /api/webhooks/:id/test - send test event."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _test_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for webhook test: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "webhooks.test")
        if rbac_error:
            return rbac_error

        store = self._get_webhook_store()
        webhook = store.get(webhook_id)

        if not webhook:
            return error_response(f"Webhook not found: {webhook_id}", 404)

        # Check ownership
        user = self.get_current_user(handler)
        if self._is_webhook_access_denied(webhook, user):
            return self._webhook_access_denied_response(webhook, user)

        # Import here to avoid circular dependency
        from aragora.events.dispatcher import dispatch_webhook

        # Create test payload
        test_event = {
            "event": "test",
            "webhook_id": webhook_id,
            "timestamp": time.time(),
            "data": {
                "message": "This is a test webhook delivery",
                "webhook_name": webhook.name or webhook.id,
            },
        }

        # Dispatch synchronously for testing
        success, status_code, error = dispatch_webhook(webhook, test_event)

        if success:
            return json_response(
                {
                    "success": True,
                    "status_code": status_code,
                    "message": "Test webhook delivered successfully",
                }
            )
        else:
            return json_response(
                {
                    "success": False,
                    "status_code": status_code,
                    "error": error,
                    "message": "Test webhook delivery failed",
                },
                status=502,
            )

    def _handle_slo_status(self, handler: Any) -> HandlerResult:
        """Handle GET /api/webhooks/slo/status - get SLO webhook status."""
        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "webhooks.read")
        if rbac_error:
            return rbac_error

        try:
            from aragora.observability.metrics.slo import (
                get_slo_webhook_status,
                get_violation_state,
            )

            webhook_status = get_slo_webhook_status()
            violation_state = get_violation_state()

            # enabled means initialized (callback is set)
            is_enabled = webhook_status.get("enabled", False)

            return json_response(
                {
                    "slo_webhooks": {
                        "enabled": is_enabled,
                        "initialized": is_enabled,  # Same as enabled
                        "config": webhook_status.get("config"),
                        "notifications_sent": webhook_status.get("notifications_sent", 0),
                        "recoveries_sent": webhook_status.get("recoveries_sent", 0),
                    },
                    "violation_state": violation_state,
                    "active_violations": sum(
                        1 for v in violation_state.values() if v.get("in_violation", False)
                    ),
                }
            )
        except ImportError:
            return json_response(
                {
                    "slo_webhooks": {
                        "enabled": False,
                        "initialized": False,
                        "error": "SLO module not available",
                    },
                    "violation_state": {},
                    "active_violations": 0,
                }
            )
        except (KeyError, ValueError, AttributeError, TypeError) as e:
            logger.error("Error getting SLO webhook status: %s", e)
            return error_response("Failed to retrieve SLO status", 500)

    def _handle_slo_test(self, handler: Any) -> HandlerResult:
        """Handle POST /api/webhooks/slo/test - send test SLO violation notification."""
        # RBAC permission check (admin operation)
        rbac_error = self._check_rbac_permission(handler, "webhooks.admin")
        if rbac_error:
            return rbac_error

        try:
            from aragora.observability.metrics.slo import (
                get_slo_webhook_status,
                notify_slo_violation,
            )

            status = get_slo_webhook_status()
            if not status.get("enabled", False):
                return error_response(
                    "SLO webhooks are not enabled. Initialize with init_slo_webhooks() first.",
                    400,
                )

            # Send a test violation notification
            success = notify_slo_violation(
                operation="test_operation",
                percentile="p99",
                latency_ms=1500.0,
                threshold_ms=500.0,
                severity="minor",
                context={"test": True, "message": "This is a test SLO violation notification"},
                cooldown_seconds=0.0,  # Bypass cooldown for test
            )

            if success:
                return json_response(
                    {
                        "success": True,
                        "message": "Test SLO violation notification sent successfully",
                        "details": {
                            "operation": "test_operation",
                            "percentile": "p99",
                            "latency_ms": 1500.0,
                            "threshold_ms": 500.0,
                            "severity": "minor",
                        },
                    }
                )
            else:
                return json_response(
                    {
                        "success": False,
                        "message": "Test SLO violation notification was not sent (may be on cooldown or filtered)",
                    },
                    status=200,
                )

        except ImportError:
            return error_response("SLO module not available", 500)
        except (KeyError, ValueError, AttributeError, TypeError) as e:
            logger.error("Error sending test SLO notification: %s", e)
            return error_response("Test notification failed", 500)

    # =========================================================================
    # Dead-Letter Queue Handlers
    # =========================================================================

    async def _handle_list_dead_letters(self, query_params: dict, handler: Any) -> HandlerResult:
        """Handle GET /api/webhooks/dead-letter - list dead-letter deliveries."""
        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "webhooks.admin")
        if rbac_error:
            return rbac_error

        try:
            from aragora.webhooks.retry_queue import get_retry_queue

            queue = get_retry_queue()
            limit = safe_query_int(query_params, "limit", default=100, min_val=1, max_val=1000)

            dead_letters = await queue.get_dead_letters(limit)

            return json_response(
                {
                    "dead_letters": [d.to_dict() for d in dead_letters],
                    "count": len(dead_letters),
                    "limit": limit,
                }
            )

        except ImportError:
            return error_response("Webhook retry queue not available", 500)
        except (KeyError, ValueError, OSError, TypeError) as e:
            logger.error("Error listing dead letters: %s", e)
            return error_response("Failed to list dead letters", 500)

    async def _handle_get_dead_letter(self, delivery_id: str, handler: Any) -> HandlerResult:
        """Handle GET /api/webhooks/dead-letter/:id - get specific dead-letter delivery."""
        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "webhooks.admin")
        if rbac_error:
            return rbac_error

        try:
            from aragora.webhooks.retry_queue import DeliveryStatus, get_retry_queue

            queue = get_retry_queue()
            delivery = await queue.get_delivery(delivery_id)

            if not delivery:
                return error_response(f"Delivery not found: {delivery_id}", 404)

            if delivery.status != DeliveryStatus.DEAD_LETTER:
                return error_response(f"Delivery {delivery_id} is not in dead-letter queue", 400)

            return json_response({"delivery": delivery.to_dict()})

        except ImportError:
            return error_response("Webhook retry queue not available", 500)
        except (KeyError, ValueError, OSError, TypeError) as e:
            logger.error("Error getting dead letter: %s", e)
            return error_response("Failed to retrieve dead letter", 500)

    async def _handle_retry_dead_letter(self, delivery_id: str, handler: Any) -> HandlerResult:
        """Handle POST /api/webhooks/dead-letter/:id/retry - retry dead-letter delivery."""
        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "webhooks.admin")
        if rbac_error:
            return rbac_error

        try:
            from aragora.webhooks.retry_queue import get_retry_queue

            queue = get_retry_queue()
            success = await queue.retry_dead_letter(delivery_id)

            if not success:
                return error_response(
                    f"Delivery {delivery_id} not found or not in dead-letter queue", 404
                )

            # Audit log
            user = self.get_current_user(handler)
            if AUDIT_AVAILABLE and audit_data:
                audit_data(
                    user_id=cast(str, user.user_id) if user else "anonymous",
                    resource_type="webhook_delivery",
                    resource_id=delivery_id,
                    action="retry",
                )

            return json_response(
                {
                    "success": True,
                    "delivery_id": delivery_id,
                    "message": "Delivery queued for retry",
                }
            )

        except ImportError:
            return error_response("Webhook retry queue not available", 500)
        except (KeyError, ValueError, OSError, TypeError) as e:
            logger.error("Error retrying dead letter: %s", e)
            return error_response("Dead letter retry failed", 500)

    async def _handle_delete_dead_letter(self, delivery_id: str, handler: Any) -> HandlerResult:
        """Handle DELETE /api/webhooks/dead-letter/:id - remove from dead-letter queue."""
        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "webhooks.admin")
        if rbac_error:
            return rbac_error

        try:
            from aragora.webhooks.retry_queue import get_retry_queue

            queue = get_retry_queue()
            success = await queue.cancel_delivery(delivery_id)

            if not success:
                return error_response(f"Delivery not found: {delivery_id}", 404)

            # Audit log
            user = self.get_current_user(handler)
            if AUDIT_AVAILABLE and audit_data:
                audit_data(
                    user_id=cast(str, user.user_id) if user else "anonymous",
                    resource_type="webhook_delivery",
                    resource_id=delivery_id,
                    action="delete",
                )

            return json_response(
                {
                    "deleted": True,
                    "delivery_id": delivery_id,
                }
            )

        except ImportError:
            return error_response("Webhook retry queue not available", 500)
        except (KeyError, ValueError, OSError, TypeError) as e:
            logger.error("Error deleting dead letter: %s", e)
            return error_response("Dead letter deletion failed", 500)

    async def _handle_queue_stats(self, handler: Any) -> HandlerResult:
        """Handle GET /api/webhooks/queue/stats - get queue statistics."""
        # RBAC permission check (read-only stats can use lower permission)
        rbac_error = self._check_rbac_permission(handler, "webhooks.read")
        if rbac_error:
            return rbac_error

        try:
            from aragora.webhooks.retry_queue import get_retry_queue

            queue = get_retry_queue()
            stats = await queue.get_stats()

            return json_response({"stats": stats})

        except ImportError:
            return error_response("Webhook retry queue not available", 500)
        except (KeyError, ValueError, OSError, TypeError) as e:
            logger.error("Error getting queue stats: %s", e)
            return error_response("Failed to retrieve queue stats", 500)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "WebhookHandler",
    "WebhookConfig",
    "WebhookStore",
    "get_webhook_store",
    "generate_signature",
    "verify_signature",
    "WEBHOOK_EVENTS",
]
