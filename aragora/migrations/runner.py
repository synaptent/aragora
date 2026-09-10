"""
Migration runner for Aragora database schema management.

Provides a lightweight alternative to Alembic for managing schema changes
across SQLite and PostgreSQL backends.

Features:
- Advisory locking for PostgreSQL to prevent concurrent migration runs
- Version tracking with applied_by metadata
- Checksum verification to detect modified migration files
- Rollback SQL storage for disaster recovery
- Support for SQL and Python migration functions
- Multi-step rollback with safety validation and history tracking
- Dry-run mode for previewing rollback operations
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import logging
import os
import pkgutil
import socket
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable

from aragora.config import resolve_db_path
from aragora.storage.backends import (
    POSTGRESQL_AVAILABLE,
    DatabaseBackend,
    PostgreSQLBackend,
    SQLiteBackend,
)

logger = logging.getLogger(__name__)

DATABASE_ERRORS: tuple[type[Exception], ...] = (sqlite3.Error,)
try:
    from psycopg2 import Error as PostgreSQLError
except ImportError:
    pass
else:
    DATABASE_ERRORS += (PostgreSQLError,)

# Advisory lock ID for migration coordination (hash of 'aragora_migration')
MIGRATION_LOCK_ID = 2089872453


def compute_checksum(content: str) -> str:
    """Compute SHA-256 checksum of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class Migration:
    """
    Represents a database migration.

    Attributes:
        version: Unique version number (use timestamps like 20240115120000)
        name: Human-readable name
        up_sql: SQL to apply the migration (can be None if using up_fn)
        down_sql: SQL to rollback the migration (can be None if using down_fn)
        up_fn: Python function to apply migration (alternative to up_sql)
        down_fn: Python function to rollback migration (alternative to down_sql)
        checksum: Optional pre-computed checksum (computed automatically if not provided)
    """

    version: int
    name: str
    up_sql: str | None = None
    down_sql: str | None = None
    up_fn: Callable[[DatabaseBackend], None] | None = None
    down_fn: Callable[[DatabaseBackend], None] | None = None
    checksum: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.up_sql and not self.up_fn:
            raise ValueError(f"Migration {self.version} must have up_sql or up_fn")

    def compute_checksum(self) -> str:
        """
        Compute checksum based on migration content.

        For SQL migrations, uses the up_sql content.
        For function migrations, uses the function source code if available.
        """
        if self.checksum:
            return self.checksum

        content_parts = [str(self.version), self.name]

        if self.up_sql:
            content_parts.append(self.up_sql)
        elif self.up_fn:
            try:
                content_parts.append(inspect.getsource(self.up_fn))
            except (OSError, TypeError):
                # Fallback to function name if source unavailable
                content_parts.append(self.up_fn.__name__)

        if self.down_sql:
            content_parts.append(self.down_sql)
        elif self.down_fn:
            try:
                content_parts.append(inspect.getsource(self.down_fn))
            except (OSError, TypeError):
                content_parts.append(self.down_fn.__name__ if self.down_fn else "")

        return compute_checksum("\n".join(content_parts))


@dataclass
class RollbackValidation:
    """
    Result of a pre-rollback validation check.

    Attributes:
        safe: Whether it is safe to proceed with the rollback.
        warnings: Non-blocking issues that the caller should be aware of.
        errors: Blocking issues that prevent rollback.
        migrations_to_rollback: Versions that would be rolled back.
    """

    safe: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    migrations_to_rollback: list[int] = field(default_factory=list)


@dataclass
class RollbackRecord:
    """
    Record of a rollback operation stored in the rollback history table.

    Attributes:
        id: Auto-incremented record ID.
        version: The migration version that was rolled back.
        name: The migration name.
        rolled_back_at: ISO-8601 timestamp of when the rollback occurred.
        rolled_back_by: Identifier for the process that performed the rollback.
        reason: Optional human-readable reason for the rollback.
    """

    id: int
    version: int
    name: str
    rolled_back_at: str
    rolled_back_by: str
    reason: str | None = None


