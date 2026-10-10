"""Requeue decisions for ``SwarmSupervisor`` work orders.

``SwarmSupervisor`` (``aragora.swarm.supervisor``) inherits these helpers: they decide
whether a stale, reaped, conflict-only, lease-failed, dependency-failed or
scope-violating work order goes back to the queue, and reset it for a clean attempt.
Import the supervisor from ``aragora.swarm.supervisor``.
"""

from __future__ import annotations

from typing import Any

from aragora.swarm.worker_launcher import WorkerLauncher, is_ignored_changed_path


class SwarmSupervisorRequeueMixin:
    """Work-order requeue predicates inherited by ``SwarmSupervisor``."""

    def _should_requeue_stale_work_order(
        self,
        item: dict[str, Any],
        active_leases: dict[str, Any],
    ) -> bool:
        status = str(item.get("status", "")).strip()
        if status not in {"leased", "dispatched"}:
            return False
        lease_id = str(item.get("lease_id", "")).strip()
        if not lease_id or lease_id in active_leases:
            return False
        raw_pid = item.get("pid")
        normalized_pid: int | None = None
        if raw_pid is not None and not isinstance(raw_pid, bool):
            try:
                normalized_pid = int(str(raw_pid))
            except ValueError:
                normalized_pid = None
        running = (
            normalized_pid is not None
            and normalized_pid > 0
            and WorkerLauncher._is_pid_running(normalized_pid)
        )
        return not running

    @staticmethod
    def _should_requeue_conflict_only_needs_human(item: dict[str, Any]) -> bool:
        if str(item.get("status", "")).strip() != "needs_human":
            return False
        if item.get("conflicts"):
            return False
        if str(item.get("worker_outcome", "")).strip():
            return False
        if str(item.get("dispatch_error", "")).strip():
            return False
        failure_reason = str(item.get("failure_reason", "")).strip()
        if failure_reason and failure_reason != "needs_human":
            return False
        default_question = "What human input is required before rerunning this lane?"
        blocking_question = str(item.get("blocking_question", "")).strip()
        if blocking_question and blocking_question != default_question:
            return False
        blocker = item.get("blocker")
        if isinstance(blocker, dict):
            blocker_reason = str(blocker.get("reason", "")).strip()
            blocker_question = str(blocker.get("question", "")).strip()
            if blocker_reason and blocker_reason != "needs_human":
                return False
            if blocker_question and blocker_question != default_question:
                return False
        blockers = [
            str(blocker_text).strip()
            for blocker_text in item.get("blockers", [])
            if str(blocker_text).strip()
        ]
        if blockers:
            return False
        return True

    @staticmethod
    def _should_requeue_reaped_needs_human(
        item: dict[str, Any],
        active_leases: dict[str, Any],
    ) -> bool:
        if str(item.get("status", "")).strip() != "needs_human":
            return False
        failure_reason = str(item.get("failure_reason", "")).strip().lower()
        if failure_reason not in {"stale_lease_reaped", "expired_lease_reaped"}:
            return False
        lease_id = str(item.get("lease_id", "")).strip()
        if lease_id and lease_id in active_leases:
            return False
        if str(item.get("receipt_id") or "").strip():
            return False
        if item.get("commit_shas") or item.get("changed_paths") or item.get("pr_url"):
            return False
        metadata = item.get("metadata")
        if isinstance(metadata, dict) and str(metadata.get("archived_due_to", "")).strip():
            return False
        return True

    @staticmethod
    def _should_requeue_recoverable_work_order_leasing_failed(
        item: dict[str, Any],
        active_leases: dict[str, Any],
    ) -> bool:
        status = str(item.get("status", "")).strip().lower()
        if status not in {"needs_human", "discarded"}:
            return False
        failure_reason = str(item.get("failure_reason", "")).strip().lower()
        metadata = item.get("metadata")
        archived_due_to = (
            str(metadata.get("archived_due_to", "")).strip().lower()
            if isinstance(metadata, dict)
            else ""
        )
        if (
            failure_reason != "work_order_leasing_failed"
            and archived_due_to != "work_order_leasing_failed"
        ):
            return False
        lease_id = str(item.get("lease_id", "")).strip()
        if lease_id and lease_id in active_leases:
            return False
        if str(item.get("receipt_id") or "").strip():
            return False
        if item.get("commit_shas") or item.get("changed_paths") or item.get("pr_url"):
            return False
        dispatch_error = str(item.get("dispatch_error", "")).strip().lower()
        if not dispatch_error:
            return False
        return (
            "autopilot ensure failed" in dispatch_error
            and "a branch named" in dispatch_error
            and "already exists" in dispatch_error
        )

    @staticmethod
    def _should_requeue_terminal_dependency_failure(
        item: dict[str, Any],
        work_orders: list[dict[str, Any]],
    ) -> bool:
        status = str(item.get("status", "")).strip().lower()
        if status not in {"needs_human", "discarded"}:
            return False
        failure_reason = str(item.get("failure_reason", "")).strip().lower()
        metadata = item.get("metadata")
        archived_due_to = (
            str(metadata.get("archived_due_to", "")).strip().lower()
            if isinstance(metadata, dict)
            else ""
        )
        if (
            failure_reason != "terminal_dependency_failure"
            and archived_due_to != "terminal_dependency_failure"
        ):
            return False
        dependency_id = ""
        if isinstance(metadata, dict):
            dependency_id = str(metadata.get("blocking_dependency_id", "")).strip()
        blocker = item.get("blocker")
        if not dependency_id and isinstance(blocker, dict):
            dependency_id = str(blocker.get("dependency_id", "")).strip()
        if not dependency_id:
            return False
        dependency_lookup: dict[str, dict[str, Any]] = {}
        for candidate in work_orders:
            if not isinstance(candidate, dict):
                continue
            for key in ("pipeline_task_id", "work_order_id", "task_key"):
                candidate_id = str(candidate.get(key, "")).strip()
                if candidate_id:
                    dependency_lookup[candidate_id] = candidate
        dependency = dependency_lookup.get(dependency_id)
        if not isinstance(dependency, dict):
            return False
        dependency_status = str(dependency.get("status", "")).strip().lower()
        return dependency_status not in {"discarded", "failed", "timed_out", "scope_violation"}

    @staticmethod
    def _should_requeue_ignorable_scope_violation(item: dict[str, Any]) -> bool:
        status = str(item.get("status", "")).strip().lower()
        if status not in {"scope_violation", "needs_human", "discarded"}:
            return False
        failure_reason = str(item.get("failure_reason", "")).strip().lower()
        metadata = item.get("metadata")
        archived_due_to = (
            str(metadata.get("archived_due_to", "")).strip().lower()
            if isinstance(metadata, dict)
            else ""
        )
        if failure_reason != "scope_violation" and archived_due_to != "scope_violation":
            return False
        if str(item.get("receipt_id") or "").strip():
            return False
        if item.get("commit_shas") or item.get("pr_url") or item.get("adopted_pr"):
            return False

        candidate_paths: set[str] = {
            str(path).strip() for path in item.get("changed_paths", []) if str(path).strip()
        }
        scope_violation = item.get("scope_violation")
        if isinstance(scope_violation, dict):
            for violation in scope_violation.get("violations", []) or []:
                if not isinstance(violation, dict):
                    continue
                path = str(violation.get("path", "")).strip()
                if path:
                    candidate_paths.add(path)
        if not candidate_paths:
            return False
        return all(is_ignored_changed_path(path) for path in candidate_paths)

    @staticmethod
    def _reset_work_order_for_requeue(item: dict[str, Any]) -> None:
        item["status"] = "queued"
        item["review_status"] = "pending"
        # Requeued lanes must start from a clean attempt state. Preserve only
        # dispatch inputs (scope/tests/agent hints), not terminal artifacts from
        # the dead or conflict-only attempt we are replacing.
        for key in (
            "lease_id",
            "owner_session_id",
            "worktree_path",
            "initial_head",
            "exit_code",
            "pid",
            "dispatched_at",
            "dispatch_error",
            "blocking_question",
            "failure_reason",
            "resource_error",
            "blocker",
            "conflicts",
            "receipt_id",
            "confidence",
            "worker_outcome",
            "completed_at",
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
        for key in (
            "archived_due_to",
            "archived_at",
            "archive_reason",
            "previous_status",
            "canonical_task_key",
            "canonical_work_order_id",
            "canonical_run_id",
            "blocking_dependency_id",
            "blocking_dependency_status",
            "blocking_dependency_reason",
        ):
            metadata.pop(key, None)
        if metadata:
            item["metadata"] = metadata
        else:
            item.pop("metadata", None)
