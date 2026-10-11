"""
Tests for MySQL Enterprise Connector.

Tests the MySQL integration including:
- Incremental sync using transaction timestamps
- Binary log (binlog) CDC for real-time change detection
- Table/view selection with schema support
- Connection pooling for performance
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import hashlib

import pytest

from aragora.connectors.enterprise.base import SyncState, SyncStatus
from aragora.connectors.enterprise.database.mysql import (
    MySQLConnector,
    DEFAULT_TIMESTAMP_COLUMNS,
    _validate_sql_identifier,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_credentials():
    """Mock credential provider with MySQL credentials."""
    from tests.connectors.enterprise.conftest import MockCredentialProvider

    return MockCredentialProvider(
        {
            "MYSQL_USER": "test_user",
            "MYSQL_PASSWORD": "test_password",
        }
    )


@pytest.fixture
def mysql_connector(mock_credentials, tmp_path):
    """Create a MySQL connector for testing."""
    return MySQLConnector(
        host="localhost",
        port=3306,
        database="testdb",
        tables=["users", "orders"],
        credentials=mock_credentials,
        state_dir=tmp_path / "sync_state",
    )


@pytest.fixture
def sample_users_rows():
    """Sample user table rows."""
    return [
        {
            "id": 1,
            "username": "alice",
            "email": "alice@example.com",
            "created_at": datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
            "updated_at": datetime(2024, 1, 16, 14, 30, tzinfo=timezone.utc),
        },
        {
            "id": 2,
            "username": "bob",
            "email": "bob@example.com",
            "created_at": datetime(2024, 1, 14, 9, 0, tzinfo=timezone.utc),
            "updated_at": datetime(2024, 1, 17, 11, 0, tzinfo=timezone.utc),
        },
    ]


@pytest.fixture
def sample_orders_rows():
    """Sample order table rows."""
    return [
        {
            "id": 101,
            "user_id": 1,
            "total": 99.99,
            "status": "completed",
            "created_at": datetime(2024, 1, 16, 10, 0, tzinfo=timezone.utc),
        },
        {
            "id": 102,
            "user_id": 2,
            "total": 149.50,
            "status": "pending",
            "created_at": datetime(2024, 1, 17, 9, 0, tzinfo=timezone.utc),
        },
    ]


@pytest.fixture
def sample_columns():
    """Sample column information."""
    return [
        {"column_name": "id", "data_type": "int", "is_nullable": "NO"},
        {"column_name": "username", "data_type": "varchar", "is_nullable": "NO"},
        {"column_name": "email", "data_type": "varchar", "is_nullable": "YES"},
        {"column_name": "created_at", "data_type": "datetime", "is_nullable": "YES"},
        {"column_name": "updated_at", "data_type": "datetime", "is_nullable": "YES"},
    ]


# =============================================================================
# Initialization Tests
# =============================================================================


class TestMySQLConnectorInit:
    """Test MySQLConnector initialization."""

    def test_init_with_defaults(self, mock_credentials, tmp_path):
        """Test initialization with default options."""
        connector = MySQLConnector(
            credentials=mock_credentials,
            state_dir=tmp_path,
        )
        assert connector.host == "localhost"
        assert connector.port == 3306
        assert connector.database == "mysql"
        assert connector.tables == []
        assert connector.pool_size == 5
        assert connector.enable_binlog_cdc is False

    def test_init_with_custom_options(self, mock_credentials, tmp_path):
        """Test initialization with custom options."""
        connector = MySQLConnector(
            host="db.example.com",
            port=3307,
            database="production",
            tables=["table1", "table2"],
            timestamp_column="modified_date",
            primary_key_column="pk_id",
            content_columns=["title", "body"],
            enable_binlog_cdc=True,
            server_id=200,
            pool_size=10,
            credentials=mock_credentials,
            state_dir=tmp_path,
        )

        assert connector.host == "db.example.com"
        assert connector.port == 3307
        assert connector.database == "production"
        assert connector.tables == ["table1", "table2"]
        assert connector.timestamp_column == "modified_date"
        assert connector.primary_key_column == "pk_id"
        assert connector.content_columns == ["title", "body"]
        assert connector.enable_binlog_cdc is True
        assert connector.server_id == 200
        assert connector.pool_size == 10

    def test_connector_id_format(self, mysql_connector):
        """Test connector ID is properly formatted."""
        assert mysql_connector.connector_id == "mysql_localhost_testdb"

    def test_source_type(self, mysql_connector):
        """Test source type property."""
        from aragora.reasoning.provenance import SourceType

        assert mysql_connector.source_type == SourceType.DATABASE

    def test_name_property(self, mysql_connector):
        """Test name property."""
        assert mysql_connector.name == "MySQL (testdb)"


# =============================================================================
# Row to Content Tests
# =============================================================================


class TestRowToContent:
    """Test row to content conversion."""

    def test_row_to_content_basic(self, mysql_connector, sample_users_rows):
        """Test basic row to content conversion."""
        content = mysql_connector._row_to_content(sample_users_rows[0])

        assert "id: 1" in content
        assert "username: alice" in content
        assert "email: alice@example.com" in content

    def test_row_to_content_with_columns_filter(self, mysql_connector, sample_users_rows):
        """Test row to content with column filter."""
        content = mysql_connector._row_to_content(
            sample_users_rows[0],
            columns=["username", "email"],
        )

        assert "username: alice" in content
        assert "email: alice@example.com" in content
        assert "id:" not in content

    def test_row_to_content_handles_none_values(self, mysql_connector):
        """Test row to content handles None values."""
        row = {"id": 1, "name": "Test", "email": None}
        content = mysql_connector._row_to_content(row)

        assert "id: 1" in content
        assert "name: Test" in content
        # None values should not appear in content
        lines = content.split("\n")
        assert not any("email:" in line for line in lines if "None" in line)

    def test_row_to_content_handles_json_values(self, mysql_connector):
        """Test row to content handles JSON/dict values."""
        row = {"id": 1, "metadata": {"key": "value", "nested": {"a": 1}}}
        content = mysql_connector._row_to_content(row)

        assert "id: 1" in content
        assert "metadata:" in content
        assert '"key"' in content or "key" in content

    def test_row_to_content_handles_datetime(self, mysql_connector):
        """Test row to content handles datetime values."""
        row = {"id": 1, "created_at": datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)}
        content = mysql_connector._row_to_content(row)

        assert "created_at:" in content
        assert "2024-01-15" in content


# =============================================================================
# Timestamp Column Tests
# =============================================================================


class TestTimestampColumn:
    """Test timestamp column detection."""

    def test_find_explicit_timestamp_column(self, mock_credentials, tmp_path):
        """Test finding explicitly configured timestamp column."""
        connector = MySQLConnector(
            timestamp_column="modified_date",
            credentials=mock_credentials,
            state_dir=tmp_path,
        )

        columns = [
            {"column_name": "id", "data_type": "int"},
            {"column_name": "updated_at", "data_type": "datetime"},
            {"column_name": "modified_date", "data_type": "datetime"},
        ]

        result = connector._find_timestamp_column(columns)
        assert result == "modified_date"  # Uses explicit config

    def test_find_timestamp_column_auto(self, mysql_connector):
        """Test auto-detecting timestamp column."""
        columns = [
            {"column_name": "id", "data_type": "int"},
            {"column_name": "name", "data_type": "varchar"},
            {"column_name": "updated_at", "data_type": "datetime"},
        ]

        result = mysql_connector._find_timestamp_column(columns)
        assert result == "updated_at"

    def test_find_timestamp_column_modified_at(self, mysql_connector):
        """Test detecting modified_at column."""
        columns = [
            {"column_name": "id", "data_type": "int"},
            {"column_name": "modified_at", "data_type": "datetime"},
        ]

        result = mysql_connector._find_timestamp_column(columns)
        assert result == "modified_at"

    def test_find_timestamp_column_none(self, mysql_connector):
        """Test when no timestamp column exists."""
        columns = [
            {"column_name": "id", "data_type": "int"},
            {"column_name": "name", "data_type": "varchar"},
        ]

        result = mysql_connector._find_timestamp_column(columns)
        assert result is None


# =============================================================================
# Connection Pool Tests
# =============================================================================


class TestConnectionPool:
    """Test connection pool management."""

    @pytest.mark.asyncio
    async def test_get_pool_creates_pool(self, mysql_connector):
        """Test pool is created on first access."""
        aiomysql = pytest.importorskip("aiomysql")

        mock_pool = MagicMock()

        # mysql.py binds aiomysql at import time, so patch the module object it holds.
        with patch.object(
            aiomysql, "create_pool", AsyncMock(return_value=mock_pool)
        ) as mock_create_pool:
            pool = await mysql_connector._get_pool()

            assert pool == mock_pool
            assert mysql_connector._pool == mock_pool
            mock_create_pool.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_pool_reuses_existing(self, mysql_connector):
        """Test existing pool is reused."""
        existing_pool = MagicMock()
        mysql_connector._pool = existing_pool

        pool = await mysql_connector._get_pool()

        assert pool == existing_pool

    @pytest.mark.asyncio
    async def test_get_pool_aiomysql_not_installed(self, mysql_connector):
        """Test error when aiomysql not installed."""
        import sys

        # Remove aiomysql from modules and ensure import fails
        with patch.dict(sys.modules, {"aiomysql": None}):
            with pytest.raises(ImportError):
                await mysql_connector._get_pool()


# =============================================================================
# Table Discovery Tests
# =============================================================================


class TestTableDiscovery:
    """Test table discovery functionality."""

    @pytest.mark.asyncio
    async def test_discover_tables(self, mysql_connector):
        """Test discovering tables in database."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(
            return_value=[
                ("users",),
                ("orders",),
                ("products",),
            ]
        )
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        # Setup pool.acquire() as async context manager
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        mysql_connector._pool = mock_pool

        tables = await mysql_connector._discover_tables()

        assert len(tables) == 3
        assert "users" in tables
        assert "orders" in tables
        assert "products" in tables

    @pytest.mark.asyncio
    async def test_get_table_columns(self, mysql_connector, sample_columns):
        """Test getting column information."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(
            return_value=[
                (col["column_name"], col["data_type"], col["is_nullable"]) for col in sample_columns
            ]
        )
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        # Setup pool.acquire() as async context manager
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        mysql_connector._pool = mock_pool

        columns = await mysql_connector._get_table_columns("users")

        assert len(columns) == 5
        assert columns[0]["column_name"] == "id"
        assert columns[1]["column_name"] == "username"


# =============================================================================
# CDC Manager Tests
# =============================================================================


class TestCDCManager:
    """Test CDC manager functionality."""

    def test_cdc_manager_created_lazily(self, mysql_connector):
        """Test CDC manager is created lazily."""
        assert mysql_connector._cdc_manager is None
        manager = mysql_connector.cdc_manager
        assert manager is not None
        assert mysql_connector._cdc_manager is manager

    def test_add_change_handler(self, mysql_connector):
        """Test adding change handlers."""
        mock_handler = MagicMock()
        mysql_connector.add_change_handler(mock_handler)

        assert mock_handler in mysql_connector._change_handlers
        # CDC manager should be reset
        assert mysql_connector._cdc_manager is None


# =============================================================================
# Binlog CDC Tests
# =============================================================================


class TestBinlogCDC:
    """Test binlog CDC functionality."""

    @pytest.mark.asyncio
    async def test_start_binlog_cdc_disabled(self, mysql_connector):
        """Test binlog CDC doesn't start when disabled."""
        mysql_connector.enable_binlog_cdc = False
        await mysql_connector.start_binlog_cdc()
        assert mysql_connector._binlog_stream is None

    @pytest.mark.asyncio
    async def test_stop_binlog_cdc(self, mysql_connector):
        """Test stopping binlog CDC."""
        import asyncio

        # Create a mock task
        async def dummy_task():
            await asyncio.sleep(1)

        task = asyncio.create_task(dummy_task())
        mysql_connector._cdc_task = task
        mysql_connector._binlog_stream = MagicMock()

        await mysql_connector.stop_binlog_cdc()

        assert task.cancelled()
        assert mysql_connector._binlog_stream is None


