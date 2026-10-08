"""
Hybrid multi-model executor.

Updated routing based on empirical performance data (Dec 2025):
- Claude: ALL implementation tasks (37% faster than alternatives, best code quality)
- Codex: Code review / QA after implementation (high quality review, latency-tolerant)
- Gemini: Planning only (handled by planner.py, leverages 1M context window)

Research sources:
- Claude completed projects in 1h17m vs Gemini's 2h2m (37% faster)
- Codex has known latency issues (5-20 min for simple tasks per GitHub issues)
- Claude produces "production-ready codebase with organized folders"
- Codex excels at review/QA where latency isn't critical
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from aragora.agents.cli_agents import ClaudeAgent, CodexAgent

from .types import ImplementTask, TaskResult

# Feature flags for task splitting (Jan 2026)
# COMPLEXITY_TIMEOUT: Use task complexity to calculate timeouts (default ON)
# DECOMPOSE_FAILED: Decompose failed complex tasks into subtasks (default OFF)
# PARALLEL_TASKS: Execute independent tasks in parallel (default OFF)
COMPLEXITY_TIMEOUT = os.environ.get("IMPL_COMPLEXITY_TIMEOUT", "1") == "1"
DECOMPOSE_FAILED = os.environ.get("IMPL_DECOMPOSE_FAILED", "0") == "1"
PARALLEL_TASKS = os.environ.get("IMPL_PARALLEL_TASKS", "0") == "1"
MAX_PARALLEL = int(os.environ.get("IMPL_MAX_PARALLEL", "2"))

TASK_PROMPT_TEMPLATE = """Implement this task in the codebase:

## Task
{description}

## Files to Create/Modify
{files}

## Historical Context
{memory_context}

## Repository
Working directory: {repo_path}

## Instructions

1. Create or modify the files listed above
2. Follow existing code style and patterns
3. Include docstrings and type hints
4. Make only the changes necessary for this task
5. Do not break existing functionality

IMPORTANT: Only make changes that are safe and reversible.
"""

TASK_REVIEW_PROMPT_TEMPLATE = """Review this implementation for correctness and safety.

## Task
{description}

## Files
{files}

## Git Diff
```
{diff}
```

## Response Format
- APPROVED: yes/no
- ISSUES: List any problems that MUST be fixed
- SUGGESTIONS: Optional improvements

