"""CodeImplementationTask workflow node.

Wraps the ClaudeCodeHarness.execute_implementation() method as a workflow
step, providing the concrete binding from debate-derived implementation
specs to harness execution and structured result output.

Config keys:
    repo_path: str - Repository path (required)
    implementation_prompt: str - Focused instructions for Claude Code
    files_to_modify: list[str] - Optional list of file paths to scope
    timeout_seconds: int - Execution timeout (default 600)
    harness_type: str - "claude-code" (default) or "codex"
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from aragora.workflow.step import BaseStep, WorkflowContext

logger = logging.getLogger(__name__)

# Stdout/stderr truncation limit for structured results
_MAX_SUMMARY_CHARS = 2000


class CodeImplementationTask(BaseStep):
    """Execute a code implementation task via the Claude Code harness.

    Unlike the generic HarnessStep (which supports both analysis and
    implementation modes), this step is purpose-built for the OpenClaw
    E2E loop: it takes an implementation prompt derived from a debate
    result, executes it through ClaudeCodeHarness.execute_implementation(),
    and returns structured output suitable for receipt generation.

    Config keys:
        repo_path: str - Repository to modify (required)
        implementation_prompt: str - What to implement
        files_to_modify: list[str] - Optional scope hint for the harness
        timeout_seconds: int - Execution timeout (default 600)
        harness_type: str - Harness backend ("claude-code" or "codex")
    """

    def __init__(self, name: str, config: dict[str, Any] | None = None):
        super().__init__(name, config)

    async def execute(self, context: WorkflowContext) -> dict[str, Any]:
        """Execute implementation via Claude Code harness."""
        config = {**self._config, **context.current_step_config}
        start_time = time.monotonic()

        repo_path_str = config.get("repo_path") or context.get_input("repo_path", ".")
        repo_path = Path(repo_path_str)
        implementation_prompt = config.get("implementation_prompt", "")
        files_to_modify: list[str] = config.get("files_to_modify", []) or []
        timeout_seconds = int(config.get("timeout_seconds", 600))
        harness_type = config.get("harness_type", "claude-code")

        if not implementation_prompt:
            return self._error_result(
                "No implementation_prompt provided",
                start_time,
                harness_type,
            )

        # Build the full prompt, scoping to files if provided
        full_prompt = implementation_prompt
        if files_to_modify:
            file_list = "\n".join(f"- {f}" for f in files_to_modify)
            full_prompt = f"{implementation_prompt}\n\nFocus on the following files:\n{file_list}"

        # Create the harness
        harness = await self._create_harness(harness_type, timeout_seconds)
        if harness is None:
            return self._error_result(
                f"Harness '{harness_type}' not available",
                start_time,
                harness_type,
            )

        # Initialize
        try:
            initialized = await harness.initialize()
            if not initialized:
                return self._error_result(
                    f"Harness '{harness_type}' failed to initialize",
                    start_time,
                    harness_type,
                )
        except (RuntimeError, OSError, ValueError, TypeError) as e:
            logger.warning("Harness initialization failed: %s", e)
            return self._error_result(
                f"Initialization failed: {type(e).__name__}",
                start_time,
                harness_type,
            )

        # Execute implementation
        try:
            stdout, stderr = await harness.execute_implementation(
                repo_path=repo_path,
                prompt=full_prompt,
            )

            elapsed = time.monotonic() - start_time
            exit_code = 0 if not stderr or "error" not in stderr.lower() else 1

            # Count files changed by scanning stdout for common patterns
            files_changed = self._count_files_changed(stdout)

            result: dict[str, Any] = {
                "harness": harness_type,
                "success": exit_code == 0,
                "exit_code": exit_code,
                "files_changed": files_changed,
                "stdout": stdout[:_MAX_SUMMARY_CHARS] if stdout else "",
                "stderr": stderr[:_MAX_SUMMARY_CHARS] if stderr else "",
                "duration_seconds": elapsed,
                "error": None,
            }

            logger.info(
                "CodeImplementationTask completed (exit=%d, files_changed=%d, %.1fs)",
                exit_code,
                files_changed,
                elapsed,
            )

            # Emit event
            context.emit_event(
                "code_implementation_complete",
                {
                    "harness": harness_type,
                    "success": exit_code == 0,
                    "files_changed": files_changed,
                    "duration_seconds": elapsed,
                },
            )

            return result

        except (RuntimeError, OSError, ValueError, TimeoutError) as e:
            elapsed = time.monotonic() - start_time
            logger.warning("Code implementation failed: %s", e)
            return {
                "harness": harness_type,
                "success": False,
                "exit_code": 1,
                "files_changed": 0,
                "stdout": "",
                "stderr": "",
                "duration_seconds": elapsed,
                "error": f"Execution failed: {type(e).__name__}",
            }

    @staticmethod
    async def _create_harness(
        harness_type: str,
        timeout_seconds: int,
    ) -> Any | None:
        """Create and configure a harness instance."""
        try:
            if harness_type == "claude-code":
                from aragora.harnesses.claude_code import (
                    ClaudeCodeConfig,
                    ClaudeCodeHarness,
                )

                cfg = ClaudeCodeConfig(timeout_seconds=timeout_seconds)
                return ClaudeCodeHarness(config=cfg)
            elif harness_type == "codex":
                from aragora.harnesses.codex import CodexHarness

                return CodexHarness()
            else:
                logger.warning("Unknown harness type: %s", harness_type)
                return None
        except (ImportError, AttributeError, TypeError) as e:
            logger.warning("Failed to create harness '%s': %s", harness_type, e)
            return None

    @staticmethod
    def _count_files_changed(stdout: str) -> int:
        """Heuristic count of files changed from harness stdout.

        Looks for common patterns like "Created file", "Modified file",
        or Write/Edit tool usage in Claude Code output.
        """
        import re

        patterns = [
            r"(?:Created|Modified|Wrote|Updated|Edited)\s+(?:file\s+)?[`'\"]?([^\s`'\"]+)",
            r"Write\s+→\s+(.+)",
            r"Edit\s+→\s+(.+)",
        ]
        files: set[str] = set()
        for pattern in patterns:
            for match in re.finditer(pattern, stdout, re.IGNORECASE):
                files.add(match.group(1).strip())
        return len(files) if files else 0

    @staticmethod
    def _error_result(
        error: str,
        start_time: float,
        harness_type: str,
    ) -> dict[str, Any]:
        """Build a standard error result dict."""
        return {
            "harness": harness_type,
            "success": False,
            "exit_code": 1,
            "files_changed": 0,
            "stdout": "",
            "stderr": "",
            "duration_seconds": time.monotonic() - start_time,
            "error": error,
        }
