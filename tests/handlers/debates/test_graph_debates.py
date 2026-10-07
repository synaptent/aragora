"""Tests for graph debates handler.

Tests the graph debates API endpoints including:
- POST /api/v1/debates/graph - Run a graph-structured debate with branching
- GET /api/v1/debates/graph/{id} - Get graph debate by ID
- GET /api/v1/debates/graph/{id}/branches - Get all branches for a debate
- GET /api/v1/debates/graph/{id}/nodes - Get all nodes in debate graph
"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.tenancy.record_scope import OrgScope

pytestmark = pytest.mark.usefixtures("org_scoped_request_user")

TEST_ORG = "test-org-001"
SCOPE = OrgScope(org_id=TEST_ORG, user_id="test-user-001", role="admin")


@pytest.fixture
def graph_handler():
    """Create graph debates handler with mock context."""
    from aragora.server.handlers.debates.graph_debates import GraphDebatesHandler

    ctx = {}
    handler = GraphDebatesHandler(ctx)
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
        from aragora.server.handlers.debates import graph_debates

        graph_debates._graph_limiter = graph_debates.RateLimiter(requests_per_minute=5)
        graph_debates._graph_debate_cache.clear()
    except (ImportError, AttributeError):
        pass

    yield

    try:
        from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

        reset_rate_limiters()
    except ImportError:
        pass

    try:
        from aragora.server.handlers.debates import graph_debates

        graph_debates._graph_debate_cache.clear()
    except (ImportError, AttributeError):
        pass


@pytest.fixture
def mock_http_handler():
    """Create mock HTTP handler."""
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler.event_emitter = None
    handler.storage = None
    return handler


@pytest.fixture
def graph_debate_payload():
    """Create a representative graph debate payload."""
    return {
        "debate_id": "graph-123",
        "task": "Should AI systems require formal approval for deployment?",
        "status": "completed",
        "created_at": "2026-03-30T18:30:00+00:00",
        "graph": {
            "debate_id": "graph-123",
            "root_id": "node-1",
            "main_branch_id": "main",
            "created_at": "2026-03-30T18:30:00+00:00",
            "nodes": {
                "node-1": {
                    "id": "node-1",
                    "node_type": "root",
                    "agent_id": "claude",
                    "content": "Root prompt",
                    "timestamp": "2026-03-30T18:30:00+00:00",
                    "parent_ids": [],
                    "child_ids": ["node-2"],
                    "branch_id": "main",
                    "confidence": 0.71,
                    "agreement_scores": {},
                    "claims": [],
                    "evidence": [],
                    "metadata": {},
                    "hash": "hash-1",
                }
            },
            "branches": {
                "main": {
                    "id": "main",
                    "name": "main",
                    "reason": "root",
                    "start_node_id": "node-1",
                    "end_node_id": None,
                    "hypothesis": "Primary line",
                    "confidence": 0.71,
                    "is_active": True,
                    "is_merged": False,
                    "merged_into": None,
                    "node_count": 1,
                    "total_agreement": 0.71,
                }
            },
            "merge_history": [],
            "policy": {
                "disagreement_threshold": 0.7,
                "uncertainty_threshold": 0.3,
                "max_branches": 3,
                "max_depth": 5,
            },
        },
        "branches": [
            {
                "id": "main",
                "name": "main",
                "reason": "root",
                "start_node_id": "node-1",
                "end_node_id": None,
                "hypothesis": "Primary line",
                "confidence": 0.71,
                "is_active": True,
                "is_merged": False,
                "merged_into": None,
                "node_count": 1,
                "total_agreement": 0.71,
            }
        ],
        "merge_results": [],
        "node_count": 1,
        "branch_count": 1,
        "org_id": TEST_ORG,
        "created_by": "test-user-001",
    }


# =============================================================================
# Initialization Tests
# =============================================================================


class TestGraphDebatesHandlerInit:
    """Tests for handler initialization."""

    def test_routes_defined(self, graph_handler):
        """Test that handler routes are defined."""
        assert hasattr(graph_handler, "ROUTES")
        assert len(graph_handler.ROUTES) > 0

    def test_can_handle_graph_path(self, graph_handler):
        """Test can_handle recognizes graph paths."""
        assert graph_handler.can_handle("/api/v1/debates/graph")
        assert graph_handler.can_handle("/api/v1/debates/graph/")
        assert graph_handler.can_handle("/api/v1/debates/graph/abc123")
        assert graph_handler.can_handle("/api/v1/debates/graph/abc123/branches")
        assert graph_handler.can_handle("/api/v1/debates/graph/abc123/nodes")

    def test_cannot_handle_other_paths(self, graph_handler):
        """Test can_handle rejects non-graph paths."""
        assert not graph_handler.can_handle("/api/v1/debates")
        assert not graph_handler.can_handle("/api/v1/debates/abc123")
        assert not graph_handler.can_handle("/api/v1/debates/matrix")
        assert not graph_handler.can_handle("/api/v1/users")


class TestGraphDebatesLiveListing:
    """Tests for listing and cache-backed retrieval of graph debates."""

    @pytest.mark.asyncio
    async def test_get_root_lists_cached_graph_debates(
        self, graph_handler, mock_http_handler, graph_debate_payload
    ):
        """GET /api/v1/debates/graph returns cached debates instead of 404."""
        from aragora.server.handlers.debates import graph_debates

        graph_handler.get_auth_context = AsyncMock(return_value={})
        graph_handler.check_permission = MagicMock()
        graph_debates._remember_graph_debate(graph_debate_payload)

        result = await graph_handler.handle_get(mock_http_handler, "/api/v1/debates/graph", {})

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["debates"][0]["debate_id"] == "graph-123"
        assert data["debates"][0]["task"] == graph_debate_payload["task"]

    @pytest.mark.asyncio
    async def test_get_graph_debate_falls_back_to_cache(
        self, graph_handler, mock_http_handler, graph_debate_payload
    ):
        """Cached graph debates remain readable even without external storage."""
        from aragora.server.handlers.debates import graph_debates

        graph_debates._remember_graph_debate(graph_debate_payload)

        result = await graph_handler._get_graph_debate(mock_http_handler, "graph-123", SCOPE)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["debate_id"] == "graph-123"

    @pytest.mark.asyncio
    async def test_persist_graph_debate_saves_when_storage_hook_exists(
        self, graph_handler, mock_http_handler, graph_debate_payload
    ):
        """Completed graph debates use optional storage save hooks when present."""
        mock_http_handler.storage = MagicMock()
        mock_http_handler.storage.save_graph_debate = AsyncMock()

        await graph_handler._persist_graph_debate(mock_http_handler, graph_debate_payload)

        mock_http_handler.storage.save_graph_debate.assert_awaited_once()


# =============================================================================
# POST Validation Tests
# =============================================================================


class TestGraphDebatePostValidation:
    """Tests for POST request validation."""

    @pytest.mark.asyncio
    async def test_returns_404_for_wrong_path(self, graph_handler, mock_http_handler):
        """Returns 404 for non-graph POST paths."""
        result = await graph_handler.handle_post(mock_http_handler, "/api/v1/debates/other", {})
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_400_without_task(self, graph_handler, mock_http_handler):
        """Returns 400 when task is missing."""
        result = await graph_handler.handle_post(
            mock_http_handler, "/api/v1/debates/graph", {"agents": ["claude", "gpt4"]}
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "task" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_non_string_task(self, graph_handler, mock_http_handler):
        """Returns 400 when task is not a string."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {"task": 12345, "agents": ["claude", "gpt4"]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "string" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_short_task(self, graph_handler, mock_http_handler):
        """Returns 400 when task is too short."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {"task": "Short", "agents": ["claude", "gpt4"]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "10 characters" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_long_task(self, graph_handler, mock_http_handler):
        """Returns 400 when task is too long."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {"task": "A" * 5001, "agents": ["claude", "gpt4"]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "5000 characters" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_suspicious_task_script(self, graph_handler, mock_http_handler):
        """Returns 400 when task contains script tag."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {"task": "What about <script>alert('xss')</script>?", "agents": ["claude", "gpt4"]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "invalid characters" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_suspicious_task_template(self, graph_handler, mock_http_handler):
        """Returns 400 when task contains template injection."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {"task": "Evaluate this: {{config.secret}}", "agents": ["claude", "gpt4"]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "invalid characters" in data.get("error", "").lower()


