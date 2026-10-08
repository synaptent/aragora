"""Comprehensive tests for database_utils health check utility functions.

Tests all public functions and the Protocol in
aragora/server/handlers/admin/health/database_utils.py:

  TestHealthHandlerProtocol           - _HealthHandlerProtocol runtime check
  TestHandleStoreCheckErrors          - handle_store_check_errors() wrapper
  TestCheckDebateStorage              - check_debate_storage()
  TestCheckEloSystem                  - check_elo_system()
  TestCheckInsightStore               - check_insight_store()
  TestCheckFlipDetector               - check_flip_detector()
  TestCheckUserStore                  - check_user_store()
  TestCheckConsensusMemory            - check_consensus_memory()
  TestCheckAgentMetadata              - check_agent_metadata()
  TestCheckIntegrationStore           - check_integration_store()
  TestCheckGmailTokenStore            - check_gmail_token_store()
  TestCheckSyncStore                  - check_sync_store()
  TestCheckDecisionResultStore        - check_decision_result_store()
  TestCrossCutting                    - Cross-cutting contract tests
  TestSecurityEdgeCases               - Path traversal, injection, edge cases

120+ tests covering all branches, error paths, and edge cases.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.admin.health.database_utils import (
    _HealthHandlerProtocol,
    check_agent_metadata,
    check_consensus_memory,
    check_debate_storage,
    check_decision_result_store,
    check_elo_system,
    check_flip_detector,
    check_gmail_token_store,
    check_insight_store,
    check_integration_store,
    check_sync_store,
    check_user_store,
    handle_store_check_errors,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeHandler:
    """Concrete implementation of _HealthHandlerProtocol for testing."""

    def __init__(self, ctx: dict[str, Any] | None = None, nomic_dir: Path | None = None):
        self.ctx = ctx or {}
        self._nomic_dir = nomic_dir
        self._storage = self.ctx.get("storage")
        self._elo_system = self.ctx.get("elo_system")

    def get_storage(self) -> Any:
        return self._storage

    def get_elo_system(self) -> Any:
        return self._elo_system

    def get_nomic_dir(self) -> Path | None:
        return self._nomic_dir


def _make_handler(
    ctx: dict[str, Any] | None = None,
    nomic_dir: Path | None = None,
) -> FakeHandler:
    """Create a FakeHandler with the given context and optional nomic dir."""
    return FakeHandler(ctx=ctx, nomic_dir=nomic_dir)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Default handler with empty context."""
    return _make_handler()


@pytest.fixture
def tmp_nomic_dir(tmp_path):
    """Temporary directory usable as nomic_dir."""
    d = tmp_path / "nomic"
    d.mkdir()
    return d


# ============================================================================
# TestHealthHandlerProtocol
# ============================================================================


class TestHealthHandlerProtocol:
    """Tests for the _HealthHandlerProtocol runtime check."""

    def test_fake_handler_implements_protocol(self, handler):
        """FakeHandler satisfies the _HealthHandlerProtocol at runtime."""
        assert isinstance(handler, _HealthHandlerProtocol)

    def test_object_without_ctx_does_not_satisfy(self):
        """A plain object without the required attrs does not satisfy the protocol."""

        class Bare:
            pass

        assert not isinstance(Bare(), _HealthHandlerProtocol)

    def test_object_missing_get_storage(self):
        """An object missing get_storage does not satisfy the protocol."""

        class Incomplete:
            ctx: dict[str, Any] = {}

            def get_elo_system(self):
                return None

            def get_nomic_dir(self):
                return None

        assert not isinstance(Incomplete(), _HealthHandlerProtocol)


# ============================================================================
# TestHandleStoreCheckErrors
# ============================================================================


class TestHandleStoreCheckErrors:
    """Tests for handle_store_check_errors() wrapper."""

    def test_successful_check(self):
        """Successful check_fn returns its result and healthy=True."""

        def check():
            return {"healthy": True, "status": "connected"}

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is True
        assert result["healthy"] is True
        assert result["status"] == "connected"

    def test_successful_check_healthy_false(self):
        """check_fn returning healthy=False is passed through correctly."""

        def check():
            return {"healthy": False, "status": "degraded"}

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is False
        assert result["healthy"] is False

    def test_successful_check_no_healthy_key(self):
        """check_fn returning dict without healthy key defaults to healthy=True."""

        def check():
            return {"status": "ok"}

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is True

    def test_sqlite_error(self):
        """sqlite3.Error -> database error type, not healthy."""

        def check():
            raise sqlite3.OperationalError("database is locked")

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is False
        assert result["healthy"] is False
        assert result["error_type"] == "database"
        assert result["error"] == "Health check failed"

    def test_sqlite_integrity_error(self):
        """sqlite3.IntegrityError -> database error type."""

        def check():
            raise sqlite3.IntegrityError("constraint failed")

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is False
        assert result["error_type"] == "database"

    def test_os_error(self):
        """OSError -> database error type."""

        def check():
            raise OSError("disk full")

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is False
        assert result["error_type"] == "database"

    def test_io_error(self):
        """IOError (alias for OSError) -> database error type."""

        def check():
            raise IOError("read error")

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is False
        assert result["error_type"] == "database"

    def test_key_error(self):
        """KeyError -> data_access error type."""

        def check():
            raise KeyError("missing_key")

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is False
        assert result["error_type"] == "data_access"

    def test_type_error(self):
        """TypeError -> data_access error type."""

        def check():
            raise TypeError("wrong type")

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is False
        assert result["error_type"] == "data_access"

    def test_attribute_error(self):
        """AttributeError -> data_access error type."""

        def check():
            raise AttributeError("no such attribute")

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is False
        assert result["error_type"] == "data_access"

    def test_import_error(self):
        """ImportError -> module_not_available, healthy=True."""

        def check():
            raise ImportError("no module named 'foo'")

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is True
        assert result["healthy"] is True
        assert result["status"] == "module_not_available"

    def test_value_error(self):
        """ValueError -> generic health check failed."""

        def check():
            raise ValueError("invalid value")

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is False
        assert result["healthy"] is False
        assert result["error"] == "Health check failed"

    def test_runtime_error(self):
        """RuntimeError -> generic health check failed."""

        def check():
            raise RuntimeError("unexpected failure")

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is False
        assert result["error"] == "Health check failed"

    def test_error_message_sanitized_sqlite(self):
        """sqlite3 error message is NOT leaked in the result dict."""

        def check():
            raise sqlite3.OperationalError("table users has 5 columns but 6 values were supplied")

        result, _ = handle_store_check_errors("test_store", check)
        assert "5 columns" not in result.get("error", "")

    def test_error_message_sanitized_key(self):
        """KeyError original message is NOT leaked in result."""

        def check():
            raise KeyError("secret_column_name")

        result, _ = handle_store_check_errors("test_store", check)
        assert "secret_column_name" not in result.get("error", "")

    def test_error_message_sanitized_runtime(self):
        """RuntimeError original message is NOT leaked in result."""

        def check():
            raise RuntimeError("connection string: postgres://user:pass@host/db")

        result, _ = handle_store_check_errors("test_store", check)
        assert "postgres://" not in result.get("error", "")


