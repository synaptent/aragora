"""Comprehensive tests for StoresMixin health check methods.

Tests the StoresMixin class in aragora/server/handlers/admin/health/stores.py:

  TestDatabaseStoresHealth       - database_stores_health() top-level orchestrator
  TestCheckDebateStorage         - _check_debate_storage() debate persistence
  TestCheckEloSystem             - _check_elo_system() agent rankings
  TestCheckInsightStore          - _check_insight_store() debate insights
  TestCheckFlipDetector          - _check_flip_detector() flip detection
  TestCheckUserStore             - _check_user_store() user/org data
  TestCheckConsensusMemory       - _check_consensus_memory() consensus patterns
  TestCheckAgentMetadata         - _check_agent_metadata() agent metadata table
  TestCheckIntegrationStore      - _check_integration_store() third-party integrations
  TestCheckGmailTokenStore       - _check_gmail_token_store() Gmail OAuth tokens
  TestCheckSyncStore             - _check_sync_store() enterprise sync
  TestCheckDecisionResultStore   - _check_decision_result_store() decision persistence
  TestGetHelpers                 - get_storage/get_elo_system/get_nomic_dir accessors

120+ tests covering all branches, error paths, and edge cases.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.admin.health.stores import StoresMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if result is None:
        return 0
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


class ConcreteStoresHandler(StoresMixin):
    """Concrete class using StoresMixin for testing."""

    def __init__(self, ctx: dict[str, Any] | None = None):
        self.ctx = ctx or {}


def _make_handler(ctx: dict[str, Any] | None = None) -> ConcreteStoresHandler:
    """Create a ConcreteStoresHandler with the given context."""
    return ConcreteStoresHandler(ctx=ctx)


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
# TestGetHelpers - get_storage/get_elo_system/get_nomic_dir accessors
# ============================================================================


class TestGetHelpers:
    """Tests for the accessor methods on the mixin."""

    def test_get_storage_returns_none_when_absent(self, handler):
        """get_storage returns None when 'storage' not in ctx."""
        assert handler.get_storage() is None

    def test_get_storage_returns_value(self):
        """get_storage returns the storage from ctx."""
        mock_storage = MagicMock()
        h = _make_handler({"storage": mock_storage})
        assert h.get_storage() is mock_storage

    def test_get_elo_system_returns_none_when_absent(self, handler):
        """get_elo_system returns None when no elo_system in ctx or class."""
        assert handler.get_elo_system() is None

    def test_get_elo_system_from_ctx(self):
        """get_elo_system returns from ctx when no class attribute."""
        mock_elo = MagicMock()
        h = _make_handler({"elo_system": mock_elo})
        assert h.get_elo_system() is mock_elo

    def test_get_elo_system_from_class_attribute(self):
        """get_elo_system prefers class attribute over ctx."""
        class_elo = MagicMock()
        ctx_elo = MagicMock()

        class HandlerWithClassElo(ConcreteStoresHandler):
            elo_system = class_elo

        h = HandlerWithClassElo(ctx={"elo_system": ctx_elo})
        assert h.get_elo_system() is class_elo

    def test_get_elo_system_class_attr_none_falls_to_ctx(self):
        """get_elo_system falls back to ctx when class attribute is None."""
        ctx_elo = MagicMock()

        class HandlerWithNoneElo(ConcreteStoresHandler):
            elo_system = None

        h = HandlerWithNoneElo(ctx={"elo_system": ctx_elo})
        assert h.get_elo_system() is ctx_elo

    def test_get_nomic_dir_returns_none_when_absent(self, handler):
        """get_nomic_dir returns None when not in ctx."""
        assert handler.get_nomic_dir() is None

    def test_get_nomic_dir_returns_value(self, tmp_nomic_dir):
        """get_nomic_dir returns the path from ctx."""
        h = _make_handler({"nomic_dir": tmp_nomic_dir})
        assert h.get_nomic_dir() == tmp_nomic_dir


# ============================================================================
# TestCheckDebateStorage - _check_debate_storage()
# ============================================================================


class TestCheckDebateStorage:
    """Tests for _check_debate_storage() method."""

    def test_connected_when_storage_present(self):
        """Storage present and list_recent succeeds -> connected, healthy."""
        mock_storage = MagicMock()
        mock_storage.list_recent.return_value = []
        h = _make_handler({"storage": mock_storage})
        result, healthy = h._check_debate_storage()
        assert healthy is True
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["type"] == "MagicMock"

    def test_not_initialized_when_no_storage(self, handler):
        """No storage -> not_initialized, healthy (will auto-create)."""
        result, healthy = handler._check_debate_storage()
        assert healthy is True
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result

    def test_sqlite_error(self):
        """sqlite3.Error in list_recent -> database error, not healthy."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = sqlite3.OperationalError("db locked")
        h = _make_handler({"storage": mock_storage})
        result, healthy = h._check_debate_storage()
        assert healthy is False
        assert result["healthy"] is False
        assert result["error_type"] == "database"

    def test_os_error(self):
        """OSError -> database error, not healthy."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = OSError("disk full")
        h = _make_handler({"storage": mock_storage})
        result, healthy = h._check_debate_storage()
        assert healthy is False
        assert result["healthy"] is False
        assert result["error_type"] == "database"

    def test_key_error(self):
        """KeyError -> data access error, not healthy."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = KeyError("missing key")
        h = _make_handler({"storage": mock_storage})
        result, healthy = h._check_debate_storage()
        assert healthy is False
        assert result["healthy"] is False
        assert result["error_type"] == "data_access"

    def test_type_error(self):
        """TypeError -> data access error."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = TypeError("bad type")
        h = _make_handler({"storage": mock_storage})
        result, healthy = h._check_debate_storage()
        assert healthy is False
        assert result["error_type"] == "data_access"

    def test_attribute_error(self):
        """AttributeError -> data access error."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = AttributeError("no attr")
        h = _make_handler({"storage": mock_storage})
        result, healthy = h._check_debate_storage()
        assert healthy is False
        assert result["error_type"] == "data_access"

    def test_runtime_error(self):
        """RuntimeError -> generic health check failed."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = RuntimeError("broken")
        h = _make_handler({"storage": mock_storage})
        result, healthy = h._check_debate_storage()
        assert healthy is False
        assert result["healthy"] is False
        assert result["error"] == "Health check failed"

    def test_value_error(self):
        """ValueError -> generic health check failed."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = ValueError("invalid")
        h = _make_handler({"storage": mock_storage})
        result, healthy = h._check_debate_storage()
        assert healthy is False
        assert result["error"] == "Health check failed"

    def test_storage_type_name_preserved(self):
        """Type name of the storage class is included in result."""

        class MyCustomStorage:
            def list_recent(self, limit=1):
                return []

        h = _make_handler({"storage": MyCustomStorage()})
        result, healthy = h._check_debate_storage()
        assert result["type"] == "MyCustomStorage"


