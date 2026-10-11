"""Work-order overlap, duplicate-detection and scope-matching helpers.

Split out of :mod:`aragora.nomic.dev_coordination.core`, which re-imports
every name here, so ``core._work_orders_overlap_by_scope``, the package-level
attribute fallthrough and the ``aragora.nomic.dev_receipts`` aliases keep
resolving to these functions.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
import re

from aragora.nomic.dev_coordination.models import LeaseStatus
from aragora.nomic.dev_coordination.utils import _has_wildcard, _normalize_claim, _parse_dt, _utcnow


def _optional_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _work_order_has_concrete_deliverable(work_order: dict[str, Any]) -> bool:
    receipt_id = _optional_text(work_order.get("receipt_id"))
    pr_url = _optional_text(work_order.get("pr_url"))
    adopted_pr = _optional_text(work_order.get("adopted_pr"))
    branch = _optional_text(work_order.get("branch"))
    commit_shas = [
        str(item).strip() for item in work_order.get("commit_shas", []) if str(item).strip()
    ]
    return bool(receipt_id or pr_url or adopted_pr or (branch and commit_shas))


def _work_order_is_live_overlap_sibling(work_order: dict[str, Any]) -> bool:
    status = _optional_text(work_order.get("status")).lower()
    if status in {"discarded", "superseded", "merged"}:
        return False
    return status in {
        "queued",
        "leased",
        "dispatched",
        "active",
        "completed",
        "changes_requested",
        "needs_human",
    }


def _live_overlap_sibling_priority(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> tuple[int, int, int, str]:
    status = _optional_text(work_order.get("status")).lower()
    status_rank = {
        "completed": 6,
        "changes_requested": 5,
        "active": 4,
        "dispatched": 3,
        "leased": 2,
        "queued": 1,
        "needs_human": 0,
    }.get(status, -1)
    return (
        status_rank,
        1 if _work_order_has_concrete_deliverable(work_order) else 0,
        len(_work_order_scope_patterns(work_order)),
        _developer_task_updated_at(work_order, run),
    )


def _work_order_is_duplicate_work_order_leasing_failed_candidate(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    lease_status: str | None,
) -> bool:
    if _optional_text(work_order.get("status")).lower() != "needs_human":
        return False
    if _optional_text(lease_status).lower() == LeaseStatus.ACTIVE.value:
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    if _optional_text(work_order.get("failure_reason")).lower() != "work_order_leasing_failed":
        return False
    if _optional_text(work_order.get("receipt_id")) or _work_order_has_concrete_deliverable(
        work_order
    ):
        return False
    return bool(_canonical_work_order_scope_key(work_order)) and bool(
        _canonical_goal_key(run.get("goal"))
    )


def _work_order_is_duplicate_waiting_conflict_candidate(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    lease_status: str | None,
) -> bool:
    if _optional_text(work_order.get("status")).lower() != "waiting_conflict":
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
    return bool(_duplicate_waiting_conflict_group_key(work_order, run=run))


def _waiting_conflict_candidate_text(work_order: dict[str, Any], *, run: dict[str, Any]) -> str:
    metadata = work_order.get("metadata") or {}
    acceptance = metadata.get("acceptance_criteria") if isinstance(metadata, dict) else []
    parts: list[str] = [
        _optional_text(run.get("goal")),
        _optional_text(work_order.get("title")),
        _optional_text(work_order.get("description")),
    ]
    if isinstance(acceptance, list):
        parts.extend(str(item).strip() for item in acceptance if str(item).strip())
    return " ".join(part for part in parts if part).lower()


def _work_order_source_name(work_order: dict[str, Any]) -> str:
    metadata = work_order.get("metadata") or {}
    return _optional_text(work_order.get("source"), metadata.get("source")).lower()


def _work_order_is_broad_explicit_pytest_umbrella(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> bool:
    if _work_order_source_name(work_order) != "explicit_spec_work_order":
        return False
    text = _waiting_conflict_candidate_text(work_order, run=run)
    if "pytest" not in text:
        return False
    return any(
        marker in text
        for marker in (
            "comprehensive pytest",
            "thorough pytest",
            "cover every",
            "internal helper",
            "helper function",
        )
    )


def _work_order_is_specific_pytest_child(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> bool:
    text = _waiting_conflict_candidate_text(work_order, run=run)
    if "pytest" not in text:
        return False
    return any(
        marker in text
        for marker in (
            "write one pytest test",
            "one pytest test",
            "single pytest test",
        )
    )


def _duplicate_waiting_conflict_group_key(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> tuple[str, str, tuple[str, ...]] | None:
    scope_key = _canonical_work_order_scope_key(work_order)
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict):
        tranche_lane_id = _optional_text(metadata.get("tranche_lane_id"))
        if tranche_lane_id:
            return ("tranche_lane_id", tranche_lane_id, scope_key)
    goal_key = _canonical_goal_key(run.get("goal"))
    if not goal_key:
        return None
    return ("goal", goal_key, scope_key)


def _superseded_waiting_conflict_group_key(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> str | None:
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict):
        tranche_lane_id = _optional_text(metadata.get("tranche_lane_id"))
        if tranche_lane_id:
            return f"lane:{tranche_lane_id}"
    goal_key = _canonical_goal_key(run.get("goal"))
    if not goal_key:
        return None
    return f"goal:{goal_key}"


def _duplicate_work_order_leasing_failed_priority(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> tuple[str, str, str]:
    return (
        _developer_task_updated_at(work_order, run),
        _optional_text(run.get("created_at")),
        _optional_text(work_order.get("work_order_id"), work_order.get("task_id")),
    )


def _work_order_should_archive_duplicate_branch_deliverable(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    cutoff: datetime,
    lease_status: str | None,
) -> bool:
    status = _optional_text(work_order.get("status")).lower()
    if status in {"discarded", "superseded", "merged"}:
        return False
    if _optional_text(lease_status).lower() == LeaseStatus.ACTIVE.value:
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    if not _optional_text(work_order.get("branch")):
        return False
    if not _work_order_has_concrete_deliverable(work_order):
        return False
    updated_at = _parse_dt(_developer_task_updated_at(work_order, run))
    return updated_at <= cutoff


def _work_order_scope_patterns(work_order: dict[str, Any]) -> list[str]:
    patterns = [
        _canonical_scope_pattern(str(item))
        for item in work_order.get("file_scope", []) or []
        if _canonical_scope_pattern(str(item))
    ]
    if patterns:
        return _collapse_scope_patterns(patterns)
    changed_paths = [
        _canonical_scope_pattern(str(item))
        for item in work_order.get("changed_paths", []) or []
        if _canonical_scope_pattern(str(item))
    ]
    return _collapse_scope_patterns(changed_paths)


def _canonical_work_order_scope_key(work_order: dict[str, Any]) -> tuple[str, ...]:
    patterns = _work_order_scope_patterns(work_order)
    if not patterns:
        return ()
    return tuple(sorted(dict.fromkeys(patterns)))


def _canonical_scope_pattern(value: str) -> str:
    clean = _normalize_claim(value)
    if not clean:
        return ""
    if clean.endswith("/**"):
        clean = clean[:-3].rstrip("/")
    return clean


def _collapse_scope_patterns(patterns: list[str]) -> list[str]:
    collapsed: list[str] = []
    unique_patterns = list(
        dict.fromkeys(_canonical_scope_pattern(item) for item in patterns if item)
    )
    for pattern in unique_patterns:
        if not pattern:
            continue
        if any(
            other != pattern and _path_matches_glob(pattern, other)
            for other in unique_patterns
            if other
        ):
            continue
        collapsed.append(pattern)
    return collapsed


def _canonical_goal_key(value: Any) -> str:
    text = str(value or "").strip()
    for paragraph in re.split(r"\n\s*\n", text):
        candidate = " ".join(paragraph.split()).strip()
        if not candidate:
            continue
        lower = candidate.lower()
        if lower.startswith(
            (
                "## ",
                "validation",
                "allowed write scope",
                "verification commands",
                "source issue context",
                "acceptance criteria",
                "context",
                "goal",
            )
        ):
            continue
        first_sentence = re.split(r"(?<=[.!?])\s+", candidate, maxsplit=1)[0]
        normalized = " ".join(first_sentence.split()).strip().lower()
        if normalized:
            return normalized
    return " ".join(text.split()).strip().lower()


def _claim_contains(container: str, containee: str) -> bool:
    clean_container = _normalize_claim(container)
    clean_containee = _normalize_claim(containee)
    if not clean_container or not clean_containee:
        return False
    return _path_matches_glob(clean_containee, clean_container)


def _work_order_scope_contains(container: dict[str, Any], containee: dict[str, Any]) -> bool:
    container_patterns = _work_order_scope_patterns(container)
    containee_patterns = _work_order_scope_patterns(containee)
    if not container_patterns or not containee_patterns:
        return False
    return all(
        any(
            _claim_contains(container_pattern, containee_pattern)
            for container_pattern in container_patterns
        )
        for containee_pattern in containee_patterns
    )


def _work_orders_overlap_by_scope(
    first: dict[str, Any],
    second: dict[str, Any],
) -> bool:
    first_globs = _work_order_scope_patterns(first)
    second_globs = _work_order_scope_patterns(second)
    first_paths = [
        _normalize_claim(str(item))
        for item in first.get("changed_paths", []) or []
        if _normalize_claim(str(item))
    ]
    second_paths = [
        _normalize_claim(str(item))
        for item in second.get("changed_paths", []) or []
        if _normalize_claim(str(item))
    ]
    if not first_globs and not first_paths:
        return False
    if not second_globs and not second_paths:
        return False
    return _globs_overlap_any(first_globs, second_globs, first_paths, second_paths)


def _developer_task_updated_at(work_order: dict[str, Any], run: dict[str, Any]) -> str:
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
        run.get("updated_at"),
        _utcnow().isoformat(),
    ):
        text = str(value or "").strip()
        if text and text.lower() != "none":
            return text
    return _utcnow().isoformat()


def _path_matches_glob(path: str, pattern: str) -> bool:
    clean_path = _normalize_claim(path)
    clean_pattern = _normalize_claim(pattern)
    if not clean_pattern:
        return False
    if _has_wildcard(clean_pattern):
        if clean_pattern.endswith("/**"):
            prefix = clean_pattern[:-3].rstrip("/")
            return clean_path == prefix or clean_path.startswith(f"{prefix}/")
        return PurePosixPath(clean_path).match(clean_pattern)
    return clean_path == clean_pattern or clean_path.startswith(f"{clean_pattern}/")


def _glob_overlap(first: str, second: str) -> bool:
    a = _normalize_claim(first)
    b = _normalize_claim(second)
    if not a or not b:
        return False
    if a == b:
        return True
    a_wild = _has_wildcard(a)
    b_wild = _has_wildcard(b)
    if not a_wild and not b_wild:
        return a.startswith(f"{b}/") or b.startswith(f"{a}/")
    if not a_wild:
        return _path_matches_glob(a, b)
    if not b_wild:
        return _path_matches_glob(b, a)
    a_prefix = a.split("*")[0]
    b_prefix = b.split("*")[0]
    if a_prefix and b_prefix and (a_prefix.startswith(b_prefix) or b_prefix.startswith(a_prefix)):
        return True
    return False


def _globs_overlap_any(
    first_globs: list[str],
    second_globs: list[str],
    first_paths: list[str],
    second_paths: list[str],
) -> bool:
    for path in first_paths:
        if _claims_overlap([path], second_globs, second_paths):
            return True
    for path in second_paths:
        if _claims_overlap([path], first_globs, first_paths):
            return True
    for left in first_globs:
        for right in second_globs:
            if _glob_overlap(left, right):
                return True
    return False


def _claims_overlap(
    claimed_paths: list[str], allowed_globs: list[str], other_paths: list[str]
) -> bool:
    for claimed in claimed_paths:
        for glob in allowed_globs:
            if _path_matches_glob(claimed, glob) or _path_matches_glob(glob, claimed):
                return True
        for other in other_paths:
            if _glob_overlap(claimed, other):
                return True
    return False
