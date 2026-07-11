#!/usr/bin/env python3
"""Harvest engine: fold merged/parked/orphaned outcomes back into the backlog (#8760).

Bounded single-pass harvest for cron/launchd (not a daemon): scans recently
closed/merged PRs and stale remote branches (read-only via gh/git) and
classifies each as learned-pattern (fed to the swarm OutcomeLearner via the
outcome-signal JSONL log), salvage-candidate (WIP-capped boss-loop follow-up
issue), or write-off (recorded, no action). Overflow beyond --max-issues is
recorded as deferred, never silently dropped; per-run counts append to a
durable JSONL ledger. DRY-RUN BY DEFAULT — nothing is mutated without --apply.
This script NEVER closes PRs, deletes branches, or comments on others' PRs;
those authorities stay with the separately-gated cleanup plan
(docs/plans/2026-06-30-queue-drain-diagnosis-and-cleanup-plan.md).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

DEFAULT_REPO = "synaptent/aragora"
DEFAULT_SINCE_DAYS = 7
DEFAULT_MAX_ISSUES = 5
DEFAULT_MAX_BRANCHES = 50
DEFAULT_BRANCH_STALE_DAYS = 14
DEFAULT_PR_SCAN_LIMIT = 200
DEFAULT_LEDGER_PATH = Path("docs/status/harvest_ledger.jsonl")
DEFAULT_SIGNAL_LOG = Path("~/.aragora/outcome_signals.jsonl").expanduser()

CLASS_LEARNED = "learned-pattern"
CLASS_SALVAGE = "salvage-candidate"
CLASS_WRITEOFF = "write-off"

# Minimum additive diff for salvage (the "genuine feature: additive, tested"
# archetype from the 2026-06-30 harvest map).
SALVAGE_MIN_ADDITIONS = 30
# gh subcommands this script must never issue (cleanup-plan authority).
_FORBIDDEN_GH_TOKENS = frozenset({"close", "delete", "merge", "comment", "DELETE"})
# Branch name hints for feature work worth salvaging (vs. substrate churn).
_SALVAGE_NAME_HINTS = ("feat/", "feat-", "feature/")

_PR_JSON_FIELDS = "number,title,mergedAt,closedAt,additions,deletions,isDraft,headRefName,url"


def _find_due_receipt_followups(
    receipt_followups: list[Any] | None,
    *,
    now: datetime | None,
) -> list[dict[str, Any]]:
    """Return due receipt follow-ups without making cron startup import Aragora.

    ``harvest_outcomes.py`` is intentionally stdlib-only for launchd/cron
    startup. The receipt follow-up integration is optional and currently has no
    CLI source, so normal scheduled runs must not import the full ``aragora``
    package just to report an empty list.
    """
    if not receipt_followups:
        return []

    from aragora.insights.receipt_followups import find_due_falsification_followups

    return find_due_falsification_followups(receipt_followups, now=now)


def run_gh(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run a gh command with a hard guard against destructive subcommands."""
    forbidden = _FORBIDDEN_GH_TOKENS.intersection(args)
    if forbidden:
        raise RuntimeError(
            f"harvest_outcomes refuses destructive gh subcommand {sorted(forbidden)}; "
            "close/delete/comment authority stays with the gated cleanup plan"
        )
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def run_git(
    args: list[str], repo_root: Path, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@dataclass
class HarvestItem:
    """One classified PR or branch."""

    kind: str  # "pr" | "branch"
    identifier: str  # "#8389" or "feat/goals-store"
    title: str
    classification: str
    reason: str
    url: str = ""
    head_sha: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def source(self) -> str:
        """Stable provenance key used for ledger dedup."""
        return f"{self.kind}:{self.identifier}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "source": self.source}


def fetch_recent_prs(
    *, repo: str, since_days: int, limit: int = DEFAULT_PR_SCAN_LIMIT
) -> list[dict[str, Any]]:
    """List PRs closed within the past ``since_days`` days (read-only)."""
    args = ["pr", "list", "--repo", repo, "--state", "closed", "--limit", str(limit)]
    proc = run_gh([*args, "--json", _PR_JSON_FIELDS])
    if proc.returncode != 0:
        raise RuntimeError(f"gh pr list failed: {proc.stderr.strip()}")
    cutoff = datetime.now(UTC) - timedelta(days=since_days)
    prs = []
    for pr in json.loads(proc.stdout or "[]"):
        closed_at = _parse_ts(pr.get("closedAt") or pr.get("mergedAt") or "")
        if closed_at is not None and closed_at >= cutoff:
            prs.append(pr)
    return prs


def fetch_open_pr_head_refs(*, repo: str) -> set[str]:
    """Head branch names of open PRs — those branches belong to the PR flow."""
    args = ["pr", "list", "--repo", repo, "--state", "open", "--limit", "300"]
    proc = run_gh([*args, "--json", "headRefName"])
    if proc.returncode != 0:
        raise RuntimeError(f"gh pr list (open) failed: {proc.stderr.strip()}")
    return {row.get("headRefName", "") for row in json.loads(proc.stdout or "[]")}


def _verify_origin_fresh(repo_root: Path) -> None:
    """Fail loud if local origin/main is stale vs the remote.

    Branch ancestry facts (merge-base, is-ancestor, ahead counts) are only
    meaningful against fresh remote-tracking refs. ``git ls-remote`` is a
    read-only network check; on mismatch we refuse rather than misclassify.
    """
    local = run_git(["rev-parse", "refs/remotes/origin/main"], repo_root)
    remote = run_git(["ls-remote", "origin", "refs/heads/main"], repo_root, timeout=120)
    if local.returncode != 0 or remote.returncode != 0:
        raise RuntimeError(
            "cannot verify origin/main freshness; run `git fetch origin --prune` and retry"
        )
    remote_sha = remote.stdout.split()[0] if remote.stdout.split() else ""
    if remote_sha and remote_sha != local.stdout.strip():
        raise RuntimeError(
            f"local origin/main ({local.stdout.strip()[:12]}) is stale vs remote "
            f"({remote_sha[:12]}); run `git fetch origin --prune` before harvesting"
        )


def fetch_stale_branches(
    *,
    repo_root: Path,
    stale_days: int,
    max_branches: int,
    exclude_refs: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Discover stale remote branches (read-only; requires fresh origin refs)."""
    _verify_origin_fresh(repo_root)
    fmt = "%(refname:short)%09%(objectname)%09%(committerdate:iso8601-strict)"
    proc = run_git(
        ["for-each-ref", "--sort=-committerdate", "refs/remotes/origin/", f"--format={fmt}"],
        repo_root,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git for-each-ref failed: {proc.stderr.strip()}")
    exclude = exclude_refs or set()
    cutoff = datetime.now(UTC) - timedelta(days=stale_days)
    branches: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        refname, sha, committed = parts
        name = refname.removeprefix("origin/")
        if name in ("HEAD", "main", "master") or name in exclude:
            continue
        committed_at = _parse_ts(committed)
        if committed_at is None or committed_at >= cutoff:
            continue
        branches.append(_inspect_branch(repo_root, refname, name, sha, committed))
        if len(branches) >= max_branches:
            break
    return branches


def _inspect_branch(
    repo_root: Path, refname: str, name: str, sha: str, committed_at: str
) -> dict[str, Any]:
    """Compute ancestry facts for a single remote branch (read-only)."""
    merge_base = run_git(["merge-base", "origin/main", refname], repo_root)
    orphaned = merge_base.returncode != 0 or not merge_base.stdout.strip()
    merged = False
    ahead_count = 0
    if not orphaned:
        is_ancestor = run_git(["merge-base", "--is-ancestor", refname, "origin/main"], repo_root)
        merged = is_ancestor.returncode == 0
        if not merged:
            counted = run_git(["rev-list", "--count", f"origin/main..{refname}"], repo_root)
            try:
                ahead_count = int(counted.stdout.strip()) if counted.returncode == 0 else 0
            except ValueError:
                ahead_count = 0
    return {
        "name": name,
        "sha": sha[:12],
        "committed_at": committed_at,
        "orphaned": orphaned,
        "merged": merged,
        "ahead_count": ahead_count,
    }


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def classify_pr(pr: dict[str, Any]) -> tuple[str, str]:
    """Classify a recently closed PR into exactly one harvest bucket."""
    if pr.get("mergedAt"):
        return CLASS_LEARNED, "merged to main — success outcome for the learner"
    if pr.get("isDraft"):
        return CLASS_WRITEOFF, "closed while still draft — abandoned in-flight work"
    title = str(pr.get("title", ""))
    additions = int(pr.get("additions") or 0)
    deletions = int(pr.get("deletions") or 0)
    is_feature = title.lower().startswith("feat")
    if is_feature and additions >= SALVAGE_MIN_ADDITIONS and additions > deletions:
        return CLASS_SALVAGE, (
            f"closed feature PR with non-trivial additive diff (+{additions}/-{deletions})"
        )
    return CLASS_WRITEOFF, (
        f"closed without merge and no salvage archetype (+{additions}/-{deletions})"
    )


def classify_branch(branch: dict[str, Any]) -> tuple[str, str]:
    """Classify a stale remote branch into exactly one harvest bucket."""
    if branch.get("merged"):
        return CLASS_LEARNED, "branch tip already on main — work landed"
    if branch.get("orphaned"):
        return CLASS_WRITEOFF, (
            "orphaned by history rewrite (no merge-base with origin/main); "
            "ancestry-unrecoverable — deletion stays with the gated cleanup plan"
        )
    name = str(branch.get("name", "")).lower()
    ahead = int(branch.get("ahead_count") or 0)
    if ahead > 0 and any(hint in name for hint in _SALVAGE_NAME_HINTS):
        return CLASS_SALVAGE, f"stale feature branch with {ahead} unique commit(s)"
    if ahead == 0:
        return CLASS_WRITEOFF, "no unique commits vs origin/main"
    return CLASS_WRITEOFF, "stale non-feature branch (substrate churn archetype)"


def build_salvage_issue(item: HarvestItem) -> dict[str, str]:
    """Render a bounded follow-up issue in boss-loop format."""
    origin = f"PR {item.identifier}" if item.kind == "pr" else f"branch `{item.identifier}`"
    provenance = [f"- harvest-source: {item.source}"]
    if item.url:
        provenance.append(f"- origin: {item.url}")
    if item.head_sha:
        provenance.append(f"- head SHA: {item.head_sha}")
    provenance.append(f"- classification reason: {item.reason}")
    body = "\n".join(
        [
            "Bounded salvage follow-up generated by `scripts/harvest_outcomes.py` (#8760).",
            "",
            "## Files",
            f"- Recover the diff from {origin} "
            "(cherry-pick or re-implement against current main; do NOT force-merge stale history).",
            "",
            "## Acceptance",
            "- The salvageable behavior from the source is re-landed on main behind tests.",
            "- New/changed code has test coverage; full suite stays green.",
            "- If the value is no longer relevant, close this issue with a recorded rationale.",
            "",
            "## Constraints",
            "- Scope to the single feature from the source diff; no drive-by refactors.",
            "- Never delete the source branch or close the source PR from this issue "
            "(that authority stays with the gated cleanup plan).",
            "- Keep the change reviewable (<800 LOC delta).",
            "",
            "## Provenance",
            *provenance,
        ]
    )
    return {"title": f"Salvage: {item.title} (from {origin})"[:200], "body": body}


def apply_wip_cap(
    items: list[HarvestItem], max_issues: int
) -> tuple[list[HarvestItem], list[HarvestItem]]:
    """Split salvage candidates at the WIP cap; the tail is deferred, not dropped."""
    cap = max(0, int(max_issues))
    return items[:cap], items[cap:]


def append_ledger(ledger_path: Path, record: dict[str, Any]) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def load_filed_sources(ledger_path: Path) -> set[str]:
    """Sources for which a salvage issue was already filed in a prior run."""
    if not ledger_path.exists():
        return set()
    sources: set[str] = set()
    try:
        with open(ledger_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for filed in record.get("issues_filed", []) or []:
                    if filed.get("source"):
                        sources.add(str(filed["source"]))
    except OSError:
        pass
    return sources


def load_emitted_signal_sources(ledger_path: Path) -> set[str]:
    """Sources whose learner signal was already emitted in a prior run."""
    if not ledger_path.exists():
        return set()
    sources: set[str] = set()
    try:
        with open(ledger_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for source in record.get("signal_sources", []) or []:
                    sources.add(str(source))
    except OSError:
        pass
    return sources


def emit_learned_signals(items: list[HarvestItem], signal_log: Path, ledger_path: Path) -> int:
    """Append one OutcomeSignal per not-yet-emitted learned-pattern item.

    ``aragora.swarm.outcome_learner.load_category_success_rates`` consumes this
    JSONL log, so appending here is exactly "feeding the learner" (plain-dict
    fallback if the aragora package is unavailable). Emission is deduped by
    source via the ledger so repeated --apply runs over overlapping windows
    never double-count; sources actually written are ledgered even if a
    mid-batch write fails.
    """
    already = load_emitted_signal_sources(ledger_path)
    to_emit = [i for i in items if i.source not in already]
    if not to_emit:
        return 0
    signal_log.parent.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    try:
        with open(signal_log, "a", encoding="utf-8") as f:
            for item in to_emit:
                ref = str(item.details.get("headRefName") or item.identifier).lower()
                agent = next(
                    (a for a in ("codex", "claude", "gemini", "grok") if ref.startswith(f"{a}/")),
                    "",
                )
                base: dict[str, Any] = {
                    "source_loop": "harvest",
                    "signal_type": "completed",
                    "entity_id": item.source,
                    "entity_title": item.title,
                    "did_merge": "merged" in item.reason or "landed" in item.reason,
                    "agent_type": agent,
                }
                try:
                    from aragora.swarm.outcome_signals import OutcomeSignal

                    row = OutcomeSignal(**base).to_dict()
                except ImportError:
                    row = {**base, "timestamp": datetime.now(UTC).isoformat()}
                f.write(json.dumps(row) + "\n")
                written.append(item.source)
    finally:
        if written:
            append_ledger(
                ledger_path,
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event": "signals_emitted",
                    "signal_sources": written,
                },
            )
    return len(written)


def file_salvage_issues(
    repo: str, items: list[HarvestItem], ledger_path: Path
) -> list[dict[str, str]]:
    """The ONLY gh write path in this script; called only under --apply.

    Each successfully-created issue is ledgered IMMEDIATELY so a mid-batch gh
    failure leaves the ledger true and the next run's dedup skips it.
    """
    filed = []
    for item in items:
        issue = build_salvage_issue(item)
        proc = run_gh(
            ["issue", "create", "--repo", repo, "--title", issue["title"], "--body", issue["body"]]
        )
        if proc.returncode != 0:
            raise RuntimeError(f"gh issue create failed for {item.source}: {proc.stderr.strip()}")
        lines = str(proc.stdout or "").strip().splitlines()
        url = lines[-1].strip() if lines else ""
        record = {"source": item.source, "title": issue["title"], "url": url}
        append_ledger(
            ledger_path,
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "issue_filed",
                "issues_filed": [record],
            },
        )
        filed.append(record)
    return filed


def run_harvest(
    *,
    repo: str,
    repo_root: Path,
    since_days: int = DEFAULT_SINCE_DAYS,
    max_issues: int = DEFAULT_MAX_ISSUES,
    max_branches: int = DEFAULT_MAX_BRANCHES,
    branch_stale_days: int = DEFAULT_BRANCH_STALE_DAYS,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    signal_log: Path = DEFAULT_SIGNAL_LOG,
    apply: bool = False,
    receipt_followups: list[Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One bounded harvest pass. Read-only unless ``apply`` is True."""
    items: list[HarvestItem] = []
    for pr in fetch_recent_prs(repo=repo, since_days=since_days):
        classification, reason = classify_pr(pr)
        items.append(
            HarvestItem(
                "pr",
                f"#{pr.get('number')}",
                str(pr.get("title", "")),
                classification,
                reason,
                url=str(pr.get("url", "")),
                details={"headRefName": pr.get("headRefName", "")},
            )
        )
    open_heads = fetch_open_pr_head_refs(repo=repo)
    for branch in fetch_stale_branches(
        repo_root=repo_root,
        stale_days=branch_stale_days,
        max_branches=max_branches,
        exclude_refs=open_heads,
    ):
        classification, reason = classify_branch(branch)
        name = str(branch.get("name", ""))
        items.append(
            HarvestItem(
                "branch",
                name,
                name,
                classification,
                reason,
                head_sha=str(branch.get("sha", "")),
                details={"ahead_count": branch.get("ahead_count", 0)},
            )
        )

    learned = [i for i in items if i.classification == CLASS_LEARNED]
    salvage = [i for i in items if i.classification == CLASS_SALVAGE]
    already_filed = load_filed_sources(ledger_path)
    skipped = [i for i in salvage if i.source in already_filed]
    fresh = [i for i in salvage if i.source not in already_filed]
    to_file, deferred = apply_wip_cap(fresh, max_issues)
    counts = {
        CLASS_LEARNED: len(learned),
        CLASS_SALVAGE: len(salvage),
        CLASS_WRITEOFF: sum(1 for i in items if i.classification == CLASS_WRITEOFF),
        "total": len(items),
    }

    issues_filed: list[dict[str, str]] = []
    signals_emitted = 0
    if apply:
        # Both steps ledger their own successes incrementally, so a mid-batch
        # failure in either leaves the ledger true for the next run's dedup.
        issues_filed = file_salvage_issues(repo, to_file, ledger_path)
        signals_emitted = emit_learned_signals(learned, signal_log, ledger_path)
        append_ledger(
            ledger_path,
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "run_summary",
                "repo": repo,
                "since_days": since_days,
                "counts": counts,
                "issues_filed": issues_filed,
                "deferred": [i.source for i in deferred],
                "skipped_already_filed": [i.source for i in skipped],
                "signals_emitted": signals_emitted,
            },
        )

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "mode": "apply" if apply else "dry-run",
        "repo": repo,
        "since_days": since_days,
        "counts": counts,
        "items": [i.to_dict() for i in items],
        "salvage": {
            "to_file": [i.to_dict() for i in to_file],
            "deferred": [i.to_dict() for i in deferred],
            "skipped_already_filed": [i.to_dict() for i in skipped],
        },
        "issues_filed": issues_filed,
        "signals_emitted": signals_emitted,
        "receipt_followups": _find_due_receipt_followups(receipt_followups, now=now),
        "ledger_appended": apply,
        "ledger_path": str(ledger_path),
    }


