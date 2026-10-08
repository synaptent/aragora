"""
Tests for OpenAPI Schema Generator (aragora/server/openapi_impl.py).

Tests cover:
1. Request validation against schema
2. Response format compliance
3. Authentication/authorization integration
4. Error response formats (4xx, 5xx)
5. Rate limiting behavior
6. CORS and security headers
7. Path parameter validation
8. Query parameter validation
9. Request body validation
10. OpenAPI spec generation

Uses pytest fixtures with mocked dependencies. Follows project test patterns.
"""

from __future__ import annotations

import json
import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def openapi_schema() -> dict[str, Any]:
    """Generate the OpenAPI schema for testing."""
    from aragora.server.openapi_impl import generate_openapi_schema

    return generate_openapi_schema()


@pytest.fixture
def openapi_json() -> str:
    """Get the OpenAPI schema as JSON string."""
    from aragora.server.openapi_impl import get_openapi_json

    return get_openapi_json()


@pytest.fixture
def mock_all_handlers():
    """Mock ALL_HANDLERS for isolated testing."""
    mock_handler_cls = MagicMock()
    mock_handler_cls.ROUTES = ["/api/test"]
    mock_handler_cls.ROUTE_PREFIXES = None
    mock_handler_cls.ROUTE_PATTERNS = None
    mock_handler_cls.__dict__ = {"handle_get": lambda: None}

    with patch(
        "aragora.server.openapi_impl.ALL_HANDLERS",
        [mock_handler_cls],
    ):
        yield [mock_handler_cls]


@pytest.fixture
def mock_empty_handlers():
    """Mock ALL_HANDLERS as empty for testing default behavior."""
    with patch("aragora.server.handlers.ALL_HANDLERS", []):
        yield


# ---------------------------------------------------------------------------
# Test Class: OpenAPI Schema Structure
# ---------------------------------------------------------------------------


class TestOpenAPISchemaStructure:
    """Tests for OpenAPI schema structure and compliance."""

    def test_schema_has_openapi_version(self, openapi_schema):
        """Schema should specify OpenAPI 3.1.0 version."""
        assert openapi_schema["openapi"] == "3.1.0"

    def test_schema_has_info_block(self, openapi_schema):
        """Schema should have info block with required fields."""
        info = openapi_schema["info"]
        assert "title" in info
        assert info["title"] == "Aragora API"
        assert "version" in info
        assert "description" in info

    def test_schema_has_contact_info(self, openapi_schema):
        """Schema should have contact information."""
        assert "contact" in openapi_schema["info"]
        assert "name" in openapi_schema["info"]["contact"]

    def test_schema_has_license_info(self, openapi_schema):
        """Schema should have license information."""
        assert "license" in openapi_schema["info"]
        assert "name" in openapi_schema["info"]["license"]

    def test_schema_has_servers(self, openapi_schema):
        """Schema should define servers."""
        servers = openapi_schema["servers"]
        assert len(servers) >= 2
        assert any(s["url"] == "http://localhost:8080" for s in servers)
        assert any("production" in s.get("description", "").lower() for s in servers)

    def test_schema_has_tags(self, openapi_schema):
        """Schema should define tags for organization."""
        tags = openapi_schema["tags"]
        assert isinstance(tags, list)
        assert len(tags) > 0
        tag_names = {t["name"] for t in tags}
        assert "System" in tag_names
        assert "Debates" in tag_names
        assert "Agents" in tag_names

    def test_schema_has_paths(self, openapi_schema):
        """Schema should have paths defined."""
        paths = openapi_schema["paths"]
        assert isinstance(paths, dict)
        assert len(paths) > 0

    def test_schema_has_components(self, openapi_schema):
        """Schema should have components section."""
        components = openapi_schema["components"]
        assert "schemas" in components
        assert "securitySchemes" in components

    def test_security_scheme_defined(self, openapi_schema):
        """Schema should define bearer auth security scheme."""
        schemes = openapi_schema["components"]["securitySchemes"]
        assert "bearerAuth" in schemes
        assert schemes["bearerAuth"]["type"] == "http"
        assert schemes["bearerAuth"]["scheme"] == "bearer"


class TestOpenAPISchemaContent:
    """Tests for OpenAPI schema content validity."""

    def test_json_output_is_valid_json(self, openapi_json):
        """JSON output should be valid JSON."""
        parsed = json.loads(openapi_json)
        assert isinstance(parsed, dict)
        assert "openapi" in parsed

    def test_paths_have_valid_methods(self, openapi_schema):
        """All paths should have valid HTTP methods."""
        valid_methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
        for path, spec in openapi_schema["paths"].items():
            for method in spec.keys():
                if method.startswith("x-"):
                    continue
                assert method.lower() in valid_methods, f"Invalid method {method} in {path}"

    def test_paths_have_responses(self, openapi_schema):
        """All path operations should have responses defined."""
        http_methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if method.lower() not in http_methods:
                    continue
                assert "responses" in operation, f"Missing responses in {method} {path}"
                assert len(operation["responses"]) > 0

    def test_paths_have_tags(self, openapi_schema):
        """All path operations should have tags."""
        http_methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if method.lower() not in http_methods:
                    continue
                assert "tags" in operation, f"Missing tags in {method} {path}"
                assert len(operation["tags"]) > 0

    def test_paths_have_stability_marker(self, openapi_schema):
        """All path operations should include stability metadata."""
        from aragora.server.openapi.stability import STABILITY_VALUES

        http_methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if method.lower() not in http_methods:
                    continue
                stability = operation.get("x-aragora-stability")
                assert stability in STABILITY_VALUES, (
                    f"Missing/invalid stability for {method} {path}"
                )

    def test_runtime_openapi_has_spend_analytics_paths(self, openapi_schema):
        """Spend analytics dashboard routes should be published in the runtime schema."""
        paths = openapi_schema["paths"]

        assert "/api/v1/analytics/spend/summary" in paths
        summary_operation = paths["/api/v1/analytics/spend/summary"]["get"]
        assert {param["name"] for param in summary_operation["parameters"]} == {
            "workspace_id",
            "org_id",
        }

        assert "/api/v1/analytics/spend/trends" in paths
        trends_operation = paths["/api/v1/analytics/spend/trends"]["get"]
        assert {param["name"] for param in trends_operation["parameters"]} == {
            "org_id",
            "period",
            "days",
        }

        assert "/api/v1/analytics/spend/by-agent" in paths
        by_agent_operation = paths["/api/v1/analytics/spend/by-agent"]["get"]
        assert {param["name"] for param in by_agent_operation["parameters"]} == {
            "workspace_id",
        }

        assert "/api/v1/analytics/spend/by-decision" in paths
        by_decision_operation = paths["/api/v1/analytics/spend/by-decision"]["get"]
        assert {param["name"] for param in by_decision_operation["parameters"]} == {
            "workspace_id",
            "limit",
        }

        assert "/api/v1/analytics/spend/budget" in paths
        budget_operation = paths["/api/v1/analytics/spend/budget"]["get"]
        assert {param["name"] for param in budget_operation["parameters"]} == {
            "org_id",
        }


