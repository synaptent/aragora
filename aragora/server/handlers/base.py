"""
Base handler utilities for modular endpoint handlers.

Provides common response formatting, error handling, and utilities
shared across all endpoint modules.

Note: Many utilities have been extracted to submodules for better organization.
They are re-exported here for backwards compatibility:
- mixins.py: PaginatedHandlerMixin, CachedHandlerMixin, AuthenticatedHandlerMixin
- api_decorators.py: api_endpoint, rate_limit, validate_body, require_quota
- typed_handlers.py: TypedHandler, AuthenticatedHandler, PermissionHandler, etc.
- utils/responses.py: HandlerResult, json_response, error_response
- utils/decorators.py: handle_errors, require_auth, require_permission, etc.

Authentication Requirements
---------------------------
Aragora uses header-based authentication (Bearer tokens in Authorization header).
This approach is inherently immune to CSRF attacks because:

1. Tokens are sent via Authorization header, not cookies
2. JavaScript must explicitly set the header (not automatic like cookies)
3. Cross-origin requests cannot access the header

Endpoint Authentication Patterns:
- Public endpoints: No authentication required (e.g., /api/plans, /api/health)
- Protected endpoints: Require valid Bearer token
- Write operations: Always require authentication

Handler classes should use `extract_user_from_request()` for authentication:

    from aragora.billing.jwt_auth import extract_user_from_request

    def _handle_protected(self, handler) -> HandlerResult:
        user_store = self._get_user_store()
        auth_ctx = extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return error_response("Not authenticated", 401)
        # ... proceed with authenticated logic

Rate limiting is applied via the @rate_limit decorator from utils.rate_limit.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import os
import re
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, TypeAlias, TypedDict, cast
from collections.abc import Awaitable

from aragora.billing.auth.context import UserAuthContext
from aragora.config import DB_TIMEOUT_SECONDS
from aragora.protocols import AgentRating, HTTPRequestHandler

if TYPE_CHECKING:
    from pathlib import Path

    from aragora.debate.calibration import CalibrationTracker
    from aragora.debate.embeddings import DebateEmbeddingsDatabase
    from aragora.evidence.collector import EvidenceCollector
    from aragora.evidence.store import EvidenceStore
    from aragora.insights.moment_detector import MomentDetector
    from aragora.knowledge.mound import KnowledgeMound
    from aragora.memory.continuum import ContinuumMemory
    from aragora.memory.cross_debate_rlm import CrossDebateMemory
    from aragora.memory.store import CritiqueStore
    from aragora.ranking.elo import EloSystem
    from aragora.server.storage import DebateStorage
    from aragora.server.stream.ws_manager import WebSocketManager
    from aragora.storage.documents import DocumentStore
    from aragora.storage.webhooks import WebhookStore
    from aragora.users.store import UserStore
    from aragora.billing.usage import UsageTracker


class ServerContext(TypedDict, total=False):
    """Type definition for server context passed to handlers.

    All fields are optional (total=False) since not all handlers need all resources.
    Handlers should use ctx.get("key") to safely access optional fields.

    Core Resources:
        storage: Main debate storage
        user_store: User authentication and profile storage
        elo_system: Agent ELO rating system
        nomic_dir: Path to Nomic session directory

    Memory Systems:
        continuum_memory: Cross-debate memory system
        critique_store: Critique persistence

    Analytics & Monitoring:
        calibration_tracker: Prediction calibration tracking
        moment_detector: Significant moment detection
        usage_tracker: API usage tracking

    Feature Stores:
        document_store: Document persistence
        evidence_store: Evidence snippet storage
        evidence_collector: Evidence collection service
        webhook_store: Webhook configuration storage
        audio_store: Audio file storage

    Event & Communication:
        event_emitter: Event emission for pub/sub
        ws_manager: WebSocket connection manager
        connectors: External service connectors

    Database Paths:
        analytics_db: Path to analytics database
        debate_embeddings: Debate embedding database
    """

    # Core Resources
    storage: DebateStorage
    user_store: UserStore
    elo_system: EloSystem
    nomic_dir: Path

    # Memory Systems
    continuum_memory: ContinuumMemory
    cross_debate_memory: CrossDebateMemory
    critique_store: CritiqueStore
    knowledge_mound: KnowledgeMound

    # Analytics & Monitoring
    calibration_tracker: CalibrationTracker
    moment_detector: MomentDetector
    usage_tracker: UsageTracker

    # Feature Stores
    document_store: DocumentStore
    evidence_store: EvidenceStore
    evidence_collector: EvidenceCollector
    webhook_store: WebhookStore
    audio_store: Any  # AudioStore type if available

    # Event & Communication
    event_emitter: Any  # EventEmitter type if available
    ws_manager: WebSocketManager
    connectors: dict[str, Any]  # Service connectors

    # Database Paths
    analytics_db: str
    debate_embeddings: DebateEmbeddingsDatabase

    # Request Context (populated by handler registry)
    body: dict[str, Any]  # Parsed JSON request body
    headers: dict[str, str]  # Request headers
    raw_body: bytes  # Raw request body for signature verification
    user_id: str  # Authenticated user ID
    query: dict[str, str]  # Query string parameters


# =============================================================================
# Imports from extracted modules (re-exported for backward compatibility)
# =============================================================================

# Error handling
from aragora.server.errors import safe_error_message

# Cache utilities
from aragora.server.handlers.admin.cache import (
    CACHE_INVALIDATION_MAP,
    BoundedTTLCache,
    _cache,
    async_ttl_cache,
    clear_cache,
    get_cache_stats,
    invalidate_agent_cache,
    invalidate_cache,
    invalidate_debate_cache,
    invalidate_leaderboard_cache,
    invalidate_on_event,
    ttl_cache,
)

# Database utilities
from aragora.server.handlers.utils.database import (
    get_db_connection,
    table_exists,
)

# RBAC decorators
from aragora.rbac.decorators import require_permission

# Handler decorators
from aragora.server.handlers.utils.decorators import (
    PERMISSION_MATRIX,
    auto_error_response,
    deprecated_endpoint,
    generate_trace_id,
    handle_errors,
    has_permission,
    log_request,
    require_auth,
    require_feature,
    require_storage,
    require_user_auth,
    safe_fetch,
    validate_params,
    with_error_recovery,
)

# Parameter extraction
from aragora.server.handlers.utils.params import (
    get_bool_param,
    get_bounded_float_param,
    get_bounded_string_param,
    get_clamped_int_param,
    get_float_param,
    get_int_param,
    get_string_param,
    parse_query_params,
)

# Routing utilities
from aragora.server.handlers.utils.routing import (
    PathMatcher,
    RouteDispatcher,
)

# Safe data access
from aragora.server.handlers.utils.safe_data import (
    safe_get,
    safe_get_nested,
    safe_json_parse,
)

# Validation
from aragora.server.validation import (
    SAFE_AGENT_PATTERN,
    SAFE_ID_PATTERN,
    SAFE_SLUG_PATTERN,
    validate_agent_name,
    validate_debate_id,
    validate_path_segment,
    validate_string,
)

# Response builders
from aragora.server.handlers.utils.responses import (
    HandlerResult,
    error_response,
    json_response,
    success_response,
)

# Type alias for handlers that may be sync or async
MaybeAsyncHandlerResult: TypeAlias = HandlerResult | None | Awaitable[HandlerResult | None]

# API decorators (from new module)
from aragora.server.handlers.api_decorators import (
    api_endpoint,
    rate_limit,
    require_quota,
    validate_body,
)

# Handler mixins (from new module)
from aragora.server.handlers.mixins import (
    AuthenticatedHandlerMixin,
    CachedHandlerMixin,
    PaginatedHandlerMixin,
)


# =============================================================================
# Module-level exports
# =============================================================================

logger = logging.getLogger(__name__)

# Default host from environment (used when Host header is missing)
_DEFAULT_HOST = os.environ.get("ARAGORA_DEFAULT_HOST", "localhost:8080")

# Re-export DB_TIMEOUT_SECONDS for backwards compatibility
__all__ = [
    "DB_TIMEOUT_SECONDS",
    "require_auth",
    "require_user_auth",
    "require_quota",
    "require_storage",
    "require_feature",
    "require_permission",
    "api_endpoint",
    "rate_limit",
    "validate_body",
    "has_permission",
    "PERMISSION_MATRIX",
    "deprecated_endpoint",
    "error_response",
    "json_response",
    "success_response",
    "HandlerResult",
    "handle_errors",
    "auto_error_response",
    "log_request",
    "ttl_cache",
    "safe_error_message",
    "safe_error_response",
    "async_ttl_cache",
    "BoundedTTLCache",
    "_cache",
    "clear_cache",
    "get_cache_stats",
    "CACHE_INVALIDATION_MAP",
    "invalidate_cache",
    "invalidate_on_event",
    "invalidate_leaderboard_cache",
    "invalidate_agent_cache",
    "invalidate_debate_cache",
    "PathMatcher",
    "RouteDispatcher",
    "safe_fetch",
    "with_error_recovery",
    "get_db_connection",
    "table_exists",
    "safe_get",
    "safe_get_nested",
    "safe_json_parse",
    "get_host_header",
    "get_agent_name",
    "agent_to_dict",
    "validate_params",
    "SAFE_ID_PATTERN",
    "SAFE_SLUG_PATTERN",
    "SAFE_AGENT_PATTERN",
    "validate_agent_name",
    "validate_debate_id",
    "validate_string",
    "feature_unavailable_response",
    # Parameter extraction helpers
    "get_int_param",
    "get_float_param",
    "get_bool_param",
    "get_string_param",
    "get_clamped_int_param",
    "get_bounded_float_param",
    "get_bounded_string_param",
    "parse_query_params",
    # Handler mixins
    "PaginatedHandlerMixin",
    "CachedHandlerMixin",
    "AuthenticatedHandlerMixin",
    "BaseHandler",
    # Typed handler base classes
    "TypedHandler",  # noqa: F822
    "AuthenticatedHandler",  # noqa: F822
    "PermissionHandler",  # noqa: F822
    "AdminHandler",  # noqa: F822
    "AsyncTypedHandler",  # noqa: F822
    "ResourceHandler",  # noqa: F822
    # Server context type
    "ServerContext",
    # Response type alias
    "MaybeAsyncHandlerResult",
]


# =============================================================================
# Helper Functions
# =============================================================================


def feature_unavailable_response(
    feature_id: str,
    message: str | None = None,
) -> HandlerResult:
    """
    Create a standardized response for unavailable features.

    This should be used by all handlers when an optional feature is missing.
    Provides consistent error format with helpful installation hints.

    Args:
        feature_id: The feature identifier (e.g., "pulse", "genesis")
        message: Optional custom message (defaults to feature description)

    Returns:
        HandlerResult with 503 status and helpful information

    Example:
        if not self._pulse_manager:
            return feature_unavailable_response("pulse")
    """
    # Import here to avoid circular imports
    from aragora.server.handlers.features import (
        feature_unavailable_response as _feature_unavailable,
    )

    return _feature_unavailable(feature_id, message)


def get_host_header(handler: HTTPRequestHandler | None, default: str | None = None) -> str:
    """Extract Host header from request handler.

    Args:
        handler: HTTP request handler with headers attribute
        default: Default value if handler is None or Host header missing.
                 If None, uses ARAGORA_DEFAULT_HOST env var or 'localhost:8080'.

    Returns:
        Host header value or default

    Example:
        # Before (repeated 5+ times):
        host = handler.headers.get('Host', 'localhost:8080') if handler else 'localhost:8080'

        # After:
        host = get_host_header(handler)
    """
    if default is None:
        default = _DEFAULT_HOST
    if handler is None:
        return default
    return handler.headers.get("Host", default) if hasattr(handler, "headers") else default


def get_agent_name(agent: dict[str, Any] | AgentRating | Any | None) -> str | None:
    """Extract agent name from dict or object.

    Handles the common pattern where agent data might be either
    a dict with 'name'/'agent_name' key or an object with name attribute.

    Args:
        agent: Dict or AgentRating-like object containing agent name

    Returns:
        Agent name string or None if not found

    Example:
        # Before (repeated 4+ times):
        name = agent.get("name") if isinstance(agent, dict) else getattr(agent, "name", None)

        # After:
        name = get_agent_name(agent)
    """
    if agent is None:
        return None
    if isinstance(agent, dict):
        result = agent.get("agent_name") or agent.get("name")
        return str(result) if result else None
    result = getattr(agent, "agent_name", None) or getattr(agent, "name", None)
    return str(result) if result else None


def _compute_trust_tier(brier_score: float, prediction_count: int) -> str:
    """Compute a trust tier label from calibration metrics.

    Args:
        brier_score: Agent's Brier score (lower is better)
        prediction_count: Number of resolved predictions

    Returns:
        One of "excellent", "good", "moderate", "poor", or "unrated"
    """
    if prediction_count < 20:
        return "unrated"
    if brier_score < 0.1:
        return "excellent"
    if brier_score < 0.2:
        return "good"
    if brier_score < 0.35:
        return "moderate"
    return "poor"


def agent_to_dict(
    agent: dict[str, Any] | AgentRating | Any | None,
    include_name: bool = True,
    calibration_tracker: CalibrationTracker | None = None,
) -> dict[str, Any]:
    """Convert agent object or dict to standardized dict with ELO fields.

    Handles the common pattern where agent data might be either a dict
    or an AgentRating object, extracting standard fields with safe defaults.

    Args:
        agent: Dict or object containing agent data
        include_name: Whether to include name/agent_name fields (default: True)
        calibration_tracker: Optional tracker to enrich with calibration data

    Returns:
        Dict with standardized ELO-related fields

    Example:
        # Before (repeated 40+ times across handlers):
        agent_dict = {
            "name": getattr(agent, "name", "unknown"),
            "elo": getattr(agent, "elo", 1500),
            "wins": getattr(agent, "wins", 0),
            "losses": getattr(agent, "losses", 0),
            ...
        }

        # After:
        agent_dict = agent_to_dict(agent)
    """
    if agent is None:
        return {}

    if isinstance(agent, dict):
        result = agent.copy()
        # Enrich dict with calibration if tracker provided and agent has a name
        if calibration_tracker is not None:
            name = result.get("agent_name") or result.get("name")
            if name:
                result = _enrich_with_calibration(result, str(name), calibration_tracker)
        return result

    # Extract standard ELO fields from object
    name = get_agent_name(agent) or "unknown"
    result = {
        "elo": getattr(agent, "elo", 1500),
        "wins": getattr(agent, "wins", 0),
        "losses": getattr(agent, "losses", 0),
        "draws": getattr(agent, "draws", 0),
        "win_rate": getattr(agent, "win_rate", 0.0),
        "games": getattr(agent, "games_played", getattr(agent, "games", 0)),
        "matches": getattr(agent, "matches", 0),
    }

    if include_name:
        result["name"] = name
        result["agent_name"] = name

    # Enrich with calibration data
    if calibration_tracker is not None:
        result = _enrich_with_calibration(result, name, calibration_tracker)

    return result


def _enrich_with_calibration(
    result: dict[str, Any],
    agent_name: str,
    calibration_tracker: Any,
) -> dict[str, Any]:
    """Add calibration sub-dict to an agent result dict.

    Args:
        result: Existing agent dict to enrich
        agent_name: Agent name for calibration lookup
        calibration_tracker: Tracker instance

    Returns:
        The result dict (modified in-place and returned)
    """
    try:
        summary = calibration_tracker.get_calibration_summary(agent_name)
        if summary.total_predictions > 0:
            result["calibration"] = {
                "brier_score": round(summary.brier_score, 4),
                "ece": round(summary.ece, 4),
                "trust_tier": _compute_trust_tier(summary.brier_score, summary.total_predictions),
                "prediction_count": summary.total_predictions,
            }
    except (AttributeError, TypeError, ValueError, OSError):
        pass
    return result


def safe_error_response(
    exception: Exception,
    context: str,
    status: int = 500,
    handler: HTTPRequestHandler | None = None,
) -> HandlerResult:
    """Create an error response with sanitized message.

    Logs full exception details server-side for debugging, but returns only
    a generic, safe message to the client. This prevents information disclosure
    of internal paths, stack traces, and sensitive configuration.

    Args:
        exception: The exception that occurred
        context: Context for logging (e.g., "debate creation", "agent lookup")
        status: HTTP status code (default: 500)
        handler: Optional request handler for extracting trace_id

    Returns:
        HandlerResult with sanitized error message

    Example:
        try:
            result = do_something()
        except Exception as e:
            return safe_error_response(e, "debate creation", 500, handler)
    """
    from aragora.server.errors import ErrorFormatter

    # Generate or extract trace ID
    trace_id = None
    if handler is not None:
        # Try to get existing trace_id from handler
        if hasattr(handler, "trace_id"):
            trace_id = handler.trace_id
        elif hasattr(handler, "headers") and handler.headers:
            trace_id = handler.headers.get("X-Request-ID") or handler.headers.get("X-Trace-ID")
    if not trace_id:
        trace_id = generate_trace_id()

    # Format error with sanitization (logs full details server-side)
    error_dict = ErrorFormatter.format_server_error(exception, context=context, trace_id=trace_id)

    return json_response(error_dict, status=status)


# =============================================================================
# BaseHandler Class
# =============================================================================


class BaseHandler:
    """
    Base class for endpoint handlers.

    Subclasses implement specific endpoint groups and register
    their routes via the `routes` class attribute.
    """

    ctx: dict[str, Any]
    _current_handler: Any = None
    _current_query_params: dict[str, Any] | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Allow server_context kwarg for handlers that only accept ctx."""
        super().__init_subclass__(**kwargs)
        original_init = cls.__init__
        if original_init is BaseHandler.__init__:
            return

        signature = inspect.signature(original_init)
        if "server_context" in signature.parameters:
            return

        @functools.wraps(original_init)
        def _wrapped_init(self: Any, *args: Any, server_context: Any = None, **kwargs: Any) -> None:  # type: ignore[no-untyped-def]
            if server_context is not None and "ctx" in signature.parameters and "ctx" not in kwargs:
                kwargs["ctx"] = server_context
            original_init(self, *args, **kwargs)

        cls.__init__ = _wrapped_init  # type: ignore[assignment]

    def __init__(self, server_context: ServerContext | dict[str, Any]):
        """
        Initialize with server context.

        Args:
            server_context: ServerContext containing shared server resources like
                           storage, elo_system, debate_embeddings, etc.
                           See ServerContext TypedDict for available fields.
        """
        self.ctx = cast(dict[str, Any], server_context)
        self._current_handler = None
        self._current_query_params = {}

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path.

        Default implementation checks against the ROUTES class attribute.
        Subclasses may override for prefix-based or dynamic matching.
        """
        routes = getattr(self, "ROUTES", None)
        if routes is None:
            return False
        if isinstance(routes, dict):
            return path in routes
        for route in routes:
            if isinstance(route, (tuple, list)):
                route_path = route[1] if len(route) >= 2 else route[0]
            elif isinstance(route, str) and " " in route:
                route_path = route.split(" ", 1)[1]
            else:
                route_path = route
            if path == route_path or (isinstance(route_path, str) and path.startswith(route_path)):
                return True
        return False

    def set_request_context(self, handler: Any, query_params: dict[str, Any] | None = None) -> None:
        """Set the current request context for helper methods.

        Call this at the start of request handling to enable helper methods
        like get_query_param(), get_json_body(), json_response(), json_error().

        Args:
            handler: HTTP request handler
            query_params: Parsed query parameters dict
        """
        self._current_handler = handler
        self._current_query_params = query_params or {}

    def get_query_param(
        self,
        name_or_handler: Any,
        name_or_default: str | None = None,
        default: str | None = None,
    ) -> str | None:
        """Get a query parameter from the current request.

        Supports two calling patterns for backwards compatibility:
        1. get_query_param(name, default) - uses stored request context
        2. get_query_param(handler, name, default) - extracts from handler

        Args:
            name_or_handler: Either parameter name (str) or HTTP handler
            name_or_default: Either default value or parameter name
            default: Default value (only used in handler pattern)

        Returns:
            Parameter value or default
        """
        # Detect calling pattern
        if isinstance(name_or_handler, str):
            # Pattern 1: get_query_param(name, default)
            name = name_or_handler
            default_value = name_or_default
            if self._current_query_params is None:
                return default_value
            value = self._current_query_params.get(name)
        else:
            # Pattern 2: get_query_param(handler, name, default)
            handler = name_or_handler
            name = name_or_default or ""
            default_value = default
            # Try to extract query params from handler
            query_params = {}
            if hasattr(handler, "path") and "?" in handler.path:
                from urllib.parse import parse_qs, urlparse

                parsed = urlparse(handler.path)
                query_params = parse_qs(parsed.query)
            value = query_params.get(name)

        if isinstance(value, list):
            return value[0] if value else default_value
        return value if value is not None else default_value

    def get_json_body(self) -> dict[str, Any] | None:
        """Get JSON body from the current request.

        Returns:
            Parsed JSON dict, empty dict if no body, None on error
        """
        if self._current_handler is None:
            return None
        return self.read_json_body(self._current_handler)

    def json_response(
        self,
        data: Any,
        status: int | HTTPStatus = HTTPStatus.OK,
    ) -> HandlerResult:
        """Create a JSON response.

        Args:
            data: Data to serialize as JSON
            status: HTTP status code

        Returns:
            HandlerResult with JSON response
        """
        status_code = status.value if isinstance(status, HTTPStatus) else status
        return json_response(data, status=status_code)

    def success_response(
        self,
        data: Any,
        status: int | HTTPStatus = HTTPStatus.OK,
    ) -> HandlerResult:
        """Create a standard success response."""
        status_code = status.value if isinstance(status, HTTPStatus) else status
        return json_response(data, status=status_code)

    def error_response(
        self,
        message: str,
        status: int | HTTPStatus = HTTPStatus.BAD_REQUEST,
    ) -> HandlerResult:
        """Create a standard error response."""
        status_code = status.value if isinstance(status, HTTPStatus) else status
        return error_response(message, status=status_code)

    def json_error(
        self,
        message: str,
        status: int | HTTPStatus = HTTPStatus.BAD_REQUEST,
    ) -> HandlerResult:
        """Create a JSON error response.

        Args:
            message: Error message
            status: HTTP status code

        Returns:
            HandlerResult with error response
        """
        status_code = status.value if isinstance(status, HTTPStatus) else status
        return error_response(message, status_code)

    def extract_path_param(
        self,
        path: str,
        segment_index: int,
        param_name: str,
        pattern: re.Pattern[str] | None = None,
    ) -> tuple[str | None, HandlerResult | None]:
        """Extract and validate a path segment parameter.

        Consolidates the common pattern of:
        1. Split path into parts
        2. Check segment exists at index
        3. Validate against pattern
        4. Return error response if invalid

        Args:
            path: URL path to extract from
            segment_index: Index of segment to extract (0-based)
            param_name: Human-readable name for error messages
            pattern: Regex pattern to validate against (default: SAFE_ID_PATTERN)

        Returns:
            Tuple of (value, error_response):
            - (value, None) on success
            - (None, HandlerResult) on failure

        Example:
            # Before:
            parts = path.split("/")
            if len(parts) < 4:
                return error_response("Invalid path", 400)
            domain = parts[3]
            is_valid, err = validate_path_segment(domain, "domain", SAFE_ID_PATTERN)
            if not is_valid:
                return error_response(err, 400)

            # After:
            domain, err = self.extract_path_param(path, 3, "domain")
            if err:
                return err
        """
        pattern = pattern or SAFE_ID_PATTERN
        # Don't strip leading slash - handler code expects index 0 to be empty string
        # e.g., "/api/agent/claude/profile" -> ["", "api", "agent", "claude", "profile"]
        parts = path.split("/")

        if segment_index >= len(parts):
            return None, error_response(f"Missing {param_name} in path", 400)

        value = parts[segment_index]
        if not value:
            return None, error_response(f"Empty {param_name}", 400)

        is_valid, err_msg = validate_path_segment(value, param_name, pattern)
        if not is_valid:
            return None, error_response(err_msg, 400)

        return value, None

    def extract_path_params(
        self,
        path: str,
        param_specs: list[tuple[int, str, re.Pattern[str] | None]],
    ) -> tuple[dict[str, str] | None, HandlerResult | None]:
        """Extract and validate multiple path parameters at once.

        Args:
            path: URL path to extract from
            param_specs: List of (segment_index, param_name, pattern) tuples.
                        If pattern is None, SAFE_ID_PATTERN is used.

        Returns:
            Tuple of (params_dict, error_response):
            - ({"name": value, ...}, None) on success
            - (None, HandlerResult) on first failure

        Example:
            # Extract agent_a and agent_b from /api/agents/compare/claude/gpt4
            params, err = self.extract_path_params(path, [
                (3, "agent_a", SAFE_AGENT_PATTERN),
                (4, "agent_b", SAFE_AGENT_PATTERN),
            ])
            if err:
                return err
            # params = {"agent_a": "claude", "agent_b": "gpt4"}
        """
        result = {}
        for segment_index, param_name, pattern in param_specs:
            value, err = self.extract_path_param(path, segment_index, param_name, pattern)
            if err:
                return None, err
            result[param_name] = value
        return result, None

    def get_storage(self) -> DebateStorage | None:
        """Get debate storage instance."""
        return self.ctx.get("storage")

    def get_elo_system(self) -> EloSystem | None:
        """Get ELO system instance."""
        # Check class attribute first (set by unified_server), then ctx
        if hasattr(self.__class__, "elo_system") and self.__class__.elo_system is not None:
            elo: EloSystem | None = self.__class__.elo_system
            return elo
        return self.ctx.get("elo_system")

    def get_debate_embeddings(self) -> DebateEmbeddingsDatabase | None:
        """Get debate embeddings database."""
        return self.ctx.get("debate_embeddings")

    def get_critique_store(self) -> CritiqueStore | None:
        """Get critique store instance."""
        return self.ctx.get("critique_store")

    def get_calibration_tracker(self) -> CalibrationTracker | None:
        """Get calibration tracker instance."""
        if (
            hasattr(self.__class__, "calibration_tracker")
            and self.__class__.calibration_tracker is not None
        ):
            ct: CalibrationTracker | None = self.__class__.calibration_tracker
            return ct
        return self.ctx.get("calibration_tracker")

    def get_nomic_dir(self) -> Path | None:
        """Get nomic directory path."""
        return self.ctx.get("nomic_dir")

    def get_current_user(self, handler: HTTPRequestHandler) -> UserAuthContext | None:
        """Get authenticated user from request, if any.

        Unlike @require_user_auth decorator which requires authentication,
        this method allows optional authentication - returning None if
        no valid auth is provided. Useful for endpoints that work for
        anonymous users but have enhanced features when authenticated.

        Args:
            handler: HTTP request handler with headers

        Returns:
            UserAuthContext if authenticated, None otherwise

        Example:
            def handle(self, path, query_params, handler):
                user = self.get_current_user(handler)
                if user:
                    # Show personalized content
                    return json_response({"user": user.email, "debates": ...})
                else:
                    # Show public content
                    return json_response({"debates": ...})
        """
        from aragora.billing.jwt_auth import extract_user_from_request

        user_store = None
        if hasattr(handler, "user_store"):
            user_store = handler.user_store
        elif hasattr(self.__class__, "user_store"):
            user_store = self.__class__.user_store

        user_ctx = extract_user_from_request(handler, user_store)
        return user_ctx if user_ctx.is_authenticated else None

    def require_auth_or_error(
        self, handler: HTTPRequestHandler
    ) -> tuple[UserAuthContext | None, HandlerResult | None]:
        """Require authentication and return user or error response.

        Alternative to @require_user_auth decorator for cases where you need
        the user context inline without using a decorator.

        Args:
            handler: HTTP request handler with headers

        Returns:
            Tuple of (UserAuthContext, None) if authenticated,
            or (None, HandlerResult) with 401 error if not

        Example:
            def handle_post(self, path, query_params, handler):
                user, err = self.require_auth_or_error(handler)
                if err:
                    return err
                # user is now guaranteed to be authenticated
                return json_response({"created_by": user.user_id})
        """
        user = self.get_current_user(handler)
        if user is None:
            return None, error_response("Authentication required", 401)
        return user, None

    def require_admin_or_error(
        self, handler: HTTPRequestHandler
    ) -> tuple[UserAuthContext | None, HandlerResult | None]:
        """Require admin authentication and return user or error response.

        Checks that the user is authenticated and has admin privileges
        (either 'admin' role or 'admin' permission).

        Args:
            handler: HTTP request handler with headers

        Returns:
            Tuple of (UserAuthContext, None) if authenticated as admin,
            or (None, HandlerResult) with 401/403 error if not

        Example:
            def handle_post(self, path, query_params, handler):
                user, err = self.require_admin_or_error(handler)
                if err:
                    return err
                # user is now guaranteed to be an admin
                return json_response({"admin_action": "completed"})
        """
        user, err = self.require_auth_or_error(handler)
        if err:
            return None, err

        # Check for admin role or permission
        roles = getattr(user, "roles", []) or []
        permissions = getattr(user, "permissions", []) or []

        is_admin = "admin" in roles or "admin" in permissions or getattr(user, "is_admin", False)

        if not is_admin:
            return None, error_response("Admin access required", 403)

        return user, None

    def require_permission_or_error(
        self, handler: HTTPRequestHandler, permission: str
    ) -> tuple[UserAuthContext, None] | tuple[None, HandlerResult]:
        """Require authentication and specific permission.

        Checks that the user is authenticated and has the required permission.
        Use this for inline permission checking when different paths need
        different permissions.

        Args:
            handler: HTTP request handler with headers
            permission: Required permission string (e.g., "knowledge.read")

        Returns:
            Tuple of (UserAuthContext, None) if authenticated with permission,
            or (None, HandlerResult) with 401/403 error if not

        Example:
            def handle_post(self, path, query_params, handler):
                if path.endswith("/store"):
                    user, err = self.require_permission_or_error(handler, "knowledge.write")
                else:
                    user, err = self.require_permission_or_error(handler, "knowledge.read")
                if err:
                    return err
                # user has required permission
                return json_response({"status": "ok"})
        """
        user, err = self.require_auth_or_error(handler)
        if err:
            return None, err

        # Check permission using role and permissions
        roles = getattr(user, "roles", []) or []
        permissions = getattr(user, "permissions", []) or []
        role = getattr(user, "role", None)

        # Admin role has all permissions
        if "admin" in roles or "admin" in permissions or role == "admin":
            return user, None

        # Owner role has all permissions
        if "owner" in roles or role == "owner":
            return user, None

        # Check specific permission
        if permission in permissions:
            return user, None

        # Check using PERMISSION_MATRIX from decorators
        try:
            from aragora.server.handlers.utils.decorators import has_permission

            if role and has_permission(role, permission):
                return user, None
        except ImportError:
            pass

        return None, error_response("Permission denied", 403)

    # === POST Body Parsing Support ===

    # Maximum request body size (10MB default)
    MAX_BODY_SIZE = 10 * 1024 * 1024

    def read_json_body(self, handler: Any, max_size: int | None = None) -> dict[str, Any] | None:
        """Read and parse JSON body from request handler.

        Handles missing Content-Length (e.g. Cloudflare HTTP/2 proxying)
        and Transfer-Encoding: chunked.

        Args:
            handler: The HTTP request handler with headers and rfile
            max_size: Maximum body size to accept (default: MAX_BODY_SIZE)

        Returns:
            Parsed JSON dict, empty dict for no content, or None for parse errors
        """
        max_size = max_size or self.MAX_BODY_SIZE
        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            is_chunked = "chunked" in (handler.headers.get("Transfer-Encoding", "") or "").lower()

            if content_length > max_size:
                return None  # Body too large

            if content_length > 0:
                body = handler.rfile.read(content_length)
            elif is_chunked or content_length == 0:
                # Missing or zero Content-Length: read available data up to max_size.
                # This handles Cloudflare HTTP/2 -> HTTP/1.1 proxy scenarios.
                body = handler.rfile.read(max_size)
            else:
                return {}

            if not body:
                return {}
            if len(body) > max_size:
                return None  # Body too large after read
            return json.loads(body)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    def validate_content_length(self, handler: Any, max_size: int | None = None) -> int | None:
        """Validate Content-Length header.

        Args:
            handler: The HTTP request handler
            max_size: Maximum allowed size (default: MAX_BODY_SIZE)

        Returns:
            Content length if valid, None if invalid
        """
        max_size = max_size or self.MAX_BODY_SIZE
        try:
            content_length = int(handler.headers.get("Content-Length", "0"))
        except ValueError:
            return None

        if content_length < 0 or content_length > max_size:
            return None

        return content_length

    def validate_json_content_type(self, handler: Any) -> HandlerResult | None:
        """Validate that Content-Type is application/json for JSON endpoints.

        Args:
            handler: The HTTP request handler with headers

        Returns:
            None if valid, HandlerResult with 415 error if Content-Type is invalid
        """
        if not hasattr(handler, "headers"):
            return error_response("Missing Content-Type header", 415)

        content_type = handler.headers.get("Content-Type", "")
        # Accept application/json with or without charset
        if not content_type:
            # Allow empty Content-Type for backwards compatibility with empty bodies
            content_length = handler.headers.get("Content-Length", "0")
            if content_length == "0" or content_length == 0:
                return None
            return error_response("Content-Type header required for POST with body", 415)

        # Parse media type (ignore parameters like charset)
        media_type = content_type.split(";")[0].strip().lower()
        if media_type not in ("application/json", "text/json"):
            return error_response(
                f"Unsupported Content-Type: {content_type}. Expected application/json", 415
            )

        return None

    def read_json_body_validated(
        self, handler: Any, max_size: int | None = None
    ) -> tuple[dict[str, Any] | None, HandlerResult | None]:
        """Read and parse JSON body with Content-Type validation.

        Combines Content-Type validation and body parsing into a single call.

        Args:
            handler: The HTTP request handler with headers and rfile
            max_size: Maximum body size to accept (default: MAX_BODY_SIZE)

        Returns:
            Tuple of (parsed_dict, None) on success,
            or (None, HandlerResult) with error response on failure
        """
        # Validate Content-Type
        content_type_error = self.validate_json_content_type(handler)
        if content_type_error:
            return None, content_type_error

        # Read and parse body
        body = self.read_json_body(handler, max_size)
        if body is None:
            return None, error_response("Invalid or too large JSON body", 400)

        return body, None

    def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> MaybeAsyncHandlerResult:
        """
        Handle a GET request. Override in subclasses.

        Args:
            path: The request path
            query_params: Parsed query parameters
            handler: HTTP request handler for accessing request context

        Returns:
            HandlerResult if handled, None if not handled by this handler
        """
        return None

    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> MaybeAsyncHandlerResult:
        """
        Handle a POST request. Override in subclasses that support POST.

        Args:
            path: The request path
            query_params: Parsed query parameters
            handler: HTTP request handler for accessing request context

        Returns:
            HandlerResult if handled, None if not handled by this handler
        """
        return None

    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> MaybeAsyncHandlerResult:
        """
        Handle a DELETE request. Override in subclasses that support DELETE.

        Args:
            path: The request path
            query_params: Parsed query parameters
            handler: HTTP request handler for accessing request context

        Returns:
            HandlerResult if handled, None if not handled by this handler
        """
        return None

    def handle_patch(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> MaybeAsyncHandlerResult:
        """
        Handle a PATCH request. Override in subclasses that support PATCH.

        Args:
            path: The request path
            query_params: Parsed query parameters
            handler: HTTP request handler for accessing request context

        Returns:
            HandlerResult if handled, None if not handled by this handler
        """
        return None

    def handle_put(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> MaybeAsyncHandlerResult:
        """
        Handle a PUT request. Override in subclasses that support PUT.

        Args:
            path: The request path
            query_params: Parsed query parameters
            handler: HTTP request handler for accessing request context

        Returns:
            HandlerResult if handled, None if not handled by this handler
        """
        return None


def __getattr__(name: str) -> Any:  # type: ignore[no-untyped-def]
    """Lazily expose typed handler classes to avoid circular imports."""
    if name in {
        "TypedHandler",  # noqa: F822
        "AuthenticatedHandler",  # noqa: F822
        "PermissionHandler",  # noqa: F822
        "AdminHandler",  # noqa: F822
        "AsyncTypedHandler",  # noqa: F822
        "ResourceHandler",  # noqa: F822
        "MaybeAsyncHandlerResult",
    }:
        from aragora.server.handlers import typed_handlers as _typed_handlers

        return getattr(_typed_handlers, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
