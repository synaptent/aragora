"""
Distributed Tracing Middleware.

Adds trace ID propagation and request timing for observability.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class TracingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for distributed tracing.

    - Generates or propagates trace IDs
    - Generates request IDs
    - Records request timing
    - Adds correlation headers to responses
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request.state.start_time = time.perf_counter()

        ctx = None
        try:
            from aragora.server.middleware.correlation import init_correlation
            from aragora.server.middleware.request_logging import (
                REQUEST_ID_HEADER,
                generate_request_id,
            )

            headers = dict(request.headers)
            request_id = (
                headers.get(REQUEST_ID_HEADER)
                or headers.get(REQUEST_ID_HEADER.lower())
                or generate_request_id()
            )
            ctx = init_correlation(headers, request_id=request_id)

            request.state.trace_id = ctx.trace_id
            request.state.request_id = ctx.request_id
            request.state.span_id = ctx.span_id
        except ImportError:
            # Fall back to minimal timing-only behavior if correlation setup fails
            pass

        response = await call_next(request)

        duration_ms = (time.perf_counter() - request.state.start_time) * 1000
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"

        if ctx is not None:
            try:
                from aragora.server.middleware.request_logging import REQUEST_ID_HEADER
                from aragora.observability.middleware.tracing import (
                    PARENT_SPAN_HEADER,
                    SPAN_ID_HEADER,
                    TRACE_ID_HEADER,
                )

                response.headers[REQUEST_ID_HEADER] = ctx.request_id
                response.headers[TRACE_ID_HEADER] = ctx.trace_id
                response.headers[SPAN_ID_HEADER] = ctx.span_id
                if ctx.parent_span_id:
                    response.headers[PARENT_SPAN_HEADER] = ctx.parent_span_id
            except (ImportError, AttributeError, KeyError) as exc:
                logger.debug("Failed to set tracing headers: %s", exc)

        return response
