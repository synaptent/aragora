"""Tests for matrix debates handler.

Tests the matrix debates API endpoints including:
- POST /api/v1/debates/matrix - Run parallel scenario debates
- GET /api/v1/debates/matrix/{id} - Get matrix debate results
- GET /api/v1/debates/matrix/{id}/scenarios - Get all scenario results
- GET /api/v1/debates/matrix/{id}/conclusions - Get universal/conditional conclusions
"""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aragora.server.handlers.utils.responses import HandlerResult

from aragora.tenancy.record_scope import OrgScope

pytestmark = pytest.mark.usefixtures("org_scoped_request_user")

TEST_ORG = "test-org-001"
SCOPE = OrgScope(org_id=TEST_ORG, user_id="test-user-001", role="admin")


@pytest.fixture
def matrix_handler():
    """Create matrix debates handler with mock context."""
    from aragora.server.handlers.debates.matrix_debates import MatrixDebatesHandler

    ctx = {}
    handler = MatrixDebatesHandler(ctx)
    return handler


@pytest.fixture(autouse=True)
def reset_state():
    """Reset state before each test."""
    try:
        from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

        reset_rate_limiters()
    except ImportError:
        pass

    # Also reset the module-level rate limiter
    try:
        from aragora.server.handlers.debates import matrix_debates

        matrix_debates._matrix_limiter = matrix_debates.RateLimiter(requests_per_minute=5)
    except (ImportError, AttributeError):
        pass

    yield

    try:
        from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

        reset_rate_limiters()
    except ImportError:
        pass


@pytest.fixture
def mock_http_handler():
    """Create mock HTTP handler."""
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    return handler


# =============================================================================
# Initialization Tests
# =============================================================================


class TestMatrixDebatesHandlerInit:
    """Tests for handler initialization."""

    def test_routes_defined(self, matrix_handler):
        """Test that handler routes are defined."""
        assert hasattr(matrix_handler, "ROUTES")
        assert len(matrix_handler.ROUTES) > 0

    def test_can_handle_matrix_path(self, matrix_handler):
        """Test can_handle recognizes matrix paths."""
        assert matrix_handler.can_handle("/api/v1/debates/matrix")
        assert matrix_handler.can_handle("/api/v1/debates/matrix/")
        assert matrix_handler.can_handle("/api/v1/debates/matrix/abc123")
        assert matrix_handler.can_handle("/api/v1/debates/matrix/abc123/scenarios")
        assert matrix_handler.can_handle("/api/v1/debates/matrix/abc123/conclusions")

    def test_cannot_handle_other_paths(self, matrix_handler):
        """Test can_handle rejects non-matrix paths."""
        assert not matrix_handler.can_handle("/api/v1/debates")
        assert not matrix_handler.can_handle("/api/v1/debates/abc123")
        assert not matrix_handler.can_handle("/api/v1/debates/graph")
        assert not matrix_handler.can_handle("/api/v1/users")


# =============================================================================
# POST Validation Tests
# =============================================================================


