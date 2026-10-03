"""
OpenTelemetry distributed tracing for Aragora.

Provides decorators and utilities for instrumenting API handlers
and agent calls with distributed tracing spans.

Usage:
    from aragora.observability.tracing import tracer, trace_handler

    @trace_handler("debates.create")
    def handle_create_debate(self, handler):
        with tracer.start_as_current_span("validate_input"):
            ...

Requirements:
    pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp

Environment Variables:
    OTEL_ENABLED: Set to "true" to enable tracing
    OTEL_EXPORTER_OTLP_ENDPOINT: OTLP collector endpoint

See docs/OBSERVABILITY.md for configuration guide.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from functools import wraps
from typing import Any, TypeVar, cast
from collections.abc import Callable, Iterator

from aragora.observability.config import get_tracing_config

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# OpenTelemetry imports - only imported when tracing is enabled
_tracer = None
_tracer_provider = None


def _init_tracer() -> Any:
    """Initialize OpenTelemetry tracer lazily.

    Delegates to the unified otel.py setup module when available.
    Falls back to direct initialization for backward compatibility.
    """
    global _tracer, _tracer_provider

    if _tracer is not None:
        return _tracer

    config = get_tracing_config()

    if not config.enabled:
        # Return a no-op tracer
        return _NoOpTracer()

    # Try unified OTel setup first (preferred path)
    try:
        from aragora.observability.otel import (
            setup_otel,
            get_tracer as otel_get_tracer,
            is_initialized,
        )

        if not is_initialized():
            setup_otel()  # Will read config from environment

        if is_initialized():
            _tracer = otel_get_tracer("aragora", config.service_version)
            logger.info(
                "OpenTelemetry tracing initialized via unified setup: service=%s, sample_rate=%s",
                config.service_name,
                config.sample_rate,
            )
            return _tracer
    except ImportError:
        logger.debug("Unified OTel setup not available, falling back to direct init")
    except (RuntimeError, ValueError, TypeError) as e:
        logger.debug(
            "Unified OTel setup failed, falling back to direct init",
            extra={"error_type": type(e).__name__, "error": str(e)},
        )
    except OSError as e:
        logger.warning(
            "Unified OTel setup failed due to resource error, falling back to direct init",
            extra={"error_type": type(e).__name__, "error": str(e)},
        )

    # Fallback: direct initialization (legacy path)
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        # Create resource with service attributes
        resource = Resource.create(
            {
                "service.name": config.service_name,
                "service.version": config.service_version,
                "deployment.environment": config.environment,
            }
        )

        # Create sampler based on sample rate
        sampler = TraceIdRatioBased(config.sample_rate)

        # Create provider with sampler and resource
        _tracer_provider = TracerProvider(sampler=sampler, resource=resource)

        # Create exporter and processor
        exporter = OTLPSpanExporter(endpoint=config.otlp_endpoint)
        processor = BatchSpanProcessor(
            exporter,
            max_queue_size=config.batch_size * 2,
            max_export_batch_size=config.batch_size,
            export_timeout_millis=config.export_timeout_ms,
        )
        _tracer_provider.add_span_processor(processor)

        # Set as global provider
        trace.set_tracer_provider(_tracer_provider)

        # Get tracer
        _tracer = trace.get_tracer("aragora", config.service_version)

        logger.info(
            "OpenTelemetry tracing initialized (direct): endpoint=%s, "
            "service=%s/%s, environment=%s, sample_rate=%s",
            config.otlp_endpoint,
            config.service_name,
            config.service_version,
            config.environment,
            config.sample_rate,
        )

        return _tracer

    except ImportError as e:
        logger.warning(
            "OpenTelemetry not installed, tracing disabled: %s. "
            "Install with: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp",
            e,
        )
        return _NoOpTracer()
    except (ValueError, TypeError, RuntimeError) as e:
        # Configuration or initialization errors
        logger.error(
            "Failed to initialize OpenTelemetry due to configuration error",
            extra={"error_type": type(e).__name__, "error": str(e)},
        )
        return _NoOpTracer()
    except OSError as e:
        # Network or resource errors (e.g., cannot connect to OTLP endpoint)
        logger.error(
            "Failed to initialize OpenTelemetry due to resource error",
            extra={"error_type": type(e).__name__, "error": str(e)},
        )
        return _NoOpTracer()


class _NoOpSpan:
    """No-op span for when tracing is disabled."""

    def set_attribute(self, key: str, value: Any) -> _NoOpSpan:
        return self

    def set_attributes(self, attributes: dict[str, Any]) -> _NoOpSpan:
        return self

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> _NoOpSpan:
        return self

    def record_exception(self, exception: BaseException) -> _NoOpSpan:
        return self

    def set_status(self, status: Any) -> _NoOpSpan:
        return self

    def end(self) -> None:
        pass

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _NoOpTracer:
    """No-op tracer for when tracing is disabled."""

    def start_as_current_span(
        self,
        name: str,
        **kwargs: Any,
    ) -> _NoOpSpan:
        return _NoOpSpan()

    def start_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()


def get_tracer() -> Any:
    """Get the OpenTelemetry tracer instance."""
    return _init_tracer()


@contextmanager
def create_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Create a span context manager.

    Args:
        name: Span name
        attributes: Optional span attributes

    Yields:
        The span object (or NoOpSpan if tracing disabled)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes:
            add_span_attributes(span, attributes)
        yield span


def trace_handler(name: str) -> Callable[[F], F]:
    """Decorator to trace HTTP handler methods.

    Args:
        name: Span name for the handler (e.g., "debates.create")

    Returns:
        Decorated function with tracing

    Example:
        @trace_handler("debates.list")
        def handle_list_debates(self, handler):
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(self: Any, handler: Any, *args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(name) as span:
                # Add HTTP attributes
                if hasattr(handler, "path"):
                    span.set_attribute("http.path", handler.path)
                if hasattr(handler, "command"):
                    span.set_attribute("http.method", handler.command)
                if hasattr(handler, "client_address"):
                    span.set_attribute("net.peer.ip", str(handler.client_address[0]))

                try:
                    result = func(self, handler, *args, **kwargs)

                    # Add response attributes
                    if hasattr(result, "status_code"):
                        span.set_attribute("http.status_code", result.status_code)

                    return result
                except Exception as e:  # noqa: BLE001 - tracing must catch all to record exception on span before re-raising
                    span.record_exception(e)
                    _set_error_status(span)
                    raise

        return cast(F, wrapper)

    return decorator


def trace_async_handler(name: str) -> Callable[[F], F]:
    """Decorator to trace async HTTP handler methods.

    Args:
        name: Span name for the handler

    Returns:
        Decorated async function with tracing
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(self: Any, handler: Any, *args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(name) as span:
                if hasattr(handler, "path"):
                    span.set_attribute("http.path", handler.path)
                if hasattr(handler, "command"):
                    span.set_attribute("http.method", handler.command)

                try:
                    result = await func(self, handler, *args, **kwargs)
                    if hasattr(result, "status_code"):
                        span.set_attribute("http.status_code", result.status_code)
                    return result
                except Exception as e:  # noqa: BLE001 - tracing must catch all to record exception on span before re-raising
                    span.record_exception(e)
                    _set_error_status(span)
                    raise

        return cast(F, wrapper)

    return decorator


def trace_agent_call(agent_name: str) -> Callable[[F], F]:
    """Decorator to trace agent API calls.

    Args:
        agent_name: Name of the agent being called

    Returns:
        Decorated async function with tracing

    Example:
        @trace_agent_call("anthropic")
        async def respond(self, prompt: str) -> str:
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(f"agent.{agent_name}") as span:
                span.set_attribute("agent.name", agent_name)

                # Extract prompt if available
                if args and len(args) > 1:
                    prompt = args[1] if len(args) > 1 else kwargs.get("prompt", "")
                    if isinstance(prompt, str):
                        span.set_attribute("agent.prompt_length", len(prompt))

                try:
                    result = await func(*args, **kwargs)

                    # Record response length
                    if isinstance(result, str):
                        span.set_attribute("agent.response_length", len(result))

                    return result
                except Exception as e:  # noqa: BLE001 - tracing must catch all to record exception on span before re-raising
                    span.record_exception(e)
                    span.set_attribute("agent.error", str(e))
                    _set_error_status(span)
                    raise

        return cast(F, wrapper)

    return decorator


def add_span_attributes(span: Any, attributes: dict[str, Any]) -> None:
    """Add attributes to a span safely.

    Args:
        span: The span to add attributes to
        attributes: Dictionary of attribute key-value pairs
    """
    if span is None:
        return

    for key, value in attributes.items():
        if value is not None:
            # Convert complex types to strings
            if isinstance(value, (list, dict)):
                value = str(value)
            try:
                span.set_attribute(key, value)
            except (TypeError, ValueError) as e:
                # Ignore invalid attribute types (e.g., unsupported types)
                logger.debug("Failed to set span attribute %s: %s", key, e)


def record_exception(span: Any, exception: BaseException) -> None:
    """Record an exception on a span.

    Args:
        span: The span to record the exception on
        exception: The exception to record
    """
    if span is not None and hasattr(span, "record_exception"):
        span.record_exception(exception)
        _set_error_status(span)


def _set_error_status(span: Any) -> None:
    """Set error status on a span."""
    if span is None:
        return

    try:
        from opentelemetry.trace import StatusCode

        span.set_status(StatusCode.ERROR)
    except ImportError:
        pass


def shutdown() -> None:
    """Shutdown the tracer provider gracefully."""
    global _tracer_provider
    if _tracer_provider is not None:
        try:
            _tracer_provider.shutdown()
            logger.info("OpenTelemetry tracer shutdown complete")
        except (RuntimeError, TimeoutError) as e:
            # Shutdown may fail if already shutdown or timeout during flush
            logger.error(
                "Error shutting down tracer",
                extra={"error_type": type(e).__name__, "error": str(e)},
            )
        except OSError as e:
            # Network error during final flush
            logger.error(
                "Network error during tracer shutdown",
                extra={"error_type": type(e).__name__, "error": str(e)},
            )


# =============================================================================
# Debate-Specific Tracing
# =============================================================================


def trace_debate(debate_id: str) -> Callable[[F], F]:
    """Decorator to trace an entire debate lifecycle.

    Args:
        debate_id: The debate ID (can be a function arg name to extract)

    Returns:
        Decorated async function with debate tracing

    Example:
        @trace_debate("debate_id")
        async def run_debate(self, debate_id: str) -> DebateResult:
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            # Try to get debate_id from kwargs or args
            did = kwargs.get(debate_id) or (
                args[1] if len(args) > 1 and isinstance(args[1], str) else debate_id
            )

            with tracer.start_as_current_span("debate") as span:
                span.set_attribute("debate.id", str(did))

                try:
                    result = await func(*args, **kwargs)

                    # Record result attributes
                    if hasattr(result, "consensus_reached"):
                        span.set_attribute("debate.consensus_reached", result.consensus_reached)
                    if hasattr(result, "rounds_used"):
                        span.set_attribute("debate.rounds", result.rounds_used)
                    if hasattr(result, "confidence"):
                        span.set_attribute("debate.confidence", result.confidence)

                    return result
                except Exception as e:  # noqa: BLE001 - tracing must catch all to record exception on span before re-raising
                    span.record_exception(e)
                    _set_error_status(span)
                    raise

        return cast(F, wrapper)

    return decorator


@contextmanager
def trace_debate_phase(
    phase_name: str, debate_id: str, round_num: int | None = None
) -> Iterator[Any]:
    """Context manager for tracing a debate phase.

    Args:
        phase_name: Name of the phase (propose, critique, vote, etc.)
        debate_id: The debate ID
        round_num: Optional round number

    Yields:
        The span object

    Example:
        with trace_debate_phase("propose", debate_id, round_num=1) as span:
            proposal = await agent.generate(prompt)
            span.set_attribute("proposal.length", len(proposal))
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"debate.phase.{phase_name}") as span:
        span.set_attribute("debate.id", debate_id)
        span.set_attribute("debate.phase", phase_name)
        if round_num is not None:
            span.set_attribute("debate.round", round_num)
        yield span


