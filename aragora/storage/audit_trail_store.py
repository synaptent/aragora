"""
Audit Trail and Decision Receipt Storage.

Provides persistent storage for:
- Gauntlet audit trails (event timelines)
- Decision receipts (compliance artifacts)

Replaces in-memory storage in AuditTrailHandler for production deployments.

Backends:
- SQLite: Default for single-instance deployments
- PostgreSQL: For production multi-instance deployments

Usage:
    from aragora.storage.audit_trail_store import get_audit_trail_store

    store = get_audit_trail_store()
    await store.save_trail(trail_dict)
    trail = await store.get_trail(trail_id)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
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
DEFAULT_RETENTION_DAYS = int(
    os.environ.get("ARAGORA_AUDIT_TRAIL_RETENTION_DAYS", "365")
)  # 1 year default
DEFAULT_DB_PATH = Path(resolve_db_path("audit_trails.db"))


@dataclass
class StoredTrail:
    """A stored audit trail entry."""

    trail_id: str
    gauntlet_id: str
    created_at: float
    verdict: str
    confidence: float
    total_findings: int
    duration_seconds: float
    receipt_id: str | None
    data: dict[str, Any]  # Full trail JSON

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "trail_id": self.trail_id,
            "gauntlet_id": self.gauntlet_id,
            "created_at": self.created_at,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "total_findings": self.total_findings,
            "duration_seconds": self.duration_seconds,
            "receipt_id": self.receipt_id,
            **self.data,
        }


@dataclass
class StoredReceipt:
    """A stored decision receipt entry."""

    receipt_id: str
    gauntlet_id: str
    created_at: float
    verdict: str
    confidence: float
    risk_level: str
    checksum: str
    audit_trail_id: str | None
    data: dict[str, Any]  # Full receipt JSON

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "receipt_id": self.receipt_id,
            "gauntlet_id": self.gauntlet_id,
            "created_at": self.created_at,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "checksum": self.checksum,
            "audit_trail_id": self.audit_trail_id,
            **self.data,
        }


class AuditTrailStore:
    """
    Database-backed storage for audit trails and decision receipts.

    Supports SQLite (default) and PostgreSQL backends.
    Provides persistence for the AuditTrailHandler.
    """

    SCHEMA_STATEMENTS = [
        """
        CREATE TABLE IF NOT EXISTS audit_trails (
            trail_id TEXT PRIMARY KEY,
            gauntlet_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            verdict TEXT NOT NULL,
            confidence REAL NOT NULL,
            total_findings INTEGER NOT NULL DEFAULT 0,
            duration_seconds REAL NOT NULL DEFAULT 0,
            receipt_id TEXT,
            data_json TEXT NOT NULL,
            UNIQUE(gauntlet_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_trails_created ON audit_trails(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_trails_gauntlet ON audit_trails(gauntlet_id)",
        "CREATE INDEX IF NOT EXISTS idx_trails_receipt ON audit_trails(receipt_id)",
        """
        CREATE TABLE IF NOT EXISTS decision_receipts (
            receipt_id TEXT PRIMARY KEY,
            gauntlet_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            verdict TEXT NOT NULL,
            confidence REAL NOT NULL,
            risk_level TEXT NOT NULL,
            checksum TEXT NOT NULL,
            audit_trail_id TEXT,
            data_json TEXT NOT NULL,
            UNIQUE(gauntlet_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_receipts_created ON decision_receipts(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_gauntlet ON decision_receipts(gauntlet_id)",
        "CREATE INDEX IF NOT EXISTS idx_receipts_trail ON decision_receipts(audit_trail_id)",
    ]

    def __init__(
        self,
        db_path: Path | None = None,
        backend: str | None = None,
        database_url: str | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ):
        """
        Initialize audit trail store.

        Args:
            db_path: Path to SQLite database (used when backend="sqlite")
            backend: Database backend ("sqlite" or "postgresql")
            database_url: PostgreSQL connection URL
            retention_days: Days to retain trails (default: 365)
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self.retention_days = retention_days

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

        if backend == "postgresql":
            if not actual_url:
                raise ValueError("PostgreSQL backend requires DATABASE_URL")
            if not POSTGRESQL_AVAILABLE:
                raise ImportError("psycopg2 required for PostgreSQL")
            self._backend = PostgreSQLBackend(actual_url)
            logger.info("AuditTrailStore using PostgreSQL backend")
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._backend = SQLiteBackend(str(self.db_path))
            logger.info("AuditTrailStore using SQLite backend: %s", self.db_path)

        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        if self._backend is None:
            return

        for statement in self.SCHEMA_STATEMENTS:
            try:
                self._backend.execute_write(statement)
            except (OSError, RuntimeError, ValueError) as e:
                logger.debug("Schema statement skipped: %s", e)
            except Exception as e:  # noqa: BLE001 - filter for read-only DB, re-raises otherwise
                err_msg = str(e).lower()
                if "read-only" in err_msg or "read only" in err_msg:
                    logger.info("AuditTrailStore: read-only database, skipping schema init")
                    break
                raise

    # =========================================================================
    # Audit Trail Methods
    # =========================================================================

    def save_trail(self, trail_dict: dict[str, Any]) -> None:
        """
        Save an audit trail.

        Args:
            trail_dict: Trail data from AuditTrail.to_dict()
        """
        if self._backend is None:
            return

        trail_id = trail_dict.get("trail_id", "")
        gauntlet_id = trail_dict.get("gauntlet_id", "")
        created_at = trail_dict.get("created_at", time.time())
        if isinstance(created_at, str):
            # Parse ISO format timestamp
            from datetime import datetime

            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                created_at = time.time()

        self._backend.execute_write(
            """
            INSERT OR REPLACE INTO audit_trails
            (trail_id, gauntlet_id, created_at, verdict, confidence,
             total_findings, duration_seconds, receipt_id, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trail_id,
                gauntlet_id,
                created_at,
                trail_dict.get("verdict", ""),
                trail_dict.get("confidence", 0.0),
                trail_dict.get("total_findings", 0),
                trail_dict.get("duration_seconds", 0.0),
                trail_dict.get("receipt_id"),
                json.dumps(trail_dict),
            ),
        )
        logger.debug("Saved audit trail: %s", trail_id)

    def get_trail(self, trail_id: str) -> dict[str, Any] | None:
        """
        Get an audit trail by ID.

        Args:
            trail_id: Trail ID to retrieve

        Returns:
            Trail dict or None if not found
        """
        if self._backend is None:
            return None

        row = self._backend.fetch_one(
            "SELECT data_json FROM audit_trails WHERE trail_id = ?",
            (trail_id,),
        )
        if row:
            return json.loads(row[0])
        return None

    def get_trail_by_gauntlet(self, gauntlet_id: str) -> dict[str, Any] | None:
        """Get audit trail by gauntlet ID."""
        if self._backend is None:
            return None

        row = self._backend.fetch_one(
            "SELECT data_json FROM audit_trails WHERE gauntlet_id = ?",
            (gauntlet_id,),
        )
        if row:
            return json.loads(row[0])
        return None

    def list_trails(
        self,
        limit: int = 20,
        offset: int = 0,
        verdict: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List audit trails with pagination.

        Args:
            limit: Maximum trails to return
            offset: Pagination offset
            verdict: Filter by verdict

        Returns:
            List of trail summary dicts
        """
        if self._backend is None:
            return []

        if verdict:
            rows = self._backend.fetch_all(
                """
                SELECT trail_id, gauntlet_id, created_at, verdict, confidence,
                       total_findings, duration_seconds, receipt_id
                FROM audit_trails
                WHERE verdict = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (verdict, limit, offset),
            )
        else:
            rows = self._backend.fetch_all(
                """
                SELECT trail_id, gauntlet_id, created_at, verdict, confidence,
                       total_findings, duration_seconds, receipt_id
                FROM audit_trails
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )

        return [
            {
                "trail_id": row[0],
                "gauntlet_id": row[1],
                "created_at": row[2],
                "verdict": row[3],
                "confidence": row[4],
                "total_findings": row[5],
                "duration_seconds": row[6],
                "receipt_id": row[7],
            }
            for row in rows
        ]

    def count_trails(self, verdict: str | None = None) -> int:
        """Get total count of audit trails."""
        if self._backend is None:
            return 0

        if verdict:
            row = self._backend.fetch_one(
                "SELECT COUNT(*) FROM audit_trails WHERE verdict = ?",
                (verdict,),
            )
        else:
            row = self._backend.fetch_one("SELECT COUNT(*) FROM audit_trails")

        return row[0] if row else 0

    def link_trail_to_receipt(self, trail_id: str, receipt_id: str) -> None:
        """Update trail with receipt reference."""
        if self._backend is None:
            return

        self._backend.execute_write(
            "UPDATE audit_trails SET receipt_id = ? WHERE trail_id = ?",
            (receipt_id, trail_id),
        )

    # =========================================================================
    # Decision Receipt Methods
    # =========================================================================

    def save_receipt(self, receipt_dict: dict[str, Any]) -> None:
        """
        Save a decision receipt.

        Args:
            receipt_dict: Receipt data from DecisionReceipt.to_dict()
        """
        if self._backend is None:
            return

        receipt_id = receipt_dict.get("receipt_id", "")
        gauntlet_id = receipt_dict.get("gauntlet_id", "")
        created_at = receipt_dict.get("timestamp", time.time())
        if isinstance(created_at, str):
            from datetime import datetime

            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                created_at = time.time()

        self._backend.execute_write(
            """
            INSERT OR REPLACE INTO decision_receipts
            (receipt_id, gauntlet_id, created_at, verdict, confidence,
             risk_level, checksum, audit_trail_id, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                gauntlet_id,
                created_at,
                receipt_dict.get("verdict", ""),
                receipt_dict.get("confidence", 0.0),
                receipt_dict.get("risk_level", "MEDIUM"),
                receipt_dict.get("checksum", ""),
                receipt_dict.get("audit_trail_id"),
                json.dumps(receipt_dict),
            ),
        )
        logger.debug("Saved decision receipt: %s", receipt_id)

    def get_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        """
        Get a decision receipt by ID.

        Args:
            receipt_id: Receipt ID to retrieve

        Returns:
            Receipt dict or None if not found
        """
        if self._backend is None:
            return None

        row = self._backend.fetch_one(
            "SELECT data_json FROM decision_receipts WHERE receipt_id = ?",
            (receipt_id,),
        )
        if row:
            return json.loads(row[0])
        return None

    def get_receipt_by_gauntlet(self, gauntlet_id: str) -> dict[str, Any] | None:
        """Get decision receipt by gauntlet ID."""
        if self._backend is None:
            return None

        row = self._backend.fetch_one(
            "SELECT data_json FROM decision_receipts WHERE gauntlet_id = ?",
            (gauntlet_id,),
        )
        if row:
            return json.loads(row[0])
        return None

    def list_receipts(
        self,
        limit: int = 20,
        offset: int = 0,
        verdict: str | None = None,
        risk_level: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List decision receipts with pagination.

        Args:
            limit: Maximum receipts to return
            offset: Pagination offset
            verdict: Filter by verdict
            risk_level: Filter by risk level

        Returns:
            List of receipt summary dicts
        """
        if self._backend is None:
            return []

        conditions = []
        params: list[Any] = []

        if verdict:
            conditions.append("verdict = ?")
            params.append(verdict)
        if risk_level:
            conditions.append("risk_level = ?")
            params.append(risk_level)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        rows = self._backend.fetch_all(
            f"""
            SELECT receipt_id, gauntlet_id, created_at, verdict, confidence,
                   risk_level, checksum, audit_trail_id
            FROM decision_receipts
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,  # nosec B608 - where_clause built from hardcoded conditions  # noqa: S608
            tuple(params),
        )

        return [
            {
                "receipt_id": row[0],
                "gauntlet_id": row[1],
                "created_at": row[2],
                "verdict": row[3],
                "confidence": row[4],
                "risk_level": row[5],
                "checksum": row[6],
                "audit_trail_id": row[7],
            }
            for row in rows
        ]

    def count_receipts(
        self,
        verdict: str | None = None,
        risk_level: str | None = None,
    ) -> int:
        """Get total count of decision receipts."""
        if self._backend is None:
            return 0

        conditions = []
        params: list[Any] = []

        if verdict:
            conditions.append("verdict = ?")
            params.append(verdict)
        if risk_level:
            conditions.append("risk_level = ?")
            params.append(risk_level)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        row = self._backend.fetch_one(
            f"SELECT COUNT(*) FROM decision_receipts WHERE {where_clause}",  # nosec B608  # noqa: S608
            tuple(params),
        )
        return row[0] if row else 0

    def link_receipt_to_trail(self, receipt_id: str, trail_id: str) -> None:
        """Update receipt with trail reference."""
        if self._backend is None:
            return

        self._backend.execute_write(
            "UPDATE decision_receipts SET audit_trail_id = ? WHERE receipt_id = ?",
            (trail_id, receipt_id),
        )

    # =========================================================================
    # Cleanup Methods
    # =========================================================================

    def cleanup_expired(self) -> int:
        """
        Remove trails and receipts older than retention period.

        Returns:
            Number of entries removed
        """
        if self._backend is None:
            return 0

        cutoff = time.time() - (self.retention_days * 86400)
        total_removed = 0

        # Clean trails
        result = self._backend.fetch_one(
            "SELECT COUNT(*) FROM audit_trails WHERE created_at < ?",
            (cutoff,),
        )
        trail_count = result[0] if result else 0
        if trail_count > 0:
            self._backend.execute_write(
                "DELETE FROM audit_trails WHERE created_at < ?",
                (cutoff,),
            )
            total_removed += trail_count

        # Clean receipts
        result = self._backend.fetch_one(
            "SELECT COUNT(*) FROM decision_receipts WHERE created_at < ?",
            (cutoff,),
        )
        receipt_count = result[0] if result else 0
        if receipt_count > 0:
            self._backend.execute_write(
                "DELETE FROM decision_receipts WHERE created_at < ?",
                (cutoff,),
            )
            total_removed += receipt_count

        if total_removed > 0:
            logger.info(
                "Cleaned up %s audit trail entries older than %s days",
                total_removed,
                self.retention_days,
            )

        return total_removed

    def close(self) -> None:
        """Close database connection."""
        if self._backend is not None:
            self._backend.close()
            self._backend = None


# Module-level singleton
_default_store: AuditTrailStore | None = None
_store_lock = threading.Lock()


def get_audit_trail_store(
    db_path: Path | None = None,
    backend: str | None = None,
    database_url: str | None = None,
) -> AuditTrailStore:
    """
    Get or create the default AuditTrailStore instance.

    Backend selection (in preference order):
    1. Supabase PostgreSQL (if SUPABASE_URL + SUPABASE_DB_PASSWORD configured)
    2. Self-hosted PostgreSQL (if DATABASE_URL or ARAGORA_POSTGRES_DSN configured)
    3. SQLite (fallback, with production warning)

    Override via:
    - ARAGORA_AUDIT_TRAIL_STORE_BACKEND: "sqlite", "postgres", or "supabase"
    - ARAGORA_DB_BACKEND: Global override

    Returns:
        Configured AuditTrailStore instance
    """
    global _default_store

    if _default_store is None:
        with _store_lock:
            if _default_store is None:
                # Use connection factory to determine backend and DSN
                from aragora.storage.connection_factory import (
                    resolve_database_config,
                    StorageBackendType,
                )

                # Check for explicit backend override, else use preference order
                store_backend = os.environ.get("ARAGORA_AUDIT_TRAIL_STORE_BACKEND")
                if not store_backend and backend is None:
                    config = resolve_database_config("audit_trail", allow_sqlite=True)
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
                        config = resolve_database_config("audit_trail", allow_sqlite=True)
                        database_url = database_url or config.dsn
                        backend = "postgresql"
                    else:
                        backend = store_backend

                _default_store = AuditTrailStore(
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
                        "audit_trail_store",
                        StorageMode.SQLITE,
                        "Audit trails must use distributed storage in production. "
                        "Configure SUPABASE_URL or DATABASE_URL for PostgreSQL.",
                    )

    return _default_store


def reset_audit_trail_store() -> None:
    """Reset the default store instance (for testing)."""
    global _default_store
    with _store_lock:
        if _default_store is not None:
            _default_store.close()
            _default_store = None


__all__ = [
    "AuditTrailStore",
    "StoredTrail",
    "StoredReceipt",
    "get_audit_trail_store",
    "reset_audit_trail_store",
]
