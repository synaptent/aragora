"""Tests for Cross-Subsystem Event Subscribers.

Tests cover:
- Subscriber registration
- Event dispatching
- Built-in handler execution
- Statistics tracking
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from aragora.events.types import StreamEvent, StreamEventType
from aragora.events.cross_subscribers import (
    CrossSubscriberManager,
    SubscriberStats,
    get_cross_subscriber_manager,
    reset_cross_subscriber_manager,
)


def make_stream_event(
    event_type: StreamEventType,
    data: dict = None,
) -> StreamEvent:
    """Factory for creating test stream events."""
    return StreamEvent(
        type=event_type,
        data=data or {},
        round=0,
        agent="test_agent",
    )


class TestCrossSubscriberManager:
    """Test CrossSubscriberManager class."""

    def setup_method(self):
        """Reset global state before each test."""
        reset_cross_subscriber_manager()

    def test_init_registers_builtin_subscribers(self):
        """Test manager registers built-in subscribers on init."""
        manager = CrossSubscriberManager()

        # Should have built-in subscribers
        assert len(manager._stats) > 0
        assert "memory_to_rlm" in manager._stats
        # elo_to_debate / calibration_to_agent relocated to
        # aragora.debate.event_subscribers (P4a Batch E4); see
        # tests/debate/test_event_subscribers.py for their coverage.

    def test_register_custom_subscriber(self):
        """Test registering a custom subscriber."""
        manager = CrossSubscriberManager()
        handler = MagicMock()

        manager.register("custom_handler", StreamEventType.DEBATE_START, handler)

        assert "custom_handler" in manager._stats
        assert StreamEventType.DEBATE_START in manager._subscribers

    def test_subscribe_decorator(self):
        """Test subscribe decorator registers handler."""
        manager = CrossSubscriberManager()

        @manager.subscribe(StreamEventType.DEBATE_END)
        def on_debate_end(event):
            pass

        assert "on_debate_end" in manager._stats

    def test_dispatch_calls_handler(self):
        """Test dispatching event calls registered handler."""
        manager = CrossSubscriberManager()
        handler = MagicMock()
        manager.register("test_handler", StreamEventType.DEBATE_START, handler)

        event = make_stream_event(StreamEventType.DEBATE_START)
        manager._dispatch_event(event)

        handler.assert_called_once_with(event)

    def test_dispatch_updates_stats(self):
        """Test dispatching event updates statistics."""
        manager = CrossSubscriberManager()
        handler = MagicMock()
        manager.register("test_handler", StreamEventType.DEBATE_START, handler)

        event = make_stream_event(StreamEventType.DEBATE_START)
        manager._dispatch_event(event)

        stats = manager._stats["test_handler"]
        assert stats.events_processed == 1
        assert stats.last_event_time is not None

    def test_dispatch_handles_errors(self):
        """Test dispatching handles handler errors gracefully."""
        manager = CrossSubscriberManager()

        def failing_handler(event):
            raise ValueError("Test error")

        manager.register("failing", StreamEventType.DEBATE_START, failing_handler)

        event = make_stream_event(StreamEventType.DEBATE_START)
        # Should not raise
        manager._dispatch_event(event)

        stats = manager._stats["failing"]
        assert stats.events_failed == 1

    def test_dispatch_only_matching_events(self):
        """Test dispatch only calls handlers for matching event types."""
        manager = CrossSubscriberManager()
        handler = MagicMock()
        manager.register("test", StreamEventType.DEBATE_START, handler)

        # Dispatch non-matching event
        event = make_stream_event(StreamEventType.DEBATE_END)
        manager._dispatch_event(event)

        handler.assert_not_called()

    def test_required_dispatch_attempts_handler_with_open_circuit(self):
        """Safety-critical dispatch must not suppress an attempt after prior failures."""
        manager = CrossSubscriberManager(failure_threshold=1)
        handler = MagicMock(return_value=True)
        manager.register("required", StreamEventType.ALERT_ESCALATED, handler)
        manager._circuit_breaker.record_failure("required")
        assert manager._circuit_breaker.is_available("required") is False

        event = make_stream_event(StreamEventType.ALERT_ESCALATED)
        manager.dispatch_required(event, "required")

        handler.assert_called_once_with(event)
        assert manager._stats["required"].events_processed == 1


class TestBuiltinHandlers:
    """Test built-in cross-subsystem handlers.

    elo_to_debate / calibration_to_agent relocated to
    ``aragora.debate.event_subscribers`` (P4a Batch E4 relocate-UP); see
    ``tests/debate/test_event_subscribers.py`` for their handler-execution
    coverage.
    """

    def setup_method(self):
        reset_cross_subscriber_manager()

    def test_memory_to_rlm_handler(self):
        """Test memory retrieval handler executes without error."""
        manager = CrossSubscriberManager()

        event = make_stream_event(
            StreamEventType.MEMORY_RETRIEVED,
            data={"tier": "fast", "cache_hit": True},
        )

        # Should not raise
        manager._dispatch_event(event)


class TestSubscriberManagement:
    """Test subscriber enable/disable and stats."""

    def setup_method(self):
        reset_cross_subscriber_manager()

    def test_get_stats(self):
        """Test getting subscriber statistics."""
        manager = CrossSubscriberManager()
        handler = MagicMock()
        manager.register("test", StreamEventType.DEBATE_START, handler)

        # Process an event
        event = make_stream_event(StreamEventType.DEBATE_START)
        manager._dispatch_event(event)

        stats = manager.get_stats()

        assert "test" in stats
        assert stats["test"]["events_processed"] == 1
        assert stats["test"]["enabled"] is True

    def test_enable_disable_subscriber(self):
        """Test enabling and disabling subscribers."""
        manager = CrossSubscriberManager()
        handler = MagicMock()
        manager.register("test", StreamEventType.DEBATE_START, handler)

        assert manager.disable_subscriber("test") is True
        assert manager._stats["test"].enabled is False

        assert manager.enable_subscriber("test") is True
        assert manager._stats["test"].enabled is True

    def test_enable_nonexistent_returns_false(self):
        """Test enabling nonexistent subscriber returns False."""
        manager = CrossSubscriberManager()
        assert manager.enable_subscriber("nonexistent") is False

    def test_reset_stats(self):
        """Test resetting subscriber statistics."""
        manager = CrossSubscriberManager()
        handler = MagicMock()
        manager.register("test", StreamEventType.DEBATE_START, handler)

        # Process events
        for _ in range(5):
            manager._dispatch_event(make_stream_event(StreamEventType.DEBATE_START))

        manager.reset_stats()

        stats = manager._stats["test"]
        assert stats.events_processed == 0
        assert stats.last_event_time is None


class TestEventEmitterConnection:
    """Test connecting to event emitters."""

    def setup_method(self):
        reset_cross_subscriber_manager()

    def test_connect_subscribes_to_emitter(self):
        """Test connect subscribes to event emitter."""
        manager = CrossSubscriberManager()
        mock_emitter = MagicMock()

        manager.connect(mock_emitter)

        mock_emitter.subscribe.assert_called_once()
        assert manager._connected is True

    def test_connect_twice_logs_warning(self):
        """Test connecting twice logs warning."""
        manager = CrossSubscriberManager()
        mock_emitter = MagicMock()

        manager.connect(mock_emitter)
        manager.connect(mock_emitter)

        # Should only subscribe once
        assert mock_emitter.subscribe.call_count == 1

    def test_connected_receives_events(self):
        """Test connected manager receives events."""
        manager = CrossSubscriberManager()
        handler = MagicMock()
        manager.register("test", StreamEventType.DEBATE_START, handler)

        # Simulate emitter behavior
        callback = None

        def mock_subscribe(cb):
            nonlocal callback
            callback = cb

        mock_emitter = MagicMock()
        mock_emitter.subscribe = mock_subscribe

        manager.connect(mock_emitter)

        # Simulate event emission
        event = make_stream_event(StreamEventType.DEBATE_START)
        callback(event)

        handler.assert_called_once_with(event)


class TestGlobalManager:
    """Test global manager instance management."""

    def setup_method(self):
        reset_cross_subscriber_manager()

    def test_get_returns_singleton(self):
        """Test get_cross_subscriber_manager returns singleton."""
        manager1 = get_cross_subscriber_manager()
        manager2 = get_cross_subscriber_manager()
        assert manager1 is manager2

    def test_reset_creates_new_instance(self):
        """Test reset creates new manager instance."""
        manager1 = get_cross_subscriber_manager()
        reset_cross_subscriber_manager()
        manager2 = get_cross_subscriber_manager()
        assert manager1 is not manager2


class TestNewEventTypes:
    """Test new event types added for cross-pollination."""

    def test_memory_stored_event_exists(self):
        """Test MEMORY_STORED event type exists."""
        assert hasattr(StreamEventType, "MEMORY_STORED")
        assert StreamEventType.MEMORY_STORED.value == "memory_stored"

    def test_knowledge_indexed_event_exists(self):
        """Test KNOWLEDGE_INDEXED event type exists."""
        assert hasattr(StreamEventType, "KNOWLEDGE_INDEXED")
        assert StreamEventType.KNOWLEDGE_INDEXED.value == "knowledge_indexed"

    def test_agent_calibration_changed_event_exists(self):
        """Test AGENT_CALIBRATION_CHANGED event type exists."""
        assert hasattr(StreamEventType, "AGENT_CALIBRATION_CHANGED")
        assert StreamEventType.AGENT_CALIBRATION_CHANGED.value == "agent_calibration_changed"

    def test_agent_fallback_triggered_event_exists(self):
        """Test AGENT_FALLBACK_TRIGGERED event type exists."""
        assert hasattr(StreamEventType, "AGENT_FALLBACK_TRIGGERED")
        assert StreamEventType.AGENT_FALLBACK_TRIGGERED.value == "agent_fallback_triggered"

    def test_mound_updated_event_exists(self):
        """Test MOUND_UPDATED event type exists."""
        assert hasattr(StreamEventType, "MOUND_UPDATED")
        assert StreamEventType.MOUND_UPDATED.value == "mound_updated"
