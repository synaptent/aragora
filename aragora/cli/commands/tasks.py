"""Public CLI for the developer task queue and lease lifecycle."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import inspect
import json
import subprocess
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, cast


def _resolve(result: Any) -> Any:
    """Resolve an awaitable from sync CLI code."""
    if inspect.isawaitable(result):
        return asyncio.run(cast(Coroutine[Any, Any, Any], result))
    return result


def _repo_root() -> Path:
    from aragora.worktree.fleet import resolve_repo_root

    return resolve_repo_root(Path.cwd())


def _load_queue():
    from aragora.nomic.global_work_queue import GlobalWorkQueue

    queue = GlobalWorkQueue(storage_dir=_repo_root() / ".work_queue")
    _resolve(queue.initialize())
    return queue


def _load_store():
    from aragora.nomic.dev_coordination import DevCoordinationStore

    return DevCoordinationStore(repo_root=_repo_root())


def _current_branch(repo_root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _default_agent() -> str:
    user = getpass.getuser().strip() or "unknown"
    return f"cli:{user}"


def _default_session() -> str:
    user = getpass.getuser().strip() or "unknown"
    return f"cli-session:{user}"


def _serialize(item: Any) -> dict[str, Any]:
    if hasattr(item, "to_dict"):
        return item.to_dict()
    if isinstance(item, dict):
        return item
    raise TypeError(f"Unsupported item type: {type(item)!r}")


def _queue_task_defaults(
    task_id: str, *, queue: Any, store: Any
) -> tuple[str, list[str], list[str]]:
    title = task_id
    allowed_globs: list[str] = []
    expected_tests: list[str] = []

    item = _resolve(queue.get(task_id))
    if item is not None:
        payload = _serialize(item)
        title = str(payload.get("title") or title)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        if isinstance(metadata, dict):
            allowed_globs = [str(p) for p in metadata.get("allowed_paths", []) if str(p).strip()]
            expected_tests = [
                str(item) for item in metadata.get("acceptance_checks", []) if str(item).strip()
            ]

    if task_id.startswith("task:"):
        developer_task = store.get_developer_task(task_id.split("task:", 1)[1])
        if developer_task is not None:
            title = developer_task.title or title
            if not allowed_globs:
                allowed_globs = [str(p) for p in developer_task.allowed_paths if str(p).strip()]
            if not expected_tests:
                expected_tests = [
                    str(item) for item in developer_task.acceptance_checks if str(item).strip()
                ]

    return title, allowed_globs, expected_tests


def _active_lease(store: Any, lease_id: str) -> Any | None:
    for lease in store.list_active_leases():
        if getattr(lease, "lease_id", "") == lease_id:
            return lease
    return None


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))  # noqa: T201


def _print_queue_table(items: list[dict[str, Any]]) -> None:
    print(f"{'ID':28s} {'Status':12s} {'Type':12s} {'Pri':>4s} Title")  # noqa: T201
    print("-" * 88)  # noqa: T201
    for item in items:
        priority = item.get("computed_priority", item.get("base_priority", 0))
        print(  # noqa: T201
            f"{str(item.get('id', ''))[:28]:28s} "
            f"{str(item.get('status', ''))[:12]:12s} "
            f"{str(item.get('work_type', ''))[:12]:12s} "
            f"{int(priority):>4d} "
            f"{str(item.get('title', ''))[:28]}"
        )


def _print_leases_table(items: list[dict[str, Any]]) -> None:
    print(  # noqa: T201
        f"{'Lease ID':14s} {'Task ID':28s} {'Agent':18s} {'Status':12s} {'Branch':18s} Expires"
    )
    print("-" * 118)  # noqa: T201
    for item in items:
        print(  # noqa: T201
            f"{str(item.get('lease_id', ''))[:14]:14s} "
            f"{str(item.get('task_id', ''))[:28]:28s} "
            f"{str(item.get('owner_agent', ''))[:18]:18s} "
            f"{str(item.get('status', ''))[:12]:12s} "
            f"{str(item.get('branch', ''))[:18]:18s} "
            f"{str(item.get('expires_at', ''))}"
        )


def _print_salvage_table(items: list[dict[str, Any]]) -> None:
    print(f"{'Candidate ID':14s} {'Source':12s} {'Branch':18s} Summary")  # noqa: T201
    print("-" * 88)  # noqa: T201
    for item in items:
        print(  # noqa: T201
            f"{str(item.get('candidate_id', ''))[:14]:14s} "
            f"{str(item.get('source_kind', ''))[:12]:12s} "
            f"{str(item.get('branch', ''))[:18]:18s} "
            f"{str(item.get('summary', ''))[:36]}"
        )


def add_tasks_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the public tasks command."""
    parser = subparsers.add_parser(
        "tasks",
        help="Inspect and operate the developer task queue",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="tasks_command")

    list_p = sub.add_parser("list", help="List queued work items")
    list_p.add_argument(
        "--status",
        choices=["pending", "ready", "claimed", "in_progress", "blocked", "completed", "failed"],
    )
    list_p.add_argument(
        "--work-type",
        choices=["bead", "convoy", "molecule", "escalation", "maintenance", "custom"],
    )
    list_p.add_argument("--limit", type=int, default=20)
    list_p.add_argument(
        "--format", dest="output_format", choices=["table", "json"], default="table"
    )

    show_p = sub.add_parser("show", help="Show one queued work item")
    show_p.add_argument("task_id")
    show_p.add_argument("--format", dest="output_format", choices=["table", "json"], default="json")

    claim_p = sub.add_parser("claim", help="Claim a queued task and create a lease")
    claim_p.add_argument("task_id")
    claim_p.add_argument("--agent", default=None, help="Owner agent id")
    claim_p.add_argument("--session-id", default=None, help="Owner session id")
    claim_p.add_argument("--title", default=None, help="Override lease title")
    claim_p.add_argument("--branch", default=None, help="Branch for the lease")
    claim_p.add_argument("--worktree", default=None, help="Worktree path for the lease")
    claim_p.add_argument("--ttl-hours", type=float, default=8.0)
    claim_p.add_argument("--write-scope", action="append", default=[], help="Allowed path glob")
    claim_p.add_argument(
        "--claimed-path", action="append", default=[], help="Explicit claimed path"
    )
    claim_p.add_argument("--test", action="append", default=[], help="Expected test")
    claim_p.add_argument("--allow-overlap", action="store_true")
    claim_p.add_argument(
        "--format", dest="output_format", choices=["table", "json"], default="json"
    )

    leases_p = sub.add_parser("leases", help="List active leases")
    leases_p.add_argument(
        "--format", dest="output_format", choices=["table", "json"], default="table"
    )

    heartbeat_p = sub.add_parser("heartbeat", help="Refresh a lease heartbeat")
    heartbeat_p.add_argument("lease_id")
    heartbeat_p.add_argument("--ttl-hours", type=float, default=None)
    heartbeat_p.add_argument(
        "--format", dest="output_format", choices=["table", "json"], default="json"
    )

    release_p = sub.add_parser("release", help="Release a lease")
    release_p.add_argument("lease_id")
    release_p.add_argument(
        "--format", dest="output_format", choices=["table", "json"], default="json"
    )

    complete_p = sub.add_parser("complete", help="Complete a lease and emit a receipt")
    complete_p.add_argument("lease_id")
    complete_p.add_argument("--agent", default=None, help="Owner agent id")
    complete_p.add_argument("--session-id", default=None, help="Owner session id")
    complete_p.add_argument("--branch", default=None)
    complete_p.add_argument("--worktree", default=None)
    complete_p.add_argument("--base-sha", default=None)
    complete_p.add_argument("--head-sha", default=None)
    complete_p.add_argument("--commit", action="append", default=[])
    complete_p.add_argument("--changed-path", action="append", default=[])
    complete_p.add_argument("--test", action="append", default=[])
    complete_p.add_argument("--validation", action="append", default=[])
    complete_p.add_argument("--assumption", action="append", default=[])
    complete_p.add_argument("--blocker", action="append", default=[])
    complete_p.add_argument("--risk", action="append", default=[])
    complete_p.add_argument("--outcome", default="completed")
    complete_p.add_argument("--pr-url", default=None)
    complete_p.add_argument("--pr-number", type=int, default=None)
    complete_p.add_argument("--confidence", type=float, default=0.0)
    complete_p.add_argument(
        "--format", dest="output_format", choices=["table", "json"], default="json"
    )

    salvage_p = sub.add_parser("salvage", help="List salvage candidates")
    salvage_p.add_argument(
        "--format", dest="output_format", choices=["table", "json"], default="table"
    )

    stats_p = sub.add_parser("stats", help="Show queue statistics")
    stats_p.add_argument(
        "--format", dest="output_format", choices=["table", "json"], default="json"
    )

    sync_p = sub.add_parser("sync", help="Project developer and pending work into the queue")
    sync_p.add_argument("--skip-developer-tasks", action="store_true")
    sync_p.add_argument("--skip-pending", action="store_true")
    sync_p.add_argument("--keep-missing-open", action="store_true")
    sync_p.add_argument("--format", dest="output_format", choices=["table", "json"], default="json")

    parser.set_defaults(func=cmd_tasks)


