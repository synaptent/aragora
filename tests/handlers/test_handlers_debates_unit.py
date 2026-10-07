"""Unit tests for debates handler.

Tests the DebatesHandler class in isolation using mocks.
"""

import json
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from aragora.rbac.models import AuthorizationContext
from aragora.server.handlers.debates import DebatesHandler
from aragora.server.handlers.base import HandlerResult, clear_cache


def _mock_handler_with_auth():
    """Create a mock handler with admin auth context for RBAC-protected methods."""
    handler = MagicMock()
    handler._auth_context = AuthorizationContext(
        user_id="test-admin",
        permissions={"debates:read", "debates:create", "debates:update", "debates:delete"},
        roles={"admin"},
    )
    return handler


@pytest.fixture(autouse=True)
def clear_handler_cache():
    """Clear cache before each test to ensure isolation."""
    clear_cache()
    yield
    clear_cache()


def parse_body(result: HandlerResult) -> dict:
    """Parse the JSON body from a HandlerResult."""
    return json.loads(result.body.decode("utf-8"))


class TestCanHandle:
    """Tests for the can_handle method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.handler = DebatesHandler(server_context={})

    def test_handles_debates_list_endpoint(self) -> None:
        """Test /api/debates endpoint is handled."""
        assert self.handler.can_handle("/api/v1/debates") is True

    def test_handles_debates_with_slash(self) -> None:
        """Test /api/debates/{id} pattern is handled."""
        assert self.handler.can_handle("/api/v1/debates/my-debate-123") is True

    def test_handles_debates_slug(self) -> None:
        """Test /api/debates/slug/{slug} pattern is handled."""
        assert self.handler.can_handle("/api/v1/debates/slug/my-slug") is True

    def test_handles_impasse(self) -> None:
        """Test impasse endpoint is handled."""
        assert self.handler.can_handle("/api/v1/debates/test-123/impasse") is True

    def test_handles_convergence(self) -> None:
        """Test convergence endpoint is handled."""
        assert self.handler.can_handle("/api/v1/debates/test-123/convergence") is True

    def test_handles_citations(self) -> None:
        """Test citations endpoint is handled."""
        assert self.handler.can_handle("/api/v1/debates/test-123/citations") is True

    def test_handles_meta_critique(self) -> None:
        """Test meta-critique endpoint is handled."""
        assert self.handler.can_handle("/api/v1/debate/test-123/meta-critique") is True

    def test_handles_graph_stats(self) -> None:
        """Test graph/stats endpoint is handled."""
        assert self.handler.can_handle("/api/v1/debate/test-123/graph/stats") is True

    def test_does_not_handle_agents(self) -> None:
        """Test agents endpoint is not handled."""
        assert self.handler.can_handle("/api/v1/agents") is False

    def test_does_not_handle_rankings(self) -> None:
        """Test rankings endpoint is not handled."""
        assert self.handler.can_handle("/api/v1/rankings") is False

    def test_does_not_handle_random_path(self) -> None:
        """Test random paths are not handled."""
        assert self.handler.can_handle("/random/path") is False


class TestExtractDebateId:
    """Tests for the _extract_debate_id method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.handler = DebatesHandler(server_context={})

    def test_extracts_valid_id(self) -> None:
        """Test valid debate ID is extracted."""
        debate_id, err = self.handler._extract_debate_id("/api/debates/test-123/impasse")
        assert debate_id == "test-123"
        assert err is None

    def test_extracts_id_with_underscores(self) -> None:
        """Test ID with underscores is extracted."""
        debate_id, err = self.handler._extract_debate_id("/api/debates/test_debate/impasse")
        assert debate_id == "test_debate"
        assert err is None

    def test_rejects_invalid_path_too_short(self) -> None:
        """Test too-short path is rejected."""
        debate_id, err = self.handler._extract_debate_id("/api/debates")
        assert debate_id is None
        assert err == "Invalid path"

    def test_rejects_invalid_id_with_dots(self) -> None:
        """Test ID with dots is rejected (path traversal attempt)."""
        debate_id, err = self.handler._extract_debate_id("/api/debates/../etc/impasse")
        assert debate_id is None
        assert err is not None  # Validation error

    def test_rejects_empty_id(self) -> None:
        """Test empty ID is rejected."""
        debate_id, err = self.handler._extract_debate_id("/api/debates//impasse")
        assert debate_id is None
        assert err is not None


