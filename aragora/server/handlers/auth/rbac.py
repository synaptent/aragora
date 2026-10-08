"""
RBAC Management Endpoints.

Provides REST API endpoints for managing roles, permissions, and assignments:
- GET    /api/v1/rbac/permissions          - List all permissions
- GET    /api/v1/rbac/permissions/:key      - Get a specific permission
- GET    /api/v1/rbac/roles                - List all roles
- GET    /api/v1/rbac/roles/:name          - Get a specific role
- POST   /api/v1/rbac/roles                - Create a custom role
- PUT    /api/v1/rbac/roles/:name          - Update a custom role
- DELETE /api/v1/rbac/roles/:name          - Delete a custom role
- GET    /api/v1/rbac/assignments          - List role assignments
- POST   /api/v1/rbac/assignments          - Create a role assignment
- DELETE /api/v1/rbac/assignments/:id      - Delete a role assignment
- POST   /api/v1/rbac/check               - Check a permission
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from aragora.rbac.checker import get_permission_checker
from aragora.rbac.decorators import require_permission
from aragora.rbac.defaults import (
    SYSTEM_PERMISSIONS,
    SYSTEM_ROLES,
    ROLE_HIERARCHY,
    get_permission,
    get_role,
    get_role_permissions,
    create_custom_role,
)
from aragora.rbac.models import (
    AuthorizationContext,
    Permission,
    Role,
    RoleAssignment,
)
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    validate_path_segment,
)

logger = logging.getLogger(__name__)


def _permission_to_dict(perm: Permission) -> dict[str, Any]:
    """Serialize a Permission to a JSON-safe dict."""
    return {
        "id": perm.id,
        "name": perm.name,
        "key": perm.key,
        "resource": perm.resource.value,
        "action": perm.action.value,
        "description": perm.description,
    }


def _role_to_dict(role: Role) -> dict[str, Any]:
    """Serialize a Role to a JSON-safe dict."""
    return {
        "id": role.id,
        "name": role.name,
        "display_name": role.display_name,
        "description": role.description,
        "permissions": sorted(role.permissions),
        "parent_roles": role.parent_roles,
        "is_system": role.is_system,
        "is_custom": role.is_custom,
        "org_id": role.org_id,
        "priority": role.priority,
    }


def _assignment_to_dict(assignment: RoleAssignment) -> dict[str, Any]:
    """Serialize a RoleAssignment to a JSON-safe dict."""
    return {
        "id": assignment.id,
        "user_id": assignment.user_id,
        "role_id": assignment.role_id,
        "org_id": assignment.org_id,
        "assigned_by": assignment.assigned_by,
        "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None,
        "expires_at": assignment.expires_at.isoformat() if assignment.expires_at else None,
        "is_active": assignment.is_active,
        "is_valid": assignment.is_valid,
    }


class RBACHandler(BaseHandler):
    """
    HTTP handler for RBAC management endpoints.

    Provides CRUD operations for permissions, roles, and role assignments,
    as well as permission checking.
    """

    ROUTES = [
        "/api/v1/rbac/permissions",
        "/api/v1/rbac/permissions/*",
        "/api/v1/rbac/roles",
        "/api/v1/rbac/roles/*",
        "/api/v1/rbac/assignments",
        "/api/v1/rbac/assignments/*",
        "/api/v1/rbac/check",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if not path.startswith("/api/v1/rbac/"):
            return False
        segment = path[len("/api/v1/rbac/") :]
        if segment.startswith("permissions"):
            return method == "GET"
        if segment.startswith("roles"):
            return method in ("GET", "POST", "PUT", "DELETE")
        if segment.startswith("assignments"):
            return method in ("GET", "POST", "DELETE")
        if segment == "check":
            return method == "POST"
        return False

    async def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Route request to appropriate handler method."""
        method: str = getattr(handler, "command", "GET") if handler else "GET"
        body: dict[str, Any] = (self.read_json_body(handler) or {}) if handler else {}
        query_params = query_params or {}

        try:
            # Permissions endpoints
            if path == "/api/v1/rbac/permissions" and method == "GET":
                return self._list_permissions(query_params)

            if path.startswith("/api/v1/rbac/permissions/") and method == "GET":
                key = path[len("/api/v1/rbac/permissions/") :]
                return self._get_permission(key)

            # Roles endpoints
            if path == "/api/v1/rbac/roles" and method == "GET":
                return self._list_roles(query_params)

            if path == "/api/v1/rbac/roles" and method == "POST":
                return self._create_role(body)

            if path.startswith("/api/v1/rbac/roles/"):
                role_name = path[len("/api/v1/rbac/roles/") :]
                if not role_name:
                    return error_response("Role name required", 400)
                if method == "GET":
                    return self._get_role(role_name)
                if method == "PUT":
                    return self._update_role(role_name, body)
                if method == "DELETE":
                    return self._delete_role(role_name)

            # Assignments endpoints
            if path == "/api/v1/rbac/assignments" and method == "GET":
                return self._list_assignments(query_params)

            if path == "/api/v1/rbac/assignments" and method == "POST":
                return self._create_assignment(body)

            if path.startswith("/api/v1/rbac/assignments/") and method == "DELETE":
                assignment_id = path[len("/api/v1/rbac/assignments/") :]
                return self._delete_assignment(assignment_id)

            # Permission check endpoint
            if path == "/api/v1/rbac/check" and method == "POST":
                return self._check_permission(body)

            return error_response("Not found", 404)

        except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
            logger.exception("Error handling RBAC request: %s", e)
            return error_response("Internal server error", 500)

    # -------------------------------------------------------------------------
    # Permission endpoints
    # -------------------------------------------------------------------------

    @require_permission("role.read")
    @handle_errors("list permissions")
    def _list_permissions(self, query_params: dict[str, Any]) -> HandlerResult:
        """List all system permissions with optional filtering."""
        resource_filter = query_params.get("resource")
        action_filter = query_params.get("action")

        # Deduplicate: only use dot-notation keys (skip colon aliases)
        seen_keys: set[str] = set()
        permissions: list[dict[str, Any]] = []

        for key, perm in sorted(SYSTEM_PERMISSIONS.items()):
            # Skip colon-format aliases
            if ":" in key:
                continue
            if perm.key in seen_keys:
                continue
            seen_keys.add(perm.key)

            if resource_filter and perm.resource.value != resource_filter:
                continue
            if action_filter and perm.action.value != action_filter:
                continue

            permissions.append(_permission_to_dict(perm))

        return json_response(
            {
                "permissions": permissions,
                "total": len(permissions),
            }
        )

    @require_permission("role.read")
    @handle_errors("get permission")
    def _get_permission(self, key: str) -> HandlerResult:
        """Get a specific permission by key."""
        if not key:
            return error_response("Permission key required", 400)

        perm = get_permission(key)
        # Try dot notation if not found
        if perm is None and ":" in key:
            perm = get_permission(key.replace(":", "."))
        if perm is None and "." in key:
            perm = get_permission(key.replace(".", ":"))

        if perm is None:
            return error_response(f"Permission not found: {key}", 404)

        return json_response({"permission": _permission_to_dict(perm)})

    # -------------------------------------------------------------------------
    # Role endpoints
    # -------------------------------------------------------------------------

    @require_permission("role.read")
    @handle_errors("list roles")
    def _list_roles(self, query_params: dict[str, Any]) -> HandlerResult:
        """List all roles (system and custom)."""
        include_permissions = query_params.get("include_permissions", "false").lower() == "true"
        checker = get_permission_checker()

        roles: list[dict[str, Any]] = []

        # System roles
        for name, role in sorted(SYSTEM_ROLES.items()):
            role_dict = _role_to_dict(role)
            if include_permissions:
                resolved = get_role_permissions(name, include_inherited=True)
                role_dict["resolved_permissions"] = sorted(resolved)
            role_dict["hierarchy"] = ROLE_HIERARCHY.get(name, [])
            roles.append(role_dict)

        # Custom roles from checker
        for key, custom_data in checker._custom_roles.items():
            roles.append(
                {
                    "id": key,
                    "name": custom_data.get("name", key),
                    "display_name": custom_data.get("display_name", key),
                    "description": custom_data.get("description", ""),
                    "permissions": sorted(custom_data.get("permissions", set())),
                    "parent_roles": custom_data.get("parent_roles", []),
                    "is_system": False,
                    "is_custom": True,
                    "org_id": custom_data.get("org_id"),
                    "priority": custom_data.get("priority", 0),
                }
            )

        return json_response(
            {
                "roles": roles,
                "total": len(roles),
            }
        )

    @require_permission("role.read")
    @handle_errors("get role")
    def _get_role(self, name: str) -> HandlerResult:
        """Get a specific role by name."""
        role = get_role(name)
        if role is None:
            # Check custom roles
            checker = get_permission_checker()
            for key, custom_data in checker._custom_roles.items():
                if custom_data.get("name") == name or key.endswith(f":{name}"):
                    return json_response(
                        {
                            "role": {
                                "id": key,
                                "name": custom_data.get("name", name),
                                "display_name": custom_data.get("display_name", name),
                                "description": custom_data.get("description", ""),
                                "permissions": sorted(custom_data.get("permissions", set())),
                                "parent_roles": custom_data.get("parent_roles", []),
                                "is_system": False,
                                "is_custom": True,
                                "org_id": custom_data.get("org_id"),
                                "priority": custom_data.get("priority", 0),
                            },
                        }
                    )
            return error_response(f"Role not found: {name}", 404)

        role_dict = _role_to_dict(role)
        role_dict["resolved_permissions"] = sorted(
            get_role_permissions(name, include_inherited=True)
        )
        role_dict["hierarchy"] = ROLE_HIERARCHY.get(name, [])

        return json_response({"role": role_dict})

    @require_permission("role.create")
    @handle_errors("create role")
    def _create_role(self, body: dict[str, Any]) -> HandlerResult:
        """Create a new custom role."""
        name = body.get("name")
        if not name or not isinstance(name, str):
            return error_response("Role name is required", 400)

        # Validate name format
        if not validate_path_segment(name, "role_name"):
            return error_response("Invalid role name format", 400)

        # Check for duplicates
        if get_role(name) is not None:
            return error_response(f"Role already exists: {name}", 409)

        org_id = body.get("org_id", "default")
        display_name = body.get("display_name", name.replace("_", " ").title())
        description = body.get("description", "")
        permission_keys = set(body.get("permissions", []))
        base_role = body.get("base_role")

        try:
            role = create_custom_role(
                name=name,
                display_name=display_name,
                description=description,
                permission_keys=permission_keys,
                org_id=org_id,
                base_role=base_role,
            )
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)

        # Register in the checker's custom roles
        checker = get_permission_checker()
        checker._custom_roles[f"{org_id}:{name}"] = {
            "name": name,
            "display_name": display_name,
            "description": description,
            "permissions": role.permissions,
            "parent_roles": role.parent_roles,
            "org_id": org_id,
            "priority": role.priority,
        }

        logger.info("Created custom role: %s for org: %s", name, org_id)

        return json_response({"role": _role_to_dict(role)}, status=201)

    @require_permission("role.update")
    @handle_errors("update role")
    def _update_role(self, name: str, body: dict[str, Any]) -> HandlerResult:
        """Update an existing custom role."""
        # System roles cannot be modified
        system_role = get_role(name)
        if system_role is not None and system_role.is_system:
            return error_response("Cannot modify system roles", 403)

        checker = get_permission_checker()

        # Find the custom role
        target_key = None
        for key, custom_data in checker._custom_roles.items():
            if custom_data.get("name") == name or key.endswith(f":{name}"):
                target_key = key
                break

        if target_key is None:
            return error_response(f"Custom role not found: {name}", 404)

        existing = checker._custom_roles[target_key]

        # Apply updates
        if "display_name" in body:
            existing["display_name"] = body["display_name"]
        if "description" in body:
            existing["description"] = body["description"]
        if "permissions" in body:
            new_perms = set(body["permissions"])
            # Validate permissions exist
            for perm_key in new_perms:
                if perm_key not in SYSTEM_PERMISSIONS and not perm_key.endswith(".*"):
                    return error_response(f"Unknown permission: {perm_key}", 400)
            existing["permissions"] = new_perms
        if "base_role" in body:
            base = body["base_role"]
            if base and get_role(base) is not None:
                existing["parent_roles"] = [base]
                # Merge base permissions
                base_perms = get_role_permissions(base, include_inherited=True)
                existing["permissions"] = existing.get("permissions", set()) | base_perms

        # Clear cache since role permissions changed
        checker.clear_cache()

        logger.info("Updated custom role: %s", name)

        return json_response(
            {
                "role": {
                    "id": target_key,
                    "name": existing.get("name", name),
                    "display_name": existing.get("display_name", name),
                    "description": existing.get("description", ""),
                    "permissions": sorted(existing.get("permissions", set())),
                    "parent_roles": existing.get("parent_roles", []),
                    "is_system": False,
                    "is_custom": True,
                    "org_id": existing.get("org_id"),
                    "priority": existing.get("priority", 0),
                },
            }
        )

    @require_permission("role.delete")
    @handle_errors("delete role")
    def _delete_role(self, name: str) -> HandlerResult:
        """Delete a custom role."""
        # System roles cannot be deleted
        system_role = get_role(name)
        if system_role is not None and system_role.is_system:
            return error_response("Cannot delete system roles", 403)

        checker = get_permission_checker()

        # Find and remove the custom role
        target_key = None
        for key, custom_data in checker._custom_roles.items():
            if custom_data.get("name") == name or key.endswith(f":{name}"):
                target_key = key
                break

        if target_key is None:
            return error_response(f"Custom role not found: {name}", 404)

        del checker._custom_roles[target_key]
        checker.clear_cache()

        logger.info("Deleted custom role: %s", name)

        return json_response({"deleted": True, "role": name})

    # -------------------------------------------------------------------------
    # Assignment endpoints
    # -------------------------------------------------------------------------

    @require_permission("role.read")
    @handle_errors("list assignments")
    def _list_assignments(self, query_params: dict[str, Any]) -> HandlerResult:
        """List role assignments with optional filtering."""
        user_id_filter = query_params.get("user_id")
        role_id_filter = query_params.get("role_id")
        org_id_filter = query_params.get("org_id")

        checker = get_permission_checker()
        assignments: list[dict[str, Any]] = []

        for uid, user_assignments in checker._role_assignments.items():
            if user_id_filter and uid != user_id_filter:
                continue
            for assignment in user_assignments:
                if role_id_filter and assignment.role_id != role_id_filter:
                    continue
                if org_id_filter and assignment.org_id != org_id_filter:
                    continue
                assignments.append(_assignment_to_dict(assignment))

        return json_response(
            {
                "assignments": assignments,
                "total": len(assignments),
            }
        )

    @require_permission("role.create")
    @handle_errors("create assignment")
    def _create_assignment(self, body: dict[str, Any]) -> HandlerResult:
        """Create a new role assignment."""
        user_id = body.get("user_id")
        role_id = body.get("role_id")

        if not user_id or not isinstance(user_id, str):
            return error_response("user_id is required", 400)
        if not role_id or not isinstance(role_id, str):
            return error_response("role_id is required", 400)

        # Validate role exists (system or custom)
        role = get_role(role_id)
        checker = get_permission_checker()
        if role is None:
            # Check custom roles
            found = False
            for key in checker._custom_roles:
                if key.endswith(f":{role_id}"):
                    found = True
                    break
            if not found:
                return error_response(f"Role not found: {role_id}", 404)

        org_id = body.get("org_id")
        assigned_by = body.get("assigned_by")
        expires_at_str = body.get("expires_at")

        expires_at = None
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                return error_response("Invalid expires_at format (use ISO 8601)", 400)

        assignment = RoleAssignment(
            id=str(uuid4()),
            user_id=user_id,
            role_id=role_id,
            org_id=org_id,
            assigned_by=assigned_by,
            assigned_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            is_active=True,
        )

        checker.add_role_assignment(assignment)
        checker.clear_cache(user_id)

        logger.info("Created role assignment: %s -> %s", role_id, user_id)

        return json_response({"assignment": _assignment_to_dict(assignment)}, status=201)

    @require_permission("role.delete")
    @handle_errors("delete assignment")
    def _delete_assignment(self, assignment_id: str) -> HandlerResult:
        """Delete a role assignment by ID."""
        if not assignment_id:
            return error_response("Assignment ID required", 400)

        checker = get_permission_checker()

        # Find the assignment
        for uid, user_assignments in checker._role_assignments.items():
            for assignment in user_assignments:
                if assignment.id == assignment_id:
                    checker.remove_role_assignment(uid, assignment.role_id, assignment.org_id)
                    checker.clear_cache(uid)

                    logger.info("Deleted role assignment: %s -> %s", assignment.role_id, uid)

                    return json_response(
                        {
                            "deleted": True,
                            "assignment_id": assignment_id,
                        }
                    )

        return error_response(f"Assignment not found: {assignment_id}", 404)

    # -------------------------------------------------------------------------
    # Permission check endpoint
    # -------------------------------------------------------------------------

    @handle_errors("check permission")
    def _check_permission(self, body: dict[str, Any]) -> HandlerResult:
        """Check if a user has a specific permission.

        This endpoint does not itself require RBAC (it is the mechanism
        for checking RBAC), but callers should be authenticated.
        """
        user_id = body.get("user_id")
        permission_key = body.get("permission")
        resource_id = body.get("resource_id")
        roles = body.get("roles", [])
        org_id = body.get("org_id")

        if not user_id or not isinstance(user_id, str):
            return error_response("user_id is required", 400)
        if not permission_key or not isinstance(permission_key, str):
            return error_response("permission is required", 400)

        context = AuthorizationContext(
            user_id=user_id,
            org_id=org_id,
            roles=set(roles) if roles else set(),
        )

        checker = get_permission_checker()

        # If no roles provided, resolve from assignments
        if not context.roles:
            context = AuthorizationContext(
                user_id=user_id,
                org_id=org_id,
                roles=checker.get_user_roles(user_id, org_id),
            )

        decision = checker.check_permission(context, permission_key, resource_id)

        return json_response(
            {
                "allowed": decision.allowed,
                "reason": decision.reason,
                "permission": decision.permission_key,
                "resource_id": decision.resource_id,
                "cached": decision.cached,
            }
        )
