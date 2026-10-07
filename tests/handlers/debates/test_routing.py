"""Tests for debate routing handler mixin.

Tests the RoutingMixin from aragora/server/handlers/debates/routing.py:
- Route configuration constants (ROUTES, AUTH_REQUIRED_ENDPOINTS, etc.)
- build_suffix_routes() factory
- RoutingMixin._check_auth() authentication logic (JWT, API token, legacy HMAC)
- RoutingMixin._requires_auth() path matching
- RoutingMixin._check_artifact_access() public/private debate access
- RoutingMixin._dispatch_suffix_route() suffix dispatch table
- RoutingMixin._extract_debate_id() path parsing + validation
- RoutingMixin.can_handle() path matching
- Security edge cases (path traversal, invalid IDs, header injection)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Patch target for auth_config (imported lazily inside _check_auth)
_AUTH_CONFIG_TARGET = "aragora.server.auth.auth_config"


# =============================================================================
# Helpers
# =============================================================================


def _body(result) -> dict:
    """Parse HandlerResult.body bytes into dict."""
    if result is None:
        return {}
    body = result.body
    if isinstance(body, str):
        return json.loads(body)
    if isinstance(body, bytes):
        return json.loads(body.decode())
    return body


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    return result.status_code


# =============================================================================
# Handler Factories
# =============================================================================


def _make_routing_handler(
    storage=None,
    ctx=None,
    extra_methods=None,
):
    """Create a test handler incorporating the RoutingMixin."""
    from aragora.server.handlers.debates.routing import RoutingMixin

    class TestHandler(RoutingMixin):
        def __init__(self, storage, ctx, extra_methods):
            self._storage = storage
            self.ctx = ctx or {}
            # Register extra handler methods for dispatch testing
            if extra_methods:
                for name, fn in extra_methods.items():
                    setattr(self, name, fn)

        def get_storage(self):
            return self._storage

    return TestHandler(storage=storage, ctx=ctx, extra_methods=extra_methods)


def _make_mock_http_handler(
    auth_header=None,
):
    """Create a mock HTTP handler with optional auth header."""
    handler = MagicMock()
    headers = {"Content-Length": "0"}
    if auth_header is not None:
        headers["Authorization"] = auth_header
    handler.headers = headers
    return handler


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_storage():
    """Create a mock storage with default methods."""
    storage = MagicMock()
    storage.get_debate.return_value = None
    storage.is_public.return_value = False
    return storage


@pytest.fixture
def routing_handler(mock_storage):
    """Create a basic routing handler with mock storage."""
    return _make_routing_handler(storage=mock_storage)


@pytest.fixture
def mock_http_handler():
    """Create a minimal mock HTTP handler (no auth header)."""
    return _make_mock_http_handler()


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Reset rate limiters between tests."""
    try:
        from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

        reset_rate_limiters()
    except ImportError:
        pass
    yield
    try:
        from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

        reset_rate_limiters()
    except ImportError:
        pass


# =============================================================================
# Tests: Route Constants
# =============================================================================


class TestRouteConstants:
    """Test module-level route constants are well-formed."""

    def test_routes_list_is_non_empty(self):
        """ROUTES contains at least the core debate endpoints."""
        from aragora.server.handlers.debates.routing import ROUTES

        assert len(ROUTES) > 20

    def test_routes_all_start_with_api_v1(self):
        """All routes start with /api/v1/."""
        from aragora.server.handlers.debates.routing import ROUTES

        for route in ROUTES:
            assert route.startswith("/api/v1/"), f"Route {route} missing /api/v1/ prefix"

    def test_routes_contain_key_endpoints(self):
        """ROUTES includes critical debate endpoints."""
        from aragora.server.handlers.debates.routing import ROUTES

        expected = [
            "/api/v1/debate",
            "/api/v1/debates",
            "/api/v1/debates/estimate-cost",
            "/api/v1/debates/batch",
            "/api/v1/debates/queue/status",
            "/api/v1/debate-this",
            "/api/v1/search",
        ]
        for ep in expected:
            assert ep in ROUTES, f"Missing expected route: {ep}"

    def test_routes_contain_wildcard_endpoints(self):
        """ROUTES includes debate-ID wildcard endpoints."""
        from aragora.server.handlers.debates.routing import ROUTES

        wildcard_routes = [r for r in ROUTES if "*" in r]
        assert len(wildcard_routes) >= 10

    def test_auth_required_endpoints_is_list(self):
        """AUTH_REQUIRED_ENDPOINTS is a list."""
        from aragora.server.handlers.debates.routing import AUTH_REQUIRED_ENDPOINTS

        assert isinstance(AUTH_REQUIRED_ENDPOINTS, list)
        assert len(AUTH_REQUIRED_ENDPOINTS) > 0

    def test_auth_required_endpoints_contain_batch(self):
        """Batch submission requires auth."""
        from aragora.server.handlers.debates.routing import AUTH_REQUIRED_ENDPOINTS

        assert "/api/v1/debates/batch" in AUTH_REQUIRED_ENDPOINTS

    def test_auth_required_endpoints_contain_export(self):
        """Export endpoints require auth."""
        from aragora.server.handlers.debates.routing import AUTH_REQUIRED_ENDPOINTS

        assert any("/export/" in ep for ep in AUTH_REQUIRED_ENDPOINTS)

    def test_auth_required_endpoints_contain_package(self):
        """Decision package endpoints require auth."""
        from aragora.server.handlers.debates.routing import AUTH_REQUIRED_ENDPOINTS

        assert any("/package" in ep for ep in AUTH_REQUIRED_ENDPOINTS)

    def test_auth_required_endpoints_contain_fork(self):
        """Fork endpoint requires auth."""
        from aragora.server.handlers.debates.routing import AUTH_REQUIRED_ENDPOINTS

        assert "/fork" in AUTH_REQUIRED_ENDPOINTS

    def test_auth_required_endpoints_contain_followup(self):
        """Follow-up endpoint requires auth."""
        from aragora.server.handlers.debates.routing import AUTH_REQUIRED_ENDPOINTS

        assert "/followup" in AUTH_REQUIRED_ENDPOINTS

    def test_auth_required_endpoints_contain_decision_integrity(self):
        """Decision integrity endpoint requires auth."""
        from aragora.server.handlers.debates.routing import AUTH_REQUIRED_ENDPOINTS

        assert "/decision-integrity" in AUTH_REQUIRED_ENDPOINTS

    def test_allowed_export_formats(self):
        """ALLOWED_EXPORT_FORMATS contains expected formats."""
        from aragora.server.handlers.debates.routing import ALLOWED_EXPORT_FORMATS

        assert ALLOWED_EXPORT_FORMATS == {"json", "csv", "html", "txt", "md"}

    def test_allowed_export_tables(self):
        """ALLOWED_EXPORT_TABLES contains expected tables."""
        from aragora.server.handlers.debates.routing import ALLOWED_EXPORT_TABLES

        assert ALLOWED_EXPORT_TABLES == {"summary", "messages", "critiques", "votes"}

    def test_artifact_endpoints_is_set(self):
        """ARTIFACT_ENDPOINTS is a set of strings."""
        from aragora.server.handlers.debates.routing import ARTIFACT_ENDPOINTS

        assert isinstance(ARTIFACT_ENDPOINTS, set)
        assert "/messages" in ARTIFACT_ENDPOINTS
        assert "/evidence" in ARTIFACT_ENDPOINTS
        assert "/verification-report" in ARTIFACT_ENDPOINTS

    def test_id_only_methods(self):
        """ID_ONLY_METHODS contains known method names."""
        from aragora.server.handlers.debates.routing import ID_ONLY_METHODS

        assert isinstance(ID_ONLY_METHODS, set)
        assert "_get_meta_critique" in ID_ONLY_METHODS
        assert "_get_graph_stats" in ID_ONLY_METHODS
        assert "_get_followup_suggestions" in ID_ONLY_METHODS
        assert "_get_rhetorical_observations" in ID_ONLY_METHODS
        assert "_get_trickster_status" in ID_ONLY_METHODS
        assert "_get_diagnostics" in ID_ONLY_METHODS


