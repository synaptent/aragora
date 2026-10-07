"""
Aragora Audit Log System.

Enterprise-grade audit logging for compliance requirements:
- SOC 2 Type II
- HIPAA
- GDPR
- SOX

Features:
- Immutable audit trail with cryptographic integrity
- Retention policies (configurable)
- Export in compliance formats (JSON, CSV, SOC2)
- Full-text search
- Tamper detection via hash chains

Usage:
    from aragora.observability.audit_log import AuditLog, AuditEvent, AuditCategory

    audit = AuditLog()

    # Log an event
    audit.log(AuditEvent(
        category=AuditCategory.AUTH,
        action="login",
        actor_id="user_123",
        resource_type="session",
        resource_id="sess_abc",
        outcome="success",
    ))

    # Export for compliance
    audit.export_soc2("soc2_audit_2026_Q1.json", start_date, end_date)
"""

from __future__ import annotations

import contextvars
import csv
import hashlib
import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from aragora.storage.production_guards import require_distributed_store, StorageMode

logger = logging.getLogger(__name__)

# Check for PostgreSQL availability
try:
    import psycopg2  # noqa: F401

    POSTGRESQL_AVAILABLE = True
except ImportError:
    POSTGRESQL_AVAILABLE = False


class AuditCategory(Enum):
    """Categories of audit events."""

    AUTH = "auth"  # Authentication events
    ACCESS = "access"  # Resource access
    DATA = "data"  # Data modifications
    ADMIN = "admin"  # Administrative actions
    BILLING = "billing"  # Billing/subscription events
    DEBATE = "debate"  # Debate operations
    API = "api"  # API access
    SECURITY = "security"  # Security events
    SYSTEM = "system"  # System events


class AuditOutcome(Enum):
    """Outcome of audited action."""

    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    ERROR = "error"


AUDIT_COLUMNS = [
    "id",
    "timestamp",
    "category",
    "action",
    "actor_id",
    "resource_type",
    "resource_id",
    "outcome",
    "ip_address",
    "user_agent",
    "correlation_id",
    "org_id",
    "workspace_id",
    "details",
    "reason",
    "previous_hash",
    "event_hash",
]

