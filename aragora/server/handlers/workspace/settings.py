"""
Workspace Settings Mixin - Classification and Audit Endpoints.

Provides handler methods for sensitivity classification and privacy audit
log operations. Used as a mixin class by WorkspaceHandler in workspace_module.py.

All references to ``extract_user_from_request`` and privacy types are resolved
at *call time* via ``aragora.server.handlers.workspace.workspace_module`` so that test
patches on that module are respected.

Stability: STABLE
"""

from __future__ import annotations

import logging
from collections.abc import Coroutine
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from aragora.events.handler_events import emit_handler_event, COMPLETED
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import handle_errors
from aragora.server.handlers.openapi_decorator import api_endpoint
from aragora.server.handlers.utils.rate_limit import rate_limit

if TYPE_CHECKING:
    from aragora.billing.auth.context import UserAuthContext
    from aragora.privacy import PrivacyAuditLog, SensitivityClassifier
    from aragora.protocols import HTTPRequestHandler
    from aragora.server.handlers.base import HandlerResult

logger = logging.getLogger(__name__)


def _mod() -> Any:
    """Lazy import of workspace_module to avoid circular imports and respect patches."""
    import aragora.server.handlers.workspace.workspace_module as m

    return m


class WorkspaceSettingsMixin:
    """Mixin providing classification and audit handler methods.

    Expects the host class to provide:
    - _get_user_store()
    - _get_classifier()
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

        def _get_classifier(self) -> SensitivityClassifier: ...

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

    # =========================================================================
    # Classification Handlers
    # =========================================================================

    @api_endpoint(
        method="POST",
        path="/api/v1/classify",
        summary="Classify content sensitivity",
        tags=["Classification"],
    )
    @rate_limit(requests_per_minute=60, limiter_name="classify")
    @require_permission("workspace:settings:write")
    @handle_errors("classify content")
    def _handle_classify_content(self, handler: HTTPRequestHandler) -> HandlerResult:
        """Classify content sensitivity."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_CLASSIFY_WRITE, auth_ctx)
        if rbac_error:
            return rbac_error

        body = self.read_json_body(handler)
        if body is None:
            return m.error_response("Invalid JSON body", 400)

        content = body.get("content")
        if not content:
            return m.error_response("content is required", 400)

        document_id = body.get("document_id", "")
        metadata = body.get("metadata", {})

        classifier = self._get_classifier()
        result = self._run_async(
            classifier.classify(
                content=content,
                document_id=document_id,
                metadata=metadata,
            )
        )

        # Log to audit if document_id provided
        if document_id:
            audit_log = self._get_audit_log()
            self._run_async(
                audit_log.log(
                    action=m.AuditAction.CLASSIFY_DOCUMENT,
                    actor=m.Actor(id=auth_ctx.user_id, type="user"),
                    resource=m.Resource(
                        id=document_id,
                        type="document",
                        sensitivity_level=result.level.value,
                    ),
                    outcome=m.AuditOutcome.SUCCESS,
                    details={"level": result.level.value, "confidence": result.confidence},
                )
            )

        emit_handler_event("workspace", COMPLETED, {"action": "classify_content"})
        return m.json_response({"classification": result.to_dict()})

    @api_endpoint(
        method="GET",
        path="/api/v1/classify/policy/{level}",
        summary="Get policy for sensitivity level",
        tags=["Classification"],
    )
    @require_permission("workspace:settings:read")
    @handle_errors("get level policy")
    def _handle_get_level_policy(self, handler: HTTPRequestHandler, level: str) -> HandlerResult:
        """Get recommended policy for a sensitivity level."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_CLASSIFY_READ, auth_ctx)
        if rbac_error:
            return rbac_error

        try:
            sensitivity_level = m.SensitivityLevel(level)
        except ValueError:
            valid_levels = [lvl.value for lvl in m.SensitivityLevel]
            return m.error_response(
                f"Invalid level: {level}. Valid: {', '.join(valid_levels)}", 400
            )

        classifier = self._get_classifier()
        policy = classifier.get_level_policy(sensitivity_level)

        return m.json_response({"level": level, "policy": policy})

    # =========================================================================
    # Audit Log Handlers
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/audit/entries",
        summary="Query audit log entries",
        tags=["Audit"],
    )
    @require_permission("workspace:settings:read")
    @handle_errors("query audit entries")
    def _handle_query_audit(
        self, handler: HTTPRequestHandler, query_params: dict[str, Any]
    ) -> HandlerResult:
        """Query audit log entries with caching (2 min TTL)."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_AUDIT_READ, auth_ctx)
        if rbac_error:
            return rbac_error

        # Parse filters
        start_date = None
        end_date = None
        try:
            if "start_date" in query_params:
                start_date = datetime.fromisoformat(query_params["start_date"])
            if "end_date" in query_params:
                end_date = datetime.fromisoformat(query_params["end_date"])
        except ValueError:
            return m.error_response("Invalid date format. Use ISO 8601.", 400)

        actor_id = query_params.get("actor_id")
        resource_id = query_params.get("resource_id")
        workspace_id = query_params.get("workspace_id")
        action_str = query_params.get("action")
        outcome_str = query_params.get("outcome")
        limit = max(1, min(int(query_params.get("limit", "100")), 1000))

        action = m.AuditAction(action_str) if action_str else None
        outcome = m.AuditOutcome(outcome_str) if outcome_str else None

        # Build cache key from query params
        cache_key = (
            f"audit:query:{workspace_id or 'all'}:{actor_id or 'any'}:"
            f"{resource_id or 'any'}:{action_str or 'any'}:{outcome_str or 'any'}:"
            f"{start_date}:{end_date}:{limit}"
        )
        cached_result = m._audit_query_cache.get(cache_key)
        if cached_result is not None:
            logger.debug("Cache hit for audit query: %s", cache_key)
            return m.json_response(cached_result)

        audit_log = self._get_audit_log()
        entries = self._run_async(
            audit_log.query(
                start_date=start_date,
                end_date=end_date,
                actor_id=actor_id,
                resource_id=resource_id,
                workspace_id=workspace_id,
                action=action,
                outcome=outcome,
                limit=limit,
            )
        )

        # Batch convert entries to dict to avoid N+1 pattern
        entry_dicts = [e.to_dict() for e in entries]

        result = {
            "entries": entry_dicts,
            "total": len(entry_dicts),
            "limit": limit,
        }

        # Cache the result
        m._audit_query_cache.set(cache_key, result)
        logger.debug("Cached audit query: %s", cache_key)

        return m.json_response(result)

    @api_endpoint(
        method="GET",
        path="/api/v1/audit/report",
        summary="Generate compliance audit report",
        tags=["Audit"],
    )
    @require_permission("workspace:settings:read")
    @handle_errors("generate audit report")
    def _handle_audit_report(
        self, handler: HTTPRequestHandler, query_params: dict[str, Any]
    ) -> HandlerResult:
        """Generate compliance report."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_AUDIT_REPORT, auth_ctx)
        if rbac_error:
            return rbac_error

        start_date = None
        end_date = None
        try:
            if "start_date" in query_params:
                start_date = datetime.fromisoformat(query_params["start_date"])
            if "end_date" in query_params:
                end_date = datetime.fromisoformat(query_params["end_date"])
        except ValueError:
            return m.error_response("Invalid date format. Use ISO 8601.", 400)

        workspace_id = query_params.get("workspace_id")
        format_type = query_params.get("format", "json")

        audit_log = self._get_audit_log()
        report = self._run_async(
            audit_log.generate_compliance_report(
                start_date=start_date,
                end_date=end_date,
                workspace_id=workspace_id,
                format=format_type,
            )
        )

        # Log report generation
        self._run_async(
            audit_log.log(
                action=m.AuditAction.GENERATE_REPORT,
                actor=m.Actor(id=auth_ctx.user_id, type="user"),
                resource=m.Resource(id=report["report_id"], type="compliance_report"),
                outcome=m.AuditOutcome.SUCCESS,
                details={"workspace_id": workspace_id},
            )
        )

        return m.json_response({"report": report})

    @api_endpoint(
        method="GET",
        path="/api/v1/audit/verify",
        summary="Verify audit log integrity",
        tags=["Audit"],
    )
    @require_permission("workspace:settings:read")
    @handle_errors("verify audit integrity")
    def _handle_verify_integrity(
        self, handler: HTTPRequestHandler, query_params: dict[str, Any]
    ) -> HandlerResult:
        """Verify audit log integrity."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_AUDIT_VERIFY, auth_ctx)
        if rbac_error:
            return rbac_error

        start_date = None
        end_date = None
        try:
            if "start_date" in query_params:
                start_date = datetime.fromisoformat(query_params["start_date"])
            if "end_date" in query_params:
                end_date = datetime.fromisoformat(query_params["end_date"])
        except ValueError:
            return m.error_response("Invalid date format. Use ISO 8601.", 400)

        audit_log = self._get_audit_log()
        is_valid, errors = self._run_async(
            audit_log.verify_integrity(start_date=start_date, end_date=end_date)
        )

        return m.json_response(
            {
                "valid": is_valid,
                "errors": errors,
                "error_count": len(errors),
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/audit/actor/{actor_id}/history",
        summary="Get all actions by a specific actor",
        tags=["Audit"],
    )
    @require_permission("workspace:settings:read")
    @handle_errors("get actor history")
    def _handle_actor_history(
        self, handler: HTTPRequestHandler, actor_id: str, query_params: dict[str, Any]
    ) -> HandlerResult:
        """Get all actions by a specific actor with caching (2 min TTL)."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_AUDIT_READ, auth_ctx)
        if rbac_error:
            return rbac_error

        days = int(query_params.get("days", "30"))

        # Check cache first
        cache_key = f"audit:actor:{actor_id}:days:{days}"
        cached_result = m._audit_query_cache.get(cache_key)
        if cached_result is not None:
            logger.debug("Cache hit for actor history: %s", cache_key)
            return m.json_response(cached_result)

        audit_log = self._get_audit_log()
        entries = self._run_async(audit_log.get_actor_history(actor_id=actor_id, days=days))

        # Batch convert entries to dict
        entry_dicts = [e.to_dict() for e in entries]

        result = {
            "actor_id": actor_id,
            "entries": entry_dicts,
            "total": len(entry_dicts),
            "days": days,
        }

        # Cache the result
        m._audit_query_cache.set(cache_key, result)
        logger.debug("Cached actor history: %s", cache_key)

        return m.json_response(result)

    @api_endpoint(
        method="GET",
        path="/api/v1/audit/resource/{resource_id}/history",
        summary="Get all actions on a specific resource",
        tags=["Audit"],
    )
    @require_permission("workspace:settings:read")
    @handle_errors("get resource history")
    def _handle_resource_history(
        self, handler: HTTPRequestHandler, resource_id: str, query_params: dict[str, Any]
    ) -> HandlerResult:
        """Get all actions on a specific resource with caching (2 min TTL)."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_AUDIT_READ, auth_ctx)
        if rbac_error:
            return rbac_error

        days = m.safe_query_int(query_params, "days", default=30, min_val=1, max_val=365)

        # Check cache first
        cache_key = f"audit:resource:{resource_id}:days:{days}"
        cached_result = m._audit_query_cache.get(cache_key)
        if cached_result is not None:
            logger.debug("Cache hit for resource history: %s", cache_key)
            return m.json_response(cached_result)

        audit_log = self._get_audit_log()
        entries = self._run_async(
            audit_log.get_resource_history(resource_id=resource_id, days=days)
        )

        # Batch convert entries to dict
        entry_dicts = [e.to_dict() for e in entries]

        result = {
            "resource_id": resource_id,
            "entries": entry_dicts,
            "total": len(entry_dicts),
            "days": days,
        }

        # Cache the result
        m._audit_query_cache.set(cache_key, result)
        logger.debug("Cached resource history: %s", cache_key)

        return m.json_response(result)

    @api_endpoint(
        method="GET",
        path="/api/v1/audit/denied",
        summary="Get denied access attempts",
        tags=["Audit"],
    )
    @require_permission("workspace:settings:read")
    @handle_errors("get denied access attempts")
    def _handle_denied_access(
        self, handler: HTTPRequestHandler, query_params: dict[str, Any]
    ) -> HandlerResult:
        """Get all denied access attempts with caching (2 min TTL)."""
        m = _mod()
        user_store = self._get_user_store()
        auth_ctx = m.extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return m.error_response("Not authenticated", 401)

        rbac_error = self._check_rbac_permission(handler, m.PERM_AUDIT_READ, auth_ctx)
        if rbac_error:
            return rbac_error

        days = m.safe_query_int(query_params, "days", default=7, min_val=1, max_val=365)

        # Check cache first
        cache_key = f"audit:denied:days:{days}"
        cached_result = m._audit_query_cache.get(cache_key)
        if cached_result is not None:
            logger.debug("Cache hit for denied access: %s", cache_key)
            return m.json_response(cached_result)

        audit_log = self._get_audit_log()
        entries = self._run_async(audit_log.get_denied_access_attempts(days=days))

        # Batch convert entries to dict
        entry_dicts = [e.to_dict() for e in entries]

        result = {
            "denied_attempts": entry_dicts,
            "total": len(entry_dicts),
            "days": days,
        }

        # Cache the result
        m._audit_query_cache.set(cache_key, result)
        logger.debug("Cached denied access: %s", cache_key)

        return m.json_response(result)


__all__ = ["WorkspaceSettingsMixin"]
