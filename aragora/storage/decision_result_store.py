"""
Decision Result Storage.

Provides persistent storage for decision routing results with:
- TTL-based expiration (default 24 hours)
- LRU eviction when max entries reached
- In-memory cache for fast reads
- SQLite persistence for durability

Replaces the in-memory _decision_results dict for production use.

Usage:
    from aragora.storage.decision_result_store import get_decision_result_store

    store = get_decision_result_store()
    await store.save(request_id, result_dict)
    result = await store.get(request_id)
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
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
# TTL can be configured via ARAGORA_DECISION_RETENTION_DAYS (default: 1 day = 86400s)
# For audit/compliance, set to 90 (days) or 365 for longer retention
DEFAULT_TTL_SECONDS = (
    int(os.environ.get("ARAGORA_DECISION_RETENTION_DAYS", "1")) * 86400
)  # Convert days to seconds
DEFAULT_MAX_ENTRIES = int(
    os.environ.get("ARAGORA_DECISION_MAX_ENTRIES", "10000")
)  # Maximum entries before LRU eviction
DEFAULT_CACHE_SIZE = 1000  # In-memory cache size
DEFAULT_DB_PATH = Path(resolve_db_path("decision_results.db"))
DEFAULT_CLEANUP_INTERVAL = 300  # 5 minutes


@dataclass
class DecisionResultEntry:
    """A stored decision result entry."""

    request_id: str
    status: str
    result: dict[str, Any]
    created_at: float = field(default_factory=time.time)
    completed_at: str | None = None
    error: str | None = None
    ttl_seconds: int = DEFAULT_TTL_SECONDS

    @property
    def expires_at(self) -> float:
        """Get expiration timestamp."""
        return self.created_at + self.ttl_seconds

    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_id": self.request_id,
            "status": self.status,
            "result": self.result,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> DecisionResultEntry:
        """Create from dictionary."""
        return cls(
            request_id=data["request_id"],
            status=data["status"],
            result=data.get("result", {}),
            created_at=data.get("created_at", time.time()),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
            ttl_seconds=ttl_seconds,
        )


class DecisionResultStore:
    """
    Persistent store for decision routing results.

    Features:
    - SQLite persistence for durability across restarts
    - In-memory LRU cache for fast reads
    - TTL-based automatic expiration
    - LRU eviction when max entries reached
    - Thread-safe operations

    Usage:
        store = DecisionResultStore()
        store.save("req-123", {"status": "completed", "result": {...}})
        entry = store.get("req-123")
    """

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        cache_size: int = DEFAULT_CACHE_SIZE,
        cleanup_interval: int = DEFAULT_CLEANUP_INTERVAL,
        backend: str | None = None,
        database_url: str | None = None,
    ):
        """
        Initialize the decision result store.

        Args:
            db_path: Path to SQLite database file
            ttl_seconds: Time-to-live for entries in seconds (default: 24 hours)
            max_entries: Maximum entries before LRU eviction (default: 10000)
            cache_size: In-memory cache size (default: 1000)
            cleanup_interval: Seconds between automatic cleanups (default: 5 min)
            backend: Database backend ("sqlite" or "postgresql")
            database_url: PostgreSQL connection URL
        """
        self._db_path = Path(resolve_db_path(db_path))
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._cache_size = cache_size
        self._cleanup_interval = cleanup_interval

        # In-memory LRU cache using OrderedDict
        self._cache: OrderedDict[str, DecisionResultEntry] = OrderedDict()
        self._cache_lock = threading.Lock()

        # ContextVar for per-async-context connection (async-safe replacement for threading.local)
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            f"decisionresult_conn_{id(self)}", default=None
        )
        # Track all connections for proper cleanup
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.Lock()
        self._last_cleanup = time.time()

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

        # Initialize backend
        if backend == "postgresql":
            if not actual_url:
                raise ValueError("PostgreSQL backend requires DATABASE_URL")
            if not POSTGRESQL_AVAILABLE:
                raise ImportError("psycopg2 required for PostgreSQL")
            self._backend = PostgreSQLBackend(actual_url)
            logger.info("DecisionResultStore using PostgreSQL backend")
        else:
            # SECURITY: Check production guards for SQLite usage
            try:
                from aragora.storage.production_guards import (
                    require_distributed_store,
                    StorageMode,
                )

                require_distributed_store(
                    "decision_result_store",
                    StorageMode.SQLITE,
                    "Decision result store using SQLite - use PostgreSQL for multi-instance deployments",
                )
            except ImportError:
                pass  # Guards not available, allow SQLite

            self._backend = SQLiteBackend(str(db_path))
            logger.info("DecisionResultStore using SQLite backend: %s", db_path)

        # Initialize database
        self._init_db()
        self._cleanup_expired()

        logger.info(
            "DecisionResultStore initialized: backend=%s, ttl=%ss, max=%s, cache=%s",
            backend,
            ttl_seconds,
            max_entries,
            cache_size,
        )

    def _get_connection(self):
        """Get per-context database connection."""
        conn = self._conn_var.get()
        if conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self._db_path),
                timeout=30.0,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            # Enable WAL mode for concurrent access
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._conn_var.set(conn)
            with self._connections_lock:
                self._connections.add(conn)
        return conn

    def _init_db(self) -> None:
        """Initialize database schema."""
        if self._backend is not None:
            # Use backend for schema creation
            self._backend.execute_write("""
                CREATE TABLE IF NOT EXISTS decision_results (
                    request_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at REAL NOT NULL,
                    completed_at TEXT,
                    error TEXT,
                    expires_at REAL NOT NULL
                )
            """)
            # Create indexes
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_decision_results_expires ON decision_results(expires_at)",
                "CREATE INDEX IF NOT EXISTS idx_decision_results_status ON decision_results(status)",
                "CREATE INDEX IF NOT EXISTS idx_decision_results_created ON decision_results(created_at DESC)",
            ]
            for idx_sql in indexes:
                try:
                    self._backend.execute_write(idx_sql)
                except (OSError, RuntimeError, sqlite3.Error) as e:
                    logger.debug("Index creation skipped: %s", e)
            return

        # Legacy path
        conn = self._get_connection()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS decision_results (
                request_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                result_json TEXT,
                created_at REAL NOT NULL,
                completed_at TEXT,
                error TEXT,
                expires_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_decision_results_expires
            ON decision_results(expires_at);

            CREATE INDEX IF NOT EXISTS idx_decision_results_status
            ON decision_results(status);

            CREATE INDEX IF NOT EXISTS idx_decision_results_created
            ON decision_results(created_at DESC);
        """)
        conn.commit()

    def save(self, request_id: str, data: dict[str, Any]) -> None:
        """
        Save a decision result.

        Args:
            request_id: Unique request identifier
            data: Result data including status, result, completed_at, error
        """
        now = time.time()
        expires_at = now + self._ttl_seconds

        entry = DecisionResultEntry(
            request_id=request_id,
            status=data.get("status", "unknown"),
            result=data.get("result", {}),
            created_at=data.get("created_at", now),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
            ttl_seconds=self._ttl_seconds,
        )

        params = (
            request_id,
            entry.status,
            json.dumps(entry.result),
            entry.created_at,
            entry.completed_at,
            entry.error,
            expires_at,
        )

        # Save to database
        if self._backend is not None:
            # Use ON CONFLICT for PostgreSQL compatibility
            if self.backend_type == "postgresql":
                self._backend.execute_write(
                    """
                    INSERT INTO decision_results
                    (request_id, status, result_json, created_at, completed_at, error, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (request_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        result_json = EXCLUDED.result_json,
                        completed_at = EXCLUDED.completed_at,
                        error = EXCLUDED.error,
                        expires_at = EXCLUDED.expires_at
                    """,
                    params,
                )
            else:
                self._backend.execute_write(
                    """
                    INSERT OR REPLACE INTO decision_results
                    (request_id, status, result_json, created_at, completed_at, error, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )
        else:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT OR REPLACE INTO decision_results
                (request_id, status, result_json, created_at, completed_at, error, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            conn.commit()

        # Update cache
        with self._cache_lock:
            # If entry exists, move to end (most recently used)
            if request_id in self._cache:
                self._cache.move_to_end(request_id)
            self._cache[request_id] = entry

            # Evict oldest if cache is full
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)

        # Maybe run cleanup
        self._maybe_cleanup()

        # Enforce max entries with LRU eviction
        self._enforce_max_entries()

    def get(self, request_id: str) -> dict[str, Any] | None:
        """
        Get a decision result by request ID.

        Args:
            request_id: Unique request identifier

        Returns:
            Result dict if found and not expired, None otherwise
        """
        # Check cache first
        with self._cache_lock:
            if request_id in self._cache:
                entry = self._cache[request_id]
                if not entry.is_expired:
                    # Move to end (most recently used)
                    self._cache.move_to_end(request_id)
                    return entry.to_dict()
                else:
                    # Remove expired entry from cache
                    del self._cache[request_id]

        # Fall back to database
        query = """
            SELECT request_id, status, result_json, created_at, completed_at, error, expires_at
            FROM decision_results
            WHERE request_id = ? AND expires_at > ?
        """
        params = (request_id, time.time())

        if self._backend is not None:
            row = self._backend.fetch_one(query, params)
        else:
            conn = self._get_connection()
            cursor = conn.execute(query, params)
            row = cursor.fetchone()

        if row:
            entry = DecisionResultEntry(
                request_id=row[0],
                status=row[1],
                result=json.loads(row[2] or "{}"),
                created_at=row[3],
                completed_at=row[4],
                error=row[5],
                ttl_seconds=self._ttl_seconds,
            )

            # Add to cache
            with self._cache_lock:
                self._cache[request_id] = entry
                self._cache.move_to_end(request_id)

                # Evict oldest if cache is full
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)

            return entry.to_dict()

        return None

    def get_status(self, request_id: str) -> dict[str, Any]:
        """
        Get decision status for polling.

        Args:
            request_id: Unique request identifier

        Returns:
            Status dict with request_id and status
        """
        result = self.get(request_id)
        if result:
            return {
                "request_id": request_id,
                "status": result.get("status", "unknown"),
                "completed_at": result.get("completed_at"),
            }
        return {
            "request_id": request_id,
            "status": "not_found",
        }

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """
        List recent decision results.

        Args:
            limit: Maximum number of results to return

        Returns:
            List of result summaries
        """
        query = """
            SELECT request_id, status, completed_at
            FROM decision_results
            WHERE expires_at > ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        params = (time.time(), limit)

        if self._backend is not None:
            rows = self._backend.fetch_all(query, params)
        else:
            conn = self._get_connection()
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        return [
            {
                "request_id": row[0],
                "status": row[1],
                "completed_at": row[2],
            }
            for row in rows
        ]

    def count(self) -> int:
        """Get total count of non-expired entries."""
        query = "SELECT COUNT(*) FROM decision_results WHERE expires_at > ?"
        params = (time.time(),)

        if self._backend is not None:
            result = self._backend.fetch_one(query, params)
            return result[0] if result else 0

        conn = self._get_connection()
        cursor = conn.execute(query, params)
        return cursor.fetchone()[0]

    def delete(self, request_id: str) -> bool:
        """
        Delete a decision result.

        Args:
            request_id: Unique request identifier

        Returns:
            True if deleted, False if not found
        """
        # Remove from cache
        with self._cache_lock:
            self._cache.pop(request_id, None)

        # Remove from database
        if self._backend is not None:
            # Check if exists first for return value
            result = self._backend.fetch_one(
                "SELECT 1 FROM decision_results WHERE request_id = ?",
                (request_id,),
            )
            if result:
                self._backend.execute_write(
                    "DELETE FROM decision_results WHERE request_id = ?",
                    (request_id,),
                )
                return True
            return False

        conn = self._get_connection()
        cursor = conn.execute(
            "DELETE FROM decision_results WHERE request_id = ?",
            (request_id,),
        )
        conn.commit()
        return cursor.rowcount > 0

    def _maybe_cleanup(self) -> None:
        """Run cleanup if interval has passed."""
        now = time.time()
        if now - self._last_cleanup >= self._cleanup_interval:
            self._cleanup_expired()
            self._last_cleanup = now

    def _cleanup_expired(self) -> None:
        """Remove expired entries from database."""
        try:
            if self._backend is not None:
                # Count first for logging
                result = self._backend.fetch_one(
                    "SELECT COUNT(*) FROM decision_results WHERE expires_at <= ?",
                    (time.time(),),
                )
                deleted = result[0] if result else 0
                if deleted > 0:
                    self._backend.execute_write(
                        "DELETE FROM decision_results WHERE expires_at <= ?",
                        (time.time(),),
                    )
                    logger.debug("Cleaned up %s expired decision results", deleted)
                return

            conn = self._get_connection()
            cursor = conn.execute(
                "DELETE FROM decision_results WHERE expires_at <= ?",
                (time.time(),),
            )
            conn.commit()
            deleted = cursor.rowcount
            if deleted > 0:
                logger.debug("Cleaned up %s expired decision results", deleted)
        except (OSError, RuntimeError, sqlite3.Error) as e:
            logger.warning("Failed to cleanup expired results: %s", e)

    def _enforce_max_entries(self) -> None:
        """Enforce maximum entries using LRU eviction."""
        try:
            if self._backend is not None:
                result = self._backend.fetch_one(
                    "SELECT COUNT(*) FROM decision_results WHERE expires_at > ?",
                    (time.time(),),
                )
                count = result[0] if result else 0

                if count > self._max_entries:
                    excess = count - self._max_entries
                    self._backend.execute_write(
                        """
                        DELETE FROM decision_results
                        WHERE request_id IN (
                            SELECT request_id FROM decision_results
                            WHERE expires_at > ?
                            ORDER BY created_at ASC
                            LIMIT ?
                        )
                        """,
                        (time.time(), excess),
                    )
                    logger.info(
                        "LRU evicted %s decision results (max: %s)", excess, self._max_entries
                    )
                return

            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT COUNT(*) FROM decision_results WHERE expires_at > ?",
                (time.time(),),
            )
            count = cursor.fetchone()[0]

            if count > self._max_entries:
                # Delete oldest entries beyond the limit
                excess = count - self._max_entries
                conn.execute(
                    """
                    DELETE FROM decision_results
                    WHERE request_id IN (
                        SELECT request_id FROM decision_results
                        WHERE expires_at > ?
                        ORDER BY created_at ASC
                        LIMIT ?
                    )
                    """,
                    (time.time(), excess),
                )
                conn.commit()
                logger.info("LRU evicted %s decision results (max: %s)", excess, self._max_entries)
        except (OSError, RuntimeError, sqlite3.Error) as e:
            logger.warning("Failed to enforce max entries: %s", e)

    def get_metrics(self) -> dict[str, Any]:
        """Get store metrics for monitoring."""
        with self._cache_lock:
            cache_size = len(self._cache)

        return {
            "total_entries": self.count(),
            "cache_size": cache_size,
            "cache_capacity": self._cache_size,
            "max_entries": self._max_entries,
            "ttl_seconds": self._ttl_seconds,
            "db_path": str(self._db_path),
            "backend_type": self.backend_type,
        }

    def close(self) -> None:
        """Close database connection/pool."""
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        # Close all tracked connections
        with self._connections_lock:
            for conn in self._connections:
                try:
                    conn.close()
                except (sqlite3.Error, OSError) as e:
                    logger.debug("Error closing connection: %s", e)
            self._connections.clear()


