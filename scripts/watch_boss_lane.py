#!/usr/bin/env python3
"""Read-only watcher for the live boss lane and bridge health."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import agent_bridge_sessions  # type: ignore[import-not-found]
except ModuleNotFoundError:
    _scripts_dir = str(Path(__file__).resolve().parent)
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)
    import agent_bridge_sessions  # type: ignore[import-not-found]

DEFAULT_REPO = "synaptent/aragora"
DEFAULT_QUEUE_LIMIT = 6
DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_STALE_MINUTES = 30
DEFAULT_WATCH_SESSIONS = ("codex-strategic", "codex-session-state")
DEFAULT_WATCH_PRS = (5345, 5347, 5350, 5342, 5339)
FAILURE_CONCLUSIONS = {
    "ACTION_REQUIRED",
    "CANCELLED",
    "FAILURE",
    "STALE",
    "STARTUP_FAILURE",
    "TIMED_OUT",
}
NON_FAILURE_CONCLUSIONS = {"", "NEUTRAL", "SKIPPED", "SUCCESS"}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _canonical_repo_root() -> Path:
    return agent_bridge_sessions.resolve_canonical_repo_root(Path(__file__).resolve().parents[1])


def _default_jsonl_log(repo_root: Path) -> Path:
    return repo_root / ".aragora" / "overnight" / "boss_lane_watch.jsonl"


def _default_state_file(repo_root: Path) -> Path:
    return repo_root / ".aragora" / "overnight" / "boss_lane_watch_state.json"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _run_json(args: list[str], *, timeout: int = 30) -> Any:
    proc = subprocess.run(
        args,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(stderr or f"command failed: {' '.join(args)}")
    text = proc.stdout.strip() or "[]"
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON from {' '.join(args)}: {exc}") from exc


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bridge_snapshot(repo_root: Path, watched_sessions: list[str]) -> dict[str, Any]:
    records = agent_bridge_sessions.collect_sessions(
        repo_root=repo_root,
        tmux_dir=Path.home() / ".aragora" / "tmux-sessions",
        claude_projects_root=Path.home() / ".claude" / "projects",
        source="tmux",
        limit=500,
    )
    by_name = {record.name: record for record in records}
    result: dict[str, Any] = {}
    for name in watched_sessions:
        record = by_name.get(name)
        if record is None:
            result[name] = {
                "status": "missing",
                "branch": "-",
                "summary": "",
                "worktree": None,
                "updated_at": None,
            }
            continue
        result[name] = {
            "status": record.status,
            "branch": record.branch or "-",
            "summary": record.summary or "",
            "worktree": record.cwd,
            "updated_at": record.updated_at,
        }
    return result


def _queue_snapshot(repo: str, queue_limit: int) -> dict[str, Any]:
    gh = subprocess.run(
        ["which", "gh"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if gh.returncode != 0:
        raise RuntimeError("gh not found")
    payload = _run_json(
        [
            gh.stdout.strip(),
            "issue",
            "list",
            "--repo",
            repo,
            "--label",
            "boss-ready",
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,title,url,state",
        ],
        timeout=30,
    )
    if not isinstance(payload, list):
        raise RuntimeError("boss-ready issue list returned a non-list payload")
    front = [
        {
            "number": item.get("number"),
            "title": item.get("title"),
            "url": item.get("url"),
        }
        for item in payload[: max(1, queue_limit)]
        if isinstance(item, dict)
    ]
    return {
        "count": len(payload),
        "front": front,
        "front_numbers": [item["number"] for item in front if item.get("number") is not None],
    }


def _normalize_check_name(check: dict[str, Any]) -> str:
    name = str(check.get("name") or check.get("context") or "unknown").strip()
    workflow = str(check.get("workflowName") or "").strip()
    if workflow and workflow != name:
        return f"{workflow} / {name}"
    return name


def _failed_or_pending_checks(
    checks: list[dict[str, Any]], *, pr_state: str
) -> tuple[list[str], list[str]]:
    if pr_state != "OPEN":
        return [], []

    failed: list[str] = []
    pending: list[str] = []
    for check in checks:
        status = str(check.get("status") or "").upper()
        conclusion = str(check.get("conclusion") or "").upper()
        name = _normalize_check_name(check)
        if status != "COMPLETED":
            pending.append(name)
            continue
        if conclusion in NON_FAILURE_CONCLUSIONS:
            continue
        if conclusion in FAILURE_CONCLUSIONS:
            failed.append(name)
    return sorted(set(failed)), sorted(set(pending))


def _pr_snapshot(repo: str, pr_number: int) -> dict[str, Any]:
    payload = _run_json(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "number,title,state,isDraft,mergeable,reviewDecision,url,headRefName,statusCheckRollup",
        ],
        timeout=45,
    )
    if not isinstance(payload, dict):
        raise RuntimeError(f"PR #{pr_number} view returned a non-object payload")

    checks_raw = payload.get("statusCheckRollup") or []
    checks = [item for item in checks_raw if isinstance(item, dict)]
    failed, pending = _failed_or_pending_checks(checks, pr_state=str(payload.get("state") or ""))
    return {
        "number": payload.get("number"),
        "title": payload.get("title"),
        "state": payload.get("state"),
        "isDraft": bool(payload.get("isDraft")),
        "mergeable": payload.get("mergeable"),
        "reviewDecision": payload.get("reviewDecision"),
        "url": payload.get("url"),
        "headRefName": payload.get("headRefName"),
        "failed_checks": failed,
        "failed_count": len(failed),
        "pending_checks": pending,
        "pending_count": len(pending),
    }


def _issue_pr_search(repo: str, issue_number: int) -> dict[str, Any]:
    payload = _run_json(
        [
            "gh",
            "search",
            "prs",
            f"#{issue_number}",
            "--repo",
            repo,
            "--match",
            "title,body,comments",
            "--json",
            "number,title,url,state,isDraft",
        ],
        timeout=45,
    )
    if not isinstance(payload, list):
        raise RuntimeError(f"PR search for issue #{issue_number} returned a non-list payload")
    prs = [
        {
            "number": item.get("number"),
            "title": item.get("title"),
            "url": item.get("url"),
            "state": item.get("state"),
            "isDraft": bool(item.get("isDraft")),
        }
        for item in payload
        if isinstance(item, dict)
    ]
    return {
        "issue_number": issue_number,
        "prs": prs,
        "pr_numbers": [item["number"] for item in prs if item.get("number") is not None],
    }


def _boss_metrics_snapshot(metrics_path: Path, stale_minutes: int) -> dict[str, Any]:
    if not metrics_path.exists():
        return {
            "path": str(metrics_path),
            "exists": False,
            "updated_at": None,
            "age_minutes": None,
            "stale": True,
            "last_iteration": None,
            "last_issue_number": None,
            "last_terminal_class": None,
            "last_worker_status": None,
            "last_publish_action": None,
        }

    now = _utc_now().timestamp()
    updated_at = datetime.fromtimestamp(metrics_path.stat().st_mtime, UTC)
    age_minutes = round((now - metrics_path.stat().st_mtime) / 60.0, 1)
    last_row: dict[str, Any] | None = None
    for raw in reversed(metrics_path.read_text(encoding="utf-8", errors="replace").splitlines()):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            last_row = payload
            break

    return {
        "path": str(metrics_path),
        "exists": True,
        "updated_at": updated_at.isoformat(),
        "age_minutes": age_minutes,
        "stale": age_minutes > stale_minutes,
        "last_iteration": _safe_int((last_row or {}).get("iteration")),
        "last_issue_number": _safe_int((last_row or {}).get("issue_number")),
        "last_terminal_class": (last_row or {}).get("terminal_class"),
        "last_worker_status": (last_row or {}).get("worker_status"),
        "last_publish_action": (last_row or {}).get("publish_action"),
    }


def _error_snapshot(message: str) -> dict[str, Any]:
    return {"_error": message}


def collect_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    snapshot: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "repo_root": str(repo_root),
        "repo": args.repo,
    }
    try:
        snapshot["bridge_sessions"] = _bridge_snapshot(repo_root, args.watch_session)
    except Exception as exc:
        snapshot["bridge_sessions"] = _error_snapshot(str(exc))

    try:
        snapshot["queue"] = _queue_snapshot(args.repo, args.queue_limit)
    except Exception as exc:
        snapshot["queue"] = _error_snapshot(str(exc))

    metrics_path = repo_root / ".aragora" / "overnight" / "boss_metrics.jsonl"
    snapshot["boss_metrics"] = _boss_metrics_snapshot(metrics_path, args.stale_minutes)

    prs: dict[str, Any] = {}
    for pr_number in args.watch_pr:
        try:
            prs[str(pr_number)] = _pr_snapshot(args.repo, pr_number)
        except Exception as exc:
            prs[str(pr_number)] = _error_snapshot(str(exc))
    snapshot["prs"] = prs

    try:
        snapshot["issue_pr_search"] = _issue_pr_search(args.repo, args.pr_search_issue)
    except Exception as exc:
        snapshot["issue_pr_search"] = _error_snapshot(str(exc))
    return snapshot


def _load_previous_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _save_state(path: Path, snapshot: dict[str, Any]) -> None:
    _ensure_parent(path)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _append_jsonl(path: Path, snapshot: dict[str, Any]) -> None:
    _ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, sort_keys=True) + "\n")


def _dict_field(snapshot: dict[str, Any], key: str) -> dict[str, Any]:
    value = snapshot.get(key)
    return value if isinstance(value, dict) else {}


def _compare_states(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    if previous is None:
        return []

    alerts: list[str] = []

    prev_sessions = _dict_field(previous, "bridge_sessions")
    cur_sessions = _dict_field(current, "bridge_sessions")
    for name, session in cur_sessions.items():
        if not isinstance(session, dict) or name.startswith("_"):
            continue
        prev_session = prev_sessions.get(name) if isinstance(prev_sessions, dict) else {}
        if not isinstance(prev_session, dict):
            prev_session = {}
        if prev_session.get("status") != session.get("status") or prev_session.get(
            "branch"
        ) != session.get("branch"):
            alerts.append(
                f"bridge session {name}: status {prev_session.get('status', 'missing')} -> {session.get('status')} ; "
                f"branch {prev_session.get('branch', '-')} -> {session.get('branch', '-')}"
            )

    prev_queue = _dict_field(previous, "queue")
    cur_queue = _dict_field(current, "queue")
    if prev_queue.get("front_numbers") != cur_queue.get("front_numbers"):
        alerts.append(
            f"boss-ready front changed: {prev_queue.get('front_numbers', [])} -> {cur_queue.get('front_numbers', [])}"
        )
    if prev_queue.get("count") != cur_queue.get("count"):
        alerts.append(
            f"boss-ready count changed: {prev_queue.get('count')} -> {cur_queue.get('count')}"
        )

    prev_metrics = _dict_field(previous, "boss_metrics")
    cur_metrics = _dict_field(current, "boss_metrics")
    if prev_metrics.get("stale") != cur_metrics.get("stale"):
        alerts.append(
            f"boss metrics stale flipped: {prev_metrics.get('stale')} -> {cur_metrics.get('stale')} "
            f"(age={cur_metrics.get('age_minutes')}m)"
        )

    prev_prs = _dict_field(previous, "prs")
    cur_prs = _dict_field(current, "prs")
    for pr_number, pr in cur_prs.items():
        if not isinstance(pr, dict):
            continue
        prev_pr = prev_prs.get(pr_number) if isinstance(prev_prs, dict) else {}
        if not isinstance(prev_pr, dict):
            prev_pr = {}
        if prev_pr.get("state") != pr.get("state") or prev_pr.get("isDraft") != pr.get("isDraft"):
            alerts.append(
                f"PR #{pr_number} state changed: {prev_pr.get('state', 'missing')} -> {pr.get('state')} "
                f"(draft {prev_pr.get('isDraft')} -> {pr.get('isDraft')})"
            )
        prev_failed = prev_pr.get("failed_checks") or []
        cur_failed = pr.get("failed_checks") or []
        if prev_failed != cur_failed:
            if cur_failed:
                alerts.append(f"PR #{pr_number} failing checks: {', '.join(cur_failed)}")
            elif prev_failed:
                alerts.append(f"PR #{pr_number} failing checks cleared")

    prev_search = _dict_field(previous, "issue_pr_search")
    cur_search = _dict_field(current, "issue_pr_search")
    if prev_search.get("pr_numbers") != cur_search.get("pr_numbers"):
        alerts.append(
            f"issue #{cur_search.get('issue_number')} PR matches changed: "
            f"{prev_search.get('pr_numbers', [])} -> {cur_search.get('pr_numbers', [])}"
        )

    return alerts


def _print_snapshot(snapshot: dict[str, Any], alerts: list[str], *, baseline: bool) -> None:
    queue = snapshot.get("queue", {})
    metrics = snapshot.get("boss_metrics", {})
    bridge = snapshot.get("bridge_sessions", {})
    issue_search = snapshot.get("issue_pr_search", {})
    print(
        f"[{snapshot.get('generated_at')}] "
        f"queue_front={queue.get('front_numbers', [])} "
        f"queue_count={queue.get('count', '?')} "
        f"boss_metrics_age={metrics.get('age_minutes', '?')}m "
        f"stale={metrics.get('stale')} "
        f"last_issue={metrics.get('last_issue_number')} "
        f"last_iteration={metrics.get('last_iteration')}"
    )
    if baseline:
        for name, session in bridge.items():
            if not isinstance(session, dict):
                continue
            print(
                f"  bridge {name}: status={session.get('status')} "
                f"branch={session.get('branch', '-')} summary={session.get('summary', '')}"
            )
        for pr_number, pr in (snapshot.get("prs", {}) or {}).items():
            if not isinstance(pr, dict):
                continue
            print(
                f"  pr #{pr_number}: state={pr.get('state')} draft={pr.get('isDraft')} "
                f"failed={pr.get('failed_count', 0)} pending={pr.get('pending_count', 0)}"
            )
        print(
            f"  issue #{issue_search.get('issue_number')} PR matches: "
            f"{issue_search.get('pr_numbers', [])}"
        )
    for alert in alerts:
        print(f"  ALERT {alert}")
    print("", flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only watcher for the live boss lane.")
    repo_root = _canonical_repo_root()
    parser.add_argument(
        "--repo-root", default=str(repo_root), help="Canonical repo root to monitor"
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo in owner/name form")
    parser.add_argument(
        "--watch-session",
        action="append",
        default=list(DEFAULT_WATCH_SESSIONS),
        help="Bridge session name to watch (repeatable)",
    )
    parser.add_argument(
        "--watch-pr",
        action="append",
        type=int,
        default=list(DEFAULT_WATCH_PRS),
        help="PR number to watch (repeatable)",
    )
    parser.add_argument(
        "--pr-search-issue",
        type=int,
        default=5320,
        help="Issue number to search for matching PRs",
    )
    parser.add_argument("--queue-limit", type=int, default=DEFAULT_QUEUE_LIMIT)
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--stale-minutes", type=int, default=DEFAULT_STALE_MINUTES)
    parser.add_argument("--once", action="store_true", help="Collect one snapshot and exit")
    parser.add_argument(
        "--jsonl-log",
        default=str(_default_jsonl_log(repo_root)),
        help="JSONL snapshot log path",
    )
    parser.add_argument(
        "--state-file",
        default=str(_default_state_file(repo_root)),
        help="State file used for change detection",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    jsonl_log = Path(args.jsonl_log).expanduser()
    state_file = Path(args.state_file).expanduser()

    while True:
        previous = _load_previous_state(state_file)
        snapshot = collect_snapshot(args)
        alerts = _compare_states(previous, snapshot)
        _append_jsonl(jsonl_log, snapshot)
        _save_state(state_file, snapshot)
        _print_snapshot(snapshot, alerts, baseline=previous is None)
        if args.once:
            return 0
        time.sleep(max(1, int(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
