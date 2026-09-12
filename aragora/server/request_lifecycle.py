"""
Request lifecycle management for HTTP handlers.

Centralizes the common request handling pattern:
- State reset
- Timing and tracing
- Error handling
- Metrics and logging
- Timeout enforcement

This eliminates repetition across do_GET, do_POST, do_PUT, etc.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import TYPE_CHECKING, Any
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

if TYPE_CHECKING:
    from aragora.server.tracing_service import TracingService

logger = logging.getLogger(__name__)

# Timeout middleware integration (graceful degradation if not available)
_timeout_config_factory: Callable | None = None
_timeout_executor_factory: Callable | None = None

try:
    from aragora.server.middleware.timeout import (
        get_executor as _get_timeout_executor,
        get_timeout_config as _get_timeout_config,
    )

    _timeout_config_factory = _get_timeout_config
    _timeout_executor_factory = _get_timeout_executor
except ImportError:
    logger.debug(
        "Timeout middleware not available, requests will proceed without timeout enforcement"
    )
    _timeout_config_factory = None
    _timeout_executor_factory = None


def _get_request_timeout(path: str) -> float | None:
    """Get the timeout for a request path, or None if timeout is not available."""
    if _timeout_config_factory is None:
        return None
    try:
        config = _timeout_config_factory()
        return config.get_timeout(path)
    except (ValueError, TypeError, RuntimeError, AttributeError) as e:
        logger.debug("Could not get timeout config: %s", e)
        return None


def _get_executor() -> ThreadPoolExecutor | None:
    """Get the timeout executor, or None if not available."""
    if _timeout_executor_factory is None:
        return None
    try:
        return _timeout_executor_factory()
    except (ValueError, TypeError, RuntimeError, AttributeError) as e:
        logger.debug("Could not get timeout executor: %s", e)
        return None


class RequestLifecycleManager:
    """Manages the lifecycle of HTTP requests.

    Handles the common boilerplate for all HTTP methods:
    - State reset
    - Timing measurement
    - Distributed tracing
    - Timeout enforcement
    - Error handling with proper span recording
    - Prometheus metrics recording
    - Request logging

    Usage:
        lifecycle = RequestLifecycleManager(handler, tracing)
        lifecycle.handle_request(
            method="GET",
            internal_handler=self._do_GET_internal,
            path_arg=path,
            query_arg=query,
        )
    """

    def __init__(
        self,
        handler: Any,  # UnifiedHandler instance
        tracing: TracingService | None = None,
        record_metrics_fn: Callable[[str, str, int, float], None] | None = None,
        log_request_fn: Callable[[str, str, int, float], None] | None = None,
        normalize_endpoint_fn: Callable[[str], str] | None = None,
    ):
        """Initialize the lifecycle manager.

        Args:
            handler: The HTTP handler instance (for sending responses)
            tracing: TracingService for distributed tracing
            record_metrics_fn: Function to record Prometheus metrics
            log_request_fn: Function to log request details
            normalize_endpoint_fn: Function to normalize endpoint paths
        """
        self.handler = handler
        self.tracing = tracing
        self._record_metrics = record_metrics_fn
        self._log_request = log_request_fn
        self._normalize_endpoint = normalize_endpoint_fn

    def handle_request(
        self,
        method: str,
        internal_handler: Callable,
        *,
        with_query: bool = False,
        trace_api_only: bool = True,
        record_api_metrics_only: bool = True,
    ) -> None:
        """Execute the request lifecycle.

        Args:
            method: HTTP method (GET, POST, etc.)
            internal_handler: The _do_METHOD_internal function to call
            with_query: Whether to parse and pass query parameters
            trace_api_only: Only start tracing for /api/* paths
            record_api_metrics_only: Only record metrics for /api/* paths
        """
        # Reset per-request state
        self.handler._rate_limit_result = None
        self.handler._response_status = 200

        start_time = time.time()
        parsed = urlparse(self.handler.path)
        path = parsed.path
        query = parse_qs(parsed.query) if with_query else {}

        is_api_request = path.startswith("/api/")

        request_headers: dict[str, str] = {}
        if hasattr(self.handler, "headers"):
            try:
                request_headers = {k: v for k, v in self.handler.headers.items()}
            except (AttributeError, TypeError):
                logger.debug("Failed to extract request headers", exc_info=True)
                request_headers = {}

        request_id: str | None = None
        try:
            from aragora.server.middleware.request_logging import (
                REQUEST_ID_HEADER,
                generate_request_id,
            )

            request_id = (
                request_headers.get(REQUEST_ID_HEADER)
                or request_headers.get(REQUEST_ID_HEADER.lower())
                or generate_request_id()
            )
        except (ImportError, AttributeError):
            logger.debug("Request ID generation unavailable", exc_info=True)
            request_id = None

        # Start tracing span for API requests
        span = None
        if self.tracing and (is_api_request or not trace_api_only):
            span = self.tracing.start_request_span(method, path, request_headers)

            # Bind correlation context to tracing span if available
            try:
                from aragora.server.middleware.correlation import init_correlation

                init_correlation(
                    request_headers,
                    request_id=request_id,
                    trace_id=span.trace_id,
                    span_id=span.span_id,
                    parent_span_id=span.parent_span_id,
                )
            except (ImportError, AttributeError):
                logger.debug("Correlation context init failed with tracing span", exc_info=True)
                try:
                    from aragora.server.middleware.request_logging import set_current_request_id

                    if request_id:
                        set_current_request_id(request_id)
                except (ImportError, AttributeError):
                    logger.debug("Fallback request ID binding also failed", exc_info=True)
        else:
            # Even without tracing, establish correlation context for logs/headers
            try:
                from aragora.server.middleware.correlation import init_correlation

                init_correlation(request_headers, request_id=request_id)
            except (ImportError, AttributeError):
                logger.debug("Correlation context init failed (no tracing)", exc_info=True)
                try:
                    from aragora.server.middleware.request_logging import set_current_request_id

                    if request_id:
                        set_current_request_id(request_id)
                except (ImportError, AttributeError):
                    logger.debug("Fallback request ID binding also failed", exc_info=True)

        # Determine timeout for this request
        timeout_seconds = _get_request_timeout(path)
        timed_out = False

        try:
            # Call the internal handler with timeout enforcement if available
            if timeout_seconds is not None:
                executor = _get_executor()
                if executor is not None:
                    # Execute handler in thread pool with timeout
                    if with_query:
                        future = executor.submit(internal_handler, path, query)
                    else:
                        future = executor.submit(internal_handler, path)

                    try:
                        future.result(timeout=timeout_seconds)
                    except FuturesTimeoutError:
                        timed_out = True
                        future.cancel()
                        self.handler._response_status = 504
                        logger.warning(
                            "[request] Request timeout after %ss: %s %s",
                            timeout_seconds,
                            method,
                            path,
                        )
                        self._send_timeout_response(timeout_seconds, path)
                else:
                    # Executor not available, fall through to direct call
                    if with_query:
                        internal_handler(path, query)
                    else:
                        internal_handler(path)
            else:
                # No timeout configured, call directly (graceful degradation)
                if with_query:
                    internal_handler(path, query)
                else:
                    internal_handler(path)

        except Exception as e:  # noqa: BLE001 - Top-level safety net: must catch all unhandled handler errors
            # Top-level safety net for handlers (not triggered for timeout)
            if not timed_out:
                self.handler._response_status = 500
                logger.exception("[request] Unhandled exception in %s %s: %s", method, path, e)
                if span:
                    span.set_error(e)
                self._send_error_response()

        finally:
            status_code = getattr(self.handler, "_response_status", 200)
            duration_seconds = time.time() - start_time

            # Finish tracing span
            if span and self.tracing:
                self.tracing.finish_request_span(span, status_code)

            # Record Prometheus metrics
            if self._record_metrics and (is_api_request or not record_api_metrics_only):
                endpoint = path
                if self._normalize_endpoint:
                    endpoint = self._normalize_endpoint(path)
                self._record_metrics(method, endpoint, status_code, duration_seconds)

            # Log the request
            if self._log_request:
                duration_ms = duration_seconds * 1000
                self._log_request(method, path, status_code, duration_ms)

    def _send_error_response(self) -> None:
        """Send a JSON error response if possible."""
        try:
            self.handler._send_json({"error": "Internal server error"}, status=500)
        except (OSError, ConnectionError, RuntimeError) as send_err:
            logger.debug("Could not send error response (already sent?): %s", send_err)

    def _send_timeout_response(self, timeout_seconds: float, path: str) -> None:
        """Send a 504 Gateway Timeout response.

        Args:
            timeout_seconds: The timeout that was exceeded
            path: The request path
        """
        try:
            # Calculate Retry-After header (suggest waiting before retry)
            retry_after = min(int(timeout_seconds * 0.5), 60)  # Half of timeout, max 60s

            response_body = {
                "error": "Gateway Timeout",
                "message": f"Request timed out after {timeout_seconds}s",
                "code": "request_timeout",
                "timeout_seconds": timeout_seconds,
                "path": path,
            }

            # Send response with timeout headers
            self.handler._send_json(
                response_body,
                status=504,
                headers={
                    "Retry-After": str(retry_after),
                    "X-Timeout-Seconds": str(timeout_seconds),
                },
            )
        except (OSError, ConnectionError, RuntimeError) as send_err:
            logger.debug("Could not send timeout response (already sent?): %s", send_err)


def create_lifecycle_manager(handler: Any) -> RequestLifecycleManager:
    """Factory function to create a lifecycle manager from a handler.

    This convenience function extracts the necessary components from the handler
    and creates a properly configured lifecycle manager.

    Args:
        handler: UnifiedHandler instance

    Returns:
        Configured RequestLifecycleManager
    """
    from aragora.server.prometheus import record_http_request

    _record_endpoint_request: Callable[[str, str, int, float], None] | None = None
    try:
        from aragora.server.handlers.observability.endpoint_analytics import record_endpoint_request

        _record_endpoint_request = record_endpoint_request
    except ImportError:
        pass

    def _record_metrics(method: str, endpoint: str, status: int, duration: float) -> None:
        record_http_request(method, endpoint, status, duration)
        if _record_endpoint_request is not None:
            _record_endpoint_request(endpoint, method, status, duration)

    return RequestLifecycleManager(
        handler=handler,
        tracing=getattr(handler, "tracing", None),
        record_metrics_fn=_record_metrics,
        log_request_fn=getattr(handler, "_log_request", None),
        normalize_endpoint_fn=getattr(handler, "_normalize_endpoint", None),
    )
