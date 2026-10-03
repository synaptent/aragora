"""
Tests for aragora.server.handlers.budgets - Budget Management API handler.

Tests cover:
- List budgets (GET /api/v1/budgets)
- Create budget (POST /api/v1/budgets)
- Get budget (GET /api/v1/budgets/:id)
- Update budget (PATCH /api/v1/budgets/:id)
- Delete budget (DELETE /api/v1/budgets/:id)
- Get alerts (GET /api/v1/budgets/:id/alerts)
- Acknowledge alert (POST /api/v1/budgets/:id/alerts/:alert_id/acknowledge)
- Add override (POST /api/v1/budgets/:id/override)
- Remove override (DELETE /api/v1/budgets/:id/override/:user_id)
- Reset budget (POST /api/v1/budgets/:id/reset)
- Get transactions (GET /api/v1/budgets/:id/transactions)
- Get budget trends (GET /api/v1/budgets/:id/trends)
- Get summary (GET /api/v1/budgets/summary)
- Get org trends (GET /api/v1/budgets/trends)
- Check budget (POST /api/v1/budgets/check)
- Authentication checks
- RBAC permission checks
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.budgets import BudgetHandler


# ===========================================================================
# Mock Classes
# ===========================================================================


class MockBudgetPeriod(Enum):
    """Mock budget period enum."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class MockBudgetStatus(Enum):
    """Mock budget status enum."""

    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class MockBudgetAction(Enum):
    """Mock budget action enum."""

    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class MockBudget:
    """Mock budget for testing."""

    id: str = "budget-123"
    org_id: str = "org-123"
    name: str = "Test Budget"
    amount_usd: float = 1000.0
    spent_usd: float = 250.0
    period: MockBudgetPeriod = MockBudgetPeriod.MONTHLY
    status: MockBudgetStatus = MockBudgetStatus.ACTIVE
    description: str = "Test budget description"
    auto_suspend: bool = True
    created_by: str | None = "user-123"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "org_id": self.org_id,
            "name": self.name,
            "amount_usd": self.amount_usd,
            "spent_usd": self.spent_usd,
            "period": self.period.value,
            "status": self.status.value,
            "description": self.description,
            "auto_suspend": self.auto_suspend,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class MockAlert:
    """Mock budget alert for testing."""

    id: str = "alert-123"
    budget_id: str = "budget-123"
    threshold: float = 80.0
    triggered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "budget_id": self.budget_id,
            "threshold": self.threshold,
            "triggered_at": self.triggered_at.isoformat(),
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": (self.acknowledged_at.isoformat() if self.acknowledged_at else None),
        }


@dataclass
class MockTransaction:
    """Mock budget transaction for testing."""

    id: str = "txn-123"
    budget_id: str = "budget-123"
    amount_usd: float = 5.50
    user_id: str = "user-123"
    description: str = "API call"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "budget_id": self.budget_id,
            "amount_usd": self.amount_usd,
            "user_id": self.user_id,
            "description": self.description,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class MockUserAuthContext:
    """Mock user authentication context."""

    is_authenticated: bool = True
    user_id: str = "user-123"
    email: str = "test@example.com"
    org_id: str = "org-123"
    role: str = "admin"


