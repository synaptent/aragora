"""Org isolation of the FastAPI v2 debate and decision routes.

Two orgs (real JWTs), an org-less user and an anonymous caller exercise every
``/api/v2/debates`` and ``/api/v2/decisions`` route against a real SQLite
``DebateStorage`` and a real ``AsyncDecisionService``:

* another org's record, an unowned record and a missing one answer the same
  404 body, before any permission check, and writes to them have no effect;
* lists only show the caller org's records;
* a public debate is readable by anyone but writable only by its org;
* anonymous callers get 401 and org-less users 403 ``org_required``;
* the owner keeps access (export is checked against ``debates:read``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from aragora.debate.decision_service import (
    AsyncDecisionService,
    DebateEvent,
    DebateState,
    DebateStatus,
    EventType,
    InMemoryStateStore,
)
from aragora.rbac.models import AuthorizationContext
from aragora.server.fastapi import create_app
from aragora.server.fastapi.dependencies.auth import require_authenticated
from aragora.server.fastapi.routes.debates import get_nomic_dir
from aragora.storage.debate_storage import DebateStorage

ORG_A = "org-a"
ORG_B = "org-b"

DA = "debate-iso-a"
DA_DEL = "debate-iso-a-delete"
DB = "debate-iso-b"
DN = "debate-iso-null"
DP = "debate-iso-b-public"
DX = "debate-iso-missing"

DEC_A = "decision-iso-a"
DEC_B = "decision-iso-b"
DEC_NULL = "decision-iso-null"
DEC_X = "decision-iso-missing"

DEBATE_NOT_FOUND = {"error": "Debate not found", "code": "not_found"}
DECISION_NOT_FOUND = {"error": "Decision not found", "code": "not_found"}
ORG_REQUIRED = "org_required"

# Every route on one debate, as (method, path template, JSON body).
DEBATE_ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/api/v2/debates/{id}", None),
    ("GET", "/api/v2/debates/{id}/messages", None),
    ("GET", "/api/v2/debates/{id}/convergence", None),
    ("GET", "/api/v2/debates/{id}/export/json", None),
    ("GET", "/api/v2/debates/{id}/export/md", None),
    ("GET", "/api/v2/debates/{id}/argument-graph", None),
    ("GET", "/api/v2/debates/{id}/stats", None),
    ("PATCH", "/api/v2/debates/{id}", {"title": "hijacked"}),
    ("DELETE", "/api/v2/debates/{id}", None),
]
DECISION_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v2/decisions/{id}"),
    ("GET", "/api/v2/decisions/{id}/events"),
    ("DELETE", "/api/v2/decisions/{id}"),
]


def _debate(debate_id: str, task: str) -> dict[str, Any]:
    return {
        "id": debate_id,
        "task": task,
        "agents": ["claude", "codex"],
        "rounds": [
            {
                "round_num": 1,
                "messages": [{"role": "proposal", "agent": "claude", "content": f"{task} body"}],
            }
        ],
        "consensus_reached": True,
        "confidence": 0.8,
        "final_answer": f"{task} answer",
    }


@pytest.fixture
def nomic_dir(tmp_path: Path) -> Path:
    path = tmp_path / "nomic"
    path.mkdir()
    return path


@pytest.fixture
def storage(nomic_dir: Path) -> DebateStorage:
    store = DebateStorage(str(nomic_dir / "debates.db"))
    store.save_dict(_debate(DA, "Org A private sentinel"), org_id=ORG_A)
    store.save_dict(_debate(DA_DEL, "Org A throwaway"), org_id=ORG_A)
    store.save_dict(_debate(DB, "Org B private sentinel"), org_id=ORG_B)
    store.save_dict(_debate(DN, "Unowned sentinel"))
    store.save_dict(_debate(DP, "Org B public sentinel"), org_id=ORG_B)
    store.set_public(DP, True)
    return store


def _decision(decision_id: str, org_id: str | None) -> DebateState:
    metadata = {"org_id": org_id, "user_id": f"user-{org_id}"} if org_id else {}
    return DebateState(
        id=decision_id,
        task=f"decision {decision_id}",
        status=DebateStatus.RUNNING,
        metadata=metadata,
    )


@pytest.fixture
def decision_service() -> AsyncDecisionService:
    store = InMemoryStateStore()
    for decision_id, org_id in ((DEC_A, ORG_A), (DEC_B, ORG_B), (DEC_NULL, None)):
        asyncio.run(store.save(_decision(decision_id, org_id)))
    return AsyncDecisionService(store=store)


@pytest.fixture
def app(nomic_dir, storage, decision_service, fastapi_context_builder):
    application = create_app(nomic_dir=nomic_dir)
    application.state.context = fastapi_context_builder(
        storage=storage, decision_service=decision_service
    )
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app):
    # Not entered as a context manager: the app's startup would replace this context.
    test_client = TestClient(app, raise_server_exceptions=False)
    yield test_client
    test_client.close()


@pytest.fixture
def as_a(fastapi_bearer) -> dict[str, str]:
    return fastapi_bearer("user-a", ORG_A)


@pytest.fixture
def as_b(fastapi_bearer) -> dict[str, str]:
    return fastapi_bearer("user-b", ORG_B)


@pytest.fixture
def no_org(fastapi_bearer) -> dict[str, str]:
    return fastapi_bearer("user-solo", None)


def _call(client: TestClient, method: str, path: str, headers: dict, body=None):
    return client.request(method, path, headers=headers, json=body)


def _grant(app, org_id: str, user_id: str, *permissions: str) -> None:
    """Give the caller extra permissions; its org scope still comes from the JWT."""
    app.dependency_overrides[require_authenticated] = lambda: AuthorizationContext(
        user_id=user_id, org_id=org_id, roles={"owner"}, permissions=set(permissions)
    )


def _snapshot(storage: DebateStorage, debate_id: str) -> tuple[Any, Any]:
    return storage.get_access_info(debate_id), storage.get_debate(debate_id)


# =============================================================================
# Anonymous and org-less callers
# =============================================================================


class TestNoScope:
    def test_anonymous_gets_401_on_every_route(self, client, storage):
        before = _snapshot(storage, DA)
        responses = [client.get("/api/v2/debates"), client.get("/api/v2/decisions")]
        for method, template, body in DEBATE_ROUTES:
            for debate_id in (DA, DX):
                responses.append(_call(client, method, template.format(id=debate_id), {}, body))
        for method, template in DECISION_ROUTES:
            responses.append(client.request(method, template.format(id=DEC_A)))
        responses.append(client.post("/api/v2/decisions", json={"task": "anon"}))

        assert [r.status_code for r in responses] == [401] * len(responses)
        assert _snapshot(storage, DA) == before

    def test_org_less_user_gets_org_required(self, client, storage, no_org):
        before = _snapshot(storage, DA)
        responses = [
            client.get("/api/v2/debates", headers=no_org),
            client.get(f"/api/v2/debates/{DA}", headers=no_org),
            client.get(f"/api/v2/debates/{DA}/export/json", headers=no_org),
            client.patch(f"/api/v2/debates/{DA}", headers=no_org, json={"title": "x"}),
            client.delete(f"/api/v2/debates/{DA}", headers=no_org),
            client.get("/api/v2/decisions", headers=no_org),
            client.get(f"/api/v2/decisions/{DEC_A}", headers=no_org),
            client.post("/api/v2/decisions", headers=no_org, json={"task": "no org"}),
        ]

        assert [r.status_code for r in responses] == [403] * len(responses)
        assert {r.json()["code"] for r in responses} == {ORG_REQUIRED}
        assert _snapshot(storage, DA) == before


# =============================================================================
# Debates: other org
# =============================================================================


class TestDebatesOtherOrg:
    @pytest.mark.parametrize(("method", "template", "body"), DEBATE_ROUTES)
    def test_other_org_record_answers_like_a_missing_one(
        self, client, storage, as_b, method, template, body
    ):
        before = {debate_id: _snapshot(storage, debate_id) for debate_id in (DA, DN)}

        answers = {
            debate_id: _call(client, method, template.format(id=debate_id), as_b, body)
            for debate_id in (DA, DN, DX)
        }

        for response in answers.values():
            assert response.status_code == 404
            assert response.json() == DEBATE_NOT_FOUND
        assert {debate_id: _snapshot(storage, debate_id) for debate_id in (DA, DN)} == before

    def test_other_org_record_is_404_even_without_the_permission(self, client, storage, as_b):
        """Ownership is checked before the permission, so the answer never depends on the role."""
        before = _snapshot(storage, DA)

        patch_response = client.patch(f"/api/v2/debates/{DA}", headers=as_b, json={"title": "x"})

        # An owner of org B does not hold debates:write; the debate is still just "not found".
        assert patch_response.status_code == 404
        assert patch_response.json() == DEBATE_NOT_FOUND
        assert _snapshot(storage, DA) == before

    def test_other_org_slug_answers_like_a_missing_one(self, client, storage, as_b):
        response = client.get(f"/api/v2/debates/{_slug_of(storage, DA)}", headers=as_b)

        assert response.status_code == 404
        assert response.json() == DEBATE_NOT_FOUND

    def test_list_shows_only_the_callers_org(self, client, as_a, as_b):
        listed_a = client.get("/api/v2/debates", headers=as_a).json()
        listed_b = client.get("/api/v2/debates", headers=as_b).json()

        assert {d["id"] for d in listed_a["debates"]} == {DA, DA_DEL}
        assert listed_a["total"] == 2
        assert {d["id"] for d in listed_b["debates"]} == {DB, DP}
        assert listed_b["total"] == 2


def _slug_of(storage: DebateStorage, debate_id: str) -> str:
    for meta in storage.list_recent(limit=100):
        if meta.debate_id == debate_id:
            return meta.slug
    raise AssertionError(f"no slug for {debate_id}")


# =============================================================================
# Debates: owner and public debates
# =============================================================================


class TestDebatesOwner:
    def test_owner_reads_its_debate(self, client, as_a):
        detail = client.get(f"/api/v2/debates/{DA}", headers=as_a)
        messages = client.get(f"/api/v2/debates/{DA}/messages", headers=as_a)
        convergence = client.get(f"/api/v2/debates/{DA}/convergence", headers=as_a)

        assert detail.status_code == 200
        assert detail.json()["id"] == DA
        assert detail.json()["task"] == "Org A private sentinel"
        assert messages.status_code == 200
        assert messages.json()["messages"][0]["content"] == "Org A private sentinel body"
        assert convergence.status_code == 200
        assert convergence.json()["converged"] is True

    def test_owner_reads_by_slug(self, client, storage, as_a):
        response = client.get(f"/api/v2/debates/{_slug_of(storage, DA)}", headers=as_a)

        assert response.status_code == 200
        assert response.json()["id"] == DA

    @pytest.mark.parametrize("export_format", ["json", "md"])
    def test_owner_exports_with_debates_read(self, client, as_a, export_format):
        """An owner holds debates:read, which export requires (export:read is held by no role)."""
        response = client.get(f"/api/v2/debates/{DA}/export/{export_format}", headers=as_a)

        assert response.status_code == 200
        assert "Org A private sentinel" in response.text

    def test_owner_update_needs_debates_write_after_the_ownership_check(
        self, app, client, storage, as_a
    ):
        before = _snapshot(storage, DA)
        denied = client.patch(f"/api/v2/debates/{DA}", headers=as_a, json={"title": "Renamed"})
        assert denied.status_code == 403
        assert _snapshot(storage, DA) == before

        _grant(app, ORG_A, "user-a", "debates:write")
        allowed = client.patch(f"/api/v2/debates/{DA}", headers=as_a, json={"title": "Renamed"})

        assert allowed.status_code == 200
        assert storage.get_debate(DA)["title"] == "Renamed"
        assert storage.get_access_info(DA) == (DA, ORG_A, False)

    def test_owner_deletes_its_debate(self, client, storage, as_a):
        response = client.delete(f"/api/v2/debates/{DA_DEL}", headers=as_a)

        assert response.status_code == 200
        assert response.json() == {"deleted": True, "id": DA_DEL}
        assert storage.get_access_info(DA_DEL) is None

    def test_delete_permission_is_checked_for_the_owner_org(self, client, storage, fastapi_bearer):
        viewer_a = fastapi_bearer("viewer-a", ORG_A, role="viewer")
        viewer_b = fastapi_bearer("viewer-b", ORG_B, role="viewer")
        before = _snapshot(storage, DA)

        own = client.delete(f"/api/v2/debates/{DA}", headers=viewer_a)
        other = client.delete(f"/api/v2/debates/{DA}", headers=viewer_b)

        assert own.status_code == 403
        assert other.status_code == 404
        assert other.json() == DEBATE_NOT_FOUND
        assert _snapshot(storage, DA) == before


class TestPublicDebate:
    def test_public_debate_is_readable_by_anyone(self, client, as_a):
        assert client.get(f"/api/v2/debates/{DP}").status_code == 200
        assert client.get(f"/api/v2/debates/{DP}/messages").status_code == 200
        assert client.get(f"/api/v2/debates/{DP}", headers=as_a).json()["id"] == DP

    def test_public_debate_is_not_listed_or_writable_by_another_org(
        self, app, client, storage, as_a
    ):
        before = _snapshot(storage, DP)
        _grant(app, ORG_A, "user-a", "debates:write", "debates:delete")

        patched = client.patch(f"/api/v2/debates/{DP}", headers=as_a, json={"title": "x"})
        deleted = client.delete(f"/api/v2/debates/{DP}", headers=as_a)
        listed = client.get("/api/v2/debates", headers=as_a).json()

        assert (patched.status_code, deleted.status_code) == (404, 404)
        assert patched.json() == deleted.json() == DEBATE_NOT_FOUND
        assert DP not in {d["id"] for d in listed["debates"]}
        assert _snapshot(storage, DP) == before


# =============================================================================
# Trace reads use the app's nomic dir
# =============================================================================


class TestNomicDir:
    def test_get_nomic_dir_prefers_the_app_dir(self, tmp_path, monkeypatch):
        app_dir = tmp_path / "app-nomic"
        env_dir = tmp_path / "env-nomic"
        app_dir.mkdir()
        env_dir.mkdir()
        monkeypatch.setenv("ARAGORA_NOMIC_DIR", str(env_dir))

        request = SimpleNamespace(app=create_app(nomic_dir=app_dir))

        assert get_nomic_dir(request) == app_dir
        assert get_nomic_dir(SimpleNamespace(app=create_app())) == env_dir
        assert get_nomic_dir() == env_dir

    def test_stats_read_replays_from_the_app_nomic_dir(
        self, app, client, nomic_dir, tmp_path, monkeypatch, as_a, as_b
    ):
        other_dir = tmp_path / "elsewhere"
        other_dir.mkdir()
        monkeypatch.setenv("ARAGORA_NOMIC_DIR", str(other_dir))
        replay = nomic_dir / "replays" / DA / "events.jsonl"
        replay.parent.mkdir(parents=True)
        replay.write_text(
            json.dumps(
                {
                    "type": "agent_message",
                    "agent": "claude",
                    "round": 1,
                    "data": {"content": "A claim", "role": "proposer"},
                }
            )
            + "\n"
        )

        other_org = client.get(f"/api/v2/debates/{DA}/stats", headers=as_b)
        _grant(app, ORG_A, "user-a", "analysis:read")
        owner = client.get(f"/api/v2/debates/{DA}/stats", headers=as_a)

        assert other_org.status_code == 404
        assert other_org.json() == DEBATE_NOT_FOUND
        assert owner.status_code == 200
        assert owner.json()["node_count"] >= 1


# =============================================================================
# Decisions
# =============================================================================


async def _one_terminal_event(debate_id: str):
    yield DebateEvent(debate_id=debate_id, type=EventType.DEBATE_COMPLETED, data={})


class TestDecisions:
    @pytest.mark.parametrize(("method", "template"), DECISION_ROUTES)
    def test_other_org_decision_answers_like_a_missing_one(
        self, client, decision_service, as_b, method, template
    ):
        answers = [
            client.request(method, template.format(id=decision_id), headers=as_b)
            for decision_id in (DEC_A, DEC_NULL, DEC_X)
        ]

        assert [r.status_code for r in answers] == [404, 404, 404]
        assert all(r.json() == DECISION_NOT_FOUND for r in answers)
        for decision_id in (DEC_A, DEC_NULL):
            state = asyncio.run(decision_service.get_debate(decision_id))
            assert state.status == DebateStatus.RUNNING

    def test_list_shows_only_the_callers_org(self, client, as_a, as_b):
        listed_a = client.get("/api/v2/decisions", headers=as_a)
        listed_b = client.get("/api/v2/decisions", headers=as_b)

        assert [d["id"] for d in listed_a.json()] == [DEC_A]
        assert [d["id"] for d in listed_b.json()] == [DEC_B]

    def test_owner_reads_streams_and_cancels(self, client, decision_service, as_a):
        decision_service.subscribe_events = _one_terminal_event

        detail = client.get(f"/api/v2/decisions/{DEC_A}", headers=as_a)
        events = client.get(f"/api/v2/decisions/{DEC_A}/events", headers=as_a)
        cancelled = client.delete(f"/api/v2/decisions/{DEC_A}", headers=as_a)

        assert detail.status_code == 200
        assert detail.json()["metadata"]["org_id"] == ORG_A
        assert events.status_code == 200
        assert "event: debate_completed" in events.text
        assert cancelled.status_code == 200
        assert cancelled.json()["cancelled"] is True

    def test_start_owns_the_decision_by_the_callers_org_not_the_body(
        self, client, decision_service, as_a, as_b
    ):
        with patch.object(AsyncDecisionService, "_run_debate", AsyncMock()):
            response = client.post(
                "/api/v2/decisions",
                headers=as_a,
                json={"task": "Who owns this?", "metadata": {"org_id": ORG_B, "user_id": "evil"}},
            )
        assert response.status_code == 202
        decision_id = response.json()["id"]

        state = asyncio.run(decision_service.get_debate(decision_id))
        assert state.metadata["org_id"] == ORG_A
        assert state.metadata["user_id"] == "user-a"
        assert client.get(f"/api/v2/decisions/{decision_id}", headers=as_a).status_code == 200
        foreign = client.get(f"/api/v2/decisions/{decision_id}", headers=as_b)
        assert foreign.status_code == 404
        assert foreign.json() == DECISION_NOT_FOUND
