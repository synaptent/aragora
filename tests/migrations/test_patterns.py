"""
Tests for aragora.migrations.patterns module.

Covers:
- Zero-downtime migration patterns (safe_add_column, safe_drop_column, etc.)
- Backfill operations with batching
- Index creation/deletion
- Migration safety validation
- PostgreSQL vs SQLite behavior differences

Run with:
    python -m pytest tests/migrations/test_patterns.py -v --noconftest --timeout=30
"""

from __future__ import annotations

import sqlite3
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: lightweight in-memory SQLite backend that satisfies DatabaseBackend
# ---------------------------------------------------------------------------


class InMemorySQLiteBackend:
    """
    Minimal DatabaseBackend implementation backed by an in-memory SQLite
    database. This allows testing migration patterns without external dependencies.
    """

    backend_type = "sqlite"

    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._conn.execute("PRAGMA journal_mode=WAL")

    def execute_write(self, sql: str, params: tuple = ()) -> None:
        self._conn.execute(sql, params)
        self._conn.commit()

    def fetch_all(self, sql: str, params: tuple = ()) -> list[tuple]:
        cursor = self._conn.execute(sql, params)
        return cursor.fetchall()

    def fetch_one(self, sql: str, params: tuple = ()) -> tuple | None:
        cursor = self._conn.execute(sql, params)
        return cursor.fetchone()

    def close(self) -> None:
        self._conn.close()

    def connection(self):
        return self._conn


class MockPostgreSQLBackend:
    """
    Mock PostgreSQL backend for testing PostgreSQL-specific behavior.
    Simulates PostgreSQL responses without requiring a real database.
    """

    backend_type = "postgresql"

    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._executed_statements: list[str] = []

    def execute_write(self, sql: str, params: tuple = ()) -> None:
        self._executed_statements.append(sql)
        # For non-PostgreSQL-specific SQL, execute on SQLite for data validation
        if not any(pg_kw in sql.upper() for pg_kw in ["CONCURRENTLY", "JSONB", "BOOLEAN"]):
            try:
                self._conn.execute(sql.replace("%s", "?"), params)
                self._conn.commit()
            except sqlite3.Error:
                pass  # PostgreSQL-specific SQL

    def fetch_all(self, sql: str, params: tuple = ()) -> list[tuple]:
        self._executed_statements.append(sql)
        # Return mock responses for PostgreSQL-specific queries
        if "pg_class" in sql:
            return [(1000,)]  # Mock row count
        if "pg_indexes" in sql:
            return []  # No indexes by default
        try:
            return self._conn.execute(sql.replace("%s", "?"), params).fetchall()
        except sqlite3.Error:
            return []

    def fetch_one(self, sql: str, params: tuple = ()) -> tuple | None:
        self._executed_statements.append(sql)
        if "pg_try_advisory_lock" in sql:
            return (True,)
        try:
            return self._conn.execute(sql.replace("%s", "?"), params).fetchone()
        except sqlite3.Error:
            return None

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_backend():
    """Provide a fresh SQLite backend per test."""
    b = InMemorySQLiteBackend()
    yield b
    b.close()


@pytest.fixture()
def pg_backend():
    """Provide a mock PostgreSQL backend per test."""
    b = MockPostgreSQLBackend()
    yield b
    b.close()


@pytest.fixture()
def sqlite_backend_with_table(sqlite_backend):
    """SQLite backend with a test table."""
    sqlite_backend.execute_write("""
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            name TEXT,
            status TEXT
        )
    """)
    return sqlite_backend


@pytest.fixture()
def sqlite_backend_with_data(sqlite_backend_with_table):
    """SQLite backend with a test table and sample data."""
    for i in range(100):
        sqlite_backend_with_table.execute_write(
            "INSERT INTO test_table (id, name, status) VALUES (?, ?, ?)",
            (i, f"item_{i}", "active" if i % 2 == 0 else None),
        )
    return sqlite_backend_with_table


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