SQLITE_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        category TEXT NOT NULL,
        action TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        resource_type TEXT,
        resource_id TEXT,
        outcome TEXT NOT NULL,
        ip_address TEXT,
        user_agent TEXT,
        correlation_id TEXT,
        org_id TEXT,
        workspace_id TEXT,
        details TEXT DEFAULT '{}',
        reason TEXT,
        previous_hash TEXT,
        event_hash TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_events(category)",
    "CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events(actor_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_org ON audit_events(org_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_events(resource_type, resource_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_outcome ON audit_events(outcome)",
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS audit_fts USING fts5(
        id, action, actor_id, resource_type, resource_id, details, reason,
        content='audit_events',
        content_rowid='rowid'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_ai AFTER INSERT ON audit_events BEGIN
        INSERT INTO audit_fts(rowid, id, action, actor_id, resource_type,
            resource_id, details, reason)
        VALUES (new.rowid, new.id, new.action, new.actor_id, new.resource_type,
            new.resource_id, new.details, new.reason);
    END
    """,
]

POSTGRES_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        timestamp TIMESTAMPTZ NOT NULL,
        category TEXT NOT NULL,
        action TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        resource_type TEXT,
        resource_id TEXT,
        outcome TEXT NOT NULL,
        ip_address TEXT,
        user_agent TEXT,
        correlation_id TEXT,
        org_id TEXT,
        workspace_id TEXT,
        details TEXT DEFAULT '{}',
        reason TEXT,
        previous_hash TEXT,
        event_hash TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_events(category)",
    "CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events(actor_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_org ON audit_events(org_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_events(resource_type, resource_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_outcome ON audit_events(outcome)",
]


@dataclass
class AuditEvent:
    """An audit log event."""

    # Required fields
    category: AuditCategory
    action: str
    actor_id: str

    # Resource being acted upon
    resource_type: str = ""
    resource_id: str = ""

    # Outcome
    outcome: AuditOutcome = AuditOutcome.SUCCESS

    # Context
    ip_address: str = ""
    user_agent: str = ""
    correlation_id: str = ""
    org_id: str = ""
    workspace_id: str = ""

    # Details
    details: dict[str, Any] = field(default_factory=dict)
    reason: str = ""  # For denials/failures

    # Metadata
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Integrity
    previous_hash: str = ""
    event_hash: str = ""

    def compute_hash(self) -> str:
        """Compute hash of event for integrity chain."""
        data = (
            f"{self.id}|{self.timestamp.isoformat()}|{self.category.value}|"
            f"{self.action}|{self.actor_id}|{self.resource_type}|{self.resource_id}|"
            f"{self.outcome.value}|{self.previous_hash}"
        )
        return hashlib.sha256(data.encode()).hexdigest()[:32]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "category": self.category.value,
            "action": self.action,
            "actor_id": self.actor_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "outcome": self.outcome.value,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "correlation_id": self.correlation_id,
            "org_id": self.org_id,
            "workspace_id": self.workspace_id,
            "details": self.details,
            "reason": self.reason,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditEvent:
        """Create from dictionary."""
        return cls(
            id=data.get("id", str(uuid4())),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if isinstance(data.get("timestamp"), str)
                else data.get("timestamp", datetime.now(timezone.utc))
            ),
            category=AuditCategory(data.get("category", "system")),
            action=data.get("action", ""),
            actor_id=data.get("actor_id", ""),
            resource_type=data.get("resource_type", ""),
            resource_id=data.get("resource_id", ""),
            outcome=AuditOutcome(data.get("outcome", "success")),
            ip_address=data.get("ip_address", ""),
            user_agent=data.get("user_agent", ""),
            correlation_id=data.get("correlation_id", ""),
            org_id=data.get("org_id", ""),
            workspace_id=data.get("workspace_id", ""),
            details=data.get("details", {}),
            reason=data.get("reason", ""),
            previous_hash=data.get("previous_hash", ""),
            event_hash=data.get("event_hash", ""),
        )


@dataclass
class AuditQuery:
    """Query parameters for audit log search."""

    start_date: datetime | None = None
    end_date: datetime | None = None
    category: AuditCategory | None = None
    action: str | None = None
    actor_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    outcome: AuditOutcome | None = None
    org_id: str | None = None
    ip_address: str | None = None
    search_text: str | None = None
    limit: int = 1000
    offset: int = 0


class SQLiteBackend:
    """SQLite backend for audit log storage.

    Uses context variables for connections to ensure context safety.
    Each async context gets its own connection to the database.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            f"sqlite_audit_conn_{id(self)}", default=None
        )
        self._connections: list[sqlite3.Connection] = []

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create context-local database connection."""
        conn = self._conn_var.get()
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
            self._conn_var.set(conn)
            self._connections.append(conn)
        return conn

    def execute_write(self, sql: str, params: tuple = ()) -> None:
        """Execute a write operation."""
        conn = self._get_connection()
        conn.execute(sql, params)
        conn.commit()

    def fetch_one(self, sql: str, params: tuple = ()) -> Any | None:
        """Execute query and fetch single row."""
        conn = self._get_connection()
        cursor = conn.execute(sql, params)
        return cursor.fetchone()

    def fetch_all(self, sql: str, params: tuple = ()) -> list:
        """Execute query and fetch all rows."""
        conn = self._get_connection()
        cursor = conn.execute(sql, params)
        return cursor.fetchall()

    def close(self) -> None:
        """Close the current context's database connection."""
        conn = self._conn_var.get()
        if conn is not None:
            conn.close()
            self._conn_var.set(None)
            if conn in self._connections:
                self._connections.remove(conn)

    def close_all(self) -> None:
        """Close all tracked connections."""
        for conn in self._connections:
            try:
                conn.close()
            except (OSError, RuntimeError) as exc:
                logger.debug("Failed to close connection: %s", exc)
        self._connections.clear()
        self._conn_var.set(None)


