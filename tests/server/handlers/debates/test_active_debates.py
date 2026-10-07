"""
Tests for GET /api/v1/debates/active endpoint.

Covers:
- Returns empty list when no debates are running
- Returns active debates with correct fields
- Correct ISO timestamp conversion
- Multiple concurrent debates
- Route dispatch from DebatesHandler.handle()
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.debates.crud import CrudOperationsMixin, _epoch_to_iso
from aragora.server.handlers.base import HandlerResult
from aragora.server.state import DebateState

ORG = "test-org-001"

# ============================================================================
# Helpers
# ============================================================================


def _parse_result(result: HandlerResult) -> tuple[dict, int]:
    """Extract parsed JSON body and status code from HandlerResult."""
    body = json.loads(result.body) if isinstance(result.body, bytes) else result.body
    return body, result.status_code


class _FakeHandler(CrudOperationsMixin):
    """Minimal concrete class mixing in CrudOperationsMixin for testing."""

    def __init__(self):
        self.ctx = {}

    def get_storage(self):
        return MagicMock()

    def read_json_body(self, handler, max_size=None):
        return {}

    def get_current_user(self, handler):
        return None


# ============================================================================
# Tests: _epoch_to_iso helper
# ============================================================================


class TestEpochToIso:
    def test_zero_returns_empty(self):
        assert _epoch_to_iso(0) == ""

    def test_valid_epoch(self):
        # 2026-01-01T00:00:00+00:00
        result = _epoch_to_iso(1767225600)
        assert "2026" in result
        assert "T" in result

    def test_falsy_returns_empty(self):
        assert _epoch_to_iso(0.0) == ""


# ============================================================================
# Tests: _get_active_debates endpoint
# ============================================================================


class TestGetActiveDebates:
    @pytest.fixture
    def handler(self):
        return _FakeHandler()

    @pytest.fixture
    def mock_state_manager(self):
        mgr = MagicMock()
        mgr.get_active_debates.return_value = {}
        return mgr

    def test_empty_when_no_debates(self, handler, mock_state_manager):
        with patch(
            "aragora.server.state.get_state_manager",
            return_value=mock_state_manager,
        ):
            result = handler._get_active_debates(ORG)

        assert isinstance(result, HandlerResult)
        body, status = _parse_result(result)
        assert status == 200
        assert "debates" in body
        assert body["debates"] == []

    def test_returns_running_debate(self, handler, mock_state_manager):
        now = time.time()
        debate_state = DebateState(
            debate_id="debate-abc",
            task="Should we refactor the API?",
            agents=["claude", "gemini", "grok"],
            start_time=now - 120,  # started 2 minutes ago
            status="running",
            current_round=2,
            total_rounds=5,
            metadata={"org_id": ORG},
        )
        mock_state_manager.get_active_debates.return_value = {
            "debate-abc": debate_state,
        }

        with patch(
            "aragora.server.state.get_state_manager",
            return_value=mock_state_manager,
        ):
            result = handler._get_active_debates(ORG)

        body, status = _parse_result(result)
        assert status == 200
        debates = body["debates"]
        assert len(debates) == 1

        d = debates[0]
        assert d["id"] == "debate-abc"
        assert d["topic"] == "Should we refactor the API?"
        assert d["status"] == "running"
        assert d["agents"] == ["claude", "gemini", "grok"]
        assert d["round"] == 2
        assert d["total_rounds"] == 5
        assert d["elapsed_seconds"] > 0
        assert d["started_at"] != ""  # non-empty ISO string

    def test_multiple_active_debates(self, handler, mock_state_manager):
        now = time.time()
        debates = {
            "debate-1": DebateState(
                debate_id="debate-1",
                task="Topic A",
                agents=["claude"],
                start_time=now - 60,
                status="running",
                current_round=1,
                total_rounds=3,
                metadata={"org_id": ORG},
            ),
            "debate-2": DebateState(
                debate_id="debate-2",
                task="Topic B",
                agents=["gemini", "grok"],
                start_time=now - 300,
                status="paused",
                current_round=3,
                total_rounds=3,
                metadata={"org_id": ORG},
            ),
            "debate-other-org": DebateState(
                debate_id="debate-other-org",
                task="Topic of another org",
                agents=["claude"],
                start_time=now - 30,
                status="running",
                metadata={"org_id": "org-other"},
            ),
            "debate-no-org": DebateState(
                debate_id="debate-no-org",
                task="Topic without an org",
                agents=["claude"],
                start_time=now - 30,
                status="running",
            ),
        }
        mock_state_manager.get_active_debates.return_value = debates

        with patch(
            "aragora.server.state.get_state_manager",
            return_value=mock_state_manager,
        ):
            result = handler._get_active_debates(ORG)

        body, status = _parse_result(result)
        assert status == 200
        assert len(body["debates"]) == 2

        ids = {d["id"] for d in body["debates"]}
        # Debates of another org, or with no recorded org, are left out.
        assert ids == {"debate-1", "debate-2"}

        # Verify paused debate has correct status
        paused = next(d for d in body["debates"] if d["id"] == "debate-2")
        assert paused["status"] == "paused"


# ============================================================================
# Tests: Route dispatch
# ============================================================================


class TestActiveDebatesRouteDispatch:
    """Test that DebatesHandler.handle() dispatches to _get_active_debates."""

    @pytest.fixture
    def debates_handler(self):
        from aragora.server.handlers.debates.handler import DebatesHandler

        return DebatesHandler(ctx={})

    def test_route_dispatches_active(self, debates_handler):
        """Verify /api/v1/debates/active dispatches to _get_active_debates."""
        mock_state_manager = MagicMock()
        mock_state_manager.get_active_debates.return_value = {}

        with patch(
            "aragora.server.state.get_state_manager",
            return_value=mock_state_manager,
        ):
            result = debates_handler.handle("/api/v1/debates/active", {}, None)

        assert result is not None
        assert isinstance(result, HandlerResult)
        body, status = _parse_result(result)
        assert status == 200
        assert "debates" in body

    def test_can_handle_active_route(self, debates_handler):
        """Verify can_handle returns True for the active debates route."""
        assert debates_handler.can_handle("/api/v1/debates/active")