# =============================================================================
# Tests: build_suffix_routes
# =============================================================================


class TestBuildSuffixRoutes:
    """Test the build_suffix_routes factory function."""

    def test_returns_list_of_tuples(self):
        """build_suffix_routes returns a list of 4-tuples."""
        from aragora.server.handlers.debates.routing import build_suffix_routes

        routes = build_suffix_routes()
        assert isinstance(routes, list)
        for entry in routes:
            assert len(entry) == 4
            suffix, method_name, needs_id, extra_fn = entry
            assert isinstance(suffix, str)
            assert isinstance(method_name, str)
            assert isinstance(needs_id, bool)
            assert extra_fn is None or callable(extra_fn)

    def test_all_suffixes_start_with_slash(self):
        """Every suffix starts with /."""
        from aragora.server.handlers.debates.routing import build_suffix_routes

        for suffix, _, _, _ in build_suffix_routes():
            assert suffix.startswith("/"), f"Suffix {suffix} missing leading /"

    def test_all_method_names_start_with_underscore(self):
        """All method names are private (start with _)."""
        from aragora.server.handlers.debates.routing import build_suffix_routes

        for _, method_name, _, _ in build_suffix_routes():
            assert method_name.startswith("_"), f"Method {method_name} should be private"

    def test_known_suffixes_present(self):
        """Key suffixes are present in the route table."""
        from aragora.server.handlers.debates.routing import build_suffix_routes

        suffixes = {entry[0] for entry in build_suffix_routes()}
        expected = {
            "/impasse",
            "/convergence",
            "/citations",
            "/evidence",
            "/messages",
            "/meta-critique",
            "/graph/stats",
            "/verification-report",
            "/followups",
            "/forks",
            "/summary",
            "/rhetorical",
            "/trickster",
            "/diagnostics",
        }
        assert expected.issubset(suffixes)

    def test_messages_has_extra_params_fn(self):
        """The /messages route has an extra_params_fn for pagination."""
        from aragora.server.handlers.debates.routing import build_suffix_routes

        for suffix, method_name, needs_id, extra_fn in build_suffix_routes():
            if suffix == "/messages":
                assert extra_fn is not None
                assert needs_id is True
                # Test the lambda works
                result = extra_fn("/api/v1/debates/abc/messages", {"limit": "10", "offset": "5"})
                assert "limit" in result
                assert "offset" in result
                return
        pytest.fail("/messages suffix not found")

    def test_messages_extra_params_defaults(self):
        """The /messages extra_params_fn uses defaults when no params given."""
        from aragora.server.handlers.debates.routing import build_suffix_routes

        for suffix, _, _, extra_fn in build_suffix_routes():
            if suffix == "/messages":
                result = extra_fn("/api/v1/debates/abc/messages", {})
                assert result["limit"] == 50
                assert result["offset"] == 0
                return
        pytest.fail("/messages suffix not found")

    def test_all_routes_need_debate_id(self):
        """All suffix routes need a debate ID."""
        from aragora.server.handlers.debates.routing import build_suffix_routes

        for suffix, _, needs_id, _ in build_suffix_routes():
            assert needs_id is True, f"Suffix {suffix} should need debate ID"

    def test_pre_built_suffix_routes_matches_factory(self):
        """SUFFIX_ROUTES matches build_suffix_routes() output."""
        from aragora.server.handlers.debates.routing import SUFFIX_ROUTES, build_suffix_routes

        fresh = build_suffix_routes()
        assert len(SUFFIX_ROUTES) == len(fresh)
        for (s1, m1, n1, _), (s2, m2, n2, _) in zip(SUFFIX_ROUTES, fresh):
            assert s1 == s2
            assert m1 == m2
            assert n1 == n2


# =============================================================================
# Tests: _check_auth
# =============================================================================


