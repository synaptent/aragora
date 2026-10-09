"""Workspace decision, source and passage tables in ``plans.db``.

Every row carries a non-blank ``org_id`` and every read takes the caller's
org: a row of another org is simply not found. Passage content is immutable
once written (a trigger rejects any update except the ``in_context`` flag),
and source rows cannot be updated at all, so passage labels, text and hashes
stay stable for the life of the decision.

The tables are schema module ``decision_workspace`` (version 1) in
``_schema_versions``, next to the ``plans`` table of the same file.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from aragora.decision_workspace.intake import PreparedDecision
from aragora.storage.schema import SchemaManager

SCHEMA_MODULE = "decision_workspace"
SCHEMA_VERSION = 1

STATUS_DEBATING = "debating"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
DECISION_STATUSES = (STATUS_DEBATING, STATUS_READY, STATUS_FAILED)

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


def new_decision_rows(
    prepared: PreparedDecision,
    *,
    plan_id: str,
    org_id: str,
    user_id: str | None,
    document_ids: Mapping[str, str],
) -> DecisionRows:
    """Rows for a new ``debating`` decision; ``document_ids`` maps source label to document id."""
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
    )
    return DecisionRows(decision=decision, sources=tuple(sources), passages=tuple(passages))


class WorkspaceStore:
    """Org-scoped access to the workspace tables of one ``plans.db`` file."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        conn = self._connect()
        try:
            SchemaManager(conn, SCHEMA_MODULE, current_version=SCHEMA_VERSION).ensure_schema(
                initial_schema=_SCHEMA_V1
            )
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
        """Write a decision with its sources and passages in one transaction."""
        decision = rows.decision
        _require_org(decision.org_id)
        if any(r.org_id != decision.org_id or r.plan_id != decision.plan_id for r in rows.sources):
            raise ValueError("every source must belong to the decision's plan and org")
        if any(r.org_id != decision.org_id or r.plan_id != decision.plan_id for r in rows.passages):
            raise ValueError("every passage must belong to the decision's plan and org")
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
        finally:
            conn.close()

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
                "WHERE p.plan_id = d.plan_id AND p.org_id = d.org_id) AS passage_count "
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
            )
            for r in rows
        ]

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


def _require_org(org_id: str | None) -> None:
    if not isinstance(org_id, str) or not org_id.strip():
        raise ValueError("workspace records require a non-blank org_id")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json_list(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except ValueError:
        return []
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


__all__ = [
    "DECISION_STATUSES",
    "DecisionRecord",
    "DecisionRows",
    "PassageRecord",
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
