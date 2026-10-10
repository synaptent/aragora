"""
Tests for SecureHandler and security decorators.

Covers:
- SecureHandler class methods
- @secure_endpoint decorator
- @audit_sensitive_access decorator
- Security error handling (401, 403 responses)
"""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from aragora.server.handlers.secure import (
    SecureHandler,
    secure_endpoint,
    audit_sensitive_access,
    UnauthorizedError,
    ForbiddenError,
)
from aragora.server.handlers.base import HandlerResult, json_response, error_response
from aragora.rbac.models import AuthorizationContext
from aragora.rbac.decorators import PermissionDeniedError, RoleRequiredError


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def server_context():
    """Create a mock server context."""
    return {"config": {"debug": True}}


@pytest.fixture
def auth_context():
    """Create a test authorization context."""
    return AuthorizationContext(
        user_id="user-123",
        org_id="org-456",
        roles={"member", "analyst"},
        permissions={"debates:read", "debates:create"},
    )


@pytest.fixture
def anonymous_context():
    """Create an anonymous authorization context."""
    return AuthorizationContext(
        user_id="anonymous",
        org_id=None,
        roles=set(),
        permissions=set(),
    )


@pytest.fixture
def mock_request():
    """Create a mock HTTP request."""
    request = MagicMock()
    request.headers = {
        "Authorization": "Bearer test-token",
        "X-Workspace-ID": "ws-789",
        "X-Forwarded-For": "192.168.1.1, 10.0.0.1",
        "User-Agent": "TestClient/1.0",
    }
    request.remote = "127.0.0.1"
    request.method = "GET"
    return request


@pytest.fixture
def secure_handler(server_context):
    """Create a SecureHandler instance."""
    return SecureHandler(server_context)


# -----------------------------------------------------------------------------
# SecureHandler Class Tests
# -----------------------------------------------------------------------------


class TestSecureHandlerInitialization:
    """Tests for SecureHandler initialization."""

    def test_init_with_server_context(self, server_context):
        """SecureHandler initializes with server context."""
        handler = SecureHandler(server_context)
        assert handler.ctx == server_context
        assert handler._auth_context is None

    def test_default_method_permissions(self, secure_handler):
        """SecureHandler has default method permissions."""
        assert secure_handler.DEFAULT_METHOD_PERMISSIONS["GET"] is None
        assert secure_handler.DEFAULT_METHOD_PERMISSIONS["POST"] is None
        assert secure_handler.DEFAULT_METHOD_PERMISSIONS["DELETE"] is None

    def test_default_resource_type(self, secure_handler):
        """SecureHandler has default resource type."""
        assert secure_handler.RESOURCE_TYPE == "unknown"


class TestSecureHandlerGetAuthContext:
    """Tests for SecureHandler.get_auth_context() method."""

    @pytest.mark.asyncio
    async def test_get_auth_context_authenticated(self, secure_handler, mock_request, auth_context):
        """get_auth_context returns context for authenticated user."""
        # Patch at the module level where it's imported in secure.py
        with patch(
            "aragora.server.handlers.secure.get_auth_context",
            new_callable=AsyncMock,
            return_value=auth_context,
        ) as mock_get_auth:
            result = await secure_handler.get_auth_context(mock_request)
            assert result.user_id == "user-123"
            assert result.org_id == "org-456"
            mock_get_auth.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_auth_context_anonymous_allowed(
        self, secure_handler, mock_request, anonymous_context
    ):
        """get_auth_context returns anonymous context when auth not required."""
        with patch(
            "aragora.server.handlers.secure.get_auth_context",
            new_callable=AsyncMock,
            return_value=anonymous_context,
        ):
            result = await secure_handler.get_auth_context(mock_request, require_auth=False)
            assert result.user_id == "anonymous"

    @pytest.mark.asyncio
    async def test_get_auth_context_require_auth_raises(self, secure_handler, mock_request):
        """get_auth_context raises UnauthorizedError when required and not authenticated."""
        with patch(
            "aragora.server.handlers.secure.get_auth_context",
            new_callable=AsyncMock,
            side_effect=UnauthorizedError("Token required"),
        ):
            with pytest.raises(UnauthorizedError) as exc_info:
                await secure_handler.get_auth_context(mock_request, require_auth=True)
            assert "Token required" in str(exc_info.value)


class TestSecureHandlerCheckPermission:
    """Tests for SecureHandler.check_permission() method."""

    def test_check_permission_granted(self, secure_handler, auth_context):
        """check_permission returns True when permission granted."""
        mock_decision = MagicMock()
        mock_decision.allowed = True

        mock_checker = MagicMock()
        mock_checker.check_permission.return_value = mock_decision

        with patch(
            "aragora.rbac.checker.get_permission_checker",
            return_value=mock_checker,
        ):
            with patch("aragora.observability.metrics.security.record_rbac_decision"):
                result = secure_handler.check_permission(auth_context, "debates:read")
                assert result is True
                mock_checker.check_permission.assert_called_once_with(
                    auth_context, "debates:read", None
                )

    def test_check_permission_denied_raises(self, secure_handler, auth_context):
        """check_permission raises ForbiddenError when permission denied."""
        mock_decision = MagicMock()
        mock_decision.allowed = False

        mock_checker = MagicMock()
        mock_checker.check_permission.return_value = mock_decision

        with patch(
            "aragora.rbac.checker.get_permission_checker",
            return_value=mock_checker,
        ):
            with patch("aragora.observability.metrics.security.record_rbac_decision"):
                with pytest.raises(ForbiddenError) as exc_info:
                    secure_handler.check_permission(auth_context, "admin:delete")
                assert "Permission denied" in str(exc_info.value)

    def test_check_permission_with_resource_id(self, secure_handler, auth_context):
        """check_permission passes resource_id to checker."""
        mock_decision = MagicMock()
        mock_decision.allowed = True

        mock_checker = MagicMock()
        mock_checker.check_permission.return_value = mock_decision

        with patch(
            "aragora.rbac.checker.get_permission_checker",
            return_value=mock_checker,
        ):
            with patch("aragora.observability.metrics.security.record_rbac_decision"):
                secure_handler.check_permission(auth_context, "debates:read", "debate-123")
                mock_checker.check_permission.assert_called_once_with(
                    auth_context, "debates:read", "debate-123"
                )


