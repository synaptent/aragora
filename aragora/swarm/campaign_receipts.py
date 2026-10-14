"""Campaign decision-receipt helpers.

Pure functions that derive receipt fields (phase, final status, review verdict, duration,
changed files, worker branches and commits, work-order snapshots, planner metadata and the
verification-missing reason) from a campaign project and its swarm run dictionary.
``aragora.swarm.campaign`` re-exports every name here, so importing from either module
yields the same function objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aragora.swarm.campaign_models import (
    CampaignProject,
    CampaignReviewStatus,
    CampaignRunOutcome,
    _optional_text,
)
from aragora.swarm.worker_launcher import MAX_WORKER_LOG_TAIL_CHARS, WorkerLauncher


def _derive_phase(campaign_id: str) -> str | None:
    cid = str(campaign_id or "").lower()
    for prefix, label in (
        ("phase0a", "0a"),
        ("phase0b", "0b"),
        ("phase1", "1"),
        ("phase2", "2"),
    ):
        if cid.startswith(prefix):
            return label
    return None


def _failure_classification_from_outcome(outcome: str | None) -> str | None:
    mapping = {
        CampaignRunOutcome.CRASH.value: "worker_crash",
        CampaignRunOutcome.TIMEOUT.value: "timeout",
        CampaignRunOutcome.STALLED.value: "stall",
        CampaignRunOutcome.BLOCKED.value: "stall",
        CampaignRunOutcome.NEEDS_HUMAN.value: "stall",
        CampaignRunOutcome.CLEAN_EXIT_NO_DELIVERABLE.value: "stall",
    }
    return mapping.get(str(outcome or ""))


def _receipt_final_status(project_status: str) -> str:
    return {
        "completed": "completed",
        "failed": "failed",
        "skipped": "failed",
        "stalled": "rejected",
        "blocked": "rejected",
    }.get(project_status, "failed")


def _receipt_review_verdict(review_status: str) -> str:
    return {
        CampaignReviewStatus.PASSED.value: "passed",
        CampaignReviewStatus.CHANGES_REQUESTED.value: "failed",
        CampaignReviewStatus.BLOCKED_NONREVIEWABLE.value: "failed",
        CampaignReviewStatus.PENDING.value: "skipped",
    }.get(review_status, "skipped")


def _duration_seconds_from_run(run_dict: dict[str, Any] | None) -> int | None:
    if not run_dict:
        return None
    for wo in run_dict.get("work_orders", []):
        if not isinstance(wo, dict):
            continue
        started = str(wo.get("started_at", "")).strip()
        ended = str(wo.get("completed_at", "")).strip()
        if started and ended:
            try:
                t_start = datetime.fromisoformat(started)
                t_end = datetime.fromisoformat(ended)
                return max(0, int((t_end - t_start).total_seconds()))
            except (ValueError, TypeError):
                continue
    return None


def _changed_files_from_run(run_dict: dict[str, Any] | None) -> list[str]:
    if not run_dict:
        return []
    paths: list[str] = []
    seen: set[str] = set()
    for wo in run_dict.get("work_orders", []):
        if not isinstance(wo, dict):
            continue
        for p in wo.get("changed_paths", []):
            text = str(p).strip()
            if text and text not in seen:
                seen.add(text)
                paths.append(text)
    return paths


def _tests_from_acceptance_criteria(acceptance_criteria: list[str]) -> list[str]:
    tests: list[str] = []
    for item in acceptance_criteria:
        text = str(item).strip()
        if text.startswith("python -m pytest") or text.startswith("pytest"):
            tests.append(text)
    return list(dict.fromkeys(tests))


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _worker_branches_from_run(
    project: CampaignProject, run_dict: dict[str, Any] | None
) -> list[str]:
    branches: list[str] = []
    if project.branch:
        branches.append(project.branch)
    if run_dict:
        for wo in run_dict.get("work_orders", []):
            if not isinstance(wo, dict):
                continue
            branch = str(wo.get("branch", "")).strip()
            if branch:
                branches.append(branch)
    return _ordered_unique(branches)


def _worker_commits_from_run(
    project: CampaignProject, run_dict: dict[str, Any] | None
) -> list[str]:
    commits: list[str] = [str(sha).strip() for sha in project.commit_shas if str(sha).strip()]
    if run_dict:
        for wo in run_dict.get("work_orders", []):
            if not isinstance(wo, dict):
                continue
            commits.extend(
                str(sha).strip() for sha in wo.get("commit_shas", []) if str(sha).strip()
            )
            head_sha = str(wo.get("head_sha", "")).strip()
            if head_sha:
                commits.append(head_sha)
    return _ordered_unique(commits)


def _worker_branch_from_run(
    project: CampaignProject, run_dict: dict[str, Any] | None
) -> str | None:
    branches = _worker_branches_from_run(project, run_dict)
    return branches[0] if branches else None


def _worker_commit_from_run(
    project: CampaignProject, run_dict: dict[str, Any] | None
) -> str | None:
    commits = _worker_commits_from_run(project, run_dict)
    return commits[-1] if commits else None


def _truncate_receipt_text(
    value: Any,
    *,
    max_chars: int = MAX_WORKER_LOG_TAIL_CHARS,
    tail: bool = False,
) -> str:
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[-max_chars:] if tail else text[:max_chars]


def _receipt_debug_value(value: Any, *, tail: bool = False) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_receipt_text(value, tail=tail)
    if isinstance(value, list):
        return [_receipt_debug_value(item, tail=tail) for item in value]
    if isinstance(value, dict):
        return {str(key): _receipt_debug_value(item, tail=tail) for key, item in value.items()}
    return _truncate_receipt_text(value, tail=tail)


def _receipt_verification_results(
    work_order: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for entry in work_order.get("verification_results", []):
        if not isinstance(entry, dict):
            continue
        command = str(entry.get("command", "")).strip()
        if not command:
            continue
        result: dict[str, Any] = {
            "command": command,
            "passed": bool(entry.get("passed", False)),
            "stdout_tail": _truncate_receipt_text(entry.get("stdout", ""), tail=True),
            "stderr_tail": _truncate_receipt_text(entry.get("stderr", ""), tail=True),
        }
        try:
            result["exit_code"] = int(entry.get("exit_code", 0))
        except (TypeError, ValueError):
            result["exit_code"] = -1
        try:
            result["duration_seconds"] = float(entry.get("duration_seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            result["duration_seconds"] = 0.0
        results.append(result)
    return results


def _receipt_merge_gate(work_order: dict[str, Any]) -> dict[str, Any] | None:
    merge_gate = work_order.get("merge_gate")
    if not isinstance(merge_gate, dict) or not merge_gate:
        return None
    return {
        "enabled": bool(merge_gate.get("enabled", True)),
        "checks_passed": bool(merge_gate.get("checks_passed", False)),
        "human_approval_required": bool(merge_gate.get("human_approval_required", False)),
        "merge_eligible": bool(merge_gate.get("merge_eligible", False)),
        "verification_missing_reason": _optional_text(
            merge_gate.get("verification_missing_reason")
        ),
        "expected_checks": [
            str(item).strip() for item in merge_gate.get("expected_checks", []) if str(item).strip()
        ],
        "blocked_reasons": [
            _truncate_receipt_text(item)
            for item in merge_gate.get("blocked_reasons", [])
            if str(item).strip()
        ],
    }


def _work_order_snapshot_for_receipt(work_order: dict[str, Any]) -> dict[str, Any]:
    prompt_preview = _truncate_receipt_text(
        WorkerLauncher._build_prompt(work_order),
        max_chars=MAX_WORKER_LOG_TAIL_CHARS,
    )
    stdout_tail = _truncate_receipt_text(work_order.get("stdout_tail", ""), tail=True)
    stderr_tail = _truncate_receipt_text(work_order.get("stderr_tail", ""), tail=True)
    return {
        "work_order_id": _optional_text(work_order.get("work_order_id")),
        "title": _optional_text(work_order.get("title")),
        "description": _optional_text(work_order.get("description")),
        "status": _optional_text(work_order.get("status")),
        "target_agent": _optional_text(work_order.get("target_agent")),
        "reviewer_agent": _optional_text(work_order.get("reviewer_agent")),
        "file_scope": [
            str(item).strip() for item in work_order.get("file_scope", []) if str(item).strip()
        ],
        "expected_tests": [
            str(item).strip() for item in work_order.get("expected_tests", []) if str(item).strip()
        ],
        "success_criteria": _receipt_debug_value(work_order.get("success_criteria")),
        "metadata": _receipt_debug_value(work_order.get("metadata") or {}),
        "prompt_preview": prompt_preview,
        "branch": _optional_text(work_order.get("branch")),
        "commit_shas": [
            str(item).strip() for item in work_order.get("commit_shas", []) if str(item).strip()
        ],
        "head_sha": _optional_text(work_order.get("head_sha")),
        "changed_paths": [
            str(item).strip() for item in work_order.get("changed_paths", []) if str(item).strip()
        ],
        "receipt_id": _optional_text(work_order.get("receipt_id")),
        "review_status": _optional_text(work_order.get("review_status")),
        "worker_outcome": _optional_text(work_order.get("worker_outcome")),
        "dispatch_error": _optional_text(work_order.get("dispatch_error")),
        "blockers": [
            _truncate_receipt_text(item)
            for item in work_order.get("blockers", [])
            if str(item).strip()
        ],
        "verification_missing_reason": _optional_text(
            work_order.get("verification_missing_reason")
        ),
        "verification_results": _receipt_verification_results(work_order),
        "merge_gate": _receipt_merge_gate(work_order),
        "stdout_tail": stdout_tail or None,
        "stderr_tail": stderr_tail or None,
        "dispatched_at": _optional_text(work_order.get("dispatched_at")),
        "started_at": _optional_text(work_order.get("started_at")),
        "completed_at": _optional_text(work_order.get("completed_at")),
        "last_progress_at": _optional_text(work_order.get("last_progress_at")),
        "last_observed_at": _optional_text(work_order.get("last_observed_at")),
    }


def _work_order_snapshots_from_run(run_dict: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not run_dict:
        return []
    snapshots: list[dict[str, Any]] = []
    for work_order in run_dict.get("work_orders", []):
        if not isinstance(work_order, dict):
            continue
        snapshots.append(_work_order_snapshot_for_receipt(work_order))
    return snapshots


def _planner_metadata_from_run(run_dict: dict[str, Any] | None) -> dict[str, Any]:
    if not run_dict:
        return {}
    for wo in run_dict.get("work_orders", []):
        if not isinstance(wo, dict):
            continue
        metadata = dict(wo.get("metadata") or {})
        if any(
            key in metadata
            for key in (
                "planner_strategy_requested",
                "planner_strategy_used",
                "planner_fallback_reason",
            )
        ):
            return {
                "planner_strategy_requested": str(
                    metadata.get("planner_strategy_requested", "")
                ).strip()
                or None,
                "planner_strategy_used": str(metadata.get("planner_strategy_used", "")).strip()
                or None,
                "planner_fallback_reason": str(metadata.get("planner_fallback_reason", "")).strip()
                or None,
            }
    return {}


def _verification_missing_reason_from_run(run_dict: dict[str, Any] | None) -> str | None:
    if not run_dict:
        return None
    for wo in run_dict.get("work_orders", []):
        if not isinstance(wo, dict):
            continue
        reason = str(wo.get("verification_missing_reason", "")).strip()
        if reason:
            return reason
        merge_gate = dict(wo.get("merge_gate") or {})
        reason = str(merge_gate.get("verification_missing_reason", "")).strip()
        if reason:
            return reason
    return None
