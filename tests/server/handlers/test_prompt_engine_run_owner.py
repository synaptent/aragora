"""Backbone runs from POST /api/prompt-engine/run belong to the authenticated caller."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.billing.auth.context import UserAuthContext
from aragora.pipeline.plan_store import PlanStore
from aragora.prompt_engine.types import Specification
from aragora.server.handlers.prompt_engine.handler import PromptEngineHandler
from aragora.server.handlers.runs import handle_run_detail, handle_runs_list


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch) -> PlanStore:
    spec = Specification(
        title="S", problem_statement="P", proposed_solution="F", success_criteria=["Ok"]
    )
    result = MagicMock(specification=spec, questions=[], stages_completed=[], auto_approved=False)
    result.intent.to_dict.return_value = {"raw_prompt": "Build it", "intent_type": "feature"}
    result.timing.to_dict.return_value = {}
    conductor = MagicMock(run=AsyncMock(return_value=result))
    monkeypatch.setattr(PromptEngineHandler, "_make_conductor", lambda self, data: conductor)
    plan_store = PlanStore(db_path=str(tmp_path / "runs.db"))
    monkeypatch.setattr("aragora.pipeline.plan_store.get_plan_store", lambda: plan_store)
    return plan_store


def _post_run(monkeypatch, org_id, body, handler=None, authenticated=True) -> dict:
    user = UserAuthContext(authenticated=authenticated, user_id="user-a1", org_id=org_id)
    monkeypatch.setattr("aragora.billing.jwt_auth.extract_user_from_request", lambda *a: user)
    raw = json.dumps(body).encode()
    request = MagicMock(headers={"Content-Length": str(len(raw))}, rfile=BytesIO(raw))
    request.path = "/api/prompt-engine/run"
    return (handler or PromptEngineHandler({})).handle_POST(request).to_dict()


def _owner(store: PlanStore, run_id: str) -> tuple:
    with closing(sqlite3.connect(store._db_path)) as conn:
        sql = "SELECT org_id, created_by FROM backbone_runs WHERE run_id = ?"
        return tuple(conn.execute(sql, (run_id,)).fetchone())


def test_run_belongs_to_the_callers_org_and_ignores_payload_identity(store, monkeypatch) -> None:
    body = {"prompt": "Build it", "org_id": "org-b", "user_id": "intruder"}
    response = _post_run(monkeypatch, "org-a", body)
    run_id = response["body"]["run"]["run_id"]

    assert _owner(store, run_id) == ("org-a", "user-a1")
    assert store.get_run_for_org(run_id, "org-b") is None
    listed = handle_runs_list({}, org_id="org-a", store=store).to_dict()["body"]["runs"]
    assert [run["run_id"] for run in listed] == [run_id]
    assert handle_runs_list({}, org_id="org-b", store=store).to_dict()["body"]["runs"] == []
    assert handle_run_detail(run_id, org_id="org-a", store=store).to_dict()["status"] == 200
    assert handle_run_detail(run_id, org_id="org-b", store=store).to_dict()["status"] == 404


@pytest.mark.parametrize("authenticated", [True, False])
def test_caller_without_an_org_keeps_an_ownerless_run(store, monkeypatch, authenticated) -> None:
    body = {"prompt": "Build it", "org_id": "org-a"}
    response = _post_run(monkeypatch, None, body, authenticated=authenticated)
    run_id = response["body"]["run"]["run_id"]

    assert _owner(store, run_id) == (None, None)
    assert store.list_runs_for_org("org-a") == []


def test_run_reuses_the_owner_resolved_for_the_decision_plan(store, monkeypatch) -> None:
    handler = PromptEngineHandler({})
    planner = MagicMock(org_id="org-a", user_id="user-a1")
    handler.require_permission_or_error = MagicMock(return_value=(planner, None))

    # The spec is not execution grade (422), but the run was persisted before that.
    _post_run(
        monkeypatch, "org-other", {"prompt": "Build it", "decision_plan": {"create": True}}, handler
    )
    [run] = store.list_runs()
    assert _owner(store, run.run_id) == ("org-a", "user-a1")
