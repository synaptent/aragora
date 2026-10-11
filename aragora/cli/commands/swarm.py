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
import logging
import os
from pathlib import Path
import sqlite3
import sys
from collections.abc import Sequence  # noqa: F401
from typing import TYPE_CHECKING, Any, Coroutine, TypeVar
from uuid import uuid4

from aragora.cli.commands.swarm_runner_payloads import (  # noqa: F401
    _build_multi_runner_payload,
    _build_runner_probe_payload,
    _build_runner_report_payload,
)

# Every helper is re-exported so existing imports keep working. Patching a name
# here only affects calls made from this module; helpers that are called inside
# a split module (e.g. _probe_validation_command in swarm_validation_audit or
# _print_table in swarm_render) must be patched there.
from aragora.cli.commands.swarm_validation_audit import (  # noqa: F401
    _UNSAFE_VALIDATION_SHELL_FRAGMENTS,
    _audit_issue_validation_contract,
    _classify_issue_validation_status,
    _open_audit_checkout,
    _probe_validation_command,
    _trim_command_output,
)
from aragora.cli.commands.swarm_inputs import (  # noqa: F401
    _coordination_assigned_by,
    _coordination_session_id,
    _load_structured_object,
    _optional_text,
    _parse_csv_set,
    _probe_limit_arg,
    _resolve_swarm_action_goal,
)
from aragora.cli.commands.swarm_render import (  # noqa: F401
    _format_elapsed_seconds,
    _print_supervisor_run,
    _print_table,
    _render_coordination_view,
    _render_initiative,
    _render_initiative_status,
    _render_integrator_table,
    _render_runner_report,
    _render_tranche_queue_harvest_table,
    _render_tranche_queue_status,
)
from aragora.cli.commands.swarm_runner import _run_runner_action
from aragora.cli.commands.swarm_campaign import _run_campaign_action
from aragora.cli.commands.swarm_preflight import _run_preflight_action
from aragora.cli.commands.swarm_initiative import (  # noqa: F401
    _initiative_rows,
    _run_initiative_action,
)

logger = logging.getLogger(__name__)

JsonDict = dict[str, Any]
T = TypeVar("T")


# ``DevCoordinationStore`` is an optional dependency: importing it pulls in
# nomic coordination state which may not be available in every environment.
# To keep mypy type narrowing intact without losing the runtime fallback,
# we expose the type to type-checkers unconditionally while tolerating
# runtime import failures.
if TYPE_CHECKING:
    from aragora.nomic.dev_coordination import (  # noqa: F401
        DevCoordinationStore as DevCoordinationStore,
    )
else:
    try:
        from aragora.nomic.dev_coordination import DevCoordinationStore
    except (ImportError, RuntimeError, OSError, ValueError):  # pragma: no cover - defensive
        DevCoordinationStore = None  # type: ignore[misc,assignment]


def _dev_coordination_store_cls() -> "type[DevCoordinationStore] | None":
    """Return the optional :class:`DevCoordinationStore` class or ``None``.

    Centralised helper so callers do not have to re-import the class or
    re-check the optional-dependency sentinel on every use. Returning a
    narrow ``type | None`` keeps mypy happy on both branches.
    """

    return DevCoordinationStore if DevCoordinationStore is not None else None


# Keep boss-loop iteration output readable without hiding the lane signal
# entirely when multiple inferred hints are available.
MAX_DISPLAYED_LANE_HINTS = 2


def _run_supervised_or_report(awaitable: Coroutine[Any, Any, T]) -> T | None:
    try:
        return asyncio.run(awaitable)
    except ValueError as exc:
        print(f"Error: {exc}")
        return None


def _build_boss_payload(
    run: JsonDict,
    *,
    repo_root: Path,
    target_branch: str,
    routing: JsonDict | None = None,
) -> JsonDict:
    from aragora.swarm.reporter import build_boss_payload, build_integrator_view
    from aragora.worktree.fleet import FleetCoordinationStore, build_fleet_rows

    dev_store_cls = _dev_coordination_store_cls()

    worktrees = build_fleet_rows(
        repo_root,
        base_branch=target_branch,
        tail=0,
        include_git_metrics=False,
    )
    fleet_store = FleetCoordinationStore(repo_root)
    claims = fleet_store.list_claims()
    merge_queue = fleet_store.list_merge_queue()
    # Fleet-only coordination has no dedicated status summary; the richer
    # integrator view is populated from ``DevCoordinationStore`` below when
    # it is available.
    coordination: JsonDict = {}
    if dev_store_cls is not None:
        try:
            coordination = dict(
                dev_store_cls(repo_root=repo_root).status_summary(include_integrator_artifacts=True)
            )
        except (RuntimeError, OSError, ValueError) as exc:
            logger.debug("coordination_status_fetch_failed: %s: %s", type(exc).__name__, exc)
    integrator_view = build_integrator_view(
        runs=[run],
        worktrees=worktrees,
        claims=claims,
        merge_queue=merge_queue,
        coordination=coordination,
    )
    return build_boss_payload(
        run=run,
        integrator_view=integrator_view,
        coordination=coordination,
        routing=routing,
    )


def _resolve_boss_routing(
    *,
    requested_runner_type: str | None = None,
    allowed_profiles: set[str] | None = None,
    rotation_interval_seconds: float = 1800.0,
) -> dict[str, object]:
    from aragora.swarm.runner_registry import (
        LocalRunnerRegistry,
        authorization_context_with_defaults,
    )

    owner_context = authorization_context_with_defaults(repo_root=Path.cwd())
    return (
        LocalRunnerRegistry()
        .resolve_boss_routing(
            owner_context=owner_context,
            requested_runner_type=requested_runner_type,
            allowed_profiles=allowed_profiles,
            rotation_interval_seconds=rotation_interval_seconds,
        )
        .to_dict()
    )


def _blocked_boss_payload(
    *,
    goal: str | None,
    target_branch: str,
    routing: dict[str, object],
) -> dict[str, object]:
    next_action = str(routing.get("next_action", "")).strip()
    return {
        "mode": "boss",
        "run_id": None,
        "status": "blocked",
        "goal": goal or "",
        "target_branch": target_branch,
        "work_order_counts": {},
        "lanes": [],
        "integrator_next_actions": [next_action] if next_action else [],
        "needs_human": [],
        "coordination_counts": {},
        "integrator_summary": {},
        "routing": routing,
    }


def _load_integrator_view(repo_root: Path, *, base_branch: str) -> dict[str, object]:
    from aragora.swarm.reporter import build_integrator_view
    from aragora.worktree.fleet import FleetCoordinationStore, build_fleet_rows

    dev_store_cls = _dev_coordination_store_cls()

    worktrees = build_fleet_rows(
        repo_root,
        base_branch=base_branch,
        tail=0,
        include_git_metrics=False,
    )
    fleet_store = FleetCoordinationStore(repo_root)
    claims = fleet_store.list_claims()
    merge_queue = fleet_store.list_merge_queue()
    coordination: dict[str, object] = {}
    if dev_store_cls is not None:
        try:
            coordination = dict(
                dev_store_cls(repo_root=repo_root).status_summary(include_integrator_artifacts=True)
            )
        except (RuntimeError, OSError, ValueError):
            coordination = {}
    return build_integrator_view(
        runs=[],
        worktrees=worktrees,
        claims=claims,
        merge_queue=merge_queue,
        coordination=coordination,
    )


