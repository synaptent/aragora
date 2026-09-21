"""Decision Plan API handler.

Endpoints:
- POST /api/v1/plans                - Create plan from debate result
- GET  /api/v1/plans                - List plans with pagination
- GET  /api/v1/plans/{id}           - Get plan details
- POST /api/v1/plans/{id}/approve   - Approve a plan
- POST /api/v1/plans/{id}/reject    - Reject a plan with reason
- POST /api/v1/plans/{id}/execute   - Execute an approved plan
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.pipeline.decision_plan.core import DecisionPlan

from aragora.pipeline.backbone_errors import (
    BackbonePersistenceError,
    FAIL_CLOSED_BACKBONE_MESSAGE,
)
from aragora.pipeline.backbone_runtime import BackboneRuntime
from aragora.pipeline.execution_mode import ExecutionMode as SafetyMode
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.server.handlers.utils.routing import RouteDispatcher
from aragora.server.validation.query_params import safe_query_int

logger = logging.getLogger(__name__)

_RESERVED_BACKBONE_METADATA_KEYS = frozenset(
    {"backbone_entrypoint", "backbone_run_id", "source_id", "source_surface"}
)


def _fire_plan_notification(event: str, plan: Any, **kwargs: Any) -> None:
    """Fire-and-forget plan lifecycle notification.

    Runs async notification in background; never blocks the HTTP response.
    """
    import asyncio

    async def _send() -> None:
        try:
            from aragora.pipeline.notifications import (
                notify_plan_created,
                notify_plan_approved,
                notify_plan_rejected,
                notify_execution_started,
            )

            if event == "created":
                await notify_plan_created(plan)
            elif event == "approved":
                await notify_plan_approved(plan, approved_by=kwargs.get("approved_by", "unknown"))
            elif event == "rejected":
                await notify_plan_rejected(
                    plan,
                    rejected_by=kwargs.get("rejected_by", "unknown"),
                    reason=kwargs.get("reason", ""),
                )
            elif event == "execution_started":
                await notify_execution_started(plan)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
            logger.debug("Plan notification (%s) failed: %s", event, exc)

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_send())
        task.add_done_callback(
            lambda t: logger.warning("Plan notification failed: %s", t.exception())
            if not t.cancelled() and t.exception()
            else None
        )
    except RuntimeError:
        # No running loop (sync handler context) -- skip notification
        logger.debug("No event loop for plan notification (%s)", event)


# Paths this handler serves
_ROUTES = [
    "/api/v1/plans",
    "/api/plans",
]
_PLAN_PREFIX = "/api/v1/plans/"
_PLAN_PREFIX_UNVERSIONED = "/api/plans/"


def _get_plan_store():
    """Lazy import to avoid circular imports at module load time."""
    from aragora.pipeline.plan_store import get_plan_store

    return get_plan_store()


def _sanitize_plan_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Remove request-controlled keys reserved for backbone wiring."""
    return {
        key: value for key, value in metadata.items() if key not in _RESERVED_BACKBONE_METADATA_KEYS
    }