class PostgreSQLBackend:
    """PostgreSQL backend for audit log storage (enterprise deployments)."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._conn_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
            f"postgres_audit_conn_{id(self)}", default=None
        )
        self._connections: list[Any] = []

    def _get_connection(self) -> Any:
        """Get or create context-local database connection."""
        conn = self._conn_var.get()
        if conn is None:
            conn = psycopg2.connect(self.database_url)
            self._conn_var.set(conn)
            self._connections.append(conn)
        return conn

    def execute_write(self, sql: str, params: tuple = ()) -> None:
        """Execute a write operation."""
        # Convert SQLite ? placeholders to PostgreSQL %s
        sql = sql.replace("?", "%s")
        conn = self._get_connection()
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
        conn.commit()

    def fetch_one(self, sql: str, params: tuple = ()) -> Any | None:
        """Execute query and fetch single row."""
        sql = sql.replace("?", "%s")
        conn = self._get_connection()
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def fetch_all(self, sql: str, params: tuple = ()) -> list:
        """Execute query and fetch all rows."""
        sql = sql.replace("?", "%s")
        conn = self._get_connection()
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def close(self) -> None:
        """Close the current context's database connection."""
        conn = self._conn_var.get()
        if conn is not None:
            conn.close()
            self._conn_var.set(None)
            if conn in self._connections:
                self._connections.remove(conn)

    def close_all(self) -> None:
        """Close all tracked connections."""
        for conn in self._connections:
            try:
                conn.close()
            except (OSError, RuntimeError) as e:
                logger.warning("Failed to close audit log connection: %s", e)
        self._connections.clear()
        self._conn_var.set(None)


