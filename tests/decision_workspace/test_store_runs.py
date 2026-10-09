"""Decision runs and revisions: one running run, preserved finished runs, revision 1, restart sweep."""

from __future__ import annotations

import json
import sqlite3

import pytest

from aragora.decision_workspace import store as store_module
from aragora.decision_workspace.config import ENV_AGENTS, WorkspaceLimits, agent_options
from aragora.decision_workspace.forms import parse_json_intake
from aragora.decision_workspace.intake import prepare_decision
from aragora.decision_workspace.revisions import revision_content_hash
from aragora.decision_workspace.store import (
    INTERRUPTED_RUN_ERROR,
    ORPHANED_DECISION_ERROR,
    SCHEMA_MODULE,
    RunConflictError,
    WorkspaceStore,
    new_decision_rows,
)
from aragora.pipeline.plan_store import PlanStore
from aragora.storage.schema import SchemaManager

ORG_A = "org-a-runs"
ORG_B = "org-b-runs"
PLAN = "dp-runs00000001"
AGENTS = agent_options({ENV_AGENTS: "grok,openai-api|gpt-5.5"})
LIMITS = WorkspaceLimits(max_documents=10, max_file_bytes=1048576, max_pasted_chars=204800)
CONTENT = {
    "recommendation": "Adopt usage pricing.",
    "citations": [],
    "alternatives": [],
    "dissent": [],
    "missing_evidence": [],
    "assumptions": [],
}


def _prepared(question="Should we adopt usage pricing?", pasted="One.\n\nTwo."):
    body = json.dumps(
        {"question": question, "pasted_text": pasted, "agents": ["grok", "openai-api|gpt-5.5"]}
    ).encode()
    return prepare_decision(parse_json_intake(body), options=AGENTS, limits=LIMITS)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "plans.db"
    PlanStore(str(path))
    return str(path)


@pytest.fixture
def store(db_path):
    return WorkspaceStore(db_path)


def _insert(store, plan_id=PLAN, org_id=ORG_A, **kwargs):
    rows = new_decision_rows(
        _prepared(**kwargs), plan_id=plan_id, org_id=org_id, user_id="user-a", document_ids={}
    )
    store.insert_decision(rows)
    return rows


def _sql(db_path, query, params=()):
    conn = sqlite3.connect(db_path)
    try:
        result = conn.execute(query, params).fetchall()
        conn.commit()
        return result
    finally:
        conn.close()


