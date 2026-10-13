"""
Workspace CRUD Operations Mixin.

Provides handler methods for workspace create, list, get, and delete operations.
Used as a mixin class by WorkspaceHandler in workspace_module.py.

All references to ``extract_user_from_request`` and privacy types are resolved
at *call time* via ``aragora.server.handlers.workspace.workspace_module`` so that test
patches on that module are respected.

Stability: STABLE
"""

from __future__ import annotations

import logging
from collections.abc import Coroutine
from typing import Any, TYPE_CHECKING

from aragora.events.handler_events import emit_handler_event, CREATED, DELETED
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


class WorkspaceCrudMixin:
    """Mixin providing workspace CRUD handler methods.

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
        method="POST",
        path="/api/v1/workspaces",
        summary="Create a new workspace",
        tags=["Workspaces"],
    )
    @rate_limit(requests_per_minute=30, limiter_name="workspace_create")
    @require_permission("workspace:write")
    @handle_errors("create workspace")
    @log_request("create workspace")
    def _handle_create_workspace(self, handler: HTTPRequestHandler) -> HandlerResult:
        """Create a new workspace."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_WORKSPACE_WRITE, auth_ctx)
        if rbac_error:
            return rbac_error

        body = self.read_json_body(handler)
        if body is None:
            return m.error_response("Invalid JSON body", 400)

        name = body.get("name")
        if not name:
            return m.error_response("name is required", 400)

        # SECURITY: Always use authenticated user's org_id to prevent cross-tenant access
        org_id = auth_ctx.org_id
        if not org_id:
            return m.error_response("organization_id is required", 400)

        # Reject requests that attempt to specify a different organization
        requested_org_id = body.get("organization_id")
        if requested_org_id and requested_org_id != org_id:
            logger.warning(
                "Cross-tenant workspace creation attempt: user=%s own_org=%s requested_org=%s",
                auth_ctx.user_id,
                org_id,
                requested_org_id,
            )
            return m.error_response("Cannot create workspace in another organization", 403)

        initial_members = body.get("members", [])

        manager = self._get_isolation_manager()
        workspace = self._run_async(
            manager.create_workspace(
                organization_id=org_id,
                name=name,
                created_by=auth_ctx.user_id,
                initial_members=initial_members,
            )
        )

        # Log to audit
        audit_log = self._get_audit_log()
        self._run_async(
            audit_log.log(
                action=m.AuditAction.CREATE_WORKSPACE,
                actor=m.Actor(id=auth_ctx.user_id, type="user"),
                resource=m.Resource(id=workspace.id, type="workspace", workspace_id=workspace.id),
                outcome=m.AuditOutcome.SUCCESS,
                details={"name": name, "org_id": org_id},
            )
        )

        logger.info("Created workspace %s for org %s", workspace.id, org_id)

        emit_handler_event(
            "workspace", CREATED, {"workspace_id": workspace.id}, user_id=auth_ctx.user_id
        )
        return m.json_response(
            {
                "workspace": workspace.to_dict(),
                "message": "Workspace created successfully",
            },
            status=201,
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/workspaces",
        summary="List workspaces accessible to user",
        tags=["Workspaces"],
    )
    @require_permission("workspace:read")
    @handle_errors("list workspaces")
    def _handle_list_workspaces(
        self, handler: HTTPRequestHandler, query_params: dict[str, Any]
    ) -> HandlerResult:
        """List workspaces accessible to user."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_WORKSPACE_READ, auth_ctx)
        if rbac_error:
            return rbac_error

        # SECURITY: Only list workspaces from user's own organization
        org_id = auth_ctx.org_id
        if not org_id:
            return m.error_response("organization_id is required", 400)

        # Reject requests that attempt to access another organization's workspaces
        requested_org_id = query_params.get("organization_id")
        if requested_org_id and requested_org_id != org_id:
            logger.warning(
                "Cross-tenant workspace list attempt: user=%s own_org=%s requested_org=%s",
                auth_ctx.user_id,
                org_id,
                requested_org_id,
            )
            return m.error_response("Cannot list workspaces from another organization", 403)

        manager = self._get_isolation_manager()
        workspaces = self._run_async(
            manager.list_workspaces(
                actor=auth_ctx.user_id,
                organization_id=org_id,
            )
        )

        return m.json_response(
            {
                "workspaces": [w.to_dict() for w in workspaces],
                "total": len(workspaces),
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/workspaces/{workspace_id}",
        summary="Get workspace details",
        tags=["Workspaces"],
    )
    @require_permission("workspace:read")
    @handle_errors("get workspace")
    def _handle_get_workspace(
        self, handler: HTTPRequestHandler, workspace_id: str
    ) -> HandlerResult:
        """Get workspace details."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_WORKSPACE_READ, auth_ctx)
        if rbac_error:
            return rbac_error

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

        return m.json_response({"workspace": workspace.to_dict()})

    @api_endpoint(
        method="DELETE",
        path="/api/v1/workspaces/{workspace_id}",
        summary="Delete a workspace",
        tags=["Workspaces"],
    )
    @rate_limit(requests_per_minute=10, limiter_name="workspace_delete")
    @require_permission("workspace:delete")
    @handle_errors("delete workspace")
    @log_request("delete workspace")
    def _handle_delete_workspace(
        self, handler: HTTPRequestHandler, workspace_id: str
    ) -> HandlerResult:
        """Delete a workspace."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_WORKSPACE_DELETE, auth_ctx)
        if rbac_error:
            return rbac_error

        body = self.read_json_body(handler) or {}
        force = body.get("force", False)

        manager = self._get_isolation_manager()
        try:
            self._run_async(
                manager.delete_workspace(
                    workspace_id=workspace_id,
                    deleted_by=auth_ctx.user_id,
                    force=force,
                )
            )
        except m.AccessDeniedException as e:
            logger.warning("Handler error: %s", e)
            return m.error_response("Permission denied", 403)

        # Log to audit
        audit_log = self._get_audit_log()
        self._run_async(
            audit_log.log(
                action=m.AuditAction.DELETE_WORKSPACE,
                actor=m.Actor(id=auth_ctx.user_id, type="user"),
                resource=m.Resource(id=workspace_id, type="workspace", workspace_id=workspace_id),
                outcome=m.AuditOutcome.SUCCESS,
            )
        )

        emit_handler_event(
            "workspace", DELETED, {"workspace_id": workspace_id}, user_id=auth_ctx.user_id
        )
        return m.json_response({"message": "Workspace deleted successfully"})


__all__ = ["WorkspaceCrudMixin"]
