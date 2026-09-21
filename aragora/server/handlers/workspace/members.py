"""
Workspace Member Management Mixin.

Provides handler methods for adding/removing members, managing roles, and
listing RBAC profiles. Used as a mixin class by WorkspaceHandler in
workspace_module.py.

All references to ``extract_user_from_request`` and privacy types are resolved
at *call time* via ``aragora.server.handlers.workspace.workspace_module`` so that test
patches on that module are respected.

Stability: STABLE
"""

from __future__ import annotations

import logging
from collections.abc import Coroutine
from typing import Any, TYPE_CHECKING

from aragora.events.handler_events import emit_handler_event, UPDATED
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import handle_errors, log_request
from aragora.server.handlers.openapi_decorator import api_endpoint
from aragora.server.handlers.utils.rate_limit import rate_limit

if TYPE_CHECKING:
    from aragora.billing.auth.context import UserAuthContext
    from aragora.privacy import DataIsolationManager, PrivacyAuditLog
    from aragora.protocols import HTTPRequestHandler
    from aragora.server.handlers.base import HandlerResult

logger = logging.getLogger(__name__)


def _mod() -> Any:
    """Lazy import of workspace_module to avoid circular imports and respect patches."""
    import aragora.server.handlers.workspace.workspace_module as m

    return m


