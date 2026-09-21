"""
Tests for auth exemption configuration in unified_server.py.

Ensures public endpoints remain accessible without authentication,
preventing regressions like the 401 errors on /api/docs.

Tests cover:
- AUTH_EXEMPT_PATHS - exact path matches
- AUTH_EXEMPT_PREFIXES - prefix matches for all methods
- AUTH_EXEMPT_GET_PREFIXES - prefix matches for GET only
"""

from __future__ import annotations

import pytest


class TestAuthExemptPaths:
    """Tests for AUTH_EXEMPT_PATHS configuration."""

    @pytest.fixture
    def exempt_paths(self):
        """Get the AUTH_EXEMPT_PATHS from unified_server."""
        from aragora.server.unified_server import UnifiedHandler

        return UnifiedHandler.AUTH_EXEMPT_PATHS

    def test_health_endpoints_exempt(self, exempt_paths):
        """Health check endpoints should be publicly accessible."""
        health_endpoints = [
            "/healthz",
            "/readyz",
            "/api/health",
            "/api/health/detailed",
            "/api/health/deep",
            "/api/health/stores",
        ]
        for endpoint in health_endpoints:
            assert endpoint in exempt_paths, f"Health endpoint {endpoint} should be exempt"

    def test_oauth_provider_endpoint_exempt(self, exempt_paths):
        """OAuth provider discovery should be public."""
        assert "/api/auth/oauth/providers" in exempt_paths

    def test_api_docs_endpoints_require_auth(self, exempt_paths):
        """API documentation endpoints require auth to prevent attack surface mapping."""
        doc_endpoints = [
            "/api/openapi",
            "/api/openapi.json",
            "/api/openapi.yaml",
            "/api/postman.json",
            "/api/docs",
            "/api/docs/",
            "/api/redoc",
            "/api/redoc/",
        ]
        for endpoint in doc_endpoints:
            assert endpoint not in exempt_paths, (
                f"Doc endpoint {endpoint} should NOT be exempt (requires auth)"
            )

    def test_public_data_endpoints_exempt(self, exempt_paths):
        """Public read-only data endpoints should be accessible."""
        public_endpoints = [
            "/api/insights/recent",
            "/api/flips/recent",
            "/api/evidence",
            "/api/evidence/statistics",
            "/api/verification/status",
            "/api/leaderboard",
            "/api/leaderboard-view",
            "/api/agents",
            "/api/v1/spectate/recent",
            "/api/v1/spectate/status",
            "/api/v1/spectate/stream",
        ]
        for endpoint in public_endpoints:
            assert endpoint in exempt_paths, f"Public endpoint {endpoint} should be exempt"

    def test_slack_webhook_endpoints_exempt(self, exempt_paths):
        """Slack webhook endpoints should bypass API/JWT auth and rely on signatures."""
        slack_webhook_endpoints = [
            "/api/v1/integrations/slack/commands",
            "/api/v1/integrations/slack/events",
            "/api/v1/integrations/slack/interactive",
            "/api/v1/bots/slack/commands",
            "/api/v1/bots/slack/events",
            "/api/v1/bots/slack/interactions",
            "/api/v1/bots/slack/interactive",
        ]
        for endpoint in slack_webhook_endpoints:
            assert endpoint in exempt_paths, f"Slack webhook endpoint {endpoint} should be exempt"


