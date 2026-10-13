#!/usr/bin/env python3
"""Boss-loop metrics health scorecard.

Aggregates ``.aragora/overnight/boss_metrics.jsonl`` to surface
operator-actionable signals:

- **Top-N issues by skip-row count** — issues that the boss-loop
  attempted many times without producing a deliverable; candidates
  for the unstick lane (see PR #6841).
- **Stale skip-loop detector** — issues that have ``>=N`` skip rows
  AND are already CLOSED or MERGED on GitHub; these are hard
  evidence that the loop is wasting cycles.
- **dispatch_skip_reason aggregation** — once PR #6831's
  ``dispatch_skip_reason`` field appears in the metrics file,
  surface the top reasons. Falls back to ``terminal_class`` when
  ``dispatch_skip_reason`` is not yet emitted.

This is a **read-only** script: no GitHub mutations, no metric
file mutations, JSON output to stdout (or markdown via ``--markdown``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, TypeGuard

# Skip-suggesting terminal_class values (the loop did not produce a deliverable).
SKIP_TERMINAL_CLASSES: frozenset[str] = frozenset(
    {
        "blocked_auth_failure",
        "blocked_not_dispatch_bounded",
        "blocked_sanitation_failed",
        "blocked_validation_target_missing",
        "rescue_no_deliverable",
        "rescue_timeout",
        "rescue_worker_crash",
        "rescue_verification_failed",
    }
)


def load_metrics(path: Path) -> list[dict[str, Any]]:
    """Load JSONL metrics, returning a list of dicts; bad lines are skipped."""
    if not path.exists():
        raise FileNotFoundError(f"metrics file not found: {path}")
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _row_is_skip(row: dict[str, Any]) -> bool:
    """Return True if the row indicates the loop did not produce a deliverable."""
    if row.get("dispatch_skip_reason"):
        return True
    tc = row.get("terminal_class")
    if isinstance(tc, str) and tc in SKIP_TERMINAL_CLASSES:
        return True
    return False


def _valid_issue_number(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_int(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def top_issues_by_skip_count(rows: list[dict[str, Any]], top_n: int = 20) -> list[dict[str, Any]]:
    """Return the top-N issues ranked by skip-row count."""
    top_n = _positive_int(top_n, field="top_n")
    counter: Counter[int] = Counter()
    for row in rows:
        if not _row_is_skip(row):
            continue
        issue_number = row.get("issue_number")
        if not _valid_issue_number(issue_number):
            continue
        counter[issue_number] += 1

    out: list[dict[str, Any]] = []
    for issue_number, count in counter.most_common(top_n):
        last_terminal = None
        last_skip_reason = None
        for row in reversed(rows):
            if row.get("issue_number") == issue_number:
                last_terminal = row.get("terminal_class")
                last_skip_reason = row.get("dispatch_skip_reason")
                break
        out.append(
            {
                "issue_number": issue_number,
                "skip_count": count,
                "last_terminal_class": last_terminal,
                "last_dispatch_skip_reason": last_skip_reason,
            }
        )
    return out


def aggregate_skip_reasons(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Aggregate ``dispatch_skip_reason`` values, falling back to terminal_class."""
    counter: Counter[str] = Counter()
    for row in rows:
        reason = row.get("dispatch_skip_reason")
        if isinstance(reason, str) and reason:
            counter[f"dispatch_skip_reason:{reason}"] += 1
            continue
        tc = row.get("terminal_class")
        if isinstance(tc, str) and tc in SKIP_TERMINAL_CLASSES:
            counter[f"terminal_class:{tc}"] += 1
    return dict(counter.most_common())


def detect_stale_loops(rows: list[dict[str, Any]], min_skip_rows: int = 10) -> list[dict[str, Any]]:
    """Return issues with ``>=min_skip_rows`` skip rows.

    A high skip count is a strong signal that the loop is stuck on
    that issue. The actual GitHub state (CLOSED/MERGED vs OPEN) is
    not checked here — that requires GitHub network access. The
    operator can join this list with ``aragora/swarm/unstick.py``
    output.
    """
    min_skip_rows = _positive_int(min_skip_rows, field="min_skip_rows")
    counter: Counter[int] = Counter()
    for row in rows:
        if not _row_is_skip(row):
            continue
        issue_number = row.get("issue_number")
        if not _valid_issue_number(issue_number):
            continue
        counter[issue_number] += 1

    return [
        {"issue_number": issue_number, "skip_count": count}
        for issue_number, count in sorted(counter.items(), key=lambda x: (-x[1], x[0]))
        if count >= min_skip_rows
    ]


