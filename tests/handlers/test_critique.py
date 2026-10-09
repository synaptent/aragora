"""Tests for critique handler (aragora/server/handlers/critique.py).

Covers all routes and behavior of the CritiqueHandler class:
- can_handle() routing for all ROUTES (versioned and unversioned)
- GET /api/critiques/patterns - High-impact critique patterns
- GET /api/critiques/archive - Archive statistics
- GET /api/reputation/all - All agent reputations
- GET /api/agent/:name/reputation - Specific agent reputation
- Rate limiting
- RBAC permission checks
- Error handling and edge cases
- Query parameter parsing (limit, min_success)
- Path traversal protection
- Agent name validation
- Store unavailability scenarios
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.critique import CritiqueHandler, _critique_limiter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: object) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result: object) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


class MockHTTPHandler:
    """Mock HTTP request handler for CritiqueHandler tests."""

    def __init__(
        self,
        body: dict | None = None,
        method: str = "GET",
    ):
        self.command = method
        self.client_address = ("127.0.0.1", 12345)
        self.headers: dict[str, str] = {"User-Agent": "test-agent"}
        self.rfile = MagicMock()

        if body:
            body_bytes = json.dumps(body).encode()
            self.rfile.read.return_value = body_bytes
            self.headers["Content-Length"] = str(len(body_bytes))
        else:
            self.rfile.read.return_value = b"{}"
            self.headers["Content-Length"] = "2"


# ---------------------------------------------------------------------------
# Mock data builders
# ---------------------------------------------------------------------------


@dataclass
class MockPattern:
    """Mock critique pattern returned by store.retrieve_patterns()."""

    issue_type: str = "logic_error"
    pattern_text: str = "Circular reasoning detected"
    success_rate: float = 0.85
    usage_count: int = 42


@dataclass
class MockReputation:
    """Mock reputation record returned by store methods."""

    agent_name: str = "claude"
    reputation_score: float = 0.92
    vote_weight: float = 1.5
    proposal_acceptance_rate: float = 0.78
    critique_value: float = 0.88
    debates_participated: int = 150


class MockCritiqueStore:
    """Mock CritiqueStore for testing handler behavior."""

    def __init__(
        self,
        patterns: list[MockPattern] | None = None,
        stats: dict | None = None,
        archive_stats: dict | None = None,
        reputations: list[MockReputation] | None = None,
        agent_reputation: MockReputation | None = None,
    ):
        self._patterns = patterns or []
        self._stats = stats or {"total_critiques": 100, "unique_patterns": 25}
        self._archive_stats = archive_stats or {"archived": 50, "by_type": {"logic_error": 20}}
        self._reputations = reputations or []
        self._agent_reputation = agent_reputation

    def retrieve_patterns(self, min_success_rate: float = 0.5, limit: int = 10):
        return self._patterns

    def get_stats(self):
        return self._stats

    def get_archive_stats(self):
        return self._archive_stats

    def get_all_reputations(self):
        return self._reputations

    def get_reputation(self, agent: str):
        return self._agent_reputation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a CritiqueHandler with a test nomic_dir."""
    return CritiqueHandler(ctx={"nomic_dir": Path("/tmp/test_nomic")})


@pytest.fixture
def handler_no_dir():
    """Create a CritiqueHandler with no nomic_dir."""
    return CritiqueHandler()


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler."""
    return MockHTTPHandler()


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the rate limiter between tests."""
    _critique_limiter._buckets.clear()
    yield
    _critique_limiter._buckets.clear()


