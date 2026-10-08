"""Receipt, integration, and completion-tracking helpers for development coordination."""

from __future__ import annotations

import sqlite3
import subprocess
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .dev_coordination import _get_lane_telemetry

if TYPE_CHECKING:
    from .dev_coordination import core as _dev
else:
    # At runtime the package facade is the consumer surface (PEP 562 fall-through
    # to ``core``); ``core`` itself delegates back here with function-local
    # imports, so a direct module edge would make the two mutually dependent.
    from . import dev_coordination as _dev
from .dev_coordination.models import (
    CompletionReceipt,
    FileScopeViolationError,
    IntegrationDecision,
    IntegrationDecisionType,
    LeaseStatus,
    WorkLease,
)

_CLEAN_EXIT_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS = _dev._CLEAN_EXIT_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS
_DUPLICATE_BRANCH_DELIVERABLE_ARCHIVE_GRACE_HOURS = (
    _dev._DUPLICATE_BRANCH_DELIVERABLE_ARCHIVE_GRACE_HOURS
)
_FAILED_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS = _dev._FAILED_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS
_PENDING_INTEGRATION_DECISIONS = _dev._PENDING_INTEGRATION_DECISIONS
_REAPED_NO_RECEIPT_ARCHIVE_GRACE_HOURS = _dev._REAPED_NO_RECEIPT_ARCHIVE_GRACE_HOURS
_SUPERSEDED_WAITING_CONFLICT_ARCHIVE_GRACE_HOURS = (
    _dev._SUPERSEDED_WAITING_CONFLICT_ARCHIVE_GRACE_HOURS
)
_WORKER_TYPE_BLOCKED_ARCHIVE_GRACE_HOURS = _dev._WORKER_TYPE_BLOCKED_ARCHIVE_GRACE_HOURS
_WORK_ORDER_LEASING_FAILED_ARCHIVE_GRACE_HOURS = _dev._WORK_ORDER_LEASING_FAILED_ARCHIVE_GRACE_HOURS
_backfill_work_order_blocker_metadata = _dev._backfill_work_order_blocker_metadata
_blocking_waiting_conflict_siblings = _dev._blocking_waiting_conflict_siblings
_canonical_goal_key = _dev._canonical_goal_key
_canonical_verification_command = _dev._canonical_verification_command
_canonical_work_order_scope_key = _dev._canonical_work_order_scope_key
_containing_waiting_conflict_priority = _dev._containing_waiting_conflict_priority
_default_blocking_question_for_reason = _dev._default_blocking_question_for_reason
_dependency_deferred_verification_ids_for_work_order = (
    _dev._dependency_deferred_verification_ids_for_work_order
)
_developer_task_blockers = _dev._developer_task_blockers
_docs_only_replay_commands_for_work_order = _dev._docs_only_replay_commands_for_work_order
_duplicate_branch_deliverable_priority = _dev._duplicate_branch_deliverable_priority
_duplicate_waiting_conflict_group_key = _dev._duplicate_waiting_conflict_group_key
_duplicate_waiting_conflict_priority = _dev._duplicate_waiting_conflict_priority
_duplicate_work_order_leasing_failed_priority = _dev._duplicate_work_order_leasing_failed_priority
_extract_pr_number = _dev._extract_pr_number
_find_work_order = _dev._find_work_order
_has_wildcard = _dev._has_wildcard
_inferred_expected_tests_for_work_order = _dev._inferred_expected_tests_for_work_order
_json_dump = _dev._json_dump
_json_loads = _dev._json_loads
_live_overlap_sibling_priority = _dev._live_overlap_sibling_priority
_looks_like_helper_clean_exit_no_deliverable = _dev._looks_like_helper_clean_exit_no_deliverable
_mainline_missing_repo_paths_for_work_order = _dev._mainline_missing_repo_paths_for_work_order
_mainline_verification_commands_for_work_order = _dev._mainline_verification_commands_for_work_order
_merge_gate_replay_matches_task_keys = _dev._merge_gate_replay_matches_task_keys
_merge_gate_state_for_work_order = _dev._merge_gate_state_for_work_order
_missing_required_replay_commands_for_work_order = (
    _dev._missing_required_replay_commands_for_work_order
)
_narrow_pytest_replay_commands_for_work_order = _dev._narrow_pytest_replay_commands_for_work_order
_narrow_waiting_conflict_scope_from_explicit_paths = (
    _dev._narrow_waiting_conflict_scope_from_explicit_paths
)
_normalize_claim = _dev._normalize_claim
_normalize_completion_outcome = _dev._normalize_completion_outcome
_optional_text = _dev._optional_text
_parse_dt = _dev._parse_dt
_path_matches_glob = _dev._path_matches_glob
_superseded_waiting_conflict_group_key = _dev._superseded_waiting_conflict_group_key
_terminal_dependency_failure_for_work_order = _dev._terminal_dependency_failure_for_work_order
_targeted_replay_expected_tests_for_work_order = _dev._targeted_replay_expected_tests_for_work_order
_utcnow = _dev._utcnow
_verification_timeout_for_command = _dev._verification_timeout_for_command
_work_order_clean_exit_no_deliverable_reason = _dev._work_order_clean_exit_no_deliverable_reason
_work_order_failed_no_deliverable_reason = _dev._work_order_failed_no_deliverable_reason
_work_order_has_concrete_deliverable = _dev._work_order_has_concrete_deliverable
_work_order_identifier = _dev._work_order_identifier
_work_order_is_broad_explicit_pytest_umbrella = _dev._work_order_is_broad_explicit_pytest_umbrella
_work_order_is_duplicate_waiting_conflict_candidate = (
    _dev._work_order_is_duplicate_waiting_conflict_candidate
)
_work_order_is_duplicate_work_order_leasing_failed_candidate = (
    _dev._work_order_is_duplicate_work_order_leasing_failed_candidate
)
_work_order_is_live_overlap_sibling = _dev._work_order_is_live_overlap_sibling
_work_order_is_specific_pytest_child = _dev._work_order_is_specific_pytest_child
_work_order_reap_failure_reason = _dev._work_order_reap_failure_reason
_work_order_receipt_outcome = _dev._work_order_receipt_outcome
_work_order_scope_contains = _dev._work_order_scope_contains
_work_order_scope_patterns = _dev._work_order_scope_patterns
_work_order_should_archive_clean_exit_no_deliverable = (
    _dev._work_order_should_archive_clean_exit_no_deliverable
)
_work_order_should_archive_duplicate_branch_deliverable = (
    _dev._work_order_should_archive_duplicate_branch_deliverable
)
_work_order_should_archive_failed_no_deliverable = (
    _dev._work_order_should_archive_failed_no_deliverable
)
_work_order_should_archive_reaped_no_receipt = _dev._work_order_should_archive_reaped_no_receipt
_work_order_should_archive_scope_violation_no_deliverable = (
    _dev._work_order_should_archive_scope_violation_no_deliverable
)
_work_order_should_archive_superseded_clean_exit_no_deliverable = (
    _dev._work_order_should_archive_superseded_clean_exit_no_deliverable
)
_work_order_should_archive_superseded_stale_lease_reaped = (
    _dev._work_order_should_archive_superseded_stale_lease_reaped
)
_work_order_should_archive_superseded_waiting_conflict = (
    _dev._work_order_should_archive_superseded_waiting_conflict
)
_work_order_should_archive_work_order_leasing_failed = (
    _dev._work_order_should_archive_work_order_leasing_failed
)
_work_order_should_archive_worker_type_blocked = _dev._work_order_should_archive_worker_type_blocked
_work_order_should_backfill_file_scope_from_changed_paths = (
    _dev._work_order_should_backfill_file_scope_from_changed_paths
)
_work_order_should_backfill_receipt = _dev._work_order_should_backfill_receipt
_work_order_should_backfill_verification_plan = _dev._work_order_should_backfill_verification_plan
_work_order_should_reclassify_branch_snapshot_stale_review = (
    _dev._work_order_should_reclassify_branch_snapshot_stale_review
)
_work_order_should_reclassify_branch_stale_merge_gate_failure = (
    _dev._work_order_should_reclassify_branch_stale_merge_gate_failure
)
_work_order_should_reclassify_branch_stale_verification_target_missing = (
    _dev._work_order_should_reclassify_branch_stale_verification_target_missing
)
_work_order_should_reclassify_deliverable_changes_requested = (
    _dev._work_order_should_reclassify_deliverable_changes_requested
)
_work_order_should_reconcile_merge_gate_failure = (
    _dev._work_order_should_reconcile_merge_gate_failure
)
_work_order_should_rehabilitate_deliverable_backed_clean_exit_no_deliverable = (
    _dev._work_order_should_rehabilitate_deliverable_backed_clean_exit_no_deliverable
)
_work_order_should_rehabilitate_docs_only_missing_verification_plan = (
    _dev._work_order_should_rehabilitate_docs_only_missing_verification_plan
)
_work_order_should_rehabilitate_narrowed_waiting_conflict = (
    _dev._work_order_should_rehabilitate_narrowed_waiting_conflict
)
_work_order_should_replay_docs_only_merge_gate_failure = (
    _dev._work_order_should_replay_docs_only_merge_gate_failure
)
_work_order_should_replay_environment_blocked_verification = (
    _dev._work_order_should_replay_environment_blocked_verification
)
_work_order_should_replay_missing_required_merge_gate_failure = (
    _dev._work_order_should_replay_missing_required_merge_gate_failure
)
_work_order_should_replay_missing_verification = _dev._work_order_should_replay_missing_verification
_work_order_should_replay_narrow_pytest_merge_gate_failure = (
    _dev._work_order_should_replay_narrow_pytest_merge_gate_failure
)
_work_order_should_replay_targeted_merge_gate_failure = (
    _dev._work_order_should_replay_targeted_merge_gate_failure
)
_work_orders_overlap_by_scope = _dev._work_orders_overlap_by_scope


def backfill_missing_blocker_metadata(self) -> int:
    """Fill structured blocker fields for historical lanes that only stored free-text errors."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        updated = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                normalized = _backfill_work_order_blocker_metadata(item)
                if not normalized:
                    continue
                changed = True
                updated += 1
            if not changed:
                continue
            record["updated_at"] = now
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return updated


def backfill_missing_verification_plans(self) -> int:
    """Infer verification commands for historical merge-gate rows missing them."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        updated = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not _work_order_should_backfill_verification_plan(item):
                    continue
                inferred_tests = _inferred_expected_tests_for_work_order(item)
                if not inferred_tests:
                    continue
                item["expected_tests"] = list(inferred_tests)
                success_criteria = dict(item.get("success_criteria") or {})
                if "tests" not in success_criteria:
                    success_criteria["tests"] = (
                        inferred_tests[0] if len(inferred_tests) == 1 else list(inferred_tests)
                    )
                item["success_criteria"] = success_criteria
                merge_gate = _merge_gate_state_for_work_order(item)
                item["merge_gate"] = merge_gate
                item["verification_missing_reason"] = merge_gate.get("verification_missing_reason")
                blocked_reasons = [
                    str(reason).strip()
                    for reason in merge_gate.get("blocked_reasons", [])
                    if str(reason).strip()
                ]
                if blocked_reasons:
                    item["dispatch_error"] = blocked_reasons[0]
                    item["blockers"] = blocked_reasons
                if not merge_gate.get("verification_missing_reason"):
                    item["failure_reason"] = "merge_gate_failed"
                    item["worker_outcome"] = "merge_gate_failed"
                    item["blocking_question"] = _default_blocking_question_for_reason(
                        "merge_gate_failed"
                    )
                    item["blocker"] = {
                        "reason": "merge_gate_failed",
                        "question": item["blocking_question"],
                    }
                changed = True
                updated += 1
            if not changed:
                continue
            record["updated_at"] = now
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return updated


