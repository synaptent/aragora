"""
Attribute-Based Access Control (ABAC) Middleware.

Provides fine-grained resource-level access control beyond role-based checks.
Evaluates access based on:
- Subject attributes (user role, plan, workspace membership)
- Resource attributes (owner, workspace, sensitivity)
- Action attributes (read, write, delete, admin)
- Environment attributes (IP, time, request context)

Usage:
    from aragora.server.middleware.abac import (
        check_resource_access,
        require_resource_owner,
        ResourcePolicy,
    )

    @require_resource_owner("debate")
    async def delete_debate(request, debate_id: str, user: User):
        # Only debate owner can delete
        ...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, TypeVar, cast
from collections.abc import Callable

logger = logging.getLogger(__name__)

# =============================================================================
# Access Control Types
# =============================================================================


class Action(str, Enum):
    """Actions that can be performed on resources."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    SHARE = "share"
    ADMIN = "admin"
    EXECUTE = "execute"
    EXPORT = "export"


class ResourceType(str, Enum):
    """Types of resources in the system."""

    DEBATE = "debate"
    WORKSPACE = "workspace"
    DOCUMENT = "document"
    KNOWLEDGE = "knowledge"
    WORKFLOW = "workflow"
    AGENT = "agent"
    TEMPLATE = "template"
    EVIDENCE = "evidence"
    INSIGHT = "insight"
    TOURNAMENT = "tournament"


class AccessLevel(str, Enum):
    """Access levels for resources."""

    NONE = "none"
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    OWNER = "owner"


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class Subject:
    """Subject (user) attempting access."""

    user_id: str
    role: str = "user"  # user, admin, service, superadmin
    plan: str = "free"  # free, pro, team, enterprise
    workspace_id: str | None = None
    workspace_role: str | None = None  # owner, admin, member, viewer
    scopes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_admin(self) -> bool:
        return self.role in ("admin", "superadmin")

    @property
    def is_workspace_admin(self) -> bool:
        return self.workspace_role in ("owner", "admin")


@dataclass
class Resource:
    """Resource being accessed."""

    resource_type: ResourceType
    resource_id: str
    owner_id: str | None = None
    workspace_id: str | None = None
    sensitivity: str = "internal"  # public, internal, confidential, restricted
    shared_with: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Environment:
    """Environment context for access decision."""

    ip_address: str | None = None
    user_agent: str | None = None
    request_path: str | None = None
    request_method: str | None = None
    timestamp: float | None = None


@dataclass
class AccessRequest:
    """Complete access request for evaluation."""

    subject: Subject
    resource: Resource
    action: Action
    environment: Environment = field(default_factory=Environment)


@dataclass
class AccessDecision:
    """Result of access evaluation."""

    allowed: bool
    reason: str
    policy_name: str | None = None
    attributes_evaluated: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Policy Definitions
# =============================================================================


@dataclass
class ResourcePolicy:
    """
    Policy defining access rules for a resource type.

    Attributes:
        resource_type: Type of resource this policy applies to
        allow_public_read: Allow unauthenticated read access
        owner_actions: Actions owners can perform
        workspace_admin_actions: Actions workspace admins can perform
        workspace_member_actions: Actions workspace members can perform
        shared_user_actions: Actions users with explicit shares can perform
        admin_actions: Actions system admins can perform
        require_same_workspace: Require subject and resource in same workspace
        sensitivity_restrictions: Map sensitivity level to required plan
    """

    resource_type: ResourceType
    allow_public_read: bool = False
    owner_actions: set[Action] = field(
        default_factory=lambda: {
            Action.READ,
            Action.WRITE,
            Action.DELETE,
            Action.SHARE,
            Action.ADMIN,
            Action.EXPORT,
        }
    )
    workspace_admin_actions: set[Action] = field(
        default_factory=lambda: {
            Action.READ,
            Action.WRITE,
            Action.DELETE,
            Action.ADMIN,
        }
    )
    workspace_member_actions: set[Action] = field(
        default_factory=lambda: {Action.READ, Action.WRITE}
    )
    shared_user_actions: set[Action] = field(default_factory=lambda: {Action.READ})
    admin_actions: set[Action] = field(
        default_factory=lambda: {
            Action.READ,
            Action.WRITE,
            Action.DELETE,
            Action.ADMIN,
            Action.EXPORT,
        }
    )
    require_same_workspace: bool = True
    sensitivity_restrictions: dict[str, list[str]] = field(
        default_factory=lambda: {
            "public": ["free", "pro", "team", "enterprise"],
            "internal": ["free", "pro", "team", "enterprise"],
            "confidential": ["pro", "team", "enterprise"],
            "restricted": ["enterprise"],
        }
    )


