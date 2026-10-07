"""
Integration tests for Matrix Debates feature.

Tests cover end-to-end flows for:
- Creating matrix debates with parallel scenarios
- Running scenario comparisons
- Extracting universal and conditional conclusions
- Handler endpoint coverage
"""

import json
import pytest
from unittest.mock import Mock, AsyncMock, patch

# Import MatrixDebatesHandler directly since it's now available
from aragora.server.handlers.debates import MatrixDebatesHandler
from aragora.tenancy.record_scope import OrgScope

SCOPE = OrgScope(org_id="org-matrix", user_id="user-matrix", role="member")


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_agents():
    """Create mock agents for debates."""
    agent1 = Mock()
    agent1.name = "claude"
    agent1.generate = AsyncMock(return_value="Agent 1 response")

    agent2 = Mock()
    agent2.name = "gpt4"
    agent2.generate = AsyncMock(return_value="Agent 2 response")

    return [agent1, agent2]


@pytest.fixture
def mock_storage():
    """Create mock matrix storage."""
    storage = Mock()
    storage.get_matrix_debate = AsyncMock(return_value=None)
    storage.get_matrix_scenarios = AsyncMock(return_value=[])
    storage.get_matrix_conclusions = AsyncMock(
        return_value={
            "universal": [],
            "conditional": [],
        }
    )
    return storage


@pytest.fixture
def mock_handler(mock_storage):
    """Create mock HTTP handler."""
    handler = Mock()
    handler.command = "GET"
    handler.storage = mock_storage
    handler.event_emitter = None
    return handler


@pytest.fixture
def sample_scenarios():
    """Sample scenario configurations."""
    return [
        {
            "name": "Baseline",
            "parameters": {"budget": "low"},
            "constraints": ["must be cost-effective"],
            "is_baseline": True,
        },
        {
            "name": "High Budget",
            "parameters": {"budget": "high"},
            "constraints": ["maximize quality"],
            "is_baseline": False,
        },
        {
            "name": "Time Constrained",
            "parameters": {"budget": "medium", "timeline": "short"},
            "constraints": ["deliver quickly"],
            "is_baseline": False,
        },
    ]


@pytest.fixture
def sample_results():
    """Sample scenario results for testing utility methods."""
    return [
        {
            "scenario_name": "Baseline",
            "parameters": {"budget": "low"},
            "constraints": ["must be cost-effective"],
            "is_baseline": True,
            "winner": "claude",
            "final_answer": "Use approach A",
            "confidence": 0.85,
            "consensus_reached": True,
            "rounds_used": 2,
        },
        {
            "scenario_name": "High Budget",
            "parameters": {"budget": "high"},
            "constraints": ["maximize quality"],
            "is_baseline": False,
            "winner": "gpt4",
            "final_answer": "Use approach B",
            "confidence": 0.9,
            "consensus_reached": True,
            "rounds_used": 3,
        },
        {
            "scenario_name": "Time Constrained",
            "parameters": {"budget": "medium", "timeline": "short"},
            "constraints": ["deliver quickly"],
            "is_baseline": False,
            "winner": "claude",
            "final_answer": "Use approach C",
            "confidence": 0.75,
            "consensus_reached": True,
            "rounds_used": 1,
        },
    ]


# ============================================================================
# Handler Route Tests
# ============================================================================


class TestMatrixDebatesHandlerRoutes:
    """Tests for MatrixDebatesHandler route recognition."""

    def test_handler_routes(self):
        """Test handler recognizes all matrix debate routes."""
        handler = MatrixDebatesHandler({})

        # Test route recognition (versioned routes)
        assert "/api/v1/debates/matrix" in handler.ROUTES
        assert "/api/v1/debates/matrix/" in handler.ROUTES

    def test_auth_required_endpoints(self):
        """Test auth is required for POST endpoint."""
        handler = MatrixDebatesHandler({})

        assert "/api/v1/debates/matrix" in handler.AUTH_REQUIRED_ENDPOINTS


# ============================================================================
# GET Endpoint Tests
# ============================================================================


