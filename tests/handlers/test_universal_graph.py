"""Tests for the UniversalGraphHandler REST endpoints.

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
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.pipeline.universal_graph import (
    UniversalGraphHandler,
    _get_store,
)
from aragora.tenancy.record_scope import OrgScope

_SCOPE = OrgScope(org_id="test-org-001", user_id="test-user-001", role="admin")
_real_check_permission = UniversalGraphHandler._check_permission


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    node_id: str = "n-1",
    stage: str = "ideas",
    subtype: str = "concept",
    label: str = "Test Node",
) -> MagicMock:
    node = MagicMock()
    node.id = node_id
    node.stage.value = stage
    node.node_subtype = subtype
    node.label = label
    node.to_dict.return_value = {
        "id": node_id,
        "stage": stage,
        "node_subtype": subtype,
        "label": label,
    }
    node.content_hash = "abc123"
    node.parent_ids = []
    return node


def _make_graph(
    graph_id: str = "g-1",
    name: str = "Test Graph",
    nodes: dict | None = None,
    edges: dict | None = None,
) -> MagicMock:
    graph = MagicMock()
    graph.id = graph_id
    graph.name = name
    graph.nodes = nodes or {}
    graph.edges = edges or {}
    graph.to_dict.return_value = {
        "id": graph_id,
        "name": name,
        "nodes": {k: v.to_dict() for k, v in (nodes or {}).items()},
        "edges": {},
    }
    graph.integrity_hash.return_value = "sha256-deadbeef"
    graph.to_react_flow.return_value = {"nodes": [], "edges": []}
    return graph


def _mock_handler() -> MagicMock:
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    return handler


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset the module-level lazy store between tests."""
    import aragora.server.handlers.pipeline.universal_graph as mod

    mod._store = None
    yield
    mod._store = None


