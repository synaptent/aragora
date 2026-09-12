"""Comprehensive tests for RelationshipHandler.

Tests cover all endpoints:
- GET /api/v1/agents/{name}/relationships          - Rivals + allies for an agent
- GET /api/v1/agents/{name}/relationships/{other}   - Pairwise metrics between two agents

Each endpoint is tested for:
- Happy path with valid data
- No tracker available (graceful fallback)
- Input validation (agent name pattern)
- Limit clamping and defaults
- Edge cases (empty results, swapped agent names in relationships)
- Path matching (can_handle positive and negative cases)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: object) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result: object) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if result is None:
        return 0
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


# ---------------------------------------------------------------------------
# Mock relationship data objects
# ---------------------------------------------------------------------------


@dataclass
class MockRelationship:
    """Minimal relationship object returned by RelationshipTracker."""

    agent_a: str
    agent_b: str
    rivalry_score: float = 0.0
    alliance_score: float = 0.0
    debate_count: int = 0
    relationship: str = "neutral"
    agreement_rate: float = 0.5
    head_to_head: dict | None = None

    def __post_init__(self):
        if self.head_to_head is None:
            self.head_to_head = {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a RelationshipHandler instance."""
    from aragora.server.handlers.agents.relationships import RelationshipHandler

    return RelationshipHandler()


@pytest.fixture
def handler_with_ctx():
    """Create a RelationshipHandler instance with custom context."""
    from aragora.server.handlers.agents.relationships import RelationshipHandler

    return RelationshipHandler(ctx={"custom": True})


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler."""
    h = MagicMock()
    h.rfile = MagicMock()
    h.rfile.read.return_value = b"{}"
    h.headers = {"Content-Length": "2"}
    return h


@pytest.fixture
def mock_tracker():
    """Create a mock RelationshipTracker."""
    tracker = MagicMock()
    tracker.get_rivals.return_value = []
    tracker.get_allies.return_value = []
    tracker.compute_metrics.return_value = MockRelationship(
        agent_a="claude",
        agent_b="gpt4",
        debate_count=10,
        rivalry_score=0.7,
        alliance_score=0.3,
        relationship="rival",
        agreement_rate=0.35,
        head_to_head={"claude": 6, "gpt4": 4},
    )
    return tracker


# ---------------------------------------------------------------------------
# can_handle tests
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for RelationshipHandler.can_handle path matching."""

    def test_can_handle_summary_path(self, handler):
        assert handler.can_handle("/api/v1/agents/claude/relationships") is True

    def test_can_handle_pairwise_path(self, handler):
        assert handler.can_handle("/api/v1/agents/claude/relationships/gpt4") is True

    def test_can_handle_without_version_prefix(self, handler):
        assert handler.can_handle("/api/agents/claude/relationships") is True

    def test_can_handle_without_version_prefix_pairwise(self, handler):
        assert handler.can_handle("/api/agents/claude/relationships/gpt4") is True

    def test_cannot_handle_root_agents(self, handler):
        assert handler.can_handle("/api/v1/agents") is False

    def test_cannot_handle_agent_detail(self, handler):
        assert handler.can_handle("/api/v1/agents/claude") is False

    def test_cannot_handle_different_subpath(self, handler):
        assert handler.can_handle("/api/v1/agents/claude/rankings") is False

    def test_cannot_handle_unrelated_path(self, handler):
        assert handler.can_handle("/api/v1/debates/123") is False

    def test_cannot_handle_partial_match(self, handler):
        assert handler.can_handle("/api/v1/other/claude/relationships") is False

    def test_cannot_handle_empty_path(self, handler):
        assert handler.can_handle("") is False

    def test_cannot_handle_slash(self, handler):
        assert handler.can_handle("/") is False

    def test_cannot_handle_no_api_prefix(self, handler):
        assert handler.can_handle("/agents/claude/relationships") is False


# ---------------------------------------------------------------------------
# Constructor tests
# ---------------------------------------------------------------------------


