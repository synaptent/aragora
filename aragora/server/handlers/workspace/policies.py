"""
Workspace Retention Policy Management Mixin.

Provides handler methods for retention policy CRUD, execution, and expiring items.
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

from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import handle_errors, log_request
from aragora.server.handlers.openapi_decorator import api_endpoint
from aragora.server.handlers.utils.rate_limit import rate_limit

if TYPE_CHECKING:
    from aragora.billing.auth.context import UserAuthContext
    from aragora.privacy import PrivacyAuditLog, RetentionPolicyManager
    from aragora.protocols import HTTPRequestHandler
    from aragora.server.handlers.base import HandlerResult

logger = logging.getLogger(__name__)


def _mod() -> Any:
    """Lazy import of workspace_module to avoid circular imports and respect patches."""
    import aragora.server.handlers.workspace.workspace_module as m

    return m


class WorkspacePoliciesMixin:
    """Mixin providing retention policy handler methods.

    Expects the host class to provide:
    - _get_user_store()
    - _get_retention_manager()
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

        def _get_retention_manager(self) -> RetentionPolicyManager: ...

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
        path="/api/v1/retention/policies",
        summary="List retention policies",
        tags=["Retention"],
    )
    @require_permission("workspace:policies:read")
    @handle_errors("list retention policies")
    def _handle_list_policies(
        self, handler: HTTPRequestHandler, query_params: dict[str, Any]
    ) -> HandlerResult:
        """List retention policies with caching (5 min TTL)."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_RETENTION_READ, auth_ctx)
        if rbac_error:
            return rbac_error

        workspace_id = query_params.get("workspace_id")

        # Check cache first
        cache_key = f"retention:list:{workspace_id or 'all'}"
        cached_result = m._retention_policy_cache.get(cache_key)
        if cached_result is not None:
            logger.debug("Cache hit for retention policies list: %s", cache_key)
            return m.json_response(cached_result)

        manager = self._get_retention_manager()
        policies = manager.list_policies(workspace_id=workspace_id)

        result = {
            "policies": [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "retention_days": p.retention_days,
                    "action": p.action.value,
                    "enabled": p.enabled,
                    "applies_to": p.applies_to,
                    "last_run": p.last_run.isoformat() if p.last_run else None,
                }
                for p in policies
            ],
            "total": len(policies),
        }

        # Cache the result
        m._retention_policy_cache.set(cache_key, result)
        logger.debug("Cached retention policies list: %s", cache_key)

        return m.json_response(result)

    @api_endpoint(
        method="POST",
        path="/api/v1/retention/policies",
        summary="Create a retention policy",
        tags=["Retention"],
    )
    @rate_limit(requests_per_minute=20, limiter_name="retention_policy")
    @require_permission("workspace:policies:write")
    @handle_errors("create retention policy")
    @log_request("create retention policy")
    def _handle_create_policy(self, handler: HTTPRequestHandler) -> HandlerResult:
        """Create a retention policy."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_RETENTION_WRITE, auth_ctx)
        if rbac_error:
            return rbac_error

        body = self.read_json_body(handler)
        if body is None:
            return m.error_response("Invalid JSON body", 400)

        name = body.get("name")
        if not name:
            return m.error_response("name is required", 400)

        retention_days = body.get("retention_days", 90)
        action_str = body.get("action", "delete")

        try:
            action = m.RetentionAction(action_str)
        except ValueError:
            return m.error_response(
                f"Invalid action: {action_str}. Valid: delete, archive, anonymize, notify",
                400,
            )

        workspace_ids = body.get("workspace_ids")
        description = body.get("description", "")
        applies_to = body.get("applies_to", ["documents", "findings", "sessions"])

        manager = self._get_retention_manager()
        policy = manager.create_policy(
            name=name,
            retention_days=retention_days,
            action=action,
            workspace_ids=workspace_ids,
            description=description,
            applies_to=applies_to,
        )

        # Invalidate cache after creating policy
        m._invalidate_retention_cache()
        logger.debug("Invalidated retention policy cache after create")

        # Log to audit
        audit_log = self._get_audit_log()
        self._run_async(
            audit_log.log(
                action=m.AuditAction.MODIFY_POLICY,
                actor=m.Actor(id=auth_ctx.user_id, type="user"),
                resource=m.Resource(id=policy.id, type="retention_policy"),
                outcome=m.AuditOutcome.SUCCESS,
                details={"operation": "create", "name": name},
            )
        )

        return m.json_response(
            {
                "policy": {
                    "id": policy.id,
                    "name": policy.name,
                    "retention_days": policy.retention_days,
                    "action": policy.action.value,
                },
                "message": "Policy created successfully",
            },
            status=201,
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/retention/policies/{policy_id}",
        summary="Get a retention policy",
        tags=["Retention"],
    )
    @require_permission("workspace:policies:read")
    @handle_errors("get retention policy")
    def _handle_get_policy(self, handler: HTTPRequestHandler, policy_id: str) -> HandlerResult:
        """Get a retention policy with caching (5 min TTL)."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_RETENTION_READ, auth_ctx)
        if rbac_error:
            return rbac_error

        # Check cache first
        cache_key = f"retention:{policy_id}"
        cached_result = m._retention_policy_cache.get(cache_key)
        if cached_result is not None:
            logger.debug("Cache hit for retention policy: %s", cache_key)
            return m.json_response(cached_result)

        manager = self._get_retention_manager()
        policy = manager.get_policy(policy_id)

        if not policy:
            return m.error_response("Policy not found", 404)

        result = {
            "policy": {
                "id": policy.id,
                "name": policy.name,
                "description": policy.description,
                "retention_days": policy.retention_days,
                "action": policy.action.value,
                "enabled": policy.enabled,
                "applies_to": policy.applies_to,
                "workspace_ids": policy.workspace_ids,
                "grace_period_days": policy.grace_period_days,
                "notify_before_days": policy.notify_before_days,
                "exclude_sensitivity_levels": policy.exclude_sensitivity_levels,
                "exclude_tags": policy.exclude_tags,
                "created_at": policy.created_at.isoformat(),
                "last_run": policy.last_run.isoformat() if policy.last_run else None,
            }
        }

        # Cache the result
        m._retention_policy_cache.set(cache_key, result)
        logger.debug("Cached retention policy: %s", cache_key)

        return m.json_response(result)

    @api_endpoint(
        method="PUT",
        path="/api/v1/retention/policies/{policy_id}",
        summary="Update a retention policy",
        tags=["Retention"],
    )
    @rate_limit(requests_per_minute=20, limiter_name="retention_policy")
    @require_permission("workspace:policies:write")
    @handle_errors("update retention policy")
    @log_request("update retention policy")
    def _handle_update_policy(self, handler: HTTPRequestHandler, policy_id: str) -> HandlerResult:
        """Update a retention policy."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_RETENTION_WRITE, auth_ctx)
        if rbac_error:
            return rbac_error

        body = self.read_json_body(handler)
        if body is None:
            return m.error_response("Invalid JSON body", 400)

        manager = self._get_retention_manager()

        # Convert action string to enum if present
        if "action" in body:
            try:
                body["action"] = m.RetentionAction(body["action"])
            except ValueError:
                return m.error_response(f"Invalid action: {body['action']}", 400)

        try:
            policy = manager.update_policy(policy_id, **body)
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return m.error_response("Resource not found", 404)

        # Invalidate cache after updating policy
        m._invalidate_retention_cache(policy_id)
        logger.debug("Invalidated retention policy cache after update: %s", policy_id)

        # Log to audit
        audit_log = self._get_audit_log()
        self._run_async(
            audit_log.log(
                action=m.AuditAction.MODIFY_POLICY,
                actor=m.Actor(id=auth_ctx.user_id, type="user"),
                resource=m.Resource(id=policy_id, type="retention_policy"),
                outcome=m.AuditOutcome.SUCCESS,
                details={"operation": "update", "changes": list(body.keys())},
            )
        )

        return m.json_response(
            {
                "policy": {
                    "id": policy.id,
                    "name": policy.name,
                    "retention_days": policy.retention_days,
                },
                "message": "Policy updated successfully",
            }
        )

    @api_endpoint(
        method="DELETE",
        path="/api/v1/retention/policies/{policy_id}",
        summary="Delete a retention policy",
        tags=["Retention"],
    )
    @rate_limit(requests_per_minute=10, limiter_name="retention_policy")
    @require_permission("workspace:policies:write")
    @handle_errors("delete retention policy")
    @log_request("delete retention policy")
    def _handle_delete_policy(self, handler: HTTPRequestHandler, policy_id: str) -> HandlerResult:
        """Delete a retention policy."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_RETENTION_DELETE, auth_ctx)
        if rbac_error:
            return rbac_error

        manager = self._get_retention_manager()
        manager.delete_policy(policy_id)

        # Invalidate cache after deleting policy
        m._invalidate_retention_cache(policy_id)
        logger.debug("Invalidated retention policy cache after delete: %s", policy_id)

        # Log to audit
        audit_log = self._get_audit_log()
        self._run_async(
            audit_log.log(
                action=m.AuditAction.MODIFY_POLICY,
                actor=m.Actor(id=auth_ctx.user_id, type="user"),
                resource=m.Resource(id=policy_id, type="retention_policy"),
                outcome=m.AuditOutcome.SUCCESS,
                details={"operation": "delete"},
            )
        )

        return m.json_response({"message": "Policy deleted successfully"})

    @api_endpoint(
        method="POST",
        path="/api/v1/retention/policies/{policy_id}/execute",
        summary="Execute a retention policy",
        tags=["Retention"],
    )
    @rate_limit(requests_per_minute=5, limiter_name="retention_execute")
    @require_permission("workspace:policies:write")
    @handle_errors("execute retention policy")
    @log_request("execute retention policy")
    def _handle_execute_policy(
        self, handler: HTTPRequestHandler, policy_id: str, query_params: dict[str, Any]
    ) -> HandlerResult:
        """Execute a retention policy."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_RETENTION_EXECUTE, auth_ctx)
        if rbac_error:
            return rbac_error

        dry_run = query_params.get("dry_run", "false").lower() == "true"
        manager = self._get_retention_manager()

        try:
            report = self._run_async(manager.execute_policy(policy_id, dry_run=dry_run))
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return m.error_response("Resource not found", 404)

        # Log to audit
        audit_log = self._get_audit_log()
        self._run_async(
            audit_log.log(
                action=m.AuditAction.EXECUTE_RETENTION,
                actor=m.Actor(id=auth_ctx.user_id, type="user"),
                resource=m.Resource(id=policy_id, type="retention_policy"),
                outcome=m.AuditOutcome.SUCCESS,
                details={
                    "dry_run": dry_run,
                    "items_deleted": report.items_deleted,
                    "items_evaluated": report.items_evaluated,
                },
            )
        )

        return m.json_response({"report": report.to_dict(), "dry_run": dry_run})

    @api_endpoint(
        method="GET",
        path="/api/v1/retention/expiring",
        summary="Get items expiring soon",
        tags=["Retention"],
    )
    @require_permission("workspace:policies:read")
    @handle_errors("get expiring items")
    def _handle_expiring_items(
        self, handler: HTTPRequestHandler, query_params: dict[str, Any]
    ) -> HandlerResult:
        """Get items expiring soon."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_RETENTION_READ, auth_ctx)
        if rbac_error:
            return rbac_error

        workspace_id = query_params.get("workspace_id")
        days = int(query_params.get("days", "14"))

        manager = self._get_retention_manager()
        expiring = self._run_async(
            manager.check_expiring_soon(workspace_id=workspace_id, days=days)
        )

        return m.json_response({"expiring": expiring, "total": len(expiring), "days_ahead": days})


__all__ = ["WorkspacePoliciesMixin"]
