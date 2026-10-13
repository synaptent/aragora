"""
HTTP API Handlers for GitHub Pull Request Review.

Provides REST APIs for automated PR review:
- Trigger multi-agent PR review
- Get PR details and diff
- Submit review comments
- Manage review state

Endpoints:
- POST /api/v1/github/pr/review - Trigger PR review
- GET /api/v1/github/pr/{pr_number} - Get PR details
- POST /api/v1/github/pr/{pr_number}/review - Submit review
- GET /api/v1/github/pr/{pr_number}/reviews - List reviews
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    success_response,
    handle_errors,
)
from aragora.server.handlers.utils.decorators import require_permission
from aragora.services import ServiceRegistry

if TYPE_CHECKING:
    from aragora.connectors.github import GitHubConnector

logger = logging.getLogger(__name__)

# =============================================================================
# Bug Detector Lazy Import
# =============================================================================

_bug_detector_imported = False
_BugDetector: Any = None
_BugSeverity: Any = None


def _import_bug_detector():
    """Lazy import bug detector to avoid circular imports."""
    global _bug_detector_imported, _BugDetector, _BugSeverity
    if _bug_detector_imported:
        return _BugDetector is not None
    _bug_detector_imported = True
    try:
        from aragora.analysis.codebase.bug_detector import BugDetector, BugSeverity

        _BugDetector = BugDetector
        _BugSeverity = BugSeverity
        return True
    except ImportError as e:
        logger.debug("BugDetector not available: %s", e)
        return False


# =============================================================================
# Data Models
# =============================================================================


class ReviewVerdict(str, Enum):
    """PR review verdict."""

    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    COMMENT = "COMMENT"


class ReviewStatus(str, Enum):
    """Status of automated review."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReviewComment:
    """A single review comment."""

    id: str
    file_path: str
    line: int
    body: str
    side: str = "RIGHT"  # LEFT or RIGHT
    suggestion: str | None = None
    severity: str = "info"  # info, warning, error
    category: str = "general"  # quality, security, performance, etc.

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "file_path": self.file_path,
            "line": self.line,
            "body": self.body,
            "side": self.side,
            "suggestion": self.suggestion,
            "severity": self.severity,
            "category": self.category,
        }


@dataclass
class PRReviewResult:
    """Result of an automated PR review."""

    review_id: str
    pr_number: int
    repository: str
    status: ReviewStatus
    verdict: ReviewVerdict | None = None
    summary: str | None = None
    comments: list[ReviewComment] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "pr_number": self.pr_number,
            "repository": self.repository,
            "status": self.status.value,
            "verdict": self.verdict.value if self.verdict else None,
            "summary": self.summary,
            "comments": [c.to_dict() for c in self.comments],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "metrics": self.metrics,
        }


@dataclass
class PRDetails:
    """Pull request details."""

    number: int
    title: str
    body: str
    state: str
    author: str
    base_branch: str
    head_branch: str
    diff: str | None = None
    changed_files: list[dict[str, Any]] = field(default_factory=list)
    commits: list[dict[str, Any]] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "body": self.body,
            "state": self.state,
            "author": self.author,
            "base_branch": self.base_branch,
            "head_branch": self.head_branch,
            "changed_files": self.changed_files,
            "commits": self.commits,
            "labels": self.labels,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# =============================================================================
# In-Memory Storage (replace with database in production)
# =============================================================================

_review_results: dict[str, PRReviewResult] = {}  # review_id -> result
_pr_reviews: dict[str, list[str]] = {}  # "repo/pr_number" -> [review_ids]
_storage_lock = threading.Lock()
_running_reviews: dict[str, asyncio.Task] = {}

# =============================================================================
# GitHub API Client (with ServiceRegistry integration)
# =============================================================================


