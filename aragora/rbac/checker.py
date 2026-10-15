"""
RBAC Permission Checker - Evaluates access control decisions.

Provides the core logic for checking if a user has permission to perform
an action on a resource, with support for caching and audit logging.

Supports both in-memory and distributed (Redis-backed) caching for
horizontal scaling in multi-instance deployments.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from .conditions import ConditionResult, get_condition_evaluator
from .defaults import get_role_permissions
from .models import (
    Action,
    AuthorizationContext,
    AuthorizationDecision,
    ResourceType,
    RoleAssignment,
    _permission_candidates,
)

if TYPE_CHECKING:
    from .audit import AuthorizationAuditor
    from .cache import RBACDistributedCache
    from .conditions import ConditionEvaluator
    from .delegation import DelegationManager
    from .resource_permissions import ResourcePermissionStore

logger = logging.getLogger(__name__)


def _build_condition_context(
    context: AuthorizationContext,
    resource_attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build condition context from authorization context and resource attributes.

    Args:
        context: Authorization context with user info
        resource_attrs: Optional resource attributes

    Returns:
        Combined context dict for condition evaluation
    """
    condition_ctx: dict[str, Any] = {
        "user_id": context.user_id,
        "actor_id": context.user_id,  # Alias for ResourceOwnerCondition
        "org_id": context.org_id,
        "current_time": context.timestamp or datetime.now(timezone.utc),
    }

    # Add IP if available
    if context.ip_address:
        condition_ctx["ip_address"] = context.ip_address

    # Add resource attributes with condition-friendly aliases
    if resource_attrs:
        attrs = dict(resource_attrs)
        # Map owner_id to resource_owner for ResourceOwnerCondition
        if "owner_id" in attrs and "resource_owner" not in attrs:
            attrs["resource_owner"] = attrs["owner_id"]
        # Map status to resource_status for ResourceStatusCondition
        if "status" in attrs and "resource_status" not in attrs:
            attrs["resource_status"] = attrs["status"]
        # Map tags to resource_tags for TagCondition
        if "tags" in attrs and "resource_tags" not in attrs:
            attrs["resource_tags"] = attrs["tags"]
        condition_ctx.update(attrs)

    return condition_ctx