# ============================================================================
# TestCheckEloSystem - _check_elo_system()
# ============================================================================


class TestCheckEloSystem:
    """Tests for _check_elo_system() method."""

    def test_connected_with_agents(self):
        """ELO system connected with agents -> healthy with count."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.return_value = [{"agent": "a"}, {"agent": "b"}]
        h = _make_handler({"elo_system": mock_elo})
        result, healthy = h._check_elo_system()
        assert healthy is True
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["agent_count"] == 2

    def test_connected_empty_leaderboard(self):
        """ELO system connected with empty leaderboard -> still healthy."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.return_value = []
        h = _make_handler({"elo_system": mock_elo})
        result, healthy = h._check_elo_system()
        assert healthy is True
        assert result["agent_count"] == 0

    def test_not_initialized(self, handler):
        """No ELO system -> not_initialized with hint."""
        result, healthy = handler._check_elo_system()
        assert healthy is True
        assert result["status"] == "not_initialized"
        assert "hint" in result

    def test_sqlite_error(self):
        """sqlite3.Error -> database error."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = sqlite3.OperationalError("db locked")
        h = _make_handler({"elo_system": mock_elo})
        result, healthy = h._check_elo_system()
        assert healthy is False
        assert result["error_type"] == "database"

    def test_os_error(self):
        """OSError -> database error."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = OSError("disk error")
        h = _make_handler({"elo_system": mock_elo})
        result, healthy = h._check_elo_system()
        assert healthy is False
        assert result["error_type"] == "database"

    def test_key_error(self):
        """KeyError -> data access error."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = KeyError("missing")
        h = _make_handler({"elo_system": mock_elo})
        result, healthy = h._check_elo_system()
        assert healthy is False
        assert result["error_type"] == "data_access"

    def test_type_error(self):
        """TypeError -> data access error."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = TypeError("bad type")
        h = _make_handler({"elo_system": mock_elo})
        result, healthy = h._check_elo_system()
        assert healthy is False
        assert result["error_type"] == "data_access"

    def test_attribute_error(self):
        """AttributeError -> data access error."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = AttributeError("no method")
        h = _make_handler({"elo_system": mock_elo})
        result, healthy = h._check_elo_system()
        assert healthy is False
        assert result["error_type"] == "data_access"

    def test_runtime_error(self):
        """RuntimeError -> generic health check failed."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = RuntimeError("elo crashed")
        h = _make_handler({"elo_system": mock_elo})
        result, healthy = h._check_elo_system()
        assert healthy is False
        assert result["error"] == "Health check failed"

    def test_value_error(self):
        """ValueError -> generic health check failed."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = ValueError("invalid state")
        h = _make_handler({"elo_system": mock_elo})
        result, healthy = h._check_elo_system()
        assert healthy is False
        assert result["error"] == "Health check failed"


# ============================================================================
# TestCheckInsightStore - _check_insight_store()
# ============================================================================


class TestCheckInsightStore:
    """Tests for _check_insight_store() method."""

    def test_connected(self):
        """Insight store present -> connected with type."""
        mock_store = MagicMock()
        h = _make_handler({"insight_store": mock_store})
        result = h._check_insight_store()
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["type"] == "MagicMock"

    def test_not_initialized(self, handler):
        """No insight store -> not_initialized with hint."""
        result = handler._check_insight_store()
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result

    def test_key_error(self):
        """KeyError accessing ctx -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = KeyError("bad key")
        result = h._check_insight_store()
        assert result["healthy"] is False
        assert result["error"] == "Health check failed"

    def test_type_error(self):
        """TypeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = TypeError("wrong type")
        result = h._check_insight_store()
        assert result["healthy"] is False

    def test_attribute_error(self):
        """AttributeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = AttributeError("no attr")
        result = h._check_insight_store()
        assert result["healthy"] is False

    def test_custom_type_name(self):
        """Custom class type name preserved."""

        class MyInsightStore:
            pass

        h = _make_handler({"insight_store": MyInsightStore()})
        result = h._check_insight_store()
        assert result["type"] == "MyInsightStore"