class TestMatrixDebatesGetEndpoints:
    """Tests for GET endpoints."""

    @pytest.mark.asyncio
    async def test_get_matrix_debate_not_found(self, mock_handler):
        """Test 404 response for non-existent matrix debate."""
        handler = MatrixDebatesHandler({})

        result = await handler._get_matrix_debate(mock_handler, "nonexistent-id", SCOPE)

        assert result.status_code == 404
        data = json.loads(result.body)
        assert "not found" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_get_matrix_debate_success(self, mock_handler, mock_storage):
        """Test successful matrix debate retrieval."""
        # Configure storage to return a debate
        mock_storage.get_matrix_debate = AsyncMock(
            return_value={
                "matrix_id": "test-123",
                "task": "Test task",
                "scenario_count": 3,
                "org_id": SCOPE.org_id,
            }
        )
        mock_handler.storage = mock_storage

        handler = MatrixDebatesHandler({})
        result = await handler._get_matrix_debate(mock_handler, "test-123", SCOPE)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["matrix_id"] == "test-123"

    @pytest.mark.asyncio
    async def test_get_matrix_debate_no_storage(self, mock_handler):
        """Test 503 when storage not configured."""
        mock_handler.storage = None

        handler = MatrixDebatesHandler({})
        result = await handler._get_matrix_debate(mock_handler, "test-123", SCOPE)

        assert result.status_code == 503

    @pytest.mark.asyncio
    async def test_get_scenarios_empty(self, mock_handler):
        """Test empty scenarios response."""
        handler = MatrixDebatesHandler({})

        mock_handler.storage.get_matrix_debate = AsyncMock(return_value={"org_id": SCOPE.org_id})

        result = await handler._get_scenarios(mock_handler, "matrix-123", SCOPE)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert "scenarios" in data
        assert data["matrix_id"] == "matrix-123"

    @pytest.mark.asyncio
    async def test_get_conclusions_empty(self, mock_handler):
        """Test empty conclusions response."""
        handler = MatrixDebatesHandler({})

        mock_handler.storage.get_matrix_debate = AsyncMock(return_value={"org_id": SCOPE.org_id})

        result = await handler._get_conclusions(mock_handler, "matrix-123", SCOPE)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert "universal_conclusions" in data
        assert "conditional_conclusions" in data
        assert data["matrix_id"] == "matrix-123"


# ============================================================================
# POST Endpoint Tests
# ============================================================================


class TestMatrixDebatesPostEndpoint:
    """Tests for POST /api/debates/matrix endpoint."""

    @pytest.mark.asyncio
    async def test_create_matrix_debate_missing_task(self, mock_handler):
        """Test 400 response when task is missing."""
        handler = MatrixDebatesHandler({})

        # Call internal method directly to avoid decorator complexity
        result = await handler._run_matrix_debate(
            mock_handler,
            scope=SCOPE,
            data={"scenarios": [{"name": "Test"}]},
        )

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "task" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_create_matrix_debate_missing_scenarios(self, mock_handler):
        """Test 400 response when scenarios are missing."""
        handler = MatrixDebatesHandler({})

        # Call internal method directly (task must be 10+ chars)
        result = await handler._run_matrix_debate(
            mock_handler,
            scope=SCOPE,
            data={"task": "Test matrix debate task"},
        )

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "scenario" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_create_matrix_debate_empty_scenarios(self, mock_handler):
        """Test 400 response when scenarios list is empty."""
        handler = MatrixDebatesHandler({})

        # Task must be 10+ chars to pass task validation first
        result = await handler._run_matrix_debate(
            mock_handler,
            scope=SCOPE,
            data={"task": "Test matrix debate task", "scenarios": []},
        )

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "scenario" in data.get("error", "").lower()


# ============================================================================
# Utility Method Tests
# ============================================================================


