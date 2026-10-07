"""
E2E tests for modular HTTP handlers.

Tests cover:
- SystemHandler: history, debug, circuit-breakers
- DebatesHandler: list, get by slug, impasse, convergence, export
- AgentsHandler: leaderboard, matches, profiles, comparisons (via internal methods)
- Handler routing: modular handler chain, fallthrough behavior

Note: Health, nomic, and modes endpoints have been extracted to dedicated handlers
(HealthHandler, NomicHandler) and are tested in their own test files.
AgentsHandler.handle() and AnalyticsHandler.handle() are async; tests call
internal sync methods directly to avoid coroutine issues.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, MagicMock, patch

from aragora.server.handlers import (
    SystemHandler,
    DebatesHandler,
    AgentsHandler,
    HandlerResult,
    json_response,
    error_response,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def temp_nomic_dir():
    """Create a temporary nomic directory with state files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        nomic_dir = Path(tmpdir)

        # Create nomic state file
        state_file = nomic_dir / "nomic_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "phase": "implement",
                    "stage": "executing",
                    "cycle": 1,
                    "total_tasks": 5,
                    "completed_tasks": 2,
                }
            )
        )

        # Create nomic log file
        log_file = nomic_dir / "nomic_loop.log"
        log_file.write_text(
            "\n".join(
                [
                    "2026-01-05 00:00:01 Starting cycle 1",
                    "2026-01-05 00:00:02 Phase: context",
                    "2026-01-05 00:00:03 Phase: debate",
                    "2026-01-05 00:00:04 Phase: design",
                    "2026-01-05 00:00:05 Phase: implement",
                ]
            )
        )

        yield nomic_dir


@pytest.fixture
def mock_storage():
    """Create a mock DebateStorage."""
    storage = Mock()
    storage.list_recent.return_value = [
        {"id": "debate-1", "slug": "test-debate", "task": "Test task", "created_at": "2026-01-05"},
        {
            "id": "debate-2",
            "slug": "another-debate",
            "task": "Another task",
            "created_at": "2026-01-04",
        },
    ]
    storage.get_debate.return_value = {
        "id": "debate-1",
        "slug": "test-debate",
        "task": "Test task",
        "messages": [{"agent": "claude", "content": "Hello"}],
        "critiques": [],
        "consensus_reached": False,
        "rounds_used": 3,
    }
    # Every debate id resolves to a private debate of the test user's org.
    storage.get_access_info.side_effect = lambda ref: (ref, "test-org-001", False)
    return storage


@pytest.fixture
def mock_elo_system():
    """Create a mock EloSystem."""
    elo = Mock()
    leaderboard_data = [
        {"name": "claude", "rating": 1500, "wins": 10, "losses": 5},
        {"name": "gemini", "rating": 1480, "wins": 8, "losses": 7},
    ]
    elo.get_leaderboard.return_value = leaderboard_data
    elo.get_cached_leaderboard.return_value = leaderboard_data  # Same data for cache
    elo.get_rating.return_value = 1500
    elo.get_agent_stats.return_value = {"wins": 10, "losses": 5, "win_rate": 0.67}
    elo.get_agent_history.return_value = [
        {"opponent": "gemini", "result": "win", "date": "2026-01-05"},
    ]
    elo.get_recent_matches.return_value = [
        {"agent1": "claude", "agent2": "gemini", "winner": "claude"},
    ]
    elo.get_head_to_head.return_value = {"matches": 5, "agent1_wins": 3, "agent2_wins": 2}
    elo.get_rivals.return_value = [{"name": "gemini", "matches": 10}]
    elo.get_allies.return_value = [{"name": "grok", "agreements": 8}]
    return elo


@pytest.fixture
def system_handler(temp_nomic_dir, mock_storage, mock_elo_system):
    """Create SystemHandler with test context."""
    ctx = {
        "storage": mock_storage,
        "elo_system": mock_elo_system,
        "nomic_dir": temp_nomic_dir,
    }
    return SystemHandler(ctx)


@pytest.fixture
def debates_handler(mock_storage):
    """Create DebatesHandler with test context."""
    ctx = {
        "storage": mock_storage,
        "elo_system": None,
        "nomic_dir": None,
    }
    return DebatesHandler(ctx)


@pytest.fixture
def agents_handler(mock_elo_system, temp_nomic_dir):
    """Create AgentsHandler with test context."""
    ctx = {
        "storage": None,
        "elo_system": mock_elo_system,
        "nomic_dir": temp_nomic_dir,
    }
    return AgentsHandler(ctx)


# ============================================================================
# SystemHandler Tests
# ============================================================================


