"""
Persistent Message Queue for Slack Delivery.

Provides reliable message delivery with automatic retry for failed Slack API calls.
Messages are persisted to survive server restarts and retry with exponential backoff.

Features:
- SQLite-backed persistence
- Exponential backoff with jitter
- Dead letter queue for permanently failed messages
- Background processor for automatic retry
- Workspace-aware message routing

"Messages that matter deserve a second (or tenth) chance."
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aragora.config import resolve_db_path

logger = logging.getLogger(__name__)


class MessageStatus(str, Enum):
    """Status of a queued message."""

    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"
    DEAD = "dead"  # Permanently failed after max retries


@dataclass
class QueuedMessage:
    """A message in the delivery queue."""

    id: str
    workspace_id: str
    channel_id: str
    text: str
    blocks: list[dict[str, Any]] | None = None
    thread_ts: str | None = None
    status: MessageStatus = MessageStatus.PENDING
    retries: int = 0
    last_error: str | None = None
    created_at: float = field(default_factory=time.time)
    next_retry_at: float | None = None
    delivered_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "channel_id": self.channel_id,
            "text": self.text,
            "blocks": self.blocks,
            "thread_ts": self.thread_ts,
            "status": self.status.value,
            "retries": self.retries,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "next_retry_at": self.next_retry_at,
            "delivered_at": self.delivered_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueuedMessage:
        return cls(
            id=data["id"],
            workspace_id=data["workspace_id"],
            channel_id=data["channel_id"],
            text=data["text"],
            blocks=data.get("blocks"),
            thread_ts=data.get("thread_ts"),
            status=MessageStatus(data.get("status", "pending")),
            retries=data.get("retries", 0),
            last_error=data.get("last_error"),
            created_at=data.get("created_at", time.time()),
            next_retry_at=data.get("next_retry_at"),
            delivered_at=data.get("delivered_at"),
            metadata=data.get("metadata", {}),
        )


class SlackMessageQueueStore:
    """SQLite-backed storage for the message queue."""

    def __init__(self, db_path: str = "slack_message_queue.db"):
        self._db_path = resolve_db_path(db_path)
        self._conn = None
        self._ensure_table()

    def _get_connection(self):
        """Get or create database connection."""
        if self._conn is None:
            import os
            import sqlite3

            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_table(self):
        """Create messages table if it doesn't exist."""
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS queued_messages (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                text TEXT NOT NULL,
                blocks TEXT,
                thread_ts TEXT,
                status TEXT DEFAULT 'pending',
                retries INTEGER DEFAULT 0,
                last_error TEXT,
                created_at REAL NOT NULL,
                next_retry_at REAL,
                delivered_at REAL,
                metadata TEXT,
                UNIQUE(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_status_retry
            ON queued_messages(status, next_retry_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspace
            ON queued_messages(workspace_id, status)
        """)
        conn.commit()

    def insert(self, message: QueuedMessage) -> bool:
        """Insert a new message into the queue."""
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO queued_messages
            (id, workspace_id, channel_id, text, blocks, thread_ts, status,
             retries, last_error, created_at, next_retry_at, delivered_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                message.id,
                message.workspace_id,
                message.channel_id,
                message.text,
                json.dumps(message.blocks) if message.blocks else None,
                message.thread_ts,
                message.status.value,
                message.retries,
                message.last_error,
                message.created_at,
                message.next_retry_at,
                message.delivered_at,
                json.dumps(message.metadata),
            ),
        )
        conn.commit()
        return True

    def get_pending(self, limit: int = 100) -> list[QueuedMessage]:
        """Get messages ready for retry."""
        conn = self._get_connection()
        now = time.time()
        cursor = conn.execute(
            """
            SELECT * FROM queued_messages
            WHERE status = 'pending'
              AND (next_retry_at IS NULL OR next_retry_at <= ?)
            ORDER BY created_at ASC
            LIMIT ?
        """,
            (now, limit),
        )
        return [self._row_to_message(row) for row in cursor.fetchall()]

    def mark_processing(self, message_id: str) -> bool:
        """Mark a message as being processed."""
        conn = self._get_connection()
        conn.execute(
            "UPDATE queued_messages SET status = 'processing' WHERE id = ?",
            (message_id,),
        )
        conn.commit()
        return True

    def mark_delivered(self, message_id: str) -> bool:
        """Mark a message as successfully delivered."""
        conn = self._get_connection()
        conn.execute(
            """
            UPDATE queued_messages
            SET status = 'delivered', delivered_at = ?
            WHERE id = ?
        """,
            (time.time(), message_id),
        )
        conn.commit()
        logger.info("Message %s delivered successfully", message_id)
        return True

    def mark_failed(
        self,
        message_id: str,
        error: str,
        next_retry_at: float | None = None,
    ) -> bool:
        """Mark a message as failed with optional retry time."""
        conn = self._get_connection()
        conn.execute(
            """
            UPDATE queued_messages
            SET status = 'pending', last_error = ?, retries = retries + 1,
                next_retry_at = ?
            WHERE id = ?
        """,
            (error, next_retry_at, message_id),
        )
        conn.commit()
        return True

    def mark_dead(self, message_id: str, error: str) -> bool:
        """Move message to dead letter queue (permanently failed)."""
        conn = self._get_connection()
        conn.execute(
            """
            UPDATE queued_messages
            SET status = 'dead', last_error = ?
            WHERE id = ?
        """,
            (error, message_id),
        )
        conn.commit()
        logger.warning("Message %s moved to dead letter queue: %s", message_id, error)
        return True

    def get(self, message_id: str) -> QueuedMessage | None:
        """Get a specific message by ID."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM queued_messages WHERE id = ?", (message_id,))
        row = cursor.fetchone()
        return self._row_to_message(row) if row else None

    def get_stats(self) -> dict[str, int]:
        """Get queue statistics."""
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM queued_messages
            GROUP BY status
        """)
        stats = {row["status"]: row["count"] for row in cursor.fetchall()}
        return {
            "pending": stats.get("pending", 0),
            "processing": stats.get("processing", 0),
            "delivered": stats.get("delivered", 0),
            "failed": stats.get("failed", 0),
            "dead": stats.get("dead", 0),
            "total": sum(stats.values()),
        }

    def get_dead_letters(self, limit: int = 100) -> list[QueuedMessage]:
        """Get messages in the dead letter queue."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT * FROM queued_messages
            WHERE status = 'dead'
            ORDER BY created_at DESC
            LIMIT ?
        """,
            (limit,),
        )
        return [self._row_to_message(row) for row in cursor.fetchall()]

    def retry_dead_letter(self, message_id: str) -> bool:
        """Move a dead letter back to pending for retry."""
        conn = self._get_connection()
        conn.execute(
            """
            UPDATE queued_messages
            SET status = 'pending', next_retry_at = NULL, retries = 0
            WHERE id = ? AND status = 'dead'
        """,
            (message_id,),
        )
        conn.commit()
        return True

    def cleanup_delivered(self, older_than_hours: int = 24) -> int:
        """Remove delivered messages older than specified hours."""
        conn = self._get_connection()
        cutoff = time.time() - (older_than_hours * 3600)
        cursor = conn.execute(
            """
            DELETE FROM queued_messages
            WHERE status = 'delivered' AND delivered_at < ?
        """,
            (cutoff,),
        )
        conn.commit()
        return cursor.rowcount

    def _row_to_message(self, row) -> QueuedMessage:
        """Convert database row to QueuedMessage."""
        return QueuedMessage(
            id=row["id"],
            workspace_id=row["workspace_id"],
            channel_id=row["channel_id"],
            text=row["text"],
            blocks=json.loads(row["blocks"]) if row["blocks"] else None,
            thread_ts=row["thread_ts"],
            status=MessageStatus(row["status"]),
            retries=row["retries"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            next_retry_at=row["next_retry_at"],
            delivered_at=row["delivered_at"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )


class SlackMessageQueue:
    """
    High-level message queue with automatic retry processing.

    Provides reliable Slack message delivery with:
    - Automatic enqueue on failure
    - Exponential backoff with jitter
    - Background retry processing
    - Dead letter handling for permanent failures

    Example:
        queue = SlackMessageQueue()

        # Start background processor
        await queue.start_processor()

        # Enqueue a failed message
        await queue.enqueue(
            workspace_id="T12345",
            channel_id="C67890",
            text="Hello, world!",
        )

        # Queue will automatically retry delivery
    """

    def __init__(
        self,
        store: SlackMessageQueueStore | None = None,
        max_retries: int = 10,
        base_delay: float = 60.0,
        max_delay: float = 3600.0,
        process_interval: float = 30.0,
    ):
        """
        Initialize message queue.

        Args:
            store: Storage backend (defaults to SQLite)
            max_retries: Maximum retry attempts before dead letter
            base_delay: Initial retry delay in seconds
            max_delay: Maximum retry delay in seconds
            process_interval: How often to check for pending messages
        """
        self._store = store or SlackMessageQueueStore()
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._process_interval = process_interval
        self._processor_task: asyncio.Task | None = None
        self._running = False

    async def enqueue(
        self,
        workspace_id: str,
        channel_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Add a message to the delivery queue.

        Args:
            workspace_id: Slack workspace ID
            channel_id: Target channel ID
            text: Message text
            blocks: Optional Block Kit blocks
            thread_ts: Optional thread timestamp for replies
            metadata: Optional metadata for tracking

        Returns:
            Message ID for tracking
        """
        import uuid

        message_id = str(uuid.uuid4())
        message = QueuedMessage(
            id=message_id,
            workspace_id=workspace_id,
            channel_id=channel_id,
            text=text,
            blocks=blocks,
            thread_ts=thread_ts,
            metadata=metadata or {},
        )

        if not self._store.insert(message):
            raise RuntimeError(f"Failed to persist queued Slack message {message_id}")
        logger.info("Enqueued message %s for %s/%s", message_id, workspace_id, channel_id)

        return message_id

    def _calculate_retry_delay(self, retries: int) -> float:
        """Calculate exponential backoff with jitter."""
        delay = min(self._base_delay * (2**retries), self._max_delay)
        jitter = random.uniform(0, delay * 0.1)  # 10% jitter  # noqa: S311 -- retry jitter
        return delay + jitter

    async def _send_message(self, message: QueuedMessage) -> bool:
        """Attempt to send a message via Slack API."""
        try:
            from aragora.storage.slack_workspace_store import get_slack_workspace_store

            # Get workspace credentials
            workspace_store = get_slack_workspace_store()
            workspace = workspace_store.get(message.workspace_id)

            if not workspace:
                raise ValueError(f"Workspace {message.workspace_id} not found")

            if not workspace.is_active:
                raise ValueError(f"Workspace {message.workspace_id} is not active")

            # Send via Slack connector
            from aragora.connectors.chat.slack import SlackConnector

            connector = SlackConnector(
                token=workspace.access_token,
                signing_secret=workspace.signing_secret,
            )

            response = await connector.send_message(
                channel_id=message.channel_id,
                text=message.text,
                blocks=message.blocks,
                thread_id=message.thread_ts,
            )

            if not response.success:
                error = response.error or "Slack API returned unsuccessful response"
                raise RuntimeError(f"Slack API send failed: {error}")

            return True

        except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
            logger.error("Failed to send message %s: %s", message.id, exc)
            raise RuntimeError(
                f"Slack message delivery failed for message {message.id} "
                f"to channel {message.channel_id} in workspace {message.workspace_id}"
            ) from exc

    async def process_pending(self) -> dict[str, int]:
        """
        Process pending messages in the queue.

        Returns:
            Summary of processed messages
        """
        stats = {"processed": 0, "delivered": 0, "failed": 0, "dead": 0}

        messages = self._store.get_pending(limit=100)

        for message in messages:
            stats["processed"] += 1
            self._store.mark_processing(message.id)

            try:
                await self._send_message(message)
                self._store.mark_delivered(message.id)
                stats["delivered"] += 1

            except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
                logger.warning("Message delivery failed for %s: %s", message.id, e)
                error = "Message delivery failed"

                if message.retries >= self._max_retries:
                    # Move to dead letter queue
                    self._store.mark_dead(message.id, error)
                    stats["dead"] += 1
                else:
                    # Schedule retry with exponential backoff
                    delay = self._calculate_retry_delay(message.retries)
                    next_retry = time.time() + delay
                    self._store.mark_failed(message.id, error, next_retry)
                    stats["failed"] += 1
                    logger.info(
                        "Message %s retry scheduled in %.0fs (attempt %s/%s)",
                        message.id,
                        delay,
                        message.retries + 1,
                        self._max_retries,
                    )

        return stats

    async def _processor_loop(self):
        """Background processor loop."""
        logger.info("Slack message queue processor started")

        while self._running:
            try:
                stats = await self.process_pending()
                if stats["processed"] > 0:
                    logger.info(
                        "Queue processed: %s delivered, %s retry, %s dead",
                        stats["delivered"],
                        stats["failed"],
                        stats["dead"],
                    )
            except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
                logger.exception("Queue processor error: %s", e)

            await asyncio.sleep(self._process_interval)

        logger.info("Slack message queue processor stopped")

    async def start_processor(self) -> asyncio.Task[Any]:
        """Start the background processor."""
        if self._running and self._processor_task is not None:
            return self._processor_task

        self._running = True
        if self._processor_task is None or self._processor_task.done():
            self._processor_task = asyncio.create_task(self._processor_loop())
        return self._processor_task

    async def stop_processor(self):
        """Stop the background processor."""
        self._running = False
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                logger.debug("Queue processor task cancelled")
            self._processor_task = None

    def get_stats(self) -> dict[str, Any]:
        """Get queue statistics."""
        store_stats = self._store.get_stats()
        return {
            **store_stats,
            "processor_running": self._running,
            "max_retries": self._max_retries,
            "process_interval": self._process_interval,
        }

    def get_dead_letters(self, limit: int = 100) -> list[QueuedMessage]:
        """Get messages in the dead letter queue."""
        return self._store.get_dead_letters(limit)

    def retry_dead_letter(self, message_id: str) -> bool:
        """Retry a dead letter message."""
        return self._store.retry_dead_letter(message_id)


# Module-level instance for convenience
_default_queue: SlackMessageQueue | None = None


def get_slack_message_queue() -> SlackMessageQueue:
    """Get or create the default message queue."""
    global _default_queue
    if _default_queue is None:
        _default_queue = SlackMessageQueue()
    return _default_queue


async def enqueue_slack_message(
    workspace_id: str,
    channel_id: str,
    text: str,
    blocks: list[dict[str, Any]] | None = None,
    thread_ts: str | None = None,
) -> str:
    """Convenience function to enqueue a message."""
    queue = get_slack_message_queue()
    return await queue.enqueue(
        workspace_id=workspace_id,
        channel_id=channel_id,
        text=text,
        blocks=blocks,
        thread_ts=thread_ts,
    )