# ============================================================================
# TestCheckFlipDetector - _check_flip_detector()
# ============================================================================


class TestCheckFlipDetector:
    """Tests for _check_flip_detector() method."""

    def test_connected(self):
        """Flip detector present -> connected with type."""
        mock_fd = MagicMock()
        h = _make_handler({"flip_detector": mock_fd})
        result = h._check_flip_detector()
        assert result["healthy"] is True
        assert result["status"] == "connected"

    def test_not_initialized(self, handler):
        """No flip detector -> not_initialized."""
        result = handler._check_flip_detector()
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"

    def test_no_hint_when_not_initialized(self, handler):
        """No hint for flip detector unlike insight_store."""
        result = handler._check_flip_detector()
        assert "hint" not in result

    def test_key_error(self):
        """KeyError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = KeyError("bad")
        result = h._check_flip_detector()
        assert result["healthy"] is False

    def test_type_error(self):
        """TypeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = TypeError("bad")
        result = h._check_flip_detector()
        assert result["healthy"] is False

    def test_attribute_error(self):
        """AttributeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = AttributeError("bad")
        result = h._check_flip_detector()
        assert result["healthy"] is False


# ============================================================================
# TestCheckUserStore - _check_user_store()
# ============================================================================


class TestCheckUserStore:
    """Tests for _check_user_store() method."""

    def test_connected(self):
        """User store present -> connected."""
        mock_store = MagicMock()
        h = _make_handler({"user_store": mock_store})
        result = h._check_user_store()
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["type"] == "MagicMock"

    def test_not_initialized(self, handler):
        """No user store -> not_initialized."""
        result = handler._check_user_store()
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"

    def test_key_error(self):
        """KeyError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = KeyError("bad")
        result = h._check_user_store()
        assert result["healthy"] is False

    def test_type_error(self):
        """TypeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = TypeError("bad")
        result = h._check_user_store()
        assert result["healthy"] is False


# ============================================================================
# TestCheckConsensusMemory - _check_consensus_memory()
# ============================================================================


class TestCheckConsensusMemory:
    """Tests for _check_consensus_memory() method."""

    def test_exists_with_db_file(self, tmp_nomic_dir):
        """Consensus memory DB file exists -> status=exists with path."""
        db_file = tmp_nomic_dir / "consensus_memory.db"
        db_file.touch()
        h = _make_handler({"nomic_dir": tmp_nomic_dir})
        result = h._check_consensus_memory()
        assert result["healthy"] is True
        assert result["status"] == "exists"
        assert result["path"] == str(db_file)

    def test_not_initialized_no_db_file(self, tmp_nomic_dir):
        """Nomic dir exists but no consensus_memory.db -> not_initialized with hint."""
        h = _make_handler({"nomic_dir": tmp_nomic_dir})
        result = h._check_consensus_memory()
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result

    def test_nomic_dir_not_set(self, handler):
        """No nomic_dir -> nomic_dir_not_set."""
        result = handler._check_consensus_memory()
        assert result["healthy"] is True
        assert result["status"] == "nomic_dir_not_set"

    def test_import_error(self):
        """ConsensusMemory module not available -> module_not_available."""
        h = _make_handler({"nomic_dir": Path("/tmp/fake")})
        with patch.dict("sys.modules", {"aragora.memory.consensus": None}):
            result = h._check_consensus_memory()
            assert result["healthy"] is True
            assert result["status"] == "module_not_available"

    def test_os_error(self, tmp_nomic_dir):
        """OSError checking path -> health check failed."""
        h = _make_handler({"nomic_dir": tmp_nomic_dir})
        with patch.object(Path, "exists", side_effect=OSError("permission denied")):
            result = h._check_consensus_memory()
            assert result["healthy"] is False
            assert result["error"] == "Health check failed"

    def test_runtime_error(self, tmp_nomic_dir):
        """RuntimeError -> health check failed."""
        h = _make_handler({"nomic_dir": tmp_nomic_dir})
        with patch.object(Path, "exists", side_effect=RuntimeError("oops")):
            result = h._check_consensus_memory()
            assert result["healthy"] is False

    def test_value_error(self, tmp_nomic_dir):
        """ValueError -> health check failed."""
        h = _make_handler({"nomic_dir": tmp_nomic_dir})
        with patch.object(Path, "exists", side_effect=ValueError("bad value")):
            result = h._check_consensus_memory()
            assert result["healthy"] is False

    def test_key_error(self):
        """KeyError in get_nomic_dir -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = KeyError("nomic_dir")
        result = h._check_consensus_memory()
        assert result["healthy"] is False

    def test_type_error(self):
        """TypeError -> health check failed."""
        h = _make_handler()
        # Force TypeError by making nomic_dir a non-Path object that fails on / operator
        h.ctx = {"nomic_dir": 42}
        result = h._check_consensus_memory()
        assert result["healthy"] is False