# =============================================================================
# Agent Validation Tests
# =============================================================================


class TestGraphDebateAgentValidation:
    """Tests for agent validation."""

    @pytest.mark.asyncio
    async def test_returns_400_for_non_array_agents(self, graph_handler, mock_http_handler):
        """Returns 400 when agents is not an array."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {"task": "What is the meaning of life and existence?", "agents": "claude"},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "array" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_too_few_agents(self, graph_handler, mock_http_handler):
        """Returns 400 when less than 2 agents provided."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {"task": "What is the meaning of life and existence?", "agents": ["claude"]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "2 agents" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_too_many_agents(self, graph_handler, mock_http_handler):
        """Returns 400 when more than 10 agents provided."""
        agents = [f"agent{i}" for i in range(11)]
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {"task": "What is the meaning of life and existence?", "agents": agents},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "10 agents" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_non_string_agent(self, graph_handler, mock_http_handler):
        """Returns 400 when agent name is not a string."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {"task": "What is the meaning of life and existence?", "agents": ["claude", 123]},
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "agents[1]" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_long_agent_name(self, graph_handler, mock_http_handler):
        """Returns 400 when agent name exceeds 50 chars."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {
                "task": "What is the meaning of life and existence?",
                "agents": ["claude", "a" * 51],
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "50 chars" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_invalid_agent_name(self, graph_handler, mock_http_handler):
        """Returns 400 when agent name contains invalid characters."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {
                "task": "What is the meaning of life and existence?",
                "agents": ["claude", "agent<script>"],
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "invalid agent name" in data.get("error", "").lower()


# =============================================================================
# Max Rounds Validation Tests
# =============================================================================


class TestGraphDebateRoundsValidation:
    """Tests for max_rounds validation."""

    @pytest.mark.asyncio
    async def test_returns_400_for_invalid_max_rounds(self, graph_handler, mock_http_handler):
        """Returns 400 when max_rounds is not a number."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {
                "task": "What is the meaning of life and existence?",
                "agents": ["claude", "gpt4"],
                "max_rounds": "invalid",
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "max_rounds" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_zero_max_rounds(self, graph_handler, mock_http_handler):
        """Returns 400 when max_rounds is less than 1."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {
                "task": "What is the meaning of life and existence?",
                "agents": ["claude", "gpt4"],
                "max_rounds": 0,
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "at least 1" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_too_many_rounds(self, graph_handler, mock_http_handler):
        """Returns 400 when max_rounds exceeds 20."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {
                "task": "What is the meaning of life and existence?",
                "agents": ["claude", "gpt4"],
                "max_rounds": 21,
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "at most 20" in data.get("error", "")


