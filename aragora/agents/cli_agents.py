"""
CLI-based agent implementations that wrap external AI tools.

These agents invoke CLI tools (codex, claude, openai) as subprocesses,
enabling heterogeneous multi-model debates.

Supports automatic fallback to OpenRouter API when CLI commands fail due to
rate limits, timeouts, or other errors. Enable fallback by setting
ARAGORA_OPENROUTER_FALLBACK_ENABLED=true and providing OPENROUTER_API_KEY.

Note: Fallback is opt-in by default to prevent silent billing on OpenRouter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import threading
import time
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.agents.base import MAX_CONTEXT_CHARS, MAX_MESSAGE_CHARS, CritiqueMixin
from aragora.agents.errors import (
    RATE_LIMIT_PATTERNS,
    AgentStreamError,
    AgentCircuitOpenError,
    CLISubprocessError,
    ErrorClassifier,
)
from aragora.agents.registry import AgentRegistry
from aragora.core import Agent, Critique, Message
from aragora.core_types import AgentRole
from aragora.resilience import BaseCircuitBreaker, get_v2_circuit_breaker as get_circuit_breaker

if TYPE_CHECKING:
    from aragora.agents.api_agents import OpenRouterAgent

# Module-level semaphore to limit concurrent CLI subprocesses
# Prevents OS resource exhaustion when running many agents in parallel
# Configurable via ARAGORA_MAX_CLI_SUBPROCESSES environment variable
_MAX_CLI_SUBPROCESSES = int(os.environ.get("ARAGORA_MAX_CLI_SUBPROCESSES", "10"))
_subprocess_semaphore = asyncio.Semaphore(_MAX_CLI_SUBPROCESSES)

# Track active CLI subprocess PIDs so timeout handlers can perform best-effort cleanup.
_tracked_cli_pids: set[int] = set()
_tracked_cli_pids_lock = threading.Lock()

# Maximum prompt size to pass as CLI argument (avoids E2BIG error)
# Prompts larger than this should be passed via stdin where supported
# Configurable via ARAGORA_MAX_CLI_PROMPT_CHARS environment variable
MAX_CLI_PROMPT_CHARS = int(
    os.environ.get("ARAGORA_MAX_CLI_PROMPT_CHARS", "100000")
)  # 100KB default

# Retry OpenRouter fallback generation for transient transport failures.
FALLBACK_GENERATE_RETRY_ATTEMPTS = max(
    1, int(os.environ.get("ARAGORA_FALLBACK_GENERATE_RETRY_ATTEMPTS", "2"))
)
FALLBACK_GENERATE_RETRY_DELAY_SECONDS = float(
    os.environ.get("ARAGORA_FALLBACK_GENERATE_RETRY_DELAY_SECONDS", "0.75")
)

# Re-export constants for backward compatibility
__all__ = [
    "CLIAgent",
    "CodexAgent",
    "ClaudeAgent",
    "OpenAIAgent",
    "GeminiCLIAgent",
    "GrokCLIAgent",
    "QwenCLIAgent",
    "DeepseekCLIAgent",
    "KiloCodeAgent",
    "terminate_tracked_cli_processes",
    "MAX_CLI_PROMPT_CHARS",
    "MAX_CONTEXT_CHARS",
    "MAX_MESSAGE_CHARS",
    "RATE_LIMIT_PATTERNS",  # Re-exported from errors.py
    "get_default_agents",
]

logger = logging.getLogger(__name__)


def _track_cli_pid(pid: int | None) -> None:
    if not isinstance(pid, int) or pid <= 0:
        return
    with _tracked_cli_pids_lock:
        _tracked_cli_pids.add(pid)


def _untrack_cli_pid(pid: int | None) -> None:
    if not isinstance(pid, int) or pid <= 0:
        return
    with _tracked_cli_pids_lock:
        _tracked_cli_pids.discard(pid)


def terminate_tracked_cli_processes(grace_seconds: float = 0.2) -> dict[str, int]:
    """Best-effort cleanup of tracked CLI subprocesses.

    This is intentionally synchronous so timeout handlers can call it from
    non-async contexts (for example strict wall-clock signal paths).
    """
    with _tracked_cli_pids_lock:
        tracked = list(_tracked_cli_pids)

    if not tracked:
        return {"tracked": 0, "terminated": 0, "killed": 0, "remaining": 0}

    terminated = 0
    killed = 0
    remaining_pids: set[int] = set()
    unknown_state_pids: set[int] = set()

    # First attempt a graceful terminate.
    for pid in tracked:
        try:
            os.kill(pid, signal.SIGTERM)
            terminated += 1
        except ProcessLookupError:
            _untrack_cli_pid(pid)
            continue
        except (PermissionError, OSError):
            unknown_state_pids.add(pid)

    # Allow a brief grace period for process exit.
    if grace_seconds > 0:
        time.sleep(min(grace_seconds, 1.0))

    # Force-kill any process still alive (or whose state is unknown).
    for pid in tracked:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            _untrack_cli_pid(pid)
            continue
        except (PermissionError, OSError):
            # Cannot verify state; keep as remaining and do not attempt further signals.
            unknown_state_pids.add(pid)
            continue

        try:
            os.kill(pid, signal.SIGKILL)
            killed += 1
        except ProcessLookupError:
            _untrack_cli_pid(pid)
            continue
        except (PermissionError, OSError):
            unknown_state_pids.add(pid)
            continue

        # After SIGKILL, check if process is gone and clear tracking.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            _untrack_cli_pid(pid)
        except (PermissionError, OSError):
            unknown_state_pids.add(pid)
        else:
            remaining_pids.add(pid)

    # Final pass: capture any remaining live tracked PIDs.
    for pid in tracked:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            _untrack_cli_pid(pid)
            continue
        except (PermissionError, OSError):
            unknown_state_pids.add(pid)
            continue
        else:
            remaining_pids.add(pid)

    with _tracked_cli_pids_lock:
        current_remaining = len(_tracked_cli_pids)
    remaining = max(current_remaining, len(remaining_pids) + len(unknown_state_pids))

    return {
        "tracked": len(tracked),
        "terminated": terminated,
        "killed": killed,
        "remaining": remaining,
    }


class CLIAgent(CritiqueMixin, Agent):
    """Base class for CLI-based agents.

    Supports automatic fallback to OpenRouter API when CLI commands fail.
    Enable with ARAGORA_OPENROUTER_FALLBACK_ENABLED=true and OPENROUTER_API_KEY env var.
    """

    # Map CLI agent models to OpenRouter model identifiers
    OPENROUTER_MODEL_MAP: dict[str, str] = {
        # Claude models
        "claude": "anthropic/claude-sonnet-4.6",  # Default claude CLI
        "claude-opus-4-6": "anthropic/claude-opus-4.6",
        "claude-sonnet-4-6": "anthropic/claude-sonnet-4.6",
        "claude-opus-4-5-20251101": "anthropic/claude-opus-4.5",
        "claude-sonnet-4-20250514": "anthropic/claude-sonnet-4",
        "claude-3-opus-20240229": "anthropic/claude-3-opus",
        "claude-3-sonnet-20240229": "anthropic/claude-3-sonnet",
        # OpenAI/Codex models
        "gpt-5.4": "openai/gpt-5.4",
        "gpt-5.3": "openai/gpt-5.3-chat",
        "gpt-5.3-codex": "openai/gpt-5.3-codex",
        "gpt-5.3-chat-latest": "openai/gpt-5.3-chat",
        "gpt-4.1-codex": "openai/gpt-4.1",
        "gpt-4.1": "openai/gpt-4.1",
        "gpt-4.1-mini": "openai/gpt-4.1-mini",
        "gpt-4o": "openai/gpt-4o",
        "gpt-4-turbo": "openai/gpt-4-turbo",
        "gpt-4": "openai/gpt-4",
        # Gemini models
        "gemini-3.1-pro-preview": "google/gemini-3.1-pro-preview",
        "gemini-3.1-pro": "google/gemini-3.1-pro-preview",
        "gemini-3-pro-preview": "google/gemini-3.1-pro-preview",
        "gemini-3-pro": "google/gemini-3.1-pro-preview",
        "gemini-3-flash-preview": "google/gemini-3-flash-preview",
        "gemini-3-flash": "google/gemini-3-flash-preview",
        "gemini-2.0-flash": "google/gemini-2.0-flash-001",
        "gemini-1.5-pro": "google/gemini-pro-1.5",
        # Grok models
        "grok-4-1-fast": "x-ai/grok-4.1-fast",
        "grok-4-latest": "x-ai/grok-4",
        "grok-4": "x-ai/grok-4",
        "grok-3": "x-ai/grok-4",
        "grok-2": "x-ai/grok-4",
        # Deepseek models
        "deepseek-coder": "deepseek/deepseek-chat",
        "deepseek-v3": "deepseek/deepseek-chat",
        "deepseek-v3.2": "deepseek/deepseek-v3.2",
        # Qwen models
        "qwen-2.5-coder": "qwen/qwen-2.5-coder-32b-instruct",
        "qwen3-coder": "qwen/qwen3-coder-next",
        "qwen3-max": "qwen/qwen3-max",
        # Mistral models
        "mistral-large-2512": "mistralai/mistral-large-2512",
    }

    def __init__(
        self,
        name: str,
        model: str,
        role: AgentRole = "proposer",
        timeout: int = 300,  # Increased default for complex operations
        enable_fallback: bool | None = None,  # None = use config setting
        circuit_breaker: BaseCircuitBreaker | None = None,
        enable_circuit_breaker: bool = True,
        prefer_api: bool = False,  # Skip CLI, use OpenRouter directly
    ):
        super().__init__(name, model, role)
        self.timeout = timeout
        # Use config setting if not explicitly provided
        if enable_fallback is None:
            from aragora.agents.fallback import get_default_fallback_enabled

            self.enable_fallback = get_default_fallback_enabled()
        else:
            self.enable_fallback = enable_fallback
        self.prefer_api = prefer_api
        self._fallback_agent: OpenRouterAgent | None = None
        self._fallback_used = False  # Track if fallback was triggered this session
        self.enable_circuit_breaker = enable_circuit_breaker

        # Use provided circuit breaker, global registry, or disable
        # Global registry ensures consistent state across agent instances
        if circuit_breaker is not None:
            self._circuit_breaker = circuit_breaker
        elif enable_circuit_breaker:
            # Use global registry with agent name for shared state
            self._circuit_breaker = get_circuit_breaker(
                f"cli_{name}",
                failure_threshold=15,  # High threshold for CLI flakiness
                cooldown_seconds=120.0,  # Longer cooldown for active debates
            )
        else:
            self._circuit_breaker = None

    @property
    def circuit_breaker(self) -> BaseCircuitBreaker | None:
        """Get the circuit breaker for this agent."""
        return self._circuit_breaker

    def is_circuit_open(self) -> bool:
        """Check if the circuit breaker is open (blocking requests)."""
        if self._circuit_breaker is None:
            return False
        return not self._circuit_breaker.can_execute()

    def _get_fallback_agent(self) -> OpenRouterAgent | None:
        """Get or create the OpenRouter fallback agent.

        Returns None if fallback is disabled or OPENROUTER_API_KEY is not set.
        """
        if not self.enable_fallback:
            return None

        if self._fallback_agent is None:
            api_key = os.environ.get("OPENROUTER_API_KEY")
            if not api_key:
                logger.warning(
                    "[%s] No OPENROUTER_API_KEY set, fallback disabled - rate limit errors will not have a fallback",
                    self.name,
                )
                return None

            # Import here to avoid circular dependency
            from aragora.agents.api_agents import OpenRouterAgent

            # Map the model to OpenRouter format
            openrouter_model = self.OPENROUTER_MODEL_MAP.get(self.model)
            if not openrouter_model:
                # If already in provider/model form, normalize for OpenRouter
                if "/" in self.model:
                    if self.model.startswith("openrouter/"):
                        openrouter_model = self.model.split("/", 1)[1]
                    else:
                        openrouter_model = self.model
                else:
                    openrouter_model = "anthropic/claude-sonnet-4.6"  # Default fallback model

            self._fallback_agent = OpenRouterAgent(
                name=f"{self.name}_fallback",
                model=openrouter_model,
                role=self.role,
                timeout=self.timeout,
            )
            # Copy system prompt if set
            if self.system_prompt:
                self._fallback_agent.system_prompt = self.system_prompt
            logger.info(
                "[%s] Created OpenRouter fallback agent with model %s", self.name, openrouter_model
            )

        return self._fallback_agent

    def _is_fallback_error(self, error: Exception) -> bool:
        """Check if the error should trigger a fallback to OpenRouter.

        Uses centralized ErrorClassifier for consistent error classification
        across all agent types. Detects rate limits, timeouts, CLI-specific
        errors, and network issues.

        This method is intentionally permissive to maximize fallback opportunities.
        """
        should_fallback, category = ErrorClassifier.classify_error(error)
        if should_fallback:
            logger.debug(
                "[%s] Detected fallback error (%s): %s", self.name, category, str(error)[:100]
            )
        return should_fallback

    def _sanitize_cli_arg(self, arg: str) -> str:
        """Sanitize a string for use as a CLI argument.

        Removes null bytes and other control characters that can cause
        'embedded null byte' ValueError from subprocess calls.
        Command-line arguments are null-terminated in C, so null bytes
        in arguments are not allowed by the OS.
        """
        if not isinstance(arg, str):
            return str(arg)
        # Remove null bytes (cause 'embedded null byte' error)
        sanitized = arg.replace("\x00", "")
        # Remove other problematic control characters (except newlines/tabs)
        sanitized = re.sub(r"[\x01-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", sanitized)
        return sanitized

    async def _run_cli(self, command: list[str], input_text: str | None = None) -> str:
        """Run a CLI command and return output.

        Integrates with circuit breaker to prevent cascading failures.
        Uses a module-level semaphore to limit concurrent subprocesses.
        """
        # Check circuit breaker before attempting the call
        if self._circuit_breaker is not None and not self._circuit_breaker.can_proceed():
            raise AgentCircuitOpenError(
                "Circuit breaker is open for CLI agent",
                agent_name=self.name,
                cooldown_seconds=self._circuit_breaker.cooldown_seconds,
            )

        # Sanitize all command arguments to prevent 'embedded null byte' errors
        sanitized_command = [self._sanitize_cli_arg(arg) for arg in command]
        proc = None

        # Use semaphore to limit concurrent subprocesses (prevents resource exhaustion)
        async with _subprocess_semaphore:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *sanitized_command,
                    stdin=asyncio.subprocess.PIPE if input_text else None,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _track_cli_pid(getattr(proc, "pid", None))

                # Also sanitize stdin input (used by ClaudeAgent)
                sanitized_input = self._sanitize_cli_arg(input_text) if input_text else None
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=sanitized_input.encode() if sanitized_input else None),
                    timeout=self.timeout,
                )

                if proc.returncode != 0:
                    # Record failure to circuit breaker
                    if self._circuit_breaker is not None:
                        self._circuit_breaker.record_failure()
                    # Build informative error message with return code
                    stderr_text = stderr.decode("utf-8", errors="replace").strip()
                    error_msg = f"CLI command failed with return code {proc.returncode}"
                    if stderr_text:
                        # For verbose CLIs (like Codex), extract last meaningful line
                        lines = [line.strip() for line in stderr_text.split("\n") if line.strip()]
                        if lines:
                            last_line = lines[-1][:200]
                            error_msg += f": {last_line}"
                    else:
                        error_msg += " (stderr empty)"
                    raise CLISubprocessError(
                        message=error_msg,
                        agent_name=self.name,
                        returncode=proc.returncode,
                        stderr=stderr_text or None,
                    )

                stdout_text = stdout.decode("utf-8", errors="replace").strip()
                stderr_text = stderr.decode("utf-8", errors="replace").strip()

                # Some CLIs (e.g., Kilo) emit errors on stderr but return code 0.
                # Treat "no stdout + non-empty stderr" as a failure to enable fallback.
                if not stdout_text and stderr_text:
                    if self._circuit_breaker is not None:
                        self._circuit_breaker.record_failure()
                    lines = [line.strip() for line in stderr_text.split("\n") if line.strip()]
                    last_line = lines[-1][:200] if lines else "stderr present"
                    raise CLISubprocessError(
                        message=f"CLI command produced no output: {last_line}",
                        agent_name=self.name,
                        returncode=0,
                        stderr=stderr_text or None,
                    )

                # Record success to circuit breaker
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_success()

                return stdout_text

            except asyncio.TimeoutError:
                # Record failure to circuit breaker
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
                if proc:
                    proc.kill()
                    await proc.wait()  # Ensure process is fully cleaned up
                raise TimeoutError(f"CLI command timed out after {self.timeout}s")
            except asyncio.CancelledError:
                # Ensure subprocess cleanup when outer timeout/cancellation interrupts.
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
                if proc and proc.returncode is None:
                    proc.kill()
                    await proc.wait()
                raise
            except AgentCircuitOpenError:
                # Don't record circuit open errors as failures - just re-raise
                raise
            except (OSError, ValueError, RuntimeError, UnicodeDecodeError) as e:
                # Record failure to circuit breaker (subprocess/encoding errors)
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
                if proc and proc.returncode is None:
                    logger.debug("[cleanup] Killing subprocess after error: %s", e)
                    proc.kill()
                    await proc.wait()  # Cleanup zombie processes
                raise
            finally:
                if proc is not None:
                    _untrack_cli_pid(getattr(proc, "pid", None))

    def _build_context_prompt(
        self,
        context: list[Message] | None = None,
        truncate: bool = True,
        sanitize_fn: Callable[[str], str] | None = None,
    ) -> str:
        """Build context from previous messages with truncation for large contexts.

        Delegates to CritiqueMixin with CLI-specific settings.
        """
        # Use CLI sanitization by default if not specified
        if sanitize_fn is None:
            sanitize_fn = self._sanitize_cli_arg
        # Use mixin method with truncation and CLI sanitization
        return CritiqueMixin._build_context_prompt(
            self, context, truncate=truncate, sanitize_fn=sanitize_fn
        )

    # _parse_critique is inherited from CritiqueMixin

    def _build_full_prompt(self, prompt: str, context: list[Message] | None = None) -> str:
        """Build full prompt with context and system prompt.

        Consolidates the repeated pattern across all CLI agents.
        """
        full_prompt = prompt
        if context:
            full_prompt = self._build_context_prompt(context) + prompt
        if self.system_prompt:
            full_prompt = f"System context: {self.system_prompt}\n\n{full_prompt}"
        return full_prompt

    def _is_prompt_too_large_for_argv(self, prompt: str) -> bool:
        """Check if prompt is too large to pass as CLI argument.

        Large prompts can trigger E2BIG (argument list too long) errors.
        Returns True if prompt should be passed via stdin instead.
        """
        return len(prompt) > MAX_CLI_PROMPT_CHARS

    async def _generate_with_fallback(
        self,
        cli_command: list[str],
        prompt: str,
        context: list[Message] | None = None,
        input_text: str | None = None,
        response_extractor: Callable[[str], str] | None = None,
    ) -> str:
        """Execute CLI command with automatic fallback on errors.

        Consolidates the repeated try/except fallback pattern across all CLI agents.

        Args:
            cli_command: CLI command to execute
            prompt: Original prompt (for fallback)
            context: Message context (for fallback)
            input_text: Optional stdin input for CLI
            response_extractor: Optional function to extract response from CLI output

        Returns:
            Generated response string
        """
        # If prefer_api is set, skip CLI entirely and use OpenRouter directly
        if self.prefer_api:
            fallback = self._get_fallback_agent()
            if fallback:
                logger.debug("[%s] prefer_api=True, using OpenRouter directly", self.name)
                self._fallback_used = True
                return await fallback.generate(prompt, context)
            # If no fallback available, fall through to CLI

        try:
            result = await self._run_cli(cli_command, input_text=input_text)
            if response_extractor:
                return response_extractor(result)
            return result

        except (
            OSError,
            RuntimeError,
            ValueError,
            TimeoutError,
            UnicodeDecodeError,
            CLISubprocessError,
            AgentCircuitOpenError,
        ) as e:
            if self._is_fallback_error(e):
                fallback = self._get_fallback_agent()
                if fallback:
                    logger.warning(
                        "[%s] CLI failed (%s: %s), falling back to OpenRouter",
                        self.name,
                        type(e).__name__,
                        str(e)[:100],
                    )
                    self._fallback_used = True
                    for attempt in range(1, FALLBACK_GENERATE_RETRY_ATTEMPTS + 1):
                        try:
                            result = await fallback.generate(prompt, context)
                            # Record success when fallback works - prevents circuit from opening
                            if self._circuit_breaker is not None:
                                self._circuit_breaker.record_success()
                            return result
                        except (
                            AgentStreamError,
                            OSError,
                            RuntimeError,
                            ValueError,
                            TimeoutError,
                        ) as fallback_error:
                            if attempt >= FALLBACK_GENERATE_RETRY_ATTEMPTS:
                                # Fallback also failed - record as failure
                                if self._circuit_breaker is not None:
                                    self._circuit_breaker.record_failure()
                                raise fallback_error

                            logger.warning(
                                "[%s] OpenRouter fallback attempt %d/%d failed (%s), retrying",
                                self.name,
                                attempt,
                                FALLBACK_GENERATE_RETRY_ATTEMPTS,
                                type(fallback_error).__name__,
                            )
                            await asyncio.sleep(FALLBACK_GENERATE_RETRY_DELAY_SECONDS * attempt)
            raise

    def _build_critique_prompt(self, proposal: str, task: str) -> str:
        """Build standard critique prompt.

        Subclasses can override for custom critique prompts.
        """
        return f"""Analyze this proposal critically for the given task.

