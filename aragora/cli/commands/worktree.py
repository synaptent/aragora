"""Worktree management CLI subcommand.

Provides first-class CLI access to git worktree management for
parallel multi-agent development sessions.

Usage:
    aragora worktree create --tracks sme developer qa
    aragora worktree list
    aragora worktree merge <branch>
    aragora worktree merge-all --test-first
    aragora worktree conflicts
    aragora worktree cleanup
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from aragora.swarm.reporter import build_integrator_view
from aragora.worktree import (
    AutopilotRequest,
    FleetIntegrationWorker,
    FleetIntegrationWorkerConfig,
    resolve_repo_root,
    run_autopilot,
)
from aragora.worktree.fleet import (
    FleetCoordinationStore,
    build_fleet_rows,
)


def add_worktree_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'worktree' subcommand and its sub-subcommands."""
    wt_parser = subparsers.add_parser(
        "worktree",
        help="Manage git worktrees for parallel agent sessions",
        description=(
            "Create, list, merge, and clean up git worktrees for isolated "
            "parallel development sessions. Each track gets its own worktree "
            "so multiple Claude Code sessions can work without conflicts."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Workflow:
  1. aragora worktree create --tracks sme developer qa
  2. Open a Claude Code session in each worktree path
  3. Work independently; each session commits to its branch
  4. aragora worktree merge-all --test-first
  5. aragora worktree cleanup
""",
    )
    wt_parser.add_argument(
        "--repo",
        default=None,
        help="Repository path (default: current directory)",
    )
    wt_parser.add_argument(
        "--base",
        default="main",
        help="Base branch (default: main)",
    )

    wt_sub = wt_parser.add_subparsers(dest="wt_action")

    # create
    create_p = wt_sub.add_parser("create", help="Create worktrees for tracks")
    create_p.add_argument(
        "--tracks",
        "-t",
        nargs="+",
        required=True,
        help="Tracks: sme, developer, self_hosted, qa, core, security",
    )

    # list
    wt_sub.add_parser("list", help="List active worktrees")

    # merge
    merge_p = wt_sub.add_parser("merge", help="Merge a branch back to base")
    merge_p.add_argument("branch", help="Branch name to merge")
    merge_p.add_argument("--test-first", action="store_true", help="Run tests before merging")
    merge_p.add_argument("--dry-run", action="store_true", help="Check without merging")

    # merge-all
    merge_all_p = wt_sub.add_parser("merge-all", help="Merge all worktree branches")
    merge_all_p.add_argument("--test-first", action="store_true", help="Run tests first")

    # conflicts
    wt_sub.add_parser("conflicts", help="Show conflict report")

    # cleanup
    wt_sub.add_parser("cleanup", help="Clean up merged worktrees")

    # fleet status
    fleet_p = wt_sub.add_parser(
        "fleet-status",
        help="Show codex/claude session status and recent logs across worktrees",
    )
    fleet_p.add_argument(
        "--tail",
        type=int,
        default=500,
        help="Log lines to show per worktree (default: 500)",
    )
    fleet_p.add_argument("--json", action="store_true", help="Emit JSON output")

    # fleet claims
    claims_p = wt_sub.add_parser(
        "fleet-claims",
        help="List file ownership claims across active sessions",
    )
    claims_p.add_argument("--json", action="store_true", help="Emit JSON output")

    claim_p = wt_sub.add_parser(
        "fleet-claim",
        help="Claim file ownership for a session to avoid collision",
    )
    claim_p.add_argument("--session-id", required=True, help="Session ID (from fleet-status)")
    claim_p.add_argument("--paths", nargs="+", required=True, help="File paths to claim")
    claim_p.add_argument("--branch", default="", help="Branch associated with the claim")
    claim_p.add_argument(
        "--mode",
        choices=["exclusive", "shared"],
        default="exclusive",
        help="Claim mode (default: exclusive)",
    )
    claim_p.add_argument("--json", action="store_true", help="Emit JSON output")

    release_p = wt_sub.add_parser(
        "fleet-release",
        help="Release file ownership claims for a session",
    )
    release_p.add_argument("--session-id", required=True, help="Session ID (from fleet-status)")
    release_p.add_argument("--paths", nargs="*", default=None, help="Optional subset to release")
    release_p.add_argument("--json", action="store_true", help="Emit JSON output")

    queue_add_p = wt_sub.add_parser(
        "fleet-queue-add",
        help="Enqueue a branch in merge queue",
    )
    queue_add_p.add_argument("--session-id", required=True, help="Session ID (from fleet-status)")
    queue_add_p.add_argument("--branch", required=True, help="Branch to enqueue")
    queue_add_p.add_argument("--title", default="", help="Optional merge item title")
    queue_add_p.add_argument("--priority", type=int, default=50, help="Priority 0-100")
    queue_add_p.add_argument("--json", action="store_true", help="Emit JSON output")

    queue_list_p = wt_sub.add_parser(
        "fleet-queue-list",
        help="List merge queue items",
    )
    queue_list_p.add_argument("--status", default="", help="Filter by queue status")
    queue_list_p.add_argument("--json", action="store_true", help="Emit JSON output")

    queue_process_p = wt_sub.add_parser(
        "fleet-queue-process-next",
        help="Validate or integrate the next merge queue item",
    )
    queue_process_p.add_argument(
        "--worker-session-id",
        required=True,
        help="Integrator worker session ID",
    )
    queue_process_p.add_argument(
        "--target-branch",
        default="main",
        help="Target branch to validate/merge into (default: main)",
    )
    queue_process_p.add_argument(
        "--execute",
        action="store_true",
        help="Attempt the actual merge after validation",
    )
    queue_process_p.add_argument(
        "--test-gate",
        action="store_true",
        help="Use BranchCoordinator's test-gated merge path when executing",
    )
    queue_process_p.add_argument("--json", action="store_true", help="Emit JSON output")

    # autopilot
    auto_p = wt_sub.add_parser(
        "autopilot",
        help="Manage auto-worktree sessions (codex_worktree_autopilot.py)",
    )
    auto_p.add_argument(
        "auto_action",
        choices=["ensure", "reconcile", "cleanup", "maintain", "status"],
        nargs="?",
        default="status",
        help="Autopilot action (default: status)",
    )
    auto_p.add_argument(
        "--managed-dir",
        default=".worktrees/codex-auto",
        help="Managed worktree directory (relative to repo)",
    )
    auto_p.add_argument(
        "--base",
        dest="auto_base",
        default=None,
        help="Base branch override for autopilot actions",
    )
    auto_p.add_argument("--agent", default="codex", help="Agent name for ensure")
    auto_p.add_argument("--session-id", default=None, help="Optional session id for ensure")
    auto_p.add_argument("--force-new", action="store_true", help="Force new session on ensure")
    auto_p.add_argument(
        "--strategy",
        choices=["merge", "rebase", "ff-only", "none"],
        default="merge",
        help="Integration strategy",
    )
    auto_p.add_argument(
        "--reconcile",
        action="store_true",
        help="Run integration on reused ensure sessions",
    )
    auto_p.add_argument("--all", action="store_true", help="Apply reconcile to all sessions")
    auto_p.add_argument("--path", default=None, help="Specific worktree path for reconcile")
    auto_p.add_argument("--ttl-hours", type=int, default=24, help="Cleanup TTL in hours")
    auto_p.add_argument("--force-unmerged", action="store_true", help="Cleanup unmerged sessions")
    auto_p.add_argument(
        "--delete-branches",
        dest="delete_branches",
        action="store_true",
        help="Allow cleanup to delete local codex/* branches",
    )
    auto_p.add_argument(
        "--no-delete-branches",
        dest="delete_branches",
        action="store_false",
        help="Keep local codex/* branches during cleanup",
    )
    auto_p.set_defaults(delete_branches=None)
    auto_p.add_argument("--json", action="store_true", help="Emit JSON output")
    auto_p.add_argument("--print-path", action="store_true", help="Print ensured path only")

    wt_parser.set_defaults(func=cmd_worktree)


def cmd_worktree(args: argparse.Namespace) -> None:
    """Dispatch worktree subcommand."""
    action = getattr(args, "wt_action", None)
    if not action:
        print(
            "Usage: aragora worktree "
            "{create|list|merge|merge-all|conflicts|cleanup|fleet-status|fleet-claims|fleet-claim|fleet-release|fleet-queue-add|fleet-queue-list|fleet-queue-process-next|autopilot}"
        )
        print("Run 'aragora worktree --help' for details.")
        return

    repo_path = Path(args.repo).resolve() if args.repo else Path.cwd()
    repo_root = resolve_repo_root(repo_path)
    base_branch = args.base

    if action == "autopilot":
        base_branch = getattr(args, "auto_base", None) or base_branch
        _cmd_worktree_autopilot(args, repo_path=repo_root, base_branch=base_branch)
        return
    if action == "fleet-status":
        _cmd_worktree_fleet_status(args, repo_path=repo_root, base_branch=base_branch)
        return
    if action == "fleet-claims":
        _cmd_worktree_fleet_claims(args, repo_path=repo_root)
        return
    if action == "fleet-claim":
        _cmd_worktree_fleet_claim(args, repo_path=repo_root)
        return
    if action == "fleet-release":
        _cmd_worktree_fleet_release(args, repo_path=repo_root)
        return
    if action == "fleet-queue-add":
        _cmd_worktree_fleet_queue_add(args, repo_path=repo_root)
        return
    if action == "fleet-queue-list":
        _cmd_worktree_fleet_queue_list(args, repo_path=repo_root)
        return
    if action == "fleet-queue-process-next":
        _cmd_worktree_fleet_queue_process_next(args, repo_path=repo_root)
        return

    from aragora.nomic.branch_coordinator import (
        BranchCoordinator,
        BranchCoordinatorConfig,
    )
    from aragora.nomic.meta_planner import Track

    config = BranchCoordinatorConfig(
        base_branch=base_branch,
        use_worktrees=True,
    )
    coordinator = BranchCoordinator(repo_path=repo_root, config=config)

    track_map = {t.value: t for t in Track}

    if action == "create":
        tracks = []
        for name in args.tracks:
            key = name.lower().strip()
            if key not in track_map:
                print(f"Error: Unknown track '{name}'. Valid: {', '.join(sorted(track_map))}")
                return
            tracks.append(track_map[key])

        config.max_parallel_branches = len(tracks)
        print(f"Creating {len(tracks)} worktree(s) from '{base_branch}'...\n")

        for track in tracks:
            goal = f"Session work on {track.value} track"
            branch = asyncio.run(coordinator.create_track_branch(track=track, goal=goal))
            wt_path = coordinator.get_worktree_path(branch)
            print(f"  [{track.value}]  {branch}")
            print(f"    Path: {wt_path}\n")

        print("Done. Open a session in each worktree path.")

    elif action == "list":
        worktrees = coordinator.list_worktrees()
        if not worktrees:
            print("No active worktrees.")
            return
        print(f"Active worktrees ({len(worktrees)}):\n")
        for wt in worktrees:
            track_label = f" [{wt.track}]" if wt.track else ""
            print(f"  {wt.branch_name}{track_label}")
            print(f"    Path: {wt.worktree_path}")
            if wt.created_at:
                print(f"    Created: {wt.created_at:%Y-%m-%d %H:%M}")
            print()

    elif action == "merge":
        branch = args.branch
        if not coordinator.branch_exists(branch):
            print(f"Error: Branch '{branch}' does not exist.")
            return

        if getattr(args, "test_first", False):
            wt_path = coordinator.get_worktree_path(branch) or repo_root
            result = subprocess.run(
                ["python", "-m", "pytest", "tests/", "-x", "-q", "--tb=short"],  # noqa: S607 -- fixed command
                cwd=wt_path,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                print("Tests FAILED. Aborting merge.")
                return
            print("Tests passed.")

        dry_run = getattr(args, "dry_run", False)
        merge_result = asyncio.run(coordinator.safe_merge(branch, dry_run=dry_run))
        if merge_result.success:
            if dry_run:
                print("Merge would succeed (no conflicts).")
            else:
                print(f"Merged: {merge_result.commit_sha[:12]}")
        else:
            print(f"Merge failed: {merge_result.error}")
            if merge_result.conflicts:
                for f in merge_result.conflicts:
                    print(f"  - {f}")

    elif action == "merge-all":
        worktrees = coordinator.list_worktrees()
        branches = [
            wt.branch_name for wt in worktrees if wt.branch_name not in (base_branch, "main")
        ]
        if not branches:
            print("No branches to merge.")
            return

        merged, failed = 0, 0
        for branch in branches:
            print(f"Merging: {branch}")
            if getattr(args, "test_first", False):
                wt_path = coordinator.get_worktree_path(branch) or repo_root
                result = subprocess.run(
                    ["python", "-m", "pytest", "tests/", "-x", "-q", "--tb=short"],  # noqa: S607 -- fixed command
                    cwd=wt_path,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    print("  Tests FAILED, skipping.")
                    failed += 1
                    continue

            merge_result = asyncio.run(coordinator.safe_merge(branch))
            if merge_result.success:
                print(f"  Merged: {merge_result.commit_sha[:12]}")
                merged += 1
            else:
                print(f"  FAILED: {merge_result.error}")
                failed += 1

        print(f"\n{merged} merged, {failed} failed")

    elif action == "conflicts":
        worktrees = coordinator.list_worktrees()
        branches = [
            wt.branch_name for wt in worktrees if wt.branch_name not in (base_branch, "main")
        ]
        if not branches:
            print("No active branches.")
            return

        conflicts = asyncio.run(coordinator.detect_conflicts(branches))
        if not conflicts:
            print("No conflicts detected.")
        else:
            print(f"{len(conflicts)} potential conflict(s):\n")
            for c in conflicts:
                print(f"  {c.source_branch} <-> {c.target_branch} [{c.severity}]")
                print(f"    Files: {', '.join(c.conflicting_files[:5])}")
                if c.resolution_hint:
                    print(f"    Hint: {c.resolution_hint}")
                print()

    elif action == "cleanup":
        deleted = coordinator.cleanup_branches()
        removed = coordinator.cleanup_worktrees()
        print(f"Deleted {deleted} merged branch(es), removed {removed} worktree(s).")


def _cmd_worktree_fleet_status(
    args: argparse.Namespace, *, repo_path: Path, base_branch: str
) -> None:
    """Show active session state and recent logs across all git worktrees."""
    tail_count = max(0, int(getattr(args, "tail", 500)))
    rows = build_fleet_rows(repo_path, base_branch=base_branch, tail=tail_count)
    store = FleetCoordinationStore(repo_path)
    claims = store.list_claims()
    queue = store.list_merge_queue()
    try:
        from aragora.nomic.dev_coordination import DevCoordinationStore

        coordination_summary = DevCoordinationStore(repo_root=repo_path).status_summary()
    except (ImportError, RuntimeError, OSError, ValueError) as exc:
        coordination_summary = {"error": str(exc), "counts": {}}
    claims_by_session: dict[str, list[str]] = {}
    for claim in claims:
        sid = str(claim.get("session_id", "")).strip()
        if not sid:
            continue
        claims_by_session.setdefault(sid, []).append(str(claim.get("path", "")))
    queue_by_session: dict[str, list[str]] = {}
    for item in queue:
        sid = str(item.get("session_id", "")).strip()
        if not sid:
            continue
        queue_by_session.setdefault(sid, []).append(str(item.get("branch", "")))
    for row in rows:
        session_id = str(row.get("session_id", ""))
        row["claimed_paths"] = sorted(claims_by_session.get(session_id, []))
        row["queued_branches"] = sorted(queue_by_session.get(session_id, []))
    integrator_view = build_integrator_view(
        worktrees=rows,
        claims=claims,
        merge_queue=queue,
        coordination=coordination_summary,
    )

    if getattr(args, "json", False):
        payload = {
            "repo_root": str(repo_path),
            "base_branch": base_branch,
            "tail": tail_count,
            "worktrees": rows,
            "claims": claims,
            "merge_queue": queue,
            "coordination": coordination_summary,
            "integrator_view": integrator_view,
        }
        print(json.dumps(payload, indent=2))
        return

    print(f"Fleet status: {len(rows)} worktree(s)")
    counts = coordination_summary.get("counts", {})
    if counts:
        print(
            "Coordination: "
            f"leases={counts.get('active_leases', 0)} "
            f"pending_integrations={counts.get('pending_integrations', 0)} "
            f"salvage={counts.get('open_salvage_candidates', 0)} "
            f"fleet_claims={counts.get('fleet_claims', 0)} "
            f"fleet_queue={counts.get('fleet_merge_queue', 0)}"
        )
    integrator_summary = integrator_view.get("summary", {})
    print(
        "Integrator: "
        f"ready={integrator_summary.get('ready_lanes', 0)} "
        f"review={integrator_summary.get('review_lanes', 0)} "
        f"blocked={integrator_summary.get('blocked_lanes', 0)} "
        f"stale={integrator_summary.get('stale_heartbeat_lanes', 0)} "
        f"collisions={integrator_summary.get('collision_lanes', 0)} "
        f"missing_receipts={integrator_summary.get('missing_receipt_lanes', 0)} "
        f"superseded={integrator_summary.get('superseded_lanes', 0)}"
    )
    for action in integrator_view.get("next_actions", [])[:3]:
        print(f"  next: {action}")
    if not rows:
        return

    for row in rows:
        pid_alive = bool(row["pid_alive"])
        has_lock = bool(row["has_lock"])
        status = "active" if has_lock and pid_alive else ("stale_lock" if has_lock else "idle")
        ahead = row["ahead"]
        behind = row["behind"]
        ahead_behind = "?"
        if isinstance(ahead, int) and isinstance(behind, int):
            ahead_behind = f"+{ahead}/-{behind}"

        print("")
        print(f"[{status}] {row['branch']}")
        print(f"  path: {row['path']}")
        print(f"  agent: {row.get('agent') or 'n/a'} mode: {row.get('mode') or 'n/a'}")
        print(f"  pid: {row.get('pid') or 'n/a'} alive: {pid_alive}")
        print(f"  dirty_files: {row['dirty_files']} ahead/behind({base_branch}): {ahead_behind}")
        print(f"  orchestrator: {row.get('orchestration_pattern') or 'generic'}")
        print(f"  last_activity: {row.get('last_activity') or 'n/a'}")
        lane = next(
            (
                item
                for item in integrator_view.get("lanes", [])
                if item.get("owner_session_id") == row.get("session_id")
                and item.get("worktree_path") == row.get("path")
            ),
            None,
        )
        if isinstance(lane, dict):
            print(
                f"  lease_health: {lane.get('lease_health', 'idle')} "
                f"merge_readiness: {lane.get('merge_readiness', 'unknown')}"
            )
            if lane.get("collisions"):
                print(f"  collisions: {', '.join(lane['collisions'])}")
            if lane.get("missing_receipt"):
                print("  receipt: missing")
            elif lane.get("receipt_id"):
                print(f"  receipt: {lane['receipt_id']}")
        claimed_paths = row.get("claimed_paths")
        if isinstance(claimed_paths, list) and claimed_paths:
            print(f"  claimed_paths({len(claimed_paths)}): {', '.join(claimed_paths[:8])}")
        queued_branches = row.get("queued_branches")
        if isinstance(queued_branches, list) and queued_branches:
            print(f"  merge_queue({len(queued_branches)}): {', '.join(queued_branches)}")
        if row.get("log_path"):
            print(f"  log: {row['log_path']}")
            tail_lines = row["log_tail"]
            if isinstance(tail_lines, list) and tail_lines:
                print(f"  log_tail(last {tail_count} lines):")
                for line in tail_lines:
                    print(f"    {line}")
            else:
                print("  log_tail: (empty)")
        else:
            print("  log: none")


def _cmd_worktree_fleet_claims(args: argparse.Namespace, *, repo_path: Path) -> None:
    """List ownership claims."""
    store = FleetCoordinationStore(repo_path)
    claims = store.list_claims()
    if getattr(args, "json", False):
        print(json.dumps({"repo_root": str(repo_path), "claims": claims}, indent=2))
        return
    print(f"Fleet claims: {len(claims)}")
    for claim in claims:
        print(
            f"  {claim.get('session_id', 'n/a')} -> {claim.get('path', '')} "
            f"[{claim.get('mode', 'exclusive')}]"
        )


def _cmd_worktree_fleet_claim(args: argparse.Namespace, *, repo_path: Path) -> None:
    """Claim ownership of files for a session."""
    store = FleetCoordinationStore(repo_path)
    result = store.claim_paths(
        session_id=str(args.session_id),
        paths=[str(path) for path in args.paths],
        branch=str(getattr(args, "branch", "") or ""),
        mode=str(args.mode),
    )
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return
    print(f"claimed={len(result.get('claimed', []))} conflicts={len(result.get('conflicts', []))}")
    for path in result.get("claimed", []):
        print(f"  claimed: {path}")
    for conflict in result.get("conflicts", []):
        owner = conflict.get("session_id", "unknown")
        path = conflict.get("path", "")
        print(f"  conflict: {path} (owned by {owner})")


def _cmd_worktree_fleet_release(args: argparse.Namespace, *, repo_path: Path) -> None:
    """Release ownership claims for a session."""
    store = FleetCoordinationStore(repo_path)
    paths = [str(path) for path in args.paths] if args.paths else None
    result = store.release_paths(session_id=str(args.session_id), paths=paths)
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return
    print(f"released={result.get('released', 0)} session={result.get('session_id', '')}")


def _cmd_worktree_fleet_queue_add(args: argparse.Namespace, *, repo_path: Path) -> None:
    """Enqueue merge work for a branch."""
    store = FleetCoordinationStore(repo_path)
    result = store.enqueue_merge(
        session_id=str(args.session_id),
        branch=str(args.branch),
        priority=int(getattr(args, "priority", 50)),
        title=str(getattr(args, "title", "")),
    )
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return
    item = result.get("item") or {}
    if result.get("duplicate"):
        print(f"already queued: {item.get('branch', '')} [{item.get('id', '')}]")
        return
    print(f"queued: {item.get('branch', '')} [{item.get('id', '')}]")


def _cmd_worktree_fleet_queue_list(args: argparse.Namespace, *, repo_path: Path) -> None:
    """List merge queue entries."""
    status_filter = str(getattr(args, "status", "")).strip() or None
    store = FleetCoordinationStore(repo_path)
    queue = store.list_merge_queue(status=status_filter)
    if getattr(args, "json", False):
        print(json.dumps({"repo_root": str(repo_path), "merge_queue": queue}, indent=2))
        return
    print(f"Merge queue: {len(queue)}")
    for item in queue:
        print(
            f"  {item.get('id', '')} {item.get('status', '')} "
            f"p{item.get('priority', 0)} {item.get('branch', '')} "
            f"(session={item.get('session_id', '')})"
        )


def _cmd_worktree_fleet_queue_process_next(args: argparse.Namespace, *, repo_path: Path) -> None:
    """Process the next queued merge item with the fleet integration worker."""
    worker = FleetIntegrationWorker(
        repo_path=repo_path,
        config=FleetIntegrationWorkerConfig(
            target_branch=str(getattr(args, "target_branch", "main")),
            execute_with_test_gate=bool(getattr(args, "test_gate", False)),
        ),
    )
    outcome = asyncio.run(
        worker.process_next(
            worker_session_id=str(args.worker_session_id),
            execute=bool(getattr(args, "execute", False)),
        )
    )
    payload = outcome.to_dict()
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return
    branch = payload.get("branch") or "(none)"
    item_id = payload.get("queue_item_id") or "-"
    print(
        f"{payload.get('action', 'processed')}: {branch} [{item_id}] "
        f"status={payload.get('queue_status', '')}"
    )
    if payload.get("error"):
        print(f"  error: {payload['error']}")
    conflicts = payload.get("conflicts") or []
    if conflicts:
        print(f"  conflicts({len(conflicts)}): {', '.join(str(item) for item in conflicts)}")


def _cmd_worktree_autopilot(args: argparse.Namespace, *, repo_path: Path, base_branch: str) -> None:
    """Run codex worktree autopilot through the main Aragora CLI."""
    request = AutopilotRequest(
        action=args.auto_action,
        managed_dir=args.managed_dir,
        base_branch=base_branch,
        agent=args.agent,
        session_id=args.session_id,
        force_new=args.force_new,
        strategy=args.strategy,
        reconcile=args.reconcile,
        reconcile_all=args.all,
        path=args.path,
        ttl_hours=args.ttl_hours,
        force_unmerged=args.force_unmerged,
        delete_branches=args.delete_branches,
        json_output=args.json,
        print_path=args.print_path,
    )

    try:
        result = run_autopilot(
            repo_root=repo_path, request=request, python_executable=sys.executable
        )
    except FileNotFoundError as exc:
        print(f"Error: autopilot script not found at {exc}")
        return

    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.stderr.strip():
        print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode != 0:
        print(f"Autopilot command failed with exit code {result.returncode}")
