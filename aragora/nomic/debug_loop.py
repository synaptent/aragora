"""Iterative debug loop for self-improvement agent execution.

Wraps agent execution with a test-failure-feedback-retry cycle:
1. Send implementation prompt to agent (via ClaudeCodeHarness)
2. Run tests on the result
3. If tests fail, build a "fix these failures" prompt
4. Repeat until tests pass or max retries exhausted

Usage:
    loop = DebugLoop()
    result = await loop.execute_with_retry(
        instruction="Fix the authentication bug",
        worktree_path="/tmp/worktree",
        test_scope=["tests/auth/"],
    )
    if result.success:
        print(f"Fixed in {result.total_attempts} attempts")
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DebugLoopConfig:
    """Configuration for the iterative debug loop."""

    max_retries: int = 3
    test_timeout: int = 120  # seconds per test run
    max_failure_context_chars: int = 3000  # truncate test output in retry prompt
    agent_timeout: int = 300  # seconds per agent execution


@dataclass
class DebugAttempt:
    """Result of a single debug attempt."""

    attempt_number: int
    prompt: str
    tests_passed: int = 0
    tests_failed: int = 0
    test_output: str = ""
    success: bool = False
    agent_stdout: str = ""
    agent_stderr: str = ""
    diff_context: str = ""  # git diff after this attempt


@dataclass
class DebugLoopResult:
    """Result of the complete debug loop."""

    subtask_id: str
    success: bool
    total_attempts: int
    attempts: list[DebugAttempt] = field(default_factory=list)
    final_tests_passed: int = 0
    final_tests_failed: int = 0
    final_files_changed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "subtask_id": self.subtask_id,
            "success": self.success,
            "total_attempts": self.total_attempts,
            "final_tests_passed": self.final_tests_passed,
            "final_tests_failed": self.final_tests_failed,
            "final_files_changed": self.final_files_changed,
            "attempts": [
                {
                    "attempt_number": a.attempt_number,
                    "tests_passed": a.tests_passed,
                    "tests_failed": a.tests_failed,
                    "success": a.success,
                }
                for a in self.attempts
            ],
        }


class DebugLoop:
    """Iterative debug loop wrapping agent execution with test feedback.

    Each iteration:
    1. Send prompt to ClaudeCodeHarness
    2. Run tests in worktree
    3. If tests fail, build retry prompt with failure context
    4. Repeat until success or max_retries exhausted
    """

    def __init__(self, config: DebugLoopConfig | None = None):
        self.config = config or DebugLoopConfig()

    async def execute_with_retry(
        self,
        instruction: str,
        worktree_path: str,
        test_scope: list[str] | None = None,
        subtask_id: str = "",
    ) -> DebugLoopResult:
        """Execute an instruction with test-driven retry loop.

        Args:
            instruction: The implementation prompt for the agent
            worktree_path: Path to the isolated worktree
            test_scope: Test directories/files to run after each attempt
            subtask_id: Identifier for logging

        Returns:
            DebugLoopResult with all attempt details
        """
        result = DebugLoopResult(
            subtask_id=subtask_id,
            success=False,
            total_attempts=0,
        )

        current_prompt = instruction

        for attempt_num in range(1, self.config.max_retries + 1):
            logger.info(
                "debug_loop_attempt attempt=%d/%d subtask=%s",
                attempt_num,
                self.config.max_retries,
                subtask_id[:30],
            )

            attempt = await self._run_attempt(
                current_prompt, worktree_path, test_scope, attempt_num
            )
            result.attempts.append(attempt)
            result.total_attempts = attempt_num

            if attempt.success:
                result.success = True
                result.final_tests_passed = attempt.tests_passed
                result.final_tests_failed = attempt.tests_failed
                result.final_files_changed = self._get_changed_files(worktree_path)

                # Auto-commit changes in worktree for downstream merge
                if result.final_files_changed:
                    try:
                        commit_result = subprocess.run(
                            ["git", "add", "-A"],  # fixed command
                            capture_output=True,
                            text=True,
                            cwd=worktree_path,
                            timeout=10,
                        )
                        if commit_result.returncode == 0:
                            subprocess.run(  # subprocess with fixed args, no shell
                                [  # fixed command
                                    "git",
                                    "commit",
                                    "-m",
                                    f"debug-loop: {subtask_id[:40]}",
                                ],
                                capture_output=True,
                                text=True,
                                cwd=worktree_path,
                                timeout=10,
                                check=False,
                            )
                    except (subprocess.TimeoutExpired, OSError):
                        pass

                logger.info(
                    "debug_loop_succeeded attempt=%d tests_passed=%d subtask=%s",
                    attempt_num,
                    attempt.tests_passed,
                    subtask_id[:30],
                )
                break

            # Build retry prompt with failure context
            if attempt_num < self.config.max_retries:
                current_prompt = self._build_retry_prompt(instruction, attempt)

        if not result.success:
            # Record final state even on failure
            last = result.attempts[-1] if result.attempts else None
            if last:
                result.final_tests_passed = last.tests_passed
                result.final_tests_failed = last.tests_failed
            result.final_files_changed = self._get_changed_files(worktree_path)

            logger.warning(
                "debug_loop_exhausted attempts=%d tests_failed=%d subtask=%s",
                result.total_attempts,
                result.final_tests_failed,
                subtask_id[:30],
            )

        return result

    async def _run_attempt(
        self,
        prompt: str,
        worktree_path: str,
        test_scope: list[str] | None,
        attempt_number: int,
    ) -> DebugAttempt:
        """Run a single attempt: agent execution + test validation."""
        attempt = DebugAttempt(
            attempt_number=attempt_number,
            prompt=prompt[:500],
        )

        # Step 1: Run agent
        stdout, stderr = await self._run_agent(prompt, worktree_path)
        attempt.agent_stdout = stdout[:1000]
        attempt.agent_stderr = stderr[:500]

        # Step 1b: Capture git diff for retry context
        attempt.diff_context = self._get_diff(worktree_path)

        # Step 2: Run tests
        test_result = await self._run_tests(worktree_path, test_scope)
        attempt.tests_passed = test_result.get("passed", 0)
        attempt.tests_failed = test_result.get("failed", 0)
        attempt.test_output = test_result.get("output", "")
        attempt.success = attempt.tests_failed == 0 and attempt.tests_passed > 0

        return attempt

    async def _run_agent(
        self,
        prompt: str,
        worktree_path: str,
    ) -> tuple[str, str]:
        """Execute the agent via ClaudeCodeHarness.

        Returns (stdout, stderr) tuple.
        Raises RuntimeError when claude CLI is not in PATH.
        """
        import shutil

        if not shutil.which("claude"):
            raise RuntimeError("Claude CLI not found in PATH")

        try:
            from aragora.harnesses.claude_code import (
                ClaudeCodeConfig,
                ClaudeCodeHarness,
            )
            from aragora.harnesses.base import HarnessError
            from aragora.pipeline.execution_mode import ExecutionMode

            config = ClaudeCodeConfig(
                timeout_seconds=self.config.agent_timeout,
                use_mcp_tools=False,
                execution_mode=ExecutionMode.AUTONOMOUS,
            )
            harness = ClaudeCodeHarness(config)

            stdout, stderr = await harness.execute_implementation(
                repo_path=Path(worktree_path),
                prompt=prompt,
            )
            return stdout, stderr

        except ImportError as exc:
            logger.debug("ClaudeCodeHarness unavailable: %s", exc)
            return "", ""
        except (RuntimeError, OSError, asyncio.TimeoutError, HarnessError) as exc:
            logger.warning("Agent execution failed: %s", exc)
            return "", str(exc)

    async def _run_tests(
        self,
        worktree_path: str,
        test_scope: list[str] | None,
    ) -> dict[str, Any]:
        """Run tests in worktree and return results.

        Returns dict with keys: passed, failed, output
        """
        cmd = [sys.executable, "-m", "pytest", "-x", "-q", "--tb=short"]

        if test_scope:
            cmd.extend(test_scope)

        try:
            proc_result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                cwd=worktree_path,
                timeout=self.config.test_timeout,
            )

            output = proc_result.stdout + proc_result.stderr
            passed = 0
            failed = 0

            passed_match = re.search(r"(\d+) passed", output)
            failed_match = re.search(r"(\d+) failed", output)

            if passed_match:
                passed = int(passed_match.group(1))
            if failed_match:
                failed = int(failed_match.group(1))

            return {"passed": passed, "failed": failed, "output": output}

        except subprocess.TimeoutExpired:
            logger.warning("Test run timed out after %ds", self.config.test_timeout)
            return {"passed": 0, "failed": 0, "output": "TIMEOUT"}
        except OSError as exc:
            logger.warning("Test run failed: %s", exc)
            return {"passed": 0, "failed": 0, "output": str(exc)}

    def _build_retry_prompt(
        self,
        original_instruction: str,
        failed_attempt: DebugAttempt,
    ) -> str:
        """Build a retry prompt incorporating test failure context.

        Includes the original objective, the test output (truncated),
        and instructions to fix rather than revert.
        """
        # Truncate test output to configured max
        test_output = failed_attempt.test_output
        if len(test_output) > self.config.max_failure_context_chars:
            test_output = test_output[: self.config.max_failure_context_chars] + "\n... [truncated]"

        # Include diff of what the previous attempt changed
        diff_section = ""
        if failed_attempt.diff_context:
            diff_text = failed_attempt.diff_context
            if len(diff_text) > self.config.max_failure_context_chars:
                diff_text = diff_text[: self.config.max_failure_context_chars] + "\n... [truncated]"
            diff_section = f"""
