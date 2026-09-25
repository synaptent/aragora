"""Swarm Commander CLI command.

Launches the full swarm lifecycle: interrogate -> spec -> dispatch -> report.

Usage:
    aragora swarm "Make the dashboard faster"
    aragora swarm "Fix tests" --skip-interrogation
    aragora swarm --spec my-spec.yaml
    aragora swarm "Add auth" --budget-limit 10
    aragora swarm "Improve UX" --dry-run
    aragora swarm "Build feature" --profile cto
    aragora swarm --from-obsidian ~/vault
    aragora swarm "Improve tests" --autonomy metrics
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Coroutine, TypeVar
from uuid import uuid4

logger = logging.getLogger(__name__)

JsonDict = dict[str, Any]
T = TypeVar("T")


# ``DevCoordinationStore`` is an optional dependency: importing it pulls in
# nomic coordination state which may not be available in every environment.
# To keep mypy type narrowing intact without losing the runtime fallback,
# we expose the type to type-checkers unconditionally while tolerating
# runtime import failures.
if TYPE_CHECKING:
    from aragora.nomic.dev_coordination import (  # noqa: F401
        DevCoordinationStore as DevCoordinationStore,
    )
else:
    try:
        from aragora.nomic.dev_coordination import DevCoordinationStore
    except (ImportError, RuntimeError, OSError, ValueError):  # pragma: no cover - defensive
        DevCoordinationStore = None  # type: ignore[misc,assignment]


def _dev_coordination_store_cls() -> "type[DevCoordinationStore] | None":
    """Return the optional :class:`DevCoordinationStore` class or ``None``.

    Centralised helper so callers do not have to re-import the class or
    re-check the optional-dependency sentinel on every use. Returning a
    narrow ``type | None`` keeps mypy happy on both branches.
    """

    return DevCoordinationStore if DevCoordinationStore is not None else None


def _resolve_swarm_action_goal(args: argparse.Namespace) -> tuple[str, str | None]:
    first = getattr(args, "swarm_action_or_goal", None)
    second = getattr(args, "swarm_goal", None)
    if first in {
        "run",
        "preflight",
        "boss",
        "boss-loop",
        "audit-issues",
        "runner",
        "status",
        "shift-status",
        "harness-status",
        "reconcile",
        "initiative",
        "campaign",
        "initiative",
        "integrator",
        "tranche",
        "coord",
        "assign",
        "claim-pr",
        "report",
        "findings",
        "merge-arbiter",
        "dispatch",
    }:
        return str(first), second
    return "run", first


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_csv_set(value: object) -> set[str] | None:
    text = _optional_text(value)
    if not text:
        return None
    result = {item.strip() for item in text.split(",") if item.strip()}
    return result or None


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


def _initiative_rows(items: "Sequence[object]") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in items:
        rows.append(
            {
                "initiative_id": getattr(item, "initiative_id", "") or "",
                "status": getattr(item, "status", "") or "",
                "feature_flag": getattr(item, "feature_flag_name", "") or "-",
                "slices": len(getattr(item, "slices", []) or []),
                "title": getattr(item, "title", "") or "",
                "updated_at": getattr(item, "updated_at", "") or "",
            }
        )
    return rows


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


def _coordination_session_id(args: argparse.Namespace) -> str:
    explicit = _optional_text(getattr(args, "session_id", None))
    if explicit:
        return explicit
    for env_name in ("ARAGORA_SESSION_ID", "ARAGORA_AGENT_SESSION_ID", "ARAGORA_SWARM_SESSION_ID"):
        from_env = _optional_text(os.environ.get(env_name))
        if from_env:
            return from_env
    for env_name in ("ARAGORA_AGENT", "ARAGORA_AGENT_NAME"):
        agent_name = _optional_text(os.environ.get(env_name))
        if agent_name:
            return f"{agent_name}-{os.getpid()}"
    return f"session-{os.getpid()}"


def _coordination_assigned_by(args: argparse.Namespace) -> str:
    explicit = _optional_text(getattr(args, "assigned_by", None))
    if explicit:
        return explicit
    from_env = _optional_text(os.environ.get("ARAGORA_BOSS_SESSION_ID"))
    if from_env:
        return from_env
    return f"boss-{os.getpid()}"


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


def _trim_command_output(text: str, *, limit: int = 240) -> str | None:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


_UNSAFE_VALIDATION_SHELL_FRAGMENTS = (
    "|",
    "&&",
    "||",
    ";",
    "<",
    ">",
    "$(",
    "`",
    "\n",
    "\r",
)

# Keep boss-loop iteration output readable without hiding the lane signal
# entirely when multiple inferred hints are available.
MAX_DISPLAYED_LANE_HINTS = 2


def _probe_validation_command(
    command: str,
    *,
    repo_root: Path,
    timeout_seconds: float,
) -> dict[str, object]:
    normalized = str(command or "").strip()
    if not normalized:
        return {
            "command": command,
            "status": "unsafe",
            "detail": "empty validation command",
        }
    for fragment in _UNSAFE_VALIDATION_SHELL_FRAGMENTS:
        if fragment in normalized:
            return {
                "command": command,
                "status": "unsafe",
                "detail": (
                    "shell operators are not allowed in auto-probed validation commands; "
                    "use a single direct command instead"
                ),
            }
    try:
        argv = shlex.split(normalized, posix=True)
    except ValueError as exc:
        return {
            "command": command,
            "status": "unsafe",
            "detail": f"invalid shell quoting: {exc}",
        }
    if not argv:
        return {
            "command": command,
            "status": "unsafe",
            "detail": "empty validation command",
        }
    try:
        proc = subprocess.run(
            argv,
            cwd=str(repo_root),
            text=True,
            capture_output=True,
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "status": "timeout",
            "stdout": _trim_command_output(getattr(exc, "stdout", "") or ""),
            "stderr": _trim_command_output(getattr(exc, "stderr", "") or ""),
        }
    except (FileNotFoundError, OSError) as exc:
        return {
            "command": command,
            "status": "error",
            "stderr": _trim_command_output(str(exc)),
        }

    return {
        "command": command,
        "status": "passed" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "stdout": _trim_command_output(proc.stdout),
        "stderr": _trim_command_output(proc.stderr),
    }


def _classify_issue_validation_status(
    *,
    validation_contract: list[str],
    commands: list[str],
    probe_results: list[dict[str, object]],
) -> tuple[str, str]:
    if not validation_contract:
        return (
            "missing_validation_contract",
            "Add an Acceptance Criteria, Validation, or Test section with at least one concrete command.",
        )
    if not commands:
        return (
            "non_runnable_validation_contract",
            "Rewrite the validation contract so it contains runnable commands instead of prose.",
        )
    if probe_results and all(str(item.get("status")) == "passed" for item in probe_results):
        return (
            "passes_now",
            "Issue validations already pass on the current branch; close, relabel, or rewrite the stale queue item.",
        )
    first_failure = next(
        (item for item in probe_results if str(item.get("status")) != "passed"),
        None,
    )
    command = str(first_failure.get("command") if isinstance(first_failure, dict) else "")
    returncode_value = first_failure.get("returncode") if isinstance(first_failure, dict) else None
    returncode = int(returncode_value) if isinstance(returncode_value, int) else None
    stdout_text = str(first_failure.get("stdout") if isinstance(first_failure, dict) else "" or "")
    stderr_text = str(first_failure.get("stderr") if isinstance(first_failure, dict) else "" or "")
    combined_output = f"{stdout_text}\n{stderr_text}".lower()
    if isinstance(first_failure, dict) and str(first_failure.get("status")) == "unsafe":
        return (
            "unsafe_validation_contract",
            "Rewrite the validation contract as a single direct command without shell pipelines, redirects, or chaining.",
        )
    if command.startswith("python3 -m aragora.cli.main ") and (
        returncode in {1, 2}
        and ("unrecognized arguments" in combined_output or "usage: main.py" in combined_output)
    ):
        return (
            "cli_usage_failure",
            "The current Aragora parser rejects this queued CLI command. Refresh the contract if the flags were renamed, or keep the issue queued if it is meant to add that CLI surface.",
        )
    if returncode == 5 and (
        command.startswith("pytest ")
        or command.startswith("python -m pytest ")
        or command.startswith("python3 -m pytest ")
    ):
        return (
            "no_matching_tests_collected",
            "The queued pytest selector collects no tests on the current branch. Refresh the selector if tests moved, or keep the issue queued if the expected coverage has not been added yet.",
        )
    if any(
        cmd.startswith(prefix)
        for cmd in commands
        for prefix in (
            "pytest tests/ -q",
            "python -m pytest tests/ -q",
            "python3 -m pytest tests/ -q",
        )
    ):
        return (
            "broad_validation_contract",
            "Replace the broad test-suite command with focused validation tied to the intended file scope.",
        )
    return (
        "validation_fails_now",
        "Validation still fails on the current branch; confirm whether the issue remains real or the contract is stale.",
    )


def _audit_issue_validation_contract(
    issue: object,
    *,
    repo_root: Path,
    timeout_seconds: float = 45.0,
) -> dict[str, object]:
    from aragora.swarm.boss_loop import (
        extract_issue_validation_contract,
        extract_pre_dispatch_validation_commands,
    )

    body = str(getattr(issue, "body", "") or "")
    validation_contract = extract_issue_validation_contract(body)
    commands = extract_pre_dispatch_validation_commands(body)
    probe_results: list[dict[str, object]] = []

    for command in commands:
        result = _probe_validation_command(
            command,
            repo_root=repo_root,
            timeout_seconds=timeout_seconds,
        )
        probe_results.append(result)
        if result["status"] != "passed":
            break

    status, next_action = _classify_issue_validation_status(
        validation_contract=validation_contract,
        commands=commands,
        probe_results=probe_results,
    )
    return {
        "number": int(getattr(issue, "number", 0) or 0),
        "title": str(getattr(issue, "title", "") or "").strip(),
        "url": str(getattr(issue, "url", "") or "").strip(),
        "labels": list(getattr(issue, "labels", []) or []),
        "validation_contract": validation_contract,
        "commands": commands,
        "probe_results": probe_results,
        "status": status,
        "next_action": next_action,
    }


@contextmanager
def _open_audit_checkout(repo_root: Path, *, git_ref: str | None):
    if not git_ref:
        yield repo_root
        return

    with tempfile.TemporaryDirectory(prefix="aragora-audit-") as temp_dir:
        checkout_root = Path(temp_dir) / "checkout"
        add_proc = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "worktree",
                "add",
                "--detach",
                str(checkout_root),
                git_ref,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if add_proc.returncode != 0:
            stderr = _trim_command_output(add_proc.stderr or "") or "git worktree add failed"
            raise RuntimeError(f"Failed to open audit checkout for {git_ref}: {stderr}")
        try:
            yield checkout_root
        finally:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "worktree",
                    "remove",
                    "--force",
                    str(checkout_root),
                ],
                text=True,
                capture_output=True,
                check=False,
            )


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


def _run_supervised_or_report(awaitable: Coroutine[Any, Any, T]) -> T | None:
    try:
        return asyncio.run(awaitable)
    except ValueError as exc:
        print(f"Error: {exc}")
        return None


def _probe_limit_arg(args: argparse.Namespace, *, default: int = 1) -> int:
    raw = getattr(args, "probe_limit", default)
    try:
        return max(1, int(raw or default))
    except (TypeError, ValueError):
        return default


def _load_structured_object(source: str) -> JsonDict:
    if source == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(source).read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-untyped]

        payload = yaml.safe_load(raw) or {}
    except ImportError:
        payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("structured input must deserialize to an object")
    return dict(payload)


def _build_boss_payload(
    run: JsonDict,
    *,
    repo_root: Path,
    target_branch: str,
    routing: JsonDict | None = None,
) -> JsonDict:
    from aragora.swarm.reporter import build_boss_payload, build_integrator_view
    from aragora.worktree.fleet import FleetCoordinationStore, build_fleet_rows

    dev_store_cls = _dev_coordination_store_cls()

    worktrees = build_fleet_rows(
        repo_root,
        base_branch=target_branch,
        tail=0,
        include_git_metrics=False,
    )
    fleet_store = FleetCoordinationStore(repo_root)
    claims = fleet_store.list_claims()
    merge_queue = fleet_store.list_merge_queue()
    # Fleet-only coordination has no dedicated status summary; the richer
    # integrator view is populated from ``DevCoordinationStore`` below when
    # it is available.
    coordination: JsonDict = {}
    if dev_store_cls is not None:
        try:
            coordination = dict(
                dev_store_cls(repo_root=repo_root).status_summary(include_integrator_artifacts=True)
            )
        except (RuntimeError, OSError, ValueError) as exc:
            logger.debug("coordination_status_fetch_failed: %s: %s", type(exc).__name__, exc)
    integrator_view = build_integrator_view(
        runs=[run],
        worktrees=worktrees,
        claims=claims,
        merge_queue=merge_queue,
        coordination=coordination,
    )
    return build_boss_payload(
        run=run,
        integrator_view=integrator_view,
        coordination=coordination,
        routing=routing,
    )


def _resolve_boss_routing(
    *,
    requested_runner_type: str | None = None,
    allowed_profiles: set[str] | None = None,
    rotation_interval_seconds: float = 1800.0,
) -> dict[str, object]:
    from aragora.swarm.runner_registry import (
        LocalRunnerRegistry,
        authorization_context_with_defaults,
    )

    owner_context = authorization_context_with_defaults(repo_root=Path.cwd())
    return (
        LocalRunnerRegistry()
        .resolve_boss_routing(
            owner_context=owner_context,
            requested_runner_type=requested_runner_type,
            allowed_profiles=allowed_profiles,
            rotation_interval_seconds=rotation_interval_seconds,
        )
        .to_dict()
    )


def _blocked_boss_payload(
    *,
    goal: str | None,
    target_branch: str,
    routing: dict[str, object],
) -> dict[str, object]:
    next_action = str(routing.get("next_action", "")).strip()
    return {
        "mode": "boss",
        "run_id": None,
        "status": "blocked",
        "goal": goal or "",
        "target_branch": target_branch,
        "work_order_counts": {},
        "lanes": [],
        "integrator_next_actions": [next_action] if next_action else [],
        "needs_human": [],
        "coordination_counts": {},
        "integrator_summary": {},
        "routing": routing,
    }


def _load_integrator_view(repo_root: Path, *, base_branch: str) -> dict[str, object]:
    from aragora.swarm.reporter import build_integrator_view
    from aragora.worktree.fleet import FleetCoordinationStore, build_fleet_rows

    dev_store_cls = _dev_coordination_store_cls()

    worktrees = build_fleet_rows(
        repo_root,
        base_branch=base_branch,
        tail=0,
        include_git_metrics=False,
    )
    fleet_store = FleetCoordinationStore(repo_root)
    claims = fleet_store.list_claims()
    merge_queue = fleet_store.list_merge_queue()
    coordination: dict[str, object] = {}
    if dev_store_cls is not None:
        try:
            coordination = dict(
                dev_store_cls(repo_root=repo_root).status_summary(include_integrator_artifacts=True)
            )
        except (RuntimeError, OSError, ValueError):
            coordination = {}
    return build_integrator_view(
        runs=[],
        worktrees=worktrees,
        claims=claims,
        merge_queue=merge_queue,
        coordination=coordination,
    )


def _find_integrator_lane(
    view: JsonDict,
    *,
    lane_id: str = "",
    receipt_id: str = "",
    lease_id: str = "",
    branch: str = "",
) -> JsonDict | None:
    lanes = [item for item in view.get("lanes", []) if isinstance(item, dict)]
    lane_id = str(lane_id or "").strip()
    receipt_id = str(receipt_id or "").strip()
    lease_id = str(lease_id or "").strip()
    branch = str(branch or "").strip()

    if lane_id:
        for lane in lanes:
            if str(lane.get("lane_id", "")).strip() == lane_id:
                return lane
        return None
    if receipt_id:
        for lane in lanes:
            if str(lane.get("receipt_id", "")).strip() == receipt_id:
                return lane
        return None
    if lease_id:
        for lane in lanes:
            if str(lane.get("lease_id", "")).strip() == lease_id:
                return lane
        return None
    if branch:
        canonical = [
            lane
            for lane in lanes
            if str(lane.get("branch", "")).strip() == branch and bool(lane.get("canonical_lane"))
        ]
        if canonical:
            return canonical[0]
        for lane in lanes:
            if str(lane.get("branch", "")).strip() == branch:
                return lane
    return None


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


def cmd_swarm(args: argparse.Namespace) -> None:
    """Handle 'swarm' command."""
    from aragora.swarm import (
        SwarmApprovalPolicy,
        SwarmCommander,
        SwarmCommanderConfig,
        SwarmReconciler,
        SwarmSpec,
        SwarmSupervisor,
    )
    from aragora.swarm.config import (
        AutonomyLevel,
        InterrogatorConfig,
        UserProfile,
    )
    from aragora.swarm.reporter import build_integrator_view
    from aragora.worktree.fleet import (
        FleetCoordinationStore,
        build_fleet_rows,
        resolve_repo_root,
    )

    # ``payload`` and ``response`` are reused across action branches with
    # heterogeneous concrete types (dict literals, dataclass.to_dict() results,
    # helper returns). Pinning them to ``JsonDict`` here lets mypy narrow
    # each assignment locally without the whole-function union drift that
    # previously inferred ``dict[str, Collection[str] | None]``.
    payload: JsonDict = {}
    response: JsonDict = {}

    action, goal = _resolve_swarm_action_goal(args)
    spec_file = getattr(args, "spec", None)
    skip_interrogation = getattr(args, "skip_interrogation", False)
    dry_run = getattr(args, "dry_run", False)
    budget_limit = getattr(args, "budget_limit", 50.0)
    require_approval = getattr(args, "require_approval", False)
    max_parallel = getattr(args, "max_parallel", 20)
    concurrency_cap = min(max(1, int(getattr(args, "concurrency_cap", 8))), 8)
    no_loop = getattr(args, "no_loop", False)
    target_branch = getattr(args, "target_branch", "main")
    skip_publication = bool(getattr(args, "skip_publication", False))
    managed_dir_pattern = getattr(args, "managed_dir_pattern", ".worktrees/{agent}-auto")
    as_json = bool(getattr(args, "json", False))
    run_id = getattr(args, "run_id", None)
    refresh_scaling = bool(getattr(args, "refresh_scaling", False))
    no_dispatch = bool(getattr(args, "no_dispatch", False))
    watch = bool(getattr(args, "watch", False))
    claude_runner_profiles = _optional_text(getattr(args, "claude_runner_profiles", None))
    allowed_runner_profiles = _parse_csv_set(claude_runner_profiles)
    runner_rotation_interval = float(getattr(args, "runner_rotation_interval", 1800.0) or 1800.0)
    interval_seconds = float(getattr(args, "interval_seconds", 5.0) or 5.0)
    max_ticks = getattr(args, "max_ticks", None)
    all_runs = bool(getattr(args, "all_runs", False))
    dispatch_only = bool(getattr(args, "dispatch_only", False))
    no_wait = bool(getattr(args, "no_wait", False))
    allow_claude_write = bool(getattr(args, "allow_claude_write", False))
    dispatch_workers = not no_dispatch
    boss_mode = action == "boss"
    boss_routing: dict[str, object] | None = None
    if dispatch_only:
        no_wait = True
    if boss_mode:
        dispatch_workers = True
        no_wait = False
        concurrency_cap = max(4, concurrency_cap)

    # Phase 2: User profile
    profile_str = getattr(args, "profile", "ceo")
    profile_map = {
        "ceo": UserProfile.CEO,
        "cto": UserProfile.CTO,
        "developer": UserProfile.DEVELOPER,
        "power-user": UserProfile.POWER_USER,
    }
    user_profile = profile_map.get(profile_str, UserProfile.CEO)

    # Phase 4: Obsidian
    from_obsidian = getattr(args, "from_obsidian", None)
    obsidian_vault = getattr(args, "obsidian_vault", None)
    no_obsidian_receipts = getattr(args, "no_obsidian_receipts", False)

    # Phase 6: Autonomy
    autonomy_str = getattr(args, "autonomy", "propose")
    autonomy_map = {
        "full-auto": AutonomyLevel.FULL_AUTO,
        "propose": AutonomyLevel.PROPOSE_APPROVE,
        "guided": AutonomyLevel.HUMAN_GUIDED,
        "metrics": AutonomyLevel.METRICS_DRIVEN,
    }
    autonomy_level = autonomy_map.get(autonomy_str, AutonomyLevel.PROPOSE_APPROVE)

    if action == "preflight":
        from aragora.swarm.credential_envelope import CredentialEnvelope
        from aragora.swarm.preflight import (
            evaluate_preflight_receipt_gate,
            run_contract_preflight_receipt,
            run_preflight,
        )

        repo_root = resolve_repo_root(Path.cwd())
        contract_arg = getattr(args, "contract", None)
        if contract_arg:
            contract_path = Path(str(contract_arg)).expanduser()
            envelope = CredentialEnvelope.from_environment(os.environ)
            receipt = run_contract_preflight_receipt(
                repo_root=repo_root,
                agent=str(getattr(args, "worker_model", "claude") or "claude"),
                base_ref=str(target_branch or "main"),
                skip_publication=skip_publication,
                contract_path=contract_path,
                envelope=envelope,
            )
            expected_contract_checksum = str(
                receipt.artifacts.get("expected_contract_checksum", "") or ""
            ).strip()
            admission_gate = evaluate_preflight_receipt_gate(
                receipt,
                repo_root=repo_root,
                envelope=envelope,
                check_type="scratch" if skip_publication else "remote_publish",
                base_ref=str(target_branch or "main"),
                expected_contract_checksum=expected_contract_checksum,
            )
            failure_terminal_class = receipt.failure_terminal_class
            payload = {
                "mode": "swarm-preflight",
                "receipt": receipt.to_dict(),
                "admission_gate": admission_gate.to_dict(),
                "failure_terminal_class": (
                    failure_terminal_class.value if failure_terminal_class is not None else None
                ),
            }
        else:
            preflight_result = run_preflight(
                repo_root=repo_root,
                agent=str(getattr(args, "worker_model", "claude") or "claude"),
                base_ref=str(target_branch or "main"),
                skip_publication=skip_publication,
                contract_path=None,
            )
            payload = {"mode": "swarm-preflight", **preflight_result.to_dict()}
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            if contract_arg:
                receipt_payload = dict(payload.get("receipt", {}) or {})
                gate_payload = dict(payload.get("admission_gate", {}) or {})
                print(f"swarm preflight: {gate_payload.get('verdict', 'blocked')}")
                print(f"receipt_id={receipt_payload.get('receipt_id', '')}")
                print(f"check_type={receipt_payload.get('check_type', '')}")
                print(f"passed={receipt_payload.get('passed', False)}")
                print(f"expires_at={receipt_payload.get('expires_at', '')}")
                failure_terminal_text = str(payload.get("failure_terminal_class", "") or "").strip()
                if failure_terminal_text:
                    print(f"failure_terminal_class={failure_terminal_text}")
            else:
                preflight_passed = bool(payload.get("passed", False))
                print(f"swarm preflight: {'ok' if preflight_passed else 'blocked'}")
                print(f"repo_root={payload['repo_root']}")
                print(f"agent={payload['agent']}")
                print(f"base_ref={payload['base_ref']}")
                print(f"branch={payload['branch']}")
                worker = payload.get("worker", {})
                checksum = str(worker.get("worker_contract_checksum", "")).strip()
                if checksum:
                    print(f"worker_contract_checksum={checksum}")
        if contract_arg and payload["admission_gate"]["verdict"] != "pass":
            raise SystemExit(2)
        if not contract_arg and not bool(payload.get("passed", False)):
            raise SystemExit(2)
        return

    if action in {"coord", "assign", "claim-pr", "report", "findings"}:
        from aragora.swarm.session_coordinator import (
            claim_pr as coord_claim_pr,
            list_findings as coord_list_findings,
            read_directives as coord_read,
            report_finding as coord_report_finding,
            set_assignment as coord_set_assignment,
        )
        from aragora.worktree.fleet import resolve_repo_root

        repo_root = resolve_repo_root(Path.cwd())
        findings_limit = max(1, int(getattr(args, "findings_limit", 10)))
        session_id = _coordination_session_id(args)

        if action == "coord":
            payload = coord_read(repo_root, findings_limit=findings_limit)
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                _render_coordination_view(payload)
            return

        if action == "assign":
            target_session = _optional_text(goal)
            task_text = _optional_text(getattr(args, "swarm_campaign_target", None))
            if not target_session or not task_text:
                print('Error: usage: aragora swarm assign <session-id> "task description"')
                return
            payload = coord_set_assignment(
                target_session,
                task_text,
                scope=[
                    str(item) for item in (getattr(args, "scope", None) or []) if str(item).strip()
                ],
                constraints=[
                    str(item)
                    for item in (getattr(args, "constraint", None) or [])
                    if str(item).strip()
                ],
                status=str(getattr(args, "directive_status", "active") or "active"),
                issued_by=_coordination_assigned_by(args),
                repo_root=repo_root,
            )
            response = {"mode": "coordination-assign", "directive": payload}
            if as_json:
                print(json.dumps(response, indent=2))
            else:
                print(f"assigned {payload.get('target', '')}: {payload.get('task', '')}")
            return

        if action == "claim-pr":
            pr_text = _optional_text(goal)
            if not pr_text:
                print("Error: usage: aragora swarm claim-pr <pr-number>")
                return
            try:
                pr_number = int(pr_text)
            except ValueError:
                print(f"Error: invalid PR number: {pr_text}")
                return
            payload = dict(
                coord_claim_pr(
                    pr_number,
                    session_id,
                    intent=_optional_text(getattr(args, "claim_intent", None)) or "",
                    ttl_minutes=max(1, int(getattr(args, "ttl_minutes", 30) or 30)),
                    repo_root=repo_root,
                )
            )
            response = {"mode": "coordination-claim-pr", "pr": pr_number, **payload}
            if as_json:
                print(json.dumps(response, indent=2))
            else:
                status_text = str(payload.get("status", "unknown"))
                if status_text == "granted":
                    print(f"claimed PR#{pr_number} for {session_id}")
                else:
                    owners = [
                        str(item.get("session_id", ""))
                        for item in payload.get("contested_by", [])
                        if isinstance(item, dict)
                    ]
                    print(
                        f"PR#{pr_number} claim contested for {session_id}"
                        + (f" (also claimed by {', '.join(owners)})" if owners else "")
                    )
            return

        if action == "report":
            message = _optional_text(goal)
            if not message:
                print('Error: usage: aragora swarm report "finding text"')
                return
            payload = coord_report_finding(
                message,
                session_id,
                kind=_optional_text(getattr(args, "kind", None)) or "finding",
                pr=getattr(args, "pr", None),
                scope=[
                    str(item) for item in (getattr(args, "scope", None) or []) if str(item).strip()
                ],
                repo_root=repo_root,
            )
            response = {"mode": "coordination-report", "finding": payload}
            if as_json:
                print(json.dumps(response, indent=2))
            else:
                print(f"reported {payload.get('kind', 'finding')} from {session_id}")
            return

        findings = coord_list_findings(
            limit=findings_limit,
            session_id=_optional_text(getattr(args, "session_id", None)),
            kind=_optional_text(getattr(args, "kind", None)),
            pr=getattr(args, "pr", None),
            repo_root=repo_root,
        )
        if as_json:
            print(json.dumps({"mode": "coordination-findings", "findings": findings}, indent=2))
        elif not findings:
            print("No findings reported yet.")
        else:
            for finding in findings:
                pr_value = finding.get("pr")
                pr_text = f" pr=#{pr_value}" if pr_value not in (None, "", 0) else ""
                print(
                    "[{session}] {kind}{pr} {message}".format(
                        session=finding.get("source_session", "-") or "-",
                        kind=finding.get("kind", "finding"),
                        pr=pr_text,
                        message=finding.get("message", ""),
                    )
                )
        return

    if action == "dispatch":
        from aragora.swarm.runbook_dispatcher import dispatch_runbook, resolve_runbook_path
        from aragora.worktree.fleet import resolve_repo_root

        repo_root = resolve_repo_root(Path.cwd())
        runbook_name = _optional_text(getattr(args, "runbook", None)) or _optional_text(goal)
        if not runbook_name:
            print("Error: usage: aragora swarm dispatch <runbook-name>", file=sys.stderr)
            sys.exit(1)
        runbook_path = resolve_runbook_path(runbook_name, repo_root)
        if not runbook_path.exists():
            print(f"Error: runbook not found: {runbook_path}", file=sys.stderr)
            sys.exit(1)
        issued_by = _coordination_assigned_by(args)
        dry_run = bool(getattr(args, "dry_run", False))
        dispatch_result: JsonDict = dispatch_runbook(
            runbook_path,
            issued_by=issued_by,
            repo_root=repo_root,
            dry_run=dry_run,
        )
        if as_json:
            print(json.dumps(dispatch_result, indent=2))
        else:
            print(
                f"runbook={dispatch_result.get('name', '')} "
                f"dispatched={len(dispatch_result.get('directives', []))}"
            )
            for directive in dispatch_result.get("directives", []):
                target = directive.get("target", "")
                task = str(directive.get("task", "") or "")
                task_summary = task.splitlines()[0] if task else ""
                print(f"  {target}: {task_summary}")
        return

    if action == "initiative":
        from aragora.swarm.initiative_campaign_bridge import sync_campaign_manifest_for_initiative
        from aragora.swarm.initiative_integrator import (
            DEFAULT_INITIATIVE_MANIFEST,
            InitiativeIntegrator,
        )
        from aragora.swarm.initiative_planner import InitiativePlanner
        from aragora.swarm.initiative_store import InitiativeStore

        subaction = str(goal or "list").strip().lower() or "list"
        if subaction not in {"plan", "show", "list", "run", "status", "promote"}:
            raise ValueError(
                "initiative action must be one of: plan, show, list, run, status, promote"
            )

        repo_root = resolve_repo_root(Path.cwd())
        initiative_dir = _optional_text(getattr(args, "initiative_dir", None))
        state_dir = Path(initiative_dir).expanduser().resolve() if initiative_dir else None
        store = InitiativeStore(repo_root=repo_root, state_dir=state_dir)
        if subaction in {"run", "status", "promote"}:
            target_text = _optional_text(getattr(args, "swarm_campaign_target", None))
            explicit_manifest = _optional_text(getattr(args, "manifest", None))
            project_id = target_text if explicit_manifest and subaction == "promote" else None
            if explicit_manifest:
                manifest_path = Path(explicit_manifest).resolve()
            elif target_text:
                initiative = store.get(target_text)
                if initiative is None:
                    raise FileNotFoundError(f"initiative not found: {target_text}")
                manifest_path = sync_campaign_manifest_for_initiative(
                    store,
                    initiative,
                    planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
                    planner_strategy=str(
                        getattr(args, "planner_strategy", "heuristic") or "heuristic"
                    ),
                    worker_model=str(getattr(args, "worker_model", "claude") or "claude"),
                    review_model=str(getattr(args, "review_model", "codex") or "codex"),
                )
            else:
                manifest_path = Path(DEFAULT_INITIATIVE_MANIFEST).resolve()
            if not manifest_path.exists():
                raise ValueError(f"initiative manifest not found: {manifest_path}")

            integrator = InitiativeIntegrator(
                manifest_path=manifest_path,
                repo_root=repo_root,
                target_branch=target_branch,
                repo=getattr(args, "boss_repo", None) or "synaptent/aragora",
            )
            if subaction == "run":
                payload = asyncio.run(integrator.run())
            elif subaction == "status":
                payload = integrator.status()
            else:
                payload = integrator.promote(
                    project_id=project_id,
                    dry_run=bool(getattr(args, "dry_run", False)),
                )

            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                if subaction in {"run", "status"}:
                    _render_initiative_status(payload)
                else:
                    print(json.dumps(payload, indent=2))
            return

        if subaction == "list":
            items = store.list()
            payload = {
                "mode": "initiative-list",
                "action": subaction,
                "count": len(items),
                "items": [item.to_dict() for item in items],
                "state_dir": str(store.state_dir),
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(f"initiatives={len(items)} state_dir={store.state_dir}")
                _print_table(
                    [
                        ("initiative_id", "Initiative"),
                        ("status", "Status"),
                        ("feature_flag", "Feature Flag"),
                        ("slices", "Slices"),
                        ("title", "Title"),
                    ],
                    _initiative_rows(items),
                )
            return

        initiative_id = _optional_text(getattr(args, "swarm_campaign_target", None))
        if subaction == "show":
            if not initiative_id:
                raise ValueError("initiative show requires an initiative id as the third argument")
            show_record = store.get(initiative_id)
            if show_record is None:
                raise FileNotFoundError(f"initiative not found: {initiative_id}")
            payload = {
                "mode": "initiative-show",
                "action": subaction,
                "initiative": show_record.to_dict(),
                "state_dir": str(store.state_dir),
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                _render_initiative(show_record)
            return

        goal_text = initiative_id
        if not goal_text:
            raise ValueError("initiative plan requires a goal as the third argument")
        rationale = ""
        source_file = _optional_text(getattr(args, "source_file", None))
        if source_file:
            rationale = Path(source_file).expanduser().resolve().read_text().strip()
        planner = InitiativePlanner(repo_root=repo_root)
        initiative = planner.plan(
            goal=goal_text,
            rationale=rationale,
            dependencies=[
                str(item).strip()
                for item in (getattr(args, "dependency", None) or [])
                if str(item).strip()
            ],
            validations=[
                str(item).strip()
                for item in (getattr(args, "validation", None) or [])
                if str(item).strip()
            ],
            feature_flag_name=_optional_text(getattr(args, "feature_flag", None)),
            milestone_titles=[
                str(item).strip()
                for item in (getattr(args, "milestone", None) or [])
                if str(item).strip()
            ],
            checkpoint_titles=[
                str(item).strip()
                for item in (getattr(args, "checkpoint", None) or [])
                if str(item).strip()
            ],
            planner_strategy=str(getattr(args, "planner_strategy", "heuristic") or "heuristic"),
            planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
        )
        if source_file:
            initiative.metadata["source_file"] = str(Path(source_file).expanduser().resolve())
        saved_path = store.save(initiative)
        manifest_path = sync_campaign_manifest_for_initiative(
            store,
            initiative,
            planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
            planner_strategy=str(getattr(args, "planner_strategy", "heuristic") or "heuristic"),
            worker_model=str(getattr(args, "worker_model", "claude") or "claude"),
            review_model=str(getattr(args, "review_model", "codex") or "codex"),
        )
        payload = {
            "mode": "initiative-plan",
            "action": subaction,
            "initiative": initiative.to_dict(),
            "path": str(saved_path),
            "manifest_path": str(manifest_path),
            "state_dir": str(store.state_dir),
        }
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"initiative_id={initiative.initiative_id}")
            print(f"path={saved_path}")
            print(f"manifest={manifest_path}")
            print(f"slices={len(initiative.slices)}")
        return

    if action == "runner":
        from aragora.swarm.reporter import render_runner_registration_text
        from aragora.swarm.runner_registry import (
            LocalRunnerRegistry,
            authorization_context_with_defaults,
            discover_runner_inspections,
            prioritized_probe_candidates,
            probe_runner_execution,
            refresh_discovered_runners,
        )

        subaction = str(goal or "inspect").strip().lower()
        if subaction not in {"inspect", "register", "heartbeat", "report", "probe", "maintain"}:
            print(
                "Error: swarm runner action must be 'inspect', 'register', 'heartbeat', "
                "'report', 'probe', or 'maintain'"
            )
            return

        runner_type = (
            str(
                getattr(args, "runner_type", None) or os.environ.get("ARAGORA_RUNNER_TYPE", "codex")
            ).strip()
            or "codex"
        )
        inspections: list[Any] = []
        probe_limit = _probe_limit_arg(args, default=1 if subaction == "maintain" else 2)
        if subaction == "register":
            inspections = discover_runner_inspections(
                runner_type,
                env=dict(os.environ),
                repo_root=Path.cwd(),
                profiles=allowed_runner_profiles or None,
            )
            owner_context = authorization_context_with_defaults(repo_root=Path.cwd())
            payloads = [
                LocalRunnerRegistry()
                .register(
                    inspection,
                    owner_context=owner_context,
                )
                .to_dict()
                for inspection in inspections
            ]
            payload = (
                payloads[0]
                if len(payloads) == 1
                else _build_multi_runner_payload(subaction=subaction, runners=payloads)
            )
        elif subaction == "heartbeat":
            inspections = discover_runner_inspections(
                runner_type,
                env=dict(os.environ),
                repo_root=Path.cwd(),
                profiles=allowed_runner_profiles or None,
            )
            owner_context = authorization_context_with_defaults(repo_root=Path.cwd())
            payloads = [
                LocalRunnerRegistry()
                .heartbeat(
                    inspection,
                    owner_context=owner_context,
                )
                .to_dict()
                for inspection in inspections
            ]
            payload = (
                payloads[0]
                if len(payloads) == 1
                else _build_multi_runner_payload(subaction=subaction, runners=payloads)
            )
        elif subaction == "report":
            owner_context = authorization_context_with_defaults(repo_root=Path.cwd())
            registry = LocalRunnerRegistry()
            inspections = (
                refresh_discovered_runners(
                    runner_type,
                    registry=registry,
                    owner_context=owner_context,
                    env=dict(os.environ),
                    repo_root=Path.cwd(),
                    profiles=allowed_runner_profiles or None,
                )
                if owner_context is not None
                else discover_runner_inspections(
                    runner_type,
                    env=dict(os.environ),
                    repo_root=Path.cwd(),
                    profiles=allowed_runner_profiles or None,
                )
            )
            payload = _build_runner_report_payload(
                registrations=registry.list_registrations(),
                routing=registry.resolve_boss_routing(
                    owner_context=owner_context,
                    requested_runner_type=runner_type,
                    allowed_profiles=allowed_runner_profiles,
                    rotation_interval_seconds=runner_rotation_interval,
                ).to_dict(),
                discovered=[item.to_dict() for item in inspections],
            )
        elif subaction == "probe":
            owner_context = authorization_context_with_defaults(repo_root=Path.cwd())
            registry = LocalRunnerRegistry()
            inspections = discover_runner_inspections(
                runner_type,
                env=dict(os.environ),
                repo_root=Path.cwd(),
                profiles=allowed_runner_profiles or None,
            )
            routing_before = (
                registry.resolve_boss_routing(
                    owner_context=owner_context,
                    requested_runner_type=runner_type,
                    allowed_profiles=allowed_runner_profiles,
                    rotation_interval_seconds=runner_rotation_interval,
                ).to_dict()
                if owner_context is not None
                else None
            )
            probe_payloads: list[dict[str, object]] = []
            for inspection in inspections[:probe_limit]:
                probe = probe_runner_execution(
                    inspection,
                    repo_root=Path.cwd(),
                )
                probe_payloads.append(
                    registry.record_probe(
                        inspection,
                        probe,
                        owner_context=owner_context,
                    )
                )
            routing_after = (
                registry.resolve_boss_routing(
                    owner_context=owner_context,
                    requested_runner_type=runner_type,
                    allowed_profiles=allowed_runner_profiles,
                    rotation_interval_seconds=runner_rotation_interval,
                ).to_dict()
                if owner_context is not None
                else None
            )
            payload = _build_runner_probe_payload(
                subaction=subaction,
                runners=probe_payloads,
                discovered=[item.to_dict() for item in inspections],
                routing_before=routing_before,
                routing_after=routing_after,
            )
        elif subaction == "maintain":
            owner_context = authorization_context_with_defaults(repo_root=Path.cwd())
            registry = LocalRunnerRegistry()
            inspections = (
                refresh_discovered_runners(
                    runner_type,
                    registry=registry,
                    owner_context=owner_context,
                    env=dict(os.environ),
                    repo_root=Path.cwd(),
                    profiles=allowed_runner_profiles or None,
                )
                if owner_context is not None
                else discover_runner_inspections(
                    runner_type,
                    env=dict(os.environ),
                    repo_root=Path.cwd(),
                    profiles=allowed_runner_profiles or None,
                )
            )
            routing_before = (
                registry.resolve_boss_routing(
                    owner_context=owner_context,
                    requested_runner_type=runner_type,
                    allowed_profiles=allowed_runner_profiles,
                    rotation_interval_seconds=runner_rotation_interval,
                ).to_dict()
                if owner_context is not None
                else None
            )
            candidates = (
                prioritized_probe_candidates(
                    registry=registry,
                    runner_type=runner_type,
                    discovered_inspections=inspections,
                    owner_context=owner_context,
                    selected_runners=(
                        list(routing_before.get("selected_runners", []))
                        if isinstance(routing_before, dict)
                        else None
                    ),
                )
                if owner_context is not None
                else list(inspections)
            )
            if not candidates:
                candidates = list(inspections)
            probe_payloads = []
            for inspection in candidates[:probe_limit]:
                probe = probe_runner_execution(
                    inspection,
                    repo_root=Path.cwd(),
                )
                probe_payloads.append(
                    registry.record_probe(
                        inspection,
                        probe,
                        owner_context=owner_context,
                    )
                )
            routing_after = (
                registry.resolve_boss_routing(
                    owner_context=owner_context,
                    requested_runner_type=runner_type,
                    allowed_profiles=allowed_runner_profiles,
                    rotation_interval_seconds=runner_rotation_interval,
                ).to_dict()
                if owner_context is not None
                else None
            )
            payload = _build_runner_probe_payload(
                subaction=subaction,
                runners=probe_payloads,
                discovered=[item.to_dict() for item in inspections],
                routing_before=routing_before,
                routing_after=routing_after,
            )
        else:
            inspections = discover_runner_inspections(
                runner_type,
                env=dict(os.environ),
                repo_root=Path.cwd(),
                profiles=allowed_runner_profiles or None,
            )
            inspection_payloads = [item.to_dict() for item in inspections]
            payload = (
                inspection_payloads[0]
                if len(inspection_payloads) == 1
                else _build_multi_runner_payload(subaction=subaction, runners=inspection_payloads)
            )

        payload["mode"] = "runner"
        payload["action"] = subaction
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            if subaction == "report":
                _render_runner_report(payload)
            elif subaction in {"probe", "maintain"}:
                probe_summary = (
                    payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
                )
                print(
                    "Runner {action} discovered={discovered} attempted={attempted} "
                    "passed={passed} failed={failed}".format(
                        action=subaction,
                        discovered=probe_summary.get("discovered", 0),
                        attempted=probe_summary.get("attempted", 0),
                        passed=probe_summary.get("passed", 0),
                        failed=probe_summary.get("failed", 0),
                    )
                )
                print()
                for item in [
                    entry for entry in payload.get("runners", []) if isinstance(entry, dict)
                ]:
                    print(render_runner_registration_text(item))
                    print()
            elif "runners" in payload:
                runner_summary = (
                    payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
                )
                print(
                    "Runner {action} count={count} available={available} registered={registered}".format(
                        action=subaction,
                        count=runner_summary.get("count", 0),
                        available=runner_summary.get("available", 0),
                        registered=runner_summary.get("registered", 0),
                    )
                )
                print()
                for item in [
                    entry for entry in payload.get("runners", []) if isinstance(entry, dict)
                ]:
                    print(render_runner_registration_text(item))
                    print()
            else:
                print(render_runner_registration_text(payload))
        return

    if action == "audit-issues":
        from aragora.swarm.boss_loop import GitHubIssueFeed

        audit_labels: list[str] = list(getattr(args, "labels", None) or [])
        audit_ref = _optional_text(getattr(args, "audit_ref", None))
        legacy_label = getattr(args, "boss_label_filter", None)
        if legacy_label and legacy_label not in audit_labels:
            audit_labels.insert(0, legacy_label)
        label_filter = audit_labels[0] if audit_labels else None
        required_labels = set(audit_labels)
        issue_list = [
            int(item.strip())
            for item in str(getattr(args, "boss_issue_list", "") or "").split(",")
            if item.strip()
        ]
        if getattr(args, "boss_issue_number", None):
            issue_list.append(int(getattr(args, "boss_issue_number")))

        feed = GitHubIssueFeed(
            repo=getattr(args, "boss_repo", None),
            label_filter=label_filter,
            issue_numbers=issue_list or None,
            limit=25,
        )
        issues = feed.fetch()
        if required_labels:
            issues = [
                issue
                for issue in issues
                if required_labels.issubset(
                    {str(label).strip() for label in getattr(issue, "labels", [])}
                )
            ]

        with _open_audit_checkout(Path.cwd(), git_ref=audit_ref) as audit_root:
            audits = [
                _audit_issue_validation_contract(issue, repo_root=audit_root) for issue in issues
            ]
        audit_summary: dict[str, int] = {}
        for item in audits:
            status = str(item.get("status", "unknown") or "unknown")
            audit_summary[status] = audit_summary.get(status, 0) + 1
        payload = {
            "mode": "swarm-issue-audit",
            "action": "audit-issues",
            "repo": getattr(args, "boss_repo", None),
            "audit_ref": audit_ref,
            "labels": audit_labels,
            "issue_count": len(audits),
            "summary": audit_summary,
            "issues": audits,
        }
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"audited={len(audits)} "
                + (f"ref={audit_ref} " if audit_ref else "")
                + " ".join(f"{key}={value}" for key, value in sorted(audit_summary.items()))
            )
            rows = [
                {
                    "number": item["number"],
                    "status": item["status"],
                    "title": str(item.get("title", ""))[:64],
                    "next_action": str(item["next_action"])[:80],
                }
                for item in audits
            ]
            _print_table(
                [
                    ("number", "Issue"),
                    ("status", "Status"),
                    ("title", "Title"),
                    ("next_action", "Next Action"),
                ],
                rows,
            )
        return

    if action == "integrator":
        subaction = str(goal or "view").strip().lower() or "view"
        repo_root = resolve_repo_root(Path.cwd())
        base_branch = str(getattr(args, "target_branch", "main") or "main")
        view = _load_integrator_view(repo_root, base_branch=base_branch)
        readiness_filter = str(getattr(args, "readiness", None) or "").strip()
        if readiness_filter:
            filtered_view = dict(view)
            lanes_value = view.get("lanes", [])
            lanes = lanes_value if isinstance(lanes_value, list) else []
            filtered_view["lanes"] = [
                item
                for item in lanes
                if isinstance(item, dict)
                and str(item.get("merge_readiness", "")).strip() == readiness_filter
            ]
            view = filtered_view

        if subaction in {"view", "status"}:
            if as_json:
                print(json.dumps(view, indent=2))
            else:
                _render_integrator_table(view)
            return

        lane = _find_integrator_lane(
            view,
            lane_id=str(getattr(args, "lane_id", None) or ""),
            receipt_id=str(getattr(args, "receipt_id", None) or ""),
            lease_id=str(getattr(args, "lease_id", None) or ""),
            branch=str(getattr(args, "lane_branch", None) or ""),
        )
        if lane is None:
            print(
                "Error: integrator action requires a resolvable lane via "
                "--lane-id, --receipt-id, --lease-id, or --lane-branch",
                file=sys.stderr,
            )
            sys.exit(1)

        rationale = str(getattr(args, "rationale", "") or "").strip()
        decided_by = str(getattr(args, "decided_by", "cli-integrator") or "cli-integrator").strip()

        if subaction in {"merge", "archive"}:
            from aragora.nomic.dev_coordination import IntegrationDecisionType

            if DevCoordinationStore is None:
                print(
                    "Error: DevCoordinationStore is unavailable in this environment",
                    file=sys.stderr,
                )
                sys.exit(1)

            resolved_receipt_id = str(
                getattr(args, "receipt_id", None) or lane.get("receipt_id") or ""
            ).strip()
            resolved_lease_id = str(
                getattr(args, "lease_id", None) or lane.get("lease_id") or ""
            ).strip()
            if not resolved_receipt_id:
                print(
                    "Error: selected lane has no receipt_id; cannot record an integration decision",
                    file=sys.stderr,
                )
                sys.exit(1)

            decision_type = (
                IntegrationDecisionType.MERGE
                if subaction == "merge"
                else IntegrationDecisionType.DISCARD
            )
            decision = DevCoordinationStore(repo_root=repo_root).record_integration_decision(
                receipt_id=resolved_receipt_id,
                lease_id=resolved_lease_id or None,
                decided_by=decided_by,
                decision=decision_type,
                rationale=rationale
                or (
                    "Integrator approved lane for merge"
                    if subaction == "merge"
                    else "Integrator archived lane"
                ),
                target_branch=base_branch,
            )
            branch = str(lane.get("branch", "") or "").strip()
            if subaction == "archive" and branch:
                try:
                    from aragora.swarm.pr_registry import PullRequestRegistry

                    PullRequestRegistry().close(branch, outcome="archived")
                except ImportError:
                    pass
                except (RuntimeError, OSError, ValueError) as exc:
                    logger.debug("pr_registry_close_failed branch=%s: %s", branch, exc)
            payload = {
                "lane_id": lane.get("lane_id"),
                "receipt_id": resolved_receipt_id,
                "lease_id": resolved_lease_id or None,
                "branch": branch or None,
                "decision": decision.decision,
                "decision_id": decision.decision_id,
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(
                    "decision_id={decision_id} decision={decision} lane_id={lane_id} receipt_id={receipt_id}".format(
                        decision_id=payload["decision_id"],
                        decision=payload["decision"],
                        lane_id=payload["lane_id"],
                        receipt_id=payload["receipt_id"],
                    )
                )
            return

        if subaction == "supersede":
            from aragora.swarm.pr_registry import PullRequestRegistry

            branch = str(getattr(args, "lane_branch", None) or lane.get("branch") or "").strip()
            new_pr_url = str(getattr(args, "new_pr_url", None) or "").strip()
            if not branch or not new_pr_url:
                print(
                    "Error: integrator supersede requires a lane branch and --new-pr-url",
                    file=sys.stderr,
                )
                sys.exit(1)
            entry = PullRequestRegistry().supersede(
                branch,
                new_pr_url,
                reason=rationale or "Integrator superseded the canonical PR",
            )
            if entry is None:
                print(f"Error: branch not found in PR registry: {branch}", file=sys.stderr)
                sys.exit(1)
            payload = {
                "branch": branch,
                "new_pr_url": new_pr_url,
                "status": entry.status,
                "superseded_count": len(entry.superseded),
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(
                    "branch={branch} superseded_count={count} new_pr={url}".format(
                        branch=branch,
                        count=payload["superseded_count"],
                        url=new_pr_url,
                    )
                )
            return

        print(
            "Error: swarm integrator action must be one of view, status, merge, archive, or supersede",
            file=sys.stderr,
        )
        sys.exit(1)

    if action == "merge-arbiter":
        from aragora.swarm.merge_arbiter import MergeArbiter, MergeArbiterConfig

        prefixes_raw = str(getattr(args, "boss_branch_prefix", "") or "boss-harvest")
        prefixes = [p.strip() for p in prefixes_raw.split(",") if p.strip()]
        arbiter_config = MergeArbiterConfig(
            repo=getattr(args, "boss_repo", None) or "synaptent/aragora",
            branch_prefixes=prefixes,
            poll_interval_seconds=float(getattr(args, "interval_seconds", 120.0) or 120.0),
            max_runtime_hours=float(getattr(args, "max_hours", 12.0) or 12.0),
            max_consecutive_failures=int(getattr(args, "max_consecutive_failures", 3) or 3),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
        arbiter = MergeArbiter(config=arbiter_config)
        summary = asyncio.run(arbiter.run())
        if as_json:
            print(json.dumps(summary.to_dict(), indent=2))
        else:
            print(f"\nMerge arbiter finished: {summary.stop_reason}")
            print(
                f"polls={summary.polls} merged={len(summary.merged)} "
                f"skipped={len(summary.skipped)} failed={len(summary.failed)} "
                f"elapsed={summary.elapsed_seconds:.1f}s"
            )
            if summary.merged:
                print(f"  merged PRs: {summary.merged}")
        return

    if action == "boss-loop":
        from aragora.swarm.boss_loop import BossLoop, BossLoopConfig

        # Merge --label (repeatable) with legacy --boss-label-filter (single string).
        cli_labels: list[str] = list(getattr(args, "labels", None) or [])
        legacy_label = getattr(args, "boss_label_filter", None)
        if legacy_label and legacy_label not in cli_labels:
            cli_labels.insert(0, legacy_label)

        # Use the first label for gh CLI pre-filtering (server-side), and the
        # full set as require_labels for Python-side ALL-match filtering.
        label_filter = cli_labels[0] if cli_labels else None
        require_labels = set(cli_labels) if cli_labels else None

        # When --autonomy full-auto, continue past needs_human states
        auto_continue = autonomy_str in {"full-auto", "fire_and_forget"}
        issue_list = [
            int(item.strip())
            for item in str(getattr(args, "boss_issue_list", "") or "").split(",")
            if item.strip()
        ]
        default_target_agent = str(getattr(args, "worker_model", "") or "").strip() or None
        default_reviewer_agent = str(getattr(args, "review_model", "") or "").strip() or None

        boss_loop_config = BossLoopConfig(
            max_iterations=int(getattr(args, "max_ticks", None) or 50),
            iteration_interval_seconds=float(getattr(args, "interval_seconds", 30.0) or 30.0),
            freshness_ttl_seconds=float(getattr(args, "freshness_ttl", 3600.0) or 3600.0),
            repo=getattr(args, "boss_repo", None),
            label_filter=label_filter,
            require_labels=require_labels,
            issue_number=getattr(args, "boss_issue_number", None),
            issue_numbers=issue_list or None,
            target_branch=target_branch,
            budget_limit_usd=budget_limit,
            max_consecutive_failures=int(getattr(args, "max_consecutive_failures", 3) or 3),
            require_validation_contract=not bool(
                getattr(args, "allow_missing_validation_contract", False)
            ),
            dispatch_enabled=not no_dispatch,
            default_target_agent=default_target_agent,
            default_reviewer_agent=default_reviewer_agent,
            allowed_runner_profiles=allowed_runner_profiles,
            runner_rotation_interval_seconds=runner_rotation_interval,
            max_parallel_dispatches=int(getattr(args, "boss_max_parallel_dispatches", 1) or 1),
            auto_continue_on_needs_human=auto_continue,
            enable_ping_pong_retry=bool(getattr(args, "ping_pong", False)),
            allow_claude_dangerously_skip_permissions=auto_continue,
            allow_codex_full_auto=auto_continue,
            auto_publish_deliverables=auto_continue,
            auto_close_already_done_issues=auto_continue,
            auto_update_enabled=bool(getattr(args, "boss_auto_update", False)),
            auto_update_interval_iterations=int(
                getattr(args, "boss_auto_update_interval", 10) or 10
            ),
            use_llm_pre_dispatch_gate=bool(getattr(args, "boss_llm_pre_dispatch_gate", False)),
            no_suitable_issue_keepalive=bool(getattr(args, "no_suitable_issue_keepalive", False)),
        )
        exec_argv = ["-m", "aragora.cli.main", *sys.argv[1:]]
        loop = BossLoop(config=boss_loop_config, exec_argv=exec_argv)

        def _on_status(status: object) -> None:
            if as_json:
                return  # JSON output is emitted at the end
            status_dict = status.to_dict() if hasattr(status, "to_dict") else {}
            iteration = status_dict.get("iteration", "?")
            worker = status_dict.get("worker_status", "?")
            issue = status_dict.get("selected_issue")
            lane = None
            if isinstance(issue, dict):
                lane = issue.get("lane_id")
                if lane is None:
                    lane_hints = issue.get("lane_hints")
                    if isinstance(lane_hints, list) and lane_hints:
                        lane = ",".join(
                            str(item).strip()
                            for item in lane_hints[:MAX_DISPLAYED_LANE_HINTS]
                            if str(item).strip()
                        )
            issue_text = (
                f"#{issue.get('number', '?')} {issue.get('title', '')[:60]}"
                if isinstance(issue, dict)
                else "none"
            )
            if lane:
                issue_text = f"{issue_text} lane={lane}"
            stop = status_dict.get("stop_reason")
            configured_parallel = status_dict.get("configured_max_parallel_dispatches")
            effective_parallel = status_dict.get("effective_parallel_dispatches")
            parallel_text = ""
            if configured_parallel is not None:
                effective_text = str(effective_parallel) if effective_parallel is not None else "?"
                parallel_text = f" parallel={configured_parallel}/{effective_text}"
            print(
                f"[iter {iteration}] worker={worker} issue={issue_text}{parallel_text}"
                + (f" stop={stop}" if stop else "")
            )
            for action_text in status_dict.get("next_actions", [])[:2]:
                print(f"  next: {action_text}")

        loop_result = asyncio.run(loop.run(on_status=_on_status))
        if as_json:
            to_bounded_dict = getattr(loop_result, "to_bounded_dict", None)
            payload = to_bounded_dict() if callable(to_bounded_dict) else loop_result.to_dict()
            print(json.dumps(payload, indent=2))
        else:
            print(f"\nBoss loop finished: {loop_result.stop_reason}")
            print(
                f"iterations={loop_result.iterations_completed} "
                f"attempted={len(loop_result.issues_attempted)} "
                f"completed={len(loop_result.issues_completed)} "
                f"failed={len(loop_result.issues_failed)} "
                f"elapsed={loop_result.total_elapsed_seconds:.1f}s "
                f"parallel={loop_result.configured_max_parallel_dispatches}/"
                f"{loop_result.effective_parallel_dispatches_observed if loop_result.effective_parallel_dispatches_observed is not None else '?'}"
            )
            for reason in loop_result.needs_human_reasons[:3]:
                print(f"  needs_human: {reason}")
            for action_text in loop_result.next_actions[:3]:
                print(f"  next: {action_text}")
        return

    if action == "campaign":
        from aragora.swarm.campaign import (
            CampaignExecutor,
            CampaignPlanner,
            DEFAULT_CAMPAIGN_MANIFEST,
            load_campaign_manifest,
            locked_manifest_path,
            save_campaign_manifest,
        )

        subaction = str(goal or "status").strip().lower()
        manifest_path = Path(getattr(args, "manifest", None) or DEFAULT_CAMPAIGN_MANIFEST).resolve()
        output_path = Path(getattr(args, "output", None) or manifest_path).resolve()

        def _campaign_input_count() -> int:
            return sum(
                1
                for value in (
                    getattr(args, "source_file", None),
                    getattr(args, "issue_list", None),
                    getattr(args, "github_query", None),
                )
                if value
            )

        def _campaign_planner(parallel_default: int = 1):
            return CampaignPlanner(
                repo_root=Path.cwd(),
                planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
                planner_strategy=str(getattr(args, "planner_strategy", "heuristic") or "heuristic"),
                worker_model=str(getattr(args, "worker_model", "codex") or "codex"),
                review_model=str(getattr(args, "review_model", "claude") or "claude"),
                enforce_cross_model_review=not bool(
                    getattr(args, "allow_same_model_review", False)
                ),
                budget_limit_usd=float(getattr(args, "budget_limit", 50.0) or 50.0),
                max_parallel_ready_projects=int(
                    getattr(args, "max_parallel_ready_projects", parallel_default)
                    or parallel_default
                ),
                experiment_id=str(getattr(args, "experiment_id", "")).strip() or None,
                experiment_label=str(getattr(args, "experiment_label", "")).strip() or None,
            )

        def _plan_campaign(planner):
            source_file = getattr(args, "source_file", None)
            issue_list = getattr(args, "issue_list", None)
            github_query = getattr(args, "github_query", None)
            if source_file:
                return planner.plan_from_source_file(Path(source_file).resolve())
            if issue_list:
                issue_numbers = [
                    int(item.strip()) for item in str(issue_list).split(",") if item.strip()
                ]
                return planner.plan_from_issue_list(
                    issue_numbers,
                    repo=getattr(args, "boss_repo", None),
                )
            if github_query:
                return planner.plan_from_github_query(
                    str(github_query),
                    repo=getattr(args, "boss_repo", None),
                )
            raise ValueError(
                "campaign plan requires exactly one of --source-file, --issue-list, or --github-query"
            )

        if subaction == "plan":
            if _campaign_input_count() != 1:
                raise ValueError(
                    "campaign plan requires exactly one of --source-file, --issue-list, or --github-query"
                )
            planner = _campaign_planner(parallel_default=1)
            manifest = _plan_campaign(planner)
            with locked_manifest_path(output_path):
                save_campaign_manifest(output_path, manifest)
            payload = {
                "mode": "campaign-plan",
                "manifest_path": str(output_path),
                **manifest.to_dict(),
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(f"campaign_id={manifest.campaign_id}")
                print(f"manifest={output_path}")
                print(
                    f"projects={len(manifest.projects)} budget=${manifest.budget_limit_usd:.2f} "
                    f"worker={manifest.worker_model} review={manifest.review_model}"
                )
                for finding in manifest.planning_findings[:5]:
                    print(f"  finding: {finding}")
            return

        if subaction == "run":
            # Unified pipeline: plan once into a canonical manifest, then execute exactly one iteration.
            source_count = _campaign_input_count()
            run_manifest_path = manifest_path
            invocation_mode = "resumed"
            if manifest_path.exists():
                if source_count > 0:
                    raise ValueError(
                        "campaign run: cannot supply --source-file, --issue-list, or "
                        "--github-query when resuming from an existing manifest"
                    )
                if not as_json:
                    print(f"Resuming from existing manifest: {manifest_path}")
            else:
                if source_count == 0:
                    raise ValueError(
                        "campaign run requires an existing manifest or one of "
                        "--source-file, --issue-list, --github-query"
                    )
                if source_count != 1:
                    raise ValueError(
                        "campaign run requires exactly one of --source-file, --issue-list, or "
                        "--github-query when the manifest does not exist"
                    )
                planner = _campaign_planner(parallel_default=1)
                manifest = _plan_campaign(planner)
                run_manifest_path = output_path
                with locked_manifest_path(run_manifest_path):
                    save_campaign_manifest(output_path, manifest)
                invocation_mode = "planned_then_executed"
                if not as_json:
                    print(f"Planned {len(manifest.projects)} projects → {run_manifest_path}")
            executor = CampaignExecutor(
                manifest_path=run_manifest_path,
                repo_root=Path.cwd(),
                target_branch=target_branch,
            )
            payload = {
                "mode": "campaign-run",
                "invocation_mode": invocation_mode,
                "manifest_path": str(run_manifest_path),
                **asyncio.run(executor.execute_once()),
            }
            with locked_manifest_path(run_manifest_path):
                manifest = load_campaign_manifest(run_manifest_path)
                payload["campaign_id"] = manifest.campaign_id
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                stop = payload.get("stop_reason", "")
                dispatched = payload.get("dispatched_projects", [])
                print(
                    f"campaign_id={payload.get('campaign_id', '')} "
                    f"manifest={run_manifest_path} "
                    f"invocation_mode={invocation_mode} "
                    f"stop_reason={stop} dispatched={len(dispatched)}"
                )
                for item in dispatched:
                    if isinstance(item, dict):
                        print(
                            f"  {item.get('project_id')} status={item.get('status')} "
                            f"outcome={item.get('outcome')}"
                        )
                    elif isinstance(item, str):
                        print(f"  {item}")
            return

        executor = CampaignExecutor(
            manifest_path=manifest_path,
            repo_root=Path.cwd(),
            target_branch=target_branch,
        )
        if subaction == "execute":
            payload = asyncio.run(executor.execute_once())
        elif subaction == "status":
            payload = executor.status()
        elif subaction == "review":
            target = str(getattr(args, "swarm_campaign_target", None) or "").strip()
            if not target:
                raise ValueError("campaign review requires a project id as the third argument")
            payload = asyncio.run(executor.review_project(target))
        elif subaction == "sync-issues":
            payload = executor.sync_issue_plan()
        else:
            raise ValueError(
                "campaign action must be one of: plan, run, execute, status, review, sync-issues"
            )

        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            if subaction == "status":
                print(
                    f"campaign_id={payload.get('campaign_id', '')} "
                    f"stop_reason={payload.get('stop_reason', '')}"
                )
                counts = payload.get("counts", {})
                if isinstance(counts, dict):
                    counts_text = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                    print(f"counts={counts_text}")
                for project in payload.get("projects", [])[:10]:
                    if not isinstance(project, dict):
                        continue
                    print(
                        f"{project.get('project_id')} status={project.get('status')} "
                        f"review={project.get('review_status')} title={project.get('title', '')}"
                    )
            else:
                print(json.dumps(payload, indent=2))
        return

    if action == "tranche":
        from aragora.ralph.github_control import GitHubControl
        from aragora.swarm.pr_registry import PullRequestRegistry
        from aragora.swarm.tranche import (
            TrancheArtifactStore,
            TrancheExecutor,
            TrancheInspector,
            TranchePlanner,
            load_tranche_manifest,
            render_tranche_inspection_text,
        )
        from aragora.swarm.tranche_integrate import (
            integrate_lane,
        )
        from aragora.swarm.tranche_queue import (
            compile_tranche_queue,
            explore_tranche_queue,
            harvest_tranche_queue,
            plan_tranche_queue,
            reconcile_tranche_queue,
            run_tranche_queue,
            tranche_queue_status,
        )
        from aragora.swarm.tranche_review import review_lane, select_review_tier
        from aragora.swarm.tranche_submit import submit_intake_bundle
        from aragora.swarm.tranche_watch import (
            claim_driver,
            list_tranche_states,
            load_tranche_run_state,
            refresh_supervisor_run_dict,
            release_driver,
            run_state_path_for_manifest,
            watch_loop,
        )

        subaction = str(goal or "inspect").strip().lower() or "inspect"
        repo_root = resolve_repo_root(Path.cwd())
        if subaction == "submit":
            intake_arg = str(getattr(args, "intake", "") or "").strip()
            if not intake_arg:
                raise ValueError("tranche submit requires --intake <path|->")
            intake_path: Path | None = None
            if intake_arg != "-":
                intake_path = Path(intake_arg).resolve()
                if not intake_path.exists():
                    raise ValueError(f"intake bundle not found: {intake_path}")
            bundle = _load_structured_object(intake_arg)
            payload = submit_intake_bundle(
                bundle,
                repo_root=repo_root,
                autonomy_mode=_optional_text(getattr(args, "autonomy", None)),
            )
            payload["mode"] = "tranche-submit"
            payload["action"] = subaction
            if intake_path is not None:
                payload["intake_path"] = str(intake_path)
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(json.dumps(payload, indent=2))
            return
        if subaction == "list":
            tranche_items = list_tranche_states(repo_root)
            payload = {
                "mode": "tranche-list",
                "action": subaction,
                "count": len(tranche_items),
                "items": tranche_items,
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(json.dumps(payload, indent=2))
            return
        if subaction == "compile-queue":
            sources_arg = str(getattr(args, "sources", "") or "").strip()
            if not sources_arg:
                raise ValueError("tranche compile-queue requires --sources <path>")
            output_arg = str(getattr(args, "output", "") or "").strip()
            if not output_arg:
                raise ValueError("tranche compile-queue requires --output <path>")
            sources_path = Path(sources_arg).resolve()
            if not sources_path.exists():
                raise ValueError(f"tranche queue source manifest not found: {sources_path}")
            output_path = Path(output_arg).resolve()
            payload = compile_tranche_queue(
                sources_path=sources_path,
                output_path=output_path,
                repo_root=repo_root,
            )
            payload["action"] = subaction
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(json.dumps(payload, indent=2))
            return
        if subaction == "status":
            queue_arg = str(getattr(args, "queue", "") or "").strip()
            if not queue_arg:
                raise ValueError("tranche status requires --queue <path>")
            queue_path = Path(queue_arg).resolve()
            if not queue_path.exists():
                raise ValueError(f"tranche queue manifest not found: {queue_path}")
            payload = tranche_queue_status(
                queue_path=queue_path,
                repo_root=repo_root,
            )
            payload["action"] = subaction
            payload["queue_path"] = str(queue_path)
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                _render_tranche_queue_status(payload)
            return
        if subaction in {
            "explore-queue",
            "plan-queue",
            "run-queue",
            "reconcile-queue",
            "harvest-queue",
        }:
            queue_arg = str(getattr(args, "queue", "") or "").strip()
            if not queue_arg:
                raise ValueError(f"tranche {subaction} requires --queue <path>")
            queue_path = Path(queue_arg).resolve()
            if not queue_path.exists():
                raise ValueError(f"tranche queue manifest not found: {queue_path}")
            if subaction == "explore-queue":
                payload = asyncio.run(
                    explore_tranche_queue(
                        queue_path=queue_path,
                        repo_root=repo_root,
                        planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
                        planner_strategy=str(
                            getattr(args, "planner_strategy", "heuristic") or "heuristic"
                        ),
                        worker_model=str(getattr(args, "worker_model", "codex") or "codex"),
                        review_model=str(getattr(args, "review_model", "claude") or "claude"),
                        max_parallel_lanes=int(getattr(args, "max_parallel_lanes", 1) or 1),
                        enforce_cross_model_review=not bool(
                            getattr(args, "allow_same_model_review", False)
                        ),
                    )
                )
            elif subaction == "plan-queue":
                payload = asyncio.run(
                    plan_tranche_queue(
                        queue_path=queue_path,
                        repo_root=repo_root,
                        planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
                        planner_strategy=str(
                            getattr(args, "planner_strategy", "heuristic") or "heuristic"
                        ),
                        worker_model=str(getattr(args, "worker_model", "codex") or "codex"),
                        review_model=str(getattr(args, "review_model", "claude") or "claude"),
                        max_parallel_lanes=int(getattr(args, "max_parallel_lanes", 1) or 1),
                        enforce_cross_model_review=not bool(
                            getattr(args, "allow_same_model_review", False)
                        ),
                    )
                )
            elif subaction == "run-queue":
                payload = asyncio.run(
                    run_tranche_queue(
                        queue_path=queue_path,
                        repo_root=repo_root,
                        target_branch=str(getattr(args, "target_branch", "main") or "main"),
                        interval_seconds=interval_seconds,
                        max_hours=float(getattr(args, "max_hours", 12.0) or 12.0),
                        max_consecutive_failures=int(
                            getattr(args, "max_consecutive_failures", 3) or 3
                        ),
                        planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
                        planner_strategy=str(
                            getattr(args, "planner_strategy", "heuristic") or "heuristic"
                        ),
                        worker_model=str(getattr(args, "worker_model", "codex") or "codex"),
                        review_model=str(getattr(args, "review_model", "claude") or "claude"),
                        max_parallel_lanes=int(getattr(args, "max_parallel_lanes", 1) or 1),
                        enforce_cross_model_review=not bool(
                            getattr(args, "allow_same_model_review", False)
                        ),
                        allow_claude_dangerously_skip_permissions=allow_claude_write,
                    )
                )
            elif subaction == "harvest-queue":
                requested_execute_merge = bool(getattr(args, "execute_merge", False))
                dry_run = bool(getattr(args, "dry_run", False))
                payload = harvest_tranche_queue(
                    queue_path=queue_path,
                    repo_root=repo_root,
                    execute_merge=requested_execute_merge and not dry_run,
                    allow_admin=bool(getattr(args, "allow_admin", False)),
                )
                payload["dry_run"] = dry_run
                payload["requested_execute_merge"] = requested_execute_merge
            else:
                payload = reconcile_tranche_queue(
                    queue_path=queue_path,
                    repo_root=repo_root,
                )
            payload["action"] = subaction
            payload["queue_path"] = str(queue_path)
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                if subaction == "harvest-queue":
                    _render_tranche_queue_harvest_table(payload)
                else:
                    _render_tranche_queue_status(payload)
            return
        if subaction == "plan":
            prompt_arg = str(getattr(args, "from_prompts", "") or "").strip()
            if not prompt_arg:
                raise ValueError("tranche plan requires --from-prompts <path>")
            prompt_path = Path(prompt_arg).resolve()
            if not prompt_path.exists():
                raise ValueError(f"prompt bundle not found: {prompt_path}")
            manifest_arg = str(getattr(args, "manifest", "") or "").strip()
            output_arg = str(getattr(args, "output", "") or "").strip()
            tranche_output_path: Path | None = None
            if output_arg:
                tranche_output_path = Path(output_arg).resolve()
            elif manifest_arg and manifest_arg != ".aragora/campaign_manifest.yaml":
                tranche_output_path = Path(manifest_arg).resolve()
            tranche_planner = TranchePlanner(repo_root=repo_root)
            manifest, saved_path = tranche_planner.plan_from_prompt_bundle(
                prompt_path,
                output_path=tranche_output_path,
            )
            payload = {
                "mode": "tranche-plan",
                "action": subaction,
                "manifest_id": manifest.manifest_id,
                "manifest_path": str(saved_path),
                "lane_count": len(manifest.lanes),
                "reference_groups": sorted(manifest.references),
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(f"manifest_id={manifest.manifest_id}")
                print(f"manifest_path={saved_path}")
                print(f"lanes={len(manifest.lanes)}")
            return

        manifest_arg = str(getattr(args, "manifest", "") or "").strip()
        if not manifest_arg:
            raise ValueError(f"tranche {subaction} requires --manifest <path>")
        manifest_path = Path(manifest_arg).resolve()
        if not manifest_path.exists():
            raise ValueError(f"tranche manifest not found: {manifest_path}")
        manifest = load_tranche_manifest(manifest_path)

        if subaction == "inspect":
            payload = TrancheInspector(repo_root=repo_root).inspect(manifest)
            payload["action"] = subaction
            payload["manifest_path"] = str(manifest_path)
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(render_tranche_inspection_text(payload))
            return

        if subaction == "watch":
            state_path = run_state_path_for_manifest(manifest_path)
            state = load_tranche_run_state(manifest_path)
            artifact_store = TrancheArtifactStore(repo_root=repo_root)
            driver_mode = bool(getattr(args, "driver", False))
            session_id = str(
                getattr(args, "owner_session_id", None) or f"cli-watch-{os.getpid()}"
            ).strip()
            executor = TrancheExecutor(repo_root=repo_root) if driver_mode else None  # type: ignore[assignment]
            supervisor = None
            github = None
            watch_pr_registry: "PullRequestRegistry | None" = None

            async def _watch_run_fn(*, manifest):
                if executor is None:
                    return None
                try:
                    return await executor.run(
                        manifest,
                        owner_session_id=session_id,
                        target_branch=str(getattr(args, "target_branch", "main") or "main"),
                        max_ticks=int(getattr(args, "max_ticks", 360) or 360),
                        wait_for_completion=False,
                        skip_review=True,
                    )
                except ValueError as exc:
                    detail = str(exc or "").strip()
                    if (
                        "No ready claimable lanes found" in detail
                        or "Tranche is not ready to run." in detail
                        or detail.endswith("is not ready.")
                    ):
                        return None
                    raise

            async def _watch_review_fn(*, manifest, lane_id, artifact):
                nonlocal supervisor
                from aragora.swarm.supervisor import SwarmSupervisor

                if artifact is None:
                    return {
                        "status": "blocked_nonreviewable",
                        "findings": ["Missing tranche artifact."],
                    }
                run_id = str(getattr(artifact, "run_id", None) or "").strip()
                if not run_id:
                    return {
                        "status": "blocked_nonreviewable",
                        "findings": ["Artifact has no run_id."],
                    }
                if supervisor is None:
                    supervisor = SwarmSupervisor(repo_root=repo_root)
                run_dict = refresh_supervisor_run_dict(supervisor, run_id)
                if run_dict is None:
                    return {
                        "status": "blocked_nonreviewable",
                        "findings": [f"Supervisor run {run_id} is not available."],
                    }
                tranche_lane = manifest.lane(lane_id)
                tier = select_review_tier(
                    write_scope=list(getattr(tranche_lane, "allowed_write_scope", [])),
                    diff_lines=int(getattr(artifact, "metadata", {}).get("diff_lines", 0) or 0),
                    verification_passed=bool(getattr(artifact, "commands", [])),
                    risk_tolerance=str(
                        getattr(artifact, "metadata", {}).get("risk_tolerance", "") or ""
                    ).strip()
                    or None,
                )
                return await review_lane(
                    manifest=manifest,
                    lane_id=lane_id,
                    artifact=artifact,
                    run_dict=run_dict,
                    tier=tier,
                    repo_root=repo_root,
                )

            async def _watch_integrate_fn(*, manifest, lane_id, artifact, approve, run_state=None):
                nonlocal github, watch_pr_registry
                if artifact is None:
                    return {"recommendation": "needs_human", "executed": False}
                if github is None:
                    github = GitHubControl(repo_root=repo_root)
                if watch_pr_registry is None:
                    watch_pr_registry = PullRequestRegistry()
                if DevCoordinationStore is None:
                    return {
                        "recommendation": "needs_human",
                        "executed": False,
                        "reason": "DevCoordinationStore unavailable",
                    }
                coord_store = DevCoordinationStore(repo_root=repo_root)
                return await integrate_lane(
                    artifact=artifact,
                    manifest=manifest,
                    approve=bool(approve),
                    repo_root=repo_root,
                    github=github,
                    registry=watch_pr_registry,
                    store=coord_store,
                    target_branch=str(getattr(args, "target_branch", "main") or "main"),
                    decided_by="tranche-watch",
                    rationale="Tranche watch approved merge after green checks and review.",
                    run_state=run_state,
                    autonomy_mode=str(state.autonomy_mode or "adaptive"),
                )

            if driver_mode:
                state = claim_driver(state, session_id=session_id)
                state.save(state_path)
            final_state = asyncio.run(
                watch_loop(
                    state,
                    manifest=manifest,
                    interval_seconds=interval_seconds,
                    max_ticks=max_ticks,
                    state_path=state_path,
                    driver_session_id=session_id if driver_mode else None,
                    artifact_store=artifact_store,
                    repo_root=repo_root,
                    run_fn=_watch_run_fn if driver_mode else None,
                    review_fn=_watch_review_fn if driver_mode else None,
                    integrate_fn=_watch_integrate_fn if driver_mode else None,
                )
            )
            if driver_mode:
                final_state = release_driver(final_state, session_id=session_id)
                final_state.save(state_path)
            payload = {
                "mode": "tranche-watch",
                "action": subaction,
                "manifest_id": manifest.manifest_id,
                "manifest_path": str(manifest_path),
                "driver": driver_mode,
                **final_state.to_dict(),
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(json.dumps(payload, indent=2))
            return

        if subaction == "design-review":
            from aragora.swarm.tranche_design_review import (
                DesignReviewRecord,
                run_design_review,
                save_design_review,
            )

            tranche_inspection = TrancheInspector(repo_root=repo_root).inspect(manifest)
            normalized_path = manifest_path.with_name("normalized_bundle.yaml")
            if normalized_path.exists():
                normalized_bundle = _load_structured_object(str(normalized_path))
            else:
                normalized_bundle = {
                    "manifest_id": getattr(manifest, "manifest_id", ""),
                    "objective": getattr(manifest, "objective", ""),
                    "lanes": [
                        lane.to_dict()
                        for lane in getattr(manifest, "lanes", [])
                        if hasattr(lane, "to_dict")
                    ],
                }
            payload = asyncio.run(
                run_design_review(
                    manifest=manifest,
                    normalized_bundle=normalized_bundle,
                    inspection=tranche_inspection,
                    max_rounds=int(getattr(args, "rounds", 2) or 2),
                )
            )
            record_payload = payload.get("record")
            if isinstance(record_payload, dict):
                save_design_review(
                    manifest_path.with_name("design_review.yaml"),
                    DesignReviewRecord.from_dict(record_payload),
                )
            payload["action"] = subaction
            payload["manifest_path"] = str(manifest_path)
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(json.dumps(payload, indent=2))
            return

        if subaction == "review":
            from aragora.swarm.supervisor import SwarmSupervisor

            artifact_store = TrancheArtifactStore(repo_root=repo_root)
            lane_id = str(getattr(args, "lane_id", "") or "").strip()
            all_completed = bool(getattr(args, "all_completed", False))
            if lane_id:
                artifact = artifact_store.load(manifest.manifest_id, lane_id)
                selected_artifacts = [artifact] if artifact is not None else []
            elif all_completed:
                selected_artifacts = [
                    item
                    for item in artifact_store.list(manifest.manifest_id)
                    if str(item.status).strip()
                    in {"completed", "review_passed", "changes_requested", "review_blocked"}
                ]
            else:
                raise ValueError("tranche review requires --lane-id <id> or --all-completed")
            if not selected_artifacts:
                raise ValueError("No matching tranche artifacts found for review.")
            supervisor = SwarmSupervisor(repo_root=repo_root)
            results: list[dict[str, object]] = []
            for artifact in selected_artifacts:
                run_id = str(getattr(artifact, "run_id", None) or "").strip()
                if not run_id:
                    raise ValueError(f"Artifact {artifact.lane_id} has no run_id.")
                run_dict = refresh_supervisor_run_dict(supervisor, run_id)
                if run_dict is None:
                    raise ValueError(f"Supervisor run {run_id} is not available.") from None
                tier_arg = str(getattr(args, "tier", "auto") or "auto").strip()
                if tier_arg == "auto":
                    tranche_lane = manifest.lane(artifact.lane_id)
                    tier = select_review_tier(
                        write_scope=list(getattr(tranche_lane, "allowed_write_scope", [])),
                        diff_lines=int(getattr(artifact, "metadata", {}).get("diff_lines", 0) or 0),
                        verification_passed=bool(getattr(artifact, "commands", [])),
                        risk_tolerance=str(
                            getattr(artifact, "metadata", {}).get("risk_tolerance", "") or ""
                        ).strip()
                        or None,
                    )
                else:
                    tier = int(tier_arg)
                review_payload = asyncio.run(
                    review_lane(
                        manifest=manifest,
                        lane_id=artifact.lane_id,
                        artifact=artifact,
                        run_dict=run_dict,
                        tier=tier,
                        repo_root=repo_root,
                    )
                )
                results.append({"lane_id": artifact.lane_id, **review_payload})
            payload = {
                "mode": "tranche-review",
                "action": subaction,
                "manifest_id": manifest.manifest_id,
                "manifest_path": str(manifest_path),
                "results": results,
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(json.dumps(payload, indent=2))
            return

        if subaction == "integrate":
            artifact_store = TrancheArtifactStore(repo_root=repo_root)
            lane_id = str(getattr(args, "lane_id", "") or "").strip()
            all_mergeable = bool(getattr(args, "all_mergeable", False))
            approve = bool(getattr(args, "approve", False))
            if lane_id:
                artifact = artifact_store.load(manifest.manifest_id, lane_id)
                selected_artifacts = [artifact] if artifact is not None else []
            elif all_mergeable:
                selected_artifacts = [
                    item
                    for item in artifact_store.list(manifest.manifest_id)
                    if str(item.status).strip() in {"review_passed", "completed"}
                ]
            else:
                raise ValueError("tranche integrate requires --lane-id <id> or --all-mergeable")
            if not selected_artifacts:
                raise ValueError("No matching tranche artifacts found for integrate.")

            github = GitHubControl(repo_root=repo_root)
            pr_registry = PullRequestRegistry()
            if approve and DevCoordinationStore is None:
                raise RuntimeError(
                    "tranche integrate --approve requires DevCoordinationStore (unavailable)"
                )
            tranche_store = (
                DevCoordinationStore(repo_root=repo_root)
                if approve and DevCoordinationStore is not None
                else None
            )
            state_path = run_state_path_for_manifest(manifest_path)
            run_state = None
            try:
                if state_path.exists():
                    run_state = load_tranche_run_state(manifest_path)
            except (OSError, ValueError):
                run_state = None
            tranche_results: list[JsonDict] = []
            for artifact in selected_artifacts:
                lane_result: JsonDict = asyncio.run(
                    integrate_lane(
                        manifest=manifest,
                        artifact=artifact,
                        approve=approve,
                        repo_root=repo_root,
                        github=github,
                        registry=pr_registry,
                        store=tranche_store,
                        artifact_store=artifact_store,
                        target_branch=str(getattr(args, "target_branch", "main") or "main"),
                        decided_by=str(getattr(args, "decided_by", None) or "tranche-integrate"),
                        rationale=str(
                            getattr(args, "rationale", None)
                            or "Tranche integrate approved merge after green checks and review."
                        ),
                        run_state=run_state,
                        autonomy_mode=str(getattr(args, "autonomy", "adaptive") or "adaptive"),
                    )
                )
                tranche_results.append(lane_result)

                if run_state is not None:
                    run_state.save(state_path)

                payload = {
                    "mode": "tranche-integrate",
                    "action": subaction,
                    "manifest_id": manifest.manifest_id,
                    "manifest_path": str(manifest_path),
                    "approve": approve,
                    "results": tranche_results,
                }
                if as_json:
                    print(json.dumps(payload, indent=2))
                else:
                    print(json.dumps(payload, indent=2))
            return

        tranche_executor = TrancheExecutor(repo_root=repo_root)
        lane_id = str(getattr(args, "lane_id", "") or "").strip()
        all_ready = bool(getattr(args, "all_ready", False))
        owner_agent = _optional_text(getattr(args, "owner_agent", None))
        owner_session_id = _optional_text(getattr(args, "owner_session_id", None))
        if subaction == "prepare":
            payload = tranche_executor.prepare(
                manifest,
                lane_id=lane_id,
                all_ready=all_ready,
                owner_agent=owner_agent,
                owner_session_id=owner_session_id,
                base_branch=str(getattr(args, "target_branch", "main") or "main"),
            )
        elif subaction == "run":
            payload = asyncio.run(
                tranche_executor.run(
                    manifest,
                    lane_id=lane_id,
                    all_ready=all_ready,
                    owner_agent=owner_agent,
                    owner_session_id=owner_session_id,
                    target_branch=str(getattr(args, "target_branch", "main") or "main"),
                    max_ticks=int(getattr(args, "max_ticks", 360) or 360),
                    wait_for_completion=not bool(getattr(args, "no_wait", False)),
                    skip_review=bool(getattr(args, "skip_review", False)),
                    allow_claude_dangerously_skip_permissions=allow_claude_write,
                )
            )
        else:
            raise ValueError(
                "tranche action must be one of: submit, plan, inspect, watch, list, design-review, review, integrate, prepare, run, status, compile-queue, run-queue, reconcile-queue, harvest-queue"
                ", explore-queue, plan-queue"
            )
        payload["action"] = subaction
        payload["manifest_path"] = str(manifest_path)
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(json.dumps(payload, indent=2))
        return

    if boss_mode:
        boss_routing = _resolve_boss_routing(
            requested_runner_type=str(getattr(args, "worker_model", "") or "").strip() or None,
            allowed_profiles=allowed_runner_profiles,
            rotation_interval_seconds=runner_rotation_interval,
        )
        blocked_reason = boss_routing.get("blocked_reason")
        if isinstance(blocked_reason, str) and blocked_reason.strip():
            from aragora.swarm.reporter import render_boss_text

            payload = _blocked_boss_payload(
                goal=goal,
                target_branch=target_branch,
                routing=boss_routing,
            )
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(render_boss_text(payload))
            return
    if action == "status":
        from aragora.cli.commands.swarm_status import load_operator_status, render_operator_status
        from aragora.swarm.session_coordinator import read_directives as coord_read

        repo_root = resolve_repo_root(Path.cwd())
        try:
            supervisor = SwarmSupervisor(repo_root=repo_root)
            payload = supervisor.status_summary(
                run_id=run_id,
                limit=int(getattr(args, "status_limit", 20)),
                refresh_scaling=refresh_scaling,
            )
        except (sqlite3.Error, OSError, RuntimeError) as exc:
            payload = {
                "runs": [],
                "counts": {
                    "runs": 0,
                    "queued_work_orders": 0,
                    "leased_work_orders": 0,
                    "completed_work_orders": 0,
                },
                "coordination": {
                    "available": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            }
        base_branch = str(getattr(args, "target_branch", "main") or "main")
        worktrees = build_fleet_rows(
            repo_root,
            base_branch=base_branch,
            tail=0,
            include_git_metrics=False,
        )
        status_fleet_store = FleetCoordinationStore(repo_root)
        claims = status_fleet_store.list_claims()
        merge_queue = status_fleet_store.list_merge_queue()
        payload["integrator_view"] = build_integrator_view(
            runs=payload.get("runs", []),
            worktrees=worktrees,
            claims=claims,
            merge_queue=merge_queue,
            coordination=payload.get("coordination", {}),
        )
        payload["coordination_view"] = coord_read(
            repo_root,
            findings_limit=max(1, int(getattr(args, "findings_limit", 10))),
        )
        payload["operator_status"] = load_operator_status(
            repo_root,
            limit=10,
            boss_repo=_optional_text(getattr(args, "boss_repo", None)),
        )
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                "runs={runs} queued={queued} leased={leased} completed={completed}".format(
                    runs=payload["counts"].get("runs", 0),
                    queued=payload["counts"].get("queued_work_orders", 0),
                    leased=payload["counts"].get("leased_work_orders", 0),
                    completed=payload["counts"].get("completed_work_orders", 0),
                )
            )
            integrator_summary = payload["integrator_view"].get("summary", {})
            print(
                "integrator ready={ready} review={review} blocked={blocked} stale={stale} "
                "collisions={collisions} missing_receipts={missing} superseded={superseded}".format(
                    ready=integrator_summary.get("ready_lanes", 0),
                    review=integrator_summary.get("review_lanes", 0),
                    blocked=integrator_summary.get("blocked_lanes", 0),
                    stale=integrator_summary.get("stale_heartbeat_lanes", 0),
                    collisions=integrator_summary.get("collision_lanes", 0),
                    missing=integrator_summary.get("missing_receipt_lanes", 0),
                    superseded=integrator_summary.get("superseded_lanes", 0),
                )
            )
            for action_text in payload["integrator_view"].get("next_actions", [])[:3]:
                print(f"next: {action_text}")
            for run in payload.get("runs", []):
                if isinstance(run, dict):
                    print("---")
                    _print_supervisor_run(run)
            print("---")
            _render_coordination_view(payload["coordination_view"])
            print("---")
            print(render_operator_status(payload["operator_status"]))
        return

    if action == "shift-status":
        from aragora.cli.commands.shift_status import cmd_shift_status

        cmd_shift_status(args)
        return

    if action == "harness-status":
        from aragora.cli.commands.harness_status import cmd_harness_status

        cmd_harness_status(args)
        return

    if action == "reconcile":
        reconciler = SwarmReconciler(repo_root=Path.cwd())
        if all_runs:
            runs = asyncio.run(
                reconciler.tick_open_runs(limit=int(getattr(args, "status_limit", 20)))
            )
            payload = {"runs": [run.to_dict() for run in runs], "count": len(runs)}
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(f"runs={payload['count']}")
                for run in payload["runs"]:
                    print("---")
                    _print_supervisor_run(run)
            return
        if not run_id:
            print("Error: provide --run-id or --all-runs for 'reconcile'")
            return
        run = asyncio.run(
            reconciler.watch_run(
                run_id,
                interval_seconds=interval_seconds,
                max_ticks=max_ticks,
            )
            if watch
            else reconciler.tick_run(run_id)
        )
        if as_json:
            print(json.dumps(run.to_dict(), indent=2))
        else:
            _print_supervisor_run(run.to_dict())
        return

    if not goal and not spec_file and not from_obsidian:
        print("Error: provide a goal or --spec file (or --from-obsidian vault)")
        print('Usage: aragora swarm run "your goal here"')
        return

    config = SwarmCommanderConfig(
        interrogator=InterrogatorConfig(user_profile=user_profile),
        budget_limit_usd=budget_limit,
        require_approval=require_approval,
        max_parallel_tasks=max_parallel,
        iterative_mode=not no_loop,
        user_profile=user_profile,
        obsidian_vault_path=obsidian_vault or from_obsidian,
        obsidian_write_receipts=not no_obsidian_receipts,
        autonomy_level=autonomy_level,
    )
    commander = SwarmCommander(config=config)
    approval_policy = SwarmApprovalPolicy(
        require_merge_approval=True,
        require_external_action_approval=True,
    )

    # Phase 4: Load goals from Obsidian
    if from_obsidian and not goal:
        goals = asyncio.run(commander._load_from_obsidian(from_obsidian))
        if goals:
            goal = goals[0]  # Use first tagged note as goal
            print(f"\nLoaded goal from Obsidian: {goal[:100]}...")
        else:
            print("No #swarm tagged notes found in Obsidian vault")
            return

    if spec_file:
        spec_path = Path(spec_file)
        if not spec_path.exists():
            print(f"Error: spec file not found: {spec_file}")
            return
        spec = SwarmSpec.from_yaml(spec_path.read_text())
        print(f"\nLoaded spec from {spec_file}")
        print(spec.summary())
        run = _run_supervised_or_report(
            commander.run_supervised_from_spec(
                spec,
                repo_path=Path.cwd(),
                target_branch=target_branch,
                max_concurrency=concurrency_cap,
                managed_dir_pattern=managed_dir_pattern,
                approval_policy=approval_policy,
                dispatch=dispatch_workers,
                wait=not no_wait,
                interval_seconds=interval_seconds,
                max_ticks=max_ticks,
            )
        )
        if run is None:
            return
        run_payload = run.to_dict()
        if boss_mode:
            boss_payload = _build_boss_payload(
                run_payload,
                repo_root=Path.cwd(),
                target_branch=target_branch,
                routing=boss_routing,
            )
            if as_json:
                print(json.dumps(boss_payload, indent=2))
            else:
                from aragora.swarm.reporter import render_boss_text

                print(render_boss_text(boss_payload))
            return
        if as_json:
            print(json.dumps(run_payload, indent=2))
        else:
            _print_supervisor_run(run_payload)
    elif dry_run:
        goal_text = goal or ""
        if skip_interrogation:
            spec = SwarmSpec(
                id=str(uuid4()),
                created_at=datetime.now(timezone.utc),
                raw_goal=goal_text,
                refined_goal=goal_text,
                budget_limit_usd=budget_limit,
                requires_approval=require_approval,
                interrogation_turns=0,
                user_expertise="developer",
            )
            print("\n[DRY RUN] Skipping interrogation and building a direct spec.\n")
            print(spec.to_json(indent=2))
        else:
            spec = asyncio.run(commander.dry_run(goal_text))
        save_path = getattr(args, "save_spec", None)
        if save_path:
            Path(save_path).write_text(spec.to_yaml())
            print(f"\nSpec saved to {save_path}")
    elif skip_interrogation:
        goal_text = goal or ""
        spec = SwarmSpec.from_direct_goal(
            goal_text,
            budget_limit_usd=budget_limit,
            requires_approval=require_approval,
            user_expertise="developer",
        )
        print("\nSkipping interrogation (developer mode)")
        print(spec.summary())
        if not spec.is_dispatch_bounded():
            print(f"Error: {spec.dispatch_gate_reason()}")
            return
        run = _run_supervised_or_report(
            commander.run_supervised_from_spec(
                spec,
                repo_path=Path.cwd(),
                target_branch=target_branch,
                max_concurrency=concurrency_cap,
                managed_dir_pattern=managed_dir_pattern,
                approval_policy=approval_policy,
                dispatch=dispatch_workers,
                wait=not no_wait,
                interval_seconds=interval_seconds,
                max_ticks=max_ticks,
            )
        )
        if run is None:
            return
        run_payload = run.to_dict()
        if boss_mode:
            boss_payload = _build_boss_payload(
                run_payload,
                repo_root=Path.cwd(),
                target_branch=target_branch,
                routing=boss_routing,
            )
            if as_json:
                print(json.dumps(boss_payload, indent=2))
            else:
                from aragora.swarm.reporter import render_boss_text

                print(render_boss_text(boss_payload))
            return
        if as_json:
            print(json.dumps(run_payload, indent=2))
        else:
            _print_supervisor_run(run_payload)
    else:
        run = _run_supervised_or_report(
            commander.run_supervised(
                goal or "",
                repo_path=Path.cwd(),
                target_branch=target_branch,
                max_concurrency=concurrency_cap,
                managed_dir_pattern=managed_dir_pattern,
                approval_policy=approval_policy,
                dispatch=dispatch_workers,
                wait=not no_wait,
                interval_seconds=interval_seconds,
                max_ticks=max_ticks,
            )
        )
        if run is None:
            return
        run_payload = run.to_dict()
        if boss_mode:
            boss_payload = _build_boss_payload(
                run_payload,
                repo_root=Path.cwd(),
                target_branch=target_branch,
                routing=boss_routing,
            )
            if as_json:
                print(json.dumps(boss_payload, indent=2))
            else:
                from aragora.swarm.reporter import render_boss_text

                print(render_boss_text(boss_payload))
            return
        if as_json:
            print(json.dumps(run_payload, indent=2))
        else:
            _print_supervisor_run(run_payload)