Task: {task}

Proposal:
{proposal}

Provide structured feedback:
- ISSUES: Specific problems (bullet points)
- SUGGESTIONS: Improvements (bullet points)
- SEVERITY: 0-10 rating (0=trivial, 10=critical)
- REASONING: Brief explanation"""

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        """Critique a proposal using this CLI agent.

        Default implementation uses _build_critique_prompt and generate.
        Subclasses can override for custom critique behavior.

        Args:
            proposal: The proposal content to critique
            task: The debate task/question
            context: Optional conversation context
            target_agent: Name of the agent whose proposal is being critiqued
        """
        critique_prompt = self._build_critique_prompt(proposal, task)
        response = await self.generate(critique_prompt, context)
        # Use target_agent if provided, otherwise fall back to generic "proposal"
        return self._parse_critique(response, target_agent or "proposal", proposal)


@AgentRegistry.register(
    "codex",
    default_model="gpt-5.3-codex",
    agent_type="CLI",
    requires="codex CLI (npm install -g @openai/codex)",
)
class CodexAgent(CLIAgent):
    """Agent that uses OpenAI Codex CLI.

    Falls back to OpenRouter (OpenAI GPT-5.2) on CLI failures if enabled.
    """

    _CODEX_WARNING_PREFIXES: tuple[str, ...] = (
        "`collab` is deprecated.",
        "Enable it with `--enable multi_agent`",
        "See https://github.com/openai/codex/blob/main/docs/config.md#feature-flags",
    )

    def _is_codex_warning_noise(self, line: str) -> bool:
        """Return True for known non-response warning lines from Codex CLI."""
        text = line.strip()
        if not text:
            return False
        return any(text.startswith(prefix) for prefix in self._CODEX_WARNING_PREFIXES)

    def _extract_codex_response(self, result: str) -> str:
        """Extract the actual response from codex output (skip header)."""
        lines = result.split("\n")
        response_lines = []
        in_response = False
        dropped_noise = False
        for line in lines:
            if self._is_codex_warning_noise(line):
                dropped_noise = True
                continue
            if line.strip() == "codex":
                in_response = True
                continue
            if in_response:
                if line.startswith("tokens used"):
                    continue
                response_lines.append(line)
        if response_lines:
            return "\n".join(response_lines).strip()

        filtered = [
            line
            for line in lines
            if not self._is_codex_warning_noise(line) and not line.startswith("tokens used")
        ]
        if filtered and filtered[0].strip() == "codex":
            filtered = filtered[1:]

        cleaned = "\n".join(filtered).strip()
        if dropped_noise and not cleaned:
            raise RuntimeError("cli error: unable to parse response (codex warning-only output)")
        return cleaned if cleaned else result

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response using codex exec.

        For large prompts (>10KB), uses stdin to avoid OS E2BIG error
        (argument list too long).
        """
        full_prompt = self._build_full_prompt(prompt, context)
        # Use stdin for large prompts to avoid E2BIG (arg list too long)
        if self._is_prompt_too_large_for_argv(full_prompt):
            return await self._generate_with_fallback(
                ["codex", "exec", "--skip-git-repo-check", "-"],
                prompt,
                context,
                input_text=full_prompt,
                response_extractor=self._extract_codex_response,
            )
        return await self._generate_with_fallback(
            ["codex", "exec", "--skip-git-repo-check", full_prompt],
            prompt,
            context,
            response_extractor=self._extract_codex_response,
        )

    def _build_critique_prompt(self, proposal: str, task: str) -> str:
        """Build critique prompt with codex-specific formatting."""
        return f"""You are a critical reviewer. Analyze this proposal for the given task.

Task: {task}

Proposal to critique:
{proposal}

Provide a structured critique with:
1. ISSUES: List specific problems, errors, or weaknesses (use bullet points)
2. SUGGESTIONS: List concrete improvements (use bullet points)
3. SEVERITY: Rate 0-10 (0=trivial, 10=critical)
4. REASONING: Brief explanation of your assessment

Be constructive but thorough. Identify both technical and conceptual issues."""