def test_a_v1_database_migrates_to_v2_and_keeps_its_rows(tmp_path):
    path = str(tmp_path / "plans.db")
    conn = sqlite3.connect(path)
    try:
        SchemaManager(conn, SCHEMA_MODULE, current_version=1).ensure_schema(
            initial_schema=store_module._SCHEMA_V1
        )
        conn.execute(
            "INSERT INTO workspace_decisions (plan_id, org_id, question, status, created_at, "
            "updated_at) VALUES ('dp-old', ?, 'Old?', 'debating', 'then', 'then')",
            (ORG_A,),
        )
        conn.commit()
    finally:
        conn.close()

    migrated = WorkspaceStore(path)
    assert _sql(
        path, "SELECT version FROM _schema_versions WHERE module = ?", (SCHEMA_MODULE,)
    ) == [(2,)]
    tables = {r[0] for r in _sql(path, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"decision_runs", "decision_revisions"} <= tables
    assert migrated.get_decision("dp-old", ORG_A).question == "Old?"
    assert migrated.list_runs("dp-old", ORG_A) == []


def test_new_decision_starts_with_one_running_run_owned_by_the_org(store):
    rows = _insert(store)
    runs = store.list_runs(PLAN, ORG_A)
    assert [(r.run_id, r.status, r.agents, r.rounds, r.started_by) for r in runs] == [
        (rows.run.run_id, "running", ("grok", "openai-api|gpt-5.5"), 1, "user-a")
    ]
    assert store.list_runs(PLAN, ORG_B) == []
    assert store.get_run(rows.run.run_id, ORG_B) is None


def test_passages_over_the_context_budget_are_marked_and_counted(store):
    pasted = "\n\n".join(
        ["Usage pricing works for analytics."] + [f"Unrelated note number {n}." for n in range(6)]
    )
    rows = new_decision_rows(
        _prepared(question="Does usage pricing work for analytics?", pasted=pasted),
        plan_id=PLAN,
        org_id=ORG_A,
        user_id="user-a",
        document_ids={},
        context_char_budget=60,
    )
    store.insert_decision(rows)
    passages = store.list_passages(PLAN, ORG_A)
    flags = [p.in_context for p in passages]
    assert flags[0] is True
    assert flags.count(False) > 0
    assert sum(len(p.text) for p in passages if p.in_context) <= 60
    decision = store.get_decision(PLAN, ORG_A)
    assert decision.omitted_passage_count == flags.count(False)
    assert rows.decision.omitted_passage_count == flags.count(False)


def test_under_budget_nothing_is_omitted(store):
    _insert(store)
    assert store.get_decision(PLAN, ORG_A).omitted_passage_count == 0


def test_completing_a_run_creates_revision_one_as_current(store):
    rows = _insert(store)
    run_id = rows.run.run_id
    assert store.update_run(run_id, ORG_A, debate_id="ws_debate1", budget_usd=1.0)
    assert store.finish_run(
        run_id,
        ORG_A,
        status="completed",
        result={"debate": {"final_answer": "x"}},
        cost_actual_usd=0.02,
        cost_estimated_usd=0.05,
        revision_content=CONTENT,
    )
    decision = store.get_decision(PLAN, ORG_A)
    revisions = store.list_revisions(PLAN, ORG_A)
    assert len(revisions) == 1
    revision = revisions[0]
    assert (revision.number, revision.status, revision.origin, revision.parent_revision_id) == (
        1,
        "current",
        "debate",
        None,
    )
    assert revision.author_id == "user-a"
    assert revision.content == CONTENT
    assert revision.content_hash == revision_content_hash(PLAN, 1, None, CONTENT)
    assert decision.status == "ready"
    assert decision.current_revision_id == revision.revision_id
    assert (decision.cost_actual_usd, decision.cost_estimated_usd, decision.budget_usd) == (
        0.02,
        0.05,
        1.0,
    )
    run = store.get_run(run_id, ORG_A)
    assert (run.status, run.debate_id, run.result) == (
        "completed",
        "ws_debate1",
        {"debate": {"final_answer": "x"}},
    )
    assert run.finished_at is not None
    assert store.get_revision(PLAN, revision.revision_id, ORG_B) is None


def test_failing_a_run_keeps_its_error_and_partial_output(store):
    rows = _insert(store)
    store.finish_run(
        rows.run.run_id,
        ORG_A,
        status="failed",
        error="synthesis invalid",
        result={"synthesis": {"raw_outputs": ["bad", "worse"]}},
    )
    decision = store.get_decision(PLAN, ORG_A)
    run = store.get_run(rows.run.run_id, ORG_A)
    assert decision.status == "failed"
    assert decision.current_revision_id is None
    assert (run.status, run.error) == ("failed", "synthesis invalid")
    assert run.result["synthesis"]["raw_outputs"] == ["bad", "worse"]
    assert store.list_revisions(PLAN, ORG_A) == []


def test_finished_runs_cannot_change_or_be_deleted(store, db_path):
    rows = _insert(store)
    run_id = rows.run.run_id
    store.finish_run(run_id, ORG_A, status="budget_exceeded", error="over budget")
    assert store.finish_run(run_id, ORG_A, status="completed") is False
    assert store.update_run(run_id, ORG_A, debate_id="other") is False
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        _sql(db_path, "UPDATE decision_runs SET error = 'x' WHERE run_id = ?", (run_id,))
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        _sql(db_path, "DELETE FROM decision_runs WHERE run_id = ?", (run_id,))
    assert store.get_run(run_id, ORG_A).status == "budget_exceeded"


def test_another_org_cannot_finish_or_update_a_run(store):
    rows = _insert(store)
    assert store.update_run(rows.run.run_id, ORG_B, debate_id="x") is False
    assert store.finish_run(rows.run.run_id, ORG_B, status="failed", error="x") is False
    assert store.get_run(rows.run.run_id, ORG_A).status == "running"


def test_rerun_starts_a_new_run_and_keeps_the_old_one(store):
    rows = _insert(store)
    store.finish_run(rows.run.run_id, ORG_A, status="failed", error="boom")
    new_run = store.start_run(PLAN, ORG_A, "user-a2")
    runs = store.list_runs(PLAN, ORG_A)
    assert [r.run_id for r in runs] == [new_run.run_id, rows.run.run_id]
    assert (runs[0].status, runs[0].started_by, runs[0].agents) == (
        "running",
        "user-a2",
        ("grok", "openai-api|gpt-5.5"),
    )
    assert (runs[1].status, runs[1].error) == ("failed", "boom")
    assert store.get_decision(PLAN, ORG_A).status == "debating"


def test_double_rerun_starts_only_one_run(store):
    rows = _insert(store)
    store.finish_run(rows.run.run_id, ORG_A, status="failed", error="boom")
    first = store.start_run(PLAN, ORG_A, "user-a")
    with pytest.raises(RunConflictError) as conflict:
        store.start_run(PLAN, ORG_A, "user-a")
    assert conflict.value.code == "run_in_progress"
    assert conflict.value.run_id == first.run_id
    assert len(store.list_runs(PLAN, ORG_A)) == 2


def test_only_one_running_run_even_bypassing_the_store(store, db_path):
    rows = _insert(store)
    with pytest.raises(sqlite3.IntegrityError):
        _sql(
            db_path,
            "INSERT INTO decision_runs (run_id, plan_id, org_id, status, started_at) "
            "VALUES ('run_dupe', ?, ?, 'running', 'now')",
            (PLAN, ORG_A),
        )
    assert [r.run_id for r in store.list_runs(PLAN, ORG_A)] == [rows.run.run_id]


def test_rerun_needs_a_failed_decision_of_the_callers_org(store):
    rows = _insert(store)
    with pytest.raises(RunConflictError) as conflict:
        store.start_run(PLAN, ORG_A, "user-a")
    assert conflict.value.code == "run_in_progress"
    store.finish_run(rows.run.run_id, ORG_A, status="completed", revision_content=CONTENT)
    with pytest.raises(RunConflictError) as conflict:
        store.start_run(PLAN, ORG_A, "user-a")
    assert conflict.value.code == "decision_not_failed"
    with pytest.raises(LookupError):
        store.start_run(PLAN, ORG_B, "user-b")


def test_revisions_are_immutable_and_never_deleted(store, db_path):
    rows = _insert(store)
    store.finish_run(rows.run.run_id, ORG_A, status="completed", revision_content=CONTENT)
    revision_id = store.list_revisions(PLAN, ORG_A)[0].revision_id
    for statement in (
        "UPDATE decision_revisions SET content_json = '{}' WHERE revision_id = ?",
        "UPDATE decision_revisions SET content_hash = 'x' WHERE revision_id = ?",
    ):
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            _sql(db_path, statement, (revision_id,))
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        _sql(db_path, "DELETE FROM decision_revisions WHERE revision_id = ?", (revision_id,))


def test_restart_sweep_interrupts_running_runs_and_fails_their_decisions(store):
    rows = _insert(store)
    other = _insert(store, plan_id="dp-runs00000002", org_id=ORG_B)
    interrupted, failed = store.sweep_after_restart(started_before="9999")
    assert (interrupted, failed) == (2, 2)
    for plan_id, org_id, run in ((PLAN, ORG_A, rows.run), ("dp-runs00000002", ORG_B, other.run)):
        swept = store.get_run(run.run_id, org_id)
        assert (swept.status, swept.error) == ("interrupted", INTERRUPTED_RUN_ERROR)
        assert swept.finished_at is not None
        assert store.get_decision(plan_id, org_id).status == "failed"
        assert len(store.list_runs(plan_id, org_id)) == 1
    # The decision can be rerun, and nothing restarts by itself.
    assert store.start_run(PLAN, ORG_A, "user-a").status == "running"


def test_restart_sweep_leaves_runs_started_by_this_process_alone(store):
    rows = _insert(store)
    assert store.sweep_after_restart(started_before="0000") == (0, 0)
    assert store.get_run(rows.run.run_id, ORG_A).status == "running"
    assert store.get_decision(PLAN, ORG_A).status == "debating"


def test_restart_sweep_fails_a_debating_decision_without_a_run(store, db_path):
    rows = new_decision_rows(
        _prepared(), plan_id=PLAN, org_id=ORG_A, user_id="user-a", document_ids={}
    )
    store.insert_decision(rows.__class__(rows.decision, rows.sources, rows.passages, None))
    assert store.list_runs(PLAN, ORG_A) == []
    assert store.sweep_after_restart(started_before="0000") == (0, 1)
    decision = store.get_decision(PLAN, ORG_A)
    runs = store.list_runs(PLAN, ORG_A)
    assert decision.status == "failed"
    assert [(r.status, r.error) for r in runs] == [("interrupted", ORPHANED_DECISION_ERROR)]