# =============================================================================
# Default Policies
# =============================================================================

DEFAULT_POLICIES: dict[ResourceType, ResourcePolicy] = {
    ResourceType.DEBATE: ResourcePolicy(
        resource_type=ResourceType.DEBATE,
        allow_public_read=False,
        owner_actions={
            Action.READ,
            Action.WRITE,
            Action.DELETE,
            Action.SHARE,
            Action.EXPORT,
        },
        workspace_member_actions={Action.READ, Action.WRITE},
        shared_user_actions={Action.READ},
    ),
    ResourceType.WORKSPACE: ResourcePolicy(
        resource_type=ResourceType.WORKSPACE,
        allow_public_read=False,
        owner_actions={
            Action.READ,
            Action.WRITE,
            Action.DELETE,
            Action.ADMIN,
            Action.SHARE,
        },
        workspace_admin_actions={Action.READ, Action.WRITE, Action.ADMIN},
        workspace_member_actions={Action.READ},
        require_same_workspace=False,  # Workspace access is self-contained
    ),
    ResourceType.DOCUMENT: ResourcePolicy(
        resource_type=ResourceType.DOCUMENT,
        allow_public_read=False,
        owner_actions={
            Action.READ,
            Action.WRITE,
            Action.DELETE,
            Action.SHARE,
            Action.EXPORT,
        },
        sensitivity_restrictions={
            "public": ["free", "pro", "team", "enterprise"],
            "internal": ["pro", "team", "enterprise"],
            "confidential": ["team", "enterprise"],
            "restricted": ["enterprise"],
        },
    ),
    ResourceType.WORKFLOW: ResourcePolicy(
        resource_type=ResourceType.WORKFLOW,
        allow_public_read=False,
        owner_actions={
            Action.READ,
            Action.WRITE,
            Action.DELETE,
            Action.EXECUTE,
            Action.SHARE,
        },
        workspace_member_actions={Action.READ, Action.EXECUTE},
    ),
    ResourceType.KNOWLEDGE: ResourcePolicy(
        resource_type=ResourceType.KNOWLEDGE,
        allow_public_read=False,
        workspace_member_actions={Action.READ, Action.WRITE},
    ),
    ResourceType.EVIDENCE: ResourcePolicy(
        resource_type=ResourceType.EVIDENCE,
        allow_public_read=True,  # Evidence is generally public
        workspace_member_actions={Action.READ, Action.WRITE},
    ),
    ResourceType.TEMPLATE: ResourcePolicy(
        resource_type=ResourceType.TEMPLATE,
        allow_public_read=True,  # Templates can be public
        owner_actions={Action.READ, Action.WRITE, Action.DELETE, Action.SHARE},
        workspace_member_actions={Action.READ},
    ),
    ResourceType.TOURNAMENT: ResourcePolicy(
        resource_type=ResourceType.TOURNAMENT,
        allow_public_read=True,
        owner_actions={Action.READ, Action.WRITE, Action.DELETE, Action.ADMIN},
        workspace_member_actions={Action.READ, Action.WRITE},
    ),
    ResourceType.INSIGHT: ResourcePolicy(
        resource_type=ResourceType.INSIGHT,
        allow_public_read=False,
        workspace_member_actions={Action.READ},
    ),
    ResourceType.AGENT: ResourcePolicy(
        resource_type=ResourceType.AGENT,
        allow_public_read=True,  # Agent profiles are public
        owner_actions={Action.READ, Action.WRITE, Action.DELETE, Action.ADMIN},
        workspace_member_actions={Action.READ},
    ),
}

# =============================================================================
# Policy Registry
# =============================================================================


class PolicyRegistry:
    """Registry for resource access policies."""

    _instance: PolicyRegistry | None = None
    _policies: dict[ResourceType, ResourcePolicy]

    def __new__(cls) -> PolicyRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._policies = dict(DEFAULT_POLICIES)
        return cls._instance

    def register(self, policy: ResourcePolicy) -> None:
        """Register a policy for a resource type."""
        self._policies[policy.resource_type] = policy
        logger.debug("Registered policy for %s", policy.resource_type.value)

    def get(self, resource_type: ResourceType) -> ResourcePolicy | None:
        """Get policy for a resource type."""
        return self._policies.get(resource_type)

    def get_or_default(self, resource_type: ResourceType) -> ResourcePolicy:
        """Get policy or create default."""
        if resource_type not in self._policies:
            self._policies[resource_type] = ResourcePolicy(resource_type=resource_type)
        return self._policies[resource_type]

    def list_all(self) -> dict[ResourceType, ResourcePolicy]:
        """List all registered policies."""
        return dict(self._policies)

    @classmethod
    def reset(cls) -> None:
        """Reset to default policies (for testing)."""
        if cls._instance:
            cls._instance._policies = dict(DEFAULT_POLICIES)


