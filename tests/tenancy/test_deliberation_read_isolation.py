"""Control-plane deliberation reads show a decision only to the org that owns it.

The legacy routes (with and without ``/v1``, result and status) and the FastAPI
``/api/v2`` twins read the shared ``decision_results`` rows. Another org's
decision and one with no recorded owner answer exactly like a missing id.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import aragora.core.decision_results as decision_results
from aragora.billing.auth.context import UserAuthContext
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