# Global singleton instance
_decision_result_store: DecisionResultStore | None = None
_store_lock = threading.Lock()


def get_decision_result_store(
    db_path: str | Path | None = None,
    backend: str | None = None,
    database_url: str | None = None,
    **kwargs,
) -> DecisionResultStore:
    """
    Get the global decision result store instance.

    Args:
        db_path: Optional custom database path
        backend: Database backend ("sqlite" or "postgresql")
        database_url: PostgreSQL connection URL
        **kwargs: Additional arguments for DecisionResultStore

    Returns:
        DecisionResultStore instance
    """
    global _decision_result_store

    with _store_lock:
        if _decision_result_store is None:
            path = db_path or os.environ.get(
                "ARAGORA_DECISION_RESULTS_DB",
                str(DEFAULT_DB_PATH),
            )
            _decision_result_store = DecisionResultStore(
                db_path=path,
                backend=backend,
                database_url=database_url,
                **kwargs,
            )

    return _decision_result_store


def reset_decision_result_store() -> None:
    """Reset the global store instance (for testing)."""
    global _decision_result_store
    with _store_lock:
        if _decision_result_store is not None:
            _decision_result_store.close()
            _decision_result_store = None


__all__ = [
    "DecisionResultStore",
    "DecisionResultEntry",
    "get_decision_result_store",
    "reset_decision_result_store",
]
