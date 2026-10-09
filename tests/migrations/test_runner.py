"""
Tests for aragora.migrations.runner module.

Covers:
- Migration dataclass validation
- MigrationRunner lifecycle (register, upgrade, downgrade, status)
- SQL-based and Python function-based migrations
- Target version support for partial upgrade/downgrade
- Edge cases (empty state, duplicate register, failed migrations)
- Module import verification

Run with:
    python -m pytest tests/migrations/test_runner.py -v --noconftest --timeout=30
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: lightweight in-memory SQLite backend that satisfies DatabaseBackend
# ---------------------------------------------------------------------------


class InMemorySQLiteBackend:
    """
    Minimal DatabaseBackend implementation backed by an in-memory SQLite
    database.  This avoids importing aragora.storage.backends (which may
    pull in heavy optional dependencies) while faithfully exercising the
    MigrationRunner logic.
    """

    backend_type = "sqlite"

    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._conn.execute("PRAGMA journal_mode=WAL")

    # -- DatabaseBackend interface ------------------------------------------

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


# ---------------------------------------------------------------------------
# Fixtures (pytest-style, no conftest needed)
# ---------------------------------------------------------------------------


@pytest.fixture()
def backend():
    """Provide a fresh in-memory SQLite backend per test."""
    b = InMemorySQLiteBackend()
    yield b
    b.close()


@pytest.fixture()
def runner(backend):
    """Provide a MigrationRunner wired to the in-memory backend."""
    from aragora.migrations.runner import MigrationRunner

    return MigrationRunner(backend=backend)


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


class TestImports:
    """Verify the migrations module and its public API can be imported."""

    def test_import_runner_module(self):
        import aragora.migrations.runner as mod

        assert hasattr(mod, "Migration")
        assert hasattr(mod, "MigrationRunner")

    def test_import_package_init(self):
        from aragora.migrations import (
            Migration,
            MigrationRunner,
            apply_migrations,
            get_migration_runner,
            get_migration_status,
            rollback_migration,
        )

        assert Migration is not None
        assert MigrationRunner is not None
        assert callable(apply_migrations)
        assert callable(get_migration_runner)
        assert callable(get_migration_status)
        assert callable(rollback_migration)

    def test_import_versions_package(self):
        import aragora.migrations.versions

        assert aragora.migrations.versions is not None

    def test_import_main_module(self):
        import aragora.migrations.__main__ as mod

        assert hasattr(mod, "main")


# ---------------------------------------------------------------------------
# Migration dataclass tests
# ---------------------------------------------------------------------------


class TestMigrationDataclass:
    """Tests for the Migration dataclass itself."""

    def test_create_with_up_sql(self):
        from aragora.migrations.runner import Migration

        m = Migration(version=1, name="test", up_sql="CREATE TABLE t(id INT)")
        assert m.version == 1
        assert m.name == "test"
        assert m.up_sql is not None
        assert m.down_sql is None
        assert m.up_fn is None
        assert m.down_fn is None

    def test_create_with_up_fn(self):
        from aragora.migrations.runner import Migration

        fn = lambda backend: None  # noqa: E731
        m = Migration(version=2, name="fn-based", up_fn=fn)
        assert m.up_fn is fn

    def test_create_with_both_sql_and_fn(self):
        from aragora.migrations.runner import Migration

        fn = lambda backend: None  # noqa: E731
        m = Migration(version=3, name="both", up_sql="SELECT 1", up_fn=fn)
        assert m.up_sql is not None
        assert m.up_fn is not None

    def test_create_without_up_raises(self):
        from aragora.migrations.runner import Migration

        with pytest.raises(ValueError, match="must have up_sql or up_fn"):
            Migration(version=4, name="bad")

    def test_down_sql_optional(self):
        from aragora.migrations.runner import Migration

        m = Migration(version=5, name="no-down", up_sql="SELECT 1")
        assert m.down_sql is None
        assert m.down_fn is None

    def test_down_fn_only(self):
        from aragora.migrations.runner import Migration

        fn = lambda backend: None  # noqa: E731
        m = Migration(version=6, name="down-fn", up_sql="SELECT 1", down_fn=fn)
        assert m.down_fn is fn


class TestPreviousChecksums:
    """verify_checksums accepts checksums that earlier revisions recorded."""

    @staticmethod
    def _record_applied(runner, backend, migration, stored_checksum):
        runner.register(migration)
        backend.execute_write(
            "INSERT INTO _aragora_migrations (version, name, checksum) VALUES (?, ?, ?)",
            (migration.version, migration.name, stored_checksum),
        )

    def test_previous_checksum_verifies(self, runner, backend):
        from aragora.migrations.runner import Migration

        m = Migration(version=1, name="t", up_sql="SELECT 1", previous_checksums=("old",))
        self._record_applied(runner, backend, m, "old")

        assert runner.verify_checksums() == []

    def test_other_checksums_still_mismatch(self, runner, backend):
        from aragora.migrations.runner import Migration

        m = Migration(version=1, name="t", up_sql="SELECT 1", previous_checksums=("old",))
        self._record_applied(runner, backend, m, "edited")

        assert runner.verify_checksums() == [(1, "edited", m.compute_checksum())]

    def test_upgrade_records_the_current_checksum(self, runner, backend):
        from aragora.migrations.runner import Migration

        m = Migration(version=1, name="t", up_sql="SELECT 1", previous_checksums=("old",))
        runner.register(m)
        runner.upgrade()

        row = backend.fetch_one("SELECT checksum FROM _aragora_migrations WHERE version = 1")
        assert row == (m.compute_checksum(),)


# ---------------------------------------------------------------------------
# MigrationRunner core lifecycle
# ---------------------------------------------------------------------------


class TestMigrationRunnerInit:
    """Runner initialisation and migrations table creation."""

    def test_creates_migrations_table(self, backend, runner):
        rows = backend.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            ("_aragora_migrations",),
        )
        assert len(rows) == 1

    def test_migrations_table_has_columns(self, backend, runner):
        cursor = backend._conn.execute("PRAGMA table_info(_aragora_migrations)")
        cols = {row[1] for row in cursor.fetchall()}
        assert "version" in cols
        assert "name" in cols
        assert "applied_at" in cols


class TestRegister:
    """Test migration registration."""

    def test_register_single(self, runner):
        from aragora.migrations.runner import Migration

        m = Migration(version=100, name="first", up_sql="SELECT 1")
        runner.register(m)
        assert len(runner._migrations) == 1

    def test_register_sorted_by_version(self, runner):
        from aragora.migrations.runner import Migration

        runner.register(Migration(version=300, name="c", up_sql="SELECT 1"))
        runner.register(Migration(version=100, name="a", up_sql="SELECT 1"))
        runner.register(Migration(version=200, name="b", up_sql="SELECT 1"))
        versions = [m.version for m in runner._migrations]
        assert versions == [100, 200, 300]


# ---------------------------------------------------------------------------
# Upgrade (apply) tests
# ---------------------------------------------------------------------------


class TestUpgrade:
    """Test the upgrade / apply path."""

    def _make_migration(self, version, name, up_sql, down_sql=None):
        from aragora.migrations.runner import Migration

        return Migration(version=version, name=name, up_sql=up_sql, down_sql=down_sql)

    def test_upgrade_applies_single(self, runner, backend):
        m = self._make_migration(1, "create_t1", "CREATE TABLE t1 (id INTEGER PRIMARY KEY)")
        runner.register(m)
        applied = runner.upgrade()
        assert len(applied) == 1
        assert applied[0].version == 1

        # Table should exist
        rows = backend.fetch_all("SELECT name FROM sqlite_master WHERE type='table' AND name='t1'")
        assert len(rows) == 1

    def test_upgrade_records_in_tracking_table(self, runner, backend):
        m = self._make_migration(1, "first", "SELECT 1")
        runner.register(m)
        runner.upgrade()

        rows = backend.fetch_all("SELECT version, name FROM _aragora_migrations")
        assert len(rows) == 1
        assert rows[0][0] == 1
        assert rows[0][1] == "first"

    def test_upgrade_applies_multiple_in_order(self, runner, backend):
        runner.register(self._make_migration(2, "second", "CREATE TABLE t2 (id INT)"))
        runner.register(self._make_migration(1, "first", "CREATE TABLE t1 (id INT)"))
        applied = runner.upgrade()
        assert [m.version for m in applied] == [1, 2]

    def test_upgrade_skips_already_applied(self, runner, backend):
        m = self._make_migration(1, "only-once", "SELECT 1")
        runner.register(m)
        runner.upgrade()
        applied_again = runner.upgrade()
        assert len(applied_again) == 0

    def test_upgrade_with_target_version(self, runner, backend):
        runner.register(self._make_migration(1, "a", "SELECT 1"))
        runner.register(self._make_migration(2, "b", "SELECT 1"))
        runner.register(self._make_migration(3, "c", "SELECT 1"))

        applied = runner.upgrade(target_version=2)
        assert [m.version for m in applied] == [1, 2]

        # Version 3 should still be pending
        pending = runner.get_pending_migrations()
        assert len(pending) == 1
        assert pending[0].version == 3

    def test_upgrade_with_multi_statement_sql(self, runner, backend):
        sql = "CREATE TABLE t1 (id INT); CREATE TABLE t2 (id INT)"
        m = self._make_migration(1, "multi", sql)
        runner.register(m)
        runner.upgrade()

        for table in ["t1", "t2"]:
            rows = backend.fetch_all(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            assert len(rows) == 1, f"Table {table} not found"

    def test_upgrade_with_up_fn(self, runner, backend):
        from aragora.migrations.runner import Migration

        def up(be):
            be.execute_write("CREATE TABLE fn_table (id INTEGER PRIMARY KEY)")

        m = Migration(version=1, name="fn-based", up_fn=up)
        runner.register(m)
        runner.upgrade()

        rows = backend.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='fn_table'"
        )
        assert len(rows) == 1

    def test_upgrade_prefers_up_fn_over_up_sql(self, runner, backend):
        """When both up_fn and up_sql are set, up_fn takes precedence."""
        from aragora.migrations.runner import Migration

        call_log = []

        def up(be):
            call_log.append("fn")
            be.execute_write("CREATE TABLE fn_wins (id INT)")

        m = Migration(
            version=1,
            name="both",
            up_sql="CREATE TABLE sql_wins (id INT)",
            up_fn=up,
        )
        runner.register(m)
        runner.upgrade()

        assert "fn" in call_log
        # fn_wins should exist, sql_wins should not
        assert (
            len(
                backend.fetch_all(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='fn_wins'"
                )
            )
            == 1
        )
        assert (
            len(
                backend.fetch_all(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='sql_wins'"
                )
            )
            == 0
        )

    def test_upgrade_raises_on_error(self, runner):
        from aragora.migrations.runner import Migration

        def bad_up(be):
            raise RuntimeError("boom")

        m = Migration(version=1, name="fail", up_fn=bad_up)
        runner.register(m)

        with pytest.raises(RuntimeError, match="boom"):
            runner.upgrade()

    def test_no_pending_returns_empty(self, runner):
        applied = runner.upgrade()
        assert applied == []


# ---------------------------------------------------------------------------
# Downgrade (rollback) tests
# ---------------------------------------------------------------------------


class TestDowngrade:
    """Test the downgrade / rollback path."""

    def _make_migration(self, version, name, up_sql="SELECT 1", down_sql=None, down_fn=None):
        from aragora.migrations.runner import Migration

        return Migration(
            version=version,
            name=name,
            up_sql=up_sql,
            down_sql=down_sql,
            down_fn=down_fn,
        )

    def test_downgrade_rolls_back_one_by_default(self, runner, backend):
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.register(self._make_migration(2, "b", down_sql="SELECT 1"))
        runner.upgrade()

        rolled = runner.downgrade()
        assert len(rolled) == 1
        assert rolled[0].version == 2

        applied = runner.get_applied_versions()
        assert 1 in applied
        assert 2 not in applied

    def test_downgrade_with_target_version(self, runner, backend):
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.register(self._make_migration(2, "b", down_sql="SELECT 1"))
        runner.register(self._make_migration(3, "c", down_sql="SELECT 1"))
        runner.upgrade()

        rolled = runner.downgrade(target_version=1)
        assert len(rolled) == 2
        versions_rolled = {m.version for m in rolled}
        assert versions_rolled == {2, 3}

        applied = runner.get_applied_versions()
        assert applied == {1}

    def test_downgrade_executes_down_sql(self, runner, backend):
        runner.register(
            self._make_migration(
                1,
                "create",
                up_sql="CREATE TABLE d1 (id INT)",
                down_sql="DROP TABLE d1",
            )
        )
        runner.upgrade()

        # Table exists after upgrade
        assert (
            len(
                backend.fetch_all("SELECT name FROM sqlite_master WHERE type='table' AND name='d1'")
            )
            == 1
        )

        runner.downgrade()

        # Table gone after downgrade
        assert (
            len(
                backend.fetch_all("SELECT name FROM sqlite_master WHERE type='table' AND name='d1'")
            )
            == 0
        )

    def test_downgrade_executes_down_fn(self, runner, backend):
        from aragora.migrations.runner import Migration

        call_log = []

        def down(be):
            call_log.append("down_called")

        m = Migration(version=1, name="fn-down", up_sql="SELECT 1", down_fn=down)
        runner.register(m)
        runner.upgrade()
        runner.downgrade()

        assert "down_called" in call_log

    def test_downgrade_removes_tracking_record(self, runner, backend):
        runner.register(self._make_migration(1, "tracked", down_sql="SELECT 1"))
        runner.upgrade()
        assert runner.get_applied_versions() == {1}

        runner.downgrade()
        assert runner.get_applied_versions() == set()

    def test_downgrade_stops_if_no_down(self, runner, backend):
        """Migrations without down_sql/down_fn cannot be rolled back."""
        runner.register(self._make_migration(1, "no-down"))
        runner.upgrade()

        rolled = runner.downgrade()
        assert len(rolled) == 0
        # Still applied
        assert 1 in runner.get_applied_versions()

    def test_downgrade_empty_state(self, runner):
        rolled = runner.downgrade()
        assert rolled == []

    def test_downgrade_raises_on_error(self, runner):
        from aragora.migrations.runner import Migration

        def bad_down(be):
            raise RuntimeError("rollback boom")

        m = Migration(version=1, name="fail-down", up_sql="SELECT 1", down_fn=bad_down)
        runner.register(m)
        runner.upgrade()

        with pytest.raises(RuntimeError, match="rollback boom"):
            runner.downgrade()


# ---------------------------------------------------------------------------
# Status tests
# ---------------------------------------------------------------------------


class TestStatus:
    """Test the status reporting method."""

    def _make_migration(self, version, name):
        from aragora.migrations.runner import Migration

        return Migration(version=version, name=name, up_sql="SELECT 1", down_sql="SELECT 1")

    def test_status_empty(self, runner):
        s = runner.status()
        assert s["applied_count"] == 0
        assert s["pending_count"] == 0
        assert s["applied_versions"] == []
        assert s["pending_versions"] == []
        assert s["latest_applied"] is None
        assert s["latest_available"] is None

    def test_status_with_registered_only(self, runner):
        runner.register(self._make_migration(1, "a"))
        runner.register(self._make_migration(2, "b"))
        s = runner.status()
        assert s["applied_count"] == 0
        assert s["pending_count"] == 2
        assert s["pending_versions"] == [1, 2]
        assert s["latest_available"] == 2

    def test_status_all_applied(self, runner):
        runner.register(self._make_migration(1, "a"))
        runner.register(self._make_migration(2, "b"))
        runner.upgrade()

        s = runner.status()
        assert s["applied_count"] == 2
        assert s["pending_count"] == 0
        assert s["applied_versions"] == [1, 2]
        assert s["latest_applied"] == 2
        assert s["latest_available"] == 2

    def test_status_partial(self, runner):
        runner.register(self._make_migration(1, "a"))
        runner.register(self._make_migration(2, "b"))
        runner.register(self._make_migration(3, "c"))
        runner.upgrade(target_version=2)

        s = runner.status()
        assert s["applied_count"] == 2
        assert s["pending_count"] == 1
        assert s["pending_versions"] == [3]
        assert s["latest_applied"] == 2


# ---------------------------------------------------------------------------
# get_applied_versions / get_pending_migrations
# ---------------------------------------------------------------------------


class TestVersionQueries:
    def test_get_applied_versions_empty(self, runner):
        assert runner.get_applied_versions() == set()

    def test_get_pending_migrations_all_pending(self, runner):
        from aragora.migrations.runner import Migration

        runner.register(Migration(version=1, name="a", up_sql="SELECT 1"))
        runner.register(Migration(version=2, name="b", up_sql="SELECT 1"))
        pending = runner.get_pending_migrations()
        assert len(pending) == 2

    def test_pending_excludes_applied(self, runner):
        from aragora.migrations.runner import Migration

        runner.register(Migration(version=1, name="a", up_sql="SELECT 1"))
        runner.register(Migration(version=2, name="b", up_sql="SELECT 1"))
        runner.upgrade(target_version=1)

        pending = runner.get_pending_migrations()
        assert len(pending) == 1
        assert pending[0].version == 2


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_does_not_raise(self, runner):
        runner.close()
        # Calling again should not raise either (sqlite allows it)


# ---------------------------------------------------------------------------
# Full round-trip lifecycle
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """End-to-end: register -> upgrade -> verify -> downgrade -> verify."""

    def test_full_lifecycle(self, backend):
        from aragora.migrations.runner import Migration, MigrationRunner

        runner = MigrationRunner(backend=backend)

        m1 = Migration(
            version=1,
            name="create users",
            up_sql="CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)",
            down_sql="DROP TABLE users",
        )
        m2 = Migration(
            version=2,
            name="create posts",
            up_sql="CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER, body TEXT)",
            down_sql="DROP TABLE posts",
        )

        runner.register(m1)
        runner.register(m2)

        # Status before
        s = runner.status()
        assert s["pending_count"] == 2
        assert s["applied_count"] == 0

        # Upgrade all
        applied = runner.upgrade()
        assert len(applied) == 2

        # Insert some data to prove tables are real
        backend.execute_write("INSERT INTO users (id, name) VALUES (1, 'alice')")
        backend.execute_write("INSERT INTO posts (id, user_id, body) VALUES (1, 1, 'hello')")

        # Status after upgrade
        s = runner.status()
        assert s["applied_count"] == 2
        assert s["pending_count"] == 0

        # Downgrade one
        rolled = runner.downgrade()
        assert len(rolled) == 1
        assert rolled[0].version == 2

        # posts table should be gone
        rows = backend.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='posts'"
        )
        assert len(rows) == 0

        # users table should still exist
        rows = backend.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        )
        assert len(rows) == 1

        # Downgrade the rest
        rolled = runner.downgrade()
        assert len(rolled) == 1
        assert rolled[0].version == 1

        # All clean
        s = runner.status()
        assert s["applied_count"] == 0
        assert s["pending_count"] == 2


# ---------------------------------------------------------------------------
# Global helper functions (with mocked backend to avoid file-system side effects)
# ---------------------------------------------------------------------------


class TestGlobalHelpers:
    """Tests for module-level convenience functions (reset_runner, etc.)."""

    def test_reset_runner(self):
        from aragora.migrations.runner import reset_runner, _runner

        # Just verify it doesn't blow up
        reset_runner()

    def test_reset_runner_clears_global(self):
        import aragora.migrations.runner as mod

        # Set a mock runner
        mock = MagicMock()
        mod._runner = mock
        mod.reset_runner()
        assert mod._runner is None
        mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Edge cases and error paths
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Miscellaneous edge-case coverage."""

    def test_upgrade_idempotent_if_not_exists(self, runner, backend):
        """CREATE TABLE IF NOT EXISTS should be safe to re-run."""
        from aragora.migrations.runner import Migration

        m = Migration(
            version=1,
            name="idempotent",
            up_sql="CREATE TABLE IF NOT EXISTS safe_t (id INT)",
        )
        runner.register(m)
        runner.upgrade()

        # Manually execute the same SQL again (simulating a bug or re-entry)
        backend.execute_write("CREATE TABLE IF NOT EXISTS safe_t (id INT)")

    def test_multi_statement_down_sql(self, runner, backend):
        from aragora.migrations.runner import Migration

        m = Migration(
            version=1,
            name="multi-down",
            up_sql="CREATE TABLE a1 (id INT); CREATE TABLE a2 (id INT)",
            down_sql="DROP TABLE a1; DROP TABLE a2",
        )
        runner.register(m)
        runner.upgrade()
        runner.downgrade()

        for t in ["a1", "a2"]:
            rows = backend.fetch_all(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)
            )
            assert len(rows) == 0, f"Table {t} should have been dropped"

    def test_version_as_timestamp(self, runner, backend):
        """Ensure large timestamp-style versions work with SQLite INTEGER."""
        from aragora.migrations.runner import Migration

        m = Migration(version=20260129120000, name="timestamp-version", up_sql="SELECT 1")
        runner.register(m)
        runner.upgrade()

        applied = runner.get_applied_versions()
        assert 20260129120000 in applied

    def test_concurrent_register_ordering(self, runner):
        """Registering in any order always produces sorted list."""
        from aragora.migrations.runner import Migration

        versions = [50, 10, 30, 20, 40]
        for v in versions:
            runner.register(Migration(version=v, name=f"m{v}", up_sql="SELECT 1"))

        result_versions = [m.version for m in runner._migrations]
        assert result_versions == sorted(versions)


