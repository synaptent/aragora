"""
Tests for MatrixDebatesHandler - parallel scenario debate endpoints.

Tests cover:
- POST /api/debates/matrix - Run matrix debate
- GET /api/debates/matrix/{id} - Get debate by ID
- GET /api/debates/matrix/{id}/scenarios - Get scenarios
- GET /api/debates/matrix/{id}/conclusions - Get conclusions
"""

import json
import pytest
from unittest.mock import Mock, AsyncMock, patch

from aragora.rbac.models import AuthorizationContext
from aragora.server.handlers.debates import MatrixDebatesHandler


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def _mock_auth():
    """Provide admin auth context for all handler tests."""
    ctx = AuthorizationContext(
        user_id="test-user",
        roles={"admin"},
        permissions={"debates:read", "debates:create", "debates:delete"},
    )
    return AsyncMock(return_value=ctx)


@pytest.fixture
def handler(_mock_auth):
    """Create MatrixDebatesHandler instance with auth bypass."""
    h = MatrixDebatesHandler({})
    h.get_auth_context = _mock_auth
    h.check_permission = Mock()
    return h


@pytest.fixture
def mock_storage():
    """Create mock storage with async methods."""
    storage = Mock()
    storage.get_matrix_debate = AsyncMock(
        return_value={
            "matrix_id": "matrix-123",
            "task": "Test task",
            "scenario_count": 2,
            "results": [],
            "org_id": "test-org-001",
        }
    )
    storage.get_matrix_scenarios = AsyncMock(
        return_value=[
            {"scenario_name": "Baseline", "is_baseline": True},
            {"scenario_name": "Alternative", "is_baseline": False},
        ]
    )
    storage.get_matrix_conclusions = AsyncMock(
        return_value={
            "universal": ["All scenarios agree on X"],
            "conditional": [{"condition": "When Y", "conclusion": "Z"}],
        }
    )
    return storage


@pytest.fixture
def mock_handler_obj(mock_storage):
    """Create mock HTTP handler object."""
    handler = Mock()
    handler.storage = mock_storage
    handler.event_emitter = None
    return handler


# ============================================================================
# Route Recognition Tests
# ============================================================================


class TestMatrixDebatesRouting:
    """Tests for matrix debates route recognition."""

    def test_routes_defined(self, handler):
        """Test handler has routes defined."""
        assert "/api/v1/debates/matrix" in handler.ROUTES

    def test_auth_required_endpoints(self, handler):
        """Test auth required endpoints defined."""
        assert "/api/v1/debates/matrix" in handler.AUTH_REQUIRED_ENDPOINTS


# ============================================================================
# GET /api/debates/matrix/{id} Tests
# ============================================================================


class TestGetMatrixDebate:
    """Tests for getting specific matrix debate."""

    @pytest.mark.asyncio
    async def test_get_debate_success(self, handler, mock_handler_obj):
        """Test successful debate retrieval."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/matrix/matrix-123",
            {},
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["matrix_id"] == "matrix-123"

    @pytest.mark.asyncio
    async def test_get_debate_not_found(self, handler, mock_handler_obj, mock_storage):
        """Test 404 for non-existent debate."""
        mock_storage.get_matrix_debate.return_value = None

        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/matrix/nonexistent",
            {},
        )

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_debate_no_storage(self, handler):
        """Test 503 when storage not configured."""
        mock_handler = Mock()
        mock_handler.storage = None

        result = await handler.handle_get(
            mock_handler,
            "/api/debates/matrix/matrix-123",
            {},
        )

        assert result.status_code == 503


# ============================================================================
# GET /api/debates/matrix/{id}/scenarios Tests
# ============================================================================


class TestGetScenarios:
    """Tests for getting debate scenarios."""

    @pytest.mark.asyncio
    async def test_get_scenarios_success(self, handler, mock_handler_obj):
        """Test successful scenarios retrieval."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/matrix/matrix-123/scenarios",
            {},
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert "scenarios" in data
        assert len(data["scenarios"]) == 2

    @pytest.mark.asyncio
    async def test_get_scenarios_includes_matrix_id(self, handler, mock_handler_obj):
        """Test scenarios response includes matrix ID."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/matrix/matrix-123/scenarios",
            {},
        )

        data = json.loads(result.body)
        assert data["matrix_id"] == "matrix-123"


# ============================================================================
# GET /api/debates/matrix/{id}/conclusions Tests
# ============================================================================


class TestGetConclusions:
    """Tests for getting debate conclusions."""

    @pytest.mark.asyncio
    async def test_get_conclusions_success(self, handler, mock_handler_obj):
        """Test successful conclusions retrieval."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/matrix/matrix-123/conclusions",
            {},
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert "universal_conclusions" in data
        assert "conditional_conclusions" in data

    @pytest.mark.asyncio
    async def test_get_conclusions_includes_matrix_id(self, handler, mock_handler_obj):
        """Test conclusions response includes matrix ID."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/matrix/matrix-123/conclusions",
            {},
        )

        data = json.loads(result.body)
        assert data["matrix_id"] == "matrix-123"


# ============================================================================
# POST /api/debates/matrix Tests
# ============================================================================


class TestRunMatrixDebate:
    """Tests for running matrix debates."""

    @pytest.mark.asyncio
    async def test_run_debate_missing_task(self, handler, mock_handler_obj):
        """Test 400 when task is missing."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/matrix",
            {},
        )

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "task" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_run_debate_missing_scenarios(self, handler, mock_handler_obj):
        """Test 400 when scenarios are missing."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/matrix",
            {"task": "Test task that is long enough to pass validation"},
        )

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "scenario" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_run_debate_wrong_path(self, handler, mock_handler_obj):
        """Test 404 for wrong path."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/matrix/something",
            {"task": "Test", "scenarios": [{"name": "S1"}]},
        )

        assert result.status_code == 404


