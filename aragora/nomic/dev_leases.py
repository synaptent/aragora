"""Lease management helpers for development coordination."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .dev_coordination import core as _dev
else:
    # Runtime access goes through the package facade (PEP 562 fall-through to
    # ``core``) because ``core`` delegates lease operations back to this module.
    from . import dev_coordination as _dev
from .dev_coordination.models import LeaseConflictError, LeaseStatus, WorkLease

_claims_overlap = _dev._claims_overlap
_json_dump = _dev._json_dump
_json_loads = _dev._json_loads
_normalize_claim = _dev._normalize_claim
_parse_dt = _dev._parse_dt
_path_matches_glob = _dev._path_matches_glob
_safe_kill_probe = _dev._safe_kill_probe
_utcnow = _dev._utcnow


def _fleet_claim_overlaps_requested_scope(
    fleet_claim_path: str,
    requested_globs: list[str],
    requested_paths: list[str],
) -> bool:
    """Return whether an existing fleet path claim conflicts with a requested lease."""

    return _claims_overlap([fleet_claim_path], requested_globs, requested_paths)


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


def list_leases(
    self,
    *,
    statuses: list[str] | None = None,
    limit: int | None = 500,
) -> list[WorkLease]:
    query = "SELECT * FROM leases ORDER BY updated_at DESC"
    params: tuple[Any, ...] = ()
    if isinstance(limit, int) and limit > 0:
        query += " LIMIT ?"
        params = (limit,)
    conn = self._connect()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    leases = [WorkLease.from_row(row) for row in rows]
    if statuses is None:
        return leases
    allowed = set(statuses)
    return [item for item in leases if item.status in allowed]


def reap_expired_leases(self) -> list[WorkLease]:
    now = _utcnow()
    conn = self._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM leases WHERE status = ?",
            (LeaseStatus.ACTIVE.value,),
        ).fetchall()
        expired = [WorkLease.from_row(row) for row in rows if _parse_dt(row["expires_at"]) <= now]
        for lease in expired:
            conn.execute(
                "UPDATE leases SET status = ?, updated_at = ? WHERE lease_id = ?",
                (LeaseStatus.EXPIRED.value, now.isoformat(), lease.lease_id),
            )
        conn.commit()
    finally:
        conn.close()

    for lease in expired:
        self._release_fleet_claims_for_lease(lease)
        self._publish(
            "task_expired",
            track=lease.branch,
            data={
                "lease_id": lease.lease_id,
                "task_id": lease.task_id,
                "worktree_path": lease.worktree_path,
            },
        )
        self._sync_supervisor_run_from_lease(
            lease.metadata,
            update={"status": "needs_human", "failure_reason": "expired_lease_reaped"},
        )
    self.backfill_missing_completion_receipts()
    self.backfill_missing_blocker_metadata()
    self.archive_reaped_no_receipt_work_orders()
    self.archive_scope_violation_no_deliverable_work_orders()
    self.archive_failed_no_deliverable_work_orders()
    self.archive_terminal_dependency_failure_work_orders()
    self.archive_clean_exit_no_deliverable_work_orders()
    self.archive_work_order_leasing_failed_work_orders()
    self.archive_worker_type_blocked_work_orders()
    self.archive_duplicate_work_order_leasing_failed_work_orders()
    self.archive_duplicate_branch_deliverable_work_orders()
    self.archive_superseded_waiting_conflict_work_orders()
    self.archive_duplicate_waiting_conflict_work_orders()
    self.rehabilitate_narrowed_waiting_conflict_work_orders()
    return expired


def reap_stale_leases(
    self,
    *,
    stale_threshold_seconds: float = 1800.0,
) -> list[WorkLease]:
    """Release active leases whose worker process is dead.

    A lease is stale when its metadata ``worker_pid`` is no longer running,
    **or** no ``worker_pid`` is recorded and the lease has not been
    heartbeated within *stale_threshold_seconds* (default 30 min).

    Complements ``reap_expired_leases`` (TTL only) and the conflict-path
    reaping in ``SwarmSupervisor._release_orphaned_conflict_leases``.
    """
    now = _utcnow()
    conn = self._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM leases WHERE status = ?",
            (LeaseStatus.ACTIVE.value,),
        ).fetchall()
    finally:
        conn.close()

    stale: list[WorkLease] = []
    for row in rows:
        lease = WorkLease.from_row(row)
        if _parse_dt(lease.expires_at) <= now:
            continue  # reap_expired_leases handles TTL expiry.

        metadata = lease.metadata or {}
        raw_pid = metadata.get("worker_pid")

        if raw_pid is not None:
            probe = _safe_kill_probe(raw_pid)
            if probe is None or isinstance(probe, PermissionError):
                continue  # Process alive (or owned by another user).
        else:
            updated = _parse_dt(lease.updated_at)
            if (now - updated).total_seconds() < stale_threshold_seconds:
                continue

        stale.append(lease)

    if not stale:
        return stale

    conn = self._connect()
    try:
        for lease in stale:
            conn.execute(
                "UPDATE leases SET status = ?, updated_at = ? WHERE lease_id = ?",
                (LeaseStatus.EXPIRED.value, now.isoformat(), lease.lease_id),
            )
        conn.commit()
    finally:
        conn.close()

    for lease in stale:
        self._release_fleet_claims_for_lease(lease)
        reason = (
            "worker_pid_dead"
            if (lease.metadata or {}).get("worker_pid") is not None
            else "heartbeat_timeout"
        )
        self._publish(
            "lease_stale",
            track=lease.branch,
            data={
                "lease_id": lease.lease_id,
                "task_id": lease.task_id,
                "worktree_path": lease.worktree_path,
                "reason": reason,
            },
        )
        self._sync_supervisor_run_from_lease(
            lease.metadata,
            update={"status": "needs_human", "failure_reason": "stale_lease_reaped"},
        )

    self.backfill_missing_completion_receipts()
    self.backfill_missing_blocker_metadata()
    self.archive_reaped_no_receipt_work_orders()
    self.archive_scope_violation_no_deliverable_work_orders()
    self.archive_failed_no_deliverable_work_orders()
    self.archive_terminal_dependency_failure_work_orders()
    self.archive_clean_exit_no_deliverable_work_orders()
    self.archive_work_order_leasing_failed_work_orders()
    self.archive_worker_type_blocked_work_orders()
    self.archive_duplicate_work_order_leasing_failed_work_orders()
    self.archive_duplicate_branch_deliverable_work_orders()
    self.archive_superseded_waiting_conflict_work_orders()
    self.archive_duplicate_waiting_conflict_work_orders()
    self.rehabilitate_narrowed_waiting_conflict_work_orders()
    return stale


def find_conflicting_leases(
    self,
    *,
    allowed_globs: list[str],
    claimed_paths: list[str],
    owner_session_id: str | None = None,
    exclude_lease_id: str | None = None,
) -> list[dict[str, Any]]:
    self.fleet_store.reap_stale_claims()
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
        if not _fleet_claim_overlaps_requested_scope(path, normalized_globs, normalized_paths):
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
    normalized_globs = [_normalize_claim(item) for item in allowed_globs or [] if str(item).strip()]
    normalized_paths = [_normalize_claim(item) for item in claimed_paths or [] if str(item).strip()]
    self.reap_expired_leases()
    self.reap_stale_leases()
    self.fleet_store.reap_stale_claims()
    now = _utcnow()
    conn = self._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conflicts = self._find_conflicting_leases_locked(
            conn,
            allowed_globs=normalized_globs,
            claimed_paths=normalized_paths,
            owner_session_id=owner_session_id,
        )
        if conflicts and not allow_overlap:
            raise LeaseConflictError(conflicts)

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
    except LeaseConflictError:
        conn.rollback()
        self._publish(
            "conflict_detected",
            track=branch,
            data={
                "task_id": task_id,
                "worktree_path": worktree_path,
                "conflicts": conflicts,
            },
        )
        raise
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
    claim_paths = self._fleet_claim_paths(lease)
    if claim_paths:
        self.fleet_store.claim_paths(
            session_id=lease.owner_session_id,
            paths=claim_paths,
            branch=lease.branch,
            mode="exclusive",
        )
    self._sync_supervisor_run_from_lease(
        lease.metadata,
        update={
            "status": "leased",
            "lease_id": lease.lease_id,
            "owner_session_id": lease.owner_session_id,
            "branch": lease.branch,
            "worktree_path": lease.worktree_path,
            "target_agent": lease.owner_agent,
            "expected_tests": list(lease.expected_tests),
        },
    )
    return lease


def _find_conflicting_leases_locked(
    self,
    conn: sqlite3.Connection,
    *,
    allowed_globs: list[str],
    claimed_paths: list[str],
    owner_session_id: str | None = None,
    exclude_lease_id: str | None = None,
) -> list[dict[str, Any]]:
    normalized_globs = [_normalize_claim(item) for item in allowed_globs if str(item).strip()]
    normalized_paths = [_normalize_claim(item) for item in claimed_paths if str(item).strip()]
    conflicts: list[dict[str, Any]] = []
    now = _utcnow()
    rows = conn.execute("SELECT * FROM leases ORDER BY created_at ASC").fetchall()
    active_leases = [
        lease
        for lease in (WorkLease.from_row(row) for row in rows)
        if lease.status == LeaseStatus.ACTIVE.value and _parse_dt(lease.expires_at) > now
    ]
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
        if not _fleet_claim_overlaps_requested_scope(path, normalized_globs, normalized_paths):
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
                (_parse_dt(lease.expires_at) - _parse_dt(lease.updated_at)).total_seconds() / 3600,
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
    lease = WorkLease.from_row(row)
    claim_paths = self._fleet_claim_paths(lease)
    if claim_paths:
        self.fleet_store.claim_paths(
            session_id=lease.owner_session_id,
            paths=claim_paths,
            branch=lease.branch,
            mode="exclusive",
        )
    return lease


def persist_scope_violation(
    self,
    lease_id: str,
    *,
    changed_paths: list[str],
    violations: list[dict[str, Any]],
) -> None:
    """Write scope-violation metadata into a lease without releasing it.

    The lease remains active so that ``status_summary()`` — which scans
    ``list_active_leases()`` for ``last_scope_violation`` — can surface the
    violation to fleet/integrator views.  This mirrors the metadata write in
    ``record_completion()`` but is callable from the supervisor's early-kill
    path where a full completion receipt is not available.
    """
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        row = conn.execute(
            "SELECT metadata_json FROM leases WHERE lease_id = ?", (lease_id,)
        ).fetchone()
        if row is None:
            return  # Unknown lease — nothing to update
        metadata = {
            **_json_loads(row["metadata_json"], {}),
            "last_scope_violation": {
                "detected_at": now,
                "changed_paths": changed_paths,
                "violations": violations,
            },
        }
        conn.execute(
            "UPDATE leases SET updated_at = ?, metadata_json = ? WHERE lease_id = ?",
            (now, _json_dump(metadata), lease_id),
        )
        conn.commit()
    finally:
        conn.close()
    self._publish(
        "scope_violation_detected",
        track="",
        data={
            "lease_id": lease_id,
            "changed_paths": changed_paths,
            "violations": violations,
        },
    )


def update_lease_metadata(self, lease_id: str, updates: dict[str, Any]) -> None:
    """Merge *updates* into a lease's metadata JSON."""
    now = _utcnow().isoformat()
    conn = self._connect()
    try:
        row = conn.execute(
            "SELECT metadata_json FROM leases WHERE lease_id = ?", (lease_id,)
        ).fetchone()
        if row is None:
            return
        metadata = {**_json_loads(row["metadata_json"], {}), **updates}
        conn.execute(
            "UPDATE leases SET updated_at = ?, metadata_json = ? WHERE lease_id = ?",
            (now, _json_dump(metadata), lease_id),
        )
        conn.commit()
    finally:
        conn.close()


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
    self._release_fleet_claims_for_lease(lease)
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