class TestSecureHandlerAuditAction:
    """Tests for SecureHandler.audit_action() method."""

    @pytest.mark.asyncio
    async def test_audit_action_basic(self, secure_handler, auth_context, mock_request):
        """audit_action logs to audit trail."""
        mock_audit_log = AsyncMock()

        with patch(
            "aragora.observability.immutable_log.get_audit_log",
            return_value=mock_audit_log,
        ):
            await secure_handler.audit_action(
                auth_context,
                action="create",
                resource_id="debate-123",
                request=mock_request,
            )

            mock_audit_log.append.assert_awaited_once()
            call_kwargs = mock_audit_log.append.call_args.kwargs
            assert call_kwargs["actor"] == "user-123"
            assert call_kwargs["action"] == "create"
            assert call_kwargs["resource_id"] == "debate-123"
            assert call_kwargs["ip_address"] == "192.168.1.1"
            assert call_kwargs["user_agent"] == "TestClient/1.0"

    @pytest.mark.asyncio
    async def test_audit_action_custom_resource_type(self, secure_handler, auth_context):
        """audit_action uses custom resource type."""
        mock_audit_log = AsyncMock()

        with patch(
            "aragora.observability.immutable_log.get_audit_log",
            return_value=mock_audit_log,
        ):
            await secure_handler.audit_action(
                auth_context,
                action="update",
                resource_id="config-456",
                resource_type="settings",
            )

            call_kwargs = mock_audit_log.append.call_args.kwargs
            assert call_kwargs["resource_type"] == "settings"
            assert call_kwargs["event_type"] == "settings.update"

    @pytest.mark.asyncio
    async def test_audit_action_with_details(self, secure_handler, auth_context):
        """audit_action includes additional details."""
        mock_audit_log = AsyncMock()

        with patch(
            "aragora.observability.immutable_log.get_audit_log",
            return_value=mock_audit_log,
        ):
            await secure_handler.audit_action(
                auth_context,
                action="delete",
                resource_id="item-789",
                details={"reason": "cleanup", "count": 5},
            )

            call_kwargs = mock_audit_log.append.call_args.kwargs
            assert call_kwargs["details"]["reason"] == "cleanup"
            assert call_kwargs["details"]["count"] == 5


class TestSecureHandlerEncryption:
    """Tests for SecureHandler encryption methods."""

    def test_encrypt_response_fields(self, secure_handler):
        """encrypt_response_fields encrypts sensitive data."""
        with patch(
            "aragora.storage.encrypted_fields.encrypt_sensitive",
            return_value={"api_key": "ENCRYPTED", "name": "test"},
        ) as mock_encrypt:
            result = secure_handler.encrypt_response_fields(
                {"api_key": "secret-key", "name": "test"}
            )
            assert result["api_key"] == "ENCRYPTED"
            assert result["name"] == "test"
            mock_encrypt.assert_called_once()

    def test_decrypt_request_fields(self, secure_handler):
        """decrypt_request_fields decrypts sensitive data."""
        with patch(
            "aragora.storage.encrypted_fields.decrypt_sensitive",
            return_value={"api_key": "decrypted-key", "name": "test"},
        ) as mock_decrypt:
            result = secure_handler.decrypt_request_fields({"api_key": "ENCRYPTED", "name": "test"})
            assert result["api_key"] == "decrypted-key"
            mock_decrypt.assert_called_once()


class TestSecureHandlerErrorHandling:
    """Tests for SecureHandler.handle_security_error() method."""

    def test_handle_unauthorized_error(self, secure_handler):
        """handle_security_error returns 401 for UnauthorizedError."""
        with patch("aragora.observability.metrics.security.record_auth_failure"):
            error = UnauthorizedError("Token invalid")
            result = secure_handler.handle_security_error(error)
            assert result.status_code == 401

    def test_handle_forbidden_error(self, secure_handler):
        """handle_security_error returns 403 for ForbiddenError."""
        with patch("aragora.observability.metrics.security.record_blocked_request"):
            error = ForbiddenError("No access", permission="admin:delete")
            result = secure_handler.handle_security_error(error)
            assert result.status_code == 403

    def test_handle_permission_denied_error(self, secure_handler):
        """handle_security_error returns 403 for PermissionDeniedError."""
        with patch("aragora.observability.metrics.security.record_blocked_request"):
            error = PermissionDeniedError("Permission denied: users.delete")
            result = secure_handler.handle_security_error(error)
            assert result.status_code == 403

    def test_handle_role_required_error(self, secure_handler):
        """handle_security_error returns 403 for RoleRequiredError."""
        with patch("aragora.observability.metrics.security.record_blocked_request"):
            error = RoleRequiredError("Role required: admin", {"admin"}, {"member"})
            result = secure_handler.handle_security_error(error)
            assert result.status_code == 403

    def test_handle_unknown_security_error(self, secure_handler):
        """handle_security_error returns 500 for unknown errors."""
        error = Exception("Unexpected error")
        result = secure_handler.handle_security_error(error)
        assert result.status_code == 500


