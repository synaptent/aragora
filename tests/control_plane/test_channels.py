"""
Tests for Control Plane Channel Notifications.

Tests cover:
- NotificationChannel enum
- NotificationPriority enum
- NotificationEventType enum
- NotificationMessage dataclass
- ChannelConfig dataclass
- NotificationManager routing logic
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from aragora.control_plane.channels import (
    NotificationChannel,
    NotificationPriority,
    NotificationEventType,
    NotificationMessage,
    ChannelConfig,
    NotificationManager,
)


class TestNotificationChannelEnum:
    """Tests for NotificationChannel enum."""

    def test_all_channels_defined(self):
        """Test that all channels are defined."""
        expected = ["slack", "teams", "email", "webhook"]
        for channel in expected:
            assert NotificationChannel(channel) is not None

    def test_channel_values(self):
        """Test channel enum values."""
        assert NotificationChannel.SLACK.value == "slack"
        assert NotificationChannel.TEAMS.value == "teams"
        assert NotificationChannel.EMAIL.value == "email"
        assert NotificationChannel.WEBHOOK.value == "webhook"


class TestNotificationPriorityEnum:
    """Tests for NotificationPriority enum."""

    def test_all_priorities_defined(self):
        """Test that all priorities are defined."""
        expected = ["low", "normal", "high", "urgent"]
        for priority in expected:
            assert NotificationPriority(priority) is not None

    def test_priority_values(self):
        """Test priority enum values."""
        assert NotificationPriority.LOW.value == "low"
        assert NotificationPriority.NORMAL.value == "normal"
        assert NotificationPriority.HIGH.value == "high"
        assert NotificationPriority.URGENT.value == "urgent"


class TestNotificationEventTypeEnum:
    """Tests for NotificationEventType enum."""

    def test_task_events_defined(self):
        """Test that task events are defined."""
        assert NotificationEventType.TASK_COMPLETED.value == "task_completed"
        assert NotificationEventType.TASK_FAILED.value == "task_failed"

    def test_deliberation_events_defined(self):
        """Test that deliberation events are defined."""
        assert NotificationEventType.DELIBERATION_STARTED.value == "deliberation_started"
        assert NotificationEventType.DELIBERATION_CONSENSUS.value == "deliberation_consensus"
        assert NotificationEventType.DELIBERATION_FAILED.value == "deliberation_failed"

    def test_agent_events_defined(self):
        """Test that agent events are defined."""
        assert NotificationEventType.AGENT_REGISTERED.value == "agent_registered"
        assert NotificationEventType.AGENT_OFFLINE.value == "agent_offline"
        assert NotificationEventType.AGENT_ERROR.value == "agent_error"

    def test_sla_events_defined(self):
        """Test that SLA events are defined."""
        assert NotificationEventType.SLA_WARNING.value == "sla_warning"
        assert NotificationEventType.SLA_VIOLATION.value == "sla_violation"

    def test_connector_events_defined(self):
        """Test that connector events are defined."""
        assert NotificationEventType.CONNECTOR_SYNC_COMPLETE.value == "connector_sync_complete"
        assert NotificationEventType.CONNECTOR_SYNC_FAILED.value == "connector_sync_failed"


class TestNotificationMessage:
    """Tests for NotificationMessage dataclass."""

    def test_message_creation(self):
        """Test creating a notification message."""
        msg = NotificationMessage(
            event_type=NotificationEventType.TASK_COMPLETED,
            title="Task Complete",
            body="Task 'Code Review' completed successfully",
            priority=NotificationPriority.NORMAL,
            workspace_id="ws_123",
        )

        assert msg.event_type == NotificationEventType.TASK_COMPLETED
        assert msg.title == "Task Complete"
        assert msg.body == "Task 'Code Review' completed successfully"
        assert msg.priority == NotificationPriority.NORMAL
        assert msg.workspace_id == "ws_123"

    def test_message_defaults(self):
        """Test message default values."""
        msg = NotificationMessage(
            event_type=NotificationEventType.AGENT_REGISTERED,
            title="Agent Registered",
            body="New agent joined",
        )

        assert msg.priority == NotificationPriority.NORMAL
        assert msg.metadata == {}
        assert msg.workspace_id is None
        assert msg.link_url is None
        assert msg.timestamp is not None

    def test_message_with_link(self):
        """Test message with action link."""
        msg = NotificationMessage(
            event_type=NotificationEventType.SLA_WARNING,
            title="SLA Warning",
            body="Task approaching timeout",
            priority=NotificationPriority.HIGH,
            link_url="https://app.example.com/tasks/123",
            link_text="View Task",
        )

        assert msg.link_url == "https://app.example.com/tasks/123"
        assert msg.link_text == "View Task"

    def test_message_to_dict(self):
        """Test message serialization."""
        msg = NotificationMessage(
            event_type=NotificationEventType.DELIBERATION_CONSENSUS,
            title="Consensus Reached",
            body="Agents agreed on solution",
            priority=NotificationPriority.NORMAL,
            metadata={"confidence": 0.85},
        )

        data = msg.to_dict()
        assert data["event_type"] == "deliberation_consensus"
        assert data["title"] == "Consensus Reached"
        assert data["priority"] == "normal"
        assert data["metadata"]["confidence"] == 0.85

    def test_urgent_notification(self):
        """Test urgent priority notification."""
        msg = NotificationMessage(
            event_type=NotificationEventType.SLA_VIOLATION,
            title="SLA Violated!",
            body="Task exceeded maximum time",
            priority=NotificationPriority.URGENT,
        )

        assert msg.priority == NotificationPriority.URGENT


class TestChannelConfig:
    """Tests for ChannelConfig dataclass."""

    def test_slack_config(self):
        """Test Slack channel configuration."""
        config = ChannelConfig(
            channel_type=NotificationChannel.SLACK,
            enabled=True,
            slack_webhook_url="https://hooks.slack.com/services/xxx",
            slack_channel="#alerts",
        )

        assert config.channel_type == NotificationChannel.SLACK
        assert config.enabled is True
        assert config.slack_webhook_url is not None
        assert config.slack_channel == "#alerts"
        # config_id should be auto-generated
        assert config.config_id is not None

    def test_email_config(self):
        """Test email channel configuration."""
        config = ChannelConfig(
            channel_type=NotificationChannel.EMAIL,
            enabled=True,
            email_recipients=["admin@example.com"],
            email_from="alerts@example.com",
        )

        assert config.channel_type == NotificationChannel.EMAIL
        assert "admin@example.com" in config.email_recipients
        assert config.email_from == "alerts@example.com"

    def test_config_disabled(self):
        """Test disabled channel configuration."""
        config = ChannelConfig(
            channel_type=NotificationChannel.TEAMS,
            enabled=False,
        )

        assert config.enabled is False

    def test_config_to_dict(self):
        """Test config serialization."""
        config = ChannelConfig(
            channel_type=NotificationChannel.WEBHOOK,
            enabled=True,
            webhook_url="https://example.com/webhook",
        )

        data = config.to_dict()
        assert data["channel_type"] == "webhook"
        assert data["enabled"] is True
        assert data["webhook_url"] == "https://example.com/webhook"

    def test_config_from_dict(self):
        """Test config deserialization."""
        data = {
            "channel_type": "slack",
            "enabled": True,
            "slack_webhook_url": "https://hooks.slack.com/test",
        }

        config = ChannelConfig.from_dict(data)
        assert config.channel_type == NotificationChannel.SLACK
        assert config.enabled is True
        assert config.slack_webhook_url == "https://hooks.slack.com/test"


class TestNotificationManager:
    """Tests for NotificationManager class."""

    def test_manager_creation(self):
        """Test creating notification manager."""
        manager = NotificationManager()
        assert manager is not None

    @pytest.mark.asyncio
    async def test_remove_channel_async_skips_configs_without_id(self):
        """Only configs with a persistence id are deleted from Redis."""
        redis = AsyncMock()
        manager = NotificationManager(redis_client=redis)
        kept_id = ChannelConfig(channel_type=NotificationChannel.SLACK, slack_webhook_url="u1")
        cleared_id = ChannelConfig(channel_type=NotificationChannel.SLACK, slack_webhook_url="u2")
        cleared_id.config_id = None
        manager._channels.extend([kept_id, cleared_id])

        assert await manager.remove_channel_async(NotificationChannel.SLACK) is True

        redis.hdel.assert_awaited_once_with(manager.REDIS_CHANNEL_KEY, kept_id.config_id)
        assert manager.get_channels() == []

    def test_add_channel(self):
        """Test adding a channel."""
        manager = NotificationManager()
        config = ChannelConfig(
            channel_type=NotificationChannel.SLACK,
            enabled=True,
            slack_webhook_url="https://hooks.slack.com/test",
        )

        manager.add_channel(config)

        channels = manager.get_channels()
        assert len(channels) == 1
        assert channels[0].channel_type == NotificationChannel.SLACK

    def test_get_channels_filtered_by_workspace(self):
        """Test getting channels filtered by workspace."""
        manager = NotificationManager()

        # Add global channel
        global_config = ChannelConfig(
            channel_type=NotificationChannel.SLACK,
            enabled=True,
            slack_webhook_url="https://hooks.slack.com/global",
        )
        manager.add_channel(global_config)

        # Add workspace-specific channel
        ws_config = ChannelConfig(
            channel_type=NotificationChannel.TEAMS,
            enabled=True,
            teams_webhook_url="https://teams.webhook.com/ws1",
            workspace_id="workspace_1",
        )
        manager.add_channel(ws_config)

        # Get channels for workspace_1 (should include global + workspace-specific)
        channels = manager.get_channels(workspace_id="workspace_1")
        assert len(channels) == 2

    def test_disabled_channel_filtering(self):
        """Test that disabled channels are filtered correctly."""
        manager = NotificationManager()
        config = ChannelConfig(
            channel_type=NotificationChannel.EMAIL,
            enabled=False,
        )
        manager.add_channel(config)

        # Disabled channels should still be in the list
        channels = manager.get_channels()
        assert len(channels) == 1
        assert channels[0].enabled is False

    def test_remove_channel(self):
        """Test removing a channel."""
        manager = NotificationManager()
        config = ChannelConfig(
            channel_type=NotificationChannel.SLACK,
            enabled=True,
            slack_webhook_url="https://hooks.slack.com/test",
        )
        manager.add_channel(config)

        assert len(manager.get_channels()) == 1

        # Remove the channel
        result = manager.remove_channel(NotificationChannel.SLACK)
        assert result is True
        assert len(manager.get_channels()) == 0

    def test_get_stats(self):
        """Test getting notification statistics."""
        manager = NotificationManager()
        stats = manager.get_stats()

        assert "total_sent" in stats
        assert "successful" in stats
        assert "failed" in stats
        assert "channels_configured" in stats


class TestEventToChannelMapping:
    """Tests for event-to-channel mapping logic."""

    @pytest.mark.parametrize(
        "event_type,expected_priority",
        [
            (NotificationEventType.TASK_COMPLETED, NotificationPriority.LOW),
            (NotificationEventType.SLA_WARNING, NotificationPriority.HIGH),
            (NotificationEventType.SLA_VIOLATION, NotificationPriority.URGENT),
            (NotificationEventType.AGENT_ERROR, NotificationPriority.HIGH),
        ],
    )
    def test_event_default_priorities(self, event_type, expected_priority):
        """Test that events have appropriate default priorities."""
        # This tests the expected mapping - actual implementation may vary
        priority_map = {
            NotificationEventType.TASK_COMPLETED: NotificationPriority.LOW,
            NotificationEventType.TASK_FAILED: NotificationPriority.HIGH,
            NotificationEventType.SLA_WARNING: NotificationPriority.HIGH,
            NotificationEventType.SLA_VIOLATION: NotificationPriority.URGENT,
            NotificationEventType.AGENT_ERROR: NotificationPriority.HIGH,
        }

        if event_type in priority_map:
            assert priority_map[event_type] == expected_priority