class TestListDebates:
    """Tests for the _list_debates method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_storage = MagicMock()
        self.handler = DebatesHandler(server_context={"storage": self.mock_storage})

    def test_returns_debates_list(self) -> None:
        """Test successful debate listing."""
        self.mock_storage.list_recent.return_value = [
            {"id": "debate-1", "title": "Test 1"},
            {"id": "debate-2", "title": "Test 2"},
        ]

        result = self.handler._list_debates(limit=20)

        assert result.status_code == 200
        data = parse_body(result)
        assert data["count"] == 2
        assert len(data["debates"]) == 2

    def test_returns_empty_list(self) -> None:
        """Test empty debate list."""
        self.mock_storage.list_recent.return_value = []

        result = self.handler._list_debates(limit=20)

        assert result.status_code == 200
        data = parse_body(result)
        assert data["count"] == 0
        assert data["debates"] == []

    def test_handles_storage_error(self) -> None:
        """Test storage error handling."""
        self.mock_storage.list_recent.side_effect = Exception("Database error")

        result = self.handler._list_debates(limit=20)

        assert result.status_code == 500
        assert parse_body(result)["error"]  # Sanitized error message

    def test_handles_no_storage(self) -> None:
        """Test missing storage handling."""
        handler = DebatesHandler(server_context={})

        result = handler._list_debates(limit=20)

        assert result.status_code == 503
        assert "Storage not available" in parse_body(result)["error"]


class TestGetDebateBySlug:
    """Tests for the _get_debate_by_slug method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_storage = MagicMock()
        self.handler = DebatesHandler(server_context={"storage": self.mock_storage})

    def test_returns_found_debate(self) -> None:
        """Test successful debate retrieval."""
        self.mock_storage.get_debate.return_value = {
            "id": "test-123",
            "title": "Test Debate",
            "messages": [],
        }

        result = self.handler._get_debate_by_slug(None, "test-123")

        assert result.status_code == 200
        assert parse_body(result)["id"] == "test-123"

    def test_returns_404_for_missing(self) -> None:
        """Test 404 for missing debate."""
        self.mock_storage.get_debate.return_value = None

        result = self.handler._get_debate_by_slug(None, "nonexistent")

        assert result.status_code == 404
        assert "not found" in parse_body(result)["error"]

    def test_handles_storage_error(self) -> None:
        """Test storage error handling."""
        self.mock_storage.get_debate.side_effect = Exception("Connection failed")

        result = self.handler._get_debate_by_slug(None, "test-123")

        assert result.status_code == 500
        assert parse_body(result)["error"]  # Sanitized error message


class TestGetImpasse:
    """Tests for the _get_impasse method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_storage = MagicMock()
        self.handler = DebatesHandler(server_context={"storage": self.mock_storage})
        self.mock_http_handler = _mock_handler_with_auth()

    def test_detects_no_impasse(self) -> None:
        """Test no impasse when consensus reached."""
        self.mock_storage.get_debate.return_value = {
            "id": "test-123",
            "consensus_reached": True,
            "messages": [],
            "critiques": [],
        }

        result = self.handler._get_impasse(self.mock_http_handler, "test-123")

        assert result.status_code == 200
        assert parse_body(result)["is_impasse"] is False

    def test_detects_impasse_no_consensus_high_severity(self) -> None:
        """Test impasse detected with no consensus and high severity critiques."""
        self.mock_storage.get_debate.return_value = {
            "id": "test-123",
            "consensus_reached": False,
            "messages": [],
            "critiques": [{"severity": 0.9}],
        }

        result = self.handler._get_impasse(self.mock_http_handler, "test-123")

        assert result.status_code == 200
        # no_convergence = True, high_severity = True, repeated = False
        # 2 out of 3 = impasse
        assert parse_body(result)["is_impasse"] is True

    def test_returns_404_for_missing_debate(self) -> None:
        """Test 404 for missing debate."""
        self.mock_storage.get_debate.return_value = None

        result = self.handler._get_impasse(self.mock_http_handler, "nonexistent")

        assert result.status_code == 404

    def test_returns_impasse_indicators(self) -> None:
        """Test impasse indicators are returned."""
        self.mock_storage.get_debate.return_value = {
            "id": "test-123",
            "consensus_reached": False,
            "messages": [],
            "critiques": [{"severity": 0.5}],  # Low severity
        }

        result = self.handler._get_impasse(self.mock_http_handler, "test-123")

        assert result.status_code == 200
        data = parse_body(result)
        assert "indicators" in data
        indicators = data["indicators"]
        assert "no_convergence" in indicators
        assert "high_severity_critiques" in indicators


class TestGetConvergence:
    """Tests for the _get_convergence method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_storage = MagicMock()
        self.handler = DebatesHandler(server_context={"storage": self.mock_storage})
        self.mock_http_handler = _mock_handler_with_auth()

    def test_returns_convergence_status(self) -> None:
        """Test convergence status is returned."""
        self.mock_storage.get_debate.return_value = {
            "id": "test-123",
            "convergence_status": "converged",
            "convergence_similarity": 0.85,
            "consensus_reached": True,
            "rounds_used": 3,
        }

        result = self.handler._get_convergence(self.mock_http_handler, "test-123")

        assert result.status_code == 200
        data = parse_body(result)
        assert data["convergence_status"] == "converged"
        assert data["convergence_similarity"] == 0.85
        assert data["consensus_reached"] is True
        assert data["rounds_used"] == 3

    def test_returns_defaults_for_missing_fields(self) -> None:
        """Test defaults are used for missing fields."""
        self.mock_storage.get_debate.return_value = {
            "id": "test-123",
        }

        result = self.handler._get_convergence(self.mock_http_handler, "test-123")

        assert result.status_code == 200
        data = parse_body(result)
        assert data["convergence_status"] == "unknown"
        assert data["convergence_similarity"] == 0.0
        assert data["consensus_reached"] is False
        assert data["rounds_used"] == 0

    def test_returns_404_for_missing_debate(self) -> None:
        """Test 404 for missing debate."""
        self.mock_storage.get_debate.return_value = None

        result = self.handler._get_convergence(self.mock_http_handler, "nonexistent")

        assert result.status_code == 404