@AgentRegistry.register(
    "claude",
    default_model="claude-opus-4-6",
    agent_type="CLI",
    requires="claude CLI (npm install -g @anthropic-ai/claude-code)",
)
class ClaudeAgent(CLIAgent):
    """Agent that uses Claude CLI (claude-code).

    Falls back to OpenRouter (Anthropic Claude) on CLI failures if enabled.
    """

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response using claude CLI via stdin."""
        full_prompt = self._build_full_prompt(prompt, context)
        # Pass prompt via stdin to avoid shell argument length limits
        return await self._generate_with_fallback(
            ["claude", "--print", "-p", "-"],
            prompt,
            context,
            input_text=full_prompt,
        )


@AgentRegistry.register(
    "gemini-cli",
    default_model="gemini-3.1-pro-preview",
    agent_type="CLI",
    requires="gemini CLI (npm install -g @google/gemini-cli)",
)
class GeminiCLIAgent(CLIAgent):
    """Agent that uses Google Gemini CLI (v0.22+).

    Falls back to OpenRouter (Google Gemini) on CLI failures if enabled.
    """

    def _extract_gemini_response(self, result: str) -> str:
        """Filter out YOLO mode message from gemini output."""
        lines = result.split("\n")
        filtered = [line for line in lines if not line.startswith("YOLO mode is enabled")]
        return "\n".join(filtered).strip()

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response using gemini CLI.

        For large prompts (>100KB), uses stdin to avoid OS E2BIG error.
        """
        full_prompt = self._build_full_prompt(prompt, context)
        # Use stdin for large prompts to avoid E2BIG (arg list too long)
        if self._is_prompt_too_large_for_argv(full_prompt):
            logger.debug(
                "[%s] Using stdin for large prompt (%s chars)", self.name, len(full_prompt)
            )
            return await self._generate_with_fallback(
                ["gemini", "--yolo", "-o", "text", "-"],
                prompt,
                context,
                input_text=full_prompt,
                response_extractor=self._extract_gemini_response,
            )
        return await self._generate_with_fallback(
            ["gemini", "--yolo", "-o", "text", full_prompt],
            prompt,
            context,
            response_extractor=self._extract_gemini_response,
        )