# ============================================================================
# TestCheckDebateStorage
# ============================================================================


class TestCheckDebateStorage:
    """Tests for check_debate_storage() function."""

    def test_connected_when_storage_present(self):
        """Storage present and list_recent succeeds -> connected, healthy."""
        mock_storage = MagicMock()
        mock_storage.list_recent.return_value = []
        h = _make_handler({"storage": mock_storage})
        result = check_debate_storage(h)
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["type"] == "MagicMock"

    def test_not_initialized_when_no_storage(self, handler):
        """No storage -> not_initialized, healthy with hint."""
        result = check_debate_storage(handler)
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result
        assert "auto-create" in result["hint"]

    def test_list_recent_called_with_limit(self):
        """list_recent is called with limit=1."""
        mock_storage = MagicMock()
        mock_storage.list_recent.return_value = [{"id": "debate-1"}]
        h = _make_handler({"storage": mock_storage})
        check_debate_storage(h)
        mock_storage.list_recent.assert_called_once_with(limit=1)

    def test_storage_type_name_preserved(self):
        """Type name of the storage class is included in result."""

        class CustomDebateStorage:
            def list_recent(self, limit=1):
                return []

        h = _make_handler({"storage": CustomDebateStorage()})
        result = check_debate_storage(h)
        assert result["type"] == "CustomDebateStorage"

    def test_storage_with_many_debates(self):
        """Storage with multiple debates returns healthy."""
        mock_storage = MagicMock()
        mock_storage.list_recent.return_value = [{"id": f"d{i}"} for i in range(5)]
        h = _make_handler({"storage": mock_storage})
        result = check_debate_storage(h)
        assert result["healthy"] is True
        assert result["status"] == "connected"

    def test_storage_returns_none(self):
        """Explicit None storage -> not_initialized."""
        h = _make_handler({"storage": None})
        h._storage = None
        result = check_debate_storage(h)
        assert result["status"] == "not_initialized"


# ============================================================================
# TestCheckEloSystem
# ============================================================================


class TestCheckEloSystem:
    """Tests for check_elo_system() function."""

    def test_connected_with_agents(self):
        """ELO system connected with agents -> healthy with count."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.return_value = [{"agent": "a"}, {"agent": "b"}]
        h = _make_handler({"elo_system": mock_elo})
        result = check_elo_system(h)
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["agent_count"] == 2

    def test_connected_empty_leaderboard(self):
        """ELO system connected with empty leaderboard -> still healthy."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.return_value = []
        h = _make_handler({"elo_system": mock_elo})
        result = check_elo_system(h)
        assert result["healthy"] is True
        assert result["agent_count"] == 0

    def test_not_initialized(self, handler):
        """No ELO system -> not_initialized with hint."""
        result = check_elo_system(handler)
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result
        assert "seed_agents" in result["hint"]

    def test_get_leaderboard_called_with_limit(self):
        """get_leaderboard is called with limit=5."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.return_value = []
        h = _make_handler({"elo_system": mock_elo})
        check_elo_system(h)
        mock_elo.get_leaderboard.assert_called_once_with(limit=5)

    def test_large_leaderboard(self):
        """Leaderboard with many agents returns correct count."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.return_value = [{"agent": f"a{i}"} for i in range(100)]
        h = _make_handler({"elo_system": mock_elo})
        result = check_elo_system(h)
        assert result["agent_count"] == 100


# ============================================================================
# TestCheckInsightStore
# ============================================================================


