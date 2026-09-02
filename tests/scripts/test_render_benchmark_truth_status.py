from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_scripts_dir = str(_REPO_ROOT / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import render_benchmark_truth_status as mod  # noqa: E402


def test_open_pr_help_warns_no_draft_is_only_for_live_review_ready_branches() -> None:
    result = subprocess.run(
        ["bash", str(_REPO_ROOT / "scripts" / "open_pr.sh"), "--help"],
        cwd=_REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "Pass --no-draft only when the branch is ready for live review." in result.stdout


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _truth_payload(
    *, revision: int, generated_at: str = "2026-04-14T20:00:00Z"
) -> dict[str, object]:
    return {
        "generated_at": generated_at,
        "corpus": {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": revision,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issue_count": 1,
        },
    }


def _scorecard_payload(
    *, revision: int, generated_at: str = "2026-04-14T20:05:00Z"
) -> dict[str, object]:
    return {
        "generated_at": generated_at,
        "corpus": {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": revision,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issue_count": 1,
        },
        "coverage": {
            "status": "incomplete",
            "attempted_issue_count": 0,
            "missing_issue_numbers": [1064],
        },
        "truth_metrics": {
            "truth_success_rate": 0.0,
            "truth_success_rate_verified": 0.0,
            "no_rescue_truth_success_rate": 0.0,
            "merged_only_rate": 0.0,
        },
        "proxy_metrics": {
            "no_rescue_success_rate": 0.0,
            "unique_issues_attempted": 0,
            "unique_issues_succeeded": 0,
            "unique_issues_failed": 0,
            "unique_issues_neutral": 0,
            "total_ticks": 0,
            "neutral_classes": {},
        },
        "failure_class_distribution": {"blocked_auth_failure": 1},
        "rescue_counts_by_type": {},
    }


def test_render_status_markdown_includes_metrics_and_paths(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 1,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )
    markdown = mod.render_status_markdown(
        corpus_path=corpus_path,
        truth_path=latest_paths["truth_corpus_latest"],
        scorecard_path=latest_paths["scorecard_corpus_latest"],
        latest_paths=latest_paths,
        truth_payload={
            "generated_at": "2026-04-14T19:00:00Z",
            "corpus": {
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 1,
                "recorded_on": "2026-04-14",
                "success_contract": "mergeable_pr_or_merged_pr",
                "issue_count": 1,
                "verified_expected_count": 1,
                "in_progress_expected_count": 0,
            },
        },
        scorecard_payload={
            "generated_at": "2026-04-14T19:05:00Z",
            "corpus": {
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 1,
                "recorded_on": "2026-04-14",
                "success_contract": "mergeable_pr_or_merged_pr",
                "issue_count": 1,
                "verified_expected_count": 1,
                "in_progress_expected_count": 0,
            },
            "coverage": {
                "status": "complete",
                "attempted_issue_count": 1,
                "missing_issue_numbers": [],
            },
            "truth_metrics": {
                "truth_success_rate": 1.0,
                "truth_success_rate_verified": 1.0,
                "no_rescue_truth_success_rate": 1.0,
                "merged_only_rate": 0.0,
            },
            "proxy_metrics": {
                "no_rescue_success_rate": 1.0,
                "unique_issues_attempted": 1,
                "unique_issues_succeeded": 1,
                "unique_issues_failed": 0,
                "unique_issues_neutral": 0,
                "total_ticks": 1,
                "neutral_classes": {},
            },
            "failure_class_distribution": {},
            "rescue_counts_by_type": {},
            "previous_artifact": {
                "path": "docs/status/generated/benchmark_scorecards/tw-01-bounded-execution-v1/rev-1/scorecard-20260407T190500Z.json",
                "generated_at": "2026-04-07T19:05:00Z",
            },
            "deltas": {
                "truth_success_rate": 0.25,
                "proxy_no_rescue_success_rate": 0.5,
            },
        },
    )

    assert "B0 Benchmark Truth Status" in markdown
    assert f"`{latest_paths['truth_corpus_latest']}`" in markdown
    assert f"`{latest_paths['scorecard_corpus_latest']}`" in markdown
    assert "- Corpus-scoped truth pointer:" in markdown
    assert "- Corpus-scoped scorecard pointer:" in markdown
    assert "- Latest truth artifact:" not in markdown
    assert "- Latest scorecard:" not in markdown
    assert "Verified expected issues: `1`" in markdown
    assert "In-progress expected issues: `0`" in markdown
    assert "| Verified truth success rate (primary) | 100.0% |" in markdown
    assert "| Full-corpus truth success rate (legacy/context) | 100.0% |" in markdown
    assert "## Proxy Metrics" in markdown
    assert "| Proxy no-rescue success rate | 100.0% |" in markdown
    assert "## Deltas" in markdown
    assert (
        "Full-corpus truth success rate (legacy/context) (`truth_success_rate`): 0.2500" in markdown
    )


def test_render_status_markdown_warns_for_runner_local_metrics(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 7,
            "issues": [{"issue_id": 5754, "title": "Issue A"}],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )
    truth_payload = _truth_payload(revision=7)
    scorecard_payload = _scorecard_payload(revision=7)
    scorecard_payload["metrics_provenance"] = {
        "capture_scope": "runner_local",
        "content_sha256": None,
        "path": ".aragora/overnight/boss_metrics.jsonl",
        "repository_head_sha": "c1868664248be7f533cabb441a8b8159dc47b908",
        "repository_reproducible": False,
        "repository_tracked": False,
        "source_run_url": "https://github.com/synaptent/aragora/actions/runs/33314070684",
    }

    markdown = mod.render_status_markdown(
        corpus_path=corpus_path,
        truth_path=latest_paths["truth_corpus_latest"],
        scorecard_path=latest_paths["scorecard_corpus_latest"],
        truth_payload=truth_payload,
        scorecard_payload=scorecard_payload,
        latest_paths=latest_paths,
    )

    assert "## Evidence Provenance" in markdown
    assert "- Capture scope: `runner_local`" in markdown
    assert "- Reproducible from this repository: `false`" in markdown
    assert "c1868664248be7f533cabb441a8b8159dc47b908" in markdown
    assert "runner-local metrics window that is not tracked" in markdown
    assert "actions/runs/33314070684" in markdown


def test_load_corpus_rejects_blank_corpus_id(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": " ",
            "revision": 1,
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )

    with pytest.raises(ValueError, match="non-empty corpus_id"):
        mod.load_corpus(corpus_path)


@pytest.mark.parametrize("revision", [0, -1, True, "not-a-number", None])
def test_load_corpus_rejects_invalid_revision(tmp_path: Path, revision: object) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": revision,
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )

    with pytest.raises(ValueError, match="positive integer revision"):
        mod.load_corpus(corpus_path)


def test_render_status_markdown_headlines_verified_rate_and_in_flight_metrics(
    tmp_path: Path,
) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 3,
            "recorded_on": "2026-04-17",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 1001, "title": "Verified A", "expected_status": "verified"},
                {"issue_id": 1002, "title": "Verified B", "expected_status": "verified"},
                {
                    "issue_id": 5814,
                    "title": "In-progress liveness coverage",
                    "expected_status": "in_progress",
                },
            ],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )
    corpus = {
        "corpus_id": "tw-01-bounded-execution-v1",
        "revision": 3,
        "recorded_on": "2026-04-17",
        "success_contract": "mergeable_pr_or_merged_pr",
        "issue_count": 3,
        "verified_expected_count": 2,
        "in_progress_expected_count": 1,
    }
    markdown = mod.render_status_markdown(
        corpus_path=corpus_path,
        truth_path=latest_paths["truth_corpus_latest"],
        scorecard_path=latest_paths["scorecard_corpus_latest"],
        latest_paths=latest_paths,
        truth_payload={
            "generated_at": "2026-04-17T06:00:00Z",
            "corpus": corpus,
            "primary_metrics": {
                "truth_success_rate": 0.667,
                "truth_success_rate_verified": 1.0,
                "no_rescue_truth_success_rate": 0.667,
                "merged_only_rate": 0.667,
            },
            "in_flight_metrics": {
                "in_progress_expected_count": 1,
                "in_progress_attempted_count": 0,
                "in_progress_success_count": 0,
                "in_progress_graduation_rate": 0.0,
                "in_progress_issue_numbers": [5814],
            },
            "issues": [
                {
                    "expected_status": "in_progress",
                    "issue_number": 5814,
                    "issue_state": "OPEN",
                },
                {
                    "expected_status": "in_progress",
                    "issue_number": 5815,
                    "issue_state": "CLOSED",
                },
                {
                    "expected_status": "verified",
                    "issue_number": 5800,
                    "issue_state": "CLOSED",
                },
            ],
        },
        scorecard_payload={
            "generated_at": "2026-04-17T06:05:00Z",
            "corpus": corpus,
            "coverage": {
                "status": "complete",
                "attempted_issue_count": 2,
                "missing_issue_numbers": [],
            },
            "truth_metrics": {
                "truth_success_rate": 0.667,
                "truth_success_rate_verified": 1.0,
                "no_rescue_truth_success_rate": 0.667,
                "merged_only_rate": 0.667,
            },
            "proxy_metrics": {
                "no_rescue_success_rate": 0.0,
                "unique_issues_attempted": 2,
                "unique_issues_succeeded": 0,
                "unique_issues_failed": 0,
                "unique_issues_neutral": 2,
                "total_ticks": 2,
                "neutral_classes": {"issue_already_resolved": 2},
            },
        },
    )

    assert "Revision: `3`" in markdown
    assert "Verified expected issues: `2`" in markdown
    assert "In-progress expected issues: `1`" in markdown
    assert "| Verified truth success rate (primary) | 100.0% |" in markdown
    assert "| Full-corpus truth success rate (legacy/context) | 66.7% |" in markdown
    assert "## In-Flight Graduation Metrics" in markdown
    assert "| In-progress expected issues | 1 |" in markdown
    assert "| In-progress attempted issues | 0 |" in markdown
    assert "| In-progress successful issues | 0 |" in markdown
    assert "| In-progress graduation rate | 0.0% |" in markdown
    assert "| Expected in-progress issue numbers | `#5814` |" in markdown
    assert "| Live-open expected issue numbers | `#5814` |" in markdown
    assert "| Live-closed expected issue numbers | `#5815` |" in markdown


