"""
Tests for cost anomaly enforcement pipeline.

Covers:
- BudgetManager.handle_cost_anomaly() suspends on critical
- BudgetManager.is_budget_suspended() query
- Non-critical anomalies do not suspend
- detect_and_store_anomalies calls handle_cost_anomaly
- Debate setup_debate_budget checks suspension state
- COST_ANOMALY event emission
"""

from __future__ import annotations

import os
import tempfile
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.billing.budget_manager import (
    Budget,
    BudgetManager,
    BudgetPeriod,
    BudgetStatus,
)


@pytest.fixture
def temp_db():
    """Create a temporary database file for tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def manager(temp_db):
    """Create a BudgetManager with temporary database."""
    return BudgetManager(db_path=temp_db)


# =============================================================================
# handle_cost_anomaly tests
# =============================================================================


class TestHandleCostAnomaly:
    """Tests for BudgetManager.handle_cost_anomaly."""

    def test_critical_anomaly_suspends_budget(self, manager):
        """Critical anomaly suspends all active budgets for org."""
        manager.create_budget(
            org_id="org-1",
            name="Test Budget",
            amount_usd=100.0,
        )

        suspended = manager.handle_cost_anomaly(
            org_id="org-1",
            anomaly_type="spike",
            severity="critical",
            amount=500.0,
            expected=50.0,
        )

        assert suspended is True

        budgets = manager.get_budgets_for_org("org-1", active_only=False)
        assert len(budgets) == 1
        assert budgets[0].status == BudgetStatus.SUSPENDED

    def test_warning_anomaly_does_not_suspend(self, manager):
        """Warning anomaly does not suspend budgets."""
        manager.create_budget(
            org_id="org-2",
            name="Test Budget",
            amount_usd=100.0,
        )

        suspended = manager.handle_cost_anomaly(
            org_id="org-2",
            anomaly_type="drift",
            severity="warning",
            amount=80.0,
            expected=50.0,
        )

        assert suspended is False

        budgets = manager.get_budgets_for_org("org-2", active_only=True)
        assert len(budgets) == 1
        assert budgets[0].status == BudgetStatus.ACTIVE

    def test_info_anomaly_does_not_suspend(self, manager):
        """Info anomaly does not suspend budgets."""
        manager.create_budget(
            org_id="org-3",
            name="Test Budget",
            amount_usd=100.0,
        )

        suspended = manager.handle_cost_anomaly(
            org_id="org-3",
            anomaly_type="minor_increase",
            severity="info",
            amount=60.0,
            expected=50.0,
        )

        assert suspended is False

    def test_critical_suspends_multiple_budgets(self, manager):
        """Critical anomaly suspends all active budgets."""
        manager.create_budget(
            org_id="org-4",
            name="Budget A",
            amount_usd=100.0,
        )
        manager.create_budget(
            org_id="org-4",
            name="Budget B",
            amount_usd=200.0,
        )

        suspended = manager.handle_cost_anomaly(
            org_id="org-4",
            anomaly_type="spike",
            severity="critical",
            amount=1000.0,
            expected=100.0,
        )

        assert suspended is True

        budgets = manager.get_budgets_for_org("org-4", active_only=False)
        suspended_count = sum(1 for b in budgets if b.status == BudgetStatus.SUSPENDED)
        assert suspended_count == 2

    def test_no_budgets_returns_false(self, manager):
        """No budgets for org returns False."""
        suspended = manager.handle_cost_anomaly(
            org_id="org-nonexistent",
            anomaly_type="spike",
            severity="critical",
            amount=500.0,
            expected=50.0,
        )

        assert suspended is False


# =============================================================================
# is_budget_suspended tests
# =============================================================================


class TestIsBudgetSuspended:
    """Tests for BudgetManager.is_budget_suspended."""

    def test_not_suspended_initially(self, manager):
        """New budgets are not suspended."""
        manager.create_budget(
            org_id="org-s1",
            name="Active Budget",
            amount_usd=100.0,
        )

        assert manager.is_budget_suspended("org-s1") is False

    def test_suspended_after_critical_anomaly(self, manager):
        """Budget shows as suspended after critical anomaly."""
        manager.create_budget(
            org_id="org-s2",
            name="Test Budget",
            amount_usd=100.0,
        )

        manager.handle_cost_anomaly(
            org_id="org-s2",
            anomaly_type="spike",
            severity="critical",
            amount=500.0,
            expected=50.0,
        )

        assert manager.is_budget_suspended("org-s2") is True

    def test_not_suspended_for_unknown_org(self, manager):
        """Unknown org returns False."""
        assert manager.is_budget_suspended("org-unknown") is False

    def test_suspended_budget_blocks_spending(self, manager):
        """Suspended budget blocks can_spend."""
        budget = manager.create_budget(
            org_id="org-s3",
            name="Test Budget",
            amount_usd=100.0,
        )

        manager.handle_cost_anomaly(
            org_id="org-s3",
            anomaly_type="spike",
            severity="critical",
            amount=500.0,
            expected=50.0,
        )

        # Re-fetch budget to get updated status
        updated = manager.get_budget(budget.budget_id)
        assert updated is not None
        allowed, reason = updated.can_spend(10.0)
        assert allowed is False
        assert "suspended" in reason.lower()


# =============================================================================
# Cost tracker integration tests
# =============================================================================


class TestCostTrackerEnforcement:
    """Test detect_and_store_anomalies calls budget enforcement."""

    @pytest.mark.asyncio
    async def test_critical_anomaly_triggers_enforcement(self):
        """Critical anomaly in detect_and_store_anomalies calls handle_cost_anomaly."""
        from aragora.billing.cost_tracker import CostTracker

        mock_adapter = MagicMock()
        mock_anomaly = MagicMock()
        mock_anomaly.to_dict.return_value = {
            "type": "spike",
            "severity": "critical",
            "actual": 500.0,
            "expected": 50.0,
            "description": "Critical cost spike",
        }
        mock_adapter.detect_anomalies.return_value = [mock_anomaly]
        mock_adapter.store_anomaly.return_value = "anomaly-id-1"

        tracker = CostTracker(km_adapter=mock_adapter)
        tracker._workspace_stats["ws-enforce"] = {
            "total_cost": Decimal("500"),
            "tokens_in": 10000,
            "tokens_out": 2000,
            "api_calls": 20,
        }

        mock_mgr = MagicMock()
        mock_mgr.handle_cost_anomaly.return_value = True

        with (
            patch(
                "aragora.billing.cost_tracker.notify_cost_anomaly",
                new_callable=AsyncMock,
            ),
            patch(
                "aragora.billing.cost_tracker.get_budget_manager",
                return_value=mock_mgr,
            ),
        ):
            anomalies, advisory = await tracker.detect_and_store_anomalies("ws-enforce")

            assert len(anomalies) == 1
            mock_mgr.handle_cost_anomaly.assert_called_once_with(
                org_id="ws-enforce",
                anomaly_type="spike",
                severity="critical",
                amount=500.0,
                expected=50.0,
            )

    @pytest.mark.asyncio
    async def test_enforcement_failure_doesnt_break_detection(self):
        """Budget enforcement failure doesn't break anomaly detection."""
        from aragora.billing.cost_tracker import CostTracker

        mock_adapter = MagicMock()
        mock_anomaly = MagicMock()
        mock_anomaly.to_dict.return_value = {
            "type": "spike",
            "severity": "critical",
            "actual": 500.0,
            "expected": 50.0,
        }
        mock_adapter.detect_anomalies.return_value = [mock_anomaly]
        mock_adapter.store_anomaly.return_value = "anomaly-id-2"

        tracker = CostTracker(km_adapter=mock_adapter)
        tracker._workspace_stats["ws-fail"] = {
            "total_cost": Decimal("500"),
            "tokens_in": 10000,
            "tokens_out": 2000,
            "api_calls": 20,
        }

        with (
            patch(
                "aragora.billing.cost_tracker.notify_cost_anomaly",
                new_callable=AsyncMock,
            ),
            patch(
                "aragora.billing.cost_tracker.get_budget_manager",
                side_effect=RuntimeError("DB unavailable"),
            ),
        ):
            anomalies, advisory = await tracker.detect_and_store_anomalies("ws-fail")
            assert len(anomalies) == 1