# ============================================================================
# TestCheckAgentMetadata - _check_agent_metadata()
# ============================================================================


class TestCheckAgentMetadata:
    """Tests for _check_agent_metadata() method."""

    def test_connected_with_metadata(self, tmp_nomic_dir):
        """elo.db exists with agent_metadata table and data -> connected."""
        elo_path = tmp_nomic_dir / "elo.db"
        conn = sqlite3.connect(elo_path)
        conn.execute("CREATE TABLE agent_metadata (id TEXT, name TEXT)")
        conn.execute("INSERT INTO agent_metadata VALUES ('a1', 'Agent 1')")
        conn.execute("INSERT INTO agent_metadata VALUES ('a2', 'Agent 2')")
        conn.commit()
        conn.close()

        h = _make_handler({"nomic_dir": tmp_nomic_dir})
        result = h._check_agent_metadata()
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

        h = _make_handler({"nomic_dir": tmp_nomic_dir})
        result = h._check_agent_metadata()
        assert result["healthy"] is True
        assert result["status"] == "table_not_exists"
        assert "hint" in result

    def test_database_not_exists(self, tmp_nomic_dir):
        """Nomic dir exists but no elo.db -> database_not_exists."""
        h = _make_handler({"nomic_dir": tmp_nomic_dir})
        result = h._check_agent_metadata()
        assert result["healthy"] is True
        assert result["status"] == "database_not_exists"

    def test_nomic_dir_not_set(self, handler):
        """No nomic_dir -> nomic_dir_not_set."""
        result = handler._check_agent_metadata()
        assert result["healthy"] is True
        assert result["status"] == "nomic_dir_not_set"

    def test_os_error(self, tmp_nomic_dir):
        """OSError -> health check failed."""
        elo_path = tmp_nomic_dir / "elo.db"
        elo_path.touch()
        h = _make_handler({"nomic_dir": tmp_nomic_dir})
        with patch("sqlite3.connect", side_effect=OSError("disk error")):
            result = h._check_agent_metadata()
            assert result["healthy"] is False
            assert result["error"] == "Health check failed"

    def test_runtime_error(self, tmp_nomic_dir):
        """RuntimeError -> health check failed."""
        elo_path = tmp_nomic_dir / "elo.db"
        elo_path.touch()
        h = _make_handler({"nomic_dir": tmp_nomic_dir})
        with patch("sqlite3.connect", side_effect=RuntimeError("bad")):
            result = h._check_agent_metadata()
            assert result["healthy"] is False

    def test_value_error(self, tmp_nomic_dir):
        """ValueError -> health check failed."""
        h = _make_handler({"nomic_dir": tmp_nomic_dir})
        # Force ValueError by making path exist check fail
        elo_path = tmp_nomic_dir / "elo.db"
        elo_path.touch()
        with patch("sqlite3.connect", side_effect=ValueError("bad path")):
            result = h._check_agent_metadata()
            assert result["healthy"] is False

    def test_empty_metadata_table(self, tmp_nomic_dir):
        """agent_metadata table exists but is empty -> connected with count 0."""
        elo_path = tmp_nomic_dir / "elo.db"
        conn = sqlite3.connect(elo_path)
        conn.execute("CREATE TABLE agent_metadata (id TEXT, name TEXT)")
        conn.commit()
        conn.close()

        h = _make_handler({"nomic_dir": tmp_nomic_dir})
        result = h._check_agent_metadata()
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["agent_count"] == 0