@contextmanager
def trace_consensus_check(debate_id: str, round_num: int) -> Iterator[Any]:
    """Context manager for tracing consensus checking.

    Args:
        debate_id: The debate ID
        round_num: Current round number

    Yields:
        The span object
    """
    tracer = get_tracer()
    with tracer.start_as_current_span("debate.consensus_check") as span:
        span.set_attribute("debate.id", debate_id)
        span.set_attribute("debate.round", round_num)
        yield span


def trace_memory_operation(operation: str, tier: str) -> Callable[[F], F]:
    """Decorator to trace memory operations.

    Args:
        operation: Operation type (store, query, promote, demote)
        tier: Memory tier (fast, medium, slow, glacial)

    Returns:
        Decorated function with tracing
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(f"memory.{operation}") as span:
                span.set_attribute("memory.operation", operation)
                span.set_attribute("memory.tier", tier)
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:  # noqa: BLE001 - tracing must catch all to record exception on span before re-raising
                    span.record_exception(e)
                    _set_error_status(span)
                    raise

        return cast(F, wrapper)

    return decorator


# =============================================================================
# Decision Pipeline Tracing
# =============================================================================


@contextmanager
def trace_decision_routing(
    request_id: str,
    decision_type: str,
    source: str,
    priority: str = "normal",
) -> Iterator[Any]:
    """Context manager for tracing decision routing.

    Args:
        request_id: The unique request ID
        decision_type: Type of decision (debate, workflow, gauntlet, quick)
        source: Input source (http_api, slack, voice, etc.)
        priority: Request priority level

    Yields:
        The span object

    Example:
        with trace_decision_routing(request.request_id, "debate", "slack") as span:
            result = await router.route(request)
            span.set_attribute("decision.confidence", result.confidence)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span("decision.route") as span:
        span.set_attribute("decision.request_id", request_id)
        span.set_attribute("decision.type", decision_type)
        span.set_attribute("decision.source", source)
        span.set_attribute("decision.priority", priority)
        yield span


