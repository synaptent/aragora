from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import scripts.merge_codex_automation_prs as merge_codex
from scripts.merge_codex_automation_prs import (
    MergeDecision,
    PullRequestSnapshot,
    select_mergeable_prs,
)


def _pr(
    number: int,
    *,
    head_ref: str = "codex/safe-fix",
    head_sha: str = "a" * 40,
    is_draft: bool = False,
    mergeable: str = "MERGEABLE",
    body: str = "## Validation\n- pytest -q",
    changed_files: list[str] | None = None,
    status_rollup: list[dict[str, str]] | None = None,
) -> PullRequestSnapshot:
    if changed_files is None:
        changed_files = ["aragora/live/src/app/page.tsx"]
    if status_rollup is None:
        status_rollup = [{"status": "COMPLETED", "conclusion": "SUCCESS", "name": "tests"}]
    return PullRequestSnapshot(
        number=number,
        title=f"PR {number}",
        head_ref=head_ref,
        head_sha=head_sha,
        is_draft=is_draft,
        mergeable=mergeable,
        body=body,
        url=f"https://example.com/pr/{number}",
        changed_files=changed_files,
        status_rollup=status_rollup,
    )


def _decision(decisions: list[MergeDecision], number: int) -> MergeDecision:
    for decision in decisions:
        if decision.number == number:
            return decision
    raise AssertionError(f"missing decision for PR {number}")


def _snapshot_metadata(number: int = 7) -> dict[str, object]:
    return {
        "number": number,
        "title": f"PR {number}",
        "headRefName": "codex/snapshot",
        "headRefOid": "a" * 40,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "body": "## Validation\n- pytest",
        "url": f"https://example.com/pr/{number}",
        "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS", "name": "tests"}],
    }


def test_select_mergeable_prs_marks_safe_codex_pr_eligible() -> None:
    decisions = select_mergeable_prs([_pr(1)])

    decision = _decision(decisions, 1)
    assert decision.eligible is True
    assert decision.reason == "eligible"
    assert decision.head_sha == "a" * 40


@pytest.mark.parametrize("head_sha", ["", "a" * 39, "A" * 40, "not-a-sha"])
def test_select_mergeable_prs_rejects_missing_or_malformed_head(head_sha: str) -> None:
    decision = _decision(select_mergeable_prs([_pr(1, head_sha=head_sha)]), 1)

    assert decision.eligible is False
    assert decision.reason == "invalid_head_sha"


def test_select_mergeable_prs_skips_non_codex_draft_and_missing_validation() -> None:
    decisions = select_mergeable_prs(
        [
            _pr(1, head_ref="feature/not-codex"),
            _pr(2, is_draft=True),
            _pr(3, body="No evidence here"),
        ]
    )

    assert _decision(decisions, 1).reason == "not_codex_branch"
    assert _decision(decisions, 2).reason == "draft"
    assert _decision(decisions, 3).reason == "missing_validation"


def test_select_mergeable_prs_skips_pending_and_failed_checks() -> None:
    decisions = select_mergeable_prs(
        [
            _pr(1, status_rollup=[{"status": "IN_PROGRESS", "conclusion": "", "name": "tests"}]),
            _pr(
                2, status_rollup=[{"status": "COMPLETED", "conclusion": "FAILURE", "name": "tests"}]
            ),
        ]
    )

    assert _decision(decisions, 1).reason == "checks_pending"
    assert _decision(decisions, 2).reason == "checks_failed"


def test_select_mergeable_prs_skips_sensitive_and_large_changes() -> None:
    decisions = select_mergeable_prs(
        [
            _pr(1, changed_files=["aragora/billing/auth/config.py"]),
            _pr(2, changed_files=[f"aragora/file_{idx}.py" for idx in range(7)]),
        ]
    )

    assert _decision(decisions, 1).reason == "sensitive_paths"
    assert _decision(decisions, 2).reason == "too_many_files"


def test_select_mergeable_prs_skips_non_mergeable_or_unchecked_prs() -> None:
    decisions = select_mergeable_prs(
        [
            _pr(1, mergeable="UNKNOWN"),
            _pr(2, status_rollup=[]),
        ]
    )

    assert _decision(decisions, 1).reason == "not_mergeable"
    assert _decision(decisions, 2).reason == "no_status_checks"