class TestHandle:
    """Tests for the handle method (routing)."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_storage = MagicMock()
        self.mock_storage.get_access_info.side_effect = lambda ref: (ref, "test-org-001", False)
        self.handler = DebatesHandler(server_context={"storage": self.mock_storage})
        self.mock_http_handler = _mock_handler_with_auth()

    def test_routes_to_list_debates(self) -> None:
        """Test routing to list debates."""
        self.mock_storage.list_recent.return_value = []

        result = self.handler.handle("/api/debates", {}, self.mock_http_handler)

        assert result is not None
        assert result.status_code == 200

    def test_routes_to_slug_lookup(self) -> None:
        """Test routing to slug lookup."""
        self.mock_storage.get_debate.return_value = {"id": "test"}

        result = self.handler.handle("/api/debates/slug/my-slug", {}, self.mock_http_handler)

        assert result is not None
        assert result.status_code == 200

    def test_routes_to_impasse(self) -> None:
        """Test routing to impasse endpoint."""
        self.mock_storage.get_debate.return_value = {
            "id": "test-123",
            "consensus_reached": True,
            "messages": [],
            "critiques": [],
        }

        result = self.handler.handle("/api/debates/test-123/impasse", {}, self.mock_http_handler)

        assert result is not None
        assert result.status_code == 200
        assert "is_impasse" in parse_body(result)

    def test_routes_to_convergence(self) -> None:
        """Test routing to convergence endpoint."""
        self.mock_storage.get_debate.return_value = {
            "id": "test-123",
            "convergence_status": "converged",
        }

        result = self.handler.handle(
            "/api/debates/test-123/convergence", {}, self.mock_http_handler
        )

        assert result is not None
        assert result.status_code == 200
        assert "convergence_status" in parse_body(result)

    def test_rejects_invalid_debate_id_in_route(self) -> None:
        """Test invalid debate ID in route is rejected."""
        result = self.handler.handle("/api/debates/../etc/impasse", {}, self.mock_http_handler)

        assert result is not None
        assert result.status_code == 400

    def test_uses_limit_parameter(self) -> None:
        """Test limit parameter is used for list."""
        self.mock_storage.list_recent.return_value = []

        self.handler.handle("/api/debates", {"limit": ["50"]}, self.mock_http_handler)

        self.mock_storage.list_recent.assert_called_once()
        call_kwargs = self.mock_storage.list_recent.call_args.kwargs
        assert call_kwargs["limit"] == 50

    def test_caps_limit_at_100(self) -> None:
        """Test limit is capped at 100."""
        self.mock_storage.list_recent.return_value = []

        self.handler.handle("/api/debates", {"limit": ["500"]}, self.mock_http_handler)

        self.mock_storage.list_recent.assert_called_once()
        call_kwargs = self.mock_storage.list_recent.call_args
        assert call_kwargs.kwargs.get("limit", call_kwargs[1].get("limit")) == 100
