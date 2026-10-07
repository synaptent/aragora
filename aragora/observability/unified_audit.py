"""
Unified Audit Logging Facade.

Provides a single entry point for audit logging that dispatches to all
relevant audit systems while maintaining backward compatibility.

This consolidation layer:
- Provides a unified API for all audit logging needs
- Dispatches to appropriate backends (compliance, privacy, RBAC, immutable)
- Maintains consistent event format across systems
- Simplifies integration for new features
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)


class UnifiedAuditCategory(str, Enum):
    """Unified audit categories across all systems."""

    # Authentication and Authorization
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_FAILED = "auth.failed"
    AUTH_MFA = "auth.mfa"
    AUTH_TOKEN_ISSUED = "auth.token_issued"  # noqa: S105 -- enum value
    AUTH_TOKEN_REVOKED = "auth.token_revoked"  # noqa: S105 -- enum value

    # Access Control (RBAC)
    ACCESS_GRANTED = "access.granted"
    ACCESS_DENIED = "access.denied"
    ROLE_ASSIGNED = "access.role_assigned"
    ROLE_REVOKED = "access.role_revoked"
    PERMISSION_CHANGED = "access.permission_changed"

    # Data Operations
    DATA_READ = "data.read"
    DATA_CREATED = "data.created"
    DATA_UPDATED = "data.updated"
    DATA_DELETED = "data.deleted"
    DATA_EXPORTED = "data.exported"

    # Admin Actions
    ADMIN_CONFIG_CHANGED = "admin.config_changed"
    ADMIN_USER_CREATED = "admin.user_created"
    ADMIN_USER_DELETED = "admin.user_deleted"
    ADMIN_USER_MODIFIED = "admin.user_modified"

    # Security Events
    SECURITY_THREAT_DETECTED = "security.threat"
    SECURITY_ENCRYPTION = "security.encryption"
    SECURITY_KEY_ROTATION = "security.key_rotation"
    SECURITY_ANOMALY = "security.anomaly"

    # API Operations
    API_REQUEST = "api.request"
    API_RATE_LIMITED = "api.rate_limited"
    API_KEY_CREATED = "api.key_created"
    API_KEY_REVOKED = "api.key_revoked"

    # Debate and Workflow
    DEBATE_STARTED = "debate.started"
    DEBATE_COMPLETED = "debate.completed"
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    APPROVAL_REQUESTED = "workflow.approval_requested"
    APPROVAL_GRANTED = "workflow.approval_granted"
    APPROVAL_DENIED = "workflow.approval_denied"

    # System Events
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"

    # Privacy Events
    PRIVACY_CONSENT_GIVEN = "privacy.consent_given"
    PRIVACY_CONSENT_WITHDRAWN = "privacy.consent_withdrawn"
    PRIVACY_DATA_REQUEST = "privacy.data_request"


class AuditOutcome(str, Enum):
    """Outcome of an audited action."""

    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    ERROR = "error"
    PARTIAL = "partial"


class AuditSeverity(str, Enum):
    """Severity level for audit events."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class UnifiedAuditEvent:
    """
    Unified audit event that can be dispatched to any audit backend.

    This event structure is designed to be translatable to all existing
    audit systems while providing a consistent interface.
    """

    # Core fields
    category: UnifiedAuditCategory
    action: str  # Human-readable action description
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    severity: AuditSeverity = AuditSeverity.INFO

    # Actor information
    actor_id: str | None = None
    actor_type: str = "user"  # user, service, system, api_key

    # Resource information
    resource_type: str | None = None
    resource_id: str | None = None

    # Organizational context
    org_id: str | None = None
    workspace_id: str | None = None

    # Request context
    request_id: str | None = None
    session_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None

    # Event details
    details: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    # Timestamp
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "category": self.category.value,
            "action": self.action,
            "outcome": self.outcome.value,
            "severity": self.severity.value,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "org_id": self.org_id,
            "workspace_id": self.workspace_id,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "details": self.details,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
        }


