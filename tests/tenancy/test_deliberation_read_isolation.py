"""Control-plane deliberation reads show a decision only to the org that owns it.

The legacy routes (with and without ``/v1``, result and status) and the FastAPI
``/api/v2`` twins read the shared ``decision_results`` rows. Another org's
decision and one with no recorded owner answer exactly like a missing id.
The deliberation writes (legacy POST sync or async plus the coordinator worker,
FastAPI POST) record the creating org, so the creator's org can read them back.
"""

from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import aragora.core.decision_results as decision_results
from aragora.billing.auth.context import UserAuthContext
from aragora.control_plane.deliberation import DeliberationManager, DeliberationTask
from aragora.core.decision import DecisionResult, DecisionType
from aragora.rbac.models import AuthorizationContext
from aragora.server.fastapi import create_app
from aragora.server.handlers.control_plane import ControlPlaneHandler
from aragora.storage.decision_result_store import DecisionResultStore

ORG_A, ORG_B = "org-a", "org-b"
WEBHOOK = "https://hooks.example.test/deliver"
NOT_FOUND = {"error": "Deliberation not found", "code": "not_found"}
STORED = {
    "status": "completed",
    "completed_at": 1700000000.0,
    "result": {
        "answer": "Ship it",
        "request": {"content": "Ship?", "response_channels": [{"type": "webhook", "url": WEBHOOK}]},
    },
}
# caller -> (org_id, user_id, role)
CALLERS = {
    "a": (ORG_A, "user-a", "owner"),
    "b": (ORG_B, "user-b", "owner"),
    "noorg-owner": (None, "user-n", "owner"),
    "noorg-member": (None, "user-m", "member"),
}
LEGACY_PATHS = [
    "/api/control-plane/deliberations/{id}",
    "/api/v1/control-plane/deliberations/{id}",
    "/api/control-plane/deliberations/{id}/status",
    "/api/v1/control-plane/deliberations/{id}/status",
]
V2_PATHS = ["/api/v2/deliberations/{id}", "/api/v2/deliberations/{id}/status"]
HIDDEN = [("b", "dec_a"), ("a", "dec_ownerless"), ("b", "dec_ownerless")]
REFUSED = [
    (None, (401, "auth_required")),
    ("noorg-owner", (403, "org_required")),
    ("noorg-member", (403, "org_required")),
]


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    store = DecisionResultStore(db_path=tmp_path / "decision_results.db", ttl_seconds=3600)
    store.save("dec_a", STORED, org_id=ORG_A, created_by="user-a")
    store.save("dec_ownerless", STORED)
    monkeypatch.setattr(decision_results, "_decision_result_store", store)
    monkeypatch.setattr(decision_results, "_decision_results_fallback", {})
    return store


@pytest.fixture
def legacy_get(monkeypatch):
    def _user(handler, user_store=None):
        caller = handler.headers.get("X-Caller")
        if caller not in CALLERS:
            return UserAuthContext()
        org_id, user_id, role = CALLERS[caller]
        return UserAuthContext(
            authenticated=True, user_id=user_id, org_id=org_id, role=role, token_type="access"
        )

    monkeypatch.setattr("aragora.billing.jwt_auth.extract_user_from_request", _user)
    handler = ControlPlaneHandler({})

    def get(path: str, caller: str | None) -> tuple[int, bytes]:
        http = SimpleNamespace(headers={"X-Caller": caller} if caller else {}, user_store=None)
        result = handler.handle(path, {}, http)
        return result.status_code, result.body

    return get


@pytest.fixture
def v2_get(monkeypatch):
    async def _auth_context(request):
        caller = request.headers.get("X-Caller")
        if caller not in CALLERS:
            return AuthorizationContext(user_id="anonymous", org_id=None)
        org_id, user_id, role = CALLERS[caller]
        return AuthorizationContext(user_id=user_id, org_id=org_id, roles={role})

    monkeypatch.setattr("aragora.server.fastapi.dependencies.auth.get_auth_context", _auth_context)
    client = TestClient(create_app(), raise_server_exceptions=False)

    def get(path: str, caller: str | None) -> tuple[int, bytes]:
        response = client.get(path, headers={"X-Caller": caller} if caller else {})
        return response.status_code, response.content

    return get


def _owner_body_ok(path: str, body: dict) -> None:
    if path.endswith("/status"):
        assert body == {"request_id": "dec_a", "status": "completed", "completed_at": 1700000000.0}
    else:
        assert body["request_id"] == "dec_a"
        assert body["result"] == {"answer": "Ship it"}
    assert WEBHOOK not in json.dumps(body)