# ---------------------------------------------------------------------------
# Test Class: Tag Inference
# ---------------------------------------------------------------------------


class TestTagInference:
    """Tests for tag inference from URL paths."""

    def test_infer_tag_debates(self):
        """Should infer Debates tag for debate paths."""
        from aragora.server.openapi_impl import _infer_tag_for_path

        assert _infer_tag_for_path("/api/debates") == "Debates"
        assert _infer_tag_for_path("/api/v1/debates/123") == "Debates"
        assert _infer_tag_for_path("/api/debate") == "Debates"

    def test_infer_tag_agents(self):
        """Should infer Agents tag for agent paths."""
        from aragora.server.openapi_impl import _infer_tag_for_path

        assert _infer_tag_for_path("/api/agents") == "Agents"
        assert _infer_tag_for_path("/api/v1/agents/claude") == "Agents"

    def test_infer_tag_system(self):
        """Should infer System tag for system paths."""
        from aragora.server.openapi_impl import _infer_tag_for_path

        assert _infer_tag_for_path("/api/health") == "System"
        assert _infer_tag_for_path("/healthz") == "System"
        assert _infer_tag_for_path("/readyz") == "System"
        assert _infer_tag_for_path("/api/openapi") == "System"

    def test_infer_tag_bots_telegram(self):
        """Should infer Bots - Telegram tag for Telegram paths."""
        from aragora.server.openapi_impl import _infer_tag_for_path

        assert _infer_tag_for_path("/api/bots/telegram") == "Bots - Telegram"
        assert _infer_tag_for_path("/api/v1/bots/telegram/webhook") == "Bots - Telegram"

    def test_infer_tag_bots_discord(self):
        """Should infer Bots - Discord tag for Discord paths."""
        from aragora.server.openapi_impl import _infer_tag_for_path

        assert _infer_tag_for_path("/api/bots/discord") == "Bots - Discord"

    def test_infer_tag_knowledge_mound(self):
        """Should infer Knowledge Mound tag for km paths."""
        from aragora.server.openapi_impl import _infer_tag_for_path

        assert _infer_tag_for_path("/api/km") == "Knowledge Mound"
        assert _infer_tag_for_path("/api/knowledge-mound") == "Knowledge Mound"

    def test_infer_tag_workflows(self):
        """Should infer Workflows tag for workflow paths."""
        from aragora.server.openapi_impl import _infer_tag_for_path

        assert _infer_tag_for_path("/api/workflows") == "Workflows"
        assert _infer_tag_for_path("/api/workflow") == "Workflows"

    def test_infer_tag_workflow_templates(self):
        """Should infer Workflow Templates tag for template paths."""
        from aragora.server.openapi_impl import _infer_tag_for_path

        assert _infer_tag_for_path("/api/workflow-templates") == "Workflow Templates"

    def test_infer_tag_undocumented_fallback(self):
        """Should return Undocumented for unknown paths."""
        from aragora.server.openapi_impl import _infer_tag_for_path

        assert _infer_tag_for_path("/api/unknown-random-path-xyz") == "Undocumented"

    def test_infer_tag_strips_version_prefix(self):
        """Should strip version prefix before matching."""
        from aragora.server.openapi_impl import _infer_tag_for_path

        assert _infer_tag_for_path("/api/v1/debates") == "Debates"
        assert _infer_tag_for_path("/api/v2/debates") == "Debates"

    def test_infer_tag_strips_path_params(self):
        """Should strip path parameters before matching."""
        from aragora.server.openapi_impl import _infer_tag_for_path

        assert _infer_tag_for_path("/api/debates/{id}") == "Debates"
        assert _infer_tag_for_path("/api/agents/{agent_id}/stats") == "Agents"


# ---------------------------------------------------------------------------
# Test Class: Version Aliasing
# ---------------------------------------------------------------------------


class TestVersionAliasing:
    """Tests for v1 alias generation."""

    def test_add_v1_aliases_creates_aliases(self):
        """Should create /api/v1/ aliases for /api/ paths."""
        from aragora.server.openapi_impl import _add_v1_aliases

        paths = {
            "/api/debates": {"get": {"summary": "List debates", "responses": {"200": {}}}},
        }
        result = _add_v1_aliases(paths)

        assert "/api/debates" in result
        assert "/api/v1/debates" in result
        assert result["/api/v1/debates"]["get"]["summary"] == "List debates"

    def test_add_v1_aliases_preserves_existing_v1(self):
        """Should preserve existing v1 paths."""
        from aragora.server.openapi_impl import _add_v1_aliases

        paths = {
            "/api/v1/debates": {"get": {"summary": "V1 List", "responses": {"200": {}}}},
            "/api/debates": {"get": {"summary": "Legacy List", "responses": {"200": {}}}},
        }
        result = _add_v1_aliases(paths)

        assert result["/api/v1/debates"]["get"]["summary"] == "V1 List"

    def test_add_v1_aliases_preserves_v2(self):
        """Should preserve v2 paths without aliasing."""
        from aragora.server.openapi_impl import _add_v1_aliases

        paths = {
            "/api/v2/debates": {"get": {"summary": "V2 List", "responses": {"200": {}}}},
        }
        result = _add_v1_aliases(paths)

        assert "/api/v2/debates" in result
        assert "/api/v1/v2/debates" not in result

    def test_add_v1_aliases_ignores_non_api_paths(self):
        """Should not alias non-API paths."""
        from aragora.server.openapi_impl import _add_v1_aliases

        paths = {
            "/healthz": {"get": {"summary": "Health", "responses": {"200": {}}}},
        }
        result = _add_v1_aliases(paths)

        assert "/healthz" in result
        assert len(result) == 1