class MockBudgetManager:
    """Mock budget manager for testing."""

    def __init__(self):
        self.budgets: dict[str, MockBudget] = {}
        self.alerts: dict[str, list[MockAlert]] = {}
        self.transactions: dict[str, list[MockTransaction]] = {}
        self.overrides: dict[str, dict[str, Any]] = {}

    def get_budgets_for_org(self, org_id: str, active_only: bool = True) -> list[MockBudget]:
        budgets = [b for b in self.budgets.values() if b.org_id == org_id]
        if active_only:
            budgets = [b for b in budgets if b.status == MockBudgetStatus.ACTIVE]
        return budgets

    def create_budget(
        self,
        org_id: str,
        name: str,
        amount_usd: float,
        period: MockBudgetPeriod,
        description: str = "",
        auto_suspend: bool = True,
        created_by: str | None = None,
    ) -> MockBudget:
        budget = MockBudget(
            id=f"budget-{len(self.budgets) + 1}",
            org_id=org_id,
            name=name,
            amount_usd=amount_usd,
            period=period,
            description=description,
            auto_suspend=auto_suspend,
            created_by=created_by,
        )
        self.budgets[budget.id] = budget
        return budget

    def get_budget(self, budget_id: str) -> MockBudget | None:
        return self.budgets.get(budget_id)

    def update_budget(
        self,
        budget_id: str,
        name: str | None = None,
        description: str | None = None,
        amount_usd: float | None = None,
        auto_suspend: bool | None = None,
        status: MockBudgetStatus | None = None,
    ) -> MockBudget | None:
        budget = self.budgets.get(budget_id)
        if not budget:
            return None
        if name is not None:
            budget.name = name
        if description is not None:
            budget.description = description
        if amount_usd is not None:
            budget.amount_usd = amount_usd
        if auto_suspend is not None:
            budget.auto_suspend = auto_suspend
        if status is not None:
            budget.status = status
        return budget

    def delete_budget(self, budget_id: str) -> bool:
        if budget_id in self.budgets:
            del self.budgets[budget_id]
            return True
        return False

    def get_summary(self, org_id: str) -> dict[str, Any]:
        budgets = self.get_budgets_for_org(org_id, active_only=False)
        total_allocated = sum(b.amount_usd for b in budgets)
        total_spent = sum(b.spent_usd for b in budgets)
        return {
            "org_id": org_id,
            "total_budgets": len(budgets),
            "active_budgets": len([b for b in budgets if b.status == MockBudgetStatus.ACTIVE]),
            "total_allocated_usd": total_allocated,
            "total_spent_usd": total_spent,
            "utilization_percent": (
                (total_spent / total_allocated * 100) if total_allocated else 0
            ),
        }

    def check_budget(
        self, org_id: str, estimated_cost_usd: float, user_id: str | None = None
    ) -> tuple[bool, str, MockBudgetAction | None]:
        budgets = self.get_budgets_for_org(org_id)
        if not budgets:
            return True, "No active budgets", None

        for budget in budgets:
            remaining = budget.amount_usd - budget.spent_usd
            if estimated_cost_usd > remaining:
                if budget.auto_suspend:
                    return (
                        False,
                        f"Would exceed budget {budget.name}",
                        MockBudgetAction.BLOCK,
                    )
                return (
                    True,
                    f"Would exceed budget {budget.name} (warning)",
                    MockBudgetAction.WARN,
                )

        return True, "Within budget", MockBudgetAction.ALLOW

    def get_alerts(self, budget_id: str) -> list[MockAlert]:
        return self.alerts.get(budget_id, [])

    def acknowledge_alert(self, alert_id: str, user_id: str) -> bool:
        for alerts in self.alerts.values():
            for alert in alerts:
                if alert.id == alert_id:
                    alert.acknowledged_by = user_id
                    alert.acknowledged_at = datetime.now(timezone.utc)
                    return True
        return False

    def add_override(
        self,
        budget_id: str,
        user_id: str,
        duration_hours: float | None = None,
    ) -> bool:
        if budget_id not in self.overrides:
            self.overrides[budget_id] = {}
        self.overrides[budget_id][user_id] = {
            "duration_hours": duration_hours,
            "created_at": datetime.now(timezone.utc),
        }
        return True

    def remove_override(self, budget_id: str, user_id: str) -> bool:
        if budget_id in self.overrides and user_id in self.overrides[budget_id]:
            del self.overrides[budget_id][user_id]
            return True
        return False

    def reset_period(self, budget_id: str) -> MockBudget | None:
        budget = self.budgets.get(budget_id)
        if budget:
            budget.spent_usd = 0.0
            return budget
        return None

    def get_transactions(
        self,
        budget_id: str,
        limit: int = 50,
        offset: int = 0,
        date_from: float | None = None,
        date_to: float | None = None,
        user_id: str | None = None,
    ) -> list[MockTransaction]:
        txns = self.transactions.get(budget_id, [])
        if user_id:
            txns = [t for t in txns if t.user_id == user_id]
        return txns[offset : offset + limit]

    def count_transactions(
        self,
        budget_id: str,
        date_from: float | None = None,
        date_to: float | None = None,
        user_id: str | None = None,
    ) -> int:
        txns = self.transactions.get(budget_id, [])
        if user_id:
            txns = [t for t in txns if t.user_id == user_id]
        return len(txns)

    def get_spending_trends(
        self, budget_id: str, period: str = "day", limit: int = 30
    ) -> list[dict[str, Any]]:
        return [
            {"period": "2024-01-01", "amount_usd": 100.0},
            {"period": "2024-01-02", "amount_usd": 150.0},
        ]

    def get_org_spending_trends(
        self, org_id: str, period: str = "day", limit: int = 30
    ) -> list[dict[str, Any]]:
        return [
            {"period": "2024-01-01", "amount_usd": 500.0, "budget_count": 3},
            {"period": "2024-01-02", "amount_usd": 600.0, "budget_count": 3},
        ]


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def enable_real_auth_for_auth_tests(request):
    """Enable real auth checks for tests marked with no_auto_auth."""
    if "no_auto_auth" in [m.name for m in request.node.iter_markers()]:
        os.environ["ARAGORA_TEST_REAL_AUTH"] = "1"
        yield
        del os.environ["ARAGORA_TEST_REAL_AUTH"]
    else:
        yield


