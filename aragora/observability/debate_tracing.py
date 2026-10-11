"""
Distributed tracing for debate orchestration.

Provides lightweight tracing with correlation IDs, spans, and structured
attributes for observability. Compatible with OpenTelemetry when available.

Usage:
    from aragora.observability.debate_tracing import Tracer, get_tracer

    tracer = get_tracer()
    with tracer.debate_context(debate_id), tracer.span("debate.execute") as span:
        span.set_attribute("agents", len(agents))
        result = await run_debate()
        span.set_attribute("success", True)
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from contextlib import AbstractContextManager
from collections.abc import Callable, Generator

if TYPE_CHECKING:
    from aragora.logging_config import StructuredLogger

# Use structured logging if available
_structured_logger: StructuredLogger | None = None
set_context: Callable[..., None] | None = None
_log_scope: Callable[..., AbstractContextManager[Any]] | None = None
try:
    from aragora import logging_config as _logging_config
except ImportError:
    pass
else:
    _structured_logger = _logging_config.get_logger(__name__)
    set_context = _logging_config.set_context
    _log_scope = _logging_config.LogContext

logger = logging.getLogger(__name__)

# Context variable for current span propagation
_current_span: contextvars.ContextVar[Span | None] = contextvars.ContextVar(
    "current_span", default=None
)

# Context variable for debate correlation ID
_debate_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "debate_context", default={}
)


def generate_trace_id() -> str:
    """Generate a unique trace ID (32-char hex)."""
    return uuid.uuid4().hex


def generate_span_id() -> str:
    """Generate a unique span ID (16-char hex)."""
    return uuid.uuid4().hex[:16]


@dataclass
class SpanContext:
    """Immutable context for a span, used for propagation."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None


