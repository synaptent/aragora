"""
Channel Subscription Storage for receipt and alert delivery.

Stores which channels should receive automated notifications (receipts, budget alerts).
Supports Slack, Teams, email, and webhook channels.

Schema:
    CREATE TABLE channel_subscriptions (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        channel_type TEXT NOT NULL,  -- 'slack', 'teams', 'email', 'webhook'
        channel_id TEXT NOT NULL,
        workspace_id TEXT,           -- Slack workspace or Teams tenant
        event_types TEXT NOT NULL,   -- JSON array: ["receipt", "budget_alert"]
        channel_name TEXT,           -- Human-readable channel name
        created_at REAL NOT NULL,
        created_by TEXT,
        is_active INTEGER DEFAULT 1,
        config TEXT,                 -- JSON: additional channel-specific config
        UNIQUE(org_id, channel_type, channel_id)
    );
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from aragora.config import resolve_db_path

logger = logging.getLogger(__name__)

# Storage configuration
CHANNEL_SUBSCRIPTION_DB_PATH = resolve_db_path(
    os.environ.get("CHANNEL_SUBSCRIPTION_DB_PATH", "channel_subscriptions.db")
)


class ChannelType(str, Enum):
    """Supported channel types for notifications."""

    SLACK = "slack"
    TEAMS = "teams"
    EMAIL = "email"
    WEBHOOK = "webhook"


class EventType(str, Enum):
    """Event types that can be subscribed to."""

    RECEIPT = "receipt"
    BUDGET_ALERT = "budget_alert"
    DEBATE_COMPLETE = "debate_complete"
    CONSENSUS_REACHED = "consensus_reached"


@dataclass
class ChannelSubscription:
    """Represents a channel subscription for notifications."""

    id: str
    org_id: str
    channel_type: ChannelType
    channel_id: str
    event_types: list[EventType]
    created_at: float  # Unix timestamp
    workspace_id: str | None = None
    channel_name: str | None = None
    created_by: str | None = None
    is_active: bool = True
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "org_id": self.org_id,
            "channel_type": self.channel_type.value
            if isinstance(self.channel_type, ChannelType)
            else self.channel_type,
            "channel_id": self.channel_id,
            "workspace_id": self.workspace_id,
            "channel_name": self.channel_name,
            "event_types": [e.value if isinstance(e, EventType) else e for e in self.event_types],
            "created_at": self.created_at,
            "created_at_iso": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
            "created_by": self.created_by,
            "is_active": self.is_active,
            "config": self.config,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> ChannelSubscription:
        """Create from database row."""
        event_types_raw = json.loads(row["event_types"] or "[]")
        event_types = []
        for et in event_types_raw:
            try:
                event_types.append(EventType(et))
            except ValueError:
                event_types.append(et)  # Keep as string if unknown

        channel_type = row["channel_type"]
        try:
            channel_type = ChannelType(channel_type)
        except ValueError:
            pass  # Keep as string if unknown

        config = {}
        if row["config"]:
            try:
                config = json.loads(row["config"])
            except json.JSONDecodeError as e:
                logger.warning("Failed to parse JSON data: %s", e)

        return cls(
            id=row["id"],
            org_id=row["org_id"],
            channel_type=channel_type,
            channel_id=row["channel_id"],
            workspace_id=row["workspace_id"],
            channel_name=row["channel_name"],
            event_types=event_types,
            created_at=row["created_at"],
            created_by=row["created_by"],
            is_active=bool(row["is_active"]),
            config=config,
        )


class ChannelSubscriptionStore:
    """SQLite-backed storage for channel subscriptions.

    Thread-safe implementation with connection pooling.
    """

    _instances: dict[str, ChannelSubscriptionStore] = {}

    def __init__(self, db_path: str | None = None):
        """Initialize the store.

        Args:
            db_path: Path to SQLite database. Defaults to CHANNEL_SUBSCRIPTION_DB_PATH.
        """
        self.db_path = resolve_db_path(db_path or CHANNEL_SUBSCRIPTION_DB_PATH)
        self._conn: sqlite3.Connection | None = None
        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        if self._conn is None:
            # Ensure data directory exists
            db_dir = os.path.dirname(self.db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)

            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS channel_subscriptions (
                id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                channel_type TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                workspace_id TEXT,
                channel_name TEXT,
                event_types TEXT NOT NULL,
                created_at REAL NOT NULL,
                created_by TEXT,
                is_active INTEGER DEFAULT 1,
                config TEXT,
                UNIQUE(org_id, channel_type, channel_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_subscriptions_org
            ON channel_subscriptions(org_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_subscriptions_active
            ON channel_subscriptions(is_active)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_subscriptions_type
            ON channel_subscriptions(channel_type)
        """)
        conn.commit()

    def create(self, subscription: ChannelSubscription) -> ChannelSubscription:
        """Create a new subscription.

        Args:
            subscription: Subscription to create.

        Returns:
            Created subscription with generated ID if not provided.

        Raises:
            ValueError: If subscription already exists for org/channel.
        """
        if not subscription.id:
            subscription.id = str(uuid4())

        if not subscription.created_at:
            subscription.created_at = time.time()

        event_types_json = json.dumps(
            [e.value if isinstance(e, EventType) else e for e in subscription.event_types]
        )
        channel_type_str = (
            subscription.channel_type.value
            if isinstance(subscription.channel_type, ChannelType)
            else subscription.channel_type
        )
        config_json = json.dumps(subscription.config) if subscription.config else None

        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO channel_subscriptions
                (id, org_id, channel_type, channel_id, workspace_id, channel_name,
                 event_types, created_at, created_by, is_active, config)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription.id,
                    subscription.org_id,
                    channel_type_str,
                    subscription.channel_id,
                    subscription.workspace_id,
                    subscription.channel_name,
                    event_types_json,
                    subscription.created_at,
                    subscription.created_by,
                    1 if subscription.is_active else 0,
                    config_json,
                ),
            )
            conn.commit()
            logger.info(
                "Created subscription %s for org %s to %s:%s",
                subscription.id,
                subscription.org_id,
                channel_type_str,
                subscription.channel_id,
            )
            return subscription
        except sqlite3.IntegrityError as e:
            raise ValueError(
                f"Subscription already exists for org {subscription.org_id} "
                f"and channel {subscription.channel_id}"
            ) from e

    def get(self, subscription_id: str) -> ChannelSubscription | None:
        """Get a subscription by ID.

        Args:
            subscription_id: Subscription ID.

        Returns:
            Subscription if found, None otherwise.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT * FROM channel_subscriptions WHERE id = ?",
            (subscription_id,),
        )
        row = cursor.fetchone()
        return ChannelSubscription.from_row(row) if row else None

    def get_by_org(
        self,
        org_id: str,
        channel_type: ChannelType | None = None,
        event_type: EventType | None = None,
        active_only: bool = True,
    ) -> list[ChannelSubscription]:
        """Get subscriptions for an organization.

        Args:
            org_id: Organization ID.
            channel_type: Filter by channel type.
            event_type: Filter by event type.
            active_only: Only return active subscriptions.

        Returns:
            List of matching subscriptions.
        """
        conn = self._get_connection()
        query = "SELECT * FROM channel_subscriptions WHERE org_id = ?"
        params: list[Any] = [org_id]

        if active_only:
            query += " AND is_active = 1"

        if channel_type:
            query += " AND channel_type = ?"
            params.append(
                channel_type.value if isinstance(channel_type, ChannelType) else channel_type
            )

        cursor = conn.execute(query, params)
        subscriptions = [ChannelSubscription.from_row(row) for row in cursor.fetchall()]

        # Filter by event type if specified
        if event_type:
            event_type_value = event_type.value if isinstance(event_type, EventType) else event_type
            subscriptions = [
                s
                for s in subscriptions
                if event_type_value
                in [e.value if isinstance(e, EventType) else e for e in s.event_types]
            ]

        return subscriptions

    def get_for_event(
        self,
        org_id: str,
        event_type: EventType,
    ) -> list[ChannelSubscription]:
        """Get active subscriptions for a specific event type.

        Args:
            org_id: Organization ID.
            event_type: Event type to get subscriptions for.

        Returns:
            List of subscriptions that should receive this event.
        """
        return self.get_by_org(org_id, event_type=event_type, active_only=True)

    def update(
        self,
        subscription_id: str,
        event_types: list[EventType] | None = None,
        is_active: bool | None = None,
        channel_name: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> ChannelSubscription | None:
        """Update a subscription.

        Args:
            subscription_id: Subscription ID.
            event_types: New event types (optional).
            is_active: New active status (optional).
            channel_name: New channel name (optional).
            config: New config (optional).

        Returns:
            Updated subscription if found, None otherwise.
        """
        subscription = self.get(subscription_id)
        if not subscription:
            return None

        conn = self._get_connection()
        updates = []
        params: list[Any] = []

        if event_types is not None:
            updates.append("event_types = ?")
            params.append(
                json.dumps([e.value if isinstance(e, EventType) else e for e in event_types])
            )
            subscription.event_types = event_types

        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)
            subscription.is_active = is_active

        if channel_name is not None:
            updates.append("channel_name = ?")
            params.append(channel_name)
            subscription.channel_name = channel_name

        if config is not None:
            updates.append("config = ?")
            params.append(json.dumps(config))
            subscription.config = config

        if updates:
            params.append(subscription_id)
            conn.execute(
                # dynamic clause from internal state
                f"UPDATE channel_subscriptions SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()
            logger.info("Updated subscription %s", subscription_id)

        return subscription

    def delete(self, subscription_id: str) -> bool:
        """Delete a subscription.

        Args:
            subscription_id: Subscription ID.

        Returns:
            True if deleted, False if not found.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            "DELETE FROM channel_subscriptions WHERE id = ?",
            (subscription_id,),
        )
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Deleted subscription %s", subscription_id)
        return deleted

    def deactivate(self, subscription_id: str) -> bool:
        """Deactivate a subscription (soft delete).

        Args:
            subscription_id: Subscription ID.

        Returns:
            True if deactivated, False if not found.
        """
        result = self.update(subscription_id, is_active=False)
        return result is not None

    def count_by_org(self, org_id: str, active_only: bool = True) -> int:
        """Count subscriptions for an organization.

        Args:
            org_id: Organization ID.
            active_only: Only count active subscriptions.

        Returns:
            Number of subscriptions.
        """
        conn = self._get_connection()
        query = "SELECT COUNT(*) FROM channel_subscriptions WHERE org_id = ?"
        params: list[Any] = [org_id]

        if active_only:
            query += " AND is_active = 1"

        cursor = conn.execute(query, params)
        return cursor.fetchone()[0]

    def clear(self) -> None:
        """Clear all subscriptions (for testing)."""
        conn = self._get_connection()
        conn.execute("DELETE FROM channel_subscriptions")
        conn.commit()


# Global instance (lazy initialization)
_store: ChannelSubscriptionStore | None = None
_store_lock = threading.Lock()


def get_channel_subscription_store() -> ChannelSubscriptionStore:
    """Get the global channel subscription store instance."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ChannelSubscriptionStore()
    return _store
