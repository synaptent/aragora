"""SwarmReporter: plain-English report generation for non-developer users."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import logging
from dataclasses import dataclass, field
from typing import Any

from pathlib import Path

from aragora.harnesses.base import AnalysisType
from aragora.swarm.spec import SwarmSpec

logger = logging.getLogger(__name__)

_STALE_LANE_AFTER_SECONDS = 15 * 60


def _parse_iso_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _age_seconds(value: Any, *, now: datetime) -> float | None:
    parsed = _parse_iso_timestamp(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _text(value: Any) -> str:
    return str(value or "").strip()


def _metadata(item: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    data = item.get("metadata")
    return data if isinstance(data, dict) else {}


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


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


def _extract_pr_link(*sources: dict[str, Any] | None) -> dict[str, Any] | None:
    url = ""
    number: int | None = None
    for source in sources:
        if not isinstance(source, dict):
            continue
        meta = _metadata(source)
        for candidate in (
            source.get("pr_url"),
            source.get("pull_request_url"),
            meta.get("pr_url"),
            meta.get("pull_request_url"),
        ):
            text = _text(candidate)
            if text and not url:
                url = text
        for candidate in (
            source.get("pr_number"),
            source.get("pull_request_number"),
            meta.get("pr_number"),
            meta.get("pull_request_number"),
        ):
            if isinstance(candidate, int):
                number = candidate
                break
            text = _text(candidate)
            if text.isdigit():
                number = int(text)
                break
        if url or number is not None:
            break
    if not url and number is None:
        return None
    return {"url": url or None, "number": number}


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


def _is_superseded(*sources: dict[str, Any] | None) -> bool:
    for source in sources:
        if not isinstance(source, dict):
            continue
        if _text(source.get("status")).lower() == "superseded":
            return True
        meta = _metadata(source)
        if _text(meta.get("superseded_by")) or _text(meta.get("supersedes")):
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
    stale_heartbeat: bool,
    missing_receipt: bool,
    scope_violation: bool,
    superseded: bool,
    collisions: list[str],
    queue_status: str,
) -> str:
    if superseded:
        return "Close or archive the superseded lane."
    if collisions:
        return "Resolve the branch or file-scope collision before integrating."
    if scope_violation:
        return "Narrow the lane scope or split ownership before it can re-enter merge review."
    if stale_heartbeat:
        return "Inspect the stale lane and decide whether to salvage or reassign it."
    if missing_receipt:
        return "Attach or regenerate the completion receipt before integration."
    if queue_status == "needs_human":
        return "Review the validated lane and decide whether it should merge."
    if readiness == "ready":
        return "Queue or validate this lane for merge."
    if readiness == "merged":
        return "No action needed; the lane is already merged."
    return "Monitor the lane or reconcile it if progress stalls."


def build_integrator_view(
    *,
    runs: list[dict[str, Any]] | None = None,
    worktrees: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
    merge_queue: list[dict[str, Any]] | None = None,
    coordination: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Normalize coordination state into an integrator-facing lane view."""
    runs = [item for item in (runs or []) if isinstance(item, dict)]
    worktrees = [item for item in (worktrees or []) if isinstance(item, dict)]
    claims = [item for item in (claims or []) if isinstance(item, dict)]
    merge_queue = [item for item in (merge_queue or []) if isinstance(item, dict)]
    coordination = coordination if isinstance(coordination, dict) else {}
    now = now or datetime.now(UTC)

    worktrees_by_branch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    worktrees_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    worktrees_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in worktrees:
        branch = _text(row.get("branch"))
        if branch:
            worktrees_by_branch[branch].append(row)
        path = _text(row.get("path"))
        if path:
            worktrees_by_path[path].append(row)
        session_id = _text(row.get("session_id"))
        if session_id:
            worktrees_by_session[session_id].append(row)

    claims_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sessions_by_path: dict[str, set[str]] = defaultdict(set)
    for claim in claims:
        session_id = _text(claim.get("session_id"))
        path = _text(claim.get("path"))
        if session_id:
            claims_by_session[session_id].append(claim)
        if session_id and path:
            sessions_by_path[path].add(session_id)

    worktree_branch_counts: dict[str, int] = defaultdict(int)
    work_order_branch_counts: dict[str, int] = defaultdict(int)
    queue_branch_counts: dict[str, int] = defaultdict(int)
    for branch, rows_for_branch in worktrees_by_branch.items():
        worktree_branch_counts[branch] += len(rows_for_branch)
    for run in runs:
        for work_order in run.get("work_orders", []):
            if not isinstance(work_order, dict):
                continue
            branch = _text(work_order.get("branch"))
            if branch:
                work_order_branch_counts[branch] += 1

    queue_by_branch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    queue_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in merge_queue:
        branch = _text(item.get("branch"))
        session_id = _text(item.get("session_id"))
        if branch:
            queue_by_branch[branch].append(item)
            queue_branch_counts[branch] += 1
        if session_id:
            queue_by_session[session_id].append(item)

    scope_violations = coordination.get("scope_violations", [])
    scope_violation_by_lease: dict[str, dict[str, Any]] = {}
    scope_violation_by_session_branch: dict[tuple[str, str], dict[str, Any]] = {}
    for item in scope_violations:
        if not isinstance(item, dict):
            continue
        lease_id = _text(item.get("lease_id"))
        if lease_id:
            scope_violation_by_lease[lease_id] = item
        session_id = _text(item.get("owner_session_id"))
        branch = _text(item.get("branch"))
        if session_id or branch:
            scope_violation_by_session_branch[(session_id, branch)] = item

    lanes: list[dict[str, Any]] = []
    seen_worktree_keys: set[tuple[str, str]] = set()
    seen_queue_keys: set[tuple[str, str, str]] = set()

    def build_lane(
        *,
        source: str,
        run: dict[str, Any] | None = None,
        work_order: dict[str, Any] | None = None,
        worktree_row: dict[str, Any] | None = None,
        queue_item: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        work_order = work_order or {}
        worktree_row = worktree_row or {}
        queue_item = queue_item or {}
        run = run or {}
        work_order_meta = _metadata(work_order)
        queue_meta = _metadata(queue_item)
        inferred_status = ""
        if bool(worktree_row.get("has_lock")) and bool(worktree_row.get("pid_alive")):
            inferred_status = "active"
        elif bool(worktree_row.get("has_lock")):
            inferred_status = "needs_human"
        status = _first_text(
            work_order.get("status"), worktree_row.get("status"), inferred_status, "unknown"
        ).lower()
        branch = _first_text(
            work_order.get("branch"), worktree_row.get("branch"), queue_item.get("branch")
        )
        worktree_path = _first_text(
            work_order.get("worktree_path"),
            worktree_row.get("path"),
            queue_meta.get("integration_workspace_path"),
        )
        session_id = _first_text(
            work_order_meta.get("owner_session_id"),
            worktree_row.get("session_id"),
            queue_item.get("session_id"),
        )
        owner_agent = _first_text(
            work_order.get("target_agent"),
            work_order_meta.get("owner_agent"),
            worktree_row.get("agent"),
        )
        receipt_id = _extract_receipt_id(work_order, queue_item)
        queue_status = _merge_queue_status(queue_item)
        branch_collision = bool(
            branch
            and (
                worktree_branch_counts.get(branch, 0) > 1
                or work_order_branch_counts.get(branch, 0) > 1
                or queue_branch_counts.get(branch, 0) > 1
            )
        )

        claimed_paths = sorted(
            {
                _text(claim.get("path"))
                for claim in claims_by_session.get(session_id, [])
                if _text(claim.get("path"))
            }
        )
        file_scope = [_text(path) for path in work_order.get("file_scope", []) if _text(path)]
        collision_reasons: list[str] = []
        if branch_collision:
            collision_reasons.append(f"branch:{branch}")
        for path in claimed_paths or file_scope:
            owners = sessions_by_path.get(path, set())
            if len(owners) > 1:
                collision_reasons.append(f"path:{path}")
        collision_reasons = sorted(set(collision_reasons))

        heartbeat_source = _first_text(
            work_order.get("last_progress_at"),
            work_order.get("last_observed_at"),
            work_order.get("dispatched_at"),
            worktree_row.get("last_activity"),
            queue_item.get("updated_at"),
        )
        heartbeat_age_seconds = _age_seconds(heartbeat_source, now=now)
        stale_heartbeat = bool(
            (
                work_order
                and status in {"leased", "dispatched", "active"}
                and heartbeat_age_seconds is not None
                and heartbeat_age_seconds >= _STALE_LANE_AFTER_SECONDS
            )
            or (bool(worktree_row.get("has_lock")) and not bool(worktree_row.get("pid_alive")))
        )

        superseded = _is_superseded(work_order, queue_item)
        missing_receipt = _explicit_missing_receipt(work_order, queue_item) or (
            _receipt_expected(status, queue_status) and not receipt_id
        )
        if status in {"queued", "leased", "dispatched"} and queue_status in {"", "queued"}:
            missing_receipt = (
                False if not _explicit_missing_receipt(work_order, queue_item) else True
            )

        lease_id = _first_text(work_order.get("lease_id"), work_order_meta.get("lease_id"))
        scope_violation_record = (
            scope_violation_by_lease.get(lease_id)
            if lease_id
            else scope_violation_by_session_branch.get((session_id, branch))
        )
        scope_violation = isinstance(scope_violation_record, dict)
        lease_health = "idle"
        if lease_id:
            lease_health = "stale" if stale_heartbeat else "healthy"
        elif status in {"leased", "dispatched"}:
            lease_health = "missing"
        elif bool(worktree_row.get("has_lock")):
            lease_health = "stale" if stale_heartbeat else "healthy"

        readiness = _merge_readiness(
            status=status,
            queue_status=queue_status,
            stale_heartbeat=stale_heartbeat,
            missing_receipt=missing_receipt,
            scope_violation=scope_violation,
            superseded=superseded,
            collisions=collision_reasons,
        )

        title = _first_text(
            work_order.get("title"),
            work_order.get("description"),
            queue_item.get("title"),
            run.get("goal"),
            branch,
            session_id,
            "lane",
        )
        pr = _extract_pr_link(work_order, queue_item)
        blockers = sorted(
            {
                *[_text(item) for item in work_order.get("blockers", []) if _text(item)],
                *collision_reasons,
            }
        )
        if stale_heartbeat:
            blockers.append("stale_heartbeat")
        if missing_receipt:
            blockers.append("missing_receipt")
        if scope_violation:
            blockers.append("scope_violation")
        if superseded:
            blockers.append("superseded")
        blockers = sorted(set(blockers))

        lane_id = _first_text(
            work_order.get("work_order_id"),
            queue_item.get("id"),
            branch,
            session_id,
            worktree_path,
            title,
        )
        return {
            "lane_id": lane_id,
            "source": source,
            "run_id": _text(run.get("run_id")),
            "work_order_id": _text(work_order.get("work_order_id")),
            "title": title,
            "status": status,
            "owner_agent": owner_agent or None,
            "owner_session_id": session_id or None,
            "branch": branch or None,
            "worktree_path": worktree_path or None,
            "lease_id": lease_id or None,
            "lease_health": lease_health,
            "heartbeat_at": heartbeat_source or None,
            "heartbeat_age_seconds": round(heartbeat_age_seconds, 1)
            if heartbeat_age_seconds is not None
            else None,
            "stale_heartbeat": stale_heartbeat,
            "claimed_paths": claimed_paths,
            "file_scope": file_scope,
            "queue_item_id": _text(queue_item.get("id")) or None,
            "merge_queue_status": queue_status or None,
            "receipt_id": receipt_id or None,
            "missing_receipt": missing_receipt,
            "scope_violation": scope_violation_record,
            "superseded": superseded,
            "collisions": collision_reasons,
            "pr": pr,
            "merge_readiness": readiness,
            "blockers": blockers,
            "next_action": _next_action(
                readiness=readiness,
                stale_heartbeat=stale_heartbeat,
                missing_receipt=missing_receipt,
                scope_violation=scope_violation,
                superseded=superseded,
                collisions=collision_reasons,
                queue_status=queue_status,
            ),
        }

    for run in runs:
        for work_order in run.get("work_orders", []):
            if not isinstance(work_order, dict):
                continue
            branch = _text(work_order.get("branch"))
            worktree_path = _text(work_order.get("worktree_path"))
            matched_row = None
            if branch and worktrees_by_branch.get(branch):
                matched_row = worktrees_by_branch[branch][0]
            elif worktree_path and worktrees_by_path.get(worktree_path):
                matched_row = worktrees_by_path[worktree_path][0]
            queue_item = queue_by_branch.get(branch, [None])[0] if branch else None
            if matched_row:
                seen_worktree_keys.add(
                    (_text(matched_row.get("session_id")), _text(matched_row.get("branch")))
                )
            if isinstance(queue_item, dict):
                seen_queue_keys.add(
                    (
                        _text(queue_item.get("id")),
                        _text(queue_item.get("branch")),
                        _text(queue_item.get("session_id")),
                    )
                )
            lanes.append(
                build_lane(
                    source="swarm",
                    run=run,
                    work_order=work_order,
                    worktree_row=matched_row,
                    queue_item=queue_item if isinstance(queue_item, dict) else None,
                )
            )

    for row in worktrees:
        key = (_text(row.get("session_id")), _text(row.get("branch")))
        if key in seen_worktree_keys:
            continue
        branch = _text(row.get("branch"))
        queue_item = queue_by_branch.get(branch, [None])[0] if branch else None
        if isinstance(queue_item, dict):
            seen_queue_keys.add(
                (
                    _text(queue_item.get("id")),
                    _text(queue_item.get("branch")),
                    _text(queue_item.get("session_id")),
                )
            )
        lanes.append(
            build_lane(
                source="fleet",
                worktree_row=row,
                queue_item=queue_item if isinstance(queue_item, dict) else None,
            )
        )

    for item in merge_queue:
        queue_key = (
            _text(item.get("id")),
            _text(item.get("branch")),
            _text(item.get("session_id")),
        )
        if queue_key in seen_queue_keys:
            continue
        session_id = _text(item.get("session_id"))
        matched_row = worktrees_by_session.get(session_id, [None])[0] if session_id else None
        lanes.append(
            build_lane(
                source="merge_queue",
                worktree_row=matched_row if isinstance(matched_row, dict) else None,
                queue_item=item,
            )
        )

    def lane_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
        readiness = _text(item.get("merge_readiness"))
        priority = {
            "blocked": 0,
            "review": 1,
            "ready": 2,
            "in_progress": 3,
            "validating": 4,
            "integrating": 5,
            "merged": 6,
            "superseded": 7,
        }.get(readiness, 8)
        return (priority, _text(item.get("branch")), _text(item.get("lane_id")))

    lanes.sort(key=lane_sort_key)

    alerts = {
        "collisions": [],
        "stale_heartbeats": [],
        "superseded_lanes": [],
        "missing_receipts": [],
        "scope_violations": [],
        "merge_ready": [],
    }
    for lane in lanes:
        ref = {
            "lane_id": lane["lane_id"],
            "branch": lane["branch"],
            "owner_session_id": lane["owner_session_id"],
            "title": lane["title"],
        }
        if lane["collisions"]:
            alerts["collisions"].append({**ref, "reasons": lane["collisions"]})
        if lane["stale_heartbeat"]:
            alerts["stale_heartbeats"].append(ref)
        if lane["superseded"]:
            alerts["superseded_lanes"].append(ref)
        if lane["missing_receipt"]:
            alerts["missing_receipts"].append(ref)
        if isinstance(lane.get("scope_violation"), dict):
            alerts["scope_violations"].append(ref)
        if lane["merge_readiness"] == "ready":
            alerts["merge_ready"].append(ref)

    next_actions: list[str] = []
    for lane in lanes:
        action = _text(lane.get("next_action"))
        if not action:
            continue
        summary = f"{lane['title']}: {action}"
        if summary not in next_actions:
            next_actions.append(summary)
        if len(next_actions) >= 5:
            break

    summary = {
        "total_lanes": len(lanes),
        "ready_lanes": sum(1 for lane in lanes if lane["merge_readiness"] == "ready"),
        "blocked_lanes": sum(1 for lane in lanes if lane["merge_readiness"] == "blocked"),
        "review_lanes": sum(1 for lane in lanes if lane["merge_readiness"] == "review"),
        "in_progress_lanes": sum(1 for lane in lanes if lane["merge_readiness"] == "in_progress"),
        "collision_lanes": len(alerts["collisions"]),
        "stale_heartbeat_lanes": len(alerts["stale_heartbeats"]),
        "superseded_lanes": len(alerts["superseded_lanes"]),
        "missing_receipt_lanes": len(alerts["missing_receipts"]),
        "scope_violation_lanes": len(alerts.get("scope_violations", [])),
        "merge_ready_lanes": len(alerts["merge_ready"]),
        "coordination_counts": coordination.get("counts", {}),
    }
    return {
        "summary": summary,
        "next_actions": next_actions,
        "alerts": alerts,
        "lanes": lanes,
    }


@dataclass
class SwarmReport:
    """Plain-English report of swarm execution for non-developer users."""

    success: bool = False
    summary: str = ""
    what_was_done: list[str] = field(default_factory=list)
    what_failed: list[str] = field(default_factory=list)
    what_to_do_next: list[str] = field(default_factory=list)

    # Details (for developer review)
    spec: SwarmSpec | None = None
    result: Any = None
    receipts: list[Any] = field(default_factory=list)
    duration_seconds: float = 0.0
    budget_spent_usd: float = 0.0

    def to_plain_text(self) -> str:
        """Render as plain text for terminal output."""
        lines = []
        lines.append("=" * 60)
        lines.append("SWARM REPORT")
        lines.append("=" * 60)
        lines.append("")

        status = "SUCCESS" if self.success else "COMPLETED WITH ISSUES"
        lines.append(f"Status: {status}")
        lines.append("")

        if self.summary:
            lines.append(self.summary)
            lines.append("")

        if self.what_was_done:
            lines.append("What was done:")
            for item in self.what_was_done:
                lines.append(f"  - {item}")
            lines.append("")

        if self.what_failed:
            lines.append("What had issues:")
            for item in self.what_failed:
                lines.append(f"  - {item}")
            lines.append("")

        if self.what_to_do_next:
            lines.append("Suggested next steps:")
            for item in self.what_to_do_next:
                lines.append(f"  - {item}")
            lines.append("")

        lines.append("-" * 60)
        if self.duration_seconds > 0:
            mins = int(self.duration_seconds // 60)
            secs = int(self.duration_seconds % 60)
            lines.append(f"Duration: {mins}m {secs}s")
        if self.budget_spent_usd > 0:
            lines.append(f"Budget spent: ${self.budget_spent_usd:.2f}")
        lines.append("=" * 60)

        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Render as Markdown for docs/reports."""
        lines = []
        lines.append("# Swarm Report")
        lines.append("")

        status = "Success" if self.success else "Completed with issues"
        lines.append(f"**Status:** {status}")
        lines.append("")

        if self.summary:
            lines.append(f"> {self.summary}")
            lines.append("")

        if self.what_was_done:
            lines.append("## What was done")
            for item in self.what_was_done:
                lines.append(f"- {item}")
            lines.append("")

        if self.what_failed:
            lines.append("## Issues")
            for item in self.what_failed:
                lines.append(f"- {item}")
            lines.append("")

        if self.what_to_do_next:
            lines.append("## Next steps")
            for item in self.what_to_do_next:
                lines.append(f"- {item}")
            lines.append("")

        lines.append("---")
        details = []
        if self.duration_seconds > 0:
            mins = int(self.duration_seconds // 60)
            secs = int(self.duration_seconds % 60)
            details.append(f"Duration: {mins}m {secs}s")
        if self.budget_spent_usd > 0:
            details.append(f"Budget: ${self.budget_spent_usd:.2f}")
        if details:
            lines.append(" | ".join(details))

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON storage/API."""
        return {
            "success": self.success,
            "summary": self.summary,
            "what_was_done": self.what_was_done,
            "what_failed": self.what_failed,
            "what_to_do_next": self.what_to_do_next,
            "duration_seconds": self.duration_seconds,
            "budget_spent_usd": self.budget_spent_usd,
            "spec": self.spec.to_dict() if self.spec else None,
        }


class SwarmReporter:
    """Generates plain-language reports from orchestration results.

    Two modes:
    1. LLM-assisted: Claude translates OrchestrationResult into plain English
    2. Template fallback: structured templates (no LLM needed)
    """

    async def generate(
        self,
        spec: SwarmSpec,
        result: Any,
        duration_seconds: float = 0.0,
    ) -> SwarmReport:
        """Generate a SwarmReport from orchestration results.

        Args:
            spec: The SwarmSpec that drove the execution.
            result: OrchestrationResult from the orchestrator.
            duration_seconds: How long execution took.

        Returns:
            A plain-English SwarmReport.
        """
        # Try LLM-assisted report generation
        report = await self._try_llm_report(spec, result, duration_seconds)
        if report is not None:
            return report

        # Fall back to template-based generation
        return self._template_report(spec, result, duration_seconds)

    async def _try_llm_report(
        self,
        spec: SwarmSpec,
        result: Any,
        duration_seconds: float,
    ) -> SwarmReport | None:
        """Try to generate report using Claude. Returns None on failure."""
        try:
            from aragora.harnesses.claude_code import ClaudeCodeHarness

            harness = ClaudeCodeHarness()
            if not await harness.initialize():
                return None

            result_summary = self._summarize_result(result, spec=spec)
            prompt = (
                "You are a CTO giving a status update to your CEO.\n"
                "Explain what your engineering team accomplished in plain, "
                "simple language. Never use jargon. Be specific about what "
                "was done -- say 'We updated the login page to show your "
                "company logo' not 'Task 3 completed successfully'.\n\n"
                f"Goal: {spec.refined_goal or spec.raw_goal}\n\n"
                f"Results:\n{result_summary}\n\n"
                "Produce a JSON object with:\n"
                '- "summary": 2-3 sentence plain English overview\n'
                '- "what_was_done": Array of bullet points (plain language)\n'
                '- "what_failed": Array of failures (plain language, empty if none)\n'
                '- "what_to_do_next": Array of actionable next steps\n\n'
                "Respond with ONLY the JSON object."
            )

            llm_result = await harness.analyze_repository(
                repo_path=Path("."),
                analysis_type=AnalysisType.GENERAL,
                prompt=prompt,
            )
            raw = llm_result.raw_output if hasattr(llm_result, "raw_output") else str(llm_result)

            import json

            data = json.loads(raw)
            return SwarmReport(
                success=self._is_success(result),
                summary=data.get("summary", ""),
                what_was_done=data.get("what_was_done", []),
                what_failed=data.get("what_failed", []),
                what_to_do_next=data.get("what_to_do_next", []),
                spec=spec,
                result=result,
                duration_seconds=duration_seconds,
                budget_spent_usd=self._extract_budget(result),
            )
        except Exception:
            logger.debug("LLM report generation failed, using template")
            return None

    def _template_report(
        self,
        spec: SwarmSpec,
        result: Any,
        duration_seconds: float,
    ) -> SwarmReport:
        """Template-based report generation (no LLM needed)."""
        total = getattr(result, "total_subtasks", 0)
        completed = getattr(result, "completed_subtasks", 0)
        failed = getattr(result, "failed_subtasks", 0)
        skipped = getattr(result, "skipped_subtasks", 0)
        success = self._is_success(result)

        goal = spec.refined_goal or spec.raw_goal

        if success:
            summary = (
                "Great news -- everything you asked for is done. "
                f"Your team finished all {total} tasks without any issues."
            )
        elif completed > 0:
            summary = (
                f'Your team made good progress on "{goal}". '
                f"They finished {completed} out of {total} tasks, "
                f"but {failed} had issues."
            )
        else:
            summary = (
                f"Your team wasn't able to complete '{goal}'. All {total} tasks ran into issues."
            )

        what_was_done = []
        what_failed = []
        assignments = getattr(result, "assignments", [])
        for assignment in assignments:
            task_title = getattr(assignment, "subtask_title", "Task")
            status = getattr(assignment, "status", "unknown")
            if status == "completed":
                what_was_done.append(task_title)
            elif status in ("failed", "error"):
                error_msg = getattr(assignment, "error", "Unknown error")
                what_failed.append(f"{task_title}: {error_msg}")

        if not what_was_done and completed > 0:
            what_was_done.append(f"{completed} tasks completed successfully")
        if not what_failed and failed > 0:
            what_failed.append(f"{failed} tasks encountered issues")

        what_to_do_next = []
        if failed > 0:
            what_to_do_next.append(
                "Some tasks had issues -- you might want to run the swarm again "
                "or have someone look into what went wrong"
            )
        if skipped > 0:
            what_to_do_next.append(
                f"{skipped} tasks were skipped and may need someone to handle them manually"
            )
        if success:
            what_to_do_next.append(
                "You might want to have someone do a quick review of the changes "
                "to make sure everything looks right"
            )

        # Add confidence level from epistemic scores if available (Phase 5)
        if hasattr(spec, "epistemic_scores") and spec.epistemic_scores:
            avg_score = spec.epistemic_scores.get("average", 0)
            if avg_score >= 0.7:
                confidence = "High"
            elif avg_score >= 0.4:
                confidence = "Medium"
            else:
                confidence = "Low"
            summary += f" Confidence level: {confidence}."

        return SwarmReport(
            success=success,
            summary=summary,
            what_was_done=what_was_done,
            what_failed=what_failed,
            what_to_do_next=what_to_do_next,
            spec=spec,
            result=result,
            duration_seconds=duration_seconds,
            budget_spent_usd=self._extract_budget(result),
        )

    def _is_success(self, result: Any) -> bool:
        """Determine if the orchestration succeeded."""
        failed = getattr(result, "failed_subtasks", 0)
        total = getattr(result, "total_subtasks", 0)
        if total == 0:
            return False
        return failed == 0

    def _extract_budget(self, result: Any) -> float:
        """Extract total cost from result."""
        return getattr(result, "total_cost_usd", 0.0)

    def _summarize_result(self, result: Any, spec: SwarmSpec | None = None) -> str:
        """Produce a text summary of OrchestrationResult for LLM consumption."""
        lines = []
        total = getattr(result, "total_subtasks", 0)
        completed = getattr(result, "completed_subtasks", 0)
        failed = getattr(result, "failed_subtasks", 0)
        skipped = getattr(result, "skipped_subtasks", 0)
        lines.append(f"Total tasks: {total}")
        lines.append(f"Completed: {completed}")
        lines.append(f"Failed: {failed}")
        lines.append(f"Skipped: {skipped}")

        assignments = getattr(result, "assignments", [])
        for assignment in assignments[:15]:
            title = getattr(assignment, "subtask_title", "Unknown")
            status = getattr(assignment, "status", "unknown")
            error = getattr(assignment, "error", "")
            line = f"  [{status}] {title}"
            if error:
                line += f" - {error}"
            lines.append(line)

        if spec and spec.proactive_suggestions:
            lines.append("\nProactive suggestions made during planning:")
            for suggestion in spec.proactive_suggestions:
                lines.append(f"  - {suggestion}")

        return "\n".join(lines)