# ---------------------------------------------------------------------------
# Advisory locking tests
# ---------------------------------------------------------------------------


class TestAdvisoryLocking:
    """Tests for advisory lock functionality."""

    def test_acquire_lock_sqlite_always_succeeds(self, runner):
        """SQLite doesn't use advisory locks, should return True immediately."""
        result = runner._acquire_migration_lock(timeout_seconds=1.0)
        assert result is True

    def test_release_lock_sqlite_noop(self, runner):
        """SQLite release lock should be a no-op (no exception)."""
        runner._release_migration_lock()  # Should not raise

    def test_get_applied_by(self, runner):
        """Test _get_applied_by returns hostname:pid format."""
        applied_by = runner._get_applied_by()
        assert ":" in applied_by
        # Should contain process ID
        import os

        assert str(os.getpid()) in applied_by


class TestAppliedByTracking:
    """Tests for applied_by metadata tracking."""

    def test_upgrade_records_applied_by(self, runner, backend):
        """Upgrade should record applied_by in tracking table."""
        from aragora.migrations.runner import Migration

        m = Migration(version=1, name="test", up_sql="SELECT 1")
        runner.register(m)
        runner.upgrade()

        # Check applied_by was recorded
        rows = backend.fetch_all(
            "SELECT version, name, applied_by FROM _aragora_migrations WHERE version = ?",
            (1,),
        )
        assert len(rows) == 1
        version, name, applied_by = rows[0]
        assert version == 1
        assert name == "test"
        # applied_by should have hostname:pid format
        assert applied_by is not None
        assert ":" in applied_by


