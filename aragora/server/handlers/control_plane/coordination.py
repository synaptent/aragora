"""
Coordination handlers for Cross-Workspace Federation.

Provides REST API endpoints for:
- Workspace registration and management
- Federation policy configuration
- Cross-workspace execution
- Data sharing consent management
- Coordination health and statistics
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
    safe_error_message,
)
from aragora.server.handlers.openapi_decorator import api_endpoint
from aragora.server.handlers.utils.decorators import (
    handle_errors,
    require_permission,
)
from aragora.worktree.fleet import (
    FleetCoordinationStore,
    build_fleet_rows,
    resolve_repo_root,
)

logger = logging.getLogger(__name__)


class CoordinationHandlerMixin:
    """
    Mixin class providing cross-workspace coordination handlers.

    Provides methods for:
    - Workspace registration, listing, and unregistration
    - Federation policy creation and listing
    - Cross-workspace execution and approval
    - Data sharing consent management
    - Coordination stats and health
    """

    # Attribute declarations - provided by BaseHandler / ControlPlaneHandler
    ctx: dict[str, Any]

    def _get_coordination_coordinator(self) -> Any | None:
        """Get the cross-workspace coordinator."""
        return self.ctx.get("coordination_coordinator")

    def _require_coordination_coordinator(self) -> tuple[Any | None, HandlerResult | None]:
        """Return coordinator and None, or None and error response if not available."""
        coord = self._get_coordination_coordinator()
        if not coord:
            return None, error_response("Coordination service not initialized", 503)
        return coord, None

    # =========================================================================
    # Workspace Management
    # =========================================================================

    @api_endpoint(
        method="POST",
        path="/api/v1/coordination/workspaces",
        summary="Register a workspace for federation",
        tags=["Coordination"],
    )
    @handle_errors("coordination workspace registration")
    @require_permission("coordination:workspaces.write")
    def _handle_register_workspace(self, body: dict[str, Any]) -> HandlerResult:
        """Register a workspace for federation."""
        coordinator, err = self._require_coordination_coordinator()
        if err:
            return err

        workspace_id = body.get("id")
        if not workspace_id:
            return error_response("Workspace id is required", 400)

        name = body.get("name", "")
        org_id = body.get("org_id", "")
        federation_mode = body.get("federation_mode", "readonly")
        endpoint_url = body.get("endpoint_url")

        try:
            from aragora.coordination.cross_workspace import (
                FederatedWorkspace,
                FederationMode,
            )

            mode = FederationMode(federation_mode)
            workspace = FederatedWorkspace(
                id=workspace_id,
                name=name,
                org_id=org_id,
                federation_mode=mode,
                endpoint_url=endpoint_url,
                supports_agent_execution=body.get("supports_agent_execution", True),
                supports_workflow_execution=body.get("supports_workflow_execution", True),
                supports_knowledge_query=body.get("supports_knowledge_query", True),
            )
            coordinator.register_workspace(workspace)
            return json_response(workspace.to_dict(), status=201)
        except (ValueError, KeyError) as e:
            logger.warning("Invalid workspace registration data: %s", e)
            return error_response(safe_error_message(e, "coordination"), 400)

    @api_endpoint(
        method="GET",
        path="/api/v1/coordination/workspaces",
        summary="List registered workspaces",
        tags=["Coordination"],
    )
    @require_permission("coordination:workspaces.read")
    def _handle_list_workspaces(self, query_params: dict[str, Any]) -> HandlerResult:
        """List all registered workspaces."""
        coordinator, err = self._require_coordination_coordinator()
        if err:
            return err

        try:
            workspaces = coordinator.list_workspaces()
            return json_response(
                {
                    "workspaces": [w.to_dict() for w in workspaces],
                    "total": len(workspaces),
                }
            )
        except (ValueError, RuntimeError) as e:
            logger.error("Error listing workspaces: %s", e)
            return error_response(safe_error_message(e, "coordination"), 500)

    @api_endpoint(
        method="DELETE",
        path="/api/v1/coordination/workspaces/{workspace_id}",
        summary="Unregister a workspace",
        tags=["Coordination"],
    )
    @handle_errors("coordination workspace unregistration")
    @require_permission("coordination:workspaces.write")
    def _handle_unregister_workspace(self, workspace_id: str) -> HandlerResult:
        """Unregister a workspace from federation."""
        coordinator, err = self._require_coordination_coordinator()
        if err:
            return err

        try:
            coordinator.unregister_workspace(workspace_id)
            return json_response({"unregistered": True})
        except (ValueError, KeyError) as e:
            logger.warning("Error unregistering workspace %s: %s", workspace_id, e)
            return error_response(safe_error_message(e, "coordination"), 400)

    # =========================================================================
    # Federation Policies
    # =========================================================================

    @api_endpoint(
        method="POST",
        path="/api/v1/coordination/federation",
        summary="Create a federation policy",
        tags=["Coordination"],
    )
    @handle_errors("coordination federation policy creation")
    @require_permission("coordination:federation.write")
    def _handle_create_federation_policy(self, body: dict[str, Any]) -> HandlerResult:
        """Create a federation policy."""
        coordinator, err = self._require_coordination_coordinator()
        if err:
            return err

        name = body.get("name", "")
        if not name:
            return error_response("Policy name is required", 400)

        try:
            from aragora.coordination.cross_workspace import (
                FederationMode,
                FederationPolicy,
                OperationType,
                SharingScope,
            )

            mode = FederationMode(body.get("mode", "isolated"))
            sharing_scope = SharingScope(body.get("sharing_scope", "none"))

            allowed_ops = set()
            for op_str in body.get("allowed_operations", []):
                allowed_ops.add(OperationType(op_str))

            policy = FederationPolicy(
                name=name,
                description=body.get("description", ""),
                mode=mode,
                sharing_scope=sharing_scope,
                allowed_operations=allowed_ops,
                max_requests_per_hour=body.get("max_requests_per_hour", 100),
                require_approval=body.get("require_approval", False),
                audit_all_requests=body.get("audit_all_requests", True),
            )

            workspace_id = body.get("workspace_id")
            source_workspace_id = body.get("source_workspace_id")
            target_workspace_id = body.get("target_workspace_id")

            coordinator.set_policy(
                policy,
                workspace_id=workspace_id,
                source_workspace_id=source_workspace_id,
                target_workspace_id=target_workspace_id,
            )

            return json_response(policy.to_dict(), status=201)
        except (ValueError, KeyError) as e:
            logger.warning("Invalid federation policy data: %s", e)
            return error_response(safe_error_message(e, "coordination"), 400)

    @api_endpoint(
        method="GET",
        path="/api/v1/coordination/federation",
        summary="List federation policies",
        tags=["Coordination"],
    )
    @require_permission("coordination:federation.read")
    def _handle_list_federation_policies(self, query_params: dict[str, Any]) -> HandlerResult:
        """List federation policies."""
        coordinator, err = self._require_coordination_coordinator()
        if err:
            return err

        try:
            # Collect all policies (default + workspace-specific + pair-specific)
            policies: list[dict[str, Any]] = []

            # Default policy
            if hasattr(coordinator, "_default_policy"):
                default = coordinator._default_policy
                entry = default.to_dict()
                entry["scope"] = "default"
                policies.append(entry)

            # Workspace policies
            if hasattr(coordinator, "_workspace_policies"):
                for ws_id, policy in coordinator._workspace_policies.items():
                    entry = policy.to_dict()
                    entry["scope"] = "workspace"
                    entry["workspace_id"] = ws_id
                    policies.append(entry)

            # Pair policies
            if hasattr(coordinator, "_pair_policies"):
                for (src, tgt), policy in coordinator._pair_policies.items():
                    entry = policy.to_dict()
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
        except (ValueError, RuntimeError) as e:
            logger.error("Error listing federation policies: %s", e)
            return error_response(safe_error_message(e, "coordination"), 500)

    # =========================================================================
    # Cross-Workspace Execution
    # =========================================================================

    @api_endpoint(
        method="POST",
        path="/api/v1/coordination/execute",
        summary="Execute a cross-workspace operation",
        tags=["Coordination"],
    )
    @handle_errors("coordination cross-workspace execution")
    @require_permission("coordination:execute.write")
    def _handle_execute(self, body: dict[str, Any]) -> HandlerResult:
        """Execute a cross-workspace operation."""
        coordinator, err = self._require_coordination_coordinator()
        if err:
            return err

        operation = body.get("operation")
        source_workspace_id = body.get("source_workspace_id")
        target_workspace_id = body.get("target_workspace_id")

        if not operation or not source_workspace_id or not target_workspace_id:
            return error_response(
                "operation, source_workspace_id, and target_workspace_id are required", 400
            )

        try:
            from aragora.coordination.cross_workspace import (
                CrossWorkspaceRequest,
                OperationType,
            )
            from aragora.server.http_utils import run_async

            op = OperationType(operation)
            request = CrossWorkspaceRequest(
                operation=op,
                source_workspace_id=source_workspace_id,
                target_workspace_id=target_workspace_id,
                payload=body.get("payload", {}),
                timeout_seconds=body.get("timeout_seconds", 30.0),
                requester_id=body.get("requester_id", ""),
                consent_id=body.get("consent_id"),
            )

            result = run_async(coordinator.execute(request))
            return json_response(result.to_dict(), status=200 if result.success else 422)
        except (ValueError, KeyError) as e:
            logger.warning("Invalid execution request: %s", e)
            return error_response(safe_error_message(e, "coordination"), 400)

    @api_endpoint(
        method="GET",
        path="/api/v1/coordination/executions",
        summary="List pending executions",
        tags=["Coordination"],
    )
    @require_permission("coordination:execute.read")
    def _handle_list_executions(self, query_params: dict[str, Any]) -> HandlerResult:
        """List pending cross-workspace execution requests."""
        coordinator, err = self._require_coordination_coordinator()
        if err:
            return err

        try:
            workspace_id = query_params.get("workspace_id")
            requests = coordinator.list_pending_requests(workspace_id=workspace_id)
            return json_response(
                {
                    "executions": [r.to_dict() for r in requests],
                    "total": len(requests),
                }
            )
        except (ValueError, RuntimeError) as e:
            logger.error("Error listing executions: %s", e)
            return error_response(safe_error_message(e, "coordination"), 500)

    # =========================================================================
    # Consent Management
    # =========================================================================

    @api_endpoint(
        method="POST",
        path="/api/v1/coordination/consent",
        summary="Grant data sharing consent",
        tags=["Coordination"],
    )
    @handle_errors("coordination consent grant")
    @require_permission("coordination:consent.write")
    def _handle_grant_consent(self, body: dict[str, Any]) -> HandlerResult:
        """Grant data sharing consent between workspaces."""
        coordinator, err = self._require_coordination_coordinator()
        if err:
            return err

        source_workspace_id = body.get("source_workspace_id")
        target_workspace_id = body.get("target_workspace_id")
        if not source_workspace_id or not target_workspace_id:
            return error_response("source_workspace_id and target_workspace_id are required", 400)

        try:
            from aragora.coordination.cross_workspace import (
                OperationType,
                SharingScope,
            )

            scope = SharingScope(body.get("scope", "metadata"))
            data_types = set(body.get("data_types", []))
            operations = {OperationType(op) for op in body.get("operations", [])}
            granted_by = body.get("granted_by", "")
            expires_in_days = body.get("expires_in_days")

            consent = coordinator.grant_consent(
                source_workspace_id=source_workspace_id,
                target_workspace_id=target_workspace_id,
                scope=scope,
                data_types=data_types,
                operations=operations,
                granted_by=granted_by,
                expires_in_days=expires_in_days,
            )

            return json_response(consent.to_dict(), status=201)
        except (ValueError, KeyError) as e:
            logger.warning("Invalid consent data: %s", e)
            return error_response(safe_error_message(e, "coordination"), 400)

    @api_endpoint(
        method="DELETE",
        path="/api/v1/coordination/consent/{consent_id}",
        summary="Revoke data sharing consent",
        tags=["Coordination"],
    )
    @handle_errors("coordination consent revocation")
    @require_permission("coordination:consent.write")
    def _handle_revoke_consent(self, consent_id: str, body: dict[str, Any]) -> HandlerResult:
        """Revoke a data sharing consent."""
        coordinator, err = self._require_coordination_coordinator()
        if err:
            return err

        revoked_by = body.get("revoked_by", "api")

        success = coordinator.revoke_consent(consent_id, revoked_by)
        if not success:
            return error_response(f"Consent not found: {consent_id}", 404)

        return json_response({"revoked": True})

    @api_endpoint(
        method="GET",
        path="/api/v1/coordination/consent",
        summary="List data sharing consents",
        tags=["Coordination"],
    )
    @require_permission("coordination:consent.read")
    def _handle_list_consents(self, query_params: dict[str, Any]) -> HandlerResult:
        """List data sharing consents."""
        coordinator, err = self._require_coordination_coordinator()
        if err:
            return err

        try:
            workspace_id = query_params.get("workspace_id")
            consents = coordinator.list_consents(workspace_id=workspace_id)
            return json_response(
                {
                    "consents": [c.to_dict() for c in consents],
                    "total": len(consents),
                }
            )
        except (ValueError, RuntimeError) as e:
            logger.error("Error listing consents: %s", e)
            return error_response(safe_error_message(e, "coordination"), 500)

    # =========================================================================
    # Approval
    # =========================================================================

    @api_endpoint(
        method="POST",
        path="/api/v1/coordination/approve/{request_id}",
        summary="Approve a pending execution request",
        tags=["Coordination"],
    )
    @handle_errors("coordination request approval")
    @require_permission("coordination:execute.write")
    def _handle_approve_request(self, request_id: str, body: dict[str, Any]) -> HandlerResult:
        """Approve a pending cross-workspace execution request."""
        coordinator, err = self._require_coordination_coordinator()
        if err:
            return err

        approved_by = body.get("approved_by", "api")

        success = coordinator.approve_request(request_id, approved_by)
        if not success:
            return error_response(f"Request not found or not pending: {request_id}", 404)

        return json_response({"approved": True})

    # =========================================================================
    # Stats and Health
    # =========================================================================

    @api_endpoint(
        method="GET",
        path="/api/v1/coordination/stats",
        summary="Get coordination statistics",
        tags=["Coordination"],
    )
    @require_permission("coordination:stats.read")
    def _handle_coordination_stats(self, query_params: dict[str, Any]) -> HandlerResult:
        """Get coordination statistics."""
        coordinator, err = self._require_coordination_coordinator()
        if err:
            return err

        try:
            stats = coordinator.get_stats()
            return json_response(stats)
        except (ValueError, RuntimeError) as e:
            logger.error("Error getting coordination stats: %s", e)
            return error_response(safe_error_message(e, "coordination"), 500)

    @api_endpoint(
        method="GET",
        path="/api/v1/coordination/health",
        summary="Coordination health check",
        tags=["Coordination"],
    )
    @require_permission("coordination:health.read")
    def _handle_coordination_health(self, query_params: dict[str, Any]) -> HandlerResult:
        """Check coordination service health."""
        coordinator = self._get_coordination_coordinator()
        if not coordinator:
            return json_response(
                {
                    "status": "unavailable",
                    "message": "Coordination service not initialized",
                }
            )

        try:
            stats = coordinator.get_stats()
            return json_response(
                {
                    "status": "healthy",
                    "total_workspaces": stats.get("total_workspaces", 0),
                    "pending_requests": stats.get("pending_requests", 0),
                    "valid_consents": stats.get("valid_consents", 0),
                }
            )
        except (ValueError, RuntimeError) as e:
            logger.error("Coordination health check failed: %s", e)
            return json_response(
                {
                    "status": "degraded",
                    "error": safe_error_message(e, "coordination"),
                }
            )

    # =========================================================================
    # Fleet Monitoring
    # =========================================================================

    def _fleet_repo_root(self) -> Path:
        repo_hint = Path(str(self.ctx.get("repo_root", ".")))
        return resolve_repo_root(repo_hint)

    def _fleet_store(self, repo_root: Path) -> FleetCoordinationStore:
        return FleetCoordinationStore(repo_root)

    @api_endpoint(
        method="GET",
        path="/api/v1/coordination/fleet/status",
        summary="Get worktree session fleet status",
        tags=["Coordination"],
    )
    @require_permission("coordination:stats.read")
    def _handle_fleet_status(self, query_params: dict[str, Any]) -> HandlerResult:
        """Return codex/claude worktree session status and recent logs."""
        try:
            tail = int(query_params.get("tail", 500))
        except (TypeError, ValueError):
            tail = 500
        tail = max(0, min(tail, 2000))

        base_branch = str(query_params.get("base", "main"))
        repo_root = self._fleet_repo_root()
        rows = build_fleet_rows(repo_root, base_branch=base_branch, tail=tail)
        store = self._fleet_store(repo_root)
        claims = store.list_claims()
        queue = store.list_merge_queue()
        try:
            from aragora.nomic.dev_coordination import DevCoordinationStore

            coordination_summary = DevCoordinationStore(repo_root=repo_root).status_summary()
        except (ImportError, RuntimeError, OSError, ValueError, sqlite3.Error) as exc:
            coordination_summary = {"error": str(exc), "counts": {}}
        claims_by_session: dict[str, list[str]] = {}
        for claim in claims:
            sid = str(claim.get("session_id", "")).strip()
            if not sid:
                continue
            claims_by_session.setdefault(sid, []).append(str(claim.get("path", "")))
        queue_by_session: dict[str, list[str]] = {}
        for item in queue:
            sid = str(item.get("session_id", "")).strip()
            if not sid:
                continue
            queue_by_session.setdefault(sid, []).append(str(item.get("branch", "")))
        for row in rows:
            session_id = str(row.get("session_id", ""))
            row["claimed_paths"] = sorted(claims_by_session.get(session_id, []))
            row["queued_branches"] = sorted(queue_by_session.get(session_id, []))
        return json_response(
            {
                "repo_root": str(repo_root),
                "base_branch": base_branch,
                "tail": tail,
                "worktrees": rows,
                "claims": claims,
                "merge_queue": queue,
                "coordination": coordination_summary,
                "total": len(rows),
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v1/coordination/fleet/logs",
        summary="Get recent logs for a specific worktree session",
        tags=["Coordination"],
    )
    @require_permission("coordination:stats.read")
    def _handle_fleet_logs(self, query_params: dict[str, Any]) -> HandlerResult:
        """Return tail logs for one fleet session by session_id."""
        session_id = str(query_params.get("session_id", "")).strip()
        if not session_id:
            return error_response("session_id is required", 400)

        try:
            tail = int(query_params.get("tail", 500))
        except (TypeError, ValueError):
            tail = 500
        tail = max(0, min(tail, 5000))

        base_branch = str(query_params.get("base", "main"))
        repo_root = self._fleet_repo_root()
        rows = build_fleet_rows(repo_root, base_branch=base_branch, tail=tail)

        for row in rows:
            if str(row.get("session_id", "")).strip() == session_id:
                return json_response(
                    {
                        "repo_root": str(repo_root),
                        "session_id": session_id,
                        "tail": tail,
                        "worktree": row,
                    }
                )

        return error_response(f"session_id not found: {session_id}", 404)

    @api_endpoint(
        method="GET",
        path="/api/v1/coordination/fleet/claims",
        summary="List fleet ownership claims",
        tags=["Coordination"],
    )
    @require_permission("coordination:stats.read")
    def _handle_fleet_claims(self, query_params: dict[str, Any]) -> HandlerResult:
        """List all file ownership claims."""
        repo_root = self._fleet_repo_root()
        store = self._fleet_store(repo_root)
        session_id = str(query_params.get("session_id", "")).strip()
        claims = store.list_claims()
        if session_id:
            claims = [c for c in claims if str(c.get("session_id", "")) == session_id]
        return json_response({"repo_root": str(repo_root), "claims": claims, "total": len(claims)})

    @api_endpoint(
        method="POST",
        path="/api/v1/coordination/fleet/claims",
        summary="Claim file ownership for a session",
        tags=["Coordination"],
    )
    @require_permission("coordination:workspaces.write")
    def _handle_fleet_claim(self, body: dict[str, Any]) -> HandlerResult:
        """Claim file ownership to avoid concurrent merge collisions."""
        session_id = str(body.get("session_id", "")).strip()
        if not session_id:
            return error_response("session_id is required", 400)
        raw_paths = body.get("paths")
        if not isinstance(raw_paths, list) or not raw_paths:
            return error_response("paths must be a non-empty list", 400)
        paths = [str(item) for item in raw_paths if str(item).strip()]
        if not paths:
            return error_response("paths must be a non-empty list", 400)

        mode = str(body.get("mode", "exclusive")).strip().lower()
        branch = str(body.get("branch", "")).strip()
        repo_root = self._fleet_repo_root()
        store = self._fleet_store(repo_root)
        try:
            result = store.claim_paths(
                session_id=session_id,
                paths=paths,
                mode=mode,
                branch=branch,
            )
        except ValueError as exc:
            return error_response(safe_error_message(exc, "coordination"), 400)
        status_code = 409 if result.get("conflicts") else 200
        return json_response(result, status=status_code)

    @api_endpoint(
        method="POST",
        path="/api/v1/coordination/fleet/claims/release",
        summary="Release file ownership claims for a session",
        tags=["Coordination"],
    )
    @require_permission("coordination:workspaces.write")
    def _handle_fleet_release(self, body: dict[str, Any]) -> HandlerResult:
        """Release ownership claims."""
        session_id = str(body.get("session_id", "")).strip()
        if not session_id:
            return error_response("session_id is required", 400)
        raw_paths = body.get("paths")
        paths: list[str] | None = None
        if raw_paths is not None:
            if not isinstance(raw_paths, list):
                return error_response("paths must be a list", 400)
            paths = [str(item) for item in raw_paths if str(item).strip()]
        repo_root = self._fleet_repo_root()
        store = self._fleet_store(repo_root)
        result = store.release_paths(session_id=session_id, paths=paths)
        return json_response(result)

    @api_endpoint(
        method="GET",
        path="/api/v1/coordination/fleet/merge-queue",
        summary="List merge queue items",
        tags=["Coordination"],
    )
    @require_permission("coordination:stats.read")
    def _handle_fleet_merge_queue(self, query_params: dict[str, Any]) -> HandlerResult:
        """List merge queue entries."""
        status = str(query_params.get("status", "")).strip()
        repo_root = self._fleet_repo_root()
        store = self._fleet_store(repo_root)
        queue = store.list_merge_queue(status=status or None)
        return json_response(
            {"repo_root": str(repo_root), "merge_queue": queue, "total": len(queue)}
        )

    @api_endpoint(
        method="POST",
        path="/api/v1/coordination/fleet/merge-queue",
        summary="Enqueue a branch merge request",
        tags=["Coordination"],
    )
    @require_permission("coordination:workspaces.write")
    def _handle_fleet_merge_enqueue(self, body: dict[str, Any]) -> HandlerResult:
        """Queue branch merge work in priority order."""
        session_id = str(body.get("session_id", "")).strip()
        if not session_id:
            return error_response("session_id is required", 400)
        branch = str(body.get("branch", "")).strip()
        if not branch:
            return error_response("branch is required", 400)
        title = str(body.get("title", "")).strip()
        priority_raw = body.get("priority", 50)
        try:
            priority = int(priority_raw)
        except (TypeError, ValueError):
            return error_response("priority must be an integer", 400)

        repo_root = self._fleet_repo_root()
        store = self._fleet_store(repo_root)
        result = store.enqueue_merge(
            session_id=session_id,
            branch=branch,
            priority=priority,
            title=title,
        )
        status_code = 200 if result.get("duplicate") else 201
        return json_response(result, status=status_code)


__all__ = ["CoordinationHandlerMixin"]