@pytest.fixture(autouse=True)
def _bypass_rbac():
    """Authorize every request as test-org-001, which owns every graph."""
    with (
        patch.object(UniversalGraphHandler, "_check_permission", return_value=(_SCOPE, None)),
        patch("aragora.tenancy.pipeline_access.graph_owned", return_value=True),
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset rate limiter between tests."""
    import aragora.server.handlers.pipeline.universal_graph as mod

    mod._graph_limiter = type(mod._graph_limiter)(requests_per_minute=60)


# =========================================================================
# can_handle
# =========================================================================


class TestCanHandle:
    def test_matches_versioned_path(self):
        h = UniversalGraphHandler()
        assert h.can_handle("/api/v1/pipeline/graphs") is True

    def test_matches_versioned_subpath(self):
        h = UniversalGraphHandler()
        assert h.can_handle("/api/v1/pipeline/graphs/g-1/nodes") is True

    def test_rejects_unrelated_path(self):
        h = UniversalGraphHandler()
        assert h.can_handle("/api/v1/debates") is False

    def test_rejects_similar_prefix(self):
        h = UniversalGraphHandler()
        assert h.can_handle("/api/v1/pipeline/graph") is False  # singular


# =========================================================================
# GET /api/v1/pipeline/graphs (list)
# =========================================================================


class TestListGraphs:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_list_graphs_returns_array(self, mock_gs):
        store = MagicMock()
        store.list.return_value = [{"id": "g-1", "name": "A"}]
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle("/api/v1/pipeline/graphs", {}, _mock_handler())

        assert result is not None
        body = json.loads(result["body"])
        assert body["count"] == 1
        assert body["graphs"][0]["id"] == "g-1"

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_list_with_owner_filter(self, mock_gs):
        store = MagicMock()
        store.list.return_value = []
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        h.handle("/api/v1/pipeline/graphs", {"owner_id": "user-1"}, _mock_handler())

        store.list.assert_called_once_with(
            owner_id="user-1", workspace_id=None, limit=50, org_id="test-org-001"
        )

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_list_with_workspace_filter(self, mock_gs):
        store = MagicMock()
        store.list.return_value = []
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        h.handle("/api/v1/pipeline/graphs", {"workspace_id": "ws-1"}, _mock_handler())

        store.list.assert_called_once_with(
            owner_id=None, workspace_id="ws-1", limit=50, org_id="test-org-001"
        )

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_list_with_limit(self, mock_gs):
        store = MagicMock()
        store.list.return_value = []
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        h.handle("/api/v1/pipeline/graphs", {"limit": "10"}, _mock_handler())

        store.list.assert_called_once_with(
            owner_id=None, workspace_id=None, limit=10, org_id="test-org-001"
        )


# =========================================================================
# GET /api/v1/pipeline/graphs/:id (get)
# =========================================================================


class TestGetGraph:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_get_existing_graph(self, mock_gs):
        graph = _make_graph("g-1", "My Graph")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle("/api/v1/pipeline/graphs/g-1", {}, _mock_handler())

        assert result is not None
        body = json.loads(result["body"])
        assert body["id"] == "g-1"
        assert body["name"] == "My Graph"

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_get_missing_graph_returns_404(self, mock_gs):
        store = MagicMock()
        store.get.return_value = None
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle("/api/v1/pipeline/graphs/nonexistent", {}, _mock_handler())

        assert result is not None
        assert result["status"] == 404

    def test_get_with_invalid_id_returns_400(self):
        h = UniversalGraphHandler()
        result = h.handle("/api/v1/pipeline/graphs/../../etc/passwd", {}, _mock_handler())

        assert result is not None
        assert result["status"] == 400


# =========================================================================
# POST /api/v1/pipeline/graphs (create)
# =========================================================================


class TestCreateGraph:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_create_graph(self, mock_gs):
        store = MagicMock()
        store.get.return_value = None
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        body = {"id": "g-new", "name": "New Graph", "owner_id": "user-1"}
        result = h.handle_post("/api/v1/pipeline/graphs", body, _mock_handler())

        assert result is not None
        assert result["status"] == 201
        resp = json.loads(result["body"])
        assert resp["id"] == "g-new"
        assert resp["name"] == "New Graph"
        store.create.assert_called_once()

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_create_graph_auto_generates_id(self, mock_gs):
        store = MagicMock()
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_post("/api/v1/pipeline/graphs", {"name": "Auto"}, _mock_handler())

        assert result is not None
        assert result["status"] == 201
        resp = json.loads(result["body"])
        assert resp["id"].startswith("graph-")

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_create_graph_default_name(self, mock_gs):
        store = MagicMock()
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_post("/api/v1/pipeline/graphs", {}, _mock_handler())

        assert result is not None
        resp = json.loads(result["body"])
        assert resp["name"] == "Untitled Pipeline"


# =========================================================================
# PUT /api/v1/pipeline/graphs/:id (update)
# =========================================================================


class TestUpdateGraph:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_update_graph_name(self, mock_gs):
        graph = _make_graph("g-1", "Old Name")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_put("/api/v1/pipeline/graphs/g-1", {"name": "New Name"}, _mock_handler())

        assert result is not None
        assert graph.name == "New Name"
        store.update.assert_called_once_with(graph)

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_update_missing_graph_returns_404(self, mock_gs):
        store = MagicMock()
        store.get.return_value = None
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_put("/api/v1/pipeline/graphs/missing", {"name": "X"}, _mock_handler())

        assert result is not None
        assert result["status"] == 404

    def test_update_invalid_id_returns_none_or_400(self):
        """Path traversal IDs are either rejected (400) or don't match PUT route."""
        h = UniversalGraphHandler()
        # "../../bad" in path creates extra segments, so len(parts) != 5
        result = h.handle_put("/api/v1/pipeline/graphs/../../bad", {"name": "X"}, _mock_handler())
        # Returns None because len(parts) != 5 for PUT route
        assert result is None

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_update_metadata_merges(self, mock_gs):
        graph = _make_graph("g-1")
        graph.metadata = {"existing": "value"}
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        h.handle_put(
            "/api/v1/pipeline/graphs/g-1",
            {"metadata": {"new_key": "new_value"}},
            _mock_handler(),
        )

        # metadata.update() is called by the handler — verify the final state
        assert graph.metadata["new_key"] == "new_value"
        assert graph.metadata["existing"] == "value"

    def test_update_unmatched_path_returns_none(self):
        h = UniversalGraphHandler()
        result = h.handle_put("/api/v1/pipeline/graphs/g-1/extra", {}, _mock_handler())
        assert result is None


# =========================================================================
# DELETE /api/v1/pipeline/graphs/:id (delete)
# =========================================================================


class TestDeleteGraph:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_delete_graph(self, mock_gs):
        store = MagicMock()
        store.delete.return_value = True
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_delete("/api/v1/pipeline/graphs/g-1", {}, _mock_handler())

        assert result is not None
        body = json.loads(result["body"])
        assert body["deleted"] is True
        assert body["id"] == "g-1"

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_delete_missing_graph_returns_404(self, mock_gs):
        store = MagicMock()
        store.delete.return_value = False
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_delete("/api/v1/pipeline/graphs/missing", {}, _mock_handler())

        assert result is not None
        assert result["status"] == 404


# =========================================================================
# POST /api/v1/pipeline/graphs/:id/nodes (add node)
# =========================================================================


class TestAddNode:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_add_node(self, mock_gs):
        graph = _make_graph("g-1")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        body = {
            "id": "n-new",
            "stage": "ideas",
            "node_subtype": "concept",
            "label": "New Idea",
        }
        result = h.handle_post("/api/v1/pipeline/graphs/g-1/nodes", body, _mock_handler())

        assert result is not None
        assert result["status"] == 201
        resp = json.loads(result["body"])
        assert resp["id"] == "n-new"
        assert resp["label"] == "New Idea"

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_add_node_missing_graph_returns_404(self, mock_gs):
        store = MagicMock()
        store.get.return_value = None
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/missing/nodes", {"label": "X"}, _mock_handler()
        )

        assert result is not None
        assert result["status"] == 404

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_add_node_invalid_stage_returns_400(self, mock_gs):
        graph = _make_graph("g-1")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/g-1/nodes",
            {"stage": "invalid_stage"},
            _mock_handler(),
        )

        assert result is not None
        assert result["status"] == 400

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_add_node_auto_id(self, mock_gs):
        graph = _make_graph("g-1")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/g-1/nodes",
            {"label": "Auto ID"},
            _mock_handler(),
        )

        assert result is not None
        resp = json.loads(result["body"])
        assert resp["id"].startswith("node-")


