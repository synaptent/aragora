# mypy: disable-error-code="attr-defined"
"""
Workspace Invite Management Mixin.

Provides handler methods for creating, listing, canceling, and accepting
workspace invites. Used as a mixin class by WorkspaceHandler in
workspace_module.py.

Stability: STABLE
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, TYPE_CHECKING

from aragora.events.handler_events import emit_handler_event, CREATED, COMPLETED
from aragora.server.handlers.base import handle_errors, log_request
from aragora.server.handlers.openapi_decorator import api_endpoint
from aragora.server.handlers.utils.lazy_stores import LazyStore
from aragora.server.handlers.utils.rate_limit import rate_limit

if TYPE_CHECKING:
    from aragora.protocols import HTTPRequestHandler
    from aragora.server.handlers.base import HandlerResult

logger = logging.getLogger(__name__)


def _mod() -> Any:
    """Lazy import of workspace_module to avoid circular imports and respect patches."""
    import aragora.server.handlers.workspace.workspace_module as m

    return m


class InviteStatus(str, Enum):
    """Status of a workspace invite."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    CANCELED = "canceled"


@dataclass
class WorkspaceInvite:
    """A workspace invite record."""

    id: str
    workspace_id: str
    email: str
    role: str
    token: str
    status: InviteStatus
    created_by: str
    created_at: datetime
    expires_at: datetime
    accepted_by: str | None = None
    accepted_at: datetime | None = None

    def is_valid(self) -> bool:
        """Check if the invite is still valid (pending and not expired)."""
        if self.status != InviteStatus.PENDING:
            return False
        return datetime.now(timezone.utc) < self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "email": self.email,
            "role": self.role,
            "status": self.status.value,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "accepted_by": self.accepted_by,
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
        }


class InviteStore:
    """In-memory store for workspace invites.

    In production, this would be backed by a database.
    """

    def __init__(self) -> None:
        self._invites: dict[str, WorkspaceInvite] = {}
        self._tokens: dict[str, str] = {}  # token -> invite_id

    def create(
        self,
        workspace_id: str,
        email: str,
        role: str,
        created_by: str,
        expires_in_days: int = 7,
    ) -> WorkspaceInvite:
        """Create a new invite."""
        invite_id = f"inv_{secrets.token_hex(8)}"
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)

        invite = WorkspaceInvite(
            id=invite_id,
            workspace_id=workspace_id,
            email=email.lower().strip(),
            role=role,
            token=token,
            status=InviteStatus.PENDING,
            created_by=created_by,
            created_at=now,
            expires_at=now + timedelta(days=expires_in_days),
        )

        self._invites[invite_id] = invite
        self._tokens[token] = invite_id
        return invite

    def get(self, invite_id: str) -> WorkspaceInvite | None:
        """Get an invite by ID."""
        return self._invites.get(invite_id)

    def get_by_token(self, token: str) -> WorkspaceInvite | None:
        """Get an invite by token."""
        invite_id = self._tokens.get(token)
        if invite_id:
            return self._invites.get(invite_id)
        return None

    def list_for_workspace(
        self, workspace_id: str, status: InviteStatus | None = None
    ) -> list[WorkspaceInvite]:
        """List invites for a workspace, optionally filtered by status."""
        invites = [inv for inv in self._invites.values() if inv.workspace_id == workspace_id]
        if status:
            invites = [inv for inv in invites if inv.status == status]
        return sorted(invites, key=lambda x: x.created_at, reverse=True)

    def update_status(
        self,
        invite_id: str,
        status: InviteStatus,
        accepted_by: str | None = None,
    ) -> bool:
        """Update an invite's status."""
        invite = self._invites.get(invite_id)
        if not invite:
            return False

        invite.status = status
        if accepted_by:
            invite.accepted_by = accepted_by
            invite.accepted_at = datetime.now(timezone.utc)
        return True

    def delete(self, invite_id: str) -> bool:
        """Delete an invite."""
        invite = self._invites.get(invite_id)
        if not invite:
            return False

        if invite.token in self._tokens:
            del self._tokens[invite.token]
        del self._invites[invite_id]
        return True

    def check_existing(self, workspace_id: str, email: str) -> WorkspaceInvite | None:
        """Check if there's an existing pending invite for this email."""
        email_normalized = email.lower().strip()
        for invite in self._invites.values():
            if (
                invite.workspace_id == workspace_id
                and invite.email == email_normalized
                and invite.status == InviteStatus.PENDING
                and invite.is_valid()
            ):
                return invite
        return None


