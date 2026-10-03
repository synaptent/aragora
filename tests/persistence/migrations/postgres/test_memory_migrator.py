"""
Tests for SQLite to PostgreSQL Memory Migrator.

Tests the MemoryMigrator class that migrates ConsensusMemory and CritiqueStore
data from SQLite to PostgreSQL.
"""

import pytest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


import asyncpg


class TestMigrationStats:
    """Tests for MigrationStats dataclass."""

    def test_stats_success_when_no_errors(self):
        """MigrationStats.success should be True when no errors."""
        from aragora.persistence.migrations.postgres.memory_migrator import MigrationStats

        stats = MigrationStats(table="test", rows_migrated=100, rows_skipped=5)
        assert stats.success is True

    def test_stats_failure_when_errors(self):
        """MigrationStats.success should be False when errors present."""
        from aragora.persistence.migrations.postgres.memory_migrator import MigrationStats

        stats = MigrationStats(table="test", rows_migrated=50, rows_skipped=10, errors=["Error 1"])
        assert stats.success is False


class TestMigrationReport:
    """Tests for MigrationReport dataclass."""

    def test_report_totals(self):
        """MigrationReport should calculate totals correctly."""
        from aragora.persistence.migrations.postgres.memory_migrator import (
            MigrationReport,
            MigrationStats,
        )

        report = MigrationReport(
            source_path="/test/path",
            target_dsn="postgresql://...",
            started_at=datetime.now(timezone.utc),
            tables=[
                MigrationStats(table="t1", rows_migrated=100, rows_skipped=10),
                MigrationStats(table="t2", rows_migrated=200, rows_skipped=20),
            ],
        )

        assert report.total_migrated == 300
        assert report.total_skipped == 30
        assert report.total_errors == 0
        assert report.success is True

    def test_report_success_false_when_errors(self):
        """MigrationReport.success should be False if any table has errors."""
        from aragora.persistence.migrations.postgres.memory_migrator import (
            MigrationReport,
            MigrationStats,
        )

        report = MigrationReport(
            source_path="/test/path",
            target_dsn="postgresql://...",
            started_at=datetime.now(timezone.utc),
            tables=[
                MigrationStats(table="t1", rows_migrated=100),
                MigrationStats(table="t2", rows_migrated=0, errors=["Failed"]),
            ],
        )

        assert report.success is False
        assert report.total_errors == 1


