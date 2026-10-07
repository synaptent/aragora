"""Tests for Matrix Debates handler."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import aragora.server.handlers.debates.matrix_debates as _matrix_module

from aragora.server.handlers.debates.matrix_debates import (
    MatrixDebatesHandler,
    _matrix_limiter,
)
from aragora.server.handlers.secure import ForbiddenError, UnauthorizedError


def parse_result(result):
    """Parse HandlerResult into (body_dict, status_code) for easier testing."""
    body = json.loads(result.body) if result.body else {}
    return body, result.status_code


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def handler():
    """Create a MatrixDebatesHandler instance."""
    return MatrixDebatesHandler({})


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler."""
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 12345)
    handler.storage = MagicMock()
    handler.event_emitter = None
    return handler


@pytest.fixture
def mock_auth_context():
    """Create a mock authentication context."""
    context = MagicMock()
    context.user_id = "test-user"
    context.roles = ["debates:read", "debates:create"]
    return context


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset and bypass rate limiter to prevent xdist cross-test interference."""
    _matrix_module._matrix_limiter._buckets.clear()
    with patch(
        "aragora.server.handlers.debates.matrix_debates._matrix_limiter.is_allowed",
        return_value=True,
    ):
        yield


# =============================================================================
# Test can_handle
# =============================================================================


class TestCanHandle:
    """Tests for can_handle method."""

    def test_can_handle_matrix_root(self, handler):
        """Should handle matrix debate root path."""
        assert handler.can_handle("/api/v1/debates/matrix") is True

    def test_can_handle_matrix_with_id(self, handler):
        """Should handle matrix debate with ID."""
        assert handler.can_handle("/api/v1/debates/matrix/abc-123") is True

    def test_can_handle_scenarios(self, handler):
        """Should handle scenarios path."""
        assert handler.can_handle("/api/v1/debates/matrix/abc-123/scenarios") is True

    def test_can_handle_conclusions(self, handler):
        """Should handle conclusions path."""
        assert handler.can_handle("/api/v1/debates/matrix/abc-123/conclusions") is True

    def test_cannot_handle_other_paths(self, handler):
        """Should not handle non-matrix paths."""
        assert handler.can_handle("/api/v1/debates/123") is False
        assert handler.can_handle("/api/v1/debates/graph") is False


# =============================================================================
# Test GET Endpoints
# =============================================================================


class TestHandleGet:
    """Tests for GET request handling."""

    @pytest.mark.asyncio
    async def test_get_requires_authentication(self, handler, mock_http_handler):
        """Should return 401 when not authenticated."""
        with patch.object(handler, "get_auth_context", side_effect=UnauthorizedError()):
            result = await handler.handle_get(
                mock_http_handler, "/api/v1/debates/matrix/abc-123", {}
            )
            body, status = parse_result(result)

        assert status == 401
        assert "Authentication required" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_get_requires_debates_read_permission(
        self, handler, mock_http_handler, mock_auth_context
    ):
        """Should return 403 when missing debates:read permission."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(
                handler,
                "check_permission",
                side_effect=ForbiddenError("Permission denied"),
            ):
                result = await handler.handle_get(
                    mock_http_handler, "/api/v1/debates/matrix/abc-123", {}
                )
                body, status = parse_result(result)

        assert status == 403

    @pytest.mark.asyncio
    async def test_get_matrix_calls_storage(self, handler, mock_http_handler, mock_auth_context):
        """Should call storage to get matrix debate."""
        mock_http_handler.storage.get_matrix_debate = AsyncMock(
            return_value={"id": "abc-123", "task": "Test task", "org_id": "test-org-001"}
        )

        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_get(
                    mock_http_handler, "/api/v1/debates/matrix/abc-123", {}
                )
                body, status = parse_result(result)

        assert status == 200
        assert body["id"] == "abc-123"
        mock_http_handler.storage.get_matrix_debate.assert_called_once_with("abc-123")

    @pytest.mark.asyncio
    async def test_get_matrix_not_found(self, handler, mock_http_handler, mock_auth_context):
        """Should return 404 when matrix debate not found."""
        mock_http_handler.storage.get_matrix_debate = AsyncMock(return_value=None)

        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_get(
                    mock_http_handler, "/api/v1/debates/matrix/nonexistent", {}
                )
                body, status = parse_result(result)

        assert status == 404

    @pytest.mark.asyncio
    async def test_get_scenarios(self, handler, mock_http_handler, mock_auth_context):
        """Should get scenarios for a matrix debate."""
        mock_http_handler.storage.get_matrix_debate = AsyncMock(
            return_value={"org_id": "test-org-001"}
        )
        mock_http_handler.storage.get_matrix_scenarios = AsyncMock(
            return_value=[{"name": "scenario-1"}, {"name": "scenario-2"}]
        )

        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_get(
                    mock_http_handler, "/api/v1/debates/matrix/abc-123/scenarios", {}
                )
                body, status = parse_result(result)

        assert status == 200
        assert body["matrix_id"] == "abc-123"
        assert len(body["scenarios"]) == 2

    @pytest.mark.asyncio
    async def test_get_conclusions(self, handler, mock_http_handler, mock_auth_context):
        """Should get conclusions for a matrix debate."""
        mock_http_handler.storage.get_matrix_debate = AsyncMock(
            return_value={"org_id": "test-org-001"}
        )
        mock_http_handler.storage.get_matrix_conclusions = AsyncMock(
            return_value={
                "universal": ["All scenarios agree"],
                "conditional": [{"condition": "When X", "conclusion": "Y"}],
            }
        )

        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_get(
                    mock_http_handler, "/api/v1/debates/matrix/abc-123/conclusions", {}
                )
                body, status = parse_result(result)

        assert status == 200
        assert body["matrix_id"] == "abc-123"
        assert len(body["universal_conclusions"]) == 1
        assert len(body["conditional_conclusions"]) == 1


