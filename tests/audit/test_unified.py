"""
Tests for unified audit logging facade.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from aragora.audit.unified import (
    UnifiedAuditCategory,
    AuditOutcome,
    AuditSeverity,
    UnifiedAuditEvent,
    UnifiedAuditLogger,
    get_unified_audit_logger,
    configure_unified_audit_logger,
    audit_log,
    audit_login,
    audit_logout,
    audit_access,
    audit_data,
    audit_admin,
    audit_security,
    audit_debate,
)


class TestUnifiedAuditEvent:
    """Tests for UnifiedAuditEvent dataclass."""

    def test_default_values(self):
        """Test default event values."""
        event = UnifiedAuditEvent(
            category=UnifiedAuditCategory.AUTH_LOGIN,
            action="User login",
        )

        assert event.category == UnifiedAuditCategory.AUTH_LOGIN
        assert event.action == "User login"
        assert event.outcome == AuditOutcome.SUCCESS
        assert event.severity == AuditSeverity.INFO
        assert event.actor_type == "user"
        assert event.details == {}

    def test_full_event(self):
        """Test event with all fields."""
        event = UnifiedAuditEvent(
            category=UnifiedAuditCategory.DATA_UPDATED,
            action="Update user profile",
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.INFO,
            actor_id="user_123",
            actor_type="user",
            resource_type="user_profile",
            resource_id="profile_456",
            org_id="org_789",
            workspace_id="ws_abc",
            request_id="req_def",
            session_id="sess_ghi",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            details={"field": "email", "old_value": "old@test.com"},
            reason="User requested change",
        )

        assert event.actor_id == "user_123"
        assert event.resource_type == "user_profile"
        assert event.org_id == "org_789"

    def test_to_dict(self):
        """Test event serialization."""
        event = UnifiedAuditEvent(
            category=UnifiedAuditCategory.AUTH_LOGIN,
            action="User login",
            actor_id="user_123",
        )

        data = event.to_dict()

        assert data["category"] == "auth.login"
        assert data["action"] == "User login"
        assert data["actor_id"] == "user_123"
        assert "timestamp" in data


class TestUnifiedAuditLogger:
    """Tests for UnifiedAuditLogger class."""

    def test_init_defaults(self):
        """Test default initialization."""
        logger = UnifiedAuditLogger()

        assert logger._enable_compliance is True
        assert logger._enable_privacy is True
        assert logger._enable_rbac is True
        assert logger._enable_immutable is False
        assert logger._enable_middleware is True

    def test_init_custom(self):
        """Test custom initialization."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_immutable=True,
        )

        assert logger._enable_compliance is False
        assert logger._enable_immutable is True

    def test_add_remove_handler(self):
        """Test custom handler registration."""
        logger = UnifiedAuditLogger()
        handler = MagicMock()

        logger.add_handler(handler)
        assert handler in logger._handlers

        logger.remove_handler(handler)
        assert handler not in logger._handlers

    def test_handler_called_on_log(self):
        """Test that handlers are called when logging."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )
        handler = MagicMock()
        logger.add_handler(handler)

        event = UnifiedAuditEvent(
            category=UnifiedAuditCategory.AUTH_LOGIN,
            action="Test login",
        )
        logger.log(event)

        handler.assert_called_once_with(event)

    def test_handler_error_doesnt_break_logging(self):
        """Test that handler errors don't break other handlers."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )
        bad_handler = MagicMock(side_effect=RuntimeError("Handler error"))
        good_handler = MagicMock()

        logger.add_handler(bad_handler)
        logger.add_handler(good_handler)

        event = UnifiedAuditEvent(
            category=UnifiedAuditCategory.AUTH_LOGIN,
            action="Test login",
        )
        logger.log(event)  # Should not raise

        good_handler.assert_called_once()


