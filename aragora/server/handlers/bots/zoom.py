"""
Zoom Bot endpoint handler.

Handles incoming events from Zoom's webhook API for chat messages
and meeting events.

Endpoints:
- POST /api/bots/zoom/events - Handle Zoom events/webhooks
- GET /api/bots/zoom/status - Bot status

Environment Variables:
- ZOOM_CLIENT_ID - Required for OAuth
- ZOOM_CLIENT_SECRET - Required for OAuth
- ZOOM_BOT_JID - Bot's JID
- ZOOM_SECRET_TOKEN - Webhook signature verification
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.server.handlers.bots.base import BotHandlerMixin
from aragora.server.handlers.secure import SecureHandler
from aragora.server.handlers.utils.rate_limit import rate_limit

# RBAC imports - optional dependency
try:
    from aragora.rbac.checker import check_permission
    from aragora.rbac.models import AuthorizationContext

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

logger = logging.getLogger(__name__)

# Environment variables - None defaults make misconfiguration explicit
ZOOM_CLIENT_ID = os.environ.get("ZOOM_CLIENT_ID")
ZOOM_CLIENT_SECRET = os.environ.get("ZOOM_CLIENT_SECRET")
ZOOM_BOT_JID = os.environ.get("ZOOM_BOT_JID")
ZOOM_SECRET_TOKEN = os.environ.get("ZOOM_SECRET_TOKEN")

# Log at debug level for unconfigured optional integrations
if not ZOOM_SECRET_TOKEN:
    logger.debug("ZOOM_SECRET_TOKEN not configured - webhook signature verification will fail")


class ZoomHandler(BotHandlerMixin, SecureHandler):
    """Handler for Zoom Bot endpoints.

    Uses BotHandlerMixin for shared auth/status patterns.

    RBAC Protected:
    - bots.read - required for status endpoint

    Note: Event webhook endpoints are authenticated via Zoom's signature,
    not RBAC, since they are called by Zoom servers directly.
    """

    # BotHandlerMixin configuration
    bot_platform = "zoom"

    ROUTES = [
        "/api/v1/bots/zoom/events",
        "/api/v1/bots/zoom/status",
    ]

    def __init__(self, ctx: dict | None = None):
        super().__init__(ctx or {})
        self._bot: Any | None = None
        self._bot_initialized = False

    # ------------------------------------------------------------------
    # RBAC helper
    # ------------------------------------------------------------------

    def _check_bot_permission(
        self, permission: str, *, user_id: str = "", context: dict | None = None
    ) -> None:
        """Check RBAC permission if available.

        Args:
            permission: The permission string to check (e.g. "debates:create").
            user_id: Platform-qualified user id (e.g. "zoom:abc123").
            context: Optional dict that may carry an ``auth_context`` key.

        Raises:
            PermissionError: When RBAC is available and the check fails.
        """
        if not RBAC_AVAILABLE:
            if rbac_fail_closed():
                raise PermissionError("Service unavailable: access control module not loaded")
            return
        auth_ctx = (context or {}).get("auth_context")
        if auth_ctx is None and user_id:
            auth_ctx = AuthorizationContext(
                user_id=user_id,
                roles={"bot_user"},
            )
        if auth_ctx:
            check_permission(auth_ctx, permission)

    def _is_bot_enabled(self) -> bool:
        """Check if Zoom bot is configured."""
        return bool(ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET)

    def _get_platform_config_status(self) -> dict[str, Any]:
        """Return Zoom-specific config fields for status response."""
        return {
            "client_id_configured": bool(ZOOM_CLIENT_ID),
            "client_secret_configured": bool(ZOOM_CLIENT_SECRET),
            "bot_jid_configured": bool(ZOOM_BOT_JID),
            "secret_token_configured": bool(ZOOM_SECRET_TOKEN),
        }

    def _ensure_bot(self) -> Any | None:
        """Lazily initialize the Zoom bot."""
        if self._bot_initialized:
            return self._bot

        self._bot_initialized = True

        if not ZOOM_CLIENT_ID or not ZOOM_CLIENT_SECRET:
            logger.warning("Zoom credentials not configured")
            return None

        try:
            from aragora.bots.zoom_bot import create_zoom_bot

            self._bot = create_zoom_bot()
            logger.info("Zoom bot initialized")
        except ImportError as e:
            logger.warning("Zoom bot module not available: %s", e)
            self._bot = None
        except (ValueError, KeyError, TypeError) as e:
            logger.error("Failed to initialize Zoom bot due to configuration error: %s", e)
            self._bot = None
        except (RuntimeError, OSError, AttributeError) as e:
            logger.exception("Unexpected error initializing Zoom bot: %s", e)
            self._bot = None

        return self._bot

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES

    @rate_limit(requests_per_minute=30)
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route Zoom requests with RBAC for status endpoint."""
        if path == "/api/v1/bots/zoom/status":
            # Use BotHandlerMixin's RBAC-protected status handler
            return await self.handle_status_request(handler)

        return None

    @handle_errors("zoom creation")
    @rate_limit(requests_per_minute=30)
    async def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests."""
        if path == "/api/v1/bots/zoom/events":
            return await self._handle_events(handler)

        return None

    async def _handle_events(self, handler: Any) -> HandlerResult:
        """Handle incoming Zoom webhook events.

        This endpoint receives events from Zoom including:
        - endpoint.url_validation (initial verification)
        - bot_notification (chat messages)
        - meeting.ended (meeting ended)
        - bot_installed (bot was installed)
        """
        bot = self._ensure_bot()
        if not bot:
            # For URL validation, we still need to respond even without full bot
            pass

        try:
            # Get verification headers
            timestamp = handler.headers.get("x-zm-request-timestamp", "")
            signature = handler.headers.get("x-zm-signature", "")

            # Read body
            body = self._read_request_body(handler)

            # Parse event first to check if URL validation (which has different requirements)
            event, err = self._parse_json_body(body, "Zoom event")
            if err:
                return err
            if event is None:
                return error_response("Zoom event body must be a JSON object", 400)

            event_type = event.get("event", "")

            # Handle URL validation - requires ZOOM_SECRET_TOKEN
            if event_type == "endpoint.url_validation":
                if not ZOOM_SECRET_TOKEN:
                    logger.warning("ZOOM_SECRET_TOKEN not configured - rejecting URL validation")
                    return error_response("Zoom secret token not configured", 503)

                import hashlib
                import hmac

                payload = event.get("payload", {})
                if not isinstance(payload, dict):
                    return error_response("Zoom URL validation payload must be a JSON object", 400)
                plain_token = payload.get("plainToken", "")

                encrypted = hmac.new(
                    ZOOM_SECRET_TOKEN.encode(),
                    plain_token.encode(),
                    hashlib.sha256,
                ).hexdigest()
                return json_response(
                    {
                        "plainToken": plain_token,
                        "encryptedToken": encrypted,
                    }
                )

            # For all other events, require signature verification
            if signature:
                if not bot:
                    logger.warning("Zoom bot not configured - cannot verify signature")
                    return error_response("Zoom bot not configured for signature verification", 503)
                if not bot.verify_webhook(body, timestamp, signature):
                    logger.warning("Zoom webhook signature verification failed")
                    self._audit_webhook_auth_failure("signature")
                    return error_response("Invalid signature", 401)
            else:
                # No signature provided - for security, require it
                logger.warning("Zoom webhook request missing signature")
                self._audit_webhook_auth_failure("signature", "missing")
                return error_response("Missing signature header", 401)

            if not isinstance(event_type, str) or not event_type.strip():
                return error_response("Zoom event body must include a non-empty 'event' field", 400)
            logger.info("Zoom event received: %s", event_type)

            # For other events, require bot
            if not bot:
                return json_response(
                    {
                        "error": "Zoom bot not configured",
                        "details": "Set ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET environment variables",
                    },
                    status=503,
                )

            # RBAC: check permission for chat-related events
            if event_type == "bot_notification":
                payload = event.get("payload", {})
                if not isinstance(payload, dict):
                    return error_response(
                        "Zoom bot notification payload must be a JSON object", 400
                    )
                user_jid = payload.get("userJid", "")
                try:
                    self._check_bot_permission(
                        "debates:create", user_id=f"zoom:{user_jid}" if user_jid else ""
                    )
                except PermissionError as exc:
                    logger.warning("RBAC denied debates:create for zoom:%s: %s", user_jid, exc)
                    return json_response({"error": "permission_denied"})

            # Process event
            result = await bot.handle_event(event)
            return json_response(result)

        except (json.JSONDecodeError, ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            return self._handle_webhook_exception(e, "Zoom event", return_200_on_error=False)


__all__ = ["ZoomHandler"]
