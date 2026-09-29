from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import build_benchmark_truth_artifact as mod  # noqa: E402


class FakeGitHubTruthClient:
    def __init__(
        self,
        *,
        issues: dict[int, dict],
        prs: dict[int, dict],
        cross_refs: dict[int, list[int] | Exception] | None = None,
    ) -> None:
        self.issues = issues
        self.prs = prs
        self.cross_refs = cross_refs or {}

    def get_issue(self, repo: str, number: int) -> dict:
        return self.issues[number]

    def get_pr(self, repo: str, number: int) -> dict:
        return self.prs[number]

    def get_cross_referenced_pr_numbers(self, repo: str, number: int) -> list[int]:
        value = self.cross_refs.get(number, [])
        if isinstance(value, Exception):
            raise value
        return list(value)


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_repo_stable_path_relativizes_git_common_root(tmp_path: Path, monkeypatch) -> None:
    worktree_root = tmp_path / "worktree"
    shared_root = tmp_path / "shared"
    metrics_path = shared_root / ".aragora" / "overnight" / "boss_metrics.jsonl"
    metrics_path.parent.mkdir(parents=True)
    metrics_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(mod, "REPO_ROOT", worktree_root)
    monkeypatch.setattr(mod, "git_common_repo_root", lambda _repo_root: shared_root)

    assert mod._repo_stable_path(metrics_path) == ".aragora/overnight/boss_metrics.jsonl"


def test_build_benchmark_truth_artifact_links_corpus_revision_and_truth_metrics(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "issue_number": 1064,
                        "issue_title": "Dependency bump",
                        "terminal_class": "deliverable_pr_created",
                        "publish_action": "pr_created",
                        "worker_outcome": "pr_adopted",
                    }
                ),
                json.dumps(
                    {
                        "issue_number": 2712,
                        "issue_title": "Boolean parsing fix",
                        "terminal_class": "rescue_worker_crash",
                        "worker_outcome": "crash",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 3,
            "recorded_on": "2026-04-13",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 1064, "title": "Dependency bump"},
                {"issue_id": 2712, "title": "Boolean parsing fix"},
            ],
        },
    )
    client = FakeGitHubTruthClient(
        issues={
            1064: {
                "title": "Dependency bump",
                # Benchmark truth uses strict linkage: only the GraphQL
                # closedByPullRequestsReferences edge counts as closure.
                "closedByPullRequestsReferences": [
                    {
                        "number": 6001,
                        "repository": {
                            "name": "aragora",
                            "owner": {"login": "synaptent"},
                        },
                    }
                ],
                "comments": [{"body": "PR: https://github.com/synaptent/aragora/pull/6001"}],
            },
            2712: {"title": "Boolean parsing fix", "comments": []},
        },
        prs={
            6001: {
                "number": 6001,
                "title": "merged fix",
                "url": "https://github.com/synaptent/aragora/pull/6001",
                "state": "MERGED",
                "mergeable": "MERGEABLE",
                "mergeStateStatus": "CLEAN",
                "mergedAt": "2026-04-13T12:00:00Z",
                "isDraft": False,
            }
        },
    )

    artifact = mod.build_benchmark_truth_artifact(
        repo="synaptent/aragora",
        metrics_file=metrics_path,
        corpus_path=corpus_path,
        client=client,
        generated_at="2026-04-13T20:00:00Z",
    )

    assert artifact["corpus"]["corpus_id"] == "tw-01-bounded-execution-v1"
    assert artifact["corpus"]["revision"] == 3
    assert (
        artifact["corpus"]["manifest_sha256"]
        == hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    )
    assert artifact["corpus"]["membership_issue_numbers"] == [1064, 2712]
    assert artifact["corpus"]["membership_sha256"] == hashlib.sha256(b"[1064,2712]").hexdigest()
    assert artifact["run_status"] == "complete"
    assert artifact["coverage"]["attempted_issue_count"] == 2
    assert artifact["coverage"]["missing_issue_numbers"] == []
    assert artifact["coverage"]["is_complete"] is True
    assert artifact["primary_metrics"]["truth_success_rate"] == 0.5
    assert artifact["primary_metrics"]["no_rescue_truth_success_rate"] == 0.5
    assert artifact["primary_metrics"]["merged_only_rate"] == 0.5
    assert artifact["failure_class_distribution"] == {"rescue_worker_crash": 1}
    assert artifact["rescue_counts_by_type"] == {"rescue_worker_crash": 1}
    assert artifact["corpus_freshness"]["status"] == "fresh"
    assert artifact["corpus_freshness"]["stale_closed_issue_count"] == 0
    assert artifact["proxy_metrics"]["attempted_issue_count"] == 2
    assert [issue["truth_state"] for issue in artifact["issues"]] == ["merged_pr", "no_linked_pr"]
    assert artifact["issues"][0]["stale_corpus_issue"] is False


def test_build_benchmark_truth_artifact_marks_partial_corpus_runs_incomplete(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "issue_number": 1064,
                "issue_title": "Dependency bump",
                "terminal_class": "deliverable_pr_created",
                "publish_action": "pr_created",
                "worker_outcome": "pr_adopted",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 4,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 1064, "title": "Dependency bump"},
                {"issue_id": 873, "title": "ESLint bump"},
            ],
        },
    )
    client = FakeGitHubTruthClient(
        issues={
            1064: {
                "title": "Dependency bump",
                "closedByPullRequestsReferences": [
                    {
                        "number": 6001,
                        "repository": {
                            "name": "aragora",
                            "owner": {"login": "synaptent"},
                        },
                    }
                ],
                "comments": [{"body": "PR: https://github.com/synaptent/aragora/pull/6001"}],
            },
            873: {"title": "ESLint bump", "comments": []},
        },
        prs={
            6001: {
                "number": 6001,
                "title": "merged fix",
                "url": "https://github.com/synaptent/aragora/pull/6001",
                "state": "MERGED",
                "mergeable": "MERGEABLE",
                "mergeStateStatus": "CLEAN",
                "mergedAt": "2026-04-13T12:00:00Z",
                "isDraft": False,
            }
        },
    )

    artifact = mod.build_benchmark_truth_artifact(
        repo="synaptent/aragora",
        metrics_file=metrics_path,
        corpus_path=corpus_path,
        client=client,
        generated_at="2026-04-14T01:00:00Z",
    )

    assert artifact["run_status"] == "incomplete"
    assert artifact["corpus"]["membership_issue_numbers"] == [873, 1064]
    assert artifact["coverage"]["attempted_issue_count"] == 1
    assert artifact["coverage"]["missing_issue_count"] == 1
    assert artifact["coverage"]["missing_issue_numbers"] == [873]
    assert artifact["coverage"]["is_complete"] is False
    assert artifact["primary_metrics"]["truth_success_rate"] == 0.5
    assert [issue["truth_state"] for issue in artifact["issues"]] == ["not_attempted", "merged_pr"]


