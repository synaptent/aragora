#!/usr/bin/env python3
"""Worktree Session Manager for multi-agent development.

Wraps BranchCoordinator to create, list, merge, and clean up git worktrees
for isolated parallel Claude Code sessions.

Usage:
    # Create worktrees for specific tracks
    python scripts/worktree_sessions.py create --tracks sme developer qa security

    # List active worktrees with status
    python scripts/worktree_sessions.py list

    # Merge a completed worktree back to main (runs tests first)
    python scripts/worktree_sessions.py merge dev/sme-improve-dashboard-0215

    # Merge ALL completed worktrees
    python scripts/worktree_sessions.py merge-all --test-first

    # Show conflict report across all active worktrees
    python scripts/worktree_sessions.py conflicts

    # Clean up merged worktrees
    python scripts/worktree_sessions.py cleanup
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

# Add project root to path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from aragora.nomic.branch_coordinator import (
    BranchCoordinator,
    BranchCoordinatorConfig,
)
from aragora.nomic.meta_planner import PrioritizedGoal, Track


# -------------------------------------------------------------------------
# Track mapping
# -------------------------------------------------------------------------

TRACK_MAP: dict[str, Track] = {t.value: t for t in Track}

VALID_TRACKS = sorted(TRACK_MAP.keys())


def _resolve_tracks(names: list[str]) -> list[Track]:
    """Resolve track name strings to Track enum values."""
    tracks: list[Track] = []
    for name in names:
        key = name.lower().strip()
        if key not in TRACK_MAP:
            print(f"Error: Unknown track '{name}'. Valid: {', '.join(VALID_TRACKS)}")
            sys.exit(1)
        tracks.append(TRACK_MAP[key])
    return tracks


# -------------------------------------------------------------------------
# Subcommands
# -------------------------------------------------------------------------


def cmd_create(args: argparse.Namespace) -> int:
    """Create worktrees for the specified tracks."""
    tracks = _resolve_tracks(args.tracks)
    repo_path = Path(args.repo).resolve()
    base_branch = args.base

    config = BranchCoordinatorConfig(
        base_branch=base_branch,
        use_worktrees=True,
        max_parallel_branches=len(tracks),
    )
    coordinator = BranchCoordinator(repo_path=repo_path, config=config)

    print(f"Creating {len(tracks)} worktree(s) from '{base_branch}'...\n")

    for track in tracks:
        goal = f"Session work on {track.value} track"
        branch = asyncio.run(coordinator.create_track_branch(track=track, goal=goal))
        wt_path = coordinator.get_worktree_path(branch)
        print(f"  [{track.value}]")
        print(f"    Branch:   {branch}")
        print(f"    Path:     {wt_path}")
        print()

    print("Done. Open a Claude Code session in each worktree path above.")
    print("When finished, run:  python scripts/worktree_sessions.py merge-all --test-first")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List all active worktrees."""
    repo_path = Path(args.repo).resolve()
    config = BranchCoordinatorConfig(use_worktrees=True)
    coordinator = BranchCoordinator(repo_path=repo_path, config=config)

    worktrees = coordinator.list_worktrees()

    if not worktrees:
        print("No active worktrees found.")
        return 0

    print(f"Active worktrees ({len(worktrees)}):\n")
    for wt in worktrees:
        track_label = f" [{wt.track}]" if wt.track else ""
        created = f"  Created: {wt.created_at:%Y-%m-%d %H:%M}" if wt.created_at else ""
        print(f"  {wt.branch_name}{track_label}")
        print(f"    Path: {wt.worktree_path}{created}")
        # Show uncommitted changes count
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=wt.worktree_path,
                capture_output=True,
                text=True,
                check=False,
            )
            changes = len([l for l in result.stdout.strip().split("\n") if l.strip()])
            if changes:
                print(f"    Uncommitted changes: {changes} file(s)")
        except (subprocess.SubprocessError, OSError):
            pass
        print()

    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    """Merge a single branch back to base."""
    repo_path = Path(args.repo).resolve()
    branch = args.branch
    base_branch = args.base
    test_first = args.test_first
    dry_run = args.dry_run

    config = BranchCoordinatorConfig(
        base_branch=base_branch,
        use_worktrees=True,
    )
    coordinator = BranchCoordinator(repo_path=repo_path, config=config)

    if not coordinator.branch_exists(branch):
        print(f"Error: Branch '{branch}' does not exist.")
        return 1

    # Scope guard: check for cross-track file modifications
    try:
        from aragora.nomic.scope_guard import ScopeGuard

        guard = ScopeGuard(repo_path=repo_path, mode="warn")
        track_name = guard.detect_track_from_branch(branch)
        if track_name:
            wt_path = coordinator.get_worktree_path(branch) or repo_path
            # Get changed files in the branch
            changed_result = subprocess.run(
                ["git", "diff", "--name-only", f"{base_branch}...HEAD"],
                cwd=wt_path,
                capture_output=True,
                text=True,
                check=False,
            )
            changed = [f for f in changed_result.stdout.strip().split("\n") if f]
            if changed:
                violations = guard.check_files(changed, track=track_name)
                if violations:
                    print(f"Scope warnings for track '{track_name}':")
                    for v in violations[:10]:
                        severity = "BLOCK" if v.severity == "block" else "WARN"
                        print(f"  [{severity}] {v.file_path}: {v.violation_type}")
                    blocking = [v for v in violations if v.severity == "block"]
                    if blocking:
                        print(f"\n{len(blocking)} blocking violation(s). Use --force to override.")
                        if not getattr(args, "force", False):
                            return 1
                    print()
    except ImportError:
        pass

    # Run tests if requested
    if test_first:
        print(f"Running tests on '{branch}'...")
        wt_path = coordinator.get_worktree_path(branch) or repo_path
        test_result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-x", "-q", "--tb=short"],
            cwd=wt_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if test_result.returncode != 0:
            print("Tests FAILED. Aborting merge.\n")
            print(
                test_result.stdout[-500:] if len(test_result.stdout) > 500 else test_result.stdout
            )
            return 1
        print("Tests passed.\n")

    # Check CI status if gh CLI is available
    try:
        from aragora.nomic.ci_feedback import CIResultCollector

        ci_collector = CIResultCollector()
        ci_result = ci_collector.get_latest_result(branch)
        if ci_result is not None:
            if ci_result.conclusion == "success":
                print(f"CI check passed for '{branch}'.")
            else:
                print(f"WARNING: CI {ci_result.conclusion} for '{branch}'.")
    except ImportError:
        pass

    action = "Dry-run merge" if dry_run else "Merging"
    print(f"{action}: {branch} -> {base_branch}")

    result = asyncio.run(coordinator.safe_merge(branch, dry_run=dry_run))

    if result.success:
        if dry_run:
            print("Merge would succeed (no conflicts).")
        else:
            print(f"Merged successfully. Commit: {(result.commit_sha or 'unknown')[:12]}")
    else:
        print(f"Merge failed: {result.error}")
        if result.conflicts:
            print("Conflicting files:")
            for f in result.conflicts:
                print(f"  - {f}")
        return 1

    return 0


