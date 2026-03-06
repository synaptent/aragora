"""
Coordinate CLI commands for multi-agent worktree coordination.

Provides CLI access to the worktree coordination infrastructure:
- aragora coordinate plan "goal"   - Decompose a goal into track-scoped subtasks
- aragora coordinate status        - Show worktree status and agent assignments
- aragora coordinate merge         - Merge completed worktrees back to main
- aragora coordinate sync          - Sync all worktrees with latest main
- aragora coordinate scope         - Check scope violations for current track
- aragora coordinate events        - View cross-worktree event bus
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def add_coordinate_parser(subparsers) -> None:
    """Add the 'coordinate' subcommand parser."""
    coord_parser = subparsers.add_parser(
        "coordinate",
        help="Multi-agent worktree coordination",
        description="Coordinate parallel agent work across isolated git worktrees",
    )

    coord_sub = coord_parser.add_subparsers(
        dest="coordinate_command",
        help="Coordination subcommands",
    )

    # --- plan ---
    plan_parser = coord_sub.add_parser(
        "plan",
        help="Decompose a goal into track-scoped subtasks",
    )
    plan_parser.add_argument("goal", help="Goal to decompose")
    plan_parser.add_argument(
        "--tracks",
        nargs="*",
        help="Limit to specific tracks (e.g., core qa security)",
    )
    plan_parser.add_argument(
        "--debate",
        action="store_true",
        help="Use debate-based decomposition (slower, more nuanced)",
    )
    plan_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output as JSON",
    )

    # --- status ---
    status_parser = coord_sub.add_parser(
        "status",
        help="Show worktree status and agent assignments",
    )
    status_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output as JSON",
    )

    # --- merge ---
    merge_parser = coord_sub.add_parser(
        "merge",
        help="Merge completed worktrees back to main",
    )
    merge_parser.add_argument(
        "--track",
        type=str,
        default=None,
        help="Specific track to merge (default: all ready tracks)",
    )
    merge_parser.add_argument(
        "--require-tests",
        action="store_true",
        default=True,
        help="Run tests before merging (default: True)",
    )
    merge_parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip test requirement",
    )
    merge_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be merged without merging",
    )

    # --- sync ---
    sync_parser = coord_sub.add_parser(
        "sync",
        help="Sync all worktrees with latest main",
    )
    sync_parser.add_argument(
        "--rebase",
        action="store_true",
        help="Rebase behind/diverged worktrees onto main",
    )

    # --- scope ---
    scope_parser = coord_sub.add_parser(
        "scope",
        help="Check scope violations for current track",
    )
    scope_parser.add_argument(
        "--track",
        type=str,
        default=None,
        help="Override track detection",
    )
    scope_parser.add_argument(
        "--mode",
        choices=["warn", "block"],
        default="warn",
        help="Violation severity mode (default: warn)",
    )

    # --- events ---
    events_parser = coord_sub.add_parser(
        "events",
        help="View cross-worktree event bus",
    )
    events_parser.add_argument(
        "--since",
        type=float,
        default=60.0,
        help="Show events from last N minutes (default: 60)",
    )
    events_parser.add_argument(
        "--type",
        dest="event_type",
        type=str,
        default=None,
        help="Filter by event type",
    )
    events_parser.add_argument(
        "--publish",
        type=str,
        default=None,
        help="Publish an event (format: type:track:message)",
    )
    events_parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Clean up old events",
    )

    # --- register ---
    register_parser = coord_sub.add_parser(
        "register",
        help="Register this session in the manifest",
    )
    register_parser.add_argument("track", help="Track name")
    register_parser.add_argument(
        "--goal",
        type=str,
        default="",
        help="Current goal description",
    )

    # Set the handler
    coord_parser.set_defaults(func=cmd_coordinate)


def cmd_coordinate(args: argparse.Namespace) -> None:
    """Handle 'coordinate' command — dispatch to subcommands."""
    subcommand = getattr(args, "coordinate_command", None)

    if subcommand is None:
        # No subcommand — show status by default
        _cmd_status(args)
        return

    dispatch = {
        "plan": _cmd_plan,
        "status": _cmd_status,
        "merge": _cmd_merge,
        "sync": _cmd_sync,
        "scope": _cmd_scope,
        "events": _cmd_events,
        "register": _cmd_register,
    }

    handler = dispatch.get(subcommand)
    if handler:
        handler(args)
    else:
        print(f"Unknown subcommand: {subcommand}")
        print("Available: plan, status, merge, sync, scope, events, register")


def _cmd_plan(args: argparse.Namespace) -> None:
    """Decompose a goal into track-scoped subtasks."""
    from aragora.nomic.task_decomposer import TaskDecomposer, DecomposerConfig

    goal = args.goal
    tracks = args.tracks
    use_debate = getattr(args, "debate", False)
    json_output = getattr(args, "json_output", False)

    print(f"Decomposing goal: {goal}")
    if tracks:
        print(f"Limiting to tracks: {', '.join(tracks)}")

    config = DecomposerConfig()
    decomposer = TaskDecomposer(config=config)

    if use_debate:
        print("Using debate-based decomposition...")
        import asyncio

        result = asyncio.run(decomposer.analyze_with_debate(goal))
    else:
        result = decomposer.analyze(goal)

    if json_output:
        output = {
            "goal": goal,
            "subtasks": [
                {
                    "id": st.id,
                    "description": st.description,
                    "track": st.track if hasattr(st, "track") else "unassigned",
                    "priority": st.priority if hasattr(st, "priority") else 0,
                    "dependencies": st.dependencies if hasattr(st, "dependencies") else [],
                }
                for st in result.subtasks
            ],
            "complexity_score": result.complexity_score
            if hasattr(result, "complexity_score")
            else 0,
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"\nDecomposition ({len(result.subtasks)} subtasks):")
        print("-" * 60)
        for i, st in enumerate(result.subtasks, 1):
            track_str = f" [{st.track}]" if hasattr(st, "track") and st.track else ""
            print(f"  {i}. {st.description}{track_str}")
            if hasattr(st, "dependencies") and st.dependencies:
                deps = ", ".join(str(d) for d in st.dependencies)
                print(f"     depends on: {deps}")


def _cmd_status(args: argparse.Namespace) -> None:
    """Show worktree status and agent assignments."""
    json_output = getattr(args, "json_output", False)
    repo_root = Path.cwd()

    # Get worktree list
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],  # noqa: S607 -- fixed command
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )

    worktrees: list[dict] = []
    current_path: str | None = None
    current_branch: str | None = None

    if result.returncode == 0:
        for line in result.stdout.split("\n"):
            line = line.strip()
            if line.startswith("worktree "):
                current_path = line[len("worktree ") :]
                current_branch = None
            elif line.startswith("branch refs/heads/"):
                current_branch = line[len("branch refs/heads/") :]
            elif line == "" and current_path and current_branch:
                if current_branch not in ("main", "master"):
                    # Get ahead/behind
                    ab_result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                        ["git", "rev-list", "--left-right", "--count", f"main...{current_branch}"],  # noqa: S607 -- fixed command
                        capture_output=True,
                        text=True,
                        cwd=repo_root,
                        check=False,
                    )
                    behind, ahead = 0, 0
                    if ab_result.returncode == 0:
                        parts = ab_result.stdout.strip().split()
                        if len(parts) == 2:
                            behind, ahead = int(parts[0]), int(parts[1])

                    worktrees.append(
                        {
                            "path": current_path,
                            "branch": current_branch,
                            "ahead": ahead,
                            "behind": behind,
                        }
                    )
                current_path = None
                current_branch = None

    # Get session manifest info
    try:
        from aragora.nomic.session_manifest import SessionManifest

        manifest = SessionManifest(repo_root=repo_root)
        sessions = manifest.list_active()
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        sessions = []

    # Get recent events
    try:
        from aragora.nomic.event_bus import EventBus

        bus = EventBus(repo_root=repo_root)
        recent_events = bus.poll(since_minutes=60)
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        recent_events = []

    # Get lease/integration/salvage state
    try:
        from aragora.nomic.dev_coordination import DevCoordinationStore

        coordination_summary = DevCoordinationStore(repo_root=repo_root).status_summary()
    except (ImportError, OSError, ValueError, TypeError, KeyError, RuntimeError):
        coordination_summary = {
            "active_leases": [],
            "pending_integrations": [],
            "open_salvage_candidates": [],
            "counts": {
                "active_leases": 0,
                "pending_integrations": 0,
                "open_salvage_candidates": 0,
            },
        }

    if json_output:
        print(
            json.dumps(
                {
                    "worktrees": worktrees,
                    "sessions": [
                        {"track": s.track, "goal": s.current_goal, "agent": s.agent}
                        for s in sessions
                    ],
                    "recent_events": len(recent_events),
                    "coordination": coordination_summary,
                },
                indent=2,
            )
        )
        return

    # Human-readable output
    print("\n" + "=" * 60)
    print("  Worktree Coordination Status")
    print("=" * 60)

    if worktrees:
        print(f"\n  {'Branch':<35} {'Ahead':>6} {'Behind':>7}")
        print("  " + "-" * 50)
        for wt in worktrees:
            status = ""
            if wt["behind"] > 0:
                status = " (needs sync)"
            print(f"  {wt['branch']:<35} {wt['ahead']:>6} {wt['behind']:>7}{status}")
    else:
        print("\n  No active worktrees found.")
        print("  Setup with: ./scripts/setup_worktrees.sh")

    if sessions:
        print(f"\n  Active Sessions ({len(sessions)}):")
        print("  " + "-" * 50)
        for s in sessions:
            goal = s.current_goal[:40] + "..." if len(s.current_goal) > 40 else s.current_goal
            print(f"  {s.track:<20} {s.agent:<10} {goal}")

    if recent_events:
        print(f"\n  Recent Events ({len(recent_events)} in last hour):")
        print("  " + "-" * 50)
        for e in recent_events[-5:]:
            print(f"  [{e.event_type}] {e.track}: {e.data.get('message', '')}")

    counts = coordination_summary.get("counts", {})
    print("\n  Coordination State:")
    print("  " + "-" * 50)
    print(
        "  "
        f"Active leases: {counts.get('active_leases', 0)} | "
        f"Pending integrations: {counts.get('pending_integrations', 0)} | "
        f"Open salvage candidates: {counts.get('open_salvage_candidates', 0)}"
    )

    print()


def _cmd_merge(args: argparse.Namespace) -> None:
    """Merge completed worktrees back to main."""
    track = getattr(args, "track", None)
    skip_tests = getattr(args, "skip_tests", False)
    dry_run = getattr(args, "dry_run", False)

    # Delegate to the existing merge script
    cmd = ["bash", "scripts/merge_worktrees.sh"]
    if track:
        # merge_worktrees.sh expects to find branches, not be given track names
        # as args — use --status to filter
        pass
    if skip_tests:
        cmd.append("--skip-tests")
    if dry_run:
        cmd.append("--dry-run")

    print("Running worktree merge...")
    result = subprocess.run(cmd, cwd=Path.cwd(), check=False)  # noqa: S603 -- subprocess with fixed args, no shell
    sys.exit(result.returncode)


def _cmd_sync(args: argparse.Namespace) -> None:
    """Sync all worktrees with latest main."""
    rebase = getattr(args, "rebase", False)

    cmd = [sys.executable, "scripts/worktree_sync.py"]
    if rebase:
        cmd.append("--rebase")

    result = subprocess.run(cmd, cwd=Path.cwd(), check=False)  # noqa: S603 -- subprocess with fixed args, no shell
    sys.exit(result.returncode)


def _cmd_scope(args: argparse.Namespace) -> None:
    """Check scope violations for current track."""
    from aragora.nomic.scope_guard import ScopeGuard

    track = getattr(args, "track", None)
    mode = getattr(args, "mode", "warn")

    guard = ScopeGuard(mode=mode)

    if track is None:
        track = guard.detect_track_from_branch()

    if track is None:
        print("Could not detect track from branch name. Use --track to specify.")
        return

    files = guard.get_changed_files()
    if not files:
        print(f"No changed files for track {track}.")
        return

    violations = guard.check_files(files, track)

    if not violations:
        print(f"All {len(files)} files are within {track} scope.")
        return

    block_count = 0
    for v in violations:
        icon = "BLOCK" if v.severity == "block" else "WARN"
        if v.severity == "block":
            block_count += 1
        print(f"  [{icon}] {v.message}")

    if block_count > 0:
        print(f"\n{block_count} scope violations found.")


def _cmd_events(args: argparse.Namespace) -> None:
    """View or interact with the cross-worktree event bus."""
    from aragora.nomic.event_bus import EventBus

    bus = EventBus(repo_root=Path.cwd())

    # Publish mode
    publish_str = getattr(args, "publish", None)
    if publish_str:
        parts = publish_str.split(":", 2)
        if len(parts) < 2:
            print("Format: --publish type:track[:message]")
            return
        event_type = parts[0]
        track = parts[1]
        message = parts[2] if len(parts) > 2 else ""
        event = bus.publish(event_type, track, data={"message": message})
        print(f"Published: {event.event_id}")
        return

    # Cleanup mode
    if getattr(args, "cleanup", False):
        cleaned = bus.cleanup()
        print(f"Cleaned up {cleaned} old events.")
        return

    # View mode
    since = getattr(args, "since", 60.0)
    event_type = getattr(args, "event_type", None)

    events = bus.poll(since_minutes=since, event_type=event_type)

    if not events:
        print(f"No events in the last {since:.0f} minutes.")
        return

    print(f"\nEvents (last {since:.0f} minutes):")
    print("-" * 60)
    for e in events:
        msg = e.data.get("message", "")
        files = e.data.get("files", [])
        detail = msg or (f"files: {', '.join(files[:3])}" if files else "")
        print(f"  [{e.event_type:<18}] {e.track:<15} {detail}")
        print(f"    {e.timestamp}")


def _cmd_register(args: argparse.Namespace) -> None:
    """Register this session in the manifest."""
    from aragora.nomic.session_manifest import SessionManifest

    track = args.track
    goal = getattr(args, "goal", "")

    manifest = SessionManifest(repo_root=Path.cwd())
    entry = manifest.register(track, goal=goal)
    print(f"Registered session: {entry.track}")
    print(f"  Worktree: {entry.worktree}")
    print(f"  Goal: {entry.current_goal or '(none)'}")
    print(f"  PID: {entry.pid}")


__all__ = [
    "add_coordinate_parser",
    "cmd_coordinate",
]