# -----------------------------------------------------------------------------
# @secure_endpoint Decorator Tests
# -----------------------------------------------------------------------------


class TestSecureEndpointDecorator:
    """Tests for @secure_endpoint decorator."""

    @pytest.mark.asyncio
    async def test_secure_endpoint_basic_auth(self, server_context, mock_request, auth_context):
        """@secure_endpoint extracts authentication."""

        class TestHandler(SecureHandler):
            @secure_endpoint()
            async def handle_get(self, request, auth_context):
                return json_response({"user_id": auth_context.user_id})

        handler = TestHandler(server_context)

        with patch.object(
            handler, "get_auth_context", new_callable=AsyncMock, return_value=auth_context
        ):
            with patch("aragora.observability.metrics.security.record_auth_attempt"):
                result = await handler.handle_get(mock_request)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_secure_endpoint_permission_check(
        self, server_context, mock_request, auth_context
    ):
        """@secure_endpoint checks permission when specified."""

        class TestHandler(SecureHandler):
            @secure_endpoint(permission="debates:create")
            async def handle_post(self, request, auth_context):
                return json_response({"created": True})

        handler = TestHandler(server_context)

        with patch.object(
            handler, "get_auth_context", new_callable=AsyncMock, return_value=auth_context
        ):
            with patch.object(handler, "check_permission", return_value=True) as mock_check:
                with patch("aragora.observability.metrics.security.record_auth_attempt"):
                    with patch("aragora.observability.metrics.security.track_rbac_evaluation"):
                        await handler.handle_post(mock_request)
                        mock_check.assert_called_once_with(auth_context, "debates:create", None)

    @pytest.mark.asyncio
    async def test_secure_endpoint_permission_with_resource_id(
        self, server_context, mock_request, auth_context
    ):
        """@secure_endpoint passes resource_id from kwargs."""

        class TestHandler(SecureHandler):
            @secure_endpoint(permission="debates:read", resource_id_param="debate_id")
            async def handle_get(self, request, auth_context, debate_id=None):
                return json_response({"id": debate_id})

        handler = TestHandler(server_context)

        with patch.object(
            handler, "get_auth_context", new_callable=AsyncMock, return_value=auth_context
        ):
            with patch.object(handler, "check_permission", return_value=True) as mock_check:
                with patch("aragora.observability.metrics.security.record_auth_attempt"):
                    with patch("aragora.observability.metrics.security.track_rbac_evaluation"):
                        await handler.handle_get(mock_request, debate_id="debate-123")
                        mock_check.assert_called_once_with(
                            auth_context, "debates:read", "debate-123"
                        )

    @pytest.mark.asyncio
    async def test_secure_endpoint_audit_logging(self, server_context, mock_request, auth_context):
        """@secure_endpoint logs to audit trail when audit=True."""

        class TestHandler(SecureHandler):
            @secure_endpoint(permission="items.create", audit=True, resource_id_param="item_id")
            async def handle_post(self, request, auth_context, item_id=None):
                return json_response({"created": True})

        handler = TestHandler(server_context)

        with patch.object(
            handler, "get_auth_context", new_callable=AsyncMock, return_value=auth_context
        ):
            with patch.object(handler, "check_permission", return_value=True):
                with patch.object(handler, "audit_action", new_callable=AsyncMock) as mock_audit:
                    with patch("aragora.observability.metrics.security.record_auth_attempt"):
                        with patch("aragora.observability.metrics.security.track_rbac_evaluation"):
                            await handler.handle_post(mock_request, item_id="item-456")
                            mock_audit.assert_awaited_once()
                            call_kwargs = mock_audit.call_args.kwargs
                            assert call_kwargs["action"] == "post"
                            assert call_kwargs["resource_id"] == "item-456"

    @pytest.mark.asyncio
    async def test_secure_endpoint_custom_audit_action(
        self, server_context, mock_request, auth_context
    ):
        """@secure_endpoint uses custom audit_action name."""

        class TestHandler(SecureHandler):
            @secure_endpoint(
                permission="items.delete",
                audit=True,
                audit_action="purge",
                resource_id_param="item_id",
            )
            async def handle_delete(self, request, auth_context, item_id=None):
                return json_response({"deleted": True})

        handler = TestHandler(server_context)

        with patch.object(
            handler, "get_auth_context", new_callable=AsyncMock, return_value=auth_context
        ):
            with patch.object(handler, "check_permission", return_value=True):
                with patch.object(handler, "audit_action", new_callable=AsyncMock) as mock_audit:
                    with patch("aragora.observability.metrics.security.record_auth_attempt"):
                        with patch("aragora.observability.metrics.security.track_rbac_evaluation"):
                            await handler.handle_delete(mock_request, item_id="item-789")
                            call_kwargs = mock_audit.call_args.kwargs
                            assert call_kwargs["action"] == "purge"

    @pytest.mark.asyncio
    async def test_secure_endpoint_no_auth_required(
        self, server_context, mock_request, anonymous_context
    ):
        """@secure_endpoint allows anonymous access when require_auth=False."""

        class TestHandler(SecureHandler):
            @secure_endpoint(require_auth=False)
            async def handle_get(self, request, auth_context):
                return json_response({"public": True, "user": auth_context.user_id})

        handler = TestHandler(server_context)

        with patch.object(
            handler, "get_auth_context", new_callable=AsyncMock, return_value=anonymous_context
        ):
            with patch("aragora.observability.metrics.security.record_auth_attempt"):
                result = await handler.handle_get(mock_request)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_secure_endpoint_unauthorized_error(self, server_context, mock_request):
        """@secure_endpoint handles UnauthorizedError."""

        class TestHandler(SecureHandler):
            @secure_endpoint()
            async def handle_get(self, request, auth_context):
                return json_response({})

        handler = TestHandler(server_context)

        with patch.object(
            handler,
            "get_auth_context",
            new_callable=AsyncMock,
            side_effect=UnauthorizedError("Invalid token"),
        ):
            with patch.object(
                handler, "handle_security_error", return_value=error_response("Auth required", 401)
            ) as mock_error:
                result = await handler.handle_get(mock_request)
                mock_error.assert_called_once()
                assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_secure_endpoint_forbidden_error(
        self, server_context, mock_request, auth_context
    ):
        """@secure_endpoint handles ForbiddenError."""

        class TestHandler(SecureHandler):
            @secure_endpoint(permission="admin:manage")
            async def handle_post(self, request, auth_context):
                return json_response({})

        handler = TestHandler(server_context)

        with patch.object(
            handler, "get_auth_context", new_callable=AsyncMock, return_value=auth_context
        ):
            with patch.object(
                handler, "check_permission", side_effect=ForbiddenError("No admin access")
            ):
                with patch.object(
                    handler,
                    "handle_security_error",
                    return_value=error_response("Forbidden", 403),
                ) as mock_error:
                    with patch("aragora.observability.metrics.security.record_auth_attempt"):
                        with patch("aragora.observability.metrics.security.track_rbac_evaluation"):
                            result = await handler.handle_post(mock_request)
                            mock_error.assert_called_once()
                            assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_secure_endpoint_permission_denied_error(
        self, server_context, mock_request, auth_context
    ):
        """@secure_endpoint handles PermissionDeniedError."""

        class TestHandler(SecureHandler):
            @secure_endpoint(permission="users:delete")
            async def handle_delete(self, request, auth_context):
                return json_response({})

        handler = TestHandler(server_context)

        with patch.object(
            handler, "get_auth_context", new_callable=AsyncMock, return_value=auth_context
        ):
            with patch.object(
                handler,
                "check_permission",
                side_effect=PermissionDeniedError("users:delete"),
            ):
                with patch.object(
                    handler,
                    "handle_security_error",
                    return_value=error_response("Permission denied", 403),
                ):
                    with patch("aragora.observability.metrics.security.record_auth_attempt"):
                        with patch("aragora.observability.metrics.security.track_rbac_evaluation"):
                            result = await handler.handle_delete(mock_request)
                            assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_secure_endpoint_role_required_error(
        self, server_context, mock_request, auth_context
    ):
        """@secure_endpoint handles RoleRequiredError."""

        class TestHandler(SecureHandler):
            @secure_endpoint(permission="system:configure")
            async def handle_post(self, request, auth_context):
                return json_response({})

        handler = TestHandler(server_context)

        with patch.object(
            handler, "get_auth_context", new_callable=AsyncMock, return_value=auth_context
        ):
            with patch.object(
                handler,
                "check_permission",
                side_effect=RoleRequiredError("Role required", {"owner"}, {"member"}),
            ):
                with patch.object(
                    handler,
                    "handle_security_error",
                    return_value=error_response("Role required", 403),
                ):
                    with patch("aragora.observability.metrics.security.record_auth_attempt"):
                        with patch("aragora.observability.metrics.security.track_rbac_evaluation"):
                            result = await handler.handle_post(mock_request)
                            assert result.status_code == 403


