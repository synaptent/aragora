"""
Workspace Handler - Enterprise Privacy and Data Isolation APIs.

Stability: STABLE

Provides API endpoints for:
- Workspace creation and management
- Data isolation and access control
- Retention policy management
- Sensitivity classification
- Privacy audit logging

Endpoints:
- POST /api/workspaces - Create a new workspace
- GET /api/workspaces - List workspaces
- GET /api/workspaces/{id} - Get workspace details
- DELETE /api/workspaces/{id} - Delete workspace
- POST /api/workspaces/{id}/members - Add member to workspace
- DELETE /api/workspaces/{id}/members/{user_id} - Remove member
- GET /api/retention/policies - List retention policies
- POST /api/retention/policies - Create retention policy
- PUT /api/retention/policies/{id} - Update retention policy
- DELETE /api/retention/policies/{id} - Delete retention policy
- POST /api/retention/policies/{id}/execute - Execute retention policy
- GET /api/retention/expiring - Get items expiring soon
- POST /api/classify - Classify content sensitivity
- GET /api/classify/policy/{level} - Get policy for sensitivity level
- GET /api/audit/entries - Query audit entries
- GET /api/audit/report - Generate compliance report
- GET /api/audit/verify - Verify audit log integrity

Features:
- Circuit breaker pattern for resilient subsystem access
- Rate limiting on mutation endpoints
- RBAC permission enforcement via @require_permission decorators
- Comprehensive input validation
- Tenant isolation with cross-tenant access prevention
- Full audit logging for compliance (SOC 2)

SOC 2 Controls: CC6.1, CC6.3 - Logical access controls

Handler method implementations are decomposed into mixin modules:
- workspace/crud.py      - Workspace CRUD operations
- workspace/policies.py  - Retention policy management
- workspace/members.py   - Member management and RBAC profiles
- workspace/settings.py  - Classification and audit endpoints
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, TypeVar

from aragora.server.http_utils import run_async
from aragora.server.validation.entities import validate_path_segment
from aragora.utils.cache import TTLCache

from aragora.billing.auth.context import UserAuthContext
from aragora.billing.jwt_auth import extract_user_from_request
from aragora.protocols import HTTPRequestHandler

# RBAC imports - graceful fallback if not available
AuthorizationContext: Any = None
check_permission: Any = None
try:
    from aragora.rbac import AuthorizationContext as _AuthorizationContext
    from aragora.rbac import check_permission as _check_permission

    AuthorizationContext = _AuthorizationContext
    check_permission = _check_permission
    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False
from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed
from aragora.privacy import (
    AccessDeniedException,  # noqa: F401 - used by mixin modules via _mod()
    AuditAction,  # noqa: F401 - used by mixin modules via _mod()
    AuditOutcome,  # noqa: F401 - used by mixin modules via _mod()
    ClassificationConfig,
    DataIsolationManager,
    IsolationConfig,
    PrivacyAuditLog,
    RetentionAction,  # noqa: F401 - used by mixin modules via _mod()
    RetentionPolicyManager,
    SensitivityClassifier,
    SensitivityLevel,  # noqa: F401 - used by mixin modules via _mod()
    WorkspacePermission,  # noqa: F401 - used by mixin modules via _mod()
)
from aragora.privacy.audit_log import Actor, Resource  # noqa: F401 - used by mixin modules via _mod()
from aragora.server.validation.query_params import safe_query_int  # noqa: F401 - used by mixin modules via _mod()

# RBAC profile imports for workspace role management
RBACProfile: Any = None
try:
    from aragora.rbac.profiles import (
        RBACProfile as _RBACProfile,
    )
    from aragora.rbac.profiles import (
        get_available_roles_for_assignment,  # noqa: F401
        get_lite_role_summary,  # noqa: F401
        get_profile_config,  # noqa: F401
        get_profile_roles,  # noqa: F401
    )

    RBACProfile = _RBACProfile
    PROFILES_AVAILABLE = True
except ImportError:
    PROFILES_AVAILABLE = False

from aragora.rbac.decorators import require_permission

# =============================================================================
# RBAC Permission Constants for Workspace Module
# =============================================================================
# These constants define all permission keys used in this module.
# Permissions follow the pattern: resource:action
#
# Workspace permissions:
PERM_WORKSPACE_READ = "workspace:read"
PERM_WORKSPACE_WRITE = "workspace:write"
PERM_WORKSPACE_DELETE = "workspace:delete"
PERM_WORKSPACE_ADMIN = "workspace:admin"
PERM_WORKSPACE_SHARE = "workspace:share"
PERM_WORKSPACE_EXPORT = "workspace:export"

# Retention policy permissions:
PERM_RETENTION_READ = "retention:read"
PERM_RETENTION_WRITE = "retention:write"
PERM_RETENTION_DELETE = "retention:delete"
PERM_RETENTION_EXECUTE = "retention:execute"

# Classification permissions:
PERM_CLASSIFY_READ = "classify:read"
PERM_CLASSIFY_WRITE = "classify:write"

# Audit permissions:
PERM_AUDIT_READ = "audit:read"
PERM_AUDIT_REPORT = "audit:report"
PERM_AUDIT_VERIFY = "audit:verify"

from ..base import (
    HandlerResult,
    ServerContext,
    error_response,
    handle_errors,  # noqa: F401 - used by mixin modules via _mod()
    json_response,  # noqa: F401 - used by mixin modules via _mod()
    log_request,  # noqa: F401 - used by mixin modules via _mod()
)
from aragora.server.handlers.openapi_decorator import api_endpoint  # noqa: F401 - used by mixin modules via _mod()
from aragora.server.versioning.compat import strip_version_prefix
from ..secure import SecureHandler
from ..utils.rate_limit import rate_limit  # noqa: F401 - used by mixin modules via _mod()

# Import utilities from the workspace package
from .workspace_utils import (
    WorkspaceCircuitBreaker,
    get_workspace_circuit_breaker_status,
    _validate_workspace_id,
    _validate_policy_id,
    _validate_user_id,
)

# Import mixin classes providing handler method implementations
from .crud import WorkspaceCrudMixin
from .policies import WorkspacePoliciesMixin
from .members import WorkspaceMembersMixin
from .invites import WorkspaceInvitesMixin
from .settings import WorkspaceSettingsMixin

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# TypeVar for generic coroutine return type
T = TypeVar("T")

# =============================================================================
# Caching Infrastructure
# =============================================================================

# Cache TTL constants (in seconds)
CACHE_TTL_RETENTION_POLICY = 300.0  # 5 minutes for retention policy queries
CACHE_TTL_PERMISSION_CHECK = 60.0  # 1 minute for permission matrix lookups
CACHE_TTL_AUDIT_QUERY = 120.0  # 2 minutes for audit log queries

# Cache instances with appropriate sizes
_retention_policy_cache: TTLCache[Any] = TTLCache(
    maxsize=256, ttl_seconds=CACHE_TTL_RETENTION_POLICY
)
_permission_cache: TTLCache[Any] = TTLCache(maxsize=512, ttl_seconds=CACHE_TTL_PERMISSION_CHECK)
_audit_query_cache: TTLCache[Any] = TTLCache(maxsize=256, ttl_seconds=CACHE_TTL_AUDIT_QUERY)

# Lock for thread-safe cache invalidation
_cache_lock = threading.Lock()


def _invalidate_retention_cache(policy_id: str | None = None) -> int:
    """Invalidate retention policy cache entries.

    Args:
        policy_id: If provided, only invalidate entries for this policy.
                  If None, clear all retention cache entries.

    Returns:
        Number of entries invalidated.
    """
    with _cache_lock:
        if policy_id:
            return _retention_policy_cache.clear_prefix(f"retention:{policy_id}")
        return _retention_policy_cache.clear()


def _invalidate_permission_cache(
    user_id: str | None = None, workspace_id: str | None = None
) -> int:
    """Invalidate permission cache entries.

    Args:
        user_id: If provided, invalidate entries for this user.
        workspace_id: If provided, invalidate entries for this workspace.
        If both None, clear all permission cache entries.

    Returns:
        Number of entries invalidated.
    """
    with _cache_lock:
        total = 0
        if user_id:
            total += _permission_cache.clear_prefix(f"perm:user:{user_id}")
        if workspace_id:
            total += _permission_cache.clear_prefix(f"perm:ws:{workspace_id}")
        if not user_id and not workspace_id:
            total = _permission_cache.clear()
        return total


def _invalidate_audit_cache(workspace_id: str | None = None) -> int:
    """Invalidate audit query cache entries.

    Args:
        workspace_id: If provided, invalidate entries for this workspace.
                     If None, clear all audit cache entries.

    Returns:
        Number of entries invalidated.
    """
    with _cache_lock:
        if workspace_id:
            return _audit_query_cache.clear_prefix(f"audit:ws:{workspace_id}")
        return _audit_query_cache.clear()


def get_workspace_cache_stats() -> dict[str, Any]:
    """Get cache statistics for monitoring."""
    return {
        "retention_policy_cache": _retention_policy_cache.stats,
        "permission_cache": _permission_cache.stats,
        "audit_query_cache": _audit_query_cache.stats,
    }


class WorkspaceHandler(
    WorkspaceCrudMixin,
    WorkspacePoliciesMixin,
    WorkspaceMembersMixin,
    WorkspaceInvitesMixin,
    WorkspaceSettingsMixin,
    SecureHandler,
):
    """Handler for workspace and privacy management endpoints.

    Extends SecureHandler for JWT-based authentication, RBAC permission
    enforcement, and security audit logging.

    Handler method implementations are provided by mixin classes:
    - WorkspaceCrudMixin: create, list, get, delete workspace
    - WorkspacePoliciesMixin: retention policy CRUD, execute, expiring
    - WorkspaceMembersMixin: add/remove members, roles, profiles
    - WorkspaceSettingsMixin: classification, audit queries/reports

    Production-ready features:
    - Circuit breaker pattern for resilient subsystem access
    - Rate limiting on mutation endpoints
    - RBAC permission enforcement
    - Comprehensive input validation
    - Tenant isolation
    """

    RESOURCE_TYPE = "workspace"

    ROUTES = [
        "/api/v1/workspaces",
        "/api/v1/workspaces/profiles",  # RBAC profile endpoints
        "/api/v1/invites",  # Invite acceptance endpoint
        "/api/v1/retention/policies",
        "/api/v1/retention/expiring",
        "/api/v1/classify",
        "/api/v1/audit/entries",
        "/api/v1/audit/report",
        "/api/v1/audit/verify",
        "/api/v1/audit/actor",
        "/api/v1/audit/resource",
        "/api/v1/audit/denied",
    ]

    def __init__(self, server_context: ServerContext) -> None:
        super().__init__(server_context)
        self._isolation_manager: DataIsolationManager | None = None
        self._retention_manager: RetentionPolicyManager | None = None
        self._classifier: SensitivityClassifier | None = None
        self._audit_log: PrivacyAuditLog | None = None

    def _get_isolation_manager(self) -> DataIsolationManager:
        """Get or create isolation manager."""
        if self._isolation_manager is None:
            self._isolation_manager = DataIsolationManager(IsolationConfig())
        return self._isolation_manager

    def _get_retention_manager(self) -> RetentionPolicyManager:
        """Get or create retention manager."""
        if self._retention_manager is None:
            self._retention_manager = RetentionPolicyManager()
        return self._retention_manager

    def _get_classifier(self) -> SensitivityClassifier:
        """Get or create sensitivity classifier."""
        if self._classifier is None:
            self._classifier = SensitivityClassifier(ClassificationConfig())
        return self._classifier

    def _get_audit_log(self) -> PrivacyAuditLog:
        """Get or create audit log."""
        if self._audit_log is None:
            self._audit_log = PrivacyAuditLog()
        return self._audit_log

    def _run_async(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run an async coroutine from sync context.

        Delegates to the centralized run_async utility which handles
        event loop management and nested loop edge cases.
        """
        return run_async(coro)

    def _get_user_store(self) -> Any:
        """Get user store from context."""
        return self.ctx.get("user_store")

    def _get_auth_context(
        self, handler: HTTPRequestHandler, auth_ctx: UserAuthContext | None = None
    ) -> AuthorizationContext | None:
        """Build RBAC authorization context from request."""
        if not RBAC_AVAILABLE or AuthorizationContext is None:
            return None

        if auth_ctx is None:
            user_store = self._get_user_store()
            auth_ctx = extract_user_from_request(handler, user_store)

        if not auth_ctx.is_authenticated:
            return None

        # Get user role from user store if available
        user_store = self._get_user_store()
        user = user_store.get_user_by_id(auth_ctx.user_id) if user_store else None
        roles = set([user.role]) if user and user.role else set()

        return AuthorizationContext(
            user_id=auth_ctx.user_id,
            roles=roles,
            org_id=auth_ctx.org_id,
        )

    def _check_rbac_permission(
        self,
        handler: HTTPRequestHandler,
        permission_key: str,
        auth_ctx: UserAuthContext | None = None,
    ) -> HandlerResult | None:
        """
        Check RBAC permission with caching (1 min TTL).

        Caches permission decisions to avoid repeated lookups for the same
        user/permission combination within a short time window.

        Returns None if allowed, or an error response if denied.
        """
        if not RBAC_AVAILABLE:
            if rbac_fail_closed():
                return error_response("Service unavailable: access control module not loaded", 503)
            return None

        rbac_ctx = self._get_auth_context(handler, auth_ctx)
        if not rbac_ctx:
            # No auth context - rely on existing auth checks
            return None

        # Check permission cache first
        cache_key = f"perm:user:{rbac_ctx.user_id}:{permission_key}"
        cached_decision = _permission_cache.get(cache_key)
        if cached_decision is not None:
            logger.debug("Permission cache hit: %s", cache_key)
            allowed, reason = cached_decision
            if not allowed:
                logger.warning("Permission denied: %s", reason)
                return error_response("Permission denied", 403)
            return None

        decision = check_permission(rbac_ctx, permission_key)

        # Cache the decision
        _permission_cache.set(cache_key, (decision.allowed, decision.reason))
        logger.debug("Cached permission decision: %s -> %s", cache_key, decision.allowed)

        if not decision.allowed:
            logger.warning(
                "RBAC denied: user=%s permission=%s reason=%s",
                rbac_ctx.user_id,
                permission_key,
                decision.reason,
            )
            return error_response(
                "Permission denied",
                403,
            )

        return None

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        return any(normalized.startswith(strip_version_prefix(route)) for route in self.ROUTES)

    @require_permission("workspace:read")
    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: HTTPRequestHandler,
        method: str = "GET",
    ) -> HandlerResult | None:
        """Route GET requests."""
        if hasattr(handler, "command"):
            method = handler.command

        # Workspace endpoints
        if path.startswith("/api/v1/workspaces"):
            return self._route_workspace(path, query_params, handler, method)

        # Invite acceptance endpoint
        if path.startswith("/api/v1/invites"):
            return self._route_invites(path, query_params, handler, method)

        # Retention endpoints
        if path.startswith("/api/v1/retention"):
            return self._route_retention(path, query_params, handler, method)

        # Classification endpoints
        if path.startswith("/api/v1/classify"):
            return self._route_classify(path, query_params, handler, method)

        # Audit endpoints
        if path.startswith("/api/v1/audit"):
            return self._route_audit(path, query_params, handler, method)

        return None

    @handle_errors("workspace creation")
    @require_permission("workspace:write")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: HTTPRequestHandler
    ) -> HandlerResult | None:
        """Route POST requests."""
        return self.handle(path, query_params, handler, method="POST")

    @handle_errors("workspace deletion")
    @require_permission("workspace:delete")
    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: HTTPRequestHandler
    ) -> HandlerResult | None:
        """Route DELETE requests."""
        return self.handle(path, query_params, handler, method="DELETE")

    @handle_errors("workspace update")
    @require_permission("workspace:write")
    def handle_put(
        self, path: str, query_params: dict[str, Any], handler: HTTPRequestHandler
    ) -> HandlerResult | None:
        """Route PUT requests."""
        return self.handle(path, query_params, handler, method="PUT")

    # =========================================================================
    # Routing Methods
    # =========================================================================

    def _route_workspace(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: HTTPRequestHandler,
        method: str,
    ) -> HandlerResult | None:
        """Route workspace requests."""
        normalized = strip_version_prefix(path)
        parts = normalized.strip("/").split("/")

        # POST /api/workspaces - Create workspace
        if normalized in ("/api/workspaces", "/api/v1/workspaces") and method == "POST":
            return self._handle_create_workspace(handler)

        # GET /api/workspaces - List workspaces
        if normalized in ("/api/workspaces", "/api/v1/workspaces") and method == "GET":
            return self._handle_list_workspaces(handler, query_params)

        # GET /api/workspaces/profiles - List available RBAC profiles
        # NOTE: Must be checked BEFORE the generic GET /api/workspaces/{id} route
        # to avoid treating "profiles" as a workspace ID.
        if (
            normalized in ("/api/workspaces/profiles", "/api/v1/workspaces/profiles")
            and method == "GET"
        ):
            return self._handle_list_profiles(handler)

        # GET /api/workspaces/{id}
        if len(parts) == 3 and method == "GET":
            workspace_id = parts[2]
            valid, err = _validate_workspace_id(workspace_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_get_workspace(handler, workspace_id)

        # DELETE /api/workspaces/{id}
        if len(parts) == 3 and method == "DELETE":
            workspace_id = parts[2]
            valid, err = _validate_workspace_id(workspace_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_delete_workspace(handler, workspace_id)

        # POST /api/workspaces/{id}/members - Add member
        if len(parts) == 4 and parts[3] == "members" and method == "POST":
            workspace_id = parts[2]
            valid, err = _validate_workspace_id(workspace_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_add_member(handler, workspace_id)

        # DELETE /api/workspaces/{id}/members/{user_id} - Remove member
        if len(parts) == 5 and parts[3] == "members" and method == "DELETE":
            workspace_id = parts[2]
            user_id = parts[4]
            valid, err = _validate_workspace_id(workspace_id)
            if not valid:
                return error_response(err, 400)
            valid, err = _validate_user_id(user_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_remove_member(handler, workspace_id, user_id)

        # GET /api/workspaces/{id}/roles - Get available roles for workspace
        if len(parts) == 4 and parts[3] == "roles" and method == "GET":
            workspace_id = parts[2]
            valid, err = _validate_workspace_id(workspace_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_get_workspace_roles(handler, workspace_id)

        # PUT /api/workspaces/{id}/members/{user_id}/role - Update member role
        if len(parts) == 6 and parts[3] == "members" and parts[5] == "role" and method == "PUT":
            workspace_id = parts[2]
            user_id = parts[4]
            valid, err = _validate_workspace_id(workspace_id)
            if not valid:
                return error_response(err, 400)
            valid, err = _validate_user_id(user_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_update_member_role(handler, workspace_id, user_id)

        # POST /api/workspaces/{id}/invites - Create invite
        if len(parts) == 4 and parts[3] == "invites" and method == "POST":
            workspace_id = parts[2]
            valid, err = _validate_workspace_id(workspace_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_create_invite(handler, workspace_id)

        # GET /api/workspaces/{id}/invites - List invites
        if len(parts) == 4 and parts[3] == "invites" and method == "GET":
            workspace_id = parts[2]
            valid, err = _validate_workspace_id(workspace_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_list_invites(handler, workspace_id)

        # DELETE /api/workspaces/{id}/invites/{invite_id} - Cancel invite
        if len(parts) == 5 and parts[3] == "invites" and method == "DELETE":
            workspace_id = parts[2]
            invite_id = parts[4]
            valid, err = _validate_workspace_id(workspace_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_cancel_invite(handler, workspace_id, invite_id)

        # POST /api/workspaces/{id}/invites/{invite_id}/resend - Resend invite
        if len(parts) == 6 and parts[3] == "invites" and parts[5] == "resend" and method == "POST":
            workspace_id = parts[2]
            invite_id = parts[4]
            valid, err = _validate_workspace_id(workspace_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_resend_invite(handler, workspace_id, invite_id)

        return error_response("Not found", 404)

    def _route_invites(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: HTTPRequestHandler,
        method: str,
    ) -> HandlerResult | None:
        """Route invite acceptance requests."""
        normalized = strip_version_prefix(path)
        parts = normalized.strip("/").split("/")

        # POST /api/v1/invites/{token}/accept - Accept invite
        if len(parts) == 4 and parts[3] == "accept" and method == "POST":
            token = parts[2]
            return self._handle_accept_invite(handler, token)

        return error_response("Not found", 404)

    def _route_retention(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: HTTPRequestHandler,
        method: str,
    ) -> HandlerResult | None:
        """Route retention requests."""
        normalized = strip_version_prefix(path)
        parts = normalized.strip("/").split("/")

        # GET /api/retention/policies - List policies
        if (
            normalized in ("/api/retention/policies", "/api/v1/retention/policies")
            and method == "GET"
        ):
            return self._handle_list_policies(handler, query_params)

        # POST /api/retention/policies - Create policy
        if (
            normalized in ("/api/retention/policies", "/api/v1/retention/policies")
            and method == "POST"
        ):
            return self._handle_create_policy(handler)

        # GET /api/retention/policies/{id}
        if len(parts) == 4 and parts[2] == "policies" and method == "GET":
            policy_id = parts[3]
            valid, err = _validate_policy_id(policy_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_get_policy(handler, policy_id)

        # PUT /api/retention/policies/{id}
        if len(parts) == 4 and parts[2] == "policies" and method == "PUT":
            policy_id = parts[3]
            valid, err = _validate_policy_id(policy_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_update_policy(handler, policy_id)

        # DELETE /api/retention/policies/{id}
        if len(parts) == 4 and parts[2] == "policies" and method == "DELETE":
            policy_id = parts[3]
            valid, err = _validate_policy_id(policy_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_delete_policy(handler, policy_id)

        # POST /api/retention/policies/{id}/execute
        if len(parts) == 5 and parts[4] == "execute" and method == "POST":
            policy_id = parts[3]
            valid, err = _validate_policy_id(policy_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_execute_policy(handler, policy_id, query_params)

        # GET /api/retention/expiring
        if (
            normalized in ("/api/retention/expiring", "/api/v1/retention/expiring")
            and method == "GET"
        ):
            return self._handle_expiring_items(handler, query_params)

        return error_response("Not found", 404)

    def _route_classify(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: HTTPRequestHandler,
        method: str,
    ) -> HandlerResult | None:
        """Route classification requests."""
        path = strip_version_prefix(path)
        parts = path.strip("/").split("/")

        # POST /api/classify - Classify content
        if path == "/api/classify" and method == "POST":
            return self._handle_classify_content(handler)

        # GET /api/classify/policy/{level}
        if len(parts) == 4 and parts[2] == "policy" and method == "GET":
            level = parts[3]
            return self._handle_get_level_policy(handler, level)

        return error_response("Not found", 404)

    def _route_audit(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: HTTPRequestHandler,
        method: str,
    ) -> HandlerResult | None:
        """Route audit requests."""
        normalized = strip_version_prefix(path)
        parts = normalized.strip("/").split("/")

        # GET /api/audit/entries - Query audit entries
        if path == "/api/v1/audit/entries" and method == "GET":
            return self._handle_query_audit(handler, query_params)

        # GET /api/audit/report - Generate compliance report
        if path == "/api/v1/audit/report" and method == "GET":
            return self._handle_audit_report(handler, query_params)

        # GET /api/audit/verify - Verify integrity
        if path == "/api/v1/audit/verify" and method == "GET":
            return self._handle_verify_integrity(handler, query_params)

        # GET /api/audit/actor/{id}/history
        if len(parts) >= 4 and parts[2] == "actor" and method == "GET":
            actor_id = parts[3]
            valid, err = _validate_user_id(actor_id)
            if not valid:
                return error_response(err, 400)
            return self._handle_actor_history(handler, actor_id, query_params)

        # GET /api/audit/resource/{id}/history
        if len(parts) >= 4 and parts[2] == "resource" and method == "GET":
            resource_id = parts[3]
            is_valid, err = validate_path_segment(resource_id, "resource_id")
            if not is_valid:
                return error_response(err or f"Invalid resource_id format: {resource_id}", 400)
            return self._handle_resource_history(handler, resource_id, query_params)

        # GET /api/audit/denied - Get denied access attempts
        if path == "/api/v1/audit/denied" and method == "GET":
            return self._handle_denied_access(handler, query_params)

        return error_response("Not found", 404)


__all__ = [
    "WorkspaceHandler",
    "WorkspaceCircuitBreaker",
    "get_workspace_circuit_breaker_status",
    "get_workspace_cache_stats",
]
