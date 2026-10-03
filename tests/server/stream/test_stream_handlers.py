"""
Tests for StreamAPIHandlersMixin HTTP handlers.

Tests cover:
- Handler responses with missing/null subsystems (graceful empty responses)
- Query parameter validation (limit, min_confidence, threshold)
- Path parameter validation (tournament_id, agent_name, loop_id, replay_id)
- CORS headers on all responses
- Error handling and 500 responses
- Happy path with mocked subsystems
"""

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.stream.stream_handlers import StreamAPIHandlersMixin


# ===========================================================================
# Test Fixtures
# ===========================================================================


class MockRequest:
    """Mock aiohttp request object."""

    def __init__(
        self,
        query: dict[str, str] | None = None,
        match_info: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.query = query or {}
        self.match_info = match_info or {}
        self.headers = headers or {}


class ConcreteStreamAPIHandlers(StreamAPIHandlersMixin):
    """Concrete implementation of the mixin for testing."""

    def __init__(
        self,
        nomic_dir: Path | None = None,
        elo_system: Any = None,
        insight_store: Any = None,
        flip_detector: Any = None,
        persona_manager: Any = None,
        debate_embeddings: Any = None,
        audience_inbox: Any = None,
    ):
        self.nomic_dir = nomic_dir
        self.elo_system = elo_system
        self.insight_store = insight_store
        self.flip_detector = flip_detector
        self.persona_manager = persona_manager
        self.debate_embeddings = debate_embeddings
        self.active_loops: dict[str, Any] = {}
        self._active_loops_lock = threading.Lock()
        self.cartographers: dict[str, Any] = {}
        self._cartographers_lock = threading.Lock()
        self.audience_inbox = audience_inbox
        self.emitter = MagicMock()

    def _cors_headers(self, origin: str | None) -> dict[str, str]:
        """Return CORS headers for testing."""
        return {
            "Access-Control-Allow-Origin": origin or "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }


@pytest.fixture
def handler():
    """Create a handler instance with no subsystems."""
    return ConcreteStreamAPIHandlers()


@pytest.fixture
def request_factory():
    """Factory for creating mock requests."""

    def _create(
        query: dict[str, str] | None = None,
        match_info: dict[str, str] | None = None,
        origin: str | None = None,
    ) -> MockRequest:
        headers = {"Origin": origin} if origin else {}
        return MockRequest(query=query, match_info=match_info, headers=headers)

    return _create


# ===========================================================================
# Test CORS Handler
# ===========================================================================


class TestCORSHandler:
    """Tests for _handle_options CORS preflight handler."""

    @pytest.mark.asyncio
    async def test_returns_204_status(self, handler, request_factory):
        """OPTIONS request returns 204 No Content."""
        request = request_factory(origin="http://localhost:3000")

        with patch("aiohttp.web.Response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_options(request)
            mock_response.assert_called_once()
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs["status"] == 204

    @pytest.mark.asyncio
    async def test_includes_cors_headers(self, handler, request_factory):
        """OPTIONS response includes CORS headers."""
        request = request_factory(origin="http://localhost:3000")

        with patch("aiohttp.web.Response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_options(request)
            call_kwargs = mock_response.call_args[1]
            assert "Access-Control-Allow-Origin" in call_kwargs["headers"]


# ===========================================================================
# Test Leaderboard Handlers
# ===========================================================================


class TestLeaderboardHandler:
    """Tests for _handle_leaderboard endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_elo_system(self, handler, request_factory):
        """Returns empty leaderboard when elo_system is None."""
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_leaderboard(request)
            call_args = mock_response.call_args[0][0]
            assert call_args == {"agents": [], "count": 0}

    @pytest.mark.asyncio
    async def test_respects_limit_parameter(self, request_factory):
        """Limit parameter is passed to elo_system."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.return_value = []
        handler = ConcreteStreamAPIHandlers(elo_system=mock_elo)
        request = request_factory(query={"limit": "5"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_leaderboard(request)
            mock_elo.get_leaderboard.assert_called_once_with(limit=5)

    @pytest.mark.asyncio
    async def test_formats_agent_data_correctly(self, request_factory):
        """Agent data is formatted with correct fields."""

        @dataclass
        class MockAgent:
            agent_name: str = "claude"
            elo: float = 1500.7
            wins: int = 10
            losses: int = 5
            draws: int = 2
            win_rate: float = 0.667
            games_played: int = 17

        mock_elo = MagicMock()
        mock_elo.get_leaderboard.return_value = [MockAgent()]
        handler = ConcreteStreamAPIHandlers(elo_system=mock_elo)
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_leaderboard(request)
            call_args = mock_response.call_args[0][0]
            agent = call_args["agents"][0]
            assert agent["name"] == "claude"
            assert agent["elo"] == 1501  # Rounded
            assert agent["win_rate"] == 66.7  # Percentage

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self, request_factory):
        """Returns 500 error on exception."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = RuntimeError("Database error")
        handler = ConcreteStreamAPIHandlers(elo_system=mock_elo)
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_leaderboard(request)
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("status") == 500


class TestMatchesRecentHandler:
    """Tests for _handle_matches_recent endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_elo_system(self, handler, request_factory):
        """Returns empty matches when elo_system is None."""
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_matches_recent(request)
            call_args = mock_response.call_args[0][0]
            assert call_args == {"matches": [], "count": 0}

    @pytest.mark.asyncio
    async def test_returns_matches_from_elo_system(self, request_factory):
        """Returns matches from elo_system."""
        mock_elo = MagicMock()
        mock_elo.get_recent_matches.return_value = [
            {"agent_a": "claude", "agent_b": "gpt4", "winner": "claude"}
        ]
        handler = ConcreteStreamAPIHandlers(elo_system=mock_elo)
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_matches_recent(request)
            call_args = mock_response.call_args[0][0]
            assert call_args["count"] == 1
            assert call_args["matches"][0]["winner"] == "claude"


# ===========================================================================
# Test Insights Handlers
# ===========================================================================


class TestInsightsRecentHandler:
    """Tests for _handle_insights_recent endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_insight_store(self, handler, request_factory):
        """Returns empty insights when insight_store is None."""
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_insights_recent(request)
            call_args = mock_response.call_args[0][0]
            assert call_args == {"insights": [], "count": 0}

    @pytest.mark.asyncio
    async def test_calls_to_dict_on_insights(self, request_factory):
        """Converts insights to dict if they have to_dict method."""
        mock_insight = MagicMock()
        mock_insight.to_dict.return_value = {"id": "1", "text": "test"}

        mock_store = MagicMock()
        mock_store.get_recent_insights = AsyncMock(return_value=[mock_insight])
        handler = ConcreteStreamAPIHandlers(insight_store=mock_store)
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_insights_recent(request)
            mock_insight.to_dict.assert_called_once()


class TestFlipsSummaryHandler:
    """Tests for _handle_flips_summary endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_flip_detector(self, handler, request_factory):
        """Returns empty summary when flip_detector is None."""
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_flips_summary(request)
            call_args = mock_response.call_args[0][0]
            assert call_args == {"summary": {}, "count": 0}

    @pytest.mark.asyncio
    async def test_extracts_total_flips_from_summary(self, request_factory):
        """Extracts total_flips count from summary."""
        mock_detector = MagicMock()
        mock_detector.get_flip_summary.return_value = {"total_flips": 42, "by_agent": {}}
        handler = ConcreteStreamAPIHandlers(flip_detector=mock_detector)
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_flips_summary(request)
            call_args = mock_response.call_args[0][0]
            assert call_args["count"] == 42


class TestFlipsRecentHandler:
    """Tests for _handle_flips_recent endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_flip_detector(self, handler, request_factory):
        """Returns empty flips when flip_detector is None."""
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_flips_recent(request)
            call_args = mock_response.call_args[0][0]
            assert call_args == {"flips": [], "count": 0}


# ===========================================================================
# Test Tournament Handlers
# ===========================================================================


class TestTournamentsHandler:
    """Tests for _handle_tournaments endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_nomic_dir(self, handler, request_factory):
        """Returns empty tournaments when nomic_dir is None."""
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_tournaments(request)
            call_args = mock_response.call_args[0][0]
            assert call_args == {"tournaments": [], "count": 0}

    @pytest.mark.asyncio
    async def test_handles_missing_tournaments_dir(self, request_factory, tmp_path):
        """Returns empty when tournaments dir doesn't exist."""
        handler = ConcreteStreamAPIHandlers(nomic_dir=tmp_path)
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_tournaments(request)
            call_args = mock_response.call_args[0][0]
            assert call_args == {"tournaments": [], "count": 0}


class TestTournamentDetailsHandler:
    """Tests for _handle_tournament_details endpoint."""

    @pytest.mark.asyncio
    async def test_rejects_invalid_tournament_id_format(self, handler, request_factory):
        """Rejects tournament_id with invalid characters."""
        request = request_factory(match_info={"tournament_id": "../etc/passwd"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_tournament_details(request)
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("status") == 400
            call_args = mock_response.call_args[0][0]
            assert "Invalid tournament ID format" in call_args["error"]

    @pytest.mark.asyncio
    async def test_returns_503_when_no_nomic_dir(self, handler, request_factory):
        """Returns 503 when nomic_dir is not configured."""
        request = request_factory(match_info={"tournament_id": "test-tournament"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_tournament_details(request)
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("status") == 503

    @pytest.mark.asyncio
    async def test_returns_404_when_tournament_not_found(self, request_factory, tmp_path):
        """Returns 404 when tournament file doesn't exist."""
        (tmp_path / "tournaments").mkdir()
        handler = ConcreteStreamAPIHandlers(nomic_dir=tmp_path)
        request = request_factory(match_info={"tournament_id": "nonexistent"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_tournament_details(request)
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("status") == 404


# ===========================================================================
# Test Agent Analysis Handlers
# ===========================================================================


class TestAgentConsistencyHandler:
    """Tests for _handle_agent_consistency endpoint."""

    @pytest.mark.asyncio
    async def test_rejects_invalid_agent_name_format(self, handler, request_factory):
        """Rejects agent_name with invalid characters."""
        request = request_factory(match_info={"name": "agent;DROP TABLE"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_agent_consistency(request)
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("status") == 400

    @pytest.mark.asyncio
    async def test_accepts_valid_agent_names(self, handler, request_factory):
        """Accepts valid agent names with alphanumeric, underscore, hyphen."""
        valid_names = ["claude", "gpt-4", "agent_001", "Claude-3-5-sonnet"]

        for name in valid_names:
            request = request_factory(match_info={"name": name})

            with patch("aiohttp.web.json_response") as mock_response:
                mock_response.return_value = MagicMock()
                # FlipDetector is imported inside the handler, so patch at the source
                with patch("aragora.insights.flip_detector.FlipDetector") as mock_fd:
                    mock_fd.return_value.get_agent_consistency.return_value = None
                    with patch("aragora.persistence.db_config.get_db_path") as mock_db:
                        mock_db.return_value = ":memory:"
                        await handler._handle_agent_consistency(request)

                call_kwargs = mock_response.call_args[1]
                assert call_kwargs.get("status") is None  # 200 OK

    @pytest.mark.asyncio
    async def test_returns_default_consistency_when_no_data(self, handler, request_factory):
        """Returns default high consistency when no data for agent."""
        request = request_factory(match_info={"name": "new-agent"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            # FlipDetector is imported inside the handler, so patch at the source
            with patch("aragora.insights.flip_detector.FlipDetector") as mock_fd:
                mock_fd.return_value.get_agent_consistency.return_value = None
                with patch("aragora.persistence.db_config.get_db_path") as mock_db:
                    mock_db.return_value = ":memory:"
                    await handler._handle_agent_consistency(request)

            call_args = mock_response.call_args[0][0]
            assert call_args["agent"] == "new-agent"
            assert call_args["consistency"] == 1.0
            assert call_args["consistency_class"] == "high"


class TestAgentNetworkHandler:
    """Tests for _handle_agent_network endpoint."""

    @pytest.mark.asyncio
    async def test_rejects_invalid_agent_name_format(self, handler, request_factory):
        """Rejects agent_name with invalid characters."""
        request = request_factory(match_info={"name": "agent/../../../etc"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_agent_network(request)
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("status") == 400

    @pytest.mark.asyncio
    async def test_returns_empty_network_when_no_systems(self, handler, request_factory):
        """Returns empty network data when no persona_manager or elo_system."""
        request = request_factory(match_info={"name": "claude"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_agent_network(request)
            call_args = mock_response.call_args[0][0]
            assert call_args["agent"] == "claude"
            assert call_args["influences"] == []
            assert call_args["rivals"] == []
            assert call_args["allies"] == []


# ===========================================================================
# Test Memory and Laboratory Handlers
# ===========================================================================


class TestMemoryTierStatsHandler:
    """Tests for _handle_memory_tier_stats endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_debate_embeddings(self, handler, request_factory):
        """Returns zero stats when debate_embeddings is None."""
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_memory_tier_stats(request)
            call_args = mock_response.call_args[0][0]
            assert call_args == {
                "tiers": {"fast": 0, "medium": 0, "slow": 0, "glacial": 0},
                "total": 0,
            }

    @pytest.mark.asyncio
    async def test_sums_tier_stats_for_total(self, request_factory):
        """Sums all tier stats for total."""
        mock_embeddings = MagicMock()
        mock_embeddings.get_tier_stats.return_value = {
            "fast": 10,
            "medium": 20,
            "slow": 30,
            "glacial": 40,
        }
        handler = ConcreteStreamAPIHandlers(debate_embeddings=mock_embeddings)
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_memory_tier_stats(request)
            call_args = mock_response.call_args[0][0]
            assert call_args["total"] == 100


class TestLaboratoryEmergentTraitsHandler:
    """Tests for _handle_laboratory_emergent_traits endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_persona_manager(self, handler, request_factory):
        """Returns empty traits when persona_manager is None."""
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_laboratory_emergent_traits(request)
            call_args = mock_response.call_args[0][0]
            assert call_args == {"traits": [], "count": 0}

    @pytest.mark.asyncio
    async def test_passes_query_params_to_persona_manager(self, request_factory):
        """Passes min_confidence and limit to persona_manager."""
        mock_persona = MagicMock()
        mock_persona.get_emergent_traits.return_value = []
        handler = ConcreteStreamAPIHandlers(persona_manager=mock_persona)
        request = request_factory(query={"min_confidence": "0.7", "limit": "25"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_laboratory_emergent_traits(request)
            mock_persona.get_emergent_traits.assert_called_once_with(min_confidence=0.7, limit=25)


class TestLaboratoryCrossPollinationsHandler:
    """Tests for _handle_laboratory_cross_pollinations endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_persona_manager(self, handler, request_factory):
        """Returns empty suggestions when persona_manager is None."""
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_laboratory_cross_pollinations(request)
            call_args = mock_response.call_args[0][0]
            assert call_args == {"suggestions": [], "count": 0}


# ===========================================================================
# Test Nomic State Handlers
# ===========================================================================


class TestHealthHandler:
    """Tests for _handle_health endpoint."""

    @pytest.mark.asyncio
    async def test_returns_healthy_status(self, handler, request_factory):
        """Returns healthy status with timestamp and version."""
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_health(request)
            call_args = mock_response.call_args[0][0]
            assert call_args["status"] == "healthy"
            assert "timestamp" in call_args
            assert "version" in call_args


class TestMetricsHandler:
    """Tests for _handle_metrics endpoint."""

    @pytest.mark.asyncio
    async def test_returns_prometheus_metrics(self, handler, request_factory):
        """Returns Prometheus-formatted metrics."""
        request = request_factory()

        with patch("aiohttp.web.Response") as mock_response:
            mock_response.return_value = MagicMock()
            # get_prometheus_metrics is imported inside the handler from aragora.server.prometheus
            with patch("aragora.observability.prometheus.get_prometheus_metrics") as mock_metrics:
                mock_metrics.return_value = "# HELP test_metric Test\n"
                await handler._handle_metrics(request)

            call_kwargs = mock_response.call_args[1]
            assert (
                "prometheus" in call_kwargs.get("content_type", "").lower()
                or call_kwargs.get("text") == "# HELP test_metric Test\n"
            )

    @pytest.mark.asyncio
    async def test_handles_missing_prometheus_client(self, handler, request_factory):
        """Returns placeholder when prometheus_client not installed."""
        request = request_factory()

        with patch("aiohttp.web.Response") as mock_response:
            mock_response.return_value = MagicMock()
            # Simulate ImportError when trying to import from aragora.server.prometheus
            with patch.dict("sys.modules", {"aragora.observability.prometheus": None}):
                await handler._handle_metrics(request)

            # Should not raise, returns text response
            assert mock_response.called


class TestNomicStateHandler:
    """Tests for _handle_nomic_state endpoint."""

    @pytest.mark.asyncio
    async def test_returns_idle_when_no_active_loops(self, handler, request_factory):
        """Returns idle state when no active loops."""
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_nomic_state(request)
            call_args = mock_response.call_args[0][0]
            assert call_args == {"cycle": 0, "phase": "idle"}

    @pytest.mark.asyncio
    async def test_returns_active_loop_state(self, request_factory):
        """Returns state from first active loop."""
        handler = ConcreteStreamAPIHandlers()

        @dataclass
        class MockLoop:
            cycle: int = 5
            phase: str = "debate"
            loop_id: str = "test-loop-1"
            name: str = "Test Loop"

        handler.active_loops["test-loop-1"] = MockLoop()
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_nomic_state(request)
            call_args = mock_response.call_args[0][0]
            assert call_args["cycle"] == 5
            assert call_args["phase"] == "debate"
            assert call_args["loop_id"] == "test-loop-1"


# ===========================================================================
# Test Graph Visualization Handlers
# ===========================================================================


class TestGraphJsonHandler:
    """Tests for _handle_graph_json endpoint."""

    @pytest.mark.asyncio
    async def test_rejects_invalid_loop_id_format(self, handler, request_factory):
        """Rejects loop_id with path traversal characters."""
        request = request_factory(match_info={"loop_id": "../../../etc/passwd"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_graph_json(request)
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("status") == 400

    @pytest.mark.asyncio
    async def test_returns_404_when_cartographer_not_found(self, handler, request_factory):
        """Returns 404 when no cartographer for loop_id."""
        request = request_factory(match_info={"loop_id": "nonexistent-loop"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_graph_json(request)
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("status") == 404

    @pytest.mark.asyncio
    async def test_returns_graph_json_from_cartographer(self, request_factory):
        """Returns JSON from cartographer.export_json()."""
        handler = ConcreteStreamAPIHandlers()
        mock_cartographer = MagicMock()
        mock_cartographer.export_json.return_value = '{"nodes": [], "edges": []}'
        handler.cartographers["test-loop"] = mock_cartographer
        request = request_factory(match_info={"loop_id": "test-loop"})

        with patch("aiohttp.web.Response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_graph_json(request)
            mock_cartographer.export_json.assert_called_once_with(include_full_content=False)


class TestGraphMermaidHandler:
    """Tests for _handle_graph_mermaid endpoint."""

    @pytest.mark.asyncio
    async def test_validates_direction_parameter(self, request_factory):
        """Only accepts TD or LR for direction parameter."""
        handler = ConcreteStreamAPIHandlers()
        mock_cartographer = MagicMock()
        mock_cartographer.export_mermaid.return_value = "graph TD\n  A --> B"
        handler.cartographers["test-loop"] = mock_cartographer

        # Invalid direction should default to TD
        request = request_factory(
            match_info={"loop_id": "test-loop"}, query={"direction": "INVALID"}
        )

        with patch("aiohttp.web.Response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_graph_mermaid(request)
            mock_cartographer.export_mermaid.assert_called_once_with(direction="TD")


class TestGraphStatsHandler:
    """Tests for _handle_graph_stats endpoint."""

    @pytest.mark.asyncio
    async def test_returns_statistics_from_cartographer(self, request_factory):
        """Returns statistics from cartographer.get_statistics()."""
        handler = ConcreteStreamAPIHandlers()
        mock_cartographer = MagicMock()
        mock_cartographer.get_statistics.return_value = {
            "node_count": 10,
            "edge_count": 15,
        }
        handler.cartographers["test-loop"] = mock_cartographer
        request = request_factory(match_info={"loop_id": "test-loop"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_graph_stats(request)
            call_args = mock_response.call_args[0][0]
            assert call_args["node_count"] == 10
            assert call_args["edge_count"] == 15


# ===========================================================================
# Test Audience Handlers
# ===========================================================================


class TestAudienceClustersHandler:
    """Tests for _handle_audience_clusters endpoint."""

    @pytest.mark.asyncio
    async def test_rejects_invalid_loop_id_format(self, handler, request_factory):
        """Rejects loop_id with invalid characters."""
        request = request_factory(match_info={"loop_id": "loop;DROP TABLE"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_audience_clusters(request)
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("status") == 400

    @pytest.mark.asyncio
    async def test_returns_error_when_no_audience_inbox(self, handler, request_factory):
        """Returns error when audience_inbox is None."""
        request = request_factory(match_info={"loop_id": "test-loop"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_audience_clusters(request)
            call_args = mock_response.call_args[0][0]
            assert "error" in call_args or call_args.get("clusters") == []

    @pytest.mark.asyncio
    async def test_does_not_drain_suggestions_when_reading_clusters(self, request_factory):
        """GET audience clusters should not consume pending suggestions."""
        from aragora.server.stream.emitter import AudienceInbox
        from aragora.events.types import AudienceMessage

        inbox = AudienceInbox()
        inbox.put(
            AudienceMessage(
                type="suggestion",
                loop_id="test-loop",
                payload={"text": "Add more benchmarks", "user_id": "user-1"},
            )
        )
        handler = ConcreteStreamAPIHandlers(audience_inbox=inbox)
        request = request_factory(match_info={"loop_id": "test-loop"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_audience_clusters(request)

        remaining = inbox.drain_suggestions(loop_id="test-loop")
        assert len(remaining) == 1
        assert remaining[0]["text"] == "Add more benchmarks"


# ===========================================================================
# Test Replay Handlers
# ===========================================================================


class TestReplaysHandler:
    """Tests for _handle_replays endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_nomic_dir(self, handler, request_factory):
        """Returns empty replays when nomic_dir is None."""
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_replays(request)
            call_args = mock_response.call_args[0][0]
            assert call_args == {"replays": [], "count": 0}

    @pytest.mark.asyncio
    async def test_returns_empty_when_replays_dir_missing(self, request_factory, tmp_path):
        """Returns empty when replays directory doesn't exist."""
        handler = ConcreteStreamAPIHandlers(nomic_dir=tmp_path)
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_replays(request)
            call_args = mock_response.call_args[0][0]
            assert call_args == {"replays": [], "count": 0}

    @pytest.mark.asyncio
    async def test_respects_limit_parameter(self, request_factory, tmp_path):
        """Respects limit query parameter."""
        replays_dir = tmp_path / "replays"
        replays_dir.mkdir()

        # Create 5 replay directories
        for i in range(5):
            replay_dir = replays_dir / f"replay-{i}"
            replay_dir.mkdir()
            (replay_dir / "meta.json").write_text(json.dumps({"topic": f"Test {i}"}))

        handler = ConcreteStreamAPIHandlers(nomic_dir=tmp_path)
        request = request_factory(query={"limit": "2"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_replays(request)
            call_args = mock_response.call_args[0][0]
            assert len(call_args["replays"]) <= 2

    @pytest.mark.asyncio
    async def test_treats_non_object_meta_as_empty(self, request_factory, tmp_path):
        """Valid JSON that is not an object degrades to default replay metadata."""
        replays_dir = tmp_path / "replays"
        replay_dir = replays_dir / "replay-non-object-meta"
        replay_dir.mkdir(parents=True)
        (replay_dir / "meta.json").write_text("[]")

        handler = ConcreteStreamAPIHandlers(nomic_dir=tmp_path)
        request = request_factory()

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_replays(request)
            call_args = mock_response.call_args[0][0]
            assert call_args["count"] == 1
            assert call_args["replays"][0]["id"] == "replay-non-object-meta"
            assert call_args["replays"][0]["topic"] == "replay-non-object-meta"


class TestReplayHtmlHandler:
    """Tests for _handle_replay_html endpoint."""

    @pytest.mark.asyncio
    async def test_rejects_invalid_replay_id_format(self, handler, request_factory):
        """Rejects replay_id with path traversal characters."""
        request = request_factory(match_info={"replay_id": "../../../etc/passwd"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_replay_html(request)
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("status") == 400

    @pytest.mark.asyncio
    async def test_returns_500_when_no_nomic_dir(self, handler, request_factory):
        """Returns 500 when nomic_dir is not configured."""
        request = request_factory(match_info={"replay_id": "test-replay"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_replay_html(request)
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("status") == 500

    @pytest.mark.asyncio
    async def test_returns_404_when_replay_not_found(self, request_factory, tmp_path):
        """Returns 404 when replay directory doesn't exist."""
        (tmp_path / "replays").mkdir()
        handler = ConcreteStreamAPIHandlers(nomic_dir=tmp_path)
        request = request_factory(match_info={"replay_id": "nonexistent"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_replay_html(request)
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("status") == 404

    @pytest.mark.asyncio
    async def test_returns_pregenerated_html(self, request_factory, tmp_path):
        """Returns pre-generated HTML if exists."""
        replays_dir = tmp_path / "replays"
        replay_dir = replays_dir / "test-replay"
        replay_dir.mkdir(parents=True)
        (replay_dir / "replay.html").write_text("<html><body>Test</body></html>")

        handler = ConcreteStreamAPIHandlers(nomic_dir=tmp_path)
        request = request_factory(match_info={"replay_id": "test-replay"})

        with patch("aiohttp.web.Response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_replay_html(request)
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("content_type") == "text/html"
            assert "<html>" in call_kwargs.get("text", "")

    @pytest.mark.asyncio
    async def test_tolerates_non_object_meta_and_malformed_event_shapes(
        self, request_factory, tmp_path
    ):
        """Replay HTML generation skips malformed JSON shapes instead of returning 500."""
        replays_dir = tmp_path / "replays"
        replay_dir = replays_dir / "test-replay"
        replay_dir.mkdir(parents=True)
        (replay_dir / "meta.json").write_text("[]")
        (replay_dir / "events.jsonl").write_text(
            "\n".join(
                [
                    json.dumps("not-an-event"),
                    json.dumps(
                        {
                            "type": "agent_message",
                            "agent": "claude",
                            "data": "bad-payload",
                            "round": [],
                        }
                    ),
                    json.dumps(
                        {
                            "type": "critique",
                            "agent": "gemini",
                            "data": {"role": "critic", "content": "Hello"},
                            "round": 1,
                        }
                    ),
                ]
            )
        )

        handler = ConcreteStreamAPIHandlers(nomic_dir=tmp_path)
        request = request_factory(match_info={"replay_id": "test-replay"})

        with (
            patch("aiohttp.web.Response") as mock_response,
            patch("aiohttp.web.json_response") as mock_json_response,
        ):
            mock_response.return_value = MagicMock()
            await handler._handle_replay_html(request)
            mock_json_response.assert_not_called()
            call_kwargs = mock_response.call_args[1]
            assert call_kwargs.get("content_type") == "text/html"
            assert "Hello" in call_kwargs.get("text", "")


# ===========================================================================
# Test Query Parameter Validation
# ===========================================================================


class TestQueryParameterValidation:
    """Tests for query parameter validation across handlers."""

    @pytest.mark.asyncio
    async def test_limit_defaults_to_10(self, request_factory):
        """Limit parameter defaults to 10 when not provided."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.return_value = []
        handler = ConcreteStreamAPIHandlers(elo_system=mock_elo)
        request = request_factory()  # No limit param

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_leaderboard(request)
            mock_elo.get_leaderboard.assert_called_once_with(limit=10)

    @pytest.mark.asyncio
    async def test_limit_capped_at_100(self, request_factory):
        """Limit parameter is capped at 100."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.return_value = []
        handler = ConcreteStreamAPIHandlers(elo_system=mock_elo)
        request = request_factory(query={"limit": "500"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_leaderboard(request)
            mock_elo.get_leaderboard.assert_called_once_with(limit=100)

    @pytest.mark.asyncio
    async def test_min_confidence_clamped_to_valid_range(self, request_factory):
        """min_confidence is clamped between 0.0 and 1.0."""
        mock_persona = MagicMock()
        mock_persona.get_emergent_traits.return_value = []
        handler = ConcreteStreamAPIHandlers(persona_manager=mock_persona)

        # Test value > 1.0
        request = request_factory(query={"min_confidence": "2.0"})

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_laboratory_emergent_traits(request)
            call_args = mock_persona.get_emergent_traits.call_args
            assert call_args[1]["min_confidence"] <= 1.0


# ===========================================================================
# Test CORS Headers on All Responses
# ===========================================================================


class TestCORSHeadersOnAllResponses:
    """Tests that CORS headers are included on all responses."""

    @pytest.mark.asyncio
    async def test_cors_headers_on_success_response(self, handler, request_factory):
        """CORS headers included on successful responses."""
        request = request_factory(origin="http://localhost:3000")

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_health(request)
            call_kwargs = mock_response.call_args[1]
            assert "headers" in call_kwargs
            assert "Access-Control-Allow-Origin" in call_kwargs["headers"]

    @pytest.mark.asyncio
    async def test_cors_headers_on_error_response(self, handler, request_factory):
        """CORS headers included on error responses."""
        mock_elo = MagicMock()
        mock_elo.get_leaderboard.side_effect = RuntimeError("Error")
        handler.elo_system = mock_elo
        request = request_factory(origin="http://localhost:3000")

        with patch("aiohttp.web.json_response") as mock_response:
            mock_response.return_value = MagicMock()
            await handler._handle_leaderboard(request)
            call_kwargs = mock_response.call_args[1]
            assert "headers" in call_kwargs
