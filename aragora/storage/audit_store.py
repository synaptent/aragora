"""
AuditStore - SQLite backend for audit logging and compliance.

DEPRECATION NOTICE:
    This module provides user/organization-specific audit storage. For new code,
    use the unified audit system in aragora.audit instead:

        from aragora.audit import AuditLog, AuditEvent, AuditCategory

    The unified system supports all audit categories including AUTH, DATA,
    ADMIN, and BILLING events with compliance export (SOC 2, GDPR, HIPAA).

    This module is maintained for backward compatibility with existing
    storage code that depends on AuditStore for UserStore composition.

Extracted from UserStore to improve modularity.
Provides audit trail functionality for:
- User actions (login, logout, settings changes)
- Organization changes (member added/removed, tier changes)
- Subscription events (created, updated, cancelled)
- Security events (failed logins, password changes)
"""

from __future__ import annotations

__all__ = [
    "AuditStore",
    "get_audit_store",  # noqa: F822
    "reset_audit_store",  # noqa: F822
]

import contextvars
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Callable, Iterator

from aragora.config import resolve_db_path
from aragora.persistence.db_config import get_default_data_dir
from aragora.storage.backends import (
    POSTGRESQL_AVAILABLE,
    DatabaseBackend,
    PostgreSQLBackend,
    SQLiteBackend,
)

logger = logging.getLogger(__name__)


