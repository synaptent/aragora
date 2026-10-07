"""
Code Review Agent.

Multi-agent code review orchestrator that coordinates specialized reviewers:
- Security reviewer (vulnerabilities, injection, auth issues)
- Performance reviewer (bottlenecks, complexity, resource usage)
- Maintainability reviewer (code quality, patterns, readability)
- Test coverage reviewer (test gaps, assertion quality)

Synthesizes findings and can debate conflicting recommendations.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aragora.agents.base import BaseDebateAgent
from aragora.core_types import Critique, Message

logger = logging.getLogger(__name__)


class ReviewCategory(str, Enum):
    """Categories of code review findings."""

    SECURITY = "security"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"
    TEST_COVERAGE = "test_coverage"
    BUG = "bug"
    STYLE = "style"
    DOCUMENTATION = "documentation"
    ARCHITECTURE = "architecture"


class FindingSeverity(str, Enum):
    """Severity levels for findings."""

    CRITICAL = "critical"  # Must fix before merge
    HIGH = "high"  # Should fix before merge
    MEDIUM = "medium"  # Recommended fix
    LOW = "low"  # Nice to have
    INFO = "info"  # Informational


@dataclass
class CodeLocation:
    """Location of code in a file."""

    file_path: str
    start_line: int
    end_line: int | None = None
    code_snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "filePath": self.file_path,
            "startLine": self.start_line,
            "endLine": self.end_line,
            "codeSnippet": self.code_snippet,
        }


@dataclass
class ReviewFinding:
    """A single code review finding."""

    id: str
    category: ReviewCategory
    severity: FindingSeverity
    title: str
    description: str
    location: CodeLocation | None = None
    suggestion: str = ""
    suggested_code: str = ""
    reviewer: str = ""
    confidence: float = 0.8
    references: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "location": self.location.to_dict() if self.location else None,
            "suggestion": self.suggestion,
            "suggestedCode": self.suggested_code,
            "reviewer": self.reviewer,
            "confidence": self.confidence,
            "references": self.references,
            "tags": self.tags,
        }


@dataclass
class ReviewResult:
    """Aggregated code review result."""

    pr_url: str | None = None
    files_reviewed: int = 0
    lines_reviewed: int = 0
    findings: list[ReviewFinding] = field(default_factory=list)
    summary: str = ""
    approval_status: str = "pending"  # approved, changes_requested, pending
    by_category: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    reviewers_participated: list[str] = field(default_factory=list)
    consensus_notes: list[str] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return len([f for f in self.findings if f.severity == FindingSeverity.CRITICAL])

    @property
    def high_count(self) -> int:
        return len([f for f in self.findings if f.severity == FindingSeverity.HIGH])

    @property
    def should_block_merge(self) -> bool:
        return self.critical_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "prUrl": self.pr_url,
            "filesReviewed": self.files_reviewed,
            "linesReviewed": self.lines_reviewed,
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
            "approvalStatus": self.approval_status,
            "byCategory": self.by_category,
            "bySeverity": self.by_severity,
            "criticalCount": self.critical_count,
            "highCount": self.high_count,
            "shouldBlockMerge": self.should_block_merge,
            "reviewersParticipated": self.reviewers_participated,
            "consensusNotes": self.consensus_notes,
        }


# Security vulnerability patterns
SECURITY_PATTERNS = [
    (r"eval\s*\(", "Use of eval() - potential code injection", FindingSeverity.CRITICAL),
    (r"exec\s*\(", "Use of exec() - potential code injection", FindingSeverity.CRITICAL),
    (
        r"subprocess\..*shell\s*=\s*True",
        "Shell injection risk with subprocess",
        FindingSeverity.HIGH,
    ),
    (
        r"\.format\s*\(.*user|input|request",
        "Potential format string injection",
        FindingSeverity.MEDIUM,
    ),
    (r"password\s*=\s*['\"][^'\"]+['\"]", "Hardcoded password detected", FindingSeverity.CRITICAL),
    (
        r"api[_-]?key\s*=\s*['\"][^'\"]+['\"]",
        "Hardcoded API key detected",
        FindingSeverity.CRITICAL,
    ),
    (r"secret\s*=\s*['\"][^'\"]+['\"]", "Hardcoded secret detected", FindingSeverity.HIGH),
    (r"pickle\.load", "Unsafe pickle deserialization", FindingSeverity.HIGH),
    (r"yaml\.load\s*\([^,]+\)", "Unsafe YAML load (use safe_load)", FindingSeverity.HIGH),
    (r"SELECT.*\+.*input|request", "Potential SQL injection", FindingSeverity.CRITICAL),
    (r"innerHTML\s*=", "Potential XSS via innerHTML", FindingSeverity.HIGH),
    (r"dangerouslySetInnerHTML", "React dangerouslySetInnerHTML usage", FindingSeverity.MEDIUM),
]

# Performance patterns
PERFORMANCE_PATTERNS = [
    (r"for.*in.*range.*len\(", "Use enumerate() instead of range(len())", FindingSeverity.LOW),
    (r"\+\s*=.*in.*for", "String concatenation in loop - use join()", FindingSeverity.MEDIUM),
    (r"time\.sleep\s*\(\s*[1-9]\d*", "Long sleep() call may block", FindingSeverity.MEDIUM),
    (r"\.read\(\)", "Reading entire file at once - consider streaming", FindingSeverity.LOW),
    (r"import\s+\*", "Wildcard import - may slow down startup", FindingSeverity.LOW),
    (
        r"@property\s*\n.*def.*\n.*for.*in",
        "Complex property getter - consider caching",
        FindingSeverity.LOW,
    ),
]

# Maintainability patterns
MAINTAINABILITY_PATTERNS = [
    (r"except:\s*$", "Bare except clause - catches all exceptions", FindingSeverity.MEDIUM),
    (r"except\s+Exception:", "Catching broad Exception", FindingSeverity.LOW),
    (r"#\s*TODO", "TODO comment found", FindingSeverity.INFO),
    (r"#\s*FIXME", "FIXME comment found", FindingSeverity.LOW),
    (r"#\s*HACK", "HACK comment found", FindingSeverity.MEDIUM),
    (r"def\s+\w+\([^)]{100,}\)", "Function with too many parameters", FindingSeverity.MEDIUM),
    (r"^\s{40,}", "Deeply nested code", FindingSeverity.MEDIUM),
    (r"global\s+\w+", "Global variable usage", FindingSeverity.LOW),
    (r"print\s*\(", "Print statement (use logging instead)", FindingSeverity.LOW),
]


class SecurityReviewer(BaseDebateAgent):
    """Agent specialized in security review."""

    def __init__(self, **kwargs):
        # Initialize Agent attributes directly to avoid ABC init issues
        self.name = kwargs.get("name", "security_reviewer")
        self.model = kwargs.get("model", "pattern-based")
        self.role = kwargs.get("role", "proposer")
        self.agent_type = "security_reviewer"
        self.stance = "neutral"
        self.persona = ""
        self.focus = "security"
        self.system_prompt = """You are a Security Code Reviewer specializing in identifying vulnerabilities.