class TestMatrixDebatePostValidation:
    """Tests for POST request validation."""

    @pytest.mark.asyncio
    async def test_returns_404_for_wrong_path(self, matrix_handler, mock_http_handler):
        """Returns 404 for non-matrix POST paths."""
        result = await matrix_handler.handle_post(mock_http_handler, "/api/debates/other", {})
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_accepts_router_signature(self, matrix_handler, mock_http_handler):
        """Accepts (path, query_params, handler) signature from router."""
        payload = {
            "task": "Evaluate architecture tradeoffs for scale",
            "scenarios": [{"name": "baseline"}],
        }
        matrix_handler.read_json_body_validated = MagicMock(return_value=(payload, None))
        matrix_handler.get_auth_context = AsyncMock(return_value=MagicMock())
        matrix_handler.check_permission = MagicMock()
        matrix_handler._run_matrix_debate = AsyncMock(
            return_value=HandlerResult(
                status_code=200,
                content_type="application/json",
                body=b"{}",
            )
        )

        result = await matrix_handler.handle_post(
            "/api/v1/debates/matrix",
            {},
            mock_http_handler,
        )

        assert result.status_code == 200
        matrix_handler._run_matrix_debate.assert_awaited_once_with(
            mock_http_handler, payload, SCOPE
        )

    @pytest.mark.asyncio
    async def test_returns_400_without_task(self, matrix_handler, mock_http_handler):
        """Returns 400 when task is missing."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {"scenarios": [{"name": "test"}]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "task" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_non_string_task(self, matrix_handler, mock_http_handler):
        """Returns 400 when task is not a string."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {"task": 12345, "scenarios": [{"name": "test"}]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "string" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_short_task(self, matrix_handler, mock_http_handler):
        """Returns 400 when task is too short."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {"task": "Short", "scenarios": [{"name": "test"}]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "10 characters" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_long_task(self, matrix_handler, mock_http_handler):
        """Returns 400 when task is too long."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {"task": "A" * 5001, "scenarios": [{"name": "test"}]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "5000 characters" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_scenarios_and_agent_combinations(
        self, matrix_handler, mock_http_handler
    ):
        """Returns 400 when both matrix modes are requested together."""
        result = await matrix_handler._run_matrix_debate(
            mock_http_handler,
            scope=SCOPE,
            data={
                "task": "What is the best approach for this problem?",
                "scenarios": [{"name": "baseline"}],
                "agent_combinations": [
                    {
                        "name": "combo",
                        "agents": [
                            {"provider": "openai-api"},
                            {"provider": "anthropic-api"},
                        ],
                    }
                ],
            },
        )

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "either scenarios or agent_combinations" in data.get("error", "").lower()


# =============================================================================
# Scenario Validation Tests
# =============================================================================