# =============================================================================
# Health Check Tests
# =============================================================================


class TestHealthCheck:
    """Test health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, mysql_connector):
        """Test health check returns healthy status."""
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(1,))
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        # Setup pool.acquire() as async context manager
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        mysql_connector._pool = mock_pool

        health = await mysql_connector.health_check()

        assert health["healthy"] is True
        assert health["database"] == "testdb"
        assert health["host"] == "localhost"

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, mysql_connector):
        """Test health check returns unhealthy on error."""
        mysql_connector._pool = None

        # Mock _get_pool to raise an exception
        with patch.object(mysql_connector, "_get_pool", side_effect=OSError("Connection failed")):
            health = await mysql_connector.health_check()

        assert health["healthy"] is False
        assert "error" in health


# =============================================================================
# Close Tests
# =============================================================================


class TestClose:
    """Test connection cleanup."""

    @pytest.mark.asyncio
    async def test_close_cleans_up(self, mysql_connector):
        """Test close method cleans up resources."""
        mock_pool = MagicMock()
        mock_pool.close = MagicMock()
        mock_pool.wait_closed = AsyncMock()
        mysql_connector._pool = mock_pool

        await mysql_connector.close()

        mock_pool.close.assert_called_once()
        mock_pool.wait_closed.assert_called_once()
        assert mysql_connector._pool is None


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Test module constants."""

    def test_default_timestamp_columns(self):
        """Test default timestamp column names."""
        assert "updated_at" in DEFAULT_TIMESTAMP_COLUMNS
        assert "modified_at" in DEFAULT_TIMESTAMP_COLUMNS
        assert "last_modified" in DEFAULT_TIMESTAMP_COLUMNS
        assert "timestamp" in DEFAULT_TIMESTAMP_COLUMNS