def test_render_status_markdown_surfaces_proxy_neutral_issue_classes(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 1,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )
    markdown = mod.render_status_markdown(
        corpus_path=corpus_path,
        truth_path=latest_paths["truth_corpus_latest"],
        scorecard_path=latest_paths["scorecard_corpus_latest"],
        latest_paths=latest_paths,
        truth_payload=_truth_payload(revision=1),
        scorecard_payload={
            **_scorecard_payload(revision=1),
            "proxy_metrics": {
                "no_rescue_success_rate": 0.0,
                "unique_issues_attempted": 1,
                "unique_issues_succeeded": 0,
                "unique_issues_failed": 0,
                "unique_issues_neutral": 1,
                "total_ticks": 1,
                "neutral_classes": {"issue_already_resolved": 1},
            },
        },
    )

    assert "| Unique issues neutral | 1 |" in markdown
    assert "Proxy note: neutral issue outcomes" in markdown
    assert "## Proxy Neutral Class Distribution" in markdown
    assert "`issue_already_resolved`: 1" in markdown


def test_render_status_markdown_flags_exhausted_corpus_window(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 6,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )
    markdown = mod.render_status_markdown(
        corpus_path=corpus_path,
        truth_path=latest_paths["truth_corpus_latest"],
        scorecard_path=latest_paths["scorecard_corpus_latest"],
        latest_paths=latest_paths,
        truth_payload=_truth_payload(revision=6),
        scorecard_payload={
            **_scorecard_payload(revision=6),
            "proxy_metrics": {
                "no_rescue_success_rate": 0.0,
                "unique_issues_attempted": 13,
                "unique_issues_succeeded": 0,
                "unique_issues_failed": 0,
                "unique_issues_neutral": 13,
                "total_ticks": 13,
                "neutral_classes": {"issue_already_resolved": 13},
            },
        },
    )

    assert "Corpus exhaustion note:" in markdown
    assert "not fresh autonomy proof" in markdown
    assert "All `13`/`13` proxy corpus rows" in markdown
    assert "corpus revision `6` is exhausted" in markdown
    # The note must sit directly under the headline table, before in-flight metrics.
    assert markdown.index("Corpus exhaustion note:") < markdown.index("## Proxy Metrics")


