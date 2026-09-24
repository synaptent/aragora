"""
V1 API Sunset Deprecation Middleware.

Automatically adds RFC 8594 compliant deprecation and sunset headers
to all v1 API responses. This middleware is part of the v1 sunset
preparation and should be active until v1 endpoints are removed.

Features:
- Sunset header (RFC 8594) with date 2026-06-01
- Deprecation header with announcement date
- Link header pointing to migration documentation
- X-API-Version-Warning custom header for easy detection
- Usage logging for monitoring migration progress
- Only applies to /api/v1/ endpoints (v2 is unaffected)
- Configurable via ARAGORA_DISABLE_V1_DEPRECATION env var

Usage:
    # As aiohttp middleware
    from aragora.server.middleware.deprecation import (
        v1_sunset_middleware,
        create_v1_sunset_middleware,
    )
    app.middlewares.append(v1_sunset_middleware)

    # Standalone header injection (for non-aiohttp handlers)
    from aragora.server.middleware.deprecation import (
        inject_v1_deprecation_headers,
        get_v1_deprecation_headers,
    )
    headers = get_v1_deprecation_headers(path="/api/v1/debates")
    inject_v1_deprecation_headers(response_headers, path="/api/v1/debates")
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import central constants
# ---------------------------------------------------------------------------

from aragora.server.versioning.constants import (
    CURRENT_API_VERSION,
    ENV_DISABLE_DEPRECATION_HEADERS,
    MIGRATION_DOCS_URL,
    V1_DEPRECATION_TIMESTAMP,
    V1_SUNSET_HTTP_DATE,
    V1_SUNSET_ISO,
    days_until_v1_sunset,
    deprecation_level,
)

# ---------------------------------------------------------------------------
# V1 path detection
# ---------------------------------------------------------------------------

_V1_PATH_RE = re.compile(r"^/api/v1(/|$)")


def is_v1_request(path: str) -> bool:
    """Check whether a request path targets the v1 API.

    Only paths starting with /api/v1/ (or exactly /api/v1) are considered v1.
    Paths like /api/v2/, /api/debates, /health, etc. are NOT v1.

    Args:
        path: The request URL path.

    Returns:
        True if the path targets the v1 API.
    """
    return bool(_V1_PATH_RE.match(path))


# ---------------------------------------------------------------------------
# Header construction
# ---------------------------------------------------------------------------


def get_v1_deprecation_headers(path: str | None = None) -> dict[str, str]:
    """Build the full set of deprecation headers for a v1 API response.

    Headers returned (RFC 8594 compliant):
        Sunset          - HTTP-date when v1 will be removed
        Deprecation     - RFC 8594 @<unix-timestamp> indicating deprecation
        Link            - URI to migration documentation with rel="sunset"
        X-API-Version   - Current API version the client should migrate to
        X-API-Version-Warning - Human-readable deprecation notice
        X-API-Sunset    - ISO 8601 sunset date for easy parsing
        X-Deprecation-Level - Current severity (warning/critical/sunset)

    Args:
        path: Optional request path for more specific Link header.

    Returns:
        Dictionary of header name to header value.
    """
    level = deprecation_level()
    days_left = days_until_v1_sunset()

    headers: dict[str, str] = {
        # RFC 8594 Sunset header
        "Sunset": V1_SUNSET_HTTP_DATE,
        # RFC draft Deprecation header
        "Deprecation": f"@{V1_DEPRECATION_TIMESTAMP}",
        # Link to migration docs
        "Link": f'<{MIGRATION_DOCS_URL}>; rel="sunset"',
        # Custom headers for easy programmatic detection
        "X-API-Version": "v1",
        "X-API-Version-Warning": (
            f"API v1 is deprecated and will be removed on {V1_SUNSET_ISO}. "
            f"Please migrate to API {CURRENT_API_VERSION}. "
            f"See {MIGRATION_DOCS_URL} for details."
        ),
        "X-API-Sunset": V1_SUNSET_ISO,
        "X-Deprecation-Level": level,
    }

    # Add replacement link if we can infer the v2 equivalent
    if path and path.startswith("/api/v1/"):
        v2_path = path.replace("/api/v1/", f"/api/{CURRENT_API_VERSION}/", 1)
        headers["Link"] = (
            f'<{MIGRATION_DOCS_URL}>; rel="sunset", <{v2_path}>; rel="successor-version"'
        )

    # Add urgency indicator when close to sunset
    if level == "critical":
        headers["X-API-Version-Warning"] = (
            f"URGENT: API v1 is deprecated and will be removed in {days_left} days "
            f"({V1_SUNSET_ISO}). "
            f"Migrate to API {CURRENT_API_VERSION} immediately. "
            f"See {MIGRATION_DOCS_URL}"
        )
    elif level == "sunset":
        headers["X-API-Version-Warning"] = (
            f"API v1 has passed its sunset date ({V1_SUNSET_ISO}) and may "
            f"be removed at any time. Use API {CURRENT_API_VERSION} instead. "
            f"See {MIGRATION_DOCS_URL}"
        )

    return headers


def inject_v1_deprecation_headers(
    response_headers: dict[str, str],
    path: str | None = None,
) -> dict[str, str]:
    """Inject v1 deprecation headers into an existing headers dict.

    Modifies the dict in place and returns it for convenience.

    Args:
        response_headers: Mutable dict of response headers.
        path: Optional request path for v2 equivalent Link.

    Returns:
        The same dict with deprecation headers added.
    """
    deprecation_headers = get_v1_deprecation_headers(path)
    response_headers.update(deprecation_headers)
    return response_headers


# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------


@dataclass
class V1UsageTracker:
    """Tracks v1 API usage for migration monitoring.

    Provides counters and statistics to help operators understand
    which v1 endpoints are still actively used.
    """

    total_requests: int = 0
    requests_by_path: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    requests_by_method: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    first_seen: float = field(default_factory=time.time)
    last_request_time: float = 0.0
    _log_interval: int = 100  # Log summary every N requests

    def record(self, path: str, method: str, client_info: str = "") -> None:
        """Record a v1 API request.

        Args:
            path: Request path.
            method: HTTP method.
            client_info: Optional client identifier for tracking.
        """
        self.total_requests += 1
        self.requests_by_path[path] += 1
        self.requests_by_method[method.upper()] += 1
        self.last_request_time = time.time()

        # Record Prometheus metrics
        try:
            from aragora.observability.prometheus import record_v1_api_request

            record_v1_api_request(path, method.upper())
        except ImportError:
            pass

        # Log individual deprecated access
        logger.warning(
            "v1_api_access: %s %s (client=%s, total_v1_requests=%d, "
            "days_until_sunset=%d, level=%s)",
            method,
            path,
            client_info or "unknown",
            self.total_requests,
            days_until_v1_sunset(),
            deprecation_level(),
        )

        # Periodic summary
        if self.total_requests % self._log_interval == 0:
            self._log_summary()

    def _log_summary(self) -> None:
        """Log a summary of v1 usage."""
        top_paths = sorted(
            self.requests_by_path.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:10]

        logger.info(
            "v1_api_usage_summary: total=%d, top_endpoints=%s, days_until_sunset=%d",
            self.total_requests,
            [(p, c) for p, c in top_paths],
            days_until_v1_sunset(),
        )

    def get_stats(self) -> dict[str, Any]:
        """Get usage statistics as a dictionary.

        Returns:
            Dictionary with usage stats suitable for JSON serialization.
        """
        top_paths = sorted(
            self.requests_by_path.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:20]

        return {
            "total_v1_requests": self.total_requests,
            "top_endpoints": [{"path": p, "count": c} for p, c in top_paths],
            "requests_by_method": dict(self.requests_by_method),
            "tracking_since": self.first_seen,
            "last_request": self.last_request_time,
            "days_until_sunset": days_until_v1_sunset(),
            "deprecation_level": deprecation_level(),
            "sunset_date": V1_SUNSET_ISO,
        }


# Global tracker instance
_usage_tracker = V1UsageTracker()


def get_v1_usage_tracker() -> V1UsageTracker:
    """Get the global v1 usage tracker instance."""
    return _usage_tracker


def reset_v1_usage_tracker() -> None:
    """Reset the global v1 usage tracker (for testing)."""
    global _usage_tracker
    _usage_tracker = V1UsageTracker()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def is_deprecation_middleware_enabled() -> bool:
    """Check whether the v1 deprecation middleware is enabled.

    Controlled by the ARAGORA_DISABLE_V1_DEPRECATION environment variable.
    The middleware is enabled by default; set the env var to 'true' to disable.

    Returns:
        True if the middleware should be active.
    """
    disabled = os.environ.get(ENV_DISABLE_DEPRECATION_HEADERS, "false").lower()
    return disabled not in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# aiohttp Middleware
# ---------------------------------------------------------------------------

# Type alias for aiohttp handler
try:
    from aiohttp import web

    Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

    @web.middleware
    async def v1_sunset_middleware(
        request: web.Request,
        handler: Handler,
    ) -> web.StreamResponse:
        """aiohttp middleware that adds deprecation headers to v1 API responses.

        This middleware:
        1. Checks if the request targets a v1 API endpoint
        2. If not v1, passes through with zero overhead
        3. If v1, adds all deprecation/sunset headers to the response
        4. Logs the v1 usage for migration monitoring
        5. Can be disabled via ARAGORA_DISABLE_V1_DEPRECATION=true

        The middleware does NOT block any requests -- it only adds headers
        and logs usage. Blocking of sunset endpoints is handled separately
        by the deprecation_enforcer middleware.
        """
        path = request.path

        # Fast path: skip non-v1 requests entirely
        if not is_v1_request(path):
            return await handler(request)

        # Check if middleware is disabled
        if not is_deprecation_middleware_enabled():
            return await handler(request)

        # Track usage
        client_info = request.headers.get(
            "X-Client-ID",
            request.headers.get("User-Agent", ""),
        )[:100]  # Truncate for safety
        _usage_tracker.record(path, request.method, client_info)

        # Call the actual handler
        response = await handler(request)

        # Inject deprecation headers into the response
        deprecation_headers = get_v1_deprecation_headers(path)
        for key, value in deprecation_headers.items():
            response.headers[key] = value

        return response

    def create_v1_sunset_middleware() -> Callable:
        """Create the v1 sunset deprecation middleware.

        Returns:
            aiohttp middleware function that can be added to app.middlewares.
        """
        return v1_sunset_middleware

except ImportError:
    # aiohttp not available - provide stubs; mypy sees these as redefinitions
    # of the names conditionally defined in the try block.
    def v1_sunset_middleware(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        """Stub when aiohttp is not available."""
        raise RuntimeError("aiohttp is required for v1_sunset_middleware")

    def create_v1_sunset_middleware() -> Callable:  # type: ignore[misc]
        """Stub when aiohttp is not available."""
        raise RuntimeError("aiohttp is required for v1_sunset_middleware")


# ---------------------------------------------------------------------------
# BaseHTTPRequestHandler support
# ---------------------------------------------------------------------------


def add_v1_headers_to_handler(handler: Any, path: str) -> None:
    """Add v1 deprecation headers using BaseHTTPRequestHandler.send_header.

    For use with the ThreadingHTTPServer-based unified_server.py.

    Args:
        handler: HTTP handler with send_header() method.
        path: The request path.
    """
    if not is_v1_request(path):
        return

    if not is_deprecation_middleware_enabled():
        return

    deprecation_headers = get_v1_deprecation_headers(path)
    if hasattr(handler, "send_header"):
        for key, value in deprecation_headers.items():
            handler.send_header(key, value)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    # Core functions
    "get_v1_deprecation_headers",
    "inject_v1_deprecation_headers",
    "is_v1_request",
    # aiohttp middleware
    "create_v1_sunset_middleware",
    "v1_sunset_middleware",
    # BaseHTTPRequestHandler support
    "add_v1_headers_to_handler",
    # Usage tracking
    "V1UsageTracker",
    "get_v1_usage_tracker",
    "reset_v1_usage_tracker",
    # Configuration
    "is_deprecation_middleware_enabled",
]
