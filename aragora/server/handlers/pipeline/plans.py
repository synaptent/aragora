"""
Decision Pipeline Plan Management API.

Provides:
- GET /api/v1/plans (list plans)
- GET /api/v1/plans/:id (plan detail)
- PUT /api/v1/plans/:id/approve (approval checkpoint)
- GET /api/v1/plans/:id/memo (DecisionMemo markdown)
"""

from __future__ import annotations

import logging
from typing import Any, cast

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    SAFE_ID_PATTERN,
    BaseHandler,
    HandlerResult,
    error_response,
    get_int_param,
    get_string_param,
    json_response,
    validate_path_segment,
    handle_errors,
)
from ..utils.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

_plan_limiter = RateLimiter(requests_per_minute=30)

# In-memory plan store (production would use database)
_plan_store: dict[str, Any] = {}


def get_plan_store() -> dict[str, Any]:
    """Get the plan store (allows test injection)."""
    return _plan_store


class PlanManagementHandler(BaseHandler):
    """Handler for decision plan management endpoints."""

    ROUTES = ["/api/v1/plans"]

    def __init__(self, ctx: dict[str, Any] | None = None):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        cleaned = strip_version_prefix(path)
        return cleaned.startswith("/api/plans")

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests."""
        cleaned = strip_version_prefix(path)

        client_ip = get_client_ip(handler)
        if not _plan_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if cleaned == "/api/plans":
            return self._list_plans(query_params)

        # /api/plans/:id
        parts = cleaned.split("/")
        if len(parts) >= 4 and parts[1] == "api" and parts[2] == "plans":
            plan_id = parts[3]
            is_valid, err = validate_path_segment(plan_id, "plan_id", SAFE_ID_PATTERN)
            if not is_valid:
                return error_response(cast(str, err), 400)

            if len(parts) == 4:
                return self._get_plan(plan_id)
            elif len(parts) == 5 and parts[4] == "memo":
                return self._get_plan_memo(plan_id)

        return None

    @handle_errors("plan management update")
    @require_permission("plans:approve")
    def handle_put(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route PUT requests."""
        cleaned = strip_version_prefix(path)

        client_ip = get_client_ip(handler)
        if not _plan_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # /api/plans/:id/approve
        parts = cleaned.split("/")
        if len(parts) == 5 and parts[1] == "api" and parts[2] == "plans" and parts[4] == "approve":
            plan_id = parts[3]
            is_valid, err = validate_path_segment(plan_id, "plan_id", SAFE_ID_PATTERN)
            if not is_valid:
                return error_response(cast(str, err), 400)
            return self._approve_plan(plan_id, handler)

        return None

    def _get_plans_from_store(self) -> dict[str, Any]:
        """Get plans from context or in-memory store."""
        store = self.ctx.get("plan_store")
        if store is not None:
            return store
        return get_plan_store()

    def _list_plans(self, query_params: dict[str, Any]) -> HandlerResult:
        """List all decision plans."""
        limit = get_int_param(query_params, "limit", 20)
        limit = max(1, min(limit, 100))
        offset = get_int_param(query_params, "offset", 0)
        offset = max(0, offset)
        status_filter = get_string_param(query_params, "status")

        try:
            store = self._get_plans_from_store()
            plans = list(store.values())

            # Filter by status if provided
            if status_filter:
                plans = [p for p in plans if self._get_plan_status(p) == status_filter]

            # Sort by created_at descending
            plans.sort(
                key=lambda p: self._get_plan_created_at(p),
                reverse=True,
            )

            total = len(plans)
            paginated = plans[offset : offset + limit]

            # Summarize each plan for list view
            summaries = []
            for plan in paginated:
                summaries.append(self._plan_summary(plan))

            return json_response(
                {
                    "plans": summaries,
                    "count": len(summaries),
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            )
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            logger.error("List plans failed: %s: %s", type(e).__name__, e)
            return error_response("Failed to list plans", 500)

    def _get_plan(self, plan_id: str) -> HandlerResult:
        """Get plan detail."""
        store = self._get_plans_from_store()
        plan = store.get(plan_id)
        if plan is None:
            return error_response(f"Plan not found: {plan_id}", 404)

        try:
            if hasattr(plan, "to_dict"):
                return json_response(plan.to_dict())
            elif isinstance(plan, dict):
                return json_response(plan)
            else:
                return json_response({"id": plan_id, "plan": str(plan)})
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            logger.error("Get plan failed: %s: %s", type(e).__name__, e)
            return error_response("Failed to get plan", 500)

    def _approve_plan(self, plan_id: str, handler: Any) -> HandlerResult:
        """Approve a plan at checkpoint."""
        store = self._get_plans_from_store()
        plan = store.get(plan_id)
        if plan is None:
            return error_response(f"Plan not found: {plan_id}", 404)

        body = self.read_json_body(handler)
        reason = ""
        conditions: list[str] = []
        if body:
            reason = body.get("reason", "")
            conditions = body.get("conditions", [])

        user = self.get_current_user(handler)
        approver_id = user.user_id if user and hasattr(user, "user_id") else "anonymous"

        try:
            if hasattr(plan, "approve"):
                plan.approve(
                    approver_id=approver_id,
                    reason=reason,
                    conditions=conditions,
                )
                result_dict = plan.to_dict() if hasattr(plan, "to_dict") else {"id": plan_id}
            elif isinstance(plan, dict):
                plan["status"] = "approved"
                plan["approval_record"] = {
                    "approved": True,
                    "approver_id": approver_id,
                    "reason": reason,
                    "conditions": conditions,
                }
                result_dict = plan
            else:
                return error_response("Plan does not support approval", 400)

            return json_response(
                {
                    "approved": True,
                    "plan_id": plan_id,
                    "approver_id": approver_id,
                    "plan": result_dict,
                }
            )
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            logger.error("Approve plan failed: %s: %s", type(e).__name__, e)
            return error_response("Failed to approve plan", 500)

    def _get_plan_memo(self, plan_id: str) -> HandlerResult:
        """Get DecisionMemo markdown for a plan."""
        store = self._get_plans_from_store()
        plan = store.get(plan_id)
        if plan is None:
            return error_response(f"Plan not found: {plan_id}", 404)

        try:
            # Try to generate DecisionMemo from plan
            memo_md = None

            if hasattr(plan, "debate_result") and plan.debate_result:
                try:
                    from aragora.pipeline.pr_generator import PRGenerator
                    from aragora.export.artifact import create_artifact_from_debate

                    artifact = create_artifact_from_debate(plan.debate_result)
                    generator = PRGenerator(artifact)
                    memo = generator.generate_decision_memo()
                    memo_md = memo.to_markdown()
                except (ImportError, ValueError, TypeError, AttributeError) as e:
                    logger.debug("PRGenerator unavailable: %s", e)

            # Fallback: build simple memo from plan data
            if memo_md is None:
                memo_md = self._build_simple_memo(plan, plan_id)

            return json_response(
                {
                    "plan_id": plan_id,
                    "memo": memo_md,
                    "format": "markdown",
                }
            )
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            logger.error("Get memo failed: %s: %s", type(e).__name__, e)
            return error_response("Failed to generate memo", 500)

    def _build_simple_memo(self, plan: Any, plan_id: str) -> str:
        """Build a simple markdown memo from plan data."""
        task = ""
        status = ""
        debate_id = ""

        if hasattr(plan, "task"):
            task = plan.task
        elif isinstance(plan, dict):
            task = plan.get("task", "")

        if hasattr(plan, "status"):
            status = plan.status.value if hasattr(plan.status, "value") else str(plan.status)
        elif isinstance(plan, dict):
            status = plan.get("status", "")

        if hasattr(plan, "debate_id"):
            debate_id = plan.debate_id
        elif isinstance(plan, dict):
            debate_id = plan.get("debate_id", "")

        return f"""# Decision Memo: {plan_id}

**Status:** {status}
**Debate ID:** {debate_id}

## Task

{task}

---

*Generated from plan data.*
"""

    def _plan_summary(self, plan: Any) -> dict[str, Any]:
        """Extract summary fields from a plan for list view."""
        if isinstance(plan, dict):
            return {
                "id": plan.get("id", ""),
                "task": plan.get("task", ""),
                "status": plan.get("status", ""),
                "debate_id": plan.get("debate_id", ""),
                "created_at": plan.get("created_at", ""),
                "requires_approval": plan.get("requires_human_approval", False),
            }
        status_obj = getattr(plan, "status", "")
        status_value = getattr(status_obj, "value", status_obj)
        return {
            "id": getattr(plan, "id", ""),
            "task": getattr(plan, "task", ""),
            "status": str(status_value),
            "debate_id": getattr(plan, "debate_id", ""),
            "created_at": getattr(plan, "created_at", ""),
            "requires_approval": getattr(plan, "requires_human_approval", False),
        }

    def _get_plan_status(self, plan: Any) -> str:
        """Extract status string from plan."""
        if isinstance(plan, dict):
            return plan.get("status", "")
        status = getattr(plan, "status", "")
        return status.value if hasattr(status, "value") else str(status)

    def _get_plan_created_at(self, plan: Any) -> str:
        """Extract created_at string for sorting."""
        if isinstance(plan, dict):
            return plan.get("created_at", "")
        ca = getattr(plan, "created_at", "")
        return ca.isoformat() if hasattr(ca, "isoformat") else str(ca)
