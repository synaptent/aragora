"""Graph debates belong to the org that created them.

``GraphDebatesHandler`` stamps the creator's org and user on every graph debate
it stores and shows a caller only its own org's graph debates; another org's
debate, one with no recorded org and a missing id all get the same 404.
Callers without a user get 401 and users without an org get 403 on every
route, before any debate runs or any record is read.
"""

from __future__ import annotations

import inspect
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from aragora.server.handlers.debates import graph_debates
from aragora.server.handlers.debates.graph_debates import GraphDebatesHandler
from tests.server.handlers.debates.write_isolation.support import (
    ANON,
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    USER_NO_ORG,
    Request,
    act_as,
    body_of,
    route,
    text_of,
)

GRAPH_NOT_FOUND = {"error": "Graph debate not found", "code": "not_found"}
TASK = "Should graph debates stay inside their org?"
GA, GB, GN, GX = "graph-alpha-a", "graph-bravo-b", "graph-null-org", "graph-missing-x"
# Indirect ``server`` parameter: the static API token the server is configured with.
SERVER_TOKEN = "rbac-route-rules-static-token"


def graph_record(debate_id: str, org_id: str | None, created_by: str | None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "debate_id": debate_id,
        "task": f"{TASK} ({debate_id})",
        "created_at": "2026-10-01T12:00:00+00:00",
        "graph": {
            "nodes": {"n1": {"id": "n1", "content": f"{debate_id} root"}},
            "branches": {"main": {"id": "main", "name": "main"}},
        },
    }
    if org_id is not None:
        record.update(org_id=org_id, created_by=created_by)
    return record


@pytest.fixture(autouse=True)
def _clean_graph_cache():
    graph_debates._graph_debate_cache.clear()
    yield
    graph_debates._graph_debate_cache.clear()


@pytest.fixture(autouse=True)
def _no_graph_limiter(monkeypatch):
    monkeypatch.setattr(graph_debates, "_graph_limiter", SimpleNamespace(is_allowed=lambda k: True))


