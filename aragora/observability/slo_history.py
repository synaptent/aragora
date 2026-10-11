"""
SLO History Persistence.

Stores SLO violations for audit trail and trend analysis.
Uses SQLite for lightweight, zero-dependency persistence.

Usage:
    from aragora.observability.slo_history import (
        SLOHistoryStore,
        get_slo_history_store,
        slo_history_callback,
    )

    # Wire into SLOAlertMonitor
    from aragora.observability.slo import get_global_monitor
    monitor = get_global_monitor()
    monitor.add_callback(slo_history_callback)

    # Query violations
    store = get_slo_history_store()
    violations = store.query(slo_name="availability")
    recent = store.query(hours=24)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Iterator

from aragora.config import resolve_db_path

logger = logging.getLogger(__name__)

# Default retention: 90 days
DEFAULT_RETENTION_DAYS = 90


@dataclass
class SLOViolationRecord:
    """A persisted SLO violation record."""

    id: int
    timestamp: str
    slo_name: str
    severity: str
    current_value: float
    target_value: float
    error_budget_remaining: float
    burn_rate: float
    message: str
    metadata: str | None = None

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "timestamp": self.timestamp,
            "slo_name": self.slo_name,
            "severity": self.severity,
            "current_value": self.current_value,
            "target_value": self.target_value,
            "error_budget_remaining": self.error_budget_remaining,
            "burn_rate": self.burn_rate,
            "message": self.message,
        }
        if self.metadata:
            try:
                result["metadata"] = json.loads(self.metadata)
            except (json.JSONDecodeError, TypeError):
                result["metadata"] = self.metadata
        return result


class SLOHistoryStore:
    """
    SQLite-backed SLO violation store.

    Thread-safe. Each instance maintains its own connection pool.
    """

    _CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS slo_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            slo_name TEXT NOT NULL,
            severity TEXT NOT NULL,
            current_value REAL NOT NULL,
            target_value REAL NOT NULL,
            error_budget_remaining REAL NOT NULL,
            burn_rate REAL NOT NULL,
            message TEXT NOT NULL,
            metadata TEXT
        )
    """

    _CREATE_INDICES = [
        "CREATE INDEX IF NOT EXISTS idx_slo_violations_name ON slo_violations(slo_name)",
        "CREATE INDEX IF NOT EXISTS idx_slo_violations_severity ON slo_violations(severity)",
        "CREATE INDEX IF NOT EXISTS idx_slo_violations_timestamp ON slo_violations(timestamp)",
    ]

    def __init__(
        self,
        db_path: str | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ):
        self._db_path = db_path or self._default_db_path()
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._ensure_schema()

    @staticmethod
    def _default_db_path() -> str:
        db_path = resolve_db_path("slo_history.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return str(db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(self._CREATE_TABLE)
            for idx_sql in self._CREATE_INDICES:
                conn.execute(idx_sql)

    def record_violation(
        self,
        slo_name: str,
        severity: str,
        current_value: float,
        target_value: float,
        error_budget_remaining: float,
        burn_rate: float,
        message: str,
        metadata: dict | None = None,
        timestamp: datetime | None = None,
    ) -> int:
        """Record an SLO violation.

        Returns the row ID of the inserted record.
        """
        ts = (timestamp or datetime.now(timezone.utc)).isoformat()
        meta_json = json.dumps(metadata) if metadata else None

        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO slo_violations
                    (timestamp, slo_name, severity, current_value, target_value,
                     error_budget_remaining, burn_rate, message, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    slo_name,
                    severity,
                    current_value,
                    target_value,
                    error_budget_remaining,
                    burn_rate,
                    message,
                    meta_json,
                ),
            )
            return cursor.lastrowid or 0

    def query(
        self,
        slo_name: str | None = None,
        severity: str | None = None,
        hours: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[SLOViolationRecord]:
        """Query SLO violations with filters.

        Args:
            slo_name: Filter by SLO name.
            severity: Filter by severity (warning, critical, etc.).
            hours: Filter to last N hours.
            since: Filter from this timestamp.
            until: Filter until this timestamp.
            limit: Maximum records to return.

        Returns:
            List of violation records, newest first.
        """
        conditions: list[str] = []
        params: list = []

        if slo_name:
            conditions.append("slo_name = ?")
            params.append(slo_name)

        if severity:
            conditions.append("severity = ?")
            params.append(severity)

        if hours:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            conditions.append("timestamp >= ?")
            params.append(cutoff)

        if since:
            conditions.append("timestamp >= ?")
            params.append(since.isoformat())

        if until:
            conditions.append("timestamp <= ?")
            params.append(until.isoformat())

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""
            SELECT id, timestamp, slo_name, severity, current_value, target_value,
                   error_budget_remaining, burn_rate, message, metadata
            FROM slo_violations
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
        """  # dynamic clause from internal state
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            SLOViolationRecord(
                id=row["id"],
                timestamp=row["timestamp"],
                slo_name=row["slo_name"],
                severity=row["severity"],
                current_value=row["current_value"],
                target_value=row["target_value"],
                error_budget_remaining=row["error_budget_remaining"],
                burn_rate=row["burn_rate"],
                message=row["message"],
                metadata=row["metadata"],
            )
            for row in rows
        ]

    def count(
        self,
        slo_name: str | None = None,
        severity: str | None = None,
        hours: int | None = None,
    ) -> int:
        """Count violations matching filters."""
        conditions: list[str] = []
        params: list = []

        if slo_name:
            conditions.append("slo_name = ?")
            params.append(slo_name)

        if severity:
            conditions.append("severity = ?")
            params.append(severity)

        if hours:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            conditions.append("timestamp >= ?")
            params.append(cutoff)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        # dynamic clause from internal state
        sql = f"SELECT COUNT(*) as cnt FROM slo_violations WHERE {where_clause}"

        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return row["cnt"] if row else 0

    def cleanup(self, retention_days: int | None = None) -> int:
        """Remove violations older than retention period.

        Returns the number of deleted records.
        """
        days = retention_days or self._retention_days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM slo_violations WHERE timestamp < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
            if deleted:
                logger.info(
                    "SLO history cleanup: removed %s records older than %s days", deleted, days
                )
            return deleted

    def get_summary(self, hours: int = 24) -> dict:
        """Get a summary of violations in the given time window.

        Returns dict with counts by SLO name and severity.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        with self._connect() as conn:
            # By SLO name
            by_slo = conn.execute(
                """
                SELECT slo_name, COUNT(*) as cnt
                FROM slo_violations
                WHERE timestamp >= ?
                GROUP BY slo_name
                ORDER BY cnt DESC
                """,
                (cutoff,),
            ).fetchall()

            # By severity
            by_severity = conn.execute(
                """
                SELECT severity, COUNT(*) as cnt
                FROM slo_violations
                WHERE timestamp >= ?
                GROUP BY severity
                ORDER BY cnt DESC
                """,
                (cutoff,),
            ).fetchall()

            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM slo_violations WHERE timestamp >= ?",
                (cutoff,),
            ).fetchone()

        return {
            "hours": hours,
            "total": total["cnt"] if total else 0,
            "by_slo": {row["slo_name"]: row["cnt"] for row in by_slo},
            "by_severity": {row["severity"]: row["cnt"] for row in by_severity},
        }


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_global_store: SLOHistoryStore | None = None
_store_lock = threading.Lock()