class WorkspaceMembersMixin:
    """Mixin providing member management handler methods.

    Expects the host class to provide:
    - _get_user_store()
    - _get_isolation_manager()
    - _get_audit_log()
    - _run_async(coro)
    - _check_rbac_permission(handler, perm, auth_ctx)
    - read_json_body(handler)

    The full contract is formalised in
    :class:`aragora.server.handlers.workspace._protocols.WorkspaceMixinHost`;
    the ``TYPE_CHECKING`` stubs below mirror that protocol so that mypy can
    resolve cross-mixin attribute accesses without altering runtime
    behaviour.
    """

    if TYPE_CHECKING:
        # Cross-mixin host contract (see ``_protocols.WorkspaceMixinHost``).
        # These declarations exist for static type checking only; at runtime
        # the real implementations are provided by ``WorkspaceHandler`` and
        # ``SecureHandler`` in the final class hierarchy.
        def _get_user_store(self) -> Any: ...

        def _get_isolation_manager(self) -> DataIsolationManager: ...

        def _get_audit_log(self) -> PrivacyAuditLog: ...

        def _run_async(self, coro: Coroutine[Any, Any, Any]) -> Any: ...

        def _check_rbac_permission(
            self,
            handler: HTTPRequestHandler,
            permission_key: str,
            auth_ctx: UserAuthContext | None = ...,
        ) -> HandlerResult | None: ...

        def read_json_body(
            self,
            handler: Any,
            max_size: int | None = ...,
        ) -> dict[str, Any] | None: ...

    @api_endpoint(
        method="GET",
        path="/api/v1/workspaces/{workspace_id}/members",
        summary="List workspace members",
        tags=["Workspaces"],
    )
    @rate_limit(requests_per_minute=60, limiter_name="workspace_member")
    @require_permission("workspace:members:read")
    @handle_errors("list workspace members")
    @log_request("list workspace members")
    def _handle_list_members(self, handler: HTTPRequestHandler, workspace_id: str) -> HandlerResult:
        """List all members of a workspace with their roles and permissions."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, "workspace:members:read", auth_ctx)
        if rbac_error:
            return rbac_error

        manager = self._get_isolation_manager()

        try:
            members_data = self._run_async(manager.list_members(workspace_id))
            members = []
            for member in members_data:
                user_id = member.get("user_id", "")
                user_profile = self._run_async(user_store.get_user_by_id(user_id))
                members.append(
                    {
                        "id": user_id,
                        "name": user_profile.name if user_profile else "Unknown",
                        "email": user_profile.email if user_profile else "",
                        "role": member.get("role", "member"),
                        "permissions": member.get("permissions", []),
                        "status": member.get("status", "active"),
                        "joined_at": member.get("joined_at", ""),
                        "workspace_id": workspace_id,
                    }
                )

            logger.info("workspace_members.list workspace=%s count=%d", workspace_id, len(members))
            return {"members": members, "total": len(members)}  # type: ignore[return-value]

        except m.AccessDeniedException as e:
            logger.warning("Handler error: %s", e)
            return m.error_response("Permission denied", 403)
        except (RuntimeError, OSError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error("Failed to list workspace members: %s", e)
            return m.error_response("Failed to list members", 500)

    @api_endpoint(
        method="POST",
        path="/api/v1/workspaces/{workspace_id}/members",
        summary="Add member to workspace",
        tags=["Workspaces"],
    )
    @rate_limit(requests_per_minute=30, limiter_name="workspace_member")
    @require_permission("workspace:members:write")
    @handle_errors("add workspace member")
    @log_request("add workspace member")
    def _handle_add_member(self, handler: HTTPRequestHandler, workspace_id: str) -> HandlerResult:
        """Add a member to a workspace."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_WORKSPACE_SHARE, auth_ctx)
        if rbac_error:
            return rbac_error

        body = self.read_json_body(handler)
        if body is None:
            return m.error_response("Invalid JSON body", 400)

        user_id = body.get("user_id")
        if not user_id:
            return m.error_response("user_id is required", 400)

        permissions_raw = body.get("permissions", ["read"])
        permissions = [m.WorkspacePermission(p) for p in permissions_raw]

        manager = self._get_isolation_manager()
        try:
            self._run_async(
                manager.add_member(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    permissions=permissions,
                    added_by=auth_ctx.user_id,
                )
            )
        except m.AccessDeniedException as e:
            logger.warning("Handler error: %s", e)
            return m.error_response("Permission denied", 403)

        # Log to audit
        audit_log = self._get_audit_log()
        self._run_async(
            audit_log.log(
                action=m.AuditAction.ADD_MEMBER,
                actor=m.Actor(id=auth_ctx.user_id, type="user"),
                resource=m.Resource(id=workspace_id, type="workspace", workspace_id=workspace_id),
                outcome=m.AuditOutcome.SUCCESS,
                details={"added_user_id": user_id, "permissions": permissions_raw},
            )
        )

        emit_handler_event(
            "workspace",
            UPDATED,
            {"action": "member_added", "workspace_id": workspace_id},
            user_id=auth_ctx.user_id,
        )
        return m.json_response({"message": f"Member {user_id} added to workspace"}, status=201)

    @api_endpoint(
        method="DELETE",
        path="/api/v1/workspaces/{workspace_id}/members/{user_id}",
        summary="Remove member from workspace",
        tags=["Workspaces"],
    )
    @rate_limit(requests_per_minute=30, limiter_name="workspace_member")
    @require_permission("workspace:members:write")
    @handle_errors("remove workspace member")
    @log_request("remove workspace member")
    def _handle_remove_member(
        self, handler: HTTPRequestHandler, workspace_id: str, user_id: str
    ) -> HandlerResult:
        """Remove a member from a workspace."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_WORKSPACE_SHARE, auth_ctx)
        if rbac_error:
            return rbac_error

        manager = self._get_isolation_manager()
        try:
            self._run_async(
                manager.remove_member(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    removed_by=auth_ctx.user_id,
                )
            )
        except m.AccessDeniedException as e:
            logger.warning("Handler error: %s", e)
            return m.error_response("Permission denied", 403)

        # Log to audit
        audit_log = self._get_audit_log()
        self._run_async(
            audit_log.log(
                action=m.AuditAction.REMOVE_MEMBER,
                actor=m.Actor(id=auth_ctx.user_id, type="user"),
                resource=m.Resource(id=workspace_id, type="workspace", workspace_id=workspace_id),
                outcome=m.AuditOutcome.SUCCESS,
                details={"removed_user_id": user_id},
            )
        )

        return m.json_response({"message": f"Member {user_id} removed from workspace"})

    @api_endpoint(
        method="GET",
        path="/api/v1/workspaces/profiles",
        summary="List available RBAC profiles",
        tags=["Workspaces"],
    )
    @require_permission("workspace:read")
    @handle_errors("list profiles")
    def _handle_list_profiles(self, handler: HTTPRequestHandler) -> HandlerResult:
        """List available RBAC profiles for workspace configuration.

        Returns the three profile tiers: lite, standard, enterprise.
        Each includes available roles, default role, and features.
        """
        m = _mod()
        if not m.PROFILES_AVAILABLE:
            return m.error_response("RBAC profiles not available", 503)

        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_WORKSPACE_READ, auth_ctx)
        if rbac_error:
            return rbac_error

        profiles = []
        for profile in m.RBACProfile:
            config = m.get_profile_config(profile)
            profiles.append(
                {
                    "id": profile.value,
                    "name": config.name,
                    "description": config.description,
                    "roles": config.roles,
                    "default_role": config.default_role,
                    "features": list(config.features),
                }
            )

        # Include lite role details for quick reference
        lite_summary = m.get_lite_role_summary()

        return m.json_response(
            {
                "profiles": profiles,
                "lite_roles_detail": lite_summary,
                "recommended": "lite",
                "message": "Use 'lite' for SME workspaces, 'standard' for growing teams",
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/workspaces/{workspace_id}/roles",
        summary="Get available roles for workspace",
        tags=["Workspaces"],
    )
    @require_permission("workspace:members:read")
    @handle_errors("get workspace roles")
    def _handle_get_workspace_roles(
        self, handler: HTTPRequestHandler, workspace_id: str
    ) -> HandlerResult:
        """Get available roles for a workspace based on its profile.

        Returns roles that can be assigned to members, with descriptions
        and what roles the current user can assign.
        """
        m = _mod()
        if not m.PROFILES_AVAILABLE:
            return m.error_response("RBAC profiles not available", 503)

        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_WORKSPACE_READ, auth_ctx)
        if rbac_error:
            return rbac_error

        # Get workspace to find its profile
        manager = self._get_isolation_manager()
        try:
            workspace = self._run_async(
                manager.get_workspace(
                    workspace_id=workspace_id,
                    actor=auth_ctx.user_id,
                )
            )
        except m.AccessDeniedException as e:
            logger.warning("Handler error: %s", e)
            return m.error_response("Permission denied", 403)

        # Get workspace profile (default to lite)
        workspace_dict = workspace.to_dict()
        profile_name = workspace_dict.get("rbac_profile", "lite")

        try:
            config = m.get_profile_config(profile_name)
            roles = m.get_profile_roles(profile_name)
        except ValueError:
            # Fallback to lite if profile is invalid
            config = m.get_profile_config("lite")
            roles = m.get_profile_roles("lite")

        # Get current user's role to determine what they can assign
        user_role = workspace_dict.get("member_roles", {}).get(auth_ctx.user_id, "member")
        assignable_roles = m.get_available_roles_for_assignment(profile_name, user_role)

        role_list = []
        for role_name in config.roles:
            role = roles.get(role_name)
            if role:
                role_list.append(
                    {
                        "id": role_name,
                        "name": role.name,
                        "description": role.description,
                        "can_assign": role_name in assignable_roles,
                    }
                )

        return m.json_response(
            {
                "workspace_id": workspace_id,
                "profile": profile_name,
                "roles": role_list,
                "your_role": user_role,
                "assignable_by_you": assignable_roles,
            }
        )

    @api_endpoint(
        method="PUT",
        path="/api/v1/workspaces/{workspace_id}/members/{user_id}/role",
        summary="Update member role in workspace",
        tags=["Workspaces"],
    )
    @rate_limit(requests_per_minute=30, limiter_name="workspace_member")
    @require_permission("workspace:members:write")
    @handle_errors("update member role")
    @log_request("update member role")
    def _handle_update_member_role(
        self, handler: HTTPRequestHandler, workspace_id: str, user_id: str
    ) -> HandlerResult:
        """Update a member's role in the workspace.

        Request body: {"role": "admin"}

        Only owners can assign admin roles. Admins can assign member roles.
        """
        m = _mod()
        if not m.PROFILES_AVAILABLE:
            return m.error_response("RBAC profiles not available", 503)

        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_WORKSPACE_ADMIN, auth_ctx)
        if rbac_error:
            return rbac_error

        body = self.read_json_body(handler)
        if body is None:
            return m.error_response("Invalid JSON body", 400)

        new_role = body.get("role")
        if not new_role:
            return m.error_response("role is required", 400)

        # Get workspace to check profile and current roles
        manager = self._get_isolation_manager()
        try:
            workspace = self._run_async(
                manager.get_workspace(
                    workspace_id=workspace_id,
                    actor=auth_ctx.user_id,
                )
            )
        except m.AccessDeniedException as e:
            logger.warning("Handler error: %s", e)
            return m.error_response("Permission denied", 403)

        workspace_dict = workspace.to_dict()
        profile_name = workspace_dict.get("rbac_profile", "lite")

        # Validate the role exists in the profile
        try:
            config = m.get_profile_config(profile_name)
        except ValueError:
            return m.error_response(f"Invalid workspace profile: {profile_name}", 400)

        if new_role not in config.roles:
            return m.error_response(
                f"Role '{new_role}' not available in {profile_name} profile. "
                f"Available roles: {config.roles}",
                400,
            )

        # Check if current user can assign this role
        member_roles = workspace_dict.get("member_roles", {})
        assigner_role = member_roles.get(auth_ctx.user_id, "member")
        assignable = m.get_available_roles_for_assignment(profile_name, assigner_role)

        if new_role not in assignable:
            return m.error_response(
                f"You cannot assign the '{new_role}' role. "
                f"Your role ({assigner_role}) can assign: {assignable}",
                403,
            )

        # Prevent removing the last owner
        if member_roles.get(user_id) == "owner" and new_role != "owner":
            owner_count = sum(1 for r in member_roles.values() if r == "owner")
            if owner_count <= 1:
                return m.error_response(
                    "Cannot change role of the last owner. Assign another owner first.",
                    400,
                )

        # Update the role (stored in workspace metadata)
        member_roles[user_id] = new_role

        # Log role change to audit (using MODIFY_PERMISSIONS action)
        audit_log = self._get_audit_log()
        self._run_async(
            audit_log.log(
                action=m.AuditAction.MODIFY_PERMISSIONS,
                actor=m.Actor(id=auth_ctx.user_id, type="user"),
                resource=m.Resource(id=workspace_id, type="workspace", workspace_id=workspace_id),
                outcome=m.AuditOutcome.SUCCESS,
                details={
                    "action_type": "role_change",
                    "target_user_id": user_id,
                    "new_role": new_role,
                    "assigned_by": auth_ctx.user_id,
                },
            )
        )

        logger.info(
            "Updated member role: workspace=%s user=%s role=%s by=%s",
            workspace_id,
            user_id,
            new_role,
            auth_ctx.user_id,
        )

        return m.json_response(
            {
                "message": f"Role updated to '{new_role}' for user {user_id}",
                "workspace_id": workspace_id,
                "user_id": user_id,
                "new_role": new_role,
            }
        )


__all__ = ["WorkspaceMembersMixin"]