@contextmanager
def trace_decision_engine(
    engine_type: str,
    request_id: str,
) -> Iterator[Any]:
    """Context manager for tracing decision engine execution.

    Args:
        engine_type: Type of engine (debate, workflow, gauntlet, quick)
        request_id: The request ID being processed

    Yields:
        The span object
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"decision.engine.{engine_type}") as span:
        span.set_attribute("decision.engine", engine_type)
        span.set_attribute("decision.request_id", request_id)
        yield span


@contextmanager
def trace_response_delivery(
    platform: str,
    channel_id: str | None = None,
    voice_enabled: bool = False,
) -> Iterator[Any]:
    """Context manager for tracing response delivery.

    Args:
        platform: Target platform (slack, discord, http, etc.)
        channel_id: Optional channel/destination ID
        voice_enabled: Whether voice response is enabled

    Yields:
        The span object
    """
    tracer = get_tracer()
    with tracer.start_as_current_span("decision.deliver") as span:
        span.set_attribute("delivery.platform", platform)
        if channel_id:
            span.set_attribute("delivery.channel_id", channel_id)
        span.set_attribute("delivery.voice_enabled", voice_enabled)
        yield span


# =============================================================================
# Webhook Tracing
# =============================================================================


@contextmanager
def trace_webhook_delivery(
    event_type: str,
    webhook_id: str,
    webhook_url: str,
    correlation_id: str | None = None,
) -> Iterator[Any]:
    """Context manager for tracing webhook delivery.

    Args:
        event_type: Type of event being delivered (e.g., "slo_violation")
        webhook_id: Unique identifier for the webhook endpoint
        webhook_url: URL of the webhook endpoint
        correlation_id: Optional correlation ID for request tracing

    Yields:
        The span object

    Example:
        with trace_webhook_delivery("slo_violation", webhook.id, webhook.url) as span:
            result = dispatch_webhook(webhook, payload)
            span.set_attribute("webhook.success", result.success)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span("webhook.delivery") as span:
        span.set_attribute("webhook.event_type", event_type)
        span.set_attribute("webhook.id", webhook_id)
        span.set_attribute("webhook.url", _redact_url(webhook_url))
        if correlation_id:
            span.set_attribute("webhook.correlation_id", correlation_id)
        yield span