def test_build_benchmark_truth_artifact_does_not_count_historical_truth_for_unattempted_issues(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "issue_number": 1064,
                "issue_title": "Dependency bump",
                "terminal_class": "rescue_worker_crash",
                "worker_outcome": "crash",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 4,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 1064, "title": "Dependency bump"},
                {"issue_id": 873, "title": "ESLint bump"},
            ],
        },
    )
    client = FakeGitHubTruthClient(
        issues={
            1064: {"title": "Dependency bump", "comments": []},
            873: {
                "title": "ESLint bump",
                "comments": [{"body": "PR: https://github.com/synaptent/aragora/pull/6001"}],
            },
        },
        prs={
            6001: {
                "number": 6001,
                "title": "merged fix",
                "url": "https://github.com/synaptent/aragora/pull/6001",
                "state": "MERGED",
                "mergeable": "MERGEABLE",
                "mergeStateStatus": "CLEAN",
                "mergedAt": "2026-04-13T12:00:00Z",
                "isDraft": False,
            }
        },
    )

    artifact = mod.build_benchmark_truth_artifact(
        repo="synaptent/aragora",
        metrics_file=metrics_path,
        corpus_path=corpus_path,
        client=client,
        generated_at="2026-04-14T01:00:00Z",
    )

    assert artifact["run_status"] == "incomplete"
    assert artifact["coverage"]["missing_issue_numbers"] == [873]
    assert artifact["primary_metrics"]["truth_success_rate"] == 0.0
    assert artifact["primary_metrics"]["no_rescue_truth_success_rate"] == 0.0
    assert [issue["truth_state"] for issue in artifact["issues"]] == [
        "not_attempted",
        "no_linked_pr",
    ]


def test_build_benchmark_truth_artifact_does_not_graduate_open_in_progress_issue_from_corpus_pr(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "issue_number": 1064,
                        "issue_title": "Verified dependency bump",
                        "terminal_class": "issue_already_resolved",
                        "worker_outcome": "issue_already_resolved",
                    }
                ),
                json.dumps(
                    {
                        "issue_number": 5814,
                        "issue_title": "Open in-progress test task",
                        "terminal_class": "blocked_not_dispatch_bounded",
                        "worker_outcome": "blocked",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 3,
            "recorded_on": "2026-04-17",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {
                    "issue_id": 1064,
                    "title": "Verified dependency bump",
                    "expected_status": "verified",
                },
                {
                    "issue_id": 5814,
                    "title": "Open in-progress test task",
                    "expected_status": "in_progress",
                },
            ],
        },
    )
    client = FakeGitHubTruthClient(
        issues={
            1064: {
                "title": "Verified dependency bump",
                "state": "CLOSED",
                "closedAt": "2026-04-16T12:00:00Z",
                "closedByPullRequestsReferences": [
                    {
                        "number": 6001,
                        "repository": {
                            "name": "aragora",
                            "owner": {"login": "synaptent"},
                        },
                    }
                ],
                "comments": [{"body": "PR: https://github.com/synaptent/aragora/pull/6001"}],
            },
            5814: {
                "title": "Open in-progress test task",
                "state": "OPEN",
                # Strict linkage: the forensic 'seeded by' comment is NOT
                # credited; the corpus-creation PR #6079 is a forensic
                # reference, not a closer.
                "comments": [{"body": "Seeded by https://github.com/synaptent/aragora/pull/6079"}],
            },
        },
        prs={
            6001: {
                "number": 6001,
                "title": "merged fix",
                "url": "https://github.com/synaptent/aragora/pull/6001",
                "state": "MERGED",
                "mergeable": "MERGEABLE",
                "mergeStateStatus": "CLEAN",
                "mergedAt": "2026-04-16T12:00:00Z",
                "isDraft": False,
            },
            6079: {
                "number": 6079,
                "title": "corpus v3",
                "url": "https://github.com/synaptent/aragora/pull/6079",
                "state": "MERGED",
                "mergeable": "UNKNOWN",
                "mergeStateStatus": "UNKNOWN",
                "mergedAt": "2026-04-17T12:07:40Z",
                "isDraft": False,
            },
        },
    )

    artifact = mod.build_benchmark_truth_artifact(
        repo="synaptent/aragora",
        metrics_file=metrics_path,
        corpus_path=corpus_path,
        client=client,
        generated_at="2026-04-17T13:00:00Z",
    )

    assert artifact["run_status"] == "complete"
    assert artifact["coverage"]["attempted_issue_count"] == 2
    assert artifact["primary_metrics"]["truth_success_rate_verified"] == 1.0
    assert artifact["primary_metrics"]["truth_success_rate"] == 0.5
    assert artifact["primary_metrics"]["no_rescue_truth_success_rate"] == 0.5
    assert artifact["primary_metrics"]["merged_only_rate"] == 0.5
    assert artifact["in_flight_metrics"]["in_progress_attempted_count"] == 1
    assert artifact["in_flight_metrics"]["in_progress_success_count"] == 0
    assert artifact["in_flight_metrics"]["in_progress_graduation_rate"] == 0.0
    assert [issue["truth_state"] for issue in artifact["issues"]] == [
        "merged_pr",
        "in_progress_open",
    ]
    assert artifact["issues"][1]["truth_success"] is False