def cmd_tasks(args: argparse.Namespace) -> None:
    command = getattr(args, "tasks_command", None)
    if not command:
        print(  # noqa: T201
            "Usage: aragora tasks {list|show|claim|leases|heartbeat|release|complete|salvage|stats|sync}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    dispatch = {
        "list": _cmd_list,
        "show": _cmd_show,
        "claim": _cmd_claim,
        "leases": _cmd_leases,
        "heartbeat": _cmd_heartbeat,
        "release": _cmd_release,
        "complete": _cmd_complete,
        "salvage": _cmd_salvage,
        "stats": _cmd_stats,
        "sync": _cmd_sync,
    }
    dispatch[command](args)


def _cmd_list(args: argparse.Namespace) -> None:
    from aragora.nomic.global_work_queue import WorkStatus, WorkType

    queue = _load_queue()
    status = WorkStatus(args.status) if args.status else None
    work_type = WorkType(args.work_type) if getattr(args, "work_type", None) else None
    items = [
        _serialize(item)
        for item in _resolve(queue.list_items(status=status, work_type=work_type, limit=args.limit))
    ]
    if args.output_format == "json":
        _print_json(items)
        return
    _print_queue_table(items)


def _cmd_show(args: argparse.Namespace) -> None:
    queue = _load_queue()
    item = _resolve(queue.get(args.task_id))
    if item is None:
        print(f"Task {args.task_id} not found", file=sys.stderr)  # noqa: T201
        raise SystemExit(1)
    payload = _serialize(item)
    if args.output_format == "json":
        _print_json(payload)
        return
    _print_queue_table([payload])


