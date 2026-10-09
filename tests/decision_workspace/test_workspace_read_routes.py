"""Decision, sources and passage reads through the real server dispatch.

Another org's decision, source or passage answers exactly like a missing one;
anonymous 401, no-org and static-token 403 ``org_required``, viewer 403.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

import aragora.pipeline.plan_store as plan_store_module
from aragora.decision_workspace import store as workspace_store
from aragora.pipeline.plan_store import PlanStore
from tests.decision_workspace.routes import (
    BASE,
    MARKDOWN,
    ORG_A,
    ORG_B,
    PASTED,
    QUESTION,
    assert_every_route_answers,
    assert_narrow_rule,
    seed_decision,
)
from tests.server.rbac_dispatch import AUTH_REQUIRED_BODY, ORG_REQUIRED_BODY, STATIC_TOKEN, dispatch

pytestmark = pytest.mark.no_auto_auth

MISSING_DECISION = "dp-000000000000"
MISSING_PASSAGE = "psg_00000000000000000000000000000000"
DECISION_NOT_FOUND = {"error": "Decision not found", "code": "not_found"}


@pytest.fixture
def d1(server, users, env):
    decision = seed_decision(ORG_A, "user-a")
    status, body = dispatch(server, "GET", f"{BASE}/decisions/{decision.id}/sources", users.a)
    assert status == 200, body
    return SimpleNamespace(id=decision.id, sources=body["sources"])


def _passage_path(d1, passage_id: str | None = None) -> str:
    passage_id = passage_id or d1.sources[0]["passages"][0]["passage_id"]
    return f"{BASE}/decisions/{d1.id}/passages/{passage_id}"


def _routes(d1) -> list[tuple[str, str]]:
    return [
        ("GET", f"{BASE}/decisions/{d1.id}"),
        ("GET", f"{BASE}/decisions/{d1.id}/sources"),
        ("GET", _passage_path(d1)),
    ]


def test_owner_reads_the_decision(server, users, d1):
    status, detail = dispatch(server, "GET", f"{BASE}/decisions/{d1.id}", users.a)
    assert status == 200
    assert (detail["id"], detail["question"], detail["status"]) == (d1.id, QUESTION, "debating")
    assert detail["agents"] == ["openai-api|gpt-5.5", "grok"]
    assert (detail["rounds"], detail["created_by"]) == (1, "user-a")
    assert (detail["source_count"], detail["passage_count"]) == (
        3,
        sum(len(s["passages"]) for s in d1.sources),
    )


def test_sources_are_labelled_in_intake_order_with_hashes(server, users, d1):
    assert [(s["label"], s["kind"], s["filename"]) for s in d1.sources] == [
        ("S1", "pasted", None),
        ("S2", "upload", "brief.md"),
        ("S3", "upload", "interviews.txt"),
    ]
    assert d1.sources[0]["content_sha256"] == hashlib.sha256(PASTED.encode()).hexdigest()
    assert d1.sources[1]["content_sha256"] == hashlib.sha256(MARKDOWN).hexdigest()
    for source in d1.sources:
        assert source["passage_count"] == len(source["passages"]) > 0


def test_passages_are_labelled_hashed_and_carry_headings(server, users, d1):
    brief = d1.sources[1]
    assert [p["label"] for p in brief["passages"]] == ["S2:P1", "S2:P2"]
    assert [p["heading"] for p in brief["passages"]] == ["Pricing", "Risks"]
    for source in d1.sources:
        labels = [p["label"] for p in source["passages"]]
        assert labels == [f"{source['label']}:P{m}" for m in range(1, len(labels) + 1)]
        for summary in source["passages"]:
            status, passage = dispatch(
                server, "GET", _passage_path(d1, summary["passage_id"]), users.a
            )
            assert status == 200
            assert passage["label"] == summary["label"]
            assert passage["source_label"] == source["label"]
            assert passage["decision_id"] == d1.id
            assert passage["sha256"] == hashlib.sha256(passage["text"].encode()).hexdigest()
            assert passage["sha256"] == summary["sha256"]


def test_passages_are_identical_after_a_store_restart(server, users, env, d1, monkeypatch):
    paths = [_passage_path(d1, p["passage_id"]) for s in d1.sources for p in s["passages"]]
    first = {path: dispatch(server, "GET", path, users.a)[1] for path in paths}
    monkeypatch.setattr(workspace_store, "_stores", {})
    monkeypatch.setattr(plan_store_module, "_store", PlanStore(str(env.plans_db)))
    status, sources = dispatch(server, "GET", f"{BASE}/decisions/{d1.id}/sources", users.a)
    assert status == 200 and sources["sources"] == d1.sources
    for path, before in first.items():
        assert dispatch(server, "GET", path, users.a) == (200, before)


def test_other_org_gets_the_missing_id_404_on_every_read(server, users, d1):
    pairs = [
        (f"{BASE}/decisions/{d1.id}", f"{BASE}/decisions/{MISSING_DECISION}"),
        (f"{BASE}/decisions/{d1.id}/sources", f"{BASE}/decisions/{MISSING_DECISION}/sources"),
        (_passage_path(d1), f"{BASE}/decisions/{MISSING_DECISION}/passages/{MISSING_PASSAGE}"),
    ]
    for real, missing in pairs:
        real_status, real_body = dispatch(server, "GET", real, users.b)
        missing_status, missing_body = dispatch(server, "GET", missing, users.b)
        assert real_status == missing_status == 404, real
        assert real_body == missing_body == DECISION_NOT_FOUND
        assert d1.id not in json.dumps(real_body)


def test_other_orgs_passage_through_own_decision_is_404(server, users, d1):
    b_decision = seed_decision(ORG_B, "user-b")
    passage = d1.sources[0]["passages"][0]["passage_id"]
    status, body = dispatch(
        server, "GET", f"{BASE}/decisions/{b_decision.id}/passages/{passage}", users.b
    )
    missing = dispatch(
        server, "GET", f"{BASE}/decisions/{b_decision.id}/passages/{MISSING_PASSAGE}", users.b
    )
    assert (status, body) == missing
    assert body == {"error": "Passage not found", "code": "not_found"}


def test_member_can_read(server, users, d1):
    for _method, path in _routes(d1):
        assert dispatch(server, "GET", path, users.a_member)[0] == 200, path


def test_anonymous_gets_401(server, env, d1):
    assert_every_route_answers(server, env, _routes(d1), None, 401, AUTH_REQUIRED_BODY)


def test_user_without_org_gets_403_org_required(server, users, env, d1):
    assert_every_route_answers(server, env, _routes(d1), users.no_org, 403, ORG_REQUIRED_BODY)


def test_static_token_gets_403_org_required(server, env, d1, mode):
    if mode != "token":
        pytest.skip("the static token exists only with ARAGORA_API_TOKEN set")
    assert_every_route_answers(
        server, env, _routes(d1), f"Bearer {STATIC_TOKEN}", 403, ORG_REQUIRED_BODY
    )


def test_viewer_gets_403(server, users, env, d1):
    assert_every_route_answers(server, env, _routes(d1), users.a_viewer, 403)


def test_trailing_slash_forms_answer_like_the_canonical_paths(server, users, d1, mode):
    status, _ = dispatch(server, "GET", f"{BASE}/decisions/{d1.id}/", users.a)
    if mode == "token":
        # The central gate matches exact paths: slash forms keep the default deny.
        assert status == 403
        return
    assert status == 200
    assert dispatch(server, "GET", f"{BASE}/decisions/{d1.id}/sources/", users.a)[0] == 200
    assert dispatch(server, "GET", f"{BASE}/decisions/{d1.id}/", users.b) == (
        404,
        DECISION_NOT_FOUND,
    )


def test_unversioned_alias_is_scoped_like_the_v1_path(server, users, d1):
    legacy = f"/api/workspace/decisions/{d1.id}"
    status, body = dispatch(server, "GET", legacy, users.a)
    assert (status, body["id"]) == (200, d1.id)
    assert dispatch(server, "GET", legacy, users.b) == dispatch(
        server, "GET", f"/api/workspace/decisions/{MISSING_DECISION}", users.b
    )
    assert dispatch(server, "GET", legacy)[0] == 401


def test_unsupported_methods_never_answer_like_a_read(server, users, env, d1):
    for method in ("PUT", "PATCH", "DELETE", "POST"):
        for _get, path in _routes(d1):
            status, body = dispatch(server, method, path, users.a)
            assert status in (403, 404, 405), (method, path, status)
            assert d1.id not in json.dumps(body)
            assert "question" not in body and "text" not in body


def test_unknown_decision_sub_paths_are_404(server, users, d1, mode):
    if mode == "token":
        pytest.skip("token mode default-denies unmapped paths before the handler")
    for path in (f"{BASE}/decisions/{d1.id}/unknown", f"{BASE}/decisions/{d1.id}/passages"):
        assert dispatch(server, "GET", path, users.a)[0] == 404, path


@pytest.mark.parametrize("bad_id", ["dp-%C3%A9t%C3%A9", "x" * 300, "dp-..", "dp-a%2Fb"])
def test_odd_decision_ids_are_plain_404s(server, users, env, bad_id):
    status, body = dispatch(server, "GET", f"{BASE}/decisions/{bad_id}", users.a)
    assert (status, body) == (404, DECISION_NOT_FOUND)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/workspace/decisions/dp-123",
        "/api/v1/workspace/decisions/dp-123/sources",
        "/api/v1/workspace/decisions/dp-123/passages/psg_1",
    ],
)
def test_each_route_has_its_own_narrow_rule(path):
    assert_narrow_rule("GET", path, "decisions.read")


@pytest.mark.parametrize(
    "method, path",
    [
        ("DELETE", "/api/v1/workspace/decisions/dp-123"),
        ("PUT", "/api/v1/workspace/decisions/dp-123"),
        ("PATCH", "/api/v1/workspace/decisions/dp-123"),
        ("POST", "/api/v1/workspace/decisions/dp-123"),
        ("POST", "/api/v1/workspace/agent-options"),
        ("DELETE", "/api/v1/workspace/decisions"),
        ("GET", "/api/v1/workspace/decisions/dp-123/other"),
        ("GET", "/api/v1/workspace/other"),
    ],
)
def test_no_rule_admits_unmapped_workspace_routes(method, path):
    from aragora.rbac.middleware import DEFAULT_ROUTE_PERMISSIONS

    assert not [rule for rule in DEFAULT_ROUTE_PERMISSIONS if rule.matches(path, method)[0]]


def test_workspace_paths_are_org_scoped():
    from aragora.tenancy.record_scope import is_org_scoped_path

    assert is_org_scoped_path("/api/v1/workspace/decisions")
    assert is_org_scoped_path("/api/v1/workspace/decisions/dp-1/passages/p")
    assert is_org_scoped_path("/api/v1/workspace/agent-options")
