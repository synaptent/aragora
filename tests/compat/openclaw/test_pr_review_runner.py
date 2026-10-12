"""Tests for the OpenClaw PR Review Runner."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.compat.openclaw.pr_review_runner import (
    PolicyChecker,
    PolicyConfig,
    PRReviewRunner,
    ReviewFinding,
    ReviewReceipt,
    ReviewResult,
    _default_policy,
    _extract_repo,
    _format_comment,
    _infer_severity,
    _parse_findings,
    _parse_policy,
    _parse_pr_url,
    findings_to_sarif,
    load_policy,
)


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------


class TestParsePRUrl:
    def test_standard_url(self):
        repo, num, err = _parse_pr_url("https://github.com/owner/repo/pull/42")
        assert repo == "owner/repo"
        assert num == 42
        assert err is None

    def test_trailing_slash(self):
        repo, num, err = _parse_pr_url("https://github.com/org/project/pull/99/")
        assert repo == "org/project"
        assert num == 99
        assert err is None

    def test_invalid_url_no_pull(self):
        _, _, err = _parse_pr_url("https://github.com/owner/repo/issues/5")
        assert err is not None
        assert "Invalid PR URL" in err

    def test_invalid_url_garbage(self):
        _, _, err = _parse_pr_url("not-a-url")
        assert err is not None


class TestExtractRepo:
    def test_https_url(self):
        assert _extract_repo("https://github.com/owner/repo") == "owner/repo"

    def test_trailing_slash(self):
        assert _extract_repo("https://github.com/owner/repo/") == "owner/repo"

    def test_owner_repo_format(self):
        assert _extract_repo("owner/repo") == "owner/repo"

    def test_invalid(self):
        assert _extract_repo("https://example.com") is None


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------


class TestPolicyConfig:
    def test_default_policy_has_sensible_defaults(self):
        policy = _default_policy()
        assert "gh" in policy.allowed_tools
        assert "git" in policy.allowed_tools
        assert "rm" in policy.denied_tools
        assert "sudo" in policy.denied_tools
        assert "api.github.com" in policy.allowed_hosts
        assert "pr diff" in policy.allowed_gh_actions
        assert "pr merge" in policy.denied_gh_actions

    def test_default_policy_denies_by_default(self):
        policy = _default_policy()
        assert policy.default_action == "deny"

    def test_default_policy_requires_receipts(self):
        policy = _default_policy()
        assert policy.require_receipt is True

    def test_parse_policy_from_dict(self):
        data = {
            "name": "test-policy",
            "default_action": "deny",
            "tools": {
                "allow": [
                    {"pattern": "^gh$", "reason": "GitHub CLI"},
                ],
                "deny": [
                    {"pattern": "^rm$", "reason": "No deleting"},
                ],
            },
            "network": {
                "allow": [
                    {"host": "api.github.com", "ports": [443]},
                ],
            },
            "github": {
                "allow": [
                    {"action": "pr diff"},
                ],
                "deny": [
                    {"action": "pr merge"},
                ],
            },
            "resources": {
                "max_execution_seconds": 120,
                "max_concurrent_reviews": 3,
            },
            "audit": {
                "require_receipt": True,
                "log_all_actions": True,
            },
        }
        config = _parse_policy(data)
        assert config.name == "test-policy"
        assert "^gh$" in config.allowed_tools
        assert "^rm$" in config.denied_tools
        assert "api.github.com" in config.allowed_hosts
        assert "pr diff" in config.allowed_gh_actions
        assert "pr merge" in config.denied_gh_actions
        assert config.max_execution_seconds == 120
        assert config.max_concurrent_reviews == 3

    def test_parse_policy_string_rules(self):
        data = {
            "tools": {"allow": ["gh", "git"]},
            "github": {"allow": ["pr diff"], "deny": ["pr merge"]},
        }
        config = _parse_policy(data)
        assert "gh" in config.allowed_tools
        assert "git" in config.allowed_tools

    def test_load_policy_missing_file(self):
        policy = load_policy("/nonexistent/path/policy.yaml")
        # Falls back to defaults
        assert "gh" in policy.allowed_tools

    def test_load_bundled_policy(self):
        """The bundled policy.yaml should load and parse correctly."""
        bundled = Path(__file__).parent.parent.parent.parent / (
            "aragora/compat/openclaw/skills/pr-reviewer/policy.yaml"
        )
        if bundled.exists():
            policy = load_policy(bundled)
            assert policy.name == "pr-reviewer"
            assert len(policy.allowed_hosts) > 0


# ---------------------------------------------------------------------------
# Policy checker
# ---------------------------------------------------------------------------


class TestPolicyChecker:
    def test_allows_whitelisted_action(self):
        policy = _default_policy()
        checker = PolicyChecker(policy)
        assert checker.check_gh_action("pr diff") is True
        assert len(checker.violations) == 0

    def test_denies_blacklisted_action(self):
        policy = _default_policy()
        checker = PolicyChecker(policy)
        assert checker.check_gh_action("pr merge") is False
        assert len(checker.violations) == 1
        assert "pr merge" in checker.violations[0]

    def test_denies_unknown_action_by_default(self):
        policy = _default_policy()
        checker = PolicyChecker(policy)
        assert checker.check_gh_action("repo delete-everything") is False

    def test_allows_unknown_action_when_permissive(self):
        policy = _default_policy()
        policy.default_action = "allow"
        checker = PolicyChecker(policy)
        assert checker.check_gh_action("some-unknown-action") is True

    def test_diff_size_within_limit(self):
        policy = _default_policy()
        checker = PolicyChecker(policy)
        diff = "a" * 1024  # 1KB, well within 50KB limit
        assert checker.check_diff_size(diff) is True

    def test_diff_size_exceeds_limit(self):
        policy = PolicyConfig(max_diff_size_kb=1)  # 1KB limit
        checker = PolicyChecker(policy)
        diff = "a" * 2048  # 2KB
        assert checker.check_diff_size(diff) is False
        assert len(checker.violations) == 1

    def test_violations_accumulate(self):
        policy = _default_policy()
        checker = PolicyChecker(policy)
        checker.check_gh_action("pr merge")
        checker.check_gh_action("pr close")
        assert len(checker.get_violations()) == 2


# ---------------------------------------------------------------------------
# Findings parsing
# ---------------------------------------------------------------------------


class TestParseFindings:
    def test_empty_findings(self):
        findings = _parse_findings({})
        assert findings == []

    def test_unanimous_critiques(self):
        data = {
            "unanimous_critiques": [
                "SQL injection vulnerability in login handler",
                "Missing error handling in API endpoint",
            ],
        }
        findings = _parse_findings(data)
        assert len(findings) == 2
        assert all(f.unanimous for f in findings)

    def test_severity_buckets(self):
        data = {
            "critical_issues": ["RCE via eval()"],
            "high_issues": ["Hardcoded credentials"],
            "medium_issues": ["No input validation"],
            "low_issues": ["Unused import"],
        }
        findings = _parse_findings(data)
        assert len(findings) == 4
        assert findings[0].severity == "critical"
        assert findings[1].severity == "high"
        assert findings[2].severity == "medium"
        assert findings[3].severity == "low"

    def test_title_truncation(self):
        data = {
            "critical_issues": ["A" * 200],
        }
        findings = _parse_findings(data)
        assert len(findings[0].title) == 120


class TestInferSeverity:
    def test_critical_keywords(self):
        assert _infer_severity("SQL injection vulnerability") == "critical"
        assert _infer_severity("Remote code execution via eval") == "critical"

    def test_high_keywords(self):
        assert _infer_severity("Missing authentication check") == "high"
        assert _infer_severity("Hardcoded secret in config") == "high"

    def test_medium_keywords(self):
        assert _infer_severity("Performance issue with N+1 queries") == "medium"
        assert _infer_severity("Potential race condition") == "medium"

    def test_low_default(self):
        assert _infer_severity("Unused variable") == "low"
        assert _infer_severity("Naming convention mismatch") == "low"


# ---------------------------------------------------------------------------
# Comment formatting
# ---------------------------------------------------------------------------


class TestFormatComment:
    def test_no_findings(self):
        comment = _format_comment([], 0.0)
        assert "No significant issues found" in comment

    def test_critical_findings_shown(self):
        findings = [
            ReviewFinding(
                severity="critical",
                title="SQL injection",
                description="SQL injection in login.py:42",
            ),
        ]
        comment = _format_comment(findings, 0.85)
        assert "Critical Issues" in comment
        assert "SQL injection" in comment
        assert "85%" in comment

    def test_medium_low_in_collapsible(self):
        findings = [
            ReviewFinding(severity="medium", title="perf", description="Slow query"),
            ReviewFinding(severity="low", title="style", description="Naming"),
        ]
        comment = _format_comment(findings, 0.5)
        assert "<details>" in comment
        assert "Medium Issues" in comment
        assert "Low Issues" in comment

    def test_unanimous_section(self):
        findings = [
            ReviewFinding(
                severity="high",
                title="auth",
                description="Missing auth",
                unanimous=True,
            ),
        ]
        comment = _format_comment(findings, 0.9)
        assert "All Agents Agree" in comment


# ---------------------------------------------------------------------------
# Review receipt
# ---------------------------------------------------------------------------


class TestReviewReceipt:
    def test_receipt_to_dict(self):
        receipt = ReviewReceipt(
            review_id="abc123",
            pr_url="https://github.com/o/r/pull/1",
            started_at=1000.0,
            completed_at=1030.0,
            findings_count=5,
            critical_count=1,
            high_count=2,
            medium_count=1,
            low_count=1,
            agreement_score=0.85,
            agents_used=["anthropic-api", "openai-api"],
            policy_name="pr-reviewer",
            policy_violations=[],
            checksum="abc",
        )
        d = receipt.to_dict()
        assert d["duration_seconds"] == 30.0
        assert d["severity_counts"]["critical"] == 1
        assert d["policy"]["name"] == "pr-reviewer"
        assert d["checksum"] == "abc"

    def test_receipt_duration(self):
        receipt = ReviewReceipt(
            review_id="x",
            pr_url="url",
            started_at=100.0,
            completed_at=145.5,
            findings_count=0,
            critical_count=0,
            high_count=0,
            medium_count=0,
            low_count=0,
            agreement_score=0.0,
            agents_used=[],
            policy_name="test",
            policy_violations=[],
            checksum="",
        )
        assert receipt.duration_seconds == 45.5


# ---------------------------------------------------------------------------
# Review result
# ---------------------------------------------------------------------------


class TestReviewResult:
    def test_critical_count(self):
        result = ReviewResult(
            pr_url="url",
            pr_number=1,
            repo="o/r",
            findings=[
                ReviewFinding(severity="critical", title="a", description="a"),
                ReviewFinding(severity="critical", title="b", description="b"),
                ReviewFinding(severity="high", title="c", description="c"),
            ],
            agreement_score=0.5,
            agents_used=[],
            comment_posted=False,
            comment_url=None,
            receipt=None,
        )
        assert result.critical_count == 2
        assert result.high_count == 1
        assert result.has_critical is True

    def test_no_critical(self):
        result = ReviewResult(
            pr_url="url",
            pr_number=1,
            repo="o/r",
            findings=[
                ReviewFinding(severity="low", title="a", description="a"),
            ],
            agreement_score=0.9,
            agents_used=[],
            comment_posted=False,
            comment_url=None,
            receipt=None,
        )
        assert result.has_critical is False


# ---------------------------------------------------------------------------
# PRReviewRunner
# ---------------------------------------------------------------------------


class TestPRReviewRunner:
    def test_init_defaults(self):
        runner = PRReviewRunner()
        assert runner.policy.name == "pr-reviewer"
        assert runner.dry_run is False
        assert runner.ci_mode is False

    def test_init_custom_policy(self):
        policy = PolicyConfig(name="custom", max_execution_seconds=60)
        runner = PRReviewRunner(policy=policy, dry_run=True)
        assert runner.policy.name == "custom"
        assert runner.dry_run is True

    @pytest.mark.asyncio
    async def test_run_review_uses_subprocess_when_gauntlet_enabled(self):
        runner = PRReviewRunner(dry_run=True, gauntlet=True)
        with patch.object(
            runner,
            "_run_review_subprocess",
            return_value=({"high_issues": ["gauntlet finding"]}, None),
        ) as mock_subprocess:
            findings, error = await runner._run_review("diff --git a/x b/x")
        assert error is None
        assert findings == {"high_issues": ["gauntlet finding"]}
        mock_subprocess.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_review_logs_import_fallback(self):
        runner = PRReviewRunner(dry_run=True)
        with patch.dict("sys.modules", {"aragora.review.diff_review": None}):
            with patch.object(
                runner,
                "_run_review_subprocess",
                return_value=({"raw_output": "fallback"}, None),
            ) as mock_subprocess:
                with patch("aragora.compat.openclaw.pr_review_runner.logger.debug") as mock_debug:
                    findings, error = await runner._run_review("diff --git a/x b/x")
        assert error is None
        assert findings == {"raw_output": "fallback"}
        mock_subprocess.assert_called_once()
        assert mock_debug.call_count == 1
        assert "Direct review import unavailable" in mock_debug.call_args.args[0]

    def test_from_policy_file_missing(self):
        runner = PRReviewRunner.from_policy_file("/nonexistent/policy.yaml")
        # Falls back to default
        assert "gh" in runner.policy.allowed_tools

    @pytest.mark.asyncio
    async def test_review_pr_invalid_url(self):
        runner = PRReviewRunner(dry_run=True)
        result = await runner.review_pr("not-a-pr-url")
        assert result.error is not None
        assert "Invalid PR URL" in result.error

    @pytest.mark.asyncio
    async def test_review_pr_policy_denies_diff(self):
        """If policy denies pr diff, review should fail gracefully."""
        policy = PolicyConfig(
            denied_gh_actions=["pr diff", "pr comment"],
            allowed_gh_actions=[],
            default_action="deny",
        )
        runner = PRReviewRunner(policy=policy)
        result = await runner.review_pr("https://github.com/o/r/pull/1")
        assert result.error is not None
        assert "Policy denied" in result.error

    @pytest.mark.asyncio
    async def test_review_pr_fetch_failure(self):
        """Test handling of diff fetch failure."""
        runner = PRReviewRunner(dry_run=True)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="Not found",
                stdout="",
            )
            result = await runner.review_pr("https://github.com/o/r/pull/1")
        assert result.error is not None
        assert "Fetch failed" in result.error

    @pytest.mark.asyncio
    async def test_review_pr_success_dry_run(self):
        """Full dry-run review should succeed without posting."""
        runner = PRReviewRunner(dry_run=True, demo=True)

        mock_findings = {
            "unanimous_critiques": ["Missing null check"],
            "critical_issues": [],
            "high_issues": ["No error handling"],
            "medium_issues": [],
            "low_issues": [],
            "agreement_score": 0.75,
        }

        # Mock diff fetch
        diff_result = MagicMock(returncode=0, stdout="diff --git a/foo b/foo\n+bar")

        with patch("subprocess.run", return_value=diff_result):
            with patch.object(
                runner,
                "_run_review",
                new_callable=AsyncMock,
                return_value=(mock_findings, None),
            ):
                result = await runner.review_pr("https://github.com/o/r/pull/42")

        assert result.error is None
        assert result.pr_number == 42
        assert result.repo == "o/r"
        assert result.comment_posted is False  # dry run
        assert result.agreement_score == 0.75
        assert len(result.findings) == 2  # unanimous + high
        assert result.receipt is not None
        assert result.receipt.review_id is not None
        assert result.receipt.checksum  # non-empty

    @pytest.mark.asyncio
    async def test_review_pr_posts_comment(self):
        """Non-dry-run review should attempt to post comment."""
        runner = PRReviewRunner(dry_run=False, demo=True)
        mock_findings = {
            "critical_issues": ["SQL injection"],
            "agreement_score": 0.9,
        }

        diff_result = MagicMock(returncode=0, stdout="diff")
        comment_result = MagicMock(
            returncode=0,
            stdout="https://github.com/o/r/pull/1#comment",
        )

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return diff_result
            return comment_result

        with patch("subprocess.run", side_effect=side_effect):
            with patch.object(
                runner,
                "_run_review",
                new_callable=AsyncMock,
                return_value=(mock_findings, None),
            ):
                result = await runner.review_pr("https://github.com/o/r/pull/1")

        assert result.comment_posted is True
        assert result.receipt is not None
        assert result.receipt.critical_count == 1

    @pytest.mark.asyncio
    async def test_review_pr_truncates_large_diff(self):
        """Large diffs should be truncated, not rejected."""
        policy = PolicyConfig(
            max_diff_size_kb=1,  # 1KB limit
            allowed_gh_actions=["pr diff", "pr comment"],
        )
        runner = PRReviewRunner(policy=policy, dry_run=True)

        # 5KB diff
        large_diff = "+" * 5120
        diff_result = MagicMock(returncode=0, stdout=large_diff)

        with patch("subprocess.run", return_value=diff_result):
            with patch.object(
                runner,
                "_run_review",
                new_callable=AsyncMock,
                return_value=({"agreement_score": 0.5}, None),
            ):
                result = await runner.review_pr("https://github.com/o/r/pull/1")

        # Should succeed (truncated, not rejected)
        assert result.error is None

    @pytest.mark.asyncio
    async def test_review_repo_no_open_prs(self):
        """review_repo with no open PRs returns empty list."""
        runner = PRReviewRunner(dry_run=True)

        list_result = MagicMock(returncode=0, stdout="[]")
        with patch("subprocess.run", return_value=list_result):
            results = await runner.review_repo("https://github.com/o/r")

        assert results == []

    @pytest.mark.asyncio
    async def test_review_repo_invalid_url(self):
        runner = PRReviewRunner(dry_run=True)
        results = await runner.review_repo("not-a-url")
        assert len(results) == 1
        assert results[0].error is not None

    @pytest.mark.asyncio
    async def test_review_repo_respects_concurrent_limit(self):
        """Should not review more PRs than max_concurrent_reviews."""
        policy = PolicyConfig(max_concurrent_reviews=2)
        runner = PRReviewRunner(policy=policy, dry_run=True)

        # 5 open PRs
        prs = [{"number": i} for i in range(1, 6)]
        list_result = MagicMock(returncode=0, stdout=json.dumps(prs))

        reviewed_prs = []

        async def mock_review(pr_url):
            reviewed_prs.append(pr_url)
            return ReviewResult(
                pr_url=pr_url,
                pr_number=None,
                repo=None,
                findings=[],
                agreement_score=0.0,
                agents_used=[],
                comment_posted=False,
                comment_url=None,
                receipt=None,
            )

        with patch("subprocess.run", return_value=list_result):
            with patch.object(runner, "review_pr", side_effect=mock_review):
                results = await runner.review_repo("https://github.com/o/r")

        assert len(results) == 2  # limited by max_concurrent_reviews


# ---------------------------------------------------------------------------
# Subprocess fallback
# ---------------------------------------------------------------------------


class TestReviewSubprocess:
    def test_subprocess_json_parsing(self):
        runner = PRReviewRunner(dry_run=True)
        mock_result = MagicMock(
            returncode=0,
            stdout='Some log output\n{"critical_issues": ["bug"], "agreement_score": 0.8}\n',
            stderr="",
        )
        with patch("subprocess.run", return_value=mock_result):
            findings, error = runner._run_review_subprocess("diff content")
        assert error is None
        assert findings["agreement_score"] == 0.8

    def test_subprocess_invalid_json_logs_debug(self):
        runner = PRReviewRunner(dry_run=True)
        mock_result = MagicMock(returncode=0, stdout="log line\n{invalid json", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            with patch("aragora.compat.openclaw.pr_review_runner.logger.debug") as mock_debug:
                findings, error = runner._run_review_subprocess("diff content")
        assert error is None
        assert findings == {"raw_output": "log line\n{invalid json"}
        assert mock_debug.call_count == 2
        assert "Review subprocess stdout was not valid JSON" in mock_debug.call_args_list[0].args[0]
        assert (
            "Review subprocess embedded JSON parse failed" in mock_debug.call_args_list[1].args[0]
        )

    def test_subprocess_failure(self):
        runner = PRReviewRunner(dry_run=True)
        mock_result = MagicMock(returncode=1, stdout="", stderr="Error: no agents")
        with patch("subprocess.run", return_value=mock_result):
            findings, error = runner._run_review_subprocess("diff")
        assert findings is None
        assert "Error: no agents" in error

    def test_subprocess_timeout(self):
        import subprocess as sp

        runner = PRReviewRunner(dry_run=True)
        with patch("subprocess.run", side_effect=sp.TimeoutExpired("cmd", 300)):
            findings, error = runner._run_review_subprocess("diff")
        assert findings is None
        assert "timed out" in error.lower()

    def test_subprocess_not_found(self):
        runner = PRReviewRunner(dry_run=True)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            findings, error = runner._run_review_subprocess("diff")
        assert findings is None
        assert "not found" in error.lower()


# ---------------------------------------------------------------------------
# SKILL.md integration
# ---------------------------------------------------------------------------


class TestSkillMdIntegration:
    """Verify the SKILL.md file can be parsed by the OpenClaw parser."""

    def test_skill_md_exists(self):
        skill_path = (
            Path(__file__).parent.parent.parent.parent
            / "aragora/compat/openclaw/skills/pr-reviewer/SKILL.md"
        )
        assert skill_path.exists()

    def test_skill_md_parseable(self):
        from aragora.compat.openclaw.skill_parser import OpenClawSkillParser

        skill_path = (
            Path(__file__).parent.parent.parent.parent
            / "aragora/compat/openclaw/skills/pr-reviewer/SKILL.md"
        )
        assert skill_path.exists(), "SKILL.md should exist"

        parsed = OpenClawSkillParser.parse_file(skill_path)
        assert parsed.name == "pr-reviewer"
        assert "code review" in parsed.description.lower()
        assert "shell" in parsed.requires
        assert parsed.frontmatter.version == "1.0.0"
        assert "code-review" in parsed.frontmatter.tags

    def test_policy_yaml_exists(self):
        policy_path = (
            Path(__file__).parent.parent.parent.parent
            / "aragora/compat/openclaw/skills/pr-reviewer/policy.yaml"
        )
        assert policy_path.exists()

    def test_policy_yaml_loadable(self):
        policy_path = (
            Path(__file__).parent.parent.parent.parent
            / "aragora/compat/openclaw/skills/pr-reviewer/policy.yaml"
        )
        assert policy_path.exists(), "policy.yaml should exist"

        policy = load_policy(policy_path)
        assert policy.name == "pr-reviewer"
        assert policy.require_receipt is True
        assert policy.log_all_actions is True


# ---------------------------------------------------------------------------
# SARIF export
# ---------------------------------------------------------------------------


class TestFindingsToSarif:
    def test_empty_findings(self):
        sarif = findings_to_sarif([])
        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"]) == 1
        assert sarif["runs"][0]["results"] == []
        assert sarif["runs"][0]["tool"]["driver"]["name"] == "aragora-pr-reviewer"

    def test_single_finding(self):
        findings = [
            ReviewFinding(
                severity="critical",
                title="SQL injection in login",
                description="User input passed directly to SQL query",
                file_path="src/auth.py",
                line_number=42,
                agent="claude-opus",
            ),
        ]
        sarif = findings_to_sarif(findings)
        run = sarif["runs"][0]
        assert len(run["tool"]["driver"]["rules"]) == 1
        assert len(run["results"]) == 1

        result = run["results"][0]
        assert result["level"] == "error"  # critical → error
        assert (
            result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "src/auth.py"
        )
        assert result["locations"][0]["physicalLocation"]["region"]["startLine"] == 42
        assert result["properties"]["agent"] == "claude-opus"

        rule = run["tool"]["driver"]["rules"][0]
        assert rule["properties"]["severity"] == "critical"

    def test_severity_mapping(self):
        findings = [
            ReviewFinding(severity="critical", title="a", description="a"),
            ReviewFinding(severity="high", title="b", description="b"),
            ReviewFinding(severity="medium", title="c", description="c"),
            ReviewFinding(severity="low", title="d", description="d"),
        ]
        sarif = findings_to_sarif(findings)
        levels = [r["level"] for r in sarif["runs"][0]["results"]]
        assert levels == ["error", "error", "warning", "note"]

    def test_deduplicated_rules(self):
        """Findings with the same title should share a rule."""
        findings = [
            ReviewFinding(severity="high", title="Missing auth", description="In endpoint A"),
            ReviewFinding(severity="high", title="Missing auth", description="In endpoint B"),
        ]
        sarif = findings_to_sarif(findings)
        run = sarif["runs"][0]
        assert len(run["tool"]["driver"]["rules"]) == 1  # deduplicated
        assert len(run["results"]) == 2  # but two results
        assert run["results"][0]["ruleIndex"] == run["results"][1]["ruleIndex"]

    def test_finding_without_location(self):
        findings = [
            ReviewFinding(severity="low", title="Style issue", description="Naming"),
        ]
        sarif = findings_to_sarif(findings)
        result = sarif["runs"][0]["results"][0]
        assert "locations" not in result

    def test_receipt_metadata(self):
        receipt = ReviewReceipt(
            review_id="abc123",
            pr_url="https://github.com/o/r/pull/1",
            started_at=1000.0,
            completed_at=1030.0,
            findings_count=1,
            critical_count=0,
            high_count=1,
            medium_count=0,
            low_count=0,
            agreement_score=0.92,
            agents_used=["anthropic-api", "openai-api"],
            policy_name="pr-reviewer",
            policy_violations=[],
            checksum="deadbeef",
        )
        sarif = findings_to_sarif([], receipt)
        props = sarif["runs"][0]["properties"]
        assert props["reviewId"] == "abc123"
        assert props["agreementScore"] == 0.92
        assert props["checksum"] == "deadbeef"

    def test_sarif_schema_field(self):
        sarif = findings_to_sarif([])
        assert "$schema" in sarif
        assert "sarif-schema-2.1.0" in sarif["$schema"]

    def test_unanimous_property(self):
        findings = [
            ReviewFinding(
                severity="high",
                title="Bug",
                description="Bug",
                unanimous=True,
            ),
        ]
        sarif = findings_to_sarif(findings)
        rule = sarif["runs"][0]["tool"]["driver"]["rules"][0]
        assert rule["properties"]["unanimous"] is True
