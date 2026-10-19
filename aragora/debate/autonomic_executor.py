"""
Autonomic executor for safe agent operations.

Provides error handling and timeout management for agent generation,
critique, and voting operations. Implements the "autonomic layer" pattern
that catches all exceptions to keep debates running even when individual
agents fail.

Features:
- Timeout escalation: retries use progressively longer timeouts
- Fallback agents: automatic substitution when primary agent fails
- Streaming buffer: capture partial content from timed-out streams
- Circuit breaker integration: track and avoid failing agents

Extracted from Arena orchestrator to improve testability and separation
of concerns.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import TYPE_CHECKING, TypeVar, Any
from collections.abc import Awaitable

from aragora.config import AGENT_TIMEOUT_SECONDS
from aragora.resilience import CircuitBreaker

T = TypeVar("T")
from aragora.debate.sanitization import OutputSanitizer
from aragora.debate.schemas import validate_agent_response

# Lazy import for telemetry to avoid circular imports
_telemetry_initialized = False


def _ensure_telemetry_collectors() -> None:
    """Initialize default telemetry collectors (once)."""
    global _telemetry_initialized
    if _telemetry_initialized:
        return
    try:
        from aragora.agents.telemetry import setup_default_collectors

        setup_default_collectors()
        _telemetry_initialized = True
    except ImportError:
        pass


if TYPE_CHECKING:
    from aragora.agents.performance_monitor import AgentPerformanceMonitor
    from aragora.core import Agent, Critique, Message, Vote
    from aragora.debate.chaos_theater import ChaosDirector
    from aragora.debate.immune_system import TransparentImmuneSystem
    from aragora.insights.store import InsightStore

logger = logging.getLogger(__name__)


class StreamingContentBuffer:
    """
    Buffer for capturing partial streaming responses.

    When an agent times out during streaming, this buffer preserves
    any content received before the timeout, allowing partial responses
    to be recovered rather than lost entirely.

    Thread-safe via per-agent locks.
    """

    def __init__(self) -> None:
        self._buffer: dict[str, str] = defaultdict(str)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def append(self, agent_name: str, chunk: str) -> None:
        """Append chunk to agent's buffer."""
        async with self._locks[agent_name]:
            self._buffer[agent_name] += chunk

    def get_partial(self, agent_name: str) -> str:
        """Get accumulated partial content (non-async for error handlers)."""
        return self._buffer.get(agent_name, "")

    async def get_partial_async(self, agent_name: str) -> str:
        """Get accumulated partial content with lock."""
        async with self._locks[agent_name]:
            return self._buffer.get(agent_name, "")

    async def clear(self, agent_name: str) -> None:
        """Clear agent's buffer."""
        async with self._locks[agent_name]:
            self._buffer.pop(agent_name, None)

    def clear_sync(self, agent_name: str) -> None:
        """Clear agent's buffer (non-async)."""
        self._buffer.pop(agent_name, None)