def get_slo_history_store(db_path: str | None = None) -> SLOHistoryStore:
    """Get or create the global SLO history store."""
    global _global_store
    with _store_lock:
        if _global_store is None:
            _global_store = SLOHistoryStore(db_path=db_path)
        return _global_store


def reset_slo_history_store() -> None:
    """Reset the global store (for testing)."""
    global _global_store
    with _store_lock:
        _global_store = None


# ---------------------------------------------------------------------------
# SLOAlertMonitor callback
# ---------------------------------------------------------------------------


def slo_history_callback(breach) -> None:
    """
    Callback for SLOAlertMonitor that persists violations.

    Wire into monitor:
        monitor.add_callback(slo_history_callback)
    """
    try:
        store = get_slo_history_store()
        store.record_violation(
            slo_name=breach.slo_name,
            severity=breach.severity,
            current_value=breach.current_value,
            target_value=breach.target_value,
            error_budget_remaining=breach.error_budget_remaining,
            burn_rate=breach.burn_rate,
            message=breach.message,
            timestamp=getattr(breach, "timestamp", None),
        )
    except (OSError, sqlite3.Error, AttributeError) as e:
        logger.error("Failed to persist SLO violation: %s", e)


__all__ = [
    "SLOHistoryStore",
    "SLOViolationRecord",
    "get_slo_history_store",
    "reset_slo_history_store",
    "slo_history_callback",
]
