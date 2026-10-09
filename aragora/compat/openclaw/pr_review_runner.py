"""
OpenClaw PR Review Runner.

Orchestrates autonomous PR code review using Aragora's multi-agent debate
engine with OpenClaw policy enforcement.

This is the "point it at your repo and it does the work" component:
  1. Discover open PRs (or accept a specific PR)
  2. Fetch diffs
  3. Run multi-agent review with policy constraints
  4. Post findings as PR comments
  5. Generate decision receipts

Usage:
    from aragora.compat.openclaw.pr_review_runner import PRReviewRunner

    runner = PRReviewRunner.from_policy_file("policy.yaml")
    results = await runner.review_pr("https://github.com/owner/repo/pull/123")
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Bundled policy file lives next to the SKILL.md
_SKILL_DIR = Path(__file__).parent / "skills" / "pr-reviewer"
_DEFAULT_POLICY_PATH = _SKILL_DIR / "policy.yaml"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PolicyConfig:
    """Parsed policy configuration for the PR reviewer."""

    name: str = "pr-reviewer"
    default_action: str = "deny"

    # Allowed/denied tool patterns
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)

    # Network allowlist (host → ports)
    allowed_hosts: dict[str, list[int]] = field(default_factory=dict)

    # GitHub action allowlist/denylist
    allowed_gh_actions: list[str] = field(default_factory=list)
    denied_gh_actions: list[str] = field(default_factory=list)

    # File access
    writable_patterns: list[str] = field(default_factory=list)
    denied_write_patterns: list[str] = field(default_factory=list)

    # Resource limits
    max_execution_seconds: int = 300
    max_diff_size_kb: int = 50
    max_concurrent_reviews: int = 5

    # Audit
    require_receipt: bool = True
    log_all_actions: bool = True


@dataclass
class ReviewFinding:
    """A single finding from the review."""

    severity: str  # critical, high, medium, low
    title: str
    description: str
    file_path: str | None = None
    line_number: int | None = None
    agent: str | None = None
    unanimous: bool = False


@dataclass
class ReviewReceipt:
    """Audit receipt for a completed review."""

    review_id: str
    pr_url: str
    started_at: float
    completed_at: float
    findings_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    agreement_score: float
    agents_used: list[str]
    policy_name: str
    policy_violations: list[str]
    checksum: str  # SHA-256 of findings

    @property
    def duration_seconds(self) -> float:
        return self.completed_at - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "pr_url": self.pr_url,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "findings_count": self.findings_count,
            "severity_counts": {
                "critical": self.critical_count,
                "high": self.high_count,
                "medium": self.medium_count,
                "low": self.low_count,
            },
            "agreement_score": self.agreement_score,
            "agents_used": self.agents_used,
            "policy": {
                "name": self.policy_name,
                "violations": self.policy_violations,
            },
            "checksum": self.checksum,
        }


@dataclass
class ReviewResult:
    """Complete result of a PR review run."""

    pr_url: str
    pr_number: int | None
    repo: str | None
    findings: list[ReviewFinding]
    agreement_score: float
    agents_used: list[str]
    comment_posted: bool
    comment_url: str | None
    receipt: ReviewReceipt | None
    raw_findings: dict[str, Any] | None = None
    error: str | None = None

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "high")

    @property
    def has_critical(self) -> bool:
        return self.critical_count > 0


@dataclass
class PRMetadata:
    """Normalized public pull request metadata."""

    pr_url: str
    repo: str
    pr_number: int
    title: str | None = None
    state: str | None = None
    author: str | None = None
    base_ref: str | None = None
    base_sha: str | None = None
    head_ref: str | None = None
    head_sha: str | None = None
    is_draft: bool | None = None
    merged_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pr_url": self.pr_url,
            "repo": self.repo,
            "pr_number": self.pr_number,
            "title": self.title,
            "state": self.state,
            "author": self.author,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "head_ref": self.head_ref,
            "head_sha": self.head_sha,
            "is_draft": self.is_draft,
            "merged_at": self.merged_at,
        }


# ---------------------------------------------------------------------------
# Policy loader
# ---------------------------------------------------------------------------


def load_policy(path: str | Path | None = None) -> PolicyConfig:
    """Load policy from YAML file.

    Args:
        path: Path to policy YAML. Defaults to the bundled policy.

    Returns:
        Parsed PolicyConfig.
    """
    if path is None:
        path = _DEFAULT_POLICY_PATH

    path = Path(path)
    if not path.exists():
        logger.warning("Policy file not found: %s, using defaults", path)
        return _default_policy()

    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        logger.warning("PyYAML not installed, using default policy")
        return _default_policy()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Failed to parse policy %s: %s", path, exc)
        return _default_policy()

    return _parse_policy(data)


def _default_policy() -> PolicyConfig:
    """Return a sensible default policy."""
    return PolicyConfig(
        allowed_tools=[
            "gh",
            "git",
            "aragora",
            "python",
            "python3",
            "cat",
            "head",
            "tail",
            "grep",
            "find",
            "ls",
            "wc",
            "sort",
            "jq",
        ],
        denied_tools=[
            "rm",
            "rmdir",
            "dd",
            "chmod",
            "chown",
            "sudo",
            "su",
            "curl",
            "wget",
            "nc",
            "ssh",
            "docker",
            "kill",
        ],
        allowed_hosts={
            "api.github.com": [443],
            "github.com": [443],
            "api.anthropic.com": [443],
            "api.openai.com": [443],
            "openrouter.ai": [443],
            "api.mistral.ai": [443],
        },
        allowed_gh_actions=["pr diff", "pr view", "pr comment", "pr checks"],
        denied_gh_actions=["pr merge", "pr close", "pr edit", "release", "repo delete"],
    )


def _parse_policy(data: dict[str, Any]) -> PolicyConfig:
    """Parse a policy dict into PolicyConfig."""
    config = PolicyConfig(
        name=data.get("name", "pr-reviewer"),
        default_action=data.get("default_action", "deny"),
    )

    # Tools
    tools = data.get("tools", {})
    for rule in tools.get("allow", []):
        if isinstance(rule, dict):
            config.allowed_tools.append(rule.get("pattern", ""))
        elif isinstance(rule, str):
            config.allowed_tools.append(rule)
    for rule in tools.get("deny", []):
        if isinstance(rule, dict):
            config.denied_tools.append(rule.get("pattern", ""))
        elif isinstance(rule, str):
            config.denied_tools.append(rule)

    # Network
    network = data.get("network", {})
    for rule in network.get("allow", []):
        if isinstance(rule, dict):
            host = rule.get("host", "")
            ports = rule.get("ports", [443])
            config.allowed_hosts[host] = ports

    # GitHub actions
    gh = data.get("github", {})
    for rule in gh.get("allow", []):
        if isinstance(rule, dict):
            config.allowed_gh_actions.append(rule.get("action", ""))
        elif isinstance(rule, str):
            config.allowed_gh_actions.append(rule)
    for rule in gh.get("deny", []):
        if isinstance(rule, dict):
            config.denied_gh_actions.append(rule.get("action", ""))
        elif isinstance(rule, str):
            config.denied_gh_actions.append(rule)

    # Files
    files = data.get("files", {})
    for rule in files.get("write", []):
        if isinstance(rule, dict):
            config.writable_patterns.append(rule.get("pattern", ""))
    for rule in files.get("deny_write", []):
        if isinstance(rule, dict):
            config.denied_write_patterns.append(rule.get("pattern", ""))

    # Resources
    resources = data.get("resources", {})
    config.max_execution_seconds = resources.get("max_execution_seconds", 300)
    config.max_diff_size_kb = resources.get("max_file_size_mb", 50)
    config.max_concurrent_reviews = resources.get("max_concurrent_reviews", 5)

    # Audit
    audit = data.get("audit", {})
    config.require_receipt = audit.get("require_receipt", True)
    config.log_all_actions = audit.get("log_all_actions", True)

    return config


# ---------------------------------------------------------------------------
# Policy checker
# ---------------------------------------------------------------------------


class PolicyChecker:
    """Enforces policy constraints on PR review actions."""

    def __init__(self, policy: PolicyConfig):
        self.policy = policy
        self.violations: list[str] = []

    def check_gh_action(self, action: str) -> bool:
        """Check if a GitHub CLI action is allowed."""
        for denied in self.policy.denied_gh_actions:
            if denied in action:
                violation = f"Denied GitHub action: {action} (matches deny rule: {denied})"
                self.violations.append(violation)
                logger.warning(violation)
                return False

        for allowed in self.policy.allowed_gh_actions:
            if allowed in action:
                return True

        if self.policy.default_action == "deny":
            violation = f"GitHub action not in allowlist: {action}"
            self.violations.append(violation)
            logger.warning(violation)
            return False

        return True

    def check_diff_size(self, diff: str) -> bool:
        """Check if diff is within size limits."""
        size_kb = len(diff.encode("utf-8")) / 1024
        if size_kb > self.policy.max_diff_size_kb:
            violation = f"Diff size {size_kb:.1f}KB exceeds limit {self.policy.max_diff_size_kb}KB"
            self.violations.append(violation)
            logger.warning(violation)
            return False
        return True

    def get_violations(self) -> list[str]:
        """Return all policy violations recorded during this session."""
        return self.violations.copy()


# ---------------------------------------------------------------------------
# PR Review Runner
# ---------------------------------------------------------------------------


class PRReviewRunner:
    """
    Orchestrates autonomous PR review with policy enforcement.

    This is the core "point it at your repo" component. It:
    1. Parses PR URL to extract owner/repo/number
    2. Fetches the diff (enforcing size limits)
    3. Runs multi-agent review via aragora CLI or API
    4. Posts findings as PR comments
    5. Generates audit receipts
    """

    def __init__(
        self,
        policy: PolicyConfig | None = None,
        dry_run: bool = False,
        ci_mode: bool = False,
        fail_on_critical: bool = False,
        demo: bool = False,
        agents: str = "anthropic-api,openai-api",
        rounds: int = 2,
        gauntlet: bool = False,
    ):
        """
        Args:
            policy: Policy config. Loads default if None.
            dry_run: Analyze but don't post comments.
            ci_mode: CI-friendly output with exit codes.
            fail_on_critical: Exit non-zero if critical issues found.
            demo: Use demo mode (no API keys required).
            agents: Comma-separated agent list.
            rounds: Number of debate rounds.
            gauntlet: Run adversarial stress-test on findings.
        """
        self.policy = policy or load_policy()
        self.checker = PolicyChecker(self.policy)
        self.dry_run = dry_run
        self.ci_mode = ci_mode
        self.fail_on_critical = fail_on_critical
        self.demo = demo
        self.agents = agents
        self.rounds = rounds
        self.gauntlet = gauntlet

    @classmethod
    def from_policy_file(cls, path: str | Path, **kwargs: Any) -> PRReviewRunner:
        """Create a runner from a policy YAML file."""
        policy = load_policy(path)
        return cls(policy=policy, **kwargs)

    async def review_pr(self, pr_url: str) -> ReviewResult:
        """
        Review a single pull request.

        Args:
            pr_url: GitHub PR URL (e.g. https://github.com/owner/repo/pull/123)

        Returns:
            ReviewResult with findings, receipt, and metadata.
        """
        started_at = time.time()
        review_id = hashlib.sha256(f"{pr_url}:{started_at}".encode()).hexdigest()[:16]

        logger.info("Starting review %s for %s", review_id, pr_url)

        # Parse PR URL
        repo, pr_number, error = _parse_pr_url(pr_url)
        if error or repo is None or pr_number is None:
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
                error=error or f"Invalid PR URL format: {pr_url}",
            )

        # Step 1: Fetch diff (policy-checked)
        if not self.checker.check_gh_action("pr diff"):
            return self._error_result(pr_url, pr_number, repo, "Policy denied: pr diff")

        diff, error = self._fetch_diff(repo, pr_number)
        if error or diff is None:
            return self._error_result(pr_url, pr_number, repo, f"Fetch failed: {error}")

        # Step 2: Check diff size
        if not self.checker.check_diff_size(diff):
            # Truncate instead of failing
            max_bytes = self.policy.max_diff_size_kb * 1024
            diff = diff[:max_bytes]
            logger.info("Diff truncated to %dKB", self.policy.max_diff_size_kb)

        # Step 3: Run review
        findings_data, error = await self._run_review(diff)
        if error or findings_data is None:
            return self._error_result(pr_url, pr_number, repo, f"Review failed: {error}")

        # Step 4: Parse findings
        findings = _parse_findings(findings_data)
        agreement_score = findings_data.get("agreement_score", 0.0)
        agents_used = findings_data.get("agents_used", self.agents.split(","))

        # Step 5: Post comment (if not dry run)
        comment_url = None
        comment_posted = False
        if not self.dry_run:
            if not self.checker.check_gh_action("pr comment"):
                logger.warning("Policy denied posting comment")
            else:
                comment_url, post_error = self._post_comment(
                    repo,
                    pr_number,
                    findings,
                    agreement_score,
                )
                if post_error:
                    logger.warning("Failed to post comment: %s", post_error)
                else:
                    comment_posted = True

        # Step 6: Generate receipt
        completed_at = time.time()
        receipt = self._generate_receipt(
            review_id=review_id,
            pr_url=pr_url,
            started_at=started_at,
            completed_at=completed_at,
            findings=findings,
            agreement_score=agreement_score,
            agents_used=agents_used,
        )

        result = ReviewResult(
            pr_url=pr_url,
            pr_number=pr_number,
            repo=repo,
            findings=findings,
            agreement_score=agreement_score,
            agents_used=agents_used,
            comment_posted=comment_posted,
            comment_url=comment_url,
            receipt=receipt,
            raw_findings=findings_data,
        )

        logger.info(
            "Review %s complete: %d findings (%d critical, %d high), agreement=%.0f%%, comment=%s",
            review_id,
            len(findings),
            result.critical_count,
            result.high_count,
            agreement_score * 100,
            "posted" if comment_posted else "skipped",
        )

        return result

    def fetch_pr_metadata(self, pr_url: str) -> tuple[PRMetadata | None, str | None]:
        """Fetch normalized metadata for a public GitHub pull request."""
        repo, pr_number, error = _parse_pr_url(pr_url)
        if error or repo is None or pr_number is None:
            return None, error or "Invalid PR URL"

        if not self.checker.check_gh_action("pr view"):
            return None, "Policy denied: pr view"

        return self._fetch_pr_metadata(repo, pr_number)

    async def review_diff(self, diff: str, label: str = "local") -> ReviewResult:
        """
        Review a raw diff string without requiring a GitHub PR URL.

        This enables autonomous review in contexts like the Nomic Loop verify
        phase where changes exist as local git diffs, not yet pushed to GitHub.

        Args:
            diff: Unified diff text to review.
            label: Human-readable label for the review (used in receipt).

        Returns:
            ReviewResult with findings and receipt.
        """
        started_at = time.time()
        review_id = hashlib.sha256(f"{label}:{started_at}".encode()).hexdigest()[:16]

        logger.info("Starting diff review %s (label=%s, %d bytes)", review_id, label, len(diff))

        if not diff.strip():
            return ReviewResult(
                pr_url=label,
                pr_number=None,
                repo=None,
                findings=[],
                agreement_score=0.0,
                agents_used=[],
                comment_posted=False,
                comment_url=None,
                receipt=None,
                error="Empty diff",
            )

        # Check diff size
        if not self.checker.check_diff_size(diff):
            max_bytes = self.policy.max_diff_size_kb * 1024
            diff = diff[:max_bytes]
            logger.info("Diff truncated to %dKB", self.policy.max_diff_size_kb)

        # Run review
        findings_data, error = await self._run_review(diff)
        if error or findings_data is None:
            return self._error_result(label, None, None, f"Review failed: {error}")

        # Parse findings
        findings = _parse_findings(findings_data)
        agreement_score = findings_data.get("agreement_score", 0.0)
        agents_used = findings_data.get("agents_used", self.agents.split(","))

        # Generate receipt (no comment posting for local diffs)
        completed_at = time.time()
        receipt = self._generate_receipt(
            review_id=review_id,
            pr_url=label,
            started_at=started_at,
            completed_at=completed_at,
            findings=findings,
            agreement_score=agreement_score,
            agents_used=agents_used,
        )

        result = ReviewResult(
            pr_url=label,
            pr_number=None,
            repo=None,
            findings=findings,
            agreement_score=agreement_score,
            agents_used=agents_used,
            comment_posted=False,
            comment_url=None,
            receipt=receipt,
            raw_findings=findings_data,
        )

        logger.info(
            "Diff review %s complete: %d findings (%d critical, %d high), agreement=%.0f%%",
            review_id,
            len(findings),
            result.critical_count,
            result.high_count,
            agreement_score * 100,
        )

        return result

    async def review_repo(self, repo_url: str, limit: int = 10) -> list[ReviewResult]:
        """
        Review all open PRs in a repository.

        Args:
            repo_url: GitHub repository URL.
            limit: Maximum number of PRs to review.

        Returns:
            List of ReviewResult, one per PR.
        """
        repo = _extract_repo(repo_url)
        if not repo:
            return [self._error_result(repo_url, None, None, f"Invalid repo URL: {repo_url}")]

        # List open PRs
        pr_numbers, error = self._list_open_prs(repo, limit)
        if error:
            return [self._error_result(repo_url, None, repo, f"Failed to list PRs: {error}")]

        if not pr_numbers:
            logger.info("No open PRs found in %s", repo)
            return []

        results = []
        for pr_num in pr_numbers[: self.policy.max_concurrent_reviews]:
            pr_url = f"https://github.com/{repo}/pull/{pr_num}"
            result = await self.review_pr(pr_url)
            results.append(result)

        return results

    # --- Internal methods ---

    def _fetch_diff(self, repo: str, pr_number: int) -> tuple[str | None, str | None]:
        """Fetch PR diff via gh CLI."""
        try:
            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                ["gh", "pr", "diff", str(pr_number), "--repo", repo],  # noqa: S607 -- fixed command
                capture_output=True,
                text=True,
                timeout=self.policy.max_execution_seconds,
            )
            if result.returncode != 0:
                return None, result.stderr.strip() or "gh pr diff failed"
            return result.stdout, None
        except FileNotFoundError:
            return None, "gh CLI not found. Install: https://cli.github.com"
        except subprocess.TimeoutExpired:
            return None, "Timed out fetching PR diff"

    async def _run_review(
        self,
        diff: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Run the Aragora review engine."""
        # Demo and gauntlet modes must run through the CLI path. The in-process
        # review helper does not accept a gauntlet flag, so subprocess is the
        # only truthful way to activate adversarial review behavior here.
        if self.demo or self.gauntlet:
            return self._run_review_subprocess(diff)

        # Try direct import first (faster, in-process)
        try:
            from aragora.cli.review import (
                extract_review_findings,
                run_review_debate,
            )

            debate_result = await run_review_debate(
                diff=diff,
                agents_str=self.agents,
                rounds=self.rounds,
                focus_areas=["security", "quality", "performance"],
            )
            findings = extract_review_findings(debate_result)
            return findings, None
        except ImportError as exc:
            logger.debug("Direct review import unavailable: %s, falling back to subprocess", exc)
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            logger.warning("Direct review import failed: %s, falling back to subprocess", exc)

        # Fallback: run as subprocess
        return self._run_review_subprocess(diff)

    def _run_review_subprocess(
        self,
        diff: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Fallback: run review via aragora CLI subprocess."""
        cmd = [
            "aragora",
            "review",
            "--output-format",
            "json",
            "--agents",
            self.agents,
            "--rounds",
            str(self.rounds),
        ]
        if self.demo:
            cmd.append("--demo")
        if self.gauntlet:
            cmd.append("--gauntlet")

        try:
            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                cmd,
                input=diff,
                capture_output=True,
                text=True,
                timeout=self.policy.max_execution_seconds,
            )
            if result.returncode != 0:
                return None, result.stderr.strip() or "aragora review failed"

            # Parse JSON from output (may be multi-line pretty-printed)
            stdout = result.stdout.strip()
            try:
                return json.loads(stdout), None
            except json.JSONDecodeError as exc:
                logger.debug("Review subprocess stdout was not valid JSON: %s", exc)

            # Try to find a JSON object in the output
            brace_start = stdout.find("{")
            if brace_start >= 0:
                try:
                    return json.loads(stdout[brace_start:]), None
                except json.JSONDecodeError as exc:
                    logger.debug("Review subprocess embedded JSON parse failed: %s", exc)

            return {"raw_output": stdout}, None
        except FileNotFoundError:
            return None, "aragora CLI not found"
        except subprocess.TimeoutExpired:
            return None, f"Review timed out after {self.policy.max_execution_seconds}s"
        except json.JSONDecodeError as exc:
            logger.warning("Review subprocess output not parseable as JSON: %s", exc)
            return {"raw_output": result.stdout}, None

    def _post_comment(
        self,
        repo: str,
        pr_number: int,
        findings: list[ReviewFinding],
        agreement_score: float,
    ) -> tuple[str | None, str | None]:
        """Post review findings as a PR comment."""
        body = _format_comment(findings, agreement_score)

        try:
            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                [  # noqa: S607 -- fixed command
                    "gh",
                    "pr",
                    "comment",
                    str(pr_number),
                    "--repo",
                    repo,
                    "--body",
                    body,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return None, result.stderr.strip()
            return result.stdout.strip() or f"https://github.com/{repo}/pull/{pr_number}", None
        except FileNotFoundError:
            return None, "gh CLI not found"
        except subprocess.TimeoutExpired:
            return None, "Timed out posting comment"

    def _list_open_prs(
        self,
        repo: str,
        limit: int,
    ) -> tuple[list[int] | None, str | None]:
        """List open PR numbers for a repo."""
        try:
            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                [  # noqa: S607 -- fixed command
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
                    "number",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return None, result.stderr.strip()
            prs = json.loads(result.stdout)
            return [pr["number"] for pr in prs], None
        except FileNotFoundError:
            return None, "gh CLI not found"
        except subprocess.TimeoutExpired:
            return None, "Timed out listing PRs"
        except (json.JSONDecodeError, KeyError) as exc:
            return None, f"Failed to parse PR list: {exc}"

    def _fetch_pr_metadata(
        self,
        repo: str,
        pr_number: int,
    ) -> tuple[PRMetadata | None, str | None]:
        """Fetch public PR metadata via gh CLI."""
        try:
            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                [  # noqa: S607 -- fixed command
                    "gh",
                    "pr",
                    "view",
                    str(pr_number),
                    "--repo",
                    repo,
                    "--json",
                    "url,number,title,state,author,baseRefName,baseRefOid,headRefName,headRefOid,isDraft,mergedAt",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return None, result.stderr.strip() or "gh pr view failed"

            data = json.loads(result.stdout)
            author = data.get("author")
            author_login = None
            if isinstance(author, dict):
                author_login = author.get("login")

            return (
                PRMetadata(
                    pr_url=str(data.get("url") or f"https://github.com/{repo}/pull/{pr_number}"),
                    repo=repo,
                    pr_number=int(data.get("number", pr_number)),
                    title=data.get("title"),
                    state=data.get("state"),
                    author=author_login,
                    base_ref=data.get("baseRefName"),
                    base_sha=data.get("baseRefOid"),
                    head_ref=data.get("headRefName"),
                    head_sha=data.get("headRefOid"),
                    is_draft=data.get("isDraft"),
                    merged_at=data.get("mergedAt"),
                ),
                None,
            )
        except FileNotFoundError:
            return None, "gh CLI not found. Install: https://cli.github.com"
        except subprocess.TimeoutExpired:
            return None, "Timed out fetching PR metadata"
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return None, f"Failed to parse PR metadata: {exc}"

    def _generate_receipt(
        self,
        review_id: str,
        pr_url: str,
        started_at: float,
        completed_at: float,
        findings: list[ReviewFinding],
        agreement_score: float,
        agents_used: list[str],
    ) -> ReviewReceipt:
        """Generate an audit receipt for the review."""
        # Compute checksum over findings
        findings_json = json.dumps(
            [
                {"severity": f.severity, "title": f.title, "description": f.description}
                for f in findings
            ],
            sort_keys=True,
        )
        checksum = hashlib.sha256(findings_json.encode()).hexdigest()

        return ReviewReceipt(
            review_id=review_id,
            pr_url=pr_url,
            started_at=started_at,
            completed_at=completed_at,
            findings_count=len(findings),
            critical_count=sum(1 for f in findings if f.severity == "critical"),
            high_count=sum(1 for f in findings if f.severity == "high"),
            medium_count=sum(1 for f in findings if f.severity == "medium"),
            low_count=sum(1 for f in findings if f.severity == "low"),
            agreement_score=agreement_score,
            agents_used=agents_used,
            policy_name=self.policy.name,
            policy_violations=self.checker.get_violations(),
            checksum=checksum,
        )

    def _error_result(
        self,
        pr_url: str,
        pr_number: int | None,
        repo: str | None,
        error: str,
    ) -> ReviewResult:
        """Create an error ReviewResult."""
        return ReviewResult(
            pr_url=pr_url,
            pr_number=pr_number,
            repo=repo,
            findings=[],
            agreement_score=0.0,
            agents_used=[],
            comment_posted=False,
            comment_url=None,
            receipt=None,
            error=error,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_pr_url(pr_url: str) -> tuple[str | None, int | None, str | None]:
    """Parse a GitHub PR URL into (owner/repo, pr_number, error)."""
    parts = pr_url.rstrip("/").split("/")
    try:
        idx = parts.index("pull")
        repo = "/".join(parts[idx - 2 : idx])
        pr_number = int(parts[idx + 1])
        return repo, pr_number, None
    except (ValueError, IndexError):
        return None, None, f"Invalid PR URL format: {pr_url}"


def _extract_repo(repo_url: str) -> str | None:
    """Extract owner/repo from a GitHub URL."""
    url = repo_url.rstrip("/")
    # Handle https://github.com/owner/repo
    if "github.com" in url:
        parts = url.split("github.com/", 1)
        if len(parts) == 2:
            repo_parts = parts[1].split("/")
            if len(repo_parts) >= 2:
                return f"{repo_parts[0]}/{repo_parts[1]}"
    # Handle owner/repo format directly (no scheme, no dots in owner)
    if "/" in url and ":" not in url and "." not in url.split("/")[0]:
        return url
    return None


def _parse_findings(findings_data: dict[str, Any]) -> list[ReviewFinding]:
    """Convert raw findings dict into structured ReviewFinding objects."""
    findings: list[ReviewFinding] = []

    # Parse unanimous critiques
    for critique in findings_data.get("unanimous_critiques", []):
        text = critique if isinstance(critique, str) else str(critique)
        findings.append(
            ReviewFinding(
                severity=_infer_severity(text),
                title=text[:120],
                description=text,
                unanimous=True,
            )
        )

    # Parse severity-bucketed issues
    for severity in ("critical", "high", "medium", "low"):
        for issue in findings_data.get(f"{severity}_issues", []):
            text = issue if isinstance(issue, str) else str(issue)
            findings.append(
                ReviewFinding(
                    severity=severity,
                    title=text[:120],
                    description=text,
                )
            )

    return findings


def _infer_severity(text: str) -> str:
    """Infer severity from finding text."""
    lower = text.lower()
    if any(
        w in lower
        for w in (
            "critical",
            "vulnerability",
            "injection",
            "rce",
            "exploit",
            "remote code",
            "code execution",
        )
    ):
        return "critical"
    if any(w in lower for w in ("security", "auth", "credential", "secret", "xss")):
        return "high"
    if any(w in lower for w in ("performance", "memory leak", "race condition", "error handling")):
        return "medium"
    return "low"


def _format_comment(
    findings: list[ReviewFinding],
    agreement_score: float,
) -> str:
    """Format findings as a GitHub PR comment."""
    lines = ["## Aragora Multi-Agent Code Review", ""]

    if agreement_score:
        lines.append(f"**Consensus Score:** {agreement_score:.0%}")
        lines.append("")

    critical = [f for f in findings if f.severity == "critical"]
    high = [f for f in findings if f.severity == "high"]
    medium = [f for f in findings if f.severity == "medium"]
    low = [f for f in findings if f.severity == "low"]
    unanimous = [f for f in findings if f.unanimous]

    if critical:
        lines.append("### Critical Issues")
        for f in critical:
            lines.append(f"- {f.description}")
        lines.append("")

    if high:
        lines.append("### High Severity")
        for f in high:
            lines.append(f"- {f.description}")
        lines.append("")

    if unanimous:
        lines.append("### All Agents Agree")
        for f in unanimous:
            lines.append(f"- {f.description}")
        lines.append("")

    if medium:
        lines.append("<details><summary>Medium Issues (%d)</summary>\n" % len(medium))
        for f in medium:
            lines.append(f"- {f.description}")
        lines.append("\n</details>\n")

    if low:
        lines.append("<details><summary>Low Issues (%d)</summary>\n" % len(low))
        for f in low:
            lines.append(f"- {f.description}")
        lines.append("\n</details>\n")

    if not any([critical, high, medium, low]):
        lines.append("No significant issues found.")
        lines.append("")

    lines.append("---")
    lines.append(
        "*Reviewed by [Aragora](https://github.com/your-org/aragora) "
        "multi-agent debate engine | "
        f"Policy: `{findings[0].agent or 'pr-reviewer'}`*"
        if findings
        else "*Reviewed by [Aragora](https://github.com/your-org/aragora) "
        "multi-agent debate engine*"
    )
    return "\n".join(lines)


def findings_to_sarif(
    findings: list[ReviewFinding],
    receipt: ReviewReceipt | None = None,
) -> dict[str, Any]:
    """Convert review findings to SARIF 2.1.0 format.

    SARIF (Static Analysis Results Interchange Format) is the standard
    for tool output consumed by GitHub Security tab, Azure DevOps, and
    other CI/CD platforms.

    Args:
        findings: List of ReviewFinding objects.
        receipt: Optional ReviewReceipt for run-level metadata.

    Returns:
        SARIF 2.1.0 compliant dict.
    """
    severity_to_sarif = {
        "critical": "error",
        "high": "error",
        "medium": "warning",
        "low": "note",
    }

    rules: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    seen_rules: dict[str, int] = {}

    for finding in findings:
        # Create a stable rule ID from the title
        rule_id = hashlib.sha256(finding.title.encode()).hexdigest()[:12]
        if rule_id not in seen_rules:
            seen_rules[rule_id] = len(rules)
            rules.append(
                {
                    "id": rule_id,
                    "name": finding.title[:80],
                    "shortDescription": {"text": finding.title[:120]},
                    "fullDescription": {"text": finding.description},
                    "defaultConfiguration": {
                        "level": severity_to_sarif.get(finding.severity, "note"),
                    },
                    "properties": {
                        "severity": finding.severity,
                        "unanimous": finding.unanimous,
                    },
                }
            )

        result: dict[str, Any] = {
            "ruleId": rule_id,
            "ruleIndex": seen_rules[rule_id],
            "message": {"text": finding.description},
            "level": severity_to_sarif.get(finding.severity, "note"),
        }

        if finding.file_path:
            location: dict[str, Any] = {
                "physicalLocation": {
                    "artifactLocation": {"uri": finding.file_path},
                },
            }
            if finding.line_number:
                location["physicalLocation"]["region"] = {
                    "startLine": finding.line_number,
                }
            result["locations"] = [location]

        if finding.agent:
            result["properties"] = {"agent": finding.agent}

        results.append(result)

    run: dict[str, Any] = {
        "tool": {
            "driver": {
                "name": "aragora-pr-reviewer",
                "informationUri": "https://github.com/synaptent/aragora",
                "version": "1.0.0",
                "rules": rules,
            },
        },
        "results": results,
    }

    if receipt:
        run["properties"] = {
            "reviewId": receipt.review_id,
            "agreementScore": receipt.agreement_score,
            "agentsUsed": receipt.agents_used,
            "checksum": receipt.checksum,
        }

    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [run],
    }