def build_parser() -> argparse.ArgumentParser:
    description = next((line for line in (__doc__ or "").splitlines() if line.strip()), "")
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--since-days", type=int, default=DEFAULT_SINCE_DAYS)
    parser.add_argument("--max-issues", type=int, default=DEFAULT_MAX_ISSUES)
    parser.add_argument("--max-branches", type=int, default=DEFAULT_MAX_BRANCHES)
    parser.add_argument("--branch-stale-days", type=int, default=DEFAULT_BRANCH_STALE_DAYS)
    parser.add_argument("--ledger-path", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--signal-log", type=Path, default=DEFAULT_SIGNAL_LOG)
    parser.add_argument("--apply", action="store_true", help="Mutate (otherwise dry-run)")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output")
    return parser


def _print_human(result: dict[str, Any]) -> None:
    counts = result["counts"]
    print(f"harvest_outcomes [{result['mode']}] repo={result['repo']}")
    print("  counts: " + " | ".join(f"{v} {k}" for k, v in counts.items()))
    for item in result.get("items", []):
        print(f"  [{item['classification']:>17}] {item['source']}: {item['reason']}")
    salvage = result.get("salvage", {})
    for bucket in ("to_file", "deferred", "skipped_already_filed"):
        for item in salvage.get(bucket, []):
            print(f"  salvage {bucket}: {item['source']} — {item['title']}")
    for filed in result.get("issues_filed", []):
        print(f"  filed: {filed['url']} ({filed['source']})")
    print(
        f"  signals_emitted={result.get('signals_emitted', 0)} "
        f"ledger_appended={result.get('ledger_appended', False)} "
        f"ledger={result.get('ledger_path', '')}"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_harvest(
            repo=args.repo,
            repo_root=args.repo_root,
            since_days=args.since_days,
            max_issues=args.max_issues,
            max_branches=args.max_branches,
            branch_stale_days=args.branch_stale_days,
            ledger_path=args.ledger_path,
            signal_log=args.signal_log,
            apply=args.apply,
        )
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"harvest_outcomes failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_human(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