def rehabilitate_docs_only_missing_verification_plan_work_orders(self) -> int:
    """Restore docs-only deliverables that were blocked only by absent test commands."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        updated = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not _work_order_should_rehabilitate_docs_only_missing_verification_plan(item):
                    continue
                item["merge_gate"] = _merge_gate_state_for_work_order(item)
                item["verification_missing_reason"] = None
                item["status"] = "completed"
                item["review_status"] = "pending_heterogeneous_review"
                item["worker_outcome"] = "completed"
                for key in (
                    "failure_reason",
                    "blocking_question",
                    "blocker",
                    "dispatch_error",
                ):
                    item.pop(key, None)
                item["blockers"] = []
                changed = True
                updated += 1
            if not changed:
                continue
            record["updated_at"] = now
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return updated


def rehabilitate_dependency_deferred_missing_verification_plan_work_orders(self) -> int:
    """Restore historical implementation lanes whose verification is deferred downstream."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        updated = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                deferred_dependency_ids = _dependency_deferred_verification_ids_for_work_order(
                    item,
                    work_orders=record["work_orders"],
                )
                if not deferred_dependency_ids:
                    continue
                metadata = dict(item.get("metadata") or {})
                metadata["deferred_verification_to_dependency_ids"] = deferred_dependency_ids
                metadata["dependency_deferred_verification_rehabilitated_at"] = now
                item["metadata"] = metadata
                item["merge_gate"] = _merge_gate_state_for_work_order(item)
                item["verification_missing_reason"] = item["merge_gate"].get(
                    "verification_missing_reason"
                )
                item["status"] = "completed"
                item["review_status"] = "pending_heterogeneous_review"
                item["worker_outcome"] = "completed"
                for key in (
                    "failure_reason",
                    "blocking_question",
                    "blocker",
                    "dispatch_error",
                ):
                    item.pop(key, None)
                item["blockers"] = []
                changed = True
                updated += 1
            if not changed:
                continue
            record["updated_at"] = now
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return updated


def rehabilitate_deliverable_backed_clean_exit_no_deliverable_work_orders(self) -> int:
    """Restore contradictory clean-exit lanes that already have receipt-backed deliverables."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        updated = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not _work_order_should_rehabilitate_deliverable_backed_clean_exit_no_deliverable(
                    item,
                    work_orders=record["work_orders"],
                ):
                    continue
                item["merge_gate"] = _merge_gate_state_for_work_order(item)
                item["status"] = "completed"
                item["review_status"] = "pending_heterogeneous_review"
                item["worker_outcome"] = "completed"
                for key in (
                    "failure_reason",
                    "blocking_question",
                    "blocker",
                    "dispatch_error",
                ):
                    item.pop(key, None)
                item["blockers"] = []
                changed = True
                updated += 1
            if not changed:
                continue
            record["updated_at"] = now
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return updated


def reclassify_branch_snapshot_stale_review_work_orders(self) -> int:
    """Move deliverable-backed branch-stale lanes into the review bucket."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        updated = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not _work_order_should_reclassify_branch_snapshot_stale_review(item):
                    continue
                item["status"] = "changes_requested"
                item["review_status"] = "changes_requested"
                changed = True
                updated += 1
            if not changed:
                continue
            record["updated_at"] = now
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return updated


