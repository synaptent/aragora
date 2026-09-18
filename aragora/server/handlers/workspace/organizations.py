"""
Organization Management Handlers.

Endpoints:
- GET /api/org/{org_id} - Get organization details
- PUT /api/org/{org_id} - Update organization settings
- GET /api/org/{org_id}/members - List organization members
- POST /api/org/{org_id}/invite - Invite user to organization
- GET /api/org/{org_id}/invitations - List pending invitations
- DELETE /api/org/{org_id}/invitations/{invitation_id} - Revoke invitation
- DELETE /api/org/{org_id}/members/{user_id} - Remove member
- PUT /api/org/{org_id}/members/{user_id}/role - Update member role
- GET /api/invitations/pending - List pending invitations for current user
- POST /api/invitations/{token}/accept - Accept an invitation
- GET /api/user/organizations - List organizations for current user
- POST /api/user/organizations/switch - Switch active organization
- POST /api/user/organizations/default - Set default organization
- DELETE /api/user/organizations/{org_id} - Leave organization
"""

from __future__ import annotations

from typing import Any

import logging
import re
from datetime import datetime, timezone, timedelta

from aragora.billing.models import OrganizationInvitation
from aragora.server.validation.schema import ORG_INVITE_SCHEMA, validate_against_schema

# Audit logging
from aragora.audit.unified import audit_admin, audit_data

# RBAC imports - graceful fallback if not available
AuthorizationContext: Any
check_permission: Any
try:
    from aragora.rbac import AuthorizationContext, check_permission

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False
    AuthorizationContext = None
    check_permission = None

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    log_request,
)
from ..utils.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip
from ..secure import SecureHandler

logger = logging.getLogger(__name__)

# Rate limiter for organization endpoints (30 requests per minute)
_org_limiter = RateLimiter(requests_per_minute=30)

# Role hierarchy (higher number = more permissions)
ROLE_HIERARCHY = {
    "member": 1,
    "admin": 2,
    "owner": 3,
}

# Settings validation limits
MAX_SETTINGS_KEYS = 50  # Maximum number of settings keys
MAX_SETTINGS_VALUE_SIZE = 10000  # 10KB per value


