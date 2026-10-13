"""Decision Pipeline HTTP handlers.

Endpoints for the gold path: debate -> plan -> approve -> execute -> verify -> learn.

All endpoints require authentication.
Read operations require `decisions:read`.
Write operations require `decisions:create` or `decisions:update`.

Endpoints:
    POST   /api/v1/decisions/plans              - Create plan from debate result
    GET    /api/v1/decisions/plans              - List plans
    GET    /api/v1/decisions/plans/{plan_id}    - Get plan details
    POST   /api/v1/decisions/plans/{plan_id}/approve - Approve plan
    POST   /api/v1/decisions/plans/{plan_id}/reject  - Reject plan
    POST   /api/v1/decisions/plans/{plan_id}/execute - Execute approved plan
    GET    /api/v1/decisions/plans/{plan_id}/outcome - Get execution outcome

Stability: ALPHA
"""

from __future__ import annotations

__all__ = ["DecisionPipelineHandler"]

import logging
from typing import TYPE_CHECKING, Any, cast

from aragora.pipeline.backbone_errors import (
    BackbonePersistenceError,
    FAIL_CLOSED_BACKBONE_MESSAGE,
)
from aragora.pipeline.decision_plan.factory import normalize_execution_mode
from aragora.pipeline.execution_mode import ExecutionMode as SafetyMode
from aragora.resilience import get_circuit_breaker
from aragora.pipeline.decision_integrity_utils import (
    ensure_decision_plan_backbone_run,
    execute_decision_plan_with_backbone,
    sync_decision_plan_backbone_receipt,
)

from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..secure import SecureHandler
from ..utils.rate_limit import RateLimiter

if TYPE_CHECKING:
    from aragora.protocols import HTTPRequestHandler
    from aragora.pipeline.executor import ExecutionMode

logger = logging.getLogger(__name__)

# Circuit breaker for pipeline operations
_pipeline_cb = None

# Rate limiter (60 requests per minute for pipeline ops)
_pipeline_limiter = RateLimiter(requests_per_minute=60)
_RESERVED_BACKBONE_METADATA_KEYS = frozenset(
    {"backbone_entrypoint", "backbone_run_id", "source_id", "source_surface"}
)


def _get_circuit_breaker():  # type: ignore[no-untyped-def]
    global _pipeline_cb
    if _pipeline_cb is None:
        _pipeline_cb = get_circuit_breaker(
            "decision_pipeline",
            failure_threshold=5,
            cooldown_seconds=30,
        )
    return _pipeline_cb


def _normalize_string_list(value: Any, field_name: str) -> list[str] | None:
    """Validate and normalize comma-separated or list-based string fields."""
    if value is None:
        return None
    if isinstance(value, str):
        split_items = [item.strip() for item in value.split(",") if item.strip()]
        return split_items or None
    if isinstance(value, (list, tuple)):
        normalized_items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"{field_name} must be a string or list of strings")
            normalized = item.strip()
            if normalized:
                normalized_items.append(normalized)
        return normalized_items or None
    raise ValueError(f"{field_name} must be a string or list of strings")