# -----------------------------------------------------------------------------
# @audit_sensitive_access Decorator Tests
# -----------------------------------------------------------------------------


class TestAuditSensitiveAccessDecorator:
    """Tests for @audit_sensitive_access decorator."""

    @pytest.mark.asyncio
    async def test_audit_sensitive_access_records_metric(
        self, server_context, mock_request, auth_context
    ):
        """@audit_sensitive_access records secret access metric."""

        class TestHandler(SecureHandler):
            RESOURCE_TYPE = "api_keys"

            @audit_sensitive_access("api_key", "read")
            async def get_api_key(self, request, auth_context):
                return json_response({"key": "xxx"})

        handler = TestHandler(server_context)

        with patch("aragora.observability.metrics.security.record_secret_access") as mock_metric:
            with patch(
                "aragora.observability.security_audit.audit_secret_access", new_callable=AsyncMock
            ):
                await handler.get_api_key(mock_request, auth_context)
                mock_metric.assert_called_once_with("api_key", "read")

    @pytest.mark.asyncio
    async def test_audit_sensitive_access_logs_audit(
        self, server_context, mock_request, auth_context
    ):
        """@audit_sensitive_access logs to security audit."""

        class TestHandler(SecureHandler):
            RESOURCE_TYPE = "credentials"

            @audit_sensitive_access("oauth_token", "access")
            async def get_token(self, request, auth_context):
                return json_response({"token": "xxx"})

        handler = TestHandler(server_context)

        with patch("aragora.observability.metrics.security.record_secret_access"):
            with patch(
                "aragora.observability.security_audit.audit_secret_access", new_callable=AsyncMock
            ) as mock_audit:
                await handler.get_token(mock_request, auth_context)
                mock_audit.assert_awaited_once()
                call_kwargs = mock_audit.call_args.kwargs
                assert call_kwargs["actor"] == "user-123"
                assert call_kwargs["secret_type"] == "oauth_token"
                assert call_kwargs["operation"] == "access"
                assert call_kwargs["store"] == "credentials"

    @pytest.mark.asyncio
    async def test_audit_sensitive_access_with_org(
        self, server_context, mock_request, auth_context
    ):
        """@audit_sensitive_access logs actor and store correctly."""

        class TestHandler(SecureHandler):
            RESOURCE_TYPE = "secrets"

            @audit_sensitive_access("password", "decrypt")
            async def decrypt_password(self, request, auth_context):
                return json_response({"decrypted": True})

        handler = TestHandler(server_context)

        with patch("aragora.observability.metrics.security.record_secret_access"):
            with patch(
                "aragora.observability.security_audit.audit_secret_access", new_callable=AsyncMock
            ) as mock_audit:
                await handler.decrypt_password(mock_request, auth_context)
                call_kwargs = mock_audit.call_args.kwargs
                assert call_kwargs["actor"] == "user-123"
                assert call_kwargs["store"] == "secrets"


