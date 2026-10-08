"""Tests for DAG Operations handler.

Covers all routes and behaviour of the DAGOperationsHandler class:
- GET  /api/v1/pipeline/dag/{graph_id}                              - Get graph
- POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/debate       - Debate node
- POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/decompose    - Decompose node
- POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/prioritize   - Prioritize children
- POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/assign-agents- Assign agents
- POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/execute      - Execute node
- POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/find-precedents - Find precedents
- POST /api/v1/pipeline/dag/{graph_id}/cluster-ideas                - Cluster ideas
- POST /api/v1/pipeline/dag/{graph_id}/auto-flow                    - Auto-flow
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.dag_operations import DAGOperationsHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if result is None:
        return 0
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


def _data(result) -> dict:
    """Extract the 'data' envelope from a response."""
    body = _body(result)
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------


@dataclass
class MockOpResult:
    """Mock result returned by DAGOperationsCoordinator methods."""

    success: bool = True
    message: str = "Operation completed"
    created_nodes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class MockGraph:
    """Mock pipeline graph."""

    def __init__(self, graph_id: str = "graph-1"):
        self.graph_id = graph_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "nodes": [],
            "edges": [],
        }


class MockGraphStore:
    """Mock graph store."""

    def __init__(self, graphs: dict[str, MockGraph] | None = None):
        self._graphs = graphs or {}

    def get(self, graph_id: str) -> MockGraph | None:
        return self._graphs.get(graph_id)


class MockCoordinator:
    """Mock DAGOperationsCoordinator."""

    def __init__(self):
        self.debate_node = AsyncMock(
            return_value=MockOpResult(
                success=True,
                message="Debate completed",
                metadata={"rounds": 3},
            )
        )
        self.decompose_node = AsyncMock(
            return_value=MockOpResult(
                success=True,
                message="Decomposed into 3 sub-tasks",
                created_nodes=["n1", "n2", "n3"],
            )
        )
        self.prioritize_children = AsyncMock(
            return_value=MockOpResult(
                success=True,
                message="Prioritized 3 children",
            )
        )
        self.assign_agents = AsyncMock(
            return_value=MockOpResult(
                success=True,
                message="Agents assigned",
            )
        )
        self.execute_node = AsyncMock(
            return_value=MockOpResult(
                success=True,
                message="Execution complete",
            )
        )
        self.find_precedents = AsyncMock(
            return_value=MockOpResult(
                success=True,
                message="Found 2 precedents",
                metadata={"count": 2},
            )
        )
        self.cluster_ideas = AsyncMock(
            return_value=MockOpResult(
                success=True,
                message="Clustered into 2 groups",
                created_nodes=["c1", "c2"],
            )
        )
        self.auto_flow = AsyncMock(
            return_value=MockOpResult(
                success=True,
                message="Auto-flow complete",
                created_nodes=["af1", "af2"],
            )
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.usefixtures("org_scoped_request_user")


@pytest.fixture(autouse=True)
def _caller_owns_every_graph():
    """The caller's org owns every graph; isolation is covered in the pipeline isolation tests."""
    with patch("aragora.tenancy.pipeline_access.graph_owned", return_value=True):
        yield


@pytest.fixture
def handler():
    """Create a DAGOperationsHandler instance."""
    return DAGOperationsHandler(ctx={})


@pytest.fixture
def mock_graph():
    """Create a mock graph."""
    return MockGraph(graph_id="test-graph")


@pytest.fixture
def mock_store(mock_graph):
    """Create a mock graph store with one graph."""
    return MockGraphStore(graphs={"test-graph": mock_graph})


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    return MockCoordinator()


@pytest.fixture
def mock_handler_obj():
    """Create a mock HTTP handler with request body."""

    def _make(body: dict | None = None):
        h = MagicMock()
        if body:
            h.request.body = json.dumps(body).encode("utf-8")
        else:
            h.request.body = b"{}"
        return h

    return _make


