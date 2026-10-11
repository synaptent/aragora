"""
Tests for RBAC Decorators.

Tests cover:
- @require_permission decorator
- @require_role decorator
- @require_owner and @require_admin decorators
- @require_org_access decorator
- @require_self_or_admin decorator
- @with_permission_context decorator
- Error handling and exceptions
"""

import pytest
from unittest.mock import MagicMock

from aragora.rbac.decorators import (
    PermissionDeniedError,
    RoleRequiredError,
    require_permission,
    require_role,
    require_owner,
    require_admin,
    require_org_access,
    require_self_or_admin,
    with_permission_context,
)
from aragora.rbac.checker import PermissionChecker, set_permission_checker
from aragora.rbac.models import AuthorizationContext


class TestRequirePermission:
    """Tests for @require_permission decorator."""

    @pytest.fixture(autouse=True)
    def setup_checker(self):
        """Set up a fresh permission checker for each test."""
        checker = PermissionChecker(enable_cache=False)
        set_permission_checker(checker)
        yield
        set_permission_checker(None)

    def test_allows_when_permission_granted(self):
        """Decorator allows execution when permission is granted."""

        @require_permission("debates:read")
        def read_debate(context: AuthorizationContext) -> str:
            return "success"

        context = AuthorizationContext(
            user_id="user-1",
            permissions={"debates:read"},
        )
        result = read_debate(context)
        assert result == "success"

    def test_denies_when_permission_missing(self):
        """Decorator raises PermissionDeniedError when permission missing."""

        @require_permission("debates:delete")
        def delete_debate(context: AuthorizationContext) -> str:
            return "success"

        context = AuthorizationContext(
            user_id="user-1",
            permissions={"debates:read"},
        )

        with pytest.raises(PermissionDeniedError) as exc_info:
            delete_debate(context)

        # Permission key is normalized to dot format internally
        assert exc_info.value.permission_key == "debates.delete"

    def test_raises_when_no_context(self):
        """Decorator raises when no AuthorizationContext found."""
        from unittest.mock import patch

        @require_permission("debates:read")
        def read_debate() -> str:
            return "success"

        with patch("aragora.server.auth.auth_config") as mock_auth:
            mock_auth.enabled = True
            with pytest.raises(PermissionDeniedError) as exc_info:
                read_debate()

        assert "No AuthorizationContext found" in str(exc_info.value)

    def test_extracts_context_from_kwargs(self):
        """Decorator extracts context from kwargs."""

        @require_permission("debates:read")
        def read_debate(context: AuthorizationContext, debate_id: str) -> str:
            return f"debate-{debate_id}"

        context = AuthorizationContext(
            user_id="user-1",
            permissions={"debates:read"},
        )
        result = read_debate(context=context, debate_id="123")
        assert result == "debate-123"

    def test_extracts_resource_id_from_kwargs(self):
        """Decorator extracts resource ID from specified parameter."""

        @require_permission("debates:update", resource_id_param="debate_id")
        def update_debate(context: AuthorizationContext, debate_id: str) -> str:
            return f"updated-{debate_id}"

        context = AuthorizationContext(
            user_id="user-1",
            permissions={"debates:update"},
        )
        result = update_debate(context, debate_id="123")
        assert result == "updated-123"

    def test_on_denied_callback(self):
        """Decorator calls on_denied callback when permission denied."""
        callback_called = []

        def on_denied(decision):
            callback_called.append(decision)

        @require_permission("debates:delete", on_denied=on_denied)
        def delete_debate(context: AuthorizationContext) -> str:
            return "success"

        context = AuthorizationContext(
            user_id="user-1",
            permissions={"debates:read"},
        )

        with pytest.raises(PermissionDeniedError):
            delete_debate(context)

        assert len(callback_called) == 1
        assert callback_called[0].allowed is False

    @pytest.mark.asyncio
    async def test_async_function_support(self):
        """Decorator works with async functions."""

        @require_permission("debates:read")
        async def read_debate(context: AuthorizationContext) -> str:
            return "async-success"

        context = AuthorizationContext(
            user_id="user-1",
            permissions={"debates:read"},
        )
        result = await read_debate(context)
        assert result == "async-success"

    @pytest.mark.asyncio
    async def test_async_raises_on_denied(self):
        """Async decorator raises PermissionDeniedError when denied."""

        @require_permission("debates:delete")
        async def delete_debate(context: AuthorizationContext) -> str:
            return "success"

        context = AuthorizationContext(
            user_id="user-1",
            permissions={"debates:read"},
        )

        with pytest.raises(PermissionDeniedError):
            await delete_debate(context)

    def test_auto_audit_emits_audit_event_on_denial(self):
        """auto_audit=True (default) emits audit event when permission denied."""
        from unittest.mock import patch

        @require_permission("debates:delete")  # auto_audit=True by default
        def delete_debate(context: AuthorizationContext) -> str:
            return "success"

        context = AuthorizationContext(
            user_id="user-1",
            permissions={"debates:read"},
        )

        with patch("aragora.observability.unified_audit.audit_access") as mock_audit:
            with pytest.raises(PermissionDeniedError):
                delete_debate(context)

            # Verify audit was called
            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args.kwargs
            assert call_kwargs["user_id"] == "user-1"
            assert call_kwargs["granted"] is False
            assert "delete" in call_kwargs["permission"]

    def test_auto_audit_disabled(self):
        """auto_audit=False prevents automatic audit events."""
        from unittest.mock import patch

        @require_permission("debates:delete", auto_audit=False)
        def delete_debate(context: AuthorizationContext) -> str:
            return "success"

        context = AuthorizationContext(
            user_id="user-1",
            permissions={"debates:read"},
        )

        with patch("aragora.observability.unified_audit.audit_access") as mock_audit:
            with pytest.raises(PermissionDeniedError):
                delete_debate(context)

            # audit should NOT be called when auto_audit=False
            mock_audit.assert_not_called()

    def test_on_denied_overrides_auto_audit(self):
        """Explicit on_denied callback overrides default auto_audit behavior."""
        from unittest.mock import patch

        custom_callback_called = []

        def custom_callback(decision):
            custom_callback_called.append(decision)

        @require_permission("debates:delete", on_denied=custom_callback)
        def delete_debate(context: AuthorizationContext) -> str:
            return "success"

        context = AuthorizationContext(
            user_id="user-1",
            permissions={"debates:read"},
        )

        with patch("aragora.observability.unified_audit.audit_access") as mock_audit:
            with pytest.raises(PermissionDeniedError):
                delete_debate(context)

            # Custom callback should be called, not audit_access
            assert len(custom_callback_called) == 1
            # audit_access should NOT be called when on_denied is provided
            mock_audit.assert_not_called()

    def test_auto_audit_handles_import_error_gracefully(self):
        """auto_audit handles missing audit module gracefully."""
        from unittest.mock import patch

        @require_permission("debates:delete")  # auto_audit=True by default
        def delete_debate(context: AuthorizationContext) -> str:
            return "success"

        context = AuthorizationContext(
            user_id="user-1",
            permissions={"debates:read"},
        )

        # Simulate audit import failure
        def raise_import_error(*args, **kwargs):
            raise ImportError("Module not available")

        with patch(
            "aragora.observability.unified_audit.audit_access", side_effect=raise_import_error
        ):
            # Should still raise PermissionDeniedError, not crash on audit
            with pytest.raises(PermissionDeniedError):
                delete_debate(context)