class AutonomicExecutor:
    """
    Executes agent operations with automatic error handling.

    The autonomic layer ensures that individual agent failures don't
    crash the entire debate. Errors are caught, logged, and converted
    to graceful fallback responses.

    Features:
        - Timeout escalation: each retry gets 1.5x more time (configurable)
        - Fallback agents: automatic substitution when primary agent fails
        - Streaming buffer: capture partial content from timed-out streams
        - Circuit breaker: track and avoid persistently failing agents

    Usage:
        executor = AutonomicExecutor(circuit_breaker)
        response = await executor.generate(agent, prompt, context)
        critique = await executor.critique(agent, proposal, task, context)
        vote = await executor.vote(agent, proposals, task)

        # With fallback agents
        response = await executor.generate_with_fallback(
            agent, prompt, context, fallback_agents=[backup1, backup2]
        )
    """

    def __init__(
        self,
        circuit_breaker: CircuitBreaker | None = None,
        default_timeout: float | None = None,  # Uses AGENT_TIMEOUT_SECONDS if not specified
        timeout_escalation_factor: float = 1.5,
        max_timeout: float = 600.0,  # Max timeout cap
        streaming_buffer: StreamingContentBuffer | None = None,
        wisdom_store: InsightStore | None = None,
        loop_id: str | None = None,
        immune_system: TransparentImmuneSystem | None = None,
        chaos_director: ChaosDirector | None = None,
        performance_monitor: AgentPerformanceMonitor | None = None,
        enable_telemetry: bool = False,
        event_hooks: dict | None = None,  # Optional hooks for emitting events
        power_sampling_config: Any | None = None,
        power_sampling_scorer: Any | None = None,
    ):
        """
        Initialize the autonomic executor.

        Args:
            circuit_breaker: Optional circuit breaker for failure tracking
            default_timeout: Default timeout for agent operations in seconds
            timeout_escalation_factor: Multiplier for timeout on each retry (default 1.5x)
            max_timeout: Maximum timeout cap in seconds (default 300s / 5 min)
            streaming_buffer: Optional buffer for capturing partial streaming content
            wisdom_store: Optional InsightStore for audience wisdom fallback
            loop_id: Current loop/debate ID for wisdom retrieval
            immune_system: Optional TransparentImmuneSystem for health monitoring
            chaos_director: Optional ChaosDirector for theatrical failure messages
            performance_monitor: Optional AgentPerformanceMonitor for telemetry
            enable_telemetry: Enable Prometheus/Blackbox telemetry emission
            event_hooks: Optional dict of hooks for emitting agent events (on_agent_error, etc.)
        """
        self.circuit_breaker = circuit_breaker
        self.event_hooks = event_hooks or {}
        # Use AGENT_TIMEOUT_SECONDS from config if not explicitly specified
        self.default_timeout = (
            default_timeout if default_timeout is not None else float(AGENT_TIMEOUT_SECONDS)
        )
        self.immune_system = immune_system
        self.chaos_director = chaos_director
        self.timeout_escalation_factor = timeout_escalation_factor
        self.max_timeout = max_timeout
        self.streaming_buffer = streaming_buffer or StreamingContentBuffer()
        self.wisdom_store = wisdom_store
        self.loop_id = loop_id
        self.performance_monitor = performance_monitor
        self.enable_telemetry = enable_telemetry
        self.power_sampling_config = power_sampling_config
        self._power_sampling_scorer = power_sampling_scorer
        self._power_sampler: Any = None
        self._power_sampling_runtime_config: Any = None
        self._power_sampling_resolved = False
        # Track retry counts per agent for timeout escalation
        self._retry_counts: dict[str, int] = defaultdict(int)

        # Per-debate cost tracking (set via set_debate_cost_tracker)
        self._debate_cost_tracker: Any = None
        self._debate_id: str = ""

        # Initialize telemetry collectors if enabled
        if enable_telemetry:
            _ensure_telemetry_collectors()
            logger.debug("[telemetry] Prometheus/Blackbox collectors initialized")

    def set_loop_id(self, loop_id: str) -> None:
        """Set the current loop/debate ID for wisdom retrieval."""
        self.loop_id = loop_id

    def set_debate_cost_tracker(
        self,
        tracker: Any,
        debate_id: str,
    ) -> None:
        """Attach a DebateCostTracker and debate ID for per-call cost recording.

        Called by the Arena at debate start so that every agent call through
        this executor is automatically recorded with per-agent, per-round,
        and per-operation cost breakdowns.

        Args:
            tracker: DebateCostTracker instance (or None to disable).
            debate_id: The debate ID to associate costs with.
        """
        self._debate_cost_tracker = tracker
        self._debate_id = debate_id

    def _record_call_cost(
        self,
        agent: Any,
        phase: str,
        round_num: int,
    ) -> None:
        """Record cost of the last agent API call to the DebateCostTracker.

        Reads last_tokens_in / last_tokens_out from the agent (set by
        APIAgent._record_token_usage after each call) and records them
        with the correct debate_id, round, and operation.

        This is a best-effort operation -- failures are logged at debug
        level and never propagate to callers.
        """
        if self._debate_cost_tracker is None or not self._debate_id:
            return

        try:
            tokens_in = getattr(agent, "last_tokens_in", 0) or 0
            tokens_out = getattr(agent, "last_tokens_out", 0) or 0

            # Only record if we actually have token usage data
            if tokens_in == 0 and tokens_out == 0:
                return

            provider = getattr(agent, "provider", "unknown") or "unknown"
            # Price against the model that ACTUALLY answered: a call a
            # server-side refusal fallback served produced its tokens at the
            # fallback model's rate, not the requested model's (finding C-P3
            # on #9989). ``billing_model`` is ``self.model`` for every agent
            # that cannot tell the difference.
            model = (
                getattr(agent, "billing_model", None) or getattr(agent, "model", None) or "unknown"
            )
            agent_name = getattr(agent, "name", str(agent))

            self._debate_cost_tracker.record_agent_call(
                debate_id=self._debate_id,
                agent_name=agent_name,
                provider=provider,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                round_number=round_num,
                operation=phase,
            )
        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("autonomic_cost_record_failed (non-critical): %s", e)

    def _emit_agent_error(
        self,
        agent_name: str,
        error_type: str,
        message: str,
        recoverable: bool = True,
        phase: str = "",
    ) -> None:
        """Emit an agent error event via hooks if available.

        This notifies the frontend about agent failures so users understand
        why an agent produced placeholder/error output.
        """
        on_agent_error = self.event_hooks.get("on_agent_error")
        if on_agent_error:
            try:
                on_agent_error(
                    agent=agent_name,
                    error_type=error_type,
                    message=message,
                    recoverable=recoverable,
                    phase=phase,
                )
            except (RuntimeError, TypeError, AttributeError, ValueError) as e:
                logger.debug("[Autonomic] Failed to emit agent error event: %s", e)

    def _should_power_sample(self, agent: Agent, phase: str) -> bool:
        cfg = self.power_sampling_config
        if cfg is None or not getattr(cfg, "enable_power_sampling", False):
            return False
        role = getattr(agent, "role", "")
        if role == "critic" and not getattr(cfg, "enable_for_critiques", False):
            return False
        return True

    def _resolve_power_sampling(self) -> None:
        if self._power_sampling_resolved:
            return
        self._power_sampling_resolved = True

        cfg = self.power_sampling_config
        if cfg is None:
            return

        try:
            from aragora.reasoning.sampling.power_sampling import (
                PowerSamplingConfig as RuntimeConfig,
            )

            temps = [float(getattr(cfg, "sampling_temperature", 1.0))] * int(
                getattr(cfg, "n_samples", 8)
            )
            self._power_sampling_runtime_config = RuntimeConfig(
                n_samples=int(getattr(cfg, "n_samples", 8)),
                power_alpha=float(getattr(cfg, "alpha", 2.0)),
                min_samples=min(
                    int(getattr(cfg, "k_diverse", 3)), int(getattr(cfg, "n_samples", 8))
                ),
                temperature_schedule=temps,
                timeout_seconds=float(getattr(cfg, "sample_timeout", 30.0)),
            )
        except (ImportError, ValueError, TypeError, AttributeError) as e:
            logger.debug("[Autonomic] Power sampling config resolution failed: %s", e)
            self._power_sampling_runtime_config = None

        # Resolve custom scorer if configured
        custom_path = getattr(cfg, "custom_scorer", None) if cfg is not None else None
        if custom_path and self._power_sampling_scorer is None:
            self._power_sampling_scorer = self._load_custom_scorer(custom_path)

    def _load_custom_scorer(self, path: str) -> Any | None:
        try:
            import importlib

            module_path, _, attr = path.rpartition(".")
            if not module_path:
                return None
            module = importlib.import_module(module_path)
            scorer = getattr(module, attr, None)
            if scorer is None:
                return None
            if isinstance(scorer, type):
                scorer = scorer()
            if callable(scorer) and not hasattr(scorer, "score"):
                func = scorer

                class _FuncScorer:
                    async def score(self, response: str, prompt: str) -> float:  # type: ignore[override]
                        return float(func(response, prompt))

                return _FuncScorer()
            return scorer
        except (ImportError, AttributeError, ValueError, TypeError, ModuleNotFoundError) as e:
            logger.debug("[Autonomic] Failed to load custom scorer %s: %s", path, e)
            return None

    def _get_power_sampler(self) -> Any | None:
        self._resolve_power_sampling()
        if self._power_sampling_runtime_config is None:
            return None
        if self._power_sampler is None:
            try:
                from aragora.reasoning.sampling.power_sampling import PowerSampler

                self._power_sampler = PowerSampler(config=self._power_sampling_runtime_config)
            except (ImportError, RuntimeError, TypeError, ValueError) as e:
                logger.debug("[Autonomic] Failed to initialize PowerSampler: %s", e)
                self._power_sampler = None
        return self._power_sampler

    async def _generate_with_power_sampling(
        self,
        agent: Agent,
        prompt: str,
        context: list[Message],
    ) -> str:
        sampler = self._get_power_sampler()
        if sampler is None:
            return await agent.generate(prompt, context)

        scorer = self._power_sampling_scorer
        if scorer is None:
            try:
                from aragora.reasoning.sampling.power_sampling import DefaultScorer

                scorer = DefaultScorer()
            except (ImportError, AttributeError):
                scorer = None

        async def generator(p: str) -> str:
            return await agent.generate(p, context)

        if scorer is None:
            return await generator(prompt)

        try:
            result = await sampler.sample_best_reasoning(generator, prompt, scorer)
            return result.best_response or await generator(prompt)
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("[Autonomic] Power sampling failed: %s", e)
            return await generator(prompt)

    @staticmethod
    def _is_empty_critique(result: Critique | None) -> bool:
        """Return True if a critique is empty or only contains placeholder content."""
        if result is None:
            return True
        if isinstance(result, str):
            return not result.strip()

        raw_issues = getattr(result, "issues", [])
        raw_suggestions = getattr(result, "suggestions", [])
        issues = (
            [i.strip() for i in raw_issues if isinstance(i, str) and i.strip()]
            if isinstance(raw_issues, (list, tuple, set))
            else []
        )
        suggestions = (
            [s.strip() for s in raw_suggestions if isinstance(s, str) and s.strip()]
            if isinstance(raw_suggestions, (list, tuple, set))
            else []
        )
        if not issues and not suggestions:
            if not isinstance(raw_issues, (list, tuple, set)) and not isinstance(
                raw_suggestions, (list, tuple, set)
            ):
                for attr in ("text", "message", "content"):
                    value = getattr(result, attr, None)
                    if isinstance(value, str) and value.strip():
                        return False
            return True
        if len(issues) == 1:
            normalized = issues[0].strip().lower()
            if normalized in (
                "agent response was empty",
                "(agent produced empty output)",
                "agent produced empty output",
            ):
                return not suggestions
        return False

    def _emit_agent_telemetry(
        self,
        agent_name: str,
        operation: str,
        start_time: float,
        success: bool,
        error: Exception | None = None,
        output: str | None = None,
        input_text: str | None = None,
    ) -> None:
        """Emit telemetry for an agent operation if enabled."""
        if not self.enable_telemetry:
            return

        try:
            from aragora.agents.telemetry import AgentTelemetry, _emit_telemetry

            telemetry = AgentTelemetry(
                agent_name=agent_name,
                operation=operation,
                start_time=start_time,
            )

            # Set input/output tokens
            if input_text:
                telemetry.input_chars = len(input_text)
                telemetry.input_tokens = AgentTelemetry.estimate_tokens(input_text)
            if output:
                telemetry.output_chars = len(output)
                telemetry.output_tokens = AgentTelemetry.estimate_tokens(output)

            telemetry.complete(success=success, error=error)
            _emit_telemetry(telemetry)
        except ImportError:
            pass  # Telemetry not available
        except (TypeError, ValueError, OSError) as e:
            # Expected telemetry issues: serialization, I/O
            logger.debug("[telemetry] Emission failed: %s", e)
        except (RuntimeError, AttributeError, KeyError) as e:
            # Unexpected errors - log at warning level
            logger.warning("[telemetry] Unexpected emission error: %s: %s", type(e).__name__, e)

    def _get_wisdom_fallback(self, failed_agent: str) -> str | None:
        """
        Get audience wisdom as fallback when agent fails.

        Returns formatted wisdom response if available, None otherwise.
        """
        if not self.wisdom_store or not self.loop_id:
            return None

        try:
            wisdom_list = self.wisdom_store.get_relevant_wisdom(self.loop_id, limit=1)
            if not wisdom_list:
                return None

            wisdom = wisdom_list[0]
            self.wisdom_store.mark_wisdom_used(wisdom["id"])

            logger.info("[wisdom] Injecting audience wisdom for failed agent %s", failed_agent)

            return (
                f"[Audience Wisdom - submitted by {wisdom['submitter_id']}]\n\n"
                f"{wisdom['text']}\n\n"
                f"[System: This response was provided by the audience after "
                f"{failed_agent} failed to respond]"
            )
        except (KeyError, OSError) as e:
            # Expected database/storage issues
            logger.warning("[wisdom] Failed to retrieve wisdom: %s", e)
            return None
        except (RuntimeError, AttributeError, TypeError, ValueError) as e:
            # Unexpected errors - log with more detail
            logger.error("[wisdom] Unexpected error retrieving wisdom: %s: %s", type(e).__name__, e)
            return None

    def get_escalated_timeout(self, agent_name: str, base_timeout: float | None = None) -> float:
        """
        Calculate escalated timeout based on retry count.

        Each retry increases the timeout by the escalation factor,
        up to max_timeout. This gives slow agents more time on retries
        while keeping initial attempts fast.

        Args:
            agent_name: Agent name for retry tracking
            base_timeout: Base timeout (uses default if None)

        Returns:
            Escalated timeout in seconds
        """
        base = base_timeout or self.default_timeout
        retry_count = self._retry_counts[agent_name]
        escalated = base * (self.timeout_escalation_factor**retry_count)
        return min(escalated, self.max_timeout)

    def record_retry(self, agent_name: str) -> int:
        """
        Record a retry attempt for an agent.

        Args:
            agent_name: Agent that is being retried

        Returns:
            New retry count
        """
        self._retry_counts[agent_name] += 1
        return self._retry_counts[agent_name]

    def reset_retries(self, agent_name: str) -> None:
        """Reset retry count for an agent after success."""
        self._retry_counts.pop(agent_name, None)

    async def with_timeout(
        self,
        coro: Awaitable[T],
        agent_name: str,
        timeout_seconds: float | None = None,
    ) -> T:
        """
        Wrap coroutine with per-agent timeout.

        If the agent times out, records a circuit breaker failure and
        raises TimeoutError. This prevents a single stalled agent from
        blocking the entire debate.

        Args:
            coro: Coroutine to execute
            agent_name: Agent name for logging and circuit breaker
            timeout_seconds: Timeout in seconds (uses default if None)

        Returns:
            Result of the coroutine

        Raises:
            TimeoutError: If the operation times out
        """
        timeout = timeout_seconds or self.default_timeout
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            if self.circuit_breaker:
                just_opened = self.circuit_breaker.record_failure(agent_name)
                if just_opened and self.immune_system:
                    self.immune_system.circuit_opened(agent_name, f"timeout after {timeout}s")
            logger.warning("Agent %s timed out after %ss", agent_name, timeout)
            raise TimeoutError(f"Agent {agent_name} timed out after {timeout}s")

    async def generate(
        self,
        agent: Agent,
        prompt: str,
        context: list[Message],
        phase: str = "",
        round_num: int = 0,
    ) -> str:
        """
        Generate response with an agent, handling errors and sanitizing output.

        Implements the "autonomic layer" - catches all exceptions to keep
        the debate alive even when individual agents fail.

        Args:
            agent: Agent to generate response
            prompt: Prompt for the agent
            context: Conversation context
            phase: Current debate phase (for telemetry)
            round_num: Current round number (for telemetry)

        Returns:
            Generated response (or system message on failure)
        """
        start_time = time.time()

        # Start performance tracking
        tracking_id = None
        if self.performance_monitor:
            tracking_id = self.performance_monitor.track_agent_call(
                agent.name, "generate", phase=phase, round_num=round_num
            )

        # Notify immune system that agent started
        if self.immune_system:
            self.immune_system.agent_started(agent.name, task=prompt[:100])

        # Progress monitoring task for immune system transparency
        progress_task = None
        if self.immune_system:
            # Bind the narrowed reference the closure actually uses: reading
            # ``self.immune_system`` from inside the task would re-widen it to
            # ``... | None`` (the attribute is reassignable), and the task can
            # outlive any later reassignment.
            immune_system = self.immune_system

            async def _report_progress() -> None:
                """Periodically report agent progress to immune system."""
                try:
                    while True:
                        await asyncio.sleep(5)
                        elapsed = time.time() - start_time
                        immune_system.agent_progress(agent.name, elapsed)
                except asyncio.CancelledError:
                    pass

            progress_task = asyncio.create_task(_report_progress())
            progress_task.add_done_callback(
                lambda t: logger.debug("[Autonomic] Progress monitoring error: %s", t.exception())
                if not t.cancelled() and t.exception()
                else None
            )

        try:
            if self._should_power_sample(agent, phase):
                raw_output = await self._generate_with_power_sampling(agent, prompt, context)
            else:
                raw_output = await agent.generate(prompt, context)
            response_ms = (time.time() - start_time) * 1000

            # Notify immune system of successful completion
            if self.immune_system:
                self.immune_system.agent_completed(agent.name, response_ms, success=True)

            # If circuit was open for this agent and it just succeeded, notify closure
            if self.circuit_breaker and self.immune_system:
                was_open = not self.circuit_breaker.is_available(agent.name)
                self.circuit_breaker.record_success(agent.name)
                if was_open and self.circuit_breaker.is_available(agent.name):
                    self.immune_system.circuit_closed(agent.name)

            sanitized = OutputSanitizer.sanitize_agent_output(raw_output, agent.name)
            empty_output = sanitized == "(Agent produced empty output)"

            # Retry once on empty output (qwen and other agents sometimes produce empty responses)
            if empty_output:
                logger.warning(
                    "[Autonomic] Agent %s produced empty output, retrying once...", agent.name
                )
                retry_raw = await agent.generate(prompt, context)
                retry_sanitized = OutputSanitizer.sanitize_agent_output(retry_raw, agent.name)
                if retry_sanitized != "(Agent produced empty output)":
                    logger.info("[Autonomic] Agent %s retry succeeded", agent.name)
                    sanitized = retry_sanitized
                    empty_output = False
                else:
                    logger.warning(
                        "[Autonomic] Agent %s retry also produced empty output", agent.name
                    )

            if empty_output:
                if tracking_id and self.performance_monitor:
                    self.performance_monitor.record_completion(
                        tracking_id, success=False, error="empty output"
                    )

                if self.circuit_breaker:
                    just_opened = self.circuit_breaker.record_failure(agent.name)
                    if just_opened and self.immune_system:
                        self.immune_system.circuit_opened(agent.name, "empty output")

                if self.immune_system:
                    self.immune_system.agent_failed(agent.name, "empty output", recoverable=True)

                self._emit_agent_telemetry(
                    agent.name,
                    "generate",
                    start_time,
                    success=False,
                    error=None,  # Empty output is not an exception
                    input_text=prompt,
                )
                self._emit_agent_error(
                    agent.name,
                    error_type="empty",
                    message="Agent produced empty output",
                    recoverable=True,
                    phase=phase,
                )
                return sanitized

            # Validate response schema for type safety and size limits
            validation_result = validate_agent_response(
                content=sanitized,
                agent_name=agent.name,
                role=getattr(agent, "role", "proposer"),
                round_number=round_num,
            )
            if not validation_result.is_valid:
                logger.warning(
                    "[Autonomic] Agent %s response validation failed: %s",
                    agent.name,
                    validation_result.errors,
                )
            elif validation_result.warnings:
                for warning in validation_result.warnings:
                    logger.info("[Autonomic] Agent %s response warning: %s", agent.name, warning)

            # Record successful completion
            if tracking_id and self.performance_monitor:
                self.performance_monitor.record_completion(
                    tracking_id, success=True, response=sanitized
                )

            # Emit telemetry
            self._emit_agent_telemetry(
                agent.name,
                "generate",
                start_time,
                success=True,
                output=sanitized,
                input_text=prompt,
            )

            # Record per-call cost to DebateCostTracker (best-effort)
            self._record_call_cost(agent, phase or "generate", round_num)

            return sanitized
        except asyncio.TimeoutError as e:
            timeout_seconds = time.time() - start_time
            logger.warning("[Autonomic] Agent %s timed out", agent.name)

            # Record timeout failure
            if tracking_id and self.performance_monitor:
                self.performance_monitor.record_completion(
                    tracking_id, success=False, error=f"timeout after {timeout_seconds:.1f}s"
                )

            # Notify immune system of timeout
            if self.immune_system:
                self.immune_system.agent_timeout(agent.name, timeout_seconds)

            # Emit telemetry for timeout
            self._emit_agent_telemetry(
                agent.name, "generate", start_time, success=False, error=e, input_text=prompt
            )

            # Emit agent error event for frontend visibility
            self._emit_agent_error(
                agent.name,
                error_type="timeout",
                message=f"Agent timed out after {timeout_seconds:.1f}s",
                recoverable=True,
                phase=phase,
            )

            # Use theatrical message if chaos director available
            if self.chaos_director:
                return self.chaos_director.timeout_response(agent.name, timeout_seconds).message
            return f"[System: Agent {agent.name} timed out - skipping this turn]"

        except (ConnectionError, OSError) as e:
            # Network/OS errors - log without full traceback
            logger.warning("[Autonomic] Agent %s connection error: %s", agent.name, e)

            # Record connection failure
            if tracking_id and self.performance_monitor:
                self.performance_monitor.record_completion(
                    tracking_id, success=False, error=f"connection error: {e}"
                )

            # Notify immune system of failure
            if self.immune_system:
                self.immune_system.agent_failed(
                    agent.name, f"connection_error:{type(e).__name__}", recoverable=True
                )

            # Emit telemetry for connection error
            self._emit_agent_telemetry(
                agent.name, "generate", start_time, success=False, error=e, input_text=prompt
            )

            # Emit agent error event for frontend visibility
            self._emit_agent_error(
                agent.name,
                error_type="connection",
                message=f"Connection failed: {type(e).__name__}",
                recoverable=True,
                phase=phase,
            )

            # Use theatrical message if chaos director available
            if self.chaos_director:
                return self.chaos_director.connection_response(agent.name).message
            return f"[System: Agent {agent.name} connection failed - skipping this turn]"

        except Exception as e:  # noqa: BLE001 - autonomic containment: agent failures must not crash debate
            # Autonomic containment: convert crashes to valid responses
            logger.exception("[Autonomic] Agent %s failed: %s: %s", agent.name, type(e).__name__, e)

            # Record exception failure
            if tracking_id and self.performance_monitor:
                self.performance_monitor.record_completion(
                    tracking_id, success=False, error=f"{type(e).__name__}: {e}"
                )

            # Notify immune system of failure
            if self.immune_system:
                self.immune_system.agent_failed(
                    agent.name, f"internal_error:{type(e).__name__}", recoverable=False
                )

            # Emit telemetry for exception
            self._emit_agent_telemetry(
                agent.name, "generate", start_time, success=False, error=e, input_text=prompt
            )

            # Emit agent error event for frontend visibility
            self._emit_agent_error(
                agent.name,
                error_type="internal",
                message=f"Internal error: {type(e).__name__}",
                recoverable=False,
                phase=phase,
            )

            # Use theatrical message if chaos director available
            if self.chaos_director:
                return self.chaos_director.internal_error_response(agent.name).message
            return f"[System: Agent {agent.name} encountered an error - skipping this turn]"
        finally:
            # Cancel progress monitoring task
            if progress_task is not None:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass

    async def critique(
        self,
        agent: Agent,
        proposal: str,
        task: str,
        context: list[Message],
        phase: str = "",
        round_num: int = 0,
        target_agent: str | None = None,
    ) -> Critique | None:
        """
        Get critique from an agent with autonomic error handling.

        Args:
            agent: Agent to provide critique
            proposal: Proposal to critique
            task: Task description
            context: Conversation context
            phase: Current debate phase (for telemetry)
            round_num: Current round number (for telemetry)
            target_agent: Name of the agent being critiqued (for fallback messages)

        Returns:
            Critique object or None on failure
        """
        start_time = time.time()
        tracking_id = None
        if self.performance_monitor:
            tracking_id = self.performance_monitor.track_agent_call(
                agent.name, "critique", phase=phase, round_num=round_num
            )

        try:
            result = await agent.critique(proposal, task, context, target_agent=target_agent)
            if self._is_empty_critique(result):
                logger.warning(
                    "[Autonomic] Agent %s returned empty critique, retrying once...", agent.name
                )
                retry_result = await agent.critique(
                    proposal, task, context, target_agent=target_agent
                )
                if not self._is_empty_critique(retry_result):
                    result = retry_result
                else:
                    logger.warning(
                        "[Autonomic] Agent %s retry also returned empty critique", agent.name
                    )
                    if tracking_id and self.performance_monitor:
                        self.performance_monitor.record_completion(
                            tracking_id, success=False, error="empty critique"
                        )
                    self._emit_agent_telemetry(
                        agent.name,
                        "critique",
                        start_time,
                        success=False,
                        output=None,
                        input_text=proposal,
                    )
                    self._emit_agent_error(
                        agent.name,
                        error_type="empty",
                        message="Agent returned empty critique",
                        recoverable=True,
                        phase=phase,
                    )
                    return None
            if result is None:
                if tracking_id and self.performance_monitor:
                    self.performance_monitor.record_completion(
                        tracking_id, success=False, error="empty critique"
                    )
                self._emit_agent_telemetry(
                    agent.name,
                    "critique",
                    start_time,
                    success=False,
                    output=None,
                    input_text=proposal,
                )
                self._emit_agent_error(
                    agent.name,
                    error_type="empty",
                    message="Agent returned no critique",
                    recoverable=True,
                    phase=phase,
                )
                return None
            if tracking_id and self.performance_monitor:
                self.performance_monitor.record_completion(
                    tracking_id, success=True, response=str(result) if result else None
                )
            # Emit telemetry
            self._emit_agent_telemetry(
                agent.name,
                "critique",
                start_time,
                success=True,
                output=str(result) if result else None,
                input_text=proposal,
            )
            # Record per-call cost to DebateCostTracker (best-effort)
            self._record_call_cost(agent, phase or "critique", round_num)
            return result
        except asyncio.TimeoutError as e:
            logger.warning("[Autonomic] Agent %s critique timed out", agent.name)
            if tracking_id and self.performance_monitor:
                self.performance_monitor.record_completion(
                    tracking_id, success=False, error="timeout"
                )
            self._emit_agent_telemetry(
                agent.name, "critique", start_time, success=False, error=e, input_text=proposal
            )
            self._emit_agent_error(
                agent.name,
                error_type="timeout",
                message="Critique timed out",
                recoverable=True,
                phase=phase,
            )
            return None
        except (ConnectionError, OSError) as e:
            logger.warning("[Autonomic] Agent %s critique connection error: %s", agent.name, e)
            if tracking_id and self.performance_monitor:
                self.performance_monitor.record_completion(
                    tracking_id, success=False, error=f"connection error: {e}"
                )
            self._emit_agent_telemetry(
                agent.name, "critique", start_time, success=False, error=e, input_text=proposal
            )
            self._emit_agent_error(
                agent.name,
                error_type="connection",
                message=f"Critique connection error: {type(e).__name__}",
                recoverable=True,
                phase=phase,
            )
            return None
        except Exception as e:  # noqa: BLE001 - autonomic containment: agent failures must not crash debate
            logger.exception("[Autonomic] Agent %s critique failed: %s", agent.name, e)
            if tracking_id and self.performance_monitor:
                self.performance_monitor.record_completion(
                    tracking_id, success=False, error=f"{type(e).__name__}: {e}"
                )
            self._emit_agent_telemetry(
                agent.name, "critique", start_time, success=False, error=e, input_text=proposal
            )
            self._emit_agent_error(
                agent.name,
                error_type="internal",
                message=f"Critique failed: {type(e).__name__}",
                recoverable=False,
                phase=phase,
            )
            return None

    async def vote(
        self,
        agent: Agent,
        proposals: dict[str, str],
        task: str,
        phase: str = "",
        round_num: int = 0,
    ) -> Vote | None:
        """
        Get vote from an agent with autonomic error handling.

        Args:
            agent: Agent to vote
            proposals: Dict of agent_name -> proposal text
            task: Task description
            phase: Current debate phase (for telemetry)
            round_num: Current round number (for telemetry)

        Returns:
            Vote object or None on failure
        """
        start_time = time.time()
        input_text = f"{task}\n{str(proposals)}"
        tracking_id = None
        if self.performance_monitor:
            tracking_id = self.performance_monitor.track_agent_call(
                agent.name, "vote", phase=phase, round_num=round_num
            )

        try:
            result = await agent.vote(proposals, task)
            if result is None:
                if tracking_id and self.performance_monitor:
                    self.performance_monitor.record_completion(
                        tracking_id, success=False, error="empty vote"
                    )
                self._emit_agent_telemetry(
                    agent.name,
                    "vote",
                    start_time,
                    success=False,
                    output=None,
                    input_text=input_text,
                )
                self._emit_agent_error(
                    agent.name,
                    error_type="empty",
                    message="Agent returned no vote",
                    recoverable=True,
                    phase=phase,
                )
                return None
            if not str(getattr(result, "choice", "")).strip():
                if tracking_id and self.performance_monitor:
                    self.performance_monitor.record_completion(
                        tracking_id, success=False, error="empty vote choice"
                    )
                self._emit_agent_telemetry(
                    agent.name,
                    "vote",
                    start_time,
                    success=False,
                    output=None,
                    input_text=input_text,
                )
                self._emit_agent_error(
                    agent.name,
                    error_type="empty",
                    message="Agent returned empty vote choice",
                    recoverable=True,
                    phase=phase,
                )
                return None
            if tracking_id and self.performance_monitor:
                self.performance_monitor.record_completion(
                    tracking_id, success=True, response=str(result) if result else None
                )
            # Emit telemetry
            self._emit_agent_telemetry(
                agent.name,
                "vote",
                start_time,
                success=True,
                output=str(result) if result else None,
                input_text=input_text,
            )
            # Record per-call cost to DebateCostTracker (best-effort)
            self._record_call_cost(agent, phase or "vote", round_num)
            return result
        except asyncio.TimeoutError as e:
            logger.warning("[Autonomic] Agent %s vote timed out", agent.name)
            if tracking_id and self.performance_monitor:
                self.performance_monitor.record_completion(
                    tracking_id, success=False, error="timeout"
                )
            self._emit_agent_telemetry(
                agent.name, "vote", start_time, success=False, error=e, input_text=input_text
            )
            self._emit_agent_error(
                agent.name,
                error_type="timeout",
                message="Vote timed out",
                recoverable=True,
                phase=phase,
            )
            return None
        except (ConnectionError, OSError) as e:
            logger.warning("[Autonomic] Agent %s vote connection error: %s", agent.name, e)
            if tracking_id and self.performance_monitor:
                self.performance_monitor.record_completion(
                    tracking_id, success=False, error=f"connection error: {e}"
                )
            self._emit_agent_telemetry(
                agent.name, "vote", start_time, success=False, error=e, input_text=input_text
            )
            self._emit_agent_error(
                agent.name,
                error_type="connection",
                message=f"Vote connection error: {type(e).__name__}",
                recoverable=True,
                phase=phase,
            )
            return None
        except Exception as e:  # noqa: BLE001 - autonomic containment: agent failures must not crash debate
            logger.exception("[Autonomic] Agent %s vote failed: %s", agent.name, e)
            if tracking_id and self.performance_monitor:
                self.performance_monitor.record_completion(
                    tracking_id, success=False, error=f"{type(e).__name__}: {e}"
                )
            self._emit_agent_telemetry(
                agent.name, "vote", start_time, success=False, error=e, input_text=input_text
            )
            self._emit_agent_error(
                agent.name,
                error_type="internal",
                message=f"Vote failed: {type(e).__name__}",
                recoverable=False,
                phase=phase,
            )
            return None

    async def generate_with_fallback(
        self,
        agent: Agent,
        prompt: str,
        context: list[Message],
        fallback_agents: list[Agent] | None = None,
        max_retries: int = 2,
    ) -> str:
        """
        Generate response with automatic fallback to alternative agents.

        Tries the primary agent first. If it fails, tries fallback agents
        in order. Each retry gets an escalated timeout. If all agents fail,
        returns partial content from streaming buffer if available.

        Args:
            agent: Primary agent to generate response
            prompt: Prompt for the agent
            context: Conversation context
            fallback_agents: List of backup agents to try on failure
            max_retries: Maximum retries per agent before moving to fallback

        Returns:
            Generated response (or system message on total failure)
        """
        fallback_agents = fallback_agents or []
        all_agents = [agent] + fallback_agents
        last_error = None

        for current_agent in all_agents:
            # Skip agents that are circuit-broken
            if self.circuit_breaker and not self.circuit_breaker.is_available(current_agent.name):
                logger.info("[Autonomic] Skipping circuit-broken agent %s", current_agent.name)
                continue

            for attempt in range(max_retries):
                try:
                    timeout = self.get_escalated_timeout(current_agent.name)
                    logger.debug(
                        f"[Autonomic] {current_agent.name} attempt {attempt + 1}/{max_retries}, "
                        f"timeout={timeout:.1f}s"
                    )

                    # Clear streaming buffer before attempt
                    self.streaming_buffer.clear_sync(current_agent.name)

                    raw_output = await asyncio.wait_for(
                        current_agent.generate(prompt, context),
                        timeout=timeout,
                    )

                    # Success - reset retry count and return
                    self.reset_retries(current_agent.name)
                    return OutputSanitizer.sanitize_agent_output(raw_output, current_agent.name)

                except asyncio.TimeoutError:
                    self.record_retry(current_agent.name)
                    if self.circuit_breaker:
                        self.circuit_breaker.record_failure(current_agent.name)

                    # Check for partial content
                    partial = self.streaming_buffer.get_partial(current_agent.name)
                    if partial and len(partial) > 100:
                        logger.warning(
                            "[Autonomic] %s timed out but has %s chars of partial content",
                            current_agent.name,
                            len(partial),
                        )
                        # Could use partial content as fallback

                    logger.warning(
                        "[Autonomic] %s timed out on attempt %s/%s",
                        current_agent.name,
                        attempt + 1,
                        max_retries,
                    )
                    last_error = f"timeout after {timeout:.1f}s"

                except (ConnectionError, OSError) as e:
                    self.record_retry(current_agent.name)
                    if self.circuit_breaker:
                        self.circuit_breaker.record_failure(current_agent.name)
                    logger.warning(
                        "[Autonomic] %s connection error on attempt %s: %s",
                        current_agent.name,
                        attempt + 1,
                        e,
                    )
                    last_error = f"timeout after {timeout:.1f}s"

                except (ConnectionError, OSError) as e:
                    self.record_retry(current_agent.name)
                    if self.circuit_breaker:
                        self.circuit_breaker.record_failure(current_agent.name)
                    logger.warning(
                        "[Autonomic] %s connection error on attempt %s: %s",
                        current_agent.name,
                        attempt + 1,
                        e,
                    )
                    last_error = f"connection_error:{type(e).__name__}"

                except Exception as e:  # noqa: BLE001 - autonomic containment: agent failures must not crash debate
                    self.record_retry(current_agent.name)
                    if self.circuit_breaker:
                        self.circuit_breaker.record_failure(current_agent.name)
                    logger.exception(
                        "[Autonomic] %s failed on attempt %s: %s: %s",
                        current_agent.name,
                        attempt + 1,
                        type(e).__name__,
                        e,
                    )
                    last_error = f"agent_error:{type(e).__name__}"
                    # Don't retry on unexpected errors
                    break

            # Agent exhausted retries, try next fallback
            logger.info("[Autonomic] Moving to fallback after %s failed", current_agent.name)

        # All agents failed - check for any partial content
        for tried_agent in all_agents:
            partial = self.streaming_buffer.get_partial(tried_agent.name)
            if partial and len(partial) > 200:
                logger.info(
                    "[Autonomic] Using partial content (%s chars) from %s",
                    len(partial),
                    tried_agent.name,
                )
                sanitized = OutputSanitizer.sanitize_agent_output(partial, tried_agent.name)
                return f"{sanitized}\n\n[System: Response truncated due to timeout]"

        # Try audience wisdom as final fallback
        wisdom_response = self._get_wisdom_fallback(agent.name)
        if wisdom_response:
            return wisdom_response

        # Total failure
        tried_names = [a.name for a in all_agents]
        logger.error(
            "[Autonomic] All agents failed: %s. Last error: %s",
            tried_names,
            last_error,
        )
        return f"[System: All agents failed ({', '.join(tried_names)}). Please retry or check agent configuration.]"


__all__ = ["AutonomicExecutor", "StreamingContentBuffer"]
