#!/usr/bin/env python3
"""Fleet sentinel — Dead Man's Signals for the aragora agent fleet.

Steering Leverage Operating Plan v2, Pillar 6 / Phase 0.1
(docs/superpowers/plans/2026-06-10-steering-leverage-operating-plan-v2.md).

The 2026-06-10 steering audit found that every loss in the window —
publisher dead three weeks (auth_ok:false since 2026-05-18), boss metrics
silent ten days, an empty daemon plist, a 217-item outbox — shared one
shape: a cheap signal existed on disk, nothing was contracted to read it,
and the human was the only fallback reader.  This sentinel IS that
contracted reader.

Contract:
  * stdlib only; intended to run from cron/launchd every 10 minutes.
  * Each check returns ``{check, status: ok|breach|unknown, detail}``.
  * ``--json`` emits one JSON object
    ``{generated_at, checks, breaches, blind_checks}``.
  * Every run appends one line to the JSONL ledger.
  * Exit codes: 0 all ok; 1 any breach; 2 any errored/unknown check.
    Unknown takes precedence over breach — a sentinel that cannot see is
    worse than one that sees a fire.  Silence is never success.
  * A breach additionally invokes ``--notify-cmd`` (template; ``{summary}``
    placeholder is replaced with the one-line breach summary).
"""

from __future__ import annotations

import argparse
import glob as glob_module
import hashlib
import importlib.util
import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Callable

CheckResult = dict[str, Any]
SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = SCRIPTS_DIR.parent

ALL_CHECKS = (
    "publisher_status",
    "boss_metrics_heartbeat",
    "launchd_plists",
    "gh_auth",
    "checkout_invariant",
    "outbox_depth",
    "outbox_drain_progress",
    "disk_free",
    "lane_liveness",
    "stale_terminal_owner",
    "github_api_health",
    "trail_reconcile",
)
REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
STATE_PATH_ARGS = {
    "--agent-bridge-lanes": "agent_bridge_lanes",
    "--agent-heartbeats": "agent_heartbeats",
    "--operator-steering-root": "operator_steering_root",
    "--stale-terminal-owner-receipt-dir": "stale_terminal_owner_receipt_dir",
}
RESOLVER_REQUIRED_ATTRS = (
    "ACTIVE_STATUSES",
    "_annotate_terminal_safety",
    "_active_pr_lane_findings",
    "_base_merged_pr_audit_result",
    "_merged_pr_audit_blocked_reason",
    "_parse_timestamp",
    "_read_rows_checked",
    "_utc_now_iso",
)

# Branch namespaces owned by autonomous lanes; only these are eligible for the
# ledger-less orphan-branch sweep (failure class A, 2026-06-10/11: coordinator
# lanes died at setup leaving empty elves/run-* branches nobody noticed).
ORPHAN_BRANCH_PATTERNS = ("elves/*", "aragora/boss*")
LANE_TIMESTAMP_KEYS = (
    "updated_at",
    "last_heartbeat_at",
    "last_seen_at",
    "claimed_at",
    "created_at",
)
LIVE_OWNER_BLOCKERS = frozenset({"fresh_heartbeat", "live_process"})
_RESOLVER_MODULE: Any | None = None


def _canonical_repo_root(path: Path) -> Path:
    common_dir_proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if common_dir_proc.returncode == 0:
        common_dir = common_dir_proc.stdout.strip()
        if common_dir.endswith("/.git"):
            return Path(common_dir).resolve().parent

    root_proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if root_proc.returncode == 0 and root_proc.stdout.strip():
        return Path(root_proc.stdout.strip()).resolve()
    return path.resolve()


def _git_common_state_root(path: Path) -> Path | None:
    common_dir_proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if common_dir_proc.returncode != 0 or not common_dir_proc.stdout.strip():
        return None
    common_dir = Path(common_dir_proc.stdout.strip()).resolve()
    if common_dir.name == ".git":
        return common_dir.parent / ".aragora"
    for parent in common_dir.parents:
        if parent.name == ".git":
            return parent.parent / ".aragora"
    return None


def _git_toplevel(path: Path) -> Path | None:
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip()).resolve()


def _registered_worktree_roots(repo_root: Path) -> set[Path]:
    roots: set[Path] = set()
    toplevel = _git_toplevel(repo_root)
    if toplevel is not None:
        roots.add(toplevel)
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return roots
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            roots.add(Path(line.removeprefix("worktree ")).resolve())
    return roots


def _state_root_repo_candidate(state_root: Path) -> Path:
    return state_root.parent if state_root.name == ".aragora" else state_root


def _is_registered_worktree_state_root(state_root: Path, repo_root: Path) -> bool:
    candidate = _state_root_repo_candidate(state_root)
    candidate_root = _git_toplevel(candidate)
    if candidate_root is None or candidate.resolve() != candidate_root:
        return False
    return candidate_root in _registered_worktree_roots(repo_root)


def _trusted_automation_state_roots(repo_root: Path) -> set[Path]:
    roots = {
        (_canonical_repo_root(repo_root) / ".aragora").resolve(),
        (DEFAULT_REPO_ROOT / ".aragora").resolve(),
    }
    common_state_root = _git_common_state_root(repo_root)
    if common_state_root is not None:
        roots.add(common_state_root.resolve())
    return roots


def _normalize_automation_state_root(path: str) -> Path:
    root = Path(path).expanduser()
    root = root if root.name == ".aragora" else root / ".aragora"
    return root.resolve()


def _automation_state_root(repo_root: Path) -> Path:
    configured = os.environ.get("ARAGORA_AUTOMATION_STATE_ROOT")
    if configured:
        root = _normalize_automation_state_root(configured)
        trusted_roots = _trusted_automation_state_roots(repo_root)
        if root not in trusted_roots and not _is_registered_worktree_state_root(root, repo_root):
            allowed = ", ".join(str(item) for item in sorted(trusted_roots))
            raise ValueError(
                f"untrusted ARAGORA_AUTOMATION_STATE_ROOT {root}; expected one of: "
                f"{allowed}, or a registered worktree's .aragora"
            )
        return root
    return (_canonical_repo_root(repo_root) / ".aragora").resolve()


def _automation_state_root_for_defaults(repo_root: Path) -> tuple[Path, str | None]:
    try:
        return _automation_state_root(repo_root), None
    except ValueError as exc:
        # Parser construction must not crash before explicit path overrides can
        # be parsed. The stale_terminal_owner check fails closed if these
        # fallback defaults are actually used.
        return (_canonical_repo_root(repo_root) / ".aragora").resolve(), str(exc)


def _explicit_state_path_args(argv: list[str]) -> set[str]:
    explicit: set[str] = set()
    for token in argv:
        for flag, dest in STATE_PATH_ARGS.items():
            if token == flag or token.startswith(f"{flag}="):
                explicit.add(dest)
    return explicit


def _validate_repo_slug(repo_slug: str) -> str:
    slug = repo_slug.strip()
    if slug != repo_slug or not REPO_SLUG_RE.fullmatch(slug):
        raise ValueError("repo_slug must be a single GitHub owner/repo slug")
    owner, repo = slug.split("/", 1)
    if owner in {".", ".."} or repo in {".", ".."} or owner.startswith("-") or repo.startswith("-"):
        raise ValueError("repo_slug contains an unsafe owner or repository segment")
    return slug


def _validate_gh_bin(gh_bin: str) -> str:
    value = str(gh_bin)
    if value != value.strip() or any(char.isspace() for char in value) or "\0" in value:
        raise ValueError("gh_bin must be one executable token")
    if value == "gh":
        return value
    path = Path(value).expanduser()
    if not path.is_absolute() and not any(sep in value for sep in ("/", os.sep)):
        raise ValueError("gh_bin must be 'gh' or an executable path")
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise ValueError(f"gh_bin path could not be resolved: {exc}") from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError("gh_bin path must be an executable file")
    return str(resolved)