class PermissionChecker:
    """
    Core permission checking service.

    Evaluates whether a user has permission to perform actions on resources,
    with support for:
    - Role-based permissions
    - Permission inheritance
    - Resource-level access control
    - API key scopes
    - Caching for performance
    - Audit logging
    """

    def __init__(
        self,
        auditor: AuthorizationAuditor | None = None,
        cache_ttl: int = 300,
        enable_cache: bool = True,
        cache_backend: RBACDistributedCache | None = None,
        resource_permission_store: ResourcePermissionStore | None = None,
        delegation_manager: DelegationManager | None = None,
        enable_delegation: bool = True,
        enable_workspace_scope: bool = True,
        enable_conditions: bool = True,
        condition_evaluator: ConditionEvaluator | None = None,
        enable_ownership: bool = True,
    ) -> None:
        """
        Initialize the permission checker.

        Args:
            auditor: Optional auditor for logging authorization decisions
            cache_ttl: Cache TTL in seconds (default 5 minutes)
            enable_cache: Whether to enable decision caching
            cache_backend: Optional distributed cache backend (Redis-backed).
                          If provided, uses distributed cache instead of local dict.
            resource_permission_store: Optional store for resource-level permissions.
                          If provided, checks resource-level permissions before role-based.
            delegation_manager: Optional manager for permission delegations.
                          If provided, checks delegated permissions.
            enable_delegation: Whether to check delegated permissions (default True)
            enable_workspace_scope: Whether to enforce workspace-level scoping (default True)
            enable_conditions: Whether to evaluate ABAC conditions on permissions (default True)
            condition_evaluator: Optional custom condition evaluator. If not provided,
                          uses the global condition evaluator singleton.
        """
        self._auditor = auditor
        self._cache_ttl = cache_ttl
        self._enable_cache = enable_cache
        self._cache_backend = cache_backend
        self._resource_permission_store = resource_permission_store
        self._delegation_manager = delegation_manager
        self._enable_delegation = enable_delegation
        self._enable_workspace_scope = enable_workspace_scope
        self._enable_conditions = enable_conditions
        self._condition_evaluator = condition_evaluator
        self._enable_ownership = enable_ownership
        self._ownership_manager: Any = None

        # Local cache (used when no distributed backend, or as L1)
        self._decision_cache: dict[str, tuple[AuthorizationDecision, datetime]] = {}
        self._role_assignments: dict[str, list[RoleAssignment]] = {}
        self._custom_roles: dict[str, dict[str, Any]] = {}
        self._resource_policies: dict[str, Callable[..., bool]] = {}

        # Cache for resource permission checks
        self._resource_permission_cache: dict[str, tuple[AuthorizationDecision, datetime]] = {}

        # Workspace-scoped role assignments (workspace_id -> user_id -> roles)
        self._workspace_roles: dict[str, dict[str, set[str]]] = {}

        # Cache versioning for O(1) invalidation (instead of iterating all keys)
        # When clearing cache for a user, we increment their version instead of
        # iterating all keys. The version is embedded in cache keys, so old entries
        # automatically become stale and won't match on lookup.
        self._global_cache_version: int = 0
        self._user_cache_versions: dict[str, int] = {}
        # Resource permission cache also uses versioning
        self._global_resource_cache_version: int = 0
        self._user_resource_cache_versions: dict[str, int] = {}

        # Lock for thread-safe cache version operations (prevents race conditions
        # between version read and use)
        self._cache_version_lock = threading.Lock()

        # If distributed cache provided, register for invalidation callbacks
        if self._cache_backend:
            self._cache_backend.add_invalidation_callback(self._on_remote_invalidation)

    def _get_cache_version(self, user_id: str) -> str:
        """Get the cache version string for a user (combines global and user version).

        Thread-safe: Uses lock to prevent race condition between version read and use.
        """
        with self._cache_version_lock:
            global_v = self._global_cache_version
            user_v = self._user_cache_versions.get(user_id, 0)
        return f"v{global_v}.{user_v}"

    def _get_resource_cache_version(self, user_id: str) -> str:
        """Get the resource cache version string for a user.

        Thread-safe: Uses lock to prevent race condition between version read and use.
        """
        with self._cache_version_lock:
            global_v = self._global_resource_cache_version
            user_v = self._user_resource_cache_versions.get(user_id, 0)
        return f"v{global_v}.{user_v}"

    def _get_condition_evaluator(self) -> ConditionEvaluator:
        """Get the condition evaluator (custom or global singleton)."""
        if self._condition_evaluator is not None:
            return self._condition_evaluator
        return get_condition_evaluator()

    def _evaluate_conditions(
        self,
        conditions: dict[str, Any],
        context: AuthorizationContext,
        resource_attrs: dict[str, Any] | None = None,
    ) -> tuple[bool, list[ConditionResult]]:
        """Evaluate ABAC conditions against context.

        Args:
            conditions: Condition definitions from permission/role assignment
            context: Authorization context
            resource_attrs: Optional resource attributes

        Returns:
            Tuple of (all_satisfied, list_of_results)
        """
        if not self._enable_conditions or not conditions:
            return True, []

        evaluator = self._get_condition_evaluator()
        condition_ctx = _build_condition_context(context, resource_attrs)

        return evaluator.evaluate(conditions, condition_ctx)

    def check_permission(
        self,
        context: AuthorizationContext,
        permission_key: str,
        resource_id: str | None = None,
    ) -> AuthorizationDecision:
        """
        Check if the context has a specific permission.

        Args:
            context: Authorization context (user, roles, etc.)
            permission_key: Permission to check (e.g., "debates.create")
                           Also accepts colon format (e.g., "debates:create")
            resource_id: Optional specific resource ID

        Returns:
            AuthorizationDecision with result and reason
        """
        # Normalize permission key format: accept both "resource:action" and "resource.action"
        # Standard format is "resource.action" (dot notation)
        if ":" in permission_key and "." not in permission_key:
            permission_key = permission_key.replace(":", ".")

        # Check cache first (distributed or local)
        if self._enable_cache:
            cached = self._get_cached_decision(context, permission_key, resource_id)
            if cached:
                return cached

        # Resolve permissions if not already done
        if not context.permissions:
            context = self._resolve_permissions(context)

        # Check permission
        decision = self._evaluate_permission(context, permission_key, resource_id)

        # Cache the decision (distributed or local)
        if self._enable_cache:
            self._cache_decision(context, permission_key, resource_id, decision)

        # Audit log
        if self._auditor:
            self._auditor.log_decision(decision)

        return decision

    def check_resource_access(
        self,
        context: AuthorizationContext,
        resource_type: ResourceType,
        action: Action,
        resource_id: str,
        resource_attrs: dict[str, Any] | None = None,
        permission_conditions: dict[str, Any] | None = None,
    ) -> AuthorizationDecision:
        """
        Check if context can perform an action on a specific resource.

        This method supports attribute-based access control (ABAC) by
        allowing resource policies and conditions to be evaluated.

        Args:
            context: Authorization context
            resource_type: Type of resource
            action: Action to perform
            resource_id: Specific resource ID
            resource_attrs: Optional resource attributes for ABAC conditions.
                          Used to evaluate conditions like owner, status, tags.
            permission_conditions: Optional explicit conditions to evaluate.
                          If not provided, uses conditions from the permission.

        Returns:
            AuthorizationDecision
        """
        permission_key = f"{resource_type.value}.{action.value}"

        # First check base permission
        decision = self.check_permission(context, permission_key, resource_id)
        if not decision.allowed:
            return decision

        # Check ABAC conditions if provided or if resource has attributes
        if self._enable_conditions and (permission_conditions or resource_attrs):
            conditions_to_check = permission_conditions or {}

            # Add implicit owner check if owner_id in resource_attrs
            if (
                resource_attrs
                and "owner_id" in resource_attrs
                and "owner" not in conditions_to_check
            ):
                conditions_to_check = {**conditions_to_check, "owner": True}

            if conditions_to_check:
                satisfied, results = self._evaluate_conditions(
                    conditions_to_check,
                    context,
                    resource_attrs,
                )
                if not satisfied:
                    failed_conditions = [r for r in results if not r.satisfied]
                    reasons = [f"{r.condition_name}: {r.reason}" for r in failed_conditions]
                    return AuthorizationDecision(
                        allowed=False,
                        reason=f"ABAC conditions not satisfied: {'; '.join(reasons)}",
                        permission_key=permission_key,
                        resource_id=resource_id,
                        context=context,
                    )

        # Check resource-specific policies
        policy_key = f"{resource_type.value}:{resource_id}"
        if policy_key in self._resource_policies:
            policy = self._resource_policies[policy_key]
            if not policy(context, action, resource_attrs or {}):
                return AuthorizationDecision(
                    allowed=False,
                    reason=f"Resource policy denied access to {resource_id}",
                    permission_key=permission_key,
                    resource_id=resource_id,
                    context=context,
                )

        # Check API key scope for resource access
        if context.api_key_scope:
            if not context.api_key_scope.allows_resource(resource_type, resource_id):
                return AuthorizationDecision(
                    allowed=False,
                    reason=f"API key scope does not allow access to {resource_id}",
                    permission_key=permission_key,
                    resource_id=resource_id,
                    context=context,
                )

        return decision

    def check_resource_permission(
        self,
        user_id: str,
        action: Action,
        resource_type: ResourceType,
        resource_id: str,
        org_id: str | None = None,
        context: AuthorizationContext | None = None,
    ) -> AuthorizationDecision:
        """
        Check if a user has permission to perform an action on a specific resource.

        This method first checks resource-level permissions (fine-grained),
        then falls back to role-based permissions if no resource-level grant exists.

        Args:
            user_id: User to check
            action: Action to perform
            resource_type: Type of resource
            resource_id: Specific resource ID
            org_id: Organization context
            context: Optional full authorization context for role-based fallback

        Returns:
            AuthorizationDecision with result and reason
        """
        permission_key = f"{resource_type.value}.{action.value}"

        # Check cache first
        if self._enable_cache:
            cached = self._get_cached_resource_permission(
                user_id, permission_key, resource_type, resource_id, org_id
            )
            if cached is not None:
                return cached

        # Step 1: Check resource-level permissions if store is configured
        if self._resource_permission_store:
            has_resource_perm = self._resource_permission_store.check_resource_permission(
                user_id=user_id,
                permission_id=permission_key,
                resource_type=resource_type,
                resource_id=resource_id,
                org_id=org_id,
            )
            if has_resource_perm:
                decision = AuthorizationDecision(
                    allowed=True,
                    reason=f"Resource-level permission '{permission_key}' granted for {resource_type.value}/{resource_id}",
                    permission_key=permission_key,
                    resource_id=resource_id,
                    context=context,
                )
                if self._enable_cache:
                    self._cache_resource_permission(
                        user_id, permission_key, resource_type, resource_id, org_id, decision
                    )
                if self._auditor:
                    self._auditor.log_decision(decision)
                return decision

        # Step 2: Fall back to role-based permissions if context provided
        if context:
            decision = self.check_permission(context, permission_key, resource_id)
            if self._enable_cache:
                self._cache_resource_permission(
                    user_id, permission_key, resource_type, resource_id, org_id, decision
                )
            return decision

        # No resource permission and no context for role check
        decision = AuthorizationDecision(
            allowed=False,
            reason=f"No resource-level permission '{permission_key}' for {resource_type.value}/{resource_id}",
            permission_key=permission_key,
            resource_id=resource_id,
            context=None,
        )

        if self._enable_cache:
            self._cache_resource_permission(
                user_id, permission_key, resource_type, resource_id, org_id, decision
            )

        if self._auditor:
            self._auditor.log_decision(decision)

        return decision

    def set_resource_permission_store(self, store: ResourcePermissionStore | None) -> None:
        """
        Set the resource permission store.

        Args:
            store: ResourcePermissionStore instance or None to disable
        """
        self._resource_permission_store = store
        # Clear resource permission cache when store changes
        self._resource_permission_cache.clear()

    def get_resource_permission_store(self) -> ResourcePermissionStore | None:
        """Get the current resource permission store."""
        return self._resource_permission_store

    def clear_resource_permission_cache(
        self,
        user_id: str | None = None,
        resource_type: ResourceType | None = None,
        resource_id: str | None = None,
    ) -> None:
        """
        Clear the resource permission cache.

        Uses O(1) versioning for user-only invalidation, falls back to
        O(n) iteration when filtering by resource_type or resource_id.

        Thread-safe: Uses lock for version operations.

        Args:
            user_id: Optional filter by user ID
            resource_type: Optional filter by resource type
            resource_id: Optional filter by resource ID
        """
        if not user_id and not resource_type and not resource_id:
            # O(1) global invalidation
            with self._cache_version_lock:
                self._global_resource_cache_version += 1
                self._user_resource_cache_versions.clear()
                self._resource_permission_cache.clear()
            return

        # O(1) user-only invalidation via versioning
        if user_id and not resource_type and not resource_id:
            with self._cache_version_lock:
                self._user_resource_cache_versions[user_id] = (
                    self._user_resource_cache_versions.get(user_id, 0) + 1
                )
            return

        # O(n) fallback for resource_type/resource_id filtering
        # (would need additional indexing for O(1) in these cases)
        keys_to_remove = []
        for key in list(self._resource_permission_cache.keys()):
            parts = key.split(":")
            # Key format: version:user_id:permission:resource_type:resource_id:org_id
            if len(parts) >= 5:
                _, key_user_id, _, key_resource_type, key_resource_id = parts[:5]
                if user_id and key_user_id != user_id:
                    continue
                if resource_type and key_resource_type != resource_type.value:
                    continue
                if resource_id and key_resource_id != resource_id:
                    continue
                keys_to_remove.append(key)

        for key in keys_to_remove:
            self._resource_permission_cache.pop(key, None)

    def _get_cached_resource_permission(
        self,
        user_id: str,
        permission_key: str,
        resource_type: ResourceType,
        resource_id: str,
        org_id: str | None,
    ) -> AuthorizationDecision | None:
        """Get cached resource permission decision."""
        cache_key = f"{user_id}:{permission_key}:{resource_type.value}:{resource_id}:{org_id or ''}"

        if cache_key not in self._resource_permission_cache:
            return None

        result, cached_at = self._resource_permission_cache[cache_key]
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()

        if age > self._cache_ttl:
            del self._resource_permission_cache[cache_key]
            return None

        # Reconstruct decision from cached data
        if isinstance(result, AuthorizationDecision):
            return AuthorizationDecision(
                allowed=result.allowed,
                reason=result.reason,
                permission_key=result.permission_key,
                resource_id=result.resource_id,
                context=result.context,
                checked_at=result.checked_at,
                cached=True,
            )

        return None

    def _cache_resource_permission(
        self,
        user_id: str,
        permission_key: str,
        resource_type: ResourceType,
        resource_id: str,
        org_id: str | None,
        decision: AuthorizationDecision,
    ) -> None:
        """Cache a resource permission decision."""
        cache_key = f"{user_id}:{permission_key}:{resource_type.value}:{resource_id}:{org_id or ''}"
        self._resource_permission_cache[cache_key] = (decision, datetime.now(timezone.utc))

    def has_role(self, context: AuthorizationContext, role_name: str) -> bool:
        """Check if context has a specific role."""
        return role_name in context.roles

    def has_any_role(self, context: AuthorizationContext, *role_names: str) -> bool:
        """Check if context has any of the specified roles."""
        return bool(context.roles & set(role_names))

    def has_all_roles(self, context: AuthorizationContext, *role_names: str) -> bool:
        """Check if context has all of the specified roles."""
        return set(role_names) <= context.roles

    def is_owner(self, context: AuthorizationContext) -> bool:
        """Check if context has owner role."""
        return self.has_role(context, "owner")

    def is_admin(self, context: AuthorizationContext) -> bool:
        """Check if context has admin or owner role."""
        return self.has_any_role(context, "owner", "admin")

    def register_resource_policy(
        self,
        resource_type: ResourceType,
        resource_id: str,
        policy: Callable[[AuthorizationContext, Action, dict[str, Any]], bool],
    ) -> None:
        """
        Register a custom policy for a specific resource.

        Args:
            resource_type: Type of resource
            resource_id: Specific resource ID
            policy: Policy function that returns True if access is allowed
        """
        policy_key = f"{resource_type.value}:{resource_id}"
        self._resource_policies[policy_key] = policy

    def add_role_assignment(self, assignment: RoleAssignment) -> None:
        """Add a role assignment to the checker's cache."""
        if assignment.user_id not in self._role_assignments:
            self._role_assignments[assignment.user_id] = []
        self._role_assignments[assignment.user_id].append(assignment)

    def remove_role_assignment(self, user_id: str, role_id: str, org_id: str | None = None) -> None:
        """Remove a role assignment."""
        if user_id in self._role_assignments:
            self._role_assignments[user_id] = [
                a
                for a in self._role_assignments[user_id]
                if not (a.role_id == role_id and a.org_id == org_id)
            ]

    def get_user_roles(self, user_id: str, org_id: str | None = None) -> set[str]:
        """Get all active roles for a user in an organization."""
        roles: set[str] = set()
        assignments = self._role_assignments.get(user_id, [])

        for assignment in assignments:
            if not assignment.is_valid:
                continue
            if org_id is None or assignment.org_id == org_id:
                roles.add(assignment.role_id)

        return roles

    def clear_cache(self, user_id: str | None = None) -> None:
        """
        Clear decision cache, optionally for a specific user.

        Uses O(1) cache versioning instead of O(n) key iteration.
        Old entries with stale versions become unreachable and are
        cleaned up on TTL expiry or periodic cache maintenance.

        Thread-safe: Uses lock to prevent race conditions during version updates.
        """
        with self._cache_version_lock:
            if user_id:
                # O(1) invalidation: increment user's cache version
                # Old keys with old version won't match on lookup
                self._user_cache_versions[user_id] = self._user_cache_versions.get(user_id, 0) + 1
                # Also invalidate resource permission cache for this user
                self._user_resource_cache_versions[user_id] = (
                    self._user_resource_cache_versions.get(user_id, 0) + 1
                )
            else:
                # O(1) global invalidation: increment global versions
                self._global_cache_version += 1
                self._global_resource_cache_version += 1
                # Clear version dicts (optional, but keeps memory bounded)
                self._user_cache_versions.clear()
                self._user_resource_cache_versions.clear()
                # Also clear the actual cache dicts to free memory immediately
                self._decision_cache.clear()
                self._resource_permission_cache.clear()

    def _resolve_permissions(self, context: AuthorizationContext) -> AuthorizationContext:
        """Resolve all permissions from roles."""
        all_permissions: set[str] = set()

        for role_name in context.roles:
            # Get system role permissions
            permissions = get_role_permissions(role_name, include_inherited=True)
            all_permissions |= permissions

            # Check for custom role
            if context.org_id:
                custom_key = f"{context.org_id}:{role_name}"
                if custom_key in self._custom_roles:
                    custom = self._custom_roles[custom_key]
                    all_permissions |= custom.get("permissions", set())

        # Create new context with resolved permissions
        return AuthorizationContext(
            user_id=context.user_id,
            org_id=context.org_id,
            roles=context.roles,
            permissions=all_permissions,
            api_key_scope=context.api_key_scope,
            ip_address=context.ip_address,
            user_agent=context.user_agent,
            request_id=context.request_id,
            timestamp=context.timestamp,
        )

    def _evaluate_permission(
        self,
        context: AuthorizationContext,
        permission_key: str,
        resource_id: str | None,
    ) -> AuthorizationDecision:
        """Evaluate if context has permission."""
        # Check API key scope FIRST - if API key is present, it must allow the permission
        if context.api_key_scope:
            if not context.api_key_scope.allows_permission(permission_key):
                return AuthorizationDecision(
                    allowed=False,
                    reason=f"API key scope does not include '{permission_key}'",
                    permission_key=permission_key,
                    resource_id=resource_id,
                    context=context,
                )

        # Check for exact permission (try both colon and dot formats)
        candidates = _permission_candidates(permission_key)
        if candidates & context.permissions:
            return AuthorizationDecision(
                allowed=True,
                reason=f"Permission '{permission_key}' granted",
                permission_key=permission_key,
                resource_id=resource_id,
                context=context,
            )

        # Check for wildcard permission (e.g., "debates.*" or "debates:*")
        resource = permission_key.split(".")[0]
        wildcard_candidates = {f"{resource}.*", f"{resource}:*"}
        matched_wildcard = wildcard_candidates & context.permissions
        if matched_wildcard:
            return AuthorizationDecision(
                allowed=True,
                reason=f"Wildcard permission '{next(iter(matched_wildcard))}' grants '{permission_key}'",
                permission_key=permission_key,
                resource_id=resource_id,
                context=context,
            )

        # Check for super wildcard
        if "*" in context.permissions:
            return AuthorizationDecision(
                allowed=True,
                reason="Super wildcard '*' grants all permissions",
                permission_key=permission_key,
                resource_id=resource_id,
                context=context,
            )

        # Check workspace-scoped permissions if enabled
        if self._enable_workspace_scope and context.workspace_id:
            workspace_perms = self._get_workspace_permissions(context.user_id, context.workspace_id)
            if candidates & workspace_perms:
                return AuthorizationDecision(
                    allowed=True,
                    reason=f"Workspace-scoped permission '{permission_key}' granted",
                    permission_key=permission_key,
                    resource_id=resource_id,
                    context=context,
                )

        # Check delegated permissions if enabled
        if self._enable_delegation and self._delegation_manager:
            delegation = self._delegation_manager.check_delegation(
                user_id=context.user_id,
                permission_id=permission_key,
                org_id=context.org_id,
                workspace_id=context.workspace_id,
            )
            if delegation:
                return AuthorizationDecision(
                    allowed=True,
                    reason=f"Permission '{permission_key}' granted via delegation from {delegation.delegator_id}",
                    permission_key=permission_key,
                    resource_id=resource_id,
                    context=context,
                )

        # Check resource ownership as final fallback
        if self._enable_ownership and resource_id:
            try:
                if self._ownership_manager is None:
                    from .ownership import get_ownership_manager

                    self._ownership_manager = get_ownership_manager()
                resource_type_str = permission_key.split(".")[0]
                resource_type = ResourceType(resource_type_str)
                if self._ownership_manager.is_owner(
                    context.user_id, resource_type, resource_id, org_id=context.org_id
                ):
                    return AuthorizationDecision(
                        allowed=True,
                        reason=f"Implicit owner permission for '{permission_key}' on owned resource",
                        permission_key=permission_key,
                        resource_id=resource_id,
                        context=context,
                    )
            except (ValueError, ImportError):
                pass  # Resource type not in enum or ownership module unavailable

        # Permission denied
        return AuthorizationDecision(
            allowed=False,
            reason=f"Permission '{permission_key}' not granted to user",
            permission_key=permission_key,
            resource_id=resource_id,
            context=context,
        )

    def _get_workspace_permissions(self, user_id: str, workspace_id: str) -> set[str]:
        """Get permissions for a user in a specific workspace."""
        workspace_roles = self._workspace_roles.get(workspace_id, {})
        user_roles = workspace_roles.get(user_id, set())

        all_permissions: set[str] = set()
        for role_name in user_roles:
            permissions = get_role_permissions(role_name, include_inherited=True)
            all_permissions |= permissions

        return all_permissions

    def assign_workspace_role(
        self,
        user_id: str,
        workspace_id: str,
        role_name: str,
    ) -> None:
        """Assign a role to a user within a specific workspace."""
        if workspace_id not in self._workspace_roles:
            self._workspace_roles[workspace_id] = {}
        if user_id not in self._workspace_roles[workspace_id]:
            self._workspace_roles[workspace_id][user_id] = set()

        self._workspace_roles[workspace_id][user_id].add(role_name)
        logger.info("Assigned role %s to user %s in workspace %s", role_name, user_id, workspace_id)

    def remove_workspace_role(
        self,
        user_id: str,
        workspace_id: str,
        role_name: str,
    ) -> bool:
        """Remove a role from a user within a specific workspace."""
        if workspace_id not in self._workspace_roles:
            return False
        if user_id not in self._workspace_roles[workspace_id]:
            return False

        self._workspace_roles[workspace_id][user_id].discard(role_name)
        logger.info(
            "Removed role %s from user %s in workspace %s", role_name, user_id, workspace_id
        )
        return True

    def get_workspace_roles(self, user_id: str, workspace_id: str) -> set[str]:
        """Get all roles for a user in a specific workspace."""
        workspace_roles = self._workspace_roles.get(workspace_id, {})
        return workspace_roles.get(user_id, set()).copy()

    def set_delegation_manager(self, manager: DelegationManager | None) -> None:
        """Set the delegation manager."""
        self._delegation_manager = manager

    def get_delegation_manager(self) -> DelegationManager | None:
        """Get the current delegation manager."""
        return self._delegation_manager

    def set_condition_evaluator(self, evaluator: ConditionEvaluator | None) -> None:
        """Set a custom condition evaluator.

        Args:
            evaluator: ConditionEvaluator instance or None to use global singleton
        """
        self._condition_evaluator = evaluator

    def get_condition_evaluator(self) -> ConditionEvaluator | None:
        """Get the current condition evaluator (custom instance only)."""
        return self._condition_evaluator

    def set_conditions_enabled(self, enabled: bool) -> None:
        """Enable or disable ABAC condition evaluation.

        Args:
            enabled: Whether to evaluate conditions on permission checks
        """
        self._enable_conditions = enabled

    def is_conditions_enabled(self) -> bool:
        """Check if ABAC condition evaluation is enabled."""
        return self._enable_conditions

    def _roles_hash(self, roles: set[str]) -> str:
        """Generate hash for a set of roles."""
        return str(hash(frozenset(roles)))

    def _get_cached_decision(
        self,
        context: AuthorizationContext,
        permission_key: str,
        resource_id: str | None,
    ) -> AuthorizationDecision | None:
        """Get cached decision if valid (from distributed or local cache)."""
        roles_hash = self._roles_hash(context.roles)

        # Try distributed cache first if available
        if self._cache_backend:
            cached_dict = self._cache_backend.get_decision(
                context.user_id,
                context.org_id,
                roles_hash,
                permission_key,
                resource_id,
            )
            if cached_dict:
                return AuthorizationDecision(
                    allowed=cached_dict["allowed"],
                    reason=cached_dict["reason"],
                    permission_key=cached_dict.get("permission_key", permission_key),
                    resource_id=cached_dict.get("resource_id"),
                    context=context,
                    checked_at=(
                        datetime.fromisoformat(cached_dict["checked_at"])
                        if cached_dict.get("checked_at")
                        else datetime.now(timezone.utc)
                    ),
                    cached=True,
                )

        # Fall back to local cache (version included for O(1) invalidation)
        version = self._get_cache_version(context.user_id)
        cache_key = (
            f"{version}:{context.user_id}:{context.org_id}:{roles_hash}:"
            f"{permission_key}:{resource_id}"
        )
        if cache_key not in self._decision_cache:
            return None

        decision, cached_at = self._decision_cache[cache_key]
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()

        if age > self._cache_ttl:
            del self._decision_cache[cache_key]
            return None

        # Return cached decision with cached flag
        return AuthorizationDecision(
            allowed=decision.allowed,
            reason=decision.reason,
            permission_key=decision.permission_key,
            resource_id=decision.resource_id,
            context=decision.context,
            checked_at=decision.checked_at,
            cached=True,
        )

    def _cache_decision(
        self,
        context: AuthorizationContext,
        permission_key: str,
        resource_id: str | None,
        decision: AuthorizationDecision,
    ) -> None:
        """Cache a decision (to distributed and/or local cache)."""
        roles_hash = self._roles_hash(context.roles)

        # Cache to distributed backend if available
        if self._cache_backend:
            self._cache_backend.set_decision(
                context.user_id,
                context.org_id,
                roles_hash,
                permission_key,
                resource_id,
                {
                    "allowed": decision.allowed,
                    "reason": decision.reason,
                    "permission_key": decision.permission_key,
                    "resource_id": decision.resource_id,
                    "checked_at": (
                        decision.checked_at.isoformat()
                        if decision.checked_at
                        else datetime.now(timezone.utc).isoformat()
                    ),
                },
            )

        # Also cache locally (L1 when using distributed, primary otherwise)
        # Include version for O(1) invalidation
        version = self._get_cache_version(context.user_id)
        cache_key = (
            f"{version}:{context.user_id}:{context.org_id}:{roles_hash}:"
            f"{permission_key}:{resource_id}"
        )
        self._decision_cache[cache_key] = (decision, datetime.now(timezone.utc))

    def _on_remote_invalidation(self, key: str) -> None:
        """Handle invalidation from distributed cache (pub/sub).

        Thread-safe: Uses lock to prevent race conditions during version updates.
        """
        with self._cache_version_lock:
            if key == "all":
                # O(1) global invalidation via versioning
                self._global_cache_version += 1
                self._global_resource_cache_version += 1
                self._user_cache_versions.clear()
                self._user_resource_cache_versions.clear()
                self._decision_cache.clear()
                self._resource_permission_cache.clear()
            elif key.startswith("user:"):
                # O(1) user invalidation via versioning
                user_id = key[5:]
                self._user_cache_versions[user_id] = self._user_cache_versions.get(user_id, 0) + 1
                self._user_resource_cache_versions[user_id] = (
                    self._user_resource_cache_versions.get(user_id, 0) + 1
                )

    def get_role_permissions(self, role_name: str) -> set[str]:
        """
        Get permissions for a role, with caching.

        Args:
            role_name: Name of the role

        Returns:
            Set of permission keys
        """
        # Check distributed cache first
        if self._cache_backend:
            cached = self._cache_backend.get_role_permissions(role_name)
            if cached is not None:
                return cached

        # Get from defaults
        permissions = get_role_permissions(role_name, include_inherited=True)

        # Cache if distributed backend available
        if self._cache_backend:
            self._cache_backend.set_role_permissions(role_name, permissions)

        return permissions

    def get_users_with_permission(
        self,
        permission_key: str,
        org_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 100,
    ) -> list[str]:
        """
        Get user IDs that have a specific permission.

        This is the reverse lookup of check_permission - finds all users
        who could approve a request requiring this permission.

        Args:
            permission_key: Permission to search for (e.g., "debates.admin" or "debates:admin")
            org_id: Optional organization filter
            workspace_id: Optional workspace filter
            limit: Maximum users to return (default 100)

        Returns:
            List of user IDs with the permission
        """
        users_with_permission: list[str] = []

        # Normalize permission key (support both : and . separators)
        normalized_key = permission_key.replace(":", ".")

        # Extract resource type for wildcard matching
        resource = normalized_key.split(".")[0] if "." in normalized_key else normalized_key

        # Check role assignments
        for user_id, assignments in self._role_assignments.items():
            if len(users_with_permission) >= limit:
                break

            for assignment in assignments:
                # Skip invalid assignments
                if not assignment.is_valid:
                    continue
                # Filter by org if specified
                if org_id and assignment.org_id and assignment.org_id != org_id:
                    continue

                # Get role permissions
                role_permissions = get_role_permissions(assignment.role_id, include_inherited=True)

                # Check if role has the permission (exact match)
                if normalized_key in role_permissions:
                    if user_id not in users_with_permission:
                        users_with_permission.append(user_id)
                    break

                # Check wildcard patterns
                wildcards = [f"{resource}.*", f"{resource}:*", "*"]
                if any(w in role_permissions for w in wildcards):
                    if user_id not in users_with_permission:
                        users_with_permission.append(user_id)
                    break

        # Also check workspace roles if workspace_id provided
        if workspace_id and workspace_id in self._workspace_roles:
            workspace_users = self._workspace_roles[workspace_id]
            for user_id, roles in workspace_users.items():
                if user_id in users_with_permission:
                    continue
                if len(users_with_permission) >= limit:
                    break

                for role_name in roles:
                    role_permissions = get_role_permissions(role_name, include_inherited=True)
                    if normalized_key in role_permissions:
                        users_with_permission.append(user_id)
                        break
                    # Check wildcards
                    wildcards = [f"{resource}.*", f"{resource}:*", "*"]
                    if any(w in role_permissions for w in wildcards):
                        users_with_permission.append(user_id)
                        break

        logger.debug(
            "Found %s users with permission '%s'", len(users_with_permission), permission_key
        )
        return users_with_permission

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        stats: dict[str, Any] = {
            "local_cache_size": len(self._decision_cache),
            "resource_permission_cache_size": len(self._resource_permission_cache),
            "cache_enabled": self._enable_cache,
            "cache_ttl": self._cache_ttl,
            "resource_permission_store_enabled": self._resource_permission_store is not None,
            "delegation_enabled": self._enable_delegation,
            "delegation_manager_enabled": self._delegation_manager is not None,
            "workspace_scope_enabled": self._enable_workspace_scope,
            "workspace_count": len(self._workspace_roles),
            "conditions_enabled": self._enable_conditions,
            "condition_evaluator_custom": self._condition_evaluator is not None,
        }

        if self._cache_backend:
            stats["distributed"] = True
            stats["distributed_stats"] = self._cache_backend.get_stats()
        else:
            stats["distributed"] = False

        if self._resource_permission_store:
            stats["resource_permission_store_stats"] = self._resource_permission_store.get_stats()

        if self._delegation_manager:
            stats["delegation_stats"] = self._delegation_manager.get_stats()

        return stats


