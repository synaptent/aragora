"""
Debate-related endpoint handlers.

This is the main DebatesHandler class that composes functionality from specialized mixins:
- AnalysisOperationsMixin: Meta-critique and argument graph analysis
- BatchOperationsMixin: Batch debate submission and processing
- CreateOperationsMixin: Debate creation and cancellation
- CrudOperationsMixin: List, get, update, delete debates
- DiagnosticsMixin: Debate diagnostics for self-service debugging
- EvidenceOperationsMixin: Citations, evidence, verification reports
- ExportOperationsMixin: Export in various formats
- ForkOperationsMixin: Counterfactual forks and follow-ups
- RoutingMixin: Route dispatch and authentication
- SearchOperationsMixin: Cross-debate search

Endpoints:
- GET /api/debates - List all debates
- GET /api/debates/{slug} - Get debate by slug
- GET /api/debates/slug/{slug} - Get debate by slug (alternative)
- GET /api/debates/{id}/export/{format} - Export debate
- GET /api/debates/{id}/impasse - Detect debate impasse
- GET /api/debates/{id}/convergence - Get convergence status
- GET /api/debates/{id}/citations - Get evidence citations for debate
- GET /api/debates/{id}/evidence - Get comprehensive evidence trail
- GET /api/debate/{id}/meta-critique - Get meta-level debate analysis
- GET /api/debate/{id}/graph/stats - Get argument graph statistics
- GET /api/debates/{id}/rhetorical - Get rhetorical pattern observations
- GET /api/debates/{id}/trickster - Get trickster hollow consensus status
- GET /api/debates/{id}/positions - Get per-agent position evolution
- GET /api/debates/{id}/diagnostics - Get diagnostic report for debugging
- POST /api/debates/{id}/fork - Fork debate at a branch point
- PATCH /api/debates/{id} - Update debate metadata (title, tags, status)
- DELETE /api/debates/{id} - Permanently delete a debate (cascades to critiques)
- GET /api/search - Cross-debate search by query
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.debate_controller_mixin import DebateControllerMixin
from aragora.server.debate_utils import _active_debates  # noqa: F401
from aragora.server.http_utils import run_async
from aragora.server.validation import validate_debate_id
from aragora.server.validation.schema import validate_against_schema  # noqa: F401

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_int_param,
    handle_errors,
)

# Import all mixins
from .analysis import AnalysisOperationsMixin
from .batch import BatchOperationsMixin
from .costs import CostsMixin
from .create import CreateOperationsMixin
from .crud import CrudOperationsMixin
from .diagnostics import DiagnosticsMixin
from .evidence import EvidenceOperationsMixin
from .export import ExportOperationsMixin
from .fork import ForkOperationsMixin
from .implementation import ImplementationOperationsMixin
from .routing import (
    ALLOWED_EXPORT_FORMATS,
    ALLOWED_EXPORT_TABLES,
    ARTIFACT_ENDPOINTS,
    AUTH_REQUIRED_ENDPOINTS,
    ROUTES,
    SUFFIX_ROUTES,
    RoutingMixin,
)
from .search import SearchOperationsMixin


logger = logging.getLogger(__name__)


class DebatesHandler(
    AnalysisOperationsMixin,
    BatchOperationsMixin,
    CostsMixin,
    CreateOperationsMixin,
    CrudOperationsMixin,
    DebateControllerMixin,
    DiagnosticsMixin,
    EvidenceOperationsMixin,
    ExportOperationsMixin,
    ForkOperationsMixin,
    ImplementationOperationsMixin,
    RoutingMixin,
    SearchOperationsMixin,
    BaseHandler,
):
    """Handler for debate-related endpoints.

    Composes functionality from specialized mixins for better modularity.
    Each mixin provides a specific category of operations:
    - Analysis: Meta-critique and graph analysis
    - Batch: Batch submission and processing
    - Create: Debate creation and cancellation
    - CRUD: List, get, update, delete
    - Diagnostics: Self-service debugging reports
    - Evidence: Citations and verification reports
    - Export: Export in various formats
    - Fork: Counterfactual forks and follow-ups
    - Routing: Route dispatch and authentication
    - Search: Cross-debate search
    """

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        if server_context is not None:
            self.ctx = server_context
        else:
            self.ctx = ctx or {}  # dict is runtime-compatible with ServerContext

    # Route patterns this handler manages (from routing module)
    ROUTES = ROUTES
    # Spec-only verb declarations for the batch-export root, which serves
    # both verbs through _handle_batch_export inside generic handle()
    # (POST starts an export, GET lists jobs); read by openapi_impl, not
    # used for request routing.
    _ROUTE_MAP: dict[str, Any] = {
        "POST /api/v1/debates/export/batch": None,
        "GET /api/v1/debates/export/batch": None,
    }
    AUTH_REQUIRED_ENDPOINTS = AUTH_REQUIRED_ENDPOINTS
    ALLOWED_EXPORT_FORMATS = ALLOWED_EXPORT_FORMATS
    ALLOWED_EXPORT_TABLES = ALLOWED_EXPORT_TABLES
    ARTIFACT_ENDPOINTS = ARTIFACT_ENDPOINTS
    SUFFIX_ROUTES = SUFFIX_ROUTES

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route debate requests to appropriate handler methods.

        Note: Paths may be normalized (version stripped) by handler_registry,
        so we normalize to unversioned for consistent route matching.
        """
        # Normalize to unversioned for consistent checking
        normalized = path.replace("/api/v1/", "/api/").replace("/api/v2/", "/api/")

        # Check authentication for protected endpoints
        if self._requires_auth(path):
            auth_error = self._check_auth(handler)
            if auth_error:
                return auth_error

        # Search endpoint
        if normalized in ("/api/search", "/api/debates/search"):
            query = query_params.get("q", query_params.get("query", ""))
            if isinstance(query, list):
                query = query[0] if query else ""
            limit = min(get_int_param(query_params, "limit", 20), 100)
            offset = get_int_param(query_params, "offset", 0)
            # Get authenticated user for org-scoped search
            user = self.get_current_user(handler)
            org_id = user.org_id if user else None
            return self._search_debates(query, limit, offset, org_id)

        # Cost estimation endpoint (no auth required - public preview)
        if normalized == "/api/debates/estimate-cost":
            from .cost_estimation import handle_estimate_cost

            num_agents = get_int_param(query_params, "num_agents", 3)
            num_rounds = get_int_param(query_params, "num_rounds", 9)
            model_types_str = query_params.get("model_types", "")
            if isinstance(model_types_str, list):
                model_types_str = model_types_str[0] if model_types_str else ""
            return handle_estimate_cost(num_agents, num_rounds, model_types_str)

        # Queue status endpoint
        if normalized == "/api/debates/queue/status":
            return self._get_queue_status()

        # Batch status endpoint (GET /api/debates/batch/{id}/status)
        if normalized.startswith("/api/debates/batch/") and normalized.endswith("/status"):
            parts = normalized.split("/")
            if len(parts) >= 5:
                batch_id = parts[3]  # Index 3 for unversioned paths
                return self._get_batch_status(batch_id)

        # List batches (GET /api/debates/batch)
        if normalized in ("/api/debates/batch", "/api/debates/batch/"):
            limit = min(get_int_param(query_params, "limit", 50), 100)
            status_filter = query_params.get("status")
            return self._list_batches(limit, status_filter)

        # Batch export endpoints
        if normalized.startswith("/api/debates/export/batch"):
            return self._handle_batch_export(normalized, query_params, handler)

        # Active (in-progress) debates
        if normalized == "/api/debates/active":
            return self._get_active_debates()

        # Exact path matches - list debates
        if normalized in ("/api/debates", "/api/debates/"):
            limit = min(get_int_param(query_params, "limit", 20), 100)
            offset = max(get_int_param(query_params, "offset", 0), 0)
            # Get authenticated user for org-scoped results
            user = self.get_current_user(handler)
            org_id = user.org_id if user else None
            return self._list_debates(limit, org_id, offset)

        if normalized.startswith("/api/debates/slug/"):
            slug = normalized.split("/")[-1]
            return self._get_debate_by_slug(handler, slug)

        # Dispatch suffix-based routes (impasse, convergence, citations, messages, etc.)
        result = self._dispatch_suffix_route(normalized, query_params, handler)
        if result:
            return result

        # Decision integrity package (POST /api/debates/{id}/decision-integrity)
        if normalized.endswith("/decision-integrity"):
            # Enforce POST
            if handler is not None and getattr(handler, "command", "POST") != "POST":
                return error_response("Method not allowed", 405)
            debate_id, err = self._extract_debate_id(normalized)
            if err:
                return error_response(err, 400)
            if not debate_id:
                return error_response("Invalid debate id", 400)
            return self._create_decision_integrity(handler, debate_id)

        # Export route (special handling for format/table validation)
        # URL: /api/debates/{id}/export/{format}
        # Parts: ['', 'api', 'debates', '{id}', 'export', '{format}']
        if "/export/" in normalized:
            parts = normalized.split("/")
            if len(parts) >= 6:
                debate_id = parts[3]  # Index 3 for unversioned paths
                # Validate debate ID for export
                is_valid, err = validate_debate_id(debate_id)
                if not is_valid:
                    return error_response(err, 400)
                export_format = parts[5]  # Index 5 for unversioned paths
                # Validate export format
                if export_format not in self.ALLOWED_EXPORT_FORMATS:
                    return error_response(
                        f"Invalid format '{export_format}'. Allowed: {sorted(self.ALLOWED_EXPORT_FORMATS)}",
                        400,
                    )
                table = query_params.get("table", "summary")
                # Validate table parameter
                if table not in self.ALLOWED_EXPORT_TABLES:
                    return error_response(
                        f"Invalid table '{table}'. Allowed: {sorted(self.ALLOWED_EXPORT_TABLES)}",
                        400,
                    )
                return self._export_debate(handler, debate_id, export_format, table)

        # Default: treat as slug lookup
        if normalized.startswith("/api/debates/"):
            slug = normalized.split("/")[-1]
            if slug and slug not in ("impasse", "convergence"):
                return self._get_debate_by_slug(handler, slug)

        return None

    @handle_errors("batch export")
    def _handle_batch_export(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route batch export requests to appropriate methods."""
        # Normalize to unversioned for consistent checking
        normalized = path.replace("/api/v1/", "/api/").replace("/api/v2/", "/api/")

        # The root path serves two verbs: POST starts a batch export, GET
        # lists export jobs. The POST branch previously matched
        # unconditionally, shadowing the GET list (every GET returned 400).
        if normalized in ("/api/debates/export/batch", "/api/debates/export/batch/"):
            method = str(getattr(handler, "command", "GET") or "GET").upper()
            if method == "POST":
                body = self.read_json_body(handler)
                if not body:
                    return error_response("Invalid or missing JSON body", 400)
                debate_ids = body.get("debate_ids", [])
                format = body.get("format", "json")
                return self._start_batch_export(handler, debate_ids, format)  # Mixin method

            # GET /api/debates/export/batch - list export jobs
            limit = min(get_int_param(query_params, "limit", 50), 100)
            return self._list_batch_exports(limit)  # Mixin method

        # Extract job ID from normalized path
        parts = normalized.split("/")
        if len(parts) < 5:
            return error_response("Invalid batch export path", 400)

        job_id = parts[4]

        # GET /api/debates/export/batch/{job_id}/status
        if path.endswith("/status"):
            return self._get_batch_export_status(job_id)  # Mixin method

        # GET /api/debates/export/batch/{job_id}/results
        if path.endswith("/results"):
            return self._get_batch_export_results(job_id)  # Mixin method

        # GET /api/debates/export/batch/{job_id}/stream - SSE stream
        if path.endswith("/stream"):

            async def stream() -> AsyncIterator[Any]:
                async for chunk in self._stream_batch_export_progress(job_id):  # Mixin method
                    yield chunk

            return HandlerResult(
                status_code=200,
                content_type="text/event-stream",
                body=run_async(
                    stream()  # type: ignore[arg-type]
                ),  # Async generator used as SSE stream body  # type: ignore[misc]
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

        return error_response(f"Unknown batch export endpoint: {path}", 404)

    @handle_errors("debates creation")
    @require_permission("debates:create")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route POST requests to appropriate methods."""
        # One-click debate launcher
        if path in ("/api/v1/debate-this", "/api/debate-this"):
            return self._debate_this(handler)

        # Create debate endpoint - both legacy and RESTful
        # POST /api/debates (canonical) or POST /api/debate (legacy, deprecated)
        # Note: path is normalized (version stripped), so check both versioned and unversioned
        if path in ("/api/v1/debate", "/api/v1/debates", "/api/debate", "/api/debates"):
            result = self._create_debate(handler)

            # Add deprecation headers for legacy endpoint
            if path in ("/api/v1/debate", "/api/debate") and result:
                # RFC 8594 Sunset header - 6 months from now
                result.headers = result.headers or {}
                result.headers["Deprecation"] = "true"
                result.headers["Sunset"] = "Sat, 01 Aug 2026 00:00:00 GMT"
                result.headers["Link"] = '</api/debates>; rel="successor-version"'
                logger.warning("Legacy endpoint /api/debate used. Use /api/debates instead.")
            return result

        # Batch submission endpoint
        if path in (
            "/api/v1/debates/batch",
            "/api/v1/debates/batch/",
            "/api/debates/batch",
            "/api/debates/batch/",
        ):
            return self._submit_batch(handler)

        if path.endswith("/fork"):
            debate_id, err = self._extract_debate_id(path)
            if err:
                return error_response(err, 400)
            if debate_id:
                return self._fork_debate(handler, debate_id)

        if path.endswith("/verify"):
            debate_id, err = self._extract_debate_id(path)
            if err:
                return error_response(err, 400)
            if debate_id:
                return self._verify_outcome(handler, debate_id)

        if path.endswith("/followup"):
            debate_id, err = self._extract_debate_id(path)
            if err:
                return error_response(err, 400)
            if debate_id:
                return self._create_followup_debate(handler, debate_id)

        if path.endswith("/cancel"):
            debate_id, err = self._extract_debate_id(path)
            if err:
                return error_response(err, 400)
            if debate_id:
                return self._cancel_debate(handler, debate_id)

        return None

    @handle_errors("debates modification")
    @require_permission("debates:update")
    def handle_patch(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route PATCH requests to appropriate methods.

        Note: the registry dispatches the version-stripped path
        (/api/debates/{id}) when the handler claims the normalized form, so
        match on the normalized path. Matching only /api/v1/... silently
        dropped runtime PATCH requests into the generic handle() slug lookup.
        """
        # Handle /api/debates/{id} pattern for updates
        normalized = path.replace("/api/v1/", "/api/").replace("/api/v2/", "/api/")
        if normalized.startswith("/api/debates/") and normalized.count("/") == 3:
            debate_id, err = self._extract_debate_id(normalized)
            if err:
                return error_response(err, 400)
            if debate_id:
                return self._patch_debate(handler, debate_id)
        return None

    @handle_errors("debates deletion")
    @require_permission("debates:delete")
    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route DELETE requests to appropriate methods.

        Note: matches the version-stripped path for the same reason as
        handle_patch above.
        """
        # Handle DELETE /api/debates/{id}
        normalized = path.replace("/api/v1/", "/api/").replace("/api/v2/", "/api/")
        if normalized.startswith("/api/debates/") and normalized.count("/") == 3:
            debate_id, err = self._extract_debate_id(normalized)
            if err:
                return error_response(err, 400)
            if debate_id:
                return self._delete_debate(handler, debate_id)
        return None


# Backward compatibility alias
DebateHandler = DebatesHandler

__all__ = ["DebatesHandler", "DebateHandler"]