class TestValueConversion:
    """Tests for value conversion logic."""

    @pytest.fixture
    def migrator(self):
        """Create a migrator instance for testing."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        # Use a dummy path since we won't actually connect
        return MemoryMigrator(sqlite_path="/tmp/test.db", postgres_dsn="postgresql://test")

    def test_convert_boolean_true(self, migrator):
        """Boolean 1 should convert to True."""
        config = {"bool_columns": ["is_active"]}
        result = migrator._convert_value(1, "is_active", config)
        assert result is True

    def test_convert_boolean_false(self, migrator):
        """Boolean 0 should convert to False."""
        config = {"bool_columns": ["is_active"]}
        result = migrator._convert_value(0, "is_active", config)
        assert result is False

    def test_convert_json_string(self, migrator):
        """JSON string should be preserved."""
        config = {"json_columns": ["data"]}
        result = migrator._convert_value('{"key": "value"}', "data", config)
        assert result == '{"key": "value"}'

    def test_convert_json_invalid(self, migrator):
        """Invalid JSON should be returned as-is."""
        config = {"json_columns": ["data"]}
        result = migrator._convert_value("not json", "data", config)
        assert result == "not json"

    def test_convert_timestamp_iso(self, migrator):
        """ISO timestamp should be converted to datetime."""
        config = {"timestamp_columns": ["created_at"]}
        result = migrator._convert_value("2024-01-15T10:30:00", "created_at", config)
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_convert_timestamp_with_z(self, migrator):
        """ISO timestamp with Z suffix should be converted."""
        config = {"timestamp_columns": ["created_at"]}
        result = migrator._convert_value("2024-01-15T10:30:00Z", "created_at", config)
        assert isinstance(result, datetime)

    def test_convert_none(self, migrator):
        """None values should remain None."""
        config = {"bool_columns": ["flag"]}
        result = migrator._convert_value(None, "flag", config)
        assert result is None

    def test_convert_regular_value(self, migrator):
        """Regular values should pass through unchanged."""
        config = {}
        result = migrator._convert_value("hello", "name", config)
        assert result == "hello"


class TestTableConfigurations:
    """Tests for table configuration definitions."""

    def test_consensus_tables_defined(self):
        """CONSENSUS_TABLES should define expected tables."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        expected_tables = ["consensus", "dissent", "verified_proofs"]
        for table in expected_tables:
            assert table in MemoryMigrator.CONSENSUS_TABLES

    def test_critique_tables_defined(self):
        """CRITIQUE_TABLES should define expected tables."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        expected_tables = [
            "debates",
            "critiques",
            "patterns",
            "agent_reputation",
            "patterns_archive",
        ]
        for table in expected_tables:
            assert table in MemoryMigrator.CRITIQUE_TABLES

    def test_consensus_columns_match(self):
        """Consensus table configs should have matching sqlite and pg columns."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        for table, config in MemoryMigrator.CONSENSUS_TABLES.items():
            assert config["sqlite_columns"] == config["pg_columns"], f"Column mismatch in {table}"

    def test_critique_columns_match(self):
        """Critique table configs should have matching sqlite and pg columns."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        for table, config in MemoryMigrator.CRITIQUE_TABLES.items():
            assert config["sqlite_columns"] == config["pg_columns"], f"Column mismatch in {table}"


class TestSQLiteOperations:
    """Tests for SQLite operations."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary SQLite database with test tables."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE debates (
                id TEXT PRIMARY KEY,
                task TEXT,
                consensus_reached INTEGER,
                created_at TEXT
            )
        """)
        conn.execute("""
            INSERT INTO debates (id, task, consensus_reached, created_at)
            VALUES ('d1', 'Test task', 1, '2024-01-15T10:00:00')
        """)
        conn.commit()
        conn.close()

        yield db_path

        # Cleanup
        db_path.unlink(missing_ok=True)

    def test_get_sqlite_conn(self, temp_db):
        """Should successfully connect to SQLite database."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        migrator = MemoryMigrator(sqlite_path=temp_db, postgres_dsn="postgresql://test")
        conn = migrator._get_sqlite_conn()

        try:
            cursor = conn.execute("SELECT id FROM debates")
            row = cursor.fetchone()
            assert row["id"] == "d1"
        finally:
            conn.close()

    def test_table_exists_sqlite_true(self, temp_db):
        """_table_exists_sqlite should return True for existing table."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        migrator = MemoryMigrator(sqlite_path=temp_db, postgres_dsn="postgresql://test")
        conn = sqlite3.connect(str(temp_db))
        conn.row_factory = sqlite3.Row

        try:
            assert migrator._table_exists_sqlite(conn, "debates") is True
        finally:
            conn.close()

    def test_table_exists_sqlite_false(self, temp_db):
        """_table_exists_sqlite should return False for missing table."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        migrator = MemoryMigrator(sqlite_path=temp_db, postgres_dsn="postgresql://test")
        conn = sqlite3.connect(str(temp_db))
        conn.row_factory = sqlite3.Row

        try:
            assert migrator._table_exists_sqlite(conn, "nonexistent") is False
        finally:
            conn.close()

    def test_get_sqlite_columns(self, temp_db):
        """_get_sqlite_columns should return column names."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        migrator = MemoryMigrator(sqlite_path=temp_db, postgres_dsn="postgresql://test")
        conn = sqlite3.connect(str(temp_db))
        conn.row_factory = sqlite3.Row

        try:
            columns = migrator._get_sqlite_columns(conn, "debates")
            assert "id" in columns
            assert "task" in columns
            assert "consensus_reached" in columns
        finally:
            conn.close()


class TestPostgresOperations:
    """Tests for PostgreSQL operations with mocking."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock connection pool."""
        return MagicMock()

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="INSERT 0 1")
        conn.executemany = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.fetchrow = AsyncMock(return_value=None)
        return conn

    @pytest.mark.asyncio
    async def test_table_exists_pg_true(self, mock_pool, mock_connection):
        """_table_exists_pg should return True when table exists."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        mock_connection.fetchrow.return_value = [True]
        mock_pool.acquire = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_connection),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        migrator = MemoryMigrator(sqlite_path="/tmp/test.db", postgres_dsn="postgresql://test")
        migrator._pool = mock_pool

        # Create proper async context manager
        async def async_ctx(self):
            return mock_connection

        mock_pool.acquire.return_value.__aenter__ = async_ctx
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await migrator._table_exists_pg(mock_pool, "debates")
        assert result is True


class TestMigratorInit:
    """Tests for MemoryMigrator initialization."""

    def test_init_with_defaults(self):
        """Migrator should initialize with default values."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        migrator = MemoryMigrator(
            sqlite_path="/test/path.db",
            postgres_dsn="postgresql://user:pass@host/db",
        )

        assert migrator.sqlite_path == Path("/test/path.db")
        assert migrator.postgres_dsn == "postgresql://user:pass@host/db"
        assert migrator.batch_size == 1000
        assert migrator.skip_existing is True

    def test_init_with_custom_values(self):
        """Migrator should accept custom values."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        migrator = MemoryMigrator(
            sqlite_path="/test/path.db",
            postgres_dsn="postgresql://test",
            batch_size=500,
            skip_existing=False,
        )

        assert migrator.batch_size == 500
        assert migrator.skip_existing is False


class TestReportPrinting:
    """Tests for report printing."""

    def test_print_report_success(self, capsys):
        """print_report should format successful migration."""
        from aragora.persistence.migrations.postgres.memory_migrator import (
            MigrationReport,
            MigrationStats,
            print_report,
        )

        report = MigrationReport(
            source_path="/test/source.db",
            target_dsn="host/db",
            started_at=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2024, 1, 15, 10, 0, 30, tzinfo=timezone.utc),
            tables=[
                MigrationStats(table="debates", rows_migrated=100),
                MigrationStats(table="patterns", rows_migrated=50, rows_skipped=5),
            ],
        )

        print_report(report)
        captured = capsys.readouterr()

        assert "MEMORY STORE MIGRATION REPORT" in captured.out
        assert "debates" in captured.out
        assert "100 migrated" in captured.out
        assert "SUCCESS" in captured.out

    def test_print_report_with_errors(self, capsys):
        """print_report should show errors."""
        from aragora.persistence.migrations.postgres.memory_migrator import (
            MigrationReport,
            MigrationStats,
            print_report,
        )

        report = MigrationReport(
            source_path="/test/source.db",
            target_dsn="host/db",
            started_at=datetime.now(timezone.utc),
            tables=[
                MigrationStats(table="debates", rows_migrated=0, errors=["Connection failed"]),
            ],
        )
        report.completed_at = datetime.now(timezone.utc)

        print_report(report)
        captured = capsys.readouterr()

        assert "Connection failed" in captured.out
        assert "FAILED" in captured.out


# ===========================================================================
# Tests: migrate_table Method (Async)
# ===========================================================================


class TestMigrateTableAsync:
    """Tests for async migrate_table method."""

    @pytest.fixture
    def temp_db_with_consensus(self):
        """Create SQLite database with consensus table."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE consensus (
                id TEXT PRIMARY KEY,
                task_hash TEXT,
                question TEXT,
                answer TEXT,
                confidence REAL,
                created_at TEXT
            )
        """)
        conn.execute("""
            INSERT INTO consensus (id, task_hash, question, answer, confidence, created_at)
            VALUES
                ('c1', 'hash1', 'Question 1', 'Answer 1', 0.9, '2024-01-15T10:00:00'),
                ('c2', 'hash2', 'Question 2', 'Answer 2', 0.85, '2024-01-16T11:00:00')
        """)
        conn.commit()
        conn.close()

        yield db_path
        db_path.unlink(missing_ok=True)

    @pytest.fixture
    def mock_pool_async(self):
        """Create mock asyncpg pool with async context manager."""
        pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.executemany = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.fetchrow = AsyncMock(return_value=[True])

        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=mock_acquire)
        pool.close = AsyncMock()

        return pool, mock_conn

    @pytest.mark.asyncio
    async def test_migrate_table_success(self, temp_db_with_consensus, mock_pool_async):
        """Should migrate table successfully with batching."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        pool, conn = mock_pool_async
        conn.fetchrow.return_value = [True]  # Table exists

        migrator = MemoryMigrator(
            sqlite_path=temp_db_with_consensus,
            postgres_dsn="postgresql://test",
            batch_size=10,
        )
        migrator._pool = pool

        table_config = MemoryMigrator.CONSENSUS_TABLES.get(
            "consensus",
            {
                "sqlite_columns": [
                    "id",
                    "task_hash",
                    "question",
                    "answer",
                    "confidence",
                    "created_at",
                ],
                "pg_columns": ["id", "task_hash", "question", "answer", "confidence", "created_at"],
                "timestamp_columns": ["created_at"],
            },
        )

        stats = await migrator.migrate_table("consensus", table_config)

        assert stats.success is True
        assert stats.rows_migrated == 2
        assert stats.table == "consensus"

    @pytest.mark.asyncio
    async def test_migrate_table_skip_existing(self, temp_db_with_consensus, mock_pool_async):
        """Should use ON CONFLICT DO NOTHING when skip_existing is True."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        pool, conn = mock_pool_async
        conn.fetchrow.return_value = [True]

        migrator = MemoryMigrator(
            sqlite_path=temp_db_with_consensus,
            postgres_dsn="postgresql://test",
            skip_existing=True,
        )
        migrator._pool = pool

        table_config = {
            "sqlite_columns": ["id", "task_hash"],
            "pg_columns": ["id", "task_hash"],
        }

        await migrator.migrate_table("consensus", table_config)

        # Verify executemany was called
        conn.executemany.assert_called()

    @pytest.mark.asyncio
    async def test_migrate_table_missing_sqlite_table(self, mock_pool_async):
        """Should skip migration if SQLite table doesn't exist."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        # Create empty database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        conn = sqlite3.connect(str(db_path))
        conn.close()

        pool, mock_conn = mock_pool_async

        migrator = MemoryMigrator(
            sqlite_path=db_path,
            postgres_dsn="postgresql://test",
        )
        migrator._pool = pool

        table_config = {
            "sqlite_columns": ["id"],
            "pg_columns": ["id"],
        }

        stats = await migrator.migrate_table("nonexistent", table_config)

        assert stats.rows_migrated == 0
        db_path.unlink(missing_ok=True)


