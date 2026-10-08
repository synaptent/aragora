"""
Handler registry for modular HTTP endpoint routing.

This module provides centralized initialization and routing for all modular
HTTP handlers. The HandlerRegistryMixin can be mixed into request handler
classes to add modular routing capabilities.

Features:
- O(1) exact path lookup via route index
- LRU cached prefix matching for dynamic routes
- Lazy handler initialization
- API versioning support (/api/v1/... paths)

Usage:
    class MyHandler(HandlerRegistryMixin, BaseHTTPRequestHandler):
        pass

The handler registry is split into domain-specific submodules:
- core.py: Core infrastructure (RouteIndex, validation, utilities)
- debates.py: Debate-related handlers
- agents.py: Agent-related handlers
- memory.py: Memory and knowledge handlers
- analytics.py: Analytics and metrics handlers
- social.py: Social and chat handlers
- admin.py: Admin and enterprise handlers
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any, BinaryIO
from collections.abc import Callable

from aragora.server.versioning import (
    extract_version,
    normalize_path_version,
    strip_version_prefix,
    version_response_headers,
)
# Rate limit functions are imported lazily in _try_modular_handler() to avoid
# importing the full rate_limit package (630+ modules) at module load time.
# This saves ~1.3s on server startup.

# Import core infrastructure
from .core import (
    HANDLER_TIERS,
    HandlerType,
    HandlerValidationError,
    RouteIndex,
    _DeferredImport,
    _run_handler_coroutine,
    _safe_import,
    check_handler_coverage,
    filter_registry_by_tier,
    get_active_tiers,
    get_route_index,
    validate_all_handlers,
    validate_handler_class,
    validate_handler_instance,
    validate_handlers_on_init,
)
from .instrumented import auto_instrument_handler

# Import domain-specific registries
from .admin import ADMIN_HANDLER_REGISTRY
from .agents import AGENT_HANDLER_REGISTRY
from .analytics import ANALYTICS_HANDLER_REGISTRY
from .debates import DEBATE_HANDLER_REGISTRY
from .memory import MEMORY_HANDLER_REGISTRY
from .social import SOCIAL_HANDLER_REGISTRY

# Import critical handlers for availability check
from .admin import HealthHandler, SystemHandler
from .debates import DebatesHandler

if TYPE_CHECKING:
    from pathlib import Path

    from aragora.agents.personas import PersonaManager
    from aragora.agents.positions import PositionLedger
    from aragora.debate.embeddings import DebateEmbeddingsDatabase
    from aragora.memory.store import CritiqueStore
    from aragora.ranking.elo import EloSystem
    from aragora.storage.debate_storage import DebateStorage

logger = logging.getLogger(__name__)


# =============================================================================
# Combined Handler Registry
# =============================================================================

# Build the combined handler registry from domain-specific registries
# Order matters for routing - more specific handlers should come first
HANDLER_REGISTRY: list[tuple[str, Any]] = [
    *ADMIN_HANDLER_REGISTRY,  # Core system handlers first (health, docs)
    *DEBATE_HANDLER_REGISTRY,
    *AGENT_HANDLER_REGISTRY,
    *ANALYTICS_HANDLER_REGISTRY,
    *MEMORY_HANDLER_REGISTRY,
    *SOCIAL_HANDLER_REGISTRY,
]

# Compute availability: with deferred imports, handler classes are _DeferredImport
# proxies (always truthy). Actual import failures are caught later in _init_handlers().
# This is intentional — it allows the server to start fast and defer handler loading
# to first-request time.
HANDLERS_AVAILABLE = all(
    [
        SystemHandler is not None,
        HealthHandler is not None,
        DebatesHandler is not None,
    ]
)


class HandlerRegistryMixin:
    """
    Mixin providing modular HTTP handler initialization and routing.

    This mixin expects the following class attributes from the parent:
    - storage: DebateStorage | None
    - elo_system: EloSystem | None
    - debate_embeddings: DebateEmbeddingsDatabase | None
    - document_store: DocumentStore | None
    - nomic_state_file: Path | None (for deriving nomic_dir)
    - critique_store: CritiqueStore | None
    - persona_manager: PersonaManager | None
    - position_ledger: PositionLedger | None

    And these methods:
    - _add_cors_headers()
    - _add_security_headers()
    - send_response(status)
    - send_header(name, value)
    - end_headers()
    - wfile.write(data)
    """

    # Type stubs for attributes expected from parent class
    storage: DebateStorage | None
    elo_system: EloSystem | None
    debate_embeddings: DebateEmbeddingsDatabase | None
    document_store: Any | None
    nomic_state_file: Path | None
    critique_store: CritiqueStore | None
    persona_manager: PersonaManager | None
    position_ledger: PositionLedger | None
    wfile: BinaryIO
    _auth_context: Any

    # Type stubs for methods expected from parent class
    _add_cors_headers: Callable[[], None]
    _add_security_headers: Callable[[], None]
    _add_trace_headers: Callable[[], None]
    send_response: Callable[[int], None]
    send_header: Callable[[str, str], None]
    end_headers: Callable[[], None]

    # Handler instances (initialized lazily, with thread-safe init)
    _handlers_initialized: bool = False
    _init_lock = __import__("threading").Lock()

    @classmethod
    def _init_handlers(cls) -> None:
        """Initialize modular HTTP handlers with server context.

        Called lazily on first request. Creates handler instances with
        references to storage, ELO system, and other shared resources.

        Deferred imports: Handler classes are stored as _DeferredImport
        proxies at module load time. The actual module imports happen here,
        on first request, avoiding the cost of importing 165+ handler
        modules during server startup.

        Thread-safe: uses double-checked locking to prevent race conditions
        in ThreadingHTTPServer where concurrent requests could see partially
        initialized state (handlers created but route index not yet built).
        """
        # Fast path: already initialized (no lock needed)
        if cls._handlers_initialized or not HANDLERS_AVAILABLE:
            return

        # Acquire lock for thread-safe initialization
        with cls._init_lock:
            # Double-check after acquiring lock
            if cls._handlers_initialized:
                return

            t_start = time.monotonic()

            # Build server context for handlers
            nomic_dir = None
            if hasattr(cls, "nomic_state_file") and cls.nomic_state_file:
                nomic_dir = cls.nomic_state_file.parent

            ctx = {
                "storage": getattr(cls, "storage", None),
                "stream_emitter": getattr(cls, "stream_emitter", None),
                "control_plane_stream": getattr(cls, "control_plane_stream", None),
                "nomic_loop_stream": getattr(cls, "nomic_loop_stream", None),
                "elo_system": getattr(cls, "elo_system", None),
                "nomic_dir": nomic_dir,
                "debate_embeddings": getattr(cls, "debate_embeddings", None),
                "critique_store": getattr(cls, "critique_store", None),
                "document_store": getattr(cls, "document_store", None),
                "persona_manager": getattr(cls, "persona_manager", None),
                "position_ledger": getattr(cls, "position_ledger", None),
                "user_store": getattr(cls, "user_store", None),
                "continuum_memory": getattr(cls, "continuum_memory", None),
                "cross_debate_memory": getattr(cls, "cross_debate_memory", None),
                "knowledge_mound": getattr(cls, "knowledge_mound", None),
            }

            # Filter registry by active tiers
            active_tiers = get_active_tiers()
            active_registry = filter_registry_by_tier(HANDLER_REGISTRY, active_tiers)

            t_filter = time.monotonic()
            import_failures = 0
            init_count = 0

            # Initialize handlers from filtered registry with auto-instrumentation
            for attr_name, handler_ref in active_registry:
                # Resolve deferred imports (lazy → actual class)
                if isinstance(handler_ref, _DeferredImport):
                    handler_class = handler_ref.resolve()
                else:
                    handler_class = handler_ref

                if handler_class is not None:
                    try:
                        instance = handler_class(ctx)
                    except TypeError:
                        # Facade handlers (route discovery only) don't accept ctx
                        instance = handler_class()
                    except Exception as e:  # noqa: BLE001 - handler init can fail unpredictably
                        # Handler init failure (e.g., read-only DB) — skip handler
                        logger.warning(
                            "[init_handlers] %s init failed, skipping: %s: %s",
                            attr_name,
                            type(e).__name__,
                            e,
                        )
                        continue
                    auto_instrument_handler(instance)
                    setattr(cls, attr_name, instance)
                    init_count += 1
                else:
                    import_failures += 1

            t_init = time.monotonic()

            # Build route index for O(1) dispatch BEFORE setting initialized flag.
            # This prevents other threads from seeing _handlers_initialized=True
            # while the route index is still empty, which caused intermittent 404s.
            route_index = get_route_index()
            route_index.build(cls, active_registry)

            # Mark as initialized only AFTER routes are fully built
            cls._handlers_initialized = True

            t_done = time.monotonic()

            skipped = len(HANDLER_REGISTRY) - len(active_registry)
            tier_info = ",".join(sorted(active_tiers))
            logger.info(
                "[handlers] Initialized %d/%d handlers in %.1fms "
                "(resolve+init=%.1fms, routes=%.1fms, tiers=%s, skipped=%d, failed=%d)",
                init_count,
                len(HANDLER_REGISTRY),
                (t_done - t_start) * 1000,
                (t_init - t_filter) * 1000,
                (t_done - t_init) * 1000,
                tier_info,
                skipped,
                import_failures,
            )

            # Check for unregistered handler classes in the codebase
            try:
                check_handler_coverage(active_registry)
            except (ImportError, OSError, RuntimeError, ValueError) as e:
                logger.debug("[handlers] Handler coverage check failed: %s", e)

            # Validate instantiated handlers
            validation_results = validate_handlers_on_init(cls, active_registry)
            if validation_results["invalid"]:
                logger.warning(
                    "[handlers] %s handlers have validation issues",
                    len(validation_results["invalid"]),
                )

            # Log resource availability for observability
            cls._log_resource_availability(nomic_dir)

    @classmethod
    def _log_resource_availability(cls, nomic_dir) -> None:
        """Log which optional resources are available at startup."""
        from aragora.persistence.db_config import LEGACY_DB_NAMES, DatabaseType

        resources = {
            "storage": getattr(cls, "storage", None) is not None,
            "elo_system": getattr(cls, "elo_system", None) is not None,
            "debate_embeddings": getattr(cls, "debate_embeddings", None) is not None,
            "document_store": getattr(cls, "document_store", None) is not None,
            "nomic_dir": nomic_dir is not None,
        }

        # Check database files if nomic_dir exists
        if nomic_dir:
            db_files = [
                ("positions_db", "aragora_positions.db"),
                ("personas_db", LEGACY_DB_NAMES[DatabaseType.PERSONAS]),
                ("grounded_db", "grounded_positions.db"),
                ("insights_db", "insights.db"),
                ("calibration_db", "agent_calibration.db"),
                ("embeddings_db", "debate_embeddings.db"),
            ]
            for name, filename in db_files:
                resources[name] = (nomic_dir / filename).exists()

        available = [k for k, v in resources.items() if v]
        unavailable = [k for k, v in resources.items() if not v]

        if unavailable:
            logger.info("[resources] Available: %s", ", ".join(available))
            logger.info("[resources] Unavailable: %s", ", ".join(unavailable))
        else:
            logger.info("[resources] All resources available: %s", ", ".join(available))

    def _try_modular_handler(self, path: str, query: dict) -> bool:
        """Try to handle request via modular handlers.

        Uses O(1) route index for fast handler lookup instead of iterating
        through all handlers. Supports API versioning with automatic
        version header injection.

        Returns True if handled, False if should fall through to legacy routes.
        """
        if not HANDLERS_AVAILABLE:
            return False

        # Ensure handlers are initialized
        self._init_handlers()

        # Extract API version from path/headers
        request_headers = {}
        if hasattr(self, "headers"):
            request_headers = {k: v for k, v in self.headers.items()}
        api_version, is_legacy = extract_version(path, request_headers)

        # Normalize path for handler matching (strip version prefix)
        normalized_path = strip_version_prefix(path)
        candidate_paths = [path]
        if is_legacy:
            versioned_path = normalize_path_version(path, api_version)
            if versioned_path not in candidate_paths:
                candidate_paths.append(versioned_path)
        if normalized_path not in candidate_paths:
            candidate_paths.append(normalized_path)

        # Convert query params from {key: [val]} to {key: val}
        query_dict = {
            k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in query.items()
        }

        # Determine HTTP method for routing
        method = getattr(self, "command", "GET")

        # O(1) route lookup via index (uses both original and normalized paths)
        route_index = get_route_index()
        route_match = None
        matched_path = None
        for candidate in candidate_paths:
            route_match = route_index.get_handler(candidate)
            if route_match is not None:
                matched_path = candidate
                break

        if route_match is None:
            # Fallback: iterate through handlers for edge cases not in index
            for attr_name, _ in HANDLER_REGISTRY:
                handler = getattr(self, attr_name, None)
                if handler and hasattr(handler, "can_handle"):
                    for candidate in candidate_paths:
                        if handler.can_handle(candidate):
                            route_match = (attr_name, handler)
                            matched_path = candidate
                            break
                if route_match is not None:
                    break

        if route_match is None:
            return False

        attr_name, handler = route_match

        try:
            # Extract auth context and store on request handler for permission checks
            try:
                from aragora.billing.jwt_auth import extract_user_from_request
                from aragora.rbac.models import AuthorizationContext

                user_ctx = extract_user_from_request(self)
                if user_ctx and user_ctx.is_authenticated and user_ctx.user_id:
                    # Store auth context for handlers to access
                    self._auth_context = AuthorizationContext(
                        user_id=user_ctx.user_id,
                        user_email=user_ctx.email,
                        org_id=user_ctx.org_id,
                        workspace_id=self.headers.get("X-Workspace-ID")
                        if hasattr(self, "headers")
                        else None,
                        roles={user_ctx.role} if user_ctx.role else {"member"},
                        permissions=set(),  # Permissions loaded by checker
                    )
                else:
                    self._auth_context = None
            except (ImportError, AttributeError, KeyError, ValueError) as auth_err:
                logger.debug("[handlers] Auth context extraction failed: %s", auth_err)
                self._auth_context = None

            # Determine the handler method name for rate limit checking
            if method == "POST" and hasattr(handler, "handle_post"):
                handler_method_name = "handle_post"
            elif method == "DELETE" and hasattr(handler, "handle_delete"):
                handler_method_name = "handle_delete"
            elif method == "PATCH" and hasattr(handler, "handle_patch"):
                handler_method_name = "handle_patch"
            elif method == "PUT" and hasattr(handler, "handle_put"):
                handler_method_name = "handle_put"
            else:
                handler_method_name = "handle"

            # Apply default rate limiting if handler doesn't have explicit rate limit
            # Lazy import to avoid loading 630+ rate_limit modules at startup
            from aragora.server.middleware.rate_limit import (
                check_default_rate_limit,
                should_apply_default_rate_limit,
            )

            if should_apply_default_rate_limit(handler, handler_method_name):
                rate_limit_result = check_default_rate_limit(self)
                if not rate_limit_result.allowed:
                    # Return 429 Too Many Requests
                    body_429 = json.dumps(
                        {
                            "error": "Rate limit exceeded. Please try again later.",
                            "code": "rate_limit_exceeded",
                            "retry_after": int(rate_limit_result.retry_after) + 1,
                        }
                    ).encode()
                    self.send_response(429)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body_429)))
                    self.send_header("Retry-After", str(int(rate_limit_result.retry_after) + 1))
                    self.send_header("X-RateLimit-Limit", str(rate_limit_result.limit))
                    self.send_header("X-RateLimit-Remaining", str(rate_limit_result.remaining))
                    self._add_cors_headers()
                    self._add_security_headers()
                    self._add_trace_headers()
                    self.end_headers()
                    self.wfile.write(body_429)
                    return True

            # Use matched path if available, otherwise fall back to normalized path
            dispatch_path = matched_path or normalized_path
            if normalized_path != dispatch_path and handler.can_handle(normalized_path):
                dispatch_path = normalized_path

            # Dispatch to appropriate handler method based on HTTP method.
            # Try method-specific handler first (handle_post, handle_delete, etc.),
            # then fall through to generic handle() if it returns None.
            # This handles the case where BaseHandler defines stub methods that
            # return None, while the handler routes all methods via handle().
            result = None
            if method == "POST" and hasattr(handler, "handle_post"):
                result = handler.handle_post(dispatch_path, query_dict, self)
            elif method == "DELETE" and hasattr(handler, "handle_delete"):
                result = handler.handle_delete(dispatch_path, query_dict, self)
            elif method == "PATCH" and hasattr(handler, "handle_patch"):
                result = handler.handle_patch(dispatch_path, query_dict, self)
            elif method == "PUT" and hasattr(handler, "handle_put"):
                result = handler.handle_put(dispatch_path, query_dict, self)

            # Resolve async result from method-specific handler
            if asyncio.iscoroutine(result):
                result = _run_handler_coroutine(result)

            # Fall through to generic handle() when method-specific handler
            # returned None (e.g., base class stub or unhandled path)
            if result is None:
                result = handler.handle(dispatch_path, query_dict, self)

            # Handle async handlers - await coroutines
            if asyncio.iscoroutine(result):
                result = _run_handler_coroutine(result)

            if result:
                # Track status for request lifecycle logging
                self._response_status = result.status_code
                # Log successful handler dispatch at debug level
                logger.debug(
                    "[handlers] %s %s -> %s (status=%d)",
                    method,
                    path,
                    handler.__class__.__name__,
                    result.status_code,
                )
                self.send_response(result.status_code)
                self.send_header("Content-Type", result.content_type)
                self.send_header("Content-Length", str(len(result.body)))

                # Add API version headers
                version_headers = version_response_headers(
                    api_version,
                    is_legacy,
                    path=path,
                )
                existing = {name.lower() for name in result.headers}
                for h_name, h_val in version_headers.items():
                    if h_name.lower() in existing:
                        continue
                    self.send_header(h_name, h_val)

                # Add handler-specific headers
                for h_name, h_val in result.headers.items():
                    self.send_header(h_name, h_val)

                # Add CORS and security headers for modular handlers
                self._add_cors_headers()
                self._add_security_headers()
                self._add_trace_headers()
                self.end_headers()
                self.wfile.write(result.body)
                return True
        except ImportError as e:
            # Subsystem not available — return 503 not 500
            logger.warning(
                "[handlers] Subsystem unavailable in %s: %s", handler.__class__.__name__, e
            )
            body_503 = json.dumps(
                {
                    "error": "Feature temporarily unavailable",
                    "code": "subsystem_unavailable",
                }
            ).encode()
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_503)))
            self._add_cors_headers()
            self._add_security_headers()
            self._add_trace_headers()
            self.end_headers()
            self.wfile.write(body_503)
            return True
        except (
            RuntimeError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            PermissionError,
            LookupError,
            TimeoutError,
        ) as e:
            # Check for permission-related errors
            error_msg = str(e)
            if "AuthorizationContext" in error_msg or "Permission" in error_msg:
                logger.warning(
                    "[handlers] Permission denied in %s: %s", handler.__class__.__name__, e
                )
                body_403 = json.dumps({"error": "Permission denied", "code": "forbidden"}).encode()
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body_403)))
                self._add_cors_headers()
                self._add_security_headers()
                self._add_trace_headers()
                self.end_headers()
                self.wfile.write(body_403)
                return True
            logger.error("[handlers] Error in %s: %s", handler.__class__.__name__, e, exc_info=True)
            body_500 = json.dumps(
                {
                    "error": "Internal server error",
                    "code": "handler_error",
                    "handler": handler.__class__.__name__,
                }
            ).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_500)))
            self._add_cors_headers()
            self._add_security_headers()
            self._add_trace_headers()
            self.end_headers()
            self.wfile.write(body_500)
            return True
        except Exception as e:  # noqa: BLE001 - catch-all for diagnostic: catches exception types not in the specific list above
            logger.error(
                "[handlers] UNEXPECTED exception type %s in %s for %s %s: %s",
                type(e).__name__,
                handler.__class__.__name__,
                method,
                path,
                e,
                exc_info=True,
            )
            body_exc = json.dumps(
                {
                    "error": "Internal server error",
                    "code": "unexpected_exception",
                    "exception_type": type(e).__name__,
                    "handler": handler.__class__.__name__,
                }
            ).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_exc)))
            self._add_cors_headers()
            self._add_security_headers()
            self._add_trace_headers()
            self.end_headers()
            self.wfile.write(body_exc)
            return True

        # Handler was found but returned a falsy result — log this for debugging.
        # Common cause: async handler returned None (no path/method match inside handle()).
        if route_match is not None:
            logger.warning(
                "[handlers] Handler %s matched %s %s but returned falsy result: %r",
                handler.__class__.__name__,
                method,
                path,
                result,
            )
            body_no_result = json.dumps(
                {
                    "error": "Handler matched but returned no result",
                    "code": "handler_no_result",
                    "handler": handler.__class__.__name__,
                    "result_type": type(result).__name__,
                    "method": method,
                    "path": path,
                }
            ).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_no_result)))
            self._add_cors_headers()
            self._add_security_headers()
            self._add_trace_headers()
            self.end_headers()
            self.wfile.write(body_no_result)
            return True
        return False

    def _get_handler_stats(self) -> dict[str, Any]:
        """Get statistics about initialized handlers.

        Returns:
            Dict with handler counts and names
        """
        if not self._handlers_initialized:
            return {"initialized": False, "count": 0, "handlers": []}

        initialized_handlers = []
        for attr_name, _ in HANDLER_REGISTRY:
            handler = getattr(self, attr_name, None)
            if handler is not None:
                initialized_handlers.append(handler.__class__.__name__)

        return {
            "initialized": True,
            "count": len(initialized_handlers),
            "handlers": initialized_handlers,
        }


# =============================================================================
# Public API - Re-exports for backward compatibility
# =============================================================================

__all__ = [
    # Main exports
    "HandlerRegistryMixin",
    "HANDLER_REGISTRY",
    "HANDLERS_AVAILABLE",
    # Route index
    "RouteIndex",
    "get_route_index",
    # Type definitions
    "HandlerType",
    # Validation functions
    "HandlerValidationError",
    "validate_handler_class",
    "validate_handler_instance",
    "validate_all_handlers",
    "validate_handlers_on_init",
    "check_handler_coverage",
    # Tier configuration
    "HANDLER_TIERS",
    # Utilities
    "_safe_import",
    # Re-exported for backward compatibility
    "UnifiedHandler",
]


# Re-export UnifiedHandler from unified_server for backward compatibility
def __getattr__(name: str) -> Any:
    """Lazy import for UnifiedHandler to avoid circular import."""
    if name == "UnifiedHandler":
        from aragora.server.unified_server import UnifiedHandler

        return UnifiedHandler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
