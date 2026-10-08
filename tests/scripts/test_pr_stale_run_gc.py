from __future__ import annotations

from typing import Any

from scripts.pr_stale_run_gc import (
    compute_active_head_map,
    compute_draft_branches,
    compute_stale_runs,
    parse_args,
)

PR_EVENTS = {"pull_request", "pull_request_target"}


def _default_schedule_stale(
    pulls: list[dict[str, Any]], runs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Mirror the scheduled GC invocation, which passes no --keep-draft-runs."""
    return compute_stale_runs(
        runs,
        active_heads=compute_active_head_map(pulls),
        cancel_events=set(PR_EVENTS),
    )


def test_compute_active_head_map_includes_draft_heads() -> None:
    pulls = [
        {"draft": False, "head": {"ref": "feat/a", "sha": "sha-a"}},
        {"draft": True, "head": {"ref": "feat/b", "sha": "sha-b"}},
    ]
    active = compute_active_head_map(pulls)
    assert active == {"feat/a": "sha-a", "feat/b": "sha-b"}


def test_compute_draft_branches_returns_only_draft_refs() -> None:
    pulls = [
        {"draft": False, "head": {"ref": "feat/a", "sha": "sha-a"}},
        {"draft": True, "head": {"ref": "feat/b", "sha": "sha-b"}},
        {"draft": True, "head": {"ref": "", "sha": "sha-c"}},
    ]
    assert compute_draft_branches(pulls) == {"feat/b"}


def test_draft_pr_current_head_run_survives_default_gc() -> None:
    pulls = [{"draft": True, "head": {"ref": "feat/draft", "sha": "sha-cur"}}]
    runs = [
        {
            "id": 10,
            "event": "pull_request",
            "status": "in_progress",
            "head_branch": "feat/draft",
            "head_sha": "sha-cur",
        }
    ]
    assert _default_schedule_stale(pulls, runs) == []


def test_draft_pr_superseded_head_run_still_cancelled() -> None:
    pulls = [{"draft": True, "head": {"ref": "feat/draft", "sha": "sha-new"}}]
    runs = [
        {
            "id": 11,
            "event": "pull_request",
            "status": "queued",
            "head_branch": "feat/draft",
            "head_sha": "sha-old",
        }
    ]
    stale = _default_schedule_stale(pulls, runs)
    assert [(item["run_id"], item["reason"]) for item in stale] == [(11, "stale-sha")]
    assert stale[0]["active_sha"] == "sha-new"


def test_branch_without_open_pr_still_cancelled() -> None:
    pulls = [{"draft": True, "head": {"ref": "feat/draft", "sha": "sha-cur"}}]
    runs = [
        {
            "id": 12,
            "event": "pull_request",
            "status": "queued",
            "head_branch": "feat/closed",
            "head_sha": "sha-z",
        }
    ]
    stale = _default_schedule_stale(pulls, runs)
    assert [(item["run_id"], item["reason"]) for item in stale] == [(12, "no-active-pr-head")]


def test_non_draft_behavior_unchanged_by_default() -> None:
    pulls = [{"draft": False, "head": {"ref": "feat/a", "sha": "sha-a"}}]
    runs = [
        {
            "id": 20,
            "event": "pull_request",
            "status": "in_progress",
            "head_branch": "feat/a",
            "head_sha": "sha-a",
        },
        {
            "id": 21,
            "event": "pull_request",
            "status": "queued",
            "head_branch": "feat/a",
            "head_sha": "sha-old",
        },
        {
            "id": 22,
            "event": "push",
            "status": "queued",
            "head_branch": "feat/a",
            "head_sha": "sha-old",
        },
    ]
    stale = _default_schedule_stale(pulls, runs)
    assert [(item["run_id"], item["reason"]) for item in stale] == [(21, "stale-sha")]


def test_keep_draft_runs_also_keeps_superseded_draft_heads() -> None:
    pulls = [
        {"draft": True, "head": {"ref": "feat/draft", "sha": "sha-new"}},
        {"draft": False, "head": {"ref": "feat/a", "sha": "sha-a"}},
    ]
    runs = [
        {
            "id": 30,
            "event": "pull_request",
            "status": "queued",
            "head_branch": "feat/draft",
            "head_sha": "sha-old",
        },
        {
            "id": 31,
            "event": "pull_request",
            "status": "queued",
            "head_branch": "feat/a",
            "head_sha": "sha-old",
        },
    ]
    stale = compute_stale_runs(
        runs,
        active_heads=compute_active_head_map(pulls),
        cancel_events=set(PR_EVENTS),
        keep_stale_sha_branches=compute_draft_branches(pulls),
    )
    assert [(item["run_id"], item["reason"]) for item in stale] == [(31, "stale-sha")]


def test_compute_stale_runs_flags_missing_branch_and_stale_sha() -> None:
    runs = [
        {
            "id": 1,
            "event": "pull_request",
            "status": "queued",
            "head_branch": "feat/a",
            "head_sha": "old-sha",
        },
        {
            "id": 2,
            "event": "pull_request",
            "status": "in_progress",
            "head_branch": "feat/missing",
            "head_sha": "sha-z",
        },
        {
            "id": 3,
            "event": "push",
            "status": "queued",
            "head_branch": "feat/a",
            "head_sha": "sha-a",
        },
    ]
    active_heads = {"feat/a": "sha-a"}
    stale = compute_stale_runs(
        runs,
        active_heads=active_heads,
        cancel_events={"pull_request", "pull_request_target"},
    )

    by_id = {item["run_id"]: item for item in stale}
    assert by_id[1]["reason"] == "stale-sha"
    assert by_id[2]["reason"] == "no-active-pr-head"
    assert 3 not in by_id


def test_parse_args_keep_draft_runs_flag() -> None:
    assert parse_args(["--repo", "o/r"]).keep_draft_runs is False
    assert parse_args(["--repo", "o/r", "--keep-draft-runs"]).keep_draft_runs is True
