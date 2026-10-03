#!/usr/bin/env python3
"""File Stage-Gate Conductor drift issues with fingerprint-based dedup.

The Stage-Gate Conductor's escalation rule allows one bounded ``[stage-gate]``
issue per run, but repeated runs observing the *same* finding must land on a
single anchor issue instead of opening a near-duplicate every cycle (see
issue #9490: ~19 duplicates of the ``b0-corpus-exhausted`` finding).

Contract:

- Every drift issue body carries a stable machine-readable marker line::

    `Drift-Fingerprint: <kebab-slug-of-finding-class>`

- Before filing, search open ``stage-gate-drift`` issues for a matching
  fingerprint. If an anchor exists, append the new observation as a comment
  on it; only create a new issue for a genuinely new finding class.
- The recurring run log uses one rolling anchor per month
  (``[automation] Stage-Gate Conductor Log (YYYY-MM)``) rather than a new
  ``automation-log`` issue per run.

CLI (all subcommands are dry-run unless ``--apply`` is passed)::

    python scripts/stage_gate_drift.py file --repo org/repo \
        --fingerprint b0-corpus-exhausted \
        --title "[stage-gate] ..." --body-file drift.md --apply

    python scripts/stage_gate_drift.py log --repo org/repo \
        --month 2026-07 --body-file run_summary.md --apply
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

DRIFT_LABEL = "stage-gate-drift"
LOG_LABEL = "automation-log"
LOG_TITLE_PREFIX = "[automation] Stage-Gate Conductor Log"
DEFAULT_REPO = "synaptent/aragora"

_FINGERPRINT_RE = re.compile(
    r"^[ \t]*`?drift-fingerprint:\s*([A-Za-z0-9][A-Za-z0-9-]*)`?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_ISSUE_URL_RE = re.compile(r"https?://[^\s]+/issues/(\d+)(?:[?#][^\s]*)?")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_GH_TIMEOUT = 30


def slugify_fingerprint(text: str) -> str:
    """Normalize a finding-class name to a stable kebab-case slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise ValueError(f"fingerprint {text!r} normalizes to an empty slug")
    return slug


def render_fingerprint_line(slug: str) -> str:
    return f"`Drift-Fingerprint: {slug}`"


def extract_fingerprint(body: str) -> str | None:
    """Return the fingerprint slug embedded in an issue body, if any."""
    matches = list(_FINGERPRINT_RE.finditer(body or ""))
    if not matches:
        return None
    return matches[-1].group(1).lower()


def find_anchor(issues: list[dict[str, Any]], slug: str) -> dict[str, Any] | None:
    """Return the lowest-numbered open issue whose body carries ``slug``."""
    matches = [
        issue for issue in issues if extract_fingerprint(str(issue.get("body") or "")) == slug
    ]
    if not matches:
        return None
    return min(matches, key=lambda issue: int(issue.get("number") or 0))