@pytest.fixture
def mock_budget_manager():
    """Create a mock budget manager with test data."""
    manager = MockBudgetManager()

    # Add test budgets
    manager.budgets["budget-123"] = MockBudget(
        id="budget-123",
        org_id="org-123",
        name="Development Budget",
        amount_usd=1000.0,
        spent_usd=250.0,
    )
    manager.budgets["budget-456"] = MockBudget(
        id="budget-456",
        org_id="org-123",
        name="Production Budget",
        amount_usd=5000.0,
        spent_usd=1200.0,
    )
    manager.budgets["budget-other"] = MockBudget(
        id="budget-other",
        org_id="org-other",
        name="Other Org Budget",
        amount_usd=2000.0,
    )

    # Add test alerts
    manager.alerts["budget-123"] = [
        MockAlert(id="alert-1", budget_id="budget-123", threshold=50.0),
        MockAlert(id="alert-2", budget_id="budget-123", threshold=80.0),
    ]

    # Add test transactions
    manager.transactions["budget-123"] = [
        MockTransaction(id="txn-1", budget_id="budget-123", amount_usd=5.50),
        MockTransaction(id="txn-2", budget_id="budget-123", amount_usd=10.25),
        MockTransaction(id="txn-3", budget_id="budget-123", amount_usd=3.75),
    ]

    return manager


@pytest.fixture
def mock_user_context():
    """Create a mock authenticated user context."""
    return MockUserAuthContext()


@pytest.fixture
def mock_handler():
    """Create a mock HTTP handler object."""
    handler = MagicMock()
    handler.path = "/api/v1/budgets"
    handler.org_id = "org-123"
    handler.user_id = "user-123"
    return handler


@pytest.fixture
def budget_handler():
    """Create a BudgetHandler instance."""
    return BudgetHandler(MagicMock())


# ===========================================================================
# Helper Functions
# ===========================================================================


def parse_response(result) -> tuple[dict[str, Any], int]:
    """Parse HandlerResult into (body_dict, status_code)."""
    body = json.loads(result.body) if result.body else {}
    return body, result.status_code


def create_json_handler(body: dict[str, Any], path: str = "/api/v1/budgets") -> MagicMock:
    """Create a mock handler with JSON body."""
    handler = MagicMock()
    handler.path = path
    handler.org_id = "org-123"
    handler.user_id = "user-123"
    handler._body = body
    return handler


