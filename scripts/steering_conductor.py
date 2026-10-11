#!/usr/bin/env python3
"""Run one bounded operator-steering conductor cycle.

The conductor chooses at most one live lane and writes at most one
operator-steering mailbox message.  It never mutates GitHub or PR branches.
Repeated runs are de-duplicated through a small JSON ledger, plus unread
mailbox detection for the target owner_session.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import send_operator_steering
import identify_lane_owner as owner_lookup

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER_PATH = Path.home() / ".aragora" / "steering_conductor_ledger.json"
LANE_REGISTRY_DEFAULT = owner_lookup.LANE_REGISTRY_DEFAULT
STEERING_INBOX_ROOT_DEFAULT = owner_lookup.STEERING_INBOX_ROOT_DEFAULT
USER_LANE_REGISTRY_DEFAULT = send_operator_steering.USER_LANE_REGISTRY_DEFAULT
DEFAULT_RECENT_TARGET_CYCLES = 3
DEFAULT_RECENT_TARGET_HOURS = 2.0
DEFAULT_MAX_LANE_AGE_MINUTES = 120.0
SCHEMA_VERSION = "aragora-steering-conductor-ledger/1.0"

ACTIVE_STATUSES = {
    "active",
    "running",
    "pending",
    "queued",
    "claimed",
    "working",
    "waiting_for_steering",
    "acknowledged",
}
TERMINAL_STATUSES = {
    "completed",
    "released",
    "superseded",
    "expired",
    "dead",
    "stale",
}
RESOLVED_STEERING_OUTCOMES = {
    "obeyed",
    "held",
    "stale",
    "superseded",
    "blocked",
    "completed",
}
EXCLUDED_PR_NUMBERS = {8456}
EXCLUDED_BRANCH_PREFIXES = ("claude/fusion-",)
HIGH_LEVERAGE_TERMS = (
    "duplicate",
    "collision",
    "head drift",
    "drift",
    "breaker",
    "treadmill",
    "owner",
    "human-gated",
    "tier 3",
    "tier 4",
    "stop",
    "blocked",
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class Candidate:
    record: dict[str, Any]
    target_key: str
    owner_session: str
    score: tuple[int, float, str]
    reason: str


@dataclass(frozen=True)
class CycleConfig:
    repo_root: Path = REPO_ROOT
    ledger_path: Path = DEFAULT_LEDGER_PATH
    lane_registry_path: Path = LANE_REGISTRY_DEFAULT
    steering_inbox_root: Path = STEERING_INBOX_ROOT_DEFAULT
    recent_target_cycles: int = DEFAULT_RECENT_TARGET_CYCLES
    recent_target_hours: float = DEFAULT_RECENT_TARGET_HOURS
    max_lane_age_minutes: float = DEFAULT_MAX_LANE_AGE_MINUTES
    dry_run: bool = False
    skip_fetch: bool = False


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def _iso(ts: dt.datetime) -> str:
    return ts.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    command_runner: CommandRunner = subprocess.run,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    return command_runner(
        list(command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _run_json(
    command: Sequence[str],
    *,
    cwd: Path,
    command_runner: CommandRunner = subprocess.run,
    timeout: int = 30,
) -> dict[str, Any] | list[Any] | None:
    proc = _run(command, cwd=cwd, command_runner=command_runner, timeout=timeout)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        return None


def _load_json_file(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_ledger(path: Path) -> dict[str, Any]:
    data = _load_json_file(path, {})
    if not isinstance(data, dict):
        data = {}
    entries = data.get("entries")
    if not isinstance(entries, list):
        entries = []
    return {
        "schema_version": SCHEMA_VERSION,
        "consecutive_no_send": int(data.get("consecutive_no_send") or 0),
        "entries": [entry for entry in entries if isinstance(entry, dict)],
    }


def write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _acquire_cycle_lock(path: Path) -> Any:
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = lock_path.open("a+", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _release_cycle_lock(handle: Any) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _load_lane_records_file(path: Path) -> list[dict[str, Any]]:
    data = _load_json_file(path, [])
    return [record for record in data if isinstance(record, dict)] if isinstance(data, list) else []


def load_lane_records(path: Path) -> list[dict[str, Any]]:
    if path != LANE_REGISTRY_DEFAULT:
        return _load_lane_records_file(path)

    records: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for candidate in (
        USER_LANE_REGISTRY_DEFAULT,
        LANE_REGISTRY_DEFAULT,
    ):
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        records.extend(_load_lane_records_file(candidate))
    return records


def _target_key(record: dict[str, Any]) -> str:
    pr_number = record.get("pr_number")
    if pr_number is not None:
        try:
            return f"pr:{int(pr_number)}"
        except (TypeError, ValueError):
            pass
    branch = str(record.get("branch") or "").strip()
    if branch:
        return f"branch:{branch}"
    return f"lane:{record.get('lane_id') or record.get('owner_session') or 'unknown'}"


def _record_pr_number(record: dict[str, Any]) -> int | None:
    if record.get("pr_number") is None:
        return None
    try:
        return int(record["pr_number"])
    except (TypeError, ValueError):
        return None


def _lane_age_minutes(record: dict[str, Any], now: dt.datetime) -> float | None:
    stamp = _parse_timestamp(record.get("last_heartbeat_at") or record.get("updated_at"))
    if stamp is None:
        return None
    return max(0.0, (now - stamp).total_seconds() / 60.0)


def _is_excluded_record(
    record: dict[str, Any], now: dt.datetime, max_age_minutes: float
) -> str | None:
    status = str(record.get("status") or "").strip().lower()
    if status in TERMINAL_STATUSES:
        return f"terminal status {status}"
    if status not in ACTIVE_STATUSES:
        return f"non-active status {status or '<missing>'}"
    try:
        if int(record.get("pr_number") or 0) in EXCLUDED_PR_NUMBERS:
            return "excluded PR"
    except (TypeError, ValueError):
        pass
    branch = str(record.get("branch") or "")
    if branch.startswith(EXCLUDED_BRANCH_PREFIXES):
        return "excluded branch prefix"
    if record.get("possible_unpushed_work") is True:
        return "possible_unpushed_work"
    age = _lane_age_minutes(record, now)
    if age is None:
        return "missing freshness timestamp"
    if age > max_age_minutes:
        return f"stale lane age {age:.1f}m"
    if not str(record.get("owner_session") or "").strip():
        return "missing owner_session"
    return None


def _open_pr_lookup(open_prs_payload: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(open_prs_payload, list):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for row in open_prs_payload:
        if not isinstance(row, dict):
            continue
        try:
            number = int(row["number"])
        except (KeyError, TypeError, ValueError):
            continue
        out[number] = row
    return out


def _message_body(
    record: dict[str, Any], *, repo_root: Path, open_pr: dict[str, Any] | None = None
) -> str:
    pr_number = record.get("pr_number")
    branch = str(record.get("branch") or "").strip()
    lane_id = str(record.get("lane_id") or "").strip()
    owner_session = str(record.get("owner_session") or "").strip()
    target = (
        f"PR #{pr_number}" if pr_number else f"branch {branch}" if branch else f"lane {lane_id}"
    )
    head = ""
    if open_pr:
        head_oid = str(open_pr.get("headRefOid") or "").strip()
        if head_oid:
            head = f" at live observed head {head_oid}"
    next_action = str(
        record.get("next_action")
        or "re-ground from live state and choose exactly one bounded action"
    ).strip()
    last_observed = (
        f"lane {lane_id or '<unknown>'} status={record.get('status') or '<unknown>'}, "
        f"updated_at={record.get('updated_at') or '<unknown>'}, owner_session={owner_session}."
    )
    return "\n".join(
        [
            f"Start from live repo truth in {repo_root}. Do not trust prior transcript state.",
            "Operating contract: re-read docs/AGENT_OPERATING_CONTRACT.md §Conductor and docs/REVIEW_AUTHORITY_PRINCIPLES.md this cycle.",
            "",
            f"Target: {target}{head}; owner_session {owner_session}.",
            f"Last observed: {last_observed}",
            f"Next bounded action: {next_action}",
            "Do not merge, settle Tier 3/4, rerun workflows, use --admin, change branch protection, post duplicate evidence, delete worktrees, or touch unrelated PRs unless separately exact-head authorized.",
            "If blocked: stop and report the exact blocker plus the safest next authorization prompt.",
        ]
    )


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _ledger_has_sent_body(
    ledger: dict[str, Any],
    *,
    target_key: str,
    body_hash: str,
) -> bool:
    for entry in reversed([e for e in ledger.get("entries", []) if isinstance(e, dict)]):
        if entry.get("target_key") != target_key:
            continue
        if entry.get("sent") is True and entry.get("body_sha256") == body_hash:
            return True
    return False


def _recent_target_keys(
    ledger: dict[str, Any],
    *,
    now: dt.datetime,
    recent_cycles: int,
    recent_hours: float,
) -> set[str]:
    entries = [entry for entry in ledger.get("entries", []) if isinstance(entry, dict)]
    recent_entries = entries[-recent_cycles:] if recent_cycles > 0 else []
    cutoff = now - dt.timedelta(hours=recent_hours)
    keys: set[str] = {
        str(entry.get("target_key")) for entry in recent_entries if entry.get("target_key")
    }
    for entry in entries:
        target_key = str(entry.get("target_key") or "")
        if not target_key:
            continue
        stamp = _parse_timestamp(entry.get("timestamp"))
        if stamp is not None and stamp >= cutoff:
            keys.add(target_key)
    return keys


def _resolved_receipt_keys(receipt_dir: Path) -> tuple[set[str], set[str]]:
    filenames: set[str] = set()
    shas: set[str] = set()
    if not receipt_dir.is_dir():
        return filenames, shas
    for path in receipt_dir.glob("*.json"):
        payload = _load_json_file(path, {})
        if not isinstance(payload, dict):
            continue
        if str(payload.get("outcome") or "").strip().lower() not in RESOLVED_STEERING_OUTCOMES:
            continue
        if payload.get("message_filename"):
            filenames.add(str(payload["message_filename"]))
        if payload.get("message_sha256"):
            shas.add(str(payload["message_sha256"]))
    return filenames, shas


def unread_messages(owner_session: str, *, steering_inbox_root: Path) -> list[dict[str, Any]]:
    inbox = send_operator_steering.validate_to_session(
        owner_session, steering_inbox_root=steering_inbox_root
    )
    if not inbox.is_dir():
        return []
    resolved_filenames, resolved_shas = _resolved_receipt_keys(inbox / "_read_receipts")
    unread: list[dict[str, Any]] = []
    for path in sorted(p for p in inbox.glob("*.json") if p.is_file()):
        payload = _load_json_file(path, {})
        if not isinstance(payload, dict):
            unread.append({"path": str(path), "reason": "unreadable"})
            continue
        sha = str(payload.get("message_sha256") or "")
        if path.name not in resolved_filenames and (not sha or sha not in resolved_shas):
            unread.append(
                {
                    "path": str(path),
                    "subject": payload.get("subject"),
                    "sent_at_utc": payload.get("sent_at_utc"),
                    "message_sha256": sha,
                }
            )
    return unread


def _score_candidate(
    record: dict[str, Any],
    *,
    open_prs: dict[int, dict[str, Any]],
    now: dt.datetime,
) -> Candidate:
    target_key = _target_key(record)
    owner_session = str(record.get("owner_session") or "").strip()
    next_action = str(record.get("next_action") or "").lower()
    priority = 40
    reason = "active non-PR lane"
    pr_number: int | None = None
    try:
        pr_number = int(record["pr_number"]) if record.get("pr_number") is not None else None
    except (TypeError, ValueError):
        pr_number = None
    if pr_number is not None and pr_number in open_prs:
        priority = 10
        reason = "active owner on open PR"
        if any(term in next_action for term in HIGH_LEVERAGE_TERMS):
            priority = 0
            reason = "active open PR lane with molasses-prevention signal"
    elif any(term in next_action for term in HIGH_LEVERAGE_TERMS):
        priority = 30
        reason = "active lane with stop/coordination signal"
    age = _lane_age_minutes(record, now)
    return Candidate(
        record=record,
        target_key=target_key,
        owner_session=owner_session,
        score=(priority, age if age is not None else 999999.0, target_key),
        reason=reason,
    )


def _active_owner_conflicts(
    records: list[dict[str, Any]],
    *,
    open_prs: dict[int, dict[str, Any]],
    now: dt.datetime,
    max_lane_age_minutes: float,
    steering_inbox_root: Path,
) -> dict[str, list[str]]:
    owners_by_target: dict[str, set[str]] = {}
    for record in records:
        if _is_excluded_record(record, now, max_lane_age_minutes):
            continue
        pr_number = _record_pr_number(record)
        if pr_number is not None and pr_number not in open_prs:
            continue
        owner_session = str(record.get("owner_session") or "").strip()
        try:
            send_operator_steering.validate_to_session(
                owner_session, steering_inbox_root=steering_inbox_root
            )
        except ValueError:
            continue
        owners_by_target.setdefault(_target_key(record), set()).add(owner_session)
    return {
        target_key: sorted(owners)
        for target_key, owners in owners_by_target.items()
        if len(owners) > 1
    }


def choose_candidate(
    records: list[dict[str, Any]],
    *,
    open_prs: dict[int, dict[str, Any]],
    ledger: dict[str, Any],
    now: dt.datetime,
    recent_target_cycles: int,
    recent_target_hours: float,
    max_lane_age_minutes: float,
    steering_inbox_root: Path,
) -> tuple[Candidate | None, list[dict[str, Any]]]:
    skips: list[dict[str, Any]] = []
    candidates: list[Candidate] = []
    owner_conflicts = _active_owner_conflicts(
        records,
        open_prs=open_prs,
        now=now,
        max_lane_age_minutes=max_lane_age_minutes,
        steering_inbox_root=steering_inbox_root,
    )
    for record in records:
        target_key = _target_key(record)
        excluded = _is_excluded_record(record, now, max_lane_age_minutes)
        if excluded:
            skips.append({"target_key": target_key, "reason": excluded})
            continue
        pr_number = _record_pr_number(record)
        if pr_number is not None and pr_number not in open_prs:
            skips.append({"target_key": target_key, "reason": "PR is not open"})
            continue
        owner_session = str(record.get("owner_session") or "").strip()
        if target_key in owner_conflicts:
            skips.append(
                {
                    "target_key": target_key,
                    "owner_session": owner_session,
                    "reason": "multiple active owners",
                    "owner_sessions": owner_conflicts[target_key],
                }
            )
            continue
        try:
            unread = unread_messages(owner_session, steering_inbox_root=steering_inbox_root)
        except ValueError as exc:
            skips.append(
                {
                    "target_key": target_key,
                    "owner_session": owner_session,
                    "reason": f"invalid owner_session: {exc}",
                }
            )
            continue
        if unread:
            skips.append(
                {
                    "target_key": target_key,
                    "owner_session": owner_session,
                    "reason": "unread pending steering",
                    "unread_count": len(unread),
                }
            )
            continue
        candidates.append(_score_candidate(record, open_prs=open_prs, now=now))

    if not candidates:
        return None, skips

    recent_keys = _recent_target_keys(
        ledger,
        now=now,
        recent_cycles=recent_target_cycles,
        recent_hours=recent_target_hours,
    )
    fresh_candidates = [
        candidate for candidate in candidates if candidate.target_key not in recent_keys
    ]
    if fresh_candidates:
        candidates = fresh_candidates
    return sorted(candidates, key=lambda candidate: candidate.score)[0], skips


def _find_current_record(
    records: list[dict[str, Any]], candidate: Candidate
) -> dict[str, Any] | None:
    lane_id = candidate.record.get("lane_id")
    owner_session = candidate.record.get("owner_session")
    for record in records:
        if record.get("lane_id") == lane_id and record.get("owner_session") == owner_session:
            return record
    return None


def _current_record_blocker(
    record: dict[str, Any],
    candidate: Candidate,
    *,
    open_prs: dict[int, dict[str, Any]],
    now: dt.datetime,
    max_lane_age_minutes: float,
) -> str | None:
    current_target_key = _target_key(record)
    if current_target_key != candidate.target_key:
        return f"candidate target changed to {current_target_key}"
    excluded = _is_excluded_record(record, now, max_lane_age_minutes)
    if excluded:
        return excluded
    pr_number = _record_pr_number(record)
    if pr_number is not None and pr_number not in open_prs:
        return "PR is not open"
    return None


def _append_ledger_entry(
    ledger: dict[str, Any],
    entry: dict[str, Any],
    *,
    sent: bool,
) -> dict[str, Any]:
    entries = [e for e in ledger.get("entries", []) if isinstance(e, dict)]
    entries.append(entry)
    ledger["entries"] = entries[-200:]
    ledger["consecutive_no_send"] = 0 if sent else int(ledger.get("consecutive_no_send") or 0) + 1
    ledger["schema_version"] = SCHEMA_VERSION
    return ledger


def collect_live_state(
    config: CycleConfig,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    repo_root = config.repo_root
    fetch_result: dict[str, Any] | None = None
    if not config.skip_fetch:
        proc = _run(
            ["git", "fetch", "origin", "main", "--quiet"],
            cwd=repo_root,
            command_runner=command_runner,
            timeout=60,
        )
        fetch_result = {"returncode": proc.returncode, "stderr": proc.stderr.strip()}
    status = _run(
        ["git", "status", "--short", "--branch", "--untracked-files=all"],
        cwd=repo_root,
        command_runner=command_runner,
    )
    rev = _run(
        ["git", "rev-parse", "HEAD", "origin/main"],
        cwd=repo_root,
        command_runner=command_runner,
    )
    rev_lines = (rev.stdout or "").splitlines()
    pr_proc = _run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,headRefName,headRefOid,isDraft,mergeStateStatus,title,url",
        ],
        cwd=repo_root,
        command_runner=command_runner,
    )
    pr_payload: Any = None
    pr_error: str | None = None
    if pr_proc.returncode == 0:
        try:
            pr_payload = json.loads(pr_proc.stdout or "null")
        except json.JSONDecodeError as exc:
            pr_error = f"invalid gh pr list JSON: {exc}"
    else:
        pr_error = (pr_proc.stderr or pr_proc.stdout or "gh pr list failed").strip()
    if not isinstance(pr_payload, list):
        pr_payload = None
    return {
        "fetch": fetch_result,
        "status": status.stdout,
        "head": rev_lines[0] if len(rev_lines) >= 1 else None,
        "origin_main": rev_lines[1] if len(rev_lines) >= 2 else None,
        "open_prs": pr_payload,
        "open_pr_count": len(pr_payload) if pr_payload is not None else None,
        "open_pr_error": pr_error,
    }


def run_cycle(
    config: CycleConfig,
    *,
    command_runner: CommandRunner = subprocess.run,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now = now or _utc_now()
    live_state = collect_live_state(config, command_runner=command_runner)
    lock_handle = None
    if not config.dry_run:
        lock_handle = _acquire_cycle_lock(config.ledger_path)
    try:
        return _run_cycle_locked(config, live_state=live_state, now=now)
    finally:
        if lock_handle is not None:
            _release_cycle_lock(lock_handle)


def _run_cycle_locked(
    config: CycleConfig,
    *,
    live_state: dict[str, Any],
    now: dt.datetime,
) -> dict[str, Any]:
    ledger = load_ledger(config.ledger_path)
    records = load_lane_records(config.lane_registry_path)
    open_prs_payload = live_state.get("open_prs")
    open_prs = _open_pr_lookup(open_prs_payload)

    result: dict[str, Any] = {
        "ok": True,
        "sent": False,
        "dry_run": config.dry_run,
        "timestamp": _iso(now),
        "origin_main": live_state.get("origin_main"),
        "open_pr_count": live_state.get("open_pr_count"),
        "candidate_skips": [],
        "selected": None,
        "message_path": None,
        "stop": False,
        "stop_reason": None,
    }

    if open_prs_payload is None:
        result.update(
            {
                "ok": False,
                "no_send_reason": "open PR list unavailable",
                "open_pr_error": live_state.get("open_pr_error"),
                "ledger_consecutive_no_send": ledger["consecutive_no_send"],
                "ledger_updated": False,
                "next_prompt": _next_prompt(config.repo_root),
            }
        )
        return result

    candidate, skips = choose_candidate(
        records,
        open_prs=open_prs,
        ledger=ledger,
        now=now,
        recent_target_cycles=config.recent_target_cycles,
        recent_target_hours=config.recent_target_hours,
        max_lane_age_minutes=config.max_lane_age_minutes,
        steering_inbox_root=config.steering_inbox_root,
    )
    result["candidate_skips"] = skips[:25]

    if candidate is None:
        entry = {
            "timestamp": _iso(now),
            "sent": False,
            "skip_reason": "no eligible live owner target",
        }
        ledger = _append_ledger_entry(ledger, entry, sent=False)
        result["ledger_consecutive_no_send"] = ledger["consecutive_no_send"]
        if ledger["consecutive_no_send"] >= 3:
            result["stop"] = True
            result["stop_reason"] = "three consecutive no-send cycles"
        if not config.dry_run:
            write_ledger(config.ledger_path, ledger)
        result["ledger_updated"] = not config.dry_run
        result["no_send_reason"] = "no eligible live owner target"
        result["next_prompt"] = _next_prompt(config.repo_root)
        return result

    latest_records = load_lane_records(config.lane_registry_path)
    latest_owner_conflicts = _active_owner_conflicts(
        latest_records,
        open_prs=open_prs,
        now=now,
        max_lane_age_minutes=config.max_lane_age_minutes,
        steering_inbox_root=config.steering_inbox_root,
    )
    current_conflict_owners = latest_owner_conflicts.get(candidate.target_key)
    current_record = _find_current_record(latest_records, candidate)
    current_blocker = (
        "multiple active owners"
        if current_conflict_owners
        else (
            "candidate disappeared before send"
            if current_record is None
            else _current_record_blocker(
                current_record,
                candidate,
                open_prs=open_prs,
                now=now,
                max_lane_age_minutes=config.max_lane_age_minutes,
            )
        )
    )
    if current_blocker is not None:
        entry = {
            "timestamp": _iso(now),
            "sent": False,
            "target_key": candidate.target_key,
            "owner_session": candidate.owner_session,
            "skip_reason": current_blocker,
        }
        if current_conflict_owners:
            entry["owner_sessions"] = current_conflict_owners
        ledger = _append_ledger_entry(ledger, entry, sent=False)
        if ledger["consecutive_no_send"] >= 3:
            result["stop"] = True
            result["stop_reason"] = "three consecutive no-send cycles"
        if not config.dry_run:
            write_ledger(config.ledger_path, ledger)
        result.update(
            {
                "selected": {"target_key": candidate.target_key, "reason": candidate.reason},
                "no_send_reason": current_blocker,
                "owner_sessions": current_conflict_owners,
                "ledger_consecutive_no_send": ledger["consecutive_no_send"],
                "ledger_updated": not config.dry_run,
                "next_prompt": _next_prompt(config.repo_root),
            }
        )
        return result
    assert current_record is not None, "a missing record always sets current_blocker"
    candidate = Candidate(
        record=current_record,
        target_key=candidate.target_key,
        owner_session=candidate.owner_session,
        score=candidate.score,
        reason=candidate.reason,
    )

    open_pr: dict[str, Any] | None = None
    try:
        pr_number = (
            int(candidate.record["pr_number"])
            if candidate.record.get("pr_number") is not None
            else None
        )
    except (TypeError, ValueError):
        pr_number = None
    if pr_number is not None:
        open_pr = open_prs.get(pr_number)
    body = _message_body(candidate.record, repo_root=config.repo_root, open_pr=open_pr)
    body_hash = _body_hash(body)
    if _ledger_has_sent_body(ledger, target_key=candidate.target_key, body_hash=body_hash):
        entry = {
            "timestamp": _iso(now),
            "sent": False,
            "target_key": candidate.target_key,
            "owner_session": candidate.owner_session,
            "skip_reason": "duplicate steering body already sent",
            "body_sha256": body_hash,
        }
        ledger = _append_ledger_entry(ledger, entry, sent=False)
        if ledger["consecutive_no_send"] >= 3:
            result["stop"] = True
            result["stop_reason"] = "three consecutive no-send cycles"
        if not config.dry_run:
            write_ledger(config.ledger_path, ledger)
        result.update(
            {
                "selected": {"target_key": candidate.target_key, "reason": candidate.reason},
                "no_send_reason": "duplicate steering body already sent",
                "ledger_consecutive_no_send": ledger["consecutive_no_send"],
                "ledger_updated": not config.dry_run,
                "next_prompt": _next_prompt(config.repo_root),
            }
        )
        return result
    route = send_operator_steering.direct_route_payload(
        candidate.owner_session, steering_inbox_root=config.steering_inbox_root
    )
    message = send_operator_steering.build_message(
        to_session=candidate.owner_session,
        body=body,
        from_label="steering-conductor",
        lane_id_hint=str(candidate.record.get("lane_id") or "") or None,
        pr_hint=pr_number,
        priority="normal",
    )

    written_path: Path | None = None
    if not config.dry_run:
        written_path = send_operator_steering.write_message(
            message, steering_inbox_root=config.steering_inbox_root
        )

    entry = {
        "timestamp": _iso(now),
        "sent": not config.dry_run,
        "dry_run": config.dry_run,
        "target_key": candidate.target_key,
        "owner_session": candidate.owner_session,
        "lane_id": candidate.record.get("lane_id"),
        "pr_number": pr_number,
        "branch": candidate.record.get("branch"),
        "body_sha256": body_hash,
        "message_sha256": message["message_sha256"],
        "message_path": str(written_path) if written_path is not None else None,
        "selection_reason": candidate.reason,
    }
    ledger = _append_ledger_entry(ledger, entry, sent=not config.dry_run)
    if not config.dry_run:
        write_ledger(config.ledger_path, ledger)

    result.update(
        {
            "sent": not config.dry_run,
            "selected": {
                "target_key": candidate.target_key,
                "owner_session": candidate.owner_session,
                "lane_id": candidate.record.get("lane_id"),
                "pr_number": pr_number,
                "branch": candidate.record.get("branch"),
                "reason": candidate.reason,
                "body_sha256": body_hash,
            },
            "diagnose_result": {
                "safe_to_send": True,
                "route": route,
                "unread_pending_count": 0,
            },
            "message_path": str(written_path) if written_path is not None else None,
            "message_preview": body,
            "ledger_consecutive_no_send": ledger["consecutive_no_send"],
            "ledger_updated": not config.dry_run,
            "next_prompt": _next_prompt(config.repo_root),
        }
    )
    return result


def _next_prompt(repo_root: Path = REPO_ROOT) -> str:
    return (
        "Run one long-lived Aragora STEERING-CONDUCTOR cycle from live repo truth in "
        f"{repo_root}. Do not trust prior transcript state. "
        "Operating contract: re-read docs/AGENT_OPERATING_CONTRACT.md §Conductor, "
        "docs/REVIEW_AUTHORITY_PRINCIPLES.md, and AGENTS.md this cycle. Send at most "
        "one local operator-steering message via scripts/steering_conductor.py, "
        "respecting steering-conductor ledger rotation and all "
        "hard exclusions. Do not mutate GitHub, PR branches, evidence, settlements, "
        "workflows, branch protection, or repo-tracked files."
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="steering_conductor.py",
        description="Send at most one idempotent operator-steering message to a live lane.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Select and validate without writing."
    )
    parser.add_argument(
        "--skip-fetch", action="store_true", help="Skip git fetch for tests/offline use."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--ledger-path", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument(
        "--lane-registry-path",
        type=Path,
        default=LANE_REGISTRY_DEFAULT,
    )
    parser.add_argument(
        "--steering-inbox-root",
        type=Path,
        default=STEERING_INBOX_ROOT_DEFAULT,
    )
    parser.add_argument("--recent-target-cycles", type=int, default=DEFAULT_RECENT_TARGET_CYCLES)
    parser.add_argument("--recent-target-hours", type=float, default=DEFAULT_RECENT_TARGET_HOURS)
    parser.add_argument("--max-lane-age-minutes", type=float, default=DEFAULT_MAX_LANE_AGE_MINUTES)
    return parser


def _format_text(result: dict[str, Any]) -> str:
    lines = [
        f"origin/main: {result.get('origin_main') or '<unknown>'}",
        f"open PR count: {result.get('open_pr_count') if result.get('open_pr_count') is not None else '<unknown>'}",
    ]
    selected = result.get("selected")
    if selected:
        lines.append(
            "selected: "
            f"{selected.get('target_key')} owner={selected.get('owner_session')} "
            f"reason={selected.get('reason')}"
        )
    else:
        lines.append(f"selected: none ({result.get('no_send_reason')})")
    lines.append(f"sent: {result.get('sent')}")
    if result.get("message_path"):
        lines.append(f"message path: {result['message_path']}")
    lines.append(f"ledger consecutive no-send: {result.get('ledger_consecutive_no_send')}")
    if result.get("stop"):
        lines.append(f"STOP: {result.get('stop_reason')}")
    lines.append("")
    lines.append("Next prompt:")
    lines.append(str(result.get("next_prompt") or _next_prompt()))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = CycleConfig(
        repo_root=args.repo_root,
        ledger_path=args.ledger_path,
        lane_registry_path=args.lane_registry_path,
        steering_inbox_root=args.steering_inbox_root,
        recent_target_cycles=args.recent_target_cycles,
        recent_target_hours=args.recent_target_hours,
        max_lane_age_minutes=args.max_lane_age_minutes,
        dry_run=args.dry_run,
        skip_fetch=args.skip_fetch,
    )
    try:
        result = run_cycle(config)
    except Exception as exc:
        out = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}
        if args.json:
            print(json.dumps(out, indent=2, sort_keys=True))
        else:
            print(f"ERROR: {out['error']}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(_format_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
