"""
OpenTelemetry Bridge for Middleware Tracing.

Connects the internal tracing middleware with OpenTelemetry for distributed
tracing export to external collectors (Jaeger, Zipkin, OTLP, Datadog).

This bridge:
1. Converts internal Span objects to OpenTelemetry spans
2. Propagates W3C Trace Context headers
3. Supports both standard OTEL_* and ARAGORA_* environment variables
4. Provides configurable sampling strategies

Environment Variables (standard OpenTelemetry, takes precedence):
    OTEL_EXPORTER_OTLP_ENDPOINT: OTLP collector endpoint
    OTEL_SERVICE_NAME: Service name for traces
    OTEL_TRACES_SAMPLER: Sampler type (always_on, always_off, traceidratio, parentbased_always_on, parentbased_always_off, parentbased_traceidratio)
    OTEL_TRACES_SAMPLER_ARG: Argument for sampler (e.g., ratio for traceidratio)

Aragora-specific variables (fallback):
    ARAGORA_OTLP_EXPORTER: Exporter type
    ARAGORA_OTLP_ENDPOINT: Collector endpoint
    See docs/ENVIRONMENT.md for full reference.

Usage:
    from aragora.observability.middleware.otel_bridge import (
        init_otel_bridge,
        export_span_to_otel,
        inject_trace_context,
        extract_trace_context,
    )

    # Initialize at startup
    init_otel_bridge()

    # Export a span
    export_span_to_otel(span)

    # Inject context into outgoing requests
    headers = inject_trace_context({})

    # Extract context from incoming requests
    context = extract_trace_context(request_headers)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

from aragora.observability.middleware.trace_state import set_span_exporter

logger = logging.getLogger(__name__)

# OpenTelemetry imports - optional
_otel_available = False
_tracer: Any = None
_propagator: Any = None


class SamplerType(str, Enum):
    """Supported OpenTelemetry sampler types."""

    ALWAYS_ON = "always_on"
    ALWAYS_OFF = "always_off"
    TRACE_ID_RATIO = "traceidratio"
    PARENT_BASED_ALWAYS_ON = "parentbased_always_on"
    PARENT_BASED_ALWAYS_OFF = "parentbased_always_off"
    PARENT_BASED_TRACE_ID_RATIO = "parentbased_traceidratio"


@dataclass
class OTelBridgeConfig:
    """Configuration for the OpenTelemetry bridge.

    Attributes:
        enabled: Whether OTEL export is enabled
        endpoint: OTLP collector endpoint
        service_name: Service name for traces
        service_version: Service version string
        environment: Deployment environment
        sampler_type: Type of sampler to use
        sampler_arg: Argument for sampler (e.g., ratio)
        propagator_format: Context propagation format
        headers: Additional headers for exporter
        insecure: Allow insecure connections
    """

    enabled: bool = False
    endpoint: str = ""  # Must be set via OTEL_EXPORTER_OTLP_ENDPOINT or ARAGORA_OTLP_ENDPOINT
    service_name: str = "aragora"
    service_version: str = "1.0.0"
    environment: str = "development"
    sampler_type: SamplerType = SamplerType.PARENT_BASED_ALWAYS_ON
    sampler_arg: float = 1.0
    propagator_format: str = "tracecontext,baggage"
    headers: dict[str, str] | None = None
    insecure: bool = False

    @classmethod
    def from_env(cls) -> OTelBridgeConfig:
        """Create configuration from environment variables.

        Prioritizes standard OTEL_* variables over ARAGORA_* ones.

        Returns:
            OTelBridgeConfig instance
        """
        # Check if any OTEL export is configured
        otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        aragora_exporter = os.environ.get("ARAGORA_OTLP_EXPORTER", "none").lower()

        # Determine if OTEL is enabled
        enabled = bool(otel_endpoint) or (aragora_exporter != "none")

        # Get endpoint - standard OTEL takes precedence
        endpoint = otel_endpoint or os.environ.get("ARAGORA_OTLP_ENDPOINT") or ""

        # Warn if OTEL appears enabled but no endpoint is configured
        if enabled and not endpoint:
            logger.warning(
                "OpenTelemetry export appears enabled (ARAGORA_OTLP_EXPORTER=%s) but no endpoint configured. "
                "Set OTEL_EXPORTER_OTLP_ENDPOINT or ARAGORA_OTLP_ENDPOINT. Disabling OTEL export.",
                aragora_exporter,
            )
            enabled = False

        # Service name
        service_name = (
            os.environ.get("OTEL_SERVICE_NAME")
            or os.environ.get("ARAGORA_SERVICE_NAME")
            or "aragora"
        )

        # Service version
        service_version = os.environ.get("ARAGORA_SERVICE_VERSION", "1.0.0")

        # Environment
        environment = (
            os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
            .split("deployment.environment=")[-1]
            .split(",")[0]
            or os.environ.get("ARAGORA_ENVIRONMENT")
            or "development"
        )
        if not environment:
            environment = "development"

        # Sampler configuration
        sampler_str = os.environ.get("OTEL_TRACES_SAMPLER", "parentbased_always_on").lower()
        try:
            sampler_type = SamplerType(sampler_str)
        except ValueError:
            logger.warning(
                "Unknown sampler type: %s, using parentbased_always_on. Valid options: %s",
                sampler_str,
                [s.value for s in SamplerType],
            )
            sampler_type = SamplerType.PARENT_BASED_ALWAYS_ON

        # Sampler argument (ratio for traceidratio samplers)
        sampler_arg_str = os.environ.get(
            "OTEL_TRACES_SAMPLER_ARG",
            os.environ.get("ARAGORA_TRACE_SAMPLE_RATE", "1.0"),
        )
        try:
            sampler_arg = float(sampler_arg_str)
            if not 0.0 <= sampler_arg <= 1.0:
                raise ValueError("Sampler arg must be between 0.0 and 1.0")
        except ValueError:
            logger.warning("Invalid sampler arg: %s, using 1.0", sampler_arg_str)
            sampler_arg = 1.0

        # Propagator format
        propagator = os.environ.get("OTEL_PROPAGATORS", "tracecontext,baggage")

        # Headers for authenticated endpoints
        headers = None
        headers_json = os.environ.get("ARAGORA_OTLP_HEADERS", "")
        if headers_json:
            try:
                import json

                headers = json.loads(headers_json)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Failed to parse ARAGORA_OTLP_HEADERS: %s", e)

        # Insecure mode
        insecure = os.environ.get("ARAGORA_OTLP_INSECURE", "false").lower() in (
            "true",
            "1",
            "yes",
        )

        return cls(
            enabled=enabled,
            endpoint=endpoint,
            service_name=service_name,
            service_version=service_version,
            environment=environment,
            sampler_type=sampler_type,
            sampler_arg=sampler_arg,
            propagator_format=propagator,
            headers=headers,
            insecure=insecure,
        )


# Global configuration
_config: OTelBridgeConfig | None = None


def get_bridge_config() -> OTelBridgeConfig:
    """Get the current bridge configuration.

    Returns:
        Current OTelBridgeConfig, loading from environment if not set.
    """
    global _config
    if _config is None:
        _config = OTelBridgeConfig.from_env()
    return _config


def _create_sampler(config: OTelBridgeConfig) -> Any:
    """Create an OpenTelemetry sampler based on configuration.

    Args:
        config: Bridge configuration

    Returns:
        Sampler instance
    """
    try:
        from opentelemetry.sdk.trace.sampling import (
            ALWAYS_OFF,
            ALWAYS_ON,
            ParentBased,
            TraceIdRatioBased,
        )

        if config.sampler_type == SamplerType.ALWAYS_ON:
            return ALWAYS_ON
        elif config.sampler_type == SamplerType.ALWAYS_OFF:
            return ALWAYS_OFF
        elif config.sampler_type == SamplerType.TRACE_ID_RATIO:
            return TraceIdRatioBased(config.sampler_arg)
        elif config.sampler_type == SamplerType.PARENT_BASED_ALWAYS_ON:
            return ParentBased(root=ALWAYS_ON)
        elif config.sampler_type == SamplerType.PARENT_BASED_ALWAYS_OFF:
            return ParentBased(root=ALWAYS_OFF)
        elif config.sampler_type == SamplerType.PARENT_BASED_TRACE_ID_RATIO:
            return ParentBased(root=TraceIdRatioBased(config.sampler_arg))
        else:
            return ParentBased(root=ALWAYS_ON)
    except ImportError:
        return None


def init_otel_bridge(config: OTelBridgeConfig | None = None) -> bool:
    """Initialize the OpenTelemetry bridge.

    Tries the unified otel.py setup first for consistent configuration.
    Falls back to direct initialization if the unified module is unavailable.

    Args:
        config: Optional configuration. If None, loads from environment.

    Returns:
        True if bridge was initialized successfully, False otherwise.
    """
    global _otel_available, _tracer, _propagator, _config

    config = config or OTelBridgeConfig.from_env()
    _config = config

    if not config.enabled:
        logger.debug("OpenTelemetry bridge disabled (no OTEL endpoint configured)")
        return False

    if not config.endpoint:
        logger.error(
            "OpenTelemetry enabled but no endpoint configured. "
            "Set OTEL_EXPORTER_OTLP_ENDPOINT or ARAGORA_OTLP_ENDPOINT environment variable."
        )
        return False

    # Try unified OTel setup first (preferred path for consistent configuration)
    try:
        from aragora.observability.otel import (
            setup_otel,
            is_initialized,
            get_tracer as otel_get_tracer,
        )

        if not is_initialized():
            setup_otel()

        if is_initialized():
            _tracer = otel_get_tracer("aragora.middleware", config.service_version)
            _otel_available = True
            set_span_exporter(export_span_to_otel)
            logger.info(
                "OpenTelemetry bridge initialized via unified setup: service=%s, sampler=%s",
                config.service_name,
                config.sampler_type.value,
            )
            return True
    except ImportError:
        logger.debug("Unified OTel setup not available, falling back to direct bridge init")
    except (RuntimeError, ValueError, TypeError, OSError) as e:
        logger.debug("Unified OTel setup failed in bridge, falling back: %s", e)

    # Fallback: direct initialization (legacy path)
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.propagate import set_global_textmap
        from opentelemetry.propagators.composite import CompositePropagator
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        # Try to import propagators (Any type for mixed propagator types)
        propagators: list[Any] = []
        if "tracecontext" in config.propagator_format:
            try:
                from opentelemetry.trace.propagation.tracecontext import (
                    TraceContextTextMapPropagator,
                )

                propagators.append(TraceContextTextMapPropagator())
            except ImportError:
                pass

        if "baggage" in config.propagator_format:
            try:
                from opentelemetry.baggage.propagation import W3CBaggagePropagator

                propagators.append(W3CBaggagePropagator())
            except ImportError:
                pass

        # Create resource with service attributes
        resource = Resource.create(
            {
                "service.name": config.service_name,
                "service.version": config.service_version,
                "deployment.environment": config.environment,
            }
        )

        # Create sampler
        sampler = _create_sampler(config)

        # Create provider
        provider = TracerProvider(resource=resource, sampler=sampler)

        # Create exporter
        exporter = OTLPSpanExporter(
            endpoint=config.endpoint,
            headers=config.headers or None,
            insecure=config.insecure,
        )

        # Add batch processor
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)

        # Set global provider
        trace.set_tracer_provider(provider)

        # Set global propagator
        if propagators:
            _propagator = CompositePropagator(propagators)
            set_global_textmap(_propagator)

        # Get tracer
        _tracer = trace.get_tracer("aragora.middleware", config.service_version)
        _otel_available = True
        set_span_exporter(export_span_to_otel)

        logger.info(
            "OpenTelemetry bridge initialized (direct): endpoint=%s, service=%s, sampler=%s",
            config.endpoint,
            config.service_name,
            config.sampler_type.value,
        )
        return True

    except ImportError as e:
        logger.debug(
            "OpenTelemetry not available: %s. Install with: pip install aragora[observability]",
            e,
        )
        return False
    except (RuntimeError, ValueError, TypeError, OSError) as e:
        logger.error("Failed to initialize OpenTelemetry bridge: %s", e)
        return False


def export_span_to_otel(span: Any) -> None:
    """Export an internal Span to OpenTelemetry.

    Converts the middleware Span object to an OpenTelemetry span and exports it.

    Args:
        span: Internal Span object from aragora.observability.middleware.trace_state
    """
    if not _otel_available or _tracer is None:
        return

    try:
        from opentelemetry.trace import Status, StatusCode

        # Create OTEL span
        with _tracer.start_as_current_span(
            span.operation,
            start_time=int(span.start_time * 1e9),  # Convert to nanoseconds
        ) as otel_span:
            # Set attributes
            for key, value in span.tags.items():
                if value is not None:
                    otel_span.set_attribute(key, value)

            # Add trace context
            otel_span.set_attribute("aragora.trace_id", span.trace_id)
            otel_span.set_attribute("aragora.span_id", span.span_id)
            if span.parent_span_id:
                otel_span.set_attribute("aragora.parent_span_id", span.parent_span_id)

            # Add events
            for event in span.events:
                otel_span.add_event(
                    event["name"],
                    attributes=event.get("attributes", {}),
                )

            # Set status
            if span.status == "error":
                otel_span.set_status(Status(StatusCode.ERROR, span.error or "Error"))
            else:
                otel_span.set_status(Status(StatusCode.OK))

    except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
        logger.debug("Failed to export span to OTEL: %s", e)


def inject_trace_context(headers: dict[str, str]) -> dict[str, str]:
    """Inject trace context into outgoing request headers.

    Uses W3C Trace Context format for propagation.

    Args:
        headers: Existing headers dictionary (modified in place)

    Returns:
        Headers dictionary with trace context added
    """
    if not _otel_available or _propagator is None:
        # Fall back to internal trace context
        try:
            from aragora.observability.middleware.trace_state import get_span_id, get_trace_id

            trace_id = get_trace_id()
            span_id = get_span_id()

            if trace_id:
                headers["X-Trace-ID"] = trace_id
                parent_id = span_id or "0000000000000000"
                trace_id_padded = trace_id.ljust(32, "0")[:32]
                parent_id_padded = parent_id.ljust(16, "0")[:16]
                headers["traceparent"] = f"00-{trace_id_padded}-{parent_id_padded}-01"
        except ImportError:
            pass
        return headers

    try:
        from opentelemetry import context

        _propagator.inject(headers, context.get_current())
    except (RuntimeError, ValueError, TypeError, AttributeError) as e:
        logger.debug("Failed to inject trace context: %s", e)

    return headers


def extract_trace_context(headers: dict[str, str]) -> Any:
    """Extract trace context from incoming request headers.

    Supports W3C Trace Context and custom X-Trace-ID headers.

    Args:
        headers: Request headers dictionary

    Returns:
        OpenTelemetry context or None
    """
    if not _otel_available or _propagator is None:
        return None

    try:
        ctx = _propagator.extract(headers)
        return ctx
    except (RuntimeError, ValueError, TypeError, AttributeError) as e:
        logger.debug("Failed to extract trace context: %s", e)
        return None


def get_current_trace_id() -> str | None:
    """Get the current trace ID from OpenTelemetry context.

    Returns:
        Current trace ID as hex string, or None if not in trace context
    """
    if not _otel_available:
        try:
            from aragora.observability.middleware.trace_state import get_trace_id

            return get_trace_id()
        except ImportError:
            return None

    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().trace_id, "032x")
    except (RuntimeError, ValueError, TypeError, AttributeError) as e:
        logger.debug("Failed to get trace ID: %s: %s", type(e).__name__, e)

    return None


def get_current_span_id() -> str | None:
    """Get the current span ID from OpenTelemetry context.

    Returns:
        Current span ID as hex string, or None if not in trace context
    """
    if not _otel_available:
        try:
            from aragora.observability.middleware.trace_state import get_span_id

            return get_span_id()
        except ImportError:
            return None

    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().span_id, "016x")
    except (RuntimeError, ValueError, TypeError, AttributeError) as e:
        logger.debug("Failed to get span ID: %s: %s", type(e).__name__, e)

    return None


def create_span_context(
    operation: str,
    parent_context: Any = None,
) -> Any:
    """Create a new span context for an operation.

    Args:
        operation: Name of the operation
        parent_context: Optional parent context for linking

    Returns:
        Context manager yielding the span
    """
    if not _otel_available or _tracer is None:
        # Fall back to internal tracing
        try:
            from aragora.observability.middleware.trace_state import trace_context

            return trace_context(operation)
        except ImportError:
            from contextlib import nullcontext

            return nullcontext()

    try:
        from opentelemetry import context as otel_context

        if parent_context:
            otel_context.attach(parent_context)

        return _tracer.start_as_current_span(operation)
    except (RuntimeError, ValueError, TypeError, AttributeError) as e:
        logger.debug("Failed to create span context: %s", e)
        from contextlib import nullcontext

        return nullcontext()


def shutdown_otel_bridge() -> None:
    """Shutdown the OpenTelemetry bridge gracefully.

    Ensures all pending spans are exported before shutdown.
    """
    global _otel_available, _tracer

    if not _otel_available:
        return

    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
        logger.info("OpenTelemetry bridge shutdown complete")
    except (RuntimeError, ValueError, TypeError, OSError) as e:
        logger.error("Error shutting down OpenTelemetry bridge: %s", e)
    finally:
        _otel_available = False
        _tracer = None
        set_span_exporter(None)


def is_otel_available() -> bool:
    """Check if OpenTelemetry is available and initialized.

    Returns:
        True if OTEL is available and initialized
    """
    return _otel_available


# =============================================================================
# Span enrichment helpers
# =============================================================================


def enrich_span_with_debate_context(
    span: Any,
    debate_id: str | None = None,
    round_number: int | None = None,
    agent_name: str | None = None,
    phase: str | None = None,
) -> None:
    """Enrich a span with debate-specific attributes.

    Adds structured attributes that enable filtering and grouping
    traces by debate, round, agent, and phase in observability backends.

    Safe to call with no-op spans or when OTel is not available.

    Args:
        span: The span to enrich (OTel span or internal span)
        debate_id: Debate identifier
        round_number: Current round number
        agent_name: Name of the agent involved
        phase: Debate phase (propose, critique, vote, revise, consensus)
    """
    if span is None:
        return

    attrs: dict[str, Any] = {}
    if debate_id:
        attrs["debate.id"] = debate_id
    if round_number is not None:
        attrs["debate.round_number"] = round_number
    if agent_name:
        attrs["agent.name"] = agent_name
    if phase:
        attrs["debate.phase"] = phase

    for key, value in attrs.items():
        try:
            if hasattr(span, "set_attribute"):
                span.set_attribute(key, value)
            elif hasattr(span, "set_tag"):
                span.set_tag(key, value)
        except (TypeError, ValueError) as e:
            logger.debug("Failed to set span attribute %s: %s", key, e)


def enrich_span_with_http_context(
    span: Any,
    method: str | None = None,
    path: str | None = None,
    status_code: int | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Enrich a span with HTTP request context attributes.

    Follows OpenTelemetry semantic conventions for HTTP spans.

    Args:
        span: The span to enrich
        method: HTTP method (GET, POST, etc.)
        path: Request path
        status_code: HTTP response status code
        client_ip: Client IP address
        user_agent: User-Agent header value
    """
    if span is None:
        return

    attrs: dict[str, Any] = {}
    if method:
        attrs["http.method"] = method
    if path:
        attrs["http.target"] = path
    if status_code is not None:
        attrs["http.status_code"] = status_code
    if client_ip:
        attrs["net.peer.ip"] = client_ip
    if user_agent:
        # Truncate to avoid huge attributes
        attrs["http.user_agent"] = user_agent[:200]

    for key, value in attrs.items():
        try:
            if hasattr(span, "set_attribute"):
                span.set_attribute(key, value)
            elif hasattr(span, "set_tag"):
                span.set_tag(key, value)
        except (TypeError, ValueError) as e:
            logger.debug("Failed to set span attribute %s: %s", key, e)


__all__ = [
    "OTelBridgeConfig",
    "SamplerType",
    "get_bridge_config",
    "init_otel_bridge",
    "export_span_to_otel",
    "inject_trace_context",
    "extract_trace_context",
    "get_current_trace_id",
    "get_current_span_id",
    "create_span_context",
    "shutdown_otel_bridge",
    "is_otel_available",
    "enrich_span_with_debate_context",
    "enrich_span_with_http_context",
]