class TestConstructor:
    """Tests for RelationshipHandler construction."""

    def test_default_ctx(self, handler):
        assert handler.ctx == {}

    def test_custom_ctx(self, handler_with_ctx):
        assert handler_with_ctx.ctx == {"custom": True}

    def test_none_ctx_becomes_empty_dict(self):
        from aragora.server.handlers.agents.relationships import RelationshipHandler

        h = RelationshipHandler(ctx=None)
        assert h.ctx == {}


# ---------------------------------------------------------------------------
# ROUTES class attribute
# ---------------------------------------------------------------------------


class TestRoutes:
    """Tests for the ROUTES class attribute."""

    def test_routes_defined(self, handler):
        assert hasattr(handler, "ROUTES")
        assert len(handler.ROUTES) == 2

    def test_routes_include_summary(self, handler):
        assert "/api/v1/agents/*/relationships" in handler.ROUTES

    def test_routes_include_pairwise(self, handler):
        assert "/api/v1/agents/*/relationships/*" in handler.ROUTES


# ---------------------------------------------------------------------------
# handle - summary endpoint
# ---------------------------------------------------------------------------


class TestHandleSummary:
    """Tests for GET /api/v1/agents/{name}/relationships."""

    @patch(
        "aragora.server.handlers.agents.relationships._get_relationship_tracker",
        return_value=None,
    )
    def test_summary_no_tracker_returns_empty(self, mock_get_tracker, handler, mock_http_handler):
        result = handler.handle("/api/v1/agents/claude/relationships", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert body["agent"] == "claude"
        assert body["rivals"] == []
        assert body["allies"] == []

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_summary_with_rivals_and_allies(self, mock_get_tracker, handler, mock_http_handler):
        tracker = MagicMock()
        tracker.get_rivals.return_value = [
            MockRelationship(
                agent_a="claude",
                agent_b="gpt4",
                rivalry_score=0.8,
                debate_count=15,
                relationship="rival",
            ),
        ]
        tracker.get_allies.return_value = [
            MockRelationship(
                agent_a="claude",
                agent_b="gemini",
                alliance_score=0.9,
                debate_count=12,
                relationship="ally",
            ),
        ]
        mock_get_tracker.return_value = tracker

        result = handler.handle("/api/v1/agents/claude/relationships", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert body["agent"] == "claude"
        assert len(body["rivals"]) == 1
        assert body["rivals"][0]["agent"] == "gpt4"
        assert body["rivals"][0]["rivalry_score"] == 0.8
        assert body["rivals"][0]["debate_count"] == 15
        assert body["rivals"][0]["relationship"] == "rival"
        assert len(body["allies"]) == 1
        assert body["allies"][0]["agent"] == "gemini"
        assert body["allies"][0]["alliance_score"] == 0.9

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_summary_default_limit_is_5(self, mock_get_tracker, handler, mock_http_handler):
        tracker = MagicMock()
        tracker.get_rivals.return_value = []
        tracker.get_allies.return_value = []
        mock_get_tracker.return_value = tracker

        handler.handle("/api/v1/agents/claude/relationships", {}, mock_http_handler)
        tracker.get_rivals.assert_called_once_with("claude", limit=5)
        tracker.get_allies.assert_called_once_with("claude", limit=5)

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_summary_custom_limit(self, mock_get_tracker, handler, mock_http_handler):
        tracker = MagicMock()
        tracker.get_rivals.return_value = []
        tracker.get_allies.return_value = []
        mock_get_tracker.return_value = tracker

        handler.handle("/api/v1/agents/claude/relationships", {"limit": "10"}, mock_http_handler)
        tracker.get_rivals.assert_called_once_with("claude", limit=10)
        tracker.get_allies.assert_called_once_with("claude", limit=10)

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_summary_limit_clamped_to_min_1(self, mock_get_tracker, handler, mock_http_handler):
        tracker = MagicMock()
        tracker.get_rivals.return_value = []
        tracker.get_allies.return_value = []
        mock_get_tracker.return_value = tracker

        handler.handle("/api/v1/agents/claude/relationships", {"limit": "0"}, mock_http_handler)
        tracker.get_rivals.assert_called_once_with("claude", limit=1)

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_summary_limit_clamped_to_max_20(self, mock_get_tracker, handler, mock_http_handler):
        tracker = MagicMock()
        tracker.get_rivals.return_value = []
        tracker.get_allies.return_value = []
        mock_get_tracker.return_value = tracker

        handler.handle("/api/v1/agents/claude/relationships", {"limit": "100"}, mock_http_handler)
        tracker.get_rivals.assert_called_once_with("claude", limit=20)

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_summary_negative_limit_clamped_to_1(
        self, mock_get_tracker, handler, mock_http_handler
    ):
        tracker = MagicMock()
        tracker.get_rivals.return_value = []
        tracker.get_allies.return_value = []
        mock_get_tracker.return_value = tracker

        handler.handle("/api/v1/agents/claude/relationships", {"limit": "-5"}, mock_http_handler)
        tracker.get_rivals.assert_called_once_with("claude", limit=1)

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_summary_invalid_limit_uses_default(self, mock_get_tracker, handler, mock_http_handler):
        tracker = MagicMock()
        tracker.get_rivals.return_value = []
        tracker.get_allies.return_value = []
        mock_get_tracker.return_value = tracker

        handler.handle("/api/v1/agents/claude/relationships", {"limit": "abc"}, mock_http_handler)
        tracker.get_rivals.assert_called_once_with("claude", limit=5)

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_summary_agent_name_swapped_in_rival(
        self, mock_get_tracker, handler, mock_http_handler
    ):
        """When agent_a != queried agent, the rival's name is agent_a."""
        tracker = MagicMock()
        tracker.get_rivals.return_value = [
            MockRelationship(
                agent_a="gpt4",
                agent_b="claude",
                rivalry_score=0.6,
                debate_count=8,
                relationship="rival",
            ),
        ]
        tracker.get_allies.return_value = []
        mock_get_tracker.return_value = tracker

        result = handler.handle("/api/v1/agents/claude/relationships", {}, mock_http_handler)
        body = _body(result)
        assert body["rivals"][0]["agent"] == "gpt4"

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_summary_agent_name_swapped_in_ally(self, mock_get_tracker, handler, mock_http_handler):
        """When agent_a != queried agent, the ally's name is agent_a."""
        tracker = MagicMock()
        tracker.get_rivals.return_value = []
        tracker.get_allies.return_value = [
            MockRelationship(
                agent_a="gemini",
                agent_b="claude",
                alliance_score=0.85,
                debate_count=5,
                relationship="ally",
            ),
        ]
        mock_get_tracker.return_value = tracker

        result = handler.handle("/api/v1/agents/claude/relationships", {}, mock_http_handler)
        body = _body(result)
        assert body["allies"][0]["agent"] == "gemini"

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_summary_multiple_rivals(self, mock_get_tracker, handler, mock_http_handler):
        tracker = MagicMock()
        tracker.get_rivals.return_value = [
            MockRelationship(
                agent_a="claude",
                agent_b="gpt4",
                rivalry_score=0.9,
                debate_count=20,
                relationship="rival",
            ),
            MockRelationship(
                agent_a="claude",
                agent_b="gemini",
                rivalry_score=0.7,
                debate_count=15,
                relationship="rival",
            ),
            MockRelationship(
                agent_a="claude",
                agent_b="grok",
                rivalry_score=0.5,
                debate_count=10,
                relationship="rival",
            ),
        ]
        tracker.get_allies.return_value = []
        mock_get_tracker.return_value = tracker

        result = handler.handle("/api/v1/agents/claude/relationships", {}, mock_http_handler)
        body = _body(result)
        assert len(body["rivals"]) == 3
        assert body["rivals"][0]["agent"] == "gpt4"
        assert body["rivals"][1]["agent"] == "gemini"
        assert body["rivals"][2]["agent"] == "grok"

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_summary_multiple_allies(self, mock_get_tracker, handler, mock_http_handler):
        tracker = MagicMock()
        tracker.get_rivals.return_value = []
        tracker.get_allies.return_value = [
            MockRelationship(
                agent_a="claude",
                agent_b="gemini",
                alliance_score=0.95,
                debate_count=25,
                relationship="ally",
            ),
            MockRelationship(
                agent_a="claude",
                agent_b="mistral",
                alliance_score=0.8,
                debate_count=18,
                relationship="ally",
            ),
        ]
        mock_get_tracker.return_value = tracker

        result = handler.handle("/api/v1/agents/claude/relationships", {}, mock_http_handler)
        body = _body(result)
        assert len(body["allies"]) == 2


# ---------------------------------------------------------------------------
# handle - pairwise endpoint
# ---------------------------------------------------------------------------


class TestHandlePairwise:
    """Tests for GET /api/v1/agents/{name}/relationships/{other}."""

    @patch(
        "aragora.server.handlers.agents.relationships._get_relationship_tracker",
        return_value=None,
    )
    def test_pairwise_no_tracker_returns_defaults(
        self, mock_get_tracker, handler, mock_http_handler
    ):
        result = handler.handle("/api/v1/agents/claude/relationships/gpt4", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert body["agent_a"] == "claude"
        assert body["agent_b"] == "gpt4"
        assert body["debate_count"] == 0
        assert body["relationship"] == "unknown"

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_pairwise_with_tracker(
        self, mock_get_tracker, handler, mock_http_handler, mock_tracker
    ):
        mock_get_tracker.return_value = mock_tracker

        result = handler.handle("/api/v1/agents/claude/relationships/gpt4", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert body["agent_a"] == "claude"
        assert body["agent_b"] == "gpt4"
        assert body["debate_count"] == 10
        assert body["rivalry_score"] == 0.7
        assert body["alliance_score"] == 0.3
        assert body["relationship"] == "rival"
        assert body["agreement_rate"] == 0.35
        assert body["head_to_head"] == {"claude": 6, "gpt4": 4}

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_pairwise_calls_compute_metrics(
        self, mock_get_tracker, handler, mock_http_handler, mock_tracker
    ):
        mock_get_tracker.return_value = mock_tracker

        handler.handle("/api/v1/agents/claude/relationships/gpt4", {}, mock_http_handler)
        mock_tracker.compute_metrics.assert_called_once_with("claude", "gpt4")

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_pairwise_different_agents(self, mock_get_tracker, handler, mock_http_handler):
        tracker = MagicMock()
        tracker.compute_metrics.return_value = MockRelationship(
            agent_a="gemini",
            agent_b="grok",
            debate_count=5,
            rivalry_score=0.2,
            alliance_score=0.8,
            relationship="ally",
            agreement_rate=0.75,
            head_to_head={"gemini": 2, "grok": 3},
        )
        mock_get_tracker.return_value = tracker

        result = handler.handle("/api/v1/agents/gemini/relationships/grok", {}, mock_http_handler)
        body = _body(result)
        assert body["agent_a"] == "gemini"
        assert body["agent_b"] == "grok"
        assert body["relationship"] == "ally"


# ---------------------------------------------------------------------------
# handle - input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Tests for input validation on agent names."""

    def test_dotted_agent_name_is_valid(self, handler, mock_http_handler):
        """Dotted model-version names are valid agent names (#9994)."""
        result = handler.handle(
            "/api/v1/agents/claude-fable-5.1/relationships", {}, mock_http_handler
        )
        assert _status(result) == 200

    def test_leading_dot_agent_name_returns_400(self, handler, mock_http_handler):
        """A dot-led token can never be an agent name (guards '.' and '..')."""
        result = handler.handle("/api/v1/agents/.bad/relationships", {}, mock_http_handler)
        assert _status(result) == 400
        result = handler.handle("/api/v1/agents/../relationships", {}, mock_http_handler)
        assert _status(result) != 200

    def test_agent_name_with_special_chars(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/agents/bad%3Cscript/relationships", {}, mock_http_handler)
        assert _status(result) == 400

    def test_agent_name_too_long(self, handler, mock_http_handler):
        long_name = "a" * 33  # SAFE_AGENT_PATTERN allows max 32 chars
        result = handler.handle(f"/api/v1/agents/{long_name}/relationships", {}, mock_http_handler)
        assert _status(result) == 400

    def test_agent_name_with_at_sign(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/agents/bad@name/relationships", {}, mock_http_handler)
        assert _status(result) == 400

    def test_agent_name_with_slash_encoding(self, handler, mock_http_handler):
        """Agent name with encoded characters fails validation."""
        result = handler.handle("/api/v1/agents/bad%2Fname/relationships", {}, mock_http_handler)
        assert _status(result) == 400

    @patch(
        "aragora.server.handlers.agents.relationships._get_relationship_tracker",
        return_value=None,
    )
    def test_valid_agent_name_with_hyphens(self, mock_get_tracker, handler, mock_http_handler):
        result = handler.handle("/api/v1/agents/claude-3/relationships", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert body["agent"] == "claude-3"

    @patch(
        "aragora.server.handlers.agents.relationships._get_relationship_tracker",
        return_value=None,
    )
    def test_valid_agent_name_with_underscores(self, mock_get_tracker, handler, mock_http_handler):
        result = handler.handle("/api/v1/agents/gpt_4o/relationships", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert body["agent"] == "gpt_4o"

    def test_pairwise_invalid_other_agent_name(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/agents/claude/relationships/<evil>", {}, mock_http_handler)
        assert _status(result) == 400

    def test_pairwise_other_agent_too_long(self, handler, mock_http_handler):
        long_name = "x" * 33
        result = handler.handle(
            f"/api/v1/agents/claude/relationships/{long_name}", {}, mock_http_handler
        )
        assert _status(result) == 400


# ---------------------------------------------------------------------------
# handle - path routing / edge cases
# ---------------------------------------------------------------------------


class TestPathRouting:
    """Tests for correct path routing within handle()."""

    def test_too_few_parts_returns_none(self, handler, mock_http_handler):
        """Path with fewer than 5 parts after strip should return None."""
        result = handler.handle("/api/v1/agents/claude", {}, mock_http_handler)
        assert result is None

    def test_wrong_segment_at_index_4_returns_none(self, handler, mock_http_handler):
        """If parts[4] != 'relationships', should return None."""
        result = handler.handle("/api/v1/agents/claude/rankings", {}, mock_http_handler)
        assert result is None

    @patch(
        "aragora.server.handlers.agents.relationships._get_relationship_tracker",
        return_value=None,
    )
    def test_exact_5_parts_is_summary(self, mock_get_tracker, handler, mock_http_handler):
        result = handler.handle("/api/v1/agents/claude/relationships", {}, mock_http_handler)
        body = _body(result)
        assert body["agent"] == "claude"
        assert "rivals" in body
        assert "allies" in body

    @patch(
        "aragora.server.handlers.agents.relationships._get_relationship_tracker",
        return_value=None,
    )
    def test_exact_6_parts_is_pairwise(self, mock_get_tracker, handler, mock_http_handler):
        result = handler.handle("/api/v1/agents/claude/relationships/gpt4", {}, mock_http_handler)
        body = _body(result)
        assert body["agent_a"] == "claude"
        assert body["agent_b"] == "gpt4"


# ---------------------------------------------------------------------------
# _get_relationship_tracker factory
# ---------------------------------------------------------------------------


class TestGetRelationshipTracker:
    """Tests for the module-level _get_relationship_tracker helper."""

    def test_import_error_returns_none(self):
        """ImportError during tracker creation returns None."""
        from aragora.server.handlers.agents.relationships import _get_relationship_tracker

        with patch(
            "aragora.persistence.db_config.get_default_data_dir",
            side_effect=ImportError("no module"),
        ):
            result = _get_relationship_tracker()
        assert result is None

    def test_os_error_returns_none(self):
        """OSError during tracker creation returns None."""
        from aragora.server.handlers.agents.relationships import _get_relationship_tracker

        mock_path = MagicMock()
        mock_path.__truediv__ = MagicMock(side_effect=OSError("disk full"))

        with patch(
            "aragora.persistence.db_config.get_default_data_dir",
            return_value=mock_path,
        ):
            result = _get_relationship_tracker()
        assert result is None

    def test_relationship_tracker_import_error(self):
        """ImportError on RelationshipTracker import returns None."""
        from aragora.server.handlers.agents.relationships import _get_relationship_tracker

        with patch.dict("sys.modules", {"aragora.ranking.relationships": None}):
            result = _get_relationship_tracker()
        assert result is None

    def test_successful_tracker_creation(self):
        """Successful creation returns a tracker instance."""
        from aragora.server.handlers.agents.relationships import _get_relationship_tracker

        mock_path = MagicMock()
        mock_db_path = MagicMock()
        mock_path.__truediv__ = MagicMock(return_value=mock_db_path)
        mock_tracker_instance = MagicMock()

        with (
            patch(
                "aragora.persistence.db_config.get_default_data_dir",
                return_value=mock_path,
            ),
            patch(
                "aragora.ranking.relationships.RelationshipTracker",
                return_value=mock_tracker_instance,
            ),
        ):
            result = _get_relationship_tracker()

        assert result is mock_tracker_instance


# ---------------------------------------------------------------------------
# Limit boundary tests
# ---------------------------------------------------------------------------


class TestLimitBoundaries:
    """Fine-grained tests for limit clamping."""

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_limit_exactly_1(self, mock_get_tracker, handler, mock_http_handler):
        tracker = MagicMock()
        tracker.get_rivals.return_value = []
        tracker.get_allies.return_value = []
        mock_get_tracker.return_value = tracker

        handler.handle("/api/v1/agents/claude/relationships", {"limit": "1"}, mock_http_handler)
        tracker.get_rivals.assert_called_once_with("claude", limit=1)

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_limit_exactly_20(self, mock_get_tracker, handler, mock_http_handler):
        tracker = MagicMock()
        tracker.get_rivals.return_value = []
        tracker.get_allies.return_value = []
        mock_get_tracker.return_value = tracker

        handler.handle("/api/v1/agents/claude/relationships", {"limit": "20"}, mock_http_handler)
        tracker.get_rivals.assert_called_once_with("claude", limit=20)

    @patch("aragora.server.handlers.agents.relationships._get_relationship_tracker")
    def test_limit_21_clamped(self, mock_get_tracker, handler, mock_http_handler):
        tracker = MagicMock()
        tracker.get_rivals.return_value = []
        tracker.get_allies.return_value = []
        mock_get_tracker.return_value = tracker

        handler.handle("/api/v1/agents/claude/relationships", {"limit": "21"}, mock_http_handler)
        tracker.get_rivals.assert_called_once_with("claude", limit=20)


# ---------------------------------------------------------------------------
# Version prefix stripping tests
# ---------------------------------------------------------------------------


class TestVersionPrefixStripping:
    """Tests for correct strip_version_prefix behavior."""

    @patch(
        "aragora.server.handlers.agents.relationships._get_relationship_tracker",
        return_value=None,
    )
    def test_v1_prefix_stripped(self, mock_get_tracker, handler, mock_http_handler):
        result = handler.handle("/api/v1/agents/claude/relationships", {}, mock_http_handler)
        assert _status(result) == 200

    @patch(
        "aragora.server.handlers.agents.relationships._get_relationship_tracker",
        return_value=None,
    )
    def test_v2_prefix_stripped(self, mock_get_tracker, handler, mock_http_handler):
        result = handler.handle("/api/v2/agents/claude/relationships", {}, mock_http_handler)
        assert _status(result) == 200

    @patch(
        "aragora.server.handlers.agents.relationships._get_relationship_tracker",
        return_value=None,
    )
    def test_no_version_prefix_works(self, mock_get_tracker, handler, mock_http_handler):
        result = handler.handle("/api/agents/claude/relationships", {}, mock_http_handler)
        assert _status(result) == 200