def test_build_benchmark_truth_artifact_reports_stale_closed_corpus_issues(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "issue_number": 1733,
                "issue_title": "Detached worker cleanup",
                "terminal_class": "issue_already_resolved",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 4,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 1733, "title": "Detached worker cleanup"},
            ],
        },
    )
    client = FakeGitHubTruthClient(
        issues={
            1733: {
                "title": "Detached worker cleanup",
                "url": "https://github.com/synaptent/aragora/issues/1733",
                "state": "CLOSED",
                "stateReason": "COMPLETED",
                "closedAt": "2026-03-31T23:45:29Z",
                "closedByPullRequestsReferences": [],
                "comments": [],
            }
        },
        prs={},
    )

    artifact = mod.build_benchmark_truth_artifact(
        repo="synaptent/aragora",
        metrics_file=metrics_path,
        corpus_path=corpus_path,
        client=client,
        generated_at="2026-04-14T01:00:00Z",
    )

    assert artifact["primary_metrics"]["truth_success_rate"] == 0.0
    assert artifact["corpus_freshness"]["status"] == "stale_closed_issues_detected"
    assert artifact["corpus_freshness"]["stale_closed_issue_numbers"] == [1733]
    assert artifact["issues"][0]["stale_corpus_issue"] is True
    assert artifact["issues"][0]["issue_state"] == "CLOSED"


def test_build_benchmark_truth_artifact_surfaces_linkage_warnings_without_stale_alerts(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "issue_number": 1733,
                "issue_title": "Detached worker cleanup",
                "terminal_class": "issue_already_resolved",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 4,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 1733, "title": "Detached worker cleanup"},
            ],
        },
    )
    client = FakeGitHubTruthClient(
        issues={
            1733: {
                "title": "Detached worker cleanup",
                "url": "https://github.com/synaptent/aragora/issues/1733",
                "state": "CLOSED",
                "stateReason": "COMPLETED",
                "closedAt": "2026-03-31T23:45:29Z",
                "closedByPullRequestsReferences": [],
                "comments": [],
            }
        },
        prs={},
        # Under strict linkage the cross-ref fallback is no longer consulted
        # for the benchmark truth surface — failing it must not mask the
        # fact that the issue has no closing PR on the GraphQL edge.
        cross_refs={1733: RuntimeError("error connecting to api.github.com")},
    )

    artifact = mod.build_benchmark_truth_artifact(
        repo="synaptent/aragora",
        metrics_file=metrics_path,
        corpus_path=corpus_path,
        client=client,
        generated_at="2026-04-14T01:00:00Z",
    )

    # Strict linkage means a CLOSED issue with an empty
    # closedByPullRequestsReferences edge is immediately flagged as stale,
    # regardless of what the (unused) cross-ref lookup would have returned.
    # Forensic-reference PRs no longer get a second chance to mask the gap.
    assert artifact["corpus_freshness"]["status"] == "stale_closed_issues_detected"
    assert artifact["corpus_freshness"]["stale_closed_issue_numbers"] == [1733]
    assert artifact["corpus_freshness"]["linkage_error_count"] == 0
    assert artifact["issues"][0]["stale_corpus_issue"] is True
    assert artifact["issues"][0]["truth_state"] == "no_linked_pr"
    assert artifact["issues"][0]["linkage_verification_incomplete"] is False


def test_build_benchmark_truth_artifact_surfaces_closure_hygiene_drift(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "issue_number": 5903,
                "issue_title": "Roadmap-priority tests",
                "terminal_class": "deliverable_pr_created",
                "publish_action": "pr_created",
                "worker_outcome": "pr_adopted",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 4,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 5903, "title": "Roadmap-priority tests"},
            ],
        },
    )
    client = FakeGitHubTruthClient(
        issues={
            5903: {
                "title": "Roadmap-priority tests",
                "url": "https://github.com/synaptent/aragora/issues/5903",
                "state": "OPEN",
                "stateReason": "",
                "closedAt": None,
                "closedByPullRequestsReferences": [],
                "comments": [],
            }
        },
        prs={},
    )

    artifact = mod.build_benchmark_truth_artifact(
        repo="synaptent/aragora",
        metrics_file=metrics_path,
        corpus_path=corpus_path,
        client=client,
        generated_at="2026-04-14T01:00:00Z",
    )

    assert artifact["corpus_freshness"]["status"] == "closure_hygiene_drift_detected"
    assert artifact["corpus_freshness"]["stale_closed_issue_count"] == 0
    assert artifact["corpus_freshness"]["closure_hygiene_issue_numbers"] == [5903]
    assert artifact["issues"][0]["proxy_pr_signal"] is True
    assert artifact["issues"][0]["truth_state"] == "no_linked_pr"
    assert artifact["issues"][0]["issue_state"] == "OPEN"


def test_build_benchmark_truth_artifact_surfaces_freshness_issue_draft(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "issue_number": 1733,
                "issue_title": "Detached worker cleanup",
                "terminal_class": "issue_already_resolved",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 4,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 1733, "title": "Detached worker cleanup"},
            ],
        },
    )
    freshness_map_path = _write_json(
        tmp_path / "benchmark_corpus_freshness.json",
        {
            "schema_version": 1,
            "entries": [],
        },
    )
    client = FakeGitHubTruthClient(
        issues={
            1733: {
                "title": "Detached worker cleanup",
                "url": "https://github.com/synaptent/aragora/issues/1733",
                "state": "CLOSED",
                "stateReason": "COMPLETED",
                "closedAt": "2026-03-31T23:45:29Z",
                "closedByPullRequestsReferences": [],
                "comments": [],
            }
        },
        prs={},
    )

    artifact = mod.build_benchmark_truth_artifact(
        repo="synaptent/aragora",
        metrics_file=metrics_path,
        corpus_path=corpus_path,
        client=client,
        generated_at="2026-04-14T01:00:00Z",
        freshness_map_path=freshness_map_path,
    )

    assert artifact["corpus_freshness"]["issue_map_path"] == str(freshness_map_path)
    assert artifact["corpus_freshness"]["linked_issue_count"] == 0
    assert artifact["corpus_freshness"]["unlinked_issue_count"] == 1
    assert artifact["corpus_freshness"]["issue_drafts"][0]["title"] == (
        "[TW-02] Restock stale issues in tw-01-bounded-execution-v1 rev-4"
    )


