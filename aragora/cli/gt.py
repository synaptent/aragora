"""
Gas Town CLI (gt) - Multi-agent orchestration command line interface.

Commands:
    gt convoy list              # List active convoys
    gt convoy create <title>    # Create convoy with beads
    gt convoy status <id>       # Convoy progress
    gt bead list [--status]     # List beads with filters
    gt bead assign <id> <agent> # Assign bead to agent
    gt agent list               # List agents with roles
    gt agent promote <id> MAYOR # Promote agent role
    gt witness status           # Patrol status
    gt workspace init           # Initialize GT workspace

Usage via aragora CLI:
    aragora gt convoy list
    aragora gt bead list --status pending

Bead list will show convoy associations when convoys are available.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
from collections.abc import Coroutine
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _format_timestamp(dt: datetime) -> str:
    """Format datetime for display."""
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "N/A"


def _print_table(headers: list[str], rows: list[list[str]], widths: list[int] | None = None):
    """Print a simple text table."""
    if not widths:
        widths = [max(len(str(row[i])) for row in [headers] + rows) for i in range(len(headers))]

    # Header
    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(header_line)
    print("-" * len(header_line))

    # Rows
    for row in rows:
        print("  ".join(str(cell).ljust(w) for cell, w in zip(row, widths)))


def _resolve_gt_paths() -> tuple[Path, Path]:
    """Resolve bead and convoy storage paths."""
    from aragora.nomic.stores.paths import resolve_bead_and_convoy_dirs

    return resolve_bead_and_convoy_dirs(prefer_legacy_gt=True)


def _init_bead_store():
    """Initialize the canonical bead store."""
    from aragora.stores import get_canonical_workspace_stores

    bead_dir, convoy_dir = _resolve_gt_paths()
    stores = get_canonical_workspace_stores(
        bead_dir=str(bead_dir),
        convoy_dir=str(convoy_dir),
        git_enabled=True,
        auto_commit=False,
    )
    return _run_async(stores.bead_store())


def _init_convoy_manager(bead_store=None):
    """Initialize the canonical convoy manager."""
    from aragora.stores import get_canonical_workspace_stores

    bead_dir, convoy_dir = _resolve_gt_paths()
    stores = get_canonical_workspace_stores(
        bead_dir=str(bead_dir),
        convoy_dir=str(convoy_dir),
        git_enabled=True,
        auto_commit=False,
    )
    if bead_store is None:
        bead_store = _run_async(stores.bead_store())
    manager = _run_async(stores.convoy_manager())
    return bead_store, manager


def _normalize_priority(priority: str) -> str:
    """Normalize CLI priority to enum names."""
    key = priority.strip().upper()
    if key == "CRITICAL":
        return "URGENT"
    return key


# =============================================================================
# Convoy Commands
# =============================================================================


def cmd_convoy_list(args: argparse.Namespace) -> int:
    """List active convoys."""
    try:
        from aragora.nomic.stores import ConvoyStatus

        _, manager = _init_convoy_manager()

        # Filter by status if specified
        status_filter = None
        if args.status:
            try:
                status_filter = ConvoyStatus(args.status)
            except ValueError:
                print(f"Invalid status: {args.status}")
                print(f"Valid: {', '.join(s.value for s in ConvoyStatus)}")
                return 1

        convoys = _run_async(manager.list_convoys(status=status_filter))

        if not convoys:
            print("No convoys found")
            return 0

        headers = ["ID", "Title", "Status", "Beads", "Progress", "Created"]
        rows = []
        for c in convoys[: args.limit]:
            progress = _run_async(manager.get_convoy_progress(c.id))
            progress_text = f"{progress.completed_beads}/{progress.total_beads}"
            rows.append(
                [
                    c.id[:8],
                    c.title[:30] if c.title else "Untitled",
                    c.status.value,
                    str(len(c.bead_ids)),
                    progress_text,
                    _format_timestamp(c.created_at),
                ]
            )

        print(f"Found {len(convoys)} convoy(s):\n")
        _print_table(headers, rows, [10, 32, 12, 8, 10, 20])
        return 0

    except ImportError as e:
        print(f"Gas Town modules not available: {e}")
        return 1
    except (OSError, RuntimeError, ValueError, KeyError) as e:
        print(f"Error listing convoys: {e}")
        return 1


def cmd_convoy_create(args: argparse.Namespace) -> int:
    """Create a new convoy."""
    try:
        from aragora.nomic.stores import (
            Bead,
            BeadPriority,
            BeadSpec,
            BeadType,
            ConvoyPriority,
            ConvoySpec,
        )

        bead_store, manager = _init_convoy_manager()

        # Parse beads from comma-separated list
        bead_specs = []
        if args.beads:
            for bead_title in args.beads.split(","):
                bead_title = bead_title.strip()
                if bead_title:
                    priority_key = _normalize_priority(args.priority)
                    bead_specs.append(
                        BeadSpec(
                            title=bead_title,
                            priority=BeadPriority[priority_key],
                        )
                    )

        if not bead_specs:
            print("Error: At least one bead is required (--beads task1,task2,...)")
            return 1

        priority_key = _normalize_priority(args.priority)
        spec = ConvoySpec(
            title=args.title,
            description=args.description or "",
            beads=bead_specs,
            priority=ConvoyPriority[priority_key],
        )

        bead_ids = []
        for bead_spec in spec.beads:
            bead_type = bead_spec.bead_type or BeadType.TASK
            if isinstance(bead_type, str):
                try:
                    bead_type = BeadType(bead_type)
                except ValueError:
                    bead_type = BeadType.TASK

            bead_priority = bead_spec.priority or BeadPriority[priority_key]
            if isinstance(bead_priority, int):
                bead_priority = BeadPriority(bead_priority)

            bead = Bead.create(
                bead_type=bead_type,
                title=bead_spec.title,
                description=bead_spec.description,
                priority=bead_priority,
                dependencies=list(bead_spec.dependencies),
                tags=list(bead_spec.tags),
                metadata=dict(bead_spec.metadata),
            )
            bead_id = _run_async(bead_store.create(bead))
            bead_ids.append(bead_id)

        convoy = _run_async(
            manager.create_convoy(
                title=spec.title,
                bead_ids=bead_ids,
                description=spec.description,
                priority=spec.priority or ConvoyPriority[priority_key],
                dependencies=list(spec.dependencies) if spec.dependencies else None,
                tags=list(spec.tags),
                metadata=dict(spec.metadata),
            )
        )

        print("Convoy created successfully!")
        print(f"  ID: {convoy.id}")
        print(f"  Title: {convoy.title}")
        print(f"  Beads: {len(convoy.bead_ids)}")
        print(f"  Status: {convoy.status.value}")
        return 0

    except ImportError as e:
        print(f"Gas Town modules not available: {e}")
        return 1
    except (OSError, RuntimeError, ValueError, KeyError) as e:
        print(f"Error creating convoy: {e}")
        return 1


def cmd_convoy_status(args: argparse.Namespace) -> int:
    """Get convoy status and progress."""
    try:
        bead_store, manager = _init_convoy_manager()
        convoy = _run_async(manager.get_convoy(args.convoy_id))

        if not convoy:
            print(f"Convoy not found: {args.convoy_id}")
            return 1

        progress = _run_async(manager.get_convoy_progress(convoy.id))

        print(f"Convoy: {convoy.title}")
        print(f"  ID: {convoy.id}")
        print(f"  Status: {convoy.status.value}")
        print(f"  Created: {_format_timestamp(convoy.created_at)}")
        print(f"  Progress: {progress.completed_beads}/{progress.total_beads} beads")

        if convoy.bead_ids:
            print("\nBeads:")
            for bead_id in convoy.bead_ids[:10]:
                bead = _run_async(bead_store.get(bead_id))
                if not bead:
                    continue
                status_icon = {
                    "pending": "[ ]",
                    "claimed": "[~]",
                    "running": "[~]",
                    "completed": "[x]",
                    "failed": "[!]",
                    "cancelled": "[-]",
                    "blocked": "[?]",
                }.get(bead.status.value, "[ ]")
                print(f"  {status_icon} {bead.title[:50]}")

            if len(convoy.bead_ids) > 10:
                print(f"  ... and {len(convoy.bead_ids) - 10} more")

        return 0

    except ImportError as e:
        print(f"Gas Town modules not available: {e}")
        return 1
    except (OSError, RuntimeError, ValueError, KeyError) as e:
        print(f"Error getting convoy status: {e}")
        return 1


# =============================================================================
# Bead Commands
# =============================================================================


def cmd_bead_list(args: argparse.Namespace) -> int:
    """List beads with optional filters."""
    try:
        from aragora.nomic.stores import BeadStatus

        # Filter by status if specified
        status_filter = None
        if args.status:
            try:
                status_filter = BeadStatus(args.status)
            except ValueError:
                print(f"Invalid status: {args.status}")
                print(f"Valid: {', '.join(s.value for s in BeadStatus)}")
                return 1

        bead_store = _init_bead_store()
        beads = _run_async(
            bead_store.list_beads(
                status=status_filter,
                limit=args.limit,
            )
        )

        convoy_map = {}
        if args.convoy:
            _, manager = _init_convoy_manager(bead_store)
            convoy = _run_async(manager.get_convoy(args.convoy))
            if not convoy:
                print(f"Convoy not found: {args.convoy}")
                return 1
            convoy_map = dict.fromkeys(convoy.bead_ids, convoy.id)
            beads = [b for b in beads if b.id in convoy_map]
        else:
            try:
                _, manager = _init_convoy_manager(bead_store)
                convoys = _run_async(manager.list_convoys())
                for convoy in convoys:
                    for bead_id in convoy.bead_ids:
                        convoy_map.setdefault(bead_id, convoy.id)
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.debug("Unable to load convoys for bead list: %s", e)

        if not beads:
            print("No beads found")
            return 0

        headers = ["ID", "Title", "Status", "Priority", "Assigned", "Convoy"]
        rows = []
        for b in beads:
            assigned = getattr(b, "claimed_by", None) or getattr(b, "assigned_to", None)
            convoy_id = getattr(b, "convoy_id", None) or convoy_map.get(b.id)
            priority_value = getattr(b, "priority", None)
            if priority_value is None:
                priority_label = "normal"
            elif hasattr(priority_value, "name"):
                priority_label = priority_value.name.lower()
            else:
                priority_label = str(priority_value)
            rows.append(
                [
                    b.id[:8],
                    b.title[:30] if b.title else "Untitled",
                    b.status.value,
                    priority_label,
                    assigned[:8] if assigned else "-",
                    convoy_id[:8] if convoy_id else "-",
                ]
            )

        print(f"Found {len(beads)} bead(s):\n")
        _print_table(headers, rows, [10, 32, 12, 10, 10, 10])
        return 0

    except ImportError as e:
        print(f"Gas Town modules not available: {e}")
        return 1
    except (OSError, RuntimeError, ValueError, KeyError) as e:
        print(f"Error listing beads: {e}")
        return 1


def cmd_bead_assign(args: argparse.Namespace) -> int:
    """Assign a bead to an agent."""
    try:
        bead_store = _init_bead_store()
        success = _run_async(bead_store.claim(args.bead_id, args.agent_id))

        if success:
            print(f"Bead {args.bead_id} assigned to agent {args.agent_id}")
            return 0
        else:
            print("Failed to assign bead")
            return 1

    except ImportError as e:
        print(f"Gas Town modules not available: {e}")
        return 1
    except (OSError, RuntimeError, ValueError, KeyError) as e:
        print(f"Error assigning bead: {e}")
        return 1


# =============================================================================
# Agent Commands
# =============================================================================


def cmd_agent_list(args: argparse.Namespace) -> int:
    """List agents with their roles."""
    try:
        from aragora.nomic.agent_roles import AgentHierarchy, AgentRole, RoleAssignment

        hierarchy = AgentHierarchy()
        _run_async(hierarchy.initialize())

        # Filter by role if specified
        role_filter: AgentRole | None = None
        if args.role:
            try:
                role_filter = AgentRole(args.role.lower())
            except ValueError:
                print(f"Invalid role: {args.role}")
                print(f"Valid: {', '.join(r.value for r in AgentRole)}")
                return 1

        agents: list[RoleAssignment]
        if role_filter is not None:
            agents = _run_async(hierarchy.get_agents_by_role(role_filter))
        else:
            # Get all agents by iterating through all roles (dedupe by agent_id).
            agents_by_id: dict[str, RoleAssignment] = {}
            for role in AgentRole:
                for agent in _run_async(hierarchy.get_agents_by_role(role)):
                    agents_by_id.setdefault(agent.agent_id, agent)
            agents = list(agents_by_id.values())

        if not agents:
            print("No agents found")
            return 0

        headers = ["Agent ID", "Role", "Supervised By", "Registered"]
        rows: list[list[str]] = []
        for a in agents:
            rows.append(
                [
                    a.agent_id[:20],
                    a.role.value.upper(),
                    a.supervised_by[:10] if a.supervised_by else "-",
                    _format_timestamp(a.assigned_at),
                ]
            )

        print(f"Found {len(agents)} agent(s):\n")
        _print_table(headers, rows, [22, 10, 12, 20])
        return 0

    except ImportError as e:
        print(f"Gas Town modules not available: {e}")
        return 1
    except (OSError, RuntimeError, ValueError, KeyError) as e:
        print(f"Error listing agents: {e}")
        return 1


def cmd_agent_promote(args: argparse.Namespace) -> int:
    """Promote an agent to a new role."""
    try:
        from aragora.nomic.agent_roles import AgentHierarchy, AgentRole

        # Parse role
        try:
            new_role = AgentRole(args.role.lower())
        except ValueError:
            print(f"Invalid role: {args.role}")
            print(f"Valid: {', '.join(r.value for r in AgentRole)}")
            return 1

        hierarchy = AgentHierarchy()
        _run_async(hierarchy.initialize())

        # Get the existing assignment
        existing = _run_async(hierarchy.get_assignment(args.agent_id))
        if not existing:
            print("Failed to promote agent (not found?)")
            return 1

        # Preserve existing assignment properties while changing the role
        _run_async(hierarchy.unregister_agent(args.agent_id))
        _run_async(
            hierarchy.register_agent(
                agent_id=existing.agent_id,
                role=new_role,
                supervised_by=existing.supervised_by,
                metadata=existing.metadata,
            )
        )

        print(f"Agent {args.agent_id} promoted to {new_role.value.upper()}")
        return 0

    except ImportError as e:
        print(f"Gas Town modules not available: {e}")
        return 1
    except (OSError, RuntimeError, ValueError, KeyError) as e:
        print(f"Error promoting agent: {e}")
        return 1


# =============================================================================
# Witness Commands
# =============================================================================


def cmd_witness_status(args: argparse.Namespace) -> int:
    """Get witness patrol status."""
    try:
        from aragora.server.startup import get_witness_behavior

        witness = get_witness_behavior()
        if not witness:
            print("Witness patrol not initialized")
            print("Start the server to enable witness patrol")
            return 1

        print("Witness Patrol Status")
        print("=" * 40)
        print(f"  Patrolling: {'Yes' if witness._running else 'No'}")
        print(f"  Patrol Interval: {witness.config.patrol_interval_seconds}s")
        print(f"  Heartbeat Timeout: {witness.config.heartbeat_timeout_seconds}s")

        # Try to get health report
        try:
            report = _run_async(witness.generate_health_report())
            print(f"\nHealth Report ({report.report_id[:8]}):")
            print(f"  Overall Status: {report.overall_status.value}")
            print(f"  Agents Checked: {len(report.agent_checks)}")
            print(f"  Convoys Checked: {len(report.convoy_checks)}")
            print(f"  Active Alerts: {len(report.alerts)}")

            if report.recommendations:
                print("\nRecommendations:")
                for rec in report.recommendations[:5]:
                    print(f"  - {rec}")
        except (OSError, RuntimeError, TypeError, ValueError, KeyError) as e:
            logger.debug("Could not generate health report: %s", e)

        return 0

    except ImportError as e:
        print(f"Witness module not available: {e}")
        return 1
    except (OSError, RuntimeError, TypeError, ValueError, KeyError) as e:
        print(f"Error getting witness status: {e}")
        return 1


# =============================================================================
# Workspace Commands
# =============================================================================


def cmd_workspace_init(args: argparse.Namespace) -> int:
    """Initialize a Gas Town workspace."""
    workspace_dir = Path(args.directory or ".").resolve()

    # Create GT directories
    gt_dirs = [
        workspace_dir / ".gt",
        workspace_dir / ".gt" / "convoys",
        workspace_dir / ".gt" / "beads",
        workspace_dir / ".gt" / "agents",
        workspace_dir / ".gt" / "hooks",
    ]

    for d in gt_dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Create config file
    config_file = workspace_dir / ".gt" / "config.json"
    if not config_file.exists() or args.force:
        config = {
            "version": "1.0",
            "workspace": str(workspace_dir),
            "created_at": datetime.now().isoformat(),
            "settings": {
                "auto_assign_beads": True,
                "max_concurrent_agents": 5,
                "witness_patrol_enabled": True,
            },
        }
        config_file.write_text(json.dumps(config, indent=2))

    print(f"Gas Town workspace initialized at: {workspace_dir}")
    print(f"  Config: {config_file}")
    print("\nNext steps:")
    print("  aragora gt convoy create 'My First Convoy' --beads task1,task2")
    print("  aragora gt agent list")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    """Run the Gastown state migration helper."""
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "gastown_migrate_state.py"
    if not script_path.exists():
        print("Migration helper not found in this installation.")
        return 1

    cmd = [sys.executable, str(script_path)]
    if args.source:
        cmd += ["--from", args.source]
    if args.target:
        cmd += ["--to", args.target]
    if args.mode:
        cmd += ["--mode", args.mode]
    if args.apply:
        cmd.append("--apply")

    result = subprocess.run(cmd, check=False)  # noqa: S603 -- subprocess with fixed args, no shell
    return result.returncode


# =============================================================================
# Main GT Command Handler
# =============================================================================


def add_gt_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Add GT subcommand to the main CLI parser."""
    gt_parser = subparsers.add_parser(
        "gt",
        help="Gas Town multi-agent orchestration",
        description="""
Gas Town (GT) - Multi-agent orchestration for complex tasks.

Organize work into Convoys (batch orders) containing Beads (work units).
Agents are assigned roles: MAYOR (coordinator), WITNESS (monitor),
POLECAT (ephemeral worker), or CREW (persistent worker).
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    gt_subparsers = gt_parser.add_subparsers(dest="gt_command", help="GT commands")

    # --- Convoy commands ---
    convoy_parser = gt_subparsers.add_parser("convoy", help="Manage convoys")
    convoy_subparsers = convoy_parser.add_subparsers(dest="convoy_action")

    # convoy list
    convoy_list = convoy_subparsers.add_parser("list", help="List convoys")
    convoy_list.add_argument("--status", "-s", help="Filter by status")
    convoy_list.add_argument("--limit", "-l", type=int, default=20, help="Max results")
    convoy_list.set_defaults(func=cmd_convoy_list)

    # convoy create
    convoy_create = convoy_subparsers.add_parser("create", help="Create a convoy")
    convoy_create.add_argument("title", help="Convoy title")
    convoy_create.add_argument("--beads", "-b", required=True, help="Comma-separated bead titles")
    convoy_create.add_argument("--description", "-d", help="Convoy description")
    convoy_create.add_argument(
        "--priority",
        "-p",
        default="normal",
        choices=["low", "normal", "high", "critical", "urgent"],
    )
    convoy_create.set_defaults(func=cmd_convoy_create)

    # convoy status
    convoy_status = convoy_subparsers.add_parser("status", help="Get convoy status")
    convoy_status.add_argument("convoy_id", help="Convoy ID")
    convoy_status.set_defaults(func=cmd_convoy_status)

    # --- Bead commands ---
    bead_parser = gt_subparsers.add_parser("bead", help="Manage beads")
    bead_subparsers = bead_parser.add_subparsers(dest="bead_action")

    # bead list
    bead_list = bead_subparsers.add_parser("list", help="List beads")
    bead_list.add_argument("--status", "-s", help="Filter by status")
    bead_list.add_argument("--convoy", "-c", help="Filter by convoy ID")
    bead_list.add_argument("--limit", "-l", type=int, default=20, help="Max results")
    bead_list.set_defaults(func=cmd_bead_list)

    # bead assign
    bead_assign = bead_subparsers.add_parser("assign", help="Assign bead to agent")
    bead_assign.add_argument("bead_id", help="Bead ID")
    bead_assign.add_argument("agent_id", help="Agent ID")
    bead_assign.set_defaults(func=cmd_bead_assign)

    # --- Agent commands ---
    agent_parser = gt_subparsers.add_parser("agent", help="Manage agents")
    agent_subparsers = agent_parser.add_subparsers(dest="agent_action")

    # agent list
    agent_list = agent_subparsers.add_parser("list", help="List agents")
    agent_list.add_argument("--role", "-r", help="Filter by role (mayor, witness, polecat, crew)")
    agent_list.set_defaults(func=cmd_agent_list)

    # agent promote
    agent_promote = agent_subparsers.add_parser("promote", help="Promote agent to role")
    agent_promote.add_argument("agent_id", help="Agent ID")
    agent_promote.add_argument("role", help="New role (mayor, witness, polecat, crew)")
    agent_promote.set_defaults(func=cmd_agent_promote)

    # --- Witness commands ---
    witness_parser = gt_subparsers.add_parser("witness", help="Witness patrol operations")
    witness_subparsers = witness_parser.add_subparsers(dest="witness_action")

    # witness status
    witness_status = witness_subparsers.add_parser("status", help="Get patrol status")
    witness_status.set_defaults(func=cmd_witness_status)

    # --- Workspace commands ---
    workspace_parser = gt_subparsers.add_parser("workspace", help="Workspace management")
    workspace_subparsers = workspace_parser.add_subparsers(dest="workspace_action")

    # workspace init
    workspace_init = workspace_subparsers.add_parser("init", help="Initialize workspace")
    workspace_init.add_argument("directory", nargs="?", help="Target directory")
    workspace_init.add_argument("--force", "-f", action="store_true", help="Overwrite existing")
    workspace_init.set_defaults(func=cmd_workspace_init)

    # --- Migration command ---
    migrate_parser = gt_subparsers.add_parser("migrate", help="Migrate legacy Gastown state")
    migrate_parser.add_argument("--from", dest="source", help="Legacy Gastown root dir")
    migrate_parser.add_argument("--to", dest="target", help="Target canonical store dir")
    migrate_parser.add_argument(
        "--mode",
        choices=["workspace", "coordinator"],
        default="workspace",
        help="Target layout for migration",
    )
    migrate_parser.add_argument("--apply", action="store_true", help="Apply changes")
    migrate_parser.set_defaults(func=cmd_migrate)


def cmd_gt(args: argparse.Namespace) -> int:
    """Handle the 'gt' command group."""
    if not hasattr(args, "func") or args.func is None:
        # No subcommand specified - show help
        print("Gas Town CLI - Multi-agent orchestration")
        print("\nUsage: aragora gt <command> [options]")
        print("\nCommands:")
        print("  convoy    Manage convoys (batch work orders)")
        print("  bead      Manage beads (individual work units)")
        print("  agent     Manage agents and roles")
        print("  witness   Witness patrol operations")
        print("  workspace Workspace management")
        print("  migrate   Migrate legacy Gastown state")
        print("\nRun 'aragora gt <command> --help' for more information")
        return 0

    return args.func(args)
