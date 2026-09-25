"""
Tests for RBAC middleware module.

Tests cover:
- RoutePermission matching and resource ID extraction
- RBACMiddlewareConfig defaults and customization
- RBACMiddleware request checking
- Bypass paths and methods
- Default route permissions
- Permission validation
- Route permission management (add/remove)
- Global middleware instance
- Permission handler factory
- Convenience functions
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from aragora.rbac.checker import PermissionChecker
from aragora.rbac.middleware import (
    DEFAULT_ROUTE_PERMISSIONS,
    RBACMiddleware,
    RBACMiddlewareConfig,
    RoutePermission,
    check_route_access,
    create_permission_handler,
    get_middleware,
    set_middleware,
    validate_route_permissions,
)
from aragora.rbac.models import AuthorizationContext, AuthorizationDecision


# ============================================================================
# RoutePermission Tests
# ============================================================================


class TestRoutePermission:
    """Tests for RoutePermission dataclass."""

    def test_pattern_string_compiled_to_regex(self):
        """Test string pattern is compiled to regex."""
        rule = RoutePermission(r"^/api/debates$", "GET", "debates:read")

        assert isinstance(rule.pattern, re.Pattern)
        assert rule.pattern.pattern == r"^/api/debates$"

    def test_pattern_regex_accepted(self):
        """Test compiled regex pattern is accepted."""
        pattern = re.compile(r"^/api/users/([^/]+)$")
        rule = RoutePermission(pattern, "GET", "users:read")

        assert rule.pattern is pattern

    def test_matches_exact_path_and_method(self):
        """Test matching exact path and method."""
        rule = RoutePermission(r"^/api/debates$", "POST", "debates:create")

        matches, resource_id = rule.matches("/api/debates", "POST")

        assert matches is True
        assert resource_id is None

    def test_matches_case_insensitive_method(self):
        """Test method matching is case-insensitive."""
        rule = RoutePermission(r"^/api/debates$", "POST", "debates:create")

        matches, _ = rule.matches("/api/debates", "post")
        assert matches is True

        matches, _ = rule.matches("/api/debates", "POST")
        assert matches is True

    def test_no_match_wrong_method(self):
        """Test no match when method differs."""
        rule = RoutePermission(r"^/api/debates$", "POST", "debates:create")

        matches, _ = rule.matches("/api/debates", "GET")

        assert matches is False

    def test_no_match_wrong_path(self):
        """Test no match when path differs."""
        rule = RoutePermission(r"^/api/debates$", "GET", "debates:read")

        matches, _ = rule.matches("/api/users", "GET")

        assert matches is False

    def test_wildcard_method_matches_all(self):
        """Test wildcard method matches any method."""
        rule = RoutePermission(r"^/api/admin", "*", "admin.*")

        for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            matches, _ = rule.matches("/api/admin/config", method)
            assert matches is True

    def test_resource_id_extraction(self):
        """Test resource ID is extracted from regex group."""
        rule = RoutePermission(
            r"^/api/debates/([^/]+)$",
            "GET",
            "debates:read",
            resource_id_group=1,
        )

        matches, resource_id = rule.matches("/api/debates/debate-123", "GET")

        assert matches is True
        assert resource_id == "debate-123"

    def test_resource_id_extraction_nested(self):
        """Test nested resource ID extraction."""
        rule = RoutePermission(
            r"^/api/orgs/([^/]+)/debates/([^/]+)$",
            "GET",
            "debates:read",
            resource_id_group=2,
        )

        matches, resource_id = rule.matches("/api/orgs/org-1/debates/debate-123", "GET")

        assert matches is True
        assert resource_id == "debate-123"

    def test_resource_id_extraction_invalid_group(self):
        """Test invalid group index doesn't crash."""
        rule = RoutePermission(
            r"^/api/debates/([^/]+)$",
            "GET",
            "debates:read",
            resource_id_group=5,  # Invalid - only 1 group
        )

        matches, resource_id = rule.matches("/api/debates/debate-123", "GET")

        assert matches is True
        assert resource_id is None  # Graceful handling


# ============================================================================
# RBACMiddlewareConfig Tests
# ============================================================================