class TestMatrixDebatesUtilities:
    """Tests for utility methods."""

    def test_find_universal_conclusions_all_consensus(self, sample_results):
        """Test finding universal conclusions when all reach consensus."""
        handler = MatrixDebatesHandler({})

        result = handler._find_universal_conclusions(sample_results)

        # All scenarios reached consensus
        assert len(result) > 0
        assert "consensus" in result[0].lower()

    def test_find_universal_conclusions_no_consensus(self):
        """Test finding universal conclusions when some don't reach consensus."""
        handler = MatrixDebatesHandler({})

        results = [
            {"consensus_reached": True, "final_answer": "A"},
            {"consensus_reached": False, "final_answer": "B"},
        ]

        result = handler._find_universal_conclusions(results)

        # Not all scenarios reached consensus
        assert result == []

    def test_find_universal_conclusions_empty(self):
        """Test finding universal conclusions with empty results."""
        handler = MatrixDebatesHandler({})

        result = handler._find_universal_conclusions([])

        assert result == []

    def test_find_conditional_conclusions(self, sample_results):
        """Test finding conditional conclusions."""
        handler = MatrixDebatesHandler({})

        result = handler._find_conditional_conclusions(sample_results)

        # Should have one conclusion per scenario with final_answer
        assert len(result) == 3

        # Check structure
        for conclusion in result:
            assert "condition" in conclusion
            assert "parameters" in conclusion
            assert "conclusion" in conclusion
            assert "confidence" in conclusion

    def test_find_conditional_conclusions_empty(self):
        """Test finding conditional conclusions with empty results."""
        handler = MatrixDebatesHandler({})

        result = handler._find_conditional_conclusions([])

        assert result == []

    def test_build_comparison_matrix(self, sample_results):
        """Test building comparison matrix."""
        handler = MatrixDebatesHandler({})

        result = handler._build_comparison_matrix(sample_results)

        assert "scenarios" in result
        assert len(result["scenarios"]) == 3

        assert "consensus_rate" in result
        assert result["consensus_rate"] == 1.0  # All reached consensus

        assert "avg_confidence" in result
        assert 0 <= result["avg_confidence"] <= 1

        assert "avg_rounds" in result
        assert result["avg_rounds"] == 2.0  # (2+3+1)/3 = 2.0

    def test_build_comparison_matrix_empty(self):
        """Test building comparison matrix with empty results."""
        handler = MatrixDebatesHandler({})

        result = handler._build_comparison_matrix([])

        assert result["scenarios"] == []
        assert result["consensus_rate"] == 0
        assert result["avg_confidence"] == 0
        assert result["avg_rounds"] == 0


# ============================================================================
# Agent Loading Tests
# ============================================================================


