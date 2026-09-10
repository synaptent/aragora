"""
Tests for PostgreSQL Migration Runner.

Tests the PostgresMigrationRunner class that handles async migrations
for PostgreSQL databases with rollback support.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


import asyncpg


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def mock_pool():
    """Create mock asyncpg pool with async context manager support."""
    pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value=None)

    # Create transaction context manager
    mock_tx = MagicMock()
    mock_tx.__aenter__ = AsyncMock()
    mock_tx.__aexit__ = AsyncMock(return_value=False)
    mock_conn.transaction = MagicMock(return_value=mock_tx)

    # Create acquire context manager
    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=mock_acquire)
    pool.close = AsyncMock()

    return pool, mock_conn


@pytest.fixture
def runner():
    """Create a PostgresMigrationRunner for testing."""
    from aragora.persistence.migrations.postgres.runner import PostgresMigrationRunner

    return PostgresMigrationRunner(dsn="postgresql://test:test@localhost/testdb")


# ===========================================================================
# Tests: MigrationRecord Dataclass
# ===========================================================================


class TestMigrationRecord:
    """Tests for MigrationRecord dataclass."""

    def test_creation(self):
        """Test MigrationRecord creation with all fields."""
        from aragora.persistence.migrations.postgres.runner import MigrationRecord

        record = MigrationRecord(
            version=1,
            name="Initial migration",
            applied_at=datetime.now(timezone.utc),
            checksum="abc123",
        )

        assert record.version == 1
        assert record.name == "Initial migration"
        assert record.checksum == "abc123"

    def test_creation_without_checksum(self):
        """Test MigrationRecord creation without checksum (legacy)."""
        from aragora.persistence.migrations.postgres.runner import MigrationRecord

        record = MigrationRecord(
            version=2,
            name="Add indexes",
            applied_at=datetime.now(timezone.utc),
        )

        assert record.version == 2
        assert record.checksum is None


# ===========================================================================
# Tests: MigrationResult Dataclass
# ===========================================================================


class TestMigrationResult:
    """Tests for MigrationResult dataclass."""

    def test_success_when_no_errors(self):
        """MigrationResult.success should be True when no errors."""
        from aragora.persistence.migrations.postgres.runner import MigrationResult

        result = MigrationResult(
            success=True,
            migrations_applied=3,
            migrations_rolled_back=0,
            current_version=3,
            errors=[],
        )

        assert result.success is True
        assert result.migrations_applied == 3

    def test_failure_when_errors(self):
        """MigrationResult.success should be False when errors present."""
        from aragora.persistence.migrations.postgres.runner import MigrationResult

        result = MigrationResult(
            success=False,
            migrations_applied=1,
            migrations_rolled_back=0,
            current_version=1,
            errors=["Migration 2 failed: syntax error"],
        )

        assert result.success is False
        assert len(result.errors) == 1

    def test_dry_run_flag(self):
        """MigrationResult should track dry_run mode."""
        from aragora.persistence.migrations.postgres.runner import MigrationResult

        result = MigrationResult(
            success=True,
            migrations_applied=5,
            migrations_rolled_back=0,
            current_version=0,
            errors=[],
            dry_run=True,
        )

        assert result.dry_run is True


# ===========================================================================
# Tests: PostgresMigrationRunner Initialization
# ===========================================================================


class TestPostgresMigrationRunnerInit:
    """Tests for PostgresMigrationRunner initialization."""

    def test_init_with_pool(self, mock_pool):
        """Test initialization with existing pool."""
        from aragora.persistence.migrations.postgres.runner import PostgresMigrationRunner

        pool, _ = mock_pool
        runner = PostgresMigrationRunner(pool=pool)

        assert runner._pool is pool

    def test_init_with_dsn(self):
        """Test initialization with DSN string."""
        from aragora.persistence.migrations.postgres.runner import PostgresMigrationRunner

        dsn = "postgresql://user:pass@host/db"
        runner = PostgresMigrationRunner(dsn=dsn)

        assert runner._dsn == dsn

    def test_init_with_env_dsn(self, monkeypatch):
        """Test initialization falls back to environment variables."""
        from aragora.persistence.migrations.postgres.runner import PostgresMigrationRunner

        monkeypatch.setenv("ARAGORA_POSTGRES_DSN", "postgresql://env@host/db")

        runner = PostgresMigrationRunner()

        assert runner._dsn == "postgresql://env@host/db"


# ===========================================================================
# Tests: Register Migration
# ===========================================================================


class TestRegisterMigration:
    """Tests for register_migration method."""

    def test_register_single_migration(self, runner):
        """Test registering a single migration."""
        runner.register_migration(
            version=1,
            name="Create users table",
            up_sql="CREATE TABLE users (id SERIAL PRIMARY KEY);",
            down_sql="DROP TABLE users;",
        )

        assert 1 in runner._migrations
        assert runner._migrations[1]["name"] == "Create users table"

    def test_register_multiple_migrations(self, runner):
        """Test registering multiple migrations."""
        runner.register_migration(1, "First", "CREATE TABLE a;", "DROP TABLE a;")
        runner.register_migration(2, "Second", "CREATE TABLE b;", "DROP TABLE b;")

        assert len(runner._migrations) == 2

    def test_checksum_generation(self, runner):
        """Test that checksums are generated for migrations."""
        runner.register_migration(version=1, name="Test", up_sql="CREATE TABLE test;")

        checksum = runner._migrations[1]["checksum"]
        assert checksum is not None
        assert len(checksum) == 16


# ===========================================================================
# Tests: Migrate Method
# ===========================================================================


class TestMigrate:
    """Tests for migrate method."""

    @pytest.mark.asyncio
    async def test_migrate_applies_pending(self, mock_pool):
        """Test migrate applies pending migrations."""
        from aragora.persistence.migrations.postgres.runner import PostgresMigrationRunner

        pool, conn = mock_pool
        conn.fetch.return_value = []

        runner = PostgresMigrationRunner(pool=pool)
        runner.register_migration(1, "First", "CREATE TABLE a;")
        runner.register_migration(2, "Second", "CREATE TABLE b;")

        result = await runner.migrate()

        assert result.success is True
        assert result.migrations_applied == 2

    @pytest.mark.asyncio
    async def test_migrate_dry_run(self, mock_pool):
        """Test migrate with dry_run=True doesn't execute."""
        from aragora.persistence.migrations.postgres.runner import PostgresMigrationRunner

        pool, conn = mock_pool
        conn.fetch.return_value = []

        runner = PostgresMigrationRunner(pool=pool)
        runner.register_migration(1, "Test", "CREATE TABLE a;")

        result = await runner.migrate(dry_run=True)

        assert result.dry_run is True

    @pytest.mark.asyncio
    async def test_migrate_stops_on_error(self, mock_pool):
        """Test migrate stops on first error."""
        from aragora.persistence.migrations.postgres.runner import PostgresMigrationRunner

        pool, conn = mock_pool
        conn.fetch.return_value = []

        migration_count = [0]

        def counting_transaction():
            migration_count[0] += 1
            tx = MagicMock()
            if migration_count[0] > 1:
                tx.__aenter__ = AsyncMock(side_effect=RuntimeError("SQL error"))
            else:
                tx.__aenter__ = AsyncMock()
            tx.__aexit__ = AsyncMock(return_value=False)
            return tx

        conn.transaction = counting_transaction

        runner = PostgresMigrationRunner(pool=pool)
        runner.register_migration(1, "First", "SELECT 1;")
        runner.register_migration(2, "Fail", "INVALID;")

        result = await runner.migrate()

        assert result.success is False