class TestRBACMiddlewareConfig:
    """Tests for RBACMiddlewareConfig dataclass."""

    def test_default_bypass_paths(self):
        """Test default bypass paths are set."""
        config = RBACMiddlewareConfig()

        assert "/health" in config.bypass_paths
        assert "/healthz" in config.bypass_paths
        assert "/ready" in config.bypass_paths
        assert "/metrics" in config.bypass_paths

    def test_default_bypass_methods(self):
        """Test OPTIONS is bypassed by default."""
        config = RBACMiddlewareConfig()

        assert "OPTIONS" in config.bypass_methods

    def test_default_authenticated_true(self):
        """Test default_authenticated is True by default."""
        config = RBACMiddlewareConfig()

        assert config.default_authenticated is True

    def test_custom_bypass_paths(self):
        """Test custom bypass paths can be set."""
        config = RBACMiddlewareConfig(bypass_paths={"/custom"})

        assert "/custom" in config.bypass_paths
        assert "/health" not in config.bypass_paths


# ============================================================================
# RBACMiddleware Tests
# ============================================================================


class TestRBACMiddleware:
    """Tests for RBACMiddleware class."""

    def test_middleware_initialization_default(self):
        """Test middleware initializes with defaults."""
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(validate_permissions=False)

            assert middleware.config is not None
            assert len(middleware.config.route_permissions) > 0

    def test_middleware_uses_default_route_permissions(self):
        """Test middleware uses default route permissions when none specified."""
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(validate_permissions=False)

            assert len(middleware.config.route_permissions) == len(DEFAULT_ROUTE_PERMISSIONS)

    def test_check_request_bypass_path(self):
        """Test bypass paths are allowed without auth."""
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(validate_permissions=False)

            allowed, reason, perm = middleware.check_request("/health", "GET", None)

            assert allowed is True
            assert "bypass" in reason.lower()
            assert perm is None

    def test_check_request_bypass_method(self):
        """Test bypass methods (OPTIONS) are allowed."""
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(validate_permissions=False)

            allowed, reason, perm = middleware.check_request("/api/debates", "OPTIONS", None)

            assert allowed is True
            assert "bypass" in reason.lower()

    def test_check_request_unauthenticated_allowed(self):
        """Test routes with allow_unauthenticated pass without auth."""
        config = RBACMiddlewareConfig(
            route_permissions=[
                RoutePermission(r"^/api/auth/login$", "POST", "", allow_unauthenticated=True),
            ],
        )
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(config, validate_permissions=False)

            allowed, reason, perm = middleware.check_request("/api/auth/login", "POST", None)

            assert allowed is True
            assert "unauthenticated" in reason.lower()

    def test_check_request_requires_authentication(self):
        """Test protected routes require authentication."""
        config = RBACMiddlewareConfig(
            route_permissions=[
                RoutePermission(r"^/api/debates$", "POST", "debates:create"),
            ],
        )
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(config, validate_permissions=False)

            allowed, reason, perm = middleware.check_request("/api/debates", "POST", None)

            assert allowed is False
            assert "authentication" in reason.lower()

    def test_check_request_empty_permission_allows_authenticated(self):
        """Test routes with empty permission allow any authenticated user."""
        config = RBACMiddlewareConfig(
            route_permissions=[
                RoutePermission(r"^/api/profile$", "GET", ""),
            ],
        )
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(config, validate_permissions=False)

            context = AuthorizationContext(user_id="user-1")
            allowed, reason, perm = middleware.check_request("/api/profile", "GET", context)

            assert allowed is True
            assert "authenticated" in reason.lower()

    def test_check_request_permission_granted(self):
        """Test permission check grants access when allowed."""
        config = RBACMiddlewareConfig(
            route_permissions=[
                RoutePermission(r"^/api/debates$", "POST", "debates:create"),
            ],
        )
        mock_checker = MagicMock()
        mock_checker.check_permission.return_value = AuthorizationDecision(
            allowed=True,
            reason="User has debates.create permission",
            permission_key="debates:create",
        )

        with patch("aragora.rbac.middleware.get_permission_checker", return_value=mock_checker):
            middleware = RBACMiddleware(config, validate_permissions=False)

            context = AuthorizationContext(user_id="user-1", org_id="org-1")
            allowed, reason, perm = middleware.check_request("/api/debates", "POST", context)

            assert allowed is True
            assert perm == "debates:create"

    def test_check_request_permission_denied(self):
        """Test permission check denies access when not allowed."""
        config = RBACMiddlewareConfig(
            route_permissions=[
                RoutePermission(r"^/api/debates$", "DELETE", "debates:delete"),
            ],
        )
        mock_checker = MagicMock()
        mock_checker.check_permission.return_value = AuthorizationDecision(
            allowed=False,
            reason="User lacks debates.delete permission",
            permission_key="debates:delete",
        )

        with patch("aragora.rbac.middleware.get_permission_checker", return_value=mock_checker):
            middleware = RBACMiddleware(config, validate_permissions=False)

            context = AuthorizationContext(user_id="user-1", org_id="org-1")
            allowed, reason, perm = middleware.check_request("/api/debates", "DELETE", context)

            assert allowed is False
            assert perm == "debates:delete"

    @pytest.mark.parametrize(
        ("path", "method", "expected_permission"),
        [
            ("/api/v1/webhook-configs", "GET", "webhooks.read"),
            ("/api/v1/webhook-configs", "POST", "webhooks.create"),
            ("/api/v1/webhook-configs/probe-123", "GET", "webhooks.read"),
            ("/api/v1/webhook-configs/probe-123", "DELETE", "webhooks.delete"),
            ("/api/v1/webhook-configs/probe-123", "PATCH", "webhooks.update"),
        ],
    )
    def test_webhook_config_alias_enforces_exact_default_permissions(
        self, path: str, method: str, expected_permission: str
    ) -> None:
        checker = PermissionChecker(
            enable_cache=False,
            enable_delegation=False,
            enable_workspace_scope=False,
            enable_conditions=False,
            enable_ownership=False,
        )
        middleware = RBACMiddleware(
            RBACMiddlewareConfig(permission_checker=checker), validate_permissions=False
        )
        allowed_context = AuthorizationContext(
            user_id="allowed-user", permissions={expected_permission}
        )
        denied_context = AuthorizationContext(user_id="denied-user", permissions={"debates.read"})

        allowed, _reason, required = middleware.check_request(path, method, allowed_context)
        denied, _reason, denied_required = middleware.check_request(path, method, denied_context)

        assert allowed is True
        assert required == expected_permission
        assert denied is False
        assert denied_required == expected_permission
        assert middleware.get_required_permission(path + "/extra/deeper", method) is None

    def test_check_request_no_matching_rule_authenticated(self):
        """Test no matching rule with authenticated user is denied (default-deny)."""
        config = RBACMiddlewareConfig(
            route_permissions=[],  # No rules
            default_authenticated=False,
        )
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(config, validate_permissions=False)

            context = AuthorizationContext(user_id="user-1")
            allowed, reason, perm = middleware.check_request("/api/unknown", "GET", context)

            assert allowed is False
            assert "no permission rule" in reason.lower()

    def test_check_request_no_matching_rule_requires_auth(self):
        """Test no matching rule requires auth when default_authenticated is True."""
        config = RBACMiddlewareConfig(
            route_permissions=[],  # No rules
            default_authenticated=True,
        )
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(config, validate_permissions=False)

            allowed, reason, perm = middleware.check_request("/api/unknown", "GET", None)

            assert allowed is False
            assert "authentication" in reason.lower()


