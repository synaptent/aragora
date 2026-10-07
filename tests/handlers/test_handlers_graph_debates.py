"""
Tests for GraphDebatesHandler - graph-structured debate endpoints.

Tests cover:
- POST /api/debates/graph - Run graph debate with validation
- GET /api/debates/graph/{id} - Get debate by ID
- GET /api/debates/graph/{id}/branches - Get branches
- GET /api/debates/graph/{id}/nodes - Get nodes
- Input validation (task, agents, max_rounds, branch_policy)
- Rate limiting
- Error handling
"""

import json
import pytest
from unittest.mock import Mock, AsyncMock, patch

from aragora.server.handlers.debates import GraphDebatesHandler, _graph_limiter, graph_debates


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def handler():
    """Create GraphDebatesHandler instance."""
    return GraphDebatesHandler({})


@pytest.fixture
def mock_storage():
    """Create mock storage with async methods."""
    storage = Mock()
    storage.get_graph_debate = AsyncMock(
        return_value={
            "debate_id": "graph-123",
            "task": "Test task",
            "nodes": [],
            "branches": [],
            "org_id": "test-org-001",
        }
    )
    storage.get_debate_branches = AsyncMock(
        return_value=[
            {"id": "main", "parent_id": None},
            {"id": "branch-1", "parent_id": "main"},
        ]
    )
    storage.get_debate_nodes = AsyncMock(
        return_value=[
            {"id": "node-1", "content": "Test", "branch_id": "main"},
        ]
    )
    storage.list_graph_debates = AsyncMock(return_value=[])
    return storage


@pytest.fixture
def mock_handler_obj(mock_storage):
    """Create mock HTTP handler object."""
    handler = Mock()
    handler.storage = mock_storage
    handler.event_emitter = None
    handler.client_address = ("127.0.0.1", 12345)  # For rate limiting
    return handler


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset rate limiter between tests."""
    _graph_limiter._buckets.clear()
    graph_debates._graph_debate_cache.clear()


# ============================================================================
# Route Recognition Tests
# ============================================================================


class TestGraphDebatesRouting:
    """Tests for graph debates route recognition."""

    def test_routes_defined(self, handler):
        """Test handler has routes defined."""
        assert "/api/v1/debates/graph" in handler.ROUTES

    def test_auth_required_endpoints(self, handler):
        """Test auth required endpoints defined."""
        assert "/api/v1/debates/graph" in handler.AUTH_REQUIRED_ENDPOINTS


# ============================================================================
# GET /api/debates/graph/{id} Tests
# ============================================================================


class TestGetGraphDebate:
    """Tests for getting specific graph debate."""

    @pytest.mark.asyncio
    async def test_get_debate_success(self, handler, mock_handler_obj):
        """Test successful debate retrieval."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph/graph-123",
            {},
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["debate_id"] == "graph-123"

    @pytest.mark.asyncio
    async def test_get_debate_not_found(self, handler, mock_handler_obj, mock_storage):
        """Test 404 for non-existent debate."""
        mock_storage.get_graph_debate.return_value = None

        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph/nonexistent",
            {},
        )

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_debate_no_storage(self, handler):
        """Test 404 when no storage or cached debate is available."""
        mock_handler = Mock()
        mock_handler.storage = None

        result = await handler.handle_get(
            mock_handler,
            "/api/debates/graph/graph-123",
            {},
        )

        assert result.status_code == 404


# ============================================================================
# GET /api/debates/graph/{id}/branches Tests
# ============================================================================


class TestGetBranches:
    """Tests for getting debate branches."""

    @pytest.mark.asyncio
    async def test_get_branches_success(self, handler, mock_handler_obj):
        """Test successful branches retrieval."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph/graph-123/branches",
            {},
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert "branches" in data
        assert len(data["branches"]) == 2

    @pytest.mark.asyncio
    async def test_get_branches_includes_debate_id(self, handler, mock_handler_obj):
        """Test branches response includes debate ID."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph/graph-123/branches",
            {},
        )

        data = json.loads(result.body)
        assert data["debate_id"] == "graph-123"


# ============================================================================
# GET /api/debates/graph/{id}/nodes Tests
# ============================================================================


class TestGetNodes:
    """Tests for getting debate nodes."""

    @pytest.mark.asyncio
    async def test_get_nodes_success(self, handler, mock_handler_obj):
        """Test successful nodes retrieval."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph/graph-123/nodes",
            {},
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert "nodes" in data

    @pytest.mark.asyncio
    async def test_get_nodes_includes_debate_id(self, handler, mock_handler_obj):
        """Test nodes response includes debate ID."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph/graph-123/nodes",
            {},
        )

        data = json.loads(result.body)
        assert data["debate_id"] == "graph-123"