def test_render_status_markdown_uses_generic_note_for_mixed_neutral_classes(
    tmp_path: Path,
) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 6,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )
    markdown = mod.render_status_markdown(
        corpus_path=corpus_path,
        truth_path=latest_paths["truth_corpus_latest"],
        scorecard_path=latest_paths["scorecard_corpus_latest"],
        latest_paths=latest_paths,
        truth_payload=_truth_payload(revision=6),
        scorecard_payload={
            **_scorecard_payload(revision=6),
            "proxy_metrics": {
                "no_rescue_success_rate": 0.0,
                "unique_issues_attempted": 4,
                "unique_issues_succeeded": 0,
                "unique_issues_failed": 0,
                "unique_issues_neutral": 4,
                "total_ticks": 4,
                "neutral_classes": {
                    "issue_already_resolved": 2,
                    "blocked_config": 2,
                },
            },
        },
    )

    # An all-neutral window that is not purely issue_already_resolved must not
    # claim corpus exhaustion — only that no fresh evidence was produced.
    assert "Corpus exhaustion note:" not in markdown
    assert "Freshness note:" in markdown
    assert "no fresh execution evidence" in markdown
    assert "not fresh autonomy proof" in markdown


def test_render_status_markdown_omits_exhaustion_note_on_fresh_successes(
    tmp_path: Path,
) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 6,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )
    markdown = mod.render_status_markdown(
        corpus_path=corpus_path,
        truth_path=latest_paths["truth_corpus_latest"],
        scorecard_path=latest_paths["scorecard_corpus_latest"],
        latest_paths=latest_paths,
        truth_payload=_truth_payload(revision=6),
        scorecard_payload={
            **_scorecard_payload(revision=6),
            "proxy_metrics": {
                "no_rescue_success_rate": 0.5,
                "unique_issues_attempted": 13,
                "unique_issues_succeeded": 2,
                "unique_issues_failed": 0,
                "unique_issues_neutral": 11,
                "total_ticks": 13,
                "neutral_classes": {"issue_already_resolved": 11},
            },
        },
    )

    assert "Corpus exhaustion note:" not in markdown
    assert "Freshness note:" not in markdown


