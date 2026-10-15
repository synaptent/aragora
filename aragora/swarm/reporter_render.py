"""Plain-text renderers for the swarm boss status and runner registration views.

``aragora.swarm.reporter`` builds the payloads and re-exports every name here, so
importing from either module yields the same objects.
"""

from __future__ import annotations

from typing import Any

from aragora.swarm.reporter_fields import _first_text, _render_repair_summary, _text


def render_runner_registration_text(payload: dict[str, Any]) -> str:
    """Render a concise runner inspection or registration summary."""
    lines = [
        f"runner_id={_text(payload.get('runner_id'))}",
        "availability="
        f"{_text(payload.get('availability'))} auth_mode={_text(payload.get('auth_mode'))}",
        f"runner_type={_text(payload.get('runner_type'))}",
    ]
    profile = _text(payload.get("profile"))
    if profile:
        lines.append(f"profile={profile}")

    owner = payload.get("owner_binding", {})
    if isinstance(owner, dict):
        lines.append(
            "owner="
            f"{_text(owner.get('user_id')) or 'unbound'}"
            f" workspace={_text(owner.get('workspace_id')) or 'none'}"
        )

    capabilities = payload.get("capabilities", {})
    if isinstance(capabilities, dict):
        lines.append(
            "capabilities="
            f"exec={capabilities.get('supports_exec', False)} "
            f"review={capabilities.get('supports_review', False)} "
            f"max_parallel={capabilities.get('max_parallel_lanes', 0)}"
        )

    if payload.get("registered"):
        lines.append(f"registered_at={_text(payload.get('registered_at'))}")
    freshness_status = _text(payload.get("freshness_status"))
    if freshness_status:
        lines.append(
            "freshness="
            f"{freshness_status} heartbeat_at={_text(payload.get('heartbeat_at')) or 'none'} "
            f"stale_after={_text(payload.get('stale_after_seconds')) or 'none'}"
        )

    status_summary = _text(payload.get("status_summary"))
    if status_summary:
        lines.append(f"status_summary={status_summary}")

    next_action = _text(payload.get("next_action"))
    if next_action:
        lines.append(f"next: {next_action}")

    return "\n".join(lines)