class MigrationRunner:
    """
    Manages and executes database migrations.

    Tracks applied migrations in a _migrations table and supports both
    SQLite and PostgreSQL backends.

    Features:
    - Version tracking with applied_by metadata
    - Checksum verification to detect modified migration files
    - Rollback SQL storage for disaster recovery
    - Advisory locking for PostgreSQL concurrent safety
    - Multi-step rollback with safety validation
    - Rollback history tracking for audit trails
    """

    MIGRATIONS_TABLE = "_aragora_migrations"
    ROLLBACK_HISTORY_TABLE = "_aragora_rollback_history"

    def __init__(
        self,
        backend: DatabaseBackend | None = None,
        db_path: str = "aragora.db",
        database_url: str | None = None,
        verify_checksums: bool = True,
    ):
        """
        Initialize the migration runner.

        Args:
            backend: Existing database backend to use.
            db_path: SQLite database path (if no backend provided).
            database_url: PostgreSQL URL (if no backend provided).
            verify_checksums: Whether to verify migration checksums on upgrade.
        """
        if backend:
            self._backend = backend
        else:
            # Create backend from parameters
            env_url = os.environ.get("DATABASE_URL") or os.environ.get("ARAGORA_DATABASE_URL")
            actual_url = database_url or env_url

            if actual_url:
                if not POSTGRESQL_AVAILABLE:
                    raise ImportError(
                        "psycopg2 required for PostgreSQL. Install with: pip install psycopg2-binary"
                    )
                self._backend = PostgreSQLBackend(actual_url)
            else:
                resolved_path = resolve_db_path(db_path)
                self._backend = SQLiteBackend(resolved_path)

        self._migrations: list[Migration] = []
        self._verify_checksums = verify_checksums
        self._init_migrations_table()
        self._init_rollback_history_table()

    def _init_migrations_table(self) -> None:
        """Create the migrations tracking table if it doesn't exist."""
        # Use BIGINT for PostgreSQL to support timestamp-based version numbers
        version_type = "BIGINT" if isinstance(self._backend, PostgreSQLBackend) else "INTEGER"
        sql = f"""
            CREATE TABLE IF NOT EXISTS {self.MIGRATIONS_TABLE} (
                version {version_type} PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                applied_by TEXT DEFAULT NULL,
                checksum TEXT DEFAULT NULL,
                rollback_sql TEXT DEFAULT NULL
            )
        """
        self._backend.execute_write(sql)
        # Ensure new columns exist (for upgrades from older schema)
        self._ensure_tracking_columns()

    def _ensure_tracking_columns(self) -> None:
        """Add checksum and rollback_sql columns if they don't exist (schema upgrade)."""
        # Check for checksum column
        try:
            self._backend.fetch_one(f"SELECT checksum FROM {self.MIGRATIONS_TABLE} LIMIT 1")  # noqa: S608 -- table name interpolation, parameterized
        except (sqlite3.Error, OSError, RuntimeError, ValueError) as e:
            # Column doesn't exist, add it
            logger.debug("checksum column check failed (will add): %s: %s", type(e).__name__, e)
            try:
                self._backend.execute_write(
                    f"ALTER TABLE {self.MIGRATIONS_TABLE} ADD COLUMN checksum TEXT DEFAULT NULL"
                )
                logger.info("Added checksum column to migrations table")
            except (sqlite3.Error, OSError, RuntimeError, ValueError) as e:
                logger.debug("Could not add checksum column (may already exist): %s", e)

        # Check for rollback_sql column
        try:
            self._backend.fetch_one(f"SELECT rollback_sql FROM {self.MIGRATIONS_TABLE} LIMIT 1")  # noqa: S608 -- table name interpolation, parameterized
        except (sqlite3.Error, OSError, RuntimeError, ValueError) as e:
            # Column doesn't exist, add it
            logger.debug("rollback_sql column check failed (will add): %s: %s", type(e).__name__, e)
            try:
                self._backend.execute_write(
                    f"ALTER TABLE {self.MIGRATIONS_TABLE} ADD COLUMN rollback_sql TEXT DEFAULT NULL"
                )
                logger.info("Added rollback_sql column to migrations table")
            except (sqlite3.Error, OSError, RuntimeError, ValueError) as e:
                logger.debug("Could not add rollback_sql column (may already exist): %s", e)

    def _init_rollback_history_table(self) -> None:
        """Create the rollback history table if it doesn't exist."""
        version_type = "BIGINT" if isinstance(self._backend, PostgreSQLBackend) else "INTEGER"
        id_type = (
            "SERIAL PRIMARY KEY"
            if isinstance(self._backend, PostgreSQLBackend)
            else "INTEGER PRIMARY KEY AUTOINCREMENT"
        )
        sql = f"""
            CREATE TABLE IF NOT EXISTS {self.ROLLBACK_HISTORY_TABLE} (
                id {id_type},
                version {version_type} NOT NULL,
                name TEXT NOT NULL,
                rolled_back_at TIMESTAMP NOT NULL,
                rolled_back_by TEXT NOT NULL,
                reason TEXT DEFAULT NULL
            )
        """
        try:
            self._backend.execute_write(sql)
        except DATABASE_ERRORS + (OSError, RuntimeError, ValueError) as e:
            # Non-fatal: rollback history is optional audit functionality
            logger.debug("Could not create rollback history table: %s", e)

    def _record_rollback(
        self,
        migration: Migration,
        reason: str | None = None,
    ) -> None:
        """
        Record a rollback operation in the history table.

        Args:
            migration: The migration that was rolled back.
            reason: Optional human-readable reason for the rollback.
        """
        try:
            self._backend.execute_write(
                f"INSERT INTO {self.ROLLBACK_HISTORY_TABLE} "  # noqa: S608 -- table name interpolation, parameterized
                "(version, name, rolled_back_at, rolled_back_by, reason) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    migration.version,
                    migration.name,
                    datetime.now(timezone.utc).isoformat(),
                    self._get_applied_by(),
                    reason,
                ),
            )
        except DATABASE_ERRORS + (OSError, RuntimeError, ValueError) as e:
            # Non-fatal: don't let history tracking failures block rollback
            logger.warning("Failed to record rollback history for v%s: %s", migration.version, e)

    def _acquire_migration_lock(self, timeout_seconds: float = 30.0) -> bool:
        """
        Acquire an advisory lock for running migrations (PostgreSQL only).

        Uses pg_try_advisory_lock to prevent concurrent migration runs across
        multiple pods/instances. SQLite uses file-level locking inherently.

        Args:
            timeout_seconds: Maximum time to wait for lock acquisition.

        Returns:
            True if lock acquired.

        Raises:
            RuntimeError: If lock cannot be acquired within timeout.
        """
        if not isinstance(self._backend, PostgreSQLBackend):
            # SQLite has inherent file locking, no advisory lock needed
            return True

        start_time = time.time()
        poll_interval = 0.5  # seconds between retry attempts

        while True:
            # Try to acquire advisory lock (non-blocking)
            result = self._backend.fetch_one(f"SELECT pg_try_advisory_lock({MIGRATION_LOCK_ID})")

            if result and result[0]:
                logger.info("Acquired migration advisory lock")
                return True

            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                logger.error(
                    f"Failed to acquire migration lock after {elapsed:.1f}s. "
                    "Another migration may be in progress."
                )
                raise RuntimeError(
                    f"Migration lock acquisition timeout after {timeout_seconds}s. "
                    "Ensure no other migration is running and try again."
                )

            logger.debug(
                "Migration lock held by another process, retrying in %ss...", poll_interval
            )
            time.sleep(poll_interval)

    def _release_migration_lock(self) -> None:
        """
        Release the advisory lock for migrations (PostgreSQL only).

        Safe to call even if lock was not acquired (no-op for SQLite).
        """
        if not isinstance(self._backend, PostgreSQLBackend):
            return

        try:
            self._backend.execute_write(f"SELECT pg_advisory_unlock({MIGRATION_LOCK_ID})")
            logger.info("Released migration advisory lock")
        except (RuntimeError, OSError) as e:
            # Log but don't raise - lock will be released on connection close anyway
            logger.warning("Failed to release migration lock: %s", e)

    def _get_applied_by(self) -> str:
        """Get identifier for who applied the migration."""
        hostname = socket.gethostname()
        pid = os.getpid()
        return f"{hostname}:{pid}"

    def register(self, migration: Migration) -> None:
        """
        Register a migration.

        Args:
            migration: Migration to register.
        """
        # Insert in version order
        self._migrations.append(migration)
        self._migrations.sort(key=lambda m: m.version)

    def get_applied_versions(self) -> set[int]:
        """Get set of applied migration versions."""
        rows = self._backend.fetch_all(f"SELECT version FROM {self.MIGRATIONS_TABLE}")  # noqa: S608 -- table name interpolation, parameterized
        return {row[0] for row in rows}

    def get_pending_migrations(self) -> list[Migration]:
        """Get list of migrations that haven't been applied."""
        applied = self.get_applied_versions()
        return [m for m in self._migrations if m.version not in applied]

    def verify_checksums(self) -> list[tuple[int, str, str]]:
        """
        Verify checksums of all applied migrations.

        Returns:
            List of (version, stored_checksum, current_checksum) for mismatches.
        """
        mismatches = []
        applied_versions = self.get_applied_versions()

        for migration in self._migrations:
            if migration.version in applied_versions:
                current_checksum = migration.compute_checksum()
                row = self._backend.fetch_one(
                    f"SELECT checksum FROM {self.MIGRATIONS_TABLE} WHERE version = ?",  # noqa: S608 -- table name interpolation, parameterized
                    (migration.version,),
                )
                if row and row[0] and row[0] != current_checksum:
                    mismatches.append((migration.version, row[0], current_checksum))

        return mismatches

    def get_stored_rollback_sql(self, version: int) -> str | None:
        """
        Get stored rollback SQL for a migration version.

        This can be used for disaster recovery when the migration file
        is no longer available.

        Args:
            version: Migration version.

        Returns:
            Rollback SQL if stored, None otherwise.
        """
        row = self._backend.fetch_one(
            f"SELECT rollback_sql FROM {self.MIGRATIONS_TABLE} WHERE version = ?",  # noqa: S608 -- table name interpolation, parameterized
            (version,),
        )
        return row[0] if row else None

    def upgrade(
        self,
        target_version: int | None = None,
        lock_timeout: float = 30.0,
        dry_run: bool = False,
    ) -> list[Migration]:
        """
        Apply pending migrations up to target version.

        Acquires an advisory lock (PostgreSQL) to prevent concurrent migrations
        across multiple pods/instances.

        Args:
            target_version: Maximum version to apply (None = all pending).
            lock_timeout: Maximum seconds to wait for migration lock.
            dry_run: If True, only show what would be applied without executing.

        Returns:
            List of applied (or would-be-applied) migrations.

        Raises:
            RuntimeError: If migration lock cannot be acquired.
            ValueError: If checksum verification fails (when verify_checksums=True).
        """
        applied: list[Migration] = []
        pending = self.get_pending_migrations()

        if not pending:
            return applied

        # Verify checksums of already-applied migrations
        if self._verify_checksums:
            mismatches = self.verify_checksums()
            if mismatches:
                mismatch_details = ", ".join(f"v{v}" for v, _, _ in mismatches)
                raise ValueError(
                    f"Migration checksum mismatch detected for: {mismatch_details}. "
                    "Migration files may have been modified after being applied. "
                    "This could cause inconsistencies. Review changes and consider "
                    "creating new migrations instead of modifying existing ones."
                )

        if dry_run:
            for migration in pending:
                if target_version and migration.version > target_version:
                    break
                applied.append(migration)
                logger.info(
                    "[DRY RUN] Would apply migration %s: %s", migration.version, migration.name
                )
            return applied

        # Acquire lock before running migrations
        self._acquire_migration_lock(timeout_seconds=lock_timeout)

        try:
            applied_by = self._get_applied_by()

            for migration in pending:
                if target_version and migration.version > target_version:
                    break

                logger.info("Applying migration %s: %s", migration.version, migration.name)

                try:
                    if migration.up_fn:
                        migration.up_fn(self._backend)
                    elif migration.up_sql:
                        # Split by semicolon and execute each statement
                        for stmt in migration.up_sql.split(";"):
                            stmt = stmt.strip()
                            if stmt:
                                self._backend.execute_write(stmt)

                    # Compute checksum and store rollback SQL
                    checksum = migration.compute_checksum()
                    rollback_sql = migration.down_sql

                    # Record migration with full metadata
                    self._backend.execute_write(
                        f"INSERT INTO {self.MIGRATIONS_TABLE} "  # noqa: S608 -- table name interpolation, parameterized
                        "(version, name, applied_by, checksum, rollback_sql) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (migration.version, migration.name, applied_by, checksum, rollback_sql),
                    )
                    applied.append(migration)
                    logger.info("Applied migration %s", migration.version)

                except DATABASE_ERRORS + (RuntimeError, OSError, ValueError) as e:
                    logger.error("Failed to apply migration %s: %s", migration.version, e)
                    raise
        finally:
            # Always release lock
            self._release_migration_lock()

        return applied

    def downgrade(
        self,
        target_version: int | None = None,
        lock_timeout: float = 30.0,
        use_stored_rollback: bool = False,
        dry_run: bool = False,
        reason: str | None = None,
    ) -> list[Migration]:
        """
        Rollback migrations down to target version.

        Acquires an advisory lock (PostgreSQL) to prevent concurrent migrations
        across multiple pods/instances.

        Args:
            target_version: Minimum version to keep (None = rollback one).
            lock_timeout: Maximum seconds to wait for migration lock.
            use_stored_rollback: If True, use stored rollback_sql from database
                instead of the migration's down_sql (useful for disaster recovery
                when migration files may have been modified).
            dry_run: If True, only show what would be rolled back without executing.
            reason: Optional human-readable reason for the rollback (stored in
                rollback history for audit purposes).

        Returns:
            List of rolled back (or would-be-rolled-back in dry_run mode) migrations.

        Raises:
            RuntimeError: If migration lock cannot be acquired.
        """
        rolled_back: list[Migration] = []
        applied = self.get_applied_versions()

        # Get applied migrations in reverse order
        to_rollback = [m for m in reversed(self._migrations) if m.version in applied]

        if not to_rollback:
            logger.info("No migrations to rollback")
            return rolled_back

        # Filter to migrations above target_version, and limit to one if no target
        candidates: list[Migration] = []
        for migration in to_rollback:
            if target_version is not None and migration.version <= target_version:
                break
            candidates.append(migration)
            if target_version is None:
                break  # Only rollback one if no target specified

        if dry_run:
            for migration in candidates:
                rollback_sql = migration.down_sql
                has_down_fn = migration.down_fn is not None
                has_stored = self.get_stored_rollback_sql(migration.version) is not None

                if not rollback_sql and not has_down_fn and not has_stored:
                    logger.info(
                        "[DRY RUN] Would SKIP migration %s: %s (no rollback defined)",
                        migration.version,
                        migration.name,
                    )
                    break
                logger.info(
                    "[DRY RUN] Would rollback migration %s: %s", migration.version, migration.name
                )
                rolled_back.append(migration)
            return rolled_back

        # Acquire lock before rolling back
        self._acquire_migration_lock(timeout_seconds=lock_timeout)

        try:
            for migration in candidates:
                # Determine which rollback SQL to use
                rollback_sql = None
                if use_stored_rollback:
                    rollback_sql = self.get_stored_rollback_sql(migration.version)
                    if rollback_sql:
                        logger.debug(
                            "Using stored rollback SQL for migration %s", migration.version
                        )
                if not rollback_sql:
                    rollback_sql = migration.down_sql

                if not rollback_sql and not migration.down_fn:
                    logger.warning("Migration %s has no rollback", migration.version)
                    break

                logger.info("Rolling back migration %s: %s", migration.version, migration.name)

                try:
                    if migration.down_fn and not use_stored_rollback:
                        migration.down_fn(self._backend)
                    elif rollback_sql:
                        for stmt in rollback_sql.split(";"):
                            stmt = stmt.strip()
                            if stmt:
                                self._backend.execute_write(stmt)
                    else:
                        logger.warning("No rollback available for migration %s", migration.version)
                        break

                    # Remove migration record
                    self._backend.execute_write(
                        f"DELETE FROM {self.MIGRATIONS_TABLE} WHERE version = ?",  # noqa: S608 -- table name interpolation, parameterized
                        (migration.version,),
                    )
                    # Record in rollback history
                    self._record_rollback(migration, reason=reason)
                    rolled_back.append(migration)
                    logger.info("Rolled back migration %s", migration.version)

                except DATABASE_ERRORS + (RuntimeError, OSError, ValueError) as e:
                    logger.error("Failed to rollback migration %s: %s", migration.version, e)
                    raise
        finally:
            # Always release lock
            self._release_migration_lock()

        return rolled_back

    def rollback_steps(
        self,
        steps: int = 1,
        lock_timeout: float = 30.0,
        use_stored_rollback: bool = False,
        dry_run: bool = False,
        reason: str | None = None,
    ) -> list[Migration]:
        """
        Rollback a specific number of migrations.

        This is a convenience method that rolls back the N most recently
        applied migrations. For rolling back to a specific version, use
        ``downgrade(target_version=...)``.

        Args:
            steps: Number of migrations to rollback (must be >= 1).
            lock_timeout: Maximum seconds to wait for migration lock.
            use_stored_rollback: If True, use stored rollback_sql from database
                instead of the migration's down_sql.
            dry_run: If True, only show what would be rolled back without executing.
            reason: Optional human-readable reason for the rollback.

        Returns:
            List of rolled back (or would-be-rolled-back) migrations.

        Raises:
            ValueError: If steps < 1.
            RuntimeError: If migration lock cannot be acquired.
        """
        if steps < 1:
            raise ValueError(f"steps must be >= 1, got {steps}")

        applied = self.get_applied_versions()
        if not applied:
            logger.info("No migrations to rollback")
            return []

        # Get applied migrations in reverse order
        to_rollback = [m for m in reversed(self._migrations) if m.version in applied]
        to_rollback = to_rollback[:steps]

        if not to_rollback:
            logger.info("No migrations to rollback")
            return []

        # Compute the target version: the version just below the lowest we want to rollback
        lowest_rollback = to_rollback[-1].version
        remaining_applied = sorted(v for v in applied if v < lowest_rollback)
        target_version = remaining_applied[-1] if remaining_applied else 0

        return self.downgrade(
            target_version=target_version,
            lock_timeout=lock_timeout,
            use_stored_rollback=use_stored_rollback,
            dry_run=dry_run,
            reason=reason,
        )

    def validate_rollback(
        self,
        target_version: int | None = None,
        steps: int | None = None,
    ) -> RollbackValidation:
        """
        Validate whether a rollback operation can be performed safely.

        Performs pre-flight checks without modifying any data. Use this before
        calling ``downgrade()`` or ``rollback_steps()`` to identify potential
        issues.

        Args:
            target_version: Target version to validate rollback to.
            steps: Number of steps to validate rollback for. Ignored if
                target_version is also provided.

        Returns:
            RollbackValidation with safety assessment, warnings, and errors.
        """
        warnings: list[str] = []
        errors: list[str] = []
        versions_to_rollback: list[int] = []

        applied = self.get_applied_versions()

        if not applied:
            return RollbackValidation(
                safe=False,
                errors=["No migrations have been applied"],
                migrations_to_rollback=[],
            )

        # Determine which migrations would be rolled back
        to_rollback = [m for m in reversed(self._migrations) if m.version in applied]

        if target_version is not None:
            if target_version < 0:
                errors.append(f"target_version must be >= 0, got {target_version}")
                return RollbackValidation(
                    safe=False,
                    errors=errors,
                    migrations_to_rollback=[],
                )

            max_applied = max(applied)
            if target_version >= max_applied:
                errors.append(
                    f"target_version ({target_version}) must be less than "
                    f"current version ({max_applied})"
                )
                return RollbackValidation(
                    safe=False,
                    errors=errors,
                    migrations_to_rollback=[],
                )

            candidates = [m for m in to_rollback if m.version > target_version]
        elif steps is not None:
            if steps < 1:
                errors.append(f"steps must be >= 1, got {steps}")
                return RollbackValidation(
                    safe=False,
                    errors=errors,
                    migrations_to_rollback=[],
                )
            candidates = to_rollback[:steps]
        else:
            # Default: validate rolling back one
            candidates = to_rollback[:1]

        # Check each candidate migration
        for migration in candidates:
            versions_to_rollback.append(migration.version)

            has_down_sql = migration.down_sql is not None
            has_down_fn = migration.down_fn is not None
            has_stored = self.get_stored_rollback_sql(migration.version) is not None

            if not has_down_sql and not has_down_fn and not has_stored:
                errors.append(
                    f"Migration {migration.version} ({migration.name}) has no "
                    f"rollback defined (no down_sql, down_fn, or stored rollback SQL)"
                )
            elif not has_down_sql and not has_down_fn and has_stored:
                warnings.append(
                    f"Migration {migration.version} ({migration.name}) only has "
                    f"stored rollback SQL; use use_stored_rollback=True"
                )

        # Check for large rollback scope
        if len(candidates) > 5:
            warnings.append(
                f"Rolling back {len(candidates)} migrations is a large operation; "
                f"consider creating a backup first"
            )

        is_safe = len(errors) == 0
        return RollbackValidation(
            safe=is_safe,
            warnings=warnings,
            errors=errors,
            migrations_to_rollback=versions_to_rollback,
        )

    def get_rollback_history(self) -> list[RollbackRecord]:
        """
        Get the history of all rollback operations.

        Returns:
            List of RollbackRecord objects ordered by most recent first.
        """
        try:
            rows = self._backend.fetch_all(
                f"SELECT id, version, name, rolled_back_at, rolled_back_by, reason "  # noqa: S608 -- internal query construction
                f"FROM {self.ROLLBACK_HISTORY_TABLE} ORDER BY id DESC"
            )
            return [
                RollbackRecord(
                    id=row[0],
                    version=row[1],
                    name=row[2],
                    rolled_back_at=row[3],
                    rolled_back_by=row[4],
                    reason=row[5],
                )
                for row in rows
            ]
        except (sqlite3.Error, OSError, RuntimeError, ValueError) as e:
            logger.debug("Could not read rollback history: %s", e)
            return []

    def status(self, include_checksums: bool = False) -> dict:
        """
        Get migration status.

        Args:
            include_checksums: If True, include checksum verification results.

        Returns:
            Dict with applied, pending, latest version info, and optionally checksums.
        """
        applied = self.get_applied_versions()
        pending = self.get_pending_migrations()

        status_dict = {
            "applied_count": len(applied),
            "pending_count": len(pending),
            "applied_versions": sorted(applied),
            "pending_versions": [m.version for m in pending],
            "latest_applied": max(applied) if applied else None,
            "latest_available": self._migrations[-1].version if self._migrations else None,
        }

        if include_checksums:
            mismatches = self.verify_checksums()
            status_dict["checksum_valid"] = len(mismatches) == 0
            status_dict["checksum_mismatches"] = [
                {"version": v, "stored": stored, "current": current}
                for v, stored, current in mismatches
            ]

        return status_dict

    def close(self) -> None:
        """Close the database connection."""
        self._backend.close()


