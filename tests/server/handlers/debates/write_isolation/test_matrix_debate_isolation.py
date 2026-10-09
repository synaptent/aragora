"""Matrix debates belong to the org that created them.

``MatrixDebatesHandler`` shows a caller only its own org's stored matrix
debates (another org's, one with no recorded org and a missing id all get the
same 404, and their scenarios and conclusions are never read) and gives every
Arena a matrix run creates the creator as its receipt owner. Callers without a
user get 401 and users without an org get 403 on every route, before any
debate runs or any record is read.
"""

from __future__ import annotations

import inspect
from collections import OrderedDict
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from aragora.server.handlers.debates import matrix_debates
from aragora.server.handlers.debates.matrix_debates import MatrixDebatesHandler
from tests.server.handlers.debates.write_isolation.support import (
    ANON,
    ORG_A,
    USER_A,
    USER_B,
    USER_NO_ORG,
    Request,
    act_as,
    body_of,
    route,
    text_of,
)

MATRIX_NOT_FOUND = {"error": "Matrix debate not found", "code": "not_found"}
TASK = "Should matrix debates stay inside their org?"
MA, MN, MX = "matrix-alpha-a", "matrix-null-org", "matrix-missing-x"
# Indirect ``server`` parameter: the static API token the server is configured with.
SERVER_TOKEN = "rbac-route-rules-static-token"


@pytest.fixture(autouse=True)
def _no_matrix_limiter(monkeypatch):
    monkeypatch.setattr(
        matrix_debates, "_matrix_limiter", SimpleNamespace(is_allowed=lambda k: True)
    )
    monkeypatch.setattr(matrix_debates, "_matrix_debate_cache", OrderedDict())


@pytest.fixture
def arenas(monkeypatch):
    """Fake Arena and agents; returns the keyword arguments of every Arena constructed."""
    constructed: list[dict[str, Any]] = []

    class FakeArena:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            constructed.append(kwargs)

        async def run(self) -> SimpleNamespace:
            return SimpleNamespace(
                winner="claude",
                final_answer="Keep them inside their org",
                confidence=0.9,
                consensus_reached=True,
                rounds_used=1,
            )

    async def fake_agents(self, *args: Any, **kwargs: Any) -> list[Any]:
        return [SimpleNamespace(name="claude"), SimpleNamespace(name="openai")]

    monkeypatch.setattr("aragora.debate.orchestrator.Arena", FakeArena)
    monkeypatch.setattr(MatrixDebatesHandler, "_load_agents_from_specs", fake_agents)
    return constructed


class MatrixStorage:
    """Duck-typed matrix storage that records which scenario/conclusion reads happen."""

    def __init__(self) -> None:
        self.records = {
            MA: {"matrix_id": MA, "task": TASK, "org_id": ORG_A, "created_by": USER_A.user_id},
            MN: {"matrix_id": MN, "task": TASK},
        }
        self.reads: list[tuple[str, str]] = []

    async def get_matrix_debate(self, matrix_id: str) -> dict[str, Any] | None:
        record = self.records.get(matrix_id)
        return deepcopy(record) if record is not None else None

    async def get_matrix_scenarios(self, matrix_id: str) -> list[dict[str, Any]]:
        self.reads.append(("scenarios", matrix_id))
        return [{"scenario_name": "baseline"}]

    async def get_matrix_conclusions(self, matrix_id: str) -> dict[str, Any]:
        self.reads.append(("conclusions", matrix_id))
        return {"universal": ["stay inside the org"], "conditional": []}


@pytest.fixture
def matrix(monkeypatch):
    """``matrix(user, method, path, body=None, storage=None)`` runs ``MatrixDebatesHandler``."""
    handler = MatrixDebatesHandler(ctx={})

    async def _send(user: Any, method: str, path: str, body: Any = None, storage: Any = None):
        act_as(monkeypatch, user)
        request = Request(method, user, body)
        request.storage = storage
        if method == "GET":
            return await handler.handle_get(request, path, {})
        result = route(handler, method, path, request)
        return await result if inspect.isawaitable(result) else result

    return _send


def _matrix_bodies() -> list[dict[str, Any]]:
    return [
        {
            "task": TASK,
            "agents": ["claude", "openai"],
            "scenarios": [{"name": "s1"}, {"name": "s2"}],
        },
        {"task": TASK, "agent_combinations": [{"name": "c1", "agents": ["claude", "openai"]}]},
        {"task": TASK, "model_combinations": [{"name": "m1", "agents": ["claude"]}]},
    ]


def _no_result(method: str, path: str) -> dict[str, Any]:
    """The server's answer when no handler serves ``method`` on a matrix path."""
    return {
        "error": "Handler matched but returned no result",
        "code": "handler_no_result",
        "handler": "MatrixDebatesHandler",
        "result_type": "NoneType",
        "method": method,
        "path": path,
    }


