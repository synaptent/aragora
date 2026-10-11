"""Blocker-metadata and rehabilitation predicates for dev-coordination work orders.

Infers a missing failure reason and its blocking question, decides when a
blocked or clean-exit work order can be rehabilitated (docs-only changes,
dependency-validated successors, deliverable-backed clean exits), when a
review can be reclassified, and when receipts, file scopes or verification
plans should be backfilled. Split out of
:mod:`aragora.nomic.dev_coordination.core`, which re-imports every name here,
so ``core._backfill_work_order_blocker_metadata``, the package-level attribute
fallthrough and the ``aragora.nomic.dev_receipts`` aliases keep resolving to
these objects.
"""

from __future__ import annotations

from typing import Any

from aragora.nomic.dev_coordination.merge_gate_replay import (
    _is_docs_only_path,
    _merge_gate_state_for_work_order,
)
from aragora.nomic.dev_coordination.work_order_archive import _work_order_receipt_outcome
from aragora.nomic.dev_coordination.work_order_overlap import (
    _optional_text,
    _work_order_has_concrete_deliverable,
)
from aragora.nomic.dev_coordination.work_order_waiting_conflict import _work_order_identifier


def _default_blocking_question_for_reason(reason_code: str) -> str:
    mapping = {
        "waiting_conflict": (
            "Which overlapping lane should finish, be discarded, or be split before this task can proceed?"
        ),
        "clean_exit_no_deliverable": (
            "What concrete branch, commit, or PR should this lane produce before rerunning?"
        ),
        "merge_gate_failed": (
            "Which required verification or acceptance check must pass before approval?"
        ),
        "branch_snapshot_stale": (
            "Should this deliverable be rebased, regenerated, or otherwise refreshed on current main before review?"
        ),
        "missing_verification_plan": (
            "Which verification command or acceptance check should be added before rerunning?"
        ),
        "verification_target_missing": (
            "Which current verification target should replace the missing path before rerunning?"
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
        "stale_lease_reaped": ("Should this stale lane be requeued, recovered, or discarded?"),
        "expired_lease_reaped": ("Should this expired lane be requeued, recovered, or discarded?"),
    }
    return mapping.get(reason_code, "What human input is required before rerunning this lane?")


def _merge_gate_verification_target_missing(work_order: dict[str, Any]) -> bool:
    haystacks = [_optional_text(work_order.get("dispatch_error")).lower()]
    for entry in work_order.get("verification_results", []):
        if not isinstance(entry, dict):
            continue
        haystacks.extend(
            _optional_text(entry.get(field)).lower()
            for field in ("stdout", "stderr")
            if _optional_text(entry.get(field))
        )
    combined = "\n".join(text for text in haystacks if text)
    return "file or directory not found:" in combined


def _infer_missing_failure_reason_for_work_order(work_order: dict[str, Any]) -> str:
    status = _optional_text(work_order.get("status")).lower()
    if status == "waiting_conflict":
        return "waiting_conflict"

    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and bool(metadata.get("mainline_verification_passed")):
        return "branch_snapshot_stale"

    merge_gate = work_order.get("merge_gate")
    if isinstance(merge_gate, dict):
        missing = _optional_text(merge_gate.get("verification_missing_reason")).lower()
        if missing:
            return missing

    worker_outcome = _optional_text(work_order.get("worker_outcome")).lower()
    if worker_outcome == "branch_snapshot_stale":
        return "branch_snapshot_stale"
    if worker_outcome == "clean_exit_no_effect":
        return "clean_exit_no_deliverable"
    if worker_outcome == "merge_gate_failed":
        dispatch_error = _optional_text(work_order.get("dispatch_error")).lower()
        if "missing verification plan" in dispatch_error:
            return "missing_verification_plan"
        if _merge_gate_verification_target_missing(work_order):
            return "verification_target_missing"
        return "merge_gate_failed"
    if worker_outcome == "scope_violation":
        return "scope_violation"
    if worker_outcome == "timeout_with_salvage":
        return "worker_timeout_with_salvage"
    if worker_outcome == "timeout_no_progress":
        return "worker_no_progress_timeout"
    if worker_outcome == "crash_with_salvage":
        return "worker_crash_with_salvage"

    lowered = _optional_text(work_order.get("dispatch_error")).lower()
    if "branch snapshot stale" in lowered or "passes on main" in lowered:
        return "branch_snapshot_stale"
    if "missing verification plan" in lowered:
        return "missing_verification_plan"
    if _merge_gate_verification_target_missing(work_order):
        return "verification_target_missing"
    if "merge gate" in lowered:
        return "merge_gate_failed"
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
    if "dispatch blocked" in lowered:
        return "worker_type_blocked"
    if "autopilot ensure failed" in lowered or "lease" in lowered or "worktree" in lowered:
        return "work_order_leasing_failed"

    return _optional_text(work_order.get("failure_reason")) or "needs_human"


def _backfill_work_order_blocker_metadata(work_order: dict[str, Any]) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {
        "waiting_conflict",
        "needs_human",
        "changes_requested",
        "dispatch_failed",
        "failed",
        "timed_out",
        "scope_violation",
    }:
        return False

    changed = False
    failure_reason = _optional_text(work_order.get("failure_reason"))
    inferred = _infer_missing_failure_reason_for_work_order(work_order)
    if inferred and (not failure_reason or failure_reason == "merge_gate_failed"):
        if failure_reason != inferred:
            work_order["failure_reason"] = inferred
            failure_reason = inferred
            changed = True
    elif (
        inferred
        and inferred != failure_reason
        and failure_reason
        in {
            "merge_gate_failed",
            "needs_human",
        }
    ):
        work_order["failure_reason"] = inferred
        failure_reason = inferred
        changed = True

    blocking_question = _optional_text(work_order.get("blocking_question"))
    if failure_reason and (
        not blocking_question
        or (
            inferred
            and inferred == failure_reason
            and blocking_question == _default_blocking_question_for_reason("merge_gate_failed")
        )
    ):
        work_order["blocking_question"] = _default_blocking_question_for_reason(failure_reason)
        blocking_question = _optional_text(work_order.get("blocking_question"))
        changed = True

    blocker = work_order.get("blocker")
    if (
        not isinstance(blocker, dict)
        or not _optional_text(blocker.get("reason"))
        or not _optional_text(blocker.get("question"))
    ) and (failure_reason or blocking_question):
        work_order["blocker"] = {
            "reason": failure_reason or "needs_human",
            "question": blocking_question
            or _default_blocking_question_for_reason(failure_reason or "needs_human"),
        }
        changed = True

    return changed


def _work_order_should_backfill_verification_plan(work_order: dict[str, Any]) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested", "completed"}:
        return False
    if _infer_missing_failure_reason_for_work_order(work_order) != "missing_verification_plan":
        return False
    return not [
        str(item).strip() for item in work_order.get("expected_tests", []) if str(item).strip()
    ]


def _work_order_should_rehabilitate_docs_only_missing_verification_plan(
    work_order: dict[str, Any],
) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested"}:
        return False
    if _infer_missing_failure_reason_for_work_order(work_order) != "missing_verification_plan":
        return False
    candidates = [
        str(path).strip()
        for path in work_order.get("changed_paths", []) or work_order.get("file_scope", [])
        if str(path).strip()
    ]
    if not candidates or not all(_is_docs_only_path(path) for path in candidates):
        return False
    return _work_order_has_concrete_deliverable(work_order)


def _work_order_is_validation_successor(work_order: dict[str, Any]) -> bool:
    expected_tests = [
        str(item).strip() for item in work_order.get("expected_tests", []) if str(item).strip()
    ]
    if expected_tests:
        return True
    text = " ".join(
        part
        for part in (
            _optional_text(work_order.get("title")),
            _optional_text(work_order.get("description")),
            " ".join(
                str(item).strip()
                for item in ((work_order.get("metadata") or {}).get("acceptance_criteria") or [])
                if str(item).strip()
            ),
        )
        if part
    ).lower()
    return any(
        token in text
        for token in (
            "run validation",
            "validation and fix failures",
            "acceptance tests",
            "pytest ",
            "fix any failures",
        )
    )


def _work_order_rehabilitation_identifier(work_order: dict[str, Any]) -> str:
    return (
        _optional_text(work_order.get("pipeline_task_id"))
        or _work_order_identifier(work_order)
        or _optional_text(work_order.get("task_key"))
    )


def _dependency_deferred_verification_ids_for_work_order(
    work_order: dict[str, Any],
    *,
    work_orders: list[dict[str, Any]],
) -> list[str]:
    if not isinstance(work_order, dict):
        return []
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested"}:
        return []
    if _infer_missing_failure_reason_for_work_order(work_order) != "missing_verification_plan":
        return []
    if not _work_order_has_concrete_deliverable(work_order):
        return []

    work_order_ids = {
        identifier
        for identifier in (
            _optional_text(work_order.get("pipeline_task_id")),
            _work_order_identifier(work_order),
            _optional_text(work_order.get("task_key")),
        )
        if identifier
    }
    if not work_order_ids:
        return []

    deferred_dependency_ids: list[str] = []
    for candidate in work_orders:
        if not isinstance(candidate, dict) or candidate is work_order:
            continue
        dependency_ids = set(_work_order_dependency_ids(candidate))
        if not dependency_ids or not dependency_ids.intersection(work_order_ids):
            continue
        if not _work_order_is_validation_successor(candidate):
            continue
        candidate_id = _work_order_rehabilitation_identifier(candidate)
        if candidate_id and candidate_id not in deferred_dependency_ids:
            deferred_dependency_ids.append(candidate_id)
    return deferred_dependency_ids


def _work_order_dependency_ids(work_order: dict[str, Any]) -> list[str]:
    return [str(item).strip() for item in work_order.get("dependency_ids", []) if str(item).strip()]


def _work_order_matches_dependency_id(work_order: dict[str, Any], dependency_id: str) -> bool:
    target = str(dependency_id).strip()
    if not target:
        return False
    return target in {
        _optional_text(work_order.get("pipeline_task_id")),
        _work_order_identifier(work_order),
        _optional_text(work_order.get("task_key")),
    }


def _resolve_dependency_work_order(
    work_orders: list[dict[str, Any]],
    dependency_id: str,
) -> dict[str, Any] | None:
    for candidate in work_orders:
        if not isinstance(candidate, dict):
            continue
        if _work_order_matches_dependency_id(candidate, dependency_id):
            return candidate
    return None


def _work_order_has_passed_verification_results(work_order: dict[str, Any]) -> bool:
    verification_results = [
        dict(entry)
        for entry in work_order.get("verification_results", [])
        if isinstance(entry, dict) and str(entry.get("command", "")).strip()
    ]
    if not verification_results:
        return False
    if not all(bool(entry.get("passed", False)) for entry in verification_results):
        return False
    merge_gate = _merge_gate_state_for_work_order(work_order)
    return bool(merge_gate.get("checks_passed")) and not _optional_text(
        merge_gate.get("verification_missing_reason")
    )


def _work_order_should_rehabilitate_dependency_validated_clean_exit_no_deliverable(
    work_order: dict[str, Any],
    *,
    work_orders: list[dict[str, Any]],
) -> bool:
    if _optional_text(work_order.get("status")).lower() != "completed":
        return False
    if _optional_text(work_order.get("review_status")).lower() != "changes_requested":
        return False
    if _optional_text(work_order.get("worker_outcome")).lower() != "clean_exit_no_effect":
        return False
    if any(str(path).strip() for path in work_order.get("changed_paths", []) or []):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    if not _work_order_has_passed_verification_results(work_order):
        return False
    dependency_ids = _work_order_dependency_ids(work_order)
    if not dependency_ids:
        return False
    for dependency_id in dependency_ids:
        dependency = _resolve_dependency_work_order(work_orders, dependency_id)
        if dependency is None or dependency is work_order:
            return False
        if _optional_text(dependency.get("status")).lower() not in {
            "completed",
            "changes_requested",
            "merged",
        }:
            return False
        if not _work_order_has_concrete_deliverable(dependency):
            return False
    return True


def _work_order_should_rehabilitate_deliverable_backed_clean_exit_no_deliverable(
    work_order: dict[str, Any],
    *,
    work_orders: list[dict[str, Any]] | None = None,
) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested", "completed"}:
        return False
    if _infer_missing_failure_reason_for_work_order(work_order) != "clean_exit_no_deliverable":
        return False
    if status == "completed":
        return _work_order_should_rehabilitate_dependency_validated_clean_exit_no_deliverable(
            work_order,
            work_orders=list(work_orders or []),
        )
    if not _optional_text(work_order.get("receipt_id")):
        return False
    return _work_order_has_concrete_deliverable(work_order)


def _work_order_should_reclassify_branch_snapshot_stale_review(
    work_order: dict[str, Any],
) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status != "needs_human":
        return False
    if _optional_text(work_order.get("failure_reason")).lower() != "branch_snapshot_stale":
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    if not _work_order_has_concrete_deliverable(work_order):
        return False
    metadata = work_order.get("metadata")
    if not isinstance(metadata, dict) or not bool(metadata.get("mainline_verification_passed")):
        return False
    return True


def _work_order_should_reclassify_deliverable_changes_requested(
    work_order: dict[str, Any],
) -> bool:
    if not isinstance(work_order, dict):
        return False
    if _optional_text(work_order.get("status")).lower() != "needs_human":
        return False
    if _optional_text(work_order.get("review_status")).lower() != "changes_requested":
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    if not _work_order_has_concrete_deliverable(work_order):
        return False
    return _optional_text(work_order.get("failure_reason")).lower() in {
        "verification_target_missing",
        "merge_gate_failed",
        "branch_snapshot_stale",
    }


def _merge_gate_replay_matches_task_keys(
    run_id: str,
    work_order: dict[str, Any],
    task_keys: set[str],
) -> bool:
    if not task_keys:
        return True
    metadata = work_order.get("metadata")
    metadata_task_key = ""
    if isinstance(metadata, dict):
        metadata_task_key = _optional_text(metadata.get("task_key"))
    explicit = _optional_text(work_order.get("task_key"))
    derived = ""
    work_order_id = _work_order_identifier(work_order)
    if run_id and work_order_id:
        derived = f"{run_id}:{work_order_id}"
    return metadata_task_key in task_keys or explicit in task_keys or derived in task_keys


def _work_order_should_backfill_file_scope_from_changed_paths(work_order: dict[str, Any]) -> bool:
    status = _optional_text(work_order.get("status")).lower()
    if status in {"discarded", "superseded", "merged", "scope_violation"}:
        return False
    if any(str(path).strip() for path in work_order.get("file_scope", []) or []):
        return False
    if not any(str(path).strip() for path in work_order.get("changed_paths", []) or []):
        return False
    if isinstance(work_order.get("scope_violation"), dict):
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    return True


def _work_order_should_backfill_receipt(work_order: dict[str, Any]) -> bool:
    status = _optional_text(work_order.get("status")).lower()
    if status in {"queued", "leased", "dispatched", "active", "integrating", "discarded"}:
        return False
    if _optional_text(work_order.get("receipt_id")):
        return False
    if not _optional_text(work_order.get("lease_id")):
        return False
    return _work_order_receipt_outcome(work_order) in {"deliverable_created", "pr_adopted"}
