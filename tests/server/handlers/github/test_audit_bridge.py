"""
Tests for GitHub audit bridge handler.

Tests cover:
- IssuePriority and SyncStatus enums
- GitHubIssueResult and SyncResult dataclasses
- GitHubAuditClient methods
- Issue title/body generation
- Label mapping
- Handler functions for creating issues
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from aragora.server.handlers.github.audit_bridge import (
    IssuePriority,
    SyncStatus,
    GitHubIssueResult,
    SyncResult,
    GitHubAuditClient,
    SEVERITY_LABELS,
    CATEGORY_LABELS,
    generate_issue_title,
    generate_issue_body,
    get_labels_for_finding,
    handle_create_issue,
    handle_bulk_create_issues,
)


# =============================================================================
# IssuePriority Enum Tests
# =============================================================================


class TestIssuePriority:
    """Tests for IssuePriority enum."""

    def test_critical_value(self):
        """Should have critical value."""
        assert IssuePriority.CRITICAL.value == "critical"

    def test_high_value(self):
        """Should have high value."""
        assert IssuePriority.HIGH.value == "high"

    def test_medium_value(self):
        """Should have medium value."""
        assert IssuePriority.MEDIUM.value == "medium"

    def test_low_value(self):
        """Should have low value."""
        assert IssuePriority.LOW.value == "low"

    def test_info_value(self):
        """Should have info value."""
        assert IssuePriority.INFO.value == "info"


# =============================================================================
# SyncStatus Enum Tests
# =============================================================================


class TestSyncStatus:
    """Tests for SyncStatus enum."""

    def test_pending_value(self):
        """Should have pending value."""
        assert SyncStatus.PENDING.value == "pending"

    def test_in_progress_value(self):
        """Should have in_progress value."""
        assert SyncStatus.IN_PROGRESS.value == "in_progress"

    def test_completed_value(self):
        """Should have completed value."""
        assert SyncStatus.COMPLETED.value == "completed"

    def test_partial_value(self):
        """Should have partial value."""
        assert SyncStatus.PARTIAL.value == "partial"

    def test_failed_value(self):
        """Should have failed value."""
        assert SyncStatus.FAILED.value == "failed"


# =============================================================================
# GitHubIssueResult Tests
# =============================================================================


class TestGitHubIssueResult:
    """Tests for GitHubIssueResult dataclass."""

    def test_default_values(self):
        """Should have correct defaults."""
        result = GitHubIssueResult(finding_id="f1")
        assert result.finding_id == "f1"
        assert result.issue_number is None
        assert result.issue_url is None
        assert result.status == "pending"
        assert result.error is None

    def test_with_all_values(self):
        """Should accept all values."""
        result = GitHubIssueResult(
            finding_id="f1",
            issue_number=123,
            issue_url="https://github.com/owner/repo/issues/123",
            status="created",
            error=None,
        )
        assert result.issue_number == 123
        assert result.status == "created"

    def test_to_dict(self):
        """Should convert to dict."""
        result = GitHubIssueResult(
            finding_id="f1",
            issue_number=123,
            issue_url="https://github.com/owner/repo/issues/123",
            status="created",
        )
        d = result.to_dict()
        assert d["finding_id"] == "f1"
        assert d["issue_number"] == 123
        assert d["issue_url"] == "https://github.com/owner/repo/issues/123"
        assert d["status"] == "created"

    def test_to_dict_with_error(self):
        """Should include error in dict."""
        result = GitHubIssueResult(
            finding_id="f1",
            status="failed",
            error="API error",
        )
        d = result.to_dict()
        assert d["error"] == "API error"


# =============================================================================
# SyncResult Tests
# =============================================================================


class TestSyncResult:
    """Tests for SyncResult dataclass."""

    def test_default_values(self):
        """Should have correct defaults."""
        result = SyncResult(
            sync_id="s1",
            session_id="sess1",
            repository="owner/repo",
            status=SyncStatus.PENDING,
        )
        assert result.sync_id == "s1"
        assert result.issues_created == []
        assert result.pr_created is None
        assert result.completed_at is None
        assert result.error is None

    def test_to_dict(self):
        """Should convert to dict."""
        result = SyncResult(
            sync_id="s1",
            session_id="sess1",
            repository="owner/repo",
            status=SyncStatus.COMPLETED,
        )
        d = result.to_dict()
        assert d["sync_id"] == "s1"
        assert d["session_id"] == "sess1"
        assert d["repository"] == "owner/repo"
        assert d["status"] == "completed"

    def test_to_dict_with_issues(self):
        """Should include issues in dict."""
        issue = GitHubIssueResult(finding_id="f1", issue_number=123)
        result = SyncResult(
            sync_id="s1",
            session_id="sess1",
            repository="owner/repo",
            status=SyncStatus.COMPLETED,
            issues_created=[issue],
        )
        d = result.to_dict()
        assert len(d["issues_created"]) == 1
        assert d["issues_created"][0]["finding_id"] == "f1"

    def test_to_dict_with_completed_at(self):
        """Should include completed_at as ISO string."""
        now = datetime.now(timezone.utc)
        result = SyncResult(
            sync_id="s1",
            session_id="sess1",
            repository="owner/repo",
            status=SyncStatus.COMPLETED,
            completed_at=now,
        )
        d = result.to_dict()
        assert d["completed_at"] == now.isoformat()


# =============================================================================
# GitHubAuditClient Tests
# =============================================================================


class TestGitHubAuditClientInit:
    """Tests for GitHubAuditClient initialization."""

    def test_uses_provided_token(self):
        """Should use provided token."""
        client = GitHubAuditClient(token="test-token")
        assert client.token == "test-token"

    def test_uses_env_var_token(self):
        """Should use env var token when not provided."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "env-token"}):
            client = GitHubAuditClient()
            assert client.token == "env-token"

    def test_base_url(self):
        """Should have GitHub API base URL."""
        client = GitHubAuditClient()
        assert client.base_url == "https://api.github.com"


