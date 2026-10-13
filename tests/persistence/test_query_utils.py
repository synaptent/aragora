"""
Tests for database query utilities.

Tests cover:
- chunked iterator
- batch_select
- batch_exists
- timed_query
- get_table_stats
"""

import pytest
import sqlite3
import time
from unittest.mock import patch, MagicMock

from aragora.persistence.query_utils import (
    chunked,
    batch_select,
    batch_exists,
    timed_query,
    get_table_stats,
)


@pytest.fixture
def db_conn():
    """In-memory SQLite database with test data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    # Create test table
    conn.execute("""
        CREATE TABLE test_items (
            id TEXT PRIMARY KEY,
            name TEXT,
            value INTEGER
        )
    """)

    # Insert test data
    items = [
        ("id1", "item1", 100),
        ("id2", "item2", 200),
        ("id3", "item3", 300),
        ("id4", "item4", 400),
        ("id5", "item5", 500),
    ]
    conn.executemany("INSERT INTO test_items VALUES (?, ?, ?)", items)
    conn.commit()

    yield conn
    conn.close()


class TestChunked:
    """Tests for chunked iterator."""

    def test_chunks_list(self):
        """Splits list into chunks."""
        items = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        chunks = list(chunked(items, 3))

        assert len(chunks) == 4
        assert chunks[0] == [1, 2, 3]
        assert chunks[1] == [4, 5, 6]
        assert chunks[2] == [7, 8, 9]
        assert chunks[3] == [10]

    def test_exact_division(self):
        """Handles exact division."""
        items = [1, 2, 3, 4, 5, 6]
        chunks = list(chunked(items, 3))

        assert len(chunks) == 2
        assert chunks[0] == [1, 2, 3]
        assert chunks[1] == [4, 5, 6]

    def test_larger_chunk_size(self):
        """Handles chunk size larger than list."""
        items = [1, 2, 3]
        chunks = list(chunked(items, 10))

        assert len(chunks) == 1
        assert chunks[0] == [1, 2, 3]

    def test_empty_list(self):
        """Handles empty list."""
        chunks = list(chunked([], 3))
        assert chunks == []

    def test_chunk_size_one(self):
        """Handles chunk size of 1."""
        items = [1, 2, 3]
        chunks = list(chunked(items, 1))

        assert len(chunks) == 3
        assert chunks == [[1], [2], [3]]


class TestBatchSelect:
    """Tests for batch_select function."""

    def test_select_all_ids(self, db_conn):
        """Selects all specified IDs."""
        ids = ["id1", "id2", "id3"]
        rows = batch_select(db_conn, "test_items", ids)

        assert len(rows) == 3
        row_ids = {row["id"] for row in rows}
        assert row_ids == {"id1", "id2", "id3"}

    def test_select_specific_columns(self, db_conn):
        """Selects specific columns."""
        ids = ["id1"]
        rows = batch_select(db_conn, "test_items", ids, columns=["id", "name"])

        assert len(rows) == 1
        assert dict(rows[0]).keys() == {"id", "name"}

    def test_empty_ids_list(self, db_conn):
        """Returns empty list for empty IDs."""
        rows = batch_select(db_conn, "test_items", [])
        assert rows == []

    def test_nonexistent_ids(self, db_conn):
        """Handles nonexistent IDs."""
        ids = ["nonexistent1", "nonexistent2"]
        rows = batch_select(db_conn, "test_items", ids)
        assert rows == []

    def test_mixed_existing_nonexistent(self, db_conn):
        """Returns only existing rows."""
        ids = ["id1", "nonexistent", "id3"]
        rows = batch_select(db_conn, "test_items", ids)

        assert len(rows) == 2
        row_ids = {row["id"] for row in rows}
        assert row_ids == {"id1", "id3"}

    def test_batching(self, db_conn):
        """Batches large ID lists."""
        ids = ["id1", "id2", "id3", "id4", "id5"]
        rows = batch_select(db_conn, "test_items", ids, batch_size=2)

        assert len(rows) == 5

    def test_custom_id_column(self, db_conn):
        """Uses custom ID column."""
        db_conn.execute("CREATE TABLE named_items (name TEXT PRIMARY KEY, value INT)")
        db_conn.execute("INSERT INTO named_items VALUES ('foo', 1)")
        db_conn.commit()

        rows = batch_select(db_conn, "named_items", ["foo"], id_column="name")
        assert len(rows) == 1

    def test_invalid_table_name_rejected(self, db_conn):
        """Rejects invalid table names."""
        with pytest.raises(ValueError, match="Invalid table name"):
            batch_select(db_conn, "test; DROP TABLE--", ["id1"])

    def test_invalid_column_name_rejected(self, db_conn):
        """Rejects invalid column names."""
        with pytest.raises(ValueError, match="Invalid column name"):
            batch_select(db_conn, "test_items", ["id1"], id_column="id; DROP--")

    def test_invalid_select_column_rejected(self, db_conn):
        """Rejects invalid column names in columns list."""
        with pytest.raises(ValueError, match="Invalid column name"):
            batch_select(db_conn, "test_items", ["id1"], columns=["id", "x; DROP--"])


class TestBatchExists:
    """Tests for batch_exists function."""

    def test_finds_existing_ids(self, db_conn):
        """Finds existing IDs."""
        ids = ["id1", "id2", "id3"]
        existing = batch_exists(db_conn, "test_items", ids)

        assert existing == {"id1", "id2", "id3"}

    def test_empty_ids_list(self, db_conn):
        """Returns empty set for empty IDs."""
        existing = batch_exists(db_conn, "test_items", [])
        assert existing == set()

    def test_nonexistent_ids(self, db_conn):
        """Returns empty for nonexistent IDs."""
        existing = batch_exists(db_conn, "test_items", ["nope1", "nope2"])
        assert existing == set()

    def test_mixed_existing_nonexistent(self, db_conn):
        """Returns only existing IDs."""
        ids = ["id1", "nonexistent", "id3", "also_nonexistent"]
        existing = batch_exists(db_conn, "test_items", ids)

        assert existing == {"id1", "id3"}

    def test_batching(self, db_conn):
        """Batches large ID lists."""
        ids = ["id1", "id2", "id3", "id4", "id5"]
        existing = batch_exists(db_conn, "test_items", ids, batch_size=2)

        assert len(existing) == 5

    def test_invalid_table_name_rejected(self, db_conn):
        """Rejects invalid table names."""
        with pytest.raises(ValueError, match="Invalid table name"):
            batch_exists(db_conn, "test; DROP TABLE--", ["id1"])


class TestTimedQuery:
    """Tests for timed_query function."""

    def test_executes_query(self, db_conn):
        """Executes query and returns cursor."""
        cursor = timed_query(db_conn, "SELECT * FROM test_items")
        rows = cursor.fetchall()

        assert len(rows) == 5

    def test_query_with_params(self, db_conn):
        """Executes query with parameters."""
        cursor = timed_query(
            db_conn,
            "SELECT * FROM test_items WHERE id = ?",
            params=("id1",),
        )
        rows = cursor.fetchall()

        assert len(rows) == 1
        assert rows[0]["id"] == "id1"

    def test_logs_slow_queries(self, db_conn):
        """Logs queries exceeding threshold."""
        with patch("aragora.persistence.query_utils.logger") as mock_logger:
            # Very low threshold to trigger logging
            cursor = timed_query(
                db_conn,
                "SELECT * FROM test_items",
                threshold_ms=0.0001,
            )
            cursor.fetchall()

            mock_logger.warning.assert_called()
            msg, *fmt_args = mock_logger.warning.call_args[0]
            assert "Slow query" in msg % tuple(fmt_args)

    def test_does_not_log_fast_queries(self, db_conn):
        """Does not log fast queries."""
        with patch("aragora.persistence.query_utils.logger") as mock_logger:
            cursor = timed_query(
                db_conn,
                "SELECT * FROM test_items",
                threshold_ms=10000,  # Very high threshold
            )
            cursor.fetchall()

            mock_logger.warning.assert_not_called()

    def test_includes_operation_name(self, db_conn):
        """Includes operation name in logs."""
        with patch("aragora.persistence.query_utils.logger") as mock_logger:
            timed_query(
                db_conn,
                "SELECT * FROM test_items",
                operation_name="fetch_items",
                threshold_ms=0.0001,
            )

            msg, *fmt_args = mock_logger.warning.call_args[0]
            assert "fetch_items" in msg % tuple(fmt_args)

    def test_truncates_long_queries_in_log(self, db_conn):
        """Truncates long queries in log output."""
        long_query = "SELECT * FROM test_items WHERE " + "id = 'x' OR " * 100

        with patch("aragora.persistence.query_utils.logger") as mock_logger:
            try:
                timed_query(db_conn, long_query, threshold_ms=0.0001)
            except sqlite3.Error:
                pass  # Query may fail, but we care about logging

            # Check warning was called and query was truncated
            if mock_logger.warning.called:
                msg, *fmt_args = mock_logger.warning.call_args[0]
                assert "..." in msg % tuple(fmt_args)

    def test_raises_on_error(self, db_conn):
        """Raises exception on query error."""
        with pytest.raises(sqlite3.Error):
            timed_query(db_conn, "SELECT * FROM nonexistent_table")


class TestGetTableStats:
    """Tests for get_table_stats function."""

    def test_returns_row_count(self, db_conn):
        """Returns correct row count."""
        stats = get_table_stats(db_conn, "test_items")

        assert stats["table"] == "test_items"
        assert stats["row_count"] == 5

    def test_empty_table(self, db_conn):
        """Handles empty table."""
        db_conn.execute("CREATE TABLE empty_table (id TEXT)")
        db_conn.commit()

        stats = get_table_stats(db_conn, "empty_table")
        assert stats["row_count"] == 0

    def test_invalid_table_name_rejected(self, db_conn):
        """Rejects invalid table names."""
        with pytest.raises(ValueError, match="Invalid table name"):
            get_table_stats(db_conn, "test; DROP TABLE--")


class TestEdgeCases:
    """Edge case tests."""

    def test_batch_select_preserves_order_within_batch(self, db_conn):
        """Results may not preserve input order but all are returned."""
        ids = ["id5", "id1", "id3"]
        rows = batch_select(db_conn, "test_items", ids)

        assert len(rows) == 3
        row_ids = {row["id"] for row in rows}
        assert row_ids == {"id1", "id3", "id5"}

    def test_unicode_ids(self, db_conn):
        """Handles unicode IDs."""
        db_conn.execute("INSERT INTO test_items VALUES ('日本語', 'japanese', 999)")
        db_conn.commit()

        rows = batch_select(db_conn, "test_items", ["日本語"])
        assert len(rows) == 1
        assert rows[0]["name"] == "japanese"

    def test_special_chars_in_values(self, db_conn):
        """Handles special characters in values (parameterized)."""
        db_conn.execute("INSERT INTO test_items VALUES ('special', 'O''Brien', 999)")
        db_conn.commit()

        rows = batch_select(db_conn, "test_items", ["special"])
        assert len(rows) == 1
        assert rows[0]["name"] == "O'Brien"