# ===========================================================================
# Tests: migrate_consensus_memory Method
# ===========================================================================


class TestMigrateConsensusMemory:
    """Tests for migrate_consensus_memory method."""

    @pytest.fixture
    def temp_consensus_db(self):
        """Create SQLite database with all consensus tables."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        conn = sqlite3.connect(str(db_path))

        # Create consensus table
        conn.execute("""
            CREATE TABLE consensus (
                id TEXT PRIMARY KEY,
                task_hash TEXT,
                question TEXT
            )
        """)
        conn.execute("INSERT INTO consensus VALUES ('c1', 'h1', 'Q1')")

        # Create dissent table
        conn.execute("""
            CREATE TABLE dissent (
                id TEXT PRIMARY KEY,
                consensus_id TEXT,
                agent TEXT
            )
        """)
        conn.execute("INSERT INTO dissent VALUES ('d1', 'c1', 'agent1')")

        conn.commit()
        conn.close()

        yield db_path
        db_path.unlink(missing_ok=True)

    @pytest.fixture
    def mock_pool_for_consensus(self):
        """Create mock pool for consensus migration."""
        pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.executemany = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.fetchrow = AsyncMock(return_value=[True])

        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=mock_acquire)
        pool.close = AsyncMock()

        return pool, mock_conn

    @pytest.mark.asyncio
    async def test_migrate_consensus_memory_all_tables(
        self, temp_consensus_db, mock_pool_for_consensus
    ):
        """Should migrate all consensus tables."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        pool, conn = mock_pool_for_consensus

        migrator = MemoryMigrator(
            sqlite_path=temp_consensus_db,
            postgres_dsn="postgresql://test",
        )
        migrator._pool = pool

        results = await migrator.migrate_consensus_memory()

        # Should have results for each consensus table
        assert len(results) > 0