class TestMigrationLockingBehavior:
    """Tests for locking behavior during migrations."""

    def test_upgrade_acquires_and_releases_lock(self, backend):
        """Test that upgrade acquires lock before and releases after."""
        from aragora.migrations.runner import Migration, MigrationRunner

        runner = MigrationRunner(backend=backend)

        # Track lock operations
        lock_operations = []
        original_acquire = runner._acquire_migration_lock
        original_release = runner._release_migration_lock

        def mock_acquire(timeout_seconds=30.0):
            lock_operations.append("acquire")
            return original_acquire(timeout_seconds)

        def mock_release():
            lock_operations.append("release")
            return original_release()

        runner._acquire_migration_lock = mock_acquire
        runner._release_migration_lock = mock_release

        m = Migration(version=1, name="test", up_sql="SELECT 1")
        runner.register(m)
        runner.upgrade()

        # Should have acquired then released
        assert lock_operations == ["acquire", "release"]

    def test_downgrade_acquires_and_releases_lock(self, backend):
        """Test that downgrade acquires lock before and releases after."""
        from aragora.migrations.runner import Migration, MigrationRunner

        runner = MigrationRunner(backend=backend)

        m = Migration(version=1, name="test", up_sql="SELECT 1", down_sql="SELECT 1")
        runner.register(m)
        runner.upgrade()

        # Track lock operations
        lock_operations = []
        original_acquire = runner._acquire_migration_lock
        original_release = runner._release_migration_lock

        def mock_acquire(timeout_seconds=30.0):
            lock_operations.append("acquire")
            return original_acquire(timeout_seconds)

        def mock_release():
            lock_operations.append("release")
            return original_release()

        runner._acquire_migration_lock = mock_acquire
        runner._release_migration_lock = mock_release

        runner.downgrade()

        # Should have acquired then released
        assert lock_operations == ["acquire", "release"]

    def test_lock_released_on_error(self, backend):
        """Test that lock is released even when migration fails."""
        from aragora.migrations.runner import Migration, MigrationRunner

        runner = MigrationRunner(backend=backend)

        lock_released = []

        original_release = runner._release_migration_lock

        def mock_release():
            lock_released.append(True)
            return original_release()

        runner._release_migration_lock = mock_release

        def bad_up(be):
            raise RuntimeError("boom")

        m = Migration(version=1, name="fail", up_fn=bad_up)
        runner.register(m)

        with pytest.raises(RuntimeError, match="boom"):
            runner.upgrade()

        # Lock should still be released
        assert len(lock_released) == 1

    def test_no_lock_for_empty_pending(self, backend):
        """Test that lock is not acquired when no migrations pending."""
        from aragora.migrations.runner import MigrationRunner

        runner = MigrationRunner(backend=backend)

        lock_acquired = []
        original_acquire = runner._acquire_migration_lock

        def mock_acquire(timeout_seconds=30.0):
            lock_acquired.append(True)
            return original_acquire(timeout_seconds)

        runner._acquire_migration_lock = mock_acquire

        # No migrations registered, upgrade should return early
        applied = runner.upgrade()

        assert applied == []
        assert len(lock_acquired) == 0  # Lock not acquired


