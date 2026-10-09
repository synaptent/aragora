"""Agent options and the decision list through the real server dispatch.

Lists show only the caller's org; anonymous 401, no-org and static-token 403
``org_required``, viewer 403, each route with its own narrow RBAC rule.
"""

from __future__ import annotations

import pytest

from tests.decision_workspace.routes import (
    AGENTS,
    BASE,
    ORG_A,
    ORG_B,
    QUESTION,
    assert_every_route_answers,
    assert_narrow_rule,
    seed_decision,
)
from tests.server.rbac_dispatch import AUTH_REQUIRED_BODY, ORG_REQUIRED_BODY, STATIC_TOKEN, dispatch

pytestmark = pytest.mark.no_auto_auth

ROUTES = [("GET", f"{BASE}/agent-options"), ("GET", f"{BASE}/decisions")]


def test_agent_options_lists_exactly_the_configured_agents(server, users, env):
    status, body = dispatch(server, "GET", f"{BASE}/agent-options", users.a)
    assert status == 200
    assert body["configured"] is True
    assert [a["spec"] for a in body["agents"]] == AGENTS.split(",")
    assert body["agents"][0] == {
        "spec": "openai-api|gpt-5.5",
        "provider": "openai-api",
        "model": "gpt-5.5",
    }
    assert body["limits"] == {
        "max_documents": 10,
        "max_file_bytes": 1048576,
        "max_pasted_chars": 204800,
    }
    assert body["accepted_extensions"] == [".md", ".txt"]


def test_agent_options_explain_a_missing_configuration(server, users, env, monkeypatch):
    monkeypatch.delenv("ARAGORA_WORKSPACE_AGENTS")
    status, body = dispatch(server, "GET", f"{BASE}/agent-options", users.a)
    assert status == 200
    assert (body["configured"], body["agents"]) == (False, [])
    assert "ARAGORA_WORKSPACE_AGENTS" in body["message"]


def test_list_shows_question_and_status(server, users, env):
    decision = seed_decision(ORG_A, "user-a")
    status, body = dispatch(server, "GET", f"{BASE}/decisions", users.a)
    assert status == 200
    assert (body["total"], body["limit"], body["offset"]) == (1, 50, 0)
    [entry] = body["decisions"]
    assert (entry["id"], entry["question"], entry["status"], entry["source_count"]) == (
        decision.id,
        QUESTION,
        "debating",
        3,
    )


def test_lists_exclude_other_orgs(server, users, env):
    a_decision = seed_decision(ORG_A, "user-a")
    b_decision = seed_decision(ORG_B, "user-b")
    for authorization, expected in ((users.a, a_decision.id), (users.b, b_decision.id)):
        status, body = dispatch(server, "GET", f"{BASE}/decisions", authorization)
        assert status == 200
        assert [d["id"] for d in body["decisions"]] == [expected]
        assert body["total"] == 1


def test_list_pages_newest_first(server, users, env):
    ids = [seed_decision(ORG_A, "user-a", question=f"Q{n}?").id for n in range(3)]
    status, body = dispatch(
        server, "GET", f"{BASE}/decisions", users.a, query={"limit": "2", "offset": "1"}
    )
    assert status == 200
    assert [d["id"] for d in body["decisions"]] == [ids[1], ids[0]]
    assert body["total"] == 3


@pytest.mark.parametrize(
    "query, field",
    [({"limit": "0"}, "limit"), ({"limit": "201"}, "limit"), ({"offset": "-1"}, "offset")],
)
def test_list_rejects_bad_paging(server, users, env, query, field):
    status, body = dispatch(server, "GET", f"{BASE}/decisions", users.a, query=query)
    assert (status, body["code"], body["field"]) == (400, "invalid_parameter", field)


def test_member_can_read(server, users, env):
    for _method, path in ROUTES:
        assert dispatch(server, "GET", path, users.a_member)[0] == 200, path


def test_anonymous_gets_401(server, env):
    assert_every_route_answers(server, env, ROUTES, None, 401, AUTH_REQUIRED_BODY)


def test_user_without_org_gets_403_org_required(server, users, env):
    assert_every_route_answers(server, env, ROUTES, users.no_org, 403, ORG_REQUIRED_BODY)


def test_static_token_gets_403_org_required(server, env, mode):
    if mode != "token":
        pytest.skip("the static token exists only with ARAGORA_API_TOKEN set")
    assert_every_route_answers(
        server, env, ROUTES, f"Bearer {STATIC_TOKEN}", 403, ORG_REQUIRED_BODY
    )


def test_viewer_gets_403(server, users, env):
    assert_every_route_answers(server, env, ROUTES, users.a_viewer, 403)


def test_trailing_slash_forms_answer_like_the_canonical_paths(server, users, env, mode):
    seed_decision(ORG_A, "user-a")
    for path in (f"{BASE}/decisions/", f"{BASE}/agent-options/"):
        status, body = dispatch(server, "GET", path, users.a)
        if mode == "token":
            # The central gate matches exact paths: slash forms keep the default deny.
            assert status == 403, path
        else:
            assert status == 200, path
    if mode == "stock":
        assert dispatch(server, "GET", f"{BASE}/decisions/", users.b)[1]["decisions"] == []


def test_unknown_workspace_paths_are_404(server, users, env, mode):
    if mode == "token":
        pytest.skip("token mode default-denies unmapped paths before the handler")
    for path in (f"{BASE}/nope", BASE + "/"):
        assert dispatch(server, "GET", path, users.a)[0] == 404, path


def test_unsupported_methods_are_refused(server, users, env, mode):
    for method in ("PUT", "PATCH", "DELETE"):
        status, body = dispatch(server, method, f"{BASE}/decisions", users.a)
        assert status in (403, 405), (method, status)
        assert "decisions" not in body
    status, _ = dispatch(server, "POST", f"{BASE}/agent-options", users.a)
    assert status in (403, 405)


@pytest.mark.parametrize("method, path", ROUTES)
def test_each_route_has_its_own_narrow_rule(method, path):
    assert_narrow_rule(method, path, "decisions.read")