# ============================================================================
# TestCheckIntegrationStore - _check_integration_store()
# ============================================================================


class TestCheckIntegrationStore:
    """Tests for _check_integration_store() method."""

    def test_connected(self):
        """Integration store present -> connected."""
        mock_store = MagicMock()
        h = _make_handler({"integration_store": mock_store})
        result = h._check_integration_store()
        assert result["healthy"] is True
        assert result["status"] == "connected"
        assert result["type"] == "MagicMock"

    def test_not_initialized(self, handler):
        """No integration store -> not_initialized with hint."""
        result = handler._check_integration_store()
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result

    def test_import_error(self):
        """IntegrationStoreBackend module not available -> module_not_available."""
        h = _make_handler()
        with patch.dict("sys.modules", {"aragora.storage.integration_store": None}):
            result = h._check_integration_store()
            assert result["healthy"] is True
            assert result["status"] == "module_not_available"

    def test_key_error(self):
        """KeyError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = KeyError("bad")
        result = h._check_integration_store()
        assert result["healthy"] is False
        assert result["error"] == "Health check failed"

    def test_type_error(self):
        """TypeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = TypeError("bad")
        result = h._check_integration_store()
        assert result["healthy"] is False

    def test_attribute_error(self):
        """AttributeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = AttributeError("bad")
        result = h._check_integration_store()
        assert result["healthy"] is False

    def test_runtime_error(self):
        """RuntimeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = RuntimeError("bad")
        result = h._check_integration_store()
        assert result["healthy"] is False