def test_render_status_markdown_backfills_legacy_proxy_neutral_fields(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 1,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )
    markdown = mod.render_status_markdown(
        corpus_path=corpus_path,
        truth_path=latest_paths["truth_corpus_latest"],
        scorecard_path=latest_paths["scorecard_corpus_latest"],
        latest_paths=latest_paths,
        truth_payload=_truth_payload(revision=1),
        scorecard_payload={
            **_scorecard_payload(revision=1),
            "proxy_metrics": {
                "no_rescue_success_rate": 0.0,
                "unique_issues_attempted": 5,
                "unique_issues_succeeded": 0,
                "unique_issues_failed": 1,
                "total_ticks": 6,
                "terminal_class_distribution": {
                    "blocked_auth_failure": 2,
                    "issue_already_resolved": 4,
                },
            },
        },
    )

    assert "| Unique issues neutral | 4 |" in markdown
    assert "## Proxy Neutral Class Distribution" in markdown
    assert "`issue_already_resolved`: 4" in markdown


def test_render_status_markdown_rejects_proxy_neutral_count_mismatch(
    tmp_path: Path,
) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 1,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )

    with pytest.raises(ValueError, match="unique_issues_neutral"):
        mod.render_status_markdown(
            corpus_path=corpus_path,
            truth_path=latest_paths["truth_corpus_latest"],
            scorecard_path=latest_paths["scorecard_corpus_latest"],
            latest_paths=latest_paths,
            truth_payload=_truth_payload(revision=1),
            scorecard_payload={
                **_scorecard_payload(revision=1),
                "proxy_metrics": {
                    "no_rescue_success_rate": 0.0,
                    "unique_issues_attempted": 5,
                    "unique_issues_succeeded": 1,
                    "unique_issues_failed": 1,
                    "unique_issues_neutral": 9,
                    "total_ticks": 5,
                },
            },
        )


def test_render_status_markdown_rejects_proxy_success_failure_overflow(
    tmp_path: Path,
) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 1,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )

    with pytest.raises(ValueError, match="exceeds unique_issues_attempted"):
        mod.render_status_markdown(
            corpus_path=corpus_path,
            truth_path=latest_paths["truth_corpus_latest"],
            scorecard_path=latest_paths["scorecard_corpus_latest"],
            latest_paths=latest_paths,
            truth_payload=_truth_payload(revision=1),
            scorecard_payload={
                **_scorecard_payload(revision=1),
                "proxy_metrics": {
                    "no_rescue_success_rate": 0.0,
                    "unique_issues_attempted": 1,
                    "unique_issues_succeeded": 1,
                    "unique_issues_failed": 1,
                    "total_ticks": 2,
                },
            },
        )