Be concise and actionable."""


class HybridExecutor:
    """
    Executes implementation tasks using Claude, with optional Codex review.

    Updated routing strategy (Dec 2025):
    - ALL tasks: Claude (fastest, best quality for implementation)
    - Post-implementation: Codex review (optional QA phase)
    - Fallback: Codex if Claude times out (resilience)

    Rationale:
    - Codex has severe latency issues (GitHub #5149, #1811, #6990)
    - Claude is 37% faster and produces more organized code
    - Codex quality shines in review mode where latency is acceptable

    Resilience features (Jan 2026):
    - Retry failed tasks with 2x timeout
    - Model fallback on timeout (Claude → Codex)
    - Continue execution after failures (collect, retry at end)
    """

    def __init__(
        self,
        repo_path: Path,
        claude_timeout: int = 1200,  # 20 min - doubled from 600
        codex_timeout: int = 1200,  # 20 min - doubled from 600
        max_retries: int = 2,
        strategy: str | None = None,
        implementers: list[str] | None = None,
        critic: str | None = None,
        reviser: str | None = None,
        max_revisions: int | None = None,
        complexity_router: dict[str, str] | None = None,
        task_type_router: dict[str, str] | None = None,
        capability_router: dict[str, str] | None = None,
        use_harness: bool = True,
        sandbox_mode: bool = True,
        sandbox_image: str = "python:3.11-slim",
        sandbox_memory_mb: int = 2048,
        memory_gateway: Any | None = None,
    ):
        self.repo_path = repo_path

        # Allow env var override for use_harness (backwards compatibility)
        env_use_harness = os.environ.get("IMPL_USE_HARNESS")
        if env_use_harness is not None:
            use_harness = env_use_harness == "1"
        self.use_harness = use_harness
        self.sandbox_mode = sandbox_mode
        self.sandbox_image = sandbox_image
        self.sandbox_memory_mb = sandbox_memory_mb
        self._memory_gateway = memory_gateway

        # Initialize agents lazily (created on first use)
        self._claude: ClaudeAgent | None = None
        self._codex: CodexAgent | None = None

        self.claude_timeout = claude_timeout
        self.codex_timeout = codex_timeout
        self.max_retries = max_retries

        # Strategy configuration
        env_strategy = os.environ.get("IMPL_STRATEGY")
        self._strategy = (strategy or env_strategy or "direct").strip().lower()
        self._review_strict = self._strategy.endswith("strict")
        self._max_revisions = (
            max_revisions
            if max_revisions is not None
            else int(os.environ.get("IMPL_MAX_REVISIONS", "1"))
        )

        env_implementers = os.environ.get("IMPL_IMPLEMENTERS", "")
        env_critic = os.environ.get("IMPL_CRITIC", "")
        env_reviser = os.environ.get("IMPL_REVISER", "")
        env_complexity_router = os.environ.get("IMPL_AGENT_BY_COMPLEXITY", "")
        env_task_type_router = os.environ.get("IMPL_AGENT_BY_TASK_TYPE", "")
        env_capability_router = os.environ.get("IMPL_AGENT_BY_CAPABILITY", "")

        self._implementer_pool = self._parse_agent_list(implementers, env_implementers)
        self._critic_type = (critic or env_critic or "codex").strip()
        self._reviser_type = (reviser or env_reviser or "").strip()
        self._complexity_router = complexity_router or self._parse_router_map(env_complexity_router)
        self._task_type_router = task_type_router or self._parse_router_map(env_task_type_router)
        self._capability_router = capability_router or self._parse_router_map(env_capability_router)
        self._implementer_index = 0
        self._dynamic_agents: dict[tuple[str, str], Any] = {}

    @property
    def claude(self) -> ClaudeAgent:
        if self._claude is None:
            self._claude = ClaudeAgent(
                name="claude-implementer",
                model="claude",
                role="implementer",
                timeout=self.claude_timeout,
            )
            self._claude.system_prompt = """You are implementing code changes in a repository.
Be precise, follow existing patterns, and make only necessary changes.
Include proper type hints and docstrings."""
        return self._claude

    @property
    def codex(self) -> CodexAgent:
        if self._codex is None:
            self._codex = CodexAgent(
                name="codex-specialist",
                model="o3",
                role="implementer",
                timeout=self.codex_timeout,
            )
            self._codex.system_prompt = """You are implementing a focused code change.
Make only the changes specified. Follow existing code style."""
        return self._codex

    @staticmethod
    def _parse_agent_list(override: list[str] | None, raw: str) -> list[str]:
        if override is not None:
            return [item.strip() for item in override if item and item.strip()]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @staticmethod
    def _parse_router_map(raw: str) -> dict[str, str]:
        mapping: dict[str, str] = {}
        if not raw:
            return mapping
        for entry in raw.split(","):
            if ":" not in entry:
                continue
            key, value = entry.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key and value:
                mapping[key] = value
        return mapping

    @staticmethod
    def _parse_complexity_router(raw: str) -> dict[str, str]:
        """Backward-compatible alias for router parsing."""
        return HybridExecutor._parse_router_map(raw)

    def _get_dynamic_agent(
        self, agent_type: str, role: str, timeout: int, system_prompt: str
    ) -> Any | None:
        if not agent_type:
            return None
        if agent_type == "claude":
            agent: Any = self.claude
            if hasattr(agent, "timeout"):
                agent.timeout = timeout
            if system_prompt and hasattr(agent, "system_prompt"):
                agent.system_prompt = system_prompt
            return agent
        if agent_type == "codex":
            agent = self.codex
            if hasattr(agent, "timeout"):
                agent.timeout = timeout
            if system_prompt and hasattr(agent, "system_prompt"):
                agent.system_prompt = system_prompt
            return agent

        key = (agent_type, role)
        agent = self._dynamic_agents.get(key)
        if agent is None:
            try:
                from aragora.agents.registry import AgentRegistry, register_all_agents

                register_all_agents()
                spec = AgentRegistry.get_spec(agent_type)
                if spec is None or spec.agent_type != "CLI":
                    logger.warning(
                        "Implementation agent %s is not a CLI agent; skipping.",
                        agent_type,
                    )
                    return None
                agent = AgentRegistry.create(
                    model_type=agent_type,
                    name=f"{agent_type}-{role}",
                    role=role,
                    timeout=timeout,
                    use_cache=False,
                )
                self._dynamic_agents[key] = agent
            except (ImportError, RuntimeError, ValueError) as exc:
                logger.warning("Failed to initialize agent %s: %s", agent_type, exc)
                return None

        if hasattr(agent, "timeout"):
            agent.timeout = timeout
        if hasattr(agent, "system_prompt") and system_prompt:
            agent.system_prompt = system_prompt
        return agent

    def _select_implementer(self, task: ImplementTask) -> tuple[Any, str]:
        task_type = str(getattr(task, "task_type", "") or "").lower()
        if self._task_type_router and task_type in self._task_type_router:
            agent_type = self._task_type_router[task_type]
            agent = self._get_dynamic_agent(
                agent_type,
                role="implementer",
                timeout=self.claude_timeout,
                system_prompt="""You are implementing code changes in a repository.
Be precise, follow existing patterns, and make only necessary changes.
Include proper type hints and docstrings.""",
            )
            if agent is not None:
                return agent, agent_type

        capabilities = getattr(task, "capabilities", None)
        if capabilities and self._capability_router:
            if isinstance(capabilities, str):
                capabilities = [capabilities]
            for capability in capabilities:
                cap_key = str(capability).lower()
                if cap_key in self._capability_router:
                    agent_type = self._capability_router[cap_key]
                    agent = self._get_dynamic_agent(
                        agent_type,
                        role="implementer",
                        timeout=self.claude_timeout,
                        system_prompt="""You are implementing code changes in a repository.
Be precise, follow existing patterns, and make only necessary changes.
Include proper type hints and docstrings.""",
                    )
                    if agent is not None:
                        return agent, agent_type

        complexity_key = str(getattr(task, "complexity", "moderate")).lower()
        if self._complexity_router and complexity_key in self._complexity_router:
            agent_type = self._complexity_router[complexity_key]
            agent = self._get_dynamic_agent(
                agent_type,
                role="implementer",
                timeout=self.claude_timeout,
                system_prompt="""You are implementing code changes in a repository.
Be precise, follow existing patterns, and make only necessary changes.
Include proper type hints and docstrings.""",
            )
            if agent is not None:
                return agent, agent_type

        if self._implementer_pool:
            agent_type = self._implementer_pool[
                self._implementer_index % len(self._implementer_pool)
            ]
            self._implementer_index += 1
            agent = self._get_dynamic_agent(
                agent_type,
                role="implementer",
                timeout=self.claude_timeout,
                system_prompt="""You are implementing code changes in a repository.
Be precise, follow existing patterns, and make only necessary changes.
Include proper type hints and docstrings.""",
            )
            if agent is not None:
                return agent, agent_type

        return self.claude, "claude"

    def _get_critic(self, timeout: int) -> Any | None:
        return self._get_dynamic_agent(
            self._critic_type,
            role="critic",
            timeout=timeout,
            system_prompt="""You are a senior code reviewer.
Focus on correctness, security, and maintainability.
Be constructive but thorough.""",
        )

    def _get_reviser(self, timeout: int) -> Any | None:
        if not self._reviser_type:
            return None
        return self._get_dynamic_agent(
            self._reviser_type,
            role="implementer",
            timeout=timeout,
            system_prompt="""You are revising code based on review feedback.
Make the minimal changes needed to address issues.
Follow existing code style and tests.""",
        )

    def _select_agent(self, task: ImplementTask | str, use_fallback: bool = False):
        """Select an agent based on strategy, routing, and fallback.

        Accepts either an ImplementTask (preferred) or a legacy complexity
        string for backward compatibility with tests and older callers.
        """
        if use_fallback:
            return self.codex, "codex-fallback"

        if isinstance(task, ImplementTask):
            return self._select_implementer(task)

        # Legacy fallback: always use Claude for implementation.
        return self.claude, "claude"

    @staticmethod
    def _parse_review_response(response: str | None) -> tuple[bool | None, list[str], list[str]]:
        if not response:
            return None, [], []

        approved: bool | None = None
        issues: list[str] = []
        suggestions: list[str] = []
        current: str | None = None

        for raw_line in response.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            upper = line.upper()
            if upper.startswith("APPROVED"):
                approved = "YES" in upper
                current = None
                continue
            if upper.startswith("ISSUES"):
                current = "issues"
                tail = line.split(":", 1)[1].strip() if ":" in line else ""
                if tail:
                    issues.append(tail)
                continue
            if upper.startswith("SUGGESTIONS"):
                current = "suggestions"
                tail = line.split(":", 1)[1].strip() if ":" in line else ""
                if tail:
                    suggestions.append(tail)
                continue

            if current == "issues":
                issues.append(line)
            elif current == "suggestions":
                suggestions.append(line)

        if approved is None:
            approved = len(issues) == 0
        return approved, issues, suggestions

    @staticmethod
    def _format_review_feedback(issues: list[str], suggestions: list[str], fallback: str) -> str:
        lines: list[str] = []
        if issues:
            lines.append("Issues to address:")
            for issue in issues:
                cleaned = issue.lstrip("-*• ").strip()
                if cleaned:
                    lines.append(f"- {cleaned}")
        if suggestions:
            lines.append("Suggested improvements:")
            for suggestion in suggestions:
                cleaned = suggestion.lstrip("-*• ").strip()
                if cleaned:
                    lines.append(f"- {cleaned}")
        if lines:
            return "\n".join(lines)
        return fallback

    def _should_review(self) -> bool:
        return "review" in self._strategy or "critic" in self._strategy

    def _get_task_timeout(self, task: ImplementTask) -> int:
        """Calculate timeout based on task complexity and file count.

        Uses COMPLEXITY_TIMEOUT feature flag (default ON).
        When disabled, returns the default claude_timeout.

        Timeout guidelines:
        - simple: 5 min base (single file, <50 lines)
        - moderate: 10 min base (2-3 files, coordination needed)
        - complex: 20 min base (4+ files, architectural changes)
        - +2 min per additional file beyond the first
        - Maximum: 30 min (prevents runaway tasks)
        """
        if not COMPLEXITY_TIMEOUT:
            return self.claude_timeout

        base_timeouts = {"simple": 300, "moderate": 600, "complex": 1200}
        base = base_timeouts.get(task.complexity, 600)

        # Add 2 min per additional file (coordination overhead)
        file_count = len(task.files) if task.files else 1
        file_bonus = max(0, file_count - 1) * 120

        return min(base + file_bonus, 1800)  # Cap at 30 min

    def _read_claude_md_fallback(self) -> str:
        """Read key patterns from CLAUDE.md as cold-start context.

        Extracts the Common Patterns and Architecture sections, capped at 1500 chars.
        """
        claude_md = Path(self.repo_path) / "CLAUDE.md"
        if not claude_md.exists():
            return ""
        try:
            text = claude_md.read_text(encoding="utf-8")
            # Extract useful sections
            sections: list[str] = []
            in_section = False
            for line in text.split("\n"):
                if line.startswith("## Common Patterns") or line.startswith("## Architecture"):
                    in_section = True
                    sections.append(line)
                elif line.startswith("## ") and in_section:
                    in_section = False
                elif in_section:
                    sections.append(line)
            result = "\n".join(sections).strip()
            return result[:1500] if result else ""
        except OSError:
            return ""

    async def _fetch_memory_context(self, description: str) -> str:
        """Fetch relevant historical context from the unified memory gateway.

        Falls back to CLAUDE.md key patterns when gateway is unavailable or empty.
        """
        gateway_result = None

        if self._memory_gateway is not None:
            try:
                from aragora.memory.gateway import UnifiedMemoryQuery

                response = await asyncio.wait_for(
                    self._memory_gateway.query(
                        UnifiedMemoryQuery(query=description, limit=5, min_confidence=0.3)
                    ),
                    timeout=10.0,
                )
                if response.results:
                    lines = []
                    for r in response.results:
                        source = getattr(r, "source", "unknown")
                        confidence = getattr(r, "confidence", 0.0)
                        content = getattr(r, "content", str(r))
                        lines.append(f"[{source}, {confidence:.0%}] {content}")
                    gateway_result = "\n".join(lines)
            except (
                ImportError,
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
                AttributeError,
                KeyError,
            ) as exc:
                logger.debug("Memory context fetch failed: %s", exc)

        if gateway_result:
            return gateway_result

        # Cold-start fallback: read key patterns from CLAUDE.md
        fallback = self._read_claude_md_fallback()
        if fallback:
            return f"[CLAUDE.md patterns]\n{fallback}"

        return "(No historical context available)"

    def _build_prompt(
        self, task: ImplementTask, feedback: str | None = None, memory_context: str = ""
    ) -> str:
        """Build the implementation prompt for a task."""
        files_str = (
            "\n".join(f"- {f}" for f in task.files)
            if task.files
            else "- (determine from description)"
        )

        prompt = TASK_PROMPT_TEMPLATE.format(
            description=task.description,
            files=files_str,
            repo_path=str(self.repo_path),
            memory_context=memory_context or "(No historical context available)",
        )

        if feedback:
            prompt += "\n\n## Review Feedback\n"
            prompt += feedback.strip() + "\n"

        return prompt

    def _get_git_diff(
        self,
        *,
        stat_only: bool = True,
        max_chars: int | None = None,
        files: list[str] | None = None,
    ) -> str:
        """Get the current git diff.

        Args:
            stat_only: If True, return --stat output (compact). If False, return full diff.
            max_chars: Optional truncation limit for large diffs.
            files: Optional list of file paths to scope the diff.
        """
        try:
            args = ["git", "diff"]
            if stat_only:
                args.append("--stat")
            if files:
                scoped_files = [f for f in files if f]
                if scoped_files:
                    args.append("--")
                    args.extend(scoped_files)
            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                args,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=180,  # Minimum 3 min (was 30)
                shell=False,
            )
            diff = result.stdout
            if max_chars and len(diff) > max_chars:
                diff = diff[:max_chars].rstrip() + "\n...diff truncated...\n"
            return diff
        except subprocess.TimeoutExpired:
            logger.warning("Git diff timed out after 3 minutes")
            return ""
        except (subprocess.SubprocessError, OSError) as e:
            logger.debug("Git diff failed: %s", e)
            return ""

    def get_review_diff(self, max_chars: int | None = None) -> str:
        """Get a full git diff for review purposes."""
        return self._get_git_diff(stat_only=False, max_chars=max_chars)

    async def _run_review(self, task: ImplementTask, diff: str) -> dict[str, Any]:
        """Run a critic review for an implementation diff."""
        if not diff.strip():
            return {"approved": True, "issues": [], "suggestions": [], "review": ""}

        critic = self._get_critic(timeout=self.codex_timeout * 2)
        if critic is None:
            return {"approved": True, "issues": [], "suggestions": [], "review": ""}

        files_str = "\n".join(f"- {f}" for f in task.files) if task.files else "- (unknown)"
        review_prompt = TASK_REVIEW_PROMPT_TEMPLATE.format(
            description=task.description,
            files=files_str,
            diff=diff,
        )

        try:
            from aragora.server.stream.arena_hooks import streaming_task_context

            critic_name = getattr(critic, "name", "critic")
            task_id = f"{critic_name}:impl_review"
            with streaming_task_context(task_id):
                response = await critic.generate(review_prompt, context=[])
        except (RuntimeError, OSError, TimeoutError) as exc:
            logger.warning("Review failed: %s", exc)
            return {"approved": None, "issues": [], "suggestions": [], "error": str(exc)}

        approved, issues, suggestions = self._parse_review_response(response)
        return {
            "approved": approved,
            "issues": issues,
            "suggestions": suggestions,
            "review": response,
            "model": getattr(critic, "name", None),
        }

    async def _execute_via_harness(self, task: ImplementTask) -> TaskResult:
        """Delegate task execution to ClaudeCodeHarness.

        Uses the harness in implementation mode (not analysis mode) so that
        Claude Code can actually edit files. The harness runs without --print,
        allowing file modifications that show up in git diff.
        """
        from aragora.harnesses.claude_code import ClaudeCodeConfig, ClaudeCodeHarness
        from aragora.pipeline.execution_mode import ExecutionMode

        timeout = self._get_task_timeout(task)
        config = ClaudeCodeConfig(
            timeout_seconds=timeout,
            execution_mode=ExecutionMode.AUTONOMOUS,
        )
        harness = ClaudeCodeHarness(config=config)

        memory_context = await self._fetch_memory_context(task.description)
        prompt = self._build_prompt(task, memory_context=memory_context)

        logger.info(
            "  Executing [%s] %s via harness implementation mode (timeout %ss)...",
            task.complexity,
            task.id,
            timeout,
        )

        start_time = time.time()
        try:
            await harness.initialize()
            stdout, stderr = await harness.execute_implementation(
                repo_path=self.repo_path,
                prompt=prompt,
            )
            diff = self._get_git_diff(files=task.files)
            duration = time.time() - start_time

            if diff:
                logger.info("    Harness produced changes (%s chars diff)", len(diff))
            else:
                logger.info("    Harness completed but no file changes detected")

            return TaskResult(
                task_id=task.id,
                success=bool(diff),
                diff=diff,
                model_used="harness:claude-code",
                duration_seconds=duration,
            )
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            logger.error("    Harness error: %s", e)
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Harness error: {e}",
                model_used="harness:claude-code",
                duration_seconds=0.0,
            )

    async def execute_task(
        self,
        task: ImplementTask,
        attempt: int = 1,
        use_fallback: bool = False,
        feedback: str | None = None,
        agent_override: Any | None = None,
        model_label: str | None = None,
    ) -> TaskResult:
        """
        Execute a single implementation task with retry and fallback support.

        Args:
            task: The task to execute
            attempt: Current attempt number (1-based)
            use_fallback: If True, use Codex instead of Claude

        Returns:
            TaskResult with success status and diff
        """
        # Delegate to harness when enabled (first attempt, no overrides)
        if self.use_harness and attempt == 1 and agent_override is None and not use_fallback:
            return await self._execute_via_harness(task)

        # Delegate to sandbox when enabled (first attempt, no overrides, harness not active)
        if (
            self.sandbox_mode
            and not self.use_harness
            and attempt == 1
            and agent_override is None
            and not use_fallback
        ):
            memory_context = await self._fetch_memory_context(task.description)
            prompt = self._build_prompt(task, feedback=feedback, memory_context=memory_context)
            timeout = self._get_task_timeout(task)
            return await self._execute_in_sandbox(task, prompt, timeout)

        # Calculate base timeout from task complexity
        base_timeout = self._get_task_timeout(task)

        # Select agent - use fallback (Codex) if primary failed
        if agent_override is not None:
            agent = agent_override
            model_name = model_label or getattr(agent_override, "name", "override")
        else:
            agent, model_name = self._select_agent(task, use_fallback)

        # Scale timeout by attempt number (fallback doubles)
        if hasattr(agent, "timeout"):
            agent.timeout = base_timeout * attempt
            if use_fallback:
                agent.timeout = base_timeout * 2

        if attempt > 1:
            logger.info(
                "  Retry [%s] %s with %s (attempt %s, timeout %ss)...",
                task.complexity,
                task.id,
                model_name,
                attempt,
                getattr(agent, "timeout", base_timeout),
            )
        else:
            logger.info(
                "  Executing [%s] %s with %s (timeout %ss)...",
                task.complexity,
                task.id,
                model_name,
                getattr(agent, "timeout", base_timeout),
            )

        memory_context = await self._fetch_memory_context(task.description)
        prompt = self._build_prompt(task, feedback=feedback, memory_context=memory_context)
        start_time = time.time()

        try:
            from aragora.server.stream.arena_hooks import streaming_task_context

            # Execute with the selected agent
            agent_name = getattr(agent, "name", "impl-agent")
            task_id = f"{agent_name}:impl_execute"
            with streaming_task_context(task_id):
                await agent.generate(prompt, context=[])

            # Get the diff to see what changed
            diff = self._get_git_diff(files=task.files)
            duration = time.time() - start_time

            logger.info("    Completed in %.1fs", duration)
            if diff:
                logger.debug("    Changes:\n%s...", diff[:200])

            return TaskResult(
                task_id=task.id,
                success=True,
                diff=diff,
                model_used=model_name,
                duration_seconds=duration,
            )

        except TimeoutError as e:
            duration = time.time() - start_time
            logger.warning("    Timeout after %.1fs", duration)
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Timeout: {e}",
                model_used=model_name,
                duration_seconds=duration,
            )

        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            duration = time.time() - start_time
            logger.error("    Error: %s", e)
            return TaskResult(
                task_id=task.id,
                success=False,
                error=str(e),
                model_used=model_name,
                duration_seconds=duration,
            )

    async def execute_task_with_retry(self, task: ImplementTask) -> TaskResult:
        """
        Execute a task with automatic retry and model fallback.

        Retry strategy:
        1. First attempt with Claude (primary)
        2. If retryable error, retry with error analysis hint
        3. If timeout, try Codex as fallback with 2x timeout

        Returns:
            Best TaskResult from attempts
        """
        # Attempt 1: primary agent with normal timeout
        result = await self.execute_task(task, attempt=1, use_fallback=False)
        if result.success:
            if self._should_review():
                return await self._review_and_revise(task, result)
            return result

        # Analyze the failure for structured retry enrichment
        from aragora.implement.error_analyzer import ErrorAnalyzer

        analyzer = ErrorAnalyzer()
        analysis = analyzer.analyze(result.error or "", getattr(result, "stderr", ""))

        # Non-retryable errors: return immediately
        if not analysis.retryable:
            return result

        is_timeout = analysis.category == "timeout"
        retry_hint = analyzer.build_retry_hint(analysis, task.description)

        if self.max_retries >= 2:
            # Attempt 2: retry with error context injected as feedback
            logger.info("    Retrying %s (%s error)...", task.id, analysis.category)
            result = await self.execute_task(
                task,
                attempt=2,
                use_fallback=False,
                feedback=retry_hint,
            )
            if result.success:
                if self._should_review():
                    return await self._review_and_revise(task, result)
                return result

        if is_timeout and self.max_retries >= 3:
            # Attempt 3: Fallback to Codex on timeout
            logger.info("    Falling back to Codex for %s...", task.id)
            result = await self.execute_task(task, attempt=3, use_fallback=True)

        if result.success and self._should_review():
            return await self._review_and_revise(task, result)

        return result

    async def _review_and_revise(self, task: ImplementTask, result: TaskResult) -> TaskResult:
        """Run review loop and optional revisions based on configured strategy."""
        full_diff = self._get_git_diff(stat_only=False, max_chars=20000, files=task.files)
        review = await self._run_review(task, full_diff)
        approved = review.get("approved")
        issues = review.get("issues") or []
        suggestions = review.get("suggestions") or []

        if approved is True:
            return result

        if not self._reviser_type or self._max_revisions <= 0:
            if self._review_strict:
                return TaskResult(
                    task_id=result.task_id,
                    success=False,
                    diff=result.diff,
                    error="Review failed",
                    model_used=result.model_used,
                    duration_seconds=result.duration_seconds,
                )
            return result

        feedback = self._format_review_feedback(
            issues,
            suggestions,
            review.get("review") or "Review requested changes.",
        )

        for revision_idx in range(self._max_revisions):
            reviser = self._get_reviser(timeout=self.claude_timeout)
            if reviser is None:
                break
            logger.info(
                "  Revising %s based on review feedback (%d/%d)...",
                task.id,
                revision_idx + 1,
                self._max_revisions,
            )
            result = await self.execute_task(
                task,
                attempt=1,
                use_fallback=False,
                feedback=feedback,
                agent_override=reviser,
                model_label=f"{self._reviser_type}-reviser",
            )
            if not result.success:
                return result

            full_diff = self._get_git_diff(stat_only=False, max_chars=20000, files=task.files)
            review = await self._run_review(task, full_diff)
            approved = review.get("approved")
            issues = review.get("issues") or []
            suggestions = review.get("suggestions") or []
            if approved is True:
                return result
            feedback = self._format_review_feedback(
                issues,
                suggestions,
                review.get("review") or feedback,
            )

        if self._review_strict:
            return TaskResult(
                task_id=result.task_id,
                success=False,
                diff=result.diff,
                error="Review failed after revisions",
                model_used=result.model_used,
                duration_seconds=result.duration_seconds,
            )

        return result

    async def execute_plan(
        self,
        tasks: list[ImplementTask],
        completed: set[str],
        on_task_complete=None,
        stop_on_failure: bool = False,
    ) -> list[TaskResult]:
        """
        Execute all tasks in a plan, respecting dependencies.

        Updated Jan 2026: Now continues after failures by default and retries.

        Args:
            tasks: List of tasks to execute
            completed: Set of already-completed task IDs
            on_task_complete: Optional callback after each task
            stop_on_failure: If True, stop on first failure (legacy behavior)

        Returns:
            List of TaskResults for executed tasks
        """
        results = []
        failed_tasks = []

        # First pass: execute all tasks, collecting failures
        for task in tasks:
            # Skip already completed
            if task.id in completed:
                continue

            # Check dependencies
            deps_met = all(dep in completed for dep in task.dependencies)
            if not deps_met:
                logger.info("  Skipping %s - dependencies not met", task.id)
                continue

            # Execute with retry
            result = await self.execute_task_with_retry(task)
            results.append(result)

            if result.success:
                completed.add(task.id)
                if on_task_complete:
                    on_task_complete(task.id, result)
            else:
                failed_tasks.append(task)
                if stop_on_failure:
                    logger.warning("  Stopping execution due to failure in %s", task.id)
                    break
                else:
                    logger.warning("  Task %s failed, continuing with remaining tasks...", task.id)

        # Second pass: retry failed tasks once more (dependencies may now be met)
        if failed_tasks and not stop_on_failure:
            logger.info("Retrying %s failed tasks...", len(failed_tasks))
            for task in failed_tasks:
                # Check if dependencies are now met
                deps_met = all(dep in completed for dep in task.dependencies)
                if not deps_met:
                    logger.info("  Skipping retry of %s - dependencies still not met", task.id)
                    continue

                # Already tried with retry, try one more time with max timeout
                logger.info("  Final retry for %s...", task.id)
                result = await self.execute_task(
                    task, attempt=self.max_retries + 1, use_fallback=True
                )

                # Update results (replace the failed one)
                for i, r in enumerate(results):
                    if r.task_id == task.id:
                        results[i] = result
                        break

                if result.success:
                    completed.add(task.id)
                    if on_task_complete:
                        on_task_complete(task.id, result)

        return results

    @staticmethod
    def _task_priority(task: ImplementTask) -> tuple[int, int]:
        order = {"complex": 0, "moderate": 1, "simple": 2}
        complexity_rank = order.get(task.complexity, 1)
        file_count = len(task.files) if task.files else 0
        return complexity_rank, -file_count

    def _select_parallel_batch(
        self, ready: list[ImplementTask], max_parallel: int
    ) -> list[ImplementTask]:
        if not ready:
            return []

        sorted_ready = sorted(ready, key=self._task_priority)
        batch: list[ImplementTask] = []
        used_files: set[str] = set()
        has_unknown = False

        for task in sorted_ready:
            task_files = [f for f in (task.files or []) if f]
            if not task_files:
                if batch:
                    continue
                batch.append(task)
                has_unknown = True
                break

            if has_unknown:
                continue

            task_file_set = set(task_files)
            if task_file_set & used_files:
                continue

            batch.append(task)
            used_files.update(task_file_set)
            if len(batch) >= max_parallel:
                break

        if not batch:
            batch = [sorted_ready[0]]

        return batch

    async def execute_plan_parallel(
        self,
        tasks: list[ImplementTask],
        completed: set[str],
        max_parallel: int | None = None,
        on_task_complete=None,
    ) -> list[TaskResult]:
        """
        Execute tasks with parallelism for independent tasks.

        Uses PARALLEL_TASKS feature flag (default OFF).
        When disabled, falls back to sequential execute_plan().

        Groups tasks by dependency level and executes each level
        in parallel (up to max_parallel concurrent tasks).

        Args:
            tasks: List of tasks to execute
            completed: Set of already-completed task IDs
            max_parallel: Max concurrent tasks (default from MAX_PARALLEL env)
            on_task_complete: Optional callback after each task

        Returns:
            List of TaskResults for executed tasks
        """
        if not PARALLEL_TASKS:
            return await self.execute_plan(tasks, completed, on_task_complete)

        max_parallel = max_parallel or MAX_PARALLEL
        results: list[TaskResult] = []
        remaining = [t for t in tasks if t.id not in completed]

        logger.info("  Executing %s tasks (max %s parallel)...", len(remaining), max_parallel)

        while remaining:
            # Find tasks with all dependencies met
            ready = [t for t in remaining if all(dep in completed for dep in t.dependencies)]

            if not ready:
                # Deadlock - remaining tasks have unmet dependencies
                unmet = remaining[0]
                missing = [d for d in unmet.dependencies if d not in completed]
                logger.error("  Deadlock: %s waiting for %s", unmet.id, missing)
                break

            # Execute up to max_parallel tasks concurrently
            batch = self._select_parallel_batch(ready, max_parallel)
            logger.info("    Parallel batch: %s", [t.id for t in batch])

            batch_results = await asyncio.gather(
                *[self.execute_task_with_retry(t) for t in batch], return_exceptions=True
            )

            for task, raw_result in zip(batch, batch_results):
                # Handle exceptions from gather - normalize to TaskResult
                if isinstance(raw_result, BaseException):
                    task_result = TaskResult(
                        task_id=task.id,
                        success=False,
                        error=str(raw_result),
                        model_used="unknown",
                        duration_seconds=0,
                    )
                else:
                    task_result = raw_result

                results.append(task_result)
                remaining.remove(task)

                if task_result.success:
                    completed.add(task.id)

                if on_task_complete:
                    on_task_complete(task.id, task_result)

        return results

    def _get_sandbox_docker_args(self) -> list[str]:
        """Build Docker run arguments for sandbox-mode execution.

        Mounts the repo_path as the workspace (RW) inside the container.
        Uses the configured sandbox image and memory limit.
        """
        from aragora.sandbox.executor import build_worktree_docker_args

        return build_worktree_docker_args(
            worktree_path=self.repo_path,
            repo_root=None,
            image=self.sandbox_image,
            memory_mb=self.sandbox_memory_mb,
            network=True,  # Agents need network to call LLM APIs
        )

    async def _execute_in_sandbox(
        self,
        task: ImplementTask,
        prompt: str,
        timeout: int,
    ) -> TaskResult:
        """Execute an implementation task inside a Docker sandbox.

        The agent CLI (e.g. ``claude``) runs inside the container with the
        worktree mounted read-write.  This prevents accidental writes to
        files outside the designated working directory.
        """
        docker_args = self._get_sandbox_docker_args()
        cmd = ["docker", "run", *docker_args, "bash", "-c", f"echo {repr(prompt)} | claude --print"]

        logger.info(
            "  Executing [%s] %s in sandbox (timeout %ds)...",
            task.complexity,
            task.id,
            timeout,
        )

        start_time = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            duration = time.time() - start_time

            diff = self._get_git_diff(files=task.files)
            success = proc.returncode == 0
            return TaskResult(
                task_id=task.id,
                success=success,
                diff=diff,
                model_used="sandbox:claude",
                duration_seconds=duration,
                error=stderr.decode()[:500] if not success and stderr else None,
            )
        except asyncio.TimeoutError:
            # Kill the orphaned subprocess to prevent zombies
            proc.kill()
            await proc.wait()
            duration = time.time() - start_time
            return TaskResult(
                task_id=task.id,
                success=False,
                error=f"Sandbox timeout after {duration:.0f}s",
                model_used="sandbox:claude",
                duration_seconds=duration,
            )
        except FileNotFoundError:
            return TaskResult(
                task_id=task.id,
                success=False,
                error="Docker not found. Install Docker or disable sandbox_mode.",
                model_used="sandbox:claude",
                duration_seconds=0.0,
            )

    async def review_with_codex(
        self, diff: str, timeout: int = 2400
    ) -> dict:  # 40 min - Codex is slow but thorough
        """
        Run Codex code review on implemented changes.

        Codex is slow (~5-20min) but produces high-quality review.
        Use this as a QA step after Claude implementation.

        Args:
            diff: The git diff to review
            timeout: Max time to wait (default 10 min)

        Returns:
            dict with 'approved', 'issues', and 'suggestions'
        """
        if not diff.strip():
            return {"approved": True, "issues": [], "suggestions": []}

        review_prompt = f"""Review this code change for quality and safety issues.

## Git Diff
```
{diff}
```

## Review Checklist
1. Are there any bugs or logic errors?
2. Are there security vulnerabilities (injection, XSS, etc.)?
3. Does the code follow consistent style?
4. Are there missing error handlers or edge cases?
5. Is there unnecessary complexity that could be simplified?

## Response Format
Provide your review as:
- APPROVED: yes/no
- ISSUES: List any problems that MUST be fixed
- SUGGESTIONS: List any improvements that would be nice

Be concise and actionable."""

        logger.info("  Running Codex code review (this may take several minutes)...")
        start_time = time.time()

        try:
            # Use codex with extended timeout for review
            self._codex = CodexAgent(
                name="codex-reviewer",
                model="o3",
                role="critic",
                timeout=timeout,
            )
            self._codex.system_prompt = """You are a senior code reviewer.
Focus on correctness, security, and maintainability.
Be constructive but thorough."""

            from aragora.server.stream.arena_hooks import streaming_task_context

            codex_name = getattr(self._codex, "name", "codex")
            task_id = f"{codex_name}:impl_review"
            with streaming_task_context(task_id):
                response = await self._codex.generate(review_prompt, context=[])
            duration = time.time() - start_time

            logger.info("    Review completed in %.1fs", duration)

            # Parse response (basic parsing)
            response_lower = response.lower() if response else ""
            approved = "approved: yes" in response_lower or "approved:yes" in response_lower

            return {
                "approved": approved,
                "review": response,
                "duration_seconds": duration,
                "model": "codex-o3",
            }

        except (RuntimeError, OSError, TimeoutError) as e:
            duration = time.time() - start_time
            logger.error("    Review failed after %.1fs: %s", duration, e)
            return {
                "approved": None,
                "error": "Review execution failed",
                "duration_seconds": duration,
            }
