"""
Cross-workspace coordination HTTP handler.

Wires the CrossWorkspaceCoordinator into REST endpoints:
- POST   /api/v1/coordination/workspaces        - register workspace
- GET    /api/v1/coordination/workspaces         - list registered workspaces
- DELETE /api/v1/coordination/workspaces/{id}    - unregister workspace
- POST   /api/v1/coordination/federation         - create federation policy
- GET    /api/v1/coordination/federation         - list federation policies
- POST   /api/v1/coordination/execute            - cross-workspace execution
- GET    /api/v1/coordination/executions         - list executions
- POST   /api/v1/coordination/consent            - grant consent
- DELETE /api/v1/coordination/consent/{id}       - revoke consent
- GET    /api/v1/coordination/consent            - list consents
- POST   /api/v1/coordination/approve/{id}       - approve pending execution
- GET    /api/v1/coordination/stats              - coordination stats
- GET    /api/v1/coordination/health             - health check
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.rbac.decorators import require_permission
from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)

logger = logging.getLogger(__name__)

# Graceful degradation: try to import the coordinator
try:
    from aragora.coordination.cross_workspace import (
        CrossWorkspaceCoordinator,  # noqa: F401
        CrossWorkspaceRequest,
        DataSharingConsent,  # noqa: F401
        FederatedWorkspace,
        FederationMode,
        FederationPolicy,
        OperationType,
        SharingScope,
        get_coordinator,
    )

    _HAS_COORDINATION = True
except ImportError:
    _HAS_COORDINATION = False

    def get_coordinator() -> Any:  # type: ignore[misc]
        """Stub for when coordination module is unavailable."""
        return None


def _coordination_unavailable() -> HandlerResult:
    """Return 501 when coordination module is not available."""
    return error_response(
        "Cross-workspace coordination module is not available. "
        "Install the aragora.coordination package to enable this feature.",
        501,
    )


def _parse_federation_mode(value: str) -> Any:
    """Parse a federation mode string, returning None on failure."""
    if not _HAS_COORDINATION:
        return None
    try:
        return FederationMode(value)
    except (ValueError, KeyError):
        return None


def _parse_sharing_scope(value: str) -> Any:
    """Parse a sharing scope string, returning None on failure."""
    if not _HAS_COORDINATION:
        return None
    try:
        return SharingScope(value)
    except (ValueError, KeyError):
        return None


def _parse_operation_type(value: str) -> Any:
    """Parse an operation type string, returning None on failure."""
    if not _HAS_COORDINATION:
        return None
    try:
        return OperationType(value)
    except (ValueError, KeyError):
        return None


class CoordinationHandler(BaseHandler):
    """Handler for cross-workspace coordination API endpoints."""

    PREFIX = "/api/v1/coordination"
    ROUTES = [
        "/api/v1/coordination/workspaces",
        "/api/v1/coordination/federation",
        "/api/v1/coordination/execute",
        "/api/v1/coordination/executions",
        "/api/v1/coordination/consent",
        "/api/v1/coordination/stats",
        "/api/v1/coordination/health",
    ]
    _ROUTE_MAP = {
        "GET /api/v1/coordination/workspaces": "handle",
        "POST /api/v1/coordination/workspaces": "handle_post",
        "DELETE /api/v1/coordination/workspaces/{workspace_id}": "handle_delete",
        "GET /api/v1/coordination/federation": "handle",
        "POST /api/v1/coordination/federation": "handle_post",
        "POST /api/v1/coordination/execute": "handle_post",
        "GET /api/v1/coordination/executions": "handle",
        "GET /api/v1/coordination/consent": "handle",
        "POST /api/v1/coordination/consent": "handle_post",
        "POST /api/v1/coordination/approve/{request_id}": "handle_post",
        "DELETE /api/v1/coordination/consent/{consent_id}": "handle_delete",
        "GET /api/v1/coordination/stats": "handle",
        "GET /api/v1/coordination/health": "handle",
    }

    def __init__(self, ctx: dict[str, Any] | None = None):
        """Initialize handler with optional context."""
        super().__init__(ctx or {})
        self._coordinator = get_coordinator() if _HAS_COORDINATION else None

    # -----------------------------------------------------------------
    # Route matching
    # -----------------------------------------------------------------

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given request path."""
        normalized = path.rstrip("/")
        if not normalized.startswith(self.PREFIX):
            # Also match unversioned paths
            if not normalized.startswith("/api/coordination"):
                return False
        return True

    # -----------------------------------------------------------------
    # GET dispatch
    # -----------------------------------------------------------------

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests to appropriate handler methods."""
        normalized = path.rstrip("/")

        if normalized.endswith("/coordination/workspaces"):
            return self._handle_list_workspaces(query_params)
        if normalized.endswith("/coordination/federation"):
            return self._handle_list_policies(query_params)
        if normalized.endswith("/coordination/executions"):
            return self._handle_list_executions(query_params)
        if normalized.endswith("/coordination/consent"):
            return self._handle_list_consents(query_params)
        if normalized.endswith("/coordination/stats"):
            return self._handle_stats()
        if normalized.endswith("/coordination/health"):
            return self._handle_health()

        return None

    # -----------------------------------------------------------------
    # POST dispatch
    # -----------------------------------------------------------------

    @handle_errors
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route POST requests to appropriate handler methods."""
        normalized = path.rstrip("/")

        if normalized.endswith("/coordination/workspaces"):
            body, error = self.read_json_object_or_error(handler)
            if error:
                return error
            return self._handle_register_workspace(body)

        if normalized.endswith("/coordination/federation"):
            body, error = self.read_json_object_or_error(handler)
            if error:
                return error
            return self._handle_create_policy(body)

        if normalized.endswith("/coordination/execute"):
            body, error = self.read_json_object_or_error(handler)
            if error:
                return error
            return self._handle_execute(body)

        if normalized.endswith("/coordination/consent"):
            body, error = self.read_json_object_or_error(handler)
            if error:
                return error
            return self._handle_grant_consent(body)

        # POST /api/v1/coordination/approve/{id}
        if "/coordination/approve/" in normalized:
            segments = normalized.split("/")
            # Find the segment after "approve"
            request_id = None
            for i, seg in enumerate(segments):
                if seg == "approve" and i + 1 < len(segments):
                    request_id = segments[i + 1]
                    break
            if not request_id:
                return error_response("Missing request ID", 400)
            body, error = self.read_json_object_or_error(handler)
            if error:
                return error
            return self._handle_approve(request_id, body)

        return None

    # -----------------------------------------------------------------
    # DELETE dispatch
    # -----------------------------------------------------------------

    @handle_errors
    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route DELETE requests to appropriate handler methods."""
        normalized = path.rstrip("/")

        # DELETE /api/v1/coordination/workspaces/{id}
        if "/coordination/workspaces/" in normalized:
            segments = normalized.split("/")
            # Find the segment after "workspaces"
            workspace_id = None
            for i, seg in enumerate(segments):
                if seg == "workspaces" and i + 1 < len(segments):
                    workspace_id = segments[i + 1]
                    break
            if not workspace_id:
                return error_response("Missing workspace ID", 400)
            return self._handle_unregister_workspace(workspace_id)

        # DELETE /api/v1/coordination/consent/{id}
        if "/coordination/consent/" in normalized:
            segments = normalized.split("/")
            consent_id = None
            for i, seg in enumerate(segments):
                if seg == "consent" and i + 1 < len(segments):
                    consent_id = segments[i + 1]
                    break
            if not consent_id:
                return error_response("Missing consent ID", 400)
            return self._handle_revoke_consent(consent_id)

        return None

    # =================================================================
    # Workspace endpoints
    # =================================================================

    @handle_errors("workspace registration")
    @require_permission("coordination:write")
    def _handle_register_workspace(self, body: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/coordination/workspaces -- register a workspace."""
        if not _HAS_COORDINATION or self._coordinator is None:
            return _coordination_unavailable()

        ws_id = body.get("id", "")
        if not ws_id:
            return error_response("Workspace 'id' is required", 400)

        name = body.get("name", ws_id)
        org_id = body.get("org_id", "")
        mode_str = body.get("federation_mode", "readonly")
        mode = _parse_federation_mode(mode_str)
        if mode is None:
            return error_response(
                f"Invalid federation_mode: {mode_str}. "
                f"Valid values: {', '.join(m.value for m in FederationMode)}",
                400,
            )

        workspace = FederatedWorkspace(
            id=ws_id,
            name=name,
            org_id=org_id,
            federation_mode=mode,
            endpoint_url=body.get("endpoint_url"),
            supports_agent_execution=body.get("supports_agent_execution", True),
            supports_workflow_execution=body.get("supports_workflow_execution", True),
            supports_knowledge_query=body.get("supports_knowledge_query", True),
        )

        self._coordinator.register_workspace(workspace)

        logger.info("Registered workspace %s (%s)", ws_id, name)

        return json_response(
            {"workspace": workspace.to_dict(), "registered": True},
            status=201,
        )

    @require_permission("coordination:read")
    def _handle_list_workspaces(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/coordination/workspaces -- list workspaces."""
        if not _HAS_COORDINATION or self._coordinator is None:
            return _coordination_unavailable()

        workspaces = self._coordinator.list_workspaces()
        return json_response(
            {
                "workspaces": [ws.to_dict() for ws in workspaces],
                "total": len(workspaces),
            }
        )

    @handle_errors("workspace unregistration")
    @require_permission("coordination:delete")
    def _handle_unregister_workspace(self, workspace_id: str) -> HandlerResult:
        """DELETE /api/v1/coordination/workspaces/{id} -- unregister workspace."""
        if not _HAS_COORDINATION or self._coordinator is None:
            return _coordination_unavailable()

        self._coordinator.unregister_workspace(workspace_id)

        logger.info("Unregistered workspace %s", workspace_id)

        return json_response({"unregistered": True, "workspace_id": workspace_id})

    # =================================================================
    # Federation policy endpoints
    # =================================================================

    @handle_errors("federation policy creation")
    @require_permission("coordination:write")
    def _handle_create_policy(self, body: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/coordination/federation -- create federation policy."""
        if not _HAS_COORDINATION or self._coordinator is None:
            return _coordination_unavailable()

        name = body.get("name", "")
        if not name:
            return error_response("Policy 'name' is required", 400)

        mode_str = body.get("mode", "isolated")
        mode = _parse_federation_mode(mode_str)
        if mode is None:
            return error_response(f"Invalid mode: {mode_str}", 400)

        scope_str = body.get("sharing_scope", "none")
        scope = _parse_sharing_scope(scope_str)
        if scope is None:
            return error_response(f"Invalid sharing_scope: {scope_str}", 400)

        # Parse allowed operations
        allowed_ops: set[OperationType] = set()
        for op_str in body.get("allowed_operations", []):
            op = _parse_operation_type(op_str)
            if op is not None:
                allowed_ops.add(op)

        policy = FederationPolicy(
            name=name,
            description=body.get("description", ""),
            mode=mode,
            sharing_scope=scope,
            allowed_operations=allowed_ops,
            max_requests_per_hour=body.get("max_requests_per_hour", 100),
            require_approval=body.get("require_approval", False),
            audit_all_requests=body.get("audit_all_requests", True),
        )

        # Apply policy at the right scope
        workspace_id = body.get("workspace_id")
        source_workspace_id = body.get("source_workspace_id")
        target_workspace_id = body.get("target_workspace_id")

        self._coordinator.set_policy(
            policy,
            workspace_id=workspace_id,
            source_workspace_id=source_workspace_id,
            target_workspace_id=target_workspace_id,
        )

        logger.info("Created federation policy %s (mode=%s)", name, mode_str)

        return json_response(
            {"policy": policy.to_dict(), "created": True},
            status=201,
        )

    @require_permission("coordination:read")
    def _handle_list_policies(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/coordination/federation -- list federation policies."""
        if not _HAS_COORDINATION or self._coordinator is None:
            return _coordination_unavailable()

        # Gather all policies: default + workspace-specific + pair-specific
        policies: list[dict[str, Any]] = []

        # Default policy
        default = self._coordinator._default_policy
        entry = default.to_dict()
        entry["scope"] = "default"
        policies.append(entry)

        # Workspace policies
        for ws_id, pol in self._coordinator._workspace_policies.items():
            entry = pol.to_dict()
            entry["scope"] = "workspace"
            entry["workspace_id"] = ws_id
            policies.append(entry)

        # Pair policies
        for (src, tgt), pol in self._coordinator._pair_policies.items():
            entry = pol.to_dict()
            entry["scope"] = "pair"
            entry["source_workspace_id"] = src
            entry["target_workspace_id"] = tgt
            policies.append(entry)

        return json_response(
            {
                "policies": policies,
                "total": len(policies),
            }
        )

    # =================================================================
    # Execution endpoints
    # =================================================================

    @handle_errors("cross-workspace execution")
    @require_permission("coordination:execute")
    def _handle_execute(self, body: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/coordination/execute -- cross-workspace execution."""
        if not _HAS_COORDINATION or self._coordinator is None:
            return _coordination_unavailable()

        operation_str = body.get("operation", "")
        if not operation_str:
            return error_response("'operation' is required", 400)

        operation = _parse_operation_type(operation_str)
        if operation is None:
            return error_response(f"Invalid operation: {operation_str}", 400)

        source = body.get("source_workspace_id", "")
        target = body.get("target_workspace_id", "")
        if not source or not target:
            return error_response(
                "'source_workspace_id' and 'target_workspace_id' are required", 400
            )

        request = CrossWorkspaceRequest(
            operation=operation,
            source_workspace_id=source,
            target_workspace_id=target,
            payload=body.get("payload", {}),
            timeout_seconds=body.get("timeout_seconds", 30.0),
            requester_id=body.get("requester_id", ""),
            consent_id=body.get("consent_id"),
        )

        # Execute synchronously via asyncio (handler is sync)
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        try:
            if loop is not None and loop.is_running():
                # If already in an async context, run in a thread pool
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(asyncio.run, self._coordinator.execute(request)).result(
                        timeout=request.timeout_seconds + 5
                    )
            else:
                result = asyncio.run(self._coordinator.execute(request))
        except RuntimeError:
            result = asyncio.run(self._coordinator.execute(request))

        status = 200 if result.success else 422
        if result.error_code == "APPROVAL_REQUIRED":
            status = 202

        return json_response(result.to_dict(), status=status)

    @require_permission("coordination:read")
    def _handle_list_executions(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/coordination/executions -- list pending executions."""
        if not _HAS_COORDINATION or self._coordinator is None:
            return _coordination_unavailable()

        workspace_id = query_params.get("workspace_id")
        requests = self._coordinator.list_pending_requests(workspace_id)

        return json_response(
            {
                "executions": [r.to_dict() for r in requests],
                "total": len(requests),
            }
        )

    # =================================================================
    # Consent endpoints
    # =================================================================

    @handle_errors("consent granting")
    @require_permission("coordination:write")
    def _handle_grant_consent(self, body: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/coordination/consent -- grant consent."""
        if not _HAS_COORDINATION or self._coordinator is None:
            return _coordination_unavailable()

        source = body.get("source_workspace_id", "")
        target = body.get("target_workspace_id", "")
        if not source or not target:
            return error_response(
                "'source_workspace_id' and 'target_workspace_id' are required", 400
            )

        scope_str = body.get("scope", "metadata")
        scope = _parse_sharing_scope(scope_str)
        if scope is None:
            return error_response(f"Invalid scope: {scope_str}", 400)

        # Parse data types and operations
        data_types = set(body.get("data_types", []))
        operations: set[OperationType] = set()
        for op_str in body.get("operations", []):
            op = _parse_operation_type(op_str)
            if op is not None:
                operations.add(op)

        consent = self._coordinator.grant_consent(
            source_workspace_id=source,
            target_workspace_id=target,
            scope=scope,
            data_types=data_types,
            operations=operations,
            granted_by=body.get("granted_by", ""),
            expires_in_days=body.get("expires_in_days"),
        )

        logger.info("Granted consent %s from %s to %s", consent.id, source, target)

        return json_response(
            {"consent": consent.to_dict(), "granted": True},
            status=201,
        )

    @require_permission("coordination:read")
    def _handle_list_consents(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/coordination/consent -- list consents."""
        if not _HAS_COORDINATION or self._coordinator is None:
            return _coordination_unavailable()

        workspace_id = query_params.get("workspace_id")
        consents = self._coordinator.list_consents(workspace_id)

        return json_response(
            {
                "consents": [c.to_dict() for c in consents],
                "total": len(consents),
            }
        )

    @handle_errors("consent revocation")
    @require_permission("coordination:delete")
    def _handle_revoke_consent(self, consent_id: str) -> HandlerResult:
        """DELETE /api/v1/coordination/consent/{id} -- revoke consent."""
        if not _HAS_COORDINATION or self._coordinator is None:
            return _coordination_unavailable()

        success = self._coordinator.revoke_consent(consent_id, revoked_by="api")
        if not success:
            return error_response(f"Consent '{consent_id}' not found", 404)

        logger.info("Revoked consent %s", consent_id)

        return json_response({"revoked": True, "consent_id": consent_id})

    # =================================================================
    # Approval endpoint
    # =================================================================

    @handle_errors("execution approval")
    @require_permission("coordination:admin")
    def _handle_approve(self, request_id: str, body: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/coordination/approve/{id} -- approve pending execution."""
        if not _HAS_COORDINATION or self._coordinator is None:
            return _coordination_unavailable()

        approved_by = body.get("approved_by", "api")

        success = self._coordinator.approve_request(request_id, approved_by)
        if not success:
            return error_response(f"Request '{request_id}' not found or not pending", 404)

        logger.info("Approved request %s by %s", request_id, approved_by)

        return json_response({"approved": True, "request_id": request_id})

    # =================================================================
    # Stats and health
    # =================================================================

    @require_permission("coordination:read")
    def _handle_stats(self) -> HandlerResult:
        """GET /api/v1/coordination/stats -- coordination statistics."""
        if not _HAS_COORDINATION or self._coordinator is None:
            return _coordination_unavailable()

        stats = self._coordinator.get_stats()
        return json_response(stats)

    def _handle_health(self) -> HandlerResult:
        """GET /api/v1/coordination/health -- health check."""
        if not _HAS_COORDINATION:
            return json_response(
                {
                    "status": "unavailable",
                    "reason": "coordination module not installed",
                }
            )

        if self._coordinator is None:
            return json_response(
                {
                    "status": "degraded",
                    "reason": "coordinator not initialized",
                }
            )

        stats = self._coordinator.get_stats()
        status = "healthy"
        if stats["total_workspaces"] == 0:
            status = "idle"

        return json_response(
            {
                "status": status,
                "total_workspaces": stats["total_workspaces"],
                "total_consents": stats["total_consents"],
                "pending_requests": stats["pending_requests"],
            }
        )


__all__ = ["CoordinationHandler"]