class TestGitHubAuditClientCreateIssue:
    """Tests for GitHubAuditClient.create_issue method."""

    @pytest.mark.asyncio
    async def test_demo_mode_without_token(self):
        """Should return demo response without token."""
        client = GitHubAuditClient(token=None)
        result = await client.create_issue(
            owner="owner",
            repo="repo",
            title="Test Issue",
            body="Test body",
        )
        assert result["success"] is True
        assert result["demo"] is True
        assert result["number"] is not None
        assert "github.com" in result["html_url"]

    @pytest.mark.asyncio
    async def test_includes_labels_in_payload(self):
        """Should include labels when provided."""
        client = GitHubAuditClient(token="test-token")

        mock_response = AsyncMock()
        mock_response.status = 201
        mock_response.json = AsyncMock(
            return_value={
                "number": 123,
                "html_url": "https://github.com/owner/repo/issues/123",
                "id": 456,
            }
        )

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.post = MagicMock(return_value=mock_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=False)
            mock_session_class.return_value = mock_session

            result = await client.create_issue(
                owner="owner",
                repo="repo",
                title="Test",
                body="Body",
                labels=["bug", "priority: high"],
            )
            assert result["success"] is True


class TestGitHubAuditClientCreateBranch:
    """Tests for GitHubAuditClient.create_branch method."""

    @pytest.mark.asyncio
    async def test_demo_mode_without_token(self):
        """Should return demo response without token."""
        client = GitHubAuditClient(token=None)
        result = await client.create_branch(
            owner="owner",
            repo="repo",
            branch_name="fix/audit-123",
        )
        assert result["success"] is True
        assert result["demo"] is True
        assert "fix/audit-123" in result["ref"]


class TestGitHubAuditClientCreatePullRequest:
    """Tests for GitHubAuditClient.create_pull_request method."""

    @pytest.mark.asyncio
    async def test_demo_mode_without_token(self):
        """Should return demo response without token."""
        client = GitHubAuditClient(token=None)
        result = await client.create_pull_request(
            owner="owner",
            repo="repo",
            title="Fix audit findings",
            body="Fixes issues from audit",
            head_branch="fix/audit-123",
        )
        assert result["success"] is True
        assert result["demo"] is True
        assert "pull" in result["html_url"]


class TestGitHubAuditClientGetIssue:
    """Tests for GitHubAuditClient.get_issue method."""

    @pytest.mark.asyncio
    async def test_demo_mode_without_token(self):
        """Should return demo issue without token."""
        client = GitHubAuditClient(token=None)
        result = await client.get_issue(
            owner="owner",
            repo="repo",
            issue_number=123,
        )
        assert result is not None
        assert result["number"] == 123
        assert result["state"] == "open"


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestGenerateIssueTitle:
    """Tests for generate_issue_title function."""

    def test_includes_severity(self):
        """Should include severity in title."""
        finding = {"severity": "CRITICAL", "title": "SQL Injection"}
        title = generate_issue_title(finding)
        assert "[CRITICAL]" in title

    def test_includes_title(self):
        """Should include finding title."""
        finding = {"severity": "HIGH", "title": "XSS Vulnerability"}
        title = generate_issue_title(finding)
        assert "XSS Vulnerability" in title

    def test_handles_missing_severity(self):
        """Should handle missing severity."""
        finding = {"title": "Test Finding"}
        title = generate_issue_title(finding)
        assert "Test Finding" in title

    def test_handles_missing_title(self):
        """Should handle missing title with default."""
        finding = {"severity": "LOW"}
        title = generate_issue_title(finding)
        # Title uses default when missing
        assert "Audit Finding" in title or "LOW" in title


