"""Org isolation of DAG operations (E5) and the universal graph routes.

Requests go through the handlers' public dispatch methods with a real graph
store and the real RBAC checker. Org A owns ``graph-a`` (two ideas joined by an
edge); org B owns ``graph-b``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.canvas.stages import PipelineStage, StageEdgeType
from aragora.pipeline.graph_store import GraphStore
from aragora.pipeline.universal_node import UniversalEdge, UniversalGraph, UniversalNode
from aragora.server.handlers.pipeline import universal_graph as graph_module
from aragora.server.handlers.pipeline.dag_operations import DAGOperationsHandler
from aragora.server.handlers.pipeline.universal_graph import UniversalGraphHandler

pytestmark = pytest.mark.no_auto_auth

USER_A = SimpleNamespace(is_authenticated=True, user_id="user-a", org_id="org-a", role="owner")
USER_B = SimpleNamespace(is_authenticated=True, user_id="user-b", org_id="org-b", role="owner")
ANONYMOUS = SimpleNamespace(is_authenticated=False, user_id=None, org_id=None, role=None)

GA, GB, MISSING = "graph-a", "graph-b", "graph-missing"
NOT_FOUND = {"error": "Graph not found", "code": "not_found"}

DAG_POSTS = [
    *(f"/nodes/idea-a1/{op}" for op in ("debate", "decompose", "prioritize", "assign-agents")),
    *(f"/nodes/idea-a1/{op}" for op in ("execute", "find-precedents")),
    "/cluster-ideas",
    "/auto-flow",
]
GRAPH_GETS = ["", "/nodes", "/react-flow", "/integrity", "/provenance/idea-a1"]
GRAPH_WRITES = [
    ("post", "/nodes", {"id": "idea-new", "stage": "ideas", "label": "B idea"}),
    ("post", "/edges", {"source_id": "idea-a1", "target_id": "idea-a2"}),
    ("post", "/promote", {"node_ids": ["idea-a1"], "target_stage": "goals"}),
    ("post", "/execute/idea-a1", {}),
    ("put", "", {"name": "renamed"}),
    ("patch", "/nodes/idea-a1", {"label": "renamed"}),
    ("delete", "/nodes/idea-a2", None),
    ("delete", "/edges/edge-a", None),
    ("delete", "", None),
]


class _Request:
    def __init__(self, caller: Any, body: dict[str, Any] | None = None) -> None:
        self.caller = caller
        self.client_address = ("127.0.0.1", 12345)
        self.headers: dict[str, str] = {}
        self.request = SimpleNamespace(body=json.dumps(body or {}).encode())


def _resolve(result: Any) -> Any:
    return asyncio.run(result) if inspect.isawaitable(result) else result


def _json(result: Any) -> Any:
    return json.loads(result.body)


@pytest.fixture(autouse=True)
def _identity():
    with patch(
        "aragora.billing.jwt_auth.extract_user_from_request",
        side_effect=lambda handler, user_store=None: handler.caller,
    ):
        yield


@pytest.fixture
def store(tmp_path):
    graphs = GraphStore(db_path=str(tmp_path / "graphs.db"))
    graph_a = UniversalGraph(id=GA, name="A graph")
    for node_id in ("idea-a1", "idea-a2"):
        graph_a.nodes[node_id] = UniversalNode(
            id=node_id, stage=PipelineStage.IDEAS, node_subtype="concept", label=node_id
        )
    graph_a.add_edge(
        UniversalEdge(
            id="edge-a",
            source_id="idea-a1",
            target_id="idea-a2",
            edge_type=StageEdgeType.RELATES_TO,
        )
    )
    graphs.create(graph_a, org_id="org-a", created_by="user-a")
    graph_b = UniversalGraph(id=GB, name="B graph")
    graph_b.nodes["idea-b1"] = UniversalNode(
        id="idea-b1", stage=PipelineStage.IDEAS, node_subtype="concept", label="B"
    )
    graphs.create(graph_b, org_id="org-b", created_by="user-b")

    graph_module._store = None
    graph_module._graph_limiter = graph_module.RateLimiter(requests_per_minute=600)
    with patch("aragora.pipeline.graph_store.get_graph_store", return_value=graphs):
        yield graphs
    graph_module._store = None


@pytest.fixture
def coordinator():
    outcome = SimpleNamespace(success=True, message="ok", created_nodes=[], metadata={})
    instance = MagicMock()
    for op in (
        "debate_node",
        "decompose_node",
        "prioritize_children",
        "assign_agents",
        "execute_node",
        "find_precedents",
        "cluster_ideas",
        "auto_flow",
    ):
        setattr(instance, op, AsyncMock(return_value=outcome))
    with patch("aragora.pipeline.dag_operations.DAGOperationsCoordinator") as cls:
        cls.return_value = instance
        yield cls


def _snapshot(store: GraphStore, graph_id: str) -> dict[str, Any]:
    graph = store.get(graph_id)
    assert graph is not None
    snapshot = graph.to_dict()
    snapshot.pop("updated_at", None)
    return snapshot


def _dag_get(caller: Any, graph_id: str = GA) -> Any:
    return _resolve(DAGOperationsHandler().handle(f"/api/v1/pipeline/dag/{graph_id}", {}, caller))


def _dag_post(caller: Any, suffix: str, graph_id: str = GA) -> Any:
    request = _Request(caller, {"ideas": ["one", "two"], "agents": ["claude"]})
    path = f"/api/v1/pipeline/dag/{graph_id}{suffix}"
    return _resolve(DAGOperationsHandler().handle_post(path, {}, request))


def _graph_call(method: str, caller: Any, suffix: str, body: Any, graph_id: str = GA) -> Any:
    handler = UniversalGraphHandler()
    path = f"/api/v1/pipeline/graphs/{graph_id}{suffix}"
    request = _Request(caller)
    if method in ("post", "put", "patch"):
        return getattr(handler, f"handle_{method}")(path, body or {}, request)
    if method == "delete":
        return handler.handle_delete(path, {}, request)
    return handler.handle(path, {}, request)


class TestDagOperations:
    def test_owner_reads_graph(self, store):
        result = _dag_get(_Request(USER_A))
        assert result.status_code == 200
        assert _json(result)["data"]["id"] == GA

    def test_other_org_read_matches_missing_graph(self, store):
        other, missing = _dag_get(_Request(USER_B)), _dag_get(_Request(USER_A), MISSING)
        assert (other.status_code, _json(other)) == (404, NOT_FOUND)
        assert (missing.status_code, _json(missing)) == (404, NOT_FOUND)

    def test_anonymous_read_needs_auth(self, store):
        assert _dag_get(_Request(ANONYMOUS)).status_code == 401

    @pytest.mark.parametrize("suffix", DAG_POSTS)
    def test_owner_runs_operation(self, store, coordinator, suffix):
        assert _dag_post(USER_A, suffix).status_code == 200
        coordinator.assert_called_once()

    @pytest.mark.parametrize("suffix", DAG_POSTS)
    def test_other_org_operation_is_hidden_and_inert(self, store, coordinator, suffix):
        before = _snapshot(store, GA)
        result = _dag_post(USER_B, suffix)
        assert (result.status_code, _json(result)) == (404, NOT_FOUND)
        coordinator.assert_not_called()
        assert _snapshot(store, GA) == before

    @pytest.mark.parametrize("suffix", DAG_POSTS)
    def test_anonymous_operation_needs_auth(self, store, coordinator, suffix):
        assert _dag_post(ANONYMOUS, suffix).status_code == 401
        coordinator.assert_not_called()

    def test_unknown_path_is_left_to_other_handlers(self, store):
        handler = DAGOperationsHandler()
        assert handler.handle("/api/v1/pipeline/dag/", {}, _Request(ANONYMOUS)) is None
        assert handler.handle_post("/api/v1/pipeline/dag/x/nope", {}, _Request(ANONYMOUS)) is None

    def test_checker_failure_denies_owner(self, store):
        with patch("aragora.rbac.checker.get_permission_checker", side_effect=RuntimeError):
            assert _dag_get(_Request(USER_A)).status_code == 403


class TestUniversalGraph:
    def test_list_shows_only_the_callers_org(self, store):
        handler = UniversalGraphHandler()
        for caller, expected in ((USER_A, [GA]), (USER_B, [GB])):
            result = handler.handle("/api/v1/pipeline/graphs", {}, _Request(caller))
            assert [g["id"] for g in _json(result)["graphs"]] == expected

    @pytest.mark.parametrize("suffix", GRAPH_GETS)
    def test_owner_reads(self, store, suffix):
        assert _graph_call("get", USER_A, suffix, None).status_code == 200

    @pytest.mark.parametrize("suffix", GRAPH_GETS)
    def test_other_org_read_matches_missing_graph(self, store, suffix):
        other = _graph_call("get", USER_B, suffix, None)
        missing = _graph_call("get", USER_A, suffix, None, graph_id=MISSING)
        assert (other.status_code, _json(other)) == (404, NOT_FOUND)
        assert (missing.status_code, _json(missing)) == (404, NOT_FOUND)

    @pytest.mark.parametrize(("method", "suffix", "body"), GRAPH_WRITES)
    def test_owner_writes(self, store, coordinator, method, suffix, body):
        result = _graph_call(method, USER_A, suffix, body)
        assert result.status_code in (200, 201)

    @pytest.mark.parametrize(("method", "suffix", "body"), GRAPH_WRITES)
    def test_other_org_write_is_hidden_and_inert(self, store, coordinator, method, suffix, body):
        before = _snapshot(store, GA)
        result = _graph_call(method, USER_B, suffix, body)
        assert (result.status_code, _json(result)) == (404, NOT_FOUND)
        assert _snapshot(store, GA) == before
        assert store.get_owner_org(GA) == "org-a"
        coordinator.assert_not_called()

    @pytest.mark.parametrize(
        ("method", "suffix", "body"), [("get", s, None) for s in GRAPH_GETS] + GRAPH_WRITES
    )
    def test_anonymous_needs_auth(self, store, coordinator, method, suffix, body):
        assert _graph_call(method, ANONYMOUS, suffix, body).status_code == 401
        coordinator.assert_not_called()

    def test_anonymous_list_and_create_need_auth(self, store):
        handler = UniversalGraphHandler()
        assert handler.handle("/api/v1/pipeline/graphs", {}, _Request(ANONYMOUS)).status_code == 401
        result = handler.handle_post("/api/v1/pipeline/graphs", {}, _Request(ANONYMOUS))
        assert result.status_code == 401

    def test_create_belongs_to_the_creators_org(self, store):
        handler = UniversalGraphHandler()
        result = handler.handle_post("/api/v1/pipeline/graphs", {"name": "B new"}, _Request(USER_B))
        assert result.status_code == 201
        graph_id = _json(result)["id"]
        assert store.get_owner_org(graph_id) == "org-b"
        assert _graph_call("get", USER_A, "", None, graph_id=graph_id).status_code == 404

    def test_create_cannot_reuse_another_orgs_graph_id(self, store):
        before = _snapshot(store, GA)
        result = UniversalGraphHandler().handle_post(
            "/api/v1/pipeline/graphs", {"id": GA, "name": "taken"}, _Request(USER_B)
        )
        assert result.status_code == 409
        assert _snapshot(store, GA) == before
        assert store.get_owner_org(GA) == "org-a"

    def test_add_node_cannot_reuse_another_orgs_node_id(self, store):
        result = _graph_call(
            "post", USER_B, "/nodes", {"id": "idea-a1", "label": "stolen"}, graph_id=GB
        )
        assert result.status_code == 409
        assert store.node_graph_id("idea-a1") == GA

    def test_checker_failure_denies_owner(self, store):
        with patch("aragora.rbac.checker.get_permission_checker", side_effect=RuntimeError):
            assert _graph_call("get", USER_A, "", None).status_code == 403