class TestCheckInsightStore:
    """Tests for check_insight_store() function."""

    def test_connected(self):
        """Insight store present -> connected with type."""
        mock_store = MagicMock()
        h = _make_handler({"insight_store": mock_store})
        result = check_insight_store(h)
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["type"] == "MagicMock"

    def test_not_initialized(self, handler):
        """No insight store -> not_initialized with hint."""
        result = check_insight_store(handler)
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result
        assert "auto-create" in result["hint"]

    def test_custom_type_name(self):
        """Custom class type name preserved."""

        class MyInsightStore:
            pass

        h = _make_handler({"insight_store": MyInsightStore()})
        result = check_insight_store(h)
        assert result["type"] == "MyInsightStore"

    def test_insight_store_none_explicit(self):
        """Explicit None in ctx -> not_initialized."""
        h = _make_handler({"insight_store": None})
        result = check_insight_store(h)
        assert result["status"] == "not_initialized"


# ============================================================================
# TestCheckFlipDetector
# ============================================================================


class TestCheckFlipDetector:
    """Tests for check_flip_detector() function."""

    def test_connected(self):
        """Flip detector present -> connected with type."""
        mock_fd = MagicMock()
        h = _make_handler({"flip_detector": mock_fd})
        result = check_flip_detector(h)
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["type"] == "MagicMock"

    def test_not_initialized(self, handler):
        """No flip detector -> not_initialized."""
        result = check_flip_detector(handler)
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"

    def test_no_hint_when_not_initialized(self, handler):
        """Unlike insight_store, flip_detector has no hint."""
        result = check_flip_detector(handler)
        assert "hint" not in result

    def test_custom_type_name(self):
        """Custom class type name preserved."""

        class FlipDetectorV2:
            pass

        h = _make_handler({"flip_detector": FlipDetectorV2()})
        result = check_flip_detector(h)
        assert result["type"] == "FlipDetectorV2"


# ============================================================================
# TestCheckUserStore
# ============================================================================


class TestCheckUserStore:
    """Tests for check_user_store() function."""

    def test_connected(self):
        """User store present -> connected."""
        mock_store = MagicMock()
        h = _make_handler({"user_store": mock_store})
        result = check_user_store(h)
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["type"] == "MagicMock"

    def test_not_initialized(self, handler):
        """No user store -> not_initialized."""
        result = check_user_store(handler)
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"

    def test_no_hint_when_not_initialized(self, handler):
        """Unlike insight_store, user_store has no hint."""
        result = check_user_store(handler)
        assert "hint" not in result

    def test_custom_type_name(self):
        """Custom class type name preserved."""

        class SupabaseUserStore:
            pass

        h = _make_handler({"user_store": SupabaseUserStore()})
        result = check_user_store(h)
        assert result["type"] == "SupabaseUserStore"


# ============================================================================
# TestCheckConsensusMemory
# ============================================================================


class TestCheckConsensusMemory:
    """Tests for check_consensus_memory() function."""

    def test_exists_with_db_file(self, tmp_nomic_dir):
        """Consensus memory DB file exists -> status=exists with path."""
        db_file = tmp_nomic_dir / "consensus_memory.db"
        db_file.touch()
        h = _make_handler(nomic_dir=tmp_nomic_dir)
        result = check_consensus_memory(h)
        assert result["healthy"] is True
        assert result["status"] == "exists"
        assert result["path"] == str(db_file)

    def test_not_initialized_no_db_file(self, tmp_nomic_dir):
        """Nomic dir exists but no consensus_memory.db -> not_initialized with hint."""
        h = _make_handler(nomic_dir=tmp_nomic_dir)
        result = check_consensus_memory(h)
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result
        assert "seed_consensus" in result["hint"]

    def test_nomic_dir_not_set(self, handler):
        """No nomic_dir -> nomic_dir_not_set."""
        result = check_consensus_memory(handler)
        assert result["healthy"] is True
        assert result["status"] == "nomic_dir_not_set"

    def test_import_error(self, tmp_nomic_dir):
        """ConsensusMemory module not available -> ImportError is raised (not caught here)."""
        # The function does a bare import of ConsensusMemory before checking nomic_dir.
        # ImportError from the lazy import will propagate since handle_store_check_errors
        # is not used inside this function.
        h = _make_handler(nomic_dir=tmp_nomic_dir)
        with patch.dict("sys.modules", {"aragora.memory.consensus": None}):
            with pytest.raises(ImportError):
                check_consensus_memory(h)

    def test_path_construction(self, tmp_nomic_dir):
        """Consensus path is correctly constructed as nomic_dir / consensus_memory.db."""
        db_file = tmp_nomic_dir / "consensus_memory.db"
        db_file.touch()
        h = _make_handler(nomic_dir=tmp_nomic_dir)
        result = check_consensus_memory(h)
        assert result["path"] == str(tmp_nomic_dir / "consensus_memory.db")


# ============================================================================
# TestCheckAgentMetadata
# ============================================================================


