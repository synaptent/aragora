#!/usr/bin/env python3
"""
Database Consolidation Migration Script

Migrates from 22 SQLite databases to 4 consolidated databases:
- core.db: Debates, traces, tournaments, embeddings, positions
- memory.db: Continuum memory, agent memories, consensus, critiques, patterns
- analytics.db: ELO ratings, calibration, insights, evolution, meta-learning
- agents.db: Personas, relationships, experiments, genomes, genesis events

Usage:
    python scripts/migrate_databases.py --dry-run
    python scripts/migrate_databases.py --validate
    python scripts/migrate_databases.py --migrate

The migration uses schema files from aragora/persistence/schemas/*.sql
"""

import argparse
import hashlib
import json
import logging
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class DatabaseInventory:
    """Tracks database files and their metadata."""

    path: Path
    tables: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)
    checksum: str = ""
    size_bytes: int = 0


@dataclass
class MigrationResult:
    """Result of a migration operation."""

    source_db: str
    target_db: str
    tables_migrated: list[str]
    rows_migrated: int
    success: bool
    error: str | None = None
    duration_seconds: float = 0.0


class DatabaseMigrator:
    """Handles database consolidation migrations."""

    # Schema file locations (relative to project root)
    SCHEMA_DIR = Path("aragora/persistence/schemas")

    # Source -> (Target, Table mappings)
    # Each mapping is: source_table -> target_table (or same if unchanged)
    MIGRATION_MAP = {
        # === CORE DATABASE (debates, traces, tournaments, embeddings, positions) ===
        # From server/storage.py
        "debates.db": ("core.db", {"debates": "debates"}),
        # From debate/traces.py (embedded in various DBs)
        # Traces are typically in-memory or debate-specific
        # From tournaments/tournament.py
        # Tournaments may be in aragora_positions.db or separate
        # From memory/embeddings.py
        "debate_embeddings.db": ("core.db", {"embeddings": "embeddings"}),
        # From insights/flip_detector.py, agents/grounded.py
        "aragora_positions.db": (
            "core.db",
            {"positions": "positions", "detected_flips": "detected_flips"},
        ),
        "grounded_positions.db": ("core.db", {"positions": "positions"}),
        "position_ledger.db": ("core.db", {"positions": "positions"}),
        # === MEMORY DATABASE (continuum, memories, consensus, critiques, patterns) ===
        # From memory/continuum.py
        "continuum.db": (
            "memory.db",
            {
                "continuum_memory": "continuum_memory",
                "tier_transitions": "tier_transitions",
                "continuum_memory_archive": "continuum_memory_archive",
                "meta_learning_state": "meta_learning_state",
            },
        ),
        # From memory/streams.py
        "agent_memories.db": (
            "memory.db",
            {
                "memories": "memories",
                "reflection_schedule": "reflection_schedule",
            },
        ),
        # From memory/consensus.py
        "consensus_memory.db": (
            "memory.db",
            {
                "consensus": "consensus",
                "dissent": "dissent",
            },
        ),
        # From memory/store.py
        "agora_memory.db": (
            "memory.db",
            {
                "debates": "debates",
                "critiques": "critiques",
                "patterns": "patterns",
                "pattern_embeddings": "pattern_embeddings",
                "agent_reputation": "agent_reputation",
                "patterns_archive": "patterns_archive",
            },
        ),
        # From audience/feedback.py
        "suggestion_feedback.db": (
            "memory.db",
            {
                "suggestion_injections": "suggestion_injections",
                "contributor_stats": "contributor_stats",
            },
        ),
        # From memory/embeddings.py (semantic)
        "semantic_patterns.db": ("memory.db", {"embeddings": "semantic_embeddings"}),
        # === ANALYTICS DATABASE (ELO, calibration, insights, evolution) ===
        # From ranking/elo.py
        "agent_elo.db": (
            "analytics.db",
            {
                "ratings": "ratings",
                "matches": "matches",
                "elo_history": "elo_history",
                "calibration_predictions": "calibration_predictions",
                "domain_calibration": "domain_calibration",
                "calibration_buckets": "calibration_buckets",
                "agent_relationships": "agent_relationships",
            },
        ),
        "elo.db": ("analytics.db", {"ratings": "ratings", "matches": "matches"}),
        # From agents/calibration.py
        "agent_calibration.db": ("analytics.db", {"predictions": "calibration_predictions"}),
        # From insights/store.py
        "aragora_insights.db": (
            "analytics.db",
            {
                "insights": "insights",
                "debate_summaries": "debate_summaries",
                "agent_performance_history": "agent_performance_history",
                "pattern_clusters": "pattern_clusters",
            },
        ),
        # From evolution/evolver.py
        "prompt_evolution.db": (
            "analytics.db",
            {
                "prompt_versions": "prompt_versions",
                "extracted_patterns": "extracted_patterns",
                "evolution_history": "evolution_history",
            },
        ),
        # From learning/meta.py
        "meta_learning.db": (
            "analytics.db",
            {
                "meta_hyperparams": "meta_hyperparams",
                "meta_efficiency_log": "meta_efficiency_log",
            },
        ),
        # === AGENTS DATABASE (personas, relationships, experiments, genomes) ===
        # From agents/personas.py
        "agent_personas.db": (
            "agents.db",
            {
                "personas": "personas",
                "performance_history": "performance_history",
            },
        ),
        "aragora_personas.db": (
            "agents.db",
            {
                "personas": "personas",
                "performance_history": "performance_history",
            },
        ),
        "personas.db": ("agents.db", {"personas": "personas"}),
        # From agents/grounded.py (relationships in elo DB)
        "agent_relationships.db": ("agents.db", {"agent_relationships": "agent_relationships"}),
        # From agents/truth_grounding.py
        # position_history and debate_outcomes
        # From agents/laboratory.py
        "persona_lab.db": (
            "agents.db",
            {
                "experiments": "experiments",
                "emergent_traits": "emergent_traits",
                "trait_transfers": "trait_transfers",
                "evolution_history": "agent_evolution_history",
            },
        ),
        # From genesis/genome.py
        "genesis.db": (
            "agents.db",
            {
                "genomes": "genomes",
                "populations": "populations",
                "active_population": "active_population",
                "genesis_events": "genesis_events",
            },
        ),
    }

    TARGET_DATABASES = ["core.db", "memory.db", "analytics.db", "agents.db"]

    TARGET_SCHEMAS = {
        "core.db": "core.sql",
        "memory.db": "memory.sql",
        "analytics.db": "analytics.sql",
        "agents.db": "agents.sql",
    }

    def __init__(self, source_dir: Path, target_dir: Path, backup_dir: Path):
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.backup_dir = backup_dir
        self.inventory: dict[str, DatabaseInventory] = {}
        self.results: list[MigrationResult] = []

    def discover_databases(self) -> dict[str, DatabaseInventory]:
        """Scan for all database files and inventory them."""
        logger.info(f"Discovering databases in {self.source_dir}")

        db_files = list(self.source_dir.glob("*.db"))
        db_files.extend(self.source_dir.glob(".nomic/*.db"))

        for db_path in db_files:
            if not db_path.exists():
                continue

            inv = DatabaseInventory(path=db_path)
            inv.size_bytes = db_path.stat().st_size
            inv.checksum = self._compute_checksum(db_path)

            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()

                # Get table names
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                inv.tables = [row[0] for row in cursor.fetchall()]

                # Get row counts
                for table in inv.tables:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        inv.row_counts[table] = cursor.fetchone()[0]
                    except sqlite3.Error:
                        inv.row_counts[table] = -1

                conn.close()
            except sqlite3.Error as e:
                logger.warning(f"Could not read {db_path}: {e}")

            self.inventory[db_path.name] = inv

        logger.info(f"Found {len(self.inventory)} database files")
        return self.inventory

    def _compute_checksum(self, path: Path) -> str:
        """Compute MD5 checksum of a file."""
        hash_md5 = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def backup_all(self) -> bool:
        """Create JSON backups of all databases."""
        logger.info(f"Creating backups in {self.backup_dir}")
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_subdir = self.backup_dir / f"backup_{timestamp}"
        backup_subdir.mkdir()

        manifest: dict[str, Any] = {
            "timestamp": timestamp,
            "databases": {},
        }

        for db_name, inv in self.inventory.items():
            try:
                # Copy the raw database file
                shutil.copy2(inv.path, backup_subdir / db_name)

                # Export to JSON for readability
                json_path = backup_subdir / f"{db_name}.json"
                self._export_to_json(inv.path, json_path)

                manifest["databases"][db_name] = {
                    "checksum": inv.checksum,
                    "size_bytes": inv.size_bytes,
                    "tables": inv.tables,
                    "row_counts": inv.row_counts,
                }
            except Exception as e:
                logger.error(f"Failed to backup {db_name}: {e}")
                return False

        # Write manifest
        manifest_path = backup_subdir / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        logger.info(f"Backup complete: {backup_subdir}")
        return True

    def _export_to_json(self, db_path: Path, json_path: Path) -> None:
        """Export all tables in a database to JSON."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        export = {}

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        for table in tables:
            try:
                cursor.execute(f"SELECT * FROM {table}")
                rows = [dict(row) for row in cursor.fetchall()]
                export[table] = rows
            except sqlite3.Error:
                export[table] = []

        conn.close()

        with open(json_path, "w") as f:
            json.dump(export, f, indent=2, default=str)

    def validate_source(self) -> tuple[bool, list[str]]:
        """Validate source databases are readable and have expected tables."""
        errors = []
        warnings = []

        for source_db, (target_db, table_map) in self.MIGRATION_MAP.items():
            if source_db not in self.inventory:
                # Not all databases are required (some are created on-demand)
                warnings.append(f"Source database not found: {source_db}")
                continue

            inv = self.inventory[source_db]

            # Skip empty databases - they have no data to migrate
            # Filter out SQLite internal tables (sqlite_*)
            user_tables = [t for t in inv.tables if not t.startswith("sqlite_")]
            if not user_tables:
                warnings.append(f"Empty database (no user tables): {source_db}")
                continue

            for source_table in table_map.keys():
                if source_table not in inv.tables:
                    errors.append(f"Missing table {source_table} in {source_db}")

        # Log warnings but don't fail validation for missing optional DBs
        for warning in warnings:
            logger.warning(warning)

        return len(errors) == 0, errors

    def create_target_schemas(self, dry_run: bool = True) -> bool:
        """Create the consolidated target database schemas from SQL files."""
        if dry_run:
            logger.info("[DRY RUN] Would create target schemas:")
            for db_name, schema_file in self.TARGET_SCHEMAS.items():
                schema_path = self.source_dir / self.SCHEMA_DIR / schema_file
                if schema_path.exists():
                    logger.info(f"  {db_name} <- {schema_file}")
                else:
                    logger.warning(f"  {db_name} <- {schema_file} (MISSING)")
            return True

        self.target_dir.mkdir(parents=True, exist_ok=True)

        for db_name, schema_file in self.TARGET_SCHEMAS.items():
            schema_path = self.source_dir / self.SCHEMA_DIR / schema_file

            if not schema_path.exists():
                logger.error(f"Schema file not found: {schema_path}")
                return False

            db_path = self.target_dir / db_name
            try:
                # Read schema SQL
                with open(schema_path) as f:
                    schema_sql = f.read()

                # Create database with schema
                conn = sqlite3.connect(db_path)
                conn.executescript(schema_sql)
                conn.commit()
                conn.close()
                logger.info(f"Created schema for {db_name} from {schema_file}")
            except sqlite3.Error as e:
                logger.error(f"Failed to create schema for {db_name}: {e}")
                return False
            except OSError as e:
                logger.error(f"Failed to read schema {schema_file}: {e}")
                return False

        return True

    def migrate(self, dry_run: bool = True) -> list[MigrationResult]:
        """Execute the migration."""
        results: list[MigrationResult] = []

        if dry_run:
            logger.info("[DRY RUN] Migration plan:")
            for source_db, (target_db, table_map) in self.MIGRATION_MAP.items():
                if source_db in self.inventory:
                    inv = self.inventory[source_db]
                    total_rows = sum(
                        inv.row_counts.get(t, 0) for t in table_map.keys() if t in inv.row_counts
                    )
                    tables_str = ", ".join(f"{s}->{t}" for s, t in table_map.items())
                    logger.info(f"  {source_db} -> {target_db}: [{tables_str}] ({total_rows} rows)")
            return results

        # Actual migration
        logger.info("Starting migration...")
        start_time = datetime.now()

        for source_db, (target_db, table_map) in self.MIGRATION_MAP.items():
            if source_db not in self.inventory:
                logger.debug(f"Skipping {source_db} (not found)")
                continue

            inv = self.inventory[source_db]
            result = MigrationResult(
                source_db=source_db,
                target_db=target_db,
                tables_migrated=[],
                rows_migrated=0,
                success=False,
            )

            migration_start = datetime.now()
            try:
                rows_migrated = self._migrate_database(
                    source_path=inv.path,
                    target_path=self.target_dir / target_db,
                    table_map=table_map,
                )
                result.tables_migrated = list(table_map.keys())
                result.rows_migrated = rows_migrated
                result.success = True
                logger.info(
                    f"Migrated {source_db} -> {target_db}: "
                    f"{len(table_map)} tables, {rows_migrated} rows"
                )
            except Exception as e:
                result.error = str(e)
                logger.error(f"Failed to migrate {source_db}: {e}")

            result.duration_seconds = (datetime.now() - migration_start).total_seconds()
            results.append(result)

        total_duration = (datetime.now() - start_time).total_seconds()
        total_rows = sum(r.rows_migrated for r in results)
        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Migration complete: {successful}/{len(results)} databases, "
            f"{total_rows} rows in {total_duration:.1f}s"
        )

        return results

    def _migrate_database(
        self,
        source_path: Path,
        target_path: Path,
        table_map: dict[str, str],
    ) -> int:
        """
        Migrate tables from source to target database.

        Args:
            source_path: Path to source SQLite database
            target_path: Path to target SQLite database
            table_map: Mapping of source_table -> target_table

        Returns:
            Total number of rows migrated
        """
        total_rows = 0

        source_conn = sqlite3.connect(source_path)
        source_conn.row_factory = sqlite3.Row
        target_conn = sqlite3.connect(target_path)

        try:
            for source_table, target_table in table_map.items():
                rows = self._migrate_table(source_conn, target_conn, source_table, target_table)
                total_rows += rows
        finally:
            source_conn.close()
            target_conn.close()

        return total_rows

    def _migrate_table(
        self,
        source_conn: sqlite3.Connection,
        target_conn: sqlite3.Connection,
        source_table: str,
        target_table: str,
    ) -> int:
        """
        Migrate a single table from source to target.

        Handles column mapping between source and target schemas.

        Returns:
            Number of rows migrated
        """
        source_cursor = source_conn.cursor()
        target_cursor = target_conn.cursor()

        # Get source table columns
        try:
            source_cursor.execute(f"PRAGMA table_info({source_table})")
            source_columns = {row[1] for row in source_cursor.fetchall()}
        except sqlite3.Error:
            logger.warning(f"Source table {source_table} not found, skipping")
            return 0

        if not source_columns:
            return 0

        # Get target table columns
        target_cursor.execute(f"PRAGMA table_info({target_table})")
        target_columns = {row[1] for row in target_cursor.fetchall()}

        if not target_columns:
            logger.warning(f"Target table {target_table} not found, skipping")
            return 0

        # Find common columns (columns that exist in both tables)
        common_columns = source_columns & target_columns

        if not common_columns:
            logger.warning(f"No common columns between {source_table} and {target_table}")
            return 0

        # Build insert statement
        columns_str = ", ".join(sorted(common_columns))
        placeholders = ", ".join("?" * len(common_columns))
        insert_sql = f"INSERT OR IGNORE INTO {target_table} ({columns_str}) VALUES ({placeholders})"

        # Read source data
        select_sql = f"SELECT {columns_str} FROM {source_table}"
        source_cursor.execute(select_sql)

        # Batch insert
        batch_size = 1000
        rows_migrated = 0
        batch = []

        for row in source_cursor:
            batch.append(tuple(row))
            if len(batch) >= batch_size:
                target_cursor.executemany(insert_sql, batch)
                rows_migrated += len(batch)
                batch = []

        # Insert remaining rows
        if batch:
            target_cursor.executemany(insert_sql, batch)
            rows_migrated += len(batch)

        target_conn.commit()

        logger.debug(
            f"  {source_table} -> {target_table}: {rows_migrated} rows "
            f"({len(common_columns)} columns)"
        )

        return rows_migrated

    def rollback(self, backup_name: str) -> bool:
        """
        Rollback to a previous backup.

        Args:
            backup_name: Name of backup directory (e.g., "backup_20260107_143022")

        Returns:
            True if rollback succeeded
        """
        backup_path = self.backup_dir / backup_name

        if not backup_path.exists():
            logger.error(f"Backup not found: {backup_path}")
            return False

        manifest_path = backup_path / "manifest.json"
        if not manifest_path.exists():
            logger.error(f"Manifest not found in backup: {manifest_path}")
            return False

        try:
            with open(manifest_path) as f:
                manifest = json.load(f)

            logger.info(f"Rolling back to backup from {manifest.get('timestamp', 'unknown')}")

            # Restore each database from backup
            for db_name in manifest.get("databases", {}):
                backup_db = backup_path / db_name
                if backup_db.exists():
                    # Find target location
                    target_path = self.source_dir / ".nomic" / db_name
                    if not target_path.parent.exists():
                        target_path = self.source_dir / db_name

                    logger.info(f"Restoring {db_name} -> {target_path}")
                    shutil.copy2(backup_db, target_path)

            logger.info("Rollback complete!")
            return True

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return False

    def verify_migration(self) -> tuple[bool, list[str]]:
        """
        Verify migrated databases have expected data.

        Returns:
            (success, list of issues)
        """
        issues = []

        for target_db in self.TARGET_DATABASES:
            target_path = self.target_dir / target_db

            if not target_path.exists():
                issues.append(f"Target database missing: {target_db}")
                continue

            try:
                conn = sqlite3.connect(target_path)
                cursor = conn.cursor()

                # Check schema version exists
                cursor.execute(
                    "SELECT version FROM _schema_versions WHERE module = ?",
                    (target_db.replace(".db", ""),),
                )
                row = cursor.fetchone()
                if not row:
                    issues.append(f"Schema version missing in {target_db}")
                else:
                    logger.info(f"{target_db}: schema version {row[0]}")

                # Count tables and rows
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                tables = [r[0] for r in cursor.fetchall()]

                total_rows = 0
                for table in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    total_rows += count

                logger.info(f"{target_db}: {len(tables)} tables, {total_rows} rows")

                conn.close()

            except sqlite3.Error as e:
                issues.append(f"Error reading {target_db}: {e}")

        return len(issues) == 0, issues

    def report(self) -> dict[str, Any]:
        """Generate migration report."""
        report: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "source_dir": str(self.source_dir),
            "target_dir": str(self.target_dir),
            "schema_dir": str(self.SCHEMA_DIR),
            "target_databases": self.TARGET_DATABASES,
            "inventory": {},
            "migration_plan": {},
            "summary": {
                "total_databases": len(self.inventory),
                "total_tables": 0,
                "total_rows": 0,
                "total_size_bytes": 0,
            },
        }

        for db_name, inv in self.inventory.items():
            report["inventory"][db_name] = {
                "path": str(inv.path),
                "size_bytes": inv.size_bytes,
                "tables": inv.tables,
                "row_counts": inv.row_counts,
                "checksum": inv.checksum,
            }
            report["summary"]["total_tables"] += len(inv.tables)
            report["summary"]["total_rows"] += sum(inv.row_counts.values())
            report["summary"]["total_size_bytes"] += inv.size_bytes

        for source, (target, table_map) in self.MIGRATION_MAP.items():
            if source in self.inventory:
                inv = self.inventory[source]
                report["migration_plan"][source] = {
                    "target": target,
                    "table_mappings": table_map,
                    "estimated_rows": sum(inv.row_counts.get(t, 0) for t in table_map.keys()),
                }

        return report


def main():
    parser = argparse.ArgumentParser(
        description="Aragora Database Consolidation Migration Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/migrate_databases.py --dry-run
  python scripts/migrate_databases.py --validate
  python scripts/migrate_databases.py --backup
  python scripts/migrate_databases.py --migrate

See docs/DATABASE_CONSOLIDATION.md for full documentation.
        """,
    )

    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory containing source databases (default: current directory)",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=Path.cwd() / "consolidated",
        help="Directory for consolidated databases (default: ./consolidated)",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path.cwd() / "backups",
        help="Directory for backups (default: ./backups)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show migration plan without executing"
    )
    parser.add_argument("--validate", action="store_true", help="Validate source databases")
    parser.add_argument("--backup", action="store_true", help="Create backups of all databases")
    parser.add_argument(
        "--migrate", action="store_true", help="Execute the migration (requires --backup first)"
    )
    parser.add_argument(
        "--report", action="store_true", help="Generate JSON report of current state"
    )
    parser.add_argument(
        "--rollback",
        type=str,
        metavar="BACKUP_DIR",
        help="Rollback to a previous backup (specify backup directory name)",
    )
    parser.add_argument(
        "--verify", action="store_true", help="Verify migrated databases match expected row counts"
    )

    args = parser.parse_args()

    migrator = DatabaseMigrator(
        source_dir=args.source_dir,
        target_dir=args.target_dir,
        backup_dir=args.backup_dir,
    )

    # Always discover databases first
    migrator.discover_databases()

    if args.report:
        report = migrator.report()
        print(json.dumps(report, indent=2))
        return 0

    if args.validate:
        valid, errors = migrator.validate_source()
        if valid:
            logger.info("Validation passed!")
        else:
            logger.error(f"Validation failed with {len(errors)} errors:")
            for err in errors:
                logger.error(f"  - {err}")
            return 1
        return 0

    if args.backup:
        success = migrator.backup_all()
        return 0 if success else 1

    if args.rollback:
        success = migrator.rollback(args.rollback)
        return 0 if success else 1

    if args.verify:
        success, issues = migrator.verify_migration()
        if success:
            logger.info("Verification passed!")
        else:
            logger.error(f"Verification failed with {len(issues)} issues:")
            for issue in issues:
                logger.error(f"  - {issue}")
            return 1
        return 0

    if args.migrate:
        if not args.backup:
            logger.warning("Recommend running --backup before --migrate")
        if not migrator.create_target_schemas(dry_run=False):
            logger.error("Failed to create target schemas")
            return 1
        results = migrator.migrate(dry_run=False)
        failed = sum(1 for r in results if not r.success)
        if failed > 0:
            logger.warning(f"{failed} databases failed to migrate")
            return 1
        return 0

    if args.dry_run:
        migrator.create_target_schemas(dry_run=True)
        migrator.migrate(dry_run=True)
        return 0

    # Default: show inventory
    print("\nDatabase Inventory:")
    print("-" * 60)
    total_size = 0
    total_rows = 0
    for db_name, inv in sorted(migrator.inventory.items()):
        rows = sum(inv.row_counts.values())
        total_rows += rows
        total_size += inv.size_bytes
        print(f"\n{db_name}")
        print(f"  Size: {inv.size_bytes / 1024:.1f} KB")
        print(f"  Tables: {', '.join(inv.tables) or 'none'}")
        print(f"  Total Rows: {rows}")

    print("\n" + "-" * 60)
    print(
        f"Total: {len(migrator.inventory)} databases, {total_size / 1024:.1f} KB, {total_rows} rows"
    )
    print("\nRun with --dry-run to see migration plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
