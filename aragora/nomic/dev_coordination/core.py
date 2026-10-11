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
import shlex  # noqa: F401 -- kept on core's attribute surface (the package __getattr__ falls through to core)
import sqlite3
import subprocess
import uuid
from datetime import datetime, timedelta  # noqa: F401 -- datetime kept on core's attribute surface
from pathlib import Path
from typing import Any

from aragora.docs_only import (  # noqa: F401 -- kept on core's attribute surface
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
    _normalize_claim,  # noqa: F401 -- kept on core's attribute surface
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
from aragora.nomic.dev_coordination.work_order_archive import (  # noqa: F401
    _HELPER_CLEAN_EXIT_TITLE_PREFIXES,
    _OPEN_DEVELOPER_TASK_STATUSES,
    _REAPED_NO_RECEIPT_BLOCKERS,
    _developer_task_blockers,
    _looks_like_helper_clean_exit_no_deliverable,
    _terminal_dependency_failure_for_work_order,
    _work_order_clean_exit_no_deliverable_reason,
    _work_order_clean_exit_no_deliverable_staleness_anchor,
    _work_order_failed_no_deliverable_reason,
    _work_order_has_scope_violation,
    _work_order_leasing_failed_staleness_anchor,
    _work_order_reap_failure_reason,
    _work_order_receipt_outcome,
    _work_order_should_archive_clean_exit_no_deliverable,
    _work_order_should_archive_failed_no_deliverable,
    _work_order_should_archive_reaped_no_receipt,
    _work_order_should_archive_scope_violation_no_deliverable,
    _work_order_should_archive_superseded_clean_exit_no_deliverable,
    _work_order_should_archive_superseded_stale_lease_reaped,
    _work_order_should_archive_work_order_leasing_failed,
    _work_order_should_archive_worker_type_blocked,
)
from aragora.nomic.dev_coordination.merge_gate_replay import (  # noqa: F401
    _DOCS_ONLY_GENERATE_CAPABILITY_MATRIX_COMMANDS,
    _docs_only_merge_gate_needs_capability_matrix_generation,
    _docs_only_replay_commands_for_work_order,
    _docs_only_verification_script_path,
    _is_docs_only_path,
    _is_docs_only_verification_command,
    _mainline_candidate_repo_paths_for_work_order,
    _mainline_missing_repo_paths_for_work_order,
    _mainline_verification_commands_for_work_order,
    _merge_gate_state_for_work_order,
    _missing_required_replay_commands_for_work_order,
    _narrow_pytest_replay_commands_for_work_order,
    _targeted_replay_expected_tests_for_work_order,
    _verification_result_looks_environment_blocked,
    _work_order_should_reclassify_branch_stale_merge_gate_failure,
    _work_order_should_reclassify_branch_stale_verification_target_missing,
    _work_order_should_reconcile_merge_gate_failure,
    _work_order_should_replay_docs_only_merge_gate_failure,
    _work_order_should_replay_environment_blocked_verification,
    _work_order_should_replay_missing_required_merge_gate_failure,
    _work_order_should_replay_missing_verification,
    _work_order_should_replay_narrow_pytest_merge_gate_failure,
    _work_order_should_replay_targeted_merge_gate_failure,
)
from aragora.nomic.dev_coordination.work_order_waiting_conflict import (  # noqa: F401
    _blocking_waiting_conflict_siblings,
    _containing_waiting_conflict_priority,
    _docs_only_scope_hints_for_waiting_conflict,
    _duplicate_branch_deliverable_priority,
    _duplicate_waiting_conflict_priority,
    _explicit_scope_paths_for_waiting_conflict,
    _is_concrete_repo_path_hint,
    _narrow_waiting_conflict_scope_from_explicit_paths,
    _waiting_conflict_inference_text,
    _waiting_conflict_sibling_can_be_ignored,
    _waiting_conflict_staleness_anchor,
    _work_order_identifier,
    _work_order_should_archive_superseded_waiting_conflict,
    _work_order_should_rehabilitate_narrowed_waiting_conflict,
)
from aragora.nomic.dev_coordination.work_order_rehabilitation import (  # noqa: F401
    _backfill_work_order_blocker_metadata,
    _default_blocking_question_for_reason,
    _dependency_deferred_verification_ids_for_work_order,
    _infer_missing_failure_reason_for_work_order,
    _merge_gate_replay_matches_task_keys,
    _merge_gate_verification_target_missing,
    _resolve_dependency_work_order,
    _work_order_dependency_ids,
    _work_order_has_passed_verification_results,
    _work_order_is_validation_successor,
    _work_order_matches_dependency_id,
    _work_order_rehabilitation_identifier,
    _work_order_should_backfill_file_scope_from_changed_paths,
    _work_order_should_backfill_receipt,
    _work_order_should_backfill_verification_plan,
    _work_order_should_reclassify_branch_snapshot_stale_review,
    _work_order_should_reclassify_deliverable_changes_requested,
    _work_order_should_rehabilitate_deliverable_backed_clean_exit_no_deliverable,
    _work_order_should_rehabilitate_dependency_validated_clean_exit_no_deliverable,
    _work_order_should_rehabilitate_docs_only_missing_verification_plan,
)
from aragora.nomic.dev_coordination.work_order_maintenance import (  # noqa: F401
    _CLEAN_EXIT_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS,
    _DUPLICATE_BRANCH_DELIVERABLE_ARCHIVE_GRACE_HOURS,
    _FAILED_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS,
    _OPEN_SALVAGE_STATUSES,
    _QUEUEABLE_DEVELOPER_TASK_STATUSES,
    _REAPED_NO_RECEIPT_ARCHIVE_GRACE_HOURS,
    _SUPERSEDED_WAITING_CONFLICT_ARCHIVE_GRACE_HOURS,
    _WORKER_TYPE_BLOCKED_ARCHIVE_GRACE_HOURS,
    _WORK_ORDER_LEASING_FAILED_ARCHIVE_GRACE_HOURS,
    WorkOrderMaintenanceMixin,
)
from aragora.nomic.event_bus import EventBus
from aragora.nomic.global_work_queue import (  # noqa: F401 -- kept on core's attribute surface
    GlobalWorkQueue,
    WorkItem,
    WorkStatus,
)
from aragora.worktree.fleet import FleetCoordinationStore

_ACTIVE_LEASE_STATUSES = {"active"}
_PENDING_INTEGRATION_DECISIONS = {"pending_review"}
_OPEN_SUPERVISOR_RUN_STATUSES = {"planned", "active", "needs_human"}
_SQLITE_BUSY_TIMEOUT_MS = 60_000
_DEV_COORDINATION_DB_ENV = "ARAGORA_DEV_COORDINATION_DB"
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
_REPAIR_JOURNAL_MAX_ENTRIES = 20


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


class DevCoordinationStore(WorkOrderMaintenanceMixin):
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