@pytest.mark.parametrize("template", LEGACY_PATHS)
class TestLegacyRoutes:
    def test_owner_org_reads_without_stored_request(self, legacy_get, template):
        path = template.format(id="dec_a")
        status, body = legacy_get(path, "a")
        assert status == 200
        _owner_body_ok(path, json.loads(body))

    @pytest.mark.parametrize("caller,request_id", HIDDEN)
    def test_other_org_and_ownerless_match_missing(self, legacy_get, template, caller, request_id):
        hidden = legacy_get(template.format(id=request_id), caller)
        missing = legacy_get(template.format(id="dec_missing"), caller)
        assert hidden == missing
        assert hidden[0] == 404 and json.loads(hidden[1]) == NOT_FOUND

    @pytest.mark.parametrize("caller,expected", REFUSED)
    def test_callers_without_org_scope_are_refused(self, legacy_get, template, caller, expected):
        status, body = legacy_get(template.format(id="dec_a"), caller)
        assert (status, json.loads(body)["code"]) == expected


@pytest.mark.parametrize("template", V2_PATHS)
class TestFastAPIRoutes:
    def test_owner_org_reads_without_stored_request(self, v2_get, template):
        path = template.format(id="dec_a")
        status, body = v2_get(path, "a")
        assert status == 200
        _owner_body_ok(path, json.loads(body)["data"])

    @pytest.mark.parametrize("caller,request_id", HIDDEN)
    def test_other_org_and_ownerless_match_missing(self, v2_get, template, caller, request_id):
        hidden = v2_get(template.format(id=request_id), caller)
        missing = v2_get(template.format(id="dec_missing"), caller)
        assert hidden == missing
        assert hidden[0] == 404 and json.loads(hidden[1]) == NOT_FOUND

    @pytest.mark.parametrize("caller,expected", REFUSED)
    def test_callers_without_org_scope_are_refused(self, v2_get, template, caller, expected):
        status, body = v2_get(template.format(id="dec_a"), caller)
        assert (status, json.loads(body)["code"]) == expected


def test_in_memory_fallback_is_owner_checked(monkeypatch):
    monkeypatch.setattr(decision_results, "_get_result_store", lambda: None)
    monkeypatch.setattr(
        decision_results,
        "_decision_results_fallback",
        {"dec_a": {**STORED, "org_id": ORG_A}, "dec_ownerless": {**STORED, "org_id": None}},
    )

    assert decision_results.get_decision_result_for_org("dec_a", ORG_A)["result"] == {
        "answer": "Ship it"
    }
    assert decision_results.get_decision_status_for_org("dec_a", ORG_A) == {
        "request_id": "dec_a",
        "status": "completed",
        "completed_at": 1700000000.0,
    }
    for request_id, org_id in [("dec_a", ORG_B), ("dec_ownerless", ORG_A), ("dec_a", "")]:
        assert decision_results.get_decision_result_for_org(request_id, org_id) is None
        assert decision_results.get_decision_status_for_org(request_id, org_id) is None


# --- Writes -----------------------------------------------------------------

POST_PATHS = ["/api/control-plane/deliberations", "/api/v1/control-plane/deliberations"]
OWNER_A = {"org_id": ORG_A, "created_by": "user-a"}
OUTCOMES = [  # router outcome, legacy sync POST status, stored status
    (None, 200, "completed"),
    (RuntimeError("engine crash"), 500, "failed"),
    (asyncio.TimeoutError(), 408, "timeout"),
]


def _decide(request) -> DecisionResult:
    return DecisionResult(request.request_id, DecisionType.DEBATE, "Ship it", 0.9, True)


def _only_org_a_reads(get, templates, request_id) -> None:
    for template in templates:
        status, raw = get(template.format(id=request_id), "a")
        body = json.loads(raw)
        assert status == 200 and body.get("data", body)["request_id"] == request_id
        hidden = get(template.format(id=request_id), "b")
        assert hidden[0] == 404 and hidden == get(template.format(id="dec_missing"), "b")


@pytest.fixture
def router(monkeypatch):
    router = SimpleNamespace(route=AsyncMock(side_effect=_decide))
    monkeypatch.setattr("aragora.control_plane.deliberation.get_decision_router", lambda: router)
    return router


@pytest.fixture
def legacy_post(legacy_get, monkeypatch):
    run_async = "aragora.server.handlers.control_plane.tasks._run_async"
    monkeypatch.setattr(run_async, lambda coro: coro.close() or "task-1")
    coordinator = SimpleNamespace(submit_task=AsyncMock())
    handler = ControlPlaneHandler({"control_plane_coordinator": coordinator})

    async def post(path: str, caller: str | None, body: dict) -> tuple[int, dict]:
        raw = json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "Content-Length": len(raw)}
        http = SimpleNamespace(headers={**headers, "X-Caller": caller}, rfile=io.BytesIO(raw))
        result = await handler.handle_post(path, {}, http)
        return result.status_code, json.loads(result.body)

    post.submit_task = coordinator.submit_task
    return post