FOCUS AREAS:
- Injection vulnerabilities (SQL, command, XSS)
- Authentication and authorization issues
- Sensitive data exposure
- Cryptographic weaknesses
- Input validation gaps
- Security misconfigurations

When reviewing code, look for:
1. User input that flows to dangerous functions
2. Missing authentication checks
3. Hardcoded secrets or credentials
4. Insecure cryptographic practices
5. Missing input sanitization

Output findings in format:
FINDING: [title]
SEVERITY: critical|high|medium|low
LOCATION: [file:line]
DESCRIPTION: [detailed explanation]
SUGGESTION: [how to fix]
CWE: [CWE-XXX if applicable]"""
        self._finding_counter = 0

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate response - stub for pattern-based reviewer."""
        return ""

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        """Critique - stub for pattern-based reviewer."""
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:200],
            issues=[],
            suggestions=[],
            severity=0.0,
            reasoning="Pattern-based reviewer",
        )

    async def review(self, code: str, language: str = "python") -> list[ReviewFinding]:
        """
        Review code for security vulnerabilities.

        Args:
            code: Source code to review
            language: Programming language

        Returns:
            List of security findings
        """
        findings = []
        lines = code.split("\n")

        for pattern, description, severity in SECURITY_PATTERNS:
            for i, line in enumerate(lines):
                if re.search(pattern, line, re.IGNORECASE):
                    self._finding_counter += 1
                    findings.append(
                        ReviewFinding(
                            id=f"sec_{self._finding_counter}",
                            category=ReviewCategory.SECURITY,
                            severity=severity,
                            title=description,
                            description=f"Found in line {i + 1}: {line.strip()[:100]}",
                            location=CodeLocation(
                                file_path="unknown",
                                start_line=i + 1,
                                code_snippet=line.strip(),
                            ),
                            reviewer="security_reviewer",
                        )
                    )

        return findings


