"""Core implementation of ``aragora.nomic.dev_coordination``.

Contains the SQLite-backed :class:`DevCoordinationStore`, the work-order
classification jungle, scope/glob helpers, and the argparse CLI.

Split out of the original 5311-line ``dev_coordination.py`` module as
TCP-3 PR-A.  Dataclasses/enums/errors now live in
:mod:`aragora.nomic.dev_coordination.models`, and stateless helpers live
in :mod:`aragora.nomic.dev_coordination.utils`.  The public import
surface is preserved verbatim through ``__init__.py`` re-exports.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib  # noqa: F401 — re-exported as ``aragora.nomic.dev_coordination.hashlib`` for ``dev_salvage``
import json
import os
import re
import shlex
import sqlite3
import subprocess
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aragora.docs_only import (
    canonical_docs_container_scope,
    infer_docs_safe_hints,
    is_docs_safe_path,
    is_docs_safe_top_level_file,
)
from aragora.nomic import dev_coordination_verification as _verification_helpers
from aragora.nomic.dev_coordination.models import (
    CompletionReceipt,
    DeveloperTask,
    IntegrationDecision,
    IntegrationDecisionType,
    LeaseConflictError,
    LeaseStatus,
    SalvageCandidate,
    SalvageStatus,
    WorkLease,
)
from aragora.nomic.dev_coordination.utils import (
    _has_wildcard,  # noqa: F401 -- read as core._has_wildcard by aragora.nomic.dev_receipts
    _json_dump,
    _json_loads,
    _normalize_claim,
    _parse_dt,
    _safe_kill_probe,
    _utcnow,
)
from aragora.nomic.dev_coordination.work_order_overlap import (  # noqa: F401
    _canonical_goal_key,
    _canonical_scope_pattern,
    _canonical_work_order_scope_key,
    _claim_contains,
    _claims_overlap,
    _collapse_scope_patterns,
    _developer_task_updated_at,
    _duplicate_waiting_conflict_group_key,
    _duplicate_work_order_leasing_failed_priority,
    _glob_overlap,
    _globs_overlap_any,
    _live_overlap_sibling_priority,
    _optional_text,
    _path_matches_glob,
    _superseded_waiting_conflict_group_key,
    _waiting_conflict_candidate_text,
    _work_order_has_concrete_deliverable,
    _work_order_is_broad_explicit_pytest_umbrella,
    _work_order_is_duplicate_waiting_conflict_candidate,
    _work_order_is_duplicate_work_order_leasing_failed_candidate,
    _work_order_is_live_overlap_sibling,
    _work_order_is_specific_pytest_child,
    _work_order_scope_contains,
    _work_order_scope_patterns,
    _work_order_should_archive_duplicate_branch_deliverable,
    _work_order_source_name,
    _work_orders_overlap_by_scope,
)
from aragora.nomic.event_bus import EventBus
from aragora.nomic.global_work_queue import GlobalWorkQueue, WorkItem, WorkStatus
from aragora.worktree.fleet import FleetCoordinationStore

_ACTIVE_LEASE_STATUSES = {"active"}
_PENDING_INTEGRATION_DECISIONS = {"pending_review"}
_OPEN_SALVAGE_STATUSES = {"detected", "claimed"}
_OPEN_SUPERVISOR_RUN_STATUSES = {"planned", "active", "needs_human"}
_DUPLICATE_BRANCH_DELIVERABLE_ARCHIVE_GRACE_HOURS = 24.0
_SUPERSEDED_WAITING_CONFLICT_ARCHIVE_GRACE_HOURS = 24.0
_CLEAN_EXIT_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS = 24.0
_FAILED_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS = 24.0
_WORK_ORDER_LEASING_FAILED_ARCHIVE_GRACE_HOURS = 24.0
_WORKER_TYPE_BLOCKED_ARCHIVE_GRACE_HOURS = 24.0
_SQLITE_BUSY_TIMEOUT_MS = 60_000
_DEV_COORDINATION_DB_ENV = "ARAGORA_DEV_COORDINATION_DB"
_OPEN_DEVELOPER_TASK_STATUSES = {
    "queued",
    "leased",
    "dispatched",
    "active",
    "waiting_conflict",
    "dispatch_failed",
    "completed",
    "needs_human",
    "changes_requested",
    "timed_out",
    "failed",
    "integrating",
}
_QUEUEABLE_DEVELOPER_TASK_STATUSES = {
    "queued",
    "leased",
    "dispatched",
    "active",
    "waiting_conflict",
    "dispatch_failed",
    "needs_human",
    "changes_requested",
    "timed_out",
    "failed",
}
_REAPED_NO_RECEIPT_ARCHIVE_GRACE_HOURS = 6.0
_REAPED_NO_RECEIPT_BLOCKERS = {"stale_lease_reaped", "expired_lease_reaped"}
_TEST_FILE_PATTERN = _verification_helpers._TEST_FILE_PATTERN
_canonical_verification_command = _verification_helpers._canonical_verification_command
_extract_tests_value = _verification_helpers._extract_tests_value
_inferred_expected_tests_for_work_order = (
    _verification_helpers._inferred_expected_tests_for_work_order
)
_is_overbroad_pytest_command = _verification_helpers._is_overbroad_pytest_command
_pytest_command_targets = _verification_helpers._pytest_command_targets
_verification_command_covers_expected = _verification_helpers._verification_command_covers_expected
_verification_timeout_for_command = _verification_helpers._verification_timeout_for_command
_DOCS_ONLY_GENERATE_CAPABILITY_MATRIX_COMMANDS = (
    "python3 scripts/generate_capability_matrix.py",
    "python3 scripts/generate_capability_matrix.py --out docs-site/docs/contributing/capability-matrix.md",
)
_REPAIR_JOURNAL_MAX_ENTRIES = 20


def _is_docs_only_path(path: Any) -> bool:
    normalized = str(path or "").strip().removeprefix("./")
    if not normalized:
        return False
    return normalized.startswith("docs/") or normalized.endswith((".md", ".mdx", ".rst", ".txt"))


def _normalize_completion_outcome(
    *,
    outcome: str,
    commit_shas: list[str],
    changed_paths: list[str],
    pr_url: str,
    pr_number: int | None,
) -> str:
    normalized = str(outcome or "").strip()
    lowered = normalized.lower()
    if lowered and lowered != "completed":
        return normalized
    has_deliverable = bool(pr_url.strip() or pr_number is not None or commit_shas or changed_paths)
    return "deliverable_created" if has_deliverable else "clean_exit_no_deliverable"


class DevCoordinationStore:
    """SQLite-backed coordination state for concurrent development."""

    def __init__(
        self,
        repo_root: Path | None = None,
        db_path: Path | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.repo_root = (repo_root or Path.cwd()).resolve()
        env_db_path = os.environ.get(_DEV_COORDINATION_DB_ENV, "").strip()
        if db_path is not None:
            self.db_path = db_path
        elif env_db_path:
            configured = Path(env_db_path).expanduser()
            self.db_path = configured if configured.is_absolute() else self.repo_root / configured
        else:
            self.db_path = (
                self._git_common_dir(self.repo_root) / "aragora-agent-state" / "dev_coordination.db"
            )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._supervisor_run_snapshot_dir = self.db_path.parent / "supervisor_runs"
        self._supervisor_run_snapshot_dir.mkdir(parents=True, exist_ok=True)
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
        conn = sqlite3.connect(self.db_path, timeout=_SQLITE_BUSY_TIMEOUT_MS / 1000.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
        except Exception:
            conn.close()
            raise
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

                CREATE TABLE IF NOT EXISTS worker_repair_journals (
                    journal_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    task_key TEXT NOT NULL,
                    handoff_key TEXT NOT NULL DEFAULT '',
                    work_order_id TEXT NOT NULL,
                    supervisor_run_id TEXT NOT NULL,
                    lease_id TEXT NOT NULL,
                    owner_agent TEXT NOT NULL,
                    owner_session_id TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    worktree_path TEXT NOT NULL,
                    entry_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_repair_journal_task ON worker_repair_journals(task_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_repair_journal_key ON worker_repair_journals(task_key, created_at);
                CREATE INDEX IF NOT EXISTS idx_repair_journal_handoff_key ON worker_repair_journals(handoff_key, created_at);
                CREATE INDEX IF NOT EXISTS idx_repair_journal_work_order ON worker_repair_journals(work_order_id, created_at);

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

                CREATE TABLE IF NOT EXISTS supervisor_runs (
                    run_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    target_branch TEXT NOT NULL,
                    status TEXT NOT NULL,
                    supervisor_agents_json TEXT NOT NULL,
                    approval_policy_json TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    work_orders_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_supervisor_runs_status ON supervisor_runs(status, updated_at);
                """
            )
            self._ensure_completion_receipt_columns(conn)
            self._ensure_worker_repair_journal_columns(conn)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _ensure_completion_receipt_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(completion_receipts)").fetchall()
        }
        required_columns = {
            "task_id": "TEXT NOT NULL DEFAULT ''",
            "base_sha": "TEXT NOT NULL DEFAULT ''",
            "head_sha": "TEXT NOT NULL DEFAULT ''",
            "validations_run_json": "TEXT NOT NULL DEFAULT '[]'",
            "outcome": "TEXT NOT NULL DEFAULT 'completed'",
            "risks_json": "TEXT NOT NULL DEFAULT '[]'",
            "pr_url": "TEXT NOT NULL DEFAULT ''",
            "pr_number": "INTEGER",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for name, ddl in required_columns.items():
            if name in columns:
                continue
            conn.execute(f"ALTER TABLE completion_receipts ADD COLUMN {name} {ddl}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_receipts_task ON completion_receipts(task_id, created_at)"
        )

    @staticmethod
    def _ensure_worker_repair_journal_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(worker_repair_journals)").fetchall()
        }
        required_columns = {
            "handoff_key": "TEXT NOT NULL DEFAULT ''",
        }
        for name, ddl in required_columns.items():
            if name in columns:
                continue
            conn.execute(f"ALTER TABLE worker_repair_journals ADD COLUMN {name} {ddl}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_repair_journal_handoff_key "
            "ON worker_repair_journals(handoff_key, created_at)"
        )

    def status_summary(
        self,
        *,
        include_integrator_artifacts: bool = False,
        integrator_limit: int = 200,
    ) -> dict[str, Any]:
        active_leases = self.list_active_leases()
        pending_integrations = self.list_integration_decisions(only_pending=True)
        salvage = self.list_salvage_candidates(statuses=sorted(_OPEN_SALVAGE_STATUSES))
        supervisor_runs = self.list_supervisor_runs(statuses=sorted(_OPEN_SUPERVISOR_RUN_STATUSES))
        developer_tasks = self.list_developer_tasks(open_only=True)
        scope_violations = []
        for lease in active_leases:
            violation = lease.metadata.get("last_scope_violation")
            if not isinstance(violation, dict):
                continue
            scope_violations.append(
                {
                    "lease_id": lease.lease_id,
                    "task_id": lease.task_id,
                    "title": lease.title,
                    "owner_agent": lease.owner_agent,
                    "owner_session_id": lease.owner_session_id,
                    "branch": lease.branch,
                    "worktree_path": lease.worktree_path,
                    **violation,
                }
            )
        payload = {
            "db_path": str(self.db_path),
            "fleet_path": str(self.fleet_store.path),
            "active_leases": [item.to_dict() for item in active_leases],
            "pending_integrations": [item.to_dict() for item in pending_integrations],
            "open_salvage_candidates": [item.to_dict() for item in salvage],
            "supervisor_runs": supervisor_runs,
            "developer_tasks": [item.to_dict() for item in developer_tasks],
            "scope_violations": scope_violations,
            "counts": {
                "active_leases": len(active_leases),
                "pending_integrations": len(pending_integrations),
                "open_salvage_candidates": len(salvage),
                "supervisor_runs": len(supervisor_runs),
                "open_developer_tasks": len(developer_tasks),
                "fleet_claims": len(self.fleet_store.list_claims()),
                "fleet_merge_queue": len(self.fleet_store.list_merge_queue()),
                "scope_violations": len(scope_violations),
            },
        }
        if include_integrator_artifacts:
            payload["integrator"] = self.integrator_snapshot(limit=integrator_limit)
        return payload

    def create_supervisor_run(
        self,
        *,
        goal: str,
        target_branch: str,
        supervisor_agents: dict[str, Any],
        approval_policy: dict[str, Any],
        spec: dict[str, Any],
        work_orders: list[dict[str, Any]],
        status: str = "planned",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.cleanup_stale_supervisor_runs()
        now = _utcnow().isoformat()
        record = {
            "run_id": str(uuid.uuid4())[:12],
            "goal": goal,
            "target_branch": target_branch,
            "status": status,
            "supervisor_agents": dict(supervisor_agents),
            "approval_policy": dict(approval_policy),
            "spec": dict(spec),
            "work_orders": [dict(item) for item in work_orders],
            "metadata": dict(metadata or {}),
            "created_at": now,
            "updated_at": now,
        }
        conn = self._connect()
        try:
            self._insert_supervisor_run(conn, record)
            conn.commit()
        finally:
            conn.close()
        self._write_supervisor_run_snapshot(record)
        return record

    def get_supervisor_run(self, run_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM supervisor_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return self._restore_missing_supervisor_run(conn, run_id)
        finally:
            conn.close()
        return None if row is None else self._supervisor_run_from_row(row)

    def list_supervisor_runs(
        self,
        *,
        statuses: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM supervisor_runs ORDER BY updated_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        finally:
            conn.close()
        runs = [self._supervisor_run_from_row(row) for row in rows]
        if statuses is None:
            return runs
        allowed = set(statuses)
        return [item for item in runs if str(item.get("status", "")) in allowed]

    def list_developer_tasks(
        self,
        *,
        open_only: bool = False,
        run_id: str | None = None,
        limit: int = 200,
    ) -> list[DeveloperTask]:
        tasks: list[DeveloperTask] = []
        for run in self.list_supervisor_runs(limit=max(1, int(limit))):
            current_run_id = str(run.get("run_id", "")).strip()
            if run_id and current_run_id != str(run_id).strip():
                continue
            for raw_item in run.get("work_orders", []):
                if not isinstance(raw_item, dict):
                    continue
                task = self._developer_task_from_run(run, raw_item)
                if open_only and task.status not in _OPEN_DEVELOPER_TASK_STATUSES:
                    continue
                tasks.append(task)
        tasks.sort(key=lambda item: item.updated_at, reverse=True)
        return tasks

    def backfill_missing_blocker_metadata(self) -> int:
        from aragora.nomic.dev_receipts import backfill_missing_blocker_metadata as _impl

        return _impl(self)

    def backfill_missing_verification_plans(self) -> int:
        from aragora.nomic.dev_receipts import backfill_missing_verification_plans as _impl

        return _impl(self)

    def rehabilitate_docs_only_missing_verification_plan_work_orders(self) -> int:
        from aragora.nomic.dev_receipts import (
            rehabilitate_docs_only_missing_verification_plan_work_orders as _impl,
        )

        return _impl(self)

    def rehabilitate_dependency_deferred_missing_verification_plan_work_orders(self) -> int:
        from aragora.nomic.dev_receipts import (
            rehabilitate_dependency_deferred_missing_verification_plan_work_orders as _impl,
        )

        return _impl(self)

    def rehabilitate_deliverable_backed_clean_exit_no_deliverable_work_orders(self) -> int:
        from aragora.nomic.dev_receipts import (
            rehabilitate_deliverable_backed_clean_exit_no_deliverable_work_orders as _impl,
        )

        return _impl(self)

    def reclassify_branch_snapshot_stale_review_work_orders(self) -> int:
        from aragora.nomic.dev_receipts import (
            reclassify_branch_snapshot_stale_review_work_orders as _impl,
        )

        return _impl(self)

    def reclassify_deliverable_changes_requested_work_orders(self) -> int:
        from aragora.nomic.dev_receipts import (
            reclassify_deliverable_changes_requested_work_orders as _impl,
        )

        return _impl(self)

    def archive_reaped_no_receipt_work_orders(
        self, *, grace_period_hours: float = _REAPED_NO_RECEIPT_ARCHIVE_GRACE_HOURS
    ) -> int:
        from aragora.nomic.dev_receipts import archive_reaped_no_receipt_work_orders as _impl

        return _impl(self, grace_period_hours=grace_period_hours)

    def archive_scope_violation_no_deliverable_work_orders(
        self, *, grace_period_hours: float = _REAPED_NO_RECEIPT_ARCHIVE_GRACE_HOURS
    ) -> int:
        from aragora.nomic.dev_receipts import (
            archive_scope_violation_no_deliverable_work_orders as _impl,
        )

        return _impl(self, grace_period_hours=grace_period_hours)

    def archive_failed_no_deliverable_work_orders(
        self, *, grace_period_hours: float = _FAILED_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS
    ) -> int:
        from aragora.nomic.dev_receipts import archive_failed_no_deliverable_work_orders as _impl

        return _impl(self, grace_period_hours=grace_period_hours)

    def archive_terminal_dependency_failure_work_orders(self) -> int:
        from aragora.nomic.dev_receipts import (
            archive_terminal_dependency_failure_work_orders as _impl,
        )

        return _impl(self)

    def archive_clean_exit_no_deliverable_work_orders(
        self, *, grace_period_hours: float = _CLEAN_EXIT_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS
    ) -> int:
        from aragora.nomic.dev_receipts import (
            archive_clean_exit_no_deliverable_work_orders as _impl,
        )

        return _impl(self, grace_period_hours=grace_period_hours)

    def archive_work_order_leasing_failed_work_orders(
        self, *, grace_period_hours: float = _WORK_ORDER_LEASING_FAILED_ARCHIVE_GRACE_HOURS
    ) -> int:
        from aragora.nomic.dev_receipts import (
            archive_work_order_leasing_failed_work_orders as _impl,
        )

        return _impl(self, grace_period_hours=grace_period_hours)

    def archive_worker_type_blocked_work_orders(
        self, *, grace_period_hours: float = _WORKER_TYPE_BLOCKED_ARCHIVE_GRACE_HOURS
    ) -> int:
        from aragora.nomic.dev_receipts import archive_worker_type_blocked_work_orders as _impl

        return _impl(self, grace_period_hours=grace_period_hours)

    def archive_superseded_clean_exit_no_deliverable_work_orders(self) -> int:
        from aragora.nomic.dev_receipts import (
            archive_superseded_clean_exit_no_deliverable_work_orders as _impl,
        )

        return _impl(self)

    def archive_superseded_stale_lease_reaped_work_orders(self) -> int:
        from aragora.nomic.dev_receipts import (
            archive_superseded_stale_lease_reaped_work_orders as _impl,
        )

        return _impl(self)

    def archive_duplicate_work_order_leasing_failed_work_orders(self) -> int:
        from aragora.nomic.dev_receipts import (
            archive_duplicate_work_order_leasing_failed_work_orders as _impl,
        )

        return _impl(self)

    def archive_duplicate_branch_deliverable_work_orders(
        self, *, grace_period_hours: float = _DUPLICATE_BRANCH_DELIVERABLE_ARCHIVE_GRACE_HOURS
    ) -> int:
        from aragora.nomic.dev_receipts import (
            archive_duplicate_branch_deliverable_work_orders as _impl,
        )

        return _impl(self, grace_period_hours=grace_period_hours)

    def archive_superseded_waiting_conflict_work_orders(
        self, *, grace_period_hours: float = _SUPERSEDED_WAITING_CONFLICT_ARCHIVE_GRACE_HOURS
    ) -> int:
        from aragora.nomic.dev_receipts import (
            archive_superseded_waiting_conflict_work_orders as _impl,
        )

        return _impl(self, grace_period_hours=grace_period_hours)

    def archive_duplicate_waiting_conflict_work_orders(self) -> int:
        from aragora.nomic.dev_receipts import (
            archive_duplicate_waiting_conflict_work_orders as _impl,
        )

        return _impl(self)

    def rehabilitate_narrowed_waiting_conflict_work_orders(
        self, *, grace_period_hours: float = _SUPERSEDED_WAITING_CONFLICT_ARCHIVE_GRACE_HOURS
    ) -> int:
        from aragora.nomic.dev_receipts import (
            rehabilitate_narrowed_waiting_conflict_work_orders as _impl,
        )

        return _impl(self, grace_period_hours=grace_period_hours)

    def backfill_file_scope_from_changed_paths(self) -> int:
        from aragora.nomic.dev_receipts import backfill_file_scope_from_changed_paths as _impl

        return _impl(self)

    def backfill_missing_completion_receipts(self) -> int:
        from aragora.nomic.dev_receipts import backfill_missing_completion_receipts as _impl

        return _impl(self)

    def _rehydrate_lease_scope_from_work_order(self, work_order: dict[str, Any]) -> bool:
        from aragora.nomic.dev_receipts import _rehydrate_lease_scope_from_work_order as _impl

        return _impl(self, work_order)

    @staticmethod
    def _run_verification_commands_sync(
        worktree_path: str, commands: list[str], *, timeout: float = 900.0
    ) -> list[dict[str, Any]]:
        from aragora.nomic.dev_receipts import _run_verification_commands_sync as _impl

        return _impl(worktree_path, commands, timeout=timeout)

    def _resolve_verification_worktree(self, work_order: dict[str, Any]) -> tuple[str, Path | None]:
        from aragora.nomic.dev_receipts import _resolve_verification_worktree as _impl

        return _impl(self, work_order)

    def _cleanup_verification_worktree(self, worktree_path: Path | None) -> None:
        from aragora.nomic.dev_receipts import _cleanup_verification_worktree as _impl

        return _impl(self, worktree_path)

    @staticmethod
    def _update_completion_receipt_verification_locked(
        conn: sqlite3.Connection,
        *,
        receipt_id: str,
        verification_results: list[dict[str, Any]],
        replayed_at: str,
    ) -> bool:
        from aragora.nomic.dev_receipts import (
            _update_completion_receipt_verification_locked as _impl,
        )

        return _impl(
            conn,
            receipt_id=receipt_id,
            verification_results=verification_results,
            replayed_at=replayed_at,
        )

    def sync_completion_receipt_verification(
        self,
        *,
        receipt_id: str,
        verification_results: list[dict[str, Any]],
        replayed_at: str | None = None,
    ) -> bool:
        from aragora.nomic.dev_receipts import sync_completion_receipt_verification as _impl

        return _impl(
            self,
            receipt_id=receipt_id,
            verification_results=verification_results,
            replayed_at=replayed_at,
        )

    def _replay_merge_gate_failures(
        self,
        *,
        should_replay: Any,
        metadata_flag: str,
        prepare_commands: Any | None = None,
        merge_existing_results: bool = False,
        task_keys: list[str] | None = None,
        limit: int | None = None,
        timeout: float = 900.0,
    ) -> int:
        from aragora.nomic.dev_receipts import _replay_merge_gate_failures as _impl

        return _impl(
            self,
            should_replay=should_replay,
            metadata_flag=metadata_flag,
            prepare_commands=prepare_commands,
            merge_existing_results=merge_existing_results,
            task_keys=task_keys,
            limit=limit,
            timeout=timeout,
        )

    def replay_missing_verification_for_merge_gate_failures(
        self,
        *,
        task_keys: list[str] | None = None,
        limit: int | None = None,
        timeout: float = 900.0,
    ) -> int:
        from aragora.nomic.dev_receipts import (
            replay_missing_verification_for_merge_gate_failures as _impl,
        )

        return _impl(self, task_keys=task_keys, limit=limit, timeout=timeout)

    def replay_environment_blocked_merge_gate_failures(
        self,
        *,
        task_keys: list[str] | None = None,
        limit: int | None = None,
        timeout: float = 900.0,
    ) -> int:
        from aragora.nomic.dev_receipts import (
            replay_environment_blocked_merge_gate_failures as _impl,
        )

        return _impl(self, task_keys=task_keys, limit=limit, timeout=timeout)

    def replay_docs_only_merge_gate_failures(
        self,
        *,
        task_keys: list[str] | None = None,
        limit: int | None = None,
        timeout: float = 900.0,
    ) -> int:
        from aragora.nomic.dev_receipts import replay_docs_only_merge_gate_failures as _impl

        return _impl(self, task_keys=task_keys, limit=limit, timeout=timeout)

    def replay_missing_required_merge_gate_failures(
        self,
        *,
        task_keys: list[str] | None = None,
        limit: int | None = None,
        timeout: float = 900.0,
    ) -> int:
        from aragora.nomic.dev_receipts import replay_missing_required_merge_gate_failures as _impl

        return _impl(self, task_keys=task_keys, limit=limit, timeout=timeout)

    def replay_narrow_pytest_merge_gate_failures(
        self,
        *,
        task_keys: list[str] | None = None,
        limit: int | None = None,
        timeout: float = 900.0,
    ) -> int:
        from aragora.nomic.dev_receipts import replay_narrow_pytest_merge_gate_failures as _impl

        return _impl(self, task_keys=task_keys, limit=limit, timeout=timeout)

    def replay_targeted_merge_gate_failures(
        self,
        *,
        task_keys: list[str] | None = None,
        limit: int | None = None,
        timeout: float = 900.0,
    ) -> int:
        from aragora.nomic.dev_receipts import replay_targeted_merge_gate_failures as _impl

        return _impl(self, task_keys=task_keys, limit=limit, timeout=timeout)

    def reclassify_branch_stale_merge_gate_failures(
        self,
        *,
        limit: int | None = None,
        timeout: float = 900.0,
        task_keys: list[str] | None = None,
    ) -> int:
        from aragora.nomic.dev_receipts import reclassify_branch_stale_merge_gate_failures as _impl

        return _impl(self, limit=limit, timeout=timeout, task_keys=task_keys)

    def reconcile_merge_gate_failed_work_orders(self) -> int:
        from aragora.nomic.dev_receipts import reconcile_merge_gate_failed_work_orders as _impl

        return _impl(self)

    def get_developer_task(self, task_key: str) -> DeveloperTask | None:
        for task in self.list_developer_tasks(limit=500):
            if task.task_key == str(task_key).strip():
                return task
        return None

    def record_worker_repair_journal(
        self,
        *,
        task_id: str,
        entry: dict[str, Any],
        task_key: str | None = None,
        handoff_key: str | None = None,
        work_order_id: str | None = None,
        supervisor_run_id: str | None = None,
        lease_id: str | None = None,
        owner_agent: str | None = None,
        owner_session_id: str | None = None,
        branch: str | None = None,
        worktree_path: str | None = None,
    ) -> dict[str, Any]:
        now = _utcnow().isoformat()
        record = {
            "journal_id": str(uuid.uuid4())[:12],
            "task_id": str(task_id or "").strip(),
            "task_key": str(task_key or "").strip(),
            "handoff_key": str(handoff_key or "").strip(),
            "work_order_id": str(work_order_id or "").strip(),
            "supervisor_run_id": str(supervisor_run_id or "").strip(),
            "lease_id": str(lease_id or "").strip(),
            "owner_agent": str(owner_agent or "").strip(),
            "owner_session_id": str(owner_session_id or "").strip(),
            "branch": str(branch or "").strip(),
            "worktree_path": str(worktree_path or "").strip(),
            "entry": dict(entry),
            "created_at": now,
        }
        if (
            not record["task_id"]
            and not record["task_key"]
            and not record["handoff_key"]
            and not record["work_order_id"]
        ):
            raise ValueError(
                "repair journal requires task_id, task_key, handoff_key, or work_order_id"
            )
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO worker_repair_journals (
                    journal_id, task_id, task_key, handoff_key, work_order_id, supervisor_run_id,
                    lease_id, owner_agent, owner_session_id, branch, worktree_path,
                    entry_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["journal_id"],
                    record["task_id"],
                    record["task_key"],
                    record["handoff_key"],
                    record["work_order_id"],
                    record["supervisor_run_id"],
                    record["lease_id"],
                    record["owner_agent"],
                    record["owner_session_id"],
                    record["branch"],
                    record["worktree_path"],
                    _json_dump(record["entry"]),
                    record["created_at"],
                ),
            )
            conn.commit()
        finally:
            conn.close()
        self._publish(
            "worker_repair_journal_recorded",
            track=record["branch"] or record["task_id"] or record["task_key"],
            data={
                "journal_id": record["journal_id"],
                "task_id": record["task_id"],
                "task_key": record["task_key"],
                "handoff_key": record["handoff_key"],
                "work_order_id": record["work_order_id"],
                "supervisor_run_id": record["supervisor_run_id"],
            },
        )
        return record

    def list_worker_repair_journals(
        self,
        *,
        task_id: str | None = None,
        task_key: str | None = None,
        handoff_key: str | None = None,
        work_order_id: str | None = None,
        limit: int = _REPAIR_JOURNAL_MAX_ENTRIES,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("task_id", task_id),
            ("task_key", task_key),
            ("handoff_key", handoff_key),
            ("work_order_id", work_order_id),
        ):
            text = str(value or "").strip()
            if text:
                filters.append(f"{column} = ?")
                params.append(text)
        if not filters:
            return []
        sql = (
            "SELECT * FROM worker_repair_journals WHERE "
            + " OR ".join(filters)
            + " ORDER BY created_at DESC LIMIT ?"
        )
        params.append(max(1, int(limit)))
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        records = [
            {
                "journal_id": row["journal_id"],
                "task_id": row["task_id"],
                "task_key": row["task_key"],
                "handoff_key": row["handoff_key"],
                "work_order_id": row["work_order_id"],
                "supervisor_run_id": row["supervisor_run_id"],
                "lease_id": row["lease_id"],
                "owner_agent": row["owner_agent"],
                "owner_session_id": row["owner_session_id"],
                "branch": row["branch"],
                "worktree_path": row["worktree_path"],
                "entry": _json_loads(row["entry_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
        return list(reversed(records))

    def update_supervisor_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        work_orders: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM supervisor_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                restored = self._restore_missing_supervisor_run(conn, run_id)
                if restored is None:
                    raise KeyError(f"Unknown supervisor run: {run_id}")
                record = restored
            else:
                record = self._supervisor_run_from_row(row)
            if status is not None:
                record["status"] = status
            if work_orders is not None:
                record["work_orders"] = [dict(item) for item in work_orders]
            if metadata:
                record["metadata"] = {
                    **dict(record.get("metadata") or {}),
                    **dict(metadata),
                }
            record["updated_at"] = _utcnow().isoformat()
            self._persist_supervisor_run(conn, record)
            conn.commit()
        finally:
            conn.close()
        return record

    def list_active_leases(self) -> list[WorkLease]:
        from aragora.nomic.dev_leases import list_active_leases as _impl

        return _impl(self)

    def list_leases(
        self, *, statuses: list[str] | None = None, limit: int | None = 500
    ) -> list[WorkLease]:
        from aragora.nomic.dev_leases import list_leases as _impl

        return _impl(self, statuses=statuses, limit=limit)

    def reap_expired_leases(self) -> list[WorkLease]:
        from aragora.nomic.dev_leases import reap_expired_leases as _impl

        return _impl(self)

    def cleanup_stale_supervisor_runs(
        self,
        *,
        max_age_hours: float = 24.0,
        limit: int = 200,
    ) -> int:
        """Mark stale supervisor runs as completed so duplicate detection doesn't block new dispatches.

        A run is stale when:
        - It is older than ``max_age_hours``
        - Its status is ``planned`` with only untouched queued work orders,
          ``needs_human``/``completed`` with only non-actionable work orders,
          or ``active`` with no work orders backed by a living process
        - No work order shows evidence of active progress

        Runs with active leases whose worker process is still alive are
        never cleaned — only truly orphaned runs from previous sessions.

        This prevents the duplicate_open_work_order detector in
        _suppress_duplicate_open_work_orders from permanently blocking new work
        orders that share file scope with old, abandoned runs.

        Returns:
            Number of runs cleaned up.
        """
        terminal_wo_statuses = {
            "completed",
            "discarded",
            "needs_human",
            "dispatch_failed",
            "failed",
            "timed_out",
            "scope_violation",
            "cancelled",
        }
        now = _utcnow()
        max_age = timedelta(hours=max(0.0, float(max_age_hours)))
        conn = self._connect()
        try:
            active_lease_ids = {
                str(row["lease_id"]).strip()
                for row in conn.execute(
                    "SELECT lease_id FROM leases WHERE status = ?",
                    (LeaseStatus.ACTIVE.value,),
                ).fetchall()
                if str(row["lease_id"]).strip()
            }
        finally:
            conn.close()

        def _has_live_worker_process(work_order: dict[str, Any]) -> bool:
            metadata = work_order.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            raw_pid = work_order.get("worker_pid")
            if raw_pid is None:
                raw_pid = metadata.get("worker_pid")
            if raw_pid is None:
                return False
            probe = _safe_kill_probe(raw_pid)
            return probe is None or isinstance(probe, PermissionError)

        runs = self.list_supervisor_runs(limit=limit)
        cleaned = 0
        for run in runs:
            status = str(run.get("status", "")).strip().lower()
            if status not in ("planned", "active", "needs_human", "completed"):
                continue
            updated_at = _parse_dt(str(run.get("updated_at") or run.get("created_at") or ""))
            if updated_at is None:
                continue
            if max_age.total_seconds() > 0 and (now - updated_at) < max_age:
                continue
            work_orders = run.get("work_orders", [])
            if not work_orders:
                continue
            if any(
                isinstance(wo, dict)
                and (
                    _optional_text(wo.get("lease_id")) in active_lease_ids
                    or _has_live_worker_process(wo)
                )
                for wo in work_orders
            ):
                continue
            if status == "planned":
                all_stranded = True
                changed = False
                for wo in work_orders:
                    if not isinstance(wo, dict):
                        continue
                    wo_status = str(wo.get("status", "")).strip().lower()
                    if wo_status != "queued":
                        all_stranded = False
                        break
                    if (
                        wo.get("lease_id")
                        or wo.get("owner_session_id")
                        or wo.get("branch")
                        or wo.get("worktree_path")
                        or wo.get("receipt_id")
                        or wo.get("commit_shas")
                        or wo.get("changed_paths")
                        or wo.get("changed_files")
                        or wo.get("pr_url")
                        or wo.get("adopted_pr")
                    ):
                        all_stranded = False
                        break
                if not all_stranded:
                    continue
                archived_at = now.isoformat()
                for wo in work_orders:
                    if not isinstance(wo, dict):
                        continue
                    metadata = dict(wo.get("metadata") or {})
                    metadata.update(
                        {
                            "archived_due_to": "stale_planned_run",
                            "archive_reason": "stale_planned_run",
                            "archived_at": archived_at,
                            "previous_status": str(wo.get("status") or "queued").strip()
                            or "queued",
                        }
                    )
                    wo["metadata"] = metadata
                    wo["status"] = "discarded"
                    wo["failure_reason"] = "stale_planned_run"
                    changed = True
                if changed:
                    self.update_supervisor_run(
                        run["run_id"],
                        status="completed",
                        work_orders=work_orders,
                    )
                    cleaned += 1
                continue
            if status == "active":
                # Active runs from previous sessions may have orphaned work
                # orders.  Only clean if no work order has a living worker
                # process (active lease with live PID or live work-order PID).
                has_live_worker = False
                # Collect lease IDs to check against the DB
                lease_ids = [
                    wo.get("lease_id")
                    for wo in work_orders
                    if isinstance(wo, dict)
                    and wo.get("lease_id")
                    and str(wo.get("status", "")).strip().lower() not in terminal_wo_statuses
                ]
                active_lease_pids: dict[str, Any] = {}
                if lease_ids:
                    conn = self._connect()
                    try:
                        placeholders = ",".join("?" for _ in lease_ids)
                        rows = conn.execute(
                            f"SELECT lease_id, metadata FROM leases WHERE status = 'active' AND lease_id IN ({placeholders})",
                            lease_ids,
                        ).fetchall()
                        for row in rows:
                            meta = (
                                json.loads(row["metadata"] or "{}")
                                if isinstance(row["metadata"], str)
                                else (row["metadata"] or {})
                            )
                            active_lease_pids[row["lease_id"]] = meta.get("worker_pid")
                    finally:
                        conn.close()
                for wo in work_orders:
                    if not isinstance(wo, dict):
                        continue
                    wo_status = str(wo.get("status", "")).strip().lower()
                    if wo_status in terminal_wo_statuses:
                        continue
                    # Check lease PID if the lease is still active
                    lid = wo.get("lease_id")
                    if lid and lid in active_lease_pids:
                        raw_pid = active_lease_pids[lid]
                        if raw_pid is not None:
                            probe = _safe_kill_probe(raw_pid)
                            if probe is None or isinstance(probe, PermissionError):
                                has_live_worker = True
                                break
                        else:
                            # No PID recorded but lease is active — treat
                            # as live to be safe.
                            has_live_worker = True
                            break
                    # Check work order-level PID
                    wo_pid = wo.get("pid")
                    if wo_pid is not None:
                        probe = _safe_kill_probe(wo_pid)
                        if probe is None or isinstance(probe, PermissionError):
                            has_live_worker = True
                            break
                if has_live_worker:
                    continue
                archived_at = now.isoformat()
                changed = False
                for wo in work_orders:
                    if not isinstance(wo, dict):
                        continue
                    wo_status = str(wo.get("status", "")).strip().lower()
                    if wo_status in terminal_wo_statuses:
                        continue
                    metadata = dict(wo.get("metadata") or {})
                    metadata.update(
                        {
                            "archived_due_to": "stale_active_run",
                            "archive_reason": "stale_active_run",
                            "archived_at": archived_at,
                            "previous_status": wo_status or "queued",
                        }
                    )
                    wo["metadata"] = metadata
                    wo["status"] = "discarded"
                    wo["failure_reason"] = "stale_active_run"
                    changed = True
                if changed:
                    self.update_supervisor_run(
                        run["run_id"],
                        status="completed",
                        work_orders=work_orders,
                    )
                    cleaned += 1
                continue
            all_terminal = all(
                str(wo.get("status", "")).strip().lower() in terminal_wo_statuses
                for wo in work_orders
                if isinstance(wo, dict)
            )
            if not all_terminal:
                continue
            # Mark non-terminal work orders as completed
            changed = False
            for wo in work_orders:
                if not isinstance(wo, dict):
                    continue
                wo_status = str(wo.get("status", "")).strip().lower()
                if wo_status not in ("completed",):
                    wo["status"] = "completed"
                    changed = True
            if changed or status == "needs_human":
                self.update_supervisor_run(
                    run["run_id"],
                    status="completed",
                    work_orders=work_orders,
                )
                cleaned += 1
        return cleaned

    def reap_stale_leases(self, *, stale_threshold_seconds: float = 1800.0) -> list[WorkLease]:
        from aragora.nomic.dev_leases import reap_stale_leases as _impl

        return _impl(self, stale_threshold_seconds=stale_threshold_seconds)

    def list_completion_receipts(
        self, lease_id: str | None = None, *, task_id: str | None = None, limit: int | None = None
    ) -> list[CompletionReceipt]:
        from aragora.nomic.dev_receipts import list_completion_receipts as _impl

        return _impl(self, lease_id, task_id=task_id, limit=limit)

    def get_completion_receipt(self, receipt_id: str) -> CompletionReceipt | None:
        from aragora.nomic.dev_receipts import get_completion_receipt as _impl

        return _impl(self, receipt_id)

    def list_integration_decisions(
        self, *, only_pending: bool = False, receipt_id: str | None = None, limit: int | None = None
    ) -> list[IntegrationDecision]:
        from aragora.nomic.dev_receipts import list_integration_decisions as _impl

        return _impl(self, only_pending=only_pending, receipt_id=receipt_id, limit=limit)

    def integrator_snapshot(self, *, limit: int = 200) -> dict[str, Any]:
        bounded_limit = max(1, int(limit))
        return {
            "generated_at": _utcnow().isoformat(),
            "leases": [item.to_dict() for item in self.list_leases(limit=bounded_limit)],
            "developer_tasks": [
                item.to_dict()
                for item in self.list_developer_tasks(open_only=False, limit=bounded_limit)
            ],
            "completion_receipts": [
                item.to_dict() for item in self.list_completion_receipts(limit=bounded_limit)
            ],
            "integration_decisions": [
                item.to_dict() for item in self.list_integration_decisions(limit=bounded_limit)
            ],
            "salvage_candidates": [
                item.to_dict()
                for item in self.list_salvage_candidates(statuses=sorted(_OPEN_SALVAGE_STATUSES))
            ],
        }

    def list_salvage_candidates(self, statuses: list[str] | None = None) -> list[SalvageCandidate]:
        from aragora.nomic.dev_salvage import list_salvage_candidates as _impl

        return _impl(self, statuses)

    def find_conflicting_leases(
        self,
        *,
        allowed_globs: list[str],
        claimed_paths: list[str],
        owner_session_id: str | None = None,
        exclude_lease_id: str | None = None,
    ) -> list[dict[str, Any]]:
        from aragora.nomic.dev_leases import find_conflicting_leases as _impl

        return _impl(
            self,
            allowed_globs=allowed_globs,
            claimed_paths=claimed_paths,
            owner_session_id=owner_session_id,
            exclude_lease_id=exclude_lease_id,
        )

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
        from aragora.nomic.dev_leases import claim_lease as _impl

        return _impl(
            self,
            task_id=task_id,
            title=title,
            owner_agent=owner_agent,
            owner_session_id=owner_session_id,
            branch=branch,
            worktree_path=worktree_path,
            allowed_globs=allowed_globs,
            claimed_paths=claimed_paths,
            expected_tests=expected_tests,
            ttl_hours=ttl_hours,
            metadata=metadata,
            allow_overlap=allow_overlap,
        )

    def _find_conflicting_leases_locked(
        self,
        conn: sqlite3.Connection,
        *,
        allowed_globs: list[str],
        claimed_paths: list[str],
        owner_session_id: str | None = None,
        exclude_lease_id: str | None = None,
    ) -> list[dict[str, Any]]:
        from aragora.nomic.dev_leases import _find_conflicting_leases_locked as _impl

        return _impl(
            self,
            conn,
            allowed_globs=allowed_globs,
            claimed_paths=claimed_paths,
            owner_session_id=owner_session_id,
            exclude_lease_id=exclude_lease_id,
        )

    def heartbeat_lease(self, lease_id: str, ttl_hours: float | None = None) -> WorkLease:
        from aragora.nomic.dev_leases import heartbeat_lease as _impl

        return _impl(self, lease_id, ttl_hours)

    def persist_scope_violation(
        self, lease_id: str, *, changed_paths: list[str], violations: list[dict[str, Any]]
    ) -> None:
        from aragora.nomic.dev_leases import persist_scope_violation as _impl

        return _impl(self, lease_id, changed_paths=changed_paths, violations=violations)

    def update_lease_metadata(self, lease_id: str, updates: dict[str, Any]) -> None:
        from aragora.nomic.dev_leases import update_lease_metadata as _impl

        return _impl(self, lease_id, updates)

    def release_lease(self, lease_id: str, status: LeaseStatus = LeaseStatus.RELEASED) -> WorkLease:
        from aragora.nomic.dev_leases import release_lease as _impl

        return _impl(self, lease_id, status)

    def record_completion(
        self,
        *,
        lease_id: str,
        owner_agent: str,
        owner_session_id: str,
        branch: str,
        worktree_path: str,
        base_sha: str | None = None,
        head_sha: str | None = None,
        commit_shas: list[str] | None = None,
        changed_paths: list[str] | None = None,
        tests_run: list[str] | None = None,
        validations_run: list[str] | None = None,
        assumptions: list[str] | None = None,
        blockers: list[str] | None = None,
        outcome: str = "completed",
        risks: list[str] | None = None,
        pr_url: str | None = None,
        pr_number: int | None = None,
        confidence: float = 0.0,
        metadata: dict[str, Any] | None = None,
        require_session_ownership: bool = True,
    ) -> CompletionReceipt:
        from aragora.nomic.dev_receipts import record_completion as _impl

        return _impl(
            self,
            lease_id=lease_id,
            owner_agent=owner_agent,
            owner_session_id=owner_session_id,
            branch=branch,
            worktree_path=worktree_path,
            base_sha=base_sha,
            head_sha=head_sha,
            commit_shas=commit_shas,
            changed_paths=changed_paths,
            tests_run=tests_run,
            validations_run=validations_run,
            assumptions=assumptions,
            blockers=blockers,
            outcome=outcome,
            risks=risks,
            pr_url=pr_url,
            pr_number=pr_number,
            confidence=confidence,
            metadata=metadata,
            require_session_ownership=require_session_ownership,
        )

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
        from aragora.nomic.dev_receipts import record_integration_decision as _impl

        return _impl(
            self,
            receipt_id=receipt_id,
            decision=decision,
            decided_by=decided_by,
            rationale=rationale,
            target_branch=target_branch,
            chosen_commits=chosen_commits,
            followups=followups,
            lease_id=lease_id,
        )

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
        from aragora.nomic.dev_salvage import upsert_salvage_candidate as _impl

        return _impl(
            self,
            source_kind=source_kind,
            source_ref=source_ref,
            branch=branch,
            worktree_path=worktree_path,
            stash_ref=stash_ref,
            head_sha=head_sha,
            changed_paths=changed_paths,
            summary=summary,
            likely_value=likely_value,
            status=status,
            metadata=metadata,
        )

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

    def developer_task_work_items(self) -> list[WorkItem]:
        items: list[WorkItem] = []
        for task in self.list_developer_tasks(open_only=True):
            if task.status not in _QUEUEABLE_DEVELOPER_TASK_STATUSES:
                continue
            items.append(task.to_work_item())
        return items

    async def sync_developer_task_queue(
        self,
        queue: GlobalWorkQueue | None = None,
        *,
        complete_missing: bool = True,
    ) -> dict[str, int]:
        """Project open developer tasks into the global work queue."""
        self.backfill_missing_completion_receipts()
        self.backfill_missing_blocker_metadata()
        self.backfill_missing_verification_plans()
        self.rehabilitate_docs_only_missing_verification_plan_work_orders()
        self.rehabilitate_dependency_deferred_missing_verification_plan_work_orders()
        self.rehabilitate_deliverable_backed_clean_exit_no_deliverable_work_orders()
        self.reclassify_branch_snapshot_stale_review_work_orders()
        self.reclassify_deliverable_changes_requested_work_orders()
        self.archive_superseded_clean_exit_no_deliverable_work_orders()
        self.archive_superseded_stale_lease_reaped_work_orders()
        self.archive_reaped_no_receipt_work_orders()
        self.archive_scope_violation_no_deliverable_work_orders()
        self.archive_failed_no_deliverable_work_orders()
        self.archive_clean_exit_no_deliverable_work_orders()
        self.archive_work_order_leasing_failed_work_orders()
        self.archive_worker_type_blocked_work_orders()
        self.archive_duplicate_work_order_leasing_failed_work_orders()
        self.archive_duplicate_branch_deliverable_work_orders()
        self.archive_superseded_waiting_conflict_work_orders()
        self.archive_duplicate_waiting_conflict_work_orders()
        self.rehabilitate_narrowed_waiting_conflict_work_orders()
        work_queue = queue or GlobalWorkQueue(storage_dir=self.repo_root / ".work_queue")
        await work_queue.initialize()

        desired_items = {item.id: item for item in self.developer_task_work_items()}
        existing_items = {item.id: item for item in await work_queue.list_items(limit=10_000)}

        counts = {
            "created": 0,
            "updated": 0,
            "reopened": 0,
            "completed": 0,
            "skipped_active": 0,
            "open_items": len(desired_items),
        }

        for item_id, item in desired_items.items():
            existing = existing_items.get(item_id)
            if existing and existing.status in (WorkStatus.CLAIMED, WorkStatus.IN_PROGRESS):
                counts["skipped_active"] += 1
                continue
            await work_queue.upsert(
                item,
                allow_reopen=True,
                preserve_claimed=True,
                persist=False,
            )
            if existing is None:
                counts["created"] += 1
            elif existing.status in (WorkStatus.COMPLETED, WorkStatus.FAILED):
                counts["reopened"] += 1
            else:
                counts["updated"] += 1

        if complete_missing:
            for item_id, existing in existing_items.items():
                if not item_id.startswith("task:") or item_id in desired_items:
                    continue
                if existing.status in (
                    WorkStatus.CLAIMED,
                    WorkStatus.IN_PROGRESS,
                    WorkStatus.COMPLETED,
                    WorkStatus.FAILED,
                ):
                    continue
                completed = await work_queue.complete(
                    item_id,
                    result={"source": "dev_coordination", "reason": "task_no_longer_open"},
                    persist=False,
                )
                if completed is not None:
                    counts["completed"] += 1

        await work_queue.reprioritize()
        return counts

    async def sync_pending_work_queue(
        self,
        queue: GlobalWorkQueue | None = None,
        *,
        complete_missing: bool = True,
    ) -> dict[str, int]:
        """Project pending integration/salvage items into the global work queue."""
        work_queue = queue or GlobalWorkQueue(storage_dir=self.repo_root / ".work_queue")
        await work_queue.initialize()

        desired_items = {item.id: item for item in self.pending_work_items()}
        existing_items = {item.id: item for item in await work_queue.list_items(limit=10_000)}
        managed_prefixes = ("integration:", "salvage:")

        counts = {
            "created": 0,
            "updated": 0,
            "reopened": 0,
            "completed": 0,
            "skipped_active": 0,
            "open_items": len(desired_items),
        }

        for item_id, item in desired_items.items():
            existing = existing_items.get(item_id)
            if existing and existing.status in (WorkStatus.CLAIMED, WorkStatus.IN_PROGRESS):
                counts["skipped_active"] += 1
                continue

            await work_queue.upsert(
                item,
                allow_reopen=True,
                preserve_claimed=True,
                persist=False,
            )
            if existing is None:
                counts["created"] += 1
            elif existing.status in (WorkStatus.COMPLETED, WorkStatus.FAILED):
                counts["reopened"] += 1
            else:
                counts["updated"] += 1

        if complete_missing:
            for item_id, existing in existing_items.items():
                if not item_id.startswith(managed_prefixes) or item_id in desired_items:
                    continue
                if existing.status in (
                    WorkStatus.CLAIMED,
                    WorkStatus.IN_PROGRESS,
                    WorkStatus.COMPLETED,
                    WorkStatus.FAILED,
                ):
                    continue
                completed = await work_queue.complete(
                    item_id,
                    result={"source": "dev_coordination", "reason": "no_longer_pending"},
                    persist=False,
                )
                if completed is not None:
                    counts["completed"] += 1

        await work_queue.reprioritize()
        return counts

    def scan_salvage_sources(
        self, *, include_worktrees: bool = True, include_stashes: bool = True, max_stashes: int = 25
    ) -> list[SalvageCandidate]:
        from aragora.nomic.dev_salvage import scan_salvage_sources as _impl

        return _impl(
            self,
            include_worktrees=include_worktrees,
            include_stashes=include_stashes,
            max_stashes=max_stashes,
        )

    def _scan_worktrees(self) -> list[SalvageCandidate]:
        from aragora.nomic.dev_salvage import _scan_worktrees as _impl

        return _impl(self)

    def _scan_stashes(self, *, max_stashes: int = 25) -> list[SalvageCandidate]:
        from aragora.nomic.dev_salvage import _scan_stashes as _impl

        return _impl(self, max_stashes=max_stashes)

    def _publish(self, event_type: str, *, track: str, data: dict[str, Any]) -> None:
        try:
            self.event_bus.publish(event_type, track=track, data=data)
        except (OSError, ValueError, RuntimeError):
            # Coordination state must not fail closed if the event bus is unavailable.
            pass

    @staticmethod
    def _fleet_claim_paths(lease: WorkLease) -> list[str]:
        return lease.claimed_paths or lease.allowed_globs

    def _release_fleet_claims_for_lease(self, lease: WorkLease) -> None:
        release_paths = self._fleet_claim_paths(lease)
        if release_paths:
            self.fleet_store.release_paths(
                session_id=lease.owner_session_id,
                paths=release_paths,
            )

    def _find_fleet_queue_item(self, *, receipt_id: str) -> dict[str, Any] | None:
        for item in self.fleet_store.list_merge_queue():
            metadata = item.get("metadata")
            if isinstance(metadata, dict) and str(metadata.get("receipt_id", "")) == receipt_id:
                return item
        return None

    def _validate_completion_scope(
        self,
        lease: WorkLease,
        *,
        changed_paths: list[str],
        owner_session_id: str,
        branch: str,
        require_session_ownership: bool = True,
    ) -> list[dict[str, Any]]:
        from aragora.nomic.dev_leases import _validate_completion_scope as _impl

        return _impl(
            self,
            lease,
            changed_paths=changed_paths,
            owner_session_id=owner_session_id,
            branch=branch,
            require_session_ownership=require_session_ownership,
        )

    def mark_supervisor_run_merged(
        self, *, receipt_id: str, merge_commit_sha: str | None = None, merged_at: str | None = None
    ) -> None:
        from aragora.nomic.dev_receipts import mark_supervisor_run_merged as _impl

        return _impl(
            self, receipt_id=receipt_id, merge_commit_sha=merge_commit_sha, merged_at=merged_at
        )

    def _record_supervisor_merge_telemetry(
        self,
        lease_metadata: dict[str, Any] | None,
        *,
        receipt: CompletionReceipt,
        merge_commit_sha: str | None,
        merged_at: str,
    ) -> None:
        from aragora.nomic.dev_receipts import _record_supervisor_merge_telemetry as _impl

        return _impl(
            self,
            lease_metadata,
            receipt=receipt,
            merge_commit_sha=merge_commit_sha,
            merged_at=merged_at,
        )

    @staticmethod
    def _supervisor_run_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "goal": row["goal"],
            "target_branch": row["target_branch"],
            "status": row["status"],
            "supervisor_agents": _json_loads(row["supervisor_agents_json"], {}),
            "approval_policy": _json_loads(row["approval_policy_json"], {}),
            "spec": _json_loads(row["spec_json"], {}),
            "work_orders": _json_loads(row["work_orders_json"], []),
            "metadata": _json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _developer_task_from_run(
        run: dict[str, Any],
        work_order: dict[str, Any],
    ) -> DeveloperTask:
        run_id = str(run.get("run_id", "")).strip()
        task_id = (
            str(work_order.get("work_order_id", "")).strip()
            or str(work_order.get("task_id", "")).strip()
            or "task"
        )
        status = str(work_order.get("status", "")).strip().lower() or "queued"
        metadata = dict(work_order.get("metadata") or {})
        lease_id = _optional_text(work_order.get("lease_id"))
        return DeveloperTask(
            task_key=f"{run_id}:{task_id}",
            task_id=task_id,
            run_id=run_id,
            goal=str(run.get("goal", "")).strip(),
            title=str(work_order.get("title", "")).strip() or task_id,
            status=status,
            priority=_developer_task_priority(work_order),
            owner_agent=_optional_text(
                work_order.get("target_agent"),
                metadata.get("owner_agent"),
            )
            or "",
            reviewer_agent=_optional_text(
                work_order.get("reviewer_agent"),
                metadata.get("reviewer_agent"),
            )
            or "",
            blocked_by=_developer_task_blockers(work_order),
            acceptance_checks=_developer_task_acceptance_checks(work_order),
            allowed_paths=[
                str(item).strip() for item in work_order.get("file_scope", []) if str(item).strip()
            ],
            lease_id=lease_id or None,
            owner_session_id=_optional_text(work_order.get("owner_session_id")) or None,
            branch=_optional_text(work_order.get("branch")) or None,
            worktree_path=_optional_text(work_order.get("worktree_path")) or None,
            receipt_id=_optional_text(work_order.get("receipt_id")) or None,
            created_at=str(run.get("created_at", _utcnow().isoformat())),
            updated_at=_developer_task_updated_at(work_order, run),
            metadata={
                **metadata,
                "base_sha": _optional_text(work_order.get("base_sha")) or None,
                "head_sha": _optional_text(work_order.get("head_sha")) or None,
                "commit_shas": [
                    str(item).strip()
                    for item in work_order.get("commit_shas", [])
                    if str(item).strip()
                ],
                "changed_paths": [
                    str(item).strip()
                    for item in work_order.get("changed_paths", [])
                    if str(item).strip()
                ],
                "changed_files": [
                    str(item).strip()
                    for item in work_order.get("changed_files", [])
                    if str(item).strip()
                ],
                "pr_url": _optional_text(work_order.get("pr_url")) or None,
                "pr_number": work_order.get("pr_number"),
                "adopted_pr": _optional_text(work_order.get("adopted_pr")) or None,
                "worker_outcome": _optional_text(work_order.get("worker_outcome")) or None,
                "failure_reason": _optional_text(work_order.get("failure_reason")) or None,
                "dispatch_error": _optional_text(work_order.get("dispatch_error")) or None,
                "blocking_question": _optional_text(work_order.get("blocking_question")) or None,
                "blocker": dict(work_order.get("blocker") or {})
                if isinstance(work_order.get("blocker"), dict)
                else None,
                "target_branch": str(run.get("target_branch", "")).strip() or None,
                "run_status": str(run.get("status", "")).strip() or None,
                "success_criteria": dict(work_order.get("success_criteria") or {}),
                "dependency_ids": [
                    str(item).strip()
                    for item in work_order.get("dependency_ids", [])
                    if str(item).strip()
                ],
                "risk_level": str(work_order.get("risk_level", "")).strip() or None,
                "estimated_complexity": str(work_order.get("estimated_complexity", "")).strip()
                or None,
                "approval_required": bool(work_order.get("approval_required", False)),
            },
        )

    @staticmethod
    def _derive_supervisor_run_status(work_orders: list[dict[str, Any]]) -> str:
        statuses = {str(item.get("status", "")).strip() for item in work_orders if item}
        if not statuses:
            return "planned"
        terminal = {
            "merged",
            "discarded",
            "salvage",
            "completed",
            "failed",
            "timed_out",
            "scope_violation",
        }
        if statuses <= terminal:
            return "completed"
        if (
            "changes_requested" in statuses
            or "needs_human" in statuses
            or "dispatch_failed" in statuses
        ):
            return "needs_human"
        forward_progress = {"queued", "leased", "dispatched"}
        non_terminal = statuses - terminal
        if non_terminal and not (non_terminal & forward_progress):
            return "needs_human"
        return "active"

    def _persist_supervisor_run(
        self,
        conn: sqlite3.Connection,
        record: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            UPDATE supervisor_runs
            SET goal = ?, target_branch = ?, status = ?, supervisor_agents_json = ?,
                approval_policy_json = ?, spec_json = ?, work_orders_json = ?,
                metadata_json = ?, updated_at = ?
            WHERE run_id = ?
            """,
            (
                record["goal"],
                record["target_branch"],
                record["status"],
                _json_dump(record.get("supervisor_agents", {})),
                _json_dump(record.get("approval_policy", {})),
                _json_dump(record.get("spec", {})),
                _json_dump(record.get("work_orders", [])),
                _json_dump(record.get("metadata", {})),
                record["updated_at"],
                record["run_id"],
            ),
        )
        self._write_supervisor_run_snapshot(record)

    def _insert_supervisor_run(
        self,
        conn: sqlite3.Connection,
        record: dict[str, Any],
        *,
        ignore_existing: bool = False,
    ) -> None:
        insert_mode = "INSERT OR IGNORE" if ignore_existing else "INSERT"
        conn.execute(
            f"""
            {insert_mode} INTO supervisor_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["run_id"],
                record["goal"],
                record["target_branch"],
                record["status"],
                _json_dump(record.get("supervisor_agents", {})),
                _json_dump(record.get("approval_policy", {})),
                _json_dump(record.get("spec", {})),
                _json_dump(record.get("work_orders", [])),
                _json_dump(record.get("metadata", {})),
                record["created_at"],
                record["updated_at"],
            ),
        )

    def _supervisor_run_snapshot_path(self, run_id: str) -> Path:
        safe_run_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(run_id).strip())
        return self._supervisor_run_snapshot_dir / f"{safe_run_id}.json"

    def _write_supervisor_run_snapshot(self, record: dict[str, Any]) -> None:
        run_id = str(record.get("run_id", "")).strip()
        if not run_id:
            return
        path = self._supervisor_run_snapshot_path(run_id)
        tmp_path = path.with_suffix(".json.tmp")
        payload = json.dumps(record, indent=2, sort_keys=True) + "\n"
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(path)

    def _load_supervisor_run_snapshot(self, run_id: str) -> dict[str, Any] | None:
        path = self._supervisor_run_snapshot_path(run_id)
        if not path.exists():
            return None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(loaded, dict):
            return None
        if str(loaded.get("run_id", "")).strip() != str(run_id).strip():
            return None
        return {
            "run_id": str(loaded.get("run_id", "")).strip(),
            "goal": str(loaded.get("goal", "")),
            "target_branch": str(loaded.get("target_branch", "")),
            "status": str(loaded.get("status", "")),
            "supervisor_agents": dict(loaded.get("supervisor_agents") or {}),
            "approval_policy": dict(loaded.get("approval_policy") or {}),
            "spec": dict(loaded.get("spec") or {}),
            "work_orders": [dict(item) for item in loaded.get("work_orders", [])],
            "metadata": dict(loaded.get("metadata") or {}),
            "created_at": str(loaded.get("created_at", "")),
            "updated_at": str(loaded.get("updated_at", "")),
        }

    def _restore_missing_supervisor_run(
        self,
        conn: sqlite3.Connection,
        run_id: str,
    ) -> dict[str, Any] | None:
        snapshot = self._load_supervisor_run_snapshot(run_id)
        if snapshot is None:
            return None
        self._insert_supervisor_run(conn, snapshot, ignore_existing=True)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM supervisor_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is not None:
            return self._supervisor_run_from_row(row)
        return snapshot

    def _sync_supervisor_run_from_lease(
        self,
        lease_metadata: dict[str, Any] | None,
        *,
        update: dict[str, Any],
    ) -> None:
        if not lease_metadata:
            return
        run_id = str(lease_metadata.get("supervisor_run_id", "")).strip()
        work_order_id = str(lease_metadata.get("work_order_id", "")).strip()
        if not run_id or not work_order_id:
            return
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM supervisor_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if str(item.get("work_order_id", "")).strip() != work_order_id:
                    continue
                reaped_failure = _optional_text(update.get("failure_reason"))
                if reaped_failure in {
                    "stale_lease_reaped",
                    "expired_lease_reaped",
                } and _work_order_has_concrete_deliverable(item):
                    preserved_update = {
                        key: value
                        for key, value in update.items()
                        if key not in {"status", "failure_reason", "blocking_question", "blocker"}
                    }
                    if not preserved_update:
                        break
                    item.update(preserved_update)
                    changed = True
                    break
                item.update(update)
                if _optional_text(update.get("status")) == "completed":
                    for key in (
                        "failure_reason",
                        "blocking_question",
                        "blocker",
                        "dispatch_error",
                    ):
                        item.pop(key, None)
                    item["blockers"] = []
                changed = True
                break
            if not changed:
                return
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = _utcnow().isoformat()
            self._persist_supervisor_run(conn, record)
            conn.commit()
        finally:
            conn.close()


def _flatten_acceptance_value(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        items: list[str] = []
        for key, nested in value.items():
            for text in _flatten_acceptance_value(nested):
                items.append(f"{key}: {text}")
        return items
    if isinstance(value, list):
        values: list[str] = []
        for nested in value:
            values.extend(_flatten_acceptance_value(nested))
        return values
    text = str(value or "").strip()
    return [text] if text else []


def _work_order_identifier(work_order: dict[str, Any]) -> str:
    return (
        str(work_order.get("work_order_id", "")).strip()
        or str(work_order.get("task_id", "")).strip()
        or str(work_order.get("id", "")).strip()
    )


def _find_work_order(record: dict[str, Any], work_order_id: str) -> dict[str, Any] | None:
    target = str(work_order_id).strip()
    if not target:
        return None
    for item in record.get("work_orders", []):
        if not isinstance(item, dict):
            continue
        if _work_order_identifier(item) == target:
            return item
    return None


def _developer_task_acceptance_checks(work_order: dict[str, Any]) -> list[str]:
    checks: list[str] = []
    for entry in work_order.get("expected_tests", []):
        text = str(entry).strip()
        if text and text not in checks:
            checks.append(text)
    for entry in _flatten_acceptance_value(work_order.get("success_criteria", {})):
        if entry not in checks:
            checks.append(entry)
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict):
        for entry in metadata.get("acceptance_criteria", []):
            text = str(entry).strip()
            if text and text not in checks:
                checks.append(text)
    return checks


def _merge_gate_state_for_work_order(work_order: dict[str, Any]) -> dict[str, Any]:
    expected_checks = _inferred_expected_tests_for_work_order(work_order)
    verification_results = [
        dict(entry)
        for entry in work_order.get("verification_results", [])
        if isinstance(entry, dict) and str(entry.get("command", "")).strip()
    ]
    missing_checks = [
        command
        for command in expected_checks
        if not any(
            _verification_command_covers_expected(entry.get("command", ""), command)
            for entry in verification_results
        )
    ]
    failed_checks = [
        dict(entry)
        for entry in verification_results
        if any(
            _verification_command_covers_expected(entry.get("command", ""), command)
            for command in expected_checks
        )
        and not bool(entry.get("passed", False))
    ]
    deferred_dependency_ids = [
        str(dep).strip()
        for dep in (
            dict(work_order.get("metadata") or {}).get("deferred_verification_to_dependency_ids")
            or []
        )
        if str(dep).strip()
    ]

    if deferred_dependency_ids:
        return {
            "enabled": True,
            "expected_checks": expected_checks,
            "verification_results": verification_results,
            "verification_missing_reason": None,
            "checks_passed": True,
            "human_approval_required": True,
            "merge_eligible": True,
            "blocked_reasons": [],
            "verification_deferred_to_dependency_ids": deferred_dependency_ids,
        }

    blocked_reasons: list[str] = []
    verification_missing_reason: str | None = None
    if not expected_checks:
        candidates = [
            str(path).strip()
            for path in work_order.get("changed_paths", []) or work_order.get("file_scope", [])
            if str(path).strip()
        ]
        if candidates and all(_is_docs_only_path(path) for path in candidates):
            return {
                "enabled": True,
                "expected_checks": expected_checks,
                "verification_results": verification_results,
                "verification_missing_reason": None,
                "checks_passed": True,
                "human_approval_required": True,
                "merge_eligible": True,
                "blocked_reasons": [],
            }
        verification_missing_reason = "missing_verification_plan"
        blocked_reasons.append(
            "merge gate blocked: missing verification plan or verification command"
        )
    if missing_checks:
        blocked_reasons.append(
            "merge gate blocked: required verification did not run: "
            + ", ".join(missing_checks[:3])
        )
    if failed_checks:
        first = failed_checks[0]
        reason = (
            "merge gate blocked: verification failed: "
            f"{first.get('command', '')} (exit {first.get('exit_code', -1)})"
        )
        stderr = str(first.get("stderr", "")).strip()
        if stderr:
            reason = f"{reason} - {stderr.splitlines()[0][:200]}"
        blocked_reasons.append(reason)

    checks_passed = not blocked_reasons
    return {
        "enabled": True,
        "expected_checks": expected_checks,
        "verification_results": verification_results,
        "verification_missing_reason": verification_missing_reason,
        "checks_passed": checks_passed,
        "human_approval_required": True,
        "merge_eligible": checks_passed,
        "blocked_reasons": blocked_reasons,
    }


def _developer_task_blockers(work_order: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for value in work_order.get("blockers", []):
        text = str(value).strip()
        if text and text not in blockers:
            blockers.append(text)
    for key in ("dispatch_error", "failure_reason"):
        text = str(work_order.get(key, "")).strip()
        if text and text not in blockers:
            blockers.append(text)
    if isinstance(work_order.get("scope_violation"), dict):
        blockers.append("scope_violation")
    return blockers


def _default_blocking_question_for_reason(reason_code: str) -> str:
    mapping = {
        "waiting_conflict": (
            "Which overlapping lane should finish, be discarded, or be split before this task can proceed?"
        ),
        "clean_exit_no_deliverable": (
            "What concrete branch, commit, or PR should this lane produce before rerunning?"
        ),
        "merge_gate_failed": (
            "Which required verification or acceptance check must pass before approval?"
        ),
        "branch_snapshot_stale": (
            "Should this deliverable be rebased, regenerated, or otherwise refreshed on current main before review?"
        ),
        "missing_verification_plan": (
            "Which verification command or acceptance check should be added before rerunning?"
        ),
        "verification_target_missing": (
            "Which current verification target should replace the missing path before rerunning?"
        ),
        "scope_violation": (
            "Which files should stay in scope, or should this lane be split before rerunning?"
        ),
        "worker_exited_without_receipt": (
            "Should this lane be rerun, or recovered manually from the existing worktree?"
        ),
        "worker_no_progress_timeout": (
            "Should this stalled lane be rerun, split, or investigated in its current worktree?"
        ),
        "worker_timeout_with_salvage": (
            "Should the recovered timed-out deliverable be adopted, amended, or rerun before integration?"
        ),
        "worker_timeout_no_deliverable": (
            "Should this timed-out lane be rerun, split, or investigated before retrying?"
        ),
        "worker_crash_with_salvage": (
            "Should the recovered crashed deliverable be adopted, amended, or rerun before integration?"
        ),
        "worker_crash": (
            "Should this crashed lane be rerun, reassigned, or investigated before retrying?"
        ),
        "worker_type_blocked": (
            "Which worker type or capacity issue must be resolved before rerunning this lane?"
        ),
        "work_order_leasing_failed": (
            "What missing environment, resource, or policy input must be resolved first?"
        ),
        "stale_lease_reaped": ("Should this stale lane be requeued, recovered, or discarded?"),
        "expired_lease_reaped": ("Should this expired lane be requeued, recovered, or discarded?"),
    }
    return mapping.get(reason_code, "What human input is required before rerunning this lane?")


def _merge_gate_verification_target_missing(work_order: dict[str, Any]) -> bool:
    haystacks = [_optional_text(work_order.get("dispatch_error")).lower()]
    for entry in work_order.get("verification_results", []):
        if not isinstance(entry, dict):
            continue
        haystacks.extend(
            _optional_text(entry.get(field)).lower()
            for field in ("stdout", "stderr")
            if _optional_text(entry.get(field))
        )
    combined = "\n".join(text for text in haystacks if text)
    return "file or directory not found:" in combined


def _infer_missing_failure_reason_for_work_order(work_order: dict[str, Any]) -> str:
    status = _optional_text(work_order.get("status")).lower()
    if status == "waiting_conflict":
        return "waiting_conflict"

    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and bool(metadata.get("mainline_verification_passed")):
        return "branch_snapshot_stale"

    merge_gate = work_order.get("merge_gate")
    if isinstance(merge_gate, dict):
        missing = _optional_text(merge_gate.get("verification_missing_reason")).lower()
        if missing:
            return missing

    worker_outcome = _optional_text(work_order.get("worker_outcome")).lower()
    if worker_outcome == "branch_snapshot_stale":
        return "branch_snapshot_stale"
    if worker_outcome == "clean_exit_no_effect":
        return "clean_exit_no_deliverable"
    if worker_outcome == "merge_gate_failed":
        dispatch_error = _optional_text(work_order.get("dispatch_error")).lower()
        if "missing verification plan" in dispatch_error:
            return "missing_verification_plan"
        if _merge_gate_verification_target_missing(work_order):
            return "verification_target_missing"
        return "merge_gate_failed"
    if worker_outcome == "scope_violation":
        return "scope_violation"
    if worker_outcome == "timeout_with_salvage":
        return "worker_timeout_with_salvage"
    if worker_outcome == "timeout_no_progress":
        return "worker_no_progress_timeout"
    if worker_outcome == "crash_with_salvage":
        return "worker_crash_with_salvage"

    lowered = _optional_text(work_order.get("dispatch_error")).lower()
    if "branch snapshot stale" in lowered or "passes on main" in lowered:
        return "branch_snapshot_stale"
    if "missing verification plan" in lowered:
        return "missing_verification_plan"
    if _merge_gate_verification_target_missing(work_order):
        return "verification_target_missing"
    if "merge gate" in lowered:
        return "merge_gate_failed"
    if "scope" in lowered and "ownership" in lowered:
        return "scope_violation"
    if "without receipt or exit marker" in lowered:
        return "worker_exited_without_receipt"
    if "no-progress timeout" in lowered:
        return "worker_no_progress_timeout"
    if "recoverable deliverable" in lowered and "timed out" in lowered:
        return "worker_timeout_with_salvage"
    if "recoverable deliverable" in lowered and "non-zero" in lowered:
        return "worker_crash_with_salvage"
    if "timed out before producing a deliverable" in lowered:
        return "worker_timeout_no_deliverable"
    if "crashed before producing a deliverable" in lowered:
        return "worker_crash"
    if "no commits and no changed paths" in lowered or "no real deliverables" in lowered:
        return "clean_exit_no_deliverable"
    if "dispatch blocked" in lowered:
        return "worker_type_blocked"
    if "autopilot ensure failed" in lowered or "lease" in lowered or "worktree" in lowered:
        return "work_order_leasing_failed"

    return _optional_text(work_order.get("failure_reason")) or "needs_human"


def _backfill_work_order_blocker_metadata(work_order: dict[str, Any]) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {
        "waiting_conflict",
        "needs_human",
        "changes_requested",
        "dispatch_failed",
        "failed",
        "timed_out",
        "scope_violation",
    }:
        return False

    changed = False
    failure_reason = _optional_text(work_order.get("failure_reason"))
    inferred = _infer_missing_failure_reason_for_work_order(work_order)
    if inferred and (not failure_reason or failure_reason == "merge_gate_failed"):
        if failure_reason != inferred:
            work_order["failure_reason"] = inferred
            failure_reason = inferred
            changed = True
    elif (
        inferred
        and inferred != failure_reason
        and failure_reason
        in {
            "merge_gate_failed",
            "needs_human",
        }
    ):
        work_order["failure_reason"] = inferred
        failure_reason = inferred
        changed = True

    blocking_question = _optional_text(work_order.get("blocking_question"))
    if failure_reason and (
        not blocking_question
        or (
            inferred
            and inferred == failure_reason
            and blocking_question == _default_blocking_question_for_reason("merge_gate_failed")
        )
    ):
        work_order["blocking_question"] = _default_blocking_question_for_reason(failure_reason)
        blocking_question = _optional_text(work_order.get("blocking_question"))
        changed = True

    blocker = work_order.get("blocker")
    if (
        not isinstance(blocker, dict)
        or not _optional_text(blocker.get("reason"))
        or not _optional_text(blocker.get("question"))
    ) and (failure_reason or blocking_question):
        work_order["blocker"] = {
            "reason": failure_reason or "needs_human",
            "question": blocking_question
            or _default_blocking_question_for_reason(failure_reason or "needs_human"),
        }
        changed = True

    return changed


def _work_order_should_backfill_verification_plan(work_order: dict[str, Any]) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested", "completed"}:
        return False
    if _infer_missing_failure_reason_for_work_order(work_order) != "missing_verification_plan":
        return False
    return not [
        str(item).strip() for item in work_order.get("expected_tests", []) if str(item).strip()
    ]


def _work_order_should_rehabilitate_docs_only_missing_verification_plan(
    work_order: dict[str, Any],
) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested"}:
        return False
    if _infer_missing_failure_reason_for_work_order(work_order) != "missing_verification_plan":
        return False
    candidates = [
        str(path).strip()
        for path in work_order.get("changed_paths", []) or work_order.get("file_scope", [])
        if str(path).strip()
    ]
    if not candidates or not all(_is_docs_only_path(path) for path in candidates):
        return False
    return _work_order_has_concrete_deliverable(work_order)


def _work_order_is_validation_successor(work_order: dict[str, Any]) -> bool:
    expected_tests = [
        str(item).strip() for item in work_order.get("expected_tests", []) if str(item).strip()
    ]
    if expected_tests:
        return True
    text = " ".join(
        part
        for part in (
            _optional_text(work_order.get("title")),
            _optional_text(work_order.get("description")),
            " ".join(
                str(item).strip()
                for item in ((work_order.get("metadata") or {}).get("acceptance_criteria") or [])
                if str(item).strip()
            ),
        )
        if part
    ).lower()
    return any(
        token in text
        for token in (
            "run validation",
            "validation and fix failures",
            "acceptance tests",
            "pytest ",
            "fix any failures",
        )
    )


def _work_order_rehabilitation_identifier(work_order: dict[str, Any]) -> str:
    return (
        _optional_text(work_order.get("pipeline_task_id"))
        or _work_order_identifier(work_order)
        or _optional_text(work_order.get("task_key"))
    )


def _dependency_deferred_verification_ids_for_work_order(
    work_order: dict[str, Any],
    *,
    work_orders: list[dict[str, Any]],
) -> list[str]:
    if not isinstance(work_order, dict):
        return []
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested"}:
        return []
    if _infer_missing_failure_reason_for_work_order(work_order) != "missing_verification_plan":
        return []
    if not _work_order_has_concrete_deliverable(work_order):
        return []

    work_order_ids = {
        identifier
        for identifier in (
            _optional_text(work_order.get("pipeline_task_id")),
            _work_order_identifier(work_order),
            _optional_text(work_order.get("task_key")),
        )
        if identifier
    }
    if not work_order_ids:
        return []

    deferred_dependency_ids: list[str] = []
    for candidate in work_orders:
        if not isinstance(candidate, dict) or candidate is work_order:
            continue
        dependency_ids = set(_work_order_dependency_ids(candidate))
        if not dependency_ids or not dependency_ids.intersection(work_order_ids):
            continue
        if not _work_order_is_validation_successor(candidate):
            continue
        candidate_id = _work_order_rehabilitation_identifier(candidate)
        if candidate_id and candidate_id not in deferred_dependency_ids:
            deferred_dependency_ids.append(candidate_id)
    return deferred_dependency_ids


def _work_order_dependency_ids(work_order: dict[str, Any]) -> list[str]:
    return [str(item).strip() for item in work_order.get("dependency_ids", []) if str(item).strip()]


def _work_order_matches_dependency_id(work_order: dict[str, Any], dependency_id: str) -> bool:
    target = str(dependency_id).strip()
    if not target:
        return False
    return target in {
        _optional_text(work_order.get("pipeline_task_id")),
        _work_order_identifier(work_order),
        _optional_text(work_order.get("task_key")),
    }


def _resolve_dependency_work_order(
    work_orders: list[dict[str, Any]],
    dependency_id: str,
) -> dict[str, Any] | None:
    for candidate in work_orders:
        if not isinstance(candidate, dict):
            continue
        if _work_order_matches_dependency_id(candidate, dependency_id):
            return candidate
    return None


def _work_order_has_passed_verification_results(work_order: dict[str, Any]) -> bool:
    verification_results = [
        dict(entry)
        for entry in work_order.get("verification_results", [])
        if isinstance(entry, dict) and str(entry.get("command", "")).strip()
    ]
    if not verification_results:
        return False
    if not all(bool(entry.get("passed", False)) for entry in verification_results):
        return False
    merge_gate = _merge_gate_state_for_work_order(work_order)
    return bool(merge_gate.get("checks_passed")) and not _optional_text(
        merge_gate.get("verification_missing_reason")
    )


def _work_order_should_rehabilitate_dependency_validated_clean_exit_no_deliverable(
    work_order: dict[str, Any],
    *,
    work_orders: list[dict[str, Any]],
) -> bool:
    if _optional_text(work_order.get("status")).lower() != "completed":
        return False
    if _optional_text(work_order.get("review_status")).lower() != "changes_requested":
        return False
    if _optional_text(work_order.get("worker_outcome")).lower() != "clean_exit_no_effect":
        return False
    if any(str(path).strip() for path in work_order.get("changed_paths", []) or []):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    if not _work_order_has_passed_verification_results(work_order):
        return False
    dependency_ids = _work_order_dependency_ids(work_order)
    if not dependency_ids:
        return False
    for dependency_id in dependency_ids:
        dependency = _resolve_dependency_work_order(work_orders, dependency_id)
        if dependency is None or dependency is work_order:
            return False
        if _optional_text(dependency.get("status")).lower() not in {
            "completed",
            "changes_requested",
            "merged",
        }:
            return False
        if not _work_order_has_concrete_deliverable(dependency):
            return False
    return True


def _work_order_should_rehabilitate_deliverable_backed_clean_exit_no_deliverable(
    work_order: dict[str, Any],
    *,
    work_orders: list[dict[str, Any]] | None = None,
) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested", "completed"}:
        return False
    if _infer_missing_failure_reason_for_work_order(work_order) != "clean_exit_no_deliverable":
        return False
    if status == "completed":
        return _work_order_should_rehabilitate_dependency_validated_clean_exit_no_deliverable(
            work_order,
            work_orders=list(work_orders or []),
        )
    if not _optional_text(work_order.get("receipt_id")):
        return False
    return _work_order_has_concrete_deliverable(work_order)


def _work_order_should_reclassify_branch_snapshot_stale_review(
    work_order: dict[str, Any],
) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status != "needs_human":
        return False
    if _optional_text(work_order.get("failure_reason")).lower() != "branch_snapshot_stale":
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    if not _work_order_has_concrete_deliverable(work_order):
        return False
    metadata = work_order.get("metadata")
    if not isinstance(metadata, dict) or not bool(metadata.get("mainline_verification_passed")):
        return False
    return True


def _work_order_should_reclassify_deliverable_changes_requested(
    work_order: dict[str, Any],
) -> bool:
    if not isinstance(work_order, dict):
        return False
    if _optional_text(work_order.get("status")).lower() != "needs_human":
        return False
    if _optional_text(work_order.get("review_status")).lower() != "changes_requested":
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    if not _work_order_has_concrete_deliverable(work_order):
        return False
    return _optional_text(work_order.get("failure_reason")).lower() in {
        "verification_target_missing",
        "merge_gate_failed",
        "branch_snapshot_stale",
    }


def _work_order_should_replay_missing_verification(work_order: dict[str, Any]) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested"}:
        return False
    if _optional_text(work_order.get("failure_reason")).lower() != "merge_gate_failed":
        return False
    if not _work_order_has_concrete_deliverable(work_order):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    expected_tests = [
        str(item).strip() for item in work_order.get("expected_tests", []) if str(item).strip()
    ]
    if not expected_tests:
        return False
    verification_results = [
        dict(entry)
        for entry in work_order.get("verification_results", [])
        if isinstance(entry, dict) and str(entry.get("command", "")).strip()
    ]
    if verification_results:
        return False
    tests_run = [str(item).strip() for item in work_order.get("tests_run", []) if str(item).strip()]
    return not tests_run


def _verification_result_looks_environment_blocked(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    if bool(result.get("passed", False)):
        return False
    haystack = "\n".join(
        str(result.get(key, "")).lower()
        for key in ("stdout", "stderr")
        if str(result.get(key, "")).strip()
    )
    return any(
        marker in haystack
        for marker in (
            "no module named 'aragora_debate'",
            "no module named 'pydantic_settings'",
            "cannot find module 'next/jest'",
            "jest: command not found",
            "cannot find module 'react'",
            "react/jsx-runtime",
            "cannot execute binary file",
        )
    )


def _docs_only_verification_script_path(command: Any) -> str:
    normalized = _canonical_verification_command(command)
    if not normalized:
        return ""
    try:
        tokens = shlex.split(normalized)
    except ValueError:
        return ""
    if not tokens:
        return ""
    interpreter = Path(tokens[0]).name
    if len(tokens) < 2 or not interpreter.startswith("python"):
        return ""
    return tokens[1]


def _is_docs_only_verification_command(command: Any) -> bool:
    script = _docs_only_verification_script_path(command)
    return script in {
        "scripts/reconcile_status_docs.py",
        "scripts/check_capability_matrix_sync.py",
        "scripts/check_version_alignment.py",
        "scripts/generate_capability_matrix.py",
    }


def _docs_only_merge_gate_needs_capability_matrix_generation(
    work_order: dict[str, Any],
    commands: list[str],
) -> bool:
    if any(
        _docs_only_verification_script_path(command)
        in {
            "scripts/reconcile_status_docs.py",
            "scripts/check_capability_matrix_sync.py",
        }
        for command in commands
        if str(command).strip()
    ):
        return True
    haystacks = [str(work_order.get("dispatch_error", "")).lower()]
    for entry in work_order.get("verification_results", []):
        if not isinstance(entry, dict):
            continue
        haystacks.extend(
            str(entry.get(field, "")).lower() for field in ("stdout", "stderr") if entry.get(field)
        )
    combined = "\n".join(haystacks)
    return any(
        marker in combined
        for marker in (
            "capability matrix files are out of date",
            "capability_matrix.md",
            "generate_capability_matrix.py",
        )
    )


def _docs_only_replay_commands_for_work_order(work_order: dict[str, Any]) -> list[str] | None:
    commands: list[str] = []
    seen: set[str] = set()

    def _append(command: Any) -> None:
        text = str(command).strip()
        canonical = _canonical_verification_command(text)
        if not text or not canonical or canonical in seen:
            return
        seen.add(canonical)
        commands.append(text)

    for source in (
        work_order.get("expected_tests", []),
        work_order.get("tests_run", []),
    ):
        for entry in source:
            if _is_docs_only_verification_command(entry):
                _append(entry)
    for entry in work_order.get("verification_results", []):
        if not isinstance(entry, dict):
            continue
        command = entry.get("command", "")
        if _is_docs_only_verification_command(command):
            _append(command)

    if not commands:
        return None

    if _docs_only_merge_gate_needs_capability_matrix_generation(work_order, commands):
        generated: list[str] = []
        for command in _DOCS_ONLY_GENERATE_CAPABILITY_MATRIX_COMMANDS:
            canonical = _canonical_verification_command(command)
            if canonical in seen:
                continue
            seen.add(canonical)
            generated.append(command)
        commands = generated + commands

    return commands


def _work_order_should_replay_docs_only_merge_gate_failure(work_order: dict[str, Any]) -> bool:
    if not _work_order_should_reconcile_merge_gate_failure(work_order):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    candidates = [
        str(path).strip()
        for path in work_order.get("changed_paths", []) or work_order.get("file_scope", [])
        if str(path).strip()
    ]
    if not candidates or not all(_is_docs_only_path(path) for path in candidates):
        return False
    return _docs_only_replay_commands_for_work_order(work_order) is not None


def _missing_required_replay_commands_for_work_order(
    work_order: dict[str, Any],
) -> list[str] | None:
    if not _work_order_should_reconcile_merge_gate_failure(work_order):
        return None
    if not _optional_text(work_order.get("receipt_id")):
        return None

    merge_gate = _merge_gate_state_for_work_order(work_order)
    expected_checks = [
        str(command).strip()
        for command in merge_gate.get("expected_checks", [])
        if str(command).strip()
    ]
    verification_results = [
        dict(entry)
        for entry in work_order.get("verification_results", [])
        if isinstance(entry, dict) and str(entry.get("command", "")).strip()
    ]
    if not expected_checks:
        return None

    missing_checks = [
        command
        for command in expected_checks
        if not any(
            _verification_command_covers_expected(entry.get("command", ""), command)
            for entry in verification_results
        )
    ]
    failed_checks = [
        dict(entry)
        for entry in verification_results
        if any(
            _verification_command_covers_expected(entry.get("command", ""), command)
            for command in expected_checks
        )
        and not bool(entry.get("passed", False))
    ]
    if failed_checks or not missing_checks:
        return None
    return missing_checks


def _work_order_should_replay_missing_required_merge_gate_failure(
    work_order: dict[str, Any],
) -> bool:
    return _missing_required_replay_commands_for_work_order(work_order) is not None


def _narrow_pytest_replay_commands_for_work_order(work_order: dict[str, Any]) -> list[str] | None:
    commands: list[str] = []
    seen: set[str] = set()

    def _append(command: Any) -> None:
        text = str(command).strip()
        canonical = _canonical_verification_command(text)
        if not text or not canonical or canonical in seen:
            return
        if not _pytest_command_targets(text) or _is_overbroad_pytest_command(text):
            return
        seen.add(canonical)
        commands.append(text)

    for source in (
        work_order.get("expected_tests", []),
        work_order.get("tests_run", []),
    ):
        for entry in source:
            _append(entry)
    for entry in work_order.get("verification_results", []):
        if not isinstance(entry, dict):
            continue
        _append(entry.get("command", ""))

    return commands or None


def _work_order_should_replay_narrow_pytest_merge_gate_failure(work_order: dict[str, Any]) -> bool:
    if not _work_order_should_reconcile_merge_gate_failure(work_order):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    return _narrow_pytest_replay_commands_for_work_order(work_order) is not None


def _work_order_should_replay_environment_blocked_verification(work_order: dict[str, Any]) -> bool:
    if not _work_order_should_reconcile_merge_gate_failure(work_order):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    verification_results = [
        dict(entry)
        for entry in work_order.get("verification_results", [])
        if isinstance(entry, dict) and str(entry.get("command", "")).strip()
    ]
    return any(
        _verification_result_looks_environment_blocked(entry) for entry in verification_results
    )


def _targeted_replay_expected_tests_for_work_order(work_order: dict[str, Any]) -> list[str]:
    targeted: list[str] = []
    seen: set[str] = set()

    def _append(command: str) -> None:
        display = str(command).strip()
        normalized = _canonical_verification_command(display)
        if (
            not display
            or not normalized
            or normalized in seen
            or _is_overbroad_pytest_command(normalized)
        ):
            return
        seen.add(normalized)
        targeted.append(display)

    success_criteria = work_order.get("success_criteria")
    if isinstance(success_criteria, dict):
        for entry in _extract_tests_value(success_criteria.get("tests")):
            _append(entry)

    metadata = work_order.get("metadata")
    if isinstance(metadata, dict):
        for entry in metadata.get("acceptance_criteria", []):
            text = str(entry).strip()
            if text.startswith("python -m pytest") or text.startswith("pytest"):
                _append(text)
            for match in _TEST_FILE_PATTERN.findall(text):
                _append(f"python -m pytest {match} -q")

    for entry in work_order.get("tests_run", []):
        _append(str(entry))

    for entry in work_order.get("verification_results", []):
        if isinstance(entry, dict):
            _append(str(entry.get("command", "")))

    for path in work_order.get("file_scope", []):
        normalized = str(path).strip()
        if normalized.startswith("tests/") and normalized.endswith(".py"):
            _append(f"python -m pytest {normalized} -q")

    for path in work_order.get("changed_paths", []):
        normalized = str(path).strip()
        if normalized.startswith("tests/") and normalized.endswith(".py"):
            _append(f"python -m pytest {normalized} -q")

    return targeted


def _work_order_should_replay_targeted_merge_gate_failure(work_order: dict[str, Any]) -> bool:
    if not _work_order_should_reconcile_merge_gate_failure(work_order):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    current_expected = [
        _canonical_verification_command(command)
        for command in work_order.get("expected_tests", [])
        if str(command).strip()
    ]
    if not any(_is_overbroad_pytest_command(command) for command in current_expected):
        return False
    targeted = _targeted_replay_expected_tests_for_work_order(work_order)
    if not targeted:
        return False
    return set(targeted) != {command for command in current_expected if command}


def _mainline_verification_commands_for_work_order(work_order: dict[str, Any]) -> list[str]:
    targeted = _targeted_replay_expected_tests_for_work_order(work_order)
    if targeted:
        return list(targeted)

    commands: list[str] = []
    seen: set[str] = set()
    for entry in work_order.get("expected_tests", []):
        display = str(entry).strip()
        normalized = _canonical_verification_command(display)
        if not display or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        commands.append(display)
    return commands


def _mainline_candidate_repo_paths_for_work_order(work_order: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()

    def _append(raw: Any) -> None:
        text = str(raw or "").strip()
        if not text:
            return
        target = text.split("::", 1)[0].strip()
        normalized = _normalize_claim(target)
        if not normalized or any(token in normalized for token in ("*", "?", "[", "]", "{", "}")):
            return
        if normalized in seen:
            return
        seen.add(normalized)
        paths.append(normalized)

    for entry in work_order.get("file_scope", []) or []:
        _append(entry)
    for entry in work_order.get("changed_paths", []) or []:
        _append(entry)
    for command in _mainline_verification_commands_for_work_order(work_order):
        for target in _pytest_command_targets(command):
            _append(target)
    return paths


def _mainline_missing_repo_paths_for_work_order(
    work_order: dict[str, Any],
    *,
    repo_root: Path,
) -> list[str]:
    root = repo_root.resolve()
    missing: list[str] = []
    for candidate in _mainline_candidate_repo_paths_for_work_order(work_order):
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if not resolved.exists():
            missing.append(candidate)
    return missing


def _work_order_should_reclassify_branch_stale_verification_target_missing(
    work_order: dict[str, Any],
    *,
    repo_root: Path,
) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested"}:
        return False
    if _optional_text(work_order.get("failure_reason")).lower() != "verification_target_missing":
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    if not _work_order_has_concrete_deliverable(work_order):
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and (
        bool(metadata.get("mainline_verification_passed"))
        or bool(metadata.get("mainline_verification_target_missing"))
    ):
        return False
    candidate_paths = _mainline_candidate_repo_paths_for_work_order(work_order)
    if not candidate_paths:
        return False
    missing_paths = _mainline_missing_repo_paths_for_work_order(work_order, repo_root=repo_root)
    return bool(missing_paths) and len(missing_paths) == len(candidate_paths)


def _work_order_should_reclassify_branch_stale_merge_gate_failure(
    work_order: dict[str, Any],
) -> bool:
    if not _work_order_should_reconcile_merge_gate_failure(work_order):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and bool(metadata.get("mainline_verification_passed")):
        return False
    return bool(_mainline_verification_commands_for_work_order(work_order))


def _work_order_should_reconcile_merge_gate_failure(work_order: dict[str, Any]) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested"}:
        return False
    if _optional_text(work_order.get("failure_reason")).lower() != "merge_gate_failed":
        return False
    if not _work_order_has_concrete_deliverable(work_order):
        return False
    verification_results = [
        dict(entry)
        for entry in work_order.get("verification_results", [])
        if isinstance(entry, dict) and str(entry.get("command", "")).strip()
    ]
    return bool(verification_results)


def _merge_gate_replay_matches_task_keys(
    run_id: str,
    work_order: dict[str, Any],
    task_keys: set[str],
) -> bool:
    if not task_keys:
        return True
    metadata = work_order.get("metadata")
    metadata_task_key = ""
    if isinstance(metadata, dict):
        metadata_task_key = _optional_text(metadata.get("task_key"))
    explicit = _optional_text(work_order.get("task_key"))
    derived = ""
    work_order_id = _work_order_identifier(work_order)
    if run_id and work_order_id:
        derived = f"{run_id}:{work_order_id}"
    return metadata_task_key in task_keys or explicit in task_keys or derived in task_keys


def _work_order_reap_failure_reason(
    work_order: dict[str, Any],
    *,
    lease_status: str | None = None,
) -> str:
    for blocker in _developer_task_blockers(work_order):
        normalized = blocker.strip().lower()
        if normalized in _REAPED_NO_RECEIPT_BLOCKERS:
            return normalized
    status = _optional_text(work_order.get("status")).lower()
    normalized_lease_status = _optional_text(lease_status).lower()
    if status in {"leased", "dispatched", "active", "integrating"} and normalized_lease_status in {
        "released",
        "expired",
    }:
        return (
            "expired_lease_reaped"
            if normalized_lease_status == LeaseStatus.EXPIRED.value
            else "stale_lease_reaped"
        )
    return ""


def _work_order_should_archive_reaped_no_receipt(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    cutoff: datetime,
    lease_status: str | None,
) -> bool:
    status = _optional_text(work_order.get("status")).lower()
    if status not in _OPEN_DEVELOPER_TASK_STATUSES:
        return False
    if _optional_text(lease_status).lower() == LeaseStatus.ACTIVE.value:
        return False
    metadata = work_order.get("metadata")
    if (
        isinstance(metadata, dict)
        and _optional_text(metadata.get("archived_due_to")) == "reaped_no_receipt"
    ):
        return False
    if _optional_text(work_order.get("receipt_id")) or _work_order_has_concrete_deliverable(
        work_order
    ):
        return False
    if not _work_order_reap_failure_reason(work_order, lease_status=lease_status):
        return False
    updated_at = _parse_dt(_developer_task_updated_at(work_order, run))
    return updated_at <= cutoff


def _work_order_has_scope_violation(work_order: dict[str, Any]) -> bool:
    if _optional_text(work_order.get("status")).lower() == "scope_violation":
        return True
    if isinstance(work_order.get("scope_violation"), dict):
        return True
    lowered_blockers = {
        blocker.strip().lower()
        for blocker in _developer_task_blockers(work_order)
        if blocker.strip()
    }
    return "scope_violation" in lowered_blockers


def _work_order_should_archive_scope_violation_no_deliverable(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    cutoff: datetime,
    lease_status: str | None,
) -> bool:
    status = _optional_text(work_order.get("status")).lower()
    if status not in (_OPEN_DEVELOPER_TASK_STATUSES | {"scope_violation"}):
        return False
    if _optional_text(lease_status).lower() == LeaseStatus.ACTIVE.value:
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    if _optional_text(work_order.get("receipt_id")) or _work_order_has_concrete_deliverable(
        work_order
    ):
        return False
    if not _work_order_has_scope_violation(work_order):
        return False
    updated_at = _parse_dt(_developer_task_updated_at(work_order, run))
    return updated_at <= cutoff


def _work_order_failed_no_deliverable_reason(work_order: dict[str, Any]) -> str:
    for blocker in _developer_task_blockers(work_order):
        text = blocker.strip()
        if text:
            return text
    return _optional_text(work_order.get("failure_reason")) or "failed_no_deliverable"


def _terminal_dependency_failure_for_work_order(
    work_order: dict[str, Any],
    *,
    work_orders: list[dict[str, Any]],
) -> dict[str, str] | None:
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"queued", "waiting_conflict"}:
        return None
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return None
    if _optional_text(work_order.get("receipt_id")) or _work_order_has_concrete_deliverable(
        work_order
    ):
        return None
    dependency_ids = [
        _optional_text(dep) for dep in work_order.get("dependency_ids", []) if _optional_text(dep)
    ]
    if not dependency_ids:
        return None

    dependency_lookup: dict[str, dict[str, Any]] = {}
    for candidate in work_orders:
        if not isinstance(candidate, dict):
            continue
        for key in ("pipeline_task_id", "work_order_id", "task_key"):
            candidate_id = _optional_text(candidate.get(key))
            if candidate_id:
                dependency_lookup[candidate_id] = candidate

    for dependency_id in dependency_ids:
        dependency = dependency_lookup.get(dependency_id)
        if not isinstance(dependency, dict):
            continue
        if _optional_text(dependency.get("receipt_id")) or _work_order_has_concrete_deliverable(
            dependency
        ):
            continue
        dependency_status = _optional_text(dependency.get("status")).lower()
        dependency_metadata = dependency.get("metadata")
        dependency_archived_due_to = (
            _optional_text(dependency_metadata.get("archived_due_to"))
            if isinstance(dependency_metadata, dict)
            else ""
        )
        dependency_reason = _optional_text(
            dependency.get("failure_reason"),
            dependency.get("dispatch_error"),
            dependency_metadata.get("archive_reason")
            if isinstance(dependency_metadata, dict)
            else "",
            dependency_archived_due_to,
            dependency.get("worker_outcome"),
            dependency_status,
        )
        if dependency_status in {"discarded", "failed", "timed_out", "scope_violation"}:
            return {
                "dependency_id": dependency_id,
                "dependency_status": dependency_status,
                "dependency_reason": dependency_reason or dependency_status,
            }
        if dependency_status == "dispatch_failed":
            return {
                "dependency_id": dependency_id,
                "dependency_status": dependency_status,
                "dependency_reason": dependency_reason or dependency_status,
            }
        if dependency_status == "needs_human":
            non_terminal_reasons = {"stale_lease_reaped", "expired_lease_reaped", "needs_human"}
            if dependency_reason.lower() in non_terminal_reasons and not dependency_archived_due_to:
                continue
            return {
                "dependency_id": dependency_id,
                "dependency_status": dependency_status,
                "dependency_reason": dependency_reason or dependency_status,
            }
    return None


def _work_order_clean_exit_no_deliverable_reason(work_order: dict[str, Any]) -> str:
    status = _optional_text(work_order.get("status")).lower()
    metadata = work_order.get("metadata")
    candidate_fields = [
        work_order.get("worker_outcome"),
        work_order.get("last_run_outcome"),
        work_order.get("failure_reason"),
    ]
    if isinstance(metadata, dict):
        candidate_fields.extend(
            [
                metadata.get("outcome"),
                metadata.get("terminal_outcome"),
                metadata.get("receipt_outcome"),
            ]
        )
    for candidate in candidate_fields:
        if _optional_text(candidate).lower() == "clean_exit_no_deliverable":
            return "clean_exit_no_deliverable"
    for blocker in _developer_task_blockers(work_order):
        normalized = blocker.strip().lower()
        if normalized in {
            "clean_exit_no_deliverable",
            "run ended without a concrete deliverable.",
        }:
            return blocker.strip()
    if (
        status == "completed"
        and _work_order_receipt_outcome(work_order) == "clean_exit_no_deliverable"
        and not _developer_task_blockers(work_order)
        and not _optional_text(work_order.get("failure_reason"))
    ):
        return "clean_exit_no_deliverable"
    return ""


def _work_order_should_archive_failed_no_deliverable(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    cutoff: datetime,
    lease_status: str | None,
) -> bool:
    status = _optional_text(work_order.get("status")).lower()
    timeout_like_needs_human = False
    empty_launch_crash_needs_human = False
    if status == "needs_human":
        worker_outcome = _optional_text(work_order.get("worker_outcome")).lower()
        failure_reason = _optional_text(work_order.get("failure_reason")).lower()
        blockers = {blocker.strip().lower() for blocker in _developer_task_blockers(work_order)}
        timeout_like_needs_human = (
            worker_outcome
            in {
                "timeout_no_progress",
                "timeout_with_salvage",
            }
            or any("timeout" in blocker for blocker in blockers)
            or "timeout" in failure_reason
        )
        changed_paths = [
            _optional_text(path)
            for path in work_order.get("changed_paths", [])
            if _optional_text(path)
        ]
        empty_launch_crash_needs_human = (
            failure_reason == "worker_exited_without_receipt"
            and worker_outcome in {"", "crash"}
            and not changed_paths
            and not _optional_text(work_order.get("stdout_tail"))
            and not _optional_text(work_order.get("stderr_tail"))
            and not _optional_text(work_order.get("diff"))
            and int(work_order.get("diff_lines", 0) or 0) == 0
        )
    if (
        status not in {"failed", "dispatch_failed", "timed_out"}
        and not timeout_like_needs_human
        and not empty_launch_crash_needs_human
    ):
        return False
    if _optional_text(lease_status).lower() == LeaseStatus.ACTIVE.value:
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    if _optional_text(work_order.get("receipt_id")) or _work_order_has_concrete_deliverable(
        work_order
    ):
        return False
    updated_at = _parse_dt(_developer_task_updated_at(work_order, run))
    return updated_at <= cutoff


def _work_order_should_archive_clean_exit_no_deliverable(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    cutoff: datetime,
    lease_status: str | None,
) -> bool:
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"completed", "needs_human"}:
        return False
    if _optional_text(lease_status).lower() == LeaseStatus.ACTIVE.value:
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    if _optional_text(work_order.get("receipt_id")) or _work_order_has_concrete_deliverable(
        work_order
    ):
        return False
    if not _work_order_clean_exit_no_deliverable_reason(work_order):
        return False
    updated_at = _parse_dt(_work_order_clean_exit_no_deliverable_staleness_anchor(work_order, run))
    return updated_at <= cutoff


def _work_order_should_archive_work_order_leasing_failed(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    cutoff: datetime,
    lease_status: str | None,
) -> bool:
    status = _optional_text(work_order.get("status")).lower()
    if status != "needs_human":
        return False
    if _optional_text(lease_status).lower() == LeaseStatus.ACTIVE.value:
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    if _optional_text(work_order.get("receipt_id")) or _work_order_has_concrete_deliverable(
        work_order
    ):
        return False
    if _optional_text(work_order.get("failure_reason")).lower() != "work_order_leasing_failed":
        return False
    updated_at = _parse_dt(_work_order_leasing_failed_staleness_anchor(work_order, run))
    return updated_at <= cutoff


def _work_order_should_archive_worker_type_blocked(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    cutoff: datetime,
    lease_status: str | None,
) -> bool:
    status = _optional_text(work_order.get("status")).lower()
    if status != "needs_human":
        return False
    if _optional_text(lease_status).lower() == LeaseStatus.ACTIVE.value:
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    if _optional_text(work_order.get("receipt_id")) or _work_order_has_concrete_deliverable(
        work_order
    ):
        return False
    if _optional_text(work_order.get("failure_reason")).lower() != "worker_type_blocked":
        return False
    updated_at = _parse_dt(_work_order_leasing_failed_staleness_anchor(work_order, run))
    return updated_at <= cutoff


def _work_order_leasing_failed_staleness_anchor(
    work_order: dict[str, Any],
    run: dict[str, Any],
) -> str:
    for value in (
        *(
            work_order.get(key)
            for key in (
                "last_observed_at",
                "last_progress_at",
                "completed_at",
                "dispatched_at",
                "leased_at",
                "started_at",
            )
        ),
        run.get("created_at"),
        run.get("updated_at"),
        _utcnow().isoformat(),
    ):
        text = str(value or "").strip()
        if text and text.lower() != "none":
            return text
    return _utcnow().isoformat()


def _work_order_clean_exit_no_deliverable_staleness_anchor(
    work_order: dict[str, Any],
    run: dict[str, Any],
) -> str:
    for value in (
        *(
            work_order.get(key)
            for key in (
                "last_observed_at",
                "last_progress_at",
                "completed_at",
                "dispatched_at",
                "leased_at",
                "started_at",
            )
        ),
        run.get("created_at"),
        run.get("updated_at"),
        _utcnow().isoformat(),
    ):
        text = str(value or "").strip()
        if text and text.lower() != "none":
            return text
    return _utcnow().isoformat()


def _work_order_should_archive_superseded_clean_exit_no_deliverable(
    work_order: dict[str, Any],
) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status != "needs_human":
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    if _optional_text(work_order.get("receipt_id")) or _work_order_has_concrete_deliverable(
        work_order
    ):
        return False
    if _optional_text(work_order.get("failure_reason")).lower() != "clean_exit_no_deliverable":
        return False
    return _optional_text(work_order.get("worker_outcome")).lower() == "clean_exit_no_effect"


_HELPER_CLEAN_EXIT_TITLE_PREFIXES = (
    "read existing ",
    "inspect ",
    "understand ",
    "run tests and validate",
    "validate implementation",
    "review existing ",
    "analyze existing ",
)


def _looks_like_helper_clean_exit_no_deliverable(work_order: dict[str, Any]) -> bool:
    title = " ".join(_optional_text(work_order.get("title")).lower().split())
    return any(title.startswith(prefix) for prefix in _HELPER_CLEAN_EXIT_TITLE_PREFIXES)


def _work_order_should_archive_superseded_stale_lease_reaped(
    work_order: dict[str, Any],
) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status != "needs_human":
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    if _optional_text(work_order.get("receipt_id")) or _work_order_has_concrete_deliverable(
        work_order
    ):
        return False
    if _optional_text(work_order.get("failure_reason")).lower() != "stale_lease_reaped":
        return False
    return _looks_like_helper_clean_exit_no_deliverable(work_order)


def _work_order_should_archive_superseded_waiting_conflict(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    cutoff: datetime,
    lease_status: str | None,
) -> bool:
    if _optional_text(work_order.get("status")).lower() != "waiting_conflict":
        return False
    if _optional_text(lease_status).lower() == LeaseStatus.ACTIVE.value:
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    if _optional_text(work_order.get("receipt_id")) or _work_order_has_concrete_deliverable(
        work_order
    ):
        return False
    if not _work_order_scope_patterns(work_order):
        return False
    updated_at = _parse_dt(_waiting_conflict_staleness_anchor(work_order, run))
    return updated_at <= cutoff


def _work_order_should_rehabilitate_narrowed_waiting_conflict(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    cutoff: datetime,
    lease_status: str | None,
) -> bool:
    if not _work_order_should_archive_superseded_waiting_conflict(
        work_order,
        run=run,
        cutoff=cutoff,
        lease_status=lease_status,
    ):
        return False
    return bool(
        _narrow_waiting_conflict_scope_from_explicit_paths(
            work_order,
            run=run,
            repo_root=None,
        )
    )


def _waiting_conflict_staleness_anchor(work_order: dict[str, Any], run: dict[str, Any]) -> str:
    for value in (
        *(
            work_order.get(key)
            for key in (
                "last_observed_at",
                "last_progress_at",
                "completed_at",
                "dispatched_at",
                "leased_at",
                "started_at",
            )
        ),
        run.get("created_at"),
        run.get("updated_at"),
        _utcnow().isoformat(),
    ):
        text = str(value or "").strip()
        if text and text.lower() != "none":
            return text
    return _utcnow().isoformat()


def _duplicate_branch_deliverable_priority(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> tuple[int, int, int, str]:
    commit_shas = [
        str(item).strip() for item in work_order.get("commit_shas", []) if str(item).strip()
    ]
    return (
        1 if _optional_text(work_order.get("receipt_id")) else 0,
        len(commit_shas),
        1 if _optional_text(work_order.get("head_sha")) else 0,
        _developer_task_updated_at(work_order, run),
    )


def _duplicate_waiting_conflict_priority(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> tuple[int, str, str]:
    return (
        -len(_work_order_scope_patterns(work_order)),
        _waiting_conflict_staleness_anchor(work_order, run),
        _optional_text(work_order.get("work_order_id"), work_order.get("task_id")),
    )


def _containing_waiting_conflict_priority(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> tuple[int, int, str]:
    patterns = _work_order_scope_patterns(work_order)
    return (
        len(patterns),
        -sum(len(pattern) for pattern in patterns),
        _optional_text(work_order.get("work_order_id"), work_order.get("task_id")),
    )


def _is_concrete_repo_path_hint(path: str, *, repo_root: Path | None) -> bool:
    clean = _normalize_claim(path)
    if not clean or any(token in clean for token in ("*", "?", "[", "]", "{", "}")):
        return False
    name = clean.rsplit("/", 1)[-1]
    if repo_root is not None:
        candidate = (repo_root / clean).resolve()
        try:
            candidate.relative_to(repo_root.resolve())
        except ValueError:
            return False
        if candidate.is_file():
            return True
    return "." in name


def _waiting_conflict_inference_text(work_order: dict[str, Any], run: dict[str, Any]) -> str:
    spec = run.get("spec")
    metadata = work_order.get("metadata")
    spec_acceptance = spec.get("acceptance_criteria") if isinstance(spec, dict) else []
    spec_constraints = spec.get("constraints") if isinstance(spec, dict) else []
    metadata_acceptance = metadata.get("acceptance_criteria") if isinstance(metadata, dict) else []
    metadata_constraints = metadata.get("constraints") if isinstance(metadata, dict) else []
    parts = [
        run.get("goal"),
        spec.get("raw_goal") if isinstance(spec, dict) else None,
        spec.get("refined_goal") if isinstance(spec, dict) else None,
        work_order.get("title"),
        work_order.get("description"),
        metadata.get("description") if isinstance(metadata, dict) else None,
    ]
    if isinstance(spec_acceptance, list):
        parts.extend(spec_acceptance)
    if isinstance(spec_constraints, list):
        parts.extend(spec_constraints)
    if isinstance(metadata_acceptance, list):
        parts.extend(metadata_acceptance)
    if isinstance(metadata_constraints, list):
        parts.extend(metadata_constraints)
    return " ".join(str(part).strip() for part in parts if str(part or "").strip())


def _explicit_scope_paths_for_waiting_conflict(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    repo_root: Path | None,
) -> list[str]:
    from aragora.swarm.spec import SwarmSpec

    original_scope = [
        _canonical_scope_pattern(str(path))
        for path in work_order.get("file_scope", []) or []
        if _canonical_scope_pattern(str(path))
    ]
    if not original_scope:
        return []
    explicit_paths: list[str] = []
    for path in SwarmSpec.infer_file_scope_hints(_waiting_conflict_inference_text(work_order, run)):
        clean = _normalize_claim(path)
        if not _is_concrete_repo_path_hint(clean, repo_root=repo_root):
            continue
        if not any(_path_matches_glob(clean, scope) for scope in original_scope):
            continue
        if clean not in explicit_paths:
            explicit_paths.append(clean)
    return explicit_paths


def _docs_only_scope_hints_for_waiting_conflict(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> list[str]:
    metadata = work_order.get("metadata") or {}
    constraints = metadata.get("constraints") if isinstance(metadata, dict) else []
    if not isinstance(constraints, list) or not any(
        "documentation only" in str(item).strip().lower() for item in constraints
    ):
        spec = run.get("spec")
        spec_constraints = spec.get("constraints") if isinstance(spec, dict) else []
        if not isinstance(spec_constraints, list) or not any(
            "documentation only" in str(item).strip().lower() for item in spec_constraints
        ):
            return []

    original_scope = [
        _canonical_scope_pattern(str(path))
        for path in work_order.get("file_scope", []) or []
        if _canonical_scope_pattern(str(path))
    ]
    if not original_scope:
        return []

    def _scope_supports_docs_only_hint(path: str) -> bool:
        if any(
            scope == path or path.startswith(f"{scope}/") or scope.startswith(f"{path}/")
            for scope in original_scope
        ):
            return True
        if not is_docs_safe_top_level_file(path):
            return False
        return any(canonical_docs_container_scope(scope) == "docs" for scope in original_scope)

    doc_hints: list[str] = []
    for path in infer_docs_safe_hints(_waiting_conflict_inference_text(work_order, run)):
        clean = _canonical_scope_pattern(path)
        if _scope_supports_docs_only_hint(clean):
            doc_hints.append(clean)
    if any(
        is_docs_safe_path(hint) and canonical_docs_container_scope(hint) is None
        for hint in doc_hints
    ):
        doc_hints = [hint for hint in doc_hints if canonical_docs_container_scope(hint) is None]
    collapsed = _collapse_scope_patterns(doc_hints)
    if collapsed:
        return collapsed
    return list(
        dict.fromkeys(
            scope
            for scope in (canonical_docs_container_scope(path) for path in original_scope)
            if scope is not None
        )
    )


def _narrow_waiting_conflict_scope_from_explicit_paths(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    repo_root: Path | None,
) -> list[str]:
    original_scope = [
        _canonical_scope_pattern(str(path))
        for path in work_order.get("file_scope", []) or []
        if _canonical_scope_pattern(str(path))
    ]
    if not original_scope:
        return []
    explicit_paths = _explicit_scope_paths_for_waiting_conflict(
        work_order,
        run=run,
        repo_root=repo_root,
    )
    if explicit_paths:
        narrowed_scope: list[str] = []
        replaced = False
        for scope in original_scope:
            contains_explicit = any(_path_matches_glob(path, scope) for path in explicit_paths)
            if (
                contains_explicit
                and scope not in explicit_paths
                and not _is_concrete_repo_path_hint(
                    scope,
                    repo_root=repo_root,
                )
            ):
                replaced = True
                continue
            narrowed_scope.append(scope)
        if replaced:
            return _collapse_scope_patterns(narrowed_scope + explicit_paths)

    docs_only_scope = _docs_only_scope_hints_for_waiting_conflict(work_order, run=run)
    if docs_only_scope and tuple(docs_only_scope) != tuple(original_scope):
        return docs_only_scope
    return []


def _waiting_conflict_sibling_can_be_ignored(
    candidate: dict[str, Any],
    sibling: dict[str, Any],
) -> bool:
    if _optional_text(sibling.get("status")).lower() != "waiting_conflict":
        return False
    metadata = sibling.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    if _optional_text(sibling.get("receipt_id")) or _work_order_has_concrete_deliverable(sibling):
        return False
    return _work_order_scope_contains(sibling, candidate) and not _work_order_scope_contains(
        candidate,
        sibling,
    )


def _blocking_waiting_conflict_siblings(
    candidate: dict[str, Any],
    *,
    run: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    run_id = _optional_text(run.get("run_id"))
    work_order_id = _work_order_identifier(candidate)
    conflicts: list[dict[str, Any]] = []
    for sibling_record in records:
        sibling_run_id = _optional_text(sibling_record.get("run_id"))
        for sibling in sibling_record.get("work_orders", []):
            if not isinstance(sibling, dict):
                continue
            if sibling is candidate and sibling_run_id == run_id:
                continue
            if (
                work_order_id
                and sibling_run_id == run_id
                and _work_order_identifier(sibling) == work_order_id
            ):
                continue
            status = _optional_text(sibling.get("status")).lower()
            if status in {"discarded", "superseded", "merged"}:
                continue
            metadata = sibling.get("metadata")
            if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
                continue
            if not _work_orders_overlap_by_scope(candidate, sibling):
                continue
            if _waiting_conflict_sibling_can_be_ignored(candidate, sibling):
                continue
            conflicts.append(
                {
                    "source": "work_order",
                    "run_id": sibling_run_id or None,
                    "work_order_id": _work_order_identifier(sibling) or None,
                    "status": status or None,
                    "title": _optional_text(sibling.get("title")) or None,
                    "allowed_globs": _work_order_scope_patterns(sibling),
                }
            )
    return conflicts


def _work_order_receipt_outcome(work_order: dict[str, Any]) -> str:
    if _optional_text(work_order.get("adopted_pr")):
        return "pr_adopted"
    if _work_order_has_concrete_deliverable(work_order):
        return "deliverable_created"
    return "clean_exit_no_deliverable"


def _work_order_should_backfill_file_scope_from_changed_paths(work_order: dict[str, Any]) -> bool:
    status = _optional_text(work_order.get("status")).lower()
    if status in {"discarded", "superseded", "merged", "scope_violation"}:
        return False
    if any(str(path).strip() for path in work_order.get("file_scope", []) or []):
        return False
    if not any(str(path).strip() for path in work_order.get("changed_paths", []) or []):
        return False
    if isinstance(work_order.get("scope_violation"), dict):
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    return True


def _work_order_should_backfill_receipt(work_order: dict[str, Any]) -> bool:
    status = _optional_text(work_order.get("status")).lower()
    if status in {"queued", "leased", "dispatched", "active", "integrating", "discarded"}:
        return False
    if _optional_text(work_order.get("receipt_id")):
        return False
    if not _optional_text(work_order.get("lease_id")):
        return False
    return _work_order_receipt_outcome(work_order) in {"deliverable_created", "pr_adopted"}


def _extract_pr_number(pr_reference: str) -> int | None:
    text = str(pr_reference or "").strip().rstrip("/")
    if not text:
        return None
    tail = text.rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _developer_task_priority(work_order: dict[str, Any]) -> int:
    explicit = work_order.get("priority")
    if isinstance(explicit, int):
        return max(0, min(100, explicit))
    if isinstance(explicit, str):
        normalized = explicit.strip().lower()
        if normalized.isdigit():
            return max(0, min(100, int(normalized)))
        named = {
            "critical": 95,
            "high": 80,
            "medium": 60,
            "normal": 50,
            "low": 35,
        }
        if normalized in named:
            return named[normalized]
    risk_level = str(work_order.get("risk_level", "")).strip().lower()
    risk_priority = {
        "critical": 90,
        "high": 75,
        "review": 60,
        "medium": 55,
        "low": 45,
    }
    return risk_priority.get(risk_level, 50)


def _developer_task_work_status(status: str) -> WorkStatus:
    normalized = str(status or "").strip().lower()
    if normalized == "queued":
        return WorkStatus.READY
    if normalized == "leased":
        return WorkStatus.CLAIMED
    if normalized in {"dispatched", "active"}:
        return WorkStatus.IN_PROGRESS
    if normalized in {"waiting_conflict", "dispatch_failed", "needs_human", "changes_requested"}:
        return WorkStatus.BLOCKED
    if normalized in {"timed_out", "failed"}:
        return WorkStatus.FAILED
    if normalized in {"merged", "discarded", "salvage", "completed", "integrating"}:
        return WorkStatus.COMPLETED
    return WorkStatus.PENDING


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
    complete.add_argument("--base-sha", default=None)
    complete.add_argument("--head-sha", default=None)
    complete.add_argument("--commit", action="append", default=[])
    complete.add_argument("--changed-path", action="append", default=[])
    complete.add_argument("--test", action="append", default=[])
    complete.add_argument("--validation", action="append", default=[])
    complete.add_argument("--assumption", action="append", default=[])
    complete.add_argument("--blocker", action="append", default=[])
    complete.add_argument("--outcome", default="completed")
    complete.add_argument("--risk", action="append", default=[])
    complete.add_argument("--pr-url", default=None)
    complete.add_argument("--pr-number", type=int, default=None)
    complete.add_argument("--confidence", type=float, default=0.0)
    complete.add_argument("--json", action="store_true")

    heartbeat = sub.add_parser("heartbeat", help="Refresh a lease TTL")
    heartbeat.add_argument("--lease-id", required=True)
    heartbeat.add_argument("--ttl-hours", type=float, default=None)
    heartbeat.add_argument("--json", action="store_true")

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

    sync_queue = sub.add_parser(
        "sync-queue",
        help="Project pending integration/salvage items into the global work queue",
    )
    sync_queue.add_argument("--json", action="store_true")

    tasks = sub.add_parser("tasks", help="List canonical developer tasks")
    tasks.add_argument("--open-only", action="store_true")
    tasks.add_argument("--json", action="store_true")

    sync_tasks = sub.add_parser(
        "sync-tasks",
        help="Project open developer tasks into the global work queue",
    )
    sync_tasks.add_argument("--json", action="store_true")

    reap = sub.add_parser("reap", help="Expire stale leases and release mirrored fleet claims")
    reap.add_argument("--json", action="store_true")

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
                f"open_salvage_candidates={counts['open_salvage_candidates']} "
                f"open_developer_tasks={counts['open_developer_tasks']}"
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
            base_sha=args.base_sha,
            head_sha=args.head_sha,
            commit_shas=args.commit,
            changed_paths=args.changed_path,
            tests_run=args.test,
            validations_run=args.validation,
            assumptions=args.assumption,
            blockers=args.blocker,
            outcome=args.outcome,
            risks=args.risk,
            pr_url=args.pr_url,
            pr_number=args.pr_number,
            confidence=args.confidence,
        )
        if args.json:
            print(json.dumps({"ok": True, "receipt": receipt.to_dict()}, indent=2))  # noqa: T201
        else:
            print(receipt.receipt_id)  # noqa: T201
        return 0

    if args.command == "heartbeat":
        lease = store.heartbeat_lease(
            lease_id=args.lease_id,
            ttl_hours=args.ttl_hours,
        )
        if args.json:
            print(json.dumps({"ok": True, "lease": lease.to_dict()}, indent=2))  # noqa: T201
        else:
            print(lease.lease_id)  # noqa: T201
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

    if args.command == "sync-queue":
        payload = {
            "ok": True,
            "counts": asyncio.run(store.sync_pending_work_queue()),
        }
        if args.json:
            print(json.dumps(payload, indent=2))  # noqa: T201
        else:
            print(json.dumps(payload["counts"], indent=2))  # noqa: T201
        return 0

    if args.command == "tasks":
        payload = {
            "ok": True,
            "count": 0,
            "tasks": [
                item.to_dict() for item in store.list_developer_tasks(open_only=args.open_only)
            ],
        }
        payload["count"] = len(payload["tasks"])
        if args.json:
            print(json.dumps(payload, indent=2))  # noqa: T201
        else:
            print(payload["count"])  # noqa: T201
        return 0

    if args.command == "sync-tasks":
        payload = {
            "ok": True,
            "counts": asyncio.run(store.sync_developer_task_queue()),
        }
        if args.json:
            print(json.dumps(payload, indent=2))  # noqa: T201
        else:
            print(json.dumps(payload["counts"], indent=2))  # noqa: T201
        return 0

    if args.command == "reap":
        expired = store.reap_expired_leases()
        stale = store.reap_stale_leases()
        all_reaped = expired + stale
        payload = {
            "ok": True,
            "count": len(all_reaped),
            "expired": len(expired),
            "stale": len(stale),
            "leases": [lease.to_dict() for lease in all_reaped],
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