def cmd_merge_all(args: argparse.Namespace) -> int:
    """Merge all completed worktree branches."""
    repo_path = Path(args.repo).resolve()
    base_branch = args.base
    test_first = args.test_first

    config = BranchCoordinatorConfig(
        base_branch=base_branch,
        use_worktrees=True,
    )
    coordinator = BranchCoordinator(repo_path=repo_path, config=config)

    worktrees = coordinator.list_worktrees()
    # Filter out main worktree (the repo itself)
    branches = [
        wt.branch_name
        for wt in worktrees
        if wt.branch_name != base_branch and wt.branch_name != "main"
    ]

    if not branches:
        print("No worktree branches to merge.")
        return 0

    print(f"Found {len(branches)} branch(es) to merge:\n")
    for b in branches:
        print(f"  - {b}")
    print()

    # Check for conflicts first
    conflicts = asyncio.run(coordinator.detect_conflicts(branches))
    if conflicts:
        print(f"WARNING: {len(conflicts)} potential conflict(s) detected:\n")
        for c in conflicts:
            print(f"  {c.source_branch} <-> {c.target_branch} [{c.severity}]")
            for f in c.conflicting_files[:5]:
                print(f"    - {f}")
            if len(c.conflicting_files) > 5:
                print(f"    ... and {len(c.conflicting_files) - 5} more")
            print()

    # Merge each branch
    merged = 0
    failed = 0
    for branch in branches:
        print(f"Merging: {branch}")

        if test_first:
            wt_path = coordinator.get_worktree_path(branch) or repo_path
            test_result = subprocess.run(
                ["python", "-m", "pytest", "tests/", "-x", "-q", "--tb=short"],
                cwd=wt_path,
                capture_output=True,
                text=True,
                check=False,
            )
            if test_result.returncode != 0:
                print("  Tests FAILED, skipping merge.")
                failed += 1
                continue
            print("  Tests passed.")

        result = asyncio.run(coordinator.safe_merge(branch))
        if result.success:
            print(f"  Merged: {(result.commit_sha or 'unknown')[:12]}")
            merged += 1
        else:
            print(f"  FAILED: {result.error}")
            failed += 1

    print(f"\nSummary: {merged} merged, {failed} failed, {len(branches)} total")
    return 1 if failed > 0 else 0