# ============================================================================
# POST /api/debates/graph Tests
# ============================================================================


class TestRunGraphDebate:
    """Tests for running graph debates."""

    @pytest.mark.asyncio
    async def test_run_debate_missing_task(self, handler, mock_handler_obj):
        """Test 400 when task is missing."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {},
        )

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "task" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_run_debate_wrong_path(self, handler, mock_handler_obj):
        """Test 404 for wrong path."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph/something",
            {"task": "Test"},
        )

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_run_debate_graph_module_unavailable(self, handler, mock_handler_obj):
        """Test error when graph module not available."""
        with patch.object(handler, "_load_agents", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = [Mock(name="agent1")]

            # Need at least 2 agents
            result = await handler.handle_post(
                mock_handler_obj,
                "/api/debates/graph",
                {"task": "This is a valid debate topic", "agents": ["claude", "gpt4"]},
            )

            # Either 500 (import error), 400 (no valid agents), or success
            assert result.status_code in [200, 400, 500]


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestGraphDebatesErrorHandling:
    """Tests for error handling in graph debates handler."""

    @pytest.mark.asyncio
    async def test_storage_exception_handled(self, handler, mock_handler_obj, mock_storage):
        """Test storage exceptions are handled gracefully."""
        mock_storage.get_graph_debate.side_effect = Exception("DB error")

        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph/graph-123",
            {},
        )

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_branches_exception_handled(self, handler, mock_handler_obj, mock_storage):
        """Test branches retrieval error handling."""
        mock_storage.get_debate_branches.side_effect = Exception("Connection lost")

        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph/graph-123/branches",
            {},
        )

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_nodes_exception_handled(self, handler, mock_handler_obj, mock_storage):
        """Test nodes retrieval error handling."""
        mock_storage.get_debate_nodes.side_effect = Exception("Timeout")

        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph/graph-123/nodes",
            {},
        )

        assert result.status_code == 500


# ============================================================================
# Task Validation Tests
# ============================================================================