# =========================================================================
# DELETE /api/v1/pipeline/graphs/:id/nodes/:nid (remove node)
# =========================================================================


class TestRemoveNode:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_remove_node(self, mock_gs):
        store = MagicMock()
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_delete("/api/v1/pipeline/graphs/g-1/nodes/n-1", {}, _mock_handler())

        assert result is not None
        body = json.loads(result["body"])
        assert body["deleted"] is True
        assert body["node_id"] == "n-1"
        store.remove_node.assert_called_once_with("g-1", "n-1")

    def test_remove_node_invalid_node_id_returns_400(self):
        h = UniversalGraphHandler()
        result = h.handle_delete("/api/v1/pipeline/graphs/g-1/nodes/../../bad", {}, _mock_handler())

        assert result is not None
        assert result["status"] == 400


# =========================================================================
# GET /api/v1/pipeline/graphs/:id/nodes (query)
# =========================================================================


class TestQueryNodes:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_query_nodes_no_filter(self, mock_gs):
        n1 = _make_node("n-1")
        store = MagicMock()
        store.query_nodes.return_value = [n1]
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle("/api/v1/pipeline/graphs/g-1/nodes", {}, _mock_handler())

        assert result is not None
        body = json.loads(result["body"])
        assert body["count"] == 1

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_query_nodes_with_stage_filter(self, mock_gs):
        store = MagicMock()
        store.query_nodes.return_value = []
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        h.handle("/api/v1/pipeline/graphs/g-1/nodes", {"stage": "goals"}, _mock_handler())

        call_args = store.query_nodes.call_args
        assert call_args[1]["stage"].value == "goals"

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_query_nodes_invalid_stage_returns_400(self, mock_gs):
        store = MagicMock()
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle("/api/v1/pipeline/graphs/g-1/nodes", {"stage": "bad"}, _mock_handler())

        assert result is not None
        assert result["status"] == 400

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_query_nodes_with_subtype_filter(self, mock_gs):
        store = MagicMock()
        store.query_nodes.return_value = []
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        h.handle(
            "/api/v1/pipeline/graphs/g-1/nodes",
            {"subtype": "concept"},
            _mock_handler(),
        )

        store.query_nodes.assert_called_once_with("g-1", stage=None, subtype="concept")


# =========================================================================
# POST /api/v1/pipeline/graphs/:id/edges (add edge)
# =========================================================================


