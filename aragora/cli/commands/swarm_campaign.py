"""``aragora swarm campaign`` subcommand.

``aragora.cli.commands.swarm`` dispatches ``swarm campaign`` here and re-exports
``_run_campaign_action``. The campaign classes are imported when the command
runs, so tests patch them on ``aragora.swarm.campaign``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]


def _run_campaign_action(
    args: argparse.Namespace,
    *,
    goal: str | None,
    target_branch: str,
    as_json: bool,
) -> None:
    """Handle ``aragora swarm campaign [plan|run|execute|status|review|sync-issues]``."""

    from aragora.swarm.campaign import (
        CampaignExecutor,
        CampaignPlanner,
        DEFAULT_CAMPAIGN_MANIFEST,
        load_campaign_manifest,
        locked_manifest_path,
        save_campaign_manifest,
    )

    payload: JsonDict

    subaction = str(goal or "status").strip().lower()
    manifest_path = Path(getattr(args, "manifest", None) or DEFAULT_CAMPAIGN_MANIFEST).resolve()
    output_path = Path(getattr(args, "output", None) or manifest_path).resolve()

    def _campaign_input_count() -> int:
        return sum(
            1
            for value in (
                getattr(args, "source_file", None),
                getattr(args, "issue_list", None),
                getattr(args, "github_query", None),
            )
            if value
        )

    def _campaign_planner(parallel_default: int = 1):
        return CampaignPlanner(
            repo_root=Path.cwd(),
            planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
            planner_strategy=str(getattr(args, "planner_strategy", "heuristic") or "heuristic"),
            worker_model=str(getattr(args, "worker_model", "codex") or "codex"),
            review_model=str(getattr(args, "review_model", "claude") or "claude"),
            enforce_cross_model_review=not bool(getattr(args, "allow_same_model_review", False)),
            budget_limit_usd=float(getattr(args, "budget_limit", 50.0) or 50.0),
            max_parallel_ready_projects=int(
                getattr(args, "max_parallel_ready_projects", parallel_default) or parallel_default
            ),
            experiment_id=str(getattr(args, "experiment_id", "")).strip() or None,
            experiment_label=str(getattr(args, "experiment_label", "")).strip() or None,
        )

    def _plan_campaign(planner):
        source_file = getattr(args, "source_file", None)
        issue_list = getattr(args, "issue_list", None)
        github_query = getattr(args, "github_query", None)
        if source_file:
            return planner.plan_from_source_file(Path(source_file).resolve())
        if issue_list:
            issue_numbers = [
                int(item.strip()) for item in str(issue_list).split(",") if item.strip()
            ]
            return planner.plan_from_issue_list(
                issue_numbers,
                repo=getattr(args, "boss_repo", None),
            )
        if github_query:
            return planner.plan_from_github_query(
                str(github_query),
                repo=getattr(args, "boss_repo", None),
            )
        raise ValueError(
            "campaign plan requires exactly one of --source-file, --issue-list, or --github-query"
        )

    if subaction == "plan":
        if _campaign_input_count() != 1:
            raise ValueError(
                "campaign plan requires exactly one of --source-file, --issue-list, or --github-query"
            )
        planner = _campaign_planner(parallel_default=1)
        manifest = _plan_campaign(planner)
        with locked_manifest_path(output_path):
            save_campaign_manifest(output_path, manifest)
        payload = {
            "mode": "campaign-plan",
            "manifest_path": str(output_path),
            **manifest.to_dict(),
        }
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"campaign_id={manifest.campaign_id}")
            print(f"manifest={output_path}")
            print(
                f"projects={len(manifest.projects)} budget=${manifest.budget_limit_usd:.2f} "
                f"worker={manifest.worker_model} review={manifest.review_model}"
            )
            for finding in manifest.planning_findings[:5]:
                print(f"  finding: {finding}")
        return

    if subaction == "run":
        # Unified pipeline: plan once into a canonical manifest, then execute exactly one iteration.
        source_count = _campaign_input_count()
        run_manifest_path = manifest_path
        invocation_mode = "resumed"
        if manifest_path.exists():
            if source_count > 0:
                raise ValueError(
                    "campaign run: cannot supply --source-file, --issue-list, or "
                    "--github-query when resuming from an existing manifest"
                )
            if not as_json:
                print(f"Resuming from existing manifest: {manifest_path}")
        else:
            if source_count == 0:
                raise ValueError(
                    "campaign run requires an existing manifest or one of "
                    "--source-file, --issue-list, --github-query"
                )
            if source_count != 1:
                raise ValueError(
                    "campaign run requires exactly one of --source-file, --issue-list, or "
                    "--github-query when the manifest does not exist"
                )
            planner = _campaign_planner(parallel_default=1)
            manifest = _plan_campaign(planner)
            run_manifest_path = output_path
            with locked_manifest_path(run_manifest_path):
                save_campaign_manifest(output_path, manifest)
            invocation_mode = "planned_then_executed"
            if not as_json:
                print(f"Planned {len(manifest.projects)} projects → {run_manifest_path}")
        executor = CampaignExecutor(
            manifest_path=run_manifest_path,
            repo_root=Path.cwd(),
            target_branch=target_branch,
        )
        payload = {
            "mode": "campaign-run",
            "invocation_mode": invocation_mode,
            "manifest_path": str(run_manifest_path),
            **asyncio.run(executor.execute_once()),
        }
        with locked_manifest_path(run_manifest_path):
            manifest = load_campaign_manifest(run_manifest_path)
            payload["campaign_id"] = manifest.campaign_id
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            stop = payload.get("stop_reason", "")
            dispatched = payload.get("dispatched_projects", [])
            print(
                f"campaign_id={payload.get('campaign_id', '')} "
                f"manifest={run_manifest_path} "
                f"invocation_mode={invocation_mode} "
                f"stop_reason={stop} dispatched={len(dispatched)}"
            )
            for item in dispatched:
                if isinstance(item, dict):
                    print(
                        f"  {item.get('project_id')} status={item.get('status')} "
                        f"outcome={item.get('outcome')}"
                    )
                elif isinstance(item, str):
                    print(f"  {item}")
        return

    executor = CampaignExecutor(
        manifest_path=manifest_path,
        repo_root=Path.cwd(),
        target_branch=target_branch,
    )
    if subaction == "execute":
        payload = asyncio.run(executor.execute_once())
    elif subaction == "status":
        payload = executor.status()
    elif subaction == "review":
        target = str(getattr(args, "swarm_campaign_target", None) or "").strip()
        if not target:
            raise ValueError("campaign review requires a project id as the third argument")
        payload = asyncio.run(executor.review_project(target))
    elif subaction == "sync-issues":
        payload = executor.sync_issue_plan()
    else:
        raise ValueError(
            "campaign action must be one of: plan, run, execute, status, review, sync-issues"
        )

    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        if subaction == "status":
            print(
                f"campaign_id={payload.get('campaign_id', '')} "
                f"stop_reason={payload.get('stop_reason', '')}"
            )
            counts = payload.get("counts", {})
            if isinstance(counts, dict):
                counts_text = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                print(f"counts={counts_text}")
            for project in payload.get("projects", [])[:10]:
                if not isinstance(project, dict):
                    continue
                print(
                    f"{project.get('project_id')} status={project.get('status')} "
                    f"review={project.get('review_status')} title={project.get('title', '')}"
                )
        else:
            print(json.dumps(payload, indent=2))
    return
