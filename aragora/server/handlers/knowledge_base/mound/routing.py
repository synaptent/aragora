"""
Routing mixin for Knowledge Mound handler.

Provides a dispatch table pattern to reduce cyclomatic complexity of the main
handle() method. Routes are organized by endpoint category for maintainability.

Each route entry maps a path pattern to a handler method and HTTP method(s).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from collections.abc import Callable

from aragora.server.http_utils import run_async as _run_async
from aragora.server.validation.query_params import safe_query_float, safe_query_int

from ...base import HandlerResult, error_response
from ...utils.rate_limit import get_client_ip
from ...utils.tenant_validation import validate_workspace_access_sync

if TYPE_CHECKING:
    from aragora.knowledge.mound import KnowledgeMound

logger = logging.getLogger(__name__)


@dataclass
class RouteEntry:
    """A route entry mapping a path pattern to a handler."""

    pattern: str  # Exact path or regex pattern
    handler: str  # Method name to call
    methods: tuple[str, ...]  # Allowed HTTP methods
    is_regex: bool = False  # Whether pattern is a regex


class RoutingProtocol(Protocol):
    """Protocol for handlers that use RoutingMixin."""

    def _get_mound(self) -> KnowledgeMound | None: ...

    def get_current_user(self, handler: Any) -> Any: ...


def _parse_json_body(handler: Any) -> dict[str, Any]:
    """Parse JSON body from request handler, returning empty dict on failure."""
    try:
        body = handler.request.body.decode("utf-8") if handler.request.body else "{}"
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError) as e:
        logger.warning("Failed to parse request body: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Handler call-signature registry
# ---------------------------------------------------------------------------
# Maps handler method names to their expected argument pattern:
#   "none" = ()
#   "q"    = (query_params)
#   "h"    = (handler)          [default if not listed]
#   "qh"   = (query_params, handler)
#   "pqh"  = (path, query_params, handler)
#   "id"   = (entity_id)
#   "id_q" = (entity_id, query_params)
#   "id_h" = (entity_id, handler)
#   "id_qh"= (entity_id, query_params, handler)
_HANDLER_SIGNATURES: dict[str, str] = {
    # query_params only
    "_handle_mound_stats": "q",
    "_handle_list_nodes": "q",
    "_handle_get_culture": "q",
    "_handle_get_stale": "q",
    "_handle_export_d3": "q",
    "_handle_export_graphml": "q",
    "_handle_get_system_facts": "q",
    "_handle_get_duplicate_clusters": "q",
    "_handle_get_dedup_report": "q",
    "_handle_get_prunable_items": "q",
    "_handle_get_prune_history": "q",
    "_handle_list_contradictions": "q",
    "_handle_query_audit": "q",
    "_handle_analyze_coverage": "q",
    "_handle_analyze_usage": "q",
    "_handle_get_quality_trend": "q",
    "_handle_get_confidence_history": "q",
    "_handle_curation_status": "q",
    "_handle_curation_history": "q",
    "_handle_quality_scores": "q",
    "_handle_tier_distribution": "q",
    # query_params + handler
    "_handle_shared_with_me": "qh",
    "_handle_my_shares": "qh",
    "_handle_query_global": "qh",
    "_handle_list_regions": "qh",
    "_handle_get_federation_status": "qh",
    # no args
    "_handle_get_system_workspace_id": "none",
    "_handle_contradiction_stats": "none",
    "_handle_governance_stats": "none",
    "_handle_analytics_stats": "none",
    "_handle_extraction_stats": "none",
    "_handle_decay_stats": "none",
    # path + query_params + handler (routing dispatchers)
    "_route_nodes": "pqh",
    "_route_share": "pqh",
    "_route_global": "pqh",
    "_route_federation_regions": "pqh",
    "_route_governance_roles": "pqh",
    "_route_curation_policy": "pqh",
    # entity_id only
    "_handle_get_node": "id",
    # entity_id + query_params
    "_handle_get_node_relationships": "id_q",
    "_handle_graph_lineage": "id_q",
    "_handle_graph_related": "id_q",
    "_handle_graph_traversal": "id_q",
    "_handle_get_visibility": "id_q",
    "_handle_list_access_grants": "id_q",
    "_handle_get_user_permissions": "id_q",
    "_handle_get_user_activity": "id_q",
    # entity_id + handler
    "_handle_revalidate_node": "id_h",
    "_handle_set_visibility": "id_h",
    "_handle_grant_access": "id_h",
    "_handle_revoke_access": "id_h",
    "_handle_unregister_region": "id_h",
    "_handle_resolve_contradiction": "id_h",
    # entity_id + query_params + handler (routing dispatchers with ID)
    "_route_node_visibility": "id_qh",
    "_route_node_access": "id_qh",
}


class RoutingMixin:
    """Mixin providing URL routing via dispatch table pattern."""

    def _build_route_table(self) -> dict[str, list[RouteEntry]]:
        """
        Build the route dispatch table.

        Routes are grouped by category for organization.
        Returns a dict mapping exact paths to handlers, plus a list of regex routes.
        """
        return {
            # Static routes - exact path match
            "static": [
                # Query
                RouteEntry(
                    "/api/v1/knowledge/mound/query",
                    "_handle_mound_query",
                    ("POST",),
                ),
                # Nodes
                RouteEntry(
                    "/api/v1/knowledge/mound/nodes",
                    "_route_nodes",
                    ("GET", "POST"),
                ),
                # Relationships
                RouteEntry(
                    "/api/v1/knowledge/mound/relationships",
                    "_handle_create_relationship",
                    ("POST",),
                ),
                # Stats
                RouteEntry(
                    "/api/v1/knowledge/mound/stats",
                    "_handle_mound_stats",
                    ("GET",),
                ),
                # Index
                RouteEntry(
                    "/api/v1/knowledge/mound/index/repository",
                    "_handle_index_repository",
                    ("POST",),
                ),
                # Culture
                RouteEntry(
                    "/api/v1/knowledge/mound/culture",
                    "_handle_get_culture",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/culture/documents",
                    "_handle_add_culture_document",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/culture/promote",
                    "_handle_promote_to_culture",
                    ("POST",),
                ),
                # Staleness
                RouteEntry(
                    "/api/v1/knowledge/mound/stale",
                    "_handle_get_stale",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/schedule-revalidation",
                    "_handle_schedule_revalidation",
                    ("POST",),
                ),
                # Sync
                RouteEntry(
                    "/api/v1/knowledge/mound/sync/continuum",
                    "_handle_sync_continuum",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/sync/consensus",
                    "_handle_sync_consensus",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/sync/facts",
                    "_handle_sync_facts",
                    ("POST",),
                ),
                # Export
                RouteEntry(
                    "/api/v1/knowledge/mound/export/d3",
                    "_handle_export_d3",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/export/graphml",
                    "_handle_export_graphml",
                    ("GET",),
                ),
                # Sharing
                RouteEntry(
                    "/api/v1/knowledge/mound/share",
                    "_route_share",
                    ("POST", "DELETE", "PATCH"),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/shared-with-me",
                    "_handle_shared_with_me",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/my-shares",
                    "_handle_my_shares",
                    ("GET",),
                ),
                # Global knowledge
                RouteEntry(
                    "/api/v1/knowledge/mound/global",
                    "_route_global",
                    ("GET", "POST"),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/global/promote",
                    "_handle_promote_to_global",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/global/facts",
                    "_handle_get_system_facts",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/global/workspace-id",
                    "_handle_get_system_workspace_id",
                    ("GET",),
                ),
                # Federation
                RouteEntry(
                    "/api/v1/knowledge/mound/federation/regions",
                    "_route_federation_regions",
                    ("GET", "POST"),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/federation/sync/push",
                    "_handle_sync_to_region",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/federation/sync/pull",
                    "_handle_pull_from_region",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/federation/sync/all",
                    "_handle_sync_all_regions",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/federation/status",
                    "_handle_get_federation_status",
                    ("GET",),
                ),
                # Dedup
                RouteEntry(
                    "/api/v1/knowledge/mound/dedup/clusters",
                    "_handle_get_duplicate_clusters",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/dedup/report",
                    "_handle_get_dedup_report",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/dedup/merge",
                    "_handle_merge_duplicate_cluster",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/dedup/auto-merge",
                    "_handle_auto_merge_exact_duplicates",
                    ("POST",),
                ),
                # Pruning
                RouteEntry(
                    "/api/v1/knowledge/mound/pruning/items",
                    "_handle_get_prunable_items",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/pruning/execute",
                    "_handle_execute_prune",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/pruning/auto",
                    "_handle_auto_prune",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/pruning/history",
                    "_handle_get_prune_history",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/pruning/restore",
                    "_handle_restore_pruned_item",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/pruning/decay",
                    "_handle_apply_confidence_decay",
                    ("POST",),
                ),
                # Dashboard
                RouteEntry(
                    "/api/v1/knowledge/mound/dashboard/health",
                    "_handle_dashboard_health",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/dashboard/metrics",
                    "_handle_dashboard_metrics",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/dashboard/metrics/reset",
                    "_handle_dashboard_metrics_reset",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/dashboard/adapters",
                    "_handle_dashboard_adapters",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/dashboard/queries",
                    "_handle_dashboard_queries",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/dashboard/batcher",
                    "_handle_dashboard_batcher_stats",
                    ("GET",),
                ),
                # Contradiction
                RouteEntry(
                    "/api/v1/knowledge/mound/contradictions/detect",
                    "_handle_detect_contradictions",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/contradictions",
                    "_handle_list_contradictions",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/contradictions/stats",
                    "_handle_contradiction_stats",
                    ("GET",),
                ),
                # Governance
                RouteEntry(
                    "/api/v1/knowledge/mound/governance/roles",
                    "_route_governance_roles",
                    ("GET", "POST"),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/governance/roles/assign",
                    "_handle_assign_role",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/governance/roles/revoke",
                    "_handle_revoke_role",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/governance/permissions/check",
                    "_handle_check_permission",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/governance/audit",
                    "_handle_query_audit",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/governance/stats",
                    "_handle_governance_stats",
                    ("GET",),
                ),
                # Analytics
                RouteEntry(
                    "/api/v1/knowledge/mound/analytics/coverage",
                    "_handle_analyze_coverage",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/analytics/usage",
                    "_handle_analyze_usage",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/analytics/usage/record",
                    "_handle_record_usage_event",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/analytics/quality/snapshot",
                    "_handle_capture_quality_snapshot",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/analytics/quality/trend",
                    "_handle_get_quality_trend",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/analytics/stats",
                    "_handle_analytics_stats",
                    ("GET",),
                ),
                # Extraction
                RouteEntry(
                    "/api/v1/knowledge/mound/extraction/debate",
                    "_handle_extract_from_debate",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/extraction/promote",
                    "_handle_promote_extracted",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/extraction/stats",
                    "_handle_extraction_stats",
                    ("GET",),
                ),
                # Confidence decay
                RouteEntry(
                    "/api/v1/knowledge/mound/confidence/decay",
                    "_handle_apply_confidence_decay_new",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/confidence/event",
                    "_handle_record_confidence_event",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/confidence/history",
                    "_handle_get_confidence_history",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/confidence/stats",
                    "_handle_decay_stats",
                    ("GET",),
                ),
                # Curation
                RouteEntry(
                    "/api/v1/knowledge/mound/curation/policy",
                    "_route_curation_policy",
                    ("GET", "POST", "PUT"),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/curation/status",
                    "_handle_curation_status",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/curation/run",
                    "_handle_run_curation",
                    ("POST",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/curation/history",
                    "_handle_curation_history",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/curation/scores",
                    "_handle_quality_scores",
                    ("GET",),
                ),
                RouteEntry(
                    "/api/v1/knowledge/mound/curation/tiers",
                    "_handle_tier_distribution",
                    ("GET",),
                ),
            ],
            # Dynamic routes - patterns with path parameters
            "dynamic": [
                # Nodes with ID
                RouteEntry(
                    r"^/api/v1/knowledge/mound/nodes/([^/]+)$",
                    "_handle_get_node",
                    ("GET",),
                    is_regex=True,
                ),
                RouteEntry(
                    r"^/api/v1/knowledge/mound/nodes/([^/]+)/relationships$",
                    "_handle_get_node_relationships",
                    ("GET",),
                    is_regex=True,
                ),
                RouteEntry(
                    r"^/api/v1/knowledge/mound/nodes/([^/]+)/visibility$",
                    "_route_node_visibility",
                    ("GET", "PUT"),
                    is_regex=True,
                ),
                RouteEntry(
                    r"^/api/v1/knowledge/mound/nodes/([^/]+)/access$",
                    "_route_node_access",
                    ("GET", "POST", "DELETE"),
                    is_regex=True,
                ),
                # Graph
                RouteEntry(
                    r"^/api/v1/knowledge/mound/graph/([^/]+)/lineage$",
                    "_handle_graph_lineage",
                    ("GET",),
                    is_regex=True,
                ),
                RouteEntry(
                    r"^/api/v1/knowledge/mound/graph/([^/]+)/related$",
                    "_handle_graph_related",
                    ("GET",),
                    is_regex=True,
                ),
                RouteEntry(
                    r"^/api/v1/knowledge/mound/graph/([^/]+)$",
                    "_handle_graph_traversal",
                    ("GET",),
                    is_regex=True,
                ),
                # Revalidate
                RouteEntry(
                    r"^/api/v1/knowledge/mound/revalidate/([^/]+)$",
                    "_handle_revalidate_node",
                    ("POST",),
                    is_regex=True,
                ),
                # Federation regions with ID
                RouteEntry(
                    r"^/api/v1/knowledge/mound/federation/regions/([^/]+)$",
                    "_handle_unregister_region",
                    ("DELETE",),
                    is_regex=True,
                ),
                # Contradiction resolve
                RouteEntry(
                    r"^/api/v1/knowledge/mound/contradictions/([^/]+)/resolve$",
                    "_handle_resolve_contradiction",
                    ("POST",),
                    is_regex=True,
                ),
                # Governance permissions for user
                RouteEntry(
                    r"^/api/v1/knowledge/mound/governance/permissions/([^/]+)$",
                    "_handle_get_user_permissions",
                    ("GET",),
                    is_regex=True,
                ),
                # Governance audit for user
                RouteEntry(
                    r"^/api/v1/knowledge/mound/governance/audit/user/([^/]+)$",
                    "_handle_get_user_activity",
                    ("GET",),
                    is_regex=True,
                ),
            ],
        }

    def routes(self) -> list[tuple[str, str, str]]:
        """Explicit ``(METHOD, path, handler_name)`` declarations for this handler.

        The OpenAPI generator treats ``routes()`` as per-path verb evidence
        (same protocol as ``SSOHandler.routes()``, see #9360): without it, the
        dispatch-table verbs below are invisible to spec generation and the
        read-suffix fallback documents POST-only mound routes as GET (#9396).
        Derived directly from ``_build_route_table()`` so the declaration
        cannot drift from dispatch truth. Dynamic regex patterns are converted
        to wildcard paths (``([^/]+)`` -> ``*``) for spec templating.
        """
        declared: list[tuple[str, str, str]] = []
        table = self._build_route_table()
        for entry in table["static"]:
            for method in entry.methods:
                declared.append((method, entry.pattern, entry.handler))
        for entry in table["dynamic"]:
            path = entry.pattern.lstrip("^").rstrip("$").replace("([^/]+)", "*")
            for method in entry.methods:
                declared.append((method, path, entry.handler))
        return declared

    def _dispatch_route(
        self,
        path: str,
        query_params: dict,
        handler: Any,
    ) -> HandlerResult | None:
        """
        Dispatch a request to the appropriate handler method.

        Returns None if no route matches.
        """
        method = getattr(handler, "command", "GET")
        route_table = self._build_route_table()

        # Check static routes first (O(1) lookup for exact matches)
        static_routes = {r.pattern: r for r in route_table["static"]}
        if path in static_routes:
            route = static_routes[path]
            if method in route.methods:
                handler_method = getattr(self, route.handler, None)
                if handler_method:
                    return self._invoke_handler(handler_method, path, query_params, handler)
            return None

        # Check dynamic routes (regex patterns)
        for route in route_table["dynamic"]:
            match = re.match(route.pattern, path)
            if match and method in route.methods:
                handler_method = getattr(self, route.handler, None)
                if handler_method:
                    # Extract path parameters from regex groups
                    path_params = match.groups()
                    return self._invoke_handler(
                        handler_method, path, query_params, handler, path_params
                    )

        return None

    def _invoke_handler(
        self,
        handler_method: Callable,
        path: str,
        query_params: dict,
        handler: Any,
        path_params: tuple = (),
    ) -> HandlerResult | None:
        """Invoke a handler method with the correct argument pattern.

        Uses the module-level ``_HANDLER_SIGNATURES`` dict for O(1) lookup
        instead of sequential set-membership checks.
        """
        method_name = (
            getattr(handler_method, "__name__", None)
            or getattr(handler_method, "_mock_name", None)
            or getattr(handler_method, "__qualname__", None)
            or handler_method.__class__.__name__
        )

        sig = _HANDLER_SIGNATURES.get(method_name, "h")

        if sig == "none":
            return handler_method()
        if sig == "q":
            return handler_method(query_params)
        if sig == "h":
            return handler_method(handler)
        if sig == "qh":
            return handler_method(query_params, handler)
        if sig == "pqh":
            return handler_method(path, query_params, handler)

        # Signatures that require a path parameter
        entity_id = path_params[0] if path_params else ""
        if sig == "id":
            return handler_method(entity_id)
        if sig == "id_q":
            return handler_method(entity_id, query_params)
        if sig == "id_h":
            return handler_method(entity_id, handler)
        if sig == "id_qh":
            return handler_method(entity_id, query_params, handler)

        # Fallback: try common arg patterns
        logger.warning("Unknown handler method signature: %s", method_name)
        try:
            return handler_method(path, query_params, handler)
        except TypeError:
            try:
                return handler_method(query_params, handler)
            except TypeError:
                try:
                    return handler_method(handler)
                except TypeError:
                    return handler_method()

    # -------------------------------------------------------------------------
    # Routing helper methods for endpoints with multiple HTTP methods
    # -------------------------------------------------------------------------

    def _route_nodes(
        self: RoutingProtocol, path: str, query_params: dict, handler: Any
    ) -> HandlerResult | None:
        """Route /nodes endpoint based on HTTP method."""
        method = getattr(handler, "command", "GET")
        if method == "POST":
            return getattr(self, "_handle_create_node")(handler)
        return getattr(self, "_handle_list_nodes")(query_params)

    def _route_share(
        self: RoutingProtocol, path: str, query_params: dict, handler: Any
    ) -> HandlerResult | None:
        """Route /share endpoint based on HTTP method."""
        method = getattr(handler, "command", "POST")
        if method == "POST":
            return getattr(self, "_handle_share_item")(handler)
        elif method == "DELETE":
            return getattr(self, "_handle_revoke_share")(handler)
        elif method == "PATCH":
            return getattr(self, "_handle_update_share")(handler)
        return None

    def _route_global(
        self: RoutingProtocol, path: str, query_params: dict, handler: Any
    ) -> HandlerResult | None:
        """Route /global endpoint based on HTTP method."""
        method = getattr(handler, "command", "GET")
        if method == "POST":
            return getattr(self, "_handle_store_verified_fact")(handler)
        return getattr(self, "_handle_query_global")(query_params)

    def _route_federation_regions(
        self: RoutingProtocol, path: str, query_params: dict, handler: Any
    ) -> HandlerResult | None:
        """Route /federation/regions endpoint based on HTTP method."""
        method = getattr(handler, "command", "GET")
        if method == "POST":
            return getattr(self, "_handle_register_region")(handler)
        return getattr(self, "_handle_list_regions")(query_params)

    def _route_governance_roles(
        self: RoutingProtocol, path: str, query_params: dict, handler: Any
    ) -> HandlerResult | None:
        """Route /governance/roles endpoint based on HTTP method."""
        method = getattr(handler, "command", "GET")
        if method == "POST":
            return getattr(self, "_handle_create_role")(handler)
        # GET not implemented yet - would list roles
        return None

    def _route_node_visibility(
        self: RoutingProtocol, node_id: str, query_params: dict, handler: Any
    ) -> HandlerResult | None:
        """Route /nodes/:id/visibility endpoint based on HTTP method."""
        method = getattr(handler, "command", "GET")
        if method == "PUT":
            return getattr(self, "_handle_set_visibility")(node_id, handler)
        return getattr(self, "_handle_get_visibility")(node_id)

    def _route_node_access(
        self: RoutingProtocol, node_id: str, query_params: dict, handler: Any
    ) -> HandlerResult | None:
        """Route /nodes/:id/access endpoint based on HTTP method."""
        method = getattr(handler, "command", "GET")
        if method == "POST":
            return getattr(self, "_handle_grant_access")(node_id, handler)
        elif method == "DELETE":
            return getattr(self, "_handle_revoke_access")(node_id, handler)
        return getattr(self, "_handle_list_access_grants")(node_id, query_params)

    def _route_curation_policy(
        self: RoutingProtocol, path: str, query_params: dict, handler: Any
    ) -> HandlerResult | None:
        """Route /curation/policy endpoint based on HTTP method."""
        method = getattr(handler, "command", "GET")
        if method in ("POST", "PUT"):
            # Create and update share one upsert implementation.
            return getattr(self, "_handle_set_curation_policy")(handler)
        return getattr(self, "_handle_get_curation_policy")(query_params)

    # -------------------------------------------------------------------------
    # Wrapper methods for dashboard endpoints (async -> sync)
    # -------------------------------------------------------------------------

    def _handle_dashboard_health(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle GET /dashboard/health."""
        return _run_async(getattr(self, "handle_dashboard_health")(handler.request))

    def _handle_dashboard_metrics(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle GET /dashboard/metrics."""
        return _run_async(getattr(self, "handle_dashboard_metrics")(handler.request))

    def _handle_dashboard_metrics_reset(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /dashboard/metrics/reset."""
        return _run_async(getattr(self, "handle_dashboard_metrics_reset")(handler.request))

    def _handle_dashboard_adapters(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle GET /dashboard/adapters."""
        return _run_async(getattr(self, "handle_dashboard_adapters")(handler.request))

    def _handle_dashboard_queries(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle GET /dashboard/queries."""
        return _run_async(getattr(self, "handle_dashboard_queries")(handler.request))

    def _handle_dashboard_batcher_stats(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle GET /dashboard/batcher."""
        return _run_async(getattr(self, "handle_dashboard_batcher_stats")(handler.request))

    # -------------------------------------------------------------------------
    # Wrapper methods for stats endpoints (async -> sync)
    # -------------------------------------------------------------------------

    def _handle_contradiction_stats(self: RoutingProtocol) -> HandlerResult:
        """Handle GET /contradictions/stats."""
        return _run_async(getattr(self, "get_contradiction_stats")())

    def _handle_governance_stats(self: RoutingProtocol) -> HandlerResult:
        """Handle GET /governance/stats."""
        return _run_async(getattr(self, "get_governance_stats")())

    def _handle_analytics_stats(self: RoutingProtocol) -> HandlerResult:
        """Handle GET /analytics/stats."""
        return _run_async(getattr(self, "get_analytics_stats")())

    def _handle_extraction_stats(self: RoutingProtocol) -> HandlerResult:
        """Handle GET /extraction/stats."""
        return _run_async(getattr(self, "get_extraction_stats")())

    def _handle_decay_stats(self: RoutingProtocol) -> HandlerResult:
        """Handle GET /confidence/stats."""
        return _run_async(getattr(self, "get_decay_stats")())

    # -------------------------------------------------------------------------
    # Dedup handler methods
    # -------------------------------------------------------------------------

    def _handle_get_duplicate_clusters(self: RoutingProtocol, query_params: dict) -> HandlerResult:
        """Handle GET /dedup/clusters."""
        workspace_id = query_params.get("workspace_id", "default")
        similarity_threshold = safe_query_float(query_params, "similarity_threshold", default=0.9)
        limit = safe_query_int(query_params, "limit", default=100, max_val=1000)
        return _run_async(
            getattr(self, "get_duplicate_clusters")(
                workspace_id=workspace_id,
                similarity_threshold=similarity_threshold,
                limit=limit,
            )
        )

    def _handle_get_dedup_report(self: RoutingProtocol, query_params: dict) -> HandlerResult:
        """Handle GET /dedup/report."""
        workspace_id = query_params.get("workspace_id", "default")
        similarity_threshold = safe_query_float(query_params, "similarity_threshold", default=0.9)
        return _run_async(
            getattr(self, "get_dedup_report")(
                workspace_id=workspace_id,
                similarity_threshold=similarity_threshold,
            )
        )

    def _handle_merge_duplicate_cluster(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /dedup/merge."""
        body = _parse_json_body(handler)
        workspace_id = body.get("workspace_id", "default")

        # SECURITY: Validate workspace access
        user = self.get_current_user(handler)
        workspace_err = validate_workspace_access_sync(
            user=user,
            workspace_id=workspace_id,
            endpoint="/api/v1/knowledge/mound/dedup/merge",
            ip_address=get_client_ip(handler),
        )
        if workspace_err:
            return workspace_err

        cluster_id = body.get("cluster_id")
        primary_node_id = body.get("primary_node_id")
        archive = body.get("archive", True)

        if not cluster_id:
            return error_response("cluster_id is required", 400)

        return _run_async(
            getattr(self, "merge_duplicate_cluster")(
                workspace_id=workspace_id,
                cluster_id=cluster_id,
                primary_node_id=primary_node_id,
                archive=archive,
            )
        )

    def _handle_auto_merge_exact_duplicates(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /dedup/auto-merge."""
        body = _parse_json_body(handler)
        workspace_id = body.get("workspace_id", "default")

        # SECURITY: Validate workspace access
        user = self.get_current_user(handler)
        workspace_err = validate_workspace_access_sync(
            user=user,
            workspace_id=workspace_id,
            endpoint="/api/v1/knowledge/mound/dedup/auto-merge",
            ip_address=get_client_ip(handler),
        )
        if workspace_err:
            return workspace_err

        dry_run = body.get("dry_run", True)

        return _run_async(
            getattr(self, "auto_merge_exact_duplicates")(
                workspace_id=workspace_id,
                dry_run=dry_run,
            )
        )

    # -------------------------------------------------------------------------
    # Pruning handler methods
    # -------------------------------------------------------------------------

    def _handle_get_prunable_items(self: RoutingProtocol, query_params: dict) -> HandlerResult:
        """Handle GET /pruning/items."""
        workspace_id = query_params.get("workspace_id", "default")
        staleness_threshold = safe_query_float(query_params, "staleness_threshold", default=0.9)
        min_age_days = safe_query_int(query_params, "min_age_days", default=30, max_val=3650)
        limit = safe_query_int(query_params, "limit", default=100, max_val=1000)
        return _run_async(
            getattr(self, "get_prunable_items")(
                workspace_id=workspace_id,
                staleness_threshold=staleness_threshold,
                min_age_days=min_age_days,
                limit=limit,
            )
        )

    def _handle_execute_prune(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /pruning/execute."""
        body = _parse_json_body(handler)
        workspace_id = body.get("workspace_id", "default")

        # SECURITY: Validate workspace access
        user = self.get_current_user(handler)
        workspace_err = validate_workspace_access_sync(
            user=user,
            workspace_id=workspace_id,
            endpoint="/api/v1/knowledge/mound/pruning/execute",
            ip_address=get_client_ip(handler),
        )
        if workspace_err:
            return workspace_err

        item_ids = body.get("item_ids", [])
        action = body.get("action", "archive")
        reason = body.get("reason", "manual_prune")

        if not item_ids:
            return error_response("item_ids is required", 400)

        return _run_async(
            getattr(self, "execute_prune")(
                workspace_id=workspace_id,
                item_ids=item_ids,
                action=action,
                reason=reason,
            )
        )

    def _handle_auto_prune(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /pruning/auto."""
        body = _parse_json_body(handler)
        workspace_id = body.get("workspace_id", "default")
        policy_id = body.get("policy_id")
        staleness_threshold = safe_query_float(body, "staleness_threshold", default=0.9)
        min_age_days = safe_query_int(body, "min_age_days", default=30, max_val=3650)
        action = body.get("action", "archive")
        dry_run = body.get("dry_run", True)

        return _run_async(
            getattr(self, "auto_prune")(
                workspace_id=workspace_id,
                policy_id=policy_id,
                staleness_threshold=staleness_threshold,
                min_age_days=min_age_days,
                action=action,
                dry_run=dry_run,
            )
        )

    def _handle_get_prune_history(self: RoutingProtocol, query_params: dict) -> HandlerResult:
        """Handle GET /pruning/history."""
        workspace_id = query_params.get("workspace_id", "default")
        limit = safe_query_int(query_params, "limit", default=50, max_val=1000)
        since = query_params.get("since")
        return _run_async(
            getattr(self, "get_prune_history")(
                workspace_id=workspace_id,
                limit=limit,
                since=since,
            )
        )

    def _handle_restore_pruned_item(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /pruning/restore."""
        body = _parse_json_body(handler)
        workspace_id = body.get("workspace_id", "default")
        node_id = body.get("node_id")

        if not node_id:
            return error_response("node_id is required", 400)

        return _run_async(
            getattr(self, "restore_pruned_item")(
                workspace_id=workspace_id,
                node_id=node_id,
            )
        )

    def _handle_apply_confidence_decay(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /pruning/decay."""
        body = _parse_json_body(handler)
        workspace_id = body.get("workspace_id", "default")
        decay_rate = safe_query_float(body, "decay_rate", default=0.01)
        min_confidence = safe_query_float(body, "min_confidence", default=0.1)

        return _run_async(
            getattr(self, "apply_confidence_decay")(
                workspace_id=workspace_id,
                decay_rate=decay_rate,
                min_confidence=min_confidence,
            )
        )

    # -------------------------------------------------------------------------
    # Contradiction handler methods
    # -------------------------------------------------------------------------

    def _handle_detect_contradictions(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /contradictions/detect."""
        body = _parse_json_body(handler)
        workspace_id = body.get("workspace_id", "default")
        item_ids = body.get("item_ids")

        return _run_async(
            getattr(self, "detect_contradictions")(
                workspace_id=workspace_id,
                item_ids=item_ids,
            )
        )

    def _handle_list_contradictions(self: RoutingProtocol, query_params: dict) -> HandlerResult:
        """Handle GET /contradictions."""
        workspace_id = query_params.get("workspace_id")
        min_severity = query_params.get("min_severity")

        return _run_async(
            getattr(self, "list_contradictions")(
                workspace_id=workspace_id,
                min_severity=min_severity,
            )
        )

    def _handle_resolve_contradiction(
        self: RoutingProtocol, contradiction_id: str, handler: Any
    ) -> HandlerResult:
        """Handle POST /contradictions/:id/resolve."""
        body = _parse_json_body(handler)
        strategy = body.get("strategy")
        resolved_by = body.get("resolved_by")
        notes = body.get("notes", "")

        if not strategy:
            return error_response("strategy is required", 400)

        return _run_async(
            getattr(self, "resolve_contradiction")(
                contradiction_id=contradiction_id,
                strategy=strategy,
                resolved_by=resolved_by,
                notes=notes,
            )
        )

    # -------------------------------------------------------------------------
    # Governance handler methods
    # -------------------------------------------------------------------------

    def _handle_create_role(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /governance/roles."""
        body = _parse_json_body(handler)
        name = body.get("name")
        permissions = body.get("permissions", [])
        description = body.get("description", "")
        workspace_id = body.get("workspace_id")
        created_by = body.get("created_by")

        if not name:
            return error_response("name is required", 400)

        return _run_async(
            getattr(self, "create_role")(
                name=name,
                permissions=permissions,
                description=description,
                workspace_id=workspace_id,
                created_by=created_by,
            )
        )

    def _handle_assign_role(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /governance/roles/assign."""
        body = _parse_json_body(handler)
        user_id = body.get("user_id")
        role_id = body.get("role_id")
        workspace_id = body.get("workspace_id")
        assigned_by = body.get("assigned_by")

        if not user_id or not role_id:
            return error_response("user_id and role_id are required", 400)

        return _run_async(
            getattr(self, "assign_role")(
                user_id=user_id,
                role_id=role_id,
                workspace_id=workspace_id,
                assigned_by=assigned_by,
            )
        )

    def _handle_revoke_role(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /governance/roles/revoke."""
        body = _parse_json_body(handler)
        user_id = body.get("user_id")
        role_id = body.get("role_id")
        workspace_id = body.get("workspace_id")

        if not user_id or not role_id:
            return error_response("user_id and role_id are required", 400)

        return _run_async(
            getattr(self, "revoke_role")(
                user_id=user_id,
                role_id=role_id,
                workspace_id=workspace_id,
            )
        )

    def _handle_get_user_permissions(
        self: RoutingProtocol, user_id: str, query_params: dict
    ) -> HandlerResult:
        """Handle GET /governance/permissions/:user_id."""
        workspace_id = query_params.get("workspace_id")

        return _run_async(
            getattr(self, "get_user_permissions")(
                user_id=user_id,
                workspace_id=workspace_id,
            )
        )

    def _handle_check_permission(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /governance/permissions/check."""
        body = _parse_json_body(handler)
        user_id = body.get("user_id")
        permission = body.get("permission")
        workspace_id = body.get("workspace_id")

        if not user_id or not permission:
            return error_response("user_id and permission are required", 400)

        return _run_async(
            getattr(self, "check_permission")(
                user_id=user_id,
                permission=permission,
                workspace_id=workspace_id,
            )
        )

    def _handle_query_audit(self: RoutingProtocol, query_params: dict) -> HandlerResult:
        """Handle GET /governance/audit."""
        actor_id = query_params.get("actor_id")
        action = query_params.get("action")
        workspace_id = query_params.get("workspace_id")
        limit = safe_query_int(query_params, "limit", default=100, max_val=1000)

        return _run_async(
            getattr(self, "query_audit_trail")(
                actor_id=actor_id,
                action=action,
                workspace_id=workspace_id,
                limit=limit,
            )
        )

    def _handle_get_user_activity(
        self: RoutingProtocol, user_id: str, query_params: dict
    ) -> HandlerResult:
        """Handle GET /governance/audit/user/:user_id."""
        days = safe_query_int(query_params, "days", default=30, max_val=365)

        return _run_async(
            getattr(self, "get_user_activity")(
                user_id=user_id,
                days=days,
            )
        )

    # -------------------------------------------------------------------------
    # Analytics handler methods
    # -------------------------------------------------------------------------

    def _handle_analyze_coverage(self: RoutingProtocol, query_params: dict) -> HandlerResult:
        """Handle GET /analytics/coverage."""
        workspace_id = query_params.get("workspace_id", "default")
        stale_threshold_days = safe_query_int(
            query_params, "stale_threshold_days", default=90, max_val=3650
        )

        return _run_async(
            getattr(self, "analyze_coverage")(
                workspace_id=workspace_id,
                stale_threshold_days=stale_threshold_days,
            )
        )

    def _handle_analyze_usage(self: RoutingProtocol, query_params: dict) -> HandlerResult:
        """Handle GET /analytics/usage."""
        workspace_id = query_params.get("workspace_id", "default")
        days = safe_query_int(query_params, "days", default=30, max_val=365)

        return _run_async(
            getattr(self, "analyze_usage")(
                workspace_id=workspace_id,
                days=days,
            )
        )

    def _handle_record_usage_event(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /analytics/usage/record."""
        body = _parse_json_body(handler)
        event_type = body.get("event_type")
        item_id = body.get("item_id")
        user_id = body.get("user_id")
        workspace_id = body.get("workspace_id")
        query = body.get("query")

        if not event_type:
            return error_response("event_type is required", 400)

        return _run_async(
            getattr(self, "record_usage_event")(
                event_type=event_type,
                item_id=item_id,
                user_id=user_id,
                workspace_id=workspace_id,
                query=query,
            )
        )

    def _handle_capture_quality_snapshot(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /analytics/quality/snapshot."""
        body = _parse_json_body(handler)
        workspace_id = body.get("workspace_id", "default")

        return _run_async(
            getattr(self, "capture_quality_snapshot")(
                workspace_id=workspace_id,
            )
        )

    def _handle_get_quality_trend(self: RoutingProtocol, query_params: dict) -> HandlerResult:
        """Handle GET /analytics/quality/trend."""
        workspace_id = query_params.get("workspace_id", "default")
        days = safe_query_int(query_params, "days", default=30, max_val=365)

        return _run_async(
            getattr(self, "get_quality_trend")(
                workspace_id=workspace_id,
                days=days,
            )
        )

    # -------------------------------------------------------------------------
    # Extraction handler methods
    # -------------------------------------------------------------------------

    def _handle_extract_from_debate(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /extraction/debate."""
        body = _parse_json_body(handler)
        debate_id = body.get("debate_id")
        messages = body.get("messages", [])
        consensus_text = body.get("consensus_text")
        topic = body.get("topic")

        if not debate_id:
            return error_response("debate_id is required", 400)

        if not messages:
            return error_response("messages list is required", 400)

        return _run_async(
            getattr(self, "extract_from_debate")(
                debate_id=debate_id,
                messages=messages,
                consensus_text=consensus_text,
                topic=topic,
            )
        )

    def _handle_promote_extracted(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /extraction/promote."""
        body = _parse_json_body(handler)
        workspace_id = body.get("workspace_id", "default")
        min_confidence = safe_query_float(body, "min_confidence", default=0.6)

        return _run_async(
            getattr(self, "promote_extracted_knowledge")(
                workspace_id=workspace_id,
                min_confidence=min_confidence,
            )
        )

    # -------------------------------------------------------------------------
    # Confidence decay handler methods
    # -------------------------------------------------------------------------

    def _handle_apply_confidence_decay_new(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /confidence/decay."""
        body = _parse_json_body(handler)
        workspace_id = body.get("workspace_id", "default")
        force = body.get("force", False)

        return _run_async(
            getattr(self, "apply_confidence_decay_endpoint")(
                workspace_id=workspace_id,
                force=force,
            )
        )

    def _handle_record_confidence_event(self: RoutingProtocol, handler: Any) -> HandlerResult:
        """Handle POST /confidence/event."""
        body = _parse_json_body(handler)
        item_id = body.get("item_id")
        event = body.get("event")
        reason = body.get("reason", "")

        if not item_id:
            return error_response("item_id is required", 400)

        if not event:
            return error_response("event is required", 400)

        return _run_async(
            getattr(self, "record_confidence_event")(
                item_id=item_id,
                event=event,
                reason=reason,
            )
        )

    def _handle_get_confidence_history(self: RoutingProtocol, query_params: dict) -> HandlerResult:
        """Handle GET /confidence/history."""
        item_id = query_params.get("item_id")
        event_type = query_params.get("event_type")
        limit = safe_query_int(query_params, "limit", default=100, max_val=1000)

        return _run_async(
            getattr(self, "get_confidence_history")(
                item_id=item_id,
                event_type=event_type,
                limit=limit,
            )
        )