@AgentRegistry.register(
    "kilocode",
    default_model=None,
    default_name="kilocode",
    agent_type="CLI",
    requires="kilo CLI",
)
class KiloCodeAgent(CLIAgent):
    """Agent that uses Kilo Code CLI for codebase exploration.

    Kilo Code is an agentic coding assistant that can explore codebases
    autonomously. It supports multiple AI providers including Gemini and Grok
    via direct API or OpenRouter.

    Provider IDs should be in provider/model format for the `kilo run` CLI.
    Example: openrouter/google/gemini-3.1-pro-preview
    """

    def __init__(
        self,
        name: str,
        provider_id: str = "openrouter/google/gemini-3.1-pro-preview",
        model: str | None = None,
        role: AgentRole = "proposer",
        timeout: int = 600,
        mode: str = "architect",
    ):
        super().__init__(name, model or provider_id, role, timeout)
        self.provider_id = provider_id
        self.mode = mode  # architect, code, ask, debug

    def _extract_kilocode_response(self, output: str) -> str:
        """Extract the assistant response from Kilo Code JSON output."""
        clean = output.strip()
        if not clean:
            raise CLISubprocessError(
                message="KiloCode returned empty output",
                agent_name=self.name,
                returncode=0,
            )
        if re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", clean or ""):
            raise CLISubprocessError(
                message="KiloCode returned version string; provider not configured",
                agent_name=self.name,
                returncode=0,
                stderr=clean or None,
            )
        lines = output.strip().split("\n")
        responses = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") == "error":
                    err = msg.get("error") or {}
                    message = (
                        err.get("message") or err.get("data", {}).get("message") or "Kilo error"
                    )
                    raise CLISubprocessError(
                        message=f"KiloCode error event: {message}",
                        agent_name=self.name,
                        returncode=0,
                        stderr=json.dumps(err)[:500] if err else None,
                    )
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if content:
                        responses.append(content)
                elif msg.get("type") == "text":
                    text = msg.get("text", "")
                    if not text:
                        part = msg.get("part") or {}
                        text = part.get("text") or part.get("content", "")
                    if text:
                        responses.append(text)
            except json.JSONDecodeError:
                logger.debug("Skipping non-JSON line in agent output: %s", line[:100])
                continue
        return "\n\n".join(responses) if responses else output

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response using kilocode CLI with codebase access.

        For large prompts (>100KB), uses stdin to avoid OS E2BIG error.
        """
        full_prompt = self._build_full_prompt(prompt, context)
        # Kilo CLI expects provider/model via --model and outputs JSON events when --format json
        base_cmd = [
            "kilo",
            "run",
            "--format",
            "json",
            "--model",
            self.provider_id,
            "--auto",
        ]
        # Use a file attachment for very large prompts to avoid E2BIG errors
        if self._is_prompt_too_large_for_argv(full_prompt):
            logger.debug(
                "[%s] Using file attachment for large prompt (%s chars)",
                self.name,
                len(full_prompt),
            )
            tmp_path = None
            try:
                import tempfile

                with tempfile.NamedTemporaryFile(mode="w", delete=False) as tf:
                    tf.write(full_prompt)
                    tmp_path = tf.name
                return await self._generate_with_fallback(
                    base_cmd + ["--file", tmp_path, "--", "See attached prompt file."],
                    prompt,
                    context,
                    response_extractor=self._extract_kilocode_response,
                )
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except OSError as e:
                        logger.debug("Failed to clean up temp file %s: %s", tmp_path, e)
        return await self._generate_with_fallback(
            base_cmd + [full_prompt],
            prompt,
            context,
            response_extractor=self._extract_kilocode_response,
        )


@AgentRegistry.register(
    "grok-cli",
    default_model="grok-4-latest",
    agent_type="CLI",
    requires="grok CLI (npm install -g grok-cli)",
)
class GrokCLIAgent(CLIAgent):
    """Agent that uses xAI Grok CLI.

    Falls back to OpenRouter (xAI Grok) on CLI failures if enabled.
    """

    def _extract_grok_response(self, output: str) -> str:
        """Extract the final assistant response from Grok CLI JSON output."""
        lines = output.strip().split("\n")
        final_content = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if content and not content.startswith("Using tools"):
                        final_content = content
            except json.JSONDecodeError:
                if not output.startswith('{"role":'):
                    return output
                continue
        return final_content if final_content else output

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response using grok CLI.

        For large prompts (>100KB), uses stdin to avoid OS E2BIG error.
        """
        full_prompt = self._build_full_prompt(prompt, context)
        # Use stdin for large prompts to avoid E2BIG (arg list too long)
        if self._is_prompt_too_large_for_argv(full_prompt):
            logger.debug(
                "[%s] Using stdin for large prompt (%s chars)", self.name, len(full_prompt)
            )
            return await self._generate_with_fallback(
                ["grok", "-p", "-"],
                prompt,
                context,
                input_text=full_prompt,
                response_extractor=self._extract_grok_response,
            )
        return await self._generate_with_fallback(
            ["grok", "-p", full_prompt],
            prompt,
            context,
            response_extractor=self._extract_grok_response,
        )


