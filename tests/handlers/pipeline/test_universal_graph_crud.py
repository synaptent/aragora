"""Tests for UniversalGraphHandler full CRUD API.

Covers:
  GET    /api/v1/pipeline/graphs              List graphs
  GET    /api/v1/pipeline/graphs/:id          Get graph
  POST   /api/v1/pipeline/graphs              Create graph
  PUT    /api/v1/pipeline/graphs/:id          Update graph
  DELETE /api/v1/pipeline/graphs/:id          Delete graph
  POST   /api/v1/pipeline/graphs/:id/nodes    Add node
  DELETE /api/v1/pipeline/graphs/:id/nodes/:nid  Remove node
  GET    /api/v1/pipeline/graphs/:id/nodes    Query nodes
  POST   /api/v1/pipeline/graphs/:id/edges    Add edge
  DELETE /api/v1/pipeline/graphs/:id/edges/:eid  Remove edge
  POST   /api/v1/pipeline/graphs/:id/promote  Promote nodes
  GET    /api/v1/pipeline/graphs/:id/provenance/:nid  Provenance chain
  GET    /api/v1/pipeline/graphs/:id/react-flow  React Flow export
  GET    /api/v1/pipeline/graphs/:id/integrity   Integrity hash
  PATCH  /api/v1/pipeline/graphs/:id/nodes/:node_id  Update node properties
  POST   /api/v1/pipeline/graphs/:id/execute/:node_id  Trigger debate on node
  can_handle routing
  Rate limiting
  Invalid ID validation (SAFE_ID_PATTERN)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.pipeline.universal_node import UniversalEdge, UniversalGraph, UniversalNode
import aragora.server.handlers.pipeline.universal_graph as universal_graph_module
from aragora.server.handlers.pipeline.universal_graph import UniversalGraphHandler
from aragora.tenancy.record_scope import OrgScope

_SCOPE = OrgScope(org_id="test-org-001", user_id="test-user-001", role="admin")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler(ctx: dict[str, Any] | None = None) -> UniversalGraphHandler:
    return UniversalGraphHandler(ctx=ctx or {})


def _make_http_handler(
    body: dict[str, Any] | None = None,
    client_ip: str = "127.0.0.1",
) -> MagicMock:
    handler = MagicMock()
    handler.client_address = (client_ip, 12345)
    handler.headers = {"Content-Length": "0"}
    if body is not None:
        raw = json.dumps(body).encode()
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile.read.return_value = raw
    else:
        handler.rfile.read.return_value = b"{}"
        handler.headers = {"Content-Length": "2"}
    return handler


def _body(result) -> dict[str, Any]:
    """Extract JSON body from a HandlerResult."""
    if result is None:
        return {}
    if hasattr(result, "body"):
        raw = result.body
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw) if raw else {}
    if isinstance(result, tuple):
        return result[0] if isinstance(result[0], dict) else json.loads(result[0])
    return {}


def _status(result) -> int:
    """Extract status code from a HandlerResult."""
    if result is None:
        return 0
    if hasattr(result, "status_code"):
        return result.status_code
    if isinstance(result, tuple):
        return result[1]
    return 0


def _mock_graph(graph_id: str = "graph-abc123", name: str = "Test Pipeline"):
    """Create a mock UniversalGraph."""
    graph = MagicMock(spec=UniversalGraph)
    graph.id = graph_id
    graph.name = name
    graph.nodes = {}
    graph.edges = {}
    graph.owner_id = "user-1"
    graph.workspace_id = "ws-1"
    graph.metadata = {}
    graph.created_at = 1000.0
    graph.updated_at = 1000.0
    graph.to_dict.return_value = {
        "id": graph_id,
        "name": name,
        "nodes": [],
        "edges": [],
        "transitions": [],
        "metadata": {},
    }
    return graph


def _mock_node(node_id: str = "node-abc123"):
    """Create a mock UniversalNode with mutable attributes."""
    node = MagicMock(spec=UniversalNode)
    node.id = node_id
    node.label = "Test Node"
    node.description = "A test node"
    node.status = "active"
    node.position_x = 0.0
    node.position_y = 0.0
    node.confidence = 0.5
    node.data = {}
    node.metadata = {}
    node.to_dict.return_value = {
        "id": node_id,
        "stage": "ideas",
        "node_subtype": "concept",
        "label": "Test Node",
        "status": "active",
        "position_x": 0.0,
        "position_y": 0.0,
    }
    return node


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset the rate limiter between tests."""
    universal_graph_module._graph_limiter = universal_graph_module.RateLimiter(
        requests_per_minute=60
    )
    yield
    universal_graph_module._graph_limiter = universal_graph_module.RateLimiter(
        requests_per_minute=60
    )


