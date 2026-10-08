"""Checkpoints are visible only to the org that owns their debate.

``CheckpointHandler`` serves ``/api/v1/checkpoints`` (list, resumable list, get,
resume, delete, intervention) and the debate-scoped checkpoint routes. A
checkpoint of another org's debate, of a public debate of another org, of a
debate with no recorded org and a missing id all get the same 404 and change
nothing.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from aragora.debate.checkpoint import CheckpointManager, DebateCheckpoint
from aragora.debate.checkpoint_backends import DatabaseCheckpointStore
from aragora.server.handlers.memory import checkpoints as checkpoints_module
from aragora.server.handlers.memory.checkpoints import CheckpointHandler
from tests.server.handlers.debates.write_isolation.support import (
    ANON,
    DA,
    DB,
    DN,
    DP,
    NOT_FOUND,
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    USER_NO_ORG,
    Request,
    act_as,
    body_of,
    text_of,
)
from tests.server.rbac_dispatch import STATIC_TOKEN

CA, CB, CN, CP, CX = "cp-alpha-a", "cp-bravo-b", "cp-null-org", "cp-public-a", "cp-missing-x"
CHECKPOINT_NOT_FOUND = {"error": "Checkpoint not found", "code": "not_found"}
ORG_REQUIRED_CODE = "org_required"


def _checkpoint(checkpoint_id: str, debate_id: str) -> DebateCheckpoint:
    return DebateCheckpoint(
        checkpoint_id=checkpoint_id,
        debate_id=debate_id,
        task=f"Checkpointed task of {debate_id}",
        current_round=1,
        total_rounds=3,
        phase="proposal",
        messages=[],
        critiques=[],
        votes=[],
        agent_states=[],
    )


def _routes(checkpoint_id: str) -> tuple[tuple[str, str, dict[str, Any] | None], ...]:
    path = f"/api/v1/checkpoints/{checkpoint_id}"
    return (
        ("GET", path, None),
        ("POST", f"{path}/resume", {}),
        ("DELETE", path, None),
        ("POST", f"{path}/intervention", {"note": "Pause here", "by": "reviewer"}),
    )


DEBATE_ROUTES = (
    ("GET", f"/api/v1/debates/{DA}/checkpoints", None),
    ("POST", f"/api/v1/debates/{DA}/checkpoint", {"note": "manual"}),
    ("POST", f"/api/v1/debates/{DA}/checkpoint/pause", {"note": "hold"}),
)
LIST_ROUTES = (
    ("GET", "/api/v1/checkpoints", None),
    ("GET", "/api/v1/checkpoints/resumable", None),
)
ALL_ROUTES = LIST_ROUTES + _routes(CA) + DEBATE_ROUTES


@pytest.fixture(autouse=True)
def _allow_checkpoint_requests(monkeypatch):
    monkeypatch.setattr(checkpoints_module._checkpoint_limiter, "is_allowed", lambda key: True)


@pytest.fixture(autouse=True)
def _fresh_intervention_state(monkeypatch):
    from aragora.server.handlers.debates import intervention

    monkeypatch.setattr(intervention, "_debate_state", {})
    monkeypatch.setattr(intervention, "_intervention_log", [])


@pytest.fixture
def manager(tmp_path) -> CheckpointManager:
    store = DatabaseCheckpointStore(str(tmp_path / "checkpoints.db"))
    for checkpoint_id, debate_id in ((CA, DA), (CB, DB), (CN, DN), (CP, DP)):
        asyncio.run(store.save(_checkpoint(checkpoint_id, debate_id)))
    return CheckpointManager(store=store)


@pytest.fixture
def running_da(state_manager):
    return state_manager.register_debate(DA, "Running debate of A", ["claude"], 3)


@pytest.fixture
def send(monkeypatch, storage, manager):
    """``send(user, method, path, body, query)`` runs ``CheckpointHandler`` as ``user``."""
    handler = CheckpointHandler({"storage": storage})
    handler._checkpoint_manager = manager

    def _send(
        user: Any,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ):
        act_as(monkeypatch, user)
        raw = json.dumps(body).encode() if body is not None else None
        request = Request(method, user, body)
        return asyncio.run(handler.handle(path, query or {}, request, raw))

    return _send


def _state(manager: CheckpointManager, checkpoint_id: str) -> tuple[Any, ...] | None:
    checkpoint = asyncio.run(manager.store.load(checkpoint_id))
    if checkpoint is None:
        return None
    return (
        checkpoint.resume_count,
        tuple(checkpoint.intervention_notes),
        checkpoint.pending_intervention,
        checkpoint.status,
    )


def _stored(manager: CheckpointManager) -> dict[str, tuple[Any, ...] | None]:
    return {cid: _state(manager, cid) for cid in (CA, CB, CN, CP)}


def _ids(result: Any, key: str = "checkpoints", field: str = "checkpoint_id") -> set[str]:
    assert result.status_code == 200, text_of(result)
    return {row[field] for row in body_of(result)[key]}


def test_lists_hold_only_the_callers_org_checkpoints(send):
    assert _ids(send(USER_A, "GET", "/api/v1/checkpoints")) == {CA, CP}
    assert _ids(send(USER_B, "GET", "/api/v1/checkpoints")) == {CB}
    assert _ids(send(USER_B, "GET", "/api/v1/checkpoints", query={"debate_id": DA})) == set()

    page = body_of(send(USER_A, "GET", "/api/v1/checkpoints", query={"limit": "1"}))
    assert page["total"] == 2 and len(page["checkpoints"]) == 1
    filtered = send(USER_B, "GET", "/api/v1/checkpoints", query={"status": "complete"})
    assert body_of(filtered)["total"] == 1

    resumable = "/api/v1/checkpoints/resumable"
    assert _ids(send(USER_A, "GET", resumable), "debates", "debate_id") == {DA, DP}
    b_resumable = send(USER_B, "GET", resumable)
    assert _ids(b_resumable, "debates", "debate_id") == {DB}
    assert body_of(b_resumable)["total"] == 1


def test_newer_checkpoints_of_other_orgs_do_not_hide_the_callers_older_ones(send, manager):
    for n in range(150):
        newer = _checkpoint(f"cp-bravo-newer-{n:03d}", DB)
        newer.created_at = f"2999-01-01T00:00:{n % 60:02d}.{n:06d}"
        asyncio.run(manager.store.save(newer))

    page = body_of(send(USER_A, "GET", "/api/v1/checkpoints", query={"limit": "1"}))
    assert (page["total"], len(page["checkpoints"])) == (2, 1)
    assert _ids(send(USER_A, "GET", "/api/v1/checkpoints")) == {CA, CP}
    b_page = body_of(send(USER_B, "GET", "/api/v1/checkpoints", query={"offset": "140"}))
    assert (b_page["total"], len(b_page["checkpoints"])) == (151, 11)
    resumable = send(USER_A, "GET", "/api/v1/checkpoints/resumable")
    assert _ids(resumable, "debates", "debate_id") == {DA, DP}


def test_other_org_null_org_public_and_missing_get_the_same_404(send, manager):
    before = _stored(manager)
    for checkpoint_id in (CA, CP, CN, CX):
        for method, path, body in _routes(checkpoint_id):
            result = send(USER_B, method, path, body)
            assert result.status_code == 404, (method, path, text_of(result))
            assert body_of(result) == CHECKPOINT_NOT_FOUND, (method, path)
    for method, path, body in _routes(CN):
        assert body_of(send(USER_A, method, path, body)) == CHECKPOINT_NOT_FOUND, (method, path)
    assert _stored(manager) == before


def test_owner_reads_resumes_annotates_and_deletes(send, manager):
    path = f"/api/v1/checkpoints/{CA}"
    got = send(USER_A, "GET", path)
    assert got.status_code == 200, text_of(got)
    assert body_of(got)["checkpoint"]["checkpoint_id"] == CA

    resumed = send(USER_A, "POST", f"{path}/resume", {"resumed_by": "user-a"})
    assert resumed.status_code == 200, text_of(resumed)
    assert body_of(resumed)["resumed_debate"]["original_debate_id"] == DA

    noted = send(USER_A, "POST", f"{path}/intervention", {"note": "Check sources", "by": "a"})
    assert noted.status_code == 200, text_of(noted)
    resume_count, notes, pending, _status = _state(manager, CA)
    assert (resume_count, notes, pending) == (1, ("[a] Check sources",), True)

    deleted = send(USER_A, "DELETE", path)
    assert deleted.status_code == 200, text_of(deleted)
    assert _state(manager, CA) is None
    assert _state(manager, CB) is not None


def test_callers_without_an_org_scope_are_refused_on_every_route(send, manager, running_da):
    before = _stored(manager)
    for user, status in ((ANON, 401), (USER_NO_ORG, 403)):
        for method, path, body in ALL_ROUTES:
            result = send(user, method, path, body)
            assert result.status_code == status, (user.user_id, method, path, text_of(result))
            if status == 403:
                assert body_of(result)["code"] == ORG_REQUIRED_CODE
    assert _stored(manager) == before
    assert running_da.status == "running"


def test_debate_routes_refuse_other_orgs_and_change_nothing(send, manager, running_da):
    from aragora.server.handlers.debates import intervention

    before = _stored(manager)
    for user, debate_id in ((USER_B, DA), (USER_B, DP), (USER_A, DN), (USER_B, "deb-missing")):
        for method, path, body in DEBATE_ROUTES:
            path = path.replace(DA, debate_id)
            result = send(user, method, path, body)
            assert (result.status_code, body_of(result)) == (404, NOT_FOUND), (method, path)
    assert _stored(manager) == before
    assert running_da.status == "running"
    assert DA not in intervention._debate_state


def test_owner_lists_creates_and_pauses_its_debate_checkpoints(send, manager, running_da):
    listed = send(USER_A, "GET", f"/api/v1/debates/{DA}/checkpoints")
    assert _ids(listed) == {CA}

    created = send(USER_A, "POST", f"/api/v1/debates/{DA}/checkpoint", {"phase": "manual"})
    assert created.status_code == 200, text_of(created)
    paused = send(USER_A, "POST", f"/api/v1/debates/{DA}/checkpoint/pause", {})
    assert paused.status_code == 200, text_of(paused)
    assert running_da.status == "paused"

    rows = asyncio.run(manager.store.list_checkpoints(debate_id=DA))
    assert len(rows) == 3
    assert _ids(send(USER_B, "GET", "/api/v1/checkpoints")) == {CB}


@pytest.mark.no_auto_auth
class TestThroughTheServer:
    """The real dispatch path: route index, auth gates and RBAC, with real JWTs."""

    @staticmethod
    def _wire(server: Any, storage: Any, manager: CheckpointManager) -> None:
        checkpoint_handler = server.cls._checkpoint_handler
        checkpoint_handler.ctx["storage"] = storage
        checkpoint_handler._checkpoint_manager = manager

    @pytest.mark.parametrize("server", [None, "rbac-route-rules-static-token"], indirect=True)
    def test_anonymous_requests_get_401(self, server, storage, manager):
        from tests.server.rbac_dispatch import dispatch

        self._wire(server, storage, manager)
        before = _stored(manager)
        for method, path in (
            ("GET", "/api/v1/checkpoints"),
            ("DELETE", f"/api/v1/checkpoints/{CA}"),
        ):
            status, _payload = dispatch(server, method, path)
            assert status == 401, (method, path)
        assert _stored(manager) == before

    @pytest.mark.parametrize("server", [STATIC_TOKEN], indirect=True)
    def test_static_token_without_a_user_gets_org_required(self, server, storage, manager):
        from tests.server.rbac_dispatch import ORG_REQUIRED_BODY, dispatch

        self._wire(server, storage, manager)
        before = _stored(manager)
        for method, path in (
            ("GET", "/api/v1/checkpoints"),
            ("DELETE", f"/api/v1/checkpoints/{CA}"),
        ):
            status, payload = dispatch(server, method, path, f"Bearer {STATIC_TOKEN}")
            assert (status, payload) == (403, ORG_REQUIRED_BODY), (method, path)
        assert _stored(manager) == before

    def test_other_org_gets_the_checkpoint_404_and_owner_reads(self, server, storage, manager):
        from tests.server.rbac_dispatch import dispatch, jwt

        self._wire(server, storage, manager)
        before = _stored(manager)
        token_b = jwt("user-b", ORG_B, "owner")
        for method in ("GET", "DELETE"):
            status, payload = dispatch(server, method, f"/api/v1/checkpoints/{CA}", token_b)
            assert (status, payload) == (404, CHECKPOINT_NOT_FOUND), method
        status, payload = dispatch(server, "GET", "/api/v1/checkpoints", token_b)
        assert status == 200, payload
        assert {row["checkpoint_id"] for row in payload["checkpoints"]} == {CB}
        assert _stored(manager) == before

        token_a = jwt("user-a", ORG_A, "owner")
        status, payload = dispatch(server, "GET", f"/api/v1/checkpoints/{CA}", token_a)
        assert status == 200, payload
        assert payload["checkpoint"]["checkpoint_id"] == CA