def test_build_benchmark_truth_artifact_reopens_draft_when_linked_issue_is_closed(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "issue_number": 1733,
                "issue_title": "Detached worker cleanup",
                "terminal_class": "issue_already_resolved",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 4,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 1733, "title": "Detached worker cleanup"},
            ],
        },
    )
    freshness_map_path = _write_json(
        tmp_path / "benchmark_corpus_freshness.json",
        {
            "schema_version": 1,
            "entries": [
                {
                    "corpus_id": "tw-01-bounded-execution-v1",
                    "revision": 4,
                    "stale_issue_numbers": [1733],
                    "target_kind": "issue",
                    "target": "#6001",
                    "title": "[TW-02] Restock stale issues in tw-01-bounded-execution-v1 rev-4",
                    "url": "https://github.com/synaptent/aragora/issues/6001",
                    "notes": "Auto-linked by recurring TW-02 publication.",
                }
            ],
        },
    )
    client = FakeGitHubTruthClient(
        issues={
            1733: {
                "title": "Detached worker cleanup",
                "url": "https://github.com/synaptent/aragora/issues/1733",
                "state": "CLOSED",
                "stateReason": "COMPLETED",
                "closedAt": "2026-03-31T23:45:29Z",
                "closedByPullRequestsReferences": [],
                "comments": [],
            },
            6001: {
                "title": "[TW-02] Restock stale issues in tw-01-bounded-execution-v1 rev-4",
                "url": "https://github.com/synaptent/aragora/issues/6001",
                "state": "CLOSED",
                "stateReason": "COMPLETED",
                "closedAt": "2026-04-14T10:00:00Z",
                "closedByPullRequestsReferences": [],
                "comments": [],
            },
        },
        prs={},
    )

    artifact = mod.build_benchmark_truth_artifact(
        repo="synaptent/aragora",
        metrics_file=metrics_path,
        corpus_path=corpus_path,
        client=client,
        generated_at="2026-04-14T01:00:00Z",
        freshness_map_path=freshness_map_path,
    )

    assert artifact["corpus_freshness"]["linked_issue_count"] == 0
    assert artifact["corpus_freshness"]["unlinked_issue_count"] == 1
    assert artifact["corpus_freshness"]["issue_drafts"][0]["stale_issue_numbers"] == [1733]


def test_detect_post_generation_issue_state_drift_flags_issue_closed_after_artifact() -> None:
    artifact = {
        "generated_at": "2026-04-17T14:33:07Z",
        "issues": [
            {
                "issue_number": 5903,
                "issue_title": "[CS-01] Add roadmap priority policy classification tests",
                "issue_url": "https://github.com/synaptent/aragora/issues/5903",
                "issue_state": "OPEN",
                "issue_state_reason": "",
                "issue_closed_at": None,
            }
        ],
    }
    client = FakeGitHubTruthClient(
        issues={
            5903: {
                "title": "[CS-01] Add roadmap priority policy classification tests",
                "url": "https://github.com/synaptent/aragora/issues/5903",
                "state": "CLOSED",
                "stateReason": "COMPLETED",
                "closedAt": "2026-04-17T15:45:52Z",
                "updatedAt": "2026-04-17T15:45:52Z",
                "closedByPullRequestsReferences": [],
                "comments": [],
            }
        },
        prs={},
    )

    drift = mod.detect_post_generation_issue_state_drift(
        artifact=artifact,
        repo="synaptent/aragora",
        client=client,
    )

    assert drift["status"] == "post_generation_issue_state_drift"
    assert drift["issue_count"] == 1
    assert drift["issues"][0]["issue_number"] == 5903
    assert drift["issues"][0]["artifact_issue_state"] == "OPEN"
    assert drift["issues"][0]["live_issue_state"] == "CLOSED"


def test_detect_post_generation_issue_state_drift_ignores_unchanged_issue_state() -> None:
    artifact = {
        "generated_at": "2026-04-17T14:33:07Z",
        "issues": [
            {
                "issue_number": 5903,
                "issue_title": "[CS-01] Add roadmap priority policy classification tests",
                "issue_url": "https://github.com/synaptent/aragora/issues/5903",
                "issue_state": "OPEN",
                "issue_state_reason": "",
                "issue_closed_at": None,
            }
        ],
    }
    client = FakeGitHubTruthClient(
        issues={
            5903: {
                "title": "[CS-01] Add roadmap priority policy classification tests",
                "url": "https://github.com/synaptent/aragora/issues/5903",
                "state": "OPEN",
                "stateReason": "",
                "closedAt": None,
                "updatedAt": "2026-04-17T15:45:52Z",
                "closedByPullRequestsReferences": [],
                "comments": [],
            }
        },
        prs={},
    )

    drift = mod.detect_post_generation_issue_state_drift(
        artifact=artifact,
        repo="synaptent/aragora",
        client=client,
    )

    assert drift == {
        "status": "fresh",
        "generated_at": "2026-04-17T14:33:07Z",
        "issue_count": 0,
        "issues": [],
    }