# ===========================================================================
# Tests: migrate_critique_store Method
# ===========================================================================


class TestMigrateCritiqueStore:
    """Tests for migrate_critique_store method."""

    @pytest.fixture
    def temp_critique_db(self):
        """Create SQLite database with critique tables."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        conn = sqlite3.connect(str(db_path))

        # Create debates table
        conn.execute("""
            CREATE TABLE debates (
                id TEXT PRIMARY KEY,
                task TEXT,
                consensus_reached INTEGER
            )
        """)
        conn.execute("INSERT INTO debates VALUES ('d1', 'Task 1', 1)")

        # Create critiques table
        conn.execute("""
            CREATE TABLE critiques (
                id TEXT PRIMARY KEY,
                debate_id TEXT,
                agent TEXT
            )
        """)
        conn.execute("INSERT INTO critiques VALUES ('cr1', 'd1', 'agent1')")

        conn.commit()
        conn.close()

        yield db_path
        db_path.unlink(missing_ok=True)

    @pytest.fixture
    def mock_pool_for_critique(self):
        """Create mock pool for critique migration."""
        pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.executemany = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.fetchrow = AsyncMock(return_value=[True])

        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=mock_acquire)
        pool.close = AsyncMock()

        return pool, mock_conn

    @pytest.mark.asyncio
    async def test_migrate_critique_store_all_tables(
        self, temp_critique_db, mock_pool_for_critique
    ):
        """Should migrate all critique tables."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        pool, conn = mock_pool_for_critique

        migrator = MemoryMigrator(
            sqlite_path=temp_critique_db,
            postgres_dsn="postgresql://test",
        )
        migrator._pool = pool

        results = await migrator.migrate_critique_store()

        assert len(results) > 0