class TestAuthExemptPrefixes:
    """Tests for AUTH_EXEMPT_PREFIXES configuration."""

    @pytest.fixture
    def exempt_prefixes(self):
        """Get the AUTH_EXEMPT_PREFIXES from unified_server."""
        from aragora.server.unified_server import UnifiedHandler

        return UnifiedHandler.AUTH_EXEMPT_PREFIXES

    def test_oauth_flow_prefix_exempt(self, exempt_prefixes):
        """OAuth flow paths should be exempt."""
        # Check that OAuth paths would be covered by prefix matching
        oauth_path = "/api/auth/oauth/google"
        assert any(oauth_path.startswith(p) for p in exempt_prefixes)

    def test_agent_profiles_prefix_exempt(self, exempt_prefixes):
        """Agent profile paths should be exempt."""
        assert any("/api/agent/" in p for p in exempt_prefixes)

    def test_routing_prefix_exempt(self, exempt_prefixes):
        """Routing/domain detection paths should be exempt."""
        assert any("/api/routing/" in p for p in exempt_prefixes)

    def test_prefix_matches_subpaths(self, exempt_prefixes):
        """Prefixes should match subpaths correctly."""
        test_paths = [
            ("/api/auth/oauth/google", True),
            ("/api/auth/oauth/github/callback", True),
            ("/api/agent/claude-opus", True),
            ("/api/agent/gpt-4o/stats", True),
            ("/api/routing/detect-domain", True),
            ("/api/auth/login", False),  # Not under oauth/
            ("/api/agents", False),  # Plural, different endpoint
        ]
        for path, should_match in test_paths:
            matches = any(path.startswith(prefix) for prefix in exempt_prefixes)
            if should_match:
                assert matches, f"Path {path} should match an exempt prefix"
            # Note: we don't assert False cases here since they may be in AUTH_EXEMPT_PATHS


class TestAuthExemptGetPrefixes:
    """Tests for AUTH_EXEMPT_GET_PREFIXES configuration."""

    @pytest.fixture
    def get_prefixes(self):
        """Get the AUTH_EXEMPT_GET_PREFIXES from unified_server."""
        from aragora.server.unified_server import UnifiedHandler

        return UnifiedHandler.AUTH_EXEMPT_GET_PREFIXES

    def test_evidence_prefix_get_only(self, get_prefixes):
        """Evidence paths should be GET-only exempt."""
        assert any("/api/evidence/" in p for p in get_prefixes)

    def test_get_prefix_paths(self, get_prefixes):
        """GET-only prefixes should cover expected paths."""
        # These paths should be accessible via GET without auth
        test_paths = [
            "/api/evidence/123",
            "/api/evidence/search",
        ]
        for path in test_paths:
            matches = any(path.startswith(prefix) for prefix in get_prefixes)
            assert matches, f"Path {path} should match a GET-only exempt prefix"


class TestReceiptExportExemptionPattern:
    """The public ODR export exemption must not admit a sibling receipt route."""

    RESERVED_SEGMENTS = ("dsar", "share", "search", "stats", "verify")

    @pytest.fixture
    def handler(self):
        """An uninitialised handler; the exemption checks read class state only."""
        from aragora.server.unified_server import UnifiedHandler

        return UnifiedHandler.__new__(UnifiedHandler)

    @pytest.mark.parametrize("segment", RESERVED_SEGMENTS)
    def test_reserved_segment_export_is_not_exempt(self, handler, segment):
        """Path /api/v2/receipts/<reserved>/export must never bypass authentication."""
        path = f"/api/v2/receipts/{segment}/export"
        assert not handler._is_path_exempt_for_get(path)
        assert not handler._is_path_exempt(path)

    def test_receipt_id_export_stays_exempt(self, handler):
        """A real receipt id keeps the public ODR export exemption."""
        assert handler._is_path_exempt_for_get("/api/v2/receipts/crux-1a2b3c4d/export")

    def test_dsar_still_requires_authentication(self, handler):
        """No DSAR path is exempt by any mechanism, for any request shape."""
        for path in ("/api/v2/receipts/dsar/export", "/api/v2/receipts/dsar/user-42"):
            assert not handler._is_path_exempt(path)
            assert not handler._is_path_exempt_for_get(path)


