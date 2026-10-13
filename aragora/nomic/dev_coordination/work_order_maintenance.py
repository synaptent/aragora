"""Work-order maintenance and work-queue projection for :class:`DevCoordinationStore`.

``WorkOrderMaintenanceMixin`` holds the store's backfill, rehabilitation,
reclassification, archive, verification-sync and merge-gate replay entry points
(each delegates lazily to :mod:`aragora.nomic.dev_receipts`) and the projection
of open developer tasks and pending integration/salvage items into the global
work queue. Split out of :mod:`aragora.nomic.dev_coordination.core`;
``DevCoordinationStore`` inherits the mixin, and ``core`` re-imports the mixin and
the archive grace periods and status sets defined here, so ``core.<name>`` keeps
resolving to the same objects.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.nomic.global_work_queue import GlobalWorkQueue, WorkItem, WorkStatus

if TYPE_CHECKING:
    from aragora.nomic.dev_coordination.models import (
        DeveloperTask,
        IntegrationDecision,
        SalvageCandidate,
    )

_OPEN_SALVAGE_STATUSES = {"detected", "claimed"}
_DUPLICATE_BRANCH_DELIVERABLE_ARCHIVE_GRACE_HOURS = 24.0
_SUPERSEDED_WAITING_CONFLICT_ARCHIVE_GRACE_HOURS = 24.0
_CLEAN_EXIT_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS = 24.0
_FAILED_NO_DELIVERABLE_ARCHIVE_GRACE_HOURS = 24.0
_WORK_ORDER_LEASING_FAILED_ARCHIVE_GRACE_HOURS = 24.0
_WORKER_TYPE_BLOCKED_ARCHIVE_GRACE_HOURS = 24.0
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


class WorkOrderMaintenanceMixin:
    """Maintenance passes and queue projection; mixed into ``DevCoordinationStore``."""

    repo_root: Path

    if TYPE_CHECKING:

        def list_developer_tasks(
            self,
            *,
            open_only: bool = False,
            run_id: str | None = None,
            limit: int = 200,
        ) -> list[DeveloperTask]: ...

        def list_integration_decisions(
            self,
            *,
            only_pending: bool = False,
            receipt_id: str | None = None,
            limit: int | None = None,
        ) -> list[IntegrationDecision]: ...

        def list_salvage_candidates(
            self, statuses: list[str] | None = None
        ) -> list[SalvageCandidate]: ...

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
