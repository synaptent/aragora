"""
Memory-related endpoint handlers.

Endpoints:
- GET /api/v1/memory/continuum/retrieve - Retrieve memories from continuum
- POST /api/v1/memory/continuum/consolidate - Trigger memory consolidation
- POST /api/v1/memory/continuum/cleanup - Cleanup expired memories
- GET /api/v1/memory/tier-stats - Get tier statistics
- GET /api/v1/memory/archive-stats - Get archive statistics
- GET /api/v1/memory/pressure - Get memory pressure and utilization
- DELETE /api/v1/memory/continuum/{id} - Delete a memory by ID
- GET /api/v1/memory/tiers - List all memory tiers with detailed stats
- GET /api/v1/memory/search - Search memories across tiers
- GET /api/v1/memory/critiques - Browse critique store entries

Note: `/api/memory/*` legacy routes are normalized to `/api/v1/memory/*`.
"""

from __future__ import annotations

from typing import Any

import logging
import math

from aragora.rbac.decorators import require_permission

from ..base import (
    HandlerResult,
    error_response,
    get_bounded_string_param,
    handle_errors,
    json_response,
)
from ..secure import SecureHandler
from ..utils.rate_limit import RateLimiter, get_client_ip

# Import mixins
from .memory_continuum import MemoryContinuumMixin
from .memory_external import MemoryExternalMixin
from .memory_progressive import MemoryProgressiveMixin
from .memory_viewer import MemoryViewerMixin
from .memory_critiques import MemoryCritiquesMixin

# Rate limiters for memory endpoints
_retrieve_limiter = RateLimiter(requests_per_minute=60)  # Read operations
_stats_limiter = RateLimiter(requests_per_minute=30)  # Stats operations
_mutation_limiter = RateLimiter(requests_per_minute=10)  # State-changing operations

logger = logging.getLogger(__name__)

# Permissions for memory endpoints
MEMORY_READ_PERMISSION = "memory:read"
MEMORY_WRITE_PERMISSION = "memory:write"
MEMORY_MANAGE_PERMISSION = "memory:manage"

# Optional import for memory functionality.
# Fallbacks are assigned in the ``except`` branch so static type checkers do
# not see a redundant re-definition of the imported name.
try:
    from aragora.memory.continuum import MemoryTier

    CONTINUUM_AVAILABLE = True
except ImportError:
    MemoryTier = None  # type: ignore[assignment,misc]
    CONTINUUM_AVAILABLE = False

# Optional import for critique store - use canonical helper
from aragora.stores.canonical import is_critique_store_available

CRITIQUE_STORE_AVAILABLE = is_critique_store_available()

# Optional import for critique store class (for direct fallback + test patching)
try:
    from aragora.memory.store import CritiqueStore
except ImportError:
    CritiqueStore = None  # type: ignore[assignment,misc]