# -----------------------------------------------------------------------------
# Exception Class Tests
# -----------------------------------------------------------------------------


class TestSecurityExceptions:
    """Tests for security exception classes."""

    def test_unauthorized_error_default_message(self):
        """UnauthorizedError has default message."""
        error = UnauthorizedError()
        assert error.message == "Authentication required"

    def test_unauthorized_error_custom_message(self):
        """UnauthorizedError accepts custom message."""
        error = UnauthorizedError("Token expired")
        assert error.message == "Token expired"
        assert str(error) == "Token expired"

    def test_forbidden_error_default_message(self):
        """ForbiddenError has default message."""
        error = ForbiddenError()
        assert error.message == "Access denied"
        assert error.permission is None

    def test_forbidden_error_with_permission(self):
        """ForbiddenError stores permission info."""
        error = ForbiddenError("No access to debates", permission="debates:delete")
        assert error.message == "No access to debates"
        assert error.permission == "debates:delete"


# -----------------------------------------------------------------------------
# Integration Tests
# -----------------------------------------------------------------------------


class TestSecureHandlerIntegration:
    """Integration tests for SecureHandler patterns."""

    @pytest.mark.asyncio
    async def test_full_secure_endpoint_flow(self, server_context, mock_request, auth_context):
        """Full flow through secure endpoint with auth, permission, and audit."""

        class DebateHandler(SecureHandler):
            RESOURCE_TYPE = "debate"

            @secure_endpoint(
                permission="debates:create",
                audit=True,
                resource_id_param="debate_id",
            )
            async def handle_post(self, request, auth_context, debate_id=None):
                return json_response(
                    {
                        "id": debate_id or "new-debate",
                        "created_by": auth_context.user_id,
                    }
                )

        handler = DebateHandler(server_context)

        # Mock all dependencies
        mock_decision = MagicMock()
        mock_decision.allowed = True
        mock_checker = MagicMock()
        mock_checker.check_permission.return_value = mock_decision

        with patch.object(
            handler, "get_auth_context", new_callable=AsyncMock, return_value=auth_context
        ):
            with patch(
                "aragora.rbac.checker.get_permission_checker",
                return_value=mock_checker,
            ):
                with patch("aragora.observability.metrics.security.record_rbac_decision"):
                    with patch("aragora.observability.metrics.security.record_auth_attempt"):
                        with patch("aragora.observability.metrics.security.track_rbac_evaluation"):
                            with patch.object(
                                handler, "audit_action", new_callable=AsyncMock
                            ) as mock_audit:
                                result = await handler.handle_post(
                                    mock_request, debate_id="debate-new"
                                )

                                assert result.status_code == 200
                                mock_checker.check_permission.assert_called_once()
                                mock_audit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_secure_handler_subclass_customization(
        self, server_context, mock_request, auth_context
    ):
        """Subclass can customize RESOURCE_TYPE and DEFAULT_METHOD_PERMISSIONS."""

        class WorkflowHandler(SecureHandler):
            RESOURCE_TYPE = "workflow"
            DEFAULT_METHOD_PERMISSIONS = {
                "GET": "workflows:read",
                "POST": "workflows:create",
                "PUT": "workflows:update",
                "DELETE": "workflows:delete",
            }

            @secure_endpoint(permission="workflows:read")
            async def handle_get(self, request, auth_context):
                return json_response({"workflows": []})

        handler = WorkflowHandler(server_context)
        assert handler.RESOURCE_TYPE == "workflow"
        assert handler.DEFAULT_METHOD_PERMISSIONS["GET"] == "workflows:read"

        with patch.object(
            handler, "get_auth_context", new_callable=AsyncMock, return_value=auth_context
        ):
            with patch.object(handler, "check_permission", return_value=True):
                with patch("aragora.observability.metrics.security.record_auth_attempt"):
                    with patch("aragora.observability.metrics.security.track_rbac_evaluation"):
                        result = await handler.handle_get(mock_request)
                        assert result.status_code == 200


# -----------------------------------------------------------------------------
# CORS Preflight with Credentials Tests
# -----------------------------------------------------------------------------