class TestMatrixDebateScenarioValidation:
    """Tests for scenario validation."""

    @pytest.mark.asyncio
    async def test_returns_400_for_non_array_scenarios(self, matrix_handler, mock_http_handler):
        """Returns 400 when scenarios is not an array."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {"task": "What is the best approach for this problem?", "scenarios": "test"},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "array" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_empty_scenarios(self, matrix_handler, mock_http_handler):
        """Returns 400 when scenarios is empty."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {"task": "What is the best approach for this problem?", "scenarios": []},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "one scenario" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_too_many_scenarios(self, matrix_handler, mock_http_handler):
        """Returns 400 when more than 10 scenarios provided."""
        scenarios = [{"name": f"scenario{i}"} for i in range(11)]
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {"task": "What is the best approach for this problem?", "scenarios": scenarios},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "10 scenarios" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_non_dict_scenario(self, matrix_handler, mock_http_handler):
        """Returns 400 when scenario is not an object."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {
                "task": "What is the best approach for this problem?",
                "scenarios": ["invalid"],
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "scenarios[0]" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_long_scenario_name(self, matrix_handler, mock_http_handler):
        """Returns 400 when scenario name exceeds 100 chars."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {
                "task": "What is the best approach for this problem?",
                "scenarios": [{"name": "A" * 101}],
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "100 chars" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_non_dict_parameters(self, matrix_handler, mock_http_handler):
        """Returns 400 when scenario parameters is not an object."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {
                "task": "What is the best approach for this problem?",
                "scenarios": [{"name": "test", "parameters": "invalid"}],
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "parameters" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_non_array_constraints(self, matrix_handler, mock_http_handler):
        """Returns 400 when scenario constraints is not an array."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {
                "task": "What is the best approach for this problem?",
                "scenarios": [{"name": "test", "constraints": "invalid"}],
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "constraints" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_too_many_constraints(self, matrix_handler, mock_http_handler):
        """Returns 400 when scenario has more than 10 constraints."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {
                "task": "What is the best approach for this problem?",
                "scenarios": [{"name": "test", "constraints": [f"c{i}" for i in range(11)]}],
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "constraints" in data.get("error", "")


class TestMatrixDebateModelCombinationValidation:
    """Tests for model combination validation."""

    @pytest.mark.asyncio
    async def test_returns_400_for_non_array_model_combinations(
        self, matrix_handler, mock_http_handler
    ):
        """Returns 400 when model_combinations is not an array."""
        result = await matrix_handler._run_matrix_debate(
            mock_http_handler,
            scope=SCOPE,
            data={
                "task": "Compare the same debate across multiple model combinations",
                "model_combinations": "invalid",
            },
        )

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "model_combinations" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_when_agents_and_model_combinations_are_combined(
        self, matrix_handler, mock_http_handler
    ):
        """Returns 400 for ambiguous legacy/new execution settings."""
        result = await matrix_handler._run_matrix_debate(
            mock_http_handler,
            scope=SCOPE,
            data={
                "task": "Compare the same debate across multiple model combinations",
                "agents": ["anthropic-api", "openai-api"],
                "model_combinations": [
                    {"name": "combo-a", "agents": ["anthropic-api", "openai-api"]}
                ],
            },
        )

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "cannot be used together" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_when_scenarios_and_model_combinations_are_combined(
        self, matrix_handler, mock_http_handler
    ):
        """Returns 400 because cross-product execution is not supported here."""
        result = await matrix_handler._run_matrix_debate(
            mock_http_handler,
            scope=SCOPE,
            data={
                "task": "Compare the same debate across multiple model combinations",
                "scenarios": [{"name": "baseline"}],
                "model_combinations": [
                    {"name": "combo-a", "agents": ["anthropic-api", "openai-api"]}
                ],
            },
        )

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "cannot be combined" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_accepts_model_combinations_without_scenarios(
        self, matrix_handler, mock_http_handler
    ):
        """Model combinations should be a valid alternative to scenarios."""
        matrix_handler._run_matrix_debate_fallback = AsyncMock(
            return_value=HandlerResult(
                status_code=200,
                content_type="application/json",
                body=b"{}",
            )
        )

        result = await matrix_handler._run_matrix_debate(
            mock_http_handler,
            scope=SCOPE,
            data={
                "task": "Compare the same debate across multiple model combinations",
                "model_combinations": [
                    {"name": "combo-a", "agents": ["anthropic-api", "openai-api"]},
                    {"name": "combo-b", "agents": ["gemini", "grok"]},
                ],
                "select_best_result": True,
            },
        )

        assert result.status_code == 200
        matrix_handler._run_matrix_debate_fallback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_400_for_non_boolean_select_best_result(
        self, matrix_handler, mock_http_handler
    ):
        """Returns 400 when select_best_result is not a boolean."""
        result = await matrix_handler._run_matrix_debate(
            mock_http_handler,
            scope=SCOPE,
            data={
                "task": "Compare the same debate across multiple model combinations",
                "model_combinations": [
                    {"name": "combo-a", "agents": ["anthropic-api", "openai-api"]}
                ],
                "select_best_result": "yes",
            },
        )

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "select_best_result" in data.get("error", "")


# =============================================================================
# Agent Validation Tests
# =============================================================================


class TestMatrixDebateAgentValidation:
    """Tests for agent validation."""

    @pytest.mark.asyncio
    async def test_returns_400_for_non_array_agents(self, matrix_handler, mock_http_handler):
        """Returns 400 when agents is not an array."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {
                "task": "What is the best approach for this problem?",
                "scenarios": [{"name": "test"}],
                "agents": "claude",
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "array" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_too_many_agents(self, matrix_handler, mock_http_handler):
        """Returns 400 when more than 10 agents provided."""
        agents = [f"agent{i}" for i in range(11)]
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {
                "task": "What is the best approach for this problem?",
                "scenarios": [{"name": "test"}],
                "agents": agents,
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "10 agents" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_non_string_agent(self, matrix_handler, mock_http_handler):
        """Returns 400 when agent name is not a string."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {
                "task": "What is the best approach for this problem?",
                "scenarios": [{"name": "test"}],
                "agents": ["claude", 123],
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "agents[1]" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_long_agent_name(self, matrix_handler, mock_http_handler):
        """Returns 400 when agent name exceeds 50 chars."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {
                "task": "What is the best approach for this problem?",
                "scenarios": [{"name": "test"}],
                "agents": ["claude", "a" * 51],
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "50 chars" in data.get("error", "")


# =============================================================================
# Max Rounds Validation Tests
# =============================================================================


class TestMatrixDebateRoundsValidation:
    """Tests for max_rounds validation."""

    @pytest.mark.asyncio
    async def test_returns_400_for_invalid_max_rounds(self, matrix_handler, mock_http_handler):
        """Returns 400 when max_rounds is not a number."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {
                "task": "What is the best approach for this problem?",
                "scenarios": [{"name": "test"}],
                "max_rounds": "invalid",
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "max_rounds" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_zero_max_rounds(self, matrix_handler, mock_http_handler):
        """Returns 400 when max_rounds is less than 1."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {
                "task": "What is the best approach for this problem?",
                "scenarios": [{"name": "test"}],
                "max_rounds": 0,
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "at least 1" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_too_many_rounds(self, matrix_handler, mock_http_handler):
        """Returns 400 when max_rounds exceeds 10."""
        result = await matrix_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/matrix",
            {
                "task": "What is the best approach for this problem?",
                "scenarios": [{"name": "test"}],
                "max_rounds": 11,
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "at most 10" in data.get("error", "")


# =============================================================================
# GET Endpoint Tests
# =============================================================================


class TestMatrixDebateGetEndpoints:
    """Tests for GET endpoints."""

    @pytest.mark.asyncio
    async def test_get_returns_404_for_base_path(self, matrix_handler, mock_http_handler):
        """Returns 404 for GET on base matrix path."""
        result = await matrix_handler.handle_get(mock_http_handler, "/api/v1/debates/matrix", {})
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_debate_returns_503_without_storage(self, matrix_handler, mock_http_handler):
        """Returns 503 when storage is not configured."""
        mock_http_handler.storage = None
        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/test-123", {}
        )
        assert result.status_code == 503
        data = json.loads(result.body)
        assert "storage" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_get_debate_returns_404_when_not_found(self, matrix_handler, mock_http_handler):
        """Returns 404 when matrix debate doesn't exist."""
        mock_storage = AsyncMock()
        mock_storage.get_matrix_debate = AsyncMock(return_value=None)
        mock_http_handler.storage = mock_storage

        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/nonexistent", {}
        )
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_debate_returns_debate_data(self, matrix_handler, mock_http_handler):
        """Returns debate data when found."""
        debate_data = {"id": "test-123", "task": "Test task", "scenarios": [], "org_id": TEST_ORG}
        mock_storage = AsyncMock()
        mock_storage.get_matrix_debate = AsyncMock(return_value=debate_data)
        mock_http_handler.storage = mock_storage

        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/test-123", {}
        )
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["id"] == "test-123"

    @pytest.mark.asyncio
    async def test_get_scenarios_returns_503_without_storage(
        self, matrix_handler, mock_http_handler
    ):
        """Returns 503 when storage is not configured for scenarios."""
        mock_http_handler.storage = None
        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/test-123/scenarios", {}
        )
        assert result.status_code == 503

    @pytest.mark.asyncio
    async def test_get_scenarios_returns_scenario_data(self, matrix_handler, mock_http_handler):
        """Returns scenario data when found."""
        scenarios = [{"name": "scenario-1"}, {"name": "scenario-2"}]
        mock_storage = AsyncMock()
        mock_storage.get_matrix_scenarios = AsyncMock(return_value=scenarios)
        mock_storage.get_matrix_debate = AsyncMock(return_value={"org_id": TEST_ORG})
        mock_http_handler.storage = mock_storage

        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/test-123/scenarios", {}
        )
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["matrix_id"] == "test-123"
        assert len(data["scenarios"]) == 2

    @pytest.mark.asyncio
    async def test_get_conclusions_returns_503_without_storage(
        self, matrix_handler, mock_http_handler
    ):
        """Returns 503 when storage is not configured for conclusions."""
        mock_http_handler.storage = None
        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/test-123/conclusions", {}
        )
        assert result.status_code == 503

    @pytest.mark.asyncio
    async def test_get_conclusions_returns_conclusion_data(self, matrix_handler, mock_http_handler):
        """Returns conclusion data when found."""
        conclusions = {
            "universal": ["All scenarios agree"],
            "conditional": [{"condition": "When A", "conclusion": "Result B"}],
        }
        mock_storage = AsyncMock()
        mock_storage.get_matrix_conclusions = AsyncMock(return_value=conclusions)
        mock_storage.get_matrix_debate = AsyncMock(return_value={"org_id": TEST_ORG})
        mock_http_handler.storage = mock_storage

        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/test-123/conclusions", {}
        )
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["matrix_id"] == "test-123"
        assert len(data["universal_conclusions"]) == 1
        assert len(data["conditional_conclusions"]) == 1


