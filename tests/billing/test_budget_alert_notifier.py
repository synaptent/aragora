"""Tests for Budget Alert Notifier."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.billing.budget_alert_notifier import (
    BudgetAlertNotifier,
    DeliveryResult,
    NotificationStatus,
    clear_budget_alert_sinks,
    get_budget_alert_notifier,
    register_budget_alert_sink,
    setup_budget_notifications,
)


@dataclass
class MockBudgetAlert:
    """Mock BudgetAlert for testing."""

    alert_id: str = "alert-123"
    budget_id: str = "budget-456"
    org_id: str = "org-789"
    threshold_percentage: float = 0.75
    action: Any = None
    spent_usd: float = 75.0
    amount_usd: float = 100.0
    message: str = "Budget at 75% usage"
    created_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    acknowledged: bool = False
    acknowledged_by: str | None = None
    acknowledged_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "budget_id": self.budget_id,
            "org_id": self.org_id,
            "threshold_percentage": self.threshold_percentage,
            "spent_usd": self.spent_usd,
            "amount_usd": self.amount_usd,
            "message": self.message,
            "created_at": self.created_at,
            "acknowledged": self.acknowledged,
        }


@dataclass
class MockChannelSubscription:
    """Mock ChannelSubscription for testing."""

    id: str = "sub-123"
    org_id: str = "org-789"
    channel_type: str = "slack"
    channel_id: str = "C12345678"
    workspace_id: str = "T12345678"
    event_types: list[str] = field(default_factory=lambda: ["budget_alert"])
    config: dict[str, Any] = field(default_factory=dict)


@pytest.fixture
def mock_subscription_store():
    """Create a mock subscription store."""
    store = MagicMock()
    store.get_for_event.return_value = []
    return store


@pytest.fixture
def notifier(mock_subscription_store):
    """Create a notifier with mock dependencies."""
    return BudgetAlertNotifier(subscription_store=mock_subscription_store)


@pytest.fixture
def sample_alert():
    """Create a sample alert for testing."""
    return MockBudgetAlert()


@pytest.fixture(autouse=True)
def reset_budget_alert_sinks():
    """Keep process-wide sink registration isolated between tests."""
    clear_budget_alert_sinks()
    yield
    clear_budget_alert_sinks()


class TestDeliveryResult:
    """Tests for DeliveryResult dataclass."""

    def test_to_dict(self):
        """Test to_dict includes all fields."""
        result = DeliveryResult(
            channel_type="slack",
            channel_id="C123",
            status=NotificationStatus.SUCCESS,
            timestamp=1700000000.0,
        )
        d = result.to_dict()

        assert d["channel_type"] == "slack"
        assert d["channel_id"] == "C123"
        assert d["status"] == "success"
        assert d["timestamp"] == 1700000000.0
        assert "timestamp_iso" in d

    def test_auto_timestamp(self):
        """Test that timestamp is auto-generated if not provided."""
        result = DeliveryResult(
            channel_type="slack",
            channel_id="C123",
            status=NotificationStatus.SUCCESS,
        )
        assert result.timestamp > 0

    def test_failed_with_error(self):
        """Test failed result with error message."""
        result = DeliveryResult(
            channel_type="teams",
            channel_id="channel-1",
            status=NotificationStatus.FAILED,
            error="Connection timeout",
        )
        d = result.to_dict()

        assert d["status"] == "failed"
        assert d["error"] == "Connection timeout"


class TestNotificationStatus:
    """Tests for NotificationStatus enum."""

    def test_all_statuses_exist(self):
        """Test all expected statuses exist."""
        assert NotificationStatus.SUCCESS.value == "success"
        assert NotificationStatus.FAILED.value == "failed"
        assert NotificationStatus.SKIPPED.value == "skipped"


class TestBudgetAlertNotifier:
    """Tests for BudgetAlertNotifier."""

    def test_initialization(self, mock_subscription_store):
        """Test notifier initialization."""
        notifier = BudgetAlertNotifier(subscription_store=mock_subscription_store)
        assert notifier.subscription_store == mock_subscription_store

    def test_format_alert_message(self, notifier, sample_alert):
        """Test alert message formatting."""
        message = notifier._format_alert_message(sample_alert)

        assert "text" in message
        assert "blocks" in message
        assert "alert_data" in message
        assert "$75.00" in message["text"]
        assert "$100.00" in message["text"]
        assert "75.0%" in message["text"]

    def test_format_alert_message_exceeded(self, notifier):
        """Test alert formatting when budget exceeded."""
        alert = MockBudgetAlert(
            threshold_percentage=1.0,
            spent_usd=110.0,
            amount_usd=100.0,
            message="Budget exceeded!",
        )
        message = notifier._format_alert_message(alert)

        # Should have red emoji for exceeded
        assert "🔴" in message["text"]

    def test_format_alert_message_critical(self, notifier):
        """Test alert formatting at critical threshold."""
        alert = MockBudgetAlert(
            threshold_percentage=0.95,
            spent_usd=95.0,
            message="Budget at 95%",
        )
        message = notifier._format_alert_message(alert)

        # Should have orange emoji for critical
        assert "🟠" in message["text"]

    @pytest.mark.asyncio
    async def test_deliver_alert_no_subscriptions(
        self, notifier, sample_alert, mock_subscription_store
    ):
        """Test delivery when no subscriptions exist."""
        mock_subscription_store.get_for_event.return_value = []

        results = await notifier.deliver_alert(sample_alert)

        assert len(results) == 1
        assert results[0].status == NotificationStatus.SKIPPED
        assert results[0].error == "No subscriptions"

    @pytest.mark.asyncio
    async def test_deliver_alert_to_slack(self, sample_alert, mock_subscription_store):
        """Test delivery to Slack channel."""
        subscription = MockChannelSubscription(channel_type="slack")
        mock_subscription_store.get_for_event.return_value = [subscription]

        mock_slack = AsyncMock()
        notifier = BudgetAlertNotifier(
            slack_connector=mock_slack,
            subscription_store=mock_subscription_store,
        )

        results = await notifier.deliver_alert(sample_alert)

        assert len(results) == 1
        assert results[0].status == NotificationStatus.SUCCESS
        assert results[0].channel_type == "slack"
        mock_slack.post_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_deliver_alert_to_teams(self, sample_alert, mock_subscription_store):
        """Test delivery to Teams channel."""
        subscription = MockChannelSubscription(
            channel_type="teams",
            workspace_id="tenant-123",
        )
        mock_subscription_store.get_for_event.return_value = [subscription]

        mock_teams = AsyncMock()
        notifier = BudgetAlertNotifier(
            teams_connector=mock_teams,
            subscription_store=mock_subscription_store,
        )

        results = await notifier.deliver_alert(sample_alert)

        assert len(results) == 1
        assert results[0].status == NotificationStatus.SUCCESS
        assert results[0].channel_type == "teams"
        mock_teams.post_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_deliver_alert_uses_registered_sink(self, sample_alert, mock_subscription_store):
        """Fallback delivery resolves a connector-owned registered sink."""
        subscription = MockChannelSubscription(channel_type="slack")
        mock_subscription_store.get_for_event.return_value = [subscription]
        sink = AsyncMock()
        register_budget_alert_sink("slack", sink)

        notifier = BudgetAlertNotifier(subscription_store=mock_subscription_store)
        results = await notifier.deliver_alert(sample_alert)

        assert results[0].status == NotificationStatus.SUCCESS
        sink.deliver.assert_awaited_once_with(
            workspace_id=subscription.workspace_id,
            channel_id=subscription.channel_id,
            message=notifier._format_alert_message(sample_alert),
            config=subscription.config,
        )

    @pytest.mark.asyncio
    async def test_deliver_alert_fails_when_sink_unregistered(
        self, sample_alert, mock_subscription_store
    ):
        """Missing external capability is reported as a failed delivery."""
        subscription = MockChannelSubscription(channel_type="slack")
        mock_subscription_store.get_for_event.return_value = [subscription]

        notifier = BudgetAlertNotifier(subscription_store=mock_subscription_store)
        results = await notifier.deliver_alert(sample_alert)

        assert results[0].status == NotificationStatus.FAILED

    @pytest.mark.asyncio
    async def test_deliver_alert_handles_failure(self, sample_alert, mock_subscription_store):
        """Test delivery handles connector failure gracefully."""
        subscription = MockChannelSubscription(channel_type="slack")
        mock_subscription_store.get_for_event.return_value = [subscription]

        mock_slack = AsyncMock()
        mock_slack.post_message.side_effect = ConnectionError("Connection failed")

        notifier = BudgetAlertNotifier(
            slack_connector=mock_slack,
            subscription_store=mock_subscription_store,
        )

        results = await notifier.deliver_alert(sample_alert)

        assert len(results) == 1
        assert results[0].status == NotificationStatus.FAILED
        assert "failed" in results[0].error.lower()

    @pytest.mark.asyncio
    async def test_deliver_alert_multiple_channels(self, sample_alert, mock_subscription_store):
        """Test delivery to multiple channels."""
        subscriptions = [
            MockChannelSubscription(id="sub-1", channel_type="slack", channel_id="C1"),
            MockChannelSubscription(id="sub-2", channel_type="teams", channel_id="teams-1"),
        ]
        mock_subscription_store.get_for_event.return_value = subscriptions

        mock_slack = AsyncMock()
        mock_teams = AsyncMock()

        notifier = BudgetAlertNotifier(
            slack_connector=mock_slack,
            teams_connector=mock_teams,
            subscription_store=mock_subscription_store,
        )

        results = await notifier.deliver_alert(sample_alert)

        assert len(results) == 2
        mock_slack.post_message.assert_called_once()
        mock_teams.post_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_deliver_alert_unsupported_channel_type(
        self, sample_alert, mock_subscription_store
    ):
        """Test delivery skips unsupported channel types."""
        subscription = MockChannelSubscription(channel_type="sms")  # Unsupported
        mock_subscription_store.get_for_event.return_value = [subscription]

        notifier = BudgetAlertNotifier(subscription_store=mock_subscription_store)

        results = await notifier.deliver_alert(sample_alert)

        assert len(results) == 1
        assert results[0].status == NotificationStatus.SKIPPED
        assert "Unsupported channel type" in results[0].error

    def test_on_alert_sync_wrapper(self, mock_subscription_store):
        """Test on_alert runs async delivery in sync context."""
        mock_subscription_store.get_for_event.return_value = []
        notifier = BudgetAlertNotifier(subscription_store=mock_subscription_store)

        # Should not raise, even though it runs async code
        notifier.on_alert(MockBudgetAlert())

        mock_subscription_store.get_for_event.assert_called_once()

    def test_delivery_history(self, notifier):
        """Test delivery history is recorded."""
        result = DeliveryResult(
            channel_type="slack",
            channel_id="C123",
            status=NotificationStatus.SUCCESS,
        )
        notifier._record_delivery(result)

        history = notifier.get_delivery_history()
        assert len(history) == 1
        assert history[0].channel_id == "C123"

    def test_delivery_history_limit(self, notifier):
        """Test delivery history respects limit."""
        for i in range(100):
            notifier._record_delivery(
                DeliveryResult(
                    channel_type="slack",
                    channel_id=f"C{i}",
                    status=NotificationStatus.SUCCESS,
                )
            )

        history = notifier.get_delivery_history(limit=10)
        assert len(history) == 10

    def test_delivery_history_filter_by_status(self, notifier):
        """Test delivery history filtering by status."""
        notifier._record_delivery(
            DeliveryResult(
                channel_type="slack",
                channel_id="C1",
                status=NotificationStatus.SUCCESS,
            )
        )
        notifier._record_delivery(
            DeliveryResult(
                channel_type="slack",
                channel_id="C2",
                status=NotificationStatus.FAILED,
                error="Test error",
            )
        )

        success_only = notifier.get_delivery_history(status=NotificationStatus.SUCCESS)
        assert len(success_only) == 1
        assert success_only[0].channel_id == "C1"


class TestSetupBudgetNotifications:
    """Tests for setup_budget_notifications helper."""

    def test_registers_callback(self):
        """Test that setup registers callback with manager."""
        mock_manager = MagicMock()

        notifier = setup_budget_notifications(mock_manager)

        mock_manager.register_alert_callback.assert_called_once()
        assert notifier is not None


class TestGetBudgetAlertNotifier:
    """Tests for get_budget_alert_notifier helper."""

    def test_returns_notifier(self):
        """Test that helper returns a notifier instance."""
        notifier = get_budget_alert_notifier()
        assert isinstance(notifier, BudgetAlertNotifier)

    def test_returns_same_instance(self):
        """Test singleton behavior."""
        notifier1 = get_budget_alert_notifier()
        notifier2 = get_budget_alert_notifier()
        assert notifier1 is notifier2
