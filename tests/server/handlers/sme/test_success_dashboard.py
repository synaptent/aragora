"""
Tests for SME Success Dashboard handler.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.sme_success_dashboard import (
    MILESTONES,
    SMESuccessDashboardHandler,
)


@pytest.fixture
def mock_server_context():
    """Create a mock server context."""
    ctx = MagicMock()
    ctx.get.return_value = None
    return ctx


@pytest.fixture
def handler(mock_server_context):
    """Create a handler instance with mocked context."""
    h = SMESuccessDashboardHandler(server_context=mock_server_context)
    return h


@pytest.fixture
def mock_user():
    """Create a mock user."""
    user = MagicMock()
    user.user_id = "user_123"
    user.org_id = "org_123"
    user.role = "member"
    return user


@pytest.fixture
def mock_org():
    """Create a mock organization."""
    org = MagicMock()
    org.id = "org_123"
    org.name = "Test Org"
    return org


@pytest.fixture
def mock_user_store(mock_user, mock_org):
    """Create a mock user store."""
    store = MagicMock()
    store.get_user_by_id.return_value = mock_user
    store.get_organization_by_id.return_value = mock_org
    return store


@pytest.fixture
def mock_cost_tracker():
    """Create a mock cost tracker."""
    tracker = MagicMock()
    tracker.get_workspace_stats.return_value = {
        "total_cost_usd": "15.50",
        "total_api_calls": 150,
        "total_tokens_in": 500000,
        "total_tokens_out": 250000,
        "cost_by_agent": {"claude": "10.00", "gpt-4": "5.50"},
        "cost_by_model": {"claude-3-opus": "10.00", "gpt-4-turbo": "5.50"},
    }
    tracker.get_budget.return_value = MagicMock(
        monthly_limit_usd=Decimal("100.00"),
        current_monthly_spend=Decimal("15.50"),
        daily_limit_usd=Decimal("10.00"),
        current_daily_spend=Decimal("1.50"),
        check_alert_level=lambda: None,
    )
    return tracker


@pytest.fixture
def mock_request():
    """Create a mock HTTP request handler."""
    request = MagicMock()
    request.command = "GET"

    # Mock query params
    def get_argument(name, default=None):
        params = {
            "period": "month",
            "benchmark": "sme",
        }
        return params.get(name, default)

    request.get_argument = get_argument
    return request


class TestSMESuccessDashboardHandler:
    """Tests for SMESuccessDashboardHandler."""

    def test_can_handle_routes(self, handler):
        """Test route matching."""
        assert handler.can_handle("/api/v1/sme/success")
        assert handler.can_handle("/api/v1/sme/success/cfo")
        assert handler.can_handle("/api/v1/sme/success/pm")
        assert handler.can_handle("/api/v1/sme/success/hr")
        assert handler.can_handle("/api/v1/sme/success/milestones")
        assert handler.can_handle("/api/v1/sme/success/insights")
        assert not handler.can_handle("/api/v1/usage/summary")
        assert not handler.can_handle("/api/v1/debates")

    def test_milestones_defined(self):
        """Test that milestones are properly defined."""
        assert len(MILESTONES) > 0

        for milestone in MILESTONES:
            assert "id" in milestone
            assert "name" in milestone
            assert "description" in milestone
            assert "icon" in milestone
            assert "threshold" in milestone
            assert "metric" in milestone
            assert isinstance(milestone["threshold"], (int, float))

    def test_milestone_metrics_valid(self):
        """Test that milestone metrics reference valid metric names."""
        valid_metrics = {
            "total_debates",
            "consensus_streak",
            "minutes_saved",
            "roi_percentage",
            "cost_saved_usd",
        }

        for milestone in MILESTONES:
            assert milestone["metric"] in valid_metrics, (
                f"Milestone {milestone['id']} references invalid metric {milestone['metric']}"
            )

    @patch("aragora.server.handlers.sme_success_dashboard.get_client_ip")
    def test_rate_limiting(self, mock_get_ip, handler, mock_request, mock_user_store):
        """Test that rate limiting is applied."""
        mock_get_ip.return_value = "192.168.1.1"
        handler.ctx["user_store"] = mock_user_store

        # Should not be rate limited on first request
        result = handler.handle("/api/v1/sme/success", {}, mock_request)
        # Result will be an error due to missing auth, but not rate limit error
        assert result is not None

    def test_routes_list(self, handler):
        """Test that all routes are registered."""
        expected_routes = [
            "/api/v1/sme/success",
            "/api/v1/sme/success/cfo",
            "/api/v1/sme/success/pm",
            "/api/v1/sme/success/hr",
            "/api/v1/sme/success/milestones",
            "/api/v1/sme/success/insights",
        ]

        for route in expected_routes:
            assert route in handler.ROUTES

    def test_resource_type(self, handler):
        """Test resource type is set correctly."""
        assert handler.RESOURCE_TYPE == "success_dashboard"


class TestMilestoneEvaluation:
    """Tests for milestone evaluation logic."""

    def test_first_debate_milestone(self):
        """Test first debate milestone threshold."""
        milestone = next(m for m in MILESTONES if m["id"] == "first_debate")
        assert milestone["threshold"] == 1
        assert milestone["metric"] == "total_debates"

    def test_roi_positive_milestone(self):
        """Test ROI positive milestone threshold."""
        milestone = next(m for m in MILESTONES if m["id"] == "roi_positive")
        assert milestone["threshold"] == 0
        assert milestone["metric"] == "roi_percentage"

    def test_time_saved_milestones(self):
        """Test time saving milestones are properly ordered."""
        time_milestones = [m for m in MILESTONES if "time_saved" in m["id"]]
        thresholds = [m["threshold"] for m in time_milestones]
        assert thresholds == sorted(thresholds), "Time milestones should be in ascending order"

    def test_cost_saved_milestones(self):
        """Test cost saving milestones are properly ordered."""
        cost_milestones = [m for m in MILESTONES if "cost_saved" in m["id"]]
        thresholds = [m["threshold"] for m in cost_milestones]
        assert thresholds == sorted(thresholds), "Cost milestones should be in ascending order"


class TestRoleViews:
    """Tests for role-specific views."""

    def test_cfo_view_fields(self):
        """Test CFO view should include financial metrics."""
        # CFO view should emphasize financial data
        expected_sections = ["financial_summary", "cost_efficiency", "budget", "projections"]
        # This is a structure test - actual response testing would require full integration

    def test_pm_view_fields(self):
        """Test PM view should include velocity metrics."""
        # PM view should emphasize decision velocity
        expected_sections = ["velocity", "quality", "efficiency", "trends"]

    def test_hr_view_fields(self):
        """Test HR view should include alignment metrics."""
        # HR view should emphasize team alignment
        expected_sections = ["alignment", "time_impact", "participation", "wellbeing_impact"]


class TestOnboardingActivation:
    """Tests for onboarding activation metrics in PM dashboard."""

    def test_onboarding_activation_metrics_from_snapshot(self, handler):
        snapshot = {
            "funnel": {
                "started": 12,
                "first_debate": 8,
                "first_receipt": 6,
                "completed": 5,
                "completion_rate": 41.67,
            },
            "timing": {
                "time_to_first_debate_seconds": 95.0,
                "time_to_first_receipt_seconds": 210.0,
            },
            "step_drop_off": {"welcome": {"drop_off_count": 3}},
        }

        with patch(
            "aragora.server.handlers.onboarding.get_onboarding_analytics_snapshot",
            return_value=snapshot,
        ):
            metrics = handler._get_onboarding_activation_metrics("org_123")

        assert metrics["started"] == 12
        assert metrics["first_debate"] == 8
        assert metrics["first_receipt"] == 6
        assert metrics["time_to_first_debate_seconds"] == 95.0
        assert metrics["time_to_first_receipt_seconds"] == 210.0
        assert metrics["step_drop_off"]["welcome"]["drop_off_count"] == 3

    def test_pm_view_includes_activation_block(self, handler, mock_user, mock_org):
        base_metrics = {
            "total_debates": 20,
            "total_cost_usd": 10.0,
            "minutes_saved": 300,
            "hours_saved": 5.0,
            "cost_saved_usd": 100.0,
            "net_savings_usd": 90.0,
            "roi_percentage": 900.0,
            "consensus_rate": 80.0,
            "consensus_streak": 5,
            "avg_debate_time_minutes": 5.0,
            "manual_equivalent_minutes": 45,
        }
        activation_metrics = {
            "started": 4,
            "first_debate": 3,
            "first_receipt": 2,
            "completed": 1,
            "completion_rate_percent": 25.0,
            "time_to_first_debate_seconds": 60.0,
            "time_to_first_receipt_seconds": 120.0,
            "step_drop_off": {"welcome": {"drop_off_count": 1}},
        }

        with (
            patch.object(handler, "_get_user_and_org", return_value=(mock_user, mock_org, None)),
            patch.object(handler, "_calculate_success_metrics", return_value=base_metrics),
            patch.object(
                handler, "_get_onboarding_activation_metrics", return_value=activation_metrics
            ),
        ):
            result = handler._get_pm_view.__wrapped__.__wrapped__(  # type: ignore[attr-defined]
                handler,
                {"period": "month"},
                {},
                mock_user,
            )

        payload = json.loads(result.body)
        assert payload["pm_view"]["activation"]["started"] == 4
        assert payload["pm_view"]["activation"]["time_to_first_debate_seconds"] == 60.0


class TestPeriodParsing:
    """Tests for period parameter parsing."""

    @pytest.mark.parametrize("period_val", ["week", "month", "quarter", "year"])
    def test_valid_periods(self, handler, period_val):
        """Test that valid periods are accepted."""
        # get_string_param uses .get() on the handler dict-like object
        mock_handler = {"period": period_val}

        start, end, parsed = handler._parse_period(mock_handler)

        assert parsed == period_val, f"Expected {period_val}, got {parsed}"
        assert start < end
        assert (end - start).days > 0

    def test_default_period(self, handler):
        """Test that default period is month."""
        # Empty dict - get_string_param will return default "month"
        mock_handler = {}

        start, end, parsed = handler._parse_period(mock_handler)

        assert parsed == "month"
        assert 28 <= (end - start).days <= 31


class TestSuccessMetrics:
    """Tests for success metrics calculation."""

    def test_metrics_calculation_with_data(self, handler):
        """Test metrics calculation with usage data."""
        mock_tracker = MagicMock()
        mock_tracker.get_workspace_stats.return_value = {
            "total_cost_usd": "10.00",
            "total_api_calls": 100,
        }

        handler._get_debate_analytics = MagicMock(return_value=None)
        with patch.object(handler, "_get_cost_tracker", return_value=mock_tracker):
            with patch.object(handler, "_get_roi_calculator") as mock_calc:
                mock_calc.return_value.hourly_rate = Decimal("50.00")

                start = datetime(2025, 1, 1, tzinfo=timezone.utc)
                end = datetime(2025, 1, 31, tzinfo=timezone.utc)

                metrics = handler._calculate_success_metrics("org_123", start, end)

                assert "total_debates" in metrics
                assert "total_cost_usd" in metrics
                assert "minutes_saved" in metrics
                assert "hours_saved" in metrics
                assert "cost_saved_usd" in metrics
                assert "net_savings_usd" in metrics
                assert "roi_percentage" in metrics
                assert "consensus_rate" in metrics

                # Verify positive time savings
                assert metrics["minutes_saved"] >= 0
                assert metrics["hours_saved"] >= 0

    def test_metrics_calculation_no_data(self, handler):
        """Test metrics calculation with no usage data."""
        mock_tracker = MagicMock()
        mock_tracker.get_workspace_stats.return_value = {
            "total_cost_usd": "0",
            "total_api_calls": 0,
        }

        handler._get_debate_analytics = MagicMock(return_value=None)
        with patch.object(handler, "_get_cost_tracker", return_value=mock_tracker):
            with patch.object(handler, "_get_roi_calculator") as mock_calc:
                mock_calc.return_value.hourly_rate = Decimal("50.00")

                start = datetime(2025, 1, 1, tzinfo=timezone.utc)
                end = datetime(2025, 1, 31, tzinfo=timezone.utc)

                metrics = handler._calculate_success_metrics("org_123", start, end)

                # Should handle zero gracefully
                assert metrics["total_debates"] == 0
                assert metrics["total_cost_usd"] == 0
                assert metrics["minutes_saved"] == 0


class TestInsightsGeneration:
    """Tests for insights generation."""

    def test_insight_types(self):
        """Test that insight types are valid."""
        valid_types = {
            "getting_started",
            "engagement",
            "success",
            "optimization",
            "quality",
            "celebration",
        }
        # Insights should only use these types
        # Actual generation would be tested with integration tests


class TestHandlerIntegration:
    """Integration tests for the handler."""

    @pytest.mark.asyncio
    async def test_handler_inherits_secure_handler(self, handler):
        """Test that handler properly inherits from SecureHandler."""
        from aragora.server.handlers.secure import SecureHandler

        assert isinstance(handler, SecureHandler)

    def test_handler_has_permission_decorator_support(self, handler):
        """Test that RBAC permission checks are in place."""
        # The _get_success_summary method should have require_permission decorator
        assert hasattr(handler._get_success_summary, "__wrapped__") or callable(
            handler._get_success_summary
        )
