"""
Tests for resilient notification delivery.

Covers circuit breaker integration, retry queue wiring, and
the process_retry_queue drain loop in NotificationService.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationResult,
    SlackConfig,
)
from aragora.notifications.retry_queue import NotificationRetryQueue, RetryEntry
from aragora.notifications.service import NotificationService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_notification(**kwargs):
    defaults = dict(title="Test Alert", message="Something happened", severity="warning")
    defaults.update(kwargs)
    return Notification(**defaults)


def _success_result(channel, recipient, notification_id="n-1"):
    return NotificationResult(
        success=True,
        channel=channel,
        recipient=recipient,
        notification_id=notification_id,
    )


def _failure_result(channel, recipient, notification_id="n-1", error="timeout"):
    return NotificationResult(
        success=False,
        channel=channel,
        recipient=recipient,
        notification_id=notification_id,
        error=error,
    )


# ---------------------------------------------------------------------------
# Circuit Breaker Integration
# ---------------------------------------------------------------------------


class TestCircuitBreakerIntegration:
    """Test that circuit breakers protect notification channels."""

    def test_service_creates_circuit_breakers_by_default(self):
        svc = NotificationService(
            slack_config=SlackConfig(webhook_url="https://hooks.slack.com/test"),
        )
        states = svc.get_circuit_breaker_states()
        # Should have breakers for all registered channels
        assert "slack" in states
        assert "email" in states
        assert "webhook" in states

    def test_service_skips_circuit_breakers_when_disabled(self):
        svc = NotificationService(enable_circuit_breakers=False)
        assert svc.get_circuit_breaker_states() == {}

    @pytest.mark.asyncio
    async def test_open_circuit_skips_channel(self):
        """When a channel's circuit breaker is open, deliveries are skipped."""
        svc = NotificationService(
            slack_config=SlackConfig(webhook_url="https://hooks.slack.com/test"),
            enable_circuit_breakers=True,
        )

        # Force the Slack circuit breaker open
        cb = svc._circuit_breakers[NotificationChannel.SLACK]
        cb.is_open = True

        # Mock provider to track if send is called
        mock_provider = AsyncMock()
        mock_provider.is_configured.return_value = True
        mock_provider.channel = NotificationChannel.SLACK
        svc.providers[NotificationChannel.SLACK] = mock_provider

        notification = _make_notification()
        results = await svc.notify(
            notification,
            channels=[NotificationChannel.SLACK],
            recipients={NotificationChannel.SLACK: ["#general"]},
        )

        # Provider should NOT have been called
        mock_provider.send.assert_not_called()
        assert results == []

    @pytest.mark.asyncio
    async def test_successful_delivery_records_success(self):
        """Successful send updates the circuit breaker."""
        svc = NotificationService(enable_circuit_breakers=True)
        cb = svc._circuit_breakers[NotificationChannel.SLACK]

        mock_provider = AsyncMock()
        mock_provider.is_configured.return_value = True
        mock_provider.channel = NotificationChannel.SLACK
        mock_provider.send.return_value = _success_result(NotificationChannel.SLACK, "#alerts")
        svc.providers[NotificationChannel.SLACK] = mock_provider

        notification = _make_notification()
        results = await svc.notify(
            notification,
            channels=[NotificationChannel.SLACK],
            recipients={NotificationChannel.SLACK: ["#alerts"]},
        )

        assert len(results) == 1
        assert results[0].success
        # Circuit breaker should still be closed
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_failures_eventually_open_circuit(self):
        """Repeated failures trip the circuit breaker."""
        svc = NotificationService(enable_circuit_breakers=True)
        cb = svc._circuit_breakers[NotificationChannel.SLACK]
        # Lower threshold for test
        cb.failure_threshold = 3

        mock_provider = AsyncMock()
        mock_provider.is_configured.return_value = True
        mock_provider.channel = NotificationChannel.SLACK
        mock_provider.send.return_value = _failure_result(NotificationChannel.SLACK, "#alerts")
        svc.providers[NotificationChannel.SLACK] = mock_provider

        notification = _make_notification()

        for _ in range(3):
            await svc.notify(
                notification,
                channels=[NotificationChannel.SLACK],
                recipients={NotificationChannel.SLACK: ["#alerts"]},
            )

        assert cb.state == "open"


# ---------------------------------------------------------------------------
# Retry Queue Integration
# ---------------------------------------------------------------------------