def reclassify_deliverable_changes_requested_work_orders(self) -> int:
    """Align status with review bucket for deliverable-backed lanes already marked changes_requested."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        updated = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not _work_order_should_reclassify_deliverable_changes_requested(item):
                    continue
                item["status"] = "changes_requested"
                changed = True
                updated += 1
            if not changed:
                continue
            record["updated_at"] = now
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return updated


def archive_reaped_no_receipt_work_orders(
    self,
    *,
    grace_period_hours: float = _REAPED_NO_RECEIPT_ARCHIVE_GRACE_HOURS,
) -> int:
    """Archive stale reaped work orders that never produced a receipt."""
    now = _utcnow()
    grace_period = timedelta(hours=max(0.0, float(grace_period_hours)))
    cutoff = now - grace_period
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        lease_status_by_id = {
            str(row["lease_id"]).strip(): str(row["status"]).strip()
            for row in conn.execute("SELECT lease_id, status FROM leases").fetchall()
            if str(row["lease_id"]).strip()
        }
        archived = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                lease_status = lease_status_by_id.get(_optional_text(item.get("lease_id")))
                if not _work_order_should_archive_reaped_no_receipt(
                    item,
                    run=record,
                    cutoff=cutoff,
                    lease_status=lease_status,
                ):
                    continue
                metadata = dict(item.get("metadata") or {})
                archive_reason = (
                    _work_order_reap_failure_reason(item, lease_status=lease_status)
                    or "stale_lease_reaped"
                )
                metadata.update(
                    {
                        "archived_due_to": "reaped_no_receipt",
                        "archived_at": now.isoformat(),
                        "archive_reason": archive_reason,
                        "previous_status": _optional_text(item.get("status")) or "needs_human",
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                if not _optional_text(item.get("failure_reason")):
                    item["failure_reason"] = archive_reason
                changed = True
                archived += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now.isoformat()
            self._persist_supervisor_run(conn, record)

        conn.commit()
    finally:
        conn.close()
    return archived


def archive_scope_violation_no_deliverable_work_orders(
    self,
    *,
    grace_period_hours: float = _REAPED_NO_RECEIPT_ARCHIVE_GRACE_HOURS,
) -> int:
    """Archive old scope-violation work orders that never produced a deliverable."""
    now = _utcnow()
    grace_period = timedelta(hours=max(0.0, float(grace_period_hours)))
    cutoff = now - grace_period
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        lease_status_by_id = {
            str(row["lease_id"]).strip(): str(row["status"]).strip()
            for row in conn.execute("SELECT lease_id, status FROM leases").fetchall()
            if str(row["lease_id"]).strip()
        }
        archived = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                lease_status = lease_status_by_id.get(_optional_text(item.get("lease_id")))
                if not _work_order_should_archive_scope_violation_no_deliverable(
                    item,
                    run=record,
                    cutoff=cutoff,
                    lease_status=lease_status,
                ):
                    continue
                metadata = dict(item.get("metadata") or {})
                metadata.update(
                    {
                        "archived_due_to": "scope_violation_no_deliverable",
                        "archived_at": now.isoformat(),
                        "archive_reason": "scope_violation",
                        "previous_status": _optional_text(item.get("status")) or "blocked",
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                if not _optional_text(item.get("failure_reason")):
                    item["failure_reason"] = "scope_violation"
                changed = True
                archived += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now.isoformat()
            self._persist_supervisor_run(conn, record)

        conn.commit()
    finally:
        conn.close()
    return archived


def archive_failed_no_deliverable_work_orders(
    self,
    *,
    grace_period_hours: float = _FAILED_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS,
) -> int:
    """Archive old failed lanes that never produced a receipt or deliverable."""
    now = _utcnow()
    grace_period = timedelta(hours=max(0.0, float(grace_period_hours)))
    cutoff = now - grace_period
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        lease_status_by_id = {
            str(row["lease_id"]).strip(): str(row["status"]).strip()
            for row in conn.execute("SELECT lease_id, status FROM leases").fetchall()
            if str(row["lease_id"]).strip()
        }
        archived = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                lease_status = lease_status_by_id.get(_optional_text(item.get("lease_id")))
                if not _work_order_should_archive_failed_no_deliverable(
                    item,
                    run=record,
                    cutoff=cutoff,
                    lease_status=lease_status,
                ):
                    continue
                metadata = dict(item.get("metadata") or {})
                archive_reason = _work_order_failed_no_deliverable_reason(item)
                metadata.update(
                    {
                        "archived_due_to": "failed_no_deliverable",
                        "archived_at": now.isoformat(),
                        "archive_reason": archive_reason,
                        "previous_status": _optional_text(item.get("status")) or "failed",
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                if not _optional_text(item.get("failure_reason")):
                    item["failure_reason"] = archive_reason
                changed = True
                archived += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now.isoformat()
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return archived


def archive_terminal_dependency_failure_work_orders(self) -> int:
    """Archive queued lanes that are blocked by a terminal failed dependency."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        archived = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                dependency_failure = _terminal_dependency_failure_for_work_order(
                    item,
                    work_orders=record["work_orders"],
                )
                if dependency_failure is None:
                    continue
                dependency_id = dependency_failure["dependency_id"]
                dependency_status = dependency_failure["dependency_status"]
                dependency_reason = dependency_failure["dependency_reason"]
                metadata = dict(item.get("metadata") or {})
                metadata.update(
                    {
                        "archived_due_to": "terminal_dependency_failure",
                        "archived_at": now,
                        "archive_reason": f"terminal_dependency_failure:{dependency_id}",
                        "previous_status": _optional_text(item.get("status")) or "queued",
                        "blocking_dependency_id": dependency_id,
                        "blocking_dependency_status": dependency_status,
                        "blocking_dependency_reason": dependency_reason,
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                item["failure_reason"] = "terminal_dependency_failure"
                item["blocking_question"] = (
                    f"Dependency {dependency_id} ended in {dependency_status}; "
                    "should that dependency be rerun or replaced before retrying this lane?"
                )
                item["blocker"] = {
                    "reason": "terminal_dependency_failure",
                    "dependency_id": dependency_id,
                    "dependency_status": dependency_status,
                    "dependency_reason": dependency_reason,
                }
                item["blockers"] = [
                    (
                        f"Dependency {dependency_id} ended in {dependency_status} "
                        f"without a deliverable: {dependency_reason}"
                    )
                ]
                changed = True
                archived += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return archived


def archive_clean_exit_no_deliverable_work_orders(
    self,
    *,
    grace_period_hours: float = _CLEAN_EXIT_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS,
) -> int:
    """Archive old clean-exit lanes that never produced a receipt or deliverable."""
    now = _utcnow()
    grace_period = timedelta(hours=max(0.0, float(grace_period_hours)))
    cutoff = now - grace_period
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        lease_status_by_id = {
            str(row["lease_id"]).strip(): str(row["status"]).strip()
            for row in conn.execute("SELECT lease_id, status FROM leases").fetchall()
            if str(row["lease_id"]).strip()
        }
        archived = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                lease_status = lease_status_by_id.get(_optional_text(item.get("lease_id")))
                if not _work_order_should_archive_clean_exit_no_deliverable(
                    item,
                    run=record,
                    cutoff=cutoff,
                    lease_status=lease_status,
                ):
                    continue
                metadata = dict(item.get("metadata") or {})
                archive_reason = _work_order_clean_exit_no_deliverable_reason(item)
                metadata.update(
                    {
                        "archived_due_to": "clean_exit_no_deliverable",
                        "archived_at": now.isoformat(),
                        "archive_reason": archive_reason,
                        "previous_status": _optional_text(item.get("status")) or "completed",
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                if not _optional_text(item.get("failure_reason")):
                    item["failure_reason"] = archive_reason
                changed = True
                archived += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now.isoformat()
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return archived


def archive_work_order_leasing_failed_work_orders(
    self,
    *,
    grace_period_hours: float = _WORK_ORDER_LEASING_FAILED_ARCHIVE_GRACE_HOURS,
) -> int:
    """Archive stale leasing failures that never produced a receipt or deliverable."""
    now = _utcnow()
    grace_period = timedelta(hours=max(0.0, float(grace_period_hours)))
    cutoff = now - grace_period
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        lease_status_by_id = {
            str(row["lease_id"]).strip(): str(row["status"]).strip()
            for row in conn.execute("SELECT lease_id, status FROM leases").fetchall()
            if str(row["lease_id"]).strip()
        }
        archived = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                lease_status = lease_status_by_id.get(_optional_text(item.get("lease_id")))
                if not _work_order_should_archive_work_order_leasing_failed(
                    item,
                    run=record,
                    cutoff=cutoff,
                    lease_status=lease_status,
                ):
                    continue
                metadata = dict(item.get("metadata") or {})
                metadata.update(
                    {
                        "archived_due_to": "work_order_leasing_failed",
                        "archived_at": now.isoformat(),
                        "archive_reason": "work_order_leasing_failed",
                        "previous_status": _optional_text(item.get("status")) or "needs_human",
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                if not _optional_text(item.get("failure_reason")):
                    item["failure_reason"] = "work_order_leasing_failed"
                changed = True
                archived += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now.isoformat()
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return archived


def archive_worker_type_blocked_work_orders(
    self,
    *,
    grace_period_hours: float = _WORKER_TYPE_BLOCKED_ARCHIVE_GRACE_HOURS,
) -> int:
    """Archive stale capacity/worker-type blocked lanes with no artifact."""
    now = _utcnow()
    grace_period = timedelta(hours=max(0.0, float(grace_period_hours)))
    cutoff = now - grace_period
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        lease_status_by_id = {
            str(row["lease_id"]).strip(): str(row["status"]).strip()
            for row in conn.execute("SELECT lease_id, status FROM leases").fetchall()
            if str(row["lease_id"]).strip()
        }
        archived = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                lease_status = lease_status_by_id.get(_optional_text(item.get("lease_id")))
                if not _work_order_should_archive_worker_type_blocked(
                    item,
                    run=record,
                    cutoff=cutoff,
                    lease_status=lease_status,
                ):
                    continue
                metadata = dict(item.get("metadata") or {})
                metadata.update(
                    {
                        "archived_due_to": "worker_type_blocked",
                        "archived_at": now.isoformat(),
                        "archive_reason": "worker_type_blocked",
                        "previous_status": _optional_text(item.get("status")) or "needs_human",
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                if not _optional_text(item.get("failure_reason")):
                    item["failure_reason"] = "worker_type_blocked"
                changed = True
                archived += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now.isoformat()
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return archived


def archive_superseded_clean_exit_no_deliverable_work_orders(self) -> int:
    """Archive no-op helper lanes when same-run deliverable siblings already cover the scope."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        archived = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            deliverable_items = [
                item
                for item in record["work_orders"]
                if isinstance(item, dict) and _work_order_has_concrete_deliverable(item)
            ]
            changed = False
            for item in record["work_orders"]:
                if not _work_order_should_archive_superseded_clean_exit_no_deliverable(item):
                    continue
                overlapping_deliverables = [
                    sibling
                    for sibling in deliverable_items
                    if sibling is not item and _work_orders_overlap_by_scope(item, sibling)
                ]
                if not overlapping_deliverables:
                    if not _looks_like_helper_clean_exit_no_deliverable(item):
                        continue
                    overlapping_siblings = [
                        sibling
                        for sibling in record["work_orders"]
                        if isinstance(sibling, dict)
                        and sibling is not item
                        and _work_orders_overlap_by_scope(item, sibling)
                        and _work_order_is_live_overlap_sibling(sibling)
                    ]
                    if not overlapping_siblings:
                        continue
                    keeper = max(
                        overlapping_siblings,
                        key=lambda sibling: _live_overlap_sibling_priority(sibling, run=record),
                    )
                    archive_reason = "helper_clean_exit_no_deliverable"
                else:
                    keeper = max(
                        overlapping_deliverables,
                        key=lambda sibling: _duplicate_branch_deliverable_priority(
                            sibling, run=record
                        ),
                    )
                    archive_reason = "superseded_clean_exit_no_deliverable"
                keeper_id = _optional_text(
                    keeper.get("work_order_id"),
                    keeper.get("task_id"),
                )
                metadata = dict(item.get("metadata") or {})
                metadata.update(
                    {
                        "archived_due_to": "superseded_clean_exit_no_deliverable",
                        "archived_at": now,
                        "archive_reason": archive_reason,
                        "canonical_work_order_id": keeper_id or None,
                        "previous_status": _optional_text(item.get("status")) or "needs_human",
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                if not _optional_text(item.get("failure_reason")):
                    item["failure_reason"] = "clean_exit_no_deliverable"
                changed = True
                archived += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return archived


def archive_superseded_stale_lease_reaped_work_orders(self) -> int:
    """Archive helper stale-lease rows when an overlapping same-run sibling still owns the work."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        archived = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not _work_order_should_archive_superseded_stale_lease_reaped(item):
                    continue
                overlapping_siblings = [
                    sibling
                    for sibling in record["work_orders"]
                    if isinstance(sibling, dict)
                    and sibling is not item
                    and _work_orders_overlap_by_scope(item, sibling)
                    and _work_order_is_live_overlap_sibling(sibling)
                ]
                if not overlapping_siblings:
                    continue
                keeper = max(
                    overlapping_siblings,
                    key=lambda sibling: _live_overlap_sibling_priority(sibling, run=record),
                )
                keeper_id = _optional_text(
                    keeper.get("work_order_id"),
                    keeper.get("task_id"),
                )
                metadata = dict(item.get("metadata") or {})
                metadata.update(
                    {
                        "archived_due_to": "superseded_stale_lease_reaped",
                        "archived_at": now,
                        "archive_reason": "helper_stale_lease_reaped",
                        "canonical_work_order_id": keeper_id or None,
                        "previous_status": _optional_text(item.get("status")) or "needs_human",
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                if not _optional_text(item.get("failure_reason")):
                    item["failure_reason"] = "stale_lease_reaped"
                changed = True
                archived += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return archived


def archive_duplicate_work_order_leasing_failed_work_orders(self) -> int:
    """Collapse duplicate no-artifact leasing failures across runs."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        lease_status_by_id = {
            str(row["lease_id"]).strip(): str(row["status"]).strip()
            for row in conn.execute("SELECT lease_id, status FROM leases").fetchall()
            if str(row["lease_id"]).strip()
        }
        records = [self._supervisor_run_from_row(row) for row in rows]
        grouped: dict[tuple[str, tuple[str, ...]], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
        for record in records:
            goal_key = _canonical_goal_key(record.get("goal"))
            if not goal_key:
                continue
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                lease_status = lease_status_by_id.get(_optional_text(item.get("lease_id")))
                if not _work_order_is_duplicate_work_order_leasing_failed_candidate(
                    item,
                    run=record,
                    lease_status=lease_status,
                ):
                    continue
                scope_key = _canonical_work_order_scope_key(item)
                if not scope_key:
                    continue
                grouped.setdefault((goal_key, scope_key), []).append((record, item))

        archived = 0
        changed_run_ids: set[str] = set()
        for _, siblings in grouped.items():
            if len(siblings) < 2:
                continue
            keeper_record, keeper_item = max(
                siblings,
                key=lambda pair: _duplicate_work_order_leasing_failed_priority(
                    pair[1], run=pair[0]
                ),
            )
            keeper_run_id = _optional_text(keeper_record.get("run_id"))
            keeper_id = _optional_text(
                keeper_item.get("work_order_id"),
                keeper_item.get("task_id"),
            )
            for record, item in siblings:
                if record is keeper_record and item is keeper_item:
                    continue
                metadata = dict(item.get("metadata") or {})
                if _optional_text(metadata.get("archived_due_to")):
                    continue
                metadata.update(
                    {
                        "archived_due_to": "duplicate_work_order_leasing_failed",
                        "archived_at": now,
                        "archive_reason": "duplicate_work_order_leasing_failed",
                        "canonical_run_id": keeper_run_id or None,
                        "canonical_work_order_id": keeper_id or None,
                        "previous_status": _optional_text(item.get("status")) or "needs_human",
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                if not _optional_text(item.get("failure_reason")):
                    item["failure_reason"] = "work_order_leasing_failed"
                archived += 1
                changed_run_ids.add(_optional_text(record.get("run_id")))

        for record in records:
            run_id = _optional_text(record.get("run_id"))
            if run_id not in changed_run_ids:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return archived


def archive_duplicate_branch_deliverable_work_orders(
    self,
    *,
    grace_period_hours: float = _DUPLICATE_BRANCH_DELIVERABLE_ARCHIVE_GRACE_HOURS,
) -> int:
    """Collapse same-run duplicate deliverable siblings that point at the same branch."""
    now = _utcnow()
    grace_period = timedelta(hours=max(0.0, float(grace_period_hours)))
    cutoff = now - grace_period
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        lease_status_by_id = {
            str(row["lease_id"]).strip(): str(row["status"]).strip()
            for row in conn.execute("SELECT lease_id, status FROM leases").fetchall()
            if str(row["lease_id"]).strip()
        }
        archived = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            grouped: dict[str, list[dict[str, Any]]] = {}
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                branch = _optional_text(item.get("branch"))
                if branch:
                    grouped.setdefault(branch, []).append(item)
            changed = False
            for branch, items in grouped.items():
                eligible = [
                    item
                    for item in items
                    if _work_order_should_archive_duplicate_branch_deliverable(
                        item,
                        run=record,
                        cutoff=cutoff,
                        lease_status=lease_status_by_id.get(_optional_text(item.get("lease_id"))),
                    )
                ]
                if len(eligible) < 2:
                    continue
                keeper = max(
                    eligible,
                    key=lambda item: _duplicate_branch_deliverable_priority(item, run=record),
                )
                keeper_id = _optional_text(
                    keeper.get("work_order_id"),
                    keeper.get("task_id"),
                )
                for item in eligible:
                    if item is keeper:
                        continue
                    metadata = dict(item.get("metadata") or {})
                    metadata.update(
                        {
                            "archived_due_to": "duplicate_branch_deliverable",
                            "archived_at": now.isoformat(),
                            "archive_reason": f"duplicate_branch:{branch}",
                            "duplicate_branch": branch,
                            "canonical_work_order_id": keeper_id or None,
                            "previous_status": _optional_text(item.get("status")) or "completed",
                        }
                    )
                    item["metadata"] = metadata
                    item["status"] = "discarded"
                    if not _optional_text(item.get("failure_reason")):
                        item["failure_reason"] = "duplicate_branch_deliverable"
                    changed = True
                    archived += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now.isoformat()
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return archived


def archive_superseded_waiting_conflict_work_orders(
    self,
    *,
    grace_period_hours: float = _SUPERSEDED_WAITING_CONFLICT_ARCHIVE_GRACE_HOURS,
) -> int:
    """Archive stale waiting_conflict siblings covered by deliverables or duplicate same-scope siblings."""
    now = _utcnow()
    grace_period = timedelta(hours=max(0.0, float(grace_period_hours)))
    cutoff = now - grace_period
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        lease_status_by_id = {
            str(row["lease_id"]).strip(): str(row["status"]).strip()
            for row in conn.execute("SELECT lease_id, status FROM leases").fetchall()
            if str(row["lease_id"]).strip()
        }
        archived = 0
        records = [self._supervisor_run_from_row(row) for row in rows]
        for record in records:
            deliverable_items = [
                item
                for item in record["work_orders"]
                if isinstance(item, dict) and _work_order_has_concrete_deliverable(item)
            ]
            changed = False
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                lease_status = lease_status_by_id.get(_optional_text(item.get("lease_id")))
                if not _work_order_should_archive_superseded_waiting_conflict(
                    item,
                    run=record,
                    cutoff=cutoff,
                    lease_status=lease_status,
                ):
                    continue
                overlapping_deliverables = [
                    sibling
                    for sibling in deliverable_items
                    if sibling is not item and _work_orders_overlap_by_scope(item, sibling)
                ]
                if not overlapping_deliverables:
                    continue
                keeper = max(
                    overlapping_deliverables,
                    key=lambda sibling: _duplicate_branch_deliverable_priority(sibling, run=record),
                )
                keeper_id = _optional_text(
                    keeper.get("work_order_id"),
                    keeper.get("task_id"),
                )
                metadata = dict(item.get("metadata") or {})
                metadata.update(
                    {
                        "archived_due_to": "superseded_waiting_conflict",
                        "archived_at": now.isoformat(),
                        "archive_reason": "overlapping_deliverable_sibling",
                        "canonical_work_order_id": keeper_id or None,
                        "previous_status": "waiting_conflict",
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                if not _optional_text(item.get("failure_reason")):
                    item["failure_reason"] = "superseded_waiting_conflict"
                changed = True
                archived += 1
            if not changed:
                eligible_waiting = [
                    item
                    for item in record["work_orders"]
                    if isinstance(item, dict)
                    and _work_order_should_archive_superseded_waiting_conflict(
                        item,
                        run=record,
                        cutoff=cutoff,
                        lease_status=lease_status_by_id.get(_optional_text(item.get("lease_id"))),
                    )
                ]
                grouped_waiting: dict[tuple[str, ...], list[dict[str, Any]]] = {}
                for item in eligible_waiting:
                    scope_key = _canonical_work_order_scope_key(item)
                    if not scope_key:
                        continue
                    grouped_waiting.setdefault(scope_key, []).append(item)
                for siblings in grouped_waiting.values():
                    if len(siblings) < 2:
                        continue
                    keeper = min(
                        siblings,
                        key=lambda sibling: _duplicate_waiting_conflict_priority(
                            sibling, run=record
                        ),
                    )
                    keeper_id = _optional_text(
                        keeper.get("work_order_id"),
                        keeper.get("task_id"),
                    )
                    for item in siblings:
                        if item is keeper:
                            continue
                        metadata = dict(item.get("metadata") or {})
                        metadata.update(
                            {
                                "archived_due_to": "superseded_waiting_conflict",
                                "archived_at": now.isoformat(),
                                "archive_reason": "duplicate_waiting_conflict_sibling",
                                "canonical_work_order_id": keeper_id or None,
                                "previous_status": "waiting_conflict",
                            }
                        )
                        item["metadata"] = metadata
                        item["status"] = "discarded"
                        if not _optional_text(item.get("failure_reason")):
                            item["failure_reason"] = "superseded_waiting_conflict"
                        changed = True
                        archived += 1
                remaining_waiting = [
                    item
                    for item in record["work_orders"]
                    if isinstance(item, dict)
                    and _optional_text(item.get("status")).lower() == "waiting_conflict"
                    and not _optional_text(item.get("receipt_id"))
                    and not _work_order_has_concrete_deliverable(item)
                ]
                for item in remaining_waiting:
                    containing_siblings = [
                        sibling
                        for sibling in remaining_waiting
                        if sibling is not item
                        and _optional_text(sibling.get("status")).lower() == "waiting_conflict"
                        and _work_order_scope_contains(sibling, item)
                        and not _work_order_scope_contains(item, sibling)
                    ]
                    if not containing_siblings:
                        continue
                    keeper = max(
                        containing_siblings,
                        key=lambda sibling: _containing_waiting_conflict_priority(
                            sibling, run=record
                        ),
                    )
                    keeper_id = _optional_text(
                        keeper.get("work_order_id"),
                        keeper.get("task_id"),
                    )
                    metadata = dict(item.get("metadata") or {})
                    if _optional_text(metadata.get("archived_due_to")):
                        continue
                    metadata.update(
                        {
                            "archived_due_to": "superseded_waiting_conflict",
                            "archived_at": now.isoformat(),
                            "archive_reason": "contained_waiting_conflict_sibling",
                            "canonical_work_order_id": keeper_id or None,
                            "previous_status": "waiting_conflict",
                        }
                    )
                    item["metadata"] = metadata
                    item["status"] = "discarded"
                    if not _optional_text(item.get("failure_reason")):
                        item["failure_reason"] = "superseded_waiting_conflict"
                    changed = True
                    archived += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now.isoformat()
            self._persist_supervisor_run(conn, record)

        grouped_waiting_by_goal: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
        for record in records:
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                if not _work_order_should_archive_superseded_waiting_conflict(
                    item,
                    run=record,
                    cutoff=cutoff,
                    lease_status=lease_status_by_id.get(_optional_text(item.get("lease_id"))),
                ):
                    continue
                group_key = _superseded_waiting_conflict_group_key(item, run=record)
                if not group_key:
                    continue
                grouped_waiting_by_goal.setdefault(group_key, []).append((record, item))

        changed_run_ids: set[str] = set()
        for sibling_pairs in grouped_waiting_by_goal.values():
            pairs: list[tuple[dict[str, Any], dict[str, Any]]] = list(sibling_pairs)
            for record, item in pairs:
                if _optional_text(item.get("status")).lower() != "waiting_conflict":
                    continue
                metadata = dict(item.get("metadata") or {})
                if _optional_text(metadata.get("archived_due_to")):
                    continue
                record_run_id = _optional_text(record.get("run_id"))
                containing_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = [
                    (candidate_record, candidate_item)
                    for candidate_record, candidate_item in pairs
                    if candidate_item is not item
                    and _optional_text(candidate_record.get("run_id")) != record_run_id
                    and _optional_text(candidate_item.get("status")).lower() == "waiting_conflict"
                    and _work_order_scope_contains(candidate_item, item)
                    and not _work_order_scope_contains(item, candidate_item)
                ]
                if not containing_pairs:
                    continue
                keeper_record, keeper = max(
                    containing_pairs,
                    key=lambda pair: _containing_waiting_conflict_priority(pair[1], run=pair[0]),
                )
                metadata.update(
                    {
                        "archived_due_to": "superseded_waiting_conflict",
                        "archived_at": now.isoformat(),
                        "archive_reason": "cross_run_contained_waiting_conflict_sibling",
                        "canonical_run_id": _optional_text(keeper_record.get("run_id")) or None,
                        "canonical_work_order_id": _optional_text(
                            keeper.get("work_order_id"),
                            keeper.get("task_id"),
                        )
                        or None,
                        "previous_status": "waiting_conflict",
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                if not _optional_text(item.get("failure_reason")):
                    item["failure_reason"] = "superseded_waiting_conflict"
                changed_run_ids.add(record_run_id)
                archived += 1

        for record in records:
            run_id = _optional_text(record.get("run_id"))
            if run_id not in changed_run_ids:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now.isoformat()
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return archived


def archive_duplicate_waiting_conflict_work_orders(self) -> int:
    """Collapse duplicate no-artifact waiting_conflict rows across runs."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        lease_status_by_id = {
            str(row["lease_id"]).strip(): str(row["status"]).strip()
            for row in conn.execute("SELECT lease_id, status FROM leases").fetchall()
            if str(row["lease_id"]).strip()
        }
        records = [self._supervisor_run_from_row(row) for row in rows]
        grouped: dict[
            tuple[str, str, tuple[str, ...]],
            list[tuple[dict[str, Any], dict[str, Any]]],
        ] = {}
        for record in records:
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                lease_status = lease_status_by_id.get(_optional_text(item.get("lease_id")))
                if not _work_order_is_duplicate_waiting_conflict_candidate(
                    item,
                    run=record,
                    lease_status=lease_status,
                ):
                    continue
                group_key = _duplicate_waiting_conflict_group_key(item, run=record)
                if not group_key:
                    continue
                grouped.setdefault(group_key, []).append((record, item))

        archived = 0
        changed_run_ids: set[str] = set()
        for _, siblings in grouped.items():
            if len(siblings) < 2:
                continue
            keeper_record, keeper_item = max(
                siblings,
                key=lambda pair: _duplicate_waiting_conflict_priority(pair[1], run=pair[0]),
            )
            keeper_run_id = _optional_text(keeper_record.get("run_id"))
            keeper_id = _optional_text(
                keeper_item.get("work_order_id"),
                keeper_item.get("task_id"),
            )
            for record, item in siblings:
                if record is keeper_record and item is keeper_item:
                    continue
                metadata = dict(item.get("metadata") or {})
                if _optional_text(metadata.get("archived_due_to")):
                    continue
                metadata.update(
                    {
                        "archived_due_to": "duplicate_waiting_conflict",
                        "archived_at": now,
                        "archive_reason": "duplicate_waiting_conflict",
                        "canonical_run_id": keeper_run_id or None,
                        "canonical_work_order_id": keeper_id or None,
                        "previous_status": _optional_text(item.get("status")) or "waiting_conflict",
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                if not _optional_text(item.get("failure_reason")):
                    item["failure_reason"] = "duplicate_waiting_conflict"
                archived += 1
                changed_run_ids.add(_optional_text(record.get("run_id")))

        waiting_by_scope: dict[tuple[str, ...], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
        for record in records:
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                lease_status = lease_status_by_id.get(_optional_text(item.get("lease_id")))
                if not _work_order_is_duplicate_waiting_conflict_candidate(
                    item,
                    run=record,
                    lease_status=lease_status,
                ):
                    continue
                scope_key = _canonical_work_order_scope_key(item)
                if not scope_key:
                    continue
                waiting_by_scope.setdefault(scope_key, []).append((record, item))

        for siblings in waiting_by_scope.values():
            umbrella_candidates = [
                (record, item)
                for record, item in siblings
                if _work_order_is_broad_explicit_pytest_umbrella(item, run=record)
            ]
            if not umbrella_candidates:
                continue
            keeper_record, keeper_item = max(
                umbrella_candidates,
                key=lambda pair: _duplicate_waiting_conflict_priority(pair[1], run=pair[0]),
            )
            keeper_run_id = _optional_text(keeper_record.get("run_id"))
            keeper_id = _optional_text(
                keeper_item.get("work_order_id"),
                keeper_item.get("task_id"),
            )
            for record, item in siblings:
                if record is keeper_record and item is keeper_item:
                    continue
                if not _work_order_is_specific_pytest_child(item, run=record):
                    continue
                metadata = dict(item.get("metadata") or {})
                if _optional_text(metadata.get("archived_due_to")):
                    continue
                metadata.update(
                    {
                        "archived_due_to": "duplicate_waiting_conflict",
                        "archived_at": now,
                        "archive_reason": "broader_explicit_pytest_waiting_conflict",
                        "canonical_run_id": keeper_run_id or None,
                        "canonical_work_order_id": keeper_id or None,
                        "previous_status": _optional_text(item.get("status")) or "waiting_conflict",
                    }
                )
                item["metadata"] = metadata
                item["status"] = "discarded"
                if not _optional_text(item.get("failure_reason")):
                    item["failure_reason"] = "duplicate_waiting_conflict"
                archived += 1
                changed_run_ids.add(_optional_text(record.get("run_id")))

        for record in records:
            run_id = _optional_text(record.get("run_id"))
            if run_id not in changed_run_ids:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now
            self._persist_supervisor_run(conn, record)

        if archived:
            conn.commit()
        else:
            conn.rollback()
        return archived
    finally:
        conn.close()


def rehabilitate_narrowed_waiting_conflict_work_orders(
    self,
    *,
    grace_period_hours: float = _SUPERSEDED_WAITING_CONFLICT_ARCHIVE_GRACE_HOURS,
) -> int:
    """Narrow stale waiting-conflict scopes and requeue lanes that are no longer truly blocked."""
    now = _utcnow()
    grace_period = timedelta(hours=max(0.0, float(grace_period_hours)))
    cutoff = now - grace_period
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        lease_status_by_id = {
            str(row["lease_id"]).strip(): str(row["status"]).strip()
            for row in conn.execute("SELECT lease_id, status FROM leases").fetchall()
            if str(row["lease_id"]).strip()
        }
        records = [self._supervisor_run_from_row(row) for row in rows]
        updated = 0
        for record in records:
            changed = False
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                lease_status = lease_status_by_id.get(_optional_text(item.get("lease_id")))
                if not _work_order_should_rehabilitate_narrowed_waiting_conflict(
                    item,
                    run=record,
                    cutoff=cutoff,
                    lease_status=lease_status,
                ):
                    continue
                narrowed_scope = _narrow_waiting_conflict_scope_from_explicit_paths(
                    item,
                    run=record,
                    repo_root=self.repo_root,
                )
                if not narrowed_scope:
                    continue

                original_scope = [
                    str(path).strip() for path in item.get("file_scope", []) if str(path).strip()
                ]
                item_changed = False
                if _canonical_work_order_scope_key({"file_scope": narrowed_scope}) != (
                    _canonical_work_order_scope_key(item)
                ):
                    item["file_scope"] = list(narrowed_scope)
                    metadata = dict(item.get("metadata") or {})
                    metadata["waiting_conflict_scope_narrowed_at"] = now.isoformat()
                    metadata["waiting_conflict_original_scope"] = original_scope
                    item["metadata"] = metadata
                    item_changed = True

                lease_conflicts = self._find_conflicting_leases_locked(
                    conn,
                    allowed_globs=_work_order_scope_patterns(item),
                    claimed_paths=[],
                    owner_session_id=_optional_text(item.get("owner_session_id")),
                )
                sibling_conflicts = _blocking_waiting_conflict_siblings(
                    item,
                    run=record,
                    records=records,
                )
                item["conflicts"] = [*lease_conflicts, *sibling_conflicts]

                if not lease_conflicts and not sibling_conflicts:
                    metadata = dict(item.get("metadata") or {})
                    metadata["waiting_conflict_requeued_at"] = now.isoformat()
                    metadata["waiting_conflict_previous_scope"] = original_scope
                    metadata["waiting_conflict_requeue_reason"] = (
                        "narrowed_scope_cleared_container_only_blockers"
                    )
                    item["metadata"] = metadata
                    item["status"] = "queued"
                    item["blockers"] = []
                    item["conflicts"] = []
                    item.pop("review_status", None)
                    for key in (
                        "failure_reason",
                        "blocking_question",
                        "blocker",
                        "dispatch_error",
                    ):
                        item.pop(key, None)
                    item_changed = True
                else:
                    item["status"] = "waiting_conflict"
                    item["failure_reason"] = "waiting_conflict"
                    _backfill_work_order_blocker_metadata(item)
                    item["blockers"] = _developer_task_blockers(item)

                if not item_changed:
                    continue
                changed = True
                updated += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = now.isoformat()
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return updated


def backfill_file_scope_from_changed_paths(self) -> int:
    """Repair historical empty-scope rows from concrete changed-path evidence."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        backfilled = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                if not _work_order_should_backfill_file_scope_from_changed_paths(item):
                    continue
                changed_paths = [
                    str(path).strip()
                    for path in item.get("changed_paths", []) or []
                    if str(path).strip()
                ]
                if not changed_paths:
                    continue
                item["file_scope"] = list(dict.fromkeys(changed_paths))
                metadata = dict(item.get("metadata") or {})
                metadata["backfilled_file_scope_from_changed_paths"] = True
                metadata["file_scope_backfilled_at"] = now
                item["metadata"] = metadata
                changed = True
                backfilled += 1
            if not changed:
                continue
            record["updated_at"] = now
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return backfilled


def backfill_missing_completion_receipts(self) -> int:
    """Attach or synthesize missing receipts for stored deliverable work orders."""
    self.backfill_file_scope_from_changed_paths()
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
    finally:
        conn.close()

    backfilled = 0
    for row in rows:
        record = self._supervisor_run_from_row(row)
        changed = False
        for item in record["work_orders"]:
            if not isinstance(item, dict):
                continue
            if not _work_order_should_backfill_receipt(item):
                continue
            lease_id = _optional_text(item.get("lease_id"))
            if not lease_id:
                continue
            existing = self.list_completion_receipts(lease_id=lease_id, limit=1)
            if existing:
                receipt = existing[0]
            else:
                try:
                    receipt = self.record_completion(
                        lease_id=lease_id,
                        owner_agent=_optional_text(item.get("target_agent")),
                        owner_session_id=_optional_text(item.get("owner_session_id")),
                        branch=_optional_text(item.get("branch")),
                        worktree_path=_optional_text(item.get("worktree_path")),
                        base_sha=_optional_text(item.get("initial_head")),
                        head_sha=_optional_text(item.get("head_sha")),
                        commit_shas=list(item.get("commit_shas", []) or []),
                        changed_paths=list(item.get("changed_paths", []) or []),
                        tests_run=list(item.get("tests_run", []) or []),
                        validations_run=list(item.get("validations_run", []) or []),
                        assumptions=[],
                        blockers=[
                            str(blocker).strip()
                            for blocker in item.get("blockers", [])
                            if str(blocker).strip()
                        ],
                        outcome=_work_order_receipt_outcome(item),
                        risks=[
                            str(blocker).strip()
                            for blocker in item.get("blockers", [])
                            if str(blocker).strip()
                        ],
                        pr_url=_optional_text(item.get("pr_url"), item.get("adopted_pr")),
                        pr_number=_extract_pr_number(
                            _optional_text(item.get("pr_url"), item.get("adopted_pr"))
                        ),
                        confidence=float(item.get("confidence", 0.0) or 0.0),
                        metadata={
                            "task_key": _optional_text(item.get("task_key")) or None,
                            "verification_results": list(
                                item.get("verification_results", []) or []
                            ),
                            "worker_outcome": _optional_text(item.get("worker_outcome")) or None,
                            "approval_required": bool(item.get("approval_required", False)),
                            "risk_level": _optional_text(item.get("risk_level")) or None,
                            "success_criteria": dict(item.get("success_criteria") or {}),
                            "backfilled_receipt": True,
                        },
                        require_session_ownership=False,
                    )
                except FileScopeViolationError:
                    if not self._rehydrate_lease_scope_from_work_order(item):
                        continue
                    try:
                        receipt = self.record_completion(
                            lease_id=lease_id,
                            owner_agent=_optional_text(item.get("target_agent")),
                            owner_session_id=_optional_text(item.get("owner_session_id")),
                            branch=_optional_text(item.get("branch")),
                            worktree_path=_optional_text(item.get("worktree_path")),
                            base_sha=_optional_text(item.get("initial_head")),
                            head_sha=_optional_text(item.get("head_sha")),
                            commit_shas=list(item.get("commit_shas", []) or []),
                            changed_paths=list(item.get("changed_paths", []) or []),
                            tests_run=list(item.get("tests_run", []) or []),
                            validations_run=list(item.get("validations_run", []) or []),
                            assumptions=[],
                            blockers=[
                                str(blocker).strip()
                                for blocker in item.get("blockers", [])
                                if str(blocker).strip()
                            ],
                            outcome=_work_order_receipt_outcome(item),
                            risks=[
                                str(blocker).strip()
                                for blocker in item.get("blockers", [])
                                if str(blocker).strip()
                            ],
                            pr_url=_optional_text(item.get("pr_url"), item.get("adopted_pr")),
                            pr_number=_extract_pr_number(
                                _optional_text(item.get("pr_url"), item.get("adopted_pr"))
                            ),
                            confidence=float(item.get("confidence", 0.0) or 0.0),
                            metadata={
                                "task_key": _optional_text(item.get("task_key")) or None,
                                "verification_results": list(
                                    item.get("verification_results", []) or []
                                ),
                                "worker_outcome": _optional_text(item.get("worker_outcome"))
                                or None,
                                "approval_required": bool(item.get("approval_required", False)),
                                "risk_level": _optional_text(item.get("risk_level")) or None,
                                "success_criteria": dict(item.get("success_criteria") or {}),
                                "backfilled_receipt": True,
                                "lease_scope_rehydrated": True,
                            },
                            require_session_ownership=False,
                        )
                    except (FileScopeViolationError, KeyError, ValueError):
                        continue
                except (KeyError, ValueError):
                    continue
            item["receipt_id"] = receipt.receipt_id
            item["confidence"] = receipt.confidence
            changed = True
            backfilled += 1
        if not changed:
            continue
        self.update_supervisor_run(record["run_id"], work_orders=record["work_orders"])
    return backfilled


def _rehydrate_lease_scope_from_work_order(self, work_order: dict[str, Any]) -> bool:
    lease_id = _optional_text(work_order.get("lease_id"))
    if not lease_id:
        return False
    patterns = _work_order_scope_patterns(work_order)
    if not patterns:
        return False
    changed_paths = [
        _normalize_claim(str(item))
        for item in work_order.get("changed_paths", []) or []
        if _normalize_claim(str(item))
    ]
    if changed_paths and not all(
        any(_path_matches_glob(path, pattern) for pattern in patterns) for path in changed_paths
    ):
        return False
    allowed_globs = [pattern for pattern in patterns if _has_wildcard(pattern)]
    claimed_paths = [pattern for pattern in patterns if not _has_wildcard(pattern)]
    if not allowed_globs and not claimed_paths:
        claimed_paths = list(patterns)

    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        row = conn.execute("SELECT * FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
        if row is None:
            return False
        lease = WorkLease.from_row(row)
        if lease.claimed_paths or lease.allowed_globs:
            return False
        metadata = _json_loads(row["metadata_json"], {})
        metadata.pop("last_scope_violation", None)
        conn.execute(
            """
            UPDATE leases
            SET allowed_globs_json = ?, claimed_paths_json = ?, metadata_json = ?, updated_at = ?
            WHERE lease_id = ?
            """,
            (
                _json_dump(allowed_globs),
                _json_dump(claimed_paths),
                _json_dump(metadata),
                now,
                lease_id,
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def _run_verification_commands_sync(
    worktree_path: str,
    commands: list[str],
    *,
    timeout: float = 900.0,
) -> list[dict[str, Any]]:
    from aragora.swarm.worker_launcher import WorkerLauncher

    results: list[dict[str, Any]] = []
    verification_env = WorkerLauncher._verification_environment(worktree_path)
    for raw_command in commands:
        command = str(raw_command).strip()
        if not command:
            continue
        execution_command = WorkerLauncher._prepare_verification_command(command)
        command_timeout = _verification_timeout_for_command(command, timeout)
        started = time.monotonic()
        try:
            proc = subprocess.run(
                ["/bin/bash", "-lc", execution_command],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=command_timeout,
                check=False,
                env=verification_env,
            )
            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code = -1
            raw_stdout = exc.stdout
            raw_stderr = exc.stderr
            stdout = raw_stdout.decode() if isinstance(raw_stdout, bytes) else (raw_stdout or "")
            stderr = (
                raw_stderr.decode()
                if isinstance(raw_stderr, bytes)
                else (raw_stderr or f"Timed out after {int(command_timeout)}s")
            )
        except OSError as exc:
            exit_code = -2
            stdout = ""
            stderr = str(exc)
        results.append(
            {
                "command": command,
                "exit_code": exit_code,
                "passed": exit_code == 0,
                "stdout": stdout,
                "stderr": stderr,
                "duration_seconds": round(time.monotonic() - started, 3),
            }
        )
    return results


def _resolve_verification_worktree(
    self,
    work_order: dict[str, Any],
) -> tuple[str, Path | None]:
    worktree_path = Path(str(work_order.get("worktree_path") or "").strip())
    if worktree_path.is_dir():
        head_sha = str(work_order.get("head_sha") or "").strip()
        if head_sha:
            proc = subprocess.run(
                ["git", "-C", str(worktree_path), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            actual_sha = proc.stdout.strip() if proc.returncode == 0 else ""
            if not actual_sha or not (
                actual_sha.startswith(head_sha) or head_sha.startswith(actual_sha)
            ):
                pass  # fall through to create fresh worktree
            else:
                return str(worktree_path), None
        else:
            return str(worktree_path), None

    subprocess.run(
        ["git", "-C", str(self.repo_root), "worktree", "prune"],
        capture_output=True,
        text=True,
        check=False,
    )
    ref_candidates = [
        _optional_text(work_order.get("branch")),
        _optional_text(work_order.get("head_sha")),
    ]
    ref = ""
    for candidate in ref_candidates:
        if not candidate:
            continue
        proc = subprocess.run(
            ["git", "-C", str(self.repo_root), "rev-parse", "--verify", "--quiet", candidate],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            ref = candidate
            break
    if not ref:
        return "", None

    parent = self.repo_root / ".worktrees" / "verification-replay"
    parent.mkdir(parents=True, exist_ok=True)
    temp_path = parent / f"verify-{str(uuid.uuid4())[:8]}"
    proc = subprocess.run(
        ["git", "-C", str(self.repo_root), "worktree", "add", "--detach", str(temp_path), ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return "", None
    return str(temp_path), temp_path


def _cleanup_verification_worktree(self, worktree_path: Path | None) -> None:
    if worktree_path is None:
        return
    subprocess.run(
        ["git", "-C", str(self.repo_root), "worktree", "remove", "--force", str(worktree_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["git", "-C", str(self.repo_root), "worktree", "prune"],
        capture_output=True,
        text=True,
        check=False,
    )


def _update_completion_receipt_verification_locked(
    conn: sqlite3.Connection,
    *,
    receipt_id: str,
    verification_results: list[dict[str, Any]],
    replayed_at: str,
) -> bool:
    row = conn.execute(
        "SELECT * FROM completion_receipts WHERE receipt_id = ?",
        (receipt_id,),
    ).fetchone()
    if row is None:
        return False
    receipt = CompletionReceipt.from_row(row)
    tests_run = [
        str(entry.get("command", "")).strip()
        for entry in verification_results
        if str(entry.get("command", "")).strip()
    ]
    metadata = dict(receipt.metadata)
    metadata["verification_results"] = [dict(entry) for entry in verification_results]
    metadata["verification_replayed"] = True
    metadata["verification_replayed_at"] = replayed_at
    updated_receipt = CompletionReceipt(
        receipt_id=receipt.receipt_id,
        lease_id=receipt.lease_id,
        task_id=receipt.task_id,
        owner_agent=receipt.owner_agent,
        owner_session_id=receipt.owner_session_id,
        branch=receipt.branch,
        worktree_path=receipt.worktree_path,
        base_sha=receipt.base_sha,
        head_sha=receipt.head_sha,
        commit_shas=list(receipt.commit_shas),
        changed_paths=list(receipt.changed_paths),
        tests_run=tests_run,
        validations_run=tests_run,
        assumptions=list(receipt.assumptions),
        blockers=list(receipt.blockers),
        outcome=receipt.outcome,
        risks=list(receipt.risks),
        pr_url=receipt.pr_url,
        pr_number=receipt.pr_number,
        confidence=receipt.confidence,
        created_at=receipt.created_at,
        metadata=metadata,
    )
    conn.execute(
        """
        UPDATE completion_receipts
        SET tests_run_json = ?, validations_run_json = ?, artifact_hash = ?, metadata_json = ?
        WHERE receipt_id = ?
        """,
        (
            _json_dump(updated_receipt.tests_run),
            _json_dump(updated_receipt.validations_run),
            updated_receipt.artifact_hash,
            _json_dump(updated_receipt.metadata),
            receipt_id,
        ),
    )
    return True


def sync_completion_receipt_verification(
    self,
    *,
    receipt_id: str,
    verification_results: list[dict[str, Any]],
    replayed_at: str | None = None,
) -> bool:
    normalized_receipt_id = str(receipt_id or "").strip()
    if not normalized_receipt_id:
        return False
    timestamp = str(replayed_at or _utcnow().isoformat()).strip() or _utcnow().isoformat()
    normalized_results = [dict(entry) for entry in verification_results if isinstance(entry, dict)]
    conn = self._connect()
    try:
        updated = self._update_completion_receipt_verification_locked(
            conn,
            receipt_id=normalized_receipt_id,
            verification_results=normalized_results,
            replayed_at=timestamp,
        )
        if updated:
            conn.commit()
        return updated
    finally:
        conn.close()


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
    normalized_task_keys = {
        str(task_key).strip() for task_key in (task_keys or []) if str(task_key).strip()
    }
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        candidate_ids: list[tuple[str, str]] = []
        attempted = 0
        for row in rows:
            if isinstance(limit, int) and limit > 0 and attempted >= limit:
                break
            record = self._supervisor_run_from_row(row)
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                if isinstance(limit, int) and limit > 0 and attempted >= limit:
                    break
                if not _merge_gate_replay_matches_task_keys(
                    record["run_id"], item, normalized_task_keys
                ):
                    continue
                if not should_replay(item):
                    continue
                work_order_id = _work_order_identifier(item)
                if not work_order_id:
                    continue
                candidate_ids.append((record["run_id"], work_order_id))
                attempted += 1
    finally:
        conn.close()

    replayed = 0
    for run_id, work_order_id in candidate_ids:
        record = self.get_supervisor_run(run_id)
        if not record:
            continue
        item = _find_work_order(record, work_order_id)
        if item is None or not _merge_gate_replay_matches_task_keys(
            run_id, item, normalized_task_keys
        ):
            continue
        if not should_replay(item):
            continue

        commands = [
            str(command).strip()
            for command in item.get("expected_tests", [])
            if str(command).strip()
        ]
        if prepare_commands is not None:
            prepared_commands = prepare_commands(item)
            if prepared_commands is None:
                continue
            commands = [
                str(command).strip() for command in prepared_commands if str(command).strip()
            ]
        if not commands:
            continue

        worktree_path, cleanup_path = self._resolve_verification_worktree(item)
        if not worktree_path:
            continue
        try:
            verification_results = self._run_verification_commands_sync(
                worktree_path,
                commands,
                timeout=timeout,
            )
        finally:
            self._cleanup_verification_worktree(cleanup_path)
        if not verification_results:
            continue

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM supervisor_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                continue
            record = self._supervisor_run_from_row(row)
            item = _find_work_order(record, work_order_id)
            if item is None or not _merge_gate_replay_matches_task_keys(
                run_id, item, normalized_task_keys
            ):
                continue
            if not should_replay(item):
                continue
            if prepare_commands is not None and prepare_commands(item) is None:
                continue

            existing_results = [
                dict(entry)
                for entry in item.get("verification_results", [])
                if isinstance(entry, dict) and str(entry.get("command", "")).strip()
            ]
            existing_tests_run = [
                str(command).strip()
                for command in item.get("tests_run", [])
                if str(command).strip()
            ]
            effective_results = [dict(entry) for entry in verification_results]
            effective_tests_run = [
                str(entry.get("command", "")).strip()
                for entry in effective_results
                if str(entry.get("command", "")).strip()
            ]
            if merge_existing_results:
                seen_commands = {
                    _canonical_verification_command(entry.get("command", ""))
                    for entry in effective_results
                    if _canonical_verification_command(entry.get("command", ""))
                }
                for entry in existing_results:
                    canonical = _canonical_verification_command(entry.get("command", ""))
                    if canonical and canonical not in seen_commands:
                        effective_results.append(dict(entry))
                        seen_commands.add(canonical)
                seen_tests = {
                    _canonical_verification_command(command)
                    for command in effective_tests_run
                    if _canonical_verification_command(command)
                }
                for command in existing_tests_run:
                    canonical = _canonical_verification_command(command)
                    if canonical and canonical not in seen_tests:
                        effective_tests_run.append(command)
                        seen_tests.add(canonical)

            item["tests_run"] = effective_tests_run
            item["verification_results"] = [dict(entry) for entry in effective_results]
            item["merge_gate"] = _merge_gate_state_for_work_order(item)
            metadata = dict(item.get("metadata") or {})
            metadata[metadata_flag] = True
            metadata[f"{metadata_flag}_at"] = _utcnow().isoformat()
            item["metadata"] = metadata
            receipt_id = _optional_text(item.get("receipt_id"))
            if receipt_id:
                self._update_completion_receipt_verification_locked(
                    conn,
                    receipt_id=receipt_id,
                    verification_results=effective_results,
                    replayed_at=metadata[f"{metadata_flag}_at"],
                )
            if item["merge_gate"]["checks_passed"]:
                item["status"] = "completed"
                item["review_status"] = "pending_heterogeneous_review"
                item["worker_outcome"] = "completed"
                item["blockers"] = []
                for key in (
                    "failure_reason",
                    "blocking_question",
                    "blocker",
                    "dispatch_error",
                ):
                    item.pop(key, None)
            else:
                item["status"] = "needs_human"
                item["review_status"] = "changes_requested"
                item["worker_outcome"] = "merge_gate_failed"
                item["failure_reason"] = "merge_gate_failed"
                item["dispatch_error"] = (
                    item["merge_gate"]["blocked_reasons"][0]
                    if item["merge_gate"]["blocked_reasons"]
                    else "merge gate blocked"
                )
                item["blockers"] = list(item["merge_gate"]["blocked_reasons"])
                _backfill_work_order_blocker_metadata(item)
                if _work_order_should_reclassify_deliverable_changes_requested(item):
                    item["status"] = "changes_requested"

            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = _utcnow().isoformat()
            self._persist_supervisor_run(conn, record)
            conn.commit()
            replayed += 1
        finally:
            conn.close()
    return replayed


def replay_missing_verification_for_merge_gate_failures(
    self,
    *,
    task_keys: list[str] | None = None,
    limit: int | None = None,
    timeout: float = 900.0,
) -> int:
    return self._replay_merge_gate_failures(
        should_replay=_work_order_should_replay_missing_verification,
        metadata_flag="verification_replayed",
        task_keys=task_keys,
        limit=limit,
        timeout=timeout,
    )


def replay_environment_blocked_merge_gate_failures(
    self,
    *,
    task_keys: list[str] | None = None,
    limit: int | None = None,
    timeout: float = 900.0,
) -> int:
    return self._replay_merge_gate_failures(
        should_replay=_work_order_should_replay_environment_blocked_verification,
        metadata_flag="verification_environment_replayed",
        task_keys=task_keys,
        limit=limit,
        timeout=timeout,
    )


def replay_docs_only_merge_gate_failures(
    self,
    *,
    task_keys: list[str] | None = None,
    limit: int | None = None,
    timeout: float = 900.0,
) -> int:
    return self._replay_merge_gate_failures(
        should_replay=_work_order_should_replay_docs_only_merge_gate_failure,
        metadata_flag="verification_docs_replayed",
        prepare_commands=_docs_only_replay_commands_for_work_order,
        task_keys=task_keys,
        limit=limit,
        timeout=timeout,
    )


def replay_missing_required_merge_gate_failures(
    self,
    *,
    task_keys: list[str] | None = None,
    limit: int | None = None,
    timeout: float = 900.0,
) -> int:
    return self._replay_merge_gate_failures(
        should_replay=_work_order_should_replay_missing_required_merge_gate_failure,
        metadata_flag="verification_missing_required_replayed",
        prepare_commands=_missing_required_replay_commands_for_work_order,
        merge_existing_results=True,
        task_keys=task_keys,
        limit=limit,
        timeout=timeout,
    )


def replay_narrow_pytest_merge_gate_failures(
    self,
    *,
    task_keys: list[str] | None = None,
    limit: int | None = None,
    timeout: float = 900.0,
) -> int:
    return self._replay_merge_gate_failures(
        should_replay=_work_order_should_replay_narrow_pytest_merge_gate_failure,
        metadata_flag="verification_narrow_pytest_replayed",
        prepare_commands=_narrow_pytest_replay_commands_for_work_order,
        task_keys=task_keys,
        limit=limit,
        timeout=timeout,
    )


def replay_targeted_merge_gate_failures(
    self,
    *,
    task_keys: list[str] | None = None,
    limit: int | None = None,
    timeout: float = 900.0,
) -> int:
    def _prepare(item: dict[str, Any]) -> list[str] | None:
        targeted_commands = _targeted_replay_expected_tests_for_work_order(item)
        if not targeted_commands:
            return None
        previous_expected = [
            str(command).strip()
            for command in item.get("expected_tests", [])
            if str(command).strip()
        ]
        metadata = dict(item.get("metadata") or {})
        if previous_expected and not metadata.get("verification_targeted_previous_expected_tests"):
            metadata["verification_targeted_previous_expected_tests"] = list(previous_expected)
        item["metadata"] = metadata
        item["expected_tests"] = list(targeted_commands)
        success_criteria = dict(item.get("success_criteria") or {})
        success_criteria["tests"] = (
            targeted_commands[0] if len(targeted_commands) == 1 else list(targeted_commands)
        )
        item["success_criteria"] = success_criteria
        item["tests_run"] = []
        item["verification_results"] = []
        return targeted_commands

    return self._replay_merge_gate_failures(
        should_replay=_work_order_should_replay_targeted_merge_gate_failure,
        metadata_flag="verification_targeted_replayed",
        prepare_commands=_prepare,
        task_keys=task_keys,
        limit=limit,
        timeout=timeout,
    )


def reclassify_branch_stale_merge_gate_failures(
    self,
    *,
    limit: int | None = None,
    timeout: float = 900.0,
    task_keys: list[str] | None = None,
) -> int:
    requested_task_keys = {str(item).strip() for item in (task_keys or []) if str(item).strip()}

    def _task_key_for(record: dict[str, Any], item: dict[str, Any], work_order_id: str) -> str:
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            task_key = _optional_text(metadata.get("task_key"))
            if task_key:
                return task_key
        task_key = _optional_text(item.get("task_key"))
        if task_key:
            return task_key
        if record.get("run_id") and work_order_id:
            return f"{record['run_id']}:{work_order_id}"
        return ""

    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        candidate_ids: list[tuple[str, str]] = []
        attempted = 0
        for row in rows:
            if isinstance(limit, int) and limit > 0 and attempted >= limit:
                break
            record = self._supervisor_run_from_row(row)
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                if isinstance(limit, int) and limit > 0 and attempted >= limit:
                    break
                if not (
                    _work_order_should_reclassify_branch_stale_merge_gate_failure(item)
                    or _work_order_should_reclassify_branch_stale_verification_target_missing(
                        item, repo_root=self.repo_root
                    )
                ):
                    continue
                work_order_id = _work_order_identifier(item)
                if not work_order_id:
                    continue
                task_key = _task_key_for(record, item, work_order_id)
                if requested_task_keys and task_key not in requested_task_keys:
                    continue
                candidate_ids.append((record["run_id"], work_order_id))
                attempted += 1
    finally:
        conn.close()

    reclassified = 0
    for run_id, work_order_id in candidate_ids:
        record = self.get_supervisor_run(run_id)
        if not record:
            continue
        item = _find_work_order(record, work_order_id)
        is_missing_target = False
        if item is None:
            continue
        if _work_order_should_reclassify_branch_stale_merge_gate_failure(item):
            pass
        elif _work_order_should_reclassify_branch_stale_verification_target_missing(
            item, repo_root=self.repo_root
        ):
            is_missing_target = True
        else:
            continue
        task_key = _task_key_for(record, item, work_order_id)
        if requested_task_keys and task_key not in requested_task_keys:
            continue
        target_ref = _optional_text(record.get("target_branch")) or "main"
        commands = _mainline_verification_commands_for_work_order(item)
        verification_results: list[dict[str, Any]] = []
        missing_paths: list[str] = []
        if is_missing_target:
            missing_paths = _mainline_missing_repo_paths_for_work_order(
                item, repo_root=self.repo_root
            )
            if not missing_paths:
                continue
        else:
            if not commands:
                continue
            worktree_path, cleanup_path = self._resolve_verification_worktree(
                {"branch": target_ref}
            )
            if not worktree_path and target_ref != "main":
                target_ref = "main"
                worktree_path, cleanup_path = self._resolve_verification_worktree(
                    {"branch": target_ref}
                )
            if not worktree_path:
                continue
            try:
                verification_results = self._run_verification_commands_sync(
                    worktree_path,
                    commands,
                    timeout=timeout,
                )
            finally:
                self._cleanup_verification_worktree(cleanup_path)
            if not verification_results or not all(
                bool(entry.get("passed", False)) for entry in verification_results
            ):
                continue

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM supervisor_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                continue
            refreshed_record = self._supervisor_run_from_row(row)
            refreshed_item = _find_work_order(refreshed_record, work_order_id)
            refreshed_is_missing_target = False
            if refreshed_item is None:
                continue
            if _work_order_should_reclassify_branch_stale_merge_gate_failure(refreshed_item):
                pass
            elif _work_order_should_reclassify_branch_stale_verification_target_missing(
                refreshed_item, repo_root=self.repo_root
            ):
                refreshed_is_missing_target = True
            else:
                continue
            refreshed_task_key = _task_key_for(refreshed_record, refreshed_item, work_order_id)
            if requested_task_keys and refreshed_task_key not in requested_task_keys:
                continue

            checked_at = _utcnow().isoformat()
            metadata = dict(refreshed_item.get("metadata") or {})
            metadata["mainline_verification_checked_at"] = checked_at
            if refreshed_is_missing_target:
                metadata["mainline_verification_target_missing"] = True
                metadata["mainline_missing_paths"] = list(missing_paths)
                metadata["mainline_verification_commands"] = list(commands)
            else:
                metadata["mainline_verification_passed"] = True
                metadata["mainline_verification_commands"] = list(commands)
                metadata["mainline_verification_results"] = [
                    dict(entry) for entry in verification_results
                ]
            refreshed_item["metadata"] = metadata
            refreshed_item["status"] = "changes_requested"
            refreshed_item["review_status"] = "changes_requested"
            refreshed_item["worker_outcome"] = "branch_snapshot_stale"
            refreshed_item["failure_reason"] = "branch_snapshot_stale"
            refreshed_item["blocking_question"] = _default_blocking_question_for_reason(
                "branch_snapshot_stale"
            )
            if refreshed_is_missing_target:
                refreshed_item["dispatch_error"] = (
                    "branch snapshot stale: referenced verification targets no longer exist "
                    f"on {target_ref}"
                )
            else:
                refreshed_item["dispatch_error"] = (
                    f"branch snapshot stale: merge-gate verification now passes on {target_ref}"
                )
            refreshed_item["blockers"] = ["branch_snapshot_stale"]
            refreshed_item["blocker"] = {
                "reason": "branch_snapshot_stale",
                "question": refreshed_item["blocking_question"],
            }

            refreshed_record["status"] = self._derive_supervisor_run_status(
                refreshed_record["work_orders"]
            )
            refreshed_record["updated_at"] = checked_at
            self._persist_supervisor_run(conn, refreshed_record)
            conn.commit()
            reclassified += 1
        finally:
            conn.close()

    return reclassified


def reconcile_merge_gate_failed_work_orders(self) -> int:
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        reconciled = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                if not _work_order_should_reconcile_merge_gate_failure(item):
                    continue
                item["merge_gate"] = _merge_gate_state_for_work_order(item)
                metadata = dict(item.get("metadata") or {})
                metadata["merge_gate_reconciled"] = True
                metadata["merge_gate_reconciled_at"] = _utcnow().isoformat()
                item["metadata"] = metadata
                if item["merge_gate"]["checks_passed"]:
                    item["status"] = "completed"
                    item["review_status"] = "pending_heterogeneous_review"
                    item["worker_outcome"] = "completed"
                    item["blockers"] = []
                    for key in (
                        "failure_reason",
                        "blocking_question",
                        "blocker",
                        "dispatch_error",
                    ):
                        item.pop(key, None)
                else:
                    item["status"] = "needs_human"
                    item["review_status"] = "changes_requested"
                    item["worker_outcome"] = "merge_gate_failed"
                    item["failure_reason"] = "merge_gate_failed"
                    item["dispatch_error"] = (
                        item["merge_gate"]["blocked_reasons"][0]
                        if item["merge_gate"]["blocked_reasons"]
                        else "merge gate blocked"
                    )
                    item["blockers"] = list(item["merge_gate"]["blocked_reasons"])
                    _backfill_work_order_blocker_metadata(item)
                changed = True
                reconciled += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = _utcnow().isoformat()
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return reconciled


def list_completion_receipts(
    self,
    lease_id: str | None = None,
    *,
    task_id: str | None = None,
    limit: int | None = None,
) -> list[CompletionReceipt]:
    suffix = ""
    params: list[Any] = []
    if isinstance(limit, int) and limit > 0:
        suffix = " LIMIT ?"
    conn = self._connect()
    try:
        if lease_id:
            params = [lease_id]
            if suffix:
                params.append(limit)
            rows = conn.execute(
                "SELECT * FROM completion_receipts WHERE lease_id = ? ORDER BY created_at DESC"
                + suffix,
                tuple(params),
            ).fetchall()
        elif task_id:
            params = [task_id]
            if suffix:
                params.append(limit)
            rows = conn.execute(
                "SELECT * FROM completion_receipts WHERE task_id = ? ORDER BY created_at DESC"
                + suffix,
                tuple(params),
            ).fetchall()
        else:
            params = [limit] if suffix else []
            rows = conn.execute(
                "SELECT * FROM completion_receipts ORDER BY created_at DESC" + suffix,
                tuple(params),
            ).fetchall()
    finally:
        conn.close()
    return [CompletionReceipt.from_row(row) for row in rows]


def get_completion_receipt(self, receipt_id: str) -> CompletionReceipt | None:
    conn = self._connect()
    try:
        row = conn.execute(
            "SELECT * FROM completion_receipts WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else CompletionReceipt.from_row(row)


def list_integration_decisions(
    self,
    *,
    only_pending: bool = False,
    receipt_id: str | None = None,
    limit: int | None = None,
) -> list[IntegrationDecision]:
    suffix = ""
    params: list[Any] = []
    if isinstance(limit, int) and limit > 0:
        suffix = " LIMIT ?"
    conn = self._connect()
    try:
        if receipt_id:
            params = [receipt_id]
            if suffix:
                params.append(limit)
            rows = conn.execute(
                "SELECT * FROM integration_decisions WHERE receipt_id = ? ORDER BY created_at DESC"
                + suffix,
                tuple(params),
            ).fetchall()
        else:
            params = [limit] if suffix else []
            rows = conn.execute(
                "SELECT * FROM integration_decisions ORDER BY created_at DESC" + suffix,
                tuple(params),
            ).fetchall()
    finally:
        conn.close()
    decisions = [IntegrationDecision.from_row(row) for row in rows]
    if only_pending:
        return [item for item in decisions if item.decision in _PENDING_INTEGRATION_DECISIONS]
    return decisions


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
    normalized_changed_paths = [
        _normalize_claim(item) for item in changed_paths or [] if str(item).strip()
    ]
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        lease_row = conn.execute("SELECT * FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
        if lease_row is None:
            raise KeyError(f"Unknown lease_id: {lease_id}")
        lease = WorkLease.from_row(lease_row)
        lease_metadata = _json_loads(lease_row["metadata_json"], {})
        receipt_metadata = {
            **dict(metadata or {}),
            "supervisor_run_id": lease_metadata.get("supervisor_run_id"),
            "work_order_id": lease_metadata.get("work_order_id"),
            "task_key": lease_metadata.get("task_key"),
            "reviewer_agent": lease_metadata.get("reviewer_agent"),
            "risk_level": lease_metadata.get("risk_level"),
        }
        if (str(pr_url or "").strip() or pr_number is not None) and not str(
            receipt_metadata.get("pr_created_at", "")
        ).strip():
            receipt_metadata["pr_created_at"] = now
        normalized_outcome = _normalize_completion_outcome(
            outcome=str(outcome or "completed").strip() or "completed",
            commit_shas=list(commit_shas or []),
            changed_paths=normalized_changed_paths,
            pr_url=str(pr_url or "").strip(),
            pr_number=pr_number,
        )
        receipt = CompletionReceipt(
            receipt_id=str(uuid.uuid4())[:12],
            lease_id=lease_id,
            task_id=lease.task_id,
            owner_agent=owner_agent,
            owner_session_id=owner_session_id,
            branch=branch,
            worktree_path=str(Path(worktree_path).resolve()),
            base_sha=str(base_sha or lease_metadata.get("base_sha") or "").strip(),
            head_sha=str(head_sha or "").strip(),
            commit_shas=list(commit_shas or []),
            changed_paths=normalized_changed_paths,
            tests_run=list(tests_run or []),
            validations_run=list(validations_run or tests_run or []),
            assumptions=list(assumptions or []),
            blockers=list(blockers or []),
            outcome=normalized_outcome,
            risks=list(risks or blockers or []),
            pr_url=str(pr_url or "").strip(),
            pr_number=pr_number,
            confidence=float(confidence),
            created_at=now,
            metadata=receipt_metadata,
        )
        violations = self._validate_completion_scope(
            lease,
            changed_paths=receipt.changed_paths,
            owner_session_id=owner_session_id,
            branch=branch,
            require_session_ownership=require_session_ownership,
        )
        if violations:
            metadata = {
                **_json_loads(lease_row["metadata_json"], {}),
                "last_scope_violation": {
                    "detected_at": now,
                    "changed_paths": list(receipt.changed_paths),
                    "violations": violations,
                },
            }
            conn.execute(
                "UPDATE leases SET updated_at = ?, metadata_json = ? WHERE lease_id = ?",
                (now, _json_dump(metadata), lease_id),
            )
            conn.commit()
            self._publish(
                "scope_violation_detected",
                track=branch,
                data={
                    "lease_id": lease_id,
                    "owner_session_id": owner_session_id,
                    "changed_paths": receipt.changed_paths,
                    "violations": violations,
                },
            )
            raise FileScopeViolationError(violations)
        conn.execute(
            """
            INSERT INTO completion_receipts (
                receipt_id, lease_id, owner_agent, owner_session_id, branch, worktree_path,
                commit_shas_json, changed_paths_json, tests_run_json, assumptions_json,
                blockers_json, confidence, created_at, artifact_hash, task_id, base_sha,
                head_sha, validations_run_json, outcome, risks_json, pr_url, pr_number,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
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
                receipt.task_id,
                receipt.base_sha,
                receipt.head_sha,
                _json_dump(receipt.validations_run),
                receipt.outcome,
                _json_dump(receipt.risks),
                receipt.pr_url,
                receipt.pr_number,
                _json_dump(receipt.metadata),
            ),
        )
        conn.execute(
            "UPDATE leases SET status = ?, updated_at = ?, metadata_json = ? WHERE lease_id = ?",
            (
                LeaseStatus.COMPLETED.value,
                now,
                _json_dump(
                    {
                        **lease_metadata,
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

    self._release_fleet_claims_for_lease(lease)

    self._publish(
        "task_completed",
        track=branch,
        data={
            "lease_id": lease_id,
            "receipt_id": receipt.receipt_id,
            "files": receipt.changed_paths,
            "tests_run": receipt.tests_run,
            "validations_run": receipt.validations_run,
            "confidence": receipt.confidence,
            "task_id": receipt.task_id,
            "base_sha": receipt.base_sha,
            "head_sha": receipt.head_sha,
            "outcome": receipt.outcome,
            "risks": receipt.risks,
            "pr_url": receipt.pr_url or None,
            "pr_number": receipt.pr_number,
            "pr_created_at": receipt.metadata.get("pr_created_at"),
            "metadata": dict(receipt.metadata),
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
            "task_id": receipt.task_id,
        },
    )
    self.fleet_store.enqueue_merge(
        session_id=owner_session_id,
        branch=branch,
        title=f"{owner_agent}: {lease_id}",
        metadata={
            "lease_id": lease_id,
            "receipt_id": receipt.receipt_id,
            "task_id": receipt.task_id,
            "tests_run": receipt.tests_run,
            "validations_run": receipt.validations_run,
            "changed_paths": receipt.changed_paths,
            "confidence": receipt.confidence,
            "artifact_hash": receipt.artifact_hash,
            "base_sha": receipt.base_sha,
            "head_sha": receipt.head_sha,
            "outcome": receipt.outcome,
            "risks": receipt.risks,
            "pr_url": receipt.pr_url or None,
            "pr_number": receipt.pr_number,
            "pr_created_at": receipt.metadata.get("pr_created_at"),
        },
    )
    self._sync_supervisor_run_from_lease(
        lease.metadata,
        update={
            "status": "completed",
            "receipt_id": receipt.receipt_id,
            "changed_paths": list(receipt.changed_paths),
            "tests_run": list(receipt.tests_run),
            "confidence": receipt.confidence,
            "review_status": "pending_heterogeneous_review",
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
                chosen_commits or (_json_loads(latest["chosen_commits_json"], []) if latest else [])
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
    queue_item = self._find_fleet_queue_item(receipt_id=receipt_id)
    if queue_item is not None:
        queue_status = {
            IntegrationDecisionType.MERGE: "integrating",
            IntegrationDecisionType.CHERRY_PICK: "integrating",
            IntegrationDecisionType.REQUEST_CHANGES: "needs_human",
            IntegrationDecisionType.DISCARD: "blocked",
            IntegrationDecisionType.SALVAGE: "blocked",
        }.get(decision)
        if queue_status:
            self.fleet_store.update_merge_queue_item(
                item_id=str(queue_item.get("id", "")),
                status=queue_status,
                metadata={
                    "integration_decision_id": decision_row.decision_id,
                    "integration_decision": decision_row.decision,
                    "chosen_commits": decision_row.chosen_commits,
                    "followups": decision_row.followups,
                },
            )
    conn = self._connect()
    try:
        lease_row = conn.execute(
            "SELECT metadata_json FROM leases WHERE lease_id = ?",
            (decision_row.lease_id,),
        ).fetchone()
    finally:
        conn.close()
    lease_metadata = _json_loads(lease_row["metadata_json"], {}) if lease_row else {}
    self._sync_supervisor_run_from_lease(
        lease_metadata,
        update={
            "integration_decision": decision_row.decision,
            "integration_decision_id": decision_row.decision_id,
            "integration_followups": list(decision_row.followups),
            "status": {
                IntegrationDecisionType.PENDING_REVIEW.value: "needs_human",
                IntegrationDecisionType.MERGE.value: "integrating",
                IntegrationDecisionType.CHERRY_PICK.value: "integrating",
                IntegrationDecisionType.REQUEST_CHANGES.value: "changes_requested",
                IntegrationDecisionType.DISCARD.value: "discarded",
                IntegrationDecisionType.SALVAGE.value: "salvage",
            }.get(decision_row.decision, "needs_human"),
        },
    )
    return decision_row


def mark_supervisor_run_merged(
    self,
    *,
    receipt_id: str,
    merge_commit_sha: str | None = None,
    merged_at: str | None = None,
) -> None:
    receipt = self.get_completion_receipt(receipt_id)
    if receipt is None:
        return
    conn = self._connect()
    try:
        lease_row = conn.execute(
            "SELECT metadata_json FROM leases WHERE lease_id = ?",
            (receipt.lease_id,),
        ).fetchone()
    finally:
        conn.close()
    lease_metadata = _json_loads(lease_row["metadata_json"], {}) if lease_row else {}
    merged_at_text = str(merged_at or _utcnow().isoformat()).strip() or _utcnow().isoformat()
    update = {"status": "merged", "merged_at": merged_at_text}
    if merge_commit_sha:
        update["merge_commit_sha"] = merge_commit_sha
    self._sync_supervisor_run_from_lease(lease_metadata, update=update)
    self._record_supervisor_merge_telemetry(
        lease_metadata,
        receipt=receipt,
        merge_commit_sha=merge_commit_sha,
        merged_at=merged_at_text,
    )


def _record_supervisor_merge_telemetry(
    self,
    lease_metadata: dict[str, Any] | None,
    *,
    receipt: CompletionReceipt,
    merge_commit_sha: str | None,
    merged_at: str,
) -> None:
    from aragora.swarm.lane_telemetry import LaneTelemetryRecord

    if not isinstance(lease_metadata, dict):
        lease_metadata = {}
    run_id = str(lease_metadata.get("supervisor_run_id", "")).strip()
    work_order_id = str(lease_metadata.get("work_order_id", "")).strip()
    task_key = str(lease_metadata.get("task_key", "")).strip()
    lane_id = task_key or (
        f"{run_id}:{work_order_id}" if run_id and work_order_id else work_order_id or run_id
    )
    if not lane_id:
        return

    collector = _get_lane_telemetry()
    existing = collector.get_lane("supervisor_work_order", lane_id)
    deliverable_type = str(existing.deliverable_type if existing else "").strip()
    if not deliverable_type:
        if receipt.pr_url or receipt.pr_number is not None:
            deliverable_type = "pr"
        elif receipt.branch and receipt.commit_shas:
            deliverable_type = "branch"
    terminal_outcome = str(existing.terminal_outcome if existing else "").strip()
    if not terminal_outcome:
        terminal_outcome = str(receipt.outcome or "").strip()
    if terminal_outcome == "completed":
        terminal_outcome = (
            "deliverable_created" if deliverable_type else "clean_exit_no_deliverable"
        )
    if not terminal_outcome:
        if deliverable_type == "adopted_pr":
            terminal_outcome = "pr_adopted"
        elif deliverable_type:
            terminal_outcome = "deliverable_created"
        else:
            terminal_outcome = "unknown"

    time_to_merge_seconds = existing.time_to_merge_seconds if existing else None
    try:
        time_to_merge_seconds = max(
            0.0,
            (_parse_dt(merged_at) - _parse_dt(receipt.created_at)).total_seconds(),
        )
    except (TypeError, ValueError):
        pass
    time_to_pr_seconds = existing.time_to_pr_seconds if existing else None
    pr_created_at = str((receipt.metadata or {}).get("pr_created_at", "")).strip()
    try:
        if pr_created_at:
            time_to_pr_seconds = max(
                0.0,
                (_parse_dt(pr_created_at) - _parse_dt(receipt.created_at)).total_seconds(),
            )
    except (TypeError, ValueError):
        pass

    metadata = dict(existing.metadata if existing else {})
    metadata.update(
        {
            "status": "merged",
            "merge_commit_sha": merge_commit_sha or metadata.get("merge_commit_sha"),
            "merged_at": merged_at,
            "receipt_outcome": receipt.outcome or None,
        }
    )
    collector.record_lane(
        LaneTelemetryRecord(
            lane_kind="supervisor_work_order",
            lane_id=lane_id,
            run_id=run_id or (existing.run_id if existing else ""),
            task_id=(existing.task_id if existing else "") or task_key or work_order_id,
            work_order_id=work_order_id or (existing.work_order_id if existing else ""),
            terminal_outcome=terminal_outcome,
            worker_outcome=(existing.worker_outcome if existing else "") or "",
            deliverable_type=deliverable_type,
            receipt_id=receipt.receipt_id or (existing.receipt_id if existing else ""),
            human_intervention_required=False,
            duration_seconds=existing.duration_seconds if existing else 0.0,
            pr_url=receipt.pr_url or (existing.pr_url if existing else ""),
            pr_number=receipt.pr_number
            if receipt.pr_number is not None
            else (existing.pr_number if existing else None),
            merge_ref=merge_commit_sha or (existing.merge_ref if existing else ""),
            merged_at=merged_at,
            time_to_pr_seconds=time_to_pr_seconds,
            time_to_merge_seconds=time_to_merge_seconds,
            false_success_candidate=False
            if deliverable_type
            else bool(existing.false_success_candidate if existing else False),
            timestamp=existing.timestamp if existing else _utcnow().timestamp(),
            metadata=metadata,
        )
    )