class TestMigrationTableSchema:
    """Tests for the migration tracking table schema."""

    def test_migrations_table_has_applied_by_column(self, backend, runner):
        """Verify the migrations table has the applied_by column."""
        cursor = backend._conn.execute("PRAGMA table_info(_aragora_migrations)")
        cols = {row[1] for row in cursor.fetchall()}
        assert "version" in cols
        assert "name" in cols
        assert "applied_at" in cols
        assert "applied_by" in cols


# ---------------------------------------------------------------------------
# Rollback history table tests
# ---------------------------------------------------------------------------


class TestRollbackHistoryTable:
    """Tests for the rollback history table creation."""

    def test_rollback_history_table_created(self, backend, runner):
        """Verify the rollback history table is created on init."""
        rows = backend.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            ("_aragora_rollback_history",),
        )
        assert len(rows) == 1

    def test_rollback_history_table_has_columns(self, backend, runner):
        """Verify the rollback history table has expected columns."""
        cursor = backend._conn.execute("PRAGMA table_info(_aragora_rollback_history)")
        cols = {row[1] for row in cursor.fetchall()}
        assert "id" in cols
        assert "version" in cols
        assert "name" in cols
        assert "rolled_back_at" in cols
        assert "rolled_back_by" in cols
        assert "reason" in cols


