"""
Integration tests for Multi Agent PR Review feature.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# Check if we have API keys for integration tests
HAS_API_KEYS = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))

from aragora.cli.review import (
    build_review_prompt,
    extract_review_findings,
    format_github_comment,
    DEFAULT_REVIEW_AGENTS,
    DEFAULT_ROUNDS,
    MAX_DIFF_SIZE,
)
from aragora.config.settings import DebateSettings
from aragora.export.pr_comment import (
    format_pr_comment,
    format_compact_comment,
    format_slack_message,
    PRCommentConfig,
)
from aragora.prompts.code_review import (
    SECURITY_PROMPT,
    PERFORMANCE_PROMPT,
    QUALITY_PROMPT,
    build_review_prompt as prompts_build_review_prompt,
    get_focus_prompts,
    get_role_prompt,
)


class TestBuildReviewPrompt:
    """Tests for review prompt building."""

    def test_build_prompt_includes_diff(self):
        """Prompt should include the diff content."""
        diff = "diff --git a/test.py\n+new line"
        prompt = build_review_prompt(diff)
        assert diff in prompt

    def test_build_prompt_includes_security_focus(self):
        """Prompt should include security focus when specified."""
        prompt = build_review_prompt("diff", focus_areas=["security"])
        assert "Security" in prompt
        assert "SQL" in prompt or "injection" in prompt.lower()

    def test_build_prompt_includes_performance_focus(self):
        """Prompt should include performance focus when specified."""
        prompt = build_review_prompt("diff", focus_areas=["performance"])
        assert "Performance" in prompt
        assert "N+1" in prompt or "algorithm" in prompt.lower()

    def test_build_prompt_includes_quality_focus(self):
        """Prompt should include quality focus when specified."""
        prompt = build_review_prompt("diff", focus_areas=["quality"])
        assert "Quality" in prompt
        assert "error" in prompt.lower() or "edge case" in prompt.lower()

    def test_build_prompt_truncates_large_diff(self):
        """Large diffs should be truncated."""
        large_diff = "x" * (MAX_DIFF_SIZE + 1000)
        prompt = build_review_prompt(large_diff)
        assert len(prompt) < len(large_diff) + 1000
        assert "truncated" in prompt.lower()

    def test_build_prompt_all_focus_areas_by_default(self):
        """Default should include all focus areas."""
        prompt = build_review_prompt("diff")
        assert "Security" in prompt
        assert "Performance" in prompt
        assert "Quality" in prompt


class TestExtractReviewFindings:
    """Tests for extracting findings from debate results."""

    def test_extract_findings_returns_expected_keys(self):
        """Findings dict should have all expected keys."""
        mock_result = Mock()
        mock_result.votes = []
        mock_result.critiques = []
        mock_result.final_answer = "Test summary"
        mock_result.messages = []

        with patch("aragora.review.diff_review.DisagreementReporter") as MockReporter:
            mock_report = Mock()
            mock_report.unanimous_critiques = []
            mock_report.split_opinions = []
            mock_report.risk_areas = []
            mock_report.agreement_score = 0.8
            mock_report.agent_alignment = {}
            MockReporter.return_value.generate_report.return_value = mock_report

            findings = extract_review_findings(mock_result)

        assert "unanimous_critiques" in findings
        assert "split_opinions" in findings
        assert "risk_areas" in findings
        assert "agreement_score" in findings
        assert "critical_issues" in findings
        assert "high_issues" in findings
        assert "medium_issues" in findings
        assert "low_issues" in findings

    def test_extract_findings_categorizes_by_severity(self):
        """Critiques should be categorized by severity."""
        mock_result = Mock()
        mock_result.votes = []
        mock_result.final_answer = ""
        mock_result.messages = []

        # Create critiques with different severities
        critical_critique = Mock()
        critical_critique.severity = 0.95
        critical_critique.agent = "agent1"
        critical_critique.target_agent = "target1"
        critical_critique.issues = ["Critical issue"]
        critical_critique.suggestions = []

        low_critique = Mock()
        low_critique.severity = 0.2
        low_critique.agent = "agent2"
        low_critique.target_agent = "target2"
        low_critique.issues = ["Low issue"]
        low_critique.suggestions = []

        mock_result.critiques = [critical_critique, low_critique]

        with patch("aragora.review.diff_review.DisagreementReporter") as MockReporter:
            mock_report = Mock()
            mock_report.unanimous_critiques = []
            mock_report.split_opinions = []
            mock_report.risk_areas = []
            mock_report.agreement_score = 0.5
            mock_report.agent_alignment = {}
            MockReporter.return_value.generate_report.return_value = mock_report

            findings = extract_review_findings(mock_result)

        assert len(findings["critical_issues"]) == 1
        assert len(findings["low_issues"]) == 1

    def test_extract_findings_drops_meta_review_issues(self):
        """Critiques about the review itself should not become blocking findings."""
        mock_result = Mock()
        mock_result.votes = []
        mock_result.final_answer = ""
        mock_result.messages = []

        meta_critique = Mock()
        meta_critique.severity = 0.95
        meta_critique.agent = "agent1"
        meta_critique.target_agent = "openai-api_performance_reviewer"
        meta_critique.issues = [
            "Good catch: this should be reframed as incomplete visibility, not a confirmed bug."
        ]
        meta_critique.suggestions = [
            "Reframe the strongest findings as review blockers due to incomplete visibility."
        ]
        mock_result.critiques = [meta_critique]

        with patch("aragora.review.diff_review.DisagreementReporter") as MockReporter:
            mock_report = Mock()
            mock_report.unanimous_critiques = []
            mock_report.split_opinions = []
            mock_report.risk_areas = []
            mock_report.agreement_score = 0.5
            mock_report.agent_alignment = {}
            MockReporter.return_value.generate_report.return_value = mock_report

            findings = extract_review_findings(mock_result)

        assert findings["critical_issues"] == []
        assert len(findings["meta_issues"]) == 1

    def test_extract_findings_drops_location_only_artifact(self):
        """Malformed location-only review artifacts should stay non-blocking."""
        mock_result = Mock()
        mock_result.votes = []
        mock_result.final_answer = ""
        mock_result.messages = []

        meta_critique = Mock()
        meta_critique.severity = 0.95
        meta_critique.agent = "agent1"
        meta_critique.target_agent = "openai-api_performance_reviewer"
        meta_critique.issues = ["Location**: aragora/live/e2e/admin.spec.ts"]
        meta_critique.suggestions = []
        mock_result.critiques = [meta_critique]

        with patch("aragora.review.diff_review.DisagreementReporter") as MockReporter:
            mock_report = Mock()
            mock_report.unanimous_critiques = []
            mock_report.split_opinions = []
            mock_report.risk_areas = []
            mock_report.agreement_score = 0.5
            mock_report.agent_alignment = {}
            MockReporter.return_value.generate_report.return_value = mock_report

            findings = extract_review_findings(mock_result)

        assert findings["critical_issues"] == []
        assert len(findings["meta_issues"]) == 1

    def test_extract_findings_drops_meta_review_with_file_target(self):
        """Meta-review should not become blocking just because it names a file."""
        mock_result = Mock()
        mock_result.votes = []
        mock_result.final_answer = ""
        mock_result.messages = []

        meta_critique = Mock()
        meta_critique.severity = 0.95
        meta_critique.agent = "agent1"
        meta_critique.target_agent = "scripts/ci_install_project.sh"
        meta_critique.issues = [
            "Overstates CI shell-script execution as a new critical security bug. "
            "Calling this CRITICAL is not well supported from the diff alone."
        ]
        meta_critique.suggestions = [
            "agent-like target,",
            "no concrete file/location hint,",
            "and explicit meta-review language.",
        ]
        mock_result.critiques = [meta_critique]

        with patch("aragora.review.diff_review.DisagreementReporter") as MockReporter:
            mock_report = Mock()
            mock_report.unanimous_critiques = []
            mock_report.split_opinions = []
            mock_report.risk_areas = []
            mock_report.agreement_score = 0.5
            mock_report.agent_alignment = {}
            MockReporter.return_value.generate_report.return_value = mock_report

            findings = extract_review_findings(mock_result)

        assert findings["critical_issues"] == []
        assert len(findings["meta_issues"]) == 1

    def test_extract_findings_drops_incomplete_defect_rebuttal(self):
        """Certainty rebuttals on a file target should remain meta issues."""
        mock_result = Mock()
        mock_result.votes = []
        mock_result.final_answer = ""
        mock_result.messages = []

        meta_critique = Mock()
        meta_critique.severity = 0.95
        meta_critique.agent = "agent1"
        meta_critique.target_agent = "aragora/cli/commands/debate.py"
        meta_critique.issues = [
            "Removed role hints observation is reasonable but incomplete. "
            "Good to flag as a regression risk, but not as a definite defect."
        ]
        meta_critique.suggestions = []
        mock_result.critiques = [meta_critique]

        with patch("aragora.review.diff_review.DisagreementReporter") as MockReporter:
            mock_report = Mock()
            mock_report.unanimous_critiques = []
            mock_report.split_opinions = []
            mock_report.risk_areas = []
            mock_report.agreement_score = 0.5
            mock_report.agent_alignment = {}
            MockReporter.return_value.generate_report.return_value = mock_report

            findings = extract_review_findings(mock_result)

        assert findings["critical_issues"] == []
        assert len(findings["meta_issues"]) == 1

    def test_extract_findings_drops_speculative_regression_risk_rebuttal(self):
        """Speculative regression-risk framing should remain a meta review note."""
        mock_result = Mock()
        mock_result.votes = []
        mock_result.final_answer = ""
        mock_result.messages = []

        meta_critique = Mock()
        meta_critique.severity = 0.95
        meta_critique.agent = "agent1"
        meta_critique.target_agent = "aragora/cli/commands/debate.py"
        meta_critique.issues = [
            "Removed role hints note is plausible but somewhat speculative from this diff "
            "and should be framed as a regression risk to validate, not a definite bug."
        ]
        meta_critique.suggestions = []
        mock_result.critiques = [meta_critique]

        with patch("aragora.review.diff_review.DisagreementReporter") as MockReporter:
            mock_report = Mock()
            mock_report.unanimous_critiques = []
            mock_report.split_opinions = []
            mock_report.risk_areas = []
            mock_report.agreement_score = 0.5
            mock_report.agent_alignment = {}
            MockReporter.return_value.generate_report.return_value = mock_report

            findings = extract_review_findings(mock_result)

        assert findings["critical_issues"] == []
        assert len(findings["meta_issues"]) == 1

    def test_extract_findings_drops_location_only_issue_artifact(self):
        """Location-only issue artifacts should not count as grounded criticals."""
        mock_result = Mock()
        mock_result.votes = []
        mock_result.final_answer = ""
        mock_result.messages = []

        meta_critique = Mock()
        meta_critique.severity = 0.95
        meta_critique.agent = "agent1"
        meta_critique.target_agent = "aragora/cli/review.py"
        meta_critique.issues = [
            "Location:** `aragora/cli/review.py` and `.github/workflows/aragora-review-gate.yml`"
        ]
        meta_critique.suggestions = []
        mock_result.critiques = [meta_critique]

        with patch("aragora.review.diff_review.DisagreementReporter") as MockReporter:
            mock_report = Mock()
            mock_report.unanimous_critiques = []
            mock_report.split_opinions = []
            mock_report.risk_areas = []
            mock_report.agreement_score = 0.5
            mock_report.agent_alignment = {}
            MockReporter.return_value.generate_report.return_value = mock_report

            findings = extract_review_findings(mock_result)

        assert findings["critical_issues"] == []
        assert len(findings["meta_issues"]) == 1


class TestFormatGitHubComment:
    """Tests for GitHub comment formatting."""

    def test_format_comment_includes_header(self):
        """Comment should include Multi Agent header."""
        mock_result = Mock()
        findings = {
            "agents_used": ["agent1", "agent2"],
            "unanimous_critiques": [],
            "split_opinions": [],
            "risk_areas": [],
            "critical_issues": [],
            "high_issues": [],
            "agreement_score": 0.8,
            "final_summary": "",
        }
        comment = format_github_comment(mock_result, findings)
        assert "Multi Agent" in comment

    def test_format_comment_includes_unanimous_issues(self):
        """Comment should show unanimous issues prominently."""
        mock_result = Mock()
        findings = {
            "agents_used": ["agent1"],
            "unanimous_critiques": ["SQL injection found"],
            "split_opinions": [],
            "risk_areas": [],
            "critical_issues": [],
            "high_issues": [],
            "agreement_score": 1.0,
            "final_summary": "",
        }
        comment = format_github_comment(mock_result, findings)
        assert "Unanimous Issues" in comment
        assert "SQL injection found" in comment

    def test_format_comment_includes_split_opinions(self):
        """Comment should show split opinions as table."""
        mock_result = Mock()
        findings = {
            "agents_used": ["agent1", "agent2"],
            "unanimous_critiques": [],
            "split_opinions": [("Add caching?", ["agent1"], ["agent2"])],
            "risk_areas": [],
            "critical_issues": [],
            "high_issues": [],
            "agreement_score": 0.5,
            "final_summary": "",
        }
        comment = format_github_comment(mock_result, findings)
        assert "Split Opinions" in comment
        assert "For" in comment
        assert "Against" in comment

    def test_format_comment_includes_footer(self):
        """Comment should include Aragora footer."""
        mock_result = Mock()
        findings = {
            "agents_used": [],
            "unanimous_critiques": [],
            "split_opinions": [],
            "risk_areas": [],
            "critical_issues": [],
            "high_issues": [],
            "agreement_score": 0.8,
            "final_summary": "",
        }
        comment = format_github_comment(mock_result, findings)
        assert "Aragora" in comment
        assert "Agreement score" in comment


class TestPRCommentFormatter:
    """Tests for the pr_comment module."""

    def test_format_pr_comment_basic(self):
        """Basic PR comment formatting should work."""
        findings = {
            "agents_used": ["anthropic-api_security", "openai-api_quality"],
            "unanimous_critiques": ["Issue 1"],
            "split_opinions": [],
            "risk_areas": [],
            "critical_issues": [],
            "high_issues": [],
            "agreement_score": 0.9,
            "final_summary": "Summary text",
        }
        comment = format_pr_comment(findings)
        assert "Multi Agent" in comment
        assert "Issue 1" in comment

    def test_format_pr_comment_with_config(self):
        """PR comment should respect configuration."""
        findings = {
            "agents_used": ["agent1"],
            "unanimous_critiques": ["Issue 1", "Issue 2", "Issue 3"],
            "split_opinions": [],
            "risk_areas": [],
            "critical_issues": [],
            "high_issues": [],
            "agreement_score": 0.8,
            "final_summary": "",
        }
        config = PRCommentConfig(max_unanimous_issues=1)
        comment = format_pr_comment(findings, config)
        assert "Issue 1" in comment
        assert "more" in comment  # Should indicate more issues

    def test_format_compact_comment(self):
        """Compact comment should be single line."""
        findings = {
            "critical_issues": [{"issue": "critical"}],
            "high_issues": [{"issue": "high1"}, {"issue": "high2"}],
            "unanimous_critiques": ["unanimous"],
            "agreement_score": 0.85,
        }
        compact = format_compact_comment(findings)
        assert "AI Review:" in compact
        assert "1 critical" in compact
        assert "2 high" in compact
        assert "85%" in compact

    def test_format_compact_no_issues(self):
        """Compact comment should handle no issues."""
        findings = {
            "critical_issues": [],
            "high_issues": [],
            "unanimous_critiques": [],
            "agreement_score": 0.9,
        }
        compact = format_compact_comment(findings)
        assert "No major issues" in compact

    def test_format_slack_message(self):
        """Slack message should have correct structure."""
        findings = {
            "critical_issues": [{"issue": "critical"}],
            "high_issues": [],
            "unanimous_critiques": ["Issue 1"],
            "agreement_score": 0.8,
        }
        slack = format_slack_message(findings)
        assert "attachments" in slack
        assert slack["attachments"][0]["color"] == "danger"  # Critical = red

    def test_format_slack_no_critical(self):
        """Slack message color should be yellow for high only."""
        findings = {
            "critical_issues": [],
            "high_issues": [{"issue": "high"}],
            "unanimous_critiques": [],
            "agreement_score": 0.8,
        }
        slack = format_slack_message(findings)
        assert slack["attachments"][0]["color"] == "warning"

    def test_format_slack_no_issues(self):
        """Slack message color should be green when no issues."""
        findings = {
            "critical_issues": [],
            "high_issues": [],
            "unanimous_critiques": [],
            "agreement_score": 0.9,
        }
        slack = format_slack_message(findings)
        assert slack["attachments"][0]["color"] == "good"


class TestCodeReviewPrompts:
    """Tests for the code review prompts module."""

    def test_security_prompt_exists(self):
        """Security prompt should exist and have content."""
        assert SECURITY_PROMPT
        assert "injection" in SECURITY_PROMPT.lower()
        assert "XSS" in SECURITY_PROMPT

    def test_performance_prompt_exists(self):
        """Performance prompt should exist and have content."""
        assert PERFORMANCE_PROMPT
        assert "N+1" in PERFORMANCE_PROMPT
        assert "memory" in PERFORMANCE_PROMPT.lower()

    def test_quality_prompt_exists(self):
        """Quality prompt should exist and have content."""
        assert QUALITY_PROMPT
        assert "error" in QUALITY_PROMPT.lower()
        assert "edge" in QUALITY_PROMPT.lower()

    def test_get_focus_prompts_single(self):
        """Get single focus area prompt."""
        prompt = get_focus_prompts(["security"])
        assert "Security" in prompt
        assert "Performance" not in prompt

    def test_get_focus_prompts_multiple(self):
        """Get multiple focus area prompts."""
        prompt = get_focus_prompts(["security", "performance"])
        assert "Security" in prompt
        assert "Performance" in prompt

    def test_get_focus_prompts_default(self):
        """Default should include all focus areas."""
        prompt = get_focus_prompts()
        assert "Security" in prompt
        assert "Performance" in prompt
        assert "Quality" in prompt

    def test_build_review_prompt_from_prompts_module(self):
        """Build review prompt should work."""
        diff = "diff content"
        prompt = prompts_build_review_prompt(diff)
        assert diff in prompt
        assert "Security" in prompt

    def test_build_review_prompt_with_context(self):
        """Build review prompt with additional context."""
        prompt = prompts_build_review_prompt("diff", additional_context="This is a Django app")
        assert "Django" in prompt

    def test_get_role_prompt(self):
        """Role prompts should exist for known roles."""
        security_role = get_role_prompt("security_reviewer")
        assert "security" in security_role.lower()

        performance_role = get_role_prompt("performance_reviewer")
        assert "performance" in performance_role.lower()

        # Unknown role returns empty
        unknown = get_role_prompt("unknown_role")
        assert unknown == ""


class TestConstants:
    """Tests for module constants."""

    def test_default_agents(self):
        """Default agents should be reasonable."""
        assert "anthropic" in DEFAULT_REVIEW_AGENTS.lower()
        agents = DEFAULT_REVIEW_AGENTS.split(",")
        assert len(agents) >= 2

    def test_default_rounds(self):
        """Default rounds should be quick but meaningful."""
        assert DEFAULT_ROUNDS == DebateSettings().default_rounds

    def test_max_diff_size(self):
        """Max diff size should be reasonable."""
        assert MAX_DIFF_SIZE >= 10000  # At least 10KB
        assert MAX_DIFF_SIZE <= 100000  # At most 100KB


class TestRunReviewDebate:
    """Tests for review debate execution helpers."""

    @pytest.mark.asyncio
    async def test_uses_available_agents_for_default_review_set(self):
        """Default review debates should avoid unavailable providers."""
        from aragora.cli.review import run_review_debate

        mock_result = Mock(final_answer="Looks good")
        mock_arena = Mock()
        mock_arena.run = AsyncMock(return_value=mock_result)

        with (
            patch(
                "aragora.review.diff_review.get_available_agents",
                return_value="anthropic-api,openai-api",
            ),
            patch(
                "aragora.review.diff_review.create_agent",
                side_effect=lambda **kwargs: Mock(name=kwargs["name"]),
            ) as create_agent_mock,
            patch("aragora.review.diff_review.Arena", return_value=mock_arena),
        ):
            result = await run_review_debate("diff --git a/a.py b/a.py", rounds=1)

        assert result is mock_result
        assert [call.kwargs["model_type"] for call in create_agent_mock.call_args_list] == [
            "anthropic-api",
            "openai-api",
        ]


# Integration test that requires API keys
@pytest.mark.integration
@pytest.mark.skipif(not HAS_API_KEYS, reason="Requires ANTHROPIC_API_KEY or OPENAI_API_KEY")
class TestReviewIntegration:
    """Integration tests that run actual reviews."""

    @pytest.mark.asyncio
    async def test_run_review_debate(self):
        """Test running an actual review debate."""
        from aragora.cli.review import run_review_debate

        diff = """diff --git a/test.py b/test.py
+def hello():
+    print("Hello")
"""
        result = await run_review_debate(diff, rounds=1)
        assert result is not None
        assert result.final_answer