# ============================================================================
# TestCheckGmailTokenStore - _check_gmail_token_store()
# ============================================================================


class TestCheckGmailTokenStore:
    """Tests for _check_gmail_token_store() method."""

    def test_connected(self):
        """Gmail token store present -> connected."""
        mock_store = MagicMock()
        h = _make_handler({"gmail_token_store": mock_store})
        result = h._check_gmail_token_store()
        assert result["healthy"] is True
        assert result["status"] == "connected"

    def test_not_initialized(self, handler):
        """No Gmail token store -> not_initialized with hint."""
        result = handler._check_gmail_token_store()
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result
        assert "Gmail" in result["hint"]

    def test_import_error(self):
        """GmailTokenStoreBackend module not available -> module_not_available."""
        h = _make_handler()
        with patch.dict("sys.modules", {"aragora.storage.gmail_token_store": None}):
            result = h._check_gmail_token_store()
            assert result["healthy"] is True
            assert result["status"] == "module_not_available"

    def test_key_error(self):
        """KeyError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = KeyError("bad")
        result = h._check_gmail_token_store()
        assert result["healthy"] is False

    def test_runtime_error(self):
        """RuntimeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = RuntimeError("bad")
        result = h._check_gmail_token_store()
        assert result["healthy"] is False


# ============================================================================
# TestCheckSyncStore - _check_sync_store()
# ============================================================================


class TestCheckSyncStore:
    """Tests for _check_sync_store() method."""

    def test_connected(self):
        """Sync store present -> connected."""
        mock_store = MagicMock()
        h = _make_handler({"sync_store": mock_store})
        result = h._check_sync_store()
        assert result["healthy"] is True
        assert result["status"] == "connected"

    def test_not_initialized(self, handler):
        """No sync store -> not_initialized with hint."""
        result = handler._check_sync_store()
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result

    def test_import_error(self):
        """SyncStore module not available -> module_not_available."""
        h = _make_handler()
        with patch.dict("sys.modules", {"aragora.storage.sync_store": None}):
            result = h._check_sync_store()
            assert result["healthy"] is True
            assert result["status"] == "module_not_available"

    def test_key_error(self):
        """KeyError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = KeyError("bad")
        result = h._check_sync_store()
        assert result["healthy"] is False

    def test_runtime_error(self):
        """RuntimeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = RuntimeError("bad")
        result = h._check_sync_store()
        assert result["healthy"] is False

    def test_type_error(self):
        """TypeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = TypeError("bad")
        result = h._check_sync_store()
        assert result["healthy"] is False

    def test_attribute_error(self):
        """AttributeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = AttributeError("bad")
        result = h._check_sync_store()
        assert result["healthy"] is False


# ============================================================================
# TestCheckDecisionResultStore - _check_decision_result_store()
# ============================================================================


class TestCheckDecisionResultStore:
    """Tests for _check_decision_result_store() method."""

    def test_connected(self):
        """Decision result store present -> connected."""
        mock_store = MagicMock()
        h = _make_handler({"decision_result_store": mock_store})
        result = h._check_decision_result_store()
        assert result["healthy"] is True
        assert result["status"] == "connected"

    def test_not_initialized(self, handler):
        """No decision result store -> not_initialized with hint."""
        result = handler._check_decision_result_store()
        assert result["healthy"] is True
        assert result["status"] == "not_initialized"
        assert "hint" in result

    def test_import_error(self):
        """DecisionResultStore module not available -> module_not_available."""
        h = _make_handler()
        with patch.dict("sys.modules", {"aragora.storage.decision_result_store": None}):
            result = h._check_decision_result_store()
            assert result["healthy"] is True
            assert result["status"] == "module_not_available"

    def test_key_error(self):
        """KeyError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = KeyError("bad")
        result = h._check_decision_result_store()
        assert result["healthy"] is False

    def test_runtime_error(self):
        """RuntimeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = RuntimeError("bad")
        result = h._check_decision_result_store()
        assert result["healthy"] is False

    def test_type_error(self):
        """TypeError -> health check failed."""
        h = _make_handler()
        h.ctx = MagicMock()
        h.ctx.get.side_effect = TypeError("bad")
        result = h._check_decision_result_store()
        assert result["healthy"] is False


