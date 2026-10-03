"""Guard the merge-quorum status vocabulary against producer/consumer drift.

``aragora/cli/commands/review_queue.py`` decides a merge-quorum ``status`` string;
``.github/workflows/aragora-merge-quorum.yml`` dispatches on it and ends with a
catch-all::

    fail(f"Unrecognized merge-quorum status '{status}' — failing closed.")

Because ``aragora-merge-quorum`` is a *required* check, any status the evaluator
emits that the workflow never learned becomes a hard failure with no actionable
text — the operator sees a parser error instead of the real reason.

Regression test for #9640, where exactly that happened: ``blocked_by_live_gate``
(emitted when the live gate withholds admin squash, e.g. an ``operator-review-required``
label) and ``settled`` (emitted for an already-merged PR) both fell through to the
catch-all. Nothing coupled the two files, so the drift was invisible until a PR hit it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCER = REPO_ROOT / "aragora" / "cli" / "commands" / "review_queue.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "aragora-merge-quorum.yml"

# The evaluator defines a status two ways, and the guard must catch both:
#   * assignment ...... `status = "..."` / `entry_status = "..."`
#   * dict literal .... `"status": "..."`   (how `already_merged` is defined)
# Missing the dict form is not hypothetical: the first version of this guard only
# matched assignments, shipped green, and `already_merged` still reached the
# catch-all in production. See #9640.
_PRODUCED = re.compile(
    r'^\s*(?:(?:entry_)?status = "([a-z0-9_]+)"|"status": "([a-z0-9_]+)")',
    re.MULTILINE,
)
# `status == "..."` and `status in ("...", "...")` in the workflow's dispatch.
_HANDLED_EQ = re.compile(r'status == "([a-z0-9_]+)"')
_HANDLED_IN = re.compile(r"status in \(([^)]*)\)")
_LITERAL = re.compile(r'"([a-z0-9_]+)"')


def produced_statuses() -> set[str]:
    found = _PRODUCED.findall(PRODUCER.read_text(encoding="utf-8"))
    # Each match yields one group per alternative; keep whichever matched.
    return {value for groups in found for value in groups if value}


def handled_statuses() -> set[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    handled = set(_HANDLED_EQ.findall(text))
    for group in _HANDLED_IN.findall(text):
        handled.update(_LITERAL.findall(group))
    return handled


def test_producer_and_workflow_are_both_readable() -> None:
    """A rename must fail loudly here rather than silently vacuous-pass the guard."""
    assert PRODUCER.is_file(), f"missing evaluator: {PRODUCER}"
    assert WORKFLOW.is_file(), f"missing gate workflow: {WORKFLOW}"
    assert produced_statuses(), "extracted no statuses — the assignment pattern drifted"
    assert handled_statuses(), "extracted no handled statuses — the dispatch pattern drifted"


def test_every_produced_status_is_handled_by_the_gate() -> None:
    produced = produced_statuses()
    handled = handled_statuses()
    unhandled = sorted(produced - handled)
    assert not unhandled, (
        "merge-quorum status(es) emitted by review_queue.py but not handled by "
        f"aragora-merge-quorum.yml: {unhandled}. These fall through to the catch-all "
        "'Unrecognized merge-quorum status' and hard-fail a REQUIRED check with no "
        "actionable message. Add an explicit branch that either exits 0 or fails with "
        "the real reason. See #9640."
    )


def test_regression_9640_statuses_have_explicit_branches() -> None:
    """Pin the statuses that were missing, so a revert cannot silently undo the fix."""
    handled = handled_statuses()
    for status in ("blocked_by_live_gate", "settled", "already_merged"):
        assert status in handled, (
            f"'{status}' lost its explicit branch in aragora-merge-quorum.yml; it would "
            "again hard-fail a required check via the catch-all. See #9640."
        )


def test_merged_statuses_are_checked_before_the_dissent_guard() -> None:
    """An already-merged PR must short-circuit before any fail-closed guard.

    The dissent guard tests the ``unresolved_dissent`` *field*, not just the status, and
    the producer does not clear that field when it settles a merged PR. So if the
    settled/already_merged branch sits after it, a merged-and-settled PR carrying the
    flag hard-fails a required check and the pass branch is unreachable (#9650 openai [P2]).
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    merged_at = text.index('if status in ("settled", "already_merged"):')
    dissent_at = text.index('if status == "unresolved_dissent"')
    assert merged_at < dissent_at, (
        "the settled/already_merged branch must come BEFORE the unresolved_dissent "
        "guard; otherwise it is unreachable for a merged PR that still carries "
        "unresolved_dissent=True. See #9650."
    )


def test_blocked_by_live_gate_still_fails_closed() -> None:
    """The fix is diagnostic only — it must not turn an operator hold into a pass.

    ``blocked_by_live_gate`` is emitted when the model quorum IS satisfied but the live
    gate withheld authorization (e.g. an ``operator-review-required`` label). Exiting 0
    there would merge away a deliberate human hold.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index('if status == "blocked_by_live_gate":')
    branch = text[start : start + 1200]
    assert "fail(" in branch, (
        "the blocked_by_live_gate branch must still fail closed — it guards an "
        "operator hold; only the message should improve. See #9640."
    )
    assert "sys.exit(0)" not in branch.split("fail(")[0], (
        "blocked_by_live_gate must not exit 0 before failing; that would drop an "
        "'operator-review-required' hold. See #9640."
    )