class TestRetryQueueIntegration:
    """Test that failed deliveries are enqueued and retried."""

    @pytest.mark.asyncio
    async def test_failed_delivery_enqueues_retry(self):
        """A failed send automatically creates a retry entry."""
        queue = NotificationRetryQueue(max_size=100)
        svc = NotificationService(
            retry_queue=queue,
            enable_circuit_breakers=False,
        )

        mock_provider = AsyncMock()
        mock_provider.is_configured.return_value = True
        mock_provider.channel = NotificationChannel.SLACK
        mock_provider.send.return_value = _failure_result(
            NotificationChannel.SLACK,
            "#alerts",
            error="connection refused",
        )
        svc.providers[NotificationChannel.SLACK] = mock_provider

        notification = _make_notification()
        await svc.notify(
            notification,
            channels=[NotificationChannel.SLACK],
            recipients={NotificationChannel.SLACK: ["#alerts"]},
        )

        assert queue.pending_count() == 1
        pending = queue.get_pending(1)
        assert pending[0].channel == "slack"
        assert pending[0].recipient == "#alerts"
        assert pending[0].notification_id == notification.id

    @pytest.mark.asyncio
    async def test_successful_delivery_does_not_enqueue(self):
        """A successful send does NOT create a retry entry."""
        queue = NotificationRetryQueue(max_size=100)
        svc = NotificationService(
            retry_queue=queue,
            enable_circuit_breakers=False,
        )

        mock_provider = AsyncMock()
        mock_provider.is_configured.return_value = True
        mock_provider.channel = NotificationChannel.SLACK
        mock_provider.send.return_value = _success_result(
            NotificationChannel.SLACK,
            "#alerts",
        )
        svc.providers[NotificationChannel.SLACK] = mock_provider

        await svc.notify(
            _make_notification(),
            channels=[NotificationChannel.SLACK],
            recipients={NotificationChannel.SLACK: ["#alerts"]},
        )

        assert queue.pending_count() == 0

    @pytest.mark.asyncio
    async def test_process_retry_queue_succeeds(self):
        """process_retry_queue retries and marks successful."""
        queue = NotificationRetryQueue(max_size=100)
        svc = NotificationService(
            retry_queue=queue,
            enable_circuit_breakers=False,
        )

        # Pre-load a retry entry
        entry = RetryEntry(
            id="r-1",
            notification_id="n-100",
            channel="slack",
            recipient="#alerts",
            payload={"id": "n-100", "title": "Retry Me", "message": "Please"},
        )
        queue.enqueue(entry)

        # Provider now succeeds
        mock_provider = AsyncMock()
        mock_provider.is_configured.return_value = True
        mock_provider.channel = NotificationChannel.SLACK
        mock_provider.send.return_value = _success_result(
            NotificationChannel.SLACK,
            "#alerts",
            notification_id="n-100",
        )
        svc.providers[NotificationChannel.SLACK] = mock_provider

        results = await svc.process_retry_queue()

        assert len(results) == 1
        assert results[0].success
        assert queue.pending_count() == 0

    @pytest.mark.asyncio
    async def test_process_retry_queue_failure_requeues(self):
        """process_retry_queue re-enqueues on failure with backoff."""
        queue = NotificationRetryQueue(max_size=100)
        svc = NotificationService(
            retry_queue=queue,
            enable_circuit_breakers=False,
        )

        entry = RetryEntry(
            id="r-2",
            notification_id="n-200",
            channel="slack",
            recipient="#alerts",
            payload={"id": "n-200", "title": "Fail Again", "message": "Oops"},
            max_attempts=5,
        )
        queue.enqueue(entry)

        # Provider still fails
        mock_provider = AsyncMock()
        mock_provider.is_configured.return_value = True
        mock_provider.channel = NotificationChannel.SLACK
        mock_provider.send.return_value = _failure_result(
            NotificationChannel.SLACK,
            "#alerts",
            notification_id="n-200",
        )
        svc.providers[NotificationChannel.SLACK] = mock_provider

        results = await svc.process_retry_queue()

        assert len(results) == 1
        assert not results[0].success
        # Entry re-enqueued (attempt incremented, next_retry_at in future)
        assert queue.pending_count() == 1
        pending = queue.get_pending(1)
        assert pending[0].attempt == 1
        assert pending[0].next_retry_at > time.time()

    @pytest.mark.asyncio
    async def test_process_retry_queue_respects_circuit_breaker(self):
        """Retries skip channels with open circuit breakers."""
        queue = NotificationRetryQueue(max_size=100)
        svc = NotificationService(
            retry_queue=queue,
            enable_circuit_breakers=True,
        )

        # Open the Slack circuit breaker
        svc._circuit_breakers[NotificationChannel.SLACK].is_open = True

        entry = RetryEntry(
            id="r-3",
            notification_id="n-300",
            channel="slack",
            recipient="#alerts",
            payload={"id": "n-300", "title": "Blocked", "message": "By CB"},
        )
        queue.enqueue(entry)

        mock_provider = AsyncMock()
        mock_provider.is_configured.return_value = True
        mock_provider.channel = NotificationChannel.SLACK
        svc.providers[NotificationChannel.SLACK] = mock_provider

        results = await svc.process_retry_queue()

        # Provider should not have been called
        mock_provider.send.assert_not_called()
        assert results == []
        # Entry should be re-enqueued without consuming an attempt
        assert queue.pending_count() == 1
        pending = queue.get_pending(1)
        assert pending[0].attempt == 0  # Not incremented

    @pytest.mark.asyncio
    async def test_retry_queue_accessible_via_property(self):
        """The retry queue is accessible for inspection."""
        queue = NotificationRetryQueue(max_size=50)
        svc = NotificationService(retry_queue=queue, enable_circuit_breakers=False)
        assert svc.retry_queue is queue

    @pytest.mark.asyncio
    async def test_multiple_failures_across_channels_enqueue_separately(self):
        """Failures on different channels create separate retry entries."""
        queue = NotificationRetryQueue(max_size=100)
        svc = NotificationService(
            retry_queue=queue,
            enable_circuit_breakers=False,
        )

        for channel_enum in (NotificationChannel.SLACK, NotificationChannel.EMAIL):
            mock_provider = AsyncMock()
            mock_provider.is_configured.return_value = True
            mock_provider.channel = channel_enum
            mock_provider.send.return_value = _failure_result(
                channel_enum,
                "target",
                error="down",
            )
            svc.providers[channel_enum] = mock_provider

        await svc.notify(
            _make_notification(),
            channels=[NotificationChannel.SLACK, NotificationChannel.EMAIL],
            recipients={
                NotificationChannel.SLACK: ["#general"],
                NotificationChannel.EMAIL: ["admin@example.com"],
            },
        )

        assert queue.pending_count() == 2
        channels = {e.channel for e in queue.get_pending(10)}
        assert channels == {"slack", "email"}


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases for resilient delivery."""

    @pytest.mark.asyncio
    async def test_retry_entry_with_unknown_channel_skipped(self):
        """Retry entries with an invalid channel value are skipped."""
        queue = NotificationRetryQueue(max_size=100)
        svc = NotificationService(
            retry_queue=queue,
            enable_circuit_breakers=False,
        )

        entry = RetryEntry(
            id="r-bad",
            notification_id="n-bad",
            channel="carrier_pigeon",
            recipient="pigeon-1",
            payload={"id": "n-bad", "title": "Coo", "message": "Coo coo"},
        )
        queue.enqueue(entry)

        results = await svc.process_retry_queue()
        assert results == []
        # Entry consumed (not re-enqueued)
        assert queue.pending_count() == 0

    @pytest.mark.asyncio
    async def test_retry_preserves_notification_payload(self):
        """Retry reconstructs notification from stored payload."""
        queue = NotificationRetryQueue(max_size=100)
        svc = NotificationService(
            retry_queue=queue,
            enable_circuit_breakers=False,
        )

        entry = RetryEntry(
            id="r-payload",
            notification_id="n-payload",
            channel="slack",
            recipient="#ops",
            payload={
                "id": "n-payload",
                "title": "Important",
                "message": "Details here",
                "severity": "critical",
            },
        )
        queue.enqueue(entry)

        captured_notification = None

        async def capture_send(notification, recipient):
            nonlocal captured_notification
            captured_notification = notification
            return _success_result(NotificationChannel.SLACK, recipient)

        mock_provider = AsyncMock(side_effect=capture_send)
        mock_provider.is_configured.return_value = True
        mock_provider.channel = NotificationChannel.SLACK
        mock_provider.send = capture_send
        svc.providers[NotificationChannel.SLACK] = mock_provider

        await svc.process_retry_queue()

        assert captured_notification is not None
        assert captured_notification.title == "Important"
        assert captured_notification.message == "Details here"
        assert captured_notification.severity == "critical"