# =============================================================================
# Rate Limiting Tests
# =============================================================================


class TestMatrixDebateRateLimiting:
    """Tests for rate limiting."""

    @pytest.mark.asyncio
    async def test_rate_limit_after_multiple_requests(self, matrix_handler):
        """Returns 429 after exceeding rate limit."""

        # Mock the internal methods to avoid import errors during rate limit testing
        async def mock_run(*args, **kwargs):
            return MagicMock(
                status_code=200,
                body=json.dumps({"matrix_id": "test"}).encode(),
            )

        with patch.object(matrix_handler, "_run_matrix_debate", side_effect=mock_run):
            # Make requests until rate limited
            for i in range(6):  # 5 allowed, 6th should fail
                mock_handler = MagicMock()
                mock_handler.client_address = ("192.168.1.200", 12345)
                mock_handler.headers = {}

                result = await matrix_handler.handle_post(
                    mock_handler,
                    "/api/v1/debates/matrix",
                    {
                        "task": f"What is the best approach for this problem? Request {i}",
                        "scenarios": [{"name": "test"}],
                    },
                )

                if i >= 5:  # After 5 requests, should be rate limited
                    assert result.status_code == 429
                    data = json.loads(result.body)
                    assert "rate limit" in data.get("error", "").lower()


# =============================================================================
# Helper Method Tests
# =============================================================================


