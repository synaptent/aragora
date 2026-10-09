"""Shared constants and helpers for the workspace route tests."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import Any

import aragora.pipeline.plan_store as plan_store_module
from aragora.decision_workspace import store as workspace_store
from aragora.decision_workspace.config import agent_options, workspace_limits
from aragora.decision_workspace.forms import parse_multipart_intake
from aragora.decision_workspace.intake import prepare_decision
from aragora.pipeline.decision_plan.core import ApprovalMode, DecisionPlan
from tests.decision_workspace.multipart import encode_multipart
from tests.server.rbac_dispatch import dispatch

ORG_A = "org-a-workspace"
ORG_B = "org-b-workspace"
AGENTS = "openai-api|gpt-5.5,grok"
BASE = "/api/v1/workspace"

QUESTION = "Should we move to usage-based pricing?"
MARKDOWN = b"# Pricing\nSeat pricing today.\n\n## Risks\nRevenue less predictable."
TEXT = b"Customer interviews favour usage pricing.\n\nThree of five asked for it."
PASTED = "Board asked for a recommendation.\n\nDecide by Q3."


def seed_decision(org_id: str, user_id: str, question: str = QUESTION) -> SimpleNamespace:
    """Store a decision (pasted text plus two files) without going through the POST route."""
    body, content_type = encode_multipart(
        [
            ("question", question),
            ("pasted_text", PASTED),
            ("agents[]", "openai-api|gpt-5.5"),
            ("agents[]", "grok"),
        ],
        [("files[]", "brief.md", MARKDOWN), ("files[]", "interviews.txt", TEXT)],
    )
    prepared = prepare_decision(
        parse_multipart_intake(body, content_type),
        options=agent_options(),
        limits=workspace_limits(),
    )
    plans = plan_store_module.get_plan_store()
    plan = DecisionPlan(
        task=prepared.question,
        approval_mode=ApprovalMode.ALWAYS,
        org_id=org_id,
        created_by=user_id,
    )
    plans.create(plan)
    rows = workspace_store.new_decision_rows(
        prepared, plan_id=plan.id, org_id=org_id, user_id=user_id, document_ids={}
    )
    workspace_store.get_workspace_store(plans.db_path).insert_decision(rows)
    return SimpleNamespace(id=plan.id, rows=rows)


def counts(env: Any) -> dict[str, int]:
    """Row counts of every table an intake writes, plus stored documents."""
    conn = sqlite3.connect(env.plans_db)
    try:
        result = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("plans", "workspace_decisions", "decision_sources", "decision_passages")
        }
    finally:
        conn.close()
    result["documents"] = len(list(env.documents.storage_dir.glob("*.json")))
    return result


def assert_every_route_answers(
    server: Any,
    env: Any,
    routes: list[tuple[str, str]],
    authorization: str | None,
    status: int,
    body: dict[str, Any] | None = None,
) -> None:
    """Each route answers ``status`` (and ``body`` if given) and nothing is written."""
    before = counts(env)
    for method, path in routes:
        got_status, got_body = dispatch(server, method, path, authorization)
        assert got_status == status, (method, path, got_body)
        if body is not None:
            assert got_body == body, (method, path)
        else:
            assert got_body.get("code") != "org_required", (method, path)
    assert counts(env) == before


def assert_narrow_rule(method: str, path: str, key: str) -> None:
    """The first RBAC route rule for ``method path`` is a narrow, method-specific one."""
    from aragora.rbac.middleware import DEFAULT_ROUTE_PERMISSIONS

    matching = [rule for rule in DEFAULT_ROUTE_PERMISSIONS if rule.matches(path, method)[0]]
    assert matching, (method, path)
    first = matching[0]
    assert first.permission_key == key
    assert first.method == method
    assert not first.allow_unauthenticated
    assert "workspace" in first.pattern.pattern and first.pattern.pattern.endswith("$")