# =============================================================================
# Branch Policy Validation Tests
# =============================================================================


class TestGraphDebateBranchPolicyValidation:
    """Tests for branch_policy validation."""

    @pytest.mark.asyncio
    async def test_returns_400_for_non_dict_branch_policy(self, graph_handler, mock_http_handler):
        """Returns 400 when branch_policy is not an object."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {
                "task": "What is the meaning of life and existence?",
                "agents": ["claude", "gpt4"],
                "branch_policy": "invalid",
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "object" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_returns_400_for_invalid_min_disagreement(self, graph_handler, mock_http_handler):
        """Returns 400 when min_disagreement is out of range."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {
                "task": "What is the meaning of life and existence?",
                "agents": ["claude", "gpt4"],
                "branch_policy": {"min_disagreement": 1.5},
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "min_disagreement" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_invalid_max_branches(self, graph_handler, mock_http_handler):
        """Returns 400 when max_branches is out of range."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {
                "task": "What is the meaning of life and existence?",
                "agents": ["claude", "gpt4"],
                "branch_policy": {"max_branches": 15},
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "max_branches" in data.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_400_for_invalid_merge_strategy(self, graph_handler, mock_http_handler):
        """Returns 400 when merge_strategy is invalid."""
        result = await graph_handler.handle_post(
            mock_http_handler,
            "/api/v1/debates/graph",
            {
                "task": "What is the meaning of life and existence?",
                "agents": ["claude", "gpt4"],
                "branch_policy": {"merge_strategy": "invalid"},
            },
        )
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "merge_strategy" in data.get("error", "")


# =============================================================================
# GET Endpoint Tests
# =============================================================================


class TestGraphDebateGetEndpoints:
    """Tests for GET endpoints."""

    @pytest.mark.asyncio
    async def test_get_base_path_returns_empty_list(self, graph_handler, mock_http_handler):
        """Returns an empty graph debate list for the root path."""
        result = await graph_handler.handle_get(mock_http_handler, "/api/v1/debates/graph", {})
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["debates"] == []

    @pytest.mark.asyncio
    async def test_get_debate_returns_404_without_storage(self, graph_handler, mock_http_handler):
        """Returns 404 when no stored or cached graph debate exists."""
        mock_http_handler.storage = None
        result = await graph_handler.handle_get(
            mock_http_handler, "/api/v1/debates/graph/test-123", {}
        )
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_debate_returns_404_when_not_found(self, graph_handler, mock_http_handler):
        """Returns 404 when graph debate doesn't exist."""
        mock_storage = AsyncMock()
        mock_storage.get_graph_debate = AsyncMock(return_value=None)
        mock_http_handler.storage = mock_storage

        result = await graph_handler.handle_get(
            mock_http_handler, "/api/v1/debates/graph/nonexistent", {}
        )
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_debate_returns_debate_data(self, graph_handler, mock_http_handler):
        """Returns debate data when found."""
        debate_data = {"id": "test-123", "task": "Test task", "nodes": [], "org_id": TEST_ORG}
        mock_storage = AsyncMock()
        mock_storage.get_graph_debate = AsyncMock(return_value=debate_data)
        mock_http_handler.storage = mock_storage

        result = await graph_handler.handle_get(
            mock_http_handler, "/api/v1/debates/graph/test-123", {}
        )
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["id"] == "test-123"

    @pytest.mark.asyncio
    async def test_get_branches_returns_404_without_storage(self, graph_handler, mock_http_handler):
        """Returns 404 when branch data is unavailable from storage and cache."""
        mock_http_handler.storage = None
        result = await graph_handler.handle_get(
            mock_http_handler, "/api/v1/debates/graph/test-123/branches", {}
        )
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_branches_returns_branch_data(self, graph_handler, mock_http_handler):
        """Returns branch data when found."""
        branches = [{"id": "branch-1"}, {"id": "branch-2"}]
        mock_storage = AsyncMock()
        mock_storage.get_debate_branches = AsyncMock(return_value=branches)
        mock_storage.get_graph_debate = AsyncMock(return_value={"org_id": TEST_ORG})
        mock_http_handler.storage = mock_storage

        result = await graph_handler.handle_get(
            mock_http_handler, "/api/v1/debates/graph/test-123/branches", {}
        )
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["debate_id"] == "test-123"
        assert len(data["branches"]) == 2

    @pytest.mark.asyncio
    async def test_get_nodes_returns_404_without_storage(self, graph_handler, mock_http_handler):
        """Returns 404 when node data is unavailable from storage and cache."""
        mock_http_handler.storage = None
        result = await graph_handler.handle_get(
            mock_http_handler, "/api/v1/debates/graph/test-123/nodes", {}
        )
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_nodes_returns_node_data(self, graph_handler, mock_http_handler):
        """Returns node data when found."""
        nodes = [{"id": "node-1", "content": "First"}, {"id": "node-2", "content": "Second"}]
        mock_storage = AsyncMock()
        mock_storage.get_debate_nodes = AsyncMock(return_value=nodes)
        mock_storage.get_graph_debate = AsyncMock(return_value={"org_id": TEST_ORG})
        mock_http_handler.storage = mock_storage

        result = await graph_handler.handle_get(
            mock_http_handler, "/api/v1/debates/graph/test-123/nodes", {}
        )
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["debate_id"] == "test-123"
        assert len(data["nodes"]) == 2