def render_scorecard(
    rows: list[dict[str, Any]],
    *,
    top_n: int = 20,
    stale_threshold: int = 10,
) -> dict[str, Any]:
    """Compute the full scorecard payload."""
    top_n = _positive_int(top_n, field="top_n")
    stale_threshold = _positive_int(stale_threshold, field="stale_threshold")
    return {
        "total_rows": len(rows),
        "skip_rows": sum(1 for row in rows if _row_is_skip(row)),
        "deliverable_rows": sum(
            1
            for row in rows
            if row.get("terminal_class") in {"deliverable_pr_created", "deliverable_branch_pushed"}
        ),
        "skip_reason_counts": aggregate_skip_reasons(rows),
        "top_issues_by_skip_count": top_issues_by_skip_count(rows, top_n=top_n),
        "stale_threshold": stale_threshold,
        "stale_loops": detect_stale_loops(rows, min_skip_rows=stale_threshold),
    }


def render_markdown(scorecard: dict[str, Any]) -> str:
    """Render the scorecard as a markdown report."""
    lines = ["# boss-loop metrics health scorecard", ""]
    total = scorecard.get("total_rows", 0)
    skip = scorecard.get("skip_rows", 0)
    deliv = scorecard.get("deliverable_rows", 0)
    lines.append(f"- total rows: **{total}**")
    lines.append(f"- skip rows: **{skip}** ({(skip / total * 100) if total else 0:.1f}%)")
    lines.append(f"- deliverable rows: **{deliv}** ({(deliv / total * 100) if total else 0:.1f}%)")
    lines.append("")

    lines.append("## Top skip reasons")
    lines.append("")
    lines.append("| Reason | Count |")
    lines.append("| --- | ---: |")
    for reason, count in (scorecard.get("skip_reason_counts") or {}).items():
        lines.append(f"| `{reason}` | {count} |")
    lines.append("")

    lines.append("## Top issues by skip count")
    lines.append("")
    lines.append("| Issue | Skip count | Last terminal_class | Last dispatch_skip_reason |")
    lines.append("| --- | ---: | --- | --- |")
    for entry in scorecard.get("top_issues_by_skip_count") or []:
        lines.append(
            f"| #{entry['issue_number']} | {entry['skip_count']} | "
            f"{entry.get('last_terminal_class') or '—'} | "
            f"{entry.get('last_dispatch_skip_reason') or '—'} |"
        )
    lines.append("")

    stale = scorecard.get("stale_loops") or []
    stale_threshold = scorecard.get("stale_threshold", 10)
    lines.append(f"## Stale loops (>= {stale_threshold} skip rows)")
    lines.append("")
    if stale:
        lines.append("| Issue | Skip count |")
        lines.append("| --- | ---: |")
        for entry in stale:
            lines.append(f"| #{entry['issue_number']} | {entry['skip_count']} |")
    else:
        lines.append("_No issues exceed the stale-loop threshold._")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metrics",
        type=Path,
        default=Path(".aragora/overnight/boss_metrics.jsonl"),
        help="Path to boss_metrics.jsonl (default: .aragora/overnight/boss_metrics.jsonl)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="Number of issues to show in the top-skip table (default: 20)",
    )
    parser.add_argument(
        "--stale-threshold",
        type=int,
        default=10,
        help="Skip-row count threshold for the stale-loop detector (default: 10)",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format (default: json)",
    )
    args = parser.parse_args(argv)
    if args.top_n <= 0:
        parser.error("--top-n must be a positive integer")
    if args.stale_threshold <= 0:
        parser.error("--stale-threshold must be a positive integer")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = load_metrics(args.metrics)
    scorecard = render_scorecard(rows, top_n=args.top_n, stale_threshold=args.stale_threshold)
    if args.format == "markdown":
        print(render_markdown(scorecard))
    else:
        print(json.dumps(scorecard, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