class TestCheckAuth:
    """Test _check_auth authentication logic."""

    def test_no_handler_returns_none(self, routing_handler):
        """None handler means no auth check possible - returns None."""
        result = routing_handler._check_auth(None)
        assert result is None

    def test_auth_disabled_returns_none(self, routing_handler, mock_http_handler):
        """When auth is globally disabled, returns None."""
        mock_config = MagicMock()
        mock_config.enabled = False
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(mock_http_handler)
        assert result is None

    def test_no_api_token_configured_returns_none(self, routing_handler, mock_http_handler):
        """When no API token is configured server-side, returns None."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = ""
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(mock_http_handler)
        assert result is None

    def test_missing_auth_header_returns_401(self, routing_handler):
        """Missing auth header returns 401."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "server-secret"
        handler = _make_mock_http_handler(auth_header=None)
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(handler)
        assert _status(result) == 401
        assert "missing" in _body(result).get("error", "").lower()

    def test_empty_bearer_token_returns_401(self, routing_handler):
        """Empty Bearer token returns 401."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "server-secret"
        handler = _make_mock_http_handler(auth_header="Bearer ")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(handler)
        assert _status(result) == 401

    def test_valid_jwt_token_returns_none(self, routing_handler):
        """Valid JWT token (3 dot-separated parts) returns None."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "server-secret"
        handler = _make_mock_http_handler(auth_header="Bearer header.payload.signature")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            with patch(
                "aragora.billing.auth.validate_access_token",
                return_value={"sub": "user-1"},
            ):
                result = routing_handler._check_auth(handler)
        assert result is None

    def test_invalid_jwt_falls_through(self, routing_handler):
        """Invalid JWT falls through to other auth methods."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "server-secret"
        mock_config.validate_token.return_value = False
        handler = _make_mock_http_handler(auth_header="Bearer bad.jwt.token")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            with patch(
                "aragora.billing.auth.validate_access_token",
                return_value=None,
            ):
                result = routing_handler._check_auth(handler)
        assert _status(result) == 401

    def test_jwt_validation_import_error_falls_through(self, routing_handler):
        """JWT import error is caught and falls through."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "server-secret"
        mock_config.validate_token.return_value = True
        handler = _make_mock_http_handler(auth_header="Bearer a.b.c")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            with patch(
                "aragora.billing.auth.validate_access_token",
                side_effect=ImportError("no billing module"),
            ):
                result = routing_handler._check_auth(handler)
        # Falls through to legacy token check; validate_token returns True
        assert result is None

    def test_api_token_with_ara_prefix_returns_none(self, routing_handler):
        """API tokens with ara_ prefix are accepted."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "server-secret"
        handler = _make_mock_http_handler(auth_header="Bearer ara_test_key_123")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(handler)
        assert result is None

    def test_valid_legacy_hmac_token_returns_none(self, routing_handler):
        """Valid legacy HMAC token returns None."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "server-secret"
        mock_config.validate_token.return_value = True
        handler = _make_mock_http_handler(auth_header="Bearer legacy-hmac-token")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(handler)
        assert result is None

    def test_invalid_legacy_hmac_token_returns_401(self, routing_handler):
        """Invalid legacy HMAC token returns 401."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "server-secret"
        mock_config.validate_token.return_value = False
        handler = _make_mock_http_handler(auth_header="Bearer bad-legacy-token")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(handler)
        assert _status(result) == 401
        assert "invalid" in _body(result).get("error", "").lower()

    def test_handler_without_headers_attribute(self, routing_handler):
        """Handler without headers attribute - no auth header extracted."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "server-secret"
        handler = MagicMock(spec=[])  # No attributes
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(handler)
        assert _status(result) == 401

    def test_non_bearer_auth_header(self, routing_handler):
        """Non-Bearer auth header fails - no token extracted."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "server-secret"
        handler = _make_mock_http_handler(auth_header="Basic dXNlcjpwYXNz")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(handler)
        assert _status(result) == 401


# =============================================================================
# Tests: _requires_auth
# =============================================================================


class TestRequiresAuth:
    """Test _requires_auth path matching."""

    def test_batch_endpoint_requires_auth(self, routing_handler):
        """Batch submission endpoint requires auth."""
        assert routing_handler._requires_auth("/api/v1/debates/batch") is True

    def test_export_endpoint_requires_auth(self, routing_handler):
        """Export endpoints require auth."""
        assert routing_handler._requires_auth("/api/v1/debates/abc/export/") is True

    def test_package_endpoint_requires_auth(self, routing_handler):
        """Decision package JSON endpoint requires auth."""
        assert routing_handler._requires_auth("/api/v1/debates/abc/package") is True

    def test_package_markdown_endpoint_requires_auth(self, routing_handler):
        """Decision package markdown endpoint requires auth."""
        assert routing_handler._requires_auth("/api/v1/debates/abc/package/markdown") is True

    def test_citations_endpoint_requires_auth(self, routing_handler):
        """Citations endpoint requires auth."""
        assert routing_handler._requires_auth("/api/v1/debates/abc/citations") is True

    def test_fork_endpoint_requires_auth(self, routing_handler):
        """Fork endpoint requires auth."""
        assert routing_handler._requires_auth("/api/v1/debates/abc/fork") is True

    def test_followup_endpoint_requires_auth(self, routing_handler):
        """Followup endpoint requires auth."""
        assert routing_handler._requires_auth("/api/v1/debates/abc/followup") is True

    def test_decision_integrity_requires_auth(self, routing_handler):
        """Decision integrity endpoint requires auth."""
        assert routing_handler._requires_auth("/api/v1/debates/abc/decision-integrity") is True

    def test_debates_list_does_not_require_auth(self, routing_handler):
        """Basic debates list does not require auth."""
        assert routing_handler._requires_auth("/api/v1/debates") is False

    def test_impasse_does_not_require_auth(self, routing_handler):
        """Impasse endpoint does not require auth."""
        assert routing_handler._requires_auth("/api/v1/debates/abc/impasse") is False

    def test_convergence_does_not_require_auth(self, routing_handler):
        """Convergence endpoint does not require auth."""
        assert routing_handler._requires_auth("/api/v1/debates/abc/convergence") is False

    def test_v2_normalization_for_batch(self, routing_handler):
        """V2 versioned paths are normalized for auth checking."""
        assert routing_handler._requires_auth("/api/v2/debates/batch") is True

    def test_unversioned_path_for_export(self, routing_handler):
        """Unversioned export path also requires auth."""
        assert routing_handler._requires_auth("/api/debates/abc/export/") is True

    def test_partial_match_in_path(self, routing_handler):
        """Auth check uses substring matching on normalized path."""
        assert routing_handler._requires_auth("/api/v1/debates/123/fork") is True

    def test_empty_path_does_not_require_auth(self, routing_handler):
        """Empty path does not require auth."""
        assert routing_handler._requires_auth("") is False

    def test_root_path_does_not_require_auth(self, routing_handler):
        """Root path does not require auth."""
        assert routing_handler._requires_auth("/") is False


# =============================================================================
# Tests: _check_artifact_access
# =============================================================================


class TestCheckArtifactAccess:
    """Test _check_artifact_access for public/private debate access control."""

    def test_non_artifact_endpoint_returns_none(self, routing_handler, mock_http_handler):
        """Non-artifact suffix returns None (no access check needed)."""
        result = routing_handler._check_artifact_access("debate-1", "/impasse", mock_http_handler)
        assert result is None

    def test_messages_artifact_public_debate(
        self, routing_handler, mock_storage, mock_http_handler
    ):
        """Public debate - /messages artifact returns None (allowed)."""
        mock_storage.is_public.return_value = True
        result = routing_handler._check_artifact_access("debate-1", "/messages", mock_http_handler)
        assert result is None

    def test_messages_artifact_private_debate_no_auth(self, routing_handler, mock_storage):
        """Private debate - /messages artifact requires auth."""
        mock_storage.is_public.return_value = False
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "secret"
        handler = _make_mock_http_handler(auth_header=None)
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_artifact_access("debate-1", "/messages", handler)
        assert _status(result) == 401

    def test_messages_artifact_private_debate_with_auth(self, routing_handler, mock_storage):
        """Private debate with valid auth returns None (allowed)."""
        mock_storage.is_public.return_value = False
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "secret"
        mock_config.validate_token.return_value = True
        handler = _make_mock_http_handler(auth_header="Bearer valid-token")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_artifact_access("debate-1", "/messages", handler)
        assert result is None

    def test_evidence_artifact_public_debate(
        self, routing_handler, mock_storage, mock_http_handler
    ):
        """Public debate - /evidence artifact returns None."""
        mock_storage.is_public.return_value = True
        result = routing_handler._check_artifact_access("debate-1", "/evidence", mock_http_handler)
        assert result is None

    def test_evidence_artifact_private_no_auth(self, routing_handler, mock_storage):
        """Private debate - /evidence requires auth."""
        mock_storage.is_public.return_value = False
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "secret"
        handler = _make_mock_http_handler(auth_header=None)
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_artifact_access("debate-1", "/evidence", handler)
        assert _status(result) == 401

    def test_verification_report_artifact(self, routing_handler, mock_storage, mock_http_handler):
        """Public debate - /verification-report returns None."""
        mock_storage.is_public.return_value = True
        result = routing_handler._check_artifact_access(
            "debate-1", "/verification-report", mock_http_handler
        )
        assert result is None

    def test_no_storage_returns_none_for_non_artifact(self, mock_http_handler):
        """Non-artifact endpoint returns None even without storage."""
        handler = _make_routing_handler(storage=None)
        result = handler._check_artifact_access("debate-1", "/impasse", mock_http_handler)
        assert result is None

    def test_storage_none_for_artifact_endpoint(self):
        """None storage for artifact endpoint - is_public call skipped."""
        handler = _make_routing_handler(storage=None)
        mock_config = MagicMock()
        mock_config.enabled = False
        http_handler = _make_mock_http_handler()
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = handler._check_artifact_access("debate-1", "/messages", http_handler)
        # storage is None, so is_public call fails with AttributeError
        # but auth is disabled, so _check_auth returns None
        # Result: None (access allowed)
        assert result is None

    def test_auth_disabled_allows_artifact_access(self, routing_handler, mock_storage):
        """Auth disabled globally allows artifact access even for private debates."""
        mock_storage.is_public.return_value = False
        mock_config = MagicMock()
        mock_config.enabled = False
        handler = _make_mock_http_handler(auth_header=None)
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_artifact_access("debate-1", "/messages", handler)
        assert result is None


# =============================================================================
# Tests: _extract_debate_id
# =============================================================================


class TestExtractDebateId:
    """Test _extract_debate_id path parsing and validation."""

    def test_standard_versioned_path(self, routing_handler):
        """Standard /api/v1/debates/{id}/suffix extracts correctly."""
        debate_id, err = routing_handler._extract_debate_id(
            "/api/v1/debates/test-debate-001/impasse"
        )
        assert debate_id == "test-debate-001"
        assert err is None

    def test_v2_versioned_path(self, routing_handler):
        """V2 versioned path is normalized and extracts correctly."""
        debate_id, err = routing_handler._extract_debate_id("/api/v2/debates/debate-v2/convergence")
        assert debate_id == "debate-v2"
        assert err is None

    def test_unversioned_path(self, routing_handler):
        """Unversioned /api/debates/{id}/suffix extracts correctly."""
        debate_id, err = routing_handler._extract_debate_id("/api/debates/my-debate/messages")
        assert debate_id == "my-debate"
        assert err is None

    def test_short_path_returns_error(self, routing_handler):
        """Path with fewer than 4 parts returns error."""
        debate_id, err = routing_handler._extract_debate_id("/api/debates")
        assert debate_id is None
        assert err == "Invalid path"

    def test_very_short_path(self, routing_handler):
        """Very short path returns error."""
        debate_id, err = routing_handler._extract_debate_id("/api")
        assert debate_id is None
        assert err == "Invalid path"

    def test_empty_path(self, routing_handler):
        """Empty path returns error."""
        debate_id, err = routing_handler._extract_debate_id("")
        assert debate_id is None
        assert err == "Invalid path"

    def test_root_path(self, routing_handler):
        """Root path returns error."""
        debate_id, err = routing_handler._extract_debate_id("/")
        assert debate_id is None
        assert err == "Invalid path"

    def test_invalid_debate_id_special_chars(self, routing_handler):
        """Debate ID with special characters fails validation."""
        debate_id, err = routing_handler._extract_debate_id(
            "/api/v1/debates/../../../etc/passwd/impasse"
        )
        assert debate_id is None
        assert err is not None

    def test_debate_id_with_dots_fails(self, routing_handler):
        """Debate ID with dots fails the slug pattern."""
        debate_id, err = routing_handler._extract_debate_id("/api/v1/debates/bad.id.here/impasse")
        assert debate_id is None
        assert err is not None

    def test_valid_alphanumeric_debate_id(self, routing_handler):
        """Alphanumeric debate ID with hyphens and underscores is valid."""
        debate_id, err = routing_handler._extract_debate_id("/api/v1/debates/abc-123_def/summary")
        assert debate_id == "abc-123_def"
        assert err is None

    def test_debate_id_too_long(self, routing_handler):
        """Debate ID exceeding 128 chars fails validation."""
        long_id = "a" * 129
        debate_id, err = routing_handler._extract_debate_id(f"/api/v1/debates/{long_id}/impasse")
        assert debate_id is None
        assert err is not None

    def test_debate_id_exactly_128_chars(self, routing_handler):
        """Debate ID of exactly 128 chars is valid."""
        id_128 = "a" * 128
        debate_id, err = routing_handler._extract_debate_id(f"/api/v1/debates/{id_128}/impasse")
        assert debate_id == id_128
        assert err is None

    def test_debate_id_with_spaces_fails(self, routing_handler):
        """Debate ID with spaces fails validation."""
        debate_id, err = routing_handler._extract_debate_id("/api/v1/debates/bad id/impasse")
        assert debate_id is None
        assert err is not None

    def test_debate_id_single_char(self, routing_handler):
        """Single character debate ID is valid."""
        debate_id, err = routing_handler._extract_debate_id("/api/v1/debates/x/impasse")
        assert debate_id == "x"
        assert err is None


# =============================================================================
# Tests: can_handle
# =============================================================================


class TestCanHandle:
    """Test can_handle path matching."""

    def test_debate_create_endpoint(self, routing_handler):
        """Handles /api/v1/debate for debate creation."""
        assert routing_handler.can_handle("/api/v1/debate") is True

    def test_debates_list_endpoint(self, routing_handler):
        """Handles /api/v1/debates for listing."""
        assert routing_handler.can_handle("/api/v1/debates") is True

    def test_debate_this_endpoint(self, routing_handler):
        """Handles /api/v1/debate-this one-click launcher."""
        assert routing_handler.can_handle("/api/v1/debate-this") is True

    def test_search_endpoint(self, routing_handler):
        """Handles /api/v1/search cross-debate search."""
        assert routing_handler.can_handle("/api/v1/search") is True

    def test_debates_search_endpoint(self, routing_handler):
        """Handles /api/v1/debates/search variant."""
        assert routing_handler.can_handle("/api/v1/debates/search") is True

    def test_debates_with_id_suffix(self, routing_handler):
        """Handles /api/v1/debates/{id}/impasse."""
        assert routing_handler.can_handle("/api/v1/debates/abc/impasse") is True

    def test_debates_estimate_cost(self, routing_handler):
        """Handles /api/v1/debates/estimate-cost."""
        assert routing_handler.can_handle("/api/v1/debates/estimate-cost") is True

    def test_debates_batch(self, routing_handler):
        """Handles /api/v1/debates/batch."""
        assert routing_handler.can_handle("/api/v1/debates/batch") is True

    def test_debates_export_batch(self, routing_handler):
        """Handles /api/v1/debates/export/batch."""
        assert routing_handler.can_handle("/api/v1/debates/export/batch") is True

    def test_unversioned_debate(self, routing_handler):
        """Handles unversioned /api/debate path."""
        assert routing_handler.can_handle("/api/debate") is True

    def test_unversioned_debates(self, routing_handler):
        """Handles unversioned /api/debates path."""
        assert routing_handler.can_handle("/api/debates") is True

    def test_unversioned_debate_this(self, routing_handler):
        """Handles unversioned /api/debate-this path."""
        assert routing_handler.can_handle("/api/debate-this") is True

    def test_unversioned_search(self, routing_handler):
        """Handles unversioned /api/search path."""
        assert routing_handler.can_handle("/api/search") is True

    def test_unversioned_debates_subpath(self, routing_handler):
        """Handles unversioned /api/debates/ subpaths."""
        assert routing_handler.can_handle("/api/debates/abc/messages") is True

    def test_v2_debates_path(self, routing_handler):
        """Handles v2 versioned /api/v2/debates path."""
        assert routing_handler.can_handle("/api/v2/debates") is True

    def test_v2_debates_id_suffix(self, routing_handler):
        """Handles v2 versioned /api/v2/debates/{id}/fork."""
        assert routing_handler.can_handle("/api/v2/debates/abc/fork") is True

    def test_meta_critique_via_debate_path(self, routing_handler):
        """Handles /api/debate/{id}/meta-critique via singular path."""
        assert routing_handler.can_handle("/api/v1/debate/abc/meta-critique") is True

    def test_graph_stats_via_debate_path(self, routing_handler):
        """Handles /api/debate/{id}/graph/stats via singular path."""
        assert routing_handler.can_handle("/api/v1/debate/abc/graph/stats") is True

    def test_unrelated_path_not_handled(self, routing_handler):
        """Does not handle unrelated paths."""
        assert routing_handler.can_handle("/api/v1/users") is False

    def test_root_not_handled(self, routing_handler):
        """Does not handle root path."""
        assert routing_handler.can_handle("/") is False

    def test_empty_path_not_handled(self, routing_handler):
        """Does not handle empty path."""
        assert routing_handler.can_handle("") is False

    def test_agents_not_handled(self, routing_handler):
        """Does not handle /api/v1/agents."""
        assert routing_handler.can_handle("/api/v1/agents") is False

    def test_partial_debate_not_handled(self, routing_handler):
        """Does not handle /api/v1/deba (partial match)."""
        assert routing_handler.can_handle("/api/v1/deba") is False

    def test_analytics_subpath_handled(self, routing_handler):
        """Handles debates analytics subpath."""
        assert routing_handler.can_handle("/api/v1/debates/analytics/consensus") is True

    def test_health_subpath_handled(self, routing_handler):
        """Handles debates health subpath."""
        assert routing_handler.can_handle("/api/v1/debates/health") is True


# =============================================================================
# Tests: _dispatch_suffix_route
# =============================================================================


class TestDispatchSuffixRoute:
    """Test _dispatch_suffix_route suffix-based dispatch."""

    def test_no_matching_suffix_returns_none(self, routing_handler):
        """Path with no matching suffix returns None."""
        result = routing_handler._dispatch_suffix_route(
            "/api/v1/debates/abc/unknown-suffix",
            {},
            _make_mock_http_handler(),
        )
        assert result is None

    def test_dispatches_to_impasse(self, mock_storage):
        """Dispatches to _get_impasse for /impasse suffix."""
        mock_impasse = MagicMock(return_value="impasse-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_impasse": mock_impasse},
        )
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/impasse",
            {},
            _make_mock_http_handler(),
        )
        assert result == "impasse-result"
        mock_impasse.assert_called_once()

    def test_dispatches_to_convergence(self, mock_storage):
        """Dispatches to _get_convergence for /convergence suffix."""
        mock_fn = MagicMock(return_value="conv-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_convergence": mock_fn},
        )
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/convergence",
            {},
            _make_mock_http_handler(),
        )
        assert result == "conv-result"
        mock_fn.assert_called_once()

    def test_dispatches_to_diagnostics_id_only(self, mock_storage):
        """Dispatches to _get_diagnostics (ID-only method)."""
        mock_fn = MagicMock(return_value="diag-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_diagnostics": mock_fn},
        )
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/diagnostics",
            {},
            _make_mock_http_handler(),
        )
        assert result == "diag-result"
        mock_fn.assert_called_once_with("test-id")

    def test_dispatches_to_meta_critique_id_only(self, mock_storage):
        """Dispatches to _get_meta_critique (ID-only method)."""
        mock_fn = MagicMock(return_value="meta-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_meta_critique": mock_fn},
        )
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/meta-critique",
            {},
            _make_mock_http_handler(),
        )
        assert result == "meta-result"
        mock_fn.assert_called_once_with("test-id")

    def test_dispatches_to_messages_with_pagination(self, mock_storage):
        """Dispatches to _get_debate_messages with limit/offset params."""
        mock_fn = MagicMock(return_value="msgs-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_debate_messages": mock_fn},
        )
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/messages",
            {"limit": "20", "offset": "10"},
            _make_mock_http_handler(),
        )
        assert result == "msgs-result"
        mock_fn.assert_called_once_with("test-id", limit=20, offset=10)

    def test_messages_uses_default_pagination(self, mock_storage):
        """Messages dispatch uses default limit=50, offset=0."""
        mock_fn = MagicMock(return_value="msgs-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_debate_messages": mock_fn},
        )
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/messages",
            {},
            _make_mock_http_handler(),
        )
        mock_fn.assert_called_once_with("test-id", limit=50, offset=0)

    def test_dispatches_to_followups_id_only(self, mock_storage):
        """Dispatches to _get_followup_suggestions (ID-only)."""
        mock_fn = MagicMock(return_value="followups-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_followup_suggestions": mock_fn},
        )
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/followups",
            {},
            _make_mock_http_handler(),
        )
        assert result == "followups-result"
        mock_fn.assert_called_once_with("test-id")

    def test_dispatches_to_forks_with_id_only(self, mock_storage):
        """_list_debate_forks takes only the debate id."""
        mock_fn = MagicMock(return_value="forks-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_list_debate_forks": mock_fn},
        )
        http_handler = _make_mock_http_handler()
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/forks",
            {},
            http_handler,
        )
        assert result == "forks-result"
        mock_fn.assert_called_once_with("test-id")

    def test_dispatches_to_summary_with_handler(self, mock_storage):
        """Dispatches to _get_summary with handler + debate_id."""
        mock_fn = MagicMock(return_value="summary-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_summary": mock_fn},
        )
        http_handler = _make_mock_http_handler()
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/summary",
            {},
            http_handler,
        )
        assert result == "summary-result"
        mock_fn.assert_called_once_with(http_handler, "test-id")

    def test_dispatches_to_citations_with_handler(self, mock_storage):
        """Dispatches to _get_citations with handler + debate_id."""
        mock_fn = MagicMock(return_value="citations-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_citations": mock_fn},
        )
        http_handler = _make_mock_http_handler()
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/citations",
            {},
            http_handler,
        )
        assert result == "citations-result"
        mock_fn.assert_called_once_with(http_handler, "test-id")

    def test_dispatches_to_evidence_with_handler(self, mock_storage):
        """Dispatches to _get_evidence with handler + debate_id."""
        mock_fn = MagicMock(return_value="evidence-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_evidence": mock_fn},
        )
        http_handler = _make_mock_http_handler()
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/evidence",
            {},
            http_handler,
        )
        assert result == "evidence-result"
        mock_fn.assert_called_once_with(http_handler, "test-id")

    def test_dispatches_to_verification_report(self, mock_storage):
        """Dispatches to _get_verification_report."""
        mock_fn = MagicMock(return_value="vr-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_verification_report": mock_fn},
        )
        http_handler = _make_mock_http_handler()
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/verification-report",
            {},
            http_handler,
        )
        assert result == "vr-result"
        mock_fn.assert_called_once_with(http_handler, "test-id")

    def test_dispatches_to_graph_stats_id_only(self, mock_storage):
        """Dispatches to _get_graph_stats (ID-only)."""
        mock_fn = MagicMock(return_value="gs-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_graph_stats": mock_fn},
        )
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/graph/stats",
            {},
            _make_mock_http_handler(),
        )
        assert result == "gs-result"
        mock_fn.assert_called_once_with("test-id")

    def test_dispatches_to_rhetorical_id_only(self, mock_storage):
        """Dispatches to _get_rhetorical_observations (ID-only)."""
        mock_fn = MagicMock(return_value="rhet-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_rhetorical_observations": mock_fn},
        )
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/rhetorical",
            {},
            _make_mock_http_handler(),
        )
        assert result == "rhet-result"
        mock_fn.assert_called_once_with("test-id")

    def test_dispatches_to_trickster_id_only(self, mock_storage):
        """Dispatches to _get_trickster_status (ID-only)."""
        mock_fn = MagicMock(return_value="trick-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_trickster_status": mock_fn},
        )
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/trickster",
            {},
            _make_mock_http_handler(),
        )
        assert result == "trick-result"
        mock_fn.assert_called_once_with("test-id")

    def test_invalid_debate_id_returns_400(self, mock_storage):
        """Invalid debate ID in path returns 400 error."""
        mock_fn = MagicMock()
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_impasse": mock_fn},
        )
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/bad..id/impasse",
            {},
            _make_mock_http_handler(),
        )
        assert _status(result) == 400
        mock_fn.assert_not_called()

    def test_method_not_found_skips(self, mock_storage):
        """If method doesn't exist on handler, suffix is skipped."""
        handler = _make_routing_handler(storage=mock_storage)
        # No _get_impasse method registered
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/impasse",
            {},
            _make_mock_http_handler(),
        )
        assert result is None

    def test_artifact_access_check_for_messages(self, mock_storage):
        """Messages is an artifact endpoint - checks access."""
        mock_storage.is_public.return_value = False
        mock_fn = MagicMock(return_value="msgs")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_debate_messages": mock_fn},
        )
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "secret"
        http_handler = _make_mock_http_handler(auth_header=None)
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = handler._dispatch_suffix_route(
                "/api/v1/debates/test-id/messages",
                {},
                http_handler,
            )
        assert _status(result) == 401
        mock_fn.assert_not_called()

    def test_artifact_access_public_debate_allows_messages(self, mock_storage):
        """Public debate allows messages without auth."""
        mock_storage.is_public.return_value = True
        mock_fn = MagicMock(return_value="msgs")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_debate_messages": mock_fn},
        )
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/messages",
            {},
            _make_mock_http_handler(),
        )
        assert result == "msgs"

    def test_path_too_short_for_id_extraction(self, mock_storage):
        """Short path fails ID extraction - route is skipped."""
        mock_fn = MagicMock()
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_impasse": mock_fn},
        )
        # Path ends with /impasse but won't extract a valid debate_id
        result = handler._dispatch_suffix_route(
            "/impasse",
            {},
            _make_mock_http_handler(),
        )
        # Either returns None (skip) or 400 (invalid path)
        if result is not None:
            assert _status(result) == 400
        mock_fn.assert_not_called()