def _normalize_thread_map(value: Any) -> dict[str, str] | None:
    """Validate and normalize per-platform thread mapping."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("thread_id_by_platform must be an object")

    normalized: dict[str, str] = {}
    for raw_platform, raw_thread in value.items():
        if not isinstance(raw_platform, str) or not isinstance(raw_thread, str):
            raise ValueError("thread_id_by_platform keys and values must be strings")
        platform = raw_platform.strip()
        thread = raw_thread.strip()
        if platform and thread:
            normalized[platform] = thread
    return normalized or None


def _build_implementation_profile_payload(body: dict[str, Any]) -> dict[str, Any] | None:
    """Build an implementation profile payload from request fields."""
    profile = body.get("implementation_profile")
    payload: dict[str, Any] = dict(profile) if isinstance(profile, dict) else {}

    def _maybe_set(key: str, value: Any) -> None:
        if value is None:
            return
        if key not in payload:
            payload[key] = value

    _maybe_set(
        "execution_mode",
        normalize_execution_mode(body.get("execution_engine") or body.get("execution_mode")),
    )
    _maybe_set("implementers", body.get("implementers"))
    _maybe_set("critic", body.get("critic"))
    _maybe_set("reviser", body.get("reviser"))
    _maybe_set("strategy", body.get("strategy"))
    _maybe_set("max_revisions", body.get("max_revisions"))
    _maybe_set("parallel_execution", body.get("parallel_execution"))
    _maybe_set("max_parallel", body.get("max_parallel"))
    _maybe_set(
        "complexity_router", body.get("complexity_router") or body.get("agent_by_complexity")
    )
    _maybe_set("task_type_router", body.get("task_type_router") or body.get("agent_by_task_type"))
    _maybe_set(
        "capability_router",
        body.get("capability_router") or body.get("agent_by_capability"),
    )
    _maybe_set("fabric_models", body.get("fabric_models"))
    _maybe_set("fabric_pool_id", body.get("fabric_pool_id"))
    _maybe_set("fabric_min_agents", body.get("fabric_min_agents"))
    _maybe_set("fabric_max_agents", body.get("fabric_max_agents"))
    _maybe_set("fabric_timeout_seconds", body.get("fabric_timeout_seconds"))
    _maybe_set("channel_targets", body.get("channel_targets") or body.get("chat_targets"))
    _maybe_set("thread_id", body.get("thread_id") or body.get("origin_thread_id"))
    _maybe_set("thread_id_by_platform", body.get("thread_id_by_platform"))

    if "channel_targets" in payload:
        normalized_targets = _normalize_string_list(
            payload.get("channel_targets"), "channel_targets"
        )
        if normalized_targets is None:
            payload.pop("channel_targets", None)
        else:
            payload["channel_targets"] = normalized_targets

    if "thread_id" in payload:
        thread_id = payload.get("thread_id")
        if thread_id is None:
            payload.pop("thread_id", None)
        elif not isinstance(thread_id, str) or not thread_id.strip():
            raise ValueError("thread_id must be a non-empty string")
        else:
            payload["thread_id"] = thread_id.strip()

    if "thread_id_by_platform" in payload:
        normalized_map = _normalize_thread_map(payload.get("thread_id_by_platform"))
        if normalized_map is None:
            payload.pop("thread_id_by_platform", None)
        else:
            payload["thread_id_by_platform"] = normalized_map

    return payload or None


def _sanitize_plan_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Remove request-controlled keys reserved for backbone wiring."""
    return {
        key: value for key, value in metadata.items() if key not in _RESERVED_BACKBONE_METADATA_KEYS
    }


# RBAC permission keys
DECISION_READ_PERMISSION = "decisions:read"
DECISION_CREATE_PERMISSION = "decisions:create"
DECISION_UPDATE_PERMISSION = "decisions:update"


