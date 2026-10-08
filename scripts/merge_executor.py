#!/usr/bin/env python3
"""Bounded single-pass Tier 0-2 merge executor: authorized -> merged, unattended.

Closes issue #8759: CI authorizes Tier 0-2 merges (merge-quorum packet
``status=satisfied``) but nothing executed them without a human typing
``--apply``. This is the launchd/cron invocable that does — ONE bounded pass
per invocation, never a daemon loop, and NO new risk judgment: discovery and
merge I/O come verbatim from ``scripts/auto_merge_quorum_green.py`` (the exact
``gh pr merge --squash --admin --match-head-commit`` path) and eligibility is
the pure defense-in-depth ``aragora.swarm.auto_merge_green.decide_auto_merge``.

The executor shell adds: dry-run by default (the decision trace prints,
nothing mutates); Tier 3-4 PRs never acted on (human-review digest only);
``--max-merges`` (default 1) bounding; exact-head re-verification immediately
before each merge; auto-halt (main health — check runs AND commit statuses —
re-evaluated before EVERY merge, not once per pass; red writes a halt marker
that blocks every later pass until a human deletes it, non-green blocks the
remainder of the pass); a one-way ``--disarm-file`` kill switch; and an
operator receipt JSON per executed merge in ``--receipt-dir``.

ARMING IS A HUMAN STEP: installing this under launchd and passing ``--apply``
is Tier 4 per docs/AGENT_OPERATING_CONTRACT.md; this file only makes that step
possible and safe, it never takes it.
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import importlib.util
import json
import os
import socket
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from aragora.swarm.auto_merge_green import (  # noqa: E402
    MAX_AUTO_MERGE_TIER,
    REQUIRED_CHECKS,
    context_from_gh,
    decide_auto_merge,
)
from aragora.swarm.merge_halt import DEFAULT_HALT_FILE, SHARED_REPO_ROOT  # noqa: E402


def _load_amqg() -> Any:
    """Load auto_merge_quorum_green.py (its I/O + merge invocation are reused
    verbatim, never reimplemented)."""
    path = _SCRIPTS_DIR / "auto_merge_quorum_green.py"
    spec = importlib.util.spec_from_file_location("merge_executor_amqg", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_amqg = _load_amqg()

# Conservative default: ONE merge per pass. Cadence (the launchd interval), not
# this cap, sets throughput; a small cap keeps any single bad pass small.
DEFAULT_MAX_MERGES = 1

DEFAULT_RECEIPT_DIR = _REPO_ROOT / ".aragora" / "merge_executor" / "receipts"
# DEFAULT_HALT_FILE comes from the shared guard so the arming lane, this executor
# and every other merge path read one marker. The disarm file must resolve the
# same way, or a disarm placed beside the halt would not stop a worktree run.
DEFAULT_DISARM_FILE = SHARED_REPO_ROOT / ".aragora" / "merge_executor.disarm"

# REST check-runs conclusions that make a required check on main "red".
_RED_CONCLUSIONS = frozenset(
    {"failure", "error", "cancelled", "timed_out", "startup_failure", "action_required"}
)


# Delegated I/O: module-level aliases (tests monkeypatch these) whose bodies
# are the existing script's, never re-implemented here.
fetch_view = _amqg.fetch_view
fetch_packet = _amqg.fetch_packet_entry
list_open_prs = _amqg.list_open_pr_numbers


def make_merge_fn(repo: str) -> Callable[[int, str], tuple[bool, str]]:
    """The one and only merge invocation: auto_merge_quorum_green's, verbatim."""
    return _amqg._make_merge_fn(repo)