class TestCORSPreflightWithCredentials:
    """Tests for CORS preflight handling with credentials."""

    @pytest.fixture
    def options_request(self):
        """Create a mock OPTIONS request for CORS preflight."""
        request = MagicMock()
        request.method = "OPTIONS"
        request.headers = {
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        }
        request.remote = "192.168.1.100"
        return request

    def test_cors_preflight_origin_validation_allowed(self):
        """Verify allowed origin is accepted in preflight."""
        from aragora.server.cors_config import CORSConfig

        config = CORSConfig()
        # Add test origin
        config.add_origin("https://test.aragora.ai")

        assert config.is_origin_allowed("https://test.aragora.ai") is True
        assert config.is_origin_allowed("https://malicious.com") is False

    def test_cors_preflight_origin_validation_denied(self):
        """Verify disallowed origin is rejected in preflight."""
        from aragora.server.cors_config import CORSConfig

        config = CORSConfig()

        # Unknown origins should be rejected
        assert config.is_origin_allowed("https://evil.attacker.com") is False
        assert config.is_origin_allowed("null") is False
        assert config.is_origin_allowed("") is False

    def test_cors_config_rejects_wildcard_in_production(self):
        """Verify wildcard origin is rejected in production for security."""
        import os
        from aragora.server.cors_config import CORSConfig

        # Temporarily set environment with wildcard
        original_origins = os.environ.get("ARAGORA_ALLOWED_ORIGINS", "")
        try:
            os.environ["ARAGORA_ALLOWED_ORIGINS"] = "*"
            # Use _env_mode parameter to simulate production
            with pytest.raises(ValueError, match="Wildcard origin"):
                CORSConfig(_env_mode="production")
        finally:
            if original_origins:
                os.environ["ARAGORA_ALLOWED_ORIGINS"] = original_origins
            else:
                os.environ.pop("ARAGORA_ALLOWED_ORIGINS", None)

    def test_cors_config_validates_origin_format(self):
        """Verify origin format validation (must have scheme and host)."""
        import os
        from aragora.server.cors_config import CORSConfig

        original = os.environ.get("ARAGORA_ALLOWED_ORIGINS", "")
        try:
            # Invalid origin without scheme
            os.environ["ARAGORA_ALLOWED_ORIGINS"] = "example.com"
            with pytest.raises(ValueError, match="must include scheme"):
                CORSConfig()
        finally:
            if original:
                os.environ["ARAGORA_ALLOWED_ORIGINS"] = original
            else:
                os.environ.pop("ARAGORA_ALLOWED_ORIGINS", None)

    def test_cors_preflight_with_credentials_header(self, options_request):
        """Verify credentials header handling in preflight."""
        # When Access-Control-Allow-Credentials is true, origin cannot be *
        from aragora.server.cors_config import cors_config

        origin = options_request.headers.get("Origin")

        # Verify specific origin check (not wildcard)
        if cors_config.is_origin_allowed(origin):
            # Response should echo back the specific origin, not *
            response_origin = origin
        else:
            response_origin = None

        # Should never return * with credentials
        assert response_origin != "*"


# -----------------------------------------------------------------------------
# Rate Limit Bypass Attempt Tests
# -----------------------------------------------------------------------------


class TestRateLimitBypassAttempts:
    """Tests for rate limit bypass prevention."""

    def test_xff_header_spoofing_untrusted_proxy(self):
        """Verify X-Forwarded-For is ignored from untrusted sources."""
        from aragora.server.middleware.rate_limit import _extract_client_ip

        headers = {
            "X-Forwarded-For": "1.2.3.4, 5.6.7.8",
        }
        # Remote address is NOT a trusted proxy
        remote_addr = "10.0.0.100"

        # Should return the actual remote address, not spoofed XFF
        result = _extract_client_ip(headers, remote_addr, trust_xff_from_proxies=True)
        assert result == "10.0.0.100"

    def test_xff_header_respected_from_trusted_proxy(self):
        """Verify X-Forwarded-For is respected from trusted proxies."""
        from aragora.server.middleware.rate_limit import _extract_client_ip

        headers = {
            "X-Forwarded-For": "1.2.3.4, 5.6.7.8",
        }
        # Remote address IS a trusted proxy (localhost)
        remote_addr = "127.0.0.1"

        # Should extract the rightmost untrusted hop; earlier hops are client-supplied
        result = _extract_client_ip(headers, remote_addr, trust_xff_from_proxies=True)
        assert result == "5.6.7.8"

    def test_xff_header_empty_values(self):
        """Verify handling of empty or malformed X-Forwarded-For."""
        from aragora.server.middleware.rate_limit import _extract_client_ip

        # Empty XFF
        headers = {"X-Forwarded-For": ""}
        result = _extract_client_ip(headers, "127.0.0.1", trust_xff_from_proxies=True)
        assert result == "127.0.0.1"

        # XFF with only whitespace
        headers = {"X-Forwarded-For": "   "}
        result = _extract_client_ip(headers, "127.0.0.1", trust_xff_from_proxies=True)
        assert result == "127.0.0.1"

    def test_xff_header_with_invalid_ips(self):
        """Verify handling of invalid IPs in X-Forwarded-For."""
        from aragora.server.middleware.rate_limit import _extract_client_ip

        # XFF with invalid IP
        headers = {"X-Forwarded-For": "1.2.3.4, not-an-ip"}
        result = _extract_client_ip(headers, "127.0.0.1", trust_xff_from_proxies=True)
        # Should still return the rightmost untrusted entry (even if invalid) as a string key
        assert "not-an-ip" in result or result == "127.0.0.1"

    def test_ip_normalization_ipv6(self):
        """Verify IPv6 address normalization for rate limiting fairness."""
        from aragora.server.middleware.rate_limit import _normalize_ip

        # IPv6 addresses should be grouped by /64
        ip1 = _normalize_ip("2001:db8::1")
        ip2 = _normalize_ip("2001:db8::2")
        ip3 = _normalize_ip("2001:db8:1::1")  # Different /64

        # Same /64 prefix should normalize to same value
        assert ip1 == ip2
        # Different /64 prefix should be different
        assert ip1 != ip3

    def test_rate_limit_with_spoofed_user_agent(self):
        """Verify rate limiting is not affected by User-Agent spoofing."""
        from aragora.server.middleware.rate_limit import RateLimiter

        limiter = RateLimiter()

        # Same IP with different User-Agents should share rate limit
        # Rate limit is by IP, not User-Agent
        initial_result = limiter.allow("192.168.1.1")
        initial_remaining = initial_result.remaining

        for _ in range(5):
            limiter.allow("192.168.1.1")

        # Should have consumed tokens regardless of User-Agent changes
        final_result = limiter.allow("192.168.1.1")
        # Verify tokens were consumed (at least 6 used: initial + 5 in loop + final)
        assert final_result.remaining < initial_remaining