@contextmanager
def trace_webhook_batch(
    event_type: str,
    batch_size: int,
    correlation_id: str | None = None,
) -> Iterator[Any]:
    """Context manager for tracing batched webhook delivery.

    Args:
        event_type: Type of events in the batch
        batch_size: Number of events in the batch
        correlation_id: Optional correlation ID

    Yields:
        The span object
    """
    tracer = get_tracer()
    with tracer.start_as_current_span("webhook.batch_delivery") as span:
        span.set_attribute("webhook.event_type", event_type)
        span.set_attribute("webhook.batch_size", batch_size)
        if correlation_id:
            span.set_attribute("webhook.correlation_id", correlation_id)
        yield span


def _redact_url(url: str) -> str:
    """Redact sensitive parts of webhook URL for tracing.

    Keeps host and path but removes query params that might contain secrets.
    """
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        # Keep scheme, host, and path; remove query and fragment
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except (ValueError, AttributeError) as e:
        # Invalid URL format or None passed
        logger.debug(
            "URL sanitization failed",
            extra={"error_type": type(e).__name__, "error": str(e)},
        )
        return "[redacted]"


def trace_decision(func: F) -> F:
    """Decorator to trace the entire decision routing lifecycle.

    Automatically extracts request attributes and records result metrics.

    Example:
        @trace_decision
        async def route(self, request: DecisionRequest) -> DecisionResult:
            ...
    """

    @wraps(func)
    async def wrapper(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
        tracer = get_tracer()

        # Extract attributes from request
        request_id = getattr(request, "request_id", "unknown")
        decision_type = cast(Any, getattr(request, "decision_type", None))
        decision_type_str = (
            decision_type.value if hasattr(decision_type, "value") else str(decision_type)
        )
        source = cast(Any, getattr(request, "source", None))
        source_str = source.value if hasattr(source, "value") else str(source)
        priority = cast(Any, getattr(request, "priority", None))
        priority_str = priority.value if hasattr(priority, "value") else str(priority)

        with tracer.start_as_current_span("decision.route") as span:
            span.set_attribute("decision.request_id", request_id)
            span.set_attribute("decision.type", decision_type_str)
            span.set_attribute("decision.source", source_str)
            span.set_attribute("decision.priority", priority_str)

            # Extract content length
            content = getattr(request, "content", "")
            if isinstance(content, str):
                span.set_attribute("decision.content_length", len(content))

            # Extract agent config
            config = getattr(request, "config", None)
            if config:
                agents = getattr(config, "agents", [])
                span.set_attribute("decision.agent_count", len(agents))

            try:
                result = await func(self, request, *args, **kwargs)

                # Record result attributes
                if result:
                    if hasattr(result, "confidence"):
                        span.set_attribute("decision.confidence", result.confidence)
                    if hasattr(result, "consensus_reached"):
                        span.set_attribute("decision.consensus_reached", result.consensus_reached)
                    if hasattr(result, "success"):
                        span.set_attribute("decision.success", result.success)
                    if hasattr(result, "duration_seconds"):
                        span.set_attribute("decision.duration_seconds", result.duration_seconds)
                    if hasattr(result, "error") and result.error:
                        span.set_attribute("decision.error", str(result.error)[:200])

                return result

            except Exception as e:  # noqa: BLE001 - tracing must catch all to record exception on span before re-raising
                span.record_exception(e)
                span.set_attribute("decision.error", str(e)[:200])
                _set_error_status(span)
                raise

    return cast(F, wrapper)


# =============================================================================
# Agent Fabric Tracing
# =============================================================================


@contextmanager
def trace_fabric_operation(
    operation: str,
    agent_id: str | None = None,
    task_id: str | None = None,
    pool_id: str | None = None,
) -> Iterator[Any]:
    """Context manager for tracing Agent Fabric operations.

    Args:
        operation: Type of operation (spawn, schedule, execute, policy_check, etc.)
        agent_id: Optional agent ID involved
        task_id: Optional task ID involved
        pool_id: Optional pool ID involved

    Yields:
        The span object

    Example:
        with trace_fabric_operation("schedule", agent_id="a1", task_id="t1") as span:
            handle = await scheduler.schedule(task, agent_id)
            span.set_attribute("task.status", handle.status.value)
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"fabric.{operation}") as span:
        span.set_attribute("fabric.operation", operation)
        if agent_id:
            span.set_attribute("fabric.agent_id", agent_id)
        if task_id:
            span.set_attribute("fabric.task_id", task_id)
        if pool_id:
            span.set_attribute("fabric.pool_id", pool_id)
        yield span


@contextmanager
def trace_fabric_task(
    task_type: str,
    task_id: str,
    agent_id: str,
    priority: str = "normal",
) -> Iterator[Any]:
    """Context manager for tracing fabric task execution.

    Args:
        task_type: Type of task (debate, generate, etc.)
        task_id: Task identifier
        agent_id: Agent executing the task
        priority: Task priority

    Yields:
        The span object
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"fabric.task.{task_type}") as span:
        span.set_attribute("fabric.task.id", task_id)
        span.set_attribute("fabric.task.type", task_type)
        span.set_attribute("fabric.agent_id", agent_id)
        span.set_attribute("fabric.task.priority", priority)
        yield span


