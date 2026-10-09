"""Benchmark corpus freshness invariants (revision 3+).

The rev-3 honesty pass (see ``docs/archive/benchmarks/corpus_honesty_audit_2026-04-17.md``)
changed how this test measures the corpus:

- ``verified`` entries must be CLOSED by a PR recorded on GitHub's
  ``closedByPullRequestsReferences`` edge. Entries CLOSED without such a link
  (manual stale closures, closures by unrelated PRs that merely mention the
  issue) are flagged.
- ``in_progress`` entries may be OPEN at authoring time, but they MUST have
  been dispatched at least once to the autonomous boss loop — i.e. there must
  be at least one row in ``.aragora/overnight/boss_metrics.jsonl`` with a
  matching ``issue_number`` AND a non-empty ``worker_outcome``.

Both halves of the invariant guard against the rev-2 failure mode: the old
freshness test required every corpus entry to be CLOSED, ``linkage_status ==
"verified"``, and ``truth_success == true``. That forced the corpus to contain
only already-solved issues, which is the exact artifact class the honesty audit
identified as hollow.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aragora.utils import git_paths

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = REPO_ROOT / "docs/benchmarks/corpus.json"
LATEST_TRUTH_PATH = (
    REPO_ROOT
    / "docs/status/generated/benchmark_truth_artifacts/tw-01-bounded-execution-v1/latest.json"
)
BOSS_METRICS_PATH = REPO_ROOT / ".aragora/overnight/boss_metrics.jsonl"

VALID_EXPECTED_STATUSES = {"verified", "in_progress"}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _corpus_issue_numbers(corpus: dict[str, Any]) -> list[int]:
    return sorted(int(issue["issue_id"]) for issue in corpus["issues"])


def _corpus_expected_status(corpus: dict[str, Any]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for item in corpus["issues"]:
        issue_id = int(item["issue_id"])
        status = str(item.get("expected_status") or "verified").strip().lower()
        if status not in VALID_EXPECTED_STATUSES:
            raise AssertionError(
                f"corpus issue #{issue_id} has unknown expected_status={status!r}; "
                f"must be one of {sorted(VALID_EXPECTED_STATUSES)}"
            )
        mapping[issue_id] = status
    return mapping


def load_dispatch_outcomes(metrics_rows: list[dict[str, Any]]) -> dict[int, list[str]]:
    """Aggregate boss_metrics rows by issue_number → list of worker_outcomes.

    Rows without an integer ``issue_number`` or without a non-empty
    ``worker_outcome`` are skipped. The returned outcomes preserve row order.
    """

    outcomes: dict[int, list[str]] = {}
    for row in metrics_rows:
        issue_number = row.get("issue_number")
        if not isinstance(issue_number, int) or issue_number <= 0:
            continue
        worker_outcome = row.get("worker_outcome")
        if worker_outcome is None:
            continue
        outcome_text = str(worker_outcome).strip()
        if not outcome_text:
            continue
        outcomes.setdefault(issue_number, []).append(outcome_text)
    return outcomes


def load_metrics_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def resolve_boss_metrics_path(path: Path = BOSS_METRICS_PATH) -> Path:
    """Resolve boss metrics through the shared git-common-dir repo root."""

    return git_paths.resolve_repo_fallback_path(path, repo_root=REPO_ROOT)


def validate_corpus_freshness(
    *,
    corpus: dict[str, Any],
    truth: dict[str, Any],
    dispatch_outcomes: dict[int, list[str]],
) -> list[str]:
    """Return a list of human-readable invariant violations (empty → healthy).

    This pure function is the unit-testable core of the freshness invariant.
    The top-level integration test feeds it real files; the branching unit
    tests below feed it in-memory fixtures.
    """

    failures: list[str] = []

    issue_numbers = _corpus_issue_numbers(corpus)
    expected_by_number = _corpus_expected_status(corpus)
    verified_numbers = sorted(n for n, s in expected_by_number.items() if s == "verified")
    in_progress_numbers = sorted(n for n, s in expected_by_number.items() if s == "in_progress")

    truth_corpus = truth.get("corpus") or {}
    if truth_corpus.get("path") != "docs/benchmarks/corpus.json":
        failures.append(
            f"truth.corpus.path != docs/benchmarks/corpus.json ({truth_corpus.get('path')!r})"
        )
    if truth_corpus.get("corpus_id") != corpus.get("corpus_id"):
        failures.append("truth.corpus.corpus_id mismatch with corpus.json")
    if truth_corpus.get("revision") != corpus.get("revision"):
        failures.append("truth.corpus.revision mismatch with corpus.json")
    if truth_corpus.get("issue_count") != len(issue_numbers):
        failures.append("truth.corpus.issue_count mismatch with corpus.issues length")
    if truth_corpus.get("membership_issue_numbers") != issue_numbers:
        failures.append("truth.corpus.membership_issue_numbers mismatch with corpus.issues ids")
    if truth_corpus.get("verified_expected_count") != len(verified_numbers):
        failures.append("truth.corpus.verified_expected_count mismatch")
    if truth_corpus.get("in_progress_expected_count") != len(in_progress_numbers):
        failures.append("truth.corpus.in_progress_expected_count mismatch")

    truth_records = {
        int(record["issue_number"]): record
        for record in truth.get("issues") or []
        if int(record.get("issue_number", 0) or 0) in issue_numbers
    }
    if sorted(truth_records) != issue_numbers:
        failures.append("truth.issues set does not match corpus membership")

    for issue_number, record in truth_records.items():
        if record.get("expected_status") != expected_by_number[issue_number]:
            failures.append(
                f"issue #{issue_number}: truth.expected_status "
                f"{record.get('expected_status')!r} != corpus "
                f"{expected_by_number[issue_number]!r}"
            )

    # Verified invariant: the issue MUST be CLOSED by a PR on
    # closedByPullRequestsReferences. A manual close with no linked PR, or a
    # textual reference from an unrelated PR, does not count.
    for issue_number in verified_numbers:
        record = truth_records.get(issue_number)
        if record is None:
            continue
        issue_state = str(record.get("issue_state", "")).upper()
        truth_state = record.get("truth_state")
        linkage_status = record.get("linkage_status")
        linkage_incomplete = record.get("linkage_verification_incomplete")
        truth_success = record.get("truth_success")
        stale = record.get("stale_corpus_issue") or record.get("stale_corpus_reason")

        if issue_state == "CLOSED" and (truth_state == "no_linked_pr" or stale):
            failures.append(
                f"verified issue #{issue_number}: CLOSED without a linked PR "
                f"(truth_state={truth_state!r}) — must be retired or replaced"
            )
        if linkage_incomplete or linkage_status != "verified":
            failures.append(
                f"verified issue #{issue_number}: linkage not verified "
                f"(status={linkage_status!r}, incomplete={linkage_incomplete!r})"
            )
        if not truth_success:
            failures.append(f"verified issue #{issue_number}: truth_success is False")

    # In-progress invariant: issue must be OPEN at authoring (or at least not
    # stuck-closed-without-PR) AND must have at least one recorded
    # worker_outcome in boss_metrics.jsonl.
    for issue_number in in_progress_numbers:
        record = truth_records.get(issue_number)
        if record is None:
            continue
        issue_state = str(record.get("issue_state", "")).upper()
        truth_state = record.get("truth_state")
        stale = record.get("stale_corpus_issue") or record.get("stale_corpus_reason")

        if issue_state == "CLOSED" and (truth_state == "no_linked_pr" or stale):
            failures.append(
                f"in_progress issue #{issue_number}: CLOSED without a verified "
                f"PR link — silent regression, must be promoted to verified or "
                f"removed"
            )

        outcomes = dispatch_outcomes.get(issue_number) or []
        if not outcomes:
            failures.append(
                f"in_progress issue #{issue_number}: has no recorded worker_outcome "
                f"in .aragora/overnight/boss_metrics.jsonl — per the rev-3 honesty "
                f"invariant, every in_progress entry must have been dispatched at "
                f"least once to the autonomous boss loop before inclusion"
            )

    # truth_success_rate_verified must exist and match the verified subset.
    primary = truth.get("primary_metrics") or {}
    if "truth_success_rate_verified" not in primary:
        failures.append("primary_metrics.truth_success_rate_verified missing")
    elif verified_numbers:
        verified_records = [truth_records[n] for n in verified_numbers if n in truth_records]
        computed = sum(1 for record in verified_records if record.get("truth_success")) / len(
            verified_numbers
        )
        if abs(primary["truth_success_rate_verified"] - round(computed, 4)) >= 1e-6:
            failures.append(
                f"primary_metrics.truth_success_rate_verified "
                f"({primary['truth_success_rate_verified']!r}) does not match "
                f"verified subset ({round(computed, 4)!r})"
            )

    return failures


# ---------------------------------------------------------------------------
# Integration test: the actual rev-3 corpus must be fresh and honest.
# ---------------------------------------------------------------------------


def test_current_benchmark_corpus_has_fresh_verifiable_truth() -> None:
    corpus = _read_json(CORPUS_PATH)
    truth = _read_json(LATEST_TRUTH_PATH)
    dispatch_outcomes = load_dispatch_outcomes(load_metrics_rows(resolve_boss_metrics_path()))

    failures = validate_corpus_freshness(
        corpus=corpus,
        truth=truth,
        dispatch_outcomes=dispatch_outcomes,
    )

    assert failures == [], "corpus freshness violations:\n" + "\n".join(
        f"  - {f}" for f in failures
    )


# ---------------------------------------------------------------------------
# Unit tests: the four scenarios called out in the 2026-04-17 audit.
# ---------------------------------------------------------------------------


def _make_corpus(entries: list[dict[str, Any]], *, revision: int = 3) -> dict[str, Any]:
    return {
        "corpus_id": "tw-01-bounded-execution-v1",
        "revision": revision,
        "recorded_on": "2026-04-17",
        "success_contract": "mergeable_pr_or_merged_pr",
        "issues": entries,
    }


def _make_truth(
    *,
    corpus: dict[str, Any],
    issue_records: list[dict[str, Any]],
    verified_success_count: int | None = None,
) -> dict[str, Any]:
    issue_numbers = _corpus_issue_numbers(corpus)
    expected_by_number = _corpus_expected_status(corpus)
    verified_numbers = [n for n, s in expected_by_number.items() if s == "verified"]
    in_progress_numbers = [n for n, s in expected_by_number.items() if s == "in_progress"]
    if verified_success_count is None:
        verified_success_count = sum(
            1
            for rec in issue_records
            if int(rec["issue_number"]) in verified_numbers and rec.get("truth_success")
        )
    truth_success_rate_verified = (
        round(verified_success_count / len(verified_numbers), 4) if verified_numbers else 0.0
    )
    return {
        "corpus": {
            "path": "docs/benchmarks/corpus.json",
            "corpus_id": corpus["corpus_id"],
            "revision": corpus["revision"],
            "issue_count": len(issue_numbers),
            "membership_issue_numbers": issue_numbers,
            "verified_expected_count": len(verified_numbers),
            "in_progress_expected_count": len(in_progress_numbers),
        },
        "coverage": {"status": "complete", "missing_issue_numbers": []},
        "corpus_freshness": {
            "status": "fresh",
            "stale_closed_issue_count": 0,
            "stale_closed_issue_numbers": [],
            "stale_closed_issues": [],
            "linkage_error_count": 0,
            "linkage_errors": [],
        },
        "primary_metrics": {
            "truth_success_rate": 0.0,
            "truth_success_rate_verified": truth_success_rate_verified,
            "no_rescue_truth_success_rate": 0.0,
            "merged_only_rate": 0.0,
        },
        "issues": issue_records,
    }


def test_in_progress_entry_with_dispatch_history_passes() -> None:
    # Scenario (a): open in_progress entry with at least one recorded
    # worker_outcome in boss_metrics.jsonl.
    corpus = _make_corpus(
        [
            {
                "issue_id": 5903,
                "title": "test authoring task",
                "expected_status": "in_progress",
            }
        ]
    )
    truth = _make_truth(
        corpus=corpus,
        issue_records=[
            {
                "issue_number": 5903,
                "expected_status": "in_progress",
                "issue_state": "OPEN",
                "truth_state": "in_progress_open",
                "truth_success": False,
                "linkage_status": "verified",
                "linkage_verification_incomplete": False,
                "stale_corpus_issue": False,
                "stale_corpus_reason": None,
            }
        ],
    )
    dispatch = {5903: ["blocked", "blocked"]}

    failures = validate_corpus_freshness(corpus=corpus, truth=truth, dispatch_outcomes=dispatch)

    assert failures == []


def test_in_progress_entry_without_dispatch_fails() -> None:
    # Scenario (b): open in_progress entry that has never been dispatched.
    # This is the rev-3 invariant's core check — without it, the corpus can be
    # stuffed with aspirational open issues that autonomy has never actually
    # attempted.
    corpus = _make_corpus(
        [
            {
                "issue_id": 5903,
                "title": "test authoring task",
                "expected_status": "in_progress",
            }
        ]
    )
    truth = _make_truth(
        corpus=corpus,
        issue_records=[
            {
                "issue_number": 5903,
                "expected_status": "in_progress",
                "issue_state": "OPEN",
                "truth_state": "not_attempted",
                "truth_success": False,
                "linkage_status": "verified",
                "linkage_verification_incomplete": False,
                "stale_corpus_issue": False,
                "stale_corpus_reason": None,
            }
        ],
    )
    dispatch: dict[int, list[str]] = {}

    failures = validate_corpus_freshness(corpus=corpus, truth=truth, dispatch_outcomes=dispatch)

    assert any("has no recorded worker_outcome" in f for f in failures), failures


def test_verified_entry_closed_by_linked_pr_passes() -> None:
    # Scenario (c): verified entry closed via a linked closedByPullRequestsReferences
    # edge; truth_success resolves to True.
    corpus = _make_corpus(
        [
            {
                "issue_id": 1064,
                "title": "dependency bump",
                "expected_status": "verified",
            }
        ]
    )
    truth = _make_truth(
        corpus=corpus,
        issue_records=[
            {
                "issue_number": 1064,
                "expected_status": "verified",
                "issue_state": "CLOSED",
                "truth_state": "merged_pr",
                "truth_success": True,
                "linkage_status": "verified",
                "linkage_verification_incomplete": False,
                "stale_corpus_issue": False,
                "stale_corpus_reason": None,
            }
        ],
    )

    failures = validate_corpus_freshness(corpus=corpus, truth=truth, dispatch_outcomes={})

    assert failures == []


def test_verified_entry_closed_manually_without_linked_pr_fails() -> None:
    # Scenario (d): verified entry closed manually/stale with no PR on the
    # closedByPullRequestsReferences edge. This is exactly the #873 pattern in
    # the rev-2 corpus that the honesty audit flagged.
    corpus = _make_corpus(
        [
            {
                "issue_id": 873,
                "title": "closed as stale",
                "expected_status": "verified",
            }
        ]
    )
    truth = _make_truth(
        corpus=corpus,
        issue_records=[
            {
                "issue_number": 873,
                "expected_status": "verified",
                "issue_state": "CLOSED",
                "truth_state": "no_linked_pr",
                "truth_success": False,
                "linkage_status": "verified",
                "linkage_verification_incomplete": False,
                "stale_corpus_issue": True,
                "stale_corpus_reason": "closed_without_linked_pr",
            }
        ],
        verified_success_count=0,
    )

    failures = validate_corpus_freshness(corpus=corpus, truth=truth, dispatch_outcomes={})

    assert any("CLOSED without a linked PR" in f for f in failures), failures
    assert any("truth_success is False" in f for f in failures), failures


def test_dispatch_outcomes_ignores_rows_without_worker_outcome() -> None:
    # Regression guard: worker_outcome=None or "" rows should not count as
    # a dispatch. Per the audit, "dispatched at least once" means a recorded
    # outcome, not a row that was dropped mid-pipeline.
    rows = [
        {"issue_number": 5903, "worker_outcome": "blocked"},
        {"issue_number": 5903, "worker_outcome": None},
        {"issue_number": 5903, "worker_outcome": "  "},
        {"issue_number": 5903, "worker_outcome": "pr_adopted"},
        {"issue_number": None, "worker_outcome": "blocked"},
    ]

    outcomes = load_dispatch_outcomes(rows)

    assert outcomes == {5903: ["blocked", "pr_adopted"]}


def test_resolve_boss_metrics_path_falls_back_to_git_common_root(
    tmp_path: Path, monkeypatch
) -> None:
    worktree_root = tmp_path / "worktree-root"
    shared_root = tmp_path / "shared-root"
    metrics_file = shared_root / ".aragora" / "overnight" / "boss_metrics.jsonl"
    metrics_file.parent.mkdir(parents=True)
    metrics_file.write_text("", encoding="utf-8")

    monkeypatch.setattr("tests.benchmarks.test_corpus_freshness.REPO_ROOT", worktree_root)
    monkeypatch.setattr(git_paths, "git_common_repo_root", lambda _repo_root: shared_root)

    resolved = resolve_boss_metrics_path(
        worktree_root / ".aragora" / "overnight" / "boss_metrics.jsonl"
    )

    assert resolved == metrics_file.resolve()