@AgentRegistry.register(
    "qwen-cli",
    default_model="qwen3-coder",
    agent_type="CLI",
    requires="qwen CLI (npm install -g @qwen-code/qwen-code)",
)
class QwenCLIAgent(CLIAgent):
    """Agent that uses Alibaba Qwen Code CLI.

    Falls back to OpenRouter (Qwen) on CLI failures if enabled.
    """

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response using qwen CLI.

        For large prompts (>100KB), uses stdin to avoid OS E2BIG error.
        """
        full_prompt = self._build_full_prompt(prompt, context)
        # Use stdin for large prompts to avoid E2BIG (arg list too long)
        if self._is_prompt_too_large_for_argv(full_prompt):
            logger.debug(
                "[%s] Using stdin for large prompt (%s chars)", self.name, len(full_prompt)
            )
            return await self._generate_with_fallback(
                ["qwen", "-p", "-"],
                prompt,
                context,
                input_text=full_prompt,
            )
        return await self._generate_with_fallback(
            ["qwen", "-p", full_prompt],
            prompt,
            context,
        )


@AgentRegistry.register(
    "deepseek-cli",
    default_model="deepseek-v3",
    agent_type="CLI",
    requires="deepseek CLI (pip install deepseek-cli)",
    env_vars="DEEPSEEK_API_KEY",
)
class DeepseekCLIAgent(CLIAgent):
    """Agent that uses Deepseek CLI.

    Falls back to OpenRouter (Deepseek) on CLI failures if enabled.
    """

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response using deepseek CLI.

        For large prompts (>100KB), uses stdin to avoid OS E2BIG error.
        """
        full_prompt = self._build_full_prompt(prompt, context)
        # Use stdin for large prompts to avoid E2BIG (arg list too long)
        if self._is_prompt_too_large_for_argv(full_prompt):
            logger.debug(
                "[%s] Using stdin for large prompt (%s chars)", self.name, len(full_prompt)
            )
            return await self._generate_with_fallback(
                ["deepseek", "-p", "-"],
                prompt,
                context,
                input_text=full_prompt,
            )
        return await self._generate_with_fallback(
            ["deepseek", "-p", full_prompt],
            prompt,
            context,
        )


