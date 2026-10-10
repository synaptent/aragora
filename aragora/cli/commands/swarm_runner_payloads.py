"""Runner report and probe payload builders for ``aragora swarm runner``.

``aragora.cli.commands.swarm`` re-exports every name here.
"""

from __future__ import annotations

from typing import Any

JsonDict = dict[str, Any]


def _build_runner_report_payload(
    *,
    registrations: list[JsonDict],
    routing: JsonDict,
    discovered: list[JsonDict] | None = None,
) -> JsonDict:
    rows: list[JsonDict] = []
    by_type: dict[str, dict[str, int]] = {}
    by_cost: dict[str, int] = {}
    fresh_count = 0
    probe_failed = 0
    execution_verified = 0
    for item in registrations:
        runner_type = str(item.get("runner_type", "") or "").strip() or "unknown"
        cost_class = str(item.get("cost_class", "") or "").strip() or "local"
        freshness = str(item.get("freshness_status", "") or "").strip() or "unknown"
        probe_status = str(item.get("probe_status", "") or "").strip() or None
        capabilities = dict(item.get("capabilities") or {})
        max_parallel = int(capabilities.get("max_parallel_lanes") or 1)
        claimed_lanes = int(item.get("claimed_lanes") or 0)
        active_lanes = int(capabilities.get("active_lanes") or item.get("active_lanes") or 0)
        active_lanes += claimed_lanes
        available_capacity = max(0, max_parallel - active_lanes)
        if freshness == "fresh":
            fresh_count += 1
        if probe_status == "passed":
            execution_verified += 1
        elif probe_status == "failed":
            probe_failed += 1
        by_type.setdefault(
            runner_type,
            {
                "registered": 0,
                "fresh": 0,
                "execution_verified": 0,
                "probe_failed": 0,
                "active_lanes": 0,
                "available_capacity": 0,
            },
        )
        by_type[runner_type]["registered"] += 1
        if freshness == "fresh":
            by_type[runner_type]["fresh"] += 1
        if probe_status == "passed":
            by_type[runner_type]["execution_verified"] += 1
        elif probe_status == "failed":
            by_type[runner_type]["probe_failed"] += 1
        by_type[runner_type]["active_lanes"] += active_lanes
        by_type[runner_type]["available_capacity"] += available_capacity
        by_cost[cost_class] = by_cost.get(cost_class, 0) + 1
        rows.append(
            {
                "runner_id": str(item.get("runner_id", "") or "").strip(),
                "runner_type": runner_type,
                "freshness_status": freshness,
                "cost_class": cost_class,
                "probe_status": probe_status,
                "active_lanes": active_lanes,
                "available_capacity": available_capacity,
            }
        )
    rows.sort(key=lambda row: (str(row["runner_type"]), str(row["runner_id"])))
    type_rows = [
        {"runner_type": key, **value}
        for key, value in sorted(by_type.items(), key=lambda item: item[0])
    ]
    cost_rows = [
        {"cost_class": key, "registered": value}
        for key, value in sorted(by_cost.items(), key=lambda item: item[0])
    ]
    discovered_rows = [dict(item) for item in discovered or [] if isinstance(item, dict)]
    selected_runners = [
        item for item in routing.get("selected_runners", []) if isinstance(item, dict)
    ]
    return {
        "mode": "runner",
        "action": "report",
        "summary": {
            "registered": len(registrations),
            "fresh": fresh_count,
            "execution_verified": execution_verified,
            "probe_failed": probe_failed,
            "discovered": len(discovered_rows),
            "selected_for_routing": len(selected_runners),
            "selected_verified": len(
                [
                    item
                    for item in selected_runners
                    if str(item.get("probe_status", "")).strip() == "passed"
                ]
            ),
        },
        "by_runner_type": type_rows,
        "by_cost_class": cost_rows,
        "runners": rows,
        "discovered_runners": discovered_rows,
        "routing": routing,
    }


def _build_multi_runner_payload(
    *,
    subaction: str,
    runners: list[JsonDict],
) -> JsonDict:
    return {
        "mode": "runner",
        "action": subaction,
        "summary": {
            "count": len(runners),
            "available": len(
                [
                    item
                    for item in runners
                    if str(item.get("availability", "")).strip() == "available"
                    and bool(item.get("available", True))
                ]
            ),
            "registered": len([item for item in runners if bool(item.get("registered"))]),
        },
        "runners": runners,
    }


def _build_runner_probe_payload(
    *,
    subaction: str,
    runners: list[JsonDict],
    discovered: list[JsonDict],
    routing_before: JsonDict | None = None,
    routing_after: JsonDict | None = None,
) -> JsonDict:
    attempted = len(runners)
    passed = len(
        [item for item in runners if str(item.get("probe_status", "")).strip() == "passed"]
    )
    failed = len(
        [item for item in runners if str(item.get("probe_status", "")).strip() == "failed"]
    )
    payload: JsonDict = {
        "mode": "runner",
        "action": subaction,
        "summary": {
            "discovered": len(discovered),
            "attempted": attempted,
            "passed": passed,
            "failed": failed,
        },
        "runners": runners,
        "discovered_runners": discovered,
    }
    if routing_before is not None:
        payload["routing_before"] = routing_before
        payload["summary"]["selected_before"] = len(
            [item for item in routing_before.get("selected_runners", []) if isinstance(item, dict)]
        )
    if routing_after is not None:
        payload["routing_after"] = routing_after
        selected_after = [
            item for item in routing_after.get("selected_runners", []) if isinstance(item, dict)
        ]
        execution_verified_after = len(
            [
                item
                for item in selected_after
                if str(item.get("probe_status", "")).strip() == "passed"
            ]
        )
        payload["summary"]["selected_after"] = len(selected_after)
        payload["summary"]["execution_verified_after"] = execution_verified_after
        if subaction == "maintain":
            payload["heartbeat_readiness"] = {
                "ready": execution_verified_after > 0,
                "blocked_reason": (
                    None if execution_verified_after > 0 else "no_execution_verified_runner"
                ),
                "execution_verified_count": execution_verified_after,
            }
    return payload