class TestCheckAgentMetadata:
    """Tests for check_agent_metadata() function."""

    def test_connected_with_metadata(self, tmp_nomic_dir):
        """elo.db exists with agent_metadata table and data -> connected."""
        elo_path = tmp_nomic_dir / "elo.db"
        conn = sqlite3.connect(elo_path)
        conn.execute("CREATE TABLE agent_metadata (id TEXT, name TEXT)")
        conn.execute("INSERT INTO agent_metadata VALUES ('a1', 'Agent 1')")
        conn.execute("INSERT INTO agent_metadata VALUES ('a2', 'Agent 2')")
        conn.commit()
        conn.close()

        h = _make_handler(nomic_dir=tmp_nomic_dir)
        result = check_agent_metadata(h)
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["agent_count"] == 2

    def test_table_not_exists(self, tmp_nomic_dir):
        """elo.db exists but no agent_metadata table -> table_not_exists."""
        elo_path = tmp_nomic_dir / "elo.db"
        conn = sqlite3.connect(elo_path)
        conn.execute("CREATE TABLE other_table (id TEXT)")
        conn.commit()
        conn.close()

        h = _make_handler(nomic_dir=tmp_nomic_dir)
        result = check_agent_metadata(h)
        assert result["healthy"] is True
        assert result["status"] == "table_not_exists"
        assert "hint" in result
        assert "with-metadata" in result["hint"]

    def test_database_not_exists(self, tmp_nomic_dir):
        """Nomic dir exists but no elo.db -> database_not_exists."""
        h = _make_handler(nomic_dir=tmp_nomic_dir)
        result = check_agent_metadata(h)
        assert result["healthy"] is True
        assert result["status"] == "database_not_exists"

    def test_nomic_dir_not_set(self, handler):
        """No nomic_dir -> nomic_dir_not_set."""
        result = check_agent_metadata(handler)
        assert result["healthy"] is True
        assert result["status"] == "nomic_dir_not_set"

    def test_empty_metadata_table(self, tmp_nomic_dir):
        """agent_metadata table exists but is empty -> connected with count 0."""
        elo_path = tmp_nomic_dir / "elo.db"
        conn = sqlite3.connect(elo_path)
        conn.execute("CREATE TABLE agent_metadata (id TEXT, name TEXT)")
        conn.commit()
        conn.close()

        h = _make_handler(nomic_dir=tmp_nomic_dir)
        result = check_agent_metadata(h)
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["agent_count"] == 0

    def test_large_metadata_table(self, tmp_nomic_dir):
        """agent_metadata table with many entries returns correct count."""
        elo_path = tmp_nomic_dir / "elo.db"
        conn = sqlite3.connect(elo_path)
        conn.execute("CREATE TABLE agent_metadata (id TEXT, name TEXT)")
        for i in range(50):
            conn.execute(f"INSERT INTO agent_metadata VALUES ('a{i}', 'Agent {i}')")
        conn.commit()
        conn.close()

        h = _make_handler(nomic_dir=tmp_nomic_dir)
        result = check_agent_metadata(h)
        assert result["agent_count"] == 50

    def test_connection_is_closed(self, tmp_nomic_dir):
        """Database connection is properly closed even on success."""
        elo_path = tmp_nomic_dir / "elo.db"
        conn = sqlite3.connect(elo_path)
        conn.execute("CREATE TABLE agent_metadata (id TEXT)")
        conn.commit()
        conn.close()

        h = _make_handler(nomic_dir=tmp_nomic_dir)
        # If connection leaks, subsequent tests may fail on locked db
        check_agent_metadata(h)
        # Verify we can still open the database (no lock held)
        conn2 = sqlite3.connect(elo_path)
        cursor = conn2.execute("SELECT COUNT(*) FROM agent_metadata")
        assert cursor.fetchone()[0] == 0
        conn2.close()

    def test_connection_closed_after_error(self, tmp_nomic_dir):
        """Database connection is closed even when query fails (via finally block)."""
        elo_path = tmp_nomic_dir / "elo.db"
        conn = sqlite3.connect(elo_path)
        conn.execute("CREATE TABLE agent_metadata (id TEXT)")
        conn.commit()
        conn.close()

        h = _make_handler(nomic_dir=tmp_nomic_dir)
        # Use a mock connection to verify close() is called
        mock_conn = MagicMock()
        # First execute (check table existence) returns a cursor with a result
        mock_cursor_1 = MagicMock()
        mock_cursor_1.fetchone.return_value = ("agent_metadata",)
        # Second execute (count) raises an error
        mock_conn.execute.side_effect = [mock_cursor_1, sqlite3.OperationalError("simulated")]

        with patch(
            "aragora.server.handlers.admin.health.database_utils.sqlite3.connect",
            return_value=mock_conn,
        ):
            with pytest.raises(sqlite3.OperationalError):
                check_agent_metadata(h)

        # Verify close was called in the finally block
        mock_conn.close.assert_called_once()


# ============================================================================
# TestCheckIntegrationStore
# ============================================================================


class TestCheckIntegrationStore:
    """Tests for check_integration_store() function."""

    def test_connected(self):
        """Integration store present -> connected."""
        mock_store = MagicMock()
        h = _make_handler({"integration_store": mock_store})
        result = check_integration_store(h)
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["type"] == "MagicMock"

    def test_not_initialized(self, handler):
        """No integration store -> not_initialized with hint."""
        result = check_integration_store(handler)
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result
        assert "auto-create" in result["hint"]

    def test_import_error(self):
        """IntegrationStoreBackend module not available -> ImportError raised."""
        h = _make_handler()
        with patch.dict("sys.modules", {"aragora.storage.integration_store": None}):
            with pytest.raises(ImportError):
                check_integration_store(h)

    def test_import_error_even_with_store_in_ctx(self):
        """Import fails even with a store in ctx (import happens first)."""
        h = _make_handler({"integration_store": MagicMock()})
        with patch.dict("sys.modules", {"aragora.storage.integration_store": None}):
            with pytest.raises(ImportError):
                check_integration_store(h)

    def test_custom_type_name(self):
        """Custom class type name preserved."""

        class PostgresIntegrationStore:
            pass

        h = _make_handler({"integration_store": PostgresIntegrationStore()})
        result = check_integration_store(h)
        assert result["type"] == "PostgresIntegrationStore"


# ============================================================================
# TestCheckGmailTokenStore
# ============================================================================


