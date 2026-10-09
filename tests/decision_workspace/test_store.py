"""Workspace tables in plans.db: org-scoped reads, uniqueness, immutable passages."""

from __future__ import annotations

import sqlite3

import pytest

from aragora.decision_workspace.config import ENV_AGENTS, WorkspaceLimits, agent_options
from aragora.decision_workspace.forms import parse_json_intake
from aragora.decision_workspace.intake import prepare_decision
from aragora.decision_workspace.store import (
    SCHEMA_MODULE,
    WorkspaceStore,
    new_decision_rows,
)
from aragora.pipeline.plan_store import PlanStore

ORG_A = "org-a-store"
ORG_B = "org-b-store"
AGENTS = agent_options({ENV_AGENTS: "grok,openai-api|gpt-5.5"})
LIMITS = WorkspaceLimits(max_documents=10, max_file_bytes=1048576, max_pasted_chars=204800)


def _prepared(question="Q?", pasted="# H\nOne.\n\nTwo."):
    body = (
        '{"question": %s, "pasted_text": %s, "agents": ["grok"]}' % (_json(question), _json(pasted))
    ).encode()
    return prepare_decision(parse_json_intake(body), options=AGENTS, limits=LIMITS)


def _json(value: str) -> str:
    import json

    return json.dumps(value)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "plans.db"
    PlanStore(str(path))
    return str(path)


def _insert(store: WorkspaceStore, plan_id: str, org_id: str, question="Q?"):
    rows = new_decision_rows(
        _prepared(question=question),
        plan_id=plan_id,
        org_id=org_id,
        user_id=f"user-{org_id}",
        document_ids={},
    )
    store.insert_decision(rows)
    return rows


def test_tables_live_in_plans_db_next_to_plans(db_path):
    WorkspaceStore(db_path)
    conn = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = conn.execute(
            "SELECT version FROM _schema_versions WHERE module = ?", (SCHEMA_MODULE,)
        ).fetchone()
        columns = {
            table: {r[1]: r for r in conn.execute(f"PRAGMA table_info({table})")}
            for table in ("workspace_decisions", "decision_sources", "decision_passages")
        }
    finally:
        conn.close()
    assert {
        "plans",
        "workspace_decisions",
        "decision_sources",
        "decision_passages",
        "decision_runs",
        "decision_revisions",
    } <= tables
    assert version == (2,)
    for table, cols in columns.items():
        assert cols["org_id"][3] == 1, f"{table}.org_id must be NOT NULL"
    assert set(columns["workspace_decisions"]) >= {
        "plan_id",
        "org_id",
        "created_by",
        "question",
        "status",
        "current_revision_id",
        "budget_usd",
        "cost_actual_usd",
        "cost_estimated_usd",
        "created_at",
        "updated_at",
    }
    assert set(columns["decision_sources"]) >= {
        "source_id",
        "plan_id",
        "org_id",
        "label",
        "kind",
        "filename",
        "document_id",
        "content_sha256",
        "char_count",
        "created_at",
    }
    assert set(columns["decision_passages"]) >= {
        "passage_id",
        "source_id",
        "plan_id",
        "org_id",
        "seq",
        "label",
        "heading",
        "start_char",
        "end_char",
        "text",
        "sha256",
        "in_context",
        "created_at",
    }


def test_reopening_the_store_is_idempotent_and_keeps_rows(db_path):
    store = WorkspaceStore(db_path)
    rows = _insert(store, "dp-aaaaaaaaaaaa", ORG_A)
    reopened = WorkspaceStore(db_path)
    assert reopened.get_decision("dp-aaaaaaaaaaaa", ORG_A) == store.get_decision(
        "dp-aaaaaaaaaaaa", ORG_A
    )
    assert reopened.list_passages("dp-aaaaaaaaaaaa", ORG_A) == store.list_passages(
        "dp-aaaaaaaaaaaa", ORG_A
    )
    assert [p.passage_id for p in reopened.list_passages("dp-aaaaaaaaaaaa", ORG_A)] == [
        p.passage_id for p in rows.passages
    ]


