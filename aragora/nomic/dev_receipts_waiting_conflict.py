"""Waiting-conflict archive and rehabilitation passes for dev-coordination work orders.

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

_SUPERSEDED_WAITING_CONFLICT_ARCHIVE_GRACE_HOURS = (
    _dev._SUPERSEDED_WAITING_CONFLICT_ARCHIVE_GRACE_HOURS
)
_backfill_work_order_blocker_metadata = _dev._backfill_work_order_blocker_metadata
_blocking_waiting_conflict_siblings = _dev._blocking_waiting_conflict_siblings
_canonical_work_order_scope_key = _dev._canonical_work_order_scope_key
_containing_waiting_conflict_priority = _dev._containing_waiting_conflict_priority
_developer_task_blockers = _dev._developer_task_blockers
_duplicate_branch_deliverable_priority = _dev._duplicate_branch_deliverable_priority
_duplicate_waiting_conflict_group_key = _dev._duplicate_waiting_conflict_group_key
_duplicate_waiting_conflict_priority = _dev._duplicate_waiting_conflict_priority
_narrow_waiting_conflict_scope_from_explicit_paths = (
    _dev._narrow_waiting_conflict_scope_from_explicit_paths
)
_optional_text = _dev._optional_text
_superseded_waiting_conflict_group_key = _dev._superseded_waiting_conflict_group_key
_utcnow = _dev._utcnow
_work_order_has_concrete_deliverable = _dev._work_order_has_concrete_deliverable
_work_order_is_broad_explicit_pytest_umbrella = _dev._work_order_is_broad_explicit_pytest_umbrella
_work_order_is_duplicate_waiting_conflict_candidate = (
    _dev._work_order_is_duplicate_waiting_conflict_candidate
)
_work_order_is_specific_pytest_child = _dev._work_order_is_specific_pytest_child
_work_order_scope_contains = _dev._work_order_scope_contains
_work_order_scope_patterns = _dev._work_order_scope_patterns
_work_order_should_archive_superseded_waiting_conflict = (
    _dev._work_order_should_archive_superseded_waiting_conflict
)
_work_order_should_rehabilitate_narrowed_waiting_conflict = (
    _dev._work_order_should_rehabilitate_narrowed_waiting_conflict
)
_work_orders_overlap_by_scope = _dev._work_orders_overlap_by_scope


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