# ============================================================================
# Route Permission Management Tests
# ============================================================================


class TestRoutePermissionManagement:
    """Tests for route permission management."""

    def test_add_route_permission(self):
        """Test adding a route permission."""
        config = RBACMiddlewareConfig(route_permissions=[])
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(config, validate_permissions=False)

            new_rule = RoutePermission(r"^/api/custom$", "GET", "custom.read")
            middleware.add_route_permission(new_rule)

            assert new_rule in middleware.config.route_permissions

    def test_remove_route_permission(self):
        """Test removing a route permission."""
        rule = RoutePermission(r"^/api/debates$", "GET", "debates:read")
        config = RBACMiddlewareConfig(route_permissions=[rule])
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(config, validate_permissions=False)

            middleware.remove_route_permission(r"^/api/debates$", "GET")

            assert len(middleware.config.route_permissions) == 0

    def test_get_required_permission(self):
        """Test getting required permission for a route."""
        rule = RoutePermission(r"^/api/debates$", "POST", "debates:create")
        config = RBACMiddlewareConfig(route_permissions=[rule])
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(config, validate_permissions=False)

            perm = middleware.get_required_permission("/api/debates", "POST")

            assert perm == "debates:create"

    def test_get_required_permission_no_match(self):
        """Test getting required permission when no rule matches."""
        config = RBACMiddlewareConfig(route_permissions=[])
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(config, validate_permissions=False)

            perm = middleware.get_required_permission("/api/unknown", "GET")

            assert perm is None


