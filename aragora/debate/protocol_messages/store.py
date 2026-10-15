"""
Protocol Message Store for Aragora Debates.

Provides SQLite-backed persistence and querying for protocol messages.
Enables audit trails, debugging, and debate replay functionality.

Inspired by gastown's beads storage pattern for persistent work state.

Connection Pooling:
    Uses a bounded connection pool with configurable max_connections to prevent
    resource exhaustion. Connections are reused from the pool when available.

Async Support:
    AsyncProtocolMessageStore wraps the sync store and executes all database
    operations via asyncio.run_in_executor() to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import queue
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar
from collections.abc import Iterator

from .messages import ProtocolMessage, ProtocolMessageType

T = TypeVar("T")

logger = logging.getLogger(__name__)

# Module-level singleton
_protocol_store: ProtocolMessageStore | None = None
_store_lock = threading.Lock()


def get_protocol_store(db_path: str | None = None) -> ProtocolMessageStore:
    """Get or create the global protocol message store."""
    global _protocol_store
    with _store_lock:
        if _protocol_store is None:
            _protocol_store = ProtocolMessageStore(db_path)
        return _protocol_store


@dataclass
class QueryFilters:
    """Filters for querying protocol messages."""

    debate_id: str | None = None
    agent_id: str | None = None
    message_type: ProtocolMessageType | None = None
    message_types: list[ProtocolMessageType] | None = None
    round_number: int | None = None
    min_round: int | None = None
    max_round: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    correlation_id: str | None = None
    parent_message_id: str | None = None
    limit: int = 1000
    offset: int = 0
    order_by: str = "timestamp"
    order_desc: bool = False


class ConnectionPool:
    """Thread-safe SQLite connection pool with bounded size.

    Connections are created on-demand up to max_connections, then reused from
    the pool. When all connections are in use, get_connection() blocks until
    one becomes available.

    Thread Safety:
        All pool operations are protected by a threading.Lock. Each connection
        can only be used by one thread at a time.
    """

    def __init__(
        self,
        db_path: str,
        max_connections: int = 5,
        timeout: float = 30.0,
    ):
        """Initialize the connection pool.

        Args:
            db_path: Path to SQLite database (or ":memory:" for in-memory).
            max_connections: Maximum number of connections in the pool.
            timeout: Seconds to wait for a connection before raising an error.
        """
        self.db_path = db_path
        self.max_connections = max_connections
        self.timeout = timeout

        self._pool: queue.Queue[sqlite3.Connection] = queue.Queue(maxsize=max_connections)
        self._created_count = 0
        self._lock = threading.Lock()
        self._closed = False

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection."""
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def get_connection(self) -> sqlite3.Connection:
        """Get a connection from the pool.

        If pool is empty but under max_connections, creates a new connection.
        If at max_connections, blocks until a connection is returned.

        Returns:
            SQLite connection ready for use.

        Raises:
            RuntimeError: If pool is closed or timeout waiting for connection.
        """
        if self._closed:
            raise RuntimeError("Connection pool is closed")

        # Try to get from pool first (non-blocking)
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            pass

        # Check if we can create a new connection
        with self._lock:
            if self._created_count < self.max_connections:
                self._created_count += 1
                return self._create_connection()

        # Pool exhausted, wait for a connection
        try:
            return self._pool.get(timeout=self.timeout)
        except queue.Empty:
            raise RuntimeError(f"Connection pool exhausted: waited {self.timeout}s for connection")

    def return_connection(self, conn: sqlite3.Connection) -> None:
        """Return a connection to the pool.

        Args:
            conn: Connection to return.
        """
        if self._closed:
            try:
                conn.close()
            except (OSError, RuntimeError, ValueError) as exc:
                logger.debug("Failed to close connection: %s", exc)
            return

        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            # Pool full (shouldn't happen), close the extra connection
            try:
                conn.close()
            except (OSError, RuntimeError, ValueError) as e:
                logger.debug("Failed to close excess connection: %s", e)

    def close_all(self) -> None:
        """Close all connections in the pool."""
        self._closed = True

        # Drain the pool and close connections
        while True:
            try:
                conn = self._pool.get_nowait()
                try:
                    conn.close()
                except (OSError, RuntimeError, ValueError) as e:
                    logger.debug("Failed to close pooled connection during cleanup: %s", e)
            except queue.Empty:
                break

        with self._lock:
            self._created_count = 0


