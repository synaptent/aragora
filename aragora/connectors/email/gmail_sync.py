"""
Gmail Background Sync Service.

.. deprecated::
    This module is deprecated. For new implementations, use
    :class:`~aragora.connectors.enterprise.communication.gmail.GmailConnector`
    which provides the same functionality plus additional enterprise features:

    - Full Gmail API (send, reply, archive, labels)
    - Circuit breaker resilience
    - Knowledge Mound integration
    - Pub/Sub watch management (setup_watch, stop_watch)
    - State persistence (load_state, save_state)
    - Prioritization (sync_with_prioritization, rank_inbox)

    Migration example::

        # Old (deprecated)
        from aragora.connectors.email.gmail_sync import GmailSyncService
        service = GmailSyncService(tenant_id="t1", user_id="u1", config=config)
        await service.start(refresh_token=token)

        # New (recommended)
        from aragora.connectors.enterprise.communication.gmail import GmailConnector
        connector = GmailConnector()
        await connector.authenticate(refresh_token=token)
        await connector.setup_watch(topic_name="gmail-notifications")

Provides real-time Gmail synchronization using:
- Google Cloud Pub/Sub for push notifications
- History API for incremental message retrieval
- EmailPrioritizer integration for scoring
- Tenant-isolated sync state persistence

Architecture:
    1. Initial sync: Full inbox scan, stores history ID
    2. Webhook receives Pub/Sub notification when inbox changes
    3. History API fetches only changed messages
    4. EmailPrioritizer scores new messages
    5. Results published to message queue for processing

Usage:
    from aragora.connectors.email.gmail_sync import (
        GmailSyncService,
        GmailSyncConfig,
    )

    config = GmailSyncConfig(
        project_id="my-project",
        topic_name="gmail-notifications",
        subscription_name="gmail-sync-sub",
    )

    sync_service = GmailSyncService(
        tenant_id="tenant_123",
        user_id="user_456",
        config=config,
    )

    # Start background sync
    await sync_service.start()

    # Handle webhook from Pub/Sub
    await sync_service.handle_webhook(webhook_payload)

    # Stop sync
    await sync_service.stop()
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.observability.http_client_pool import get_http_pool

# Emit deprecation warning on import
warnings.warn(
    "aragora.connectors.email.gmail_sync is deprecated. "
    "Use aragora.connectors.enterprise.communication.gmail.GmailConnector instead, "
    "which provides the same functionality plus additional enterprise features.",
    DeprecationWarning,
    stacklevel=2,
)

if TYPE_CHECKING:
    from aragora.connectors.enterprise.communication.gmail import GmailConnector
    from aragora.connectors.enterprise.communication.models import EmailMessage
    from aragora.services.email_prioritization import EmailPrioritizer, EmailPriorityResult

logger = logging.getLogger(__name__)

_MAX_PAGES = 1000  # Safety cap for pagination loops


class SyncStatus(Enum):
    """Status of the sync service."""

    IDLE = "idle"
    SYNCING = "syncing"
    WATCHING = "watching"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class GmailSyncConfig:
    """Configuration for Gmail sync service."""

    # Google Cloud Pub/Sub settings
    project_id: str = ""
    topic_name: str = "gmail-notifications"
    subscription_name: str = "gmail-sync-sub"

    # Sync settings
    initial_sync_days: int = 7  # Days of history on initial sync
    max_messages_per_sync: int = 100
    sync_labels: list[str] = field(default_factory=lambda: ["INBOX"])
    exclude_labels: list[str] = field(default_factory=lambda: ["SPAM", "TRASH"])

    # Watch renewal (Gmail watch expires after ~7 days)
    watch_renewal_hours: int = 24 * 6  # Renew every 6 days

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
class GmailSyncState:
    """Persistent state for Gmail sync."""

    tenant_id: str
    user_id: str
    email_address: str = ""

    # Sync state
    history_id: str = ""
    last_sync: datetime | None = None
    initial_sync_complete: bool = False

    # Watch state
    watch_expiration: datetime | None = None
    watch_resource_id: str | None = None

    # Statistics
    total_messages_synced: int = 0
    total_messages_prioritized: int = 0
    sync_errors: int = 0
    last_error: str | None = None

    # Labels synced
    synced_labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "email_address": self.email_address,
            "history_id": self.history_id,
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
            "initial_sync_complete": self.initial_sync_complete,
            "watch_expiration": (
                self.watch_expiration.isoformat() if self.watch_expiration else None
            ),
            "watch_resource_id": self.watch_resource_id,
            "total_messages_synced": self.total_messages_synced,
            "total_messages_prioritized": self.total_messages_prioritized,
            "sync_errors": self.sync_errors,
            "last_error": self.last_error,
            "synced_labels": self.synced_labels,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GmailSyncState:
        """Create from dictionary."""
        state = cls(
            tenant_id=data.get("tenant_id", ""),
            user_id=data.get("user_id", ""),
            email_address=data.get("email_address", ""),
            history_id=data.get("history_id", ""),
            initial_sync_complete=data.get("initial_sync_complete", False),
            watch_resource_id=data.get("watch_resource_id"),
            total_messages_synced=data.get("total_messages_synced", 0),
            total_messages_prioritized=data.get("total_messages_prioritized", 0),
            sync_errors=data.get("sync_errors", 0),
            last_error=data.get("last_error"),
            synced_labels=data.get("synced_labels", []),
        )

        if data.get("last_sync"):
            state.last_sync = datetime.fromisoformat(data["last_sync"])
        if data.get("watch_expiration"):
            state.watch_expiration = datetime.fromisoformat(data["watch_expiration"])

        return state


@dataclass
class GmailWebhookPayload:
    """Parsed webhook payload from Gmail Pub/Sub."""

    message_id: str
    subscription: str
    email_address: str
    history_id: str
    raw_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_pubsub(cls, payload: dict[str, Any]) -> GmailWebhookPayload:
        """
        Parse Pub/Sub webhook payload.

        The payload format is:
        {
            "message": {
                "data": "<base64 encoded JSON>",
                "messageId": "...",
                "message_id": "...",  # Alternate field
                "publishTime": "..."
            },
            "subscription": "projects/project-id/subscriptions/sub-name"
        }

        The decoded data contains:
        {
            "emailAddress": "user@example.com",
            "historyId": "12345"
        }
        """
        message = payload.get("message", {})
        subscription = payload.get("subscription", "")

        # Decode base64 data
        data_b64 = message.get("data", "")
        try:
            data_json = base64.urlsafe_b64decode(data_b64).decode("utf-8")
            data = json.loads(data_json)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Failed to decode Pub/Sub data: %s", e)
            data = {}

        return cls(
            message_id=message.get("messageId") or message.get("message_id", ""),
            subscription=subscription,
            email_address=data.get("emailAddress", ""),
            history_id=str(data.get("historyId", "")),
            raw_data=payload,
        )


@dataclass
class SyncedMessage:
    """A message that was synced and prioritized."""

    message: EmailMessage
    priority_result: EmailPriorityResult | None = None
    sync_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    account_id: str = ""
    is_new: bool = True


class GmailSyncService:
    """
    Background sync service for Gmail.

    Provides:
    - Initial full sync on startup
    - Real-time incremental sync via Pub/Sub webhooks
    - Automatic watch renewal
    - Integration with EmailPrioritizer
    - Tenant-isolated state management
    """

    def __init__(
        self,
        tenant_id: str,
        user_id: str,
        config: GmailSyncConfig | None = None,
        gmail_connector: GmailConnector | None = None,
        prioritizer: EmailPrioritizer | None = None,
        on_message_synced: Callable[[SyncedMessage], None] | None = None,
        on_batch_complete: Callable[[list[SyncedMessage]], None] | None = None,
    ):
        """
        Initialize Gmail sync service.

        Args:
            tenant_id: Tenant identifier for isolation
            user_id: User identifier
            config: Sync configuration
            gmail_connector: Pre-configured Gmail connector
            prioritizer: Email prioritizer instance
            on_message_synced: Callback for each synced message
            on_batch_complete: Callback when a sync batch completes
        """
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.config = config or GmailSyncConfig()
        self._connector = gmail_connector
        self._prioritizer = prioritizer

        # Callbacks
        self._on_message_synced = on_message_synced
        self._on_batch_complete = on_batch_complete

        # State
        self._state: GmailSyncState | None = None
        self._status = SyncStatus.IDLE
        self._sync_lock = asyncio.Lock()
        self._watch_task: asyncio.Task | None = None
        self._running = False

    @property
    def status(self) -> SyncStatus:
        """Get current sync status."""
        return self._status

    @property
    def state(self) -> GmailSyncState | None:
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
            logger.warning("[GmailSync] Service already running")
            return True

        try:
            # Initialize connector if needed
            if not self._connector:
                from aragora.connectors.enterprise.communication.gmail import GmailConnector

                self._connector = GmailConnector()
                if refresh_token:
                    success = await self._connector.authenticate(refresh_token=refresh_token)
                    if not success:
                        raise ValueError("Gmail authentication failed")

            # Initialize prioritizer if needed
            if self.config.enable_prioritization and not self._prioritizer:
                from aragora.services.email_prioritization import EmailPrioritizer

                self._prioritizer = EmailPrioritizer(gmail_connector=self._connector)

            # Load or create state
            self._state = await self._load_state()
            if not self._state:
                self._state = GmailSyncState(
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                )

            # Get email address
            if not self._state.email_address:
                profile = await self._connector.get_user_info()
                self._state.email_address = profile.get("emailAddress", "")

            self._running = True
            self._status = SyncStatus.IDLE

            # Perform initial sync if needed
            if do_initial_sync and not self._state.initial_sync_complete:
                await self._initial_sync()

            # Set up Gmail watch for real-time notifications
            if self.config.project_id and self.config.topic_name:
                await self._setup_watch()
                self._watch_task = asyncio.create_task(self._watch_renewal_loop())

            logger.info(
                "[GmailSync] Started for %s (tenant: %s)", self._state.email_address, self.tenant_id
            )
            return True

        except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            self._status = SyncStatus.ERROR
            if self._state:
                self._state.last_error = "Sync service failed to start"
                self._state.sync_errors += 1
            logger.error("[GmailSync] Failed to start: %s", e)
            return False

    async def stop(self) -> None:
        """Stop the sync service."""
        self._running = False

        # Cancel watch renewal task
        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                logger.debug("[GmailSync] Watch task cancelled during stop")

        # Stop the watch
        if self._state and self._state.watch_resource_id:
            await self._stop_watch()

        # Save state
        await self._save_state()

        self._status = SyncStatus.STOPPED
        logger.info("[GmailSync] Stopped for %s/%s", self.tenant_id, self.user_id)

    async def handle_webhook(
        self,
        payload: dict[str, Any],
    ) -> list[SyncedMessage]:
        """
        Handle incoming Pub/Sub webhook notification.

        Args:
            payload: Raw webhook payload from Pub/Sub

        Returns:
            List of newly synced and prioritized messages
        """
        if not self._running:
            logger.warning("[GmailSync] Webhook received but service not running")
            return []

        webhook = GmailWebhookPayload.from_pubsub(payload)

        # Verify this is for us
        if self._state and webhook.email_address != self._state.email_address:
            logger.warning(
                "[GmailSync] Webhook for %s but expecting %s",
                webhook.email_address,
                self._state.email_address,
            )
            return []

        logger.info(
            "[GmailSync] Webhook received: historyId=%s for %s",
            webhook.history_id,
            webhook.email_address,
        )

        # Perform incremental sync
        return await self._incremental_sync(webhook.history_id)

    async def force_sync(self) -> list[SyncedMessage]:
        """
        Force an immediate sync.

        Returns:
            List of synced messages
        """
        if not self._state or not self._state.history_id:
            return await self._initial_sync()

        return await self._incremental_sync()

    async def _initial_sync(self) -> list[SyncedMessage]:
        """Perform initial full sync."""
        async with self._sync_lock:
            self._status = SyncStatus.SYNCING
            synced_messages: list[SyncedMessage] = []

            try:
                if not self._connector or not self._state:
                    return []

                # Log without exposing full email address
                email_masked = (
                    self._state.email_address[:2] + "***"
                    if self._state.email_address
                    else "unknown"
                )
                logger.info("[GmailSync] Starting initial sync for %s", email_masked)

                # Get current history ID
                profile = await self._connector.get_user_info()
                current_history_id = str(profile.get("historyId", ""))

                # Build date filter for initial sync
                from datetime import timedelta

                since_date = datetime.now() - timedelta(days=self.config.initial_sync_days)
                date_filter = f"after:{since_date.strftime('%Y/%m/%d')}"

                # Sync by label
                for label in self.config.sync_labels:
                    query = f"label:{label} {date_filter}"
                    message_ids, _ = await self._connector.list_messages(
                        query=query,
                        max_results=self.config.max_messages_per_sync,
                    )

                    for msg_id in message_ids:
                        try:
                            msg = await self._connector.get_message(msg_id)
                            synced = await self._process_message(msg, is_new=False)
                            if synced:
                                synced_messages.append(synced)
                        except (OSError, KeyError, ValueError) as e:
                            logger.warning("[GmailSync] Failed to fetch message %s: %s", msg_id, e)

                    if label not in self._state.synced_labels:
                        self._state.synced_labels.append(label)

                # Update state
                self._state.history_id = current_history_id
                self._state.last_sync = datetime.now(timezone.utc)
                self._state.initial_sync_complete = True
                self._state.total_messages_synced += len(synced_messages)

                await self._save_state()

                # Callback
                if self._on_batch_complete:
                    self._on_batch_complete(synced_messages)

                logger.info(
                    "[GmailSync] Initial sync complete: %s messages synced", len(synced_messages)
                )

                self._status = SyncStatus.WATCHING if self._watch_task else SyncStatus.IDLE
                return synced_messages

            except (OSError, KeyError, ValueError, json.JSONDecodeError) as e:
                self._status = SyncStatus.ERROR
                if self._state:
                    self._state.last_error = "Initial sync failed"
                    self._state.sync_errors += 1
                logger.error("[GmailSync] Initial sync failed: %s", e)
                raise

    async def _incremental_sync(
        self,
        new_history_id: str | None = None,
    ) -> list[SyncedMessage]:
        """
        Perform incremental sync using History API.

        Args:
            new_history_id: History ID from webhook (optional)

        Returns:
            List of newly synced messages
        """
        async with self._sync_lock:
            self._status = SyncStatus.SYNCING
            synced_messages: list[SyncedMessage] = []

            try:
                if not self._connector or not self._state:
                    return []

                if not self._state.history_id:
                    # No history ID - need initial sync
                    return await self._initial_sync()

                logger.info(
                    "[GmailSync] Incremental sync from history %s...", self._state.history_id[:20]
                )

                # Get history changes
                page_token = None
                new_message_ids: set[str] = set()
                latest_history_id = self._state.history_id

                for _page in range(_MAX_PAGES):
                    history, page_token, history_id = await self._connector.get_history(
                        start_history_id=self._state.history_id,
                        page_token=page_token,
                    )

                    if not history and not page_token:
                        # History ID expired
                        if not history_id:
                            logger.warning("[GmailSync] History ID expired, doing full sync")
                            self._state.history_id = ""
                            return await self._initial_sync()
                        break

                    # Extract new message IDs
                    for record in history:
                        for msg_added in record.get("messagesAdded", []):
                            msg_data = msg_added.get("message", {})
                            msg_id = msg_data.get("id")
                            labels = msg_data.get("labelIds", [])

                            # Check label filters
                            if self.config.sync_labels:
                                if not any(lbl in labels for lbl in self.config.sync_labels):
                                    continue
                            if any(lbl in labels for lbl in self.config.exclude_labels):
                                continue

                            if msg_id:
                                new_message_ids.add(msg_id)

                    if history_id:
                        latest_history_id = history_id

                    if not page_token:
                        break

                # Fetch and process new messages
                for msg_id in new_message_ids:
                    try:
                        msg = await self._connector.get_message(msg_id)
                        synced = await self._process_message(msg, is_new=True)
                        if synced:
                            synced_messages.append(synced)
                    except (OSError, KeyError, ValueError) as e:
                        logger.warning("[GmailSync] Failed to fetch message %s: %s", msg_id, e)

                # Update state
                self._state.history_id = latest_history_id
                self._state.last_sync = datetime.now(timezone.utc)
                self._state.total_messages_synced += len(synced_messages)

                await self._save_state()

                # Callback
                if synced_messages and self._on_batch_complete:
                    self._on_batch_complete(synced_messages)

                logger.info(
                    "[GmailSync] Incremental sync complete: %s new messages", len(synced_messages)
                )

                self._status = SyncStatus.WATCHING if self._watch_task else SyncStatus.IDLE
                return synced_messages

            except (OSError, KeyError, ValueError, json.JSONDecodeError) as e:
                self._status = SyncStatus.ERROR
                if self._state:
                    self._state.last_error = "Incremental sync failed"
                    self._state.sync_errors += 1
                logger.error("[GmailSync] Incremental sync failed: %s", e)
                raise

    async def _process_message(
        self,
        message: EmailMessage,
        is_new: bool = True,
    ) -> SyncedMessage | None:
        """
        Process a synced message: prioritize and notify.

        Args:
            message: Email message to process
            is_new: Whether this is a new message

        Returns:
            SyncedMessage or None if processing failed
        """
        priority_result = None

        # Prioritize if enabled
        if self.config.enable_prioritization and self._prioritizer:
            try:
                priority_result = await asyncio.wait_for(
                    self._prioritizer.score_email(message),
                    timeout=self.config.prioritization_timeout_seconds,
                )
                if self._state:
                    self._state.total_messages_prioritized += 1
            except asyncio.TimeoutError:
                logger.warning("[GmailSync] Prioritization timeout for %s", message.id)
            except (ValueError, KeyError, TypeError, OSError) as e:
                logger.warning("[GmailSync] Prioritization failed for %s: %s", message.id, e)

        synced = SyncedMessage(
            message=message,
            priority_result=priority_result,
            account_id=f"{self.tenant_id}/{self.user_id}",
            is_new=is_new,
        )

        # Callback for individual message
        if self._on_message_synced:
            self._on_message_synced(synced)

        return synced

    async def _setup_watch(self) -> None:
        """Set up Gmail push notifications via Pub/Sub."""
        if not self._connector or not self._state:
            return

        topic = f"projects/{self.config.project_id}/topics/{self.config.topic_name}"

        try:
            # Gmail watch API call
            token = await self._connector._get_access_token()

            pool = get_http_pool()
            async with pool.get_session("gmail") as client:
                response = await client.post(
                    "https://gmail.googleapis.com/gmail/v1/users/me/watch",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "topicName": topic,
                        "labelIds": self.config.sync_labels or ["INBOX"],
                        "labelFilterBehavior": "INCLUDE",
                    },
                    timeout=30,
                )

                if response.status_code == 200:
                    data = response.json()
                    self._state.history_id = str(data.get("historyId", self._state.history_id))
                    expiration = data.get("expiration")
                    if expiration:
                        # Expiration is in milliseconds
                        self._state.watch_expiration = datetime.fromtimestamp(
                            int(expiration) / 1000, tz=timezone.utc
                        )
                    # Note: Gmail API doesn't return resourceId for watch
                    self._state.watch_resource_id = "active"

                    await self._save_state()
                    logger.info(
                        "[GmailSync] Watch set up, expires at %s", self._state.watch_expiration
                    )
                else:
                    logger.error("[GmailSync] Failed to set up watch: %s", response.text)

        except (OSError, KeyError, ValueError, json.JSONDecodeError) as e:
            logger.error("[GmailSync] Watch setup failed: %s", e)

    async def _stop_watch(self) -> None:
        """Stop Gmail push notifications."""
        if not self._connector or not self._state:
            return

        try:
            token = await self._connector._get_access_token()

            pool = get_http_pool()
            async with pool.get_session("gmail") as client:
                response = await client.post(
                    "https://gmail.googleapis.com/gmail/v1/users/me/stop",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30,
                )

                if response.status_code == 204:
                    self._state.watch_resource_id = None
                    self._state.watch_expiration = None
                    await self._save_state()
                    logger.info("[GmailSync] Watch stopped")
                else:
                    logger.warning("[GmailSync] Stop watch returned %s", response.status_code)

        except (OSError, ValueError) as e:
            logger.warning("[GmailSync] Failed to stop watch: %s", e)

    async def _watch_renewal_loop(self) -> None:
        """Background task to renew watch before expiration."""
        while self._running:
            try:
                # Sleep until renewal time
                renewal_seconds = self.config.watch_renewal_hours * 3600
                await asyncio.sleep(renewal_seconds)

                if not self._running:
                    break

                # Renew watch
                logger.info("[GmailSync] Renewing watch...")
                await self._setup_watch()

            except asyncio.CancelledError:
                break
            except (OSError, ValueError) as e:
                logger.error("[GmailSync] Watch renewal failed: %s", e)
                await asyncio.sleep(60)  # Retry in 1 minute

    async def _load_state(self) -> GmailSyncState | None:
        """Load sync state from backend."""
        state_key = f"gmail_sync:{self.tenant_id}:{self.user_id}"

        if self.config.state_backend == "redis" and self.config.redis_url:
            try:
                import redis.asyncio as redis

                client = redis.from_url(self.config.redis_url)
                data = await client.get(state_key)
                await client.close()
                if data:
                    return GmailSyncState.from_dict(json.loads(data))
            except (OSError, ConnectionError, json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning("[GmailSync] Failed to load state from Redis: %s", e)

        elif self.config.state_backend == "postgres" and self.config.postgres_dsn:
            try:
                import asyncpg

                conn = await asyncpg.connect(self.config.postgres_dsn)
                row = await conn.fetchrow(
                    "SELECT state FROM gmail_sync_state WHERE key = $1",
                    state_key,
                )
                await conn.close()
                if row:
                    return GmailSyncState.from_dict(json.loads(row["state"]))
            except (OSError, ConnectionError, json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning("[GmailSync] Failed to load state from Postgres: %s", e)

        return None

    async def _save_state(self) -> None:
        """Save sync state to backend."""
        if not self._state:
            return

        state_key = f"gmail_sync:{self.tenant_id}:{self.user_id}"
        state_json = json.dumps(self._state.to_dict())

        if self.config.state_backend == "redis" and self.config.redis_url:
            try:
                import redis.asyncio as redis

                client = redis.from_url(self.config.redis_url)
                await client.set(state_key, state_json)
                await client.close()
            except (OSError, ConnectionError, TypeError) as e:
                logger.warning("[GmailSync] Failed to save state to Redis: %s", e)

        elif self.config.state_backend == "postgres" and self.config.postgres_dsn:
            try:
                import asyncpg

                conn = await asyncpg.connect(self.config.postgres_dsn)
                await conn.execute(
                    """
                    INSERT INTO gmail_sync_state (key, state, updated_at)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (key) DO UPDATE SET state = $2, updated_at = NOW()
                    """,
                    state_key,
                    state_json,
                )
                await conn.close()
            except (OSError, ConnectionError, TypeError) as e:
                logger.warning("[GmailSync] Failed to save state to Postgres: %s", e)

    def get_stats(self) -> dict[str, Any]:
        """Get sync service statistics."""
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "status": self._status.value,
            "email_address": self._state.email_address if self._state else None,
            "history_id": self._state.history_id if self._state else None,
            "last_sync": (
                self._state.last_sync.isoformat() if self._state and self._state.last_sync else None
            ),
            "initial_sync_complete": self._state.initial_sync_complete if self._state else False,
            "watch_active": bool(self._state and self._state.watch_resource_id),
            "watch_expiration": (
                self._state.watch_expiration.isoformat()
                if self._state and self._state.watch_expiration
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
async def start_gmail_sync(
    tenant_id: str,
    user_id: str,
    refresh_token: str,
    config: GmailSyncConfig | None = None,
    on_message: Callable[[SyncedMessage], None] | None = None,
) -> GmailSyncService:
    """
    Quick start function for Gmail sync.

    Args:
        tenant_id: Tenant identifier
        user_id: User identifier
        refresh_token: OAuth refresh token
        config: Optional sync configuration
        on_message: Callback for each synced message

    Returns:
        Started GmailSyncService
    """
    service = GmailSyncService(
        tenant_id=tenant_id,
        user_id=user_id,
        config=config,
        on_message_synced=on_message,
    )

    await service.start(refresh_token=refresh_token)
    return service


__all__ = [
    "GmailSyncService",
    "GmailSyncConfig",
    "GmailSyncState",
    "GmailWebhookPayload",
    "SyncedMessage",
    "SyncStatus",
    "start_gmail_sync",
]