# =============================================================================
# Test POST Validation
# =============================================================================


class TestHandlePost:
    """Tests for POST request handling."""

    @pytest.mark.asyncio
    async def test_post_requires_authentication(self, handler, mock_http_handler):
        """Should return 401 when not authenticated."""
        with patch.object(handler, "get_auth_context", side_effect=UnauthorizedError()):
            result = await handler.handle_post(
                mock_http_handler,
                "/api/v1/debates/matrix",
                {
                    "task": "Test task that is long enough",
                    "scenarios": [{"name": "test"}],
                },
            )
            body, status = parse_result(result)

        assert status == 401

    @pytest.mark.asyncio
    async def test_post_wrong_path(self, handler, mock_http_handler, mock_auth_context):
        """Should return 404 for wrong path."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/matrix/wrong",
                    {
                        "task": "Test task that is long enough",
                        "scenarios": [{"name": "test"}],
                    },
                )
                body, status = parse_result(result)

        assert status == 404

    @pytest.mark.asyncio
    async def test_post_missing_task(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 when task is missing."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/matrix",
                    {"scenarios": [{"name": "test"}]},
                )
                body, status = parse_result(result)

        assert status == 400
        assert "task is required" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_task_too_short(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 when task is too short."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/matrix",
                    {"task": "Short", "scenarios": [{"name": "test"}]},
                )
                body, status = parse_result(result)

        assert status == 400
        assert "at least 10 characters" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_missing_scenarios(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 when scenarios is empty."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/matrix",
                    {"task": "A valid test task for debate", "scenarios": []},
                )
                body, status = parse_result(result)

        assert status == 400
        assert "At least one scenario" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_too_many_scenarios(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 when too many scenarios."""
        scenarios = [{"name": f"scenario-{i}"} for i in range(15)]
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/matrix",
                    {"task": "A valid test task for debate", "scenarios": scenarios},
                )
                body, status = parse_result(result)

        assert status == 400
        assert "Maximum 10 scenarios" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_invalid_scenario_name(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 when scenario name too long."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/matrix",
                    {
                        "task": "A valid test task for debate",
                        "scenarios": [{"name": "x" * 150}],
                    },
                )
                body, status = parse_result(result)

        assert status == 400
        assert "too long" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_invalid_max_rounds(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 for invalid max_rounds."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/matrix",
                    {
                        "task": "A valid test task for debate",
                        "scenarios": [{"name": "test"}],
                        "max_rounds": 100,
                    },
                )
                body, status = parse_result(result)

        assert status == 400
        assert "max_rounds must be at most 10" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_too_many_agents(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 when too many agents."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                agents = [f"agent-{i}" for i in range(15)]
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/matrix",
                    {
                        "task": "A valid test task for debate",
                        "scenarios": [{"name": "test"}],
                        "agents": agents,
                    },
                )
                body, status = parse_result(result)

        assert status == 400
        assert "Maximum 10 agents" in body.get("error", "")


# =============================================================================
# Test Rate Limiting
# =============================================================================


