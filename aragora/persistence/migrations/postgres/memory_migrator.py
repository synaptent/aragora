"""
SQLite to PostgreSQL Memory Store Migrator.

Migrates data from SQLite-based memory stores to PostgreSQL for production deployment.
Handles ConsensusMemory and CritiqueStore migrations.

Usage:
    from aragora.persistence.migrations.postgres import MemoryMigrator

    migrator = MemoryMigrator(
        sqlite_path="path/to/agora_memory.db",
        postgres_dsn="postgresql://user:pass@host/db"
    )
    await migrator.migrate_all()

CLI:
    python -m aragora.persistence.migrations.postgres.memory_migrator \\
        --sqlite-path .nomic/agora_memory.db \\
        --postgres-dsn "postgresql://..."
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Optional asyncpg import
try:
    import asyncpg
    from asyncpg import Pool

    ASYNCPG_AVAILABLE = True
except ImportError:
    asyncpg = None
    Pool = Any
    ASYNCPG_AVAILABLE = False


@dataclass
class MigrationStats:
    """Statistics from a data migration."""

    table: str
    rows_migrated: int = 0
    rows_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@dataclass
class MigrationReport:
    """Complete migration report."""

    source_path: str
    target_dsn: str
    started_at: datetime
    completed_at: datetime | None = None
    tables: list[MigrationStats] = field(default_factory=list)

    @property
    def total_migrated(self) -> int:
        return sum(t.rows_migrated for t in self.tables)

    @property
    def total_skipped(self) -> int:
        return sum(t.rows_skipped for t in self.tables)

    @property
    def total_errors(self) -> int:
        return sum(len(t.errors) for t in self.tables)

    @property
    def success(self) -> bool:
        return all(t.success for t in self.tables)


class MemoryMigrator:
    """
    Migrates memory stores from SQLite to PostgreSQL.

    Supports:
    - ConsensusMemory (consensus, dissent, verified_proofs tables)
    - CritiqueStore (debates, critiques, patterns, agent_reputation, patterns_archive)
    """

    # ConsensusMemory tables
    CONSENSUS_TABLES = {
        "consensus": {
            "sqlite_columns": [
                "id",
                "topic",
                "topic_hash",
                "conclusion",
                "strength",
                "confidence",
                "participating_agents",
                "agreeing_agents",
                "domain",
                "debate_id",
                "metadata",
                "data",
                "created_at",
                "updated_at",
            ],
            "pg_columns": [
                "id",
                "topic",
                "topic_hash",
                "conclusion",
                "strength",
                "confidence",
                "participating_agents",
                "agreeing_agents",
                "domain",
                "debate_id",
                "metadata",
                "data",
                "created_at",
                "updated_at",
            ],
            "json_columns": ["participating_agents", "agreeing_agents", "metadata", "data"],
            "timestamp_columns": ["created_at", "updated_at"],
        },
        "dissent": {
            "sqlite_columns": [
                "id",
                "debate_id",
                "agent_id",
                "dissent_type",
                "content",
                "reasoning",
                "confidence",
                "acknowledged",
                "rebuttal",
                "data",
                "created_at",
            ],
            "pg_columns": [
                "id",
                "debate_id",
                "agent_id",
                "dissent_type",
                "content",
                "reasoning",
                "confidence",
                "acknowledged",
                "rebuttal",
                "data",
                "created_at",
            ],
            "json_columns": ["data"],
            "timestamp_columns": ["created_at"],
            "bool_columns": ["acknowledged"],
        },
        "verified_proofs": {
            "sqlite_columns": [
                "id",
                "debate_id",
                "proof_status",
                "language",
                "formal_statement",
                "is_verified",
                "prover_version",
                "data",
                "created_at",
            ],
            "pg_columns": [
                "id",
                "debate_id",
                "proof_status",
                "language",
                "formal_statement",
                "is_verified",
                "prover_version",
                "data",
                "created_at",
            ],
            "json_columns": ["data"],
            "timestamp_columns": ["created_at"],
            "bool_columns": ["is_verified"],
        },
    }

    # CritiqueStore tables
    CRITIQUE_TABLES = {
        "debates": {
            "sqlite_columns": [
                "id",
                "task",
                "final_answer",
                "consensus_reached",
                "confidence",
                "rounds_used",
                "duration_seconds",
                "grounded_verdict",
                "created_at",
            ],
            "pg_columns": [
                "id",
                "task",
                "final_answer",
                "consensus_reached",
                "confidence",
                "rounds_used",
                "duration_seconds",
                "grounded_verdict",
                "created_at",
            ],
            "json_columns": ["grounded_verdict"],
            "timestamp_columns": ["created_at"],
            "bool_columns": ["consensus_reached"],
        },
        "critiques": {
            "sqlite_columns": [
                "id",
                "debate_id",
                "agent",
                "target_agent",
                "issues",
                "suggestions",
                "severity",
                "reasoning",
                "led_to_improvement",
                "expected_usefulness",
                "actual_usefulness",
                "prediction_error",
                "created_at",
            ],
            "pg_columns": [
                "id",
                "debate_id",
                "agent",
                "target_agent",
                "issues",
                "suggestions",
                "severity",
                "reasoning",
                "led_to_improvement",
                "expected_usefulness",
                "actual_usefulness",
                "prediction_error",
                "created_at",
            ],
            "json_columns": ["issues", "suggestions"],
            "timestamp_columns": ["created_at"],
            "bool_columns": ["led_to_improvement"],
        },
        "patterns": {
            "sqlite_columns": [
                "id",
                "issue_type",
                "issue_text",
                "suggestion_text",
                "success_count",
                "failure_count",
                "avg_severity",
                "surprise_score",
                "base_rate",
                "avg_prediction_error",
                "prediction_count",
                "example_task",
                "created_at",
                "updated_at",
            ],
            "pg_columns": [
                "id",
                "issue_type",
                "issue_text",
                "suggestion_text",
                "success_count",
                "failure_count",
                "avg_severity",
                "surprise_score",
                "base_rate",
                "avg_prediction_error",
                "prediction_count",
                "example_task",
                "created_at",
                "updated_at",
            ],
            "timestamp_columns": ["created_at", "updated_at"],
        },
        "agent_reputation": {
            "sqlite_columns": [
                "agent_name",
                "proposals_made",
                "proposals_accepted",
                "critiques_given",
                "critiques_valuable",
                "updated_at",
                "total_predictions",
                "total_prediction_error",
                "calibration_score",
            ],
            "pg_columns": [
                "agent_name",
                "proposals_made",
                "proposals_accepted",
                "critiques_given",
                "critiques_valuable",
                "updated_at",
                "total_predictions",
                "total_prediction_error",
                "calibration_score",
            ],
            "timestamp_columns": ["updated_at"],
        },
        "patterns_archive": {
            "sqlite_columns": [
                "id",
                "issue_type",
                "issue_text",
                "suggestion_text",
                "success_count",
                "failure_count",
                "avg_severity",
                "surprise_score",
                "example_task",
                "created_at",
                "updated_at",
                "archived_at",
            ],
            "pg_columns": [
                "id",
                "issue_type",
                "issue_text",
                "suggestion_text",
                "success_count",
                "failure_count",
                "avg_severity",
                "surprise_score",
                "example_task",
                "created_at",
                "updated_at",
                "archived_at",
            ],
            "timestamp_columns": ["created_at", "updated_at", "archived_at"],
        },
    }

    def __init__(
        self,
        sqlite_path: str | Path,
        postgres_dsn: str,
        batch_size: int = 1000,
        skip_existing: bool = True,
    ):
        """
        Initialize the memory migrator.

        Args:
            sqlite_path: Path to SQLite database
            postgres_dsn: PostgreSQL connection string
            batch_size: Number of rows to insert per batch
            skip_existing: Skip rows that already exist (ON CONFLICT DO NOTHING)
        """
        self.sqlite_path = Path(sqlite_path)
        self.postgres_dsn = postgres_dsn
        self.batch_size = batch_size
        self.skip_existing = skip_existing
        self._pool: Pool | None = None

    async def _get_pool(self) -> Pool:
        """Get or create PostgreSQL connection pool."""
        if not ASYNCPG_AVAILABLE:
            raise RuntimeError("asyncpg package required for PostgreSQL migration")

        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.postgres_dsn, min_size=2, max_size=10)
        return self._pool

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        """Get SQLite connection."""
        if not self.sqlite_path.exists():
            raise FileNotFoundError(f"SQLite database not found: {self.sqlite_path}")

        conn = sqlite3.connect(str(self.sqlite_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _convert_value(
        self,
        value: Any,
        column: str,
        table_config: dict,
    ) -> Any:
        """Convert SQLite value to PostgreSQL-compatible value."""
        if value is None:
            return None

        # Boolean conversion (SQLite uses 0/1)
        if column in table_config.get("bool_columns", []):
            return bool(value)

        # JSON conversion
        if column in table_config.get("json_columns", []):
            if isinstance(value, str):
                # Already JSON string, parse then re-serialize for JSONB
                try:
                    parsed = json.loads(value)
                    return json.dumps(parsed)
                except json.JSONDecodeError:
                    return value
            return json.dumps(value) if value else None

        # Timestamp conversion
        if column in table_config.get("timestamp_columns", []):
            if isinstance(value, str):
                try:
                    # Handle various timestamp formats
                    if "T" in value:
                        return datetime.fromisoformat(value.replace("Z", "+00:00"))
                    else:
                        return datetime.fromisoformat(value)
                except ValueError:
                    return datetime.now(timezone.utc)
            return value

        return value

    def _table_exists_sqlite(self, conn: sqlite3.Connection, table: str) -> bool:
        """Check if table exists in SQLite."""
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return cursor.fetchone() is not None

    async def _table_exists_pg(self, pool: Pool, table: str) -> bool:
        """Check if table exists in PostgreSQL."""
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = $1
                )
            """,
                table,
            )
            return row[0] if row else False

    def _get_sqlite_columns(self, conn: sqlite3.Connection, table: str) -> list[str]:
        """Get actual columns in SQLite table."""
        cursor = conn.execute(f"PRAGMA table_info({table})")  # nosec B608
        return [row[1] for row in cursor.fetchall()]

    async def migrate_table(
        self,
        table: str,
        table_config: dict,
    ) -> MigrationStats:
        """
        Migrate a single table from SQLite to PostgreSQL.

        Args:
            table: Table name
            table_config: Column mapping and type configuration

        Returns:
            MigrationStats with results
        """
        stats = MigrationStats(table=table)

        pool = await self._get_pool()
        sqlite_conn = self._get_sqlite_conn()

        try:
            # Check if tables exist
            if not self._table_exists_sqlite(sqlite_conn, table):
                logger.info("Table %s not found in SQLite, skipping", table)
                return stats

            if not await self._table_exists_pg(pool, table):
                stats.errors.append(f"Table {table} not found in PostgreSQL")
                return stats

            # Get actual SQLite columns
            actual_sqlite_columns = self._get_sqlite_columns(sqlite_conn, table)
            expected_columns = table_config["sqlite_columns"]

            # Find columns that exist in both SQLite source and config
            columns_to_migrate = [c for c in expected_columns if c in actual_sqlite_columns]

            if not columns_to_migrate:
                stats.errors.append(f"No columns found to migrate for {table}")
                return stats

            # Build SELECT and INSERT statements
            select_columns = ", ".join(columns_to_migrate)
            placeholders = ", ".join(f"${i + 1}" for i in range(len(columns_to_migrate)))
            insert_columns = ", ".join(columns_to_migrate)

            if self.skip_existing:
                insert_sql = f"""
                    INSERT INTO {table} ({insert_columns})
                    VALUES ({placeholders})
                    ON CONFLICT DO NOTHING
                """  # nosec B608 - columns from config
            else:
                insert_sql = f"""
                    INSERT INTO {table} ({insert_columns})
                    VALUES ({placeholders})
                """  # nosec B608

            # Fetch and migrate data in batches
            cursor = sqlite_conn.execute(f"SELECT {select_columns} FROM {table}")  # nosec B608

            batch = []
            for row in cursor:
                # Convert row values
                values = []
                for col in columns_to_migrate:
                    value = row[col]
                    converted = self._convert_value(value, col, table_config)
                    values.append(converted)

                batch.append(tuple(values))

                if len(batch) >= self.batch_size:
                    async with pool.acquire() as conn:
                        try:
                            await conn.executemany(insert_sql, batch)
                            stats.rows_migrated += len(batch)
                        except asyncpg.UniqueViolationError:
                            # Some rows already exist
                            stats.rows_skipped += len(batch)
                        except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                            stats.errors.append(f"Batch insert error: {e}")
                            stats.rows_skipped += len(batch)
                    batch = []

            # Insert remaining rows
            if batch:
                async with pool.acquire() as conn:
                    try:
                        await conn.executemany(insert_sql, batch)
                        stats.rows_migrated += len(batch)
                    except asyncpg.UniqueViolationError:
                        stats.rows_skipped += len(batch)
                    except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                        stats.errors.append(f"Final batch error: {e}")
                        stats.rows_skipped += len(batch)

            logger.info(
                "Migrated %s rows to %s (%s skipped)",
                stats.rows_migrated,
                table,
                stats.rows_skipped,
            )

        except (OSError, ConnectionError, RuntimeError, ValueError) as e:
            stats.errors.append(f"Migration error: {e}")
            logger.exception("Error migrating table %s", table)

        finally:
            sqlite_conn.close()

        return stats

    async def migrate_consensus_memory(self) -> list[MigrationStats]:
        """Migrate ConsensusMemory tables."""
        results = []
        for table, config in self.CONSENSUS_TABLES.items():
            logger.info("Migrating ConsensusMemory table: %s", table)
            stats = await self.migrate_table(table, config)
            results.append(stats)
        return results

    async def migrate_critique_store(self) -> list[MigrationStats]:
        """Migrate CritiqueStore tables."""
        results = []
        for table, config in self.CRITIQUE_TABLES.items():
            logger.info("Migrating CritiqueStore table: %s", table)
            stats = await self.migrate_table(table, config)
            results.append(stats)
        return results

    async def migrate_all(self) -> MigrationReport:
        """
        Migrate all memory store tables.

        Returns:
            MigrationReport with results
        """
        report = MigrationReport(
            source_path=str(self.sqlite_path),
            target_dsn=self.postgres_dsn.split("@")[-1] if "@" in self.postgres_dsn else "***",
            started_at=datetime.now(timezone.utc),
        )

        # Migrate ConsensusMemory tables
        consensus_stats = await self.migrate_consensus_memory()
        report.tables.extend(consensus_stats)

        # Migrate CritiqueStore tables
        critique_stats = await self.migrate_critique_store()
        report.tables.extend(critique_stats)

        report.completed_at = datetime.now(timezone.utc)
        return report

    async def close(self) -> None:
        """Close connections."""
        if self._pool:
            await self._pool.close()
            self._pool = None


