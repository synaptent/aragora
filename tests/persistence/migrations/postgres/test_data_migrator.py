"""
Tests for SQLite to PostgreSQL Data Migrator.

Tests the DataMigrator class that migrates data from SQLite databases
to PostgreSQL for production deployment.
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


import asyncpg


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def temp_sqlite_db():
    """Create a temporary SQLite database with test data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    conn = sqlite3.connect(str(db_path))

    # Create users table
    conn.execute("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            preferences TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        INSERT INTO users (id, email, is_active, preferences, created_at)
        VALUES
            ('u1', 'test@example.com', 1, '{"theme": "dark"}', '2024-01-15T10:30:00'),
            ('u2', 'user2@example.com', 0, '{}', '2024-01-16T11:00:00')
    """)

    # Create organizations table
    conn.execute("""
        CREATE TABLE organizations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            settings TEXT
        )
    """)
    conn.execute("""
        INSERT INTO organizations (id, name, settings)
        VALUES ('org1', 'Test Org', '{"plan": "enterprise"}')
    """)

    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    db_path.unlink(missing_ok=True)


@pytest.fixture
def mock_pool():
    """Create mock asyncpg pool with async context manager support."""
    pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.executemany = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value=None)

    # Create acquire context manager
    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=mock_acquire)
    pool.close = AsyncMock()

    return pool, mock_conn


@pytest.fixture
def migrator(temp_sqlite_db):
    """Create a DataMigrator instance for testing."""
    from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

    return DataMigrator(
        sqlite_path=temp_sqlite_db,
        postgres_dsn="postgresql://test:test@localhost/testdb",
    )


# ===========================================================================
# Tests: MigrationStats Dataclass
# ===========================================================================


class TestMigrationStats:
    """Tests for MigrationStats dataclass."""

    def test_creation(self):
        """Test MigrationStats creation."""
        from aragora.persistence.migrations.postgres.data_migrator import MigrationStats

        stats = MigrationStats(
            table="users",
            rows_migrated=100,
            rows_skipped=5,
            errors=[],
        )

        assert stats.table == "users"
        assert stats.rows_migrated == 100
        assert stats.rows_skipped == 5

    def test_success_when_no_errors(self):
        """MigrationStats.success should be True when no errors."""
        from aragora.persistence.migrations.postgres.data_migrator import MigrationStats

        stats = MigrationStats(table="test", rows_migrated=50, rows_skipped=0, errors=[])

        assert stats.success is True

    def test_failure_when_errors(self):
        """MigrationStats.success should be False when errors present."""
        from aragora.persistence.migrations.postgres.data_migrator import MigrationStats

        stats = MigrationStats(
            table="test",
            rows_migrated=25,
            rows_skipped=10,
            errors=["Connection failed"],
        )

        assert stats.success is False


# ===========================================================================
# Tests: DataMigrator Initialization
# ===========================================================================


class TestDataMigratorInit:
    """Tests for DataMigrator initialization."""

    def test_init_with_required_params(self, temp_sqlite_db):
        """Test initialization with required parameters."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        migrator = DataMigrator(
            sqlite_path=temp_sqlite_db,
            postgres_dsn="postgresql://test@host/db",
        )

        assert migrator.sqlite_path == temp_sqlite_db
        assert migrator.postgres_dsn == "postgresql://test@host/db"
        assert migrator.batch_size == 1000  # default

    def test_init_with_custom_batch_size(self, temp_sqlite_db):
        """Test initialization with custom batch size."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        migrator = DataMigrator(
            sqlite_path=temp_sqlite_db,
            postgres_dsn="postgresql://test@host/db",
            batch_size=500,
        )

        assert migrator.batch_size == 500

    def test_init_accepts_string_path(self):
        """Test initialization accepts string path."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        migrator = DataMigrator(
            sqlite_path="/tmp/test.db",
            postgres_dsn="postgresql://test@host/db",
        )

        assert migrator.sqlite_path == Path("/tmp/test.db")


# ===========================================================================
# Tests: _get_sqlite_conn Method
# ===========================================================================