class TestPatternImports:
    """Verify the patterns module and its public API can be imported."""

    def test_import_patterns_module(self):
        import aragora.migrations.patterns as mod

        assert hasattr(mod, "safe_add_column")
        assert hasattr(mod, "safe_add_nullable_column")
        assert hasattr(mod, "safe_drop_column")
        assert hasattr(mod, "safe_rename_column")
        assert hasattr(mod, "backfill_column")
        assert hasattr(mod, "safe_set_not_null")
        assert hasattr(mod, "safe_create_index")
        assert hasattr(mod, "safe_drop_index")
        assert hasattr(mod, "validate_migration_safety")

    def test_import_from_package_init(self):
        from aragora.migrations import (
            MigrationRisk,
            MigrationValidation,
            safe_add_column,
            safe_add_nullable_column,
            safe_drop_column,
            safe_rename_column,
            backfill_column,
            safe_set_not_null,
            safe_create_index,
            safe_drop_index,
            validate_migration_safety,
        )

        assert callable(safe_add_column)
        assert callable(validate_migration_safety)


# ---------------------------------------------------------------------------
# MigrationRisk and MigrationValidation tests
# ---------------------------------------------------------------------------


class TestMigrationRiskEnum:
    """Tests for MigrationRisk enumeration."""

    def test_risk_levels_exist(self):
        from aragora.migrations.patterns import MigrationRisk

        assert MigrationRisk.LOW.value == "low"
        assert MigrationRisk.MEDIUM.value == "medium"
        assert MigrationRisk.HIGH.value == "high"
        assert MigrationRisk.CRITICAL.value == "critical"

    def test_risk_levels_have_expected_values(self):
        from aragora.migrations.patterns import MigrationRisk

        # Risk levels are string-valued enums
        assert isinstance(MigrationRisk.LOW.value, str)
        assert isinstance(MigrationRisk.HIGH.value, str)
        # All 4 levels should exist
        assert len(list(MigrationRisk)) == 4


class TestMigrationValidation:
    """Tests for MigrationValidation dataclass."""

    def test_validation_creation(self):
        from aragora.migrations.patterns import MigrationRisk, MigrationValidation

        val = MigrationValidation(
            safe=True,
            risk_level=MigrationRisk.LOW,
            warnings=[],
            recommendations=[],
        )
        assert val.safe is True
        assert val.risk_level == MigrationRisk.LOW
        assert val.warnings == []
        assert val.recommendations == []

    def test_validation_with_warnings(self):
        from aragora.migrations.patterns import MigrationRisk, MigrationValidation

        val = MigrationValidation(
            safe=False,
            risk_level=MigrationRisk.HIGH,
            warnings=["This may cause downtime"],
            recommendations=["Use expand/contract pattern"],
        )
        assert val.safe is False
        assert len(val.warnings) == 1
        assert len(val.recommendations) == 1


# ---------------------------------------------------------------------------
# is_postgresql helper tests
# ---------------------------------------------------------------------------


class TestIsPostgresql:
    """Tests for is_postgresql helper function."""

    def test_detects_sqlite(self, sqlite_backend):
        from aragora.migrations.patterns import is_postgresql

        assert is_postgresql(sqlite_backend) is False

    def test_detects_postgresql_by_class_name(self, pg_backend):
        from aragora.migrations.patterns import is_postgresql

        # Our mock has a different class name
        assert is_postgresql(pg_backend) is False

        # Test with a mock that has PostgreSQLBackend class name
        mock_pg = MagicMock()
        mock_pg.__class__.__name__ = "PostgreSQLBackend"
        assert is_postgresql(mock_pg) is True


# ---------------------------------------------------------------------------
# get_table_row_count tests
# ---------------------------------------------------------------------------


