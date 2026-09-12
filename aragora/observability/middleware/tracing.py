"""
Distributed Tracing Middleware.

Provides request tracing for observability:
- Generates unique trace IDs for each request
- Propagates trace IDs via X-Trace-ID header
- Integrates with structured logging
- Supports parent/child span relationships
- Exports spans to OpenTelemetry collectors (Jaeger, Zipkin, OTLP, Datadog)

Usage:
    from aragora.observability.middleware.tracing import (
        TracingMiddleware,
        get_trace_id,
        get_span_id,
        trace_context,
    )

    # Get current trace ID
    trace_id = get_trace_id()

    # Create child span
    with trace_context(operation="debate.create") as span:
        # ... operation code ...
        span.set_tag("debate_id", debate_id)

OpenTelemetry Integration:
    Set OTEL_EXPORTER_OTLP_ENDPOINT to enable automatic span export.
    See docs/OBSERVABILITY.md for configuration details.
"""

from __future__ import annotations

from functools import wraps
from typing import Any
from collections.abc import Callable

from aragora.observability.middleware.trace_state import (
    Span,
    generate_span_id,
    generate_trace_id,
    get_parent_span_id,
    get_span_id,
    get_trace_id,
    set_span_id,
    set_trace_id,
    trace_context,
)

# Context variables live in ``trace_state``; re-exported here because callers
# and tests reset them through this module.
from aragora.observability.middleware.trace_state import (  # noqa: F401
    _parent_span_id,
    _span_id,
    _span_stack,
    _trace_id,
)

# Trace ID header names (W3C Trace Context compatible)
TRACE_ID_HEADER = "X-Trace-ID"
SPAN_ID_HEADER = "X-Span-ID"
PARENT_SPAN_HEADER = "X-Parent-Span-ID"

# W3C Trace Context header (if using OpenTelemetry format)
TRACEPARENT_HEADER = "traceparent"


def traced(operation: str | None = None) -> Callable:
    """Decorator for tracing function execution.

    Args:
        operation: Operation name (defaults to function name)

    Returns:
        Decorator function

    Example:
        @traced("debate.create")
        async def create_debate(task: str) -> Debate:
            ...

        @traced()  # Uses function name as operation
        def process_message(msg: dict) -> None:
            ...
    """

    def decorator(func: Callable) -> Callable:
        op_name = operation or func.__name__

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            with trace_context(op_name) as span:
                try:
                    return await func(*args, **kwargs)
                except BaseException as e:
                    span.set_error(e)
                    raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with trace_context(op_name) as span:
                try:
                    return func(*args, **kwargs)
                except BaseException as e:
                    span.set_error(e)
                    raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


class TracingMiddleware:
    """HTTP middleware for distributed tracing.

    Extracts or generates trace IDs and propagates them through the request.

    Usage:
        middleware = TracingMiddleware()

        # In request handling
        trace_id = middleware.extract_trace_id(request_headers)
        middleware.set_response_headers(response_headers, trace_id)
    """

    def __init__(self, service_name: str = "aragora"):
        """Initialize the tracing middleware.

        Args:
            service_name: Name of the service for span tagging
        """
        self.service_name = service_name

    def extract_trace_id(self, headers: dict[str, str]) -> str:
        """Extract trace ID from request headers or generate new one.

        Supports multiple header formats:
        - X-Trace-ID (custom)
        - traceparent (W3C Trace Context)

        Args:
            headers: Request headers dictionary

        Returns:
            Trace ID (extracted or generated)
        """
        # Check custom header first
        trace_id = headers.get(TRACE_ID_HEADER) or headers.get(TRACE_ID_HEADER.lower())
        if trace_id:
            return trace_id

        # Check W3C traceparent header
        traceparent = headers.get(TRACEPARENT_HEADER) or headers.get(TRACEPARENT_HEADER.lower())
        if traceparent:
            # Format: version-trace_id-parent_id-flags
            parts = traceparent.split("-")
            if len(parts) >= 2:
                return parts[1]

        # Generate new trace ID
        return generate_trace_id()

    def extract_parent_span_id(self, headers: dict[str, str]) -> str | None:
        """Extract parent span ID from request headers.

        Args:
            headers: Request headers dictionary

        Returns:
            Parent span ID or None
        """
        parent_id = headers.get(PARENT_SPAN_HEADER) or headers.get(PARENT_SPAN_HEADER.lower())
        if parent_id:
            return parent_id

        # Check W3C traceparent header
        traceparent = headers.get(TRACEPARENT_HEADER) or headers.get(TRACEPARENT_HEADER.lower())
        if traceparent:
            parts = traceparent.split("-")
            if len(parts) >= 3:
                return parts[2]

        return None

    def set_response_headers(
        self,
        headers: dict[str, str],
        trace_id: str,
        span_id: str | None = None,
    ) -> None:
        """Add tracing headers to response.

        Args:
            headers: Response headers dictionary (modified in place)
            trace_id: Trace ID to include
            span_id: Optional span ID to include
        """
        headers[TRACE_ID_HEADER] = trace_id
        if span_id:
            headers[SPAN_ID_HEADER] = span_id

    def start_request_span(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
    ) -> Span:
        """Start a span for an incoming HTTP request.

        Args:
            method: HTTP method
            path: Request path
            headers: Request headers

        Returns:
            New span for the request
        """
        trace_id = self.extract_trace_id(headers)
        parent_span_id = self.extract_parent_span_id(headers)
        span_id = generate_span_id()

        # Set global context
        set_trace_id(trace_id)
        set_span_id(span_id)

        # Create span
        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            operation=f"{method} {path}",
            parent_span_id=parent_span_id,
        )

        span.set_tag("http.method", method)
        span.set_tag("http.path", path)
        span.set_tag("service", self.service_name)

        return span

    def finish_request_span(
        self,
        span: Span,
        status_code: int,
        error: Exception | None = None,
    ) -> None:
        """Finish a request span.

        Args:
            span: The span to finish
            status_code: HTTP response status code
            error: Optional exception if request failed
        """
        span.set_tag("http.status_code", status_code)

        if error:
            span.set_error(error)
        elif status_code >= 400:
            span.status = "error"
            span.error = f"HTTP {status_code}"

        span.finish()