class TestRequireRole:
    """Tests for @require_role decorator."""

    def test_allows_with_required_role(self):
        """Decorator allows when user has required role."""

        @require_role("admin")
        def admin_action(context: AuthorizationContext) -> str:
            return "admin-success"

        context = AuthorizationContext(
            user_id="user-1",
            roles={"admin", "editor"},
        )
        result = admin_action(context)
        assert result == "admin-success"

    def test_denies_without_required_role(self):
        """Decorator denies when user lacks required role."""

        @require_role("admin")
        def admin_action(context: AuthorizationContext) -> str:
            return "admin-success"

        context = AuthorizationContext(
            user_id="user-1",
            roles={"editor"},
        )

        with pytest.raises(RoleRequiredError) as exc_info:
            admin_action(context)

        assert "admin" in exc_info.value.required_roles

    def test_any_role_sufficient(self):
        """By default, any one of specified roles is sufficient."""

        @require_role("admin", "owner")
        def privileged_action(context: AuthorizationContext) -> str:
            return "success"

        # Admin works
        admin_ctx = AuthorizationContext(user_id="u1", roles={"admin"})
        assert privileged_action(admin_ctx) == "success"

        # Owner works
        owner_ctx = AuthorizationContext(user_id="u2", roles={"owner"})
        assert privileged_action(owner_ctx) == "success"

        # Neither fails
        editor_ctx = AuthorizationContext(user_id="u3", roles={"editor"})
        with pytest.raises(RoleRequiredError):
            privileged_action(editor_ctx)

    def test_require_all_roles(self):
        """require_all=True requires all specified roles."""

        @require_role("admin", "billing_manager", require_all=True)
        def billing_admin_action(context: AuthorizationContext) -> str:
            return "success"

        # Has both - success
        both_ctx = AuthorizationContext(
            user_id="u1",
            roles={"admin", "billing_manager"},
        )
        assert billing_admin_action(both_ctx) == "success"

        # Only admin - fails
        admin_only = AuthorizationContext(user_id="u2", roles={"admin"})
        with pytest.raises(RoleRequiredError) as exc_info:
            billing_admin_action(admin_only)
        assert "billing_manager" in exc_info.value.required_roles - exc_info.value.actual_roles

    @pytest.mark.asyncio
    async def test_async_role_check(self):
        """Decorator works with async functions."""

        @require_role("admin")
        async def async_admin_action(context: AuthorizationContext) -> str:
            return "async-admin"

        context = AuthorizationContext(user_id="u1", roles={"admin"})
        result = await async_admin_action(context)
        assert result == "async-admin"


