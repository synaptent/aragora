"""
PostgreSQL persistence backend for audit logs.

Enterprise-grade backend for distributed deployments with:
- ACID transactions
- Concurrent access
- High availability support
- Efficient indexing
"""

from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .base import AuditPersistenceBackend, PersistenceError

if TYPE_CHECKING:
    from aragora.observability.audit_log import AuditEvent, AuditQuery

logger = logging.getLogger(__name__)

# Schema for PostgreSQL
POSTGRES_SCHEMA = """
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
    details JSONB DEFAULT '{}',
    reason TEXT,
    previous_hash TEXT,
    event_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_events(category);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events(actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_org ON audit_events(org_id);
CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_events(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_outcome ON audit_events(outcome);
CREATE INDEX IF NOT EXISTS idx_audit_hash ON audit_events(event_hash);
"""


class PostgresBackend(AuditPersistenceBackend):
    """
    PostgreSQL backend for enterprise audit log persistence.

    Features:
    - Connection pooling via context variables
    - JSONB for efficient details storage
    - Full-text search via ILIKE
    - Transaction safety
    """

    def __init__(self, database_url: str):
        """
        Initialize PostgreSQL backend.

        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = database_url
        self._conn_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
            f"postgres_audit_conn_{id(self)}", default=None
        )
        self._connections: list[Any] = []
        self._initialized = False

    def _get_connection(self) -> Any:
        """Get or create context-local database connection."""
        try:
            import psycopg2
        except ImportError:
            raise PersistenceError(
                "psycopg2 is required for PostgreSQL backend. "
                "Install with: pip install psycopg2-binary"
            )

        conn = self._conn_var.get()
        if conn is None:
            try:
                conn = psycopg2.connect(self.database_url)
                self._conn_var.set(conn)
                self._connections.append(conn)
            except (OSError, RuntimeError) as e:
                raise PersistenceError(f"Failed to connect to PostgreSQL: {e}")
        return conn

    def initialize(self) -> None:
        """Create database schema."""
        if self._initialized:
            return

        conn = self._get_connection()
        with conn.cursor() as cursor:
            for statement in POSTGRES_SCHEMA.strip().split(";"):
                statement = statement.strip()
                if statement:
                    cursor.execute(statement)
        conn.commit()
        self._initialized = True
        logger.info("PostgreSQL audit backend initialized")

    def store(self, event: AuditEvent) -> str:
        """Store an audit event."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO audit_events
                    (id, timestamp, category, action, actor_id, resource_type, resource_id,
                     outcome, ip_address, user_agent, correlation_id, org_id, workspace_id,
                     details, reason, previous_hash, event_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            conn.commit()
            return event.id
        except (OSError, RuntimeError) as e:
            conn.rollback()
            raise PersistenceError(f"Failed to store audit event: {e}")

    def get(self, event_id: str) -> AuditEvent | None:
        """Retrieve a single event by ID."""

        conn = self._get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM audit_events WHERE id = %s",
                (event_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_event(row, cursor.description)

    def query(self, query: AuditQuery) -> list[AuditEvent]:
        """Query events matching criteria."""
        conditions = []
        params: list[Any] = []

        if query.start_date:
            conditions.append("timestamp >= %s")
            params.append(query.start_date.isoformat())

        if query.end_date:
            conditions.append("timestamp <= %s")
            params.append(query.end_date.isoformat())

        if query.category:
            conditions.append("category = %s")
            params.append(query.category.value)

        if query.action:
            conditions.append("action = %s")
            params.append(query.action)

        if query.actor_id:
            conditions.append("actor_id = %s")
            params.append(query.actor_id)

        if query.resource_type:
            conditions.append("resource_type = %s")
            params.append(query.resource_type)

        if query.resource_id:
            conditions.append("resource_id = %s")
            params.append(query.resource_id)

        if query.outcome:
            conditions.append("outcome = %s")
            params.append(query.outcome.value)

        if query.org_id:
            conditions.append("org_id = %s")
            params.append(query.org_id)

        if query.ip_address:
            conditions.append("ip_address = %s")
            params.append(query.ip_address)

        if query.search_text:
            like = f"%{query.search_text}%"
            conditions.append(
                "(action ILIKE %s OR actor_id ILIKE %s OR resource_type ILIKE %s "
                "OR resource_id ILIKE %s OR details::text ILIKE %s OR reason ILIKE %s)"
            )
            params.extend([like, like, like, like, like, like])

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""
            SELECT * FROM audit_events
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT %s OFFSET %s
        """  # noqa: S608 -- dynamic clause from internal state
        params.extend([query.limit, query.offset])

        conn = self._get_connection()
        with conn.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_event(row, cursor.description) for row in rows]

    def get_last_hash(self) -> str:
        """Get the hash of the most recent event."""
        conn = self._get_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT event_hash FROM audit_events ORDER BY timestamp DESC LIMIT 1")
            row = cursor.fetchone()
            return row[0] if row else ""

    def count(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        """Count events in date range."""
        conditions = []
        params: list[Any] = []

        if start_date:
            conditions.append("timestamp >= %s")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("timestamp <= %s")
            params.append(end_date.isoformat())

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        conn = self._get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM audit_events WHERE {where_clause}",  # noqa: S608 -- dynamic clause from internal state
                tuple(params),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def delete_before(self, cutoff: datetime) -> int:
        """Delete events older than cutoff."""
        conn = self._get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM audit_events WHERE timestamp < %s",
                (cutoff.isoformat(),),
            )
            count = cursor.fetchone()[0]

            cursor.execute(
                "DELETE FROM audit_events WHERE timestamp < %s",
                (cutoff.isoformat(),),
            )
        conn.commit()
        return count

    def verify_integrity(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> tuple[bool, list[str]]:
        """Verify hash chain integrity."""
        from aragora.observability.audit_log import AuditQuery

        errors = []
        # AuditQuery structure preserved for potential future use
        _query = AuditQuery(
            start_date=start_date,
            end_date=end_date,
            limit=100000,
        )

        # Get events ordered by timestamp
        conditions = []
        params: list[Any] = []
        if start_date:
            conditions.append("timestamp >= %s")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("timestamp <= %s")
            params.append(end_date.isoformat())

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        conn = self._get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM audit_events WHERE {where_clause} ORDER BY timestamp",  # noqa: S608 -- dynamic clause from internal state
                tuple(params),
            )
            rows = cursor.fetchall()

            prev_hash = ""
            for row in rows:
                event = self._row_to_event(row, cursor.description)

                if event.previous_hash != prev_hash:
                    errors.append(
                        f"Hash chain broken at event {event.id}: "
                        f"expected previous_hash={prev_hash}, got {event.previous_hash}"
                    )

                computed = event.compute_hash()
                if event.event_hash != computed:
                    errors.append(
                        f"Event {event.id} hash mismatch: "
                        f"stored={event.event_hash}, computed={computed}"
                    )

                prev_hash = event.event_hash

        return len(errors) == 0, errors

    def close(self) -> None:
        """Close all connections."""
        for conn in self._connections:
            try:
                conn.close()
            except (OSError, RuntimeError) as e:
                logger.warning("Failed to close PostgreSQL connection: %s", e)
        self._connections.clear()
        self._conn_var.set(None)

    def _row_to_event(self, row: tuple, description: Any) -> AuditEvent:
        """Convert database row to AuditEvent."""
        from aragora.observability.audit_log import AuditCategory, AuditEvent, AuditOutcome

        columns = [col[0] for col in description]
        data = dict(zip(columns, row))

        details = data.get("details", {})
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except json.JSONDecodeError:
                details = {}

        return AuditEvent(
            id=data.get("id", ""),
            timestamp=(
                datetime.fromisoformat(str(data["timestamp"]))
                if data.get("timestamp")
                else datetime.now(timezone.utc)
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
            details=details,
            reason=data.get("reason", ""),
            previous_hash=data.get("previous_hash", ""),
            event_hash=data.get("event_hash", ""),
        )

    def get_stats(self) -> dict[str, Any]:
        """Get backend statistics."""
        conn = self._get_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    MIN(timestamp) as oldest,
                    MAX(timestamp) as newest
                FROM audit_events
            """)
            row = cursor.fetchone()

            cursor.execute("SELECT category, COUNT(*) FROM audit_events GROUP BY category")
            by_category = dict(cursor.fetchall())

        return {
            "backend": "PostgreSQL",
            "total_events": row[0] if row else 0,
            "oldest_event": str(row[1]) if row and row[1] else None,
            "newest_event": str(row[2]) if row and row[2] else None,
            "by_category": by_category,
        }