# ===========================================================================
# Test: can_handle
# ===========================================================================


class TestCanHandle:
    """Tests for the can_handle method."""

    def test_handles_budgets_root(self, budget_handler):
        """Should handle /api/v1/budgets."""
        assert budget_handler.can_handle("/api/v1/budgets") is True

    def test_handles_budget_id(self, budget_handler):
        """Should handle /api/v1/budgets/:id."""
        assert budget_handler.can_handle("/api/v1/budgets/budget-123") is True

    def test_handles_budget_summary(self, budget_handler):
        """Should handle /api/v1/budgets/summary."""
        assert budget_handler.can_handle("/api/v1/budgets/summary") is True

    def test_handles_budget_alerts(self, budget_handler):
        """Should handle /api/v1/budgets/:id/alerts."""
        assert budget_handler.can_handle("/api/v1/budgets/budget-123/alerts") is True

    def test_does_not_handle_other_paths(self, budget_handler):
        """Should not handle unrelated paths."""
        assert budget_handler.can_handle("/api/v1/users") is False
        assert budget_handler.can_handle("/api/v1/billing") is False


# ===========================================================================
# Test: Authentication
# ===========================================================================


class TestAuthentication:
    """Tests for authentication checks."""

    @pytest.mark.asyncio
    async def test_unauthenticated_request_returns_401(self, budget_handler, mock_handler):
        """Should return 401 for unauthenticated requests."""
        with patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract:
            mock_extract.return_value = None

            result = await budget_handler.handle("/api/v1/budgets", "GET", mock_handler)
            body, status = parse_response(result)

            assert status == 401
            assert "Authentication required" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_authenticated_request_proceeds(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should proceed for authenticated requests."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle("/api/v1/budgets", "GET", mock_handler)
            body, status = parse_response(result)

            assert status == 200
            assert "budgets" in body


# ===========================================================================
# Test: List Budgets
# ===========================================================================


class TestListBudgets:
    """Tests for GET /api/v1/budgets."""

    @pytest.mark.asyncio
    async def test_list_budgets_returns_org_budgets(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should return budgets for the organization."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle("/api/v1/budgets", "GET", mock_handler)
            body, status = parse_response(result)

            assert status == 200
            assert "budgets" in body
            assert body["count"] == 2
            assert body["org_id"] == "org-123"


# ===========================================================================
# Test: Create Budget
# ===========================================================================


class TestCreateBudget:
    """Tests for POST /api/v1/budgets."""

    @pytest.mark.asyncio
    async def test_create_budget_success(
        self, budget_handler, mock_budget_manager, mock_user_context
    ):
        """Should create a new budget."""
        handler = create_json_handler(
            {"name": "New Budget", "amount_usd": 500.0, "period": "monthly"}
        )

        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch.object(budget_handler, "read_json_body") as mock_read_body,
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
            patch("aragora.billing.budget_manager.BudgetPeriod", MockBudgetPeriod),
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)
            mock_read_body.return_value = {
                "name": "New Budget",
                "amount_usd": 500.0,
                "period": "monthly",
            }

            result = await budget_handler.handle("/api/v1/budgets", "POST", handler)
            body, status = parse_response(result)

            assert status == 201
            assert body["name"] == "New Budget"
            assert body["amount_usd"] == 500.0

    @pytest.mark.asyncio
    async def test_create_budget_missing_name_returns_400(
        self, budget_handler, mock_budget_manager, mock_user_context
    ):
        """Should return 400 when name is missing."""
        handler = create_json_handler({"amount_usd": 500.0})

        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch.object(budget_handler, "read_json_body") as mock_read_body,
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)
            mock_read_body.return_value = {"amount_usd": 500.0}

            result = await budget_handler.handle("/api/v1/budgets", "POST", handler)
            body, status = parse_response(result)

            assert status == 400
            assert "name" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_create_budget_invalid_amount_returns_400(
        self, budget_handler, mock_budget_manager, mock_user_context
    ):
        """Should return 400 when amount is invalid."""
        handler = create_json_handler({"name": "Test", "amount_usd": -100})

        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch.object(budget_handler, "read_json_body") as mock_read_body,
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)
            mock_read_body.return_value = {"name": "Test", "amount_usd": -100}

            result = await budget_handler.handle("/api/v1/budgets", "POST", handler)
            body, status = parse_response(result)

            assert status == 400
            assert "amount_usd" in body.get("error", "").lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("huge_amount", [10**400, -(10**400)])
    async def test_create_budget_huge_integer_amount_returns_400(
        self, budget_handler, mock_budget_manager, mock_user_context, huge_amount
    ):
        """Arbitrary-precision JSON ints must yield 400, not an OverflowError 500."""
        handler = create_json_handler({"name": "Test", "amount_usd": huge_amount})

        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch.object(budget_handler, "read_json_body") as mock_read_body,
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)
            mock_read_body.return_value = {"name": "Test", "amount_usd": huge_amount}

            result = await budget_handler.handle("/api/v1/budgets", "POST", handler)
            body, status = parse_response(result)

            assert status == 400
            assert "amount_usd" in body.get("error", "").lower()


