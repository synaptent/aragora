"""
Gauntlet handler class combining all gauntlet functionality.

This module contains the main GauntletHandler class that combines:
- Runner methods (start, run async)
- Receipt methods (get, verify, auto-persist)
- Heatmap methods
- Results methods (list, compare, delete, status, personas, export)
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs

from aragora.observability.metrics import track_handler
from aragora.server.validation.entities import validate_gauntlet_id
from aragora.server.versioning.compat import strip_version_prefix

from ..base import BaseHandler, HandlerResult, error_response
from ..utils.rate_limit import rate_limit
from .heatmap import GauntletHeatmapMixin
from .receipts import GauntletReceiptsMixin
from .results import GauntletResultsMixin
from .runner import GauntletRunnerMixin
from .storage import set_gauntlet_broadcast_fn

logger = logging.getLogger(__name__)


class GauntletHandler(
    GauntletRunnerMixin,
    GauntletReceiptsMixin,
    GauntletHeatmapMixin,
    GauntletResultsMixin,
    BaseHandler,
):
    """Handler for gauntlet stress-testing endpoints.

    Supports both versioned (/api/v1/gauntlet/*) and legacy (/api/gauntlet/*) routes.
    Legacy routes return a Deprecation header and should be migrated to v1.
    """

    # API version for this handler
    API_VERSION = "v1"

    # Gauntlet API routes (both versioned and non-versioned)
    ROUTES = [
        "/api/gauntlet/run",
        "/api/gauntlet/personas",
        "/api/gauntlet/results",
        "/api/gauntlet/receipts",
        "/api/gauntlet/*/receipt/verify",
        "/api/gauntlet/*/receipt",
        "/api/gauntlet/*/heatmap",
        "/api/gauntlet/*/export",
        "/api/gauntlet/*/compare/*",
        "/api/gauntlet/*",
        "/api/v1/gauntlet/run",
        "/api/v1/gauntlet/personas",
        "/api/v1/gauntlet/results",
        "/api/v1/gauntlet/*/receipt/verify",
        "/api/v1/gauntlet/*/receipt",
        "/api/v1/gauntlet/*/heatmap",
        "/api/v1/gauntlet/*/export",
        "/api/v1/gauntlet/*/compare/*",
        "/api/v1/gauntlet/*",
        "/api/v1/gauntlet",
        "/api/v1/gauntlet/heatmaps",
        "/api/v1/gauntlet/receipts",
        "/api/v1/gauntlet/receipts/export/bundle",
        "/api/v1/receipts/recent-anchors",
        "/api/v1/receipts/*/anchor-status",
    ]

    # All gauntlet endpoints require authentication
    AUTH_REQUIRED_ENDPOINTS = [
        "/api/v1/gauntlet/run",
        "/api/v1/gauntlet/",
    ]

    def __init__(self, server_context: dict[str, Any]):
        super().__init__(server_context)
        emitter = server_context.get("stream_emitter")
        if emitter and hasattr(emitter, "emit"):
            set_gauntlet_broadcast_fn(emitter.emit)

        # Direct route mapping for exact path matches (normalized paths -> method -> handler)
        # These are routes without path parameters
        self._direct_routes: dict[tuple[str, str], str] = {
            ("/api/gauntlet/run", "POST"): "_start_gauntlet",
            ("/api/gauntlet/personas", "GET"): "_list_personas",
            ("/api/gauntlet/results", "GET"): "_list_results",
            ("/api/gauntlet/receipts", "GET"): "_list_receipts",
            ("/api/receipts/recent-anchors", "GET"): "_get_recent_anchors",
        }

    def _extract_and_validate_id(
        self, path: str, segment_index: int = -1
    ) -> tuple[str | None, HandlerResult | None]:
        """Extract ID from path and validate it.

        Args:
            path: The request path
            segment_index: Index of the segment containing the ID (default -1 for last segment)

        Returns:
            Tuple of (id, None) on success or (None, error_response) on failure.
        """
        parts = path.rstrip("/").split("/")
        if len(parts) <= abs(segment_index):
            return None, error_response("Invalid path", 400)

        gauntlet_id = parts[segment_index]
        if not gauntlet_id or gauntlet_id in ("run", "personas", "results"):
            return None, error_response("Invalid gauntlet ID", 400)

        is_valid, err = validate_gauntlet_id(gauntlet_id)
        if not is_valid:
            return None, error_response(err, 400)

        return gauntlet_id, None

    async def _handle_parameterized_route(
        self, path: str, method: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle routes with path parameters.

        This method handles routes that include dynamic segments like {gauntlet_id}.
        """
        # GET /api/receipts/{receipt_id}/anchor-status
        if (
            path.endswith("/anchor-status")
            and path.startswith("/api/receipts/")
            and method == "GET"
        ):
            parts = path.rstrip("/").split("/")
            # /api/receipts/{receipt_id}/anchor-status => ['', 'api', 'receipts', '{id}', 'anchor-status']
            if len(parts) >= 5:
                receipt_id = parts[3]
                return self._get_receipt_anchor_status(receipt_id, query_params)

        # POST /api/gauntlet/{id}/receipt/verify
        if path.endswith("/receipt/verify") and method == "POST":
            gauntlet_id, err = self._extract_and_validate_id(path, -3)
            if err:
                return err
            return await self._verify_receipt(gauntlet_id, handler)

        # GET /api/gauntlet/{id}/receipt
        if path.endswith("/receipt") and method == "GET":
            gauntlet_id, err = self._extract_and_validate_id(path, -2)
            if err:
                return err
            return await self._get_receipt(gauntlet_id, query_params)

        # GET /api/gauntlet/{id}/heatmap
        if path.endswith("/heatmap") and method == "GET":
            gauntlet_id, err = self._extract_and_validate_id(path, -2)
            if err:
                return err
            return await self._get_heatmap(gauntlet_id, query_params)

        # GET /api/gauntlet/{id}/export
        if path.endswith("/export") and method == "GET":
            gauntlet_id, err = self._extract_and_validate_id(path, -2)
            if err:
                return err
            return await self._export_report(gauntlet_id, query_params, handler)

        # GET /api/gauntlet/{id}/compare/{id2}
        if "/compare/" in path and method == "GET":
            parts = path.rstrip("/").split("/")
            if len(parts) >= 5:
                gauntlet_id, err = self._extract_and_validate_id(path, -3)
                if err:
                    return err
                compare_id = parts[-1]
                is_valid, err_msg = validate_gauntlet_id(compare_id)
                if not is_valid:
                    return error_response(f"Invalid compare ID: {err_msg}", 400)
                return self._compare_results(gauntlet_id, compare_id, query_params)

        # DELETE /api/gauntlet/{id}
        if method == "DELETE" and path.startswith("/api/gauntlet/"):
            gauntlet_id, err = self._extract_and_validate_id(path)
            if err:
                return err
            return self._delete_result(gauntlet_id, query_params)

        # GET /api/gauntlet/{id} - catch-all for status
        if method == "GET" and path.startswith("/api/gauntlet/"):
            gauntlet_id, err = self._extract_and_validate_id(path)
            if err:
                return err
            return await self._get_status(gauntlet_id)

        return None

    def _is_legacy_route(self, path: str) -> bool:
        """Check if this is a legacy (non-versioned) route."""
        return path.startswith("/api/gauntlet/") and not path.startswith("/api/v1/")

    def _normalize_path(self, path: str) -> str:
        """Normalize path by removing version prefix for routing logic.

        Converts /api/v1/gauntlet/* to /api/gauntlet/* for consistent routing.
        """
        normalized = strip_version_prefix(path)
        # Convert to /api/gauntlet/* format for internal routing
        if normalized.startswith("/api/gauntlet"):
            return normalized.replace("/api/gauntlet", "/api/gauntlet")
        return normalized

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the request.

        Supports both versioned (/api/v1/gauntlet/*) and legacy (/api/gauntlet/*) routes.
        Also handles /api/v1/receipts/* anchor-related routes.
        """
        # Normalize path for matching
        normalized = self._normalize_path(path)

        # Receipt anchor routes (normalized: /api/receipts/...)
        if normalized.startswith("/api/receipts/") and method == "GET":
            return True

        # When called without method (e.g., from route index), just check path prefix
        if method == "GET" and normalized.startswith("/api/gauntlet/"):
            return True
        if normalized == "/api/gauntlet/run" and method == "POST":
            return True
        if normalized == "/api/gauntlet/personas" and method == "GET":
            return True
        if normalized == "/api/gauntlet/results" and method == "GET":
            return True
        if normalized == "/api/gauntlet/receipts" and method == "GET":
            return True
        if normalized.startswith("/api/gauntlet/") and method == "GET":
            return True
        if normalized.startswith("/api/gauntlet/") and method == "DELETE":
            return True
        return False

    def _add_version_headers(self, result: HandlerResult, original_path: str) -> HandlerResult:
        """Add API version headers and deprecation warning for legacy routes."""
        if result is None:
            return result

        # Initialize headers if needed
        if result.headers is None:
            result.headers = {}

        # Add API version header
        result.headers["X-API-Version"] = self.API_VERSION

        # Add deprecation header for legacy routes
        if self._is_legacy_route(original_path):
            result.headers["Deprecation"] = "true"
            result.headers["Sunset"] = "2026-06-01"  # 6 months notice
            result.headers["Link"] = f'</api/v1{original_path[4:]}>; rel="successor-version"'
            logger.debug("Legacy route accessed: %s", original_path)

        return result

    @track_handler("gauntlet/main", method="GET")
    @rate_limit(requests_per_minute=10)
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route request to appropriate handler.

        Supports both versioned (/api/v1/gauntlet/*) and legacy (/api/gauntlet/*) routes.
        Uses routing dictionary for direct routes and pattern matching for parameterized routes.
        """
        original_path = path
        # Determine HTTP method from handler
        method: str = getattr(handler, "command", "GET") if handler else "GET"

        # Handle backwards-compatible calling convention where query_params may be a string (method)
        # This happens when called as handle(path, "GET", handler) instead of handle(path, {}, handler)
        if isinstance(query_params, str):
            # query_params is actually a method string, extract real query_params from handler.path
            query_params = {}
            if handler and hasattr(handler, "path") and "?" in handler.path:
                query_str = handler.path.split("?", 1)[1]
                parsed = parse_qs(query_str)
                # Flatten single-value lists for convenience
                query_params = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

        # Auth and permission checks
        user, err = self.require_auth_or_error(handler)
        if err:
            return err
        perm_key = "gauntlet:write" if method == "POST" else "gauntlet:read"
        _, perm_err = self.require_permission_or_error(handler, perm_key)
        if perm_err:
            return perm_err

        # Normalize path for routing (remove version prefix)
        path = self._normalize_path(path)

        result: HandlerResult | None = None

        # Try direct route match first (exact path matches)
        route_key = (path, method)
        if route_key in self._direct_routes:
            handler_name = self._direct_routes[route_key]
            handler_method = getattr(self, handler_name)
            if handler_name == "_start_gauntlet":
                result = await handler_method(handler)
            elif handler_name in ("_list_results", "_list_receipts", "_get_recent_anchors"):
                result = handler_method(query_params)
            else:
                result = handler_method()
        else:
            # Try parameterized route matching
            result = await self._handle_parameterized_route(path, method, query_params, handler)

        # Add version headers to result
        if result is not None:
            result = self._add_version_headers(result, original_path)

        return result