class GitHubClient:
    """
    GitHub API client with ServiceRegistry integration.

    Uses GitHubConnector from service registry when available,
    falls back to direct API calls or demo data.
    """

    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.base_url = "https://api.github.com"
        self._connector: GitHubConnector | None = None
        self._init_connector()

    def _init_connector(self) -> None:
        """Initialize GitHubConnector from service registry if available."""
        try:
            from aragora.connectors.github import GitHubConnector

            registry = ServiceRegistry.get()
            if registry.has(GitHubConnector):
                self._connector = registry.resolve(GitHubConnector)
                logger.debug("Using GitHubConnector from service registry")
            elif self.token:
                # Create and register a new connector
                self._connector = GitHubConnector(token=self.token)
                registry.register(GitHubConnector, self._connector)
                logger.info("Created and registered GitHubConnector")
        except (ImportError, AttributeError, TypeError, ValueError) as e:
            logger.debug("GitHubConnector not available, using direct API: %s", e)

    async def get_pr(self, owner: str, repo: str, pr_number: int) -> PRDetails | None:
        """Get PR details from GitHub API."""
        from aragora.server.http_client_pool import get_http_pool

        # Try using the connector first
        if self._connector:
            try:
                return await self._get_pr_via_connector(owner, repo, pr_number)
            except (
                ConnectionError,
                TimeoutError,
                OSError,
                ValueError,
                KeyError,
                AttributeError,
            ) as e:
                logger.warning("Connector failed, falling back to direct API: %s", e)

        if not self.token:
            # Return demo data
            return self._demo_pr(pr_number)

        try:
            headers = {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json",
            }

            pool = get_http_pool()
            async with pool.get_session("github_pr_review") as client:
                # Get PR details
                url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
                response = await client.get(url, headers=headers)
                if response.status_code != 200:
                    return self._demo_pr(pr_number)
                data = response.json()

                # Get files
                files_url = f"{url}/files"
                files_response = await client.get(files_url, headers=headers)
                files = files_response.json() if files_response.status_code == 200 else []

                return PRDetails(
                    number=data["number"],
                    title=data["title"],
                    body=data.get("body") or "",
                    state=data["state"],
                    author=data["user"]["login"],
                    base_branch=data["base"]["ref"],
                    head_branch=data["head"]["ref"],
                    changed_files=[
                        {
                            "filename": f["filename"],
                            "status": f["status"],
                            "additions": f["additions"],
                            "deletions": f["deletions"],
                            "patch": f.get("patch", ""),
                        }
                        for f in files
                    ],
                    labels=[label["name"] for label in data.get("labels", [])],
                    created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
                    updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")),
                )

        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
            logger.exception("Failed to fetch PR: %s", e)
            return self._demo_pr(pr_number)

    async def _get_pr_via_connector(
        self, owner: str, repo: str, pr_number: int
    ) -> PRDetails | None:
        """Get PR details using GitHubConnector."""
        if not self._connector:
            return None

        # Use connector's search to get PR
        results = await self._connector.search(
            query=f"repo:{owner}/{repo} is:pr {pr_number}",
            limit=1,
            search_type="prs",
        )

        if not results:
            return None

        # Get the first result and fetch full details
        pr_evidence = results[0]
        pr_data = pr_evidence.raw_data if hasattr(pr_evidence, "raw_data") else {}

        return PRDetails(
            number=pr_number,
            title=pr_data.get("title", f"PR #{pr_number}"),
            body=pr_data.get("body", ""),
            state=pr_data.get("state", "open"),
            author=pr_data.get("user", {}).get("login", "unknown"),
            base_branch=pr_data.get("base", {}).get("ref", "main"),
            head_branch=pr_data.get("head", {}).get("ref", f"feature-{pr_number}"),
            changed_files=pr_data.get("files", []),
            labels=pr_data.get("labels", []),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    async def submit_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        event: ReviewVerdict,
        body: str,
        comments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Submit a review to GitHub."""
        from aragora.server.http_client_pool import get_http_pool

        if not self.token:
            return {"success": True, "demo": True}

        try:
            headers = {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json",
            }

            payload: dict[str, Any] = {
                "event": event.value,
                "body": body,
            }
            if comments:
                payload["comments"] = comments

            pool = get_http_pool()
            async with pool.get_session("github_pr_review") as client:
                url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code in (200, 201):
                    return {"success": True, "data": response.json()}
                else:
                    error = response.text
                    return {"success": False, "error": error}

        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
            logger.exception("Failed to submit review: %s", e)
            return {"success": False, "error": "Internal server error"}

    def _demo_pr(self, pr_number: int) -> PRDetails:
        """Return demo PR data."""
        return PRDetails(
            number=pr_number,
            title=f"Demo PR #{pr_number}: Add feature implementation",
            body="This PR adds a new feature to the codebase.\n\n## Changes\n- Added new module\n- Updated tests\n- Fixed lint errors",
            state="open",
            author="demo-user",
            base_branch="main",
            head_branch=f"feature/demo-{pr_number}",
            changed_files=[
                {
                    "filename": "src/feature.py",
                    "status": "added",
                    "additions": 50,
                    "deletions": 0,
                    "patch": "@@ -0,0 +1,50 @@\n+def new_feature():\n+    pass",
                },
                {
                    "filename": "tests/test_feature.py",
                    "status": "added",
                    "additions": 30,
                    "deletions": 0,
                    "patch": "@@ -0,0 +1,30 @@\n+import pytest",
                },
                {
                    "filename": "README.md",
                    "status": "modified",
                    "additions": 5,
                    "deletions": 2,
                    "patch": "@@ -10,2 +10,5 @@\n-Old content\n+New content",
                },
            ],
            labels=["enhancement", "review-needed"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )


# =============================================================================
# Review Handlers
# =============================================================================


@require_permission("github:create")
async def handle_trigger_pr_review(
    repository: str,
    pr_number: int,
    review_type: str = "comprehensive",
    workspace_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Trigger an automated PR review.

    POST /api/v1/github/pr/review
    {
        "repository": "owner/repo",
        "pr_number": 123,
        "review_type": "comprehensive"  # or "quick", "security"
    }
    """
    try:
        review_id = f"review_{uuid.uuid4().hex[:12]}"
        pr_key = f"{repository}/{pr_number}"

        # Check if review already running
        if pr_key in _running_reviews:
            task = _running_reviews[pr_key]
            if not task.done():
                return {
                    "success": False,
                    "error": "Review already in progress for this PR",
                }

        # Create initial result
        result = PRReviewResult(
            review_id=review_id,
            pr_number=pr_number,
            repository=repository,
            status=ReviewStatus.IN_PROGRESS,
        )

        with _storage_lock:
            _review_results[review_id] = result
            if pr_key not in _pr_reviews:
                _pr_reviews[pr_key] = []
            _pr_reviews[pr_key].append(review_id)

        # Start async review
        async def run_review():
            try:
                # Parse repository
                parts = repository.split("/")
                if len(parts) != 2:
                    raise ValueError("Invalid repository format")
                owner, repo = parts

                # Fetch PR details
                client = GitHubClient()
                pr_details = await client.get_pr(owner, repo, pr_number)
                if not pr_details:
                    raise ValueError("Could not fetch PR details")

                # Perform review (simplified - in real implementation would use debate)
                comments, verdict, summary = await _perform_review(pr_details, review_type)

                # Update result
                with _storage_lock:
                    result.status = ReviewStatus.COMPLETED
                    result.verdict = verdict
                    result.summary = summary
                    result.comments = comments
                    result.completed_at = datetime.now(timezone.utc)
                    result.metrics = {
                        "files_reviewed": len(pr_details.changed_files),
                        "comments_generated": len(comments),
                        "review_type": review_type,
                    }

                logger.info(
                    "[PRReview] Completed review %s for %s#%s: %s",
                    review_id,
                    repository,
                    pr_number,
                    verdict.value,
                )

            except (
                ValueError,
                KeyError,
                TypeError,
                RuntimeError,
                OSError,
                ConnectionError,
            ) as e:  # for async review task
                logger.exception("Review %s failed: %s", review_id, e)
                with _storage_lock:
                    result.status = ReviewStatus.FAILED
                    result.error = "Internal server error"
                    result.completed_at = datetime.now(timezone.utc)

            finally:
                if pr_key in _running_reviews:
                    del _running_reviews[pr_key]

        # Create and store task
        task = asyncio.create_task(run_review())
        _running_reviews[pr_key] = task

        logger.info("[PRReview] Started review %s for %s#%s", review_id, repository, pr_number)

        return {
            "success": True,
            "review_id": review_id,
            "status": "in_progress",
            "pr_number": pr_number,
            "repository": repository,
        }

    except (ValueError, KeyError, TypeError, RuntimeError, OSError, ConnectionError) as e:
        logger.exception("Failed to trigger PR review: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


async def _run_bug_detector_analysis(
    pr_details: PRDetails,
) -> tuple[list[ReviewComment], list[str]]:
    """
    Run bug detector analysis on changed files.

    Args:
        pr_details: The pull request details containing changed files

    Returns:
        Tuple of (review comments, critical issues found)
    """
    import ast as ast_module
    import re

    comments: list[ReviewComment] = []
    critical_issues: list[str] = []

    if not _import_bug_detector():
        return comments, critical_issues

    try:
        detector = _BugDetector()

        for file_info in pr_details.changed_files:
            filename = file_info.get("filename", "")
            patch = file_info.get("patch", "")

            # Only analyze Python files for now
            if not filename.endswith(".py"):
                continue

            # Skip test files for bug detection
            if "test_" in filename or "/tests/" in filename:
                continue

            # Extract added lines from the patch with line mapping
            added_lines: list[str] = []
            line_mapping: dict[int, int] = {}  # Maps pseudo-line to actual PR line
            current_line = 0
            for line in patch.split("\n"):
                if line.startswith("@@"):
                    # Parse the line number from the hunk header
                    match = re.search(r"\+(\d+)", line)
                    if match:
                        current_line = int(match.group(1)) - 1
                elif line.startswith("+") and not line.startswith("+++"):
                    current_line += 1
                    pseudo_line = len(added_lines) + 1
                    line_mapping[pseudo_line] = current_line
                    added_lines.append(line[1:])  # Remove the + prefix
                elif line.startswith("-"):
                    pass  # Removed line, don't increment
                else:
                    current_line += 1

            if not added_lines:
                continue

            # Construct pseudo-file content for analysis
            code_content = "\n".join(added_lines)

            # Parse AST if possible
            ast_tree = None
            try:
                ast_tree = ast_module.parse(code_content)
            except SyntaxError:
                # Partial code may not parse - that's OK
                pass

            # Run each detector pattern
            for pattern in detector.patterns:
                try:
                    findings = pattern.detect(code_content, filename, ast_tree)
                    for finding in findings:
                        # Filter by confidence
                        if finding.confidence < detector.min_confidence:
                            continue

                        # Map BugSeverity to comment severity
                        severity_map = {
                            _BugSeverity.CRITICAL: "error",
                            _BugSeverity.HIGH: "error",
                            _BugSeverity.MEDIUM: "warning",
                            _BugSeverity.LOW: "info",
                        }
                        severity = severity_map.get(finding.severity, "info")

                        # Track critical issues
                        if finding.severity in (_BugSeverity.CRITICAL, _BugSeverity.HIGH):
                            critical_issues.append(f"bug_{finding.bug_type.value}")

                        # Build the comment body
                        bug_name = finding.bug_type.value.replace("_", " ").title()
                        body = f"**{bug_name}**: {finding.message}"
                        if finding.description:
                            body += f"\n\n{finding.description}"
                        if finding.suggested_fix:
                            body += f"\n\n**Suggested fix:** {finding.suggested_fix}"

                        # Map the pseudo-line to actual PR line
                        pseudo_line = finding.line_number
                        actual_line = line_mapping.get(pseudo_line, pseudo_line)

                        comments.append(
                            ReviewComment(
                                id=f"bugdet_{uuid.uuid4().hex[:8]}",
                                file_path=filename,
                                line=actual_line,
                                body=body,
                                severity=severity,
                                category="bug_detection",
                                suggestion=finding.suggested_fix,
                            )
                        )
                except (TypeError, ValueError, KeyError, AttributeError) as pe:
                    logger.debug("Pattern %s failed: %s", pattern.__class__.__name__, pe)
                    continue

        logger.info(
            "[PRReview] Bug detector found %s issues across %s files",
            len(comments),
            len(pr_details.changed_files),
        )

    except (TypeError, ValueError, KeyError, AttributeError, OSError) as e:
        logger.warning("Bug detector analysis failed: %s", e)

    return comments, critical_issues


async def _perform_review(
    pr_details: PRDetails,
    review_type: str,
    use_debate: bool = True,
) -> tuple[list[ReviewComment], ReviewVerdict, str]:
    """
    Perform the actual review analysis.

    When use_debate=True and Arena is available, uses multi-agent debate
    for comprehensive code review. Falls back to heuristic analysis.

    Args:
        pr_details: The pull request details to review
        review_type: Type of review ("comprehensive", "quick", "security")
        use_debate: Whether to use multi-agent debate (default True)

    Returns:
        Tuple of (comments, verdict, summary)
    """
    # Try multi-agent debate if enabled
    if use_debate and review_type in ("comprehensive", "security"):
        try:
            debate_result = await _perform_debate_review(pr_details, review_type)
            if debate_result:
                # Even if debate succeeds, run bug detector for additional findings
                bug_comments, bug_issues = await _run_bug_detector_analysis(pr_details)
                if bug_comments:
                    debate_comments, debate_verdict, debate_summary = debate_result
                    combined_comments = debate_comments + bug_comments
                    # Upgrade verdict if bug detector found critical issues
                    if bug_issues and debate_verdict == ReviewVerdict.APPROVE:
                        return (
                            combined_comments,
                            ReviewVerdict.REQUEST_CHANGES,
                            f"{debate_summary}\n\nBug detector found critical issues that require attention.",
                        )
                    return combined_comments, debate_verdict, debate_summary
                return debate_result
        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.warning("Debate review failed, falling back to heuristic: %s", e)

    # Run bug detector analysis first
    bug_comments, bug_issues = await _run_bug_detector_analysis(pr_details)

    # Fallback to heuristic analysis
    comments = list(bug_comments)  # Start with bug detector findings
    issues_found = list(bug_issues)

    # Analyze each changed file
    for file in pr_details.changed_files:
        filename = file["filename"]
        patch = file.get("patch", "")

        # Check for common issues (simplified analysis)
        if "TODO" in patch or "FIXME" in patch:
            comments.append(
                ReviewComment(
                    id=f"comment_{uuid.uuid4().hex[:8]}",
                    file_path=filename,
                    line=1,
                    body="Consider addressing TODO/FIXME comments before merging.",
                    severity="info",
                    category="quality",
                )
            )

        if "console.log" in patch or "print(" in patch:
            comments.append(
                ReviewComment(
                    id=f"comment_{uuid.uuid4().hex[:8]}",
                    file_path=filename,
                    line=1,
                    body="Debug logging detected. Consider removing before merging.",
                    severity="warning",
                    category="quality",
                )
            )
            issues_found.append("debug_logging")

        if "password" in patch.lower() or "secret" in patch.lower():
            if "test" not in filename.lower():
                comments.append(
                    ReviewComment(
                        id=f"comment_{uuid.uuid4().hex[:8]}",
                        file_path=filename,
                        line=1,
                        body="Potential sensitive data detected. Please verify no secrets are hardcoded.",
                        severity="error",
                        category="security",
                    )
                )
                issues_found.append("potential_secrets")

        # Check for missing tests using TestGeneratorAgent when available
        if filename.endswith(".py") and "test_" not in filename:
            has_test = any(
                f["filename"].startswith("test_") or "/tests/" in f["filename"]
                for f in pr_details.changed_files
            )
            if not has_test:
                test_body = "Consider adding tests for the changes in this file."
                try:
                    from aragora.agents.test_generator import TestGeneratorAgent

                    generator = TestGeneratorAgent()
                    gaps = generator.analyze_coverage_gaps(
                        code=patch,
                        existing_tests="",
                        file_path=filename,
                    )
                    if gaps:
                        suggestions = []
                        for gap in gaps[:3]:
                            if gap.suggested_tests:
                                suggestions.extend(gap.suggested_tests[:2])
                        if suggestions:
                            test_body = "Missing test coverage. Suggested tests:\n" + "\n".join(
                                f"- `{s}`" for s in suggestions[:5]
                            )
                except (ImportError, ValueError, TypeError, AttributeError):
                    pass

                comments.append(
                    ReviewComment(
                        id=f"comment_{uuid.uuid4().hex[:8]}",
                        file_path=filename,
                        line=1,
                        body=test_body,
                        severity="info",
                        category="quality",
                    )
                )

    # Determine verdict
    # Check for critical bug detector findings
    critical_bugs = [i for i in issues_found if i.startswith("bug_")]

    if "potential_secrets" in issues_found:
        verdict = ReviewVerdict.REQUEST_CHANGES
        summary = (
            "Security concerns detected. Please address the highlighted issues before merging."
        )
    elif critical_bugs:
        verdict = ReviewVerdict.REQUEST_CHANGES
        bug_types = ", ".join(b.replace("bug_", "").replace("_", " ") for b in critical_bugs)
        summary = (
            f"Bug detector found critical issues ({bug_types}). Please address before merging."
        )
    elif "debug_logging" in issues_found:
        verdict = ReviewVerdict.COMMENT
        summary = "Minor issues detected. Consider addressing the suggestions."
    elif len(comments) > 0:
        verdict = ReviewVerdict.APPROVE
        summary = "LGTM with minor suggestions. Good work!"
    else:
        verdict = ReviewVerdict.APPROVE
        summary = "Looks good to me! No issues detected."

    return comments, verdict, summary


async def _perform_debate_review(
    pr_details: PRDetails,
    review_type: str,
) -> tuple[list[ReviewComment], ReviewVerdict, str] | None:
    """
    Perform code review using multi-agent debate.

    Creates an Arena with code review agents that analyze the PR
    from different perspectives (quality, security, architecture).

    Returns:
        Tuple of (comments, verdict, summary) or None if debate unavailable
    """
    try:
        from aragora.debate.orchestrator import Arena
        from aragora.protocols.debate import DebateProtocol
        from aragora.core import Environment

        # Build the review context
        diff_context = "\n".join(
            f"File: {f['filename']}\n{f.get('patch', '')[:2000]}"
            for f in pr_details.changed_files[:10]  # Limit files for context
        )

        task = f"""Review this pull request:

Title: {pr_details.title}
Author: {pr_details.author}
Base: {pr_details.base_branch} <- {pr_details.head_branch}

Description:
{pr_details.body[:2000] if pr_details.body else "No description provided."}

Changes ({len(pr_details.changed_files)} files):
{diff_context}

Provide a thorough code review covering:
1. Code quality and best practices
2. Potential bugs or issues
3. Security concerns
4. Test coverage
5. Architecture and design

Format your response as:
- VERDICT: APPROVE | REQUEST_CHANGES | COMMENT
- SUMMARY: Brief summary of the review
- COMMENTS: List of specific file:line comments"""

        # Create environment for the debate
        env = Environment(task=task)

        # Configure protocol based on review type
        if review_type == "security":
            protocol = DebateProtocol(
                rounds=2,
                consensus="majority",
                require_reasoning=True,
            )
        else:
            protocol = DebateProtocol(
                rounds=2,
                consensus="majority",
            )

        # Create and run the arena
        # Use positional args as Arena expects (environment, agents, protocol)
        # Pass empty agents list to let Arena use defaults
        async with Arena(env, [], protocol) as arena:
            result = await arena.run()

        # Parse the debate result
        if result and result.final_answer:
            return _parse_debate_result(result.final_answer, pr_details)

        return None

    except ImportError:
        logger.debug("Arena not available for debate review")
        return None
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
        logger.warning("Debate review error: %s", e)
        return None


def _parse_debate_result(
    answer: str,
    pr_details: PRDetails,
) -> tuple[list[ReviewComment], ReviewVerdict, str]:
    """Parse debate result into structured review."""
    import re

    comments = []
    verdict = ReviewVerdict.COMMENT
    summary = "Review completed via multi-agent analysis."

    # Extract verdict
    verdict_match = re.search(r"VERDICT:\s*(APPROVE|REQUEST_CHANGES|COMMENT)", answer, re.I)
    if verdict_match:
        verdict_str = verdict_match.group(1).upper()
        try:
            verdict = ReviewVerdict(verdict_str)
        except ValueError:
            pass

    # Extract summary
    summary_match = re.search(r"SUMMARY:\s*(.+?)(?=\n\n|COMMENTS:|$)", answer, re.DOTALL)
    if summary_match:
        summary = summary_match.group(1).strip()[:500]

    # Extract comments (look for file:line patterns)
    comment_pattern = re.compile(
        r"(?:[-*]\s*)?([^\s:]+\.(?:py|ts|js|tsx|jsx|go|rs|java|rb)):(\d+)?\s*[-:]\s*(.+?)(?=\n[-*]|\n\n|$)",
        re.MULTILINE | re.DOTALL,
    )

    for match in comment_pattern.finditer(answer):
        file_path = match.group(1)
        line = int(match.group(2)) if match.group(2) else 1
        body = match.group(3).strip()

        # Determine severity based on content
        severity = "info"
        if any(word in body.lower() for word in ("security", "vulnerability", "injection", "xss")):
            severity = "error"
        elif any(word in body.lower() for word in ("should", "consider", "recommend")):
            severity = "warning"

        comments.append(
            ReviewComment(
                id=f"debate_{uuid.uuid4().hex[:8]}",
                file_path=file_path,
                line=line,
                body=body[:500],
                severity=severity,
                category="debate_review",
            )
        )

    return comments, verdict, summary


@require_permission("github:read")
async def handle_get_pr_details(
    repository: str,
    pr_number: int,
) -> dict[str, Any]:
    """
    Get PR details.

    GET /api/v1/github/pr/{pr_number}?repository=owner/repo
    """
    try:
        parts = repository.split("/")
        if len(parts) != 2:
            return {"success": False, "error": "Invalid repository format"}
        owner, repo = parts

        client = GitHubClient()
        pr_details = await client.get_pr(owner, repo, pr_number)

        if not pr_details:
            return {"success": False, "error": "PR not found"}

        return {
            "success": True,
            "pr": pr_details.to_dict(),
        }

    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
        logger.exception("Failed to get PR details: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@require_permission("github:read")
async def handle_get_review_status(
    review_id: str,
) -> dict[str, Any]:
    """
    Get review status/result.

    GET /api/v1/github/pr/review/{review_id}
    """
    try:
        with _storage_lock:
            result = _review_results.get(review_id)

        if not result:
            return {"success": False, "error": "Review not found"}

        return {
            "success": True,
            "review": result.to_dict(),
        }

    except (KeyError, ValueError, TypeError, AttributeError) as e:
        logger.exception("Failed to get review status: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@require_permission("github:read")
async def handle_list_pr_reviews(
    repository: str,
    pr_number: int,
) -> dict[str, Any]:
    """
    List reviews for a PR.

    GET /api/v1/github/pr/{pr_number}/reviews?repository=owner/repo
    """
    try:
        pr_key = f"{repository}/{pr_number}"

        with _storage_lock:
            review_ids = _pr_reviews.get(pr_key, [])
            reviews = [
                _review_results[rid].to_dict() for rid in review_ids if rid in _review_results
            ]

        return {
            "success": True,
            "reviews": reviews,
            "total": len(reviews),
        }

    except (KeyError, ValueError, TypeError, AttributeError) as e:
        logger.exception("Failed to list PR reviews: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@require_permission("connectors:create")
async def handle_submit_review(
    repository: str,
    pr_number: int,
    event: str,
    body: str,
    comments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Submit a review to GitHub.

    POST /api/v1/github/pr/{pr_number}/review
    {
        "repository": "owner/repo",
        "event": "APPROVE",
        "body": "LGTM!",
        "comments": []
    }
    """
    try:
        parts = repository.split("/")
        if len(parts) != 2:
            return {"success": False, "error": "Invalid repository format"}
        owner, repo = parts

        try:
            verdict = ReviewVerdict(event)
        except ValueError:
            return {"success": False, "error": f"Invalid event: {event}"}

        client = GitHubClient()
        result = await client.submit_review(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            event=verdict,
            body=body,
            comments=comments,
        )

        return result

    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
        logger.exception("Failed to submit review: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


# =============================================================================
# Handler Class
# =============================================================================


class PRReviewHandler(BaseHandler):
    """
    HTTP handler for PR review endpoints.

    Integrates with the Aragora server routing system.
    """

    ROUTES = [
        "/api/v1/github/pr/review",
    ]

    ROUTE_PREFIXES = [
        "/api/v1/github/pr/",
    ]

    def __init__(self, ctx: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(ctx)

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        if path in self.ROUTES:
            return True
        for prefix in self.ROUTE_PREFIXES:
            if path.startswith(prefix):
                return True
        return False

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route PR review endpoint requests."""
        return None

    @handle_errors("p r review operation")
    @require_permission("github:pr:review")
    async def handle_post_trigger_review(self, data: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/github/pr/review"""
        repository = data.get("repository")
        pr_number = data.get("pr_number")

        if not repository or not pr_number:
            return error_response("repository and pr_number required", 400)

        result = await handle_trigger_pr_review(
            repository=repository,
            pr_number=pr_number,
            review_type=data.get("review_type", "comprehensive"),
            workspace_id=data.get("workspace_id"),
            user_id=self._get_user_id(),
        )

        if result.get("success"):
            return success_response(result)
        else:
            return error_response(result.get("error", "Unknown error"), 400)

    @require_permission("github:pr:read")
    async def handle_get_pr(self, params: dict[str, Any], pr_number: int) -> HandlerResult:
        """GET /api/v1/github/pr/{pr_number}"""
        repository = params.get("repository")
        if not repository:
            return error_response("repository required", 400)

        result = await handle_get_pr_details(
            repository=repository,
            pr_number=pr_number,
        )

        if result.get("success"):
            return success_response(result)
        else:
            return error_response(result.get("error", "Unknown error"), 404)

    @require_permission("github:pr:read")
    async def handle_get_review_status(
        self, params: dict[str, Any], review_id: str
    ) -> HandlerResult:
        """GET /api/v1/github/pr/review/{review_id}"""
        result = await handle_get_review_status(review_id=review_id)

        if result.get("success"):
            return success_response(result)
        else:
            return error_response(result.get("error", "Unknown error"), 404)

    @require_permission("github:pr:read")
    async def handle_list_reviews(self, params: dict[str, Any], pr_number: int) -> HandlerResult:
        """GET /api/v1/github/pr/{pr_number}/reviews"""
        repository = params.get("repository")
        if not repository:
            return error_response("repository required", 400)

        result = await handle_list_pr_reviews(
            repository=repository,
            pr_number=pr_number,
        )

        if result.get("success"):
            return success_response(result)
        else:
            return error_response(result.get("error", "Unknown error"), 400)

    @handle_errors("p r review operation")
    @require_permission("github:pr:write")
    async def handle_post_submit_review(
        self, data: dict[str, Any], pr_number: int
    ) -> HandlerResult:
        """POST /api/v1/github/pr/{pr_number}/review"""
        repository = data.get("repository")
        event = data.get("event")
        body = data.get("body", "")

        if not repository or not event:
            return error_response("repository and event required", 400)

        result = await handle_submit_review(
            repository=repository,
            pr_number=pr_number,
            event=event,
            body=body,
            comments=data.get("comments"),
        )

        if result.get("success"):
            return success_response(result)
        else:
            return error_response(result.get("error", "Unknown error"), 400)

    def _get_user_id(self) -> str:
        """Get user ID from auth context."""
        auth_ctx = self.ctx.get("auth_context")
        if auth_ctx and hasattr(auth_ctx, "user_id"):
            return auth_ctx.user_id
        return "default"
