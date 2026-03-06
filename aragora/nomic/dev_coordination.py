"""Development coordination primitives for concurrent multi-agent work.

This module adds the missing control plane for high-churn concurrent work:
- Work leases with explicit write scopes and expected tests
- Completion receipts for bounded worker outputs
- Integration decisions for an explicit integrator lane
- Salvage candidates for dirty worktrees and stashes

The design intentionally builds on existing Aragora orchestration patterns:
- EventBus for cross-worktree signaling
- GlobalWorkQueue-compatible work item projection
- Receipt-style content hashes for auditability
- Git-common-dir local state so agents coordinate without tracked-file churn
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from aragora.nomic.event_bus import EventBus
from aragora.nomic.global_work_queue import WorkItem, WorkStatus, WorkType
from aragora.worktree.fleet import FleetCoordinationStore

UTC = timezone.utc
_ACTIVE_LEASE_STATUSES = {"active"}
_PENDING_INTEGRATION_DECISIONS = {"pending_review"}
_OPEN_SALVAGE_STATUSES = {"detected", "claimed"}


class LeaseConflictError(ValueError):
    """Raised when a lease overlaps another active lease."""

    def __init__(self, conflicts: list[dict[str, Any]]):
        super().__init__("Lease overlaps existing active work")
        self.conflicts = conflicts


class LeaseStatus(str, Enum):
    """Lifecycle states for work leases."""

    ACTIVE = "active"
    COMPLETED = "completed"
    RELEASED = "released"
    EXPIRED = "expired"


class IntegrationDecisionType(str, Enum):
    """Integrator verdict for completed work."""

    PENDING_REVIEW = "pending_review"
    MERGE = "merge"
    CHERRY_PICK = "cherry_pick"
    REQUEST_CHANGES = "request_changes"
    DISCARD = "discard"
    SALVAGE = "salvage"


class SalvageStatus(str, Enum):
    """Lifecycle states for salvage candidates."""

    DETECTED = "detected"
    CLAIMED = "claimed"
    PORTED = "ported"
    DISCARDED = "discarded"


@dataclass(slots=True)
class WorkLease:
    """A bounded claim over a task, worktree, and write scope."""

    lease_id: str
    task_id: str
    title: str
    owner_agent: str
    owner_session_id: str
    branch: str
    worktree_path: str
    allowed_globs: list[str] = field(default_factory=list)
    claimed_paths: list[str] = field(default_factory=list)
    expected_tests: list[str] = field(default_factory=list)
    status: str = LeaseStatus.ACTIVE.value
    created_at: str = field(default_factory=lambda: _utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: _utcnow().isoformat())
    expires_at: str = field(default_factory=lambda: (_utcnow() + timedelta(hours=8)).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.status in _ACTIVE_LEASE_STATUSES and not self.is_expired

    @property
    def is_expired(self) -> bool:
        return _parse_dt(self.expires_at) <= _utcnow()

    def overlaps(self, allowed_globs: list[str], claimed_paths: list[str]) -> bool:
        other_globs = [_normalize_claim(x) for x in allowed_globs if str(x).strip()]
        other_paths = [_normalize_claim(x) for x in claimed_paths if str(x).strip()]
        if self.claimed_paths and _claims_overlap(self.claimed_paths, other_globs, other_paths):
            return True
        return _globs_overlap_any(self.allowed_globs, other_globs, self.claimed_paths, other_paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "task_id": self.task_id,
            "title": self.title,
            "owner_agent": self.owner_agent,
            "owner_session_id": self.owner_session_id,
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "allowed_globs": list(self.allowed_globs),
            "claimed_paths": list(self.claimed_paths),
            "expected_tests": list(self.expected_tests),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> WorkLease:
        return cls(
            lease_id=row["lease_id"],
            task_id=row["task_id"],
            title=row["title"],
            owner_agent=row["owner_agent"],
            owner_session_id=row["owner_session_id"],
            branch=row["branch"],
            worktree_path=row["worktree_path"],
            allowed_globs=_json_loads(row["allowed_globs_json"], []),
            claimed_paths=_json_loads(row["claimed_paths_json"], []),
            expected_tests=_json_loads(row["expected_tests_json"], []),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            metadata=_json_loads(row["metadata_json"], {}),
        )


@dataclass(slots=True)
class CompletionReceipt:
    """A bounded worker output ready for integration review."""

    receipt_id: str
    lease_id: str
    owner_agent: str
    owner_session_id: str
    branch: str
    worktree_path: str
    commit_shas: list[str] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    confidence: float = 0.0
    created_at: str = field(default_factory=lambda: _utcnow().isoformat())
    artifact_hash: str = ""

    def __post_init__(self) -> None:
        if not self.artifact_hash:
            self.artifact_hash = _artifact_hash(
                {
                    "lease_id": self.lease_id,
                    "owner_agent": self.owner_agent,
                    "owner_session_id": self.owner_session_id,
                    "branch": self.branch,
                    "worktree_path": self.worktree_path,
                    "commit_shas": self.commit_shas,
                    "changed_paths": self.changed_paths,
                    "tests_run": self.tests_run,
                    "assumptions": self.assumptions,
                    "blockers": self.blockers,
                    "confidence": self.confidence,
                }
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "lease_id": self.lease_id,
            "owner_agent": self.owner_agent,
            "owner_session_id": self.owner_session_id,
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "commit_shas": list(self.commit_shas),
            "changed_paths": list(self.changed_paths),
            "tests_run": list(self.tests_run),
            "assumptions": list(self.assumptions),
            "blockers": list(self.blockers),
            "confidence": self.confidence,
            "created_at": self.created_at,
            "artifact_hash": self.artifact_hash,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> CompletionReceipt:
        return cls(
            receipt_id=row["receipt_id"],
            lease_id=row["lease_id"],
            owner_agent=row["owner_agent"],
            owner_session_id=row["owner_session_id"],
            branch=row["branch"],
            worktree_path=row["worktree_path"],
            commit_shas=_json_loads(row["commit_shas_json"], []),
            changed_paths=_json_loads(row["changed_paths_json"], []),
            tests_run=_json_loads(row["tests_run_json"], []),
            assumptions=_json_loads(row["assumptions_json"], []),
            blockers=_json_loads(row["blockers_json"], []),
            confidence=float(row["confidence"]),
            created_at=row["created_at"],
            artifact_hash=row["artifact_hash"],
        )


@dataclass(slots=True)
class IntegrationDecision:
    """Integrator verdict for a completion receipt."""

    decision_id: str
    lease_id: str
    receipt_id: str
    decision: str
    target_branch: str
    rationale: str
    chosen_commits: list[str] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    decided_by: str = ""
    created_at: str = field(default_factory=lambda: _utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "lease_id": self.lease_id,
            "receipt_id": self.receipt_id,
            "decision": self.decision,
            "target_branch": self.target_branch,
            "rationale": self.rationale,
            "chosen_commits": list(self.chosen_commits),
            "followups": list(self.followups),
            "decided_by": self.decided_by,
            "created_at": self.created_at,
        }

    def to_work_item(self) -> WorkItem:
        priority = 85 if self.decision == IntegrationDecisionType.PENDING_REVIEW.value else 50
        return WorkItem(
            id=f"integration:{self.decision_id}",
            work_type=WorkType.CUSTOM,
            title=f"Integration review for receipt {self.receipt_id[:8]}",
            description=self.rationale or f"{self.decision} for lease {self.lease_id}",
            status=WorkStatus.READY,
            created_at=_parse_dt(self.created_at),
            updated_at=_parse_dt(self.created_at),
            base_priority=priority,
            tags=["integration", self.decision, self.target_branch],
            metadata=self.to_dict(),
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> IntegrationDecision:
        return cls(
            decision_id=row["decision_id"],
            lease_id=row["lease_id"],
            receipt_id=row["receipt_id"],
            decision=row["decision"],
            target_branch=row["target_branch"],
            rationale=row["rationale"],
            chosen_commits=_json_loads(row["chosen_commits_json"], []),
            followups=_json_loads(row["followups_json"], []),
            decided_by=row["decided_by"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class SalvageCandidate:
    """Potentially useful abandoned work discovered in stashes or worktrees."""

    candidate_id: str
    source_kind: str
    source_ref: str
    branch: str = ""
    worktree_path: str = ""
    stash_ref: str = ""
    head_sha: str = ""
    changed_paths: list[str] = field(default_factory=list)
    summary: str = ""
    likely_value: float = 0.0
    status: str = SalvageStatus.DETECTED.value
    created_at: str = field(default_factory=lambda: _utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: _utcnow().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "stash_ref": self.stash_ref,
            "head_sha": self.head_sha,
            "changed_paths": list(self.changed_paths),
            "summary": self.summary,
            "likely_value": self.likely_value,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    def to_work_item(self) -> WorkItem:
        return WorkItem(
            id=f"salvage:{self.candidate_id}",
            work_type=WorkType.MAINTENANCE,
            title=f"Salvage {self.source_kind} {self.source_ref}",
            description=self.summary or f"Review salvage candidate from {self.source_kind}",
            status=WorkStatus.READY,
            created_at=_parse_dt(self.created_at),
            updated_at=_parse_dt(self.updated_at),
            base_priority=max(10, min(100, int(self.likely_value * 100))),
            tags=["salvage", self.source_kind, self.status],
            metadata=self.to_dict(),
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> SalvageCandidate:
        return cls(
            candidate_id=row["candidate_id"],
            source_kind=row["source_kind"],
            source_ref=row["source_ref"],
            branch=row["branch"],
            worktree_path=row["worktree_path"],
            stash_ref=row["stash_ref"],
            head_sha=row["head_sha"],
            changed_paths=_json_loads(row["changed_paths_json"], []),
            summary=row["summary"],
            likely_value=float(row["likely_value"]),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=_json_loads(row["metadata_json"], {}),
        )


class DevCoordinationStore:
    """SQLite-backed coordination state for concurrent development."""

    def __init__(
        self,
        repo_root: Path | None = None,
        db_path: Path | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.db_path = db_path or (
            self._git_common_dir(self.repo_root) / "aragora-agent-state" / "dev_coordination.db"
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.event_bus = event_bus or EventBus(repo_root=self.repo_root)
        self.fleet_store = FleetCoordinationStore(self.repo_root)
        self._ensure_schema()

    @staticmethod
    def _git_common_dir(repo_root: Path) -> Path:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                proc.stderr.strip() or f"Failed to resolve git common dir for {repo_root}"
            )
        return Path(proc.stdout.strip()).resolve()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS leases (
                    lease_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    owner_agent TEXT NOT NULL,
                    owner_session_id TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    worktree_path TEXT NOT NULL,
                    allowed_globs_json TEXT NOT NULL,
                    claimed_paths_json TEXT NOT NULL,
                    expected_tests_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_leases_status ON leases(status, expires_at);
                CREATE INDEX IF NOT EXISTS idx_leases_worktree ON leases(worktree_path, status);

                CREATE TABLE IF NOT EXISTS completion_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    lease_id TEXT NOT NULL,
                    owner_agent TEXT NOT NULL,
                    owner_session_id TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    worktree_path TEXT NOT NULL,
                    commit_shas_json TEXT NOT NULL,
                    changed_paths_json TEXT NOT NULL,
                    tests_run_json TEXT NOT NULL,
                    assumptions_json TEXT NOT NULL,
                    blockers_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    artifact_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_receipts_lease ON completion_receipts(lease_id, created_at);

                CREATE TABLE IF NOT EXISTS integration_decisions (
                    decision_id TEXT PRIMARY KEY,
                    lease_id TEXT NOT NULL,
                    receipt_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    target_branch TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    chosen_commits_json TEXT NOT NULL,
                    followups_json TEXT NOT NULL,
                    decided_by TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_integration_receipt ON integration_decisions(receipt_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_integration_decision ON integration_decisions(decision, created_at);

                CREATE TABLE IF NOT EXISTS salvage_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    worktree_path TEXT NOT NULL,
                    stash_ref TEXT NOT NULL,
                    head_sha TEXT NOT NULL,
                    changed_paths_json TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    likely_value REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_salvage_source ON salvage_candidates(source_kind, source_ref);
                CREATE INDEX IF NOT EXISTS idx_salvage_status ON salvage_candidates(status, updated_at);
                """
            )
            conn.commit()
        finally:
            conn.close()

    def status_summary(self) -> dict[str, Any]:
        active_leases = self.list_active_leases()
        pending_integrations = self.list_integration_decisions(only_pending=True)
        salvage = self.list_salvage_candidates(statuses=sorted(_OPEN_SALVAGE_STATUSES))
        return {
            "db_path": str(self.db_path),
            "fleet_path": str(self.fleet_store.path),
            "active_leases": [item.to_dict() for item in active_leases],
            "pending_integrations": [item.to_dict() for item in pending_integrations],
            "open_salvage_candidates": [item.to_dict() for item in salvage],
            "counts": {
                "active_leases": len(active_leases),
                "pending_integrations": len(pending_integrations),
                "open_salvage_candidates": len(salvage),
                "fleet_claims": len(self.fleet_store.list_claims()),
                "fleet_merge_queue": len(self.fleet_store.list_merge_queue()),
            },
        }

    def list_active_leases(self) -> list[WorkLease]:
        now = _utcnow()
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM leases ORDER BY created_at ASC").fetchall()
        finally:
            conn.close()
        leases = [WorkLease.from_row(row) for row in rows]
        active: list[WorkLease] = []
        for lease in leases:
            if lease.status != LeaseStatus.ACTIVE.value:
                continue
            if _parse_dt(lease.expires_at) <= now:
                continue
            active.append(lease)
        return active

    def list_completion_receipts(self, lease_id: str | None = None) -> list[CompletionReceipt]:
        conn = self._connect()
        try:
            if lease_id:
                rows = conn.execute(
                    "SELECT * FROM completion_receipts WHERE lease_id = ? ORDER BY created_at DESC",
                    (lease_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM completion_receipts ORDER BY created_at DESC"
                ).fetchall()
        finally:
            conn.close()
        return [CompletionReceipt.from_row(row) for row in rows]

    def list_integration_decisions(
        self,
        *,
        only_pending: bool = False,
        receipt_id: str | None = None,
    ) -> list[IntegrationDecision]:
        conn = self._connect()
        try:
            if receipt_id:
                rows = conn.execute(
                    "SELECT * FROM integration_decisions WHERE receipt_id = ? ORDER BY created_at DESC",
                    (receipt_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM integration_decisions ORDER BY created_at DESC"
                ).fetchall()
        finally:
            conn.close()
        decisions = [IntegrationDecision.from_row(row) for row in rows]
        if only_pending:
            return [item for item in decisions if item.decision in _PENDING_INTEGRATION_DECISIONS]
        return decisions

    def list_salvage_candidates(self, statuses: list[str] | None = None) -> list[SalvageCandidate]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM salvage_candidates ORDER BY updated_at DESC"
            ).fetchall()
        finally:
            conn.close()
        items = [SalvageCandidate.from_row(row) for row in rows]
        if statuses is None:
            return items
        allowed = set(statuses)
        return [item for item in items if item.status in allowed]

    def find_conflicting_leases(
        self,
        *,
        allowed_globs: list[str],
        claimed_paths: list[str],
        owner_session_id: str | None = None,
        exclude_lease_id: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_globs = [_normalize_claim(item) for item in allowed_globs if str(item).strip()]
        normalized_paths = [_normalize_claim(item) for item in claimed_paths if str(item).strip()]
        conflicts: list[dict[str, Any]] = []
        active_leases = self.list_active_leases()
        tracked_sessions = {lease.owner_session_id for lease in active_leases}
        for lease in active_leases:
            if exclude_lease_id and lease.lease_id == exclude_lease_id:
                continue
            if lease.overlaps(normalized_globs, normalized_paths):
                conflicts.append(
                    {
                        "lease_id": lease.lease_id,
                        "task_id": lease.task_id,
                        "title": lease.title,
                        "owner_agent": lease.owner_agent,
                        "owner_session_id": lease.owner_session_id,
                        "branch": lease.branch,
                        "worktree_path": lease.worktree_path,
                        "allowed_globs": lease.allowed_globs,
                        "claimed_paths": lease.claimed_paths,
                        "expires_at": lease.expires_at,
                    }
                )
        for claim in self.fleet_store.list_claims():
            session_id = str(claim.get("session_id", "")).strip()
            if owner_session_id and session_id == owner_session_id:
                continue
            if session_id in tracked_sessions:
                continue
            path = _normalize_claim(str(claim.get("path", "")))
            if not path:
                continue
            if not _claims_overlap([path], normalized_globs, normalized_paths):
                continue
            conflicts.append(
                {
                    "source": "fleet_claim",
                    "session_id": session_id,
                    "branch": str(claim.get("branch", "")),
                    "path": path,
                    "mode": str(claim.get("mode", "exclusive")),
                }
            )
        return conflicts

    def claim_lease(
        self,
        *,
        task_id: str,
        title: str,
        owner_agent: str,
        owner_session_id: str,
        branch: str,
        worktree_path: str,
        allowed_globs: list[str] | None = None,
        claimed_paths: list[str] | None = None,
        expected_tests: list[str] | None = None,
        ttl_hours: float = 8.0,
        metadata: dict[str, Any] | None = None,
        allow_overlap: bool = False,
    ) -> WorkLease:
        normalized_globs = [
            _normalize_claim(item) for item in allowed_globs or [] if str(item).strip()
        ]
        normalized_paths = [
            _normalize_claim(item) for item in claimed_paths or [] if str(item).strip()
        ]
        conflicts = self.find_conflicting_leases(
            allowed_globs=normalized_globs,
            claimed_paths=normalized_paths,
            owner_session_id=owner_session_id,
        )
        if conflicts and not allow_overlap:
            self._publish(
                "conflict_detected",
                track=branch,
                data={
                    "task_id": task_id,
                    "worktree_path": worktree_path,
                    "conflicts": conflicts,
                },
            )
            raise LeaseConflictError(conflicts)

        now = _utcnow()
        lease = WorkLease(
            lease_id=str(uuid.uuid4())[:12],
            task_id=task_id,
            title=title or task_id,
            owner_agent=owner_agent,
            owner_session_id=owner_session_id,
            branch=branch,
            worktree_path=str(Path(worktree_path).resolve()),
            allowed_globs=normalized_globs,
            claimed_paths=normalized_paths,
            expected_tests=list(expected_tests or []),
            status=LeaseStatus.ACTIVE.value,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            expires_at=(now + timedelta(hours=ttl_hours)).isoformat(),
            metadata=dict(metadata or {}),
        )

        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO leases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    lease.lease_id,
                    lease.task_id,
                    lease.title,
                    lease.owner_agent,
                    lease.owner_session_id,
                    lease.branch,
                    lease.worktree_path,
                    _json_dump(lease.allowed_globs),
                    _json_dump(lease.claimed_paths),
                    _json_dump(lease.expected_tests),
                    lease.status,
                    lease.created_at,
                    lease.updated_at,
                    lease.expires_at,
                    _json_dump(lease.metadata),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        self._publish(
            "task_claimed",
            track=branch,
            data={
                "lease_id": lease.lease_id,
                "task_id": task_id,
                "title": lease.title,
                "files": lease.claimed_paths or lease.allowed_globs,
                "expected_tests": lease.expected_tests,
                "worktree_path": lease.worktree_path,
            },
        )
        claim_paths = lease.claimed_paths or lease.allowed_globs
        if claim_paths:
            self.fleet_store.claim_paths(
                session_id=lease.owner_session_id,
                paths=claim_paths,
                branch=lease.branch,
                mode="exclusive",
            )
        return lease

    def heartbeat_lease(self, lease_id: str, ttl_hours: float | None = None) -> WorkLease:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown lease_id: {lease_id}")
            lease = WorkLease.from_row(row)
            ttl = (
                ttl_hours
                if ttl_hours is not None
                else max(
                    1.0,
                    (_parse_dt(lease.expires_at) - _parse_dt(lease.updated_at)).total_seconds()
                    / 3600,
                )
            )
            now = _utcnow()
            conn.execute(
                "UPDATE leases SET updated_at = ?, expires_at = ? WHERE lease_id = ?",
                (now.isoformat(), (now + timedelta(hours=ttl)).isoformat(), lease_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(f"Unknown lease_id: {lease_id}")
        return WorkLease.from_row(row)

    def release_lease(self, lease_id: str, status: LeaseStatus = LeaseStatus.RELEASED) -> WorkLease:
        now = _utcnow().isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE leases SET status = ?, updated_at = ? WHERE lease_id = ?",
                (status.value, now, lease_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(f"Unknown lease_id: {lease_id}")
        lease = WorkLease.from_row(row)
        release_paths = lease.claimed_paths or lease.allowed_globs
        if release_paths:
            self.fleet_store.release_paths(session_id=lease.owner_session_id, paths=release_paths)
        self._publish(
            "task_completed",
            track=lease.branch,
            data={
                "lease_id": lease.lease_id,
                "status": lease.status,
                "worktree_path": lease.worktree_path,
            },
        )
        return lease

    def record_completion(
        self,
        *,
        lease_id: str,
        owner_agent: str,
        owner_session_id: str,
        branch: str,
        worktree_path: str,
        commit_shas: list[str] | None = None,
        changed_paths: list[str] | None = None,
        tests_run: list[str] | None = None,
        assumptions: list[str] | None = None,
        blockers: list[str] | None = None,
        confidence: float = 0.0,
    ) -> CompletionReceipt:
        receipt = CompletionReceipt(
            receipt_id=str(uuid.uuid4())[:12],
            lease_id=lease_id,
            owner_agent=owner_agent,
            owner_session_id=owner_session_id,
            branch=branch,
            worktree_path=str(Path(worktree_path).resolve()),
            commit_shas=list(commit_shas or []),
            changed_paths=[
                _normalize_claim(item) for item in changed_paths or [] if str(item).strip()
            ],
            tests_run=list(tests_run or []),
            assumptions=list(assumptions or []),
            blockers=list(blockers or []),
            confidence=float(confidence),
        )

        now = _utcnow().isoformat()
        conn = self._connect()
        try:
            lease_row = conn.execute(
                "SELECT * FROM leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            if lease_row is None:
                raise KeyError(f"Unknown lease_id: {lease_id}")
            conn.execute(
                "INSERT INTO completion_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    receipt.receipt_id,
                    receipt.lease_id,
                    receipt.owner_agent,
                    receipt.owner_session_id,
                    receipt.branch,
                    receipt.worktree_path,
                    _json_dump(receipt.commit_shas),
                    _json_dump(receipt.changed_paths),
                    _json_dump(receipt.tests_run),
                    _json_dump(receipt.assumptions),
                    _json_dump(receipt.blockers),
                    receipt.confidence,
                    receipt.created_at,
                    receipt.artifact_hash,
                ),
            )
            conn.execute(
                "UPDATE leases SET status = ?, updated_at = ?, metadata_json = ? WHERE lease_id = ?",
                (
                    LeaseStatus.COMPLETED.value,
                    now,
                    _json_dump(
                        {
                            **_json_loads(lease_row["metadata_json"], {}),
                            "last_receipt_id": receipt.receipt_id,
                        }
                    ),
                    lease_id,
                ),
            )
            pending = IntegrationDecision(
                decision_id=str(uuid.uuid4())[:12],
                lease_id=lease_id,
                receipt_id=receipt.receipt_id,
                decision=IntegrationDecisionType.PENDING_REVIEW.value,
                target_branch="main",
                rationale="Awaiting integrator review",
                chosen_commits=list(receipt.commit_shas),
                followups=[],
                decided_by="system",
                created_at=now,
            )
            conn.execute(
                "INSERT INTO integration_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pending.decision_id,
                    pending.lease_id,
                    pending.receipt_id,
                    pending.decision,
                    pending.target_branch,
                    pending.rationale,
                    _json_dump(pending.chosen_commits),
                    _json_dump(pending.followups),
                    pending.decided_by,
                    pending.created_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        self._publish(
            "task_completed",
            track=branch,
            data={
                "lease_id": lease_id,
                "receipt_id": receipt.receipt_id,
                "files": receipt.changed_paths,
                "tests_run": receipt.tests_run,
                "confidence": receipt.confidence,
            },
        )
        self._publish(
            "merge_ready",
            track=branch,
            data={
                "lease_id": lease_id,
                "receipt_id": receipt.receipt_id,
                "commit_shas": receipt.commit_shas,
                "artifact_hash": receipt.artifact_hash,
            },
        )
        self.fleet_store.enqueue_merge(
            session_id=owner_session_id,
            branch=branch,
            title=f"{owner_agent}: {lease_id}",
            metadata={
                "lease_id": lease_id,
                "receipt_id": receipt.receipt_id,
                "tests_run": receipt.tests_run,
                "changed_paths": receipt.changed_paths,
                "confidence": receipt.confidence,
                "artifact_hash": receipt.artifact_hash,
            },
        )
        return receipt

    def record_integration_decision(
        self,
        *,
        receipt_id: str,
        decision: IntegrationDecisionType,
        decided_by: str,
        rationale: str,
        target_branch: str = "main",
        chosen_commits: list[str] | None = None,
        followups: list[str] | None = None,
        lease_id: str | None = None,
    ) -> IntegrationDecision:
        conn = self._connect()
        try:
            latest = conn.execute(
                "SELECT * FROM integration_decisions WHERE receipt_id = ? ORDER BY created_at DESC LIMIT 1",
                (receipt_id,),
            ).fetchone()
            if latest is None and lease_id is None:
                receipt_row = conn.execute(
                    "SELECT * FROM completion_receipts WHERE receipt_id = ?",
                    (receipt_id,),
                ).fetchone()
                if receipt_row is None:
                    raise KeyError(f"Unknown receipt_id: {receipt_id}")
                lease_id = receipt_row["lease_id"]
            decision_row = IntegrationDecision(
                decision_id=str(uuid.uuid4())[:12],
                lease_id=lease_id or latest["lease_id"],
                receipt_id=receipt_id,
                decision=decision.value,
                target_branch=target_branch,
                rationale=rationale,
                chosen_commits=list(
                    chosen_commits
                    or (_json_loads(latest["chosen_commits_json"], []) if latest else [])
                ),
                followups=list(followups or []),
                decided_by=decided_by,
                created_at=_utcnow().isoformat(),
            )
            conn.execute(
                "INSERT INTO integration_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision_row.decision_id,
                    decision_row.lease_id,
                    decision_row.receipt_id,
                    decision_row.decision,
                    decision_row.target_branch,
                    decision_row.rationale,
                    _json_dump(decision_row.chosen_commits),
                    _json_dump(decision_row.followups),
                    decision_row.decided_by,
                    decision_row.created_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        event_type = (
            "merge_completed"
            if decision in {IntegrationDecisionType.MERGE, IntegrationDecisionType.CHERRY_PICK}
            else "conflict_detected"
        )
        self._publish(
            event_type,
            track=decision_row.target_branch,
            data=decision_row.to_dict(),
        )
        return decision_row

    def upsert_salvage_candidate(
        self,
        *,
        source_kind: str,
        source_ref: str,
        branch: str = "",
        worktree_path: str = "",
        stash_ref: str = "",
        head_sha: str = "",
        changed_paths: list[str] | None = None,
        summary: str = "",
        likely_value: float = 0.0,
        status: SalvageStatus = SalvageStatus.DETECTED,
        metadata: dict[str, Any] | None = None,
    ) -> SalvageCandidate:
        now = _utcnow().isoformat()
        candidate_id = hashlib.sha1(f"{source_kind}:{source_ref}".encode()).hexdigest()[:12]
        candidate = SalvageCandidate(
            candidate_id=candidate_id,
            source_kind=source_kind,
            source_ref=source_ref,
            branch=branch,
            worktree_path=str(Path(worktree_path).resolve()) if worktree_path else "",
            stash_ref=stash_ref,
            head_sha=head_sha,
            changed_paths=[
                _normalize_claim(item) for item in changed_paths or [] if str(item).strip()
            ],
            summary=summary,
            likely_value=float(likely_value),
            status=status.value,
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO salvage_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_kind, source_ref) DO UPDATE SET
                    branch = excluded.branch,
                    worktree_path = excluded.worktree_path,
                    stash_ref = excluded.stash_ref,
                    head_sha = excluded.head_sha,
                    changed_paths_json = excluded.changed_paths_json,
                    summary = excluded.summary,
                    likely_value = excluded.likely_value,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    candidate.candidate_id,
                    candidate.source_kind,
                    candidate.source_ref,
                    candidate.branch,
                    candidate.worktree_path,
                    candidate.stash_ref,
                    candidate.head_sha,
                    _json_dump(candidate.changed_paths),
                    candidate.summary,
                    candidate.likely_value,
                    candidate.status,
                    candidate.created_at,
                    candidate.updated_at,
                    _json_dump(candidate.metadata),
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM salvage_candidates WHERE source_kind = ? AND source_ref = ?",
                (source_kind, source_ref),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RuntimeError("Failed to persist salvage candidate")
        return SalvageCandidate.from_row(row)

    def pending_work_items(self) -> list[WorkItem]:
        items: list[WorkItem] = []
        items.extend(
            item.to_work_item() for item in self.list_integration_decisions(only_pending=True)
        )
        items.extend(
            item.to_work_item()
            for item in self.list_salvage_candidates(statuses=sorted(_OPEN_SALVAGE_STATUSES))
        )
        return items

    def scan_salvage_sources(
        self,
        *,
        include_worktrees: bool = True,
        include_stashes: bool = True,
        max_stashes: int = 25,
    ) -> list[SalvageCandidate]:
        candidates: list[SalvageCandidate] = []
        if include_worktrees:
            candidates.extend(self._scan_worktrees())
        if include_stashes:
            candidates.extend(self._scan_stashes(max_stashes=max_stashes))
        return candidates

    def _scan_worktrees(self) -> list[SalvageCandidate]:
        proc = subprocess.run(
            ["git", "-C", str(self.repo_root), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return []

        candidates: list[SalvageCandidate] = []
        for path, branch in _parse_worktree_entries(proc.stdout):
            if not branch or branch in {"main", "master"}:
                continue
            dirty_proc = subprocess.run(
                ["git", "-C", str(path), "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=False,
            )
            ahead_proc = subprocess.run(
                ["git", "-C", str(self.repo_root), "rev-list", "--count", f"origin/main..{branch}"],
                capture_output=True,
                text=True,
                check=False,
            )
            head_proc = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            ahead = int(ahead_proc.stdout.strip() or "0") if ahead_proc.returncode == 0 else 0
            status_lines = [line for line in dirty_proc.stdout.splitlines() if line.strip()]
            if not status_lines and ahead == 0:
                continue
            changed_paths = _status_paths(status_lines)
            if ahead > 0:
                diff_proc = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self.repo_root),
                        "diff",
                        "--name-only",
                        f"origin/main...{branch}",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                changed_paths.extend(
                    _normalize_claim(item) for item in diff_proc.stdout.splitlines() if item.strip()
                )
            summary = f"worktree {branch} dirty={bool(status_lines)} ahead={ahead}"
            candidate = self.upsert_salvage_candidate(
                source_kind="worktree",
                source_ref=branch,
                branch=branch,
                worktree_path=str(path),
                head_sha=head_proc.stdout.strip() if head_proc.returncode == 0 else "",
                changed_paths=sorted(set(changed_paths)),
                summary=summary,
                likely_value=_estimate_salvage_value(
                    ahead=ahead, changed_paths=changed_paths, dirty=bool(status_lines)
                ),
                metadata={"ahead": ahead, "dirty": bool(status_lines)},
            )
            candidates.append(candidate)
        return candidates

    def _scan_stashes(self, *, max_stashes: int = 25) -> list[SalvageCandidate]:
        proc = subprocess.run(
            ["git", "-C", str(self.repo_root), "stash", "list"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return []
        candidates: list[SalvageCandidate] = []
        for line in proc.stdout.splitlines()[:max_stashes]:
            if not line.strip() or ":" not in line:
                continue
            source_ref, summary = line.split(":", 1)
            source_ref = source_ref.strip()
            summary = summary.strip()
            names_proc = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.repo_root),
                    "stash",
                    "show",
                    "--name-only",
                    "--include-untracked",
                    source_ref,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            changed_paths = [
                _normalize_claim(item) for item in names_proc.stdout.splitlines() if item.strip()
            ]
            if not changed_paths:
                continue
            candidate = self.upsert_salvage_candidate(
                source_kind="stash",
                source_ref=source_ref,
                stash_ref=source_ref,
                changed_paths=changed_paths,
                summary=summary,
                likely_value=_estimate_salvage_value(
                    ahead=0, changed_paths=changed_paths, dirty=True
                ),
                metadata={"summary": summary},
            )
            candidates.append(candidate)
        return candidates

    def _publish(self, event_type: str, *, track: str, data: dict[str, Any]) -> None:
        try:
            self.event_bus.publish(event_type, track=track, data=data)
        except (OSError, ValueError, RuntimeError):
            # Coordination state must not fail closed if the event bus is unavailable.
            pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _artifact_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _normalize_claim(value: str) -> str:
    return value.strip().strip("/")


def _has_wildcard(pattern: str) -> bool:
    return any(token in pattern for token in ("*", "?", "["))


def _path_matches_glob(path: str, pattern: str) -> bool:
    clean_path = _normalize_claim(path)
    clean_pattern = _normalize_claim(pattern)
    if not clean_pattern:
        return False
    if _has_wildcard(clean_pattern):
        return PurePosixPath(clean_path).match(clean_pattern)
    return clean_path == clean_pattern or clean_path.startswith(f"{clean_pattern}/")


def _glob_overlap(first: str, second: str) -> bool:
    a = _normalize_claim(first)
    b = _normalize_claim(second)
    if not a or not b:
        return False
    if a == b:
        return True
    a_wild = _has_wildcard(a)
    b_wild = _has_wildcard(b)
    if not a_wild and not b_wild:
        return a.startswith(f"{b}/") or b.startswith(f"{a}/")
    if not a_wild:
        return _path_matches_glob(a, b)
    if not b_wild:
        return _path_matches_glob(b, a)
    a_prefix = a.split("*")[0]
    b_prefix = b.split("*")[0]
    if a_prefix and b_prefix and (a_prefix.startswith(b_prefix) or b_prefix.startswith(a_prefix)):
        return True
    return False


def _globs_overlap_any(
    first_globs: list[str],
    second_globs: list[str],
    first_paths: list[str],
    second_paths: list[str],
) -> bool:
    for path in first_paths:
        if _claims_overlap([path], second_globs, second_paths):
            return True
    for path in second_paths:
        if _claims_overlap([path], first_globs, first_paths):
            return True
    for left in first_globs:
        for right in second_globs:
            if _glob_overlap(left, right):
                return True
    return False


def _claims_overlap(
    claimed_paths: list[str], allowed_globs: list[str], other_paths: list[str]
) -> bool:
    for claimed in claimed_paths:
        for glob in allowed_globs:
            if _path_matches_glob(claimed, glob) or _path_matches_glob(glob, claimed):
                return True
        for other in other_paths:
            if _glob_overlap(claimed, other):
                return True
    return False


def _parse_worktree_entries(raw: str) -> list[tuple[Path, str]]:
    entries: list[tuple[Path, str]] = []
    current_path: Path | None = None
    current_branch: str | None = None
    for line in raw.splitlines():
        text = line.strip()
        if text.startswith("worktree "):
            current_path = Path(text[len("worktree ") :]).resolve()
            current_branch = None
        elif text.startswith("branch refs/heads/"):
            current_branch = text[len("branch refs/heads/") :]
        elif text == "" and current_path is not None and current_branch is not None:
            entries.append((current_path, current_branch))
            current_path = None
            current_branch = None
    if current_path is not None and current_branch is not None:
        entries.append((current_path, current_branch))
    return entries


def _status_paths(lines: list[str]) -> list[str]:
    paths: list[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        path = text[3:] if len(text) > 3 else text
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(_normalize_claim(path))
    return paths


def _estimate_salvage_value(*, ahead: int, changed_paths: list[str], dirty: bool) -> float:
    value = 0.2
    if dirty:
        value += 0.2
    value += min(0.4, ahead * 0.1)
    value += min(0.2, len(set(changed_paths)) * 0.02)
    return max(0.0, min(1.0, value))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dev coordination control plane")
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument("--db", default=None, help="Optional explicit SQLite path")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Show coordination status")
    status.add_argument("--json", action="store_true")

    claim = sub.add_parser("claim", help="Claim a bounded work lease")
    claim.add_argument("--task-id", required=True)
    claim.add_argument("--title", required=True)
    claim.add_argument("--agent", required=True)
    claim.add_argument("--session-id", required=True)
    claim.add_argument("--branch", required=True)
    claim.add_argument("--worktree", required=True)
    claim.add_argument("--write-scope", action="append", default=[])
    claim.add_argument("--claimed-path", action="append", default=[])
    claim.add_argument("--test", action="append", default=[])
    claim.add_argument("--ttl-hours", type=float, default=8.0)
    claim.add_argument("--allow-overlap", action="store_true")
    claim.add_argument("--json", action="store_true")

    complete = sub.add_parser("complete", help="Record a completion receipt")
    complete.add_argument("--lease-id", required=True)
    complete.add_argument("--agent", required=True)
    complete.add_argument("--session-id", required=True)
    complete.add_argument("--branch", required=True)
    complete.add_argument("--worktree", required=True)
    complete.add_argument("--commit", action="append", default=[])
    complete.add_argument("--changed-path", action="append", default=[])
    complete.add_argument("--test", action="append", default=[])
    complete.add_argument("--assumption", action="append", default=[])
    complete.add_argument("--blocker", action="append", default=[])
    complete.add_argument("--confidence", type=float, default=0.0)
    complete.add_argument("--json", action="store_true")

    decide = sub.add_parser("decide", help="Record an integration decision")
    decide.add_argument("--receipt-id", required=True)
    decide.add_argument(
        "--decision",
        required=True,
        choices=[item.value for item in IntegrationDecisionType],
    )
    decide.add_argument("--decided-by", required=True)
    decide.add_argument("--rationale", required=True)
    decide.add_argument("--target-branch", default="main")
    decide.add_argument("--commit", action="append", default=[])
    decide.add_argument("--follow-up", action="append", default=[])
    decide.add_argument("--lease-id", default=None)
    decide.add_argument("--json", action="store_true")

    salvage = sub.add_parser("scan-salvage", help="Scan stashes/worktrees for salvage candidates")
    salvage.add_argument("--no-worktrees", action="store_true")
    salvage.add_argument("--no-stashes", action="store_true")
    salvage.add_argument("--max-stashes", type=int, default=25)
    salvage.add_argument("--json", action="store_true")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    db_path = Path(args.db).resolve() if args.db else None
    store = DevCoordinationStore(repo_root=Path(args.repo), db_path=db_path)

    if args.command == "status":
        payload = store.status_summary()
        if args.json:
            print(json.dumps(payload, indent=2))  # noqa: T201
        else:
            counts = payload["counts"]
            print(  # noqa: T201
                f"active_leases={counts['active_leases']} "
                f"pending_integrations={counts['pending_integrations']} "
                f"open_salvage_candidates={counts['open_salvage_candidates']}"
            )
        return 0

    if args.command == "claim":
        try:
            lease = store.claim_lease(
                task_id=args.task_id,
                title=args.title,
                owner_agent=args.agent,
                owner_session_id=args.session_id,
                branch=args.branch,
                worktree_path=args.worktree,
                allowed_globs=args.write_scope,
                claimed_paths=args.claimed_path,
                expected_tests=args.test,
                ttl_hours=args.ttl_hours,
                allow_overlap=args.allow_overlap,
            )
        except LeaseConflictError as exc:
            if args.json:
                print(json.dumps({"ok": False, "conflicts": exc.conflicts}, indent=2))  # noqa: T201
            else:
                print("lease_conflict", json.dumps(exc.conflicts, indent=2))  # noqa: T201
            return 2
        if args.json:
            print(json.dumps({"ok": True, "lease": lease.to_dict()}, indent=2))  # noqa: T201
        else:
            print(lease.lease_id)  # noqa: T201
        return 0

    if args.command == "complete":
        receipt = store.record_completion(
            lease_id=args.lease_id,
            owner_agent=args.agent,
            owner_session_id=args.session_id,
            branch=args.branch,
            worktree_path=args.worktree,
            commit_shas=args.commit,
            changed_paths=args.changed_path,
            tests_run=args.test,
            assumptions=args.assumption,
            blockers=args.blocker,
            confidence=args.confidence,
        )
        if args.json:
            print(json.dumps({"ok": True, "receipt": receipt.to_dict()}, indent=2))  # noqa: T201
        else:
            print(receipt.receipt_id)  # noqa: T201
        return 0

    if args.command == "decide":
        decision = store.record_integration_decision(
            receipt_id=args.receipt_id,
            decision=IntegrationDecisionType(args.decision),
            decided_by=args.decided_by,
            rationale=args.rationale,
            target_branch=args.target_branch,
            chosen_commits=args.commit,
            followups=args.follow_up,
            lease_id=args.lease_id,
        )
        if args.json:
            print(json.dumps({"ok": True, "decision": decision.to_dict()}, indent=2))  # noqa: T201
        else:
            print(decision.decision_id)  # noqa: T201
        return 0

    if args.command == "scan-salvage":
        items = store.scan_salvage_sources(
            include_worktrees=not args.no_worktrees,
            include_stashes=not args.no_stashes,
            max_stashes=args.max_stashes,
        )
        payload = {
            "ok": True,
            "count": len(items),
            "candidates": [item.to_dict() for item in items],
        }
        if args.json:
            print(json.dumps(payload, indent=2))  # noqa: T201
        else:
            print(payload["count"])  # noqa: T201
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