class TestAddEdge:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_add_edge(self, mock_gs):
        n1 = _make_node("n-1")
        n2 = _make_node("n-2")
        graph = _make_graph("g-1", nodes={"n-1": n1, "n-2": n2})
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        body = {
            "id": "e-1",
            "source_id": "n-1",
            "target_id": "n-2",
            "edge_type": "supports",
        }
        result = h.handle_post("/api/v1/pipeline/graphs/g-1/edges", body, _mock_handler())

        assert result is not None
        assert result["status"] == 201
        resp = json.loads(result["body"])
        assert resp["id"] == "e-1"

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_add_edge_missing_graph_returns_404(self, mock_gs):
        store = MagicMock()
        store.get.return_value = None
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/missing/edges",
            {"source_id": "a", "target_id": "b"},
            _mock_handler(),
        )

        assert result is not None
        assert result["status"] == 404

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_add_edge_invalid_type_returns_400(self, mock_gs):
        n1 = _make_node("n-1")
        graph = _make_graph("g-1", nodes={"n-1": n1})
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/g-1/edges",
            {"source_id": "n-1", "target_id": "n-1", "edge_type": "bogus_type"},
            _mock_handler(),
        )

        assert result is not None
        assert result["status"] == 400

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_add_edge_missing_node_returns_400(self, mock_gs):
        graph = _make_graph("g-1", nodes={})
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_post(
            "/api/v1/pipeline/graphs/g-1/edges",
            {"source_id": "n-1", "target_id": "n-2"},
            _mock_handler(),
        )

        assert result is not None
        assert result["status"] == 400


# =========================================================================
# DELETE /api/v1/pipeline/graphs/:id/edges/:eid (remove edge)
# =========================================================================


class TestRemoveEdge:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_remove_edge(self, mock_gs):
        graph = _make_graph("g-1")
        graph.remove_edge.return_value = MagicMock()
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_delete("/api/v1/pipeline/graphs/g-1/edges/e-1", {}, _mock_handler())

        assert result is not None
        body = json.loads(result["body"])
        assert body["deleted"] is True
        assert body["edge_id"] == "e-1"

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_remove_edge_missing_graph_returns_404(self, mock_gs):
        store = MagicMock()
        store.get.return_value = None
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_delete("/api/v1/pipeline/graphs/missing/edges/e-1", {}, _mock_handler())

        assert result is not None
        assert result["status"] == 404

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_remove_edge_not_found_returns_404(self, mock_gs):
        graph = _make_graph("g-1")
        graph.remove_edge.return_value = None
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_delete(
            "/api/v1/pipeline/graphs/g-1/edges/nonexistent", {}, _mock_handler()
        )

        assert result is not None
        assert result["status"] == 404

    def test_remove_edge_invalid_id_returns_400(self):
        h = UniversalGraphHandler()
        result = h.handle_delete("/api/v1/pipeline/graphs/g-1/edges/../../bad", {}, _mock_handler())

        assert result is not None
        assert result["status"] == 400


# =========================================================================
# POST /api/v1/pipeline/graphs/:id/promote (promote nodes)
# =========================================================================