# ============================================================================
# Permission Validation Tests
# ============================================================================


class TestPermissionValidation:
    """Tests for permission validation."""

    def test_validate_valid_permissions_returns_empty(self):
        """Test valid permissions return empty warning list."""
        # Use empty list - no warnings for empty
        warnings = validate_route_permissions([])

        assert warnings == []

    def test_validate_undefined_permission_returns_warning(self):
        """Test undefined permission returns warning."""
        rules = [
            RoutePermission(r"^/api/fake$", "GET", "completely.fake.permission"),
        ]

        warnings = validate_route_permissions(rules)

        assert len(warnings) > 0
        assert any("completely.fake.permission" in w for w in warnings)

    def test_validate_undefined_wildcard_prefix_returns_warning(self):
        """Test undefined wildcard prefix returns warning."""
        rules = [
            RoutePermission(r"^/api/fake$", "GET", "nonexistent.*"),
        ]

        warnings = validate_route_permissions(rules)

        assert len(warnings) > 0
        assert any("nonexistent" in w for w in warnings)

    def test_validate_strict_mode_raises(self):
        """Test strict mode raises on validation failure."""
        rules = [
            RoutePermission(r"^/api/fake$", "GET", "fake.permission"),
        ]

        with pytest.raises(ValueError) as exc:
            validate_route_permissions(rules, strict=True)

        assert "validation failed" in str(exc.value).lower()

    def test_validate_skips_empty_permission(self):
        """Test validation skips empty permission keys."""
        rules = [
            RoutePermission(r"^/api/public$", "GET", "", allow_unauthenticated=True),
        ]

        warnings = validate_route_permissions(rules)

        # Should not warn about empty permission
        assert len(warnings) == 0


# ============================================================================
# Permission Handler Factory Tests
# ============================================================================


class TestPermissionHandlerFactory:
    """Tests for permission handler factory."""

    def test_create_permission_handler(self):
        """Test creating permission handler."""
        handler = create_permission_handler("debates:read")

        assert callable(handler)

    def test_permission_handler_checks_permission(self):
        """Test permission handler invokes permission check."""
        mock_checker = MagicMock()
        mock_checker.check_permission.return_value = AuthorizationDecision(
            allowed=True,
            reason="Allowed",
            permission_key="debates:read",
        )

        handler = create_permission_handler("debates:read")
        context = AuthorizationContext(user_id="user-1")

        with patch("aragora.rbac.middleware.get_permission_checker", return_value=mock_checker):
            allowed, reason = handler(MagicMock(), context)

        assert allowed is True

    def test_permission_handler_with_resource_extractor(self):
        """Test permission handler with resource ID extractor."""
        mock_checker = MagicMock()
        mock_checker.check_permission.return_value = AuthorizationDecision(
            allowed=True,
            reason="Allowed",
            permission_key="debates:read",
        )

        def extract_id(request):
            return request.get("debate_id")

        handler = create_permission_handler("debates:read", extract_id)
        context = AuthorizationContext(user_id="user-1")
        request = {"debate_id": "debate-123"}

        with patch("aragora.rbac.middleware.get_permission_checker", return_value=mock_checker):
            allowed, reason = handler(request, context)

        # Verify resource_id was passed
        mock_checker.check_permission.assert_called_with(context, "debates:read", "debate-123")


