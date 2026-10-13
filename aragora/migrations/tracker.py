"""
Migration version tracking for Aragora database migrations.

Provides persistent tracking of applied migrations with checksum verification
and rollback SQL storage for disaster recovery.

Features:
- Checksum verification to detect modified migration files
- Rollback SQL storage for each migration
- Applied/pending migration queries
- Supports both SQLite and PostgreSQL backends

Usage:
    from aragora.migrations.tracker import MigrationTracker
    from aragora.storage.backends import SQLiteBackend

    backend = SQLiteBackend("aragora.db")
    tracker = MigrationTracker(backend)

    # Check if a migration has been applied
    if not await tracker.is_applied("20240101000000"):
        await tracker.mark_applied(
            version="20240101000000",
            name="Initial schema",
            checksum="abc123...",
            rollback_sql="DROP TABLE IF EXISTS users;"
        )

    # Get all applied versions
    versions = await tracker.get_applied_versions()

    # Get pending migrations
    pending = await tracker.get_pending_migrations(available_versions)
"""

from __future__ import annotations

import hashlib
import logging
import os
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from aragora.storage.backends import DatabaseBackend

logger = logging.getLogger(__name__)


@runtime_checkable
class DatabaseBackendProtocol(Protocol):
    """Protocol for database backends that can be used with MigrationTracker."""

    def execute_write(self, sql: str, params: tuple = ()) -> None:
        """Execute a write operation."""
        ...

    def fetch_all(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Fetch all rows from a query."""
        ...

    def fetch_one(self, sql: str, params: tuple = ()) -> tuple | None:
        """Fetch a single row from a query."""
        ...


@dataclass
class AppliedMigration:
    """
    Represents a migration that has been applied to the database.

    Attributes:
        version: Unique version identifier (timestamp-based recommended)
        name: Human-readable migration name
        applied_at: When the migration was applied
        applied_by: Who/what applied the migration (hostname:pid)
        checksum: SHA-256 hash of migration content for change detection
        rollback_sql: SQL to reverse the migration (if available)
    """

    version: str
    name: str
    applied_at: datetime
    applied_by: str | None = None
    checksum: str | None = None
    rollback_sql: str | None = None


class MigrationTracker:
    """
    Track applied migrations in the database.

    Maintains a schema_migrations table that records which migrations have been
    applied, their checksums (for detecting changes), and rollback SQL for
    disaster recovery.

    The tracker is backend-agnostic and works with both SQLite and PostgreSQL.
    """

    TABLE_NAME = "schema_migrations"

    SCHEMA_SQLITE = """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version VARCHAR(255) NOT NULL UNIQUE,
            name VARCHAR(255) NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            applied_by VARCHAR(255),
            checksum VARCHAR(64),
            rollback_sql TEXT
        )
    """

    SCHEMA_POSTGRES = """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id SERIAL PRIMARY KEY,
            version VARCHAR(255) NOT NULL UNIQUE,
            name VARCHAR(255) NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            applied_by VARCHAR(255),
            checksum VARCHAR(64),
            rollback_sql TEXT
        )
    """

    def __init__(self, backend: DatabaseBackend | DatabaseBackendProtocol) -> None:
        """
        Initialize the migration tracker.

        Args:
            backend: Database backend for persistence.
        """
        self._backend = backend
        self._initialized = False

    def _ensure_table(self) -> None:
        """Create the schema_migrations table if it doesn't exist."""
        if self._initialized:
            return

        # Detect backend type for appropriate schema
        backend_type = getattr(self._backend, "backend_type", "sqlite")

        if backend_type == "postgresql":
            schema = self.SCHEMA_POSTGRES
        else:
            schema = self.SCHEMA_SQLITE

        self._backend.execute_write(schema)
        self._initialized = True
        logger.debug("Migration tracking table ensured")

    def _get_applied_by(self) -> str:
        """Get identifier for who is applying the migration."""
        hostname = socket.gethostname()
        pid = os.getpid()
        return f"{hostname}:{pid}"

    def is_applied(self, version: str) -> bool:
        """
        Check if a migration version has been applied.

        Args:
            version: Migration version to check.

        Returns:
            True if the migration has been applied.
        """
        self._ensure_table()
        result = self._backend.fetch_one(
            # table name interpolation, parameterized
            f"SELECT 1 FROM {self.TABLE_NAME} WHERE version = ?",
            (version,),
        )
        return result is not None

    def mark_applied(
        self,
        version: str,
        name: str,
        checksum: str | None = None,
        rollback_sql: str | None = None,
    ) -> None:
        """
        Record a migration as applied.

        Args:
            version: Unique migration version identifier.
            name: Human-readable migration name.
            checksum: SHA-256 hash of migration content.
            rollback_sql: SQL to reverse the migration.

        Raises:
            ValueError: If the version is already applied.
        """
        self._ensure_table()

        if self.is_applied(version):
            raise ValueError(f"Migration {version} is already applied")

        applied_by = self._get_applied_by()

        self._backend.execute_write(
            f"""
            INSERT INTO {self.TABLE_NAME}
                (version, name, applied_by, checksum, rollback_sql)
            VALUES (?, ?, ?, ?, ?)
            """,  # table name interpolation, parameterized
            (version, name, applied_by, checksum, rollback_sql),
        )
        logger.info("Marked migration %s (%s) as applied", version, name)

    def mark_rolled_back(self, version: str) -> None:
        """
        Remove a migration from the applied list (after rollback).

        Args:
            version: Migration version that was rolled back.

        Raises:
            ValueError: If the version was not applied.
        """
        self._ensure_table()

        if not self.is_applied(version):
            raise ValueError(f"Migration {version} is not applied")

        self._backend.execute_write(
            # table name interpolation, parameterized
            f"DELETE FROM {self.TABLE_NAME} WHERE version = ?",
            (version,),
        )
        logger.info("Marked migration %s as rolled back", version)

    def get_applied_versions(self) -> list[str]:
        """
        Get list of all applied migration versions in order.

        Returns:
            List of version strings, sorted by application time.
        """
        self._ensure_table()
        rows = self._backend.fetch_all(
            # table name interpolation, parameterized
            f"SELECT version FROM {self.TABLE_NAME} ORDER BY applied_at ASC"
        )
        return [row[0] for row in rows]

    def get_applied_migrations(self) -> list[AppliedMigration]:
        """
        Get detailed information about all applied migrations.

        Returns:
            List of AppliedMigration objects.
        """
        self._ensure_table()
        rows = self._backend.fetch_all(
            f"""
            SELECT version, name, applied_at, applied_by, checksum, rollback_sql
            FROM {self.TABLE_NAME}
            ORDER BY applied_at ASC
            """  # table name interpolation, parameterized
        )
        return [
            AppliedMigration(
                version=row[0],
                name=row[1],
                applied_at=row[2]
                if isinstance(row[2], datetime)
                else datetime.fromisoformat(str(row[2]))
                if row[2]
                else datetime.now(),
                applied_by=row[3],
                checksum=row[4],
                rollback_sql=row[5],
            )
            for row in rows
        ]

    def get_pending_migrations(self, available: list[str]) -> list[str]:
        """
        Get migrations that are available but not yet applied.

        Args:
            available: List of all available migration versions.

        Returns:
            List of pending migration versions, in the order provided.
        """
        self._ensure_table()
        applied = set(self.get_applied_versions())
        return [v for v in available if v not in applied]

    def get_migration(self, version: str) -> AppliedMigration | None:
        """
        Get details of a specific applied migration.

        Args:
            version: Migration version to retrieve.

        Returns:
            AppliedMigration if found, None otherwise.
        """
        self._ensure_table()
        row = self._backend.fetch_one(
            f"""
            SELECT version, name, applied_at, applied_by, checksum, rollback_sql
            FROM {self.TABLE_NAME}
            WHERE version = ?
            """,  # table name interpolation, parameterized
            (version,),
        )
        if not row:
            return None

        return AppliedMigration(
            version=row[0],
            name=row[1],
            applied_at=row[2]
            if isinstance(row[2], datetime)
            else datetime.fromisoformat(str(row[2]))
            if row[2]
            else datetime.now(),
            applied_by=row[3],
            checksum=row[4],
            rollback_sql=row[5],
        )

    def get_rollback_sql(self, version: str) -> str | None:
        """
        Get the rollback SQL for a specific migration.

        Args:
            version: Migration version.

        Returns:
            Rollback SQL if stored, None otherwise.
        """
        self._ensure_table()
        row = self._backend.fetch_one(
            # table name interpolation, parameterized
            f"SELECT rollback_sql FROM {self.TABLE_NAME} WHERE version = ?",
            (version,),
        )
        return row[0] if row else None

    def verify_checksum(self, version: str, expected_checksum: str) -> bool:
        """
        Verify that a migration's checksum matches the stored value.

        This detects if a migration file has been modified after being applied.

        Args:
            version: Migration version to verify.
            expected_checksum: Expected checksum from the migration file.

        Returns:
            True if checksums match (or no stored checksum), False if mismatch.
        """
        self._ensure_table()
        row = self._backend.fetch_one(
            # table name interpolation, parameterized
            f"SELECT checksum FROM {self.TABLE_NAME} WHERE version = ?",
            (version,),
        )
        if not row:
            return True  # Migration not applied, nothing to verify

        stored_checksum = row[0]
        if stored_checksum is None:
            return True  # No checksum stored, assume valid

        return stored_checksum == expected_checksum

    def get_checksum_mismatches(self, migrations: dict[str, str]) -> list[tuple[str, str, str]]:
        """
        Find all migrations with checksum mismatches.

        Args:
            migrations: Dict mapping version to current checksum.

        Returns:
            List of (version, stored_checksum, current_checksum) tuples for mismatches.
        """
        self._ensure_table()
        mismatches = []

        for version, current_checksum in migrations.items():
            row = self._backend.fetch_one(
                # table name interpolation, parameterized
                f"SELECT checksum FROM {self.TABLE_NAME} WHERE version = ?",
                (version,),
            )
            if row and row[0] and row[0] != current_checksum:
                mismatches.append((version, row[0], current_checksum))

        return mismatches

    def status(self) -> dict:
        """
        Get migration tracking status.

        Returns:
            Dict with applied count, latest version, and table existence.
        """
        self._ensure_table()
        applied = self.get_applied_versions()

        return {
            "table_exists": True,
            "applied_count": len(applied),
            "applied_versions": applied,
            "latest_version": applied[-1] if applied else None,
        }


def compute_migration_checksum(content: str) -> str:
    """
    Compute SHA-256 checksum of migration content.

    Args:
        content: Migration SQL or function source code.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


__all__ = [
    "MigrationTracker",
    "AppliedMigration",
    "compute_migration_checksum",
]