class MemoryHandler(
    MemoryContinuumMixin,
    MemoryExternalMixin,
    MemoryProgressiveMixin,
    MemoryViewerMixin,
    MemoryCritiquesMixin,
    SecureHandler,
):
    """Handler for memory-related endpoints.

    Requires authentication and memory:read/write permissions (RBAC).
    """

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = server_context or ctx or {}

    ROUTES = [
        "/api/v1/memory/continuum/retrieve",
        "/api/v1/memory/continuum/consolidate",
        "/api/v1/memory/continuum/cleanup",
        "/api/v1/memory/tier-stats",
        "/api/v1/memory/archive-stats",
        "/api/v1/memory/pressure",
        "/api/v1/memory/tiers",
        "/api/v1/memory/search",
        "/api/v1/memory/store",
        "/api/v1/memory/search-index",
        "/api/v1/memory/search-timeline",
        "/api/v1/memory/entries",
        "/api/v1/memory/viewer",
        "/api/v1/memory/critiques",
        # Advanced operations (SDK parity)
        "/api/v1/memory/compact",
        "/api/v1/memory/context",
        "/api/v1/memory/cross-debate",
        "/api/v1/memory/cross-debate/inject",
        "/api/v1/memory/export",
        "/api/v1/memory/import",
        "/api/v1/memory/prune",
        "/api/v1/memory/query",
        "/api/v1/memory/rebuild-index",
        "/api/v1/memory/semantic-search",
        "/api/v1/memory/snapshots",
        "/api/v1/memory/snapshots/*",
        "/api/v1/memory/snapshots/*/restore",
        "/api/v1/memory/sync",
        "/api/v1/memory/tier/*",
        "/api/v1/memory/vacuum",
        "/api/v1/memory/*",
        "/api/v1/memory/*/demote",
        "/api/v1/memory/*/move",
        "/api/v1/memory/*/promote",
    ]

    # Spec-only verb declaration for the continuum entry delete, whose
    # dispatch matches the "/api/v1/memory/continuum/" prefix inside
    # handle_delete (a prefix literal is not per-route evidence for the
    # generator); read by openapi_impl, not used for request routing.
    _ROUTE_MAP: dict = {
        "DELETE /api/v1/memory/continuum/{memory_id}": None,
    }

    @staticmethod
    def _normalize_path(path: str) -> str:
        if path.startswith("/api/memory/"):
            return "/api/v1" + path[len("/api") :]
        return path

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = self._normalize_path(path)
        if normalized in self.ROUTES:
            return True
        # Handle dynamic path segments under /api/v1/memory/
        if normalized.startswith("/api/v1/memory/"):
            return True
        return False

    def _get_user_store(self) -> Any:
        """Get user store from context."""
        return self.ctx.get("user_store")

    @require_permission("memory:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route memory requests to appropriate handler methods."""
        # Capture auth context for downstream filtering (set by handler registry)
        self._auth_context = getattr(handler, "_auth_context", None)
        path = self._normalize_path(path)
        client_ip = get_client_ip(handler)

        if path == "/api/v1/memory/continuum/retrieve":
            # Rate limit: 60/min for retrieve operations
            if not _retrieve_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._get_continuum_memories(query_params)

        # POST-only endpoints - return 405 Method Not Allowed for GET
        if path in ("/api/v1/memory/continuum/consolidate", "/api/v1/memory/continuum/cleanup"):
            return error_response(
                "Use POST method for this endpoint",
                405,
                headers={"Allow": "POST"},
            )

        if path == "/api/v1/memory/tier-stats":
            # Rate limit: 30/min for stats operations
            if not _stats_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._get_tier_stats()

        if path == "/api/v1/memory/archive-stats":
            # Rate limit: 30/min for stats operations
            if not _stats_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._get_archive_stats()

        if path == "/api/v1/memory/pressure":
            # Rate limit: 30/min for stats operations
            if not _stats_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._get_memory_pressure()

        if path == "/api/v1/memory/tiers":
            # Rate limit: 30/min for stats operations
            if not _stats_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._get_all_tiers()

        if path == "/api/v1/memory/search":
            # Rate limit: 60/min for retrieve operations
            if not _retrieve_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._search_memories(query_params)

        if path == "/api/v1/memory/search-index":
            if not _retrieve_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._search_index(query_params)

        if path == "/api/v1/memory/search-timeline":
            if not _retrieve_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._search_timeline(query_params)

        if path == "/api/v1/memory/entries":
            if not _retrieve_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._get_entries(query_params)

        if path == "/api/v1/memory/viewer":
            if not _retrieve_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._render_viewer()

        if path == "/api/v1/memory/critiques":
            # Rate limit: 30/min for stats operations
            if not _stats_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._get_critiques(query_params)

        if path == "/api/v1/memory/unified/stats":
            if not _stats_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._get_unified_stats()

        return None

    @handle_errors("memory creation")
    @require_permission("memory:manage")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route POST memory requests to admin-level state-mutating methods with auth."""
        path = self._normalize_path(path)
        from aragora.billing.jwt_auth import extract_user_from_request

        client_ip = get_client_ip(handler)

        if path == "/api/v1/memory/continuum/consolidate":
            # Rate limit: 10/min for mutation operations
            if not _mutation_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            # Require authentication for state mutation
            user_store = self._get_user_store()
            auth_ctx = extract_user_from_request(handler, user_store)
            if not auth_ctx.is_authenticated:
                return error_response("Authentication required", 401)
            return self._trigger_consolidation()

        if path == "/api/v1/memory/continuum/cleanup":
            # Rate limit: 10/min for mutation operations
            if not _mutation_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            # Require authentication for state mutation
            user_store = self._get_user_store()
            auth_ctx = extract_user_from_request(handler, user_store)
            if not auth_ctx.is_authenticated:
                return error_response("Authentication required", 401)
            return self._trigger_cleanup(query_params)

        if path == "/api/v1/memory/unified/search":
            if not _retrieve_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._unified_search(query_params, handler)

        if path == "/api/v1/memory/store":
            # Rate limit: 10/min for mutation operations
            if not _mutation_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            return self._store_memory(handler)

        # Promote an entry to a new tier: POST /api/v1/memory/{id}/promote
        if path.endswith("/promote") and path.startswith("/api/v1/memory/"):
            # Rate limit: 10/min for mutation operations
            if not _mutation_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)
            # split("/") => ["", "api", "v1", "memory", "{id}", "promote"]
            memory_id, err = self.extract_path_param(path, 4, "memory_id")
            if err or memory_id is None:
                return err or error_response("Empty memory_id", 400)
            return self._promote_memory(memory_id, handler)

        return None

    def _resolve_tier(self, tier_name: str) -> Any:
        """Resolve a tier name string to a MemoryTier enum, or None if invalid."""
        if not CONTINUUM_AVAILABLE or MemoryTier is None:
            return None
        try:
            return MemoryTier[tier_name.strip().upper()]
        except (KeyError, AttributeError):
            return None

    def _store_memory(self, handler: Any) -> HandlerResult:
        """Store a new memory entry: POST /api/v1/memory/store.

        Expects JSON body: {"content": str, "tier": str, "importance"?: float}.
        Returns {"id": str, "tier": str}.
        """
        if not CONTINUUM_AVAILABLE:
            return error_response("Continuum memory system not available", 503)

        continuum = self.ctx.get("continuum_memory")
        if not continuum:
            return error_response("Continuum memory not initialized", 503)

        body = self.read_json_body(handler) or {}
        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            return error_response("Missing required field: content", 400)

        tier_name = body.get("tier", "fast")
        tier = self._resolve_tier(str(tier_name))
        if tier is None:
            return error_response(f"Invalid tier: {tier_name}", 400)

        importance = body.get("importance", 0.5)
        try:
            importance = float(importance)
        except (TypeError, ValueError):
            importance = 0.5
        importance = max(0.0, min(1.0, importance))

        import uuid

        memory_id = str(uuid.uuid4())
        try:
            entry = continuum.add(
                id=memory_id,
                content=content,
                tier=tier,
                importance=importance,
            )
        except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
            logger.warning("Memory store failed: %s", e)
            return error_response("Failed to store memory entry", 500)

        stored_id = getattr(entry, "id", None) or memory_id
        return json_response({"id": stored_id, "tier": tier.name.lower()})

    def _promote_memory(self, memory_id: str, handler: Any) -> HandlerResult:
        """Promote a memory entry to a new tier: POST /api/v1/memory/{id}/promote.

        Expects JSON body: {"target_tier": str}.
        Returns {"success": bool, "previous_tier": str | None}.
        """
        if not CONTINUUM_AVAILABLE:
            return error_response("Continuum memory system not available", 503)

        continuum = self.ctx.get("continuum_memory")
        if not continuum:
            return error_response("Continuum memory not initialized", 503)

        body = self.read_json_body(handler) or {}
        target_tier_name = body.get("target_tier")
        if not target_tier_name:
            return error_response("Missing required field: target_tier", 400)

        target_tier = self._resolve_tier(str(target_tier_name))
        if target_tier is None:
            return error_response(f"Invalid tier: {target_tier_name}", 400)

        # Capture the current tier before promotion for the response.
        previous_tier: str | None = None
        try:
            existing = continuum.get(memory_id)
        except (RuntimeError, ValueError, TypeError, OSError, AttributeError):
            existing = None
        if existing is not None:
            existing_tier = getattr(existing, "tier", None)
            if existing_tier is not None and hasattr(existing_tier, "name"):
                previous_tier = existing_tier.name.lower()

        try:
            promoted = continuum.promote_entry(memory_id, target_tier)
        except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
            logger.warning("Memory promote failed: %s", e)
            return error_response("Failed to promote memory entry", 500)

        if not promoted:
            return json_response(
                {
                    "success": False,
                    "previous_tier": previous_tier,
                    "error": "Memory entry not found",
                }
            )

        return json_response({"success": True, "previous_tier": previous_tier})

    @handle_errors("memory deletion")
    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route DELETE memory requests to appropriate methods with auth."""
        self._auth_context = getattr(handler, "_auth_context", None)
        path = self._normalize_path(path)
        from aragora.billing.jwt_auth import extract_user_from_request

        from ..utils.rate_limit import RateLimiter, get_client_ip

        if path.startswith("/api/v1/memory/continuum/"):
            # Require authentication for state mutation
            user_store = self._get_user_store()
            auth_ctx = extract_user_from_request(handler, user_store)
            if not auth_ctx.is_authenticated:
                return error_response("Authentication required", 401)

            # Rate limit: 10 deletes per minute per IP
            if not hasattr(self, "_delete_limiter"):
                self._delete_limiter = RateLimiter(requests_per_minute=10)
            client_ip = get_client_ip(handler)
            if not self._delete_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)

            # Extract memory_id from /api/v1/memory/continuum/{id}
            # After split("/") = ["", "api", "v1", "memory", "continuum", "{id}"]
            # memory_id is at index 5
            memory_id, err = self.extract_path_param(path, 5, "memory_id")
            if err:
                return err
            return self._delete_memory(memory_id)
        return None

    # =========================================================================
    # Utility Methods (shared by mixins)
    # =========================================================================

    @staticmethod
    def _parse_bool_param(params: dict, name: str, default: bool = False) -> bool:
        """Parse a boolean parameter from query params."""
        raw = get_bounded_string_param(params, name, "", max_length=10)
        if not raw:
            return default
        return raw.strip().lower() in ("1", "true", "yes", "y", "on")

    def _parse_tiers_param(self, params: dict, name: str = "tier") -> list[MemoryTier]:
        """Parse tiers parameter from query params."""
        tier_param = get_bounded_string_param(params, name, "", max_length=100)
        tiers: list[MemoryTier] = []
        if tier_param:
            for tier_name in tier_param.split(","):
                tier_name = tier_name.strip()
                if not tier_name:
                    continue
                try:
                    tiers.append(MemoryTier[tier_name.upper()])
                except KeyError:
                    continue
        return tiers or list(MemoryTier)

    def _format_entry_summary(
        self,
        entry: Any,
        *,
        preview_chars: int = 220,
        include_metadata: bool = False,
        include_content: bool = False,
    ) -> dict[str, Any]:
        """Format a memory entry as a summary dict."""

        def _get(attr: str, default: Any = None) -> Any:
            if isinstance(entry, dict):
                return entry.get(attr, default)
            return getattr(entry, attr, default)

        content = _get("content", "") or ""
        preview = content[:preview_chars].rstrip()
        if len(content) > preview_chars:
            preview = f"{preview}..."

        tier_value = _get("tier")
        tier_name = None
        if isinstance(tier_value, MemoryTier):
            tier_name = tier_value.name.lower()
        elif hasattr(tier_value, "name"):
            tier_name = str(getattr(tier_value, "name")).lower()
        elif tier_value is not None:
            tier_name = str(tier_value).lower()

        def _to_float(value: Any) -> float | None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        importance = _to_float(_get("importance"))
        surprise = _to_float(_get("surprise_score", _get("surprise")))

        created_at = _get("created_at")
        updated_at = _get("updated_at")

        result: dict[str, Any] = {
            "id": _get("id") or _get("memory_id"),
            "tier": tier_name,
            "preview": preview,
            "importance": round(importance, 3) if importance is not None else None,
            "surprise_score": round(surprise, 3) if surprise is not None else None,
            "created_at": str(created_at) if created_at is not None else None,
            "updated_at": str(updated_at) if updated_at is not None else None,
            "token_estimate": self._estimate_tokens(content),
        }

        red_line = _get("red_line", None)
        if red_line is not None:
            result["red_line"] = bool(red_line)
            red_line_reason = _get("red_line_reason", "")
            if red_line_reason:
                result["red_line_reason"] = red_line_reason

        if include_content:
            result["content"] = content
        if include_metadata:
            result["metadata"] = _get("metadata", {}) or {}

        return result

    def _format_entry_full(self, entry: Any) -> dict[str, Any]:
        """Format a memory entry with full content."""
        result = self._format_entry_summary(
            entry,
            preview_chars=600,
            include_metadata=True,
            include_content=True,
        )
        result["token_estimate"] = self._estimate_tokens(result.get("content", ""))
        return result

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate token count for text."""
        if not text:
            return 0
        return max(1, int(math.ceil(len(text) / 4)))

    # =========================================================================
    # Unified Memory Gateway Endpoints
    # =========================================================================

    def _get_unified_handler(self) -> Any:
        """Get or create UnifiedMemoryHandler."""
        if not hasattr(self, "_unified_handler"):
            unified: Any = None
            try:
                from .unified_handler import UnifiedMemoryHandler

                gateway = getattr(self, "_memory_gateway", None)
                unified = UnifiedMemoryHandler(gateway=gateway)
            except ImportError:
                unified = None
            self._unified_handler = unified
        return self._unified_handler

    def _unified_search(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        """Handle POST /api/v1/memory/unified/search."""
        uh = self._get_unified_handler()
        if not uh:
            return error_response("Unified memory handler not available", 501)

        from aragora.utils.async_utils import run_async

        try:
            body = getattr(handler, "_request_body", None) or query_params
            result = run_async(uh.handle_search(body))
            return json_response(result)
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.warning("Unified search failed: %s", e)
            return error_response("Unified memory search failed", 500)

    def _get_unified_stats(self) -> HandlerResult:
        """Handle GET /api/v1/memory/unified/stats."""
        uh = self._get_unified_handler()
        if not uh:
            return error_response("Unified memory handler not available", 501)

        from aragora.utils.async_utils import run_async

        try:
            result = run_async(uh.handle_stats())
            return json_response(result)
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.warning("Unified stats failed: %s", e)
            return error_response("Unified memory stats retrieval failed", 500)
