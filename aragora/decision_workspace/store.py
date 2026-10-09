"""Workspace decision, source, passage, run and revision tables in ``plans.db``.

Every row carries a non-blank ``org_id`` and every read takes the caller's
org: a row of another org is simply not found. Passage content is immutable
once written (a trigger rejects any update except the ``in_context`` flag),
and source rows cannot be updated at all, so passage labels, text and hashes
stay stable for the life of the decision.

Runs are never deleted and a finished run can no longer change; at most one
run per decision is ``running``. Revision content is immutable once written
and at most one revision per decision is ``current``.

The tables are schema module ``decision_workspace`` (version 2) in
``_schema_versions``, next to the ``plans`` table of the same file.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aragora.decision_workspace.config import context_char_budget as configured_context_budget
from aragora.decision_workspace.context import select_context
from aragora.decision_workspace.intake import PreparedDecision
from aragora.decision_workspace.revisions import (
    ORIGIN_DEBATE,
    REVISION_CURRENT,
    REVISION_SUPERSEDED,
    revision_content_hash,
)
from aragora.storage.schema import SchemaManager

SCHEMA_MODULE = "decision_workspace"
SCHEMA_VERSION = 2

STATUS_DEBATING = "debating"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
DECISION_STATUSES = (STATUS_DEBATING, STATUS_READY, STATUS_FAILED)

RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_INTERRUPTED = "interrupted"
RUN_BUDGET_EXCEEDED = "budget_exceeded"
RUN_STATUSES = (RUN_RUNNING, RUN_COMPLETED, RUN_FAILED, RUN_INTERRUPTED, RUN_BUDGET_EXCEEDED)

INTERRUPTED_RUN_ERROR = (
    "The server restarted while this run was in progress, so it was stopped. "
    "Rerun the decision to start a new run."
)
ORPHANED_DECISION_ERROR = (
    "The debate for this decision was not running when the server started. "
    "Rerun the decision to start a new run."
)

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS workspace_decisions (
    plan_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL CHECK (length(trim(org_id)) > 0),
    created_by TEXT,
    question TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('debating', 'ready', 'failed')),
    agents_json TEXT NOT NULL DEFAULT '[]',
    rounds INTEGER NOT NULL DEFAULT 1,
    current_revision_id TEXT,
    budget_usd REAL,
    cost_actual_usd REAL NOT NULL DEFAULT 0,
    cost_estimated_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workspace_decisions_org
    ON workspace_decisions(org_id, created_at);

CREATE TABLE IF NOT EXISTS decision_sources (
    source_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    org_id TEXT NOT NULL CHECK (length(trim(org_id)) > 0),
    seq INTEGER NOT NULL,
    label TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('upload', 'pasted')),
    filename TEXT,
    document_id TEXT,
    content_sha256 TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (plan_id, seq),
    UNIQUE (plan_id, label)
);
CREATE INDEX IF NOT EXISTS idx_decision_sources_plan ON decision_sources(plan_id, org_id);

CREATE TABLE IF NOT EXISTS decision_passages (
    passage_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    org_id TEXT NOT NULL CHECK (length(trim(org_id)) > 0),
    seq INTEGER NOT NULL,
    label TEXT NOT NULL,
    heading TEXT,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    text TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    in_context INTEGER NOT NULL DEFAULT 1 CHECK (in_context IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (source_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_decision_passages_plan ON decision_passages(plan_id, org_id);

CREATE TRIGGER IF NOT EXISTS decision_passages_immutable
BEFORE UPDATE OF passage_id, source_id, plan_id, org_id, seq, label, heading,
    start_char, end_char, text, sha256, created_at ON decision_passages
BEGIN
    SELECT RAISE(ABORT, 'decision passages are immutable');
END;

CREATE TRIGGER IF NOT EXISTS decision_sources_immutable
BEFORE UPDATE ON decision_sources
BEGIN
    SELECT RAISE(ABORT, 'decision sources are immutable');
END;
"""

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS decision_runs (
    run_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    org_id TEXT NOT NULL CHECK (length(trim(org_id)) > 0),
    started_by TEXT,
    debate_id TEXT,
    status TEXT NOT NULL CHECK (status IN
        ('running', 'completed', 'failed', 'interrupted', 'budget_exceeded')),
    agents_json TEXT NOT NULL DEFAULT '[]',
    rounds INTEGER NOT NULL DEFAULT 1,
    budget_usd REAL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT,
    cost_actual_usd REAL NOT NULL DEFAULT 0,
    cost_estimated_usd REAL NOT NULL DEFAULT 0,
    result_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_decision_runs_plan ON decision_runs(plan_id, org_id, started_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_decision_runs_one_running
    ON decision_runs(plan_id) WHERE status = 'running';

CREATE TRIGGER IF NOT EXISTS decision_runs_finished_immutable
BEFORE UPDATE ON decision_runs
WHEN OLD.status != 'running'
BEGIN
    SELECT RAISE(ABORT, 'finished decision runs are immutable');
END;

CREATE TRIGGER IF NOT EXISTS decision_runs_owner_immutable
BEFORE UPDATE OF run_id, plan_id, org_id, started_by, agents_json, rounds, started_at
    ON decision_runs
BEGIN
    SELECT RAISE(ABORT, 'decision run identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS decision_runs_never_deleted
BEFORE DELETE ON decision_runs
BEGIN
    SELECT RAISE(ABORT, 'decision runs are never deleted');
END;

CREATE TABLE IF NOT EXISTS decision_revisions (
    revision_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    org_id TEXT NOT NULL CHECK (length(trim(org_id)) > 0),
    number INTEGER NOT NULL CHECK (number >= 1),
    parent_revision_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('draft', 'current', 'superseded')),
    origin TEXT NOT NULL CHECK (origin IN ('debate', 'user_edit')),
    author_id TEXT,
    content_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (plan_id, number)
);
CREATE INDEX IF NOT EXISTS idx_decision_revisions_plan ON decision_revisions(plan_id, org_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_decision_revisions_one_current
    ON decision_revisions(plan_id) WHERE status = 'current';

CREATE TRIGGER IF NOT EXISTS decision_revisions_immutable
BEFORE UPDATE OF revision_id, plan_id, org_id, number, parent_revision_id, origin, author_id,
    content_json, content_hash, created_at ON decision_revisions
BEGIN
    SELECT RAISE(ABORT, 'decision revisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS decision_revisions_never_deleted
BEFORE DELETE ON decision_revisions
BEGIN
    SELECT RAISE(ABORT, 'decision revisions are never deleted');
END;
"""


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    plan_id: str
    org_id: str
    created_by: str | None
    question: str
    status: str
    agents: tuple[str, ...]
    rounds: int
    current_revision_id: str | None
    budget_usd: float | None
    cost_actual_usd: float
    cost_estimated_usd: float
    created_at: str
    updated_at: str
    source_count: int = 0
    passage_count: int = 0
    omitted_passage_count: int = 0


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    plan_id: str
    org_id: str
    started_by: str | None
    debate_id: str | None
    status: str
    agents: tuple[str, ...]
    rounds: int
    budget_usd: float | None
    started_at: str
    finished_at: str | None
    error: str | None
    cost_actual_usd: float
    cost_estimated_usd: float
    result: dict[str, Any] | None = field(default=None, compare=False)


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    revision_id: str
    plan_id: str
    org_id: str
    number: int
    parent_revision_id: str | None
    status: str
    origin: str
    author_id: str | None
    content: dict[str, Any] = field(compare=False)
    content_hash: str
    created_at: str


class RunConflictError(Exception):
    """A run cannot start: one is already running, or the decision is not failed."""

    def __init__(self, code: str, message: str, run_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.run_id = run_id


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    plan_id: str
    org_id: str
    seq: int
    label: str
    kind: str
    filename: str | None
    document_id: str | None
    content_sha256: str
    char_count: int
    created_at: str
    passage_count: int = 0


@dataclass(frozen=True, slots=True)
class PassageRecord:
    passage_id: str
    source_id: str
    plan_id: str
    org_id: str
    seq: int
    label: str
    heading: str | None
    start_char: int
    end_char: int
    text: str
    sha256: str
    in_context: bool
    created_at: str
    source_label: str


@dataclass(frozen=True, slots=True)
class DecisionRows:
    """Everything one intake writes, built before anything is stored."""

    decision: DecisionRecord
    sources: tuple[SourceRecord, ...]
    passages: tuple[PassageRecord, ...]
    run: RunRecord | None = None


def new_decision_rows(
    prepared: PreparedDecision,
    *,
    plan_id: str,
    org_id: str,
    user_id: str | None,
    document_ids: Mapping[str, str],
    context_char_budget: int | None = None,
) -> DecisionRows:
    """Rows for a new ``debating`` decision with its first ``running`` run.

    ``document_ids`` maps source label to document id. Passages that do not
    fit the context budget (``ARAGORA_WORKSPACE_CONTEXT_CHAR_BUDGET`` unless
    given) are stored with ``in_context`` false.
    """
    _require_org(org_id)
    now = _now()
    sources: list[SourceRecord] = []
    passages: list[PassageRecord] = []
    for seq, prepared_source in enumerate(prepared.sources, start=1):
        source = SourceRecord(
            source_id=f"src_{uuid.uuid4().hex}",
            plan_id=plan_id,
            org_id=org_id,
            seq=seq,
            label=prepared_source.label,
            kind=prepared_source.kind,
            filename=prepared_source.filename,
            document_id=document_ids.get(prepared_source.label),
            content_sha256=prepared_source.content_sha256,
            char_count=prepared_source.char_count,
            created_at=now,
            passage_count=len(prepared_source.passages),
        )
        sources.append(source)
        passages.extend(
            PassageRecord(
                passage_id=f"psg_{uuid.uuid4().hex}",
                source_id=source.source_id,
                plan_id=plan_id,
                org_id=org_id,
                seq=span.seq,
                label=f"{source.label}:P{span.seq}",
                heading=span.heading,
                start_char=span.start_char,
                end_char=span.end_char,
                text=span.text,
                sha256=span.sha256,
                in_context=True,
                created_at=now,
                source_label=source.label,
            )
            for span in prepared_source.passages
        )
    budget = configured_context_budget() if context_char_budget is None else context_char_budget
    selection = select_context(prepared.question, passages, budget)
    passages = [
        passage if keep else replace(passage, in_context=False)
        for passage, keep in zip(passages, selection.in_context)
    ]
    run = RunRecord(
        run_id=_new_run_id(),
        plan_id=plan_id,
        org_id=org_id,
        started_by=user_id,
        debate_id=None,
        status=RUN_RUNNING,
        agents=prepared.agents,
        rounds=prepared.rounds,
        budget_usd=None,
        started_at=now,
        finished_at=None,
        error=None,
        cost_actual_usd=0.0,
        cost_estimated_usd=0.0,
    )
    decision = DecisionRecord(
        plan_id=plan_id,
        org_id=org_id,
        created_by=user_id,
        question=prepared.question,
        status=STATUS_DEBATING,
        agents=prepared.agents,
        rounds=prepared.rounds,
        current_revision_id=None,
        budget_usd=None,
        cost_actual_usd=0.0,
        cost_estimated_usd=0.0,
        created_at=now,
        updated_at=now,
        source_count=len(sources),
        passage_count=len(passages),
        omitted_passage_count=selection.omitted_count,
    )
    return DecisionRows(
        decision=decision, sources=tuple(sources), passages=tuple(passages), run=run
    )


class WorkspaceStore:
    """Org-scoped access to the workspace tables of one ``plans.db`` file."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        conn = self._connect()
        try:
            manager = SchemaManager(conn, SCHEMA_MODULE, current_version=SCHEMA_VERSION)
            manager.register_migration(
                1, 2, sql=_SCHEMA_V2, description="decision runs and revisions"
            )
            manager.ensure_schema(initial_schema=_SCHEMA_V1)
        finally:
            conn.close()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def insert_decision(self, rows: DecisionRows) -> None:
        """Write a decision with its sources, passages and first run in one transaction."""
        decision = rows.decision
        _require_org(decision.org_id)
        if any(r.org_id != decision.org_id or r.plan_id != decision.plan_id for r in rows.sources):
            raise ValueError("every source must belong to the decision's plan and org")
        if any(r.org_id != decision.org_id or r.plan_id != decision.plan_id for r in rows.passages):
            raise ValueError("every passage must belong to the decision's plan and org")
        run = rows.run
        if run is not None and (run.org_id != decision.org_id or run.plan_id != decision.plan_id):
            raise ValueError("the run must belong to the decision's plan and org")
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO workspace_decisions (plan_id, org_id, created_by, question, "
                    "status, agents_json, rounds, current_revision_id, budget_usd, "
                    "cost_actual_usd, cost_estimated_usd, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        decision.plan_id,
                        decision.org_id,
                        decision.created_by,
                        decision.question,
                        decision.status,
                        json.dumps(list(decision.agents)),
                        decision.rounds,
                        decision.current_revision_id,
                        decision.budget_usd,
                        decision.cost_actual_usd,
                        decision.cost_estimated_usd,
                        decision.created_at,
                        decision.updated_at,
                    ),
                )
                conn.executemany(
                    "INSERT INTO decision_sources (source_id, plan_id, org_id, seq, label, kind, "
                    "filename, document_id, content_sha256, char_count, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            s.source_id,
                            s.plan_id,
                            s.org_id,
                            s.seq,
                            s.label,
                            s.kind,
                            s.filename,
                            s.document_id,
                            s.content_sha256,
                            s.char_count,
                            s.created_at,
                        )
                        for s in rows.sources
                    ],
                )
                conn.executemany(
                    "INSERT INTO decision_passages (passage_id, source_id, plan_id, org_id, seq, "
                    "label, heading, start_char, end_char, text, sha256, in_context, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            p.passage_id,
                            p.source_id,
                            p.plan_id,
                            p.org_id,
                            p.seq,
                            p.label,
                            p.heading,
                            p.start_char,
                            p.end_char,
                            p.text,
                            p.sha256,
                            int(p.in_context),
                            p.created_at,
                        )
                        for p in rows.passages
                    ],
                )
                if run is not None:
                    _insert_run(conn, run)
        finally:
            conn.close()

    # -- runs ----------------------------------------------------------------

    def start_run(
        self, plan_id: str, org_id: str, user_id: str | None, *, rerun_of: str = STATUS_FAILED
    ) -> RunRecord:
        """Start a new ``running`` run for a ``failed`` decision and set it ``debating``.

        Raises :class:`LookupError` for a decision the org cannot see and
        :class:`RunConflictError` when a run is already running (including a
        concurrent double submit) or the decision is not ``failed``.
        """
        _require_org(org_id)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT status, agents_json, rounds FROM workspace_decisions "
                    "WHERE plan_id = ? AND org_id = ?",
                    (plan_id, org_id),
                ).fetchone()
                if row is None:
                    raise LookupError(plan_id)
                running = conn.execute(
                    "SELECT run_id FROM decision_runs WHERE plan_id = ? AND status = 'running'",
                    (plan_id,),
                ).fetchone()
                if running is not None or row["status"] == STATUS_DEBATING:
                    raise RunConflictError(
                        "run_in_progress",
                        "A run of this decision is already in progress.",
                        running["run_id"] if running is not None else None,
                    )
                if row["status"] != rerun_of:
                    raise RunConflictError(
                        "decision_not_failed",
                        f"Only a {rerun_of} decision can be rerun; this one is {row['status']}.",
                    )
                now = _now()
                run = RunRecord(
                    run_id=_new_run_id(),
                    plan_id=plan_id,
                    org_id=org_id,
                    started_by=user_id,
                    debate_id=None,
                    status=RUN_RUNNING,
                    agents=tuple(_json_list(row["agents_json"])),
                    rounds=row["rounds"],
                    budget_usd=None,
                    started_at=now,
                    finished_at=None,
                    error=None,
                    cost_actual_usd=0.0,
                    cost_estimated_usd=0.0,
                )
                _insert_run(conn, run)
                conn.execute(
                    "UPDATE workspace_decisions SET status = ?, updated_at = ? "
                    "WHERE plan_id = ? AND org_id = ?",
                    (STATUS_DEBATING, now, plan_id, org_id),
                )
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        except sqlite3.IntegrityError as exc:
            raise RunConflictError(
                "run_in_progress", "A run of this decision is already in progress."
            ) from exc
        finally:
            conn.close()
        return run

    def update_run(
        self,
        run_id: str,
        org_id: str,
        *,
        debate_id: str | None = None,
        budget_usd: float | None = None,
        cost_actual_usd: float | None = None,
        cost_estimated_usd: float | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> bool:
        """Record progress on a ``running`` run; False when it is no longer running."""
        _require_org(org_id)
        assignments: list[str] = []
        params: list[object] = []
        for column, value in (
            ("debate_id", debate_id),
            ("budget_usd", budget_usd),
            ("cost_actual_usd", cost_actual_usd),
            ("cost_estimated_usd", cost_estimated_usd),
            ("result_json", None if result is None else _dump(result)),
        ):
            if value is not None:
                assignments.append(f"{column} = ?")
                params.append(value)
        if not assignments:
            return True
        conn = self._connect()
        try:
            with conn:
                cursor = conn.execute(
                    f"UPDATE decision_runs SET {', '.join(assignments)} "  # noqa: S608 -- fixed columns
                    "WHERE run_id = ? AND org_id = ? AND status = 'running'",
                    (*params, run_id, org_id),
                )
                if budget_usd is not None and cursor.rowcount == 1:
                    conn.execute(
                        "UPDATE workspace_decisions SET budget_usd = ? WHERE org_id = ? AND "
                        "plan_id = (SELECT plan_id FROM decision_runs WHERE run_id = ?)",
                        (budget_usd, org_id, run_id),
                    )
        finally:
            conn.close()
        return cursor.rowcount == 1

    def finish_run(
        self,
        run_id: str,
        org_id: str,
        *,
        status: str,
        error: str | None = None,
        result: Mapping[str, Any] | None = None,
        debate_id: str | None = None,
        cost_actual_usd: float | None = None,
        cost_estimated_usd: float | None = None,
        revision_content: Mapping[str, Any] | None = None,
    ) -> bool:
        """End a ``running`` run and settle its decision in one transaction.

        ``completed`` makes the decision ``ready`` and, with
        ``revision_content``, writes the next debate revision as ``current``
        (the previous current one becomes ``superseded``); any other status
        makes the decision ``failed``. The decision's costs become the sum of
        its runs' costs. Returns False, changing nothing, when the run is no
        longer running (for example after the restart sweep stopped it).
        """
        _require_org(org_id)
        if status not in RUN_STATUSES or status == RUN_RUNNING:
            raise ValueError(f"invalid final run status {status!r}")
        if revision_content is not None and status != RUN_COMPLETED:
            raise ValueError("only a completed run creates a revision")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT plan_id, started_by, debate_id, cost_actual_usd, cost_estimated_usd "
                    "FROM decision_runs WHERE run_id = ? AND org_id = ? AND status = 'running'",
                    (run_id, org_id),
                ).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return False
                plan_id = row["plan_id"]
                now = _now()
                conn.execute(
                    "UPDATE decision_runs SET status = ?, finished_at = ?, error = ?, "
                    "result_json = COALESCE(?, result_json), debate_id = ?, "
                    "cost_actual_usd = ?, cost_estimated_usd = ? WHERE run_id = ?",
                    (
                        status,
                        now,
                        error,
                        None if result is None else _dump(result),
                        debate_id if debate_id is not None else row["debate_id"],
                        row["cost_actual_usd"] if cost_actual_usd is None else cost_actual_usd,
                        (
                            row["cost_estimated_usd"]
                            if cost_estimated_usd is None
                            else cost_estimated_usd
                        ),
                        run_id,
                    ),
                )
                revision = None
                if revision_content is not None:
                    revision = _insert_debate_revision(
                        conn, plan_id, org_id, row["started_by"], revision_content, now
                    )
                conn.execute(
                    "UPDATE workspace_decisions SET status = ?, updated_at = ?, "
                    "current_revision_id = COALESCE(?, current_revision_id), "
                    "cost_actual_usd = (SELECT COALESCE(SUM(cost_actual_usd), 0) "
                    "FROM decision_runs WHERE plan_id = ? AND org_id = ?), "
                    "cost_estimated_usd = (SELECT COALESCE(SUM(cost_estimated_usd), 0) "
                    "FROM decision_runs WHERE plan_id = ? AND org_id = ?) "
                    "WHERE plan_id = ? AND org_id = ?",
                    (
                        STATUS_READY if status == RUN_COMPLETED else STATUS_FAILED,
                        now,
                        revision.revision_id if revision is not None else None,
                        plan_id,
                        org_id,
                        plan_id,
                        org_id,
                        plan_id,
                        org_id,
                    ),
                )
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return True

    def get_run(self, run_id: str, org_id: str) -> RunRecord | None:
        _require_org(org_id)
        runs = self._select_runs("run_id = ? AND org_id = ?", (run_id, org_id))
        return runs[0] if runs else None

    def list_runs(self, plan_id: str, org_id: str) -> list[RunRecord]:
        """The decision's runs, newest first."""
        _require_org(org_id)
        return self._select_runs(
            "plan_id = ? AND org_id = ?",
            (plan_id, org_id),
            order="ORDER BY started_at DESC, rowid DESC",
        )

    def sweep_after_restart(self, *, started_before: str) -> tuple[int, int]:
        """Settle runs a previous server process left behind, across all orgs.

        Runs still ``running`` that started before ``started_before`` become
        ``interrupted``; their decisions, and any ``debating`` decision left
        without a running run, become ``failed`` so they can be rerun. A
        decision that never had a run gets an ``interrupted`` run row holding
        the explanation. Returns ``(runs_interrupted, decisions_failed)``.
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                now = _now()
                stale_plans = {
                    row["plan_id"]
                    for row in conn.execute(
                        "SELECT plan_id FROM decision_runs "
                        "WHERE status = 'running' AND started_at < ?",
                        (started_before,),
                    )
                }
                interrupted = conn.execute(
                    "UPDATE decision_runs SET status = 'interrupted', finished_at = ?, error = ? "
                    "WHERE status = 'running' AND started_at < ?",
                    (now, INTERRUPTED_RUN_ERROR, started_before),
                ).rowcount
                orphans = conn.execute(
                    "SELECT d.plan_id, d.org_id, d.agents_json, d.rounds FROM "
                    "workspace_decisions d WHERE d.status = 'debating' AND NOT EXISTS "
                    "(SELECT 1 FROM decision_runs r WHERE r.plan_id = d.plan_id "
                    "AND r.status = 'running')"
                ).fetchall()
                for orphan in orphans:
                    if orphan["plan_id"] not in stale_plans:
                        _insert_run(
                            conn,
                            RunRecord(
                                run_id=_new_run_id(),
                                plan_id=orphan["plan_id"],
                                org_id=orphan["org_id"],
                                started_by=None,
                                debate_id=None,
                                status=RUN_INTERRUPTED,
                                agents=tuple(_json_list(orphan["agents_json"])),
                                rounds=orphan["rounds"],
                                budget_usd=None,
                                started_at=now,
                                finished_at=now,
                                error=ORPHANED_DECISION_ERROR,
                                cost_actual_usd=0.0,
                                cost_estimated_usd=0.0,
                            ),
                        )
                    conn.execute(
                        "UPDATE workspace_decisions SET status = 'failed', updated_at = ?, "
                        "cost_actual_usd = (SELECT COALESCE(SUM(cost_actual_usd), 0) "
                        "FROM decision_runs WHERE plan_id = ? AND org_id = ?), "
                        "cost_estimated_usd = (SELECT COALESCE(SUM(cost_estimated_usd), 0) "
                        "FROM decision_runs WHERE plan_id = ? AND org_id = ?) "
                        "WHERE plan_id = ? AND org_id = ?",
                        (now, *((orphan["plan_id"], orphan["org_id"]) * 3)),
                    )
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return interrupted, len(orphans)

    # -- revisions -----------------------------------------------------------

    def get_revision(self, plan_id: str, revision_id: str, org_id: str) -> RevisionRecord | None:
        _require_org(org_id)
        revisions = self._select_revisions(
            "plan_id = ? AND revision_id = ? AND org_id = ?", (plan_id, revision_id, org_id)
        )
        return revisions[0] if revisions else None

    def list_revisions(self, plan_id: str, org_id: str) -> list[RevisionRecord]:
        """The decision's revisions by number."""
        _require_org(org_id)
        return self._select_revisions(
            "plan_id = ? AND org_id = ?", (plan_id, org_id), order="ORDER BY number"
        )

    def get_decision(self, plan_id: str, org_id: str) -> DecisionRecord | None:
        _require_org(org_id)
        rows = self._select_decisions("d.plan_id = ? AND d.org_id = ?", (plan_id, org_id))
        return rows[0] if rows else None

    def list_decisions(
        self, org_id: str, *, limit: int = DEFAULT_LIST_LIMIT, offset: int = 0
    ) -> tuple[list[DecisionRecord], int]:
        """The org's decisions, newest first, and the org's total count."""
        _require_org(org_id)
        limit = max(1, min(int(limit), MAX_LIST_LIMIT))
        offset = max(0, int(offset))
        decisions = self._select_decisions(
            "d.org_id = ?",
            (org_id,),
            suffix="ORDER BY d.created_at DESC, d.rowid DESC LIMIT ? OFFSET ?",
            suffix_params=(limit, offset),
        )
        conn = self._connect()
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM workspace_decisions WHERE org_id = ?", (org_id,)
            ).fetchone()[0]
        finally:
            conn.close()
        return decisions, int(total)

    def list_sources(self, plan_id: str, org_id: str) -> list[SourceRecord]:
        _require_org(org_id)
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM decision_passages p "
                "WHERE p.source_id = s.source_id AND p.org_id = s.org_id) AS passage_count "
                "FROM decision_sources s WHERE s.plan_id = ? AND s.org_id = ? ORDER BY s.seq",
                (plan_id, org_id),
            ).fetchall()
        finally:
            conn.close()
        return [
            SourceRecord(
                source_id=r["source_id"],
                plan_id=r["plan_id"],
                org_id=r["org_id"],
                seq=r["seq"],
                label=r["label"],
                kind=r["kind"],
                filename=r["filename"],
                document_id=r["document_id"],
                content_sha256=r["content_sha256"],
                char_count=r["char_count"],
                created_at=r["created_at"],
                passage_count=r["passage_count"],
            )
            for r in rows
        ]

    def list_passages(self, plan_id: str, org_id: str) -> list[PassageRecord]:
        """Every passage of the decision, in source order then passage order."""
        _require_org(org_id)
        return self._select_passages(
            "p.plan_id = ? AND p.org_id = ?", (plan_id, org_id), order="ORDER BY s.seq, p.seq"
        )

    def get_passage(self, plan_id: str, passage_id: str, org_id: str) -> PassageRecord | None:
        _require_org(org_id)
        rows = self._select_passages(
            "p.plan_id = ? AND p.passage_id = ? AND p.org_id = ?", (plan_id, passage_id, org_id)
        )
        return rows[0] if rows else None

    def _select_decisions(
        self,
        where: str,
        params: tuple[object, ...],
        *,
        suffix: str = "",
        suffix_params: tuple[object, ...] = (),
    ) -> list[DecisionRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT d.*, "
                "(SELECT COUNT(*) FROM decision_sources s "
                "WHERE s.plan_id = d.plan_id AND s.org_id = d.org_id) AS source_count, "
                "(SELECT COUNT(*) FROM decision_passages p "
                "WHERE p.plan_id = d.plan_id AND p.org_id = d.org_id) AS passage_count, "
                "(SELECT COUNT(*) FROM decision_passages p WHERE p.plan_id = d.plan_id "
                "AND p.org_id = d.org_id AND p.in_context = 0) AS omitted_passage_count "
                f"FROM workspace_decisions d WHERE {where} {suffix}",  # noqa: S608 -- fixed clauses
                (*params, *suffix_params),
            ).fetchall()
        finally:
            conn.close()
        return [
            DecisionRecord(
                plan_id=r["plan_id"],
                org_id=r["org_id"],
                created_by=r["created_by"],
                question=r["question"],
                status=r["status"],
                agents=tuple(_json_list(r["agents_json"])),
                rounds=r["rounds"],
                current_revision_id=r["current_revision_id"],
                budget_usd=r["budget_usd"],
                cost_actual_usd=r["cost_actual_usd"],
                cost_estimated_usd=r["cost_estimated_usd"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                source_count=r["source_count"],
                passage_count=r["passage_count"],
                omitted_passage_count=r["omitted_passage_count"],
            )
            for r in rows
        ]

    def _select_runs(
        self, where: str, params: tuple[object, ...], *, order: str = ""
    ) -> list[RunRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM decision_runs WHERE {where} {order}",  # noqa: S608 -- fixed clauses
                params,
            ).fetchall()
        finally:
            conn.close()
        return [
            RunRecord(
                run_id=r["run_id"],
                plan_id=r["plan_id"],
                org_id=r["org_id"],
                started_by=r["started_by"],
                debate_id=r["debate_id"],
                status=r["status"],
                agents=tuple(_json_list(r["agents_json"])),
                rounds=r["rounds"],
                budget_usd=r["budget_usd"],
                started_at=r["started_at"],
                finished_at=r["finished_at"],
                error=r["error"],
                cost_actual_usd=r["cost_actual_usd"],
                cost_estimated_usd=r["cost_estimated_usd"],
                result=_json_object(r["result_json"]),
            )
            for r in rows
        ]

    def _select_revisions(
        self, where: str, params: tuple[object, ...], *, order: str = ""
    ) -> list[RevisionRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM decision_revisions WHERE {where} {order}",  # noqa: S608 -- fixed clauses
                params,
            ).fetchall()
        finally:
            conn.close()
        return [_revision_from_row(r) for r in rows]

    def _select_passages(
        self, where: str, params: tuple[object, ...], *, order: str = ""
    ) -> list[PassageRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT p.*, s.label AS source_label FROM decision_passages p "
                "JOIN decision_sources s ON s.source_id = p.source_id AND s.org_id = p.org_id "
                f"WHERE {where} {order}",  # noqa: S608 -- fixed clauses
                params,
            ).fetchall()
        finally:
            conn.close()
        return [
            PassageRecord(
                passage_id=r["passage_id"],
                source_id=r["source_id"],
                plan_id=r["plan_id"],
                org_id=r["org_id"],
                seq=r["seq"],
                label=r["label"],
                heading=r["heading"],
                start_char=r["start_char"],
                end_char=r["end_char"],
                text=r["text"],
                sha256=r["sha256"],
                in_context=bool(r["in_context"]),
                created_at=r["created_at"],
                source_label=r["source_label"],
            )
            for r in rows
        ]


_stores: dict[str, WorkspaceStore] = {}
_stores_lock = threading.Lock()


def get_workspace_store(db_path: str | Path) -> WorkspaceStore:
    """The store for ``db_path`` (the plan store's database), created once per path."""
    key = str(db_path)
    with _stores_lock:
        store = _stores.get(key)
        if store is None:
            store = WorkspaceStore(key)
            _stores[key] = store
        return store


def _insert_run(conn: sqlite3.Connection, run: RunRecord) -> None:
    _require_org(run.org_id)
    conn.execute(
        "INSERT INTO decision_runs (run_id, plan_id, org_id, started_by, debate_id, status, "
        "agents_json, rounds, budget_usd, started_at, finished_at, error, cost_actual_usd, "
        "cost_estimated_usd, result_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run.run_id,
            run.plan_id,
            run.org_id,
            run.started_by,
            run.debate_id,
            run.status,
            json.dumps(list(run.agents)),
            run.rounds,
            run.budget_usd,
            run.started_at,
            run.finished_at,
            run.error,
            run.cost_actual_usd,
            run.cost_estimated_usd,
            None if run.result is None else _dump(run.result),
        ),
    )