@pytest.fixture
def mock_backends(mock_store, mock_coordinator, mock_graph):
    """Patch graph store and coordinator dependencies."""
    with (
        patch(
            "aragora.server.handlers.dag_operations._get_graph_store",
            return_value=mock_store,
        ),
        patch(
            "aragora.server.handlers.dag_operations._get_coordinator",
            return_value=(mock_coordinator, mock_graph),
        ),
    ):
        yield {
            "store": mock_store,
            "coordinator": mock_coordinator,
            "graph": mock_graph,
        }


@pytest.fixture
def mock_backends_no_graph():
    """Patch backends with graph not found."""
    store = MockGraphStore(graphs={})
    with (
        patch(
            "aragora.server.handlers.dag_operations._get_graph_store",
            return_value=store,
        ),
        patch(
            "aragora.server.handlers.dag_operations._get_coordinator",
            return_value=None,
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------


class TestRoutes:
    """Test ROUTES class attribute and can_handle."""

    def test_routes_contains_all_endpoints(self):
        expected = [
            "POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/debate",
            "POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/decompose",
            "POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/prioritize",
            "POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/assign-agents",
            "POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/execute",
            "POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/find-precedents",
            "POST /api/v1/pipeline/dag/{graph_id}/cluster-ideas",
            "POST /api/v1/pipeline/dag/{graph_id}/auto-flow",
            "GET /api/v1/pipeline/dag/{graph_id}",
        ]
        for route in expected:
            assert route in DAGOperationsHandler.ROUTES, f"Missing route: {route}"

    def test_can_handle_valid_dag_paths(self, handler):
        assert handler.can_handle("/api/v1/pipeline/dag/graph-1")
        assert handler.can_handle("/api/v1/pipeline/dag/graph-1/nodes/n1/debate")
        assert handler.can_handle("/api/v1/pipeline/dag/graph-1/cluster-ideas")
        assert handler.can_handle("/api/v1/pipeline/dag/graph-1/auto-flow")

    def test_can_handle_rejects_non_dag_paths(self, handler):
        assert not handler.can_handle("/api/v1/pipeline/other")
        assert not handler.can_handle("/api/v1/debate/start")
        assert not handler.can_handle("/api/v1/health")


# ---------------------------------------------------------------------------
# GET /api/v1/pipeline/dag/{graph_id}
# ---------------------------------------------------------------------------


class TestGetGraph:
    """Test the GET graph endpoint."""

    @pytest.mark.asyncio
    async def test_get_graph_returns_data(self, handler, mock_backends):
        result = await handler._handle_get_graph("test-graph")

        body = _body(result)
        assert "data" in body
        assert body["data"]["graph_id"] == "test-graph"
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_graph_not_found(self, handler):
        store = MockGraphStore(graphs={})
        with patch(
            "aragora.server.handlers.dag_operations._get_graph_store",
            return_value=store,
        ):
            result = await handler._handle_get_graph("nonexistent")

        assert _status(result) == 404
        body = _body(result)
        assert (
            "not found" in body.get("error", "").lower() or "not found" in json.dumps(body).lower()
        )


# ---------------------------------------------------------------------------
# POST node operations - debate
# ---------------------------------------------------------------------------


class TestDebateNode:
    """Test the debate node operation."""

    @pytest.mark.asyncio
    async def test_debate_node_success(self, handler, mock_backends):
        result = await handler._dispatch_node_op(
            "test-graph", "node-1", "debate", {"agents": ["claude"], "rounds": 5}
        )

        body = _body(result)
        data = body.get("data", body)
        assert data["success"] is True
        assert "Debate" in data["message"] or "completed" in data["message"].lower()
        assert _status(result) == 200

        mock_backends["coordinator"].debate_node.assert_awaited_once_with(
            "node-1",
            agents=["claude"],
            rounds=5,
        )

    @pytest.mark.asyncio
    async def test_debate_node_default_rounds(self, handler, mock_backends):
        result = await handler._dispatch_node_op("test-graph", "node-1", "debate", {})

        mock_backends["coordinator"].debate_node.assert_awaited_once_with(
            "node-1",
            agents=None,
            rounds=3,
        )

    @pytest.mark.asyncio
    async def test_debate_node_graph_not_found(self, handler, mock_backends_no_graph):
        result = await handler._dispatch_node_op("nonexistent", "node-1", "debate", {})

        assert _status(result) == 404


# ---------------------------------------------------------------------------
# POST node operations - decompose
# ---------------------------------------------------------------------------


class TestDecomposeNode:
    """Test the decompose node operation."""

    @pytest.mark.asyncio
    async def test_decompose_node_success(self, handler, mock_backends):
        result = await handler._dispatch_node_op("test-graph", "node-1", "decompose", {})

        data = _data(result)
        assert data["success"] is True
        assert data["created_nodes"] == ["n1", "n2", "n3"]
        assert _status(result) == 200

        mock_backends["coordinator"].decompose_node.assert_awaited_once_with("node-1")


# ---------------------------------------------------------------------------
# POST node operations - prioritize
# ---------------------------------------------------------------------------


class TestPrioritizeChildren:
    """Test the prioritize children operation."""

    @pytest.mark.asyncio
    async def test_prioritize_children_success(self, handler, mock_backends):
        result = await handler._dispatch_node_op("test-graph", "node-1", "prioritize", {})

        data = _data(result)
        assert data["success"] is True
        assert _status(result) == 200

        mock_backends["coordinator"].prioritize_children.assert_awaited_once_with("node-1")


# ---------------------------------------------------------------------------
# POST node operations - assign-agents
# ---------------------------------------------------------------------------


class TestAssignAgents:
    """Test the assign-agents operation."""

    @pytest.mark.asyncio
    async def test_assign_agents_default_node_id(self, handler, mock_backends):
        result = await handler._dispatch_node_op("test-graph", "node-1", "assign-agents", {})

        data = _data(result)
        assert data["success"] is True
        assert _status(result) == 200

        mock_backends["coordinator"].assign_agents.assert_awaited_once_with(["node-1"])

    @pytest.mark.asyncio
    async def test_assign_agents_custom_node_ids(self, handler, mock_backends):
        result = await handler._dispatch_node_op(
            "test-graph", "node-1", "assign-agents", {"node_ids": ["a", "b", "c"]}
        )

        mock_backends["coordinator"].assign_agents.assert_awaited_once_with(["a", "b", "c"])


# ---------------------------------------------------------------------------
# POST node operations - execute
# ---------------------------------------------------------------------------


class TestExecuteNode:
    """Test the execute node operation."""

    @pytest.mark.asyncio
    async def test_execute_node_success(self, handler, mock_backends):
        result = await handler._dispatch_node_op("test-graph", "node-1", "execute", {})

        data = _data(result)
        assert data["success"] is True
        assert _status(result) == 200

        mock_backends["coordinator"].execute_node.assert_awaited_once_with("node-1")


# ---------------------------------------------------------------------------
# POST node operations - find-precedents
# ---------------------------------------------------------------------------


class TestFindPrecedents:
    """Test the find-precedents operation."""

    @pytest.mark.asyncio
    async def test_find_precedents_success(self, handler, mock_backends):
        result = await handler._dispatch_node_op(
            "test-graph", "node-1", "find-precedents", {"max_results": 10}
        )

        data = _data(result)
        assert data["success"] is True
        assert data["metadata"]["count"] == 2
        assert _status(result) == 200

        mock_backends["coordinator"].find_precedents.assert_awaited_once_with(
            "node-1",
            max_results=10,
        )

    @pytest.mark.asyncio
    async def test_find_precedents_default_max_results(self, handler, mock_backends):
        result = await handler._dispatch_node_op("test-graph", "node-1", "find-precedents", {})

        mock_backends["coordinator"].find_precedents.assert_awaited_once_with(
            "node-1",
            max_results=5,
        )


# ---------------------------------------------------------------------------
# POST node operations - unknown operation
# ---------------------------------------------------------------------------


class TestUnknownOperation:
    """Test unknown operations return 400."""

    @pytest.mark.asyncio
    async def test_unknown_operation_returns_400(self, handler, mock_backends):
        result = await handler._dispatch_node_op("test-graph", "node-1", "unknown-op", {})

        assert _status(result) == 400
        body = _body(result)
        assert "unknown" in json.dumps(body).lower() or "Unknown" in json.dumps(body)


# ---------------------------------------------------------------------------
# POST node operations - failure result
# ---------------------------------------------------------------------------


class TestOperationFailure:
    """Test that failed coordinator results return 400 status."""

    @pytest.mark.asyncio
    async def test_failed_operation_returns_400(self, handler, mock_backends):
        mock_backends["coordinator"].debate_node.return_value = MockOpResult(
            success=False,
            message="Node not found in graph",
        )

        result = await handler._dispatch_node_op("test-graph", "node-1", "debate", {})

        data = _data(result)
        assert data["success"] is False
        assert _status(result) == 400


# ---------------------------------------------------------------------------
# POST /api/v1/pipeline/dag/{graph_id}/cluster-ideas
# ---------------------------------------------------------------------------


class TestClusterIdeas:
    """Test the cluster-ideas endpoint."""

    @pytest.mark.asyncio
    async def test_cluster_ideas_success(self, handler, mock_backends):
        result = await handler._handle_cluster_ideas(
            "test-graph",
            {"ideas": ["idea1", "idea2"], "threshold": 0.5},
        )

        data = _data(result)
        assert data["success"] is True
        assert data["created_nodes"] == ["c1", "c2"]
        assert _status(result) == 200

        mock_backends["coordinator"].cluster_ideas.assert_awaited_once_with(
            ["idea1", "idea2"],
            threshold=0.5,
        )

    @pytest.mark.asyncio
    async def test_cluster_ideas_default_threshold(self, handler, mock_backends):
        result = await handler._handle_cluster_ideas(
            "test-graph",
            {"ideas": ["idea1"]},
        )

        mock_backends["coordinator"].cluster_ideas.assert_awaited_once_with(
            ["idea1"],
            threshold=0.3,
        )

    @pytest.mark.asyncio
    async def test_cluster_ideas_missing_ideas(self, handler, mock_backends):
        result = await handler._handle_cluster_ideas("test-graph", {})

        assert _status(result) == 400
        body = _body(result)
        assert "ideas" in json.dumps(body).lower()

    @pytest.mark.asyncio
    async def test_cluster_ideas_empty_ideas_list(self, handler, mock_backends):
        result = await handler._handle_cluster_ideas("test-graph", {"ideas": []})

        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_cluster_ideas_graph_not_found(self, handler, mock_backends_no_graph):
        result = await handler._handle_cluster_ideas("nonexistent", {"ideas": ["idea1"]})

        assert _status(result) == 404


# ---------------------------------------------------------------------------
# POST /api/v1/pipeline/dag/{graph_id}/auto-flow
# ---------------------------------------------------------------------------


class TestAutoFlow:
    """Test the auto-flow endpoint."""

    @pytest.mark.asyncio
    async def test_auto_flow_success(self, handler, mock_backends):
        result = await handler._handle_auto_flow(
            "test-graph",
            {"ideas": ["idea1", "idea2"], "config": {"parallel": True}},
        )

        data = _data(result)
        assert data["success"] is True
        assert data["created_nodes"] == ["af1", "af2"]
        assert _status(result) == 200

        mock_backends["coordinator"].auto_flow.assert_awaited_once_with(
            ["idea1", "idea2"],
            config={"parallel": True},
        )

    @pytest.mark.asyncio
    async def test_auto_flow_no_config(self, handler, mock_backends):
        result = await handler._handle_auto_flow(
            "test-graph",
            {"ideas": ["idea1"]},
        )

        mock_backends["coordinator"].auto_flow.assert_awaited_once_with(
            ["idea1"],
            config=None,
        )

    @pytest.mark.asyncio
    async def test_auto_flow_missing_ideas(self, handler, mock_backends):
        result = await handler._handle_auto_flow("test-graph", {})

        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_auto_flow_graph_not_found(self, handler, mock_backends_no_graph):
        result = await handler._handle_auto_flow("nonexistent", {"ideas": ["idea1"]})

        assert _status(result) == 404


# ---------------------------------------------------------------------------
# Request body parsing
# ---------------------------------------------------------------------------


class TestGetRequestBody:
    """Test the _get_request_body static method."""

    def test_parse_valid_json_body(self):
        handler = MagicMock()
        handler.request.body = json.dumps({"key": "value"}).encode("utf-8")

        result = DAGOperationsHandler._get_request_body(handler)
        assert result == {"key": "value"}

    def test_parse_string_body(self):
        handler = MagicMock()
        handler.request.body = json.dumps({"key": "value"})

        result = DAGOperationsHandler._get_request_body(handler)
        assert result == {"key": "value"}

    def test_empty_body_returns_empty_dict(self):
        handler = MagicMock()
        handler.request.body = b""

        result = DAGOperationsHandler._get_request_body(handler)
        assert result == {}

    def test_none_body_returns_empty_dict(self):
        handler = MagicMock()
        handler.request.body = None

        result = DAGOperationsHandler._get_request_body(handler)
        assert result == {}

    def test_invalid_json_returns_empty_dict(self):
        handler = MagicMock()
        handler.request.body = b"not-json"

        result = DAGOperationsHandler._get_request_body(handler)
        assert result == {}

    def test_no_request_attr_returns_empty_dict(self):
        handler = MagicMock(spec=[])

        result = DAGOperationsHandler._get_request_body(handler)
        assert result == {}


# ---------------------------------------------------------------------------
# handle_post dispatch
# ---------------------------------------------------------------------------


class TestHandlePostDispatch:
    """Test the handle_post method dispatch logic."""

    @pytest.mark.asyncio
    async def test_handle_post_dispatches_node_op(self, handler, mock_backends, mock_handler_obj):
        h = mock_handler_obj({"agents": ["claude"]})
        result = await handler.handle_post(
            "/api/v1/pipeline/dag/test-graph/nodes/node-1/debate",
            {},
            h,
        )

        # Should dispatch to debate node
        mock_backends["coordinator"].debate_node.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_post_dispatches_cluster(self, handler, mock_backends, mock_handler_obj):
        h = mock_handler_obj({"ideas": ["idea1"]})
        result = await handler.handle_post(
            "/api/v1/pipeline/dag/test-graph/cluster-ideas",
            {},
            h,
        )

        mock_backends["coordinator"].cluster_ideas.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_post_dispatches_auto_flow(self, handler, mock_backends, mock_handler_obj):
        h = mock_handler_obj({"ideas": ["idea1"]})
        result = await handler.handle_post(
            "/api/v1/pipeline/dag/test-graph/auto-flow",
            {},
            h,
        )

        mock_backends["coordinator"].auto_flow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_post_unmatched_path_returns_none(
        self, handler, mock_backends, mock_handler_obj
    ):
        h = mock_handler_obj({})
        result = handler.handle_post(
            "/api/v1/pipeline/dag/",
            {},
            h,
        )

        assert result is None


# ---------------------------------------------------------------------------
# handle (GET) dispatch
# ---------------------------------------------------------------------------


class TestHandleGetDispatch:
    """Test the handle method (GET dispatch)."""

    @pytest.mark.asyncio
    async def test_handle_dispatches_get_graph(self, handler, mock_backends):
        result = await handler.handle(
            "/api/v1/pipeline/dag/test-graph",
            {},
            MagicMock(),
        )

        body = _body(result)
        assert "data" in body

    @pytest.mark.asyncio
    async def test_handle_returns_none_for_non_matching_path(self, handler, mock_backends):
        result = handler.handle(
            "/api/v1/pipeline/dag/test-graph/nodes/n1/debate",
            {},
            MagicMock(),
        )

        # Node-op paths don't match _DAG_BASE pattern, so handle returns None
        assert result is None


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestInit:
    """Test handler initialization."""

    def test_default_ctx(self):
        handler = DAGOperationsHandler()
        assert handler.ctx == {}

    def test_custom_ctx(self):
        ctx = {"key": "value"}
        handler = DAGOperationsHandler(ctx=ctx)
        assert handler.ctx == ctx
