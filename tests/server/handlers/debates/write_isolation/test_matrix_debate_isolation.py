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

        no_storage = await matrix(USER_A, "GET", f"/api/v1/debates/matrix/{MA}")
        assert no_storage.status_code == 503
        anonymous = await matrix(ANON, "GET", f"/api/v1/debates/matrix/{MA}")
        assert anonymous.status_code == 401

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

    Only matrix creation is exercised here: the matrix GET routes resolve to
    ``DebatesHandler`` or to ``MatrixDebatesHandler.handle``, which serves no
    GET route.
    """

    @pytest.mark.parametrize("server", [None, SERVER_TOKEN], indirect=True)
    def test_anonymous_create_gets_401(self, server, arenas):
        from tests.server.rbac_dispatch import dispatch

        status, _payload = dispatch(
            server, "POST", "/api/v1/debates/matrix", body=_matrix_bodies()[0]
        )
        assert status == 401
        assert arenas == []

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