class TestMatrixHelperMethods:
    """Tests for helper methods."""

    def test_find_universal_conclusions_empty(self, matrix_handler):
        """Returns empty for empty results."""
        result = matrix_handler._find_universal_conclusions([])
        assert result == []

    def test_find_universal_conclusions_all_consensus(self, matrix_handler):
        """Returns universal conclusion when all reach consensus."""
        results = [
            {"consensus_reached": True, "final_answer": "A"},
            {"consensus_reached": True, "final_answer": "B"},
        ]
        result = matrix_handler._find_universal_conclusions(results)
        assert "All scenarios reached consensus" in result

    def test_find_universal_conclusions_mixed(self, matrix_handler):
        """Returns empty when not all reach consensus."""
        results = [
            {"consensus_reached": True, "final_answer": "A"},
            {"consensus_reached": False, "final_answer": "B"},
        ]
        result = matrix_handler._find_universal_conclusions(results)
        assert result == []

    def test_find_conditional_conclusions(self, matrix_handler):
        """Extracts conditional conclusions from results."""
        results = [
            {
                "scenario_name": "Scenario A",
                "parameters": {"x": 1},
                "final_answer": "Result A",
                "confidence": 0.8,
            },
            {
                "scenario_name": "Scenario B",
                "parameters": {"x": 2},
                "final_answer": "Result B",
                "confidence": 0.9,
            },
        ]
        result = matrix_handler._find_conditional_conclusions(results)
        assert len(result) == 2
        assert result[0]["condition"] == "When Scenario A"
        assert result[0]["conclusion"] == "Result A"
        assert result[1]["confidence"] == 0.9

    def test_build_comparison_matrix_empty(self, matrix_handler):
        """Builds comparison matrix for empty results."""
        result = matrix_handler._build_comparison_matrix([])
        assert result["scenarios"] == []
        assert result["consensus_rate"] == 0
        assert result["avg_confidence"] == 0
        assert result["avg_rounds"] == 0

    def test_build_comparison_matrix(self, matrix_handler):
        """Builds comparison matrix with valid data."""
        results = [
            {
                "scenario_name": "A",
                "consensus_reached": True,
                "confidence": 0.8,
                "rounds_used": 3,
            },
            {
                "scenario_name": "B",
                "consensus_reached": False,
                "confidence": 0.6,
                "rounds_used": 5,
            },
        ]
        result = matrix_handler._build_comparison_matrix(results)
        assert result["scenarios"] == ["A", "B"]
        assert result["consensus_rate"] == 0.5
        assert result["avg_confidence"] == 0.7
        assert result["avg_rounds"] == 4


