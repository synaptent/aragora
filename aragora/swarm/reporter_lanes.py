"""Lane and receipt classification helpers for the swarm reporter.

They pull receipt ids, pull-request links and run/task keys out of loosely shaped
coordination records, detect superseded or retired lanes, and derive a lane's merge
readiness, health, next action and available operator actions. ``aragora.swarm.reporter``
re-exports every name here, so importing from either module yields the same objects.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from aragora.swarm.reporter_fields import _first_text, _metadata, _parse_iso_timestamp, _text


def _extract_receipt_id(*sources: dict[str, Any] | None) -> str:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("receipt_id", "decision_receipt_id", "last_receipt_id"):
            text = _text(source.get(key))
            if text:
                return text
        meta = _metadata(source)
        for key in ("receipt_id", "decision_receipt_id", "last_receipt_id"):
            text = _text(meta.get(key))
            if text:
                return text
    return ""


def _run_task_tuple(run_id: Any, task_id: Any) -> tuple[str, str] | None:
    run_text = _text(run_id)
    task_text = _text(task_id)
    if not run_text or not task_text:
        return None
    return (run_text, task_text)


def _item_task_key(item: dict[str, Any] | None) -> str:
    if not isinstance(item, dict):
        return ""
    meta = _metadata(item)
    return _first_text(item.get("task_key"), meta.get("task_key"))


def _item_run_task(item: dict[str, Any] | None) -> tuple[str, str] | None:
    if not isinstance(item, dict):
        return None
    meta = _metadata(item)
    task_id = _first_text(item.get("task_id"), meta.get("task_id"), meta.get("work_order_id"))
    run_id = _first_text(meta.get("supervisor_run_id"), meta.get("run_id"))
    return _run_task_tuple(run_id, task_id)


def _deliverable(source: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    deliverable = source.get("deliverable")
    if isinstance(deliverable, dict):
        return deliverable
    meta = _metadata(source)
    deliverable = meta.get("deliverable")
    return deliverable if isinstance(deliverable, dict) else {}


def _extract_pr_number(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    text = _text(value).rstrip("/")
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text.startswith("#") and text[1:].isdigit():
        return int(text[1:])
    tail = text.rsplit("/", 1)[-1]
    if tail.isdigit():
        return int(tail)
    match = re.search(r"#(\d+)$", text)
    if match:
        return int(match.group(1))
    return None


def _extract_pr_link(*sources: dict[str, Any] | None) -> dict[str, Any] | None:
    url = ""
    reference = ""
    number: int | None = None
    for source in sources:
        if not isinstance(source, dict):
            continue
        meta = _metadata(source)
        deliverable = _deliverable(source)
        for candidate in (
            source.get("pr_url"),
            source.get("pull_request_url"),
            source.get("adopted_pr"),
            deliverable.get("pr_url"),
            deliverable.get("adopted_pr"),
            meta.get("pr_url"),
            meta.get("pull_request_url"),
            meta.get("adopted_pr"),
        ):
            text = _text(candidate)
            if not text:
                continue
            if not url and re.match(r"^https?://", text):
                url = text
            elif not reference:
                reference = text
            if number is None:
                number = _extract_pr_number(text)
        for candidate in (
            source.get("pr_number"),
            source.get("pull_request_number"),
            source.get("adopted_pr"),
            deliverable.get("pr_number"),
            deliverable.get("pull_request_number"),
            deliverable.get("adopted_pr"),
            meta.get("pr_number"),
            meta.get("pull_request_number"),
            meta.get("adopted_pr"),
        ):
            parsed = _extract_pr_number(candidate)
            if parsed is not None:
                number = parsed
                break
    if not url and not reference and number is None:
        return None
    return {
        "url": url or None,
        "number": number,
        "reference": reference or None,
    }


def _explicit_missing_receipt(*sources: dict[str, Any] | None) -> bool:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for error_field in ("dispatch_error", "error"):
            lowered = _text(source.get(error_field)).lower()
            if "without receipt" in lowered or "missing receipt" in lowered:
                return True
        meta = _metadata(source)
        lowered = _text(meta.get("error")).lower()
        if "without receipt" in lowered or "missing receipt" in lowered:
            return True
    return False


def _receipt_backfill_scope_gap(scope_violation_record: dict[str, Any] | None) -> bool:
    if not isinstance(scope_violation_record, dict):
        return False
    for violation in scope_violation_record.get("violations", []) or []:
        if not isinstance(violation, dict):
            continue
        if _text(violation.get("type")).lower() == "undeclared_scope":
            return True
    return False


def _is_superseded(*sources: dict[str, Any] | None) -> bool:
    for source in sources:
        if not isinstance(source, dict):
            continue
        if _text(source.get("status")).lower() == "superseded":
            return True
        meta = _metadata(source)
        if _text(meta.get("superseded_by")) or _text(meta.get("supersedes")):
            return True
        if _has_retired_marker(source):
            return True
    return False


def _has_retired_marker(source: dict[str, Any]) -> bool:
    for key in ("failure_reason", "dispatch_error"):
        text = _text(source.get(key)).lower()
        if text.startswith("retired after "):
            return True
    for key in ("blockers", "blocked_by"):
        values = source.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if _text(value).lower().startswith("retired after "):
                return True
    return False


def _merge_queue_status(queue_item: dict[str, Any] | None) -> str:
    if not isinstance(queue_item, dict):
        return ""
    return _text(queue_item.get("status")).lower()


def _receipt_expected(status: str, queue_status: str) -> bool:
    if queue_status in {"validating", "integrating", "needs_human", "merged", "failed"}:
        return True
    return status in {"completed", "needs_human", "merged"}


def _merge_readiness(
    *,
    status: str,
    queue_status: str,
    stale_heartbeat: bool,
    missing_receipt: bool,
    scope_violation: bool,
    superseded: bool,
    collisions: list[str],
) -> str:
    if superseded:
        return "superseded"
    if (
        collisions
        or stale_heartbeat
        or missing_receipt
        or scope_violation
        or queue_status in {"blocked", "failed"}
    ):
        return "blocked"
    if queue_status == "merged":
        return "merged"
    if queue_status in {"validating", "integrating"}:
        return queue_status
    if queue_status == "needs_human":
        return "review"
    if status in {"completed", "needs_human"}:
        return "ready"
    if status in {"leased", "dispatched", "queued", "active"}:
        return "in_progress"
    return status or queue_status or "unknown"


def _next_action(
    *,
    readiness: str,
    lane_health: str,
    terminal_outcome: str,
    stale_heartbeat: bool,
    missing_receipt: bool,
    scope_violation: bool,
    superseded: bool,
    collisions: list[str],
    queue_status: str,
    blockers: list[str],
) -> str:
    lowered_blockers = {_text(item).lower() for item in blockers if _text(item)}
    if superseded or lane_health == "superseded":
        return "Archive the superseded lane and keep the canonical lane."
    if lane_health == "expired":
        return "Salvage or reassign the expired lane before resuming work."
    if lane_health == "stalled":
        return "Inspect the stalled lane and decide whether to salvage, supersede, or reassign it."
    if collisions:
        return "Resolve the branch or file-scope collision before integrating."
    if "receipt_backfill_blocked_undeclared_scope" in lowered_blockers:
        return "Declare the intended lane scope or discard the lane before receipt backfill and merge review."
    if scope_violation:
        return "Narrow the lane scope or split ownership before it can re-enter merge review."
    if "work_order_leasing_failed" in lowered_blockers:
        return "Reconcile or regenerate the managed worktree, then requeue the lane."
    if _text(terminal_outcome).lower() == "clean_exit_no_deliverable":
        return "Inspect why the lane produced no concrete deliverable before rerunning it."
    if "merge_gate_failed" in lowered_blockers or any(
        item.startswith("merge gate blocked:") for item in lowered_blockers
    ):
        return "Fix the merge gate or verification failure before rerunning the lane."
    if stale_heartbeat:
        return "Inspect the stale lane and decide whether to salvage or reassign it."
    if missing_receipt:
        return "Attach or regenerate the completion receipt before integration."
    if queue_status == "needs_human":
        return "Review the validated lane and decide whether it should merge."
    if readiness == "review":
        return "Review the validated lane and decide whether it should merge."
    if readiness == "ready":
        return "Queue or validate this lane for merge."
    if readiness == "merged":
        return "No action needed; the lane is already merged."
    return "Monitor the lane or reconcile it if progress stalls."


def _item_timestamp(item: dict[str, Any] | None, *keys: str) -> datetime:
    if not isinstance(item, dict):
        return datetime.min.replace(tzinfo=timezone.utc)
    for key in keys:
        parsed = _parse_iso_timestamp(item.get(key))
        if parsed is not None:
            return parsed
    meta = _metadata(item)
    for key in keys:
        parsed = _parse_iso_timestamp(meta.get(key))
        if parsed is not None:
            return parsed
    return datetime.min.replace(tzinfo=timezone.utc)


def _sort_newest(items: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: _item_timestamp(item, *keys), reverse=True)


def _lane_health(
    *,
    readiness: str,
    status: str,
    terminal_outcome: str,
    lease_status: str,
    stale_heartbeat: bool,
    missing_receipt: bool,
    scope_violation: bool,
    superseded: bool,
    collisions: list[str],
    blockers: list[str],
) -> str:
    if superseded or status == "discarded":
        return "superseded"
    lowered_blockers = {_text(item).lower() for item in blockers if _text(item)}
    if lowered_blockers.intersection({"stale_lease_reaped", "expired_lease_reaped"}):
        return "expired"
    if (
        scope_violation
        or _text(status).lower() == "scope_violation"
        or lowered_blockers.intersection({"scope_violation", "work_order_leasing_failed"})
    ):
        return "blocked"
    if lease_status == "expired" or status == "timed_out":
        return "expired"
    if readiness == "review" and _text(terminal_outcome).lower() in {
        "deliverable_created",
        "pr_adopted",
    }:
        return "healthy"
    if stale_heartbeat or status in {"dispatch_failed", "failed"}:
        return "stalled"
    if lowered_blockers.intersection({"merge_gate_failed"}) or _text(terminal_outcome).lower() in {
        "clean_exit_no_deliverable",
        "blocked",
    }:
        return "blocked"
    if readiness == "merged":
        return "merged"
    if readiness == "blocked" or missing_receipt or scope_violation or collisions:
        return "blocked"
    return "healthy"


def _available_actions(
    *,
    canonical_lane: bool,
    readiness: str,
    lane_health: str,
    missing_receipt: bool,
    scope_violation: bool,
    superseded: bool,
    collisions: list[str],
    decision: str,
) -> list[str]:
    if superseded or lane_health == "superseded" or readiness == "superseded":
        return ["archive"]
    if readiness == "merged":
        return ["archive"]

    actions: list[str] = []
    if lane_health in {"expired", "stalled"}:
        actions.extend(["salvage", "reassign", "archive"])
    if collisions or scope_violation:
        actions.extend(["request_changes", "supersede"])
    if missing_receipt:
        actions.append("attach_receipt")
    if decision == "request_changes":
        actions.extend(["request_changes", "supersede"])
    if decision == "salvage":
        actions.extend(["salvage", "archive"])
    if readiness in {"ready", "review"} and not (collisions or scope_violation or missing_receipt):
        actions.extend(["merge", "cherry_pick", "request_changes"])
    if not canonical_lane and readiness not in {"merged", "superseded"}:
        actions.append("supersede")
    if not actions:
        actions.append("monitor")
    return list(dict.fromkeys(actions))