class TestPromote:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    @patch("aragora.pipeline.stage_transitions.ideas_to_goals")
    def test_promote_ideas_to_goals(self, mock_itg, mock_gs):
        graph = _make_graph("g-1")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        created_node = _make_node("goal-1", stage="goals", subtype="goal")
        mock_itg.return_value = [created_node]

        h = UniversalGraphHandler()
        body = {"node_ids": ["n-1"], "target_stage": "goals"}
        result = h.handle_post("/api/v1/pipeline/graphs/g-1/promote", body, _mock_handler())

        assert result is not None
        resp = json.loads(result["body"])
        assert resp["count"] == 1
        assert resp["target_stage"] == "goals"
        mock_itg.assert_called_once_with(graph, ["n-1"])

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    @patch("aragora.pipeline.stage_transitions.goals_to_actions")
    def test_promote_goals_to_actions(self, mock_gta, mock_gs):
        graph = _make_graph("g-1")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store
        mock_gta.return_value = []

        h = UniversalGraphHandler()
        body = {"node_ids": ["g-1"], "target_stage": "actions"}
        result = h.handle_post("/api/v1/pipeline/graphs/g-1/promote", body, _mock_handler())

        assert result is not None
        resp = json.loads(result["body"])
        assert resp["target_stage"] == "actions"

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    @patch("aragora.pipeline.stage_transitions.actions_to_orchestration")
    def test_promote_actions_to_orchestration(self, mock_ato, mock_gs):
        graph = _make_graph("g-1")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store
        mock_ato.return_value = []

        h = UniversalGraphHandler()
        body = {"node_ids": ["a-1"], "target_stage": "orchestration"}
        result = h.handle_post("/api/v1/pipeline/graphs/g-1/promote", body, _mock_handler())

        assert result is not None
        resp = json.loads(result["body"])
        assert resp["target_stage"] == "orchestration"

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_promote_missing_graph_returns_404(self, mock_gs):
        store = MagicMock()
        store.get.return_value = None
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        body = {"node_ids": ["n-1"], "target_stage": "goals"}
        result = h.handle_post("/api/v1/pipeline/graphs/missing/promote", body, _mock_handler())

        assert result is not None
        assert result["status"] == 404

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_promote_invalid_stage_returns_400(self, mock_gs):
        graph = _make_graph("g-1")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        body = {"node_ids": ["n-1"], "target_stage": "bogus"}
        result = h.handle_post("/api/v1/pipeline/graphs/g-1/promote", body, _mock_handler())

        assert result is not None
        assert result["status"] == 400

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_promote_empty_node_ids_returns_400(self, mock_gs):
        graph = _make_graph("g-1")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        body = {"node_ids": [], "target_stage": "goals"}
        result = h.handle_post("/api/v1/pipeline/graphs/g-1/promote", body, _mock_handler())

        assert result is not None
        assert result["status"] == 400

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_promote_to_ideas_returns_400(self, mock_gs):
        graph = _make_graph("g-1")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        body = {"node_ids": ["n-1"], "target_stage": "ideas"}
        result = h.handle_post("/api/v1/pipeline/graphs/g-1/promote", body, _mock_handler())

        assert result is not None
        assert result["status"] == 400


# =========================================================================
# GET /api/v1/pipeline/graphs/:id/provenance/:nid
# =========================================================================


class TestProvenance:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_provenance_chain(self, mock_gs):
        n1 = _make_node("n-1")
        n2 = _make_node("n-2")
        store = MagicMock()
        store.get_provenance_chain.return_value = [n1, n2]
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle("/api/v1/pipeline/graphs/g-1/provenance/n-1", {}, _mock_handler())

        assert result is not None
        body = json.loads(result["body"])
        assert body["depth"] == 2
        assert len(body["chain"]) == 2

    def test_provenance_invalid_node_id_returns_400(self):
        h = UniversalGraphHandler()
        result = h.handle("/api/v1/pipeline/graphs/g-1/provenance/../../bad", {}, _mock_handler())

        assert result is not None
        assert result["status"] == 400


# =========================================================================
# GET /api/v1/pipeline/graphs/:id/react-flow
# =========================================================================


class TestReactFlow:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_react_flow_export(self, mock_gs):
        graph = _make_graph("g-1")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle("/api/v1/pipeline/graphs/g-1/react-flow", {}, _mock_handler())

        assert result is not None
        body = json.loads(result["body"])
        assert "nodes" in body
        assert "edges" in body

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_react_flow_missing_graph_returns_404(self, mock_gs):
        store = MagicMock()
        store.get.return_value = None
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle("/api/v1/pipeline/graphs/missing/react-flow", {}, _mock_handler())

        assert result is not None
        assert result["status"] == 404

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_react_flow_with_stage_filter(self, mock_gs):
        graph = _make_graph("g-1")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        h.handle(
            "/api/v1/pipeline/graphs/g-1/react-flow",
            {"stage": "goals"},
            _mock_handler(),
        )

        call_args = graph.to_react_flow.call_args
        assert call_args[1]["stage_filter"].value == "goals"

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_react_flow_invalid_stage_returns_400(self, mock_gs):
        graph = _make_graph("g-1")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle(
            "/api/v1/pipeline/graphs/g-1/react-flow",
            {"stage": "invalid"},
            _mock_handler(),
        )

        assert result is not None
        assert result["status"] == 400


# =========================================================================
# GET /api/v1/pipeline/graphs/:id/integrity
# =========================================================================


class TestIntegrity:
    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_integrity_hash(self, mock_gs):
        graph = _make_graph("g-1")
        store = MagicMock()
        store.get.return_value = graph
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle("/api/v1/pipeline/graphs/g-1/integrity", {}, _mock_handler())

        assert result is not None
        body = json.loads(result["body"])
        assert body["graph_id"] == "g-1"
        assert body["integrity_hash"] == "sha256-deadbeef"
        assert body["node_count"] == 0
        assert body["edge_count"] == 0

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_integrity_missing_graph_returns_404(self, mock_gs):
        store = MagicMock()
        store.get.return_value = None
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle("/api/v1/pipeline/graphs/missing/integrity", {}, _mock_handler())

        assert result is not None
        assert result["status"] == 404