@AgentRegistry.register(
    "openai",
    default_model="gpt-5.3",
    agent_type="CLI",
    requires="openai CLI (pip install openai)",
    env_vars="OPENAI_API_KEY",
)
class OpenAIAgent(CLIAgent):
    """Agent that uses OpenAI CLI.

    Falls back to OpenRouter (OpenAI GPT) on CLI failures if enabled.
    """

    def __init__(
        self, name: str, model: str = "gpt-5.3", role: AgentRole = "proposer", timeout: int = 120
    ) -> None:
        super().__init__(name, model, role, timeout)

    def _extract_openai_response(self, result: str) -> str:
        """Parse JSON response from OpenAI CLI."""
        try:
            data = json.loads(result)
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", result)
            return result
        except json.JSONDecodeError:
            return result

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response using openai CLI.

        For large prompts (>100KB), uses stdin to avoid OS E2BIG error.
        """
        full_prompt = self._build_full_prompt(prompt, context)
        # Use stdin for large prompts to avoid E2BIG (arg list too long)
        if self._is_prompt_too_large_for_argv(full_prompt):
            logger.debug(
                "[%s] Using stdin for large prompt (%s chars)", self.name, len(full_prompt)
            )
            return await self._generate_with_fallback(
                [
                    "openai",
                    "api",
                    "chat.completions.create",
                    "-m",
                    self.model,
                    "-g",
                    "user",
                    "-",  # Read content from stdin
                ],
                prompt,
                context,
                input_text=full_prompt,
                response_extractor=self._extract_openai_response,
            )
        return await self._generate_with_fallback(
            [
                "openai",
                "api",
                "chat.completions.create",
                "-m",
                self.model,
                "-g",
                "user",
                full_prompt,
            ],
            prompt,
            context,
            response_extractor=self._extract_openai_response,
        )

    def _build_critique_prompt(self, proposal: str, task: str) -> str:
        """Build critique prompt with OpenAI-specific formatting."""
        return f"""Critically analyze this proposal:

Task: {task}
Proposal: {proposal}

Format your response as:
ISSUES:
- issue 1
- issue 2

SUGGESTIONS:
- suggestion 1
- suggestion 2

SEVERITY: X.X
REASONING: explanation"""


def get_default_agents() -> list[Agent]:
    """Return a default set of CLI agents for debates.

    Returns agents based on available CLI tools, providing a reasonable
    default roster for multi-model debates.

    Returns:
        List of Agent instances (ClaudeAgent, CodexAgent, GeminiCLIAgent, etc.)
    """
    agents: list[Agent] = [
        ClaudeAgent(name="claude", model="claude-sonnet-4-6"),
        CodexAgent(name="codex", model="gpt-5.3-codex"),
        GeminiCLIAgent(name="gemini-cli", model="gemini-3.1-pro-preview"),
    ]
    return agents


# Synchronous wrappers for convenience
def run_sync(coro: Any) -> Any:
    """Run an async function synchronously.

    Uses asyncio.run() which properly creates and closes the event loop,
    avoiding resource leaks and deprecation warnings from get_event_loop().
    """
    return asyncio.run(coro)