class TestRequireOwnerAdmin:
    """Tests for @require_owner and @require_admin shortcuts."""

    def test_require_owner(self):
        """@require_owner requires owner role."""

        @require_owner()
        def owner_action(context: AuthorizationContext) -> str:
            return "owner"

        owner_ctx = AuthorizationContext(user_id="u1", roles={"owner"})
        admin_ctx = AuthorizationContext(user_id="u2", roles={"admin"})

        assert owner_action(owner_ctx) == "owner"

        with pytest.raises(RoleRequiredError):
            owner_action(admin_ctx)

    def test_require_admin(self):
        """@require_admin accepts owner or admin."""

        @require_admin()
        def admin_action(context: AuthorizationContext) -> str:
            return "admin"

        owner_ctx = AuthorizationContext(user_id="u1", roles={"owner"})
        admin_ctx = AuthorizationContext(user_id="u2", roles={"admin"})
        editor_ctx = AuthorizationContext(user_id="u3", roles={"editor"})

        assert admin_action(owner_ctx) == "admin"
        assert admin_action(admin_ctx) == "admin"

        with pytest.raises(RoleRequiredError):
            admin_action(editor_ctx)


class TestRequireOrgAccess:
    """Tests for @require_org_access decorator."""

    def test_allows_same_org(self):
        """Allows access when user belongs to the organization."""

        @require_org_access()
        def org_action(context: AuthorizationContext, org_id: str) -> str:
            return f"org-{org_id}"

        context = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
        )
        result = org_action(context, org_id="org-1")
        assert result == "org-org-1"

    def test_denies_different_org(self):
        """Denies access when user belongs to different organization."""

        @require_org_access()
        def org_action(context: AuthorizationContext, org_id: str) -> str:
            return "success"

        context = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
        )

        with pytest.raises(PermissionDeniedError):
            org_action(context, org_id="org-2")

    def test_platform_owner_can_access_any_org(self):
        """Platform owner (no org_id but owner role) can access any org."""

        @require_org_access()
        def org_action(context: AuthorizationContext, org_id: str) -> str:
            return "success"

        platform_owner = AuthorizationContext(
            user_id="platform-admin",
            org_id=None,  # Platform level
            roles={"owner"},
        )
        result = org_action(platform_owner, org_id="any-org")
        assert result == "success"

    def test_allow_none_option(self):
        """allow_none=True allows access when org_id is None."""

        @require_org_access(allow_none=True)
        def optional_org_action(context: AuthorizationContext, org_id: str = None) -> str:
            return "success"

        context = AuthorizationContext(user_id="user-1", org_id="org-1")
        result = optional_org_action(context, org_id=None)
        assert result == "success"

    def test_denies_when_org_id_required_but_none(self):
        """Denies when org_id is required but not provided."""

        @require_org_access()
        def org_action(context: AuthorizationContext, org_id: str = None) -> str:
            return "success"

        context = AuthorizationContext(user_id="user-1", org_id="org-1")

        with pytest.raises(PermissionDeniedError) as exc_info:
            org_action(context, org_id=None)

        assert "required but not provided" in str(exc_info.value)


