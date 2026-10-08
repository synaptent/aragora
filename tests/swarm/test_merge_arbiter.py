"""Tests for the admin merge arbiter."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from aragora.swarm.merge_arbiter import (
    AUTOMATION_REVIEWER_LOGINS,
    REQUIRED_CHECKS,
    ArbiterOperationalError,
    ArbiterSummary,
    CheckSnapshotHeadMismatch,
    MergeArbiter,
    MergeArbiterConfig,
    MergeResult,
    _classify_required_checks,
    _evaluate_pr,
    _get_check_status,
    _has_local_settlement_receipt,
    _has_matching_human_approval,
    _is_full_head_sha,
    _list_candidate_prs,
    _review_counts_as_human_approval,
    _merge_pr,
    _promote_draft,
)

HEAD_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
STALE_HEAD_SHA = "cafebeefcafebeefcafebeefcafebeefcafebeef"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gh_result(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _all_passing_checks() -> list[dict]:
    return [{"name": name, "state": "SUCCESS"} for name in REQUIRED_CHECKS]


def _all_passing_ready_checks(*extra_names: str) -> dict[str, str]:
    names = list(REQUIRED_CHECKS) + ["Prioritize Required Checks", "Quality Gates", *extra_names]
    return dict.fromkeys(names, "SUCCESS")


def _pr(
    number: int = 1,
    branch: str = "aragora/boss-harvest/fix-1",
    draft: bool = False,
    review_decision: str = "",
) -> dict:
    return {
        "number": number,
        "headRefName": branch,
        "headRefOid": HEAD_SHA,
        "isDraft": draft,
        "reviewDecision": review_decision,
    }


# ---------------------------------------------------------------------------
# _list_candidate_prs
# ---------------------------------------------------------------------------


class TestListCandidatePrs:
    def test_default_scope_matches_real_automation_branches(self):
        prs = [
            _pr(1, "aragora/boss-harvest/fix-1"),
            _pr(2, "codex/manual-fix"),
            _pr(3, "factory/manual-fix"),
            _pr(4, "feat/manual-fix"),
        ]
        config = MergeArbiterConfig()
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result(stdout=json.dumps(prs))
            result = _list_candidate_prs(config)
        assert [pr["number"] for pr in result] == [1, 2, 3]

    def test_filters_by_prefix_and_normalizes_legacy_boss_prefix(self):
        prs = [
            _pr(1, "aragora/boss-harvest/fix-1"),
            _pr(2, "codex/task-2"),
            _pr(3, "dependabot/npm"),
            _pr(4, "feat/manual-feature"),
        ]
        config = MergeArbiterConfig(branch_prefixes=["boss-harvest", "codex"])
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result(stdout=json.dumps(prs))
            result = _list_candidate_prs(config)
        assert len(result) == 2
        assert result[0]["number"] == 1
        assert result[1]["number"] == 2

    def test_raises_operational_error_on_gh_failure(self):
        config = MergeArbiterConfig()
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result(returncode=1, stderr="error connecting")
            with pytest.raises(ArbiterOperationalError):
                _list_candidate_prs(config)

    def test_raises_operational_error_on_bad_json(self):
        config = MergeArbiterConfig()
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result(stdout="not json")
            with pytest.raises(ArbiterOperationalError):
                _list_candidate_prs(config)


# ---------------------------------------------------------------------------
# _get_check_status
# ---------------------------------------------------------------------------


class TestGetCheckStatus:
    def test_parses_check_output(self):
        checks = _all_passing_checks()
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result(
                stdout=json.dumps({"headRefOid": HEAD_SHA, "statusCheckRollup": checks})
            )
            result = _get_check_status(1, "owner/repo", HEAD_SHA)
        assert len(result) == 5
        for name in REQUIRED_CHECKS:
            assert result[name] == "SUCCESS"
        assert mock_gh.call_args.args[0][-2:] == ["--json", "headRefOid,statusCheckRollup"]

    def test_rejects_checks_from_a_different_head(self):
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result(
                stdout=json.dumps(
                    {"headRefOid": STALE_HEAD_SHA, "statusCheckRollup": _all_passing_checks()}
                )
            )
            with pytest.raises(CheckSnapshotHeadMismatch, match="head changed"):
                _get_check_status(1, "owner/repo", HEAD_SHA)

    @pytest.mark.parametrize("reverse", [False, True])
    def test_duplicate_check_rows_cannot_hide_newer_failure(self, reverse: bool):
        checks = [
            {
                "name": "lint",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "startedAt": "2026-08-30T01:00:00Z",
                "completedAt": "2026-08-30T01:01:00Z",
            },
            {
                "name": "lint",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "startedAt": "2026-08-30T02:00:00Z",
                "completedAt": "2026-08-30T02:01:00Z",
            },
        ]
        if reverse:
            checks.reverse()
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result(
                stdout=json.dumps({"headRefOid": HEAD_SHA, "statusCheckRollup": checks})
            )
            assert _get_check_status(1, "owner/repo", HEAD_SHA)["lint"] == "FAILURE"

    def test_raises_operational_error_on_failure_without_json(self):
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result(returncode=1)
            with pytest.raises(ArbiterOperationalError):
                _get_check_status(1, "owner/repo", HEAD_SHA)


class TestHumanSettlement:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (HEAD_SHA, True),
            (None, False),
            ("", False),
            ("deadbeef", False),
            (HEAD_SHA.upper(), False),
            (f" {HEAD_SHA}", False),
            ("g" * 40, False),
        ],
    )
    def test_full_head_sha_validation(self, value, expected):
        assert _is_full_head_sha(value) is expected

    def test_review_counts_as_human_approval(self):
        review = {
            "state": "APPROVED",
            "commit_id": HEAD_SHA,
            "user": {"login": "armand", "type": "User"},
        }
        assert _review_counts_as_human_approval(review, HEAD_SHA) is True

    def test_review_rejects_automation_logins_and_stale_heads(self):
        bot_login = next(iter(AUTOMATION_REVIEWER_LOGINS))
        bot_review = {
            "state": "APPROVED",
            "commit_id": HEAD_SHA,
            "user": {"login": bot_login, "type": "User"},
        }
        stale_review = {
            "state": "APPROVED",
            "commit_id": STALE_HEAD_SHA,
            "user": {"login": "armand", "type": "User"},
        }
        assert _review_counts_as_human_approval(bot_review, HEAD_SHA) is False
        assert _review_counts_as_human_approval(stale_review, HEAD_SHA) is False

    @pytest.mark.parametrize("head_sha", [None, "", "deadbeef", "D" * 40])
    def test_invalid_head_cannot_count_human_approval(self, head_sha):
        review = {
            "state": "APPROVED",
            "commit_id": HEAD_SHA,
            "user": {"login": "armand", "type": "User"},
        }
        with patch("aragora.swarm.merge_arbiter._list_pr_reviews") as list_reviews:
            assert _has_matching_human_approval(12, "owner/repo", head_sha) is False
        list_reviews.assert_not_called()
        assert _review_counts_as_human_approval(review, head_sha) is False

    def test_has_matching_human_approval_scans_reviews(self):
        reviews = [
            {
                "state": "COMMENTED",
                "commit_id": HEAD_SHA,
                "user": {"login": "armand", "type": "User"},
            },
            {
                "state": "APPROVED",
                "commit_id": HEAD_SHA,
                "user": {"login": "armand", "type": "User"},
            },
        ]
        with patch("aragora.swarm.merge_arbiter._list_pr_reviews", return_value=reviews):
            assert _has_matching_human_approval(12, "owner/repo", HEAD_SHA) is True

    def test_has_local_settlement_receipt_matches_head_sha(self, tmp_path):
        root = tmp_path / ".aragora" / "review-queue" / "settlements"
        root.mkdir(parents=True)
        receipt = root / f"pr-12-{HEAD_SHA[:12]}-approve.json"
        receipt.write_text(
            json.dumps({"action": "approve", "head_sha": HEAD_SHA}),
            encoding="utf-8",
        )
        assert _has_local_settlement_receipt(12, HEAD_SHA, repo_root=tmp_path) is True

    @pytest.mark.parametrize("head_sha", [None, "", "deadbeef", "D" * 40])
    def test_invalid_head_cannot_match_local_receipt(self, tmp_path, head_sha):
        root = tmp_path / ".aragora" / "review-queue" / "settlements"
        root.mkdir(parents=True)
        (root / f"pr-12-{HEAD_SHA[:12]}-approve.json").write_text(
            json.dumps({"action": "approve", "head_sha": HEAD_SHA}),
            encoding="utf-8",
        )
        assert _has_local_settlement_receipt(12, head_sha, repo_root=tmp_path) is False


class TestClassifyRequiredChecks:
    def test_reports_missing_and_failing_required_checks(self):
        checks = {
            REQUIRED_CHECKS[0]: "SUCCESS",
            REQUIRED_CHECKS[1]: "FAILURE",
            REQUIRED_CHECKS[2]: "SUCCESS",
        }

        missing, failing = _classify_required_checks(checks)

        assert missing == REQUIRED_CHECKS[3:]
        assert failing == [f"{REQUIRED_CHECKS[1]}=FAILURE"]

    def test_accepts_custom_required_checks(self):
        missing, failing = _classify_required_checks(
            {"custom-a": "SUCCESS", "custom-b": "PENDING"},
            required_checks=["custom-a", "custom-b", "custom-c"],
        )

        assert missing == ["custom-c"]
        assert failing == ["custom-b=PENDING"]


# ---------------------------------------------------------------------------
# _promote_draft
# ---------------------------------------------------------------------------


class TestPromoteDraft:
    def test_marks_pr_ready(self):
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result()
            assert _promote_draft(5, "owner/repo") is True
        mock_gh.assert_called_once_with(
            ["pr", "ready", "5", "--repo", "owner/repo"],
            timeout=30.0,
            write_op=True,
        )


# ---------------------------------------------------------------------------
# _merge_pr
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _merge_pr
# ---------------------------------------------------------------------------


class TestMergePr:
    def test_pins_merge_to_reviewed_head_commit(self):
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result()
            success, reason = _merge_pr(
                12,
                "owner/repo",
                HEAD_SHA,
            )
        assert success is True
        assert reason == "merged"
        mock_gh.assert_called_once_with(
            [
                "pr",
                "merge",
                "12",
                "--repo",
                "owner/repo",
                "--admin",
                "--squash",
                "--delete-branch",
                "--match-head-commit",
                HEAD_SHA,
            ],
            write_op=True,
        )

    @pytest.mark.parametrize("head_sha", [None, "", "deadbeef", "D" * 40, "g" * 40])
    def test_missing_or_malformed_head_blocks_before_merge_subprocess(self, head_sha):
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            success, reason = _merge_pr(12, "owner/repo", head_sha)
        assert success is False
        assert reason == "missing or malformed full head SHA"
        mock_gh.assert_not_called()

    def test_changed_head_failure_does_not_retry_or_re_resolve(self):
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result(
                returncode=1,
                stderr="pull request head branch was modified",
            )
            success, reason = _merge_pr(12, "owner/repo", HEAD_SHA)
        assert success is False
        assert reason == "pull request head branch was modified"
        mock_gh.assert_called_once()
        assert mock_gh.call_args.args[0][-2:] == ["--match-head-commit", HEAD_SHA]


# ---------------------------------------------------------------------------
# _evaluate_pr — all checks passing → merge
# ---------------------------------------------------------------------------


class TestEvaluatePrAllPassing:
    def test_merges_ready_pr_when_required_and_full_suite_checks_pass(self):
        config = MergeArbiterConfig()
        checks = _all_passing_ready_checks("Status Doc Reconciliation")
        pr = _pr(42, "codex/ok", review_decision="APPROVED")
        with (
            patch(
                "aragora.swarm.merge_arbiter._get_required_checks",
                return_value=list(REQUIRED_CHECKS),
            ),
            patch("aragora.swarm.merge_arbiter._get_check_status") as mock_checks,
            patch(
                "aragora.swarm.merge_arbiter._has_local_settlement_receipt",
                return_value=False,
            ) as mock_receipt,
            patch(
                "aragora.swarm.merge_arbiter._has_matching_human_approval",
                return_value=True,
            ) as mock_approval,
            patch("aragora.swarm.merge_arbiter._merge_pr") as mock_merge,
        ):
            mock_checks.return_value = checks
            mock_merge.return_value = (True, "merged")
            result = _evaluate_pr(pr, config)
        assert result.success is True
        assert result.pr_number == 42
        mock_checks.assert_called_once_with(42, config.repo, HEAD_SHA)
        mock_receipt.assert_called_once_with(42, HEAD_SHA)
        mock_approval.assert_called_once_with(42, config.repo, HEAD_SHA)
        mock_merge.assert_called_once_with(42, config.repo, pr["headRefOid"])

    @pytest.mark.parametrize("head_sha", [None, "", "deadbeef", "D" * 40])
    def test_missing_or_malformed_snapshot_head_fails_before_gate_or_merge_calls(self, head_sha):
        config = MergeArbiterConfig()
        pr = _pr(42, "codex/bad-head", review_decision="APPROVED")
        pr["headRefOid"] = head_sha
        with (
            patch("aragora.swarm.merge_arbiter._get_required_checks") as required_checks,
            patch("aragora.swarm.merge_arbiter._get_check_status") as check_status,
            patch("aragora.swarm.merge_arbiter._has_local_settlement_receipt") as receipt,
            patch("aragora.swarm.merge_arbiter._has_matching_human_approval") as approval,
            patch("aragora.swarm.merge_arbiter._merge_pr") as merge_pr,
        ):
            result = _evaluate_pr(pr, config)
        assert result.success is False
        assert result.reason == "missing or malformed full head SHA in PR snapshot"
        required_checks.assert_not_called()
        check_status.assert_not_called()
        receipt.assert_not_called()
        approval.assert_not_called()
        merge_pr.assert_not_called()

    def test_changed_check_snapshot_head_blocks_before_settlement_or_merge(self):
        config = MergeArbiterConfig()
        pr = _pr(42, "codex/head-drift", review_decision="APPROVED")
        with (
            patch(
                "aragora.swarm.merge_arbiter._get_required_checks",
                return_value=list(REQUIRED_CHECKS),
            ),
            patch(
                "aragora.swarm.merge_arbiter._get_check_status",
                side_effect=CheckSnapshotHeadMismatch(
                    f"check snapshot head changed: expected {HEAD_SHA}, got {STALE_HEAD_SHA}"
                ),
            ) as check_status,
            patch("aragora.swarm.merge_arbiter._has_local_settlement_receipt") as receipt,
            patch("aragora.swarm.merge_arbiter._has_matching_human_approval") as approval,
            patch("aragora.swarm.merge_arbiter._merge_pr") as merge_pr,
        ):
            result = _evaluate_pr(pr, config)
        assert result.success is False
        assert "check snapshot head changed" in result.reason
        check_status.assert_called_once_with(42, config.repo, HEAD_SHA)
        receipt.assert_not_called()
        approval.assert_not_called()
        merge_pr.assert_not_called()


# ---------------------------------------------------------------------------
# _evaluate_pr — failing check → skipped
# ---------------------------------------------------------------------------


class TestEvaluatePrFailingCheck:
    def test_skips_when_check_fails(self):
        config = MergeArbiterConfig()
        status = _all_passing_ready_checks()
        status["lint"] = "FAILURE"
        with (
            patch(
                "aragora.swarm.merge_arbiter._get_required_checks",
                return_value=list(REQUIRED_CHECKS),
            ),
            patch("aragora.swarm.merge_arbiter._get_check_status") as mock_checks,
        ):
            mock_checks.return_value = status
            result = _evaluate_pr(_pr(10, "codex/bad"), config)
        assert result.success is False
        assert "failing" in result.reason
        assert "lint" in result.reason

    def test_skips_when_check_missing(self):
        config = MergeArbiterConfig()
        status = dict.fromkeys(REQUIRED_CHECKS[:4], "SUCCESS")
        with (
            patch(
                "aragora.swarm.merge_arbiter._get_required_checks",
                return_value=list(REQUIRED_CHECKS),
            ),
            patch("aragora.swarm.merge_arbiter._get_check_status") as mock_checks,
        ):
            mock_checks.return_value = status
            result = _evaluate_pr(_pr(11, "codex/partial"), config)
        assert result.success is False
        assert "missing required" in result.reason

    def test_ready_pr_waits_for_full_suite_signal(self):
        config = MergeArbiterConfig()
        status = dict.fromkeys([*REQUIRED_CHECKS, "Prioritize Required Checks"], "SUCCESS")
        with (
            patch(
                "aragora.swarm.merge_arbiter._get_required_checks",
                return_value=list(REQUIRED_CHECKS),
            ),
            patch("aragora.swarm.merge_arbiter._get_check_status", return_value=status),
        ):
            result = _evaluate_pr(_pr(12, "codex/reduced"), config)
        assert result.success is False
        assert "reduced fast-lane checks" in result.reason

    def test_ready_pr_blocks_on_failing_full_suite_check(self):
        config = MergeArbiterConfig()
        status = _all_passing_ready_checks("Status Doc Reconciliation")
        status["Quality Gates"] = "FAILURE"
        with (
            patch(
                "aragora.swarm.merge_arbiter._get_required_checks",
                return_value=list(REQUIRED_CHECKS),
            ),
            patch("aragora.swarm.merge_arbiter._get_check_status", return_value=status),
        ):
            result = _evaluate_pr(_pr(13, "codex/full-suite-fail"), config)
        assert result.success is False
        assert "failing full-suite checks" in result.reason
        assert "Quality Gates=FAILURE" in result.reason

    def test_ready_pr_waits_for_explicit_human_settlement(self):
        config = MergeArbiterConfig()
        status = _all_passing_ready_checks("Status Doc Reconciliation")
        with (
            patch(
                "aragora.swarm.merge_arbiter._get_required_checks",
                return_value=list(REQUIRED_CHECKS),
            ),
            patch("aragora.swarm.merge_arbiter._get_check_status", return_value=status),
            patch(
                "aragora.swarm.merge_arbiter._has_local_settlement_receipt",
                return_value=False,
            ),
            patch(
                "aragora.swarm.merge_arbiter._has_matching_human_approval",
                return_value=False,
            ),
        ):
            result = _evaluate_pr(_pr(14, "codex/waiting"), config)
        assert result.success is False
        assert "explicit human settlement" in result.reason


# ---------------------------------------------------------------------------
# _evaluate_pr — dry-run mode
# ---------------------------------------------------------------------------


class TestEvaluatePrDryRun:
    def test_dry_run_does_not_merge(self):
        config = MergeArbiterConfig(dry_run=True)
        checks = _all_passing_ready_checks("Status Doc Reconciliation")
        with (
            patch(
                "aragora.swarm.merge_arbiter._get_required_checks",
                return_value=list(REQUIRED_CHECKS),
            ),
            patch("aragora.swarm.merge_arbiter._get_check_status") as mock_checks,
            patch(
                "aragora.swarm.merge_arbiter._has_matching_human_approval",
                return_value=True,
            ),
            patch("aragora.swarm.merge_arbiter._merge_pr") as mock_merge,
        ):
            mock_checks.return_value = checks
            result = _evaluate_pr(_pr(99, "codex/dry", review_decision="APPROVED"), config)
        assert result.success is True
        assert "dry-run" in result.reason
        mock_merge.assert_not_called()


# ---------------------------------------------------------------------------
# _evaluate_pr — draft promotion
# ---------------------------------------------------------------------------


class TestEvaluatePrDraft:
    def test_draft_pr_with_no_checks_skipped(self):
        config = MergeArbiterConfig()
        with (
            patch(
                "aragora.swarm.merge_arbiter._get_required_checks",
                return_value=list(REQUIRED_CHECKS),
            ),
            patch("aragora.swarm.merge_arbiter._get_check_status", return_value={}),
        ):
            result = _evaluate_pr(_pr(5, "codex/draft", draft=True), config)
        assert result.success is False
        assert "never auto-merged" in result.reason

    def test_draft_pr_is_not_auto_promoted_or_merged_when_checks_pass(self):
        config = MergeArbiterConfig()
        checks = dict.fromkeys(REQUIRED_CHECKS, "SUCCESS")
        with (
            patch(
                "aragora.swarm.merge_arbiter._get_required_checks",
                return_value=list(REQUIRED_CHECKS),
            ),
            patch("aragora.swarm.merge_arbiter._get_check_status", return_value=checks),
            patch("aragora.swarm.merge_arbiter._promote_draft", return_value=True) as promote_draft,
            patch(
                "aragora.swarm.merge_arbiter._merge_pr", return_value=(True, "merged")
            ) as merge_pr,
        ):
            result = _evaluate_pr(_pr(5, "codex/draft", draft=True), config)
        assert result.success is False
        assert "waiting for boss-loop promotion" in result.reason
        promote_draft.assert_not_called()
        merge_pr.assert_not_called()


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_not_ready_prs_never_trip_the_breaker(self):
        # A queue of PRs with failing required checks (the common all-red state,
        # incl. PRs waiting on the quorum check) must NOT stop the engine — else
        # the arbiter would stop before posting the evidence that turns them green.
        config = MergeArbiterConfig(
            max_consecutive_failures=3,
            poll_interval_seconds=0.001,
            max_runtime_hours=0.0002,  # ~0.7s of polling
        )
        arbiter = MergeArbiter(config=config)

        failing_pr = _pr(1, "codex/fail")
        failing_checks = _all_passing_ready_checks()
        failing_checks["lint"] = "FAILURE"

        with (
            patch(
                "aragora.swarm.merge_arbiter._list_candidate_prs",
                return_value=[failing_pr],
            ),
            patch(
                "aragora.swarm.merge_arbiter._get_required_checks",
                return_value=list(REQUIRED_CHECKS),
            ),
            patch("aragora.swarm.merge_arbiter._get_check_status", return_value=failing_checks),
        ):
            summary = await arbiter.run()

        assert "circuit breaker" not in summary.stop_reason
        assert summary.stop_reason == "max runtime reached"
        assert summary.merged == []
        assert 1 in summary.failed  # recorded for reporting, but did not stop the engine

    @pytest.mark.asyncio
    async def test_consecutive_operational_faults_trip_the_breaker(self):
        # Genuine operational faults (cannot list PRs) SHOULD fail closed.
        config = MergeArbiterConfig(
            max_consecutive_failures=3,
            poll_interval_seconds=0.001,
            max_runtime_hours=1.0,  # long; breaker should stop us well before this
        )
        arbiter = MergeArbiter(config=config)

        with patch(
            "aragora.swarm.merge_arbiter._list_candidate_prs",
            side_effect=ArbiterOperationalError("gh pr list failed: error connecting"),
        ):
            summary = await arbiter.run()

        assert "operational faults" in summary.stop_reason
        assert summary.polls == 3

    @pytest.mark.asyncio
    async def test_systemic_evaluation_faults_trip_the_breaker(self):
        # Every evaluation faulting (e.g. gh auth death mid-run) is systemic
        # and SHOULD fail closed, even though listing still works.
        config = MergeArbiterConfig(
            max_consecutive_failures=3,
            poll_interval_seconds=0.001,
            max_runtime_hours=1.0,
        )
        arbiter = MergeArbiter(config=config)

        with (
            patch(
                "aragora.swarm.merge_arbiter._list_candidate_prs",
                return_value=[_pr(1, "codex/poison")],
            ),
            patch(
                "aragora.swarm.merge_arbiter._evaluate_pr",
                side_effect=ArbiterOperationalError("gh pr checks failed for #1: timeout"),
            ),
        ):
            summary = await arbiter.run()

        assert "operational faults" in summary.stop_reason
        assert summary.polls == 3

    @pytest.mark.asyncio
    async def test_single_poison_pill_pr_does_not_halt_the_arbiter(self):
        # One PR that faults on every evaluation must not stop the engine while
        # the rest of the queue evaluates cleanly.
        config = MergeArbiterConfig(
            max_consecutive_failures=3,
            poll_interval_seconds=0.001,
            max_runtime_hours=0.0002,  # ~0.7s of polling
        )
        arbiter = MergeArbiter(config=config)

        poison = _pr(1, "codex/poison")
        healthy = _pr(2, "codex/healthy")
        failing_checks = _all_passing_ready_checks()
        failing_checks["lint"] = "FAILURE"

        def evaluate(pr, _config):
            if pr["number"] == 1:
                raise ArbiterOperationalError("gh pr checks failed for #1: timeout")
            return MergeResult(2, "codex/healthy", False, "failing required checks: lint")

        with (
            patch(
                "aragora.swarm.merge_arbiter._list_candidate_prs",
                return_value=[poison, healthy],
            ),
            patch("aragora.swarm.merge_arbiter._evaluate_pr", side_effect=evaluate),
        ):
            summary = await arbiter.run()

        assert "circuit breaker" not in summary.stop_reason
        assert summary.stop_reason == "max runtime reached"
        assert 2 in summary.failed
        assert summary.polls >= config.max_consecutive_failures


class TestGetCheckStatusFaults:
    def test_raises_operational_error_when_gh_fails_without_json(self):
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result(returncode=1, stdout="", stderr="auth dead")
            with pytest.raises(ArbiterOperationalError):
                _get_check_status(1, "owner/repo", HEAD_SHA)

    def test_parses_status_context_and_check_run_shapes(self):
        payload = json.dumps(
            {
                "headRefOid": HEAD_SHA,
                "statusCheckRollup": [
                    {"context": "lint", "state": "failure"},
                    {"name": "typecheck", "status": "COMPLETED", "conclusion": "success"},
                ],
            }
        )
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result(stdout=payload)
            assert _get_check_status(1, "owner/repo", HEAD_SHA) == {
                "lint": "FAILURE",
                "typecheck": "SUCCESS",
            }

    def test_zero_exit_without_checks_is_not_a_fault(self):
        with patch("aragora.swarm.merge_arbiter._run_gh") as mock_gh:
            mock_gh.return_value = _make_gh_result(
                stdout=json.dumps({"headRefOid": HEAD_SHA, "statusCheckRollup": []})
            )
            assert _get_check_status(1, "owner/repo", HEAD_SHA) == {}


# ---------------------------------------------------------------------------
# ArbiterSummary
# ---------------------------------------------------------------------------


class TestArbiterSummary:
    def test_to_dict_roundtrip(self):
        summary = ArbiterSummary(
            merged=[1, 2],
            skipped=[3],
            failed=[4],
            polls=5,
            stop_reason="done",
            elapsed_seconds=123.456,
        )
        d = summary.to_dict()
        assert d["merged"] == [1, 2]
        assert d["elapsed_seconds"] == 123.5
        assert d["stop_reason"] == "done"


# ---------------------------------------------------------------------------
# Full run with merges
# ---------------------------------------------------------------------------


class TestFullRun:
    @pytest.mark.asyncio
    async def test_merges_eligible_pr(self):
        config = MergeArbiterConfig(
            poll_interval_seconds=0.01,
            max_runtime_hours=0.0001,  # Very short — exits after 1 poll
        )
        arbiter = MergeArbiter(config=config)

        pr = _pr(7, "codex/good", review_decision="APPROVED")
        checks = _all_passing_ready_checks("Status Doc Reconciliation")

        with (
            patch("aragora.swarm.merge_arbiter._list_candidate_prs", return_value=[pr]),
            patch(
                "aragora.swarm.merge_arbiter._get_required_checks",
                return_value=list(REQUIRED_CHECKS),
            ),
            patch("aragora.swarm.merge_arbiter._get_check_status", return_value=checks),
            patch(
                "aragora.swarm.merge_arbiter._has_matching_human_approval",
                return_value=True,
            ),
            patch("aragora.swarm.merge_arbiter._merge_pr", return_value=(True, "merged")),
        ):
            summary = await arbiter.run()

        assert 7 in summary.merged
        assert summary.polls >= 1


# ---------------------------------------------------------------------------
# Auto-collect quorum evidence for ready candidates blocked only on quorum
# ---------------------------------------------------------------------------

from aragora.swarm.merge_arbiter import (  # noqa: E402
    QUORUM_REQUIRED_CHECK,
    _result_blocked_only_on_quorum,
    _should_collect_evidence,
)
from aragora.swarm.merge_quorum_reconcile import EvidenceComment  # noqa: E402


def _evidence(*families: str) -> list[EvidenceComment]:
    return [
        EvidenceComment(created_at="2026-06-06T00:00:00Z", would_count=True, reviewer_id=f)
        for f in families
    ]


class TestResultBlockedOnlyOnQuorum:
    def test_true_when_only_quorum_check_failing(self):
        r = MergeResult(
            1, "codex/x", False, f"failing required checks: {QUORUM_REQUIRED_CHECK}=FAILURE"
        )
        assert _result_blocked_only_on_quorum(r) is True

    def test_true_when_quorum_check_missing(self):
        r = MergeResult(1, "codex/x", False, f"missing required checks: {QUORUM_REQUIRED_CHECK}")
        assert _result_blocked_only_on_quorum(r) is True

    def test_false_when_functional_check_failing(self):
        r = MergeResult(1, "codex/x", False, "failing required checks: lint=FAILURE")
        assert _result_blocked_only_on_quorum(r) is False

    def test_false_when_mixed_with_functional_check(self):
        r = MergeResult(
            1,
            "codex/x",
            False,
            f"failing required checks: {QUORUM_REQUIRED_CHECK}=FAILURE, lint=FAILURE",
        )
        assert _result_blocked_only_on_quorum(r) is False

    def test_false_for_success_or_other_waiting(self):
        assert _result_blocked_only_on_quorum(MergeResult(1, "codex/x", True, "merged")) is False
        assert (
            _result_blocked_only_on_quorum(
                MergeResult(
                    1, "codex/x", False, "waiting on full-suite checks: Core Suites=PENDING"
                )
            )
            is False
        )


class TestShouldCollectEvidence:
    def _quorum_blocked(self):
        return MergeResult(
            42, "codex/x", False, f"failing required checks: {QUORUM_REQUIRED_CHECK}=FAILURE"
        )

    def _ctx(self, *_a):
        return {"head_sha": "abc123", "head_committed_at": "2026-06-06T00:00:00Z"}

    def test_true_for_tier2_quorum_blocked_no_evidence(self):
        assert (
            _should_collect_evidence(
                _pr(42, "codex/x"),
                self._quorum_blocked(),
                config=MergeArbiterConfig(),
                tier_fetcher=lambda *_: 2,
                context_fetcher=self._ctx,
                evidence_reader=lambda *_: _evidence(),
            )
            is True
        )

    def test_false_when_flag_off(self):
        assert (
            _should_collect_evidence(
                _pr(42, "codex/x"),
                self._quorum_blocked(),
                config=MergeArbiterConfig(auto_collect_evidence=False),
                tier_fetcher=lambda *_: 2,
                context_fetcher=self._ctx,
                evidence_reader=lambda *_: _evidence(),
            )
            is False
        )

    def test_false_when_already_has_required_evidence(self):
        assert (
            _should_collect_evidence(
                _pr(42, "codex/x"),
                self._quorum_blocked(),
                config=MergeArbiterConfig(),
                tier_fetcher=lambda *_: 2,
                context_fetcher=self._ctx,
                evidence_reader=lambda *_: _evidence("claude", "grok"),
            )
            is False
        )

    def test_false_for_tier3_and_tier4(self):
        for tier in (3, 4):
            assert (
                _should_collect_evidence(
                    _pr(42, "codex/x"),
                    self._quorum_blocked(),
                    config=MergeArbiterConfig(),
                    tier_fetcher=lambda *_a, _t=tier: _t,
                    context_fetcher=self._ctx,
                    evidence_reader=lambda *_: _evidence(),
                )
                is False
            )

    def test_false_when_not_quorum_blocked(self):
        assert (
            _should_collect_evidence(
                _pr(42, "codex/x"),
                MergeResult(42, "codex/x", False, "failing required checks: lint=FAILURE"),
                config=MergeArbiterConfig(),
                tier_fetcher=lambda *_: 2,
                context_fetcher=self._ctx,
                evidence_reader=lambda *_: _evidence(),
            )
            is False
        )


class TestAutoCollectIntegration:
    def _arbiter_with_fakes(self, collector, *, tier=2, evidence=None):
        calls = {"n": 0}

        def counting_collector(**kw):
            calls["n"] += 1
            return collector(**kw)

        arb = MergeArbiter(
            config=MergeArbiterConfig(
                poll_interval_seconds=0.001,
                max_runtime_hours=0.0003,
                max_consecutive_failures=99,
            ),
            tier_fetcher=lambda *_: tier,
            context_fetcher=lambda *_: {
                "head_sha": "deadbeef",
                "head_committed_at": "2026-06-06T00:00:00Z",
            },
            evidence_reader=lambda *_: (evidence or []),
            collector=counting_collector,
            author_resolver=lambda: "an0mium",
        )
        return arb, calls

    @pytest.mark.asyncio
    async def test_collects_once_per_head_across_polls(self):
        arb, calls = self._arbiter_with_fakes(lambda **kw: None)
        quorum_pr = _pr(50, "codex/x")
        blocked = MergeResult(
            50, "codex/x", False, f"failing required checks: {QUORUM_REQUIRED_CHECK}=FAILURE"
        )
        with (
            patch("aragora.swarm.merge_arbiter._list_candidate_prs", return_value=[quorum_pr]),
            patch("aragora.swarm.merge_arbiter._evaluate_pr", return_value=blocked),
        ):
            summary = await arb.run()
        # Many polls happen in the window, but collection is idempotent per head.
        assert calls["n"] == 1
        assert summary.polls >= 1

    @pytest.mark.asyncio
    async def test_does_not_collect_for_tier3(self):
        arb, calls = self._arbiter_with_fakes(lambda **kw: None, tier=3)
        quorum_pr = _pr(51, "codex/x")
        blocked = MergeResult(
            51, "codex/x", False, f"failing required checks: {QUORUM_REQUIRED_CHECK}=FAILURE"
        )
        with (
            patch("aragora.swarm.merge_arbiter._list_candidate_prs", return_value=[quorum_pr]),
            patch("aragora.swarm.merge_arbiter._evaluate_pr", return_value=blocked),
        ):
            await arb.run()
        assert calls["n"] == 0

    @pytest.mark.asyncio
    async def test_collector_fault_is_swallowed(self):
        def boom(**kw):
            raise RuntimeError("reviewer substrate down")

        arb, calls = self._arbiter_with_fakes(boom)
        quorum_pr = _pr(52, "codex/x")
        blocked = MergeResult(
            52, "codex/x", False, f"failing required checks: {QUORUM_REQUIRED_CHECK}=FAILURE"
        )
        with (
            patch("aragora.swarm.merge_arbiter._list_candidate_prs", return_value=[quorum_pr]),
            patch("aragora.swarm.merge_arbiter._evaluate_pr", return_value=blocked),
        ):
            summary = await arb.run()  # must not raise
        assert calls["n"] == 1  # attempted once; head recorded so no retry storm
        assert summary.polls >= 1
