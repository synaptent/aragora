"""Tests for Graph Debates handler."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import aragora.server.handlers.debates.graph_debates as _graph_module

from aragora.server.handlers.debates.graph_debates import (
    GraphDebatesHandler,
    _graph_limiter,
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
    """Create a GraphDebatesHandler instance."""
    return GraphDebatesHandler({})


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
    """Reset rate limiter and bypass it by default.

    Most tests validate handler logic (auth, validation, etc.) and should not
    be affected by rate-limit state accumulated under parallel xdist execution.
    Tests that specifically exercise rate limiting re-enable it explicitly.

    Uses string-based patch target to avoid importlib mode class identity issues
    where the test's imported _graph_limiter is a different object from the one
    the handler actually uses.
    """
    _graph_module._graph_limiter._buckets.clear()
    with patch(
        "aragora.server.handlers.debates.graph_debates._graph_limiter.is_allowed",
        return_value=True,
    ):
        yield


# =============================================================================
# Test can_handle
# =============================================================================


class TestCanHandle:
    """Tests for can_handle method."""

    def test_can_handle_graph_root(self, handler):
        """Should handle graph debate root path."""
        assert handler.can_handle("/api/v1/debates/graph") is True

    def test_can_handle_graph_with_id(self, handler):
        """Should handle graph debate with ID."""
        assert handler.can_handle("/api/v1/debates/graph/abc-123") is True

    def test_can_handle_branches(self, handler):
        """Should handle branches path."""
        assert handler.can_handle("/api/v1/debates/graph/abc-123/branches") is True

    def test_can_handle_nodes(self, handler):
        """Should handle nodes path."""
        assert handler.can_handle("/api/v1/debates/graph/abc-123/nodes") is True

    def test_cannot_handle_other_paths(self, handler):
        """Should not handle non-graph paths."""
        assert handler.can_handle("/api/v1/debates/123") is False
        assert handler.can_handle("/api/v1/debates/matrix") is False


# =============================================================================
# Test GET Endpoints
# =============================================================================


class TestHandleGet:
    """Tests for GET request handling."""

    @pytest.mark.asyncio
    async def test_get_requires_authentication(self, handler, mock_http_handler):
        """Should return 401 when not authenticated."""
        with patch.object(handler, "get_auth_context", side_effect=UnauthorizedError()):
            # Use a valid path that needs auth
            result = await handler.handle_get(
                mock_http_handler, "/api/v1/debates/graph/abc-123", {}
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
                    mock_http_handler, "/api/v1/debates/graph/abc-123", {}
                )
                body, status = parse_result(result)

        assert status == 403

    @pytest.mark.asyncio
    async def test_get_debate_calls_storage(self, handler, mock_http_handler, mock_auth_context):
        """Should call storage to get debate."""
        mock_http_handler.storage.get_graph_debate = AsyncMock(
            return_value={"id": "abc-123", "task": "Test task", "org_id": "test-org-001"}
        )

        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_get(
                    mock_http_handler, "/api/v1/debates/graph/abc-123", {}
                )
                body, status = parse_result(result)

        assert status == 200
        assert body["id"] == "abc-123"
        mock_http_handler.storage.get_graph_debate.assert_called_once_with("abc-123")

    @pytest.mark.asyncio
    async def test_get_debate_not_found(self, handler, mock_http_handler, mock_auth_context):
        """Should return 404 when debate not found."""
        mock_http_handler.storage.get_graph_debate = AsyncMock(return_value=None)

        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_get(
                    mock_http_handler, "/api/v1/debates/graph/nonexistent", {}
                )
                body, status = parse_result(result)

        assert status == 404

    @pytest.mark.asyncio
    async def test_get_branches(self, handler, mock_http_handler, mock_auth_context):
        """Should get branches for a debate."""
        mock_http_handler.storage.get_graph_debate = AsyncMock(
            return_value={"org_id": "test-org-001"}
        )
        mock_http_handler.storage.get_debate_branches = AsyncMock(
            return_value=[{"id": "branch-1"}, {"id": "branch-2"}]
        )

        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_get(
                    mock_http_handler, "/api/v1/debates/graph/abc-123/branches", {}
                )
                body, status = parse_result(result)

        assert status == 200
        assert body["debate_id"] == "abc-123"
        assert len(body["branches"]) == 2

    @pytest.mark.asyncio
    async def test_get_nodes(self, handler, mock_http_handler, mock_auth_context):
        """Should get nodes for a debate."""
        mock_http_handler.storage.get_graph_debate = AsyncMock(
            return_value={"org_id": "test-org-001"}
        )
        mock_http_handler.storage.get_debate_nodes = AsyncMock(
            return_value=[{"id": "node-1"}, {"id": "node-2"}]
        )

        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_get(
                    mock_http_handler, "/api/v1/debates/graph/abc-123/nodes", {}
                )
                body, status = parse_result(result)

        assert status == 200
        assert body["debate_id"] == "abc-123"
        assert len(body["nodes"]) == 2


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
                "/api/v1/debates/graph",
                {"task": "Test task", "agents": ["claude", "gpt4"]},
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
                    "/api/v1/debates/graph/wrong",
                    {"task": "Test task", "agents": ["claude", "gpt4"]},
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
                    "/api/v1/debates/graph",
                    {"agents": ["claude", "gpt4"]},
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
                    "/api/v1/debates/graph",
                    {"task": "Short", "agents": ["claude", "gpt4"]},
                )
                body, status = parse_result(result)

        assert status == 400
        assert "at least 10 characters" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_task_too_long(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 when task is too long."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/graph",
                    {"task": "x" * 6000, "agents": ["claude", "gpt4"]},
                )
                body, status = parse_result(result)

        assert status == 400
        assert "at most 5000 characters" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_task_injection_attempt(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 for injection attempts in task."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/graph",
                    {"task": "<script>alert('xss')</script>", "agents": ["claude", "gpt4"]},
                )
                body, status = parse_result(result)

        assert status == 400
        assert "invalid characters" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_too_few_agents(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 when fewer than 2 agents."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/graph",
                    {"task": "A valid test task for debate", "agents": ["claude"]},
                )
                body, status = parse_result(result)

        assert status == 400
        assert "At least 2 agents" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_too_many_agents(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 when more than 10 agents."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                agents = [f"agent-{i}" for i in range(15)]
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/graph",
                    {"task": "A valid test task for debate", "agents": agents},
                )
                body, status = parse_result(result)

        assert status == 400
        assert "Maximum 10 agents" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_invalid_agent_name(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 for invalid agent names."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/graph",
                    {
                        "task": "A valid test task for debate",
                        "agents": ["claude", "invalid agent!@#"],
                    },
                )
                body, status = parse_result(result)

        assert status == 400
        assert "invalid agent name" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_invalid_max_rounds(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 for invalid max_rounds."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/graph",
                    {
                        "task": "A valid test task for debate",
                        "agents": ["claude", "gpt4"],
                        "max_rounds": 100,
                    },
                )
                body, status = parse_result(result)

        assert status == 400
        assert "max_rounds must be at most 20" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_post_invalid_branch_policy(self, handler, mock_http_handler, mock_auth_context):
        """Should return 400 for invalid branch_policy."""
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/graph",
                    {
                        "task": "A valid test task for debate",
                        "agents": ["claude", "gpt4"],
                        "branch_policy": {"min_disagreement": 2.0},
                    },
                )
                body, status = parse_result(result)

        assert status == 400
        assert "min_disagreement must be 0-1" in body.get("error", "")


# =============================================================================
# Test Rate Limiting
# =============================================================================


@pytest.mark.rate_limit_test
class TestRateLimiting:
    """Tests for rate limiting."""

    @pytest.fixture(autouse=True)
    def reset_rate_limiter(self):
        """Re-enable real rate limiter for rate limit tests.

        Accesses _graph_limiter through the module reference to ensure we get
        the same object the handler uses (avoids importlib identity issues).
        """
        limiter = _graph_module._graph_limiter
        limiter._buckets.clear()
        yield

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, handler, mock_http_handler, mock_auth_context):
        """Should return 429 when rate limit exceeded."""
        limiter = _graph_module._graph_limiter
        # Make requests until rate limit is hit
        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                # Pre-fill rate limiter bucket to exceed limit
                limiter._buckets["127.0.0.1"] = [time.time()] * limiter.rpm

                result = await handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/graph",
                    {
                        "task": "A valid test task for debate",
                        "agents": ["claude", "gpt4"],
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
        """Should return 404 when storage is unavailable and nothing is cached."""
        mock_http_handler.storage = None

        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_get(
                    mock_http_handler, "/api/v1/debates/graph/abc-123", {}
                )
                body, status = parse_result(result)

        assert status == 404
        assert "Graph debate not found" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_storage_exception(self, handler, mock_http_handler, mock_auth_context):
        """Should fall back to cache and return 404 when storage lookup fails."""
        mock_http_handler.storage.get_graph_debate = AsyncMock(
            side_effect=ValueError("Database error")
        )

        with patch.object(handler, "get_auth_context", new_callable=AsyncMock) as mock_auth:
            mock_auth.return_value = mock_auth_context
            with patch.object(handler, "check_permission"):
                result = await handler.handle_get(
                    mock_http_handler, "/api/v1/debates/graph/abc-123", {}
                )
                body, status = parse_result(result)

        assert status == 404