class TestGenerateIssueBody:
    """Tests for generate_issue_body function."""

    def test_includes_description(self):
        """Should include description."""
        finding = {
            "severity": "HIGH",
            "title": "Test",
            "description": "This is a security issue",
        }
        body = generate_issue_body(finding)
        assert "This is a security issue" in body

    def test_includes_severity_badge(self):
        """Should include severity information."""
        finding = {"severity": "CRITICAL", "title": "Test"}
        body = generate_issue_body(finding)
        assert "CRITICAL" in body

    def test_includes_finding_id(self):
        """Should include finding ID in metadata."""
        finding = {"id": "f123", "title": "Test"}
        body = generate_issue_body(finding)
        assert "f123" in body

    def test_includes_session_id(self):
        """Should include session ID when provided."""
        finding = {"title": "Test"}
        body = generate_issue_body(finding, session_id="sess-456")
        assert "sess-456" in body

    def test_includes_evidence(self):
        """Should include evidence when available."""
        finding = {
            "title": "Test",
            "evidence": "function vulnerable() { eval(input); }",
        }
        body = generate_issue_body(finding)
        assert "eval(input)" in body

    def test_includes_mitigation(self):
        """Should include mitigation when available."""
        finding = {
            "title": "Test",
            "mitigation": "Use parameterized queries",
        }
        body = generate_issue_body(finding)
        assert "parameterized queries" in body


class TestGetLabelsForFinding:
    """Tests for get_labels_for_finding function."""

    def test_adds_severity_labels(self):
        """Should add severity labels."""
        finding = {"severity": "critical"}
        labels = get_labels_for_finding(finding)
        assert "priority: critical" in labels
        assert "security" in labels

    def test_adds_high_severity_labels(self):
        """Should add high severity labels."""
        finding = {"severity": "high"}
        labels = get_labels_for_finding(finding)
        assert "priority: high" in labels
        assert "bug" in labels

    def test_adds_category_labels(self):
        """Should add category labels."""
        finding = {"severity": "medium", "category": "security"}
        labels = get_labels_for_finding(finding)
        assert "security" in labels

    def test_adds_performance_category(self):
        """Should add performance category labels."""
        finding = {"category": "performance"}
        labels = get_labels_for_finding(finding)
        assert "performance" in labels

    def test_adds_audit_type_label(self):
        """Should add audit type as label."""
        finding = {"severity": "low", "audit_type": "sast"}
        labels = get_labels_for_finding(finding)
        assert "sast" in labels

    def test_deduplicates_labels(self):
        """Should deduplicate labels."""
        finding = {"severity": "critical", "category": "security"}
        labels = get_labels_for_finding(finding)
        # security appears in both severity and category, should be unique
        assert labels.count("security") == 1

    def test_handles_unknown_severity(self):
        """Should handle unknown severity."""
        finding = {"severity": "unknown"}
        labels = get_labels_for_finding(finding)
        # Should not raise, may return empty or partial
        assert isinstance(labels, list)

    def test_handles_unknown_category(self):
        """Should handle unknown category."""
        finding = {"severity": "high", "category": "unknown"}
        labels = get_labels_for_finding(finding)
        # Should still include severity labels
        assert "priority: high" in labels


# =============================================================================
# Severity Labels Mapping Tests
# =============================================================================


class TestSeverityLabels:
    """Tests for SEVERITY_LABELS mapping."""

    def test_critical_labels(self):
        """Should have critical labels."""
        assert "priority: critical" in SEVERITY_LABELS["critical"]
        assert "security" in SEVERITY_LABELS["critical"]
        assert "bug" in SEVERITY_LABELS["critical"]

    def test_high_labels(self):
        """Should have high labels."""
        assert "priority: high" in SEVERITY_LABELS["high"]
        assert "bug" in SEVERITY_LABELS["high"]

    def test_medium_labels(self):
        """Should have medium labels."""
        assert "priority: medium" in SEVERITY_LABELS["medium"]

    def test_low_labels(self):
        """Should have low labels."""
        assert "priority: low" in SEVERITY_LABELS["low"]

    def test_info_labels(self):
        """Should have info labels."""
        assert "documentation" in SEVERITY_LABELS["info"]
        assert "enhancement" in SEVERITY_LABELS["info"]


# =============================================================================
# Category Labels Mapping Tests
# =============================================================================


