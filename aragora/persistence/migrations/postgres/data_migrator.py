"""
SQLite to PostgreSQL Data Migrator.

Migrates data from SQLite databases to PostgreSQL for production deployment.

Usage:
    from aragora.persistence.migrations.postgres import DataMigrator

    migrator = DataMigrator(
        sqlite_path="path/to/aragora.db",
        postgres_dsn="postgresql://user:pass@host/db"
    )
    await migrator.migrate_all()

CLI:
    python -m aragora.persistence.migrations.postgres.data_migrator \\
        --sqlite-path .nomic/aragora.db \\
        --postgres-dsn "postgresql://..."
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
from dataclasses import dataclass
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
    rows_migrated: int
    rows_skipped: int
    errors: list[str]

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class DataMigrator:
    """
    Migrates data from SQLite to PostgreSQL.

    Handles type conversions and schema differences between the two databases.
    """

    # Tables to migrate and their column mappings (sqlite_col -> pg_col)
    # If None, columns are migrated as-is
    TABLE_MAPPINGS = {
        "users": None,
        "organizations": None,
        "usage_events": None,
        "oauth_providers": None,
        "audit_log": None,
        "org_invitations": None,
        "debates": None,
        "debate_messages": None,
        "agent_elo": None,
        "consensus_memory": None,
        "knowledge_items": None,
        "knowledge_links": None,
        "knowledge_staleness": None,
    }

    def __init__(
        self,
        sqlite_path: str | Path,
        postgres_dsn: str,
        batch_size: int = 1000,
    ):
        """
        Initialize the data migrator.

        Args:
            sqlite_path: Path to SQLite database
            postgres_dsn: PostgreSQL connection string
            batch_size: Number of rows to insert per batch
        """
        self.sqlite_path = Path(sqlite_path)
        self.postgres_dsn = postgres_dsn
        self.batch_size = batch_size
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

    def _convert_value(self, value: Any, column_type: str) -> Any:
        """Convert SQLite value to PostgreSQL-compatible value."""
        if value is None:
            return None

        # Boolean conversion (SQLite uses 0/1)
        if column_type in ("BOOLEAN", "bool"):
            return bool(value)

        # JSON conversion
        if column_type in ("JSONB", "json"):
            if isinstance(value, str):
                return value  # Already JSON string
            import json

            return json.dumps(value)

        # Timestamp conversion
        if "TIMESTAMP" in column_type.upper():
            if isinstance(value, str):
                # Parse ISO format timestamps
                from datetime import datetime

                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return value
            return value

        return value

    async def _get_pg_columns(self, pool: Pool, table: str) -> dict[str, str]:
        """Get PostgreSQL column names and types for a table."""
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = $1
                ORDER BY ordinal_position
            """,
                table,
            )
            return {row["column_name"]: row["data_type"] for row in rows}

    async def migrate_table(self, table: str) -> MigrationStats:
        """
        Migrate a single table from SQLite to PostgreSQL.

        Args:
            table: Table name to migrate

        Returns:
            MigrationStats with results
        """
        stats = MigrationStats(table=table, rows_migrated=0, rows_skipped=0, errors=[])

        pool = await self._get_pool()
        sqlite_conn = self._get_sqlite_conn()

        try:
            # Get PostgreSQL column info
            pg_columns = await self._get_pg_columns(pool, table)
            if not pg_columns:
                stats.errors.append(f"Table {table} not found in PostgreSQL")
                return stats

            # Get SQLite data
            # table name interpolation, parameterized
            cursor = sqlite_conn.execute(f"SELECT * FROM {table}")
            sqlite_columns = [desc[0] for desc in cursor.description]

            # Find common columns
            common_columns = [c for c in sqlite_columns if c in pg_columns]
            if not common_columns:
                stats.errors.append(f"No common columns between SQLite and PostgreSQL for {table}")
                return stats

            # Build INSERT statement
            placeholders = ", ".join(f"${i + 1}" for i in range(len(common_columns)))
            columns_str = ", ".join(common_columns)
            insert_sql = f"""
                INSERT INTO {table} ({columns_str})
                VALUES ({placeholders})
                ON CONFLICT DO NOTHING
            """  # table name interpolation, parameterized

            # Migrate in batches
            batch = []
            for row in cursor:
                # Convert row to PostgreSQL-compatible values
                values = []
                for col in common_columns:
                    value = row[col]
                    pg_type = pg_columns[col]
                    values.append(self._convert_value(value, pg_type))

                batch.append(tuple(values))

                if len(batch) >= self.batch_size:
                    async with pool.acquire() as conn:
                        try:
                            await conn.executemany(insert_sql, batch)
                            stats.rows_migrated += len(batch)
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
                    except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                        stats.errors.append(f"Final batch error: {e}")
                        stats.rows_skipped += len(batch)

            logger.info("Migrated %s rows to %s", stats.rows_migrated, table)

        except (OSError, ConnectionError, RuntimeError, ValueError, sqlite3.Error) as e:
            stats.errors.append(f"Migration error: {e}")
            logger.exception("Error migrating table %s", table)

        finally:
            sqlite_conn.close()

        return stats

    async def migrate_all(self) -> list[MigrationStats]:
        """
        Migrate all tables.

        Returns:
            List of MigrationStats for each table
        """
        results = []

        for table in self.TABLE_MAPPINGS:
            logger.info("Migrating table: %s", table)
            stats = await self.migrate_table(table)
            results.append(stats)

            if stats.errors:
                logger.warning("Table %s had errors: %s", table, stats.errors)

        return results

    async def close(self) -> None:
        """Close connections."""
        if self._pool:
            await self._pool.close()
            self._pool = None


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Migrate SQLite data to PostgreSQL")
    parser.add_argument(
        "--sqlite-path",
        required=True,
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--postgres-dsn",
        required=True,
        help="PostgreSQL connection string",
    )
    parser.add_argument(
        "--table",
        help="Migrate specific table only",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size for inserts (default: 1000)",
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

    migrator = DataMigrator(
        sqlite_path=args.sqlite_path,
        postgres_dsn=args.postgres_dsn,
        batch_size=args.batch_size,
    )

    try:
        if args.table:
            stats = await migrator.migrate_table(args.table)
            results = [stats]
        else:
            results = await migrator.migrate_all()

        # Print summary
        print("\n=== Migration Summary ===")
        total_migrated = 0
        total_skipped = 0
        total_errors = 0

        for stats in results:
            status = "OK" if stats.success else "ERRORS"
            print(f"  {stats.table}: {stats.rows_migrated} rows [{status}]")
            total_migrated += stats.rows_migrated
            total_skipped += stats.rows_skipped
            total_errors += len(stats.errors)

            if stats.errors:
                for error in stats.errors:
                    print(f"    - {error}")

        print(f"\nTotal: {total_migrated} migrated, {total_skipped} skipped, {total_errors} errors")

    finally:
        await migrator.close()


if __name__ == "__main__":
    asyncio.run(main())