# =============================================================================
# Rate Limiting Tests
# =============================================================================


class TestGraphDebateRateLimiting:
    """Tests for rate limiting."""

    @pytest.mark.asyncio
    async def test_rate_limit_after_multiple_requests(self, graph_handler):
        """Returns 429 after exceeding rate limit."""
        # Make requests until rate limited
        for i in range(6):  # 5 allowed, 6th should fail
            mock_handler = MagicMock()
            mock_handler.client_address = ("192.168.1.100", 12345)
            mock_handler.headers = {}

            result = await graph_handler.handle_post(
                mock_handler,
                "/api/v1/debates/graph",
                {
                    "task": f"What is the meaning of life and existence? Request {i}",
                    "agents": ["claude", "gpt4"],
                },
            )

            if i >= 5:  # After 5 requests, should be rate limited
                assert result.status_code == 429
                data = json.loads(result.body)
                assert "rate limit" in data.get("error", "").lower()


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestGraphDebateErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_import_error(self, graph_handler, mock_http_handler):
        """Returns 500 when graph module import fails."""
        with patch(
            "aragora.server.handlers.debates.graph_debates.GraphDebatesHandler._load_agents",
            new_callable=AsyncMock,
            return_value=[MagicMock(), MagicMock()],
        ):
            # Patch the import to fail
            with patch.dict("sys.modules", {"aragora.debate.graph": None}):
                result = await graph_handler.handle_post(
                    mock_http_handler,
                    "/api/v1/debates/graph",
                    {
                        "task": "What is the meaning of life and existence?",
                        "agents": ["claude", "gpt4"],
                    },
                )
                # Will fail at import or with 500 error
                assert result.status_code in [400, 500]

    @pytest.mark.asyncio
    async def test_handles_no_valid_agents(self, graph_handler, mock_http_handler):
        """Returns 400 when no valid agents are found."""
        with patch.object(graph_handler, "_load_agents", new_callable=AsyncMock, return_value=[]):
            result = await graph_handler.handle_post(
                mock_http_handler,
                "/api/v1/debates/graph",
                {
                    "task": "What is the meaning of life and existence?",
                    "agents": ["invalid_agent_1", "invalid_agent_2"],
                },
            )
            assert result.status_code == 400
            data = json.loads(result.body)
            assert "no valid agents" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_get_debate_handles_storage_error(self, graph_handler, mock_http_handler):
        """Returns 500 on storage error when getting debate."""
        mock_storage = AsyncMock()
        mock_storage.get_graph_debate = AsyncMock(side_effect=RuntimeError("Database error"))
        mock_http_handler.storage = mock_storage

        result = await graph_handler.handle_get(
            mock_http_handler, "/api/v1/debates/graph/test-123", {}
        )
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_get_branches_handles_storage_error(self, graph_handler, mock_http_handler):
        """Returns 500 on storage error when getting branches."""
        mock_storage = AsyncMock()
        mock_storage.get_debate_branches = AsyncMock(side_effect=RuntimeError("Database error"))
        mock_storage.get_graph_debate = AsyncMock(return_value={"org_id": TEST_ORG})
        mock_http_handler.storage = mock_storage

        result = await graph_handler.handle_get(
            mock_http_handler, "/api/v1/debates/graph/test-123/branches", {}
        )
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_get_nodes_handles_storage_error(self, graph_handler, mock_http_handler):
        """Returns 500 on storage error when getting nodes."""
        mock_storage = AsyncMock()
        mock_storage.get_debate_nodes = AsyncMock(side_effect=RuntimeError("Database error"))
        mock_storage.get_graph_debate = AsyncMock(return_value={"org_id": TEST_ORG})
        mock_http_handler.storage = mock_storage

        result = await graph_handler.handle_get(
            mock_http_handler, "/api/v1/debates/graph/test-123/nodes", {}
        )
        assert result.status_code == 500