@pytest.mark.rate_limit_test
class TestRateLimiting:
    """Tests for rate limiting."""

    @pytest.fixture(autouse=True)
    def reset_rate_limiter(self):
        """Re-enable real rate limiter for rate limit tests.

        Uses a fresh import of the module to get the LIVE limiter object,
        not the one captured at test-file import time.  If rate_limit.py
        was reloaded by another test, the RateLimiter class and its
        RATE_LIMITING_DISABLED global may have been re-created.
        """
        import sys

        live_mod = sys.modules.get("aragora.server.handlers.debates.matrix_debates", _matrix_module)
        limiter = live_mod._matrix_limiter
        limiter._buckets.clear()
        # Ensure rate limiting is NOT globally disabled.
        rl_mod = sys.modules.get("aragora.server.handlers.utils.rate_limit")
        if rl_mod:
            saved = getattr(rl_mod, "RATE_LIMITING_DISABLED", False)
            rl_mod.RATE_LIMITING_DISABLED = False
        yield
        if rl_mod:
            rl_mod.RATE_LIMITING_DISABLED = saved

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, handler, mock_http_handler, mock_auth_context):
        """Should return 429 when rate limit exceeded."""
        # Use the handler's actual module-level limiter to avoid identity
        # split when rate_limit.py has been reloaded by another test.
        import aragora.server.handlers.debates.matrix_debates as _live_mod

        live_limiter = _live_mod._matrix_limiter
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                # Pre-fill rate limiter bucket to exceed limit
                live_limiter._buckets["127.0.0.1"] = [time.time()] * live_limiter.rpm

                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/matrix",
                    {
                        "task": "A valid test task for debate",
                        "scenarios": [{"name": "test"}],
                    },
                )
                body, status = parse_result(result)

        assert status == 429
        assert "Rate limit exceeded" in body.get("error", "")


# =============================================================================
# Test Storage Errors
# =============================================================================


class TestStorageErrors:
    """Tests for storage error handling."""

    @pytest.mark.asyncio
    async def test_no_storage_configured(self, handler, mock_http_handler, mock_auth_context):
        """Should return 503 when storage not configured."""
        mock_http_handler.storage = None

        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_get(
                    mock_http_handler, "/api/v1/debates/matrix/abc-123", {}
                )
                body, status = parse_result(result)

        assert status == 503
        assert "Storage not configured" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_storage_exception(self, handler, mock_http_handler, mock_auth_context):
        """Should return 500 on storage exception."""
        mock_http_handler.storage.get_matrix_debate = AsyncMock(
            side_effect=ValueError("Database error")
        )

        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_get(
                    mock_http_handler, "/api/v1/debates/matrix/abc-123", {}
                )
                body, status = parse_result(result)

        assert status == 500


# =============================================================================
# Test Helper Methods
# =============================================================================


class TestHelperMethods:
    """Tests for helper methods."""

    def test_find_universal_conclusions_empty(self, handler):
        """Should return empty for no results."""
        assert handler._find_universal_conclusions([]) == []

    def test_find_universal_conclusions_all_consensus(self, handler):
        """Should return universal when all reach consensus."""
        results = [
            {"consensus_reached": True},
            {"consensus_reached": True},
            {"consensus_reached": True},
        ]
        conclusions = handler._find_universal_conclusions(results)
        assert "All scenarios reached consensus" in conclusions

    def test_find_universal_conclusions_mixed(self, handler):
        """Should return empty for mixed results."""
        results = [
            {"consensus_reached": True},
            {"consensus_reached": False},
        ]
        assert handler._find_universal_conclusions(results) == []

    def test_find_conditional_conclusions(self, handler):
        """Should extract conditional conclusions from results."""
        results = [
            {
                "scenario_name": "Optimistic",
                "parameters": {"growth": "high"},
                "final_answer": "Invest now",
                "confidence": 0.8,
            },
            {
                "scenario_name": "Pessimistic",
                "parameters": {"growth": "low"},
                "final_answer": "Wait and see",
                "confidence": 0.6,
            },
        ]
        conclusions = handler._find_conditional_conclusions(results)

        assert len(conclusions) == 2
        assert conclusions[0]["condition"] == "When Optimistic"
        assert conclusions[0]["conclusion"] == "Invest now"

    def test_build_comparison_matrix(self, handler):
        """Should build comparison matrix from results."""
        results = [
            {
                "scenario_name": "Scenario A",
                "consensus_reached": True,
                "confidence": 0.8,
                "rounds_used": 3,
            },
            {
                "scenario_name": "Scenario B",
                "consensus_reached": False,
                "confidence": 0.5,
                "rounds_used": 5,
            },
        ]
        matrix = handler._build_comparison_matrix(results)

        assert matrix["scenarios"] == ["Scenario A", "Scenario B"]
        assert matrix["consensus_rate"] == 0.5
        assert matrix["avg_confidence"] == 0.65
        assert matrix["avg_rounds"] == 4.0