class TestCheckGmailTokenStore:
    """Tests for check_gmail_token_store() function."""

    def test_connected(self):
        """Gmail token store present -> connected."""
        mock_store = MagicMock()
        h = _make_handler({"gmail_token_store": mock_store})
        result = check_gmail_token_store(h)
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["type"] == "MagicMock"

    def test_not_initialized(self, handler):
        """No Gmail token store -> not_initialized with hint."""
        result = check_gmail_token_store(handler)
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result
        assert "Gmail" in result["hint"]

    def test_import_error(self):
        """GmailTokenStoreBackend module not available -> ImportError raised."""
        h = _make_handler()
        with patch.dict("sys.modules", {"aragora.storage.gmail_token_store": None}):
            with pytest.raises(ImportError):
                check_gmail_token_store(h)

    def test_custom_type_name(self):
        """Custom class type name preserved."""

        class RedisGmailTokenStore:
            pass

        h = _make_handler({"gmail_token_store": RedisGmailTokenStore()})
        result = check_gmail_token_store(h)
        assert result["type"] == "RedisGmailTokenStore"


# ============================================================================
# TestCheckSyncStore
# ============================================================================


class TestCheckSyncStore:
    """Tests for check_sync_store() function."""

    def test_connected(self):
        """Sync store present -> connected."""
        mock_store = MagicMock()
        h = _make_handler({"sync_store": mock_store})
        result = check_sync_store(h)
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["type"] == "MagicMock"

    def test_not_initialized(self, handler):
        """No sync store -> not_initialized with hint."""
        result = check_sync_store(handler)
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result
        assert "enterprise sync" in result["hint"].lower() or "sync" in result["hint"].lower()

    def test_import_error(self):
        """SyncStore module not available -> ImportError raised."""
        h = _make_handler()
        with patch.dict("sys.modules", {"aragora.storage.sync_store": None}):
            with pytest.raises(ImportError):
                check_sync_store(h)

    def test_custom_type_name(self):
        """Custom class type name preserved."""

        class EnterpriseSyncStore:
            pass

        h = _make_handler({"sync_store": EnterpriseSyncStore()})
        result = check_sync_store(h)
        assert result["type"] == "EnterpriseSyncStore"


# ============================================================================
# TestCheckDecisionResultStore
# ============================================================================


class TestCheckDecisionResultStore:
    """Tests for check_decision_result_store() function."""

    def test_connected(self):
        """Decision result store present -> connected."""
        mock_store = MagicMock()
        h = _make_handler({"decision_result_store": mock_store})
        result = check_decision_result_store(h)
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["type"] == "MagicMock"

    def test_not_initialized(self, handler):
        """No decision result store -> not_initialized with hint."""
        result = check_decision_result_store(handler)
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result
        assert "auto-create" in result["hint"]

    def test_import_error(self):
        """DecisionResultStore module not available -> ImportError raised."""
        h = _make_handler()
        with patch.dict("sys.modules", {"aragora.storage.decision_result_store": None}):
            with pytest.raises(ImportError):
                check_decision_result_store(h)

    def test_custom_type_name(self):
        """Custom class type name preserved."""

        class SupabaseDecisionStore:
            pass

        h = _make_handler({"decision_result_store": SupabaseDecisionStore()})
        result = check_decision_result_store(h)
        assert result["type"] == "SupabaseDecisionStore"


# ============================================================================
# TestHandleStoreCheckErrorsWithRealFunctions
# ============================================================================


