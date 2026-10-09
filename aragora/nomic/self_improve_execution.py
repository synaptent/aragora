"""Subtask execution steps for the self-improvement pipeline.

``SelfImprovePipeline`` (``aragora.nomic.self_improve``) inherits these methods: single
subtask execution, the debug loop, Claude Code dispatch with budget tracking, worktree
test runs, instruction files and subtask receipts. Import the pipeline and its public
names from ``aragora.nomic.self_improve``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.nomic.self_improve import SelfImproveConfig

# The facade's logger name, so log filters and caplog assertions keyed on
# "aragora.nomic.self_improve" still see records from the moved methods.
logger = logging.getLogger("aragora.nomic.self_improve")


class BudgetExceededError(RuntimeError):
    """Raised when the self-improvement pipeline exceeds its budget."""


class SelfImproveExecutionMixin:
    """Per-subtask execution steps inherited by ``SelfImprovePipeline``."""

    config: SelfImproveConfig
    _total_spend_usd: float

    async def _execute_single(
        self,
        subtask: Any,
        cycle_id: str,
        goal: Any | None = None,
    ) -> dict[str, Any]:
        """Execute a single subtask.

        In the current implementation, this generates an execution description
        but does not yet dispatch to a Claude Code session. This is the
        integration point where an execution agent would be invoked.

        Args:
            subtask: A SubTask, TaskDecomposition, TrackAssignment, or raw string
            cycle_id: The cycle identifier for logging
            goal: Optional PrioritizedGoal for richer instruction context

        Returns:
            Dict with execution outcome
        """
        # Extract description from various subtask types
        if isinstance(subtask, str):
            desc = subtask
        elif hasattr(subtask, "goal") and hasattr(subtask.goal, "description"):
            # TrackAssignment
            desc = subtask.goal.description
        elif hasattr(subtask, "original_task"):
            # TaskDecomposition
            desc = subtask.original_task
        elif hasattr(subtask, "description"):
            desc = str(subtask.description)
        elif hasattr(subtask, "title"):
            desc = str(subtask.title)
        else:
            desc = str(subtask)

        logger.info("execute_subtask cycle=%s task=%s", cycle_id, desc[:80])

        # Read file contents for richer prompts
        file_contents = self._read_file_contents(subtask)

        # Extract worktree_path hint early so create_instruction can embed it
        wt_hint = getattr(subtask, "worktree_path", None)
        worktree_path = str(wt_hint) if wt_hint is not None else None

        # Attempt to use ExecutionBridge to generate + dispatch instruction
        try:
            from aragora.nomic.execution_bridge import ExecutionBridge

            bridge = ExecutionBridge()
            instruction = bridge.create_instruction(
                subtask,
                file_contents=file_contents,
                goal=goal,
                worktree_path=worktree_path,
            )

            logger.info(
                "execution_instruction generated subtask=%s",
                getattr(instruction, "subtask_id", "unknown")[:20],
            )

            # Write instruction to worktree for agent pickup
            dispatched = False
            executed = False
            # Prefer worktree_path from instruction (may have been enriched)
            if instruction.worktree_path:
                worktree_path = instruction.worktree_path
            files_changed: list[str] = []
            tests_passed = 0
            tests_failed = 0

            if worktree_path:
                dispatched = self._write_instruction_to_worktree(instruction, worktree_path)

                # Try debug loop first (iterative test-feedback-retry)
                debug_result = await self._execute_with_debug_loop(
                    instruction, worktree_path, subtask
                )
                if debug_result is not None:
                    executed = True
                    files_changed = debug_result.get("files_changed", [])
                    tests_passed = debug_result.get("tests_passed", 0)
                    tests_failed = debug_result.get("tests_failed", 0)
                else:
                    # Fallback: single dispatch via Claude Code harness
                    exec_result = await self._dispatch_to_claude_code(instruction, worktree_path)
                    if exec_result is not None:
                        executed = True
                        files_changed = exec_result.get("files_changed", [])
                        tests_passed = exec_result.get("tests_passed", 0)
                        tests_failed = exec_result.get("tests_failed", 0)
                    else:
                        logger.warning(
                            "execute_subtask dispatch returned None for %s",
                            desc[:80],
                        )

            # Verify changes via PRReviewRunner if available
            if files_changed and worktree_path:
                try:
                    from aragora.nomic.execution_bridge import ExecutionResult

                    exec_result_obj = ExecutionResult(
                        subtask_id=getattr(instruction, "subtask_id", "unknown"),
                        success=True,
                        files_changed=files_changed,
                        diff_summary="\n".join(files_changed),
                    )
                    verification = await bridge.verify_changes(exec_result_obj)
                    logger.info(
                        "Verification result for %s: %s",
                        desc[:40],
                        verification.get("verified", "unknown"),
                    )
                except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
                    logger.debug("Verification skipped: %s", exc)

            # Auto-commit changes in worktree for downstream merge
            if files_changed and worktree_path:
                try:
                    commit_result = subprocess.run(
                        ["git", "add", "-A"],  # noqa: S607 -- fixed command
                        capture_output=True,
                        text=True,
                        cwd=worktree_path,
                        timeout=10,
                    )
                    if commit_result.returncode == 0:
                        subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                            [  # noqa: S607 -- fixed command
                                "git",
                                "commit",
                                "-m",
                                f"self-improve: {getattr(instruction, 'subtask_id', 'unknown')[:40]}",
                            ],
                            capture_output=True,
                            text=True,
                            cwd=worktree_path,
                            timeout=10,
                            check=False,
                        )
                except (subprocess.TimeoutExpired, OSError):
                    pass

            # Generate per-subtask execution receipt
            receipt_hash = self._generate_subtask_receipt(
                subtask_id=getattr(instruction, "subtask_id", "unknown"),
                cycle_id=cycle_id,
                desc=desc,
                files_changed=files_changed,
                success=executed and tests_failed == 0,
            )

            return {
                "success": executed and len(files_changed) > 0,
                "subtask": desc[:100],
                "instruction_generated": True,
                "instruction_dispatched": dispatched,
                "instruction_executed": executed,
                "worktree_path": worktree_path,
                "files_changed": files_changed,
                "tests_passed": tests_passed,
                "tests_failed": tests_failed,
                "receipt_hash": receipt_hash,
            }
        except ImportError:
            pass
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            logger.debug("ExecutionBridge failed: %s", exc)

        return {
            "success": False,
            "subtask": desc[:100],
            "instruction_generated": False,
            "instruction_dispatched": False,
            "files_changed": [],
            "tests_passed": 0,
            "tests_failed": 0,
        }

    async def _execute_with_debug_loop(
        self,
        instruction: Any,
        worktree_path: str,
        subtask: Any = None,
    ) -> dict[str, Any] | None:
        """Execute via iterative debug loop with test-failure-retry.

        Returns None if the debug loop is disabled or unavailable,
        falling back to the single-dispatch path.
        """
        if not self.config.enable_debug_loop:
            return None

        try:
            from aragora.nomic.debug_loop import DebugLoop, DebugLoopConfig

            config = DebugLoopConfig(
                max_retries=self.config.debug_loop_max_retries,
                test_timeout=self.config.metrics_test_timeout,
            )
            debug = DebugLoop(config)

            prompt = instruction.to_agent_prompt()
            subtask_id = getattr(instruction, "subtask_id", "unknown")

            # Infer test scope from file_hints
            test_scope = self._infer_test_scope(subtask)

            debug_result = await debug.execute_with_retry(
                instruction=prompt,
                worktree_path=worktree_path,
                test_scope=test_scope or None,
                subtask_id=subtask_id,
            )

            return {
                "files_changed": debug_result.final_files_changed,
                "tests_passed": debug_result.final_tests_passed,
                "tests_failed": debug_result.final_tests_failed,
                "debug_loop_attempts": debug_result.total_attempts,
                "debug_loop_success": debug_result.success,
            }

        except ImportError:
            logger.debug("DebugLoop not available, falling back to single dispatch")
            return None
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Debug loop failed, falling back: %s", exc)
            return None

    def _infer_test_scope(self, subtask: Any) -> list[str]:
        """Infer test directories from subtask file hints."""
        test_dirs: list[str] = []
        file_hints = getattr(subtask, "file_scope", [])
        if not file_hints and hasattr(subtask, "goal"):
            file_hints = getattr(subtask.goal, "file_hints", [])

        for hint in file_hints:
            if hint.startswith("aragora/"):
                parts = hint.split("/")
                if len(parts) >= 2:
                    test_dir = f"tests/{parts[1]}"
                    if test_dir not in test_dirs:
                        test_dirs.append(test_dir)
            elif hint.startswith("tests/"):
                if hint not in test_dirs:
                    test_dirs.append(hint)

        return test_dirs

    @staticmethod
    def _read_file_contents(
        subtask: Any,
        max_chars_per_file: int = 2000,
        max_total_chars: int = 10000,
    ) -> dict[str, str]:
        """Read truncated file contents from subtask file_scope.

        Gives the execution agent real code context instead of just file paths.
        Reads the first ``max_chars_per_file`` characters of each file,
        capped at ``max_total_chars`` total across all files.

        Returns:
            Dict mapping file path -> truncated content.
        """
        from pathlib import Path as P

        file_hints: list[str] = getattr(subtask, "file_scope", [])
        if not file_hints and hasattr(subtask, "goal"):
            file_hints = getattr(subtask.goal, "file_hints", [])

        contents: dict[str, str] = {}
        total = 0

        for hint in file_hints:
            if total >= max_total_chars:
                break
            path = P(hint)
            if not path.exists() or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                budget = min(max_chars_per_file, max_total_chars - total)
                snippet = text[:budget]
                if len(text) > budget:
                    snippet += "\n# ... [truncated]"
                contents[hint] = snippet
                total += len(snippet)
            except OSError:
                continue

        return contents

    def _assess_execution_risk(self, instruction: Any) -> str:
        """Assess risk level of an execution instruction.

        Returns "low", "medium", or "high" based on:
        - File count and scope (tests-only = low, core modules = high)
        - Whether files are in protected paths (CLAUDE.md, __init__.py, etc.)
        - Whether the instruction involves deletions vs additions
        """
        file_hints: list[str] = getattr(instruction, "file_hints", [])
        if not file_hints:
            file_hints = getattr(instruction, "file_scope", [])

        # Protected files -> always high risk
        protected = {"CLAUDE.md", "__init__.py", ".env", "nomic_loop.py"}
        if any(any(p in f for p in protected) for f in file_hints):
            return "high"

        # Tests-only changes -> low risk
        if all(f.startswith("tests/") for f in file_hints) and file_hints:
            return "low"

        # Many files -> high risk
        if len(file_hints) > 10:
            return "high"

        # Core modules -> medium risk
        core_paths = {"aragora/debate/", "aragora/server/", "aragora/nomic/"}
        if any(any(f.startswith(c) for c in core_paths) for f in file_hints):
            return "medium"

        return "low"

    async def _dispatch_to_claude_code(
        self,
        instruction: Any,
        worktree_path: str,
    ) -> dict[str, Any] | None:
        """Dispatch an instruction to Claude Code CLI for execution.

        Uses ClaudeCodeHarness.execute_implementation() to run the instruction
        in the given worktree directory. Returns None if the CLI is not
        available or if dispatch is skipped (e.g., require_approval is True
        and no approval mechanism exists yet).

        Args:
            instruction: ExecutionInstruction with to_agent_prompt()
            worktree_path: Path to the isolated worktree

        Returns:
            Dict with execution results, or None if dispatch was skipped.
        """
        if self.config.require_approval:
            try:
                from aragora.nomic.approval import ApprovalGate, ApprovalDecision

                mode = "auto" if self.config.autonomous else "cli"
                gate = ApprovalGate(
                    mode=mode,
                    callback_url=getattr(self.config, "approval_callback_url", None),
                )
                decision = await gate.request_approval(instruction)

                if decision == ApprovalDecision.REJECT:
                    logger.info(
                        "dispatch_rejected subtask=%s",
                        instruction.subtask_id[:20],
                    )
                    return None
                if decision == ApprovalDecision.DEFER:
                    logger.info(
                        "dispatch_deferred subtask=%s",
                        instruction.subtask_id[:20],
                    )
                    return {"deferred": True, "risk_level": "high", "files_changed": []}
                if decision == ApprovalDecision.SKIP:
                    logger.info(
                        "dispatch_skipped subtask=%s",
                        instruction.subtask_id[:20],
                    )
                    return {"skipped": True, "files_changed": []}
                # APPROVE: fall through to execution
            except ImportError:
                # Fallback to legacy gate if approval module unavailable
                if not self.config.autonomous:
                    logger.info(
                        "dispatch_skipped reason=require_approval subtask=%s",
                        instruction.subtask_id[:20],
                    )
                    return None

        try:
            import shutil

            if not shutil.which("claude"):
                logger.debug("Claude Code CLI not found in PATH, skipping dispatch")
                return None

            from pathlib import Path as P
            from aragora.harnesses.claude_code import ClaudeCodeHarness, ClaudeCodeConfig
            from aragora.pipeline.execution_mode import ExecutionMode

            config = ClaudeCodeConfig(
                timeout_seconds=int(
                    min(self.config.budget_limit_usd * 60, 600)  # Budget → timeout
                ),
                use_mcp_tools=False,  # Keep it simple for now
                execution_mode=ExecutionMode.AUTONOMOUS,
            )
            harness = ClaudeCodeHarness(config)
            prompt = instruction.to_agent_prompt()

            stdout, stderr = await harness.execute_implementation(
                repo_path=P(worktree_path),
                prompt=prompt,
            )

            # Parse files changed from git diff in worktree
            files_changed: list[str] = []
            try:
                import subprocess

                diff_result = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD"],  # noqa: S607 -- fixed command
                    capture_output=True,
                    text=True,
                    cwd=worktree_path,
                    timeout=10,
                )
                if diff_result.returncode == 0:
                    files_changed = [f for f in diff_result.stdout.strip().split("\n") if f]
            except (subprocess.TimeoutExpired, OSError):
                pass

            # Run tests if configured
            tests_passed = 0
            tests_failed = 0
            if self.config.run_tests and files_changed:
                test_result = await self._run_tests_in_worktree(worktree_path)
                tests_passed = test_result.get("passed", 0)
                tests_failed = test_result.get("failed", 0)

            # Parse cost from Claude Code output
            cost_usd = self._parse_cost_from_output(stdout)
            self._total_spend_usd += cost_usd

            logger.info(
                "dispatch_completed subtask=%s files=%d tests=%d/%d cost=$%.4f",
                instruction.subtask_id[:20],
                len(files_changed),
                tests_passed,
                tests_passed + tests_failed,
                cost_usd,
            )

            # Check budget
            if self._total_spend_usd > self.config.budget_limit_usd:
                logger.warning(
                    "budget_exceeded spend=%.2f limit=%.2f",
                    self._total_spend_usd,
                    self.config.budget_limit_usd,
                )
                raise BudgetExceededError(
                    f"Spent ${self._total_spend_usd:.2f} of "
                    f"${self.config.budget_limit_usd:.2f} budget"
                )

            return {
                "files_changed": files_changed,
                "tests_passed": tests_passed,
                "tests_failed": tests_failed,
                "stdout_len": len(stdout),
                "cost_usd": cost_usd,
            }

        except BudgetExceededError:
            raise  # Let budget errors propagate
        except ImportError as exc:
            logger.debug("ClaudeCodeHarness not available: %s", exc)
            return None
        except (RuntimeError, OSError, asyncio.TimeoutError) as exc:
            logger.warning("Claude Code dispatch failed: %s", exc)
            return None

    @staticmethod
    def _parse_cost_from_output(output: str) -> float:
        """Parse cost from Claude Code CLI output.

        Looks for patterns like ``Total cost: $0.42`` or token counts
        to estimate cost.
        """
        import re

        # Direct cost reporting: "Total cost: $X.XX"
        m = re.search(r"(?:Total cost|Cost):\s*\$?([\d.]+)", output)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass

        # Estimate from token counts: "input=1234, output=5678"
        m = re.search(r"input[=:]\s*(\d+).*?output[=:]\s*(\d+)", output)
        if m:
            input_tokens = int(m.group(1))
            output_tokens = int(m.group(2))
            # Rough estimate: $3/M input, $15/M output (Claude pricing)
            return (input_tokens * 3 + output_tokens * 15) / 1_000_000

        return 0.0

    async def _run_tests_in_worktree(
        self,
        worktree_path: str,
    ) -> dict[str, int]:
        """Run pytest in a worktree and return pass/fail counts."""
        try:
            import subprocess

            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "pytest", "--tb=no", "-q", "--timeout=30"],
                capture_output=True,
                text=True,
                cwd=worktree_path,
                timeout=300,
            )

            # Parse pytest summary line: "X passed, Y failed"
            passed = 0
            failed = 0
            for line in result.stdout.splitlines():
                if "passed" in line:
                    import re

                    m = re.search(r"(\d+) passed", line)
                    if m:
                        passed = int(m.group(1))
                    m = re.search(r"(\d+) failed", line)
                    if m:
                        failed = int(m.group(1))

            return {"passed": passed, "failed": failed}

        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Test run failed in worktree: %s", exc)
            return {"passed": 0, "failed": 0}

    @staticmethod
    def _write_instruction_to_worktree(
        instruction: Any,
        worktree_path: str,
    ) -> bool:
        """Write an execution instruction file into a worktree.

        Creates `.aragora/instruction.md` in the worktree root so a
        Claude Code session opened in that directory picks it up as context.

        Returns True if the file was written successfully.
        """
        from pathlib import Path

        wt = Path(worktree_path)
        if not wt.exists():
            logger.debug("Worktree path does not exist: %s", worktree_path)
            return False

        instruction_dir = wt / ".aragora"
        instruction_dir.mkdir(parents=True, exist_ok=True)

        prompt = instruction.to_agent_prompt()
        instruction_file = instruction_dir / "instruction.md"
        instruction_file.write_text(prompt, encoding="utf-8")

        # Also write machine-readable JSON for programmatic pickup
        json_file = instruction_dir / "instruction.json"
        json_file.write_text(
            json.dumps(instruction.to_dict(), indent=2),
            encoding="utf-8",
        )

        logger.info(
            "instruction_written worktree=%s subtask=%s",
            worktree_path,
            instruction.subtask_id[:20],
        )
        return True

    @staticmethod
    def _generate_subtask_receipt(
        subtask_id: str,
        cycle_id: str,
        desc: str,
        files_changed: list[str],
        success: bool,
    ) -> str | None:
        """Generate a DecisionReceipt for a completed subtask.

        Returns the receipt hash string, or None if receipt generation fails.
        """
        try:
            import hashlib

            # Build a deterministic receipt content hash
            content = f"{cycle_id}:{subtask_id}:{desc}:{','.join(sorted(files_changed))}:{success}"
            receipt_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            try:
                from aragora.export.decision_receipt import DecisionReceipt

                receipt = DecisionReceipt(
                    receipt_id=f"si_{subtask_id}_{receipt_hash}",
                    gauntlet_id=f"si_{cycle_id}",
                    verdict="APPROVED" if success else "REJECTED",
                    input_summary=desc[:200],
                )

                # Persist receipt to KM
                from aragora.knowledge.mound.adapters.receipt_adapter import ReceiptAdapter
                import asyncio

                adapter = ReceiptAdapter()
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        adapter.ingest_receipt(
                            receipt,
                            tags=["self_improve", "subtask", cycle_id],
                        )
                    )
                except RuntimeError:
                    pass
            except ImportError:
                pass

            logger.info(
                "subtask_receipt generated=%s subtask=%s success=%s",
                receipt_hash,
                subtask_id[:20],
                success,
            )
            return receipt_hash

        except (RuntimeError, ValueError, TypeError) as exc:
            logger.debug("Subtask receipt generation failed: %s", exc)
            return None


__all__ = ["BudgetExceededError", "SelfImproveExecutionMixin"]