# WebSocket tracing support


def trace_websocket_event(
    event_type: str,
    event_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add tracing context to a WebSocket event.

    Args:
        event_type: Type of WebSocket event
        event_data: Event data dictionary

    Returns:
        Event data with tracing context added
    """
    data = event_data or {}

    # Add trace context
    trace_id = get_trace_id()
    span_id = get_span_id()

    if trace_id:
        data["_trace"] = {
            "trace_id": trace_id,
            "span_id": span_id,
        }

    return data


def extract_websocket_trace(event_data: dict[str, Any]) -> str | None:
    """Extract trace ID from WebSocket event data.

    Args:
        event_data: Event data dictionary

    Returns:
        Trace ID or None if not present
    """
    trace_info = event_data.get("_trace", {})
    return trace_info.get("trace_id")


# Error response tracing


def add_trace_to_error(error_response: dict[str, Any]) -> dict[str, Any]:
    """Add tracing context to error response.

    Args:
        error_response: Error response dictionary

    Returns:
        Error response with trace context
    """
    trace_id = get_trace_id()
    if trace_id:
        error_response["trace_id"] = trace_id
    return error_response


def init_tracing() -> bool:
    """Initialize tracing with OpenTelemetry export if configured.

    Call this at application startup to enable automatic span export
    to external collectors (Jaeger, Zipkin, OTLP, Datadog).

    Environment Variables:
        OTEL_EXPORTER_OTLP_ENDPOINT: OTLP collector endpoint
        OTEL_SERVICE_NAME: Service name for traces
        OTEL_TRACES_SAMPLER: Sampler type
        OTEL_TRACES_SAMPLER_ARG: Sampler argument (e.g., ratio)

    Returns:
        True if OpenTelemetry export was initialized, False otherwise.
    """
    try:
        from aragora.observability.middleware.otel_bridge import init_otel_bridge

        return init_otel_bridge()
    except ImportError:
        return False


def shutdown_tracing() -> None:
    """Shutdown tracing and flush pending spans.

    Call this during application shutdown to ensure all spans are exported.
    """
    try:
        from aragora.observability.middleware.otel_bridge import shutdown_otel_bridge

        shutdown_otel_bridge()
    except ImportError:
        pass


__all__ = [
    # Header constants
    "TRACE_ID_HEADER",
    "SPAN_ID_HEADER",
    "PARENT_SPAN_HEADER",
    # ID generators
    "generate_trace_id",
    "generate_span_id",
    # Context getters/setters
    "get_trace_id",
    "get_span_id",
    "get_parent_span_id",
    "set_trace_id",
    "set_span_id",
    # Span
    "Span",
    # Context manager
    "trace_context",
    # Decorator
    "traced",
    # Middleware
    "TracingMiddleware",
    # WebSocket support
    "trace_websocket_event",
    "extract_websocket_trace",
    # Error support
    "add_trace_to_error",
    # Initialization
    "init_tracing",
    "shutdown_tracing",
]