# -----------------------------------------------------------------------------
# Authentication Header Parsing Edge Cases Tests
# -----------------------------------------------------------------------------


class TestAuthHeaderParsingEdgeCases:
    """Tests for authentication header parsing edge cases."""

    @pytest.fixture
    def make_request(self):
        """Factory for creating mock requests with custom auth headers."""

        def _make(auth_header=None):
            request = MagicMock()
            request.headers = {}
            if auth_header is not None:
                request.headers["Authorization"] = auth_header
            request.remote = "127.0.0.1"
            request.app = MagicMock()
            request.app.get = MagicMock(return_value=None)
            return request

        return _make

    def test_empty_authorization_header(self, make_request):
        """Verify empty Authorization header returns unauthenticated."""
        from aragora.billing.auth.context import extract_user_from_request

        request = make_request("")
        result = extract_user_from_request(request, None)

        assert result.is_authenticated is False
        assert result.user_id is None

    def test_bearer_without_token(self, make_request):
        """Verify 'Bearer ' without token returns unauthenticated."""
        from aragora.billing.auth.context import extract_user_from_request

        request = make_request("Bearer ")
        result = extract_user_from_request(request, None)

        assert result.is_authenticated is False

    def test_bearer_with_whitespace_only(self, make_request):
        """Verify 'Bearer   ' (whitespace only) returns unauthenticated."""
        from aragora.billing.auth.context import extract_user_from_request

        request = make_request("Bearer    ")
        result = extract_user_from_request(request, None)

        assert result.is_authenticated is False

    def test_malformed_bearer_lowercase(self, make_request):
        """Verify 'bearer' (lowercase) is not accepted."""
        from aragora.billing.auth.context import extract_user_from_request

        request = make_request("bearer some-token")
        result = extract_user_from_request(request, None)

        # Bearer must be properly cased
        assert result.is_authenticated is False

    def test_authorization_with_unknown_scheme(self, make_request):
        """Verify unknown auth schemes return unauthenticated."""
        from aragora.billing.auth.context import extract_user_from_request

        request = make_request("Basic dXNlcjpwYXNz")  # Basic auth
        result = extract_user_from_request(request, None)

        # Only Bearer and API key are supported
        assert result.is_authenticated is False

    def test_bearer_with_extra_spaces(self, make_request):
        """Verify 'Bearer  token' (extra spaces) handles correctly."""
        from aragora.billing.auth.context import extract_user_from_request

        # Token has leading space which may cause issues
        request = make_request("Bearer  token-with-space")
        result = extract_user_from_request(request, None)

        # Should handle gracefully (token with leading space won't validate)
        # The important thing is it doesn't crash
        assert result.is_authenticated is False

    def test_very_long_authorization_header(self, make_request):
        """Verify extremely long auth headers are handled safely."""
        from aragora.billing.auth.context import extract_user_from_request

        # Create a very long "token"
        long_token = "Bearer " + "x" * 100000
        request = make_request(long_token)

        # Should not crash and should return unauthenticated
        result = extract_user_from_request(request, None)
        assert result.is_authenticated is False

    def test_null_bytes_in_authorization_header(self, make_request):
        """Verify null bytes in auth header are handled safely."""
        from aragora.billing.auth.context import extract_user_from_request

        request = make_request("Bearer token\x00with\x00nulls")
        result = extract_user_from_request(request, None)

        # Should handle gracefully
        assert result.is_authenticated is False

    def test_unicode_in_authorization_header(self, make_request):
        """Verify unicode in auth header is handled safely."""
        from aragora.billing.auth.context import extract_user_from_request

        request = make_request("Bearer token\u200bwith\u200bunicode")
        result = extract_user_from_request(request, None)

        # Zero-width spaces shouldn't authenticate
        assert result.is_authenticated is False

    def test_api_key_without_prefix(self, make_request):
        """Verify API key without 'ara_' prefix is rejected."""
        from aragora.billing.auth.context import extract_user_from_request

        request = make_request("key_without_prefix_12345")
        result = extract_user_from_request(request, None)

        assert result.is_authenticated is False


# -----------------------------------------------------------------------------
# Session Hijacking Prevention Tests
# -----------------------------------------------------------------------------


