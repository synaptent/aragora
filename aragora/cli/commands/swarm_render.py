"""Text renderers for ``aragora swarm`` command output.

``aragora.cli.commands.swarm`` re-exports every name here.
"""

from __future__ import annotations

from typing import Any

JsonDict = dict[str, Any]


def _format_elapsed_seconds(value: object) -> str:
    if value is None:
        return "-"
    try:
        seconds = max(0.0, float(str(value)))
    except (TypeError, ValueError):
        return "-"
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        minutes = int(seconds // 60)
        remainder = int(seconds % 60)
        return f"{minutes}m {remainder}s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes}m"


def _print_table(
    headers: list[tuple[str, str]],
    rows: list[dict[str, object]],
) -> None:
    if not rows:
        print("(no items)")
        return
    widths = {
        key: max(len(label), *(len(str(row.get(key, "") or "")) for row in rows))
        for key, label in headers
    }
    print("  ".join(label.ljust(widths[key]) for key, label in headers))
    print("  ".join("-" * widths[key] for key, _label in headers))
    for row in rows:
        print("  ".join(str(row.get(key, "") or "").ljust(widths[key]) for key, _label in headers))


def _render_initiative(item: object) -> None:
    print(f"initiative_id={getattr(item, 'initiative_id', '')}")
    print(f"title={getattr(item, 'title', '')}")
    print(f"status={getattr(item, 'status', '')}")
    feature_flag = getattr(item, "feature_flag_name", None)
    if feature_flag:
        print(f"feature_flag={feature_flag}")
    dependencies = [
        str(value).strip() for value in getattr(item, "dependencies", []) if str(value).strip()
    ]
    validations = [
        str(value).strip() for value in getattr(item, "validations", []) if str(value).strip()
    ]
    if dependencies:
        print(f"dependencies={', '.join(dependencies)}")
    if validations:
        print(f"validations={', '.join(validations)}")
    print(f"slices={len(getattr(item, 'slices', []) or [])}")
    for slice_item in getattr(item, "slices", [])[:5]:
        print(
            "  slice {slice_id} status={status} complexity={complexity} title={title}".format(
                slice_id=getattr(slice_item, "slice_id", ""),
                status=getattr(slice_item, "status", ""),
                complexity=getattr(slice_item, "estimated_complexity", ""),
                title=getattr(slice_item, "title", ""),
            )
        )


def _render_initiative_status(payload: JsonDict) -> None:
    print(
        "initiative_id={initiative_id} completed={completed}/{total} milestones={done}/{count}".format(
            initiative_id=payload.get("initiative_id", ""),
            completed=payload.get("completed_slices", 0),
            total=payload.get("total_slices", 0),
            done=payload.get("milestones_complete", 0),
            count=payload.get("milestones_total", 0),
        )
    )
    milestones = [item for item in payload.get("milestones", []) if isinstance(item, dict)]
    if milestones:
        print("\nMilestones")
        _print_table(
            [
                ("milestone", "Milestone"),
                ("completed", "Done"),
                ("total", "Total"),
                ("waiting_for_pr", "WaitPR"),
                ("waiting_for_merge", "WaitMerge"),
                ("promotable", "Promotable"),
                ("blocked", "Blocked"),
            ],
            milestones,
        )
    slices = [item for item in payload.get("slices", []) if isinstance(item, dict)]
    if slices:
        print("\nSlices")
        _print_table(
            [
                ("project_id", "Slice"),
                ("milestone", "Milestone"),
                ("status", "Status"),
                ("next_action", "Next"),
                ("pr_number", "PR"),
                ("feature_flag", "Flag"),
            ],
            slices[:10],
        )


def _render_coordination_view(view: JsonDict) -> None:
    summary = view.get("summary", {}) if isinstance(view.get("summary"), dict) else {}
    print(
        "coordination directives={directives} sessions={sessions} claims={claims} findings={findings}".format(
            directives=summary.get("directive_count", 0),
            sessions=summary.get("session_count", 0),
            claims=summary.get("claim_count", 0),
            findings=summary.get("finding_count", 0),
        )
    )
    for directive in [item for item in view.get("directives", []) if isinstance(item, dict)][:5]:
        print(
            "directive {target} status={status} task={task}".format(
                target=directive.get("target", ""),
                status=directive.get("status", ""),
                task=directive.get("task", ""),
            )
        )
        scope = [str(item) for item in directive.get("scope", []) if str(item).strip()]
        constraints = [str(item) for item in directive.get("constraints", []) if str(item).strip()]
        if scope:
            print(f"  scope: {', '.join(scope)}")
        if constraints:
            print(f"  constraints: {', '.join(constraints)}")
    for claim in [item for item in view.get("claims", []) if isinstance(item, dict)][:5]:
        paths = [str(item) for item in claim.get("paths", []) if str(item).strip()]
        print(
            "claim session={session} scope={scope} intent={intent}".format(
                session=claim.get("session_id", ""),
                scope=", ".join(paths) or "-",
                intent=claim.get("intent", "") or "-",
            )
        )
    for finding in [item for item in view.get("findings", []) if isinstance(item, dict)][:5]:
        pr = finding.get("pr")
        pr_text = f" pr=#{pr}" if pr not in (None, "", 0) else ""
        print(
            "finding {session} kind={kind}{pr} {message}".format(
                session=finding.get("source_session", "") or "-",
                kind=finding.get("kind", "finding"),
                pr=pr_text,
                message=finding.get("message", ""),
            )
        )


def _render_runner_report(payload: JsonDict) -> None:
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    print(
        "Runner Report registered={registered} fresh={fresh} discovered={discovered} selected={selected}".format(
            registered=summary.get("registered", 0),
            fresh=summary.get("fresh", 0),
            discovered=summary.get("discovered", 0),
            selected=summary.get("selected_for_routing", 0),
        )
    )
    print()
    print("By runner type")
    _print_table(
        [
            ("runner_type", "runner_type"),
            ("registered", "registered"),
            ("fresh", "fresh"),
            ("active_lanes", "active"),
            ("available_capacity", "available"),
        ],
        [item for item in payload.get("by_runner_type", []) if isinstance(item, dict)],
    )
    print()
    print("Runners")
    _print_table(
        [
            ("runner_id", "runner_id"),
            ("runner_type", "runner_type"),
            ("freshness_status", "freshness"),
            ("cost_class", "cost"),
            ("active_lanes", "active"),
            ("available_capacity", "available"),
        ],
        [item for item in payload.get("runners", []) if isinstance(item, dict)],
    )
    discovered = [item for item in payload.get("discovered_runners", []) if isinstance(item, dict)]
    if discovered:
        print()
        print("Discovered")
        _print_table(
            [
                ("runner_id", "runner_id"),
                ("runner_type", "runner_type"),
                ("profile", "profile"),
                ("auth_mode", "auth_mode"),
                ("availability", "availability"),
                ("status_summary", "status"),
            ],
            discovered,
        )
    routing = payload.get("routing", {}) if isinstance(payload.get("routing"), dict) else {}
    selected = [
        str(item.get("runner_id", "")).strip()
        for item in routing.get("selected_runners", [])
        if isinstance(item, dict) and str(item.get("runner_id", "")).strip()
    ]
    if selected:
        print()
        print(f"Routing preview: {', '.join(selected)}")
    next_action = str(routing.get("next_action", "") or "").strip()
    if next_action:
        print(f"Next: {next_action}")


def _render_tranche_queue_status(payload: JsonDict) -> None:
    elapsed = _format_elapsed_seconds(payload.get("elapsed_seconds"))
    print(
        "queue_id={queue_id} status={status} current_item_id={current_item_id} elapsed={elapsed}".format(
            queue_id=payload.get("queue_id", ""),
            status=payload.get("status", ""),
            current_item_id=payload.get("current_item_id", "") or "none",
            elapsed=elapsed,
        )
    )
    stop_reason = str(payload.get("stop_reason", "") or "").strip()
    if stop_reason:
        print(f"stop_reason={stop_reason}")
    counts = payload.get("counts", {})
    if isinstance(counts, dict):
        counts_text = ", ".join(
            f"{key}={value}" for key, value in sorted(counts.items()) if int(value or 0) > 0
        )
        if counts_text:
            print(f"counts={counts_text}")
    terminal_counts = payload.get("terminal_counts", {})
    if isinstance(terminal_counts, dict):
        terminal_text = ", ".join(
            f"{key}={value}"
            for key, value in sorted(terminal_counts.items())
            if int(value or 0) > 0
        )
        if terminal_text:
            print(f"terminal_counts={terminal_text}")
    current_item = payload.get("current_item", {})
    if isinstance(current_item, dict) and str(current_item.get("item_id", "")).strip():
        blocker = str(current_item.get("blocking_question", "") or "").strip()
        pr_urls = [
            str(pr_url).strip() for pr_url in current_item.get("pr_urls", []) if str(pr_url).strip()
        ]
        print(
            "current_item next_action={next_action} status={status} pr_urls={pr_urls}".format(
                next_action=str(current_item.get("next_action", "")).strip() or "-",
                status=str(current_item.get("status", "")).strip() or "-",
                pr_urls=", ".join(pr_urls) if pr_urls else "-",
            )
        )
        if blocker:
            print(f"current_item_blocker={blocker}")
    rows: list[JsonDict] = []
    for item in [entry for entry in payload.get("items", []) if isinstance(entry, dict)]:
        worker_branches = [
            str(branch).strip() for branch in item.get("worker_branches", []) if str(branch).strip()
        ]
        rows.append(
            {
                "item_id": str(item.get("item_id", "")).strip(),
                "status": str(item.get("status", "")).strip(),
                "phase": str(item.get("phase", "")).strip() or "-",
                "next_action": str(item.get("next_action", "")).strip() or "-",
                "pr_url": str(item.get("pr_url", "")).strip() or "-",
                "worker_branch": (
                    str(item.get("worker_branch", "")).strip() or ", ".join(worker_branches) or "-"
                ),
                "elapsed": _format_elapsed_seconds(item.get("elapsed_seconds")),
            }
        )
    print()
    _print_table(
        [
            ("item_id", "item_id"),
            ("status", "status"),
            ("phase", "phase"),
            ("next_action", "next_action"),
            ("pr_url", "pr_url"),
            ("worker_branch", "worker_branch"),
            ("elapsed", "elapsed"),
        ],
        rows,
    )


def _print_supervisor_run(run: JsonDict) -> None:
    work_orders = (
        list(run.get("work_orders", [])) if isinstance(run.get("work_orders"), list) else []
    )
    counts: dict[str, int] = {}
    for item in work_orders:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    counts_text = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"
    print(f"run_id={run.get('run_id', '')}")
    print(f"status={run.get('status', '')} target_branch={run.get('target_branch', '')}")
    print(f"goal={run.get('goal', '')}")
    print(f"work_orders={len(work_orders)} [{counts_text}]")


def _render_tranche_queue_harvest_table(payload: JsonDict) -> None:
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    rows = [
        ("total items", int(summary.get("total_items", 0) or 0)),
        ("PRs created", int(summary.get("prs_created", 0) or 0)),
        ("completed", int(summary.get("completed", 0) or 0)),
        ("needs_human", int(summary.get("needs_human", 0) or 0)),
        ("failed", int(summary.get("failed", 0) or 0)),
    ]
    metric_width = max(len("metric"), *(len(label) for label, _ in rows))
    count_width = max(len("count"), *(len(str(value)) for _, value in rows))
    queue_id = str(payload.get("queue_id", "") or "").strip()
    status = str(payload.get("status", "") or "").strip()

    title = f"Tranche Queue Harvest ({queue_id})" if queue_id else "Tranche Queue Harvest"
    print(title)
    if status:
        print(f"status={status}")
    if bool(payload.get("dry_run", False)):
        print("dry_run=true")
        if bool(payload.get("requested_execute_merge", False)):
            print("requested_execute_merge=true")
    print()
    print(f"{'metric':<{metric_width}}  {'count':>{count_width}}")
    print(f"{'-' * metric_width}  {'-' * count_width}")
    for label, value in rows:
        print(f"{label:<{metric_width}}  {value:>{count_width}}")


def _render_integrator_table(view: JsonDict) -> None:
    summary = view.get("summary", {}) if isinstance(view.get("summary"), dict) else {}
    print(f"Swarm Integrator View ({summary.get('total_lanes', 0)} lanes)")
    print(
        "  ready={ready} blocked={blocked} review={review} stale={stale} superseded={superseded}".format(
            ready=summary.get("ready_lanes", 0),
            blocked=summary.get("blocked_lanes", 0),
            review=summary.get("review_lanes", 0),
            stale=summary.get("stale_heartbeat_lanes", 0),
            superseded=summary.get("superseded_lanes", 0),
        )
    )
    print()
    icons = {"ready": "+", "blocked": "!", "review": "?", "merged": "=", "superseded": "x"}
    lanes = [item for item in view.get("lanes", []) if isinstance(item, dict)]
    for lane in lanes:
        readiness = str(lane.get("merge_readiness", "unknown"))
        icon = icons.get(readiness, " ")
        canonical = "*" if bool(lane.get("canonical_lane")) else " "
        print(f"{canonical}[{icon}] {lane.get('title', 'untitled')}")
        print(
            "    lane_id={lane_id} branch={branch} readiness={readiness} status={status}".format(
                lane_id=lane.get("lane_id", ""),
                branch=lane.get("branch", ""),
                readiness=readiness,
                status=lane.get("status", ""),
            )
        )
        receipt_id = str(lane.get("receipt_id", "") or "").strip()
        lease_id = str(lane.get("lease_id", "") or "").strip()
        if receipt_id or lease_id:
            print(f"    receipt={receipt_id or 'none'} lease={lease_id or 'none'}")
        blockers = lane.get("blockers", [])
        if isinstance(blockers, list) and blockers:
            print(f"    blockers: {', '.join(str(item) for item in blockers)}")
        next_action = str(lane.get("next_action", "") or "").strip()
        if next_action:
            print(f"    next: {next_action}")
        print()
    for action_text in [item for item in view.get("next_actions", []) if str(item).strip()][:5]:
        print(f"next: {action_text}")