def test_reads_are_scoped_to_the_owning_org(db_path):
    store = WorkspaceStore(db_path)
    rows_a = _insert(store, "dp-aaaaaaaaaaaa", ORG_A, question="A question")
    _insert(store, "dp-bbbbbbbbbbbb", ORG_B, question="B question")

    assert store.get_decision("dp-aaaaaaaaaaaa", ORG_A).question == "A question"
    assert store.get_decision("dp-aaaaaaaaaaaa", ORG_B) is None
    assert store.list_sources("dp-aaaaaaaaaaaa", ORG_B) == []
    assert store.list_passages("dp-aaaaaaaaaaaa", ORG_B) == []
    passage_a = rows_a.passages[0].passage_id
    assert store.get_passage("dp-aaaaaaaaaaaa", passage_a, ORG_A) is not None
    assert store.get_passage("dp-aaaaaaaaaaaa", passage_a, ORG_B) is None
    # B's own decision id with A's passage id
    assert store.get_passage("dp-bbbbbbbbbbbb", passage_a, ORG_B) is None

    decisions_a, total_a = store.list_decisions(ORG_A)
    decisions_b, total_b = store.list_decisions(ORG_B)
    assert [d.plan_id for d in decisions_a] == ["dp-aaaaaaaaaaaa"] and total_a == 1
    assert [d.plan_id for d in decisions_b] == ["dp-bbbbbbbbbbbb"] and total_b == 1


@pytest.mark.parametrize("org", ["", "   ", None])
def test_blank_org_reads_nothing(db_path, org):
    store = WorkspaceStore(db_path)
    _insert(store, "dp-aaaaaaaaaaaa", ORG_A)
    with pytest.raises(ValueError):
        store.list_decisions(org)  # type: ignore[arg-type]


def test_null_owner_rows_cannot_be_written(db_path):
    store = WorkspaceStore(db_path)
    rows = new_decision_rows(
        _prepared(), plan_id="dp-cccccccccccc", org_id=ORG_A, user_id="u", document_ids={}
    )
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO workspace_decisions (plan_id, org_id, question, status, "
                "created_at, updated_at) VALUES ('dp-null', NULL, 'q', 'debating', 'x', 'x')"
            )
    finally:
        conn.close()
    store.insert_decision(rows)


def test_passage_seq_is_unique_per_source(db_path):
    store = WorkspaceStore(db_path)
    rows = _insert(store, "dp-aaaaaaaaaaaa", ORG_A)
    first = rows.passages[0]
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO decision_passages (passage_id, source_id, plan_id, org_id, seq, "
                "label, heading, start_char, end_char, text, sha256, in_context, created_at) "
                "VALUES ('psg_dupe', ?, ?, ?, ?, 'S1:P1', NULL, 0, 1, 'x', 'h', 1, 'now')",
                (first.source_id, first.plan_id, first.org_id, first.seq),
            )
    finally:
        conn.close()


def test_passage_content_is_immutable(db_path):
    store = WorkspaceStore(db_path)
    rows = _insert(store, "dp-aaaaaaaaaaaa", ORG_A)
    passage_id = rows.passages[0].passage_id
    conn = sqlite3.connect(db_path)
    try:
        for column, value in (("text", "'changed'"), ("sha256", "'0'"), ("label", "'S9:P9'")):
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                conn.execute(
                    f"UPDATE decision_passages SET {column} = {value} WHERE passage_id = ?",
                    (passage_id,),
                )
        # The context flag is the one mutable passage column.
        conn.execute(
            "UPDATE decision_passages SET in_context = 0 WHERE passage_id = ?", (passage_id,)
        )
        conn.commit()
    finally:
        conn.close()
    assert store.get_passage("dp-aaaaaaaaaaaa", passage_id, ORG_A).in_context is False


def test_a_failed_insert_leaves_no_rows(db_path):
    store = WorkspaceStore(db_path)
    rows = _insert(store, "dp-aaaaaaaaaaaa", ORG_A)
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_decision(rows)  # same ids again
    conn = sqlite3.connect(db_path)
    try:
        counts = [
            conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("workspace_decisions", "decision_sources", "decision_passages")
        ]
    finally:
        conn.close()
    assert counts == [1, len(rows.sources), len(rows.passages)]


def test_list_orders_newest_first_and_pages(db_path):
    store = WorkspaceStore(db_path)
    for n in range(3):
        _insert(store, f"dp-00000000000{n}", ORG_A, question=f"Q{n}")
    decisions, total = store.list_decisions(ORG_A, limit=2, offset=0)
    assert total == 3
    assert [d.question for d in decisions] == ["Q2", "Q1"]
    decisions, _ = store.list_decisions(ORG_A, limit=2, offset=2)
    assert [d.question for d in decisions] == ["Q0"]


def test_source_passage_counts(db_path):
    store = WorkspaceStore(db_path)
    _insert(store, "dp-aaaaaaaaaaaa", ORG_A)
    sources = store.list_sources("dp-aaaaaaaaaaaa", ORG_A)
    assert [(s.label, s.kind, s.passage_count) for s in sources] == [("S1", "pasted", 2)]