@pytest.fixture(autouse=True)
def _bypass_check_permission(request, monkeypatch):
    """Bypass _check_permission on UniversalGraphHandler for all tests."""
    if "no_auto_auth" in [m.name for m in request.node.iter_markers()]:
        return
    monkeypatch.setattr(
        UniversalGraphHandler,
        "_check_permission",
        staticmethod(lambda handler, permission: (_SCOPE, None)),
    )
    monkeypatch.setattr("aragora.tenancy.pipeline_access.graph_owned", lambda *args, **kwargs: True)


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset the module-level _store between tests."""
    import aragora.server.handlers.pipeline.universal_graph as mod

    mod._store = None
    yield
    mod._store = None


@pytest.fixture
def mock_store():
    """Create a mock graph store."""
    store = MagicMock()
    store.create = MagicMock()
    store.list = MagicMock(return_value=[])
    store.get = MagicMock(return_value=None)
    store.update = MagicMock()
    store.delete = MagicMock(return_value=True)
    store.add_node = MagicMock()
    store.remove_node = MagicMock()
    store.query_nodes = MagicMock(return_value=[])
    store.get_provenance_chain = MagicMock(return_value=[])
    return store


@pytest.fixture
def patched_store(mock_store):
    """Patch _get_store to return the mock store."""
    with patch(
        "aragora.server.handlers.pipeline.universal_graph._get_store",
        return_value=mock_store,
    ):
        yield mock_store


# ===========================================================================
# can_handle routing
# ===========================================================================


class TestCanHandle:
    """Tests for route matching."""

    def test_matches_graphs_list(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/pipeline/graphs") is True

    def test_matches_graphs_with_id(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/pipeline/graphs/graph-123") is True

    def test_matches_graphs_with_sub_resource(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/pipeline/graphs/graph-123/nodes") is True

    def test_no_match_wrong_prefix(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/debates/graphs") is False

    def test_no_match_receipts_path(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/receipts") is False


# ===========================================================================
# GET /api/v1/pipeline/graphs  (list)
# ===========================================================================


class TestListGraphs:
    """Tests for listing graphs."""

    def test_list_empty(self, patched_store):
        patched_store.list.return_value = []
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["graphs"] == []
        assert body["count"] == 0

    def test_list_returns_graphs(self, patched_store):
        patched_store.list.return_value = [
            {"id": "g1", "name": "Graph 1"},
            {"id": "g2", "name": "Graph 2"},
        ]
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs", {}, http)
        body = _body(result)
        assert body["count"] == 2

    def test_list_passes_owner_filter(self, patched_store):
        patched_store.list.return_value = []
        h = _make_handler()
        http = _make_http_handler()
        h.handle("/api/v1/pipeline/graphs", {"owner_id": "user-1"}, http)
        patched_store.list.assert_called_once()
        call_kwargs = patched_store.list.call_args
        assert (
            call_kwargs.kwargs.get("owner_id") == "user-1"
            or call_kwargs[1].get("owner_id") == "user-1"
        )

    def test_list_passes_workspace_filter(self, patched_store):
        patched_store.list.return_value = []
        h = _make_handler()
        http = _make_http_handler()
        h.handle("/api/v1/pipeline/graphs", {"workspace_id": "ws-42"}, http)
        patched_store.list.assert_called_once()
        call_kwargs = patched_store.list.call_args
        assert (
            call_kwargs.kwargs.get("workspace_id") == "ws-42"
            or call_kwargs[1].get("workspace_id") == "ws-42"
        )


# ===========================================================================
# GET /api/v1/pipeline/graphs/:id  (get)
# ===========================================================================


class TestGetGraph:
    """Tests for getting a single graph."""

    def test_get_existing(self, patched_store):
        graph = _mock_graph("graph-1")
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-1", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["id"] == "graph-1"

    def test_get_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/nonexistent", {}, http)
        assert _status(result) == 404

    def test_get_invalid_graph_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/<script>alert(1)</script>", {}, http)
        assert _status(result) == 400

    def test_get_path_traversal_rejected(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/../../etc/passwd", {}, http)
        assert _status(result) == 400


# ===========================================================================
# POST /api/v1/pipeline/graphs  (create)
# ===========================================================================


class TestCreateGraph:
    """Tests for creating a new graph."""

    def test_create_with_defaults(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        with patch("aragora.pipeline.universal_node.UniversalGraph") as MockGraph:
            mock_instance = MagicMock()
            mock_instance.to_dict.return_value = {"id": "graph-new", "name": "Untitled Pipeline"}
            MockGraph.return_value = mock_instance
            result = h.handle_post("/api/v1/pipeline/graphs", {}, http)
        assert _status(result) == 201

    def test_create_with_name(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        with patch("aragora.pipeline.universal_node.UniversalGraph") as MockGraph:
            mock_instance = MagicMock()
            mock_instance.to_dict.return_value = {"id": "graph-x", "name": "My Pipeline"}
            MockGraph.return_value = mock_instance
            result = h.handle_post(
                "/api/v1/pipeline/graphs",
                {"name": "My Pipeline", "owner_id": "user-1"},
                http,
            )
        assert _status(result) == 201
        patched_store.create.assert_called_once()

    def test_create_calls_store_create(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        with patch("aragora.pipeline.universal_node.UniversalGraph") as MockGraph:
            mock_instance = MagicMock()
            mock_instance.to_dict.return_value = {"id": "g"}
            MockGraph.return_value = mock_instance
            h.handle_post("/api/v1/pipeline/graphs", {}, http)
        patched_store.create.assert_called_once_with(
            mock_instance, org_id="test-org-001", created_by="test-user-001"
        )


# ===========================================================================
# PUT /api/v1/pipeline/graphs/:id  (update)
# ===========================================================================


class TestUpdateGraph:
    """Tests for updating a graph."""

    def test_update_name(self, patched_store):
        graph = _mock_graph("graph-1")
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put(
            "/api/v1/pipeline/graphs/graph-1",
            {"name": "Updated Name"},
            http,
        )
        assert _status(result) == 200
        assert graph.name == "Updated Name"
        patched_store.update.assert_called_once_with(graph)

    def test_update_metadata_merges(self, patched_store):
        graph = _mock_graph("graph-1")
        graph.metadata = {"existing": True}
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_put(
            "/api/v1/pipeline/graphs/graph-1",
            {"metadata": {"new_key": "val"}},
            http,
        )
        assert graph.metadata == {"existing": True, "new_key": "val"}

    def test_update_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put(
            "/api/v1/pipeline/graphs/nonexistent",
            {"name": "X"},
            http,
        )
        assert _status(result) == 404

    def test_update_invalid_graph_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put(
            "/api/v1/pipeline/graphs/<bad>",
            {"name": "X"},
            http,
        )
        assert _status(result) == 400

    def test_update_sets_updated_at(self, patched_store):
        graph = _mock_graph("graph-1")
        graph.updated_at = 0.0
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_put(
            "/api/v1/pipeline/graphs/graph-1",
            {"name": "New"},
            http,
        )
        # updated_at should have been set to a new timestamp
        assert graph.updated_at != 0.0


# ===========================================================================
# DELETE /api/v1/pipeline/graphs/:id  (delete)
# ===========================================================================


class TestDeleteGraph:
    """Tests for deleting a graph."""

    def test_delete_success(self, patched_store):
        patched_store.delete.return_value = True
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-1", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["deleted"] is True
        assert body["id"] == "graph-1"

    def test_delete_not_found(self, patched_store):
        patched_store.delete.return_value = False
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/nonexistent", {}, http)
        assert _status(result) == 404

    def test_delete_invalid_graph_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/<script>", {}, http)
        assert _status(result) == 400


# ===========================================================================
# POST /api/v1/pipeline/graphs/:id/nodes  (add node)
# ===========================================================================


class TestAddNode:
    """Tests for adding nodes to a graph."""

    def test_add_node_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-1/nodes",
            {"label": "New Node"},
            http,
        )
        assert _status(result) == 404

    def test_add_node_success(self, patched_store):
        graph = _mock_graph("graph-1")
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        with (
            patch("aragora.canvas.stages.PipelineStage") as MockStage,
            patch("aragora.pipeline.universal_node.UniversalNode") as MockNode,
        ):
            MockStage.return_value = "ideas"
            mock_node = MagicMock()
            mock_node.to_dict.return_value = {"id": "node-new", "label": "New Node"}
            MockNode.return_value = mock_node
            result = h.handle_post(
                "/api/v1/pipeline/graphs/graph-1/nodes",
                {"label": "New Node", "stage": "ideas"},
                http,
            )
        assert _status(result) == 201

    def test_add_node_invalid_stage(self, patched_store):
        graph = _mock_graph("graph-1")
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        with patch("aragora.canvas.stages.PipelineStage", side_effect=ValueError("bad")):
            result = h.handle_post(
                "/api/v1/pipeline/graphs/graph-1/nodes",
                {"stage": "invalid_stage"},
                http,
            )
        assert _status(result) == 400


# ===========================================================================
# DELETE /api/v1/pipeline/graphs/:id/nodes/:nid  (remove node)
# ===========================================================================


class TestRemoveNode:
    """Tests for removing nodes from a graph."""

    def test_remove_node_success(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-1/nodes/node-1", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["deleted"] is True
        assert body["node_id"] == "node-1"
        patched_store.remove_node.assert_called_once_with("graph-1", "node-1")

    def test_remove_node_invalid_node_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-1/nodes/<script>", {}, http)
        assert _status(result) == 400


# ===========================================================================
# GET /api/v1/pipeline/graphs/:id/nodes  (query nodes)
# ===========================================================================


class TestQueryNodes:
    """Tests for querying nodes in a graph."""

    def test_query_nodes_empty(self, patched_store):
        patched_store.query_nodes.return_value = []
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-1/nodes", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["nodes"] == []
        assert body["count"] == 0

    def test_query_nodes_with_results(self, patched_store):
        node = _mock_node("node-1")
        patched_store.query_nodes.return_value = [node]
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-1/nodes", {}, http)
        body = _body(result)
        assert body["count"] == 1

    def test_query_nodes_invalid_stage_filter(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        with patch("aragora.canvas.stages.PipelineStage", side_effect=ValueError("bad")):
            result = h.handle(
                "/api/v1/pipeline/graphs/graph-1/nodes",
                {"stage": "invalid_stage"},
                http,
            )
        assert _status(result) == 400


# ===========================================================================
# POST /api/v1/pipeline/graphs/:id/edges  (add edge)
# ===========================================================================


class TestAddEdge:
    """Tests for adding edges to a graph."""

    def test_add_edge_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-1/edges",
            {"source_id": "n1", "target_id": "n2"},
            http,
        )
        assert _status(result) == 404

    def test_add_edge_missing_source_node(self, patched_store):
        graph = _mock_graph("graph-1")
        graph.nodes = {"n2": _mock_node("n2")}  # n1 missing
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        with patch("aragora.canvas.stages.StageEdgeType"):
            result = h.handle_post(
                "/api/v1/pipeline/graphs/graph-1/edges",
                {"source_id": "n1", "target_id": "n2"},
                http,
            )
        assert _status(result) == 400

    def test_add_edge_invalid_edge_type(self, patched_store):
        graph = _mock_graph("graph-1")
        graph.nodes = {"n1": _mock_node("n1"), "n2": _mock_node("n2")}
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        with patch("aragora.canvas.stages.StageEdgeType", side_effect=ValueError("bad")):
            result = h.handle_post(
                "/api/v1/pipeline/graphs/graph-1/edges",
                {"source_id": "n1", "target_id": "n2", "edge_type": "invalid"},
                http,
            )
        assert _status(result) == 400


# ===========================================================================
# DELETE /api/v1/pipeline/graphs/:id/edges/:eid  (remove edge)
# ===========================================================================


class TestRemoveEdge:
    """Tests for removing edges from a graph."""

    def test_remove_edge_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-1/edges/edge-1", {}, http)
        assert _status(result) == 404

    def test_remove_edge_success(self, patched_store):
        graph = _mock_graph("graph-1")
        graph.remove_edge.return_value = MagicMock()  # non-None = success
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-1/edges/edge-1", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["deleted"] is True
        assert body["edge_id"] == "edge-1"

    def test_remove_edge_not_found(self, patched_store):
        graph = _mock_graph("graph-1")
        graph.remove_edge.return_value = None
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-1/edges/edge-1", {}, http)
        assert _status(result) == 404

    def test_remove_edge_invalid_edge_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-1/edges/<bad>", {}, http)
        assert _status(result) == 400


# ===========================================================================
# POST /api/v1/pipeline/graphs/:id/promote  (promote nodes)
# ===========================================================================


class TestPromoteNodes:
    """Tests for promoting nodes to a higher pipeline stage."""

    def test_promote_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-1/promote",
            {"node_ids": ["n1"], "target_stage": "goals"},
            http,
        )
        assert _status(result) == 404

    def test_promote_invalid_target_stage(self, patched_store):
        graph = _mock_graph("graph-1")
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        with patch("aragora.canvas.stages.PipelineStage", side_effect=ValueError("bad")):
            result = h.handle_post(
                "/api/v1/pipeline/graphs/graph-1/promote",
                {"node_ids": ["n1"], "target_stage": "invalid"},
                http,
            )
        assert _status(result) == 400

    def test_promote_empty_node_ids(self, patched_store):
        graph = _mock_graph("graph-1")
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        with patch("aragora.canvas.stages.PipelineStage") as MockStage:
            MockStage.return_value = MagicMock(value="goals")
            result = h.handle_post(
                "/api/v1/pipeline/graphs/graph-1/promote",
                {"node_ids": [], "target_stage": "goals"},
                http,
            )
        assert _status(result) == 400


# ===========================================================================
# GET /api/v1/pipeline/graphs/:id/provenance/:nid  (provenance chain)
# ===========================================================================


class TestProvenanceChain:
    """Tests for provenance chain retrieval."""

    def test_provenance_empty_chain(self, patched_store):
        patched_store.get_provenance_chain.return_value = []
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-1/provenance/node-1", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["chain"] == []
        assert body["depth"] == 0

    def test_provenance_with_chain(self, patched_store):
        node = _mock_node("node-1")
        patched_store.get_provenance_chain.return_value = [node]
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-1/provenance/node-1", {}, http)
        body = _body(result)
        assert body["depth"] == 1

    def test_provenance_invalid_node_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-1/provenance/<bad>", {}, http)
        assert _status(result) == 400


# ===========================================================================
# GET /api/v1/pipeline/graphs/:id/react-flow  (react flow export)
# ===========================================================================


class TestReactFlow:
    """Tests for React Flow export."""

    def test_react_flow_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-1/react-flow", {}, http)
        assert _status(result) == 404

    def test_react_flow_success(self, patched_store):
        graph = _mock_graph("graph-1")
        graph.to_react_flow.return_value = {"nodes": [], "edges": []}
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-1/react-flow", {}, http)
        assert _status(result) == 200

    def test_react_flow_invalid_stage_filter(self, patched_store):
        graph = _mock_graph("graph-1")
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        with patch("aragora.canvas.stages.PipelineStage", side_effect=ValueError("bad")):
            result = h.handle(
                "/api/v1/pipeline/graphs/graph-1/react-flow",
                {"stage": "invalid"},
                http,
            )
        assert _status(result) == 400


# ===========================================================================
# GET /api/v1/pipeline/graphs/:id/integrity  (integrity hash)
# ===========================================================================


class TestIntegrity:
    """Tests for graph integrity hash."""

    def test_integrity_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-1/integrity", {}, http)
        assert _status(result) == 404

    def test_integrity_success(self, patched_store):
        graph = _mock_graph("graph-1")
        graph.integrity_hash.return_value = "abc123hash"
        graph.nodes = {"n1": _mock_node("n1")}
        graph.edges = {"e1": MagicMock()}
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-1/integrity", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["graph_id"] == "graph-1"
        assert body["integrity_hash"] == "abc123hash"
        assert body["node_count"] == 1
        assert body["edge_count"] == 1


# ===========================================================================
# PATCH /api/v1/pipeline/graphs/:id/nodes/:node_id  (update node)
# ===========================================================================


class TestUpdateNode:
    """Tests for PATCH node property updates."""

    def test_update_label(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/nodes/node-1",
            {"label": "New Label"},
            http,
        )
        assert _status(result) == 200
        assert node.label == "New Label"
        patched_store.update.assert_called_once_with(graph)

    def test_update_position(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/nodes/node-1",
            {"position_x": 100.5, "position_y": 200.0},
            http,
        )
        assert _status(result) == 200
        assert node.position_x == 100.5
        assert node.position_y == 200.0

    def test_update_status(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/nodes/node-1",
            {"status": "completed"},
            http,
        )
        assert _status(result) == 200
        assert node.status == "completed"

    def test_update_description(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        h = _make_handler()
        http = _make_http_handler()
        h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/nodes/node-1",
            {"description": "Updated desc"},
            http,
        )
        assert node.description == "Updated desc"

    def test_update_confidence(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        h = _make_handler()
        http = _make_http_handler()
        h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/nodes/node-1",
            {"confidence": 0.95},
            http,
        )
        assert node.confidence == 0.95

    def test_update_data_merges(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        node.data = {"existing": True}
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        h = _make_handler()
        http = _make_http_handler()
        h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/nodes/node-1",
            {"data": {"new_key": "val"}},
            http,
        )
        assert node.data == {"existing": True, "new_key": "val"}

    def test_update_metadata_merges(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        node.metadata = {"tag": "a"}
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        h = _make_handler()
        http = _make_http_handler()
        h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/nodes/node-1",
            {"metadata": {"tag": "b"}},
            http,
        )
        assert node.metadata == {"tag": "b"}

    def test_update_multiple_fields(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/nodes/node-1",
            {"label": "New", "status": "done", "position_x": 50},
            http,
        )
        assert _status(result) == 200
        assert node.label == "New"
        assert node.status == "done"
        assert node.position_x == 50.0

    def test_update_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_patch(
            "/api/v1/pipeline/graphs/graph-nope/nodes/node-1",
            {"label": "X"},
            http,
        )
        assert _status(result) == 404

    def test_update_node_not_found(self, patched_store):
        graph = _mock_graph()
        graph.nodes = {}
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/nodes/node-missing",
            {"label": "X"},
            http,
        )
        assert _status(result) == 404

    def test_update_invalid_graph_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_patch(
            "/api/v1/pipeline/graphs/bad%20graph!@#/nodes/node-1",
            {"label": "X"},
            http,
        )
        assert _status(result) == 400

    def test_update_invalid_node_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/nodes/<script>",
            {"label": "X"},
            http,
        )
        assert _status(result) == 400

    def test_update_empty_body_no_changes(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        node.label = "Original"
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/nodes/node-1",
            {},
            http,
        )
        assert _status(result) == 200
        assert node.label == "Original"
        patched_store.update.assert_called_once()

    def test_update_persists_graph(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        h = _make_handler()
        http = _make_http_handler()
        h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/nodes/node-1",
            {"label": "Updated"},
            http,
        )
        patched_store.update.assert_called_once_with(graph)

    def test_patch_wrong_path_returns_none(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/edges/edge-1",
            {"label": "X"},
            http,
        )
        assert result is None

    def test_data_non_dict_ignored(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        node.data = {"existing": True}
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        h = _make_handler()
        http = _make_http_handler()
        h.handle_patch(
            "/api/v1/pipeline/graphs/graph-abc123/nodes/node-1",
            {"data": "not-a-dict"},
            http,
        )
        # Non-dict data should be ignored -- original data unchanged
        assert node.data == {"existing": True}


# ===========================================================================
# POST /api/v1/pipeline/graphs/:id/execute/:node_id  (execute node)
# ===========================================================================


class TestExecuteNode:
    """Tests for triggering debate execution on a node."""

    def test_execute_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post("/api/v1/pipeline/graphs/graph-nope/execute/node-1", {}, http)
        assert _status(result) == 404

    def test_execute_node_not_found(self, patched_store):
        graph = _mock_graph()
        graph.nodes = {}
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/execute/node-missing", {}, http
        )
        assert _status(result) == 404

    def test_execute_error_returns_500(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        h = _make_handler()
        http = _make_http_handler()
        with patch(
            "aragora.pipeline.dag_operations.DAGOperationsCoordinator",
            side_effect=RuntimeError("execution failed"),
        ):
            result = h.handle_post("/api/v1/pipeline/graphs/graph-abc123/execute/node-1", {}, http)
        assert _status(result) == 500

    def test_execute_success(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "Debate completed"
        mock_result.metadata = {"rounds": 3}

        mock_coord = MagicMock()

        import asyncio

        async def mock_debate(*a, **kw):
            return mock_result

        mock_coord.debate_node = mock_debate

        h = _make_handler()
        http = _make_http_handler()
        with patch(
            "aragora.pipeline.dag_operations.DAGOperationsCoordinator",
            return_value=mock_coord,
        ):
            result = h.handle_post(
                "/api/v1/pipeline/graphs/graph-abc123/execute/node-1",
                {"rounds": 3},
                http,
            )
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["message"] == "Debate completed"

    def test_execute_invalid_graph_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post("/api/v1/pipeline/graphs/../bad/execute/node-1", {}, http)
        assert _status(result) == 400

    def test_execute_invalid_node_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post("/api/v1/pipeline/graphs/graph-abc123/execute/<script>", {}, http)
        assert _status(result) == 400

    def test_execute_passes_agents_and_rounds(self, patched_store):
        graph = _mock_graph()
        node = _mock_node("node-1")
        graph.nodes = {"node-1": node}
        patched_store.get.return_value = graph

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "ok"
        mock_result.metadata = {}

        mock_coord = MagicMock()
        captured_kwargs = {}

        import asyncio

        async def mock_debate(node_id, agents=None, rounds=3):
            captured_kwargs["agents"] = agents
            captured_kwargs["rounds"] = rounds
            return mock_result

        mock_coord.debate_node = mock_debate

        h = _make_handler()
        http = _make_http_handler()
        with patch(
            "aragora.pipeline.dag_operations.DAGOperationsCoordinator",
            return_value=mock_coord,
        ):
            h.handle_post(
                "/api/v1/pipeline/graphs/graph-abc123/execute/node-1",
                {"agents": ["claude", "gpt4"], "rounds": 5},
                http,
            )

        assert captured_kwargs["agents"] == ["claude", "gpt4"]
        assert captured_kwargs["rounds"] == 5


# ===========================================================================
# Rate limiting
# ===========================================================================


class TestRateLimiting:
    """Tests for rate limit enforcement on graph endpoints."""

    def test_handle_get_rate_limited(self, patched_store):
        h = _make_handler()
        http = _make_http_handler(client_ip="10.0.0.1")
        with patch(
            "aragora.server.handlers.pipeline.universal_graph._graph_limiter.is_allowed",
            return_value=False,
        ):
            result = h.handle("/api/v1/pipeline/graphs", {}, http)
        assert _status(result) == 429

    def test_handle_post_rate_limited(self, patched_store):
        h = _make_handler()
        http = _make_http_handler(client_ip="10.0.0.2")
        with patch(
            "aragora.server.handlers.pipeline.universal_graph._graph_limiter.is_allowed",
            return_value=False,
        ):
            result = h.handle_post("/api/v1/pipeline/graphs", {}, http)
        assert _status(result) == 429


# ===========================================================================
# Routing edge cases
# ===========================================================================


class TestRoutingEdgeCases:
    """Tests for routing edge cases and unrecognized paths."""

    def test_handle_unrecognized_sub_resource(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-1/unknown", {}, http)
        assert result is None

    def test_handle_post_unrecognized_sub_resource(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post("/api/v1/pipeline/graphs/graph-1/unknown", {}, http)
        assert result is None

    def test_handle_delete_too_short(self, patched_store):
        """DELETE /api/v1/pipeline/graphs (no id) should return None."""
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs", {}, http)
        assert result is None

    def test_put_wrong_path_returns_none(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put("/api/v1/pipeline/graphs", {"name": "X"}, http)
        assert result is None


# ===========================================================================
# Constructor
# ===========================================================================


class TestConstructor:
    """Tests for handler initialization."""

    def test_default_ctx(self):
        h = UniversalGraphHandler()
        assert h.ctx == {}

    def test_custom_ctx(self):
        ctx = {"key": "value"}
        h = UniversalGraphHandler(ctx=ctx)
        assert h.ctx is ctx

    def test_none_ctx_defaults_to_empty(self):
        h = UniversalGraphHandler(ctx=None)
        assert h.ctx == {}


__all__ = []
