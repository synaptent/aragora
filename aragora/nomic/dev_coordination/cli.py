"""Command-line interface for ``python -m aragora.nomic.dev_coordination``.

``_build_parser`` defines the ``status``, ``claim``, ``complete``, ``heartbeat``,
``decide``, ``scan-salvage``, ``sync-queue``, ``tasks``, ``sync-tasks`` and ``reap``
subcommands; ``_run_command`` runs one parsed command against a
:class:`~aragora.nomic.dev_coordination.core.DevCoordinationStore` and returns the
exit code. :func:`aragora.nomic.dev_coordination.core.main` builds the store from
``--repo``/``--db`` and calls ``_run_command``, so ``core`` keeps the entry point and
this module never imports ``core`` at runtime.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import TYPE_CHECKING

from aragora.nomic.dev_coordination.models import IntegrationDecisionType, LeaseConflictError

if TYPE_CHECKING:
    from aragora.nomic.dev_coordination.core import DevCoordinationStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dev coordination control plane")
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument("--db", default=None, help="Optional explicit SQLite path")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Show coordination status")
    status.add_argument("--json", action="store_true")

    claim = sub.add_parser("claim", help="Claim a bounded work lease")
    claim.add_argument("--task-id", required=True)
    claim.add_argument("--title", required=True)
    claim.add_argument("--agent", required=True)
    claim.add_argument("--session-id", required=True)
    claim.add_argument("--branch", required=True)
    claim.add_argument("--worktree", required=True)
    claim.add_argument("--write-scope", action="append", default=[])
    claim.add_argument("--claimed-path", action="append", default=[])
    claim.add_argument("--test", action="append", default=[])
    claim.add_argument("--ttl-hours", type=float, default=8.0)
    claim.add_argument("--allow-overlap", action="store_true")
    claim.add_argument("--json", action="store_true")

    complete = sub.add_parser("complete", help="Record a completion receipt")
    complete.add_argument("--lease-id", required=True)
    complete.add_argument("--agent", required=True)
    complete.add_argument("--session-id", required=True)
    complete.add_argument("--branch", required=True)
    complete.add_argument("--worktree", required=True)
    complete.add_argument("--base-sha", default=None)
    complete.add_argument("--head-sha", default=None)
    complete.add_argument("--commit", action="append", default=[])
    complete.add_argument("--changed-path", action="append", default=[])
    complete.add_argument("--test", action="append", default=[])
    complete.add_argument("--validation", action="append", default=[])
    complete.add_argument("--assumption", action="append", default=[])
    complete.add_argument("--blocker", action="append", default=[])
    complete.add_argument("--outcome", default="completed")
    complete.add_argument("--risk", action="append", default=[])
    complete.add_argument("--pr-url", default=None)
    complete.add_argument("--pr-number", type=int, default=None)
    complete.add_argument("--confidence", type=float, default=0.0)
    complete.add_argument("--json", action="store_true")

    heartbeat = sub.add_parser("heartbeat", help="Refresh a lease TTL")
    heartbeat.add_argument("--lease-id", required=True)
    heartbeat.add_argument("--ttl-hours", type=float, default=None)
    heartbeat.add_argument("--json", action="store_true")

    decide = sub.add_parser("decide", help="Record an integration decision")
    decide.add_argument("--receipt-id", required=True)
    decide.add_argument(
        "--decision",
        required=True,
        choices=[item.value for item in IntegrationDecisionType],
    )
    decide.add_argument("--decided-by", required=True)
    decide.add_argument("--rationale", required=True)
    decide.add_argument("--target-branch", default="main")
    decide.add_argument("--commit", action="append", default=[])
    decide.add_argument("--follow-up", action="append", default=[])
    decide.add_argument("--lease-id", default=None)
    decide.add_argument("--json", action="store_true")

    salvage = sub.add_parser("scan-salvage", help="Scan stashes/worktrees for salvage candidates")
    salvage.add_argument("--no-worktrees", action="store_true")
    salvage.add_argument("--no-stashes", action="store_true")
    salvage.add_argument("--max-stashes", type=int, default=25)
    salvage.add_argument("--json", action="store_true")

    sync_queue = sub.add_parser(
        "sync-queue",
        help="Project pending integration/salvage items into the global work queue",
    )
    sync_queue.add_argument("--json", action="store_true")

    tasks = sub.add_parser("tasks", help="List canonical developer tasks")
    tasks.add_argument("--open-only", action="store_true")
    tasks.add_argument("--json", action="store_true")

    sync_tasks = sub.add_parser(
        "sync-tasks",
        help="Project open developer tasks into the global work queue",
    )
    sync_tasks.add_argument("--json", action="store_true")

    reap = sub.add_parser("reap", help="Expire stale leases and release mirrored fleet claims")
    reap.add_argument("--json", action="store_true")

    return parser


def _run_command(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    store: DevCoordinationStore,
) -> int:
    if args.command == "status":
        payload = store.status_summary()
        if args.json:
            print(json.dumps(payload, indent=2))  # noqa: T201
        else:
            counts = payload["counts"]
            print(  # noqa: T201
                f"active_leases={counts['active_leases']} "
                f"pending_integrations={counts['pending_integrations']} "
                f"open_salvage_candidates={counts['open_salvage_candidates']} "
                f"open_developer_tasks={counts['open_developer_tasks']}"
            )
        return 0

    if args.command == "claim":
        try:
            lease = store.claim_lease(
                task_id=args.task_id,
                title=args.title,
                owner_agent=args.agent,
                owner_session_id=args.session_id,
                branch=args.branch,
                worktree_path=args.worktree,
                allowed_globs=args.write_scope,
                claimed_paths=args.claimed_path,
                expected_tests=args.test,
                ttl_hours=args.ttl_hours,
                allow_overlap=args.allow_overlap,
            )
        except LeaseConflictError as exc:
            if args.json:
                print(json.dumps({"ok": False, "conflicts": exc.conflicts}, indent=2))  # noqa: T201
            else:
                print("lease_conflict", json.dumps(exc.conflicts, indent=2))  # noqa: T201
            return 2
        if args.json:
            print(json.dumps({"ok": True, "lease": lease.to_dict()}, indent=2))  # noqa: T201
        else:
            print(lease.lease_id)  # noqa: T201
        return 0

    if args.command == "complete":
        receipt = store.record_completion(
            lease_id=args.lease_id,
            owner_agent=args.agent,
            owner_session_id=args.session_id,
            branch=args.branch,
            worktree_path=args.worktree,
            base_sha=args.base_sha,
            head_sha=args.head_sha,
            commit_shas=args.commit,
            changed_paths=args.changed_path,
            tests_run=args.test,
            validations_run=args.validation,
            assumptions=args.assumption,
            blockers=args.blocker,
            outcome=args.outcome,
            risks=args.risk,
            pr_url=args.pr_url,
            pr_number=args.pr_number,
            confidence=args.confidence,
        )
        if args.json:
            print(json.dumps({"ok": True, "receipt": receipt.to_dict()}, indent=2))  # noqa: T201
        else:
            print(receipt.receipt_id)  # noqa: T201
        return 0

    if args.command == "heartbeat":
        lease = store.heartbeat_lease(
            lease_id=args.lease_id,
            ttl_hours=args.ttl_hours,
        )
        if args.json:
            print(json.dumps({"ok": True, "lease": lease.to_dict()}, indent=2))  # noqa: T201
        else:
            print(lease.lease_id)  # noqa: T201
        return 0

    if args.command == "decide":
        decision = store.record_integration_decision(
            receipt_id=args.receipt_id,
            decision=IntegrationDecisionType(args.decision),
            decided_by=args.decided_by,
            rationale=args.rationale,
            target_branch=args.target_branch,
            chosen_commits=args.commit,
            followups=args.follow_up,
            lease_id=args.lease_id,
        )
        if args.json:
            print(json.dumps({"ok": True, "decision": decision.to_dict()}, indent=2))  # noqa: T201
        else:
            print(decision.decision_id)  # noqa: T201
        return 0

    if args.command == "scan-salvage":
        items = store.scan_salvage_sources(
            include_worktrees=not args.no_worktrees,
            include_stashes=not args.no_stashes,
            max_stashes=args.max_stashes,
        )
        payload = {
            "ok": True,
            "count": len(items),
            "candidates": [item.to_dict() for item in items],
        }
        if args.json:
            print(json.dumps(payload, indent=2))  # noqa: T201
        else:
            print(payload["count"])  # noqa: T201
        return 0

    if args.command == "sync-queue":
        payload = {
            "ok": True,
            "counts": asyncio.run(store.sync_pending_work_queue()),
        }
        if args.json:
            print(json.dumps(payload, indent=2))  # noqa: T201
        else:
            print(json.dumps(payload["counts"], indent=2))  # noqa: T201
        return 0

    if args.command == "tasks":
        payload = {
            "ok": True,
            "count": 0,
            "tasks": [
                item.to_dict() for item in store.list_developer_tasks(open_only=args.open_only)
            ],
        }
        payload["count"] = len(payload["tasks"])
        if args.json:
            print(json.dumps(payload, indent=2))  # noqa: T201
        else:
            print(payload["count"])  # noqa: T201
        return 0

    if args.command == "sync-tasks":
        payload = {
            "ok": True,
            "counts": asyncio.run(store.sync_developer_task_queue()),
        }
        if args.json:
            print(json.dumps(payload, indent=2))  # noqa: T201
        else:
            print(json.dumps(payload["counts"], indent=2))  # noqa: T201
        return 0

    if args.command == "reap":
        expired = store.reap_expired_leases()
        stale = store.reap_stale_leases()
        all_reaped = expired + stale
        payload = {
            "ok": True,
            "count": len(all_reaped),
            "expired": len(expired),
            "stale": len(stale),
            "leases": [lease.to_dict() for lease in all_reaped],
        }
        if args.json:
            print(json.dumps(payload, indent=2))  # noqa: T201
        else:
            print(payload["count"])  # noqa: T201
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2