# =============================================================================
# Tests: Mixin Class-Level Attributes
# =============================================================================


class TestMixinClassAttributes:
    """Test that RoutingMixin exposes class-level route config."""

    def test_routes_attribute(self, routing_handler):
        """RoutingMixin has ROUTES attribute."""
        from aragora.server.handlers.debates.routing import ROUTES

        assert routing_handler.ROUTES is ROUTES

    def test_auth_required_attribute(self, routing_handler):
        """RoutingMixin has AUTH_REQUIRED_ENDPOINTS attribute."""
        from aragora.server.handlers.debates.routing import AUTH_REQUIRED_ENDPOINTS

        assert routing_handler.AUTH_REQUIRED_ENDPOINTS is AUTH_REQUIRED_ENDPOINTS

    def test_allowed_export_formats_attribute(self, routing_handler):
        """RoutingMixin has ALLOWED_EXPORT_FORMATS attribute."""
        assert routing_handler.ALLOWED_EXPORT_FORMATS == {"json", "csv", "html", "txt", "md"}

    def test_allowed_export_tables_attribute(self, routing_handler):
        """RoutingMixin has ALLOWED_EXPORT_TABLES attribute."""
        assert routing_handler.ALLOWED_EXPORT_TABLES == {
            "summary",
            "messages",
            "critiques",
            "votes",
        }

    def test_artifact_endpoints_attribute(self, routing_handler):
        """RoutingMixin has ARTIFACT_ENDPOINTS attribute."""
        assert routing_handler.ARTIFACT_ENDPOINTS == {
            "/messages",
            "/evidence",
            "/verification-report",
        }

    def test_suffix_routes_attribute(self, routing_handler):
        """RoutingMixin has SUFFIX_ROUTES attribute."""
        from aragora.server.handlers.debates.routing import SUFFIX_ROUTES

        assert routing_handler.SUFFIX_ROUTES is SUFFIX_ROUTES