# =============================================================================
# Debate suspension check tests
# =============================================================================


class TestDebateSuspensionCheck:
    """Test that debate setup checks for budget suspension."""

    def test_suspended_budget_blocks_debate_setup(self, temp_db):
        """setup_debate_budget raises RuntimeError if budget is suspended."""
        from aragora.debate.extensions import DebateExtensions

        mgr = BudgetManager(db_path=temp_db)
        mgr.create_budget(
            org_id="org-debate",
            name="Test Budget",
            amount_usd=100.0,
        )
        mgr.handle_cost_anomaly(
            org_id="org-debate",
            anomaly_type="spike",
            severity="critical",
            amount=500.0,
            expected=50.0,
        )

        ext = DebateExtensions()
        ext.org_id = "org-debate"
        ext.debate_budget_limit_usd = 10.0

        with patch(
            "aragora.debate.extensions.get_budget_manager",
            return_value=mgr,
        ):
            with pytest.raises(RuntimeError, match="Budget suspended"):
                ext.setup_debate_budget("debate-123")

    def test_active_budget_allows_debate_setup(self, temp_db):
        """setup_debate_budget proceeds if budget is active."""
        from aragora.debate.extensions import DebateExtensions

        mgr = BudgetManager(db_path=temp_db)
        mgr.create_budget(
            org_id="org-ok",
            name="Active Budget",
            amount_usd=100.0,
        )

        ext = DebateExtensions()
        ext.org_id = "org-ok"
        ext.debate_budget_limit_usd = 10.0

        with (
            patch(
                "aragora.debate.extensions.get_budget_manager",
                return_value=mgr,
            ),
            patch(
                "aragora.debate.extensions.get_cost_tracker",
            ) as mock_ct,
        ):
            ext.setup_debate_budget("debate-456")
            # Should not raise; cost tracker should be set up
            mock_ct.return_value.set_debate_limit.assert_called_once()

    def test_no_org_id_skips_suspension_check(self):
        """No org_id attribute skips suspension check."""
        from aragora.debate.extensions import DebateExtensions

        ext = DebateExtensions()
        ext.debate_budget_limit_usd = None

        # Should not raise (no org_id, no budget limit)
        ext.setup_debate_budget("debate-789")


# =============================================================================
# Event emission tests
# =============================================================================


class TestCostAnomalyEvent:
    """Test COST_ANOMALY event type existence."""

    def test_cost_anomaly_event_type_exists(self):
        from aragora.events.types import StreamEventType

        assert StreamEventType.COST_ANOMALY.value == "cost_anomaly"

    def test_budget_alert_event_type_exists(self):
        from aragora.events.types import StreamEventType

        assert StreamEventType.BUDGET_ALERT.value == "budget_alert"
