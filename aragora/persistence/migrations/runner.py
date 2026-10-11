"""
Database Migration Runner for Aragora.

Provides CLI tools for running database migrations in production with
backup support, checksum verification, and multi-step rollback.

Usage:
    # Check migration status
    python -m aragora.persistence.migrations.runner --status

    # Dry-run migrations (show what would be done)
    python -m aragora.persistence.migrations.runner --dry-run

    # Run migrations (creates automatic backup first)
    python -m aragora.persistence.migrations.runner --migrate

    # Run migrations without backup (not recommended)
    python -m aragora.persistence.migrations.runner --migrate --no-backup

    # Create a new migration
    python -m aragora.persistence.migrations.runner --create "Add user lockout fields" --db users

    # Rollback last migration (not recommended in production)
    python -m aragora.persistence.migrations.runner --rollback --db users

    # Rollback to a specific version (not recommended in production)
    python -m aragora.persistence.migrations.runner --rollback-to 5 --db users

    # Dry-run rollback to see what would happen
    python -m aragora.persistence.migrations.runner --rollback-to 5 --db users --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import logging
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable

from aragora.storage.schema import SchemaManager, get_wal_connection

logger = logging.getLogger(__name__)

# Default database paths (relative to ARAGORA_DATA_DIR or absolute)
DEFAULT_DB_PATHS = {
    "elo": "aragora_elo.db",
    "memory": "aragora_memory.db",
    "users": "aragora_users.db",
    "positions": "aragora_positions.db",
    "replay": "aragora_replay.db",
    "tokens": "aragora_tokens.db",
}


@dataclass
class MigrationFile:
    """Represents a migration file."""

    version: int
    name: str
    path: Path
    description: str = ""
    checksum: str = ""

    @property
    def module_name(self) -> str:
        """Get the Python module name for this migration."""
        return self.path.stem

    def compute_checksum(self) -> str:
        """Compute SHA-256 checksum of the migration file."""
        if not self.path.exists():
            return ""
        content = self.path.read_bytes()
        return hashlib.sha256(content).hexdigest()[:16]


@dataclass
class AppliedMigration:
    """Record of an applied migration with metadata."""

    version: int
    name: str
    checksum: str
    applied_at: str


@dataclass
class MigrationStatus:
    """Status of a database's migrations."""

    db_name: str
    db_path: str
    current_version: int
    target_version: int
    pending_count: int
    applied_migrations: list[int]
    pending_migrations: list[int]
    # Enhanced tracking
    applied_details: list[AppliedMigration] = field(default_factory=list)
    checksum_mismatches: list[int] = field(default_factory=list)


