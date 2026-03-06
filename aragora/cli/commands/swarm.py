"""Swarm Commander CLI command.

Launches the full swarm lifecycle: interrogate -> spec -> dispatch -> report.

Usage:
    aragora swarm "Make the dashboard faster"
    aragora swarm "Fix tests" --skip-interrogation
    aragora swarm --spec my-spec.yaml
    aragora swarm "Add auth" --budget-limit 10
    aragora swarm "Improve UX" --dry-run
    aragora swarm "Build feature" --profile cto
    aragora swarm --from-obsidian ~/vault
    aragora swarm "Improve tests" --autonomy metrics
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4


def _resolve_swarm_action_goal(args: argparse.Namespace) -> tuple[str, str | None]:
    first = getattr(args, "swarm_action_or_goal", None)
    second = getattr(args, "swarm_goal", None)
    if first in {"run", "status", "reconcile"}:
        return str(first), second
    return "run", first


def _print_supervisor_run(run: dict[str, object]) -> None:
    work_orders = (
        list(run.get("work_orders", [])) if isinstance(run.get("work_orders"), list) else []
    )
    counts: dict[str, int] = {}
    for item in work_orders:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    counts_text = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"
    print(f"run_id={run.get('run_id', '')}")
    print(f"status={run.get('status', '')} target_branch={run.get('target_branch', '')}")
    print(f"goal={run.get('goal', '')}")
    print(f"work_orders={len(work_orders)} [{counts_text}]")


def cmd_swarm(args: argparse.Namespace) -> None:
    """Handle 'swarm' command."""
    from aragora.swarm import (
        SwarmApprovalPolicy,
        SwarmCommander,
        SwarmCommanderConfig,
        SwarmReconciler,
        SwarmSpec,
        SwarmSupervisor,
    )
    from aragora.swarm.config import (
        AutonomyLevel,
        InterrogatorConfig,
        UserProfile,
    )

    action, goal = _resolve_swarm_action_goal(args)
    spec_file = getattr(args, "spec", None)
    skip_interrogation = getattr(args, "skip_interrogation", False)
    dry_run = getattr(args, "dry_run", False)
    budget_limit = getattr(args, "budget_limit", 50.0)
    require_approval = getattr(args, "require_approval", False)
    max_parallel = getattr(args, "max_parallel", 20)
    concurrency_cap = min(max(1, int(getattr(args, "concurrency_cap", 8))), 8)
    no_loop = getattr(args, "no_loop", False)
    target_branch = getattr(args, "target_branch", "main")
    managed_dir_pattern = getattr(args, "managed_dir_pattern", ".worktrees/{agent}-auto")
    as_json = bool(getattr(args, "json", False))
    run_id = getattr(args, "run_id", None)
    refresh_scaling = bool(getattr(args, "refresh_scaling", False))
    no_dispatch = bool(getattr(args, "no_dispatch", False))
    watch = bool(getattr(args, "watch", False))
    interval_seconds = float(getattr(args, "interval_seconds", 5.0) or 5.0)
    max_ticks = getattr(args, "max_ticks", None)
    all_runs = bool(getattr(args, "all_runs", False))
    dispatch_only = bool(getattr(args, "dispatch_only", False))
    no_wait = bool(getattr(args, "no_wait", False))
    dispatch_workers = not no_dispatch
    if dispatch_only:
        no_wait = True

    # Phase 2: User profile
    profile_str = getattr(args, "profile", "ceo")
    profile_map = {
        "ceo": UserProfile.CEO,
        "cto": UserProfile.CTO,
        "developer": UserProfile.DEVELOPER,
        "power-user": UserProfile.POWER_USER,
    }
    user_profile = profile_map.get(profile_str, UserProfile.CEO)

    # Phase 4: Obsidian
    from_obsidian = getattr(args, "from_obsidian", None)
    obsidian_vault = getattr(args, "obsidian_vault", None)
    no_obsidian_receipts = getattr(args, "no_obsidian_receipts", False)

    # Phase 6: Autonomy
    autonomy_str = getattr(args, "autonomy", "propose")
    autonomy_map = {
        "full-auto": AutonomyLevel.FULL_AUTO,
        "propose": AutonomyLevel.PROPOSE_APPROVE,
        "guided": AutonomyLevel.HUMAN_GUIDED,
        "metrics": AutonomyLevel.METRICS_DRIVEN,
    }
    autonomy_level = autonomy_map.get(autonomy_str, AutonomyLevel.PROPOSE_APPROVE)

    if action == "status":
        supervisor = SwarmSupervisor(repo_root=Path.cwd())
        payload = supervisor.status_summary(
            run_id=run_id,
            limit=int(getattr(args, "status_limit", 20)),
            refresh_scaling=refresh_scaling,
        )
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                "runs={runs} queued={queued} leased={leased} completed={completed}".format(
                    runs=payload["counts"].get("runs", 0),
                    queued=payload["counts"].get("queued_work_orders", 0),
                    leased=payload["counts"].get("leased_work_orders", 0),
                    completed=payload["counts"].get("completed_work_orders", 0),
                )
            )
            for run in payload.get("runs", []):
                if isinstance(run, dict):
                    print("---")
                    _print_supervisor_run(run)
        return

    if action == "reconcile":
        reconciler = SwarmReconciler(repo_root=Path.cwd())
        if all_runs:
            runs = asyncio.run(
                reconciler.tick_open_runs(limit=int(getattr(args, "status_limit", 20)))
            )
            payload = {"runs": [run.to_dict() for run in runs], "count": len(runs)}
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(f"runs={payload['count']}")
                for run in payload["runs"]:
                    print("---")
                    _print_supervisor_run(run)
            return
        if not run_id:
            print("Error: provide --run-id or --all-runs for 'reconcile'")
            return
        run = asyncio.run(
            reconciler.watch_run(
                run_id,
                interval_seconds=interval_seconds,
                max_ticks=max_ticks,
            )
            if watch
            else reconciler.tick_run(run_id)
        )
        if as_json:
            print(json.dumps(run.to_dict(), indent=2))
        else:
            _print_supervisor_run(run.to_dict())
        return

    if not goal and not spec_file and not from_obsidian:
        print("Error: provide a goal or --spec file (or --from-obsidian vault)")
        print('Usage: aragora swarm run "your goal here"')
        return

    config = SwarmCommanderConfig(
        interrogator=InterrogatorConfig(user_profile=user_profile),
        budget_limit_usd=budget_limit,
        require_approval=require_approval,
        max_parallel_tasks=max_parallel,
        iterative_mode=not no_loop,
        user_profile=user_profile,
        obsidian_vault_path=obsidian_vault or from_obsidian,
        obsidian_write_receipts=not no_obsidian_receipts,
        autonomy_level=autonomy_level,
    )
    commander = SwarmCommander(config=config)
    approval_policy = SwarmApprovalPolicy(
        require_merge_approval=True,
        require_external_action_approval=True,
    )

    # Phase 4: Load goals from Obsidian
    if from_obsidian and not goal:
        goals = asyncio.run(commander._load_from_obsidian(from_obsidian))
        if goals:
            goal = goals[0]  # Use first tagged note as goal
            print(f"\nLoaded goal from Obsidian: {goal[:100]}...")
        else:
            print("No #swarm tagged notes found in Obsidian vault")
            return

    if spec_file:
        spec_path = Path(spec_file)
        if not spec_path.exists():
            print(f"Error: spec file not found: {spec_file}")
            return
        spec = SwarmSpec.from_yaml(spec_path.read_text())
        print(f"\nLoaded spec from {spec_file}")
        print(spec.summary())
        run = asyncio.run(
            commander.run_supervised_from_spec(
                spec,
                repo_path=Path.cwd(),
                target_branch=target_branch,
                max_concurrency=concurrency_cap,
                managed_dir_pattern=managed_dir_pattern,
                approval_policy=approval_policy,
                dispatch=dispatch_workers,
                wait=not no_wait,
                interval_seconds=interval_seconds,
                max_ticks=max_ticks,
            )
        )
        if as_json:
            print(json.dumps(run.to_dict(), indent=2))
        else:
            _print_supervisor_run(run.to_dict())
    elif dry_run:
        if skip_interrogation:
            spec = SwarmSpec(
                id=str(uuid4()),
                created_at=datetime.now(timezone.utc),
                raw_goal=goal,
                refined_goal=goal,
                budget_limit_usd=budget_limit,
                requires_approval=require_approval,
                interrogation_turns=0,
                user_expertise="developer",
            )
            print("\n[DRY RUN] Skipping interrogation and building a direct spec.\n")
            print(spec.to_json(indent=2))
        else:
            spec = asyncio.run(commander.dry_run(goal))
        save_path = getattr(args, "save_spec", None)
        if save_path:
            Path(save_path).write_text(spec.to_yaml())
            print(f"\nSpec saved to {save_path}")
    elif skip_interrogation:
        spec = SwarmSpec(
            id=str(uuid4()),
            created_at=datetime.now(timezone.utc),
            raw_goal=goal,
            refined_goal=goal,
            budget_limit_usd=budget_limit,
            requires_approval=require_approval,
            interrogation_turns=0,
            user_expertise="developer",
        )
        print("\nSkipping interrogation (developer mode)")
        print(spec.summary())
        run = asyncio.run(
            commander.run_supervised_from_spec(
                spec,
                repo_path=Path.cwd(),
                target_branch=target_branch,
                max_concurrency=concurrency_cap,
                managed_dir_pattern=managed_dir_pattern,
                approval_policy=approval_policy,
                dispatch=dispatch_workers,
                wait=not no_wait,
                interval_seconds=interval_seconds,
                max_ticks=max_ticks,
            )
        )
        if as_json:
            print(json.dumps(run.to_dict(), indent=2))
        else:
            _print_supervisor_run(run.to_dict())
    else:
        run = asyncio.run(
            commander.run_supervised(
                goal,
                repo_path=Path.cwd(),
                target_branch=target_branch,
                max_concurrency=concurrency_cap,
                managed_dir_pattern=managed_dir_pattern,
                approval_policy=approval_policy,
                dispatch=dispatch_workers,
                wait=not no_wait,
                interval_seconds=interval_seconds,
                max_ticks=max_ticks,
            )
        )
        if as_json:
            print(json.dumps(run.to_dict(), indent=2))
        else:
            _print_supervisor_run(run.to_dict())