def _validate_completion_scope(
    self,
    lease: WorkLease,
    *,
    changed_paths: list[str],
    owner_session_id: str,
    branch: str,
    require_session_ownership: bool = True,
) -> list[dict[str, Any]]:
    scope_patterns = list(dict.fromkeys([*lease.claimed_paths, *lease.allowed_globs]))
    protected_patterns = list(
        dict.fromkeys(
            _normalize_claim(item)
            for key in ("forbidden_paths", "forbidden_globs", "hot_paths", "hot_globs")
            for item in lease.metadata.get(key, [])
            if str(item).strip()
        )
    )
    violations: list[dict[str, Any]] = []

    if changed_paths and not scope_patterns:
        return [
            {
                "type": "undeclared_scope",
                "message": "Lease has no declared file scope for the recorded changes.",
                "paths": list(changed_paths),
            }
        ]

    for path in changed_paths:
        if scope_patterns and not any(
            _path_matches_glob(path, pattern) for pattern in scope_patterns
        ):
            violations.append(
                {
                    "type": "out_of_scope",
                    "path": path,
                    "allowed_scope": list(scope_patterns),
                }
            )
        if protected_patterns and any(
            _path_matches_glob(path, pattern) for pattern in protected_patterns
        ):
            violations.append(
                {
                    "type": "protected_path",
                    "path": path,
                    "protected_scope": list(protected_patterns),
                }
            )

    if require_session_ownership:
        audit = self.fleet_store.audit_session_paths(
            session_id=owner_session_id,
            paths=changed_paths,
            branch=branch,
        )
        for path in audit["unowned_paths"]:
            violations.append({"type": "unowned_path", "path": path})
        for conflict in audit["conflicts"]:
            violations.append(
                {
                    "type": "conflicting_claim",
                    "path": str(conflict.get("path", "")),
                    "conflicting_path": str(conflict.get("conflicting_path", "")),
                    "session_id": str(conflict.get("session_id", "")),
                    "branch": str(conflict.get("branch", "")),
                    "mode": str(conflict.get("mode", "")),
                }
            )
    return violations
