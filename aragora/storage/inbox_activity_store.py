"""
Inbox Activity Store - Persistent Activity Log for Shared Inboxes.

Provides persistent storage for inbox activities like:
- Message assignments/reassignments
- Status changes (open -> in_progress -> resolved)
- Note additions
- SLA breaches
- Team member changes

Backends:
- SQLite: Default for single-instance deployments
- PostgreSQL: For production multi-instance deployments

Usage:
    from aragora.storage.inbox_activity_store import get_inbox_activity_store

    store = get_inbox_activity_store()
    await store.log_activity(activity)
    activities = await store.get_activities(inbox_id)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aragora.config import resolve_db_path
from aragora.storage.connection_factory import is_postgres_backend

from aragora.storage.backends import (
    POSTGRESQL_AVAILABLE,
    DatabaseBackend,
    PostgreSQLBackend,
    SQLiteBackend,
)

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_RETENTION_DAYS = int(
    os.environ.get("ARAGORA_INBOX_ACTIVITY_RETENTION_DAYS", "90")
)  # 90 days default
DEFAULT_DB_PATH = Path(resolve_db_path("inbox_activities.db"))


class InboxActivityAction:
    """Constants for inbox activity action types."""

    ASSIGNED = "assigned"
    REASSIGNED = "reassigned"
    STATUS_CHANGED = "status_changed"
    NOTE_ADDED = "note_added"
    SLA_BREACHED = "sla_breached"
    SLA_WARNING = "sla_warning"
    MEMBER_ADDED = "member_added"
    MEMBER_REMOVED = "member_removed"
    MEMBER_ROLE_CHANGED = "member_role_changed"
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_SENT = "message_sent"
    TAG_ADDED = "tag_added"
    TAG_REMOVED = "tag_removed"
    PRIORITY_CHANGED = "priority_changed"
    MERGED = "merged"
    SPLIT = "split"


@dataclass
class InboxActivity:
    """A shared inbox activity record."""

    inbox_id: str
    org_id: str
    actor_id: str
    action: str
    target_id: str | None = None  # message_id, member_id, etc.
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "inbox_id": self.inbox_id,
            "org_id": self.org_id,
            "actor_id": self.actor_id,
            "action": self.action,
            "target_id": self.target_id,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InboxActivity:
        """Create from dictionary."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        elif isinstance(created_at, (int, float)):
            created_at = datetime.fromtimestamp(created_at, tz=timezone.utc)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            inbox_id=data["inbox_id"],
            org_id=data["org_id"],
            actor_id=data["actor_id"],
            action=data["action"],
            target_id=data.get("target_id"),
            metadata=data.get("metadata", {}),
            created_at=created_at,
        )