def _cmd_claim(args: argparse.Namespace) -> None:
    store = _load_store()
    queue = _load_queue()
    repo_root = _repo_root()
    title, default_scopes, default_tests = _queue_task_defaults(
        args.task_id, queue=queue, store=store
    )
    lease = store.claim_lease(
        task_id=args.task_id,
        title=args.title or title,
        owner_agent=args.agent or _default_agent(),
        owner_session_id=args.session_id or _default_session(),
        branch=args.branch or _current_branch(repo_root),
        worktree_path=args.worktree or str(Path.cwd()),
        allowed_globs=list(args.write_scope or default_scopes),
        claimed_paths=list(args.claimed_path or []),
        expected_tests=list(args.test or default_tests),
        ttl_hours=args.ttl_hours,
        allow_overlap=bool(args.allow_overlap),
    )
    payload = lease.to_dict()
    if args.output_format == "json":
        _print_json(payload)
        return
    _print_leases_table([payload])


def _cmd_leases(args: argparse.Namespace) -> None:
    store = _load_store()
    items = [lease.to_dict() for lease in store.list_active_leases()]
    if args.output_format == "json":
        _print_json(items)
        return
    _print_leases_table(items)


def _cmd_heartbeat(args: argparse.Namespace) -> None:
    store = _load_store()
    lease = store.heartbeat_lease(args.lease_id, ttl_hours=args.ttl_hours)
    payload = lease.to_dict()
    if args.output_format == "json":
        _print_json(payload)
        return
    _print_leases_table([payload])