def _insert_debate_revision(
    conn: sqlite3.Connection,
    plan_id: str,
    org_id: str,
    author_id: str | None,
    content: Mapping[str, Any],
    now: str,
) -> RevisionRecord:
    """Write the next revision as ``current``; the previous current one is superseded."""
    number = conn.execute(
        "SELECT COALESCE(MAX(number), 0) + 1 FROM decision_revisions "
        "WHERE plan_id = ? AND org_id = ?",
        (plan_id, org_id),
    ).fetchone()[0]
    previous = conn.execute(
        "SELECT revision_id FROM decision_revisions "
        "WHERE plan_id = ? AND org_id = ? AND status = 'current'",
        (plan_id, org_id),
    ).fetchone()
    parent = previous["revision_id"] if previous is not None else None
    content_copy = json.loads(_dump(content))
    revision = RevisionRecord(
        revision_id=f"rev_{uuid.uuid4().hex}",
        plan_id=plan_id,
        org_id=org_id,
        number=number,
        parent_revision_id=parent,
        status=REVISION_CURRENT,
        origin=ORIGIN_DEBATE,
        author_id=author_id,
        content=content_copy,
        content_hash=revision_content_hash(plan_id, number, parent, content_copy),
        created_at=now,
    )
    if parent is not None:
        conn.execute(
            "UPDATE decision_revisions SET status = ? WHERE revision_id = ?",
            (REVISION_SUPERSEDED, parent),
        )
    conn.execute(
        "INSERT INTO decision_revisions (revision_id, plan_id, org_id, number, "
        "parent_revision_id, status, origin, author_id, content_json, content_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            revision.revision_id,
            plan_id,
            org_id,
            number,
            parent,
            revision.status,
            revision.origin,
            author_id,
            _dump(content_copy),
            revision.content_hash,
            now,
        ),
    )
    return revision


