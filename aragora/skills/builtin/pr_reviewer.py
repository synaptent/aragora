"""
PR Reviewer Skill for OpenClaw agents.

Enables autonomous PR review using Aragora's multi-agent debate engine.
An OpenClaw agent with this skill can:
  1. Fetch a PR diff from GitHub
  2. Run multi-agent code review
  3. Post findings as PR comments

This is the dogfooding skill — Aragora reviewing its own PRs.
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

from ..base import (
    Skill,
    SkillCapability,
    SkillContext,
    SkillManifest,
    SkillResult,
)

logger = logging.getLogger(__name__)


class PRReviewerSkill(Skill):
    """
    Autonomous PR code review using multi-agent debate.

    Input:
        pr_url: GitHub PR URL (e.g. https://github.com/owner/repo/pull/123)
        OR
        diff: Raw diff text to review

    Output:
        Review findings with severity levels, consensus score, and actionable items.
    """

    def __init__(self, post_comment: bool = True, demo: bool = False):
        """
        Args:
            post_comment: Whether to post findings as a PR comment via gh CLI.
            demo: Use demo mode (no API keys required).
        """
        self._post_comment = post_comment
        self._demo = demo

    @property
    def manifest(self) -> SkillManifest:
        return SkillManifest(
            name="pr_reviewer",
            version="1.0.0",
            description="Multi-agent code review for pull requests",
            capabilities=[
                SkillCapability.EXTERNAL_API,
                SkillCapability.SHELL_EXECUTION,
                SkillCapability.DEBATE_CONTEXT,
                SkillCapability.LLM_INFERENCE,
            ],
            input_schema={
                "pr_url": {
                    "type": "string",
                    "description": "GitHub PR URL to review",
                    "required": False,
                },
                "diff": {
                    "type": "string",
                    "description": "Raw diff text (alternative to pr_url)",
                    "required": False,
                },
                "post_comment": {
                    "type": "boolean",
                    "description": "Post findings as a PR comment",
                    "default": True,
                },
            },
            tags=["code-review", "github", "automation", "dogfooding"],
            debate_compatible=True,
            requires_debate_context=False,
            max_execution_time_seconds=120.0,
            rate_limit_per_minute=10,
            author="aragora",
        )

    async def execute(self, input_data: dict[str, Any], context: SkillContext) -> SkillResult:
        """Run multi-agent code review on a PR or diff."""
        pr_url = input_data.get("pr_url")
        diff = input_data.get("diff")
        post_comment = input_data.get("post_comment", self._post_comment)

        if not pr_url and not diff:
            return SkillResult.create_failure(
                error_message="Either pr_url or diff is required",
                error_code="MISSING_INPUT",
            )

        # Step 1: Get the diff
        if pr_url and not diff:
            diff, error = await self._fetch_pr_diff(pr_url)
            if error:
                return SkillResult.create_failure(
                    error_message=f"Failed to fetch PR diff: {error}",
                    error_code="FETCH_FAILED",
                )
        if diff is None:
            return SkillResult.create_failure(
                error_message="No diff to review",
                error_code="MISSING_INPUT",
            )

        # Step 2: Run the review
        findings, error = await self._run_review(diff)
        if error:
            return SkillResult.create_failure(
                error_message=f"Review failed: {error}",
                error_code="REVIEW_FAILED",
            )

        # Step 3: Post comment if requested
        comment_url = None
        if post_comment and pr_url and findings is not None:
            comment_url, error = await self._post_pr_comment(pr_url, findings)
            if error:
                logger.warning("Failed to post PR comment: %s", error)

        result_data = {
            "findings": findings,
            "pr_url": pr_url,
            "comment_posted": comment_url is not None,
            "comment_url": comment_url,
        }
        return SkillResult.create_success(data=result_data)

    async def _fetch_pr_diff(self, pr_url: str) -> tuple[str | None, str | None]:
        """Fetch a PR diff using gh CLI."""
        # Extract owner/repo/number from URL
        parts = pr_url.rstrip("/").split("/")
        try:
            idx = parts.index("pull")
            owner_repo = "/".join(parts[idx - 2 : idx])
            pr_number = parts[idx + 1]
        except (ValueError, IndexError):
            return None, f"Invalid PR URL format: {pr_url}"

        try:
            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                ["gh", "pr", "diff", pr_number, "--repo", owner_repo],  # noqa: S607 -- fixed command
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return None, result.stderr.strip()
            return result.stdout, None
        except FileNotFoundError:
            return None, "gh CLI not found. Install: https://cli.github.com"
        except subprocess.TimeoutExpired:
            return None, "Timed out fetching PR diff"

    async def _run_review(
        self,
        diff: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Run the Aragora review engine on a diff."""
        return await self._run_review_subprocess(diff)

    async def _run_review_subprocess(
        self,
        diff: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Run ``aragora review`` as a subprocess and parse its JSON output."""
        try:
            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                self._review_command(),
                input=diff,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            return None, "aragora CLI not found"
        except subprocess.TimeoutExpired:
            return None, "Review timed out"
        if result.returncode != 0:
            return None, (
                result.stderr.strip() or f"aragora review exited with code {result.returncode}"
            )
        return self._parse_review_output(result.stdout), None

    def _review_command(self) -> list[str]:
        cmd = ["aragora", "review", "--output-format", "json"]
        if self._demo:
            cmd.append("--demo")
        return cmd

    @staticmethod
    def _parse_review_output(stdout: str) -> dict[str, Any]:
        """Return the first JSON object that starts a stdout line.

        ``aragora review --output-format json`` pretty-prints the object over many
        lines and may print log lines before it, so decode from the start of the
        first line that opens an object rather than line by line.
        """
        decoder = json.JSONDecoder()
        offset = 0
        for line in stdout.splitlines(keepends=True):
            stripped = line.lstrip()
            if stripped.startswith("{"):
                try:
                    value, _ = decoder.raw_decode(stdout, offset + len(line) - len(stripped))
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(value, dict):
                        return value
            offset += len(line)
        return {"raw_output": stdout}

    async def _post_pr_comment(
        self,
        pr_url: str,
        findings: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        """Post review findings as a PR comment using gh CLI."""
        parts = pr_url.rstrip("/").split("/")
        try:
            idx = parts.index("pull")
            owner_repo = "/".join(parts[idx - 2 : idx])
            pr_number = parts[idx + 1]
        except (ValueError, IndexError):
            return None, f"Invalid PR URL: {pr_url}"

        comment_body = self._format_comment(findings)

        try:
            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                [  # noqa: S607 -- fixed command
                    "gh",
                    "pr",
                    "comment",
                    pr_number,
                    "--repo",
                    owner_repo,
                    "--body",
                    comment_body,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return None, result.stderr.strip()
            # gh outputs the comment URL
            return result.stdout.strip() or pr_url, None
        except FileNotFoundError:
            return None, "gh CLI not found"
        except subprocess.TimeoutExpired:
            return None, "Timed out posting comment"

    def _format_comment(self, findings: dict[str, Any]) -> str:
        """Format review findings as a GitHub PR comment."""
        lines = ["## Aragora Multi-Agent Code Review", ""]

        score = findings.get("agreement_score", 0)
        if score:
            lines.append(f"**Consensus Score:** {score:.0%}")
            lines.append("")

        # Critical issues
        critical = findings.get("critical_issues", [])
        if critical:
            lines.append("### Critical Issues")
            for issue in critical:
                lines.append(f"- {issue}")
            lines.append("")

        # High issues
        high = findings.get("high_issues", [])
        if high:
            lines.append("### High Severity")
            for issue in high:
                lines.append(f"- {issue}")
            lines.append("")

        # Unanimous critiques
        unanimous = findings.get("unanimous_critiques", [])
        if unanimous:
            lines.append("### All Agents Agree")
            for critique in unanimous:
                lines.append(f"- {critique}")
            lines.append("")

        # Split opinions
        splits = findings.get("split_opinions", [])
        if splits:
            lines.append("### Split Opinions")
            for split in splits:
                if isinstance(split, dict):
                    lines.append(f"- **{split.get('issue', '')}**")
                    lines.append(f"  - Majority: {split.get('majority', '')}")
                    lines.append(f"  - Minority: {split.get('minority', '')}")
                else:
                    lines.append(f"- {split}")
            lines.append("")

        # Risk areas
        risks = findings.get("risk_areas", [])
        if risks:
            lines.append("### Risk Areas")
            for risk in risks:
                lines.append(f"- {risk}")
            lines.append("")

        if not any([critical, high, unanimous, splits, risks]):
            lines.append("No significant issues found.")
            lines.append("")

        lines.append("---")
        lines.append("*Reviewed by [Aragora](https://aragora.ai) multi-agent debate engine*")
        return "\n".join(lines)