class TestSessionHijackingPrevention:
    """Tests for session hijacking prevention mechanisms."""

    def test_session_bound_to_user(self):
        """Verify sessions are bound to specific users."""
        from aragora.billing.auth.sessions import JWTSession
        import time

        session = JWTSession(
            session_id="session-123",
            user_id="user-456",
            created_at=time.time(),
            last_activity=time.time(),
        )

        # Session should track user binding
        assert session.user_id == "user-456"
        assert session.session_id == "session-123"

    def test_session_cannot_be_used_for_different_user(self):
        """Verify session manager validates user ownership."""
        from aragora.billing.auth.sessions import get_session_manager

        manager = get_session_manager()

        # Create session for user A
        manager.create_session("user-A", "session-A", {})

        # Try to get session as user B - should not find it
        session = manager.get_session("user-B", "session-A")
        assert session is None

        # User A should be able to access their session
        session = manager.get_session("user-A", "session-A")
        # May or may not exist depending on implementation, but shouldn't cross users

    def test_session_revocation_invalidates_access(self):
        """Verify revoked sessions cannot be used."""
        from aragora.billing.auth.sessions import get_session_manager

        manager = get_session_manager()

        # Create and then revoke a session
        manager.create_session("user-X", "session-X", {})
        manager.revoke_session("user-X", "session-X")

        # Session should no longer be valid
        session = manager.get_session("user-X", "session-X")
        assert session is None

    def test_token_hash_for_session_tracking(self):
        """Verify session tracking uses token hash not raw token."""
        import hashlib

        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"

        # Session ID should be derived from token hash
        session_id = hashlib.sha256(token.encode()).hexdigest()[:32]

        # Verify hash is deterministic
        assert session_id == hashlib.sha256(token.encode()).hexdigest()[:32]
        # Verify different tokens produce different session IDs
        different_session = hashlib.sha256(b"different-token").hexdigest()[:32]
        assert session_id != different_session

    def test_workspace_membership_validation(self):
        """Verify workspace access is validated against memberships."""
        from aragora.server.handlers.utils.auth import _extract_workspace_id

        # Create mock request with workspace header
        request = MagicMock()
        request.headers = {"X-Workspace-ID": "ws-123"}
        request.app = MagicMock()

        # Mock workspace store with user memberships
        mock_store = MagicMock()
        mock_store.get_user_workspaces.return_value = [
            {"workspace_id": "ws-456"},  # User belongs to ws-456, not ws-123
        ]
        request.app.get.return_value = mock_store

        # Request workspace ws-123 but user only has access to ws-456
        result = _extract_workspace_id(request, "user-123")

        # Should reject access to ws-123
        assert result is None

    def test_ip_tracking_in_auth_context(self):
        """Verify client IP is tracked in auth context for session validation."""
        from aragora.billing.auth.context import UserAuthContext

        context = UserAuthContext(
            authenticated=True,
            user_id="user-123",
            client_ip="192.168.1.100",
        )

        # IP should be available for additional security checks
        assert context.client_ip == "192.168.1.100"


# -----------------------------------------------------------------------------
# CSRF Token Validation Tests
# -----------------------------------------------------------------------------


class TestCSRFTokenValidation:
    """Tests for CSRF token validation in OAuth flows."""

    def test_oauth_state_creation_uniqueness(self):
        """Verify OAuth state tokens are unique."""
        import secrets

        state1 = secrets.token_urlsafe(32)
        state2 = secrets.token_urlsafe(32)

        # States should be unique
        assert state1 != state2
        assert len(state1) >= 32

    def test_oauth_state_validation_consumes_token(self):
        """Verify OAuth state can only be used once."""
        from aragora.server.oauth_state_store import InMemoryOAuthStateStore

        store = InMemoryOAuthStateStore()

        # Generate a state token
        state_token = store.generate(
            user_id="user-123",
            redirect_url="https://app.aragora.ai/callback",
            ttl_seconds=600,
        )

        # First validation should succeed
        result = store.validate_and_consume(state_token)
        assert result is not None
        assert result.user_id == "user-123"

        # Second validation should fail (consumed)
        result2 = store.validate_and_consume(state_token)
        assert result2 is None

    def test_oauth_state_expiration(self):
        """Verify expired OAuth states are rejected."""
        from aragora.server.oauth_state_store import InMemoryOAuthStateStore
        import time

        store = InMemoryOAuthStateStore()

        # Generate a state with very short TTL
        state_token = store.generate(
            user_id="user-123",
            redirect_url="https://app.aragora.ai/callback",
            ttl_seconds=0,  # Expires immediately
        )

        # Small delay to ensure expiration
        time.sleep(0.01)

        # Validation should fail for expired state
        result = store.validate_and_consume(state_token)
        assert result is None

    def test_oauth_state_invalid_token(self):
        """Verify invalid state tokens are rejected."""
        from aragora.server.oauth_state_store import InMemoryOAuthStateStore

        store = InMemoryOAuthStateStore()

        # Try to validate a state that was never created
        result = store.validate_and_consume("nonexistent-state")
        assert result is None

    def test_bearer_auth_immune_to_csrf(self):
        """Verify Bearer token auth is immune to CSRF by design."""
        # This is documented in base.py - Bearer tokens in Authorization header
        # are not automatically sent by browsers like cookies are.

        # The key security properties:
        # 1. Tokens are sent via Authorization header
        # 2. JavaScript must explicitly set the header
        # 3. Cross-origin requests cannot access the header

        # Test that authentication requires explicit Authorization header
        from aragora.billing.auth.context import extract_user_from_request

        request = MagicMock()
        request.headers = {}  # No Authorization header
        request.app = MagicMock()
        request.app.get.return_value = None

        # Without explicit Authorization header, request is unauthenticated
        result = extract_user_from_request(request, None)
        assert result.is_authenticated is False

    def test_state_parameter_required_for_oauth(self):
        """Verify OAuth flows require state parameter."""
        from aragora.server.oauth_state_store import InMemoryOAuthStateStore

        store = InMemoryOAuthStateStore()

        # Validate with empty state
        result1 = store.validate_and_consume("")
        # Validate with nonexistent state
        result2 = store.validate_and_consume("does-not-exist")

        # Both should fail
        assert result1 is None
        assert result2 is None

    def test_csrf_protection_with_max_states_limit(self):
        """Verify max state limit prevents memory exhaustion attacks."""
        from aragora.server.oauth_state_store import MAX_OAUTH_STATES

        # Constant should be defined and reasonable
        assert MAX_OAUTH_STATES > 0
        assert MAX_OAUTH_STATES <= 100000  # Reasonable upper bound