# ---------------------------------------------------------------------------
# Downgrade dry-run tests
# ---------------------------------------------------------------------------


class TestDowngradeDryRun:
    """Tests for dry-run rollback support."""

    def _make_migration(self, version, name, up_sql="SELECT 1", down_sql=None, down_fn=None):
        from aragora.migrations.runner import Migration

        return Migration(
            version=version,
            name=name,
            up_sql=up_sql,
            down_sql=down_sql,
            down_fn=down_fn,
        )

    def test_dry_run_returns_candidates(self, runner, backend):
        """Dry-run should return what would be rolled back without executing."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.register(self._make_migration(2, "b", down_sql="SELECT 1"))
        runner.upgrade()

        rolled = runner.downgrade(dry_run=True)
        assert len(rolled) == 1
        assert rolled[0].version == 2

        # Nothing should have actually been rolled back
        applied = runner.get_applied_versions()
        assert 1 in applied
        assert 2 in applied

    def test_dry_run_with_target_version(self, runner, backend):
        """Dry-run with target_version should preview multi-step rollback."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.register(self._make_migration(2, "b", down_sql="SELECT 1"))
        runner.register(self._make_migration(3, "c", down_sql="SELECT 1"))
        runner.upgrade()

        rolled = runner.downgrade(target_version=1, dry_run=True)
        assert len(rolled) == 2
        versions = {m.version for m in rolled}
        assert versions == {2, 3}

        # Nothing actually rolled back
        assert runner.get_applied_versions() == {1, 2, 3}

    def test_dry_run_stops_at_no_rollback(self, runner, backend):
        """Dry-run should stop if migration has no rollback defined."""
        runner.register(self._make_migration(1, "a"))  # No down_sql
        runner.upgrade()

        rolled = runner.downgrade(dry_run=True)
        assert len(rolled) == 0

    def test_dry_run_does_not_acquire_lock(self, backend):
        """Dry-run should not acquire advisory lock."""
        from aragora.migrations.runner import Migration, MigrationRunner

        runner = MigrationRunner(backend=backend)
        lock_acquired = []

        original_acquire = runner._acquire_migration_lock

        def mock_acquire(timeout_seconds=30.0):
            lock_acquired.append(True)
            return original_acquire(timeout_seconds)

        runner._acquire_migration_lock = mock_acquire

        m = Migration(version=1, name="test", up_sql="SELECT 1", down_sql="SELECT 1")
        runner.register(m)
        runner.upgrade()

        lock_acquired.clear()
        runner.downgrade(dry_run=True)
        assert len(lock_acquired) == 0


