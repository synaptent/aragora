#!/usr/bin/env python3
"""Lane janitor — bounded auto-fix for silent lane death (failure class A).

Companion to ``scripts/fleet_sentinel.py``'s ``lane_liveness`` check.  The
sentinel detects; this janitor remediates, within hard bounds:

  (a) mark lane-ledger entries dead (``status=dead`` + ``detected_at``) when
      the liveness rule fires: ``status=in_progress``, ``launched_at`` older
      than ``--lane-max-age-hours`` (default 3), and the lane's branch has
      zero commits ahead of origin/main (or is absent from origin);
  (b) emit ``RELAUNCH_QUEUE.md`` next to each run's lane ledgers, listing
      dead lanes with their briefs.  The coordinator/operator consumes it —
      autonomous relaunch is intentionally NOT done by the janitor;
  (c) delete remote branches that are zero-commits-ahead AND ledger-dead (or
      ledger-less orphans in the lane-owned namespaces) AND older than
      ``--branch-ttl-hours`` (default 24).

Hard guarantee: a branch with ANY unique commit ahead of origin/main is never
deleted, regardless of ledger state or age.  Unresolvable ahead counts and
unknown tip dates also block deletion — when in doubt, keep.

Dry-run is the default; ``--apply`` gates every mutation.  stdlib only.

Motivating incident (2026-06-10/11): three coordinator-spawned lanes
(elves/run-20260610-c06/c07/c08-*) died at setup overnight, leaving
in_progress ledgers and empty branches on origin that nobody noticed until a
manual morning sweep.
"""

from __future__ import annotations

import argparse
import glob as glob_module
import json
import subprocess
import sys
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

# Branch namespaces owned by autonomous lanes; only these are eligible for
# ledger-less orphan deletion.  Must stay in sync with fleet_sentinel.py.
ORPHAN_BRANCH_PATTERNS = ("elves/*", "aragora/boss*")


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (``Z`` suffix accepted) to aware UTC."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _hours_between(now: datetime, then: datetime) -> float:
    return (now - then).total_seconds() / 3600.0