class MigrationRunner:
    """
    Runs database migrations for Aragora.

    Discovers migration files and applies them in order.
    """

    MIGRATIONS_DIR = Path(__file__).parent

    def __init__(
        self,
        nomic_dir: Path | None = None,
        db_paths: dict[str, str] | None = None,
        backup_before_migrate: bool = True,
        backup_dir: Path | None = None,
    ):
        """
        Initialize the migration runner.

        Args:
            nomic_dir: Base directory for database files
            db_paths: Override default database paths
            backup_before_migrate: Create backup before migrations (default: True)
            backup_dir: Directory for backups (default: nomic_dir/backups)
        """
        self.nomic_dir = nomic_dir or self._get_nomic_dir()
        self.db_paths = db_paths or DEFAULT_DB_PATHS
        self.backup_before_migrate = backup_before_migrate
        self.backup_dir = backup_dir or (self.nomic_dir / "migration_backups")
        self._discovered_migrations: dict[str, list[MigrationFile]] = {}
        self._backup_manager = None  # Lazy-loaded

    @staticmethod
    def _get_nomic_dir() -> Path:
        """Get the data directory from environment or default."""
        env_dir = (
            os.environ.get("ARAGORA_DATA_DIR")
            or os.environ.get("ARAGORA_NOMIC_DIR")
            or os.environ.get("NOMIC_DIR")
        )
        if env_dir:
            return Path(env_dir)

        # Default to ARAGORA_DATA_DIR
        from aragora.persistence.db_config import get_nomic_dir

        return get_nomic_dir()

    def _get_backup_manager(self):
        """Get or create the backup manager (lazy-loaded)."""
        if self._backup_manager is None:
            try:
                from aragora.backup.manager import BackupManager

                self.backup_dir.mkdir(parents=True, exist_ok=True)
                self._backup_manager = BackupManager(
                    backup_dir=self.backup_dir,
                    compression=True,
                    verify_after_backup=True,
                )
            except ImportError:
                logger.warning("BackupManager not available, backups disabled")
                self._backup_manager = False  # Mark as unavailable
        return self._backup_manager if self._backup_manager else None

    def create_pre_migration_backup(self, db_path: Path, db_name: str) -> str | None:
        """
        Create a backup before running migrations.

        Args:
            db_path: Path to the database file
            db_name: Name of the database

        Returns:
            Backup ID if successful, None otherwise
        """
        if not self.backup_before_migrate:
            return None

        if not db_path.exists():
            logger.debug("Database %s does not exist, skipping backup", db_path)
            return None

        manager = self._get_backup_manager()
        if not manager:
            logger.warning("No backup manager available, proceeding without backup")
            return None

        try:
            logger.info("[%s] Creating pre-migration backup...", db_name)
            from aragora.backup.manager import BackupType

            backup = manager.create_backup(
                db_path,
                backup_type=BackupType.FULL,
                metadata={"reason": "pre_migration", "db_name": db_name},
            )
            logger.info("[%s] Backup created: %s", db_name, backup.id)
            return backup.id
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("[%s] Failed to create backup: %s", db_name, e)
            return None

    def restore_from_backup(self, backup_id: str, db_path: Path) -> bool:
        """
        Restore a database from a backup.

        Args:
            backup_id: ID of the backup to restore
            db_path: Path where to restore the database

        Returns:
            True if successful, False otherwise
        """
        manager = self._get_backup_manager()
        if not manager:
            logger.error("No backup manager available for restore")
            return False

        try:
            manager.restore_backup(backup_id, str(db_path))
            logger.info("Restored database from backup %s", backup_id)
            return True
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Failed to restore from backup %s: %s", backup_id, e)
            return False

    def discover_migrations(self, db_name: str) -> list[MigrationFile]:
        """
        Discover migration files for a specific database.

        Migration files should be named like:
        - 001_initial.py
        - 002_add_lockout.py
        - 003_add_analytics.py

        Args:
            db_name: Name of the database module (e.g., "elo", "users")

        Returns:
            List of MigrationFile objects sorted by version
        """
        if db_name in self._discovered_migrations:
            return self._discovered_migrations[db_name]

        migrations = []
        migrations_path = self.MIGRATIONS_DIR / db_name

        if not migrations_path.exists():
            logger.debug("No migrations directory for %s", db_name)
            return []

        # Pattern: NNN_description.py
        pattern = re.compile(r"^(\d{3})_(.+)\.py$")

        for file_path in sorted(migrations_path.glob("*.py")):
            if file_path.name.startswith("_"):
                continue

            match = pattern.match(file_path.name)
            if match:
                version = int(match.group(1))
                name = match.group(2)
                migration = MigrationFile(
                    version=version,
                    name=name,
                    path=file_path,
                    description=name.replace("_", " ").title(),
                )
                migration.checksum = migration.compute_checksum()
                migrations.append(migration)

        # Sort by version
        migrations.sort(key=lambda m: m.version)
        self._discovered_migrations[db_name] = migrations
        return migrations

    def get_db_path(self, db_name: str) -> Path:
        """Get the full path to a database file."""
        db_file = self.db_paths.get(db_name, f"aragora_{db_name}.db")
        return self.nomic_dir / db_file

    def get_status(self, db_name: str) -> MigrationStatus | None:
        """
        Get migration status for a database.

        Args:
            db_name: Name of the database module

        Returns:
            MigrationStatus or None if database doesn't exist
        """
        db_path = self.get_db_path(db_name)
        if not db_path.exists():
            return None

        migrations = self.discover_migrations(db_name)
        target_version = max((m.version for m in migrations), default=0)

        conn = get_wal_connection(db_path)
        try:
            manager = SchemaManager(conn, db_name, current_version=target_version)
            current_version = manager.get_version()

            applied = [m.version for m in migrations if m.version <= current_version]
            pending = [m.version for m in migrations if m.version > current_version]

            # Populate applied details and checksum mismatches from tracking table
            applied_details = []
            checksum_mismatches = []
            applied_checksums = self._get_applied_checksums(conn)
            applied_details_map = self._get_applied_details(conn)

            for m in migrations:
                if m.version <= current_version:
                    detail = applied_details_map.get(m.version)
                    if detail:
                        applied_details.append(detail)
                    else:
                        # Migration was applied but not tracked (pre-tracking)
                        applied_details.append(
                            AppliedMigration(
                                version=m.version,
                                name=m.name,
                                checksum=m.checksum,
                                applied_at="unknown",
                            )
                        )
                    # Check for checksum mismatch
                    if (
                        m.version in applied_checksums
                        and applied_checksums[m.version] != m.checksum
                    ):
                        checksum_mismatches.append(m.version)

            return MigrationStatus(
                db_name=db_name,
                db_path=str(db_path),
                current_version=current_version,
                target_version=target_version,
                pending_count=len(pending),
                applied_migrations=applied,
                pending_migrations=pending,
                applied_details=applied_details,
                checksum_mismatches=checksum_mismatches,
            )
        finally:
            conn.close()

    def get_all_status(self) -> dict[str, MigrationStatus | None]:
        """Get migration status for all known databases."""
        status = {}
        for db_name in self.db_paths:
            status[db_name] = self.get_status(db_name)
        return status

    def migrate(
        self,
        db_name: str,
        dry_run: bool = False,
        target_version: int | None = None,
    ) -> dict:
        """
        Run migrations for a database.

        Args:
            db_name: Name of the database module
            dry_run: If True, show what would be done without executing
            target_version: Migrate to specific version (None = latest)

        Returns:
            Dict with migration results
        """
        db_path = self.get_db_path(db_name)
        migrations = self.discover_migrations(db_name)

        if not migrations:
            return {
                "db_name": db_name,
                "status": "no_migrations",
                "message": f"No migrations found for {db_name}",
            }

        # Ensure directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)

        max_version = max(m.version for m in migrations)
        target = target_version if target_version is not None else max_version

        if dry_run:
            return self._dry_run_migrate(db_name, db_path, migrations, target)

        return self._execute_migrate(db_name, db_path, migrations, target)

    def _dry_run_migrate(
        self,
        db_name: str,
        db_path: Path,
        migrations: list[MigrationFile],
        target_version: int,
    ) -> dict:
        """Show what migrations would be run without executing."""

        def check_migrations(pending: list[MigrationFile]) -> tuple[list[dict], list[dict]]:
            """Check pending migrations for issues, returns (migration_info, warnings)."""
            migration_info = []
            warnings = []
            for m in pending:
                info = {"version": m.version, "name": m.name, "description": m.description}
                # Check if migration is empty
                try:
                    module = self._load_migration_module(m)
                    if hasattr(module, "upgrade") and self._is_empty_migration(module.upgrade):
                        info["warning"] = "Empty migration (only has pass statement)"
                        warnings.append(
                            {
                                "version": m.version,
                                "message": f"Migration {m.version} ({m.path.name}) is empty and will fail",
                            }
                        )
                except (ImportError, ModuleNotFoundError, OSError) as e:
                    # Continue if we can't load/inspect the migration module
                    logger.warning("Could not inspect migration %s: %s", m.version, e)
                    pass
                migration_info.append(info)
            return migration_info, warnings

        if not db_path.exists():
            pending = [m for m in migrations if m.version <= target_version]
            migration_info, warnings = check_migrations(pending)
            result = {
                "db_name": db_name,
                "status": "dry_run",
                "current_version": 0,
                "target_version": target_version,
                "would_create_db": True,
                "pending_migrations": migration_info,
            }
            if warnings:
                result["warnings"] = warnings
            return result

        conn = get_wal_connection(db_path)
        try:
            manager = SchemaManager(conn, db_name, current_version=target_version)
            current = manager.get_version()

            pending = [m for m in migrations if m.version > current and m.version <= target_version]
            migration_info, warnings = check_migrations(pending)

            result = {
                "db_name": db_name,
                "status": "dry_run",
                "current_version": current,
                "target_version": target_version,
                "would_create_db": False,
                "pending_migrations": migration_info,
            }
            if warnings:
                result["warnings"] = warnings
            return result
        finally:
            conn.close()

    def _ensure_migration_tracking(self, conn, db_name: str) -> None:
        """Ensure the migration tracking table exists with checksum support."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _migration_checksums (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
        """)
        conn.commit()

    def _get_applied_checksums(self, conn) -> dict[int, str]:
        """Get checksums of previously applied migrations."""
        try:
            cursor = conn.execute("SELECT version, checksum FROM _migration_checksums")
            return {row[0]: row[1] for row in cursor.fetchall()}
        except (OSError, RuntimeError, ValueError, sqlite3.OperationalError) as e:
            logger.debug("Failed to get applied checksums: %s: %s", type(e).__name__, e)
            return {}

    def _get_applied_details(self, conn) -> dict[int, AppliedMigration]:
        """Get full details of previously applied migrations."""
        try:
            cursor = conn.execute(
                "SELECT version, name, checksum, applied_at FROM _migration_checksums ORDER BY version"
            )
            return {
                row[0]: AppliedMigration(
                    version=row[0],
                    name=row[1],
                    checksum=row[2],
                    applied_at=row[3],
                )
                for row in cursor.fetchall()
            }
        except (OSError, RuntimeError, ValueError, sqlite3.OperationalError) as e:
            logger.debug("Failed to get applied migration details: %s: %s", type(e).__name__, e)
            return {}

    def get_migration_history(self, db_name: str) -> list[AppliedMigration]:
        """
        Get full migration history for a database.

        Returns applied migrations with timestamps and checksums,
        ordered by version ascending.

        Args:
            db_name: Name of the database module

        Returns:
            List of AppliedMigration records, empty if database doesn't exist
        """
        db_path = self.get_db_path(db_name)
        if not db_path.exists():
            return []

        conn = get_wal_connection(db_path)
        try:
            details = self._get_applied_details(conn)
            return sorted(details.values(), key=lambda d: d.version)
        finally:
            conn.close()

    def _record_migration(self, conn, migration: MigrationFile) -> None:
        """Record a migration with its checksum."""
        conn.execute(
            """
            INSERT OR REPLACE INTO _migration_checksums (version, name, checksum, applied_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                migration.version,
                migration.name,
                migration.checksum,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def _execute_migrate(
        self,
        db_name: str,
        db_path: Path,
        migrations: list[MigrationFile],
        target_version: int,
    ) -> dict:
        """Execute migrations."""
        # Create backup before migration
        backup_id = self.create_pre_migration_backup(db_path, db_name)

        conn = get_wal_connection(db_path)
        applied = []
        errors = []

        try:
            # Ensure tracking table exists
            self._ensure_migration_tracking(conn, db_name)

            manager = SchemaManager(conn, db_name, current_version=target_version)
            current = manager.get_version()

            # Check for checksum mismatches on already-applied migrations
            applied_checksums = self._get_applied_checksums(conn)
            checksum_warnings = []
            for m in migrations:
                if m.version <= current and m.version in applied_checksums:
                    if applied_checksums[m.version] != m.checksum:
                        checksum_warnings.append(
                            {
                                "version": m.version,
                                "expected": applied_checksums[m.version],
                                "actual": m.checksum,
                            }
                        )

            if checksum_warnings:
                logger.warning(
                    "[%s] Checksum mismatch for %s migration(s) - files may have been modified after application",
                    db_name,
                    len(checksum_warnings),
                )

            pending = [m for m in migrations if m.version > current and m.version <= target_version]

            if not pending:
                result = {
                    "db_name": db_name,
                    "status": "up_to_date",
                    "current_version": current,
                    "message": f"{db_name} is already at version {current}",
                }
                if checksum_warnings:
                    result["checksum_warnings"] = checksum_warnings
                return result

            for migration in pending:
                logger.info(
                    "[%s] Applying migration %s: %s",
                    db_name,
                    migration.version,
                    migration.description,
                )

                try:
                    # Load and execute migration module
                    module = self._load_migration_module(migration)
                    if hasattr(module, "upgrade"):
                        # Check if migration is empty (only has pass)
                        if self._is_empty_migration(module.upgrade):
                            raise ValueError(
                                f"Migration {migration.version} ({migration.path.name}) has empty "
                                f"upgrade() function. Please implement the migration SQL or remove "
                                f"the migration file if it's not needed."
                            )
                        module.upgrade(conn)
                        conn.commit()
                    else:
                        raise ValueError(f"Migration {migration.path} missing upgrade() function")

                    # Update version and record checksum
                    manager.set_version(migration.version)
                    self._record_migration(conn, migration)
                    conn.commit()
                    applied.append(migration.version)

                    logger.info(
                        "[%s] Applied migration %s successfully", db_name, migration.version
                    )

                except (OSError, RuntimeError, ValueError, sqlite3.OperationalError) as e:
                    conn.rollback()
                    errors.append(
                        {
                            "version": migration.version,
                            "error": str(e),
                        }
                    )
                    logger.error("[%s] Migration %s failed: %s", db_name, migration.version, e)
                    break  # Stop on first error

            final_version = manager.get_version()

            result = {
                "db_name": db_name,
                "status": "completed" if not errors else "partial",
                "initial_version": current,
                "final_version": final_version,
                "applied": applied,
                "errors": errors,
            }
            if backup_id:
                result["backup_id"] = backup_id
            if checksum_warnings:
                result["checksum_warnings"] = checksum_warnings
            return result

        finally:
            conn.close()

    def _load_migration_module(self, migration: MigrationFile):
        """Load a migration module."""
        # Build module path relative to package
        db_name = migration.path.parent.name
        module_path = f"aragora.persistence.migrations.{db_name}.{migration.module_name}"

        # Import the module
        return importlib.import_module(module_path)

    def _is_empty_migration(self, func: Callable) -> bool:
        """Check if a migration function is effectively empty (only pass/pass-like)."""
        import inspect

        try:
            source = inspect.getsource(func)
            # Check if body is just 'pass' or comments + pass
            lines = [
                line.strip()
                for line in source.split("\n")
                if line.strip()
                and not line.strip().startswith("#")
                and not line.strip().startswith('"""')
                and not line.strip().startswith("'''")
                and not line.strip().startswith("def ")
            ]
            # Filter out docstrings
            non_doc_lines = [
                line for line in lines if not line.startswith('"') and not line.startswith("'")
            ]
            return len(non_doc_lines) == 0 or all(line == "pass" for line in non_doc_lines)
        except (OSError, TypeError) as e:
            # Inspection failures (e.g., source file not found, built-in function) mean non-empty
            logger.warning("Could not inspect function source: %s", e)
            return False

    def migrate_all(self, dry_run: bool = False) -> dict[str, dict]:
        """Run migrations for all databases."""
        results = {}
        for db_name in self.db_paths:
            results[db_name] = self.migrate(db_name, dry_run=dry_run)
        return results

    def rollback_to_version(
        self,
        db_name: str,
        target_version: int,
        dry_run: bool = False,
    ) -> dict:
        """
        Rollback multiple migrations to reach a specific version.

        Args:
            db_name: Name of the database module
            target_version: Target version to rollback to (0 = no migrations)
            dry_run: If True, show what would be done without executing

        Returns:
            Dict with rollback results
        """
        db_path = self.get_db_path(db_name)
        migrations = self.discover_migrations(db_name)

        if not migrations:
            return {
                "db_name": db_name,
                "status": "no_migrations",
                "message": f"No migrations found for {db_name}",
            }

        if not db_path.exists():
            return {
                "db_name": db_name,
                "status": "no_database",
                "message": f"Database {db_path} does not exist",
            }

        conn = get_wal_connection(db_path)
        try:
            manager = SchemaManager(conn, db_name, current_version=0)
            current_version = manager.get_version()

            if current_version <= target_version:
                return {
                    "db_name": db_name,
                    "status": "nothing_to_rollback",
                    "current_version": current_version,
                    "target_version": target_version,
                    "message": f"Already at version {current_version}, target is {target_version}",
                }

            # Get migrations to rollback (in reverse order)
            to_rollback = sorted(
                [
                    m
                    for m in migrations
                    if m.version <= current_version and m.version > target_version
                ],
                key=lambda m: m.version,
                reverse=True,
            )

            if dry_run:
                return {
                    "db_name": db_name,
                    "status": "dry_run",
                    "current_version": current_version,
                    "target_version": target_version,
                    "would_rollback": [
                        {
                            "version": m.version,
                            "name": m.name,
                            "description": m.description,
                        }
                        for m in to_rollback
                    ],
                }

            # Create backup before multi-step rollback
            backup_id = self.create_pre_migration_backup(db_path, db_name)

            rolled_back = []
            errors = []

            for migration in to_rollback:
                logger.info(
                    "[%s] Rolling back migration %s: %s",
                    db_name,
                    migration.version,
                    migration.description,
                )

                try:
                    module = self._load_migration_module(migration)
                    if not hasattr(module, "downgrade"):
                        errors.append(
                            {
                                "version": migration.version,
                                "error": "No downgrade() function defined",
                            }
                        )
                        break

                    if self._is_empty_migration(module.downgrade):
                        errors.append(
                            {
                                "version": migration.version,
                                "error": "downgrade() function is empty (pass statement)",
                            }
                        )
                        break

                    module.downgrade(conn)
                    conn.commit()

                    # Calculate new version
                    previous_versions = [
                        m.version for m in migrations if m.version < migration.version
                    ]
                    new_version = max(previous_versions) if previous_versions else 0
                    manager.set_version(new_version)

                    # Remove checksum record
                    try:
                        conn.execute(
                            "DELETE FROM _migration_checksums WHERE version = ?",
                            (migration.version,),
                        )
                        conn.commit()
                    except (OSError, RuntimeError, ValueError, sqlite3.OperationalError) as e:
                        logger.warning(
                            "Failed to remove migration checksum for version %s: %s",
                            migration.version,
                            e,
                        )

                    rolled_back.append(migration.version)
                    logger.info("[%s] Rolled back migration %s", db_name, migration.version)

                except (OSError, RuntimeError, ValueError, sqlite3.OperationalError) as e:
                    conn.rollback()
                    errors.append(
                        {
                            "version": migration.version,
                            "error": str(e),
                        }
                    )
                    logger.error("[%s] Rollback of %s failed: %s", db_name, migration.version, e)
                    break

            final_version = manager.get_version()

            result = {
                "db_name": db_name,
                "status": "completed" if not errors else "partial",
                "initial_version": current_version,
                "final_version": final_version,
                "target_version": target_version,
                "rolled_back": rolled_back,
                "errors": errors,
            }
            if backup_id:
                result["backup_id"] = backup_id
            return result

        finally:
            conn.close()

    def rollback(
        self,
        db_name: str,
        dry_run: bool = False,
    ) -> dict:
        """
        Rollback the last applied migration.

        WARNING: Rollback is not recommended in production. SQLite has
        limited ALTER TABLE support, so downgrades may not work properly.

        Args:
            db_name: Name of the database module
            dry_run: If True, show what would be done without executing

        Returns:
            Dict with rollback results
        """
        db_path = self.get_db_path(db_name)
        migrations = self.discover_migrations(db_name)

        if not migrations:
            return {
                "db_name": db_name,
                "status": "no_migrations",
                "message": f"No migrations found for {db_name}",
            }

        if not db_path.exists():
            return {
                "db_name": db_name,
                "status": "no_database",
                "message": f"Database {db_path} does not exist",
            }

        conn = get_wal_connection(db_path)
        try:
            manager = SchemaManager(conn, db_name, current_version=0)
            current_version = manager.get_version()

            if current_version == 0:
                return {
                    "db_name": db_name,
                    "status": "nothing_to_rollback",
                    "current_version": 0,
                    "message": "No migrations have been applied",
                }

            # Find the migration that matches current version
            migration = next(
                (m for m in migrations if m.version == current_version),
                None,
            )

            if not migration:
                return {
                    "db_name": db_name,
                    "status": "migration_not_found",
                    "current_version": current_version,
                    "message": f"Migration file for version {current_version} not found",
                }

            if dry_run:
                return {
                    "db_name": db_name,
                    "status": "dry_run",
                    "current_version": current_version,
                    "would_rollback": {
                        "version": migration.version,
                        "name": migration.name,
                        "description": migration.description,
                    },
                }

            # Execute rollback
            logger.info(
                "[%s] Rolling back migration %s: %s",
                db_name,
                migration.version,
                migration.description,
            )

            try:
                module = self._load_migration_module(migration)
                if not hasattr(module, "downgrade"):
                    return {
                        "db_name": db_name,
                        "status": "no_downgrade",
                        "current_version": current_version,
                        "message": f"Migration {migration.version} does not have a downgrade() function",
                    }

                # Check if downgrade is empty
                if self._is_empty_migration(module.downgrade):
                    return {
                        "db_name": db_name,
                        "status": "empty_downgrade",
                        "current_version": current_version,
                        "message": f"Migration {migration.version} has empty downgrade() - implement it first",
                    }

                module.downgrade(conn)
                conn.commit()

                # Calculate new version (previous migration or 0)
                previous_versions = [m.version for m in migrations if m.version < current_version]
                new_version = max(previous_versions) if previous_versions else 0
                manager.set_version(new_version)

                logger.info(
                    "[%s] Rolled back migration %s successfully", db_name, migration.version
                )

                return {
                    "db_name": db_name,
                    "status": "completed",
                    "previous_version": current_version,
                    "current_version": new_version,
                    "rolled_back": migration.version,
                }

            except (OSError, RuntimeError, ValueError, sqlite3.OperationalError) as e:
                conn.rollback()
                logger.error("[%s] Rollback failed: %s", db_name, e)
                return {
                    "db_name": db_name,
                    "status": "failed",
                    "current_version": current_version,
                    "error": str(e),
                }

        finally:
            conn.close()

    def create_migration(
        self,
        db_name: str,
        description: str,
    ) -> Path:
        """
        Create a new migration file.

        Args:
            db_name: Name of the database module
            description: Human-readable description

        Returns:
            Path to the created migration file
        """
        migrations_path = self.MIGRATIONS_DIR / db_name
        migrations_path.mkdir(parents=True, exist_ok=True)

        # Find next version number
        existing = self.discover_migrations(db_name)
        next_version = max((m.version for m in existing), default=0) + 1

        # Create filename
        slug = re.sub(r"[^a-z0-9]+", "_", description.lower()).strip("_")
        filename = f"{next_version:03d}_{slug}.py"
        file_path = migrations_path / filename

        # Create migration file
        template = f'''"""
Migration {next_version}: {description}

Created: {datetime.now(timezone.utc).isoformat()}

IMPORTANT: You MUST replace the 'pass' statement in upgrade() with actual SQL.
Empty migrations will FAIL validation and cannot be applied.
If this migration is not needed, delete the file instead.
"""

import sqlite3

def upgrade(conn: sqlite3.Connection) -> None:
    """
    Apply this migration.

    Common patterns:
    - Add column: ALTER TABLE tablename ADD COLUMN colname TYPE
    - Create table: CREATE TABLE IF NOT EXISTS ...
    - Create index: CREATE INDEX IF NOT EXISTS ...
    - Insert data: INSERT INTO tablename VALUES ...

    SQLite limitations (use workarounds):
    - Cannot DROP COLUMN directly (recreate table)
    - Cannot RENAME COLUMN in older SQLite (recreate table)
    - Cannot add constraints to existing table (recreate table)
    """
    # Example: Add a new column
    # conn.execute("""
    #     ALTER TABLE users ADD COLUMN locked_until TIMESTAMP
    # """)

    # Example: Create a new table
    # conn.execute("""
    #     CREATE TABLE IF NOT EXISTS audit_log (
    #         id INTEGER PRIMARY KEY AUTOINCREMENT,
    #         action TEXT NOT NULL,
    #         user_id TEXT,
    #         timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    #         details TEXT
    #     )
    # """)

    # Example: Create an index
    # conn.execute("""
    #     CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp
    #     ON audit_log(timestamp)
    # """)

    # REQUIRED: Replace this pass with your migration SQL
    # Empty migrations will fail validation - implement or delete this file
    pass

def downgrade(conn: sqlite3.Connection) -> None:
    """
    Reverse this migration (optional, for development only).

    WARNING: Downgrade is not recommended in production.
    SQLite has limited ALTER TABLE support - you may need to
    recreate tables to reverse changes.
    """
    # Example: Drop a table (if you created one in upgrade)
    # conn.execute("DROP TABLE IF EXISTS audit_log")

    # Example: Remove columns added in upgrade (SQLite table recreation pattern)
    # SQLite doesn't support DROP COLUMN, so we recreate the table:
    # conn.executescript("""
    #     -- Backup current data
    #     CREATE TABLE tablename_backup AS SELECT * FROM tablename;
    #     -- Drop original table
    #     DROP TABLE tablename;
    #     -- Recreate table WITHOUT the new columns
    #     CREATE TABLE tablename (
    #         -- original columns only
    #     );
    #     -- Copy data back (original columns only)
    #     INSERT INTO tablename (col1, col2, ...) SELECT col1, col2, ... FROM tablename_backup;
    #     -- Drop backup
    #     DROP TABLE tablename_backup;
    #     -- Recreate indexes
    #     CREATE INDEX IF NOT EXISTS ... ON tablename(...);
    # """)

    # Implement rollback logic here if you need rollback support.
    # For simple migrations (adding columns/tables), reverse the operation.
    # For complex migrations, you may need to use the table recreation pattern above.
    # If rollback is not supported, raise NotImplementedError:
    # raise NotImplementedError("Rollback not supported for this migration")
    pass
'''  # template generates migration file, no user input

        file_path.write_text(template)
        logger.info("Created migration: %s", file_path)

        # Clear cache
        self._discovered_migrations.pop(db_name, None)

        return file_path


