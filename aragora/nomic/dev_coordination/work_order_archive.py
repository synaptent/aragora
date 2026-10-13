"""Work-order archive predicates for the dev-coordination store.

Decides when an open work order is reaped, failed, scope-violating, a clean
exit without a deliverable, stuck in leasing or superseded, and so should be
archived. Split out of :mod:`aragora.nomic.dev_coordination.core`, which
re-imports every name here, so ``core._work_order_should_archive_reaped_no_receipt``,
the package-level attribute fallthrough and the ``aragora.nomic.dev_receipts``
aliases keep resolving to these objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aragora.nomic.dev_coordination.models import LeaseStatus
from aragora.nomic.dev_coordination.utils import _parse_dt, _utcnow
from aragora.nomic.dev_coordination.work_order_overlap import (
    _developer_task_updated_at,
    _optional_text,
    _work_order_has_concrete_deliverable,
)

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
_REAPED_NO_RECEIPT_BLOCKERS = {"stale_lease_reaped", "expired_lease_reaped"}


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


def _work_order_receipt_outcome(work_order: dict[str, Any]) -> str:
    if _optional_text(work_order.get("adopted_pr")):
        return "pr_adopted"
    if _work_order_has_concrete_deliverable(work_order):
        return "deliverable_created"
    return "clean_exit_no_deliverable"