def cmd_conflicts(args: argparse.Namespace) -> int:
    """Show conflict report across active worktrees."""
    repo_path = Path(args.repo).resolve()
    base_branch = args.base

    config = BranchCoordinatorConfig(
        base_branch=base_branch,
        use_worktrees=True,
    )
    coordinator = BranchCoordinator(repo_path=repo_path, config=config)

    worktrees = coordinator.list_worktrees()
    branches = [
        wt.branch_name
        for wt in worktrees
        if wt.branch_name != base_branch and wt.branch_name != "main"
    ]

    if not branches:
        print("No active worktree branches.")
        return 0

    print(f"Checking conflicts across {len(branches)} branch(es)...\n")

    conflicts = asyncio.run(coordinator.detect_conflicts(branches))

    if not conflicts:
        print("No conflicts detected.")
        return 0

    print(f"{len(conflicts)} potential conflict(s):\n")
    for c in conflicts:
        print(f"  {c.source_branch}")
        print(f"    <-> {c.target_branch}")
        print(f"    Severity: {c.severity}")
        print(f"    Files: {', '.join(c.conflicting_files[:5])}")
        if c.resolution_hint:
            print(f"    Hint: {c.resolution_hint}")
        print()

    return 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    """Clean up merged worktrees."""
    repo_path = Path(args.repo).resolve()
    base_branch = args.base

    config = BranchCoordinatorConfig(
        base_branch=base_branch,
        use_worktrees=True,
    )
    coordinator = BranchCoordinator(repo_path=repo_path, config=config)

    # Clean up merged branches
    deleted = coordinator.cleanup_branches()
    print(f"Deleted {deleted} merged branch(es).")

    # Prune worktrees
    removed = coordinator.cleanup_worktrees()
    print(f"Removed {removed} worktree(s).")

    # Git worktree prune for any stragglers
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=repo_path,
        capture_output=True,
        check=False,
    )

    total = deleted + removed
    if total == 0:
        print("Nothing to clean up.")
    else:
        print(f"\nTotal cleaned: {total}")

    return 0


# -------------------------------------------------------------------------
# Argument parser
# -------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="worktree_sessions",
        description="Manage git worktrees for parallel multi-agent development sessions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Workflow:
  1. Create worktrees:   python scripts/worktree_sessions.py create --tracks sme developer qa
  2. Open sessions:      cd .worktrees/dev-sme-*   (one terminal per worktree)
  3. Work independently: Each session commits to its branch
  4. Merge back:         python scripts/worktree_sessions.py merge-all --test-first
  5. Clean up:           python scripts/worktree_sessions.py cleanup
""",
    )
    parser.add_argument(
        "--repo",
        default=str(_project_root),
        help="Repository path (default: project root)",
    )
    parser.add_argument(
        "--base",
        default="main",
        help="Base branch (default: main)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # create
    create_p = subparsers.add_parser("create", help="Create worktrees for tracks")
    create_p.add_argument(
        "--tracks",
        "-t",
        nargs="+",
        required=True,
        help=f"Tracks to create worktrees for ({', '.join(VALID_TRACKS)})",
    )
    create_p.set_defaults(func=cmd_create)

    # list
    list_p = subparsers.add_parser("list", help="List active worktrees")
    list_p.set_defaults(func=cmd_list)

    # merge
    merge_p = subparsers.add_parser("merge", help="Merge a branch back to base")
    merge_p.add_argument("branch", help="Branch name to merge")
    merge_p.add_argument(
        "--test-first",
        action="store_true",
        help="Run tests before merging",
    )
    merge_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Check if merge would succeed without actually merging",
    )
    merge_p.set_defaults(func=cmd_merge)

    # merge-all
    merge_all_p = subparsers.add_parser("merge-all", help="Merge all worktree branches")
    merge_all_p.add_argument(
        "--test-first",
        action="store_true",
        help="Run tests on each branch before merging",
    )
    merge_all_p.set_defaults(func=cmd_merge_all)

    # conflicts
    conflicts_p = subparsers.add_parser("conflicts", help="Show conflict report")
    conflicts_p.set_defaults(func=cmd_conflicts)

    # cleanup
    cleanup_p = subparsers.add_parser("cleanup", help="Clean up merged worktrees")
    cleanup_p.set_defaults(func=cmd_cleanup)

    return parser


def main() -> int:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