# ---------------------------------------------------------------------------
# Rollback steps tests
# ---------------------------------------------------------------------------


class TestRollbackSteps:
    """Tests for the rollback_steps method."""

    def _make_migration(self, version, name, up_sql="SELECT 1", down_sql=None, down_fn=None):
        from aragora.migrations.runner import Migration

        return Migration(
            version=version,
            name=name,
            up_sql=up_sql,
            down_sql=down_sql,
            down_fn=down_fn,
        )

    def test_rollback_one_step(self, runner, backend):
        """Rolling back 1 step should rollback the latest migration."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.register(self._make_migration(2, "b", down_sql="SELECT 1"))
        runner.register(self._make_migration(3, "c", down_sql="SELECT 1"))
        runner.upgrade()

        rolled = runner.rollback_steps(steps=1)
        assert len(rolled) == 1
        assert rolled[0].version == 3

        applied = runner.get_applied_versions()
        assert applied == {1, 2}

    def test_rollback_two_steps(self, runner, backend):
        """Rolling back 2 steps should rollback the last 2 migrations."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.register(self._make_migration(2, "b", down_sql="SELECT 1"))
        runner.register(self._make_migration(3, "c", down_sql="SELECT 1"))
        runner.upgrade()

        rolled = runner.rollback_steps(steps=2)
        assert len(rolled) == 2
        versions = {m.version for m in rolled}
        assert versions == {2, 3}

        applied = runner.get_applied_versions()
        assert applied == {1}

    def test_rollback_all_steps(self, runner, backend):
        """Rolling back all steps should remove all migrations."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.register(self._make_migration(2, "b", down_sql="SELECT 1"))
        runner.upgrade()

        rolled = runner.rollback_steps(steps=2)
        assert len(rolled) == 2

        applied = runner.get_applied_versions()
        assert applied == set()

    def test_rollback_more_steps_than_applied(self, runner, backend):
        """Rolling back more steps than applied should rollback all."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.register(self._make_migration(2, "b", down_sql="SELECT 1"))
        runner.upgrade()

        rolled = runner.rollback_steps(steps=10)
        assert len(rolled) == 2
        assert runner.get_applied_versions() == set()

    def test_rollback_steps_zero_raises(self, runner):
        """Steps < 1 should raise ValueError."""
        with pytest.raises(ValueError, match="steps must be >= 1"):
            runner.rollback_steps(steps=0)

    def test_rollback_steps_negative_raises(self, runner):
        """Negative steps should raise ValueError."""
        with pytest.raises(ValueError, match="steps must be >= 1"):
            runner.rollback_steps(steps=-1)

    def test_rollback_steps_empty_state(self, runner):
        """Rolling back with no migrations applied returns empty list."""
        rolled = runner.rollback_steps(steps=1)
        assert rolled == []

    def test_rollback_steps_dry_run(self, runner, backend):
        """Dry-run should preview without executing."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.register(self._make_migration(2, "b", down_sql="SELECT 1"))
        runner.upgrade()

        rolled = runner.rollback_steps(steps=1, dry_run=True)
        assert len(rolled) == 1
        assert rolled[0].version == 2

        # Nothing actually rolled back
        assert runner.get_applied_versions() == {1, 2}

    def test_rollback_steps_with_reason(self, runner, backend):
        """Reason should be stored in rollback history."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.upgrade()

        runner.rollback_steps(steps=1, reason="Bug in migration 1")

        history = runner.get_rollback_history()
        assert len(history) == 1
        assert history[0].version == 1
        assert history[0].reason == "Bug in migration 1"


