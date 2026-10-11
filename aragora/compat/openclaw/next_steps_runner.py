"""
OpenClaw Next Steps Runner.

Scans a repository and identifies prioritized next actions using
multi-signal analysis. This is the "tell me what to do next" engine.

Signals collected:
  - Source code markers (TODO, FIXME, HACK, XXX)
  - Open GitHub issues and PRs
  - Test failures and coverage gaps
  - Dependency health (outdated, vulnerable)
  - Documentation gaps
  - Security patterns

Usage:
    from aragora.compat.openclaw.next_steps_runner import NextStepsRunner

    runner = NextStepsRunner(repo_path=".")
    result = await runner.scan()
    for step in result.steps:
        print(f"[{step.priority}] {step.title}")
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Marker patterns to scan for in source code
_MARKER_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, category, default_priority)
    (r"\bFIXME\b[:\s]*(.*)", "bug", "high"),
    (r"\bTODO\b[:\s]*(.*)", "enhancement", "medium"),
    (r"\bHACK\b[:\s]*(.*)", "tech-debt", "medium"),
    (r"\bXXX\b[:\s]*(.*)", "tech-debt", "high"),
    (r"\bWORKAROUND\b[:\s]*(.*)", "tech-debt", "low"),
    (r"\bDEPRECATED\b[:\s]*(.*)", "maintenance", "medium"),
    (r"\bSECURITY\b[:\s]*(.*)", "security", "high"),
    (r"\bPERF\b[:\s]*(.*)", "performance", "medium"),
]

# File extensions to scan
_SCANNABLE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".php",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".swift",
    ".kt",
    ".scala",
    ".sh",
    ".bash",
    ".yaml",
    ".yml",
    ".toml",
}

# Directories to skip
_SKIP_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
    "vendor",
}

# Priority ordering for sorting
_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

# Max files to scan (safety limit)
_MAX_FILES = 5000
_MAX_ISSUES = 100


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class NextStep:
    """A single recommended next action."""

    title: str
    description: str
    category: str  # bug, enhancement, tech-debt, security, maintenance, performance, docs
    priority: str  # critical, high, medium, low
    effort: str  # small, medium, large
    source: str  # code-marker, github-issue, test-failure, dep-check, doc-gap, security-scan
    file_path: str | None = None
    line_number: int | None = None
    url: str | None = None  # GitHub issue/PR URL
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def sort_key(self) -> tuple[int, str]:
        return (_PRIORITY_ORDER.get(self.priority, 99), self.title)


@dataclass
class ScanReceipt:
    """Audit receipt for a completed scan."""

    scan_id: str
    repo: str
    started_at: float
    completed_at: float
    steps_count: int
    files_scanned: int
    signals_by_source: dict[str, int]
    checksum: str  # SHA-256 of steps

    @property
    def duration_seconds(self) -> float:
        return self.completed_at - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "repo": self.repo,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "steps_count": self.steps_count,
            "files_scanned": self.files_scanned,
            "signals_by_source": self.signals_by_source,
            "checksum": self.checksum,
        }


@dataclass
class ScanResult:
    """Result of a next-steps scan."""

    repo: str
    steps: list[NextStep]
    receipt: ScanReceipt | None = None
    error: str | None = None

    @property
    def by_priority(self) -> dict[str, list[NextStep]]:
        """Group steps by priority."""
        groups: dict[str, list[NextStep]] = {}
        for step in self.steps:
            groups.setdefault(step.priority, []).append(step)
        return groups

    @property
    def by_category(self) -> dict[str, list[NextStep]]:
        """Group steps by category."""
        groups: dict[str, list[NextStep]] = {}
        for step in self.steps:
            groups.setdefault(step.category, []).append(step)
        return groups

    def top(self, n: int = 10) -> list[NextStep]:
        """Return top N steps by priority."""
        return sorted(self.steps, key=lambda s: s.sort_key)[:n]


# ---------------------------------------------------------------------------
# Scanners (each returns a list of NextStep)
# ---------------------------------------------------------------------------


def scan_code_markers(repo_path: Path) -> tuple[list[NextStep], int]:
    """Scan source code for TODO/FIXME/HACK markers."""
    steps: list[NextStep] = []
    files_scanned = 0

    for root, dirs, files in os.walk(repo_path):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]

        for filename in files:
            ext = Path(filename).suffix.lower()
            if ext not in _SCANNABLE_EXTENSIONS:
                continue

            filepath = Path(root) / filename
            files_scanned += 1

            if files_scanned > _MAX_FILES:
                break

            try:
                content = filepath.read_text(errors="replace")
            except OSError as exc:
                logger.debug("Failed to read %s: %s", filepath, exc)
                continue

            rel_path = str(filepath.relative_to(repo_path))

            for line_num, line in enumerate(content.splitlines(), 1):
                for pattern, category, default_priority in _MARKER_PATTERNS:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        comment_text = match.group(1).strip()
                        if not comment_text:
                            comment_text = f"{pattern.split(chr(92))[0].strip()} in {rel_path}"

                        # Truncate long comments
                        if len(comment_text) > 200:
                            comment_text = comment_text[:197] + "..."

                        steps.append(
                            NextStep(
                                title=comment_text[:80],
                                description=f"Found `{match.group(0).strip()[:60]}` at {rel_path}:{line_num}",
                                category=category,
                                priority=default_priority,
                                effort="small",
                                source="code-marker",
                                file_path=rel_path,
                                line_number=line_num,
                                metadata={
                                    "marker": pattern.split("\\b")[1]
                                    if "\\b" in pattern
                                    else "TODO"
                                },
                            )
                        )
                        break  # Only match first pattern per line

        if files_scanned > _MAX_FILES:
            break

    return steps, files_scanned


def scan_github_issues(repo: str, limit: int = _MAX_ISSUES) -> list[NextStep]:
    """Scan open GitHub issues for actionable items."""
    try:
        result = subprocess.run(  # subprocess with fixed args, no shell
            [  # fixed command
                "gh",
                "issue",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--limit",
                str(limit),
                "--json",
                "number,title,labels,url,body",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.debug("gh issue list failed: %s", result.stderr)
            return []

        issues = json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        logger.debug("GitHub issues scan failed: %s", exc)
        return []

    steps = []
    for issue in issues:
        labels = [lb.get("name", "") for lb in issue.get("labels", [])]
        priority = _infer_issue_priority(labels)
        category = _infer_issue_category(labels)
        body = (issue.get("body") or "")[:200]

        steps.append(
            NextStep(
                title=issue["title"][:80],
                description=body if body else f"Issue #{issue['number']}",
                category=category,
                priority=priority,
                effort=_infer_effort(labels),
                source="github-issue",
                url=issue.get("url"),
                metadata={"number": issue["number"], "labels": labels},
            )
        )

    return steps


def scan_github_prs(repo: str, limit: int = 20) -> list[NextStep]:
    """Scan open PRs that need attention."""
    try:
        result = subprocess.run(  # subprocess with fixed args, no shell
            [  # fixed command
                "gh",
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--limit",
                str(limit),
                "--json",
                "number,title,url,reviewDecision,isDraft,createdAt",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.debug("gh pr list failed: %s", result.stderr)
            return []

        prs = json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        logger.debug("GitHub PRs scan failed: %s", exc)
        return []

    steps = []
    for pr in prs:
        if pr.get("isDraft"):
            continue
        review = pr.get("reviewDecision", "")
        if review == "APPROVED":
            steps.append(
                NextStep(
                    title=f"Merge approved PR #{pr['number']}: {pr['title'][:50]}",
                    description=f"PR #{pr['number']} is approved and ready to merge.",
                    category="maintenance",
                    priority="high",
                    effort="small",
                    source="github-pr",
                    url=pr.get("url"),
                    metadata={"number": pr["number"], "review": review},
                )
            )
        elif review in ("CHANGES_REQUESTED", ""):
            steps.append(
                NextStep(
                    title=f"Review PR #{pr['number']}: {pr['title'][:50]}",
                    description=f"PR #{pr['number']} needs review or has requested changes.",
                    category="maintenance",
                    priority="medium",
                    effort="medium",
                    source="github-pr",
                    url=pr.get("url"),
                    metadata={"number": pr["number"], "review": review},
                )
            )

    return steps


def scan_test_failures(repo_path: Path) -> list[NextStep]:
    """Run a quick test discovery to find obvious failures."""
    # Only attempt if pytest is available and there's a tests/ dir
    test_dir = repo_path / "tests"
    if not test_dir.is_dir():
        return []

    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "--collect-only", "-q", "--no-header"],  # fixed command
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(repo_path),
        )
        # Parse collection errors
        stderr = result.stderr
        if "ERROR" in stderr:
            errors = re.findall(r"ERROR\s+(.*)", stderr)
            steps = []
            for err in errors[:10]:  # Cap at 10
                steps.append(
                    NextStep(
                        title=f"Fix test collection error: {err[:60]}",
                        description=f"Test collection failed: {err}",
                        category="bug",
                        priority="high",
                        effort="medium",
                        source="test-failure",
                        metadata={"error": err},
                    )
                )
            return steps
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("Test failure scan failed: %s", exc)

    return []


def scan_dependency_health(repo_path: Path) -> list[NextStep]:
    """Check for outdated or vulnerable dependencies."""
    steps = []

    # Check Python dependencies
    requirements = repo_path / "requirements.txt"
    pyproject = repo_path / "pyproject.toml"
    if requirements.exists() or pyproject.exists():
        try:
            result = subprocess.run(
                ["pip", "list", "--outdated", "--format=json"],  # fixed command
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(repo_path),
            )
            if result.returncode == 0:
                outdated = json.loads(result.stdout)
                if len(outdated) > 10:
                    steps.append(
                        NextStep(
                            title=f"Update {len(outdated)} outdated Python dependencies",
                            description="Multiple packages have newer versions available. "
                            f"Notable: {', '.join(p['name'] for p in outdated[:5])}",
                            category="maintenance",
                            priority="low",
                            effort="medium",
                            source="dep-check",
                            metadata={
                                "count": len(outdated),
                                "packages": [p["name"] for p in outdated[:10]],
                            },
                        )
                    )
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            logger.debug("Python dependency check failed: %s", exc)

    # Check npm dependencies
    package_json = repo_path / "package.json"
    if package_json.exists():
        try:
            result = subprocess.run(
                ["npm", "audit", "--json"],  # fixed command
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(repo_path),
            )
            if result.stdout:
                audit = json.loads(result.stdout)
                vuln_count = audit.get("metadata", {}).get("vulnerabilities", {})
                critical = vuln_count.get("critical", 0)
                high = vuln_count.get("high", 0)
                if critical > 0 or high > 0:
                    steps.append(
                        NextStep(
                            title=f"Fix {critical + high} npm security vulnerabilities",
                            description=f"{critical} critical, {high} high severity npm vulnerabilities found.",
                            category="security",
                            priority="critical" if critical > 0 else "high",
                            effort="medium",
                            source="dep-check",
                            metadata={"critical": critical, "high": high},
                        )
                    )
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            logger.debug("npm audit check failed: %s", exc)

    return steps


def scan_doc_gaps(repo_path: Path) -> list[NextStep]:
    """Check for missing or sparse documentation."""
    steps = []

    readme = repo_path / "README.md"
    if not readme.exists():
        readme = repo_path / "README.rst"
    if not readme.exists():
        readme = repo_path / "README"

    if not readme.exists():
        steps.append(
            NextStep(
                title="Create a README",
                description="No README file found. A README is essential for project discoverability.",
                category="docs",
                priority="high",
                effort="medium",
                source="doc-gap",
            )
        )
    else:
        try:
            content = readme.read_text(errors="replace")
            if len(content) < 200:
                steps.append(
                    NextStep(
                        title="Expand README documentation",
                        description=f"README is only {len(content)} characters. "
                        "Consider adding: description, installation, usage, contributing.",
                        category="docs",
                        priority="medium",
                        effort="medium",
                        source="doc-gap",
                        file_path=str(readme.relative_to(repo_path)),
                    )
                )
        except OSError as exc:
            logger.debug("Failed to read README: %s", exc)

    # Check for CONTRIBUTING.md
    if not (repo_path / "CONTRIBUTING.md").exists():
        # Only suggest if repo has > 10 source files (non-trivial project)
        src_count = sum(1 for _ in repo_path.rglob("*.py"))
        if src_count > 10:
            steps.append(
                NextStep(
                    title="Add CONTRIBUTING.md",
                    description="No contributing guide found. This helps onboard new contributors.",
                    category="docs",
                    priority="low",
                    effort="small",
                    source="doc-gap",
                )
            )

    return steps


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _infer_issue_priority(labels: list[str]) -> str:
    """Infer priority from GitHub issue labels."""
    label_lower = [lb.lower() for lb in labels]
    if any("critical" in lb or "p0" in lb or "urgent" in lb for lb in label_lower):
        return "critical"
    if any("bug" in lb or "p1" in lb for lb in label_lower):
        return "high"
    if any("enhancement" in lb or "feature" in lb or "p2" in lb for lb in label_lower):
        return "medium"
    return "low"


def _infer_issue_category(labels: list[str]) -> str:
    """Infer category from GitHub issue labels."""
    label_lower = [lb.lower() for lb in labels]
    if any("bug" in lb for lb in label_lower):
        return "bug"
    if any("security" in lb for lb in label_lower):
        return "security"
    if any("doc" in lb for lb in label_lower):
        return "docs"
    if any("enhancement" in lb or "feature" in lb for lb in label_lower):
        return "enhancement"
    if any("tech-debt" in lb or "refactor" in lb for lb in label_lower):
        return "tech-debt"
    return "enhancement"


def _infer_effort(labels: list[str]) -> str:
    """Infer effort from GitHub issue labels."""
    label_lower = [lb.lower() for lb in labels]
    if any("good first issue" in lb or "easy" in lb for lb in label_lower):
        return "small"
    if any("large" in lb or "epic" in lb for lb in label_lower):
        return "large"
    return "medium"


def _deduplicate_steps(steps: list[NextStep]) -> list[NextStep]:
    """Remove duplicate steps based on title similarity."""
    seen_titles: set[str] = set()
    unique: list[NextStep] = []
    for step in steps:
        key = step.title.lower().strip()
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(step)
    return unique


def _generate_checksum(steps: list[NextStep]) -> str:
    """Generate SHA-256 checksum of steps for audit."""
    content = json.dumps(
        [{"title": s.title, "priority": s.priority, "category": s.category} for s in steps],
        sort_keys=True,
    )
    return hashlib.sha256(content.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------


class NextStepsRunner:
    """Orchestrates next-steps scanning across multiple signal sources."""

    def __init__(
        self,
        repo_path: str | Path | None = None,
        repo_url: str | None = None,
        scan_code: bool = True,
        scan_issues: bool = True,
        scan_prs: bool = True,
        scan_tests: bool = False,  # Off by default (can be slow)
        scan_deps: bool = False,  # Off by default (can be slow)
        scan_docs: bool = True,
        limit: int = 50,
    ):
        self.repo_path = Path(repo_path) if repo_path else None
        self.repo_url = repo_url
        self.scan_code = scan_code
        self.scan_issues = scan_issues
        self.scan_prs = scan_prs
        self.scan_tests = scan_tests
        self.scan_deps = scan_deps
        self.scan_docs = scan_docs
        self.limit = limit

        # Resolve repo identifiers
        self._github_repo = self._extract_github_repo()

    def _extract_github_repo(self) -> str | None:
        """Extract owner/repo from URL or local git remote."""
        if self.repo_url:
            match = re.search(r"github\.com[/:]([^/]+/[^/.]+)", self.repo_url)
            if match:
                return match.group(1)

        if self.repo_path:
            try:
                result = subprocess.run(
                    ["git", "remote", "get-url", "origin"],  # fixed command
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=str(self.repo_path),
                )
                if result.returncode == 0:
                    url = result.stdout.strip()
                    match = re.search(r"github\.com[/:]([^/]+/[^/.]+)", url)
                    if match:
                        return match.group(1)
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                logger.debug("Git remote lookup failed: %s", exc)

        return None

    async def scan(self) -> ScanResult:
        """Run all enabled scanners and return prioritized next steps."""
        started_at = time.time()
        all_steps: list[NextStep] = []
        files_scanned = 0
        signals: dict[str, int] = {}

        repo_label = self._github_repo or str(self.repo_path or ".")

        # Code markers
        if self.scan_code and self.repo_path:
            marker_steps, n_files = scan_code_markers(self.repo_path)
            files_scanned = n_files
            all_steps.extend(marker_steps)
            signals["code-marker"] = len(marker_steps)

        # GitHub issues
        if self.scan_issues and self._github_repo:
            issue_steps = scan_github_issues(self._github_repo)
            all_steps.extend(issue_steps)
            signals["github-issue"] = len(issue_steps)

        # GitHub PRs
        if self.scan_prs and self._github_repo:
            pr_steps = scan_github_prs(self._github_repo)
            all_steps.extend(pr_steps)
            signals["github-pr"] = len(pr_steps)

        # Test failures
        if self.scan_tests and self.repo_path:
            test_steps = scan_test_failures(self.repo_path)
            all_steps.extend(test_steps)
            signals["test-failure"] = len(test_steps)

        # Dependency health
        if self.scan_deps and self.repo_path:
            dep_steps = scan_dependency_health(self.repo_path)
            all_steps.extend(dep_steps)
            signals["dep-check"] = len(dep_steps)

        # Documentation gaps
        if self.scan_docs and self.repo_path:
            doc_steps = scan_doc_gaps(self.repo_path)
            all_steps.extend(doc_steps)
            signals["doc-gap"] = len(doc_steps)

        # Deduplicate and sort
        all_steps = _deduplicate_steps(all_steps)
        all_steps.sort(key=lambda s: s.sort_key)

        # Apply limit
        all_steps = all_steps[: self.limit]

        # Generate receipt
        completed_at = time.time()
        checksum = _generate_checksum(all_steps)
        scan_id = f"scan-{hashlib.sha256(f'{repo_label}-{started_at}'.encode()).hexdigest()[:12]}"

        receipt = ScanReceipt(
            scan_id=scan_id,
            repo=repo_label,
            started_at=started_at,
            completed_at=completed_at,
            steps_count=len(all_steps),
            files_scanned=files_scanned,
            signals_by_source=signals,
            checksum=checksum,
        )

        return ScanResult(
            repo=repo_label,
            steps=all_steps,
            receipt=receipt,
        )


def format_steps_table(steps: list[NextStep], max_rows: int = 30) -> str:
    """Format steps as a human-readable table."""
    if not steps:
        return "No next steps found."

    lines = []
    lines.append(f"{'#':<4} {'Priority':<10} {'Category':<14} {'Effort':<8} {'Title'}")
    lines.append("-" * 80)

    for i, step in enumerate(steps[:max_rows], 1):
        title = step.title[:42]
        lines.append(f"{i:<4} {step.priority:<10} {step.category:<14} {step.effort:<8} {title}")

    if len(steps) > max_rows:
        lines.append(f"\n... and {len(steps) - max_rows} more")

    return "\n".join(lines)


def steps_to_json(steps: list[NextStep], receipt: ScanReceipt | None = None) -> dict[str, Any]:
    """Convert steps to JSON-serializable dict."""
    result: dict[str, Any] = {
        "steps": [
            {
                "title": s.title,
                "description": s.description,
                "category": s.category,
                "priority": s.priority,
                "effort": s.effort,
                "source": s.source,
                "file_path": s.file_path,
                "line_number": s.line_number,
                "url": s.url,
            }
            for s in steps
        ],
        "count": len(steps),
        "by_priority": {p: len(ss) for p, ss in _group_by(steps, "priority").items()},
        "by_category": {c: len(ss) for c, ss in _group_by(steps, "category").items()},
    }
    if receipt:
        result["receipt"] = receipt.to_dict()
    return result


def _group_by(steps: list[NextStep], attr: str) -> dict[str, list[NextStep]]:
    """Group steps by attribute."""
    groups: dict[str, list[NextStep]] = {}
    for step in steps:
        key = getattr(step, attr, "unknown")
        groups.setdefault(key, []).append(step)
    return groups