# ---------------------------------------------------------------------------
# can_handle() routing tests
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for CritiqueHandler.can_handle() routing."""

    def test_handles_critiques_patterns(self, handler):
        assert handler.can_handle("/api/critiques/patterns") is True

    def test_handles_critiques_archive(self, handler):
        assert handler.can_handle("/api/critiques/archive") is True

    def test_handles_reputation_all(self, handler):
        assert handler.can_handle("/api/reputation/all") is True

    def test_handles_reputation_history(self, handler):
        assert handler.can_handle("/api/reputation/history") is True

    def test_handles_reputation_domain(self, handler):
        assert handler.can_handle("/api/reputation/domain") is True

    def test_handles_agent_reputation(self, handler):
        assert handler.can_handle("/api/agent/claude/reputation") is True

    def test_handles_agent_reputation_with_version(self, handler):
        assert handler.can_handle("/api/agent/claude-3.5-sonnet/reputation") is True

    def test_handles_versioned_critiques_patterns(self, handler):
        assert handler.can_handle("/api/v1/critiques/patterns") is True

    def test_handles_versioned_critiques_archive(self, handler):
        assert handler.can_handle("/api/v1/critiques/archive") is True

    def test_handles_versioned_reputation_all(self, handler):
        assert handler.can_handle("/api/v1/reputation/all") is True

    def test_handles_versioned_reputation_history(self, handler):
        assert handler.can_handle("/api/v1/reputation/history") is True

    def test_handles_versioned_reputation_domain(self, handler):
        assert handler.can_handle("/api/v1/reputation/domain") is True

    def test_handles_versioned_agent_reputation(self, handler):
        assert handler.can_handle("/api/v1/agent/claude/reputation") is True

    def test_rejects_unknown_path(self, handler):
        assert handler.can_handle("/api/unknown/route") is False

    def test_rejects_partial_critiques_path(self, handler):
        assert handler.can_handle("/api/critiques") is False

    def test_rejects_partial_reputation_path(self, handler):
        assert handler.can_handle("/api/reputation") is False

    def test_rejects_agent_without_reputation_suffix(self, handler):
        assert handler.can_handle("/api/agent/claude") is False

    def test_rejects_empty_path(self, handler):
        assert handler.can_handle("") is False

    def test_rejects_root_path(self, handler):
        assert handler.can_handle("/") is False

    def test_rejects_other_api_endpoints(self, handler):
        assert handler.can_handle("/api/debates") is False

    def test_handles_v2_versioned_path(self, handler):
        assert handler.can_handle("/api/v2/critiques/patterns") is True


# ---------------------------------------------------------------------------
# GET /api/critiques/patterns
# ---------------------------------------------------------------------------


class TestCritiquePatterns:
    """Tests for the /api/critiques/patterns endpoint."""

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_returns_patterns_successfully(self, mock_get_store, handler, mock_http_handler):
        patterns = [
            MockPattern("logic_error", "Circular reasoning", 0.85, 42),
            MockPattern("evidence_gap", "Missing citation", 0.72, 30),
        ]
        mock_store = MockCritiqueStore(
            patterns=patterns,
            stats={"total_critiques": 100},
        )
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/patterns", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["count"] == 2
        assert len(body["patterns"]) == 2
        assert body["patterns"][0]["issue_type"] == "logic_error"
        assert body["patterns"][0]["pattern"] == "Circular reasoning"
        assert body["patterns"][0]["success_rate"] == 0.85
        assert body["patterns"][0]["usage_count"] == 42
        assert body["patterns"][1]["issue_type"] == "evidence_gap"
        assert body["stats"] == {"total_critiques": 100}

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_returns_empty_patterns(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(patterns=[], stats={"total_critiques": 0})
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/patterns", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["count"] == 0
        assert body["patterns"] == []

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_store_returns_none(self, mock_get_store, handler, mock_http_handler):
        mock_get_store.return_value = None

        result = handler.handle("/api/critiques/patterns", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["patterns"] == []
        assert body["count"] == 0

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", False)
    def test_store_unavailable(self, handler, mock_http_handler):
        result = handler.handle("/api/critiques/patterns", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 503
        assert "not available" in body.get("error", "").lower()

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_limit_param_passed(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/patterns", {"limit": "5"}, mock_http_handler)

        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=0.5, limit=5)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_min_success_param_passed(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/patterns", {"min_success": "0.8"}, mock_http_handler)

        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=0.8, limit=10)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_both_params_passed(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle(
            "/api/critiques/patterns",
            {"limit": "20", "min_success": "0.9"},
            mock_http_handler,
        )

        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=0.9, limit=20)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_limit_clamped_to_max(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/patterns", {"limit": "1000"}, mock_http_handler)

        # Clamped to max_val=50
        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=0.5, limit=50)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_limit_clamped_to_min(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/patterns", {"limit": "0"}, mock_http_handler)

        # Clamped to min_val=1
        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=0.5, limit=1)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_min_success_bounded_to_max(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/patterns", {"min_success": "2.0"}, mock_http_handler)

        # Bounded to max_val=1.0
        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=1.0, limit=10)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_min_success_bounded_to_min(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/patterns", {"min_success": "-1.0"}, mock_http_handler)

        # Bounded to min_val=0.0
        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=0.0, limit=10)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_invalid_limit_uses_default(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/patterns", {"limit": "notanumber"}, mock_http_handler)

        # Falls back to default=10
        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=0.5, limit=10)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_invalid_min_success_uses_default(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/patterns", {"min_success": "abc"}, mock_http_handler)

        # Falls back to default=0.5
        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=0.5, limit=10)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_key_error_returns_500(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.side_effect = KeyError("missing_key")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/patterns", {}, mock_http_handler)

        assert _status(result) == 500

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_value_error_returns_500(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.side_effect = ValueError("bad value")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/patterns", {}, mock_http_handler)

        assert _status(result) == 500

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_os_error_returns_500(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.side_effect = OSError("disk error")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/patterns", {}, mock_http_handler)

        assert _status(result) == 500

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_type_error_returns_500(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.side_effect = TypeError("type mismatch")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/patterns", {}, mock_http_handler)

        assert _status(result) == 500

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_attribute_error_returns_500(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.side_effect = AttributeError("no such attr")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/patterns", {}, mock_http_handler)

        assert _status(result) == 500

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_versioned_path(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(
            patterns=[MockPattern()],
            stats={"total": 1},
        )
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/v1/critiques/patterns", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["count"] == 1

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_error_in_get_stats(self, mock_get_store, handler, mock_http_handler):
        """Error in get_stats after retrieve_patterns succeeds."""
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.side_effect = ValueError("stats error")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/patterns", {}, mock_http_handler)

        assert _status(result) == 500


# ---------------------------------------------------------------------------
# GET /api/critiques/archive
# ---------------------------------------------------------------------------


class TestArchiveStats:
    """Tests for the /api/critiques/archive endpoint."""

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_returns_archive_stats(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(
            archive_stats={"archived": 50, "by_type": {"logic_error": 20, "bias": 15}}
        )
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/archive", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["archived"] == 50
        assert body["by_type"]["logic_error"] == 20
        assert body["by_type"]["bias"] == 15

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_store_returns_none(self, mock_get_store, handler, mock_http_handler):
        mock_get_store.return_value = None

        result = handler.handle("/api/critiques/archive", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["archived"] == 0
        assert body["by_type"] == {}

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", False)
    def test_store_unavailable(self, handler, mock_http_handler):
        result = handler.handle("/api/critiques/archive", {}, mock_http_handler)

        assert _status(result) == 503

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_key_error_returns_500(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.get_archive_stats.side_effect = KeyError("missing")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/archive", {}, mock_http_handler)

        assert _status(result) == 500

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_os_error_returns_500(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.get_archive_stats.side_effect = OSError("disk failure")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/archive", {}, mock_http_handler)

        assert _status(result) == 500

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_versioned_path(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(archive_stats={"archived": 10, "by_type": {}})
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/v1/critiques/archive", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["archived"] == 10

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_empty_archive(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(archive_stats={"archived": 0, "by_type": {}})
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/archive", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["archived"] == 0


# ---------------------------------------------------------------------------
# GET /api/reputation/all
# ---------------------------------------------------------------------------


class TestAllReputations:
    """Tests for the /api/reputation/all endpoint."""

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_returns_all_reputations(self, mock_get_store, handler, mock_http_handler):
        reps = [
            MockReputation("claude", 0.92, 1.5, 0.78, 0.88, 150),
            MockReputation("gpt4", 0.87, 1.3, 0.72, 0.80, 120),
        ]
        mock_store = MockCritiqueStore(reputations=reps)
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/reputation/all", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["count"] == 2
        assert len(body["reputations"]) == 2
        assert body["reputations"][0]["agent"] == "claude"
        assert body["reputations"][0]["score"] == 0.92
        assert body["reputations"][0]["vote_weight"] == 1.5
        assert body["reputations"][0]["proposal_acceptance_rate"] == 0.78
        assert body["reputations"][0]["critique_value"] == 0.88
        assert body["reputations"][0]["debates_participated"] == 150
        assert body["reputations"][1]["agent"] == "gpt4"

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_empty_reputations(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(reputations=[])
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/reputation/all", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["count"] == 0
        assert body["reputations"] == []

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_store_returns_none(self, mock_get_store, handler, mock_http_handler):
        mock_get_store.return_value = None

        result = handler.handle("/api/reputation/all", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["reputations"] == []
        assert body["count"] == 0

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", False)
    def test_store_unavailable(self, handler, mock_http_handler):
        result = handler.handle("/api/reputation/all", {}, mock_http_handler)

        assert _status(result) == 503

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_key_error_returns_500(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.get_all_reputations.side_effect = KeyError("key")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/reputation/all", {}, mock_http_handler)

        assert _status(result) == 500

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_value_error_returns_500(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.get_all_reputations.side_effect = ValueError("val")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/reputation/all", {}, mock_http_handler)

        assert _status(result) == 500

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_type_error_returns_500(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.get_all_reputations.side_effect = TypeError("type")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/reputation/all", {}, mock_http_handler)

        assert _status(result) == 500

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_versioned_path(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(
            reputations=[MockReputation("claude", 0.9, 1.2, 0.7, 0.8, 100)]
        )
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/v1/reputation/all", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["count"] == 1


# ---------------------------------------------------------------------------
# GET /api/agent/:name/reputation
# ---------------------------------------------------------------------------


class TestAgentReputation:
    """Tests for the /api/agent/:name/reputation endpoint."""

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_returns_agent_reputation(self, mock_get_store, handler, mock_http_handler):
        rep = MockReputation("claude", 0.92, 1.5, 0.78, 0.88, 150)
        mock_store = MockCritiqueStore(agent_reputation=rep)
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/agent/claude/reputation", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["agent"] == "claude"
        assert body["reputation"]["score"] == 0.92
        assert body["reputation"]["vote_weight"] == 1.5
        assert body["reputation"]["proposal_acceptance_rate"] == 0.78
        assert body["reputation"]["critique_value"] == 0.88
        assert body["reputation"]["debates_participated"] == 150

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_agent_not_found(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(agent_reputation=None)
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/agent/unknown-agent/reputation", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["agent"] == "unknown-agent"
        assert body["reputation"] is None
        assert "not found" in body.get("message", "").lower()

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_store_returns_none(self, mock_get_store, handler, mock_http_handler):
        mock_get_store.return_value = None

        result = handler.handle("/api/agent/claude/reputation", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["agent"] == "claude"
        assert body["reputation"] is None
        assert "no reputation data" in body.get("message", "").lower()

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", False)
    def test_store_unavailable(self, handler, mock_http_handler):
        result = handler.handle("/api/agent/claude/reputation", {}, mock_http_handler)

        assert _status(result) == 503

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_versioned_path(self, mock_get_store, handler, mock_http_handler):
        rep = MockReputation("gpt4", 0.85, 1.2, 0.70, 0.75, 80)
        mock_store = MockCritiqueStore(agent_reputation=rep)
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/v1/agent/gpt4/reputation", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["agent"] == "gpt4"
        assert body["reputation"]["score"] == 0.85

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_agent_with_version_dots(self, mock_get_store, handler, mock_http_handler):
        rep = MockReputation("claude-3.5-sonnet", 0.95, 1.8, 0.82, 0.91, 200)
        mock_store = MockCritiqueStore(agent_reputation=rep)
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/agent/claude-3.5-sonnet/reputation", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["agent"] == "claude-3.5-sonnet"

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_key_error_returns_500(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.get_reputation.side_effect = KeyError("bad")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/agent/claude/reputation", {}, mock_http_handler)

        assert _status(result) == 500

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_os_error_returns_500(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.get_reputation.side_effect = OSError("io error")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/agent/claude/reputation", {}, mock_http_handler)

        assert _status(result) == 500

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_attribute_error_returns_500(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.get_reputation.side_effect = AttributeError("no attr")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/agent/claude/reputation", {}, mock_http_handler)

        assert _status(result) == 500


# ---------------------------------------------------------------------------
# Agent name validation and path traversal
# ---------------------------------------------------------------------------


class TestAgentNameValidation:
    """Tests for agent name extraction and validation."""

    def test_path_traversal_blocked(self, handler, mock_http_handler):
        """Path traversal attempts with '..' are rejected."""
        result = handler.handle("/api/agent/../../etc/passwd/reputation", {}, mock_http_handler)

        assert _status(result) == 400

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_valid_agent_name_with_hyphens(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(agent_reputation=None)
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/agent/my-agent/reputation", {}, mock_http_handler)

        assert _status(result) == 200

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_valid_agent_name_with_underscores(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(agent_reputation=None)
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/agent/my_agent/reputation", {}, mock_http_handler)

        assert _status(result) == 200

    def test_empty_agent_name_rejected(self, handler, mock_http_handler):
        """An empty agent name segment should be rejected."""
        result = handler.handle("/api/agent//reputation", {}, mock_http_handler)

        # The path /api/agent//reputation has an empty segment at index 3
        # which won't match the agent reputation pattern (no endswith /reputation)
        # or will fail validation - either way, not a 200 success with data
        assert result is None or _status(result) == 400

    def test_agent_name_with_special_chars_rejected(self, handler, mock_http_handler):
        """Agent names with special characters like spaces or @ are rejected."""
        result = handler.handle("/api/agent/bad agent/reputation", {}, mock_http_handler)

        # Space in URL path would typically be encoded, but if it gets through
        # the validation should reject it
        assert result is None or _status(result) == 400

    def test_path_traversal_double_encoded(self, handler, mock_http_handler):
        """Double-dot traversal should be blocked."""
        result = handler.handle("/api/agent/../admin/reputation", {}, mock_http_handler)

        assert _status(result) == 400

    def test_extract_agent_name_short_path(self, handler):
        """Paths with fewer than 5 segments return None."""
        assert handler._extract_agent_name("/api/agent") is None

    def test_extract_agent_name_valid(self, handler):
        """Valid agent names are extracted correctly."""
        assert handler._extract_agent_name("/api/agent/claude/reputation") == "claude"

    def test_extract_agent_name_with_dots(self, handler):
        """Agent names with version dots are extracted."""
        assert handler._extract_agent_name("/api/agent/claude-3.5/reputation") == "claude-3.5"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Tests for rate limiting on critique endpoints."""

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_request_within_limit(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(archive_stats={"archived": 0, "by_type": {}})
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/archive", {}, mock_http_handler)

        assert _status(result) == 200

    def test_rate_limit_exceeded(self, handler):
        """When rate limit is exceeded, 429 is returned."""
        # Fill up the rate limiter for the test IP
        mock_handler = MockHTTPHandler()
        ip = "127.0.0.1"
        # Manually fill the bucket past the limit
        now = time.time()
        _critique_limiter._buckets[ip] = [now] * 61  # 61 > 60 rpm

        with patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True):
            result = handler.handle("/api/critiques/patterns", {}, mock_handler)

        assert _status(result) == 429
        body = _body(result)
        assert "rate limit" in body.get("error", "").lower()

    def test_different_ips_tracked_separately(self, handler):
        """Different client IPs have separate rate limit buckets."""
        handler1 = MockHTTPHandler()
        handler1.client_address = ("10.0.0.1", 12345)

        handler2 = MockHTTPHandler()
        handler2.client_address = ("10.0.0.2", 12345)

        # Fill bucket for IP 1 only
        now = time.time()
        _critique_limiter._buckets["10.0.0.1"] = [now] * 61

        with (
            patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True),
            patch("aragora.server.handlers.critique.get_critique_store") as mock_get_store,
        ):
            mock_store = MockCritiqueStore(archive_stats={"archived": 0, "by_type": {}})
            mock_get_store.return_value = mock_store

            result1 = handler.handle("/api/critiques/archive", {}, handler1)
            result2 = handler.handle("/api/critiques/archive", {}, handler2)

        assert _status(result1) == 429
        assert _status(result2) == 200


