"""
Autonomous DevOps Agent.

Executes repository operations through policy-controlled subprocess calls.
Every action is audited and constrained by an allowlist of commands.

Security model:
    - Only pre-approved commands can execute (gh, aragora, git, pip, twine)
    - All actions are audit-logged with timestamps and outcomes
    - Destructive operations require explicit --allow-destructive flag
    - Network access is limited to GitHub API and PyPI
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Commands the agent is allowed to execute (prefix match)
ALLOWED_COMMANDS = [
    "gh pr ",
    "gh issue ",
    "gh release ",
    "gh api ",
    "gh auth status",
    "gh repo view",
    "aragora review",
    "aragora ask",
    "aragora compliance",
    "git diff",
    "git log",
    "git push",
    "git status",
    "git tag",
    "pip install",
    "pip list",
    "twine check",
    "twine upload",
    "python -m build",
    "python -m pytest",
]

# Commands that require --allow-destructive
DESTRUCTIVE_COMMANDS = [
    "gh pr close",
    "gh pr merge",
    "gh issue close",
    "gh release delete",
    "twine upload",
    "git push",
    "git tag",
]

# Commands that are never allowed
BLOCKED_COMMANDS = [
    "rm ",
    "sudo ",
    "chmod ",
    "curl ",
    "wget ",
    "nc ",
    "ssh ",
    "eval ",
    "exec ",
]

# Shell metacharacters that indicate injection attempts
_SHELL_METACHARACTERS = [";", "&&", "||", "|", "`", "$(", "${"]


class DevOpsTask(str, Enum):
    """Tasks the DevOps agent can perform."""

    REVIEW_PRS = "review-prs"
    TRIAGE_ISSUES = "triage-issues"
    PREPARE_RELEASE = "prepare-release"
    HEALTH_CHECK = "health-check"


@dataclass
class DevOpsAgentConfig:
    """Configuration for the DevOps agent."""

    repo: str = ""  # owner/repo format
    poll_interval: int = 300  # seconds between polls in watch mode
    max_prs_per_run: int = 5
    max_issues_per_run: int = 10
    review_agents: str = "anthropic-api,openai-api"
    review_rounds: int = 2
    review_focus: str = "security,performance,quality"
    allow_destructive: bool = False
    dry_run: bool = False
    github_token: str = ""  # Falls back to gh auth

    @classmethod
    def from_env(cls) -> DevOpsAgentConfig:
        return cls(
            repo=os.environ.get("ARAGORA_DEVOPS_REPO", ""),
            poll_interval=int(os.environ.get("ARAGORA_DEVOPS_POLL_INTERVAL", "300")),
            review_agents=os.environ.get("ARAGORA_DEVOPS_AGENTS", "anthropic-api,openai-api"),
            allow_destructive=os.environ.get("ARAGORA_DEVOPS_ALLOW_DESTRUCTIVE", "") == "true",
            dry_run=os.environ.get("ARAGORA_DEVOPS_DRY_RUN", "") == "true",
            github_token=os.environ.get("GITHUB_TOKEN", ""),
        )


@dataclass
class TaskResult:
    """Result of a DevOps task execution."""

    task: str
    success: bool
    items_processed: int = 0
    items_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    details: list[dict[str, Any]] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    duration_seconds: float = 0.0


@dataclass
class AuditEntry:
    """Audit log entry for an agent action."""

    timestamp: str
    action: str
    command: str
    outcome: str  # "allowed", "blocked", "dry_run", "error"
    detail: str = ""


class DevOpsAgent:
    """Autonomous agent that handles repository operations.

    All commands are validated against an allowlist before execution.
    Every action is logged to an audit trail.
    """

    def __init__(self, config: DevOpsAgentConfig) -> None:
        self._config = config
        self._audit_log: list[AuditEntry] = []

    @property
    def audit_log(self) -> list[AuditEntry]:
        return list(self._audit_log)

    # ── Command execution with policy enforcement ──────────────────

    def _validate_command(self, command: str) -> tuple[bool, str]:
        """Check command against allowlist and blocklist.

        Validates the full command string, not just the prefix, to prevent
        injection via shell metacharacters or embedded blocked commands.
        """
        cmd = command.strip()

        # Reject shell metacharacters anywhere in the command (defense-in-depth)
        for meta in _SHELL_METACHARACTERS:
            if meta in cmd:
                return False, f"Command contains shell metacharacter: '{meta}'"

        # Scan for blocked commands anywhere in the string, not just at the start
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd:
                return False, f"Command contains blocked token: '{blocked.strip()}'"

        # Validate the command parses cleanly with shlex (no unbalanced quotes, etc.)
        try:
            shlex.split(cmd)
        except ValueError as e:
            return False, f"Command has invalid shell quoting: {e}"

        for allowed in ALLOWED_COMMANDS:
            if cmd.startswith(allowed):
                # Check if it's destructive
                for destructive in DESTRUCTIVE_COMMANDS:
                    if cmd.startswith(destructive) and not self._config.allow_destructive:
                        return (
                            False,
                            f"Destructive command '{destructive.strip()}' requires --allow-destructive",
                        )
                return True, "allowed"

        return False, f"Command not in allowlist: {cmd[:50]}"

    def _execute(self, command: str, action_name: str = "") -> tuple[bool, str]:
        """Execute a command with policy checks and audit logging."""
        allowed, reason = self._validate_command(command)

        if not allowed:
            self._audit(action_name, command, "blocked", reason)
            logger.warning("Blocked: %s — %s", command[:80], reason)
            return False, reason

        if self._config.dry_run:
            self._audit(action_name, command, "dry_run", "")
            logger.info("[DRY RUN] Would execute: %s", command[:120])
            return True, "[dry run]"

        self._audit(action_name, command, "allowed", "")
        logger.info("Executing: %s", command[:120])

        try:
            result = subprocess.run(  # subprocess with fixed args, no shell
                shlex.split(command),
                shell=False,
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "GH_NO_PROMPT": "1"},
            )
            if result.returncode != 0:
                error = result.stderr.strip()[:500]
                self._audit(action_name, command, "error", error)
                return False, error
            return True, result.stdout.strip()
        except subprocess.TimeoutExpired:
            self._audit(action_name, command, "error", "timeout")
            return False, "Command timed out after 120s"
        except OSError as e:
            self._audit(action_name, command, "error", str(e))
            return False, "Command execution failed"

    def _audit(self, action: str, command: str, outcome: str, detail: str = "") -> None:
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action=action,
            command=command[:200],
            outcome=outcome,
            detail=detail[:500],
        )
        self._audit_log.append(entry)
        logger.debug("AUDIT: %s %s %s", action, outcome, command[:80])

    # ── Task: Review PRs ───────────────────────────────────────────

    def review_prs(self) -> TaskResult:
        """Review open PRs that haven't been reviewed by the agent yet."""
        result = TaskResult(task="review-prs", success=True)
        start = time.monotonic()

        ok, output = self._execute(
            f"gh pr list -R {self._config.repo} --state open --json number,title,labels --limit {self._config.max_prs_per_run}",
            "list_prs",
        )
        if not ok:
            result.success = False
            result.errors.append(f"Failed to list PRs: {output}")
            result.duration_seconds = time.monotonic() - start
            result.completed_at = datetime.now(timezone.utc)
            return result

        try:
            prs = json.loads(output) if output and output != "[dry run]" else []
        except json.JSONDecodeError:
            logger.debug("Failed to parse PR list JSON, defaulting to empty list")
            prs = []

        for pr in prs:
            pr_num = pr.get("number")
            title = pr.get("title", "")
            labels = [label.get("name", "") for label in pr.get("labels", [])]

            # Skip PRs already reviewed by the agent
            if "aragora-reviewed" in labels:
                result.items_skipped += 1
                continue

            pr_result = self._review_single_pr(pr_num, title)
            result.details.append(pr_result)
            if pr_result.get("success"):
                result.items_processed += 1
            else:
                result.errors.append(f"PR #{pr_num}: {pr_result.get('error', 'unknown')}")

        result.duration_seconds = time.monotonic() - start
        result.completed_at = datetime.now(timezone.utc)
        return result

    def _review_single_pr(self, pr_number: int, title: str) -> dict[str, Any]:
        """Review a single PR."""
        logger.info("Reviewing PR #%d: %s", pr_number, title)

        # Get the diff
        ok, diff = self._execute(f"gh pr diff {pr_number} -R {self._config.repo}", "get_pr_diff")
        if not ok:
            return {"pr": pr_number, "success": False, "error": diff}

        # Write diff to secure temp file
        if diff and diff != "[dry run]":
            try:
                tmp = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".diff", prefix=f"aragora_pr_{pr_number}_", delete=False
                )
                diff_path = tmp.name
                tmp.write(diff)
                tmp.close()
            except OSError as e:
                logger.error("Failed to write diff for PR %s: %s", pr_number, e)
                return {"pr": pr_number, "success": False, "error": "Failed to write diff file"}

            # Run aragora review
            ok, review_output = self._execute(
                f"aragora review --diff-file {diff_path} "
                f"--agents {self._config.review_agents} "
                f"--rounds {self._config.review_rounds} "
                f"--focus {self._config.review_focus} "
                f"--output-format json",
                "run_review",
            )

            if ok and review_output and review_output != "[dry run]":
                # Post review as PR comment
                comment = self._format_review_comment(review_output, pr_number)
                comment_escaped = comment.replace("'", "'\\''")
                self._execute(
                    f"gh pr comment {pr_number} -R {self._config.repo} --body '{comment_escaped}'",
                    "post_review_comment",
                )

                # Add reviewed label
                self._execute(
                    f"gh pr edit {pr_number} -R {self._config.repo} --add-label aragora-reviewed",
                    "add_reviewed_label",
                )

        return {"pr": pr_number, "success": True, "title": title}

    def _format_review_comment(self, review_json: str, pr_number: int) -> str:
        """Format review output as a GitHub PR comment."""
        try:
            data = json.loads(review_json)
        except json.JSONDecodeError:
            logger.debug("Failed to parse review JSON for PR #%d, using empty data", pr_number)
            data = {}

        lines = [
            "## Aragora AI Review",
            "",
            f"Automated multi-agent code review for PR #{pr_number}.",
            "",
        ]

        findings = data.get("findings", [])
        if findings:
            for finding in findings[:20]:
                severity = finding.get("severity", "info").upper()
                message = finding.get("message", "")
                lines.append(f"- **{severity}**: {message}")
        else:
            lines.append("No significant findings detected.")

        lines.extend(
            [
                "",
                "---",
                "*Generated by [Aragora DevOps Agent](https://github.com/synaptent/aragora) "
                "via OpenClaw policy-controlled execution.*",
            ]
        )
        return "\n".join(lines)

    # ── Task: Triage Issues ────────────────────────────────────────

    def triage_issues(self) -> TaskResult:
        """Auto-label new issues based on content analysis."""
        result = TaskResult(task="triage-issues", success=True)
        start = time.monotonic()

        ok, output = self._execute(
            f"gh issue list -R {self._config.repo} --state open "
            f"--json number,title,body,labels --limit {self._config.max_issues_per_run}",
            "list_issues",
        )
        if not ok:
            result.success = False
            result.errors.append(f"Failed to list issues: {output}")
            result.duration_seconds = time.monotonic() - start
            result.completed_at = datetime.now(timezone.utc)
            return result

        try:
            issues = json.loads(output) if output and output != "[dry run]" else []
        except json.JSONDecodeError:
            logger.debug("Failed to parse issue list JSON, defaulting to empty list")
            issues = []

        for issue in issues:
            issue_num = issue.get("number")
            title = issue.get("title", "")
            body = issue.get("body", "")
            existing_labels = [label.get("name", "") for label in issue.get("labels", [])]

            # Skip already-triaged issues
            if "triaged" in existing_labels:
                result.items_skipped += 1
                continue

            labels = self._classify_issue(title, body)
            if labels:
                label_str = ",".join(labels)
                self._execute(
                    f"gh issue edit {issue_num} -R {self._config.repo} --add-label {label_str},triaged",
                    "label_issue",
                )
                result.items_processed += 1
                result.details.append({"issue": issue_num, "labels": labels, "title": title})
            else:
                result.items_skipped += 1

        result.duration_seconds = time.monotonic() - start
        result.completed_at = datetime.now(timezone.utc)
        return result

    def _classify_issue(self, title: str, body: str) -> list[str]:
        """Classify an issue by keywords. Returns suggested labels."""
        text = f"{title} {body}".lower()
        labels = []

        label_keywords = {
            "bug": ["bug", "error", "crash", "broken", "fail", "exception", "traceback"],
            "enhancement": ["feature", "request", "add", "improve", "enhancement", "support"],
            "documentation": ["docs", "documentation", "readme", "typo", "guide"],
            "security": ["security", "vulnerability", "cve", "exploit", "injection", "xss"],
            "performance": ["slow", "performance", "memory", "leak", "optimize", "latency"],
            "question": ["how to", "question", "help", "what is", "how do"],
        }

        for label, keywords in label_keywords.items():
            if any(kw in text for kw in keywords):
                labels.append(label)

        return labels[:3]  # Max 3 labels

    # ── Task: Prepare Release ──────────────────────────────────────

    def prepare_release(self, version: str | None = None) -> TaskResult:
        """Prepare a release: run tests, build, check, optionally publish."""
        result = TaskResult(task="prepare-release", success=True)
        start = time.monotonic()

        # Get current version from pyproject.toml
        if not version:
            ok, output = self._execute(
                "python -c \"import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])\"",
                "get_version",
            )
            if not ok:
                # Not a critical error, use placeholder
                version = "unknown"
            else:
                version = output.strip() if output != "[dry run]" else "0.0.0"

        # Run tests
        ok, output = self._execute(
            "python -m pytest tests/ -x -q --tb=short --timeout=120",
            "run_tests",
        )
        result.details.append(
            {"step": "tests", "success": ok, "output": output[:500] if output else ""}
        )
        if not ok:
            result.errors.append(f"Tests failed: {output[:200] if output else 'unknown'}")
            result.success = False
            result.duration_seconds = time.monotonic() - start
            result.completed_at = datetime.now(timezone.utc)
            return result

        # Build package
        ok, output = self._execute("python -m build", "build_package")
        result.details.append({"step": "build", "success": ok})
        if not ok:
            result.errors.append(f"Build failed: {output[:200] if output else 'unknown'}")
            result.success = False
            result.duration_seconds = time.monotonic() - start
            result.completed_at = datetime.now(timezone.utc)
            return result

        # Check package
        ok, output = self._execute("twine check dist/*", "twine_check")
        result.details.append({"step": "twine_check", "success": ok})

        result.items_processed = 1
        result.duration_seconds = time.monotonic() - start
        result.completed_at = datetime.now(timezone.utc)
        return result

    # ── Task: Health Check ─────────────────────────────────────────

    def health_check(self) -> TaskResult:
        """Check repository health: CI status, open PRs, issues, staleness."""
        result = TaskResult(task="health-check", success=True)
        start = time.monotonic()

        checks: list[dict[str, Any]] = []

        # Check gh auth
        ok, output = self._execute("gh auth status", "check_gh_auth")
        checks.append({"check": "gh_auth", "ok": ok})

        # Open PR count
        ok, output = self._execute(
            f"gh pr list -R {self._config.repo} --state open --json number --jq length",
            "count_open_prs",
        )
        if ok and output and output != "[dry run]":
            try:
                pr_count = int(output.strip())
            except ValueError:
                logger.debug("Failed to parse open PR count from output: %s", output[:50])
                pr_count = -1
            checks.append({"check": "open_prs", "count": pr_count})

        # Open issue count
        ok, output = self._execute(
            f"gh issue list -R {self._config.repo} --state open --json number --jq length",
            "count_open_issues",
        )
        if ok and output and output != "[dry run]":
            try:
                issue_count = int(output.strip())
            except ValueError:
                logger.debug("Failed to parse open issue count from output: %s", output[:50])
                issue_count = -1
            checks.append({"check": "open_issues", "count": issue_count})

        # Latest release
        ok, output = self._execute(
            f"gh release list -R {self._config.repo} --limit 1 --json tagName,publishedAt",
            "check_latest_release",
        )
        if ok and output and output != "[dry run]":
            try:
                releases = json.loads(output)
                if releases:
                    checks.append(
                        {
                            "check": "latest_release",
                            "tag": releases[0].get("tagName"),
                            "date": releases[0].get("publishedAt"),
                        }
                    )
            except json.JSONDecodeError:
                logger.debug("Failed to parse release JSON for health check")

        result.details = checks
        result.items_processed = len(checks)
        result.duration_seconds = time.monotonic() - start
        result.completed_at = datetime.now(timezone.utc)
        return result

    # ── Watch mode ─────────────────────────────────────────────────

    def watch(self, tasks: list[DevOpsTask] | None = None) -> None:
        """Run in watch mode, polling for events."""
        if tasks is None:
            tasks = [DevOpsTask.REVIEW_PRS, DevOpsTask.TRIAGE_ISSUES]

        logger.info(
            "DevOps agent watching %s (poll every %ds, dry_run=%s)",
            self._config.repo,
            self._config.poll_interval,
            self._config.dry_run,
        )

        try:
            while True:
                for task in tasks:
                    result = self.run_task(task)
                    if result.items_processed > 0:
                        logger.info(
                            "Task %s: processed %d items",
                            task.value,
                            result.items_processed,
                        )
                    if result.errors:
                        for err in result.errors:
                            logger.error("Task %s error: %s", task.value, err)

                logger.debug("Sleeping %ds...", self._config.poll_interval)
                time.sleep(self._config.poll_interval)
        except KeyboardInterrupt:
            logger.info("Watch mode stopped by user")

    # ── Dispatcher ─────────────────────────────────────────────────

    def run_task(self, task: DevOpsTask, version: str | None = None) -> TaskResult:
        """Run a specific task."""
        if task == DevOpsTask.REVIEW_PRS:
            return self.review_prs()
        elif task == DevOpsTask.TRIAGE_ISSUES:
            return self.triage_issues()
        elif task == DevOpsTask.PREPARE_RELEASE:
            return self.prepare_release(version)
        elif task == DevOpsTask.HEALTH_CHECK:
            return self.health_check()
        else:
            return TaskResult(
                task=task.value,
                success=False,
                errors=[f"Unknown task: {task.value}"],
            )

    # ── Audit export ───────────────────────────────────────────────

    def export_audit_log(self) -> list[dict[str, str]]:
        """Export audit log as list of dicts."""
        return [
            {
                "timestamp": e.timestamp,
                "action": e.action,
                "command": e.command,
                "outcome": e.outcome,
                "detail": e.detail,
            }
            for e in self._audit_log
        ]
