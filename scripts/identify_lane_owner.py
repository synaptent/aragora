#!/usr/bin/env python3
"""Read-only consolidator: lane id / PR / branch / worktree → owner identity.

Implements Phase A of the agent-steering primitive plan. Walks the
existing aragora signals to answer the question every operator hits
when a fan-out lane is stuck: *who actually owns this PR, and where is
their session running?*

Lookup sources (read-only, in this precedence):

  1. ``.aragora/agent-bridge/lanes.json`` — primary owner identity,
     from ``LaneRecord`` rows written by
     ``scripts/claim_active_agent_lane.py``. Carries:
     ``owner_session``, ``source``, ``branch``, ``worktree``,
     ``pr_number``, plus the optional richer identity fields
     ``codex_thread_id``, ``codex_rollout_path``, ``desktop_label``,
     ``session_title`` when the claimer supplied them.

  2. ``scripts/agent_bridge.py operator-snapshot --json``
     ``process_census`` — best-effort live PID lookup when the
     snapshot exposes cwd-bearing process records. If the snapshot
     only exposes role counts, this fails closed with an explicit
     reason instead of guessing.

  3. ``~/.codex/sessions/**/*.jsonl`` — exact match via the lane's
     recorded ``codex_rollout_path`` or ``codex_thread_id``, with a
     fuzzy fallback: any recent rollout whose body contains the
     lane's worktree path string.

  4. ``~/.claude/projects/<encoded-cwd>/<uuid>.jsonl`` — Claude Code
     session lookup via the standard cwd-encoding rule
     (``/`` → ``-``).

  5. ``~/.factory/background-processes.json`` — Factory Droid
     background session match by branch or worktree.

  6. ``.aragora/operator-steering/<owner_session>/`` — pending
     steering-message inbox count (Phase B-built dir; Phase A only
     reads).

Owner-lease liveness (issue #8318): when ``--liveness`` is enabled
(default), the JSON output is additionally enriched with an
``owner_liveness`` object (lease age, last heartbeat, lane-ledger
status, assessment), a consumer-facing ``owner_blocking_state``, and
— only for stale/terminal owners with no indication of local unpushed
work — a machine-readable ``stale_claim_advisory`` codifying the
manual stale-claim override protocol exercised on #8125. This is
VISIBILITY + ADVISORY only: it may reconcile displayed owner-state
labels when current lease evidence proves a live owner, but it never
authorizes cleanup or stale-claim override by itself and it fails
closed (``advisory_withheld: "possible_unpushed_work"``) whenever
uncommitted/unpushed work might exist.

``owner_liveness.assessed`` and legacy ``liveness_state`` are deliberately
separate signals. ``owner_liveness.assessed`` uses the lane lease and the
``--stale-hours`` threshold. ``liveness_state`` remains the older direct
process / harness-heartbeat summary, including the fixed heartbeat freshness
window, so a live lease can coexist with ``missing_heartbeat`` or
``stale_heartbeat``. In that case ``owner_blocking_state`` is authoritative for
dispatch/reassignment, while ``cleanup_state`` and
``recommended_operator_action`` remain authoritative for mutation/cleanup. The
JSON ``owner_liveness_alignment`` object exposes that precedence explicitly.

Pure stdlib. No ``aragora.*`` imports. Read-only — never mutates
GitHub state, lane registry, mailboxes, or any other on-disk file.
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# Paths (overridable for tests)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]


def _state_root_from_env() -> Path | None:
    configured = os.environ.get("ARAGORA_AUTOMATION_STATE_ROOT")
    if not configured:
        return None
    root = Path(configured).expanduser()
    return root if root.name == ".aragora" else root / ".aragora"


def _git_common_repo_root(repo_root: Path) -> Path | None:
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    common_dir = Path(proc.stdout.strip())
    if common_dir.name == ".git":
        return common_dir.parent
    return None


def _default_state_root(repo_root: Path) -> Path:
    env_root = _state_root_from_env()
    if env_root is not None:
        return env_root

    local_root = repo_root / ".aragora"
    if (local_root / "agent-bridge" / "lanes.json").exists():
        return local_root

    common_repo_root = _git_common_repo_root(repo_root)
    if common_repo_root is not None:
        return common_repo_root / ".aragora"

    return local_root


STATE_ROOT_DEFAULT = _default_state_root(REPO_ROOT)
LANE_REGISTRY_DEFAULT = STATE_ROOT_DEFAULT / "agent-bridge" / "lanes.json"
HEARTBEATS_DEFAULT = STATE_ROOT_DEFAULT / "agent-bridge" / "heartbeats.json"
STEERING_INBOX_ROOT_DEFAULT = STATE_ROOT_DEFAULT / "operator-steering"
CODEX_SESSIONS_ROOT_DEFAULT = Path.home() / ".codex" / "sessions"
CLAUDE_PROJECTS_ROOT_DEFAULT = Path.home() / ".claude" / "projects"
FACTORY_BG_PROCESSES_DEFAULT = Path.home() / ".factory" / "background-processes.json"
HEARTBEAT_FRESH_SECONDS = 15 * 60

# Fuzzy codex rollout search window (seconds).
CODEX_FUZZY_MAX_AGE_SECONDS = 4 * 60 * 60
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
CONFLICT_STATUSES = {"conflict", "conflicting"}
COMPLETED_STATUSES = {"completed", "released", "superseded", "expired"}

# Subprocess timeout for ``agent_bridge operator-snapshot``.
SNAPSHOT_TIMEOUT_SECONDS = 30

SnapshotProvider = Callable[[], dict[str, Any] | None]
WORK_ID_PREFIXES = ("pr:", "issue:", "factory:", "branch:")


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class LaneOwnerInfo:
    """Consolidated owner identity for one lane.

    Mirrors the schema documented in the agent-steering plan. Fields
    that aren't applicable to a given lane carry empty dicts (with a
    ``reason`` for debuggability) rather than ``None`` so JSON
    consumers can switch on ``found``.
    """

    lane_id: str
    owner_session: str
    source: str
    status: str
    branch: str | None
    worktree: str | None
    pr_number: int | None
    goal: str | None
    updated_at: str | None
    codex_thread_id: str | None
    codex_rollout_path: str | None
    desktop_label: str | None
    session_title: str | None
    contact_method: str | None
    contact_payload: dict[str, Any] | None
    last_mailbox_check_at: str | None
    last_delivery_at: str | None
    last_ack_at: str | None
    last_heartbeat_at: str | None
    last_steering_outcome: str | None
    live_process: dict[str, Any]
    codex_thread: dict[str, Any]
    claude_session: dict[str, Any]
    factory_droid: dict[str, Any]
    steering_inbox_path: str
    pending_message_count: int
    read_receipt_count: int
    unread_message_count: int
    latest_read_receipt: dict[str, Any] | None
    latest_heartbeat: dict[str, Any] | None
    mailbox_dispatchable: bool
    live_prompt_dispatchable: bool
    dispatchable: bool
    dispatch_blocker: str | None
    steering_command: str | None
    harness_confidence: str
    owner_state: str
    liveness_state: str
    cleanup_state: str
    owner_state_reason: str
    recommended_operator_action: str


# ---------------------------------------------------------------------------
# Registry loading + match
# ---------------------------------------------------------------------------


def load_lane_records(registry_path: Path = LANE_REGISTRY_DEFAULT) -> list[dict[str, Any]]:
    """Read the lane registry; return ``[]`` on missing / unparseable."""

    if not registry_path.exists():
        return []
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _status_rank(raw_status: Any) -> int:
    """Rank lane statuses for non-unique selectors; lower is preferred."""

    status = str(raw_status or "").strip().lower()
    if status in ACTIVE_STATUSES:
        return 0
    if status in CONFLICT_STATUSES:
        return 1
    if status in COMPLETED_STATUSES:
        return 2
    return 3


def _updated_at_timestamp(raw_updated_at: Any) -> float:
    """Parse ``updated_at`` for ordering; invalid or missing values sort oldest."""

    text = str(raw_updated_at or "").strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _best_lane_match(matches: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the best row for non-unique selectors like PR, branch, or worktree."""

    if not matches:
        return None
    indexed = enumerate(matches)
    _, best = min(
        indexed,
        key=lambda item: (
            _status_rank(item[1].get("status")),
            -_updated_at_timestamp(item[1].get("updated_at")),
            item[0],
        ),
    )
    return best


def find_lane(
    records: Sequence[dict[str, Any]],
    *,
    lane_id: str | None = None,
    pr: int | None = None,
    branch: str | None = None,
    worktree: str | None = None,
) -> dict[str, Any] | None:
    """Return the best matching lane record by lane_id > pr > branch > worktree.

    Multiple historical rows can target the same PR/branch/worktree. Prefer an
    active row, then a conflict row, then the most recently updated completed or
    released row, so owner lookup does not silently route an operator to a stale
    completed lane. Exact lane-id lookup preserves registry order.
    """

    if lane_id:
        return next((r for r in records if r.get("lane_id") == lane_id), None)
    if pr is not None:
        matches = []
        for r in records:
            try:
                if int(r.get("pr_number") or 0) == int(pr):
                    matches.append(r)
            except (TypeError, ValueError):
                continue
        return _best_lane_match(matches)
    if branch:
        return _best_lane_match([r for r in records if r.get("branch") == branch])
    if worktree:
        wt_norm = os.path.normpath(worktree)
        matches = []
        for r in records:
            rwt = r.get("worktree")
            if rwt and os.path.normpath(rwt) == wt_norm:
                matches.append(r)
        return _best_lane_match(matches)
    return None


def _lane_work_id(lane: dict[str, Any]) -> str | None:
    raw = str(lane.get("work_id") or "").strip()
    if raw.startswith(WORK_ID_PREFIXES):
        return raw
    raw_pr = lane.get("pr_number")
    if raw_pr is not None:
        try:
            return f"pr:{int(raw_pr)}"
        except (TypeError, ValueError):
            pass
    branch = str(lane.get("branch") or "").strip()
    return f"branch:{branch}" if branch else None