def test_collect_pull_requests_uses_one_view_snapshot_for_all_eligibility_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    head_sha = "b" * 40
    calls: list[list[str]] = []

    def fake_run(
        args: list[str], *, cwd: Path, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check
        calls.append(args)
        if args[1:3] == ["pr", "list"]:
            payload = [
                {
                    "number": 7,
                    "title": "stale discovery title",
                    "headRefName": "codex/snapshot",
                    "isDraft": True,
                    "url": "https://example.com/stale",
                }
            ]
        elif args[1:3] == ["pr", "view"]:
            payload = {
                "number": 7,
                "title": "authoritative title",
                "headRefName": "codex/snapshot",
                "headRefOid": head_sha,
                "isDraft": False,
                "mergeable": "MERGEABLE",
                "body": "## Validation\n- pytest",
                "url": "https://example.com/pr/7",
                "changedFiles": 1,
                "files": [{"path": "aragora/safe.py"}],
                "statusCheckRollup": [
                    {"status": "COMPLETED", "conclusion": "SUCCESS", "name": "tests"}
                ],
            }
        else:  # pragma: no cover - assertion gives a clearer unexpected-call failure
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(merge_codex, "_run", fake_run)

    snapshots = merge_codex.collect_pull_requests(tmp_path, "example/repo", limit=10)

    assert snapshots == [
        PullRequestSnapshot(
            number=7,
            title="authoritative title",
            head_ref="codex/snapshot",
            head_sha=head_sha,
            is_draft=False,
            mergeable="MERGEABLE",
            body="## Validation\n- pytest",
            url="https://example.com/pr/7",
            changed_files=["aragora/safe.py"],
            status_rollup=[{"status": "COMPLETED", "conclusion": "SUCCESS", "name": "tests"}],
        )
    ]
    assert [call[1:3] for call in calls] == [["pr", "list"], ["pr", "view"]]
    assert calls[0][calls[0].index("--json") + 1] == "number,headRefName"
    view_json_fields = calls[1][calls[1].index("--json") + 1].split(",")
    assert {
        "number",
        "title",
        "headRefName",
        "headRefOid",
        "isDraft",
        "mergeable",
        "body",
        "url",
        "changedFiles",
        "statusCheckRollup",
        "files",
    }.issubset(view_json_fields)


def test_collect_pull_requests_rejects_mismatched_snapshot_number(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(
        args: list[str], *, cwd: Path, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check
        payload: object
        if args[1:3] == ["pr", "list"]:
            payload = [{"number": 7, "headRefName": "codex/snapshot"}]
        else:
            payload = {"number": 8}
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(merge_codex, "_run", fake_run)

    with pytest.raises(RuntimeError, match="requested #7, got #8"):
        merge_codex.collect_pull_requests(tmp_path, "example/repo", limit=10)


@pytest.mark.parametrize(
    ("changed_file_count", "returned_file_count"),
    [
        (101, 100),
        (2, 1),
        (None, 1),
        (True, 1),
        ("1", 1),
        (-1, 0),
    ],
)
def test_collect_pull_requests_rejects_incomplete_or_malformed_files_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    changed_file_count: object,
    returned_file_count: int,
) -> None:
    def fake_run(
        args: list[str], *, cwd: Path, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check
        if args[1:3] == ["pr", "list"]:
            payload: object = [{"number": 7, "headRefName": "codex/snapshot"}]
        else:
            payload = {
                **_snapshot_metadata(),
                "changedFiles": changed_file_count,
                "files": [
                    {"path": f"aragora/file_{index}.py"} for index in range(returned_file_count)
                ],
            }
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(merge_codex, "_run", fake_run)

    snapshots = merge_codex.collect_pull_requests(tmp_path, "example/repo", limit=10)

    assert "incomplete or malformed files snapshot" in str(snapshots[0].files_snapshot_error)
    assert _decision(select_mergeable_prs(snapshots), 7).reason == "files_snapshot_incomplete"


def test_collect_pull_requests_compares_changed_count_with_raw_file_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(
        args: list[str], *, cwd: Path, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check
        if args[1:3] == ["pr", "list"]:
            payload: object = [{"number": 7, "headRefName": "codex/snapshot"}]
        else:
            payload = {
                **_snapshot_metadata(),
                "changedFiles": 1,
                "files": [{"path": "aragora/safe.py"}, {}],
            }
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(merge_codex, "_run", fake_run)

    snapshots = merge_codex.collect_pull_requests(tmp_path, "example/repo", limit=10)

    assert "returned_entries=2" in str(snapshots[0].files_snapshot_error)
    assert _decision(select_mergeable_prs(snapshots), 7).reason == "files_snapshot_incomplete"


@pytest.mark.parametrize(
    "file_entry",
    [
        pytest.param(None, id="null-entry"),
        pytest.param([], id="list-entry"),
        pytest.param("aragora/safe.py", id="string-entry"),
        pytest.param({}, id="missing-path"),
        pytest.param({"path": None}, id="null-path"),
        pytest.param({"path": 7}, id="non-string-path"),
        pytest.param({"path": ""}, id="empty-path"),
        pytest.param({"path": "   "}, id="whitespace-path"),
    ],
)
def test_collect_pull_requests_rejects_malformed_file_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    file_entry: object,
) -> None:
    def fake_run(
        args: list[str], *, cwd: Path, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check
        if args[1:3] == ["pr", "list"]:
            payload: object = [{"number": 7, "headRefName": "codex/snapshot"}]
        else:
            payload = {
                **_snapshot_metadata(),
                "changedFiles": 1,
                "files": [file_entry],
            }
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(merge_codex, "_run", fake_run)

    snapshots = merge_codex.collect_pull_requests(tmp_path, "example/repo", limit=10)

    assert "malformed file entry" in str(snapshots[0].files_snapshot_error)
    assert _decision(select_mergeable_prs(snapshots), 7).reason == "files_snapshot_incomplete"


@pytest.mark.parametrize(
    ("include_files", "files_payload"),
    [
        (False, None),
        (True, None),
        (True, {}),
    ],
)
def test_collect_pull_requests_rejects_missing_or_non_list_files_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    include_files: bool,
    files_payload: object,
) -> None:
    def fake_run(
        args: list[str], *, cwd: Path, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check
        if args[1:3] == ["pr", "list"]:
            payload: object = [{"number": 7, "headRefName": "codex/snapshot"}]
        else:
            metadata = {**_snapshot_metadata(), "changedFiles": 0}
            if include_files:
                metadata["files"] = files_payload
            payload = metadata
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(merge_codex, "_run", fake_run)

    snapshots = merge_codex.collect_pull_requests(tmp_path, "example/repo", limit=10)

    assert "unexpected files payload" in str(snapshots[0].files_snapshot_error)
    assert _decision(select_mergeable_prs(snapshots), 7).reason == "files_snapshot_incomplete"


def test_malformed_file_snapshot_does_not_hide_later_eligible_pr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(
        args: list[str], *, cwd: Path, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check
        if args[1:3] == ["pr", "list"]:
            payload: object = [
                {"number": 7, "headRefName": "codex/truncated"},
                {"number": 8, "headRefName": "codex/safe"},
            ]
        else:
            number = int(args[3])
            payload = {
                "number": number,
                "title": f"PR {number}",
                "headRefName": "codex/truncated" if number == 7 else "codex/safe",
                "headRefOid": ("a" if number == 7 else "b") * 40,
                "isDraft": False,
                "mergeable": "MERGEABLE",
                "body": "## Validation\n- pytest",
                "url": f"https://example.com/pr/{number}",
                "changedFiles": 101 if number == 7 else 1,
                "files": (
                    [{"path": f"aragora/file_{index}.py"} for index in range(100)]
                    if number == 7
                    else [{"path": "aragora/safe.py"}]
                ),
                "statusCheckRollup": [
                    {"status": "COMPLETED", "conclusion": "SUCCESS", "name": "tests"}
                ],
            }
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(merge_codex, "_run", fake_run)

    decisions = select_mergeable_prs(
        merge_codex.collect_pull_requests(tmp_path, "example/repo", limit=10)
    )

    assert _decision(decisions, 7).reason == "files_snapshot_incomplete"
    assert _decision(decisions, 8).eligible is True


def test_collect_pull_requests_accepts_complete_empty_snapshot_as_not_mergeable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    head_sha = "c" * 40

    def fake_run(
        args: list[str], *, cwd: Path, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check
        if args[1:3] == ["pr", "list"]:
            payload: object = [{"number": 7, "headRefName": "codex/empty"}]
        else:
            payload = {
                "number": 7,
                "title": "Empty snapshot",
                "headRefName": "codex/empty",
                "headRefOid": head_sha,
                "isDraft": False,
                "mergeable": "MERGEABLE",
                "body": "## Validation\n- pytest",
                "url": "https://example.com/pr/7",
                "changedFiles": 0,
                "files": [],
                "statusCheckRollup": [
                    {"status": "COMPLETED", "conclusion": "SUCCESS", "name": "tests"}
                ],
            }
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(merge_codex, "_run", fake_run)

    snapshots = merge_codex.collect_pull_requests(tmp_path, "example/repo", limit=10)
    decision = _decision(select_mergeable_prs(snapshots), 7)

    assert snapshots[0].changed_files == []
    assert decision.eligible is False
    assert decision.reason == "no_changed_files"


@pytest.mark.parametrize("head_sha", ["", "c" * 39, "C" * 40])
def test_merge_pr_rejects_invalid_head_before_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, head_sha: str
) -> None:
    def unexpected_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("merge subprocess must not run")

    monkeypatch.setattr(merge_codex, "_run", unexpected_run)

    with pytest.raises(RuntimeError, match="missing or malformed head SHA"):
        merge_codex._merge_pr(tmp_path, "example/repo", 7, head_sha)


def test_merge_pr_pins_admin_merge_to_decision_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    head_sha = "d" * 40
    calls: list[list[str]] = []

    def fake_run(
        args: list[str], *, cwd: Path, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(merge_codex, "_run", fake_run)

    merge_codex._merge_pr(tmp_path, "example/repo", 7, head_sha)

    assert len(calls) == 1
    assert calls[0][1:4] == ["pr", "merge", "7"]
    match_index = calls[0].index("--match-head-commit")
    assert calls[0][match_index + 1] == head_sha
