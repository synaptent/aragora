#!/usr/bin/env python3
"""One-shot backlog labeler: add labels to every unlabeled open issue.

Purpose
-------
Backfills labels on issues that predate ``.github/workflows/issue-autolabel.yml``
using the same keyword map (``.github/issue-labeler.json``) and the same pure
``labels_for`` function from ``scripts/issue_autolabel.py``. Unlabeled issues
that match no keyword get ``--fallback`` (default ``triage:unverified``, the
"needs a human read" disposition from ``docs/guides/ISSUE_TRIAGE.md``) so that
the run leaves zero unlabeled open issues.

Guarantees
----------
* Dry run is the default: prints the plan and performs zero mutations.
* ``triage:protected`` issues are never touched.
* Strictly additive: the only write is ``POST /repos/<repo>/issues/<n>/labels``.
* Constant number of ``gh`` launches for the plan (one issue list, one label
  list); ``--apply`` adds exactly one POST per issue, ``time.sleep(0.5)``
  between writes, and aborts on the first ``gh`` error.
* Idempotent: a second run finds nothing to label.

Usage
-----
    python scripts/label_unlabeled_issues.py              # dry run (default)
    python scripts/label_unlabeled_issues.py --dry-run
    python scripts/label_unlabeled_issues.py --apply      # one-shot write

Exit codes
----------
    0 -- plan printed (dry run) or every planned label applied.
    1 -- a ``gh`` call failed (the run stops at that call).
    2 -- usage error, bad map file, or the map targets a label that does not
         exist in the repo (checked before any write).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from issue_autolabel import (  # noqa: E402
    DEFAULT_MAP_PATH,
    PROTECTED_LABEL,
    is_protected,
    labels_for,
    load_mapping,
)

DEFAULT_REPO = "synaptent/aragora"
DEFAULT_FALLBACK = "triage:unverified"
WRITE_PAUSE_SECONDS = 0.5

EXIT_OK = 0
EXIT_GH_FAILED = 1
EXIT_USAGE = 2


@dataclass(frozen=True)
class GhResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class PlanEntry:
    number: int
    title: str
    labels: list[str]


def run_gh(args: Sequence[str], *, input: str | None = None) -> GhResult:  # noqa: A002
    """Launch ``gh`` once and capture the result (patched in tests)."""
    try:
        proc = subprocess.run(list(args), input=input, text=True, capture_output=True, check=False)
    except OSError as exc:
        return GhResult(EXIT_GH_FAILED, "", f"cannot launch gh: {exc}")
    return GhResult(proc.returncode, proc.stdout, proc.stderr)


def _gh_json(args: Sequence[str]) -> list[dict[str, object]]:
    res = run_gh(args)
    if res.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} exited {res.returncode}: {res.stderr.strip()}")
    data = json.loads(res.stdout or "[]")
    if not isinstance(data, list):
        raise RuntimeError(f"{' '.join(args)}: expected a JSON array")
    return data


def list_open_issues(repo: str) -> list[dict[str, object]]:
    """Single ``gh issue list`` call; the limit is fixed, not per-issue."""
    return _gh_json(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            "1000",
            "--json",
            "number,title,body,labels,createdAt",
        ]
    )


def list_label_names(repo: str) -> set[str]:
    """Single ``gh label list`` call used to validate the map's targets."""
    rows = _gh_json(["gh", "label", "list", "--repo", repo, "--limit", "300", "--json", "name"])
    return {str(row["name"]) for row in rows}


def _label_names(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(lbl["name"]) for lbl in raw if isinstance(lbl, dict) and "name" in lbl]


def build_plan(
    issues: Sequence[Mapping[str, object]],
    mapping: Mapping[str, str],
    *,
    fallback: str | None,
) -> list[PlanEntry]:
    """Pure: which labels to add to which unlabeled, unprotected issue."""
    plan: list[PlanEntry] = []
    for issue in sorted(issues, key=lambda i: int(str(i["number"]))):
        existing = _label_names(issue.get("labels"))
        if existing or is_protected(existing):
            continue
        title = str(issue.get("title") or "")
        body = issue.get("body")
        labels = labels_for(title, body if isinstance(body, str) else None, existing, mapping)
        if not labels and fallback:
            labels = [fallback]
        if labels:
            plan.append(PlanEntry(int(str(issue["number"])), title, labels))
    return plan


def add_labels(repo: str, number: int, labels: Sequence[str]) -> GhResult:
    payload = json.dumps({"labels": list(labels)})
    return run_gh(
        ["gh", "api", "-X", "POST", f"repos/{repo}/issues/{number}/labels", "--input", "-"],
        input=payload,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Label every unlabeled open issue from the keyword map. Dry run by default; "
            f"never touches {PROTECTED_LABEL} issues; never removes labels."
        ),
        epilog=(
            "Exit codes: 0 plan printed or all labels applied; 1 a gh call failed "
            "(run aborts at that call); 2 usage error, bad map, or unknown target label."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan (issue number, title, labels to add) and change nothing. This is the default.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help=f"apply the plan: one POST per issue with a {WRITE_PAUSE_SECONDS}s pause between writes.",
    )
    parser.add_argument(
        "--repo", default=DEFAULT_REPO, help=f"owner/name (default: {DEFAULT_REPO})."
    )
    parser.add_argument(
        "--map",
        type=Path,
        default=Path(DEFAULT_MAP_PATH),
        help=f"keyword -> label JSON map (default: {DEFAULT_MAP_PATH}).",
    )
    parser.add_argument(
        "--fallback",
        default=DEFAULT_FALLBACK,
        help=(
            "label for unlabeled issues that match no keyword "
            f"(default: {DEFAULT_FALLBACK}; pass '' to leave them unlabeled)."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fallback = args.fallback or None
    try:
        mapping = load_mapping(args.map)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        known = list_label_names(args.repo)
        issues = list_open_issues(args.repo)
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_GH_FAILED

    targets = set(mapping.values()) | ({fallback} if fallback else set())
    unknown = sorted(targets - known)
    if unknown:
        print(
            f"ERROR: map targets labels that do not exist in {args.repo}: {unknown}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    plan = build_plan(issues, mapping, fallback=fallback)
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] {len(issues)} open issue(s) fetched; {len(plan)} issue(s) to label")
    for entry in plan:
        print(f"  #{entry.number}  +{','.join(entry.labels)}  {entry.title}")
    if not args.apply:
        if plan:
            print("dry run: no changes made (re-run with --apply to write)")
        return EXIT_OK

    for index, entry in enumerate(plan):
        if index:
            time.sleep(WRITE_PAUSE_SECONDS)
        res = add_labels(args.repo, entry.number, entry.labels)
        if res.returncode != 0:
            print(
                f"ERROR: gh api exited {res.returncode} labelling #{entry.number}; "
                f"aborting after {index} write(s): {res.stderr.strip()}",
                file=sys.stderr,
            )
            return EXIT_GH_FAILED
        print(f"  #{entry.number} labelled")
    print(f"applied {len(plan)} issue(s)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
