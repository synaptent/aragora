"""
Slack Active Debate Storage for thread-based debate tracking.

Tracks active debates initiated from Slack, mapping them to threads
for progress updates and result routing.

Schema:
    CREATE TABLE slack_active_debates (
        debate_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        thread_ts TEXT,
        topic TEXT NOT NULL,
        user_id TEXT NOT NULL,
        status TEXT DEFAULT 'running',
        receipt_id TEXT,
        created_at REAL NOT NULL,
        completed_at REAL,
        error_message TEXT
    );
"""

from __future__ import annotations

import contextvars
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from aragora.config import resolve_db_path

logger = logging.getLogger(__name__)

# Storage configuration
SLACK_DEBATE_DB_PATH = resolve_db_path(os.environ.get("SLACK_DEBATE_DB_PATH", "slack_debates.db"))


@dataclass
class SlackActiveDebate:
    """Represents an active debate initiated from Slack."""

    debate_id: str
    workspace_id: str  # Slack team_id
    channel_id: str  # Channel where debate was started
    thread_ts: str | None  # Thread timestamp for updates
    topic: str  # Debate topic
    user_id: str  # Slack user who initiated
    status: str = "running"  # "pending", "running", "completed", "failed"
    receipt_id: str | None = None  # Decision receipt ID after completion
    created_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    completed_at: float | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "debate_id": self.debate_id,
            "workspace_id": self.workspace_id,
            "channel_id": self.channel_id,
            "thread_ts": self.thread_ts,
            "topic": self.topic,
            "user_id": self.user_id,
            "status": self.status,
            "receipt_id": self.receipt_id,
            "created_at": self.created_at,
            "created_at_iso": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
            "completed_at": self.completed_at,
            "completed_at_iso": (
                datetime.fromtimestamp(self.completed_at, tz=timezone.utc).isoformat()
                if self.completed_at
                else None
            ),
            "error_message": self.error_message,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> SlackActiveDebate:
        """Create from database row."""
        return cls(
            debate_id=row["debate_id"],
            workspace_id=row["workspace_id"],
            channel_id=row["channel_id"],
            thread_ts=row["thread_ts"],
            topic=row["topic"],
            user_id=row["user_id"],
            status=row["status"],
            receipt_id=row["receipt_id"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            error_message=row["error_message"],
        )

    @property
    def is_active(self) -> bool:
        """Check if debate is still active."""
        return self.status in ("pending", "running")

    @property
    def duration_seconds(self) -> float | None:
        """Get debate duration if completed."""
        if self.completed_at and self.created_at:
            return self.completed_at - self.created_at
        return None


class SlackDebateStore:
    """
    Storage for active Slack debates.

    Tracks debates initiated from Slack with their thread mappings
    for progress updates and result routing.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS slack_active_debates (
        debate_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        thread_ts TEXT,
        topic TEXT NOT NULL,
        user_id TEXT NOT NULL,
        status TEXT DEFAULT 'running',
        receipt_id TEXT,
        created_at REAL NOT NULL,
        completed_at REAL,
        error_message TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_slack_debates_workspace
        ON slack_active_debates(workspace_id);

    CREATE INDEX IF NOT EXISTS idx_slack_debates_channel
        ON slack_active_debates(channel_id);

    CREATE INDEX IF NOT EXISTS idx_slack_debates_status
        ON slack_active_debates(status);

    CREATE INDEX IF NOT EXISTS idx_slack_debates_user
        ON slack_active_debates(user_id);

    CREATE INDEX IF NOT EXISTS idx_slack_debates_thread
        ON slack_active_debates(workspace_id, channel_id, thread_ts);
    """

    def __init__(self, db_path: str | None = None):
        """Initialize the debate store.

        Args:
            db_path: Path to SQLite database file
        """
        self._db_path = resolve_db_path(db_path or SLACK_DEBATE_DB_PATH)
        # ContextVar for per-async-context connection (async-safe replacement for threading.local)
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            f"slackdebate_conn_{id(self)}", default=None
        )
        # Track all connections for proper cleanup
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.Lock()
        self._init_lock = threading.Lock()
        self._initialized = False

    def _get_connection(self) -> sqlite3.Connection:
        """Get per-context database connection."""
        conn = self._conn_var.get()
        if conn is None:
            # Ensure directory exists
            db_dir = os.path.dirname(self._db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)

            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._ensure_schema(conn)
            self._conn_var.set(conn)
            with self._connections_lock:
                self._connections.add(conn)
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """Ensure database schema exists."""
        with self._init_lock:
            if not self._initialized:
                conn.executescript(self.SCHEMA)
                conn.commit()
                self._initialized = True

    def save(self, debate: SlackActiveDebate) -> bool:
        """Save or update a debate.

        Args:
            debate: Debate to save

        Returns:
            True if saved successfully
        """
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO slack_active_debates
                (debate_id, workspace_id, channel_id, thread_ts, topic,
                 user_id, status, receipt_id, created_at, completed_at, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    debate.debate_id,
                    debate.workspace_id,
                    debate.channel_id,
                    debate.thread_ts,
                    debate.topic,
                    debate.user_id,
                    debate.status,
                    debate.receipt_id,
                    debate.created_at,
                    debate.completed_at,
                    debate.error_message,
                ),
            )
            conn.commit()
            logger.debug("Saved Slack debate: %s", debate.debate_id)
            return True

        except sqlite3.Error as e:
            logger.error("Failed to save debate: %s", e)
            return False

    def get(self, debate_id: str) -> SlackActiveDebate | None:
        """Get a debate by ID.

        Args:
            debate_id: Debate ID

        Returns:
            Debate or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM slack_active_debates WHERE debate_id = ?",
                (debate_id,),
            )
            row = cursor.fetchone()

            if row:
                return SlackActiveDebate.from_row(row)

            return None

        except sqlite3.Error as e:
            logger.error("Failed to get debate %s: %s", debate_id, e)
            return None

    def get_by_thread(
        self,
        workspace_id: str,
        channel_id: str,
        thread_ts: str,
    ) -> SlackActiveDebate | None:
        """Get a debate by its thread location.

        Args:
            workspace_id: Slack team_id
            channel_id: Channel ID
            thread_ts: Thread timestamp

        Returns:
            Debate or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM slack_active_debates
                WHERE workspace_id = ? AND channel_id = ? AND thread_ts = ?
                """,
                (workspace_id, channel_id, thread_ts),
            )
            row = cursor.fetchone()

            if row:
                return SlackActiveDebate.from_row(row)

            return None

        except sqlite3.Error as e:
            logger.error("Failed to get debate by thread: %s", e)
            return None

    def list_active(
        self,
        workspace_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SlackActiveDebate]:
        """List active debates.

        Args:
            workspace_id: Optional filter by workspace
            limit: Maximum number of debates to return
            offset: Pagination offset

        Returns:
            List of active debates
        """
        conn = self._get_connection()
        try:
            if workspace_id:
                cursor = conn.execute(
                    """
                    SELECT * FROM slack_active_debates
                    WHERE workspace_id = ? AND status IN ('pending', 'running')
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (workspace_id, limit, offset),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM slack_active_debates
                    WHERE status IN ('pending', 'running')
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                )

            return [SlackActiveDebate.from_row(row) for row in cursor.fetchall()]

        except sqlite3.Error as e:
            logger.error("Failed to list active debates: %s", e)
            return []

    def list_by_user(
        self,
        workspace_id: str,
        user_id: str,
        limit: int = 20,
    ) -> list[SlackActiveDebate]:
        """List debates by user.

        Args:
            workspace_id: Slack team_id
            user_id: User ID
            limit: Maximum number of debates

        Returns:
            List of debates
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM slack_active_debates
                WHERE workspace_id = ? AND user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (workspace_id, user_id, limit),
            )

            return [SlackActiveDebate.from_row(row) for row in cursor.fetchall()]

        except sqlite3.Error as e:
            logger.error("Failed to list debates by user: %s", e)
            return []

    def update_status(
        self,
        debate_id: str,
        status: str,
        receipt_id: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        """Update debate status.

        Args:
            debate_id: Debate ID
            status: New status
            receipt_id: Optional receipt ID for completed debates
            error_message: Optional error message for failed debates

        Returns:
            True if updated successfully
        """
        conn = self._get_connection()
        try:
            completed_at = None
            if status in ("completed", "failed"):
                completed_at = datetime.now(timezone.utc).timestamp()

            conn.execute(
                """
                UPDATE slack_active_debates
                SET status = ?, receipt_id = ?, error_message = ?, completed_at = ?
                WHERE debate_id = ?
                """,
                (status, receipt_id, error_message, completed_at, debate_id),
            )
            conn.commit()
            logger.info("Updated Slack debate %s status to %s", debate_id, status)
            return True

        except sqlite3.Error as e:
            logger.error("Failed to update debate %s: %s", debate_id, e)
            return False

    def update_thread(self, debate_id: str, thread_ts: str) -> bool:
        """Update debate thread timestamp.

        Called after initial message is posted to set thread_ts.

        Args:
            debate_id: Debate ID
            thread_ts: Thread timestamp from posted message

        Returns:
            True if updated successfully
        """
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE slack_active_debates SET thread_ts = ? WHERE debate_id = ?",
                (thread_ts, debate_id),
            )
            conn.commit()
            logger.debug("Updated thread_ts for debate %s", debate_id)
            return True

        except sqlite3.Error as e:
            logger.error("Failed to update thread for %s: %s", debate_id, e)
            return False

    def delete(self, debate_id: str) -> bool:
        """Delete a debate record.

        Args:
            debate_id: Debate ID

        Returns:
            True if deleted successfully
        """
        conn = self._get_connection()
        try:
            conn.execute(
                "DELETE FROM slack_active_debates WHERE debate_id = ?",
                (debate_id,),
            )
            conn.commit()
            logger.info("Deleted Slack debate: %s", debate_id)
            return True

        except sqlite3.Error as e:
            logger.error("Failed to delete debate %s: %s", debate_id, e)
            return False

    def cleanup_old(self, max_age_hours: int = 24) -> int:
        """Clean up old completed/failed debates.

        Args:
            max_age_hours: Maximum age in hours

        Returns:
            Number of debates cleaned up
        """
        conn = self._get_connection()
        try:
            cutoff = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)

            cursor = conn.execute(
                """
                DELETE FROM slack_active_debates
                WHERE status IN ('completed', 'failed')
                AND completed_at < ?
                """,
                (cutoff,),
            )
            conn.commit()

            deleted = cursor.rowcount
            if deleted > 0:
                logger.info("Cleaned up %s old Slack debates", deleted)
            return deleted

        except sqlite3.Error as e:
            logger.error("Failed to cleanup old debates: %s", e)
            return 0

    def get_stats(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Get debate statistics.

        Args:
            workspace_id: Optional filter by workspace

        Returns:
            Statistics dictionary
        """
        conn = self._get_connection()
        try:
            if workspace_id:
                base_filter = "WHERE workspace_id = ?"
                params: tuple = (workspace_id,)
            else:
                base_filter = ""
                params = ()

            total = conn.execute(
                # dynamic clause from internal state
                f"SELECT COUNT(*) FROM slack_active_debates {base_filter}",
                params,
            ).fetchone()[0]

            active = conn.execute(
                f"""
                SELECT COUNT(*) FROM slack_active_debates
                {base_filter + " AND" if base_filter else "WHERE"}
                status IN ('pending', 'running')
                """,  # dynamic clause from internal state
                params,
            ).fetchone()[0]

            completed = conn.execute(
                f"""
                SELECT COUNT(*) FROM slack_active_debates
                {base_filter + " AND" if base_filter else "WHERE"}
                status = 'completed'
                """,  # dynamic clause from internal state
                params,
            ).fetchone()[0]

            failed = conn.execute(
                f"""
                SELECT COUNT(*) FROM slack_active_debates
                {base_filter + " AND" if base_filter else "WHERE"}
                status = 'failed'
                """,  # dynamic clause from internal state
                params,
            ).fetchone()[0]

            return {
                "total_debates": total,
                "active_debates": active,
                "completed_debates": completed,
                "failed_debates": failed,
            }

        except sqlite3.Error as e:
            logger.error("Failed to get stats: %s", e)
            return {"total_debates": 0, "active_debates": 0}


# Singleton instance
_debate_store: SlackDebateStore | None = None


def get_slack_debate_store(db_path: str | None = None) -> SlackDebateStore:
    """Get or create the debate store singleton.

    Args:
        db_path: Optional path to database file

    Returns:
        SlackDebateStore instance
    """
    global _debate_store
    if _debate_store is None:
        _debate_store = SlackDebateStore(db_path)
    return _debate_store