CHANGES MADE SO FAR (git diff):
```diff
{diff_text}
```
"""

        return f"""RETRY ATTEMPT {failed_attempt.attempt_number + 1}: Fix the test failures below.

ORIGINAL OBJECTIVE:
{original_instruction[:1000]}
{diff_section}
TEST FAILURES (attempt {failed_attempt.attempt_number}):
{failed_attempt.tests_passed} tests passed, {failed_attempt.tests_failed} tests failed.

TEST OUTPUT:
{test_output}

INSTRUCTIONS:
- Fix the failing tests by correcting the implementation (not by deleting or skipping tests)
- Do not revert previous changes — build on what was done
- Focus on the root cause of the failures
- Run tests again after making changes
"""

    @staticmethod
    def _get_diff(worktree_path: str, max_chars: int = 5000) -> str:
        """Capture current git diff in the worktree.

        Returns the unified diff of all uncommitted changes, truncated to
        *max_chars*.  Used to give retry attempts context about what the
        previous attempt changed.
        """
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD"],  # fixed command
                capture_output=True,
                text=True,
                cwd=worktree_path,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                diff = result.stdout
                if len(diff) > max_chars:
                    diff = diff[:max_chars] + "\n... [truncated]"
                return diff
        except (subprocess.TimeoutExpired, OSError):
            pass
        return ""

    def _get_changed_files(self, worktree_path: str) -> list[str]:
        """Get list of changed files in the worktree via git diff."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],  # fixed command
                capture_output=True,
                text=True,
                cwd=worktree_path,
                timeout=10,
            )
            if result.returncode == 0:
                return [f for f in result.stdout.strip().split("\n") if f]
        except (subprocess.TimeoutExpired, OSError):
            pass
        return []


__all__ = [
    "DebugLoop",
    "DebugLoopConfig",
    "DebugAttempt",
    "DebugLoopResult",
]