class AuditLog:
    """
    Enterprise audit log with compliance export support.

    Provides:
    - Immutable audit trail with hash chain integrity
    - Configurable retention policies
    - Export in compliance formats
    - Full-text search
    - Tamper detection
    """

    def __init__(
        self,
        db_path: Path | None = None,
        retention_days: int = 365 * 7,  # 7 years default (SOX requirement)
    ):
        """
        Initialize audit log.

        Args:
            db_path: Path to SQLite database (default: .nomic/audit.db)
            retention_days: Days to retain logs (default: 7 years for SOX)
        """
        if db_path is None:
            from aragora.persistence.db_config import get_nomic_dir

            db_path = get_nomic_dir() / "audit.db"
        self.db_path = db_path
        self.retention_days = retention_days
        self._last_hash = ""
        self._backend_type = "sqlite"
        self._backend: Any = None
        self._persistence_backend: Any = None

        backend_type = os.environ.get("ARAGORA_AUDIT_STORE_BACKEND")
        if not backend_type:
            backend_type = os.environ.get("ARAGORA_DB_BACKEND", "sqlite")
        backend_type = backend_type.lower()

        database_url = (
            os.environ.get("ARAGORA_POSTGRES_DSN")
            or os.environ.get("DATABASE_URL")
            or os.environ.get("ARAGORA_DATABASE_URL")
        )

        if backend_type == "file":
            try:
                from aragora.observability.audit_persistence import get_backend as get_audit_backend

                self._persistence_backend = get_audit_backend("file")
                self._backend_type = "file"
                try:
                    require_distributed_store(
                        "audit_log",
                        StorageMode.FILE,
                        "Audit log using file backend - configure PostgreSQL for multi-instance deployments.",
                    )
                except (ValueError, RuntimeError, OSError) as e:
                    logger.debug("Failed to require distributed store for audit log: %s", e)
                storage_path = getattr(self._persistence_backend, "storage_path", None)
                if storage_path:
                    logger.info("Audit log using file backend: %s", storage_path)
                else:
                    logger.info("Audit log using file backend")
            except (ImportError, OSError, RuntimeError) as e:
                logger.warning("File audit backend unavailable, falling back to SQLite: %s", e)
                self._persistence_backend = None

        if self._persistence_backend is None and backend_type in ("postgres", "postgresql"):
            if not POSTGRESQL_AVAILABLE:
                logger.warning("PostgreSQL audit backend requested but psycopg2 is not installed")
            elif not database_url:
                logger.warning("PostgreSQL audit backend selected but DATABASE_URL is missing")
            else:
                try:
                    self._backend = PostgreSQLBackend(database_url)
                    self._backend_type = "postgresql"
                    logger.info("Audit log using PostgreSQL backend")
                except (OSError, RuntimeError) as e:
                    logger.warning(
                        "PostgreSQL audit backend unavailable, falling back to SQLite: %s", e
                    )
                    try:
                        require_distributed_store(
                            "audit_log",
                            StorageMode.SQLITE,
                            f"PostgreSQL backend unavailable: {e}",
                        )
                    except (ValueError, RuntimeError, OSError) as e:
                        logger.debug("Failed to require distributed store for audit log: %s", e)

        if self._backend is None and self._persistence_backend is None:
            require_distributed_store(
                "audit_log",
                StorageMode.SQLITE,
                "Audit log using SQLite - configure PostgreSQL for multi-instance deployments.",
            )
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._backend = SQLiteBackend(self.db_path)
            logger.info("Audit log using SQLite backend: %s", self.db_path)

        self._ensure_schema()
        self._load_last_hash()

    def _ensure_schema(self) -> None:
        """Create database schema."""
        if self._backend_type == "file" and self._persistence_backend is not None:
            self._persistence_backend.initialize()
            return
        statements = (
            POSTGRES_SCHEMA_STATEMENTS
            if self._backend_type == "postgresql"
            else SQLITE_SCHEMA_STATEMENTS
        )
        for statement in statements:
            self._backend.execute_write(statement)

    def _load_last_hash(self) -> None:
        """Load the last event hash for chain continuity."""
        if self._backend_type == "file" and self._persistence_backend is not None:
            self._last_hash = self._persistence_backend.get_last_hash()
            return
        row = self._backend.fetch_one(
            "SELECT event_hash FROM audit_events ORDER BY timestamp DESC LIMIT 1"
        )
        if row:
            self._last_hash = row[0]

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        """Convert a database row to a dict using known column order."""
        if hasattr(row, "keys"):
            return {key: row[key] for key in row.keys()}
        return dict(zip(AUDIT_COLUMNS, row))

    def _row_to_event(self, row: Any) -> AuditEvent:
        """Convert a database row to an AuditEvent."""
        event_data = self._row_to_dict(row)
        details = event_data.get("details", "{}")
        if isinstance(details, str):
            try:
                event_data["details"] = json.loads(details)
            except json.JSONDecodeError:
                event_data["details"] = {}
        elif isinstance(details, dict):
            event_data["details"] = details
        else:
            event_data["details"] = {}
        return AuditEvent.from_dict(event_data)

    def log(self, event: AuditEvent) -> str:
        """
        Log an audit event.

        Args:
            event: The audit event to log

        Returns:
            Event ID
        """
        # Set hash chain
        event.previous_hash = self._last_hash
        event.event_hash = event.compute_hash()

        if self._backend_type == "file" and self._persistence_backend is not None:
            event_id = self._persistence_backend.store(event)
            self._last_hash = event.event_hash
            return event_id

        self._backend.execute_write(
            """
            INSERT INTO audit_events
            (id, timestamp, category, action, actor_id, resource_type, resource_id,
             outcome, ip_address, user_agent, correlation_id, org_id, workspace_id,
             details, reason, previous_hash, event_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.timestamp.isoformat(),
                event.category.value,
                event.action,
                event.actor_id,
                event.resource_type,
                event.resource_id,
                event.outcome.value,
                event.ip_address,
                event.user_agent,
                event.correlation_id,
                event.org_id,
                event.workspace_id,
                json.dumps(event.details),
                event.reason,
                event.previous_hash,
                event.event_hash,
            ),
        )

        self._last_hash = event.event_hash

        logger.debug(
            "audit_logged category=%s action=%s actor=%s outcome=%s",
            event.category.value,
            event.action,
            event.actor_id,
            event.outcome.value,
        )

        return event.id

    def query(self, query: AuditQuery) -> list[AuditEvent]:
        """
        Query audit events.

        Args:
            query: Query parameters

        Returns:
            List of matching events
        """
        if self._backend_type == "file" and self._persistence_backend is not None:
            return self._persistence_backend.query(query)

        conditions = []
        params: list[Any] = []

        if query.start_date:
            conditions.append("timestamp >= ?")
            params.append(query.start_date.isoformat())

        if query.end_date:
            conditions.append("timestamp <= ?")
            params.append(query.end_date.isoformat())

        if query.category:
            conditions.append("category = ?")
            params.append(query.category.value)

        if query.action:
            conditions.append("action = ?")
            params.append(query.action)

        if query.actor_id:
            conditions.append("actor_id = ?")
            params.append(query.actor_id)

        if query.resource_type:
            conditions.append("resource_type = ?")
            params.append(query.resource_type)

        if query.resource_id:
            conditions.append("resource_id = ?")
            params.append(query.resource_id)

        if query.outcome:
            conditions.append("outcome = ?")
            params.append(query.outcome.value)

        if query.org_id:
            conditions.append("org_id = ?")
            params.append(query.org_id)

        if query.ip_address:
            conditions.append("ip_address = ?")
            params.append(query.ip_address)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Handle full-text search separately (SQLite only)
        if query.search_text and self._backend_type == "sqlite":
            sql = f"""
                SELECT e.* FROM audit_events e
                JOIN audit_fts f ON e.id = f.id
                WHERE f.audit_fts MATCH ? AND {where_clause}
                ORDER BY e.timestamp DESC
                LIMIT ? OFFSET ?
            """  # noqa: S608 -- dynamic clause from internal state
            query_params = [query.search_text] + params + [query.limit, query.offset]
        else:
            if query.search_text:
                like = f"%{query.search_text}%"
                conditions.append(
                    "("
                    "action ILIKE ? OR actor_id ILIKE ? OR resource_type ILIKE ? "
                    "OR resource_id ILIKE ? OR details ILIKE ? OR reason ILIKE ?"
                    ")"
                )
                params.extend([like, like, like, like, like, like])
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            sql = f"""
                SELECT * FROM audit_events
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """  # noqa: S608 -- dynamic clause from internal state
            query_params = params + [query.limit, query.offset]

        rows = self._backend.fetch_all(sql, tuple(query_params))
        return [self._row_to_event(row) for row in rows]

    def verify_integrity(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> tuple[bool, list[str]]:
        """
        Verify audit log integrity via hash chain.

        Args:
            start_date: Start of verification range
            end_date: End of verification range

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        if self._backend_type == "file" and self._persistence_backend is not None:
            return self._persistence_backend.verify_integrity(start_date, end_date)

        errors = []

        conditions = []
        params: list[Any] = []

        if start_date:
            conditions.append("timestamp >= ?")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("timestamp <= ?")
            params.append(end_date.isoformat())

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        rows = self._backend.fetch_all(
            f"SELECT * FROM audit_events WHERE {where_clause} ORDER BY timestamp",  # noqa: S608 -- dynamic clause from internal state
            tuple(params),
        )

        prev_hash = ""
        for row in rows:
            event = self._row_to_event(row)

            # Verify previous hash
            if event.previous_hash != prev_hash:
                errors.append(
                    f"Hash chain broken at event {event.id}: "
                    f"expected previous_hash={prev_hash}, got {event.previous_hash}"
                )

            # Verify event hash
            computed = event.compute_hash()
            if event.event_hash != computed:
                errors.append(
                    f"Event {event.id} hash mismatch: "
                    f"stored={event.event_hash}, computed={computed}"
                )

            prev_hash = event.event_hash

        return len(errors) == 0, errors

    def export_json(
        self,
        output_path: Path,
        start_date: datetime,
        end_date: datetime,
        org_id: str | None = None,
    ) -> int:
        """
        Export audit log to JSON.

        Args:
            output_path: Output file path
            start_date: Export start date
            end_date: Export end date
            org_id: Filter by organization

        Returns:
            Number of events exported
        """
        query = AuditQuery(
            start_date=start_date,
            end_date=end_date,
            org_id=org_id,
            limit=100000,
        )
        events = self.query(query)

        export_data = {
            "export_timestamp": datetime.now(timezone.utc).isoformat(),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "org_id": org_id,
            "event_count": len(events),
            "events": [e.to_dict() for e in events],
        }

        with open(output_path, "w") as f:
            json.dump(export_data, f, indent=2)

        return len(events)

    def export_csv(
        self,
        output_path: Path,
        start_date: datetime,
        end_date: datetime,
        org_id: str | None = None,
    ) -> int:
        """
        Export audit log to CSV.

        Args:
            output_path: Output file path
            start_date: Export start date
            end_date: Export end date
            org_id: Filter by organization

        Returns:
            Number of events exported
        """
        query = AuditQuery(
            start_date=start_date,
            end_date=end_date,
            org_id=org_id,
            limit=100000,
        )
        events = self.query(query)

        fieldnames = [
            "id",
            "timestamp",
            "category",
            "action",
            "actor_id",
            "resource_type",
            "resource_id",
            "outcome",
            "ip_address",
            "org_id",
            "reason",
            "event_hash",
        ]

        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for event in events:
                row = event.to_dict()
                writer.writerow({k: row.get(k, "") for k in fieldnames})

        return len(events)

    def export_soc2(
        self,
        output_path: Path,
        start_date: datetime,
        end_date: datetime,
        org_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Export audit log in SOC 2 Type II format.

        Generates a comprehensive audit report suitable for SOC 2 auditors.

        Args:
            output_path: Output file path
            start_date: Audit period start
            end_date: Audit period end
            org_id: Organization to audit

        Returns:
            Summary statistics
        """
        query = AuditQuery(
            start_date=start_date,
            end_date=end_date,
            org_id=org_id,
            limit=100000,
        )
        events = self.query(query)

        # Verify integrity
        is_valid, integrity_errors = self.verify_integrity(start_date, end_date)

        # Compute statistics with proper types
        total_events = len(events)
        by_category: dict[str, int] = {}
        by_outcome: dict[str, int] = {}
        by_action: dict[str, int] = {}
        unique_actors: set[str] = set()
        auth_failures = 0
        access_denials = 0
        security_events = 0

        for event in events:
            # Category counts
            cat = event.category.value
            by_category[cat] = by_category.get(cat, 0) + 1

            # Outcome counts
            out = event.outcome.value
            by_outcome[out] = by_outcome.get(out, 0) + 1

            # Action counts
            act = f"{cat}:{event.action}"
            by_action[act] = by_action.get(act, 0) + 1

            # Unique actors
            unique_actors.add(event.actor_id)

            # Special counters
            if event.category == AuditCategory.AUTH and event.outcome == AuditOutcome.FAILURE:
                auth_failures += 1
            if event.outcome == AuditOutcome.DENIED:
                access_denials += 1
            if event.category == AuditCategory.SECURITY:
                security_events += 1

        # Build SOC 2 report
        report = {
            "report_type": "SOC 2 Type II Audit Log Export",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "audit_period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "days": (end_date - start_date).days,
            },
            "organization": org_id or "all",
            "integrity": {
                "chain_verified": is_valid,
                "errors": integrity_errors[:10] if integrity_errors else [],
                "total_errors": len(integrity_errors),
            },
            "summary": {
                "total_events": total_events,
                "unique_actors": len(unique_actors),
                "categories": by_category,
                "outcomes": by_outcome,
            },
            "security_metrics": {
                "authentication_failures": auth_failures,
                "access_denials": access_denials,
                "security_events": security_events,
            },
            "control_evidence": {
                "CC6.1_logical_access": {
                    "login_events": by_category.get("auth", 0),
                    "access_events": by_category.get("access", 0),
                },
                "CC6.2_access_removal": {
                    "relevant_actions": by_action.get("auth:logout", 0)
                    + by_action.get("admin:revoke_access", 0),
                },
                "CC6.3_access_authorization": {
                    "denied_attempts": access_denials,
                },
                "CC7.2_security_events": {
                    "total_security_events": security_events,
                },
            },
            "events": [e.to_dict() for e in events],
        }

        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)

        return {
            "events_exported": len(events),
            "integrity_verified": is_valid,
            "integrity_errors": len(integrity_errors),
        }

    def apply_retention(self) -> int:
        """
        Apply retention policy and delete old events.

        Returns:
            Number of events deleted
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)

        if self._backend_type == "file" and self._persistence_backend is not None:
            deleted = self._persistence_backend.delete_before(cutoff)
            if deleted > 0:
                logger.info(
                    "audit_retention_applied deleted=%s cutoff=%s",
                    deleted,
                    cutoff.date(),
                )
            return deleted

        row = self._backend.fetch_one(
            "SELECT COUNT(*) FROM audit_events WHERE timestamp < ?",
            (cutoff.isoformat(),),
        )
        deleted = row[0] if row else 0
        self._backend.execute_write(
            "DELETE FROM audit_events WHERE timestamp < ?",
            (cutoff.isoformat(),),
        )

        if deleted > 0:
            logger.info("audit_retention_applied deleted=%s cutoff=%s", deleted, cutoff.date())

        return deleted

    def get_stats(self) -> dict[str, Any]:
        """Get audit log statistics."""
        if self._backend_type == "file" and self._persistence_backend is not None:
            stats = self._persistence_backend.get_stats()
            stats["retention_days"] = self.retention_days
            return stats

        row = self._backend.fetch_one("""
            SELECT
                COUNT(*) as total,
                MIN(timestamp) as oldest,
                MAX(timestamp) as newest
            FROM audit_events
            """)

        by_category = {}
        for cat_row in self._backend.fetch_all(
            "SELECT category, COUNT(*) as count FROM audit_events GROUP BY category"
        ):
            by_category[cat_row[0]] = cat_row[1]

        return {
            "total_events": row[0] if row else 0,
            "oldest_event": row[1] if row else None,
            "newest_event": row[2] if row else None,
            "by_category": by_category,
            "retention_days": self.retention_days,
        }


# Convenience functions for common audit events
def audit_auth_login(
    audit: AuditLog,
    user_id: str,
    ip_address: str = "",
    success: bool = True,
    reason: str = "",
) -> str:
    """Log authentication attempt."""
    return audit.log(
        AuditEvent(
            category=AuditCategory.AUTH,
            action="login",
            actor_id=user_id,
            resource_type="session",
            outcome=AuditOutcome.SUCCESS if success else AuditOutcome.FAILURE,
            ip_address=ip_address,
            reason=reason,
        )
    )


def audit_data_access(
    audit: AuditLog,
    user_id: str,
    resource_type: str,
    resource_id: str,
    action: str = "read",
    org_id: str = "",
) -> str:
    """Log data access."""
    return audit.log(
        AuditEvent(
            category=AuditCategory.ACCESS,
            action=action,
            actor_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            org_id=org_id,
        )
    )


def audit_admin_action(
    audit: AuditLog,
    admin_id: str,
    action: str,
    target_type: str,
    target_id: str,
    details: dict | None = None,
) -> str:
    """Log administrative action."""
    return audit.log(
        AuditEvent(
            category=AuditCategory.ADMIN,
            action=action,
            actor_id=admin_id,
            resource_type=target_type,
            resource_id=target_id,
            details=details or {},
        )
    )


# Singleton management
_audit_log_instance: AuditLog | None = None


def get_audit_log(
    db_path: Path | None = None,
    retention_days: int = 365 * 7,
) -> AuditLog:
    """
    Get or create the singleton audit log instance.

    In production mode, this will raise DistributedStateError if no
    distributed backend (PostgreSQL) is configured, enforcing multi-instance
    consistency for compliance audit trails.

    Args:
        db_path: Path to SQLite database (default: .nomic/audit.db)
        retention_days: Days to retain logs (default: 7 years for SOX)

    Returns:
        Configured AuditLog instance
    """
    global _audit_log_instance

    if _audit_log_instance is not None:
        return _audit_log_instance

    # SECURITY: Enforce distributed storage in production for audit logs
    # Audit trails MUST be centralized for compliance (SOC2, HIPAA, SOX)

    require_distributed_store(
        "audit_log",
        StorageMode.SQLITE,
        "Audit logs must use distributed storage in production for "
        "compliance requirements (SOC2, HIPAA, SOX). Configure PostgreSQL.",
    )

    if db_path is None:
        from aragora.persistence.db_config import get_nomic_dir

        db_path = get_nomic_dir() / "audit.db"

    _audit_log_instance = AuditLog(db_path=db_path, retention_days=retention_days)
    return _audit_log_instance


def reset_audit_log() -> None:
    """Reset the singleton audit log instance (for testing)."""
    global _audit_log_instance
    _audit_log_instance = None


__all__ = [
    "AuditCategory",
    "AuditEvent",
    "AuditLog",
    "AuditOutcome",
    "AuditQuery",
    "audit_admin_action",
    "audit_auth_login",
    "audit_data_access",
    "get_audit_log",
    "reset_audit_log",
]
