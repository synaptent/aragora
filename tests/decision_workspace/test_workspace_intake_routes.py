"""Decision intake (``POST /api/v1/workspace/decisions``) through the real server dispatch.

A valid intake answers 202 ``debating`` with labelled sources; any refusal
names its field and creates nothing. The owner comes from the auth context.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

import aragora.pipeline.plan_store as plan_store_module
from aragora.decision_workspace import debate_hook
from aragora.decision_workspace import store as workspace_store
from tests.decision_workspace.multipart import encode_multipart
from tests.decision_workspace.routes import (
    BASE,
    MARKDOWN,
    ORG_A,
    ORG_B,
    PASTED,
    QUESTION,
    TEXT,
    assert_narrow_rule,
    counts,
)
from tests.server.rbac_dispatch import (
    AUTH_REQUIRED_BODY,
    ORG_REQUIRED_BODY,
    STATIC_TOKEN,
    dispatch,
    dispatch_raw,
    handler_for,
)

pytestmark = pytest.mark.no_auto_auth

DEFAULT_FIELDS = [
    ("question", QUESTION),
    ("pasted_text", PASTED),
    ("agents[]", "openai-api|gpt-5.5"),
    ("agents[]", "grok"),
    ("rounds", "1"),
]
DEFAULT_FILES = [("files[]", "brief.md", MARKDOWN), ("files[]", "interviews.txt", TEXT)]


@pytest.fixture(autouse=True)
def no_debate_starter(monkeypatch):
    monkeypatch.setattr(debate_hook, "_starter", None)


def _create(server, authorization, fields=None, files=None, content_type=None):
    body, multipart_type = encode_multipart(
        DEFAULT_FIELDS if fields is None else fields,
        DEFAULT_FILES if files is None else files,
    )
    return dispatch(
        server,
        "POST",
        f"{BASE}/decisions",
        authorization,
        raw_body=body,
        content_type=content_type or multipart_type,
    )


def _assert_refused(server, env, authorization, status, body=None, **kwargs):
    before = counts(env)
    got_status, got_body = _create(server, authorization, **kwargs)
    assert got_status == status, got_body
    if body is not None:
        assert got_body == body
    assert counts(env) == before
    return got_body


def test_owner_creates_a_decision_and_reads_it_back(server, users, env, mode):
    status, created = _create(server, users.a)
    assert status == 202, created
    assert (created["status"], created["question"]) == ("debating", QUESTION)
    assert created["decision_id"] == created["id"]
    assert created["agents"] == ["openai-api|gpt-5.5", "grok"]
    assert [(s["label"], s["kind"], s["filename"]) for s in created["sources"]] == [
        ("S1", "pasted", None),
        ("S2", "upload", "brief.md"),
        ("S3", "upload", "interviews.txt"),
    ]
    assert created["sources"][1]["content_sha256"] == hashlib.sha256(MARKDOWN).hexdigest()

    status, detail = dispatch(server, "GET", f"{BASE}/decisions/{created['id']}", users.a)
    assert (status, detail["status"], detail["source_count"]) == (200, "debating", 3)
    status, listed = dispatch(server, "GET", f"{BASE}/decisions/{created['id']}/sources", users.a)
    assert (status, listed["sources"]) == (200, created["sources"])


def test_uploads_are_stored_in_the_org_scoped_document_store(server, users, env, mode):
    status, created = _create(server, users.a)
    assert status == 202
    pasted, brief, _notes = created["sources"]
    assert pasted["document_id"] is None
    stored = env.documents.get(brief["document_id"])
    assert stored is not None
    assert (stored.org_id, stored.created_by, stored.filename) == (ORG_A, "user-a", "brief.md")


def test_plan_is_created_with_the_callers_org(server, users, env, mode):
    status, created = _create(server, users.a)
    assert status == 202
    plan = plan_store_module.get_plan_store().get(created["id"])
    assert plan is not None
    assert (plan.org_id, plan.created_by, plan.task) == (ORG_A, "user-a", QUESTION)


def test_plan_gets_a_backbone_run_owned_by_the_callers_org(server, users, env, mode):
    status, created = _create(server, users.a)
    assert status == 202
    store = plan_store_module.get_plan_store()
    run_id = store.get(created["id"]).metadata["backbone_run_id"]
    run = store.get_run_for_org(run_id, ORG_A)
    assert run is not None and run.plan_id == created["id"]
    assert store.get_run_for_org(run_id, ORG_B) is None


def test_a_failed_write_removes_everything_already_written(server, users, env, mode, monkeypatch):
    def fail(self, rows):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(workspace_store.WorkspaceStore, "insert_decision", fail)
    before = counts(env)
    status, body = _create(server, users.a)
    assert status == 500, body
    assert counts(env) == before


def test_new_decision_is_handed_to_the_debate_hook(server, users, env, mode):
    started: list[debate_hook.DebateStartRequest] = []
    debate_hook.set_decision_debate_starter(started.append)
    status, body = _create(server, users.a)
    assert status == 202
    assert [(r.plan_id, r.org_id, r.user_id, r.question, r.agents, r.rounds) for r in started] == [
        (body["id"], ORG_A, "user-a", QUESTION, ("openai-api|gpt-5.5", "grok"), 1)
    ]


def test_without_a_debate_runner_the_decision_stays_debating(server, users, env, mode):
    status, body = _create(server, users.a)
    assert status == 202
    detail = dispatch(server, "GET", f"{BASE}/decisions/{body['id']}", users.a)[1]
    assert detail["status"] == "debating"


def test_member_can_create(server, users, env, mode):
    status, created = _create(server, users.a_member)
    assert status == 202
    assert dispatch(server, "GET", f"{BASE}/decisions/{created['id']}", users.a)[0] == 200


def test_client_supplied_owner_fields_are_ignored(server, users, env, mode):
    fields = [
        ("question", "Owner spoof?"),
        ("agents[]", "grok"),
        ("org_id", ORG_B),
        ("user_id", "user-b"),
        ("workspace_id", ORG_B),
        ("created_by", "user-b"),
    ]
    status, body = _create(server, users.a, fields=fields, files=[])
    assert status == 202
    assert body["created_by"] == "user-a"
    assert dispatch(server, "GET", f"{BASE}/decisions/{body['id']}", users.b)[0] == 404
    assert dispatch(server, "GET", f"{BASE}/decisions", users.b)[1]["decisions"] == []


def test_json_intake_creates_a_text_only_decision(server, users, env, mode):
    status, body = dispatch(
        server,
        "POST",
        f"{BASE}/decisions",
        users.a,
        body={"question": "JSON?", "pasted_text": "Context.", "agents": ["grok"], "org_id": ORG_B},
    )
    assert status == 202, body
    assert [s["kind"] for s in body["sources"]] == ["pasted"]
    assert dispatch(server, "GET", f"{BASE}/decisions/{body['id']}", users.b)[0] == 404


def test_missing_agent_configuration_refuses_intake(server, users, env, mode, monkeypatch):
    monkeypatch.delenv("ARAGORA_WORKSPACE_AGENTS")
    body = _assert_refused(server, env, users.a, 400)
    assert body["code"] == "agents_not_configured"
    assert "ARAGORA_WORKSPACE_AGENTS" in body["error"]


@pytest.mark.parametrize(
    "fields, files, status, field",
    [
        ([("question", "  "), ("agents[]", "grok")], [], 400, "question"),
        ([("question", "Q?"), ("agents[]", "anthropic-api")], [], 400, "agents"),
        ([("question", "Q?")], [], 400, "agents"),
        ([("question", "Q?"), ("agents[]", "grok"), ("rounds", "3")], [], 400, "rounds"),
        ([("question", "Q?"), ("agents[]", "grok")], [("files[]", "r.pdf", b"%PDF")], 400, "files"),
        ([("question", "Q?"), ("agents[]", "grok")], [("files[]", "r.docx", b"PK")], 400, "files"),
        (
            [("question", "Q?"), ("agents[]", "grok")],
            [("files[]", f"f{n}.txt", b"x") for n in range(11)],
            400,
            "files",
        ),
        (
            [("question", "Q?"), ("agents[]", "grok")],
            [("files[]", "big.txt", b"a" * 1048577)],
            413,
            "files",
        ),
        (
            [("question", "Q?"), ("agents[]", "grok"), ("pasted_text", "p" * 204801)],
            [],
            413,
            "pasted_text",
        ),
        # A valid file before the invalid one must not be stored either.
        (
            [("question", "Q?"), ("agents[]", "grok")],
            [("files[]", "ok.txt", b"fine"), ("files[]", "bad.csv", b"a,b")],
            400,
            "files",
        ),
    ],
)
def test_refused_intake_creates_nothing(server, users, env, mode, fields, files, status, field):
    body = _assert_refused(server, env, users.a, status, fields=fields, files=files)
    assert body["field"] == field
    assert set(body) >= {"error", "code", "field"}


def test_unoffered_agent_is_named(server, users, env, mode):
    fields = [("question", "Q?"), ("agents[]", "grok"), ("agents[]", "anthropic-api")]
    body = _assert_refused(server, env, users.a, 400, fields=fields, files=[])
    assert (body["code"], body["agent"]) == ("agent_not_offered", "anthropic-api")
    assert "anthropic-api" in body["error"]


def test_pdf_is_refused_naming_the_file(server, users, env, mode):
    files = [("files[]", "report.pdf", b"%PDF-1.7")]
    body = _assert_refused(server, env, users.a, 400, files=files)
    assert body["filename"] == "report.pdf"
    assert "PDF support is planned for a later stage" in body["error"]


def test_exact_limits_are_accepted(server, users, env, mode):
    fields = [("question", "Q?"), ("agents[]", "grok"), ("pasted_text", "p" * 204800)]
    files = [("files[]", f"f{n}.txt", b"x") for n in range(9)]
    files.append(("files[]", "big.txt", b"a" * 1048576))
    status, body = _create(server, users.a, fields=fields, files=files)
    assert status == 202, body
    assert len(body["sources"]) == 11


def test_oversized_request_is_refused_before_reading(server, users, env, mode):
    before = counts(env)
    status, _headers, payload = dispatch_raw(
        server,
        "POST",
        f"{BASE}/decisions",
        users.a,
        raw_body=b"x" * 32,
        content_type="multipart/form-data; boundary=abc",
        content_length=10**9,
    )
    assert status == 413
    assert json.loads(payload)["code"] == "request_too_large"
    assert counts(env) == before


def test_unsupported_content_type_is_415(server, users, env, mode):
    body = _assert_refused(server, env, users.a, 415, content_type="text/plain")
    assert body["code"] == "unsupported_media_type"


def test_uploads_need_a_document_store(server, users, env, mode, monkeypatch):
    monkeypatch.setitem(handler_for(server, f"{BASE}/decisions").ctx, "document_store", None)
    body = _assert_refused(server, env, users.a, 503)
    assert body["code"] == "document_store_unavailable"
    status, _ = _create(server, users.a, files=[])
    assert status == 202


def test_anonymous_gets_401_and_creates_nothing(server, env, mode):
    _assert_refused(server, env, None, 401, AUTH_REQUIRED_BODY)


def test_user_without_org_gets_403_org_required(server, users, env, mode):
    _assert_refused(server, env, users.no_org, 403, ORG_REQUIRED_BODY)


def test_static_token_gets_403_org_required(server, env, mode):
    if mode != "token":
        pytest.skip("the static token exists only with ARAGORA_API_TOKEN set")
    _assert_refused(server, env, f"Bearer {STATIC_TOKEN}", 403, ORG_REQUIRED_BODY)


def test_viewer_gets_403_and_creates_nothing(server, users, env, mode):
    body = _assert_refused(server, env, users.a_viewer, 403)
    assert body.get("code") != "org_required"


def test_post_to_other_workspace_routes_creates_nothing(server, users, env, mode):
    status, created = _create(server, users.a, files=[])
    assert status == 202
    before = counts(env)
    for path in (f"{BASE}/agent-options", f"{BASE}/decisions/{created['id']}"):
        status, body = dispatch(server, "POST", path, users.a, body={"question": "Q?"})
        assert status in (403, 405), (path, status)
        assert "question" not in body
    assert counts(env) == before


def test_post_has_its_own_narrow_rule():
    assert_narrow_rule("POST", "/api/v1/workspace/decisions", "decisions.create")