class AuditStore:
    """
    Database-backed storage for audit logging.

    Supports SQLite (default) and PostgreSQL backends.
    Can be used standalone or composed with UserStore.
    Thread-safe with connection pooling.
    """

    def __init__(
        self,
        db_path: Path | str = "audit.db",
        get_connection: Callable[[], sqlite3.Connection] | None = None,
        backend: str | None = None,
        database_url: str | None = None,
    ):
        """
        Initialize AuditStore.

        Args:
            db_path: Path to SQLite database file (used when backend="sqlite")
            get_connection: Optional connection factory (for sharing with UserStore)
            backend: Database backend ("sqlite" or "postgresql")
            database_url: PostgreSQL connection URL
        """
        self.db_path = Path(resolve_db_path(db_path))
        # ContextVar for per-async-context connection (async-safe replacement for threading.local)
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            f"auditstore_conn_{id(self)}", default=None
        )
        # Track all connections for proper cleanup
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.Lock()
        self._external_get_connection = get_connection

        # Backend selection is now handled by get_audit_store() using resolve_database_config().
        # This __init__ just accepts explicit parameters from the factory function.
        self.backend_type = backend or "sqlite"
        self._backend: DatabaseBackend | None = None

        # Only create backend if not using external connection
        if get_connection is None:
            if self.backend_type == "postgresql":
                if not database_url:
                    raise ValueError("PostgreSQL backend requires database_url parameter")
                if not POSTGRESQL_AVAILABLE:
                    raise ImportError("psycopg2 required for PostgreSQL")
                self._backend = PostgreSQLBackend(database_url)
                logger.info("AuditStore using PostgreSQL backend")
            else:
                self._backend = SQLiteBackend(str(db_path))
                logger.info("AuditStore using SQLite backend: %s", db_path)

            self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get per-context database connection (async-safe, legacy SQLite mode)."""
        if self._external_get_connection:
            return self._external_get_connection()

        conn = self._conn_var.get()
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._conn_var.set(conn)
            with self._connections_lock:
                self._connections.add(conn)
        return conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        """Context manager for database transactions (legacy SQLite mode)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except (sqlite3.Error, OSError, ValueError) as e:
            conn.rollback()
            logger.debug("Transaction rolled back due to: %s", e)
            raise

    def _init_db(self) -> None:
        """Initialize database schema."""
        if self._backend is None:
            return

        # Create audit_log table
        self._backend.execute_write("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                user_id TEXT,
                org_id TEXT,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT,
                old_value TEXT,
                new_value TEXT,
                metadata TEXT,
                ip_address TEXT,
                user_agent TEXT
            )
        """)

        # Create indexes for common queries
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_org ON audit_log(org_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)",
            "CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_log(resource_type, resource_id)",
        ]
        for idx_sql in indexes:
            try:
                self._backend.execute_write(idx_sql)
            except (OSError, RuntimeError, sqlite3.Error) as e:
                logger.debug("Index creation skipped: %s", e)

    # =========================================================================
    # Audit Logging Methods
    # =========================================================================

    def log_event(
        self,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
        metadata: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> int:
        """
        Log an audit event.

        Args:
            action: Action performed (e.g., 'subscription.created', 'tier.changed')
            resource_type: Type of resource (e.g., 'subscription', 'user', 'organization')
            resource_id: ID of the affected resource
            user_id: User who performed the action
            org_id: Organization context
            old_value: Previous value (for changes)
            new_value: New value (for changes)
            metadata: Additional context
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            Audit log entry ID
        """
        params = (
            datetime.now(timezone.utc).isoformat(),
            user_id,
            org_id,
            action,
            resource_type,
            resource_id,
            json.dumps(old_value) if old_value else None,
            json.dumps(new_value) if new_value else None,
            json.dumps(metadata or {}),
            ip_address,
            user_agent,
        )

        if self._backend is not None:
            self._backend.execute_write(
                """
                INSERT INTO audit_log
                (timestamp, user_id, org_id, action, resource_type, resource_id,
                 old_value, new_value, metadata, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            # PostgreSQL doesn't easily return lastrowid, return 0
            return 0

        # Legacy SQLite path
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_log
                (timestamp, user_id, org_id, action, resource_type, resource_id,
                 old_value, new_value, metadata, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            return cursor.lastrowid or 0

    def get_log(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        Query audit log entries.

        Args:
            org_id: Filter by organization
            user_id: Filter by user
            action: Filter by action (supports prefix match with *)
            resource_type: Filter by resource type
            since: Filter entries after this time
            until: Filter entries before this time
            limit: Maximum entries to return
            offset: Pagination offset

        Returns:
            List of audit log entries
        """
        conditions: list[str] = []
        params: list[Any] = []

        if org_id:
            conditions.append("org_id = ?")
            params.append(org_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if action:
            if action.endswith("*"):
                conditions.append("action LIKE ?")
                params.append(action[:-1] + "%")
            else:
                conditions.append("action = ?")
                params.append(action)
        if resource_type:
            conditions.append("resource_type = ?")
            params.append(resource_type)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since.isoformat())
        if until:
            conditions.append("timestamp <= ?")
            params.append(until.isoformat())

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        query = f"""
            SELECT id, timestamp, user_id, org_id, action, resource_type,
                   resource_id, old_value, new_value, metadata, ip_address, user_agent
            FROM audit_log
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """  # nosec B608 - where_clause built from hardcoded conditions

        def _row_to_dict(row: tuple) -> dict:
            return {
                "id": row[0],
                "timestamp": row[1],
                "user_id": row[2],
                "org_id": row[3],
                "action": row[4],
                "resource_type": row[5],
                "resource_id": row[6],
                "old_value": json.loads(row[7]) if row[7] else None,
                "new_value": json.loads(row[8]) if row[8] else None,
                "metadata": json.loads(row[9]) if row[9] else {},
                "ip_address": row[10],
                "user_agent": row[11],
            }

        if self._backend is not None:
            rows = self._backend.fetch_all(query, tuple(params))
            return [_row_to_dict(row) for row in rows]

        # Legacy SQLite path
        with self._transaction() as cursor:
            cursor.execute(query, params)
            return [_row_to_dict(row) for row in cursor.fetchall()]

    def get_log_count(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
    ) -> int:
        """Get count of audit log entries matching filters."""
        conditions: list[str] = []
        params: list[Any] = []

        if org_id:
            conditions.append("org_id = ?")
            params.append(org_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if action:
            if action.endswith("*"):
                conditions.append("action LIKE ?")
                params.append(action[:-1] + "%")
            else:
                conditions.append("action = ?")
                params.append(action)
        if resource_type:
            conditions.append("resource_type = ?")
            params.append(resource_type)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT COUNT(*) FROM audit_log WHERE {where_clause}"  # nosec B608

        if self._backend is not None:
            result = self._backend.fetch_one(query, tuple(params))
            return result[0] if result else 0

        # Legacy SQLite path
        with self._transaction() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()[0]

    def cleanup_old_entries(self, days: int = 90) -> int:
        """
        Delete audit log entries older than specified days.

        Args:
            days: Number of days to retain (default 90)

        Returns:
            Number of deleted entries
        """
        from datetime import timedelta

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff = cutoff_date.isoformat()

        if self._backend is not None:
            # For backend, we can't easily get rowcount, do a count first
            result = self._backend.fetch_one(
                "SELECT COUNT(*) FROM audit_log WHERE timestamp < ?",
                (cutoff,),
            )
            count = result[0] if result else 0
            if count > 0:
                self._backend.execute_write(
                    "DELETE FROM audit_log WHERE timestamp < ?",
                    (cutoff,),
                )
                logger.info("Cleaned up %s audit log entries older than %s days", count, days)
            return count

        # Legacy SQLite path
        with self._transaction() as cursor:
            cursor.execute(
                "DELETE FROM audit_log WHERE timestamp < ?",
                (cutoff,),
            )
            count = cursor.rowcount
            if count > 0:
                logger.info("Cleaned up %s audit log entries older than %s days", count, days)
            return count

    def get_recent_activity(
        self,
        user_id: str | None = None,
        org_id: str | None = None,
        hours: int = 24,
        limit: int = 50,
    ) -> list[dict]:
        """
        Get recent activity for a user or organization.

        Args:
            user_id: Filter by user
            org_id: Filter by organization
            hours: Look back period in hours
            limit: Maximum entries to return

        Returns:
            List of recent audit events
        """
        from datetime import timedelta

        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        return self.get_log(
            user_id=user_id,
            org_id=org_id,
            since=since,
            limit=limit,
        )

    def get_security_events(
        self,
        user_id: str | None = None,
        org_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get security-related audit events.

        Includes: login attempts, password changes, API key operations,
        permission changes, etc.

        Args:
            user_id: Filter by user
            org_id: Filter by organization
            limit: Maximum entries to return

        Returns:
            List of security audit events
        """
        # Security-related action prefixes
        security_actions = [
            "login.%",
            "password.%",
            "api_key.%",
            "permission.%",
            "auth.%",
            "lockout.%",
        ]

        all_events = []
        for action_pattern in security_actions:
            events = self.get_log(
                user_id=user_id,
                org_id=org_id,
                action=action_pattern.replace("%", "*"),
                limit=limit,
            )
            all_events.extend(events)

        # Sort by timestamp descending and limit
        all_events.sort(key=lambda e: e["timestamp"], reverse=True)
        return all_events[:limit]

    def close(self) -> None:
        """Close database connection if we own it."""
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        elif self._external_get_connection is None:
            with self._connections_lock:
                for conn in self._connections:
                    try:
                        conn.close()
                    except (sqlite3.Error, OSError) as e:
                        logger.debug("Error closing connection during cleanup: %s", e)
                self._connections.clear()


# Module-level singleton
_default_store: AuditStore | None = None
_store_lock = threading.Lock()


def get_audit_store(
    db_path: str | None = None,
    backend: str | None = None,
    database_url: str | None = None,
) -> AuditStore:
    """
    Get or create the default AuditStore instance.

    Uses unified preference order: Supabase → PostgreSQL → SQLite.

    Environment variables:
    - ARAGORA_AUDIT_STORE_BACKEND: Store-specific backend override
    - ARAGORA_DB_BACKEND: Global database backend fallback
    - SUPABASE_URL + SUPABASE_DB_PASSWORD: Supabase PostgreSQL (preferred)
    - DATABASE_URL or ARAGORA_POSTGRES_DSN: Self-hosted PostgreSQL

    Returns:
        Configured AuditStore instance
    """
    global _default_store

    # Resolve db_path using ARAGORA_DATA_DIR if not provided
    if db_path is None:
        data_dir = get_default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(data_dir / "audit.db")

    if _default_store is None:
        with _store_lock:
            if _default_store is None:
                # Use connection factory to determine backend and DSN
                from aragora.storage.connection_factory import (
                    resolve_database_config,
                    StorageBackendType,
                )

                # Check for explicit backend override, else use preference order
                store_backend = os.environ.get("ARAGORA_AUDIT_STORE_BACKEND")
                if not store_backend and backend is None:
                    config = resolve_database_config("audit", allow_sqlite=True)
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
                        # Get DSN from connection factory
                        config = resolve_database_config("audit", allow_sqlite=True)
                        database_url = database_url or config.dsn
                        backend = "postgresql"
                    else:
                        backend = store_backend

                _default_store = AuditStore(
                    db_path=db_path,
                    backend=backend,
                    database_url=database_url,
                )

                # Enforce distributed storage in production
                if _default_store.backend_type == "sqlite":
                    from aragora.storage.production_guards import (
                        require_distributed_store,
                        StorageMode,
                    )

                    require_distributed_store(
                        "audit_store",
                        StorageMode.SQLITE,
                        "Audit data must use distributed storage in production. "
                        "Configure Supabase or PostgreSQL.",
                    )

    return _default_store


def reset_audit_store() -> None:
    """Reset the default store instance (for testing)."""
    global _default_store
    with _store_lock:
        if _default_store is not None:
            _default_store.close()
            _default_store = None


# Backwards compatibility alias
log_audit_event = AuditStore.log_event
get_audit_log = AuditStore.get_log
get_audit_log_count = AuditStore.get_log_count
