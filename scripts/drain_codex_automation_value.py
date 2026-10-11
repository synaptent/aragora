#!/usr/bin/env python3
"""Conservative authenticated drain for Codex automation outbox value.

This script composes the existing Aragora publisher and settlement helpers. It
does not interpret raw outbox handoffs as merge authority. The only automated
merge path is an exact-head protected squash after current required checks,
review-queue merge-packet, settle-one, and owner gates all pass.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from aragora.swarm.merge_halt import evaluate_merge_halt  # noqa: E402
from scripts.github_cli_health import check_github_cli_health  # noqa: E402

DEFAULT_GITHUB_REPO = "synaptent/aragora"
DEFAULT_MAX_OPEN_PRS = 12
DEFAULT_MAX_OPEN_ISSUES = 16
DEFAULT_BRANCH_LIMIT = 2
DEFAULT_ISSUE_LIMIT = 4
DEFAULT_MERGE_LIMIT = 1
DEFAULT_BRANCH_SCAN_LIMIT = 40
DEFAULT_COMMAND_TIMEOUT_SECONDS = 120
DEFAULT_GH_TIMEOUT_SECONDS = 45
DEFAULT_BASE = "origin/main"
PYTHON = sys.executable or "python3"
PASS_CHECK_STATES = {"SUCCESS", "NEUTRAL", "SKIPPED", "PASS", "PASSED"}
PENDING_CHECK_STATES = {
    "EXPECTED",
    "PENDING",
    "QUEUED",
    "REQUESTED",
    "STARTUP_FAILURE",
    "WAITING",
    "IN_PROGRESS",
}
ACTIVE_OWNER_STATUSES = {
    "active",
    "running",
    "pending",
    "queued",
    "claimed",
    "waiting_for_steering",
    "acknowledged",
    "working",
    "blocked",
}

try:
    from aragora.swarm.github_app_auth import gh_subprocess_run, github_cli_env
except ImportError:  # pragma: no cover - fallback for partially bootstrapped contexts

    def github_cli_env(
        base_env: Mapping[str, str] | None = None,
        *,
        prefer_app: bool = True,
    ) -> dict[str, str]:
        del prefer_app
        return dict(os.environ if base_env is None else base_env)

    def gh_subprocess_run(
        args: Sequence[str],
        *,
        timeout: float = 30.0,
        prefer_app: bool = True,
        write_op: bool = False,
        env: Mapping[str, str] | None = None,
        max_retries: int = 0,
        base_backoff: float = 5.0,
        max_backoff: float = 600.0,
        sleep: Callable[[float], None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del prefer_app, max_retries, base_backoff, max_backoff, sleep
        if write_op:
            command = ["gh", *list(args)]
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "GitHub app auth unavailable for write operation; refusing gh fallback",
            )
        return subprocess.run(
            ["gh", *list(args)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=dict(os.environ if env is None else env),
            check=False,
        )


Runner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class DrainConfig:
    repo_root: Path
    github_repo: str
    state_root: Path
    outbox_dir: Path
    receipt_dir: Path
    cache_output: Path | None
    base: str
    branch_limit: int
    issue_limit: int
    merge_limit: int
    max_open_prs: int
    max_open_issues: int
    branch_scan_limit: int
    apply: bool


@dataclass(frozen=True)
class MergeEvaluation:
    pr_number: int
    title: str
    url: str
    head_sha: str
    eligible: bool
    reason: str
    blockers: list[str]
    command: list[str]
    applied: bool = False


def _gh_write_op(args: Sequence[str]) -> bool:
    return len(args) >= 2 and tuple(args[:2]) in {
        ("api", "--method"),
        ("pr", "merge"),
        ("pr", "ready"),
        ("pr", "create"),
        ("pr", "edit"),
        ("issue", "create"),
    }


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _run(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    command = list(args)
    if command and command[0] == "gh":
        timeout = _env_int("ARAGORA_AUTOMATION_GH_TIMEOUT_SECONDS", DEFAULT_GH_TIMEOUT_SECONDS)
        return gh_subprocess_run(
            command[1:],
            timeout=timeout,
            prefer_app=True,
            write_op=_gh_write_op(command[1:]),
            env=github_cli_env(os.environ),
            max_retries=0,
        )
    timeout = _env_int(
        "ARAGORA_AUTOMATION_VALUE_DRAIN_TIMEOUT_SECONDS", DEFAULT_COMMAND_TIMEOUT_SECONDS
    )
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        message = stderr or f"command timed out after {timeout}s: {' '.join(command)}"
        return subprocess.CompletedProcess(command, 124, stdout, message)


def _repo_root(path: Path) -> Path:
    proc = _run(["git", "rev-parse", "--show-toplevel"], path)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "not a git repository")
    return Path(proc.stdout.strip()).resolve()


def _state_root(repo_root: Path, value: Path | None) -> Path:
    if value is not None:
        expanded = value.expanduser()
        return expanded.resolve() if expanded.is_absolute() else (repo_root / expanded).resolve()
    return repo_root


def _state_default_path(state_root: Path, default_relative: Path) -> Path:
    if default_relative.parts[:1] == (".aragora",) and state_root.name == ".aragora":
        return state_root.joinpath(*default_relative.parts[1:]).resolve()
    return (state_root / default_relative).resolve()


def _resolve_state_path(state_root: Path, value: Path | None, default_relative: Path) -> Path:
    if value is None:
        return _state_default_path(state_root, default_relative)
    expanded = value.expanduser()
    return expanded.resolve() if expanded.is_absolute() else (state_root / expanded).resolve()


def _json_or_none(text: str) -> Any:
    try:
        return json.loads(text or "")
    except json.JSONDecodeError:
        return None


def _trim_output(text: str, *, limit: int = 2000) -> str:
    stripped = (text or "").strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "...[truncated]"


def _phase_result(
    name: str,
    command: Sequence[str],
    proc: subprocess.CompletedProcess[str],
) -> dict[str, Any]:
    payload = _json_or_none(proc.stdout)
    result: dict[str, Any] = {
        "name": name,
        "command": list(command),
        "returncode": proc.returncode,
        "ok": proc.returncode == 0,
    }
    if payload is not None:
        result["json"] = payload
    else:
        result["stdout"] = _trim_output(proc.stdout)
    if proc.stderr.strip():
        result["stderr"] = _trim_output(proc.stderr)
    return result


def _run_json(
    args: Sequence[str], cwd: Path, runner: Runner
) -> tuple[Any, subprocess.CompletedProcess[str]]:
    proc = runner(args, cwd)
    payload = _json_or_none(proc.stdout)
    return payload, proc


def _cache_command(config: DrainConfig, *, output: Path) -> list[str]:
    return [
        PYTHON,
        "scripts/cache_codex_automation_github_status.py",
        "--repo",
        str(config.repo_root),
        "--github-repo",
        config.github_repo,
        "--state-root",
        str(config.state_root),
        "--outbox-dir",
        str(config.outbox_dir),
        "--receipt-dir",
        str(config.receipt_dir),
        "--output",
        str(output),
        "--max-open-prs",
        str(config.max_open_prs),
        "--max-open-issues",
        str(config.max_open_issues),
        "--json",
        "--summary-only",
    ]


def _reconcile_command(config: DrainConfig) -> list[str]:
    command = [
        PYTHON,
        "scripts/reconcile_automation_outbox.py",
        "--repo",
        str(config.repo_root),
        "--base",
        config.base,
        "--state-root",
        str(config.state_root),
        "--outbox-dir",
        str(config.outbox_dir),
        "--receipt-dir",
        str(config.receipt_dir),
        "--json",
        "--summary-only",
    ]
    command.append("--apply" if config.apply else "--dry-run")
    return command


def _branch_publish_command(config: DrainConfig) -> list[str]:
    command = [
        PYTHON,
        "scripts/publish_codex_automation_branches.py",
        "--repo",
        str(config.repo_root),
        "--base",
        config.base,
        "--github-repo",
        config.github_repo,
        "--limit",
        str(config.branch_limit),
        "--max-open-prs",
        str(config.max_open_prs),
        "--scan-limit",
        str(config.branch_scan_limit),
        "--outbox-dir",
        str(config.outbox_dir),
        "--receipt-dir",
        str(config.receipt_dir),
        "--draft",
        "--json",
        "--summary-only",
    ]
    command.append("--apply" if config.apply else "--dry-run")
    return command


def issue_publish_blocker(cache_payload: Mapping[str, Any], *, max_open_issues: int) -> str | None:
    github_queue = cache_payload.get("github_queue")
    if not isinstance(github_queue, Mapping):
        return "github_queue unavailable"
    if github_queue.get("available") is False:
        return f"github_queue unavailable: {github_queue.get('reason') or 'unknown'}"
    pressure = github_queue.get("pressure")
    if isinstance(pressure, Mapping) and pressure.get("open_issue_cap_reached") is True:
        return "open issue cap reached"
    open_issue_count = github_queue.get("open_issue_count")
    if isinstance(open_issue_count, int) and open_issue_count >= max_open_issues:
        return f"open_issue_count={open_issue_count} at or above cap {max_open_issues}"
    return None


def _issue_publish_command(config: DrainConfig) -> list[str]:
    command = [
        PYTHON,
        "scripts/publish_automation_handoffs.py",
        "--repo",
        str(config.repo_root),
        "--github-repo",
        config.github_repo,
        "--state-root",
        str(config.state_root),
        "--outbox-dir",
        str(config.outbox_dir),
        "--receipt-dir",
        str(config.receipt_dir),
        "--limit",
        str(config.issue_limit),
        "--max-open-issues",
        str(config.max_open_issues),
        "--json",
        "--summary-only",
    ]
    command.append("--apply" if config.apply else "--dry-run")
    return command


def protected_squash_merge_command(pr_number: int, head_sha: str) -> list[str]:
    return [
        "gh",
        "pr",
        "merge",
        str(pr_number),
        "--squash",
        "--match-head-commit",
        head_sha,
    ]


def required_check_blockers(required_checks: Any) -> list[str]:
    if not isinstance(required_checks, list):
        return ["required checks unavailable"]
    if not required_checks:
        return ["required checks unavailable: empty required-check JSON"]
    blockers: list[str] = []
    for row in required_checks:
        if not isinstance(row, Mapping):
            blockers.append("required checks malformed")
            continue
        name = str(row.get("name") or row.get("workflow") or "(unnamed)")
        state = str(row.get("state") or "").strip().upper()
        bucket = str(row.get("bucket") or "").strip().lower()
        if state in PASS_CHECK_STATES or bucket == "pass":
            continue
        if state in PENDING_CHECK_STATES or bucket == "pending":
            blockers.append(f"required check pending: {name} ({state or bucket})")
            continue
        blockers.append(f"required check failed: {name} ({state or bucket or 'unknown'})")
    return blockers


def _entry_pr(entry: Mapping[str, Any]) -> int | None:
    for key in ("pr_number", "number", "pr"):
        value = entry.get(key)
        if isinstance(value, int):
            return value
        try:
            return int(str(value))
        except (TypeError, ValueError):
            continue
    return None


def _entry_by_pr(packet: Mapping[str, Any], pr_number: int) -> Mapping[str, Any] | None:
    for entry in packet.get("entries") or []:
        if isinstance(entry, Mapping) and _entry_pr(entry) == pr_number:
            return entry
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def merge_packet_blockers(packet: Any, *, pr_number: int, head_sha: str) -> list[str]:
    if not isinstance(packet, Mapping):
        return ["merge-packet unavailable"]
    not_ready = packet.get("not_ready")
    if not_ready not in (None, []):
        return [f"merge-packet not_ready is non-empty: {not_ready}"]
    order = [_int_or_none(item) for item in packet.get("admin_squash_order") or []]
    if pr_number not in order:
        return ["merge-packet admin_squash_order does not contain PR"]
    entry = _entry_by_pr(packet, pr_number)
    if entry is None:
        return ["merge-packet has no entry for PR"]

    blockers: list[str] = []
    entry_head = str(entry.get("head_sha") or entry.get("headRefOid") or "").strip()
    if entry_head and entry_head != head_sha:
        blockers.append(f"merge-packet head {entry_head} does not match live head {head_sha}")
    tier = _int_or_none(entry.get("tier"))
    if tier is None:
        blockers.append("merge-packet tier unavailable")
    elif tier > 2:
        blockers.append(f"Tier {tier} requires report-only handling")
    if bool(entry.get("requires_human_risk_settlement")):
        blockers.append("requires_human_risk_settlement=true")
    if bool(entry.get("unresolved_dissent")):
        blockers.append("unresolved_dissent=true")
    if entry.get("admin_squash_allowed") is not True:
        blockers.append("merge-packet admin_squash_allowed is not true")
    if str(entry.get("status") or "") != "satisfied":
        blockers.append("merge-packet status is not satisfied")
    if str(entry.get("verdict") or "") != "admin_squash_allowed":
        blockers.append("merge-packet verdict is not admin_squash_allowed")
    recommendation = str(entry.get("machine_recommendation") or "").strip()
    if recommendation == "repair_first":
        blockers.append("merge-packet recommends repair_first")
    return blockers


def settle_one_blockers(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["settle_one unavailable"]
    raw_blockers = payload.get("blockers")
    if raw_blockers in (None, []):
        return []
    if isinstance(raw_blockers, list):
        return [f"settle_one blocker: {item}" for item in raw_blockers]
    return [f"settle_one blockers malformed: {raw_blockers}"]


def owner_blockers(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["owner status unavailable"]
    error = str(payload.get("error") or "").strip()
    if payload.get("ok") is False and error and "no lane matched" not in error.lower():
        return [f"owner status unavailable: {error}"]
    status = str(payload.get("status") or "").strip().lower()
    if status == "unavailable":
        detail = str(payload.get("error") or "owner lookup failed").strip()
        return [f"owner status unavailable: {detail}"]
    owner_session = str(payload.get("owner_session") or "").strip()
    if status in ACTIVE_OWNER_STATUSES and owner_session:
        return [f"active owner: {owner_session} ({status})"]
    return []


def pr_view_blockers(pr_view: Any) -> list[str]:
    if not isinstance(pr_view, Mapping):
        return ["PR view unavailable"]
    blockers: list[str] = []
    state = str(pr_view.get("state") or "").strip()
    if state and state != "OPEN":
        blockers.append(f"PR state is {state}")
    if bool(pr_view.get("isDraft")):
        blockers.append("PR is draft")
    mergeable = str(pr_view.get("mergeable") or "").strip()
    if mergeable != "MERGEABLE":
        blockers.append(f"mergeable={mergeable or '(unknown)'}")
    merge_state = str(pr_view.get("mergeStateStatus") or "").strip()
    if merge_state in {"DIRTY", "CONFLICTING", "UNKNOWN"}:
        blockers.append(f"mergeStateStatus={merge_state}")
    head_sha = str(pr_view.get("headRefOid") or "").strip()
    if not head_sha:
        blockers.append("missing headRefOid")
    return blockers


def evaluate_merge_candidate(
    *,
    pr_view: Mapping[str, Any],
    required_checks: Any,
    merge_packet: Any,
    settle_one: Any,
    owner: Any,
) -> MergeEvaluation:
    pr_number = int(pr_view.get("number") or 0)
    title = str(pr_view.get("title") or "")
    url = str(pr_view.get("url") or "")
    head_sha = str(pr_view.get("headRefOid") or "")
    blockers: list[str] = []
    blockers.extend(owner_blockers(owner))
    blockers.extend(pr_view_blockers(pr_view))
    blockers.extend(required_check_blockers(required_checks))
    if not blockers:
        blockers.extend(merge_packet_blockers(merge_packet, pr_number=pr_number, head_sha=head_sha))
    if not blockers:
        blockers.extend(settle_one_blockers(settle_one))
    command = protected_squash_merge_command(pr_number, head_sha) if pr_number and head_sha else []
    return MergeEvaluation(
        pr_number=pr_number,
        title=title,
        url=url,
        head_sha=head_sha,
        eligible=not blockers,
        reason="eligible" if not blockers else blockers[0],
        blockers=blockers,
        command=command,
    )


def _open_codex_prs(
    config: DrainConfig, runner: Runner
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    command = [
        "gh",
        "pr",
        "list",
        "--repo",
        config.github_repo,
        "--state",
        "open",
        "--limit",
        "100",
        "--json",
        "number,title,headRefName,url",
    ]
    payload, proc = _run_json(command, config.repo_root, runner)
    phase = _phase_result("open_pr_list", command, proc)
    if proc.returncode != 0 or not isinstance(payload, list):
        return [], phase
    return [
        item
        for item in payload
        if isinstance(item, dict) and str(item.get("headRefName") or "").startswith("codex/")
    ], phase


def _inspect_merge_candidate(
    pr_number: int,
    config: DrainConfig,
    runner: Runner,
) -> tuple[MergeEvaluation | None, list[dict[str, Any]]]:
    phases: list[dict[str, Any]] = []
    view_cmd = [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        config.github_repo,
        "--json",
        "number,state,isDraft,title,headRefName,headRefOid,mergeable,mergeStateStatus,url,files",
    ]
    pr_view, proc = _run_json(view_cmd, config.repo_root, runner)
    phases.append(_phase_result(f"pr_{pr_number}_view", view_cmd, proc))
    if proc.returncode != 0 or not isinstance(pr_view, Mapping):
        return None, phases

    owner_cmd = [PYTHON, "scripts/identify_lane_owner.py", "--pr", str(pr_number), "--json"]
    owner, proc = _run_json(owner_cmd, config.repo_root, runner)
    phases.append(_phase_result(f"pr_{pr_number}_owner", owner_cmd, proc))
    if proc.returncode != 0:
        owner_error = ""
        if isinstance(owner, Mapping):
            owner_error = str(owner.get("error") or "").strip()
        if "no lane matched" not in owner_error.lower():
            owner = {
                "status": "unavailable",
                "error": owner_error
                or _trim_output(proc.stderr or proc.stdout)
                or "owner lookup failed",
                "returncode": proc.returncode,
            }

    checks_cmd = [
        "gh",
        "pr",
        "checks",
        str(pr_number),
        "--repo",
        config.github_repo,
        "--required",
        "--json",
        "name,state,bucket,workflow,link",
    ]
    required_checks, proc = _run_json(checks_cmd, config.repo_root, runner)
    phases.append(_phase_result(f"pr_{pr_number}_required_checks", checks_cmd, proc))

    packet_cmd = [
        PYTHON,
        "-m",
        "aragora.cli.main",
        "review-queue",
        "merge-packet",
        "--pr",
        str(pr_number),
        "--json",
    ]
    packet, proc = _run_json(packet_cmd, config.repo_root, runner)
    phases.append(_phase_result(f"pr_{pr_number}_merge_packet", packet_cmd, proc))

    settle_cmd = [PYTHON, "scripts/settle_one_pr.py", "--pr", str(pr_number), "--json"]
    settle, proc = _run_json(settle_cmd, config.repo_root, runner)
    phases.append(_phase_result(f"pr_{pr_number}_settle_one", settle_cmd, proc))

    return (
        evaluate_merge_candidate(
            pr_view=pr_view,
            required_checks=required_checks,
            merge_packet=packet,
            settle_one=settle,
            owner=owner,
        ),
        phases,
    )


def _run_merge_phase(config: DrainConfig, runner: Runner) -> dict[str, Any]:
    phase: dict[str, Any] = {
        "name": "merge_existing_prs",
        "limit": config.merge_limit,
        "evaluations": [],
        "commands": [],
        "merged": [],
        "skipped": [],
    }
    if config.merge_limit <= 0:
        phase["skipped"].append({"reason": "merge_limit=0"})
        phase["ok"] = True
        return phase

    prs, list_phase = _open_codex_prs(config, runner)
    phase["commands"].append(list_phase)
    merged_count = 0
    for pr in sorted(prs, key=lambda item: int(item.get("number") or 0)):
        if merged_count >= config.merge_limit:
            break
        pr_number = int(pr.get("number") or 0)
        if pr_number <= 0:
            continue
        evaluation, phases = _inspect_merge_candidate(pr_number, config, runner)
        phase["commands"].extend(phases)
        if evaluation is None:
            phase["skipped"].append({"pr_number": pr_number, "reason": "inspection_failed"})
            continue
        evaluation_payload = asdict(evaluation)
        if not evaluation.eligible:
            phase["evaluations"].append(evaluation_payload)
            phase["skipped"].append(
                {
                    "pr_number": evaluation.pr_number,
                    "head_sha": evaluation.head_sha,
                    "reason": evaluation.reason,
                }
            )
            continue
        if not config.apply:
            phase["evaluations"].append(evaluation_payload)
            continue

        halt = evaluate_merge_halt(evaluation.pr_number, evaluation.head_sha)  # #9216
        if not halt.allowed:
            phase["evaluations"].append(evaluation_payload)
            phase["skipped"].append(
                {
                    "pr_number": evaluation.pr_number,
                    "head_sha": evaluation.head_sha,
                    "reason": "merge halt armed",
                    "error": halt.reason,
                }
            )
            phase["ok"] = False
            return phase

        merge_cmd = evaluation.command
        proc = runner(merge_cmd, config.repo_root)
        merge_result = _phase_result(f"pr_{pr_number}_protected_squash_merge", merge_cmd, proc)
        phase["commands"].append(merge_result)
        if proc.returncode != 0:
            phase["evaluations"].append(evaluation_payload)
            phase["skipped"].append(
                {
                    "pr_number": evaluation.pr_number,
                    "head_sha": evaluation.head_sha,
                    "reason": "protected squash merge rejected",
                    "error": merge_result.get("stderr") or merge_result.get("stdout"),
                }
            )
            phase["ok"] = False
            return phase
        merged_count += 1
        phase["merged"].append(
            {
                "pr_number": evaluation.pr_number,
                "head_sha": evaluation.head_sha,
                "command": merge_cmd,
            }
        )
        phase["evaluations"].append({**evaluation_payload, "applied": True})

    phase["ok"] = True
    return phase


def run_drain(config: DrainConfig, *, runner: Runner | None = None) -> dict[str, Any]:
    runner = runner or _run
    report: dict[str, Any] = {
        "mode": "apply" if config.apply else "dry-run",
        "repo": str(config.repo_root),
        "github_repo": config.github_repo,
        "state_root": str(config.state_root),
        "limits": {
            "branch_limit": config.branch_limit,
            "issue_limit": config.issue_limit,
            "merge_limit": config.merge_limit,
            "max_open_prs": config.max_open_prs,
            "max_open_issues": config.max_open_issues,
        },
        "phases": [],
    }
    health = check_github_cli_health(config.repo_root)
    report["github_health"] = health.to_dict()
    if not health.ready:
        report["status"] = "github_unavailable"
        report["blockers"] = [health.error or health.mode]
        return report

    with tempfile.TemporaryDirectory(prefix="aragora-value-drain-cache-") as tmpdir:
        if config.cache_output is not None:
            cache_output = config.cache_output
        elif config.apply:
            cache_output = _state_default_path(
                config.state_root,
                Path(".aragora/automation-github-status/latest.json"),
            )
        else:
            cache_output = Path(tmpdir) / "latest.json"
        cache_cmd = _cache_command(config, output=cache_output)
        cache_payload, proc = _run_json(cache_cmd, config.repo_root, runner)
        cache_phase = _phase_result("cache_refresh_before", cache_cmd, proc)
        report["phases"].append(cache_phase)
        if proc.returncode != 0 or not isinstance(cache_payload, Mapping):
            report["status"] = "cache_refresh_failed"
            report["blockers"] = [
                cache_phase.get("stderr") or cache_phase.get("stdout") or "cache refresh failed"
            ]
            return report

        reconcile_cmd = _reconcile_command(config)
        _payload, proc = _run_json(reconcile_cmd, config.repo_root, runner)
        reconcile_phase = _phase_result("reconcile_outbox", reconcile_cmd, proc)
        report["phases"].append(reconcile_phase)
        if proc.returncode != 0:
            report["status"] = "reconcile_failed"
            report["blockers"] = [
                reconcile_phase.get("stderr") or reconcile_phase.get("stdout") or "reconcile failed"
            ]
            return report

        merge_phase = _run_merge_phase(config, runner)
        report["phases"].append(merge_phase)
        if merge_phase.get("ok") is False:
            report["status"] = "merge_rejected"
            report["blockers"] = [
                str((merge_phase.get("skipped") or [{}])[-1].get("error") or "merge rejected")
            ]
            return report

        if config.branch_limit > 0:
            branch_cmd = _branch_publish_command(config)
            _payload, proc = _run_json(branch_cmd, config.repo_root, runner)
            report["phases"].append(_phase_result("publish_branch_prs", branch_cmd, proc))
        else:
            report["phases"].append(
                {
                    "name": "publish_branch_prs",
                    "ok": True,
                    "skipped": [{"reason": "branch_limit=0"}],
                }
            )

        issue_blocker = issue_publish_blocker(cache_payload, max_open_issues=config.max_open_issues)
        if config.issue_limit <= 0:
            report["phases"].append(
                {
                    "name": "publish_handoff_issues",
                    "ok": True,
                    "skipped": [{"reason": "issue_limit=0"}],
                }
            )
        elif issue_blocker is not None:
            report["phases"].append(
                {
                    "name": "publish_handoff_issues",
                    "ok": True,
                    "skipped": [{"reason": issue_blocker}],
                }
            )
        else:
            issue_cmd = _issue_publish_command(config)
            _payload, proc = _run_json(issue_cmd, config.repo_root, runner)
            report["phases"].append(_phase_result("publish_handoff_issues", issue_cmd, proc))

        final_cache_cmd = _cache_command(config, output=cache_output)
        _payload, proc = _run_json(final_cache_cmd, config.repo_root, runner)
        report["phases"].append(_phase_result("cache_refresh_after", final_cache_cmd, proc))

    report["status"] = "ok"
    report["blockers"] = []
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drain authenticated Codex automation value using bounded safe gates.",
        allow_abbrev=False,
    )
    parser.add_argument("--repo", default=".", help="Path inside the target repository")
    parser.add_argument("--github-repo", default=DEFAULT_GITHUB_REPO)
    parser.add_argument("--state-root", type=Path, default=None)
    parser.add_argument("--outbox-dir", type=Path, default=None)
    parser.add_argument("--receipt-dir", type=Path, default=None)
    parser.add_argument("--cache-output", type=Path, default=None)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--branch-limit", type=int, default=DEFAULT_BRANCH_LIMIT)
    parser.add_argument("--issue-limit", type=int, default=DEFAULT_ISSUE_LIMIT)
    parser.add_argument("--merge-limit", type=int, default=DEFAULT_MERGE_LIMIT)
    parser.add_argument("--max-open-prs", type=int, default=DEFAULT_MAX_OPEN_PRS)
    parser.add_argument("--max-open-issues", type=int, default=DEFAULT_MAX_OPEN_ISSUES)
    parser.add_argument("--branch-scan-limit", type=int, default=DEFAULT_BRANCH_SCAN_LIMIT)
    parser.add_argument("--json", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Run bounded write operations")
    mode.add_argument(
        "--dry-run",
        dest="apply",
        action="store_false",
        help="Plan without writing; this is the default",
    )
    parser.set_defaults(apply=False)
    return parser


def _config_from_args(args: argparse.Namespace) -> DrainConfig:
    repo_root = _repo_root(Path(args.repo).expanduser())
    state_root = _state_root(repo_root, args.state_root)
    return DrainConfig(
        repo_root=repo_root,
        github_repo=args.github_repo,
        state_root=state_root,
        outbox_dir=_resolve_state_path(
            state_root, args.outbox_dir, Path(".aragora/automation-outbox")
        ),
        receipt_dir=_resolve_state_path(
            state_root, args.receipt_dir, Path(".aragora/automation-receipts")
        ),
        cache_output=args.cache_output,
        base=args.base,
        branch_limit=max(args.branch_limit, 0),
        issue_limit=max(args.issue_limit, 0),
        merge_limit=max(args.merge_limit, 0),
        max_open_prs=max(args.max_open_prs, 0),
        max_open_issues=max(args.max_open_issues, 0),
        branch_scan_limit=max(args.branch_scan_limit, 0),
        apply=bool(args.apply),
    )


def _print_human(report: Mapping[str, Any]) -> None:
    print(f"status: {report.get('status')}")
    blockers = report.get("blockers") or []
    if blockers:
        print("blockers:")
        for blocker in blockers:
            print(f"- {blocker}")
    for phase in report.get("phases") or []:
        if isinstance(phase, Mapping):
            print(f"{phase.get('name')}: {'ok' if phase.get('ok', True) else 'blocked'}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = _config_from_args(args)
    report = run_drain(config)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0 if report.get("status") in {"ok", "github_unavailable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