def test_attach_corpus_freshness_follow_up_reopens_draft_when_stale_set_drifts(
    tmp_path: Path,
) -> None:
    freshness_map_path = _write_json(
        tmp_path / "benchmark_corpus_freshness.json",
        {
            "schema_version": 1,
            "entries": [
                {
                    "corpus_id": "tw-01-bounded-execution-v1",
                    "revision": 4,
                    "stale_issue_numbers": [1733],
                    "target_kind": "issue",
                    "target": "#6001",
                    "title": "[TW-02] Restock stale issues in tw-01-bounded-execution-v1 rev-4",
                    "url": "https://github.com/synaptent/aragora/issues/6001",
                    "notes": "Auto-linked by recurring TW-02 publication.",
                }
            ],
        },
    )

    artifact = mod.attach_corpus_freshness_follow_up(
        artifact={
            "corpus": {
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 4,
            },
            "corpus_freshness": {
                "status": "stale_closed_issues_detected",
                "stale_closed_issue_numbers": [9999],
                "stale_closed_issues": [
                    {
                        "issue_number": 9999,
                        "issue_title": "New stale issue",
                        "issue_url": "https://github.com/synaptent/aragora/issues/9999",
                        "truth_state": "no_linked_pr",
                    }
                ],
            },
        },
        freshness_map_path=freshness_map_path,
        repo="synaptent/aragora",
    )

    assert artifact["corpus_freshness"]["linked_issues"] == []
    assert artifact["corpus_freshness"]["linked_issue_count"] == 0
    assert artifact["corpus_freshness"]["unlinked_issue_count"] == 1
    assert artifact["corpus_freshness"]["issue_drafts"] == [
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 4,
            "stale_issue_numbers": [9999],
            "title": "[TW-02] Restock stale issues in tw-01-bounded-execution-v1 rev-4",
            "body": artifact["corpus_freshness"]["issue_drafts"][0]["body"],
        }
    ]
    assert "#9999" in artifact["corpus_freshness"]["issue_drafts"][0]["body"]


def test_attach_corpus_freshness_follow_up_ignores_missing_linked_issue_target(
    tmp_path: Path,
) -> None:
    freshness_map_path = _write_json(
        tmp_path / "benchmark_corpus_freshness.json",
        {
            "schema_version": 1,
            "entries": [
                {
                    "corpus_id": "tw-01-bounded-execution-v1",
                    "revision": 4,
                    "stale_issue_numbers": [1733],
                    "target_kind": "issue",
                    "target": "#6001",
                    "title": "[TW-02] Restock stale issues in tw-01-bounded-execution-v1 rev-4",
                    "url": "https://github.com/synaptent/aragora/issues/6001",
                    "notes": "Auto-linked by recurring TW-02 publication.",
                }
            ],
        },
    )
    client = FakeGitHubTruthClient(issues={}, prs={})

    artifact = mod.attach_corpus_freshness_follow_up(
        artifact={
            "corpus": {
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 4,
            },
            "corpus_freshness": {
                "status": "stale_closed_issues_detected",
                "stale_closed_issue_numbers": [1733],
                "stale_closed_issues": [
                    {
                        "issue_number": 1733,
                        "issue_title": "Detached worker cleanup",
                        "issue_url": "https://github.com/synaptent/aragora/issues/1733",
                        "truth_state": "no_linked_pr",
                    }
                ],
            },
        },
        freshness_map_path=freshness_map_path,
        repo="synaptent/aragora",
        client=client,
    )

    assert artifact["corpus_freshness"]["linked_issues"] == []
    assert artifact["corpus_freshness"]["linked_issue_count"] == 0
    assert artifact["corpus_freshness"]["unlinked_issue_count"] == 1
    assert artifact["corpus_freshness"]["issue_drafts"][0]["stale_issue_numbers"] == [1733]


def test_ensure_corpus_freshness_issue_linkage_updates_map(
    tmp_path: Path,
    monkeypatch,
) -> None:
    freshness_map_path = _write_json(
        tmp_path / "benchmark_corpus_freshness.json",
        {
            "schema_version": 1,
            "entries": [],
        },
    )
    monkeypatch.setattr(
        mod,
        "find_existing_issue_by_title",
        lambda **_: {
            "number": 6001,
            "title": "[TW-02] Restock stale issues in tw-01-bounded-execution-v1 rev-4",
            "url": "https://github.com/synaptent/aragora/issues/6001",
            "state": "open",
        },
    )

    results = mod.ensure_corpus_freshness_issue_linkage(
        issue_drafts=[
            {
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 4,
                "stale_issue_numbers": [1733],
                "title": "[TW-02] Restock stale issues in tw-01-bounded-execution-v1 rev-4",
                "body": "body",
            }
        ],
        freshness_map_path=freshness_map_path,
        repo="synaptent/aragora",
    )

    assert results == [
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 4,
            "action": "linked_existing_issue",
            "target_kind": "issue",
            "target": "#6001",
            "url": "https://github.com/synaptent/aragora/issues/6001",
        }
    ]
    written_map = json.loads(freshness_map_path.read_text(encoding="utf-8"))
    assert written_map["entries"] == [
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "notes": "Auto-linked by recurring TW-02 publication.",
            "revision": 4,
            "stale_issue_numbers": [1733],
            "target": "#6001",
            "target_kind": "issue",
            "title": "[TW-02] Restock stale issues in tw-01-bounded-execution-v1 rev-4",
            "url": "https://github.com/synaptent/aragora/issues/6001",
        }
    ]