# Global invite store instance (thread-safe lazy init)
_invite_store_lazy = LazyStore(
    factory=InviteStore,
    store_name="invite_store",
    logger_context="WorkspaceInvites",
)


def get_invite_store() -> InviteStore:
    """Get the global invite store instance."""
    return _invite_store_lazy.get()


class WorkspaceInvitesMixin:
    """Mixin providing invite management handler methods.

    Expects the host class to provide:
    - _get_user_store()
    - _get_isolation_manager()
    - _get_audit_log()
    - _run_async(coro)
    - _check_rbac_permission(handler, perm, auth_ctx)
    - read_json_body(handler)
    """

    @api_endpoint(
        method="POST",
        path="/api/v1/workspaces/{workspace_id}/invites",
        summary="Create workspace invite",
        tags=["Workspaces", "Invites"],
    )
    @rate_limit(requests_per_minute=20, limiter_name="workspace_invite")
    @handle_errors("create workspace invite")
    @log_request("create workspace invite")
    def _handle_create_invite(
        self, handler: HTTPRequestHandler, workspace_id: str
    ) -> HandlerResult:
        """Create an invite to join a workspace.

        Request body:
        {
            "email": "user@example.com",
            "role": "member",  // optional, default "member"
            "expires_in_days": 7  // optional, default 7
        }

        Returns the created invite (without the acceptance token for security).
        """
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

        email = body.get("email")
        if not email or "@" not in email:
            return m.error_response("Valid email is required", 400)

        role = body.get("role", "member")
        expires_in_days = body.get("expires_in_days", 7)

        # Validate role
        if role not in ["owner", "admin", "member", "viewer"]:
            return m.error_response(
                f"Invalid role '{role}'. Valid roles: owner, admin, member, viewer",
                400,
            )

        # Verify workspace exists and user has access
        manager = self._get_isolation_manager()
        try:
            self._run_async(
                manager.get_workspace(
                    workspace_id=workspace_id,
                    actor=auth_ctx.user_id,
                )
            )
        except m.AccessDeniedException as e:
            logger.warning("Handler error: %s", e)
            return m.error_response("Permission denied", 403)

        # Check for existing pending invite
        store = get_invite_store()
        existing = store.check_existing(workspace_id, email)
        if existing:
            return m.error_response(
                f"A pending invite already exists for {email}. "
                f"Cancel it first or wait for it to expire.",
                409,
            )

        # Create the invite
        invite = store.create(
            workspace_id=workspace_id,
            email=email,
            role=role,
            created_by=auth_ctx.user_id,
            expires_in_days=expires_in_days,
        )

        # Log to audit
        audit_log = self._get_audit_log()
        self._run_async(
            audit_log.log(
                action=m.AuditAction.WRITE,
                actor=m.Actor(id=auth_ctx.user_id, type="user"),
                resource=m.Resource(
                    id=invite.id, type="workspace_invite", workspace_id=workspace_id
                ),
                outcome=m.AuditOutcome.SUCCESS,
                details={"email": email, "role": role, "expires_at": invite.expires_at.isoformat()},
            )
        )

        logger.info(
            "Created workspace invite: workspace=%s email=%s role=%s by=%s",
            workspace_id,
            email,
            role,
            auth_ctx.user_id,
        )

        # Return invite without token (token is sent via email)
        response = invite.to_dict()
        del response["email"]  # Just use masked version
        response["email_masked"] = f"{email[:2]}***@{email.split('@')[1]}"
        response["invite_url"] = f"/invites/{invite.token}/accept"

        emit_handler_event(
            "workspace",
            CREATED,
            {"action": "invite_created", "workspace_id": workspace_id},
            user_id=auth_ctx.user_id,
        )
        return m.json_response(response, status=201)

    @api_endpoint(
        method="GET",
        path="/api/v1/workspaces/{workspace_id}/invites",
        summary="List workspace invites",
        tags=["Workspaces", "Invites"],
    )
    @handle_errors("list workspace invites")
    def _handle_list_invites(self, handler: HTTPRequestHandler, workspace_id: str) -> HandlerResult:
        """List all invites for a workspace.

        Query params:
        - status: Filter by status (pending, accepted, expired, canceled)

        Returns list of invites with status and expiration info.
        """
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_WORKSPACE_READ, auth_ctx)
        if rbac_error:
            return rbac_error

        # Verify workspace access
        manager = self._get_isolation_manager()
        try:
            self._run_async(
                manager.get_workspace(
                    workspace_id=workspace_id,
                    actor=auth_ctx.user_id,
                )
            )
        except m.AccessDeniedException as e:
            logger.warning("Handler error: %s", e)
            return m.error_response("Permission denied", 403)

        # Parse status filter from query
        from urllib.parse import parse_qs, urlparse

        query_params = parse_qs(urlparse(handler.path).query)
        status_filter = query_params.get("status", [None])[0]

        status = None
        if status_filter:
            try:
                status = InviteStatus(status_filter)
            except ValueError:
                return m.error_response(
                    f"Invalid status '{status_filter}'. Valid: pending, accepted, expired, canceled",
                    400,
                )

        store = get_invite_store()
        invites = store.list_for_workspace(workspace_id, status)

        # Update expired invites
        now = datetime.now(timezone.utc)
        for invite in invites:
            if invite.status == InviteStatus.PENDING and invite.expires_at < now:
                store.update_status(invite.id, InviteStatus.EXPIRED)
                invite.status = InviteStatus.EXPIRED

        return m.json_response(
            {
                "workspace_id": workspace_id,
                "invites": [inv.to_dict() for inv in invites],
                "total": len(invites),
            }
        )

    @api_endpoint(
        method="DELETE",
        path="/api/v1/workspaces/{workspace_id}/invites/{invite_id}",
        summary="Cancel workspace invite",
        tags=["Workspaces", "Invites"],
    )
    @rate_limit(requests_per_minute=30, limiter_name="workspace_invite")
    @handle_errors("cancel workspace invite")
    @log_request("cancel workspace invite")
    def _handle_cancel_invite(
        self, handler: HTTPRequestHandler, workspace_id: str, invite_id: str
    ) -> HandlerResult:
        """Cancel a pending workspace invite.

        Only pending invites can be canceled.
        """
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_WORKSPACE_SHARE, auth_ctx)
        if rbac_error:
            return rbac_error

        # Get the invite
        store = get_invite_store()
        invite = store.get(invite_id)
        if not invite:
            return m.error_response("Invite not found", 404)

        # Verify workspace matches
        if invite.workspace_id != workspace_id:
            return m.error_response("Invite not found in this workspace", 404)

        # Only pending invites can be canceled
        if invite.status != InviteStatus.PENDING:
            return m.error_response(
                f"Cannot cancel invite with status '{invite.status.value}'",
                400,
            )

        # Cancel the invite
        store.update_status(invite_id, InviteStatus.CANCELED)

        # Log to audit
        audit_log = self._get_audit_log()
        self._run_async(
            audit_log.log(
                action=m.AuditAction.DELETE,
                actor=m.Actor(id=auth_ctx.user_id, type="user"),
                resource=m.Resource(
                    id=invite_id, type="workspace_invite", workspace_id=workspace_id
                ),
                outcome=m.AuditOutcome.SUCCESS,
                details={"email": invite.email, "reason": "canceled"},
            )
        )

        logger.info(
            "Canceled workspace invite: workspace=%s invite=%s by=%s",
            workspace_id,
            invite_id,
            auth_ctx.user_id,
        )

        return m.json_response({"message": "Invite canceled", "invite_id": invite_id})

    @api_endpoint(
        method="POST",
        path="/api/v1/workspaces/{workspace_id}/invites/{invite_id}/resend",
        summary="Resend workspace invite",
        tags=["Workspaces", "Invites"],
    )
    @rate_limit(requests_per_minute=5, limiter_name="workspace_invite_resend")
    @handle_errors("resend workspace invite")
    @log_request("resend workspace invite")
    def _handle_resend_invite(
        self, handler: HTTPRequestHandler, workspace_id: str, invite_id: str
    ) -> HandlerResult:
        """Resend a pending workspace invite.

        This extends the expiration and triggers a new email.
        """
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_WORKSPACE_SHARE, auth_ctx)
        if rbac_error:
            return rbac_error

        store = get_invite_store()
        invite = store.get(invite_id)
        if not invite:
            return m.error_response("Invite not found", 404)

        if invite.workspace_id != workspace_id:
            return m.error_response("Invite not found in this workspace", 404)

        if invite.status != InviteStatus.PENDING:
            return m.error_response(
                f"Cannot resend invite with status '{invite.status.value}'",
                400,
            )

        # Extend expiration
        invite.expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        # In production, this would trigger email sending
        logger.info(
            "Resent workspace invite: workspace=%s invite=%s to=%s",
            workspace_id,
            invite_id,
            invite.email,
        )

        return m.json_response(
            {
                "message": "Invite resent",
                "invite_id": invite_id,
                "new_expires_at": invite.expires_at.isoformat(),
            }
        )

    @api_endpoint(
        method="POST",
        path="/api/v1/invites/{token}/accept",
        summary="Accept workspace invite",
        tags=["Invites"],
    )
    @rate_limit(requests_per_minute=10, limiter_name="workspace_invite_accept")
    @handle_errors("accept workspace invite")
    @log_request("accept workspace invite")
    def _handle_accept_invite(self, handler: HTTPRequestHandler, token: str) -> HandlerResult:
        """Accept a workspace invite using the invite token.

        The accepting user must be authenticated.
        """
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        # Find invite by token
        store = get_invite_store()
        invite = store.get_by_token(token)
        if not invite:
            return m.error_response("Invalid or expired invite token", 404)

        # Check if invite is still valid
        if not invite.is_valid():
            if (
                invite.status == InviteStatus.EXPIRED
                or datetime.now(timezone.utc) >= invite.expires_at
            ):
                store.update_status(invite.id, InviteStatus.EXPIRED)
                return m.error_response("This invite has expired", 410)
            return m.error_response(
                f"This invite has been {invite.status.value}",
                410,
            )

        # Add user to workspace
        manager = self._get_isolation_manager()
        permissions_map = {
            "owner": [
                m.WorkspacePermission.READ,
                m.WorkspacePermission.WRITE,
                m.WorkspacePermission.ADMIN,
            ],
            "admin": [
                m.WorkspacePermission.READ,
                m.WorkspacePermission.WRITE,
                m.WorkspacePermission.ADMIN,
            ],
            "member": [m.WorkspacePermission.READ, m.WorkspacePermission.WRITE],
            "viewer": [m.WorkspacePermission.READ],
        }
        permissions = permissions_map.get(invite.role, [m.WorkspacePermission.READ])

        try:
            self._run_async(
                manager.add_member(
                    workspace_id=invite.workspace_id,
                    user_id=auth_ctx.user_id,
                    permissions=permissions,
                    added_by=invite.created_by,
                )
            )
        except m.AccessDeniedException as e:
            logger.warning("Handler error: %s", e)
            return m.error_response("Permission denied", 403)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
            logger.exception("Failed to add member via invite: %s", e)
            return m.error_response("Failed to join workspace", 500)

        # Mark invite as accepted
        store.update_status(invite.id, InviteStatus.ACCEPTED, accepted_by=auth_ctx.user_id)

        # Log to audit
        audit_log = self._get_audit_log()
        self._run_async(
            audit_log.log(
                action=m.AuditAction.ADD_MEMBER,
                actor=m.Actor(id=auth_ctx.user_id, type="user"),
                resource=m.Resource(
                    id=invite.workspace_id,
                    type="workspace",
                    workspace_id=invite.workspace_id,
                ),
                outcome=m.AuditOutcome.SUCCESS,
                details={
                    "invite_id": invite.id,
                    "role": invite.role,
                    "invited_by": invite.created_by,
                },
            )
        )

        logger.info(
            "Accepted workspace invite: workspace=%s user=%s role=%s",
            invite.workspace_id,
            auth_ctx.user_id,
            invite.role,
        )

        emit_handler_event(
            "workspace",
            COMPLETED,
            {"action": "invite_accepted", "workspace_id": invite.workspace_id},
            user_id=auth_ctx.user_id,
        )
        return m.json_response(
            {
                "message": "Successfully joined workspace",
                "workspace_id": invite.workspace_id,
                "role": invite.role,
            }
        )


__all__ = [
    "WorkspaceInvitesMixin",
    "InviteStore",
    "WorkspaceInvite",
    "InviteStatus",
    "get_invite_store",
]