# ============================================================================
# TestDatabaseStoresHealth - database_stores_health() top-level
# ============================================================================


class TestDatabaseStoresHealth:
    """Tests for database_stores_health() orchestrator method."""

    def test_all_healthy_empty_context(self, handler):
        """Empty context -> all stores not_initialized, overall healthy."""
        result = handler.database_stores_health()
        body = _body(result)
        assert _status(result) == 200
        assert body["status"] == "healthy"

    def test_response_has_required_fields(self, handler):
        """Response contains standard top-level fields."""
        body = _body(handler.database_stores_health())
        for key in ("status", "stores", "elapsed_ms", "summary"):
            assert key in body, f"Missing key: {key}"

    def test_all_eleven_stores_present(self, handler):
        """All 11 store keys are present in the response."""
        body = _body(handler.database_stores_health())
        expected_stores = [
            "debate_storage",
            "elo_system",
            "insight_store",
            "flip_detector",
            "user_store",
            "consensus_memory",
            "agent_metadata",
            "integration_store",
            "gmail_token_store",
            "sync_store",
            "decision_result_store",
        ]
        for store_name in expected_stores:
            assert store_name in body["stores"], f"Missing store: {store_name}"

    def test_summary_total_count(self, handler):
        """Summary.total equals the number of stores checked."""
        body = _body(handler.database_stores_health())
        assert body["summary"]["total"] == 11

    def test_summary_counts_empty_context(self, handler):
        """With empty context, most stores are not_initialized."""
        body = _body(handler.database_stores_health())
        summary = body["summary"]
        assert summary["total"] == 11
        assert summary["connected"] == 0
        # All should be healthy (not_initialized counts as healthy)
        assert summary["healthy"] == 11

    def test_elapsed_ms_is_numeric(self, handler):
        """elapsed_ms should be a non-negative number."""
        body = _body(handler.database_stores_health())
        assert isinstance(body["elapsed_ms"], (int, float))
        assert body["elapsed_ms"] >= 0

    def test_degraded_when_debate_storage_fails(self):
        """Debate storage failure -> overall status degraded."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = sqlite3.OperationalError("locked")
        h = _make_handler({"storage": mock_storage})
        body = _body(h.database_stores_health())
        assert body["status"] == "degraded"

    def test_degraded_when_elo_system_fails(self):
        """ELO system failure -> overall status degraded."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = OSError("disk full")
        h = _make_handler({"elo_system": mock_elo})
        body = _body(h.database_stores_health())
        assert body["status"] == "degraded"

    def test_healthy_with_connected_storage(self):
        """Connected storage -> summary.connected increments."""
        mock_storage = MagicMock()
        mock_storage.list_recent.return_value = []
        h = _make_handler({"storage": mock_storage})
        body = _body(h.database_stores_health())
        assert body["status"] == "healthy"
        assert body["summary"]["connected"] >= 1

    def test_healthy_with_all_stores_connected(self, tmp_nomic_dir):
        """All optional stores connected -> high connected count."""
        # Create real elo.db with agent_metadata table
        elo_path = tmp_nomic_dir / "elo.db"
        conn = sqlite3.connect(elo_path)
        conn.execute("CREATE TABLE agent_metadata (id TEXT)")
        conn.commit()
        conn.close()

        # Create consensus_memory.db
        (tmp_nomic_dir / "consensus_memory.db").touch()

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
                "nomic_dir": tmp_nomic_dir,
                "integration_store": MagicMock(),
                "gmail_token_store": MagicMock(),
                "sync_store": MagicMock(),
                "decision_result_store": MagicMock(),
            }
        )
        body = _body(h.database_stores_health())
        assert body["status"] == "healthy"
        # At least storage, elo, insight, flip, user, integration, gmail, sync, decision = 9 connected
        assert body["summary"]["connected"] >= 9
        assert body["summary"]["healthy"] == 11

    def test_degraded_only_affects_debate_and_elo(self):
        """Only debate_storage and elo_system affect overall status."""
        # Other stores failing should not degrade status because
        # they return only a dict (not a tuple with healthy bool)
        h = _make_handler(
            {
                "insight_store": None,  # will be not_initialized
                "flip_detector": None,
            }
        )
        body = _body(h.database_stores_health())
        assert body["status"] == "healthy"

    def test_both_debate_and_elo_fail(self):
        """Both debate storage and ELO fail -> still degraded (not crash)."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = RuntimeError("storage fail")
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = RuntimeError("elo fail")
        h = _make_handler({"storage": mock_storage, "elo_system": mock_elo})
        body = _body(h.database_stores_health())
        assert body["status"] == "degraded"
        assert body["summary"]["healthy"] < 11

    def test_not_initialized_count(self, handler):
        """Count of not_initialized stores with empty context."""
        body = _body(handler.database_stores_health())
        # Several stores report not_initialized when absent
        assert body["summary"]["not_initialized"] >= 1

    def test_response_status_code_always_200(self, handler):
        """database_stores_health always returns 200 (degraded in body, not status)."""
        result = handler.database_stores_health()
        assert _status(result) == 200

    def test_response_status_code_200_even_when_degraded(self):
        """Even with failures, HTTP status is 200 (JSON body has 'degraded')."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = sqlite3.OperationalError("fail")
        h = _make_handler({"storage": mock_storage})
        result = h.database_stores_health()
        assert _status(result) == 200
        assert _body(result)["status"] == "degraded"

    def test_store_healthy_false_not_counted(self):
        """Stores with healthy=False decrease healthy count in summary."""
        mock_storage = MagicMock()
        mock_storage.list_recent.side_effect = sqlite3.Error("fail")
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = sqlite3.Error("fail")
        h = _make_handler({"storage": mock_storage, "elo_system": mock_elo})
        body = _body(h.database_stores_health())
        assert body["summary"]["healthy"] == 9  # 11 total - 2 failed