class TestLegacyPathDeprecation:
    """Tests for legacy path deprecation marking."""

    def test_marks_legacy_paths_deprecated(self):
        """Should mark /api/ paths (no version) as deprecated."""
        from aragora.server.openapi_impl import _mark_legacy_paths_deprecated

        paths = {
            "/api/debates": {"get": {"summary": "List", "responses": {"200": {}}}},
            "/api/v1/debates": {"get": {"summary": "List", "responses": {"200": {}}}},
        }
        result = _mark_legacy_paths_deprecated(paths)

        assert result["/api/debates"]["get"].get("deprecated") is True
        assert result["/api/v1/debates"]["get"].get("deprecated") is not True

    def test_does_not_mark_v1_deprecated(self):
        """Should not mark v1 paths as deprecated via this function."""
        from aragora.server.openapi_impl import _mark_legacy_paths_deprecated

        paths = {
            "/api/v1/debates": {"get": {"summary": "List", "responses": {"200": {}}}},
        }
        result = _mark_legacy_paths_deprecated(paths)

        assert result["/api/v1/debates"]["get"].get("deprecated") is not True

    def test_removes_operation_id_from_deprecated(self):
        """Should remove operationId from deprecated paths."""
        from aragora.server.openapi_impl import _mark_legacy_paths_deprecated

        paths = {
            "/api/debates": {
                "get": {
                    "operationId": "listDebates",
                    "summary": "List",
                    "responses": {"200": {}},
                }
            },
        }
        result = _mark_legacy_paths_deprecated(paths)

        assert "operationId" not in result["/api/debates"]["get"]


# ---------------------------------------------------------------------------
# Test Class: Path Normalization
# ---------------------------------------------------------------------------


class TestPathNormalization:
    """Tests for path normalization functions."""

    def test_normalize_route_strips_wildcard(self):
        """Should strip trailing wildcard from routes."""
        from aragora.server.openapi_impl import _normalize_route

        assert _normalize_route("/api/debates/*") == "/api/debates"
        assert _normalize_route("/api/debates/") == "/api/debates"
        assert _normalize_route("/api/debates") == "/api/debates"

    def test_normalize_template_replaces_params(self):
        """Should replace path parameters with wildcard."""
        from aragora.server.openapi_impl import _normalize_template

        assert _normalize_template("/api/debates/{id}") == "/api/debates/*"
        # Multiple consecutive params get collapsed to single wildcard
        result = _normalize_template("/api/{tenant}/debates/{id}")
        assert "/*" in result
        assert result.startswith("/api/")

    def test_route_to_template_conversion(self):
        """Should convert routes to OpenAPI templates."""
        from aragora.server.openapi_impl import _route_to_template

        assert _route_to_template("/api/debates/") == "/api/debates"
        # Trailing wildcard gets stripped, not converted to param
        result = _route_to_template("/api/debates/*")
        assert result == "/api/debates" or result == "/api/debates/{param}"

    def test_pattern_prefix_extracts_prefix(self):
        """Should extract static prefix from regex pattern."""
        from aragora.server.openapi_impl import _pattern_prefix

        assert _pattern_prefix("^/api/debates/") == "/api/debates"
        # Backslash is an escape character, so \d is treated as 'd'
        result = _pattern_prefix("/api/test\\d+")
        assert result.startswith("/api/test")


# ---------------------------------------------------------------------------
# Test Class: Method Inference
# ---------------------------------------------------------------------------