# Global permission checker instance
_permission_checker: PermissionChecker | None = None


def get_permission_checker() -> PermissionChecker:
    """Get or create the global permission checker instance."""
    global _permission_checker
    if _permission_checker is None:
        _permission_checker = PermissionChecker()
    return _permission_checker


def set_permission_checker(checker: PermissionChecker) -> None:
    """Set the global permission checker instance."""
    global _permission_checker
    _permission_checker = checker


def check_permission(
    context: AuthorizationContext,
    permission_key: str,
    resource_id: str | None = None,
) -> AuthorizationDecision:
    """Convenience function to check permission using global checker.

    Args:
        context: Authorization context
        permission_key: Permission to check (accepts both "resource.action" and "resource:action")
        resource_id: Optional specific resource ID

    Returns:
        AuthorizationDecision with result and reason
    """
    # Normalize permission key format (colon -> dot)
    if ":" in permission_key and "." not in permission_key:
        permission_key = permission_key.replace(":", ".")
    # Normalize legacy/plural resource names for backwards compatibility
    if "." in permission_key:
        resource, action = permission_key.split(".", 1)
        legacy_map = {
            "organizations": "organization",
            "workspaces": "workspace",
        }
        normalized_resource = legacy_map.get(resource)
        if normalized_resource:
            permission_key = f"{normalized_resource}.{action}"
        if resource == "retention" and action.startswith("policies."):
            legacy_action = action.split(".", 1)[-1]
            if legacy_action in {"read", "view"}:
                permission_key = "data_retention.read"
            else:
                permission_key = "data_retention.update"
    return get_permission_checker().check_permission(context, permission_key, resource_id)


def has_permission(
    context: AuthorizationContext,
    permission_key: str,
    resource_id: str | None = None,
) -> bool:
    """Convenience function to check if permission is granted.

    Args:
        context: Authorization context
        permission_key: Permission to check (accepts both "resource.action" and "resource:action")
        resource_id: Optional specific resource ID

    Returns:
        True if permission is granted, False otherwise
    """
    return check_permission(context, permission_key, resource_id).allowed