# ===========================================================================
# Tests: Rollback Method
# ===========================================================================


class TestRollback:
    """Tests for rollback method."""

    @pytest.mark.asyncio
    async def test_rollback_no_migrations(self, mock_pool):
        """Test rollback when no migrations applied."""
        from aragora.persistence.migrations.postgres.runner import PostgresMigrationRunner

        pool, conn = mock_pool
        conn.fetch.return_value = []

        runner = PostgresMigrationRunner(pool=pool)

        result = await runner.rollback()

        assert "No migrations to rollback" in result.errors[0]

    @pytest.mark.asyncio
    async def test_rollback_single_step(self, mock_pool):
        """Test rollback single migration."""
        from aragora.persistence.migrations.postgres.runner import PostgresMigrationRunner

        pool, conn = mock_pool
        conn.fetch.return_value = [
            {"version": 1, "name": "First", "checksum": "abc"},
        ]

        runner = PostgresMigrationRunner(pool=pool)
        runner.register_migration(1, "First", "CREATE TABLE a;", "DROP TABLE a;")

        result = await runner.rollback()

        assert result.migrations_rolled_back == 1


# ===========================================================================
# Tests: Verify Checksums
# ===========================================================================


class TestVerifyChecksums:
    """Tests for verify_checksums method."""

    @pytest.mark.asyncio
    async def test_verify_checksum_mismatch(self, mock_pool):
        """Test verify detects checksum mismatch."""
        from aragora.persistence.migrations.postgres.runner import PostgresMigrationRunner

        pool, conn = mock_pool
        conn.fetch.return_value = [
            {"version": 1, "name": "Test", "checksum": "wrongchecksum"},
        ]

        runner = PostgresMigrationRunner(pool=pool)
        runner.register_migration(1, "Test", "SELECT 1;")

        results = await runner.verify_checksums()

        assert results[1][0] is False


# ===========================================================================
# Tests: Status Method
# ===========================================================================


class TestStatus:
    """Tests for status method."""

    @pytest.mark.asyncio
    async def test_status_some_pending(self, mock_pool):
        """Test status when some migrations pending."""
        from aragora.persistence.migrations.postgres.runner import PostgresMigrationRunner

        pool, conn = mock_pool
        conn.fetch.return_value = [{"version": 1}]

        runner = PostgresMigrationRunner(pool=pool)
        runner.register_migration(1, "Applied", "SELECT 1;")
        runner.register_migration(2, "Pending", "SELECT 2;")

        status = await runner.status()

        assert status["pending_count"] == 1


# ===========================================================================
# Tests: Get Postgres Migration Runner Factory
# ===========================================================================


class TestGetPostgresMigrationRunner:
    """Tests for get_postgres_migration_runner factory function."""

    def test_registers_core_migrations(self):
        """Factory should register core migrations."""
        from aragora.persistence.migrations.postgres.runner import (
            get_postgres_migration_runner,
        )

        import aragora.persistence.migrations.postgres.runner as runner_module

        runner_module._runner = None

        runner = get_postgres_migration_runner()

        assert len(runner._migrations) >= 5