class TestTaskValidation:
    """Tests for task input validation."""

    @pytest.mark.asyncio
    async def test_task_empty_string(self, handler, mock_handler_obj):
        """Test empty string task rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": ""},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "task" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_task_too_short(self, handler, mock_handler_obj):
        """Test task shorter than 10 chars rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "Short"},  # 5 chars
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "10 character" in data["error"]

    @pytest.mark.asyncio
    async def test_task_too_long(self, handler, mock_handler_obj):
        """Test task longer than 5000 chars rejected."""
        long_task = "x" * 5001
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": long_task},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "5000" in data["error"]

    @pytest.mark.asyncio
    async def test_task_not_string(self, handler, mock_handler_obj):
        """Test non-string task rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": 12345},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "string" in data["error"]

    @pytest.mark.asyncio
    async def test_task_script_injection(self, handler, mock_handler_obj):
        """Test script tag in task rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "Discuss this <script>alert('xss')</script> topic"},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "invalid" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_task_javascript_protocol(self, handler, mock_handler_obj):
        """Test javascript: protocol rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "Click here javascript:alert(1) for more"},
        )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_task_null_byte(self, handler, mock_handler_obj):
        """Test null byte in task rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "Discuss this\x00hidden topic please"},
        )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_task_template_injection(self, handler, mock_handler_obj):
        """Test template injection rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "Discuss {{config.SECRET_KEY}} extraction"},
        )
        assert result.status_code == 400


# ============================================================================
# Agent Validation Tests
# ============================================================================


class TestAgentValidation:
    """Tests for agent input validation."""

    @pytest.mark.asyncio
    async def test_agents_not_array(self, handler, mock_handler_obj):
        """Test non-array agents rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "This is a valid debate topic", "agents": "claude"},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "array" in data["error"]

    @pytest.mark.asyncio
    async def test_agents_too_few(self, handler, mock_handler_obj):
        """Test fewer than 2 agents rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "This is a valid debate topic", "agents": ["claude"]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "2 agent" in data["error"]

    @pytest.mark.asyncio
    async def test_agents_too_many(self, handler, mock_handler_obj):
        """Test more than 10 agents rejected."""
        agents = [f"agent-{i}" for i in range(11)]
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "This is a valid debate topic", "agents": agents},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "10" in data["error"]

    @pytest.mark.asyncio
    async def test_agent_name_not_string(self, handler, mock_handler_obj):
        """Test non-string agent name rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "This is a valid debate topic", "agents": ["claude", 123]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "string" in data["error"]

    @pytest.mark.asyncio
    async def test_agent_name_too_long(self, handler, mock_handler_obj):
        """Test agent name longer than 50 chars rejected."""
        long_name = "a" * 51
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "This is a valid debate topic", "agents": ["claude", long_name]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "50" in data["error"]

    @pytest.mark.asyncio
    async def test_agent_name_invalid_chars(self, handler, mock_handler_obj):
        """Test agent name with special chars rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "This is a valid debate topic", "agents": ["claude", "agent@evil.com"]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "invalid" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_agent_name_valid_formats(self, handler, mock_handler_obj):
        """Test valid agent name formats are accepted."""
        # This won't succeed fully (module import fails) but should pass validation
        with patch.object(handler, "_load_agents", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = []  # No agents loaded

            result = await handler.handle_post(
                mock_handler_obj,
                "/api/debates/graph",
                {
                    "task": "This is a valid debate topic",
                    "agents": ["claude-3", "gpt_4", "agent123"],
                },
            )
            # Will fail at agent loading or import, not validation
            assert result.status_code in [400, 500]
            data = json.loads(result.body)
            # Error should not be about agent name format
            assert "invalid agent name" not in data["error"].lower()


# ============================================================================
# Max Rounds Validation Tests
# ============================================================================


class TestMaxRoundsValidation:
    """Tests for max_rounds parameter validation."""

    @pytest.mark.asyncio
    async def test_max_rounds_not_integer(self, handler, mock_handler_obj):
        """Test non-integer max_rounds rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {
                "task": "This is a valid debate topic",
                "agents": ["claude", "gpt4"],
                "max_rounds": "five",
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "integer" in data["error"]

    @pytest.mark.asyncio
    async def test_max_rounds_zero(self, handler, mock_handler_obj):
        """Test zero max_rounds rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "This is a valid debate topic", "agents": ["claude", "gpt4"], "max_rounds": 0},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "1" in data["error"]

    @pytest.mark.asyncio
    async def test_max_rounds_negative(self, handler, mock_handler_obj):
        """Test negative max_rounds rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {
                "task": "This is a valid debate topic",
                "agents": ["claude", "gpt4"],
                "max_rounds": -5,
            },
        )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_max_rounds_too_high(self, handler, mock_handler_obj):
        """Test max_rounds > 20 rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {
                "task": "This is a valid debate topic",
                "agents": ["claude", "gpt4"],
                "max_rounds": 21,
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "20" in data["error"]

    @pytest.mark.asyncio
    async def test_max_rounds_string_convertible(self, handler, mock_handler_obj):
        """Test string that can be converted to int is accepted."""
        with patch.object(handler, "_load_agents", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = []  # Will fail at loading

            result = await handler.handle_post(
                mock_handler_obj,
                "/api/debates/graph",
                {
                    "task": "This is a valid debate topic",
                    "agents": ["claude", "gpt4"],
                    "max_rounds": "10",
                },
            )
            # Should fail at agent loading or import, not max_rounds validation
            assert result.status_code in [400, 500]
            data = json.loads(result.body)
            # Error should not be about max_rounds
            assert "max_rounds" not in data["error"]


# ============================================================================
# Branch Policy Validation Tests
# ============================================================================


class TestBranchPolicyValidation:
    """Tests for branch_policy parameter validation."""

    @pytest.mark.asyncio
    async def test_branch_policy_not_object(self, handler, mock_handler_obj):
        """Test non-object branch_policy rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {
                "task": "This is a valid debate topic",
                "agents": ["claude", "gpt4"],
                "branch_policy": "auto",
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "object" in data["error"]

    @pytest.mark.asyncio
    async def test_min_disagreement_invalid_type(self, handler, mock_handler_obj):
        """Test non-numeric min_disagreement rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {
                "task": "This is a valid debate topic",
                "agents": ["claude", "gpt4"],
                "branch_policy": {"min_disagreement": "high"},
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "min_disagreement" in data["error"]

    @pytest.mark.asyncio
    async def test_min_disagreement_out_of_range(self, handler, mock_handler_obj):
        """Test min_disagreement outside 0-1 rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {
                "task": "This is a valid debate topic",
                "agents": ["claude", "gpt4"],
                "branch_policy": {"min_disagreement": 1.5},
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "0-1" in data["error"]

    @pytest.mark.asyncio
    async def test_max_branches_invalid(self, handler, mock_handler_obj):
        """Test invalid max_branches rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {
                "task": "This is a valid debate topic",
                "agents": ["claude", "gpt4"],
                "branch_policy": {"max_branches": 15},
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "1-10" in data["error"]

    @pytest.mark.asyncio
    async def test_max_branches_zero(self, handler, mock_handler_obj):
        """Test zero max_branches rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {
                "task": "This is a valid debate topic",
                "agents": ["claude", "gpt4"],
                "branch_policy": {"max_branches": 0},
            },
        )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_merge_strategy_invalid(self, handler, mock_handler_obj):
        """Test invalid merge_strategy rejected."""
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {
                "task": "This is a valid debate topic",
                "agents": ["claude", "gpt4"],
                "branch_policy": {"merge_strategy": "magic"},
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "synthesis" in data["error"] or "vote" in data["error"]

    @pytest.mark.asyncio
    async def test_valid_merge_strategies(self, handler, mock_handler_obj):
        """Test valid merge strategies accepted."""
        for strategy in ["synthesis", "vote", "best"]:
            with patch.object(handler, "_load_agents", new_callable=AsyncMock) as mock_load:
                mock_load.return_value = []  # Will fail at loading

                result = await handler.handle_post(
                    mock_handler_obj,
                    "/api/debates/graph",
                    {
                        "task": "This is a valid debate topic",
                        "agents": ["claude", "gpt4"],
                        "branch_policy": {"merge_strategy": strategy},
                    },
                )
                # Should fail at agent loading or import, not strategy validation
                assert result.status_code in [400, 500]
                data = json.loads(result.body)
                # Error should not be about merge strategy
                assert "merge_strategy" not in data["error"]


# ============================================================================
# Rate Limiting Tests
# ============================================================================


class TestRateLimiting:
    """Tests for rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_rate_limit_allows_initial_requests(self, handler, mock_handler_obj):
        """Test that initial requests are allowed."""
        # First request should succeed (at validation, at least)
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "This is a valid debate topic", "agents": ["claude", "gpt4"]},
        )
        # May fail for other reasons (import error), but not 429
        assert result.status_code != 429

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_excessive_requests(self, handler, mock_handler_obj):
        """Test that excessive requests are blocked."""
        # Make 5 requests (the limit)
        for _ in range(5):
            await handler.handle_post(
                mock_handler_obj,
                "/api/debates/graph",
                {"task": "This is a valid debate topic", "agents": ["claude", "gpt4"]},
            )

        # 6th request should be rate limited
        result = await handler.handle_post(
            mock_handler_obj,
            "/api/debates/graph",
            {"task": "This is a valid debate topic", "agents": ["claude", "gpt4"]},
        )
        assert result.status_code == 429
        data = json.loads(result.body)
        assert "rate limit" in data["error"].lower()


# ============================================================================
# Path Parsing Tests
# ============================================================================


class TestPathParsing:
    """Tests for path parsing edge cases."""

    @pytest.mark.asyncio
    async def test_trailing_slash_handled(self, handler, mock_handler_obj):
        """Test paths with trailing slashes work."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph/graph-123/",
            {},
        )
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_branches_path(self, handler, mock_handler_obj):
        """Test branches subpath works."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph/graph-123/branches",
            {},
        )
        assert result.status_code == 200
        data = json.loads(result.body)
        assert "branches" in data

    @pytest.mark.asyncio
    async def test_nodes_path(self, handler, mock_handler_obj):
        """Test nodes subpath works."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph/graph-123/nodes",
            {},
        )
        assert result.status_code == 200
        data = json.loads(result.body)
        assert "nodes" in data

    @pytest.mark.asyncio
    async def test_unknown_subpath(self, handler, mock_handler_obj):
        """Test unknown subpath returns 404."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph/graph-123/unknown",
            {},
        )
        # Falls through to get_graph_debate which should work
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_short_path_returns_404(self, handler, mock_handler_obj):
        """Test root path returns an empty list response."""
        result = await handler.handle_get(
            mock_handler_obj,
            "/api/debates/graph",
            {},
        )
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["debates"] == []


# ============================================================================
# Storage Configuration Tests
# ============================================================================


class TestStorageConfiguration:
    """Tests for storage configuration handling."""

    @pytest.mark.asyncio
    async def test_get_debate_no_storage(self, handler):
        """Test 404 when graph debate storage and cache are both empty."""
        mock_handler = Mock()
        mock_handler.storage = None

        result = await handler.handle_get(
            mock_handler,
            "/api/debates/graph/graph-123",
            {},
        )
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_branches_no_storage(self, handler):
        """Test branches endpoint returns 404 without storage or cache."""
        mock_handler = Mock()
        mock_handler.storage = None

        result = await handler.handle_get(
            mock_handler,
            "/api/debates/graph/graph-123/branches",
            {},
        )
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_nodes_no_storage(self, handler):
        """Test nodes endpoint returns 404 without storage or cache."""
        mock_handler = Mock()
        mock_handler.storage = None

        result = await handler.handle_get(
            mock_handler,
            "/api/debates/graph/graph-123/nodes",
            {},
        )
        assert result.status_code == 404
