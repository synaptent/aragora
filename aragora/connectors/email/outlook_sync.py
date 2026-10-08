"""
Outlook Background Sync Service.

Provides real-time Outlook synchronization using:
- Microsoft Graph Change Notifications (webhooks)
- Delta Query API for incremental message retrieval
- EmailPrioritizer integration for scoring
- Tenant-isolated sync state persistence

Architecture:
    1. Initial sync: Full inbox scan, stores delta link
    2. Webhook receives Graph change notification when inbox changes
    3. Delta Query API fetches only changed messages
    4. EmailPrioritizer scores new messages
    5. Results published to message queue for processing

Usage:
    from aragora.connectors.email.outlook_sync import (
        OutlookSyncService,
        OutlookSyncConfig,
    )

    config = OutlookSyncConfig(
        notification_url="https://api.example.com/webhooks/outlook",
    )

    sync_service = OutlookSyncService(
        tenant_id="tenant_123",
        user_id="user_456",
        config=config,
    )

    # Start background sync
    await sync_service.start()

    # Handle webhook from Microsoft Graph
    await sync_service.handle_webhook(webhook_payload)

    # Stop sync
    await sync_service.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.observability.http_client_pool import get_http_pool

if TYPE_CHECKING:
    from aragora.connectors.enterprise.communication.outlook import OutlookConnector
    from aragora.connectors.enterprise.communication.models import EmailMessage
    from aragora.services.email_prioritization import EmailPrioritizer, EmailPriorityResult

logger = logging.getLogger(__name__)

_MAX_PAGES = 1000  # Safety cap for pagination loops


class OutlookSyncStatus(Enum):
    """Status of the sync service."""

    IDLE = "idle"
    SYNCING = "syncing"
    WATCHING = "watching"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class OutlookSyncConfig:
    """Configuration for Outlook sync service."""

    # Microsoft Graph webhook settings
    notification_url: str = ""  # HTTPS URL to receive notifications
    client_state: str = ""  # Secret for validating notifications

    # Sync settings
    initial_sync_days: int = 7
    max_messages_per_sync: int = 100
    sync_folders: list[str] = field(default_factory=lambda: ["Inbox"])
    exclude_folders: list[str] = field(default_factory=lambda: ["Deleted Items", "Junk Email"])

    # Subscription settings (Graph subscriptions expire)
    subscription_expiry_minutes: int = 4230  # Max ~3 days for mail
    renewal_buffer_minutes: int = 60  # Renew this early

    # Retry settings
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    exponential_backoff: bool = True

    # Prioritization
    enable_prioritization: bool = True
    prioritization_timeout_seconds: float = 30.0

    # State persistence
    state_backend: str = "memory"  # "memory", "redis", "postgres"
    redis_url: str | None = None
    postgres_dsn: str | None = None


@dataclass
class OutlookSyncState:
    """Persistent state for Outlook sync."""

    tenant_id: str
    user_id: str
    email_address: str = ""

    # Sync state
    delta_link: str = ""  # For incremental sync
    last_sync: datetime | None = None
    initial_sync_complete: bool = False

    # Subscription state
    subscription_id: str | None = None
    subscription_expiry: datetime | None = None
    client_state: str = ""  # For validating webhooks

    # Statistics
    total_messages_synced: int = 0
    total_messages_prioritized: int = 0
    sync_errors: int = 0
    last_error: str | None = None

    # Folders synced
    synced_folder_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "email_address": self.email_address,
            "delta_link": self.delta_link,
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
            "initial_sync_complete": self.initial_sync_complete,
            "subscription_id": self.subscription_id,
            "subscription_expiry": (
                self.subscription_expiry.isoformat() if self.subscription_expiry else None
            ),
            "client_state": self.client_state,
            "total_messages_synced": self.total_messages_synced,
            "total_messages_prioritized": self.total_messages_prioritized,
            "sync_errors": self.sync_errors,
            "last_error": self.last_error,
            "synced_folder_ids": self.synced_folder_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutlookSyncState:
        """Create from dictionary."""
        state = cls(
            tenant_id=data.get("tenant_id", ""),
            user_id=data.get("user_id", ""),
            email_address=data.get("email_address", ""),
            delta_link=data.get("delta_link", ""),
            initial_sync_complete=data.get("initial_sync_complete", False),
            subscription_id=data.get("subscription_id"),
            client_state=data.get("client_state", ""),
            total_messages_synced=data.get("total_messages_synced", 0),
            total_messages_prioritized=data.get("total_messages_prioritized", 0),
            sync_errors=data.get("sync_errors", 0),
            last_error=data.get("last_error"),
            synced_folder_ids=data.get("synced_folder_ids", []),
        )

        if data.get("last_sync"):
            state.last_sync = datetime.fromisoformat(data["last_sync"])
        if data.get("subscription_expiry"):
            state.subscription_expiry = datetime.fromisoformat(data["subscription_expiry"])

        return state


@dataclass
class OutlookWebhookPayload:
    """Parsed webhook payload from Microsoft Graph."""

    subscription_id: str
    change_type: str  # "created", "updated", "deleted"
    resource: str  # Resource path (e.g., "Users/{id}/Messages/{id}")
    client_state: str
    tenant_id: str
    resource_data: dict[str, Any] = field(default_factory=dict)
    raw_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_graph(cls, notification: dict[str, Any]) -> OutlookWebhookPayload:
        """
        Parse Microsoft Graph change notification.

        The notification format is:
        {
            "subscriptionId": "...",
            "changeType": "created",
            "resource": "Users/{id}/Messages/{id}",
            "clientState": "...",
            "tenantId": "...",
            "resourceData": {
                "@odata.type": "#Microsoft.Graph.Message",
                "id": "..."
            }
        }
        """
        return cls(
            subscription_id=notification.get("subscriptionId", ""),
            change_type=notification.get("changeType", ""),
            resource=notification.get("resource", ""),
            client_state=notification.get("clientState", ""),
            tenant_id=notification.get("tenantId", ""),
            resource_data=notification.get("resourceData", {}),
            raw_data=notification,
        )


@dataclass
class OutlookSyncedMessage:
    """A message that was synced and prioritized."""

    message: EmailMessage
    priority_result: EmailPriorityResult | None = None
    sync_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    account_id: str = ""
    is_new: bool = True
    change_type: str = "created"  # created, updated


class OutlookSyncService:
    """
    Background sync service for Outlook.

    Provides:
    - Initial full sync on startup
    - Real-time incremental sync via Graph change notifications
    - Automatic subscription renewal
    - Integration with EmailPrioritizer
    - Tenant-isolated state management
    """

    def __init__(
        self,
        tenant_id: str,
        user_id: str,
        config: OutlookSyncConfig | None = None,
        outlook_connector: OutlookConnector | None = None,
        prioritizer: EmailPrioritizer | None = None,
        on_message_synced: Callable[[OutlookSyncedMessage], None] | None = None,
        on_batch_complete: Callable[[list[OutlookSyncedMessage]], None] | None = None,
    ):
        """
        Initialize Outlook sync service.

        Args:
            tenant_id: Tenant identifier for isolation
            user_id: User identifier
            config: Sync configuration
            outlook_connector: Pre-configured Outlook connector
            prioritizer: Email prioritizer instance
            on_message_synced: Callback for each synced message
            on_batch_complete: Callback when a sync batch completes
        """
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.config = config or OutlookSyncConfig()
        self._connector = outlook_connector
        self._prioritizer = prioritizer

        # Callbacks
        self._on_message_synced = on_message_synced
        self._on_batch_complete = on_batch_complete

        # State
        self._state: OutlookSyncState | None = None
        self._status = OutlookSyncStatus.IDLE
        self._sync_lock = asyncio.Lock()
        self._renewal_task: asyncio.Task | None = None
        self._running = False

    @property
    def status(self) -> OutlookSyncStatus:
        """Get current sync status."""
        return self._status

    @property
    def state(self) -> OutlookSyncState | None:
        """Get current sync state."""
        return self._state

    async def start(
        self,
        refresh_token: str | None = None,
        do_initial_sync: bool = True,
    ) -> bool:
        """
        Start the sync service.

        Args:
            refresh_token: OAuth refresh token (if connector not provided)
            do_initial_sync: Whether to perform initial sync

        Returns:
            True if started successfully
        """
        if self._running:
            logger.warning("[OutlookSync] Service already running")
            return True

        try:
            # Initialize connector if needed
            if not self._connector:
                from aragora.connectors.enterprise.communication.outlook import OutlookConnector

                self._connector = OutlookConnector()
                if refresh_token:
                    success = await self._connector.authenticate(refresh_token=refresh_token)
                    if not success:
                        raise ValueError("Outlook authentication failed")

            # Initialize prioritizer if needed
            if self.config.enable_prioritization and not self._prioritizer:
                from aragora.services.email_prioritization import EmailPrioritizer

                self._prioritizer = EmailPrioritizer()

            # Load or create state
            self._state = await self._load_state()
            if not self._state:
                self._state = OutlookSyncState(
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                )

            # Get email address and generate client state if needed
            if not self._state.email_address:
                user_info = await self._connector.get_user_info()
                self._state.email_address = user_info.get("mail") or user_info.get(
                    "userPrincipalName", ""
                )

            if not self._state.client_state:
                self._state.client_state = self.config.client_state or secrets.token_urlsafe(32)

            self._running = True
            self._status = OutlookSyncStatus.IDLE

            # Perform initial sync if needed
            if do_initial_sync and not self._state.initial_sync_complete:
                await self._initial_sync()

            # Set up Graph subscription for real-time notifications
            if self.config.notification_url:
                await self._setup_subscription()
                self._renewal_task = asyncio.create_task(self._subscription_renewal_loop())

            logger.info(
                "[OutlookSync] Started for %s (tenant: %s)",
                self._state.email_address,
                self.tenant_id,
            )
            return True

        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            ConnectionError,
            RuntimeError,
            json.JSONDecodeError,
        ) as e:
            self._status = OutlookSyncStatus.ERROR
            if self._state:
                self._state.last_error = "Sync service failed to start"
                self._state.sync_errors += 1
            logger.error("[OutlookSync] Failed to start: %s", e)
            return False

    async def stop(self) -> None:
        """Stop the sync service."""
        self._running = False

        # Cancel renewal task
        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                logger.debug("[OutlookSync] Renewal task cancelled during stop")

        # Delete subscription
        if self._state and self._state.subscription_id:
            await self._delete_subscription()

        # Save state
        await self._save_state()

        self._status = OutlookSyncStatus.STOPPED
        logger.info("[OutlookSync] Stopped for %s/%s", self.tenant_id, self.user_id)

    async def handle_webhook(
        self,
        payload: dict[str, Any],
    ) -> list[OutlookSyncedMessage]:
        """
        Handle incoming Microsoft Graph change notification.

        Args:
            payload: Raw webhook payload from Graph

        Returns:
            List of newly synced and prioritized messages
        """
        if not self._running:
            logger.warning("[OutlookSync] Webhook received but service not running")
            return []

        # Parse notifications (can be multiple in one request)
        notifications = payload.get("value", [])
        if not notifications:
            return []

        synced_messages: list[OutlookSyncedMessage] = []

        for notification in notifications:
            webhook = OutlookWebhookPayload.from_graph(notification)

            # Validate client state
            if self._state and webhook.client_state != self._state.client_state:
                logger.warning(
                    "[OutlookSync] Client state mismatch for subscription %s",
                    webhook.subscription_id,
                )
                continue

            logger.info(
                "[OutlookSync] Notification received: %s for resource %s",
                webhook.change_type,
                webhook.resource,
            )

            # Handle based on change type
            if webhook.change_type in ("created", "updated"):
                # Extract message ID from resource path
                message_id = self._extract_message_id(webhook.resource)
                if message_id:
                    try:
                        if self._connector is None:
                            raise RuntimeError("Connector not initialized - call start() first")
                        msg = await self._connector.get_message(message_id)
                        synced = await self._process_message(
                            msg,
                            is_new=(webhook.change_type == "created"),
                            change_type=webhook.change_type,
                        )
                        if synced:
                            synced_messages.append(synced)
                    except (OSError, KeyError, ValueError) as e:
                        self._status = OutlookSyncStatus.ERROR
                        if self._state:
                            self._state.last_error = (
                                f"Webhook processing failed for message {message_id}"
                            )
                            self._state.sync_errors += 1
                        logger.exception(
                            "[OutlookSync] Failed to fetch message %s during webhook processing",
                            message_id,
                        )
                        raise RuntimeError(
                            f"Failed to process Outlook webhook message {message_id}"
                        ) from e

        # Callback for batch
        if synced_messages and self._on_batch_complete:
            self._on_batch_complete(synced_messages)

        return synced_messages

    async def handle_validation(self, validation_token: str) -> str:
        """
        Handle Microsoft Graph subscription validation request.

        When creating a subscription, Graph sends a validation request
        that must return the validationToken.

        Args:
            validation_token: Token from query parameter

        Returns:
            The validation token to confirm subscription
        """
        logger.info("[OutlookSync] Handling subscription validation")
        return validation_token

    async def force_sync(self) -> list[OutlookSyncedMessage]:
        """
        Force an immediate sync.

        Returns:
            List of synced messages
        """
        if not self._state or not self._state.delta_link:
            return await self._initial_sync()

        return await self._incremental_sync()

    def _extract_message_id(self, resource: str) -> str | None:
        """Extract message ID from Graph resource path."""
        # Resource format: "Users/{userId}/Messages/{messageId}"
        # or "me/messages/{messageId}"
        parts = resource.split("/")
        # Check for both "Messages" and "messages" (case-insensitive)
        parts_lower = [p.lower() for p in parts]
        if "messages" in parts_lower:
            idx = parts_lower.index("messages")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        return None

    async def _initial_sync(self) -> list[OutlookSyncedMessage]:
        """Perform initial full sync."""
        async with self._sync_lock:
            self._status = OutlookSyncStatus.SYNCING
            synced_messages: list[OutlookSyncedMessage] = []

            try:
                if not self._connector or not self._state:
                    return []

                # Log without exposing full email address
                email_masked = (
                    self._state.email_address[:2] + "***"
                    if self._state.email_address
                    else "unknown"
                )
                logger.info("[OutlookSync] Starting initial sync for %s", email_masked)

                # Get folders to sync
                all_folders = await self._connector.list_folders()
                folders_to_sync = [
                    f
                    for f in all_folders
                    if f.display_name in self.config.sync_folders
                    and f.display_name not in self.config.exclude_folders
                ]

                if not folders_to_sync:
                    # Default to Inbox
                    folders_to_sync = [f for f in all_folders if f.display_name == "Inbox"]

                # Sync each folder
                for folder in folders_to_sync:
                    # Get delta link for this folder
                    _, _, delta_link = await self._connector.get_delta(folder_id=folder.id)
                    if delta_link:
                        self._state.delta_link = delta_link

                    if folder.id not in self._state.synced_folder_ids:
                        self._state.synced_folder_ids.append(folder.id)

                    # Fetch recent messages
                    from datetime import timedelta

                    since_date = datetime.now(timezone.utc) - timedelta(
                        days=self.config.initial_sync_days
                    )
                    filter_query = f"receivedDateTime ge {since_date.isoformat()}"

                    page_token = None
                    for _page in range(_MAX_PAGES):
                        message_ids, page_token = await self._connector.list_messages(
                            folder_id=folder.id,
                            query=filter_query,
                            max_results=self.config.max_messages_per_sync,
                            page_token=page_token,
                        )

                        for msg_id in message_ids:
                            try:
                                msg = await self._connector.get_message(msg_id)
                                synced = await self._process_message(msg, is_new=False)
                                if synced:
                                    synced_messages.append(synced)
                            except (OSError, KeyError, ValueError) as e:
                                logger.exception(
                                    "[OutlookSync] Failed to fetch message %s during initial sync",
                                    msg_id,
                                )
                                raise RuntimeError(
                                    f"Initial sync failed while fetching Outlook message {msg_id}"
                                ) from e

                        if not page_token:
                            break

                # Update state
                self._state.last_sync = datetime.now(timezone.utc)
                self._state.initial_sync_complete = True
                self._state.total_messages_synced += len(synced_messages)

                await self._save_state()

                # Callback
                if self._on_batch_complete:
                    self._on_batch_complete(synced_messages)

                logger.info(
                    "[OutlookSync] Initial sync complete: %s messages synced", len(synced_messages)
                )

                self._status = (
                    OutlookSyncStatus.WATCHING if self._renewal_task else OutlookSyncStatus.IDLE
                )
                return synced_messages

            except (
                OSError,
                KeyError,
                ValueError,
                TypeError,
                ConnectionError,
                json.JSONDecodeError,
            ) as e:
                self._status = OutlookSyncStatus.ERROR
                if self._state:
                    self._state.last_error = "Initial sync failed"
                    self._state.sync_errors += 1
                logger.error("[OutlookSync] Initial sync failed: %s", e)
                raise

    async def _incremental_sync(self) -> list[OutlookSyncedMessage]:
        """Perform incremental sync using Delta Query API."""
        async with self._sync_lock:
            self._status = OutlookSyncStatus.SYNCING
            synced_messages: list[OutlookSyncedMessage] = []

            try:
                if not self._connector or not self._state:
                    return []

                if not self._state.delta_link:
                    return await self._initial_sync()

                logger.info("[OutlookSync] Starting incremental sync with delta link...")

                delta_link = self._state.delta_link
                new_message_ids: set[str] = set()

                while delta_link:
                    changes, next_link, new_delta_link = await self._connector.get_delta(
                        delta_link=delta_link
                    )

                    if not changes and not next_link:
                        if new_delta_link:
                            self._state.delta_link = new_delta_link
                        break

                    # Collect changed message IDs
                    for change in changes:
                        if change.get("@removed"):
                            continue
                        new_message_ids.add(change["id"])

                    if next_link:
                        delta_link = next_link
                    else:
                        if new_delta_link:
                            self._state.delta_link = new_delta_link
                        break

                # Fetch and process changed messages
                for msg_id in new_message_ids:
                    try:
                        msg = await self._connector.get_message(msg_id)
                        synced = await self._process_message(msg, is_new=True)
                        if synced:
                            synced_messages.append(synced)
                    except (OSError, KeyError, ValueError) as e:
                        logger.exception(
                            "[OutlookSync] Failed to fetch message %s during incremental sync",
                            msg_id,
                        )
                        raise RuntimeError(
                            f"Incremental sync failed while fetching Outlook message {msg_id}"
                        ) from e

                # Update state
                self._state.last_sync = datetime.now(timezone.utc)
                self._state.total_messages_synced += len(synced_messages)

                await self._save_state()

                # Callback
                if synced_messages and self._on_batch_complete:
                    self._on_batch_complete(synced_messages)

                logger.info(
                    "[OutlookSync] Incremental sync complete: %s new messages", len(synced_messages)
                )

                self._status = (
                    OutlookSyncStatus.WATCHING if self._renewal_task else OutlookSyncStatus.IDLE
                )
                return synced_messages

            except (
                OSError,
                KeyError,
                ValueError,
                TypeError,
                ConnectionError,
                json.JSONDecodeError,
            ) as e:
                self._status = OutlookSyncStatus.ERROR
                if self._state:
                    self._state.last_error = "Incremental sync failed"
                    self._state.sync_errors += 1
                logger.error("[OutlookSync] Incremental sync failed: %s", e)
                raise

    async def _process_message(
        self,
        message: EmailMessage,
        is_new: bool = True,
        change_type: str = "created",
    ) -> OutlookSyncedMessage | None:
        """Process a synced message: prioritize and notify."""
        priority_result = None

        if self.config.enable_prioritization and self._prioritizer:
            try:
                priority_result = await asyncio.wait_for(
                    self._prioritizer.score_email(message),
                    timeout=self.config.prioritization_timeout_seconds,
                )
                if self._state:
                    self._state.total_messages_prioritized += 1
            except asyncio.TimeoutError as e:
                logger.exception("[OutlookSync] Prioritization timeout for %s", message.id)
                raise RuntimeError(
                    f"Prioritization timed out for Outlook message {message.id}"
                ) from e
            except (ValueError, KeyError, TypeError, OSError) as e:
                logger.exception("[OutlookSync] Prioritization failed for %s", message.id)
                raise RuntimeError(f"Prioritization failed for Outlook message {message.id}") from e

        synced = OutlookSyncedMessage(
            message=message,
            priority_result=priority_result,
            account_id=f"{self.tenant_id}/{self.user_id}",
            is_new=is_new,
            change_type=change_type,
        )

        if self._on_message_synced:
            self._on_message_synced(synced)

        return synced

    async def _setup_subscription(self) -> None:
        """Set up Microsoft Graph change notification subscription."""
        if not self._connector or not self._state:
            return

        try:
            token = await self._connector._get_access_token()

            # Calculate expiration (max 4230 minutes for mail)
            expiration = datetime.now(timezone.utc) + timedelta(
                minutes=self.config.subscription_expiry_minutes
            )

            subscription_data = {
                "changeType": "created,updated",
                "notificationUrl": self.config.notification_url,
                "resource": "me/mailFolders('Inbox')/messages",
                "expirationDateTime": expiration.isoformat().replace("+00:00", "Z"),
                "clientState": self._state.client_state,
            }

            pool = get_http_pool()
            async with pool.get_session("outlook") as client:
                response = await client.post(
                    "https://graph.microsoft.com/v1.0/subscriptions",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=subscription_data,
                    timeout=30,
                )

                if response.status_code in (200, 201):
                    data = response.json()
                    self._state.subscription_id = data.get("id")
                    expiry_str = data.get("expirationDateTime", "")
                    if expiry_str:
                        self._state.subscription_expiry = datetime.fromisoformat(
                            expiry_str.replace("Z", "+00:00")
                        )

                    await self._save_state()
                    logger.info(
                        "[OutlookSync] Subscription created: %s, expires at %s",
                        self._state.subscription_id,
                        self._state.subscription_expiry,
                    )
                else:
                    raise RuntimeError(
                        "Failed to create Outlook subscription: "
                        f"{response.status_code} {response.text}"
                    )

        except (
            OSError,
            KeyError,
            ValueError,
            TypeError,
            ConnectionError,
            RuntimeError,
            json.JSONDecodeError,
        ):
            logger.exception("[OutlookSync] Subscription setup failed")
            raise

    async def _renew_subscription(self) -> None:
        """Renew the Microsoft Graph subscription."""
        if not self._connector or not self._state or not self._state.subscription_id:
            return

        try:
            token = await self._connector._get_access_token()

            # New expiration
            expiration = datetime.now(timezone.utc) + timedelta(
                minutes=self.config.subscription_expiry_minutes
            )

            pool = get_http_pool()
            async with pool.get_session("outlook") as client:
                response = await client.patch(
                    f"https://graph.microsoft.com/v1.0/subscriptions/{self._state.subscription_id}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "expirationDateTime": expiration.isoformat().replace("+00:00", "Z"),
                    },
                    timeout=30,
                )

                if response.status_code == 200:
                    data = response.json()
                    expiry_str = data.get("expirationDateTime", "")
                    if expiry_str:
                        self._state.subscription_expiry = datetime.fromisoformat(
                            expiry_str.replace("Z", "+00:00")
                        )

                    await self._save_state()
                    logger.info(
                        "[OutlookSync] Subscription renewed, new expiry: %s",
                        self._state.subscription_expiry,
                    )
                elif response.status_code == 404:
                    # Subscription expired/deleted, recreate
                    logger.warning("[OutlookSync] Subscription not found, recreating...")
                    self._state.subscription_id = None
                    await self._setup_subscription()
                else:
                    raise RuntimeError(
                        "Failed to renew Outlook subscription: "
                        f"{response.status_code} {response.text}"
                    )

        except (
            OSError,
            KeyError,
            ValueError,
            TypeError,
            ConnectionError,
            RuntimeError,
            json.JSONDecodeError,
        ):
            logger.exception("[OutlookSync] Subscription renewal failed")
            raise

    async def _delete_subscription(self) -> None:
        """Delete the Microsoft Graph subscription."""
        if not self._connector or not self._state or not self._state.subscription_id:
            return

        try:
            token = await self._connector._get_access_token()

            pool = get_http_pool()
            async with pool.get_session("outlook") as client:
                response = await client.delete(
                    f"https://graph.microsoft.com/v1.0/subscriptions/{self._state.subscription_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30,
                )

                if response.status_code in (200, 204):
                    logger.info(
                        "[OutlookSync] Subscription deleted: %s", self._state.subscription_id
                    )
                elif response.status_code == 404:
                    logger.debug("[OutlookSync] Subscription already deleted")
                else:
                    raise RuntimeError(
                        "Failed to delete Outlook subscription: "
                        f"{response.status_code} {response.text}"
                    )

            self._state.subscription_id = None
            self._state.subscription_expiry = None
            await self._save_state()

        except (
            OSError,
            KeyError,
            ValueError,
            TypeError,
            ConnectionError,
            RuntimeError,
            json.JSONDecodeError,
        ):
            logger.exception("[OutlookSync] Failed to delete subscription")
            raise

    async def _subscription_renewal_loop(self) -> None:
        """Background task to renew subscription before expiration."""
        while self._running:
            try:
                if self._state and self._state.subscription_expiry:
                    # Calculate time until renewal needed
                    now = datetime.now(timezone.utc)
                    renewal_time = self._state.subscription_expiry - timedelta(
                        minutes=self.config.renewal_buffer_minutes
                    )
                    sleep_seconds = max(60, (renewal_time - now).total_seconds())

                    await asyncio.sleep(sleep_seconds)

                    if not self._running:
                        break

                    await self._renew_subscription()
                else:
                    # No subscription, wait and retry
                    await asyncio.sleep(300)  # 5 minutes

            except asyncio.CancelledError:
                break
            except (OSError, ValueError, TypeError, ConnectionError, RuntimeError) as e:
                self._status = OutlookSyncStatus.ERROR
                if self._state:
                    self._state.last_error = "Subscription renewal loop failed"
                    self._state.sync_errors += 1
                logger.exception("[OutlookSync] Renewal loop failed")
                raise RuntimeError("Outlook subscription renewal loop failed") from e

    async def _load_state(self) -> OutlookSyncState | None:
        """Load sync state from backend."""
        state_key = f"outlook_sync:{self.tenant_id}:{self.user_id}"

        if self.config.state_backend == "redis" and self.config.redis_url:
            try:
                import redis.asyncio as redis

                client = redis.from_url(self.config.redis_url)
                data = await client.get(state_key)
                await client.close()
                if data:
                    return OutlookSyncState.from_dict(json.loads(data))
            except (
                OSError,
                ConnectionError,
                TypeError,
                json.JSONDecodeError,
                KeyError,
                ValueError,
            ):
                logger.exception("[OutlookSync] Failed to load state from Redis")
                raise

        elif self.config.state_backend == "postgres" and self.config.postgres_dsn:
            try:
                import asyncpg

                conn = await asyncpg.connect(self.config.postgres_dsn)
                row = await conn.fetchrow(
                    "SELECT state FROM outlook_sync_state WHERE key = $1",
                    state_key,
                )
                await conn.close()
                if row:
                    return OutlookSyncState.from_dict(json.loads(row["state"]))
            except (
                OSError,
                ConnectionError,
                TypeError,
                json.JSONDecodeError,
                KeyError,
                ValueError,
            ):
                logger.exception("[OutlookSync] Failed to load state from Postgres")
                raise

        return None

    async def _save_state(self) -> None:
        """Save sync state to backend."""
        if not self._state:
            return

        state_key = f"outlook_sync:{self.tenant_id}:{self.user_id}"
        state_json = json.dumps(self._state.to_dict())

        if self.config.state_backend == "redis" and self.config.redis_url:
            try:
                import redis.asyncio as redis

                client = redis.from_url(self.config.redis_url)
                await client.set(state_key, state_json)
                await client.close()
            except (OSError, ConnectionError, TypeError):
                logger.exception("[OutlookSync] Failed to save state to Redis")
                raise

        elif self.config.state_backend == "postgres" and self.config.postgres_dsn:
            try:
                import asyncpg

                conn = await asyncpg.connect(self.config.postgres_dsn)
                await conn.execute(
                    """
                    INSERT INTO outlook_sync_state (key, state, updated_at)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (key) DO UPDATE SET state = $2, updated_at = NOW()
                    """,
                    state_key,
                    state_json,
                )
                await conn.close()
            except (OSError, ConnectionError, TypeError):
                logger.exception("[OutlookSync] Failed to save state to Postgres")
                raise

    def get_stats(self) -> dict[str, Any]:
        """Get sync service statistics."""
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "status": self._status.value,
            "email_address": self._state.email_address if self._state else None,
            "delta_link": bool(self._state.delta_link) if self._state else False,
            "last_sync": (
                self._state.last_sync.isoformat() if self._state and self._state.last_sync else None
            ),
            "initial_sync_complete": self._state.initial_sync_complete if self._state else False,
            "subscription_active": bool(self._state and self._state.subscription_id),
            "subscription_expiry": (
                self._state.subscription_expiry.isoformat()
                if self._state and self._state.subscription_expiry
                else None
            ),
            "total_messages_synced": self._state.total_messages_synced if self._state else 0,
            "total_messages_prioritized": (
                self._state.total_messages_prioritized if self._state else 0
            ),
            "sync_errors": self._state.sync_errors if self._state else 0,
            "last_error": self._state.last_error if self._state else None,
        }


# Factory function
async def start_outlook_sync(
    tenant_id: str,
    user_id: str,
    refresh_token: str,
    config: OutlookSyncConfig | None = None,
    on_message: Callable[[OutlookSyncedMessage], None] | None = None,
) -> OutlookSyncService:
    """
    Quick start function for Outlook sync.

    Args:
        tenant_id: Tenant identifier
        user_id: User identifier
        refresh_token: OAuth refresh token
        config: Optional sync configuration
        on_message: Callback for each synced message

    Returns:
        Started OutlookSyncService
    """
    service = OutlookSyncService(
        tenant_id=tenant_id,
        user_id=user_id,
        config=config,
        on_message_synced=on_message,
    )

    await service.start(refresh_token=refresh_token)
    return service


__all__ = [
    "OutlookSyncService",
    "OutlookSyncConfig",
    "OutlookSyncState",
    "OutlookWebhookPayload",
    "OutlookSyncedMessage",
    "OutlookSyncStatus",
    "start_outlook_sync",
]
