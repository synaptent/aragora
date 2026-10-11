from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aragora.ralph.github_control import GitHubControl, GitHubControlError

_HEAD_SHA = "a" * 40
_PIN = ["--match-head-commit", _HEAD_SHA]


def _completed_process(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
):
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


class TestGitHubControlBranchDiscovery:
    @patch("aragora.ralph.github_control.subprocess.run")
    def test_find_pr_for_branch_returns_url(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = _completed_process(
            stdout=json.dumps([{"url": "https://github.com/org/repo/pull/42"}])
        )

        control = GitHubControl(repo_root=tmp_path)
        assert control.find_pr_for_branch("codex/test") == "https://github.com/org/repo/pull/42"

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_find_pr_for_branch_returns_none_when_absent(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = _completed_process(stdout="[]")

        control = GitHubControl(repo_root=tmp_path)
        assert control.find_pr_for_branch("codex/test") is None


class TestGitHubControlPRCreation:
    @patch("aragora.ralph.github_control.subprocess.run")
    def test_create_pr_for_branch_returns_url(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = _completed_process(stdout="https://github.com/org/repo/pull/77\n")

        control = GitHubControl(repo_root=tmp_path)
        pr_url = control.create_pr_for_branch("codex/test", "main")

        assert pr_url == "https://github.com/org/repo/pull/77"

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_create_pr_for_branch_raises_on_error(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = _completed_process(returncode=1, stderr="auth failed")

        control = GitHubControl(repo_root=tmp_path)
        with pytest.raises(GitHubControlError, match="auth failed"):
            control.create_pr_for_branch("codex/test", "main")


class TestGitHubControlIssueComments:
    @patch("aragora.ralph.github_control.subprocess.run")
    def test_upsert_issue_comment_creates_new_comment(self, mock_run, tmp_path: Path) -> None:
        mock_run.side_effect = [
            _completed_process(stdout=json.dumps([])),
            _completed_process(
                stdout=json.dumps(
                    {
                        "id": 91,
                        "html_url": "https://github.com/org/repo/issues/42#issuecomment-91",
                    }
                )
            ),
        ]

        control = GitHubControl(repo_root=tmp_path)
        result = control.upsert_issue_comment(
            repo="org/repo",
            issue_number=42,
            body="Boss loop published a PR.",
            marker="<!-- aragora-boss-loop-publish -->",
        )

        assert result["commented"] is True
        assert result["action"] == "created"
        assert result["comment_id"] == 91
        create_cmd = mock_run.call_args_list[1].args[0]
        assert create_cmd[:4] == ["gh", "api", "--method", "POST"]
        assert create_cmd[4] == "repos/org/repo/issues/42/comments"
        assert any("aragora-boss-loop-publish" in arg for arg in create_cmd)

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_upsert_issue_comment_updates_existing_marker_comment(
        self, mock_run, tmp_path: Path
    ) -> None:
        mock_run.side_effect = [
            _completed_process(
                stdout=json.dumps(
                    [
                        {
                            "id": 77,
                            "body": "Prior update\n\n<!-- aragora-boss-loop-publish -->",
                            "html_url": "https://github.com/org/repo/issues/42#issuecomment-77",
                        }
                    ]
                )
            ),
            _completed_process(
                stdout=json.dumps(
                    {
                        "id": 77,
                        "html_url": "https://github.com/org/repo/issues/42#issuecomment-77",
                    }
                )
            ),
        ]

        control = GitHubControl(repo_root=tmp_path)
        result = control.upsert_issue_comment(
            repo="org/repo",
            issue_number=42,
            body="Boss loop reused the existing PR.",
            marker="<!-- aragora-boss-loop-publish -->",
        )

        assert result["commented"] is True
        assert result["action"] == "updated"
        assert result["comment_id"] == 77
        update_cmd = mock_run.call_args_list[1].args[0]
        assert update_cmd[:4] == ["gh", "api", "--method", "PATCH"]
        assert update_cmd[4] == "repos/org/repo/issues/comments/77"

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_upsert_issue_comment_returns_failure_on_create_error(
        self, mock_run, tmp_path: Path
    ) -> None:
        mock_run.side_effect = [
            _completed_process(stdout=json.dumps([])),
            _completed_process(returncode=1, stderr="comment write failed"),
        ]

        control = GitHubControl(repo_root=tmp_path)
        result = control.upsert_issue_comment(
            repo="org/repo",
            issue_number=42,
            body="Boss loop published a PR.",
            marker="<!-- aragora-boss-loop-publish -->",
        )

        assert result["commented"] is False
        assert result["action"] == "comment_failed"
        assert "comment write failed" in result["detail"]


class TestGitHubControlGateSnapshots:
    @patch("aragora.ralph.github_control.subprocess.run")
    def test_fetch_gate_snapshot_detects_merged_pr(self, mock_run, tmp_path: Path) -> None:
        mock_run.side_effect = [
            _completed_process(
                stdout=json.dumps(
                    {
                        "url": "https://github.com/org/repo/pull/55",
                        "state": "MERGED",
                        "isDraft": False,
                        "headRefName": "codex/test",
                        "headRefOid": _HEAD_SHA,
                        "baseRefName": "main",
                        "reviewDecision": "APPROVED",
                        "mergeStateStatus": "CLEAN",
                        "mergeCommit": {"oid": "merge-sha"},
                        "statusCheckRollup": [],
                    }
                )
            ),
            _completed_process(stdout=json.dumps([])),
        ]

        control = GitHubControl(repo_root=tmp_path)
        snapshot = control.fetch_gate_snapshot("https://github.com/org/repo/pull/55")

        assert snapshot.disposition == "merged"
        assert snapshot.merge_commit_sha == "merge-sha"
        assert snapshot.head_sha == _HEAD_SHA
        assert snapshot.to_dict()["head_sha"] == _HEAD_SHA
        view_argv = mock_run.call_args_list[0].args[0]
        assert "headRefOid" in view_argv[view_argv.index("--json") + 1].split(",")

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_fetch_gate_snapshot_waits_for_review(self, mock_run, tmp_path: Path) -> None:
        mock_run.side_effect = [
            _completed_process(
                stdout=json.dumps(
                    {
                        "url": "https://github.com/org/repo/pull/55",
                        "state": "OPEN",
                        "isDraft": False,
                        "headRefName": "codex/test",
                        "baseRefName": "main",
                        "reviewDecision": "REVIEW_REQUIRED",
                        "mergeStateStatus": "BLOCKED",
                        "mergeCommit": None,
                        "statusCheckRollup": [],
                    }
                )
            ),
            _completed_process(stdout=json.dumps([])),
        ]

        control = GitHubControl(repo_root=tmp_path)
        snapshot = control.fetch_gate_snapshot("https://github.com/org/repo/pull/55")

        assert snapshot.disposition == "wait_for_review"

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_fetch_gate_snapshot_waits_for_required_checks(self, mock_run, tmp_path: Path) -> None:
        mock_run.side_effect = [
            _completed_process(
                stdout=json.dumps(
                    {
                        "url": "https://github.com/org/repo/pull/55",
                        "state": "OPEN",
                        "isDraft": False,
                        "headRefName": "codex/test",
                        "baseRefName": "main",
                        "reviewDecision": "APPROVED",
                        "mergeStateStatus": "BLOCKED",
                        "mergeCommit": None,
                        "statusCheckRollup": [
                            {"context": "ci/unit", "state": "PENDING"},
                            {"context": "lint", "state": "SUCCESS"},
                        ],
                    }
                )
            ),
            _completed_process(
                stdout=json.dumps(
                    [
                        {
                            "parameters": {
                                "required_status_checks": [
                                    {"context": "ci/unit"},
                                ]
                            }
                        }
                    ]
                )
            ),
        ]

        control = GitHubControl(repo_root=tmp_path)
        snapshot = control.fetch_gate_snapshot("https://github.com/org/repo/pull/55")

        assert snapshot.disposition == "wait_for_required_checks"
        assert snapshot.required_checks_green is False
        assert [check.name for check in snapshot.required_checks] == ["ci/unit"]

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_fetch_gate_snapshot_ignores_advisory_failures_when_required_green(
        self, mock_run, tmp_path: Path
    ) -> None:
        mock_run.side_effect = [
            _completed_process(
                stdout=json.dumps(
                    {
                        "url": "https://github.com/org/repo/pull/55",
                        "state": "OPEN",
                        "isDraft": False,
                        "headRefName": "codex/test",
                        "baseRefName": "main",
                        "reviewDecision": "APPROVED",
                        "mergeStateStatus": "CLEAN",
                        "mergeCommit": None,
                        "statusCheckRollup": [
                            {"context": "ci/unit", "state": "SUCCESS"},
                            {"context": "lint", "state": "FAILURE"},
                        ],
                    }
                )
            ),
            _completed_process(
                stdout=json.dumps(
                    [
                        {
                            "parameters": {
                                "required_status_checks": [
                                    {"context": "ci/unit"},
                                ]
                            }
                        }
                    ]
                )
            ),
        ]

        control = GitHubControl(repo_root=tmp_path)
        snapshot = control.fetch_gate_snapshot("https://github.com/org/repo/pull/55")

        assert snapshot.disposition == "merge_now"
        assert snapshot.required_checks_green is True
        assert [check.name for check in snapshot.advisory_checks] == ["lint"]

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_fetch_gate_snapshot_fails_closed_when_required_truth_unknown(
        self, mock_run, tmp_path: Path
    ) -> None:
        mock_run.side_effect = [
            _completed_process(
                stdout=json.dumps(
                    {
                        "url": "https://github.com/org/repo/pull/55",
                        "state": "OPEN",
                        "isDraft": False,
                        "headRefName": "codex/test",
                        "baseRefName": "main",
                        "reviewDecision": "APPROVED",
                        "mergeStateStatus": "CLEAN",
                        "mergeCommit": None,
                        "statusCheckRollup": [{"context": "ci/unit", "state": "SUCCESS"}],
                    }
                )
            ),
            _completed_process(returncode=1, stderr="rules api unavailable"),
            _completed_process(returncode=1, stderr="protection api unavailable"),
        ]

        control = GitHubControl(repo_root=tmp_path)
        snapshot = control.fetch_gate_snapshot("https://github.com/org/repo/pull/55")

        assert snapshot.disposition == "blocked_nonreviewable"
        assert snapshot.required_checks_known is False


class TestGitHubControlTaskCoverage:
    @patch("aragora.ralph.github_control.subprocess.run")
    def test_find_pr_for_branch_found(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = _completed_process(
            stdout=json.dumps([{"number": 42, "url": "https://github.com/org/repo/pull/42"}])
        )

        control = GitHubControl(repo_root=tmp_path)

        assert control.find_pr_for_branch("codex/test") == "https://github.com/org/repo/pull/42"

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_find_pr_for_branch_not_found(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = _completed_process(stdout="[]")

        control = GitHubControl(repo_root=tmp_path)

        assert control.find_pr_for_branch("codex/test") is None

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_create_pr_for_branch_success(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = _completed_process(
            stdout=json.dumps({"url": "https://github.com/org/repo/pull/77 "})
        )

        control = GitHubControl(repo_root=tmp_path)

        assert control.create_pr_for_branch("codex/test", "main") == (
            "https://github.com/org/repo/pull/77"
        )

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_create_pr_for_branch_failure(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = _completed_process(returncode=1, stderr="auth failed")

        control = GitHubControl(repo_root=tmp_path)

        with pytest.raises(GitHubControlError, match="auth failed"):
            control.create_pr_for_branch("codex/test", "main")

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_fetch_gate_snapshot_parses_rulesets(self, mock_run, tmp_path: Path) -> None:
        mock_run.side_effect = [
            _completed_process(
                stdout=json.dumps(
                    {
                        "url": "https://github.com/org/repo/pull/55",
                        "state": "OPEN",
                        "isDraft": False,
                        "headRefName": "codex/test",
                        "baseRefName": "main",
                        "reviewDecision": "APPROVED",
                        "mergeStateStatus": "BLOCKED",
                        "mergeCommit": None,
                        "statusCheckRollup": [
                            {"context": "ci/unit", "state": "SUCCESS"},
                            {"context": "lint", "state": "PENDING"},
                            {"context": "coverage", "state": "SUCCESS"},
                        ],
                    }
                )
            ),
            _completed_process(
                stdout=json.dumps(
                    [
                        {
                            "parameters": {
                                "required_status_checks": [
                                    {"context": "ci/unit"},
                                    {"context": "lint"},
                                ]
                            }
                        }
                    ]
                )
            ),
        ]

        control = GitHubControl(repo_root=tmp_path)
        snapshot = control.fetch_gate_snapshot("https://github.com/org/repo/pull/55")

        assert [check.name for check in snapshot.required_checks] == ["ci/unit", "lint"]
        assert snapshot.required_checks_source == "ruleset"
        assert snapshot.required_checks_known is True

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_fetch_gate_snapshot_draft_disposition(self, mock_run, tmp_path: Path) -> None:
        mock_run.side_effect = [
            _completed_process(
                stdout=json.dumps(
                    {
                        "url": "https://github.com/org/repo/pull/56",
                        "state": "OPEN",
                        "isDraft": True,
                        "headRefName": "codex/test",
                        "baseRefName": "main",
                        "reviewDecision": "APPROVED",
                        "mergeStateStatus": "CLEAN",
                        "mergeCommit": None,
                        "statusCheckRollup": [{"context": "ci/unit", "state": "SUCCESS"}],
                    }
                )
            ),
            _completed_process(
                stdout=json.dumps(
                    [
                        {
                            "parameters": {
                                "required_status_checks": [
                                    {"context": "ci/unit"},
                                ]
                            }
                        }
                    ]
                )
            ),
        ]

        control = GitHubControl(repo_root=tmp_path)
        snapshot = control.fetch_gate_snapshot("https://github.com/org/repo/pull/56")

        assert snapshot.draft is True
        assert snapshot.disposition == "wait_for_review"


class TestGitHubControlMerge:
    @patch("aragora.ralph.github_control.subprocess.run")
    def test_merge_pr_uses_normal_merge_first(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = _completed_process(stdout="merged")

        control = GitHubControl(repo_root=tmp_path)
        result = control.merge_pr(
            "https://github.com/org/repo/pull/88",
            required_checks_green=True,
            allow_admin=True,
            head_sha=_HEAD_SHA,
        )

        assert result.merged is True
        assert result.used_admin is False
        called = mock_run.call_args.args[0]
        assert called == [
            "gh",
            "pr",
            "merge",
            "https://github.com/org/repo/pull/88",
            "--squash",
            *_PIN,
        ]

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_merge_pr_falls_back_to_admin_when_needed(self, mock_run, tmp_path: Path) -> None:
        mock_run.side_effect = [
            _completed_process(
                returncode=1, stderr="Repository rules require administrator override"
            ),
            _completed_process(stdout="merged with admin"),
        ]

        control = GitHubControl(repo_root=tmp_path)
        result = control.merge_pr(
            "https://github.com/org/repo/pull/88",
            required_checks_green=True,
            allow_admin=True,
            head_sha=_HEAD_SHA,
        )

        assert result.merged is True
        assert result.used_admin is True
        assert mock_run.call_args_list[0].args[0][-2:] == _PIN
        assert mock_run.call_args_list[1].args[0] == [
            "gh",
            "pr",
            "merge",
            "https://github.com/org/repo/pull/88",
            "--squash",
            "--admin",
            *_PIN,
        ]

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_merge_pr_does_not_attempt_admin_without_signal(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = _completed_process(returncode=1, stderr="merge conflict")

        control = GitHubControl(repo_root=tmp_path)
        result = control.merge_pr(
            "https://github.com/org/repo/pull/88",
            required_checks_green=True,
            allow_admin=True,
            head_sha=_HEAD_SHA,
        )

        assert result.merged is False
        assert result.used_admin is False
        assert mock_run.call_count == 1

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_merge_pr_blocks_when_required_checks_not_green(self, mock_run, tmp_path: Path) -> None:
        control = GitHubControl(repo_root=tmp_path)
        result = control.merge_pr(
            "https://github.com/org/repo/pull/88",
            required_checks_green=False,
            allow_admin=True,
            head_sha=_HEAD_SHA,
        )

        assert result.merged is False
        assert result.action == "blocked"
        assert mock_run.call_count == 0

    @patch("aragora.ralph.github_control.subprocess.run")
    def test_head_change_rejection_is_not_retried_with_admin(
        self, mock_run, tmp_path: Path
    ) -> None:
        """A moved head needs a fresh gate snapshot, not an admin retry."""
        mock_run.return_value = _completed_process(
            returncode=1,
            stderr="GraphQL: Head branch was modified. Review and try the merge again.",
        )

        control = GitHubControl(repo_root=tmp_path)
        result = control.merge_pr(
            "https://github.com/org/repo/pull/88",
            required_checks_green=True,
            allow_admin=True,
            head_sha=_HEAD_SHA,
        )

        assert result.merged is False
        assert result.action == "merge_failed"
        assert mock_run.call_count == 1

    @patch("aragora.ralph.github_control.subprocess.run")
    @pytest.mark.parametrize("head_sha", [None, "", "abc123", "g" * 40, "a" * 39, "a" * 41])
    def test_merge_without_a_full_snapshot_head_is_blocked(
        self, mock_run, tmp_path: Path, head_sha: str | None
    ) -> None:
        control = GitHubControl(repo_root=tmp_path)
        with patch("aragora.ralph.github_control.evaluate_merge_halt") as halt:
            result = control.merge_pr(
                "https://github.com/org/repo/pull/88",
                required_checks_green=True,
                allow_admin=True,
                head_sha=head_sha,
            )

        assert result.merged is False
        assert result.action == "blocked"
        assert "full 40-character" in result.detail
        halt.assert_not_called()
        mock_run.assert_not_called()

    @patch("aragora.ralph.github_control.subprocess.run")
    @pytest.mark.parametrize(
        ("pr_ref", "expected"),
        [
            ("https://github.com/org/repo/pull/88", 88),
            ("https://github.com/org/repo/pull/88/files", 88),
            ("88", 88),
            ("#88", 88),
            ("feature-88", 0),
        ],
    )
    def test_halt_is_checked_for_the_pr_and_the_snapshot_head(
        self, mock_run, tmp_path: Path, pr_ref: str, expected: int
    ) -> None:
        mock_run.return_value = _completed_process(stdout="merged")
        control = GitHubControl(repo_root=tmp_path)
        with patch("aragora.ralph.github_control.evaluate_merge_halt") as halt:
            halt.return_value = MagicMock(allowed=True)
            control.merge_pr(
                pr_ref,
                required_checks_green=True,
                allow_admin=False,
                head_sha=_HEAD_SHA.upper(),
            )

        halt.assert_called_once_with(expected, _HEAD_SHA)
        assert mock_run.call_args.args[0][-2:] == _PIN