def _cmd_release(args: argparse.Namespace) -> None:
    store = _load_store()
    lease = store.release_lease(args.lease_id)
    payload = lease.to_dict()
    if args.output_format == "json":
        _print_json(payload)
        return
    _print_leases_table([payload])


def _cmd_complete(args: argparse.Namespace) -> None:
    store = _load_store()
    repo_root = _repo_root()
    active_lease = _active_lease(store, args.lease_id)
    receipt = store.record_completion(
        lease_id=args.lease_id,
        owner_agent=args.agent or getattr(active_lease, "owner_agent", "") or _default_agent(),
        owner_session_id=args.session_id
        or getattr(active_lease, "owner_session_id", "")
        or _default_session(),
        branch=args.branch or getattr(active_lease, "branch", "") or _current_branch(repo_root),
        worktree_path=args.worktree
        or getattr(active_lease, "worktree_path", "")
        or str(Path.cwd()),
        base_sha=args.base_sha,
        head_sha=args.head_sha,
        commit_shas=list(args.commit or []),
        changed_paths=list(args.changed_path or []),
        tests_run=list(args.test or []),
        validations_run=list(args.validation or []),
        assumptions=list(args.assumption or []),
        blockers=list(args.blocker or []),
        outcome=args.outcome,
        risks=list(args.risk or []),
        pr_url=args.pr_url,
        pr_number=args.pr_number,
        confidence=args.confidence,
    )
    payload = receipt.to_dict()
    if args.output_format == "json":
        _print_json(payload)
        return
    print(f"receipt_id={payload['receipt_id']} lease_id={payload['lease_id']}")  # noqa: T201


def _cmd_salvage(args: argparse.Namespace) -> None:
    store = _load_store()
    items = [candidate.to_dict() for candidate in store.list_salvage_candidates()]
    if args.output_format == "json":
        _print_json(items)
        return
    _print_salvage_table(items)


def _cmd_stats(args: argparse.Namespace) -> None:
    queue = _load_queue()
    payload = _resolve(queue.get_statistics())
    if args.output_format == "json":
        _print_json(payload)
        return
    print(  # noqa: T201
        "total_items={total_items} pending_items={pending_items} completed_items={completed_items}".format(
            total_items=payload.get("total_items", 0),
            pending_items=payload.get("pending_items", 0),
            completed_items=payload.get("completed_items", 0),
        )
    )


def _cmd_sync(args: argparse.Namespace) -> None:
    store = _load_store()
    queue = _load_queue()
    counts: dict[str, Any] = {}
    complete_missing = not args.keep_missing_open
    if not args.skip_developer_tasks:
        counts["developer_tasks"] = _resolve(
            store.sync_developer_task_queue(queue, complete_missing=complete_missing)
        )
    if not args.skip_pending:
        counts["pending"] = _resolve(
            store.sync_pending_work_queue(queue, complete_missing=complete_missing)
        )
    if args.output_format == "json":
        _print_json(counts)
        return
    for section, payload in counts.items():
        print(section)  # noqa: T201
        print(json.dumps(payload, indent=2))  # noqa: T201
