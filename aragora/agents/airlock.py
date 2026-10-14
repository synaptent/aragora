"""
Airlock Resilience Layer for agents.

Wraps agents to contain failures gracefully:
- Timeout handling with configurable limits
- Response sanitization for malformed outputs
- Fallback responses on complete failure
- Metrics collection for monitoring

Inspired by the nomic loop debate proposal for resilience.
"""

from __future__ import annotations

__all__ = [
    "AirlockMetrics",
    "AirlockConfig",
    "AirlockProxy",
    "resolve_metrics_path",
    "wrap_agent",
    "wrap_agents",
]

import asyncio
import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from aragora.core import Agent, Critique, Message, Vote

logger = logging.getLogger(__name__)


OVERNIGHT_METRICS_PATH = Path(".aragora/overnight/boss_metrics.jsonl")


def resolve_metrics_path(
    metrics_path: str | Path = OVERNIGHT_METRICS_PATH,
    *,
    start: str | Path | None = None,
) -> Path:
    """Resolve overnight metrics across managed worktrees.

    Managed Codex worktrees usually do not have their own `.aragora` state;
    Git's common dir points back to the shared checkout where overnight
    benchmark metrics are written.
    """
    path = Path(metrics_path)
    base = Path(start) if start is not None else Path.cwd()
    candidate = path if path.is_absolute() else base / path
    if candidate.exists() or path.is_absolute():
        return candidate

    try:
        common_dir_output = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=base,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return candidate

    common_dir = Path(common_dir_output)
    if not common_dir.is_absolute():
        common_dir = base / common_dir
    shared_root = common_dir.parent if common_dir.name == ".git" else common_dir
    shared_candidate = shared_root / path
    if shared_candidate.exists():
        return shared_candidate
    return candidate


@dataclass
class AirlockMetrics:
    """Metrics collected by the airlock wrapper."""

    total_calls: int = 0
    successful_calls: int = 0
    timeout_errors: int = 0
    sanitization_applied: int = 0
    fallback_responses: int = 0
    total_latency_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        """Return success rate as a percentage."""
        if self.total_calls == 0:
            return 100.0
        return (self.successful_calls / self.total_calls) * 100

    @property
    def avg_latency_ms(self) -> float:
        """Return average latency in milliseconds."""
        if self.successful_calls == 0:
            return 0.0
        return self.total_latency_ms / self.successful_calls

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "timeout_errors": self.timeout_errors,
            "sanitization_applied": self.sanitization_applied,
            "fallback_responses": self.fallback_responses,
            "success_rate": round(self.success_rate, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
        }


@dataclass
class AirlockConfig:
    """Configuration for the airlock wrapper."""

    # Timeout settings (increased for complex debate prompts)
    generate_timeout: float = 240.0  # seconds
    critique_timeout: float = 180.0
    vote_timeout: float = 120.0

    # Retry settings
    max_retries: int = 1
    retry_delay: float = 2.0

    # Sanitization settings
    extract_json: bool = True
    strip_markdown_fences: bool = True

    # Fallback settings
    fallback_on_timeout: bool = True
    fallback_on_error: bool = True


