"""
Control Plane HTTP Handlers for Aragora.

Provides REST API endpoints for the enterprise control plane:
- Agent registration and discovery
- Task submission and status
- Health monitoring
- Control plane statistics and metrics
- Policy violations management

Endpoints:
    - GET  /api/control-plane/agents - List registered agents (also /api/v1/control-plane/agents)
    - POST /api/control-plane/agents - Register an agent (also /api/v1/control-plane/agents)
    - GET  /api/control-plane/agents/:id - Get agent info (also /api/v1/control-plane/agents/:id)
    - DELETE /api/control-plane/agents/:id - Unregister agent (also /api/v1/control-plane/agents/:id)
    - POST /api/control-plane/agents/:id/heartbeat - Send heartbeat
      (also /api/v1/control-plane/agents/:id/heartbeat)

    - POST /api/control-plane/tasks - Submit a task (also /api/v1/control-plane/tasks)
    - GET  /api/control-plane/tasks/:id - Get task status (also /api/v1/control-plane/tasks/:id)
    - POST /api/control-plane/tasks/:id/complete - Complete task
    - POST /api/control-plane/tasks/:id/fail - Fail task
    - POST /api/control-plane/tasks/:id/cancel - Cancel task
    - POST /api/control-plane/tasks/claim - Claim next task

    - POST /api/control-plane/deliberations - Run or queue a vetted decisionmaking session
    - GET  /api/control-plane/deliberations/:id - Get vetted decisionmaking result
    - GET  /api/control-plane/deliberations/:id/status - Get vetted decisionmaking status

    - GET  /api/control-plane/health - System health
    - GET  /api/control-plane/health/:agent_id - Agent health
    - GET  /api/control-plane/stats - Control plane statistics
    - GET  /api/control-plane/queue - Job queue (pending/running tasks)
    - GET  /api/control-plane/metrics - Dashboard metrics

    - GET  /api/control-plane/policies/violations - List policy violations
    - GET  /api/control-plane/policies/violations/stats - Policy violation statistics
    - GET  /api/control-plane/policies/violations/:id - Get violation details
    - PATCH /api/control-plane/policies/violations/:id - Update violation status
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from aragora.server.http_utils import run_async as _run_async
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    safe_error_message,
)
from aragora.server.handlers.utils.rate_limit import rate_limit, user_rate_limit
from aragora.server.handlers.utils.decorators import has_permission
from aragora.observability.metrics import track_handler
from aragora.tenancy.record_scope import OrgScope, require_org_scope

from .agents import AgentHandlerMixin
from aragora.server.handlers.utils.decorators import handle_errors
from .coordination import CoordinationHandlerMixin
from .tasks import TaskHandlerMixin
from .health import HealthHandlerMixin
from .policy import PolicyHandlerMixin

logger = logging.getLogger(__name__)


class ControlPlaneHandler(
    AgentHandlerMixin,
    CoordinationHandlerMixin,
    TaskHandlerMixin,
    HealthHandlerMixin,
    PolicyHandlerMixin,
    BaseHandler,
):
    """
    HTTP handler for control plane operations.

    Provides REST API access to the ControlPlaneCoordinator for
    agent management, task scheduling, and health monitoring.

    This class composes functionality from multiple mixins:
    - AgentHandlerMixin: Agent registration, discovery, lifecycle
    - TaskHandlerMixin: Task scheduling, claiming, completion
    - HealthHandlerMixin: Health monitoring, liveness probes
    - PolicyHandlerMixin: Policy violations, statistics
    """

    # Class-level coordinator (set during server initialization)
    coordinator: Any | None = None

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        if (
            os.environ.get("PYTEST_CURRENT_TEST")
            and self.ctx.get("control_plane_coordinator") is None
        ):
            self.__class__.coordinator = None

    def _get_coordinator(self) -> Any | None:
        """Get the control plane coordinator."""
        # Prefer class-level coordinator when set, otherwise fall back to context
        if self.__class__.coordinator is not None:
            return self.__class__.coordinator
        return self.ctx.get("control_plane_coordinator")

    def _require_coordinator(self) -> tuple[Any | None, HandlerResult | None]:
        """Return coordinator and None, or None and error response if not initialized."""
        coord = self._get_coordinator()
        if not coord:
            return None, error_response("Control plane not initialized", 503)
        return coord, None

    def _handle_coordinator_error(self, error: Exception, operation: str) -> HandlerResult:
        """Unified error handler for coordinator operations."""
        if isinstance(error, (ValueError, KeyError, AttributeError)):
            logger.warning("Data error in %s: %s: %s", operation, type(error).__name__, error)
            return error_response(safe_error_message(error, "control plane"), 400)
        logger.error("Error in %s: %s", operation, error)
        return error_response(safe_error_message(error, "control plane"), 500)

    def _get_stream(self) -> Any | None:
        """Get the control plane stream server for event emissions."""
        return self.ctx.get("control_plane_stream")

    def _normalize_path(self, path: str) -> str:
        """Normalize versioned control plane paths to legacy form."""
        if path.startswith("/api/v1/control-plane/"):
            return path.replace("/api/v1/control-plane", "/api/control-plane", 1)
        if path == "/api/v1/control-plane":
            return "/api/control-plane"
        return path

    def _emit_event(
        self,
        emit_method: str,
        *args: Any,
        max_retries: int = 3,
        base_delay: float = 0.1,
        **kwargs: Any,
    ) -> None:
        """Emit an event to the control plane stream with retry logic.

        Uses non-blocking retry scheduling to avoid blocking the thread pool.
        Retries are scheduled asynchronously using asyncio tasks when possible.

        Args:
            emit_method: Name of the emit method on the stream server
            *args: Positional arguments to pass to the emit method
            max_retries: Maximum number of retry attempts (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 0.1)
            **kwargs: Keyword arguments to pass to the emit method
        """
        stream = self._get_stream()
        if not stream:
            return

        method = getattr(stream, emit_method, None)
        if not method:
            return

        # Schedule async emission without blocking
        async def _do_emit_with_retry() -> None:
            last_error: Exception | None = None
            for attempt in range(max_retries):
                try:
                    await method(*args, **kwargs)
                    return  # Success
                except (OSError, RuntimeError, TimeoutError, ValueError, ConnectionError) as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2**attempt)
                        logger.debug(
                            f"Stream emission attempt {attempt + 1} failed, "
                            f"retrying in {delay:.2f}s: {e}"
                        )
                        await asyncio.sleep(delay)

            logger.warning(
                "Stream emission failed after %s attempts for %s: %s",
                max_retries,
                emit_method,
                last_error,
            )

        # Schedule the emission task without blocking
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_do_emit_with_retry())
            task.add_done_callback(
                lambda t: logger.error("Control plane emission failed: %s", t.exception())
                if not t.cancelled() and t.exception()
                else None
            )
        except RuntimeError:
            # No running event loop - use _run_async as fallback (single attempt)
            try:
                _run_async(method(*args, **kwargs))
            except (OSError, RuntimeError, TimeoutError, ValueError, ConnectionError) as e:
                logger.warning("Stream emission failed (no event loop): %s", e)

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = self._normalize_path(path)
        return normalized.startswith("/api/control-plane/") or path.startswith(
            "/api/v1/coordination/"
        )

    # =========================================================================
    # GET Handlers
    # =========================================================================

    @track_handler("control-plane/main", method="GET")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET requests."""
        path = self._normalize_path(path)

        # Deliberation results belong to an org: a caller without one gets the
        # scope denial (401 / 403 org_required) before any permission check.
        scope: OrgScope | None = None
        if path.startswith("/api/control-plane/deliberations/"):
            scope, scope_err = require_org_scope(handler)
            if scope is None:
                return scope_err

        # Auth and permission check
        user, err = self.require_auth_or_error(handler)
        if err:
            return err
        _, perm_err = self.require_permission_or_error(handler, "control-plane:read")
        if perm_err:
            return perm_err

        # /api/control-plane/deliberations/:id[/status]
        if scope is not None:
            parts = path.split("/")
            if len(parts) >= 5:
                request_id = parts[4]
                if len(parts) >= 6 and parts[5] == "status":
                    return self._handle_get_deliberation_status(request_id, handler, scope)
                return self._handle_get_deliberation(request_id, handler, scope)

        # /api/control-plane/agents
        if path == "/api/control-plane/agents":
            return self._handle_list_agents(query_params)

        # /api/control-plane/agents/:id
        if path.startswith("/api/control-plane/agents/") and path.count("/") == 4:
            agent_id = path.split("/")[-1]
            return self._handle_get_agent(agent_id)

        # /api/control-plane/tasks/:id
        if path.startswith("/api/control-plane/tasks/") and path.count("/") == 4:
            task_id = path.split("/")[-1]
            return self._handle_get_task(task_id)

        # /api/control-plane/health
        if path == "/api/control-plane/health":
            return self._handle_system_health()

        # /api/control-plane/health/detailed
        if path == "/api/control-plane/health/detailed":
            return self._handle_detailed_health()

        # /api/control-plane/breakers
        if path == "/api/control-plane/breakers":
            return self._handle_circuit_breakers()

        # /api/control-plane/queue/metrics
        if path == "/api/control-plane/queue/metrics":
            return self._handle_queue_metrics()

        # /api/control-plane/health/:agent_id
        if path.startswith("/api/control-plane/health/") and path.count("/") == 4:
            agent_id = path.split("/")[-1]
            if agent_id != "detailed":
                return self._handle_agent_health(agent_id)

        # /api/control-plane/stats
        if path == "/api/control-plane/stats":
            return self._handle_stats()

        # /api/control-plane/queue
        if path == "/api/control-plane/queue":
            return self._handle_get_queue(query_params)

        # /api/control-plane/metrics
        if path == "/api/control-plane/metrics":
            return self._handle_get_metrics()

        # /api/control-plane/notifications
        if path == "/api/control-plane/notifications":
            return self._handle_get_notifications(query_params)

        # /api/control-plane/notifications/stats
        if path == "/api/control-plane/notifications/stats":
            return self._handle_get_notification_stats()

        # /api/control-plane/audit
        if path == "/api/control-plane/audit":
            return self._handle_get_audit_logs(query_params, handler)

        # /api/control-plane/audit/stats
        if path == "/api/control-plane/audit/stats":
            return self._handle_get_audit_stats()

        # /api/control-plane/audit/verify
        if path == "/api/control-plane/audit/verify":
            return self._handle_verify_audit_integrity(query_params, handler)

        # /api/control-plane/policies/violations/stats
        if path == "/api/control-plane/policies/violations/stats":
            return self._handle_get_policy_violation_stats(handler)

        # /api/control-plane/policies/violations
        if path == "/api/control-plane/policies/violations":
            return self._handle_list_policy_violations(query_params, handler)

        # /api/control-plane/policies/violations/:id
        if path.startswith("/api/control-plane/policies/violations/") and path.count("/") == 5:
            violation_id = path.split("/")[-1]
            return self._handle_get_policy_violation(violation_id, handler)

        # === Coordination Routes (versioned, /api/v1/coordination/...) ===
        # _normalize_path only changes /api/v1/control-plane/ prefixes, so
        # /api/v1/coordination/ paths pass through unchanged in `path`.

        # /api/v1/coordination/workspaces
        if path == "/api/v1/coordination/workspaces":
            return self._handle_list_workspaces(query_params)

        # /api/v1/coordination/federation
        if path == "/api/v1/coordination/federation":
            return self._handle_list_federation_policies(query_params)

        # /api/v1/coordination/executions
        if path == "/api/v1/coordination/executions":
            return self._handle_list_executions(query_params)

        # /api/v1/coordination/fleet/status
        if path == "/api/v1/coordination/fleet/status":
            return self._handle_fleet_status(query_params)

        # /api/v1/coordination/active-work
        if path == "/api/v1/coordination/active-work":
            return self._handle_active_work(query_params)

        # /api/v1/coordination/fleet/logs
        if path == "/api/v1/coordination/fleet/logs":
            return self._handle_fleet_logs(query_params)

        # /api/v1/coordination/fleet/claims
        if path == "/api/v1/coordination/fleet/claims":
            return self._handle_fleet_claims(query_params)

        # /api/v1/coordination/fleet/merge-queue
        if path == "/api/v1/coordination/fleet/merge-queue":
            return self._handle_fleet_merge_queue(query_params)

        # /api/v1/coordination/swarm/integrator
        if path == "/api/v1/coordination/swarm/integrator":
            return self._handle_swarm_integrator(query_params)

        # /api/v1/coordination/consent
        if path == "/api/v1/coordination/consent":
            return self._handle_list_consents(query_params)

        # /api/v1/coordination/stats
        if path == "/api/v1/coordination/stats":
            return self._handle_coordination_stats(query_params)

        # /api/v1/coordination/health
        if path == "/api/v1/coordination/health":
            return self._handle_coordination_health(query_params)

        return None

    # =========================================================================
    # POST Handlers
    # =========================================================================

    @track_handler("control-plane/main", method="POST")
    @user_rate_limit(action="agent_call")
    @rate_limit(requests_per_minute=60, limiter_name="control_plane_post")
    @handle_errors
    async def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests."""
        path = self._normalize_path(path)

        # A deliberation is owned by the creator's org, as on the reads.
        scope: OrgScope | None = None
        if path == "/api/control-plane/deliberations":
            scope, scope_err = require_org_scope(handler)
            if scope is None:
                return scope_err

        # Auth and permission check
        user, err = self.require_auth_or_error(handler)
        if err:
            return err
        _, perm_err = self.require_permission_or_error(handler, "control-plane:write")
        if perm_err:
            return perm_err

        # /api/control-plane/deliberations
        if scope is not None:
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return await self._handle_submit_deliberation(body, handler, scope)

        # /api/control-plane/agents
        if path == "/api/control-plane/agents":
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return await self._handle_register_agent_async(body, handler)

        # /api/control-plane/agents/:id/heartbeat
        if path.endswith("/heartbeat") and "/agents/" in path:
            parts = path.split("/")
            if len(parts) >= 5:
                agent_id = parts[-2]
                body, err = self.read_json_body_validated(handler)
                if err:
                    return err
                return await self._handle_heartbeat_async(agent_id, body, handler)

        # /api/control-plane/tasks
        if path == "/api/control-plane/tasks":
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return await self._handle_submit_task_async(body, handler)

        # /api/control-plane/tasks/:id/complete
        if path.endswith("/complete") and "/tasks/" in path:
            parts = path.split("/")
            if len(parts) >= 5:
                task_id = parts[-2]
                body, err = self.read_json_body_validated(handler)
                if err:
                    return err
                return await self._handle_complete_task_async(task_id, body, handler)

        # /api/control-plane/tasks/:id/fail
        if path.endswith("/fail") and "/tasks/" in path:
            parts = path.split("/")
            if len(parts) >= 5:
                task_id = parts[-2]
                body, err = self.read_json_body_validated(handler)
                if err:
                    return err
                return await self._handle_fail_task_async(task_id, body, handler)

        # /api/control-plane/tasks/:id/cancel
        if path.endswith("/cancel") and "/tasks/" in path:
            parts = path.split("/")
            if len(parts) >= 5:
                task_id = parts[-2]
                return await self._handle_cancel_task_async(task_id, handler)

        # /api/control-plane/tasks/:id/claim
        if path.endswith("/claim") and "/tasks/" in path:
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return await self._handle_claim_task_async(body, handler)

        # === Coordination POST Routes ===
        # /api/v1/coordination/workspaces
        if path == "/api/v1/coordination/workspaces":
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_register_workspace(body)

        # /api/v1/coordination/federation
        if path == "/api/v1/coordination/federation":
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_create_federation_policy(body)

        # /api/v1/coordination/execute
        if path == "/api/v1/coordination/execute":
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_execute(body)

        # /api/v1/coordination/consent
        if path == "/api/v1/coordination/consent":
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_grant_consent(body)

        # /api/v1/coordination/fleet/claims
        if path == "/api/v1/coordination/fleet/claims":
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_fleet_claim(body)

        # /api/v1/coordination/fleet/claims/release
        if path == "/api/v1/coordination/fleet/claims/release":
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_fleet_release(body)

        # /api/v1/coordination/fleet/merge-queue
        if path == "/api/v1/coordination/fleet/merge-queue":
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_fleet_merge_enqueue(body)

        # /api/v1/coordination/swarm/integrator/*
        if path == "/api/v1/coordination/swarm/integrator/merge":
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_swarm_integrator_merge(body)

        if path == "/api/v1/coordination/swarm/integrator/archive":
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_swarm_integrator_archive(body)

        if path == "/api/v1/coordination/swarm/integrator/supersede":
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_swarm_integrator_supersede(body)

        # /api/v1/coordination/approve/:id
        if path.startswith("/api/v1/coordination/approve/"):
            request_id = path.split("/")[-1]
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_approve_request(request_id, body)

        return None

    # =========================================================================
    # DELETE Handlers
    # =========================================================================

    @track_handler("control-plane/main", method="DELETE")
    @handle_errors
    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle DELETE requests."""
        normalized = self._normalize_path(path)

        # /api/control-plane/agents/:id
        if normalized.startswith("/api/control-plane/agents/") and normalized.count("/") == 4:
            agent_id = normalized.split("/")[-1]
            return self._handle_unregister_agent(agent_id, handler)

        # /api/v1/coordination/workspaces/:id
        if path.startswith("/api/v1/coordination/workspaces/") and path.count("/") == 5:
            workspace_id = path.split("/")[-1]
            return self._handle_unregister_workspace(workspace_id)

        # /api/v1/coordination/consent/:id
        if path.startswith("/api/v1/coordination/consent/") and path.count("/") == 5:
            consent_id = path.split("/")[-1]
            return self._handle_revoke_consent(consent_id, {})

        return None

    # =========================================================================
    # PATCH Handlers
    # =========================================================================

    @track_handler("control-plane/main", method="PATCH")
    @handle_errors
    def handle_patch(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle PATCH requests."""
        path = self._normalize_path(path)

        # /api/control-plane/policies/violations/:id
        if path.startswith("/api/control-plane/policies/violations/") and path.count("/") == 5:
            violation_id = path.split("/")[-1]
            body, err = self.read_json_body_validated(handler)
            if err:
                return err
            return self._handle_update_policy_violation(violation_id, body, handler)

        return None


__all__ = ["ControlPlaneHandler", "has_permission"]