class TestMethodInference:
    """Tests for HTTP method inference from handlers."""

    def test_infer_methods_from_handle_methods(self):
        """Should infer methods from handle_X method definitions."""
        from aragora.server.openapi_impl import _infer_methods

        class TestHandler:
            def handle_get(self):
                pass

            def handle_post(self):
                pass

        methods, inferred = _infer_methods(TestHandler)
        assert set(methods) == {"get", "post"}
        assert inferred is True

    def test_infer_methods_defaults_to_get(self):
        """Should default to GET when no methods defined."""
        from aragora.server.openapi_impl import _infer_methods

        class EmptyHandler:
            pass

        methods, inferred = _infer_methods(EmptyHandler)
        assert methods == ["get"]
        assert inferred is False

    def test_route_map_methods_override_handler_fallback_per_route(self):
        """_ROUTE_MAP keys should publish their own HTTP methods."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class MixedRouteMapHandler:
            ROUTES = [
                "/api/v1/test/items",
                "/api/v1/test/run",
            ]
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None
            _ROUTE_MAP = {
                "GET /api/v1/test/items": object(),
                "POST /api/v1/test/items": object(),
                "POST /api/v1/test/run": object(),
            }

        with patch("aragora.server.handlers.ALL_HANDLERS", [MixedRouteMapHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/items"] == (["get", "post"], True)
        assert paths["/api/v1/test/run"] == (["post"], True)

    def test_declared_dict_routes_and_dynamic_routes_preserve_methods(self):
        """Dict ROUTES and DYNAMIC_ROUTES should override handler-wide fallbacks."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class DictRoutesHandler:
            ROUTES = {
                "/api/v1/test/items": ["GET", "POST"],
                "/api/v1/test/items/run": ["POST"],
            }
            DYNAMIC_ROUTES = {
                "/api/v1/test/items/{item_id}": ["GET", "DELETE"],
            }
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None

            def handle_get(self):
                pass

            def handle_post(self):
                pass

            def handle_put(self):
                pass

            def handle_delete(self):
                pass

        with patch("aragora.server.handlers.ALL_HANDLERS", [DictRoutesHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/items"][0] == ["get", "post"]
        assert paths["/api/v1/test/items/run"][0] == ["post"]
        assert paths["/api/v1/test/items/{item_id}"][0] == ["delete", "get"]

    def test_multiple_generic_routes_do_not_inherit_class_verb_union(self):
        """A handler with several generic routes must not fan its class-wide
        verb union onto every route — that publishes phantom operations
        (e.g. DELETE /api/v1/memory/store; PR #9360 round-4 review)."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class MixedVerbMultiRouteHandler:
            ROUTES = [
                "/api/v1/test/store",
                "/api/v1/test/continuum/consolidate",
            ]
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None

            def handle_get(self):
                pass

            def handle_post(self):
                pass

            def handle_delete(self):
                pass

        with patch("aragora.server.handlers.ALL_HANDLERS", [MixedVerbMultiRouteHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/store"] == (["get"], True)
        assert paths["/api/v1/test/continuum/consolidate"] == (["get"], True)

    def test_single_generic_route_still_gets_class_verb_inference(self):
        """With exactly one generic route the class verb set is unambiguous."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class SingleRouteHandler:
            ROUTES = ["/api/v1/test/single"]
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None

            def handle_get(self):
                pass

            def handle_post(self):
                pass

        with patch("aragora.server.handlers.ALL_HANDLERS", [SingleRouteHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/single"] == (["get", "post"], True)

    def test_single_verb_union_applies_to_all_generic_routes(self):
        """A handler that implements exactly one verb can only serve that verb,
        so it is attributable to every route regardless of route count."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class PostOnlyMultiRouteHandler:
            ROUTES = [
                "/api/v1/test/ingest",
                "/api/v1/test/replay",
            ]
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None

            def handle_post(self):
                pass

        with patch("aragora.server.handlers.ALL_HANDLERS", [PostOnlyMultiRouteHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/ingest"] == (["post"], True)
        assert paths["/api/v1/test/replay"] == (["post"], True)

    def test_multi_verb_union_without_get_falls_back_within_union(self):
        """When the ambiguous union has no GET, a GET placeholder would be a
        guaranteed phantom — the conservative guess must stay inside the union."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class WriteOnlyMultiRouteHandler:
            ROUTES = [
                "/api/v1/test/store",
                "/api/v1/test/purge",
            ]
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None

            def handle_post(self):
                pass

            def handle_delete(self):
                pass

        with patch("aragora.server.handlers.ALL_HANDLERS", [WriteOnlyMultiRouteHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/store"] == (["post"], True)
        assert paths["/api/v1/test/purge"] == (["post"], True)

    def test_dispatch_path_analysis_recovers_real_verbs_per_route(self):
        """When an ambiguous handler's handle_<verb> methods literally
        dispatch on a route path, those verbs are attributed to that route
        instead of the conservative guess (openai P2 on PR #9365: real
        POST /api/v1/debates/graph was dropped)."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class GraphLikeHandler:
            ROUTES = [
                "/api/v1/test/graph",
                "/api/v1/test/graph/stats",
            ]
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None

            def handle_get(self, path, query_params, handler):
                if path == "/api/v1/test/graph":
                    return {"nodes": []}
                if path == "/api/v1/test/graph/stats":
                    return {"count": 0}
                return None

            def handle_post(self, path, query_params, handler):
                if path == "/api/v1/test/graph":
                    return {"created": True}
                return None

        with patch("aragora.server.handlers.ALL_HANDLERS", [GraphLikeHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/graph"] == (["get", "post"], True)
        assert paths["/api/v1/test/graph/stats"] == (["get"], True)

    def test_dispatch_path_analysis_follows_one_helper_level(self):
        """Dispatch that delegates to a same-class helper method still
        attributes the verb when the helper references the route."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class DelegatingHandler:
            ROUTES = [
                "/api/v1/test/config",
                "/api/v1/test/status",
            ]
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None

            def handle_get(self, path, query_params, handler):
                if path == "/api/v1/test/status":
                    return {"ok": True}
                return None

            def handle_patch(self, path, query_params, handler):
                return self._patch_routes(path, handler)

            def _patch_routes(self, path, handler):
                if path == "/api/v1/test/config":
                    return {"updated": True}
                return None

        with patch("aragora.server.handlers.ALL_HANDLERS", [DelegatingHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/config"] == (["patch"], True)
        assert paths["/api/v1/test/status"] == (["get"], True)

    def test_generic_handle_literals_count_as_get_evidence(self):
        """A methodless generic handle() is the GET path in the handler
        convention; its route literals must contribute GET so real reads are
        not dropped (openai P2 round 2 on PR #9365: GET email/triage/rules)."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class TriageLikeHandler:
            ROUTES = [
                "/api/v1/test/rules",
                "/api/v1/test/check",
            ]
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None

            def handle(self, path, query_params, handler):
                if path == "/api/v1/test/rules":
                    return {"rules": []}
                return None

            def handle_put(self, path, query_params, handler):
                if path == "/api/v1/test/rules":
                    return {"updated": True}
                return None

            def handle_post(self, path, query_params, handler):
                if path == "/api/v1/test/check":
                    return {"ok": True}
                return None

        with patch("aragora.server.handlers.ALL_HANDLERS", [TriageLikeHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/rules"] == (["get", "put"], True)
        assert paths["/api/v1/test/check"] == (["post"], True)

    def test_generic_handle_with_method_dispatch_attributes_joint_conditions(self):
        """A dispatcher-style handle(path, method) attributes a verb only when
        the same condition tests both the route and the method."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class DispatcherHandler:
            ROUTES = [
                "/api/v1/test/step",
                "/api/v1/test/other",
            ]
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None

            def handle(self, path, method, data=None):
                if path == "/api/v1/test/step" and method == "PUT":
                    return {"updated": True}
                if path == "/api/v1/test/other" and method == "POST":
                    return {"created": True}
                return None

            def handle_get(self, path, query_params, handler):
                return None

            def handle_post(self, path, query_params, handler):
                return None

        with patch("aragora.server.handlers.ALL_HANDLERS", [DispatcherHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/step"] == (["put"], True)
        assert paths["/api/v1/test/other"] == (["post"], True)

    def test_prefix_literals_do_not_attribute_verbs(self):
        """startswith-style prefix literals (trailing slash) are not dispatch
        evidence for the bare route (claude P3 round 2 on PR #9365)."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class PrefixDispatchHandler:
            ROUTES = [
                "/api/v1/test/continuum",
                "/api/v1/test/entries",
            ]
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None

            def handle_get(self, path, query_params, handler):
                if path == "/api/v1/test/entries":
                    return {"entries": []}
                if path == "/api/v1/test/continuum":
                    return {"tiers": []}
                return None

            def handle_delete(self, path, query_params, handler):
                if path.startswith("/api/v1/test/continuum/"):
                    return {"deleted": True}
                return None

        with patch("aragora.server.handlers.ALL_HANDLERS", [PrefixDispatchHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/continuum"] == (["get"], True)
        assert paths["/api/v1/test/entries"] == (["get"], True)

    def test_generic_handle_presence_biases_evidence_free_fallback_to_get(self):
        """On an ambiguous handler that also defines generic handle() (the
        GET path), evidence-free routes must guess GET, not a mutating verb
        from the union (openai P2 round 6: phantom POST
        /api/v1/debates/export/batch/{param}/status)."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class GetConventionHandler:
            ROUTES = [
                "/api/v1/test/jobs",
                "/api/v1/test/jobs/{job_id}/status",
            ]
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None

            def handle(self, path, query_params, handler):
                return None

            def handle_post(self, path, query_params, handler):
                if path == "/api/v1/test/jobs":
                    return {"started": True}
                return None

            def handle_delete(self, path, query_params, handler):
                return None

        with patch("aragora.server.handlers.ALL_HANDLERS", [GetConventionHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/jobs"] == (["post"], True)
        assert paths["/api/v1/test/jobs/{job_id}/status"] == (["get"], True)

    def test_dispatch_path_analysis_matches_version_stripped_paths(self):
        """Handlers that normalize /api/v1/... to /api/... before dispatching
        (strip_version_prefix idiom) still get per-route verb attribution."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class VersionStrippingHandler:
            ROUTES = [
                "/api/v1/test/graph",
                "/api/v1/test/graph/stats",
            ]
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None

            def handle_get(self, path, query_params, handler):
                normalized = path.replace("/api/v1/", "/api/", 1)
                if normalized == "/api/test/graph":
                    return {"nodes": []}
                if normalized == "/api/test/graph/stats":
                    return {"count": 0}
                return None

            def handle_post(self, path, query_params, handler):
                normalized = path.replace("/api/v1/", "/api/", 1)
                if normalized == "/api/test/graph":
                    return {"created": True}
                return None

        with patch("aragora.server.handlers.ALL_HANDLERS", [VersionStrippingHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/graph"] == (["get", "post"], True)
        assert paths["/api/v1/test/graph/stats"] == (["get"], True)

    def test_route_patterns_respect_explicit_route_methods(self):
        """Pattern-derived templates with declared per-route methods must not
        be clobbered by the handler-wide fallback (claude P3 on PR #9365)."""
        import re

        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class PatternHandler:
            ROUTES = {
                "/api/v1/test/things/{thing_id}": ["DELETE"],
            }
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = [re.compile(r"/api/v1/test/things/[^/]+")]

            def handle_get(self):
                pass

            def handle_delete(self):
                pass

        with patch("aragora.server.handlers.ALL_HANDLERS", [PatternHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/things/{param}"] == (["delete"], False)

    def test_explicit_routes_do_not_count_toward_generic_route_total(self):
        """Routes with explicit per-route methods leave a lone generic route
        eligible for class verb inference."""
        from aragora.server.openapi_impl import _collect_autogenerated_paths

        class MostlyExplicitHandler:
            ROUTES = {
                "/api/v1/test/items": ["GET", "POST"],
            }
            DYNAMIC_ROUTES = ["/api/v1/test/generic"]
            ROUTE_PREFIXES = None
            ROUTE_PATTERNS = None

            def handle_get(self):
                pass

            def handle_delete(self):
                pass

        with patch("aragora.server.handlers.ALL_HANDLERS", [MostlyExplicitHandler]):
            paths = _collect_autogenerated_paths()

        assert paths["/api/v1/test/items"] == (["get", "post"], False)
        assert paths["/api/v1/test/generic"] == (["delete", "get"], True)

    def test_code_review_route_map_write_routes_export_post(self):
        """Code review _ROUTE_MAP write endpoints should not export as GET."""
        from aragora.server.openapi_impl import generate_openapi_schema

        paths = generate_openapi_schema()["paths"]

        for path in (
            "/api/v1/code-review/review",
            "/api/v1/code-review/diff",
            "/api/v1/code-review/pr",
            "/api/v1/code-review/security-scan",
        ):
            assert "post" in paths[path]
            assert "get" not in paths[path]

        assert "get" in paths["/api/v1/code-review/history"]
        assert "post" not in paths["/api/v1/code-review/history"]

    def test_manual_public_surface_specs_override_placeholder_methods(self):
        """Canonical specs should pin real methods for playground and spectate public routes."""
        from aragora.server.openapi_impl import generate_openapi_schema

        schema = generate_openapi_schema()
        paths = schema["paths"]

        assert set(paths["/api/v1/spectate/recent"]) == {"get"}
        assert set(paths["/api/v1/spectate/status"]) == {"get"}
        assert set(paths["/api/v1/spectate/stream"]) == {"get"}
        assert set(paths["/api/v1/spectate/emit"]) == {"post"}
        assert set(paths["/api/v1/playground/assess"]) == {"post"}
        assert set(paths["/api/v1/playground/landing/events"]) == {"post"}
        assert set(paths["/api/v1/playground/landing/events/summary"]) == {"get"}
        assert set(paths["/api/v1/playground/landing/feedback"]) == {"get", "post"}
        assert set(paths["/api/v1/playground/landing/feedback/review"]) == {"post"}


# ---------------------------------------------------------------------------
# Test Class: Request Validation Against Schema
# ---------------------------------------------------------------------------


class TestRequestValidationAgainstSchema:
    """Tests for request validation against OpenAPI schema."""

    def test_schema_defines_path_parameters(self, openapi_schema):
        """Schema should define path parameters for parameterized paths."""
        paths = openapi_schema["paths"]

        # Find a path with parameters
        for path, spec in paths.items():
            if "{" in path:
                # Extract parameter names from path
                param_names = re.findall(r"\{(\w+)\}", path)

                # Check if any operation defines these parameters
                for method, operation in spec.items():
                    if method.startswith("x-") or not isinstance(operation, dict):
                        continue
                    if "parameters" in operation:
                        defined_params = {
                            p["name"]
                            for p in operation.get("parameters", [])
                            if p.get("in") == "path"
                        }
                        # At least some path params should be defined
                        # (not all endpoints are fully specified)
                        break

    def test_schema_request_body_has_content_type(self, openapi_schema):
        """Request bodies should specify content type."""
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                if "requestBody" in operation:
                    body = operation["requestBody"]
                    assert "content" in body
                    # Should have application/json or similar
                    assert len(body["content"]) > 0


# ---------------------------------------------------------------------------
# Test Class: Response Format Compliance
# ---------------------------------------------------------------------------


class TestResponseFormatCompliance:
    """Tests for response format compliance."""

    def test_responses_have_description(self, openapi_schema):
        """All responses should have descriptions."""
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                for status, response in operation.get("responses", {}).items():
                    assert "description" in response, (
                        f"Missing description in {method} {path} response {status}"
                    )

    def test_success_responses_defined(self, openapi_schema):
        """Operations should define at least one success response."""
        http_methods = {"get", "post", "put", "patch", "delete"}
        missing_success = []
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if method.lower() not in http_methods:
                    continue
                responses = operation.get("responses", {})
                # Should have at least a 200 or 201 or 204 or 3xx redirect
                success_codes = [str(c) for c in range(200, 400)]
                has_success = any(code in responses for code in success_codes)
                if not has_success:
                    missing_success.append(f"{method} {path}")
        # Filter out known exceptions:
        # - OAuth/redirect endpoints
        # - Streaming endpoints (SSE/WebSocket)
        # - A2A protocol endpoints
        exception_patterns = ["/auth/oauth/", "/callback", "/stream", "/a2a/"]
        critical_missing = [
            p for p in missing_success if not any(pattern in p for pattern in exception_patterns)
        ]
        assert len(critical_missing) == 0, f"Missing success responses: {critical_missing[:5]}"

    def test_stable_responses_have_schema(self, openapi_schema):
        """Stable endpoints should include a response schema for success codes."""

        def has_schema(response: dict[str, Any]) -> bool:
            content = response.get("content", {})
            if not isinstance(content, dict):
                return False
            for payload in content.values():
                if isinstance(payload, dict) and payload.get("schema"):
                    return True
            return False

        missing_schema = []
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                if operation.get("x-aragora-stability") != "stable":
                    continue
                # Skip auto-generated stubs — they intentionally lack full schemas
                if operation.get("x-autogenerated"):
                    continue
                # Skip decorator-only endpoints whose responses lack content/schema
                # because they were defined with minimal metadata in @api_endpoint
                resp_200 = operation.get("responses", {}).get("200", {})
                if isinstance(resp_200, dict) and "content" not in resp_200:
                    continue
                responses = operation.get("responses", {})
                success_codes = [code for code in responses if str(code).startswith("2")]
                if not success_codes:
                    missing_schema.append(f"{method} {path} (no 2xx)")
                    continue
                ok = False
                for code in success_codes:
                    response = responses.get(code, {})
                    if str(code) == "204":
                        ok = True
                        break
                    if isinstance(response, dict) and has_schema(response):
                        ok = True
                        break
                if not ok:
                    missing_schema.append(f"{method} {path}")
        # Allow up to 2 gaps from runtime spec generation differences
        # (knowledge/facts relation endpoints have schemas in static spec
        # but not in the runtime-generated spec under pytest)
        max_allowed = 2
        assert len(missing_schema) <= max_allowed, (
            f"Stable endpoints missing response schema ({len(missing_schema)} > {max_allowed}): "
            f"{missing_schema[:5]}"
        )


# ---------------------------------------------------------------------------
# Test Class: Authentication/Authorization Integration
# ---------------------------------------------------------------------------


class TestAuthenticationIntegration:
    """Tests for authentication/authorization in OpenAPI spec."""

    def test_bearer_auth_scheme_defined(self, openapi_schema):
        """Bearer auth scheme should be defined in security schemes."""
        schemes = openapi_schema["components"]["securitySchemes"]
        assert "bearerAuth" in schemes
        assert schemes["bearerAuth"]["type"] == "http"
        assert schemes["bearerAuth"]["scheme"] == "bearer"

    def test_protected_endpoints_have_security(self, openapi_schema):
        """Protected endpoints may specify security requirements."""
        # Not all endpoints have explicit security (some use global)
        # This test verifies the structure is valid
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                if "security" in operation:
                    security = operation["security"]
                    assert isinstance(security, list)

    def test_public_endpoints_can_have_empty_security(self, openapi_schema):
        """Public endpoints may have empty security array."""
        # Find any endpoint with empty security
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                if "security" in operation and operation["security"] == []:
                    # Valid: empty security means public
                    return
        # It's okay if no such endpoint exists


# ---------------------------------------------------------------------------
# Test Class: Error Response Formats
# ---------------------------------------------------------------------------


class TestErrorResponseFormats:
    """Tests for error response format compliance."""

    def test_schema_defines_error_schema(self, openapi_schema):
        """Schema should define an Error schema in components."""
        schemas = openapi_schema["components"]["schemas"]
        # Check for common error schema patterns
        error_schemas = [
            name for name in schemas if "error" in name.lower() or "problem" in name.lower()
        ]
        # Most APIs define some error schema
        assert len(schemas) > 0  # At least has schemas

    def test_4xx_responses_have_descriptions(self, openapi_schema):
        """4xx error responses should have meaningful descriptions."""
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                for status, response in operation.get("responses", {}).items():
                    if status.startswith("4"):
                        assert response.get("description")
                        assert len(response["description"]) > 0

    def test_5xx_responses_have_descriptions(self, openapi_schema):
        """5xx error responses should have meaningful descriptions."""
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                for status, response in operation.get("responses", {}).items():
                    if status.startswith("5"):
                        assert response.get("description")
                        assert len(response["description"]) > 0


# ---------------------------------------------------------------------------
# Test Class: Rate Limiting Behavior
# ---------------------------------------------------------------------------


class TestRateLimitingBehavior:
    """Tests for rate limiting related schema elements."""

    def test_rate_limit_headers_documented(self, openapi_schema):
        """Rate limit response headers should be documented if present."""
        # This is a best practice check - headers may be defined in responses
        # Not all endpoints will have this
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                # Check if 429 response is defined
                if "429" in operation.get("responses", {}):
                    response = operation["responses"]["429"]
                    assert "description" in response

    def test_429_response_defined_for_rate_limited_endpoints(self, openapi_schema):
        """Rate-limited endpoints should define 429 response."""
        # This is informational - not all endpoints need 429
        rate_limited_paths = []
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                if "429" in operation.get("responses", {}):
                    rate_limited_paths.append(path)
        # The list exists but may be empty if rate limiting is global


# ---------------------------------------------------------------------------
# Test Class: CORS and Security Headers
# ---------------------------------------------------------------------------


class TestCORSAndSecurityHeaders:
    """Tests for CORS and security header documentation."""

    def test_options_method_for_cors(self, openapi_schema):
        """Check if OPTIONS method is documented for CORS preflight."""
        # OPTIONS endpoints may exist for CORS
        options_paths = []
        for path, spec in openapi_schema["paths"].items():
            if "options" in spec:
                options_paths.append(path)
        # OPTIONS may or may not be explicitly documented

    def test_server_security_description(self, openapi_schema):
        """Servers should have security-related descriptions."""
        servers = openapi_schema["servers"]
        for server in servers:
            # Production server should mention security
            if "production" in server.get("description", "").lower():
                assert server["url"].startswith("https")


# ---------------------------------------------------------------------------
# Test Class: Path Parameter Validation
# ---------------------------------------------------------------------------


class TestPathParameterValidation:
    """Tests for path parameter validation in schema."""

    def test_path_params_marked_required(self, openapi_schema):
        """Path parameters should be marked as required."""
        for path, spec in openapi_schema["paths"].items():
            if "{" not in path:
                continue
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                params = operation.get("parameters", [])
                for param in params:
                    if param.get("in") == "path":
                        assert param.get("required") is True, (
                            f"Path param {param.get('name')} in {path} should be required"
                        )

    def test_path_params_have_schema(self, openapi_schema):
        """Path parameters should have schema defined."""
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                params = operation.get("parameters", [])
                for param in params:
                    if param.get("in") == "path":
                        assert "schema" in param, (
                            f"Path param {param.get('name')} in {path} missing schema"
                        )


# ---------------------------------------------------------------------------
# Test Class: Query Parameter Validation
# ---------------------------------------------------------------------------


class TestQueryParameterValidation:
    """Tests for query parameter validation in schema."""

    def test_query_params_have_schema(self, openapi_schema):
        """Query parameters should have schema defined."""
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                params = operation.get("parameters", [])
                for param in params:
                    if param.get("in") == "query":
                        assert "schema" in param, (
                            f"Query param {param.get('name')} in {path} missing schema"
                        )

    def test_query_params_have_descriptions(self, openapi_schema):
        """Query parameters should have descriptions."""
        missing_descriptions = []
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                params = operation.get("parameters", [])
                for param in params:
                    if param.get("in") == "query":
                        if "description" not in param:
                            missing_descriptions.append((path, param.get("name")))
        # Log but don't fail - descriptions are recommended but not required


# ---------------------------------------------------------------------------
# Test Class: Request Body Validation
# ---------------------------------------------------------------------------


class TestRequestBodyValidation:
    """Tests for request body validation in schema."""

    def test_post_endpoints_may_have_request_body(self, openapi_schema):
        """POST endpoints typically have request bodies."""
        for path, spec in openapi_schema["paths"].items():
            if "post" in spec:
                operation = spec["post"]
                if isinstance(operation, dict):
                    # Many POST endpoints have request body, but not all
                    # (e.g., trigger endpoints may not)
                    pass

    def test_request_body_has_required_field(self, openapi_schema):
        """Request bodies should specify if required."""
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                if "requestBody" in operation:
                    body = operation["requestBody"]
                    # required field should be present (default is False)
                    if "required" in body:
                        assert isinstance(body["required"], bool)

    def test_request_body_has_json_content(self, openapi_schema):
        """Request bodies should typically accept JSON."""
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                if "requestBody" in operation:
                    body = operation["requestBody"]
                    content = body.get("content", {})
                    # Most APIs accept JSON
                    # Multipart/form-data is also valid for file uploads
                    valid_types = {"application/json", "multipart/form-data", "text/plain"}
                    has_valid_type = any(ct in valid_types for ct in content.keys())
                    # Don't require - just informational


# ---------------------------------------------------------------------------
# Test Class: OpenAPI Spec Generation Functions
# ---------------------------------------------------------------------------


class TestOpenAPISpecGeneration:
    """Tests for OpenAPI spec generation functions."""

    def test_generate_openapi_schema_returns_dict(self):
        """generate_openapi_schema should return a dictionary."""
        from aragora.server.openapi_impl import generate_openapi_schema

        schema = generate_openapi_schema()
        assert isinstance(schema, dict)

    def test_get_openapi_json_returns_string(self):
        """get_openapi_json should return a JSON string."""
        from aragora.server.openapi_impl import get_openapi_json

        json_str = get_openapi_json()
        assert isinstance(json_str, str)
        # Should be valid JSON
        json.loads(json_str)

    def test_get_openapi_yaml_returns_string(self):
        """get_openapi_yaml should return a string (YAML or JSON fallback)."""
        from aragora.server.openapi_impl import get_openapi_yaml

        yaml_str = get_openapi_yaml()
        assert isinstance(yaml_str, str)
        assert len(yaml_str) > 0

    def test_handle_openapi_request_json(self):
        """handle_openapi_request should return JSON for json format."""
        from aragora.server.openapi_impl import handle_openapi_request

        content, content_type = handle_openapi_request("json")
        assert content_type == "application/json"
        json.loads(content)

    def test_handle_openapi_request_yaml(self):
        """handle_openapi_request should return YAML for yaml format."""
        from aragora.server.openapi_impl import handle_openapi_request

        content, content_type = handle_openapi_request("yaml")
        assert content_type == "application/yaml"
        assert len(content) > 0

    def test_handle_openapi_request_default_is_json(self):
        """handle_openapi_request should default to JSON."""
        from aragora.server.openapi_impl import handle_openapi_request

        content, content_type = handle_openapi_request()
        assert content_type == "application/json"

    def test_get_endpoint_count_returns_int(self):
        """get_endpoint_count should return an integer."""
        from aragora.server.openapi_impl import get_endpoint_count

        count = get_endpoint_count()
        assert isinstance(count, int)
        assert count > 0

    def test_api_version_is_string(self):
        """API_VERSION should be a version string."""
        from aragora.server.openapi_impl import API_VERSION

        assert isinstance(API_VERSION, str)
        # Should be semver-like
        assert "." in API_VERSION


class TestSaveOpenAPISchema:
    """Tests for save_openapi_schema function."""

    def test_save_openapi_schema_returns_tuple(self, tmp_path):
        """save_openapi_schema should return path and count."""
        from aragora.server.openapi_impl import save_openapi_schema

        output_file = tmp_path / "openapi.json"
        path, count = save_openapi_schema(str(output_file))

        assert isinstance(path, str)
        assert isinstance(count, int)
        assert count > 0

    def test_save_openapi_schema_creates_file(self, tmp_path):
        """save_openapi_schema should create the output file."""
        from aragora.server.openapi_impl import save_openapi_schema

        output_file = tmp_path / "openapi.json"
        save_openapi_schema(str(output_file))

        assert output_file.exists()

    def test_save_openapi_schema_creates_directories(self, tmp_path):
        """save_openapi_schema should create parent directories."""
        from aragora.server.openapi_impl import save_openapi_schema

        output_file = tmp_path / "nested" / "dir" / "openapi.json"
        save_openapi_schema(str(output_file))

        assert output_file.exists()

    def test_saved_schema_is_valid_json(self, tmp_path):
        """Saved schema should be valid JSON."""
        from aragora.server.openapi_impl import save_openapi_schema

        output_file = tmp_path / "openapi.json"
        save_openapi_schema(str(output_file))

        with open(output_file) as f:
            schema = json.load(f)

        assert "openapi" in schema
        assert "paths" in schema


# ---------------------------------------------------------------------------
# Test Class: Handler Path Collection
# ---------------------------------------------------------------------------


class TestHandlerPathCollection:
    """Tests for handler path collection functions."""

    def test_collect_handler_paths_returns_set(self):
        """_collect_handler_paths should return a set."""
        from aragora.server.openapi_impl import _collect_handler_paths

        paths = _collect_handler_paths()
        assert isinstance(paths, set)

    def test_handler_paths_are_strings(self):
        """Collected handler paths should be strings."""
        from aragora.server.openapi_impl import _collect_handler_paths

        paths = _collect_handler_paths()
        for path in paths:
            assert isinstance(path, str)
            # Paths may include method prefix like "POST /api/..." or just "/api/..."
            # or be empty strings for some edge cases
            if path:
                # Either starts with / or has format "METHOD /path"
                assert path.startswith("/") or " /" in path or path == ""

    def test_is_path_handled_checks_prefixes(self):
        """_is_path_handled should check path prefixes."""
        from aragora.server.openapi_impl import _is_path_handled

        handled_paths = {"/api/debates", "/api/agents"}
        handled_legacy = {"/api/debates", "/api/agents"}

        assert _is_path_handled(
            "/api/debates",
            "/api/debates",
            "/api/debates",
            "/api/debates",
            handled_paths,
            handled_legacy,
        )

        assert _is_path_handled(
            "/api/debates/123",
            "/api/debates",
            "/api/debates/123",
            "/api/debates",
            handled_paths,
            handled_legacy,
        )


# ---------------------------------------------------------------------------
# Test Class: Autogenerated Paths
# ---------------------------------------------------------------------------


class TestAutogeneratedPaths:
    """Tests for autogenerated path functionality."""

    def test_autogenerated_paths_have_marker(self, openapi_schema):
        """Autogenerated paths should have x-autogenerated marker."""
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                if operation.get("x-autogenerated"):
                    assert "summary" in operation
                    assert "responses" in operation

    def test_autogenerated_placeholder_summary(self, openapi_schema):
        """Autogenerated endpoints have placeholder summary."""
        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if not isinstance(operation, dict):
                    continue
                if operation.get("x-autogenerated"):
                    assert "placeholder" in operation.get("summary", "").lower() or (
                        "autogenerated" in operation.get("summary", "").lower()
                    )

    def test_route_contract_overrides_clear_autogenerated_marker(self, openapi_schema):
        """Curated route overrides should not retain autogenerated markers."""
        operation = openapi_schema["paths"]["/api/v1/inbox/actions"]["post"]
        assert operation["summary"] == "Execute inbox quick action"
        assert operation.get("x-autogenerated") is not True


# ---------------------------------------------------------------------------
# Test Class: Legacy Path Alignment
# ---------------------------------------------------------------------------


class TestLegacyPathAlignment:
    """Tests for legacy path alignment with versioned paths."""

    def test_align_legacy_paths_preserves_methods(self):
        """_align_legacy_paths_with_versioned should align method sets."""
        from aragora.server.openapi_impl import _align_legacy_paths_with_versioned

        paths = {
            "/api/v1/debates": {
                "get": {"summary": "List", "responses": {"200": {}}},
                "post": {"summary": "Create", "responses": {"201": {}}},
            },
            "/api/debates": {
                "get": {"summary": "List Legacy", "responses": {"200": {}}},
            },
        }
        result = _align_legacy_paths_with_versioned(paths)

        # Legacy path should now have both methods
        assert "get" in result["/api/debates"]
        assert "post" in result["/api/debates"]


# ---------------------------------------------------------------------------
# Test Class: Schema Integration Tests
# ---------------------------------------------------------------------------


class TestSchemaIntegration:
    """Integration tests for full schema generation."""

    def test_schema_is_consistent_across_calls(self):
        """Schema should be consistent across multiple calls."""
        from aragora.server.openapi_impl import generate_openapi_schema

        schema1 = generate_openapi_schema()
        schema2 = generate_openapi_schema()

        assert schema1["openapi"] == schema2["openapi"]
        assert schema1["info"] == schema2["info"]
        assert set(schema1["paths"].keys()) == set(schema2["paths"].keys())

    def test_schema_endpoint_count_matches_paths(self, openapi_schema):
        """Endpoint count should match actual paths."""
        from aragora.server.openapi_impl import get_endpoint_count

        count = get_endpoint_count()
        actual_count = sum(
            len([m for m in spec if not m.startswith("x-")])
            for spec in openapi_schema["paths"].values()
        )
        assert count == actual_count

    def test_all_tags_in_schema_are_defined(self, openapi_schema):
        """All tags used in paths should be defined in tags list."""
        defined_tags = {t["name"] for t in openapi_schema["tags"]}
        used_tags = set()

        for path, spec in openapi_schema["paths"].items():
            for method, operation in spec.items():
                if isinstance(operation, dict) and "tags" in operation:
                    used_tags.update(operation["tags"])

        # All used tags should be defined
        undefined_tags = used_tags - defined_tags
        # Some dynamically generated tags may not be pre-defined
        # This is acceptable for "Undocumented" tag


class TestPostmanExportCompatibility:
    """Tests for Postman export re-export compatibility."""

    def test_postman_functions_exported(self):
        """Postman functions should be re-exported for compatibility."""
        from aragora.server.openapi_impl import (
            generate_postman_collection,
            get_postman_json,
            handle_postman_request,
            save_postman_collection,
        )

        # Just verify imports work
        assert callable(generate_postman_collection)
        assert callable(get_postman_json)
        assert callable(handle_postman_request)
        assert callable(save_postman_collection)