def _split_operator_command(command: str, *, option_name: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise ValueError(f"{option_name} is not a valid argv template: {exc}") from exc
    if not tokens:
        raise ValueError(f"{option_name} must not be empty")
    executable = tokens[0]
    if (
        executable.startswith("-")
        or "\0" in executable
        or any(char.isspace() for char in executable)
    ):
        raise ValueError(f"{option_name} executable must be one safe argv token")
    if any(sep in executable for sep in ("/", os.sep)):
        path = Path(executable).expanduser()
        try:
            resolved = path.resolve()
        except OSError as exc:
            raise ValueError(f"{option_name} executable path could not be resolved: {exc}") from exc
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise ValueError(f"{option_name} executable path must be an executable file")
        tokens[0] = str(resolved)
    return tokens


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (``Z`` suffix accepted) to aware UTC."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _result(check: str, status: str, detail: str) -> CheckResult:
    return {"check": check, "status": status, "detail": detail}


def _age_hours(path: Path, now: datetime) -> float:
    return (now.timestamp() - path.stat().st_mtime) / 3600.0


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Checks (each parameterized so tests inject fixtures; no live state touched)
# ---------------------------------------------------------------------------


def check_publisher_status(path: Path, *, max_age_hours: float, now: datetime) -> CheckResult:
    """Publisher status file must be fresh AND report healthy GitHub auth."""
    name = "publisher_status"
    if not path.exists():
        return _result(name, "breach", f"missing: {path} — publisher never reported")
    problems: list[str] = []
    age = _age_hours(path, now)
    if age > max_age_hours:
        problems.append(f"stale: mtime {age:.1f}h old (max {max_age_hours}h)")
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        problems.append(f"unreadable status JSON ({exc.__class__.__name__})")
        payload = {}
    health = payload.get("github_health") or {}
    if health.get("auth_ok") is not True:
        problems.append(f"github_health.auth_ok is {health.get('auth_ok')!r} (expected true)")
    generated_at = payload.get("generated_at")
    if generated_at:
        try:
            gen_age = (now - parse_iso(str(generated_at))).total_seconds() / 3600.0
            if gen_age > max_age_hours:
                problems.append(
                    f"generated_at {generated_at} is {gen_age:.0f}h old (max {max_age_hours}h)"
                )
        except ValueError:
            problems.append(f"unparseable generated_at: {generated_at!r}")
    if problems:
        return _result(name, "breach", "; ".join(problems))
    return _result(name, "ok", f"fresh ({age:.1f}h) and auth_ok")


def check_boss_metrics(path: Path, *, max_age_hours: float, now: datetime) -> CheckResult:
    """Boss metrics heartbeat: the JSONL must have been written recently."""
    name = "boss_metrics_heartbeat"
    if not path.exists():
        return _result(name, "breach", f"missing: {path} — heartbeat never written")
    age = _age_hours(path, now)
    if age > max_age_hours:
        return _result(
            name, "breach", f"heartbeat stale: mtime {age:.1f}h old (max {max_age_hours}h)"
        )
    return _result(name, "ok", f"heartbeat {age:.1f}h old")


def check_launchd_plists(launch_agents_dir: Path) -> CheckResult:
    """Every com.aragora.*.plist must be non-empty and plist-parseable.

    Motivating incident: the zero-byte boss-loop plist of 2026-06-10, which
    launchd silently refused to load while everything looked installed.
    """
    name = "launchd_plists"
    if not launch_agents_dir.is_dir():
        return _result(name, "ok", f"no LaunchAgents dir at {launch_agents_dir}")
    bad: list[str] = []
    plists = sorted(launch_agents_dir.glob("com.aragora.*.plist"))
    for plist in plists:
        if plist.stat().st_size == 0:
            bad.append(f"{plist.name}: zero-byte")
            continue
        try:
            with plist.open("rb") as fh:
                plistlib.load(fh)
        except Exception as exc:  # noqa: BLE001 - plistlib raises various types
            bad.append(f"{plist.name}: unparseable ({exc.__class__.__name__})")
    if bad:
        return _result(name, "breach", "; ".join(bad))
    return _result(name, "ok", f"{len(plists)} aragora plist(s) valid")


def _default_command_runner(cmd: list[str]) -> int:
    proc = subprocess.run(  # noqa: S603 - operator-configured command
        cmd, capture_output=True, text=True, timeout=60
    )
    return proc.returncode


def check_gh_auth(
    *, runner: Callable[[list[str]], int], cmd: list[str] | None = None
) -> CheckResult:
    """``gh auth status`` must exit zero — the publisher dies without it."""
    name = "gh_auth"
    command = cmd or ["gh", "auth", "status"]
    try:
        rc = runner(command)
    except Exception as exc:  # noqa: BLE001 - any runner failure means we are blind
        return _result(
            name, "unknown", f"could not run {command[0]}: {exc.__class__.__name__}: {exc}"
        )
    if rc != 0:
        return _result(name, "breach", f"{' '.join(command)} exited {rc}")
    return _result(name, "ok", "gh auth healthy")


def _default_branch_reader(repo: Path) -> str:
    proc = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "branch", "--show-current"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return proc.stdout.strip()


def check_checkout_invariant(repo: Path, *, branch_reader: Callable[[Path], str]) -> CheckResult:
    """The root checkout must stay on main (worktrees carry branches)."""
    name = "checkout_invariant"
    try:
        branch = branch_reader(repo)
    except Exception as exc:  # noqa: BLE001 - git failure means we are blind
        return _result(name, "unknown", f"could not read branch: {exc.__class__.__name__}: {exc}")
    if branch != "main":
        return _result(name, "breach", f"root checkout {repo} is on {branch!r}, not main")
    return _result(name, "ok", "root checkout on main")


def check_outbox(
    outbox_dir: Path, *, max_items: int, max_age_days: float, now: datetime
) -> CheckResult:
    """Outbox depth and oldest-item age (archive/ excluded)."""
    name = "outbox_depth"
    if not outbox_dir.is_dir():
        result = _result(name, "ok", f"no outbox dir at {outbox_dir}")
        result["depth"] = 0
        result["fingerprint"] = _outbox_fingerprint([])
        return result
    items = sorted(p for p in outbox_dir.glob("*.json") if p.is_file())
    fingerprint = _outbox_fingerprint(items)
    problems: list[str] = []
    if len(items) > max_items:
        problems.append(f"{len(items)} items queued (max {max_items})")
    if items:
        oldest = min(items, key=lambda p: p.stat().st_mtime)
        oldest_days = _age_hours(oldest, now) / 24.0
        if oldest_days > max_age_days:
            problems.append(
                f"{len(items)} item(s) queued; oldest item {oldest.name} is "
                f"{oldest_days:.1f}d old (max {max_age_days}d)"
            )
    if problems:
        result = _result(name, "breach", "; ".join(problems))
        result["depth"] = len(items)
        result["fingerprint"] = fingerprint
        return result
    result = _result(name, "ok", f"{len(items)} item(s) queued")
    result["depth"] = len(items)
    result["fingerprint"] = fingerprint
    return result


def _outbox_fingerprint(items: list[Path]) -> str:
    digest = hashlib.sha256()
    for item in sorted(items, key=lambda p: p.name):
        digest.update(item.name.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
    return digest.hexdigest()


def _extract_outbox_depth(check: dict[str, Any]) -> int | None:
    depth = check.get("depth")
    if isinstance(depth, int) and depth >= 0:
        return depth
    if isinstance(depth, float) and depth.is_integer() and depth >= 0:
        return int(depth)
    match = re.search(r"(\d+)\s+item", str(check.get("detail") or ""))
    if match:
        return int(match.group(1))
    return None


def _extract_outbox_fingerprint(check: dict[str, Any]) -> str | None:
    fingerprint = check.get("fingerprint")
    if isinstance(fingerprint, str) and fingerprint:
        return fingerprint
    return None


def _extract_outbox_sample(checks: Any) -> tuple[int | None, str | None]:
    for check in checks or []:
        if isinstance(check, dict) and check.get("check") == "outbox_depth":
            return _extract_outbox_depth(check), _extract_outbox_fingerprint(check)
    return None, None


def check_outbox_drain_progress(
    ledger: Path,
    outbox_dir: Path,
    *,
    stall_cycles: int,
    min_floor: int,
) -> CheckResult:
    """Circuit-breaker: flag an outbox that stays congested without draining.

    A drain/conductor loop that keeps running but never reduces the outbox is
    making no net depth progress — the molasses failure mode in
    ``docs/AGENT_OPERATING_CONTRACT.md`` §Conductor (observed June 2026: an outbox
    stuck at its ceiling for ~9 days while the loop only re-messaged stale lanes).
    When the live outbox is at/above ``min_floor`` and the last ``stall_cycles``
    ledger entries show no net decrease from the first observed depth and the
    live depth has not decreased from the previous cycle, breach so the loop
    halts and escalates to the operator instead of mailing more dead letters.
    """
    name = "outbox_drain_progress"
    if stall_cycles < 1:
        return _result(name, "unknown", f"invalid stall cycle count {stall_cycles}; must be >= 1")
    current_items = (
        sorted(p for p in outbox_dir.glob("*.json") if p.is_file()) if outbox_dir.is_dir() else []
    )
    current = len(current_items)
    current_fingerprint = _outbox_fingerprint(current_items)
    if current < min_floor:
        return _result(name, "ok", f"outbox depth {current} below floor {min_floor}")
    if not ledger.exists():
        return _result(name, "ok", f"no ledger history at {ledger}; cannot assess drain")
    samples: list[tuple[int | None, str | None]] = []
    for line in _read_tail_lines(ledger, stall_cycles + 4):
        try:
            entry = json.loads(line)
        except (ValueError, TypeError):
            samples.append((None, None))
            continue
        if not isinstance(entry, dict):
            samples.append((None, None))
            continue
        samples.append(_extract_outbox_sample(entry.get("checks")))
    if len(samples) < stall_cycles:
        usable = sum(1 for depth, _fingerprint in samples if depth is not None)
        return _result(
            name, "ok", f"only {usable} prior cycle(s); need {stall_cycles} to assess drain"
        )
    recent_samples = samples[-stall_cycles:]
    if any(depth is None for depth, _fingerprint in recent_samples):
        usable = sum(1 for depth, _fingerprint in recent_samples if depth is not None)
        return _result(
            name,
            "unknown",
            f"only {usable} usable outbox_depth sample(s) in the last {stall_cycles} ledger cycle(s); cannot assess drain",
        )
    window = [depth for depth, _fingerprint in recent_samples if depth is not None]
    series = [*window, current]
    congested = all(depth >= min_floor for depth in series)
    not_draining = current >= window[-1] and current >= window[0]
    fingerprints = [fingerprint for _depth, fingerprint in recent_samples] + [current_fingerprint]
    if congested and not_draining and any(not fingerprint for fingerprint in fingerprints):
        return _result(
            name,
            "unknown",
            "outbox depth did not improve, but recent ledger samples lack item fingerprints; cannot distinguish backlog stall from saturated throughput",
        )
    fingerprint_changed = len(set(fingerprints)) > 1
    if congested and not_draining and fingerprint_changed:
        return _result(
            name,
            "ok",
            f"outbox depth stayed high but item fingerprint changed (recent depths {window}, now {current}); drain loop has throughput",
        )
    if congested and not_draining:
        return _result(
            name,
            "breach",
            f"outbox not draining: net depth {window[0]}->{current} stayed at/above {min_floor} "
            f"across {stall_cycles} prior cycles plus live depth and item fingerprint did not change — "
            "the drain loop is making no net backlog progress; HALT it and escalate to the operator, "
            "do not keep re-messaging stale lanes (§Conductor dead-letter ban)",
        )
    return _result(
        name, "ok", f"outbox draining or fluctuating (recent depths {window}, now {current})"
    )


def check_disk_free(
    path: Path, *, min_free_gib: float, usage_fn: Callable[[Path], Any] = shutil.disk_usage
) -> CheckResult:
    name = "disk_free"
    try:
        usage = usage_fn(path)
    except OSError as exc:
        return _result(name, "unknown", f"disk_usage failed: {exc}")
    free_gib = usage.free / 2**30
    if free_gib < min_free_gib:
        return _result(name, "breach", f"{free_gib:.1f} GiB free (min {min_free_gib} GiB)")
    return _result(name, "ok", f"{free_gib:.1f} GiB free")


# ---------------------------------------------------------------------------
# lane_liveness (failure class A — silent lane death, 2026-06-10/11)
# ---------------------------------------------------------------------------


def _default_remote_heads(repo: Path) -> dict[str, str]:
    """``git ls-remote --heads origin`` → ``{branch: sha}``."""
    proc = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "ls-remote", "--heads", "origin"],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    heads: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        prefix = "refs/heads/"
        if ref.startswith(prefix):
            heads[ref[len(prefix) :].strip()] = sha.strip()
    return heads


def _default_ahead_counter(repo: Path) -> Callable[[str], int | None]:
    """Commits ahead of origin/main for a sha; None when unresolvable.

    A zero-ahead branch tip is by definition an ancestor of origin/main and
    therefore present locally once origin/main is fetched.  An unresolvable
    sha thus means the branch carries unfetched unique commits — callers must
    treat None as "has commits" (never as empty).
    """

    def count(sha: str) -> int | None:
        proc = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo), "rev-list", "--count", f"origin/main..{sha}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            return None
        try:
            return int(proc.stdout.strip())
        except ValueError:
            return None

    return count