# =============================================================================
# SQL Identifier Validation Tests
# =============================================================================


class TestSQLIdentifierValidation:
    """Test SQL identifier validation for injection prevention."""

    def test_valid_identifiers(self):
        """Test valid SQL identifiers are accepted."""
        assert _validate_sql_identifier("users", "table") == "users"
        assert _validate_sql_identifier("testdb", "database") == "testdb"
        assert _validate_sql_identifier("updated_at", "column") == "updated_at"
        assert _validate_sql_identifier("Table1", "table") == "Table1"
        assert _validate_sql_identifier("_internal", "table") == "_internal"
        assert _validate_sql_identifier("user-data", "table") == "user-data"

    def test_empty_identifier_rejected(self):
        """Test empty identifiers are rejected."""
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_sql_identifier("", "table")

    def test_sql_injection_patterns_rejected(self):
        """Test SQL injection patterns are rejected."""
        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_sql_identifier("users; DROP TABLE users;--", "table")

        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_sql_identifier("users'", "table")

        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_sql_identifier("users OR 1=1", "table")

        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_sql_identifier("users/**/", "table")

    def test_special_characters_rejected(self):
        """Test special characters are rejected."""
        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_sql_identifier("table;name", "table")

        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_sql_identifier("table.name", "table")

        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_sql_identifier("table()", "table")

    def test_identifier_starting_with_number_rejected(self):
        """Test identifiers starting with numbers are rejected."""
        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_sql_identifier("1users", "table")

        with pytest.raises(ValueError, match="Invalid SQL"):
            _validate_sql_identifier("123", "table")

    def test_max_length_64_for_mysql(self):
        """Test MySQL max identifier length is 64."""
        # 64 chars should be valid
        assert _validate_sql_identifier("a" * 64, "table") == "a" * 64

        # 65 chars should fail
        with pytest.raises(ValueError, match="too long"):
            _validate_sql_identifier("a" * 65, "table")
