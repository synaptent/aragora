#!/usr/bin/env python3
"""Build a concise owner-aware next prompt from live Aragora coordination state."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_RELATIVE_PATH = Path(".aragora") / "agent-bridge" / "lanes.json"
DEFAULT_AUTOMATION_OUTBOX_DIR = Path(".aragora") / "automation-outbox"
DEFAULT_BACKPRESSURE_SIGNAL_FILE = Path(".aragora") / "backpressure.json"
ACTIVE_STATUSES = {
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
SENSITIVE_KEYS = {
    "messages",
    "prompt",
    "raw_prompt",
    "raw_transcript",
    "transcript_file",
    "transcript_path",
}
CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
CONVERGENCE_SENTENCE = (
    "If the prompt above accomplishes no incremental progress make the next prompt one "
    "that does, include this sentence in all subsequent prompts to ensure they converge "
    "towards prompts that make incremental progress."
)
PENDING_CHECK_STATES = {
    "ACTION_REQUIRED",
    "EXPECTED",
    "IN_PROGRESS",
    "PENDING",
    "QUEUED",
    "REQUESTED",
    "WAITING",
}
MERGE_READY_PROMPT_MERGE_STATE_STATUSES = {"CLEAN"}
POST_MERGE_LANE_KEYWORDS = ("evidence", "review", "quorum", "settle", "settlement")
UNRESOLVED_OPERATOR_CHOICE_MARKERS = (
    "1|2|3",
    "option <",
    "I explicitly choose option <",
    "<let lane",
    "<terminate",
    "<supersede",
)
BACKPRESSURE_GENERATE_MODE = "generate"
BACKPRESSURE_SHEPHERD_MODES = {
    "hold",
    "pause",
    "shepherd",
    "stop",
    "saturated",
    "pivot",
    "missing",
    "malformed",
}


def _read_lanes(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _find_lane(
    lanes: list[dict[str, Any]],
    *,
    lane_id: str | None = None,
    pr: int | None = None,
    branch: str | None = None,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for row in lanes:
        if lane_id and str(row.get("lane_id") or "") == lane_id:
            candidates.append(row)
        elif pr is not None and row.get("pr_number") == pr:
            candidates.append(row)
        elif branch and str(row.get("branch") or "") == branch:
            candidates.append(row)
    if not candidates:
        return None
    active = [row for row in candidates if str(row.get("status") or "") in ACTIVE_STATUSES]
    return active[0] if active else candidates[0]


def _sanitize(value: Any) -> Any:
    """Drop transcript/prompt-bearing fields from live-truth packets."""

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                continue
            out[str(key)] = _sanitize(item)
        return out
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=DEFAULT_REPO_ROOT, capture_output=True, text=True, timeout=120
    )


def _repo_runner(repo_root: Path) -> CommandRunner:
    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, cwd=repo_root, capture_output=True, text=True, timeout=120)

    return run


def _json_or_empty(result: subprocess.CompletedProcess[str]) -> Any:
    text = (result.stdout or "").strip()
    if text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            if result.returncode == 0:
                return {"raw": text}
        else:
            if result.returncode != 0:
                if not isinstance(payload, dict):
                    return {
                        "error": result.stderr.strip()
                        or f"command failed with return code {result.returncode}",
                        "returncode": result.returncode,
                        "payload": payload,
                    }
                payload = dict(payload)
                # Overwrite (not setdefault): a child that exits nonzero must not
                # mask the failure via a stale "returncode": 0 in its own stdout.
                payload["returncode"] = result.returncode
                if not payload.get("error"):
                    payload["error"] = result.stderr.strip() or (
                        f"command failed with return code {result.returncode}"
                    )
            return payload
    if result.returncode != 0:
        return {"error": result.stderr.strip(), "returncode": result.returncode}
    return {}


def _run_json(command: list[str], command_runner: CommandRunner) -> Any:
    try:
        result = command_runner(command)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": str(exc)}
    return _sanitize(_json_or_empty(result))


def _run_text(command: list[str], command_runner: CommandRunner) -> dict[str, Any]:
    try:
        result = command_runner(command)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"stdout": "", "stderr": str(exc), "returncode": 127}
    return {
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
        "returncode": result.returncode,
    }


def _mute_stdout_after_broken_pipe() -> None:
    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull_fd, sys.stdout.fileno())
        finally:
            os.close(devnull_fd)
    except Exception:
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            pass


def _emit_stdout(text: str) -> bool:
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except BrokenPipeError:
        _mute_stdout_after_broken_pipe()
        return False
    return True


def _has_unresolved_operator_choice_placeholder(prompt: str) -> bool:
    normalized = prompt.lower()
    return any(marker.lower() in normalized for marker in UNRESOLVED_OPERATOR_CHOICE_MARKERS)


def _operator_choice_placeholder_guard_prompt(
    prompt: str,
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
) -> str:
    """Fail closed when a generated prompt still contains operator-choice placeholders."""

    if not _has_unresolved_operator_choice_placeholder(prompt):
        return prompt
    return "\n".join(
        [
            f"Start from live repo truth in {repo_root}. Do not trust prior transcript state.",
            "",
            "Goal: stop because the generated next prompt still contains an unresolved operator-choice placeholder.",
            "",
            "Do not continue lane work from a prompt containing placeholders such as 1|2|3 or angle-bracketed operator actions.",
            "Rebuild the prompt with one explicit operator action sentence before any evidence, ready, rerun, merge, or lane-retirement work.",
            "",
            "Required operator action format:",
            "I explicitly choose option 1: let the active lane finish.",
            "I explicitly choose option 2: terminate/retire the active lane and resume at the current live head.",
            "I explicitly choose option 3: supersede the active lane and authorize this session to continue at the exact live head.",
            "",
            "Final report: exact placeholder detected, action withheld, and the corrected explicit operator-action prompt.",
            CONVERGENCE_SENTENCE,
            "",
        ]
    )


def _load_backpressure_signal(signal_file: Path) -> dict[str, Any]:
    """Read the optional backlog/backpressure signal for writer-loop prompts."""

    if not signal_file.exists():
        return {
            "available": False,
            "mode": "missing",
            "reasons": [f"signal_file_missing:{signal_file}"],
            "annotations": [],
            "source": str(signal_file),
        }
    try:
        payload = json.loads(signal_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "available": False,
            "mode": "malformed",
            "reasons": [f"signal_file_unreadable:{str(exc)[:200]}"],
            "annotations": [],
            "source": str(signal_file),
        }
    if not isinstance(payload, dict):
        return {
            "available": False,
            "mode": "malformed",
            "reasons": ["signal_payload_not_object"],
            "annotations": [],
            "source": str(signal_file),
        }
    payload = _sanitize(payload)
    assert isinstance(payload, dict)
    payload.setdefault("available", True)
    payload.setdefault("source", str(signal_file))
    return payload


def _backpressure_mode(signal: dict[str, Any]) -> str:
    return str(signal.get("mode") or "missing").strip().lower()


def build_product_proof_loop_prompt(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    signal_file: Path | None = None,
) -> str:
    """Build a recursive prompt that consults the backlog signal before new PR work."""

    if signal_file is None:
        signal_file = repo_root / DEFAULT_BACKPRESSURE_SIGNAL_FILE
    signal = _load_backpressure_signal(signal_file)
    mode = _backpressure_mode(signal)
    reasons = signal.get("reasons")
    reason_summary = (
        ", ".join(str(reason) for reason in reasons)
        if isinstance(reasons, list) and reasons
        else "none"
    )
    annotations = signal.get("annotations")
    annotation_summary = (
        ", ".join(str(annotation) for annotation in annotations)
        if isinstance(annotations, list) and annotations
        else "none"
    )
    thresholds = signal.get("thresholds") if isinstance(signal.get("thresholds"), dict) else {}
    threshold_summary = json.dumps(thresholds, sort_keys=True) if thresholds else "unknown"
    open_prs = signal.get("open_prs", "unknown")
    drafts = signal.get("drafts", "unknown")
    ready = signal.get("ready", "unknown")
    outbox_depth = signal.get("outbox_depth", "unknown")
    generated_at = signal.get("generated_at") or "unknown"

    gate_summary = (
        f"mode={mode}, open_prs={open_prs}, drafts={drafts}, ready={ready}, "
        f"outbox_depth={outbox_depth}, thresholds={threshold_summary}, "
        f"generated_at={generated_at}, reasons={reason_summary}, "
        f"annotations={annotation_summary}"
    )
    signal_command = (
        "python3 scripts/backlog_gate.py --quiet || true"
        if signal_file == repo_root / DEFAULT_BACKPRESSURE_SIGNAL_FILE
        else f"python3 scripts/backlog_gate.py --signal-file {shlex.quote(str(signal_file))} --quiet || true"
    )

    lines = [
        f"Start from live repo truth in {repo_root}. Do not trust prior transcript state.",
        "Keep the shared root observation-only if dirty. Use a fresh disposable worktree from current origin/main for any code work.",
        "",
        "Goal: reduce product-proof / benchmark-truth opportunity cost by consulting the backlog backpressure signal before minting another micro-guard PR.",
        "",
        "First refresh and verify the backpressure signal:",
        "git fetch origin --prune",
        signal_command,
        f"cat {shlex.quote(str(signal_file))}",
        "",
        "Signal snapshot to verify, not trust:",
        gate_summary,
        "",
        "Re-check open draft/ready PRs, active owners, and duplicate newer PRs before choosing any action.",
    ]

    if mode == BACKPRESSURE_GENERATE_MODE:
        lines.extend(
            [
                "",
                "If the refreshed signal still says mode=generate, find exactly one new non-duplicate Tier 0-2 measurable gap in product-proof or benchmark-truth reporting, prefer non-mutating benchmark/report helpers, patch only that narrow surface, add focused tests, validate with ${ARAGORA_PYTHON:-python3}, run bash scripts/automation_pr_preflight.sh origin/main HEAD, push a draft PR with codex and codex-automation labels, and verify required checks.",
                "Stop before semantic/security/API changes, settlement/merge/protection workflows, queue authority, or any branch/PR with an active owner.",
            ]
        )
    elif mode in BACKPRESSURE_SHEPHERD_MODES:
        lines.extend(
            [
                "",
                f"If the refreshed signal still says mode={mode}, do not create a new branch, commit, or PR.",
                "Instead, shepherd existing work: select the highest-value existing unowned green Tier 0-2 product-proof / benchmark-truth PR for evidence/readiness/merge-throughput handling, or report that no safe unowned target exists.",
                "Do not merge, mark ready, post evidence, rerun workflows, write receipts, or touch queue authority without a separate exact-head authorization prompt.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                f"The refreshed signal mode is unrecognized ({mode}). Treat it fail-closed: do not create a new branch, commit, or PR.",
                "Report the exact signal payload and produce a repair prompt for the signal producer or prompt router.",
            ]
        )

    lines.extend(
        [
            "",
            "If blocked, report the exact blocker and produce the next recursive prompt.",
            "Final report: signal mode, duplicate/owner findings, action taken or withheld, validation if any, PR URL if any, and the next best recursive prompt.",
            CONVERGENCE_SENTENCE,
            "If any of the work involved can be better automated and made more autonomous by improving Aragora tooling at a meta level create a plan to do that instead, include this sentence in all subsequent prompts to ensure they converge towards automating and making more autonomous all steps at a meta level where this makes sense for the repo and project.",
            "Always include a final summary or report section with the best next recursive prompt in a form similar to this one, include this sentence in all subsequent prompts to ensure they converge towards prompts that produce their next best recursive prompt.",
            "",
        ]
    )
    return "\n".join(lines)


def _tmux_pane_packet(command_runner: CommandRunner) -> dict[str, Any]:
    """Return a compact tmux pane inventory for active-lane coordination."""

    result = _run_text(
        [
            "tmux",
            "list-panes",
            "-a",
            "-F",
            "#{session_name}\t#{window_name}\t#{pane_index}\t#{pane_pid}\t#{pane_current_path}\t#{pane_current_command}",
        ],
        command_runner,
    )
    panes: list[dict[str, Any]] = []
    if result["returncode"] != 0:
        return {
            "available": False,
            "returncode": result["returncode"],
            "stderr": result["stderr"].strip(),
            "panes": panes,
        }
    for raw_line in result["stdout"].splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 6:
            session_name, window_name, pane_index, pane_pid, current_path, command = parts
            panes.append(
                {
                    "tmux_target": f"{session_name}:{window_name}",
                    "session_name": session_name,
                    "window_name": window_name,
                    "pane_index": pane_index,
                    "pane_pid": pane_pid,
                    "current_path": current_path,
                    "command": command,
                }
            )
        else:
            panes.append({"raw": raw_line})
    return {
        "available": True,
        "returncode": 0,
        "stderr": "",
        "panes": panes,
    }


def _root_packet(command_runner: CommandRunner) -> dict[str, Any]:
    status = _run_text(
        ["git", "status", "--short", "--branch", "--untracked-files=all"],
        command_runner,
    )
    lines = [line for line in status["stdout"].splitlines() if line.strip()]
    dirty = any(not line.startswith("##") for line in lines)
    return {"dirty": dirty, "status": lines, "returncode": status["returncode"]}


def _worktree_entries(repo_root: Path, command_runner: CommandRunner) -> list[dict[str, Any]]:
    """Return registered git worktrees from ``git worktree list --porcelain``."""

    result = _run_text(["git", "worktree", "list", "--porcelain"], command_runner)
    if result["returncode"] != 0:
        raise RuntimeError(result["stderr"].strip() or "git worktree list failed")

    entries: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in result["stdout"].splitlines():
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            if current:
                entries.append(current)
            current = {"path": value}
        elif key == "HEAD":
            current["listed_head"] = value
        elif key == "branch":
            current["branch"] = value
        elif key == "detached":
            current["detached"] = True
        elif key == "bare":
            current["bare"] = True
    if current:
        entries.append(current)

    if not entries:
        return [{"path": str(repo_root)}]
    return entries


def _worktree_clean_origin_main_status(
    path: Path,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    """Classify whether ``path`` is clean and exactly at local ``origin/main``."""

    summary: dict[str, Any] = {
        "path": str(path),
        "status": "missing",
        "head": None,
        "origin_main": None,
        "status_lines": [],
        "dirty_paths": [],
    }
    if not path.exists():
        return summary

    status = _run_text(
        ["git", "-C", str(path), "status", "--short", "--branch", "--untracked-files=all"],
        command_runner,
    )
    if status["returncode"] != 0:
        summary.update(
            {
                "status": "git_error",
                "error": status["stderr"].strip() or "git status failed",
                "returncode": status["returncode"],
            }
        )
        return summary

    lines = [line for line in status["stdout"].splitlines() if line.strip()]
    dirty_paths = [line[3:].strip() for line in lines if not line.startswith("##")]
    summary["status_lines"] = lines
    summary["dirty_paths"] = dirty_paths

    revs = _run_text(["git", "-C", str(path), "rev-parse", "HEAD", "origin/main"], command_runner)
    rev_lines = [line.strip() for line in revs["stdout"].splitlines() if line.strip()]
    if revs["returncode"] == 0 and len(rev_lines) >= 2:
        summary["head"] = rev_lines[0]
        summary["origin_main"] = rev_lines[1]

    if dirty_paths:
        summary["status"] = "dirty"
        return summary

    if revs["returncode"] != 0 or len(rev_lines) < 2:
        summary.update(
            {
                "status": "git_error",
                "error": revs["stderr"].strip() or "git rev-parse HEAD origin/main failed",
                "returncode": revs["returncode"],
            }
        )
        return summary

    summary["status"] = (
        "usable_clean_origin_main"
        if summary["head"] == summary["origin_main"]
        else "stale_vs_origin_main"
    )
    return summary


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _clean_checkout_prompt(
    pr: int | None,
    expected_head: str | None,
    repo_root: Path,
) -> str:
    pr_fragment = f"PR #{pr}" if pr is not None else "the live queue"
    worktree_name = f"aragora-pr{pr}-triage" if pr is not None else "aragora-queue-triage"
    worktree_path = f"/private/tmp/{worktree_name}"
    mailbox = (
        f"python3 scripts/read_operator_steering.py --pr {pr} --no-receipt --json || true"
        if pr is not None
        else "python3 scripts/agent_bridge.py operator-snapshot --json --summary-only || true"
    )
    head_guard = (
        f"Stop if {pr_fragment} head drifted from {expected_head}."
        if expected_head and pr is not None
        else "Stop if the target head drifts from the operator-specified exact head."
    )
    return "\n".join(
        [
            f"Start from live repo truth in {repo_root}. Do not trust prior transcript state.",
            "Do not use or mutate dirty root source files. Do not merge/admin-merge without separate explicit operator authorization.",
            "",
            f"Goal: continue {pr_fragment} from a trusted clean current origin/main checkout.",
            "",
            "First create a disposable detached triage worktree because no registered clean origin/main checkout is available:",
            "git fetch origin main",
            f"git worktree add --detach {worktree_path} origin/main",
            "",
            f"Run all repo-native helpers from {worktree_path} only.",
            "",
            "Before lane work, check operator-steering mailbox:",
            mailbox,
            "",
            "Re-check clean checkout truth:",
            f"git -C {worktree_path} status --short --branch --untracked-files=all",
            f"git -C {worktree_path} rev-parse HEAD origin/main",
            "",
            head_guard,
            "If the clean checkout is not exactly at origin/main or becomes dirty, stop and report the blocker.",
            "If live gates are stable, continue only within the original bounded queue prompt. Do not mutate unrelated PRs.",
            CONVERGENCE_SENTENCE,
        ]
    )


def _selected_clean_checkout_prompt(
    selected_path: str,
    *,
    pr: int | None,
    expected_head: str | None,
) -> str:
    pr_fragment = f"PR #{pr}" if pr is not None else "the live queue"
    head_guard = (
        f"Stop if {pr_fragment} head drifted from {expected_head}."
        if expected_head and pr is not None
        else "Stop if the target head drifts from the operator-specified exact head."
    )
    return "\n".join(
        [
            "Before using the selected clean checkout, refresh remote truth and revalidate it:",
            f"git -C {selected_path} fetch origin main",
            f"git -C {selected_path} status --short --branch --untracked-files=all",
            f"git -C {selected_path} rev-parse HEAD origin/main",
            "",
            (
                "Use the selected checkout for repo-native helpers only if it remains clean "
                "and HEAD equals the refreshed origin/main after fetch."
            ),
            "If it is dirty or stale after fetch, do not use it; create a disposable detached triage worktree from origin/main instead.",
            head_guard,
        ]
    )


def _clean_checkout_packet(
    repo_root: Path,
    command_runner: CommandRunner,
    *,
    pr: int | None = None,
    expected_head: str | None = None,
) -> dict[str, Any]:
    root_summary = _worktree_clean_origin_main_status(repo_root, command_runner)
    candidates: list[dict[str, Any]] = [{**root_summary, "role": "root"}]
    if root_summary["status"] == "usable_clean_origin_main":
        return {
            "status": "root_usable",
            "selected_path": str(repo_root),
            "candidates": candidates,
            "recommended_prompt": None,
        }

    try:
        entries = _worktree_entries(repo_root, command_runner)
    except RuntimeError as exc:
        return {
            "status": "error",
            "selected_path": None,
            "candidates": candidates,
            "recommended_prompt": _clean_checkout_prompt(pr, expected_head, repo_root),
            "error": str(exc),
        }

    selected_path: str | None = None
    for entry in entries:
        entry_path = Path(str(entry.get("path") or ""))
        if not entry_path or _same_path(entry_path, repo_root):
            continue
        summary = _worktree_clean_origin_main_status(entry_path, command_runner)
        summary.update(
            {
                "role": "worktree",
                "branch": entry.get("branch"),
                "detached": bool(entry.get("detached")),
                "listed_head": entry.get("listed_head"),
            }
        )
        candidates.append(summary)
        if selected_path is None and summary["status"] == "usable_clean_origin_main":
            selected_path = str(entry_path)

    if selected_path is not None:
        return {
            "status": "selected",
            "selected_path": selected_path,
            "candidates": candidates,
            "recommended_prompt": _selected_clean_checkout_prompt(
                selected_path,
                pr=pr,
                expected_head=expected_head,
            ),
        }

    return {
        "status": "needs_disposable_worktree",
        "selected_path": None,
        "candidates": candidates,
        "recommended_prompt": _clean_checkout_prompt(pr, expected_head, repo_root),
    }


def _clean_checkout_uses_disposable_prompt(clean_checkout: dict[str, Any]) -> bool:
    return clean_checkout.get("status") in {
        "needs_disposable_worktree",
        "error",
    } and bool(clean_checkout.get("recommended_prompt"))


def _state_dir(state_root: Path) -> Path:
    expanded = state_root.expanduser()
    return expanded if expanded.name == ".aragora" else expanded / ".aragora"


def _has_automation_outbox(state_root: Path) -> bool:
    return (_state_dir(state_root) / "automation-outbox").is_dir()


def _automation_state_root(repo_root: Path) -> Path:
    """Return the checkout or direct .aragora dir backing shared automation state."""

    if _has_automation_outbox(repo_root):
        return repo_root

    configured = os.environ.get("ARAGORA_AUTOMATION_STATE_ROOT")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(Path.home() / "Development" / "aragora")

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if _has_automation_outbox(resolved):
            return resolved
    return repo_root


def _automation_state_default_path(state_root: Path, default_relative: Path) -> Path:
    expanded = state_root.expanduser()
    if default_relative.parts[:1] == (".aragora",) and expanded.name == ".aragora":
        return expanded.joinpath(*default_relative.parts[1:])
    return expanded / default_relative


def _count_files(path: Path) -> tuple[int | None, int]:
    if not path.is_dir():
        return None, 1
    try:
        return sum(1 for item in path.rglob("*") if item.is_file()), 0
    except OSError:
        return None, 1


def _existing_df_target(path: Path) -> Path:
    expanded = path.expanduser()
    for candidate in (expanded, *expanded.parents):
        if candidate.exists():
            return candidate
    return Path(".")


def _disk_outbox_packet(
    command_runner: CommandRunner, repo_root: Path = DEFAULT_REPO_ROOT
) -> dict[str, Any]:
    outbox_dir = _automation_state_default_path(
        _automation_state_root(repo_root), DEFAULT_AUTOMATION_OUTBOX_DIR
    )
    df = _run_text(["df", "-h", str(_existing_df_target(outbox_dir))], command_runner)
    outbox_file_count, outbox_returncode = _count_files(outbox_dir)
    return {
        "df": df["stdout"].splitlines(),
        "outbox_dir": str(outbox_dir),
        "outbox_file_count": outbox_file_count,
        "outbox_returncode": outbox_returncode,
    }


def _active_owner_map(lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lane in lanes:
        if str(lane.get("status") or "") not in ACTIVE_STATUSES:
            continue
        rows.append(
            _sanitize(
                {
                    "lane_id": lane.get("lane_id"),
                    "owner_session": lane.get("owner_session"),
                    "status": lane.get("status"),
                    "branch": lane.get("branch"),
                    "worktree": lane.get("worktree"),
                    "pr_number": lane.get("pr_number"),
                    "next_action": lane.get("next_action"),
                }
            )
        )
    return rows


def _active_target_lanes(
    lanes: list[dict[str, Any]],
    *,
    lane: dict[str, Any] | None,
    lane_id: str | None = None,
    pr: int | None = None,
    branch: str | None = None,
) -> list[dict[str, Any]]:
    """Return active lanes that appear to own the selected PR/branch/worktree."""

    keys: list[tuple[str, Any]] = []
    if lane_id:
        keys.append(("lane_id", lane_id))
    if pr is not None:
        keys.append(("pr_number", pr))
    if branch:
        keys.append(("branch", branch))
    if lane:
        for key in ("pr_number", "branch", "worktree"):
            value = lane.get(key)
            if value not in (None, ""):
                keys.append((key, value))

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in lanes:
        if str(row.get("status") or "") not in ACTIVE_STATUSES:
            continue
        if not any(row.get(key) == value for key, value in keys):
            continue
        row_key = str(row.get("lane_id") or id(row))
        if row_key in seen:
            continue
        seen.add(row_key)
        rows.append(
            _sanitize(
                {
                    "lane_id": row.get("lane_id"),
                    "owner_session": row.get("owner_session"),
                    "status": row.get("status"),
                    "branch": row.get("branch"),
                    "worktree": row.get("worktree"),
                    "pr_number": row.get("pr_number"),
                    "next_action": row.get("next_action"),
                }
            )
        )
    return rows


def _owner_lookup_packet(
    *,
    registry_path: Path,
    repo_root: Path,
    lane_id: str | None,
    pr: int | None,
    branch: str | None,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    """Run the repo-supported owner lookup for the selected target."""

    selector: list[str]
    if lane_id:
        selector = ["--lane-id", lane_id]
    elif pr is not None:
        selector = ["--pr", str(pr)]
    elif branch:
        selector = ["--branch", branch]
    else:
        return {}
    return _run_json(
        [
            "python3",
            "scripts/identify_lane_owner.py",
            *selector,
            "--json",
            "--registry-path",
            str(registry_path),
            "--steering-inbox-root",
            str(repo_root / ".aragora" / "operator-steering"),
        ],
        command_runner,
    )


def _is_stale_mailbox_only_owner(owner_state: Any) -> bool:
    if not isinstance(owner_state, dict):
        return False
    if str(owner_state.get("owner_blocking_state") or "") == "stale_terminal_owner":
        return False
    if str(owner_state.get("status") or "") not in ACTIVE_STATUSES:
        return False
    live_process = owner_state.get("live_process")
    live_process_found = (
        isinstance(live_process, dict) and str(live_process.get("found")).lower() == "true"
    )
    if live_process_found:
        return False
    harness_confidence = str(owner_state.get("harness_confidence") or "").lower()
    mailbox_only = "mailbox_only" in harness_confidence
    no_live_prompt = owner_state.get("live_prompt_dispatchable") is False
    unread = int(owner_state.get("unread_message_count") or 0)
    pending = int(owner_state.get("pending_message_count") or 0)
    never_checked_mailbox = not str(owner_state.get("last_mailbox_check_at") or "").strip()
    return bool(
        mailbox_only and no_live_prompt and (unread > 0 or pending > 0 or never_checked_mailbox)
    )


def _contains_target_token(text: str, *, pr: int | None, branch: str | None) -> bool:
    lowered = text.lower()
    if pr is not None and str(pr) in lowered:
        return True
    return bool(branch and branch.lower() in lowered)


def _active_session_matches_target(text: str, *, pr: int | None, branch: str | None) -> bool:
    if not _contains_target_token(text, pr=pr, branch=branch):
        return False
    lowered = text.lower()
    if branch and branch.lower() in lowered:
        return True
    return any(keyword in lowered for keyword in POST_MERGE_LANE_KEYWORDS)


def _post_merge_lane_matches(packet: dict[str, Any], *, pr: int | None) -> list[dict[str, Any]]:
    """Return active lane/session rows for a PR that has already merged."""

    pr_packet = packet.get("pr") if isinstance(packet.get("pr"), dict) else {}
    branch = str(pr_packet.get("headRefName") or "")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for lane in packet.get("target_active_lanes") or []:
        if not isinstance(lane, dict):
            continue
        key = f"lane:{lane.get('lane_id') or lane.get('owner_session') or id(lane)}"
        if key in seen:
            continue
        seen.add(key)
        rows.append({"source": "agent_bridge_lane", **_sanitize(lane)})

    tmux_panes = packet.get("tmux_panes") if isinstance(packet.get("tmux_panes"), dict) else {}
    for pane in tmux_panes.get("panes") or []:
        if not isinstance(pane, dict):
            continue
        text = json.dumps(_sanitize(pane), sort_keys=True)
        if not _active_session_matches_target(text, pr=pr, branch=branch):
            continue
        key = f"tmux:{pane.get('tmux_target') or pane.get('raw') or id(pane)}"
        if key in seen:
            continue
        seen.add(key)
        rows.append({"source": "tmux_pane", **_sanitize(pane)})

    active_sessions = (
        packet.get("active_sessions") if isinstance(packet.get("active_sessions"), dict) else {}
    )
    for collection_name in (
        "agent_bridge_lanes",
        "codex_cli_sessions",
        "process_census",
        "overlap_report",
    ):
        collection = active_sessions.get(collection_name)
        if not collection:
            continue
        items = collection if isinstance(collection, list) else [collection]
        for item in items:
            if not isinstance(item, dict):
                continue
            text = json.dumps(_sanitize(item), sort_keys=True)
            if not _active_session_matches_target(text, pr=pr, branch=branch):
                continue
            key = f"active:{collection_name}:{item.get('lane_id') or item.get('owner_session') or item.get('tmux_target') or id(item)}"
            if key in seen:
                continue
            seen.add(key)
            rows.append({"source": collection_name, **_sanitize(item)})

    return rows


def _merge_packet_entry(merge_packet: Any, pr: int | None) -> dict[str, Any]:
    if not isinstance(merge_packet, dict):
        return {}
    entries = merge_packet.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and pr is not None and entry.get("pr_number") == pr:
                return entry
        return {}
    return merge_packet


def _packet_not_ready(merge_packet: Any) -> list[Any]:
    if not isinstance(merge_packet, dict):
        return []
    not_ready = merge_packet.get("not_ready")
    return not_ready if isinstance(not_ready, list) else []


def _packet_not_ready_prs(merge_packet: Any) -> set[int]:
    prs: set[int] = set()
    for raw in _packet_not_ready(merge_packet):
        try:
            prs.add(int(raw))
        except (TypeError, ValueError):
            continue
    return prs


def _packet_authorizes(merge_packet: Any, *, pr: int | None) -> bool:
    entry = _merge_packet_entry(merge_packet, pr)
    if not entry.get("admin_squash_allowed"):
        return False
    not_ready = _packet_not_ready_prs(merge_packet)
    return not not_ready or (pr is not None and pr not in not_ready)


def _prompt_one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _packet_admin_squash_order(merge_packet: Any) -> list[int]:
    if not isinstance(merge_packet, dict):
        return []
    order: list[int] = []
    for raw in merge_packet.get("admin_squash_order") or []:
        try:
            order.append(int(raw))
        except (TypeError, ValueError):
            continue
    return order


def _select_merge_ready_entry(merge_packet: Any, *, pr: int | None = None) -> dict[str, Any]:
    if not isinstance(merge_packet, dict):
        return {}
    target_pr = pr
    if target_pr is None:
        order = _packet_admin_squash_order(merge_packet)
        target_pr = order[0] if order else None
    return _merge_packet_entry(merge_packet, target_pr)


def _selected_merge_ready_pr_number(merge_packet: Any, *, pr: int | None = None) -> int | None:
    entry = _select_merge_ready_entry(merge_packet, pr=pr)
    try:
        return int(entry.get("pr_number"))
    except (AttributeError, TypeError, ValueError):
        return None


def _live_pr_metadata_blocker(
    live_pr: Any,
    *,
    pr_number: int,
    expected_head: str,
) -> str:
    if live_pr is None:
        return f"live PR metadata for PR #{pr_number} is missing"
    if not isinstance(live_pr, dict) or not live_pr:
        return f"live PR metadata for PR #{pr_number} is missing or malformed"
    if live_pr.get("error"):
        return f"live PR metadata for PR #{pr_number} is unavailable: {live_pr.get('error')}"
    try:
        live_number = int(live_pr.get("number"))
    except (TypeError, ValueError):
        return f"live PR metadata for PR #{pr_number} is missing a parseable number"
    if live_number != pr_number:
        return f"live PR metadata number {live_number} does not match requested PR #{pr_number}"
    state = str(live_pr.get("state") or "").upper()
    if state != "OPEN":
        return f"PR #{pr_number} is not open in live metadata: state={state or 'unknown'}"
    if bool(live_pr.get("isDraft")):
        return f"PR #{pr_number} is draft in live metadata"
    live_head = str(live_pr.get("headRefOid") or "")
    if not live_head:
        return f"live PR metadata for PR #{pr_number} is missing an exact head"
    if live_head != expected_head:
        return (
            f"live PR head {live_head} does not match merge-packet head {expected_head} "
            f"for PR #{pr_number}"
        )
    mergeable = str(live_pr.get("mergeable") or "").upper()
    merge_state = str(live_pr.get("mergeStateStatus") or "").upper()
    if mergeable != "MERGEABLE" or merge_state not in MERGE_READY_PROMPT_MERGE_STATE_STATUSES:
        return (
            f"PR #{pr_number} is not settlement-stable in live metadata: "
            f"mergeable={mergeable or 'unknown'}, mergeStateStatus={merge_state or 'unknown'}"
        )
    return ""


def _merge_ready_prompt_blocker(merge_packet: Any, *, pr: int | None = None) -> str:
    if not isinstance(merge_packet, dict) or not merge_packet:
        return "merge-packet is missing or malformed"
    if merge_packet.get("transport_blocked") or merge_packet.get("status") == "transport_blocked":
        kind = _prompt_one_line(merge_packet.get("error_kind")) or "unknown transport"
        detail = _prompt_one_line(merge_packet.get("error")) or "live GitHub transport unavailable"
        preserve = "; preserve_no_mutate=true" if merge_packet.get("preserve_no_mutate") else ""
        return f"merge-packet transport blocked ({kind}): {detail}{preserve}"
    if merge_packet.get("error"):
        detail = _prompt_one_line(merge_packet.get("error")) or "command failed without details"
        return f"merge-packet is unavailable: {detail}"
    if "returncode" in merge_packet:
        try:
            returncode = int(merge_packet["returncode"])
        except (TypeError, ValueError):
            return "merge-packet has an invalid command return code"
        if returncode != 0:
            return f"merge-packet command failed with return code {returncode}"
    entry = _select_merge_ready_entry(merge_packet, pr=pr)
    if not entry:
        target = f"PR #{pr}" if pr is not None else "admin_squash_order"
        return f"merge-packet has no ready entry for {target}"
    try:
        pr_number = int(entry.get("pr_number"))
    except (TypeError, ValueError):
        return "merge-packet ready entry is missing a parseable pr_number"
    if pr_number in _packet_not_ready_prs(merge_packet):
        return f"merge-packet still lists PR #{pr_number} as not_ready"
    if not str(entry.get("head_sha") or entry.get("headRefOid") or ""):
        return f"merge-packet ready entry for PR #{pr_number} is missing an exact head"
    if not entry.get("admin_squash_allowed"):
        return f"merge-packet does not allow admin squash for PR #{pr_number}"
    if entry.get("requires_human_risk_settlement") or entry.get("requires_human_preapproval"):
        return f"PR #{pr_number} still requires human risk/preapproval settlement"
    try:
        tier = int(entry.get("tier"))
    except (TypeError, ValueError):
        return f"merge-packet ready entry for PR #{pr_number} is missing a parseable tier"
    if tier >= 3:
        return f"PR #{pr_number} is Tier {tier}, not an autonomous merge-ready prompt target"
    live_blocker = _live_pr_metadata_blocker(
        merge_packet.get("live_pr"),
        pr_number=pr_number,
        expected_head=str(entry.get("head_sha") or entry.get("headRefOid") or ""),
    )
    if live_blocker:
        return live_blocker
    return ""


def _packet_authorization_reason(merge_packet: Any, *, pr: int | None) -> str | None:
    if not isinstance(merge_packet, dict) or not merge_packet:
        return "merge-packet authorization is missing or malformed"
    entry = _merge_packet_entry(merge_packet, pr)
    if not entry:
        target = f"PR #{pr}" if pr is not None else "target PR"
        return f"merge-packet has no entry for {target}"
    if not entry.get("admin_squash_allowed"):
        return "merge-packet does not authorize admin squash"
    not_ready = _packet_not_ready(merge_packet)
    if pr is not None and pr in not_ready:
        return f"merge-packet still lists PR #{pr} as not_ready"
    if pr is None and not_ready:
        return "merge-packet still has not_ready entries"
    return None


def _pending_required_checks(checks: Any) -> list[dict[str, str]]:
    if not isinstance(checks, list):
        return []
    pending: list[dict[str, str]] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        bucket = str(check.get("bucket") or "").lower()
        state = str(check.get("state") or "").upper()
        if bucket == "pending" or state in PENDING_CHECK_STATES:
            pending.append(
                {
                    "name": str(check.get("name") or ""),
                    "workflow": str(check.get("workflow") or ""),
                    "state": str(check.get("state") or ""),
                    "bucket": str(check.get("bucket") or ""),
                }
            )
    return pending


def build_post_merge_lane_coordination_prompt(
    packet: dict[str, Any],
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    pr: int | None = None,
) -> str | None:
    """Build a stop-first prompt when a merged PR still has an active target lane."""

    pr_packet = packet.get("pr") if isinstance(packet.get("pr"), dict) else {}
    if str(pr_packet.get("state") or "").upper() != "MERGED":
        return None
    active_matches = _post_merge_lane_matches(packet, pr=pr)
    if not active_matches:
        return None

    target = f"#{pr}" if pr is not None else "the target PR"
    head = str(pr_packet.get("headRefOid") or "unknown")
    merge_commit = pr_packet.get("mergeCommit")
    merge_commit_oid = ""
    if isinstance(merge_commit, dict):
        merge_commit_oid = str(merge_commit.get("oid") or "")
    merged_at = str(pr_packet.get("mergedAt") or "unknown")
    lane_lines = []
    for row in active_matches:
        if row.get("source") == "tmux_pane":
            label = row.get("tmux_target") or row.get("window_name") or row.get("raw")
            cwd = row.get("current_path") or ""
            lane_lines.append(f"- tmux {label} cwd={cwd}".rstrip())
        else:
            label = row.get("lane_id") or row.get("owner_session") or row.get("source")
            lane_lines.append(f"- {row.get('source')}: {label}")
    lane_summary = "\n".join(lane_lines) or "- active target lane detected"

    return "\n".join(
        [
            f"Start from live repo truth in {repo_root}. Do not trust prior transcript state.",
            "Do not duplicate active lanes. Do not touch unrelated PRs. Do not merge without separate explicit operator authorization. Do not use or mutate dirty root source files.",
            "",
            f"Goal: coordinate stale active lane(s) after PR {target} already merged.",
            f"Live merged PR state to verify, not trust: head={head}, merge_commit={merge_commit_oid or 'unknown'}, merged_at={merged_at}.",
            "",
            "Active target lane(s) detected:",
            lane_summary,
            "",
            "First re-check tmux active sessions and gh pr view for the PR. If any listed target lane is still active and no explicit operator action is present, stop and repeat these choices:",
            "1. Let the active lane finish naturally, then re-ground queue selection from a clean current origin/main checkout.",
            "2. Explicitly terminate/retire the active lane, then re-ground queue selection from a clean current origin/main checkout.",
            "3. Explicitly supersede the lane only for post-merge cleanup/receipt inspection; do not collect evidence, rerun checks, mark statuses, or merge.",
            "",
            "If the active lane is gone, explicitly retired, or explicitly superseded, use a clean current origin/main checkout only. Re-check git status, agent health, active sessions, work robot, and open PR list before selecting the next highest-ranked unowned non-draft PR that is not policy-excluded.",
            "Before any new lane work, check mailbox, owner state, gh pr view/checks, full checks, merge-packet, and settle_one_pr.py.",
            "",
            "Final report: merged PR state, active-lane coordination result, action taken or withheld, and a fresh recursive best-next prompt that starts with mailbox checking.",
            CONVERGENCE_SENTENCE,
            "",
        ]
    )


def build_stale_owner_steering_prompt(
    packet: dict[str, Any],
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    pr: int | None = None,
    branch: str | None = None,
) -> str | None:
    """Build a concrete steering prompt for stale mailbox-only owner lanes."""

    owner_state = packet.get("owner_state")
    if not _is_stale_mailbox_only_owner(owner_state):
        return None
    assert isinstance(owner_state, dict)
    owner_session = str(owner_state.get("owner_session") or "")
    lane_id = str(owner_state.get("lane_id") or "")
    if not owner_session or not lane_id:
        return None

    target = f"PR #{pr}" if pr is not None else branch or "the target branch"
    owner_branch = str(owner_state.get("branch") or branch or "")
    heartbeat = str(owner_state.get("last_heartbeat_at") or "unknown")
    pending_count = int(owner_state.get("pending_message_count") or 0)
    unread_count = int(owner_state.get("unread_message_count") or 0)
    receipt_count = int(owner_state.get("read_receipt_count") or 0)
    body = (
        f"Please finish or explicitly retire lane {lane_id} for {target}. "
        "The lane is mailbox-only/stale: no live process is dispatchable, "
        f"last heartbeat is {heartbeat}, pending_message_count={pending_count}, "
        f"unread_message_count={unread_count}, read_receipt_count={receipt_count}. "
        "Do not leave the target blocked by stale ownership; write an outcome receipt "
        "or update the lane status to completed, released, or superseded."
    )
    steering_command = " ".join(
        [
            "python3",
            "scripts/send_operator_steering.py",
            "--to",
            shlex.quote(owner_session),
            "--lane-id",
            shlex.quote(lane_id),
            "--priority",
            "blocking",
            "--body",
            shlex.quote(body),
        ]
    )

    return "\n".join(
        [
            f"Start from live repo truth in {repo_root}. Do not trust prior transcript state.",
            "Do not duplicate active lanes. Do not touch unrelated PRs. Do not merge without separate explicit operator authorization. Do not use or mutate dirty root source files.",
            "",
            f"Goal: steer stale mailbox-only owner lane for {target}; do not supersede it from this session.",
            "",
            "Live owner state to verify, not trust:",
            f"- lane_id: {lane_id}",
            f"- owner_session: {owner_session}",
            f"- status: {owner_state.get('status') or 'unknown'}",
            f"- branch: {owner_branch or 'unknown'}",
            f"- last_heartbeat_at: {heartbeat}",
            f"- pending_message_count: {pending_count}",
            f"- unread_message_count: {unread_count}",
            f"- read_receipt_count: {receipt_count}",
            "",
            "First re-check mailbox and owner state from a clean current origin/main checkout. If the lane still resolves stale/mailbox-only and no explicit retirement/supersession authority is present, send this exact steering command and stop:",
            steering_command,
            "",
            "If the lane has retired or no longer owns the target, re-ground the target from live gh state before doing any further work.",
            "Final report: mailbox receipt state, owner status, steering command run or withheld, and the next recursive prompt.",
            CONVERGENCE_SENTENCE,
            "",
        ]
    )


def build_post_merge_fast_packet(
    *,
    registry_path: Path,
    repo_root: Path = DEFAULT_REPO_ROOT,
    pr: int,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Build the cheapest packet needed to route merged PR stale-lane prompts."""

    runner = command_runner or _repo_runner(repo_root)
    pr_packet = _run_json(
        [
            "gh",
            "pr",
            "view",
            str(pr),
            "--json",
            "number,state,headRefOid,headRefName,url,mergedAt,mergeCommit",
        ],
        runner,
    )
    pr_packet = pr_packet if isinstance(pr_packet, dict) else {}
    lanes = _read_lanes(registry_path)
    branch = str(pr_packet.get("headRefName") or "")
    target_active_lanes = _active_target_lanes(
        lanes,
        lane=_find_lane(lanes, pr=pr, branch=branch),
        pr=pr,
        branch=branch or None,
    )
    packet: dict[str, Any] = {
        "pr": pr_packet,
        "target_active_lanes": target_active_lanes,
        "active_sessions": {},
        "tmux_panes": _tmux_pane_packet(runner),
        "post_merge_lane_coordination": {},
        "blockers": [],
        "selected_action": "continue_standard_prompt",
    }
    active_post_merge_lanes = _post_merge_lane_matches(packet, pr=pr)
    post_merge_detected = str(pr_packet.get("state") or "").upper() == "MERGED" and bool(
        active_post_merge_lanes
    )
    packet["post_merge_lane_coordination"] = {
        "detected": post_merge_detected,
        "active_lanes": active_post_merge_lanes,
    }
    if post_merge_detected:
        packet["blockers"].append("merged PR still has active target lane")
        packet["selected_action"] = "post_merge_lane_retirement_coordination"
    return packet