def _default_commit_dater(repo: Path) -> Callable[[str], datetime | None]:
    def commit_date(sha: str) -> datetime | None:
        proc = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo), "log", "-1", "--format=%cI", sha],
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = proc.stdout.strip()
        if proc.returncode != 0 or not out:
            return None
        try:
            return parse_iso(out)
        except ValueError:
            return None

    return commit_date


def check_lane_liveness(
    lanes_glob: str,
    *,
    lane_max_age_hours: float,
    orphan_age_hours: float,
    now: datetime,
    remote_heads: Callable[[], dict[str, str]],
    ahead_counter: Callable[[str], int | None],
    commit_dater: Callable[[str], datetime | None],
) -> CheckResult:
    """Detect silently dead lanes and ledger-less orphan branches.

    Rule 1 (ledger): a lane-ledger entry (``.aragora/run-*/lanes/<lane>.json``)
    with ``status=in_progress``, ``launched_at`` older than
    ``lane_max_age_hours``, whose branch has zero commits ahead of origin/main
    (or is absent from origin entirely) is a dead lane — it burned its setup
    window and produced nothing durable.

    Rule 2 (orphan sweep): any origin branch matching
    ``ORPHAN_BRANCH_PATTERNS`` with zero commits ahead of origin/main whose
    tip commit is older than ``orphan_age_hours`` is an orphan — a lane died
    before its first commit and left no ledger to read.
    """
    name = "lane_liveness"
    try:
        heads = remote_heads()
    except Exception as exc:  # noqa: BLE001 - git failure means we are blind
        return _result(
            name, "unknown", f"could not list origin heads: {exc.__class__.__name__}: {exc}"
        )
    unreadable: list[str] = []
    problems: list[str] = []
    in_progress = 0
    ledger_files = sorted(glob_module.glob(str(Path(lanes_glob) / "*.json")))
    for ledger_file in ledger_files:
        try:
            entry = json.loads(Path(ledger_file).read_text())
            lane = str(entry["lane"])
            raw_status = entry.get("status") or entry.get("state")
            if raw_status is None:
                raise KeyError("status")
            status = str(raw_status)
            if status != "in_progress":
                continue
            raw_launched_at = entry.get("launched_at") or entry.get("started_at")
            if raw_launched_at is None:
                raise KeyError("launched_at")
            launched_at = parse_iso(str(raw_launched_at))
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            unreadable.append(f"{ledger_file} ({exc.__class__.__name__})")
            continue
        in_progress += 1
        age_hours = (now - launched_at).total_seconds() / 3600.0
        if age_hours <= lane_max_age_hours:
            continue
        branch = str(entry.get("branch", ""))
        sha = heads.get(branch)
        if sha is None:
            problems.append(
                f"lane {lane}: in_progress {age_hours:.1f}h (max {lane_max_age_hours}h), "
                f"branch {branch} absent from origin"
            )
            continue
        if ahead_counter(sha) == 0:
            problems.append(
                f"lane {lane}: in_progress {age_hours:.1f}h (max {lane_max_age_hours}h), "
                f"branch {branch} has zero commits ahead of origin/main"
            )
    if unreadable:
        return _result(name, "unknown", "unreadable lane ledger(s): " + "; ".join(unreadable))
    pattern_branches = 0
    for branch in sorted(heads):
        if not any(fnmatch(branch, pat) for pat in ORPHAN_BRANCH_PATTERNS):
            continue
        pattern_branches += 1
        if ahead_counter(heads[branch]) != 0:
            continue
        tip_date = commit_dater(heads[branch])
        if tip_date is None:
            continue
        tip_age_hours = (now - tip_date).total_seconds() / 3600.0
        if tip_age_hours > orphan_age_hours:
            problems.append(
                f"orphan branch {branch}: zero commits ahead of origin/main, "
                f"tip {tip_age_hours / 24:.1f}d old (max {orphan_age_hours}h) — "
                "lane likely died at setup; no ledger claims it"
            )
    if problems:
        return _result(name, "breach", "; ".join(problems))
    return _result(
        name,
        "ok",
        f"{in_progress} in_progress lane(s) live; "
        f"{pattern_branches} lane-pattern branch(es) on origin, no orphans",
    )


# ---------------------------------------------------------------------------
# stale_terminal_owner (#8562 — stale lane owners blocking terminal PRs)
# ---------------------------------------------------------------------------


def _read_json_list(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return [], "missing"
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"{exc.__class__.__name__}: {exc}"
    if not isinstance(payload, list):
        return [], "invalid_shape:not_list"
    return [row for row in payload if isinstance(row, dict)], None


def _latest_lane_timestamp(row: dict[str, Any]) -> datetime | None:
    parsed: list[datetime] = []
    for key in LANE_TIMESTAMP_KEYS:
        raw = str(row.get(key) or "").strip()
        if not raw:
            continue
        try:
            parsed.append(parse_iso(raw))
        except ValueError:
            continue
    return max(parsed) if parsed else None


def _merge_commit_oid(payload: dict[str, Any]) -> str:
    value = payload.get("mergeCommit") or payload.get("merge_commit")
    if isinstance(value, dict):
        return str(value.get("oid") or value.get("sha") or "")
    return str(value or "")


def _default_pr_state_fetcher(
    pr: int,
    *,
    repo_slug: str,
    gh_bin: str,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    try:
        safe_gh_bin = _validate_gh_bin(gh_bin)
        safe_repo_slug = _validate_repo_slug(repo_slug)
    except ValueError as exc:
        return {
            "available": False,
            "number": pr,
            "state": "UNKNOWN",
            "error": f"invalid GitHub CLI configuration: {exc}",
            "command": [],
        }
    cmd = [
        safe_gh_bin,
        "pr",
        "view",
        str(pr),
        "--repo",
        safe_repo_slug,
        "--json",
        "number,state,closed,closedAt,mergedAt,mergeCommit,headRefName,headRefOid,url",
    ]
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": False,
            "number": pr,
            "state": "UNKNOWN",
            "error": f"{exc.__class__.__name__}: {exc}",
            "command": cmd,
        }
    if proc.returncode != 0:
        return {
            "available": False,
            "number": pr,
            "state": "UNKNOWN",
            "error": proc.stderr.strip() or proc.stdout.strip(),
            "command": cmd,
        }
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "number": pr,
            "state": "UNKNOWN",
            "error": f"invalid gh json: {exc}",
            "command": cmd,
        }
    return {
        "available": True,
        "number": _coerce_int(payload.get("number")) or pr,
        "state": str(payload.get("state") or "").upper(),
        "closed_at": payload.get("closedAt"),
        "merged_at": payload.get("mergedAt"),
        "merge_commit": _merge_commit_oid(payload),
        "head_sha": str(payload.get("headRefOid") or ""),
        "branch": str(payload.get("headRefName") or ""),
        "url": str(payload.get("url") or ""),
    }


def _trusted_resolver_path() -> Path:
    script_path = SCRIPTS_DIR / "resolve_lane_conflicts.py"
    try:
        resolved = script_path.resolve(strict=True)
        trusted_scripts_dir = SCRIPTS_DIR.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"could not resolve trusted resolver path: {exc}") from exc
    expected_scripts_dir = (DEFAULT_REPO_ROOT / "scripts").resolve()
    if trusted_scripts_dir != expected_scripts_dir:
        raise RuntimeError(
            "fleet sentinel scripts directory does not match canonical repo scripts directory: "
            f"{trusted_scripts_dir} != {expected_scripts_dir}"
        )
    if resolved.parent != trusted_scripts_dir or resolved.name != "resolve_lane_conflicts.py":
        raise RuntimeError(f"untrusted resolver module path: {resolved}")
    return resolved


def _validate_resolver_module(module: Any, script_path: Path) -> None:
    missing = [name for name in RESOLVER_REQUIRED_ATTRS if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            f"resolver module at {script_path} is missing required attrs: {', '.join(missing)}"
        )


