"""Worker-type circuit breakers and stale worker-state helpers for the swarm supervisor.

Like ``aragora.swarm.supervisor_workers``, these are module-level functions that
take the supervisor as their first argument and are reached through
``SwarmSupervisor`` delegates. ``supervisor_workers`` re-exports every name here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aragora.nomic.dev_coordination import LeaseStatus
from aragora.swarm import supervisor as _supervisor
from aragora.swarm.worker_launcher import WorkerLauncher

UTC = _supervisor.UTC
logger = _supervisor.logger
DEFAULT_BREAKER_FAILURE_THRESHOLD = _supervisor.DEFAULT_BREAKER_FAILURE_THRESHOLD
DEFAULT_BREAKER_RESET_TIMEOUT_SECONDS = _supervisor.DEFAULT_BREAKER_RESET_TIMEOUT_SECONDS
SESSION_LOCK_FILES = _supervisor.SESSION_LOCK_FILES
WORKER_TYPE_CIRCUIT_BREAKERS_KEY = _supervisor.WORKER_TYPE_CIRCUIT_BREAKERS_KEY
WORKER_TYPE_CIRCUIT_BREAKER_POLICY_KEY = _supervisor.WORKER_TYPE_CIRCUIT_BREAKER_POLICY_KEY


def _persist_terminal_blocker_evidence(item: dict[str, Any]) -> str | None:
    try:
        from aragora.swarm.supervisor_probes import (
            _derive_blocker_evidence,
            _persist_blocker_evidence,
        )

        evidence = _derive_blocker_evidence(item)
        _persist_blocker_evidence(item, evidence)
        return evidence or None
    except Exception:  # noqa: BLE001 - best-effort evidence write must not block the terminal transition
        logger.debug("Blocker evidence persistence skipped", exc_info=True)
        return None


def _dispatch_failure_reason(exc: Exception) -> str:
    message = str(exc).strip().lower()
    if "cli not found" in message or "not found" in message:
        return "agent_unavailable"
    return "agent_launch_failed"


def _worker_type_circuit_breaker_policy(self, metadata: dict[str, Any]) -> dict[str, Any]:
    payload = dict(metadata.get(WORKER_TYPE_CIRCUIT_BREAKER_POLICY_KEY) or {})
    try:
        failure_threshold = max(
            1,
            int(payload.get("failure_threshold", DEFAULT_BREAKER_FAILURE_THRESHOLD)),
        )
    except (TypeError, ValueError):
        failure_threshold = DEFAULT_BREAKER_FAILURE_THRESHOLD
    try:
        reset_timeout_seconds = max(
            1.0,
            float(
                payload.get(
                    "reset_timeout_seconds",
                    DEFAULT_BREAKER_RESET_TIMEOUT_SECONDS,
                )
            ),
        )
    except (TypeError, ValueError):
        reset_timeout_seconds = DEFAULT_BREAKER_RESET_TIMEOUT_SECONDS
    return {
        "failure_threshold": failure_threshold,
        "reset_timeout_seconds": reset_timeout_seconds,
    }


def _worker_type_circuit_breakers(
    self,
    metadata: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    policy = self._worker_type_circuit_breaker_policy(metadata)
    raw_breakers = dict(metadata.get(WORKER_TYPE_CIRCUIT_BREAKERS_KEY) or {})
    normalized: dict[str, dict[str, Any]] = {}

    for raw_worker_type, raw_entry in raw_breakers.items():
        worker_type = str(raw_worker_type).strip().lower()
        if not worker_type:
            continue
        entry = self._default_worker_type_circuit_breaker(policy)
        payload = dict(raw_entry or {})
        entry["status"] = str(payload.get("status", entry["status"])).strip().lower() or "closed"
        if entry["status"] not in {"open", "closed"}:
            entry["status"] = "closed"
        try:
            entry["failure_count"] = max(0, int(payload.get("failure_count", 0) or 0))
        except (TypeError, ValueError):
            entry["failure_count"] = 0
        try:
            entry["trip_count"] = max(0, int(payload.get("trip_count", 0) or 0))
        except (TypeError, ValueError):
            entry["trip_count"] = 0
        entry["last_failure_reason"] = str(payload.get("last_failure_reason", "")).strip()
        entry["last_failure_detail"] = str(payload.get("last_failure_detail", "")).strip()[:1000]
        entry["last_failure_at"] = self._normalized_timestamp(payload.get("last_failure_at"))
        entry["opened_at"] = self._normalized_timestamp(payload.get("opened_at"))
        blocked_until = self._normalized_timestamp(payload.get("blocked_until"))
        if entry["status"] == "open" and not blocked_until and entry["opened_at"]:
            opened_at = self._parse_timestamp(entry["opened_at"])
            if opened_at is not None:
                blocked_until = (
                    opened_at + timedelta(seconds=entry["reset_timeout_seconds"])
                ).isoformat()
        entry["blocked_until"] = blocked_until if entry["status"] == "open" else None
        entry["last_reset_at"] = self._normalized_timestamp(payload.get("last_reset_at"))
        normalized[worker_type] = entry

    return normalized


def _worker_type_circuit_breaker_metadata(
    self,
    metadata: dict[str, Any],
    circuit_breakers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    policy = self._worker_type_circuit_breaker_policy(metadata)
    normalized_breakers = {
        worker_type: dict(entry) for worker_type, entry in sorted(circuit_breakers.items())
    }
    return {
        **dict(metadata),
        WORKER_TYPE_CIRCUIT_BREAKER_POLICY_KEY: policy,
        WORKER_TYPE_CIRCUIT_BREAKERS_KEY: normalized_breakers,
    }


def _default_worker_type_circuit_breaker(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "closed",
        "failure_count": 0,
        "failure_threshold": int(policy["failure_threshold"]),
        "reset_timeout_seconds": float(policy["reset_timeout_seconds"]),
        "opened_at": None,
        "blocked_until": None,
        "last_failure_at": None,
        "last_failure_reason": "",
        "last_failure_detail": "",
        "trip_count": 0,
        "last_reset_at": None,
    }


def _normalized_timestamp(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text


def _worker_type_circuit_breaker_is_open(
    circuit_breakers: dict[str, dict[str, Any]],
    worker_type: str,
) -> bool:
    entry = circuit_breakers.get(str(worker_type).strip().lower()) or {}
    return str(entry.get("status", "")).strip().lower() == "open"


def _worker_type_circuit_breaker_detail(
    self,
    worker_type: str,
    breaker: dict[str, Any],
) -> str:
    detail = f"{worker_type} breaker open"
    blocked_until = str(breaker.get("blocked_until", "")).strip()
    if blocked_until:
        detail += f" until {blocked_until}"
    last_reason = str(breaker.get("last_failure_reason", "")).strip()
    if last_reason:
        detail += f" after {last_reason}"
    return detail


def _record_worker_type_failure(
    self,
    circuit_breakers: dict[str, dict[str, Any]],
    worker_type: str,
    *,
    reason: str,
    detail: str,
    open_immediately: bool = False,
    policy: dict[str, Any] | None = None,
) -> None:
    normalized_worker_type = str(worker_type).strip().lower()
    if not normalized_worker_type:
        return
    entry = circuit_breakers.get(normalized_worker_type)
    if entry is None:
        entry = self._default_worker_type_circuit_breaker(
            policy
            or {
                "failure_threshold": DEFAULT_BREAKER_FAILURE_THRESHOLD,
                "reset_timeout_seconds": DEFAULT_BREAKER_RESET_TIMEOUT_SECONDS,
            }
        )
        circuit_breakers[normalized_worker_type] = entry

    now = datetime.now(UTC)
    threshold = max(1, int(entry.get("failure_threshold", DEFAULT_BREAKER_FAILURE_THRESHOLD)))
    reset_timeout_seconds = max(
        1.0,
        float(entry.get("reset_timeout_seconds", DEFAULT_BREAKER_RESET_TIMEOUT_SECONDS)),
    )
    was_open = str(entry.get("status", "")).strip().lower() == "open"
    failure_count = threshold if open_immediately else int(entry.get("failure_count", 0)) + 1

    entry["failure_count"] = max(failure_count, threshold if open_immediately else failure_count)
    entry["last_failure_at"] = now.isoformat()
    entry["last_failure_reason"] = str(reason).strip()
    entry["last_failure_detail"] = str(detail).strip()[:1000]

    if open_immediately or entry["failure_count"] >= threshold:
        entry["status"] = "open"
        if not was_open:
            entry["trip_count"] = int(entry.get("trip_count", 0) or 0) + 1
            entry["opened_at"] = now.isoformat()
        elif not entry.get("opened_at"):
            entry["opened_at"] = now.isoformat()
        entry["blocked_until"] = (now + timedelta(seconds=reset_timeout_seconds)).isoformat()
        return

    entry["status"] = "closed"
    entry["opened_at"] = None
    entry["blocked_until"] = None


def _record_worker_type_success(
    self,
    circuit_breakers: dict[str, dict[str, Any]],
    worker_type: str,
) -> None:
    normalized_worker_type = str(worker_type).strip().lower()
    if not normalized_worker_type:
        return
    entry = circuit_breakers.get(normalized_worker_type)
    if entry is None:
        return
    if str(entry.get("status", "")).strip().lower() == "open":
        return
    if (
        int(entry.get("failure_count", 0) or 0) == 0
        and not entry.get("opened_at")
        and not entry.get("blocked_until")
    ):
        return
    self._reset_worker_type_circuit_breaker_entry(
        circuit_breakers,
        normalized_worker_type,
    )


def _reset_worker_type_circuit_breaker_entry(
    self,
    circuit_breakers: dict[str, dict[str, Any]],
    worker_type: str,
    *,
    now: datetime | None = None,
) -> None:
    normalized_worker_type = str(worker_type).strip().lower()
    if not normalized_worker_type:
        return
    entry = circuit_breakers.get(normalized_worker_type)
    if entry is None:
        return
    reset_at = (now or datetime.now(UTC)).isoformat()
    entry["status"] = "closed"
    entry["failure_count"] = 0
    entry["opened_at"] = None
    entry["blocked_until"] = None
    entry["last_reset_at"] = reset_at


def _expire_worker_type_circuit_breakers(
    self,
    circuit_breakers: dict[str, dict[str, Any]],
) -> None:
    now = datetime.now(UTC)
    for worker_type, entry in circuit_breakers.items():
        if str(entry.get("status", "")).strip().lower() != "open":
            continue
        blocked_until = self._parse_timestamp(entry.get("blocked_until"))
        if blocked_until is None:
            opened_at = self._parse_timestamp(entry.get("opened_at"))
            if opened_at is not None:
                blocked_until = opened_at + timedelta(
                    seconds=float(
                        entry.get(
                            "reset_timeout_seconds",
                            DEFAULT_BREAKER_RESET_TIMEOUT_SECONDS,
                        )
                    )
                )
                entry["blocked_until"] = blocked_until.isoformat()
        if blocked_until is None:
            continue
        if now >= blocked_until:
            self._reset_worker_type_circuit_breaker_entry(
                circuit_breakers,
                worker_type,
                now=now,
            )


def _mark_worker_type_blocked(
    self,
    item: dict[str, Any],
    *,
    worker_type: str,
    detail: str,
) -> None:
    self._clear_stale_prelaunch_deliverable_state(item)
    metadata = dict(item.get("metadata") or {})
    metadata.update(
        {
            "last_failure_reason": "worker_type_blocked",
            "last_failure_detail": str(detail).strip()[:1000],
            "blocked_worker_type": str(worker_type).strip().lower(),
            "reuse_existing_worktree": True,
        }
    )
    item["metadata"] = metadata
    self._mark_needs_human(
        item,
        f"worker dispatch blocked: {detail}",
        failure_reason="worker_type_blocked",
    )
    _persist_terminal_blocker_evidence(item)
    self._release_terminal_lease(item)
    item.pop("lease_id", None)
    item.pop("owner_session_id", None)


def _mark_dispatch_failed(item: dict[str, Any], reason: str) -> None:
    """Persist a pre-launch failure without carrying stale deliverable state."""
    item["status"] = "dispatch_failed"
    item["review_status"] = "pending"
    item["dispatch_error"] = str(reason)
    for key in (
        "lease_id",
        "owner_session_id",
        "resource_error",
        "conflicts",
        "receipt_id",
        "confidence",
        "worker_outcome",
        "completed_at",
        "exit_code",
        "pid",
        "initial_head",
        "head_sha",
        "commit_shas",
        "changed_paths",
        "diff",
        "diff_lines",
        "stdout_tail",
        "stderr_tail",
        "tests_run",
        "verification_results",
        "merge_gate",
        "verification_missing_reason",
        "pr_url",
        "adopted_pr",
        "scope_violation",
        "dispatched_at",
        "failure_reason",
        "blocking_question",
        "blocker",
        "blocker_evidence",
        "last_observed_at",
        "last_progress_at",
        "first_output_at",
        "last_output_at",
        "progress_fingerprint",
        "output_fingerprint",
    ):
        item.pop(key, None)
    item.pop("blockers", None)
    metadata = dict(item.get("metadata") or {})
    if "blocker_evidence" in metadata:
        metadata.pop("blocker_evidence", None)
        item["metadata"] = metadata


def _clear_stale_prelaunch_deliverable_state(item: dict[str, Any]) -> None:
    """Drop stale completion and wait-state metadata before a pre-launch blocker."""
    for key in (
        "dispatch_error",
        "resource_error",
        "failure_reason",
        "blocking_question",
        "blocker",
        "blocker_evidence",
        "conflicts",
        "receipt_id",
        "confidence",
        "worker_outcome",
        "completed_at",
        "exit_code",
        "head_sha",
        "commit_shas",
        "changed_paths",
        "diff",
        "diff_lines",
        "stdout_tail",
        "stderr_tail",
        "tests_run",
        "verification_results",
        "merge_gate",
        "verification_missing_reason",
        "pr_url",
        "adopted_pr",
        "scope_violation",
    ):
        item.pop(key, None)
    item.pop("blockers", None)
    metadata = dict(item.get("metadata") or {})
    if "blocker_evidence" in metadata:
        metadata.pop("blocker_evidence", None)
        item["metadata"] = metadata


def _clear_stale_runtime_deliverable_state(item: dict[str, Any]) -> None:
    """Drop stale deliverable metadata while preserving runtime log evidence."""
    for key in (
        "receipt_id",
        "confidence",
        "worker_outcome",
        "completed_at",
        "exit_code",
        "head_sha",
        "commit_shas",
        "changed_paths",
        "diff",
        "diff_lines",
        "tests_run",
        "verification_results",
        "merge_gate",
        "verification_missing_reason",
        "pr_url",
        "adopted_pr",
        "resource_error",
        "conflicts",
        "blockers",
        "blocker_evidence",
        "scope_violation",
    ):
        item.pop(key, None)
    metadata = dict(item.get("metadata") or {})
    if "blocker_evidence" in metadata:
        metadata.pop("blocker_evidence", None)
        item["metadata"] = metadata


def _release_orphaned_conflict_leases(self, conflicts: list[dict[str, Any]]) -> int:
    released = 0
    for conflict in conflicts:
        if str(conflict.get("source", "lease")).strip() not in {"lease", ""}:
            continue
        lease_id = str(conflict.get("lease_id", "")).strip()
        worktree_path = str(conflict.get("worktree_path", "")).strip()
        if not lease_id or not worktree_path:
            continue
        orphaned_reason = self._orphaned_conflict_reason(worktree_path)
        if not orphaned_reason:
            continue
        self.store.release_lease(lease_id, status=LeaseStatus.RELEASED)
        logger.info(
            "released_orphaned_conflict_lease lease_id=%s reason=%s worktree=%s",
            lease_id,
            orphaned_reason,
            worktree_path,
        )
        released += 1
    return released


def _orphaned_conflict_reason(self, worktree_path: str) -> str | None:
    path = Path(worktree_path)
    if not path.exists():
        return "missing_worktree"

    lock_state = self._session_lock_state(path)
    if lock_state == "active":
        return None
    if lock_state == "stale":
        return "dead_session_lock"

    session_meta = WorkerLauncher._read_session_meta(str(path))
    if session_meta:
        if str(session_meta.get("ended_at", "")).strip():
            return "session_ended"
        pid = WorkerLauncher._normalized_pid(session_meta.get("pid"))
        if pid is None:
            if self._is_managed_worktree(path):
                return "managed_worktree_without_active_session"
            return None
        if WorkerLauncher._is_pid_running(pid):
            return None
        return "dead_session_pid"

    if self._is_managed_worktree(path):
        return "managed_worktree_without_active_session"
    return None


def _is_managed_worktree(self, path: Path) -> bool:
    managed_root = (self.repo_root / ".worktrees").resolve()
    try:
        return path.resolve().is_relative_to(managed_root)
    except ValueError:
        return False


def _session_lock_state(cls, worktree_path: Path) -> str:
    found_lock = False
    for lock_name in SESSION_LOCK_FILES:
        lock_path = worktree_path / lock_name
        if not lock_path.exists():
            continue
        found_lock = True
        try:
            pids = cls._parse_session_lock_pids(lock_path)
        except OSError:
            return "active"
        if not pids:
            return "active"
        if any(WorkerLauncher._is_pid_running(pid) for pid in pids):
            return "active"
    return "stale" if found_lock else "missing"


def _parse_session_lock_pids(lock_path: Path) -> list[int]:
    raw = lock_path.read_text(encoding="utf-8")
    pids: list[int] = []
    for line in raw.splitlines():
        entry = line.strip()
        if "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        if key.strip() not in {"pid", "ppid"}:
            continue
        value = value.strip()
        if value.isdigit():
            pids.append(int(value))
    return pids


def _is_resource_constraint_error(exc: Exception) -> bool:
    lowered = str(exc).lower()
    return "no space left on device" in lowered or "disk full" in lowered


def _alternate_agent(agent: str | None) -> str | None:
    value = str(agent or "").strip().lower()
    if value == "claude":
        return "codex"
    if value == "codex":
        return "claude"
    return None


async def _kill_worker(self, item: dict[str, Any]) -> None:
    """Kill a running worker process by PID."""
    import signal

    if "pid" not in item:
        return
    pid = WorkerLauncher._normalized_pid(item.get("pid"))
    if pid is None:
        item.pop("pid", None)
        return
    try:
        import os as _os

        _os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    item.pop("pid", None)