def get_policy_registry() -> PolicyRegistry:
    """Get the global policy registry."""
    return PolicyRegistry()


# =============================================================================
# Access Evaluator
# =============================================================================


class AccessEvaluator:
    """
    Evaluates access requests against policies.

    Implements ABAC logic with the following precedence:
    1. System admin override (admins can access everything)
    2. Owner check (owners have full access)
    3. Workspace admin check
    4. Workspace member check
    5. Shared access check
    6. Public access check
    7. Deny by default
    """

    def __init__(self, registry: PolicyRegistry | None = None):
        self.registry = registry or get_policy_registry()

    def evaluate(self, request: AccessRequest) -> AccessDecision:
        """
        Evaluate an access request.

        Args:
            request: The access request to evaluate

        Returns:
            AccessDecision with allow/deny and reason
        """
        subject = request.subject
        resource = request.resource
        action = request.action

        # Get policy for resource type
        policy = self.registry.get(resource.resource_type)
        if not policy:
            return AccessDecision(
                allowed=False,
                reason=f"No policy defined for resource type: {resource.resource_type.value}",
            )

        attributes = {
            "subject_id": subject.user_id,
            "subject_role": subject.role,
            "subject_plan": subject.plan,
            "resource_type": resource.resource_type.value,
            "resource_id": resource.resource_id,
            "action": action.value,
        }

        # 1. System admin override
        if subject.is_admin:
            if action in policy.admin_actions:
                return AccessDecision(
                    allowed=True,
                    reason="System admin access",
                    policy_name="admin_override",
                    attributes_evaluated=attributes,
                )

        # 2. Owner check
        if resource.owner_id and subject.user_id == resource.owner_id:
            if action in policy.owner_actions:
                return AccessDecision(
                    allowed=True,
                    reason="Resource owner access",
                    policy_name="owner_access",
                    attributes_evaluated=attributes,
                )

        # 3. Workspace checks (if resource has workspace)
        if resource.workspace_id:
            # Check if subject is in same workspace
            if policy.require_same_workspace:
                if subject.workspace_id != resource.workspace_id:
                    return AccessDecision(
                        allowed=False,
                        reason="Resource belongs to different workspace",
                        policy_name="workspace_isolation",
                        attributes_evaluated=attributes,
                    )

            # 3a. Workspace admin
            if subject.is_workspace_admin and subject.workspace_id == resource.workspace_id:
                if action in policy.workspace_admin_actions:
                    return AccessDecision(
                        allowed=True,
                        reason="Workspace admin access",
                        policy_name="workspace_admin",
                        attributes_evaluated=attributes,
                    )

            # 3b. Workspace member
            if subject.workspace_id == resource.workspace_id:
                if action in policy.workspace_member_actions:
                    return AccessDecision(
                        allowed=True,
                        reason="Workspace member access",
                        policy_name="workspace_member",
                        attributes_evaluated=attributes,
                    )

        # 4. Shared access check
        if subject.user_id in resource.shared_with:
            if action in policy.shared_user_actions:
                return AccessDecision(
                    allowed=True,
                    reason="Shared access",
                    policy_name="shared_access",
                    attributes_evaluated=attributes,
                )

        # 5. Public access check (for READ only)
        if policy.allow_public_read and action == Action.READ:
            return AccessDecision(
                allowed=True,
                reason="Public read access",
                policy_name="public_access",
                attributes_evaluated=attributes,
            )

        # 6. Sensitivity restrictions
        if resource.sensitivity in policy.sensitivity_restrictions:
            allowed_plans = policy.sensitivity_restrictions[resource.sensitivity]
            if subject.plan not in allowed_plans:
                return AccessDecision(
                    allowed=False,
                    reason=f"Plan '{subject.plan}' cannot access '{resource.sensitivity}' resources",
                    policy_name="sensitivity_restriction",
                    attributes_evaluated=attributes,
                )

        # 7. Default deny
        return AccessDecision(
            allowed=False,
            reason="Access denied by default policy",
            policy_name="default_deny",
            attributes_evaluated=attributes,
        )


# =============================================================================
# Convenience Functions
# =============================================================================

_evaluator: AccessEvaluator | None = None


def get_evaluator() -> AccessEvaluator:
    """Get the global access evaluator."""
    global _evaluator
    if _evaluator is None:
        _evaluator = AccessEvaluator()
    return _evaluator