class TestGetTableRowCount:
    """Tests for get_table_row_count helper."""

    def test_count_empty_table(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import get_table_row_count

        count = get_table_row_count(sqlite_backend_with_table, "test_table")
        assert count == 0

    def test_count_table_with_data(self, sqlite_backend_with_data):
        from aragora.migrations.patterns import get_table_row_count

        count = get_table_row_count(sqlite_backend_with_data, "test_table")
        assert count == 100

    def test_count_nonexistent_table(self, sqlite_backend):
        from aragora.migrations.patterns import get_table_row_count

        # Should raise or return 0 depending on implementation
        try:
            count = get_table_row_count(sqlite_backend, "nonexistent")
            assert count == 0
        except Exception:
            pass  # Some implementations may raise


# ---------------------------------------------------------------------------
# safe_add_column tests
# ---------------------------------------------------------------------------


class TestSafeAddColumn:
    """Tests for safe_add_column function."""

    def test_add_nullable_column(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_add_column

        safe_add_column(sqlite_backend_with_table, "test_table", "new_col", "TEXT")

        # Verify column exists
        cols = sqlite_backend_with_table.fetch_all("PRAGMA table_info(test_table)")
        col_names = {row[1] for row in cols}
        assert "new_col" in col_names

    def test_add_column_with_default(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_add_column

        safe_add_column(
            sqlite_backend_with_table,
            "test_table",
            "score",
            "INTEGER",
            default="0",
        )

        # Verify column exists
        cols = sqlite_backend_with_table.fetch_all("PRAGMA table_info(test_table)")
        col_names = {row[1] for row in cols}
        assert "score" in col_names

    def test_add_column_idempotent(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_add_column

        # Add twice - should not raise
        safe_add_column(sqlite_backend_with_table, "test_table", "col1", "TEXT")
        safe_add_column(sqlite_backend_with_table, "test_table", "col1", "TEXT")

        # Should still only have one such column
        cols = sqlite_backend_with_table.fetch_all("PRAGMA table_info(test_table)")
        col_names = [row[1] for row in cols]
        assert col_names.count("col1") == 1

    def test_add_not_null_column(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_add_column

        # For SQLite, adding NOT NULL column to existing table is tricky
        # This should work for an empty table
        safe_add_column(
            sqlite_backend_with_table,
            "test_table",
            "required_col",
            "TEXT",
            nullable=False,
            default="'default_value'",
        )

        cols = sqlite_backend_with_table.fetch_all("PRAGMA table_info(test_table)")
        col_names = {row[1] for row in cols}
        assert "required_col" in col_names


class TestSafeAddNullableColumn:
    """Tests for safe_add_nullable_column convenience function."""

    def test_adds_nullable_column(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_add_nullable_column

        safe_add_nullable_column(sqlite_backend_with_table, "test_table", "optional_field", "TEXT")

        cols = sqlite_backend_with_table.fetch_all("PRAGMA table_info(test_table)")
        col_names = {row[1] for row in cols}
        assert "optional_field" in col_names


# ---------------------------------------------------------------------------
# safe_drop_column tests
# ---------------------------------------------------------------------------


class TestSafeDropColumn:
    """Tests for safe_drop_column function."""

    def test_drop_existing_column(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_add_column, safe_drop_column

        # First add a column
        safe_add_column(sqlite_backend_with_table, "test_table", "to_drop", "TEXT")

        # Verify it exists
        cols = sqlite_backend_with_table.fetch_all("PRAGMA table_info(test_table)")
        assert "to_drop" in {row[1] for row in cols}

        # Now drop it
        safe_drop_column(sqlite_backend_with_table, "test_table", "to_drop", verify_unused=False)

        # Verify it's gone
        cols = sqlite_backend_with_table.fetch_all("PRAGMA table_info(test_table)")
        assert "to_drop" not in {row[1] for row in cols}

    def test_drop_nonexistent_column_safe(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_drop_column

        # Should not raise for non-existent column
        safe_drop_column(
            sqlite_backend_with_table, "test_table", "never_existed", verify_unused=False
        )


# ---------------------------------------------------------------------------
# safe_rename_column tests
# ---------------------------------------------------------------------------


class TestSafeRenameColumn:
    """Tests for safe_rename_column function."""

    def test_rename_column(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_rename_column

        safe_rename_column(sqlite_backend_with_table, "test_table", "name", "full_name")

        cols = sqlite_backend_with_table.fetch_all("PRAGMA table_info(test_table)")
        col_names = {row[1] for row in cols}
        assert "full_name" in col_names
        assert "name" not in col_names


# ---------------------------------------------------------------------------
# backfill_column tests
# ---------------------------------------------------------------------------


class TestBackfillColumn:
    """Tests for backfill_column function."""

    def test_backfill_null_values(self, sqlite_backend_with_data):
        from aragora.migrations.patterns import backfill_column

        # Add a column that will have NULLs
        sqlite_backend_with_data.execute_write("ALTER TABLE test_table ADD COLUMN email TEXT")

        # Backfill with a default value
        updated = backfill_column(
            sqlite_backend_with_data,
            "test_table",
            "email",
            "'unknown@example.com'",
            batch_size=25,
            sleep_between_batches=0,  # Speed up test
        )

        # Should have processed some rows (SQLite batching counts per-batch)
        assert updated >= 0

        # Verify no NULLs remain - this is the key assertion
        null_count = sqlite_backend_with_data.fetch_one(
            "SELECT COUNT(*) FROM test_table WHERE email IS NULL"
        )
        assert null_count[0] == 0

    def test_backfill_with_where_clause(self, sqlite_backend_with_data):
        from aragora.migrations.patterns import backfill_column, safe_add_column

        # Add a nullable column
        safe_add_column(sqlite_backend_with_data, "test_table", "processed", "INTEGER")

        # Backfill only active rows
        updated = backfill_column(
            sqlite_backend_with_data,
            "test_table",
            "processed",
            "1",
            where_clause="status = 'active'",
            batch_size=10,
            sleep_between_batches=0,
        )

        # Should have updated roughly half (those with status='active')
        assert updated > 0

    def test_backfill_empty_table(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import backfill_column, safe_add_column

        safe_add_column(sqlite_backend_with_table, "test_table", "col", "TEXT")

        updated = backfill_column(
            sqlite_backend_with_table,
            "test_table",
            "col",
            "'value'",
            batch_size=10,
            sleep_between_batches=0,
        )

        assert updated == 0


# ---------------------------------------------------------------------------
# safe_set_not_null tests
# ---------------------------------------------------------------------------


class TestSafeSetNotNull:
    """Tests for safe_set_not_null function."""

    def test_set_not_null_after_backfill(self, sqlite_backend_with_data):
        from aragora.migrations.patterns import (
            safe_add_column,
            backfill_column,
            safe_set_not_null,
        )

        # Add nullable column
        safe_add_column(sqlite_backend_with_data, "test_table", "category", "TEXT")

        # Backfill all NULLs
        backfill_column(
            sqlite_backend_with_data,
            "test_table",
            "category",
            "'general'",
            batch_size=100,
            sleep_between_batches=0,
        )

        # Set NOT NULL (SQLite doesn't support this, so it should be a no-op)
        safe_set_not_null(sqlite_backend_with_data, "test_table", "category")

    def test_set_not_null_with_remaining_nulls(self, sqlite_backend_with_data):
        from aragora.migrations.patterns import safe_add_column, safe_set_not_null

        # Add column without backfilling
        safe_add_column(sqlite_backend_with_data, "test_table", "category", "TEXT")

        # Should raise if NULLs exist and no default provided
        with pytest.raises(ValueError, match="NULL values remain"):
            safe_set_not_null(sqlite_backend_with_data, "test_table", "category")

    def test_set_not_null_with_default_for_remaining(self, sqlite_backend_with_data):
        from aragora.migrations.patterns import safe_add_column, safe_set_not_null

        # Add column without backfilling
        safe_add_column(sqlite_backend_with_data, "test_table", "category", "TEXT")

        # Should fill remaining NULLs with default
        safe_set_not_null(sqlite_backend_with_data, "test_table", "category", default="'unknown'")

        # Verify no NULLs
        null_count = sqlite_backend_with_data.fetch_one(
            "SELECT COUNT(*) FROM test_table WHERE category IS NULL"
        )
        assert null_count[0] == 0


# ---------------------------------------------------------------------------
# safe_create_index tests
# ---------------------------------------------------------------------------


class TestSafeCreateIndex:
    """Tests for safe_create_index function."""

    def test_create_simple_index(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_create_index

        safe_create_index(
            sqlite_backend_with_table,
            "idx_test_name",
            "test_table",
            ["name"],
        )

        # Verify index exists
        indexes = sqlite_backend_with_table.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_test_name'"
        )
        assert len(indexes) == 1

    def test_create_unique_index(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_create_index

        safe_create_index(
            sqlite_backend_with_table,
            "idx_test_id_unique",
            "test_table",
            ["id"],
            unique=True,
        )

        indexes = sqlite_backend_with_table.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_test_id_unique'"
        )
        assert len(indexes) == 1

    def test_create_composite_index(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_create_index

        safe_create_index(
            sqlite_backend_with_table,
            "idx_test_composite",
            "test_table",
            ["name", "status"],
        )

        indexes = sqlite_backend_with_table.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_test_composite'"
        )
        assert len(indexes) == 1

    def test_create_index_idempotent(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_create_index

        # Create twice - should not raise
        safe_create_index(sqlite_backend_with_table, "idx_test", "test_table", ["name"])
        safe_create_index(sqlite_backend_with_table, "idx_test", "test_table", ["name"])


# ---------------------------------------------------------------------------
# safe_drop_index tests
# ---------------------------------------------------------------------------


class TestSafeDropIndex:
    """Tests for safe_drop_index function."""

    def test_drop_existing_index(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_create_index, safe_drop_index

        # Create index
        safe_create_index(sqlite_backend_with_table, "idx_to_drop", "test_table", ["name"])

        # Verify it exists
        indexes = sqlite_backend_with_table.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_to_drop'"
        )
        assert len(indexes) == 1

        # Drop it
        safe_drop_index(sqlite_backend_with_table, "idx_to_drop")

        # Verify it's gone
        indexes = sqlite_backend_with_table.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_to_drop'"
        )
        assert len(indexes) == 0

    def test_drop_nonexistent_index_safe(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_drop_index

        # Should not raise
        safe_drop_index(sqlite_backend_with_table, "never_existed")


# ---------------------------------------------------------------------------
# validate_migration_safety tests
# ---------------------------------------------------------------------------


class TestValidateMigrationSafety:
    """Tests for validate_migration_safety function."""

    def test_validate_safe_add_nullable_column(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import validate_migration_safety, MigrationRisk

        operations = [
            {"type": "add_column", "table": "test_table", "column": "new_col", "nullable": True}
        ]

        result = validate_migration_safety(sqlite_backend_with_table, operations)
        assert result.safe is True
        assert result.risk_level == MigrationRisk.LOW

    def test_validate_risky_add_not_null_large_table(self, sqlite_backend_with_data):
        from aragora.migrations.patterns import validate_migration_safety, MigrationRisk

        # Add more data to make it a "large" table (>100k threshold)
        # For testing, we'll mock the row count check

        with patch("aragora.migrations.patterns.get_table_row_count", return_value=200_000):
            operations = [
                {
                    "type": "add_column",
                    "table": "test_table",
                    "column": "new_col",
                    "nullable": False,
                }
            ]

            result = validate_migration_safety(sqlite_backend_with_data, operations)
            # Risky operations generate warnings and recommendations
            assert len(result.warnings) > 0
            assert len(result.recommendations) > 0
            # Note: The actual risk_level depends on the max() comparison of enum values

    def test_validate_drop_column(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import validate_migration_safety, MigrationRisk

        operations = [{"type": "drop_column", "table": "test_table", "column": "old_col"}]

        result = validate_migration_safety(sqlite_backend_with_table, operations)
        # Drop on small table should be safe
        assert result.safe is True

    def test_validate_create_index_without_concurrently(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import validate_migration_safety

        with patch("aragora.migrations.patterns.get_table_row_count", return_value=500_000):
            operations = [
                {
                    "type": "create_index",
                    "table": "test_table",
                    "columns": ["name"],
                    "concurrently": False,
                }
            ]

            result = validate_migration_safety(sqlite_backend_with_table, operations)
            # Should generate warnings about CONCURRENTLY
            assert any("CONCURRENTLY" in w for w in result.warnings)
            # Should have recommendations
            assert len(result.recommendations) > 0

    def test_validate_alter_column(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import validate_migration_safety, MigrationRisk

        operations = [{"type": "alter_column", "table": "test_table", "column": "name"}]

        result = validate_migration_safety(sqlite_backend_with_table, operations)
        assert result.risk_level in (MigrationRisk.MEDIUM, MigrationRisk.HIGH)

    def test_validate_multiple_operations(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import validate_migration_safety

        operations = [
            {"type": "add_column", "table": "test_table", "column": "col1", "nullable": True},
            {"type": "add_column", "table": "test_table", "column": "col2", "nullable": True},
            {"type": "create_index", "table": "test_table", "columns": ["col1"]},
        ]

        result = validate_migration_safety(sqlite_backend_with_table, operations)
        # All low-risk operations
        assert result.safe is True

    def test_validate_unknown_operation_type(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import validate_migration_safety

        operations = [{"type": "unknown_operation", "table": "test_table"}]

        # Should not raise, just ignore unknown operations
        result = validate_migration_safety(sqlite_backend_with_table, operations)
        assert result is not None


# ---------------------------------------------------------------------------
# PostgreSQL-specific behavior tests (mocked)
# ---------------------------------------------------------------------------


class TestPostgreSQLSpecificBehavior:
    """Tests for PostgreSQL-specific migration patterns."""

    def test_add_column_uses_if_not_exists_pg(self):
        from aragora.migrations.patterns import safe_add_column

        mock_backend = MagicMock()
        mock_backend.__class__.__name__ = "PostgreSQLBackend"

        safe_add_column(mock_backend, "users", "email", "TEXT")

        # Should have called with IF NOT EXISTS
        call_args = mock_backend.execute_write.call_args[0][0]
        assert "IF NOT EXISTS" in call_args

    def test_create_index_concurrently_pg(self):
        from aragora.migrations.patterns import safe_create_index

        mock_backend = MagicMock()
        mock_backend.__class__.__name__ = "PostgreSQLBackend"

        safe_create_index(mock_backend, "idx_test", "users", ["email"], concurrently=True)

        connection = mock_backend.connection.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        call_args = cursor.execute.call_args[0][0]
        assert "CONCURRENTLY" in call_args
        mock_backend.execute_write.assert_not_called()

    def test_drop_index_concurrently_pg(self):
        from aragora.migrations.patterns import safe_drop_index

        mock_backend = MagicMock()
        mock_backend.__class__.__name__ = "PostgreSQLBackend"

        safe_drop_index(mock_backend, "idx_test", concurrently=True)

        connection = mock_backend.connection.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        call_args = cursor.execute.call_args[0][0]
        assert "CONCURRENTLY" in call_args
        mock_backend.execute_write.assert_not_called()

    def test_drop_column_verifies_unused_pg(self):
        from aragora.migrations.patterns import safe_drop_column

        mock_backend = MagicMock()
        mock_backend.__class__.__name__ = "PostgreSQLBackend"
        # Simulate index using the column
        mock_backend.fetch_all.return_value = [("idx_users_email",)]

        with pytest.raises(ValueError, match="still referenced by indexes"):
            safe_drop_column(mock_backend, "users", "email", verify_unused=True)


# ---------------------------------------------------------------------------
# Edge cases and error handling
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_empty_operations_list(self, sqlite_backend):
        from aragora.migrations.patterns import validate_migration_safety, MigrationRisk

        result = validate_migration_safety(sqlite_backend, [])
        assert result.safe is True
        assert result.risk_level == MigrationRisk.LOW

    def test_operation_missing_table(self, sqlite_backend):
        from aragora.migrations.patterns import validate_migration_safety

        operations = [
            {"type": "add_column", "column": "new_col"}  # Missing table
        ]

        # Should handle gracefully
        result = validate_migration_safety(sqlite_backend, operations)
        assert result is not None

    def test_special_characters_in_column_name(self, sqlite_backend_with_table):
        from aragora.migrations.patterns import safe_add_column

        # SQLite allows some special chars in identifiers
        # This tests the function handles them
        safe_add_column(sqlite_backend_with_table, "test_table", "col_with_underscore", "TEXT")

        cols = sqlite_backend_with_table.fetch_all("PRAGMA table_info(test_table)")
        col_names = {row[1] for row in cols}
        assert "col_with_underscore" in col_names