# ============================================================================
# Global Middleware Tests
# ============================================================================


class TestGlobalMiddleware:
    """Tests for global middleware instance."""

    def test_get_middleware_returns_instance(self):
        """Test get_middleware returns an instance."""
        # Reset global state
        import aragora.rbac.middleware as middleware_module

        middleware_module._middleware = None

        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = get_middleware()

        assert middleware is not None
        assert isinstance(middleware, RBACMiddleware)

    def test_get_middleware_returns_same_instance(self):
        """Test get_middleware returns singleton."""
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware1 = get_middleware()
            middleware2 = get_middleware()

        assert middleware1 is middleware2

    def test_set_middleware_replaces_instance(self):
        """Test set_middleware replaces global instance."""
        config = RBACMiddlewareConfig(bypass_paths={"/custom"})
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            custom = RBACMiddleware(config, validate_permissions=False)

            set_middleware(custom)
            retrieved = get_middleware()

        assert retrieved is custom
        assert "/custom" in retrieved.config.bypass_paths


# ============================================================================
# Convenience Function Tests
# ============================================================================


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_check_route_access_allowed(self):
        """Test check_route_access for allowed route."""
        config = RBACMiddlewareConfig(
            bypass_paths={"/health"},
        )
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(config, validate_permissions=False)
            set_middleware(middleware)

            allowed, reason = check_route_access("/health", "GET", None)

        assert allowed is True

    def test_check_route_access_denied(self):
        """Test check_route_access for denied route."""
        config = RBACMiddlewareConfig(
            bypass_paths=set(),
            route_permissions=[],
            default_authenticated=True,
        )
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(config, validate_permissions=False)
            set_middleware(middleware)

            allowed, reason = check_route_access("/api/debates", "GET", None)

        assert allowed is False


# ============================================================================
# Default Route Permissions Tests
# ============================================================================


