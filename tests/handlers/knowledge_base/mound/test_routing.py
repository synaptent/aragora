"""Tests for Knowledge Mound routing mixin (routing.py, 1386 lines).

Covers all routes and behavior of the RoutingMixin class:
- _build_route_table() produces correct static and dynamic routes
- _dispatch_route() matches static paths, dynamic regex paths, and HTTP methods
- _invoke_handler() dispatches with correct argument signatures
- _route_nodes() dispatches GET vs POST
- _route_share() dispatches POST/DELETE/PATCH
- _route_global() dispatches GET vs POST
- _route_federation_regions() dispatches GET vs POST
- _route_governance_roles() dispatches GET (None) vs POST
- _route_node_visibility() dispatches GET vs PUT
- _route_node_access() dispatches GET/POST/DELETE
- _route_curation_policy() dispatches GET/POST/PUT
- Dashboard wrapper methods (_handle_dashboard_*)
- Stats wrapper methods (_handle_contradiction_stats, etc.)
- Dedup handler methods with workspace validation
- Pruning handler methods with validation
- Contradiction handler methods
- Governance handler methods with required field validation
- Analytics handler methods
- Extraction handler methods with required field validation
- Confidence decay handler methods
- _parse_json_body error handling
- Path parameter extraction from dynamic routes
- Method-not-allowed returns None
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from aragora.server.handlers.knowledge_base.mound.routing import (
    RouteEntry,
    RoutingMixin,
    _parse_json_body,
    _HANDLER_SIGNATURES,
)
from aragora.server.handlers.utils.responses import HandlerResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    raw = result.body
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if result is None:
        return -1
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


# ---------------------------------------------------------------------------
# Mock HTTP handler that mimics the request object shape
# ---------------------------------------------------------------------------


@dataclass
class MockRequest:
    """Mock request with body bytes."""

    body: bytes = b"{}"


@dataclass
class MockHTTPHandler:
    """Lightweight mock for the HTTP handler passed to routing methods."""

    command: str = "GET"
    path: str = ""
    headers: dict[str, str] = field(default_factory=lambda: {"User-Agent": "test"})
    client_address: tuple = ("127.0.0.1", 12345)
    request: MockRequest = field(default_factory=MockRequest)

    @classmethod
    def with_body(cls, body: dict, method: str = "POST") -> MockHTTPHandler:
        """Create a mock handler with a JSON body."""
        raw = json.dumps(body).encode("utf-8")
        return cls(command=method, request=MockRequest(body=raw))

    @classmethod
    def with_method(cls, method: str) -> MockHTTPHandler:
        return cls(command=method)


# ---------------------------------------------------------------------------
# Concrete class combining RoutingMixin with stub dependencies
# ---------------------------------------------------------------------------


class StubHandler(RoutingMixin):
    """Concrete handler class for testing the routing mixin.

    All handler methods called by routing are stubbed as MagicMocks so we can
    verify that the routing mixin dispatches correctly.
    """

    def __init__(self):
        # Stubs for RoutingProtocol requirements
        self._mound = MagicMock()
        self._user = MagicMock()

        # Create a default HandlerResult for successful calls
        self._ok = HandlerResult(
            status_code=200,
            content_type="application/json",
            body=json.dumps({"status": "ok"}).encode(),
        )

        # ---- Static route handler stubs ----
        # NOTE: name= must match the attribute name so _invoke_handler can
        # look up the correct call-signature in _HANDLER_SIGNATURES.
        # POST /query
        self._handle_mound_query = MagicMock(name="_handle_mound_query", return_value=self._ok)
        # GET/POST /nodes router
        self._handle_list_nodes = MagicMock(name="_handle_list_nodes", return_value=self._ok)
        self._handle_create_node = MagicMock(name="_handle_create_node", return_value=self._ok)
        # POST /relationships
        self._handle_create_relationship = MagicMock(
            name="_handle_create_relationship", return_value=self._ok
        )
        # GET /stats
        self._handle_mound_stats = MagicMock(name="_handle_mound_stats", return_value=self._ok)
        # POST /index/repository
        self._handle_index_repository = MagicMock(
            name="_handle_index_repository", return_value=self._ok
        )
        # GET /culture
        self._handle_get_culture = MagicMock(name="_handle_get_culture", return_value=self._ok)
        # POST /culture/documents
        self._handle_add_culture_document = MagicMock(
            name="_handle_add_culture_document", return_value=self._ok
        )
        # POST /culture/promote
        self._handle_promote_to_culture = MagicMock(
            name="_handle_promote_to_culture", return_value=self._ok
        )
        # GET /stale
        self._handle_get_stale = MagicMock(name="_handle_get_stale", return_value=self._ok)
        # POST /schedule-revalidation
        self._handle_schedule_revalidation = MagicMock(
            name="_handle_schedule_revalidation", return_value=self._ok
        )
        # POST /sync/*
        self._handle_sync_continuum = MagicMock(
            name="_handle_sync_continuum", return_value=self._ok
        )
        self._handle_sync_consensus = MagicMock(
            name="_handle_sync_consensus", return_value=self._ok
        )
        self._handle_sync_facts = MagicMock(name="_handle_sync_facts", return_value=self._ok)
        # GET /export/*
        self._handle_export_d3 = MagicMock(name="_handle_export_d3", return_value=self._ok)
        self._handle_export_graphml = MagicMock(
            name="_handle_export_graphml", return_value=self._ok
        )
        # Sharing stubs
        self._handle_share_item = MagicMock(name="_handle_share_item", return_value=self._ok)
        self._handle_revoke_share = MagicMock(name="_handle_revoke_share", return_value=self._ok)
        self._handle_update_share = MagicMock(name="_handle_update_share", return_value=self._ok)
        self._handle_shared_with_me = MagicMock(
            name="_handle_shared_with_me", return_value=self._ok
        )
        self._handle_my_shares = MagicMock(name="_handle_my_shares", return_value=self._ok)
        # Global knowledge stubs
        self._handle_store_verified_fact = MagicMock(
            name="_handle_store_verified_fact", return_value=self._ok
        )
        self._handle_query_global = MagicMock(name="_handle_query_global", return_value=self._ok)
        self._handle_promote_to_global = MagicMock(
            name="_handle_promote_to_global", return_value=self._ok
        )
        self._handle_get_system_facts = MagicMock(
            name="_handle_get_system_facts", return_value=self._ok
        )
        self._handle_get_system_workspace_id = MagicMock(
            name="_handle_get_system_workspace_id", return_value=self._ok
        )
        # Federation stubs
        self._handle_register_region = MagicMock(
            name="_handle_register_region", return_value=self._ok
        )
        self._handle_list_regions = MagicMock(name="_handle_list_regions", return_value=self._ok)
        self._handle_sync_to_region = MagicMock(
            name="_handle_sync_to_region", return_value=self._ok
        )
        self._handle_pull_from_region = MagicMock(
            name="_handle_pull_from_region", return_value=self._ok
        )
        self._handle_sync_all_regions = MagicMock(
            name="_handle_sync_all_regions", return_value=self._ok
        )
        self._handle_get_federation_status = MagicMock(
            name="_handle_get_federation_status", return_value=self._ok
        )
        # Dynamic route handler stubs
        self._handle_get_node = MagicMock(name="_handle_get_node", return_value=self._ok)
        self._handle_get_node_relationships = MagicMock(
            name="_handle_get_node_relationships", return_value=self._ok
        )
        self._handle_revalidate_node = MagicMock(
            name="_handle_revalidate_node", return_value=self._ok
        )
        self._handle_set_visibility = MagicMock(
            name="_handle_set_visibility", return_value=self._ok
        )
        self._handle_get_visibility = MagicMock(
            name="_handle_get_visibility", return_value=self._ok
        )
        self._handle_grant_access = MagicMock(name="_handle_grant_access", return_value=self._ok)
        self._handle_revoke_access = MagicMock(name="_handle_revoke_access", return_value=self._ok)
        self._handle_list_access_grants = MagicMock(
            name="_handle_list_access_grants", return_value=self._ok
        )
        self._handle_unregister_region = MagicMock(
            name="_handle_unregister_region", return_value=self._ok
        )
        # NOTE: _handle_resolve_contradiction, _handle_get_user_permissions,
        # and _handle_get_user_activity are real methods on RoutingMixin --
        # do NOT shadow them with MagicMock stubs here.
        # Graph stubs
        self._handle_graph_lineage = MagicMock(name="_handle_graph_lineage", return_value=self._ok)
        self._handle_graph_related = MagicMock(name="_handle_graph_related", return_value=self._ok)
        self._handle_graph_traversal = MagicMock(
            name="_handle_graph_traversal", return_value=self._ok
        )
        # Dashboard async stubs (these call handle_dashboard_* coroutines)
        self.handle_dashboard_health = AsyncMock(return_value=self._ok)
        self.handle_dashboard_metrics = AsyncMock(return_value=self._ok)
        self.handle_dashboard_metrics_reset = AsyncMock(return_value=self._ok)
        self.handle_dashboard_adapters = AsyncMock(return_value=self._ok)
        self.handle_dashboard_queries = AsyncMock(return_value=self._ok)
        self.handle_dashboard_batcher_stats = AsyncMock(return_value=self._ok)
        # Stats async stubs (called by _handle_*_stats wrapper methods)
        self.get_contradiction_stats = AsyncMock(return_value=self._ok)
        self.get_governance_stats = AsyncMock(return_value=self._ok)
        self.get_analytics_stats = AsyncMock(return_value=self._ok)
        self.get_extraction_stats = AsyncMock(return_value=self._ok)
        self.get_decay_stats = AsyncMock(return_value=self._ok)
        # Dedup async stubs
        self.get_duplicate_clusters = AsyncMock(return_value=self._ok)
        self.get_dedup_report = AsyncMock(return_value=self._ok)
        self.merge_duplicate_cluster = AsyncMock(return_value=self._ok)
        self.auto_merge_exact_duplicates = AsyncMock(return_value=self._ok)
        # Pruning async stubs
        self.get_prunable_items = AsyncMock(return_value=self._ok)
        self.execute_prune = AsyncMock(return_value=self._ok)
        self.auto_prune = AsyncMock(return_value=self._ok)
        self.get_prune_history = AsyncMock(return_value=self._ok)
        self.restore_pruned_item = AsyncMock(return_value=self._ok)
        self.apply_confidence_decay = AsyncMock(return_value=self._ok)
        # Contradiction async stubs
        self.detect_contradictions = AsyncMock(return_value=self._ok)
        self.list_contradictions = AsyncMock(return_value=self._ok)
        self.resolve_contradiction = AsyncMock(return_value=self._ok)
        # Governance async stubs
        self.create_role = AsyncMock(return_value=self._ok)
        self.assign_role = AsyncMock(return_value=self._ok)
        self.revoke_role = AsyncMock(return_value=self._ok)
        self.get_user_permissions = AsyncMock(return_value=self._ok)
        self.check_permission = AsyncMock(return_value=self._ok)
        self.query_audit_trail = AsyncMock(return_value=self._ok)
        self.get_user_activity = AsyncMock(return_value=self._ok)
        # Analytics async stubs
        self.analyze_coverage = AsyncMock(return_value=self._ok)
        self.analyze_usage = AsyncMock(return_value=self._ok)
        self.record_usage_event = AsyncMock(return_value=self._ok)
        self.capture_quality_snapshot = AsyncMock(return_value=self._ok)
        self.get_quality_trend = AsyncMock(return_value=self._ok)
        # Extraction async stubs
        self.extract_from_debate = AsyncMock(return_value=self._ok)
        self.promote_extracted_knowledge = AsyncMock(return_value=self._ok)
        # Confidence decay async stubs
        self.apply_confidence_decay_endpoint = AsyncMock(return_value=self._ok)
        self.record_confidence_event = AsyncMock(return_value=self._ok)
        self.get_confidence_history = AsyncMock(return_value=self._ok)
        # Curation stubs
        self._handle_set_curation_policy = MagicMock(
            name="_handle_set_curation_policy", return_value=self._ok
        )
        self._handle_get_curation_policy = MagicMock(
            name="_handle_get_curation_policy", return_value=self._ok
        )
        self._handle_curation_status = MagicMock(
            name="_handle_curation_status", return_value=self._ok
        )
        self._handle_run_curation = MagicMock(name="_handle_run_curation", return_value=self._ok)
        self._handle_curation_history = MagicMock(
            name="_handle_curation_history", return_value=self._ok
        )
        self._handle_quality_scores = MagicMock(
            name="_handle_quality_scores", return_value=self._ok
        )
        self._handle_tier_distribution = MagicMock(
            name="_handle_tier_distribution", return_value=self._ok
        )

    def _get_mound(self):
        return self._mound

    def get_current_user(self, handler):
        return self._user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler() -> StubHandler:
    """Create a StubHandler instance for testing."""
    return StubHandler()


@pytest.fixture
def http_get() -> MockHTTPHandler:
    return MockHTTPHandler.with_method("GET")


@pytest.fixture
def http_post() -> MockHTTPHandler:
    return MockHTTPHandler.with_method("POST")


@pytest.fixture
def http_put() -> MockHTTPHandler:
    return MockHTTPHandler.with_method("PUT")


@pytest.fixture
def http_delete() -> MockHTTPHandler:
    return MockHTTPHandler.with_method("DELETE")


@pytest.fixture
def http_patch() -> MockHTTPHandler:
    return MockHTTPHandler.with_method("PATCH")


# ===========================================================================
# RouteEntry dataclass
# ===========================================================================


class TestRouteEntry:
    """Tests for the RouteEntry dataclass."""

    def test_static_route_entry(self):
        entry = RouteEntry("/api/v1/test", "_handle_test", ("GET",))
        assert entry.pattern == "/api/v1/test"
        assert entry.handler == "_handle_test"
        assert entry.methods == ("GET",)
        assert entry.is_regex is False

    def test_dynamic_route_entry(self):
        entry = RouteEntry(r"^/api/v1/test/([^/]+)$", "_handle_test_id", ("GET",), is_regex=True)
        assert entry.is_regex is True

    def test_multi_method_route(self):
        entry = RouteEntry("/api/v1/items", "_route_items", ("GET", "POST"))
        assert "GET" in entry.methods
        assert "POST" in entry.methods


# ===========================================================================
# _parse_json_body
# ===========================================================================


class TestParseJsonBody:
    """Tests for the _parse_json_body helper."""

    def test_valid_json_body(self):
        h = MockHTTPHandler(request=MockRequest(body=b'{"key": "value"}'))
        result = _parse_json_body(h)
        assert result == {"key": "value"}

    def test_empty_body_returns_empty_dict(self):
        h = MockHTTPHandler(request=MockRequest(body=b""))
        result = _parse_json_body(h)
        assert result == {}

    def test_none_body_returns_empty_dict(self):
        h = MockHTTPHandler(request=MockRequest(body=None))
        result = _parse_json_body(h)
        assert result == {}

    def test_invalid_json_returns_empty_dict(self):
        h = MockHTTPHandler(request=MockRequest(body=b"not json"))
        result = _parse_json_body(h)
        assert result == {}

    def test_invalid_utf8_returns_empty_dict(self):
        h = MockHTTPHandler(request=MockRequest(body=b"\xff\xfe"))
        result = _parse_json_body(h)
        assert result == {}

    def test_handler_without_request_attr_returns_empty_dict(self):
        """If handler has no request attribute, AttributeError is caught."""
        h = MagicMock(spec=[])  # no attributes
        result = _parse_json_body(h)
        assert result == {}

    def test_nested_json_body(self):
        data = {"workspace": {"id": "ws-1"}, "items": [1, 2, 3]}
        h = MockHTTPHandler(request=MockRequest(body=json.dumps(data).encode()))
        result = _parse_json_body(h)
        assert result == data


# ===========================================================================
# _build_route_table
# ===========================================================================


class TestBuildRouteTable:
    """Tests for the route table structure."""

    def test_route_table_has_static_and_dynamic(self, handler):
        table = handler._build_route_table()
        assert "static" in table
        assert "dynamic" in table

    def test_static_routes_are_list(self, handler):
        table = handler._build_route_table()
        assert isinstance(table["static"], list)
        assert all(isinstance(r, RouteEntry) for r in table["static"])

    def test_dynamic_routes_are_list(self, handler):
        table = handler._build_route_table()
        assert isinstance(table["dynamic"], list)
        assert all(isinstance(r, RouteEntry) for r in table["dynamic"])

    def test_static_routes_not_regex(self, handler):
        table = handler._build_route_table()
        for route in table["static"]:
            assert route.is_regex is False

    def test_dynamic_routes_are_regex(self, handler):
        table = handler._build_route_table()
        for route in table["dynamic"]:
            assert route.is_regex is True

    def test_static_route_count(self, handler):
        """Should have many static routes (65+)."""
        table = handler._build_route_table()
        assert len(table["static"]) >= 60

    def test_dynamic_route_count(self, handler):
        """Should have multiple dynamic routes (10+)."""
        table = handler._build_route_table()
        assert len(table["dynamic"]) >= 10

    def test_all_static_paths_start_with_api_prefix(self, handler):
        table = handler._build_route_table()
        for route in table["static"]:
            assert route.pattern.startswith("/api/v1/knowledge/mound/")

    def test_all_route_handlers_have_valid_names(self, handler):
        """Every handler name in the table should start with _ or be a known method."""
        table = handler._build_route_table()
        for route in table["static"] + table["dynamic"]:
            assert route.handler.startswith("_")


# ===========================================================================
# _dispatch_route - Static Routes
# ===========================================================================


class TestDispatchStaticRoutes:
    """Tests for static route dispatching."""

    def test_dispatch_query_post(self, handler):
        h = MockHTTPHandler.with_method("POST")
        result = handler._dispatch_route("/api/v1/knowledge/mound/query", {}, h)
        assert result is not None

    def test_dispatch_stats_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/stats", {}, http_get)
        assert result is not None

    def test_dispatch_culture_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/culture", {}, http_get)
        assert result is not None

    def test_dispatch_stale_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/stale", {}, http_get)
        assert result is not None

    def test_dispatch_export_d3_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/export/d3", {}, http_get)
        assert result is not None

    def test_dispatch_export_graphml_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/export/graphml", {}, http_get)
        assert result is not None

    def test_dispatch_shared_with_me_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/shared-with-me", {}, http_get)
        assert result is not None

    def test_dispatch_my_shares_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/my-shares", {}, http_get)
        assert result is not None

    def test_dispatch_global_facts_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/global/facts", {}, http_get)
        assert result is not None

    def test_dispatch_global_workspace_id_get(self, handler, http_get):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/global/workspace-id", {}, http_get
        )
        assert result is not None

    def test_dispatch_federation_status_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/federation/status", {}, http_get)
        assert result is not None

    def test_dispatch_dedup_clusters_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/dedup/clusters", {}, http_get)
        assert result is not None

    def test_dispatch_dedup_report_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/dedup/report", {}, http_get)
        assert result is not None

    def test_dispatch_pruning_items_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/pruning/items", {}, http_get)
        assert result is not None

    def test_dispatch_pruning_history_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/pruning/history", {}, http_get)
        assert result is not None

    def test_dispatch_contradictions_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/contradictions", {}, http_get)
        assert result is not None

    def test_dispatch_contradictions_stats_get(self, handler, http_get):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/contradictions/stats", {}, http_get
        )
        assert result is not None

    def test_dispatch_governance_audit_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/governance/audit", {}, http_get)
        assert result is not None

    def test_dispatch_governance_stats_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/governance/stats", {}, http_get)
        assert result is not None

    def test_dispatch_analytics_coverage_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/analytics/coverage", {}, http_get)
        assert result is not None

    def test_dispatch_analytics_usage_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/analytics/usage", {}, http_get)
        assert result is not None

    def test_dispatch_analytics_quality_trend_get(self, handler, http_get):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/analytics/quality/trend", {}, http_get
        )
        assert result is not None

    def test_dispatch_analytics_stats_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/analytics/stats", {}, http_get)
        assert result is not None

    def test_dispatch_extraction_stats_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/extraction/stats", {}, http_get)
        assert result is not None

    def test_dispatch_confidence_history_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/confidence/history", {}, http_get)
        assert result is not None

    def test_dispatch_confidence_stats_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/confidence/stats", {}, http_get)
        assert result is not None

    def test_dispatch_curation_status_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/curation/status", {}, http_get)
        assert result is not None

    def test_dispatch_curation_history_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/curation/history", {}, http_get)
        assert result is not None

    def test_dispatch_curation_scores_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/curation/scores", {}, http_get)
        assert result is not None

    def test_dispatch_curation_tiers_get(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/curation/tiers", {}, http_get)
        assert result is not None

    def test_dispatch_wrong_method_returns_none(self, handler, http_get):
        """GET on a POST-only route should return None."""
        result = handler._dispatch_route("/api/v1/knowledge/mound/query", {}, http_get)
        assert result is None

    def test_dispatch_unknown_path_returns_none(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/nonexistent", {}, http_get)
        assert result is None


# ===========================================================================
# _dispatch_route - Static POST Routes
# ===========================================================================


class TestDispatchStaticPostRoutes:
    """Tests for POST static route dispatching."""

    def test_dispatch_relationships_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/relationships", {}, http_post)
        assert result is not None

    def test_dispatch_index_repository_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/index/repository", {}, http_post)
        assert result is not None

    def test_dispatch_culture_documents_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/culture/documents", {}, http_post)
        assert result is not None

    def test_dispatch_culture_promote_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/culture/promote", {}, http_post)
        assert result is not None

    def test_dispatch_schedule_revalidation_post(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/schedule-revalidation", {}, http_post
        )
        assert result is not None

    def test_dispatch_sync_continuum_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/sync/continuum", {}, http_post)
        assert result is not None

    def test_dispatch_sync_consensus_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/sync/consensus", {}, http_post)
        assert result is not None

    def test_dispatch_sync_facts_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/sync/facts", {}, http_post)
        assert result is not None

    def test_dispatch_global_promote_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/global/promote", {}, http_post)
        assert result is not None

    def test_dispatch_federation_sync_push_post(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/federation/sync/push", {}, http_post
        )
        assert result is not None

    def test_dispatch_federation_sync_pull_post(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/federation/sync/pull", {}, http_post
        )
        assert result is not None

    def test_dispatch_federation_sync_all_post(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/federation/sync/all", {}, http_post
        )
        assert result is not None

    def test_dispatch_contradictions_detect_post(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/contradictions/detect", {}, http_post
        )
        assert result is not None

    def test_dispatch_governance_roles_assign_post(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/governance/roles/assign", {}, http_post
        )
        assert result is not None

    def test_dispatch_governance_roles_revoke_post(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/governance/roles/revoke", {}, http_post
        )
        assert result is not None

    def test_dispatch_governance_permissions_check_post(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/governance/permissions/check", {}, http_post
        )
        assert result is not None

    def test_dispatch_analytics_usage_record_post(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/analytics/usage/record", {}, http_post
        )
        assert result is not None

    def test_dispatch_analytics_quality_snapshot_post(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/analytics/quality/snapshot", {}, http_post
        )
        assert result is not None

    def test_dispatch_extraction_debate_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/extraction/debate", {}, http_post)
        assert result is not None

    def test_dispatch_extraction_promote_post(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/extraction/promote", {}, http_post
        )
        assert result is not None

    def test_dispatch_confidence_decay_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/confidence/decay", {}, http_post)
        assert result is not None

    def test_dispatch_confidence_event_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/confidence/event", {}, http_post)
        assert result is not None

    def test_dispatch_dashboard_metrics_reset_post(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/dashboard/metrics/reset", {}, http_post
        )
        assert result is not None

    def test_dispatch_dedup_merge_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/dedup/merge", {}, http_post)
        assert result is not None

    def test_dispatch_dedup_auto_merge_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/dedup/auto-merge", {}, http_post)
        assert result is not None

    def test_dispatch_pruning_execute_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/pruning/execute", {}, http_post)
        assert result is not None

    def test_dispatch_pruning_auto_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/pruning/auto", {}, http_post)
        assert result is not None

    def test_dispatch_pruning_restore_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/pruning/restore", {}, http_post)
        assert result is not None

    def test_dispatch_pruning_decay_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/pruning/decay", {}, http_post)
        assert result is not None

    def test_dispatch_curation_run_post(self, handler, http_post):
        result = handler._dispatch_route("/api/v1/knowledge/mound/curation/run", {}, http_post)
        assert result is not None


# ===========================================================================
# _dispatch_route - Dynamic Routes (regex)
# ===========================================================================


class TestDispatchDynamicRoutes:
    """Tests for dynamic (regex) route dispatching."""

    def test_dispatch_get_node_by_id(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/nodes/node-123", {}, http_get)
        assert result is not None

    def test_dispatch_get_node_relationships(self, handler, http_get):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/nodes/node-123/relationships", {}, http_get
        )
        assert result is not None

    def test_dispatch_get_node_visibility(self, handler, http_get):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/nodes/node-123/visibility", {}, http_get
        )
        assert result is not None

    def test_dispatch_put_node_visibility(self, handler, http_put):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/nodes/node-123/visibility", {}, http_put
        )
        assert result is not None

    def test_dispatch_get_node_access(self, handler, http_get):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/nodes/node-123/access", {}, http_get
        )
        assert result is not None

    def test_dispatch_post_node_access(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/nodes/node-123/access", {}, http_post
        )
        assert result is not None

    def test_dispatch_delete_node_access(self, handler, http_delete):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/nodes/node-123/access", {}, http_delete
        )
        assert result is not None

    def test_dispatch_graph_lineage(self, handler, http_get):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/graph/node-123/lineage", {}, http_get
        )
        assert result is not None

    def test_dispatch_graph_related(self, handler, http_get):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/graph/node-123/related", {}, http_get
        )
        assert result is not None

    def test_dispatch_graph_traversal(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge/mound/graph/node-123", {}, http_get)
        assert result is not None

    def test_dispatch_revalidate_node(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/revalidate/node-123", {}, http_post
        )
        assert result is not None

    def test_dispatch_unregister_region(self, handler, http_delete):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/federation/regions/us-east", {}, http_delete
        )
        assert result is not None

    def test_dispatch_resolve_contradiction(self, handler, http_post):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/contradictions/ctr-42/resolve", {}, http_post
        )
        assert result is not None

    def test_dispatch_get_user_permissions(self, handler, http_get):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/governance/permissions/user-42", {}, http_get
        )
        assert result is not None

    def test_dispatch_get_user_activity(self, handler, http_get):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/governance/audit/user/user-42", {}, http_get
        )
        assert result is not None

    def test_dynamic_route_wrong_method_returns_none(self, handler, http_get):
        """GET on a POST-only dynamic route returns None."""
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/revalidate/node-123", {}, http_get
        )
        assert result is None

    def test_dynamic_route_no_match_returns_none(self, handler, http_get):
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/nonexistent/some-id", {}, http_get
        )
        assert result is None


# ===========================================================================
# Path parameter extraction
# ===========================================================================


class TestPathParameterExtraction:
    """Tests that dynamic routes correctly extract entity IDs."""

    def test_node_id_extracted(self, handler, http_get):
        handler._dispatch_route("/api/v1/knowledge/mound/nodes/my-node-42", {}, http_get)
        handler._handle_get_node.assert_called_once_with("my-node-42")

    def test_graph_traversal_id_extracted(self, handler, http_get):
        handler._dispatch_route("/api/v1/knowledge/mound/graph/graph-node-99", {}, http_get)
        handler._handle_graph_traversal.assert_called_once_with("graph-node-99", {})

    def test_graph_lineage_id_extracted(self, handler, http_get):
        handler._dispatch_route("/api/v1/knowledge/mound/graph/abc/lineage", {}, http_get)
        handler._handle_graph_lineage.assert_called_once_with("abc", {})

    def test_graph_related_id_extracted(self, handler, http_get):
        handler._dispatch_route("/api/v1/knowledge/mound/graph/xyz/related", {}, http_get)
        handler._handle_graph_related.assert_called_once_with("xyz", {})

    def test_node_relationships_id_extracted(self, handler, http_get):
        handler._dispatch_route("/api/v1/knowledge/mound/nodes/n1/relationships", {}, http_get)
        handler._handle_get_node_relationships.assert_called_once_with("n1", {})

    def test_revalidate_id_extracted(self, handler, http_post):
        handler._dispatch_route(
            "/api/v1/knowledge/mound/revalidate/node-to-revalidate", {}, http_post
        )
        handler._handle_revalidate_node.assert_called_once_with("node-to-revalidate", http_post)

    def test_user_permissions_id_extracted(self, handler, http_get):
        handler._dispatch_route(
            "/api/v1/knowledge/mound/governance/permissions/user-xyz", {}, http_get
        )
        # _handle_get_user_permissions is a real RoutingMixin method;
        # verify the underlying async stub received the correct user_id.
        handler.get_user_permissions.assert_called_once_with(
            user_id="user-xyz",
            workspace_id=None,
        )

    def test_user_activity_id_extracted(self, handler, http_get):
        handler._dispatch_route(
            "/api/v1/knowledge/mound/governance/audit/user/admin-1", {}, http_get
        )
        # _handle_get_user_activity is a real RoutingMixin method;
        # verify the underlying async stub received the correct user_id.
        handler.get_user_activity.assert_called_once_with(
            user_id="admin-1",
            days=30,
        )

    def test_unregister_region_id_extracted(self, handler, http_delete):
        handler._dispatch_route(
            "/api/v1/knowledge/mound/federation/regions/eu-west-1", {}, http_delete
        )
        handler._handle_unregister_region.assert_called_once_with("eu-west-1", http_delete)


# ===========================================================================
# _route_nodes - GET vs POST
# ===========================================================================


class TestRouteNodes:
    """Tests for the _route_nodes multi-method dispatcher."""

    def test_get_lists_nodes(self, handler, http_get):
        handler._dispatch_route("/api/v1/knowledge/mound/nodes", {"limit": "10"}, http_get)
        handler._handle_list_nodes.assert_called_once_with({"limit": "10"})

    def test_post_creates_node(self, handler, http_post):
        handler._dispatch_route("/api/v1/knowledge/mound/nodes", {}, http_post)
        handler._handle_create_node.assert_called_once_with(http_post)


# ===========================================================================
# _route_share - POST/DELETE/PATCH
# ===========================================================================


class TestRouteShare:
    """Tests for the _route_share multi-method dispatcher."""

    def test_post_shares_item(self, handler, http_post):
        handler._dispatch_route("/api/v1/knowledge/mound/share", {}, http_post)
        handler._handle_share_item.assert_called_once_with(http_post)

    def test_delete_revokes_share(self, handler, http_delete):
        handler._dispatch_route("/api/v1/knowledge/mound/share", {}, http_delete)
        handler._handle_revoke_share.assert_called_once_with(http_delete)

    def test_patch_updates_share(self, handler, http_patch):
        handler._dispatch_route("/api/v1/knowledge/mound/share", {}, http_patch)
        handler._handle_update_share.assert_called_once_with(http_patch)

    def test_get_not_in_methods(self, handler, http_get):
        """GET is not in the allowed methods for /share, so returns None."""
        result = handler._dispatch_route("/api/v1/knowledge/mound/share", {}, http_get)
        assert result is None


# ===========================================================================
# _route_global - GET vs POST
# ===========================================================================


class TestRouteGlobal:
    """Tests for the _route_global multi-method dispatcher."""

    def test_post_stores_verified_fact(self, handler, http_post):
        handler._dispatch_route("/api/v1/knowledge/mound/global", {}, http_post)
        handler._handle_store_verified_fact.assert_called_once_with(http_post)

    def test_get_queries_global(self, handler, http_get):
        handler._dispatch_route("/api/v1/knowledge/mound/global", {"q": "test"}, http_get)
        handler._handle_query_global.assert_called_once_with({"q": "test"})


# ===========================================================================
# _route_federation_regions - GET vs POST
# ===========================================================================


class TestRouteFederationRegions:
    """Tests for the _route_federation_regions multi-method dispatcher."""

    def test_post_registers_region(self, handler, http_post):
        handler._dispatch_route("/api/v1/knowledge/mound/federation/regions", {}, http_post)
        handler._handle_register_region.assert_called_once_with(http_post)

    def test_get_lists_regions(self, handler, http_get):
        handler._dispatch_route("/api/v1/knowledge/mound/federation/regions", {}, http_get)
        handler._handle_list_regions.assert_called_once_with({})


# ===========================================================================
# _route_governance_roles - GET (None) vs POST
# ===========================================================================


class TestRouteGovernanceRoles:
    """Tests for the _route_governance_roles multi-method dispatcher."""

    def test_post_creates_role(self, handler, http_post):
        handler._dispatch_route("/api/v1/knowledge/mound/governance/roles", {}, http_post)
        # _route_governance_roles calls self._handle_create_role
        # which is a method that the governance mixin provides

    def test_get_returns_none(self, handler, http_get):
        """GET /governance/roles is not implemented -- returns None."""
        result = handler._route_governance_roles(
            "/api/v1/knowledge/mound/governance/roles", {}, http_get
        )
        assert result is None


# ===========================================================================
# _route_node_visibility - GET vs PUT
# ===========================================================================


class TestRouteNodeVisibility:
    """Tests for the _route_node_visibility multi-method dispatcher."""

    def test_get_returns_visibility(self, handler, http_get):
        handler._dispatch_route("/api/v1/knowledge/mound/nodes/n1/visibility", {}, http_get)
        handler._handle_get_visibility.assert_called_once_with("n1")

    def test_put_sets_visibility(self, handler, http_put):
        handler._dispatch_route("/api/v1/knowledge/mound/nodes/n1/visibility", {}, http_put)
        handler._handle_set_visibility.assert_called_once_with("n1", http_put)


# ===========================================================================
# _route_node_access - GET/POST/DELETE
# ===========================================================================


class TestRouteNodeAccess:
    """Tests for the _route_node_access multi-method dispatcher."""

    def test_get_lists_access_grants(self, handler, http_get):
        handler._dispatch_route("/api/v1/knowledge/mound/nodes/n1/access", {}, http_get)
        handler._handle_list_access_grants.assert_called_once_with("n1", {})

    def test_post_grants_access(self, handler, http_post):
        handler._dispatch_route("/api/v1/knowledge/mound/nodes/n1/access", {}, http_post)
        handler._handle_grant_access.assert_called_once_with("n1", http_post)

    def test_delete_revokes_access(self, handler, http_delete):
        handler._dispatch_route("/api/v1/knowledge/mound/nodes/n1/access", {}, http_delete)
        handler._handle_revoke_access.assert_called_once_with("n1", http_delete)


# ===========================================================================
# _route_curation_policy - GET/POST/PUT
# ===========================================================================


class TestRouteCurationPolicy:
    """Tests for the _route_curation_policy multi-method dispatcher."""

    def test_get_returns_policy(self, handler, http_get):
        handler._route_curation_policy(
            "/api/v1/knowledge/mound/curation/policy", {"workspace_id": "ws1"}, http_get
        )
        handler._handle_get_curation_policy.assert_called_once_with({"workspace_id": "ws1"})

    def test_post_creates_policy(self, handler, http_post):
        handler._route_curation_policy("/api/v1/knowledge/mound/curation/policy", {}, http_post)
        handler._handle_set_curation_policy.assert_called_once_with(http_post)

    def test_put_updates_policy(self, handler, http_put):
        handler._route_curation_policy("/api/v1/knowledge/mound/curation/policy", {}, http_put)
        handler._handle_set_curation_policy.assert_called_once_with(http_put)


# ===========================================================================
# Dashboard wrapper methods
# ===========================================================================


class TestDashboardWrappers:
    """Tests for the dashboard async -> sync wrapper methods."""

    def test_dashboard_health(self, handler, http_get):
        result = handler._handle_dashboard_health(http_get)
        assert result is not None

    def test_dashboard_metrics(self, handler, http_get):
        result = handler._handle_dashboard_metrics(http_get)
        assert result is not None

    def test_dashboard_metrics_reset(self, handler, http_post):
        result = handler._handle_dashboard_metrics_reset(http_post)
        assert result is not None

    def test_dashboard_adapters(self, handler, http_get):
        result = handler._handle_dashboard_adapters(http_get)
        assert result is not None

    def test_dashboard_queries(self, handler, http_get):
        result = handler._handle_dashboard_queries(http_get)
        assert result is not None

    def test_dashboard_batcher_stats(self, handler, http_get):
        result = handler._handle_dashboard_batcher_stats(http_get)
        assert result is not None


# ===========================================================================
# Stats wrapper methods (no-arg wrappers)
# ===========================================================================


class TestStatsWrappers:
    """Tests for stats wrapper methods that take no arguments."""

    def test_contradiction_stats(self, handler):
        result = handler._handle_contradiction_stats()
        assert result is not None

    def test_governance_stats(self, handler):
        result = handler._handle_governance_stats()
        assert result is not None

    def test_analytics_stats(self, handler):
        result = handler._handle_analytics_stats()
        assert result is not None

    def test_extraction_stats(self, handler):
        result = handler._handle_extraction_stats()
        assert result is not None

    def test_decay_stats(self, handler):
        result = handler._handle_decay_stats()
        assert result is not None


# ===========================================================================
# Dedup handler methods
# ===========================================================================


class TestDedupHandlers:
    """Tests for dedup handler methods."""

    def test_get_duplicate_clusters_defaults(self, handler):
        result = handler._handle_get_duplicate_clusters({})
        assert result is not None
        handler.get_duplicate_clusters.assert_called_once_with(
            workspace_id="default",
            similarity_threshold=0.9,
            limit=100,
        )

    def test_get_duplicate_clusters_custom_params(self, handler):
        handler._handle_get_duplicate_clusters(
            {
                "workspace_id": "ws-1",
                "similarity_threshold": "0.8",
                "limit": "50",
            }
        )
        handler.get_duplicate_clusters.assert_called_once_with(
            workspace_id="ws-1",
            similarity_threshold=0.8,
            limit=50,
        )

    def test_get_dedup_report_defaults(self, handler):
        handler._handle_get_dedup_report({})
        handler.get_dedup_report.assert_called_once_with(
            workspace_id="default",
            similarity_threshold=0.9,
        )

    @patch(
        "aragora.server.handlers.knowledge_base.mound.routing.validate_workspace_access_sync",
        return_value=None,
    )
    def test_merge_duplicate_cluster_success(self, mock_validate, handler):
        h = MockHTTPHandler.with_body(
            {
                "workspace_id": "default",
                "cluster_id": "cl-1",
                "primary_node_id": "n-1",
                "archive": False,
            }
        )
        result = handler._handle_merge_duplicate_cluster(h)
        assert result is not None
        handler.merge_duplicate_cluster.assert_called_once_with(
            workspace_id="default",
            cluster_id="cl-1",
            primary_node_id="n-1",
            archive=False,
        )

    @patch(
        "aragora.server.handlers.knowledge_base.mound.routing.validate_workspace_access_sync",
        return_value=None,
    )
    def test_merge_duplicate_cluster_missing_cluster_id(self, mock_validate, handler):
        h = MockHTTPHandler.with_body({"workspace_id": "default"})
        result = handler._handle_merge_duplicate_cluster(h)
        assert _status(result) == 400
        assert "cluster_id" in _body(result).get("error", "")

    @patch(
        "aragora.server.handlers.knowledge_base.mound.routing.validate_workspace_access_sync",
    )
    def test_merge_duplicate_cluster_workspace_denied(self, mock_validate, handler):
        deny_result = HandlerResult(
            status_code=403,
            content_type="application/json",
            body=json.dumps({"error": "Access denied"}).encode(),
        )
        mock_validate.return_value = deny_result
        h = MockHTTPHandler.with_body(
            {
                "workspace_id": "restricted",
                "cluster_id": "cl-1",
            }
        )
        result = handler._handle_merge_duplicate_cluster(h)
        assert _status(result) == 403

    @patch(
        "aragora.server.handlers.knowledge_base.mound.routing.validate_workspace_access_sync",
        return_value=None,
    )
    def test_auto_merge_exact_duplicates_success(self, mock_validate, handler):
        h = MockHTTPHandler.with_body(
            {
                "workspace_id": "default",
                "dry_run": False,
            }
        )
        result = handler._handle_auto_merge_exact_duplicates(h)
        assert result is not None
        handler.auto_merge_exact_duplicates.assert_called_once_with(
            workspace_id="default",
            dry_run=False,
        )

    @patch(
        "aragora.server.handlers.knowledge_base.mound.routing.validate_workspace_access_sync",
        return_value=None,
    )
    def test_auto_merge_defaults_to_dry_run(self, mock_validate, handler):
        h = MockHTTPHandler.with_body({})
        handler._handle_auto_merge_exact_duplicates(h)
        handler.auto_merge_exact_duplicates.assert_called_once_with(
            workspace_id="default",
            dry_run=True,
        )


# ===========================================================================
# Pruning handler methods
# ===========================================================================


class TestPruningHandlers:
    """Tests for pruning handler methods."""

    def test_get_prunable_items_defaults(self, handler):
        handler._handle_get_prunable_items({})
        handler.get_prunable_items.assert_called_once_with(
            workspace_id="default",
            staleness_threshold=0.9,
            min_age_days=30,
            limit=100,
        )

    def test_get_prunable_items_custom_params(self, handler):
        handler._handle_get_prunable_items(
            {
                "workspace_id": "ws-2",
                "staleness_threshold": "0.5",
                "min_age_days": "60",
                "limit": "200",
            }
        )
        handler.get_prunable_items.assert_called_once_with(
            workspace_id="ws-2",
            staleness_threshold=0.5,
            min_age_days=60,
            limit=200,
        )

    @patch(
        "aragora.server.handlers.knowledge_base.mound.routing.validate_workspace_access_sync",
        return_value=None,
    )
    def test_execute_prune_success(self, mock_validate, handler):
        h = MockHTTPHandler.with_body(
            {
                "workspace_id": "default",
                "item_ids": ["n1", "n2"],
                "action": "delete",
                "reason": "cleanup",
            }
        )
        result = handler._handle_execute_prune(h)
        assert result is not None
        handler.execute_prune.assert_called_once_with(
            workspace_id="default",
            item_ids=["n1", "n2"],
            action="delete",
            reason="cleanup",
        )

    @patch(
        "aragora.server.handlers.knowledge_base.mound.routing.validate_workspace_access_sync",
        return_value=None,
    )
    def test_execute_prune_missing_item_ids(self, mock_validate, handler):
        h = MockHTTPHandler.with_body({"workspace_id": "default"})
        result = handler._handle_execute_prune(h)
        assert _status(result) == 400
        assert "item_ids" in _body(result).get("error", "")

    @patch(
        "aragora.server.handlers.knowledge_base.mound.routing.validate_workspace_access_sync",
        return_value=None,
    )
    def test_execute_prune_defaults(self, mock_validate, handler):
        h = MockHTTPHandler.with_body(
            {
                "item_ids": ["n1"],
            }
        )
        handler._handle_execute_prune(h)
        handler.execute_prune.assert_called_once_with(
            workspace_id="default",
            item_ids=["n1"],
            action="archive",
            reason="manual_prune",
        )

    def test_auto_prune_defaults(self, handler):
        h = MockHTTPHandler.with_body({})
        handler._handle_auto_prune(h)
        handler.auto_prune.assert_called_once_with(
            workspace_id="default",
            policy_id=None,
            staleness_threshold=0.9,
            min_age_days=30,
            action="archive",
            dry_run=True,
        )

    def test_get_prune_history_defaults(self, handler):
        handler._handle_get_prune_history({})
        handler.get_prune_history.assert_called_once_with(
            workspace_id="default",
            limit=50,
            since=None,
        )

    def test_get_prune_history_with_since(self, handler):
        handler._handle_get_prune_history(
            {
                "workspace_id": "ws-1",
                "limit": "10",
                "since": "2026-01-01",
            }
        )
        handler.get_prune_history.assert_called_once_with(
            workspace_id="ws-1",
            limit=10,
            since="2026-01-01",
        )

    def test_restore_pruned_item_success(self, handler):
        h = MockHTTPHandler.with_body({"node_id": "n-1"})
        result = handler._handle_restore_pruned_item(h)
        assert result is not None
        handler.restore_pruned_item.assert_called_once_with(
            workspace_id="default",
            node_id="n-1",
        )

    def test_restore_pruned_item_missing_node_id(self, handler):
        h = MockHTTPHandler.with_body({})
        result = handler._handle_restore_pruned_item(h)
        assert _status(result) == 400
        assert "node_id" in _body(result).get("error", "")

    def test_apply_confidence_decay_defaults(self, handler):
        h = MockHTTPHandler.with_body({})
        handler._handle_apply_confidence_decay(h)
        handler.apply_confidence_decay.assert_called_once_with(
            workspace_id="default",
            decay_rate=0.01,
            min_confidence=0.1,
        )


# ===========================================================================
# Contradiction handler methods
# ===========================================================================


class TestContradictionHandlers:
    """Tests for contradiction handler methods."""

    def test_detect_contradictions(self, handler):
        h = MockHTTPHandler.with_body(
            {
                "workspace_id": "ws-1",
                "item_ids": ["a", "b"],
            }
        )
        handler._handle_detect_contradictions(h)
        handler.detect_contradictions.assert_called_once_with(
            workspace_id="ws-1",
            item_ids=["a", "b"],
        )

    def test_list_contradictions_defaults(self, handler):
        handler._handle_list_contradictions({})
        handler.list_contradictions.assert_called_once_with(
            workspace_id=None,
            min_severity=None,
        )

    def test_list_contradictions_with_filters(self, handler):
        handler._handle_list_contradictions(
            {
                "workspace_id": "ws-1",
                "min_severity": "HIGH",
            }
        )
        handler.list_contradictions.assert_called_once_with(
            workspace_id="ws-1",
            min_severity="HIGH",
        )

    def test_resolve_contradiction_success(self, handler):
        h = MockHTTPHandler.with_body(
            {
                "strategy": "merge",
                "resolved_by": "admin",
                "notes": "Merged A into B",
            }
        )
        handler._handle_resolve_contradiction("ctr-1", h)
        handler.resolve_contradiction.assert_called_once_with(
            contradiction_id="ctr-1",
            strategy="merge",
            resolved_by="admin",
            notes="Merged A into B",
        )

    def test_resolve_contradiction_missing_strategy(self, handler):
        h = MockHTTPHandler.with_body({"resolved_by": "admin"})
        result = handler._handle_resolve_contradiction("ctr-1", h)
        assert _status(result) == 400
        assert "strategy" in _body(result).get("error", "")


# ===========================================================================
# Governance handler methods
# ===========================================================================


class TestGovernanceHandlers:
    """Tests for governance handler methods."""

    def test_create_role_success(self, handler):
        h = MockHTTPHandler.with_body(
            {
                "name": "editor",
                "permissions": ["read", "write"],
                "description": "Can edit",
                "workspace_id": "ws-1",
                "created_by": "admin",
            }
        )
        handler._handle_create_role(h)
        handler.create_role.assert_called_once_with(
            name="editor",
            permissions=["read", "write"],
            description="Can edit",
            workspace_id="ws-1",
            created_by="admin",
        )

    def test_create_role_missing_name(self, handler):
        h = MockHTTPHandler.with_body({"permissions": ["read"]})
        result = handler._handle_create_role(h)
        assert _status(result) == 400
        assert "name" in _body(result).get("error", "")

    def test_assign_role_success(self, handler):
        h = MockHTTPHandler.with_body(
            {
                "user_id": "user-1",
                "role_id": "role-1",
                "workspace_id": "ws-1",
                "assigned_by": "admin",
            }
        )
        handler._handle_assign_role(h)
        handler.assign_role.assert_called_once_with(
            user_id="user-1",
            role_id="role-1",
            workspace_id="ws-1",
            assigned_by="admin",
        )

    def test_assign_role_missing_user_id(self, handler):
        h = MockHTTPHandler.with_body({"role_id": "role-1"})
        result = handler._handle_assign_role(h)
        assert _status(result) == 400

    def test_assign_role_missing_role_id(self, handler):
        h = MockHTTPHandler.with_body({"user_id": "user-1"})
        result = handler._handle_assign_role(h)
        assert _status(result) == 400

    def test_revoke_role_success(self, handler):
        h = MockHTTPHandler.with_body(
            {
                "user_id": "user-1",
                "role_id": "role-1",
                "workspace_id": "ws-1",
            }
        )
        handler._handle_revoke_role(h)
        handler.revoke_role.assert_called_once_with(
            user_id="user-1",
            role_id="role-1",
            workspace_id="ws-1",
        )

    def test_revoke_role_missing_fields(self, handler):
        h = MockHTTPHandler.with_body({})
        result = handler._handle_revoke_role(h)
        assert _status(result) == 400

    def test_get_user_permissions_with_workspace(self, handler):
        handler._handle_get_user_permissions("user-1", {"workspace_id": "ws-1"})
        handler.get_user_permissions.assert_called_once_with(
            user_id="user-1",
            workspace_id="ws-1",
        )

    def test_check_permission_success(self, handler):
        h = MockHTTPHandler.with_body(
            {
                "user_id": "user-1",
                "permission": "knowledge:write",
                "workspace_id": "ws-1",
            }
        )
        handler._handle_check_permission(h)
        handler.check_permission.assert_called_once_with(
            user_id="user-1",
            permission="knowledge:write",
            workspace_id="ws-1",
        )

    def test_check_permission_missing_user_id(self, handler):
        h = MockHTTPHandler.with_body({"permission": "knowledge:read"})
        result = handler._handle_check_permission(h)
        assert _status(result) == 400

    def test_check_permission_missing_permission(self, handler):
        h = MockHTTPHandler.with_body({"user_id": "user-1"})
        result = handler._handle_check_permission(h)
        assert _status(result) == 400

    def test_query_audit_defaults(self, handler):
        handler._handle_query_audit({})
        handler.query_audit_trail.assert_called_once_with(
            actor_id=None,
            action=None,
            workspace_id=None,
            limit=100,
        )

    def test_query_audit_with_filters(self, handler):
        handler._handle_query_audit(
            {
                "actor_id": "user-1",
                "action": "create",
                "workspace_id": "ws-1",
                "limit": "50",
            }
        )
        handler.query_audit_trail.assert_called_once_with(
            actor_id="user-1",
            action="create",
            workspace_id="ws-1",
            limit=50,
        )

    def test_get_user_activity_defaults(self, handler):
        handler._handle_get_user_activity("user-1", {})
        handler.get_user_activity.assert_called_once_with(
            user_id="user-1",
            days=30,
        )

    def test_get_user_activity_with_days(self, handler):
        handler._handle_get_user_activity("user-1", {"days": "7"})
        handler.get_user_activity.assert_called_once_with(
            user_id="user-1",
            days=7,
        )


# ===========================================================================
# Analytics handler methods
# ===========================================================================


class TestAnalyticsHandlers:
    """Tests for analytics handler methods."""

    def test_analyze_coverage_defaults(self, handler):
        handler._handle_analyze_coverage({})
        handler.analyze_coverage.assert_called_once_with(
            workspace_id="default",
            stale_threshold_days=90,
        )

    def test_analyze_usage_defaults(self, handler):
        handler._handle_analyze_usage({})
        handler.analyze_usage.assert_called_once_with(
            workspace_id="default",
            days=30,
        )

    def test_record_usage_event_success(self, handler):
        h = MockHTTPHandler.with_body(
            {
                "event_type": "query",
                "item_id": "n-1",
                "user_id": "user-1",
                "workspace_id": "ws-1",
                "query": "test query",
            }
        )
        handler._handle_record_usage_event(h)
        handler.record_usage_event.assert_called_once_with(
            event_type="query",
            item_id="n-1",
            user_id="user-1",
            workspace_id="ws-1",
            query="test query",
        )

    def test_record_usage_event_missing_event_type(self, handler):
        h = MockHTTPHandler.with_body({"item_id": "n-1"})
        result = handler._handle_record_usage_event(h)
        assert _status(result) == 400
        assert "event_type" in _body(result).get("error", "")

    def test_capture_quality_snapshot(self, handler):
        h = MockHTTPHandler.with_body({"workspace_id": "ws-1"})
        handler._handle_capture_quality_snapshot(h)
        handler.capture_quality_snapshot.assert_called_once_with(
            workspace_id="ws-1",
        )

    def test_get_quality_trend_defaults(self, handler):
        handler._handle_get_quality_trend({})
        handler.get_quality_trend.assert_called_once_with(
            workspace_id="default",
            days=30,
        )


# ===========================================================================
# Extraction handler methods
# ===========================================================================


class TestExtractionHandlers:
    """Tests for extraction handler methods."""

    def test_extract_from_debate_success(self, handler):
        h = MockHTTPHandler.with_body(
            {
                "debate_id": "dbt-1",
                "messages": [{"role": "agent", "content": "Hello"}],
                "consensus_text": "We agree",
                "topic": "Test topic",
            }
        )
        handler._handle_extract_from_debate(h)
        handler.extract_from_debate.assert_called_once_with(
            debate_id="dbt-1",
            messages=[{"role": "agent", "content": "Hello"}],
            consensus_text="We agree",
            topic="Test topic",
        )

    def test_extract_from_debate_missing_debate_id(self, handler):
        h = MockHTTPHandler.with_body(
            {
                "messages": [{"role": "agent", "content": "Hello"}],
            }
        )
        result = handler._handle_extract_from_debate(h)
        assert _status(result) == 400
        assert "debate_id" in _body(result).get("error", "")

    def test_extract_from_debate_missing_messages(self, handler):
        h = MockHTTPHandler.with_body({"debate_id": "dbt-1"})
        result = handler._handle_extract_from_debate(h)
        assert _status(result) == 400
        assert "messages" in _body(result).get("error", "")

    def test_extract_from_debate_empty_messages(self, handler):
        h = MockHTTPHandler.with_body(
            {
                "debate_id": "dbt-1",
                "messages": [],
            }
        )
        result = handler._handle_extract_from_debate(h)
        assert _status(result) == 400

    def test_promote_extracted_defaults(self, handler):
        h = MockHTTPHandler.with_body({})
        handler._handle_promote_extracted(h)
        handler.promote_extracted_knowledge.assert_called_once_with(
            workspace_id="default",
            min_confidence=0.6,
        )


# ===========================================================================
# Confidence decay handler methods
# ===========================================================================


class TestConfidenceDecayHandlers:
    """Tests for confidence decay handler methods."""

    def test_apply_confidence_decay_new_defaults(self, handler):
        h = MockHTTPHandler.with_body({})
        handler._handle_apply_confidence_decay_new(h)
        handler.apply_confidence_decay_endpoint.assert_called_once_with(
            workspace_id="default",
            force=False,
        )

    def test_apply_confidence_decay_new_force(self, handler):
        h = MockHTTPHandler.with_body(
            {
                "workspace_id": "ws-1",
                "force": True,
            }
        )
        handler._handle_apply_confidence_decay_new(h)
        handler.apply_confidence_decay_endpoint.assert_called_once_with(
            workspace_id="ws-1",
            force=True,
        )

    def test_record_confidence_event_success(self, handler):
        h = MockHTTPHandler.with_body(
            {
                "item_id": "n-1",
                "event": "validation_pass",
                "reason": "Passed all checks",
            }
        )
        handler._handle_record_confidence_event(h)
        handler.record_confidence_event.assert_called_once_with(
            item_id="n-1",
            event="validation_pass",
            reason="Passed all checks",
        )

    def test_record_confidence_event_missing_item_id(self, handler):
        h = MockHTTPHandler.with_body({"event": "validation_pass"})
        result = handler._handle_record_confidence_event(h)
        assert _status(result) == 400
        assert "item_id" in _body(result).get("error", "")

    def test_record_confidence_event_missing_event(self, handler):
        h = MockHTTPHandler.with_body({"item_id": "n-1"})
        result = handler._handle_record_confidence_event(h)
        assert _status(result) == 400
        assert "event" in _body(result).get("error", "")

    def test_get_confidence_history_defaults(self, handler):
        handler._handle_get_confidence_history({})
        handler.get_confidence_history.assert_called_once_with(
            item_id=None,
            event_type=None,
            limit=100,
        )

    def test_get_confidence_history_with_filters(self, handler):
        handler._handle_get_confidence_history(
            {
                "item_id": "n-1",
                "event_type": "decay",
                "limit": "25",
            }
        )
        handler.get_confidence_history.assert_called_once_with(
            item_id="n-1",
            event_type="decay",
            limit=25,
        )


# ===========================================================================
# _invoke_handler signature dispatch
# ===========================================================================


class TestInvokeHandlerSignatures:
    """Tests for the _invoke_handler signature dispatch logic."""

    def test_signature_none_no_args(self, handler):
        """Handlers with 'none' signature get called with no args."""
        handler._dispatch_route(
            "/api/v1/knowledge/mound/global/workspace-id", {}, MockHTTPHandler()
        )
        handler._handle_get_system_workspace_id.assert_called_once_with()

    def test_signature_q_gets_query_params(self, handler):
        """Handlers with 'q' signature get called with (query_params)."""
        qp = {"workspace_id": "ws-1"}
        handler._dispatch_route("/api/v1/knowledge/mound/stats", qp, MockHTTPHandler())
        handler._handle_mound_stats.assert_called_once_with(qp)

    def test_signature_h_gets_handler(self, handler):
        """Handlers with default 'h' signature get called with (handler)."""
        h = MockHTTPHandler.with_method("POST")
        handler._dispatch_route("/api/v1/knowledge/mound/query", {}, h)
        handler._handle_mound_query.assert_called_once_with(h)

    def test_signature_qh_gets_query_and_handler(self, handler):
        """Handlers with 'qh' signature get called with (query_params, handler)."""
        qp = {"limit": "10"}
        h = MockHTTPHandler()
        handler._dispatch_route("/api/v1/knowledge/mound/shared-with-me", qp, h)
        handler._handle_shared_with_me.assert_called_once_with(qp, h)

    def test_signature_pqh_gets_path_query_handler(self, handler):
        """Handlers with 'pqh' signature get (path, query_params, handler)."""
        qp = {"limit": "10"}
        h = MockHTTPHandler.with_method("POST")
        handler._dispatch_route("/api/v1/knowledge/mound/nodes", qp, h)
        # _route_nodes has 'pqh' signature, so it gets (path, qp, handler)
        # internally it then dispatches to _handle_create_node
        handler._handle_create_node.assert_called_once_with(h)

    def test_signature_id_gets_entity_id(self, handler):
        """Handlers with 'id' signature get called with (entity_id)."""
        handler._dispatch_route("/api/v1/knowledge/mound/nodes/test-node-id", {}, MockHTTPHandler())
        handler._handle_get_node.assert_called_once_with("test-node-id")

    def test_signature_id_q_gets_entity_and_query(self, handler):
        """Handlers with 'id_q' signature get (entity_id, query_params)."""
        qp = {"depth": "3"}
        handler._dispatch_route(
            "/api/v1/knowledge/mound/graph/test-node/lineage", qp, MockHTTPHandler()
        )
        handler._handle_graph_lineage.assert_called_once_with("test-node", qp)

    def test_signature_id_h_gets_entity_and_handler(self, handler):
        """Handlers with 'id_h' signature get (entity_id, handler)."""
        h = MockHTTPHandler.with_method("POST")
        handler._dispatch_route("/api/v1/knowledge/mound/revalidate/reval-node", {}, h)
        handler._handle_revalidate_node.assert_called_once_with("reval-node", h)


# ===========================================================================
# _HANDLER_SIGNATURES registry
# ===========================================================================


class TestHandlerSignaturesRegistry:
    """Tests for the module-level _HANDLER_SIGNATURES dict."""

    def test_known_none_signatures(self):
        assert _HANDLER_SIGNATURES["_handle_get_system_workspace_id"] == "none"
        assert _HANDLER_SIGNATURES["_handle_contradiction_stats"] == "none"
        assert _HANDLER_SIGNATURES["_handle_governance_stats"] == "none"
        assert _HANDLER_SIGNATURES["_handle_analytics_stats"] == "none"
        assert _HANDLER_SIGNATURES["_handle_extraction_stats"] == "none"
        assert _HANDLER_SIGNATURES["_handle_decay_stats"] == "none"

    def test_known_q_signatures(self):
        assert _HANDLER_SIGNATURES["_handle_mound_stats"] == "q"
        assert _HANDLER_SIGNATURES["_handle_list_nodes"] == "q"
        assert _HANDLER_SIGNATURES["_handle_get_culture"] == "q"
        assert _HANDLER_SIGNATURES["_handle_get_stale"] == "q"
        assert _HANDLER_SIGNATURES["_handle_export_d3"] == "q"
        assert _HANDLER_SIGNATURES["_handle_export_graphml"] == "q"

    def test_known_qh_signatures(self):
        assert _HANDLER_SIGNATURES["_handle_shared_with_me"] == "qh"
        assert _HANDLER_SIGNATURES["_handle_my_shares"] == "qh"
        assert _HANDLER_SIGNATURES["_handle_query_global"] == "qh"

    def test_known_pqh_signatures(self):
        assert _HANDLER_SIGNATURES["_route_nodes"] == "pqh"
        assert _HANDLER_SIGNATURES["_route_share"] == "pqh"
        assert _HANDLER_SIGNATURES["_route_global"] == "pqh"

    def test_known_id_signatures(self):
        assert _HANDLER_SIGNATURES["_handle_get_node"] == "id"

    def test_known_id_q_signatures(self):
        assert _HANDLER_SIGNATURES["_handle_get_node_relationships"] == "id_q"
        assert _HANDLER_SIGNATURES["_handle_graph_lineage"] == "id_q"
        assert _HANDLER_SIGNATURES["_handle_graph_related"] == "id_q"
        assert _HANDLER_SIGNATURES["_handle_graph_traversal"] == "id_q"

    def test_known_id_h_signatures(self):
        assert _HANDLER_SIGNATURES["_handle_revalidate_node"] == "id_h"
        assert _HANDLER_SIGNATURES["_handle_set_visibility"] == "id_h"
        assert _HANDLER_SIGNATURES["_handle_resolve_contradiction"] == "id_h"

    def test_known_id_qh_signatures(self):
        assert _HANDLER_SIGNATURES["_route_node_visibility"] == "id_qh"
        assert _HANDLER_SIGNATURES["_route_node_access"] == "id_qh"


# ===========================================================================
# Edge cases and error patterns
# ===========================================================================


class TestEdgeCases:
    """Tests for edge cases in routing dispatch."""

    def test_empty_path_returns_none(self, handler, http_get):
        result = handler._dispatch_route("", {}, http_get)
        assert result is None

    def test_partial_path_returns_none(self, handler, http_get):
        result = handler._dispatch_route("/api/v1/knowledge", {}, http_get)
        assert result is None

    def test_trailing_slash_not_matched(self, handler, http_get):
        """Routes without trailing slash should not match paths with one."""
        result = handler._dispatch_route("/api/v1/knowledge/mound/stats/", {}, http_get)
        assert result is None

    def test_dynamic_node_id_with_special_chars(self, handler, http_get):
        """Node IDs can contain hyphens, underscores, etc."""
        result = handler._dispatch_route(
            "/api/v1/knowledge/mound/nodes/node-with_special.chars123", {}, http_get
        )
        assert result is not None
        handler._handle_get_node.assert_called_once_with("node-with_special.chars123")

    def test_dynamic_node_id_cannot_contain_slashes(self, handler, http_get):
        """IDs with slashes should not match the [^/]+ pattern."""
        result = handler._dispatch_route("/api/v1/knowledge/mound/nodes/a/b", {}, http_get)
        # This should not match ^/nodes/([^/]+)$ since "a/b" has a slash
        assert result is None

    def test_query_params_passed_through(self, handler, http_get):
        """Query params are forwarded to handler methods."""
        qp = {"workspace_id": "ws-1", "min_severity": "HIGH"}
        handler._dispatch_route("/api/v1/knowledge/mound/contradictions", qp, http_get)
        # _handle_list_contradictions is a real RoutingMixin method, so
        # verify the underlying async stub received the correct args.
        handler.list_contradictions.assert_called_once_with(
            workspace_id="ws-1",
            min_severity="HIGH",
        )

    def test_dashboard_routes_dispatch_via_static(self, handler, http_get):
        """Dashboard health/metrics/adapters/queries/batcher routes dispatch."""
        paths = [
            "/api/v1/knowledge/mound/dashboard/health",
            "/api/v1/knowledge/mound/dashboard/metrics",
            "/api/v1/knowledge/mound/dashboard/adapters",
            "/api/v1/knowledge/mound/dashboard/queries",
            "/api/v1/knowledge/mound/dashboard/batcher",
        ]
        for path in paths:
            result = handler._dispatch_route(path, {}, http_get)
            assert result is not None, f"Route {path} should match"

    def test_workspace_access_denial_blocks_dedup_merge(self, handler):
        """When workspace access is denied, the handler returns 403 immediately."""
        deny = HandlerResult(
            status_code=403,
            content_type="application/json",
            body=json.dumps({"error": "Forbidden"}).encode(),
        )
        with patch(
            "aragora.server.handlers.knowledge_base.mound.routing.validate_workspace_access_sync",
            return_value=deny,
        ):
            h = MockHTTPHandler.with_body(
                {
                    "workspace_id": "restricted-ws",
                    "cluster_id": "cl-1",
                }
            )
            result = handler._handle_merge_duplicate_cluster(h)
            assert _status(result) == 403
            # The actual merge method should NOT have been called
            handler.merge_duplicate_cluster.assert_not_called()

    def test_workspace_access_denial_blocks_execute_prune(self, handler):
        deny = HandlerResult(
            status_code=403,
            content_type="application/json",
            body=json.dumps({"error": "Forbidden"}).encode(),
        )
        with patch(
            "aragora.server.handlers.knowledge_base.mound.routing.validate_workspace_access_sync",
            return_value=deny,
        ):
            h = MockHTTPHandler.with_body(
                {
                    "workspace_id": "restricted-ws",
                    "item_ids": ["n1"],
                }
            )
            result = handler._handle_execute_prune(h)
            assert _status(result) == 403
            handler.execute_prune.assert_not_called()

    def test_workspace_access_denial_blocks_auto_merge(self, handler):
        deny = HandlerResult(
            status_code=403,
            content_type="application/json",
            body=json.dumps({"error": "Forbidden"}).encode(),
        )
        with patch(
            "aragora.server.handlers.knowledge_base.mound.routing.validate_workspace_access_sync",
            return_value=deny,
        ):
            h = MockHTTPHandler.with_body({"workspace_id": "restricted-ws"})
            result = handler._handle_auto_merge_exact_duplicates(h)
            assert _status(result) == 403
            handler.auto_merge_exact_duplicates.assert_not_called()