# ---------------------------------------------------------------------------
# Handler initialization
# ---------------------------------------------------------------------------


class TestHandlerInit:
    """Tests for CritiqueHandler initialization."""

    def test_default_context(self):
        handler = CritiqueHandler()
        assert handler.ctx == {}

    def test_custom_context(self):
        ctx = {"nomic_dir": Path("/custom/dir"), "extra": "value"}
        handler = CritiqueHandler(ctx=ctx)
        assert handler.ctx == ctx
        assert handler.ctx["nomic_dir"] == Path("/custom/dir")

    def test_none_context_defaults_to_empty(self):
        handler = CritiqueHandler(ctx=None)
        assert handler.ctx == {}


# ---------------------------------------------------------------------------
# Handle returns None for unmatched paths
# ---------------------------------------------------------------------------


class TestUnmatchedPaths:
    """Tests for paths that are not handled."""

    def test_unmatched_path_returns_none(self, handler, mock_http_handler):
        result = handler.handle("/api/debates", {}, mock_http_handler)

        assert result is None

    def test_unmatched_critiques_subpath_returns_none(self, handler, mock_http_handler):
        result = handler.handle("/api/critiques/unknown", {}, mock_http_handler)

        assert result is None

    def test_unmatched_reputation_subpath_returns_none(self, handler, mock_http_handler):
        # /api/reputation/{name} is served; deeper paths are not.
        result = handler.handle("/api/reputation/unknown/extra", {}, mock_http_handler)

        assert result is None


