"""
Response utilities for HTTP handlers.

This module provides helper methods for sending HTTP responses with
proper headers (CORS, security, rate limiting, tracing).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, BinaryIO, Protocol

if TYPE_CHECKING:
    from aragora.server.middleware.rate_limit import RateLimitResult

logger = logging.getLogger(__name__)


class _HTTPHandlerProtocol(Protocol):
    """Protocol defining the interface expected from HTTP handler classes."""

    _rate_limit_result: RateLimitResult | None
    _response_status: int
    headers: Any
    wfile: BinaryIO

    def send_response(self, code: int) -> None: ...
    def send_header(self, keyword: str, value: str) -> None: ...
    def end_headers(self) -> None: ...


class ResponseHelpersMixin:
    """Mixin providing HTTP response helper methods.

    This mixin expects the following methods from the parent class:
    - send_response(status: int)
    - send_header(name: str, value: str)
    - end_headers()
    - wfile.write(data: bytes)
    - headers (dict-like)

    And these class attributes:
    - _rate_limit_result: RateLimitResult | None
    - _response_status: int

    Type stubs are provided for mypy compatibility.
    """

    # Type stubs for mypy - actual implementations come from BaseHTTPRequestHandler
    if TYPE_CHECKING:
        _rate_limit_result: RateLimitResult | None
        _response_status: int
        headers: Any
        wfile: BinaryIO

        def send_response(self, code: int, message: str | None = None) -> None: ...
        def send_header(self, keyword: str, value: str) -> None: ...
        def end_headers(self) -> None: ...

    def _send_json(
        self,
        data: Any,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Send JSON response with all standard headers."""
        self._response_status = status
        content = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self._add_cors_headers()
        self._add_security_headers()
        self._add_rate_limit_headers()
        self._add_trace_headers()
        self._add_version_headers()
        self._add_v1_deprecation_headers()
        if headers:
            for name, value in headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    def _add_version_headers(self) -> None:
        """Add X-API-Version header to all API responses.

        Extracts the API version from the request path and includes it
        in the response. Has zero overhead for non-API requests.
        """
        try:
            path = getattr(self, "path", "")
            if path and path.startswith("/api/"):
                from aragora.server.middleware.versioning import get_api_version

                version = get_api_version(path)
                self.send_header("X-API-Version", version.value)
        except (ImportError, AttributeError, ValueError, OSError) as e:
            logger.debug("Version header injection failed: %s", e)

    def _add_v1_deprecation_headers(self) -> None:
        """Add v1 API deprecation/sunset headers if this is a v1 request.

        Only adds headers for /api/v1/ paths. Has zero overhead for
        non-v1 requests. Can be disabled via ARAGORA_DISABLE_V1_DEPRECATION=true.
        """
        try:
            from aragora.server.middleware.deprecation import add_v1_headers_to_handler

            # self.path is set by BaseHTTPRequestHandler
            path = getattr(self, "path", "")
            if path:
                add_v1_headers_to_handler(self, path)
        except (ImportError, AttributeError, ValueError) as e:
            # Never let deprecation header injection break a response
            logger.debug("Deprecation header injection failed: %s", e)

    def _add_trace_headers(self) -> None:
        """Add trace ID header to response for correlation."""
        try:
            from aragora.server.middleware.correlation import get_correlation

            ctx = get_correlation()
        except (ImportError, AttributeError):
            ctx = None

        if ctx is not None:
            try:
                from aragora.server.middleware.request_logging import REQUEST_ID_HEADER

                self.send_header(REQUEST_ID_HEADER, ctx.request_id)
            except (ImportError, AttributeError):
                logger.debug("Failed to send request ID header", exc_info=True)
            from aragora.observability.middleware.tracing import (
                PARENT_SPAN_HEADER,
                SPAN_ID_HEADER,
                TRACE_ID_HEADER,
            )

            self.send_header(TRACE_ID_HEADER, ctx.trace_id)
            self.send_header(SPAN_ID_HEADER, ctx.span_id)
            if ctx.parent_span_id:
                self.send_header(PARENT_SPAN_HEADER, ctx.parent_span_id)
            return

        # Fallback to legacy context vars
        try:
            from aragora.server.middleware.request_logging import (
                REQUEST_ID_HEADER,
                get_current_request_id,
            )

            request_id = get_current_request_id()
            if request_id:
                self.send_header(REQUEST_ID_HEADER, request_id)
        except (ImportError, AttributeError):
            logger.debug("Failed to send legacy request ID header", exc_info=True)

        from aragora.observability.middleware.tracing import (
            PARENT_SPAN_HEADER,
            SPAN_ID_HEADER,
            TRACE_ID_HEADER,
            get_parent_span_id,
            get_span_id,
            get_trace_id,
        )

        trace_id = get_trace_id()
        if trace_id:
            self.send_header(TRACE_ID_HEADER, trace_id)
        span_id = get_span_id()
        if span_id:
            self.send_header(SPAN_ID_HEADER, span_id)
        parent_span_id = get_parent_span_id()
        if parent_span_id:
            self.send_header(PARENT_SPAN_HEADER, parent_span_id)

    def _add_rate_limit_headers(self) -> None:
        """Add rate limit headers to response.

        Includes X-RateLimit-Limit, X-RateLimit-Remaining, and X-RateLimit-Reset
        headers if a rate limit check was performed for this request.
        """
        result = getattr(self, "_rate_limit_result", None)
        if result is None:
            return

        from aragora.server.middleware.rate_limit import rate_limit_headers

        headers = rate_limit_headers(result)
        for name, value in headers.items():
            self.send_header(name, value)

    def _add_security_headers(self) -> None:
        """Add security headers to prevent common attacks."""
        # Prevent clickjacking
        self.send_header("X-Frame-Options", "DENY")
        # Prevent MIME type sniffing
        self.send_header("X-Content-Type-Options", "nosniff")
        # Enable XSS filter
        self.send_header("X-XSS-Protection", "1; mode=block")
        # Referrer policy - don't leak internal URLs
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        # Content Security Policy - prevent XSS and data injection
        # Note: 'unsafe-inline' for styles needed by CSS-in-JS frameworks
        # 'unsafe-eval' removed for security - blocks eval()/new Function()
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self' wss: https:; "
            "font-src 'self' data:; "
            "frame-ancestors 'none'",
        )
        # HTTP Strict Transport Security - enforce HTTPS
        self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    def _add_cors_headers(self) -> None:
        """Add CORS headers with origin validation."""
        from aragora.server.cors_config import cors_config

        # Security: Validate origin against centralized allowlist
        request_origin = self.headers.get("Origin", "")

        if cors_config.is_origin_allowed(request_origin):
            self.send_header("Access-Control-Allow-Origin", request_origin)
            # Allow credentials (cookies, authorization headers) for authenticated requests
            self.send_header("Access-Control-Allow-Credentials", "true")
        elif not request_origin:
            # Same-origin requests don't have Origin header
            pass
        # else: no CORS header = browser blocks cross-origin request

        # Support all REST methods including DELETE for privacy endpoints
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Filename, Authorization, Accept, Origin, X-Requested-With",
        )
        # Cache preflight response for 1 hour to reduce OPTIONS requests
        self.send_header("Access-Control-Max-Age", "3600")


__all__ = ["ResponseHelpersMixin"]