def _matrix_get_paths(matrix_id: str) -> list[str]:
    return [
        f"/api/v1/debates/matrix/{matrix_id}",
        f"/api/v1/debates/matrix/{matrix_id}/scenarios",
        f"/api/v1/debates/matrix/{matrix_id}/conclusions",
        f"/api/v1/matrix-debates/{matrix_id}",
    ]


class TestMatrixDebates:
    async def test_only_the_owner_org_reads_a_matrix_debate(self, matrix):
        storage = MatrixStorage()

        for matrix_id in (MA, MN, MX):
            for path in _matrix_get_paths(matrix_id):
                user = USER_A if matrix_id != MA else USER_B
                result = await matrix(user, "GET", path, storage=storage)
                assert (result.status_code, body_of(result)) == (404, MATRIX_NOT_FOUND), path
        assert storage.reads == []

        for path in _matrix_get_paths(MA):
            result = await matrix(USER_A, "GET", path, storage=storage)
            assert result.status_code == 200, (path, text_of(result))
        assert storage.reads == [("scenarios", MA), ("conclusions", MA)]

        for storage in (None, object()):
            unstored = await matrix(USER_A, "GET", f"/api/v1/debates/matrix/{MA}", storage=storage)
            assert (unstored.status_code, body_of(unstored)) == (404, MATRIX_NOT_FOUND)
        anonymous = await matrix(ANON, "GET", f"/api/v1/debates/matrix/{MA}")
        assert anonymous.status_code == 401

    async def test_only_get_and_head_reach_the_read_routes(self, matrix):
        storage = MatrixStorage()
        path = f"/api/v1/matrix-debates/{MA}"
        head = await matrix(USER_A, "HEAD", path, storage=storage)
        assert (head.status_code, body_of(head)["matrix_id"]) == (200, MA), text_of(head)
        reads = list(storage.reads)

        for method in ("DELETE", "PUT", "PATCH"):
            assert await matrix(USER_A, method, path, {"task": "x"}, storage) is None, method
        assert storage.reads == reads

    async def test_a_created_matrix_is_read_back_by_its_org_only(self, matrix, arenas):
        created = await matrix(USER_A, "POST", "/api/v1/debates/matrix", _matrix_bodies()[0])
        assert created.status_code == 200, text_of(created)
        matrix_id = body_of(created)["matrix_id"]

        for path in _matrix_get_paths(matrix_id):
            owner = await matrix(USER_A, "GET", path, storage=object())
            assert owner.status_code == 200, (path, text_of(owner))
            assert matrix_id in text_of(owner)
            other = await matrix(USER_B, "GET", path, storage=object())
            assert (other.status_code, body_of(other)) == (404, MATRIX_NOT_FOUND), path

        scenarios = await matrix(USER_A, "GET", f"/api/v1/matrix-debates/{matrix_id}/scenarios")
        assert [s["scenario_name"] for s in body_of(scenarios)["scenarios"]] == ["s1", "s2"]
        conclusions = await matrix(USER_A, "GET", f"/api/v1/matrix-debates/{matrix_id}/conclusions")
        assert body_of(conclusions)["universal_conclusions"] == ["All scenarios reached consensus"]

    async def test_the_matrix_cache_is_bounded(self, matrix, arenas, monkeypatch):
        monkeypatch.setattr(matrix_debates, "_MATRIX_DEBATE_CACHE_LIMIT", 2)
        ids = []
        for _ in range(3):
            created = await matrix(USER_A, "POST", "/api/v1/debates/matrix", _matrix_bodies()[0])
            ids.append(body_of(created)["matrix_id"])

        assert list(matrix_debates._matrix_debate_cache) == ids[1:]
        evicted = await matrix(USER_A, "GET", f"/api/v1/matrix-debates/{ids[0]}")
        assert (evicted.status_code, body_of(evicted)) == (404, MATRIX_NOT_FOUND)

    async def test_every_matrix_arena_carries_the_creator_as_receipt_owner(self, matrix, arenas):
        for body in _matrix_bodies():
            arenas.clear()
            result = await matrix(USER_A, "POST", "/api/v1/debates/matrix", body)
            assert result.status_code == 200, text_of(result)
            payload = body_of(result)
            assert (payload["org_id"], payload["created_by"]) == (ORG_A, USER_A.user_id)
            assert arenas, body
            for kwargs in arenas:
                assert kwargs["receipt_org_id"] == ORG_A, body
                assert kwargs["receipt_created_by"] == USER_A.user_id, body

    @pytest.mark.parametrize(
        ("user", "status", "code"),
        [(ANON, 401, "auth_required"), (USER_NO_ORG, 403, "org_required")],
    )
    async def test_callers_without_an_org_are_refused_before_any_work(
        self, matrix, arenas, user, status, code
    ):
        storage = MatrixStorage()
        calls: list[tuple[str, str, Any]] = [("GET", p, None) for p in _matrix_get_paths(MA)]
        calls += [("POST", "/api/v1/debates/matrix", body) for body in _matrix_bodies()]
        calls += [("POST", "/api/v1/matrix-debates", _matrix_bodies()[0])]

        for method, path, body in calls:
            result = await matrix(user, method, path, body, storage)
            assert result.status_code == status, (method, path, text_of(result))
            assert body_of(result)["code"] == code, (method, path)

        assert arenas == []
        assert storage.reads == []


