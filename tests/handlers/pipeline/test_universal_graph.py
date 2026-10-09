"""Tests for the UniversalGraphHandler.

Covers all 14 endpoints:
  POST   /api/v1/pipeline/graphs              Create graph
  GET    /api/v1/pipeline/graphs              List graphs
  GET    /api/v1/pipeline/graphs/:id          Get graph
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

Also tests:
  - can_handle routing
  - Rate limiting
  - Permission checks (auth denial, unauthenticated)
  - Invalid path segment validation
  - Unrecognized sub-routes returning None
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.canvas.stages import PipelineStage, StageEdgeType
from aragora.pipeline.universal_node import UniversalEdge, UniversalGraph, UniversalNode
import aragora.server.handlers.pipeline.universal_graph as universal_graph_module
from aragora.server.handlers.pipeline.universal_graph import UniversalGraphHandler
from aragora.tenancy.record_scope import OrgScope

_SCOPE = OrgScope(org_id="test-org-001", user_id="test-user-001", role="admin")

# Patch targets -- lazy imports inside method bodies use these source modules
_GRAPH_CLS = "aragora.pipeline.universal_node.UniversalGraph"
_NODE_CLS = "aragora.pipeline.universal_node.UniversalNode"
_EDGE_CLS = "aragora.pipeline.universal_node.UniversalEdge"
_STAGE_CLS = "aragora.canvas.stages.PipelineStage"
_EDGE_TYPE_CLS = "aragora.canvas.stages.StageEdgeType"
_IDEAS_TO_GOALS = "aragora.pipeline.stage_transitions.ideas_to_goals"
_GOALS_TO_ACTIONS = "aragora.pipeline.stage_transitions.goals_to_actions"
_ACTIONS_TO_ORCH = "aragora.pipeline.stage_transitions.actions_to_orchestration"


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


# ---------------------------------------------------------------------------
# Mock graph objects
# ---------------------------------------------------------------------------


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
        "owner_id": "user-1",
        "workspace_id": "ws-1",
        "created_at": 1000.0,
        "updated_at": 1000.0,
    }
    graph.to_react_flow.return_value = {"nodes": [], "edges": []}
    graph.integrity_hash.return_value = "abcdef1234567890"
    graph.add_edge = MagicMock()
    graph.remove_edge = MagicMock(return_value=MagicMock())
    return graph


def _mock_node(node_id: str = "node-abc123"):
    """Create a mock UniversalNode."""
    node = MagicMock(spec=UniversalNode)
    node.id = node_id
    node.to_dict.return_value = {
        "id": node_id,
        "stage": "ideas",
        "node_subtype": "concept",
        "label": "Test Node",
    }
    return node


def _mock_edge(edge_id: str = "edge-abc123"):
    """Create a mock UniversalEdge."""
    edge = MagicMock(spec=UniversalEdge)
    edge.id = edge_id
    edge.to_dict.return_value = {
        "id": edge_id,
        "source_id": "node-1",
        "target_id": "node-2",
        "edge_type": "relates_to",
    }
    return edge


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
    """Bypass _check_permission on UniversalGraphHandler for all tests.

    Opt out with @pytest.mark.no_auto_auth to test auth behavior.
    """
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
# can_handle
# ===========================================================================


class TestCanHandle:
    """Tests for route matching."""

    def test_matches_versioned_path(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/pipeline/graphs") is True

    def test_matches_versioned_path_with_id(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/pipeline/graphs/abc123") is True

    def test_matches_versioned_path_with_sub(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/pipeline/graphs/abc/nodes") is True

    def test_no_match_different_prefix(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/debates") is False

    def test_startswith_match(self):
        h = _make_handler()
        # startswith means prefix matches work
        assert h.can_handle("/api/v1/pipeline/graphsXXX") is True

    def test_no_match_wrong_path(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/pipeline/other") is False


# ===========================================================================
# GET /api/v1/pipeline/graphs  (list)
# ===========================================================================


class TestListGraphs:
    """Tests for listing graphs."""

    def test_list_empty(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["graphs"] == []
        assert body["count"] == 0

    def test_list_with_results(self, patched_store):
        patched_store.list.return_value = [{"id": "g1"}, {"id": "g2"}]
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 2

    def test_list_with_owner_filter(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        h.handle("/api/v1/pipeline/graphs", {"owner_id": "user-1"}, http)
        patched_store.list.assert_called_once_with(
            owner_id="user-1", workspace_id=None, limit=50, org_id="test-org-001"
        )

    def test_list_with_workspace_filter(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        h.handle("/api/v1/pipeline/graphs", {"workspace_id": "ws-1"}, http)
        patched_store.list.assert_called_once_with(
            owner_id=None, workspace_id="ws-1", limit=50, org_id="test-org-001"
        )

    def test_list_with_custom_limit(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        h.handle("/api/v1/pipeline/graphs", {"limit": "10"}, http)
        patched_store.list.assert_called_once_with(
            owner_id=None, workspace_id=None, limit=10, org_id="test-org-001"
        )

    def test_list_with_all_filters(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        h.handle(
            "/api/v1/pipeline/graphs",
            {"owner_id": "u1", "workspace_id": "ws-2", "limit": "5"},
            http,
        )
        patched_store.list.assert_called_once_with(
            owner_id="u1", workspace_id="ws-2", limit=5, org_id="test-org-001"
        )


# ===========================================================================
# GET /api/v1/pipeline/graphs/:id  (get)
# ===========================================================================


class TestGetGraph:
    """Tests for getting a single graph."""

    def test_get_existing(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-abc123", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["id"] == "graph-abc123"

    def test_get_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-xyz", {}, http)
        assert _status(result) == 404

    def test_get_invalid_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/../../etc", {}, http)
        assert _status(result) == 400

    def test_get_calls_store_get(self, patched_store):
        graph = _mock_graph("myid")
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle("/api/v1/pipeline/graphs/myid", {}, http)
        patched_store.get.assert_called_with("myid")


# ===========================================================================
# POST /api/v1/pipeline/graphs  (create)
# ===========================================================================


class TestCreateGraph:
    """Tests for creating a graph."""

    def test_create_with_defaults(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post("/api/v1/pipeline/graphs", {}, http)
        assert _status(result) == 201
        patched_store.create.assert_called_once()

    def test_create_with_fields(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        body = {
            "id": "my-graph",
            "name": "My Pipeline",
            "owner_id": "user-1",
            "workspace_id": "ws-1",
            "metadata": {"tag": "test"},
        }
        result = h.handle_post("/api/v1/pipeline/graphs", body, http)
        assert _status(result) == 201
        body_out = _body(result)
        assert body_out["id"] == "my-graph"
        assert body_out["name"] == "My Pipeline"

    def test_create_calls_store(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        h.handle_post("/api/v1/pipeline/graphs", {"id": "g1"}, http)
        patched_store.create.assert_called_once()
        created = patched_store.create.call_args[0][0]
        assert created.id == "g1"

    def test_create_auto_generates_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post("/api/v1/pipeline/graphs", {}, http)
        body = _body(result)
        assert body["id"].startswith("graph-")

    def test_create_default_name(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post("/api/v1/pipeline/graphs", {}, http)
        body = _body(result)
        assert body["name"] == "Untitled Pipeline"

    def test_create_with_metadata(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs",
            {"metadata": {"env": "prod"}},
            http,
        )
        body = _body(result)
        assert body["metadata"] == {"env": "prod"}

    def test_create_metadata_defaults_to_empty(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post("/api/v1/pipeline/graphs", {"name": "Test"}, http)
        body = _body(result)
        assert body["metadata"] == {}

    def test_create_unrecognized_sub_returns_none(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post("/api/v1/pipeline/graphs/abc/unknown", {}, http)
        assert result is None


# ===========================================================================
# PUT /api/v1/pipeline/graphs/:id  (update)
# ===========================================================================


class TestUpdateGraph:
    """Tests for updating a graph."""

    def test_update_name(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put(
            "/api/v1/pipeline/graphs/graph-abc123",
            {"name": "Renamed"},
            http,
        )
        assert _status(result) == 200
        assert graph.name == "Renamed"

    def test_update_metadata_merges(self, patched_store):
        graph = _mock_graph()
        graph.metadata = {"existing": True}
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_put(
            "/api/v1/pipeline/graphs/graph-abc123",
            {"metadata": {"new_key": "val"}},
            http,
        )
        # metadata.update() merges new keys into existing dict
        assert graph.metadata == {"existing": True, "new_key": "val"}

    def test_update_owner_id(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_put(
            "/api/v1/pipeline/graphs/graph-abc123",
            {"owner_id": "new-owner"},
            http,
        )
        assert graph.owner_id == "new-owner"

    def test_update_workspace_id(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_put(
            "/api/v1/pipeline/graphs/graph-abc123",
            {"workspace_id": "new-ws"},
            http,
        )
        assert graph.workspace_id == "new-ws"

    def test_update_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put(
            "/api/v1/pipeline/graphs/graph-nope",
            {"name": "X"},
            http,
        )
        assert _status(result) == 404

    def test_update_calls_store_update(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_put(
            "/api/v1/pipeline/graphs/graph-abc123",
            {"name": "Updated"},
            http,
        )
        patched_store.update.assert_called_once_with(graph)

    def test_update_sets_updated_at(self, patched_store):
        graph = _mock_graph()
        graph.updated_at = 1000.0
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_put(
            "/api/v1/pipeline/graphs/graph-abc123",
            {"name": "New"},
            http,
        )
        assert graph.updated_at != 1000.0

    def test_update_invalid_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put(
            "/api/v1/pipeline/graphs/<script>",
            {"name": "X"},
            http,
        )
        assert _status(result) == 400

    def test_update_wrong_path_length_returns_none(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put(
            "/api/v1/pipeline/graphs/abc/extra",
            {"name": "X"},
            http,
        )
        assert result is None

    def test_update_empty_body_no_changes(self, patched_store):
        graph = _mock_graph()
        graph.name = "Original"
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_put("/api/v1/pipeline/graphs/graph-abc123", {}, http)
        assert graph.name == "Original"
        patched_store.update.assert_called_once()


# ===========================================================================
# DELETE /api/v1/pipeline/graphs/:id  (delete)
# ===========================================================================


class TestDeleteGraph:
    """Tests for deleting a graph."""

    def test_delete_success(self, patched_store):
        patched_store.delete.return_value = True
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-abc123", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["deleted"] is True
        assert body["id"] == "graph-abc123"

    def test_delete_not_found(self, patched_store):
        patched_store.delete.return_value = False
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-nope", {}, http)
        assert _status(result) == 404

    def test_delete_invalid_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/<script>", {}, http)
        assert _status(result) == 400

    def test_delete_calls_store(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        h.handle_delete("/api/v1/pipeline/graphs/myid", {}, http)
        patched_store.delete.assert_called_with("myid")


# ===========================================================================
# POST /api/v1/pipeline/graphs/:id/nodes  (add node)
# ===========================================================================


class TestAddNode:
    """Tests for adding a node to a graph."""

    def test_add_node_success(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        body = {
            "id": "node-1",
            "stage": "ideas",
            "node_subtype": "concept",
            "label": "My Idea",
        }
        result = h.handle_post("/api/v1/pipeline/graphs/graph-abc123/nodes", body, http)
        assert _status(result) == 201
        assert _body(result)["id"] == "node-1"

    def test_add_node_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-nope/nodes",
            {"stage": "ideas"},
            http,
        )
        assert _status(result) == 404

    def test_add_node_invalid_stage(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/nodes",
            {"stage": "nonsense"},
            http,
        )
        assert _status(result) == 400

    def test_add_node_default_stage(self, patched_store):
        """Default stage is 'ideas'."""
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post("/api/v1/pipeline/graphs/graph-abc123/nodes", {}, http)
        assert _status(result) == 201
        node = patched_store.add_node.call_args[0][1]
        assert node.stage == PipelineStage.IDEAS

    def test_add_node_calls_store(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_post(
            "/api/v1/pipeline/graphs/g1/nodes",
            {"id": "n1", "stage": "goals"},
            http,
        )
        patched_store.add_node.assert_called_once()
        call_args = patched_store.add_node.call_args
        assert call_args[0][0] == "g1"

    def test_add_node_position_conversion(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/nodes",
            {"position_x": "10", "position_y": "20"},
            http,
        )
        node = patched_store.add_node.call_args[0][1]
        assert node.position_x == 10.0
        assert node.position_y == 20.0

    def test_add_node_confidence_conversion(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/nodes",
            {"confidence": "0.85"},
            http,
        )
        node = patched_store.add_node.call_args[0][1]
        assert node.confidence == 0.85

    def test_add_node_status_and_data(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_post(
            "/api/v1/pipeline/graphs/g1/nodes",
            {"status": "completed", "data": {"key": "val"}, "metadata": {"m": 1}},
            http,
        )
        node = patched_store.add_node.call_args[0][1]
        assert node.status == "completed"
        assert node.data == {"key": "val"}
        assert node.metadata == {"m": 1}

    def test_add_node_auto_generates_id(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post("/api/v1/pipeline/graphs/graph-abc123/nodes", {}, http)
        body = _body(result)
        assert body["id"].startswith("node-")


# ===========================================================================
# DELETE /api/v1/pipeline/graphs/:id/nodes/:nid  (remove node)
# ===========================================================================


class TestRemoveNode:
    """Tests for removing a node from a graph."""

    def test_remove_node_success(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-abc123/nodes/node-1", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["deleted"] is True
        assert body["node_id"] == "node-1"

    def test_remove_node_calls_store(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        h.handle_delete("/api/v1/pipeline/graphs/graph-abc123/nodes/node-1", {}, http)
        patched_store.remove_node.assert_called_once_with("graph-abc123", "node-1")

    def test_remove_node_invalid_graph_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/../hack/nodes/node-1", {}, http)
        assert _status(result) == 400

    def test_remove_node_invalid_node_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-abc123/nodes/../../etc", {}, http)
        assert _status(result) == 400


# ===========================================================================
# GET /api/v1/pipeline/graphs/:id/nodes  (query)
# ===========================================================================


class TestQueryNodes:
    """Tests for querying nodes."""

    def test_query_no_filters(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-abc123/nodes", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["nodes"] == []
        assert body["count"] == 0

    def test_query_with_stage_filter(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        h.handle(
            "/api/v1/pipeline/graphs/graph-abc123/nodes",
            {"stage": "ideas"},
            http,
        )
        patched_store.query_nodes.assert_called_once_with(
            "graph-abc123", stage=PipelineStage.IDEAS, subtype=None
        )

    def test_query_with_subtype_filter(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        h.handle(
            "/api/v1/pipeline/graphs/graph-abc123/nodes",
            {"subtype": "concept"},
            http,
        )
        patched_store.query_nodes.assert_called_once_with(
            "graph-abc123", stage=None, subtype="concept"
        )

    def test_query_invalid_stage(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle(
            "/api/v1/pipeline/graphs/graph-abc123/nodes",
            {"stage": "nonsense"},
            http,
        )
        assert _status(result) == 400

    def test_query_returns_nodes(self, patched_store):
        n1 = _mock_node("n1")
        n2 = _mock_node("n2")
        patched_store.query_nodes.return_value = [n1, n2]
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-abc123/nodes", {}, http)
        body = _body(result)
        assert body["count"] == 2
        assert len(body["nodes"]) == 2

    def test_query_with_both_filters(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        h.handle(
            "/api/v1/pipeline/graphs/graph-abc123/nodes",
            {"stage": "goals", "subtype": "goal"},
            http,
        )
        patched_store.query_nodes.assert_called_once_with(
            "graph-abc123", stage=PipelineStage.GOALS, subtype="goal"
        )


# ===========================================================================
# POST /api/v1/pipeline/graphs/:id/edges  (add edge)
# ===========================================================================


class TestAddEdge:
    """Tests for adding an edge to a graph."""

    def _graph_with_nodes(self):
        graph = _mock_graph()
        graph.nodes = {"node-1": _mock_node("node-1"), "node-2": _mock_node("node-2")}
        return graph

    def test_add_edge_success(self, patched_store):
        graph = self._graph_with_nodes()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        body = {
            "source_id": "node-1",
            "target_id": "node-2",
            "edge_type": "relates_to",
        }
        result = h.handle_post("/api/v1/pipeline/graphs/graph-abc123/edges", body, http)
        assert _status(result) == 201

    def test_add_edge_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/edges",
            {"source_id": "n1", "target_id": "n2"},
            http,
        )
        assert _status(result) == 404

    def test_add_edge_invalid_edge_type(self, patched_store):
        graph = self._graph_with_nodes()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/edges",
            {"edge_type": "bogus_invalid_type", "source_id": "node-1", "target_id": "node-2"},
            http,
        )
        assert _status(result) == 400

    def test_add_edge_source_not_in_graph(self, patched_store):
        graph = _mock_graph()
        graph.nodes = {"node-2": _mock_node("node-2")}
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/edges",
            {"source_id": "node-1", "target_id": "node-2", "edge_type": "relates_to"},
            http,
        )
        assert _status(result) == 400
        assert "not found" in _body(result).get("error", "").lower()

    def test_add_edge_target_not_in_graph(self, patched_store):
        graph = _mock_graph()
        graph.nodes = {"node-1": _mock_node("node-1")}
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/edges",
            {"source_id": "node-1", "target_id": "node-99", "edge_type": "relates_to"},
            http,
        )
        assert _status(result) == 400

    def test_add_edge_persists(self, patched_store):
        graph = self._graph_with_nodes()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/edges",
            {"source_id": "node-1", "target_id": "node-2", "edge_type": "relates_to"},
            http,
        )
        graph.add_edge.assert_called_once()
        patched_store.update.assert_called_once_with(graph)

    def test_add_edge_weight_conversion(self, patched_store):
        graph = self._graph_with_nodes()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/edges",
            {
                "source_id": "node-1",
                "target_id": "node-2",
                "weight": "3.5",
                "edge_type": "relates_to",
            },
            http,
        )
        edge = graph.add_edge.call_args[0][0]
        assert edge.weight == 3.5

    def test_add_edge_default_edge_type(self, patched_store):
        graph = self._graph_with_nodes()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/g1/edges",
            {"source_id": "node-1", "target_id": "node-2"},
            http,
        )
        assert _status(result) == 201
        edge = graph.add_edge.call_args[0][0]
        assert edge.edge_type == StageEdgeType.RELATES_TO

    def test_add_edge_auto_generates_id(self, patched_store):
        graph = self._graph_with_nodes()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/g1/edges",
            {"source_id": "node-1", "target_id": "node-2", "edge_type": "relates_to"},
            http,
        )
        body = _body(result)
        assert body["id"].startswith("edge-")


# ===========================================================================
# DELETE /api/v1/pipeline/graphs/:id/edges/:eid  (remove edge)
# ===========================================================================


class TestRemoveEdge:
    """Tests for removing an edge from a graph."""

    def test_remove_edge_success(self, patched_store):
        graph = _mock_graph()
        graph.remove_edge.return_value = _mock_edge("edge-1")
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-abc123/edges/edge-1", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["deleted"] is True
        assert body["edge_id"] == "edge-1"

    def test_remove_edge_not_found(self, patched_store):
        graph = _mock_graph()
        graph.remove_edge.return_value = None
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-abc123/edges/edge-nope", {}, http)
        assert _status(result) == 404

    def test_remove_edge_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-abc123/edges/edge-1", {}, http)
        assert _status(result) == 404

    def test_remove_edge_persists(self, patched_store):
        graph = _mock_graph()
        graph.remove_edge.return_value = _mock_edge("edge-1")
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle_delete("/api/v1/pipeline/graphs/graph-abc123/edges/edge-1", {}, http)
        patched_store.update.assert_called_once_with(graph)

    def test_remove_edge_invalid_edge_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-abc123/edges/../hack", {}, http)
        assert _status(result) == 400

    def test_remove_edge_invalid_graph_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/../bad/edges/edge-1", {}, http)
        assert _status(result) == 400


# ===========================================================================
# POST /api/v1/pipeline/graphs/:id/promote  (promote nodes)
# ===========================================================================


class TestPromoteNodes:
    """Tests for promoting nodes to a new stage."""

    def test_promote_to_goals(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        body = {"node_ids": ["n1"], "target_stage": "goals"}
        created_node = _mock_node("promoted-1")
        with patch(_IDEAS_TO_GOALS, return_value=[created_node]):
            result = h.handle_post("/api/v1/pipeline/graphs/graph-abc123/promote", body, http)
        assert _status(result) == 200
        body_out = _body(result)
        assert body_out["count"] == 1
        assert body_out["target_stage"] == "goals"

    def test_promote_to_actions(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        body = {"node_ids": ["n1"], "target_stage": "actions"}
        created_node = _mock_node("action-1")
        with patch(_GOALS_TO_ACTIONS, return_value=[created_node]):
            result = h.handle_post("/api/v1/pipeline/graphs/graph-abc123/promote", body, http)
        assert _status(result) == 200
        assert _body(result)["count"] == 1

    def test_promote_to_orchestration(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        body = {"node_ids": ["n1"], "target_stage": "orchestration"}
        created_node = _mock_node("orch-1")
        with patch(_ACTIONS_TO_ORCH, return_value=[created_node]):
            result = h.handle_post("/api/v1/pipeline/graphs/graph-abc123/promote", body, http)
        assert _status(result) == 200
        assert _body(result)["target_stage"] == "orchestration"

    def test_promote_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-nope/promote",
            {"node_ids": ["n1"], "target_stage": "goals"},
            http,
        )
        assert _status(result) == 404

    def test_promote_invalid_target_stage(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/promote",
            {"node_ids": ["n1"], "target_stage": "bogus"},
            http,
        )
        assert _status(result) == 400

    def test_promote_empty_node_ids(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/promote",
            {"node_ids": [], "target_stage": "goals"},
            http,
        )
        assert _status(result) == 400
        assert "node_ids" in _body(result).get("error", "").lower()

    def test_promote_to_ideas_rejected(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/promote",
            {"node_ids": ["n1"], "target_stage": "ideas"},
            http,
        )
        assert _status(result) == 400
        assert "ideas" in _body(result).get("error", "").lower()

    def test_promote_persists_and_adds_nodes(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        n1 = _mock_node("p1")
        n2 = _mock_node("p2")
        with patch(_IDEAS_TO_GOALS, return_value=[n1, n2]):
            h.handle_post(
                "/api/v1/pipeline/graphs/graph-abc123/promote",
                {"node_ids": ["n1", "n2"], "target_stage": "goals"},
                http,
            )
        patched_store.update.assert_called_once_with(graph)
        assert patched_store.add_node.call_count == 2

    def test_promote_multiple_nodes(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        nodes = [_mock_node(f"p{i}") for i in range(3)]
        with patch(_IDEAS_TO_GOALS, return_value=nodes):
            result = h.handle_post(
                "/api/v1/pipeline/graphs/graph-abc123/promote",
                {"node_ids": ["a", "b", "c"], "target_stage": "goals"},
                http,
            )
        assert _body(result)["count"] == 3
        assert patched_store.add_node.call_count == 3

    def test_promote_missing_node_ids_key(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/graph-abc123/promote",
            {"target_stage": "goals"},
            http,
        )
        assert _status(result) == 400


# ===========================================================================
# GET /api/v1/pipeline/graphs/:id/provenance/:nid
# ===========================================================================


class TestProvenanceChain:
    """Tests for the provenance chain endpoint."""

    def test_provenance_chain(self, patched_store):
        n1 = _mock_node("n1")
        n2 = _mock_node("n2")
        patched_store.get_provenance_chain.return_value = [n1, n2]
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-abc123/provenance/node-1", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["depth"] == 2
        assert len(body["chain"]) == 2

    def test_provenance_empty(self, patched_store):
        patched_store.get_provenance_chain.return_value = []
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-abc123/provenance/node-1", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["depth"] == 0

    def test_provenance_invalid_node_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-abc123/provenance/../../etc", {}, http)
        assert _status(result) == 400

    def test_provenance_invalid_graph_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/../bad/provenance/node-1", {}, http)
        assert _status(result) == 400

    def test_provenance_calls_store(self, patched_store):
        patched_store.get_provenance_chain.return_value = []
        h = _make_handler()
        http = _make_http_handler()
        h.handle("/api/v1/pipeline/graphs/g1/provenance/n1", {}, http)
        patched_store.get_provenance_chain.assert_called_once_with("g1", "n1")


# ===========================================================================
# GET /api/v1/pipeline/graphs/:id/react-flow
# ===========================================================================


class TestReactFlow:
    """Tests for React Flow export."""

    def test_react_flow_no_filter(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-abc123/react-flow", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert "nodes" in body
        assert "edges" in body

    def test_react_flow_with_stage_filter(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle(
            "/api/v1/pipeline/graphs/graph-abc123/react-flow",
            {"stage": "ideas"},
            http,
        )
        assert _status(result) == 200
        graph.to_react_flow.assert_called_once_with(stage_filter=PipelineStage.IDEAS)

    def test_react_flow_invalid_stage(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle(
            "/api/v1/pipeline/graphs/graph-abc123/react-flow",
            {"stage": "nonsense"},
            http,
        )
        assert _status(result) == 400

    def test_react_flow_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-nope/react-flow", {}, http)
        assert _status(result) == 404

    def test_react_flow_no_stage_param_passes_none(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        h.handle("/api/v1/pipeline/graphs/graph-abc123/react-flow", {}, http)
        graph.to_react_flow.assert_called_once_with(stage_filter=None)


# ===========================================================================
# GET /api/v1/pipeline/graphs/:id/integrity
# ===========================================================================


class TestIntegrity:
    """Tests for the integrity hash endpoint."""

    def test_integrity_success(self, patched_store):
        graph = _mock_graph()
        graph.nodes = {"n1": _mock_node("n1"), "n2": _mock_node("n2")}
        graph.edges = {"e1": _mock_edge("e1")}
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-abc123/integrity", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["graph_id"] == "graph-abc123"
        assert body["integrity_hash"] == "abcdef1234567890"
        assert body["node_count"] == 2
        assert body["edge_count"] == 1

    def test_integrity_graph_not_found(self, patched_store):
        patched_store.get.return_value = None
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-nope/integrity", {}, http)
        assert _status(result) == 404

    def test_integrity_empty_graph(self, patched_store):
        graph = _mock_graph()
        graph.nodes = {}
        graph.edges = {}
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-abc123/integrity", {}, http)
        body = _body(result)
        assert body["node_count"] == 0
        assert body["edge_count"] == 0


# ===========================================================================
# Rate Limiting
# ===========================================================================


class TestRateLimiting:
    """Tests for rate limit enforcement."""

    def test_handle_rate_limited(self, patched_store):
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

    def test_handle_not_rate_limited(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs", {}, http)
        assert _status(result) == 200


# ===========================================================================
# Permission Checks
# ===========================================================================


class TestPermissionChecks:
    """Tests for RBAC permission enforcement on write operations."""

    @pytest.mark.no_auto_auth
    def test_post_auth_required(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        with patch.object(
            h,
            "_check_permission",
            return_value=(
                None,
                MagicMock(
                    status_code=401,
                    body=json.dumps({"error": "Authentication required"}).encode(),
                ),
            ),
        ):
            result = h.handle_post("/api/v1/pipeline/graphs", {}, http)
        assert _status(result) == 401

    @pytest.mark.no_auto_auth
    def test_post_permission_denied(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        with patch.object(
            h,
            "_check_permission",
            return_value=(
                None,
                MagicMock(
                    status_code=403,
                    body=json.dumps({"error": "Permission denied"}).encode(),
                ),
            ),
        ):
            result = h.handle_post("/api/v1/pipeline/graphs", {}, http)
        assert _status(result) == 403

    @pytest.mark.no_auto_auth
    def test_put_auth_required(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        with patch.object(
            h,
            "_check_permission",
            return_value=(
                None,
                MagicMock(
                    status_code=401,
                    body=json.dumps({"error": "Authentication required"}).encode(),
                ),
            ),
        ):
            result = h.handle_put("/api/v1/pipeline/graphs/graph-abc123", {}, http)
        assert _status(result) == 401

    @pytest.mark.no_auto_auth
    def test_delete_auth_required(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        with patch.object(
            h,
            "_check_permission",
            return_value=(
                None,
                MagicMock(
                    status_code=401,
                    body=json.dumps({"error": "Authentication required"}).encode(),
                ),
            ),
        ):
            result = h.handle_delete("/api/v1/pipeline/graphs/graph-abc123", {}, http)
        assert _status(result) == 401

    def test_permission_check_passes(self, patched_store):
        graph = _mock_graph()
        patched_store.get.return_value = graph
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put(
            "/api/v1/pipeline/graphs/graph-abc123",
            {"name": "OK"},
            http,
        )
        assert _status(result) == 200


# ===========================================================================
# Unrecognized / Edge Routing
# ===========================================================================


class TestRoutingEdgeCases:
    """Tests for unrecognized routes and routing edge cases."""

    def test_handle_unrecognized_sub_returns_none(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-abc123/unknown", {}, http)
        assert result is None

    def test_handle_too_short_path_returns_none(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline", {}, http)
        assert result is None

    def test_handle_delete_short_path_returns_none(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline", {}, http)
        assert result is None

    def test_handle_delete_nodes_no_node_id_returns_none(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-abc123/nodes", {}, http)
        assert result is None

    def test_handle_delete_edges_no_edge_id_returns_none(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-abc123/edges", {}, http)
        assert result is None

    def test_handle_provenance_missing_node_id_returns_none(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/graphs/graph-abc123/provenance", {}, http)
        assert result is None

    def test_handle_post_short_path_returns_none(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post("/api/v1/pipeline", {}, http)
        assert result is None

    def test_handle_post_invalid_graph_id(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_post("/api/v1/pipeline/graphs/../../bad/nodes", {}, http)
        assert _status(result) == 400

    def test_handle_delete_unrecognized_sub_returns_none(self, patched_store):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_delete("/api/v1/pipeline/graphs/graph-abc123/unknown/extra", {}, http)
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

    def test_routes_defined(self):
        assert UniversalGraphHandler.ROUTES == ["/api/v1/pipeline/graphs"]

    def test_none_ctx_defaults_to_empty(self):
        h = UniversalGraphHandler(ctx=None)
        assert h.ctx == {}


# ===========================================================================
# Store lazy loading
# ===========================================================================


class TestStoreLoading:
    """Tests for the lazy-loaded store singleton."""

    def test_store_lazy_loads(self):
        import aragora.server.handlers.pipeline.universal_graph as mod

        mod._store = None
        mock_s = MagicMock()
        with patch(
            "aragora.pipeline.graph_store.get_graph_store",
            return_value=mock_s,
        ):
            from aragora.server.handlers.pipeline.universal_graph import _get_store

            result = _get_store()
        assert result is mock_s

    def test_store_cached(self):
        import aragora.server.handlers.pipeline.universal_graph as mod

        mock_s = MagicMock()
        mod._store = mock_s
        from aragora.server.handlers.pipeline.universal_graph import _get_store

        result = _get_store()
        assert result is mock_s