class PerformanceReviewer(BaseDebateAgent):
    """Agent specialized in performance review."""

    def __init__(self, **kwargs):
        # Initialize Agent attributes directly to avoid ABC init issues
        self.name = kwargs.get("name", "performance_reviewer")
        self.model = kwargs.get("model", "pattern-based")
        self.role = kwargs.get("role", "proposer")
        self.agent_type = "performance_reviewer"
        self.stance = "neutral"
        self.persona = ""
        self.focus = "performance"
        self.system_prompt = """You are a Performance Code Reviewer specializing in optimization.

FOCUS AREAS:
- Algorithm complexity (Big O)
- Memory usage and leaks
- Database query efficiency
- Caching opportunities
- Async/concurrent code issues
- Resource management

When reviewing code, look for:
1. N+1 query patterns
2. Unnecessary loops or iterations
3. Memory-intensive operations
4. Missing indexes or inefficient queries
5. Blocking operations in async code

Output findings in format:
FINDING: [title]
SEVERITY: critical|high|medium|low
LOCATION: [file:line]
DESCRIPTION: [detailed explanation]
IMPACT: [performance impact estimate]
SUGGESTION: [how to optimize]"""
        self._finding_counter = 0

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate response - stub for pattern-based reviewer."""
        return ""

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        """Critique - stub for pattern-based reviewer."""
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:200],
            issues=[],
            suggestions=[],
            severity=0.0,
            reasoning="Pattern-based reviewer",
        )

    async def review(self, code: str, language: str = "python") -> list[ReviewFinding]:
        """
        Review code for performance issues.

        Args:
            code: Source code to review
            language: Programming language

        Returns:
            List of performance findings
        """
        findings = []
        lines = code.split("\n")

        for pattern, description, severity in PERFORMANCE_PATTERNS:
            for i, line in enumerate(lines):
                if re.search(pattern, line, re.IGNORECASE):
                    self._finding_counter += 1
                    findings.append(
                        ReviewFinding(
                            id=f"perf_{self._finding_counter}",
                            category=ReviewCategory.PERFORMANCE,
                            severity=severity,
                            title=description,
                            description=f"Found in line {i + 1}: {line.strip()[:100]}",
                            location=CodeLocation(
                                file_path="unknown",
                                start_line=i + 1,
                                code_snippet=line.strip(),
                            ),
                            reviewer="performance_reviewer",
                        )
                    )

        return findings


class MaintainabilityReviewer(BaseDebateAgent):
    """Agent specialized in code quality and maintainability review."""

    def __init__(self, **kwargs):
        # Initialize Agent attributes directly to avoid ABC init issues
        self.name = kwargs.get("name", "maintainability_reviewer")
        self.model = kwargs.get("model", "pattern-based")
        self.role = kwargs.get("role", "proposer")
        self.agent_type = "maintainability_reviewer"
        self.stance = "neutral"
        self.persona = ""
        self.focus = "maintainability"
        self.system_prompt = """You are a Code Quality Reviewer specializing in maintainability.