class GitBoundary:
    """All git interaction lives here; tests inject a fake with this shape."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def _run(self, *cmd: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            ["git", "-C", str(self.repo), *cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def remote_heads(self) -> dict[str, str]:
        proc = self._run("ls-remote", "--heads", "origin")
        if proc.returncode != 0:
            raise RuntimeError(f"git ls-remote failed: {proc.stderr.strip()[:200]}")
        heads: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            sha, _, ref = line.partition("\t")
            prefix = "refs/heads/"
            if ref.startswith(prefix):
                heads[ref[len(prefix) :].strip()] = sha.strip()
        return heads

    def ahead_count(self, sha: str) -> int | None:
        """Commits ahead of origin/main; None when unresolvable.

        A zero-ahead tip is an ancestor of origin/main and therefore present
        locally; an unresolvable sha means unfetched unique commits.  Callers
        MUST treat None as "has commits" — never as empty.
        """
        proc = self._run("rev-list", "--count", f"origin/main..{sha}", timeout=60)
        if proc.returncode != 0:
            return None
        try:
            return int(proc.stdout.strip())
        except ValueError:
            return None

    def commit_date(self, sha: str) -> datetime | None:
        proc = self._run("log", "-1", "--format=%cI", sha, timeout=60)
        out = proc.stdout.strip()
        if proc.returncode != 0 or not out:
            return None
        try:
            return parse_iso(out)
        except ValueError:
            return None

    def delete_remote_branch(self, branch: str) -> None:
        proc = self._run("push", "origin", "--delete", branch, timeout=180)
        if proc.returncode != 0:
            raise RuntimeError(f"git push --delete {branch} failed: {proc.stderr.strip()[:200]}")


def _load_ledgers(runs_glob: str, errors: list[str]) -> list[dict[str, Any]]:
    """All readable lane-ledger entries under ``<runs_glob>/*.json``."""
    records: list[dict[str, Any]] = []
    for lanes_dir in sorted(glob_module.glob(runs_glob)):
        lanes_path = Path(lanes_dir)
        if not lanes_path.is_dir():
            continue
        for ledger_file in sorted(lanes_path.glob("*.json")):
            try:
                entry = json.loads(ledger_file.read_text())
                if not isinstance(entry, dict):
                    raise ValueError("ledger entry is not an object")
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                errors.append(f"unreadable ledger {ledger_file}: {exc.__class__.__name__}")
                continue
            records.append({"path": ledger_file, "lanes_dir": lanes_path, "entry": entry})
    return records


def _is_dead(
    entry: dict[str, Any],
    *,
    now: datetime,
    lane_max_age_hours: float,
    heads: dict[str, str],
    git: Any,
    errors: list[str],
) -> tuple[bool, float]:
    """Apply the liveness rule to one in_progress ledger entry."""
    try:
        launched = parse_iso(str(entry["launched_at"]))
    except (KeyError, ValueError, TypeError):
        errors.append(f"ledger for lane {entry.get('lane')!r} has bad launched_at")
        return False, 0.0
    age_hours = _hours_between(now, launched)
    if age_hours <= lane_max_age_hours:
        return False, age_hours
    branch = str(entry.get("branch", ""))
    sha = heads.get(branch)
    if sha is None:
        return True, age_hours  # never pushed anything durable
    return git.ahead_count(sha) == 0, age_hours


def _write_relaunch_queue(
    lanes_dir: Path, dead_entries: list[dict[str, Any]], now: datetime
) -> Path:
    path = lanes_dir / "RELAUNCH_QUEUE.md"
    lines = [
        f"# Relaunch queue — generated {iso_z(now)} by scripts/lane_janitor.py",
        "",
        "Lanes below died at setup (status=dead: no commits ahead of origin/main",
        "after the liveness window). The coordinator/operator should relaunch each",
        "with its original brief. The janitor never relaunches autonomously.",
        "",
    ]
    for entry in dead_entries:
        lines.append(
            f"- [ ] lane {entry.get('lane')} — branch `{entry.get('branch')}` — "
            f"brief: {entry.get('brief')} "
            f"(launched {entry.get('launched_at')}, "
            f"detected dead {entry.get('detected_at', iso_z(now))})"
        )
    lines.append("")
    path.write_text("\n".join(lines))
    return path


def build_plan(
    runs_glob: str,
    *,
    git: Any,
    now: datetime,
    lane_max_age_hours: float,
    branch_ttl_hours: float,
    apply: bool,
) -> dict[str, Any]:
    """Compute (and, when ``apply``, execute) the janitor plan."""
    errors: list[str] = []
    plan: dict[str, Any] = {
        "generated_at": iso_z(now),
        "applied": apply,
        "mark_dead": [],
        "relaunch_queue": [],
        "delete_branches": [],
        "skipped": [],
        "errors": errors,
    }
    try:
        heads = git.remote_heads()
    except Exception as exc:  # noqa: BLE001 - blind janitor must not act
        errors.append(f"could not list origin heads: {exc.__class__.__name__}: {exc}")
        return plan

    records = _load_ledgers(runs_glob, errors)

    # (a) dead-lane detection.
    newly_dead: list[dict[str, Any]] = []
    for record in records:
        entry = record["entry"]
        if str(entry.get("status", "")) != "in_progress":
            continue
        dead, age_hours = _is_dead(
            entry,
            now=now,
            lane_max_age_hours=lane_max_age_hours,
            heads=heads,
            git=git,
            errors=errors,
        )
        if not dead:
            continue
        newly_dead.append(record)
        plan["mark_dead"].append(
            {
                "lane": entry.get("lane"),
                "branch": entry.get("branch"),
                "ledger": str(record["path"]),
                "age_hours": round(age_hours, 1),
            }
        )

    if apply:
        for record in newly_dead:
            record["entry"]["status"] = "dead"
            record["entry"]["detected_at"] = iso_z(now)
            record["path"].write_text(json.dumps(record["entry"], indent=1))

    # Effective ledger status per branch (newly dead count as dead even in
    # dry-run so the deletion *plan* reflects what apply would do).
    effective_status: dict[str, str] = {}
    for record in records:
        entry = record["entry"]
        branch = str(entry.get("branch", ""))
        status = str(entry.get("status", ""))
        if record in newly_dead:
            status = "dead"
        # A live in_progress claim always wins over any other entry's status.
        if effective_status.get(branch) == "in_progress":
            continue
        effective_status[branch] = status

    # (b) relaunch queues — one per run lanes dir that has dead lanes.
    dirs_seen: dict[Path, list[dict[str, Any]]] = {}
    for record in records:
        status = str(record["entry"].get("status", ""))
        if status == "dead" or record in newly_dead:
            dirs_seen.setdefault(record["lanes_dir"], []).append(record["entry"])
    for lanes_dir, dead_entries in sorted(dirs_seen.items()):
        queue_path = lanes_dir / "RELAUNCH_QUEUE.md"
        plan["relaunch_queue"].append(
            {"path": str(queue_path), "lanes": [e.get("lane") for e in dead_entries]}
        )
        if apply:
            _write_relaunch_queue(lanes_dir, dead_entries, now)

    # (c) bounded branch deletion.
    for branch in sorted(heads):
        sha = heads[branch]
        branch_status = effective_status.get(branch)
        if branch_status is None:
            if not any(fnmatch(branch, pat) for pat in ORPHAN_BRANCH_PATTERNS):
                continue  # not a lane-owned namespace; never ours to touch
            reason = "ledger-less orphan"
        elif branch_status == "dead":
            reason = "ledger-dead"
        elif branch_status == "in_progress":
            plan["skipped"].append({"branch": branch, "reason": "live ledger (in_progress)"})
            continue
        else:
            plan["skipped"].append({"branch": branch, "reason": f"ledger status {branch_status!r}"})
            continue
        ahead = git.ahead_count(sha)
        if ahead is None:
            plan["skipped"].append({"branch": branch, "reason": "ahead count unresolvable — keep"})
            continue
        if ahead != 0:
            plan["skipped"].append(
                {"branch": branch, "reason": f"{ahead} unique commit(s) — never delete"}
            )
            continue
        tip_date = git.commit_date(sha)
        if tip_date is None:
            plan["skipped"].append({"branch": branch, "reason": "unknown tip date — keep"})
            continue
        tip_age_hours = _hours_between(now, tip_date)
        if tip_age_hours <= branch_ttl_hours:
            plan["skipped"].append(
                {
                    "branch": branch,
                    "reason": f"tip {tip_age_hours:.1f}h old <= ttl {branch_ttl_hours}h",
                }
            )
            continue
        plan["delete_branches"].append(
            {
                "branch": branch,
                "sha": sha,
                "reason": reason,
                "tip_age_hours": round(tip_age_hours, 1),
            }
        )

    if apply:
        for deletion in plan["delete_branches"]:
            try:
                git.delete_remote_branch(deletion["branch"])
            except Exception as exc:  # noqa: BLE001 - one failed delete must not stop the rest
                errors.append(
                    f"delete failed for {deletion['branch']}: {exc.__class__.__name__}: {exc}"
                )
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--repo-root", default=str(repo_root))
    parser.add_argument(
        "--runs-glob",
        default=str(repo_root / ".aragora" / "run-*" / "lanes"),
        help="glob for lane-ledger directories (entries are <lane>.json inside)",
    )
    parser.add_argument("--lane-max-age-hours", type=float, default=3.0)
    parser.add_argument("--branch-ttl-hours", type=float, default=24.0)
    parser.add_argument("--apply", action="store_true", help="execute the plan (default: dry-run)")
    parser.add_argument("--json", action="store_true", help="emit the JSON plan to stdout")
    parser.add_argument(
        "--now", default=None, help="ISO-8601 timestamp override (for tests/replays)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = parse_iso(args.now) if args.now else datetime.now(timezone.utc)
    git = GitBoundary(Path(args.repo_root))
    plan = build_plan(
        args.runs_glob,
        git=git,
        now=now,
        lane_max_age_hours=args.lane_max_age_hours,
        branch_ttl_hours=args.branch_ttl_hours,
        apply=args.apply,
    )
    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        mode = "APPLY" if plan["applied"] else "DRY-RUN"
        print(f"lane-janitor [{mode}] generated_at={plan['generated_at']}")
        for item in plan["mark_dead"]:
            print(f"  mark dead: lane {item['lane']} ({item['branch']}) — {item['ledger']}")
        for item in plan["relaunch_queue"]:
            print(f"  relaunch queue: {item['path']} lanes={item['lanes']}")
        for item in plan["delete_branches"]:
            print(
                f"  delete branch: {item['branch']} ({item['reason']}, "
                f"tip {item['tip_age_hours']}h old)"
            )
        for item in plan["skipped"]:
            print(f"  skip: {item['branch']} — {item['reason']}")
        if not (plan["mark_dead"] or plan["delete_branches"]):
            print("  nothing to do")
        for err in plan["errors"]:
            print(f"  ERROR: {err}", file=sys.stderr)
    return 1 if plan["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