def _find_integrator_lane(
    view: JsonDict,
    *,
    lane_id: str = "",
    receipt_id: str = "",
    lease_id: str = "",
    branch: str = "",
) -> JsonDict | None:
    lanes = [item for item in view.get("lanes", []) if isinstance(item, dict)]
    lane_id = str(lane_id or "").strip()
    receipt_id = str(receipt_id or "").strip()
    lease_id = str(lease_id or "").strip()
    branch = str(branch or "").strip()

    if lane_id:
        for lane in lanes:
            if str(lane.get("lane_id", "")).strip() == lane_id:
                return lane
        return None
    if receipt_id:
        for lane in lanes:
            if str(lane.get("receipt_id", "")).strip() == receipt_id:
                return lane
        return None
    if lease_id:
        for lane in lanes:
            if str(lane.get("lease_id", "")).strip() == lease_id:
                return lane
        return None
    if branch:
        canonical = [
            lane
            for lane in lanes
            if str(lane.get("branch", "")).strip() == branch and bool(lane.get("canonical_lane"))
        ]
        if canonical:
            return canonical[0]
        for lane in lanes:
            if str(lane.get("branch", "")).strip() == branch:
                return lane
    return None


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
    from aragora.swarm.reporter import build_integrator_view
    from aragora.worktree.fleet import (
        FleetCoordinationStore,
        build_fleet_rows,
        resolve_repo_root,
    )

    # ``payload`` and ``response`` are reused across action branches with
    # heterogeneous concrete types (dict literals, dataclass.to_dict() results,
    # helper returns). Pinning them to ``JsonDict`` here lets mypy narrow
    # each assignment locally without the whole-function union drift that
    # previously inferred ``dict[str, Collection[str] | None]``.
    payload: JsonDict = {}
    response: JsonDict = {}

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
    skip_publication = bool(getattr(args, "skip_publication", False))
    managed_dir_pattern = getattr(args, "managed_dir_pattern", ".worktrees/{agent}-auto")
    as_json = bool(getattr(args, "json", False))
    run_id = getattr(args, "run_id", None)
    refresh_scaling = bool(getattr(args, "refresh_scaling", False))
    no_dispatch = bool(getattr(args, "no_dispatch", False))
    watch = bool(getattr(args, "watch", False))
    claude_runner_profiles = _optional_text(getattr(args, "claude_runner_profiles", None))
    allowed_runner_profiles = _parse_csv_set(claude_runner_profiles)
    runner_rotation_interval = float(getattr(args, "runner_rotation_interval", 1800.0) or 1800.0)
    interval_seconds = float(getattr(args, "interval_seconds", 5.0) or 5.0)
    max_ticks = getattr(args, "max_ticks", None)
    all_runs = bool(getattr(args, "all_runs", False))
    dispatch_only = bool(getattr(args, "dispatch_only", False))
    no_wait = bool(getattr(args, "no_wait", False))
    allow_claude_write = bool(getattr(args, "allow_claude_write", False))
    dispatch_workers = not no_dispatch
    boss_mode = action == "boss"
    boss_routing: dict[str, object] | None = None
    if dispatch_only:
        no_wait = True
    if boss_mode:
        dispatch_workers = True
        no_wait = False
        concurrency_cap = max(4, concurrency_cap)

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

    if action == "preflight":
        _run_preflight_action(
            args,
            target_branch=target_branch,
            skip_publication=skip_publication,
            as_json=as_json,
        )
        return

    if action in {"coord", "assign", "claim-pr", "report", "findings"}:
        from aragora.swarm.session_coordinator import (
            claim_pr as coord_claim_pr,
            list_findings as coord_list_findings,
            read_directives as coord_read,
            report_finding as coord_report_finding,
            set_assignment as coord_set_assignment,
        )
        from aragora.worktree.fleet import resolve_repo_root

        repo_root = resolve_repo_root(Path.cwd())
        findings_limit = max(1, int(getattr(args, "findings_limit", 10)))
        session_id = _coordination_session_id(args)

        if action == "coord":
            payload = coord_read(repo_root, findings_limit=findings_limit)
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                _render_coordination_view(payload)
            return

        if action == "assign":
            target_session = _optional_text(goal)
            task_text = _optional_text(getattr(args, "swarm_campaign_target", None))
            if not target_session or not task_text:
                print('Error: usage: aragora swarm assign <session-id> "task description"')
                return
            payload = coord_set_assignment(
                target_session,
                task_text,
                scope=[
                    str(item) for item in (getattr(args, "scope", None) or []) if str(item).strip()
                ],
                constraints=[
                    str(item)
                    for item in (getattr(args, "constraint", None) or [])
                    if str(item).strip()
                ],
                status=str(getattr(args, "directive_status", "active") or "active"),
                issued_by=_coordination_assigned_by(args),
                repo_root=repo_root,
            )
            response = {"mode": "coordination-assign", "directive": payload}
            if as_json:
                print(json.dumps(response, indent=2))
            else:
                print(f"assigned {payload.get('target', '')}: {payload.get('task', '')}")
            return

        if action == "claim-pr":
            pr_text = _optional_text(goal)
            if not pr_text:
                print("Error: usage: aragora swarm claim-pr <pr-number>")
                return
            try:
                pr_number = int(pr_text)
            except ValueError:
                print(f"Error: invalid PR number: {pr_text}")
                return
            payload = dict(
                coord_claim_pr(
                    pr_number,
                    session_id,
                    intent=_optional_text(getattr(args, "claim_intent", None)) or "",
                    ttl_minutes=max(1, int(getattr(args, "ttl_minutes", 30) or 30)),
                    repo_root=repo_root,
                )
            )
            response = {"mode": "coordination-claim-pr", "pr": pr_number, **payload}
            if as_json:
                print(json.dumps(response, indent=2))
            else:
                status_text = str(payload.get("status", "unknown"))
                if status_text == "granted":
                    print(f"claimed PR#{pr_number} for {session_id}")
                else:
                    owners = [
                        str(item.get("session_id", ""))
                        for item in payload.get("contested_by", [])
                        if isinstance(item, dict)
                    ]
                    print(
                        f"PR#{pr_number} claim contested for {session_id}"
                        + (f" (also claimed by {', '.join(owners)})" if owners else "")
                    )
            return

        if action == "report":
            message = _optional_text(goal)
            if not message:
                print('Error: usage: aragora swarm report "finding text"')
                return
            payload = coord_report_finding(
                message,
                session_id,
                kind=_optional_text(getattr(args, "kind", None)) or "finding",
                pr=getattr(args, "pr", None),
                scope=[
                    str(item) for item in (getattr(args, "scope", None) or []) if str(item).strip()
                ],
                repo_root=repo_root,
            )
            response = {"mode": "coordination-report", "finding": payload}
            if as_json:
                print(json.dumps(response, indent=2))
            else:
                print(f"reported {payload.get('kind', 'finding')} from {session_id}")
            return

        findings = coord_list_findings(
            limit=findings_limit,
            session_id=_optional_text(getattr(args, "session_id", None)),
            kind=_optional_text(getattr(args, "kind", None)),
            pr=getattr(args, "pr", None),
            repo_root=repo_root,
        )
        if as_json:
            print(json.dumps({"mode": "coordination-findings", "findings": findings}, indent=2))
        elif not findings:
            print("No findings reported yet.")
        else:
            for finding in findings:
                pr_value = finding.get("pr")
                pr_text = f" pr=#{pr_value}" if pr_value not in (None, "", 0) else ""
                print(
                    "[{session}] {kind}{pr} {message}".format(
                        session=finding.get("source_session", "-") or "-",
                        kind=finding.get("kind", "finding"),
                        pr=pr_text,
                        message=finding.get("message", ""),
                    )
                )
        return

    if action == "dispatch":
        from aragora.swarm.runbook_dispatcher import dispatch_runbook, resolve_runbook_path
        from aragora.worktree.fleet import resolve_repo_root

        repo_root = resolve_repo_root(Path.cwd())
        runbook_name = _optional_text(getattr(args, "runbook", None)) or _optional_text(goal)
        if not runbook_name:
            print("Error: usage: aragora swarm dispatch <runbook-name>", file=sys.stderr)
            sys.exit(1)
        runbook_path = resolve_runbook_path(runbook_name, repo_root)
        if not runbook_path.exists():
            print(f"Error: runbook not found: {runbook_path}", file=sys.stderr)
            sys.exit(1)
        issued_by = _coordination_assigned_by(args)
        dry_run = bool(getattr(args, "dry_run", False))
        dispatch_result: JsonDict = dispatch_runbook(
            runbook_path,
            issued_by=issued_by,
            repo_root=repo_root,
            dry_run=dry_run,
        )
        if as_json:
            print(json.dumps(dispatch_result, indent=2))
        else:
            print(
                f"runbook={dispatch_result.get('name', '')} "
                f"dispatched={len(dispatch_result.get('directives', []))}"
            )
            for directive in dispatch_result.get("directives", []):
                target = directive.get("target", "")
                task = str(directive.get("task", "") or "")
                task_summary = task.splitlines()[0] if task else ""
                print(f"  {target}: {task_summary}")
        return

    if action == "initiative":
        _run_initiative_action(
            args,
            goal=goal,
            target_branch=target_branch,
            as_json=as_json,
        )
        return

    if action == "runner":
        _run_runner_action(
            args,
            goal=goal,
            allowed_runner_profiles=allowed_runner_profiles,
            runner_rotation_interval=runner_rotation_interval,
            as_json=as_json,
        )
        return

    if action == "audit-issues":
        from aragora.swarm.boss_loop import GitHubIssueFeed

        audit_labels: list[str] = list(getattr(args, "labels", None) or [])
        audit_ref = _optional_text(getattr(args, "audit_ref", None))
        legacy_label = getattr(args, "boss_label_filter", None)
        if legacy_label and legacy_label not in audit_labels:
            audit_labels.insert(0, legacy_label)
        label_filter = audit_labels[0] if audit_labels else None
        required_labels = set(audit_labels)
        issue_list = [
            int(item.strip())
            for item in str(getattr(args, "boss_issue_list", "") or "").split(",")
            if item.strip()
        ]
        if getattr(args, "boss_issue_number", None):
            issue_list.append(int(getattr(args, "boss_issue_number")))

        feed = GitHubIssueFeed(
            repo=getattr(args, "boss_repo", None),
            label_filter=label_filter,
            issue_numbers=issue_list or None,
            limit=25,
        )
        issues = feed.fetch()
        if required_labels:
            issues = [
                issue
                for issue in issues
                if required_labels.issubset(
                    {str(label).strip() for label in getattr(issue, "labels", [])}
                )
            ]

        with _open_audit_checkout(Path.cwd(), git_ref=audit_ref) as audit_root:
            audits = [
                _audit_issue_validation_contract(issue, repo_root=audit_root) for issue in issues
            ]
        audit_summary: dict[str, int] = {}
        for item in audits:
            status = str(item.get("status", "unknown") or "unknown")
            audit_summary[status] = audit_summary.get(status, 0) + 1
        payload = {
            "mode": "swarm-issue-audit",
            "action": "audit-issues",
            "repo": getattr(args, "boss_repo", None),
            "audit_ref": audit_ref,
            "labels": audit_labels,
            "issue_count": len(audits),
            "summary": audit_summary,
            "issues": audits,
        }
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"audited={len(audits)} "
                + (f"ref={audit_ref} " if audit_ref else "")
                + " ".join(f"{key}={value}" for key, value in sorted(audit_summary.items()))
            )
            rows = [
                {
                    "number": item["number"],
                    "status": item["status"],
                    "title": str(item.get("title", ""))[:64],
                    "next_action": str(item["next_action"])[:80],
                }
                for item in audits
            ]
            _print_table(
                [
                    ("number", "Issue"),
                    ("status", "Status"),
                    ("title", "Title"),
                    ("next_action", "Next Action"),
                ],
                rows,
            )
        return

    if action == "integrator":
        subaction = str(goal or "view").strip().lower() or "view"
        repo_root = resolve_repo_root(Path.cwd())
        base_branch = str(getattr(args, "target_branch", "main") or "main")
        view = _load_integrator_view(repo_root, base_branch=base_branch)
        readiness_filter = str(getattr(args, "readiness", None) or "").strip()
        if readiness_filter:
            filtered_view = dict(view)
            lanes_value = view.get("lanes", [])
            lanes = lanes_value if isinstance(lanes_value, list) else []
            filtered_view["lanes"] = [
                item
                for item in lanes
                if isinstance(item, dict)
                and str(item.get("merge_readiness", "")).strip() == readiness_filter
            ]
            view = filtered_view

        if subaction in {"view", "status"}:
            if as_json:
                print(json.dumps(view, indent=2))
            else:
                _render_integrator_table(view)
            return

        lane = _find_integrator_lane(
            view,
            lane_id=str(getattr(args, "lane_id", None) or ""),
            receipt_id=str(getattr(args, "receipt_id", None) or ""),
            lease_id=str(getattr(args, "lease_id", None) or ""),
            branch=str(getattr(args, "lane_branch", None) or ""),
        )
        if lane is None:
            print(
                "Error: integrator action requires a resolvable lane via "
                "--lane-id, --receipt-id, --lease-id, or --lane-branch",
                file=sys.stderr,
            )
            sys.exit(1)

        rationale = str(getattr(args, "rationale", "") or "").strip()
        decided_by = str(getattr(args, "decided_by", "cli-integrator") or "cli-integrator").strip()

        if subaction in {"merge", "archive"}:
            from aragora.nomic.dev_coordination import IntegrationDecisionType

            if DevCoordinationStore is None:
                print(
                    "Error: DevCoordinationStore is unavailable in this environment",
                    file=sys.stderr,
                )
                sys.exit(1)

            resolved_receipt_id = str(
                getattr(args, "receipt_id", None) or lane.get("receipt_id") or ""
            ).strip()
            resolved_lease_id = str(
                getattr(args, "lease_id", None) or lane.get("lease_id") or ""
            ).strip()
            if not resolved_receipt_id:
                print(
                    "Error: selected lane has no receipt_id; cannot record an integration decision",
                    file=sys.stderr,
                )
                sys.exit(1)

            decision_type = (
                IntegrationDecisionType.MERGE
                if subaction == "merge"
                else IntegrationDecisionType.DISCARD
            )
            decision = DevCoordinationStore(repo_root=repo_root).record_integration_decision(
                receipt_id=resolved_receipt_id,
                lease_id=resolved_lease_id or None,
                decided_by=decided_by,
                decision=decision_type,
                rationale=rationale
                or (
                    "Integrator approved lane for merge"
                    if subaction == "merge"
                    else "Integrator archived lane"
                ),
                target_branch=base_branch,
            )
            branch = str(lane.get("branch", "") or "").strip()
            if subaction == "archive" and branch:
                try:
                    from aragora.swarm.pr_registry import PullRequestRegistry

                    PullRequestRegistry().close(branch, outcome="archived")
                except ImportError:
                    pass
                except (RuntimeError, OSError, ValueError) as exc:
                    logger.debug("pr_registry_close_failed branch=%s: %s", branch, exc)
            payload = {
                "lane_id": lane.get("lane_id"),
                "receipt_id": resolved_receipt_id,
                "lease_id": resolved_lease_id or None,
                "branch": branch or None,
                "decision": decision.decision,
                "decision_id": decision.decision_id,
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(
                    "decision_id={decision_id} decision={decision} lane_id={lane_id} receipt_id={receipt_id}".format(
                        decision_id=payload["decision_id"],
                        decision=payload["decision"],
                        lane_id=payload["lane_id"],
                        receipt_id=payload["receipt_id"],
                    )
                )
            return

        if subaction == "supersede":
            from aragora.swarm.pr_registry import PullRequestRegistry

            branch = str(getattr(args, "lane_branch", None) or lane.get("branch") or "").strip()
            new_pr_url = str(getattr(args, "new_pr_url", None) or "").strip()
            if not branch or not new_pr_url:
                print(
                    "Error: integrator supersede requires a lane branch and --new-pr-url",
                    file=sys.stderr,
                )
                sys.exit(1)
            entry = PullRequestRegistry().supersede(
                branch,
                new_pr_url,
                reason=rationale or "Integrator superseded the canonical PR",
            )
            if entry is None:
                print(f"Error: branch not found in PR registry: {branch}", file=sys.stderr)
                sys.exit(1)
            payload = {
                "branch": branch,
                "new_pr_url": new_pr_url,
                "status": entry.status,
                "superseded_count": len(entry.superseded),
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(
                    "branch={branch} superseded_count={count} new_pr={url}".format(
                        branch=branch,
                        count=payload["superseded_count"],
                        url=new_pr_url,
                    )
                )
            return

        print(
            "Error: swarm integrator action must be one of view, status, merge, archive, or supersede",
            file=sys.stderr,
        )
        sys.exit(1)

    if action == "merge-arbiter":
        from aragora.swarm.merge_arbiter import MergeArbiter, MergeArbiterConfig

        prefixes_raw = str(getattr(args, "boss_branch_prefix", "") or "boss-harvest")
        prefixes = [p.strip() for p in prefixes_raw.split(",") if p.strip()]
        arbiter_config = MergeArbiterConfig(
            repo=getattr(args, "boss_repo", None) or "synaptent/aragora",
            branch_prefixes=prefixes,
            poll_interval_seconds=float(getattr(args, "interval_seconds", 120.0) or 120.0),
            max_runtime_hours=float(getattr(args, "max_hours", 12.0) or 12.0),
            max_consecutive_failures=int(getattr(args, "max_consecutive_failures", 3) or 3),
            dry_run=bool(getattr(args, "dry_run", False)),
        )
        arbiter = MergeArbiter(config=arbiter_config)
        summary = asyncio.run(arbiter.run())
        if as_json:
            print(json.dumps(summary.to_dict(), indent=2))
        else:
            print(f"\nMerge arbiter finished: {summary.stop_reason}")
            print(
                f"polls={summary.polls} merged={len(summary.merged)} "
                f"skipped={len(summary.skipped)} failed={len(summary.failed)} "
                f"elapsed={summary.elapsed_seconds:.1f}s"
            )
            if summary.merged:
                print(f"  merged PRs: {summary.merged}")
        return

    if action == "boss-loop":
        from aragora.swarm.boss_loop import BossLoop, BossLoopConfig

        # Merge --label (repeatable) with legacy --boss-label-filter (single string).
        cli_labels: list[str] = list(getattr(args, "labels", None) or [])
        legacy_label = getattr(args, "boss_label_filter", None)
        if legacy_label and legacy_label not in cli_labels:
            cli_labels.insert(0, legacy_label)

        # Use the first label for gh CLI pre-filtering (server-side), and the
        # full set as require_labels for Python-side ALL-match filtering.
        label_filter = cli_labels[0] if cli_labels else None
        require_labels = set(cli_labels) if cli_labels else None

        # When --autonomy full-auto, continue past needs_human states
        auto_continue = autonomy_str in {"full-auto", "fire_and_forget"}
        issue_list = [
            int(item.strip())
            for item in str(getattr(args, "boss_issue_list", "") or "").split(",")
            if item.strip()
        ]
        default_target_agent = str(getattr(args, "worker_model", "") or "").strip() or None
        default_reviewer_agent = str(getattr(args, "review_model", "") or "").strip() or None

        boss_loop_config = BossLoopConfig(
            max_iterations=int(getattr(args, "max_ticks", None) or 50),
            iteration_interval_seconds=float(getattr(args, "interval_seconds", 30.0) or 30.0),
            freshness_ttl_seconds=float(getattr(args, "freshness_ttl", 3600.0) or 3600.0),
            repo=getattr(args, "boss_repo", None),
            label_filter=label_filter,
            require_labels=require_labels,
            issue_number=getattr(args, "boss_issue_number", None),
            issue_numbers=issue_list or None,
            target_branch=target_branch,
            budget_limit_usd=budget_limit,
            max_consecutive_failures=int(getattr(args, "max_consecutive_failures", 3) or 3),
            require_validation_contract=not bool(
                getattr(args, "allow_missing_validation_contract", False)
            ),
            dispatch_enabled=not no_dispatch,
            default_target_agent=default_target_agent,
            default_reviewer_agent=default_reviewer_agent,
            allowed_runner_profiles=allowed_runner_profiles,
            runner_rotation_interval_seconds=runner_rotation_interval,
            max_parallel_dispatches=int(getattr(args, "boss_max_parallel_dispatches", 1) or 1),
            auto_continue_on_needs_human=auto_continue,
            enable_ping_pong_retry=bool(getattr(args, "ping_pong", False)),
            allow_claude_dangerously_skip_permissions=auto_continue,
            allow_codex_full_auto=auto_continue,
            auto_publish_deliverables=auto_continue,
            auto_close_already_done_issues=auto_continue,
            auto_update_enabled=bool(getattr(args, "boss_auto_update", False)),
            auto_update_interval_iterations=int(
                getattr(args, "boss_auto_update_interval", 10) or 10
            ),
            use_llm_pre_dispatch_gate=bool(getattr(args, "boss_llm_pre_dispatch_gate", False)),
            no_suitable_issue_keepalive=bool(getattr(args, "no_suitable_issue_keepalive", False)),
        )
        exec_argv = ["-m", "aragora.cli.main", *sys.argv[1:]]
        loop = BossLoop(config=boss_loop_config, exec_argv=exec_argv)

        def _on_status(status: object) -> None:
            if as_json:
                return  # JSON output is emitted at the end
            status_dict = status.to_dict() if hasattr(status, "to_dict") else {}
            iteration = status_dict.get("iteration", "?")
            worker = status_dict.get("worker_status", "?")
            issue = status_dict.get("selected_issue")
            lane = None
            if isinstance(issue, dict):
                lane = issue.get("lane_id")
                if lane is None:
                    lane_hints = issue.get("lane_hints")
                    if isinstance(lane_hints, list) and lane_hints:
                        lane = ",".join(
                            str(item).strip()
                            for item in lane_hints[:MAX_DISPLAYED_LANE_HINTS]
                            if str(item).strip()
                        )
            issue_text = (
                f"#{issue.get('number', '?')} {issue.get('title', '')[:60]}"
                if isinstance(issue, dict)
                else "none"
            )
            if lane:
                issue_text = f"{issue_text} lane={lane}"
            stop = status_dict.get("stop_reason")
            configured_parallel = status_dict.get("configured_max_parallel_dispatches")
            effective_parallel = status_dict.get("effective_parallel_dispatches")
            parallel_text = ""
            if configured_parallel is not None:
                effective_text = str(effective_parallel) if effective_parallel is not None else "?"
                parallel_text = f" parallel={configured_parallel}/{effective_text}"
            print(
                f"[iter {iteration}] worker={worker} issue={issue_text}{parallel_text}"
                + (f" stop={stop}" if stop else "")
            )
            for action_text in status_dict.get("next_actions", [])[:2]:
                print(f"  next: {action_text}")

        loop_result = asyncio.run(loop.run(on_status=_on_status))
        if as_json:
            to_bounded_dict = getattr(loop_result, "to_bounded_dict", None)
            payload = to_bounded_dict() if callable(to_bounded_dict) else loop_result.to_dict()
            print(json.dumps(payload, indent=2))
        else:
            print(f"\nBoss loop finished: {loop_result.stop_reason}")
            print(
                f"iterations={loop_result.iterations_completed} "
                f"attempted={len(loop_result.issues_attempted)} "
                f"completed={len(loop_result.issues_completed)} "
                f"failed={len(loop_result.issues_failed)} "
                f"elapsed={loop_result.total_elapsed_seconds:.1f}s "
                f"parallel={loop_result.configured_max_parallel_dispatches}/"
                f"{loop_result.effective_parallel_dispatches_observed if loop_result.effective_parallel_dispatches_observed is not None else '?'}"
            )
            for reason in loop_result.needs_human_reasons[:3]:
                print(f"  needs_human: {reason}")
            for action_text in loop_result.next_actions[:3]:
                print(f"  next: {action_text}")
        return

    if action == "campaign":
        _run_campaign_action(
            args,
            goal=goal,
            target_branch=target_branch,
            as_json=as_json,
        )
        return

    if action == "tranche":
        from aragora.ralph.github_control import GitHubControl
        from aragora.swarm.pr_registry import PullRequestRegistry
        from aragora.swarm.tranche import (
            TrancheArtifactStore,
            TrancheExecutor,
            TrancheInspector,
            TranchePlanner,
            load_tranche_manifest,
            render_tranche_inspection_text,
        )
        from aragora.swarm.tranche_integrate import (
            integrate_lane,
        )
        from aragora.swarm.tranche_queue import (
            compile_tranche_queue,
            explore_tranche_queue,
            harvest_tranche_queue,
            plan_tranche_queue,
            reconcile_tranche_queue,
            run_tranche_queue,
            tranche_queue_status,
        )
        from aragora.swarm.tranche_review import review_lane, select_review_tier
        from aragora.swarm.tranche_submit import submit_intake_bundle
        from aragora.swarm.tranche_watch import (
            claim_driver,
            list_tranche_states,
            load_tranche_run_state,
            refresh_supervisor_run_dict,
            release_driver,
            run_state_path_for_manifest,
            watch_loop,
        )

        subaction = str(goal or "inspect").strip().lower() or "inspect"
        repo_root = resolve_repo_root(Path.cwd())
        if subaction == "submit":
            intake_arg = str(getattr(args, "intake", "") or "").strip()
            if not intake_arg:
                raise ValueError("tranche submit requires --intake <path|->")
            intake_path: Path | None = None
            if intake_arg != "-":
                intake_path = Path(intake_arg).resolve()
                if not intake_path.exists():
                    raise ValueError(f"intake bundle not found: {intake_path}")
            bundle = _load_structured_object(intake_arg)
            payload = submit_intake_bundle(
                bundle,
                repo_root=repo_root,
                autonomy_mode=_optional_text(getattr(args, "autonomy", None)),
            )
            payload["mode"] = "tranche-submit"
            payload["action"] = subaction
            if intake_path is not None:
                payload["intake_path"] = str(intake_path)
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(json.dumps(payload, indent=2))
            return
        if subaction == "list":
            tranche_items = list_tranche_states(repo_root)
            payload = {
                "mode": "tranche-list",
                "action": subaction,
                "count": len(tranche_items),
                "items": tranche_items,
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(json.dumps(payload, indent=2))
            return
        if subaction == "compile-queue":
            sources_arg = str(getattr(args, "sources", "") or "").strip()
            if not sources_arg:
                raise ValueError("tranche compile-queue requires --sources <path>")
            output_arg = str(getattr(args, "output", "") or "").strip()
            if not output_arg:
                raise ValueError("tranche compile-queue requires --output <path>")
            sources_path = Path(sources_arg).resolve()
            if not sources_path.exists():
                raise ValueError(f"tranche queue source manifest not found: {sources_path}")
            output_path = Path(output_arg).resolve()
            payload = compile_tranche_queue(
                sources_path=sources_path,
                output_path=output_path,
                repo_root=repo_root,
            )
            payload["action"] = subaction
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(json.dumps(payload, indent=2))
            return
        if subaction == "status":
            queue_arg = str(getattr(args, "queue", "") or "").strip()
            if not queue_arg:
                raise ValueError("tranche status requires --queue <path>")
            queue_path = Path(queue_arg).resolve()
            if not queue_path.exists():
                raise ValueError(f"tranche queue manifest not found: {queue_path}")
            payload = tranche_queue_status(
                queue_path=queue_path,
                repo_root=repo_root,
            )
            payload["action"] = subaction
            payload["queue_path"] = str(queue_path)
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                _render_tranche_queue_status(payload)
            return
        if subaction in {
            "explore-queue",
            "plan-queue",
            "run-queue",
            "reconcile-queue",
            "harvest-queue",
        }:
            queue_arg = str(getattr(args, "queue", "") or "").strip()
            if not queue_arg:
                raise ValueError(f"tranche {subaction} requires --queue <path>")
            queue_path = Path(queue_arg).resolve()
            if not queue_path.exists():
                raise ValueError(f"tranche queue manifest not found: {queue_path}")
            if subaction == "explore-queue":
                payload = asyncio.run(
                    explore_tranche_queue(
                        queue_path=queue_path,
                        repo_root=repo_root,
                        planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
                        planner_strategy=str(
                            getattr(args, "planner_strategy", "heuristic") or "heuristic"
                        ),
                        worker_model=str(getattr(args, "worker_model", "codex") or "codex"),
                        review_model=str(getattr(args, "review_model", "claude") or "claude"),
                        max_parallel_lanes=int(getattr(args, "max_parallel_lanes", 1) or 1),
                        enforce_cross_model_review=not bool(
                            getattr(args, "allow_same_model_review", False)
                        ),
                    )
                )
            elif subaction == "plan-queue":
                payload = asyncio.run(
                    plan_tranche_queue(
                        queue_path=queue_path,
                        repo_root=repo_root,
                        planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
                        planner_strategy=str(
                            getattr(args, "planner_strategy", "heuristic") or "heuristic"
                        ),
                        worker_model=str(getattr(args, "worker_model", "codex") or "codex"),
                        review_model=str(getattr(args, "review_model", "claude") or "claude"),
                        max_parallel_lanes=int(getattr(args, "max_parallel_lanes", 1) or 1),
                        enforce_cross_model_review=not bool(
                            getattr(args, "allow_same_model_review", False)
                        ),
                    )
                )
            elif subaction == "run-queue":
                payload = asyncio.run(
                    run_tranche_queue(
                        queue_path=queue_path,
                        repo_root=repo_root,
                        target_branch=str(getattr(args, "target_branch", "main") or "main"),
                        interval_seconds=interval_seconds,
                        max_hours=float(getattr(args, "max_hours", 12.0) or 12.0),
                        max_consecutive_failures=int(
                            getattr(args, "max_consecutive_failures", 3) or 3
                        ),
                        planner_model=str(getattr(args, "planner_model", "claude") or "claude"),
                        planner_strategy=str(
                            getattr(args, "planner_strategy", "heuristic") or "heuristic"
                        ),
                        worker_model=str(getattr(args, "worker_model", "codex") or "codex"),
                        review_model=str(getattr(args, "review_model", "claude") or "claude"),
                        max_parallel_lanes=int(getattr(args, "max_parallel_lanes", 1) or 1),
                        enforce_cross_model_review=not bool(
                            getattr(args, "allow_same_model_review", False)
                        ),
                        allow_claude_dangerously_skip_permissions=allow_claude_write,
                    )
                )
            elif subaction == "harvest-queue":
                requested_execute_merge = bool(getattr(args, "execute_merge", False))
                dry_run = bool(getattr(args, "dry_run", False))
                payload = harvest_tranche_queue(
                    queue_path=queue_path,
                    repo_root=repo_root,
                    execute_merge=requested_execute_merge and not dry_run,
                    allow_admin=bool(getattr(args, "allow_admin", False)),
                )
                payload["dry_run"] = dry_run
                payload["requested_execute_merge"] = requested_execute_merge
            else:
                payload = reconcile_tranche_queue(
                    queue_path=queue_path,
                    repo_root=repo_root,
                )
            payload["action"] = subaction
            payload["queue_path"] = str(queue_path)
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                if subaction == "harvest-queue":
                    _render_tranche_queue_harvest_table(payload)
                else:
                    _render_tranche_queue_status(payload)
            return
        if subaction == "plan":
            prompt_arg = str(getattr(args, "from_prompts", "") or "").strip()
            if not prompt_arg:
                raise ValueError("tranche plan requires --from-prompts <path>")
            prompt_path = Path(prompt_arg).resolve()
            if not prompt_path.exists():
                raise ValueError(f"prompt bundle not found: {prompt_path}")
            manifest_arg = str(getattr(args, "manifest", "") or "").strip()
            output_arg = str(getattr(args, "output", "") or "").strip()
            tranche_output_path: Path | None = None
            if output_arg:
                tranche_output_path = Path(output_arg).resolve()
            elif manifest_arg and manifest_arg != ".aragora/campaign_manifest.yaml":
                tranche_output_path = Path(manifest_arg).resolve()
            tranche_planner = TranchePlanner(repo_root=repo_root)
            manifest, saved_path = tranche_planner.plan_from_prompt_bundle(
                prompt_path,
                output_path=tranche_output_path,
            )
            payload = {
                "mode": "tranche-plan",
                "action": subaction,
                "manifest_id": manifest.manifest_id,
                "manifest_path": str(saved_path),
                "lane_count": len(manifest.lanes),
                "reference_groups": sorted(manifest.references),
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(f"manifest_id={manifest.manifest_id}")
                print(f"manifest_path={saved_path}")
                print(f"lanes={len(manifest.lanes)}")
            return

        manifest_arg = str(getattr(args, "manifest", "") or "").strip()
        if not manifest_arg:
            raise ValueError(f"tranche {subaction} requires --manifest <path>")
        manifest_path = Path(manifest_arg).resolve()
        if not manifest_path.exists():
            raise ValueError(f"tranche manifest not found: {manifest_path}")
        manifest = load_tranche_manifest(manifest_path)

        if subaction == "inspect":
            payload = TrancheInspector(repo_root=repo_root).inspect(manifest)
            payload["action"] = subaction
            payload["manifest_path"] = str(manifest_path)
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(render_tranche_inspection_text(payload))
            return

        if subaction == "watch":
            state_path = run_state_path_for_manifest(manifest_path)
            state = load_tranche_run_state(manifest_path)
            artifact_store = TrancheArtifactStore(repo_root=repo_root)
            driver_mode = bool(getattr(args, "driver", False))
            session_id = str(
                getattr(args, "owner_session_id", None) or f"cli-watch-{os.getpid()}"
            ).strip()
            executor = TrancheExecutor(repo_root=repo_root) if driver_mode else None  # type: ignore[assignment]
            supervisor = None
            github = None
            watch_pr_registry: "PullRequestRegistry | None" = None

            async def _watch_run_fn(*, manifest):
                if executor is None:
                    return None
                try:
                    return await executor.run(
                        manifest,
                        owner_session_id=session_id,
                        target_branch=str(getattr(args, "target_branch", "main") or "main"),
                        max_ticks=int(getattr(args, "max_ticks", 360) or 360),
                        wait_for_completion=False,
                        skip_review=True,
                    )
                except ValueError as exc:
                    detail = str(exc or "").strip()
                    if (
                        "No ready claimable lanes found" in detail
                        or "Tranche is not ready to run." in detail
                        or detail.endswith("is not ready.")
                    ):
                        return None
                    raise

            async def _watch_review_fn(*, manifest, lane_id, artifact):
                nonlocal supervisor
                from aragora.swarm.supervisor import SwarmSupervisor

                if artifact is None:
                    return {
                        "status": "blocked_nonreviewable",
                        "findings": ["Missing tranche artifact."],
                    }
                run_id = str(getattr(artifact, "run_id", None) or "").strip()
                if not run_id:
                    return {
                        "status": "blocked_nonreviewable",
                        "findings": ["Artifact has no run_id."],
                    }
                if supervisor is None:
                    supervisor = SwarmSupervisor(repo_root=repo_root)
                run_dict = refresh_supervisor_run_dict(supervisor, run_id)
                if run_dict is None:
                    return {
                        "status": "blocked_nonreviewable",
                        "findings": [f"Supervisor run {run_id} is not available."],
                    }
                tranche_lane = manifest.lane(lane_id)
                tier = select_review_tier(
                    write_scope=list(getattr(tranche_lane, "allowed_write_scope", [])),
                    diff_lines=int(getattr(artifact, "metadata", {}).get("diff_lines", 0) or 0),
                    verification_passed=bool(getattr(artifact, "commands", [])),
                    risk_tolerance=str(
                        getattr(artifact, "metadata", {}).get("risk_tolerance", "") or ""
                    ).strip()
                    or None,
                )
                return await review_lane(
                    manifest=manifest,
                    lane_id=lane_id,
                    artifact=artifact,
                    run_dict=run_dict,
                    tier=tier,
                    repo_root=repo_root,
                )

            async def _watch_integrate_fn(*, manifest, lane_id, artifact, approve, run_state=None):
                nonlocal github, watch_pr_registry
                if artifact is None:
                    return {"recommendation": "needs_human", "executed": False}
                if github is None:
                    github = GitHubControl(repo_root=repo_root)
                if watch_pr_registry is None:
                    watch_pr_registry = PullRequestRegistry()
                if DevCoordinationStore is None:
                    return {
                        "recommendation": "needs_human",
                        "executed": False,
                        "reason": "DevCoordinationStore unavailable",
                    }
                coord_store = DevCoordinationStore(repo_root=repo_root)
                return await integrate_lane(
                    artifact=artifact,
                    manifest=manifest,
                    approve=bool(approve),
                    repo_root=repo_root,
                    github=github,
                    registry=watch_pr_registry,
                    store=coord_store,
                    target_branch=str(getattr(args, "target_branch", "main") or "main"),
                    decided_by="tranche-watch",
                    rationale="Tranche watch approved merge after green checks and review.",
                    run_state=run_state,
                    autonomy_mode=str(state.autonomy_mode or "adaptive"),
                )

            if driver_mode:
                state = claim_driver(state, session_id=session_id)
                state.save(state_path)
            final_state = asyncio.run(
                watch_loop(
                    state,
                    manifest=manifest,
                    interval_seconds=interval_seconds,
                    max_ticks=max_ticks,
                    state_path=state_path,
                    driver_session_id=session_id if driver_mode else None,
                    artifact_store=artifact_store,
                    repo_root=repo_root,
                    run_fn=_watch_run_fn if driver_mode else None,
                    review_fn=_watch_review_fn if driver_mode else None,
                    integrate_fn=_watch_integrate_fn if driver_mode else None,
                )
            )
            if driver_mode:
                final_state = release_driver(final_state, session_id=session_id)
                final_state.save(state_path)
            payload = {
                "mode": "tranche-watch",
                "action": subaction,
                "manifest_id": manifest.manifest_id,
                "manifest_path": str(manifest_path),
                "driver": driver_mode,
                **final_state.to_dict(),
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(json.dumps(payload, indent=2))
            return

        if subaction == "design-review":
            from aragora.swarm.tranche_design_review import (
                DesignReviewRecord,
                run_design_review,
                save_design_review,
            )

            tranche_inspection = TrancheInspector(repo_root=repo_root).inspect(manifest)
            normalized_path = manifest_path.with_name("normalized_bundle.yaml")
            if normalized_path.exists():
                normalized_bundle = _load_structured_object(str(normalized_path))
            else:
                normalized_bundle = {
                    "manifest_id": getattr(manifest, "manifest_id", ""),
                    "objective": getattr(manifest, "objective", ""),
                    "lanes": [
                        lane.to_dict()
                        for lane in getattr(manifest, "lanes", [])
                        if hasattr(lane, "to_dict")
                    ],
                }
            payload = asyncio.run(
                run_design_review(
                    manifest=manifest,
                    normalized_bundle=normalized_bundle,
                    inspection=tranche_inspection,
                    max_rounds=int(getattr(args, "rounds", 2) or 2),
                )
            )
            record_payload = payload.get("record")
            if isinstance(record_payload, dict):
                save_design_review(
                    manifest_path.with_name("design_review.yaml"),
                    DesignReviewRecord.from_dict(record_payload),
                )
            payload["action"] = subaction
            payload["manifest_path"] = str(manifest_path)
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(json.dumps(payload, indent=2))
            return

        if subaction == "review":
            from aragora.swarm.supervisor import SwarmSupervisor

            artifact_store = TrancheArtifactStore(repo_root=repo_root)
            lane_id = str(getattr(args, "lane_id", "") or "").strip()
            all_completed = bool(getattr(args, "all_completed", False))
            if lane_id:
                artifact = artifact_store.load(manifest.manifest_id, lane_id)
                selected_artifacts = [artifact] if artifact is not None else []
            elif all_completed:
                selected_artifacts = [
                    item
                    for item in artifact_store.list(manifest.manifest_id)
                    if str(item.status).strip()
                    in {"completed", "review_passed", "changes_requested", "review_blocked"}
                ]
            else:
                raise ValueError("tranche review requires --lane-id <id> or --all-completed")
            if not selected_artifacts:
                raise ValueError("No matching tranche artifacts found for review.")
            supervisor = SwarmSupervisor(repo_root=repo_root)
            results: list[dict[str, object]] = []
            for artifact in selected_artifacts:
                run_id = str(getattr(artifact, "run_id", None) or "").strip()
                if not run_id:
                    raise ValueError(f"Artifact {artifact.lane_id} has no run_id.")
                run_dict = refresh_supervisor_run_dict(supervisor, run_id)
                if run_dict is None:
                    raise ValueError(f"Supervisor run {run_id} is not available.") from None
                tier_arg = str(getattr(args, "tier", "auto") or "auto").strip()
                if tier_arg == "auto":
                    tranche_lane = manifest.lane(artifact.lane_id)
                    tier = select_review_tier(
                        write_scope=list(getattr(tranche_lane, "allowed_write_scope", [])),
                        diff_lines=int(getattr(artifact, "metadata", {}).get("diff_lines", 0) or 0),
                        verification_passed=bool(getattr(artifact, "commands", [])),
                        risk_tolerance=str(
                            getattr(artifact, "metadata", {}).get("risk_tolerance", "") or ""
                        ).strip()
                        or None,
                    )
                else:
                    tier = int(tier_arg)
                review_payload = asyncio.run(
                    review_lane(
                        manifest=manifest,
                        lane_id=artifact.lane_id,
                        artifact=artifact,
                        run_dict=run_dict,
                        tier=tier,
                        repo_root=repo_root,
                    )
                )
                results.append({"lane_id": artifact.lane_id, **review_payload})
            payload = {
                "mode": "tranche-review",
                "action": subaction,
                "manifest_id": manifest.manifest_id,
                "manifest_path": str(manifest_path),
                "results": results,
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(json.dumps(payload, indent=2))
            return

        if subaction == "integrate":
            artifact_store = TrancheArtifactStore(repo_root=repo_root)
            lane_id = str(getattr(args, "lane_id", "") or "").strip()
            all_mergeable = bool(getattr(args, "all_mergeable", False))
            approve = bool(getattr(args, "approve", False))
            if lane_id:
                artifact = artifact_store.load(manifest.manifest_id, lane_id)
                selected_artifacts = [artifact] if artifact is not None else []
            elif all_mergeable:
                selected_artifacts = [
                    item
                    for item in artifact_store.list(manifest.manifest_id)
                    if str(item.status).strip() in {"review_passed", "completed"}
                ]
            else:
                raise ValueError("tranche integrate requires --lane-id <id> or --all-mergeable")
            if not selected_artifacts:
                raise ValueError("No matching tranche artifacts found for integrate.")

            github = GitHubControl(repo_root=repo_root)
            pr_registry = PullRequestRegistry()
            if approve and DevCoordinationStore is None:
                raise RuntimeError(
                    "tranche integrate --approve requires DevCoordinationStore (unavailable)"
                )
            tranche_store = (
                DevCoordinationStore(repo_root=repo_root)
                if approve and DevCoordinationStore is not None
                else None
            )
            state_path = run_state_path_for_manifest(manifest_path)
            run_state = None
            try:
                if state_path.exists():
                    run_state = load_tranche_run_state(manifest_path)
            except (OSError, ValueError):
                run_state = None
            tranche_results: list[JsonDict] = []
            for artifact in selected_artifacts:
                lane_result: JsonDict = asyncio.run(
                    integrate_lane(
                        manifest=manifest,
                        artifact=artifact,
                        approve=approve,
                        repo_root=repo_root,
                        github=github,
                        registry=pr_registry,
                        store=tranche_store,
                        artifact_store=artifact_store,
                        target_branch=str(getattr(args, "target_branch", "main") or "main"),
                        decided_by=str(getattr(args, "decided_by", None) or "tranche-integrate"),
                        rationale=str(
                            getattr(args, "rationale", None)
                            or "Tranche integrate approved merge after green checks and review."
                        ),
                        run_state=run_state,
                        autonomy_mode=str(getattr(args, "autonomy", "adaptive") or "adaptive"),
                    )
                )
                tranche_results.append(lane_result)

                if run_state is not None:
                    run_state.save(state_path)

                payload = {
                    "mode": "tranche-integrate",
                    "action": subaction,
                    "manifest_id": manifest.manifest_id,
                    "manifest_path": str(manifest_path),
                    "approve": approve,
                    "results": tranche_results,
                }
                if as_json:
                    print(json.dumps(payload, indent=2))
                else:
                    print(json.dumps(payload, indent=2))
            return

        tranche_executor = TrancheExecutor(repo_root=repo_root)
        lane_id = str(getattr(args, "lane_id", "") or "").strip()
        all_ready = bool(getattr(args, "all_ready", False))
        owner_agent = _optional_text(getattr(args, "owner_agent", None))
        owner_session_id = _optional_text(getattr(args, "owner_session_id", None))
        if subaction == "prepare":
            payload = tranche_executor.prepare(
                manifest,
                lane_id=lane_id,
                all_ready=all_ready,
                owner_agent=owner_agent,
                owner_session_id=owner_session_id,
                base_branch=str(getattr(args, "target_branch", "main") or "main"),
            )
        elif subaction == "run":
            payload = asyncio.run(
                tranche_executor.run(
                    manifest,
                    lane_id=lane_id,
                    all_ready=all_ready,
                    owner_agent=owner_agent,
                    owner_session_id=owner_session_id,
                    target_branch=str(getattr(args, "target_branch", "main") or "main"),
                    max_ticks=int(getattr(args, "max_ticks", 360) or 360),
                    wait_for_completion=not bool(getattr(args, "no_wait", False)),
                    skip_review=bool(getattr(args, "skip_review", False)),
                    allow_claude_dangerously_skip_permissions=allow_claude_write,
                )
            )
        else:
            raise ValueError(
                "tranche action must be one of: submit, plan, inspect, watch, list, design-review, review, integrate, prepare, run, status, compile-queue, run-queue, reconcile-queue, harvest-queue"
                ", explore-queue, plan-queue"
            )
        payload["action"] = subaction
        payload["manifest_path"] = str(manifest_path)
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(json.dumps(payload, indent=2))
        return

    if boss_mode:
        boss_routing = _resolve_boss_routing(
            requested_runner_type=str(getattr(args, "worker_model", "") or "").strip() or None,
            allowed_profiles=allowed_runner_profiles,
            rotation_interval_seconds=runner_rotation_interval,
        )
        blocked_reason = boss_routing.get("blocked_reason")
        if isinstance(blocked_reason, str) and blocked_reason.strip():
            from aragora.swarm.reporter import render_boss_text

            payload = _blocked_boss_payload(
                goal=goal,
                target_branch=target_branch,
                routing=boss_routing,
            )
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(render_boss_text(payload))
            return
    if action == "status":
        from aragora.cli.commands.swarm_status import load_operator_status, render_operator_status
        from aragora.swarm.session_coordinator import read_directives as coord_read

        repo_root = resolve_repo_root(Path.cwd())
        try:
            supervisor = SwarmSupervisor(repo_root=repo_root)
            payload = supervisor.status_summary(
                run_id=run_id,
                limit=int(getattr(args, "status_limit", 20)),
                refresh_scaling=refresh_scaling,
            )
        except (sqlite3.Error, OSError, RuntimeError) as exc:
            payload = {
                "runs": [],
                "counts": {
                    "runs": 0,
                    "queued_work_orders": 0,
                    "leased_work_orders": 0,
                    "completed_work_orders": 0,
                },
                "coordination": {
                    "available": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            }
        base_branch = str(getattr(args, "target_branch", "main") or "main")
        worktrees = build_fleet_rows(
            repo_root,
            base_branch=base_branch,
            tail=0,
            include_git_metrics=False,
        )
        status_fleet_store = FleetCoordinationStore(repo_root)
        claims = status_fleet_store.list_claims()
        merge_queue = status_fleet_store.list_merge_queue()
        payload["integrator_view"] = build_integrator_view(
            runs=payload.get("runs", []),
            worktrees=worktrees,
            claims=claims,
            merge_queue=merge_queue,
            coordination=payload.get("coordination", {}),
        )
        payload["coordination_view"] = coord_read(
            repo_root,
            findings_limit=max(1, int(getattr(args, "findings_limit", 10))),
        )
        payload["operator_status"] = load_operator_status(
            repo_root,
            limit=10,
            boss_repo=_optional_text(getattr(args, "boss_repo", None)),
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
            integrator_summary = payload["integrator_view"].get("summary", {})
            print(
                "integrator ready={ready} review={review} blocked={blocked} stale={stale} "
                "collisions={collisions} missing_receipts={missing} superseded={superseded}".format(
                    ready=integrator_summary.get("ready_lanes", 0),
                    review=integrator_summary.get("review_lanes", 0),
                    blocked=integrator_summary.get("blocked_lanes", 0),
                    stale=integrator_summary.get("stale_heartbeat_lanes", 0),
                    collisions=integrator_summary.get("collision_lanes", 0),
                    missing=integrator_summary.get("missing_receipt_lanes", 0),
                    superseded=integrator_summary.get("superseded_lanes", 0),
                )
            )
            for action_text in payload["integrator_view"].get("next_actions", [])[:3]:
                print(f"next: {action_text}")
            for run in payload.get("runs", []):
                if isinstance(run, dict):
                    print("---")
                    _print_supervisor_run(run)
            print("---")
            _render_coordination_view(payload["coordination_view"])
            print("---")
            print(render_operator_status(payload["operator_status"]))
        return

    if action == "shift-status":
        from aragora.cli.commands.shift_status import cmd_shift_status

        cmd_shift_status(args)
        return

    if action == "harness-status":
        from aragora.cli.commands.harness_status import cmd_harness_status

        cmd_harness_status(args)
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
        run = _run_supervised_or_report(
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
        if run is None:
            return
        run_payload = run.to_dict()
        if boss_mode:
            boss_payload = _build_boss_payload(
                run_payload,
                repo_root=Path.cwd(),
                target_branch=target_branch,
                routing=boss_routing,
            )
            if as_json:
                print(json.dumps(boss_payload, indent=2))
            else:
                from aragora.swarm.reporter import render_boss_text

                print(render_boss_text(boss_payload))
            return
        if as_json:
            print(json.dumps(run_payload, indent=2))
        else:
            _print_supervisor_run(run_payload)
    elif dry_run:
        goal_text = goal or ""
        if skip_interrogation:
            spec = SwarmSpec(
                id=str(uuid4()),
                created_at=datetime.now(timezone.utc),
                raw_goal=goal_text,
                refined_goal=goal_text,
                budget_limit_usd=budget_limit,
                requires_approval=require_approval,
                interrogation_turns=0,
                user_expertise="developer",
            )
            print("\n[DRY RUN] Skipping interrogation and building a direct spec.\n")
            print(spec.to_json(indent=2))
        else:
            spec = asyncio.run(commander.dry_run(goal_text))
        save_path = getattr(args, "save_spec", None)
        if save_path:
            Path(save_path).write_text(spec.to_yaml())
            print(f"\nSpec saved to {save_path}")
    elif skip_interrogation:
        goal_text = goal or ""
        spec = SwarmSpec.from_direct_goal(
            goal_text,
            budget_limit_usd=budget_limit,
            requires_approval=require_approval,
            user_expertise="developer",
        )
        print("\nSkipping interrogation (developer mode)")
        print(spec.summary())
        if not spec.is_dispatch_bounded():
            print(f"Error: {spec.dispatch_gate_reason()}")
            return
        run = _run_supervised_or_report(
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
        if run is None:
            return
        run_payload = run.to_dict()
        if boss_mode:
            boss_payload = _build_boss_payload(
                run_payload,
                repo_root=Path.cwd(),
                target_branch=target_branch,
                routing=boss_routing,
            )
            if as_json:
                print(json.dumps(boss_payload, indent=2))
            else:
                from aragora.swarm.reporter import render_boss_text

                print(render_boss_text(boss_payload))
            return
        if as_json:
            print(json.dumps(run_payload, indent=2))
        else:
            _print_supervisor_run(run_payload)
    else:
        run = _run_supervised_or_report(
            commander.run_supervised(
                goal or "",
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
        if run is None:
            return
        run_payload = run.to_dict()
        if boss_mode:
            boss_payload = _build_boss_payload(
                run_payload,
                repo_root=Path.cwd(),
                target_branch=target_branch,
                routing=boss_routing,
            )
            if as_json:
                print(json.dumps(boss_payload, indent=2))
            else:
                from aragora.swarm.reporter import render_boss_text

                print(render_boss_text(boss_payload))
            return
        if as_json:
            print(json.dumps(run_payload, indent=2))
        else:
            _print_supervisor_run(run_payload)