def _check_dev_coordination_lease(
    lane: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Advisory read of the dev_coordination branch-write lease for a lane."""

    branch = str(lane.get("branch") or "").strip()
    work_id = _lane_work_id(lane)
    if not branch:
        return {
            "status": "unavailable",
            "reason": "missing_branch",
            "work_id": work_id,
            "lease_id": None,
            "owner_session_id": None,
        }

    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "check_work_lease.py"),
        branch,
        "--repo",
        str(repo_root),
        "--verify-only",
        "--advisory",
        "--strict",
        "--json",
    ]
    if work_id:
        cmd.extend(["--work-id", work_id])
    owner_session = str(lane.get("owner_session") or "").strip()
    if owner_session:
        cmd.extend(["--session-id", owner_session])
    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "unavailable",
            "reason": "store_unreachable",
            "work_id": work_id,
            "lease_id": None,
            "owner_session_id": owner_session or None,
            "detail": str(exc),
        }
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {
            "status": "unavailable",
            "reason": "store_unreachable",
            "work_id": work_id,
            "lease_id": None,
            "owner_session_id": owner_session or None,
            "detail": (proc.stderr or proc.stdout or "").strip(),
        }
    if not isinstance(payload, dict):
        payload = {}
    return {
        "status": "valid" if payload.get("ok") is True else "invalid",
        "reason": payload.get("reason"),
        "work_id": payload.get("work_id") or work_id,
        "lease_id": payload.get("lease_id"),
        "owner_session_id": payload.get("owner_session_id") or owner_session or None,
        "detail": payload.get("detail"),
    }


# ---------------------------------------------------------------------------
# Live process lookup (via agent_bridge operator-snapshot subprocess)
# ---------------------------------------------------------------------------


def _default_snapshot_provider() -> dict[str, Any] | None:
    """Shell out to ``scripts/agent_bridge.py operator-snapshot --json``."""

    bridge = REPO_ROOT / "scripts" / "agent_bridge.py"
    if not bridge.is_file():
        return None
    try:
        res = subprocess.run(
            [sys.executable, str(bridge), "operator-snapshot", "--json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=SNAPSHOT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    try:
        out = json.loads(res.stdout)
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) else None


_SOURCE_ROLE_MAP: dict[str, tuple[str, ...]] = {
    "claude": ("claude_code",),
    "claude_code": ("claude_code",),
    "codex": ("codex_cli", "codex_app_server"),
    "codex_cli": ("codex_cli",),
    "codex_app": ("codex_app_server",),
    "codex_app_server": ("codex_app_server",),
    "droid": ("factory_droid",),
    "factory": ("factory_droid",),
    "factory_droid": ("factory_droid",),
}


def _family_hints_for_lane(lane: dict[str, Any]) -> tuple[str, ...]:
    """Return live-process role hints implied by lane metadata."""

    hints: list[str] = []
    for raw in (
        lane.get("source"),
        lane.get("owner_session"),
        lane.get("lane_id"),
        lane.get("branch"),
    ):
        text = str(raw or "").lower()
        if not text:
            continue
        for token, roles in _SOURCE_ROLE_MAP.items():
            if token in text:
                for role in roles:
                    if role not in hints:
                        hints.append(role)
    return tuple(hints)


def _process_cwd(item: dict[str, Any]) -> str:
    """Return the cwd-like field from a process record, if available."""

    raw = item.get("cwd") or item.get("worktree")
    return str(raw) if raw else ""


def _process_match_payload(role: str, item: dict[str, Any], cwd: str) -> dict[str, Any]:
    """Safe metadata for a live process matched by cwd."""

    return {"pid": item.get("pid"), "family": role, "cwd": cwd}


def _collect_process_matches(
    process_census: dict[str, Any],
    *,
    target_norm: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Collect cwd-matching process records from the operator snapshot.

    The live ``operator-snapshot`` contract currently reports
    ``by_role`` as role counts and carries process rows in
    ``records``. Older fixtures used ``by_role`` as role -> process
    rows; keep that as a compatibility fallback, but do not require it.
    The boolean reports whether any cwd-bearing record existed at all.
    """

    matches: list[dict[str, Any]] = []
    saw_cwd_bearing_record = False

    records = process_census.get("records", [])
    if isinstance(records, list):
        for item in records:
            if not isinstance(item, dict):
                continue
            cwd = _process_cwd(item)
            if not cwd:
                continue
            saw_cwd_bearing_record = True
            if os.path.normpath(cwd) == target_norm:
                matches.append(
                    _process_match_payload(str(item.get("role") or "unknown"), item, cwd)
                )

    by_role = process_census.get("by_role", {})
    if isinstance(by_role, dict):
        for role, items in by_role.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                cwd = _process_cwd(item)
                if not cwd:
                    continue
                saw_cwd_bearing_record = True
                if os.path.normpath(cwd) == target_norm:
                    matches.append(_process_match_payload(str(role), item, cwd))

    matches.sort(key=lambda m: (str(m.get("family") or ""), str(m.get("pid") or "")))
    return matches, saw_cwd_bearing_record


def lookup_live_process(
    lane: dict[str, Any],
    *,
    snapshot_provider: SnapshotProvider | None = None,
) -> dict[str, Any]:
    """Best-effort PID lookup: match cwd-bearing snapshot records to lane.worktree."""

    target_wt = lane.get("worktree") or ""
    if not target_wt:
        return {"found": False, "reason": "lane has no worktree to match against"}
    target_norm = os.path.normpath(target_wt)

    provider = snapshot_provider or _default_snapshot_provider
    snap = provider()
    if snap is None:
        return {"found": False, "reason": "operator-snapshot unavailable"}

    process_census = snap.get("process_census", {})
    if not isinstance(process_census, dict):
        return {"found": False, "reason": "operator-snapshot has no process_census object"}

    matches, saw_cwd_bearing_record = _collect_process_matches(
        process_census,
        target_norm=target_norm,
    )
    if len(matches) == 1:
        match = matches[0]
        return {
            "found": True,
            "pid": match.get("pid"),
            "family": match.get("family"),
            "cwd": match.get("cwd"),
            "matched_via": "lane.worktree ↔ process_census.cwd (exact)",
        }
    if len(matches) > 1:
        family_hints = _family_hints_for_lane(lane)
        hinted = [m for m in matches if m.get("family") in family_hints]
        if len(hinted) == 1:
            match = hinted[0]
            return {
                "found": True,
                "pid": match.get("pid"),
                "family": match.get("family"),
                "cwd": match.get("cwd"),
                "matched_via": (
                    "lane.worktree ↔ process_census.cwd (exact; "
                    "disambiguated by lane family metadata)"
                ),
            }
        if hinted:
            reason = (
                "ambiguous_same_worktree: multiple process_census entries matched "
                f"{target_norm}; lane family hints {list(family_hints)} still matched "
                f"{len(hinted)} entries"
            )
        elif family_hints:
            reason = (
                "ambiguous_same_worktree: multiple process_census entries matched "
                f"{target_norm}; none matched lane family hints {list(family_hints)}"
            )
        else:
            reason = (
                "ambiguous_same_worktree: multiple process_census entries matched "
                f"{target_norm}; no lane family metadata available to disambiguate"
            )
        return {"found": False, "reason": reason, "matches": matches}
    if not saw_cwd_bearing_record:
        return {
            "found": False,
            "reason": (
                "operator-snapshot process_census has no cwd-bearing process records; "
                f"cannot match lane worktree {target_norm}"
            ),
        }
    return {
        "found": False,
        "reason": f"no process_census entry matched worktree {target_norm}",
    }


# ---------------------------------------------------------------------------
# Codex thread lookup
# ---------------------------------------------------------------------------


_ROLLOUT_FILENAME_RE = re.compile(
    r"rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-([0-9a-f-]+)\.jsonl$"
)


def _extract_thread_id(rollout_filename: str) -> str:
    m = _ROLLOUT_FILENAME_RE.search(rollout_filename)
    return m.group(1) if m else ""


def lookup_codex_thread(
    lane: dict[str, Any],
    *,
    sessions_root: Path = CODEX_SESSIONS_ROOT_DEFAULT,
    fuzzy_max_age_seconds: int = CODEX_FUZZY_MAX_AGE_SECONDS,
    now: float | None = None,
) -> dict[str, Any]:
    """Find the Codex rollout file backing this lane.

    Tries (in order): exact ``codex_rollout_path`` from the lane,
    exact ``codex_thread_id`` against rollout filenames, and a fuzzy
    fallback that scans recently-modified rollouts for the lane's
    worktree path appearing in the rollout body.
    """

    if not sessions_root.is_dir():
        return {"found": False, "reason": f"codex sessions root absent ({sessions_root})"}

    rollout_path_hint = lane.get("codex_rollout_path")
    if rollout_path_hint:
        p = Path(os.path.expanduser(str(rollout_path_hint)))
        if p.is_file():
            return {
                "found": True,
                "thread_id": _extract_thread_id(p.name),
                "rollout_path": str(p),
                "mtime": p.stat().st_mtime,
                "matched_via": "lane.codex_rollout_path (exact)",
            }

    thread_id_hint = lane.get("codex_thread_id")
    if thread_id_hint:
        for p in sessions_root.rglob("*.jsonl"):
            if str(thread_id_hint) in p.name:
                return {
                    "found": True,
                    "thread_id": str(thread_id_hint),
                    "rollout_path": str(p),
                    "mtime": p.stat().st_mtime,
                    "matched_via": "lane.codex_thread_id (exact filename match)",
                }

    # Fuzzy: scan recent rollouts for the lane's worktree string.
    worktree = lane.get("worktree")
    if not worktree:
        return {"found": False, "reason": "no codex identity hint and no worktree to fuzzy-match"}

    current = now if now is not None else time.time()
    candidates: list[tuple[float, Path]] = []
    for p in sessions_root.rglob("*.jsonl"):
        try:
            st = p.stat()
        except OSError:
            continue
        if current - st.st_mtime > fuzzy_max_age_seconds:
            continue
        candidates.append((st.st_mtime, p))

    target_str = str(worktree)
    matches: list[tuple[float, Path]] = []
    for mtime, p in candidates:
        try:
            # Cheap substring scan; rollouts are JSONL but the cwd
            # appears as a literal path string in numerous event
            # payloads when Codex tools fire.
            if target_str in p.read_text(encoding="utf-8", errors="ignore"):
                matches.append((mtime, p))
        except OSError:
            continue

    if not matches:
        return {
            "found": False,
            "reason": (
                f"no recent codex rollout (within {fuzzy_max_age_seconds // 60}m) "
                f"contained worktree string"
            ),
        }
    if len(matches) > 1:
        # Multiple matches — return the most-recent but flag the
        # ambiguity so the operator knows the answer isn't unique.
        matches.sort(key=lambda t: t[0], reverse=True)
        latest = matches[0][1]
        return {
            "found": True,
            "thread_id": _extract_thread_id(latest.name),
            "rollout_path": str(latest),
            "mtime": matches[0][0],
            "matched_via": (
                f"fuzzy: worktree string found in {len(matches)} recent "
                "rollouts; returning most-recent (ambiguous)"
            ),
        }
    mtime, p = matches[0]
    return {
        "found": True,
        "thread_id": _extract_thread_id(p.name),
        "rollout_path": str(p),
        "mtime": mtime,
        "matched_via": "fuzzy: worktree string found in single recent rollout",
    }


# ---------------------------------------------------------------------------
# Claude Code session lookup
# ---------------------------------------------------------------------------


def _encode_cwd_for_claude(cwd: str) -> str:
    """Replicate Claude Code's project-dir encoding rule (``/`` → ``-``)."""

    # Drop trailing slash for stable encoding.
    cwd_clean = cwd.rstrip("/")
    encoded = cwd_clean.replace("/", "-")
    # Leading slash → leading dash; Claude's encoding starts with '-'.
    if not encoded.startswith("-"):
        encoded = "-" + encoded
    return encoded


def lookup_claude_session(
    lane: dict[str, Any],
    *,
    projects_root: Path = CLAUDE_PROJECTS_ROOT_DEFAULT,
) -> dict[str, Any]:
    """Find the Claude Code session backing this lane (best-effort)."""

    worktree = lane.get("worktree")
    if not worktree:
        return {"found": False, "reason": "lane has no worktree to match against"}
    if not projects_root.is_dir():
        return {"found": False, "reason": f"claude projects root absent ({projects_root})"}

    encoded = _encode_cwd_for_claude(str(worktree))
    candidate = projects_root / encoded
    if not candidate.is_dir():
        return {"found": False, "reason": f"no claude project dir matched encoding ({encoded})"}

    sessions = sorted(
        (p for p in candidate.glob("*.jsonl")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not sessions:
        return {
            "found": False,
            "reason": f"claude project dir {encoded} has no .jsonl session files",
        }
    latest = sessions[0]
    return {
        "found": True,
        "session_uuid": latest.stem,
        "transcript_path": str(latest),
        "mtime": latest.stat().st_mtime,
        "matched_via": "lane.worktree → claude project encoding (most-recent .jsonl)",
    }


# ---------------------------------------------------------------------------
# Factory Droid lookup
# ---------------------------------------------------------------------------


def lookup_factory_droid(
    lane: dict[str, Any],
    *,
    bg_path: Path = FACTORY_BG_PROCESSES_DEFAULT,
) -> dict[str, Any]:
    """Match the lane to a Factory Droid background-process record by branch or worktree."""

    if not bg_path.is_file():
        return {"found": False, "reason": f"factory bg-processes file absent ({bg_path})"}
    try:
        data = json.loads(bg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"found": False, "reason": "factory bg-processes file unparseable"}

    processes_raw: Any
    if isinstance(data, list):
        processes_raw = data
    elif isinstance(data, dict):
        processes_raw = data.get("processes") or data.get("background_processes") or []
    else:
        processes_raw = []

    branch = lane.get("branch")
    worktree = lane.get("worktree")
    wt_norm = os.path.normpath(str(worktree)) if worktree else None

    for p in processes_raw:
        if not isinstance(p, dict):
            continue
        if branch and p.get("branch") == branch:
            return {
                "found": True,
                "process_id": p.get("id") or p.get("pid") or p.get("session_id"),
                "branch": branch,
                "matched_via": "factory.branch (exact)",
            }
        if wt_norm:
            p_wt = p.get("worktree") or p.get("cwd") or ""
            if p_wt and os.path.normpath(str(p_wt)) == wt_norm:
                return {
                    "found": True,
                    "process_id": p.get("id") or p.get("pid") or p.get("session_id"),
                    "worktree": p_wt,
                    "matched_via": "factory.worktree (exact)",
                }
    return {"found": False, "reason": "no factory droid process matched branch or worktree"}


# ---------------------------------------------------------------------------
# Steering inbox count
# ---------------------------------------------------------------------------


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_receipt_summary(inbox: Path, message_files: list[Path]) -> dict[str, Any]:
    receipt_dir = inbox / "_read_receipts"
    if not receipt_dir.is_dir():
        return {
            "read_receipt_count": 0,
            "unread_message_count": len(message_files),
            "latest_read_receipt": None,
        }

    receipts: list[dict[str, Any]] = []
    read_keys: set[tuple[str, str]] = set()
    for path in receipt_dir.glob("*.json"):
        if not path.is_file():
            continue
        data = _load_json_dict(path)
        if data is None:
            continue
        data["_receipt_filename"] = path.name
        receipts.append(data)
        read_keys.add(
            (
                str(data.get("message_filename") or ""),
                str(data.get("message_sha256") or ""),
            )
        )

    unread = 0
    for path in message_files:
        data = _load_json_dict(path) or {}
        key = (path.name, str(data.get("message_sha256") or ""))
        if key not in read_keys:
            unread += 1

    receipts.sort(key=lambda r: str(r.get("read_at_utc") or ""), reverse=True)
    latest = None
    if receipts:
        raw = receipts[0]
        latest = {
            "receipt_filename": raw.get("_receipt_filename"),
            "read_at_utc": raw.get("read_at_utc"),
            "read_by_session": raw.get("read_by_session"),
            "message_filename": raw.get("message_filename"),
            "message_sha256": raw.get("message_sha256"),
            "outcome": raw.get("outcome"),
            "subject": raw.get("subject"),
        }
    return {
        "read_receipt_count": len(receipts),
        "unread_message_count": unread,
        "latest_read_receipt": latest,
    }


def steering_inbox_for(
    owner_session: str, *, root: Path = STEERING_INBOX_ROOT_DEFAULT
) -> tuple[Path, int, dict[str, Any]]:
    """Return inbox path, pending count, and read-receipt summary."""

    inbox = root / owner_session
    if not inbox.is_dir():
        return (
            inbox,
            0,
            {
                "read_receipt_count": 0,
                "unread_message_count": 0,
                "latest_read_receipt": None,
            },
        )
    files = [path for path in inbox.glob("*.json") if path.is_file()]
    count = len(files)
    return inbox, count, _read_receipt_summary(inbox, files)


# ---------------------------------------------------------------------------
# Harness heartbeat lookup
# ---------------------------------------------------------------------------


def _parse_iso_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_heartbeats(heartbeat_path: Path = HEARTBEATS_DEFAULT) -> list[dict[str, Any]]:
    """Read heartbeat rows; fail closed to an empty list."""

    if not heartbeat_path.exists():
        return []
    try:
        data = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _heartbeat_matches_lane(row: dict[str, Any], lane: dict[str, Any], owner: str) -> bool:
    row_owner = str(row.get("owner_session") or "")
    if owner and row_owner != owner:
        return False
    lane_id = str(lane.get("lane_id") or "")
    if lane_id:
        return str(row.get("lane_id") or "") == lane_id
    for key in ("lane_id", "branch", "worktree"):
        lane_value = lane.get(key)
        row_value = row.get(key)
        if lane_value and row_value and str(lane_value) == str(row_value):
            return True
    raw_pr = lane.get("pr_number")
    row_pr = row.get("pr_number")
    if raw_pr is not None and row_pr is not None:
        try:
            return int(row_pr) == int(raw_pr)
        except (TypeError, ValueError):
            return False
    return False


def _heartbeat_summary(
    row: dict[str, Any],
    *,
    now: datetime,
    freshness_seconds: int,
) -> dict[str, Any]:
    seen = _parse_iso_utc(row.get("last_seen_at"))
    age_seconds: int | None = None
    fresh = False
    terminal = bool(row.get("terminal") is True or row.get("terminal_outcome"))
    if seen is not None:
        age_seconds = max(0, int((now - seen).total_seconds()))
        fresh = not terminal and age_seconds <= freshness_seconds
    return {
        "lane_id": row.get("lane_id"),
        "owner_session": row.get("owner_session"),
        "thread_id": row.get("thread_id"),
        "pid": row.get("pid"),
        "cwd": row.get("cwd"),
        "worktree": row.get("worktree"),
        "branch": row.get("branch"),
        "pr_number": row.get("pr_number"),
        "last_seen_at": row.get("last_seen_at"),
        "age_seconds": age_seconds,
        "fresh": fresh,
        "terminal": terminal,
        "terminal_outcome": row.get("terminal_outcome"),
        "terminal_reason": row.get("terminal_reason"),
        "terminal_finalized_at": row.get("terminal_finalized_at"),
    }


def latest_heartbeat_for_lane(
    lane: dict[str, Any],
    *,
    heartbeat_path: Path = HEARTBEATS_DEFAULT,
    heartbeat_now: str | None = None,
    freshness_seconds: int = HEARTBEAT_FRESH_SECONDS,
) -> dict[str, Any] | None:
    """Return the newest heartbeat row matching this lane, with freshness."""

    now = _parse_iso_utc(heartbeat_now) if heartbeat_now else datetime.now(timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    owner = str(lane.get("owner_session") or "")
    rows = [
        row for row in load_heartbeats(heartbeat_path) if _heartbeat_matches_lane(row, lane, owner)
    ]
    if not rows:
        return None
    rows.sort(
        key=lambda row: _parse_iso_utc(row.get("last_seen_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return _heartbeat_summary(rows[0], now=now, freshness_seconds=freshness_seconds)


def _dispatch_blocker_for(lane: dict[str, Any], owner_session: str) -> str | None:
    status = str(lane.get("status") or "").strip().lower()
    if not owner_session:
        return "lane has no owner_session"
    if status in ACTIVE_STATUSES:
        return None
    if status in CONFLICT_STATUSES:
        return "lane status is conflict; resolve the conflict before steering"
    if status in COMPLETED_STATUSES:
        return f"lane status is {status}; claim an active lane before steering"
    return f"lane status is {status or 'unknown'}; claim an active lane before steering"


def _contact_payload_for(lane: dict[str, Any]) -> dict[str, Any] | None:
    payload = lane.get("contact_payload")
    return payload if isinstance(payload, dict) else None


def _live_prompt_dispatchable_for(lane: dict[str, Any], owner_session: str) -> bool:
    if _dispatch_blocker_for(lane, owner_session) is not None:
        return False
    method = str(lane.get("contact_method") or "").strip()
    if method.startswith("tmux:"):
        return bool(method.removeprefix("tmux:").strip())
    if method.startswith("codex-exec-resume:"):
        return bool(method.removeprefix("codex-exec-resume:").strip())
    if method.startswith("codex-app-server:"):
        payload = _contact_payload_for(lane) or {}
        return bool(
            payload.get("socket") and (payload.get("thread_id") or lane.get("codex_thread_id"))
        )
    return bool(lane.get("codex_thread_id"))


def _steering_command_for(lane: dict[str, Any], owner_session: str) -> str | None:
    if _dispatch_blocker_for(lane, owner_session) is not None:
        return None
    parts = [
        "python3",
        "scripts/send_operator_steering.py",
        "--to",
        owner_session,
    ]
    lane_id = str(lane.get("lane_id") or "")
    if lane_id:
        parts.extend(["--lane-id", lane_id])
    raw_pr = lane.get("pr_number")
    if raw_pr is not None:
        parts.extend(["--pr", str(raw_pr)])
    parts.extend(["--priority", "blocking", "--body", "'<message>'"])
    return " ".join(parts)


def _harness_confidence_for(
    lane: dict[str, Any],
    *,
    live: dict[str, Any],
    codex: dict[str, Any],
    claude: dict[str, Any],
    factory: dict[str, Any],
) -> str:
    if any(
        lane.get(field)
        for field in (
            "codex_thread_id",
            "codex_rollout_path",
            "desktop_label",
            "session_title",
        )
    ):
        return "recorded_identity"
    if live.get("found"):
        return "live_process"
    if codex.get("found"):
        matched_via = str(codex.get("matched_via") or "")
        if "ambiguous" in matched_via or "fuzzy" in matched_via:
            return "mailbox_only_fuzzy_thread"
        return "codex_thread_best_effort"
    if claude.get("found"):
        return "claude_session_best_effort"
    if factory.get("found"):
        return "factory_droid_best_effort"
    return "mailbox_only"


def _owner_state_for(
    lane: dict[str, Any],
    *,
    owner_session: str,
    live: dict[str, Any],
    heartbeat: dict[str, Any] | None,
) -> dict[str, str]:
    status = str(lane.get("status") or "").strip().lower()
    if live.get("found"):
        liveness_state = "live_process"
    elif heartbeat is None:
        liveness_state = "missing_heartbeat"
    elif heartbeat.get("fresh"):
        liveness_state = "fresh_heartbeat"
    else:
        liveness_state = "stale_heartbeat"

    if not owner_session:
        return {
            "owner_state": "unowned",
            "liveness_state": liveness_state,
            "cleanup_state": "unowned_requires_fresh_cleanup_inspect",
            "owner_state_reason": "lane has no owner_session",
            "recommended_operator_action": "claim the lane before mutation; run cleanup inspection before deletion",
        }
    if status in CONFLICT_STATUSES:
        return {
            "owner_state": "duplicate",
            "liveness_state": liveness_state,
            "cleanup_state": "preserve_duplicate_owner",
            "owner_state_reason": "lane is in conflict status",
            "recommended_operator_action": "resolve the lane conflict before mutation or cleanup",
        }
    if status in COMPLETED_STATUSES:
        return {
            "owner_state": "stale",
            "liveness_state": liveness_state,
            "cleanup_state": "historical_requires_cleanup_inspect",
            "owner_state_reason": f"lane status is {status}",
            "recommended_operator_action": "treat as historical; run fresh cleanup inspection before any deletion",
        }
    if status in ACTIVE_STATUSES:
        if liveness_state == "stale_heartbeat":
            return {
                "owner_state": "owned",
                "liveness_state": liveness_state,
                "cleanup_state": "preserve_stale_owner",
                "owner_state_reason": "active lane has stale heartbeat evidence",
                "recommended_operator_action": "preserve; refresh heartbeat or contact owner before mutation or cleanup",
            }
        if liveness_state == "missing_heartbeat":
            return {
                "owner_state": "owned",
                "liveness_state": liveness_state,
                "cleanup_state": "preserve_unverified_owner",
                "owner_state_reason": "active lane has no heartbeat evidence",
                "recommended_operator_action": "preserve; start or refresh agent heartbeat before cleanup decisions",
            }
        return {
            "owner_state": "owned",
            "liveness_state": liveness_state,
            "cleanup_state": "preserve_live_owner",
            "owner_state_reason": f"lane status is {status} with current liveness evidence",
            "recommended_operator_action": "route work through owner_session; do not cleanup without owner release",
        }
    return {
        "owner_state": "unknown",
        "liveness_state": liveness_state,
        "cleanup_state": "preserve_unknown_owner_state",
        "owner_state_reason": f"lane status is {status or 'unknown'}",
        "recommended_operator_action": "preserve until lane status is clarified",
    }


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def build_owner_info(
    lane: dict[str, Any],
    *,
    snapshot_provider: SnapshotProvider | None = None,
    sessions_root: Path = CODEX_SESSIONS_ROOT_DEFAULT,
    projects_root: Path = CLAUDE_PROJECTS_ROOT_DEFAULT,
    bg_path: Path = FACTORY_BG_PROCESSES_DEFAULT,
    steering_inbox_root: Path = STEERING_INBOX_ROOT_DEFAULT,
    heartbeat_path: Path = HEARTBEATS_DEFAULT,
    heartbeat_now: str | None = None,
    heartbeat_fresh_seconds: int = HEARTBEAT_FRESH_SECONDS,
    fuzzy_now: float | None = None,
) -> LaneOwnerInfo:
    owner = str(lane.get("owner_session") or "")
    live = lookup_live_process(lane, snapshot_provider=snapshot_provider)
    codex = lookup_codex_thread(lane, sessions_root=sessions_root, now=fuzzy_now)
    claude = lookup_claude_session(lane, projects_root=projects_root)
    factory = lookup_factory_droid(lane, bg_path=bg_path)
    inbox_path, pending, receipt_summary = steering_inbox_for(owner, root=steering_inbox_root)
    heartbeat = latest_heartbeat_for_lane(
        lane,
        heartbeat_path=heartbeat_path,
        heartbeat_now=heartbeat_now,
        freshness_seconds=heartbeat_fresh_seconds,
    )
    dispatch_blocker = _dispatch_blocker_for(lane, owner)
    owner_state = _owner_state_for(lane, owner_session=owner, live=live, heartbeat=heartbeat)

    raw_pr = lane.get("pr_number")
    try:
        pr_number = int(raw_pr) if raw_pr is not None else None
    except (TypeError, ValueError):
        pr_number = None

    return LaneOwnerInfo(
        lane_id=str(lane.get("lane_id") or ""),
        owner_session=owner,
        source=str(lane.get("source") or ""),
        status=str(lane.get("status") or ""),
        branch=lane.get("branch"),
        worktree=lane.get("worktree"),
        pr_number=pr_number,
        goal=lane.get("goal"),
        updated_at=lane.get("updated_at"),
        codex_thread_id=lane.get("codex_thread_id"),
        codex_rollout_path=lane.get("codex_rollout_path"),
        desktop_label=lane.get("desktop_label"),
        session_title=lane.get("session_title"),
        contact_method=lane.get("contact_method"),
        contact_payload=_contact_payload_for(lane),
        last_mailbox_check_at=lane.get("last_mailbox_check_at"),
        last_delivery_at=lane.get("last_delivery_at"),
        last_ack_at=lane.get("last_ack_at"),
        last_heartbeat_at=lane.get("last_heartbeat_at"),
        last_steering_outcome=lane.get("last_steering_outcome"),
        live_process=live,
        codex_thread=codex,
        claude_session=claude,
        factory_droid=factory,
        steering_inbox_path=str(inbox_path),
        pending_message_count=pending,
        read_receipt_count=int(receipt_summary["read_receipt_count"]),
        unread_message_count=int(receipt_summary["unread_message_count"]),
        latest_read_receipt=receipt_summary["latest_read_receipt"],
        latest_heartbeat=heartbeat,
        mailbox_dispatchable=dispatch_blocker is None,
        live_prompt_dispatchable=_live_prompt_dispatchable_for(lane, owner),
        dispatchable=dispatch_blocker is None,
        dispatch_blocker=dispatch_blocker,
        steering_command=_steering_command_for(lane, owner),
        harness_confidence=_harness_confidence_for(
            lane,
            live=live,
            codex=codex,
            claude=claude,
            factory=factory,
        ),
        owner_state=owner_state["owner_state"],
        liveness_state=owner_state["liveness_state"],
        cleanup_state=owner_state["cleanup_state"],
        owner_state_reason=owner_state["owner_state_reason"],
        recommended_operator_action=owner_state["recommended_operator_action"],
    )


# ---------------------------------------------------------------------------
# Owner-lease liveness + stale-claim advisory (issue #8318)
# ---------------------------------------------------------------------------
#
# Advisory-only by design. Nothing in this section changes a go/no-go
# decision; it only makes a dead owner lock *visible* and codifies the
# manual stale-claim protocol (exercised successfully on #8125) as
# machine-readable output for the operator / conveyor to act on.

STALE_HOURS_DEFAULT = 6.0
LANE_RUNS_GLOB_DEFAULT = str(STATE_ROOT_DEFAULT / "run-*" / "lanes")

# Lane-ledger/status rows meaning the owning lane can no longer be working.
TERMINAL_LANE_STATUSES = COMPLETED_STATUSES | {"failed", "cancelled", "dead"}

STALE_CLAIM_PROTOCOL = "stale-claim-override"
ADVISORY_WITHHELD_UNPUSHED = "possible_unpushed_work"
REQUIRED_LEDGER_RECORD = "overriding lane must write an override entry naming the stale lane id"

OWNER_BLOCKING_LIVE = "live_owner"
OWNER_BLOCKING_UNKNOWN = "unknown_owner"
OWNER_BLOCKING_STALE = "stale_owner"
OWNER_BLOCKING_STALE_TERMINAL = "stale_terminal_owner"

# Timestamp fields on the owner (lane-registry) record; newest wins.
_OWNER_RECORD_TIMESTAMP_KEYS = (
    "updated_at",
    "claimed_at",
    "created_at",
    "last_heartbeat_at",
    "last_mailbox_check_at",
    "last_delivery_at",
    "last_ack_at",
)

# Timestamp fields on a lane-ledger entry (.aragora/run-*/lanes/*.json).
_LEDGER_TIMESTAMP_KEYS = (
    "updated_at",
    "launched_at",
    "detected_at",
    "completed_at",
    "finished_at",
    "heartbeat_at",
    "last_heartbeat_at",
)

# Boolean-ish owner/ledger fields that claim local (possibly unpushed) work.
_LOCAL_WORK_CLAIM_KEYS = (
    "uncommitted_changes",
    "has_uncommitted_changes",
    "uncommitted",
    "unpushed_commits",
    "possible_unpushed_work",
    "branch_ahead_of_origin_main",
    "unique_commits_ahead",
    "local_changes",
    "local_work",
    "dirty",
    "dirty_worktree",
    "worktree_dirty",
)
_UPSTREAM_PRESERVABLE_LOCAL_WORK_CLAIM_KEYS = (
    "branch_ahead_of_origin_main",
    "unique_commits_ahead",
)
_FALSE_LOCAL_WORK_CLAIM_STRINGS = {
    "",
    "0",
    "false",
    "no",
    "none",
    "null",
    "[]",
    "{}",
    "clean",
    "verified-clean",
    "verified_clean",
}

_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")
_PRESERVATION_GIT_TIMEOUT_SECONDS = 10.0
_PRESERVATION_GH_TIMEOUT_SECONDS = 20.0
_SAFE_WORKTREE_INSPECT_TIMEOUT_SECONDS = 30.0
_PRESERVATION_OUTBOX_DIRS = ("automation-outbox", "automation-receipts")
_PRESERVATION_SHA_KEYS = (
    "desired_head_sha",
    "head_sha",
    "headRefOid",
    "merge_head_sha",
    "commit_sha",
)

CommandRunner = Callable[[list[str], Path, float], subprocess.CompletedProcess[str]]


def _run_preservation_command(
    cmd: list[str],
    cwd: Path,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _ledger_entry_timestamp(entry: dict[str, Any]) -> float:
    """Most recent parseable timestamp on a lane-ledger entry (0.0 if none)."""

    return max(_updated_at_timestamp(entry.get(key)) for key in _LEDGER_TIMESTAMP_KEYS)


def find_lane_ledger_entry(
    lane: dict[str, Any],
    *,
    runs_glob: str = LANE_RUNS_GLOB_DEFAULT,
) -> dict[str, Any] | None:
    """Newest lane-ledger entry matching this lane by lane id or branch.

    Lane ledgers live at ``<runs_glob>/*.json`` (the same layout
    ``scripts/lane_janitor.py`` consumes): one JSON object per lane
    with ``lane``, ``branch``, ``status``, ``launched_at`` and, when
    the janitor has acted, ``detected_at``.
    """

    lane_id = str(lane.get("lane_id") or "")
    branch = str(lane.get("branch") or "")
    if not lane_id and not branch:
        return None

    best: dict[str, Any] | None = None
    best_ts = float("-inf")
    for lanes_dir in sorted(glob.glob(runs_glob)):
        lanes_path = Path(lanes_dir)
        if not lanes_path.is_dir():
            continue
        for ledger_file in sorted(lanes_path.glob("*.json")):
            try:
                entry = json.loads(ledger_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(entry, dict):
                continue
            entry_lane = str(entry.get("lane") or entry.get("lane_id") or "")
            entry_branch = str(entry.get("branch") or "")
            if not ((lane_id and entry_lane == lane_id) or (branch and entry_branch == branch)):
                continue
            ts = _ledger_entry_timestamp(entry)
            if ts > best_ts:
                best, best_ts = entry, ts
    return best


def _normal_state_root(path: Path) -> Path:
    return path if path.name == ".aragora" else path / ".aragora"


def _local_work_claim_indication(
    lane: dict[str, Any],
    ledger_entry: dict[str, Any] | None,
    *,
    local_work_preservation: dict[str, Any] | None = None,
    include_preservable_branch_claims: bool = True,
) -> str | None:
    upstream_preserved = _proof_has_upstream_preservation(local_work_preservation)
    for source_name, record in (("owner record", lane), ("lane ledger", ledger_entry or {})):
        for key in _LOCAL_WORK_CLAIM_KEYS:
            if key in _UPSTREAM_PRESERVABLE_LOCAL_WORK_CLAIM_KEYS:
                if not include_preservable_branch_claims or upstream_preserved:
                    continue
            if _truthy_local_work_claim(record.get(key)):
                return f"{source_name} claims local work ({key})"
    return None


def _truthy_local_work_claim(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized not in _FALSE_LOCAL_WORK_CLAIM_STRINGS
    return bool(value)


def _proof_has_upstream_preservation(proof: dict[str, Any] | None) -> bool:
    if not proof or proof.get("available") is not True:
        return False
    upstream_preservation = proof.get("upstream_preservation")
    return isinstance(upstream_preservation, dict) and upstream_preservation.get("proven") is True


def _worktree_reference_paths(
    lane: dict[str, Any], ledger_entry: dict[str, Any] | None
) -> list[tuple[str, str]]:
    paths: list[tuple[str, str]] = []
    for source_name, record in (("owner record", lane), ("lane ledger", ledger_entry or {})):
        worktree = str(record.get("worktree") or "").strip()
        if worktree:
            paths.append((source_name, worktree))
    return paths


def _proof_covers_worktree_paths(
    proof: dict[str, Any] | None,
    paths: list[tuple[str, str]],
) -> bool:
    if proof is None or not _proof_has_upstream_preservation(proof):
        return False
    proven_paths = {str(path) for path in proof.get("worktree_paths") or []}
    return all(path in proven_paths for _, path in paths)


def _json_payload(stdout: str) -> Any:
    try:
        return json.loads(stdout or "null")
    except json.JSONDecodeError:
        return None


def _safe_worktree_absent_noop_proof(
    path: str,
    *,
    repo_root: Path,
    runner: CommandRunner,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "safe_worktree_cleanup.py"),
        "inspect",
        path,
        "--json",
    ]
    try:
        proc = runner(cmd, repo_root, _SAFE_WORKTREE_INSPECT_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"path": path, "absent_noop": False, "reason": f"inspect_failed: {exc}"}

    payload = _json_payload(proc.stdout)
    if not isinstance(payload, dict):
        return {
            "path": path,
            "absent_noop": False,
            "reason": "safe_worktree_inspect_json_unavailable",
        }

    safety = payload.get("cleanup_safety")
    classification = safety.get("classification") if isinstance(safety, dict) else None
    payload_blockers = payload.get("blockers")
    blockers: list[Any] = payload_blockers if isinstance(payload_blockers, list) else []
    absent_noop = (
        payload.get("exists") is False
        and payload.get("dirty") is not True
        and payload.get("active_session") is not True
        and "missing_path" in blockers
        and classification == "absent_noop"
    )
    clean_inactive = (
        payload.get("exists") is True
        and payload.get("tracked_worktree") is True
        and payload.get("dirty") is False
        and payload.get("active_session") is False
        and bool(str(payload.get("branch") or "").strip())
    )
    if absent_noop:
        return {
            "path": path,
            "absent_noop": True,
            "clean_inactive": False,
            "source": "safe_worktree_cleanup.inspect",
            "classification": classification,
        }
    if clean_inactive:
        return {
            "path": path,
            "absent_noop": False,
            "clean_inactive": True,
            "branch": str(payload["branch"]).strip(),
            "source": "safe_worktree_cleanup.inspect",
            "classification": classification,
        }
    return {
        "path": path,
        "absent_noop": False,
        "clean_inactive": False,
        "reason": "worktree_not_absent_noop",
        "exists": payload.get("exists"),
        "classification": classification,
        "blockers": blockers,
    }


def _record_matches_lane(record: dict[str, Any], *, lane_id: str, branch: str) -> bool:
    for candidate in (record, record.get("metadata"), record.get("payload")):
        if not isinstance(candidate, dict):
            continue
        if lane_id and str(candidate.get("lane_id") or "") == lane_id:
            return True
        if branch and str(candidate.get("branch") or "") == branch:
            return True
    return False


def _matching_state_records(
    *,
    lane_id: str,
    branch: str,
    state_root: Path,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    root = _normal_state_root(state_root)
    for dirname in _PRESERVATION_OUTBOX_DIRS:
        directory = root / dirname
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and _record_matches_lane(
                payload, lane_id=lane_id, branch=branch
            ):
                payload = dict(payload)
                payload["_source_path"] = str(path)
                records.append(payload)
    return records


def _first_sha_from_record(record: dict[str, Any] | None) -> str | None:
    if not isinstance(record, dict):
        return None
    for key in _PRESERVATION_SHA_KEYS:
        value = record.get(key)
        if isinstance(value, str) and _SHA_RE.fullmatch(value.strip()):
            return value.strip()
    for key in ("metadata", "payload", "details", "handoff"):
        nested = record.get(key)
        if isinstance(nested, dict):
            value = _first_sha_from_record(nested)
            if value:
                return value
    return None


def _desired_head_for_preservation(
    lane: dict[str, Any],
    ledger_entry: dict[str, Any] | None,
    *,
    state_root: Path,
) -> tuple[str | None, dict[str, Any] | None]:
    branch = str(lane.get("branch") or (ledger_entry or {}).get("branch") or "")
    lane_id = str(lane.get("lane_id") or (ledger_entry or {}).get("lane") or "")
    records: list[dict[str, Any]] = [lane]
    if ledger_entry is not None:
        records.append(ledger_entry)
    records.extend(_matching_state_records(lane_id=lane_id, branch=branch, state_root=state_root))

    for record in records:
        sha = _first_sha_from_record(record)
        if sha:
            return sha, record
    return None, None


def _remote_branch_head(
    branch: str,
    *,
    repo_root: Path,
    runner: CommandRunner,
) -> dict[str, Any]:
    try:
        proc = runner(
            ["git", "ls-remote", "origin", f"refs/heads/{branch}"],
            repo_root,
            _PRESERVATION_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "lookup_failed", "reason": str(exc)}
    if proc.returncode != 0:
        return {"status": "lookup_failed", "reason": proc.stderr.strip()}
    line = (proc.stdout or "").strip().splitlines()
    if not line:
        return {"status": "missing"}
    head = line[0].split()[0] if line[0].split() else ""
    if not _SHA_RE.fullmatch(head):
        return {"status": "lookup_failed", "reason": "unexpected ls-remote output"}
    return {"status": "exists", "head_sha": head}


def _local_branch_head(
    branch: str,
    *,
    repo_root: Path,
    runner: CommandRunner,
) -> dict[str, Any]:
    """Return the local branch tip without resolving or changing the worktree."""

    try:
        proc = runner(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
            repo_root,
            _PRESERVATION_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "lookup_failed", "reason": str(exc)}
    if proc.returncode == 1 and not (proc.stdout or "").strip():
        return {"status": "missing"}
    if proc.returncode != 0:
        return {"status": "lookup_failed", "reason": proc.stderr.strip()}
    head = (proc.stdout or "").strip()
    if not _SHA_RE.fullmatch(head):
        return {"status": "lookup_failed", "reason": "unexpected rev-parse output"}
    return {"status": "exists", "head_sha": head}


def _repo_slug_from_origin(repo_root: Path, *, runner: CommandRunner) -> str | None:
    try:
        proc = runner(
            ["git", "remote", "get-url", "origin"], repo_root, _PRESERVATION_GIT_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    if url.endswith(".git"):
        url = url[:-4]
    if url.startswith("git@github.com:"):
        return url.removeprefix("git@github.com:")
    marker = "github.com/"
    if marker in url:
        return url.split(marker, 1)[1].strip("/")
    return None


def _gh_api_json(
    api_path: str,
    *,
    repo_root: Path,
    runner: CommandRunner,
) -> Any:
    try:
        proc = runner(
            ["gh", "api", "-H", "Accept: application/vnd.github+json", api_path],
            repo_root,
            _PRESERVATION_GH_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return _json_payload(proc.stdout)


def _gh_api_paginated_json_list(
    api_path: str,
    *,
    repo_root: Path,
    runner: CommandRunner,
    per_page: int = 100,
    max_pages: int = 20,
) -> list[Any] | None:
    """Fetch a small GitHub REST list endpoint without silently truncating it."""

    values: list[Any] = []
    separator = "&" if "?" in api_path else "?"
    for page in range(1, max_pages + 1):
        payload = _gh_api_json(
            f"{api_path}{separator}per_page={per_page}&page={page}",
            repo_root=repo_root,
            runner=runner,
        )
        if not isinstance(payload, list):
            return None
        values.extend(payload)
        if len(payload) < per_page:
            return values
    return None


def _pull_base_ref(pull: Mapping[str, Any]) -> str:
    base = pull.get("base")
    if isinstance(base, Mapping):
        ref = str(base.get("ref") or "").strip()
        if ref:
            return ref
    for key in ("baseRefName", "base_ref_name", "base_ref"):
        ref = str(pull.get(key) or "").strip()
        if ref:
            return ref
    return ""


def _merged_pr_commit_list_proof(
    desired_head: str,
    *,
    repo_root: Path,
    runner: CommandRunner,
) -> dict[str, Any]:
    repo_slug = _repo_slug_from_origin(repo_root, runner=runner)
    if not repo_slug:
        return {
            "proven": False,
            "method": "merged_pr_commit_list",
            "reason": "repo_slug_unavailable",
        }

    pulls = _gh_api_json(
        f"repos/{repo_slug}/commits/{desired_head}/pulls", repo_root=repo_root, runner=runner
    )
    if not isinstance(pulls, list):
        return {
            "proven": False,
            "method": "merged_pr_commit_list",
            "reason": "commit_pulls_unavailable",
        }

    for pull in pulls:
        if not isinstance(pull, dict) or not pull.get("merged_at"):
            continue
        number = pull.get("number")
        if not isinstance(number, int):
            continue
        commits = _gh_api_paginated_json_list(
            f"repos/{repo_slug}/pulls/{number}/commits",
            repo_root=repo_root,
            runner=runner,
        )
        if not isinstance(commits, list):
            continue
        if any(isinstance(item, dict) and item.get("sha") == desired_head for item in commits):
            base_ref = _pull_base_ref(pull)
            return {
                "proven": True,
                "method": "merged_pr_commit_list",
                "pr_number": number,
                "repo": repo_slug,
                "base_ref": base_ref or None,
            }
    return {
        "proven": False,
        "method": "merged_pr_commit_list",
        "reason": "no_merged_pr_commit_contains_desired_head",
    }


def build_worktree_reference_preservation_proof(
    lane: dict[str, Any],
    *,
    ledger_entry: dict[str, Any] | None = None,
    repo_root: Path = REPO_ROOT,
    state_root: Path = STATE_ROOT_DEFAULT,
    runner: CommandRunner = _run_preservation_command,
) -> dict[str, Any] | None:
    """Prove a bare worktree reference is not evidence of local-only work.

    Fail closed unless ``safe_worktree_cleanup.py inspect`` reports each
    recorded worktree absent/noop or clean, inactive, and on the recorded
    branch, and the corresponding commit is preserved upstream. For a
    terminal no-record lane, the remote branch is sufficient only when the
    local branch is absent or has the exact same tip. A present clean
    worktree additionally requires exact local/remote branch equality.
    Divergence, lookup failure, or dirty/local-work markers remain blocking.
    """

    paths = _worktree_reference_paths(lane, ledger_entry)
    if not paths:
        return None

    local_claim = _local_work_claim_indication(
        lane,
        ledger_entry,
        include_preservable_branch_claims=False,
    )
    if local_claim:
        return {
            "available": False,
            "reason": "local_work_claim_present",
            "detail": local_claim,
            "worktree_paths": [path for _, path in paths],
        }

    inspections = [
        _safe_worktree_absent_noop_proof(path, repo_root=repo_root, runner=runner)
        for _, path in paths
    ]
    if not all(
        item.get("absent_noop") is True or item.get("clean_inactive") is True
        for item in inspections
    ):
        return {
            "available": False,
            "reason": "worktree_not_absent_noop",
            "worktree_paths": [path for _, path in paths],
            "worktree_inspections": inspections,
        }

    branch = str(lane.get("branch") or (ledger_entry or {}).get("branch") or "").strip()
    desired_head, source_record = _desired_head_for_preservation(
        lane, ledger_entry, state_root=state_root
    )
    if not branch:
        return {
            "available": False,
            "reason": "branch_unavailable",
            "worktree_paths": [path for _, path in paths],
            "worktree_inspections": inspections,
        }
    clean_worktrees = [item for item in inspections if item.get("clean_inactive") is True]
    if any(item.get("branch") != branch for item in clean_worktrees):
        return {
            "available": False,
            "reason": "worktree_branch_mismatch",
            "branch": branch,
            "worktree_paths": [path for _, path in paths],
            "worktree_inspections": inspections,
        }
    if not desired_head:
        remote = _remote_branch_head(branch, repo_root=repo_root, runner=runner)
        lane_status = str((ledger_entry or {}).get("status") or lane.get("status") or "")
        if (
            remote.get("status") == "exists"
            and lane_status.strip().lower() in TERMINAL_LANE_STATUSES
        ):
            remote_head = remote.get("head_sha")
            local = _local_branch_head(branch, repo_root=repo_root, runner=runner)
            if local.get("status") == "lookup_failed":
                return {
                    "available": False,
                    "reason": "local_branch_lookup_failed",
                    "branch": branch,
                    "remote": remote,
                    "local": local,
                    "worktree_paths": [path for _, path in paths],
                    "worktree_inspections": inspections,
                }
            if local.get("status") == "exists" and local.get("head_sha") != remote_head:
                return {
                    "available": False,
                    "reason": "local_remote_branch_head_mismatch",
                    "branch": branch,
                    "remote": remote,
                    "local": local,
                    "worktree_paths": [path for _, path in paths],
                    "worktree_inspections": inspections,
                }
            if clean_worktrees and local.get("status") != "exists":
                return {
                    "available": False,
                    "reason": "local_branch_missing_for_present_worktree",
                    "branch": branch,
                    "remote": remote,
                    "local": local,
                    "worktree_paths": [path for _, path in paths],
                    "worktree_inspections": inspections,
                }
            method = (
                "remote_branch_matches_clean_worktree_no_record"
                if clean_worktrees
                else "remote_branch_matches_local_branch_no_record"
                if local.get("status") == "exists"
                else "remote_branch_only_no_local_record"
            )
            return {
                "available": True,
                "branch": branch,
                "desired_head_sha": None,
                "desired_head_source": "not_recorded",
                "lane_status": lane_status.strip().lower(),
                "worktree_paths": [path for _, path in paths],
                "worktree_inspections": inspections,
                "local_branch": local,
                "upstream_preservation": {
                    "proven": True,
                    "method": method,
                    "remote_head_sha": remote_head,
                    "scope": (
                        "registered worktree is absent and no divergent local branch tip exists"
                    ),
                },
            }
        return {
            "available": False,
            "reason": (
                "desired_head_unavailable_non_terminal_lane"
                if remote.get("status") == "exists"
                else "desired_head_unavailable"
            ),
            "branch": branch,
            "remote": remote,
            "worktree_paths": [path for _, path in paths],
            "worktree_inspections": inspections,
        }

    remote = _remote_branch_head(branch, repo_root=repo_root, runner=runner)
    if remote.get("status") == "exists":
        if clean_worktrees:
            local = _local_branch_head(branch, repo_root=repo_root, runner=runner)
            if local.get("status") != "exists" or local.get("head_sha") != remote.get("head_sha"):
                return {
                    "available": False,
                    "reason": "clean_worktree_branch_not_preserved",
                    "branch": branch,
                    "desired_head_sha": desired_head,
                    "remote": remote,
                    "local": local,
                    "worktree_paths": [path for _, path in paths],
                    "worktree_inspections": inspections,
                }
        if remote.get("head_sha") == desired_head:
            return {
                "available": True,
                "branch": branch,
                "desired_head_sha": desired_head,
                "desired_head_source": (source_record or {}).get("_source_path", "lane_or_ledger"),
                "worktree_paths": [path for _, path in paths],
                "worktree_inspections": inspections,
                "upstream_preservation": {
                    "proven": True,
                    "method": "remote_branch_exact_head",
                    "remote_head_sha": remote.get("head_sha"),
                },
            }
        return {
            "available": False,
            "reason": "remote_branch_head_mismatch",
            "branch": branch,
            "desired_head_sha": desired_head,
            "remote": remote,
            "worktree_paths": [path for _, path in paths],
            "worktree_inspections": inspections,
        }
    if remote.get("status") != "missing":
        return {
            "available": False,
            "reason": "remote_branch_lookup_failed",
            "branch": branch,
            "desired_head_sha": desired_head,
            "remote": remote,
            "worktree_paths": [path for _, path in paths],
            "worktree_inspections": inspections,
        }

    if clean_worktrees:
        # A merged historical head does not preserve a present worktree's current tip.
        return {
            "available": False,
            "reason": "remote_branch_missing_for_present_worktree",
            "branch": branch,
            "desired_head_sha": desired_head,
            "remote": remote,
            "worktree_paths": [path for _, path in paths],
            "worktree_inspections": inspections,
        }

    merged_pr = _merged_pr_commit_list_proof(desired_head, repo_root=repo_root, runner=runner)
    if merged_pr.get("proven") is True:
        return {
            "available": True,
            "branch": branch,
            "desired_head_sha": desired_head,
            "desired_head_source": (source_record or {}).get("_source_path", "lane_or_ledger"),
            "worktree_paths": [path for _, path in paths],
            "worktree_inspections": inspections,
            "upstream_preservation": merged_pr,
        }
    return {
        "available": False,
        "reason": "upstream_preservation_unproven",
        "branch": branch,
        "desired_head_sha": desired_head,
        "remote": remote,
        "merged_pr": merged_pr,
        "worktree_paths": [path for _, path in paths],
        "worktree_inspections": inspections,
    }


def _local_work_indication(
    lane: dict[str, Any],
    ledger_entry: dict[str, Any] | None,
    *,
    local_work_preservation: dict[str, Any] | None = None,
) -> str | None:
    """Reason to suspect local (possibly unpushed/uncommitted) work, or None.

    Fail closed: a worktree reference alone is enough — metadata cannot
    prove that work in a worktree was pushed. The only exception is an
    explicit preservation proof for a bare worktree reference.
    """

    local_claim = _local_work_claim_indication(
        lane,
        ledger_entry,
        local_work_preservation=local_work_preservation,
    )
    if local_claim:
        return local_claim
    worktree_paths = _worktree_reference_paths(lane, ledger_entry)
    if worktree_paths:
        if _proof_covers_worktree_paths(local_work_preservation, worktree_paths):
            return None
        return f"{worktree_paths[0][0]} references a worktree path"
    return None


def assess_owner_liveness(
    lane: dict[str, Any],
    *,
    ledger_entry: dict[str, Any] | None = None,
    heartbeat: dict[str, Any] | None = None,
    now: datetime | None = None,
    stale_hours: float = STALE_HOURS_DEFAULT,
    local_work_preservation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Advisory-only owner-lease liveness assessment (issue #8318).

    Returns a dict with ``owner_liveness``, ``stale_claim_advisory``
    and ``advisory_withheld`` keys, merged additively into the JSON
    output. Pure visibility: this may reconcile displayed owner-state
    labels when a current lease proves a live owner, but it never
    authorizes cleanup or stale-claim override by itself.
    ``owner_liveness.assessed`` uses ``stale_hours`` for lane-lease
    age. The legacy ``liveness_state`` field is computed earlier from
    direct process / harness-heartbeat evidence and may still report a
    missing or stale heartbeat; callers should use the aligned
    cleanup/action fields for operator routing.
    ``assessed == "unknown"`` NEVER produces an advisory, and any hint
    of local work withholds it
    (``advisory_withheld: "possible_unpushed_work"``).
    """

    now_dt = now or datetime.now(timezone.utc)
    threshold_seconds = max(0.0, stale_hours) * 3600.0

    # lane_status: the lane ledger's view of the owning lane. When no ledger
    # exists, a terminal registry status is still enough to avoid treating the
    # row as an active owner lease.
    lane_status = "unknown"
    registry_status = str(lane.get("status") or "").strip().lower()
    if ledger_entry is not None:
        lane_status = str(ledger_entry.get("status") or "").strip().lower() or "unknown"
    elif registry_status in COMPLETED_STATUSES:
        lane_status = registry_status

    # last_heartbeat_at: matched heartbeat row first, then owner record,
    # then ledger heartbeat fields; null when nothing carries one.
    last_heartbeat_at: str | None = None
    heartbeat_terminal = bool(
        heartbeat
        and (
            heartbeat.get("terminal") is True
            or heartbeat.get("terminal_outcome")
            or heartbeat.get("terminal_finalized_at")
        )
    )
    terminal_heartbeat_outcome = (
        str(heartbeat.get("terminal_outcome") or "") if heartbeat_terminal and heartbeat else ""
    )
    terminal_heartbeat_at = (
        str(heartbeat.get("terminal_finalized_at") or "")
        if heartbeat_terminal and heartbeat
        else ""
    )
    if heartbeat_terminal:
        last_heartbeat_at = None
    elif heartbeat and heartbeat.get("last_seen_at"):
        last_heartbeat_at = str(heartbeat["last_seen_at"])
    elif lane.get("last_heartbeat_at"):
        last_heartbeat_at = str(lane["last_heartbeat_at"])
    elif ledger_entry is not None:
        for key in ("heartbeat_at", "last_heartbeat_at"):
            if ledger_entry.get(key):
                last_heartbeat_at = str(ledger_entry[key])
                break

    # Lease anchor: the most recent timestamp across the owner record,
    # the matched heartbeat, and the ledger entry. Conservative — any
    # recent signal keeps the owner "live".
    owner_timestamp_keys: tuple[str, ...] = _OWNER_RECORD_TIMESTAMP_KEYS
    ledger_timestamp_keys: tuple[str, ...] = _LEDGER_TIMESTAMP_KEYS
    if heartbeat_terminal:
        owner_timestamp_keys = tuple(
            key for key in _OWNER_RECORD_TIMESTAMP_KEYS if key != "last_heartbeat_at"
        )
        ledger_timestamp_keys = tuple(
            key
            for key in _LEDGER_TIMESTAMP_KEYS
            if key not in {"heartbeat_at", "last_heartbeat_at"}
        )
    candidates = [_updated_at_timestamp(lane.get(key)) for key in owner_timestamp_keys]
    if last_heartbeat_at:
        candidates.append(_updated_at_timestamp(last_heartbeat_at))
    if ledger_entry is not None:
        candidates.append(
            max(_updated_at_timestamp(ledger_entry.get(key)) for key in ledger_timestamp_keys)
        )
    anchor_ts = max(candidates)

    lease_age_seconds: int | None = None
    if anchor_ts > 0.0:
        lease_age_seconds = max(0, int(now_dt.timestamp() - anchor_ts))

    heartbeat_recent = False
    heartbeat_ts = _updated_at_timestamp(last_heartbeat_at) if last_heartbeat_at else 0.0
    if heartbeat_ts > 0.0:
        heartbeat_recent = (now_dt.timestamp() - heartbeat_ts) <= threshold_seconds

    if lane_status in TERMINAL_LANE_STATUSES:
        assessed = "terminal"
    elif lease_age_seconds is None:
        assessed = "unknown"
    elif lease_age_seconds <= threshold_seconds or heartbeat_recent:
        assessed = "live"
    else:
        assessed = "stale"

    owner_liveness = {
        "lease_age_seconds": lease_age_seconds,
        "last_heartbeat_at": last_heartbeat_at,
        "terminal_heartbeat_outcome": terminal_heartbeat_outcome or None,
        "terminal_heartbeat_at": terminal_heartbeat_at or None,
        "lane_status": lane_status,
        "assessed": assessed,
        "stale_threshold_hours": stale_hours,
    }

    advisory: dict[str, Any] | None = None
    advisory_withheld: str | None = None
    if assessed in ("stale", "terminal"):
        indication = _local_work_indication(
            lane,
            ledger_entry,
            local_work_preservation=local_work_preservation,
        )
        if indication is not None:
            # Fail closed: possible unpushed/uncommitted work → no
            # advisory; escalate to an operator instead.
            advisory_withheld = ADVISORY_WITHHELD_UNPUSHED
        else:
            conditions: list[str] = []
            if assessed == "terminal":
                conditions.append(f"lane_status={lane_status} is terminal in the lane ledger")
            else:
                conditions.append(
                    f"lease_age_seconds={lease_age_seconds} exceeds stale threshold "
                    f"of {stale_hours}h"
                )
                conditions.append("no heartbeat newer than the stale window")
            if _worktree_reference_paths(lane, ledger_entry):
                method = (
                    (local_work_preservation or {}).get("upstream_preservation", {}).get("method")
                )
                conditions.append(
                    "recorded worktree reference is absent/noop and preserved upstream"
                    + (f" via {method}" if method else "")
                )
            else:
                conditions.append("no worktree or local-work claim on the owner record")
            advisory = {
                "available": True,
                "protocol": STALE_CLAIM_PROTOCOL,
                "conditions_met": conditions,
                "required_ledger_record": REQUIRED_LEDGER_RECORD,
            }

    if assessed == "live":
        owner_blocking_state = OWNER_BLOCKING_LIVE
        owner_blocking_state_reason = "owner has current lease or heartbeat evidence"
    elif assessed == "unknown":
        owner_blocking_state = OWNER_BLOCKING_UNKNOWN
        owner_blocking_state_reason = "owner lease age could not be established"
    elif (
        assessed == "terminal"
        and advisory is not None
        and advisory.get("available") is True
        and advisory_withheld is None
    ):
        owner_blocking_state = OWNER_BLOCKING_STALE_TERMINAL
        owner_blocking_state_reason = (
            "terminal stale owner has no local-work claim and is eligible for guarded "
            "stale-claim handling"
        )
    else:
        owner_blocking_state = OWNER_BLOCKING_STALE
        if advisory_withheld:
            owner_blocking_state_reason = (
                f"stale owner remains blocking because advisory is withheld: {advisory_withheld}"
            )
        else:
            owner_blocking_state_reason = "stale owner is not proven terminal-safe"

    return {
        "owner_liveness": owner_liveness,
        "owner_blocking_state": owner_blocking_state,
        "owner_blocking_state_reason": owner_blocking_state_reason,
        "owner_liveness_precedence": (
            "owner_blocking_state controls dispatch/reassignment; cleanup_state and "
            "recommended_operator_action control mutation/cleanup"
        ),
        "stale_claim_advisory": advisory,
        "advisory_withheld": advisory_withheld,
        "local_work_preservation": local_work_preservation,
    }


def _print_liveness_summary(payload: dict[str, Any]) -> None:
    """Single plain-text summary line for the liveness assessment."""

    liveness = payload["owner_liveness"]
    if payload.get("stale_claim_advisory"):
        advisory = "available"
    elif payload.get("advisory_withheld"):
        advisory = f"withheld ({payload['advisory_withheld']})"
    else:
        advisory = "none"
    lease = liveness["lease_age_seconds"]
    print(
        "owner_liveness: "
        f"assessed={liveness['assessed']} "
        f"owner_blocking_state={payload['owner_blocking_state']} "
        f"lease_age_seconds={lease if lease is not None else '-'} "
        f"lane_status={liveness['lane_status']} "
        f"last_heartbeat_at={liveness['last_heartbeat_at'] or '-'} "
        f"stale_claim_advisory={advisory}"
    )


def _align_owner_state_with_liveness(payload: dict[str, Any]) -> None:
    """Keep legacy owner fields truthful after adding advisory liveness.

    ``build_owner_info`` predates the richer liveness assessment and can only
    classify direct process/heartbeat evidence. The later ``owner_liveness``
    pass also considers current lease timestamps and lane-ledger state. When
    that pass proves a live owner but direct heartbeat evidence is missing or
    stale, keep the conservative cleanup/action guidance while clarifying that
    the lane has current owner-lease evidence.
    """

    liveness = payload.get("owner_liveness") or {}
    if (
        payload.get("owner_state") != "owned"
        or payload.get("owner_blocking_state") != OWNER_BLOCKING_LIVE
        or liveness.get("assessed") != "live"
    ):
        payload["owner_liveness_alignment"] = {
            "applied": False,
            "dispatch_field": "owner_blocking_state",
            "cleanup_field": "cleanup_state",
            "action_field": "recommended_operator_action",
            "reason": "owner lease did not prove a live owner needing legacy-field alignment",
        }
        return

    liveness_state = str(payload.get("liveness_state") or "")
    if liveness_state == "missing_heartbeat":
        payload["owner_state_reason"] = (
            "active lane has current owner lease evidence but no matched harness heartbeat row"
        )
    elif liveness_state == "stale_heartbeat":
        payload["owner_state_reason"] = (
            "active lane has current owner lease evidence but matched harness heartbeat is stale"
        )
    else:
        payload["owner_liveness_alignment"] = {
            "applied": False,
            "dispatch_field": "owner_blocking_state",
            "cleanup_field": "cleanup_state",
            "action_field": "recommended_operator_action",
            "reason": "legacy liveness_state already carries current heartbeat or process evidence",
        }
        return

    payload["owner_liveness_alignment"] = {
        "applied": True,
        "dispatch_field": "owner_blocking_state",
        "dispatch_value": payload.get("owner_blocking_state"),
        "cleanup_field": "cleanup_state",
        "cleanup_value": payload.get("cleanup_state"),
        "action_field": "recommended_operator_action",
        "action_value": payload.get("recommended_operator_action"),
        "legacy_liveness_state": liveness_state,
        "lease_assessment": liveness.get("assessed"),
        "reason": (
            "dispatch/reassignment follows live owner lease evidence; mutation/cleanup "
            "keeps conservative heartbeat-derived guidance"
        ),
    }


def owner_info_with_aligned_liveness(
    info: LaneOwnerInfo, liveness_payload: dict[str, Any] | None
) -> tuple[LaneOwnerInfo, dict[str, Any]]:
    """Return display-ready owner fields after liveness alignment.

    Direct library consumers should use this helper after combining
    ``build_owner_info`` with ``assess_owner_liveness``; otherwise they can
    produce a raw merge that lacks the same precedence/alignment metadata as
    the CLI JSON output.
    """

    payload = dataclasses.asdict(info)
    if liveness_payload is not None:
        payload.update(liveness_payload)
        _align_owner_state_with_liveness(payload)

    aligned_info = dataclasses.replace(
        info,
        cleanup_state=payload["cleanup_state"],
        owner_state_reason=payload["owner_state_reason"],
        recommended_operator_action=payload["recommended_operator_action"],
    )
    return aligned_info, payload


def _info_with_aligned_owner_state(
    info: LaneOwnerInfo, liveness_payload: dict[str, Any] | None
) -> tuple[LaneOwnerInfo, dict[str, Any]]:
    """Compatibility wrapper for the public alignment helper."""

    return owner_info_with_aligned_liveness(info, liveness_payload)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _glyph(found: bool) -> str:
    return "✓" if found else "✗"


def _print_human(info: LaneOwnerInfo) -> None:
    print(f"lane_id:        {info.lane_id}")
    print(f"owner_session:  {info.owner_session or '(none)'}")
    print(f"source:         {info.source or '(unspecified)'}")
    print(f"status:         {info.status or '(unspecified)'}")
    print(f"owner_state:    {info.owner_state}")
    print(f"liveness_state: {info.liveness_state}")
    print(f"cleanup_state:  {info.cleanup_state}")
    print(f"owner_reason:   {info.owner_state_reason}")
    print(f"recommended_action: {info.recommended_operator_action}")
    print(f"branch:         {info.branch or '-'}")
    print(f"worktree:       {info.worktree or '-'}")
    print(f"pr_number:      {info.pr_number if info.pr_number is not None else '-'}")
    print(f"goal:           {info.goal or '-'}")
    print(f"updated_at:     {info.updated_at or '-'}")
    print()
    print("self-supplied identity fields:")
    print(f"  codex_thread_id:    {info.codex_thread_id or '(not supplied)'}")
    print(f"  codex_rollout_path: {info.codex_rollout_path or '(not supplied)'}")
    print(f"  desktop_label:      {info.desktop_label or '(not supplied)'}")
    print(f"  session_title:      {info.session_title or '(not supplied)'}")
    print(f"  contact_method:     {info.contact_method or '(not supplied)'}")
    print(f"  contact_payload:    {info.contact_payload or '-'}")
    print(f"  last_mailbox_check: {info.last_mailbox_check_at or '-'}")
    print(f"  last_delivery_at:   {info.last_delivery_at or '-'}")
    print(f"  last_ack_at:        {info.last_ack_at or '-'}")
    print(f"  last_heartbeat_at:  {info.last_heartbeat_at or '-'}")
    print(f"  last_steering_outcome: {info.last_steering_outcome or '-'}")
    print()
    print("best-effort live lookups:")
    print(f"  live_process:   {_glyph(info.live_process.get('found', False))}  {info.live_process}")
    print(f"  codex_thread:   {_glyph(info.codex_thread.get('found', False))}  {info.codex_thread}")
    print(
        f"  claude_session: {_glyph(info.claude_session.get('found', False))}  {info.claude_session}"
    )
    print(
        f"  factory_droid:  {_glyph(info.factory_droid.get('found', False))}  {info.factory_droid}"
    )
    print()
    print(f"steering_inbox_path:   {info.steering_inbox_path}")
    print(f"pending_message_count: {info.pending_message_count}")
    print(f"read_receipt_count:    {info.read_receipt_count}")
    print(f"unread_message_count:  {info.unread_message_count}")
    print(f"latest_read_receipt:   {info.latest_read_receipt or '-'}")
    print(f"latest_heartbeat:      {info.latest_heartbeat or '-'}")
    print(f"mailbox_dispatchable:  {info.mailbox_dispatchable}")
    print(f"live_prompt_dispatchable: {info.live_prompt_dispatchable}")
    print(f"dispatchable:          {info.dispatchable}")
    print(f"dispatch_blocker:      {info.dispatch_blocker or '-'}")
    print(f"steering_command:      {info.steering_command or '-'}")
    print(f"harness_confidence:    {info.harness_confidence}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="identify_lane_owner.py",
        description=(
            "Read-only consolidator that answers 'who owns this lane?' by "
            "joining the agent_bridge lane registry with live process, "
            "Codex rollout, Claude project, and Factory Droid signals."
        ),
    )
    p.add_argument("--lane-id", help="Exact match on LaneRecord.lane_id.")
    p.add_argument("--pr", type=int, help="Match on LaneRecord.pr_number.")
    p.add_argument("--branch", help="Exact match on LaneRecord.branch.")
    p.add_argument("--worktree", help="Exact match on LaneRecord.worktree (path-normalised).")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of human table.")
    p.add_argument(
        "--registry-path",
        type=Path,
        default=LANE_REGISTRY_DEFAULT,
        help="Override path to lanes.json (used by tests).",
    )
    p.add_argument(
        "--codex-sessions-root",
        type=Path,
        default=CODEX_SESSIONS_ROOT_DEFAULT,
        help="Override path to ~/.codex/sessions (used by tests).",
    )
    p.add_argument(
        "--claude-projects-root",
        type=Path,
        default=CLAUDE_PROJECTS_ROOT_DEFAULT,
        help="Override path to ~/.claude/projects (used by tests).",
    )
    p.add_argument(
        "--factory-bg-path",
        type=Path,
        default=FACTORY_BG_PROCESSES_DEFAULT,
        help="Override path to ~/.factory/background-processes.json (used by tests).",
    )
    p.add_argument(
        "--steering-inbox-root",
        type=Path,
        default=STEERING_INBOX_ROOT_DEFAULT,
        help="Override path to .aragora/operator-steering (used by tests).",
    )
    p.add_argument(
        "--heartbeat-path",
        type=Path,
        default=HEARTBEATS_DEFAULT,
        help="Override path to .aragora/agent-bridge/heartbeats.json (used by tests).",
    )
    p.add_argument(
        "--stale-hours",
        type=float,
        default=STALE_HOURS_DEFAULT,
        help=(
            "Owner-lease age (hours) beyond which a lane with no fresher "
            f"heartbeat is assessed stale (default {STALE_HOURS_DEFAULT}); "
            "legacy liveness_state still reflects process/heartbeat freshness."
        ),
    )
    p.add_argument(
        "--liveness",
        dest="liveness",
        action="store_true",
        default=True,
        help="Include the advisory-only owner_liveness assessment (default).",
    )
    p.add_argument(
        "--no-liveness",
        dest="liveness",
        action="store_false",
        help="Suppress the owner_liveness assessment; output is byte-identical to pre-#8318.",
    )
    p.add_argument(
        "--runs-glob",
        default=LANE_RUNS_GLOB_DEFAULT,
        help="Glob for lane-ledger directories (.aragora/run-*/lanes; used by tests).",
    )
    p.add_argument(
        "--now",
        default=None,
        help="ISO-8601 'now' override for the liveness assessment (tests/replays).",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not any([args.lane_id, args.pr is not None, args.branch, args.worktree]):
        print(
            "ERROR: provide at least one of --lane-id / --pr / --branch / --worktree",
            file=sys.stderr,
        )
        return 2

    records = load_lane_records(args.registry_path)
    if not records:
        print(
            f"ERROR: lane registry empty or missing at {args.registry_path}",
            file=sys.stderr,
        )
        return 2

    lane = find_lane(
        records,
        lane_id=args.lane_id,
        pr=args.pr,
        branch=args.branch,
        worktree=args.worktree,
    )
    if lane is None:
        criteria = {
            k: v
            for k, v in {
                "lane_id": args.lane_id,
                "pr": args.pr,
                "branch": args.branch,
                "worktree": args.worktree,
            }.items()
            if v
        }
        print(f"ERROR: no lane matched criteria {criteria}", file=sys.stderr)
        return 1

    info = build_owner_info(
        lane,
        sessions_root=args.codex_sessions_root,
        projects_root=args.claude_projects_root,
        bg_path=args.factory_bg_path,
        steering_inbox_root=args.steering_inbox_root,
        heartbeat_path=args.heartbeat_path,
    )

    liveness_payload: dict[str, Any] | None = None
    if args.liveness:
        ledger_entry = find_lane_ledger_entry(lane, runs_glob=args.runs_glob)
        liveness_payload = assess_owner_liveness(
            lane,
            ledger_entry=ledger_entry,
            heartbeat=info.latest_heartbeat,
            now=_parse_iso_utc(args.now) if args.now else None,
            stale_hours=args.stale_hours,
        )
        if liveness_payload.get("advisory_withheld") == ADVISORY_WITHHELD_UNPUSHED:
            local_work_preservation = build_worktree_reference_preservation_proof(
                lane,
                ledger_entry=ledger_entry,
                repo_root=REPO_ROOT,
                state_root=STATE_ROOT_DEFAULT,
            )
            if local_work_preservation is not None:
                liveness_payload = assess_owner_liveness(
                    lane,
                    ledger_entry=ledger_entry,
                    heartbeat=info.latest_heartbeat,
                    now=_parse_iso_utc(args.now) if args.now else None,
                    stale_hours=args.stale_hours,
                    local_work_preservation=local_work_preservation,
                )

    output_info, payload = _info_with_aligned_owner_state(info, liveness_payload)
    dev_coordination_lease: dict[str, Any] | None = None
    if args.liveness:
        dev_coordination_lease = _check_dev_coordination_lease(lane)
        payload["dev_coordination_lease"] = dev_coordination_lease

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human(output_info)
        if dev_coordination_lease is not None:
            print(f"dev_coordination_lease: {dev_coordination_lease}")
        if liveness_payload is not None:
            _print_liveness_summary(payload)

    return 0


if __name__ == "__main__":
    sys.exit(main())