# =============================================================================
# Tests: Module __all__ Exports
# =============================================================================


class TestModuleExports:
    """Test that __all__ exports are correct."""

    def test_all_exports(self):
        """__all__ contains all expected exports."""
        from aragora.server.handlers.debates import routing

        expected = [
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
        for name in expected:
            assert name in routing.__all__, f"Missing export: {name}"
            assert hasattr(routing, name), f"Export not accessible: {name}"


# =============================================================================
# Tests: Security Edge Cases
# =============================================================================


class TestSecurityEdgeCases:
    """Test security-related edge cases."""

    def test_path_traversal_in_debate_id(self, routing_handler):
        """Path traversal attempt in debate ID is rejected."""
        debate_id, err = routing_handler._extract_debate_id(
            "/api/v1/debates/../../etc/passwd/impasse"
        )
        assert debate_id is None
        assert err is not None

    def test_null_byte_in_debate_id(self, routing_handler):
        """Null byte in debate ID is rejected."""
        debate_id, err = routing_handler._extract_debate_id("/api/v1/debates/test\x00id/impasse")
        assert debate_id is None
        assert err is not None

    def test_unicode_in_debate_id(self, routing_handler):
        """Unicode characters in debate ID are rejected."""
        debate_id, err = routing_handler._extract_debate_id("/api/v1/debates/test\u00e9/impasse")
        assert debate_id is None
        assert err is not None

    def test_html_injection_in_debate_id(self, routing_handler):
        """HTML injection in debate ID is rejected."""
        debate_id, err = routing_handler._extract_debate_id(
            "/api/v1/debates/<script>alert(1)</script>/impasse"
        )
        assert debate_id is None
        assert err is not None

    def test_sql_injection_in_debate_id(self, routing_handler):
        """SQL injection patterns in debate ID are rejected."""
        debate_id, err = routing_handler._extract_debate_id(
            "/api/v1/debates/'; DROP TABLE debates;--/impasse"
        )
        assert debate_id is None
        assert err is not None

    def test_empty_debate_id_segment(self, routing_handler):
        """Empty debate ID segment in path."""
        debate_id, err = routing_handler._extract_debate_id("/api/v1/debates//impasse")
        # Empty string won't match the slug pattern
        assert debate_id is None
        assert err is not None

    def test_auth_header_without_bearer_prefix(self, routing_handler):
        """Auth header without Bearer prefix is not accepted."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "server-secret"
        handler = _make_mock_http_handler(auth_header="Token some-token")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(handler)
        assert _status(result) == 401

    def test_jwt_with_type_error_falls_through(self, routing_handler):
        """JWT validation raising TypeError falls through gracefully."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "secret"
        mock_config.validate_token.return_value = False
        handler = _make_mock_http_handler(auth_header="Bearer x.y.z")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            with patch(
                "aragora.billing.auth.validate_access_token",
                side_effect=TypeError("bad type"),
            ):
                result = routing_handler._check_auth(handler)
        assert _status(result) == 401

    def test_jwt_with_attribute_error_falls_through(self, routing_handler):
        """JWT validation raising AttributeError falls through."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "secret"
        mock_config.validate_token.return_value = False
        handler = _make_mock_http_handler(auth_header="Bearer a.b.c")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            with patch(
                "aragora.billing.auth.validate_access_token",
                side_effect=AttributeError("no attr"),
            ):
                result = routing_handler._check_auth(handler)
        assert _status(result) == 401

    def test_jwt_with_key_error_falls_through(self, routing_handler):
        """JWT validation raising KeyError falls through."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "secret"
        mock_config.validate_token.return_value = False
        handler = _make_mock_http_handler(auth_header="Bearer a.b.c")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            with patch(
                "aragora.billing.auth.validate_access_token",
                side_effect=KeyError("missing"),
            ):
                result = routing_handler._check_auth(handler)
        assert _status(result) == 401

    def test_jwt_with_value_error_falls_through(self, routing_handler):
        """JWT validation raising ValueError falls through."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "secret"
        mock_config.validate_token.return_value = True
        handler = _make_mock_http_handler(auth_header="Bearer a.b.c")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            with patch(
                "aragora.billing.auth.validate_access_token",
                side_effect=ValueError("bad value"),
            ):
                result = routing_handler._check_auth(handler)
        # Falls through to legacy check; validate_token returns True
        assert result is None


# =============================================================================
# Tests: _check_auth edge cases around api_token config
# =============================================================================


class TestCheckAuthApiTokenConfig:
    """Edge cases around the api_token config interaction."""

    def test_api_token_none_returns_none(self, routing_handler, mock_http_handler):
        """api_token is None means skip token auth."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = None
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(mock_http_handler)
        assert result is None

    def test_api_token_false_returns_none(self, routing_handler, mock_http_handler):
        """api_token is falsy means skip token auth."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = False
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(mock_http_handler)
        assert result is None

    def test_ara_prefix_accepted_regardless_of_legacy_check(self, routing_handler):
        """ara_ prefixed tokens bypass legacy HMAC checking entirely."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "server-secret"
        mock_config.validate_token.return_value = False  # Would fail legacy
        handler = _make_mock_http_handler(auth_header="Bearer ara_my_key")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(handler)
        assert result is None
        mock_config.validate_token.assert_not_called()

    def test_jwt_token_with_two_dots_triggers_jwt_check(self, routing_handler):
        """A token with exactly 2 dots triggers JWT validation path."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "secret"
        handler = _make_mock_http_handler(auth_header="Bearer part1.part2.part3")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            with patch(
                "aragora.billing.auth.validate_access_token",
                return_value={"sub": "u1"},
            ) as mock_jwt:
                result = routing_handler._check_auth(handler)
        mock_jwt.assert_called_once_with("part1.part2.part3")
        assert result is None

    def test_token_with_three_dots_not_jwt(self, routing_handler):
        """A token with 3 dots (4 parts) does NOT trigger JWT check."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "secret"
        mock_config.validate_token.return_value = True
        handler = _make_mock_http_handler(auth_header="Bearer a.b.c.d")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            with patch(
                "aragora.billing.auth.validate_access_token",
            ) as mock_jwt:
                result = routing_handler._check_auth(handler)
        # Token has 3 dots, so token.count(".") == 3, not 2
        mock_jwt.assert_not_called()
        # Falls to legacy check which returns True
        assert result is None

    def test_token_with_one_dot_not_jwt(self, routing_handler):
        """A token with 1 dot does NOT trigger JWT check."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.api_token = "secret"
        mock_config.validate_token.return_value = True
        handler = _make_mock_http_handler(auth_header="Bearer a.b")
        with patch(_AUTH_CONFIG_TARGET, mock_config):
            result = routing_handler._check_auth(handler)
        assert result is None


# =============================================================================
# Tests: Integration-style dispatch scenarios
# =============================================================================


class TestDispatchIntegration:
    """Integration-style tests combining extraction + dispatch + access."""

    def test_full_dispatch_chain_impasse(self, mock_storage):
        """Full dispatch chain: path -> extract ID -> dispatch -> method called."""
        mock_fn = MagicMock(return_value="ok")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_impasse": mock_fn},
        )
        http = _make_mock_http_handler()
        result = handler._dispatch_suffix_route("/api/v1/debates/my-debate-123/impasse", {}, http)
        assert result == "ok"
        mock_fn.assert_called_once_with(http, "my-debate-123")

    def test_full_dispatch_chain_messages_with_params(self, mock_storage):
        """Full dispatch for messages with query params."""
        mock_fn = MagicMock(return_value="msgs")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_debate_messages": mock_fn},
        )
        mock_storage.is_public.return_value = True  # Public so no auth needed
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/d1/messages",
            {"limit": "5", "offset": "2"},
            _make_mock_http_handler(),
        )
        assert result == "msgs"
        mock_fn.assert_called_once_with("d1", limit=5, offset=2)

    def test_dispatch_first_matching_suffix_wins(self, mock_storage):
        """If path matches multiple suffixes, first match wins."""
        # /graph/stats ends with both /stats and /graph/stats
        mock_graph = MagicMock(return_value="graph-result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_graph_stats": mock_graph},
        )
        result = handler._dispatch_suffix_route(
            "/api/v1/debates/test-id/graph/stats",
            {},
            _make_mock_http_handler(),
        )
        assert result == "graph-result"

    def test_can_handle_and_dispatch_combined(self, mock_storage):
        """can_handle returns True and dispatch finds the route."""
        mock_fn = MagicMock(return_value="result")
        handler = _make_routing_handler(
            storage=mock_storage,
            extra_methods={"_get_summary": mock_fn},
        )
        path = "/api/v1/debates/abc/summary"
        assert handler.can_handle(path) is True
        result = handler._dispatch_suffix_route(path, {}, _make_mock_http_handler())
        assert result == "result"