class OrganizationsHandler(SecureHandler):
    """Handler for organization management endpoints.

    Extends SecureHandler for JWT-based authentication, RBAC permission
    enforcement, and security audit logging.
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    # Resource type for audit logging
    RESOURCE_TYPE = "organization"

    # Static ROUTES for SDK audit visibility (actual matching uses regex patterns below)
    ROUTES = [
        "/api/v1/org",
        "/api/v1/org/*",
        "/api/v1/org/*/members",
        "/api/v1/org/*/members/*",
        "/api/v1/org/*/invite",
        "/api/v1/org/*/invitations",
        "/api/v1/org/*/invitations/*",
        "/api/v1/org/*/members/*/role",
        "/api/v1/user/organizations",
        "/api/v1/user/organizations/switch",
        "/api/v1/user/organizations/default",
        "/api/v1/invitations/pending",
        "/api/v1/invitations/*/accept",
        "/api/v1/tenants",
    ]

    # Route patterns (support /api/* and /api/v1/*)
    ORG_PATTERN = re.compile(r"^/api(?:/v1)?/org/([a-zA-Z0-9_-]+)$")
    MEMBERS_PATTERN = re.compile(r"^/api(?:/v1)?/org/([a-zA-Z0-9_-]+)/members$")
    INVITE_PATTERN = re.compile(r"^/api(?:/v1)?/org/([a-zA-Z0-9_-]+)/invite$")
    INVITATIONS_PATTERN = re.compile(r"^/api(?:/v1)?/org/([a-zA-Z0-9_-]+)/invitations$")
    INVITATION_PATTERN = re.compile(
        r"^/api(?:/v1)?/org/([a-zA-Z0-9_-]+)/invitations/([a-zA-Z0-9_-]+)$"
    )
    MEMBER_PATTERN = re.compile(r"^/api(?:/v1)?/org/([a-zA-Z0-9_-]+)/members/([a-zA-Z0-9_-]+)$")
    ROLE_PATTERN = re.compile(r"^/api(?:/v1)?/org/([a-zA-Z0-9_-]+)/members/([a-zA-Z0-9_-]+)/role$")
    USER_ORGS_PATTERN = re.compile(r"^/api(?:/v1)?/user/organizations$")
    USER_ORG_SWITCH_PATTERN = re.compile(r"^/api(?:/v1)?/user/organizations/switch$")
    USER_ORG_DEFAULT_PATTERN = re.compile(r"^/api(?:/v1)?/user/organizations/default$")
    USER_ORG_LEAVE_PATTERN = re.compile(r"^/api(?:/v1)?/user/organizations/([a-zA-Z0-9_-]+)$")
    # User-facing invitation endpoints
    PENDING_INVITATIONS_PATTERN = re.compile(r"^/api(?:/v1)?/invitations/pending$")
    ACCEPT_INVITATION_PATTERN = re.compile(r"^/api(?:/v1)?/invitations/([a-zA-Z0-9_-]+)/accept$")

    # Invitations are now stored in user_store (persistent SQLite storage)

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return (
            self.ORG_PATTERN.match(path) is not None
            or self.MEMBERS_PATTERN.match(path) is not None
            or self.INVITE_PATTERN.match(path) is not None
            or self.INVITATIONS_PATTERN.match(path) is not None
            or self.INVITATION_PATTERN.match(path) is not None
            or self.MEMBER_PATTERN.match(path) is not None
            or self.ROLE_PATTERN.match(path) is not None
            or self.USER_ORGS_PATTERN.match(path) is not None
            or self.USER_ORG_SWITCH_PATTERN.match(path) is not None
            or self.USER_ORG_DEFAULT_PATTERN.match(path) is not None
            or self.USER_ORG_LEAVE_PATTERN.match(path) is not None
            or self.PENDING_INVITATIONS_PATTERN.match(path) is not None
            or self.ACCEPT_INVITATION_PATTERN.match(path) is not None
        )

    def handle(
        self, path: str, query_params: dict[str, Any], handler: Any, method: str = "GET"
    ) -> HandlerResult | None:
        """Route organization requests to appropriate methods."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _org_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for organization endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if hasattr(handler, "command"):
            method = handler.command

        # GET /api/user/organizations
        match = self.USER_ORGS_PATTERN.match(path)
        if match:
            if method == "GET":
                return self._list_user_organizations(handler)
            return error_response("Method not allowed", 405)

        # POST /api/user/organizations/switch
        match = self.USER_ORG_SWITCH_PATTERN.match(path)
        if match:
            if method == "POST":
                return self._switch_user_organization(handler)
            return error_response("Method not allowed", 405)

        # POST /api/user/organizations/default
        match = self.USER_ORG_DEFAULT_PATTERN.match(path)
        if match:
            if method == "POST":
                return self._set_default_organization(handler)
            return error_response("Method not allowed", 405)

        # DELETE /api/user/organizations/{org_id}
        match = self.USER_ORG_LEAVE_PATTERN.match(path)
        if match:
            org_id = match.group(1)
            if method == "DELETE":
                return self._leave_organization(handler, org_id)
            return error_response("Method not allowed", 405)

        # GET/PUT /api/org/{org_id}
        match = self.ORG_PATTERN.match(path)
        if match:
            org_id = match.group(1)
            if method == "GET":
                return self._get_organization(handler, org_id)
            elif method == "PUT":
                return self._update_organization(handler, org_id)
            return error_response("Method not allowed", 405)

        # GET /api/org/{org_id}/members
        match = self.MEMBERS_PATTERN.match(path)
        if match:
            org_id = match.group(1)
            if method == "GET":
                return self._list_members(handler, org_id)
            return error_response("Method not allowed", 405)

        # POST /api/org/{org_id}/invite
        match = self.INVITE_PATTERN.match(path)
        if match:
            org_id = match.group(1)
            if method == "POST":
                return self._invite_member(handler, org_id)
            return error_response("Method not allowed", 405)

        # GET /api/org/{org_id}/invitations - List pending invitations
        match = self.INVITATIONS_PATTERN.match(path)
        if match:
            org_id = match.group(1)
            if method == "GET":
                return self._list_invitations(handler, org_id)
            return error_response("Method not allowed", 405)

        # DELETE /api/org/{org_id}/invitations/{invitation_id} - Revoke invitation
        match = self.INVITATION_PATTERN.match(path)
        if match:
            org_id = match.group(1)
            invitation_id = match.group(2)
            if method == "DELETE":
                return self._revoke_invitation(handler, org_id, invitation_id)
            return error_response("Method not allowed", 405)

        # GET /api/invitations/pending - User's pending invitations
        match = self.PENDING_INVITATIONS_PATTERN.match(path)
        if match:
            if method == "GET":
                return self._get_pending_invitations(handler)
            return error_response("Method not allowed", 405)

        # POST /api/invitations/{token}/accept - Accept invitation
        match = self.ACCEPT_INVITATION_PATTERN.match(path)
        if match:
            token = match.group(1)
            if method == "POST":
                return self._accept_invitation(handler, token)
            return error_response("Method not allowed", 405)

        # DELETE /api/org/{org_id}/members/{user_id}
        match = self.MEMBER_PATTERN.match(path)
        if match:
            org_id = match.group(1)
            user_id = match.group(2)
            if method == "DELETE":
                return self._remove_member(handler, org_id, user_id)
            return error_response("Method not allowed", 405)

        # PUT /api/org/{org_id}/members/{user_id}/role
        match = self.ROLE_PATTERN.match(path)
        if match:
            org_id = match.group(1)
            user_id = match.group(2)
            if method == "PUT":
                return self._update_member_role(handler, org_id, user_id)
            return error_response("Method not allowed", 405)

        return None

    def _get_user_store(self) -> Any:
        """Get user store from context."""
        return self.ctx.get("user_store")

    def _get_current_user(self, handler: Any) -> tuple[Any, Any]:
        """Get authenticated user from request."""
        user_store = self._get_user_store()
        if not user_store:
            return None, None

        from aragora.billing.jwt_auth import extract_user_from_request

        auth_ctx = extract_user_from_request(handler, user_store)

        if not auth_ctx.is_authenticated:
            return None, None

        user = user_store.get_user_by_id(auth_ctx.user_id)
        return user, auth_ctx

    @require_permission("org:read")
    def _list_user_organizations(self, handler: Any) -> HandlerResult:
        """List organizations for the current user (single-org fallback)."""
        user_store = self._get_user_store()
        if not user_store:
            return error_response("User service unavailable", 503)

        user, _auth_ctx = self._get_current_user(handler)
        if not user:
            return error_response("Authentication required", 401)

        if not user.org_id:
            return json_response({"organizations": []})

        org = user_store.get_organization_by_id(user.org_id)
        if not org:
            return json_response({"organizations": []})

        joined_at = user.created_at.isoformat() if getattr(user, "created_at", None) else None

        return json_response(
            {
                "organizations": [
                    {
                        "user_id": user.id,
                        "org_id": org.id,
                        "organization": org.to_dict(),
                        "role": user.role or "member",
                        "is_default": True,
                        "joined_at": joined_at,
                    }
                ]
            }
        )

    @require_permission("org:settings")
    def _switch_user_organization(self, handler: Any) -> HandlerResult:
        """Switch the active organization for the current user."""
        user_store = self._get_user_store()
        if not user_store:
            return error_response("User service unavailable", 503)

        user, _auth_ctx = self._get_current_user(handler)
        if not user:
            return error_response("Authentication required", 401)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        org_id = (body.get("org_id") or "").strip()
        if not org_id:
            return error_response("Organization ID required", 400)

        if user.org_id != org_id:
            return error_response("Not a member of this organization", 403)

        org = user_store.get_organization_by_id(org_id)
        if not org:
            return error_response("Organization not found", 404)

        return json_response({"organization": org.to_dict()})

    @require_permission("org:settings")
    def _set_default_organization(self, handler: Any) -> HandlerResult:
        """Set the default organization for the current user."""
        user_store = self._get_user_store()
        if not user_store:
            return error_response("User service unavailable", 503)

        user, _auth_ctx = self._get_current_user(handler)
        if not user:
            return error_response("Authentication required", 401)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        org_id = (body.get("org_id") or "").strip()
        if not org_id:
            return error_response("Organization ID required", 400)

        if user.org_id != org_id:
            return error_response("Not a member of this organization", 403)

        return json_response({"success": True})

    @require_permission("org:members")
    def _leave_organization(self, handler: Any, org_id: str) -> HandlerResult:
        """Leave an organization (single-org fallback)."""
        user_store = self._get_user_store()
        if not user_store:
            return error_response("User service unavailable", 503)

        user, _auth_ctx = self._get_current_user(handler)
        if not user:
            return error_response("Authentication required", 401)

        if user.org_id != org_id:
            return error_response("Not a member of this organization", 403)

        if user.role == "owner":
            return error_response("Organization owners cannot leave", 400)

        success = user_store.remove_user_from_org(user.id)
        if not success:
            return error_response("Failed to leave organization", 500)

        audit_data(
            user_id=user.id,
            resource_type="organization",
            resource_id=org_id,
            action="delete",
            left_organization=True,
        )

        return json_response({"success": True})

    def _check_org_access(
        self, user: Any, org_id: str, min_role: str = "member"
    ) -> tuple[bool, str]:
        """Check if user has access to organization with minimum role."""
        if not user:
            return False, "Authentication required"
        if user.org_id != org_id:
            return False, "Not a member of this organization"

        user_level = ROLE_HIERARCHY.get(user.role, 0)
        min_level = ROLE_HIERARCHY.get(min_role, 0)

        if user_level < min_level:
            return False, f"Requires {min_role} role or higher"

        return True, ""

    def _get_auth_context(self, handler: Any, user: Any = None) -> AuthorizationContext | None:
        """Build RBAC authorization context from request."""
        if not RBAC_AVAILABLE or AuthorizationContext is None:
            return None

        if user is None:
            user, _ = self._get_current_user(handler)

        if not user:
            return None

        return AuthorizationContext(
            user_id=user.id,
            roles=set([user.role]) if user.role else set(),
            org_id=user.org_id,
        )

    def _check_rbac_permission(
        self, handler: Any, permission_key: str, user: Any = None
    ) -> HandlerResult | None:
        """
        Check RBAC permission.

        Returns None if allowed, or an error response if denied.
        """
        if not RBAC_AVAILABLE:
            if rbac_fail_closed():
                return error_response("Service unavailable: access control module not loaded", 503)
            return None

        auth_ctx = self._get_auth_context(handler, user)
        if not auth_ctx:
            # No auth context - rely on existing auth checks
            return None

        decision = check_permission(auth_ctx, permission_key)
        if not decision.allowed:
            logger.warning(
                "RBAC denied: user=%s permission=%s reason=%s",
                auth_ctx.user_id,
                permission_key,
                decision.reason,
            )
            return error_response(
                "Permission denied",
                403,
            )

        return None

    @require_permission("org:read")
    @handle_errors("get organization")
    @log_request("get organization")
    def _get_organization(self, handler: Any, org_id: str) -> HandlerResult:
        """Get organization details."""
        user, auth_ctx = self._get_current_user(handler)
        has_access, err = self._check_org_access(user, org_id)
        if not has_access:
            return error_response(err, 403 if user else 401)

        user_store = self._get_user_store()
        org = user_store.get_organization_by_id(org_id)
        if not org:
            return error_response("Organization not found", 404)

        # Get member count
        members = user_store.get_org_members(org_id)

        return json_response(
            {
                "organization": {
                    "id": org.id,
                    "name": org.name,
                    "slug": org.slug,
                    "tier": org.tier.value,
                    "owner_id": org.owner_id,
                    "member_count": len(members),
                    "debates_used": org.debates_used_this_month,
                    "debates_limit": org.limits.debates_per_month,
                    "settings": org.settings,
                    "created_at": org.created_at.isoformat(),
                }
            }
        )

    @handle_errors("update organization")
    @log_request("update organization")
    def _update_organization(self, handler: Any, org_id: str) -> HandlerResult:
        """Update organization settings."""
        user, auth_ctx = self._get_current_user(handler)
        has_access, err = self._check_org_access(user, org_id, min_role="admin")
        if not has_access:
            return error_response(err, 403 if user else 401)

        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "organizations.update", user)
        if rbac_error:
            return rbac_error

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        user_store = self._get_user_store()

        # Allowed fields for update
        updates = {}
        if "name" in body:
            name = body["name"].strip()
            if len(name) < 2:
                return error_response("Name must be at least 2 characters", 400)
            if len(name) > 100:
                return error_response("Name must be at most 100 characters", 400)
            updates["name"] = name

        if "settings" in body and isinstance(body["settings"], dict):
            settings = body["settings"]
            # Validate settings size to prevent memory exhaustion
            if len(settings) > MAX_SETTINGS_KEYS:
                return error_response(f"Too many settings keys (max {MAX_SETTINGS_KEYS})", 400)
            for key, value in settings.items():
                if isinstance(value, str) and len(value) > MAX_SETTINGS_VALUE_SIZE:
                    return error_response(f"Settings value too large for key '{key}'", 400)
            updates["settings"] = settings

        if not updates:
            return error_response("No valid fields to update", 400)

        success = user_store.update_organization(org_id, **updates)
        if not success:
            return error_response("Failed to update organization", 500)

        logger.info("Organization %s updated by user %s", org_id, user.id)
        audit_admin(
            admin_id=user.id,
            action="update_organization",
            target_type="organization",
            target_id=org_id,
            changes=list(updates.keys()),
        )

        org = user_store.get_organization_by_id(org_id)
        return json_response(
            {
                "organization": {
                    "id": org.id,
                    "name": org.name,
                    "settings": org.settings,
                },
                "message": "Organization updated",
            }
        )

    @require_permission("org:members")
    @handle_errors("list members")
    @log_request("list members")
    def _list_members(self, handler: Any, org_id: str) -> HandlerResult:
        """List organization members."""
        user, auth_ctx = self._get_current_user(handler)
        has_access, err = self._check_org_access(user, org_id)
        if not has_access:
            return error_response(err, 403 if user else 401)

        user_store = self._get_user_store()
        members = user_store.get_org_members(org_id)

        return json_response(
            {
                "members": [
                    {
                        "id": m.id,
                        "email": m.email,
                        "name": m.name,
                        "role": m.role,
                        "is_active": m.is_active,
                        "created_at": m.created_at.isoformat(),
                        "last_login_at": m.last_login_at.isoformat() if m.last_login_at else None,
                    }
                    for m in members
                ],
                "count": len(members),
            }
        )

    @handle_errors("invite member")
    @log_request("invite member")
    def _invite_member(self, handler: Any, org_id: str) -> HandlerResult:
        """Invite a user to the organization."""
        user, auth_ctx = self._get_current_user(handler)
        has_access, err = self._check_org_access(user, org_id, min_role="admin")
        if not has_access:
            return error_response(err, 403 if user else 401)

        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "organizations.invite", user)
        if rbac_error:
            return rbac_error

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        # Schema validation for input sanitization
        validation_result = validate_against_schema(body, ORG_INVITE_SCHEMA)
        if not validation_result.is_valid:
            return error_response(validation_result.error, 400)

        email = body.get("email", "").strip().lower()
        role = body.get("role", "member")

        if not email:
            return error_response("Email is required", 400)

        if role not in ["member", "admin"]:
            return error_response("Invalid role. Must be 'member' or 'admin'", 400)

        # Check org limits
        user_store = self._get_user_store()
        org = user_store.get_organization_by_id(org_id)
        if not org:
            return error_response("Organization not found", 404)

        members = user_store.get_org_members(org_id)
        if len(members) >= org.limits.users_per_org:
            return error_response(
                f"Organization member limit reached ({org.limits.users_per_org}). "
                "Upgrade your plan to add more members.",
                403,
            )

        # Check if user exists
        existing_user = user_store.get_user_by_email(email)

        if existing_user:
            if existing_user.org_id == org_id:
                return error_response("User is already a member of this organization", 400)

            if existing_user.org_id:
                return error_response(
                    "User is already a member of another organization. "
                    "They must leave their current organization first.",
                    400,
                )

            # Add existing user to org
            success = user_store.add_user_to_org(existing_user.id, org_id, role)
            if not success:
                return error_response("Failed to add user to organization", 500)

            logger.info("User %s added to org %s by %s", existing_user.id, org_id, user.id)
            audit_admin(
                admin_id=user.id,
                action="add_member",
                target_type="organization_member",
                target_id=existing_user.id,
                org_id=org_id,
                role=role,
            )

            return json_response(
                {
                    "message": f"User {email} added to organization",
                    "user_id": existing_user.id,
                    "role": role,
                }
            )

        # User doesn't exist - create invitation
        # Check if there's already a pending invitation for this email
        existing_invite = self._get_invitation_by_email(org_id, email)
        if existing_invite and existing_invite.is_pending:
            return error_response(
                f"An invitation has already been sent to {email}. "
                "It expires on " + existing_invite.expires_at.strftime("%Y-%m-%d"),
                400,
            )

        # Create new invitation
        invitation = OrganizationInvitation(
            org_id=org_id,
            email=email,
            role=role,
            invited_by=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )

        # Store invitation in persistent database
        user_store.create_invitation(invitation)

        logger.info(
            "Invitation created: %s invited to org %s by %s (token=%s...)",
            email,
            org_id,
            user.id,
            invitation.token[:8],
        )
        audit_admin(
            admin_id=user.id,
            action="create_invitation",
            target_type="invitation",
            target_id=invitation.id,
            org_id=org_id,
            invited_email=email,
            role=role,
        )

        return json_response(
            {
                "message": f"Invitation sent to {email}",
                "invitation_id": invitation.id,
                "expires_at": invitation.expires_at.isoformat(),
                "invite_link": f"/invite/{invitation.token}",
            },
            status=201,
        )

    @handle_errors("remove member")
    @log_request("remove member")
    def _remove_member(self, handler: Any, org_id: str, target_user_id: str) -> HandlerResult:
        """Remove a member from the organization."""
        user, auth_ctx = self._get_current_user(handler)
        has_access, err = self._check_org_access(user, org_id, min_role="admin")
        if not has_access:
            return error_response(err, 403 if user else 401)

        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "organizations.members.remove", user)
        if rbac_error:
            return rbac_error

        user_store = self._get_user_store()

        # Get target user
        target_user = user_store.get_user_by_id(target_user_id)
        if not target_user:
            return error_response("User not found", 404)

        if target_user.org_id != org_id:
            return error_response("User is not a member of this organization", 400)

        # Cannot remove owner
        if target_user.role == "owner":
            return error_response(
                "Cannot remove the organization owner. Transfer ownership first.", 403
            )

        # Cannot remove self (use leave instead)
        if target_user.id == user.id:
            return error_response(
                "Cannot remove yourself. Use the leave organization option instead.", 400
            )

        # Only owner can remove admins
        if target_user.role == "admin" and user.role != "owner":
            return error_response("Only the owner can remove admin members", 403)

        # Remove from org
        success = user_store.remove_user_from_org(target_user_id)
        if not success:
            return error_response("Failed to remove user from organization", 500)

        logger.info("User %s removed from org %s by %s", target_user_id, org_id, user.id)
        audit_admin(
            admin_id=user.id,
            action="remove_member",
            target_type="organization_member",
            target_id=target_user_id,
            org_id=org_id,
        )

        return json_response(
            {
                "message": "User removed from organization",
                "user_id": target_user_id,
            }
        )

    @handle_errors("update member role")
    @log_request("update member role")
    def _update_member_role(self, handler: Any, org_id: str, target_user_id: str) -> HandlerResult:
        """Update a member's role in the organization."""
        user, auth_ctx = self._get_current_user(handler)
        has_access, err = self._check_org_access(user, org_id, min_role="owner")
        if not has_access:
            return error_response(err, 403 if user else 401)

        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "organizations.members.update_role", user)
        if rbac_error:
            return rbac_error

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        new_role = body.get("role", "").lower()
        if new_role not in ["member", "admin"]:
            return error_response("Invalid role. Must be 'member' or 'admin'", 400)

        user_store = self._get_user_store()

        # Get target user
        target_user = user_store.get_user_by_id(target_user_id)
        if not target_user:
            return error_response("User not found", 404)

        if target_user.org_id != org_id:
            return error_response("User is not a member of this organization", 400)

        # Cannot change owner's role
        if target_user.role == "owner":
            return error_response(
                "Cannot change the owner's role. Transfer ownership instead.", 403
            )

        # Update role
        success = user_store.update_user(target_user_id, role=new_role)
        if not success:
            return error_response("Failed to update user role", 500)

        logger.info(
            "User %s role changed to %s in org %s by %s", target_user_id, new_role, org_id, user.id
        )
        audit_admin(
            admin_id=user.id,
            action="update_member_role",
            target_type="organization_member",
            target_id=target_user_id,
            org_id=org_id,
            old_role=target_user.role,
            new_role=new_role,
        )

        return json_response(
            {
                "message": f"User role updated to {new_role}",
                "user_id": target_user_id,
                "role": new_role,
            }
        )

    # =========================================================================
    # Invitation Helper Methods (now using persistent storage via user_store)
    # =========================================================================

    def _get_invitation_by_email(self, org_id: str, email: str) -> OrganizationInvitation | None:
        """Find a pending invitation by org and email."""
        user_store = self._get_user_store()
        if not user_store:
            return None
        return user_store.get_invitation_by_email(org_id, email)

    def _get_invitation_by_token(self, token: str) -> OrganizationInvitation | None:
        """Find an invitation by token."""
        user_store = self._get_user_store()
        if not user_store:
            return None
        return user_store.get_invitation_by_token(token)

    def _get_invitations_by_email(self, email: str) -> list[OrganizationInvitation]:
        """Get all pending invitations for an email address."""
        user_store = self._get_user_store()
        if not user_store:
            return []
        return user_store.get_pending_invitations_by_email(email)

    def _get_invitations_for_org(self, org_id: str) -> list[OrganizationInvitation]:
        """Get all invitations for an organization."""
        user_store = self._get_user_store()
        if not user_store:
            return []
        return user_store.get_invitations_for_org(org_id)

    # =========================================================================
    # Invitation Endpoints
    # =========================================================================

    @handle_errors("list invitations")
    @require_permission("org:invite")
    @log_request("list invitations")
    def _list_invitations(self, handler: Any, org_id: str) -> HandlerResult:
        """List all invitations for an organization."""
        user, auth_ctx = self._get_current_user(handler)
        has_access, err = self._check_org_access(user, org_id, min_role="admin")
        if not has_access:
            return error_response(err, 403 if user else 401)

        user_store = self._get_user_store()
        if not user_store:
            return error_response("Service unavailable", 503)

        # Clean up expired invitations in database
        user_store.cleanup_expired_invitations()

        invitations = self._get_invitations_for_org(org_id)

        return json_response(
            {
                "invitations": [inv.to_dict() for inv in invitations],
                "count": len(invitations),
                "pending_count": sum(1 for inv in invitations if inv.is_pending),
            }
        )

    @handle_errors("revoke invitation")
    @log_request("revoke invitation")
    def _revoke_invitation(self, handler: Any, org_id: str, invitation_id: str) -> HandlerResult:
        """Revoke a pending invitation."""
        user, auth_ctx = self._get_current_user(handler)
        has_access, err = self._check_org_access(user, org_id, min_role="admin")
        if not has_access:
            return error_response(err, 403 if user else 401)

        # RBAC permission check
        rbac_error = self._check_rbac_permission(handler, "organizations.invitations.revoke", user)
        if rbac_error:
            return rbac_error

        user_store = self._get_user_store()
        if not user_store:
            return error_response("Service unavailable", 503)

        invitation = user_store.get_invitation_by_id(invitation_id)
        if not invitation:
            return error_response("Invitation not found", 404)

        if invitation.org_id != org_id:
            return error_response("Invitation not found", 404)

        if not invitation.is_pending:
            return error_response(f"Cannot revoke invitation (status: {invitation.status})", 400)

        # Update status to revoked in database
        user_store.update_invitation_status(invitation_id, "revoked")

        logger.info("Invitation %s revoked by %s", invitation_id, user.id)
        audit_admin(
            admin_id=user.id,
            action="revoke_invitation",
            target_type="invitation",
            target_id=invitation_id,
            org_id=org_id,
            invited_email=invitation.email,
        )

        return json_response(
            {
                "message": "Invitation revoked",
                "invitation_id": invitation_id,
            }
        )

    @handle_errors("get pending invitations")
    @require_permission("org:read")
    @log_request("get pending invitations")
    def _get_pending_invitations(self, handler: Any) -> HandlerResult:
        """Get pending invitations for the authenticated user."""
        user, auth_ctx = self._get_current_user(handler)
        if not user:
            return error_response("Authentication required", 401)

        invitations = self._get_invitations_by_email(user.email)

        # Get org names for the invitations
        user_store = self._get_user_store()
        invitation_data = []
        for inv in invitations:
            org = user_store.get_organization_by_id(inv.org_id) if user_store else None
            invitation_data.append(
                {
                    **inv.to_dict(),
                    "org_name": org.name if org else "Unknown Organization",
                }
            )

        return json_response(
            {
                "invitations": invitation_data,
                "count": len(invitation_data),
            }
        )

    @handle_errors("accept invitation")
    @require_permission("org:read")
    @log_request("accept invitation")
    def _accept_invitation(self, handler: Any, token: str) -> HandlerResult:
        """Accept an organization invitation."""
        user, auth_ctx = self._get_current_user(handler)
        if not user:
            return error_response("Authentication required", 401)

        invitation = self._get_invitation_by_token(token)
        if not invitation:
            return error_response("Invitation not found or expired", 404)

        if not invitation.is_pending:
            return error_response(
                f"Invitation is no longer valid (status: {invitation.status})", 400
            )

        # Verify the invitation is for this user's email
        if invitation.email.lower() != user.email.lower():
            return error_response("This invitation was sent to a different email address", 403)

        # Check if user is already in an organization
        if user.org_id:
            return error_response(
                "You are already a member of an organization. "
                "Leave your current organization first.",
                400,
            )

        # Check org limits
        user_store = self._get_user_store()
        if not user_store:
            return error_response("Service unavailable", 503)

        org = user_store.get_organization_by_id(invitation.org_id)
        if not org:
            return error_response("Organization no longer exists", 404)

        members = user_store.get_org_members(invitation.org_id)
        if len(members) >= org.limits.users_per_org:
            return error_response("Organization has reached its member limit", 403)

        # Add user to organization
        success = user_store.add_user_to_org(user.id, invitation.org_id, invitation.role)
        if not success:
            return error_response("Failed to join organization", 500)

        # Mark invitation as accepted in database
        user_store.update_invitation_status(
            invitation.id, "accepted", accepted_at=datetime.now(timezone.utc)
        )

        logger.info(
            "User %s accepted invitation to org %s with role %s",
            user.id,
            invitation.org_id,
            invitation.role,
        )
        audit_data(
            user_id=user.id,
            resource_type="organization",
            resource_id=invitation.org_id,
            action="create",
            membership_role=invitation.role,
            invitation_id=invitation.id,
        )

        return json_response(
            {
                "message": f"Successfully joined {org.name}",
                "organization": {
                    "id": org.id,
                    "name": org.name,
                    "slug": org.slug,
                },
                "role": invitation.role,
            }
        )


__all__ = ["OrganizationsHandler"]
