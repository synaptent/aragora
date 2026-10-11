"""
Receipt Deletion Audit Log.

Provides an immutable audit trail for receipt deletions to ensure
GDPR/SOC2 compliance. Every deleted receipt is logged with:
- Receipt ID and checksum (for verification)
- Deletion timestamp and reason
- Operator who initiated the deletion

The deletion log itself is append-only and cannot be modified or deleted
to maintain audit integrity.

"Even what we forget, we must remember we forgot."
"""

from __future__ import annotations

import contextvars
import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aragora.config import resolve_db_path

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_DB_PATH = Path(resolve_db_path("receipt_deletions.db"))


@dataclass
class ReceiptDeletionRecord:
    """Record of a receipt deletion for audit purposes."""

    deletion_id: str
    receipt_id: str
    receipt_checksum: str
    gauntlet_id: str | None
    verdict: str | None
    deleted_at: float  # Unix timestamp
    reason: str  # "retention_expired", "user_request", "gdpr_erasure", "admin_action"
    operator: str  # User/system that initiated deletion
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "deletion_id": self.deletion_id,
            "receipt_id": self.receipt_id,
            "receipt_checksum": self.receipt_checksum,
            "gauntlet_id": self.gauntlet_id,
            "verdict": self.verdict,
            "deleted_at": self.deleted_at,
            "deleted_at_iso": datetime.fromtimestamp(self.deleted_at, tz=timezone.utc).isoformat(),
            "reason": self.reason,
            "operator": self.operator,
            "metadata": self.metadata,
        }