@pytest.fixture
def orchestrators(monkeypatch):
    """Fake orchestrator and agents; returns the list of orchestrator constructions."""
    constructed: list[dict[str, Any]] = []

    class FakeGraph:
        def __init__(self) -> None:
            self.nodes = {"n1": SimpleNamespace(id="n1")}
            self.branches = {"main": SimpleNamespace(to_dict=lambda: {"id": "main"})}
            self.merge_history: list[Any] = []

        def to_dict(self) -> dict[str, Any]:
            return {"nodes": {"n1": {"id": "n1"}}, "branches": {"main": {"id": "main"}}}

    class FakeOrchestrator:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            constructed.append(kwargs)

        async def run_debate(self, **kwargs: Any) -> FakeGraph:
            return FakeGraph()

    async def fake_agents(self, *args: Any, **kwargs: Any) -> list[Any]:
        return [SimpleNamespace(name="claude"), SimpleNamespace(name="openai")]

    monkeypatch.setattr("aragora.debate.graph.GraphDebateOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(GraphDebatesHandler, "_load_agents", fake_agents)
    return constructed


class GraphStorage:
    """Duck-typed graph storage holding a debate of org A, one of org B and one without org."""

    def __init__(self) -> None:
        self.records = {
            GA: graph_record(GA, ORG_A, USER_A.user_id),
            GB: graph_record(GB, ORG_B, USER_B.user_id),
            GN: graph_record(GN, None, None),
        }
        self.reads: list[tuple[str, str]] = []
        self.saved: list[dict[str, Any]] = []

    def list_graph_debates(self, limit: int = 20) -> list[dict[str, Any]]:
        return [deepcopy(r) for r in self.records.values()][:limit]

    def get_graph_debate(self, debate_id: str) -> dict[str, Any] | None:
        record = self.records.get(debate_id)
        return deepcopy(record) if record is not None else None

    def get_debate_branches(self, debate_id: str) -> list[dict[str, Any]]:
        self.reads.append(("branches", debate_id))
        return [{"id": "main"}]

    def get_debate_nodes(self, debate_id: str) -> list[dict[str, Any]]:
        self.reads.append(("nodes", debate_id))
        return [{"id": "n1"}]

    def save_graph_debate(self, debate: dict[str, Any]) -> None:
        self.saved.append(deepcopy(debate))


@pytest.fixture
def graph(monkeypatch):
    """``graph(user, method, path, body=None, storage=None)`` runs ``GraphDebatesHandler``."""
    handler = GraphDebatesHandler(ctx={})

    async def _send(user: Any, method: str, path: str, body: Any = None, storage: Any = None):
        act_as(monkeypatch, user)
        request = Request(method, user, body)
        request.storage = storage
        result = route(handler, method, path, request)
        return await result if inspect.isawaitable(result) else result

    return _send


def _graph_body() -> dict[str, Any]:
    return {"task": TASK, "agents": ["claude", "openai"], "max_rounds": 1}


def _graph_get_paths(debate_id: str) -> list[str]:
    return [
        f"/api/v1/debates/graph/{debate_id}",
        f"/api/v1/debates/graph/{debate_id}/branches",
        f"/api/v1/debates/graph/{debate_id}/nodes",
        f"/api/v1/graph-debates/{debate_id}",
    ]


class TestGraphDebates:
    async def test_created_debate_records_the_creator_and_stays_in_its_org(
        self, graph, orchestrators
    ):
        storage = SimpleNamespace(saved=[])
        storage.save_graph_debate = storage.saved.append

        created = await graph(USER_A, "POST", "/api/v1/debates/graph", _graph_body(), storage)
        assert created.status_code == 200, text_of(created)
        assert len(orchestrators) == 1
        debate_id = body_of(created)["debate_id"]

        cached = graph_debates._graph_debate_cache[debate_id]
        assert (cached["org_id"], cached["created_by"]) == (ORG_A, USER_A.user_id)
        [saved] = storage.saved
        assert (saved["org_id"], saved["created_by"]) == (ORG_A, USER_A.user_id)

        listed_a = body_of(await graph(USER_A, "GET", "/api/v1/debates/graph"))
        assert [d["debate_id"] for d in listed_a["debates"]] == [debate_id]
        listed_b = body_of(await graph(USER_B, "GET", "/api/v1/graph-debates"))
        assert listed_b["debates"] == []

        for path in _graph_get_paths(debate_id):
            own = await graph(USER_A, "GET", path)
            assert own.status_code == 200, (path, text_of(own))
            refused = await graph(USER_B, "GET", path)
            assert (refused.status_code, body_of(refused)) == (404, GRAPH_NOT_FOUND), path

    async def test_only_get_and_head_reach_the_read_routes(self, graph):
        storage = GraphStorage()
        path = f"/api/v1/graph-debates/{GA}"
        head = await graph(USER_A, "HEAD", path, storage=storage)
        assert (head.status_code, body_of(head)["debate_id"]) == (200, GA), text_of(head)
        records = deepcopy(storage.records)

        for method in ("DELETE", "PUT", "PATCH"):
            assert await graph(USER_A, method, path, {"task": "x"}, storage) is None, method
        assert storage.records == records
        assert storage.saved == []

    async def test_other_org_unknown_owner_and_missing_debates_get_one_404(self, graph):
        graph_debates._remember_graph_debate(graph_record(GA, ORG_A, USER_A.user_id))
        graph_debates._remember_graph_debate(graph_record(GN, None, None))

        for debate_id in (GA, GN, GX):
            for path in _graph_get_paths(debate_id):
                result = await graph(USER_B, "GET", path)
                assert (result.status_code, body_of(result)) == (404, GRAPH_NOT_FOUND), path

    async def test_storage_records_are_filtered_by_org(self, graph):
        storage = GraphStorage()

        listed = body_of(await graph(USER_A, "GET", "/api/v1/debates/graph", storage=storage))
        assert [d["debate_id"] for d in listed["debates"]] == [GA]

        for debate_id in (GB, GN, GX):
            for path in _graph_get_paths(debate_id):
                result = await graph(USER_A, "GET", path, storage=storage)
                assert (result.status_code, body_of(result)) == (404, GRAPH_NOT_FOUND), path
        assert storage.reads == []

        for path in _graph_get_paths(GA):
            result = await graph(USER_A, "GET", path, storage=storage)
            assert result.status_code == 200, (path, text_of(result))
        assert storage.reads == [("branches", GA), ("nodes", GA)]

    @pytest.mark.parametrize(
        ("user", "status", "code"),
        [(ANON, 401, "auth_required"), (USER_NO_ORG, 403, "org_required")],
    )
    async def test_callers_without_an_org_are_refused_before_any_work(
        self, graph, orchestrators, user, status, code
    ):
        graph_debates._remember_graph_debate(graph_record(GA, ORG_A, USER_A.user_id))
        storage = GraphStorage()
        calls = [("GET", p, None) for p in _graph_get_paths(GA)]
        calls += [
            ("GET", "/api/v1/debates/graph", None),
            ("POST", "/api/v1/debates/graph", _graph_body()),
            ("POST", "/api/v1/graph-debates", _graph_body()),
        ]

        for method, path, body in calls:
            result = await graph(user, method, path, body, storage)
            assert result.status_code == status, (method, path, text_of(result))
            assert body_of(result)["code"] == code, (method, path)

        assert orchestrators == []
        assert list(graph_debates._graph_debate_cache) == [GA]
        assert storage.reads == storage.saved == []


@pytest.mark.no_auto_auth
class TestThroughTheServer:
    """The real dispatch path: route index, auth gates and RBAC, with real JWTs.

    ``/api/v1/debates/graph/{id}`` resolves to ``DebatesHandler`` in the route
    index, so the per-id graph routes are exercised through their
    ``/api/v1/graph-debates/{id}`` alias, which the RBAC route rules admit
    only while no static API token is configured.
    """

    @pytest.mark.parametrize("server", [None, SERVER_TOKEN], indirect=True)
    def test_anonymous_requests_get_401(self, server, orchestrators):
        from tests.server.rbac_dispatch import dispatch

        graph_debates._remember_graph_debate(graph_record(GA, ORG_A, USER_A.user_id))
        for method, path, body in _server_requests():
            status, _payload = dispatch(server, method, path, body=body)
            assert status == 401, (method, path)
        assert orchestrators == []
        assert list(graph_debates._graph_debate_cache) == [GA]

    @pytest.mark.parametrize("server", [SERVER_TOKEN], indirect=True)
    def test_static_token_has_no_org(self, server, orchestrators):
        from tests.server.rbac_dispatch import ORG_REQUIRED_BODY, dispatch

        graph_debates._remember_graph_debate(graph_record(GA, ORG_A, USER_A.user_id))
        for method, path, body in _server_requests():
            status, payload = dispatch(server, method, path, f"Bearer {SERVER_TOKEN}", body=body)
            assert (status, payload) == (403, ORG_REQUIRED_BODY), (method, path)
        assert orchestrators == []

    def test_other_org_gets_404_on_a_cached_graph_debate(self, server):
        from tests.server.rbac_dispatch import dispatch, jwt

        graph_debates._remember_graph_debate(graph_record(GA, ORG_A, USER_A.user_id))
        alias_paths = [
            f"/api/v1/graph-debates/{GA}{suffix}" for suffix in ("", "/branches", "/nodes")
        ]
        token_b = jwt(USER_B.user_id, ORG_B, "owner")
        for path in alias_paths:
            assert dispatch(server, "GET", path, token_b) == (404, GRAPH_NOT_FOUND), path
        for path in ("/api/v1/debates/graph", "/api/v1/graph-debates"):
            assert dispatch(server, "GET", path, token_b) == (200, {"debates": []}), path

        token_a = jwt(USER_A.user_id, ORG_A, "owner")
        for path in alias_paths:
            status, payload = dispatch(server, "GET", path, token_a)
            assert status == 200, (path, payload)
        status, payload = dispatch(server, "GET", "/api/v1/debates/graph", token_a)
        assert [d["debate_id"] for d in payload["debates"]] == [GA]

    def test_writes_on_a_graph_debate_change_nothing_and_show_nothing(self, server, orchestrators):
        from tests.server.rbac_dispatch import dispatch, jwt

        token_a = jwt(USER_A.user_id, ORG_A, "owner")
        status, created = dispatch(
            server, "POST", "/api/v1/graph-debates", token_a, body=_graph_body()
        )
        assert status == 200, created
        debate_id = created["debate_id"]
        stored = deepcopy(graph_debates._graph_debate_cache[debate_id])

        for token in (token_a, jwt(USER_B.user_id, ORG_B, "owner"), None):
            for method in ("DELETE", "PUT", "PATCH"):
                for suffix in ("", "/branches", "/nodes"):
                    path = f"/api/v1/graph-debates/{debate_id}{suffix}"
                    result = dispatch(server, method, path, token, body={"task": "overwritten"})
                    assert result == (500, _no_result(method, path)), (method, path)

        assert graph_debates._graph_debate_cache[debate_id] == stored
        path = f"/api/v1/graph-debates/{debate_id}"
        status, payload = dispatch(server, "GET", path, token_a)
        assert (status, payload["debate_id"], payload["task"]) == (200, debate_id, TASK)
        other = jwt(USER_B.user_id, ORG_B, "owner")
        assert dispatch(server, "GET", path, other) == (404, GRAPH_NOT_FOUND)
        assert dispatch(server, "GET", path)[0] == 401


def _no_result(method: str, path: str) -> dict[str, Any]:
    """The server's answer when no handler serves ``method`` on a graph path."""
    return {
        "error": "Handler matched but returned no result",
        "code": "handler_no_result",
        "handler": "GraphDebatesHandler",
        "result_type": "NoneType",
        "method": method,
        "path": path,
    }


def _server_requests() -> list[tuple[str, str, dict[str, Any] | None]]:
    return [
        ("GET", "/api/v1/debates/graph", None),
        ("GET", f"/api/v1/graph-debates/{GA}", None),
        ("POST", "/api/v1/debates/graph", _graph_body()),
    ]
