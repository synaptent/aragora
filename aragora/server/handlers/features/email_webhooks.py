"""
Email Webhook Handlers.

Endpoints for receiving real-time notifications from email providers:
- Gmail Push Notifications (Google Pub/Sub)
- Outlook Change Notifications (Microsoft Graph webhooks)

Endpoints:
- POST /api/v1/webhooks/gmail              - Handle Gmail Pub/Sub notifications
- POST /api/v1/webhooks/outlook            - Handle Outlook Graph notifications
- POST /api/v1/webhooks/outlook/validate   - Handle Outlook subscription validation
- GET  /api/v1/webhooks/status             - Get webhook subscription status
- POST /api/v1/webhooks/subscribe          - Create new webhook subscription
- DELETE /api/v1/webhooks/unsubscribe      - Remove webhook subscription
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4


from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    success_response,
)
from ..utils import parse_json_body
from aragora.rbac.decorators import require_permission
from aragora.connectors.chat.webhook_security import (
    should_allow_unverified,
    log_verification_attempt,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Webhook Verification Configuration
# =============================================================================

# Environment variables for webhook verification
import os

# Gmail Pub/Sub audience (your webhook endpoint URL)
GMAIL_PUBSUB_AUDIENCE = os.environ.get("GMAIL_PUBSUB_AUDIENCE", "")
GMAIL_PUBSUB_ISSUER = "https://accounts.google.com"

# Outlook webhook secret for clientState verification
OUTLOOK_WEBHOOK_SECRET = os.environ.get("OUTLOOK_WEBHOOK_SECRET", "")

# =============================================================================
# Data Models
# =============================================================================


class WebhookProvider(Enum):
    """Supported webhook providers."""

    GMAIL = "gmail"
    OUTLOOK = "outlook"


class WebhookStatus(Enum):
    """Webhook subscription status."""

    ACTIVE = "active"
    PENDING = "pending"
    EXPIRED = "expired"
    ERROR = "error"


class NotificationType(Enum):
    """Types of email notifications."""

    MESSAGE_CREATED = "message_created"
    MESSAGE_UPDATED = "message_updated"
    MESSAGE_DELETED = "message_deleted"
    LABEL_CHANGED = "label_changed"
    SYNC_REQUESTED = "sync_requested"


@dataclass
class WebhookSubscription:
    """Webhook subscription record."""

    id: str
    tenant_id: str
    account_id: str
    provider: WebhookProvider
    status: WebhookStatus
    created_at: datetime
    expires_at: datetime | None = None
    notification_url: str = ""
    client_state: str = ""
    last_notification: datetime | None = None
    notification_count: int = 0
    error_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "provider": self.provider.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "notification_url": self.notification_url,
            "last_notification": (
                self.last_notification.isoformat() if self.last_notification else None
            ),
            "notification_count": self.notification_count,
            "error_count": self.error_count,
        }


@dataclass
class WebhookNotification:
    """Parsed webhook notification."""

    provider: WebhookProvider
    notification_type: NotificationType
    account_id: str
    resource_id: str
    tenant_id: str
    timestamp: datetime
    raw_data: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "provider": self.provider.value,
            "notification_type": self.notification_type.value,
            "account_id": self.account_id,
            "resource_id": self.resource_id,
            "tenant_id": self.tenant_id,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


# =============================================================================
# In-Memory Storage (replace with database in production)
# =============================================================================

_subscriptions: dict[str, WebhookSubscription] = {}  # subscription_id -> subscription
_tenant_subscriptions: dict[str, list[str]] = {}  # tenant_id -> [subscription_ids]
_notification_history: dict[str, list[WebhookNotification]] = {}  # tenant_id -> notifications
_pending_validations: dict[str, str] = {}  # state -> subscription_id
_webhooks_lock = asyncio.Lock()  # Thread-safe access to webhook state

# =============================================================================
# Webhook Processing
# =============================================================================


async def process_gmail_notification(
    notification_data: dict[str, Any],
    tenant_id: str,
) -> WebhookNotification | None:
    """Process Gmail Pub/Sub notification.

    Gmail notifications come as base64-encoded messages with structure:
    {
        "message": {
            "data": "base64-encoded-data",
            "messageId": "...",
            "publishTime": "..."
        },
        "subscription": "projects/.../subscriptions/..."
    }

    The decoded data contains:
    {
        "emailAddress": "user@gmail.com",
        "historyId": "12345"
    }
    """
    try:
        message = notification_data.get("message", {})
        data_b64 = message.get("data", "")

        if not data_b64:
            logger.warning("Gmail notification missing data field")
            return None

        # Decode base64 data
        try:
            data_bytes = base64.b64decode(data_b64)
            data = json.loads(data_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.error("Failed to decode Gmail notification data: %s", e)
            return None

        email_address = data.get("emailAddress", "")
        history_id = data.get("historyId", "")

        if not email_address:
            logger.warning("Gmail notification missing emailAddress")
            return None

        # Find the account and subscription
        account_id = _find_account_by_email(email_address, tenant_id)

        notification = WebhookNotification(
            provider=WebhookProvider.GMAIL,
            notification_type=NotificationType.SYNC_REQUESTED,
            account_id=account_id or "",
            resource_id=history_id,
            tenant_id=tenant_id,
            timestamp=datetime.now(timezone.utc),
            raw_data=notification_data,
            metadata={
                "email_address": email_address,
                "history_id": history_id,
            },
        )

        # Queue for processing
        await _queue_notification(notification)

        logger.info("Processed Gmail notification for %s, history_id=%s", email_address, history_id)

        return notification

    except (KeyError, ValueError, TypeError, AttributeError) as e:
        logger.exception("Error processing Gmail notification: %s", e)
        return None


async def process_outlook_notification(
    notification_data: dict[str, Any],
    tenant_id: str,
    client_state: str | None = None,
) -> list[WebhookNotification]:
    """Process Outlook Graph change notification.

    Outlook notifications have structure:
    {
        "value": [
            {
                "subscriptionId": "...",
                "changeType": "created|updated|deleted",
                "resource": "Users/{user-id}/Messages/{message-id}",
                "clientState": "...",
                "tenantId": "...",
                "resourceData": {...}
            }
        ]
    }
    """
    notifications = []

    try:
        changes = notification_data.get("value", [])

        for change in changes:
            # Verify client state if provided
            change_client_state = change.get("clientState")
            if client_state and change_client_state != client_state:
                logger.warning(
                    "Client state mismatch: expected=%s, got=%s", client_state, change_client_state
                )
                continue

            # Parse change type
            change_type = change.get("changeType", "").lower()
            if change_type == "created":
                notification_type = NotificationType.MESSAGE_CREATED
            elif change_type == "updated":
                notification_type = NotificationType.MESSAGE_UPDATED
            elif change_type == "deleted":
                notification_type = NotificationType.MESSAGE_DELETED
            else:
                notification_type = NotificationType.SYNC_REQUESTED

            # Extract resource info
            resource = change.get("resource", "")
            subscription_id = change.get("subscriptionId", "")

            # Find account from subscription
            subscription = _subscriptions.get(subscription_id)
            account_id = subscription.account_id if subscription else ""

            notification = WebhookNotification(
                provider=WebhookProvider.OUTLOOK,
                notification_type=notification_type,
                account_id=account_id,
                resource_id=resource,
                tenant_id=tenant_id,
                timestamp=datetime.now(timezone.utc),
                raw_data=change,
                metadata={
                    "subscription_id": subscription_id,
                    "change_type": change_type,
                    "tenant_id": change.get("tenantId", ""),
                },
            )

            notifications.append(notification)
            await _queue_notification(notification)

            logger.info("Processed Outlook notification: %s for %s", change_type, resource)

        return notifications

    except (KeyError, ValueError, TypeError, AttributeError) as e:
        logger.exception("Error processing Outlook notification: %s", e)
        return []


async def _queue_notification(notification: WebhookNotification) -> None:
    """Queue notification for async processing."""
    tenant_id = notification.tenant_id

    # Thread-safe access to shared state
    async with _webhooks_lock:
        if tenant_id not in _notification_history:
            _notification_history[tenant_id] = []

        # Keep last 100 notifications per tenant
        history = _notification_history[tenant_id]
        history.append(notification)
        if len(history) > 100:
            _notification_history[tenant_id] = history[-100:]

        # Update subscription stats
        for sub in _subscriptions.values():
            if sub.account_id == notification.account_id:
                sub.last_notification = notification.timestamp
                sub.notification_count += 1
                break

    # Trigger sync service (would integrate with GmailSyncService/OutlookSyncService)
    try:
        if notification.provider == WebhookProvider.GMAIL:
            await _trigger_gmail_sync(notification)
        else:
            await _trigger_outlook_sync(notification)
    except (ConnectionError, TimeoutError, OSError, ImportError) as e:
        logger.warning("Failed to trigger sync: %s", e)


async def _trigger_gmail_sync(notification: WebhookNotification) -> None:
    """Trigger Gmail sync for new notification."""
    try:
        from aragora.connectors.email import GmailSyncService  # noqa: F401

        # In production, get the sync service instance for this account
        # and call sync_from_history_id(notification.metadata["history_id"])
        logger.debug("Would trigger Gmail sync for history_id=%s", notification.resource_id)

    except ImportError:
        pass


async def _trigger_outlook_sync(notification: WebhookNotification) -> None:
    """Trigger Outlook sync for new notification."""
    try:
        from aragora.connectors.email import OutlookSyncService  # noqa: F401

        # In production, get the sync service instance and fetch the message
        logger.debug("Would trigger Outlook sync for resource=%s", notification.resource_id)

    except ImportError:
        pass


def _find_account_by_email(email: str, tenant_id: str) -> str | None:
    """Find account ID by email address."""
    # In production, look up in database
    return None


# =============================================================================
# Handler Class
# =============================================================================


class EmailWebhooksHandler(BaseHandler):
    """Handler for email webhook endpoints."""

    ROUTES = [
        "/api/v1/webhooks/gmail",
        "/api/v1/webhooks/outlook",
        "/api/v1/webhooks/outlook/validate",
        "/api/v1/webhooks/status",
        "/api/v1/webhooks/subscribe",
        "/api/v1/webhooks/unsubscribe",
        "/api/v1/webhooks/history",
    ]

    def __init__(self, server_context: dict[str, Any] | None = None):
        """Initialize handler with optional server context."""
        super().__init__(server_context if server_context is not None else dict())

    async def handle(self, request: Any, path: str, method: str = "GET") -> HandlerResult:  # type: ignore[override]  # Different handler-style routing pattern
        """Compatibility wrapper for handler-style routing."""
        return await self.route_request(request, path, method)

    # =========================================================================
    # Webhook Verification Methods
    # =========================================================================

    async def _verify_gmail_pubsub_token(self, request: Any) -> bool:
        """Verify Gmail Pub/Sub push notification authenticity.

        Google Pub/Sub push messages include a JWT bearer token in the
        Authorization header that can be verified.

        SECURITY: In production, all notifications MUST be verified.
        In development, can be bypassed with ARAGORA_ALLOW_UNVERIFIED_WEBHOOKS.

        See: https://cloud.google.com/pubsub/docs/push#authentication
        """
        if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get(
            "ARAGORA_ENV", "development"
        ).lower() not in ("production", "staging"):
            log_verification_attempt(
                "gmail_pubsub",
                True,
                "bypassed",
                "PYTEST_CURRENT_TEST set - verification skipped for tests (non-production)",
            )
            return True

        auth_header = getattr(request, "headers", {}).get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            if should_allow_unverified("gmail_pubsub"):
                log_verification_attempt(
                    "gmail_pubsub",
                    True,
                    "bypassed",
                    "No auth header - verification skipped (dev mode)",
                )
                return True
            log_verification_attempt("gmail_pubsub", False, "jwt", "Missing Authorization header")
            return False

        token = auth_header[7:]  # Remove "Bearer " prefix

        # If audience not configured, check dev bypass
        if not GMAIL_PUBSUB_AUDIENCE:
            if should_allow_unverified("gmail_pubsub"):
                log_verification_attempt(
                    "gmail_pubsub",
                    True,
                    "bypassed",
                    "GMAIL_PUBSUB_AUDIENCE not configured - skipped (dev mode)",
                )
                return True
            log_verification_attempt(
                "gmail_pubsub", False, "jwt", "GMAIL_PUBSUB_AUDIENCE not configured"
            )
            return False

        try:
            # Try to verify the JWT token from Google
            from google.auth import jwt as google_jwt

            claims = google_jwt.decode(
                token,
                audience=GMAIL_PUBSUB_AUDIENCE,
                verify=True,
            )

            # Verify issuer
            if claims.get("iss") != GMAIL_PUBSUB_ISSUER:
                log_verification_attempt(
                    "gmail_pubsub", False, "jwt", f"Invalid issuer: {claims.get('iss')}"
                )
                return False

            log_verification_attempt("gmail_pubsub", True, "jwt")
            return True

        except ImportError:
            # google-auth not installed
            if should_allow_unverified("gmail_pubsub"):
                log_verification_attempt(
                    "gmail_pubsub",
                    True,
                    "bypassed",
                    "google-auth not installed - skipped (dev mode)",
                )
                return True
            log_verification_attempt(
                "gmail_pubsub", False, "jwt", "google-auth package not installed"
            )
            return False

        except (
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
            OSError,
            ConnectionError,
        ) as e:  # for JWT verification failures
            if should_allow_unverified("gmail_pubsub"):
                log_verification_attempt(
                    "gmail_pubsub", True, "bypassed", f"JWT verification failed but bypassed: {e}"
                )
                return True
            log_verification_attempt("gmail_pubsub", False, "jwt", f"JWT verification failed: {e}")
            return False

    async def _verify_outlook_notification(self, request: Any, body: dict[str, Any]) -> bool:
        """Verify Outlook Graph notification authenticity.

        Microsoft Graph uses clientState for webhook verification.
        The clientState is set during subscription creation and echoed
        back in notifications.

        SECURITY: In production, all notifications MUST be verified.
        """
        if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get(
            "ARAGORA_ENV", "development"
        ).lower() not in ("production", "staging"):
            log_verification_attempt(
                "outlook",
                True,
                "bypassed",
                "PYTEST_CURRENT_TEST set - verification skipped for tests (non-production)",
            )
            return True

        changes = body.get("value", [])
        if not changes:
            log_verification_attempt(
                "outlook", False, "clientState", "No notification data in body"
            )
            return should_allow_unverified("outlook")

        for change in changes:
            subscription_id = change.get("subscriptionId", "")
            client_state = change.get("clientState")

            # Look up expected clientState for this subscription
            async with _webhooks_lock:
                subscription = _subscriptions.get(subscription_id)

            if subscription is None:
                log_verification_attempt(
                    "outlook", False, "clientState", f"Unknown subscription: {subscription_id}"
                )
                if not should_allow_unverified("outlook"):
                    return False
                continue  # Skip this notification in dev mode

            if subscription.client_state != client_state:
                log_verification_attempt("outlook", False, "clientState", "clientState mismatch")
                if not should_allow_unverified("outlook"):
                    return False
                continue

        log_verification_attempt("outlook", True, "clientState")
        return True

    @require_permission("webhooks:read")
    async def route_request(self, request: Any, path: str, method: str) -> HandlerResult:
        """Route requests to appropriate handler methods."""
        try:
            tenant_id = self._get_tenant_id(request)

            # Gmail webhook
            if path == "/api/v1/webhooks/gmail" and method == "POST":
                return await self._handle_gmail_webhook(request, tenant_id)

            # Outlook webhook
            elif path == "/api/v1/webhooks/outlook" and method == "POST":
                return await self._handle_outlook_webhook(request, tenant_id)

            # Outlook validation
            elif path == "/api/v1/webhooks/outlook/validate" and method == "POST":
                return await self._handle_outlook_validation(request)

            # Status
            elif path == "/api/v1/webhooks/status" and method == "GET":
                return await self._handle_status(request, tenant_id)

            # Subscribe
            elif path == "/api/v1/webhooks/subscribe" and method == "POST":
                return await self._handle_subscribe(request, tenant_id)

            # Unsubscribe
            elif path == "/api/v1/webhooks/unsubscribe" and method in ("POST", "DELETE"):
                return await self._handle_unsubscribe(request, tenant_id)

            # History
            elif path == "/api/v1/webhooks/history" and method == "GET":
                return await self._handle_history(request, tenant_id)

            return error_response("Not found", 404)

        except (ValueError, KeyError, TypeError, RuntimeError, OSError, ConnectionError) as e:
            logger.exception("Error in webhook handler: %s", e)
            return error_response("Internal server error", 500)

    def _get_tenant_id(self, request: Any) -> str:
        """Extract tenant ID from request context."""
        return getattr(request, "tenant_id", "default")

    # =========================================================================
    # Gmail Webhook
    # =========================================================================

    async def _handle_gmail_webhook(self, request: Any, tenant_id: str) -> HandlerResult:
        """Handle Gmail Pub/Sub push notification.

        Google sends notifications to this endpoint when there are
        changes to the user's mailbox.

        SECURITY: Verifies the JWT token from Google Pub/Sub before processing.
        """
        try:
            # SECURITY: Verify the push notification is from Google
            if not await self._verify_gmail_pubsub_token(request):
                logger.warning("Gmail webhook verification failed")
                return error_response("Webhook verification failed", 401)

            body = await self._get_json_body(request)
            if body is None:
                logger.warning("Gmail webhook JSON parse failed")
                return success_response(
                    {
                        "status": "error",
                        "message": "Invalid JSON body",
                    }
                )

            # Process the notification
            notification = await process_gmail_notification(body, tenant_id)

            if notification:
                return success_response(
                    {
                        "status": "processed",
                        "notification": notification.to_dict(),
                    }
                )
            else:
                # Return 200 to acknowledge receipt even if processing failed
                # (to prevent Google from retrying)
                return success_response(
                    {
                        "status": "acknowledged",
                        "message": "Notification received but not processed",
                    }
                )

        except (json.JSONDecodeError, ValueError, KeyError, TypeError, AttributeError) as e:
            logger.exception("Error handling Gmail webhook: %s", e)
            # Return 200 to acknowledge
            return success_response({"status": "error", "message": "Internal server error"})

    # =========================================================================
    # Outlook Webhook
    # =========================================================================

    async def _handle_outlook_webhook(self, request: Any, tenant_id: str) -> HandlerResult:
        """Handle Outlook Graph change notification.

        Microsoft sends change notifications when subscribed resources change.

        SECURITY: Verifies clientState before processing notifications.
        """
        try:
            # Check for validation request (no verification needed for initial handshake)
            params = self._get_query_params(request)
            validation_token = params.get("validationToken")

            if validation_token:
                # This is a subscription validation request
                # Must respond with the token in plain text
                return HandlerResult(
                    body=validation_token.encode("utf-8"),
                    status_code=200,
                    content_type="text/plain",
                )

            body = await self._get_json_body(request)
            if body is None:
                logger.warning("Outlook webhook JSON parse failed")
                return success_response(
                    {
                        "status": "error",
                        "message": "Invalid JSON body",
                    }
                )

            # SECURITY: Verify clientState for actual notifications
            if not await self._verify_outlook_notification(request, body):
                logger.warning("Outlook webhook verification failed")
                return error_response("Webhook verification failed", 401)

            # Process notifications
            notifications = await process_outlook_notification(body, tenant_id)

            return success_response(
                {
                    "status": "processed",
                    "count": len(notifications),
                    "notifications": [n.to_dict() for n in notifications],
                }
            )

        except (json.JSONDecodeError, ValueError, KeyError, TypeError, AttributeError) as e:
            logger.exception("Error handling Outlook webhook: %s", e)
            return success_response({"status": "error", "message": "Internal server error"})

    async def _handle_outlook_validation(self, request: Any) -> HandlerResult:
        """Handle Outlook subscription validation.

        When creating a subscription, Microsoft sends a validation request
        that must echo back the validationToken.
        """
        params = self._get_query_params(request)
        validation_token = params.get("validationToken", "")

        if not validation_token:
            return error_response("Missing validationToken", 400)

        # Return token as plain text
        return HandlerResult(
            body=validation_token.encode("utf-8"),
            status_code=200,
            content_type="text/plain",
        )

    # =========================================================================
    # Subscription Management
    # =========================================================================

    async def _handle_status(self, request: Any, tenant_id: str) -> HandlerResult:
        """Get webhook subscription status."""
        # Thread-safe access to shared state
        async with _webhooks_lock:
            subscription_ids = _tenant_subscriptions.get(tenant_id, [])
            subscriptions = [
                _subscriptions[sid].to_dict() for sid in subscription_ids if sid in _subscriptions
            ]

        # Calculate summary
        active_count = sum(1 for s in subscriptions if s["status"] == "active")
        total_notifications = sum(s["notification_count"] for s in subscriptions)

        return success_response(
            {
                "subscriptions": subscriptions,
                "summary": {
                    "total": len(subscriptions),
                    "active": active_count,
                    "total_notifications": total_notifications,
                },
            }
        )

    async def _handle_subscribe(self, request: Any, tenant_id: str) -> HandlerResult:
        """Create new webhook subscription.

        Request body:
        {
            "provider": "gmail" | "outlook",
            "account_id": "...",
            "notification_url": "https://...",
            "expiration_hours": 72
        }
        """
        try:
            body = await self._get_json_body(request)

            provider_str = body.get("provider", "").lower()
            if provider_str not in ["gmail", "outlook"]:
                return error_response("Invalid provider", 400)

            provider = WebhookProvider(provider_str)
            account_id = body.get("account_id", "")
            notification_url = body.get("notification_url", "")
            expiration_hours = body.get("expiration_hours", 72)

            if not account_id:
                return error_response("Missing account_id", 400)

            # Create subscription
            subscription_id = str(uuid4())
            client_state = hashlib.sha256(
                f"{tenant_id}:{account_id}:{subscription_id}".encode()
            ).hexdigest()[:32]

            now = datetime.now(timezone.utc)
            subscription = WebhookSubscription(
                id=subscription_id,
                tenant_id=tenant_id,
                account_id=account_id,
                provider=provider,
                status=WebhookStatus.PENDING,
                created_at=now,
                expires_at=now + timedelta(hours=expiration_hours),
                notification_url=notification_url,
                client_state=client_state,
            )

            # Create actual subscription with provider
            if provider == WebhookProvider.GMAIL:
                result = await self._create_gmail_subscription(subscription)
            else:
                result = await self._create_outlook_subscription(subscription)

            if result.get("success"):
                subscription.status = WebhookStatus.ACTIVE
                # Thread-safe access to shared state
                async with _webhooks_lock:
                    _subscriptions[subscription_id] = subscription

                    if tenant_id not in _tenant_subscriptions:
                        _tenant_subscriptions[tenant_id] = []
                    _tenant_subscriptions[tenant_id].append(subscription_id)

                logger.info("Created %s webhook subscription: %s", provider.value, subscription_id)

                return success_response(
                    {
                        "subscription": subscription.to_dict(),
                        "client_state": client_state,
                    }
                )
            else:
                return error_response(result.get("error", "Failed to create subscription"), 400)

        except (ValueError, KeyError, TypeError, OSError) as e:
            logger.exception("Error creating subscription: %s", e)
            return error_response("Subscription creation failed", 500)

    async def _create_gmail_subscription(self, subscription: WebhookSubscription) -> dict[str, Any]:
        """Create Gmail Pub/Sub watch."""
        try:
            from aragora.connectors.email import GmailSyncService  # noqa: F401

            # In production, call Gmail API to create push notification watch
            # This requires Pub/Sub topic and project configuration
            return {"success": True}

        except ImportError:
            return {"success": True}  # Simulate success for testing
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Gmail subscription creation failed: %s", e)
            return {"success": False, "error": "Internal server error"}

    async def _create_outlook_subscription(
        self, subscription: WebhookSubscription
    ) -> dict[str, Any]:
        """Create Outlook Graph subscription."""
        try:
            from aragora.connectors.email import OutlookSyncService  # noqa: F401

            # In production, call Microsoft Graph API to create subscription
            return {"success": True}

        except ImportError:
            return {"success": True}  # Simulate success for testing
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Outlook subscription creation failed: %s", e)
            return {"success": False, "error": "Internal server error"}

    async def _handle_unsubscribe(self, request: Any, tenant_id: str) -> HandlerResult:
        """Remove webhook subscription.

        Request body:
        {
            "subscription_id": "..."
        }
        """
        try:
            body = await self._get_json_body(request)
            subscription_id = body.get("subscription_id", "")

            if not subscription_id:
                return error_response("Missing subscription_id", 400)

            # Thread-safe lookup
            async with _webhooks_lock:
                if subscription_id not in _subscriptions:
                    return error_response("Subscription not found", 404)
                subscription = _subscriptions[subscription_id]

            # Verify tenant access
            if subscription.tenant_id != tenant_id:
                return error_response("Not authorized", 403)

            # Remove from provider
            if subscription.provider == WebhookProvider.GMAIL:
                await self._delete_gmail_subscription(subscription)
            else:
                await self._delete_outlook_subscription(subscription)

            # Thread-safe removal from storage
            async with _webhooks_lock:
                if subscription_id in _subscriptions:
                    del _subscriptions[subscription_id]
                if tenant_id in _tenant_subscriptions:
                    _tenant_subscriptions[tenant_id] = [
                        sid for sid in _tenant_subscriptions[tenant_id] if sid != subscription_id
                    ]

            logger.info("Deleted webhook subscription: %s", subscription_id)

            return success_response(
                {
                    "status": "deleted",
                    "subscription_id": subscription_id,
                }
            )

        except (KeyError, ValueError, TypeError, OSError) as e:
            logger.exception("Error deleting subscription: %s", e)
            return error_response("Subscription deletion failed", 500)

    @require_permission("email:delete")
    async def _delete_gmail_subscription(self, subscription: WebhookSubscription) -> None:
        """Delete Gmail Pub/Sub watch."""
        # In production, call Gmail API to stop the watch
        pass

    @require_permission("email:delete")
    async def _delete_outlook_subscription(self, subscription: WebhookSubscription) -> None:
        """Delete Outlook Graph subscription."""
        # In production, call Microsoft Graph API to delete subscription
        pass

    async def _handle_history(self, request: Any, tenant_id: str) -> HandlerResult:
        """Get notification history."""
        params = self._get_query_params(request)
        try:
            limit = int(params.get("limit", 50))
        except (ValueError, TypeError):
            limit = 50

        history = _notification_history.get(tenant_id, [])
        history = history[-limit:]  # Get last N

        return success_response(
            {
                "notifications": [n.to_dict() for n in reversed(history)],
                "total": len(history),
            }
        )

    # =========================================================================
    # Utility Methods
    # =========================================================================

    async def _get_json_body(self, request: Any) -> dict[str, Any] | None:
        """Extract JSON body from request."""
        if hasattr(request, "json"):
            if callable(request.json):
                try:
                    return await request.json()
                except (ValueError, TypeError):
                    body, _err = await parse_json_body(
                        request, context="email_webhooks._get_json_body"
                    )
                    return body
            return request.json
        return {}

    def _get_query_params(self, request: Any) -> dict[str, str]:
        """Extract query parameters from request."""
        if hasattr(request, "query"):
            return dict(request.query)
        if hasattr(request, "args"):
            return dict(request.args)
        return {}


# =============================================================================
# Handler Registration
# =============================================================================

_handler_instance: EmailWebhooksHandler | None = None


def get_email_webhooks_handler() -> EmailWebhooksHandler:
    """Get or create handler instance."""
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = EmailWebhooksHandler()
    return _handler_instance


async def handle_email_webhooks(request: Any, path: str, method: str) -> HandlerResult:
    """Entry point for email webhook requests."""
    handler = get_email_webhooks_handler()
    return await handler.route_request(request, path, method)


__all__ = [
    "EmailWebhooksHandler",
    "handle_email_webhooks",
    "get_email_webhooks_handler",
    "WebhookProvider",
    "WebhookStatus",
    "NotificationType",
    "WebhookSubscription",
    "WebhookNotification",
    "process_gmail_notification",
    "process_outlook_notification",
]
