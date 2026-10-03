"""
ImpersonationStore - Database persistence for impersonation sessions and audit logs.

Provides durable storage for:
- Active impersonation sessions (survive server restarts)
- Complete audit trail of all impersonation actions

Supports SQLite (default) and PostgreSQL backends.

Usage:
    from aragora.storage.impersonation_store import get_impersonation_store

    store = get_impersonation_store()

    # Save session
    store.save_session(session)

    # Log audit entry
    store.save_audit_entry(entry)

    # Recover active sessions on startup
    sessions = store.get_active_sessions()
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from aragora.config import resolve_db_path
from aragora.storage.backends import (
    POSTGRESQL_AVAILABLE,
    DatabaseBackend,
    PostgreSQLBackend,
    SQLiteBackend,
)
from aragora.utils.datetime_helpers import parse_timestamp, utc_now

logger = logging.getLogger(__name__)


@dataclass
class SessionRecord:
    """Persistent session record."""

    session_id: str
    admin_user_id: str
    admin_email: str
    target_user_id: str
    target_email: str
    reason: str
    started_at: datetime
    expires_at: datetime
    ip_address: str
    user_agent: str
    actions_performed: int = 0
    ended_at: datetime | None = None
    ended_by: str | None = None  # "admin", "timeout", "system"

    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now(timezone.utc) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "admin_user_id": self.admin_user_id,
            "admin_email": self.admin_email,
            "target_user_id": self.target_user_id,
            "target_email": self.target_email,
            "reason": self.reason,
            "started_at": (
                self.started_at.isoformat()
                if isinstance(self.started_at, datetime)
                else self.started_at
            ),
            "expires_at": (
                self.expires_at.isoformat()
                if isinstance(self.expires_at, datetime)
                else self.expires_at
            ),
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "actions_performed": self.actions_performed,
            "ended_at": (
                self.ended_at.isoformat() if isinstance(self.ended_at, datetime) else self.ended_at
            ),
            "ended_by": self.ended_by,
        }


@dataclass
class AuditRecord:
    """Persistent audit log record."""

    audit_id: str
    timestamp: datetime
    event_type: str  # start, action, end, timeout, denied
    session_id: str | None
    admin_user_id: str
    target_user_id: str | None
    reason: str | None
    action_details_json: str | None
    ip_address: str
    user_agent: str
    success: bool
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "audit_id": self.audit_id,
            "timestamp": (
                self.timestamp.isoformat()
                if isinstance(self.timestamp, datetime)
                else self.timestamp
            ),
            "event_type": self.event_type,
            "session_id": self.session_id,
            "admin_user_id": self.admin_user_id,
            "target_user_id": self.target_user_id,
            "reason": self.reason,
            "action_details": (
                json.loads(self.action_details_json) if self.action_details_json else None
            ),
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "success": self.success,
            "error_message": self.error_message,
        }


class ImpersonationStore:
    """
    Persistent storage for impersonation sessions and audit logs.

    Stores:
    - Active and historical impersonation sessions
    - Full audit trail of all impersonation events

    Supports SQLite (default) and PostgreSQL backends.
    """

    def __init__(
        self,
        db_path: str = "aragora_impersonation.db",
        backend: str | None = None,
        database_url: str | None = None,
    ):
        """
        Initialize impersonation store.

        Args:
            db_path: Path to SQLite database (used when backend="sqlite")
            backend: Database backend ("sqlite" or "postgresql")
            database_url: PostgreSQL connection URL
        """
        # Determine backend
        env_url = os.environ.get("DATABASE_URL") or os.environ.get("ARAGORA_DATABASE_URL")
        actual_url = database_url or env_url

        if backend is None:
            backend = "postgresql" if actual_url else "sqlite"

        self.backend_type = backend

        # Create backend
        if backend == "postgresql":
            if not actual_url:
                raise ValueError("PostgreSQL backend requires DATABASE_URL")
            if not POSTGRESQL_AVAILABLE:
                raise ImportError("psycopg2 required for PostgreSQL")
            self._backend: DatabaseBackend = PostgreSQLBackend(actual_url)
            logger.info("ImpersonationStore using PostgreSQL backend")
        else:
            resolved_path = resolve_db_path(db_path)
            self.db_path = Path(resolved_path)
            self._backend = SQLiteBackend(resolved_path)
            logger.info("ImpersonationStore using SQLite backend: %s", resolved_path)

        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        # Sessions table
        self._backend.execute_write("""
            CREATE TABLE IF NOT EXISTS impersonation_sessions (
                session_id TEXT PRIMARY KEY,
                admin_user_id TEXT NOT NULL,
                admin_email TEXT NOT NULL,
                target_user_id TEXT NOT NULL,
                target_email TEXT NOT NULL,
                reason TEXT NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                actions_performed INTEGER DEFAULT 0,
                ended_at TIMESTAMP,
                ended_by TEXT
            )
        """)

        # Audit log table
        self._backend.execute_write("""
            CREATE TABLE IF NOT EXISTS impersonation_audit (
                audit_id TEXT PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT NOT NULL,
                session_id TEXT,
                admin_user_id TEXT NOT NULL,
                target_user_id TEXT,
                reason TEXT,
                action_details_json TEXT,
                ip_address TEXT,
                user_agent TEXT,
                success INTEGER NOT NULL,
                error_message TEXT
            )
        """)

        # Create indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_sessions_admin ON impersonation_sessions(admin_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_target ON impersonation_sessions(target_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON impersonation_sessions(expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_ended ON impersonation_sessions(ended_at)",
            "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON impersonation_audit(timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_audit_admin ON impersonation_audit(admin_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_target ON impersonation_audit(target_user_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_session ON impersonation_audit(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_event ON impersonation_audit(event_type)",
        ]
        for idx in indexes:
            try:
                self._backend.execute_write(idx)
            except (OSError, RuntimeError, ValueError) as e:
                logger.debug("Index creation skipped: %s", e)

    # =========================================================================
    # Session Management
    # =========================================================================

    def save_session(
        self,
        session_id: str,
        admin_user_id: str,
        admin_email: str,
        target_user_id: str,
        target_email: str,
        reason: str,
        started_at: datetime,
        expires_at: datetime,
        ip_address: str,
        user_agent: str,
        actions_performed: int = 0,
    ) -> str:
        """
        Save a new impersonation session.

        Args:
            session_id: Unique session ID
            admin_user_id: Admin who initiated impersonation
            admin_email: Admin email
            target_user_id: User being impersonated
            target_email: Target user email
            reason: Justification for impersonation
            started_at: Session start time
            expires_at: Session expiration time
            ip_address: Request IP
            user_agent: Request user agent
            actions_performed: Number of actions in session

        Returns:
            The session_id
        """
        if self.backend_type == "postgresql":
            sql = """
                INSERT INTO impersonation_sessions (
                    session_id, admin_user_id, admin_email, target_user_id,
                    target_email, reason, started_at, expires_at, ip_address,
                    user_agent, actions_performed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (session_id) DO UPDATE SET
                    actions_performed = EXCLUDED.actions_performed
            """
        else:
            sql = """
                INSERT OR REPLACE INTO impersonation_sessions (
                    session_id, admin_user_id, admin_email, target_user_id,
                    target_email, reason, started_at, expires_at, ip_address,
                    user_agent, actions_performed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

        self._backend.execute_write(
            sql,
            (
                session_id,
                admin_user_id,
                admin_email,
                target_user_id,
                target_email,
                reason,
                started_at.isoformat(),
                expires_at.isoformat(),
                ip_address,
                user_agent,
                actions_performed,
            ),
        )

        logger.debug("Saved impersonation session: %s", session_id)
        return session_id

    def update_session_actions(self, session_id: str, actions_performed: int) -> bool:
        """Update the action count for a session."""
        self._backend.execute_write(
            "UPDATE impersonation_sessions SET actions_performed = ? WHERE session_id = ?",
            (actions_performed, session_id),
        )
        return True

    def end_session(
        self,
        session_id: str,
        ended_by: str,
        actions_performed: int,
    ) -> bool:
        """
        Mark a session as ended.

        Args:
            session_id: Session to end
            ended_by: How session ended ("admin", "timeout", "system")
            actions_performed: Final action count

        Returns:
            True if updated
        """
        now = datetime.now(timezone.utc).isoformat()

        self._backend.execute_write(
            """
            UPDATE impersonation_sessions
            SET ended_at = ?, ended_by = ?, actions_performed = ?
            WHERE session_id = ?
            """,
            (now, ended_by, actions_performed, session_id),
        )

        logger.debug("Ended impersonation session: %s by %s", session_id, ended_by)
        return True

    def get_session(self, session_id: str) -> SessionRecord | None:
        """Get a session by ID."""
        row = self._backend.fetch_one(
            """
            SELECT session_id, admin_user_id, admin_email, target_user_id,
                   target_email, reason, started_at, expires_at, ip_address,
                   user_agent, actions_performed, ended_at, ended_by
            FROM impersonation_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        )

        if not row:
            return None

        return self._row_to_session(row)

    def get_active_sessions(self, admin_user_id: str | None = None) -> list[SessionRecord]:
        """
        Get all active (non-ended, non-expired) sessions.

        Args:
            admin_user_id: Optional filter by admin

        Returns:
            List of active SessionRecord
        """
        now = datetime.now(timezone.utc).isoformat()

        query = """
            SELECT session_id, admin_user_id, admin_email, target_user_id,
                   target_email, reason, started_at, expires_at, ip_address,
                   user_agent, actions_performed, ended_at, ended_by
            FROM impersonation_sessions
            WHERE ended_at IS NULL AND expires_at > ?
        """
        params: list = [now]

        if admin_user_id:
            query += " AND admin_user_id = ?"
            params.append(admin_user_id)

        query += " ORDER BY started_at DESC"

        rows = self._backend.fetch_all(query, tuple(params))
        return [self._row_to_session(row) for row in rows]

    def get_sessions_for_admin(
        self,
        admin_user_id: str,
        include_ended: bool = False,
        limit: int = 100,
    ) -> list[SessionRecord]:
        """Get all sessions for an admin."""
        query = """
            SELECT session_id, admin_user_id, admin_email, target_user_id,
                   target_email, reason, started_at, expires_at, ip_address,
                   user_agent, actions_performed, ended_at, ended_by
            FROM impersonation_sessions
            WHERE admin_user_id = ?
        """
        params: list = [admin_user_id]

        if not include_ended:
            now = datetime.now(timezone.utc).isoformat()
            query += " AND ended_at IS NULL AND expires_at > ?"
            params.append(now)

        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        rows = self._backend.fetch_all(query, tuple(params))
        return [self._row_to_session(row) for row in rows]

    def _row_to_session(self, row: tuple) -> SessionRecord:
        """Convert database row to SessionRecord."""
        return SessionRecord(
            session_id=row[0],
            admin_user_id=row[1],
            admin_email=row[2],
            target_user_id=row[3],
            target_email=row[4],
            reason=row[5],
            started_at=cast(datetime, parse_timestamp(row[6], default=utc_now())),
            expires_at=cast(datetime, parse_timestamp(row[7], default=utc_now())),
            ip_address=row[8] or "",
            user_agent=row[9] or "",
            actions_performed=row[10] or 0,
            ended_at=parse_timestamp(row[11]),
            ended_by=row[12],
        )

    # =========================================================================
    # Audit Log
    # =========================================================================

    def save_audit_entry(
        self,
        audit_id: str,
        timestamp: datetime,
        event_type: str,
        admin_user_id: str,
        ip_address: str,
        user_agent: str,
        success: bool,
        session_id: str | None = None,
        target_user_id: str | None = None,
        reason: str | None = None,
        action_details: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> str:
        """
        Save an audit log entry.

        Args:
            audit_id: Unique audit entry ID
            timestamp: Event timestamp
            event_type: Type of event (start, action, end, timeout, denied)
            admin_user_id: Admin involved
            ip_address: Request IP
            user_agent: Request user agent
            success: Whether action succeeded
            session_id: Related session ID
            target_user_id: Target user
            reason: Reason/justification
            action_details: Details dict
            error_message: Error if failed

        Returns:
            The audit_id
        """
        if self.backend_type == "postgresql":
            sql = """
                INSERT INTO impersonation_audit (
                    audit_id, timestamp, event_type, session_id, admin_user_id,
                    target_user_id, reason, action_details_json, ip_address,
                    user_agent, success, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (audit_id) DO NOTHING
            """
        else:
            sql = """
                INSERT OR IGNORE INTO impersonation_audit (
                    audit_id, timestamp, event_type, session_id, admin_user_id,
                    target_user_id, reason, action_details_json, ip_address,
                    user_agent, success, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

        self._backend.execute_write(
            sql,
            (
                audit_id,
                timestamp.isoformat(),
                event_type,
                session_id,
                admin_user_id,
                target_user_id,
                reason,
                json.dumps(action_details) if action_details else None,
                ip_address,
                user_agent,
                1 if success else 0,
                error_message,
            ),
        )

        logger.debug("Saved audit entry: %s (%s)", audit_id, event_type)
        return audit_id

    def get_audit_log(
        self,
        admin_user_id: str | None = None,
        target_user_id: str | None = None,
        session_id: str | None = None,
        event_type: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditRecord]:
        """
        Query the audit log.

        Args:
            admin_user_id: Filter by admin
            target_user_id: Filter by target
            session_id: Filter by session
            event_type: Filter by event type
            since: Filter by timestamp
            limit: Maximum entries

        Returns:
            List of AuditRecord (newest first)
        """
        query = """
            SELECT audit_id, timestamp, event_type, session_id, admin_user_id,
                   target_user_id, reason, action_details_json, ip_address,
                   user_agent, success, error_message
            FROM impersonation_audit
            WHERE 1=1
        """
        params: list = []

        if admin_user_id:
            query += " AND admin_user_id = ?"
            params.append(admin_user_id)

        if target_user_id:
            query += " AND target_user_id = ?"
            params.append(target_user_id)

        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        if since:
            query += " AND timestamp >= ?"
            params.append(since.isoformat())

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self._backend.fetch_all(query, tuple(params))
        return [self._row_to_audit(row) for row in rows]

    def _row_to_audit(self, row: tuple) -> AuditRecord:
        """Convert database row to AuditRecord."""
        return AuditRecord(
            audit_id=row[0],
            timestamp=cast(datetime, parse_timestamp(row[1], default=utc_now())),
            event_type=row[2],
            session_id=row[3],
            admin_user_id=row[4],
            target_user_id=row[5],
            reason=row[6],
            action_details_json=row[7],
            ip_address=row[8] or "",
            user_agent=row[9] or "",
            success=bool(row[10]),
            error_message=row[11],
        )

    # =========================================================================
    # Cleanup
    # =========================================================================

    def cleanup_expired_sessions(self) -> int:
        """
        Mark expired sessions as ended.

        Returns:
            Number of sessions cleaned up
        """
        now = datetime.now(timezone.utc).isoformat()

        # Get count first
        result = self._backend.fetch_one(
            """
            SELECT COUNT(*) FROM impersonation_sessions
            WHERE ended_at IS NULL AND expires_at < ?
            """,
            (now,),
        )
        count = result[0] if result else 0

        if count > 0:
            self._backend.execute_write(
                """
                UPDATE impersonation_sessions
                SET ended_at = ?, ended_by = 'timeout'
                WHERE ended_at IS NULL AND expires_at < ?
                """,
                (now, now),
            )
            logger.info("Cleaned up %s expired impersonation sessions", count)

        return count

    def cleanup_old_records(
        self,
        sessions_days: int = 90,
        audit_days: int = 365,
    ) -> dict[str, int]:
        """
        Clean up old records.

        Args:
            sessions_days: Days to keep ended sessions
            audit_days: Days to keep audit entries

        Returns:
            Counts of deleted records
        """
        counts: dict[str, int] = {}

        # Clean old sessions (only ended ones)
        result = self._backend.fetch_one(
            """
            SELECT COUNT(*) FROM impersonation_sessions
            WHERE ended_at IS NOT NULL
            AND datetime(ended_at) < datetime('now', ? || ' days')
            """,
            (f"-{sessions_days}",),
        )
        counts["sessions"] = result[0] if result else 0

        if counts["sessions"] > 0:
            self._backend.execute_write(
                """
                DELETE FROM impersonation_sessions
                WHERE ended_at IS NOT NULL
                AND datetime(ended_at) < datetime('now', ? || ' days')
                """,
                (f"-{sessions_days}",),
            )

        # Clean old audit entries
        result = self._backend.fetch_one(
            """
            SELECT COUNT(*) FROM impersonation_audit
            WHERE datetime(timestamp) < datetime('now', ? || ' days')
            """,
            (f"-{audit_days}",),
        )
        counts["audit"] = result[0] if result else 0

        if counts["audit"] > 0:
            self._backend.execute_write(
                """
                DELETE FROM impersonation_audit
                WHERE datetime(timestamp) < datetime('now', ? || ' days')
                """,
                (f"-{audit_days}",),
            )

        logger.info("Cleaned up impersonation records: %s", counts)
        return counts

    def close(self) -> None:
        """Close database connection."""
        self._backend.close()


# Module-level singleton
_default_store: ImpersonationStore | None = None


def get_impersonation_store(
    db_path: str = "aragora_impersonation.db",
    backend: str | None = None,
    database_url: str | None = None,
) -> ImpersonationStore:
    """
    Get or create the default ImpersonationStore instance.

    Backend selection (in preference order):
    1. Supabase PostgreSQL (if SUPABASE_URL + SUPABASE_DB_PASSWORD configured)
    2. Self-hosted PostgreSQL (if DATABASE_URL or ARAGORA_POSTGRES_DSN configured)
    3. SQLite (fallback, with production warning)

    Override via:
    - ARAGORA_IMPERSONATION_STORE_BACKEND: "sqlite", "postgres", or "supabase"
    - ARAGORA_DB_BACKEND: Global override

    Returns:
        Configured ImpersonationStore instance
    """
    global _default_store

    if _default_store is None:
        # Use connection factory to determine backend and DSN
        from aragora.storage.connection_factory import (
            resolve_database_config,
            StorageBackendType,
        )

        # Check for explicit backend override, else use preference order
        store_backend = os.environ.get("ARAGORA_IMPERSONATION_STORE_BACKEND")
        if not store_backend and backend is None:
            config = resolve_database_config("impersonation", allow_sqlite=True)
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
                config = resolve_database_config("impersonation", allow_sqlite=True)
                database_url = database_url or config.dsn
                backend = "postgresql"
            else:
                backend = store_backend

        _default_store = ImpersonationStore(
            db_path=db_path,
            backend=backend,
            database_url=database_url,
        )

        # Enforce distributed storage in production for security-sensitive data
        if _default_store.backend_type == "sqlite":
            from aragora.storage.production_guards import (
                require_distributed_store,
                StorageMode,
            )

            require_distributed_store(
                "impersonation_store",
                StorageMode.SQLITE,
                "Impersonation sessions must use distributed storage in production. "
                "Configure SUPABASE_URL or DATABASE_URL for PostgreSQL.",
            )

    return _default_store


def reset_impersonation_store() -> None:
    """Reset the default store instance (for testing)."""
    global _default_store
    if _default_store is not None:
        _default_store.close()
        _default_store = None


__all__ = [
    "ImpersonationStore",
    "SessionRecord",
    "AuditRecord",
    "get_impersonation_store",
    "reset_impersonation_store",
]
