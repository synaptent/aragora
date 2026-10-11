#!/usr/bin/env python3
"""Classify active Aragora automation handoffs without mutating state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from handoff_state import (  # noqa: E402
    DEFAULT_REPO_ROOT,
    classify_handoffs,
    compact_summary,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="Repository root used for local state and gh cwd (default: current directory).",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help=(
            "Checkout or .aragora directory that owns shared automation state. "
            "Defaults to --repo/.aragora."
        ),
    )
    parser.add_argument(
        "--github-repo",
        default=None,
        help="GitHub repository in owner/name form. Defaults to remote.origin.url.",
    )
    parser.add_argument(
        "--outbox-file",
        default=None,
        help="Classify only this outbox JSON file. Relative names resolve inside automation-outbox.",
    )
    parser.add_argument(
        "--no-github",
        action="store_true",
        help="Disable narrow GitHub REST/ref reads and classify from local state only.",
    )
    parser.add_argument(
        "--owner-timeout-seconds",
        type=int,
        default=20,
        help="Timeout for the read-only owner/liveness helper per branch (default: 20).",
    )
    parser.add_argument(
        "--queue-cache-max-age-seconds",
        type=int,
        default=1800,
        help=(
            "Maximum age for using cached open-PR cap pressure decisions (default: 1800s = 30min)."
        ),
    )
    parser.add_argument(
        "--with-liveness-helper",
        action="store_true",
        help=(
            "Use identify_lane_owner.py --liveness for each item. Default uses the "
            "faster local lane registry to keep whole-outbox classification bounded."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="With --json, omit per-item details and emit compact counts only.",
    )
    parser.add_argument(
        "--fail-on-unsafe-state",
        action="store_true",
        help=(
            "Deprecated compatibility flag. Unsafe classifications exit 2 by default; "
            "this flag is accepted for older callers that still pass it explicitly."
        ),
    )
    return parser


def _has_unsafe_state(payload: dict) -> bool:
    raw_github = payload.get("github")
    github = raw_github if isinstance(raw_github, dict) else {}
    if github.get("mode") in {"disabled", "partial"}:
        return True
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            return True
        if item.get("state") in {"unknown", "preserved_not_actionable"}:
            return True
        if (
            item.get("state")
            in {"represented_by_exact_open_pr", "represented_by_exact_remote_branch"}
            and item.get("safe_to_mutate") is not True
        ):
            return True
        if item.get("next_mutation_candidate") != "none" and item.get("safe_to_mutate") is not True:
            return True
    return False


def _exit_code_for_payload(payload: dict, *, fail_on_unsafe_state: bool = False) -> int:
    # Fail-closed exits are now the default; the flag remains an explicit
    # compatibility alias so older callers do not get a misleading parser error.
    _ = fail_on_unsafe_state
    return 2 if _has_unsafe_state(payload) else 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = classify_handoffs(
        repo_root=args.repo,
        state_root=args.state_root,
        github_repo=args.github_repo,
        outbox_file=args.outbox_file,
        no_github=args.no_github,
        owner_timeout_seconds=args.owner_timeout_seconds,
        with_liveness_helper=args.with_liveness_helper,
        queue_cache_max_age_seconds=args.queue_cache_max_age_seconds,
    )
    output = compact_summary(payload) if args.summary_only else payload
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
        return _exit_code_for_payload(payload, fail_on_unsafe_state=args.fail_on_unsafe_state)

    print(f"schema_version: {output['schema_version']}")
    print(f"generated_at: {output['generated_at']}")
    print(f"repo: {output['repo']}")
    print(f"outbox_count: {output['outbox_count']}")
    print("counts:")
    for state, count in sorted((output.get("counts") or {}).items()):
        print(f"  {state}: {count}")
    if not args.summary_only:
        print("items:")
        for item in output.get("items", []):
            print(f"  {item.get('outbox_file')}: {item.get('state')} ({item.get('reason')})")
    return _exit_code_for_payload(payload, fail_on_unsafe_state=args.fail_on_unsafe_state)


if __name__ == "__main__":
    raise SystemExit(main())