FOCUS AREAS:
- Code readability and clarity
- Design patterns and architecture
- SOLID principles adherence
- Code duplication (DRY)
- Proper error handling
- Documentation quality

When reviewing code, look for:
1. Complex or confusing logic
2. Missing or inadequate documentation
3. Inconsistent coding style
4. Tight coupling between components
5. Missing error handling

Output findings in format:
FINDING: [title]
SEVERITY: critical|high|medium|low
LOCATION: [file:line]
DESCRIPTION: [detailed explanation]
PRINCIPLE: [violated principle if applicable]
SUGGESTION: [how to improve]"""
        self._finding_counter = 0

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate response - stub for pattern-based reviewer."""
        return ""

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        """Critique - stub for pattern-based reviewer."""
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:200],
            issues=[],
            suggestions=[],
            severity=0.0,
            reasoning="Pattern-based reviewer",
        )

    async def review(self, code: str, language: str = "python") -> list[ReviewFinding]:
        """
        Review code for maintainability issues.

        Args:
            code: Source code to review
            language: Programming language

        Returns:
            List of maintainability findings
        """
        findings = []
        lines = code.split("\n")

        for pattern, description, severity in MAINTAINABILITY_PATTERNS:
            for i, line in enumerate(lines):
                if re.search(pattern, line, re.IGNORECASE):
                    self._finding_counter += 1
                    findings.append(
                        ReviewFinding(
                            id=f"maint_{self._finding_counter}",
                            category=ReviewCategory.MAINTAINABILITY,
                            severity=severity,
                            title=description,
                            description=f"Found in line {i + 1}: {line.strip()[:100]}",
                            location=CodeLocation(
                                file_path="unknown",
                                start_line=i + 1,
                                code_snippet=line.strip(),
                            ),
                            reviewer="maintainability_reviewer",
                        )
                    )

        return findings