class DecisionPipelineHandler(SecureHandler):
    """HTTP handlers for the decision pipeline (gold path).

    Requires authentication. Read operations require decisions:read.
    Write operations require decisions:create or decisions:update.
    """

    ROUTES: list[str] = [
        "/api/v1/decisions/plans",
        "/api/v1/decisions/plans/*",
        "/api/v1/decisions/plans/*/approve",
        "/api/v1/decisions/plans/*/reject",
        "/api/v1/decisions/plans/*/execute",
        "/api/v1/decisions/plans/*/outcome",
    ]

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        if path == "/api/v1/decisions/plans":
            return True
        if path.startswith("/api/v1/decisions/plans/"):
            return True
        return False

    def _extract_plan_id(self, path: str) -> str | None:
        """Extract plan_id from path like /api/v1/decisions/plans/{plan_id}/..."""
        parts = path.split("/")
        # /api/v1/decisions/plans/{plan_id} -> ["", "api", "v1", "decisions", "plans", "{plan_id}", ...]
        if len(parts) >= 6:
            return parts[5]
        return None

    def _check_circuit_breaker(self) -> HandlerResult | None:
        """Check circuit breaker state."""
        cb = _get_circuit_breaker()
        if not cb.can_execute():
            return error_response("Decision pipeline temporarily unavailable", 503)
        return None

    # -----------------------------------------------------------------
    # GET handlers
    # -----------------------------------------------------------------

    @handle_errors("decision pipeline GET")
    def handle(
        self, path: str, query_params: dict[str, Any], handler: HTTPRequestHandler
    ) -> HandlerResult | None:
        """Handle GET requests for decision pipeline."""
        # Check circuit breaker
        cb_err = self._check_circuit_breaker()
        if cb_err:
            return cb_err

        # Check auth
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        # Check read permission
        _, perm_err = self.require_permission_or_error(handler, DECISION_READ_PERMISSION)
        if perm_err:
            return perm_err

        # Route based on path
        if path == "/api/v1/decisions/plans":
            return self._handle_list_plans(query_params, handler)

        plan_id = self._extract_plan_id(path)
        if not plan_id:
            return error_response("Invalid plan path", 400)

        if path.endswith("/outcome"):
            return self._handle_get_outcome(plan_id, handler)

        # Default: get plan details
        if path == f"/api/v1/decisions/plans/{plan_id}":
            return self._handle_get_plan(plan_id, handler)

        return None

    def _handle_list_plans(
        self, query_params: dict[str, Any], handler: HTTPRequestHandler
    ) -> HandlerResult:
        """List decision plans with optional status filter."""
        from aragora.pipeline.decision_plan import PlanStatus
        from aragora.pipeline.executor import list_plans

        status_str = query_params.get("status")
        status_filter = None
        if status_str:
            try:
                status_filter = PlanStatus(status_str)
            except ValueError:
                return error_response(f"Invalid status: {status_str}", 400)

        limit = 50
        limit_str = query_params.get("limit")
        if limit_str:
            try:
                limit = min(200, max(1, int(limit_str)))
            except ValueError:
                pass

        plans = list_plans(status=status_filter, limit=limit)

        return json_response(
            {
                "success": True,
                "plans": [p.to_dict() for p in plans],
                "count": len(plans),
            }
        )

    def _handle_get_plan(self, plan_id: str, handler: HTTPRequestHandler) -> HandlerResult:
        """Get details of a specific decision plan."""
        from aragora.pipeline.executor import get_outcome, get_plan

        plan = get_plan(plan_id)
        if not plan:
            return error_response("Plan not found", 404)

        result: dict[str, Any] = {
            "success": True,
            "plan": plan.to_dict(),
        }

        # Include outcome if execution completed
        outcome = get_outcome(plan_id)
        if outcome:
            result["outcome"] = outcome.to_dict()

        return json_response(result)

    def _handle_get_outcome(self, plan_id: str, handler: HTTPRequestHandler) -> HandlerResult:
        """Get the execution outcome for a completed plan."""
        from aragora.pipeline.executor import get_outcome, get_plan

        plan = get_plan(plan_id)
        if not plan:
            return error_response("Plan not found", 404)

        outcome = get_outcome(plan_id)
        if not outcome:
            return error_response("No outcome recorded yet", 404)

        return json_response(
            {
                "success": True,
                "outcome": outcome.to_dict(),
            }
        )

    # -----------------------------------------------------------------
    # POST handlers
    # -----------------------------------------------------------------

    @handle_errors("decision pipeline POST")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: HTTPRequestHandler
    ) -> HandlerResult | None:
        """Handle POST requests for decision pipeline."""
        # Check circuit breaker
        cb_err = self._check_circuit_breaker()
        if cb_err:
            return cb_err

        # Check auth
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        # Route based on path
        if path == "/api/v1/decisions/plans":
            _, perm_err = self.require_permission_or_error(handler, DECISION_CREATE_PERMISSION)
            if perm_err:
                return perm_err
            return self._handle_create_plan(handler, user)

        plan_id = self._extract_plan_id(path)
        if not plan_id:
            return error_response("Invalid plan path", 400)

        if path.endswith("/approve"):
            _, perm_err = self.require_permission_or_error(handler, DECISION_UPDATE_PERMISSION)
            if perm_err:
                return perm_err
            return self._handle_approve_plan(plan_id, handler, user)
        if path.endswith("/reject"):
            _, perm_err = self.require_permission_or_error(handler, DECISION_UPDATE_PERMISSION)
            if perm_err:
                return perm_err
            return self._handle_reject_plan(plan_id, handler, user)
        if path.endswith("/execute"):
            _, perm_err = self.require_permission_or_error(handler, DECISION_UPDATE_PERMISSION)
            if perm_err:
                return perm_err
            return self._handle_execute_plan(plan_id, handler, user)

        return None

    def _handle_create_plan(self, handler: HTTPRequestHandler, user: Any) -> HandlerResult:
        """Create a DecisionPlan from a completed debate."""
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        debate_id = body.get("debate_id")
        if not debate_id:
            return error_response("debate_id is required", 400)

        # Load debate result
        from aragora.utils.async_utils import get_event_loop_safe

        debate_result = get_event_loop_safe().run_until_complete(
            _load_debate_result(debate_id, self.ctx)
        )
        if debate_result is None:
            return error_response(f"Debate {debate_id} not found", 404)

        # Parse options
        from aragora.pipeline.decision_plan import (
            ApprovalMode,
            DecisionPlanFactory,
        )
        from aragora.pipeline.risk_register import RiskLevel

        approval_mode_str = body.get("approval_mode", "risk_based")
        try:
            approval_mode = ApprovalMode(approval_mode_str)
        except ValueError:
            allowed_values = ", ".join(m.value for m in ApprovalMode)
            return error_response(
                f"Invalid approval_mode: {approval_mode_str}. Allowed values: {allowed_values}",
                400,
            )

        max_auto_risk_str = body.get("max_auto_risk", "low")
        try:
            max_auto_risk = RiskLevel(max_auto_risk_str)
        except ValueError:
            allowed_values = ", ".join(r.value for r in RiskLevel)
            return error_response(
                f"Invalid max_auto_risk: {max_auto_risk_str}. Allowed values: {allowed_values}",
                400,
            )

        budget_limit = body.get("budget_limit_usd")
        if budget_limit is not None:
            try:
                budget_limit = float(budget_limit)
            except (TypeError, ValueError):
                return error_response("budget_limit_usd must be a valid number", 400)
            if budget_limit < 0:
                return error_response("budget_limit_usd must be >= 0", 400)

        metadata = body.get("metadata")
        if metadata is None:
            metadata = {}
        elif not isinstance(metadata, dict):
            return error_response("metadata must be an object", 400)
        else:
            metadata = _sanitize_plan_metadata(metadata)

        # Pass operational mode through to metadata for downstream consumption
        request_mode = body.get("mode")
        if request_mode and isinstance(request_mode, str):
            metadata["operational_mode"] = request_mode

        try:
            implementation_profile = _build_implementation_profile_payload(body)
        except ValueError as exc:
            return error_response(str(exc), 400)

        # Build the plan
        plan = DecisionPlanFactory.from_debate_result(
            debate_result,
            budget_limit_usd=budget_limit,
            approval_mode=approval_mode,
            max_auto_risk=max_auto_risk,
            metadata=metadata,
            implementation_profile=implementation_profile,
        )

        run_id = ensure_decision_plan_backbone_run(
            plan,
            auth_context=user,
            source_surface="decision_pipeline",
            source_id=str(debate_id),
        )

        # Store it
        from aragora.pipeline.executor import store_plan

        store_plan(plan)
        sync_decision_plan_backbone_receipt(plan, append_event=False)

        # Notify approvers if human approval is required
        if plan.requires_human_approval:
            try:
                from aragora.approvals.chat import send_chat_approval_request
                from aragora.utils.async_utils import run_async

                approval_targets = (
                    body.get("approval_targets")
                    or body.get("approval_channels")
                    or plan.metadata.get("approval_targets")
                    or plan.metadata.get("approval_channels")
                    or []
                )
                thread_id = None
                if isinstance(approval_targets, str):
                    approval_targets = [approval_targets]

                if not approval_targets:
                    try:
                        from aragora.server.debate_origin import get_debate_origin

                        origin = get_debate_origin(plan.debate_id)
                        if origin:
                            approval_targets = [f"{origin.platform}:{origin.channel_id}"]
                            thread_id = origin.thread_id
                    except (ImportError, AttributeError):
                        approval_targets = approval_targets or []

                fields = [
                    ("Plan ID", plan.id),
                    ("Debate ID", plan.debate_id),
                    ("Status", plan.status.value),
                ]
                if plan.risk_register:
                    fields.append(("Risk Level", plan.highest_risk_level.value))
                if plan.debate_result:
                    fields.append(("Confidence", f"{plan.debate_result.confidence:.0%}"))

                if approval_targets:
                    run_async(
                        send_chat_approval_request(
                            title="Decision Plan Approval Required",
                            description=plan.task,
                            fields=fields,
                            targets=list(approval_targets),
                            kind="decision_plan",
                            target_id=plan.id,
                            ttl_seconds=24 * 3600,
                            extra_text="Reply with Approve/Reject to continue.",
                            thread_id=thread_id,
                        )
                    )
            except (ImportError, RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
                logger.debug("Plan approval notification skipped: %s", e)

        logger.info(
            "Created decision plan %s from debate %s (status=%s)",
            plan.id,
            debate_id,
            plan.status.value,
        )

        return json_response(
            {
                "success": True,
                "plan": plan.to_dict(),
                "run_id": run_id,
            },
            status=201,
        )

    def _handle_approve_plan(
        self, plan_id: str, handler: HTTPRequestHandler, user: Any
    ) -> HandlerResult:
        """Approve a decision plan for execution."""
        from aragora.pipeline.decision_plan import PlanStatus
        from aragora.pipeline.executor import get_plan, store_plan

        plan = get_plan(plan_id)
        if not plan:
            return error_response("Plan not found", 404)

        if plan.status not in (PlanStatus.CREATED, PlanStatus.AWAITING_APPROVAL):
            return error_response(
                f"Plan cannot be approved in status: {plan.status.value}",
                409,
            )

        body = self.read_json_body(handler) or {}

        approver_id = getattr(user, "user_id", "unknown")
        reason = body.get("reason", "")
        conditions = body.get("conditions", [])

        plan.approve(
            approver_id=approver_id,
            reason=reason,
            conditions=conditions,
        )
        store_plan(plan)

        logger.info("Plan %s approved by %s", plan_id, approver_id)

        return json_response(
            {
                "success": True,
                "plan": {
                    "id": plan.id,
                    "status": plan.status.value,
                    "approval_record": plan.approval_record.to_dict()
                    if plan.approval_record
                    else None,
                },
            }
        )

    def _handle_reject_plan(
        self, plan_id: str, handler: HTTPRequestHandler, user: Any
    ) -> HandlerResult:
        """Reject a decision plan."""
        from aragora.pipeline.decision_plan import PlanStatus
        from aragora.pipeline.executor import get_plan, store_plan

        plan = get_plan(plan_id)
        if not plan:
            return error_response("Plan not found", 404)

        if plan.status not in (PlanStatus.CREATED, PlanStatus.AWAITING_APPROVAL):
            return error_response(
                f"Plan cannot be rejected in status: {plan.status.value}",
                409,
            )

        body = self.read_json_body(handler) or {}

        approver_id = getattr(user, "user_id", "unknown")
        reason = body.get("reason", "No reason provided")

        plan.reject(approver_id=approver_id, reason=reason)
        store_plan(plan)

        logger.info("Plan %s rejected by %s: %s", plan_id, approver_id, reason)

        return json_response(
            {
                "success": True,
                "plan": {
                    "id": plan.id,
                    "status": plan.status.value,
                    "approval_record": plan.approval_record.to_dict()
                    if plan.approval_record
                    else None,
                },
            }
        )

    def _handle_execute_plan(
        self, plan_id: str, handler: HTTPRequestHandler, user: Any
    ) -> HandlerResult:
        """Execute an approved decision plan."""
        from aragora.utils.async_utils import get_event_loop_safe

        from aragora.pipeline.executor import PlanExecutor, get_plan
        from aragora.rbac.models import AuthorizationContext

        plan = get_plan(plan_id)
        if not plan:
            return error_response("Plan not found", 404)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        allowed_execution_modes = {"workflow", "hybrid", "fabric", "computer_use"}
        raw_execution_mode = body.get("execution_mode")
        execution_mode = normalize_execution_mode(raw_execution_mode)
        if raw_execution_mode is not None:
            if (
                not isinstance(raw_execution_mode, str)
                or execution_mode not in allowed_execution_modes
            ):
                allowed = ", ".join(sorted(allowed_execution_modes))
                return error_response(
                    f"Invalid execution_mode: {raw_execution_mode}. Allowed values: {allowed}",
                    400,
                )
        execution_mode_typed = cast("ExecutionMode | None", execution_mode)

        parallel_execution = body.get("parallel_execution")
        if parallel_execution is not None and not isinstance(parallel_execution, bool):
            return error_response("parallel_execution must be a boolean", 400)

        max_parallel = body.get("max_parallel")
        if max_parallel is not None:
            try:
                max_parallel = int(max_parallel)
            except (TypeError, ValueError):
                return error_response("max_parallel must be an integer", 400)
            if max_parallel < 1:
                return error_response("max_parallel must be >= 1", 400)

        # Build authorization context from user for defense-in-depth permission checks
        # Note: handler-level permission check already passed (DECISION_UPDATE_PERMISSION)
        role_values = set(getattr(user, "roles", []) or [])
        single_role = getattr(user, "role", None)
        if single_role:
            role_values.add(single_role)

        permissions = set(getattr(user, "permissions", []) or [])
        # Executor still checks for decisions:execute. We add it after update
        # permission verification for backwards compatibility.
        permissions.add("decisions:execute")

        auth_context = AuthorizationContext(
            user_id=getattr(user, "user_id", None) or "unknown",
            user_email=getattr(user, "email", None),
            org_id=getattr(user, "org_id", None),
            roles=role_values or {"member"},
            permissions=permissions,
        )

        executor = PlanExecutor(
            parallel_execution=bool(parallel_execution),
            max_parallel=max_parallel,
        )

        try:
            launch, outcome = get_event_loop_safe().run_until_complete(
                execute_decision_plan_with_backbone(
                    plan,
                    executor=executor,
                    auth_context=auth_context,
                    execution_mode=execution_mode_typed,
                    safety_mode=SafetyMode.INTERACTIVE,
                )
            )
        except PermissionError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)
        except BackbonePersistenceError as exc:
            logger.warning("Interactive execution blocked for plan %s: %s", plan_id, exc)
            return error_response(FAIL_CLOSED_BACKBONE_MESSAGE, 503)
        except ValueError:
            return error_response("Conflict", 409)

        refreshed_plan = get_plan(plan_id) or plan

        logger.info(
            "Plan %s execution completed: success=%s",
            plan_id,
            outcome.success,
        )

        return json_response(
            {
                "success": True,
                "plan": refreshed_plan.to_dict(),
                "outcome": outcome.to_dict(),
                "run_id": launch.get("run_id"),
                "execution_id": launch.get("execution_id"),
                "correlation_id": launch.get("correlation_id"),
            }
        )