# ---------------------------------------------------------------------------
# Rollback validation tests
# ---------------------------------------------------------------------------


class TestValidateRollback:
    """Tests for the validate_rollback method."""

    def _make_migration(self, version, name, up_sql="SELECT 1", down_sql=None, down_fn=None):
        from aragora.migrations.runner import Migration

        return Migration(
            version=version,
            name=name,
            up_sql=up_sql,
            down_sql=down_sql,
            down_fn=down_fn,
        )

    def test_validate_no_applied_migrations(self, runner):
        """Validation should fail when no migrations are applied."""
        validation = runner.validate_rollback()
        assert validation.safe is False
        assert len(validation.errors) == 1
        assert "No migrations have been applied" in validation.errors[0]

    def test_validate_with_down_sql(self, runner, backend):
        """Validation should pass when migrations have down_sql."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.upgrade()

        validation = runner.validate_rollback()
        assert validation.safe is True
        assert validation.errors == []
        assert 1 in validation.migrations_to_rollback

    def test_validate_with_down_fn(self, runner, backend):
        """Validation should pass when migrations have down_fn."""
        from aragora.migrations.runner import Migration

        fn = lambda be: None  # noqa: E731
        runner.register(Migration(version=1, name="a", up_sql="SELECT 1", down_fn=fn))
        runner.upgrade()

        validation = runner.validate_rollback()
        assert validation.safe is True

    def test_validate_without_rollback_fails(self, runner, backend):
        """Validation should fail when migration has no rollback."""
        runner.register(self._make_migration(1, "a"))  # No down_sql or down_fn
        runner.upgrade()

        validation = runner.validate_rollback()
        assert validation.safe is False
        assert any("no rollback defined" in e for e in validation.errors)

    def test_validate_target_version_too_high(self, runner, backend):
        """Validation should fail when target >= current version."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.upgrade()

        validation = runner.validate_rollback(target_version=1)
        assert validation.safe is False
        assert any("must be less than" in e for e in validation.errors)

    def test_validate_negative_target_version(self, runner, backend):
        """Validation should fail for negative target version."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.upgrade()

        validation = runner.validate_rollback(target_version=-1)
        assert validation.safe is False
        assert any("must be >= 0" in e for e in validation.errors)

    def test_validate_steps_zero_fails(self, runner, backend):
        """Validation with steps=0 should fail."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.upgrade()

        validation = runner.validate_rollback(steps=0)
        assert validation.safe is False
        assert any("must be >= 1" in e for e in validation.errors)

    def test_validate_multi_step(self, runner, backend):
        """Validation of multi-step rollback should check all candidates."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.register(self._make_migration(2, "b", down_sql="SELECT 1"))
        runner.register(self._make_migration(3, "c"))  # No rollback
        runner.upgrade()

        # Rolling back 1 step (v3) should fail (no rollback on v3)
        validation = runner.validate_rollback(steps=1)
        assert validation.safe is False

    def test_validate_large_rollback_warning(self, runner, backend):
        """Rolling back more than 5 migrations should produce a warning."""
        for i in range(1, 8):
            runner.register(self._make_migration(i, f"m{i}", down_sql="SELECT 1"))
        runner.upgrade()

        validation = runner.validate_rollback(target_version=0)
        assert validation.safe is True
        assert any("large operation" in w for w in validation.warnings)

    def test_validate_returns_versions_to_rollback(self, runner, backend):
        """Validation should list all versions that would be rolled back."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.register(self._make_migration(2, "b", down_sql="SELECT 1"))
        runner.register(self._make_migration(3, "c", down_sql="SELECT 1"))
        runner.upgrade()

        validation = runner.validate_rollback(target_version=1)
        assert sorted(validation.migrations_to_rollback) == [2, 3]


# ---------------------------------------------------------------------------
# Rollback history tracking tests
# ---------------------------------------------------------------------------