class TestConvenienceMethods:
    """Tests for convenience logging methods."""

    def test_log_auth_login_success(self):
        """Test logging successful login."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )
        handler = MagicMock()
        logger.add_handler(handler)

        logger.log_auth_login("user_123", success=True, ip_address="192.168.1.1")

        handler.assert_called_once()
        event = handler.call_args[0][0]
        assert event.category == UnifiedAuditCategory.AUTH_LOGIN
        assert event.outcome == AuditOutcome.SUCCESS
        assert event.actor_id == "user_123"
        assert event.ip_address == "192.168.1.1"

    def test_log_auth_login_failure(self):
        """Test logging failed login."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )
        handler = MagicMock()
        logger.add_handler(handler)

        logger.log_auth_login("user_123", success=False)

        event = handler.call_args[0][0]
        assert event.category == UnifiedAuditCategory.AUTH_FAILED
        assert event.outcome == AuditOutcome.FAILURE

    def test_log_access_granted(self):
        """Test logging access granted."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )
        handler = MagicMock()
        logger.add_handler(handler)

        logger.log_access_check(
            "user_123",
            permission="webhooks.create",
            resource_type="webhook",
            resource_id="wh_456",
            granted=True,
        )

        event = handler.call_args[0][0]
        assert event.category == UnifiedAuditCategory.ACCESS_GRANTED
        assert event.outcome == AuditOutcome.SUCCESS
        assert event.details["permission"] == "webhooks.create"

    def test_log_access_denied(self):
        """Test logging access denied."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )
        handler = MagicMock()
        logger.add_handler(handler)

        logger.log_access_check(
            "user_123",
            permission="admin:delete",
            granted=False,
            reason="Insufficient privileges",
        )

        event = handler.call_args[0][0]
        assert event.category == UnifiedAuditCategory.ACCESS_DENIED
        assert event.outcome == AuditOutcome.DENIED
        assert event.reason == "Insufficient privileges"

    def test_log_data_access(self):
        """Test logging data access."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )
        handler = MagicMock()
        logger.add_handler(handler)

        logger.log_data_access(
            "user_123",
            resource_type="document",
            resource_id="doc_456",
            action="read",
        )

        event = handler.call_args[0][0]
        assert event.category == UnifiedAuditCategory.DATA_READ
        assert event.resource_type == "document"
        assert event.resource_id == "doc_456"

    def test_log_admin_action(self):
        """Test logging admin action."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )
        handler = MagicMock()
        logger.add_handler(handler)

        logger.log_admin_action(
            "admin_123",
            action="delete_user",
            target_type="user",
            target_id="user_456",
        )

        event = handler.call_args[0][0]
        assert event.category == UnifiedAuditCategory.ADMIN_CONFIG_CHANGED
        assert event.severity == AuditSeverity.WARNING
        assert event.actor_id == "admin_123"

    def test_log_security_event(self):
        """Test logging security event."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )
        handler = MagicMock()
        logger.add_handler(handler)

        logger.log_security_event(
            "threat",
            severity=AuditSeverity.CRITICAL,
            actor_id="unknown",
        )

        event = handler.call_args[0][0]
        assert event.category == UnifiedAuditCategory.SECURITY_THREAT_DETECTED
        assert event.severity == AuditSeverity.CRITICAL

    def test_log_debate_event(self):
        """Test logging debate event."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )
        handler = MagicMock()
        logger.add_handler(handler)

        logger.log_debate_event(
            debate_id="debate_123",
            action="started",
            user_id="user_456",
        )

        event = handler.call_args[0][0]
        assert event.category == UnifiedAuditCategory.DEBATE_STARTED
        assert event.resource_type == "debate"
        assert event.resource_id == "debate_123"


class TestGlobalFunctions:
    """Tests for global convenience functions."""

    def test_get_unified_audit_logger_singleton(self):
        """Test that get_unified_audit_logger returns singleton."""
        import aragora.observability.unified_audit as unified_module

        # Reset singleton
        unified_module._unified_logger = None

        logger1 = get_unified_audit_logger()
        logger2 = get_unified_audit_logger()

        assert logger1 is logger2

        # Cleanup
        unified_module._unified_logger = None

    def test_configure_replaces_singleton(self):
        """Test that configure creates new singleton."""
        import aragora.observability.unified_audit as unified_module

        # Reset singleton
        unified_module._unified_logger = None

        logger1 = get_unified_audit_logger()
        logger2 = configure_unified_audit_logger(enable_immutable=True)
        logger3 = get_unified_audit_logger()

        assert logger1 is not logger2
        assert logger2 is logger3
        assert logger2._enable_immutable is True

        # Cleanup
        unified_module._unified_logger = None

    def test_audit_log_function(self):
        """Test audit_log convenience function."""
        import aragora.observability.unified_audit as unified_module

        # Reset singleton
        unified_module._unified_logger = None

        logger = configure_unified_audit_logger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )
        handler = MagicMock()
        logger.add_handler(handler)

        event = UnifiedAuditEvent(
            category=UnifiedAuditCategory.AUTH_LOGIN,
            action="Test",
        )
        audit_log(event)

        handler.assert_called_once_with(event)

        # Cleanup
        unified_module._unified_logger = None

    def test_audit_login_function(self):
        """Test audit_login convenience function."""
        import aragora.observability.unified_audit as unified_module

        unified_module._unified_logger = None

        logger = configure_unified_audit_logger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )
        handler = MagicMock()
        logger.add_handler(handler)

        audit_login("user_123", success=True)

        handler.assert_called_once()
        event = handler.call_args[0][0]
        assert event.category == UnifiedAuditCategory.AUTH_LOGIN

        unified_module._unified_logger = None


