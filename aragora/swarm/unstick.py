"""Boss-loop ``unstick`` planning surface.

The boss-loop emits the ``boss-stuck`` label when it cannot make
progress on an issue. Once labeled, the loop's own ``skip_labels`` set
filters the issue out forever — even if the underlying work has since
been delivered by a different path (a peer agent's PR, a manual fix,
a related issue's PR, etc.).

This module gives operators a **planning** surface that says, for each
``boss-stuck`` issue:

- whether the issue's deterministic boss-harvest branch already has a
  merged PR (i.e. the work is done);
- whether the issue itself has been closed/merged outside the boss-loop;
- whether to recommend ``unstick`` (relabel + post a closure comment),
  ``close`` (the issue is already fully resolved), or ``hold`` (still
  truly stuck).

This module is **dry-run only**: it produces a JSON plan that the
operator (or a future PR) can act on. It performs **no** GitHub
mutations itself.

Wire-up: a CLI entry point lives in
``scripts/boss_loop_unstick_plan.py`` and emits the plan as JSON or
markdown. It accepts already-fetched issue and PR records, just like
:mod:`aragora.swarm.dispatch_evidence`, so this module remains pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable

from aragora.swarm.dispatch_evidence import is_issue_dispatched_via_pr

STUCK_LABEL: Final[str] = "boss-stuck"


@dataclass(frozen=True)
class UnstickRecommendation:
    """Per-issue recommendation produced by :func:`plan_unstick`.

    Attributes:
        issue_number: The numeric issue identifier.
        action: One of ``"unstick"``, ``"close"``, ``"hold"``.
        rationale: Operator-readable explanation.
        evidence: Dict carrying the dispatch verdict and any merged
            PR numbers, suitable for embedding in a comment.
    """

    issue_number: int
    action: str
    rationale: str
    evidence: dict[str, object]


_VALID_ACTIONS: Final[frozenset[str]] = frozenset({"unstick", "close", "hold"})


@dataclass(frozen=True)
class _NormalizedIssue:
    number: int
    state: str
    labels: list[str]


def _normalize_issue_record(record: object) -> _NormalizedIssue | None:
    if not isinstance(record, dict):
        return None
    raw_number = record.get("number")
    if not isinstance(raw_number, int) or raw_number <= 0:
        return None
    state = str(record.get("state") or "").strip().upper()
    labels_raw = record.get("labels") or []
    labels: list[str] = []
    if isinstance(labels_raw, list):
        for entry in labels_raw:
            if isinstance(entry, dict):
                name = entry.get("name")
                if isinstance(name, str) and name:
                    labels.append(name)
            elif isinstance(entry, str) and entry:
                labels.append(entry)
    return _NormalizedIssue(number=raw_number, state=state, labels=labels)


def plan_unstick(
    *,
    stuck_issue_records: Iterable[dict[str, object]],
    pr_records: Iterable[dict[str, object]],
) -> list[UnstickRecommendation]:
    """Build per-issue unstick recommendations.

    Args:
        stuck_issue_records: Iterable of dicts with at least
            ``number``, ``state`` (e.g. ``"OPEN"`` or ``"CLOSED"``),
            and ``labels`` (list of dicts with ``name`` or list of
            strings). Only issues carrying the ``boss-stuck`` label
            will appear in the output.
        pr_records: Iterable of dicts with at least ``number``,
            ``state``, and ``headRefName`` (the shape from
            ``gh pr list --json number,state,headRefName``).

    Returns:
        A list of :class:`UnstickRecommendation`, one per stuck issue,
        sorted by ``issue_number``.
    """
    pr_list = list(pr_records or [])
    out: list[UnstickRecommendation] = []
    seen: set[int] = set()
    for raw in stuck_issue_records or []:
        record = _normalize_issue_record(raw)
        if record is None:
            continue
        issue_number = record.number
        if issue_number in seen:
            continue
        if STUCK_LABEL not in record.labels:
            continue
        seen.add(issue_number)
        verdict = is_issue_dispatched_via_pr(issue_number, pr_records=pr_list)
        state = record.state

        merged_raw = verdict.get("pr_numbers_merged")
        open_raw = verdict.get("pr_numbers_open")
        merged_prs: list[int] = list(merged_raw) if isinstance(merged_raw, list) else []
        open_prs: list[int] = list(open_raw) if isinstance(open_raw, list) else []

        if state in {"CLOSED", "MERGED"}:
            action = "close"
            rationale = (
                f"Issue is already {state.lower()} on GitHub; the boss-stuck label "
                f"is stale. Recommend removing the label so future scans treat the "
                f"issue as resolved."
            )
        elif merged_prs:
            action = "unstick"
            rationale = (
                f"Boss-harvest PR(s) {merged_prs} merged to main. The work is "
                f"shipped; remove the boss-stuck label and post a closure comment "
                f"linking the merged PR. Operator may also close the issue."
            )
        elif open_prs:
            action = "hold"
            rationale = (
                f"Boss-harvest PR(s) {open_prs} are open and in-flight. Hold the "
                f"boss-stuck label until the PR merges or closes."
            )
        else:
            action = "hold"
            rationale = (
                "No merged or open boss-harvest PR found for this issue. The "
                "stuck label correctly reflects current state."
            )

        evidence = {
            "issue_state": state,
            "best_pr_state": verdict.get("best_state"),
            "merged_pr_numbers": merged_prs,
            "open_pr_numbers": open_prs,
        }
        out.append(
            UnstickRecommendation(
                issue_number=issue_number,
                action=action,
                rationale=rationale,
                evidence=evidence,
            )
        )

    out.sort(key=lambda r: r.issue_number)
    return out


def summarize_plan(recommendations: Iterable[UnstickRecommendation]) -> dict[str, object]:
    """Summarize a plan into operator-friendly counts.

    Returns a dict with ``total``, ``by_action`` (counts), and
    ``by_action_issue_numbers`` (sorted issue lists per action).
    """
    by_action: dict[str, int] = dict.fromkeys(_VALID_ACTIONS, 0)
    by_action_issue_numbers: dict[str, list[int]] = {a: [] for a in _VALID_ACTIONS}
    total = 0
    for rec in recommendations or []:
        if not isinstance(rec, UnstickRecommendation):
            continue
        if rec.action not in _VALID_ACTIONS:
            continue
        total += 1
        by_action[rec.action] += 1
        by_action_issue_numbers[rec.action].append(rec.issue_number)
    for k in by_action_issue_numbers:
        by_action_issue_numbers[k].sort()
    return {
        "total": total,
        "by_action": by_action,
        "by_action_issue_numbers": by_action_issue_numbers,
    }


def render_markdown(recommendations: Iterable[UnstickRecommendation]) -> str:
    """Render a markdown report for the unstick plan."""
    rows = list(recommendations or [])
    summary = summarize_plan(rows)
    total = summary["total"] if isinstance(summary["total"], int) else 0
    by_action_obj = summary["by_action"]
    by_action_ids_obj = summary["by_action_issue_numbers"]
    by_action: dict[str, int] = by_action_obj if isinstance(by_action_obj, dict) else {}
    by_action_ids: dict[str, list[int]] = (
        by_action_ids_obj if isinstance(by_action_ids_obj, dict) else {}
    )

    lines = [
        "# Boss-loop unstick plan (dry-run)",
        "",
        f"Total stuck issues considered: **{total}**",
        "",
        "## Counts by action",
        "",
        "| Action | Count | Issue numbers |",
        "| --- | ---: | --- |",
    ]
    for action in ("unstick", "close", "hold"):
        ids: list[int] = by_action_ids.get(action) or []
        ids_str = ", ".join(f"#{n}" for n in ids) if ids else "—"
        lines.append(f"| `{action}` | {by_action.get(action, 0)} | {ids_str} |")

    lines.extend(
        [
            "",
            "## Per-issue recommendations",
            "",
            "| Issue | Action | Issue state | Best PR state | Merged PRs | Rationale |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for rec in rows:
        merged_raw = rec.evidence.get("merged_pr_numbers", [])
        merged_list: list[int] = list(merged_raw) if isinstance(merged_raw, list) else []
        merged = ", ".join(f"#{n}" for n in merged_list)
        lines.append(
            f"| #{rec.issue_number} | `{rec.action}` | "
            f"{rec.evidence.get('issue_state', '?')} | "
            f"{rec.evidence.get('best_pr_state') or '—'} | "
            f"{merged or '—'} | "
            f"{rec.rationale} |"
        )
    lines.extend(["", "_This plan is dry-run only; no GitHub mutations performed._", ""])
    return "\n".join(lines)


__all__ = [
    "STUCK_LABEL",
    "UnstickRecommendation",
    "plan_unstick",
    "summarize_plan",
    "render_markdown",
]
