"""
Route dispatch and authentication helpers for debate handler.

Extracted from handler.py for modularity. Provides:
- Route configuration and patterns
- Route dispatch table and suffix matching
- Authentication checking helpers
- Artifact access control
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol
from collections.abc import Callable

from aragora.server.validation import validate_debate_id

from ..base import (
    HandlerResult,
    error_response,
    get_int_param,
)

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


# Route patterns managed by DebatesHandler
ROUTES = [
    "/api/v1/debate",  # POST - create new debate (legacy endpoint)
    "/api/v1/debates",
    "/api/v1/debates/",  # With trailing slash
    "/api/v1/debates/active",  # GET - currently running debates
    "/api/v1/debates/estimate-cost",  # GET - pre-debate cost estimation
    "/api/v1/debates/batch",  # POST - batch debate submission
    "/api/v1/debates/batch/",
    "/api/v1/debates/batch/*/status",  # GET - batch status
    "/api/v1/debates/queue/status",  # GET - queue status
    "/api/v1/debates/export/batch",  # POST - start batch export
    "/api/v1/debates/export/batch/",
    "/api/v1/debates/export/batch/*/status",  # GET - export job status
    "/api/v1/debates/export/batch/*/results",  # GET - export job results
    "/api/v1/debates/export/batch/*/stream",  # GET - SSE progress stream
    "/api/v1/debates/slug/",
    "/api/v1/debates/*/export/",
    "/api/v1/debates/*/impasse",
    "/api/v1/debates/*/convergence",
    "/api/v1/debates/*/citations",
    "/api/v1/debates/*/messages",  # Paginated message history
    "/api/v1/debates/*/fork",  # POST - counterfactual fork
    "/api/v1/debates/*/followup",  # POST - crux-driven follow-up debate
    "/api/v1/debates/*/followups",  # GET - list follow-up suggestions
    "/api/v1/debates/*/forks",  # GET - list all forks for a debate
    "/api/v1/debates/*/verification-report",  # Verification feedback
    "/api/v1/debates/*/summary",  # GET - human-readable summary
    "/api/v1/debates/*/cancel",  # POST - cancel running debate
    "/api/v1/debates/*/decision-integrity",  # POST - receipt + plan bundle
    "/api/v1/debates/*/positions",  # GET - position evolution per agent
    "/api/v1/debates/*/diagnostics",  # GET - debug report for failed debates
    "/api/v1/debates/*/costs",  # GET - per-debate cost breakdown
    "/api/v1/debate-this",  # POST - one-click debate launcher
    "/api/v1/search",  # Cross-debate search
    # Analytics and management endpoints
    "/api/v1/debates/analytics/consensus",  # GET - consensus analytics
    "/api/v1/debates/analytics/trends",  # GET - debate trend analytics
    "/api/v1/debates/archive/batch",  # POST - batch archive debates
    "/api/v1/debates/archived",  # GET - list archived debates
    "/api/v1/debates/compare",  # POST - compare debates
    "/api/v1/debates/health",  # GET - debate system health
    "/api/v1/debates/import",  # POST - import debates
    "/api/v1/debates/statistics",  # GET - debate statistics
    "/api/v1/debates/stream",  # GET - debate event stream
    "/api/v1/debates/*/events",  # GET - polling fallback for missed events
]

# Endpoints that require authentication
AUTH_REQUIRED_ENDPOINTS = [
    "/api/v1/debates/batch",  # Batch submission requires auth
    "/export/",  # Export debate data
    "/package",  # Decision package payloads include full debate details
    "/citations",  # Evidence citations
    "/fork",  # Fork debate
    "/followup",  # Create follow-up debate
    "/decision-integrity",  # Decision receipt + implementation plan
]

# Allowed export formats and tables for input validation
ALLOWED_EXPORT_FORMATS = {"json", "csv", "html", "txt", "md"}
ALLOWED_EXPORT_TABLES = {"summary", "messages", "critiques", "votes"}

# Endpoints that expose debate artifacts - require auth unless debate is_public
ARTIFACT_ENDPOINTS = {"/messages", "/evidence", "/verification-report"}


# Type for suffix route entry: (suffix, handler_method_name, needs_debate_id, extra_params_fn)
SuffixRouteEntry = tuple[
    str,  # suffix
    str,  # method_name
    bool,  # needs_debate_id
    Callable[[str, dict[str, Any]], dict[str, Any]] | None,  # extra_params_fn
]


def build_suffix_routes() -> list[SuffixRouteEntry]:
    """Build the suffix route dispatch table.

    Returns a list of tuples: (suffix, method_name, needs_id, extra_params_fn)
    """
    return [
        ("/impasse", "_get_impasse", True, None),
        ("/convergence", "_get_convergence", True, None),
        ("/citations", "_get_citations", True, None),
        ("/evidence", "_get_evidence", True, None),
        (
            "/messages",
            "_get_debate_messages",
            True,
            lambda p, q: {
                "limit": get_int_param(q, "limit", 50),
                "offset": get_int_param(q, "offset", 0),
            },
        ),
        ("/meta-critique", "_get_meta_critique", True, None),
        ("/graph/stats", "_get_graph_stats", True, None),
        ("/verification-report", "_get_verification_report", True, None),
        ("/followups", "_get_followup_suggestions", True, None),
        ("/forks", "_list_debate_forks", True, None),
        ("/summary", "_get_summary", True, None),
        ("/rhetorical", "_get_rhetorical_observations", True, None),
        ("/trickster", "_get_trickster_status", True, None),
        ("/positions", "_get_positions", True, None),
        ("/diagnostics", "_get_diagnostics", True, None),
        ("/costs", "_get_debate_costs", True, None),
        (
            "/events",
            "_get_debate_events",
            True,
            lambda p, q: {
                "since_seq": get_int_param(q, "since", 0),
                "limit": get_int_param(q, "limit", 100),
            },
        ),
    ]


# Pre-built suffix routes for the handler to use
SUFFIX_ROUTES = build_suffix_routes()

# Methods that only take debate_id (no handler parameter)
ID_ONLY_METHODS = {
    "_get_meta_critique",
    "_get_graph_stats",
    "_get_followup_suggestions",
    "_list_debate_forks",
    "_get_rhetorical_observations",
    "_get_trickster_status",
    "_get_positions",
    "_get_diagnostics",
    "_get_debate_costs",
}


class _DebatesHandlerProtocol(Protocol):
    """Protocol defining the interface expected by RoutingMixin."""

    ctx: dict[str, Any]
    AUTH_REQUIRED_ENDPOINTS: list[str]
    ARTIFACT_ENDPOINTS: set[str]
    SUFFIX_ROUTES: list[SuffixRouteEntry]

    def get_storage(self) -> Any | None:
        """Get debate storage instance."""
        ...

    def _check_auth(self, handler: Any) -> HandlerResult | None:
        """Check authentication for sensitive endpoints."""
        ...

    def _extract_debate_id(self, path: str) -> tuple[str | None, str | None]:
        """Extract and validate debate ID from path."""
        ...

    def _check_artifact_access(
        self, debate_id: str, suffix: str, handler: Any
    ) -> HandlerResult | None:
        """Check access to artifact endpoints."""
        ...


class RoutingMixin:
    """Mixin providing route dispatch and authentication helpers for DebatesHandler."""

    # Class-level route configuration
    ROUTES = ROUTES
    AUTH_REQUIRED_ENDPOINTS = AUTH_REQUIRED_ENDPOINTS
    ALLOWED_EXPORT_FORMATS = ALLOWED_EXPORT_FORMATS
    ALLOWED_EXPORT_TABLES = ALLOWED_EXPORT_TABLES
    ARTIFACT_ENDPOINTS = ARTIFACT_ENDPOINTS
    SUFFIX_ROUTES = SUFFIX_ROUTES

    def _check_auth(self: _DebatesHandlerProtocol, handler: Any) -> HandlerResult | None:
        """Check authentication for sensitive endpoints.

        Supports both:
        - JWT tokens (from Google OAuth, etc.)
        - API tokens (ara_* prefix)
        - Legacy HMAC tokens (for backwards compatibility)

        Returns:
            None if auth passes, HandlerResult with 401 if auth fails.
        """
        from aragora.server.auth import auth_config

        if handler is None:
            logger.debug("No handler provided for auth check")
            return None  # Can't check auth without handler

        # If auth is disabled globally, allow access
        if not auth_config.enabled:
            return None

        # If no API token is configured on the server, skip token authentication
        if not auth_config.api_token:
            return None

        # Extract auth token from Authorization header
        auth_header = None
        if hasattr(handler, "headers"):
            auth_header = handler.headers.get("Authorization", "")

        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]

        if not token:
            return error_response("Missing authentication token", 401)

        # Check for JWT tokens (3 base64url parts separated by dots)
        if token.count(".") == 2:
            try:
                from aragora.billing.auth import validate_access_token

                jwt_result = validate_access_token(token)
                if jwt_result:
                    return None  # JWT valid
                logger.debug("JWT token validation failed")
            except (ImportError, ValueError, TypeError, AttributeError, KeyError) as e:
                logger.debug("JWT validation error: %s", e)

        # Check for API tokens (ara_* prefix)
        if token.startswith("ara_"):
            # API tokens are validated by rate limiter, just check format
            return None

        # Check if API token is configured for legacy HMAC tokens
        if not auth_config.api_token:
            logger.debug("No API token configured, skipping legacy auth check")
            return None

        # Validate legacy HMAC token
        if auth_config.validate_token(token):
            return None

        return error_response("Invalid or expired authentication token", 401)

    def _requires_auth(self: _DebatesHandlerProtocol, path: str) -> bool:
        """Check if the given path requires authentication."""
        # Normalize path for consistent checking
        normalized = path.replace("/api/v1/", "/api/").replace("/api/v2/", "/api/")
        for pattern in self.AUTH_REQUIRED_ENDPOINTS:
            # Also normalize the pattern for comparison
            norm_pattern = pattern.replace("/api/v1/", "/api/").replace("/api/v2/", "/api/")
            if norm_pattern in normalized:
                return True
        return False

    def _check_artifact_access(
        self: _DebatesHandlerProtocol, debate_id: str, suffix: str, handler: Any
    ) -> HandlerResult | None:
        """Check access to artifact endpoints.

        Returns None if access allowed, 401 error if auth required but missing.
        Artifacts are accessible if:
        - Debate is marked as is_public=True, OR
        - Valid auth token is provided
        """
        if suffix not in self.ARTIFACT_ENDPOINTS:
            return None  # Not an artifact endpoint

        # Check if debate is public
        storage = self.get_storage()
        if storage and storage.is_public(debate_id):
            return None  # Public debate, no auth needed

        # Private debate - require authentication
        auth_result = self._check_auth(handler)
        if auth_result:
            return auth_result  # Auth failed

        return None  # Auth passed

    def _dispatch_suffix_route(
        self: _DebatesHandlerProtocol, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Dispatch routes based on path suffix using SUFFIX_ROUTES table.

        Returns:
            HandlerResult if a route matched, None otherwise.
        """
        for suffix, method_name, needs_id, extra_params_fn in self.SUFFIX_ROUTES:
            if not path.endswith(suffix):
                continue

            # Extract debate_id if needed
            debate_id = None
            if needs_id:
                debate_id, err = self._extract_debate_id(path)
                if err:
                    return error_response(err, 400)
                if not debate_id:
                    continue

                # Check artifact access (auth required for private debates)
                access_error = self._check_artifact_access(debate_id, suffix, handler)
                if access_error:
                    return access_error

            # Get handler method
            method = getattr(self, method_name, None)
            if not method:
                continue

            # Build arguments
            if needs_id:
                if extra_params_fn:
                    extra = extra_params_fn(path, query_params)
                    # Methods like _get_debate_messages don't take handler
                    if method_name == "_get_debate_messages":
                        return method(debate_id, **extra)
                    return method(handler, debate_id, **extra)
                else:
                    # Methods like _get_meta_critique only take debate_id
                    if method_name in ID_ONLY_METHODS:
                        return method(debate_id)
                    return method(handler, debate_id)

        return None

    def _extract_debate_id(
        self: _DebatesHandlerProtocol, path: str
    ) -> tuple[str | None, str | None]:
        """Extract and validate debate ID from path like /api/debates/{id}/impasse.

        Handles both versioned (/api/v1/debates/{id}) and unversioned (/api/debates/{id}) paths.

        Returns:
            Tuple of (debate_id, error_message). If error_message is set, debate_id is None.
        """
        # Normalize to unversioned path
        normalized = path.replace("/api/v1/", "/api/").replace("/api/v2/", "/api/")
        parts = normalized.split("/")
        if len(parts) < 4:
            return None, "Invalid path"

        # For unversioned routes: ['', 'api', 'debates', '{id}', ...]
        debate_id = parts[3]
        is_valid, err = validate_debate_id(debate_id)
        if not is_valid:
            return None, err

        return debate_id, None

    def can_handle(self: _DebatesHandlerProtocol, path: str) -> bool:
        """Check if this handler can process the given path.

        Note: Paths may be normalized (version stripped) by handler_registry,
        so we check both versioned and unversioned variants.
        """
        # Normalize to unversioned for consistent checking
        normalized = path.replace("/api/v1/", "/api/").replace("/api/v2/", "/api/")

        if normalized in ("/api/debate", "/api/debates", "/api/debate-this"):
            return True  # POST - create debate, GET - list debates
        if normalized in ("/api/search", "/api/debates/search"):
            return True
        if normalized.startswith("/api/debates/"):
            return True
        # Also handle /api/debate/{id}/meta-critique and /api/debate/{id}/graph/stats
        if normalized.startswith("/api/debate/") and (
            normalized.endswith("/meta-critique") or normalized.endswith("/graph/stats")
        ):
            return True
        return False


__all__ = [
    "RoutingMixin",
    "ROUTES",
    "AUTH_REQUIRED_ENDPOINTS",
    "ALLOWED_EXPORT_FORMATS",
    "ALLOWED_EXPORT_TABLES",
    "ARTIFACT_ENDPOINTS",
    "SUFFIX_ROUTES",
    "ID_ONLY_METHODS",
    "build_suffix_routes",
]