class TestHandleStoreCheckErrorsWithRealFunctions:
    """Tests combining handle_store_check_errors with each check function."""

    def test_debate_storage_wrapped(self):
        """Debate storage check wrapped in error handler catches sqlite3 error."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = sqlite3.OperationalError("locked")
        h = _make_handler({"storage": mock_storage})

        result, healthy = handle_store_check_errors(
            "debate_storage", lambda: check_debate_storage(h)
        )
        assert healthy is False
        assert result["error_type"] == "database"

    def test_elo_system_wrapped(self):
        """ELO system check wrapped catches OSError."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = OSError("disk full")
        h = _make_handler({"elo_system": mock_elo})

        result, healthy = handle_store_check_errors("elo_system", lambda: check_elo_system(h))
        assert healthy is False
        assert result["error_type"] == "database"

    def test_debate_storage_wrapped_key_error(self):
        """Debate storage KeyError wrapped -> data_access error."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = KeyError("bad key")
        h = _make_handler({"storage": mock_storage})

        result, healthy = handle_store_check_errors(
            "debate_storage", lambda: check_debate_storage(h)
        )
        assert healthy is False
        assert result["error_type"] == "data_access"

    def test_debate_storage_wrapped_type_error(self):
        """Debate storage TypeError wrapped -> data_access error."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = TypeError("bad type")
        h = _make_handler({"storage": mock_storage})

        result, healthy = handle_store_check_errors(
            "debate_storage", lambda: check_debate_storage(h)
        )
        assert healthy is False
        assert result["error_type"] == "data_access"

    def test_debate_storage_wrapped_attribute_error(self):
        """Debate storage AttributeError wrapped -> data_access error."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = AttributeError("no attr")
        h = _make_handler({"storage": mock_storage})

        result, healthy = handle_store_check_errors(
            "debate_storage", lambda: check_debate_storage(h)
        )
        assert healthy is False
        assert result["error_type"] == "data_access"

    def test_debate_storage_wrapped_runtime_error(self):
        """Debate storage RuntimeError wrapped -> generic health check failed."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = RuntimeError("broken")
        h = _make_handler({"storage": mock_storage})

        result, healthy = handle_store_check_errors(
            "debate_storage", lambda: check_debate_storage(h)
        )
        assert healthy is False
        assert result["error"] == "Health check failed"

    def test_debate_storage_wrapped_value_error(self):
        """Debate storage ValueError wrapped -> generic health check failed."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = ValueError("invalid")
        h = _make_handler({"storage": mock_storage})

        result, healthy = handle_store_check_errors(
            "debate_storage", lambda: check_debate_storage(h)
        )
        assert healthy is False
        assert result["error"] == "Health check failed"

    def test_elo_system_wrapped_key_error(self):
        """ELO system KeyError wrapped -> data_access error."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = KeyError("missing")
        h = _make_handler({"elo_system": mock_elo})

        result, healthy = handle_store_check_errors("elo_system", lambda: check_elo_system(h))
        assert healthy is False
        assert result["error_type"] == "data_access"

    def test_elo_system_wrapped_attribute_error(self):
        """ELO system AttributeError wrapped -> data_access error."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = AttributeError("no method")
        h = _make_handler({"elo_system": mock_elo})

        result, healthy = handle_store_check_errors("elo_system", lambda: check_elo_system(h))
        assert healthy is False
        assert result["error_type"] == "data_access"

    def test_consensus_memory_import_error_wrapped(self):
        """ConsensusMemory ImportError wrapped -> module_not_available, healthy."""
        h = _make_handler(nomic_dir=Path("/tmp/fake"))
        with patch.dict("sys.modules", {"aragora.memory.consensus": None}):
            result, healthy = handle_store_check_errors(
                "consensus_memory", lambda: check_consensus_memory(h)
            )
            assert healthy is True
            assert result["status"] == "module_not_available"

    def test_integration_store_import_error_wrapped(self):
        """IntegrationStoreBackend ImportError wrapped -> module_not_available."""
        h = _make_handler()
        with patch.dict("sys.modules", {"aragora.storage.integration_store": None}):
            result, healthy = handle_store_check_errors(
                "integration_store", lambda: check_integration_store(h)
            )
            assert healthy is True
            assert result["status"] == "module_not_available"

    def test_gmail_token_store_import_error_wrapped(self):
        """GmailTokenStoreBackend ImportError wrapped -> module_not_available."""
        h = _make_handler()
        with patch.dict("sys.modules", {"aragora.storage.gmail_token_store": None}):
            result, healthy = handle_store_check_errors(
                "gmail_token_store", lambda: check_gmail_token_store(h)
            )
            assert healthy is True
            assert result["status"] == "module_not_available"

    def test_sync_store_import_error_wrapped(self):
        """SyncStore ImportError wrapped -> module_not_available."""
        h = _make_handler()
        with patch.dict("sys.modules", {"aragora.storage.sync_store": None}):
            result, healthy = handle_store_check_errors("sync_store", lambda: check_sync_store(h))
            assert healthy is True
            assert result["status"] == "module_not_available"

    def test_decision_result_store_import_error_wrapped(self):
        """DecisionResultStore ImportError wrapped -> module_not_available."""
        h = _make_handler()
        with patch.dict("sys.modules", {"aragora.storage.decision_result_store": None}):
            result, healthy = handle_store_check_errors(
                "decision_result_store", lambda: check_decision_result_store(h)
            )
            assert healthy is True
            assert result["status"] == "module_not_available"


# ============================================================================
# TestCrossCutting
# ============================================================================


class TestCrossCutting:
    """Cross-cutting contract tests for all check functions."""

    def test_all_check_functions_return_dict(self, handler):
        """All check functions return a dict."""
        results = [
            check_debate_storage(handler),
            check_elo_system(handler),
            check_insight_store(handler),
            check_flip_detector(handler),
            check_user_store(handler),
        ]
        for result in results:
            assert isinstance(result, dict)

    def test_all_check_functions_have_healthy_key(self, handler):
        """All check functions include a 'healthy' key."""
        results = [
            check_debate_storage(handler),
            check_elo_system(handler),
            check_insight_store(handler),
            check_flip_detector(handler),
            check_user_store(handler),
        ]
        for result in results:
            assert "healthy" in result

    def test_all_check_functions_have_status_key(self, handler):
        """All check functions include a 'status' key."""
        results = [
            check_debate_storage(handler),
            check_elo_system(handler),
            check_insight_store(handler),
            check_flip_detector(handler),
            check_user_store(handler),
        ]
        for result in results:
            assert "status" in result

    def test_all_stores_healthy_when_not_initialized(self, handler):
        """When not initialized, all stores report healthy=True."""
        results = [
            check_debate_storage(handler),
            check_elo_system(handler),
            check_insight_store(handler),
            check_flip_detector(handler),
            check_user_store(handler),
        ]
        for result in results:
            assert result["healthy"] is True
            assert result["status"] == "not_initialized"

    def test_all_stores_healthy_when_connected(self):
        """When stores are connected, all report healthy=True."""
        mock_storage = MagicMock()
        mock_storage.list_recent.return_value = []
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.return_value = []

        h = _make_handler(
            {
                "storage": mock_storage,
                "elo_system": mock_elo,
                "insight_store": MagicMock(),
                "flip_detector": MagicMock(),
                "user_store": MagicMock(),
            }
        )

        results = [
            check_debate_storage(h),
            check_elo_system(h),
            check_insight_store(h),
            check_flip_detector(h),
            check_user_store(h),
        ]
        for result in results:
            assert result["healthy"] is True
            assert result["status"] == "connected"

    def test_consensus_memory_always_healthy(self, handler, tmp_nomic_dir):
        """Consensus memory check returns healthy=True in all non-error states."""
        # No nomic dir
        assert check_consensus_memory(handler)["healthy"] is True
        # Nomic dir, no db file
        h2 = _make_handler(nomic_dir=tmp_nomic_dir)
        assert check_consensus_memory(h2)["healthy"] is True
        # Nomic dir, db file exists
        (tmp_nomic_dir / "consensus_memory.db").touch()
        assert check_consensus_memory(h2)["healthy"] is True

    def test_agent_metadata_always_healthy(self, handler, tmp_nomic_dir):
        """Agent metadata check returns healthy=True in all non-error states."""
        # No nomic dir
        assert check_agent_metadata(handler)["healthy"] is True
        # Nomic dir, no elo.db
        h2 = _make_handler(nomic_dir=tmp_nomic_dir)
        assert check_agent_metadata(h2)["healthy"] is True
        # Nomic dir, elo.db without table
        elo_path = tmp_nomic_dir / "elo.db"
        conn = sqlite3.connect(elo_path)
        conn.execute("CREATE TABLE other (id TEXT)")
        conn.commit()
        conn.close()
        assert check_agent_metadata(h2)["healthy"] is True


# ============================================================================
# TestSecurityEdgeCases
# ============================================================================


class TestSecurityEdgeCases:
    """Security and edge case tests."""

    def test_handle_store_check_errors_does_not_leak_traceback(self):
        """Error result does not contain traceback information."""

        def check():
            raise RuntimeError("secret internal error with /path/to/secret")

        result, _ = handle_store_check_errors("test_store", check)
        result_str = str(result)
        assert "/path/to/secret" not in result_str

    def test_handle_store_check_errors_does_not_leak_db_path(self):
        """Error result does not contain database path."""

        def check():
            raise sqlite3.OperationalError("unable to open database file: /var/data/secrets.db")

        result, _ = handle_store_check_errors("test_store", check)
        assert "/var/data/secrets.db" not in str(result)

    def test_ctx_with_none_values(self):
        """Handler with None values in ctx does not crash."""
        h = _make_handler(
            {
                "insight_store": None,
                "flip_detector": None,
                "user_store": None,
                "integration_store": None,
                "gmail_token_store": None,
                "sync_store": None,
                "decision_result_store": None,
            }
        )
        assert check_insight_store(h)["status"] == "not_initialized"
        assert check_flip_detector(h)["status"] == "not_initialized"
        assert check_user_store(h)["status"] == "not_initialized"
        assert check_integration_store(h)["status"] == "not_initialized"
        assert check_gmail_token_store(h)["status"] == "not_initialized"
        assert check_sync_store(h)["status"] == "not_initialized"
        assert check_decision_result_store(h)["status"] == "not_initialized"

    def test_handler_with_empty_ctx(self, handler):
        """Empty context handler returns not_initialized for all ctx-based stores."""
        stores_to_check = [
            check_insight_store,
            check_flip_detector,
            check_user_store,
        ]
        for check_fn in stores_to_check:
            result = check_fn(handler)
            assert result["healthy"] is True
            assert result["status"] == "not_initialized"

    def test_nomic_dir_as_nonexistent_path(self):
        """Handler with nonexistent nomic_dir path for agent_metadata."""
        h = _make_handler(nomic_dir=Path("/nonexistent/dir/that/does/not/exist"))
        result = check_agent_metadata(h)
        assert result["healthy"] is True
        assert result["status"] == "database_not_exists"

    def test_nomic_dir_as_nonexistent_path_for_consensus(self):
        """Handler with nonexistent nomic_dir path for consensus."""
        h = _make_handler(nomic_dir=Path("/nonexistent/dir/that/does/not/exist"))
        result = check_consensus_memory(h)
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"

    def test_handle_store_check_errors_with_empty_store_name(self):
        """Empty store name does not cause crash."""

        def check():
            return {"healthy": True, "status": "ok"}

        result, healthy = handle_store_check_errors("", check)
        assert healthy is True

    def test_handle_store_check_errors_with_special_chars_in_name(self):
        """Store name with special characters does not cause crash."""

        def check():
            raise RuntimeError("fail")

        result, healthy = handle_store_check_errors("<script>alert('xss')</script>", check)
        assert healthy is False
        assert result["error"] == "Health check failed"

    def test_multiple_consecutive_calls(self, handler):
        """Multiple consecutive calls to the same check function are idempotent."""
        r1 = check_debate_storage(handler)
        r2 = check_debate_storage(handler)
        assert r1 == r2

    def test_multiple_consecutive_calls_elo(self, handler):
        """Multiple consecutive calls to check_elo_system are idempotent."""
        r1 = check_elo_system(handler)
        r2 = check_elo_system(handler)
        assert r1 == r2

    def test_agent_metadata_with_corrupted_db(self, tmp_nomic_dir):
        """Corrupted database file raises error (not a valid SQLite database)."""
        elo_path = tmp_nomic_dir / "elo.db"
        elo_path.write_text("this is not a sqlite database")

        h = _make_handler(nomic_dir=tmp_nomic_dir)
        # Should raise sqlite3.DatabaseError
        with pytest.raises(sqlite3.DatabaseError):
            check_agent_metadata(h)

    def test_agent_metadata_corrupted_db_wrapped(self, tmp_nomic_dir):
        """Corrupted database wrapped in error handler -> database error."""
        elo_path = tmp_nomic_dir / "elo.db"
        elo_path.write_text("this is not a sqlite database")

        h = _make_handler(nomic_dir=tmp_nomic_dir)
        result, healthy = handle_store_check_errors(
            "agent_metadata", lambda: check_agent_metadata(h)
        )
        assert healthy is False
        assert result["error_type"] == "database"

    def test_debate_storage_none_handler_storage(self):
        """Handler returning None from get_storage -> not_initialized."""
        h = _make_handler()
        assert h.get_storage() is None
        result = check_debate_storage(h)
        assert result["status"] == "not_initialized"

    def test_elo_system_none_handler_elo(self):
        """Handler returning None from get_elo_system -> not_initialized."""
        h = _make_handler()
        assert h.get_elo_system() is None
        result = check_elo_system(h)
        assert result["status"] == "not_initialized"

    def test_consensus_memory_none_handler_nomic_dir(self):
        """Handler returning None from get_nomic_dir -> nomic_dir_not_set."""
        h = _make_handler()
        assert h.get_nomic_dir() is None
        result = check_consensus_memory(h)
        assert result["status"] == "nomic_dir_not_set"

    def test_handle_store_check_errors_file_not_found(self):
        """FileNotFoundError (subclass of OSError) -> database error."""

        def check():
            raise FileNotFoundError("No such file: /tmp/missing.db")

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is False
        assert result["error_type"] == "database"

    def test_handle_store_check_errors_permission_error(self):
        """PermissionError (subclass of OSError) -> database error."""

        def check():
            raise PermissionError("Permission denied: /var/data/db")

        result, healthy = handle_store_check_errors("test_store", check)
        assert healthy is False
        assert result["error_type"] == "database"

    def test_path_traversal_in_nomic_dir(self, tmp_path):
        """Path traversal in nomic_dir does not escape sandbox."""
        traversal_dir = tmp_path / ".." / ".." / "etc"
        h = _make_handler(nomic_dir=traversal_dir)
        # Should not crash, just report database_not_exists or not_initialized
        result = check_agent_metadata(h)
        assert result["healthy"] is True


# ============================================================================
# TestReturnValueContracts
# ============================================================================


class TestReturnValueContracts:
    """Verify return value contracts for all functions."""

    def test_handle_store_check_errors_returns_tuple(self):
        """handle_store_check_errors returns (dict, bool)."""
        result = handle_store_check_errors("s", lambda: {"healthy": True})
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], dict)
        assert isinstance(result[1], bool)

    def test_check_debate_storage_returns_dict(self, handler):
        """check_debate_storage returns a dict."""
        assert isinstance(check_debate_storage(handler), dict)

    def test_check_elo_system_returns_dict(self, handler):
        """check_elo_system returns a dict."""
        assert isinstance(check_elo_system(handler), dict)

    def test_check_insight_store_returns_dict(self, handler):
        """check_insight_store returns a dict."""
        assert isinstance(check_insight_store(handler), dict)

    def test_check_flip_detector_returns_dict(self, handler):
        """check_flip_detector returns a dict."""
        assert isinstance(check_flip_detector(handler), dict)

    def test_check_user_store_returns_dict(self, handler):
        """check_user_store returns a dict."""
        assert isinstance(check_user_store(handler), dict)

    def test_check_consensus_memory_returns_dict(self, handler):
        """check_consensus_memory returns a dict."""
        assert isinstance(check_consensus_memory(handler), dict)

    def test_check_agent_metadata_returns_dict(self, handler):
        """check_agent_metadata returns a dict."""
        assert isinstance(check_agent_metadata(handler), dict)

    def test_check_integration_store_returns_dict(self, handler):
        """check_integration_store returns a dict."""
        assert isinstance(check_integration_store(handler), dict)

    def test_check_gmail_token_store_returns_dict(self, handler):
        """check_gmail_token_store returns a dict."""
        assert isinstance(check_gmail_token_store(handler), dict)

    def test_check_sync_store_returns_dict(self, handler):
        """check_sync_store returns a dict."""
        assert isinstance(check_sync_store(handler), dict)

    def test_check_decision_result_store_returns_dict(self, handler):
        """check_decision_result_store returns a dict."""
        assert isinstance(check_decision_result_store(handler), dict)

    def test_connected_results_have_type_key(self):
        """All store checks that report connected include a 'type' key."""
        mock_storage = MagicMock()
        mock_storage.list_recent.return_value = []
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.return_value = []

        h = _make_handler(
            {
                "storage": mock_storage,
                "elo_system": mock_elo,
                "insight_store": MagicMock(),
                "flip_detector": MagicMock(),
                "user_store": MagicMock(),
                "integration_store": MagicMock(),
                "gmail_token_store": MagicMock(),
                "sync_store": MagicMock(),
                "decision_result_store": MagicMock(),
            }
        )

        # debate_storage and elo_system have "type" key
        assert "type" in check_debate_storage(h)
        # Simple ctx-based stores have "type" key
        assert "type" in check_insight_store(h)
        assert "type" in check_flip_detector(h)
        assert "type" in check_user_store(h)
        assert "type" in check_integration_store(h)
        assert "type" in check_gmail_token_store(h)
        assert "type" in check_sync_store(h)
        assert "type" in check_decision_result_store(h)

    def test_elo_connected_has_agent_count(self):
        """ELO system check when connected includes agent_count."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.return_value = [1, 2, 3]
        h = _make_handler({"elo_system": mock_elo})
        result = check_elo_system(h)
        assert "agent_count" in result
        assert result["agent_count"] == 3