class PlansHandler(BaseHandler):
    """Handler for decision plan CRUD and approval workflows."""

    def __init__(self, ctx: dict[str, Any]) -> None:
        super().__init__(ctx)
        self._get_dispatcher = RouteDispatcher()
        self._get_dispatcher.add_route("/api/v1/plans", self._list_plans)
        self._get_dispatcher.add_route("/api/plans", self._list_plans)
        self._get_dispatcher.add_route("/api/v1/plans/{plan_id}", self._get_plan)
        self._get_dispatcher.add_route("/api/plans/{plan_id}", self._get_plan)

        self._post_dispatcher = RouteDispatcher()
        self._post_dispatcher.add_route("/api/v1/plans", self._create_plan)
        self._post_dispatcher.add_route("/api/plans", self._create_plan)
        self._post_dispatcher.add_route("/api/v1/plans/{plan_id}/approve", self._approve_plan)
        self._post_dispatcher.add_route("/api/plans/{plan_id}/approve", self._approve_plan)
        self._post_dispatcher.add_route("/api/v1/plans/{plan_id}/reject", self._reject_plan)
        self._post_dispatcher.add_route("/api/plans/{plan_id}/reject", self._reject_plan)
        self._post_dispatcher.add_route("/api/v1/plans/{plan_id}/execute", self._execute_plan)
        self._post_dispatcher.add_route("/api/plans/{plan_id}/execute", self._execute_plan)

    def can_handle(self, path: str) -> bool:
        """Check if this handler serves the given path."""
        if path in _ROUTES:
            return True
        if path.startswith(_PLAN_PREFIX) or path.startswith(_PLAN_PREFIX_UNVERSIONED):
            return True
        return False

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET requests (public read-only)."""
        self.set_request_context(handler, query_params)
        result = self._get_dispatcher.dispatch(path, query_params)
        if result is not None:
            return result
        # Try path param routes not matched by dispatcher segment count
        return self._try_get_by_id(path, query_params)

    @handle_errors("plans creation")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err
        _, perm_err = self.require_permission_or_error(handler, "plans:write")
        if perm_err:
            return perm_err

        self.set_request_context(handler, query_params)
        result = self._post_dispatcher.dispatch(path, query_params)
        if result is not None:
            return result
        return None

    # -------------------------------------------------------------------------
    # GET /api/v1/plans
    # -------------------------------------------------------------------------

    def _list_plans(self, query_params: dict[str, Any]) -> HandlerResult:
        """List plans with optional filters and pagination."""
        from aragora.pipeline.decision_plan.core import PlanStatus

        store = _get_plan_store()

        debate_id = query_params.get("debate_id")
        status_str = query_params.get("status")
        limit = safe_query_int(query_params, "limit", default=50, min_val=1, max_val=200)
        offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=100000)

        status = None
        if status_str:
            try:
                status = PlanStatus(status_str)
            except ValueError:
                return error_response(
                    f"Invalid status: {status_str}. "
                    f"Valid values: {', '.join(s.value for s in PlanStatus)}",
                    400,
                )

        plans = store.list(debate_id=debate_id, status=status, limit=limit, offset=offset)
        total = store.count(debate_id=debate_id, status=status)

        return json_response(
            {
                "plans": [self._plan_summary(p) for p in plans],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    # -------------------------------------------------------------------------
    # GET /api/v1/plans/{plan_id}
    # -------------------------------------------------------------------------

    def _get_plan(self, params: dict[str, str], query_params: dict[str, Any]) -> HandlerResult:
        """Get a single plan by ID."""
        plan_id = params["plan_id"]
        store = _get_plan_store()
        plan = store.get(plan_id)

        if plan is None:
            return error_response(f"Plan not found: {plan_id}", 404)

        return json_response(self._plan_detail(plan))

    def _try_get_by_id(self, path: str, query_params: dict[str, Any]) -> HandlerResult | None:
        """Fallback GET handler for /api/v1/plans/{id} paths."""
        for prefix in (_PLAN_PREFIX, _PLAN_PREFIX_UNVERSIONED):
            if path.startswith(prefix):
                remainder = path[len(prefix) :]
                if "/" not in remainder and remainder:
                    return self._get_plan({"plan_id": remainder}, query_params)
        return None

    # -------------------------------------------------------------------------
    # POST /api/v1/plans
    # -------------------------------------------------------------------------

    def _create_plan(self, query_params: dict[str, Any]) -> HandlerResult:
        """Create a new decision plan."""
        from aragora.pipeline.decision_plan.core import ApprovalMode, DecisionPlan, PlanStatus
        from aragora.server.decision_integrity_utils import (
            ensure_decision_plan_backbone_run,
            sync_decision_plan_backbone_receipt,
        )

        body = self.get_json_body()
        if body is None:
            return error_response("Invalid or missing JSON body", 400)

        debate_id = body.get("debate_id")
        task = body.get("task") or body.get("title") or body.get("summary")
        if not debate_id:
            return error_response("debate_id is required", 400)
        if not task:
            return error_response("task (or title/summary) is required", 400)

        # Optional fields
        approval_mode_str = body.get("approval_mode", "risk_based")
        try:
            approval_mode = ApprovalMode(approval_mode_str)
        except ValueError:
            return error_response(
                f"Invalid approval_mode: {approval_mode_str}. "
                f"Valid: {', '.join(m.value for m in ApprovalMode)}",
                400,
            )

        metadata = body.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        else:
            metadata = _sanitize_plan_metadata(metadata)

        # Action items from request body
        action_items = body.get("action_items", [])
        if isinstance(action_items, list):
            metadata["action_items"] = action_items

        plan = DecisionPlan(
            debate_id=str(debate_id),
            task=str(task),
            approval_mode=approval_mode,
            status=PlanStatus.AWAITING_APPROVAL
            if approval_mode != ApprovalMode.NEVER
            else PlanStatus.APPROVED,
            metadata=metadata,
        )

        # Budget
        budget_limit = body.get("estimated_budget") or body.get("budget_limit_usd")
        if budget_limit is not None:
            try:
                plan.budget.limit_usd = float(budget_limit)
            except (TypeError, ValueError):
                pass

        estimated_duration = body.get("estimated_duration")
        if estimated_duration:
            plan.metadata["estimated_duration"] = str(estimated_duration)

        store = _get_plan_store()
        user = self.get_current_user(self._current_handler) if self._current_handler else None
        run_id = ensure_decision_plan_backbone_run(
            plan,
            auth_context=user,
            source_surface="plans_api",
            source_id=str(debate_id),
        )
        store.create(plan)
        sync_decision_plan_backbone_receipt(plan, append_event=False)

        logger.info("Created plan %s for debate %s", plan.id, plan.debate_id)
        _fire_plan_notification("created", plan)

        response = self._plan_detail(plan)
        response["run_id"] = run_id
        return json_response(response, status=201)

    # -------------------------------------------------------------------------
    # POST /api/v1/plans/{plan_id}/approve
    # -------------------------------------------------------------------------

    def _approve_plan(self, params: dict[str, str], query_params: dict[str, Any]) -> HandlerResult:
        """Approve a decision plan. Requires plans:approve permission."""
        from aragora.pipeline.decision_plan.core import PlanStatus

        user, perm_err = self.require_permission_or_error(self._current_handler, "plans:approve")
        if perm_err:
            return perm_err

        plan_id = params["plan_id"]
        store = _get_plan_store()
        plan = store.get(plan_id)

        if plan is None:
            return error_response(f"Plan not found: {plan_id}", 404)

        if plan.status not in (PlanStatus.AWAITING_APPROVAL, PlanStatus.CREATED):
            return error_response(
                f"Plan {plan_id} cannot be approved (status: {plan.status.value})",
                409,
            )

        approver_id = getattr(user, "user_id", "unknown") if user else "unknown"
        runtime = BackboneRuntime(store)

        body = self.get_json_body() or {}
        reason = body.get("reason", "")
        conditions = body.get("conditions", [])

        plan.approve(approver_id, reason=str(reason), conditions=conditions)
        store.update_status(plan_id, PlanStatus.APPROVED, approved_by=approver_id)
        plan = store.get(plan_id) or plan
        runtime.sync_plan_receipt_to_run(plan, append_event=True)

        logger.info("Plan %s approved by %s", plan_id, approver_id)
        _fire_plan_notification("approved", plan, approved_by=approver_id)

        # Optionally trigger execution on approval
        auto_execute = body.get("auto_execute", False)
        execution_scheduled = False
        launch: dict[str, Any] | None = None
        execution_error = ""
        if auto_execute:
            try:
                from aragora.pipeline.canonical_execution import (
                    execute_queued_plan,
                    queue_plan_execution,
                    schedule_coroutine,
                )

                launch = queue_plan_execution(
                    plan,
                    auth_context=user,
                    execution_mode=body.get("execution_mode"),
                    safety_mode=SafetyMode.INTERACTIVE,
                )
                schedule_coroutine(
                    execute_queued_plan(
                        plan,
                        execution_id=str(launch["execution_id"]),
                        correlation_id=str(launch["correlation_id"]),
                        auth_context=user,
                        execution_mode=str(launch.get("execution_mode", "") or "").strip() or None,
                    ),
                    name=f"plan-approve-exec-{plan_id[:8]}",
                )
                execution_scheduled = True
                logger.info(
                    "Auto-execution queued for plan %s (execution_id=%s)",
                    plan_id,
                    launch.get("execution_id"),
                )
                _fire_plan_notification("execution_started", plan)
            except BackbonePersistenceError as exc:
                logger.warning("Auto-execution blocked for plan %s: %s", plan_id, exc)
                execution_error = FAIL_CLOSED_BACKBONE_MESSAGE
            except (ImportError, RuntimeError, AttributeError, ValueError, TypeError) as exc:
                logger.warning("Auto-execution scheduling failed for plan %s: %s", plan_id, exc)
                execution_error = str(exc)

        response: dict[str, Any] = {
            "plan_id": plan_id,
            "status": "approved",
            "approved_by": approver_id,
            "message": f"Plan {plan_id} approved successfully",
            "execution_scheduled": execution_scheduled,
        }
        if launch:
            response.update(
                {
                    "run_id": launch.get("run_id"),
                    "execution_id": launch.get("execution_id"),
                    "correlation_id": launch.get("correlation_id"),
                    "record_status": launch.get("status"),
                }
            )
        if execution_error:
            response["execution_error"] = execution_error
        return json_response(response)

    # -------------------------------------------------------------------------
    # POST /api/v1/plans/{plan_id}/reject
    # -------------------------------------------------------------------------

    def _reject_plan(self, params: dict[str, str], query_params: dict[str, Any]) -> HandlerResult:
        """Reject a decision plan with reason."""
        from aragora.pipeline.decision_plan.core import PlanStatus

        user, perm_err = self.require_permission_or_error(self._current_handler, "plans:deny")
        if perm_err:
            return perm_err

        plan_id = params["plan_id"]
        store = _get_plan_store()
        plan = store.get(plan_id)

        if plan is None:
            return error_response(f"Plan not found: {plan_id}", 404)

        if plan.status not in (PlanStatus.AWAITING_APPROVAL, PlanStatus.CREATED):
            return error_response(
                f"Plan {plan_id} cannot be rejected (status: {plan.status.value})",
                409,
            )

        body = self.get_json_body() or {}
        reason = body.get("reason", "")
        if not reason:
            return error_response("reason is required for rejection", 400)

        rejecter_id = getattr(user, "user_id", "unknown") if user else "unknown"
        runtime = BackboneRuntime(store)

        plan.reject(rejecter_id, reason=str(reason))
        store.update_status(
            plan_id,
            PlanStatus.REJECTED,
            approved_by=rejecter_id,
            rejection_reason=str(reason),
        )
        plan = store.get(plan_id) or plan
        runtime.sync_plan_receipt_to_run(plan, append_event=True)

        logger.info("Plan %s rejected by %s: %s", plan_id, rejecter_id, reason)
        _fire_plan_notification("rejected", plan, rejected_by=rejecter_id, reason=str(reason))

        return json_response(
            {
                "plan_id": plan_id,
                "status": "rejected",
                "rejected_by": rejecter_id,
                "reason": str(reason),
                "message": f"Plan {plan_id} rejected",
            }
        )

    # -------------------------------------------------------------------------
    # POST /api/v1/plans/{plan_id}/execute
    # -------------------------------------------------------------------------

    def _execute_plan(self, params: dict[str, str], query_params: dict[str, Any]) -> HandlerResult:
        """Execute an approved decision plan. Requires plans:approve permission.

        The plan must be in APPROVED status. Execution is scheduled as a
        background task and returns immediately with status 202 Accepted.
        """
        from aragora.pipeline.decision_plan.core import PlanStatus

        user, perm_err = self.require_permission_or_error(self._current_handler, "plans:approve")
        if perm_err:
            return perm_err

        plan_id = params["plan_id"]
        store = _get_plan_store()
        plan = store.get(plan_id)

        if plan is None:
            return error_response(f"Plan not found: {plan_id}", 404)

        if plan.status == PlanStatus.EXECUTING:
            return error_response(f"Plan {plan_id} is already executing", 409)
        if plan.status in (PlanStatus.COMPLETED, PlanStatus.FAILED):
            return error_response(
                f"Plan {plan_id} has already been executed ({plan.status.value})",
                409,
            )
        if plan.status not in (PlanStatus.APPROVED,):
            return error_response(
                f"Plan {plan_id} must be approved before execution (status: {plan.status.value})",
                409,
            )

        # Parse optional execution mode from body
        body = self.get_json_body() or {}
        execution_mode = body.get("execution_mode")

        try:
            from aragora.pipeline.canonical_execution import (
                execute_queued_plan,
                queue_plan_execution,
                schedule_coroutine,
            )

            launch = queue_plan_execution(
                plan,
                auth_context=user,
                execution_mode=execution_mode,
                safety_mode=SafetyMode.INTERACTIVE,
            )
            schedule_coroutine(
                execute_queued_plan(
                    plan,
                    execution_id=str(launch["execution_id"]),
                    correlation_id=str(launch["correlation_id"]),
                    auth_context=user,
                    execution_mode=str(launch.get("execution_mode", "") or "").strip() or None,
                ),
                name=f"plan-execute-{plan_id[:8]}",
            )
        except BackbonePersistenceError as exc:
            logger.warning("Interactive execution blocked for plan %s: %s", plan_id, exc)
            return error_response(FAIL_CLOSED_BACKBONE_MESSAGE, 503)
        except (ImportError, RuntimeError, AttributeError, ValueError, TypeError) as exc:
            logger.error("Failed to schedule execution for plan %s: %s", plan_id, exc)
            return error_response(f"Failed to schedule execution: {exc}", 500)

        logger.info("Execution scheduled for plan %s", plan_id)
        _fire_plan_notification("execution_started", plan)

        return json_response(
            {
                "plan_id": plan_id,
                "status": "executing",
                "message": f"Execution of plan {plan_id} has been scheduled",
                "run_id": launch.get("run_id"),
                "execution_id": launch.get("execution_id"),
                "correlation_id": launch.get("correlation_id"),
                "record_status": launch.get("status"),
            },
            status=202,
        )

    # -------------------------------------------------------------------------
    # Serialization helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _plan_summary(plan: DecisionPlan) -> dict[str, Any]:
        """Lightweight plan representation for list responses."""
        return {
            "id": plan.id,
            "debate_id": plan.debate_id,
            "task": plan.task[:200],
            "status": plan.status.value,
            "approval_mode": plan.approval_mode.value,
            "created_at": plan.created_at.isoformat(),
            "has_critical_risks": plan.has_critical_risks,
            "requires_human_approval": plan.requires_human_approval,
        }

    @staticmethod
    def _plan_detail(plan: DecisionPlan) -> dict[str, Any]:
        """Full plan representation for single-plan responses."""
        result = plan.to_dict()
        # Add action items from metadata for convenience
        action_items = (plan.metadata or {}).get("action_items", [])
        result["action_items"] = action_items
        result["estimated_duration"] = (plan.metadata or {}).get("estimated_duration")
        return result


__all__ = ["PlansHandler"]
