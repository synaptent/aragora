"""``aragora swarm initiative`` subcommand.

``aragora.cli.commands.swarm`` dispatches ``swarm initiative`` here and re-exports
``_run_initiative_action`` and ``_initiative_rows``. The initiative planner, store,
integrator and campaign bridge are imported when the command runs, so tests patch
them on their ``aragora.swarm.initiative_*`` modules.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from aragora.cli.commands.swarm_inputs import _optional_text
from aragora.cli.commands.swarm_render import (
    _print_table,
    _render_initiative,
    _render_initiative_status,
)

JsonDict = dict[str, Any]


def _initiative_rows(items: "Sequence[object]") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in items:
        rows.append(
            {
                "initiative_id": getattr(item, "initiative_id", "") or "",
                "status": getattr(item, "status", "") or "",
                "feature_flag": getattr(item, "feature_flag_name", "") or "-",
                "slices": len(getattr(item, "slices", []) or []),
                "title": getattr(item, "title", "") or "",
                "updated_at": getattr(item, "updated_at", "") or "",
            }
        )
    return rows


def _run_initiative_action(
    args: argparse.Namespace,
    *,
    goal: str | None,
    target_branch: str,
    as_json: bool,
) -> None:
    """Handle ``aragora swarm initiative [plan|show|list|run|status|promote]``."""

    from aragora.swarm.initiative_campaign_bridge import sync_campaign_manifest_for_initiative
    from aragora.swarm.initiative_integrator import (
        DEFAULT_INITIATIVE_MANIFEST,
        InitiativeIntegrator,
    )
    from aragora.swarm.initiative_planner import InitiativePlanner
    from aragora.swarm.initiative_store import InitiativeStore
    from aragora.worktree.fleet import resolve_repo_root

    payload: JsonDict

    subaction = str(goal or "list").strip().lower() or "list"
    if subaction not in {"plan", "show", "list", "run", "status", "promote"}:
        raise ValueError("initiative action must be one of: plan, show, list, run, status, promote")

    repo_root = resolve_repo_root(Path.cwd())
    initiative_dir = _optional_text(getattr(args, "initiative_dir", None))
    state_dir = Path(initiative_dir).expanduser().resolve() if initiative_dir else None
    store = InitiativeStore(repo_root=repo_root, state_dir=state_dir)
    if subaction in {"run", "status", "promote"}:
        target_text = _optional_text(getattr(args, "swarm_campaign_target", None))
        explicit_manifest = _optional_text(getattr(args, "manifest", None))
        project_id = target_text if explicit_manifest and subaction == "promote" else None
        if explicit_manifest:
            manifest_path = Path(explicit_manifest).resolve()
        elif target_text:
            initiative = store.get(target_text)
            if initiative is None:
                raise FileNotFoundError(f"initiative not found: {target_text}")
            manifest_path = sync_campaign_manifest_for_initiative(
                store,
                initiative,
                planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
                planner_strategy=str(getattr(args, "planner_strategy", "heuristic") or "heuristic"),
                worker_model=str(getattr(args, "worker_model", "claude") or "claude"),
                review_model=str(getattr(args, "review_model", "codex") or "codex"),
            )
        else:
            manifest_path = Path(DEFAULT_INITIATIVE_MANIFEST).resolve()
        if not manifest_path.exists():
            raise ValueError(f"initiative manifest not found: {manifest_path}")

        integrator = InitiativeIntegrator(
            manifest_path=manifest_path,
            repo_root=repo_root,
            target_branch=target_branch,
            repo=getattr(args, "boss_repo", None) or "synaptent/aragora",
        )
        if subaction == "run":
            payload = asyncio.run(integrator.run())
        elif subaction == "status":
            payload = integrator.status()
        else:
            payload = integrator.promote(
                project_id=project_id,
                dry_run=bool(getattr(args, "dry_run", False)),
            )

        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            if subaction in {"run", "status"}:
                _render_initiative_status(payload)
            else:
                print(json.dumps(payload, indent=2))
        return

    if subaction == "list":
        items = store.list()
        payload = {
            "mode": "initiative-list",
            "action": subaction,
            "count": len(items),
            "items": [item.to_dict() for item in items],
            "state_dir": str(store.state_dir),
        }
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"initiatives={len(items)} state_dir={store.state_dir}")
            _print_table(
                [
                    ("initiative_id", "Initiative"),
                    ("status", "Status"),
                    ("feature_flag", "Feature Flag"),
                    ("slices", "Slices"),
                    ("title", "Title"),
                ],
                _initiative_rows(items),
            )
        return

    initiative_id = _optional_text(getattr(args, "swarm_campaign_target", None))
    if subaction == "show":
        if not initiative_id:
            raise ValueError("initiative show requires an initiative id as the third argument")
        show_record = store.get(initiative_id)
        if show_record is None:
            raise FileNotFoundError(f"initiative not found: {initiative_id}")
        payload = {
            "mode": "initiative-show",
            "action": subaction,
            "initiative": show_record.to_dict(),
            "state_dir": str(store.state_dir),
        }
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            _render_initiative(show_record)
        return

    goal_text = initiative_id
    if not goal_text:
        raise ValueError("initiative plan requires a goal as the third argument")
    rationale = ""
    source_file = _optional_text(getattr(args, "source_file", None))
    if source_file:
        rationale = Path(source_file).expanduser().resolve().read_text().strip()
    planner = InitiativePlanner(repo_root=repo_root)
    initiative = planner.plan(
        goal=goal_text,
        rationale=rationale,
        dependencies=[
            str(item).strip()
            for item in (getattr(args, "dependency", None) or [])
            if str(item).strip()
        ],
        validations=[
            str(item).strip()
            for item in (getattr(args, "validation", None) or [])
            if str(item).strip()
        ],
        feature_flag_name=_optional_text(getattr(args, "feature_flag", None)),
        milestone_titles=[
            str(item).strip()
            for item in (getattr(args, "milestone", None) or [])
            if str(item).strip()
        ],
        checkpoint_titles=[
            str(item).strip()
            for item in (getattr(args, "checkpoint", None) or [])
            if str(item).strip()
        ],
        planner_strategy=str(getattr(args, "planner_strategy", "heuristic") or "heuristic"),
        planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
    )
    if source_file:
        initiative.metadata["source_file"] = str(Path(source_file).expanduser().resolve())
    saved_path = store.save(initiative)
    manifest_path = sync_campaign_manifest_for_initiative(
        store,
        initiative,
        planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
        planner_strategy=str(getattr(args, "planner_strategy", "heuristic") or "heuristic"),
        worker_model=str(getattr(args, "worker_model", "claude") or "claude"),
        review_model=str(getattr(args, "review_model", "codex") or "codex"),
    )
    payload = {
        "mode": "initiative-plan",
        "action": subaction,
        "initiative": initiative.to_dict(),
        "path": str(saved_path),
        "manifest_path": str(manifest_path),
        "state_dir": str(store.state_dir),
    }
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"initiative_id={initiative.initiative_id}")
        print(f"path={saved_path}")
        print(f"manifest={manifest_path}")
        print(f"slices={len(initiative.slices)}")
    return
