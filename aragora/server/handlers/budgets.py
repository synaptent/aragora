"""
Budget Management API Handler.

Stability: STABLE

All endpoints require authentication. Write operations require 'budget.write' permission.

Endpoints:
- GET  /api/v1/budgets              - List budgets for org
- POST /api/v1/budgets              - Create a budget
- GET  /api/v1/budgets/:id          - Get budget details
- PATCH /api/v1/budgets/:id         - Update a budget
- DELETE /api/v1/budgets/:id        - Delete (close) a budget
- GET  /api/v1/budgets/:id/alerts   - Get alerts for a budget
- POST /api/v1/budgets/:id/alerts/:alert_id/acknowledge - Acknowledge alert
- POST /api/v1/budgets/:id/override - Add override for user
- DELETE /api/v1/budgets/:id/override/:user_id - Remove override
- POST /api/v1/budgets/:id/reset    - Reset budget period
- GET  /api/v1/budgets/:id/transactions - Get transaction history
- GET  /api/v1/budgets/:id/trends   - Get spending trends for budget
- GET  /api/v1/budgets/summary      - Get org budget summary
- GET  /api/v1/budgets/trends       - Get org-wide spending trends
- POST /api/v1/budgets/check        - Pre-flight cost check

Features:
- Circuit breaker pattern for budget manager access resilience
- Rate limiting (60 requests/minute)
- RBAC permission checks (budget.read, budget.write, budget.delete)
- Comprehensive input validation with safe type coercion
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from aragora.rbac.decorators import require_permission

from .base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
)
from .utils.rate_limit import rate_limit
from aragora.observability.metrics import track_handler
from aragora.server.validation.query_params import safe_query_int, safe_query_float

logger = logging.getLogger(__name__)


# =============================================================================
# Circuit Breaker for Budget Manager Access
# =============================================================================

from aragora.resilience.simple_circuit_breaker import SimpleCircuitBreaker as BudgetCircuitBreaker


# Global circuit breaker instance for the budget manager
_circuit_breaker = BudgetCircuitBreaker(name="budget", half_open_max_calls=2)
_circuit_breaker_lock = threading.Lock()


def get_budget_circuit_breaker() -> BudgetCircuitBreaker:
    """Get the global circuit breaker for budget manager."""
    return _circuit_breaker


def reset_budget_circuit_breaker() -> None:
    """Reset the global circuit breaker (for testing)."""
    with _circuit_breaker_lock:
        _circuit_breaker.reset()


# RBAC permission keys
BUDGET_READ_PERMISSION = "budget.read"
BUDGET_WRITE_PERMISSION = "budget.write"
BUDGET_DELETE_PERMISSION = "budget.delete"


class BudgetHandler(BaseHandler):
    """Handler for budget management endpoints.

    Stability: STABLE

    Features:
    - Circuit breaker pattern for budget manager access resilience
    - Rate limiting (60 requests/minute)
    - RBAC permission checks (budget.read, budget.write, budget.delete)
    - Comprehensive input validation with safe type coercion
    """

    # Input validation constants
    MAX_NAME_LENGTH = 200
    MAX_DESCRIPTION_LENGTH = 2000
    MAX_AMOUNT_USD = 1_000_000_000  # 1 billion USD max
    MIN_AMOUNT_USD = 0.01

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}
        self._circuit_breaker = get_budget_circuit_breaker()

    ROUTES = [
        "/api/v1/budgets",
        "/api/v1/budgets/summary",
        "/api/v1/budgets/check",
        "/api/v1/budgets/trends",
        "/api/v1/budgets/*",
        "/api/v1/costs/agents",
        "/api/v1/costs/anomalies",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the given path."""
        if path.startswith("/api/v1/budgets"):
            return True
        if path.startswith("/api/v1/costs/"):
            return True
        return False

    @require_permission("budget:read")
    @track_handler("budgets/main", method="GET")
    @rate_limit(requests_per_minute=60)
    async def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route budget requests to appropriate methods."""
        if isinstance(query_params, str):
            method = query_params
        else:
            method = getattr(handler, "command", "GET") if handler else "GET"
        if not isinstance(method, str):
            method = "GET"
        method = method.upper()
        # Authentication check
        from aragora.billing.jwt_auth import extract_user_from_request

        user_ctx = extract_user_from_request(handler, None)
        if not user_ctx or not user_ctx.is_authenticated:
            return error_response("Authentication required", 401)

        # RBAC permission check based on method
        try:
            from aragora.rbac.checker import get_permission_checker
            from aragora.rbac.models import AuthorizationContext

            auth_ctx = AuthorizationContext(
                user_id=user_ctx.user_id,
                user_email=user_ctx.email,
                org_id=user_ctx.org_id,
                workspace_id=None,
                roles={user_ctx.role} if user_ctx.role else {"member"},
            )

            checker = get_permission_checker()

            # Write operations require budget.write permission
            if method in ("POST", "PATCH", "DELETE"):
                permission = (
                    BUDGET_DELETE_PERMISSION if method == "DELETE" else BUDGET_WRITE_PERMISSION
                )
                decision = checker.check_permission(auth_ctx, permission)
                if not decision.allowed:
                    logger.warning(
                        "User %s denied %s: %s", user_ctx.user_id, permission, decision.reason
                    )
                    return error_response("Permission denied", 403)
            else:
                # Read operations require budget.read
                decision = checker.check_permission(auth_ctx, BUDGET_READ_PERMISSION)
                if not decision.allowed:
                    logger.warning(
                        "User %s denied %s: %s",
                        user_ctx.user_id,
                        BUDGET_READ_PERMISSION,
                        decision.reason,
                    )
                    return error_response("Permission denied", 403)

        except ImportError:
            # RBAC module not available, allow access (backwards compatibility)
            logger.debug("RBAC module not available, skipping permission check")

        # Check circuit breaker before proceeding
        if not self._circuit_breaker.can_proceed():
            logger.warning("Budget circuit breaker is open, rejecting request")
            return error_response("Service temporarily unavailable. Please try again later.", 503)

        # Extract org_id from auth context
        org_id = self._get_org_id(handler)
        user_id = self._get_user_id(handler)

        # Parse path (strip trailing slash for consistent matching)
        path = path.rstrip("/") or path
        parts = path.split("/")
        # /api/v1/budgets -> ["", "api", "v1", "budgets"]
        # /api/v1/budgets/budget-xxx -> ["", "api", "v1", "budgets", "budget-xxx"]

        # GET /api/v1/budgets/summary
        if path == "/api/v1/budgets/summary" and method == "GET":
            return self._get_summary(org_id)

        # GET /api/v1/budgets/trends - org-wide trends
        if path == "/api/v1/budgets/trends" and method == "GET":
            return self._get_org_trends(org_id, handler)

        # POST /api/v1/budgets/check
        if path == "/api/v1/budgets/check" and method == "POST":
            return await self._check_budget(org_id, user_id, handler)

        # GET /api/v1/budgets - List budgets
        if path == "/api/v1/budgets" and method == "GET":
            return self._list_budgets(org_id, handler)

        # POST /api/v1/budgets - Create budget
        if path == "/api/v1/budgets" and method == "POST":
            return await self._create_budget(org_id, user_id, handler)

        # Routes with budget_id
        if len(parts) >= 5 and parts[3] == "budgets":
            budget_id = parts[4]

            # GET /api/v1/budgets/:id
            if len(parts) == 5 and method == "GET":
                return self._get_budget(budget_id, org_id)

            # PATCH /api/v1/budgets/:id
            if len(parts) == 5 and method == "PATCH":
                return await self._update_budget(budget_id, org_id, handler)

            # DELETE /api/v1/budgets/:id
            if len(parts) == 5 and method == "DELETE":
                return self._delete_budget(budget_id, org_id)

            # GET /api/v1/budgets/:id/alerts
            if len(parts) == 6 and parts[5] == "alerts" and method == "GET":
                return self._get_alerts(budget_id, org_id)

            # POST /api/v1/budgets/:id/alerts/:alert_id/acknowledge
            if (
                len(parts) == 8
                and parts[5] == "alerts"
                and parts[7] == "acknowledge"
                and method == "POST"
            ):
                alert_id = parts[6]
                return self._acknowledge_alert(alert_id, user_id)

            # POST /api/v1/budgets/:id/override
            if len(parts) == 6 and parts[5] == "override" and method == "POST":
                return await self._add_override(budget_id, org_id, handler)

            # DELETE /api/v1/budgets/:id/override/:user_id
            if len(parts) == 7 and parts[5] == "override" and method == "DELETE":
                target_user_id = parts[6]
                return self._remove_override(budget_id, org_id, target_user_id)

            # POST /api/v1/budgets/:id/reset
            if len(parts) == 6 and parts[5] == "reset" and method == "POST":
                return self._reset_budget(budget_id, org_id)

            # GET /api/v1/budgets/:id/transactions
            if len(parts) == 6 and parts[5] == "transactions" and method == "GET":
                return self._get_transactions(budget_id, org_id, handler)

            # GET /api/v1/budgets/:id/trends
            if len(parts) == 6 and parts[5] == "trends" and method == "GET":
                return self._get_budget_trends(budget_id, org_id, handler)

        # Cost analytics endpoints
        if path == "/api/v1/costs/agents" and method == "GET":
            return self._get_agent_costs(org_id, handler)

        if path == "/api/v1/costs/anomalies" and method == "GET":
            return self._get_cost_anomalies(org_id, handler)

        return error_response("Not found", 404)

    def _get_org_id(self, handler: Any) -> str:
        """Extract org_id from request context."""
        if handler and hasattr(handler, "org_id"):
            return handler.org_id

        # Try to extract from auth header
        try:
            from aragora.billing.jwt_auth import extract_user_from_request

            user_ctx = extract_user_from_request(handler, None)
            if user_ctx and user_ctx.org_id:
                return user_ctx.org_id
        except (ImportError, AttributeError):
            pass

        return "default"

    def _get_user_id(self, handler: Any) -> str | None:
        """Extract user_id from request context."""
        if handler and hasattr(handler, "user_id"):
            return handler.user_id

        try:
            from aragora.billing.jwt_auth import extract_user_from_request

            user_ctx = extract_user_from_request(handler, None)
            if user_ctx and user_ctx.user_id:
                return user_ctx.user_id
        except (ImportError, AttributeError):
            pass

        return None

    def _get_budget_manager(self):
        """Get budget manager instance with circuit breaker tracking."""
        try:
            from aragora.billing.budget_manager import get_budget_manager

            manager = get_budget_manager()
            self._circuit_breaker.record_success()
            return manager
        except ImportError:
            self._circuit_breaker.record_failure()
            logger.warning("Budget manager module not available")
            raise
        except (ValueError, TypeError, RuntimeError, OSError, AttributeError) as e:
            self._circuit_breaker.record_failure()
            logger.error("Error loading budget manager: %s", e)
            raise

    def get_circuit_breaker_status(self) -> dict[str, Any]:
        """Get the current status of the circuit breaker."""
        return self._circuit_breaker.get_status()

    # =========================================================================
    # Endpoint Implementations
    # =========================================================================

    def _list_budgets(self, org_id: str, handler: Any) -> HandlerResult:
        """List budgets for organization."""
        try:
            manager = self._get_budget_manager()

            # Parse query params
            active_only = True
            if handler:
                query_str = handler.path.split("?", 1)[1] if "?" in handler.path else ""
                from urllib.parse import parse_qs

                params = parse_qs(query_str)
                active_only = params.get("active_only", ["true"])[0].lower() == "true"

            budgets = manager.get_budgets_for_org(org_id, active_only=active_only)

            return json_response(
                {
                    "budgets": [b.to_dict() for b in budgets],
                    "count": len(budgets),
                    "org_id": org_id,
                }
            )

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.error("Failed to list budgets: %s", e)
            return error_response("Failed to list budgets", 500)

    async def _create_budget(self, org_id: str, user_id: str | None, handler: Any) -> HandlerResult:
        """Create a new budget."""
        try:
            from aragora.billing.budget_manager import BudgetPeriod

            body = self.read_json_body(handler)
            if not body:
                return error_response("Invalid request body", 400)

            # Validate name
            name = body.get("name")
            if not name:
                return error_response("Missing required field: name", 400)
            if not isinstance(name, str):
                return error_response("name must be a string", 400)
            name = name.strip()
            if not name:
                return error_response("name cannot be empty", 400)
            if len(name) > self.MAX_NAME_LENGTH:
                return error_response(f"name exceeds maximum length of {self.MAX_NAME_LENGTH}", 400)

            # Validate amount_usd
            amount_usd = body.get("amount_usd")
            if amount_usd is None:
                return error_response("Missing required field: amount_usd", 400)
            try:
                amount_usd_float = float(amount_usd)
            except (ValueError, TypeError):
                return error_response("Invalid amount_usd value: must be a number", 400)
            if amount_usd_float < self.MIN_AMOUNT_USD:
                return error_response(f"amount_usd must be at least {self.MIN_AMOUNT_USD}", 400)
            if amount_usd_float > self.MAX_AMOUNT_USD:
                return error_response(f"amount_usd exceeds maximum of {self.MAX_AMOUNT_USD}", 400)

            # Validate period
            period_str = body.get("period", "monthly")
            if not isinstance(period_str, str):
                return error_response("period must be a string", 400)
            try:
                period = BudgetPeriod(period_str)
            except ValueError:
                return error_response(
                    f"Invalid period: {period_str}. Must be one of: daily, weekly, monthly, quarterly, yearly",
                    400,
                )

            # Validate description (optional)
            description = body.get("description", "")
            if not isinstance(description, str):
                return error_response("description must be a string", 400)
            if len(description) > self.MAX_DESCRIPTION_LENGTH:
                return error_response(
                    f"description exceeds maximum length of {self.MAX_DESCRIPTION_LENGTH}", 400
                )

            # Validate auto_suspend (optional)
            auto_suspend = body.get("auto_suspend", True)
            if not isinstance(auto_suspend, bool):
                return error_response("auto_suspend must be a boolean", 400)

            manager = self._get_budget_manager()
            budget = manager.create_budget(
                org_id=org_id,
                name=name,
                amount_usd=amount_usd_float,
                period=period,
                description=description,
                auto_suspend=auto_suspend,
                created_by=user_id,
            )

            self._circuit_breaker.record_success()
            return json_response(budget.to_dict(), status=201)

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            self._circuit_breaker.record_failure()
            logger.error("Failed to create budget: %s", e)
            return error_response("Budget creation failed", 500)

    def _get_budget(self, budget_id: str, org_id: str) -> HandlerResult:
        """Get budget details."""
        try:
            manager = self._get_budget_manager()
            budget = manager.get_budget(budget_id)

            if not budget:
                return error_response("Budget not found", 404)

            if budget.org_id != org_id:
                return error_response("Access denied", 403)

            return json_response(budget.to_dict())

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.error("Failed to get budget: %s", e)
            return error_response("Failed to retrieve budget", 500)

    async def _update_budget(self, budget_id: str, org_id: str, handler: Any) -> HandlerResult:
        """Update a budget."""
        try:
            from aragora.billing.budget_manager import BudgetStatus

            manager = self._get_budget_manager()
            budget = manager.get_budget(budget_id)

            if not budget:
                return error_response("Budget not found", 404)

            if budget.org_id != org_id:
                return error_response("Access denied", 403)

            body = self.read_json_body(handler)
            if not body:
                return error_response("Invalid request body", 400)

            # Validate name if provided
            name = body.get("name")
            if name is not None:
                if not isinstance(name, str):
                    return error_response("name must be a string", 400)
                name = name.strip()
                if not name:
                    return error_response("name cannot be empty", 400)
                if len(name) > self.MAX_NAME_LENGTH:
                    return error_response(
                        f"name exceeds maximum length of {self.MAX_NAME_LENGTH}", 400
                    )

            # Validate description if provided
            description = body.get("description")
            if description is not None:
                if not isinstance(description, str):
                    return error_response("description must be a string", 400)
                if len(description) > self.MAX_DESCRIPTION_LENGTH:
                    return error_response(
                        f"description exceeds maximum length of {self.MAX_DESCRIPTION_LENGTH}", 400
                    )

            # Validate amount_usd if provided
            amount_usd = body.get("amount_usd")
            amount_usd_float = None
            if amount_usd is not None:
                try:
                    amount_usd_float = float(amount_usd)
                except (ValueError, TypeError):
                    return error_response("Invalid amount_usd value: must be a number", 400)
                if amount_usd_float < self.MIN_AMOUNT_USD:
                    return error_response(f"amount_usd must be at least {self.MIN_AMOUNT_USD}", 400)
                if amount_usd_float > self.MAX_AMOUNT_USD:
                    return error_response(
                        f"amount_usd exceeds maximum of {self.MAX_AMOUNT_USD}", 400
                    )

            # Validate auto_suspend if provided
            auto_suspend = body.get("auto_suspend")
            if auto_suspend is not None and not isinstance(auto_suspend, bool):
                return error_response("auto_suspend must be a boolean", 400)

            # Parse status if provided
            status = None
            if "status" in body:
                status_str = body["status"]
                if not isinstance(status_str, str):
                    return error_response("status must be a string", 400)
                try:
                    status = BudgetStatus(status_str)
                except ValueError:
                    return error_response(
                        f"Invalid status: {status_str}. Must be one of: active, suspended, closed",
                        400,
                    )

            updated = manager.update_budget(
                budget_id=budget_id,
                name=name,
                description=description,
                amount_usd=amount_usd_float,
                auto_suspend=auto_suspend,
                status=status,
            )

            if not updated:
                self._circuit_breaker.record_failure()
                return error_response("Failed to update budget", 500)

            self._circuit_breaker.record_success()
            return json_response(updated.to_dict())

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            self._circuit_breaker.record_failure()
            logger.error("Failed to update budget: %s", e)
            return error_response("Budget update failed", 500)

    @require_permission("budget:delete")
    def _delete_budget(self, budget_id: str, org_id: str) -> HandlerResult:
        """Delete (close) a budget."""
        try:
            manager = self._get_budget_manager()
            budget = manager.get_budget(budget_id)

            if not budget:
                return error_response("Budget not found", 404)

            if budget.org_id != org_id:
                return error_response("Access denied", 403)

            manager.delete_budget(budget_id)

            return json_response({"deleted": True, "budget_id": budget_id})

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.error("Failed to delete budget: %s", e)
            return error_response("Budget deletion failed", 500)

    def _get_summary(self, org_id: str) -> HandlerResult:
        """Get budget summary for organization."""
        try:
            manager = self._get_budget_manager()
            summary = manager.get_summary(org_id)
            return json_response(summary)

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.error("Failed to get summary: %s", e)
            return error_response("Failed to retrieve summary", 500)

    async def _check_budget(self, org_id: str, user_id: str | None, handler: Any) -> HandlerResult:
        """Pre-flight cost check."""
        try:
            body = self.read_json_body(handler)
            if not body:
                return error_response("Invalid request body", 400)

            estimated_cost = body.get("estimated_cost_usd", 0)
            if estimated_cost <= 0:
                return error_response("Invalid estimated_cost_usd: must be positive", 400)

            manager = self._get_budget_manager()
            try:
                estimated_cost_float = float(estimated_cost)
            except (ValueError, TypeError):
                return error_response("Invalid estimated_cost_usd value", 400)
            allowed, reason, action = manager.check_budget(
                org_id=org_id,
                estimated_cost_usd=estimated_cost_float,
                user_id=user_id,
            )

            return json_response(
                {
                    "allowed": allowed,
                    "reason": reason,
                    "action": action.value if action else None,
                    "estimated_cost_usd": estimated_cost,
                }
            )

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.error("Failed to check budget: %s", e)
            return error_response("Budget check failed", 500)

    def _get_alerts(self, budget_id: str, org_id: str) -> HandlerResult:
        """Get alerts for a budget."""
        try:
            manager = self._get_budget_manager()
            budget = manager.get_budget(budget_id)

            if not budget:
                return error_response("Budget not found", 404)

            if budget.org_id != org_id:
                return error_response("Access denied", 403)

            alerts = manager.get_alerts(budget_id=budget_id)

            return json_response(
                {
                    "alerts": [a.to_dict() for a in alerts],
                    "count": len(alerts),
                    "budget_id": budget_id,
                }
            )

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.error("Failed to get alerts: %s", e)
            return error_response("Failed to retrieve alerts", 500)

    def _acknowledge_alert(self, alert_id: str, user_id: str | None) -> HandlerResult:
        """Acknowledge a budget alert."""
        try:
            if not user_id:
                return error_response("User ID required", 400)

            manager = self._get_budget_manager()
            manager.acknowledge_alert(alert_id, user_id)

            return json_response({"acknowledged": True, "alert_id": alert_id})

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.error("Failed to acknowledge alert: %s", e)
            return error_response("Alert acknowledgment failed", 500)

    async def _add_override(self, budget_id: str, org_id: str, handler: Any) -> HandlerResult:
        """Add budget override for a user."""
        try:
            manager = self._get_budget_manager()
            budget = manager.get_budget(budget_id)

            if not budget:
                return error_response("Budget not found", 404)

            if budget.org_id != org_id:
                return error_response("Access denied", 403)

            body = self.read_json_body(handler)
            if not body:
                return error_response("Invalid request body", 400)

            target_user_id = body.get("user_id")
            if not target_user_id:
                return error_response("Missing required field: user_id", 400)

            duration_hours = body.get("duration_hours")

            duration_hours_float = None
            if duration_hours is not None:
                try:
                    duration_hours_float = float(duration_hours)
                except (ValueError, TypeError):
                    return error_response("Invalid duration_hours value", 400)
            manager.add_override(
                budget_id=budget_id,
                user_id=target_user_id,
                duration_hours=duration_hours_float,
            )

            return json_response(
                {
                    "override_added": True,
                    "budget_id": budget_id,
                    "user_id": target_user_id,
                    "duration_hours": duration_hours,
                }
            )

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.error("Failed to add override: %s", e)
            return error_response("Override addition failed", 500)

    def _remove_override(self, budget_id: str, org_id: str, target_user_id: str) -> HandlerResult:
        """Remove budget override for a user."""
        try:
            manager = self._get_budget_manager()
            budget = manager.get_budget(budget_id)

            if not budget:
                return error_response("Budget not found", 404)

            if budget.org_id != org_id:
                return error_response("Access denied", 403)

            manager.remove_override(budget_id, target_user_id)

            return json_response(
                {
                    "override_removed": True,
                    "budget_id": budget_id,
                    "user_id": target_user_id,
                }
            )

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.error("Failed to remove override: %s", e)
            return error_response("Override removal failed", 500)

    def _reset_budget(self, budget_id: str, org_id: str) -> HandlerResult:
        """Reset budget period."""
        try:
            manager = self._get_budget_manager()
            budget = manager.get_budget(budget_id)

            if not budget:
                return error_response("Budget not found", 404)

            if budget.org_id != org_id:
                return error_response("Access denied", 403)

            updated = manager.reset_period(budget_id)

            if not updated:
                return error_response("Failed to reset budget", 500)

            return json_response(updated.to_dict())

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.error("Failed to reset budget: %s", e)
            return error_response("Budget reset failed", 500)

    def _get_transactions(self, budget_id: str, org_id: str, handler: Any) -> HandlerResult:
        """Get transaction history for a budget."""
        try:
            manager = self._get_budget_manager()
            budget = manager.get_budget(budget_id)

            if not budget:
                return error_response("Budget not found", 404)

            if budget.org_id != org_id:
                return error_response("Access denied", 403)

            # Parse query params
            limit = 50
            offset = 0
            date_from = None
            date_to = None
            user_id = None

            if handler:
                query_str = handler.path.split("?", 1)[1] if "?" in handler.path else ""
                from urllib.parse import parse_qs

                params = parse_qs(query_str)
                limit = safe_query_int(params, "limit", default=50, min_val=1, max_val=100)
                offset = safe_query_int(params, "offset", default=0, min_val=0, max_val=10000)
                if "date_from" in params:
                    date_from = safe_query_float(
                        params, "date_from", default=0.0, min_val=0.0, max_val=float("inf")
                    )
                if "date_to" in params:
                    date_to = safe_query_float(
                        params, "date_to", default=0.0, min_val=0.0, max_val=float("inf")
                    )
                user_id = params.get("user_id", [None])[0]

            transactions = manager.get_transactions(
                budget_id=budget_id,
                limit=limit,
                offset=offset,
                date_from=date_from,
                date_to=date_to,
                user_id=user_id,
            )

            total = manager.count_transactions(
                budget_id=budget_id,
                date_from=date_from,
                date_to=date_to,
                user_id=user_id,
            )

            return json_response(
                {
                    "transactions": [t.to_dict() for t in transactions],
                    "count": len(transactions),
                    "total": total,
                    "budget_id": budget_id,
                    "pagination": {
                        "limit": limit,
                        "offset": offset,
                        "has_more": offset + len(transactions) < total,
                    },
                }
            )

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.error("Failed to get transactions: %s", e)
            return error_response("Failed to retrieve transactions", 500)

    def _get_budget_trends(self, budget_id: str, org_id: str, handler: Any) -> HandlerResult:
        """Get spending trends for a budget."""
        try:
            manager = self._get_budget_manager()
            budget = manager.get_budget(budget_id)

            if not budget:
                return error_response("Budget not found", 404)

            if budget.org_id != org_id:
                return error_response("Access denied", 403)

            # Parse query params
            period = "day"
            limit = 30

            if handler:
                query_str = handler.path.split("?", 1)[1] if "?" in handler.path else ""
                from urllib.parse import parse_qs

                params = parse_qs(query_str)
                period = params.get("period", ["day"])[0]
                limit = safe_query_int(params, "limit", default=30, min_val=1, max_val=365)

            if period not in ("hour", "day", "week", "month"):
                return error_response(
                    f"Invalid period: {period}. Must be hour, day, week, or month.",
                    400,
                )

            trends = manager.get_spending_trends(
                budget_id=budget_id,
                period=period,
                limit=limit,
            )

            return json_response(
                {
                    "trends": trends,
                    "budget_id": budget_id,
                    "period": period,
                    "count": len(trends),
                }
            )

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.error("Failed to get trends: %s", e)
            return error_response("Failed to retrieve trends", 500)

    def _get_org_trends(self, org_id: str, handler: Any) -> HandlerResult:
        """Get org-wide spending trends across all budgets."""
        try:
            manager = self._get_budget_manager()

            # Parse query params
            period = "day"
            limit = 30

            if handler:
                query_str = handler.path.split("?", 1)[1] if "?" in handler.path else ""
                from urllib.parse import parse_qs

                params = parse_qs(query_str)
                period = params.get("period", ["day"])[0]
                limit = safe_query_int(params, "limit", default=30, min_val=1, max_val=365)

            if period not in ("hour", "day", "week", "month"):
                return error_response(
                    f"Invalid period: {period}. Must be hour, day, week, or month.",
                    400,
                )

            trends = manager.get_org_spending_trends(
                org_id=org_id,
                period=period,
                limit=limit,
            )

            return json_response(
                {
                    "trends": trends,
                    "org_id": org_id,
                    "period": period,
                    "count": len(trends),
                }
            )

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ImportError,
        ) as e:
            logger.error("Failed to get org trends: %s", e)
            return error_response("Failed to retrieve trends", 500)

    # =========================================================================
    # Cost Analytics Endpoints
    # =========================================================================

    def _get_agent_costs(self, org_id: str, handler: Any) -> HandlerResult:
        """Get per-agent cost breakdown from CostTracker."""
        try:
            from aragora.billing.cost_tracker import get_cost_tracker

            tracker = get_cost_tracker()

            # Use org_id as workspace_id for cost lookup
            workspace_id = org_id
            if handler:
                query_str = handler.path.split("?", 1)[1] if "?" in handler.path else ""
                from urllib.parse import parse_qs

                params = parse_qs(query_str)
                workspace_id = params.get("workspace_id", [org_id])[0]

            stats = tracker.get_workspace_stats(workspace_id)
            agent_costs = stats.get("cost_by_agent", {})

            return json_response(
                {
                    "agents": agent_costs,
                    "workspace_id": workspace_id,
                    "total_cost_usd": stats.get("total_cost_usd", "0"),
                    "count": len(agent_costs),
                }
            )

        except ImportError:
            return error_response("Cost tracking module not available", 503)
        except (KeyError, ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Failed to get agent costs: %s", e)
            return error_response("Failed to retrieve agent costs", 500)

    def _get_cost_anomalies(self, org_id: str, handler: Any) -> HandlerResult:
        """Get recent cost anomalies with advisory."""
        try:
            from aragora.billing.cost_tracker import get_cost_tracker
            from aragora.server.http_utils import run_async

            tracker = get_cost_tracker()

            workspace_id = org_id
            if handler:
                query_str = handler.path.split("?", 1)[1] if "?" in handler.path else ""
                from urllib.parse import parse_qs

                params = parse_qs(query_str)
                workspace_id = params.get("workspace_id", [org_id])[0]

            # detect_and_store_anomalies is async, returns (anomalies, advisory)
            try:
                anomalies, cost_advisory = run_async(
                    tracker.detect_and_store_anomalies(workspace_id)
                )
            except (RuntimeError, OSError):
                anomalies = []
                cost_advisory = None

            return json_response(
                {
                    "anomalies": anomalies,
                    "workspace_id": workspace_id,
                    "count": len(anomalies),
                    "cost_advisory": cost_advisory.to_dict() if cost_advisory else None,
                    "advisory": (
                        "Cost anomalies detected. Review spending patterns."
                        if anomalies
                        else "No anomalies detected."
                    ),
                }
            )

        except ImportError:
            return error_response("Cost tracking module not available", 503)
        except (KeyError, ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Failed to get cost anomalies: %s", e)
            return error_response("Failed to retrieve cost anomalies", 500)


# Handler factory function
def create_budget_handler(server_context: Any) -> BudgetHandler:
    """Factory function for handler registration."""
    return BudgetHandler(server_context)