def _revision_from_row(r: sqlite3.Row) -> RevisionRecord:
    return RevisionRecord(
        revision_id=r["revision_id"],
        plan_id=r["plan_id"],
        org_id=r["org_id"],
        number=r["number"],
        parent_revision_id=r["parent_revision_id"],
        status=r["status"],
        origin=r["origin"],
        author_id=r["author_id"],
        content=_json_object(r["content_json"]) or {},
        content_hash=r["content_hash"],
        created_at=r["created_at"],
    )


def _require_org(org_id: str | None) -> None:
    if not isinstance(org_id, str) or not org_id.strip():
        raise ValueError("workspace records require a non-blank org_id")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _new_run_id() -> str:
    return f"run_{uuid.uuid4().hex}"


def _dump(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_list(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except ValueError:
        return []
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _json_object(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


__all__ = [
    "DECISION_STATUSES",
    "DecisionRecord",
    "DecisionRows",
    "INTERRUPTED_RUN_ERROR",
    "ORPHANED_DECISION_ERROR",
    "PassageRecord",
    "RUN_BUDGET_EXCEEDED",
    "RUN_COMPLETED",
    "RUN_FAILED",
    "RUN_INTERRUPTED",
    "RUN_RUNNING",
    "RUN_STATUSES",
    "RevisionRecord",
    "RunConflictError",
    "RunRecord",
    "SCHEMA_MODULE",
    "SCHEMA_VERSION",
    "STATUS_DEBATING",
    "STATUS_FAILED",
    "STATUS_READY",
    "SourceRecord",
    "WorkspaceStore",
    "get_workspace_store",
    "new_decision_rows",
]