class InboxActivityStore:
    """
    Database-backed storage for inbox activity logs.

    Supports SQLite (default) and PostgreSQL backends.
    Provides persistence for shared inbox activity tracking.
    """

    SCHEMA_STATEMENTS = [
        """
        CREATE TABLE IF NOT EXISTS inbox_activities (
            id TEXT PRIMARY KEY,
            inbox_id TEXT NOT NULL,
            org_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            target_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_activities_inbox ON inbox_activities(inbox_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_activities_org ON inbox_activities(org_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_activities_target ON inbox_activities(target_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_activities_action ON inbox_activities(action, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_activities_actor ON inbox_activities(actor_id, created_at DESC)",
    ]

    def __init__(
        self,
        db_path: Path | None = None,
        backend: str | None = None,
        database_url: str | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ):
        """
        Initialize inbox activity store.

        Args:
            db_path: Path to SQLite database (used when backend="sqlite")
            backend: Database backend ("sqlite" or "postgresql")
            database_url: PostgreSQL connection URL
            retention_days: Days to retain activities (default: 90)
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self.retention_days = retention_days

        # Determine backend type
        env_url = os.environ.get("DATABASE_URL") or os.environ.get("ARAGORA_DATABASE_URL")
        actual_url = database_url or env_url

        if backend is None:
            env_backend = os.environ.get("ARAGORA_DB_BACKEND", "sqlite").lower()
            backend = (
                "postgresql" if (actual_url and is_postgres_backend(env_backend)) else "sqlite"
            )

        self.backend_type = backend
        self._backend: DatabaseBackend | None = None

        if backend == "postgresql":
            if not actual_url:
                raise ValueError("PostgreSQL backend requires DATABASE_URL")
            if not POSTGRESQL_AVAILABLE:
                raise ImportError("psycopg2 required for PostgreSQL")
            self._backend = PostgreSQLBackend(actual_url)
            logger.info("InboxActivityStore using PostgreSQL backend")
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._backend = SQLiteBackend(str(self.db_path))
            logger.info("InboxActivityStore using SQLite backend: %s", self.db_path)

        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        if self._backend is None:
            return

        for statement in self.SCHEMA_STATEMENTS:
            try:
                self._backend.execute_write(statement)
            except (OSError, RuntimeError, ValueError) as e:
                logger.debug("Schema statement skipped: %s", e)

    # =========================================================================
    # Activity Methods
    # =========================================================================

    def log_activity(self, activity: InboxActivity) -> None:
        """
        Log an inbox activity.

        Args:
            activity: InboxActivity to persist
        """
        if self._backend is None:
            return

        created_at_ts = activity.created_at.timestamp()

        self._backend.execute_write(
            """
            INSERT INTO inbox_activities
            (id, inbox_id, org_id, actor_id, action, target_id, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                activity.id,
                activity.inbox_id,
                activity.org_id,
                activity.actor_id,
                activity.action,
                activity.target_id,
                json.dumps(activity.metadata),
                created_at_ts,
            ),
        )
        logger.debug("Logged inbox activity: %s for %s", activity.action, activity.inbox_id)

    def get_activity(self, activity_id: str) -> InboxActivity | None:
        """
        Get an activity by ID.

        Args:
            activity_id: Activity ID to retrieve

        Returns:
            InboxActivity or None if not found
        """
        if self._backend is None:
            return None

        row = self._backend.fetch_one(
            """
            SELECT id, inbox_id, org_id, actor_id, action, target_id, metadata_json, created_at
            FROM inbox_activities WHERE id = ?
            """,
            (activity_id,),
        )
        if row:
            return self._row_to_activity(row)
        return None

    def get_activities(
        self,
        inbox_id: str,
        limit: int = 100,
        offset: int = 0,
        after: datetime | None = None,
        action: str | None = None,
    ) -> list[InboxActivity]:
        """
        Get activities for an inbox.

        Args:
            inbox_id: Inbox ID to get activities for
            limit: Maximum activities to return
            offset: Pagination offset
            after: Only return activities after this datetime
            action: Filter by action type

        Returns:
            List of InboxActivity records
        """
        if self._backend is None:
            return []

        conditions = ["inbox_id = ?"]
        params: list[Any] = [inbox_id]

        if after:
            conditions.append("created_at > ?")
            params.append(after.timestamp())

        if action:
            conditions.append("action = ?")
            params.append(action)

        where_clause = " AND ".join(conditions)
        params.extend([limit, offset])

        rows = self._backend.fetch_all(
            f"""
            SELECT id, inbox_id, org_id, actor_id, action, target_id, metadata_json, created_at
            FROM inbox_activities
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,  # nosec B608 - where_clause built from hardcoded conditions  # noqa: S608
            tuple(params),
        )

        return [self._row_to_activity(row) for row in rows]

    def get_message_history(
        self,
        message_id: str,
        limit: int = 100,
    ) -> list[InboxActivity]:
        """
        Get activity history for a specific message.

        Args:
            message_id: Message ID to get history for
            limit: Maximum activities to return

        Returns:
            List of InboxActivity records for the message
        """
        if self._backend is None:
            return []

        rows = self._backend.fetch_all(
            """
            SELECT id, inbox_id, org_id, actor_id, action, target_id, metadata_json, created_at
            FROM inbox_activities
            WHERE target_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (message_id, limit),
        )

        return [self._row_to_activity(row) for row in rows]

    def get_org_activities(
        self,
        org_id: str,
        limit: int = 100,
        offset: int = 0,
        after: datetime | None = None,
    ) -> list[InboxActivity]:
        """
        Get all activities for an organization.

        Args:
            org_id: Organization ID
            limit: Maximum activities to return
            offset: Pagination offset
            after: Only return activities after this datetime

        Returns:
            List of InboxActivity records
        """
        if self._backend is None:
            return []

        conditions = ["org_id = ?"]
        params: list[Any] = [org_id]

        if after:
            conditions.append("created_at > ?")
            params.append(after.timestamp())

        where_clause = " AND ".join(conditions)
        params.extend([limit, offset])

        rows = self._backend.fetch_all(
            f"""
            SELECT id, inbox_id, org_id, actor_id, action, target_id, metadata_json, created_at
            FROM inbox_activities
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,  # nosec B608 - where_clause built from hardcoded conditions  # noqa: S608
            tuple(params),
        )

        return [self._row_to_activity(row) for row in rows]

    def get_actor_activities(
        self,
        actor_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[InboxActivity]:
        """
        Get all activities by a specific actor.

        Args:
            actor_id: Actor (user) ID
            limit: Maximum activities to return
            offset: Pagination offset

        Returns:
            List of InboxActivity records
        """
        if self._backend is None:
            return []

        rows = self._backend.fetch_all(
            """
            SELECT id, inbox_id, org_id, actor_id, action, target_id, metadata_json, created_at
            FROM inbox_activities
            WHERE actor_id = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (actor_id, limit, offset),
        )

        return [self._row_to_activity(row) for row in rows]

    def count_activities(
        self,
        inbox_id: str | None = None,
        org_id: str | None = None,
        action: str | None = None,
    ) -> int:
        """
        Count activities with optional filters.

        Args:
            inbox_id: Filter by inbox
            org_id: Filter by organization
            action: Filter by action type

        Returns:
            Count of matching activities
        """
        if self._backend is None:
            return 0

        conditions = []
        params: list[Any] = []

        if inbox_id:
            conditions.append("inbox_id = ?")
            params.append(inbox_id)
        if org_id:
            conditions.append("org_id = ?")
            params.append(org_id)
        if action:
            conditions.append("action = ?")
            params.append(action)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        row = self._backend.fetch_one(
            f"SELECT COUNT(*) FROM inbox_activities WHERE {where_clause}",  # nosec B608  # noqa: S608
            tuple(params),
        )
        return row[0] if row else 0

    def _row_to_activity(self, row: tuple) -> InboxActivity:
        """Convert a database row to an InboxActivity."""
        metadata = json.loads(row[6]) if row[6] else {}
        created_at = datetime.fromtimestamp(row[7], tz=timezone.utc)

        return InboxActivity(
            id=row[0],
            inbox_id=row[1],
            org_id=row[2],
            actor_id=row[3],
            action=row[4],
            target_id=row[5],
            metadata=metadata,
            created_at=created_at,
        )

    # =========================================================================
    # Cleanup Methods
    # =========================================================================

    def cleanup_expired(self) -> int:
        """
        Remove activities older than retention period.

        Returns:
            Number of entries removed
        """
        if self._backend is None:
            return 0

        cutoff = time.time() - (self.retention_days * 86400)

        result = self._backend.fetch_one(
            "SELECT COUNT(*) FROM inbox_activities WHERE created_at < ?",
            (cutoff,),
        )
        count = result[0] if result else 0

        if count > 0:
            self._backend.execute_write(
                "DELETE FROM inbox_activities WHERE created_at < ?",
                (cutoff,),
            )
            logger.info(
                "Cleaned up %s inbox activity entries older than %s days",
                count,
                self.retention_days,
            )

        return count

    def close(self) -> None:
        """Close database connection."""
        if self._backend is not None:
            self._backend.close()
            self._backend = None


# Module-level singleton
_default_store: InboxActivityStore | None = None
_store_lock = threading.Lock()


def get_inbox_activity_store(
    db_path: Path | None = None,
    backend: str | None = None,
    database_url: str | None = None,
) -> InboxActivityStore:
    """
    Get or create the default InboxActivityStore instance.

    Backend selection (in preference order):
    1. PostgreSQL (if DATABASE_URL configured)
    2. SQLite (fallback)

    Returns:
        Configured InboxActivityStore instance
    """
    global _default_store

    if _default_store is None:
        with _store_lock:
            if _default_store is None:
                # Use connection factory to determine backend and DSN
                from aragora.storage.connection_factory import (
                    resolve_database_config,
                    StorageBackendType,
                )

                store_backend = os.environ.get("ARAGORA_INBOX_ACTIVITY_STORE_BACKEND")
                if not store_backend and backend is None:
                    config = resolve_database_config("inbox_activity", allow_sqlite=True)
                    if config.backend_type in (
                        StorageBackendType.SUPABASE,
                        StorageBackendType.POSTGRES,
                    ):
                        backend = "postgresql"
                        database_url = database_url or config.dsn
                    else:
                        backend = "sqlite"
                elif store_backend:
                    store_backend = store_backend.lower()
                    if store_backend in ("postgres", "postgresql", "supabase"):
                        config = resolve_database_config("inbox_activity", allow_sqlite=True)
                        database_url = database_url or config.dsn
                        backend = "postgresql"
                    else:
                        backend = store_backend

                _default_store = InboxActivityStore(
                    db_path=db_path,
                    backend=backend,
                    database_url=database_url,
                )

    return _default_store


def reset_inbox_activity_store() -> None:
    """Reset the default store instance (for testing)."""
    global _default_store
    with _store_lock:
        if _default_store is not None:
            _default_store.close()
            _default_store = None


__all__ = [
    "InboxActivity",
    "InboxActivityAction",
    "InboxActivityStore",
    "get_inbox_activity_store",
    "reset_inbox_activity_store",
]