def test_render_status_markdown_surfaces_stale_closed_corpus_issues(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 1,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1733, "title": "Issue A"}],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )
    markdown = mod.render_status_markdown(
        corpus_path=corpus_path,
        truth_path=latest_paths["truth_corpus_latest"],
        scorecard_path=latest_paths["scorecard_corpus_latest"],
        latest_paths=latest_paths,
        truth_payload={
            **_truth_payload(revision=1),
            "corpus_freshness": {
                "status": "stale_closed_issues_detected",
                "stale_closed_issue_count": 1,
                "stale_closed_issue_numbers": [1733],
                "stale_closed_issues": [
                    {
                        "issue_number": 1733,
                        "issue_title": "Detached worker cleanup",
                        "issue_closed_at": "2026-03-31T23:45:29Z",
                        "issue_state_reason": "COMPLETED",
                        "truth_state": "no_linked_pr",
                    }
                ],
            },
        },
        scorecard_payload=_scorecard_payload(revision=1),
    )

    assert "## Corpus Freshness Alerts" in markdown
    assert "Closed issues without linked PR truth" in markdown
    assert "`#1733` `Detached worker cleanup`" in markdown
    assert "truth `no_linked_pr`" in markdown


def test_render_status_markdown_surfaces_linkage_verification_warnings(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 1,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1733, "title": "Issue A"}],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )
    markdown = mod.render_status_markdown(
        corpus_path=corpus_path,
        truth_path=latest_paths["truth_corpus_latest"],
        scorecard_path=latest_paths["scorecard_corpus_latest"],
        latest_paths=latest_paths,
        truth_payload={
            **_truth_payload(revision=1),
            "corpus_freshness": {
                "status": "linkage_verification_incomplete",
                "stale_closed_issue_count": 0,
                "stale_closed_issue_numbers": [],
                "stale_closed_issues": [],
                "linkage_error_count": 1,
                "linkage_errors": [
                    {
                        "issue_number": 1733,
                        "issue_title": "Detached worker cleanup",
                        "issue_closed_at": "2026-03-31T23:45:29Z",
                        "issue_state_reason": "COMPLETED",
                        "truth_state": "no_linked_pr",
                        "linkage_status": "cross_reference_lookup_failed",
                        "linkage_error": "error connecting to api.github.com",
                    }
                ],
            },
        },
        scorecard_payload=_scorecard_payload(revision=1),
    )

    assert "## Corpus Freshness Verification Warnings" in markdown
    assert "excluded from stale-corpus alerts" in markdown
    assert "linkage `cross_reference_lookup_failed`" in markdown
    assert "error `error connecting to api.github.com`" in markdown
    assert "## Corpus Freshness Alerts" not in markdown


def test_render_status_markdown_surfaces_closure_hygiene_alerts(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 1,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 5903, "title": "Issue A"}],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )
    markdown = mod.render_status_markdown(
        corpus_path=corpus_path,
        truth_path=latest_paths["truth_corpus_latest"],
        scorecard_path=latest_paths["scorecard_corpus_latest"],
        latest_paths=latest_paths,
        truth_payload={
            **_truth_payload(revision=1),
            "corpus_freshness": {
                "status": "closure_hygiene_drift_detected",
                "stale_closed_issue_count": 0,
                "stale_closed_issue_numbers": [],
                "stale_closed_issues": [],
                "closure_hygiene_issue_count": 1,
                "closure_hygiene_issue_numbers": [5903],
                "closure_hygiene_issues": [
                    {
                        "issue_number": 5903,
                        "issue_title": "Roadmap-priority tests",
                        "issue_state": "OPEN",
                        "issue_state_reason": "",
                        "truth_state": "no_linked_pr",
                    }
                ],
                "linkage_error_count": 0,
                "linkage_errors": [],
            },
        },
        scorecard_payload=_scorecard_payload(revision=1),
    )

    assert "## Closure Hygiene Alerts" in markdown
    assert "deliverable or PR-shaped signals" in markdown
    assert "`#5903` `Roadmap-priority tests`" in markdown
    assert "state `OPEN`" in markdown
    assert "truth `no_linked_pr`" in markdown
    assert "## Corpus Freshness Alerts" not in markdown


