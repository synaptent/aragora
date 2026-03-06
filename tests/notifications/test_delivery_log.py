"""
Tests for persistent delivery tracking (DeliveryLogEntry + DeliveryLogStore).

Covers:
- Log + retrieve round-trip
- get_by_notification filtering
- get_analytics aggregation (success_count, failure_count, avg_latency_ms, by_channel)
- get_recent ordering and limit
- Provider integration (mock provider, verify delivery log entry created on send)
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from aragora.notifications.delivery_log import (
    DeliveryLogEntry,
    InMemoryDeliveryLogStore,
    get_delivery_log_store,
    set_delivery_log_store,
)
from aragora.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationResult,
    SlackConfig,
)
from aragora.notifications.providers import SlackProvider, _log_delivery


# ============================================================================
# DeliveryLogEntry dataclass
# ============================================================================


class TestDeliveryLogEntry:
    """Basic tests for the DeliveryLogEntry dataclass."""

    def test_defaults(self):
        entry = DeliveryLogEntry()
        assert entry.id  # UUID generated
        assert entry.notification_id == ""
        assert entry.channel == ""
        assert entry.status == "sent"
        assert entry.retry_count == 0
        assert entry.latency_ms == 0.0
        assert entry.timestamp > 0

    def test_custom_fields(self):
        entry = DeliveryLogEntry(
            id="entry-1",
            notification_id="n-1",
            channel="slack",
            recipient="#general",
            status="delivered",
            external_id="msg-abc",
            error="",
            retry_count=0,
            latency_ms=42.5,
        )
        assert entry.id == "entry-1"
        assert entry.notification_id == "n-1"
        assert entry.channel == "slack"
        assert entry.recipient == "#general"
        assert entry.status == "delivered"
        assert entry.external_id == "msg-abc"
        assert entry.latency_ms == 42.5


# ============================================================================
# InMemoryDeliveryLogStore
# ============================================================================


class TestInMemoryDeliveryLogStore:
    """Tests for the in-memory implementation of DeliveryLogStore."""

    @pytest.fixture
    def store(self):
        return InMemoryDeliveryLogStore()

    @pytest.mark.asyncio
    async def test_log_and_get_by_notification(self, store):
        """Log entries, then retrieve by notification_id."""
        e1 = DeliveryLogEntry(notification_id="n-1", channel="slack", status="delivered")
        e2 = DeliveryLogEntry(
            notification_id="n-1", channel="email", status="failed", error="timeout"
        )
        e3 = DeliveryLogEntry(notification_id="n-2", channel="slack", status="delivered")

        await store.log(e1)
        await store.log(e2)
        await store.log(e3)

        results = await store.get_by_notification("n-1")
        assert len(results) == 2
        assert {r.channel for r in results} == {"slack", "email"}

        results_n2 = await store.get_by_notification("n-2")
        assert len(results_n2) == 1
        assert results_n2[0].channel == "slack"

    @pytest.mark.asyncio
    async def test_get_by_notification_empty(self, store):
        """No entries for unknown notification_id."""
        results = await store.get_by_notification("nonexistent")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_analytics_empty(self, store):
        """Analytics on empty store returns zeroes."""
        analytics = await store.get_analytics()
        assert analytics["success_count"] == 0
        assert analytics["failure_count"] == 0
        assert analytics["avg_latency_ms"] == 0.0
        assert analytics["by_channel"] == {}

    @pytest.mark.asyncio
    async def test_get_analytics_aggregation(self, store):
        """Analytics correctly aggregates success/failure counts and latency."""
        await store.log(
            DeliveryLogEntry(channel="slack", status="delivered", latency_ms=100.0, timestamp=10.0)
        )
        await store.log(
            DeliveryLogEntry(
                channel="slack", status="failed", error="timeout", latency_ms=200.0, timestamp=20.0
            )
        )
        await store.log(
            DeliveryLogEntry(channel="email", status="sent", latency_ms=50.0, timestamp=30.0)
        )

        analytics = await store.get_analytics()
        assert analytics["success_count"] == 2  # delivered + sent
        assert analytics["failure_count"] == 1  # failed
        assert analytics["avg_latency_ms"] == pytest.approx((100.0 + 200.0 + 50.0) / 3)
        assert analytics["by_channel"]["slack"] == {"success": 1, "failure": 1}
        assert analytics["by_channel"]["email"] == {"success": 1, "failure": 0}

    @pytest.mark.asyncio
    async def test_get_analytics_since_filter(self, store):
        """Analytics respects the 'since' timestamp filter."""
        await store.log(
            DeliveryLogEntry(channel="slack", status="delivered", latency_ms=10.0, timestamp=100.0)
        )
        await store.log(
            DeliveryLogEntry(channel="slack", status="delivered", latency_ms=20.0, timestamp=200.0)
        )

        analytics = await store.get_analytics(since=150.0)
        assert analytics["success_count"] == 1
        assert analytics["avg_latency_ms"] == 20.0

    @pytest.mark.asyncio
    async def test_get_recent_ordering(self, store):
        """get_recent returns entries newest-first."""
        for i in range(5):
            await store.log(
                DeliveryLogEntry(
                    id=f"e-{i}",
                    channel="slack",
                    status="delivered",
                    timestamp=float(i),
                )
            )

        recent = await store.get_recent(limit=3)
        assert len(recent) == 3
        assert [r.id for r in recent] == ["e-4", "e-3", "e-2"]

    @pytest.mark.asyncio
    async def test_get_recent_fewer_than_limit(self, store):
        """get_recent with fewer entries than limit returns all entries."""
        await store.log(DeliveryLogEntry(id="only-one", channel="email", status="sent"))
        recent = await store.get_recent(limit=50)
        assert len(recent) == 1
        assert recent[0].id == "only-one"

    @pytest.mark.asyncio
    async def test_max_entries_eviction(self):
        """Store evicts oldest entries when max_entries is exceeded."""
        store = InMemoryDeliveryLogStore(max_entries=3)
        for i in range(5):
            await store.log(DeliveryLogEntry(id=f"e-{i}", channel="slack", status="sent"))

        recent = await store.get_recent(limit=10)
        assert len(recent) == 3
        assert {r.id for r in recent} == {"e-2", "e-3", "e-4"}


# ============================================================================
# Provider integration
# ============================================================================


class TestProviderDeliveryLogging:
    """Verify that providers log delivery entries after send."""

    @pytest.fixture(autouse=True)
    def _fresh_store(self):
        """Install a fresh in-memory store for each test."""
        store = InMemoryDeliveryLogStore()
        set_delivery_log_store(store)
        yield store
        # Reset global to None so other tests get a fresh default
        set_delivery_log_store(InMemoryDeliveryLogStore())

    @pytest.mark.asyncio
    async def test_slack_success_logs_delivery(self, _fresh_store):
        """SlackProvider logs a 'delivered' entry on successful send."""
        config = SlackConfig(webhook_url="https://hooks.slack.com/test")
        provider = SlackProvider(config)

        notification = Notification(title="Test", message="Hello")

        # Mock the actual HTTP call
        with patch.object(provider, "_send_webhook", new_callable=AsyncMock):
            result = await provider.send(notification, "#general")

        assert result.success is True

        entries = await _fresh_store.get_by_notification(notification.id)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.channel == "slack"
        assert entry.recipient == "#general"
        assert entry.status == "delivered"
        assert entry.latency_ms > 0

    @pytest.mark.asyncio
    async def test_slack_failure_logs_delivery(self, _fresh_store):
        """SlackProvider logs a 'failed' entry on send failure."""
        config = SlackConfig(webhook_url="https://hooks.slack.com/test")
        provider = SlackProvider(config)

        notification = Notification(title="Test", message="Hello")

        with patch.object(
            provider,
            "_send_webhook",
            new_callable=AsyncMock,
            side_effect=ConnectionError("refused"),
        ):
            result = await provider.send(notification, "#general")

        assert result.success is False

        entries = await _fresh_store.get_by_notification(notification.id)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.channel == "slack"
        assert entry.status == "failed"
        assert entry.error == "Slack notification delivery failed"

    @pytest.mark.asyncio
    async def test_slack_not_configured_no_log(self, _fresh_store):
        """SlackProvider with no config does not log (early return before send)."""
        config = SlackConfig()  # no webhook_url, no bot_token
        provider = SlackProvider(config)
        notification = Notification(title="Test", message="Hello")

        result = await provider.send(notification, "#general")
        assert result.success is False

        # Not-configured is an early return, delivery logging only covers actual
        # attempts.  Verify we do NOT log in this case.
        entries = await _fresh_store.get_by_notification(notification.id)
        assert len(entries) == 0


# ============================================================================
# _log_delivery helper
# ============================================================================


class TestLogDeliveryHelper:
    """Direct tests for the _log_delivery helper function."""

    @pytest.fixture(autouse=True)
    def _fresh_store(self):
        store = InMemoryDeliveryLogStore()
        set_delivery_log_store(store)
        yield store
        set_delivery_log_store(InMemoryDeliveryLogStore())

    @pytest.mark.asyncio
    async def test_log_delivery_creates_entry(self, _fresh_store):
        notification = Notification(title="T", message="M")
        result = NotificationResult(
            success=True,
            channel=NotificationChannel.EMAIL,
            recipient="user@example.com",
            notification_id=notification.id,
            external_id="ext-123",
        )

        await _log_delivery(notification, result, latency_seconds=0.05)

        entries = await _fresh_store.get_by_notification(notification.id)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.channel == "email"
        assert entry.recipient == "user@example.com"
        assert entry.status == "delivered"
        assert entry.external_id == "ext-123"
        assert entry.latency_ms == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_log_delivery_failure_entry(self, _fresh_store):
        notification = Notification(title="T", message="M")
        result = NotificationResult(
            success=False,
            channel=NotificationChannel.WEBHOOK,
            recipient="ep-1",
            notification_id=notification.id,
            error="timeout",
        )

        await _log_delivery(notification, result, latency_seconds=1.0)

        entries = await _fresh_store.get_by_notification(notification.id)
        assert len(entries) == 1
        assert entries[0].status == "failed"
        assert entries[0].error == "timeout"
        assert entries[0].latency_ms == pytest.approx(1000.0)


# ============================================================================
# Singleton management
# ============================================================================


class TestSingletonManagement:
    """Tests for get_delivery_log_store / set_delivery_log_store."""

    def test_get_returns_same_instance(self):
        """get_delivery_log_store returns the same object on repeated calls."""
        # Reset to force fresh creation
        import aragora.notifications.delivery_log as mod

        mod._delivery_log_store = None
        s1 = get_delivery_log_store()
        s2 = get_delivery_log_store()
        assert s1 is s2

    def test_set_replaces_store(self):
        custom = InMemoryDeliveryLogStore(max_entries=5)
        set_delivery_log_store(custom)
        assert get_delivery_log_store() is custom