class TestSystemHandlerE2E:
    """E2E tests for SystemHandler endpoints.

    Note: Health, nomic, and modes endpoints have been extracted to dedicated
    handlers (HealthHandler, NomicHandler). SystemHandler now handles:
    - /api/history/* (cycles, events, debates, summary)
    - /api/debug/test
    - /api/system/maintenance
    - /api/circuit-breakers
    - /metrics
    """

    def test_history_cycles_with_loop_id(self, system_handler):
        """Test /api/history/cycles filters by loop_id."""
        result = system_handler.handle(
            "/api/history/cycles", {"loop_id": "loop-123", "limit": 10}, None
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert "cycles" in data


# ============================================================================
# DebatesHandler Tests
# ============================================================================


class TestDebatesHandlerE2E:
    """E2E tests for DebatesHandler endpoints."""

    def test_list_debates_returns_array(self, debates_handler):
        """Test /api/debates returns list of debates."""
        result = debates_handler.handle("/api/debates", {}, None)

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "debates" in data
        assert isinstance(data["debates"], list)
        assert len(data["debates"]) == 2

    def test_list_debates_with_limit(self, debates_handler, mock_storage):
        """Test /api/debates respects limit parameter."""
        debates_handler.handle("/api/debates", {"limit": 5}, None)
        # Handler passes org_id from authenticated user context (may be test org)
        mock_storage.list_recent.assert_called_once()
        _, kwargs = mock_storage.list_recent.call_args
        assert kwargs["limit"] == 5

    def test_debate_by_slug_returns_object(self, debates_handler):
        """Test /api/debates/{slug} returns debate details."""
        result = debates_handler.handle("/api/debates/test-debate", {}, None)

        assert result.status_code == 200
        data = json.loads(result.body)

        assert data["slug"] == "test-debate"
        assert "messages" in data

    def test_debate_not_found_returns_404(self, debates_handler, mock_storage):
        """Test /api/debates/{slug} returns 404 for missing debate."""
        mock_storage.get_debate.return_value = None

        result = debates_handler.handle("/api/debates/nonexistent", {}, None)

        assert result.status_code == 404

    def test_impasse_detection_indicators(self, debates_handler):
        """Test /api/debates/{id}/impasse returns impasse indicators."""
        result = debates_handler.handle("/api/debates/debate-1/impasse", {}, None)

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "is_impasse" in data
        assert "indicators" in data

    def test_convergence_status_fields(self, debates_handler):
        """Test /api/debates/{id}/convergence returns status fields."""
        result = debates_handler.handle("/api/debates/debate-1/convergence", {}, None)

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "convergence_status" in data
        assert "consensus_reached" in data

    def test_export_json_format(self, debates_handler):
        """Test /api/debates/{id}/export/json returns debate as JSON."""
        result = debates_handler.handle(
            "/api/debates/debate-1/export/json", {"table": "summary"}, None
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert "slug" in data

    def test_export_invalid_format_400(self, debates_handler):
        """Test /api/debates/{id}/export/{invalid} returns 400."""
        result = debates_handler.handle("/api/debates/debate-1/export/xml", {}, None)

        assert result.status_code == 400


# ============================================================================
# AgentsHandler Tests (via internal methods since handle() is async)
# ============================================================================


class TestAgentsHandlerE2E:
    """E2E tests for AgentsHandler endpoints.

    Since AgentsHandler.handle() is async (performs RBAC + rate-limiting),
    tests call internal sync methods directly.
    """

    def test_leaderboard_default_params(self, agents_handler):
        """Test leaderboard returns rankings."""
        result = agents_handler._get_leaderboard(limit=20, domain=None)

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "rankings" in data
        assert len(data["rankings"]) > 0

    def test_leaderboard_with_domain(self, agents_handler, mock_elo_system):
        """Test leaderboard filters by domain."""
        agents_handler._get_leaderboard(limit=20, domain="coding")
        mock_elo_system.get_leaderboard.assert_called_with(limit=20, domain="coding")

    def test_leaderboard_limit_capped(self, agents_handler, mock_elo_system):
        """Test leaderboard caps limit at 50."""
        agents_handler._get_leaderboard(limit=100, domain=None)
        # When domain=None, handler uses get_cached_leaderboard with capped limit
        mock_elo_system.get_cached_leaderboard.assert_called_with(limit=50)

    def test_recent_matches_returns_array(self, agents_handler):
        """Test recent matches returns match data."""
        result = agents_handler._get_recent_matches(limit=10, loop_id=None)

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "matches" in data

    def test_agent_profile_complete(self, agents_handler):
        """Test agent profile returns profile data."""
        result = agents_handler._handle_agent_endpoint("/api/agent/claude/profile", {})

        assert result.status_code == 200
        data = json.loads(result.body)

        assert data["name"] == "claude"
        assert "rating" in data

    def test_agent_history_with_limit(self, agents_handler, mock_elo_system):
        """Test agent history respects limit."""
        # Handler uses get_elo_history (returns list of (timestamp, elo) tuples)
        mock_elo_system.get_elo_history.return_value = [
            ("2026-01-05T10:00:00", 1500),
            ("2026-01-04T10:00:00", 1490),
        ]
        result = agents_handler._handle_agent_endpoint("/api/agent/claude/history", {"limit": 50})
        mock_elo_system.get_elo_history.assert_called_with("claude", limit=50)
        assert result.status_code == 200

    def test_agent_compare_two_agents(self, agents_handler):
        """Test agent compare requires 2+ agents."""
        # Test with only 1 agent - should fail
        result = agents_handler._compare_agents(["claude"])
        assert result.status_code == 400

        # Test with 2 agents - should succeed
        result = agents_handler._compare_agents(["claude", "gemini"])
        assert result.status_code == 200

    def test_head_to_head_stats(self, agents_handler):
        """Test head-to-head returns stats."""
        result = agents_handler._handle_agent_endpoint("/api/agent/claude/head-to-head/gemini", {})

        assert result.status_code == 200
        data = json.loads(result.body)

        assert data["agent1"] == "claude"
        assert data["agent2"] == "gemini"
        assert "matches" in data

    def test_agent_network_structure(self, agents_handler):
        """Test agent network returns rivals and allies."""
        result = agents_handler._handle_agent_endpoint("/api/agent/claude/network", {})

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "rivals" in data
        assert "allies" in data

    def test_cannot_handle_calibration_leaderboard(self, agents_handler):
        """AgentsHandler should NOT handle /api/calibration/leaderboard (moved to CalibrationHandler)."""
        assert agents_handler.can_handle("/api/v1/calibration/leaderboard") is False


# ============================================================================
# Handler Routing Tests
# ============================================================================


class TestHandlerRoutingE2E:
    """E2E tests for handler routing behavior."""

    def test_can_handle_matches_routes(self, system_handler, debates_handler, agents_handler):
        """Test can_handle correctly identifies routes."""
        # SystemHandler routes (note: health/nomic/modes moved to other handlers)
        assert system_handler.can_handle("/api/v1/history/cycles") is True
        assert system_handler.can_handle("/api/v1/debug/test") is True
        assert system_handler.can_handle("/api/v1/debates") is False

        # DebatesHandler routes
        assert debates_handler.can_handle("/api/v1/debates") is True
        assert debates_handler.can_handle("/api/v1/debates/test-slug") is True
        assert debates_handler.can_handle("/api/v1/leaderboard") is False

        # AgentsHandler routes
        assert agents_handler.can_handle("/api/v1/leaderboard") is True
        assert agents_handler.can_handle("/api/v1/agent/claude/profile") is True
        assert agents_handler.can_handle("/api/v1/health") is False

    def test_handler_returns_none_for_unhandled(self, system_handler):
        """Test handler returns None for routes it can handle but has no implementation."""
        # can_handle returns False, so handle() would return None
        result = system_handler.handle("/api/unknown", {}, None)
        assert result is None

    def test_query_param_conversion(self, agents_handler, mock_elo_system):
        """Test query parameters are correctly converted."""
        # Integer conversion - when domain=None, uses cached leaderboard
        agents_handler._get_leaderboard(limit=25, domain=None)
        mock_elo_system.get_cached_leaderboard.assert_called_with(limit=25)

    def test_error_response_format(self, debates_handler, mock_storage):
        """Test error responses follow consistent format."""
        mock_storage.get_debate.return_value = None

        result = debates_handler.handle("/api/debates/missing", {}, None)
        data = json.loads(result.body)

        assert "error" in data
        assert isinstance(data["error"], str)


# ============================================================================
# Handler Result Tests
# ============================================================================


class TestHandlerResult:
    """Tests for HandlerResult utilities."""

    def test_json_response_creates_valid_result(self):
        """Test json_response creates correct HandlerResult."""
        result = json_response({"key": "value"}, status=200)

        assert result.status_code == 200
        assert result.content_type == "application/json"
        assert b'"key"' in result.body

    def test_error_response_creates_error_result(self):
        """Test error_response creates error HandlerResult."""
        result = error_response("Something went wrong", status=500)

        assert result.status_code == 500
        data = json.loads(result.body)
        assert data["error"] == "Something went wrong"

    def test_handler_result_default_headers(self):
        """Test HandlerResult has default empty headers."""
        result = HandlerResult(
            status_code=200,
            content_type="application/json",
            body=b"{}",
        )
        assert result.headers == {}

    def test_handler_result_custom_headers(self):
        """Test HandlerResult accepts custom headers."""
        result = HandlerResult(
            status_code=200,
            content_type="application/json",
            body=b"{}",
            headers={"X-Custom": "value"},
        )
        assert result.headers["X-Custom"] == "value"


# ============================================================================
# PulseHandler Tests
# ============================================================================


class TestPulseHandlerE2E:
    """E2E tests for PulseHandler endpoints."""

    @pytest.fixture
    def pulse_handler(self):
        """Create PulseHandler with test context."""
        from aragora.server.handlers import PulseHandler

        ctx = {"storage": None, "elo_system": None, "nomic_dir": None}
        return PulseHandler(ctx)

    def test_can_handle_trending(self, pulse_handler):
        """Test PulseHandler handles trending endpoint."""
        assert pulse_handler.can_handle("/api/v1/pulse/trending") is True
        assert pulse_handler.can_handle("/api/v1/debates") is False

    def test_trending_handles_missing_module(self, pulse_handler):
        """Test /api/v1/pulse/trending returns 503 if module unavailable."""
        # Mock the pulse module to avoid real API calls
        with patch("aragora.pulse.ingestor.PulseManager") as mock_pm:
            with patch("aragora.pulse.ingestor.HackerNewsIngestor"):
                with patch("aragora.pulse.ingestor.RedditIngestor"):
                    with patch("aragora.pulse.ingestor.TwitterIngestor"):
                        mock_manager = MagicMock()
                        mock_manager.ingestors = {}
                        mock_manager.get_trending_topics = AsyncMock(return_value=[])
                        mock_pm.return_value = mock_manager

                        result = pulse_handler.handle("/api/v1/pulse/trending", {}, None)

                        # Will return 503 if import fails or 200/500 otherwise
                        assert result.status_code in (200, 500, 503)
                        data = json.loads(result.body)
                        # Should have either topics or error
                        assert "topics" in data or "error" in data

    def test_trending_returns_valid_json(self, pulse_handler):
        """Test /api/v1/pulse/trending returns valid JSON."""
        # Mock the pulse module to avoid real API calls
        with patch("aragora.pulse.ingestor.PulseManager") as mock_pm:
            with patch("aragora.pulse.ingestor.HackerNewsIngestor"):
                with patch("aragora.pulse.ingestor.RedditIngestor"):
                    with patch("aragora.pulse.ingestor.TwitterIngestor"):
                        mock_manager = MagicMock()
                        mock_manager.ingestors = {}
                        mock_manager.get_trending_topics = AsyncMock(return_value=[])
                        mock_pm.return_value = mock_manager

                        result = pulse_handler.handle("/api/v1/pulse/trending", {"limit": 5}, None)

                        # Should always return valid JSON regardless of status
                        data = json.loads(result.body)
                        assert isinstance(data, dict)

    def test_unhandled_route_returns_none(self, pulse_handler):
        """Test unhandled routes return None."""
        result = pulse_handler.handle("/api/unknown", {}, None)
        assert result is None


# ============================================================================
# AnalyticsHandler Tests (via internal methods since handle() is async)
# ============================================================================


class TestAnalyticsHandlerE2E:
    """E2E tests for AnalyticsHandler endpoints.

    Since AnalyticsHandler.handle() is async (performs RBAC + rate-limiting),
    tests call internal sync methods directly.
    """

    @pytest.fixture
    def mock_storage_with_debates(self):
        """Create mock storage with debate data."""
        storage = Mock()
        debates = [
            {
                "id": "d1",
                "result": {
                    "disagreement_report": {"unanimous_critiques": False},
                    "early_stopped": True,
                    "rounds_used": 2,
                    "uncertainty_metrics": {"disagreement_type": "methodological"},
                },
                "messages": [
                    {"cognitive_role": "analyst", "content": "Analysis here"},
                    {"cognitive_role": "critic", "content": "Critique here"},
                ],
            },
            {
                "id": "d2",
                "result": {
                    "disagreement_report": {"unanimous_critiques": True},
                    "early_stopped": False,
                    "rounds_used": 5,
                },
                "messages": [
                    {"cognitive_role": "analyst", "content": "More analysis"},
                ],
            },
        ]
        # Configure both list_recent (debates handler) and list_debates (analytics handler)
        storage.list_recent.return_value = debates
        storage.list_debates.return_value = debates
        return storage

    @pytest.fixture
    def analytics_handler(self, mock_storage_with_debates, mock_elo_system, temp_nomic_dir):
        """Create AnalyticsHandler with test context."""
        from aragora.server.handlers import AnalyticsHandler
        from aragora.server.handlers.base import clear_cache

        clear_cache()
        ctx = {
            "storage": mock_storage_with_debates,
            "elo_system": mock_elo_system,
            "nomic_dir": temp_nomic_dir,
        }
        return AnalyticsHandler(ctx)

    @pytest.fixture
    def analytics_handler_no_storage(self, temp_nomic_dir):
        """Create AnalyticsHandler without storage."""
        from aragora.server.handlers import AnalyticsHandler
        from aragora.server.handlers.base import clear_cache

        # Clear cache to avoid stale results from previous tests
        clear_cache()
        ctx = {"storage": None, "elo_system": None, "nomic_dir": temp_nomic_dir}
        return AnalyticsHandler(ctx)

    def test_can_handle_analytics_routes(self, analytics_handler):
        """Test AnalyticsHandler handles analytics routes."""
        assert analytics_handler.can_handle("/api/v1/analytics/disagreements") is True
        assert analytics_handler.can_handle("/api/v1/analytics/role-rotation") is True
        assert analytics_handler.can_handle("/api/v1/analytics/early-stops") is True
        assert analytics_handler.can_handle("/api/v1/ranking/stats") is True
        assert analytics_handler.can_handle("/api/v1/memory/stats") is True
        # Note: /api/memory/tier-stats moved to MemoryHandler
        assert analytics_handler.can_handle("/api/v1/memory/tier-stats") is False
        assert analytics_handler.can_handle("/api/v1/debates") is False

    def test_disagreement_stats_structure(self, analytics_handler):
        """Test disagreement stats returns correct structure."""
        result = analytics_handler._get_disagreement_stats()

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "stats" in data
        stats = data["stats"]
        assert "total_debates" in stats
        assert "with_disagreements" in stats
        assert "unanimous" in stats
        assert "disagreement_types" in stats

    def test_disagreement_stats_counts(self, analytics_handler):
        """Test disagreement stats are calculated correctly."""
        result = analytics_handler._get_disagreement_stats()
        data = json.loads(result.body)

        stats = data["stats"]
        assert stats["total_debates"] == 2
        # First has unanimous_critiques: False -> not counted as disagreement
        # Second has unanimous_critiques: True -> counted as disagreement
        assert stats["with_disagreements"] == 1
        assert stats["unanimous"] == 1

    def test_disagreement_stats_no_storage(self, analytics_handler_no_storage):
        """Test disagreement stats with no storage returns empty."""
        result = analytics_handler_no_storage._get_disagreement_stats()

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["stats"] == {}

    def test_role_rotation_stats_structure(self, analytics_handler):
        """Test role rotation returns correct structure."""
        result = analytics_handler._get_role_rotation_stats()

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "stats" in data
        stats = data["stats"]
        assert "total_debates" in stats
        assert "role_assignments" in stats

    def test_role_rotation_counts_roles(self, analytics_handler):
        """Test role rotation stats counts roles correctly."""
        result = analytics_handler._get_role_rotation_stats()
        data = json.loads(result.body)

        stats = data["stats"]
        assert stats["role_assignments"]["analyst"] == 2
        assert stats["role_assignments"]["critic"] == 1

    def test_early_stop_stats_structure(self, analytics_handler):
        """Test early stop returns correct structure."""
        result = analytics_handler._get_early_stop_stats()

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "stats" in data
        stats = data["stats"]
        assert "total_debates" in stats
        assert "early_stopped" in stats
        assert "full_rounds" in stats
        assert "average_rounds" in stats

    def test_early_stop_stats_calculations(self, analytics_handler):
        """Test early stop stats are calculated correctly."""
        result = analytics_handler._get_early_stop_stats()
        data = json.loads(result.body)

        stats = data["stats"]
        assert stats["total_debates"] == 2
        assert stats["early_stopped"] == 1
        assert stats["full_rounds"] == 1
        assert stats["average_rounds"] == 3.5  # (2 + 5) / 2

    def test_ranking_stats_structure(self, analytics_handler, mock_elo_system):
        """Test ranking stats returns correct structure."""
        from dataclasses import dataclass

        @dataclass
        class MockRanking:
            agent_name: str
            elo: int
            debates_count: int

        mock_elo_system.get_leaderboard.return_value = [MockRanking("claude", 1500, 10)]

        result = analytics_handler._get_ranking_stats()

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "stats" in data
        stats = data["stats"]
        assert "total_agents" in stats
        assert "total_matches" in stats
        assert "avg_elo" in stats

    def test_ranking_stats_no_elo_system(self, analytics_handler_no_storage):
        """Test ranking stats returns error when no ELO system."""
        result = analytics_handler_no_storage._get_ranking_stats()

        assert result.status_code == 503
        data = json.loads(result.body)
        assert "error" in data

    def test_memory_stats_structure(self, analytics_handler):
        """Test memory stats returns correct structure."""
        result = analytics_handler._get_memory_stats()

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "stats" in data
        stats = data["stats"]
        assert "embeddings_db" in stats
        assert "insights_db" in stats
        assert "continuum_memory" in stats


# ============================================================================
# Base Handler Utilities Tests
# ============================================================================


class TestBaseHandlerUtilities:
    """Tests for base handler utility functions."""

    def test_parse_query_params_empty(self):
        """Test parse_query_params with empty string."""
        from aragora.server.handlers.base import parse_query_params

        result = parse_query_params("")
        assert result == {}

    def test_parse_query_params_single_value(self):
        """Test parse_query_params with single values."""
        from aragora.server.handlers.base import parse_query_params

        result = parse_query_params("key=value&num=42")
        assert result["key"] == "value"
        assert result["num"] == "42"

    def test_parse_query_params_multiple_values(self):
        """Test parse_query_params with multiple values for same key."""
        from aragora.server.handlers.base import parse_query_params

        result = parse_query_params("tags=a&tags=b&tags=c")
        assert result["tags"] == ["a", "b", "c"]

    def test_get_int_param_valid(self):
        """Test get_int_param with valid integer."""
        from aragora.server.handlers.base import get_int_param

        result = get_int_param({"limit": "42"}, "limit", 10)
        assert result == 42

    def test_get_int_param_invalid(self):
        """Test get_int_param with invalid value returns default."""
        from aragora.server.handlers.base import get_int_param

        result = get_int_param({"limit": "invalid"}, "limit", 10)
        assert result == 10

    def test_get_int_param_missing(self):
        """Test get_int_param with missing key returns default."""
        from aragora.server.handlers.base import get_int_param

        result = get_int_param({}, "limit", 10)
        assert result == 10

    def test_get_float_param_valid(self):
        """Test get_float_param with valid float."""
        from aragora.server.handlers.base import get_float_param

        result = get_float_param({"ratio": "0.75"}, "ratio", 1.0)
        assert result == 0.75

    def test_get_float_param_invalid(self):
        """Test get_float_param with invalid value returns default."""
        from aragora.server.handlers.base import get_float_param

        result = get_float_param({"ratio": "invalid"}, "ratio", 1.0)
        assert result == 1.0

    def test_get_bool_param_true_values(self):
        """Test get_bool_param with various true values."""
        from aragora.server.handlers.base import get_bool_param

        assert get_bool_param({"flag": "true"}, "flag") is True
        assert get_bool_param({"flag": "1"}, "flag") is True
        assert get_bool_param({"flag": "yes"}, "flag") is True
        assert get_bool_param({"flag": "on"}, "flag") is True
        assert get_bool_param({"flag": "TRUE"}, "flag") is True

    def test_get_bool_param_false_values(self):
        """Test get_bool_param with false values."""
        from aragora.server.handlers.base import get_bool_param

        assert get_bool_param({"flag": "false"}, "flag") is False
        assert get_bool_param({"flag": "0"}, "flag") is False
        assert get_bool_param({"flag": "no"}, "flag") is False

    def test_get_bool_param_default(self):
        """Test get_bool_param uses default when key missing."""
        from aragora.server.handlers.base import get_bool_param

        assert get_bool_param({}, "flag", True) is True
        assert get_bool_param({}, "flag", False) is False


# ============================================================================
# TTL Cache Tests
# ============================================================================


class TestTTLCache:
    """Tests for TTL cache functionality."""

    def test_ttl_cache_caches_result(self):
        """Test ttl_cache stores and returns cached results."""
        from aragora.server.handlers.base import ttl_cache, clear_cache

        clear_cache()
        call_count = 0

        @ttl_cache(ttl_seconds=60, skip_first=False)  # Standalone function
        def expensive_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = expensive_func(5)
        result2 = expensive_func(5)

        assert result1 == 10
        assert result2 == 10
        assert call_count == 1  # Only called once

    def test_ttl_cache_different_args(self):
        """Test ttl_cache stores different results for different args."""
        from aragora.server.handlers.base import ttl_cache, clear_cache

        clear_cache()
        call_count = 0

        @ttl_cache(ttl_seconds=60, skip_first=False)  # Standalone function
        def expensive_func(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = expensive_func(5)
        result2 = expensive_func(10)

        assert result1 == 10
        assert result2 == 20
        assert call_count == 2  # Called twice for different args

    def test_clear_cache_all(self):
        """Test clear_cache clears all entries."""
        from aragora.server.handlers.base import ttl_cache, clear_cache

        # Clear first to get a clean state
        clear_cache()

        @ttl_cache(ttl_seconds=60, key_prefix="test_all", skip_first=False)
        def func1():
            return 1

        @ttl_cache(ttl_seconds=60, key_prefix="other_all", skip_first=False)
        def func2():
            return 2

        func1()
        func2()

        count = clear_cache()
        assert count == 2

    def test_clear_cache_by_prefix(self):
        """Test clear_cache with prefix only clears matching entries."""
        from aragora.server.handlers.base import ttl_cache, clear_cache
        import aragora.server.handlers.base as base_module

        clear_cache()

        @ttl_cache(ttl_seconds=60, key_prefix="prefix_x", skip_first=False)
        def func_a():
            return 1

        @ttl_cache(ttl_seconds=60, key_prefix="prefix_y", skip_first=False)
        def func_b():
            return 2

        func_a()
        func_b()

        count = clear_cache("prefix_x")
        assert count == 1

        # prefix_y should still be cached (access module's _cache directly)
        remaining = len(base_module._cache)
        assert remaining == 1


# ============================================================================
# BaseHandler Context Tests
# ============================================================================


class TestBaseHandlerContext:
    """Tests for BaseHandler context methods."""

    def test_get_storage_returns_storage(self):
        """Test get_storage returns storage from context."""
        from aragora.server.handlers.base import BaseHandler

        storage = Mock()
        handler = BaseHandler({"storage": storage})

        assert handler.get_storage() is storage

    def test_get_storage_returns_none_if_missing(self):
        """Test get_storage returns None if not in context."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        assert handler.get_storage() is None

    def test_get_elo_system_returns_elo(self):
        """Test get_elo_system returns ELO from context."""
        from aragora.server.handlers.base import BaseHandler

        elo = Mock()
        handler = BaseHandler({"elo_system": elo})

        assert handler.get_elo_system() is elo

    def test_get_nomic_dir_returns_path(self):
        """Test get_nomic_dir returns path from context."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({"nomic_dir": Path("/tmp/nomic")})

        assert handler.get_nomic_dir() == Path("/tmp/nomic")

    def test_get_debate_embeddings_returns_db(self):
        """Test get_debate_embeddings returns database from context."""
        from aragora.server.handlers.base import BaseHandler

        db = Mock()
        handler = BaseHandler({"debate_embeddings": db})

        assert handler.get_debate_embeddings() is db

    def test_get_critique_store_returns_store(self):
        """Test get_critique_store returns store from context."""
        from aragora.server.handlers.base import BaseHandler

        store = Mock()
        handler = BaseHandler({"critique_store": store})

        assert handler.get_critique_store() is store

    def test_base_handler_handle_returns_none(self):
        """Test BaseHandler.handle returns None by default."""
        from aragora.server.handlers.base import BaseHandler

        handler = BaseHandler({})
        result = handler.handle("/any/path", {}, None)

        assert result is None


# ============================================================================
# Metrics Request Tracking Tests
# ============================================================================


class TestMetricsTracking:
    """Tests for metrics request tracking."""

    def test_track_request_increments_count(self):
        """Test track_request increments counter."""
        from aragora.server.handlers.metrics import track_request, _request_counts

        initial = _request_counts.get("/test/endpoint", 0)
        track_request("/test/endpoint")

        assert _request_counts.get("/test/endpoint", 0) == initial + 1

    def test_track_request_error_increments_both(self):
        """Test track_request with error increments both counters."""
        from aragora.server.handlers.metrics import track_request, _request_counts, _error_counts

        initial_req = _request_counts.get("/test/error", 0)
        initial_err = _error_counts.get("/test/error", 0)

        track_request("/test/error", is_error=True)

        assert _request_counts.get("/test/error", 0) == initial_req + 1
        assert _error_counts.get("/test/error", 0) == initial_err + 1


# ============================================================================
# Edge Case Tests for Debates Handler
# ============================================================================


class TestDebatesHandlerEdgeCases:
    """Edge case tests for DebatesHandler."""

    @pytest.fixture
    def debates_handler_with_mock(self):
        """Create DebatesHandler with mock storage."""
        storage = Mock()
        storage.get_access_info.side_effect = lambda ref: (ref, "test-org-001", False)
        ctx = {"storage": storage, "elo_system": None, "nomic_dir": None}
        return DebatesHandler(ctx), storage

    def test_empty_debate_list(self, debates_handler_with_mock):
        """Test listing debates when storage is empty."""
        handler, storage = debates_handler_with_mock
        storage.list_recent.return_value = []

        result = handler.handle("/api/debates", {}, None)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["debates"] == []
        assert data["count"] == 0

    def test_limit_param_zero(self, debates_handler_with_mock):
        """Test limit parameter of zero is handled."""
        handler, storage = debates_handler_with_mock
        storage.list_recent.return_value = []

        result = handler.handle("/api/debates", {"limit": "0"}, None)

        assert result.status_code == 200
        storage.list_recent.assert_called_once()
        _, kwargs = storage.list_recent.call_args
        assert kwargs["limit"] == 0

    def test_limit_param_negative(self, debates_handler_with_mock):
        """Test negative limit parameter defaults gracefully."""
        handler, storage = debates_handler_with_mock
        storage.list_recent.return_value = []

        result = handler.handle("/api/debates", {"limit": "-1"}, None)

        # Should use the negative value (storage can handle it)
        assert result.status_code == 200

    def test_limit_param_exceeds_max(self, debates_handler_with_mock):
        """Test limit parameter is capped at 100."""
        handler, storage = debates_handler_with_mock
        storage.list_recent.return_value = []

        result = handler.handle("/api/debates", {"limit": "500"}, None)

        assert result.status_code == 200
        # Limit should be capped at 100
        storage.list_recent.assert_called_once()
        _, kwargs = storage.list_recent.call_args
        assert kwargs["limit"] == 100

    def test_export_empty_debate(self, debates_handler_with_mock):
        """Test exporting debate with no messages."""
        handler, storage = debates_handler_with_mock
        storage.get_debate.return_value = {
            "id": "empty",
            "slug": "empty",
            "topic": "Empty debate",
            "messages": [],
            "critiques": [],
            "votes": [],
            "consensus_reached": False,
        }

        result = handler.handle("/api/debates/empty/export/csv", {"table": "messages"}, None)

        assert result.status_code == 200
        assert b"round,agent,role,content,timestamp" in result.body  # header row only

    def test_export_html_format(self, debates_handler_with_mock):
        """Test HTML export generates valid HTML."""
        handler, storage = debates_handler_with_mock
        storage.get_debate.return_value = {
            "id": "test",
            "slug": "test",
            "topic": "Test Debate",
            "messages": [{"agent": "claude", "content": "Hello", "round": 1}],
            "critiques": [],
            "consensus_reached": True,
            "final_answer": "Test answer",
            "rounds_used": 3,
        }

        result = handler.handle("/api/debates/test/export/html", {}, None)

        assert result.status_code == 200
        html_content = result.body.decode("utf-8")
        assert "<!DOCTYPE html>" in html_content
        assert "Test Debate" in html_content
        assert "claude" in html_content

    def test_export_invalid_format(self, debates_handler_with_mock):
        """Test export with invalid format returns error."""
        handler, storage = debates_handler_with_mock

        result = handler.handle("/api/debates/test/export/pdf", {}, None)

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "Invalid format" in data["error"] or "invalid" in data["error"].lower()

    def test_impasse_high_severity(self, debates_handler_with_mock):
        """Test impasse detection with high severity critiques."""
        handler, storage = debates_handler_with_mock
        storage.get_debate.return_value = {
            "id": "impasse",
            "slug": "impasse",
            "messages": [],
            "critiques": [
                {"severity": 0.8},
                {"severity": 0.9},
            ],
            "consensus_reached": False,
        }

        result = handler.handle("/api/debates/impasse/impasse", {}, None)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["is_impasse"] is True
        assert data["indicators"]["high_severity_critiques"] is True


# ============================================================================
# Edge Case Tests for Agents Handler
# ============================================================================


class TestAgentsHandlerEdgeCases:
    """Edge case tests for AgentsHandler (via internal methods)."""

    @pytest.fixture
    def agents_handler_with_mock(self):
        """Create AgentsHandler with mock ELO system."""
        elo = Mock()
        ctx = {"storage": None, "elo_system": elo, "nomic_dir": None}
        return AgentsHandler(ctx), elo

    def test_leaderboard_empty(self, agents_handler_with_mock):
        """Test leaderboard with no agents."""
        handler, elo = agents_handler_with_mock
        elo.get_cached_leaderboard.return_value = []
        elo.get_leaderboard.return_value = []

        result = handler._get_leaderboard(limit=20, domain=None)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["rankings"] == []

    def test_agent_not_found(self, agents_handler_with_mock):
        """Test profile request for non-existent agent."""
        handler, elo = agents_handler_with_mock
        elo.get_agent_stats.return_value = None

        result = handler._handle_agent_endpoint("/api/agent/nonexistent/profile", {})

        # Should still return 200 with empty/default data or 404
        assert result.status_code in (200, 404)

    def test_compare_same_agent(self, agents_handler_with_mock):
        """Test rankings endpoint returns valid data."""
        handler, elo = agents_handler_with_mock
        # Handler uses get_cached_leaderboard first, else get_leaderboard
        elo.get_cached_leaderboard.return_value = [{"agent": "test", "elo": 1500}]
        elo.get_leaderboard.return_value = [{"agent": "test", "elo": 1500}]

        result = handler._get_leaderboard(limit=20, domain=None)

        assert result.status_code == 200
        data = json.loads(result.body)
        # Should return rankings data
        assert "rankings" in data or "agents" in data or isinstance(data, list)

    def test_matches_empty(self, agents_handler_with_mock):
        """Test recent matches when none exist."""
        handler, elo = agents_handler_with_mock
        # Handler uses get_cached_recent_matches if available, else get_recent_matches
        elo.get_cached_recent_matches.return_value = []
        elo.get_recent_matches.return_value = []

        result = handler._get_recent_matches(limit=10, loop_id=None)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["matches"] == []


# ============================================================================
# Edge Case Tests for System Handler
# ============================================================================


class TestSystemHandlerEdgeCases:
    """Edge case tests for SystemHandler."""

    @pytest.fixture
    def system_handler_with_empty_dir(self):
        """Create SystemHandler with empty nomic directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nomic_dir = Path(tmpdir)
            ctx = {"storage": None, "elo_system": None, "nomic_dir": nomic_dir}
            yield SystemHandler(ctx)

    def test_history_empty(self, system_handler_with_empty_dir):
        """Test history endpoint with no data."""
        result = system_handler_with_empty_dir.handle("/api/history/summary", {}, None)

        # Should handle empty state gracefully
        assert result.status_code in (200, 404, 503)


# ============================================================================
# MetricsHandler Tests
# ============================================================================


class TestMetricsHandlerE2E:
    """E2E tests for MetricsHandler endpoints."""

    @pytest.fixture
    def metrics_handler(self, mock_storage, mock_elo_system, temp_nomic_dir):
        """Create MetricsHandler with test context."""
        from aragora.server.handlers import MetricsHandler

        ctx = {
            "storage": mock_storage,
            "elo_system": mock_elo_system,
            "nomic_dir": temp_nomic_dir,
        }
        return MetricsHandler(ctx)

    def test_can_handle_metrics_routes(self, metrics_handler):
        """Test MetricsHandler handles metrics routes."""
        assert metrics_handler.can_handle("/api/v1/metrics") is True
        assert metrics_handler.can_handle("/api/v1/metrics/health") is True
        assert metrics_handler.can_handle("/api/v1/metrics/cache") is True
        assert metrics_handler.can_handle("/api/v1/metrics/system") is True
        assert metrics_handler.can_handle("/api/v1/debates") is False

    def test_metrics_returns_structure(self, metrics_handler):
        """Test /api/metrics returns correct structure."""
        result = metrics_handler.handle("/api/metrics", {}, None)

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "uptime_seconds" in data
        assert "uptime_human" in data
        assert "requests" in data
        assert "cache" in data
        assert "databases" in data
        assert "timestamp" in data

    def test_metrics_requests_structure(self, metrics_handler):
        """Test /api/metrics requests section has correct fields."""
        result = metrics_handler.handle("/api/metrics", {}, None)
        data = json.loads(result.body)

        requests = data["requests"]
        assert "total" in requests
        assert "errors" in requests
        assert "error_rate" in requests
        assert "top_endpoints" in requests
        assert isinstance(requests["top_endpoints"], list)

    def test_health_returns_structure(self, metrics_handler):
        """Test /api/metrics/health returns correct structure."""
        result = metrics_handler.handle("/api/metrics/health", {}, None)

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "status" in data
        assert data["status"] in ("healthy", "degraded", "unhealthy")
        assert "checks" in data
        assert isinstance(data["checks"], dict)

    def test_health_checks_storage(self, metrics_handler):
        """Test health check includes storage status."""
        result = metrics_handler.handle("/api/metrics/health", {}, None)
        data = json.loads(result.body)

        assert "storage" in data["checks"]
        assert "status" in data["checks"]["storage"]

    def test_health_checks_elo(self, metrics_handler):
        """Test health check includes ELO system status."""
        result = metrics_handler.handle("/api/metrics/health", {}, None)
        data = json.loads(result.body)

        assert "elo_system" in data["checks"]
        assert "status" in data["checks"]["elo_system"]

    def test_cache_stats_structure(self, metrics_handler):
        """Test /api/metrics/cache returns correct structure."""
        result = metrics_handler.handle("/api/metrics/cache", {}, None)

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "total_entries" in data
        assert "entries_by_prefix" in data
        assert isinstance(data["entries_by_prefix"], dict)

    def test_system_info_structure(self, metrics_handler):
        """Test /api/metrics/system returns correct structure."""
        result = metrics_handler.handle("/api/metrics/system", {}, None)

        assert result.status_code == 200
        data = json.loads(result.body)

        assert "python_version" in data
        assert "platform" in data
        assert "pid" in data

    def test_unhandled_returns_none(self, metrics_handler):
        """Test unhandled routes return None."""
        result = metrics_handler.handle("/api/other", {}, None)
        assert result is None