@contextmanager
def trace_fabric_policy_check(
    action: str,
    agent_id: str | None = None,
    resource: str | None = None,
) -> Iterator[Any]:
    """Context manager for tracing fabric policy decisions.

    Args:
        action: Action being checked
        agent_id: Agent requesting the action
        resource: Resource being accessed

    Yields:
        The span object
    """
    tracer = get_tracer()
    with tracer.start_as_current_span("fabric.policy.check") as span:
        span.set_attribute("fabric.policy.action", action)
        if agent_id:
            span.set_attribute("fabric.agent_id", agent_id)
        if resource:
            span.set_attribute("fabric.policy.resource", resource)
        yield span


# =============================================================================
# HTTP Trace Header Propagation
# =============================================================================


def build_trace_headers() -> dict[str, str]:
    """Build trace context headers for outgoing HTTP requests.

    Returns W3C Trace Context (traceparent) and custom headers for
    distributed tracing across services. Use this function to add
    trace context to any outgoing HTTP request.

    Returns:
        Dictionary of trace headers to include in HTTP requests.
        Returns empty dict if no trace context is set.

    Example:
        import httpx

        async with httpx.AsyncClient() as client:
            headers = {"Authorization": "Bearer token"}
            headers.update(build_trace_headers())
            response = await client.post(url, json=data, headers=headers)
    """
    headers: dict[str, str] = {}

    try:
        from aragora.observability.middleware.tracing import (
            get_trace_id,
            get_span_id,
            TRACE_ID_HEADER,
            SPAN_ID_HEADER,
        )

        trace_id = get_trace_id()
        span_id = get_span_id()

        if trace_id:
            # Custom headers (simple, easy to read in logs)
            headers[TRACE_ID_HEADER] = trace_id
            if span_id:
                headers[SPAN_ID_HEADER] = span_id

            # W3C Trace Context (traceparent)
            # Format: version-trace_id-parent_id-flags
            # Version 00 is current, flags 01 means sampled
            parent_id = span_id or "0000000000000000"
            # Ensure trace_id is 32 chars and parent_id is 16 chars
            trace_id_padded = trace_id.ljust(32, "0")[:32]
            parent_id_padded = parent_id.ljust(16, "0")[:16]
            headers["traceparent"] = f"00-{trace_id_padded}-{parent_id_padded}-01"

    except ImportError:
        # Tracing middleware not available
        pass

    return headers