@dataclass
class Span:
    """A single tracing span representing an operation."""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_time: float
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str = "OK"
    error: str | None = None

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self.attributes[key] = value

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        """Set multiple span attributes."""
        self.attributes.update(attributes)

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Add an event to the span."""
        self.events.append(
            {
                "name": name,
                "timestamp": time.time(),
                "attributes": attributes or {},
            }
        )

    def record_exception(self, exc: Exception) -> None:
        """Record an exception in the span."""
        self.status = "ERROR"
        self.error = f"{type(exc).__name__}: {exc}"
        self.add_event(
            "exception",
            {
                "exception.type": type(exc).__name__,
                "exception.message": str(exc),
            },
        )

    def get_span_context(self) -> SpanContext:
        """Get the immutable span context for propagation."""
        return SpanContext(
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
        )

    @property
    def duration_ms(self) -> float | None:
        """Get span duration in milliseconds."""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        """Convert span to dictionary for logging/export."""
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "end_time": (
                datetime.fromtimestamp(self.end_time).isoformat() if self.end_time else None
            ),
            "duration_ms": self.duration_ms,
            "attributes": self.attributes,
            "events": self.events,
            "status": self.status,
            "error": self.error,
        }


class SpanRecorder:
    """Records completed spans for analysis/export."""

    def __init__(self, max_spans: int = 10000):
        self.spans: list[Span] = []
        self.max_spans = max_spans
        self._lock = None  # Lock created lazily if needed

    def record(self, span: Span) -> None:
        """Record a completed span."""
        self.spans.append(span)
        # Evict old spans if over limit
        if len(self.spans) > self.max_spans:
            self.spans = self.spans[-self.max_spans // 2 :]

    def get_spans_by_trace(self, trace_id: str) -> list[Span]:
        """Get all spans for a trace."""
        return [s for s in self.spans if s.trace_id == trace_id]

    def get_recent_spans(self, limit: int = 100) -> list[Span]:
        """Get most recent spans."""
        return self.spans[-limit:]

    def clear(self) -> None:
        """Clear all recorded spans."""
        self.spans.clear()


# Global span recorder
_recorder = SpanRecorder()


class Tracer:
    """
    Distributed tracer for debate orchestration.

    Creates and manages spans for tracing operations through the debate
    execution lifecycle.
    """

    def __init__(
        self,
        service_name: str = "aragora",
        recorder: SpanRecorder | None = None,
        log_spans: bool = True,
    ):
        self.service_name = service_name
        self.recorder = recorder or _recorder
        self.log_spans = log_spans

    def get_current_span(self) -> Span | None:
        """Get the current active span from context."""
        return _current_span.get()

    def get_current_trace_id(self) -> str | None:
        """Get the current trace ID if available."""
        span = self.get_current_span()
        return span.trace_id if span else None

    @contextmanager
    def debate_context(self, debate_id: str, **extra: Any) -> Generator[dict[str, Any], None, None]:
        """Bind the debate correlation context for a ``with`` block.

        Unlike :func:`set_debate_context`, the previous debate context and log
        context fields are restored on exit, including when the block raises.
        """
        ctx = {"debate_id": debate_id, **extra}
        token = _debate_context.set(ctx)
        try:
            log_scope = (
                _log_scope(debate_id=debate_id, **extra)
                if _log_scope is not None
                else nullcontext()
            )
            with log_scope:
                yield ctx
        finally:
            _debate_context.reset(token)

    @contextmanager
    def span(
        self,
        name: str,
        parent: Span | None = None,
        trace_id: str | None = None,
        **attributes: Any,
    ) -> Generator[Span, None, None]:
        """
        Create a span context manager.

        Args:
            name: Span name (e.g., "debate.execute", "agent.generate")
            parent: Optional parent span (uses current span if not provided)
            trace_id: Optional trace ID (generates new if not provided)
            **attributes: Initial span attributes

        Usage:
            with tracer.span("debate.round", round_number=1) as span:
                # ... do work ...
                span.set_attribute("result", "success")
        """
        # Determine parent and trace context
        if parent is None:
            parent = _current_span.get()

        if trace_id is None and parent:
            trace_id = parent.trace_id
        elif trace_id is None:
            trace_id = generate_trace_id()

        parent_span_id = parent.span_id if parent else None

        # Create new span
        span = Span(
            name=name,
            trace_id=trace_id,
            span_id=generate_span_id(),
            parent_span_id=parent_span_id,
            start_time=time.time(),
            attributes={
                "service.name": self.service_name,
                **attributes,
            },
        )

        # Set as current span
        token = _current_span.set(span)

        try:
            yield span
            span.status = "OK"
        except Exception as e:  # noqa: BLE001 - tracing context manager must record all exceptions before re-raising
            span.record_exception(e)
            raise
        finally:
            span.end_time = time.time()
            _current_span.reset(token)

            # Record and optionally log
            self.recorder.record(span)
            if self.log_spans:
                self._log_span(span)

    def _log_span(self, span: Span) -> None:
        """Log span completion with structured attributes."""
        # Build structured fields from span
        fields = {
            "span_name": span.name,
            "trace_id": span.trace_id,
            "span_id": span.span_id,
            "duration_ms": round(span.duration_ms, 2) if span.duration_ms else 0,
            "status": span.status,
        }

        # Add parent span if present
        if span.parent_span_id:
            fields["parent_span_id"] = span.parent_span_id

        # Add span attributes (excluding service.name)
        for k, v in span.attributes.items():
            if k != "service.name" and v is not None:
                fields[k] = v

        # Add error info if present
        if span.error:
            fields["error"] = span.error

        # Use structured logger if available
        if _structured_logger:
            if span.status == "OK":
                _structured_logger.debug("Span completed", **fields)
            else:
                _structured_logger.warning("Span completed with error", **fields)
        else:
            # Fallback to plain logging
            level = logging.DEBUG if span.status == "OK" else logging.WARNING
            attrs = " ".join(f"{k}={v}" for k, v in fields.items())
            logger.log(level, "span_complete %s", attrs)


# Global tracer instance
_tracer: Tracer | None = None


def get_tracer(service_name: str = "aragora") -> Tracer:
    """Get or create the global tracer instance."""
    global _tracer
    if _tracer is None:
        _tracer = Tracer(service_name=service_name)
    return _tracer


def set_tracer(tracer: Tracer) -> None:
    """Set the global tracer instance (for testing/custom configuration)."""
    global _tracer
    _tracer = tracer


# Debate context management for correlation IDs


def set_debate_context(debate_id: str, **extra) -> None:
    """Set the current debate context for correlation."""
    ctx = {"debate_id": debate_id, **extra}
    _debate_context.set(ctx)

    # Also set logging context for automatic field injection
    if set_context is not None:
        set_context(debate_id=debate_id, **extra)


def get_debate_context() -> dict[str, Any]:
    """Get the current debate context."""
    return _debate_context.get()


def get_debate_id() -> str | None:
    """Get the current debate ID from context."""
    return get_debate_context().get("debate_id")


def with_debate_context(debate_id: str) -> Callable[[Callable], Callable]:
    """Decorator to set debate context for a function."""

    def decorator(func: Callable) -> Callable:
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            set_debate_context(debate_id)
            return await func(*args, **kwargs)

        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            set_debate_context(debate_id)
            return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# Convenience decorators for common operations


def trace_agent_call(operation: str) -> Callable[[Callable], Callable]:
    """Decorator for tracing agent calls (proposal, critique, vote, etc.)."""

    def decorator(func: Callable) -> Callable:
        async def async_wrapper(self: Any, agent: Any, *args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.span(
                f"agent.{operation}",
                agent_name=getattr(agent, "name", str(agent)),
                agent_model=getattr(agent, "model", "unknown"),
                operation=operation,
            ) as span:
                try:
                    result = await func(self, agent, *args, **kwargs)
                    span.set_attribute("response_length", len(result) if result else 0)
                    span.set_attribute("success", True)
                    return result
                except Exception:  # noqa: BLE001 - Re-raised after recording span attribute
                    span.set_attribute("success", False)
                    logger.warning(
                        "Agent %s call failed during %s operation",
                        getattr(agent, "name", str(agent)),
                        operation,
                        exc_info=True,
                    )
                    raise

        def sync_wrapper(self: Any, agent: Any, *args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.span(
                f"agent.{operation}",
                agent_name=getattr(agent, "name", str(agent)),
                agent_model=getattr(agent, "model", "unknown"),
                operation=operation,
            ) as span:
                try:
                    result = func(self, agent, *args, **kwargs)
                    span.set_attribute("response_length", len(result) if result else 0)
                    span.set_attribute("success", True)
                    return result
                except Exception:  # noqa: BLE001 - Re-raised after recording span attribute
                    span.set_attribute("success", False)
                    logger.warning(
                        "Agent %s call failed during %s operation",
                        getattr(agent, "name", str(agent)),
                        operation,
                        exc_info=True,
                    )
                    raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def trace_round(round_num: int) -> AbstractContextManager[Span]:
    """Context manager for tracing a debate round."""
    tracer = get_tracer()
    return tracer.span("debate.round", round_number=round_num)


def trace_phase(phase: str, round_num: int) -> AbstractContextManager[Span]:
    """Context manager for tracing a debate phase (proposal, critique, etc.)."""
    tracer = get_tracer()
    return tracer.span(f"debate.phase.{phase}", round_number=round_num, phase=phase)


# Metrics tracking


@dataclass
class DebateMetrics:
    """Aggregated metrics for a debate."""

    debate_id: str
    total_duration_ms: float = 0
    rounds_completed: int = 0
    agent_calls: int = 0
    agent_errors: int = 0
    agent_timeouts: int = 0
    consensus_reached: bool = False
    consensus_confidence: float = 0.0
    per_agent_latencies: dict[str, list[float]] = field(default_factory=dict)

    def record_agent_latency(self, agent_name: str, latency_ms: float) -> None:
        """Record an agent call latency."""
        if agent_name not in self.per_agent_latencies:
            self.per_agent_latencies[agent_name] = []
        self.per_agent_latencies[agent_name].append(latency_ms)
        self.agent_calls += 1

    def get_agent_avg_latency(self, agent_name: str) -> float:
        """Get average latency for an agent."""
        latencies = self.per_agent_latencies.get(agent_name, [])
        return sum(latencies) / len(latencies) if latencies else 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/export."""
        return {
            "debate_id": self.debate_id,
            "total_duration_ms": self.total_duration_ms,
            "rounds_completed": self.rounds_completed,
            "agent_calls": self.agent_calls,
            "agent_errors": self.agent_errors,
            "agent_timeouts": self.agent_timeouts,
            "consensus_reached": self.consensus_reached,
            "consensus_confidence": self.consensus_confidence,
            "per_agent_avg_latencies": {
                agent: self.get_agent_avg_latency(agent) for agent in self.per_agent_latencies
            },
        }


# Metrics storage (thread-safe)
_debate_metrics: dict[str, DebateMetrics] = {}
_debate_metrics_lock = threading.Lock()


def get_metrics(debate_id: str) -> DebateMetrics:
    """Get or create metrics for a debate (thread-safe)."""
    with _debate_metrics_lock:
        if debate_id not in _debate_metrics:
            _debate_metrics[debate_id] = DebateMetrics(debate_id=debate_id)
        return _debate_metrics[debate_id]


def clear_metrics(debate_id: str | None = None) -> None:
    """Clear metrics for a debate or all debates (thread-safe)."""
    with _debate_metrics_lock:
        if debate_id:
            _debate_metrics.pop(debate_id, None)
        else:
            _debate_metrics.clear()