def test_render_status_markdown_surfaces_corpus_freshness_follow_up(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 1,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1733, "title": "Issue A"}],
        },
    )
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=tmp_path / "truth",
        scorecard_root=tmp_path / "scorecards",
    )
    markdown = mod.render_status_markdown(
        corpus_path=corpus_path,
        truth_path=latest_paths["truth_corpus_latest"],
        scorecard_path=latest_paths["scorecard_corpus_latest"],
        latest_paths=latest_paths,
        truth_payload={
            **_truth_payload(revision=1),
            "corpus_freshness": {
                "status": "stale_closed_issues_detected",
                "stale_closed_issue_count": 1,
                "stale_closed_issue_numbers": [1733],
                "stale_closed_issues": [
                    {
                        "issue_number": 1733,
                        "issue_title": "Detached worker cleanup",
                        "issue_closed_at": "2026-03-31T23:45:29Z",
                        "issue_state_reason": "COMPLETED",
                        "truth_state": "no_linked_pr",
                    }
                ],
                "issue_map_path": "docs/benchmarks/benchmark_corpus_freshness.json",
                "linked_issues": [
                    {
                        "target": "#6001",
                        "title": "[TW-02] Restock stale issues in tw-01-bounded-execution-v1 rev-1",
                        "url": "https://github.com/synaptent/aragora/issues/6001",
                    }
                ],
                "issue_linkage_results": [
                    {
                        "action": "linked_existing_issue",
                        "target": "#6001",
                        "url": "https://github.com/synaptent/aragora/issues/6001",
                    }
                ],
                "issue_drafts": [],
            },
        },
        scorecard_payload=_scorecard_payload(revision=1),
    )

    assert "## Corpus Freshness Follow-Up" in markdown
    assert "Freshness map: `docs/benchmarks/benchmark_corpus_freshness.json`" in markdown
    assert "[#6001](https://github.com/synaptent/aragora/issues/6001)" in markdown
    assert (
        "`linked_existing_issue` -> [#6001](https://github.com/synaptent/aragora/issues/6001)"
        in markdown
    )