def print_status(runner: MigrationRunner) -> None:
    """Print migration status for all databases."""
    status = runner.get_all_status()

    print("\n=== Migration Status ===\n")

    for db_name, db_status in status.items():
        if db_status is None:
            print(f"[{db_name}] Database does not exist")
            continue

        status_icon = "✓" if db_status.pending_count == 0 else "!"
        print(f"[{db_name}] {status_icon}")
        print(f"  Path: {db_status.db_path}")
        print(f"  Current version: {db_status.current_version}")
        print(f"  Target version: {db_status.target_version}")

        if db_status.pending_count > 0:
            print(f"  Pending migrations: {db_status.pending_migrations}")
        else:
            print("  Status: Up to date")
        print()


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Aragora Database Migration Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Show migration status for all databases",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what migrations would be run without executing",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Run pending migrations",
    )
    parser.add_argument(
        "--create",
        metavar="DESCRIPTION",
        help="Create a new migration with the given description",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback the last migration (requires --db, not recommended in production)",
    )
    parser.add_argument(
        "--rollback-to",
        metavar="VERSION",
        type=int,
        help="Rollback to a specific version (requires --db)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip automatic backup before migrations (not recommended)",
    )
    parser.add_argument(
        "--db",
        metavar="NAME",
        help="Target specific database (default: all)",
    )
    parser.add_argument(
        "--nomic-dir",
        metavar="PATH",
        help="Override ARAGORA_DATA_DIR/ARAGORA_NOMIC_DIR (legacy: NOMIC_DIR)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # Initialize runner
    nomic_dir = Path(args.nomic_dir) if args.nomic_dir else None
    runner = MigrationRunner(
        nomic_dir=nomic_dir,
        backup_before_migrate=not args.no_backup,
    )

    # Handle commands
    if args.status:
        print_status(runner)
        return 0

    if args.dry_run:
        if args.db:
            result = runner.migrate(args.db, dry_run=True)
            print(f"\n[{args.db}] Dry run:")
            if result.get("pending_migrations"):
                for m in result["pending_migrations"]:
                    print(f"  Would apply: {m['version']:03d}_{m['name']} - {m['description']}")
            else:
                print("  No pending migrations")
        else:
            results = runner.migrate_all(dry_run=True)
            for db_name, result in results.items():
                print(f"\n[{db_name}] Dry run:")
                if result.get("pending_migrations"):
                    for m in result["pending_migrations"]:
                        print(f"  Would apply: {m['version']:03d}_{m['name']} - {m['description']}")
                else:
                    print("  No pending migrations")
        return 0

    if args.migrate:
        if args.db:
            result = runner.migrate(args.db)
            print(f"\n[{args.db}] Migration result: {result['status']}")
            if result.get("applied"):
                print(f"  Applied: {result['applied']}")
            if result.get("errors"):
                for err in result["errors"]:
                    print(f"  Error in v{err['version']}: {err['error']}")
                return 1
        else:
            results = runner.migrate_all()
            has_errors = False
            for db_name, result in results.items():
                print(f"\n[{db_name}] {result['status']}")
                if result.get("applied"):
                    print(f"  Applied: {result['applied']}")
                if result.get("errors"):
                    has_errors = True
                    for err in result["errors"]:
                        print(f"  Error in v{err['version']}: {err['error']}")
            return 1 if has_errors else 0

    if args.create:
        if not args.db:
            print("Error: --db is required when creating a migration")
            return 1
        path = runner.create_migration(args.db, args.create)
        print(f"Created migration: {path}")
        return 0

    if args.rollback:
        if not args.db:
            print("Error: --db is required when rolling back")
            print("Rollback must target a specific database for safety.")
            return 1

        # Show warning
        print("\n⚠️  WARNING: Rollback is not recommended in production!")
        print("SQLite has limited ALTER TABLE support, so downgrades may not work properly.")
        print()

        if args.dry_run:
            result = runner.rollback(args.db, dry_run=True)
            print(f"[{args.db}] Rollback dry run:")
            if result.get("would_rollback"):
                rb = result["would_rollback"]
                print(f"  Would rollback: v{rb['version']} - {rb['description']}")
            else:
                print(f"  Status: {result.get('status')} - {result.get('message', '')}")
            return 0

        result = runner.rollback(args.db)
        print(f"\n[{args.db}] Rollback result: {result['status']}")

        if result["status"] == "completed":
            print(f"  Rolled back: v{result['rolled_back']}")
            print(f"  Previous version: {result['previous_version']}")
            print(f"  Current version: {result['current_version']}")
            return 0
        elif result.get("error"):
            print(f"  Error: {result['error']}")
            return 1
        else:
            print(f"  Message: {result.get('message', 'Unknown status')}")
            return 1 if result["status"] in ("failed", "error") else 0

    if args.rollback_to is not None:
        if not args.db:
            print("Error: --db is required when using --rollback-to")
            print("Rollback must target a specific database for safety.")
            return 1

        # Show warning
        print("\n⚠️  WARNING: Multi-step rollback is not recommended in production!")
        print("SQLite has limited ALTER TABLE support, so downgrades may not work properly.")
        print(f"Target version: {args.rollback_to}")
        print()

        if args.dry_run:
            result = runner.rollback_to_version(args.db, args.rollback_to, dry_run=True)
            print(f"[{args.db}] Rollback-to dry run:")
            if result.get("would_rollback"):
                print(f"  Current version: {result['current_version']}")
                print(f"  Target version: {result['target_version']}")
                print("  Would rollback migrations:")
                for m in result["would_rollback"]:
                    print(f"    - v{m['version']:03d}: {m['description']}")
            else:
                print(f"  Status: {result.get('status')} - {result.get('message', '')}")
            return 0

        result = runner.rollback_to_version(args.db, args.rollback_to)
        print(f"\n[{args.db}] Rollback-to result: {result['status']}")

        if result.get("backup_id"):
            print(f"  Pre-rollback backup: {result['backup_id']}")

        if result["status"] == "completed":
            print(f"  Initial version: {result['initial_version']}")
            print(f"  Final version: {result['final_version']}")
            print(f"  Rolled back: {result['rolled_back']}")
            return 0
        elif result["status"] == "partial":
            print(f"  Initial version: {result['initial_version']}")
            print(f"  Final version: {result['final_version']}")
            print(f"  Rolled back: {result.get('rolled_back', [])}")
            if result.get("errors"):
                for err in result["errors"]:
                    print(f"  Error in v{err['version']}: {err['error']}")
            return 1
        elif result.get("error"):
            print(f"  Error: {result['error']}")
            return 1
        else:
            print(f"  Message: {result.get('message', 'Unknown status')}")
            return 1 if result["status"] in ("failed", "error") else 0

    # No command specified, show help
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