# ===========================================================================
# Tests: migrate_all Method
# ===========================================================================


class TestMigrateAll:
    """Tests for migrate_all method."""

    @pytest.fixture
    def temp_full_db(self):
        """Create SQLite database with multiple tables."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        conn = sqlite3.connect(str(db_path))

        conn.execute("CREATE TABLE consensus (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO consensus VALUES ('c1')")

        conn.execute("CREATE TABLE debates (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO debates VALUES ('d1')")

        conn.commit()
        conn.close()

        yield db_path
        db_path.unlink(missing_ok=True)

    @pytest.fixture
    def mock_pool_full(self):
        """Create mock pool for full migration."""
        pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.executemany = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.fetchrow = AsyncMock(return_value=[True])

        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=mock_acquire)
        pool.close = AsyncMock()

        return pool, mock_conn

    @pytest.mark.asyncio
    async def test_migrate_all_returns_report(self, temp_full_db, mock_pool_full):
        """Should return MigrationReport with all table stats."""
        from aragora.persistence.migrations.postgres.memory_migrator import (
            MemoryMigrator,
            MigrationReport,
        )

        pool, conn = mock_pool_full

        migrator = MemoryMigrator(
            sqlite_path=temp_full_db,
            postgres_dsn="postgresql://test",
        )
        migrator._pool = pool

        report = await migrator.migrate_all()

        assert isinstance(report, MigrationReport)
        assert report.source_path == str(temp_full_db)
        assert report.started_at is not None
        assert report.completed_at is not None

    @pytest.mark.asyncio
    async def test_migrate_all_aggregates_errors(self, temp_full_db, mock_pool_full):
        """Should aggregate errors across all tables."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        pool, conn = mock_pool_full
        # Make executemany fail with a type migrate_table actually catches
        # (OSError, ConnectionError, RuntimeError, ValueError); a bare
        # Exception would propagate straight out of migrate_all().
        conn.executemany = AsyncMock(side_effect=RuntimeError("DB error"))

        migrator = MemoryMigrator(
            sqlite_path=temp_full_db,
            postgres_dsn="postgresql://test",
        )
        migrator._pool = pool

        report = await migrator.migrate_all()

        # Should still complete but with errors recorded
        assert report.completed_at is not None
        assert report.total_errors > 0
        assert any("DB error" in e for t in report.tables for e in t.errors)


# ===========================================================================
# Tests: Connection Pool Lifecycle
# ===========================================================================


class TestConnectionPoolLifecycle:
    """Tests for connection pool management."""

    @pytest.mark.asyncio
    async def test_close_pool(self):
        """Should properly close connection pool."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()

        migrator = MemoryMigrator(
            sqlite_path="/tmp/test.db",
            postgres_dsn="postgresql://test",
        )
        migrator._pool = mock_pool

        await migrator.close()

        mock_pool.close.assert_called_once()
        assert migrator._pool is None

    @pytest.mark.asyncio
    async def test_close_without_pool(self):
        """Should handle close when pool doesn't exist."""
        from aragora.persistence.migrations.postgres.memory_migrator import MemoryMigrator

        migrator = MemoryMigrator(
            sqlite_path="/tmp/test.db",
            postgres_dsn="postgresql://test",
        )

        # Should not raise
        await migrator.close()

        assert migrator._pool is None