# Global runner instance with thread-safe initialization
_runner: MigrationRunner | None = None
_runner_lock = threading.Lock()


def get_migration_runner(
    db_path: str = "aragora.db",
    database_url: str | None = None,
) -> MigrationRunner:
    """
    Get or create the global migration runner (thread-safe).

    Automatically loads migrations from the migrations package.
    """
    global _runner
    if _runner is None:
        with _runner_lock:
            # Double-checked locking pattern
            if _runner is None:
                _runner = MigrationRunner(db_path=db_path, database_url=database_url)
                _load_migrations(_runner)
    return _runner


def _load_migrations(runner: MigrationRunner) -> None:
    """Load all migration modules from the versions package."""
    try:
        from aragora.migrations import versions

        versions_path = Path(versions.__file__).parent

        for _, name, _ in pkgutil.iter_modules([str(versions_path)]):
            if name.startswith("v"):
                module = importlib.import_module(f"aragora.migrations.versions.{name}")
                if hasattr(module, "migration"):
                    runner.register(module.migration)
                    logger.debug("Loaded migration: %s", name)
    except ImportError:
        logger.debug("No migrations.versions package found")


def apply_migrations(
    db_path: str = "aragora.db",
    database_url: str | None = None,
    target_version: int | None = None,
) -> list[Migration]:
    """
    Apply all pending migrations.

    Args:
        db_path: SQLite database path.
        database_url: PostgreSQL URL.
        target_version: Maximum version to apply.

    Returns:
        List of applied migrations.
    """
    runner = get_migration_runner(db_path, database_url)
    return runner.upgrade(target_version)


def rollback_migration(
    db_path: str = "aragora.db",
    database_url: str | None = None,
    target_version: int | None = None,
) -> list[Migration]:
    """
    Rollback the last migration.

    Args:
        db_path: SQLite database path.
        database_url: PostgreSQL URL.
        target_version: Minimum version to keep.

    Returns:
        List of rolled back migrations.
    """
    runner = get_migration_runner(db_path, database_url)
    return runner.downgrade(target_version)


def get_migration_status(
    db_path: str = "aragora.db",
    database_url: str | None = None,
) -> dict:
    """
    Get migration status.

    Returns:
        Dict with applied/pending counts and versions.
    """
    runner = get_migration_runner(db_path, database_url)
    return runner.status()


def reset_runner() -> None:
    """Reset the global runner (for testing)."""
    global _runner
    if _runner:
        _runner.close()
        _runner = None