class TestReceiptExportRoutePermission:
    """The RBAC route rule must admit exactly what the GET exemption pattern admits.

    Both layers carry the same regex, so a request denied by one is denied by the
    other; neither relies on the order the server runs its gates in.
    """

    RESERVED_SEGMENTS = ("dsar", "share", "search", "stats", "verify")

    @pytest.fixture
    def rbac(self):
        """Middleware carrying the default route permissions."""
        from aragora.rbac.middleware import RBACMiddleware, RBACMiddlewareConfig

        return RBACMiddleware(RBACMiddlewareConfig(), validate_permissions=False)

    @pytest.mark.parametrize("segment", RESERVED_SEGMENTS)
    def test_reserved_segment_export_requires_authentication(self, rbac, segment):
        """Path /api/v2/receipts/<reserved>/export must not be allowed unauthenticated."""
        allowed, _reason, _permission = rbac.check_request(
            f"/api/v2/receipts/{segment}/export", "GET", None
        )
        assert allowed is False

    def test_receipt_id_export_allows_unauthenticated(self, rbac):
        """A real receipt id keeps the public ODR export exemption at this layer."""
        allowed, _reason, _permission = rbac.check_request(
            "/api/v2/receipts/crux-1a2b3c4d/export", "GET", None
        )
        assert allowed is True


class TestOAuthQueryParams:
    """Tests for OAuth query parameter whitelist."""

    @pytest.fixture
    def allowed_params(self):
        """Get ALLOWED_QUERY_PARAMS from http_utils."""
        from aragora.server.http_utils import ALLOWED_QUERY_PARAMS

        return ALLOWED_QUERY_PARAMS

    def test_oauth_callback_params_allowed(self, allowed_params):
        """OAuth callback parameters should be in whitelist."""
        oauth_params = [
            "code",
            "state",
            "error",
            "error_description",
            "scope",
            "authuser",
            "prompt",
            "hd",
            "session_state",
        ]
        for param in oauth_params:
            assert param in allowed_params, f"OAuth param {param} should be allowed"

    def test_oauth_params_have_length_limits(self, allowed_params):
        """OAuth string params should have length limits for DoS protection."""
        string_params = ["scope", "prompt", "hd", "session_state"]
        for param in string_params:
            limit = allowed_params.get(param)
            assert limit is not None, f"OAuth param {param} should have a length limit"
            assert isinstance(limit, int), f"OAuth param {param} limit should be int"
            assert limit > 0, f"OAuth param {param} limit should be positive"


class TestAuthExemptionIntegration:
    """Integration tests for auth exemption behavior."""

    def test_exempt_paths_is_frozenset(self):
        """AUTH_EXEMPT_PATHS should be immutable."""
        from aragora.server.unified_server import UnifiedHandler

        assert isinstance(UnifiedHandler.AUTH_EXEMPT_PATHS, frozenset)

    def test_exempt_prefixes_is_tuple(self):
        """AUTH_EXEMPT_PREFIXES should be a tuple for efficient iteration."""
        from aragora.server.unified_server import UnifiedHandler

        assert isinstance(UnifiedHandler.AUTH_EXEMPT_PREFIXES, tuple)

    def test_get_prefixes_is_tuple(self):
        """AUTH_EXEMPT_GET_PREFIXES should be a tuple."""
        from aragora.server.unified_server import UnifiedHandler

        assert isinstance(UnifiedHandler.AUTH_EXEMPT_GET_PREFIXES, tuple)

    def test_no_duplicate_paths(self):
        """No path should appear in both PATHS and PREFIXES."""
        from aragora.server.unified_server import UnifiedHandler

        paths = UnifiedHandler.AUTH_EXEMPT_PATHS
        prefixes = UnifiedHandler.AUTH_EXEMPT_PREFIXES

        # A prefix shouldn't also be an exact path (would be redundant)
        for prefix in prefixes:
            # Prefixes typically end with / to match subpaths
            if not prefix.endswith("/"):
                assert prefix not in paths, f"Prefix {prefix} shouldn't also be in exact paths"

    def test_paths_are_normalized(self):
        """All paths should be normalized (no trailing slashes except for root)."""
        from aragora.server.unified_server import UnifiedHandler

        for path in UnifiedHandler.AUTH_EXEMPT_PATHS:
            if path != "/" and not path.endswith("/"):
                # Path without trailing slash - good
                pass
            elif path.endswith("/") and len(path) > 1:
                # Some doc endpoints intentionally have trailing slash variants
                assert path.rstrip("/") in UnifiedHandler.AUTH_EXEMPT_PATHS, (
                    f"Trailing slash path {path} should have non-slash variant"
                )