def test_main_fail_incomplete_returns_nonzero_and_emits_artifact(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "issue_number": 1064,
                "issue_title": "Dependency bump",
                "terminal_class": "deliverable_pr_created",
                "publish_action": "pr_created",
                "worker_outcome": "pr_adopted",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 5,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 1064, "title": "Dependency bump"},
                {"issue_id": 873, "title": "ESLint bump"},
            ],
        },
    )
    fake_client = FakeGitHubTruthClient(
        issues={
            1064: {
                "title": "Dependency bump",
                "comments": [{"body": "PR: https://github.com/synaptent/aragora/pull/6001"}],
            },
            873: {"title": "ESLint bump", "comments": []},
        },
        prs={
            6001: {
                "number": 6001,
                "title": "merged fix",
                "url": "https://github.com/synaptent/aragora/pull/6001",
                "state": "MERGED",
                "mergeable": "MERGEABLE",
                "mergeStateStatus": "CLEAN",
                "mergedAt": "2026-04-13T12:00:00Z",
                "isDraft": False,
            }
        },
    )

    monkeypatch.setattr(mod, "GitHubTruthClient", lambda: fake_client)

    exit_code = mod.main(
        [
            "--repo",
            "synaptent/aragora",
            "--metrics-file",
            str(metrics_path),
            "--corpus",
            str(corpus_path),
            "--json",
            "--fail-incomplete",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 2
    assert payload["run_status"] == "incomplete"
    assert payload["coverage"]["missing_issue_numbers"] == [873]
    assert "incomplete corpus coverage" in captured.err


def test_main_fail_incomplete_does_not_publish_artifacts(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text("", encoding="utf-8")
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(
        json.dumps(
            {
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 1,
                "recorded_on": "2026-04-14",
                "success_contract": "mergeable_pr_or_merged_pr",
                "issues": [
                    {"issue_id": 1064, "title": "Issue A"},
                    {"issue_id": 873, "title": "Issue B"},
                ],
            }
        ),
        encoding="utf-8",
    )
    fake_client = FakeGitHubTruthClient(
        issues={
            1064: {"title": "Issue A", "comments": []},
            873: {"title": "Issue B", "comments": []},
        },
        prs={
            1064: {
                "number": 6002,
                "title": "mergeable fix",
                "url": "https://github.com/synaptent/aragora/pull/6002",
                "state": "OPEN",
                "mergeable": "MERGEABLE",
                "mergeStateStatus": "CLEAN",
                "mergedAt": None,
                "isDraft": False,
            }
        },
    )

    monkeypatch.setattr(mod, "GitHubTruthClient", lambda: fake_client)

    publish_dir = tmp_path / "published"
    exit_code = mod.main(
        [
            "--repo",
            "synaptent/aragora",
            "--metrics-file",
            str(metrics_path),
            "--corpus",
            str(corpus_path),
            "--publish-dir",
            str(publish_dir),
            "--fail-incomplete",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "incomplete corpus coverage" in captured.err
    assert not publish_dir.exists()


def test_write_artifact_emits_diffable_json(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-04-13T20:00:00Z",
        "corpus": {"corpus_id": "tw-01", "revision": 1, "issue_count": 1},
        "primary_metrics": {"truth_success_rate": 1.0},
    }
    output = tmp_path / "artifact.json"

    written = mod.write_artifact(output, payload)

    assert written == output
    parsed = json.loads(output.read_text(encoding="utf-8"))
    assert parsed["corpus"]["revision"] == 1
    assert parsed["primary_metrics"]["truth_success_rate"] == 1.0


def test_build_benchmark_truth_artifact_normalizes_generated_at_and_repo_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text("", encoding="utf-8")
    repo_root = tmp_path / "repo"
    corpus_path = repo_root / "docs" / "benchmarks" / "corpus.json"
    corpus_path.parent.mkdir(parents=True)
    corpus_path.write_text(
        json.dumps(
            {
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 7,
                "recorded_on": "2026-04-14",
                "success_contract": "mergeable_pr_or_merged_pr",
                "issues": [{"issue_id": 1064, "title": "Dependency bump"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "REPO_ROOT", repo_root)

    artifact = mod.build_benchmark_truth_artifact(
        repo="synaptent/aragora",
        metrics_file=metrics_path,
        corpus_path=corpus_path,
        client=FakeGitHubTruthClient(
            issues={1064: {"title": "Dependency bump", "comments": []}},
            prs={},
        ),
        generated_at="2026-04-14T02:03:04+00:00",
    )

    assert artifact["generated_at"] == "2026-04-14T02:03:04Z"
    assert artifact["corpus"]["path"] == "docs/benchmarks/corpus.json"
    assert (
        artifact["corpus"]["manifest_sha256"]
        == hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    )
    assert artifact["corpus"]["membership_issue_numbers"] == [1064]
    assert artifact["metrics_file"] == str(metrics_path)


def test_resolve_published_artifact_path_uses_corpus_revision_and_timestamp() -> None:
    path = mod.resolve_published_artifact_path(
        publish_dir=Path("/tmp/published"),
        artifact={
            "generated_at": "2026-04-14T02:03:04Z",
            "corpus": {
                "corpus_id": "TW-01 Bounded Execution v1",
                "revision": 7,
            },
        },
    )

    assert path == Path(
        "/tmp/published/tw-01-bounded-execution-v1/rev-7/truth-20260414T020304Z.json"
    )


def test_resolve_latest_artifact_paths_use_corpus_and_revision_roots() -> None:
    paths = mod.resolve_latest_artifact_paths(
        publish_dir=Path("/tmp/published"),
        artifact={
            "generated_at": "2026-04-14T02:03:04Z",
            "corpus": {
                "corpus_id": "TW-01 Bounded Execution v1",
                "revision": 7,
            },
        },
    )

    assert paths == {
        "corpus_latest": Path("/tmp/published/tw-01-bounded-execution-v1/latest.json"),
        "revision_latest": Path("/tmp/published/tw-01-bounded-execution-v1/rev-7/latest.json"),
    }


def test_publish_artifact_bundle_rejects_missing_identity(tmp_path: Path) -> None:
    valid_artifact = {
        "generated_at": "2026-04-14T02:03:04Z",
        "corpus": {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 7,
            "issue_count": 1,
        },
        "primary_metrics": {"truth_success_rate": 1.0},
    }

    cases = [
        (
            {**valid_artifact, "generated_at": ""},
            "generated_at is required",
        ),
        (
            {**valid_artifact, "corpus": {**valid_artifact["corpus"], "corpus_id": ""}},
            "corpus.corpus_id is required",
        ),
        (
            {**valid_artifact, "corpus": {**valid_artifact["corpus"], "revision": 0}},
            "corpus.revision must be a positive integer",
        ),
    ]

    for artifact, expected_message in cases:
        publish_dir = tmp_path / expected_message.split()[0]
        try:
            mod.publish_artifact_bundle(publish_dir=publish_dir, artifact=artifact)
        except ValueError as exc:
            assert expected_message in str(exc)
        else:
            raise AssertionError(f"expected ValueError containing {expected_message!r}")
        assert not publish_dir.exists()


def test_main_publish_dir_writes_timestamped_artifact_and_prints_path(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text("", encoding="utf-8")
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 8,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Dependency bump"}],
        },
    )
    monkeypatch.setattr(
        mod,
        "build_benchmark_truth_artifact",
        lambda **_: {
            "generated_at": "2026-04-14T05:06:07Z",
            "corpus": {
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 8,
                "issue_count": 1,
            },
            "primary_metrics": {"truth_success_rate": 1.0},
        },
    )

    exit_code = mod.main(
        [
            "--repo",
            "synaptent/aragora",
            "--metrics-file",
            str(metrics_path),
            "--corpus",
            str(corpus_path),
            "--publish-dir",
            str(tmp_path / "published"),
        ]
    )

    captured = capsys.readouterr()
    written_path = Path(captured.out.strip())
    assert exit_code == 0
    assert written_path == Path(
        tmp_path
        / "published"
        / "tw-01-bounded-execution-v1"
        / "rev-8"
        / "truth-20260414T050607Z.json"
    )
    parsed = json.loads(written_path.read_text(encoding="utf-8"))
    assert parsed["generated_at"] == "2026-04-14T05:06:07Z"
    assert (
        json.loads(
            (tmp_path / "published" / "tw-01-bounded-execution-v1" / "latest.json").read_text(
                encoding="utf-8"
            )
        )["generated_at"]
        == "2026-04-14T05:06:07Z"
    )
    assert (
        json.loads(
            (
                tmp_path / "published" / "tw-01-bounded-execution-v1" / "rev-8" / "latest.json"
            ).read_text(encoding="utf-8")
        )["generated_at"]
        == "2026-04-14T05:06:07Z"
    )
    assert captured.err == ""


def test_main_publish_dir_with_json_keeps_stdout_json_and_reports_path_on_stderr(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    metrics_path.write_text("", encoding="utf-8")
    corpus_path = _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 9,
            "recorded_on": "2026-04-14",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [{"issue_id": 1064, "title": "Dependency bump"}],
        },
    )
    monkeypatch.setattr(
        mod,
        "build_benchmark_truth_artifact",
        lambda **_: {
            "generated_at": "2026-04-14T08:09:10Z",
            "corpus": {
                "corpus_id": "tw-01-bounded-execution-v1",
                "revision": 9,
                "issue_count": 1,
            },
            "primary_metrics": {"truth_success_rate": 1.0},
        },
    )

    exit_code = mod.main(
        [
            "--repo",
            "synaptent/aragora",
            "--metrics-file",
            str(metrics_path),
            "--corpus",
            str(corpus_path),
            "--publish-dir",
            str(tmp_path / "published"),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["generated_at"] == "2026-04-14T08:09:10Z"
    assert (
        json.loads(
            (tmp_path / "published" / "tw-01-bounded-execution-v1" / "latest.json").read_text(
                encoding="utf-8"
            )
        )["generated_at"]
        == "2026-04-14T08:09:10Z"
    )
    assert captured.err.strip() == str(
        tmp_path
        / "published"
        / "tw-01-bounded-execution-v1"
        / "rev-9"
        / "truth-20260414T080910Z.json"
    )


def _observation_corpus(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "corpus.json",
        {
            "corpus_id": "tw-01-bounded-execution-v1",
            "revision": 7,
            "recorded_on": "2026-08-19",
            "success_contract": "mergeable_pr_or_merged_pr",
            "issues": [
                {"issue_id": 1064, "title": "Dependency bump"},
                {"issue_id": 2712, "title": "Boolean parsing fix"},
            ],
        },
    )


def _observation_client() -> FakeGitHubTruthClient:
    return FakeGitHubTruthClient(
        issues={
            1064: {
                "title": "Dependency bump",
                "closedByPullRequestsReferences": [
                    {
                        "number": 6001,
                        "repository": {"name": "aragora", "owner": {"login": "synaptent"}},
                    }
                ],
                "comments": [],
            },
            2712: {"title": "Boolean parsing fix", "comments": []},
        },
        prs={
            6001: {
                "number": 6001,
                "title": "merged fix",
                "url": "https://github.com/synaptent/aragora/pull/6001",
                "state": "MERGED",
                "mergeable": "MERGEABLE",
                "mergeStateStatus": "CLEAN",
                "mergedAt": "2026-04-13T12:00:00Z",
                "isDraft": False,
            }
        },
    )


def _executed_rows_metrics(tmp_path: Path, *, elapsed: tuple[float, float]) -> Path:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    rows = [
        {
            "issue_number": 1064,
            "terminal_class": "deliverable_pr_created",
            "publish_action": "pr_created",
            "elapsed_seconds": elapsed[0],
        },
        {
            "issue_number": 2712,
            "terminal_class": "rescue_worker_crash",
            "elapsed_seconds": elapsed[1],
        },
    ]
    metrics_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return metrics_path


def _build_observed_artifact(
    tmp_path: Path, *, metrics_path: Path, rescue_ledger_path: Path | None
) -> dict:
    return mod.build_benchmark_truth_artifact(
        repo="synaptent/aragora",
        metrics_file=metrics_path,
        corpus_path=_observation_corpus(tmp_path),
        client=_observation_client(),
        generated_at="2026-09-29T01:59:04Z",
        rescue_ledger_path=rescue_ledger_path,
    )


def test_recurrence_placeholder_rows_leave_rescue_and_elapsed_unobserved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Reproduce the rows the daily recurrence writes for closed and
    # label-skipped corpus issues, via the real producer.
    import run_benchmark_corpus_recurrence as recurrence
    from aragora.swarm import boss_loop_outcome

    monkeypatch.setattr(boss_loop_outcome, "load_category_success_rates", lambda **_: {})
    metrics_path = tmp_path / "boss_metrics.jsonl"
    recurrence.append_closed_issue_rows(
        metrics_file=metrics_path,
        closed_issue_numbers=[1064],
        issue_titles={1064: "Dependency bump"},
    )
    recurrence.append_skipped_open_issue_rows(
        metrics_file=metrics_path,
        skipped_issue_numbers=[2712],
        issue_titles={2712: "Boolean parsing fix"},
        skip_label_map={2712: ["boss-stuck"]},
        start_iteration=2,
    )
    rows = [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines()]
    assert [row["terminal_class"] for row in rows] == [
        "issue_already_resolved",
        "blocked_not_dispatch_bounded",
    ]

    artifact = _build_observed_artifact(
        tmp_path,
        metrics_path=metrics_path,
        rescue_ledger_path=tmp_path / "missing" / "rescue_events.jsonl",
    )

    assert artifact["observation_status"] == {
        "raw_inputs": "available",
        "elapsed_time": "unmeasured",
        "rescue_history": "incomplete",
        "raw_input_replay": "unmeasured",
    }
    limits = artifact["observation_limits"]
    assert limits["non_authoritative_fields"] == list(mod.RESCUE_DEPENDENT_FIELDS)
    assert limits["issues_without_executed_attempt"] == [1064, 2712]
    assert "`rescue_ledger_missing`" in limits["reason"]
    assert "#1064, #2712 have no executed attempt" in limits["reason"]
    assert artifact["rescue_ledger"]["status"] == "unavailable"
    assert artifact["rescue_ledger"]["error_code"] == "rescue_ledger_missing"
    # Values are retained; the markers above are what demote them.
    issue_1064 = next(item for item in artifact["issues"] if item["issue_number"] == 1064)
    assert issue_1064["had_rescue"] is False
    assert issue_1064["no_rescue_truth_success"] is True
    assert artifact["rescue_counts_by_type"] == {}


def test_executed_attempts_and_fully_read_ledger_mark_rescue_history_complete(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "rescue_events.jsonl"
    ledger_path.write_text(
        json.dumps({"event_type": "manual_merge", "reason": "other issue", "issue_number": 9999})
        + "\n"
        + json.dumps({"event_type": "session_restart", "reason": "no issue"})
        + "\n",
        encoding="utf-8",
    )

    artifact = _build_observed_artifact(
        tmp_path,
        metrics_path=_executed_rows_metrics(tmp_path, elapsed=(120.0, 30.0)),
        rescue_ledger_path=ledger_path,
    )

    assert artifact["observation_status"] == {
        "raw_inputs": "available",
        "elapsed_time": "measured",
        "rescue_history": "complete",
        "raw_input_replay": "unmeasured",
    }
    assert "observation_limits" not in artifact
    assert artifact["rescue_ledger"]["status"] == "available"
    assert artifact["rescue_ledger"]["event_count"] == 2
    assert artifact["rescue_ledger"]["corpus_event_issue_numbers"] == []
    assert artifact["rescue_counts_by_type"] == {"rescue_worker_crash": 1}


def test_executed_attempt_without_elapsed_sample_marks_elapsed_incomplete(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "rescue_events.jsonl"
    ledger_path.write_text("", encoding="utf-8")

    artifact = _build_observed_artifact(
        tmp_path,
        metrics_path=_executed_rows_metrics(tmp_path, elapsed=(120.0, 0.0)),
        rescue_ledger_path=ledger_path,
    )

    assert artifact["observation_status"]["elapsed_time"] == "incomplete"
    assert artifact["observation_status"]["rescue_history"] == "complete"
    # The truth artifact publishes no elapsed values, so nothing is demoted.
    assert "observation_limits" not in artifact


@pytest.mark.parametrize(
    ("ledger_content", "reason_fragment"),
    [
        (
            json.dumps({"event_type": "manual_merge", "reason": "hand merge", "issue_number": 1064})
            + "\n",
            "interventions on corpus issue(s) #1064",
        ),
        (
            json.dumps({"event_type": "manual_merge", "reason": "ok"})
            + "\n"
            + '{"event_type": "manual_merge", "reason": "torn", "issue_n',
            "1 torn trailing rescue ledger record(s)",
        ),
        ("not json\n", "`rescue_ledger_malformed`"),
        (None, "No rescue event ledger was consulted"),
    ],
    ids=["corpus-intervention", "torn-trailing-record", "malformed", "not-consulted"],
)
def test_rescue_ledger_gaps_mark_rescue_history_incomplete(
    tmp_path: Path,
    ledger_content: str | None,
    reason_fragment: str,
) -> None:
    ledger_path: Path | None = None
    if ledger_content is not None:
        ledger_path = tmp_path / "rescue_events.jsonl"
        ledger_path.write_text(ledger_content, encoding="utf-8")

    artifact = _build_observed_artifact(
        tmp_path,
        metrics_path=_executed_rows_metrics(tmp_path, elapsed=(120.0, 30.0)),
        rescue_ledger_path=ledger_path,
    )

    assert artifact["observation_status"]["rescue_history"] == "incomplete"
    limits = artifact["observation_limits"]
    assert reason_fragment in limits["reason"]
    assert limits["non_authoritative_fields"] == list(mod.RESCUE_DEPENDENT_FIELDS)
    # Every corpus issue had an executed attempt; only the ledger is short.
    assert "issues_without_executed_attempt" not in limits