def fetch_main_checks(repo: str, branch: str = "main") -> list[dict[str, Any]] | None:
    """Latest check-runs on the tip of ``branch`` (None on any fetch problem)."""
    cmd = ["gh", "api", f"repos/{repo}/commits/{branch}/check-runs", "--paginate"]
    cmd += ["--jq", ".check_runs[]"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    try:
        runs = [json.loads(line) for line in out.stdout.splitlines() if line.strip()]
    except json.JSONDecodeError:
        return None
    return [run for run in runs if isinstance(run, dict)]


def fetch_main_statuses(repo: str, branch: str = "main") -> list[dict[str, Any]] | None:
    """Commit *statuses* on the tip of ``branch`` (combined status API; None on
    any fetch problem). Required branch-protection contexts can be delivered as
    statuses rather than check runs — reading only check-runs would leave a
    failing required status context invisible."""
    cmd = ["gh", "api", f"repos/{repo}/commits/{branch}/status", "--paginate"]
    cmd += ["--jq", ".statuses[]"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    try:
        statuses = [json.loads(line) for line in out.stdout.splitlines() if line.strip()]
    except json.JSONDecodeError:
        return None
    return [st for st in statuses if isinstance(st, dict)]


def evaluate_main_health(
    check_runs: list[dict[str, Any]] | None,
    required: Iterable[str] = REQUIRED_CHECKS,
    statuses: Sequence[dict[str, Any]] | None = (),
) -> tuple[str, list[str]]:
    """Classify main as ``green`` / ``red`` / ``indeterminate``.

    A required context may report as a check *run* or as a commit *status*
    (branch protection accepts both); both sources are consulted and a
    present-and-failing entry in EITHER always blocks.

    red: any required context's LATEST report completed failing (auto-halt).
    green: every required context PRESENT in either source reports ``success``
    — a context absent from BOTH sources is not-applicable, NOT a blocker
    (verified live: "Generate & Validate" and "TypeScript SDK Type Check" only
    run on PRs, never on main-push commits; treating absence as pending would
    make green unreachable when armed).
    indeterminate: a fetch failed (``None``), a present context is pending or
    inconclusive, or no required context reported at all. Indeterminate blocks
    merging (fail closed) but does NOT halt — a merge freshly landed by a
    previous pass leaves main pending, which is not evidence of breakage.
    """
    if check_runs is None or statuses is None:
        return ("indeterminate", ["check-runs/commit-status fetch failed"])

    def _run_id(run: dict[str, Any]) -> int:
        try:
            return int(run.get("id") or 0)
        except (TypeError, ValueError):
            return 0

    latest: dict[str, dict[str, Any]] = {}  # ascending sort -> last write wins
    for run in sorted((r for r in check_runs if isinstance(r, dict)), key=_run_id):
        name = str(run.get("name") or "").strip()
        if name:
            latest[name] = run

    # Combined status API already returns the latest status per context.
    status_states: dict[str, str] = {}
    for st in statuses:
        if isinstance(st, dict):
            context = str(st.get("context") or "").strip()
            if context:
                status_states[context] = str(st.get("state") or "").strip().lower()

    red: list[str] = []
    not_green: list[str] = []
    present = 0
    for name in sorted(required):
        seen = False
        latest_run = latest.get(name)
        if latest_run is not None:
            seen = True
            status = str(latest_run.get("status") or "").strip().lower()
            conclusion = str(latest_run.get("conclusion") or "").strip().lower()
            if status != "completed":
                not_green.append(f"{name}: {status or 'pending'}")
            elif conclusion in _RED_CONCLUSIONS:
                red.append(f"{name}: {conclusion}")
            elif conclusion != "success":
                not_green.append(f"{name}: {conclusion or 'no conclusion'}")
        state = status_states.get(name)
        if state is not None:
            seen = True
            if state in {"failure", "error"}:
                red.append(f"{name}: status {state}")
            elif state != "success":
                not_green.append(f"{name}: status {state or 'pending'}")
        if seen:
            present += 1
    if red:
        return ("red", red)
    if present == 0:
        return ("indeterminate", ["no required checks reported on this commit yet"])
    if not_green:
        return ("indeterminate", not_green)
    return ("green", [])


def exit_code_for(summary: dict[str, Any], *, apply: bool) -> int:
    """0 ok (dry-run is always informational), 3 halted/disarmed under --apply,
    1 if an attempted merge actually failed."""
    if not apply:
        return 0
    if summary.get("halted") or summary.get("disarmed"):
        return 3
    if any(r.get("action") == "merge-failed" for r in summary.get("results") or []):
        return 1
    return 0


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _executor_identity() -> dict[str, Any]:
    try:
        user = getpass.getuser()
    except OSError:
        user = os.environ.get("USER") or "unknown"
    host = socket.gethostname()
    return {"user": user, "host": host, "pid": os.getpid(), "script": "scripts/merge_executor.py"}


def _write_receipt(receipt_dir: Path, receipt: dict[str, Any]) -> Path:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = receipt_dir / f"MERGE_EXECUTOR_RECEIPT_{stamp}_PR{receipt['pr']}.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_halt_marker(halt_file: Path, *, repo: str, details: list[str]) -> None:
    halt_file.parent.mkdir(parents=True, exist_ok=True)
    marker = {
        "reason": "main_red",
        "repo": repo,
        "details": details,
        "written_at": _now_iso(),
        "written_by": _executor_identity(),
        "re_arm": "a human deletes this file after verifying main is green",
    }
    halt_file.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")


def run_pass(
    *,
    repo: str,
    prs: list[int],
    apply: bool,
    max_merges: int,
    receipt_dir: Path,
    halt_file: Path,
    disarm_file: Path,
    fetch_view: Callable[[int], dict[str, Any] | None],
    fetch_packet: Callable[[int], dict[str, Any] | None],
    promising: Callable[[dict[str, Any]], bool],
    merge_fn: Callable[[int, str], tuple[bool, str]],
    fetch_main_checks: Callable[[], list[dict[str, Any]] | None],
    fetch_main_statuses: Callable[[], list[dict[str, Any]] | None],
) -> dict[str, Any]:
    """One bounded pass: discover -> gate -> (re-verify -> merge -> receipt).
    Read-only unless ``apply`` AND no kill switch / halt condition is active.
    Returns the full decision trace as a JSON-serializable summary."""
    disarmed = disarm_file.exists()
    previously_halted = halt_file.exists()

    def _main_health() -> tuple[str, list[str]]:
        return evaluate_main_health(fetch_main_checks(), REQUIRED_CHECKS, fetch_main_statuses())

    health, health_details = _main_health()

    halted = previously_halted
    if apply and not disarmed and not previously_halted and health == "red":
        _write_halt_marker(halt_file, repo=repo, details=health_details)
        halted = True

    results: list[dict[str, Any]] = []
    tier_3_4_digest: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    for pr in prs:
        view = fetch_view(pr)
        if view is None:
            results.append({"pr": pr, "action": "skip", "blockers": ["gh pr view failed"]})
            continue
        packet = fetch_packet(pr) if promising(view) else None
        ctx = context_from_gh(view, packet)
        decision = decide_auto_merge(ctx)
        if ctx.tier is not None and ctx.tier > MAX_AUTO_MERGE_TIER:
            note = "Tier 3-4: human settlement required (settle_tier4_pr.py); never auto-merged"
            tier_3_4_digest.append({"pr": pr, "tier": ctx.tier, "head": ctx.head_sha, "note": note})
        record: dict[str, Any] = {"pr": pr, "head": ctx.head_sha, "tier": ctx.tier}
        if not decision.should_merge:
            record["action"] = "skip"
            record["blockers"] = list(decision.blockers)
            results.append(record)
            continue
        eligible.append(record)

    merged_count = 0
    for record in eligible:
        pr = record["pr"]
        if merged_count >= max_merges:
            record["action"] = "deferred (max-merges reached)"
        elif disarmed:
            record["action"] = "blocked (disarm file present — kill switch)"
        elif halted:
            record["action"] = "blocked (halt marker present — human re-arm required)"
        elif health != "green":
            record["action"] = f"blocked (main health {health}, requires green)"
        elif not apply:
            record["action"] = "would-merge"
            merged_count += 1
        else:
            if disarm_file.exists():  # live kill switch, honored mid-pass
                record["action"] = "blocked (disarm file appeared mid-pass)"
                results.append(record)
                continue
            # Re-verify at the EXACT head: refetch both sources, re-run the gate.
            view2 = fetch_view(pr)
            if view2 is None or str(view2.get("headRefOid") or "") != record["head"]:
                record["action"] = "skip"
                record["blockers"] = [
                    "head moved (or view lost) between discovery and merge — re-verify failed"
                ]
                results.append(record)
                continue
            packet2 = fetch_packet(pr)
            decision2 = decide_auto_merge(context_from_gh(view2, packet2))
            if not decision2.should_merge:
                record["action"] = "skip"
                record["blockers"] = ["re-verification regressed: " + b for b in decision2.blockers]
                results.append(record)
                continue
            # Re-evaluate main health immediately before EACH merge — the
            # pass-start read is stale the moment main advances (including by
            # our own previous merge). Red mid-pass halts the remainder and
            # writes the halt marker; any non-green blocks the remainder.
            health, health_details = _main_health()
            if health != "green":
                if health == "red":
                    if not halt_file.exists():
                        _write_halt_marker(halt_file, repo=repo, details=health_details)
                    halted = True
                record["action"] = f"blocked (main health {health} at merge time)"
                results.append(record)
                continue
            ok, detail = merge_fn(pr, record["head"])
            record["detail"] = detail
            if ok:
                record["action"] = "merged"
                merged_count += 1
                authority = (
                    "merge-quorum packet (status=satisfied) + aragora-merge-quorum "
                    "check; executor added no new risk judgment"
                )
                receipt = {
                    "schema": "merge-executor-receipt/v1",
                    "repo": repo,
                    "pr": pr,
                    "head_sha": record["head"],
                    "tier": record["tier"],
                    "merged_at": _now_iso(),
                    "executor": _executor_identity(),
                    "merge_detail": detail,
                    "main_health_at_merge": health,
                    "packet_entry": packet2,
                    "authority": authority,
                }
                record["receipt"] = str(_write_receipt(receipt_dir, receipt))
            else:
                record["action"] = "merge-failed"
        results.append(record)

    return {
        "schema": "merge-executor-pass/v1",
        "repo": repo,
        "mode": "apply" if apply else "dry-run",
        "timestamp": _now_iso(),
        "executor": _executor_identity(),
        "main_health": health,
        "main_health_details": health_details,
        "disarmed": disarmed,
        "halted": halted,
        "max_merges": max_merges,
        "scanned": len(prs),
        "eligible": len(eligible),
        "merged": merged_count if apply else 0,
        "tier_3_4_digest": tier_3_4_digest,
        "results": results,
    }


def _render_human(summary: dict[str, Any]) -> None:
    print(
        f"[merge-executor] {summary['mode']}: repo={summary['repo']} "
        f"main={summary['main_health']} scanned={summary['scanned']} "
        f"eligible={summary['eligible']} merged={summary['merged']}"
    )
    if summary["disarmed"]:
        print("  DISARMED: disarm file present — no merging until a human removes it")
    if summary["halted"]:
        print("  HALTED: halt marker present/written — human re-arm required")
    for detail in summary["main_health_details"]:
        print(f"  main: {detail}")
    for record in summary["results"]:
        print(f"  #{record['pr']} (tier={record.get('tier')}): {record.get('action')}")
        for blocker in (record.get("blockers") or [])[:3]:
            print(f"      blocker: {blocker}")
        if record.get("receipt"):
            print(f"      receipt: {record['receipt']}")
    if summary["tier_3_4_digest"]:
        print("  Tier 3-4 human-review digest (never auto-merged):")
        for entry in summary["tier_3_4_digest"]:
            print(f"    #{entry['pr']} tier={entry['tier']} head={entry['head'][:8]}")
    if summary["mode"] == "dry-run":
        print("  DRY RUN — nothing mutated. Arming (--apply) is a Tier 4 human step.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bounded single-pass Tier 0-2 merge executor (dry-run by default). "
        "Designed to be invoked by launchd/cron; never a daemon loop itself."
    )
    add = parser.add_argument
    add("--repo", required=True, help="owner/name")
    add("--pr", type=int, action="append", help="specific PR(s); default scans open non-drafts")
    add("--limit", type=int, default=300, help="max open PRs to scan")
    cap_help = f"cap merges in this pass (default {DEFAULT_MAX_MERGES})"
    add("--max-merges", type=int, default=DEFAULT_MAX_MERGES, help=cap_help)
    add("--branch", default="main", help="protected branch to health-check")
    add("--receipt-dir", type=Path, default=DEFAULT_RECEIPT_DIR, help="operator receipt dir (JSON)")
    halt_help = "halt marker: written when main is red; blocks merging until a human deletes it"
    add("--halt-file", type=Path, default=DEFAULT_HALT_FILE, help=halt_help)
    disarm_help = "one-way kill switch: if this file exists, nothing merges"
    add("--disarm-file", type=Path, default=DEFAULT_DISARM_FILE, help=disarm_help)
    add("--apply", action="store_true", help="actually merge (default: dry-run, mutates nothing)")
    add("--json", action="store_true", help="emit structured JSON summary")
    args = parser.parse_args(argv)

    prs = args.pr if args.pr else list_open_prs(args.repo, args.limit)
    summary = run_pass(
        repo=args.repo,
        prs=prs,
        apply=args.apply,
        max_merges=args.max_merges,
        receipt_dir=args.receipt_dir,
        halt_file=args.halt_file,
        disarm_file=args.disarm_file,
        fetch_view=lambda pr: fetch_view(args.repo, pr),
        fetch_packet=lambda pr: fetch_packet(args.repo, pr),
        promising=_amqg._cheaply_promising,
        merge_fn=make_merge_fn(args.repo),
        fetch_main_checks=lambda: fetch_main_checks(args.repo, args.branch),
        fetch_main_statuses=lambda: fetch_main_statuses(args.repo, args.branch),
    )

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _render_human(summary)
    return exit_code_for(summary, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