class AirlockProxy:
    """
    Wrap any agent to contain failures gracefully.

    The AirlockProxy acts as a transparent wrapper around any Agent,
    intercepting calls to add timeout handling, response sanitization,
    and fallback behavior.

    Usage:
        agent = GeminiAgent(name="gemini", model="gemini-3-pro")
        safe_agent = AirlockProxy(agent)

        # Use safe_agent exactly like the original agent
        response = await safe_agent.generate("Hello")

    Features:
        - Configurable timeouts per operation type
        - Response sanitization (extract JSON from malformed output)
        - Fallback responses when agent fails completely
        - Metrics collection for monitoring
    """

    def __init__(
        self,
        agent: Agent,
        config: AirlockConfig | None = None,
    ):
        """
        Initialize the airlock wrapper.

        Args:
            agent: The agent to wrap
            config: Optional configuration (defaults provided)
        """
        self._agent = agent
        self._config = config or AirlockConfig()
        self._metrics = AirlockMetrics()

    # Expose agent attributes transparently
    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to wrapped agent."""
        return getattr(self._agent, name)

    @property
    def metrics(self) -> AirlockMetrics:
        """Get collected metrics."""
        return self._metrics

    @property
    def wrapped_agent(self) -> Agent:
        """Get the wrapped agent."""
        return self._agent

    # Core method wrappers

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        """Generate a response with timeout and sanitization."""

        async def coro_factory() -> str:
            return await self._agent.generate(prompt, context)

        return await self._safe_call(
            "generate",
            coro_factory,
            timeout=self._config.generate_timeout,
            fallback=self._generate_fallback(prompt),
        )

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        """Critique a proposal with timeout handling.

        Args:
            proposal: The proposal content to critique
            task: The debate task/question
            context: Optional conversation context
            target_agent: Name of the agent being critiqued (for fallback messages)
        """
        from aragora.core import Critique

        async def coro_factory() -> Critique:
            return await self._agent.critique(proposal, task, context)

        result = await self._safe_call(
            "critique",
            coro_factory,
            timeout=self._config.critique_timeout,
            fallback=self._critique_fallback(proposal, task, target_agent or "unknown"),
        )

        # If fallback returned a dict, convert to Critique
        if isinstance(result, dict):
            return Critique(**result)
        return result

    async def vote(
        self,
        proposals: dict[str, str],
        task: str,
    ) -> Vote:
        """Vote on proposals with timeout handling."""
        from aragora.core import Vote

        async def coro_factory() -> Vote:
            return await self._agent.vote(proposals, task)

        result = await self._safe_call(
            "vote",
            coro_factory,
            timeout=self._config.vote_timeout,
            fallback=self._vote_fallback(proposals, task),
        )

        # If fallback returned a dict, convert to Vote
        if isinstance(result, dict):
            return Vote(**result)
        return result

    # Internal helpers

    async def _safe_call(
        self,
        operation: str,
        coro_factory: Callable[[], Awaitable[Any]],
        timeout: float,
        fallback: Any,
    ) -> Any:
        """
        Execute a coroutine with timeout and error handling.

        Args:
            operation: Name of the operation (for logging)
            coro_factory: Callable that returns a fresh coroutine for each attempt
            timeout: Timeout in seconds
            fallback: Value to return on failure

        Returns:
            Result of coroutine or fallback value
        """
        self._metrics.total_calls += 1
        start_time = time.time()

        for attempt in range(self._config.max_retries + 1):
            try:
                # Create fresh coroutine for each attempt (fixes reuse bug)
                coro = coro_factory()
                result = await asyncio.wait_for(coro, timeout=timeout)
                elapsed_ms = (time.time() - start_time) * 1000

                # Sanitize result if it's a string
                if isinstance(result, str):
                    result = self._sanitize_response(result)

                self._metrics.successful_calls += 1
                self._metrics.total_latency_ms += elapsed_ms

                logger.debug(
                    "airlock_success agent=%s op=%s latency_ms=%.0f",
                    self._agent.name,
                    operation,
                    elapsed_ms,
                )
                return result

            except asyncio.TimeoutError:
                self._metrics.timeout_errors += 1
                logger.debug(
                    "airlock_timeout agent=%s op=%s timeout=%ss attempt=%s",
                    self._agent.name,
                    operation,
                    timeout,
                    attempt + 1,
                )

                if attempt < self._config.max_retries:
                    await asyncio.sleep(self._config.retry_delay)
                    continue

                if self._config.fallback_on_timeout:
                    self._metrics.fallback_responses += 1
                    logger.debug(
                        "airlock_fallback agent=%s op=%s reason=timeout",
                        self._agent.name,
                        operation,
                    )
                    return fallback

                raise

            except (ConnectionError, OSError, RuntimeError) as e:
                # Retryable errors - network/connection issues
                logger.debug(
                    "airlock_retryable agent=%s op=%s error=%s: %s",
                    self._agent.name,
                    operation,
                    type(e).__name__,
                    e,
                )

                if attempt < self._config.max_retries:
                    await asyncio.sleep(self._config.retry_delay)
                    continue

                if self._config.fallback_on_error:
                    self._metrics.fallback_responses += 1
                    logger.debug(
                        "airlock_fallback agent=%s op=%s reason=retryable_error",
                        self._agent.name,
                        operation,
                    )
                    return fallback

                raise

            except (ValueError, TypeError, AttributeError) as e:
                # Non-retryable errors - validation/programming issues
                logger.error(
                    "airlock_error agent=%s op=%s error=%s: %s (non-retryable)",
                    self._agent.name,
                    operation,
                    type(e).__name__,
                    e,
                )
                # Don't retry - raise immediately or fallback
                if self._config.fallback_on_error:
                    self._metrics.fallback_responses += 1
                    return fallback
                raise

            except Exception as e:  # noqa: BLE001 - Intentional catch-all: airlock is a resilience layer that must contain ANY agent failure to keep debates alive
                # Unknown errors - log and treat as retryable
                logger.error(
                    "airlock_error agent=%s op=%s error=%s: %s",
                    self._agent.name,
                    operation,
                    type(e).__name__,
                    e,
                )

                if attempt < self._config.max_retries:
                    await asyncio.sleep(self._config.retry_delay)
                    continue

                if self._config.fallback_on_error:
                    self._metrics.fallback_responses += 1
                    logger.debug(
                        "airlock_fallback agent=%s op=%s reason=error", self._agent.name, operation
                    )
                    return fallback

                raise

        # Should not reach here, but return fallback just in case
        return fallback

    def _sanitize_response(self, content: str) -> str:
        """
        Sanitize and clean up a response.

        Handles common issues:
        - Strip markdown code fences
        - Extract JSON from surrounding text
        - Remove null bytes and control characters
        """
        if not content:
            return content

        original_content = content

        # Strip markdown code fences
        if self._config.strip_markdown_fences:
            # Remove ```json ... ``` or ```python ... ``` etc.
            content = re.sub(
                r"```(?:json|python|javascript|typescript)?\s*\n?",
                "",
                content,
            )
            content = re.sub(r"```\s*$", "", content)

        # Remove null bytes and control characters (except newlines/tabs)
        content = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", content)

        # Try to extract JSON if configured and content looks like it might have JSON
        if self._config.extract_json:
            content = self._try_extract_json(content)

        # Track if we modified the content
        if content != original_content:
            self._metrics.sanitization_applied += 1
            logger.debug(
                "airlock_sanitized agent=%s original_len=%s new_len=%s",
                self._agent.name,
                len(original_content),
                len(content),
            )

        return content.strip()

    def _try_extract_json(self, content: str) -> str:
        """
        Try to extract valid JSON from content that may have extra text.

        If content doesn't start with '{' or '[', try to find and extract
        the JSON portion.
        """
        content = content.strip()

        # If it already looks like JSON, return as-is
        if content.startswith(("{", "[")):
            return content

        # Try to find JSON object
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            try:
                # Validate it's actual JSON
                json.loads(match.group(0))
                return match.group(0)
            except json.JSONDecodeError:
                logger.debug("JSON object extraction failed, trying array pattern")

        # Try to find JSON array
        match = re.search(r"\[[\s\S]*\]", content)
        if match:
            try:
                json.loads(match.group(0))
                return match.group(0)
            except json.JSONDecodeError:
                logger.debug("JSON array extraction failed, returning original content")

        # Return original if no JSON found
        return content

    # Fallback generators

    def _generate_fallback(self, prompt: str) -> str:
        """Generate a fallback response for generate()."""
        return (
            f"[Agent {self._agent.name} timed out. "
            f"Unable to generate response for: {prompt[:100]}...]"
        )

    def _critique_fallback(self, proposal: str, task: str, target_agent: str) -> dict:
        """Generate a fallback critique.

        Args:
            proposal: The proposal content that was being critiqued
            task: The debate task/question
            target_agent: Name of the agent being critiqued
        """
        return {
            "agent": self._agent.name,
            "target_agent": target_agent,
            "target_content": proposal[:200],
            "issues": [f"Agent {self._agent.name} was unable to respond in time"],
            "suggestions": ["Consider increasing timeout or retrying"],
            "severity": 0.1,  # Low severity - we don't actually know if there are issues
            "reasoning": "Fallback critique due to agent timeout/error",
        }

    def _vote_fallback(self, proposals: dict[str, str], task: str) -> dict:
        """Generate a fallback vote."""
        # Vote for the first proposal as a fallback
        first_agent = next(iter(proposals.keys()), "unknown")
        return {
            "agent": self._agent.name,
            "choice": first_agent,
            "reasoning": f"Fallback vote due to agent timeout/error. "
            f"Defaulting to first proposal from {first_agent}.",
            "confidence": 0.1,  # Low confidence
            "continue_debate": False,
        }


def wrap_agent(
    agent: Agent,
    config: AirlockConfig | None = None,
) -> AirlockProxy:
    """
    Convenience function to wrap an agent with airlock protection.

    Args:
        agent: The agent to wrap
        config: Optional configuration

    Returns:
        AirlockProxy wrapping the agent
    """
    if isinstance(agent, AirlockProxy):
        return agent
    return AirlockProxy(agent, config)


def wrap_agents(
    agents: list[Agent],
    config: AirlockConfig | None = None,
) -> list[AirlockProxy]:
    """
    Wrap multiple agents with airlock protection.

    Args:
        agents: List of agents to wrap
        config: Optional configuration (applied to all)

    Returns:
        List of AirlockProxy instances
    """
    wrapped: list[AirlockProxy] = []
    for agent in agents:
        if isinstance(agent, AirlockProxy):
            wrapped.append(agent)
        else:
            wrapped.append(AirlockProxy(agent, config))
    return wrapped