class TestRequireSelfOrAdmin:
    """Tests for @require_self_or_admin decorator."""

    def test_allows_self_action(self):
        """Allows action when user acts on themselves."""

        @require_self_or_admin()
        def update_user(context: AuthorizationContext, user_id: str) -> str:
            return f"updated-{user_id}"

        context = AuthorizationContext(user_id="user-1", roles={"editor"})
        result = update_user(context, user_id="user-1")
        assert result == "updated-user-1"

    def test_allows_admin_on_others(self):
        """Allows admin to act on other users."""

        @require_self_or_admin()
        def update_user(context: AuthorizationContext, user_id: str) -> str:
            return f"updated-{user_id}"

        admin_ctx = AuthorizationContext(user_id="admin-1", roles={"admin"})
        result = update_user(admin_ctx, user_id="user-1")
        assert result == "updated-user-1"

    def test_denies_non_admin_on_others(self):
        """Denies non-admin acting on other users."""

        @require_self_or_admin()
        def update_user(context: AuthorizationContext, user_id: str) -> str:
            return "success"

        editor_ctx = AuthorizationContext(user_id="editor-1", roles={"editor"})

        with pytest.raises(PermissionDeniedError) as exc_info:
            update_user(editor_ctx, user_id="other-user")

        assert "own data" in str(exc_info.value)


class TestWithPermissionContext:
    """Tests for @with_permission_context decorator."""

    @pytest.fixture(autouse=True)
    def setup_checker(self):
        """Set up permission checker."""
        checker = PermissionChecker(enable_cache=False)
        set_permission_checker(checker)
        yield
        set_permission_checker(None)

    def test_builds_context_from_functions(self):
        """Decorator builds context from provided functions."""

        @with_permission_context(
            user_id_func=lambda req: req.user_id,
            org_id_func=lambda req: req.org_id,
            roles_func=lambda req: req.roles,
        )
        def action(req, context: AuthorizationContext = None) -> AuthorizationContext:
            return context

        class MockRequest:
            user_id = "user-1"
            org_id = "org-1"
            roles = {"editor"}

        result = action(MockRequest())
        assert result.user_id == "user-1"
        assert result.org_id == "org-1"
        assert result.roles == {"editor"}

    def test_works_with_require_permission(self):
        """Can be combined with @require_permission."""

        @with_permission_context(
            user_id_func=lambda req: req.user_id,
            roles_func=lambda req: req.roles,
        )
        @require_permission("debates:read")
        def read_debate(context: AuthorizationContext, req) -> str:
            return "success"

        class MockRequest:
            user_id = "user-1"
            roles = {"viewer"}

        # Viewer doesn't have debates.read
        checker = PermissionChecker(enable_cache=False)
        set_permission_checker(checker)

        # Need to manually add permissions for viewer role
        # In practice, this would come from role definitions


class TestExceptionAttributes:
    """Tests for exception classes."""

    def test_permission_denied_error_attributes(self):
        """PermissionDeniedError stores decision details."""
        from aragora.rbac.models import AuthorizationDecision

        decision = AuthorizationDecision(
            allowed=False,
            reason="Test denied",
            permission_key="debates:delete",
            resource_id="debate-123",
            context=AuthorizationContext(user_id="user-1"),
        )

        error = PermissionDeniedError("Access denied", decision)

        assert error.permission_key == "debates:delete"
        assert error.resource_id == "debate-123"
        assert error.decision == decision

    def test_role_required_error_attributes(self):
        """RoleRequiredError stores role information."""
        error = RoleRequiredError(
            "Missing roles",
            required_roles={"admin", "owner"},
            actual_roles={"editor"},
        )

        assert error.required_roles == {"admin", "owner"}
        assert error.actual_roles == {"editor"}


class TestMethodDecorators:
    """Tests for decorators on class methods."""

    @pytest.fixture(autouse=True)
    def setup_checker(self):
        checker = PermissionChecker(enable_cache=False)
        set_permission_checker(checker)
        yield
        set_permission_checker(None)

    def test_decorator_on_instance_method(self):
        """Decorators work on instance methods."""

        class DebateService:
            @require_permission("debates:read")
            def read_debate(self, context: AuthorizationContext, debate_id: str) -> str:
                return f"debate-{debate_id}"

        service = DebateService()
        context = AuthorizationContext(
            user_id="user-1",
            permissions={"debates:read"},
        )
        result = service.read_debate(context, "123")
        assert result == "debate-123"

    @pytest.mark.asyncio
    async def test_decorator_on_async_instance_method(self):
        """Decorators work on async instance methods."""

        class DebateService:
            @require_permission("debates:read")
            async def read_debate(self, context: AuthorizationContext) -> str:
                return "async-debate"

        service = DebateService()
        context = AuthorizationContext(
            user_id="user-1",
            permissions={"debates:read"},
        )
        result = await service.read_debate(context)
        assert result == "async-debate"
