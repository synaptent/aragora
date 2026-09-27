"""
API Metrics for Aragora.

Tracks API requests, latency, and WebSocket connections.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from collections.abc import Generator

from .types import Counter, Gauge, Histogram
from aragora.exceptions import REDIS_CONNECTION_ERRORS

logger = logging.getLogger(__name__)

# =============================================================================
# API Metrics
# =============================================================================

API_REQUESTS = Counter(
    name="aragora_api_requests_total",
    help="Total API requests by endpoint and status",
    label_names=["endpoint", "method", "status"],
)

API_LATENCY = Histogram(
    name="aragora_api_latency_seconds",
    help="API request latency in seconds",
    label_names=["endpoint", "method"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

ACTIVE_DEBATES = Gauge(
    name="aragora_active_debates",
    help="Currently running debates",
    label_names=[],
)
ACTIVE_DEBATES.set(0)

WEBSOCKET_CONNECTIONS = Gauge(
    name="aragora_websocket_connections",
    help="Active WebSocket connections",
    label_names=[],
)


# =============================================================================
# Helpers
# =============================================================================


@contextmanager
def track_request(endpoint: str, method: str = "GET") -> Generator[None, None, None]:
    """Context manager to track request latency."""
    start = time.perf_counter()
    status = "success"
    try:
        yield
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        # Application-level errors (validation, type issues, missing keys/attrs)
        status = "error"
        logger.warning("Request error on %s %s: %s", method, endpoint, e)
        raise
    except REDIS_CONNECTION_ERRORS as e:
        # I/O and network-related errors
        status = "error"
        logger.warning("I/O error on %s %s: %s", method, endpoint, e)
        raise
    except RuntimeError as e:
        # Runtime errors (async issues, recursion, etc.)
        status = "error"
        logger.warning("Runtime error on %s %s: %s", method, endpoint, e)
        raise
    finally:
        duration = time.perf_counter() - start
        API_REQUESTS.inc(endpoint=endpoint, method=method, status=status)
        API_LATENCY.observe(duration, endpoint=endpoint, method=method)


__all__ = [
    "API_REQUESTS",
    "API_LATENCY",
    "ACTIVE_DEBATES",
    "WEBSOCKET_CONNECTIONS",
    "track_request",
]