def check_resource_access(
    user_id: str,
    user_role: str,
    user_plan: str,
    resource_type: ResourceType | str,
    resource_id: str,
    action: Action | str,
    resource_owner_id: str | None = None,
    resource_workspace_id: str | None = None,
    user_workspace_id: str | None = None,
    user_workspace_role: str | None = None,
    shared_with: set[str] | None = None,
    sensitivity: str = "internal",
) -> AccessDecision:
    """
    Check if a user can perform an action on a resource.

    Args:
        user_id: ID of the user attempting access
        user_role: User's system role (user, admin, etc.)
        user_plan: User's subscription plan
        resource_type: Type of resource
        resource_id: ID of the resource
        action: Action being attempted
        resource_owner_id: Owner of the resource
        resource_workspace_id: Workspace the resource belongs to
        user_workspace_id: User's current workspace
        user_workspace_role: User's role in their workspace
        shared_with: Set of user IDs resource is shared with
        sensitivity: Resource sensitivity level

    Returns:
        AccessDecision with allowed status and reason
    """
    # Convert strings to enums if needed
    if isinstance(resource_type, str):
        resource_type = ResourceType(resource_type)
    if isinstance(action, str):
        action = Action(action)

    subject = Subject(
        user_id=user_id,
        role=user_role,
        plan=user_plan,
        workspace_id=user_workspace_id,
        workspace_role=user_workspace_role,
    )

    resource = Resource(
        resource_type=resource_type,
        resource_id=resource_id,
        owner_id=resource_owner_id,
        workspace_id=resource_workspace_id,
        shared_with=shared_with or set(),
        sensitivity=sensitivity,
    )

    request = AccessRequest(subject=subject, resource=resource, action=action)

    return get_evaluator().evaluate(request)


def is_resource_owner(user_id: str, resource_owner_id: str | None) -> bool:
    """Check if user is the owner of a resource."""
    return resource_owner_id is not None and user_id == resource_owner_id


# =============================================================================
# Decorators
# =============================================================================

F = TypeVar("F", bound=Callable[..., Any])


def require_resource_owner(resource_type: str) -> Callable[[F], F]:
    """
    Decorator to require resource ownership for an endpoint.

    Usage:
        @require_resource_owner("debate")
        async def delete_debate(request, debate_id: str, user: User):
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract user and resource_id from kwargs
            user = kwargs.get("user")
            kwargs.get(f"{resource_type}_id") or kwargs.get("resource_id")

            if not user:
                from aragora.api_errors import AuthenticationError, format_error_response

                return format_error_response(AuthenticationError("Authentication required"))

            # Get resource owner (would need to be fetched from DB in real implementation)
            # This is a placeholder - actual implementation would query the resource
            resource_owner_id = kwargs.get("resource_owner_id")

            if resource_owner_id and user.id != resource_owner_id:
                if not getattr(user, "is_admin", False):
                    from aragora.api_errors import ForbiddenError, format_error_response

                    return format_error_response(
                        ForbiddenError(f"You do not have permission to modify this {resource_type}")
                    )

            return await func(*args, **kwargs)

        return cast(F, wrapper)

    return decorator


def require_access(
    resource_type: ResourceType | str,
    action: Action | str,
) -> Callable[[F], F]:
    """
    Decorator to require specific access level for an endpoint.

    Usage:
        @require_access(ResourceType.DEBATE, Action.DELETE)
        async def delete_debate(request, debate_id: str, user: User):
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            user = kwargs.get("user")
            resource_id = kwargs.get("resource_id")

            if not user:
                from aragora.api_errors import AuthenticationError, format_error_response

                return format_error_response(AuthenticationError("Authentication required"))

            # Check access (simplified - would need resource metadata in real impl)
            decision = check_resource_access(
                user_id=user.id,
                user_role=getattr(user, "role", "user"),
                user_plan=getattr(user, "plan", "free"),
                resource_type=resource_type,
                resource_id=resource_id or "unknown",
                action=action,
                user_workspace_id=getattr(user, "workspace_id", None),
            )

            if not decision.allowed:
                from aragora.api_errors import ForbiddenError, format_error_response

                return format_error_response(ForbiddenError(decision.reason))

            return await func(*args, **kwargs)

        return cast(F, wrapper)

    return decorator


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Types
    "Action",
    "ResourceType",
    "AccessLevel",
    # Data models
    "Subject",
    "Resource",
    "Environment",
    "AccessRequest",
    "AccessDecision",
    # Policies
    "ResourcePolicy",
    "PolicyRegistry",
    "get_policy_registry",
    "DEFAULT_POLICIES",
    # Evaluation
    "AccessEvaluator",
    "get_evaluator",
    "check_resource_access",
    "is_resource_owner",
    # Decorators
    "require_resource_owner",
    "require_access",
]