class TestMatrixAgentCombinationMode:
    """Tests for explicit agent/model combination comparisons."""

    @pytest.mark.asyncio
    async def test_agent_combinations_pick_best_result(self, matrix_handler, mock_http_handler):
        """Returns the highest-scoring combination and annotates the winner."""

        async def fake_load_agents(agent_specs, min_agents=2):
            specs = agent_specs if isinstance(agent_specs, list) else []
            first_spec = specs[0] if specs else {}
            model = (
                getattr(first_spec, "model", None)
                if not isinstance(first_spec, dict)
                else first_spec.get("model")
            )
            if model == "best-model":
                return ["best-agent", "best-agent"]
            return ["baseline-agent", "baseline-agent"]

        class FakeArena:
            def __init__(self, env, agents, protocol, **kwargs):
                self.agents = agents

            async def run(self):
                if self.agents[0] == "best-agent":
                    return SimpleNamespace(
                        winner="best-agent",
                        final_answer="Choose the best-model path",
                        confidence=0.92,
                        consensus_reached=True,
                        rounds_used=2,
                    )
                return SimpleNamespace(
                    winner="baseline-agent",
                    final_answer="Choose the baseline path",
                    confidence=0.51,
                    consensus_reached=False,
                    rounds_used=4,
                )

        payload = {
            "task": "Compare the same debate question across model combinations",
            "agent_combinations": [
                {
                    "name": "Baseline",
                    "agents": [
                        {"provider": "openai-api", "model": "baseline-model"},
                        {"provider": "anthropic-api", "model": "baseline-model"},
                    ],
                },
                {
                    "name": "High confidence",
                    "agents": [
                        {"provider": "openai-api", "model": "best-model"},
                        {"provider": "anthropic-api", "model": "best-model"},
                    ],
                },
            ],
            "max_rounds": 5,
        }

        with patch.object(
            matrix_handler,
            "_load_agents_from_specs",
            side_effect=fake_load_agents,
        ):
            with patch("aragora.debate.orchestrator.Arena", FakeArena):
                result = await matrix_handler._run_matrix_debate_fallback(
                    mock_http_handler, payload, SCOPE
                )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["combination_count"] == 2
        assert data["best_result"]["scenario_name"] == "High confidence"
        assert data["best_result"]["selection_strategy"] == "consensus_confidence_completion"
        assert data["comparison_matrix"]["best_result_name"] == "High confidence"

        best_entry = next(
            item for item in data["results"] if item["scenario_name"] == "High confidence"
        )
        assert best_entry["is_best"] is True
        assert best_entry["selection_score"] > 0

    @pytest.mark.asyncio
    async def test_model_combinations_alias_pick_best_result(
        self, matrix_handler, mock_http_handler
    ):
        """Accepts model_combinations as an alias for agent_combinations."""

        async def fake_load_agents(agent_specs, min_agents=2):
            specs = agent_specs if isinstance(agent_specs, list) else []
            first_spec = specs[0] if specs else {}
            model = (
                getattr(first_spec, "model", None)
                if not isinstance(first_spec, dict)
                else first_spec.get("model")
            )
            if model == "best-model":
                return ["best-agent", "best-agent"]
            return ["baseline-agent", "baseline-agent"]

        class FakeArena:
            def __init__(self, env, agents, protocol, **kwargs):
                self.agents = agents

            async def run(self):
                if self.agents[0] == "best-agent":
                    return SimpleNamespace(
                        winner="best-agent",
                        final_answer="Choose the best-model path",
                        confidence=0.92,
                        consensus_reached=True,
                        rounds_used=2,
                    )
                return SimpleNamespace(
                    winner="baseline-agent",
                    final_answer="Choose the baseline path",
                    confidence=0.51,
                    consensus_reached=False,
                    rounds_used=4,
                )

        payload = {
            "task": "Compare the same debate question across model combinations",
            "model_combinations": [
                {
                    "name": "Baseline",
                    "agents": [
                        {"provider": "openai-api", "model": "baseline-model"},
                        {"provider": "anthropic-api", "model": "baseline-model"},
                    ],
                },
                {
                    "name": "High confidence",
                    "agents": [
                        {"provider": "openai-api", "model": "best-model"},
                        {"provider": "anthropic-api", "model": "best-model"},
                    ],
                },
            ],
            "max_rounds": 5,
        }

        with patch.object(
            matrix_handler,
            "_load_agents_from_specs",
            side_effect=fake_load_agents,
        ):
            with patch("aragora.debate.orchestrator.Arena", FakeArena):
                result = await matrix_handler._run_matrix_debate(mock_http_handler, payload, SCOPE)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["combination_count"] == 2
        assert data["best_result"]["scenario_name"] == "High confidence"
        assert data["comparison_matrix"]["best_result_name"] == "High confidence"


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestMatrixDebateErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_no_valid_agents(self, matrix_handler, mock_http_handler):
        """Returns 400 when no valid agents are found."""
        # Test that when _load_agents returns empty, we get 400 error
        # We need to mock the scenario import to work and return agents as empty

        async def mock_run_matrix_debate(handler, data, scope):
            # Simulate the code path that checks for valid agents
            from aragora.server.handlers.debates.matrix_debates import error_response

            agents = await matrix_handler._load_agents(data.get("agents", []))
            if not agents:
                return error_response("No valid agents found", 400)
            return MagicMock(status_code=200)

        with patch.object(matrix_handler, "_load_agents", new_callable=AsyncMock, return_value=[]):
            with patch.object(
                matrix_handler, "_run_matrix_debate", side_effect=mock_run_matrix_debate
            ):
                result = await matrix_handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/matrix",
                    {
                        "task": "What is the best approach for this problem?",
                        "scenarios": [{"name": "test"}],
                        "agents": ["invalid_agent_1", "invalid_agent_2"],
                    },
                )
                assert result.status_code == 400
                data = json.loads(result.body)
                assert "no valid agents" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_get_debate_handles_storage_error(self, matrix_handler, mock_http_handler):
        """Returns 500 on storage error when getting debate."""
        mock_storage = AsyncMock()
        mock_storage.get_matrix_debate = AsyncMock(side_effect=RuntimeError("Database error"))
        mock_http_handler.storage = mock_storage

        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/test-123", {}
        )
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_get_scenarios_handles_storage_error(self, matrix_handler, mock_http_handler):
        """Returns 500 on storage error when getting scenarios."""
        mock_storage = AsyncMock()
        mock_storage.get_matrix_scenarios = AsyncMock(side_effect=RuntimeError("Database error"))
        mock_storage.get_matrix_debate = AsyncMock(return_value={"org_id": TEST_ORG})
        mock_http_handler.storage = mock_storage

        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/test-123/scenarios", {}
        )
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_get_conclusions_handles_storage_error(self, matrix_handler, mock_http_handler):
        """Returns 500 on storage error when getting conclusions."""
        mock_storage = AsyncMock()
        mock_storage.get_matrix_conclusions = AsyncMock(side_effect=RuntimeError("Database error"))
        mock_storage.get_matrix_debate = AsyncMock(return_value={"org_id": TEST_ORG})
        mock_http_handler.storage = mock_storage

        result = await matrix_handler.handle_get(
            mock_http_handler, "/api/v1/debates/matrix/test-123/conclusions", {}
        )
        assert result.status_code == 500