# ---------------------------------------------------------------------------
# Nomic dir propagation
# ---------------------------------------------------------------------------


class TestNomicDirPropagation:
    """Tests that nomic_dir from context is passed to store."""

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_nomic_dir_from_context(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(archive_stats={"archived": 0, "by_type": {}})
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/archive", {}, mock_http_handler)

        mock_get_store.assert_called_once_with(Path("/tmp/test_nomic"))

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_nomic_dir_none_when_not_in_context(
        self, mock_get_store, handler_no_dir, mock_http_handler
    ):
        mock_store = MockCritiqueStore(archive_stats={"archived": 0, "by_type": {}})
        mock_get_store.return_value = mock_store

        handler_no_dir.handle("/api/critiques/archive", {}, mock_http_handler)

        mock_get_store.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# Sanitized error messages
# ---------------------------------------------------------------------------


class TestSanitizedErrors:
    """Tests that error messages are sanitized for client responses."""

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_os_error_sanitized(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.side_effect = OSError("/secret/path/to/db.sqlite")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/patterns", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 500
        # The error message should NOT contain the secret path
        error_msg = body.get("error", "")
        assert "/secret/path" not in error_msg

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_value_error_sanitized(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.get_all_reputations.side_effect = ValueError(
            "internal detail about column 'api_key'"
        )
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/reputation/all", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 500
        error_msg = body.get("error", "")
        assert "api_key" not in error_msg

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_key_error_sanitized(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.get_archive_stats.side_effect = KeyError("internal_field_name")
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/archive", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 500
        error_msg = body.get("error", "")
        assert "internal_field_name" not in error_msg


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case and boundary tests."""

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_single_pattern(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(
            patterns=[MockPattern()],
            stats={"total": 1},
        )
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/patterns", {}, mock_http_handler)
        body = _body(result)

        assert body["count"] == 1

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_single_reputation(self, mock_get_store, handler, mock_http_handler):
        mock_store = MockCritiqueStore(
            reputations=[MockReputation()],
        )
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/reputation/all", {}, mock_http_handler)
        body = _body(result)

        assert body["count"] == 1

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_limit_boundary_exact_one(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/patterns", {"limit": "1"}, mock_http_handler)

        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=0.5, limit=1)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_limit_boundary_exact_fifty(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/patterns", {"limit": "50"}, mock_http_handler)

        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=0.5, limit=50)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_min_success_boundary_zero(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/patterns", {"min_success": "0.0"}, mock_http_handler)

        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=0.0, limit=10)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_min_success_boundary_one(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/patterns", {"min_success": "1.0"}, mock_http_handler)

        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=1.0, limit=10)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_negative_limit_clamped(self, mock_get_store, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.retrieve_patterns.return_value = []
        mock_store.get_stats.return_value = {}
        mock_get_store.return_value = mock_store

        handler.handle("/api/critiques/patterns", {"limit": "-5"}, mock_http_handler)

        # Negative should be clamped to min_val=1
        mock_store.retrieve_patterns.assert_called_once_with(min_success_rate=0.5, limit=1)

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_reputation_with_zero_score(self, mock_get_store, handler, mock_http_handler):
        rep = MockReputation("newagent", 0.0, 0.0, 0.0, 0.0, 0)
        mock_store = MockCritiqueStore(agent_reputation=rep)
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/agent/newagent/reputation", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["reputation"]["score"] == 0.0
        assert body["reputation"]["debates_participated"] == 0

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_many_reputations(self, mock_get_store, handler, mock_http_handler):
        reps = [MockReputation(f"agent_{i}", 0.5 + i * 0.01, 1.0, 0.5, 0.5, i) for i in range(50)]
        mock_store = MockCritiqueStore(reputations=reps)
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/reputation/all", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["count"] == 50

    @patch("aragora.server.handlers.critique.CRITIQUE_STORE_AVAILABLE", True)
    @patch("aragora.server.handlers.critique.get_critique_store")
    def test_pattern_with_special_characters_in_text(
        self, mock_get_store, handler, mock_http_handler
    ):
        patterns = [MockPattern("logic", 'Pattern with "quotes" & <special> chars', 0.9, 5)]
        mock_store = MockCritiqueStore(
            patterns=patterns,
            stats={"total": 1},
        )
        mock_get_store.return_value = mock_store

        result = handler.handle("/api/critiques/patterns", {}, mock_http_handler)
        body = _body(result)

        assert _status(result) == 200
        assert body["patterns"][0]["pattern"] == 'Pattern with "quotes" & <special> chars'
