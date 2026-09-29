"""
Tests for new migration files.

Covers:
- Forward migration execution
- Rollback migration execution
- Migration idempotency
- Schema verification after migration

Run with:
    python -m pytest tests/migrations/test_new_migrations.py -v --noconftest --timeout=60
"""

from __future__ import annotations

import sqlite3
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# Helpers: lightweight in-memory SQLite backend
# ---------------------------------------------------------------------------


class InMemorySQLiteBackend:
    """Minimal DatabaseBackend implementation for testing."""

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

    def table_exists(self, table: str) -> bool:
        rows = self.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return len(rows) > 0

    def index_exists(self, index: str) -> bool:
        rows = self.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index,),
        )
        return len(rows) > 0

    def get_columns(self, table: str) -> set[str]:
        cols = self.fetch_all(f"PRAGMA table_info({table})")
        return {row[1] for row in cols}


# ---------------------------------------------------------------------------
# Fixtures
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
# Test Debate Metrics Indexes Migration
# ---------------------------------------------------------------------------


class TestDebateMetricsIndexesMigration:
    """Tests for v20260201000000_add_debate_metrics_indexes."""

    def test_import_migration(self):
        """Verify migration module can be imported."""
        from aragora.migrations.versions import v20260201000000_add_debate_metrics_indexes as mod

        assert hasattr(mod, "migration")
        assert hasattr(mod, "up_fn")
        assert hasattr(mod, "down_fn")

    def test_migration_metadata(self):
        """Verify migration has correct metadata."""
        from aragora.migrations.versions.v20260201000000_add_debate_metrics_indexes import migration

        assert migration.version == 20260201000000
        assert "index" in migration.name.lower()
        assert migration.up_fn is not None
        assert migration.down_fn is not None

    def test_forward_migration_with_gauntlet_table(self, backend):
        """Test forward migration creates indexes on existing gauntlet_results table."""
        from aragora.migrations.versions.v20260201000000_add_debate_metrics_indexes import up_fn

        # Create prerequisite table
        backend.execute_write("""
            CREATE TABLE gauntlet_results (
                gauntlet_id TEXT PRIMARY KEY,
                verdict TEXT,
                confidence REAL,
                robustness_score REAL,
                created_at TIMESTAMP
            )
        """)

        # Run migration
        up_fn(backend)

        # Verify indexes created
        assert backend.index_exists("idx_gauntlet_results_verdict_created")
        assert backend.index_exists("idx_gauntlet_results_confidence")
        assert backend.index_exists("idx_gauntlet_results_robustness")

    def test_rollback_migration(self, backend):
        """Test rollback removes indexes."""
        from aragora.migrations.versions.v20260201000000_add_debate_metrics_indexes import (
            up_fn,
            down_fn,
        )

        # Create prerequisite table
        backend.execute_write("""
            CREATE TABLE gauntlet_results (
                gauntlet_id TEXT PRIMARY KEY,
                verdict TEXT,
                confidence REAL,
                robustness_score REAL,
                created_at TIMESTAMP
            )
        """)

        # Run forward then rollback
        up_fn(backend)
        down_fn(backend)

        # Verify indexes removed
        assert not backend.index_exists("idx_gauntlet_results_verdict_created")
        assert not backend.index_exists("idx_gauntlet_results_confidence")

    def test_idempotent_forward_migration(self, backend):
        """Test migration can be run multiple times without error."""
        from aragora.migrations.versions.v20260201000000_add_debate_metrics_indexes import up_fn

        # Create prerequisite table
        backend.execute_write("""
            CREATE TABLE gauntlet_results (
                gauntlet_id TEXT PRIMARY KEY,
                verdict TEXT,
                confidence REAL,
                robustness_score REAL,
                created_at TIMESTAMP
            )
        """)

        # Run twice - should not raise
        up_fn(backend)
        up_fn(backend)

    def test_migration_without_prerequisite_tables(self, backend):
        """Test migration handles missing prerequisite tables gracefully."""
        from aragora.migrations.versions.v20260201000000_add_debate_metrics_indexes import up_fn

        # Run without creating tables - should not raise
        up_fn(backend)

    def test_job_queue_without_scheduled_at_skips_index(self, backend, caplog):
        """A job_queue created by the job queue stores has no scheduled_at column."""
        from aragora.migrations.versions.v20260201000000_add_debate_metrics_indexes import up_fn

        # Shape created at runtime by JobQueueStore / PostgresJobQueueStore
        backend.execute_write("""
            CREATE TABLE job_queue (
                id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)

        with caplog.at_level("WARNING"):
            up_fn(backend)

        assert not backend.index_exists("idx_job_queue_pending_priority")
        assert "idx_job_queue_pending_priority" in caplog.text
        assert "scheduled_at" in caplog.text

    def test_job_queue_with_scheduled_at_creates_index(self, backend):
        """A job_queue in the postgres_schema.sql shape gets the scheduling index."""
        from aragora.migrations.versions.v20260201000000_add_debate_metrics_indexes import up_fn

        backend.execute_write("""
            CREATE TABLE job_queue (
                id TEXT PRIMARY KEY,
                status TEXT DEFAULT 'pending',
                priority INTEGER DEFAULT 0,
                scheduled_at TIMESTAMP
            )
        """)

        up_fn(backend)

        assert backend.index_exists("idx_job_queue_pending_priority")


# ---------------------------------------------------------------------------
# Test Agent Performance Tracking Migration
# ---------------------------------------------------------------------------


class TestAgentPerformanceTrackingMigration:
    """Tests for v20260201000100_add_agent_performance_tracking."""

    def test_import_migration(self):
        """Verify migration module can be imported."""
        from aragora.migrations.versions import (
            v20260201000100_add_agent_performance_tracking as mod,
        )

        assert hasattr(mod, "migration")

    def test_migration_metadata(self):
        """Verify migration has correct metadata."""
        from aragora.migrations.versions.v20260201000100_add_agent_performance_tracking import (
            migration,
        )

        assert migration.version == 20260201000100
        assert "agent" in migration.name.lower()
        assert "performance" in migration.name.lower()

    def test_forward_migration_creates_table(self, backend):
        """Test forward migration creates agent_performance table."""
        from aragora.migrations.versions.v20260201000100_add_agent_performance_tracking import (
            up_fn,
        )

        up_fn(backend)

        assert backend.table_exists("agent_performance")

        # Verify columns
        cols = backend.get_columns("agent_performance")
        assert "id" in cols
        assert "agent_id" in cols
        assert "agent_type" in cols
        assert "duration_ms" in cols
        assert "input_tokens" in cols
        assert "output_tokens" in cols
        assert "elo_rating" in cols

    def test_forward_migration_creates_indexes(self, backend):
        """Test forward migration creates indexes."""
        from aragora.migrations.versions.v20260201000100_add_agent_performance_tracking import (
            up_fn,
        )

        up_fn(backend)

        assert backend.index_exists("idx_agent_perf_agent_time")
        assert backend.index_exists("idx_agent_perf_type")
        assert backend.index_exists("idx_agent_perf_debate")

    def test_rollback_migration(self, backend):
        """Test rollback removes table and indexes."""
        from aragora.migrations.versions.v20260201000100_add_agent_performance_tracking import (
            up_fn,
            down_fn,
        )

        up_fn(backend)
        assert backend.table_exists("agent_performance")

        down_fn(backend)
        assert not backend.table_exists("agent_performance")

    def test_idempotent_forward_migration(self, backend):
        """Test migration can be run multiple times without error."""
        from aragora.migrations.versions.v20260201000100_add_agent_performance_tracking import (
            up_fn,
        )

        # Run twice - should not raise
        up_fn(backend)
        up_fn(backend)

        assert backend.table_exists("agent_performance")


# ---------------------------------------------------------------------------
# Test Decision Receipts Migration
# ---------------------------------------------------------------------------


class TestDecisionReceiptsMigration:
    """Tests for v20260201000200_add_decision_receipts_table."""

    def test_import_migration(self):
        """Verify migration module can be imported."""
        from aragora.migrations.versions import v20260201000200_add_decision_receipts_table as mod

        assert hasattr(mod, "migration")

    def test_migration_metadata(self):
        """Verify migration has correct metadata."""
        from aragora.migrations.versions.v20260201000200_add_decision_receipts_table import (
            migration,
        )

        assert migration.version == 20260201000200
        assert "receipt" in migration.name.lower()

    def test_forward_migration_creates_table(self, backend):
        """Test forward migration creates decision_receipts table."""
        from aragora.migrations.versions.v20260201000200_add_decision_receipts_table import up_fn

        up_fn(backend)

        assert backend.table_exists("decision_receipts")

        # Verify columns
        cols = backend.get_columns("decision_receipts")
        assert "receipt_id" in cols
        assert "debate_id" in cols
        assert "receipt_hash" in cols
        assert "hash_algorithm" in cols
        assert "decision_summary" in cols
        assert "confidence_score" in cols
        assert "chain_hash" in cols

    def test_forward_migration_creates_indexes(self, backend):
        """Test forward migration creates indexes."""
        from aragora.migrations.versions.v20260201000200_add_decision_receipts_table import up_fn

        up_fn(backend)

        assert backend.index_exists("idx_receipts_debate")
        assert backend.index_exists("idx_receipts_hash")
        assert backend.index_exists("idx_receipts_chain")

    def test_rollback_migration(self, backend):
        """Test rollback removes table and indexes."""
        from aragora.migrations.versions.v20260201000200_add_decision_receipts_table import (
            up_fn,
            down_fn,
        )

        up_fn(backend)
        assert backend.table_exists("decision_receipts")

        down_fn(backend)
        assert not backend.table_exists("decision_receipts")

    def test_insert_and_query_receipt(self, backend):
        """Test table can store and retrieve data."""
        from aragora.migrations.versions.v20260201000200_add_decision_receipts_table import up_fn

        up_fn(backend)

        # Insert test data
        backend.execute_write("""
            INSERT INTO decision_receipts (receipt_id, debate_id, receipt_hash, decision_summary)
            VALUES ('r1', 'd1', 'abc123', 'Test decision')
        """)

        # Query it back
        row = backend.fetch_one(
            "SELECT receipt_id, debate_id, receipt_hash FROM decision_receipts WHERE receipt_id = ?",
            ("r1",),
        )
        assert row is not None
        assert row[0] == "r1"
        assert row[1] == "d1"
        assert row[2] == "abc123"


# ---------------------------------------------------------------------------
# Test Rate Limit Tracking Migration
# ---------------------------------------------------------------------------


class TestRateLimitTrackingMigration:
    """Tests for v20260201000300_add_rate_limit_tracking."""

    def test_import_migration(self):
        """Verify migration module can be imported."""
        from aragora.migrations.versions import v20260201000300_add_rate_limit_tracking as mod

        assert hasattr(mod, "migration")

    def test_migration_metadata(self):
        """Verify migration has correct metadata."""
        from aragora.migrations.versions.v20260201000300_add_rate_limit_tracking import migration

        assert migration.version == 20260201000300
        assert "rate" in migration.name.lower()

    def test_forward_migration_creates_tables(self, backend):
        """Test forward migration creates rate limit tables."""
        from aragora.migrations.versions.v20260201000300_add_rate_limit_tracking import up_fn

        up_fn(backend)

        assert backend.table_exists("rate_limit_entries")
        assert backend.table_exists("rate_limit_violations")

    def test_rate_limit_entries_schema(self, backend):
        """Test rate_limit_entries table schema."""
        from aragora.migrations.versions.v20260201000300_add_rate_limit_tracking import up_fn

        up_fn(backend)

        cols = backend.get_columns("rate_limit_entries")
        assert "key" in cols
        assert "bucket_type" in cols
        assert "tokens_remaining" in cols
        assert "expires_at" in cols

    def test_rate_limit_violations_schema(self, backend):
        """Test rate_limit_violations table schema."""
        from aragora.migrations.versions.v20260201000300_add_rate_limit_tracking import up_fn

        up_fn(backend)

        cols = backend.get_columns("rate_limit_violations")
        assert "key" in cols
        assert "bucket_type" in cols
        assert "client_ip" in cols
        assert "user_id" in cols

    def test_rollback_migration(self, backend):
        """Test rollback removes both tables."""
        from aragora.migrations.versions.v20260201000300_add_rate_limit_tracking import (
            up_fn,
            down_fn,
        )

        up_fn(backend)
        assert backend.table_exists("rate_limit_entries")
        assert backend.table_exists("rate_limit_violations")

        down_fn(backend)
        assert not backend.table_exists("rate_limit_entries")
        assert not backend.table_exists("rate_limit_violations")


# ---------------------------------------------------------------------------
# Test Session Management Migration
# ---------------------------------------------------------------------------


class TestSessionManagementMigration:
    """Tests for v20260201000400_add_session_management."""

    def test_import_migration(self):
        """Verify migration module can be imported."""
        from aragora.migrations.versions import v20260201000400_add_session_management as mod

        assert hasattr(mod, "migration")

    def test_migration_metadata(self):
        """Verify migration has correct metadata."""
        from aragora.migrations.versions.v20260201000400_add_session_management import migration

        assert migration.version == 20260201000400
        assert "session" in migration.name.lower()

    def test_forward_migration_creates_tables(self, backend):
        """Test forward migration creates session tables."""
        from aragora.migrations.versions.v20260201000400_add_session_management import up_fn

        up_fn(backend)

        assert backend.table_exists("user_sessions")
        assert backend.table_exists("session_events")

    def test_user_sessions_schema(self, backend):
        """Test user_sessions table schema."""
        from aragora.migrations.versions.v20260201000400_add_session_management import up_fn

        up_fn(backend)

        cols = backend.get_columns("user_sessions")
        assert "session_id" in cols
        assert "user_id" in cols
        assert "expires_at" in cols
        assert "ip_address" in cols
        assert "auth_method" in cols
        assert "mfa_verified" in cols

    def test_session_events_schema(self, backend):
        """Test session_events table schema."""
        from aragora.migrations.versions.v20260201000400_add_session_management import up_fn

        up_fn(backend)

        cols = backend.get_columns("session_events")
        assert "session_id" in cols
        assert "user_id" in cols
        assert "event_type" in cols
        assert "success" in cols

    def test_rollback_migration(self, backend):
        """Test rollback removes both tables."""
        from aragora.migrations.versions.v20260201000400_add_session_management import (
            up_fn,
            down_fn,
        )

        up_fn(backend)
        assert backend.table_exists("user_sessions")
        assert backend.table_exists("session_events")

        down_fn(backend)
        assert not backend.table_exists("user_sessions")
        assert not backend.table_exists("session_events")


# ---------------------------------------------------------------------------
# Full Lifecycle Tests with Runner
# ---------------------------------------------------------------------------


class TestMigrationRunnerIntegration:
    """Test migrations work correctly with the MigrationRunner."""

    def test_all_new_migrations_register(self, runner):
        """Test all new migrations can be registered."""
        from aragora.migrations.runner import _load_migrations

        _load_migrations(runner)

        # Check our new migrations are loaded
        versions = [m.version for m in runner._migrations]
        assert 20260201000000 in versions  # Debate metrics indexes
        assert 20260201000100 in versions  # Agent performance
        assert 20260201000200 in versions  # Decision receipts
        assert 20260201000300 in versions  # Rate limit tracking
        assert 20260201000400 in versions  # Session management

    def test_upgrade_applies_new_migrations(self, runner, backend):
        """Test upgrade applies our new migrations."""
        from aragora.migrations.runner import _load_migrations

        _load_migrations(runner)

        # Apply all migrations
        applied = runner.upgrade()

        # Should have applied our new migrations
        applied_versions = {m.version for m in applied}
        assert 20260201000100 in applied_versions  # Agent performance
        assert 20260201000200 in applied_versions  # Decision receipts

        # Verify tables exist
        assert backend.table_exists("agent_performance")
        assert backend.table_exists("decision_receipts")
        assert backend.table_exists("rate_limit_entries")
        assert backend.table_exists("user_sessions")

    def test_downgrade_rolls_back_new_migrations(self, runner, backend):
        """Test downgrade rolls back our new migrations."""
        from aragora.migrations.runner import _load_migrations

        _load_migrations(runner)

        # Apply all
        runner.upgrade()

        # Tables should exist
        assert backend.table_exists("agent_performance")

        # Roll back through the "new migrations" block without depending on
        # how many later migrations have been added since this test was written.
        runner.downgrade(target_version=20260201000000)

        # Tables should be gone
        assert not backend.table_exists("agent_performance")
        assert not backend.table_exists("decision_receipts")

    def test_upgrade_is_idempotent(self, runner, backend):
        """Test upgrade called multiple times is idempotent."""
        from aragora.migrations.runner import _load_migrations

        _load_migrations(runner)

        # Apply twice
        first_applied = runner.upgrade()
        second_applied = runner.upgrade()

        # Second call should return empty (nothing new to apply)
        assert len(second_applied) == 0

        # Tables should still exist
        assert backend.table_exists("agent_performance")


# ---------------------------------------------------------------------------
# Tables created at runtime by the app's stores
# ---------------------------------------------------------------------------

# Shapes the app's stores create on startup with CREATE TABLE IF NOT EXISTS.
# A database can hold these before the migrations that index them run.
RUNTIME_JOB_QUEUE = """
    CREATE TABLE job_queue (
        id TEXT PRIMARY KEY,
        job_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        priority INTEGER DEFAULT 0,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    )
"""
# Knowledge Mound PostgreSQL store: no workspace_id column
RUNTIME_ACCESS_GRANTS = """
    CREATE TABLE access_grants (
        id TEXT PRIMARY KEY,
        item_id TEXT NOT NULL,
        grantee_type TEXT NOT NULL,
        grantee_id TEXT NOT NULL,
        permissions TEXT,
        granted_by TEXT,
        granted_at TIMESTAMP,
        expires_at TIMESTAMP,
        UNIQUE(item_id, grantee_type, grantee_id)
    )
"""
# SQLite KnowledgeMoundMetaStore: no staleness_score column
RUNTIME_KNOWLEDGE_NODES = """
    CREATE TABLE knowledge_nodes (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        node_type TEXT NOT NULL,
        content TEXT NOT NULL,
        confidence REAL DEFAULT 0.5,
        validation_status TEXT DEFAULT 'unverified',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
"""


class TestRuntimeCreatedTablesMissingColumns:
    """Migrations skip indexes whose columns a runtime-created table lacks."""

    def test_km_visibility_adds_workspace_id_to_runtime_access_grants(self, backend, caplog):
        """The migration declares access_grants.workspace_id, so a runtime-shaped
        table gets the column (and its index) instead of being recorded as
        migrated without it."""
        from aragora.migrations.versions.v20260119000000_knowledge_mound_visibility import up_fn

        backend.execute_write(RUNTIME_ACCESS_GRANTS)
        backend.execute_write(
            "INSERT INTO access_grants (id, item_id, grantee_type, grantee_id) "
            "VALUES ('g1', 'n1', 'user', 'u1')"
        )

        with caplog.at_level("WARNING"):
            up_fn(backend)

        assert "workspace_id" in backend.get_columns("access_grants")
        for index in (
            "idx_grants_item_id",
            "idx_grants_grantee",
            "idx_grants_workspace",
            "idx_grants_expires",
        ):
            assert backend.index_exists(index), index
        assert "Skipping index" not in caplog.text
        # Existing grants keep their rows; the added column is NULL for them.
        assert backend.fetch_all("SELECT id, workspace_id FROM access_grants") == [("g1", None)]

    def test_km_visibility_is_idempotent_after_adding_workspace_id(self, backend):
        from aragora.migrations.versions.v20260119000000_knowledge_mound_visibility import up_fn

        backend.execute_write(RUNTIME_ACCESS_GRANTS)
        up_fn(backend)
        up_fn(backend)

        columns = [row[1] for row in backend.fetch_all("PRAGMA table_info(access_grants)")]
        assert columns.count("workspace_id") == 1
        assert backend.index_exists("idx_grants_workspace")

    def test_km_visibility_indexes_access_grants_it_creates(self, backend):
        from aragora.migrations.versions.v20260119000000_knowledge_mound_visibility import up_fn

        up_fn(backend)

        assert "workspace_id" in backend.get_columns("access_grants")
        assert backend.index_exists("idx_grants_workspace")
        assert backend.index_exists("idx_federation_enabled")

    def test_km_composite_skips_staleness_index_without_staleness_score(self, backend, caplog):
        from aragora.migrations.versions.v20260202000000_knowledge_mound_composite_indexes import (
            up_fn,
        )

        backend.execute_write(RUNTIME_KNOWLEDGE_NODES)

        with caplog.at_level("WARNING"):
            up_fn(backend)

        assert backend.index_exists("idx_km_workspace_type_confidence")
        assert backend.index_exists("idx_km_updated_workspace")
        assert not backend.index_exists("idx_km_validation_staleness")
        assert "staleness_score" in caplog.text

    def test_km_composite_creates_staleness_index_with_staleness_score(self, backend):
        from aragora.migrations.versions.v20260202000000_knowledge_mound_composite_indexes import (
            up_fn,
        )

        backend.execute_write(RUNTIME_KNOWLEDGE_NODES)
        backend.execute_write("ALTER TABLE knowledge_nodes ADD COLUMN staleness_score REAL")

        up_fn(backend)

        assert backend.index_exists("idx_km_validation_staleness")

    def test_full_upgrade_over_runtime_created_tables(self, runner, backend):
        from aragora.migrations.runner import _load_migrations

        backend.execute_write(RUNTIME_JOB_QUEUE)
        backend.execute_write(RUNTIME_ACCESS_GRANTS)
        backend.execute_write(RUNTIME_KNOWLEDGE_NODES)
        _load_migrations(runner)

        runner.upgrade()

        assert runner.get_pending_migrations() == []
        assert not backend.index_exists("idx_job_queue_pending_priority")
        assert "workspace_id" in backend.get_columns("access_grants")
        assert backend.index_exists("idx_grants_workspace")
        assert not backend.index_exists("idx_km_validation_staleness")


# What the pre-guard 20260201000000 ran on SQLite: with no scheduled_at column,
# SQLite reads the quoted name as a string literal and indexes a constant.
PRE_GUARD_JOB_QUEUE_INDEX = (
    'CREATE INDEX IF NOT EXISTS "idx_job_queue_pending_priority" '
    'ON "job_queue" ("status", "priority", "scheduled_at")'
)


def _index_key_columns(backend, index: str) -> list:
    return [row[2] for row in backend.fetch_all(f'PRAGMA index_xinfo("{index}")') if row[5] == 1]


class TestJobQueueConstantIndexRepair:
    """20260929000000 drops the constant index the pre-guard 20260201000000 left on SQLite."""

    def test_drops_constant_index_when_scheduled_at_is_missing(self, backend):
        from aragora.migrations.versions.v20260929000000_repair_job_queue_constant_index import (
            up_fn,
        )

        backend.execute_write(RUNTIME_JOB_QUEUE)
        backend.execute_write(PRE_GUARD_JOB_QUEUE_INDEX)
        assert _index_key_columns(backend, "idx_job_queue_pending_priority") == [
            "status",
            "priority",
            None,
        ]

        up_fn(backend)

        assert not backend.index_exists("idx_job_queue_pending_priority")

    def test_rebuilds_real_index_once_scheduled_at_exists(self, backend):
        from aragora.migrations.versions.v20260929000000_repair_job_queue_constant_index import (
            up_fn,
        )

        backend.execute_write(RUNTIME_JOB_QUEUE)
        backend.execute_write(PRE_GUARD_JOB_QUEUE_INDEX)
        backend.execute_write("ALTER TABLE job_queue ADD COLUMN scheduled_at REAL")

        up_fn(backend)

        assert _index_key_columns(backend, "idx_job_queue_pending_priority") == [
            "status",
            "priority",
            "scheduled_at",
        ]

    def test_leaves_a_real_index_untouched(self, backend):
        from aragora.migrations.versions.v20260929000000_repair_job_queue_constant_index import (
            up_fn,
        )

        backend.execute_write(RUNTIME_JOB_QUEUE)
        backend.execute_write("ALTER TABLE job_queue ADD COLUMN scheduled_at REAL")
        backend.execute_write(PRE_GUARD_JOB_QUEUE_INDEX)
        before = backend.fetch_all(
            "SELECT sql FROM sqlite_master WHERE name = 'idx_job_queue_pending_priority'"
        )

        up_fn(backend)

        after = backend.fetch_all(
            "SELECT sql FROM sqlite_master WHERE name = 'idx_job_queue_pending_priority'"
        )
        assert after == before
        assert _index_key_columns(backend, "idx_job_queue_pending_priority")[2] == "scheduled_at"

    def test_no_job_queue_is_a_no_op(self, backend):
        from aragora.migrations.versions.v20260929000000_repair_job_queue_constant_index import (
            up_fn,
        )

        up_fn(backend)

        assert not backend.table_exists("job_queue")
        assert not backend.index_exists("idx_job_queue_pending_priority")

    def test_full_upgrade_repairs_a_database_that_applied_the_pre_guard_version(
        self, runner, backend
    ):
        from aragora.migrations.runner import _load_migrations

        # The constant index a pre-guard 20260201000000 run left behind; the
        # guarded 20260201000000 skips (the name already exists) and the repair
        # migration removes it.
        backend.execute_write(RUNTIME_JOB_QUEUE)
        backend.execute_write(PRE_GUARD_JOB_QUEUE_INDEX)
        _load_migrations(runner)

        runner.upgrade()

        assert runner.get_pending_migrations() == []
        assert not backend.index_exists("idx_job_queue_pending_priority")


class TestColumnGuardChecksumContinuity:
    """Adding the column guards must not fail checksum verification on applied databases."""

    # Checksums these migrations had before the column guards; databases that
    # applied them (the Hetzner canary applied 20260119000000) store these.
    PRE_GUARD_CHECKSUMS = {
        20260119000000: "4410a1ca05214b011cdff23c8cfaae986c3145223cc8d2a57ea2c2a4a00fc172",
        20260201000000: "1750a3d82adbb6420727f27dcc0f502cdeab0b02147b3bf13978532e8913049e",
        20260202000000: "4fff064b3fc0e4a8280fe9739e2cf094ba03d112b4c61bcc6899cd084c074671",
    }

    def test_databases_that_applied_the_unguarded_migrations_still_verify(self, runner, backend):
        from aragora.migrations.runner import _load_migrations

        _load_migrations(runner)
        for version, checksum in self.PRE_GUARD_CHECKSUMS.items():
            backend.execute_write(
                "INSERT INTO _aragora_migrations (version, name, checksum) VALUES (?, ?, ?)",
                (version, f"v{version}", checksum),
            )

        assert runner.verify_checksums() == []

    def test_later_edits_to_the_guarded_migrations_are_still_detected(self, runner, backend):
        from aragora.migrations.runner import _load_migrations

        _load_migrations(runner)
        for version in self.PRE_GUARD_CHECKSUMS:
            backend.execute_write(
                "INSERT INTO _aragora_migrations (version, name, checksum) VALUES (?, ?, ?)",
                (version, f"v{version}", "0" * 64),
            )

        mismatched = {version for version, _, _ in runner.verify_checksums()}
        assert mismatched == set(self.PRE_GUARD_CHECKSUMS)


class TestGuardedIndexesOnCompleteTables:
    """With every column present, no guarded index is skipped (catches column-name typos)."""

    def test_debate_metrics_indexes(self, backend, caplog):
        from aragora.migrations.versions.v20260201000000_add_debate_metrics_indexes import up_fn

        backend.execute_write("""
            CREATE TABLE gauntlet_results (
                gauntlet_id TEXT PRIMARY KEY, verdict TEXT, confidence REAL,
                robustness_score REAL, created_at TIMESTAMP
            )
        """)
        backend.execute_write("""
            CREATE TABLE job_queue (
                id TEXT PRIMARY KEY, status TEXT, priority INTEGER, scheduled_at TIMESTAMP
            )
        """)
        backend.execute_write("""
            CREATE TABLE audit_log (
                id TEXT PRIMARY KEY, timestamp TEXT, resource_type TEXT, resource_id TEXT
            )
        """)

        with caplog.at_level("WARNING"):
            up_fn(backend)

        assert "Skipping index" not in caplog.text
        for index in (
            "idx_gauntlet_results_verdict_created",
            "idx_gauntlet_results_confidence",
            "idx_gauntlet_results_robustness",
            "idx_job_queue_pending_priority",
            "idx_audit_log_resource_time",
        ):
            assert backend.index_exists(index), index

    def test_km_visibility_indexes(self, backend, caplog):
        from aragora.migrations.versions.v20260119000000_knowledge_mound_visibility import up_fn

        with caplog.at_level("WARNING"):
            up_fn(backend)

        assert "Skipping index" not in caplog.text
        for index in (
            "idx_grants_item_id",
            "idx_grants_grantee",
            "idx_grants_workspace",
            "idx_grants_expires",
            "idx_federation_enabled",
        ):
            assert backend.index_exists(index), index

    def test_km_composite_indexes(self, backend, caplog):
        from aragora.migrations.versions.v20260202000000_knowledge_mound_composite_indexes import (
            up_fn,
        )

        backend.execute_write(RUNTIME_KNOWLEDGE_NODES)
        backend.execute_write("ALTER TABLE knowledge_nodes ADD COLUMN staleness_score REAL")
        backend.execute_write("""
            CREATE TABLE knowledge_relationships (
                id TEXT PRIMARY KEY, from_node_id TEXT, to_node_id TEXT, relationship_type TEXT
            )
        """)

        with caplog.at_level("WARNING"):
            up_fn(backend)

        assert "Skipping index" not in caplog.text
        for index in (
            "idx_km_workspace_type_confidence",
            "idx_km_updated_workspace",
            "idx_km_validation_staleness",
            "idx_km_rel_path",
        ):
            assert backend.index_exists(index), index


# ---------------------------------------------------------------------------
# Edge Cases and Error Handling
# ---------------------------------------------------------------------------


class TestMigrationEdgeCases:
    """Test edge cases and error handling."""

    def test_migration_with_data_preservation(self, backend):
        """Test that migrations preserve existing data."""
        from aragora.migrations.versions.v20260201000100_add_agent_performance_tracking import (
            up_fn,
        )

        up_fn(backend)

        # Insert some test data
        backend.execute_write("""
            INSERT INTO agent_performance (id, agent_id, agent_type, operation, started_at)
            VALUES ('test1', 'agent1', 'claude', 'propose', '2026-01-01 00:00:00')
        """)

        # Run migration again (idempotent)
        up_fn(backend)

        # Data should still exist
        row = backend.fetch_one(
            "SELECT id, agent_id FROM agent_performance WHERE id = ?", ("test1",)
        )
        assert row is not None
        assert row[0] == "test1"
        assert row[1] == "agent1"

    def test_migrations_in_correct_order(self, runner):
        """Test migrations are sorted by version."""
        from aragora.migrations.runner import _load_migrations

        _load_migrations(runner)

        versions = [m.version for m in runner._migrations]

        # Should be sorted
        assert versions == sorted(versions)

        # Our migrations should be in correct order
        our_versions = [v for v in versions if v >= 20260201000000 and v <= 20260201000400]
        expected_order = [
            20260201000000,  # Indexes first (no deps)
            20260201000100,  # Agent performance
            20260201000200,  # Decision receipts
            20260201000300,  # Rate limiting
            20260201000400,  # Sessions
        ]
        assert our_versions == expected_order
