"""Tests for the server-domain (interface-tier) event-subscriber home
(P4a Batch E6).

Covers ``aragora.server.event_subscribers``: the webhook-delivery,
knowledge-staleness-to-debate, and gauntlet-notification reactions relocated
out of infrastructure ``aragora.events`` into this interface home, plus the
self-registration surface (get-or-create accessor, ``register()``).

These reactions are interface-coupled (server facilities or notification
delivery), so ``ServerEventSubscriber`` is wired ONLY
via the interface-superset bootstrap
(``aragora.server.startup.event_subscribers.bootstrap_event_subscribers``),
never the domain-subset one (``aragora.debate.event_subscribers.
bootstrap_debate_event_subscribers``) - see
``tests/events/test_cross_subscriber_registry.py`` for the cross-cutting
golden-name parity/leak-prevention/fail-closed tests.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.events.cross_subscribers import (
    CrossSubscriberManager,
    get_registered_subscribers,
    reset_cross_subscriber_manager,
    reset_registry,
)
from aragora.events.types import StreamEvent, StreamEventType
from aragora.server.event_subscribers import (
    SERVER_EVENT_SUBSCRIBER_HANDLER_NAMES,
    ServerEventSubscriber,
    get_server_event_subscriber,
    register,
)


def make_stream_event(event_type: StreamEventType, data: dict | None = None) -> StreamEvent:
    """Factory for creating test stream events."""
    return StreamEvent(type=event_type, data=data or {}, round=0, agent="test_agent")


@pytest.fixture(autouse=True)
def _clean_registry_and_manager():
    """Isolate each test: empty registry + fresh manager before and after."""
    reset_registry()
    reset_cross_subscriber_manager()
    yield
    reset_registry()
    reset_cross_subscriber_manager()


class TestServerEventSubscriberHandlers:
    """Direct handler-execution tests."""

    def test_gauntlet_notification_sync_fallback_preserves_payload(self):
        subscriber = ServerEventSubscriber()
        event = make_stream_event(
            StreamEventType.GAUNTLET_COMPLETE,
            data={
                "gauntlet_id": "gauntlet-123",
                "verdict": "pass",
                "confidence": 0.91,
                "total_findings": 4,
                "critical_count": 1,
            },
        )

        with patch(
            "aragora.notifications.service.notify_gauntlet_completed",
            new_callable=AsyncMock,
        ) as notify:
            subscriber._handle_gauntlet_complete_to_notification(event)

        notify.assert_awaited_once_with(
            gauntlet_id="gauntlet-123",
            verdict="pass",
            confidence=0.91,
            total_findings=4,
            critical_count=1,
        )

    @pytest.mark.parametrize(
        "error",
        [
            ImportError("missing"),
            RuntimeError("runtime"),
            TypeError("type"),
            ValueError("value"),
            OSError("os"),
        ],
    )
    def test_gauntlet_notification_expected_failures_are_non_fatal(self, error: Exception):
        subscriber = ServerEventSubscriber()
        event = make_stream_event(StreamEventType.GAUNTLET_COMPLETE)

        with patch(
            "aragora.notifications.service.notify_gauntlet_completed",
            new_callable=AsyncMock,
            side_effect=error,
        ):
            subscriber._handle_gauntlet_complete_to_notification(event)

    def test_staleness_to_debate_handler_executes_without_error(self):
        subscriber = ServerEventSubscriber()
        event = make_stream_event(
            StreamEventType.KNOWLEDGE_STALE,
            data={"node_id": "n1", "reason": "source updated"},
        )
        subscriber._handle_staleness_to_debate(event)

    def test_staleness_to_debate_warns_on_active_debate_citation(self):
        subscriber = ServerEventSubscriber()
        event = make_stream_event(
            StreamEventType.KNOWLEDGE_STALE,
            data={"node_id": "stale-node-1", "reason": "source updated"},
        )
        active_debates = {"debate-1": {"cited_knowledge": ["stale-node-1"]}}
        with patch(
            "aragora.server.stream.state_manager.get_active_debates",
            return_value=active_debates,
        ):
            subscriber._handle_staleness_to_debate(event)

    def test_webhook_delivery_handler_executes_without_error(self):
        subscriber = ServerEventSubscriber()
        event = make_stream_event(
            StreamEventType.MEMORY_STORED,
            data={"content": "test"},
        )
        subscriber._handle_webhook_delivery(event)

    def test_webhook_delivery_dispatches_to_matching_webhooks(self):
        subscriber = ServerEventSubscriber()
        event = make_stream_event(
            StreamEventType.MEMORY_STORED,
            data={"content": "test"},
        )
        mock_webhook = MagicMock(id="wh1")
        mock_store = MagicMock()
        mock_store.get_for_event.return_value = [mock_webhook]
        mock_result = MagicMock(success=True)

        with (
            patch(
                "aragora.server.handlers.webhook_management.get_webhook_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.events.dispatcher.dispatch_webhook_with_retry",
                return_value=mock_result,
            ) as mock_dispatch,
        ):
            subscriber._handle_webhook_delivery(event)

        mock_dispatch.assert_called_once()
        assert mock_dispatch.call_args[0][0] is mock_webhook


class TestServerEventSubscriberRegistration:
    """Registration + self-registration surface tests."""

    def test_handler_names_frozenset(self):
        assert SERVER_EVENT_SUBSCRIBER_HANDLER_NAMES == frozenset(
            {
                "gauntlet_to_notification",
                "staleness_to_debate",
                "webhook_memory_stored",
                "webhook_memory_retrieved",
                "webhook_agent_elo_updated",
                "webhook_knowledge_indexed",
                "webhook_knowledge_queried",
                "webhook_mound_updated",
                "webhook_calibration_update",
                "webhook_evidence_found",
            }
        )

    def test_register_wires_all_handlers_into_manager(self):
        manager = CrossSubscriberManager()
        subscriber = ServerEventSubscriber()

        subscriber.register(manager)

        registered = set(manager.get_stats())
        assert SERVER_EVENT_SUBSCRIBER_HANDLER_NAMES <= registered

    def test_register_dispatches_staleness_to_debate_through_manager(self):
        manager = CrossSubscriberManager()
        ServerEventSubscriber().register(manager)

        manager._dispatch_event(
            make_stream_event(
                StreamEventType.KNOWLEDGE_STALE,
                data={"node_id": "n1", "reason": "x"},
            )
        )

        stats = manager.get_stats()
        assert stats["staleness_to_debate"]["events_processed"] == 1

    def test_register_dispatches_webhook_delivery_through_manager(self):
        manager = CrossSubscriberManager()
        ServerEventSubscriber().register(manager)

        manager._dispatch_event(make_stream_event(StreamEventType.EVIDENCE_FOUND, data={}))

        stats = manager.get_stats()
        assert stats["webhook_evidence_found"]["events_processed"] == 1

    @pytest.mark.asyncio
    async def test_superset_bootstrap_registers_gauntlet_notification_exactly_once(self):
        from aragora.server.startup.event_subscribers import bootstrap_event_subscribers

        first = bootstrap_event_subscribers()
        second = bootstrap_event_subscribers()
        assert first is second

        registered = [
            name
            for name, _handler in first._subscribers[StreamEventType.GAUNTLET_COMPLETE]
            if name == "gauntlet_to_notification"
        ]
        assert registered == ["gauntlet_to_notification"]

        event = make_stream_event(
            StreamEventType.GAUNTLET_COMPLETE,
            data={
                "gauntlet_id": "gauntlet-456",
                "verdict": "review",
                "confidence": 0.75,
                "total_findings": 6,
                "critical_count": 2,
            },
        )
        with patch(
            "aragora.notifications.service.notify_gauntlet_completed",
            new_callable=AsyncMock,
        ) as notify:
            first._dispatch_event(event)
            await asyncio.sleep(0)

        notify.assert_awaited_once_with(
            gauntlet_id="gauntlet-456",
            verdict="review",
            confidence=0.75,
            total_findings=6,
            critical_count=2,
        )

    def test_get_server_event_subscriber_returns_singleton(self):
        first = get_server_event_subscriber()
        second = get_server_event_subscriber()
        assert first is second
        assert get_registered_subscribers()["server"] is first

    def test_register_function_is_idempotent(self):
        register()
        first = get_registered_subscribers()["server"]
        register()
        second = get_registered_subscribers()["server"]
        assert first is second

    def test_lightweight_bootstrap_registers_webhook_store_provider(self):
        """Durable webhook storage can be wired without subscriber imports."""
        from aragora.server.startup.event_subscribers import register_webhook_store

        with (
            patch("aragora.events.dispatcher.register_webhook_store_provider") as register_provider,
            patch(
                "aragora.storage.webhook_config_store.get_webhook_config_store"
            ) as get_webhook_config_store,
        ):
            register_webhook_store()

        register_provider.assert_called_once_with(get_webhook_config_store)

    def test_superset_bootstrap_uses_lightweight_webhook_store_registration(self):
        """Direct subscriber bootstrap must include durable store wiring."""
        from aragora.server.startup.event_subscribers import bootstrap_event_subscribers

        with patch(
            "aragora.server.startup.event_subscribers.register_webhook_store"
        ) as register_store:
            bootstrap_event_subscribers()

        register_store.assert_called_once_with()

    def test_superset_bootstrap_registers_webhook_store_provider(self):
        """Server composition wires durable webhook storage into events."""
        from aragora.server.startup.event_subscribers import bootstrap_event_subscribers

        with (
            patch("aragora.events.dispatcher.register_webhook_store_provider") as register_provider,
            patch(
                "aragora.storage.webhook_config_store.get_webhook_config_store"
            ) as get_webhook_config_store,
        ):
            bootstrap_event_subscribers()

        register_provider.assert_called_once_with(get_webhook_config_store)


class TestLegacyDelegatingSitesRemoved:
    """Structural regression guard: relocated handler methods are gone
    entirely from their old infrastructure homes, not merely
    unregistered (docs/architecture/P4A_EVENTS_QUEUE_INVERSION.md §5.3).

    P4a Batch E7b dissolved ``BasicHandlersMixin``/``CultureHandlersMixin``
    into ``CrossSubscriberManager`` directly, so the guard now targets the
    manager class itself.
    """

    def test_cross_subscriber_manager_has_no_webhook_delivery(self):
        assert not hasattr(CrossSubscriberManager, "_handle_webhook_delivery")

    def test_cross_subscriber_manager_has_no_staleness_to_debate(self):
        assert not hasattr(CrossSubscriberManager, "_handle_staleness_to_debate")

    def test_cross_subscriber_manager_has_no_gauntlet_notification_delivery(self):
        assert not hasattr(
            CrossSubscriberManager,
            "_handle_gauntlet_complete_to_notification",
        )

    def test_manager_no_longer_registers_relocated_names_directly(self):
        """A bare, non-bootstrapped manager must not carry the relocated
        names: only the interface-superset bootstrap wires them in now."""
        manager = CrossSubscriberManager()
        registered = set(manager.get_stats())
        assert not (SERVER_EVENT_SUBSCRIBER_HANDLER_NAMES & registered)