def _work_order_status_counts(work_orders: list[dict[str, Any]] | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in work_orders or []:
        if not isinstance(item, dict):
            continue
        status = _text(item.get("status")) or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _render_operator_status_line(operator_status: dict[str, Any]) -> str:
    source = _text(operator_status.get("source"))
    if source == "shift_ledger":
        green_shift = operator_status.get("green_shift", {})
        green_shift = green_shift if isinstance(green_shift, dict) else {}
        merged_numbers = operator_status.get("merged_pr_numbers", [])
        merged_numbers = merged_numbers if isinstance(merged_numbers, list) else []
        merged_text = ",".join(str(item) for item in merged_numbers) or "-"
        return (
            "proof-first "
            f"queue={operator_status.get('queue_depth')} "
            f"open_prs={operator_status.get('open_prs')} "
            f"boss={operator_status.get('boss_running')} "
            f"merge={operator_status.get('merge_running')} "
            f"benchmark_fresh={operator_status.get('benchmark_fresh')} "
            f"merged_prs={operator_status.get('prs_merged_recent', 0)} "
            f"merged={merged_text} "
            f"last_stop={operator_status.get('last_stop_reason') or '-'} "
            f"green_shift={green_shift.get('is_green')}"
        )
    if source == "legacy_reporter_fallback":
        return f"reporter-fallback queue={operator_status.get('queue_depth', 'unknown')}"
    return ""


def render_boss_text(payload: dict[str, Any]) -> str:
    """Render a concise boss-facing supervised swarm summary."""
    counts = payload.get("work_order_counts", {})
    counts_text = (
        ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        if isinstance(counts, dict) and counts
        else "none"
    )
    lines = [
        f"run_id={_text(payload.get('run_id'))}",
        f"status={_text(payload.get('status'))} target_branch={_text(payload.get('target_branch'))}",
        f"goal={_text(payload.get('goal'))}",
        f"work_orders=[{counts_text}]",
    ]
    operator_status = payload.get("operator_status", {})
    if isinstance(operator_status, dict):
        operator_line = _render_operator_status_line(operator_status)
        if operator_line:
            lines.append(operator_line)

    lanes = payload.get("lanes", [])
    if isinstance(lanes, list):
        for lane in lanes[:6]:
            if not isinstance(lane, dict):
                continue
            parts = [
                _text(lane.get("work_order_id")) or "lane",
                _text(lane.get("status")) or "unknown",
            ]
            branch = _text(lane.get("branch"))
            if branch:
                parts.append(f"branch={branch}")
            worktree_path = _text(lane.get("worktree_path"))
            if worktree_path:
                parts.append(f"worktree={worktree_path}")
            receipt_id = _text(lane.get("receipt_id"))
            if receipt_id:
                parts.append(f"receipt={receipt_id}")
            lines.append("lane: " + " ".join(parts))

    routing = payload.get("routing", {})
    if isinstance(routing, dict):
        selected_runner_ids = [
            _text(item) for item in routing.get("selected_runner_ids", []) if _text(item)
        ]
        selected_runners = routing.get("selected_runners", [])
        selected_runner_parts: list[str] = []
        if isinstance(selected_runners, list):
            for item in selected_runners:
                if not isinstance(item, dict):
                    continue
                runner_id = _text(item.get("runner_id"))
                if not runner_id:
                    continue
                freshness = _text(item.get("freshness_status")) or "unknown"
                selected_runner_parts.append(f"{runner_id}({freshness})")
        if selected_runner_parts:
            lines.append("routing: selected_runners=" + ",".join(selected_runner_parts))
        elif selected_runner_ids:
            lines.append("routing: selected_runners=" + ",".join(selected_runner_ids))
        blocked_reason = _text(routing.get("blocked_reason"))
        if blocked_reason:
            lines.append(f"routing_blocked: {blocked_reason}")
        rejected_runner_ids = [
            _text(item) for item in routing.get("rejected_runner_ids", []) if _text(item)
        ]
        if rejected_runner_ids:
            lines.append("routing_rejected: " + ",".join(rejected_runner_ids))
        routing_next = _text(routing.get("next_action"))
        if routing_next:
            lines.append(f"routing_next: {routing_next}")

    next_actions = payload.get("integrator_next_actions", [])
    if isinstance(next_actions, list):
        for item in next_actions[:3]:
            text = _text(item)
            if text:
                lines.append(f"next: {text}")

    needs_human = payload.get("needs_human", [])
    if isinstance(needs_human, list):
        for item in needs_human[:3]:
            if not isinstance(item, dict):
                continue
            label = _first_text(item.get("title"), item.get("work_order_id"), "lane")
            reasons = [_text(reason) for reason in item.get("reasons", []) if _text(reason)]
            summary = "; ".join(reasons) if reasons else "manual review required"
            lines.append(f"needs_human: {label} -> {summary}")
            failure_classes = [
                _text(reason) for reason in item.get("failure_classes", []) if _text(reason)
            ]
            if failure_classes:
                lines.append(f"needs_human_classes: {label} -> {','.join(failure_classes)}")
            blocker_evidence = _text(item.get("blocker_evidence"))
            if blocker_evidence:
                lines.append(f"needs_human_evidence: {label} -> {blocker_evidence}")
            repair_summary = _render_repair_summary(item.get("repair_summary"))
            if repair_summary:
                lines.append(f"needs_human_repair: {label} -> {repair_summary}")
            next_action = _text(item.get("next_action"))
            if next_action:
                lines.append(f"needs_human_next: {label} -> {next_action}")

    return "\n".join(lines)