# ---------------------------------------------------------------------------
# Helper: Load a debate result by ID
# ---------------------------------------------------------------------------


async def _load_debate_result(debate_id: str, ctx: dict) -> Any | None:
    """Load a DebateResult by debate ID from available stores.

    Tries multiple sources in order:
    1. Trace files on disk
    2. Storage backend
    3. Decision cache
    """
    import os
    from pathlib import Path

    # Try trace files
    try:
        from aragora.debate.traces import DebateTrace

        nomic_dir = ctx.get("nomic_dir") or os.environ.get("ARAGORA_NOMIC_DIR")
        if nomic_dir:
            trace_path = Path(nomic_dir) / "traces" / f"{debate_id}.json"
            if trace_path.exists():
                trace = DebateTrace.load(trace_path)
                return trace.to_debate_result()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        logger.debug("Failed to load trace for %s: %s", debate_id, e)

    # Try storage backend
    try:
        storage = ctx.get("storage")
        if storage:
            result = await storage.get_result(debate_id)
            if result:
                return result
    except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
        logger.debug("Failed to load from storage for %s: %s", debate_id, e)

    # Try decision cache
    try:
        from aragora.core.decision_cache import get_decision_cache

        cache = get_decision_cache()
        if cache:
            result = cache.get(debate_id)
            if result:
                return result
    except (ImportError, KeyError, ValueError, TypeError, AttributeError) as e:
        logger.debug("Failed to load from cache for %s: %s", debate_id, e)

    return None