# =========================================================================
# Rate limiting
# =========================================================================


class TestRateLimiting:
    def test_get_rate_limit_exceeded(self):
        import aragora.server.handlers.pipeline.universal_graph as mod

        mod._graph_limiter = MagicMock()
        mod._graph_limiter.is_allowed.return_value = False

        h = UniversalGraphHandler()
        result = h.handle("/api/v1/pipeline/graphs", {}, _mock_handler())

        assert result is not None
        assert result["status"] == 429

    def test_post_rate_limit_exceeded(self):
        import aragora.server.handlers.pipeline.universal_graph as mod

        mod._graph_limiter = MagicMock()
        mod._graph_limiter.is_allowed.return_value = False

        h = UniversalGraphHandler()
        result = h.handle_post("/api/v1/pipeline/graphs", {}, _mock_handler())

        assert result is not None
        assert result["status"] == 429


# =========================================================================
# Unmatched routes return None
# =========================================================================


class TestUnmatchedRoutes:
    def test_handle_unmatched_returns_none(self):
        h = UniversalGraphHandler()
        result = h.handle("/api/v1/other/path", {}, _mock_handler())
        assert result is None

    def test_handle_post_unmatched_returns_none(self):
        h = UniversalGraphHandler()
        result = h.handle_post("/api/v1/other/path", {}, _mock_handler())
        assert result is None

    def test_handle_delete_unmatched_returns_none(self):
        h = UniversalGraphHandler()
        result = h.handle_delete("/api/v1/other/path", {}, _mock_handler())
        assert result is None

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_handle_post_graph_id_no_sub_returns_none(self, mock_gs):
        store = MagicMock()
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_post("/api/v1/pipeline/graphs/g-1", {}, _mock_handler())
        assert result is None

    @patch("aragora.server.handlers.pipeline.universal_graph._get_store")
    def test_handle_post_unknown_sub_returns_none(self, mock_gs):
        store = MagicMock()
        mock_gs.return_value = store

        h = UniversalGraphHandler()
        result = h.handle_post("/api/v1/pipeline/graphs/g-1/unknown", {}, _mock_handler())
        assert result is None


# =========================================================================
# RBAC permission checks
# =========================================================================


class TestRBACPermissions:
    def test_create_checks_canvas_create(self):
        h = UniversalGraphHandler()
        denial = {"status": 403, "body": "{}"}
        with patch.object(h, "_check_permission", return_value=(None, denial)) as mock_check:
            handler = _mock_handler()
            result = h.handle_post("/api/v1/pipeline/graphs", {}, handler)
            assert result["status"] == 403
            mock_check.assert_called_once_with(handler, "canvas:create")

    def test_put_checks_canvas_update(self):
        h = UniversalGraphHandler()
        denial = {"status": 403, "body": "{}"}
        with patch.object(h, "_check_permission", return_value=(None, denial)) as mock_check:
            handler = _mock_handler()
            result = h.handle_put("/api/v1/pipeline/graphs/g-1", {}, handler)
            assert result["status"] == 403
            mock_check.assert_called_once_with(handler, "canvas:update")

    def test_delete_checks_canvas_delete(self):
        h = UniversalGraphHandler()
        denial = {"status": 403, "body": "{}"}
        with patch.object(h, "_check_permission", return_value=(None, denial)) as mock_check:
            handler = _mock_handler()
            result = h.handle_delete("/api/v1/pipeline/graphs/g-1", {}, handler)
            assert result["status"] == 403
            mock_check.assert_called_once_with(handler, "canvas:delete")

    def test_check_permission_checker_failure_denies(self, monkeypatch):
        """When the permission checker is unavailable, access is denied."""
        from aragora.billing.auth.context import UserAuthContext

        user = UserAuthContext(
            authenticated=True,
            user_id="test-user-001",
            org_id="test-org-001",
            role="admin",
            token_type="access",
        )
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda handler, user_store=None: user,
        )
        with patch(
            "aragora.rbac.checker.get_permission_checker", side_effect=ImportError("no module")
        ):
            scope, denial = _real_check_permission(_mock_handler(), "canvas:update")
        assert scope is None
        assert denial.status_code == 403
