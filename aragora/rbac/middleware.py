"""
RBAC Middleware - HTTP middleware for enforcing access control.

Provides middleware that integrates with the server to enforce
permission checks on all requests automatically.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from re import Pattern
from collections.abc import Callable

from .checker import PermissionChecker, get_permission_checker
from .defaults import SYSTEM_PERMISSIONS
from .models import AuthorizationContext

logger = logging.getLogger(__name__)


def validate_route_permissions(
    route_permissions: list[RoutePermission],
    strict: bool = False,
) -> list[str]:
    """
    Validate that all route permissions are defined in SYSTEM_PERMISSIONS.

    SECURITY: This prevents configuration errors where routes reference
    undefined permissions, which could lead to:
    - Routes accidentally being unprotected (if permission check silently fails)
    - Confusion about which permissions are required

    Args:
        route_permissions: List of route permission rules to validate
        strict: If True, raise ValueError on validation failure

    Returns:
        List of warning messages for undefined permissions
    """
    warnings: list[str] = []

    # Build set of valid permission prefixes for wildcard validation
    valid_prefixes: set[str] = set()
    for perm_key in SYSTEM_PERMISSIONS:
        if "." in perm_key:
            prefix = perm_key.rsplit(".", 1)[0]  # e.g., "admin.config" -> "admin"
            valid_prefixes.add(prefix)
        if ":" in perm_key:
            prefix = perm_key.rsplit(":", 1)[0]  # e.g., "admin:config" -> "admin"
            valid_prefixes.add(prefix)

    def resolve_permission_key(permission_key: str) -> str | None:
        if permission_key in SYSTEM_PERMISSIONS:
            return permission_key
        if ":" in permission_key:
            candidate = permission_key.replace(":", ".")
            if candidate in SYSTEM_PERMISSIONS:
                return candidate
        if "." in permission_key:
            candidate = permission_key.replace(".", ":")
            if candidate in SYSTEM_PERMISSIONS:
                return candidate
        return None

    for rule in route_permissions:
        perm_key = rule.permission_key

        # Skip empty permission keys (unauthenticated or auth-only routes)
        if not perm_key:
            continue

        # Handle wildcard permissions (e.g., "admin.*" or "admin:*")
        if perm_key.endswith(".*") or perm_key.endswith(":*"):
            prefix = perm_key[:-2]  # Strip wildcard suffix
            if prefix not in valid_prefixes:
                msg = (
                    f"SECURITY: Wildcard permission '{perm_key}' references undefined "
                    f"permission prefix '{prefix}'. No permissions with this prefix exist "
                    f"in SYSTEM_PERMISSIONS. Route pattern: {rule.pattern.pattern if hasattr(rule.pattern, 'pattern') else rule.pattern}"
                )
                warnings.append(msg)
                logger.warning(msg)
        else:
            # Standard permission - must exist exactly
            resolved = resolve_permission_key(perm_key)
            if resolved is None:
                msg = (
                    f"SECURITY: Route permission '{perm_key}' is not defined in "
                    f"SYSTEM_PERMISSIONS. This route may have undefined access control. "
                    f"Route pattern: {rule.pattern.pattern if hasattr(rule.pattern, 'pattern') else rule.pattern}"
                )
                warnings.append(msg)
                logger.warning(msg)
            elif resolved != perm_key:
                msg = (
                    f"SECURITY: Route permission '{perm_key}' uses a legacy separator; "
                    f"prefer '{resolved}'. Route pattern: {rule.pattern.pattern if hasattr(rule.pattern, 'pattern') else rule.pattern}"
                )
                warnings.append(msg)
                logger.warning(msg)

    if warnings and strict:
        raise ValueError(
            f"Route permission validation failed with {len(warnings)} undefined permissions. "
            f"See logs for details."
        )

    if warnings:
        logger.error(
            "SECURITY: %s route permission(s) reference undefined permissions. These routes may have incorrect access control.",
            len(warnings),
        )
    else:
        logger.info("Route permission validation passed: all permissions are defined.")

    return warnings


@dataclass
class RoutePermission:
    """
    Permission requirement for a route.

    Attributes:
        pattern: Regex pattern to match route
        method: HTTP method (GET, POST, etc.) or * for all
        permission_key: Required permission
        resource_id_group: Regex group index for resource ID extraction
        allow_unauthenticated: Allow requests without authentication
    """

    pattern: str | Pattern[str]
    method: str
    permission_key: str
    resource_id_group: int | None = None
    allow_unauthenticated: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.pattern, str):
            self.pattern = re.compile(self.pattern)

    def matches(self, path: str, method: str) -> tuple[bool, str | None]:
        """
        Check if this rule matches the request.

        Returns:
            Tuple of (matches, resource_id or None)
        """
        if self.method != "*" and self.method.upper() != method.upper():
            return False, None

        # Pattern is always compiled in __post_init__
        if not isinstance(self.pattern, Pattern):
            raise RuntimeError("RoutePermission pattern must be a compiled regex")
        match = self.pattern.match(path)
        if not match:
            return False, None

        resource_id = None
        if self.resource_id_group is not None:
            try:
                resource_id = match.group(self.resource_id_group)
            except IndexError as e:
                logger.debug("matches encountered an error: %s", e)

        return True, resource_id


@dataclass
class RBACMiddlewareConfig:
    """
    Configuration for RBAC middleware.

    Attributes:
        route_permissions: List of route permission rules
        default_authenticated: Require authentication by default
        bypass_paths: Paths that bypass all permission checks
        bypass_methods: Methods that bypass checks (e.g., OPTIONS for CORS)
        permission_checker: Custom permission checker instance
    """

    route_permissions: list[RoutePermission] = field(default_factory=list)
    default_authenticated: bool = True
    bypass_paths: set[str] = field(
        default_factory=lambda: {
            "/health",
            "/healthz",
            "/ready",
            "/metrics",
            "/api/docs",
            "/openapi.json",
        }
    )
    bypass_methods: set[str] = field(default_factory=lambda: {"OPTIONS"})
    permission_checker: PermissionChecker | None = None


# Default route permission rules
# Note: Route patterns use (?:v1/)? to match both /api/ and /api/v1/ prefixes,
# since the frontend uses versioned endpoints (e.g., /api/v1/debates) and the
# handler_registry normalizes them. Without this, versioned paths fall through
# to the default policy instead of being properly permission-checked.
DEFAULT_ROUTE_PERMISSIONS = [
    # Debates (matches both /api/debates and /api/v1/debates)
    RoutePermission(r"^/api/(?:v1/)?debates?$", "POST", "debates.create"),
    RoutePermission(r"^/api/(?:v1/)?debates?$", "GET", "debates.read"),
    RoutePermission(r"^/api/(?:v1/)?debates?/([^/]+)$", "GET", "debates.read", 1),
    RoutePermission(r"^/api/(?:v1/)?debates?/([^/]+)$", "PUT", "debates.update", 1),
    RoutePermission(r"^/api/(?:v1/)?debates?/([^/]+)$", "PATCH", "debates.update", 1),
    RoutePermission(r"^/api/(?:v1/)?debates?/([^/]+)$", "DELETE", "debates.delete", 1),
    RoutePermission(r"^/api/(?:v1/)?debates?/([^/]+)/run$", "POST", "debates.run", 1),
    RoutePermission(r"^/api/(?:v1/)?debates?/([^/]+)/stop$", "POST", "debates.stop", 1),
    RoutePermission(r"^/api/(?:v1/)?debates?/([^/]+)/fork$", "POST", "debates.fork", 1),
    # Settlements
    RoutePermission(r"^/api/(?:v1/)?settlements?$", "GET", "settlements:read"),
    RoutePermission(r"^/api/(?:v1/)?settlements/history$", "GET", "settlements:read"),
    RoutePermission(r"^/api/(?:v1/)?settlements/summary$", "GET", "settlements:read"),
    RoutePermission(
        r"^/api/(?:v1/)?settlements/agent/([^/]+)/accuracy$",
        "GET",
        "settlements:read",
        1,
    ),
    RoutePermission(r"^/api/(?:v1/)?settlements/([^/]+)$", "GET", "settlements:read", 1),
    RoutePermission(
        r"^/api/(?:v1/)?settlements/([^/]+)/settle$",
        "POST",
        "settlements:write",
        1,
    ),
    RoutePermission(r"^/api/(?:v1/)?settlements/batch$", "POST", "settlements:write"),
    # Interrogation
    RoutePermission(r"^/api/(?:v1/)?interrogation/start$", "POST", "debates.create"),
    RoutePermission(r"^/api/(?:v1/)?interrogation/answer$", "POST", "debates.create"),
    RoutePermission(r"^/api/(?:v1/)?interrogation/crystallize$", "POST", "debates.create"),
    # Agents (matches both /api/agents and /api/v1/agents)
    RoutePermission(r"^/api/(?:v1/)?agents?$", "GET", "agents.read"),
    RoutePermission(r"^/api/(?:v1/)?agents?$", "POST", "agents.create"),
    RoutePermission(r"^/api/(?:v1/)?agents?/([^/]+)$", "GET", "agents.read", 1),
    RoutePermission(r"^/api/(?:v1/)?agents?/([^/]+)$", "PUT", "agents.update", 1),
    RoutePermission(r"^/api/(?:v1/)?agents?/([^/]+)$", "DELETE", "agents.delete", 1),
    # Workflows (matches both /api/workflows and /api/v1/workflows)
    RoutePermission(r"^/api/(?:v1/)?workflows?$", "GET", "workflows.read"),
    RoutePermission(r"^/api/(?:v1/)?workflows?$", "POST", "workflows.create"),
    RoutePermission(r"^/api/(?:v1/)?workflows?/([^/]+)$", "GET", "workflows.read", 1),
    RoutePermission(r"^/api/(?:v1/)?workflows?/([^/]+)$", "DELETE", "workflows.delete", 1),
    RoutePermission(r"^/api/(?:v1/)?workflows?/([^/]+)/execute$", "POST", "workflows.run", 1),
    # Memory
    RoutePermission(r"^/api/(?:v1/)?memory", "GET", "memory.read"),
    RoutePermission(r"^/api/(?:v1/)?memory", "POST", "memory.update"),
    RoutePermission(r"^/api/(?:v1/)?memory", "DELETE", "memory.delete"),
    # Analytics
    RoutePermission(r"^/api/(?:v1/)?analytics", "GET", "analytics.read"),
    RoutePermission(r"^/api/(?:v1/)?analytics/export", "POST", "analytics.export_data"),
    # Training
    RoutePermission(r"^/api/(?:v1/)?training", "GET", "training.read"),
    RoutePermission(r"^/api/(?:v1/)?training/export", "POST", "training.create"),
    # Evidence
    RoutePermission(r"^/api/(?:v1/)?evidence", "GET", "evidence.read"),
    RoutePermission(r"^/api/(?:v1/)?evidence", "POST", "evidence.create"),
    # Connectors
    RoutePermission(r"^/api/(?:v1/)?connectors?$", "GET", "connectors.read"),
    RoutePermission(r"^/api/(?:v1/)?connectors?$", "POST", "connectors.create"),
    RoutePermission(r"^/api/(?:v1/)?connectors?/([^/]+)$", "DELETE", "connectors.delete", 1),
    # Webhooks
    RoutePermission(r"^/api/(?:v1/)?webhooks?$", "GET", "webhooks.read"),
    RoutePermission(r"^/api/(?:v1/)?webhooks?$", "POST", "webhooks.create"),
    RoutePermission(r"^/api/(?:v1/)?webhooks?/([^/]+)$", "DELETE", "webhooks.delete", 1),
    # Checkpoints
    RoutePermission(r"^/api/(?:v1/)?checkpoints?$", "GET", "checkpoints.read"),
    RoutePermission(r"^/api/(?:v1/)?checkpoints?$", "POST", "checkpoints.create"),
    RoutePermission(r"^/api/(?:v1/)?checkpoints?/([^/]+)$", "DELETE", "checkpoints.delete", 1),
    # Admin routes - require admin permission
    RoutePermission(r"^/api/(?:v1/)?admin", "*", "admin.*"),
    # User management
    RoutePermission(r"^/api/(?:v1/)?users?$", "GET", "users.read"),
    RoutePermission(r"^/api/(?:v1/)?users?/invite$", "POST", "users.invite"),
    RoutePermission(r"^/api/(?:v1/)?users?/([^/]+)$", "DELETE", "users.remove", 1),
    RoutePermission(r"^/api/(?:v1/)?users?/([^/]+)/role$", "PUT", "users.change_role", 1),
    # Organization
    RoutePermission(r"^/api/(?:v1/)?org", "GET", "organization.read"),
    RoutePermission(r"^/api/(?:v1/)?org", "PUT", "organization.update"),
    RoutePermission(r"^/api/(?:v1/)?org", "PATCH", "organization.update"),
    RoutePermission(r"^/api/(?:v1/)?org/billing", "*", "organization.manage_billing"),
    RoutePermission(r"^/api/(?:v1/)?org/audit", "GET", "organization.view_audit"),
    RoutePermission(r"^/api/(?:v1/)?org/export", "POST", "organization.export_data"),
    # API keys
    RoutePermission(r"^/api/(?:v1/)?keys?$", "GET", "api.generate_key"),
    RoutePermission(r"^/api/(?:v1/)?keys?$", "POST", "api.generate_key"),
    RoutePermission(r"^/api/(?:v1/)?keys?/([^/]+)$", "DELETE", "api.revoke_key", 1),
    # Auth routes - allow unauthenticated
    RoutePermission(r"^/api/auth/login", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/auth/register", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/auth/callback", "*", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/auth/refresh", "POST", "", allow_unauthenticated=True),
    # Decisions (unified decision routing)
    RoutePermission(r"^/api/decisions?$", "POST", "decisions.create"),
    RoutePermission(r"^/api/decisions?$", "GET", "decisions.read"),
    RoutePermission(r"^/api/decisions?/([^/]+)$", "GET", "decisions.read", 1),
    RoutePermission(r"^/api/decisions?/([^/]+)/status$", "GET", "decisions.read", 1),
    RoutePermission(r"^/api/decisions?/([^/]+)/explain$", "GET", "decisions.read", 1),
    RoutePermission(r"^/api/decisions?/([^/]+)/cancel$", "POST", "decisions.update", 1),
    RoutePermission(r"^/api/decisions?/([^/]+)/retry$", "POST", "decisions.update", 1),
    # Versioned decision endpoints (v1)
    RoutePermission(r"^/api/v1/decisions?$", "POST", "decisions.create"),
    RoutePermission(r"^/api/v1/decisions?$", "GET", "decisions.read"),
    RoutePermission(r"^/api/v1/decisions?/([^/]+)$", "GET", "decisions.read", 1),
    RoutePermission(r"^/api/v1/decisions?/([^/]+)/status$", "GET", "decisions.read", 1),
    RoutePermission(r"^/api/v1/decisions?/([^/]+)/explain$", "GET", "decisions.read", 1),
    RoutePermission(r"^/api/v1/decisions?/([^/]+)/cancel$", "POST", "decisions.update", 1),
    RoutePermission(r"^/api/v1/decisions?/([^/]+)/retry$", "POST", "decisions.update", 1),
    # Decision plan gold path (debate -> plan -> approve/reject -> execute -> outcome)
    RoutePermission(r"^/api/(?:v1/)?decisions/plans$", "POST", "decisions.create"),
    RoutePermission(r"^/api/(?:v1/)?decisions/plans$", "GET", "decisions.read"),
    RoutePermission(r"^/api/(?:v1/)?decisions/plans/([^/]+)$", "GET", "decisions.read", 1),
    RoutePermission(
        r"^/api/(?:v1/)?decisions/plans/([^/]+)/outcome$",
        "GET",
        "decisions.read",
        1,
    ),
    RoutePermission(
        r"^/api/(?:v1/)?decisions/plans/([^/]+)/(approve|reject|execute)$",
        "POST",
        "decisions.update",
        1,
    ),
    # Policies - governance management
    RoutePermission(r"^/api/v1/policies$", "GET", "policies.read"),
    RoutePermission(r"^/api/v1/policies$", "POST", "policies.create"),
    RoutePermission(r"^/api/v1/policies/([^/]+)$", "GET", "policies.read", 1),
    RoutePermission(r"^/api/v1/policies/([^/]+)$", "PATCH", "policies.update", 1),
    RoutePermission(r"^/api/v1/policies/([^/]+)$", "DELETE", "policies.delete", 1),
    RoutePermission(r"^/api/v1/policies/([^/]+)/toggle$", "POST", "policies.update", 1),
    RoutePermission(r"^/api/v1/policies/([^/]+)/violations$", "GET", "policies.read", 1),
    # Compliance
    RoutePermission(r"^/api/v1/compliance/violations$", "GET", "compliance.read"),
    RoutePermission(r"^/api/v1/compliance/violations/([^/]+)$", "GET", "compliance.read", 1),
    RoutePermission(r"^/api/v1/compliance/violations/([^/]+)$", "PATCH", "compliance.update", 1),
    RoutePermission(r"^/api/v1/compliance/check$", "POST", "compliance.check"),
    RoutePermission(r"^/api/v1/compliance/stats$", "GET", "compliance.read"),
    # Control plane - task management
    RoutePermission(r"^/api/v1/control-plane/tasks$", "GET", "control_plane.read"),
    RoutePermission(r"^/api/v1/control-plane/tasks$", "POST", "control_plane.submit"),
    RoutePermission(r"^/api/v1/control-plane/tasks/([^/]+)$", "GET", "control_plane.read", 1),
    RoutePermission(
        r"^/api/v1/control-plane/tasks/([^/]+)/cancel$", "POST", "control_plane.cancel", 1
    ),
    RoutePermission(r"^/api/v1/control-plane/agents$", "GET", "control_plane.read"),
    RoutePermission(r"^/api/v1/control-plane/agents/([^/]+)$", "GET", "control_plane.read", 1),
    RoutePermission(r"^/api/v1/control-plane/deliberations$", "GET", "control_plane.read"),
    RoutePermission(r"^/api/v1/control-plane/deliberations$", "POST", "control_plane.deliberate"),
    RoutePermission(r"^/api/v1/control-plane/stats$", "GET", "control_plane.read"),
    RoutePermission(r"^/api/v1/control-plane/health$", "GET", "", allow_unauthenticated=True),
    # Audit findings workflow
    RoutePermission(r"^/api/audit/findings/bulk-action$", "POST", "findings.bulk"),
    RoutePermission(r"^/api/audit/findings/my-assignments$", "GET", "findings.read"),
    RoutePermission(r"^/api/audit/findings/overdue$", "GET", "findings.read"),
    RoutePermission(r"^/api/audit/findings/([^/]+)/status$", "PATCH", "findings.update", 1),
    RoutePermission(r"^/api/audit/findings/([^/]+)/assign$", "PATCH", "findings.assign", 1),
    RoutePermission(r"^/api/audit/findings/([^/]+)/unassign$", "POST", "findings.assign", 1),
    RoutePermission(r"^/api/audit/findings/([^/]+)/comments$", "*", "findings.read", 1),
    RoutePermission(r"^/api/audit/findings/([^/]+)/history$", "GET", "findings.read", 1),
    RoutePermission(r"^/api/audit/findings/([^/]+)/priority$", "PATCH", "findings.update", 1),
    RoutePermission(r"^/api/audit/findings/([^/]+)/due-date$", "PATCH", "findings.update", 1),
    RoutePermission(r"^/api/audit/findings/([^/]+)/link$", "POST", "findings.update", 1),
    RoutePermission(r"^/api/audit/findings/([^/]+)/duplicate$", "POST", "findings.update", 1),
    RoutePermission(r"^/api/audit/workflow/states$", "GET", "findings.read"),
    RoutePermission(r"^/api/audit/presets$", "GET", "findings.read"),
    RoutePermission(r"^/api/audit/types$", "GET", "findings.read"),
    # =========================================================================
    # Authentication Routes
    # =========================================================================
    # Public (no auth required) - login flows and callbacks
    RoutePermission(r"^/api/(v1/)?auth/login$", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?auth/register$", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?auth/signup$", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?auth/refresh$", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?auth/verify-email$", "*", "", allow_unauthenticated=True),
    RoutePermission(
        r"^/api/(v1/)?auth/resend-verification$", "POST", "", allow_unauthenticated=True
    ),
    RoutePermission(r"^/api/(v1/)?auth/check-invite$", "GET", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?auth/accept-invite$", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?auth/mfa/verify$", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?auth/forgot-password$", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?auth/reset-password$", "POST", "", allow_unauthenticated=True),
    # SSO - public callbacks
    RoutePermission(r"^/api/(v1/)?auth/sso/login$", "*", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?auth/sso/callback$", "*", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?auth/sso/metadata$", "GET", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?auth/sso/providers$", "GET", "", allow_unauthenticated=True),
    RoutePermission(r"^/auth/sso/.*$", "*", "", allow_unauthenticated=True),
    # OAuth - public start and callbacks
    RoutePermission(r"^/api/(v1/)?auth/oauth/[^/]+$", "GET", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?auth/oauth/[^/]+/callback$", "*", "", allow_unauthenticated=True),
    # Authenticated user endpoints
    RoutePermission(r"^/api/(v1/)?auth/me$", "GET", "authentication.read"),
    RoutePermission(r"^/api/(v1/)?auth/me$", "PATCH", "authentication.read"),
    RoutePermission(r"^/api/(v1/)?auth/me$", "PUT", "authentication.read"),
    RoutePermission(r"^/api/(v1/)?auth/logout$", "POST", "authentication.revoke"),
    RoutePermission(r"^/api/(v1/)?auth/logout-all$", "POST", "authentication.revoke"),
    RoutePermission(r"^/api/(v1/)?auth/password$", "POST", "authentication.read"),
    RoutePermission(r"^/api/(v1/)?auth/change-password$", "POST", "authentication.read"),
    # Session management
    RoutePermission(r"^/api/(v1/)?auth/sessions$", "GET", "session.list_active"),
    RoutePermission(r"^/api/(v1/)?auth/sessions/([^/]+)$", "DELETE", "session.revoke", 1),
    RoutePermission(r"^/api/(v1/)?auth/revoke$", "POST", "session.revoke"),
    # MFA management
    RoutePermission(r"^/api/(v1/)?auth/mfa/setup$", "POST", "authentication.create"),
    RoutePermission(r"^/api/(v1/)?auth/mfa/enable$", "POST", "authentication.update"),
    RoutePermission(r"^/api/(v1/)?auth/mfa/disable$", "POST", "authentication.update"),
    RoutePermission(r"^/api/(v1/)?auth/mfa/backup-codes$", "POST", "authentication.read"),
    RoutePermission(r"^/api/(v1/)?auth/mfa/status$", "GET", "authentication.read"),
    # API key management
    RoutePermission(r"^/api/(v1/)?auth/api-key$", "POST", "api_key.create"),
    RoutePermission(r"^/api/(v1/)?auth/api-key$", "DELETE", "api_key.revoke"),
    RoutePermission(r"^/api/(v1/)?auth/api-keys$", "GET", "authentication.read"),
    RoutePermission(r"^/api/(v1/)?auth/api-keys$", "POST", "api_key.create"),
    RoutePermission(r"^/api/(v1/)?auth/api-keys/([^/]+)$", "DELETE", "api_key.revoke", 1),
    # Organization management (auth-related)
    RoutePermission(r"^/api/(v1/)?auth/invite$", "POST", "organization.invite"),
    RoutePermission(r"^/api/(v1/)?auth/setup-organization$", "POST", "organization.update"),
    RoutePermission(r"^/api/(v1/)?onboarding/complete$", "POST", "authentication.read"),
    RoutePermission(r"^/api/(v1/)?onboarding/status$", "GET", "authentication.read"),
    # OAuth account linking (authenticated)
    RoutePermission(r"^/api/(v1/)?auth/oauth/link$", "POST", "authentication.update"),
    RoutePermission(r"^/api/(v1/)?auth/oauth/unlink$", "DELETE", "authentication.update"),
    RoutePermission(r"^/api/(v1/)?user/oauth-providers$", "GET", "authentication.read"),
    # Social integration OAuth (authenticated for install, public for callback)
    RoutePermission(r"^/api/integrations/slack/install$", "GET", "connectors.create"),
    RoutePermission(r"^/api/integrations/slack/callback$", "*", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/integrations/slack/uninstall$", "POST", "connectors.delete"),
    RoutePermission(r"^/api/integrations/teams/install$", "GET", "connectors.create"),
    RoutePermission(r"^/api/integrations/teams/callback$", "*", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/integrations/discord/install$", "GET", "connectors.create"),
    RoutePermission(r"^/api/integrations/discord/callback$", "*", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/integrations/discord/uninstall$", "POST", "connectors.delete"),
    # =========================================================================
    # External Webhooks - MUST be publicly accessible (called by external services)
    # =========================================================================
    # Payment webhooks (Stripe calls these)
    RoutePermission(r"^/api/(v1/)?webhooks/stripe$", "POST", "", allow_unauthenticated=True),
    # Email service webhooks (Gmail Pub/Sub, Outlook Graph, SendGrid, SES)
    RoutePermission(
        r"^/api/(v1/)?webhooks/(gmail|outlook)(/validate)?$", "POST", "", allow_unauthenticated=True
    ),
    RoutePermission(
        r"^/api/(v1/)?bots/email/webhook/(sendgrid|ses)$", "POST", "", allow_unauthenticated=True
    ),
    # Chat platform webhooks (Telegram, WhatsApp, Google Chat, Slack, Discord, Teams)
    RoutePermission(
        r"^/api/(v1/)?bots/telegram/webhook(/[^/]+)?$", "*", "", allow_unauthenticated=True
    ),
    RoutePermission(r"^/api/(v1/)?bots/whatsapp/webhook$", "*", "", allow_unauthenticated=True),
    RoutePermission(
        r"^/api/(v1/)?bots/google-chat/webhook$", "POST", "", allow_unauthenticated=True
    ),
    RoutePermission(r"^/api/(v1/)?bots/slack/webhook$", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?bots/discord/webhook$", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?bots/zoom/events$", "POST", "", allow_unauthenticated=True),
    # Unified chat router webhooks
    RoutePermission(r"^/api/(v1/)?chat/webhook$", "POST", "", allow_unauthenticated=True),
    RoutePermission(
        r"^/api/(v1/)?chat/(slack|teams|discord|google_chat|telegram|whatsapp)/webhook$",
        "POST",
        "",
        allow_unauthenticated=True,
    ),
    # Social integrations webhooks
    RoutePermission(
        r"^/api/(v1/)?integrations/(telegram|whatsapp)/webhook$",
        "*",
        "",
        allow_unauthenticated=True,
    ),
    # Scheduler trigger webhooks (internal but may be called by cron services)
    RoutePermission(
        r"^/api/(v1/)?scheduler/webhooks/[^/]+$", "POST", "", allow_unauthenticated=True
    ),
    # Playground - public demo endpoints (rate-limited, mock agents only)
    RoutePermission(r"^/api/(v1/)?playground/debate/?$", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?playground/status$", "GET", "", allow_unauthenticated=True),
    # ODR signing-key trust anchor - public Ed25519 key only, auth-free by
    # design so external auditors can verify decision receipts (issue #8804)
    RoutePermission(
        r"^/\.well-known/aragora-odr-signing-key$", "GET", "", allow_unauthenticated=True
    ),
    RoutePermission(r"^/api/v2/receipts/signing-key$", "GET", "", allow_unauthenticated=True),
    # Public ODR receipt surface (architecture §2.10): the ODR export document
    # and the stateless verifier are the two routes an external auditor needs
    # without credentials. The export handler still requires receipts:read for
    # every non-ODR format.
    RoutePermission(r"^/api/v2/receipts/[^/]+/export$", "GET", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/v2/receipts/verify$", "POST", "", allow_unauthenticated=True),
    # Health endpoints (additional patterns)
    RoutePermission(
        r"^/api/(v1/)?health(/detailed|/deep|/stores)?$", "GET", "", allow_unauthenticated=True
    ),
    # OAuth callbacks (user returns from external auth provider)
    RoutePermission(
        r"^/api/(v1/)?auth/oauth/callback(/[^/]+)?$", "*", "", allow_unauthenticated=True
    ),
    RoutePermission(r"^/api/(v1/)?auth/oauth/providers$", "GET", "", allow_unauthenticated=True),
    # ── Budget endpoints ──
    RoutePermission(r"^/api/v1/budgets$", "GET", "budget.read"),
    RoutePermission(r"^/api/v1/budgets$", "POST", "budget.set_limit"),
    RoutePermission(r"^/api/v1/budgets/summary$", "GET", "budget.read"),
    RoutePermission(r"^/api/v1/budgets/trends$", "GET", "budget.read"),
    RoutePermission(r"^/api/v1/budgets/check$", "POST", "budget.read"),
    RoutePermission(r"^/api/v1/budgets/([^/]+)$", "GET", "budget.read", 1),
    RoutePermission(r"^/api/v1/budgets/([^/]+)$", "PATCH", "budget.set_limit", 1),
    RoutePermission(r"^/api/v1/budgets/([^/]+)$", "DELETE", "budget.set_limit", 1),
    RoutePermission(r"^/api/v1/budgets/([^/]+)/alerts$", "GET", "budget.read", 1),
    RoutePermission(
        r"^/api/v1/budgets/([^/]+)/alerts/[^/]+/acknowledge$", "POST", "budget.set_limit", 1
    ),
    RoutePermission(r"^/api/v1/budgets/([^/]+)/override$", "POST", "budget.override", 1),
    RoutePermission(r"^/api/v1/budgets/([^/]+)/override/[^/]+$", "DELETE", "budget.override", 1),
    RoutePermission(r"^/api/v1/budgets/([^/]+)/reset$", "POST", "budget.set_limit", 1),
    RoutePermission(r"^/api/v1/budgets/([^/]+)/transactions$", "GET", "budget.read", 1),
    RoutePermission(r"^/api/v1/budgets/([^/]+)/trends$", "GET", "budget.read", 1),
    # SME budget endpoints
    RoutePermission(r"^/api/v1/sme/budgets$", "GET", "budget.read"),
    RoutePermission(r"^/api/v1/sme/budgets$", "POST", "budget.set_limit"),
    RoutePermission(r"^/api/v1/sme/budgets/check$", "POST", "budget.read"),
    RoutePermission(r"^/api/v1/sme/budgets/([^/]+)$", "GET", "budget.read", 1),
    RoutePermission(r"^/api/v1/sme/budgets/([^/]+)$", "PATCH", "budget.set_limit", 1),
    RoutePermission(r"^/api/v1/sme/budgets/([^/]+)$", "DELETE", "budget.set_limit", 1),
    RoutePermission(r"^/api/v1/sme/budgets/([^/]+)/alerts$", "GET", "budget.read", 1),
    RoutePermission(r"^/api/v1/sme/budgets/([^/]+)/alerts/ack$", "POST", "budget.set_limit", 1),
    RoutePermission(r"^/api/v1/sme/budgets/([^/]+)/transactions$", "GET", "budget.read", 1),
    # ── Device endpoints ──
    RoutePermission(r"^/api/(v1/)?devices/register$", "POST", "devices.write"),
    RoutePermission(r"^/api/(v1/)?devices/health$", "GET", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?devices/alexa/webhook$", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?devices/google/webhook$", "POST", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/(v1/)?devices/([^/]+)$", "GET", "devices.read", 2),
    RoutePermission(r"^/api/(v1/)?devices/([^/]+)$", "DELETE", "devices.write", 2),
    RoutePermission(r"^/api/(v1/)?devices/([^/]+)/notify$", "POST", "devices.notify", 2),
    RoutePermission(r"^/api/(v1/)?devices/user/([^/]+)$", "GET", "devices.read", 2),
    RoutePermission(r"^/api/(v1/)?devices/user/([^/]+)/notify$", "POST", "devices.notify", 2),
    # ── Singular agent profile endpoints ──
    RoutePermission(r"^/api/(v1/)?agent/compare$", "GET", "agents.read"),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/profile$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/history$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/calibration$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/consistency$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/flips$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/network$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/rivals$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/allies$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/moments$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/positions$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/domains$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/performance$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/metadata$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/head-to-head/[^/]+$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/opponent-briefing/[^/]+$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/introspect$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/persona$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/grounded-persona$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/identity-prompt$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/accuracy$", "GET", "agents.read", 2),
    RoutePermission(r"^/api/(v1/)?agent/([^/]+)/reputation$", "GET", "agents.read", 2),
    # ── Flip tracking endpoints ──
    RoutePermission(r"^/api/(v1/)?flips/recent$", "GET", "agents.read"),
    RoutePermission(r"^/api/(v1/)?flips/summary$", "GET", "agents.read"),
    # ── Queue management ──
    RoutePermission(r"^/api/(v1/)?queue/stats$", "GET", "queue.read"),
    RoutePermission(r"^/api/(v1/)?queue/workers$", "GET", "queue.read"),
    RoutePermission(r"^/api/(v1/)?queue/stale$", "GET", "queue.read"),
    RoutePermission(r"^/api/(v1/)?queue/jobs$", "GET", "queue.read"),
    RoutePermission(r"^/api/(v1/)?queue/jobs$", "POST", "queue.manage"),
    RoutePermission(r"^/api/(v1/)?queue/jobs/([^/]+)$", "GET", "queue.read", 2),
    RoutePermission(r"^/api/(v1/)?queue/jobs/([^/]+)/retry$", "POST", "queue.manage", 2),
    RoutePermission(r"^/api/(v1/)?queue/jobs/([^/]+)$", "DELETE", "queue.manage", 2),
    RoutePermission(r"^/api/(v1/)?queue/dlq$", "GET", "queue.admin"),
    RoutePermission(r"^/api/(v1/)?queue/dlq/requeue$", "POST", "queue.admin"),
    RoutePermission(r"^/api/(v1/)?queue/dlq/([^/]+)/requeue$", "POST", "queue.admin", 2),
    RoutePermission(r"^/api/(v1/)?queue/cleanup$", "POST", "queue.admin"),
    # ── Workspace management ──
    RoutePermission(r"^/api/(v1/)?workspaces$", "GET", "workspace.read"),
    RoutePermission(r"^/api/(v1/)?workspaces$", "POST", "workspace.create"),
    RoutePermission(r"^/api/(v1/)?workspaces/profiles$", "GET", "workspace.read"),
    RoutePermission(r"^/api/(v1/)?workspaces/([^/]+)$", "GET", "workspace.read", 2),
    RoutePermission(r"^/api/(v1/)?workspaces/([^/]+)$", "DELETE", "workspace.delete", 2),
    RoutePermission(r"^/api/(v1/)?workspaces/([^/]+)/members$", "POST", "workspace.create", 2),
    RoutePermission(
        r"^/api/(v1/)?workspaces/([^/]+)/members/([^/]+)$", "DELETE", "workspace.delete", 2
    ),
    # ── Retention policies ──
    RoutePermission(r"^/api/(v1/)?retention/policies$", "GET", "data_retention.read"),
    RoutePermission(r"^/api/(v1/)?retention/policies$", "POST", "data_retention.update"),
    RoutePermission(r"^/api/(v1/)?retention/policies/([^/]+)$", "PUT", "data_retention.update", 2),
    RoutePermission(
        r"^/api/(v1/)?retention/policies/([^/]+)$", "DELETE", "data_retention.update", 2
    ),
    RoutePermission(
        r"^/api/(v1/)?retention/policies/([^/]+)/execute$", "POST", "data_retention.update", 2
    ),
    RoutePermission(r"^/api/(v1/)?retention/expiring$", "GET", "data_retention.read"),
    # ── Content classification ──
    RoutePermission(r"^/api/(v1/)?classify$", "POST", "data_classification.classify"),
    RoutePermission(r"^/api/(v1/)?classify/policy/[^/]+$", "GET", "data_classification.read"),
    RoutePermission(r"^/api/(v1/)?data-classification/policy$", "GET", "data_classification.read"),
    RoutePermission(
        r"^/api/(v1/)?data-classification/classify$", "POST", "data_classification.classify"
    ),
    RoutePermission(
        r"^/api/(v1/)?data-classification/validate$", "POST", "data_classification.read"
    ),
    RoutePermission(
        r"^/api/(v1/)?data-classification/enforce$", "POST", "data_classification.read"
    ),
    # ── Audit entries ──
    RoutePermission(r"^/api/(v1/)?audit/entries$", "GET", "audit_log.read"),
    RoutePermission(r"^/api/(v1/)?audit/report$", "GET", "audit_log.read"),
    RoutePermission(r"^/api/(v1/)?audit/verify$", "GET", "audit_log.read"),
    RoutePermission(r"^/api/(v1/)?audit/actor/([^/]+)$", "GET", "audit_log.read", 2),
    RoutePermission(r"^/api/(v1/)?audit/resource/([^/]+)$", "GET", "audit_log.read", 2),
    RoutePermission(r"^/api/(v1/)?audit/denied$", "GET", "audit_log.read"),
    # ── Email services ──
    RoutePermission(r"^/api/(v1/)?email/followups/mark$", "POST", "email.create"),
    RoutePermission(r"^/api/(v1/)?email/followups/pending$", "GET", "email.read"),
    RoutePermission(r"^/api/(v1/)?email/followups/check-replies$", "POST", "email.read"),
    RoutePermission(r"^/api/(v1/)?email/followups/auto-detect$", "POST", "email.create"),
    RoutePermission(r"^/api/(v1/)?email/followups/([^/]+)/resolve$", "POST", "email.update", 2),
    RoutePermission(r"^/api/(v1/)?email/([^/]+)/snooze-suggestions$", "GET", "email.read", 2),
    RoutePermission(r"^/api/(v1/)?email/([^/]+)/snooze$", "POST", "email.update", 2),
    RoutePermission(r"^/api/(v1/)?email/([^/]+)/snooze$", "DELETE", "email.update", 2),
    RoutePermission(r"^/api/(v1/)?email/snoozed$", "GET", "email.read"),
    RoutePermission(r"^/api/(v1/)?email/snooze/process-due$", "POST", "email.update"),
    RoutePermission(r"^/api/(v1/)?email/categories$", "GET", "email.read"),
    RoutePermission(r"^/api/(v1/)?email/categories/learn$", "POST", "email.create"),
    # ── SCIM 2.0 provisioning ──
    RoutePermission(r"^/scim/v2/Users$", "GET", "users.read"),
    RoutePermission(r"^/scim/v2/Users$", "POST", "users.invite"),
    RoutePermission(r"^/scim/v2/Users/([^/]+)$", "GET", "users.read", 1),
    RoutePermission(r"^/scim/v2/Users/([^/]+)$", "PUT", "users.change_role", 1),
    RoutePermission(r"^/scim/v2/Users/([^/]+)$", "PATCH", "users.change_role", 1),
    RoutePermission(r"^/scim/v2/Users/([^/]+)$", "DELETE", "users.remove", 1),
    RoutePermission(r"^/scim/v2/Groups$", "GET", "organization.read"),
    RoutePermission(r"^/scim/v2/Groups$", "POST", "organization.update"),
    RoutePermission(r"^/scim/v2/Groups/([^/]+)$", "GET", "organization.read", 1),
    RoutePermission(r"^/scim/v2/Groups/([^/]+)$", "PUT", "organization.update", 1),
    RoutePermission(r"^/scim/v2/Groups/([^/]+)$", "PATCH", "organization.update", 1),
    RoutePermission(r"^/scim/v2/Groups/([^/]+)$", "DELETE", "organization.update", 1),
    RoutePermission(r"^/scim/v2/ServiceProviderConfig$", "GET", ""),
    RoutePermission(r"^/scim/v2/Schemas$", "GET", ""),
    RoutePermission(r"^/scim/v2/ResourceTypes$", "GET", ""),
    # ── Skill marketplace ──
    RoutePermission(r"^/api/(v1/)?skills/marketplace/search$", "GET", "skills.read"),
    RoutePermission(r"^/api/(v1/)?skills/marketplace/installed$", "GET", "skills.read"),
    RoutePermission(r"^/api/(v1/)?skills/marketplace/stats$", "GET", "skills.read"),
    RoutePermission(r"^/api/(v1/)?skills/marketplace/([^/]+)$", "GET", "skills.read", 2),
    RoutePermission(r"^/api/(v1/)?skills/marketplace/([^/]+)/install$", "POST", "skills.update", 2),
    RoutePermission(r"^/api/(v1/)?skills/marketplace/publish$", "POST", "skills.create"),
    RoutePermission(r"^/api/(v1/)?skills/marketplace/([^/]+)/rate$", "POST", "skills.update", 2),
    # ── External automation integrations ──
    RoutePermission(r"^/api/(v1/)?integrations/zapier/", "*", "connectors.create"),
    RoutePermission(r"^/api/(v1/)?integrations/make/", "*", "connectors.create"),
    RoutePermission(r"^/api/(v1/)?integrations/n8n/", "*", "connectors.create"),
    # ── Orchestration ──
    RoutePermission(r"^/api/(v1/)?orchestration/templates$", "GET", "orchestration.read"),
    RoutePermission(r"^/api/(v1/)?orchestration/status/([^/]+)$", "GET", "orchestration.read", 2),
    RoutePermission(r"^/api/(v1/)?orchestration/deliberate$", "POST", "orchestration.execute"),
    RoutePermission(r"^/api/(v1/)?orchestration/deliberate/sync$", "POST", "orchestration.execute"),
    # ── Features management ──
    RoutePermission(r"^/api/(v1/)?features$", "GET", "features.read"),
    RoutePermission(r"^/api/(v1/)?features$", "POST", "features.write"),
    RoutePermission(r"^/api/(v1/)?features/([^/]+)$", "GET", "features.read", 2),
    RoutePermission(r"^/api/(v1/)?features/([^/]+)$", "PUT", "features.write", 2),
    RoutePermission(r"^/api/(v1/)?features/([^/]+)$", "PATCH", "features.write", 2),
    RoutePermission(r"^/api/(v1/)?features/([^/]+)$", "DELETE", "features.delete", 2),
    RoutePermission(r"^/api/(v1/)?features/([^/]+)/enable$", "POST", "features.write", 2),
    RoutePermission(r"^/api/(v1/)?features/([^/]+)/disable$", "POST", "features.write", 2),
    # ── Knowledge base ──
    RoutePermission(r"^/api/(v1/)?knowledge$", "GET", "knowledge.read"),
    RoutePermission(r"^/api/(v1/)?knowledge$", "POST", "knowledge.write"),
    RoutePermission(r"^/api/(v1/)?knowledge/search$", "GET", "knowledge.read"),
    RoutePermission(r"^/api/(v1/)?knowledge/search$", "POST", "knowledge.read"),
    RoutePermission(r"^/api/(v1/)?knowledge/([^/]+)$", "GET", "knowledge.read", 2),
    RoutePermission(r"^/api/(v1/)?knowledge/([^/]+)$", "PUT", "knowledge.write", 2),
    RoutePermission(r"^/api/(v1/)?knowledge/([^/]+)$", "PATCH", "knowledge.write", 2),
    RoutePermission(r"^/api/(v1/)?knowledge/([^/]+)$", "DELETE", "knowledge.delete", 2),
    RoutePermission(r"^/api/(v1/)?knowledge/([^/]+)/share$", "POST", "knowledge.share", 2),
    RoutePermission(r"^/api/(v1/)?knowledge/([^/]+)/unshare$", "POST", "knowledge.share", 2),
    RoutePermission(r"^/api/(v1/)?knowledge/upload$", "POST", "knowledge.write"),
    RoutePermission(r"^/api/(v1/)?knowledge/chat$", "POST", "knowledge.read"),
    # ── Inbox management ──
    RoutePermission(r"^/api/(v1/)?inbox$", "GET", "inbox.read"),
    RoutePermission(r"^/api/(v1/)?inbox/summary$", "GET", "inbox.read"),
    RoutePermission(r"^/api/(v1/)?inbox/unread$", "GET", "inbox.read"),
    RoutePermission(r"^/api/(v1/)?inbox/([^/]+)$", "GET", "inbox.read", 2),
    RoutePermission(r"^/api/(v1/)?inbox/([^/]+)$", "DELETE", "inbox.delete", 2),
    RoutePermission(r"^/api/(v1/)?inbox/([^/]+)/read$", "POST", "inbox.write", 2),
    RoutePermission(r"^/api/(v1/)?inbox/([^/]+)/archive$", "POST", "inbox.write", 2),
    RoutePermission(r"^/api/(v1/)?inbox/mark-all-read$", "POST", "inbox.write"),
    # ── Canvas (visual collaboration) ──
    RoutePermission(r"^/api/(v1/)?canvas$", "GET", "canvas.read"),
    RoutePermission(r"^/api/(v1/)?canvas$", "POST", "canvas.write"),
    RoutePermission(r"^/api/(v1/)?canvas/([^/]+)$", "GET", "canvas.read", 2),
    RoutePermission(r"^/api/(v1/)?canvas/([^/]+)$", "PUT", "canvas.write", 2),
    RoutePermission(r"^/api/(v1/)?canvas/([^/]+)$", "PATCH", "canvas.write", 2),
    RoutePermission(r"^/api/(v1/)?canvas/([^/]+)$", "DELETE", "canvas.delete", 2),
    RoutePermission(r"^/api/(v1/)?canvas/([^/]+)/export$", "GET", "canvas.read", 2),
    RoutePermission(r"^/api/(v1/)?canvas/([^/]+)/share$", "POST", "canvas.share", 2),
    # ── Codebase tools ──
    RoutePermission(r"^/api/(v1/)?codebase$", "GET", "codebase.read"),
    RoutePermission(r"^/api/(v1/)?codebase/search$", "GET", "codebase.read"),
    RoutePermission(r"^/api/(v1/)?codebase/search$", "POST", "codebase.read"),
    RoutePermission(r"^/api/(v1/)?codebase/analyze$", "POST", "codebase.write"),
    RoutePermission(r"^/api/(v1/)?codebase/([^/]+)$", "GET", "codebase.read", 2),
    RoutePermission(r"^/api/(v1/)?codebase/([^/]+)/issues$", "GET", "codebase.read", 2),
    RoutePermission(r"^/api/(v1/)?codebase/([^/]+)/suggestions$", "GET", "codebase.read", 2),
    # ── Nomic (self-improvement) ──
    RoutePermission(r"^/api/nomic", "*", "nomic.read"),
    RoutePermission(r"^/api/modes", "GET", "nomic.read"),
    # ── Search ──
    RoutePermission(r"^/api/search", "GET", "debates.read"),
    RoutePermission(r"^/api/search", "POST", "debates.read"),
    # ── Leaderboard / Rankings ──
    RoutePermission(r"^/api/leaderboard", "GET", "agents.read"),
    RoutePermission(r"^/api/rankings", "GET", "agents.read"),
    # ── Pulse (trending topics) ──
    RoutePermission(r"^/api/pulse", "GET", "pulse.read"),
    RoutePermission(r"^/api/pulse", "POST", "pulse.write"),
    # ── Versioned analytics ──
    RoutePermission(r"^/api/v1/analytics", "GET", "analytics.read"),
    RoutePermission(r"^/api/v1/analytics", "POST", "analytics.read"),
    # ── Consensus ──
    RoutePermission(r"^/api/consensus", "GET", "consensus.read"),
    RoutePermission(r"^/api/consensus", "POST", "consensus.create"),
    # ── Belief network / Laboratory ──
    RoutePermission(r"^/api/belief-network", "GET", "belief.read"),
    RoutePermission(r"^/api/belief-network", "POST", "belief.write"),
    RoutePermission(r"^/api/laboratory", "GET", "laboratory.read"),
    RoutePermission(r"^/api/laboratory", "POST", "laboratory.write"),
    # ── Genesis ──
    RoutePermission(r"^/api/genesis", "GET", "genesis.read"),
    RoutePermission(r"^/api/genesis", "POST", "genesis.create"),
    # ── Replays ──
    RoutePermission(r"^/api/replays", "GET", "replays.read"),
    RoutePermission(r"^/api/replays", "POST", "replays.create"),
    # ── Tournaments ──
    RoutePermission(r"^/api/tournaments", "GET", "tournaments.read"),
    RoutePermission(r"^/api/tournaments", "POST", "tournaments.create"),
    # ── Documents ──
    RoutePermission(r"^/api/documents", "GET", "documents.read"),
    RoutePermission(r"^/api/documents", "POST", "documents.write"),
    RoutePermission(r"^/api/documents", "DELETE", "documents.delete"),
    # ── Red team / Auditing ──
    RoutePermission(r"^/api/redteam", "GET", "auditing.read"),
    RoutePermission(r"^/api/redteam", "POST", "auditing.create"),
    # ── Relationships ──
    RoutePermission(r"^/api/relationship", "GET", "relationships.read"),
    RoutePermission(r"^/api/relationship", "POST", "relationships.write"),
    # ── Moments ──
    RoutePermission(r"^/api/moments", "GET", "moments.read"),
    RoutePermission(r"^/api/moments", "POST", "moments.write"),
    # ── Personas ──
    RoutePermission(r"^/api/personas", "GET", "personas.read"),
    RoutePermission(r"^/api/personas", "POST", "personas.write"),
    # ── Evolution ──
    RoutePermission(r"^/api/evolution", "GET", "evolution.read"),
    RoutePermission(r"^/api/evolution", "POST", "evolution.write"),
    # ── Plugins ──
    RoutePermission(r"^/api/(v1/)?plugins", "GET", "plugins.read"),
    RoutePermission(r"^/api/(v1/)?plugins", "POST", "plugins.install"),
    RoutePermission(r"^/api/(v1/)?plugins", "DELETE", "plugins.uninstall"),
    # ── Podcast / Audio API ──
    RoutePermission(r"^/api/podcast", "GET", "podcast.read"),
    RoutePermission(r"^/api/podcast", "POST", "podcast.create"),
    # ── Insights ──
    RoutePermission(r"^/api/insights", "GET", "insights.read"),
    # ── Learning ──
    RoutePermission(r"^/api/learning", "GET", "learning.read"),
    RoutePermission(r"^/api/learning", "POST", "learning.write"),
    # ── Gallery ──
    RoutePermission(r"^/api/gallery", "GET", "gallery.read"),
    RoutePermission(r"^/api/gallery", "POST", "gallery.write"),
    # ── Billing ──
    RoutePermission(r"^/api/(v1/)?billing", "GET", "billing.read"),
    RoutePermission(r"^/api/(v1/)?billing", "POST", "billing.write"),
    RoutePermission(r"^/api/(v1/)?billing", "PUT", "billing.write"),
    # ── Emergency break-glass access ──
    RoutePermission(r"^/api/(v1/)?admin/emergency/activate$", "POST", "admin.*"),
    RoutePermission(r"^/api/(v1/)?admin/emergency/deactivate$", "POST", "admin.*"),
    RoutePermission(r"^/api/(v1/)?admin/emergency/status$", "GET", "admin.*"),
    # ── OpenClaw Gateway ──
    # Sessions
    RoutePermission(r"^/api/gateway/openclaw/sessions$", "GET", "gateway:sessions.read"),
    RoutePermission(r"^/api/gateway/openclaw/sessions$", "POST", "gateway:sessions.create"),
    RoutePermission(r"^/api/gateway/openclaw/sessions/([^/]+)$", "GET", "gateway:sessions.read", 1),
    RoutePermission(
        r"^/api/gateway/openclaw/sessions/([^/]+)$", "DELETE", "gateway:sessions.delete", 1
    ),
    # Actions
    RoutePermission(r"^/api/gateway/openclaw/actions$", "POST", "gateway:actions.execute"),
    RoutePermission(r"^/api/gateway/openclaw/actions/([^/]+)$", "GET", "gateway:actions.read", 1),
    RoutePermission(
        r"^/api/gateway/openclaw/actions/([^/]+)/cancel$", "POST", "gateway:actions.cancel", 1
    ),
    # Credentials (use singular "credential" to match existing permissions)
    RoutePermission(r"^/api/gateway/openclaw/credentials$", "GET", "gateway.credential.read"),
    RoutePermission(r"^/api/gateway/openclaw/credentials$", "POST", "gateway.credential.create"),
    RoutePermission(
        r"^/api/gateway/openclaw/credentials/([^/]+)$", "DELETE", "gateway.credential.delete", 1
    ),
    RoutePermission(
        r"^/api/gateway/openclaw/credentials/([^/]+)/rotate$",
        "POST",
        "gateway.credential.rotate",
        1,
    ),
    # Policy rules
    RoutePermission(r"^/api/gateway/openclaw/policy/rules$", "GET", "gateway:policy.read"),
    RoutePermission(r"^/api/gateway/openclaw/policy/rules$", "POST", "gateway:policy.write"),
    RoutePermission(
        r"^/api/gateway/openclaw/policy/rules/([^/]+)$", "DELETE", "gateway:policy.write", 1
    ),
    # Approvals
    RoutePermission(r"^/api/gateway/openclaw/approvals$", "GET", "gateway:approvals.read"),
    RoutePermission(
        r"^/api/gateway/openclaw/approvals/([^/]+)/approve$", "POST", "gateway:approvals.write", 1
    ),
    RoutePermission(
        r"^/api/gateway/openclaw/approvals/([^/]+)/deny$", "POST", "gateway:approvals.write", 1
    ),
    # Health/metrics/audit (health is public, metrics/audit require auth)
    RoutePermission(r"^/api/gateway/openclaw/health$", "GET", "", allow_unauthenticated=True),
    RoutePermission(r"^/api/gateway/openclaw/metrics$", "GET", "gateway:metrics.read"),
    RoutePermission(r"^/api/gateway/openclaw/audit$", "GET", "gateway:audit.read"),
    RoutePermission(r"^/api/gateway/openclaw/stats$", "GET", "gateway:metrics.read"),
    # v1 gateway routes
    RoutePermission(r"^/api/v1/gateway/openclaw/execute$", "POST", "gateway.execute"),
    RoutePermission(r"^/api/v1/gateway/openclaw/status/([^/]+)$", "GET", "gateway.read", 1),
    RoutePermission(r"^/api/v1/gateway/openclaw/devices$", "POST", "gateway.create"),
    RoutePermission(r"^/api/v1/gateway/openclaw/devices/([^/]+)$", "DELETE", "gateway.delete", 1),
    RoutePermission(r"^/api/v1/gateway/openclaw/plugins$", "POST", "gateway.install"),
    RoutePermission(
        r"^/api/v1/gateway/openclaw/plugins/([^/]+)$", "DELETE", "gateway.uninstall", 1
    ),
    RoutePermission(r"^/api/v1/gateway/openclaw/config$", "GET", "gateway.read"),
]


class RBACMiddleware:
    """
    HTTP middleware for enforcing role-based access control.

    Integrates with the server request/response cycle to check
    permissions before handlers are invoked.
    """

    def __init__(
        self,
        config: RBACMiddlewareConfig | None = None,
        validate_permissions: bool = True,
    ) -> None:
        """
        Initialize the middleware.

        Args:
            config: Middleware configuration
            validate_permissions: If True, validate route permissions at startup
        """
        self.config = config or RBACMiddlewareConfig()
        self._checker = self.config.permission_checker or get_permission_checker()

        # Add default route permissions if none specified
        if not self.config.route_permissions:
            self.config.route_permissions = DEFAULT_ROUTE_PERMISSIONS.copy()

        # SECURITY: Validate all route permissions are defined
        if validate_permissions:
            self._validation_warnings = validate_route_permissions(self.config.route_permissions)
        else:
            self._validation_warnings = []

    def check_request(
        self,
        path: str,
        method: str,
        context: AuthorizationContext | None,
    ) -> tuple[bool, str, str | None]:
        """
        Check if a request is allowed.

        Args:
            path: Request path
            method: HTTP method
            context: Authorization context (None if unauthenticated)

        Returns:
            Tuple of (allowed, reason, permission_key)
        """
        # Bypass paths (exact match or prefix match for paths ending with /)
        if path in self.config.bypass_paths:
            return True, "Bypass path", None
        # Check prefix matches for bypass paths ending with /
        for bypass_path in self.config.bypass_paths:
            if bypass_path.endswith("/") and path.startswith(bypass_path):
                return True, "Bypass path prefix", None

        # Bypass methods
        if method.upper() in self.config.bypass_methods:
            return True, "Bypass method", None

        # Find matching route permission
        for rule in self.config.route_permissions:
            matches, resource_id = rule.matches(path, method)
            if not matches:
                continue

            # Allow unauthenticated if rule permits
            if rule.allow_unauthenticated:
                return True, "Unauthenticated access allowed", None

            # Require authentication
            if context is None:
                return False, "Authentication required", None

            # Empty permission key means authenticated access is sufficient
            if not rule.permission_key:
                return True, "Authenticated access", None

            # Check for active break-glass emergency session BEFORE normal RBAC.
            # If the authenticated user has an active emergency session, bypass
            # the permission check but log a warning for audit purposes.
            try:
                from .emergency import get_break_glass_access

                _emergency = get_break_glass_access()
                if _emergency and _emergency._active_records:
                    # First, expire stale records synchronously
                    import datetime as _dt

                    _now = _dt.datetime.now(_dt.timezone.utc)
                    _expired_ids = [
                        rid
                        for rid, rec in _emergency._active_records.items()
                        if rec.expires_at < _now
                    ]
                    for _eid in _expired_ids:
                        _erec = _emergency._active_records.pop(_eid, None)
                        if _erec:
                            from .emergency import EmergencyAccessStatus

                            _erec.status = EmergencyAccessStatus.EXPIRED
                            _erec.deactivated_at = _now
                            logger.info(
                                "BREAK-GLASS AUTO-EXPIRED: id=%s user=%s",
                                _eid,
                                _erec.user_id,
                            )

                    # Quick synchronous check: iterate active records for this user
                    user_id = getattr(context, "user_id", None)
                    if user_id:
                        record_ids = _emergency._by_user.get(user_id, [])
                        for rid in reversed(record_ids):
                            record = _emergency._active_records.get(rid)
                            if record and record.is_active:
                                logger.warning(
                                    "SECURITY AUDIT: Emergency break-glass bypass: "
                                    "user=%s permission=%s path=%s method=%s "
                                    "session_id=%s expires_at=%s",
                                    user_id,
                                    rule.permission_key,
                                    path,
                                    method,
                                    record.id,
                                    record.expires_at.isoformat(),
                                )
                                # Record the action for post-incident review
                                record.actions_taken.append(
                                    {
                                        "timestamp": _now.isoformat(),
                                        "action": "rbac_bypass",
                                        "resource_type": "http_request",
                                        "resource_id": f"{method} {path}",
                                        "details": {
                                            "permission": rule.permission_key,
                                        },
                                    }
                                )
                                return True, "Emergency break-glass access", rule.permission_key
            except ImportError:
                pass  # emergency module not available

            # Check permission
            decision = self._checker.check_permission(
                context,
                rule.permission_key,
                resource_id,
            )

            return decision.allowed, decision.reason, rule.permission_key

        # No matching rule - default deny
        # SECURITY: Unmatched routes are denied by default to prevent
        # unauthorized access to endpoints not explicitly listed in the
        # route permission rules. This is a fail-closed policy.
        if context is None:
            return False, "Authentication required", None

        logger.warning(
            "RBAC default-deny: no permission rule matched for %s %s "
            "(authenticated user denied access)",
            method,
            path,
        )
        return False, "Access denied: no permission rule matched (default-deny policy)", None

    def add_route_permission(self, rule: RoutePermission) -> None:
        """Add a route permission rule."""
        self.config.route_permissions.append(rule)

    def remove_route_permission(self, pattern: str, method: str) -> None:
        """Remove a route permission rule by pattern and method."""
        self.config.route_permissions = [
            r
            for r in self.config.route_permissions
            if not (
                isinstance(r.pattern, Pattern)
                and r.pattern.pattern == pattern
                and r.method == method
            )
        ]

    def get_required_permission(self, path: str, method: str) -> str | None:
        """Get the required permission for a route."""
        for rule in self.config.route_permissions:
            matches, _ = rule.matches(path, method)
            if matches:
                return rule.permission_key
        return None


def create_permission_handler(
    permission_key: str,
    resource_id_extractor: Callable[[Any], str | None] | None = None,
) -> Callable[[Any, AuthorizationContext], tuple[bool, str]]:
    """
    Create a permission check handler for custom integrations.

    Args:
        permission_key: Permission to check
        resource_id_extractor: Optional function to extract resource ID from request

    Returns:
        Handler function that takes (request, context) and returns (allowed, reason)
    """

    def handler(request: Any, context: AuthorizationContext) -> tuple[bool, str]:
        resource_id = None
        if resource_id_extractor:
            resource_id = resource_id_extractor(request)

        checker = get_permission_checker()
        decision = checker.check_permission(context, permission_key, resource_id)

        return decision.allowed, decision.reason

    return handler


# Global middleware instance
_middleware: RBACMiddleware | None = None


def get_middleware() -> RBACMiddleware:
    """Get or create the global middleware instance."""
    global _middleware
    if _middleware is None:
        _middleware = RBACMiddleware()
    return _middleware


def set_middleware(middleware: RBACMiddleware) -> None:
    """Set the global middleware instance."""
    global _middleware
    _middleware = middleware


def check_route_access(
    path: str,
    method: str,
    context: AuthorizationContext | None,
) -> tuple[bool, str]:
    """Convenience function to check route access using global middleware."""
    allowed, reason, _ = get_middleware().check_request(path, method, context)
    return allowed, reason
