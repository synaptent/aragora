"""
Metrics-Tracing Correlation.

Provides utilities to correlate Prometheus metrics with distributed traces,
enabling drill-down from slow request metrics to specific traces.

Usage:
    from aragora.observability.trace_correlation import (
        get_trace_context,
        track_request_with_trace,
        should_sample_trace_id,
    )

    # Track request with trace correlation
    with track_request_with_trace("/api/debates", "POST"):
        # handle request

    # Get current trace context for custom metrics
    ctx = get_trace_context()
    if ctx.trace_id:
        my_metric.labels(trace_id=ctx.trace_id[:8]).observe(value)

Configuration:
    ARAGORA_TRACE_METRIC_SAMPLE_RATE: float (default: 0.01, 1%)
"""

from __future__ import annotations

import logging
import os
import random
import time
from contextlib import contextmanager
from dataclasses import dataclass
from collections.abc import Generator

from aragora.exceptions import REDIS_CONNECTION_ERRORS

logger = logging.getLogger(__name__)


# Sample rate for including trace_id in metrics (default 1%)
# High cardinality labels need sampling to avoid memory issues
def _parse_sample_rate(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid ARAGORA_TRACE_METRIC_SAMPLE_RATE='%s', using 0.01", raw)
        return 0.01
    if value < 0 or value > 1:
        logger.warning("ARAGORA_TRACE_METRIC_SAMPLE_RATE=%s out of range, using 0.01", value)
        return 0.01
    return value


TRACE_METRIC_SAMPLE_RATE = _parse_sample_rate(
    os.environ.get("ARAGORA_TRACE_METRIC_SAMPLE_RATE", "0.01")
)


@dataclass
class TraceContext:
    """Current trace context for metric correlation."""

    trace_id: str | None = None
    span_id: str | None = None
    sampled: bool = False

    @property
    def trace_id_short(self) -> str | None:
        """Get short trace ID (first 8 chars) for metric labels."""
        if self.trace_id:
            return self.trace_id[:8]
        return None

    def as_labels(self) -> dict[str, str]:
        """Get trace context as metric labels (if sampled)."""
        if self.sampled and self.trace_id:
            return {"trace_id": self.trace_id_short or ""}
        return {}


def get_trace_context() -> TraceContext:
    """
    Get the current trace context for metric correlation.

    Returns:
        TraceContext with trace_id, span_id, and sampling decision
    """
    try:
        from aragora.observability.middleware.tracing import get_trace_id, get_span_id

        trace_id = get_trace_id()
        span_id = get_span_id()
        sampled = should_sample_trace_id()

        return TraceContext(
            trace_id=trace_id,
            span_id=span_id,
            sampled=sampled,
        )
    except ImportError:
        return TraceContext()


def should_sample_trace_id() -> bool:
    """
    Determine if this request's trace_id should be included in metrics.

    Uses sampling to avoid high-cardinality label explosion.
    """
    return random.random() < TRACE_METRIC_SAMPLE_RATE


@contextmanager
def track_request_with_trace(
    endpoint: str,
    method: str = "GET",
    include_trace: bool = True,
) -> Generator[TraceContext, None, None]:
    """
    Context manager to track request latency with trace correlation.

    When sampled, includes trace_id in latency metrics for correlation.

    Args:
        endpoint: API endpoint path
        method: HTTP method
        include_trace: Whether to include trace correlation (can be disabled)

    Yields:
        TraceContext for the request

    Example:
        with track_request_with_trace("/api/debates", "POST") as ctx:
            # handle request
            if ctx.sampled:
                logger.info("Request traced", extra={"trace_id": ctx.trace_id})
    """
    from aragora.observability.server_metrics import API_REQUESTS, API_LATENCY

    ctx = get_trace_context() if include_trace else TraceContext()
    start = time.perf_counter()
    status = "success"

    try:
        yield ctx
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        status = "error"
        logger.warning("Request error on %s %s: %s", method, endpoint, e)
        raise
    except REDIS_CONNECTION_ERRORS as e:
        status = "error"
        logger.warning("I/O error on %s %s: %s", method, endpoint, e)
        raise
    except RuntimeError as e:
        status = "error"
        logger.warning("Runtime error on %s %s: %s", method, endpoint, e)
        raise
    finally:
        duration = time.perf_counter() - start

        # Always record basic metrics
        API_REQUESTS.inc(endpoint=endpoint, method=method, status=status)
        API_LATENCY.observe(duration, endpoint=endpoint, method=method)

        # Record trace-correlated metrics if sampled and slow
        # Only record trace_id for slow requests (>100ms) to focus on interesting cases
        if ctx.sampled and ctx.trace_id and duration > 0.1:
            _record_traced_latency(endpoint, method, duration, ctx.trace_id_short or "")


# Separate histogram for trace-correlated metrics (high cardinality)
_TRACED_LATENCY_SAMPLES: list[tuple[str, str, float, str]] = []
_TRACED_LATENCY_MAX_SAMPLES = 1000  # Keep memory bounded


def _record_traced_latency(endpoint: str, method: str, duration: float, trace_id: str) -> None:
    """Record a trace-correlated latency sample."""
    global _TRACED_LATENCY_SAMPLES

    # Bounded buffer to avoid memory issues
    if len(_TRACED_LATENCY_SAMPLES) >= _TRACED_LATENCY_MAX_SAMPLES:
        # Remove oldest 10%
        _TRACED_LATENCY_SAMPLES = _TRACED_LATENCY_SAMPLES[_TRACED_LATENCY_MAX_SAMPLES // 10 :]

    _TRACED_LATENCY_SAMPLES.append((endpoint, method, duration, trace_id))


def get_traced_latency_samples() -> list[tuple[str, str, float, str]]:
    """
    Get recent trace-correlated latency samples.

    Returns:
        List of (endpoint, method, duration, trace_id) tuples
    """
    return list(_TRACED_LATENCY_SAMPLES)


def clear_traced_latency_samples() -> None:
    """Clear the trace-correlated latency samples."""
    global _TRACED_LATENCY_SAMPLES
    _TRACED_LATENCY_SAMPLES = []


def get_slow_traces(threshold_seconds: float = 1.0) -> list[dict]:
    """
    Get traces for slow requests.

    Useful for debugging performance issues - find the trace_id
    of slow requests and look them up in your tracing backend.

    Args:
        threshold_seconds: Minimum duration to consider "slow"

    Returns:
        List of dicts with endpoint, method, duration, trace_id
    """
    slow = []
    for endpoint, method, duration, trace_id in _TRACED_LATENCY_SAMPLES:
        if duration >= threshold_seconds:
            slow.append(
                {
                    "endpoint": endpoint,
                    "method": method,
                    "duration_seconds": round(duration, 3),
                    "trace_id": trace_id,
                }
            )
    return sorted(slow, key=lambda x: x["duration_seconds"], reverse=True)


def generate_exemplar_line(trace_id: str, duration: float) -> str:
    """
    Generate a Prometheus exemplar annotation.

    Exemplars link metrics to traces in Prometheus/Grafana.

    Args:
        trace_id: Trace ID to link
        duration: Metric value

    Returns:
        Exemplar line in Prometheus format
    """
    # Format: # {trace_id="abc123"} value timestamp
    return f' # {{trace_id="{trace_id}"}} {duration}'


__all__ = [
    "TraceContext",
    "get_trace_context",
    "should_sample_trace_id",
    "track_request_with_trace",
    "get_traced_latency_samples",
    "clear_traced_latency_samples",
    "get_slow_traces",
    "generate_exemplar_line",
    "TRACE_METRIC_SAMPLE_RATE",
]