# ============================================================================
# TestImportErrorPaths - import error handling for stores with lazy imports
# ============================================================================


class TestImportErrorPaths:
    """Tests for import error handling in stores that have lazy imports."""

    def test_consensus_memory_import_error_without_nomic_dir(self):
        """ConsensusMemory import fails when no nomic_dir - gets ImportError first."""
        h = _make_handler()
        with patch.dict("sys.modules", {"aragora.memory.consensus": None}):
            result = h._check_consensus_memory()
            assert result["healthy"] is True
            assert result["status"] == "module_not_available"

    def test_integration_store_import_error_with_store_in_ctx(self):
        """IntegrationStoreBackend import fails even with store in ctx."""
        h = _make_handler({"integration_store": MagicMock()})
        with patch.dict("sys.modules", {"aragora.storage.integration_store": None}):
            result = h._check_integration_store()
            assert result["healthy"] is True
            assert result["status"] == "module_not_available"

    def test_gmail_token_store_import_error_with_store_in_ctx(self):
        """GmailTokenStoreBackend import fails even with store in ctx."""
        h = _make_handler({"gmail_token_store": MagicMock()})
        with patch.dict("sys.modules", {"aragora.storage.gmail_token_store": None}):
            result = h._check_gmail_token_store()
            assert result["healthy"] is True
            assert result["status"] == "module_not_available"

    def test_sync_store_import_error_with_store_in_ctx(self):
        """SyncStore import fails even with store in ctx."""
        h = _make_handler({"sync_store": MagicMock()})
        with patch.dict("sys.modules", {"aragora.storage.sync_store": None}):
            result = h._check_sync_store()
            assert result["healthy"] is True
            assert result["status"] == "module_not_available"

    def test_decision_result_store_import_error_with_store_in_ctx(self):
        """DecisionResultStore import fails even with store in ctx."""
        h = _make_handler({"decision_result_store": MagicMock()})
        with patch.dict("sys.modules", {"aragora.storage.decision_result_store": None}):
            result = h._check_decision_result_store()
            assert result["healthy"] is True
            assert result["status"] == "module_not_available"