def test_main_writes_markdown_from_latest_paths(tmp_path: Path, capsys) -> None:
    corpus_path = _write_json(
        tmp_path / "docs" / "benchmarks" / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 2,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )
    truth_root = tmp_path / "docs" / "status" / "generated" / "benchmark_truth_artifacts"
    scorecard_root = tmp_path / "docs" / "status" / "generated" / "benchmark_scorecards"
    _write_json(
        truth_root / "tw-01-bounded-execution-v1" / "latest.json",
        _truth_payload(revision=2),
    )
    _write_json(
        truth_root / "tw-01-bounded-execution-v1" / "rev-2" / "latest.json",
        _truth_payload(revision=2),
    )
    _write_json(
        scorecard_root / "tw-01-bounded-execution-v1" / "latest.json",
        _scorecard_payload(revision=2),
    )
    _write_json(
        scorecard_root / "tw-01-bounded-execution-v1" / "rev-2" / "latest.json",
        _scorecard_payload(revision=2),
    )
    output_path = tmp_path / "docs" / "status" / "B0_BENCHMARK_TRUTH_STATUS.md"

    exit_code = mod.main(
        [
            "--corpus",
            str(corpus_path),
            "--truth-root",
            str(truth_root),
            "--scorecard-root",
            str(scorecard_root),
            "--output",
            str(output_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == str(output_path)
    content = output_path.read_text(encoding="utf-8")
    assert "Coverage status: `incomplete`" in content
    assert "Missing corpus issues: `1064`" in content
    assert "`blocked_auth_failure`: 1" in content


def test_main_requires_revision_scoped_latest_paths(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "docs" / "benchmarks" / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 2,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )
    truth_root = tmp_path / "docs" / "status" / "generated" / "benchmark_truth_artifacts"
    scorecard_root = tmp_path / "docs" / "status" / "generated" / "benchmark_scorecards"
    _write_json(
        truth_root / "tw-01-bounded-execution-v1" / "latest.json", _truth_payload(revision=2)
    )
    _write_json(
        scorecard_root / "tw-01-bounded-execution-v1" / "latest.json",
        _scorecard_payload(revision=2),
    )
    output_path = tmp_path / "docs" / "status" / "B0_BENCHMARK_TRUTH_STATUS.md"

    with pytest.raises(SystemExit, match="truth artifact revision latest.json not found"):
        mod.main(
            [
                "--corpus",
                str(corpus_path),
                "--truth-root",
                str(truth_root),
                "--scorecard-root",
                str(scorecard_root),
                "--output",
                str(output_path),
            ]
        )

    assert not output_path.exists()


def test_main_rejects_stale_corpus_latest_payload_revision(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "docs" / "benchmarks" / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 2,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )
    truth_root = tmp_path / "docs" / "status" / "generated" / "benchmark_truth_artifacts"
    scorecard_root = tmp_path / "docs" / "status" / "generated" / "benchmark_scorecards"
    _write_json(
        truth_root / "tw-01-bounded-execution-v1" / "latest.json", _truth_payload(revision=1)
    )
    _write_json(
        truth_root / "tw-01-bounded-execution-v1" / "rev-2" / "latest.json",
        _truth_payload(revision=2),
    )
    _write_json(
        scorecard_root / "tw-01-bounded-execution-v1" / "latest.json",
        _scorecard_payload(revision=1),
    )
    _write_json(
        scorecard_root / "tw-01-bounded-execution-v1" / "rev-2" / "latest.json",
        _scorecard_payload(revision=2),
    )
    output_path = tmp_path / "docs" / "status" / "B0_BENCHMARK_TRUTH_STATUS.md"

    with pytest.raises(SystemExit, match="truth artifact latest.json revision mismatch"):
        mod.main(
            [
                "--corpus",
                str(corpus_path),
                "--truth-root",
                str(truth_root),
                "--scorecard-root",
                str(scorecard_root),
                "--output",
                str(output_path),
            ]
        )

    assert not output_path.exists()


def test_main_rejects_truth_latest_pointer_payload_divergence(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "docs" / "benchmarks" / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 2,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )
    truth_root = tmp_path / "docs" / "status" / "generated" / "benchmark_truth_artifacts"
    scorecard_root = tmp_path / "docs" / "status" / "generated" / "benchmark_scorecards"
    _write_json(
        truth_root / "tw-01-bounded-execution-v1" / "latest.json",
        _truth_payload(revision=2, generated_at="2026-04-14T20:00:00Z"),
    )
    _write_json(
        truth_root / "tw-01-bounded-execution-v1" / "rev-2" / "latest.json",
        _truth_payload(revision=2, generated_at="2026-04-14T20:30:00Z"),
    )
    _write_json(
        scorecard_root / "tw-01-bounded-execution-v1" / "latest.json",
        _scorecard_payload(revision=2),
    )
    _write_json(
        scorecard_root / "tw-01-bounded-execution-v1" / "rev-2" / "latest.json",
        _scorecard_payload(revision=2),
    )
    output_path = tmp_path / "docs" / "status" / "B0_BENCHMARK_TRUTH_STATUS.md"

    with pytest.raises(SystemExit, match="truth artifact latest pointer mismatch"):
        mod.main(
            [
                "--corpus",
                str(corpus_path),
                "--truth-root",
                str(truth_root),
                "--scorecard-root",
                str(scorecard_root),
                "--output",
                str(output_path),
            ]
        )

    assert not output_path.exists()


def test_main_rejects_scorecard_latest_pointer_payload_divergence(tmp_path: Path) -> None:
    corpus_path = _write_json(
        tmp_path / "docs" / "benchmarks" / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 2,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Issue A"}],
        },
    )
    truth_root = tmp_path / "docs" / "status" / "generated" / "benchmark_truth_artifacts"
    scorecard_root = tmp_path / "docs" / "status" / "generated" / "benchmark_scorecards"
    _write_json(
        truth_root / "tw-01-bounded-execution-v1" / "latest.json",
        _truth_payload(revision=2),
    )
    _write_json(
        truth_root / "tw-01-bounded-execution-v1" / "rev-2" / "latest.json",
        _truth_payload(revision=2),
    )
    _write_json(
        scorecard_root / "tw-01-bounded-execution-v1" / "latest.json",
        _scorecard_payload(revision=2, generated_at="2026-04-14T20:05:00Z"),
    )
    _write_json(
        scorecard_root / "tw-01-bounded-execution-v1" / "rev-2" / "latest.json",
        _scorecard_payload(revision=2, generated_at="2026-04-14T20:35:00Z"),
    )
    output_path = tmp_path / "docs" / "status" / "B0_BENCHMARK_TRUTH_STATUS.md"

    with pytest.raises(SystemExit, match="scorecard latest pointer mismatch"):
        mod.main(
            [
                "--corpus",
                str(corpus_path),
                "--truth-root",
                str(truth_root),
                "--scorecard-root",
                str(scorecard_root),
                "--output",
                str(output_path),
            ]
        )

    assert not output_path.exists()


def test_agent_bridge_classifies_benchmark_truth_renderer_process() -> None:
    import agent_bridge as bridge

    assert (
        bridge._classify_agent_process(
            "python3 scripts/render_benchmark_truth_status.py --output /tmp/status.md"
        )
        == "benchmark_truth"
    )
    assert (
        bridge._process_summary_for_role("benchmark_truth")
        == "benchmark-truth status and latest-pointer guard process"
    )


def test_repo_checked_in_benchmark_truth_surfaces_match_current_corpus(tmp_path: Path) -> None:
    corpus_path = mod.DEFAULT_CORPUS_PATH
    latest_paths = mod.resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=mod.DEFAULT_TRUTH_ROOT,
        scorecard_root=mod.DEFAULT_SCORECARD_ROOT,
    )
    corpus = mod.load_corpus(corpus_path)
    expected_corpus_id = str(corpus.get("corpus_id") or "").strip()
    expected_revision = int(corpus.get("revision", 0) or 0)
    expected_issue_numbers = sorted(
        int(item.get("issue_id", 0) or 0)
        for item in list(corpus.get("issues") or [])
        if isinstance(item, dict) and int(item.get("issue_id", 0) or 0) > 0
    )

    truth_payload = mod._load_expected_latest_payload(
        path=latest_paths["truth_corpus_latest"],
        label="truth artifact latest.json",
        expected_corpus_id=expected_corpus_id,
        expected_revision=expected_revision,
    )
    truth_revision_payload = mod._load_expected_latest_payload(
        path=latest_paths["truth_revision_latest"],
        label="truth artifact revision latest.json",
        expected_corpus_id=expected_corpus_id,
        expected_revision=expected_revision,
    )
    scorecard_payload = mod._load_expected_latest_payload(
        path=latest_paths["scorecard_corpus_latest"],
        label="scorecard latest.json",
        expected_corpus_id=expected_corpus_id,
        expected_revision=expected_revision,
    )
    scorecard_revision_payload = mod._load_expected_latest_payload(
        path=latest_paths["scorecard_revision_latest"],
        label="scorecard revision latest.json",
        expected_corpus_id=expected_corpus_id,
        expected_revision=expected_revision,
    )

    assert truth_payload == truth_revision_payload
    assert scorecard_payload == scorecard_revision_payload
    assert truth_payload["corpus"]["membership_issue_numbers"] == expected_issue_numbers
    assert scorecard_payload["corpus"]["membership_issue_numbers"] == expected_issue_numbers

    output_path = tmp_path / "B0_BENCHMARK_TRUTH_STATUS.md"
    assert (
        mod.main(
            [
                "--corpus",
                str(corpus_path),
                "--truth-root",
                str(mod.DEFAULT_TRUTH_ROOT),
                "--scorecard-root",
                str(mod.DEFAULT_SCORECARD_ROOT),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    rendered = output_path.read_text(encoding="utf-8")
    assert f"- Revision: `{expected_revision}`" in rendered
    # Rev-3 honesty pass (2026-04-17): the corpus now carries zero verified
    # entries and three in_progress entries while autonomy is on the hook to
    # land its first real closing PR. The primary metric is therefore 0.0%
    # until the first merged PR graduates an entry; reporting 100.0% against
    # a pre-solved snapshot is the exact failure mode the audit retired.
    truth_corpus = truth_payload["corpus"]
    verified_count = int(truth_corpus.get("verified_expected_count", 0) or 0)
    in_progress_count = int(truth_corpus.get("in_progress_expected_count", 0) or 0)
    assert f"- Verified expected issues: `{verified_count}`" in rendered
    assert f"- In-progress expected issues: `{in_progress_count}`" in rendered
    truth_success_rate_verified = float(
        (truth_payload.get("primary_metrics") or {}).get("truth_success_rate_verified", 0.0)
    )
    truth_success_rate = float(
        (truth_payload.get("primary_metrics") or {}).get("truth_success_rate", 0.0)
    )
    assert (
        f"| Verified truth success rate (primary) | {truth_success_rate_verified * 100:.1f}% |"
    ) in rendered
    assert (
        f"| Full-corpus truth success rate (legacy/context) | {truth_success_rate * 100:.1f}% |"
    ) in rendered
    assert "## In-Flight Graduation Metrics" in rendered
    assert f"| In-progress expected issues | {in_progress_count} |" in rendered