# ===========================================================================
# Test: Get Budget
# ===========================================================================


class TestGetBudget:
    """Tests for GET /api/v1/budgets/:id."""

    @pytest.mark.asyncio
    async def test_get_budget_success(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should return budget details."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle("/api/v1/budgets/budget-123", "GET", mock_handler)
            body, status = parse_response(result)

            assert status == 200
            assert body["id"] == "budget-123"
            assert body["name"] == "Development Budget"

    @pytest.mark.asyncio
    async def test_get_budget_not_found(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should return 404 for non-existent budget."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle("/api/v1/budgets/nonexistent", "GET", mock_handler)
            body, status = parse_response(result)

            assert status == 404

    @pytest.mark.asyncio
    async def test_get_budget_wrong_org_returns_403(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should return 403 when budget belongs to different org."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle(
                "/api/v1/budgets/budget-other", "GET", mock_handler
            )
            body, status = parse_response(result)

            assert status == 403


# ===========================================================================
# Test: Update Budget
# ===========================================================================


class TestUpdateBudget:
    """Tests for PATCH /api/v1/budgets/:id."""

    @pytest.mark.asyncio
    async def test_update_budget_success(
        self, budget_handler, mock_budget_manager, mock_user_context
    ):
        """Should update budget."""
        handler = create_json_handler(
            {"name": "Updated Budget", "amount_usd": 2000.0},
            path="/api/v1/budgets/budget-123",
        )

        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch.object(budget_handler, "read_json_body") as mock_read_body,
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)
            mock_read_body.return_value = {"name": "Updated Budget", "amount_usd": 2000.0}

            result = await budget_handler.handle("/api/v1/budgets/budget-123", "PATCH", handler)
            body, status = parse_response(result)

            assert status == 200
            assert body["name"] == "Updated Budget"
            assert body["amount_usd"] == 2000.0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("huge_amount", [10**400, -(10**400)])
    async def test_update_budget_huge_integer_amount_returns_400(
        self, budget_handler, mock_budget_manager, mock_user_context, huge_amount
    ):
        """Arbitrary-precision JSON ints must yield 400, not an OverflowError 500."""
        handler = create_json_handler(
            {"amount_usd": huge_amount},
            path="/api/v1/budgets/budget-123",
        )

        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch.object(budget_handler, "read_json_body") as mock_read_body,
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)
            mock_read_body.return_value = {"amount_usd": huge_amount}

            result = await budget_handler.handle("/api/v1/budgets/budget-123", "PATCH", handler)
            body, status = parse_response(result)

            assert status == 400
            assert "amount_usd" in body.get("error", "").lower()


# ===========================================================================
# Test: Delete Budget
# ===========================================================================