# =============================================================================
# Universal @traced Decorator
# =============================================================================


def traced(
    name: str | None = None,
    *,
    attributes: dict[str, Any] | None = None,
    record_args: bool = False,
    record_result: bool = False,
) -> Callable[[F], F]:
    """Universal decorator for tracing function execution.

    Works with both sync and async functions. Creates a span around the
    function execution with optional argument and result recording.

    Args:
        name: Span name. Defaults to the function's qualified name.
        attributes: Static attributes to add to every span.
        record_args: If True, record function arguments as span attributes.
        record_result: If True, record function return value as span attribute.

    Returns:
        Decorated function with tracing.

    Example:
        @traced("user.create")
        async def create_user(name: str, email: str) -> User:
            ...

        @traced(record_args=True, record_result=True)
        def calculate_score(values: list[int]) -> float:
            ...

        @traced(attributes={"service": "billing"})
        async def process_payment(amount: float) -> bool:
            ...
    """
    import asyncio
    import inspect

    def decorator(func: F) -> F:
        # Determine span name
        span_name = name
        if span_name is None:
            module = getattr(func, "__module__", "")
            qualname = getattr(func, "__qualname__", func.__name__)
            span_name = f"{module}.{qualname}" if module else qualname

        is_async = asyncio.iscoroutinefunction(func)
        sig = inspect.signature(func) if record_args else None

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                # Add static attributes
                if attributes:
                    add_span_attributes(span, attributes)

                # Record function arguments
                if record_args and sig:
                    _record_function_args(span, sig, args, kwargs)

                try:
                    result = await func(*args, **kwargs)

                    # Record result
                    if record_result and result is not None:
                        _record_result(span, result)

                    return result
                except Exception as e:  # noqa: BLE001 - tracing must catch all to record exception on span before re-raising
                    span.record_exception(e)
                    _set_error_status(span)
                    raise

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                # Add static attributes
                if attributes:
                    add_span_attributes(span, attributes)

                # Record function arguments
                if record_args and sig:
                    _record_function_args(span, sig, args, kwargs)

                try:
                    result = func(*args, **kwargs)

                    # Record result
                    if record_result and result is not None:
                        _record_result(span, result)

                    return result
                except Exception as e:  # noqa: BLE001 - tracing must catch all to record exception on span before re-raising
                    span.record_exception(e)
                    _set_error_status(span)
                    raise

        return cast(F, async_wrapper if is_async else sync_wrapper)

    return decorator