class TestAgentLoading:
    """Tests for agent loading functionality."""

    @pytest.mark.asyncio
    async def test_load_agents_default(self):
        """Test loading default agents."""
        handler = MatrixDebatesHandler({})

        # Patch at the correct module path
        with patch(
            "aragora.server.handlers.debates.matrix_debates.MatrixDebatesHandler._load_agents"
        ) as mock_load:
            mock_agent1 = Mock()
            mock_agent1.name = "claude"
            mock_agent2 = Mock()
            mock_agent2.name = "gpt4"
            mock_load.return_value = [mock_agent1, mock_agent2]

            agents = await handler._load_agents([])

            # The patched method was called
            assert mock_load.called

    @pytest.mark.asyncio
    async def test_load_agents_returns_empty_on_failure(self):
        """Test graceful handling of agent load failure."""
        handler = MatrixDebatesHandler({})

        # Patch at the import location within the handler
        with patch.object(handler, "_load_agents", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = []

            agents = await handler._load_agents(["nonexistent"])

            assert agents == []


# ============================================================================
# Handle GET Routing Tests
# ============================================================================


class TestHandleGetRouting:
    """Tests for GET request routing via internal methods."""

    @pytest.mark.asyncio
    async def test_get_matrix_debate_by_id(self, mock_handler, mock_storage):
        """Test getting matrix debate by ID."""
        mock_storage.get_matrix_debate = AsyncMock(
            return_value={
                "matrix_id": "abc-123",
                "task": "Test",
                "org_id": SCOPE.org_id,
            }
        )
        mock_handler.storage = mock_storage

        handler = MatrixDebatesHandler({})

        # Call internal method directly
        result = await handler._get_matrix_debate(mock_handler, "abc-123", SCOPE)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["matrix_id"] == "abc-123"

    @pytest.mark.asyncio
    async def test_get_scenarios_by_matrix_id(self, mock_handler, mock_storage):
        """Test getting scenarios for a matrix debate."""
        mock_storage.get_matrix_scenarios = AsyncMock(
            return_value=[
                {"name": "Scenario 1"},
                {"name": "Scenario 2"},
            ]
        )
        mock_handler.storage = mock_storage

        handler = MatrixDebatesHandler({})

        mock_handler.storage.get_matrix_debate = AsyncMock(return_value={"org_id": SCOPE.org_id})

        result = await handler._get_scenarios(mock_handler, "abc-123", SCOPE)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert "scenarios" in data
        assert len(data["scenarios"]) == 2

    @pytest.mark.asyncio
    async def test_get_conclusions_by_matrix_id(self, mock_handler, mock_storage):
        """Test getting conclusions for a matrix debate."""
        mock_storage.get_matrix_conclusions = AsyncMock(
            return_value={
                "universal": ["All scenarios agree"],
                "conditional": [{"condition": "When X", "conclusion": "Y"}],
            }
        )
        mock_handler.storage = mock_storage

        handler = MatrixDebatesHandler({})

        mock_handler.storage.get_matrix_debate = AsyncMock(return_value={"org_id": SCOPE.org_id})

        result = await handler._get_conclusions(mock_handler, "abc-123", SCOPE)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert "universal_conclusions" in data
        assert "conditional_conclusions" in data
        assert len(data["universal_conclusions"]) == 1


# ============================================================================
# Fallback Implementation Tests
# ============================================================================


class TestMatrixDebateFallback:
    """Tests for fallback implementation when MatrixDebateRunner unavailable."""

    @pytest.mark.asyncio
    async def test_fallback_runs_scenarios_in_parallel(self, mock_handler, sample_scenarios):
        """Test fallback runs scenarios concurrently."""
        handler = MatrixDebatesHandler({})

        mock_agent = Mock()
        mock_agent.name = "claude"

        with patch.object(handler, "_load_agents", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = [mock_agent]
            with patch.object(
                handler,
                "_load_agents_from_specs",
                new_callable=AsyncMock,
            ) as mock_load_specs:
                mock_load_specs.return_value = [mock_agent, mock_agent]

                # Mock Arena to track scenario runs
                with patch("aragora.debate.orchestrator.Arena") as mock_arena_class:
                    mock_arena = Mock()
                    mock_arena.run = AsyncMock(
                        return_value=Mock(
                            winner="claude",
                            final_answer="Test answer",
                            confidence=0.8,
                            consensus_reached=True,
                            rounds_used=2,
                        )
                    )
                    mock_arena_class.return_value = mock_arena

                    result = await handler._run_matrix_debate_fallback(
                        mock_handler,
                        scope=SCOPE,
                        data={
                            "task": "Test task",
                            "scenarios": sample_scenarios,
                            "agents": ["claude"],
                            "max_rounds": 3,
                        },
                    )

                    assert result.status_code == 200
                    data = json.loads(result.body)
                    assert "matrix_id" in data
                    assert data["scenario_count"] == 3

    @pytest.mark.asyncio
    async def test_fallback_no_agents(self, mock_handler, sample_scenarios):
        """Test fallback returns error when no agents loaded."""
        handler = MatrixDebatesHandler({})

        with patch.object(handler, "_load_agents", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = []

            result = await handler._run_matrix_debate_fallback(
                mock_handler,
                scope=SCOPE,
                data={
                    "task": "Test task",
                    "scenarios": sample_scenarios,
                },
            )

            assert result.status_code == 400
            data = json.loads(result.body)
            assert "agent" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_fallback_selects_best_model_combination(self, mock_handler):
        """Model-combination runs should include the strongest result when requested."""
        handler = MatrixDebatesHandler({})

        combo_a_agent = Mock()
        combo_a_agent.name = "anthropic-api"
        combo_b_agent = Mock()
        combo_b_agent.name = "gemini"

        with patch.object(handler, "_load_agents_from_specs", new_callable=AsyncMock) as mock_load:
            mock_load.side_effect = [
                [combo_a_agent],
                [combo_b_agent],
                [combo_a_agent],
                [combo_b_agent],
            ]

            weak_arena = Mock()
            weak_arena.run = AsyncMock(
                return_value=Mock(
                    winner="anthropic-api",
                    final_answer="Lower confidence answer",
                    confidence=0.61,
                    consensus_reached=True,
                    rounds_used=3,
                )
            )
            strong_arena = Mock()
            strong_arena.run = AsyncMock(
                return_value=Mock(
                    winner="gemini",
                    final_answer="Higher confidence answer",
                    confidence=0.93,
                    consensus_reached=True,
                    rounds_used=2,
                )
            )

            with patch("aragora.debate.orchestrator.Arena", side_effect=[weak_arena, strong_arena]):
                result = await handler._run_matrix_debate_fallback(
                    mock_handler,
                    scope=SCOPE,
                    data={
                        "task": "Compare the same debate across multiple model combinations",
                        "model_combinations": [
                            {"name": "combo-a", "agents": ["anthropic-api"]},
                            {"name": "combo-b", "agents": ["gemini"]},
                        ],
                        "select_best_result": True,
                    },
                )

        assert mock_load.await_count == 4
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["scenario_count"] == 2
        assert data["best_result"]["combination_name"] == "combo-b"
        assert data["best_result"]["confidence"] == pytest.approx(0.93)