class TestDefaultRoutePermissions:
    """Tests for default route permissions."""

    def test_debates_routes_defined(self):
        """Test debate routes are defined."""
        patterns = [
            r.pattern.pattern for r in DEFAULT_ROUTE_PERMISSIONS if hasattr(r.pattern, "pattern")
        ]

        assert any("debates" in p for p in patterns)

    def test_admin_routes_defined(self):
        """Test admin routes are defined."""
        patterns = [
            r.pattern.pattern for r in DEFAULT_ROUTE_PERMISSIONS if hasattr(r.pattern, "pattern")
        ]

        assert any("admin" in p for p in patterns)

    def test_auth_routes_allow_unauthenticated(self):
        """Test auth routes allow unauthenticated access."""
        auth_rules = [
            r
            for r in DEFAULT_ROUTE_PERMISSIONS
            if hasattr(r.pattern, "pattern") and "auth/login" in r.pattern.pattern
        ]

        assert len(auth_rules) > 0
        assert all(r.allow_unauthenticated for r in auth_rules)

    def test_webhook_routes_allow_unauthenticated(self):
        """Test external webhook routes allow unauthenticated access."""
        webhook_rules = [
            r
            for r in DEFAULT_ROUTE_PERMISSIONS
            if hasattr(r.pattern, "pattern") and "webhook" in r.pattern.pattern.lower()
        ]

        # Most webhook routes should allow unauthenticated
        unauthenticated = [r for r in webhook_rules if r.allow_unauthenticated]
        assert len(unauthenticated) > 0

    def test_health_routes_allow_unauthenticated(self):
        """Test health routes are accessible."""
        # Health routes may be in bypass_paths or allow_unauthenticated
        health_rules = [
            r
            for r in DEFAULT_ROUTE_PERMISSIONS
            if hasattr(r.pattern, "pattern") and "health" in r.pattern.pattern.lower()
        ]

        # All health rules should allow unauthenticated
        assert all(r.allow_unauthenticated for r in health_rules)

    @pytest.mark.parametrize(
        "path,method,expected_permission",
        [
            ("/api/v1/decisions/plans", "GET", "decisions.read"),
            ("/api/v1/decisions/plans", "POST", "decisions.create"),
            ("/api/v1/decisions/plans/plan-123", "GET", "decisions.read"),
            ("/api/v1/decisions/plans/plan-123/outcome", "GET", "decisions.read"),
            ("/api/v1/decisions/plans/plan-123/approve", "POST", "decisions.update"),
            ("/api/v1/decisions/plans/plan-123/reject", "POST", "decisions.update"),
            ("/api/v1/decisions/plans/plan-123/execute", "POST", "decisions.update"),
            ("/api/decisions/plans", "GET", "decisions.read"),
            ("/api/decisions/plans", "POST", "decisions.create"),
            ("/api/v1/settlements", "GET", "settlements:read"),
            ("/api/v1/settlements/history", "GET", "settlements:read"),
            ("/api/v1/settlements/summary", "GET", "settlements:read"),
            ("/api/v1/settlements/settlement-123", "GET", "settlements:read"),
            ("/api/v1/settlements/agent/demo/accuracy", "GET", "settlements:read"),
            ("/api/v1/settlements/settlement-123/settle", "POST", "settlements:write"),
            ("/api/v1/settlements/batch", "POST", "settlements:write"),
        ],
    )
    def test_decision_plan_routes_have_explicit_permissions(
        self,
        path: str,
        method: str,
        expected_permission: str,
    ):
        """Decision plan routes should not fall through as auth-only endpoints."""
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(validate_permissions=False)
            assert middleware.get_required_permission(path, method) == expected_permission

    def test_settlement_routes_resolve_for_standard_roles(self):
        """Settlement routes should allow read access to members and write access to admins."""
        middleware = RBACMiddleware(validate_permissions=False)

        member = AuthorizationContext(user_id="member-1", org_id="org-1", roles={"member"})
        admin = AuthorizationContext(user_id="admin-1", org_id="org-1", roles={"admin"})
        owner = AuthorizationContext(user_id="owner-1", org_id="org-1", roles={"owner"})

        member_read = middleware.check_request("/api/v1/settlements", "GET", member)
        member_write = middleware.check_request("/api/v1/settlements/batch", "POST", member)
        admin_write = middleware.check_request("/api/v1/settlements/batch", "POST", admin)
        owner_write = middleware.check_request("/api/v1/settlements/batch", "POST", owner)

        assert member_read[0] is True
        assert member_read[2] == "settlements:read"
        assert "settlements.read" in member_read[1]

        assert member_write[0] is False
        assert member_write[2] == "settlements:write"
        assert "settlements.write" in member_write[1]

        assert admin_write[0] is True
        assert admin_write[2] == "settlements:write"
        assert "settlements.write" in admin_write[1]

        assert owner_write[0] is True
        assert owner_write[2] == "settlements:write"
        assert "settlements.write" in owner_write[1]


# ============================================================================
# Bypass Path Prefix Tests
# ============================================================================


class TestBypassPathPrefix:
    """Tests for bypass path prefix matching."""

    def test_bypass_path_prefix_match(self):
        """Test bypass paths ending with / match prefixes."""
        config = RBACMiddlewareConfig(
            bypass_paths={"/api/docs/"},  # Trailing slash
            route_permissions=[],
        )
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(config, validate_permissions=False)

            # Should match prefix
            allowed, reason, _ = middleware.check_request("/api/docs/swagger", "GET", None)

            assert allowed is True
            assert "bypass" in reason.lower()

    def test_bypass_path_exact_match(self):
        """Test bypass paths without trailing slash require exact match."""
        config = RBACMiddlewareConfig(
            bypass_paths={"/health"},  # No trailing slash
            route_permissions=[],
            default_authenticated=True,
        )
        with patch("aragora.rbac.middleware.get_permission_checker") as mock_get:
            mock_get.return_value = MagicMock()
            middleware = RBACMiddleware(config, validate_permissions=False)

            # Exact match works
            allowed, _, _ = middleware.check_request("/health", "GET", None)
            assert allowed is True

            # Prefix does NOT match
            allowed, reason, _ = middleware.check_request("/health/detailed", "GET", None)
            # Either matches no rule or requires auth
            # In this case it requires auth since default_authenticated=True