class TestDeleteBudget:
    """Tests for DELETE /api/v1/budgets/:id."""

    @pytest.mark.asyncio
    async def test_delete_budget_success(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should delete budget."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle(
                "/api/v1/budgets/budget-123", "DELETE", mock_handler
            )
            body, status = parse_response(result)

            assert status == 200
            assert body["deleted"] is True
            assert body["budget_id"] == "budget-123"


# ===========================================================================
# Test: Get Summary
# ===========================================================================


class TestGetSummary:
    """Tests for GET /api/v1/budgets/summary."""

    @pytest.mark.asyncio
    async def test_get_summary_success(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should return budget summary."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle("/api/v1/budgets/summary", "GET", mock_handler)
            body, status = parse_response(result)

            assert status == 200
            assert "total_budgets" in body
            assert "total_allocated_usd" in body
            assert "total_spent_usd" in body


# ===========================================================================
# Test: Check Budget
# ===========================================================================


class TestCheckBudget:
    """Tests for POST /api/v1/budgets/check."""

    @pytest.mark.asyncio
    async def test_check_budget_allowed(
        self, budget_handler, mock_budget_manager, mock_user_context
    ):
        """Should return allowed for within-budget cost."""
        handler = create_json_handler({"estimated_cost_usd": 10.0}, path="/api/v1/budgets/check")

        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch.object(budget_handler, "read_json_body") as mock_read_body,
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)
            mock_read_body.return_value = {"estimated_cost_usd": 10.0}

            result = await budget_handler.handle("/api/v1/budgets/check", "POST", handler)
            body, status = parse_response(result)

            assert status == 200
            assert body["allowed"] is True


# ===========================================================================
# Test: Get Alerts
# ===========================================================================


class TestGetAlerts:
    """Tests for GET /api/v1/budgets/:id/alerts."""

    @pytest.mark.asyncio
    async def test_get_alerts_success(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should return alerts for budget."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle(
                "/api/v1/budgets/budget-123/alerts", "GET", mock_handler
            )
            body, status = parse_response(result)

            assert status == 200
            assert "alerts" in body
            assert body["count"] == 2


# ===========================================================================
# Test: Acknowledge Alert
# ===========================================================================


class TestAcknowledgeAlert:
    """Tests for POST /api/v1/budgets/:id/alerts/:alert_id/acknowledge."""

    @pytest.mark.asyncio
    async def test_acknowledge_alert_success(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should acknowledge alert."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle(
                "/api/v1/budgets/budget-123/alerts/alert-1/acknowledge",
                "POST",
                mock_handler,
            )
            body, status = parse_response(result)

            assert status == 200
            assert body["acknowledged"] is True


# ===========================================================================
# Test: Get Transactions
# ===========================================================================


class TestGetTransactions:
    """Tests for GET /api/v1/budgets/:id/transactions."""

    @pytest.mark.asyncio
    async def test_get_transactions_success(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should return transactions for budget."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle(
                "/api/v1/budgets/budget-123/transactions", "GET", mock_handler
            )
            body, status = parse_response(result)

            assert status == 200
            assert "transactions" in body
            assert "pagination" in body


# ===========================================================================
# Test: Get Trends
# ===========================================================================