class UnifiedAuditLogger:
    """
    Unified audit logger that dispatches to all configured backends.

    This provides a single point of entry for audit logging across the
    entire application, while maintaining compatibility with existing
    specialized audit systems.
    """

    def __init__(
        self,
        enable_compliance: bool = True,
        enable_privacy: bool = True,
        enable_rbac: bool = True,
        enable_immutable: bool = False,
        enable_middleware: bool = True,
    ):
        """
        Initialize the unified audit logger.

        Args:
            enable_compliance: Enable SOC2/HIPAA/GDPR compliance logging
            enable_privacy: Enable privacy-specific audit logging
            enable_rbac: Enable RBAC/authorization audit logging
            enable_immutable: Enable immutable audit log (append-only)
            enable_middleware: Enable HTTP middleware audit logging
        """
        self._enable_compliance = enable_compliance
        self._enable_privacy = enable_privacy
        self._enable_rbac = enable_rbac
        self._enable_immutable = enable_immutable
        self._enable_middleware = enable_middleware

        # Lazy-loaded backend instances
        self._compliance_logger = None
        self._privacy_logger = None
        self._rbac_auditor = None
        self._immutable_logger = None
        self._middleware_logger = None

        # Event handlers for custom integrations
        self._handlers: list[Callable[[UnifiedAuditEvent], None]] = []

    def add_handler(self, handler: Callable[[UnifiedAuditEvent], None]) -> None:
        """Add a custom event handler."""
        self._handlers.append(handler)

    def remove_handler(self, handler: Callable[[UnifiedAuditEvent], None]) -> None:
        """Remove a custom event handler."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    def _get_compliance_logger(self):
        """Lazy-load compliance audit logger."""
        if self._compliance_logger is None and self._enable_compliance:
            try:
                from aragora.observability.audit_log import get_audit_log

                self._compliance_logger = get_audit_log()
            except ImportError:
                logger.debug("Compliance audit logger not available")
        return self._compliance_logger

    def _get_privacy_logger(self):
        """Lazy-load privacy audit logger."""
        if self._privacy_logger is None and self._enable_privacy:
            try:
                from aragora.privacy.audit_log import get_privacy_audit_log

                self._privacy_logger = get_privacy_audit_log()
            except ImportError:
                logger.debug("Privacy audit logger not available")
        return self._privacy_logger

    def _get_rbac_auditor(self):
        """Lazy-load RBAC auditor."""
        if self._rbac_auditor is None and self._enable_rbac:
            try:
                from aragora.rbac.audit import get_auditor

                self._rbac_auditor = get_auditor()
            except ImportError:
                logger.debug("RBAC auditor not available")
        return self._rbac_auditor

    def _get_immutable_logger(self):
        """Lazy-load immutable audit logger."""
        if self._immutable_logger is None and self._enable_immutable:
            try:
                from aragora.observability.immutable_log import get_audit_log

                self._immutable_logger = get_audit_log()
            except ImportError:
                logger.debug("Immutable audit logger not available")
        return self._immutable_logger

    def _get_middleware_logger(self):
        """Lazy-load the middleware audit logger registered by the server."""
        if self._middleware_logger is None and self._enable_middleware:
            factory = _middleware_logger_factory
            if factory is None:
                logger.debug("Middleware audit logger not registered")
            else:
                self._middleware_logger = factory()
        return self._middleware_logger

    def log(self, event: UnifiedAuditEvent) -> None:
        """
        Log an audit event to all enabled backends.

        Args:
            event: The unified audit event to log
        """
        # Dispatch to compliance logger
        self._dispatch_to_compliance(event)

        # Dispatch to privacy logger for privacy-related events
        self._dispatch_to_privacy(event)

        # Dispatch to RBAC auditor for access events
        self._dispatch_to_rbac(event)

        # Dispatch to immutable logger if enabled
        self._dispatch_to_immutable(event)

        # Dispatch to middleware logger
        self._dispatch_to_middleware(event)

        # Call custom handlers
        for handler in self._handlers:
            try:
                handler(event)
            except (ValueError, RuntimeError, OSError) as e:
                logger.warning("Audit handler error: %s", e)

    def _dispatch_to_compliance(self, event: UnifiedAuditEvent) -> None:
        """Dispatch event to compliance audit logger."""
        log = self._get_compliance_logger()
        if log is None:
            return

        try:
            # Map to compliance categories
            category_map = {
                "auth.": "AUTH",
                "access.": "ACCESS",
                "data.": "DATA",
                "admin.": "ADMIN",
                "security.": "SECURITY",
                "api.": "API",
                "debate.": "DEBATE",
                "workflow.": "DEBATE",
                "system.": "SYSTEM",
            }

            category = "SYSTEM"
            for prefix, cat in category_map.items():
                if event.category.value.startswith(prefix):
                    category = cat
                    break

            from aragora.observability.audit_log import AuditCategory as ComplianceCategory
            from aragora.observability.audit_log import AuditEvent as ComplianceEvent
            from aragora.observability.audit_log import AuditOutcome as ComplianceOutcome

            # Map string category to AuditCategory enum
            cat_map = {
                "AUTH": ComplianceCategory.AUTH,
                "ACCESS": ComplianceCategory.ACCESS,
                "DATA": ComplianceCategory.DATA,
                "ADMIN": ComplianceCategory.ADMIN,
                "SECURITY": ComplianceCategory.SECURITY,
                "API": ComplianceCategory.API,
                "DEBATE": ComplianceCategory.DEBATE,
                "SYSTEM": ComplianceCategory.SYSTEM,
            }
            # Map outcome
            outcome_map = {
                "SUCCESS": ComplianceOutcome.SUCCESS,
                "FAILURE": ComplianceOutcome.FAILURE,
                "DENIED": ComplianceOutcome.DENIED,
            }

            compliance_event = ComplianceEvent(
                category=cat_map.get(category, ComplianceCategory.SYSTEM),
                action=event.action,
                actor_id=event.actor_id or "",
                resource_type=event.resource_type or "",
                resource_id=event.resource_id or "",
                outcome=outcome_map.get(event.outcome.value.upper(), ComplianceOutcome.SUCCESS),
                org_id=event.org_id or "",
                ip_address=event.ip_address or "",
                details=event.details or {},
            )
            log.log(compliance_event)
        except (ValueError, RuntimeError, OSError, TypeError, AttributeError) as e:
            logger.warning("Compliance audit dispatch error: %s", e)

    def _dispatch_to_privacy(self, event: UnifiedAuditEvent) -> None:
        """Dispatch event to privacy audit logger."""
        log = self._get_privacy_logger()
        if log is None:
            return

        # Only dispatch privacy-relevant events
        privacy_categories = {"data.", "privacy.", "admin.user"}
        if not any(event.category.value.startswith(p) for p in privacy_categories):
            return

        try:
            # Map to privacy action
            action_map = {
                "data.read": "read",
                "data.created": "write",
                "data.updated": "write",
                "data.deleted": "delete",
                "data.exported": "export",
            }
            action = action_map.get(event.category.value, "read")

            log.log(
                actor=event.actor_id or "system",
                resource=event.resource_id or "unknown",
                action=action,
                workspace_id=event.workspace_id,
                success=event.outcome == AuditOutcome.SUCCESS,
                metadata=event.details,
            )
        except (ValueError, RuntimeError, OSError) as e:
            logger.warning("Privacy audit dispatch error: %s", e)

    def _dispatch_to_rbac(self, event: UnifiedAuditEvent) -> None:
        """Dispatch event to RBAC auditor."""
        auditor = self._get_rbac_auditor()
        if auditor is None:
            return

        # Only dispatch access-related events
        if not event.category.value.startswith("access."):
            return

        try:
            if event.category == UnifiedAuditCategory.ACCESS_GRANTED:
                auditor.log_permission_granted(
                    user_id=event.actor_id,
                    permission=event.details.get("permission", "unknown"),
                    resource=event.resource_id,
                    context=event.details,
                )
            elif event.category == UnifiedAuditCategory.ACCESS_DENIED:
                auditor.log_permission_denied(
                    user_id=event.actor_id,
                    permission=event.details.get("permission", "unknown"),
                    resource=event.resource_id,
                    reason=event.reason,
                    context=event.details,
                )
        except (ValueError, RuntimeError, OSError) as e:
            logger.warning("RBAC audit dispatch error: %s", e)

    def _dispatch_to_immutable(self, event: UnifiedAuditEvent) -> None:
        """Dispatch event to immutable audit logger."""
        log = self._get_immutable_logger()
        if log is None:
            return

        try:
            log.log(
                event_type=event.category.value,
                actor=event.actor_id or "system",
                action=event.action,
                resource=event.resource_id,
                details=event.to_dict(),
            )
        except (ValueError, RuntimeError, OSError, TypeError, AttributeError) as e:
            logger.warning("Immutable audit dispatch error: %s", e)

    def _dispatch_to_middleware(self, event: UnifiedAuditEvent) -> None:
        """Dispatch event to middleware audit logger."""
        log = self._get_middleware_logger()
        if log is None:
            return

        try:
            # Map severity
            severity_map = {
                AuditSeverity.DEBUG: "DEBUG",
                AuditSeverity.INFO: "INFO",
                AuditSeverity.WARNING: "WARNING",
                AuditSeverity.ERROR: "ERROR",
                AuditSeverity.CRITICAL: "CRITICAL",
            }

            log.log(
                event_type=event.category.value,
                action=event.action,
                actor=event.actor_id,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                outcome=event.outcome.value,
                severity=severity_map.get(event.severity, "INFO"),
                details=event.details,
                request_id=event.request_id,
                ip_address=event.ip_address,
            )
        except (ValueError, RuntimeError, OSError, TypeError, AttributeError) as e:
            logger.warning("Middleware audit dispatch error: %s", e)

    # Convenience methods for common audit events

    def log_auth_login(
        self,
        user_id: str,
        success: bool = True,
        ip_address: str | None = None,
        method: str = "password",
        **kwargs,
    ) -> None:
        """Log a login attempt."""
        self.log(
            UnifiedAuditEvent(
                category=(
                    UnifiedAuditCategory.AUTH_LOGIN if success else UnifiedAuditCategory.AUTH_FAILED
                ),
                action=f"User login via {method}",
                outcome=AuditOutcome.SUCCESS if success else AuditOutcome.FAILURE,
                actor_id=user_id,
                ip_address=ip_address,
                details={"method": method, **kwargs},
            )
        )

    def log_auth_logout(self, user_id: str, **kwargs) -> None:
        """Log a logout."""
        self.log(
            UnifiedAuditEvent(
                category=UnifiedAuditCategory.AUTH_LOGOUT,
                action="User logout",
                actor_id=user_id,
                details=kwargs,
            )
        )

    def log_access_check(
        self,
        user_id: str,
        permission: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        granted: bool = True,
        reason: str | None = None,
        **kwargs,
    ) -> None:
        """Log an access control check."""
        self.log(
            UnifiedAuditEvent(
                category=(
                    UnifiedAuditCategory.ACCESS_GRANTED
                    if granted
                    else UnifiedAuditCategory.ACCESS_DENIED
                ),
                action=f"Permission check: {permission}",
                outcome=AuditOutcome.SUCCESS if granted else AuditOutcome.DENIED,
                actor_id=user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                reason=reason,
                details={"permission": permission, **kwargs},
            )
        )

    def log_data_access(
        self,
        user_id: str,
        resource_type: str,
        resource_id: str,
        action: str = "read",
        **kwargs,
    ) -> None:
        """Log a data access event."""
        category_map = {
            "read": UnifiedAuditCategory.DATA_READ,
            "create": UnifiedAuditCategory.DATA_CREATED,
            "update": UnifiedAuditCategory.DATA_UPDATED,
            "delete": UnifiedAuditCategory.DATA_DELETED,
            "export": UnifiedAuditCategory.DATA_EXPORTED,
        }
        self.log(
            UnifiedAuditEvent(
                category=category_map.get(action, UnifiedAuditCategory.DATA_READ),
                action=f"Data {action}: {resource_type}",
                actor_id=user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                details=kwargs,
            )
        )

    def log_admin_action(
        self,
        admin_id: str,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        **kwargs,
    ) -> None:
        """Log an administrative action."""
        self.log(
            UnifiedAuditEvent(
                category=UnifiedAuditCategory.ADMIN_CONFIG_CHANGED,
                action=f"Admin action: {action}",
                severity=AuditSeverity.WARNING,
                actor_id=admin_id,
                resource_type=target_type,
                resource_id=target_id,
                details={"action": action, **kwargs},
            )
        )

    def log_security_event(
        self,
        event_type: str,
        severity: AuditSeverity = AuditSeverity.WARNING,
        actor_id: str | None = None,
        **kwargs,
    ) -> None:
        """Log a security event."""
        category_map = {
            "threat": UnifiedAuditCategory.SECURITY_THREAT_DETECTED,
            "encryption": UnifiedAuditCategory.SECURITY_ENCRYPTION,
            "key_rotation": UnifiedAuditCategory.SECURITY_KEY_ROTATION,
            "anomaly": UnifiedAuditCategory.SECURITY_ANOMALY,
        }
        self.log(
            UnifiedAuditEvent(
                category=category_map.get(event_type, UnifiedAuditCategory.SECURITY_ANOMALY),
                action=f"Security event: {event_type}",
                severity=severity,
                actor_id=actor_id,
                details={"event_type": event_type, **kwargs},
            )
        )

    def log_debate_event(
        self,
        debate_id: str,
        action: str,  # started, completed, round_completed
        user_id: str | None = None,
        **kwargs,
    ) -> None:
        """Log a debate lifecycle event."""
        category_map = {
            "started": UnifiedAuditCategory.DEBATE_STARTED,
            "completed": UnifiedAuditCategory.DEBATE_COMPLETED,
        }
        self.log(
            UnifiedAuditEvent(
                category=category_map.get(action, UnifiedAuditCategory.DEBATE_STARTED),
                action=f"Debate {action}",
                actor_id=user_id,
                resource_type="debate",
                resource_id=debate_id,
                details={"action": action, **kwargs},
            )
        )


# Global instance
_unified_logger: UnifiedAuditLogger | None = None

# The HTTP middleware audit logger lives in aragora.server, above this layer, so the
# server registers its factory at startup instead of this module importing it.
_middleware_logger_factory: Callable[[], Any] | None = None


def register_middleware_audit_logger(factory: Callable[[], Any]) -> None:
    """Register the factory that returns the HTTP middleware audit logger."""
    global _middleware_logger_factory
    _middleware_logger_factory = factory


def get_unified_audit_logger() -> UnifiedAuditLogger:
    """Get the global unified audit logger instance."""
    global _unified_logger
    if _unified_logger is None:
        _unified_logger = UnifiedAuditLogger()
    return _unified_logger


def configure_unified_audit_logger(**kwargs) -> UnifiedAuditLogger:
    """Configure and return a new unified audit logger."""
    global _unified_logger
    _unified_logger = UnifiedAuditLogger(**kwargs)
    return _unified_logger


# Convenience functions
def audit_log(event: UnifiedAuditEvent) -> None:
    """Log an audit event using the global logger."""
    get_unified_audit_logger().log(event)


def audit_login(user_id: str, success: bool = True, **kwargs) -> None:
    """Log a login attempt."""
    get_unified_audit_logger().log_auth_login(user_id, success, **kwargs)


def audit_logout(user_id: str, **kwargs) -> None:
    """Log a logout."""
    get_unified_audit_logger().log_auth_logout(user_id, **kwargs)


def audit_access(
    user_id: str,
    permission: str,
    granted: bool = True,
    **kwargs,
) -> None:
    """Log an access control check."""
    get_unified_audit_logger().log_access_check(user_id, permission, granted=granted, **kwargs)


def audit_data(
    user_id: str,
    resource_type: str,
    resource_id: str,
    action: str = "read",
    **kwargs,
) -> None:
    """Log a data access event."""
    get_unified_audit_logger().log_data_access(
        user_id, resource_type, resource_id, action, **kwargs
    )


def audit_admin(admin_id: str, action: str, **kwargs) -> None:
    """Log an administrative action."""
    get_unified_audit_logger().log_admin_action(admin_id, action, **kwargs)


def audit_security(event_type: str, **kwargs) -> None:
    """Log a security event."""
    get_unified_audit_logger().log_security_event(event_type, **kwargs)


def audit_debate(debate_id: str, action: str, **kwargs) -> None:
    """Log a debate event."""
    get_unified_audit_logger().log_debate_event(debate_id, action, **kwargs)


def audit_action(
    user_id: str,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    **kwargs,
) -> None:
    """Log a generic action audit event.

    This is a catch-all for actions that don't fit into other categories,
    such as bot commands, integrations, and custom operations.

    Args:
        user_id: The ID of the user performing the action
        action: Description of the action (e.g., "slack_slash_command")
        resource_type: Type of resource being acted upon
        resource_id: ID of the specific resource
        **kwargs: Additional details to include in the audit event
    """
    get_unified_audit_logger().log(
        UnifiedAuditEvent(
            category=UnifiedAuditCategory.API_REQUEST,
            action=action,
            actor_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            details=kwargs,
        )
    )


__all__ = [
    "UnifiedAuditCategory",
    "AuditOutcome",
    "AuditSeverity",
    "UnifiedAuditEvent",
    "UnifiedAuditLogger",
    "get_unified_audit_logger",
    "configure_unified_audit_logger",
    "audit_log",
    "audit_login",
    "audit_logout",
    "audit_access",
    "audit_data",
    "audit_admin",
    "audit_security",
    "audit_debate",
    "audit_action",
    "register_middleware_audit_logger",
]