# ============================================================================
# Helper Method Tests
# ============================================================================


class TestMatrixDebateHelpers:
    """Tests for helper methods."""

    def test_find_universal_conclusions_all_consensus(self, handler):
        """Test finding universal conclusions when all reach consensus."""
        results = [
            {"scenario_name": "A", "consensus_reached": True},
            {"scenario_name": "B", "consensus_reached": True},
        ]
        conclusions = handler._find_universal_conclusions(results)
        assert len(conclusions) > 0

    def test_find_universal_conclusions_mixed(self, handler):
        """Test finding universal conclusions with mixed results."""
        results = [
            {"scenario_name": "A", "consensus_reached": True},
            {"scenario_name": "B", "consensus_reached": False},
        ]
        conclusions = handler._find_universal_conclusions(results)
        assert conclusions == []

    def test_find_conditional_conclusions(self, handler):
        """Test finding conditional conclusions."""
        results = [
            {"scenario_name": "A", "final_answer": "Answer A", "confidence": 0.8},
            {"scenario_name": "B", "final_answer": "Answer B", "confidence": 0.9},
        ]
        conclusions = handler._find_conditional_conclusions(results)
        assert len(conclusions) == 2

    def test_build_comparison_matrix(self, handler):
        """Test building comparison matrix."""
        results = [
            {"scenario_name": "A", "consensus_reached": True, "confidence": 0.8, "rounds_used": 3},
            {"scenario_name": "B", "consensus_reached": False, "confidence": 0.6, "rounds_used": 5},
        ]
        matrix = handler._build_comparison_matrix(results)
        assert "scenarios" in matrix
        assert matrix["consensus_rate"] == 0.5
        assert matrix["avg_confidence"] == 0.7
        assert matrix["avg_rounds"] == 4.0


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestMatrixDebatesErrorHandling:
    """Tests for error handling in matrix debates handler."""

    @pytest.mark.asyncio
    async def test_storage_exception_handled(self, handler, mock_handler_obj, mock_storage):
        """Test storage exceptions are handled gracefully."""
        mock_storage.get_matrix_debate.side_effect = Exception("DB error")

        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/matrix/matrix-123",
            {},
        )

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_scenarios_exception_handled(self, handler, mock_handler_obj, mock_storage):
        """Test scenarios retrieval error handling."""
        mock_storage.get_matrix_scenarios.side_effect = Exception("Connection lost")

        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/matrix/matrix-123/scenarios",
            {},
        )

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_conclusions_exception_handled(self, handler, mock_handler_obj, mock_storage):
        """Test conclusions retrieval error handling."""
        mock_storage.get_matrix_conclusions.side_effect = Exception("Timeout")

        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/matrix/matrix-123/conclusions",
            {},
        )

        assert result.status_code == 500