class ReceiptDeletionLog:
    """
    Immutable audit log for receipt deletions.

    Maintains a permanent record of all deleted receipts for compliance
    and audit purposes. The log is append-only - records cannot be
    modified or deleted.

    Usage:
        log = ReceiptDeletionLog()
        deletion_id = log.log_deletion(
            receipt_id="rcpt_abc123",
            receipt_checksum="sha256:...",
            reason="retention_expired",
            operator="system:cleanup_job"
        )
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS receipt_deletions (
        deletion_id TEXT PRIMARY KEY,
        receipt_id TEXT NOT NULL,
        receipt_checksum TEXT NOT NULL,
        gauntlet_id TEXT,
        verdict TEXT,
        deleted_at REAL NOT NULL,
        reason TEXT NOT NULL,
        operator TEXT NOT NULL,
        metadata TEXT DEFAULT '{}'
    );

    CREATE INDEX IF NOT EXISTS idx_receipt_deletions_receipt_id
        ON receipt_deletions(receipt_id);

    CREATE INDEX IF NOT EXISTS idx_receipt_deletions_deleted_at
        ON receipt_deletions(deleted_at);

    CREATE INDEX IF NOT EXISTS idx_receipt_deletions_reason
        ON receipt_deletions(reason);
    """

    # Valid deletion reasons
    VALID_REASONS = {
        "retention_expired",
        "user_request",
        "gdpr_erasure",
        "admin_action",
        "data_correction",
        "legal_hold_release",
    }

    def __init__(self, db_path: Path | None = None):
        """
        Initialize the deletion log.

        Args:
            db_path: Path to SQLite database file
        """
        self._db_path = db_path or DEFAULT_DB_PATH
        # ContextVar for per-async-context connection (async-safe replacement for threading.local)
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            f"receiptdeletion_conn_{id(self)}", default=None
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
            db_dir = self._db_path.parent
            if not db_dir.exists():
                db_dir.mkdir(parents=True, exist_ok=True)

            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
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

    def log_deletion(
        self,
        receipt_id: str,
        receipt_checksum: str,
        reason: str,
        operator: str,
        gauntlet_id: str | None = None,
        verdict: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Log a receipt deletion.

        Args:
            receipt_id: ID of the deleted receipt
            receipt_checksum: Integrity checksum of the deleted receipt
            reason: Reason for deletion (must be a valid reason)
            operator: User/system that initiated the deletion
            gauntlet_id: Associated gauntlet ID (optional)
            verdict: Receipt verdict before deletion (optional)
            metadata: Additional metadata to store (optional)

        Returns:
            Deletion record ID

        Raises:
            ValueError: If reason is not valid
        """
        if reason not in self.VALID_REASONS:
            raise ValueError(
                f"Invalid deletion reason: {reason}. "
                f"Must be one of: {', '.join(sorted(self.VALID_REASONS))}"
            )

        deletion_id = f"del_{uuid.uuid4().hex[:12]}"
        deleted_at = time.time()

        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO receipt_deletions
                (deletion_id, receipt_id, receipt_checksum, gauntlet_id, verdict,
                 deleted_at, reason, operator, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deletion_id,
                    receipt_id,
                    receipt_checksum,
                    gauntlet_id,
                    verdict,
                    deleted_at,
                    reason,
                    operator,
                    json.dumps(metadata or {}),
                ),
            )
            conn.commit()

            logger.info(
                "receipt_deletion_logged",
                extra={
                    "deletion_id": deletion_id,
                    "receipt_id": receipt_id,
                    "reason": reason,
                    "operator": operator,
                },
            )

            return deletion_id

        except sqlite3.Error as e:
            logger.error("Failed to log deletion for %s: %s", receipt_id, e)
            raise

    def log_batch_deletion(
        self,
        receipts: list[dict[str, Any]],
        reason: str,
        operator: str,
    ) -> list[str]:
        """
        Log multiple receipt deletions in a single transaction.

        Args:
            receipts: List of receipt dicts with id, checksum, gauntlet_id, verdict
            reason: Reason for deletion
            operator: User/system that initiated the deletion

        Returns:
            List of deletion record IDs
        """
        if reason not in self.VALID_REASONS:
            raise ValueError(f"Invalid deletion reason: {reason}")

        deletion_ids = []
        deleted_at = time.time()
        conn = self._get_connection()

        try:
            for receipt in receipts:
                deletion_id = f"del_{uuid.uuid4().hex[:12]}"
                deletion_ids.append(deletion_id)

                conn.execute(
                    """
                    INSERT INTO receipt_deletions
                    (deletion_id, receipt_id, receipt_checksum, gauntlet_id, verdict,
                     deleted_at, reason, operator, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        deletion_id,
                        receipt["receipt_id"],
                        receipt.get("checksum", ""),
                        receipt.get("gauntlet_id"),
                        receipt.get("verdict"),
                        deleted_at,
                        reason,
                        operator,
                        json.dumps(receipt.get("metadata", {})),
                    ),
                )

            conn.commit()

            logger.info(
                "batch_deletion_logged",
                extra={
                    "count": len(deletion_ids),
                    "reason": reason,
                    "operator": operator,
                },
            )

            return deletion_ids

        except sqlite3.Error as e:
            conn.rollback()
            logger.error("Failed to log batch deletion: %s", e)
            raise

    def get_deletion(self, deletion_id: str) -> ReceiptDeletionRecord | None:
        """Get a specific deletion record."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM receipt_deletions WHERE deletion_id = ?",
                (deletion_id,),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_record(row)
            return None
        except sqlite3.Error as e:
            logger.error("Failed to get deletion %s: %s", deletion_id, e)
            return None

    def find_by_receipt_id(self, receipt_id: str) -> list[ReceiptDeletionRecord]:
        """Find all deletion records for a receipt ID."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM receipt_deletions WHERE receipt_id = ? ORDER BY deleted_at DESC",
                (receipt_id,),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("Failed to find deletions for %s: %s", receipt_id, e)
            return []

    def list_deletions(
        self,
        reason: str | None = None,
        operator: str | None = None,
        from_date: float | None = None,
        to_date: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReceiptDeletionRecord]:
        """
        List deletion records with optional filters.

        Args:
            reason: Filter by deletion reason
            operator: Filter by operator
            from_date: Filter by deletion date (Unix timestamp)
            to_date: Filter by deletion date (Unix timestamp)
            limit: Maximum records to return
            offset: Number of records to skip

        Returns:
            List of deletion records
        """
        conn = self._get_connection()

        conditions = []
        params: list[Any] = []

        if reason:
            conditions.append("reason = ?")
            params.append(reason)
        if operator:
            conditions.append("operator = ?")
            params.append(operator)
        if from_date:
            conditions.append("deleted_at >= ?")
            params.append(from_date)
        if to_date:
            conditions.append("deleted_at <= ?")
            params.append(to_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        try:
            cursor = conn.execute(
                f"""
                SELECT * FROM receipt_deletions
                WHERE {where_clause}
                ORDER BY deleted_at DESC
                LIMIT ? OFFSET ?
                """,  # dynamic clause from internal state
                (*params, limit, offset),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("Failed to list deletions: %s", e)
            return []

    def count_deletions(
        self,
        reason: str | None = None,
        from_date: float | None = None,
        to_date: float | None = None,
    ) -> int:
        """Count deletion records with optional filters."""
        conn = self._get_connection()

        conditions = []
        params: list[Any] = []

        if reason:
            conditions.append("reason = ?")
            params.append(reason)
        if from_date:
            conditions.append("deleted_at >= ?")
            params.append(from_date)
        if to_date:
            conditions.append("deleted_at <= ?")
            params.append(to_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        try:
            cursor = conn.execute(
                # dynamic clause from internal state
                f"SELECT COUNT(*) FROM receipt_deletions WHERE {where_clause}",
                params,
            )
            result = cursor.fetchone()
            return result[0] if result else 0
        except sqlite3.Error as e:
            logger.error("Failed to count deletions: %s", e)
            return 0

    def get_stats(self) -> dict[str, Any]:
        """Get deletion statistics."""
        conn = self._get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) FROM receipt_deletions").fetchone()[0]

            by_reason = {}
            cursor = conn.execute("SELECT reason, COUNT(*) FROM receipt_deletions GROUP BY reason")
            for row in cursor.fetchall():
                by_reason[row[0]] = row[1]

            return {
                "total_deletions": total,
                "by_reason": by_reason,
            }
        except sqlite3.Error as e:
            logger.error("Failed to get stats: %s", e)
            return {"total_deletions": 0, "by_reason": {}}

    def _row_to_record(self, row: sqlite3.Row) -> ReceiptDeletionRecord:
        """Convert a database row to a ReceiptDeletionRecord."""
        return ReceiptDeletionRecord(
            deletion_id=row["deletion_id"],
            receipt_id=row["receipt_id"],
            receipt_checksum=row["receipt_checksum"],
            gauntlet_id=row["gauntlet_id"],
            verdict=row["verdict"],
            deleted_at=row["deleted_at"],
            reason=row["reason"],
            operator=row["operator"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )


# Singleton instance
_deletion_log: ReceiptDeletionLog | None = None
_log_lock = threading.RLock()


def get_receipt_deletion_log(db_path: Path | None = None) -> ReceiptDeletionLog:
    """Get or create the singleton deletion log instance."""
    global _deletion_log

    with _log_lock:
        if _deletion_log is None:
            _deletion_log = ReceiptDeletionLog(db_path)
        return _deletion_log