class TestGetSqliteConn:
    """Tests for _get_sqlite_conn method."""

    def test_connects_to_existing_db(self, migrator, temp_sqlite_db):
        """Should connect to existing SQLite database."""
        conn = migrator._get_sqlite_conn()

        try:
            cursor = conn.execute("SELECT id FROM users")
            rows = cursor.fetchall()
            assert len(rows) == 2
        finally:
            conn.close()

    def test_raises_for_missing_db(self):
        """Should raise FileNotFoundError for missing database."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        migrator = DataMigrator(
            sqlite_path="/nonexistent/path.db",
            postgres_dsn="postgresql://test@host/db",
        )

        with pytest.raises(FileNotFoundError):
            migrator._get_sqlite_conn()

    def test_returns_row_factory(self, migrator):
        """Connection should have row_factory set."""
        conn = migrator._get_sqlite_conn()

        try:
            cursor = conn.execute("SELECT id, email FROM users LIMIT 1")
            row = cursor.fetchone()
            assert row["id"] == "u1"
            assert row["email"] == "test@example.com"
        finally:
            conn.close()


# ===========================================================================
# Tests: Value Conversion
# ===========================================================================


class TestValueConversion:
    """Tests for _convert_value method."""

    def test_convert_boolean_true(self, migrator):
        """Boolean 1 should convert to True."""
        result = migrator._convert_value(1, "BOOLEAN")
        assert result is True

    def test_convert_boolean_false(self, migrator):
        """Boolean 0 should convert to False."""
        result = migrator._convert_value(0, "BOOLEAN")
        assert result is False

    def test_convert_json_string(self, migrator):
        """JSON string should be preserved."""
        json_str = '{"key": "value"}'
        result = migrator._convert_value(json_str, "JSONB")
        assert result == json_str

    def test_convert_json_dict(self, migrator):
        """Dict should be converted to JSON string."""
        import json

        data = {"key": "value"}
        result = migrator._convert_value(data, "json")
        assert result == json.dumps(data)

    def test_convert_timestamp_iso(self, migrator):
        """ISO timestamp should be converted to datetime."""
        result = migrator._convert_value("2024-01-15T10:30:00", "TIMESTAMP")
        assert isinstance(result, datetime)
        assert result.year == 2024

    def test_convert_none(self, migrator):
        """None values should remain None."""
        result = migrator._convert_value(None, "TEXT")
        assert result is None

    def test_convert_regular_value(self, migrator):
        """Regular values should pass through unchanged."""
        result = migrator._convert_value("hello", "TEXT")
        assert result == "hello"


# ===========================================================================
# Tests: _get_pg_columns Method
# ===========================================================================


class TestGetPgColumns:
    """Tests for _get_pg_columns method."""

    @pytest.mark.asyncio
    async def test_returns_column_dict(self, mock_pool, temp_sqlite_db):
        """Should return dictionary of column names to types."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        pool, conn = mock_pool
        conn.fetch.return_value = [
            {"column_name": "id", "data_type": "text"},
            {"column_name": "email", "data_type": "text"},
        ]

        migrator = DataMigrator(
            sqlite_path=temp_sqlite_db,
            postgres_dsn="postgresql://test@host/db",
        )
        migrator._pool = pool

        columns = await migrator._get_pg_columns(pool, "users")

        assert columns == {"id": "text", "email": "text"}

    @pytest.mark.asyncio
    async def test_returns_empty_for_missing_table(self, mock_pool, temp_sqlite_db):
        """Should return empty dict for non-existent table."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        pool, conn = mock_pool
        conn.fetch.return_value = []

        migrator = DataMigrator(
            sqlite_path=temp_sqlite_db,
            postgres_dsn="postgresql://test@host/db",
        )

        columns = await migrator._get_pg_columns(pool, "nonexistent")

        assert columns == {}


# ===========================================================================
# Tests: migrate_table Method
# ===========================================================================


class TestMigrateTable:
    """Tests for migrate_table method."""

    @pytest.mark.asyncio
    async def test_migrate_success(self, mock_pool, temp_sqlite_db):
        """Should migrate table successfully."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        pool, conn = mock_pool
        conn.fetch.return_value = [
            {"column_name": "id", "data_type": "text"},
            {"column_name": "email", "data_type": "text"},
            {"column_name": "is_active", "data_type": "boolean"},
            {"column_name": "preferences", "data_type": "jsonb"},
            {"column_name": "created_at", "data_type": "timestamp with time zone"},
        ]

        migrator = DataMigrator(
            sqlite_path=temp_sqlite_db,
            postgres_dsn="postgresql://test@host/db",
        )
        migrator._pool = pool

        stats = await migrator.migrate_table("users")

        assert stats.success is True
        assert stats.rows_migrated == 2
        assert stats.table == "users"

    @pytest.mark.asyncio
    async def test_migrate_missing_pg_table(self, mock_pool, temp_sqlite_db):
        """Should report error for missing PostgreSQL table."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        pool, conn = mock_pool
        conn.fetch.return_value = []

        migrator = DataMigrator(
            sqlite_path=temp_sqlite_db,
            postgres_dsn="postgresql://test@host/db",
        )
        migrator._pool = pool

        stats = await migrator.migrate_table("users")

        assert stats.success is False
        assert "not found in PostgreSQL" in stats.errors[0]

    @pytest.mark.asyncio
    async def test_migrate_no_common_columns(self, mock_pool, temp_sqlite_db):
        """Should report error when no common columns."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        pool, conn = mock_pool
        conn.fetch.return_value = [
            {"column_name": "different_col", "data_type": "text"},
        ]

        migrator = DataMigrator(
            sqlite_path=temp_sqlite_db,
            postgres_dsn="postgresql://test@host/db",
        )
        migrator._pool = pool

        stats = await migrator.migrate_table("users")

        assert stats.success is False
        assert "No common columns" in stats.errors[0]

    @pytest.mark.asyncio
    async def test_migrate_with_batch_error(self, mock_pool, temp_sqlite_db):
        """Should track errors during batch insert."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        pool, conn = mock_pool
        conn.fetch.return_value = [
            {"column_name": "id", "data_type": "text"},
            {"column_name": "email", "data_type": "text"},
        ]
        conn.executemany = AsyncMock(side_effect=RuntimeError("Constraint violation"))

        migrator = DataMigrator(
            sqlite_path=temp_sqlite_db,
            postgres_dsn="postgresql://test@host/db",
            batch_size=1,
        )
        migrator._pool = pool

        stats = await migrator.migrate_table("users")

        assert stats.success is False
        assert len(stats.errors) > 0


# ===========================================================================
# Tests: migrate_all Method
# ===========================================================================


class TestMigrateAll:
    """Tests for migrate_all method."""

    @pytest.mark.asyncio
    async def test_migrate_all_tables(self, mock_pool, temp_sqlite_db):
        """Should migrate all configured tables."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        pool, conn = mock_pool
        conn.fetch.return_value = [
            {"column_name": "id", "data_type": "text"},
            {"column_name": "name", "data_type": "text"},
        ]

        migrator = DataMigrator(
            sqlite_path=temp_sqlite_db,
            postgres_dsn="postgresql://test@host/db",
        )
        migrator._pool = pool

        results = await migrator.migrate_all()

        assert len(results) == len(DataMigrator.TABLE_MAPPINGS)


# ===========================================================================
# Tests: close Method
# ===========================================================================


class TestClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close_with_pool(self, mock_pool, temp_sqlite_db):
        """Test close properly closes pool."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        pool, _ = mock_pool
        migrator = DataMigrator(
            sqlite_path=temp_sqlite_db,
            postgres_dsn="postgresql://test@host/db",
        )
        migrator._pool = pool

        await migrator.close()

        pool.close.assert_called_once()


# ===========================================================================
# Tests: TABLE_MAPPINGS Configuration
# ===========================================================================


class TestTableMappings:
    """Tests for TABLE_MAPPINGS configuration."""

    def test_required_tables_defined(self):
        """Should define all required tables."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        required_tables = ["users", "organizations", "debates"]

        for table in required_tables:
            assert table in DataMigrator.TABLE_MAPPINGS

    def test_knowledge_tables_defined(self):
        """Should define knowledge mound tables."""
        from aragora.persistence.migrations.postgres.data_migrator import DataMigrator

        knowledge_tables = ["knowledge_items", "knowledge_links"]

        for table in knowledge_tables:
            assert table in DataMigrator.TABLE_MAPPINGS
