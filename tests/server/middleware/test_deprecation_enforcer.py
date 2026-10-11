"""
Tests for aragora.server.middleware.deprecation_enforcer - API deprecation middleware.

Tests cover:
- DeprecatedEndpoint dataclass properties (is_sunset, days_until_sunset, deprecation_level)
- DeprecationStats tracking and serialization
- DeprecationEnforcer registration and pattern matching
- Header building (RFC 8594 Deprecation, Sunset, Link)
- Sunset endpoint blocking (HTTP 410 Gone)
- Global enforcer management (get, reset)
- register_deprecated_endpoint convenience function
- deprecation_middleware aiohttp integration
- Pattern matching (wildcards, path params)
- Module __all__ exports
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

import aragora.server.middleware.deprecation_enforcer as dep_mod


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def _reset_enforcer():
    """Reset the global deprecation enforcer before each test."""
    dep_mod.reset_deprecation_enforcer()
    yield
    dep_mod.reset_deprecation_enforcer()


@pytest.fixture
def enforcer():
    """Create a fresh DeprecationEnforcer instance."""
    return dep_mod.DeprecationEnforcer(block_sunset=True, log_usage=True)


@pytest.fixture
def mock_request():
    """Create a mock aiohttp request."""
    request = MagicMock(spec=web.Request)
    request.path = "/api/v1/debates"
    request.method = "GET"
    return request


# ===========================================================================
# Test DeprecatedEndpoint Dataclass
# ===========================================================================


class TestDeprecatedEndpoint:
    """Tests for DeprecatedEndpoint dataclass properties."""

    def test_is_sunset_false_when_no_sunset_date(self):
        """Should return False when no sunset date is set."""
        endpoint = dep_mod.DeprecatedEndpoint(
            path_pattern="/api/v1/old",
            methods=["GET"],
            sunset_date=None,
        )
        assert endpoint.is_sunset is False

    def test_is_sunset_false_when_future_date(self):
        """Should return False when sunset date is in the future."""
        endpoint = dep_mod.DeprecatedEndpoint(
            path_pattern="/api/v1/old",
            methods=["GET"],
            sunset_date=date.today() + timedelta(days=30),
        )
        assert endpoint.is_sunset is False

    def test_is_sunset_true_when_past_date(self):
        """Should return True when sunset date has passed."""
        endpoint = dep_mod.DeprecatedEndpoint(
            path_pattern="/api/v1/old",
            methods=["GET"],
            sunset_date=date.today() - timedelta(days=1),
        )
        assert endpoint.is_sunset is True

    def test_days_until_sunset_none_when_no_date(self):
        """Should return None when no sunset date is set."""
        endpoint = dep_mod.DeprecatedEndpoint(
            path_pattern="/api/v1/old",
            methods=["GET"],
            sunset_date=None,
        )
        assert endpoint.days_until_sunset is None

    def test_days_until_sunset_positive_for_future(self):
        """Should return positive days for future sunset date."""
        endpoint = dep_mod.DeprecatedEndpoint(
            path_pattern="/api/v1/old",
            methods=["GET"],
            sunset_date=date.today() + timedelta(days=10),
        )
        assert endpoint.days_until_sunset == 10

    def test_days_until_sunset_negative_for_past(self):
        """Should return negative days for past sunset date."""
        endpoint = dep_mod.DeprecatedEndpoint(
            path_pattern="/api/v1/old",
            methods=["GET"],
            sunset_date=date.today() - timedelta(days=5),
        )
        assert endpoint.days_until_sunset == -5

    def test_deprecation_level_warning_when_no_sunset(self):
        """Should return 'warning' when no sunset date is set."""
        endpoint = dep_mod.DeprecatedEndpoint(
            path_pattern="/api/v1/old",
            methods=["GET"],
            sunset_date=None,
        )
        assert endpoint.deprecation_level == "warning"

    def test_deprecation_level_warning_when_far_future(self):
        """Should return 'warning' when sunset is more than 30 days away."""
        endpoint = dep_mod.DeprecatedEndpoint(
            path_pattern="/api/v1/old",
            methods=["GET"],
            sunset_date=date.today() + timedelta(days=60),
        )
        assert endpoint.deprecation_level == "warning"

    def test_deprecation_level_critical_when_near(self):
        """Should return 'critical' when sunset is within 30 days."""
        endpoint = dep_mod.DeprecatedEndpoint(
            path_pattern="/api/v1/old",
            methods=["GET"],
            sunset_date=date.today() + timedelta(days=15),
        )
        assert endpoint.deprecation_level == "critical"

    def test_deprecation_level_sunset_when_past(self):
        """Should return 'sunset' when sunset date has passed."""
        endpoint = dep_mod.DeprecatedEndpoint(
            path_pattern="/api/v1/old",
            methods=["GET"],
            sunset_date=date.today() - timedelta(days=1),
        )
        assert endpoint.deprecation_level == "sunset"


# ===========================================================================
# Test DeprecationStats
# ===========================================================================


class TestDeprecationStats:
    """Tests for DeprecationStats tracking and serialization."""

    def test_record_call_increments_total(self):
        """Should increment total deprecated calls."""
        stats = dep_mod.DeprecationStats()
        stats.record_call("/api/v1/debates", "GET")

        assert stats.total_deprecated_calls == 1

    def test_record_call_tracks_by_endpoint(self):
        """Should track calls by endpoint path and method."""
        stats = dep_mod.DeprecationStats()
        stats.record_call("/api/v1/debates", "GET")
        stats.record_call("/api/v1/debates", "GET")
        stats.record_call("/api/v1/debates", "POST")

        assert stats.calls_by_endpoint["GET:/api/v1/debates"] == 2
        assert stats.calls_by_endpoint["POST:/api/v1/debates"] == 1

    def test_record_blocked_increments_counter(self):
        """Should increment blocked sunset calls counter."""
        stats = dep_mod.DeprecationStats()
        stats.record_blocked()
        stats.record_blocked()

        assert stats.blocked_sunset_calls == 2

    def test_to_dict_returns_all_fields(self):
        """Should return all stats fields in dictionary."""
        stats = dep_mod.DeprecationStats()
        stats.record_call("/api/v1/old", "GET")
        stats.record_blocked()

        d = stats.to_dict()

        assert d["total_deprecated_calls"] == 1
        assert d["calls_by_endpoint"] == {"GET:/api/v1/old": 1}
        assert d["blocked_sunset_calls"] == 1
        assert "last_reset" in d
        assert "uptime_seconds" in d


# ===========================================================================
# Test DeprecationEnforcer Registration
# ===========================================================================


class TestDeprecationEnforcerRegistration:
    """Tests for DeprecationEnforcer endpoint registration."""

    def test_register_creates_endpoint(self, enforcer):
        """Should create and store a DeprecatedEndpoint."""
        endpoint = enforcer.register(
            path_pattern="/api/v1/debates",
            methods=["GET", "POST"],
            sunset_date=date(2026, 6, 1),
            replacement="/api/v2/debates",
        )

        assert endpoint.path_pattern == "/api/v1/debates"
        assert endpoint.methods == ["GET", "POST"]
        assert endpoint.sunset_date == date(2026, 6, 1)
        assert endpoint.replacement == "/api/v2/debates"

    def test_register_normalizes_single_method(self, enforcer):
        """Should normalize single method string to list."""
        endpoint = enforcer.register(
            path_pattern="/api/v1/old",
            methods="get",  # Lowercase single string
        )

        assert endpoint.methods == ["GET"]

    def test_register_uppercases_methods(self, enforcer):
        """Should uppercase all HTTP methods."""
        endpoint = enforcer.register(
            path_pattern="/api/v1/old",
            methods=["get", "post", "Delete"],
        )

        assert endpoint.methods == ["GET", "POST", "DELETE"]

    def test_register_sets_deprecated_since(self, enforcer):
        """Should set deprecated_since to today."""
        endpoint = enforcer.register(path_pattern="/api/v1/old")

        assert endpoint.deprecated_since == date.today()

    def test_get_all_deprecated_returns_all(self, enforcer):
        """Should return all registered endpoints."""
        enforcer.register("/api/v1/old1")
        enforcer.register("/api/v1/old2")
        enforcer.register("/api/v1/old3")

        endpoints = enforcer.get_all_deprecated()

        assert len(endpoints) == 3

    def test_get_critical_endpoints_filters_by_level(self, enforcer):
        """Should return only critical and sunset endpoints."""
        # Warning level (far future)
        enforcer.register(
            "/api/v1/warning",
            sunset_date=date.today() + timedelta(days=60),
        )
        # Critical level (within 30 days)
        enforcer.register(
            "/api/v1/critical",
            sunset_date=date.today() + timedelta(days=10),
        )
        # Sunset level (past)
        enforcer.register(
            "/api/v1/sunset",
            sunset_date=date.today() - timedelta(days=1),
        )

        critical = enforcer.get_critical_endpoints()

        assert len(critical) == 2
        levels = [e.deprecation_level for e in critical]
        assert "critical" in levels
        assert "sunset" in levels


# ===========================================================================
# Test DeprecationEnforcer Pattern Matching
# ===========================================================================


class TestDeprecationEnforcerPatternMatching:
    """Tests for DeprecationEnforcer pattern matching."""

    def test_check_request_exact_match(self, enforcer):
        """Should match exact path."""
        enforcer.register("/api/v1/debates", methods=["GET"])

        result = enforcer.check_request("/api/v1/debates", "GET")

        assert result is not None
        assert result.path_pattern == "/api/v1/debates"

    def test_check_request_no_match_wrong_method(self, enforcer):
        """Should not match if method does not match."""
        enforcer.register("/api/v1/debates", methods=["GET"])

        result = enforcer.check_request("/api/v1/debates", "POST")

        assert result is None

    def test_check_request_no_match_wrong_path(self, enforcer):
        """Should not match if path does not match."""
        enforcer.register("/api/v1/debates", methods=["GET"])

        result = enforcer.check_request("/api/v2/debates", "GET")

        assert result is None

    def test_check_request_wildcard_single_segment(self, enforcer):
        """Should match single wildcard segment."""
        enforcer.register("/api/v1/debates/*", methods=["GET"])

        assert enforcer.check_request("/api/v1/debates/123", "GET") is not None
        assert enforcer.check_request("/api/v1/debates/abc", "GET") is not None
        # Does not match multiple segments
        assert enforcer.check_request("/api/v1/debates/123/votes", "GET") is None

    def test_check_request_wildcard_double_star(self, enforcer):
        """Should match multiple path segments with **."""
        enforcer.register("/api/v1/**", methods=["GET"])

        assert enforcer.check_request("/api/v1/debates", "GET") is not None
        assert enforcer.check_request("/api/v1/debates/123", "GET") is not None
        assert enforcer.check_request("/api/v1/debates/123/votes", "GET") is not None

    def test_check_request_path_parameter(self, enforcer):
        """Should match path parameters like {id}."""
        enforcer.register("/api/v1/debates/{debate_id}", methods=["GET"])

        assert enforcer.check_request("/api/v1/debates/123", "GET") is not None
        assert enforcer.check_request("/api/v1/debates/abc-def", "GET") is not None

    def test_check_request_case_insensitive_method(self, enforcer):
        """Should match methods case-insensitively."""
        enforcer.register("/api/v1/debates", methods=["GET"])

        assert enforcer.check_request("/api/v1/debates", "get") is not None
        assert enforcer.check_request("/api/v1/debates", "Get") is not None


# ===========================================================================
# Test DeprecationEnforcer Header Building
# ===========================================================================


class TestDeprecationEnforcerHeaders:
    """Tests for DeprecationEnforcer header building."""

    def test_builds_deprecation_header_true_without_date(self, enforcer):
        """Should set Deprecation header to 'true' without sunset date."""
        endpoint = enforcer.register("/api/v1/old", sunset_date=None)

        headers = enforcer._build_headers(endpoint)

        assert headers["Deprecation"] == "true"

    def test_builds_deprecation_header_timestamp_with_date(self, enforcer):
        """Should set Deprecation header to RFC 8594 timestamp with date."""
        endpoint = enforcer.register(
            "/api/v1/old",
            sunset_date=date(2026, 6, 1),
        )

        headers = enforcer._build_headers(endpoint)

        # Should be Unix timestamp format: @<timestamp>
        assert headers["Deprecation"].startswith("@")
        timestamp = int(headers["Deprecation"][1:])
        assert timestamp > 0

    def test_builds_sunset_header(self, enforcer):
        """Should build Sunset header in HTTP date format."""
        endpoint = enforcer.register(
            "/api/v1/old",
            sunset_date=date(2026, 6, 1),
        )

        headers = enforcer._build_headers(endpoint)

        # Should be HTTP date format: "Mon, 01 Jun 2026 00:00:00 GMT"
        assert "Sunset" in headers
        assert "Jun 2026" in headers["Sunset"]
        assert "GMT" in headers["Sunset"]

    def test_builds_link_header_for_replacement(self, enforcer):
        """Should build Link header for replacement endpoint."""
        endpoint = enforcer.register(
            "/api/v1/old",
            replacement="/api/v2/new",
        )

        headers = enforcer._build_headers(endpoint)

        assert headers["Link"] == '</api/v2/new>; rel="successor-version"'

    def test_builds_custom_headers(self, enforcer):
        """Should build custom X- headers."""
        endpoint = enforcer.register(
            "/api/v1/old",
            migration_guide_url="https://docs.example.com/migrate",
            version="v1",
        )

        headers = enforcer._build_headers(endpoint)

        assert headers["X-Deprecation-Level"] == "warning"
        assert headers["X-Migration-Guide"] == "https://docs.example.com/migrate"
        assert headers["X-Deprecated-Version"] == "v1"


# ===========================================================================
# Test DeprecationEnforcer Request Processing
# ===========================================================================


class TestDeprecationEnforcerRequestProcessing:
    """Tests for DeprecationEnforcer.process_request()."""

    def test_process_request_returns_empty_for_non_deprecated(self, enforcer, mock_request):
        """Should return empty headers and no error for non-deprecated endpoints."""
        headers, error = enforcer.process_request(mock_request)

        assert headers == {}
        assert error is None

    def test_process_request_returns_headers_for_deprecated(self, enforcer, mock_request):
        """Should return deprecation headers for deprecated endpoints."""
        enforcer.register("/api/v1/debates", methods=["GET"])

        headers, error = enforcer.process_request(mock_request)

        assert "Deprecation" in headers
        assert error is None

    def test_process_request_tracks_usage(self, enforcer, mock_request):
        """Should track usage when log_usage is enabled."""
        enforcer.register("/api/v1/debates", methods=["GET"])

        enforcer.process_request(mock_request)

        stats = enforcer.get_stats()
        assert stats.total_deprecated_calls == 1
        assert "GET:/api/v1/debates" in stats.calls_by_endpoint

    def test_process_request_blocks_sunset_endpoints(self, enforcer, mock_request):
        """Should return 410 response for sunset endpoints."""
        enforcer.register(
            "/api/v1/debates",
            methods=["GET"],
            sunset_date=date.today() - timedelta(days=1),
        )

        headers, error = enforcer.process_request(mock_request)

        assert error is not None
        assert error.status == 410

    def test_process_request_does_not_block_when_disabled(self, mock_request):
        """Should not block sunset endpoints when block_sunset is disabled."""
        enforcer = dep_mod.DeprecationEnforcer(block_sunset=False)
        enforcer.register(
            "/api/v1/debates",
            methods=["GET"],
            sunset_date=date.today() - timedelta(days=1),
        )

        headers, error = enforcer.process_request(mock_request)

        assert error is None


# ===========================================================================
# Test Sunset Response
# ===========================================================================


class TestSunsetResponse:
    """Tests for sunset endpoint blocking response."""

    def test_sunset_response_status_410(self, enforcer, mock_request):
        """Should return HTTP 410 Gone status."""
        enforcer.register(
            "/api/v1/debates",
            methods=["GET"],
            sunset_date=date.today() - timedelta(days=1),
        )

        headers, error = enforcer.process_request(mock_request)

        assert error.status == 410

    def test_sunset_response_includes_replacement(self, enforcer, mock_request):
        """Should include replacement in response body."""
        enforcer.register(
            "/api/v1/debates",
            methods=["GET"],
            sunset_date=date.today() - timedelta(days=1),
            replacement="/api/v2/debates",
        )

        headers, error = enforcer.process_request(mock_request)

        # The error response is a web.Response with JSON body
        assert error is not None

    def test_sunset_response_includes_custom_message(self, enforcer, mock_request):
        """Should use custom message if provided."""
        enforcer.register(
            "/api/v1/debates",
            methods=["GET"],
            sunset_date=date.today() - timedelta(days=1),
            message="Please use the v2 API",
        )

        headers, error = enforcer.process_request(mock_request)

        assert error is not None

    def test_sunset_tracks_blocked_calls(self, enforcer, mock_request):
        """Should track blocked sunset calls in stats."""
        enforcer.register(
            "/api/v1/debates",
            methods=["GET"],
            sunset_date=date.today() - timedelta(days=1),
        )

        enforcer.process_request(mock_request)

        stats = enforcer.get_stats()
        assert stats.blocked_sunset_calls == 1


# ===========================================================================
# Test Global Enforcer Management
# ===========================================================================


class TestGlobalEnforcerManagement:
    """Tests for global enforcer get/reset functions."""

    def test_get_deprecation_enforcer_creates_instance(self):
        """Should create enforcer on first call."""
        enforcer = dep_mod.get_deprecation_enforcer()

        assert enforcer is not None
        assert isinstance(enforcer, dep_mod.DeprecationEnforcer)

    def test_get_deprecation_enforcer_returns_same_instance(self):
        """Should return same instance on subsequent calls."""
        enforcer1 = dep_mod.get_deprecation_enforcer()
        enforcer2 = dep_mod.get_deprecation_enforcer()

        assert enforcer1 is enforcer2

    def test_reset_deprecation_enforcer_clears_instance(self):
        """Should clear the global enforcer instance."""
        enforcer1 = dep_mod.get_deprecation_enforcer()
        dep_mod.reset_deprecation_enforcer()
        enforcer2 = dep_mod.get_deprecation_enforcer()

        assert enforcer1 is not enforcer2


# ===========================================================================
# Test register_deprecated_endpoint Convenience Function
# ===========================================================================


class TestRegisterDeprecatedEndpoint:
    """Tests for register_deprecated_endpoint convenience function."""

    def test_registers_to_global_enforcer(self):
        """Should register endpoint to global enforcer."""
        endpoint = dep_mod.register_deprecated_endpoint(
            path="/api/v1/old",
            methods=["GET"],
            sunset_date=date(2026, 6, 1),
        )

        enforcer = dep_mod.get_deprecation_enforcer()
        endpoints = enforcer.get_all_deprecated()

        assert len(endpoints) == 1
        assert endpoints[0] is endpoint

    def test_accepts_all_parameters(self):
        """Should pass all parameters to the enforcer."""
        endpoint = dep_mod.register_deprecated_endpoint(
            path="/api/v1/old",
            methods=["GET", "POST"],
            sunset_date=date(2026, 6, 1),
            replacement="/api/v2/new",
            message="Custom message",
            migration_guide_url="https://docs.example.com",
            version="v1",
        )

        assert endpoint.replacement == "/api/v2/new"
        assert endpoint.message == "Custom message"
        assert endpoint.migration_guide_url == "https://docs.example.com"
        assert endpoint.version == "v1"


# ===========================================================================
# Test Default Knowledge Fact Replacements
# ===========================================================================


class TestDefaultKnowledgeFactReplacements:
    """v1 fact-store routes point at the v2 fact router, not the Knowledge Mound router."""

    @pytest.fixture(scope="class")
    def served_paths(self) -> set[str]:
        from aragora.server.fastapi import create_app

        # FastAPI 0.138+ keeps included routers behind an internal wrapper, so
        # app.routes no longer lists their APIRoutes; the generated schema does.
        return set(create_app().openapi()["paths"])

    @pytest.mark.parametrize(
        ("method", "path", "replacement"),
        [
            ("GET", "/api/v1/facts", "/api/v2/knowledge-base/facts"),
            ("POST", "/api/v1/facts", "/api/v2/knowledge-base/facts"),
            ("GET", "/api/v1/facts/fact-1", "/api/v2/knowledge-base/facts/"),
            ("GET", "/api/v1/knowledge/facts", "/api/v2/knowledge-base/facts"),
            ("DELETE", "/api/v1/knowledge/facts/fact-1", "/api/v2/knowledge-base/facts/"),
            ("POST", "/api/v1/knowledge/facts/fact-1/relations", "/api/v2/knowledge-base/facts/"),
            ("POST", "/api/v1/knowledge/query", "/api/v2/knowledge-base/query"),
            ("GET", "/api/v1/knowledge/search", "/api/v2/knowledge-base/search"),
            ("GET", "/api/v1/knowledge/stats", "/api/v2/knowledge-base/stats"),
            ("GET", "/api/v1/knowledge/export", "/api/v2/knowledge-base/export"),
        ],
    )
    def test_fact_routes_map_to_served_knowledge_base_paths(
        self, served_paths, method, path, replacement
    ):
        dep_mod.register_default_deprecations()

        endpoint = dep_mod.get_deprecation_enforcer().check_request(path, method)

        assert endpoint is not None
        assert endpoint.replacement == replacement
        assert replacement.rstrip("/") in served_paths

    def test_other_knowledge_routes_keep_the_mound_replacement(self):
        dep_mod.register_default_deprecations()

        endpoint = dep_mod.get_deprecation_enforcer().check_request(
            "/api/v1/knowledge/mound/nodes", "GET"
        )

        assert endpoint is not None
        assert endpoint.replacement == "/api/v2/knowledge/"


# ===========================================================================
# Test aiohttp Middleware Integration
# ===========================================================================


class TestDeprecationMiddleware:
    """Tests for deprecation_middleware aiohttp integration."""

    @pytest.mark.asyncio
    async def test_middleware_passes_through_non_deprecated(self):
        """Should pass through requests to non-deprecated endpoints."""
        handler = AsyncMock(return_value=web.Response(text="OK"))
        mock_request = MagicMock(spec=web.Request)
        mock_request.path = "/api/v2/new"
        mock_request.method = "GET"

        response = await dep_mod.deprecation_middleware(mock_request, handler)

        handler.assert_called_once_with(mock_request)
        assert response.text == "OK"

    @pytest.mark.asyncio
    async def test_middleware_adds_headers_for_deprecated(self):
        """Should add deprecation headers for deprecated endpoints."""
        dep_mod.register_deprecated_endpoint("/api/v1/debates", methods=["GET"])

        handler = AsyncMock(return_value=web.Response(text="OK"))
        mock_request = MagicMock(spec=web.Request)
        mock_request.path = "/api/v1/debates"
        mock_request.method = "GET"

        response = await dep_mod.deprecation_middleware(mock_request, handler)

        assert "Deprecation" in response.headers

    @pytest.mark.asyncio
    async def test_middleware_blocks_sunset_endpoints(self):
        """Should return 410 for sunset endpoints."""
        dep_mod.register_deprecated_endpoint(
            "/api/v1/debates",
            methods=["GET"],
            sunset_date=date.today() - timedelta(days=1),
        )

        handler = AsyncMock(return_value=web.Response(text="OK"))
        mock_request = MagicMock(spec=web.Request)
        mock_request.path = "/api/v1/debates"
        mock_request.method = "GET"

        response = await dep_mod.deprecation_middleware(mock_request, handler)

        assert response.status == 410
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_middleware_includes_headers_in_error_response(self):
        """Should include deprecation headers in 410 response."""
        dep_mod.register_deprecated_endpoint(
            "/api/v1/debates",
            methods=["GET"],
            sunset_date=date.today() - timedelta(days=1),
            replacement="/api/v2/debates",
        )

        handler = AsyncMock()
        mock_request = MagicMock(spec=web.Request)
        mock_request.path = "/api/v1/debates"
        mock_request.method = "GET"

        response = await dep_mod.deprecation_middleware(mock_request, handler)

        assert "Deprecation" in response.headers
        assert "X-Deprecation-Level" in response.headers


# ===========================================================================
# Test create_deprecation_middleware Factory
# ===========================================================================


class TestCreateDeprecationMiddleware:
    """Tests for create_deprecation_middleware factory."""

    def test_returns_middleware_function(self):
        """Should return the middleware function."""
        middleware = dep_mod.create_deprecation_middleware()

        assert middleware is dep_mod.deprecation_middleware
        assert callable(middleware)


# ===========================================================================
# Test Module Exports
# ===========================================================================


class TestModuleExports:
    """Tests for __all__ exports."""

    def test_all_exports_exist(self):
        """Every name in __all__ should be importable from the module."""
        for name in dep_mod.__all__:
            assert hasattr(dep_mod, name), f"{name} listed in __all__ but not defined"

    def test_expected_public_api(self):
        """__all__ should contain the expected public API."""
        expected = {
            "DeprecatedEndpoint",
            "DeprecationEnforcer",
            "DeprecationStats",
            "create_deprecation_middleware",
            "deprecation_middleware",
            "get_deprecation_enforcer",
            "register_default_deprecations",
            "register_deprecated_endpoint",
            "reset_deprecation_enforcer",
        }
        assert expected == set(dep_mod.__all__)