def _load_resolver_module() -> Any:
    global _RESOLVER_MODULE
    if _RESOLVER_MODULE is not None:
        return _RESOLVER_MODULE
    script_path = _trusted_resolver_path()
    spec = importlib.util.spec_from_file_location(
        "resolve_lane_conflicts_for_sentinel", script_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load resolver module at {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _validate_resolver_module(module, script_path)
    _RESOLVER_MODULE = module
    return module


def _active_lane_statuses() -> set[str]:
    return set(getattr(_load_resolver_module(), "ACTIVE_STATUSES"))


def _default_terminal_owner_auditor(
    *,
    pr: int,
    github_state: dict[str, Any],
    registry_path: Path,
    receipt_dir: Path,
    gh_bin: str,
    heartbeat_path: Path,
    steering_inbox_root: Path,
    heartbeat_fresh_seconds: int,
) -> dict[str, Any]:
    resolver = _load_resolver_module()
    resolved_at = resolver._utc_now_iso()
    now_ts = resolver._parse_timestamp(resolved_at)
    github_state = dict(github_state)
    if "mergeCommit" not in github_state and github_state.get("merge_commit"):
        github_state["mergeCommit"] = github_state["merge_commit"]
    rows, row_load_error = resolver._read_rows_checked(registry_path)
    heartbeats, heartbeat_load_error = resolver._read_rows_checked(heartbeat_path)
    findings: list[dict[str, Any]] = []
    blocked_reason = ""
    if row_load_error:
        blocked_reason = f"lane_registry_unreadable:{row_load_error}"
    elif github_state.get("available") is True and github_state.get("state") == "MERGED":
        raw_findings = resolver._active_pr_lane_findings(rows, pr=pr)
        if heartbeat_fresh_seconds < 0:
            findings = []
            for finding in raw_findings:
                finding = dict(finding)
                finding["terminal_safety_blockers"] = ["invalid_heartbeat_fresh_seconds"]
                finding["terminal_safety_details"] = {
                    "heartbeat_fresh_seconds": heartbeat_fresh_seconds
                }
                finding["apply_safe"] = False
                findings.append(finding)
        else:
            findings = resolver._annotate_terminal_safety(
                raw_findings,
                heartbeats=heartbeats,
                heartbeat_load_error=heartbeat_load_error,
                steering_inbox_root=steering_inbox_root,
                now_ts=now_ts,
                heartbeat_fresh_seconds=heartbeat_fresh_seconds,
            )
    if not blocked_reason:
        blocked_reason = resolver._merged_pr_audit_blocked_reason(
            apply=False,
            operator_authorized=False,
            expected_merge_commit=None,
            expected_closed_at=None,
            expected_head_sha=None,
            github_state=github_state,
            findings=findings,
        )
    return resolver._base_merged_pr_audit_result(
        registry_path=registry_path,
        receipt_dir=receipt_dir,
        pr=pr,
        apply=False,
        operator_authorized=False,
        expected_merge_commit=None,
        expected_closed_at=None,
        expected_head_sha=None,
        github_state=github_state,
        findings=findings,
        blocked_reason=blocked_reason,
        heartbeat_path=heartbeat_path,
        steering_inbox_root=steering_inbox_root,
        heartbeat_fresh_seconds=heartbeat_fresh_seconds,
    )


def _reconciler_dry_run_command(
    *,
    pr: int,
    registry_path: Path,
    receipt_dir: Path,
    heartbeat_path: Path,
    steering_inbox_root: Path,
    heartbeat_fresh_seconds: int,
) -> str:
    return (
        "python3 scripts/resolve_lane_conflicts.py --merged-pr-lane-audit "
        f"--pr {pr} "
        f"--registry-path {shlex.quote(str(registry_path))} "
        f"--receipt-dir {shlex.quote(str(receipt_dir))} "
        f"--heartbeat-path {shlex.quote(str(heartbeat_path))} "
        f"--steering-inbox-root {shlex.quote(str(steering_inbox_root))} "
        f"--heartbeat-fresh-seconds {heartbeat_fresh_seconds} --json"
    )


def _reconciler_apply_command(
    *,
    pr: int,
    merge_commit: str,
    registry_path: Path,
    receipt_dir: Path,
    heartbeat_path: Path,
    steering_inbox_root: Path,
    heartbeat_fresh_seconds: int,
) -> str:
    return (
        "python3 scripts/resolve_lane_conflicts.py --merged-pr-lane-audit "
        f"--pr {pr} --expected-merge-commit {shlex.quote(merge_commit)} "
        "--operator-authorized "
        f"--registry-path {shlex.quote(str(registry_path))} "
        f"--receipt-dir {shlex.quote(str(receipt_dir))} "
        f"--heartbeat-path {shlex.quote(str(heartbeat_path))} "
        f"--steering-inbox-root {shlex.quote(str(steering_inbox_root))} "
        f"--heartbeat-fresh-seconds {heartbeat_fresh_seconds} --apply --json"
    )


def check_stale_terminal_owner(
    registry_path: Path,
    *,
    receipt_dir: Path,
    heartbeat_path: Path,
    steering_inbox_root: Path,
    min_age_hours: float,
    now: datetime,
    repo_slug: str,
    gh_bin: str = "gh",
    heartbeat_fresh_seconds: int = 15 * 60,
    gh_timeout_seconds: float = 30.0,
    pr_state_fetcher: Callable[..., dict[str, Any]] | None = None,
    terminal_owner_auditor: Callable[..., dict[str, Any]] | None = None,
) -> CheckResult:
    """Report stale owner rows that still block merged/closed PRs.

    This check is intentionally read-only and avoids resolver write locks.  It
    detects and routes; the only mutation path it prints is the guarded
    ``resolve_lane_conflicts.py`` apply command, and only for merged PRs where an
    exact merge commit is available.
    """
    name = "stale_terminal_owner"
    try:
        repo_slug = _validate_repo_slug(repo_slug)
        gh_bin = _validate_gh_bin(gh_bin)
    except ValueError as exc:
        return _result(name, "unknown", f"invalid GitHub CLI configuration: {exc}")

    rows, load_error = _read_json_list(registry_path)
    if load_error:
        if load_error == "missing":
            return _result(
                name,
                "ok",
                f"lane registry missing: {registry_path} — agent-bridge state absent; check skipped",
            )
        return _result(name, "unknown", f"lane registry unreadable: {load_error}")

    active_lane_statuses = _active_lane_statuses()
    stale_rows: list[dict[str, Any]] = []
    unknown_age_rows: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("status") or "") not in active_lane_statuses:
            continue
        pr = _coerce_int(row.get("pr_number"))
        if pr is None:
            continue
        latest = _latest_lane_timestamp(row)
        if latest is None:
            unknown_age_rows.append(row)
            continue
        age_hours = (now - latest).total_seconds() / 3600.0
        if age_hours >= min_age_hours:
            stale = dict(row)
            stale["_stale_age_hours"] = age_hours
            stale_rows.append(stale)

    unknown_age_detail = ""
    if unknown_age_rows:
        sample = ", ".join(
            str(row.get("lane_id") or row.get("owner_session") or row.get("pr_number"))
            for row in unknown_age_rows[:5]
        )
        unknown_age_detail = (
            f"{len(unknown_age_rows)} active PR owner row(s) have no comparable timestamp: {sample}"
        )
    if not stale_rows:
        if unknown_age_detail:
            return _result(name, "unknown", unknown_age_detail)
        return _result(name, "ok", "no stale active PR owner rows over threshold")

    if pr_state_fetcher is None:

        def fetch_state(pr: int, *, repo_slug: str, gh_bin: str) -> dict[str, Any]:
            return _default_pr_state_fetcher(
                pr,
                repo_slug=repo_slug,
                gh_bin=gh_bin,
                timeout_seconds=gh_timeout_seconds,
            )

    else:
        fetch_state = pr_state_fetcher
    audit_terminal = terminal_owner_auditor or _default_terminal_owner_auditor
    by_pr: dict[int, list[dict[str, Any]]] = {}
    for row in stale_rows:
        pr = _coerce_int(row.get("pr_number"))
        if pr is not None:
            by_pr.setdefault(pr, []).append(row)

    candidates: list[dict[str, Any]] = []
    live_suppressed: list[dict[str, Any]] = []
    unknowns: list[str] = [unknown_age_detail] if unknown_age_detail else []
    for pr, pr_rows in sorted(by_pr.items()):
        state = fetch_state(pr, repo_slug=repo_slug, gh_bin=gh_bin)
        if state.get("available") is not True:
            unknowns.append(f"PR #{pr}: {state.get('error') or 'state unavailable'}")
            continue
        terminal_state = str(state.get("state") or "").upper()
        if terminal_state not in {"MERGED", "CLOSED"}:
            continue

        audit: dict[str, Any] = {}
        findings_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        if terminal_state == "MERGED":
            audit = audit_terminal(
                pr=pr,
                github_state=state,
                registry_path=registry_path,
                receipt_dir=receipt_dir,
                gh_bin=gh_bin,
                heartbeat_path=heartbeat_path,
                steering_inbox_root=steering_inbox_root,
                heartbeat_fresh_seconds=heartbeat_fresh_seconds,
            )
            if audit.get("github_state", {}).get("available") is not True:
                unknowns.append(
                    f"PR #{pr}: reconciler audit unavailable: "
                    f"{audit.get('github_state', {}).get('error') or audit.get('blocked_reason')}"
                )
                continue
            findings_by_key = {
                (
                    str(finding.get("lane_id") or ""),
                    str(finding.get("owner_session") or ""),
                ): finding
                for finding in audit.get("findings", [])
                if isinstance(finding, dict)
            }

        for row in pr_rows:
            key = (str(row.get("lane_id") or ""), str(row.get("owner_session") or ""))
            finding = findings_by_key.get(key)
            if terminal_state == "MERGED" and finding is None:
                blockers = ["missing_reconciler_finding"]
                details = {
                    "reason": "read-only resolver audit did not return a matching active owner row"
                }
            else:
                finding = finding or {}
                blockers = list(finding.get("terminal_safety_blockers") or [])
                details = dict(finding.get("terminal_safety_details") or {})
            if terminal_state == "CLOSED":
                blockers = ["closed_pr_manual_review"]
                details = {
                    "reason": "closed-unmerged PRs are terminal but have no merge-commit guard"
                }
            candidate = {
                "lane_id": row.get("lane_id"),
                "pr_number": pr,
                "branch": row.get("branch") or state.get("branch"),
                "owner_session": row.get("owner_session"),
                "age_hours": round(float(row["_stale_age_hours"]), 2),
                "terminal_state": terminal_state,
                "terminal_url": state.get("url"),
                "merge_commit": state.get("merge_commit") or "",
                "terminal_safety_blockers": blockers,
                "terminal_safety_details": details,
                "reconciler_dry_run_command": _reconciler_dry_run_command(
                    pr=pr,
                    registry_path=registry_path,
                    receipt_dir=receipt_dir,
                    heartbeat_path=heartbeat_path,
                    steering_inbox_root=steering_inbox_root,
                    heartbeat_fresh_seconds=heartbeat_fresh_seconds,
                ),
                "reconciler_apply_command": "",
            }
            merge_commit = str(state.get("merge_commit") or "")
            if terminal_state == "MERGED" and not blockers and merge_commit:
                candidate["reconciler_apply_command"] = _reconciler_apply_command(
                    pr=pr,
                    merge_commit=merge_commit,
                    registry_path=registry_path,
                    receipt_dir=receipt_dir,
                    heartbeat_path=heartbeat_path,
                    steering_inbox_root=steering_inbox_root,
                    heartbeat_fresh_seconds=heartbeat_fresh_seconds,
                )
            if LIVE_OWNER_BLOCKERS.intersection(blockers):
                live_suppressed.append(candidate)
            else:
                candidates.append(candidate)

    if unknowns:
        return {
            **_result(name, "unknown", "terminal PR state unknown: " + "; ".join(unknowns)),
            "candidates": candidates,
            "live_suppressed": live_suppressed,
        }
    if candidates:
        detail = "; ".join(
            f"lane {item.get('lane_id')} PR #{item['pr_number']} "
            f"{item['terminal_state']} owner={item.get('owner_session')} "
            f"age={item['age_hours']:.1f}h"
            for item in candidates[:5]
        )
        return {
            **_result(name, "breach", detail),
            "candidates": candidates,
            "live_suppressed": live_suppressed,
        }
    if live_suppressed:
        return {
            **_result(
                name,
                "ok",
                f"{len(live_suppressed)} terminal PR owner row(s) have live-owner signal; "
                "no stale terminal owner rows",
            ),
            "candidates": [],
            "live_suppressed": live_suppressed,
        }
    return _result(name, "ok", "no stale terminal owner rows for merged/closed PRs")


# ---------------------------------------------------------------------------
# github_api_health (failure class B — external API degradation, 2026-06-10/11)
# ---------------------------------------------------------------------------


def _read_tail_lines(path: Path, max_lines: int) -> list[str]:
    """Read up to the last ``max_lines`` lines without loading the whole file."""
    step = 1 << 16
    with path.open("rb") as fh:
        fh.seek(0, 2)
        pos = fh.tell()
        data = b""
        while pos > 0 and data.count(b"\n") <= max_lines:
            read = min(step, pos)
            pos -= read
            fh.seek(pos)
            data = fh.read(read) + data
            step = min(step * 2, 1 << 22)
    return data.decode("utf-8", errors="replace").splitlines()[-max_lines:]


def publisher_failure_streak(lines: list[str]) -> tuple[int, str]:
    """Trailing consecutive failed branch-publish passes + last error class.

    Counts ``branch publish pass failed`` markers backwards from the end of
    the log, stopping at the first ``branch publish pass complete`` marker.
    Per-attempt retry lines (``branch publish pass attempt N/M failed``) are
    NOT pass failures and are not counted.  The error class is the most
    recent ``HTTP <code>`` (or ``connectivity_failed``) seen in the window.
    """
    streak = 0
    for line in reversed(lines):
        if "branch publish pass failed" in line:
            streak += 1
        elif "branch publish pass complete" in line:
            break
    last_error = "none"
    for line in reversed(lines):
        match = re.search(r"HTTP (\d{3})", line)
        if match:
            last_error = f"HTTP {match.group(1)}"
            break
        if "connectivity_failed" in line:
            last_error = "connectivity_failed"
            break
    return streak, last_error


def check_github_api_health(
    log_path: Path,
    *,
    persist_threshold: int,
    tail_lines: int,
    probe_runner: Callable[[list[str]], int],
    probe_cmd: list[str] | None = None,
) -> CheckResult:
    """Distinguish persistent GitHub API degradation from transient blips.

    A cheap live probe (``gh api rate_limit``) plus the publisher log's
    failed-pass streak.  Breach ONLY when both agree the degradation is
    persistent: probe fails AND streak >= ``persist_threshold``.  Transient
    blips (short streak, or probe already recovered) stay visible-but-quiet:
    recorded in the detail/ledger, exit stays green.
    """
    name = "github_api_health"
    command = probe_cmd or ["gh", "api", "rate_limit"]
    probe_error = ""
    probe_ok: bool | None
    try:
        probe_ok = probe_runner(command) == 0
    except Exception as exc:  # noqa: BLE001 - a probe we cannot run is a blind spot
        probe_ok = None
        probe_error = f"{exc.__class__.__name__}: {exc}"
    if not log_path.exists():
        return _result(name, "unknown", f"publisher log missing: {log_path}")
    try:
        lines = _read_tail_lines(log_path, tail_lines)
    except OSError as exc:
        return _result(
            name, "unknown", f"publisher log unreadable: {exc.__class__.__name__}: {exc}"
        )
    streak, last_error = publisher_failure_streak(lines)
    base = (
        f"failed-pass streak={streak} (persist-threshold {persist_threshold}); "
        f"last_error={last_error}"
    )
    if probe_ok is None:
        return _result(name, "unknown", f"probe could not run ({probe_error}); {base}")
    if probe_ok:
        return _result(name, "ok", f"probe ok; {base}")
    if streak >= persist_threshold:
        return _result(name, "breach", f"persistent degradation: probe failed and {base}")
    return _result(name, "ok", f"transient degradation (no breach): probe failed but {base}")


# ---------------------------------------------------------------------------
# trail_reconcile (TET Component 3 — witness vs anchored-intent reconciliation)
# docs/specs/TAMPER_EVIDENT_TRAIL.md, build phase T3 (+ T5 acceptance replay)
# ---------------------------------------------------------------------------

# Witness event classes that mutate the repo/org and therefore REQUIRE a
# pre-anchored intent.  severity per spec: token/key/member/workflow=critical,
# push/merge/branch=high.  require_human: credential and member changes have
# no legitimate agent intent class — only a scarmani-anchored intent matches.
_EVENT_CLASS_KEYS: tuple[tuple[tuple[str, ...], str, str, frozenset[str], bool], ...] = (
    (
        ("token", "deploy_key", "secret", "app_install", "integration"),
        "credential_change",
        "critical",
        frozenset({"credential_change"}),
        True,
    ),
    (("member", "org_role"), "member_change", "critical", frozenset({"member_change"}), True),
    (("workflow",), "workflow_change", "critical", frozenset({"workflow_change"}), False),
    (
        ("branch_delet", "branch_delete"),
        "branch_deletion",
        "high",
        frozenset({"branch_deletion", "branch_delete", "janitor"}),
        False,
    ),
    # Intent-type vocabularies include aragora.trail.intent_chain.INTENT_TYPES
    # (publish_pr/merge_pr/settle_pr — TET phase T1, PR #8251).
    (("push",), "push", "high", frozenset({"push", "publish", "publish_pr"}), False),
    (("merge",), "merge", "high", frozenset({"merge", "settle", "merge_pr", "settle_pr"}), False),
)

# Actor classification for the interim GitHub witness.  Unknown actors match
# no intent — exactly the May-incident shape (action from an unknown context).
# Intent actor_class values align with aragora.trail.intent_chain.ACTOR_CLASSES
# (human, agent-claude, agent-codex, agent-app, daemon-*); legacy bare labels
# are kept for tolerance.
KNOWN_AGENT_ACTORS = frozenset({"an0mium"})
KNOWN_HUMAN_ACTORS = frozenset({"scarmani"})
HUMAN_ACTOR_CLASSES = frozenset({"scarmani", "human", "operator"})
AGENT_ACTOR_CLASSES = frozenset({"agent", "automation", "loop", "lane"})


def _intent_class_is_agent(record_class: str) -> bool:
    return record_class in AGENT_ACTOR_CLASSES or record_class.startswith(("agent-", "daemon-"))


def classify_witness_actor(actor: str) -> str:
    if actor in KNOWN_HUMAN_ACTORS:
        return "human"
    if actor in KNOWN_AGENT_ACTORS or actor.endswith("[bot]"):
        return "agent"
    return "unknown"


def classify_witness_event(event_type: str) -> tuple[str, str, frozenset[str], bool] | None:
    """``event_type`` -> (class, severity, allowed intent_types, require_human).

    Returns None for non-mutating event classes (ignored by reconciliation).
    """
    lowered = event_type.lower()
    for keys, cls, severity, intent_types, require_human in _EVENT_CLASS_KEYS:
        if any(key in lowered for key in keys):
            # the event's own type is always an acceptable intent_type name
            return cls, severity, intent_types | {lowered}, require_human
    return None


def _parse_target(target: Any) -> tuple[str, str, str, str]:
    """Intent target -> (repo, ref, sha, pr).

    Dict form is the intent_chain contract (``{"repo", "ref"|"branch",
    "sha", "pr"}`` — e.g. the auto-evidence cycle records
    ``{"repo": ..., "pr": N}``); the string form ``<repo>[@<ref>][#<sha>]``
    is kept for hand-written replicas and replay fixtures.
    """
    if isinstance(target, dict):
        return (
            str(target.get("repo") or "").strip(),
            str(target.get("ref") or target.get("branch") or "").strip(),
            str(target.get("sha") or "").strip(),
            str(target.get("pr") or "").strip(),
        )
    head, _, sha = str(target).partition("#")
    repo, _, ref = head.partition("@")
    return repo.strip(), ref.strip(), sha.strip(), ""


def _target_matches(target: Any, repo: str, ref: str, sha: str, pr: str) -> bool:
    t_repo, t_ref, t_sha, t_pr = _parse_target(target)
    if repo and t_repo and t_repo != repo:
        return False
    if not (ref or sha or pr):
        return True  # repo-scoped event (e.g. credential change)
    if t_ref and ref and t_ref == ref:
        return True
    if t_sha and sha and (sha.startswith(t_sha) or t_sha.startswith(sha)):
        return True
    if t_pr and pr and t_pr == pr:
        return True
    return False


def _record_as_dict(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return record
    if hasattr(record, "_asdict"):
        return dict(record._asdict())
    if hasattr(record, "__dict__"):
        return dict(vars(record))
    raise TypeError(f"unsupported intent record type: {type(record).__name__}")


def _normalize_verify(verdict: Any) -> tuple[bool, str]:
    """Normalize ``verify_chain`` results across plausible return shapes."""
    if isinstance(verdict, bool):
        return verdict, ""
    if isinstance(verdict, tuple) and verdict:
        # aragora.trail.intent_chain.verify_chain returns (ok, first_broken_seq).
        ok = bool(verdict[0])
        extra = verdict[1] if len(verdict) > 1 else None
        if extra is None:
            return ok, ""
        if isinstance(extra, int):
            return ok, f"broken at seq {extra}"
        return ok, str(extra)
    if isinstance(verdict, dict):
        ok = bool(verdict.get("ok", verdict.get("valid", False)))
        detail = str(verdict.get("detail", verdict.get("error", "")) or "")
        broken_at = verdict.get("broken_at", verdict.get("broken_at_seq"))
        if broken_at is not None and "seq" not in detail:
            detail = (detail + f" at seq {broken_at}").strip()
        return ok, detail
    for attr in ("ok", "valid"):
        if hasattr(verdict, attr):
            return bool(getattr(verdict, attr)), str(getattr(verdict, "detail", "") or "")
    return bool(verdict), ""


def _default_chain_reader(chain_path: Path) -> tuple[list[dict[str, Any]], bool, str]:
    """Read + verify the intent chain via ``aragora.trail.intent_chain``.

    The module is lane TA's deliverable (TET phase T1) and is imported lazily:
    until it merges, ImportError degrades this check to ``unknown`` so T3 ships
    independently and lights up the moment T1 lands.
    """
    from aragora.trail import intent_chain  # noqa: PLC0415 - deliberate lazy import

    if not chain_path.exists():
        raise FileNotFoundError(str(chain_path))
    records = [_record_as_dict(r) for r in intent_chain.read_records(chain_path)]
    ok, detail = _normalize_verify(intent_chain.verify_chain(chain_path))
    return records, ok, detail


def _jsonl_chain_reader(chain_path: Path) -> tuple[list[dict[str, Any]], bool, str]:
    """Schema-only fallback reader: parses the chain JSONL without verifying
    hashes.  Honest about it — the verify detail says ``unverified``."""
    if not chain_path.exists():
        raise FileNotFoundError(str(chain_path))
    records = []
    for line in chain_path.read_text().splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records, True, "unverified (jsonl fallback reader; hashes not checked)"


def _match_intent(
    event: dict[str, Any],
    *,
    allowed_intent_types: frozenset[str],
    require_human: bool,
    records: list[dict[str, Any]],
    event_ts: datetime,
    pre_window_seconds: float,
    skew_seconds: float,
) -> bool:
    """An anchored intent matches a witness event iff intent_type is allowed,
    target references the event's repo and ref/sha, actor classes are
    compatible, and the intent was anchored BEFORE the event (within the match
    window; a small skew grace absorbs clock drift, nothing more — post-hoc
    anchoring cannot legitimize an action)."""
    actor_class = classify_witness_actor(str(event.get("actor", "")))
    for record in records:
        if str(record.get("intent_type", "")).lower() not in allowed_intent_types:
            continue
        if not _target_matches(
            record.get("target", ""),
            str(event.get("repo", "") or ""),
            str(event.get("ref", "") or ""),
            str(event.get("sha", "") or ""),
            str(event.get("pr", "") or ""),
        ):
            continue
        record_class = str(record.get("actor_class", "")).lower()
        if require_human:
            if record_class not in HUMAN_ACTOR_CLASSES:
                continue
        elif actor_class == "human":
            if record_class not in HUMAN_ACTOR_CLASSES:
                continue
        elif actor_class == "agent":
            if not _intent_class_is_agent(record_class):
                continue
        else:  # unknown actors match nothing
            continue
        try:
            record_ts = parse_iso(str(record.get("ts", "")))
        except ValueError:
            continue
        lead = (event_ts - record_ts).total_seconds()
        if -skew_seconds <= lead <= pre_window_seconds:
            return True
    return False


def check_trail_reconcile(
    *,
    witness_events: Callable[[], list[dict[str, Any]]],
    chain_path: Path,
    now: datetime,
    chain_reader: Callable[[Path], tuple[list[dict[str, Any]], bool, str]] | None = None,
    match_window_minutes: float = 15.0,
    skew_minutes: float = 2.0,
    witness_cadence_hours: float = 6.0,
    blind_factor: float = 4.0,
    reconcile_window_hours: float = 24.0,
    witness_coverage: str = "full",
) -> CheckResult:
    """TET Component 3: diff what HAPPENED (witness) against what was INTENDED
    (anchored intent chain).  Every mutating witness event needs a matching
    pre-anchored intent; unmatched events breach at class severity; a broken
    chain is a critical breach; an unreadable witness or absent chain is
    ``unknown`` (silence is never success).

    ``witness_coverage="events_api"`` marks the interim GitHub REST witness,
    which structurally CANNOT see token/deploy-key/member admin events — the
    exact May-incident class.  Every report then carries a coverage-gap note
    so an "ok" can never be mistaken for credential-event coverage before the
    S3 audit-stream witness (TET T0) is live."""
    name = "trail_reconcile"
    coverage_note = (
        "coverage limited: interim events-API witness cannot see "
        "token/deploy-key/member admin events (May-incident class) — "
        "S3 audit-stream witness (TET T0) required for full coverage"
        if witness_coverage == "events_api"
        else ""
    )
    try:
        events = list(witness_events())
    except Exception as exc:  # noqa: BLE001 - unreadable witness = we are blind
        return _result(name, "unknown", f"witness unreadable: {exc.__class__.__name__}: {exc}")
    try:
        records, chain_ok, chain_verify_detail = (chain_reader or _default_chain_reader)(
            Path(chain_path)
        )
    except ImportError:
        return _result(
            name,
            "unknown",
            "aragora.trail.intent_chain module not present (TET phase T1 not merged); "
            "reconciliation degraded — witness events cannot be matched yet",
        )
    except FileNotFoundError:
        return _result(name, "unknown", f"intent chain not yet populated at {chain_path}")
    except Exception as exc:  # noqa: BLE001 - unreadable chain = we are blind
        return _result(name, "unknown", f"intent chain unreadable: {exc.__class__.__name__}: {exc}")

    problems: list[str] = []
    if not chain_ok:
        problems.append(
            "critical: intent chain tampered — "
            + (chain_verify_detail or "verify_chain reported broken")
        )

    window_seconds = reconcile_window_hours * 3600.0
    newest_age_hours: float | None = None
    matched = 0
    considered = 0
    malformed = 0
    for event in events:
        try:
            event_ts = parse_iso(str(event.get("created_at", "")))
        except ValueError:
            malformed += 1
            continue
        age_seconds = (now - event_ts).total_seconds()
        age_hours = age_seconds / 3600.0
        if newest_age_hours is None or age_hours < newest_age_hours:
            newest_age_hours = age_hours
        classified = classify_witness_event(str(event.get("event_type", "")))
        if classified is None or age_seconds > window_seconds:
            continue
        event_class, severity, allowed_intent_types, require_human = classified
        considered += 1
        if _match_intent(
            event,
            allowed_intent_types=allowed_intent_types,
            require_human=require_human,
            records=records,
            event_ts=event_ts,
            pre_window_seconds=match_window_minutes * 60.0,
            skew_seconds=skew_minutes * 60.0,
        ):
            matched += 1
            continue
        anchor_hint = (
            "no scarmani-anchored intent (credential/member events have no agent intent class)"
            if require_human
            else "no anchored intent"
        )
        problems.append(
            f"{severity}: {event.get('event_type')} by {event.get('actor')} "
            f"on {event.get('repo')}"
            + (f"@{event['ref']}" if event.get("ref") else "")
            + f" at {event.get('created_at')} — {anchor_hint}"
        )

    chain_note = f"chain {'ok' if chain_ok else 'TAMPERED'} ({len(records)} record(s)"
    if chain_verify_detail:
        chain_note += f"; {chain_verify_detail}"
    chain_note += ")"
    blind_note = ""
    badly_blind = False
    if newest_age_hours is None:
        badly_blind = True
        blind_note = "blind period: witness returned no events at all"
    elif newest_age_hours > witness_cadence_hours * blind_factor:
        badly_blind = True
        blind_note = (
            f"blind period: newest witness event {newest_age_hours:.1f}h old "
            f"(cadence {witness_cadence_hours}h badly exceeded, factor {blind_factor})"
        )
    elif newest_age_hours > witness_cadence_hours:
        blind_note = (
            f"blind-period note: newest witness event {newest_age_hours:.1f}h old "
            f"(expected cadence {witness_cadence_hours}h)"
        )
    if malformed:
        blind_note = (blind_note + "; " if blind_note else "") + (
            f"{malformed} malformed witness event(s) skipped"
        )

    if problems:
        detail = "; ".join(problems) + f" | {chain_note}"
        if blind_note:
            detail += f" | {blind_note}"
        if coverage_note:
            detail += f" | {coverage_note}"
        return _result(name, "breach", detail)
    if badly_blind:
        detail = f"{blind_note} | {chain_note}"
        if coverage_note:
            detail += f" | {coverage_note}"
        return _result(name, "unknown", detail)
    detail = (
        f"{matched} matched, 0 unmatched of {considered} mutating witness event(s) "
        f"in {reconcile_window_hours:g}h window; {chain_note}"
    )
    if blind_note:
        detail += f" | {blind_note}"
    if coverage_note:
        detail += f" | {coverage_note}"
    return _result(name, "ok", detail)


def _replica_witness_events(path: Path) -> list[dict[str, Any]]:
    """Local witness replica: JSONL (one normalized event per line) or a JSON
    array of normalized events ``{event_type, repo, actor, ref, sha,
    created_at}``."""
    text = path.read_text()
    stripped = text.lstrip()
    if stripped.startswith("["):
        return list(json.loads(stripped))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _default_json_capture(cmd: list[str]) -> str:
    proc = subprocess.run(  # noqa: S603 - operator-configured command
        cmd, capture_output=True, text=True, timeout=120, check=True
    )
    return proc.stdout


def _github_witness_events(
    repo_slug: str, *, capture: Callable[[list[str]], str] = _default_json_capture
) -> list[dict[str, Any]]:
    """Interim witness: GitHub REST events API via ``gh api``.

    This is the visible-but-incomplete witness — token/deploy-key/member admin
    events are NOT exposed here.  The S3 audit-log stream (TET Component 1,
    operator phase T0) replaces this as the witness root once enabled; this
    fetcher then becomes the liveness cross-check.
    """
    safe_repo_slug = _validate_repo_slug(repo_slug)
    raw = json.loads(capture(["gh", "api", f"repos/{safe_repo_slug}/events?per_page=100"]))
    events: list[dict[str, Any]] = []
    for item in raw:
        etype = item.get("type", "")
        payload = item.get("payload") or {}
        base = {
            "repo": (item.get("repo") or {}).get("name", ""),
            "actor": (item.get("actor") or {}).get("login", ""),
            "created_at": item.get("created_at", ""),
        }
        if etype == "PushEvent":
            ref = str(payload.get("ref", ""))
            events.append(
                {
                    "event_type": "push",
                    "ref": ref.removeprefix("refs/heads/"),
                    "sha": str(payload.get("head", "")),
                    **base,
                }
            )
        elif etype == "DeleteEvent" and payload.get("ref_type") == "branch":
            events.append(
                {
                    "event_type": "branch_deletion",
                    "ref": str(payload.get("ref", "")),
                    "sha": "",
                    **base,
                }
            )
        elif etype == "PullRequestEvent" and payload.get("action") == "closed":
            pr = payload.get("pull_request") or {}
            if pr.get("merged"):
                events.append(
                    {
                        "event_type": "merge",
                        "ref": str((pr.get("base") or {}).get("ref", "")),
                        "sha": str(pr.get("merge_commit_sha", "") or ""),
                        "pr": str(pr.get("number", "") or ""),
                        **base,
                    }
                )
        elif etype == "MemberEvent":
            events.append(
                {
                    "event_type": f"member_{payload.get('action', 'change')}",
                    "ref": "",
                    "sha": "",
                    **base,
                }
            )
    return events


# ---------------------------------------------------------------------------
# Report, exit contract, ledger, notification
# ---------------------------------------------------------------------------


def exit_code_for(checks: list[CheckResult]) -> int:
    """0 all ok; 1 any breach; 2 any unknown (unknown outranks breach)."""
    statuses = {c["status"] for c in checks}
    if "unknown" in statuses:
        return 2
    if "breach" in statuses:
        return 1
    return 0


def breach_summary(checks: list[CheckResult]) -> str:
    breached = [c for c in checks if c["status"] != "ok"]
    parts = [f"{c['check']}[{c['status']}]: {c['detail']}" for c in breached]
    return f"fleet-sentinel: {len(breached)} signal(s) firing — " + " | ".join(parts)


def notify(notify_cmd: str, summary: str, *, runner: Callable[[list[str]], int]) -> None:
    try:
        tokens = _split_operator_command(notify_cmd, option_name="--notify-cmd")
        if any("{summary}" in t for t in tokens):
            # A bare "{summary}" token becomes its own argv element — safe to pass
            # the text through verbatim.  A placeholder embedded in a larger token
            # lands inside another language's string literal (e.g. the installer's
            # default AppleScript "display notification" command), so neutralize
            # quote/backslash injection before substituting.
            embedded_safe = summary.replace("\\", "/").replace('"', "'")
            tokens = [
                summary if t == "{summary}" else t.replace("{summary}", embedded_safe)
                for t in tokens
            ]
        else:
            tokens.append(summary)
        runner(tokens)
    except Exception as exc:  # noqa: BLE001 - notification failure must not mask the report
        print(f"fleet-sentinel: notify-cmd failed: {exc}", file=sys.stderr)


def append_ledger(ledger: Path, report: dict[str, Any]) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a") as fh:
        fh.write(json.dumps(report, sort_keys=True) + "\n")


def run_checks(args: argparse.Namespace, now: datetime) -> list[CheckResult]:
    selected = [c.strip() for c in args.checks.split(",") if c.strip()]
    unknown_names = set(selected) - set(ALL_CHECKS)
    if unknown_names:
        raise SystemExit(f"unknown check(s): {sorted(unknown_names)}")
    results: list[CheckResult] = []
    for name in selected:
        try:
            if name == "publisher_status":
                results.append(
                    check_publisher_status(
                        Path(args.publisher_status),
                        max_age_hours=args.publisher_max_age_hours,
                        now=now,
                    )
                )
            elif name == "boss_metrics_heartbeat":
                results.append(
                    check_boss_metrics(
                        Path(args.boss_metrics), max_age_hours=args.metrics_max_age_hours, now=now
                    )
                )
            elif name == "launchd_plists":
                results.append(check_launchd_plists(Path(args.launch_agents_dir)))
            elif name == "gh_auth":
                results.append(
                    check_gh_auth(
                        runner=_default_command_runner,
                        cmd=_split_operator_command(args.gh_auth_cmd, option_name="--gh-auth-cmd"),
                    )
                )
            elif name == "checkout_invariant":
                results.append(
                    check_checkout_invariant(
                        Path(args.repo_root), branch_reader=_default_branch_reader
                    )
                )
            elif name == "outbox_depth":
                results.append(
                    check_outbox(
                        Path(args.outbox_dir),
                        max_items=args.outbox_max,
                        max_age_days=args.outbox_max_age_days,
                        now=now,
                    )
                )
            elif name == "outbox_drain_progress":
                results.append(
                    check_outbox_drain_progress(
                        Path(args.ledger),
                        Path(args.outbox_dir),
                        stall_cycles=args.outbox_drain_stall_cycles,
                        min_floor=args.outbox_max,
                    )
                )
            elif name == "disk_free":
                results.append(
                    check_disk_free(Path(args.repo_root), min_free_gib=args.min_free_gib)
                )
            elif name == "lane_liveness":
                repo = Path(args.repo_root)
                results.append(
                    check_lane_liveness(
                        args.lanes_glob,
                        lane_max_age_hours=args.lane_max_age_hours,
                        orphan_age_hours=args.orphan_branch_age_hours,
                        now=now,
                        remote_heads=lambda repo=repo: _default_remote_heads(repo),
                        ahead_counter=_default_ahead_counter(repo),
                        commit_dater=_default_commit_dater(repo),
                    )
                )
            elif name == "stale_terminal_owner":
                default_paths = getattr(args, "_automation_state_root_default_paths", {})
                explicit_paths = set(getattr(args, "_explicit_state_path_args", set()))
                fallback_path_values = {
                    "agent_bridge_lanes": str(Path(args.agent_bridge_lanes)),
                    "agent_heartbeats": str(Path(args.agent_heartbeats)),
                    "operator_steering_root": str(Path(args.operator_steering_root)),
                    "stale_terminal_owner_receipt_dir": str(
                        Path(args.stale_terminal_owner_receipt_dir)
                    ),
                }
                if not hasattr(args, "_explicit_state_path_args"):
                    explicit_paths = {
                        name
                        for name, value in fallback_path_values.items()
                        if value != default_paths.get(name)
                    }
                unsafe_fallback_paths = [
                    name
                    for name, value in fallback_path_values.items()
                    if name not in explicit_paths and value == default_paths.get(name)
                ]
                using_unsafe_fallback_defaults = bool(
                    getattr(args, "_automation_state_root_error", "") and unsafe_fallback_paths
                )
                if using_unsafe_fallback_defaults:
                    results.append(
                        _result(
                            "stale_terminal_owner",
                            "unknown",
                            "invalid automation state root: "
                            f"{args._automation_state_root_error}; provide explicit state paths "
                            f"for: {', '.join(unsafe_fallback_paths)}",
                        )
                    )
                else:
                    results.append(
                        check_stale_terminal_owner(
                            Path(args.agent_bridge_lanes),
                            receipt_dir=Path(args.stale_terminal_owner_receipt_dir),
                            heartbeat_path=Path(args.agent_heartbeats),
                            steering_inbox_root=Path(args.operator_steering_root),
                            min_age_hours=args.stale_terminal_owner_age_hours,
                            now=now,
                            repo_slug=args.github_repo,
                            gh_bin=args.gh_bin,
                            heartbeat_fresh_seconds=args.stale_terminal_owner_heartbeat_fresh_seconds,
                            gh_timeout_seconds=args.stale_terminal_owner_gh_timeout_seconds,
                        )
                    )
            elif name == "github_api_health":
                results.append(
                    check_github_api_health(
                        Path(args.publisher_log),
                        persist_threshold=args.persist_threshold,
                        tail_lines=args.publisher_log_tail_lines,
                        probe_runner=_default_command_runner,
                        probe_cmd=_split_operator_command(
                            args.rate_limit_cmd, option_name="--rate-limit-cmd"
                        ),
                    )
                )
            elif name == "trail_reconcile":
                if args.trail_witness_replica:
                    replica = Path(args.trail_witness_replica)
                    fetcher: Callable[[], list[dict[str, Any]]] = (
                        lambda replica=replica: _replica_witness_events(replica)
                    )
                    coverage = "full"
                else:
                    fetcher = lambda slug=args.trail_witness_repo: _github_witness_events(slug)  # noqa: E731
                    coverage = "events_api"
                results.append(
                    check_trail_reconcile(
                        witness_events=fetcher,
                        chain_path=Path(args.trail_chain),
                        chain_reader=(
                            _jsonl_chain_reader if args.trail_chain_format == "jsonl" else None
                        ),
                        now=now,
                        match_window_minutes=args.trail_match_window_mins,
                        skew_minutes=args.trail_match_skew_mins,
                        witness_cadence_hours=args.trail_witness_cadence_hours,
                        reconcile_window_hours=args.trail_window_hours,
                        witness_coverage=coverage,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - a crashed check is a blind spot, not success
            results.append(
                _result(name, "unknown", f"check crashed: {exc.__class__.__name__}: {exc}")
            )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    repo_root = DEFAULT_REPO_ROOT
    automation_state_root, automation_state_root_error = _automation_state_root_for_defaults(
        repo_root
    )
    automation_default_paths = {
        "agent_bridge_lanes": str(automation_state_root / "agent-bridge" / "lanes.json"),
        "agent_heartbeats": str(automation_state_root / "agent-bridge" / "heartbeats.json"),
        "operator_steering_root": str(automation_state_root / "operator-steering"),
        "stale_terminal_owner_receipt_dir": str(
            automation_state_root / "agent-bridge" / "conflict-resolution-receipts"
        ),
    }
    parser.set_defaults(
        _automation_state_root_error=automation_state_root_error,
        _automation_state_root_default_paths=automation_default_paths,
    )
    parser.add_argument("--repo-root", default=str(repo_root))
    parser.add_argument(
        "--publisher-status",
        # Live writer path: scripts/cache_codex_automation_github_status.py
        # refreshes this on every publisher pass.  The previous default,
        # .aragora/automation-publisher-status.json, has been an orphan since
        # its writer moved (~2026-05-24) — watching it would alarm forever on
        # stale data or, worse, stay green on a frozen healthy snapshot.
        default=str(repo_root / ".aragora" / "automation-github-status" / "latest.json"),
    )
    parser.add_argument("--publisher-max-age-hours", type=float, default=24.0)
    parser.add_argument(
        "--boss-metrics",
        default=str(repo_root / ".aragora" / "overnight" / "boss_metrics.jsonl"),
    )
    parser.add_argument("--metrics-max-age-hours", type=float, default=48.0)
    parser.add_argument(
        "--launch-agents-dir", default=str(Path.home() / "Library" / "LaunchAgents")
    )
    parser.add_argument("--gh-auth-cmd", default="gh auth status")
    parser.add_argument("--outbox-dir", default=str(repo_root / ".aragora" / "automation-outbox"))
    parser.add_argument("--outbox-max", type=int, default=50)
    parser.add_argument("--outbox-max-age-days", type=float, default=7.0)
    parser.add_argument(
        "--outbox-drain-stall-cycles",
        type=int,
        default=3,
        help="breach if the outbox stays at/above --outbox-max without draining for this "
        "many consecutive sentinel cycles (circuit-breaker; §Conductor)",
    )
    parser.add_argument("--min-free-gib", type=float, default=25.0)
    parser.add_argument(
        "--lanes-glob",
        # Lane-ledger convention: .aragora/run-*/lanes/<lane>.json
        default=str(repo_root / ".aragora" / "run-*" / "lanes"),
        help="glob for lane-ledger directories (entries are <lane>.json inside)",
    )
    parser.add_argument("--lane-max-age-hours", type=float, default=3.0)
    parser.add_argument("--orphan-branch-age-hours", type=float, default=24.0)
    parser.add_argument(
        "--agent-bridge-lanes",
        default=automation_default_paths["agent_bridge_lanes"],
        help="lane owner registry used by stale_terminal_owner",
    )
    parser.add_argument(
        "--agent-heartbeats",
        default=automation_default_paths["agent_heartbeats"],
        help="heartbeat registry used by stale_terminal_owner safety checks",
    )
    parser.add_argument(
        "--operator-steering-root",
        default=automation_default_paths["operator_steering_root"],
        help="operator-steering inbox root used by stale_terminal_owner safety checks",
    )
    parser.add_argument(
        "--stale-terminal-owner-age-hours",
        type=float,
        default=24.0,
        help="minimum owner-row age before stale_terminal_owner evaluates terminal PR state",
    )
    parser.add_argument(
        "--stale-terminal-owner-receipt-dir",
        default=automation_default_paths["stale_terminal_owner_receipt_dir"],
        help="receipt directory to print in guarded resolve_lane_conflicts commands",
    )
    parser.add_argument(
        "--stale-terminal-owner-heartbeat-fresh-seconds",
        type=int,
        default=15 * 60,
        help="fresh-heartbeat TTL passed through to resolve_lane_conflicts",
    )
    parser.add_argument(
        "--stale-terminal-owner-gh-timeout-seconds",
        type=float,
        default=30.0,
        help="timeout for stale_terminal_owner GitHub CLI PR-state probes",
    )
    parser.add_argument("--github-repo", default="synaptent/aragora")
    parser.add_argument("--gh-bin", default="gh")
    parser.add_argument(
        "--publisher-log",
        default=str(repo_root / ".aragora" / "overnight" / "codex-automation-publisher.log"),
    )
    parser.add_argument("--publisher-log-tail-lines", type=int, default=2000)
    parser.add_argument(
        "--persist-threshold",
        type=int,
        default=3,
        help="consecutive failed publisher passes before degradation counts as persistent",
    )
    parser.add_argument("--rate-limit-cmd", default="gh api rate_limit")
    parser.add_argument(
        "--trail-witness-replica",
        default=None,
        help="local witness-replica file (normalized events, JSONL or JSON array); "
        "when unset, the interim GitHub REST events witness is used. The S3 "
        "audit-stream witness (TET T0, operator task) wires in here once enabled.",
    )
    parser.add_argument("--trail-witness-repo", default="synaptent/aragora")
    parser.add_argument(
        "--trail-chain",
        default=str(repo_root / ".aragora" / "trail" / "intent-chain.jsonl"),
        help="anchored intent chain (TET Component 2; lane TA's intent_chain module)",
    )
    parser.add_argument(
        "--trail-chain-format",
        choices=("intent_chain", "jsonl"),
        default="intent_chain",
        help="'intent_chain' verifies hashes via aragora.trail.intent_chain; "
        "'jsonl' is the schema-only fallback reader (reported as unverified)",
    )
    parser.add_argument("--trail-match-window-mins", type=float, default=15.0)
    parser.add_argument("--trail-match-skew-mins", type=float, default=2.0)
    parser.add_argument("--trail-witness-cadence-hours", type=float, default=6.0)
    parser.add_argument("--trail-window-hours", type=float, default=24.0)
    parser.add_argument(
        "--ledger",
        default=str(repo_root / ".aragora" / "fleet-sentinel" / "ledger.jsonl"),
    )
    parser.add_argument("--checks", default=",".join(ALL_CHECKS))
    parser.add_argument("--json", action="store_true", help="emit the JSON report to stdout")
    parser.add_argument(
        "--now", default=None, help="ISO-8601 timestamp override (for tests/replays)"
    )
    parser.add_argument(
        "--notify-cmd",
        default=None,
        help="command template invoked on breach; {summary} is replaced",
    )
    parser.add_argument("--no-ledger", action="store_true", help="skip the ledger append")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_argv)
    args._explicit_state_path_args = _explicit_state_path_args(raw_argv)
    now = parse_iso(args.now) if args.now else datetime.now(timezone.utc)
    checks = run_checks(args, now)
    breaches = sum(1 for c in checks if c["status"] == "breach")
    blind = sum(1 for c in checks if c["status"] == "unknown")
    report = {
        "generated_at": (args.now or now.isoformat().replace("+00:00", "Z")),
        "checks": checks,
        "breaches": breaches,
        "blind_checks": blind,
    }
    if not args.no_ledger:
        try:
            append_ledger(Path(args.ledger), report)
        except OSError as exc:
            print(f"fleet-sentinel: ledger append failed: {exc}", file=sys.stderr)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for c in checks:
            print(f"{c['status']:>7}  {c['check']}: {c['detail']}")
    if (breaches or blind) and args.notify_cmd:
        notify(args.notify_cmd, breach_summary(checks), runner=_default_command_runner)
    return exit_code_for(checks)


if __name__ == "__main__":
    raise SystemExit(main())