class TestGetTrends:
    """Tests for GET /api/v1/budgets/:id/trends."""

    @pytest.mark.asyncio
    async def test_get_budget_trends_success(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should return trends for budget."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle(
                "/api/v1/budgets/budget-123/trends", "GET", mock_handler
            )
            body, status = parse_response(result)

            assert status == 200
            assert "trends" in body
            assert body["budget_id"] == "budget-123"

    @pytest.mark.asyncio
    async def test_get_org_trends_success(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should return org-wide trends."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle("/api/v1/budgets/trends", "GET", mock_handler)
            body, status = parse_response(result)

            assert status == 200
            assert "trends" in body
            assert body["org_id"] == "org-123"


# ===========================================================================
# Test: Override Management
# ===========================================================================


class TestOverrideManagement:
    """Tests for override endpoints."""

    @pytest.mark.asyncio
    async def test_add_override_success(
        self, budget_handler, mock_budget_manager, mock_user_context
    ):
        """Should add override for user."""
        handler = create_json_handler(
            {"user_id": "user-456", "duration_hours": 24},
            path="/api/v1/budgets/budget-123/override",
        )

        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch.object(budget_handler, "read_json_body") as mock_read_body,
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)
            mock_read_body.return_value = {"user_id": "user-456", "duration_hours": 24}

            result = await budget_handler.handle(
                "/api/v1/budgets/budget-123/override", "POST", handler
            )
            body, status = parse_response(result)

            assert status == 200
            assert body["override_added"] is True

    @pytest.mark.asyncio
    async def test_remove_override_success(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should remove override for user."""
        # First add an override
        mock_budget_manager.add_override("budget-123", "user-456")

        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle(
                "/api/v1/budgets/budget-123/override/user-456", "DELETE", mock_handler
            )
            body, status = parse_response(result)

            assert status == 200
            assert body["override_removed"] is True


# ===========================================================================
# Test: Reset Budget
# ===========================================================================


class TestResetBudget:
    """Tests for POST /api/v1/budgets/:id/reset."""

    @pytest.mark.asyncio
    async def test_reset_budget_success(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should reset budget period."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle(
                "/api/v1/budgets/budget-123/reset", "POST", mock_handler
            )
            body, status = parse_response(result)

            assert status == 200
            assert body["spent_usd"] == 0.0


# ===========================================================================
# Test: RBAC Permission Checks
# ===========================================================================


class TestRBACPermissions:
    """Tests for RBAC permission enforcement."""

    @pytest.mark.asyncio
    async def test_read_requires_budget_read_permission(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should require budget.read permission for GET requests."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_decision = MagicMock(allowed=False, reason="Missing budget.read")
            mock_checker.return_value.check_permission.return_value = mock_decision

            result = await budget_handler.handle("/api/v1/budgets", "GET", mock_handler)
            body, status = parse_response(result)

            assert status == 403
            assert "Permission denied" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_write_requires_budget_write_permission(
        self, budget_handler, mock_budget_manager, mock_user_context
    ):
        """Should require budget.write permission for POST/PATCH requests."""
        handler = create_json_handler({"name": "Test Budget", "amount_usd": 100.0})

        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_decision = MagicMock(allowed=False, reason="Missing budget.write")
            mock_checker.return_value.check_permission.return_value = mock_decision

            result = await budget_handler.handle("/api/v1/budgets", "POST", handler)
            body, status = parse_response(result)

            assert status == 403
            assert "Permission denied" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_delete_requires_budget_delete_permission(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should require budget.delete permission for DELETE requests."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_decision = MagicMock(allowed=False, reason="Missing budget.delete")
            mock_checker.return_value.check_permission.return_value = mock_decision

            result = await budget_handler.handle(
                "/api/v1/budgets/budget-123", "DELETE", mock_handler
            )
            body, status = parse_response(result)

            assert status == 403
            assert "Permission denied" in body.get("error", "")


# ===========================================================================
# Test: Not Found
# ===========================================================================


class TestNotFound:
    """Tests for 404 responses."""

    @pytest.mark.asyncio
    async def test_invalid_path_returns_404(
        self, budget_handler, mock_handler, mock_budget_manager, mock_user_context
    ):
        """Should return 404 for invalid paths."""
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request") as mock_extract,
            patch.object(budget_handler, "_get_budget_manager", return_value=mock_budget_manager),
            patch("aragora.rbac.checker.get_permission_checker") as mock_checker,
        ):
            mock_extract.return_value = mock_user_context
            mock_checker.return_value.check_permission.return_value = MagicMock(allowed=True)

            result = await budget_handler.handle(
                "/api/v1/budgets/budget-123/invalid-endpoint", "GET", mock_handler
            )
            body, status = parse_response(result)

            assert status == 404