class ProtocolMessageStore:
    """
    SQLite-backed store for protocol messages.

    Features:
    - ACID-compliant persistence
    - Indexed queries by debate, agent, type, round
    - Time-range queries for audit trails
    - JSONL export for replay
    - Connection pooling with bounded size
    - Non-blocking async methods via run_in_executor

    Thread Safety:
        Uses a connection pool for thread-safe database access. Each operation
        acquires a connection, performs the work, and returns it to the pool.

    Async Safety:
        All async methods use asyncio.run_in_executor() to avoid blocking the
        event loop. For purely synchronous code, use the _sync suffix methods.
    """

    def __init__(self, db_path: str | None = None, max_connections: int = 5):
        """
        Initialize the protocol message store.

        Args:
            db_path: Path to SQLite database. If None, uses in-memory database.
            max_connections: Maximum number of pooled connections (default: 5).
        """
        self.db_path = db_path or ":memory:"
        self._pool = ConnectionPool(self.db_path, max_connections=max_connections)
        self._executor = None  # Uses default ThreadPoolExecutor
        self._init_schema()
        logger.info("ProtocolMessageStore initialized: %s", self.db_path)

    def _get_connection(self) -> sqlite3.Connection:
        """Get a connection from the pool."""
        return self._pool.get_connection()

    def _return_connection(self, conn: sqlite3.Connection) -> None:
        """Return a connection to the pool."""
        self._pool.return_connection(conn)

    async def _run_in_executor(self, func: functools.partial[T]) -> T:
        """Run a blocking function in a thread pool executor.

        Args:
            func: Partial function to execute

        Returns:
            Result from the function
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, func)

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        """Context manager for database cursor with connection pooling."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:  # noqa: BLE001 - Intentional: rollback transaction before re-raising any error
            conn.rollback()
            raise
        finally:
            cursor.close()
            self._return_connection(conn)

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS protocol_messages (
                    message_id TEXT PRIMARY KEY,
                    message_type TEXT NOT NULL,
                    debate_id TEXT NOT NULL,
                    agent_id TEXT,
                    round_number INTEGER,
                    timestamp TEXT NOT NULL,
                    correlation_id TEXT,
                    parent_message_id TEXT,
                    payload TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_protocol_debate
                ON protocol_messages(debate_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_protocol_agent
                ON protocol_messages(agent_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_protocol_type
                ON protocol_messages(message_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_protocol_round
                ON protocol_messages(debate_id, round_number)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_protocol_timestamp
                ON protocol_messages(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_protocol_correlation
                ON protocol_messages(correlation_id)
            """)

    async def record(self, message: ProtocolMessage) -> str:
        """
        Record a protocol message (async, non-blocking).

        Uses run_in_executor to avoid blocking the event loop.

        Args:
            message: The protocol message to record.

        Returns:
            The message_id of the recorded message.
        """
        return await self._run_in_executor(functools.partial(self.record_sync, message))

    def record_sync(self, message: ProtocolMessage) -> str:
        """Synchronous version of record for non-async contexts."""
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO protocol_messages (
                    message_id, message_type, debate_id, agent_id, round_number,
                    timestamp, correlation_id, parent_message_id, payload, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    message.message_id,
                    message.message_type.value,
                    message.debate_id,
                    message.agent_id,
                    message.round_number,
                    message.timestamp.isoformat(),
                    message.correlation_id,
                    message.parent_message_id,
                    (
                        json.dumps(message.payload.to_dict())
                        if message.payload and hasattr(message.payload, "to_dict")
                        else json.dumps(message.payload)
                        if message.payload
                        else None
                    ),
                    json.dumps(message.metadata) if message.metadata else None,
                ),
            )
        return message.message_id

    async def query(self, filters: QueryFilters | None = None) -> list[ProtocolMessage]:
        """
        Query protocol messages with filters (async, non-blocking).

        Uses run_in_executor to avoid blocking the event loop.

        Args:
            filters: Query filters. If None, returns all messages.

        Returns:
            List of matching protocol messages.
        """
        return await self._run_in_executor(functools.partial(self._query_sync_impl, filters))

    def query_sync(self, filters: QueryFilters | None = None) -> list[ProtocolMessage]:
        """Synchronous version of query."""
        import asyncio

        try:
            asyncio.get_running_loop()
            # We're in an async context, run synchronously
            return self._query_sync_impl(filters)
        except RuntimeError:
            # No running loop, use asyncio.run
            return asyncio.run(self.query(filters))

    def _query_sync_impl(self, filters: QueryFilters | None = None) -> list[ProtocolMessage]:
        """Internal synchronous query implementation with full filter support."""
        filters = filters or QueryFilters()
        conditions: list[str] = []
        params: list[Any] = []

        if filters.debate_id:
            conditions.append("debate_id = ?")
            params.append(filters.debate_id)

        if filters.agent_id:
            conditions.append("agent_id = ?")
            params.append(filters.agent_id)

        if filters.message_type:
            conditions.append("message_type = ?")
            params.append(filters.message_type.value)

        if filters.message_types:
            placeholders = ",".join("?" for _ in filters.message_types)
            conditions.append(f"message_type IN ({placeholders})")
            params.extend(mt.value for mt in filters.message_types)

        if filters.round_number is not None:
            conditions.append("round_number = ?")
            params.append(filters.round_number)

        if filters.min_round is not None:
            conditions.append("round_number >= ?")
            params.append(filters.min_round)

        if filters.max_round is not None:
            conditions.append("round_number <= ?")
            params.append(filters.max_round)

        if filters.start_time:
            conditions.append("timestamp >= ?")
            params.append(filters.start_time.isoformat())

        if filters.end_time:
            conditions.append("timestamp <= ?")
            params.append(filters.end_time.isoformat())

        if filters.correlation_id:
            conditions.append("correlation_id = ?")
            params.append(filters.correlation_id)

        if filters.parent_message_id:
            conditions.append("parent_message_id = ?")
            params.append(filters.parent_message_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        order_direction = "DESC" if filters.order_desc else "ASC"

        query = f"""
            SELECT * FROM protocol_messages
            WHERE {where_clause}
            ORDER BY {filters.order_by} {order_direction}
            LIMIT ? OFFSET ?
        """  # dynamic clause from internal state
        params.extend([filters.limit, filters.offset])

        with self._cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()

        return [self._row_to_message(row) for row in rows]

    async def get(self, message_id: str) -> ProtocolMessage | None:
        """Get a single message by ID (async, non-blocking).

        Uses run_in_executor to avoid blocking the event loop.
        """
        return await self._run_in_executor(functools.partial(self._get_sync, message_id))

    def _get_sync(self, message_id: str) -> ProtocolMessage | None:
        """Synchronous version of get for non-async contexts."""
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM protocol_messages WHERE message_id = ?",
                (message_id,),
            )
            row = cursor.fetchone()

        if row:
            return self._row_to_message(row)
        return None

    async def get_debate_timeline(
        self, debate_id: str, include_types: list[ProtocolMessageType] | None = None
    ) -> list[ProtocolMessage]:
        """
        Get full timeline of messages for a debate.

        Args:
            debate_id: The debate ID.
            include_types: Optional filter for specific message types.

        Returns:
            List of messages in chronological order.
        """
        filters = QueryFilters(
            debate_id=debate_id,
            message_types=include_types,
            order_by="timestamp",
            order_desc=False,
        )
        return await self.query(filters)

    async def get_round_messages(self, debate_id: str, round_number: int) -> list[ProtocolMessage]:
        """Get all messages for a specific round."""
        filters = QueryFilters(
            debate_id=debate_id,
            round_number=round_number,
            order_by="timestamp",
        )
        return await self.query(filters)

    async def get_agent_messages(self, debate_id: str, agent_id: str) -> list[ProtocolMessage]:
        """Get all messages from a specific agent in a debate."""
        filters = QueryFilters(
            debate_id=debate_id,
            agent_id=agent_id,
            order_by="timestamp",
        )
        return await self.query(filters)

    async def count(self, filters: QueryFilters | None = None) -> int:
        """Count messages matching filters (async, non-blocking).

        Uses run_in_executor to avoid blocking the event loop.
        """
        return await self._run_in_executor(functools.partial(self._count_sync, filters))

    def _count_sync(self, filters: QueryFilters | None = None) -> int:
        """Synchronous version of count for non-async contexts."""
        filters = filters or QueryFilters()
        conditions: list[str] = []
        params: list[Any] = []

        if filters.debate_id:
            conditions.append("debate_id = ?")
            params.append(filters.debate_id)

        if filters.message_type:
            conditions.append("message_type = ?")
            params.append(filters.message_type.value)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._cursor() as cursor:
            cursor.execute(
                # dynamic clause from internal state
                f"SELECT COUNT(*) FROM protocol_messages WHERE {where_clause}",
                params,
            )
            return cursor.fetchone()[0]

    async def export_jsonl(self, debate_id: str, output_path: str) -> int:
        """
        Export debate messages to JSONL file for replay (async, non-blocking).

        Uses run_in_executor to avoid blocking the event loop.

        Args:
            debate_id: The debate to export.
            output_path: Path to output file.

        Returns:
            Number of messages exported.
        """
        messages = await self.get_debate_timeline(debate_id)

        def _write_sync() -> int:
            with open(output_path, "w") as f:
                for msg in messages:
                    f.write(msg.to_json() + "\n")
            return len(messages)

        count = await self._run_in_executor(functools.partial(_write_sync))
        logger.info("Exported %s messages to %s", count, output_path)
        return count

    async def delete_debate(self, debate_id: str) -> int:
        """
        Delete all messages for a debate (async, non-blocking).

        Uses run_in_executor to avoid blocking the event loop.

        Args:
            debate_id: The debate to delete.

        Returns:
            Number of messages deleted.
        """
        count = await self._run_in_executor(functools.partial(self._delete_debate_sync, debate_id))
        logger.info("Deleted %s messages for debate %s...", count, debate_id[:8])
        return count

    def _delete_debate_sync(self, debate_id: str) -> int:
        """Synchronous version of delete_debate for non-async contexts."""
        with self._cursor() as cursor:
            cursor.execute(
                "DELETE FROM protocol_messages WHERE debate_id = ?",
                (debate_id,),
            )
            return cursor.rowcount

    async def cleanup_old(self, days: int = 30) -> int:
        """
        Delete messages older than specified days (async, non-blocking).

        Uses run_in_executor to avoid blocking the event loop.

        Args:
            days: Number of days to retain.

        Returns:
            Number of messages deleted.
        """
        count = await self._run_in_executor(functools.partial(self._cleanup_old_sync, days))
        logger.info("Cleaned up %s messages older than %s days", count, days)
        return count

    def _cleanup_old_sync(self, days: int = 30) -> int:
        """Synchronous version of cleanup_old for non-async contexts."""
        cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = cutoff - timedelta(days=days)

        with self._cursor() as cursor:
            cursor.execute(
                "DELETE FROM protocol_messages WHERE timestamp < ?",
                (cutoff.isoformat(),),
            )
            return cursor.rowcount

    def _row_to_message(self, row: sqlite3.Row) -> ProtocolMessage:
        """Convert database row to ProtocolMessage."""
        payload = None
        if row["payload"]:
            try:
                payload = json.loads(row["payload"])
            except json.JSONDecodeError:
                payload = row["payload"]

        metadata = {}
        if row["metadata"]:
            try:
                metadata = json.loads(row["metadata"])
            except json.JSONDecodeError as e:
                logger.debug("Failed to parse message metadata: %s", e)

        timestamp = row["timestamp"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        return ProtocolMessage(
            message_id=row["message_id"],
            message_type=ProtocolMessageType(row["message_type"]),
            debate_id=row["debate_id"],
            agent_id=row["agent_id"],
            round_number=row["round_number"],
            timestamp=timestamp,
            correlation_id=row["correlation_id"],
            parent_message_id=row["parent_message_id"],
            payload=payload,
            metadata=metadata,
        )

    def close(self) -> None:
        """Close all connections in the pool.

        Note: With connection pooling, close() now closes all pooled connections.
        For backward compatibility, this behaves the same as close_all().
        """
        self._pool.close_all()

    def close_all(self) -> None:
        """Close all pooled connections."""
        self._pool.close_all()


class AsyncProtocolMessageStore:
    """Async wrapper for ProtocolMessageStore that avoids blocking the event loop.

    All database operations are executed in a thread pool via run_in_executor
    to prevent blocking the async event loop when called from async contexts.

    Usage:
        store = AsyncProtocolMessageStore()

        # Record a message
        msg = ProtocolMessage(
            message_type=ProtocolMessageType.PROPOSAL_SUBMITTED,
            debate_id="debate-123",
            agent_id="claude-opus",
        )
        await store.record(msg)

        # Query messages
        messages = await store.query(QueryFilters(debate_id="debate-123"))

        # Get timeline
        timeline = await store.get_debate_timeline("debate-123")
    """

    def __init__(self, db_path: str | None = None, max_connections: int = 5):
        """Initialize the async protocol message store.

        Args:
            db_path: Path to SQLite database. If None, uses in-memory database.
            max_connections: Maximum number of pooled connections (default: 5).
        """
        self._sync_store = ProtocolMessageStore(db_path, max_connections=max_connections)
        self._executor = None  # Uses default ThreadPoolExecutor

    async def _run_in_executor(self, func: functools.partial[T]) -> T:
        """Run a blocking function in a thread pool executor.

        Args:
            func: Partial function to execute

        Returns:
            Result from the function
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, func)

    async def record(self, message: ProtocolMessage) -> str:
        """Record a protocol message (async, non-blocking).

        Args:
            message: The protocol message to record.

        Returns:
            The message_id of the recorded message.
        """
        return await self._run_in_executor(functools.partial(self._sync_store.record_sync, message))

    async def query(self, filters: QueryFilters | None = None) -> list[ProtocolMessage]:
        """Query protocol messages with filters (async, non-blocking).

        Args:
            filters: Query filters. If None, returns all messages.

        Returns:
            List of matching protocol messages.
        """
        return await self._run_in_executor(
            functools.partial(self._sync_store._query_sync_impl, filters)
        )

    async def get(self, message_id: str) -> ProtocolMessage | None:
        """Get a single message by ID (async, non-blocking)."""

        def _get_sync() -> ProtocolMessage | None:
            with self._sync_store._cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM protocol_messages WHERE message_id = ?",
                    (message_id,),
                )
                row = cursor.fetchone()
            if row:
                return self._sync_store._row_to_message(row)
            return None

        return await self._run_in_executor(functools.partial(_get_sync))

    async def get_debate_timeline(
        self, debate_id: str, include_types: list[ProtocolMessageType] | None = None
    ) -> list[ProtocolMessage]:
        """Get full timeline of messages for a debate (async, non-blocking).

        Args:
            debate_id: The debate ID.
            include_types: Optional filter for specific message types.

        Returns:
            List of messages in chronological order.
        """
        filters = QueryFilters(
            debate_id=debate_id,
            message_types=include_types,
            order_by="timestamp",
            order_desc=False,
        )
        return await self.query(filters)

    async def get_round_messages(self, debate_id: str, round_number: int) -> list[ProtocolMessage]:
        """Get all messages for a specific round (async, non-blocking)."""
        filters = QueryFilters(
            debate_id=debate_id,
            round_number=round_number,
            order_by="timestamp",
        )
        return await self.query(filters)

    async def get_agent_messages(self, debate_id: str, agent_id: str) -> list[ProtocolMessage]:
        """Get all messages from a specific agent in a debate (async, non-blocking)."""
        filters = QueryFilters(
            debate_id=debate_id,
            agent_id=agent_id,
            order_by="timestamp",
        )
        return await self.query(filters)

    async def count(self, filters: QueryFilters | None = None) -> int:
        """Count messages matching filters (async, non-blocking)."""
        filters = filters or QueryFilters()

        def _count_sync() -> int:
            conditions: list[str] = []
            params: list[Any] = []

            if filters.debate_id:
                conditions.append("debate_id = ?")
                params.append(filters.debate_id)

            if filters.message_type:
                conditions.append("message_type = ?")
                params.append(filters.message_type.value)

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            with self._sync_store._cursor() as cursor:
                cursor.execute(
                    # dynamic clause from internal state
                    f"SELECT COUNT(*) FROM protocol_messages WHERE {where_clause}",
                    params,
                )
                return cursor.fetchone()[0]

        return await self._run_in_executor(functools.partial(_count_sync))

    async def export_jsonl(self, debate_id: str, output_path: str) -> int:
        """Export debate messages to JSONL file for replay (async, non-blocking).

        Args:
            debate_id: The debate to export.
            output_path: Path to output file.

        Returns:
            Number of messages exported.
        """
        messages = await self.get_debate_timeline(debate_id)

        def _write_sync() -> int:
            with open(output_path, "w") as f:
                for msg in messages:
                    f.write(msg.to_json() + "\n")
            return len(messages)

        count = await self._run_in_executor(functools.partial(_write_sync))
        logger.info("Exported %s messages to %s", count, output_path)
        return count

    async def delete_debate(self, debate_id: str) -> int:
        """Delete all messages for a debate (async, non-blocking).

        Args:
            debate_id: The debate to delete.

        Returns:
            Number of messages deleted.
        """

        def _delete_sync() -> int:
            with self._sync_store._cursor() as cursor:
                cursor.execute(
                    "DELETE FROM protocol_messages WHERE debate_id = ?",
                    (debate_id,),
                )
                return cursor.rowcount

        count = await self._run_in_executor(functools.partial(_delete_sync))
        logger.info("Deleted %s messages for debate %s...", count, debate_id[:8])
        return count

    async def cleanup_old(self, days: int = 30) -> int:
        """Delete messages older than specified days (async, non-blocking).

        Args:
            days: Number of days to retain.

        Returns:
            Number of messages deleted.
        """

        def _cleanup_sync() -> int:
            cutoff = datetime.now(timezone.utc).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            ) - timedelta(days=days)

            with self._sync_store._cursor() as cursor:
                cursor.execute(
                    "DELETE FROM protocol_messages WHERE timestamp < ?",
                    (cutoff.isoformat(),),
                )
                return cursor.rowcount

        count = await self._run_in_executor(functools.partial(_cleanup_sync))
        logger.info("Cleaned up %s messages older than %s days", count, days)
        return count

    def close(self) -> None:
        """Close all connections in the pool."""
        self._sync_store.close()

    def close_all(self) -> None:
        """Close all pooled connections."""
        self._sync_store.close_all()

    @property
    def db_path(self) -> str:
        """Get the database path."""
        return self._sync_store.db_path