class TestRollbackHistory:
    """Tests for rollback history tracking."""

    def _make_migration(self, version, name, up_sql="SELECT 1", down_sql=None):
        from aragora.migrations.runner import Migration

        return Migration(version=version, name=name, up_sql=up_sql, down_sql=down_sql)

    def test_empty_history(self, runner):
        """Empty rollback history should return empty list."""
        history = runner.get_rollback_history()
        assert history == []

    def test_downgrade_records_history(self, runner, backend):
        """Downgrade should record entry in rollback history."""
        runner.register(self._make_migration(1, "create_t", down_sql="SELECT 1"))
        runner.upgrade()
        runner.downgrade()

        history = runner.get_rollback_history()
        assert len(history) == 1
        assert history[0].version == 1
        assert history[0].name == "create_t"
        assert history[0].rolled_back_by is not None
        assert ":" in history[0].rolled_back_by  # hostname:pid format

    def test_history_records_reason(self, runner, backend):
        """Reason should be stored in rollback history."""
        runner.register(self._make_migration(1, "test_m", down_sql="SELECT 1"))
        runner.upgrade()
        runner.downgrade(reason="hotfix deployment")

        history = runner.get_rollback_history()
        assert len(history) == 1
        assert history[0].reason == "hotfix deployment"

    def test_history_null_reason(self, runner, backend):
        """Rollback without reason should store None."""
        runner.register(self._make_migration(1, "test_m", down_sql="SELECT 1"))
        runner.upgrade()
        runner.downgrade()

        history = runner.get_rollback_history()
        assert len(history) == 1
        assert history[0].reason is None

    def test_multi_step_rollback_records_all(self, runner, backend):
        """Multi-step rollback should record each step individually."""
        runner.register(self._make_migration(1, "first", down_sql="SELECT 1"))
        runner.register(self._make_migration(2, "second", down_sql="SELECT 1"))
        runner.register(self._make_migration(3, "third", down_sql="SELECT 1"))
        runner.upgrade()

        runner.downgrade(target_version=1, reason="bulk rollback")

        history = runner.get_rollback_history()
        assert len(history) == 2
        versions = {h.version for h in history}
        assert versions == {2, 3}
        # All should have the same reason
        for h in history:
            assert h.reason == "bulk rollback"

    def test_history_ordered_most_recent_first(self, runner, backend):
        """History should be ordered most recent first."""
        runner.register(self._make_migration(1, "a", down_sql="SELECT 1"))
        runner.register(self._make_migration(2, "b", down_sql="SELECT 1"))
        runner.upgrade()

        runner.downgrade()  # Rollback v2
        runner.upgrade()  # Re-apply v2
        runner.downgrade()  # Rollback v2 again

        history = runner.get_rollback_history()
        assert len(history) == 2
        # Most recent should be first (higher ID)
        assert history[0].id > history[1].id

    def test_dry_run_does_not_record_history(self, runner, backend):
        """Dry-run should not create rollback history entries."""
        runner.register(self._make_migration(1, "test", down_sql="SELECT 1"))
        runner.upgrade()
        runner.downgrade(dry_run=True)

        history = runner.get_rollback_history()
        assert len(history) == 0


# ---------------------------------------------------------------------------
# Rollback import tests
# ---------------------------------------------------------------------------


class TestRollbackImports:
    """Tests for new rollback types being importable."""

    def test_import_rollback_validation(self):
        from aragora.migrations.runner import RollbackValidation

        assert RollbackValidation is not None

    def test_import_rollback_record(self):
        from aragora.migrations.runner import RollbackRecord

        assert RollbackRecord is not None

    def test_import_from_package(self):
        from aragora.migrations import RollbackRecord, RollbackValidation

        assert RollbackValidation is not None
        assert RollbackRecord is not None


# ---------------------------------------------------------------------------
# End-to-end rollback lifecycle
# ---------------------------------------------------------------------------


class TestRollbackLifecycle:
    """Full lifecycle tests involving rollback operations."""

    def test_upgrade_rollback_reapply(self, backend):
        """Test upgrade -> rollback -> re-upgrade cycle."""
        from aragora.migrations.runner import Migration, MigrationRunner

        runner = MigrationRunner(backend=backend)

        m1 = Migration(
            version=1,
            name="create users",
            up_sql="CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)",
            down_sql="DROP TABLE users",
        )
        m2 = Migration(
            version=2,
            name="create posts",
            up_sql="CREATE TABLE posts (id INTEGER PRIMARY KEY, body TEXT)",
            down_sql="DROP TABLE posts",
        )
        runner.register(m1)
        runner.register(m2)

        # Upgrade
        applied = runner.upgrade()
        assert len(applied) == 2
        assert runner.get_applied_versions() == {1, 2}

        # Rollback v2
        rolled = runner.downgrade(reason="posts table not needed yet")
        assert len(rolled) == 1
        assert rolled[0].version == 2

        # Verify posts table gone
        rows = backend.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='posts'"
        )
        assert len(rows) == 0

        # Users table still exists
        rows = backend.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        )
        assert len(rows) == 1

        # Re-apply
        applied = runner.upgrade()
        assert len(applied) == 1
        assert applied[0].version == 2
        assert runner.get_applied_versions() == {1, 2}

        # Check history
        history = runner.get_rollback_history()
        assert len(history) == 1
        assert history[0].version == 2
        assert history[0].reason == "posts table not needed yet"

    def test_validate_then_rollback(self, backend):
        """Test validation followed by actual rollback."""
        from aragora.migrations.runner import Migration, MigrationRunner

        runner = MigrationRunner(backend=backend)

        m1 = Migration(
            version=1,
            name="create t1",
            up_sql="CREATE TABLE t1 (id INTEGER PRIMARY KEY)",
            down_sql="DROP TABLE t1",
        )
        m2 = Migration(
            version=2,
            name="create t2",
            up_sql="CREATE TABLE t2 (id INTEGER PRIMARY KEY)",
            down_sql="DROP TABLE t2",
        )
        m3 = Migration(
            version=3,
            name="create t3",
            up_sql="CREATE TABLE t3 (id INTEGER PRIMARY KEY)",
            down_sql="DROP TABLE t3",
        )
        runner.register(m1)
        runner.register(m2)
        runner.register(m3)
        runner.upgrade()

        # Validate rollback of 2 steps
        validation = runner.validate_rollback(steps=2)
        assert validation.safe is True
        assert sorted(validation.migrations_to_rollback) == [2, 3]

        # Now execute
        rolled = runner.rollback_steps(steps=2)
        assert len(rolled) == 2
        assert runner.get_applied_versions() == {1}

    def test_rollback_steps_with_fn_based_migration(self, backend):
        """Test rollback_steps works with function-based migrations."""
        from aragora.migrations.runner import Migration, MigrationRunner

        runner = MigrationRunner(backend=backend)

        call_log = []

        def down(be):
            call_log.append("down_called")

        m = Migration(version=1, name="fn-based", up_sql="SELECT 1", down_fn=down)
        runner.register(m)
        runner.upgrade()

        rolled = runner.rollback_steps(steps=1)
        assert len(rolled) == 1
        assert "down_called" in call_log