def print_report(report: MigrationReport) -> None:
    """Print migration report to console."""
    print("\n" + "=" * 60)
    print("MEMORY STORE MIGRATION REPORT")
    print("=" * 60)

    print(f"\nSource: {report.source_path}")
    print(f"Target: {report.target_dsn}")
    print(f"Started: {report.started_at.isoformat()}")
    if report.completed_at:
        duration = (report.completed_at - report.started_at).total_seconds()
        print(f"Completed: {report.completed_at.isoformat()} ({duration:.1f}s)")

    print("\n" + "-" * 60)
    print("TABLE RESULTS")
    print("-" * 60)

    for stats in report.tables:
        status = "OK" if stats.success else "ERRORS"
        print(f"  {stats.table:20} | {stats.rows_migrated:6} migrated | {status}")
        if stats.rows_skipped:
            print(f"  {' ':20} | {stats.rows_skipped:6} skipped")
        for error in stats.errors:
            print(f"    ERROR: {error}")

    print("\n" + "-" * 60)
    print("SUMMARY")
    print("-" * 60)
    print(f"  Total rows migrated: {report.total_migrated}")
    print(f"  Total rows skipped:  {report.total_skipped}")
    print(f"  Total errors:        {report.total_errors}")
    print(f"  Status:              {'SUCCESS' if report.success else 'FAILED'}")
    print("=" * 60 + "\n")


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Migrate memory stores from SQLite to PostgreSQL")
    parser.add_argument(
        "--sqlite-path",
        required=True,
        help="Path to SQLite database (e.g., .nomic/agora_memory.db)",
    )
    parser.add_argument(
        "--postgres-dsn",
        required=True,
        help="PostgreSQL connection string",
    )
    parser.add_argument(
        "--store",
        choices=["all", "consensus", "critique"],
        default="all",
        help="Which store to migrate (default: all)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size for inserts (default: 1000)",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Don't skip existing rows (may cause errors)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    migrator = MemoryMigrator(
        sqlite_path=args.sqlite_path,
        postgres_dsn=args.postgres_dsn,
        batch_size=args.batch_size,
        skip_existing=not args.no_skip_existing,
    )

    try:
        if args.store == "consensus":
            stats_list = await migrator.migrate_consensus_memory()
            report = MigrationReport(
                source_path=str(migrator.sqlite_path),
                target_dsn=args.postgres_dsn.split("@")[-1],
                started_at=datetime.now(timezone.utc),
                tables=stats_list,
            )
            report.completed_at = datetime.now(timezone.utc)
        elif args.store == "critique":
            stats_list = await migrator.migrate_critique_store()
            report = MigrationReport(
                source_path=str(migrator.sqlite_path),
                target_dsn=args.postgres_dsn.split("@")[-1],
                started_at=datetime.now(timezone.utc),
                tables=stats_list,
            )
            report.completed_at = datetime.now(timezone.utc)
        else:
            report = await migrator.migrate_all()

        print_report(report)

        # Exit with error code if migration failed
        if not report.success:
            exit(1)

    finally:
        await migrator.close()


if __name__ == "__main__":
    asyncio.run(main())