class TestCoverageReviewer(BaseDebateAgent):
    """Agent specialized in test coverage review."""

    __test__ = False  # Not a pytest test class

    def __init__(self, **kwargs):
        # Initialize Agent attributes directly to avoid ABC init issues
        self.name = kwargs.get("name", "test_coverage_reviewer")
        self.model = kwargs.get("model", "pattern-based")
        self.role = kwargs.get("role", "proposer")
        self.agent_type = "test_coverage_reviewer"
        self.stance = "neutral"
        self.persona = ""
        self.focus = "test_coverage"
        self.system_prompt = """You are a Test Coverage Reviewer specializing in testing quality.

FOCUS AREAS:
- Missing test coverage
- Edge case coverage
- Test quality and assertions
- Test independence
- Mocking practices
- Integration test gaps

When reviewing code, look for:
1. New code without corresponding tests
2. Missing edge case tests
3. Weak or missing assertions
4. Test dependencies or ordering issues
5. Untested error paths

Output findings in format:
FINDING: [title]
SEVERITY: critical|high|medium|low
LOCATION: [file:line]
DESCRIPTION: [detailed explanation]
SUGGESTED_TEST: [test case suggestion]
PRIORITY: [1-5]"""

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate response - stub for pattern-based reviewer."""
        return ""

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        """Critique - stub for pattern-based reviewer."""
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:200],
            issues=[],
            suggestions=[],
            severity=0.0,
            reasoning="Pattern-based reviewer",
        )


class CodeReviewOrchestrator:
    """
    Orchestrates multi-agent code review.

    Coordinates multiple specialized reviewers, aggregates findings,
    and can facilitate debates on conflicting recommendations.
    """

    def __init__(
        self,
        arena: Any | None = None,
        enable_security: bool = True,
        enable_performance: bool = True,
        enable_maintainability: bool = True,
        enable_test_coverage: bool = True,
    ):
        """
        Initialize code review orchestrator.

        Args:
            arena: Optional Arena for multi-agent debates
            enable_security: Run security review
            enable_performance: Run performance review
            enable_maintainability: Run maintainability review
            enable_test_coverage: Run test coverage review
        """
        self.arena = arena
        self.reviewers: list[tuple[str, bool]] = []

        if enable_security:
            self.reviewers.append(("security", True))
        if enable_performance:
            self.reviewers.append(("performance", True))
        if enable_maintainability:
            self.reviewers.append(("maintainability", True))
        if enable_test_coverage:
            self.reviewers.append(("test_coverage", True))

        # Finding counter for IDs
        self._finding_counter = 0

    async def review_code(
        self,
        code: str,
        file_path: str = "unknown",
        context: str | None = None,
    ) -> ReviewResult:
        """
        Review a single code file.

        Args:
            code: Source code to review
            file_path: Path to the file
            context: Additional context about the code

        Returns:
            Review result with findings
        """
        result = ReviewResult(
            files_reviewed=1,
            lines_reviewed=len(code.split("\n")),
        )

        # Run pattern-based reviews in parallel
        security_findings = self._pattern_review(
            code, file_path, SECURITY_PATTERNS, ReviewCategory.SECURITY, "security_pattern"
        )
        performance_findings = self._pattern_review(
            code, file_path, PERFORMANCE_PATTERNS, ReviewCategory.PERFORMANCE, "performance_pattern"
        )
        maintainability_findings = self._pattern_review(
            code,
            file_path,
            MAINTAINABILITY_PATTERNS,
            ReviewCategory.MAINTAINABILITY,
            "maintainability_pattern",
        )

        result.findings.extend(security_findings)
        result.findings.extend(performance_findings)
        result.findings.extend(maintainability_findings)

        # Track reviewers
        for reviewer_type, enabled in self.reviewers:
            if enabled:
                result.reviewers_participated.append(reviewer_type)

        # Aggregate by category and severity
        result.by_category = self._count_by_field(result.findings, "category")
        result.by_severity = self._count_by_field(result.findings, "severity")

        # Generate summary
        result.summary = self._generate_summary(result)

        # Determine approval status
        if result.critical_count > 0:
            result.approval_status = "changes_requested"
        elif result.high_count > 3:
            result.approval_status = "changes_requested"
        elif result.high_count > 0:
            result.approval_status = "pending"
        else:
            result.approval_status = "approved"

        return result

    async def review_diff(
        self,
        diff: str,
        base_branch: str = "main",
        pr_url: str | None = None,
    ) -> ReviewResult:
        """
        Review a code diff (e.g., from a PR).

        Args:
            diff: Git diff content
            base_branch: Base branch name
            pr_url: Pull request URL

        Returns:
            Review result with findings
        """
        result = ReviewResult(pr_url=pr_url)

        # Parse diff to extract files and changes
        files = self._parse_diff(diff)
        result.files_reviewed = len(files)

        for file_path, added_lines, removed_lines in files:
            # Focus review on added/changed lines
            code = "\n".join(added_lines)
            result.lines_reviewed += len(added_lines)

            # Review the added code
            file_result = await self.review_code(code, file_path)
            result.findings.extend(file_result.findings)

        # Aggregate
        result.by_category = self._count_by_field(result.findings, "category")
        result.by_severity = self._count_by_field(result.findings, "severity")
        result.summary = self._generate_summary(result)

        if result.critical_count > 0:
            result.approval_status = "changes_requested"
        elif result.high_count > 3:
            result.approval_status = "changes_requested"
        elif len(result.findings) > 10:
            result.approval_status = "pending"
        else:
            result.approval_status = "approved"

        return result

    async def review_pr(
        self,
        pr_url: str,
        review_types: list[str] | None = None,
        post_comments: bool = False,
    ) -> ReviewResult:
        """
        Review a GitHub pull request.

        Args:
            pr_url: Pull request URL
            review_types: Types of reviews to run (security, performance, etc.)
            post_comments: Whether to post comments back to GitHub

        Returns:
            Review result
        """
        from aragora.connectors.github import GitHubConnector

        result = ReviewResult(pr_url=pr_url)

        # Initialize GitHub connector
        github = GitHubConnector()

        # Fetch PR diff
        diff = await github.fetch_pr_diff(pr_url)
        if not diff:
            result.summary = (
                f"Could not fetch diff from {pr_url} (ensure 'gh' CLI is authenticated)"
            )
            result.approval_status = "pending"
            return result

        # Fetch file list for metadata
        files = await github.fetch_pr_files(pr_url)
        if files:
            result.files_reviewed = len(files)

        # Review the diff
        result = await self.review_diff(
            diff=diff,
            pr_url=pr_url,
        )

        # Update PR URL in result
        result.pr_url = pr_url

        # Optionally post comments back to GitHub
        if post_comments and result.findings:
            comments = self.generate_github_comments(result)
            if comments:
                # Format review body
                review_body = self._format_pr_review_body(result)
                event = (
                    "REQUEST_CHANGES" if result.approval_status == "changes_required" else "COMMENT"
                )

                # Post the review
                success = await github.post_pr_review(
                    pr_url=pr_url,
                    body=review_body,
                    event=event,
                    comments=comments,
                )
                if success:
                    logger.info("Posted review to %s with %s comments", pr_url, len(comments))
                else:
                    logger.warning("Failed to post review to %s", pr_url)

        return result

    def _format_pr_review_body(self, result: ReviewResult) -> str:
        """Format the main PR review body."""
        lines = ["## Code Review Summary", ""]
        lines.append(result.summary)
        lines.append("")

        # Severity breakdown
        severity_counts = self._count_by_field(result.findings, "severity")
        if severity_counts:
            lines.append("### Findings by Severity")
            for severity in ["critical", "high", "medium", "low", "info"]:
                count = severity_counts.get(severity, 0)
                if count > 0:
                    lines.append(f"- **{severity.upper()}**: {count}")
            lines.append("")

        # Category breakdown
        category_counts = self._count_by_field(result.findings, "category")
        if category_counts:
            lines.append("### Findings by Category")
            for category, count in sorted(category_counts.items(), key=lambda x: -x[1]):
                lines.append(f"- {category}: {count}")
            lines.append("")

        lines.append("---")
        lines.append("*Review generated by Aragora Code Review*")

        return "\n".join(lines)

    def _pattern_review(
        self,
        code: str,
        file_path: str,
        patterns: list[tuple[str, str, FindingSeverity]],
        category: ReviewCategory,
        reviewer: str,
    ) -> list[ReviewFinding]:
        """Run pattern-based review."""
        findings = []
        lines = code.split("\n")

        for pattern, description, severity in patterns:
            for line_num, line in enumerate(lines, 1):
                if re.search(pattern, line, re.IGNORECASE):
                    self._finding_counter += 1
                    finding = ReviewFinding(
                        id=f"F{self._finding_counter:04d}",
                        category=category,
                        severity=severity,
                        title=description,
                        description=f"Pattern matched: {pattern}",
                        location=CodeLocation(
                            file_path=file_path,
                            start_line=line_num,
                            code_snippet=line.strip()[:100],
                        ),
                        reviewer=reviewer,
                        confidence=0.9,
                    )
                    findings.append(finding)

        return findings

    def _parse_diff(self, diff: str) -> list[tuple[str, list[str], list[str]]]:
        """
        Parse git diff to extract file changes.

        Returns list of (file_path, added_lines, removed_lines)
        """
        files: list[tuple[str, list[str], list[str]]] = []
        current_file: str | None = None
        added_lines: list[str] = []
        removed_lines: list[str] = []

        for line in diff.split("\n"):
            if line.startswith("diff --git"):
                if current_file:
                    files.append((current_file, added_lines, removed_lines))
                # Extract file path
                parts = line.split(" b/")
                current_file = parts[-1] if len(parts) > 1 else "unknown"
                added_lines = []
                removed_lines = []
            elif line.startswith("+") and not line.startswith("+++"):
                added_lines.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                removed_lines.append(line[1:])

        if current_file:
            files.append((current_file, added_lines, removed_lines))

        return files

    def _count_by_field(self, findings: list[ReviewFinding], field: str) -> dict[str, int]:
        """Count findings by a field."""
        counts: dict[str, int] = {}
        for finding in findings:
            value = getattr(finding, field)
            if hasattr(value, "value"):
                value = value.value
            counts[value] = counts.get(value, 0) + 1
        return counts

    def _generate_summary(self, result: ReviewResult) -> str:
        """Generate review summary."""
        parts = [f"Reviewed {result.files_reviewed} files, {result.lines_reviewed} lines."]

        total_findings = len(result.findings)
        if total_findings == 0:
            parts.append("No issues found.")
        else:
            parts.append(f"Found {total_findings} issues:")
            if result.critical_count > 0:
                parts.append(f"- {result.critical_count} critical")
            if result.high_count > 0:
                parts.append(f"- {result.high_count} high")

            medium_count = len([f for f in result.findings if f.severity == FindingSeverity.MEDIUM])
            low_count = len([f for f in result.findings if f.severity == FindingSeverity.LOW])
            if medium_count > 0:
                parts.append(f"- {medium_count} medium")
            if low_count > 0:
                parts.append(f"- {low_count} low")

        return " ".join(parts)

    async def debate_findings(
        self,
        findings: list[ReviewFinding],
        topic: str = "conflicting recommendations",
    ) -> list[str]:
        """
        Use multi-agent debate to resolve conflicting findings.

        Args:
            findings: Conflicting findings to debate
            topic: Debate topic

        Returns:
            Consensus notes from debate
        """
        if not self.arena:
            return ["No arena configured for debate"]

        try:
            from aragora.debate.orchestrator import Arena
            from aragora.protocols.debate import DebateProtocol
            from aragora.core import Environment

            findings_text = "\n".join(
                f"- [{f.severity.value.upper()}] {f.category.value}: "
                f"{f.description}" + (f" (suggestion: {f.suggestion})" if f.suggestion else "")
                for f in findings
            )

            env = Environment(
                task=(
                    f"Resolve conflicting code review findings on: {topic}\n\n"
                    f"Findings ({len(findings)}):\n{findings_text}\n\n"
                    f"For each finding, determine priority, validity, and "
                    f"recommended resolution. Provide actionable consensus."
                ),
            )
            protocol = DebateProtocol(rounds=2, consensus="majority")

            async with Arena(env, [], protocol) as arena:
                result = await arena.run()

            if result and result.final_answer:
                return [
                    f"Debate consensus on {topic}:",
                    result.final_answer,
                ]

            return [f"Debate on {topic} completed without consensus"]

        except ImportError:
            return ["Arena not available for debate review"]
        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.warning("Code review debate failed: %s", e)
            return [f"Debate on {topic} encountered an error"]

    def generate_github_comments(
        self,
        result: ReviewResult,
        max_comments: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Generate GitHub PR review comments from findings.

        Args:
            result: Review result
            max_comments: Maximum number of comments

        Returns:
            List of comment objects for GitHub API
        """
        comments = []

        # Prioritize by severity
        sorted_findings = sorted(
            result.findings,
            key=lambda f: ["critical", "high", "medium", "low", "info"].index(f.severity.value),
        )

        for finding in sorted_findings[:max_comments]:
            if not finding.location:
                continue

            comment = {
                "path": finding.location.file_path,
                "line": finding.location.start_line,
                "body": self._format_comment(finding),
            }
            comments.append(comment)

        return comments

    def _format_comment(self, finding: ReviewFinding) -> str:
        """Format a finding as a GitHub comment."""
        severity_emoji = {
            FindingSeverity.CRITICAL: "🚨",
            FindingSeverity.HIGH: "⚠️",
            FindingSeverity.MEDIUM: "📝",
            FindingSeverity.LOW: "💡",
            FindingSeverity.INFO: "ℹ️",
        }

        emoji = severity_emoji.get(finding.severity, "📝")
        lines = [
            f"{emoji} **{finding.severity.value.upper()}**: {finding.title}",
            "",
            finding.description,
        ]

        if finding.suggestion:
            lines.extend(["", f"**Suggestion:** {finding.suggestion}"])

        if finding.suggested_code:
            lines.extend(["", "```python", finding.suggested_code, "```"])

        return "\n".join(lines)
