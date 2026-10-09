#!/usr/bin/env python3
"""CLI shell for the lane conductor (see aragora.swarm.lane_conductor).

Resolves the live merge-blocked PR queue and which PRs already have a live
owner, then plans (and, only with ``--execute``, claims + dispatches) one
conductor pass. Pure decision logic lives in the module; this shell only does
I/O so the decision stays unit-testable.

Reads route through the GitHub App installation token (separate API budget) so
the conductor and its workers do not starve the operator's per-user PAT quota.

DRY-RUN BY DEFAULT. It never merges or settles -- it only assigns, claims, and
drops work orders for the supervisor / worker_launcher to spawn (each worker is
itself gated by the merge-gate tooling).

Examples
--------
::

    # Preview the next pass (no claims, no dispatch).
    python3 scripts/lane_conductor.py --json --max-workers 3

    # Actually claim + drop work orders for up to 3 lanes.
    python3 scripts/lane_conductor.py --execute --max-workers 3
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aragora.swarm import github_app_auth  # noqa: E402
from aragora.swarm.lane_conductor import (  # noqa: E402
    DEFAULT_TARGET_AGENT,
    default_claim,
    default_dispatch,
    default_release,
    run_pass,
)
from aragora.swarm.lane_cycle import run_cycle  # noqa: E402
from aragora.swarm.lane_dispatcher import DEFAULT_MAX_WORKERS  # noqa: E402
from scripts.lane_supervisor import _worker_launcher_launch  # noqa: E402

# mergeStateStatus values that mean "open and waiting on checks/quorum/settlement"
# -- i.e. a candidate the swarm can usefully advance. CLEAN/DIRTY/DRAFT excluded.
_BLOCKED_STATES = {"BLOCKED", "UNSTABLE"}
# Owner blocking-state values that mean the lane is NOT actively held, so it is
# reassignable. Anything else (including stale/unknown) is treated as live -- the
# fail-safe direction is to avoid double-dispatching a possibly-live lane.
_RECLAIMABLE_OWNER_BLOCKING_STATES = {"stale_terminal_owner", "absent", "reclaimable"}

# Compatibility for older identify_lane_owner output that predates
# owner_blocking_state. Plain "stale" remains blocking until a reconciler/sweeper
# has made the row terminal.
_RECLAIMABLE_LEGACY_ASSESSMENTS = {"terminal", "absent", "reclaimable"}
_UNKNOWN_OWNER = "owner-liveness-unavailable"
# Per-probe timeout kept short: a single slow identify_lane_owner must not stall
# the whole pass. Probes run concurrently across candidates (one slow probe no
# longer serializes the backlog).
_OWNER_PROBE_TIMEOUT_SECONDS = 15
_OWNER_PROBE_CONCURRENCY = 8


def _read_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env.setdefault("ARAGORA_USE_SECRETS_MANAGER", "false")
    return github_app_auth.github_cli_env(env)


def _gh_json(args: list[str]) -> Any:
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False, env=_read_env(), timeout=60
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def fetch_candidates(repo: str) -> list[dict[str, Any]]:
    """Open, non-draft, merge-blocked PRs in oldest-first priority order."""
    rows = (
        _gh_json(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--limit",
                "200",
                "--json",
                "number,headRefName,isDraft,mergeStateStatus,isCrossRepository",
            ]
        )
        or []
    )
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("isDraft"):
            continue
        # Lanes are same-repo only: a worker provisions a worktree on the head
        # branch and pushes to it. A fork PR's headRefName is not a ref on origin,
        # so it can be neither provisioned nor advanced here -- skip it rather
        # than dispatch a worker that is guaranteed to fail at fetch.
        if row.get("isCrossRepository"):
            continue
        if str(row.get("mergeStateStatus") or "").upper() not in _BLOCKED_STATES:
            continue
        number = row.get("number")
        branch = str(row.get("headRefName") or "").strip()
        if isinstance(number, int) and branch:
            candidates.append({"number": number, "branch": branch})
    # Oldest-first: lower PR numbers are usually closest to done.
    candidates.sort(key=lambda c: c["number"])
    return candidates


def _unknown_owner(reason: str) -> str:
    clean = " ".join(reason.strip().split())
    return _UNKNOWN_OWNER if not clean else f"{_UNKNOWN_OWNER}: {clean[:240]}"


def _resolve_owner(pr: int) -> tuple[int, str | None]:
    """Resolve one PR's live owner. Returns ``(pr, owner_session | None)``.

    ``None`` means the lane is reassignable (no live owner). The fail-safe
    direction is conservative: a probe that cannot run or fails unexpectedly is
    treated as live (return an ``owner-liveness-unavailable`` sentinel) so the
    dispatcher never reassigns -- and therefore never force-claims -- a
    possibly-live lane. A clean "no lane matched" result is reassignable.

    NOTE: no-lane detection still keys off identify_lane_owner's "no lane
    matched" message; coupling it to a stable exit code / structured JSON field
    is a tracked follow-up. Until then the conservative default means a message
    reword degrades to "dispatch nothing" (safe), never to a wrongful claim.
    """
    try:
        proc = subprocess.run(
            [
                "python3",
                str(REPO_ROOT / "scripts" / "identify_lane_owner.py"),
                "--pr",
                str(pr),
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_OWNER_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return pr, _unknown_owner(
            f"identify_lane_owner.py timed out after {_OWNER_PROBE_TIMEOUT_SECONDS}s"
        )
    except OSError as exc:
        return pr, _unknown_owner(f"identify_lane_owner.py failed: {type(exc).__name__}: {exc}")

    if proc.returncode != 0 or not proc.stdout.strip():
        stderr = proc.stderr or ""
        if "no lane matched" in stderr.lower():
            return pr, None  # clean no-lane -> reassignable
        reason = stderr or proc.stdout or f"identify_lane_owner.py exited {proc.returncode}"
        return pr, _unknown_owner(reason)  # broken probe -> stay conservative (live)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return pr, _unknown_owner("identify_lane_owner.py returned invalid JSON")
    owner = str(data.get("owner_session") or "").strip()
    if not owner:
        return pr, None
    owner_blocking_state = str(data.get("owner_blocking_state") or "").strip().lower()
    if owner_blocking_state in _RECLAIMABLE_OWNER_BLOCKING_STATES:
        return pr, None
    if owner_blocking_state:
        return pr, owner

    liveness = data.get("owner_liveness")
    assessment = (
        str((liveness.get("assessed") if isinstance(liveness, dict) else "") or "").strip().lower()
    )
    if assessment in _RECLAIMABLE_LEGACY_ASSESSMENTS:
        return pr, None
    return pr, owner


def fetch_live_claims(repo: str, candidates: Sequence[dict[str, Any]]) -> dict[int, str]:
    """Map each candidate PR with a LIVE owner to that owner_session.

    Probes run concurrently (bounded by ``_OWNER_PROBE_CONCURRENCY``) so one slow
    ``identify_lane_owner`` call no longer serializes the whole backlog.
    """
    claims: dict[int, str] = {}
    if not candidates:
        return claims
    workers = min(_OWNER_PROBE_CONCURRENCY, len(candidates))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for pr, owner in pool.map(lambda c: _resolve_owner(int(c["number"])), candidates):
            if owner is not None:
                claims[pr] = owner
    return claims


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="synaptent/aragora")
    parser.add_argument(
        "--root",
        default=".",
        help="repo root holding .aragora/lane_dispatch/ and lane claim scripts",
    )
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument(
        "--max-launches",
        type=int,
        default=None,
        help="launch cap when --launch-workers is set (default: --max-workers)",
    )
    parser.add_argument("--target-agent", default=DEFAULT_TARGET_AGENT)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write lane claims and dispatch work orders (default: dry-run preview).",
    )
    parser.add_argument(
        "--launch-workers",
        action="store_true",
        help=(
            "After the conductor pass, drain the newly dispatched work orders through "
            "the lane supervisor. Still dry-run unless --execute is also set."
        ),
    )
    parser.add_argument("--json", dest="json_output", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.launch_workers:
        cycle = run_cycle(
            repo=args.repo,
            root=root,
            fetch_candidates=fetch_candidates,
            fetch_live_claims=fetch_live_claims,
            max_workers=args.max_workers,
            max_launches=args.max_launches,
            target_agent=args.target_agent,
            execute=args.execute,
            claim_fn=lambda wo: default_claim(wo, repo_root=root),
            dispatch_fn=lambda wo: default_dispatch(wo, repo_root=root),
            launch_fn=lambda order: _worker_launcher_launch(order, repo_root=root),
        )

        if args.json_output:
            print(json.dumps(cycle.to_dict(), indent=2))
        else:
            print(cycle.reason)
            for wo in cycle.conductor.work_orders:
                print(f"  -> PR #{wo.pr} ({wo.branch}) :: {wo.owner_session} [{wo.target_agent}]")
            for path in cycle.conductor.dispatched:
                print(f"  dispatched: {path}")
            for wo_id in cycle.supervisor.launched:
                print(f"  launched: {wo_id}")
            for failure in cycle.supervisor.failed:
                print(f"  FAILED: {failure['work_order_id']} -- {failure['error']}")
            for wo_id in cycle.supervisor.deferred:
                print(f"  deferred: {wo_id}")
        return 0

    result = run_pass(
        repo=args.repo,
        fetch_candidates=fetch_candidates,
        fetch_live_claims=fetch_live_claims,
        max_workers=args.max_workers,
        target_agent=args.target_agent,
        execute=args.execute,
        claim_fn=lambda wo: default_claim(wo, repo_root=root),
        dispatch_fn=lambda wo: default_dispatch(wo, repo_root=root),
        release_fn=lambda wo: default_release(wo, repo_root=root),
    )

    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.reason)
        for wo in result.work_orders:
            print(f"  -> PR #{wo.pr} ({wo.branch}) :: {wo.owner_session} [{wo.target_agent}]")
        for pr, owner in result.owned.items():
            print(f"  .. PR #{pr} already live-owned by {owner}")
        for path in result.dispatched:
            print(f"  dispatched: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