def _run_gh(args: list[str], *, timeout: int = _GH_TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def list_open_drift_issues(*, repo: str, label: str = DRIFT_LABEL) -> list[dict[str, Any]]:
    result = _run_gh(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--label",
            label,
            "--state",
            "open",
            "--limit",
            "1000",
            "--json",
            "number,title,body",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh issue list failed")
    payload = json.loads(result.stdout or "[]")
    return [item for item in payload if isinstance(item, dict)]


def comment_on_issue(*, repo: str, number: int, body: str) -> None:
    result = _run_gh(["issue", "comment", str(number), "--repo", repo, "--body", body])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh issue comment failed")


def create_issue(*, repo: str, title: str, body: str, labels: list[str]) -> dict[str, Any]:
    cmd = ["issue", "create", "--repo", repo, "--title", title, "--body", body]
    for label in labels:
        cmd.extend(["--label", label])
    result = _run_gh(cmd)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh issue create failed")
    url_matches = list(_ISSUE_URL_RE.finditer(str(result.stdout or "")))
    if not url_matches:
        raise RuntimeError("gh issue create returned no issue URL")
    url_match = url_matches[-1]
    return {
        "number": int(url_match.group(1)),
        "title": title,
        "url": url_match.group(0),
    }


def _ensure_fingerprint_in_body(body: str, slug: str) -> str:
    without_markers = _FINGERPRINT_RE.sub("", body).rstrip()
    return f"{without_markers}\n\n{render_fingerprint_line(slug)}\n"


def file_drift(
    *,
    repo: str,
    fingerprint: str,
    title: str,
    body: str,
    apply: bool = False,
    label: str = DRIFT_LABEL,
) -> dict[str, Any]:
    """Comment on the existing anchor for ``fingerprint``, or create one."""
    slug = slugify_fingerprint(fingerprint)
    issues = list_open_drift_issues(repo=repo, label=label)
    anchor = find_anchor(issues, slug)
    if anchor is not None:
        number = int(anchor["number"])
        if not apply:
            return {"action": "would_comment", "number": number, "fingerprint": slug}
        comment_on_issue(repo=repo, number=number, body=body)
        return {"action": "commented", "number": number, "fingerprint": slug}
    if not apply:
        return {"action": "would_create", "number": None, "fingerprint": slug}
    created = create_issue(
        repo=repo,
        title=title,
        body=_ensure_fingerprint_in_body(body, slug),
        labels=[label],
    )
    return {"action": "created", "number": created.get("number"), "fingerprint": slug}


def log_anchor_title(month: str) -> str:
    return f"{LOG_TITLE_PREFIX} ({month})"


def post_log_entry(
    *,
    repo: str,
    month: str,
    body: str,
    apply: bool = False,
) -> dict[str, Any]:
    """Append a run summary to the rolling monthly Conductor log anchor."""
    if not _MONTH_RE.match(month):
        raise ValueError(f"month must be YYYY-MM, got {month!r}")
    title = log_anchor_title(month)
    issues = list_open_drift_issues(repo=repo, label=LOG_LABEL)
    matches = [i for i in issues if str(i.get("title") or "").strip() == title]
    if matches:
        number = int(min(matches, key=lambda issue: int(issue.get("number") or 0))["number"])
        if not apply:
            return {"action": "would_comment", "number": number, "title": title}
        comment_on_issue(repo=repo, number=number, body=body)
        return {"action": "commented", "number": number, "title": title}
    if not apply:
        return {"action": "would_create", "number": None, "title": title}
    created = create_issue(
        repo=repo,
        title=title,
        body=(
            f"Rolling log for the Stage-Gate Conductor automation for {month}. "
            "Each run appends one comment; do not open per-run log issues."
        ),
        labels=[LOG_LABEL],
    )
    created_number = created.get("number")
    if created_number is not None:
        comment_on_issue(repo=repo, number=int(created_number), body=body)
    return {"action": "created", "number": created_number, "title": title}


def _read_body(args: argparse.Namespace) -> str:
    if args.body is not None:
        return args.body
    if args.body_file == "-":
        return sys.stdin.read()
    with open(args.body_file, encoding="utf-8") as handle:
        return handle.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    file_parser = sub.add_parser("file", help="File a drift finding with dedup")
    file_parser.add_argument("--repo", default=DEFAULT_REPO)
    file_parser.add_argument("--fingerprint", required=True)
    file_parser.add_argument("--title", required=True)
    file_parser.add_argument("--apply", action="store_true")
    body_group = file_parser.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body")
    body_group.add_argument("--body-file")

    log_parser = sub.add_parser("log", help="Append to the monthly log anchor")
    log_parser.add_argument("--repo", default=DEFAULT_REPO)
    log_parser.add_argument("--month", required=True, help="YYYY-MM")
    log_parser.add_argument("--apply", action="store_true")
    log_body_group = log_parser.add_mutually_exclusive_group(required=True)
    log_body_group.add_argument("--body")
    log_body_group.add_argument("--body-file")

    args = parser.parse_args(argv)
    if args.command == "file":
        result = file_drift(
            repo=args.repo,
            fingerprint=args.fingerprint,
            title=args.title,
            body=_read_body(args),
            apply=args.apply,
        )
    else:
        result = post_log_entry(
            repo=args.repo, month=args.month, body=_read_body(args), apply=args.apply
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