class TestBackendDispatch:
    """Tests for backend dispatch logic."""

    def test_compliance_dispatch(self):
        """Test dispatch to compliance logger."""
        logger = UnifiedAuditLogger(
            enable_compliance=True,
            enable_privacy=False,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )

        mock_compliance = MagicMock()
        with patch.object(logger, "_get_compliance_logger", return_value=mock_compliance):
            event = UnifiedAuditEvent(
                category=UnifiedAuditCategory.AUTH_LOGIN,
                action="User login",
                actor_id="user_123",
            )
            logger.log(event)

            mock_compliance.log.assert_called_once()

    def test_privacy_dispatch_for_data_events(self):
        """Test dispatch to privacy logger for data events."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=True,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )

        mock_privacy = MagicMock()
        with patch.object(logger, "_get_privacy_logger", return_value=mock_privacy):
            event = UnifiedAuditEvent(
                category=UnifiedAuditCategory.DATA_READ,
                action="Read document",
                actor_id="user_123",
                resource_id="doc_456",
            )
            logger.log(event)

            mock_privacy.log.assert_called_once()

    def test_privacy_not_dispatched_for_auth_events(self):
        """Test privacy logger not called for auth events."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=True,
            enable_rbac=False,
            enable_immutable=False,
            enable_middleware=False,
        )

        mock_privacy = MagicMock()
        with patch.object(logger, "_get_privacy_logger", return_value=mock_privacy):
            event = UnifiedAuditEvent(
                category=UnifiedAuditCategory.AUTH_LOGIN,
                action="User login",
                actor_id="user_123",
            )
            logger.log(event)

            mock_privacy.log.assert_not_called()

    def test_rbac_dispatch_for_access_events(self):
        """Test dispatch to RBAC auditor for access events."""
        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=True,
            enable_immutable=False,
            enable_middleware=False,
        )

        mock_rbac = MagicMock()
        with patch.object(logger, "_get_rbac_auditor", return_value=mock_rbac):
            event = UnifiedAuditEvent(
                category=UnifiedAuditCategory.ACCESS_GRANTED,
                action="Permission granted",
                actor_id="user_123",
                details={"permission": "webhooks.create"},
            )
            logger.log(event)

            mock_rbac.log_permission_granted.assert_called_once()

    def test_rbac_dispatch_real_auditor_handles_access_decisions(self):
        """Test real RBAC auditor dispatch for granted and denied access checks."""
        from aragora.rbac.audit import AuditEventType, AuthorizationAuditor

        logger = UnifiedAuditLogger(
            enable_compliance=False,
            enable_privacy=False,
            enable_rbac=True,
            enable_immutable=False,
            enable_middleware=False,
        )
        events = []
        auditor = AuthorizationAuditor(handlers=[events.append])

        with patch.object(logger, "_get_rbac_auditor", return_value=auditor):
            logger.log_access_check(
                "user_123",
                permission="webhooks.create",
                resource_type="webhook",
                resource_id="wh_456",
                granted=True,
                org_id="org_123",
            )
            logger.log_access_check(
                "user_123",
                permission="admin.delete",
                resource_type="admin",
                resource_id="admin_456",
                granted=False,
                reason="Insufficient privileges",
                org_id="org_123",
            )

        assert [event.event_type for event in events] == [
            AuditEventType.PERMISSION_GRANTED,
            AuditEventType.PERMISSION_DENIED,
        ]
        assert events[0].decision is True
        assert events[0].permission_key == "webhooks.create"
        assert events[0].resource_id == "wh_456"
        assert events[0].org_id == "org_123"
        assert events[1].decision is False
        assert events[1].permission_key == "admin.delete"
        assert events[1].resource_id == "admin_456"
        assert events[1].reason == "Insufficient privileges"


class TestAuditCategories:
    """Tests for audit category enums."""

    def test_all_categories_have_values(self):
        """Test all categories have string values."""
        for category in UnifiedAuditCategory:
            assert isinstance(category.value, str)
            assert "." in category.value  # All should have dot notation

    def test_category_prefixes(self):
        """Test category prefix groupings."""
        auth_categories = [c for c in UnifiedAuditCategory if c.value.startswith("auth.")]
        assert len(auth_categories) >= 5  # login, logout, failed, mfa, token_*

        access_categories = [c for c in UnifiedAuditCategory if c.value.startswith("access.")]
        assert len(access_categories) >= 4  # granted, denied, role_*, permission_*

        data_categories = [c for c in UnifiedAuditCategory if c.value.startswith("data.")]
        assert len(data_categories) >= 4  # read, created, updated, deleted

    def test_outcomes(self):
        """Test all outcomes exist."""
        assert AuditOutcome.SUCCESS.value == "success"
        assert AuditOutcome.FAILURE.value == "failure"
        assert AuditOutcome.DENIED.value == "denied"
        assert AuditOutcome.ERROR.value == "error"

    def test_severities(self):
        """Test all severities exist."""
        assert AuditSeverity.DEBUG.value == "debug"
        assert AuditSeverity.INFO.value == "info"
        assert AuditSeverity.WARNING.value == "warning"
        assert AuditSeverity.ERROR.value == "error"
        assert AuditSeverity.CRITICAL.value == "critical"