@pytest.mark.no_auto_auth
class TestThroughTheServer:
    """The real dispatch path: route index, auth gates and RBAC, with real JWTs.

    ``/api/v1/debates/matrix/{id}`` resolves to ``DebatesHandler``; the matrix
    GET routes are served under ``/api/v1/matrix-debates/``.
    """

    def test_a_created_matrix_is_read_back_by_its_org_only(self, server, arenas):
        from tests.server.rbac_dispatch import ORG_REQUIRED_BODY, dispatch, jwt

        token_a = jwt("user-a", ORG_A, "owner")
        status, created = dispatch(
            server, "POST", "/api/v1/matrix-debates", token_a, body=_matrix_bodies()[0]
        )
        assert status == 200, created
        matrix_id = created["matrix_id"]

        for suffix in ("", "/scenarios", "/conclusions"):
            path = f"/api/v1/matrix-debates/{matrix_id}{suffix}"
            status, payload = dispatch(server, "GET", path, token_a)
            assert (status, payload["matrix_id"]) == (200, matrix_id), path
            for token, expected in (
                (jwt("user-b", "org-b", "owner"), (404, MATRIX_NOT_FOUND)),
                (jwt("user-no-org", None, "owner"), (403, ORG_REQUIRED_BODY)),
            ):
                assert dispatch(server, "GET", path, token) == expected, path
            assert dispatch(server, "GET", path)[0] == 401, path
            missing = f"/api/v1/matrix-debates/{MX}{suffix}"
            assert dispatch(server, "GET", missing, token_a) == (404, MATRIX_NOT_FOUND)

    def test_writes_on_a_matrix_debate_change_nothing_and_show_nothing(self, server, arenas):
        from tests.server.rbac_dispatch import dispatch, jwt

        token_a = jwt("user-a", ORG_A, "owner")
        status, created = dispatch(
            server, "POST", "/api/v1/matrix-debates", token_a, body=_matrix_bodies()[0]
        )
        assert status == 200, created
        matrix_id = created["matrix_id"]
        stored = deepcopy(matrix_debates._matrix_debate_cache[matrix_id])

        for token in (token_a, jwt("user-b", "org-b", "owner"), None):
            for method in ("DELETE", "PUT", "PATCH"):
                for suffix in ("", "/scenarios", "/conclusions"):
                    path = f"/api/v1/matrix-debates/{matrix_id}{suffix}"
                    result = dispatch(server, method, path, token, body={"task": "overwritten"})
                    assert result == (500, _no_result(method, path)), (method, path)

        assert matrix_debates._matrix_debate_cache[matrix_id] == stored
        status, payload = dispatch(server, "GET", f"/api/v1/matrix-debates/{matrix_id}", token_a)
        assert (status, payload["matrix_id"], payload["task"]) == (200, matrix_id, TASK)
        other = jwt("user-b", "org-b", "owner")
        path = f"/api/v1/matrix-debates/{matrix_id}"
        assert dispatch(server, "GET", path, other) == (404, MATRIX_NOT_FOUND)
        assert dispatch(server, "GET", path)[0] == 401

    @pytest.mark.parametrize("server", [None, SERVER_TOKEN], indirect=True)
    def test_anonymous_create_gets_401(self, server, arenas):
        from tests.server.rbac_dispatch import dispatch

        status, _payload = dispatch(
            server, "POST", "/api/v1/debates/matrix", body=_matrix_bodies()[0]
        )
        assert status == 401
        assert arenas == []
        assert dispatch(server, "GET", f"/api/v1/matrix-debates/{MX}")[0] == 401

    @pytest.mark.parametrize("server", [SERVER_TOKEN], indirect=True)
    def test_static_token_has_no_org(self, server, arenas):
        from tests.server.rbac_dispatch import ORG_REQUIRED_BODY, dispatch

        status, payload = dispatch(
            server,
            "POST",
            "/api/v1/debates/matrix",
            f"Bearer {SERVER_TOKEN}",
            body=_matrix_bodies()[0],
        )
        assert (status, payload) == (403, ORG_REQUIRED_BODY)
        assert arenas == []