def _record_function_args(
    span: Any,
    sig: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    """Record function arguments as span attributes."""

    try:
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()

        for param_name, value in bound.arguments.items():
            # Skip self/cls parameters
            if param_name in ("self", "cls"):
                continue

            attr_key = f"arg.{param_name}"

            # Handle different types safely
            if value is None:
                span.set_attribute(attr_key, "None")
            elif isinstance(value, (str, int, float, bool)):
                span.set_attribute(attr_key, value)
            elif isinstance(value, (list, tuple)):
                span.set_attribute(f"{attr_key}.length", len(value))
            elif isinstance(value, dict):
                span.set_attribute(f"{attr_key}.keys", str(list(value.keys())[:10]))
            else:
                span.set_attribute(f"{attr_key}.type", type(value).__name__)
    except (TypeError, ValueError, AttributeError, KeyError):
        # Don't fail tracing due to arg recording issues
        # These are expected when arguments don't match signature or have unusual types
        pass


def _record_result(span: Any, result: Any) -> None:
    """Record function result as span attribute."""
    try:
        if isinstance(result, (str, int, float, bool)):
            span.set_attribute("result", result)
        elif isinstance(result, (list, tuple)):
            span.set_attribute("result.length", len(result))
        elif isinstance(result, dict):
            span.set_attribute("result.keys", str(list(result.keys())[:10]))
        elif hasattr(result, "__dict__"):
            span.set_attribute("result.type", type(result).__name__)
    except (TypeError, ValueError, AttributeError):
        # Don't fail tracing due to result recording issues
        # These are expected when results have unusual types or span is invalid
        pass


# =============================================================================
# Auto-Instrumentation Hooks
# =============================================================================


class AutoInstrumentation:
    """Auto-instrumentation hooks for common libraries and patterns.

    Provides automatic tracing for HTTP clients, database connections,
    and other common operations without manual instrumentation.

    Usage:
        from aragora.observability.tracing import AutoInstrumentation

        # At application startup
        AutoInstrumentation.instrument_httpx()
        AutoInstrumentation.instrument_aiohttp()

        # To check what's instrumented
        AutoInstrumentation.get_instrumented_libraries()
    """

    _instrumented: set[str] = set()

    @classmethod
    def instrument_httpx(cls) -> bool:
        """Instrument httpx library for automatic HTTP client tracing.

        Returns:
            True if instrumentation was applied, False otherwise.
        """
        if "httpx" in cls._instrumented:
            return True

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentation

            HTTPXClientInstrumentation().instrument()
            cls._instrumented.add("httpx")
            logger.info("Auto-instrumented httpx for distributed tracing")
            return True
        except ImportError:
            logger.debug(
                "httpx instrumentation not available (install opentelemetry-instrumentation-httpx)"
            )
            return False

    @classmethod
    def instrument_aiohttp(cls) -> bool:
        """Instrument aiohttp library for automatic HTTP client/server tracing.

        Returns:
            True if instrumentation was applied, False otherwise.
        """
        if "aiohttp" in cls._instrumented:
            return True

        try:
            from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor

            AioHttpClientInstrumentor().instrument()
            cls._instrumented.add("aiohttp")
            logger.info("Auto-instrumented aiohttp for distributed tracing")
            return True
        except ImportError:
            logger.debug(
                "aiohttp instrumentation not available (install opentelemetry-instrumentation-aiohttp-client)"
            )
            return False

    @classmethod
    def instrument_requests(cls) -> bool:
        """Instrument requests library for automatic HTTP client tracing.

        Returns:
            True if instrumentation was applied, False otherwise.
        """
        if "requests" in cls._instrumented:
            return True

        try:
            from opentelemetry.instrumentation.requests import RequestsInstrumentor

            RequestsInstrumentor().instrument()
            cls._instrumented.add("requests")
            logger.info("Auto-instrumented requests for distributed tracing")
            return True
        except ImportError:
            logger.debug(
                "requests instrumentation not available (install opentelemetry-instrumentation-requests)"
            )
            return False

    @classmethod
    def instrument_asyncpg(cls) -> bool:
        """Instrument asyncpg library for automatic PostgreSQL tracing.

        Returns:
            True if instrumentation was applied, False otherwise.
        """
        if "asyncpg" in cls._instrumented:
            return True

        try:
            from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor

            AsyncPGInstrumentor().instrument()
            cls._instrumented.add("asyncpg")
            logger.info("Auto-instrumented asyncpg for distributed tracing")
            return True
        except ImportError:
            logger.debug(
                "asyncpg instrumentation not available (install opentelemetry-instrumentation-asyncpg)"
            )
            return False

    @classmethod
    def instrument_redis(cls) -> bool:
        """Instrument redis library for automatic Redis tracing.

        Returns:
            True if instrumentation was applied, False otherwise.
        """
        if "redis" in cls._instrumented:
            return True

        try:
            from opentelemetry.instrumentation.redis import RedisInstrumentor

            RedisInstrumentor().instrument()
            cls._instrumented.add("redis")
            logger.info("Auto-instrumented redis for distributed tracing")
            return True
        except ImportError:
            logger.debug(
                "redis instrumentation not available (install opentelemetry-instrumentation-redis)"
            )
            return False

    @classmethod
    def instrument_all(cls) -> list[str]:
        """Attempt to instrument all supported libraries.

        Returns:
            List of successfully instrumented libraries.
        """
        instrumented = []
        if cls.instrument_httpx():
            instrumented.append("httpx")
        if cls.instrument_aiohttp():
            instrumented.append("aiohttp")
        if cls.instrument_requests():
            instrumented.append("requests")
        if cls.instrument_asyncpg():
            instrumented.append("asyncpg")
        if cls.instrument_redis():
            instrumented.append("redis")
        return instrumented

    @classmethod
    def get_instrumented_libraries(cls) -> set[str]:
        """Get the set of currently instrumented libraries.

        Returns:
            Set of library names that have been instrumented.
        """
        return cls._instrumented.copy()

    @classmethod
    def reset(cls) -> None:
        """Reset instrumentation tracking (for testing)."""
        cls._instrumented.clear()


def instrument_all() -> list[str]:
    """Convenience function to instrument all supported libraries.

    Returns:
        List of successfully instrumented libraries.

    Example:
        from aragora.observability.tracing import instrument_all

        # At application startup
        instrumented = instrument_all()
        print(f"Instrumented: {instrumented}")
    """
    return AutoInstrumentation.instrument_all()


# =============================================================================
# Queue Worker Tracing Helpers
# =============================================================================


@contextmanager
def trace_worker_job(
    job_type: str,
    job_id: str,
    worker_id: str | None = None,
    payload_keys: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Context manager for tracing background worker job execution.

    Creates a span for the job with relevant attributes and handles
    trace context propagation from the job payload.

    Args:
        job_type: Type of job being processed (e.g., "routing", "gauntlet")
        job_id: Unique job identifier
        worker_id: Optional worker identifier
        payload_keys: Optional list of payload keys to include as attributes
        payload: Optional job payload dict

    Yields:
        The span object

    Example:
        with trace_worker_job("routing", job.id, worker_id="worker-1") as span:
            result = await process_job(job)
            span.set_attribute("job.result", result.status)
    """
    tracer = get_tracer()

    with tracer.start_as_current_span(f"worker.job.{job_type}") as span:
        span.set_attribute("job.type", job_type)
        span.set_attribute("job.id", job_id)
        if worker_id:
            span.set_attribute("worker.id", worker_id)

        # Extract specific payload keys as attributes
        if payload and payload_keys:
            for key in payload_keys:
                if key in payload:
                    value = payload[key]
                    if isinstance(value, (str, int, float, bool)):
                        span.set_attribute(f"job.payload.{key}", value)

        yield span


@contextmanager
def trace_worker_batch(
    job_type: str,
    batch_size: int,
    worker_id: str | None = None,
) -> Iterator[Any]:
    """Context manager for tracing a batch of worker jobs.

    Args:
        job_type: Type of jobs in the batch
        batch_size: Number of jobs in the batch
        worker_id: Optional worker identifier

    Yields:
        The span object
    """
    tracer = get_tracer()

    with tracer.start_as_current_span(f"worker.batch.{job_type}") as span:
        span.set_attribute("job.type", job_type)
        span.set_attribute("batch.size", batch_size)
        if worker_id:
            span.set_attribute("worker.id", worker_id)
        yield span


# =============================================================================
# External Service Tracing
# =============================================================================


@contextmanager
def trace_external_call(
    service: str,
    operation: str,
    endpoint: str | None = None,
) -> Iterator[Any]:
    """Context manager for tracing calls to external services.

    Args:
        service: Name of the external service (e.g., "openai", "anthropic")
        operation: Operation being performed (e.g., "chat.completions")
        endpoint: Optional endpoint URL (will be redacted)

    Yields:
        The span object

    Example:
        with trace_external_call("openai", "chat.completions") as span:
            response = await client.chat.completions.create(...)
            span.set_attribute("tokens.total", response.usage.total_tokens)
    """
    tracer = get_tracer()

    with tracer.start_as_current_span(f"external.{service}.{operation}") as span:
        span.set_attribute("external.service", service)
        span.set_attribute("external.operation", operation)
        if endpoint:
            span.set_attribute("external.endpoint", _redact_url(endpoint))
        yield span


@contextmanager
def trace_llm_call(
    provider: str,
    model: str,
    operation: str = "generate",
    prompt_tokens: int | None = None,
) -> Iterator[Any]:
    """Context manager for tracing LLM API calls.

    Args:
        provider: LLM provider (e.g., "anthropic", "openai", "google")
        model: Model name/identifier
        operation: Operation type (e.g., "generate", "embed", "complete")
        prompt_tokens: Optional prompt token count

    Yields:
        The span object

    Example:
        with trace_llm_call("anthropic", "claude-3-opus", "generate") as span:
            response = await claude.generate(prompt)
            span.set_attribute("llm.completion_tokens", response.usage.output_tokens)
            span.set_attribute("llm.total_tokens", response.usage.total_tokens)
    """
    tracer = get_tracer()

    with tracer.start_as_current_span(f"llm.{provider}.{operation}") as span:
        span.set_attribute("llm.provider", provider)
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.operation", operation)
        if prompt_tokens is not None:
            span.set_attribute("llm.prompt_tokens", prompt_tokens)
        yield span
