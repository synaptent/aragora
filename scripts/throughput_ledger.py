#!/usr/bin/env python3
"""Feed and inspect the throughput ledger (epic #9039, issue #9041).

SENSE-phase aggregator for the work-mix governor
(docs/plans/2026-07-08-vision-audit-and-work-mix-governor.md §4.1):
``snapshot`` classifies recently merged PRs (read-only via gh) into
product-core / product-proof / substrate / maintenance and appends merge +
snapshot records to ``.aragora/throughput/ledger.jsonl``; ``show`` prints the
rolling metrics. READ-ONLY vs GitHub — the only writes are ledger appends.
Advisory Phase 1: nothing here changes gate or goal-selection behavior.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from aragora.nomic.throughput import ThroughputLedger, compute_metrics
from aragora.nomic.work_mix import classify_paths


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _gh_json(cmd: list[str], *, repo_root: str, failure: str) -> object:
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
            cwd=repo_root,
        ).stdout
    except FileNotFoundError:
        sys.exit("gh CLI not found; snapshot requires gh (read-only)")
    except subprocess.TimeoutExpired:
        sys.exit(f"gh timed out {failure}")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"gh failed {failure}: {exc.stderr.strip()[:200]}")
    return json.loads(out)


def _gh_repo_name(*, repo_root: str) -> str:
    payload = _gh_json(
        ["gh", "repo", "view", "--json", "nameWithOwner"],
        repo_root=repo_root,
        failure="resolving repository",
    )
    if not isinstance(payload, dict) or not payload.get("nameWithOwner"):
        sys.exit("gh failed resolving repository: missing nameWithOwner")
    return str(payload["nameWithOwner"])


def _parse_merged_at(pr: dict) -> datetime:
    return datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00"))


def _gh_pr_files_paginated(number: int, *, repo: str, repo_root: str) -> list[dict]:
    payload = _gh_json(
        [
            "gh",
            "api",
            f"repos/{repo}/pulls/{number}/files",
            "--paginate",
            "--slurp",
        ],
        repo_root=repo_root,
        failure=f"paginating files for merged PR #{number}",
    )
    if not isinstance(payload, list):
        sys.exit(f"gh failed paginating files for merged PR #{number}: unexpected JSON shape")
    files: list[dict] = []
    for page in payload:
        if not isinstance(page, list):
            sys.exit(f"gh failed paginating files for merged PR #{number}: unexpected JSON shape")
        for item in page:
            if not isinstance(item, dict) or not isinstance(item.get("filename"), str):
                sys.exit(
                    f"gh failed paginating files for merged PR #{number}: unexpected file entry"
                )
            files.append(
                {
                    "path": item["filename"],
                    "additions": item.get("additions", 0),
                    "deletions": item.get("deletions", 0),
                }
            )
    return files


def _gh_merged_pr_details(number: int, *, repo: str, repo_root: str) -> dict:
    payload = _gh_json(
        [
            "gh",
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "number,title,mergedAt,labels,files,changedFiles",
        ],
        repo_root=repo_root,
        failure=f"reading merged PR #{number}",
    )
    if not isinstance(payload, dict):
        sys.exit(f"gh failed reading merged PR #{number}: unexpected JSON shape")
    # ``gh pr view --json files`` truncates the file list for large PRs
    # (#9048 openai [P2]); re-fetch via the paginated REST endpoint whenever
    # the reported changedFiles count disagrees with what we received.
    files = payload.get("files")
    changed = payload.get("changedFiles")
    if not isinstance(files, list) or (isinstance(changed, int) and changed != len(files)):
        payload["files"] = _gh_pr_files_paginated(number, repo=repo, repo_root=repo_root)
    return payload


def _pr_number_from_url(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        return int(value.rstrip("/").rsplit("/", 1)[-1])
    except ValueError:
        return None


def _gh_merged_prs(limit: int, *, repo_root: str = ".", lookback_days: int = 90) -> list[dict]:
    if limit <= 0:
        return []

    # ``gh pr list --search 'sort:updated-desc'`` can omit recent merges when
    # older merged PRs receive newer comments or label edits. Search by
    # merge-date buckets instead, then fetch exact PR details for the newest
    # mergedAt values we will actually record.
    repo = _gh_repo_name(repo_root=repo_root)
    merged_by_number: dict[int, dict] = {}
    for offset in range(max(lookback_days, 1)):
        day = _today_utc() - timedelta(days=offset)
        search_payload = _gh_json(
            [
                "gh",
                "search",
                "prs",
                "--repo",
                repo,
                "--merged",
                "--merged-at",
                day.isoformat(),
                "--limit",
                "1000",
                "--json",
                "url",
            ],
            repo_root=repo_root,
            failure=f"searching merged PRs for {day.isoformat()}",
        )
        if not isinstance(search_payload, list):
            sys.exit("gh failed searching merged PRs: unexpected JSON shape")
        for item in search_payload:
            if isinstance(item, dict):
                number = _pr_number_from_url(item.get("url"))
                if number is not None:
                    if number not in merged_by_number:
                        merged_by_number[number] = _gh_merged_pr_details(
                            number, repo=repo, repo_root=repo_root
                        )
                elif item.get("url") is not None:
                    sys.exit("gh failed searching merged PRs: unexpected PR URL")
        if len(merged_by_number) >= limit:
            break

    return sorted(
        merged_by_number.values(),
        key=_parse_merged_at,
        reverse=True,
    )[:limit]


@contextlib.contextmanager
def _snapshot_lock(ledger: ThroughputLedger):
    """Exclusive flock across read-seen + append so concurrent snapshot runs
    cannot double-record the same merged PR (#9048 openai [P2])."""
    lock_path = ledger.path.with_suffix(ledger.path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def cmd_snapshot(args: argparse.Namespace) -> int:
    ledger = ThroughputLedger(args.repo_root)
    with _snapshot_lock(ledger):
        return _snapshot_locked(args, ledger)


def _snapshot_locked(args: argparse.Namespace, ledger: ThroughputLedger) -> int:
    seen = {record.data.get("identifier") for record in ledger.records() if record.kind == "merge"}
    added = 0
    for pr in _gh_merged_prs(
        args.limit, repo_root=args.repo_root, lookback_days=args.lookback_days
    ):
        identifier = str(pr["number"])
        if identifier in seen:
            continue
        files = pr.get("files", [])
        classified = classify_paths(
            [f["path"] for f in files],
            identifier=identifier,
            title=pr.get("title", ""),
            labels=[label["name"] for label in pr.get("labels", [])],
            # Line weights so trivial padding can't flip the classification.
            weights={f["path"]: f.get("additions", 0) + f.get("deletions", 0) for f in files},
        )
        ledger.record_merge(
            classified,
            title=pr.get("title", ""),
            when=datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00")),
        )
        added += 1
    metrics = compute_metrics(ledger.records(), window_days=args.window_days)
    ledger.record_snapshot(
        {
            "merges_total": metrics.merges_total,
            "product_share": round(metrics.product_share, 3),
            "substrate_share": round(metrics.substrate_share, 3),
            "self_repair_ratio": round(metrics.self_repair_ratio, 3),
            "external_artifacts": metrics.external_artifacts,
            "new_merge_records": added,
        }
    )
    print(f"recorded {added} new merges; ledger at {ledger.path}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    ledger = ThroughputLedger(args.repo_root)
    metrics = compute_metrics(ledger.records(), window_days=args.window_days)
    payload = asdict(metrics)
    payload["merges_by_class"] = {
        cls.value: count for cls, count in metrics.merges_by_class.items()
    }
    print(json.dumps(payload, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="repo checkout root")
    parser.add_argument("--window-days", type=int, default=7)
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot", help="classify recent merges into the ledger")
    snapshot.add_argument("--limit", type=int, default=30, help="merged PRs to scan")
    snapshot.add_argument(
        "--lookback-days",
        type=int,
        default=90,
        help="merge-date days to search when backfilling recent merged PRs",
    )
    snapshot.set_defaults(func=cmd_snapshot)
    show = sub.add_parser("show", help="print rolling metrics as JSON")
    show.set_defaults(func=cmd_show)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
