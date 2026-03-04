from __future__ import annotations

from scripts.pr_stale_run_gc import compute_active_head_map, compute_stale_runs


def test_compute_active_head_map_excludes_drafts_by_default() -> None:
    pulls = [
        {"draft": False, "head": {"ref": "feat/a", "sha": "sha-a"}},
        {"draft": True, "head": {"ref": "feat/b", "sha": "sha-b"}},
    ]
    active = compute_active_head_map(pulls, keep_draft_runs=False)
    assert active == {"feat/a": "sha-a"}


def test_compute_active_head_map_can_keep_drafts() -> None:
    pulls = [
        {"draft": False, "head": {"ref": "feat/a", "sha": "sha-a"}},
        {"draft": True, "head": {"ref": "feat/b", "sha": "sha-b"}},
    ]
    active = compute_active_head_map(pulls, keep_draft_runs=True)
    assert active == {"feat/a": "sha-a", "feat/b": "sha-b"}


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
