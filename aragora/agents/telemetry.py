"""
Agent Telemetry Decorator - Observable metrics for agent operations.

Provides comprehensive telemetry via decorator pattern:
- Timing metrics (start, end, duration)
- Token usage tracking (input/output)
- Success/failure states
- Integration with Prometheus, ImmuneSystem, and Blackbox

Inspired by nomic loop debate consensus on observability.
"""

from __future__ import annotations

__all__ = [
    "AgentTelemetry",
    "TelemetryContext",
    "register_telemetry_collector",
    "unregister_telemetry_collector",
    "setup_default_collectors",
    "with_telemetry",
    "get_telemetry_stats",
    "reset_telemetry",
]

import asyncio
import functools
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, ParamSpec, TypeVar, cast
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")
AsyncFunc = Callable[P, Awaitable[T]]


def _get_callable_name(func: Callable) -> str:
    """Safely get a callable's name for logging.

    Handles functions, methods, lambdas, partials, and other callables
    that may not have __name__.
    """
    if hasattr(func, "__name__"):
        return func.__name__
    if hasattr(func, "__class__"):
        return func.__class__.__name__
    return repr(func)


@dataclass
class AgentTelemetry:
    """Telemetry data for a single agent operation."""

    agent_name: str
    operation: str  # "generate", "critique", "vote", "revise"
    start_time: float
    end_time: float = 0.0
    duration_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    input_chars: int = 0
    output_chars: int = 0
    success: bool = True
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict = field(default_factory=dict)

    def complete(self, success: bool = True, error: Exception | None = None) -> None:
        """Mark the operation as complete."""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.success = success
        if error:
            self.error_type = type(error).__name__
            self.error_message = str(error)[:200]

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count from text (~4 chars per token)."""
        return len(text) // 4 if text else 0


# Global telemetry collectors (thread-safe)
_telemetry_lock = threading.Lock()
_telemetry_collectors: list[Callable[[AgentTelemetry], None]] = []


def register_telemetry_collector(collector: Callable[[AgentTelemetry], None]) -> None:
    """Register a collector to receive telemetry events. Thread-safe.

    Collectors receive AgentTelemetry objects after each operation completes.

    Example:
        def my_collector(telemetry: AgentTelemetry):
            print(f"{telemetry.agent_name}: {telemetry.duration_ms}ms")

        register_telemetry_collector(my_collector)
    """
    with _telemetry_lock:
        if collector not in _telemetry_collectors:
            _telemetry_collectors.append(collector)
            logger.debug("telemetry_collector_registered total=%s", len(_telemetry_collectors))


def unregister_telemetry_collector(collector: Callable[[AgentTelemetry], None]) -> None:
    """Unregister a telemetry collector. Thread-safe."""
    with _telemetry_lock:
        if collector in _telemetry_collectors:
            _telemetry_collectors.remove(collector)


def _emit_telemetry(telemetry: AgentTelemetry) -> None:
    """Emit telemetry to all registered collectors. Thread-safe."""
    # Copy under lock, iterate outside to avoid holding lock during callbacks
    with _telemetry_lock:
        collectors = _telemetry_collectors.copy()
    for collector in collectors:
        try:
            collector(telemetry)
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.warning(
                "telemetry_collector_error collector=%s error=%s", _get_callable_name(collector), e
            )


def _default_prometheus_collector(telemetry: AgentTelemetry) -> None:
    """Default collector that records to Prometheus metrics."""
    try:
        from aragora.observability.prometheus import (
            record_agent_failure,
            record_agent_generation,
        )

        # Record generation time
        record_agent_generation(
            agent_type=telemetry.agent_name,
            model=telemetry.metadata.get("model", "unknown"),
            duration_seconds=telemetry.duration_ms / 1000,
        )

        # Record failure if applicable
        if not telemetry.success and telemetry.error_type:
            record_agent_failure(
                agent_type=telemetry.agent_name,
                error_type=telemetry.error_type,
            )
    except ImportError:
        logger.debug("prometheus_client unavailable, skipping agent telemetry metrics")


def _default_immune_system_collector(telemetry: AgentTelemetry) -> None:
    """Default collector that emits to the immune system."""
    try:
        from aragora.debate.immune_system import get_immune_system

        immune = get_immune_system()

        if telemetry.success:
            immune.agent_completed(
                agent_name=telemetry.agent_name,
                response_ms=telemetry.duration_ms,
                success=True,
            )
        else:
            if telemetry.error_type == "TimeoutError":
                immune.agent_timeout(
                    agent_name=telemetry.agent_name,
                    timeout_seconds=telemetry.duration_ms / 1000,
                    context={"operation": telemetry.operation},
                )
            else:
                immune.agent_failed(
                    agent_name=telemetry.agent_name,
                    error=telemetry.error_message or "Unknown error",
                    recoverable=True,
                )
    except ImportError:
        logger.debug("immune_system unavailable, skipping agent telemetry collector")


def _default_blackbox_collector(telemetry: AgentTelemetry) -> None:
    """Default collector that records to the blackbox."""
    try:
        from aragora.debate.blackbox import get_blackbox

        # Use agent telemetry session or default session
        session_id = getattr(telemetry, "session_id", "default_telemetry")
        blackbox = get_blackbox(session_id)

        event_type = "agent_success" if telemetry.success else "agent_failure"
        blackbox.record_event(
            event_type=event_type,
            component=telemetry.agent_name,
            data={
                "operation": telemetry.operation,
                "duration_ms": telemetry.duration_ms,
                "success": telemetry.success,
                "error_type": telemetry.error_type,
                "input_tokens": telemetry.input_tokens,
                "output_tokens": telemetry.output_tokens,
            },
        )
    except ImportError:
        logger.debug("blackbox unavailable, skipping agent telemetry collector")


def setup_default_collectors() -> None:
    """Set up the default telemetry collectors."""
    register_telemetry_collector(_default_prometheus_collector)
    register_telemetry_collector(_default_immune_system_collector)
    register_telemetry_collector(_default_blackbox_collector)
    logger.info("telemetry_default_collectors_registered")


def with_telemetry(
    operation: str = "generate",
    extract_input: Callable[..., str] | None = None,
    extract_output: Callable[[Any], str] | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator wrapping agent operations with telemetry.

    Args:
        operation: Operation type ("generate", "critique", "vote", "revise")
        extract_input: Optional function to extract input text from args
        extract_output: Optional function to extract output text from result

    Returns:
        Decorated function with telemetry instrumentation

    Usage:
        class MyAgent:
            @with_telemetry("generate")
            async def generate(self, prompt: str) -> str:
                return await self._call_model(prompt)

            @with_telemetry("critique", extract_input=lambda self, p, t, c: t)
            async def critique(self, prompt: str, target: str, context: list):
                return await self._call_model(prompt)
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Extract agent name from self
            agent_name = "unknown"
            if args and hasattr(args[0], "name"):
                agent_name = args[0].name

            # Extract model from self
            model = "unknown"
            if args and hasattr(args[0], "model"):
                model = args[0].model

            # Create telemetry record
            telemetry = AgentTelemetry(
                agent_name=agent_name,
                operation=operation,
                start_time=time.time(),
                metadata={"model": model},
            )

            # Extract input tokens if function provided
            if extract_input:
                try:
                    input_text = extract_input(*args, **kwargs)
                    telemetry.input_chars = len(input_text) if input_text else 0
                    telemetry.input_tokens = AgentTelemetry.estimate_tokens(input_text)
                except (TypeError, AttributeError, IndexError, KeyError) as e:
                    logger.debug("telemetry_input_extraction_failed: %s", e)

            try:
                result = await cast(Awaitable[T], func(*args, **kwargs))

                # Extract output tokens if function provided
                if extract_output:
                    try:
                        output_text = extract_output(result)
                        telemetry.output_chars = len(output_text) if output_text else 0
                        telemetry.output_tokens = AgentTelemetry.estimate_tokens(output_text)
                    except (TypeError, AttributeError, IndexError, KeyError) as e:
                        logger.debug("telemetry_output_extraction_failed: %s", e)
                elif isinstance(result, str):
                    telemetry.output_chars = len(result)
                    telemetry.output_tokens = AgentTelemetry.estimate_tokens(result)

                telemetry.complete(success=True)
                return result

            except BaseException as e:
                # BaseException includes Exception; AgentTelemetry.complete accepts Exception
                # but we catch BaseException to ensure telemetry is recorded for all failures
                telemetry.complete(success=False, error=e if isinstance(e, Exception) else None)
                raise

            finally:
                _emit_telemetry(telemetry)
                logger.debug(
                    f"telemetry agent={agent_name} op={operation} "
                    f"duration={telemetry.duration_ms:.0f}ms success={telemetry.success}"
                )

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Extract agent name from self
            agent_name = "unknown"
            if args and hasattr(args[0], "name"):
                agent_name = args[0].name

            model = "unknown"
            if args and hasattr(args[0], "model"):
                model = args[0].model

            telemetry = AgentTelemetry(
                agent_name=agent_name,
                operation=operation,
                start_time=time.time(),
                metadata={"model": model},
            )

            if extract_input:
                try:
                    input_text = extract_input(*args, **kwargs)
                    telemetry.input_chars = len(input_text) if input_text else 0
                    telemetry.input_tokens = AgentTelemetry.estimate_tokens(input_text)
                except (TypeError, AttributeError, IndexError, KeyError) as e:
                    logger.debug("telemetry_input_extraction_failed: %s", e)

            try:
                result = func(*args, **kwargs)

                if extract_output:
                    try:
                        output_text = extract_output(result)
                        telemetry.output_chars = len(output_text) if output_text else 0
                        telemetry.output_tokens = AgentTelemetry.estimate_tokens(output_text)
                    except (TypeError, AttributeError, IndexError, KeyError) as e:
                        logger.debug("telemetry_output_extraction_failed: %s", e)
                elif isinstance(result, str):
                    telemetry.output_chars = len(result)
                    telemetry.output_tokens = AgentTelemetry.estimate_tokens(result)

                telemetry.complete(success=True)
                return result

            except BaseException as e:
                # BaseException includes Exception; AgentTelemetry.complete accepts Exception
                # but we catch BaseException to ensure telemetry is recorded for all failures
                telemetry.complete(success=False, error=e if isinstance(e, Exception) else None)
                raise

            finally:
                _emit_telemetry(telemetry)

        # Check if function is async
        if asyncio.iscoroutinefunction(func):
            return cast(Callable[P, T], async_wrapper)
        return cast(Callable[P, T], sync_wrapper)

    return decorator


class TelemetryContext:
    """Context manager for manual telemetry recording.

    Usage:
        with TelemetryContext("claude", "generate") as ctx:
            result = await agent.generate(prompt)
            ctx.set_output(result)
    """

    def __init__(self, agent_name: str, operation: str, model: str = "unknown"):
        self.telemetry = AgentTelemetry(
            agent_name=agent_name,
            operation=operation,
            start_time=time.time(),
            metadata={"model": model},
        )

    def set_input(self, text: str) -> None:
        """Set input text for token estimation."""
        self.telemetry.input_chars = len(text)
        self.telemetry.input_tokens = AgentTelemetry.estimate_tokens(text)

    def set_output(self, text: str) -> None:
        """Set output text for token estimation."""
        self.telemetry.output_chars = len(text)
        self.telemetry.output_tokens = AgentTelemetry.estimate_tokens(text)

    def set_error(self, error: Exception) -> None:
        """Record an error."""
        self.telemetry.error_type = type(error).__name__
        self.telemetry.error_message = str(error)[:200]

    def __enter__(self) -> TelemetryContext:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        success = exc_type is None
        if exc_val:
            self.set_error(exc_val)
        self.telemetry.complete(success=success)
        _emit_telemetry(self.telemetry)


def get_telemetry_stats() -> dict:
    """Get telemetry statistics summary. Thread-safe."""
    with _telemetry_lock:
        return {
            "collectors_count": len(_telemetry_collectors),
            "collectors": [_get_callable_name(c) for c in _telemetry_collectors],
        }


def reset_telemetry() -> None:
    """Reset telemetry system (for testing). Thread-safe."""
    global _telemetry_collectors
    with _telemetry_lock:
        _telemetry_collectors = []