def build_merge_ready_packet(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    pr: int | None = None,
    limit: int = 30,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Read a live merge-packet for exact-head merge prompt generation."""

    runner = command_runner or _repo_runner(repo_root)
    command = [
        "python3",
        "-m",
        "aragora.cli.main",
        "review-queue",
        "merge-packet",
    ]
    if pr is not None:
        command.extend(["--pr", str(pr)])
    else:
        command.extend(["--limit", str(limit)])
    command.append("--json")
    packet = _run_json(command, runner)
    if not isinstance(packet, dict):
        return {"error": "merge-packet did not return an object"}
    pr_number = _selected_merge_ready_pr_number(packet, pr=pr)
    if pr_number is not None:
        packet = dict(packet)
        packet["live_pr"] = _run_json(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--json",
                "number,state,isDraft,headRefOid,mergeable,mergeStateStatus,url",
            ],
            runner,
        )
    return packet


def build_merge_ready_prompt(
    merge_packet: dict[str, Any],
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    pr: int | None = None,
) -> str:
    """Build a human-copyable exact-head prompt for one ready Tier 0-2 PR."""

    blocker = _merge_ready_prompt_blocker(merge_packet, pr=pr)
    entry = _select_merge_ready_entry(merge_packet, pr=pr)
    if blocker:
        return "\n".join(
            [
                f"Start from live repo truth in {repo_root}. Do not trust prior transcript state.",
                "",
                "Goal: stop because no safe merge-ready authorization prompt can be generated from the live merge-packet.",
                f"Blocker: {blocker}.",
                "",
                "Re-check root status, open PR list, and review-queue merge-packet. Do not merge, mark-ready, set statuses, rerun checks, or broaden queue scope from this prompt.",
                "Final report: exact blocker, packet summary, and the next single bounded target.",
                CONVERGENCE_SENTENCE,
                "",
            ]
        )

    pr_number = int(entry["pr_number"])
    head = str(entry.get("head_sha") or entry.get("headRefOid") or "")
    title = _prompt_one_line(entry.get("title"))
    tier = entry.get("tier")
    checks_summary = str(entry.get("checks_summary") or "unknown")
    return "\n".join(
        [
            f"Start from live repo truth in {repo_root}. Do not trust transcript state. Do not touch shared-root dirt.",
            "",
            f"Goal: merge exactly one queue-head PR if live gates still match: PR #{pr_number} at exact head {head}.",
            f"I authorize normal protected squash merge for PR #{pr_number} at exact head {head}.",
            "",
            f"Packet fact to verify, not trust: title={title or 'unknown'}, tier={tier}, checks={checks_summary}, verdict={entry.get('verdict') or 'unknown'}.",
            "",
            "First re-check:",
            "git status --short --branch --untracked-files=all",
            f"python3 scripts/read_operator_steering.py --pr {pr_number} --json --no-receipt || true",
            f"python3 scripts/identify_lane_owner.py --pr {pr_number} --json || true",
            f"gh pr view {pr_number} --json number,title,state,isDraft,headRefOid,mergeable,mergeStateStatus,url",
            f"gh pr checks {pr_number} --required",
            f"python3 -m aragora.cli.main review-queue merge-packet --pr {pr_number} --json",
            f"python3 scripts/settle_one_pr.py --pr {pr_number} --json",
            "",
            f"Proceed only if PR #{pr_number} remains open, non-draft, exact head {head}, MERGEABLE, required checks green, no active conflicting owner, merge-packet is satisfied/admin_squash_allowed, no Tier 3/Tier 4 settlement required, and settle_one has no blockers.",
            "",
            f"If safe, merge PR #{pr_number} by normal protected squash with --match-head-commit only. No admin merge, no bypass, no branch protection, no broad-drain, and do not touch unrelated PRs or shared-root dirt.",
            "",
            "After merge, verify state, mergedAt, mergeCommit, then re-run review-queue merge-packet --limit 30 --json and report the next single bounded target.",
            CONVERGENCE_SENTENCE,
            "",
        ]
    )


def build_settlement_guard(
    packet: dict[str, Any],
    *,
    pr: int | None = None,
    expected_head: str | None = None,
) -> dict[str, Any]:
    """Fail-closed settlement preflight for exact-head prompts."""

    pr_packet = packet.get("pr") if isinstance(packet.get("pr"), dict) else {}
    merge_packet = (
        packet.get("merge_packet") if isinstance(packet.get("merge_packet"), dict) else {}
    )
    entry = _merge_packet_entry(merge_packet, pr)
    live_head = str(pr_packet.get("headRefOid") or "") if isinstance(pr_packet, dict) else ""
    packet_head = str(entry.get("head_sha") or entry.get("headRefOid") or "")
    pending_checks = _pending_required_checks(packet.get("checks", {}).get("required"))
    target_lanes = packet.get("target_active_lanes")
    target_lanes = target_lanes if isinstance(target_lanes, list) else []
    reasons: list[str] = []
    authorization_reason = _packet_authorization_reason(merge_packet, pr=pr)

    if expected_head and live_head and expected_head != live_head:
        reasons.append(f"expected head {expected_head} does not match live head {live_head}")
    if authorization_reason:
        reasons.append(authorization_reason)
    if len(target_lanes) > 1:
        owners = ", ".join(
            str(row.get("owner_session") or row.get("lane_id")) for row in target_lanes
        )
        reasons.append(f"multiple active target owners: {owners}")
    if packet_head and live_head and packet_head != live_head:
        reasons.append(f"merge-packet head {packet_head} does not match live head {live_head}")
    if pending_checks and not authorization_reason:
        names = ", ".join(
            f"{check['workflow']} / {check['name']}".strip(" /") for check in pending_checks
        )
        reasons.append(f"merge-packet authorizes settlement while checks are pending: {names}")

    return {
        "allowed": not reasons,
        "verdict": "pass" if not reasons else "fail_closed",
        "reasons": reasons,
        "expected_head": expected_head,
        "live_head": live_head or None,
        "merge_packet_head": packet_head or None,
        "pending_checks": pending_checks,
        "target_active_lanes": target_lanes,
        "merge_packet_authorizes": _packet_authorizes(merge_packet, pr=pr),
    }


def build_decision_packet(
    *,
    registry_path: Path,
    repo_root: Path = DEFAULT_REPO_ROOT,
    lane_id: str | None = None,
    pr: int | None = None,
    branch: str | None = None,
    expected_head: str | None = None,
    command_runner: CommandRunner = _default_runner,
) -> dict[str, Any]:
    """Build machine-readable live-truth inputs for owner-aware prompts."""

    lanes = _read_lanes(registry_path)
    runner = _repo_runner(repo_root) if command_runner is _default_runner else command_runner
    lane = _find_lane(lanes, lane_id=lane_id, pr=pr, branch=branch)
    target_active_lanes = _active_target_lanes(
        lanes, lane=lane, lane_id=lane_id, pr=pr, branch=branch
    )
    blockers: list[str] = []
    root = _root_packet(runner)
    clean_checkout = _clean_checkout_packet(
        repo_root,
        runner,
        pr=pr,
        expected_head=expected_head,
    )
    owner_state = _owner_lookup_packet(
        registry_path=registry_path,
        repo_root=repo_root,
        lane_id=lane_id,
        pr=pr,
        branch=branch,
        command_runner=runner,
    )
    if root["dirty"]:
        blockers.append("dirty root")
    if lane and str(lane.get("status") or "") in ACTIVE_STATUSES:
        blockers.append("active owner exists for target")
    if len(target_active_lanes) > 1:
        blockers.append("multiple active owners exist for target")
    if _is_stale_mailbox_only_owner(owner_state):
        blockers.append("stale mailbox-only owner needs steering")

    packet: dict[str, Any] = {
        "owner": _sanitize(lane) if lane else None,
        "owner_state": _sanitize(owner_state),
        "target_active_lanes": target_active_lanes,
        "root": root,
        "clean_checkout": clean_checkout,
        "owner_map": _active_owner_map(lanes),
        "bridge_health": _run_json(
            ["python3", "scripts/agent_bridge.py", "--json", "health"],
            runner,
        ),
        "operator_snapshot": _run_json(
            ["python3", "scripts/agent_bridge.py", "operator-snapshot", "--json", "--summary-only"],
            runner,
        ),
        "active_sessions": _run_json(
            [
                "python3",
                "scripts/list_active_agent_sessions.py",
                "--json",
                "--codex-session-scan-limit",
                "120",
            ],
            runner,
        ),
        "tmux_panes": _tmux_pane_packet(runner),
        "disk_outbox": _disk_outbox_packet(runner, repo_root=repo_root),
        "pr": {},
        "checks": {"required": []},
        "merge_packet": {},
        "post_merge_lane_coordination": {},
        "blockers": blockers,
        "selected_action": "stale_owner_steering_prompt"
        if "stale mailbox-only owner needs steering" in blockers
        else "read_only_owner_routing"
        if "active owner exists for target" in blockers
        else "queue_prompt_from_clean_checkout"
        if root["dirty"] and clean_checkout.get("status") == "selected"
        else "create_clean_checkout_prompt"
        if root["dirty"] and _clean_checkout_uses_disposable_prompt(clean_checkout)
        else "repair_or_stop"
        if root["dirty"]
        else "queue_prompt",
    }

    if pr is not None:
        packet["pr"] = _run_json(
            [
                "gh",
                "pr",
                "view",
                str(pr),
                "--json",
                "number,state,isDraft,headRefOid,headRefName,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup,url,mergedAt,mergeCommit",
            ],
            runner,
        )
        checks = _run_json(
            [
                "gh",
                "pr",
                "checks",
                str(pr),
                "--required",
                "--json",
                "name,state,bucket,workflow,link",
            ],
            runner,
        )
        packet["checks"] = {"required": checks if isinstance(checks, list) else []}
        packet["merge_packet"] = _run_json(
            [
                "python3",
                "-m",
                "aragora.cli.main",
                "review-queue",
                "merge-packet",
                "--pr",
                str(pr),
                "--json",
            ],
            runner,
        )
    active_post_merge_lanes = _post_merge_lane_matches(packet, pr=pr)
    post_merge_detected = (
        isinstance(packet.get("pr"), dict)
        and str(packet["pr"].get("state") or "").upper() == "MERGED"
        and bool(active_post_merge_lanes)
    )
    packet["post_merge_lane_coordination"] = {
        "detected": post_merge_detected,
        "active_lanes": active_post_merge_lanes,
    }
    if post_merge_detected:
        packet["blockers"].append("merged PR still has active target lane")
        packet["selected_action"] = "post_merge_lane_retirement_coordination"
    packet["settlement_guard"] = build_settlement_guard(packet, pr=pr, expected_head=expected_head)
    return packet


def _mailbox_command(lane: dict[str, Any] | None, *, pr: int | None, branch: str | None) -> str:
    if lane and lane.get("lane_id"):
        return (
            "python3 scripts/read_operator_steering.py --lane-id "
            f"{shlex.quote(str(lane['lane_id']))} --json || true"
        )
    if pr is not None:
        return f"python3 scripts/read_operator_steering.py --pr {pr} --json || true"
    if branch:
        return (
            "python3 scripts/read_operator_steering.py --branch "
            f"{shlex.quote(branch)} --json || true"
        )
    return "python3 scripts/agent_bridge.py operator-snapshot --json --summary-only || true"


def _prompt_work_id(
    lane: dict[str, Any] | None, *, pr: int | None, branch: str | None
) -> str | None:
    if lane:
        raw = str(lane.get("work_id") or "").strip()
        if raw:
            return raw
        raw_pr = lane.get("pr_number")
        if raw_pr is not None:
            try:
                return f"pr:{int(raw_pr)}"
            except (TypeError, ValueError):
                pass
    if pr is not None:
        return f"pr:{pr}"
    if branch:
        return f"branch:{branch}"
    return None


def _branch_write_lease_preflight_lines(
    lane: dict[str, Any] | None, *, pr: int | None, branch: str | None
) -> list[str]:
    if not lane or str(lane.get("status") or "") not in ACTIVE_STATUSES:
        return []
    lease_branch = str(lane.get("branch") or branch or "").strip()
    owner_session = str(lane.get("owner_session") or "").strip()
    work_id = _prompt_work_id(lane, pr=pr, branch=lease_branch or branch)
    if not lease_branch or not work_id:
        return []
    session_arg = f" --session-id {shlex.quote(owner_session)}" if owner_session else ""
    command = (
        "python3 scripts/check_work_lease.py "
        f"{shlex.quote(lease_branch)} --verify-only --work-id {shlex.quote(work_id)} "
        f"--strict{session_arg} --json"
    )
    return [
        "",
        "Before any branch push when ARAGORA_REQUIRE_BRANCH_WRITE_LEASE=1, verify the dev_coordination branch-write lease:",
        command,
    ]


def build_prompt(
    *,
    registry_path: Path,
    repo_root: Path = DEFAULT_REPO_ROOT,
    lane_id: str | None = None,
    pr: int | None = None,
    branch: str | None = None,
    expected_head: str | None = None,
    command_runner: CommandRunner | None = None,
) -> str:
    lanes = _read_lanes(registry_path)
    lane = _find_lane(lanes, lane_id=lane_id, pr=pr, branch=branch)
    mailbox = _mailbox_command(lane, pr=pr, branch=branch)
    runner = command_runner or _repo_runner(repo_root)
    clean_checkout = _clean_checkout_packet(
        repo_root,
        runner,
        pr=pr,
        expected_head=expected_head,
    )
    target = (
        f"lane {lane_id}"
        if lane_id
        else f"PR #{pr}"
        if pr is not None
        else branch or "the live queue"
    )

    lines = [
        f"Start from live repo truth in {repo_root}. Do not trust prior transcript state.",
        "",
        "Before lane work, check your Aragora operator-steering mailbox:",
        mailbox,
        "If a steering message redirects or says stop, obey it before doing anything else. Do not delete, edit, move, or acknowledge mailbox files.",
        "",
        "Do not paste raw transcripts into this prompt or into follow-up prompts; rebuild live truth from Aragora tooling.",
        "",
        "Run read-only live truth first:",
        "git status --short --branch --untracked-files=all",
        "python3 scripts/agent_bridge.py health --json || true",
        "python3 scripts/agent_bridge.py operator-snapshot --json --summary-only || true",
        "python3 scripts/list_active_agent_sessions.py --json --codex-session-scan-limit 120",
    ]
    if clean_checkout.get("status") == "selected":
        selected_path = clean_checkout.get("selected_path")
        lines.extend(
            [
                "",
                "Clean-checkout routing: root is not suitable for repo-native helpers, but a registered clean origin/main checkout is available.",
                f"Run repo-native helpers only from this checkout: {selected_path}",
                clean_checkout.get("recommended_prompt") or "",
            ]
        )
    elif _clean_checkout_uses_disposable_prompt(clean_checkout):
        routing_reason = (
            "the registered clean-checkout scan failed"
            if clean_checkout.get("status") == "error"
            else "no registered clean origin/main checkout is available"
        )
        lines.extend(
            [
                "",
                f"Clean-checkout routing: {routing_reason}.",
                "Use this bounded prompt before running repo-native queue helpers:",
                clean_checkout.get("recommended_prompt") or "",
            ]
        )
    if pr is not None:
        lines.extend(
            [
                f"gh pr view {pr} --json number,state,isDraft,headRefOid,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup,url",
                f"python3 -m aragora.cli.main review-queue merge-packet --pr {pr} --json || true",
            ]
        )
    lines.extend(_branch_write_lease_preflight_lines(lane, pr=pr, branch=branch))

    lines.append("")
    if lane:
        owner_session = str(lane.get("owner_session") or "")
        status = str(lane.get("status") or "")
        lines.extend(
            [
                f"Goal: make incremental progress on {target} without duplicating active owners.",
                f"Continue only if you are owner_session {owner_session} for lane {lane.get('lane_id')}. If not, stop with NOT_OWNER and report the active owner.",
                f"Current registry status to verify, not trust: status={status}, branch={lane.get('branch') or ''}, pr={lane.get('pr_number') or ''}, next_action={lane.get('next_action') or ''}.",
                "If you are the owner, perform only the next_action after live gates pass. If the lane is blocked, produce the smallest concrete unblock prompt instead of widening scope.",
            ]
        )
    else:
        lines.extend(
            [
                f"Goal: identify one safe non-overlapping action for {target}.",
                "If you cannot map yourself to a lane, run read-only only.",
                "If an active owner appears for the target PR, branch, files, queue gate, disk cleanup, or steering work, do not mutate; report owner_session, lane_id, worktree, and exact next steering message.",
                "If no owner exists and live gates are clean, produce one bounded prompt for the highest-value unowned queue action. Do not start PR work in the same run.",
            ]
        )
    lines.extend(
        [
            "",
            "Final report: mailbox state, owner/session mapping, active/conflict lanes, target PR/head/checks if applicable, action taken or withheld, exact blocker, and a fresh recursive best-next prompt that starts with mailbox checking.",
            CONVERGENCE_SENTENCE,
        ]
    )
    return "\n".join(lines) + "\n"


def build_settlement_guard_prompt(
    packet: dict[str, Any],
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    pr: int | None = None,
    branch: str | None = None,
) -> str:
    guard = packet.get("settlement_guard")
    guard = guard if isinstance(guard, dict) else {}
    owner = packet.get("owner") if isinstance(packet.get("owner"), dict) else None
    owners = guard.get("target_active_lanes")
    owners = owners if isinstance(owners, list) else []
    active_owner = owners[0] if len(owners) == 1 and isinstance(owners[0], dict) else None
    mailbox = _mailbox_command(active_owner, pr=pr, branch=branch)
    owner_summary = (
        ", ".join(
            f"{row.get('lane_id')} / {row.get('owner_session')}"
            for row in owners
            if isinstance(row, dict)
        )
        or "none"
    )
    pending = guard.get("pending_checks")
    pending = pending if isinstance(pending, list) else []
    pending_summary = (
        ", ".join(
            f"{row.get('workflow')} / {row.get('name')}".strip(" /")
            for row in pending
            if isinstance(row, dict)
        )
        or "none"
    )
    reasons = guard.get("reasons")
    reasons = reasons if isinstance(reasons, list) else []
    reason_summary = "; ".join(str(reason) for reason in reasons) or "none"
    target = f"PR #{pr}" if pr is not None else branch or "the live queue"

    return "\n".join(
        [
            f"Start from live repo truth in {repo_root}. Do not trust prior transcript state.",
            "",
            "Before acting, check your Aragora operator-steering mailbox:",
            mailbox,
            "If a steering message redirects or says stop, obey it before doing anything else. Do not delete, edit, move, or acknowledge mailbox files.",
            "",
            f"Goal: settlement-guard {target} before any edit, push, comment, merge, mark-ready, cleanup, or workflow rerun.",
            f"Guard verdict to verify, not trust: {guard.get('verdict') or 'unknown'}.",
            f"Expected head: {guard.get('expected_head') or 'not supplied'}",
            f"Live head: {guard.get('live_head') or 'unknown'}",
            f"Merge-packet head: {guard.get('merge_packet_head') or 'unknown'}",
            f"Active target owners: {owner_summary}",
            f"Pending required checks: {pending_summary}",
            f"Fail-closed reasons: {reason_summary}",
            "",
            "Re-check git status, lanes, identify_lane_owner.py, gh pr view/checks, and merge-packet before mutating.",
            "If the guard still fails closed, do not mutate; report the exact blockers and produce the next bounded prompt.",
            "If the guard passes and merge-packet returns admin_squash_allowed=true and not_ready=[], exact-head settlement may proceed only within the prompt's PR/tier constraints.",
            CONVERGENCE_SENTENCE,
            "",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--lane-id")
    selector.add_argument("--pr", type=int)
    selector.add_argument("--branch")
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=DEFAULT_REPO_ROOT / REGISTRY_RELATIVE_PATH,
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="Repo root used in generated prompt text and default live-truth commands.",
    )
    parser.add_argument("--expected-head", help="Exact head SHA the prompt intends to handle.")
    parser.add_argument(
        "--settlement-guard",
        action="store_true",
        help="Emit a fail-closed settlement guard prompt populated from live truth.",
    )
    parser.add_argument(
        "--merge-ready-prompt",
        action="store_true",
        help="Emit a human-copyable exact-head prompt for one live merge-packet ready PR.",
    )
    parser.add_argument(
        "--product-proof-loop-prompt",
        action="store_true",
        help=(
            "Emit a product-proof / benchmark-truth loop prompt that consults the "
            "backpressure signal before creating new PR work."
        ),
    )
    parser.add_argument(
        "--backpressure-signal-file",
        type=Path,
        default=None,
        help=(
            "Backpressure signal JSON for --product-proof-loop-prompt "
            f"(default: {DEFAULT_BACKPRESSURE_SIGNAL_FILE})."
        ),
    )
    parser.add_argument(
        "--merge-ready-limit",
        type=int,
        default=30,
        help="Open queue limit used with --merge-ready-prompt when --pr is omitted.",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    prompt: str | None = None
    packet: dict[str, Any] | None = None
    guard_prompt: str | None = None
    if args.product_proof_loop_prompt:
        signal_file = args.backpressure_signal_file
        if signal_file is not None and not signal_file.is_absolute():
            signal_file = args.repo_root / signal_file
        prompt = build_product_proof_loop_prompt(
            repo_root=args.repo_root,
            signal_file=signal_file,
        )
        prompt = _operator_choice_placeholder_guard_prompt(prompt, repo_root=args.repo_root)
        if args.json:
            _emit_stdout(
                json.dumps(
                    {
                        "prompt": prompt,
                        "backpressure_signal": _load_backpressure_signal(
                            signal_file
                            if signal_file is not None
                            else args.repo_root / DEFAULT_BACKPRESSURE_SIGNAL_FILE
                        ),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
        else:
            _emit_stdout(prompt)
        return 0
    if args.merge_ready_prompt:
        merge_packet = build_merge_ready_packet(
            repo_root=args.repo_root,
            pr=args.pr,
            limit=args.merge_ready_limit,
        )
        prompt = build_merge_ready_prompt(merge_packet, repo_root=args.repo_root, pr=args.pr)
        prompt = _operator_choice_placeholder_guard_prompt(prompt, repo_root=args.repo_root)
        if args.json:
            _emit_stdout(
                json.dumps(
                    {
                        "prompt": prompt,
                        "merge_packet": merge_packet,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
        else:
            _emit_stdout(prompt)
        return 0
    if args.pr is not None:
        fast_packet = build_post_merge_fast_packet(
            registry_path=args.registry_path,
            repo_root=args.repo_root,
            pr=args.pr,
        )
        post_merge_prompt = build_post_merge_lane_coordination_prompt(
            fast_packet,
            repo_root=args.repo_root,
            pr=args.pr,
        )
        if post_merge_prompt:
            prompt = post_merge_prompt
            packet = fast_packet
    if (
        args.pr is not None
        or args.branch is not None
        or args.lane_id is not None
        or args.json
        or args.settlement_guard
    ):
        if packet is None:
            packet = build_decision_packet(
                registry_path=args.registry_path,
                repo_root=args.repo_root,
                lane_id=args.lane_id,
                pr=args.pr,
                branch=args.branch,
                expected_head=args.expected_head,
            )
            post_merge_prompt = build_post_merge_lane_coordination_prompt(
                packet,
                repo_root=args.repo_root,
                pr=args.pr,
            )
            if post_merge_prompt:
                prompt = post_merge_prompt
        if prompt is None and packet is not None:
            stale_owner_prompt = build_stale_owner_steering_prompt(
                packet,
                repo_root=args.repo_root,
                pr=args.pr,
                branch=args.branch,
            )
            if stale_owner_prompt:
                prompt = stale_owner_prompt
    if prompt is None:
        prompt = build_prompt(
            registry_path=args.registry_path,
            repo_root=args.repo_root,
            lane_id=args.lane_id,
            pr=args.pr,
            branch=args.branch,
            expected_head=args.expected_head,
        )
    prompt = _operator_choice_placeholder_guard_prompt(prompt, repo_root=args.repo_root)
    if args.json or args.settlement_guard:
        if packet is None:
            packet = build_decision_packet(
                registry_path=args.registry_path,
                repo_root=args.repo_root,
                lane_id=args.lane_id,
                pr=args.pr,
                branch=args.branch,
                expected_head=args.expected_head,
            )
        guard_prompt = build_settlement_guard_prompt(
            packet,
            repo_root=args.repo_root,
            pr=args.pr,
            branch=args.branch,
        )
    if args.json:
        _emit_stdout(
            json.dumps(
                {
                    "prompt": prompt,
                    "settlement_guard_prompt": guard_prompt,
                    "decision_packet": packet,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    elif args.settlement_guard:
        _emit_stdout(guard_prompt or "")
    else:
        _emit_stdout(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
