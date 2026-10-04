"""
API Deprecation Enforcement Middleware.

Wires the deprecation registry into the aiohttp request lifecycle,
ensuring deprecation headers are added and sunset endpoints are blocked.

This module bridges the gap between the deprecation registry
(aragora.server.versioning.deprecation) and the actual HTTP layer.

Features:
- Automatic deprecation header injection (RFC 8594)
- Sunset endpoint blocking (HTTP 410 Gone)
- Usage tracking for deprecation metrics
- Pattern-based endpoint matching
- Prometheus metrics integration

Usage:
    from aragora.server.middleware.deprecation_enforcer import (
        DeprecationEnforcer,
        create_deprecation_middleware,
        register_deprecated_endpoint,
    )

    # At startup, register deprecated endpoints
    register_deprecated_endpoint(
        path="/api/v1/debates",
        methods=["GET", "POST"],
        sunset_date=date(2026, 6, 1),
        replacement="/api/v2/debates",
    )

    # Add middleware to app
    app.middlewares.append(create_deprecation_middleware())
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from collections.abc import Awaitable, Callable

from aiohttp import web

logger = logging.getLogger(__name__)

# Configuration
BLOCK_SUNSET_ENDPOINTS = os.environ.get("ARAGORA_BLOCK_SUNSET_ENDPOINTS", "true").lower() == "true"
LOG_DEPRECATED_USAGE = os.environ.get("ARAGORA_LOG_DEPRECATED_USAGE", "true").lower() == "true"

# Type alias for aiohttp handler
Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


@dataclass
class DeprecatedEndpoint:
    """Definition of a deprecated endpoint."""

    path_pattern: str  # Can include wildcards: /api/v1/debates/*
    methods: list[str]  # HTTP methods (GET, POST, etc.)
    sunset_date: date | None = None
    replacement: str | None = None
    message: str | None = None
    migration_guide_url: str | None = None
    deprecated_since: date | None = None
    version: str | None = None  # API version being deprecated

    @property
    def is_sunset(self) -> bool:
        """Check if endpoint is past sunset date."""
        if self.sunset_date is None:
            return False
        return date.today() > self.sunset_date

    @property
    def days_until_sunset(self) -> int | None:
        """Days until sunset (negative if past)."""
        if self.sunset_date is None:
            return None
        return (self.sunset_date - date.today()).days

    @property
    def deprecation_level(self) -> str:
        """Get deprecation level based on sunset date."""
        if self.sunset_date is None:
            return "warning"
        days = self.days_until_sunset
        if days is not None:
            if days < 0:
                return "sunset"
            if days < 30:
                return "critical"
        return "warning"


MAX_TRACKED_ENDPOINTS = 500  # Prevent unbounded growth of per-endpoint stats


@dataclass
class DeprecationStats:
    """Statistics for deprecation tracking."""

    total_deprecated_calls: int = 0
    calls_by_endpoint: dict[str, int] = field(default_factory=dict)
    blocked_sunset_calls: int = 0
    last_reset: float = field(default_factory=time.time)

    def record_call(self, path: str, method: str) -> None:
        """Record a call to a deprecated endpoint."""
        self.total_deprecated_calls += 1
        key = f"{method}:{path}"
        self.calls_by_endpoint[key] = self.calls_by_endpoint.get(key, 0) + 1
        # Evict lowest-count entries if tracking too many unique endpoints
        if len(self.calls_by_endpoint) > MAX_TRACKED_ENDPOINTS:
            sorted_keys = sorted(self.calls_by_endpoint, key=self.calls_by_endpoint.get)  # type: ignore[arg-type]
            for k in sorted_keys[: len(self.calls_by_endpoint) - MAX_TRACKED_ENDPOINTS]:
                del self.calls_by_endpoint[k]

    def record_blocked(self) -> None:
        """Record a blocked sunset call."""
        self.blocked_sunset_calls += 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_deprecated_calls": self.total_deprecated_calls,
            "calls_by_endpoint": self.calls_by_endpoint,
            "blocked_sunset_calls": self.blocked_sunset_calls,
            "last_reset": self.last_reset,
            "uptime_seconds": time.time() - self.last_reset,
        }


class DeprecationEnforcer:
    """Enforces API deprecation policies in the request lifecycle.

    Maintains a registry of deprecated endpoints and applies
    deprecation headers and sunset blocking to matching requests.
    """

    def __init__(
        self,
        block_sunset: bool = BLOCK_SUNSET_ENDPOINTS,
        log_usage: bool = LOG_DEPRECATED_USAGE,
    ):
        """Initialize the deprecation enforcer.

        Args:
            block_sunset: Block requests to sunset endpoints (HTTP 410)
            log_usage: Log deprecated endpoint usage
        """
        self._endpoints: list[DeprecatedEndpoint] = []
        self._compiled_patterns: list[tuple[re.Pattern, DeprecatedEndpoint]] = []
        self._stats = DeprecationStats()
        self._block_sunset = block_sunset
        self._log_usage = log_usage

    def register(
        self,
        path_pattern: str,
        methods: list[str] | str = "GET",
        sunset_date: date | None = None,
        replacement: str | None = None,
        message: str | None = None,
        migration_guide_url: str | None = None,
        version: str | None = None,
    ) -> DeprecatedEndpoint:
        """Register a deprecated endpoint.

        Args:
            path_pattern: URL pattern (supports wildcards like /api/v1/*)
            methods: HTTP methods or single method
            sunset_date: When endpoint will be removed
            replacement: URL of replacement endpoint
            message: Custom deprecation message
            migration_guide_url: URL to migration docs
            version: API version being deprecated

        Returns:
            The registered DeprecatedEndpoint
        """
        if isinstance(methods, str):
            methods = [methods]
        methods = [m.upper() for m in methods]

        endpoint = DeprecatedEndpoint(
            path_pattern=path_pattern,
            methods=methods,
            sunset_date=sunset_date,
            replacement=replacement,
            message=message,
            migration_guide_url=migration_guide_url,
            deprecated_since=date.today(),
            version=version,
        )

        self._endpoints.append(endpoint)

        # Compile pattern for efficient matching
        regex_pattern = self._pattern_to_regex(path_pattern)
        self._compiled_patterns.append((regex_pattern, endpoint))

        logger.info(
            "Registered deprecated endpoint: %s %s (sunset: %s)",
            methods,
            path_pattern,
            sunset_date,
        )

        return endpoint

    def check_request(self, path: str, method: str) -> DeprecatedEndpoint | None:
        """Check if a request matches a deprecated endpoint.

        Args:
            path: Request path
            method: HTTP method

        Returns:
            Matching DeprecatedEndpoint or None
        """
        method = method.upper()

        for pattern, endpoint in self._compiled_patterns:
            if method in endpoint.methods and pattern.match(path):
                return endpoint

        return None

    def process_request(self, request: web.Request) -> tuple[dict[str, str], web.Response | None]:
        """Process a request for deprecation.

        Args:
            request: The incoming request

        Returns:
            Tuple of (headers_to_add, optional_error_response)
        """
        path = request.path
        method = request.method

        endpoint = self.check_request(path, method)
        if endpoint is None:
            return {}, None

        # Track usage
        if self._log_usage:
            self._stats.record_call(path, method)
            logger.warning(
                "Deprecated endpoint accessed: %s %s (level=%s, sunset=%s)",
                method,
                path,
                endpoint.deprecation_level,
                endpoint.sunset_date,
            )

        # Build deprecation headers
        headers = self._build_headers(endpoint)

        # Block sunset endpoints
        if self._block_sunset and endpoint.is_sunset:
            self._stats.record_blocked()
            # Record Prometheus metric for blocked requests
            try:
                from aragora.observability.prometheus import record_v1_api_sunset_blocked

                record_v1_api_sunset_blocked(path, method)
            except ImportError:
                pass
            return headers, self._build_sunset_response(endpoint)

        return headers, None

    def get_all_deprecated(self) -> list[DeprecatedEndpoint]:
        """Get all registered deprecated endpoints."""
        return list(self._endpoints)

    def get_critical_endpoints(self) -> list[DeprecatedEndpoint]:
        """Get endpoints near or past sunset."""
        return [e for e in self._endpoints if e.deprecation_level in ("critical", "sunset")]

    def get_stats(self) -> DeprecationStats:
        """Get deprecation statistics."""
        return self._stats

    def _pattern_to_regex(self, pattern: str) -> re.Pattern:
        """Convert a path pattern to regex.

        Supports:
        - * matches any path segment
        - ** matches any number of path segments
        - {param} matches a path parameter
        """
        # Escape regex special chars except our patterns
        escaped = re.escape(pattern)

        # Convert ** to match any path
        escaped = escaped.replace(r"\*\*", ".*")

        # Convert * to match single segment
        escaped = escaped.replace(r"\*", "[^/]+")

        # Convert {param} to match segment
        escaped = re.sub(r"\\{[^}]+\\}", "[^/]+", escaped)

        return re.compile(f"^{escaped}$")

    def _build_headers(self, endpoint: DeprecatedEndpoint) -> dict[str, str]:
        """Build deprecation response headers."""
        headers: dict[str, str] = {}

        # RFC 8594 Deprecation header
        if endpoint.sunset_date:
            # Unix timestamp format
            from datetime import datetime, timezone

            dt = datetime.combine(endpoint.sunset_date, datetime.min.time())
            dt = dt.replace(tzinfo=timezone.utc)
            headers["Deprecation"] = f"@{int(dt.timestamp())}"
        else:
            headers["Deprecation"] = "true"

        # Sunset header (HTTP date format)
        if endpoint.sunset_date:
            dt = datetime.combine(endpoint.sunset_date, datetime.min.time())
            dt = dt.replace(tzinfo=timezone.utc)
            headers["Sunset"] = dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

        # Link to replacement
        if endpoint.replacement:
            headers["Link"] = f'<{endpoint.replacement}>; rel="successor-version"'

        # Custom headers
        headers["X-Deprecation-Level"] = endpoint.deprecation_level
        if endpoint.migration_guide_url:
            headers["X-Migration-Guide"] = endpoint.migration_guide_url
        if endpoint.version:
            headers["X-Deprecated-Version"] = endpoint.version

        return headers

    def _build_sunset_response(self, endpoint: DeprecatedEndpoint) -> web.Response:
        """Build 410 Gone response for sunset endpoints."""
        body = {
            "error": "endpoint_sunset",
            "code": "ENDPOINT_REMOVED",
            "message": endpoint.message or f"This endpoint was removed on {endpoint.sunset_date}",
            "sunset_date": endpoint.sunset_date.isoformat() if endpoint.sunset_date else None,
            "replacement": endpoint.replacement,
            "migration_guide": endpoint.migration_guide_url,
        }

        return web.json_response(body, status=410)


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

_enforcer: DeprecationEnforcer | None = None
_enforcer_lock = threading.Lock()


def get_deprecation_enforcer() -> DeprecationEnforcer:
    """Get or create the global deprecation enforcer."""
    global _enforcer
    if _enforcer is not None:
        return _enforcer
    with _enforcer_lock:
        if _enforcer is None:
            _enforcer = DeprecationEnforcer()
        return _enforcer


def reset_deprecation_enforcer() -> None:
    """Reset the global deprecation enforcer (for testing)."""
    global _enforcer
    with _enforcer_lock:
        _enforcer = None


def register_deprecated_endpoint(
    path: str,
    methods: list[str] | str = "GET",
    sunset_date: date | None = None,
    replacement: str | None = None,
    message: str | None = None,
    migration_guide_url: str | None = None,
    version: str | None = None,
) -> DeprecatedEndpoint:
    """Register a deprecated endpoint in the global enforcer.

    Convenience function for registering deprecated endpoints.

    Args:
        path: URL pattern (supports wildcards)
        methods: HTTP methods
        sunset_date: When endpoint will be removed
        replacement: URL of replacement endpoint
        message: Custom deprecation message
        migration_guide_url: URL to migration docs
        version: API version being deprecated

    Returns:
        The registered DeprecatedEndpoint
    """
    return get_deprecation_enforcer().register(
        path_pattern=path,
        methods=methods,
        sunset_date=sunset_date,
        replacement=replacement,
        message=message,
        migration_guide_url=migration_guide_url,
        version=version,
    )


# ---------------------------------------------------------------------------
# aiohttp Middleware Factory
# ---------------------------------------------------------------------------


@web.middleware
async def deprecation_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    """aiohttp middleware for deprecation enforcement.

    Checks requests against deprecated endpoints and:
    - Adds deprecation headers to responses
    - Blocks sunset endpoints with 410 Gone
    - Logs deprecated endpoint usage
    """
    enforcer = get_deprecation_enforcer()
    headers, error_response = enforcer.process_request(request)

    # Return error for sunset endpoints
    if error_response is not None:
        for key, value in headers.items():
            error_response.headers[key] = value
        return error_response

    # Call the actual handler
    response = await handler(request)

    # Add deprecation headers
    for key, value in headers.items():
        response.headers[key] = value

    return response


def create_deprecation_middleware() -> Callable:
    """Create the deprecation middleware.

    Returns:
        aiohttp middleware function
    """
    return deprecation_middleware


# ---------------------------------------------------------------------------
# Startup Registration
# ---------------------------------------------------------------------------


def register_default_deprecations() -> None:
    """Register default deprecated endpoints for v1 API sunset.

    Called at server startup to register known deprecated v1 endpoints.
    All v1 endpoints have a sunset date of 2026-06-01. See
    docs/migration/V1_TO_V2_MIGRATION.md for the full migration guide.

    The wildcard pattern /api/v1/** covers all v1 endpoints. Individual
    entries below provide specific replacement URLs for key endpoints.
    """
    from aragora.server.versioning.constants import (
        MIGRATION_DOCS_URL,
        V1_SUNSET_DATE,
        days_until_v1_sunset,
    )

    all_methods = ["GET", "POST", "PUT", "DELETE", "PATCH"]

    # Key endpoint-specific deprecations with precise v2 replacements.
    # IMPORTANT: Specific patterns are registered BEFORE the blanket /api/v1/**
    # pattern so that check_request() returns the most specific match first.
    # Grouped by domain for maintainability.  See docs/migration/V1_TO_V2_MIGRATION.md
    # for the full migration guide shown to API consumers.
    _v1_endpoint_replacements: list[tuple[str, str, list[str]]] = [
        # --- Core: debates & agents ---
        ("/api/v1/debates", "/api/v2/debates", ["GET", "POST"]),
        ("/api/v1/debates/*", "/api/v2/debates/*", ["GET", "PUT", "DELETE"]),
        ("/api/v1/debate", "/api/v2/debates", ["POST"]),
        ("/api/v1/debate/*", "/api/v2/debates/*", ["GET"]),
        ("/api/v1/agents", "/api/v2/agents", ["GET"]),
        ("/api/v1/agents/*", "/api/v2/agents/*", ["GET"]),
        ("/api/v1/consensus/*", "/api/v2/debates/*/consensus", ["GET"]),
        ("/api/v1/leaderboard", "/api/v2/agents/leaderboard", ["GET"]),
        ("/api/v1/rankings", "/api/v2/agents/rankings", ["GET"]),
        ("/api/v1/team-selection", "/api/v2/agents/team-selection", all_methods),
        ("/api/v1/explain/**", "/api/v2/debates/explain/", ["GET"]),
        # --- Auth & users ---
        ("/api/v1/auth/login", "/api/v2/auth/token", ["POST"]),
        ("/api/v1/auth/register", "/api/v2/auth/register", ["POST"]),
        ("/api/v1/auth/**", "/api/v2/auth/", all_methods),
        ("/api/v1/user", "/api/v2/users/me", ["GET"]),
        ("/api/v1/rbac/**", "/api/v2/rbac/", all_methods),
        # --- System & health ---
        ("/api/v1/metrics", "/api/v2/system/metrics", ["GET"]),
        ("/api/v1/health", "/api/v2/system/health", ["GET"]),
        ("/api/v1/health/**", "/api/v2/system/health", ["GET"]),
        ("/api/v1/status", "/api/v2/health", ["GET"]),
        # --- Analytics & insights ---
        ("/api/v1/analytics/**", "/api/v2/analytics/", ["GET"]),
        ("/api/v1/insights/**", "/api/v2/analytics/insights/", ["GET"]),
        ("/api/v1/flips/**", "/api/v2/analytics/flips/", ["GET"]),
        ("/api/v1/moments/**", "/api/v2/analytics/moments/", ["GET"]),
        # --- Knowledge & memory ---
        ("/api/v1/knowledge/**", "/api/v2/knowledge/", all_methods),
        ("/api/v1/memory/**", "/api/v2/memory/", ["GET"]),
        ("/api/v1/facts/**", "/api/v2/knowledge/facts/", all_methods),
        ("/api/v1/evidence/**", "/api/v2/knowledge/evidence/", all_methods),
        # --- Gauntlet & verification ---
        ("/api/v1/gauntlet/**", "/api/v2/gauntlet/", ["GET", "POST"]),
        ("/api/v1/evaluate", "/api/v2/gauntlet/evaluate", ["POST"]),
        ("/api/v1/verify/**", "/api/v2/verification/", ["POST"]),
        # --- Workflow & automation ---
        ("/api/v1/workflows", "/api/v2/workflows", all_methods),
        ("/api/v1/workflow-templates", "/api/v2/workflows/templates", all_methods),
        ("/api/v1/workflow-executions", "/api/v2/workflows/executions", all_methods),
        ("/api/v1/approvals", "/api/v2/workflows/approvals", all_methods),
        ("/api/v1/webhooks", "/api/v2/webhooks", all_methods),
        ("/api/v1/webhooks/**", "/api/v2/webhooks/", all_methods),
        # --- Billing & usage ---
        ("/api/v1/billing/**", "/api/v2/billing/", all_methods),
        ("/api/v1/budgets", "/api/v2/billing/budgets", all_methods),
        ("/api/v1/costs", "/api/v2/billing/costs", ["GET"]),
        ("/api/v1/quotas", "/api/v2/billing/quotas", ["GET"]),
        ("/api/v1/usage/**", "/api/v2/billing/usage/", ["GET"]),
        ("/api/v1/accounting/**", "/api/v2/billing/accounting/", all_methods),
        # --- Integrations & connectors ---
        ("/api/v1/integrations/**", "/api/v2/integrations/", all_methods),
        ("/api/v1/connectors/**", "/api/v2/connectors/", all_methods),
        ("/api/v1/bots/**", "/api/v2/bots/", all_methods),
        # --- Blockchain & ERC-8004 ---
        ("/api/v1/blockchain/**", "/api/v2/blockchain/", all_methods),
        ("/api/v1/openclaw/**", "/api/v2/openclaw/", all_methods),
        # --- Nomic loop & self-improvement ---
        ("/api/v1/nomic/**", "/api/v2/nomic/", all_methods),
        ("/api/v1/genesis/**", "/api/v2/genesis/", all_methods),
        ("/api/v1/evolution/**", "/api/v2/evolution/", ["GET"]),
        # --- Gateway & routing ---
        ("/api/v1/gateway/**", "/api/v2/gateway/", all_methods),
        ("/api/v1/routing/**", "/api/v2/routing/", all_methods),
        # --- Security & compliance ---
        ("/api/v1/privacy/**", "/api/v2/users/me/", ["GET", "DELETE"]),
        ("/api/v1/audit/**", "/api/v2/audit/", all_methods),
        ("/api/v1/threat/**", "/api/v2/security/threat/", all_methods),
        ("/api/v1/compliance/**", "/api/v2/compliance/", all_methods),
        # --- Marketplace & skills ---
        ("/api/v1/marketplace", "/api/v2/marketplace", all_methods),
        ("/api/v1/marketplace/**", "/api/v2/marketplace/", all_methods),
        ("/api/v1/skills/**", "/api/v2/skills/", all_methods),
        ("/api/v1/plugins/**", "/api/v2/plugins/", all_methods),
        # --- Miscellaneous ---
        ("/api/v1/canvas/**", "/api/v2/canvas/", all_methods),
        ("/api/v1/computer-use/**", "/api/v2/computer-use/", all_methods),
        ("/api/v1/slos", "/api/v2/slo/status", ["GET"]),
        ("/api/v1/replays", "/api/v2/replays", ["GET"]),
        ("/api/v1/replays/**", "/api/v2/replays/", ["GET"]),
        ("/api/v1/tournaments", "/api/v2/tournaments", ["GET"]),
        ("/api/v1/tournaments/**", "/api/v2/tournaments/", ["GET"]),
        ("/api/v1/reviews", "/api/v2/reviews", ["GET"]),
        ("/api/v1/reviews/**", "/api/v2/reviews/", ["GET"]),
        ("/api/v1/verticals", "/api/v2/verticals", ["GET"]),
        ("/api/v1/features", "/api/v2/features", ["GET"]),
        ("/api/v1/features/**", "/api/v2/features/", ["GET"]),
        ("/api/v1/checkpoints", "/api/v2/checkpoints", all_methods),
        ("/api/v1/dashboard/**", "/api/v2/dashboard/", ["GET"]),
        ("/api/v1/cross-pollination/**", "/api/v2/cross-pollination/", ["GET"]),
        ("/api/v1/inbox/**", "/api/v2/inbox/", ["GET", "POST"]),
        ("/api/v1/onboarding/**", "/api/v2/onboarding/", all_methods),
        ("/api/v1/graphql", "/api/v2/graphql", ["POST"]),
        ("/api/v1/docs", "/api/v2/docs", ["GET"]),
        ("/api/v1/openapi", "/api/v2/openapi.json", ["GET"]),
        ("/api/v1/devices/**", "/api/v2/devices/", all_methods),
        ("/api/v1/advertising/**", "/api/v2/advertising/", all_methods),
        ("/api/v1/analytics-platforms/**", "/api/v2/analytics-platforms/", all_methods),
        ("/api/v1/crm/**", "/api/v2/crm/", all_methods),
        ("/api/v1/support/**", "/api/v2/support/", all_methods),
        ("/api/v1/ecommerce/**", "/api/v2/ecommerce/", all_methods),
        ("/api/v1/codebase/**", "/api/v2/codebase/", all_methods),
        ("/api/v1/admin/**", "/api/v2/admin/", all_methods),
    ]

    for v1_path, v2_replacement, methods in _v1_endpoint_replacements:
        register_deprecated_endpoint(
            path=v1_path,
            methods=methods,
            sunset_date=V1_SUNSET_DATE,
            replacement=v2_replacement,
            migration_guide_url=MIGRATION_DOCS_URL,
            version="v1",
        )

    # Blanket deprecation for all v1 endpoints (registered LAST so specific
    # patterns above take priority in check_request pattern matching).
    register_deprecated_endpoint(
        path="/api/v1/**",
        methods=all_methods,
        sunset_date=V1_SUNSET_DATE,
        replacement="/api/v2/",
        message=(
            "API v1 is deprecated and will be removed on 2026-06-01. "
            "Please migrate to API v2. "
            "See docs/migration/V1_TO_V2_MIGRATION.md for details."
        ),
        migration_guide_url=MIGRATION_DOCS_URL,
        version="v1",
    )

    # Update Prometheus gauge for days until sunset
    try:
        from aragora.observability.prometheus_recording import (
            register_v1_sunset_days_provider,
            update_v1_days_until_sunset,
        )

        register_v1_sunset_days_provider(days_until_v1_sunset)
        update_v1_days_until_sunset()
    except ImportError:
        pass

    logger.info(
        "Registered v1 API deprecations: sunset=%s, days_remaining=%d",
        V1_SUNSET_DATE.isoformat(),
        max(0, (V1_SUNSET_DATE - date.today()).days),
    )


__all__ = [
    "DeprecatedEndpoint",
    "DeprecationEnforcer",
    "DeprecationStats",
    "create_deprecation_middleware",
    "deprecation_middleware",
    "get_deprecation_enforcer",
    "register_default_deprecations",
    "register_deprecated_endpoint",
    "reset_deprecation_enforcer",
]
