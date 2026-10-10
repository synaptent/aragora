"""Needs-human and waiting-state marking for ``SwarmSupervisor`` work orders.

``SwarmSupervisor`` (``aragora.swarm.supervisor``) inherits these helpers: they move a
work order to ``needs_human``, ``waiting_conflict`` or ``waiting_resource`` with a
failure reason and blocking question, and clear those states again. Import the
supervisor from ``aragora.swarm.supervisor``.
"""

from __future__ import annotations

from typing import Any


class SwarmSupervisorWaitingStateMixin:
    """Needs-human and waiting-state helpers inherited by ``SwarmSupervisor``."""

    @staticmethod
    def _default_blocking_question(reason_code: str) -> str:
        mapping = {
            "waiting_conflict": (
                "Which overlapping lane should finish, be discarded, or be split before this task can proceed?"
            ),
            "waiting_resource": (
                "Which capacity or environment constraint must be resolved before this lane can proceed?"
            ),
            "clean_exit_no_deliverable": (
                "What concrete branch, commit, or PR should this lane produce before rerunning?"
            ),
            "merge_gate_failed": (
                "Which required verification or acceptance check must pass before approval?"
            ),
            "missing_verification_plan": (
                "Which verification command or acceptance check should be added before rerunning?"
            ),
            "scope_violation": (
                "Which files should stay in scope, or should this lane be split before rerunning?"
            ),
            "worker_exited_without_receipt": (
                "Should this lane be rerun, or recovered manually from the existing worktree?"
            ),
            "worker_no_progress_timeout": (
                "Should this stalled lane be rerun, split, or investigated in its current worktree?"
            ),
            "worker_timeout_with_salvage": (
                "Should the recovered timed-out deliverable be adopted, amended, or rerun before integration?"
            ),
            "worker_timeout_no_deliverable": (
                "Should this timed-out lane be rerun, split, or investigated before retrying?"
            ),
            "worker_crash_with_salvage": (
                "Should the recovered crashed deliverable be adopted, amended, or rerun before integration?"
            ),
            "worker_crash": (
                "Should this crashed lane be rerun, reassigned, or investigated before retrying?"
            ),
            "worker_type_blocked": (
                "Which worker type or capacity issue must be resolved before rerunning this lane?"
            ),
            "work_order_leasing_failed": (
                "What missing environment, resource, or policy input must be resolved first?"
            ),
        }
        return mapping.get(
            reason_code,
            "What human input is required before rerunning this lane?",
        )

    @classmethod
    def _infer_failure_reason(cls, item: dict[str, Any], reason: str) -> str:
        merge_gate = item.get("merge_gate")
        if isinstance(merge_gate, dict):
            missing = str(merge_gate.get("verification_missing_reason", "")).strip()
            if missing:
                return missing
        lowered = str(reason or "").strip().lower()
        if "scope" in lowered and "ownership" in lowered:
            return "scope_violation"
        if "without receipt or exit marker" in lowered:
            return "worker_exited_without_receipt"
        if "no-progress timeout" in lowered:
            return "worker_no_progress_timeout"
        if "recoverable deliverable" in lowered and "timed out" in lowered:
            return "worker_timeout_with_salvage"
        if "recoverable deliverable" in lowered and "non-zero" in lowered:
            return "worker_crash_with_salvage"
        if "timed out before producing a deliverable" in lowered:
            return "worker_timeout_no_deliverable"
        if "crashed before producing a deliverable" in lowered:
            return "worker_crash"
        if "no commits and no changed paths" in lowered or "no real deliverables" in lowered:
            return "clean_exit_no_deliverable"
        if "merge gate" in lowered:
            return "merge_gate_failed"
        if "dispatch blocked" in lowered:
            return "worker_type_blocked"
        return "needs_human"

    @classmethod
    def _mark_needs_human(
        cls,
        item: dict[str, Any],
        reason: str,
        *,
        failure_reason: str | None = None,
        blocking_question: str | None = None,
    ) -> None:
        item["status"] = "needs_human"
        item["review_status"] = "changes_requested"
        item["dispatch_error"] = reason
        normalized_reason = (
            str(failure_reason or cls._infer_failure_reason(item, reason)).strip() or "needs_human"
        )
        normalized_question = str(
            blocking_question or cls._default_blocking_question(normalized_reason)
        ).strip()
        item["failure_reason"] = normalized_reason
        item["blocking_question"] = normalized_question
        item["blocker"] = {
            "reason": normalized_reason,
            "question": normalized_question,
        }
        blockers = [str(value).strip() for value in item.get("blockers", []) if str(value).strip()]
        if reason not in blockers:
            blockers.append(reason)
        item["blockers"] = blockers
        item.pop("receipt_id", None)
        item.pop("confidence", None)
        item.pop("pid", None)

    @classmethod
    def _mark_waiting_conflict(
        cls,
        item: dict[str, Any],
        conflicts: list[dict[str, Any]],
    ) -> None:
        cls._clear_waiting_state(item)
        item["status"] = "waiting_conflict"
        item["conflicts"] = list(conflicts)
        item["failure_reason"] = "waiting_conflict"
        item["blocking_question"] = cls._default_blocking_question("waiting_conflict")
        item["blocker"] = {
            "reason": "waiting_conflict",
            "question": item["blocking_question"],
        }
        blockers: list[str] = []
        for conflict in conflicts:
            if not isinstance(conflict, dict):
                continue
            scope = (
                str(conflict.get("path", "")).strip()
                or ", ".join(
                    str(value).strip()
                    for value in (conflict.get("claimed_paths") or [])
                    if str(value).strip()
                )
                or ", ".join(
                    str(value).strip()
                    for value in (conflict.get("allowed_globs") or [])
                    if str(value).strip()
                )
            )
            if not scope:
                continue
            summary = f"scope already claimed: {scope}"
            if summary not in blockers:
                blockers.append(summary)
        if not blockers:
            blockers.append("waiting_conflict")
        item["blockers"] = blockers

    @classmethod
    def _mark_waiting_resource(cls, item: dict[str, Any], resource_error: str) -> None:
        """Persist a resource-blocked wait state with explicit blocker metadata."""
        cls._clear_waiting_state(item)
        normalized_error = str(resource_error).strip() or "waiting_resource"
        item["status"] = "waiting_resource"
        item["resource_error"] = normalized_error
        item["failure_reason"] = "waiting_resource"
        item["blocking_question"] = cls._default_blocking_question("waiting_resource")
        item["blocker"] = {
            "reason": "waiting_resource",
            "question": item["blocking_question"],
        }
        item["blockers"] = [normalized_error]

    @staticmethod
    def _clear_waiting_state(item: dict[str, Any]) -> None:
        """Drop stale lease, deliverable, and review state before waiting."""
        item["review_status"] = "pending"
        for key in (
            "lease_id",
            "owner_session_id",
            "branch",
            "worktree_path",
            "dispatch_error",
            "resource_error",
            "failure_reason",
            "blocking_question",
            "blocker",
            "conflicts",
            "receipt_id",
            "confidence",
            "worker_outcome",
            "completed_at",
            "exit_code",
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
            "pid",
            "dispatched_at",
            "last_observed_at",
            "last_progress_at",
            "first_output_at",
            "last_output_at",
            "progress_fingerprint",
            "output_fingerprint",
        ):
            item.pop(key, None)
        item.pop("blockers", None)
