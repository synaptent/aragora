"""Superseded and duplicate work-order archive passes for dev coordination.

Each function takes a ``DevCoordinationStore`` as ``self``. The store methods in
``aragora.nomic.dev_coordination.core`` import them lazily from
``aragora.nomic.dev_receipts``, which re-exports every function here.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .dev_coordination import core as _dev
else:
    # Same routing as ``dev_receipts``: ``core`` reaches these functions through
    # function-local imports, so a runtime edge into ``core`` would make the two
    # modules mutually dependent.
    from . import dev_coordination as _dev

_DUPLICATE_BRANCH_DELIVERABLE_ARCHIVE_GRACE_HOURS = (
    _dev._DUPLICATE_BRANCH_DELIVERABLE_ARCHIVE_GRACE_HOURS
)
_canonical_goal_key = _dev._canonical_goal_key
_canonical_work_order_scope_key = _dev._canonical_work_order_scope_key
_duplicate_branch_deliverable_priority = _dev._duplicate_branch_deliverable_priority
_duplicate_work_order_leasing_failed_priority = _dev._duplicate_work_order_leasing_failed_priority
_live_overlap_sibling_priority = _dev._live_overlap_sibling_priority
_looks_like_helper_clean_exit_no_deliverable = _dev._looks_like_helper_clean_exit_no_deliverable
_optional_text = _dev._optional_text
_utcnow = _dev._utcnow
_work_order_has_concrete_deliverable = _dev._work_order_has_concrete_deliverable
_work_order_is_duplicate_work_order_leasing_failed_candidate = (
    _dev._work_order_is_duplicate_work_order_leasing_failed_candidate
)
_work_order_is_live_overlap_sibling = _dev._work_order_is_live_overlap_sibling
_work_order_should_archive_duplicate_branch_deliverable = (
    _dev._work_order_should_archive_duplicate_branch_deliverable
)
_work_order_should_archive_superseded_clean_exit_no_deliverable = (
    _dev._work_order_should_archive_superseded_clean_exit_no_deliverable
)
_work_order_should_archive_superseded_stale_lease_reaped = (
    _dev._work_order_should_archive_superseded_stale_lease_reaped
)
_work_orders_overlap_by_scope = _dev._work_orders_overlap_by_scope


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
