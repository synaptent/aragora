#!/usr/bin/env python3
"""Add labels to a GitHub issue from a keyword map (strictly additive).

Purpose
-------
Runs from ``.github/workflows/issue-autolabel.yml`` on ``issues: [opened,
edited]``. Reads the event payload, matches keywords from
``.github/issue-labeler.json`` against the issue title and body, and adds the
resulting labels through ``gh api``. It never removes a label and it never
touches an issue that carries ``triage:protected``.

The mapping is a pure function so it can be unit-tested
(``tests/ci/test_issue_autolabel.py``) and reused by
``scripts/label_unlabeled_issues.py``. Stdlib only.

Usage
-----
    python scripts/issue_autolabel.py --event-path "$GITHUB_EVENT_PATH"
    python scripts/issue_autolabel.py --event-path event.json --dry-run

Requires ``GH_TOKEN`` (or an authenticated ``gh``) unless ``--dry-run``.

Exit codes
----------
    0 -- labels added, nothing to add, or the issue is protected.
    1 -- ``gh api`` failed.
    2 -- usage error, unreadable event payload, or invalid map file.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

DEFAULT_MAP_PATH = ".github/issue-labeler.json"
PROTECTED_LABEL = "triage:protected"

EXIT_OK = 0
EXIT_GH_FAILED = 1
EXIT_USAGE = 2


# --- pure mapping -----------------------------------------------------------


def is_protected(existing_labels: Iterable[str]) -> bool:
    """True when the issue carries the exact ``triage:protected`` label."""
    return PROTECTED_LABEL in set(existing_labels)


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    # Word-prefix match: "receipt" hits "Receipts" but the leading boundary
    # keeps "preceipt" from matching. Whitespace in a keyword matches any run
    # of whitespace.
    parts = [re.escape(p) for p in keyword.split()]
    return re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(parts), re.IGNORECASE)


def labels_for(
    title: str,
    body: str | None,
    existing_labels: Iterable[str],
    mapping: Mapping[str, str],
) -> list[str]:
    """Return the sorted labels to ADD for an issue.

    Empty when the issue is ``triage:protected`` or no keyword matches. Labels
    already present are never proposed, and nothing is ever removed.
    """
    existing = set(existing_labels)
    if is_protected(existing):
        return []
    haystack = f"{title}\n{body or ''}"
    wanted: set[str] = set()
    for keyword, label in mapping.items():
        if label in existing or label in wanted:
            continue
        if _keyword_pattern(keyword).search(haystack):
            wanted.add(label)
    return sorted(wanted)


def load_mapping(path: Path) -> dict[str, str]:
    """Load ``{"keywords": {keyword: label}}`` from ``path``; ValueError on bad shape."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read map file {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("keywords"), dict):
        raise ValueError(f'map file {path} must be an object with a "keywords" object')
    keywords: dict[str, str] = {}
    for key, value in data["keywords"].items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"map file {path}: empty keyword")
        if not isinstance(value, str) or not value:
            raise ValueError(f"map file {path}: label for {key!r} must be a non-empty string")
        keywords[key] = value
    return keywords


# --- gh wiring ----------------------------------------------------------------


def run_gh(args: Sequence[str], *, input: str | None = None) -> int:  # noqa: A002
    """Launch ``gh`` and return its exit code (patched in tests)."""
    try:
        return subprocess.run(list(args), input=input, text=True, check=False).returncode
    except OSError as exc:
        print(f"ERROR: cannot launch gh: {exc}", file=sys.stderr)
        return EXIT_GH_FAILED


def add_labels(repo: str, number: int, labels: Sequence[str]) -> int:
    """POST the labels (additive endpoint) via ``gh api``; returns gh's exit code."""
    payload = json.dumps({"labels": list(labels)})
    return run_gh(
        ["gh", "api", "-X", "POST", f"repos/{repo}/issues/{number}/labels", "--input", "-"],
        input=payload,
    )


def _load_event(path: Path) -> tuple[str, int, str, str | None, list[str]]:
    try:
        event = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read event payload {path}: {exc}") from exc
    issue = event.get("issue") if isinstance(event, dict) else None
    if not isinstance(issue, dict) or "number" not in issue:
        raise ValueError("event payload has no issue (only `issues` events are supported)")
    repo = ((event.get("repository") or {}).get("full_name")) or ""
    labels = [lbl["name"] for lbl in issue.get("labels") or [] if isinstance(lbl, dict)]
    return repo, int(issue["number"]), str(issue.get("title") or ""), issue.get("body"), labels


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Add keyword-derived labels to the issue in a GitHub `issues` event. "
            f"Strictly additive; issues labelled {PROTECTED_LABEL} are never touched."
        ),
        epilog="Exit codes: 0 done/nothing to do, 1 gh api failed, 2 usage or bad input.",
    )
    parser.add_argument(
        "--event-path",
        required=True,
        type=Path,
        help="GitHub event payload (usually $GITHUB_EVENT_PATH).",
    )
    parser.add_argument(
        "--map",
        type=Path,
        default=Path(DEFAULT_MAP_PATH),
        help=f"keyword -> label JSON map (default: {DEFAULT_MAP_PATH}).",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="owner/name override; defaults to repository.full_name from the event.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the labels but do not call gh."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        mapping = load_mapping(args.map)
        repo, number, title, body, existing = _load_event(args.event_path)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE
    repo = args.repo or repo
    if not repo:
        print("ERROR: repository not found in event; pass --repo owner/name", file=sys.stderr)
        return EXIT_USAGE

    if is_protected(existing):
        print(f"#{number}: carries {PROTECTED_LABEL}; leaving untouched")
        return EXIT_OK
    labels = labels_for(title, body, existing, mapping)
    if not labels:
        print(f"#{number}: no labels to add")
        return EXIT_OK
    print(f"#{number}: " + " ".join(f"+{lbl}" for lbl in labels))
    if args.dry_run:
        return EXIT_OK
    rc = add_labels(repo, number, labels)
    if rc != 0:
        print(f"ERROR: gh api exited {rc} while labelling #{number}", file=sys.stderr)
        return EXIT_GH_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
