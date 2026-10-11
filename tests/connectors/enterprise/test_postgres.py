"""
Tests for PostgreSQL Enterprise Connector.

Tests the PostgreSQL integration including:
- Incremental sync using transaction timestamps
- LISTEN/NOTIFY for real-time change detection
- Table/view selection with schema support
- Connection pooling for performance
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import hashlib

import asyncpg
import pytest

from aragora.connectors.enterprise.base import SyncState, SyncStatus
from aragora.connectors.enterprise.database.postgres import (
    PostgreSQLConnector,
    DEFAULT_TIMESTAMP_COLUMNS,
    _validate_sql_identifier,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_credentials():
    """Mock credential provider with PostgreSQL credentials."""
    from tests.connectors.enterprise.conftest import MockCredentialProvider

    return MockCredentialProvider(
        {
            "POSTGRES_USER": "test_user",
            "POSTGRES_PASSWORD": "test_password",
        }
    )


@pytest.fixture
def postgres_connector(mock_credentials, tmp_path):
    """Create a PostgreSQL connector for testing."""
    return PostgreSQLConnector(
        host="localhost",
        port=5432,
        database="testdb",
        schema="public",
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
        {"column_name": "id", "data_type": "integer", "is_nullable": "NO"},
        {"column_name": "username", "data_type": "character varying", "is_nullable": "NO"},
        {"column_name": "email", "data_type": "character varying", "is_nullable": "YES"},
        {
            "column_name": "created_at",
            "data_type": "timestamp with time zone",
            "is_nullable": "YES",
        },
        {
            "column_name": "updated_at",
            "data_type": "timestamp with time zone",
            "is_nullable": "YES",
        },
    ]


# =============================================================================
# Initialization Tests
# =============================================================================


class TestPostgreSQLConnectorInit:
    """Test PostgreSQLConnector initialization."""

    def test_init_with_defaults(self, mock_credentials, tmp_path):
        """Test initialization with default options."""
        connector = PostgreSQLConnector(
            credentials=mock_credentials,
            state_dir=tmp_path,
        )
        assert connector.host == "localhost"
        assert connector.port == 5432
        assert connector.database == "postgres"
        assert connector.schema == "public"
        assert connector.tables == []
        assert connector.pool_size == 5

    def test_init_with_custom_options(self, mock_credentials, tmp_path):
        """Test initialization with custom options."""
        connector = PostgreSQLConnector(
            host="db.example.com",
            port=5433,
            database="production",
            schema="myschema",
            tables=["table1", "table2"],
            timestamp_column="modified_date",
            primary_key_column="pk_id",
            content_columns=["title", "body"],
            notify_channel="changes",
            pool_size=10,
            credentials=mock_credentials,
            state_dir=tmp_path,
        )

        assert connector.host == "db.example.com"
        assert connector.port == 5433
        assert connector.database == "production"
        assert connector.schema == "myschema"
        assert connector.tables == ["table1", "table2"]
        assert connector.timestamp_column == "modified_date"
        assert connector.primary_key_column == "pk_id"
        assert connector.content_columns == ["title", "body"]
        assert connector.notify_channel == "changes"
        assert connector.pool_size == 10

    def test_connector_id_format(self, postgres_connector):
        """Test connector ID is properly formatted."""
        assert postgres_connector.connector_id == "postgres_localhost_testdb_public"

    def test_source_type(self, postgres_connector):
        """Test source type property."""
        from aragora.reasoning.provenance import SourceType

        assert postgres_connector.source_type == SourceType.DATABASE

    def test_name_property(self, postgres_connector):
        """Test name property."""
        assert postgres_connector.name == "PostgreSQL (testdb.public)"


# =============================================================================
# Row to Content Tests
# =============================================================================


class TestRowToContent:
    """Test row to content conversion."""

    def test_row_to_content_basic(self, postgres_connector, sample_users_rows):
        """Test basic row to content conversion."""
        content = postgres_connector._row_to_content(sample_users_rows[0])

        assert "id: 1" in content
        assert "username: alice" in content
        assert "email: alice@example.com" in content

    def test_row_to_content_with_columns_filter(self, postgres_connector, sample_users_rows):
        """Test row to content with column filter."""
        content = postgres_connector._row_to_content(
            sample_users_rows[0],
            columns=["username", "email"],
        )

        assert "username: alice" in content
        assert "email: alice@example.com" in content
        assert "id:" not in content

    def test_row_to_content_handles_none_values(self, postgres_connector):
        """Test row to content handles None values."""
        row = {"id": 1, "name": "Test", "email": None}
        content = postgres_connector._row_to_content(row)

        assert "id: 1" in content
        assert "name: Test" in content
        # None values should not appear in content
        lines = content.split("\n")
        assert not any("email:" in line for line in lines if "None" in line)

    def test_row_to_content_handles_json_values(self, postgres_connector):
        """Test row to content handles JSON/dict values."""
        row = {"id": 1, "metadata": {"key": "value", "nested": {"a": 1}}}
        content = postgres_connector._row_to_content(row)

        assert "id: 1" in content
        assert "metadata:" in content
        assert '"key"' in content or "key" in content

    def test_row_to_content_handles_datetime(self, postgres_connector):
        """Test row to content handles datetime values."""
        row = {"id": 1, "created_at": datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)}
        content = postgres_connector._row_to_content(row)

        assert "created_at:" in content
        assert "2024-01-15" in content


# =============================================================================
# Domain Inference Tests
# =============================================================================


class TestDomainInference:
    """Test domain inference from table names."""

    def test_infer_user_domain(self, postgres_connector):
        """Test user-related tables get correct domain."""
        assert postgres_connector._infer_domain("users") == "operational/users"
        assert postgres_connector._infer_domain("user_accounts") == "operational/users"
        assert postgres_connector._infer_domain("profiles") == "operational/users"
        assert postgres_connector._infer_domain("auth_tokens") == "operational/users"

    def test_infer_financial_domain(self, postgres_connector):
        """Test financial tables get correct domain."""
        assert postgres_connector._infer_domain("orders") == "financial/transactions"
        assert postgres_connector._infer_domain("invoices") == "financial/transactions"
        assert postgres_connector._infer_domain("payments") == "financial/transactions"
        assert postgres_connector._infer_domain("transactions") == "financial/transactions"

    def test_infer_product_domain(self, postgres_connector):
        """Test product tables get correct domain."""
        assert postgres_connector._infer_domain("products") == "operational/products"
        assert postgres_connector._infer_domain("inventory") == "operational/products"
        assert postgres_connector._infer_domain("catalog_items") == "operational/products"

    def test_infer_log_domain(self, postgres_connector):
        """Test log tables get correct domain."""
        assert postgres_connector._infer_domain("audit_logs") == "operational/logs"
        assert postgres_connector._infer_domain("event_log") == "operational/logs"

    def test_infer_config_domain(self, postgres_connector):
        """Test config tables get correct domain."""
        assert postgres_connector._infer_domain("config") == "technical/configuration"
        assert postgres_connector._infer_domain("settings") == "technical/configuration"

    def test_infer_document_domain(self, postgres_connector):
        """Test document tables get correct domain."""
        assert postgres_connector._infer_domain("documents") == "general/documents"
        assert postgres_connector._infer_domain("file_attachments") == "general/documents"

    def test_infer_default_domain(self, postgres_connector):
        """Test unknown tables get default domain."""
        assert postgres_connector._infer_domain("random_data") == "general/database"
        assert postgres_connector._infer_domain("xyz_table") == "general/database"


# =============================================================================
# Timestamp Column Tests
# =============================================================================


class TestTimestampColumn:
    """Test timestamp column detection."""

    def test_find_explicit_timestamp_column(self, mock_credentials, tmp_path):
        """Test finding explicitly configured timestamp column."""
        connector = PostgreSQLConnector(
            timestamp_column="modified_date",
            credentials=mock_credentials,
            state_dir=tmp_path,
        )

        columns = [
            {"column_name": "id", "data_type": "integer"},
            {"column_name": "updated_at", "data_type": "timestamp"},
            {"column_name": "modified_date", "data_type": "timestamp"},
        ]

        result = connector._find_timestamp_column(columns)
        assert result == "modified_date"  # Uses explicit config

    def test_find_timestamp_column_auto(self, postgres_connector):
        """Test auto-detecting timestamp column."""
        columns = [
            {"column_name": "id", "data_type": "integer"},
            {"column_name": "name", "data_type": "varchar"},
            {"column_name": "updated_at", "data_type": "timestamp"},
        ]

        result = postgres_connector._find_timestamp_column(columns)
        assert result == "updated_at"

    def test_find_timestamp_column_modified_at(self, postgres_connector):
        """Test detecting modified_at column."""
        columns = [
            {"column_name": "id", "data_type": "integer"},
            {"column_name": "modified_at", "data_type": "timestamp"},
        ]

        result = postgres_connector._find_timestamp_column(columns)
        assert result == "modified_at"

    def test_find_timestamp_column_none(self, postgres_connector):
        """Test when no timestamp column exists."""
        columns = [
            {"column_name": "id", "data_type": "integer"},
            {"column_name": "name", "data_type": "varchar"},
        ]

        result = postgres_connector._find_timestamp_column(columns)
        assert result is None


# =============================================================================
# Connection Pool Tests
# =============================================================================


class TestConnectionPool:
    """Test connection pool management."""

    @pytest.mark.asyncio
    async def test_get_pool_creates_pool(self, postgres_connector):
        """Test pool is created on first access."""
        import sys

        mock_pool = MagicMock()
        mock_asyncpg = MagicMock()
        mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

        # Inject mock asyncpg module
        with patch.dict(sys.modules, {"asyncpg": mock_asyncpg}):
            pool = await postgres_connector._get_pool()

            assert pool == mock_pool
            assert postgres_connector._pool == mock_pool
            mock_asyncpg.create_pool.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_pool_reuses_existing(self, postgres_connector):
        """Test existing pool is reused."""
        existing_pool = MagicMock()
        postgres_connector._pool = existing_pool

        pool = await postgres_connector._get_pool()

        assert pool == existing_pool

    @pytest.mark.asyncio
    async def test_get_pool_asyncpg_not_installed(self, postgres_connector):
        """Test error when asyncpg not installed."""
        import sys

        # Remove asyncpg from modules and ensure import fails
        with patch.dict(sys.modules, {"asyncpg": None}):
            with pytest.raises(ImportError):
                await postgres_connector._get_pool()


# =============================================================================
# Table Discovery Tests
# =============================================================================


class TestTableDiscovery:
    """Test table discovery functionality."""

    @pytest.mark.asyncio
    async def test_discover_tables(self, postgres_connector):
        """Test discovering tables in schema."""
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [
            {"table_name": "users"},
            {"table_name": "orders"},
            {"table_name": "products"},
        ]

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        postgres_connector._pool = mock_pool

        tables = await postgres_connector._discover_tables()

        assert len(tables) == 3
        assert "users" in tables
        assert "orders" in tables
        assert "products" in tables

    @pytest.mark.asyncio
    async def test_get_table_columns(self, postgres_connector, sample_columns):
        """Test getting column information."""
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = sample_columns

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        postgres_connector._pool = mock_pool

        columns = await postgres_connector._get_table_columns("users")

        assert len(columns) == 5
        assert columns[0]["column_name"] == "id"
        assert columns[1]["column_name"] == "username"


# =============================================================================
# Sync Tests
# =============================================================================


class TestSync:
    """Test sync_items functionality."""

    @pytest.mark.asyncio
    async def test_sync_items_full(self, postgres_connector, sample_users_rows, sample_columns):
        """Test full sync with tables."""
        state = SyncState(connector_id="postgres", status=SyncStatus.IDLE)

        mock_conn = AsyncMock()
        # Return columns first, then rows
        mock_conn.fetch = AsyncMock(
            side_effect=[
                sample_columns,  # First call: get columns
                sample_users_rows,  # Second call: get rows
                sample_columns,  # Third call: get columns for second table
                [],  # Fourth call: get rows (empty for second table)
            ]
        )

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        postgres_connector._pool = mock_pool

        items = []
        async for item in postgres_connector.sync_items(state, batch_size=10):
            items.append(item)

        assert len(items) == 2  # Two users
        assert items[0].source_type == "database"
        assert "users" in items[0].title

    @pytest.mark.asyncio
    async def test_sync_items_metadata(self, postgres_connector, sample_users_rows, sample_columns):
        """Test sync item metadata."""
        state = SyncState(connector_id="postgres", status=SyncStatus.IDLE)

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            side_effect=[
                sample_columns,
                sample_users_rows[:1],  # Just one row
                sample_columns,
                [],
            ]
        )

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        postgres_connector._pool = mock_pool

        items = []
        async for item in postgres_connector.sync_items(state, batch_size=10):
            items.append(item)

        assert len(items) == 1
        item = items[0]
        assert item.metadata["database"] == "testdb"
        assert item.metadata["schema"] == "public"
        assert item.metadata["table"] == "users"
        assert "id" in item.metadata["columns"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "table_error",
        [
            pytest.param(
                asyncpg.exceptions.ConnectionDoesNotExistError(
                    "connection was closed in the middle of operation"
                ),
                id="connection-lost-mid-query",
            ),
            pytest.param(asyncpg.InterfaceError("connection is closed"), id="connection-closed"),
        ],
    )
    async def test_sync_items_error_handling(
        self, postgres_connector, sample_users_rows, sample_columns, table_error
    ):
        """Test a per-table asyncpg error is recorded and sync moves on to the next table."""
        state = SyncState(connector_id="postgres", status=SyncStatus.IDLE)

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            side_effect=[
                sample_columns,
                table_error,  # Row fetch fails on the first table ("users")
                sample_columns,
                sample_users_rows[:1],  # Second table ("orders") works
            ]
        )

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        postgres_connector._pool = mock_pool

        items = []
        async for item in postgres_connector.sync_items(state, batch_size=10):
            items.append(item)

        assert state.errors == ["users: sync failed"]
        assert [item.metadata["table"] for item in items] == ["orders"]
        assert mock_conn.fetch.await_count == 4

    @pytest.mark.asyncio
    async def test_sync_items_unexpected_error_propagates(self, postgres_connector, sample_columns):
        """Test an error type outside the per-table clause aborts the sync."""
        state = SyncState(connector_id="postgres", status=SyncStatus.IDLE)

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=[sample_columns, Exception("Connection lost")])

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        postgres_connector._pool = mock_pool

        with pytest.raises(Exception, match="Connection lost") as exc_info:
            async for _ in postgres_connector.sync_items(state, batch_size=10):
                pass

        assert exc_info.type is Exception
        assert state.errors == []
        assert mock_conn.fetch.await_count == 2


# =============================================================================
# Search Tests
# =============================================================================


class TestSearch:
    """Test search functionality."""

    @pytest.mark.asyncio
    async def test_search_with_fts(self, postgres_connector):
        """Test search using full-text search."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {"id": 1, "content": "matching content", "rank": 0.9},
            ]
        )

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        postgres_connector._pool = mock_pool

        # Clear configured tables to trigger _discover_tables call
        postgres_connector.tables = []

        # Mock discover tables (async method)
        with patch.object(
            postgres_connector,
            "_discover_tables",
            new_callable=AsyncMock,
            return_value=["documents"],
        ):
            results = await postgres_connector.search("matching", limit=5)

        assert len(results) == 1
        assert results[0]["table"] == "documents"

    @pytest.mark.asyncio
    async def test_search_fallback_to_ilike(self, postgres_connector, sample_columns):
        """Test search falls back to ILIKE when the FTS query raises an asyncpg error."""
        alice = {"id": 1, "username": "alice", "email": "alice@example.com"}

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            side_effect=[
                # FTS query fails: the table has no "content" column
                asyncpg.exceptions.UndefinedColumnError('column "content" does not exist'),
                sample_columns,  # Column lookup for the fallback
                [alice],  # ILIKE query
            ]
        )

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        postgres_connector._pool = mock_pool

        # Clear configured tables to trigger _discover_tables call
        postgres_connector.tables = []

        with patch.object(
            postgres_connector,
            "_discover_tables",
            new_callable=AsyncMock,
            return_value=["users"],
        ):
            results = await postgres_connector.search("alice", limit=5)

        assert results == [{"table": "users", "data": alice, "rank": 0.5}]
        fallback_query, fallback_pattern, _ = mock_conn.fetch.await_args_list[2].args
        assert "ILIKE" in fallback_query
        assert fallback_pattern == "%alice%"

    @pytest.mark.asyncio
    async def test_search_unexpected_error_propagates(self, postgres_connector):
        """Test an FTS error outside the search clauses propagates without the ILIKE fallback."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=RuntimeError("FTS not configured"))

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        postgres_connector._pool = mock_pool

        postgres_connector.tables = []

        with patch.object(
            postgres_connector,
            "_discover_tables",
            new_callable=AsyncMock,
            return_value=["users"],
        ):
            with pytest.raises(RuntimeError, match="FTS not configured"):
                await postgres_connector.search("alice", limit=5)

        assert mock_conn.fetch.await_count == 1


# =============================================================================
# Fetch Tests
# =============================================================================


class TestFetch:
    """Test fetch functionality."""

    @pytest.mark.asyncio
    async def test_fetch_invalid_id_format(self, postgres_connector):
        """Test fetch with invalid ID format."""
        result = await postgres_connector.fetch("invalid-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_wrong_database(self, postgres_connector):
        """Test fetch with wrong database."""
        result = await postgres_connector.fetch("pg:otherdb:users:abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_returns_none_for_hash_ids(self, postgres_connector):
        """Test fetch returns None for hash-based IDs (can't reverse hash)."""
        result = await postgres_connector.fetch("pg:testdb:users:abc123def456")
        assert result is None


# =============================================================================
# Webhook Tests
# =============================================================================


class TestWebhook:
    """Test webhook handling."""

    @pytest.mark.asyncio
    async def test_handle_webhook_valid(self, postgres_connector):
        """Test handling valid webhook."""
        payload = {
            "table": "users",
            "operation": "INSERT",
        }

        with patch.object(postgres_connector, "sync", new_callable=AsyncMock):
            result = await postgres_connector.handle_webhook(payload)
            assert result is True

    @pytest.mark.asyncio
    async def test_handle_webhook_missing_table(self, postgres_connector):
        """Test handling webhook without table."""
        payload = {"operation": "INSERT"}

        result = await postgres_connector.handle_webhook(payload)
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_webhook_missing_operation(self, postgres_connector):
        """Test handling webhook without operation."""
        payload = {"table": "users"}

        result = await postgres_connector.handle_webhook(payload)
        assert result is False


# =============================================================================
# Listener Tests
# =============================================================================


class TestListener:
    """Test LISTEN/NOTIFY functionality."""

    @pytest.mark.asyncio
    async def test_start_listener_no_channel(self, postgres_connector):
        """Test listener doesn't start without channel."""
        postgres_connector.notify_channel = None
        await postgres_connector.start_listener()
        assert postgres_connector._listener_task is None

    @pytest.mark.asyncio
    async def test_stop_listener(self, postgres_connector):
        """Test stopping listener."""
        import asyncio

        # Create a real task that waits indefinitely until cancelled
        cancelled = asyncio.Event()

        async def dummy_listener():
            try:
                await asyncio.Event().wait()  # Wait forever until cancelled
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(dummy_listener())
        postgres_connector._listener_task = task

        # Give task a chance to start
        await asyncio.sleep(0.01)

        await postgres_connector.stop_listener()

        # Verify the task was cancelled (either via .cancelled() or our event)
        assert task.done()
        assert cancelled.is_set() or task.cancelled()
        assert postgres_connector._listener_task is None


# =============================================================================
# Close Tests
# =============================================================================


class TestClose:
    """Test connection cleanup."""

    @pytest.mark.asyncio
    async def test_close_cleans_up(self, postgres_connector):
        """Test close method cleans up resources."""
        mock_pool = AsyncMock()
        mock_pool.close = AsyncMock()
        postgres_connector._pool = mock_pool

        await postgres_connector.close()

        mock_pool.close.assert_called_once()
        assert postgres_connector._pool is None


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
        assert _validate_sql_identifier("public", "schema") == "public"
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

    def test_max_length_63_for_postgresql(self):
        """Test PostgreSQL max identifier length is 63."""
        # 63 chars should be valid
        assert _validate_sql_identifier("a" * 63, "table") == "a" * 63

        # 64 chars should fail
        with pytest.raises(ValueError, match="too long"):
            _validate_sql_identifier("a" * 64, "table")
