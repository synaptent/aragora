"""Pins DevCoordinationStore's maintenance passes and queue projection to their mixin.

``WorkOrderMaintenanceMixin`` in
``aragora.nomic.dev_coordination.work_order_maintenance`` holds the backfill,
rehabilitation, reclassification, archive, verification-sync and merge-gate replay
entry points plus the work-queue projection. ``DevCoordinationStore`` inherits it,
and ``core``, the package and ``dev_receipts`` keep exposing the moved constants.
"""

from __future__ import annotations

import asyncio
import inspect
import subprocess
from pathlib import Path

import pytest

from aragora.nomic import dev_coordination, dev_receipts
from aragora.nomic.dev_coordination import core
from aragora.nomic.dev_coordination import work_order_maintenance as maintenance
from aragora.nomic.dev_coordination.core import DevCoordinationStore
from aragora.nomic.global_work_queue import GlobalWorkQueue

Mixin = maintenance.WorkOrderMaintenanceMixin

MOVED_METHODS = (
    "backfill_missing_blocker_metadata",
    "backfill_missing_verification_plans",
    "rehabilitate_docs_only_missing_verification_plan_work_orders",
    "rehabilitate_dependency_deferred_missing_verification_plan_work_orders",
    "rehabilitate_deliverable_backed_clean_exit_no_deliverable_work_orders",
    "reclassify_branch_snapshot_stale_review_work_orders",
    "reclassify_deliverable_changes_requested_work_orders",
    "archive_reaped_no_receipt_work_orders",
    "archive_scope_violation_no_deliverable_work_orders",
    "archive_failed_no_deliverable_work_orders",
    "archive_terminal_dependency_failure_work_orders",
    "archive_clean_exit_no_deliverable_work_orders",
    "archive_work_order_leasing_failed_work_orders",
    "archive_worker_type_blocked_work_orders",
    "archive_superseded_clean_exit_no_deliverable_work_orders",
    "archive_superseded_stale_lease_reaped_work_orders",
    "archive_duplicate_work_order_leasing_failed_work_orders",
    "archive_duplicate_branch_deliverable_work_orders",
    "archive_superseded_waiting_conflict_work_orders",
    "archive_duplicate_waiting_conflict_work_orders",
    "rehabilitate_narrowed_waiting_conflict_work_orders",
    "backfill_file_scope_from_changed_paths",
    "backfill_missing_completion_receipts",
    "_rehydrate_lease_scope_from_work_order",
    "_run_verification_commands_sync",
    "_resolve_verification_worktree",
    "_cleanup_verification_worktree",
    "_update_completion_receipt_verification_locked",
    "sync_completion_receipt_verification",
    "_replay_merge_gate_failures",
    "replay_missing_verification_for_merge_gate_failures",
    "replay_environment_blocked_merge_gate_failures",
    "replay_docs_only_merge_gate_failures",
    "replay_missing_required_merge_gate_failures",
    "replay_narrow_pytest_merge_gate_failures",
    "replay_targeted_merge_gate_failures",
    "reclassify_branch_stale_merge_gate_failures",
    "reconcile_merge_gate_failed_work_orders",
    "pending_work_items",
    "developer_task_work_items",
    "sync_developer_task_queue",
    "sync_pending_work_queue",
)

MOVED_CONSTANTS = (
    "_OPEN_SALVAGE_STATUSES",
    "_QUEUEABLE_DEVELOPER_TASK_STATUSES",
    "_DUPLICATE_BRANCH_DELIVERABLE_ARCHIVE_GRACE_HOURS",
    "_SUPERSEDED_WAITING_CONFLICT_ARCHIVE_GRACE_HOURS",
    "_CLEAN_EXIT_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS",
    "_FAILED_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS",
    "_WORK_ORDER_LEASING_FAILED_ARCHIVE_GRACE_HOURS",
    "_WORKER_TYPE_BLOCKED_ARCHIVE_GRACE_HOURS",
    "_REAPED_NO_RECEIPT_ARCHIVE_GRACE_HOURS",
)


def test_store_mro_puts_the_mixin_directly_after_the_store() -> None:
    assert DevCoordinationStore.__mro__ == (DevCoordinationStore, Mixin, object)
    assert core.WorkOrderMaintenanceMixin is Mixin
    assert dev_coordination.WorkOrderMaintenanceMixin is Mixin


@pytest.mark.parametrize("name", MOVED_METHODS)
def test_store_method_resolves_to_the_mixin(name: str) -> None:
    assert name not in DevCoordinationStore.__dict__
    assert name in Mixin.__dict__
    assert inspect.getattr_static(DevCoordinationStore, name) is Mixin.__dict__[name]
    func = getattr(DevCoordinationStore, name)
    assert func.__module__ == maintenance.__name__
    assert func.__qualname__ == f"WorkOrderMaintenanceMixin.{name}"


@pytest.mark.parametrize("name", MOVED_CONSTANTS)
def test_core_and_package_expose_the_moved_constant(name: str) -> None:
    value = getattr(maintenance, name)
    assert getattr(core, name) is value
    assert getattr(dev_coordination, name) is value


def test_dev_receipts_grace_period_aliases_match() -> None:
    assert dev_receipts._REAPED_NO_RECEIPT_ARCHIVE_GRACE_HOURS == (
        maintenance._REAPED_NO_RECEIPT_ARCHIVE_GRACE_HOURS
    )
    assert dev_receipts._WORKER_TYPE_BLOCKED_ARCHIVE_GRACE_HOURS == (
        maintenance._WORKER_TYPE_BLOCKED_ARCHIVE_GRACE_HOURS
    )


def test_empty_store_projects_nothing_into_the_queue(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    store = DevCoordinationStore(repo_root=tmp_path)
    queue = GlobalWorkQueue(storage_dir=tmp_path / ".work_queue")
    assert store.pending_work_items() == []
    assert store.developer_task_work_items() == []
    pending = asyncio.run(store.sync_pending_work_queue(queue))
    tasks = asyncio.run(store.sync_developer_task_queue(queue))
    assert pending["open_items"] == 0
    assert tasks["open_items"] == 0
    assert pending["created"] == tasks["created"] == 0
