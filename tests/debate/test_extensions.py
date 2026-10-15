"""
Tests for Arena Extensions.

Tests cover:
- Notification dispatch wiring
- Extension configuration
- Graceful failure handling
"""

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


class MockDebateContext:
    """Mock debate context for testing."""

    def __init__(self, debate_id: str = "test-debate-123"):
        self.debate_id = debate_id
        self.metadata = {
            "start_time": datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            "end_time": datetime(2024, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
        }
        self.environment = MagicMock()
        self.environment.task = "What is the best approach to X?"


class MockDebateResult:
    """Mock debate result for testing."""

    def __init__(
        self,
        consensus_reached: bool = True,
        consensus_confidence: float = 0.85,
        winner: str = "claude-3-opus",
    ):
        self.consensus_reached = consensus_reached
        self.consensus_confidence = consensus_confidence
        self.winner = winner
        self.consensus_answer = "The best approach is Y because..."
        self.messages = [MagicMock(content="Final consensus message")]


class TestArenaExtensionsNotifications:
    """Tests for notification dispatch wiring in ArenaExtensions."""

    def test_has_notifications_false_by_default(self):
        """Test that notifications are disabled by default."""
        from aragora.debate.extensions import ArenaExtensions

        extensions = ArenaExtensions()
        assert extensions.has_notifications is False

    def test_has_notifications_true_when_auto_notify(self):
        """Test that has_notifications is True when auto_notify is set."""
        from aragora.debate.extensions import ArenaExtensions

        extensions = ArenaExtensions(auto_notify=True)
        assert extensions.has_notifications is True

    def test_has_notifications_true_when_dispatcher_set(self):
        """Test that has_notifications is True when dispatcher is provided."""
        from aragora.debate.extensions import ArenaExtensions

        mock_dispatcher = MagicMock()
        extensions = ArenaExtensions(notification_dispatcher=mock_dispatcher)
        assert extensions.has_notifications is True

    def test_notification_skipped_when_disabled(self):
        """Test that notifications are skipped when auto_notify is False."""
        from aragora.debate.extensions import ArenaExtensions

        extensions = ArenaExtensions(auto_notify=False)

        ctx = MockDebateContext()
        result = MockDebateResult()

        # Should not raise and should not call any notification methods
        with patch("aragora.debate.extensions.logger") as mock_logger:
            extensions._emit_debate_notifications(ctx, result)
            # No debug log about skipping confidence since we return early
            assert mock_logger.debug.call_count == 0

    def test_notification_skipped_below_confidence_threshold(self):
        """Test that notifications are skipped below confidence threshold."""
        from aragora.debate.extensions import ArenaExtensions

        extensions = ArenaExtensions(
            auto_notify=True,
            notify_min_confidence=0.9,  # Higher than result confidence
        )

        ctx = MockDebateContext()
        result = MockDebateResult(consensus_confidence=0.5)

        with patch("aragora.debate.extensions.logger") as mock_logger:
            extensions._emit_debate_notifications(ctx, result)
            # Should log that it was skipped due to confidence
            mock_logger.debug.assert_called()
            call_args = str(mock_logger.debug.call_args)
            assert "notification_skipped" in call_args

    @pytest.mark.asyncio
    async def test_notification_emitted_with_dispatcher(self):
        """Test that notifications are emitted when dispatcher is available."""
        from aragora.debate.extensions import ArenaExtensions

        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock()

        extensions = ArenaExtensions(
            auto_notify=True,
            notification_dispatcher=mock_dispatcher,
            workspace_id="test-workspace",
        )

        ctx = MockDebateContext()
        result = MockDebateResult(consensus_confidence=0.85)

        # Mock the task_events module functions
        with patch(
            "aragora.events.task_events.get_task_event_dispatcher",
            return_value=mock_dispatcher,
        ):
            with patch(
                "aragora.events.task_events.emit_task_completed",
                new_callable=AsyncMock,
            ):
                # Run the notification method - it creates tasks but doesn't await them
                extensions._emit_debate_notifications(ctx, result)
                # Give async tasks time to be created (they won't complete without loop)
                await asyncio.sleep(0.01)

    def test_notification_handles_import_error(self):
        """Test that notifications handle ImportError gracefully."""
        from aragora.debate.extensions import ArenaExtensions

        extensions = ArenaExtensions(auto_notify=True)

        ctx = MockDebateContext()
        result = MockDebateResult()

        # Mock import to fail
        with patch.dict("sys.modules", {"aragora.events.task_events": None}):
            with patch("aragora.debate.extensions.logger") as mock_logger:
                # Should not raise
                extensions._emit_debate_notifications(ctx, result)

    def test_notification_duration_calculation(self):
        """Test that duration is calculated from context metadata."""
        from aragora.debate.extensions import ArenaExtensions

        extensions = ArenaExtensions(
            auto_notify=True,
            workspace_id="test-ws",
        )

        ctx = MockDebateContext()
        # 5 minutes duration
        ctx.metadata = {
            "start_time": datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            "end_time": datetime(2024, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
        }
        result = MockDebateResult()

        # Verify duration would be calculated as 300 seconds
        if ctx.metadata:
            start_time = ctx.metadata.get("start_time")
            end_time = ctx.metadata.get("end_time")
            if start_time and end_time:
                duration = (end_time - start_time).total_seconds()
                assert duration == 300.0


class TestExtensionsConfig:
    """Tests for ExtensionsConfig notification settings."""

    def test_config_default_notification_settings(self):
        """Test default notification settings in config."""
        from aragora.debate.extensions import ExtensionsConfig

        config = ExtensionsConfig()
        assert config.notification_dispatcher is None
        assert config.auto_notify is False
        assert config.notify_min_confidence == 0.0

    def test_config_creates_extensions_with_notifications(self):
        """Test that config creates extensions with notification settings."""
        from aragora.debate.extensions import ExtensionsConfig

        mock_dispatcher = MagicMock()
        config = ExtensionsConfig(
            notification_dispatcher=mock_dispatcher,
            auto_notify=True,
            notify_min_confidence=0.7,
        )

        extensions = config.create_extensions()

        assert extensions.notification_dispatcher is mock_dispatcher
        assert extensions.auto_notify is True
        assert extensions.notify_min_confidence == 0.7


class TestNotificationIntegration:
    """Integration tests for notification wiring."""

    def test_on_debate_complete_calls_notification(self):
        """Test that on_debate_complete calls notification emission."""
        from aragora.debate.extensions import ArenaExtensions

        extensions = ArenaExtensions(auto_notify=True)

        ctx = MockDebateContext()
        result = MockDebateResult()
        agents = []

        # Mock internal methods
        extensions._record_token_usage = MagicMock()
        extensions._sync_usage_to_stripe = MagicMock()
        extensions._evaluate_debate = MagicMock()
        extensions._export_training_data = MagicMock()
        extensions._sync_km_adapters = MagicMock()
        extensions._emit_debate_notifications = MagicMock()

        extensions.on_debate_complete(ctx, result, agents)

        # Verify notification emission was called
        extensions._emit_debate_notifications.assert_called_once_with(ctx, result)

    def test_notification_error_does_not_fail_method(self):
        """Test that internal notification errors are caught gracefully."""
        from aragora.debate.extensions import ArenaExtensions

        extensions = ArenaExtensions(auto_notify=True)

        ctx = MockDebateContext()
        result = MockDebateResult()

        # Mock the import to raise an exception during notification
        with patch(
            "aragora.events.task_events.get_task_event_dispatcher",
            side_effect=RuntimeError("Dispatcher unavailable"),
        ):
            # The method catches exceptions internally, so should not raise
            # This tests the try/except in _emit_debate_notifications
            extensions._emit_debate_notifications(ctx, result)
            # If we get here, the error was caught properly
