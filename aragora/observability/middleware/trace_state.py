"""Trace context state shared by the tracing middleware and the OpenTelemetry bridge.

Holds the context variables, ID generators, ``Span`` and ``trace_context`` so
that both the HTTP tracing middleware and the OpenTelemetry bridge can consume
them without depending on each other. Export of finished spans is delegated to
whichever exporter the bridge registers via ``set_span_exporter``.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Context variables for trace propagation
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_span_id: ContextVar[str | None] = ContextVar("span_id", default=None)
_parent_span_id: ContextVar[str | None] = ContextVar("parent_span_id", default=None)
_span_stack: ContextVar[list[Span]] = ContextVar("span_stack", default=[])


def generate_trace_id() -> str:
    """Generate a unique trace ID.

    Uses UUID4 with hex encoding for 32-character trace IDs,
    compatible with most tracing systems.

    Returns:
        32-character hex trace ID
    """
    return uuid.uuid4().hex


def generate_span_id() -> str:
    """Generate a unique span ID.

    Uses UUID4 truncated to 16 characters for span IDs,
    following OpenTelemetry conventions.

    Returns:
        16-character hex span ID
    """
    return uuid.uuid4().hex[:16]


def get_trace_id() -> str | None:
    """Get the current trace ID.

    Returns:
        Current trace ID or None if not in trace context
    """
    return _trace_id.get()


def get_span_id() -> str | None:
    """Get the current span ID.

    Returns:
        Current span ID or None if not in trace context
    """
    return _span_id.get()


def get_parent_span_id() -> str | None:
    """Get the parent span ID.

    Returns:
        Parent span ID or None if no parent
    """
    return _parent_span_id.get()


def set_trace_id(trace_id: str) -> None:
    """Set the current trace ID.

    Args:
        trace_id: The trace ID to set
    """
    _trace_id.set(trace_id)


def set_span_id(span_id: str) -> None:
    """Set the current span ID.

    Args:
        span_id: The span ID to set
    """
    _span_id.set(span_id)


@dataclass
class Span:
    """Represents a single operation within a trace.

    Tracks timing, tags, and events for observability.
    """

    trace_id: str
    span_id: str
    operation: str
    parent_span_id: str | None = None
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    tags: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str = "ok"
    error: str | None = None

    def set_tag(self, key: str, value: Any) -> None:
        """Set a tag on the span.

        Args:
            key: Tag name
            value: Tag value
        """
        self.tags[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Add an event to the span.

        Args:
            name: Event name
            attributes: Optional event attributes
        """
        self.events.append(
            {
                "name": name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "attributes": attributes or {},
            }
        )

    def set_error(self, error: Exception) -> None:
        """Mark the span as errored.

        Args:
            error: The exception that occurred
        """
        self.status = "error"
        self.error = f"{type(error).__name__}: {str(error)}"
        self.add_event(
            "exception",
            {
                "type": type(error).__name__,
                "message": str(error),
            },
        )

    def finish(self) -> None:
        """Mark the span as finished and hand it to the registered exporter, if any."""
        self.end_time = time.time()
        exporter = _span_exporter
        if exporter is not None:
            exporter(self)

    @property
    def duration_ms(self) -> float:
        """Get span duration in milliseconds."""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        """Convert span to dictionary for logging/export."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "operation": self.operation,
            "start_time": datetime.fromtimestamp(self.start_time, tz=timezone.utc).isoformat(),
            "end_time": (
                datetime.fromtimestamp(self.end_time, tz=timezone.utc).isoformat()
                if self.end_time
                else None
            ),
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "error": self.error,
            "tags": self.tags,
            "events": self.events,
        }


@contextmanager
def trace_context(
    operation: str,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
) -> Generator[Span, None, None]:
    """Context manager for creating a traced operation.

    Creates a new span for the operation and propagates trace context.

    Args:
        operation: Name of the operation being traced
        trace_id: Optional trace ID (uses current or generates new if not set)
        parent_span_id: Optional parent span ID for nested spans

    Yields:
        Span object for the current operation

    Example:
        with trace_context("debate.create") as span:
            span.set_tag("agents", ["claude", "gpt4"])
            debate = await create_debate(...)
            span.set_tag("debate_id", debate.id)
    """
    # Get or generate trace ID
    current_trace_id = trace_id or get_trace_id() or generate_trace_id()

    # Get parent span ID (current span becomes parent for this new span)
    current_span_id = get_span_id()
    actual_parent = parent_span_id or current_span_id

    # Generate new span ID
    new_span_id = generate_span_id()

    # Create span
    span = Span(
        trace_id=current_trace_id,
        span_id=new_span_id,
        operation=operation,
        parent_span_id=actual_parent,
    )

    # Push span to stack
    stack = _span_stack.get().copy()
    stack.append(span)

    # Set context
    old_trace = _trace_id.set(current_trace_id)
    old_span = _span_id.set(new_span_id)
    old_parent = _parent_span_id.set(actual_parent)
    old_stack = _span_stack.set(stack)

    try:
        yield span
    except BaseException as e:
        if isinstance(e, Exception):
            span.set_error(e)
        raise
    finally:
        span.finish()

        # Pop span from stack
        stack = _span_stack.get().copy()
        if stack:
            stack.pop()

        # Restore context
        _trace_id.reset(old_trace)
        _span_id.reset(old_span)
        _parent_span_id.reset(old_parent)
        _span_stack.reset(old_stack)


_span_exporter: Callable[[Span], None] | None = None


def set_span_exporter(exporter: Callable[[Span], None] | None) -> None:
    """Register the callable that receives every finished span (``None`` clears it)."""
    global _span_exporter
    _span_exporter = exporter


__all__ = [
    "Span",
    "generate_span_id",
    "generate_trace_id",
    "get_parent_span_id",
    "get_span_id",
    "get_trace_id",
    "set_span_exporter",
    "set_span_id",
    "set_trace_id",
    "trace_context",
]