@pytest.fixture
def v2_post(v2_get, monkeypatch):
    control_plane = SimpleNamespace(submit_task=AsyncMock(return_value="task-1"))
    monkeypatch.setattr(
        "aragora.control_plane.integration.get_integrated_control_plane", lambda: control_plane
    )
    client = TestClient(create_app(), raise_server_exceptions=False)

    def post(caller: str | None, body: dict) -> tuple[int, dict]:
        response = client.post(
            "/api/v2/deliberations", json=body, headers={"X-Caller": caller or ""}
        )
        return response.status_code, response.json()

    post.submit_task = control_plane.submit_task
    return post


@pytest.mark.asyncio
@pytest.mark.parametrize("path", POST_PATHS)
@pytest.mark.parametrize("error,code,status", OUTCOMES)
async def test_legacy_sync_write_is_owned_by_the_creator_org(
    legacy_post, legacy_get, router, store, path, error, code, status
):
    router.route.side_effect = error or _decide
    body = {"content": "Ship the release?", "request_id": "dec_new"}
    assert (await legacy_post(path, "a", body))[0] == code
    stored = store.get("dec_new")
    assert (stored["status"], stored["org_id"], stored["created_by"]) == (status, ORG_A, "user-a")
    _only_org_a_reads(legacy_get, LEGACY_PATHS, "dec_new")


@pytest.mark.asyncio
@pytest.mark.parametrize("error,_code,status", OUTCOMES)
async def test_legacy_async_write_is_owned_once_the_worker_runs(
    legacy_post, legacy_get, router, store, error, _code, status
):
    router.route.side_effect = error or _decide
    code, body = await legacy_post(POST_PATHS[0], "a", {"content": "Ship?", "async": True})
    metadata = legacy_post.submit_task.call_args.kwargs["metadata"]
    assert (code, metadata) == (202, {"request_id": body["request_id"], **OWNER_A})

    task = DeliberationTask(question="Ship?", request_id=body["request_id"], metadata=metadata)
    await DeliberationManager().execute_deliberation(task)
    assert store.get(body["request_id"])["status"] == status
    _only_org_a_reads(legacy_get, LEGACY_PATHS, body["request_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("caller,expected", REFUSED)
async def test_writes_refuse_callers_without_org(legacy_post, v2_post, router, caller, expected):
    for path in POST_PATHS:
        for mode in ("sync", "async"):
            status, body = await legacy_post(path, caller, {"content": "Ship?", "mode": mode})
            assert (status, body["code"]) == expected
    for async_mode in (False, True):
        status, body = v2_post(caller, {"content": "Ship?", "async_mode": async_mode})
        assert (status, body["code"]) == expected
    router.route.assert_not_called()
    legacy_post.submit_task.assert_not_called()
    v2_post.submit_task.assert_not_called()


@pytest.mark.asyncio
async def test_another_org_cannot_take_over_an_id(legacy_post, legacy_get, router, store):
    status, _ = await legacy_post(POST_PATHS[0], "b", {"content": "Ship?", "request_id": "dec_a"})
    assert status == 200 and store.get("dec_a")["result"] == STORED["result"]
    assert decision_results._decision_results_fallback == {}
    _only_org_a_reads(legacy_get, LEGACY_PATHS, "dec_a")


def test_in_memory_fallback_keeps_the_first_owner(monkeypatch):
    monkeypatch.setattr(decision_results, "_get_result_store", lambda: None)
    decision_results.save_decision_result("dec_x", {"status": "completed", **OWNER_A})
    decision_results.save_decision_result("dec_x", {"status": "failed", "org_id": ORG_B})
    assert decision_results.get_decision_status_for_org("dec_x", ORG_A)["status"] == "completed"
    assert decision_results.get_decision_result_for_org("dec_x", ORG_B) is None


def test_fastapi_write_is_owned_by_the_creator_org(v2_post, v2_get, router, store):
    status, body = v2_post("a", {"content": "Ship the release?"})
    request_id = body["data"]["request_id"]
    stored = store.get(request_id)
    assert (status, stored["org_id"], stored["created_by"]) == (202, ORG_A, "user-a")
    _only_org_a_reads(v2_get, V2_PATHS, request_id)

    status, body = v2_post("a", {"content": "Ship?", "async_mode": True})
    metadata = v2_post.submit_task.call_args.kwargs["metadata"]
    assert (status, metadata) == (202, {"request_id": body["data"]["request_id"], **OWNER_A})