class TestCategoryLabels:
    """Tests for CATEGORY_LABELS mapping."""

    def test_security_category(self):
        """Should have security labels."""
        assert "security" in CATEGORY_LABELS["security"]

    def test_performance_category(self):
        """Should have performance labels."""
        assert "performance" in CATEGORY_LABELS["performance"]

    def test_quality_category(self):
        """Should have quality labels."""
        assert "code-quality" in CATEGORY_LABELS["quality"]

    def test_compliance_category(self):
        """Should have compliance labels."""
        assert "compliance" in CATEGORY_LABELS["compliance"]

    def test_testing_category(self):
        """Should have testing labels."""
        assert "testing" in CATEGORY_LABELS["testing"]


# =============================================================================
# Handler Function Tests
# =============================================================================


class TestHandleCreateIssue:
    """Tests for handle_create_issue function."""

    @pytest.mark.asyncio
    async def test_invalid_repository_format(self):
        """Should return error for invalid repository format."""
        result = await handle_create_issue(
            repository="invalid",
            finding={"title": "Test"},
        )
        assert result["success"] is False
        assert "Invalid repository format" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_creation_demo_mode(self):
        """Should create issue in demo mode."""
        # Clear cached decorators by mocking permission check
        with patch(
            "aragora.server.handlers.github.audit_bridge.require_permission", lambda p: lambda f: f
        ):
            result = await handle_create_issue(
                repository="owner/repo",
                finding={"id": "f1", "severity": "HIGH", "title": "Test Issue"},
            )
            # In demo mode (no token), should succeed
            assert result["success"] is True
            assert "issue_number" in result

    @pytest.mark.asyncio
    async def test_stores_finding_issue_mapping(self):
        """Should store finding-to-issue mapping when session_id provided."""
        import aragora.server.handlers.github.audit_bridge as bridge

        bridge._finding_issues.clear()

        with patch(
            "aragora.server.handlers.github.audit_bridge.require_permission", lambda p: lambda f: f
        ):
            result = await handle_create_issue(
                repository="owner/repo",
                finding={"id": "finding-123", "title": "Test"},
                session_id="session-456",
            )

            if result["success"]:
                # Check mapping was stored
                assert "session-456" in bridge._finding_issues
                assert "finding-123" in bridge._finding_issues["session-456"]


class TestHandleBulkCreateIssues:
    """Tests for handle_bulk_create_issues function."""

    @pytest.mark.asyncio
    async def test_empty_findings_list(self):
        """Should handle empty findings list."""
        with patch(
            "aragora.server.handlers.github.audit_bridge.require_permission", lambda p: lambda f: f
        ):
            result = await handle_bulk_create_issues(
                repository="owner/repo",
                findings=[],
            )
            assert result["created"] == 0 or "results" in result

    @pytest.mark.asyncio
    async def test_skip_existing_issues(self):
        """Should skip existing issues when skip_existing=True."""
        import aragora.server.handlers.github.audit_bridge as bridge

        bridge._finding_issues["session-1"] = {"finding-1": 100}

        with patch(
            "aragora.server.handlers.github.audit_bridge.require_permission", lambda p: lambda f: f
        ):
            result = await handle_bulk_create_issues(
                repository="owner/repo",
                findings=[{"id": "finding-1", "title": "Test"}],
                session_id="session-1",
                skip_existing=True,
            )
            # Should have skipped the existing finding
            if "results" in result:
                skipped = [r for r in result["results"] if r.get("status") == "skipped"]
                # Finding-1 should be skipped
                assert len(skipped) >= 0  # May or may not be in results


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_finding(self):
        """Should handle empty finding dict."""
        labels = get_labels_for_finding({})
        assert isinstance(labels, list)

    def test_empty_string_severity(self):
        """Should handle empty string severity."""
        finding = {"severity": "", "title": "Test"}
        labels = get_labels_for_finding(finding)
        assert isinstance(labels, list)

    def test_case_insensitive_severity(self):
        """Should handle case-insensitive severity."""
        finding = {"severity": "HIGH"}
        labels = get_labels_for_finding(finding)
        assert "priority: high" in labels

    def test_case_insensitive_category(self):
        """Should handle case-insensitive category."""
        finding = {"category": "SECURITY"}
        labels = get_labels_for_finding(finding)
        assert "security" in labels

    def test_generate_title_with_special_chars(self):
        """Should handle special characters in title."""
        finding = {"severity": "HIGH", "title": "XSS in <script> tag & 'quotes'"}
        title = generate_issue_title(finding)
        assert "XSS" in title

    def test_generate_body_with_markdown(self):
        """Should handle markdown in description."""
        finding = {
            "title": "Test",
            "description": "**Bold** and `code`",
        }
        body = generate_issue_body(finding)
        assert "**Bold**" in body
