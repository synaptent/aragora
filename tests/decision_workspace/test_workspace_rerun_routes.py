"""Decision rerun (``POST /api/v1/workspace/decisions/{id}/rerun``) through the real server dispatch.

A failed decision gets a new run row (the failed one is kept); a double
submit starts one run; another org's decision answers like a missing one;
anonymous 401, no-org and static-token 403 ``org_required``, viewer 403.
"""

from __future__ import annotations

import pytest

import aragora.pipeline.plan_store as plan_store_module
from aragora.decision_workspace import debate_hook
from aragora.decision_workspace import store as workspace_store
from tests.decision_workspace.routes import (
    BASE,
    ORG_A,
    assert_every_route_answers,
    assert_narrow_rule,
    counts,
    seed_decision,
)
from tests.server.rbac_dispatch import AUTH_REQUIRED_BODY, ORG_REQUIRED_BODY, STATIC_TOKEN, dispatch

pytestmark = pytest.mark.no_auto_auth

DECISION_NOT_FOUND = {"error": "Decision not found", "code": "not_found"}


@pytest.fixture(autouse=True)
def started(monkeypatch):
    requests: list[debate_hook.DebateStartRequest] = []
    monkeypatch.setattr(debate_hook, "_starter", requests.append)
    return requests


def _workspace():
    return workspace_store.get_workspace_store(plan_store_module.get_plan_store().db_path)


@pytest.fixture
def failed(server, users, env):
    decision = seed_decision(ORG_A, "user-a")
    _workspace().finish_run(decision.rows.run.run_id, ORG_A, status="failed", error="boom")
    return decision


def _rerun(server, authorization, decision_id):
    return dispatch(server, "POST", f"{BASE}/decisions/{decision_id}/rerun", authorization)


def test_rerun_starts_a_new_run_and_keeps_the_failed_one(server, users, failed, started):
    status, body = _rerun(server, users.a, failed.id)
    assert status == 202, body
    assert (body["status"], body["run"]["status"], body["run"]["started_by"]) == (
        "debating",
        "running",
        "user-a",
    )
    runs = _workspace().list_runs(failed.id, ORG_A)
    assert [(r.status, r.error) for r in runs] == [("running", None), ("failed", "boom")]
    assert [r["status"] for r in body["runs"]] == ["running", "failed"]
    (request,) = started
    assert (request.plan_id, request.org_id, request.user_id, request.run_id) == (
        failed.id,
        ORG_A,
        "user-a",
        runs[0].run_id,
    )
    assert request.agents == ("openai-api|gpt-5.5", "grok")


def test_member_can_rerun(server, users, failed):
    assert _rerun(server, users.a_member, failed.id)[0] == 202


def test_double_submit_starts_one_run(server, users, failed, started):
    first = _rerun(server, users.a, failed.id)
    second = _rerun(server, users.a, failed.id)
    assert first[0] == 202
    assert second[0] == 409
    assert second[1]["code"] == "run_in_progress"
    assert second[1]["run_id"] == first[1]["run"]["run_id"]
    assert len(started) == 1
    assert len(_workspace().list_runs(failed.id, ORG_A)) == 2


def test_only_a_failed_decision_can_be_rerun(server, users, env):
    debating = seed_decision(ORG_A, "user-a")
    status, body = _rerun(server, users.a, debating.id)
    assert (status, body["code"]) == (409, "run_in_progress")

    ready = seed_decision(ORG_A, "user-a")
    _workspace().finish_run(
        ready.rows.run.run_id,
        ORG_A,
        status="completed",
        revision_content={"recommendation": "Go", "citations": []},
    )
    status, body = _rerun(server, users.a, ready.id)
    assert (status, body["code"]) == (409, "decision_not_failed")
    assert len(_workspace().list_runs(ready.id, ORG_A)) == 1


def test_a_rerun_the_runner_cannot_take_fails_again_with_the_reason(
    server, users, failed, monkeypatch
):
    monkeypatch.setattr(debate_hook, "_starter", None)
    status, body = _rerun(server, users.a, failed.id)
    assert status == 202
    assert (body["status"], body["run"]["status"]) == ("failed", "failed")
    assert "debate runner is not available" in body["run"]["error"]
    assert [r.status for r in _workspace().list_runs(failed.id, ORG_A)] == ["failed", "failed"]


def test_other_org_gets_the_missing_id_404_and_starts_nothing(server, users, env, failed, started):
    before = counts(env)
    real = _rerun(server, users.b, failed.id)
    missing = _rerun(server, users.b, "dp-000000000000")
    assert real == missing == (404, DECISION_NOT_FOUND)
    assert counts(env) == before
    assert started == []


def test_anonymous_gets_401(server, env, failed):
    assert_every_route_answers(
        server,
        env,
        [("POST", f"{BASE}/decisions/{failed.id}/rerun")],
        None,
        401,
        AUTH_REQUIRED_BODY,
    )


def test_user_without_org_gets_403_org_required(server, users, env, failed):
    assert_every_route_answers(
        server,
        env,
        [("POST", f"{BASE}/decisions/{failed.id}/rerun")],
        users.no_org,
        403,
        ORG_REQUIRED_BODY,
    )


def test_static_token_gets_403_org_required(server, env, mode, failed):
    if mode != "token":
        pytest.skip("the static token exists only with ARAGORA_API_TOKEN set")
    assert_every_route_answers(
        server,
        env,
        [("POST", f"{BASE}/decisions/{failed.id}/rerun")],
        f"Bearer {STATIC_TOKEN}",
        403,
        ORG_REQUIRED_BODY,
    )


def test_viewer_gets_403(server, users, env, failed, started):
    assert_every_route_answers(
        server, env, [("POST", f"{BASE}/decisions/{failed.id}/rerun")], users.a_viewer, 403
    )
    assert started == []


def test_other_methods_on_rerun_are_refused(server, users, env, failed, started):
    before = counts(env)
    for method in ("GET", "PUT", "PATCH", "DELETE"):
        status, _ = dispatch(server, method, f"{BASE}/decisions/{failed.id}/rerun", users.a)
        assert status in (403, 405), method
    assert counts(env) == before
    assert started == []


def test_rerun_has_its_own_narrow_rule():
    assert_narrow_rule("POST", "/api/v1/workspace/decisions/dp-1/rerun", "decisions.update")
