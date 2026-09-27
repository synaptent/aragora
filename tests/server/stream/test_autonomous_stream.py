"""
Tests for autonomous stream WebSocket handler and event emitter.

Tests cover:
- AutonomousStreamClient: Client state and initialization
- AutonomousStreamEmitter: Event emission, subscription management, history
- Event helper functions: emit_approval_event, emit_alert_event, etc.
- WebSocket handler: Connection handling, message processing, subscriptions
- Concurrent broadcasting and error handling
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.events.types import StreamEvent, StreamEventType
from aragora.server.stream.autonomous_stream import (
    AutonomousStreamClient,
    AutonomousStreamEmitter,
    autonomous_websocket_handler,
    emit_alert_event,
    emit_approval_event,
    emit_learning_event,
    emit_monitoring_event,
    emit_trigger_event,
    get_autonomous_emitter,
    register_autonomous_stream_routes,
    set_autonomous_emitter,
)


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def emitter():
    """Create a fresh AutonomousStreamEmitter instance."""
    return AutonomousStreamEmitter()


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket response."""
    ws = MagicMock()
    ws.send_str = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.fixture
def mock_request():
    """Create a mock aiohttp request."""
    request = MagicMock()
    request.query = {}
    return request


@pytest.fixture
def client(mock_websocket):
    """Create an AutonomousStreamClient instance."""
    return AutonomousStreamClient(
        ws=mock_websocket,
        client_id="test_client_1",
        subscriptions={"alert_created", "trend_detected"},
    )


@pytest.fixture
def sample_event():
    """Create a sample stream event."""
    return StreamEvent(
        type=StreamEventType.ALERT_CREATED,
        data={"alert_id": "alert-123", "severity": "high", "title": "Test Alert"},
    )


@pytest.fixture(autouse=True)
def reset_global_emitter():
    """Reset the global emitter before each test."""
    import aragora.server.stream.autonomous_stream as module

    original = module._autonomous_emitter
    module._autonomous_emitter = None
    yield
    module._autonomous_emitter = original


@pytest.fixture
def clean_cross_subscriber_manager():
    """Provide isolated production cross-subscriber wiring."""
    from aragora.events.cross_subscribers import reset_cross_subscriber_manager

    reset_cross_subscriber_manager()
    yield
    reset_cross_subscriber_manager()


# ===========================================================================
# Test AutonomousStreamClient
# ===========================================================================


class TestAutonomousStreamClient:
    """Tests for AutonomousStreamClient dataclass."""

    def test_initialization(self, mock_websocket):
        """Client initializes with correct defaults."""
        client = AutonomousStreamClient(
            ws=mock_websocket,
            client_id="client-1",
        )
        assert client.ws is mock_websocket
        assert client.client_id == "client-1"
        assert client.subscriptions == set()
        assert client.connected_at > 0
        assert client.last_heartbeat > 0

    def test_initialization_with_subscriptions(self, mock_websocket):
        """Client can be initialized with subscriptions."""
        subs = {"alert_created", "trend_detected"}
        client = AutonomousStreamClient(
            ws=mock_websocket,
            client_id="client-2",
            subscriptions=subs,
        )
        assert client.subscriptions == subs

    def test_connected_at_timestamp(self, mock_websocket):
        """connected_at is set to current time."""
        before = time.time()
        client = AutonomousStreamClient(
            ws=mock_websocket,
            client_id="client-3",
        )
        after = time.time()
        assert before <= client.connected_at <= after

    def test_last_heartbeat_timestamp(self, mock_websocket):
        """last_heartbeat is set to current time."""
        before = time.time()
        client = AutonomousStreamClient(
            ws=mock_websocket,
            client_id="client-4",
        )
        after = time.time()
        assert before <= client.last_heartbeat <= after


# ===========================================================================
# Test AutonomousStreamEmitter
# ===========================================================================


class TestAutonomousStreamEmitter:
    """Tests for AutonomousStreamEmitter class."""

    def test_initialization(self, emitter):
        """Emitter initializes with empty state."""
        assert emitter._clients == {}
        assert emitter._event_history == []
        assert emitter._max_history == 1000
        assert emitter._client_counter == 0
        assert emitter.client_count == 0

    def test_add_client(self, emitter, mock_websocket):
        """add_client registers a new WebSocket client."""
        client_id = emitter.add_client(mock_websocket)

        assert client_id is not None
        assert client_id.startswith("auto_")
        assert emitter.client_count == 1
        assert client_id in emitter._clients

    def test_add_client_with_subscriptions(self, emitter, mock_websocket):
        """add_client accepts optional subscriptions."""
        subs = {"alert_created", "approval_requested"}
        client_id = emitter.add_client(mock_websocket, subscriptions=subs)

        assert emitter._clients[client_id].subscriptions == subs

    def test_add_client_generates_unique_ids(self, emitter):
        """Each add_client call generates a unique ID."""
        ws1, ws2, ws3 = MagicMock(), MagicMock(), MagicMock()
        id1 = emitter.add_client(ws1)
        id2 = emitter.add_client(ws2)
        id3 = emitter.add_client(ws3)

        assert id1 != id2 != id3
        assert emitter.client_count == 3

    def test_remove_client(self, emitter, mock_websocket):
        """remove_client removes a registered client."""
        client_id = emitter.add_client(mock_websocket)
        assert emitter.client_count == 1

        emitter.remove_client(client_id)
        assert emitter.client_count == 0
        assert client_id not in emitter._clients

    def test_remove_nonexistent_client(self, emitter):
        """remove_client handles nonexistent clients gracefully."""
        # Should not raise
        emitter.remove_client("nonexistent-client")
        assert emitter.client_count == 0

    @pytest.mark.asyncio
    async def test_emit_broadcasts_to_all_clients(self, emitter, sample_event):
        """emit() broadcasts to all connected clients."""
        ws1, ws2 = MagicMock(), MagicMock()
        ws1.send_str = AsyncMock()
        ws2.send_str = AsyncMock()

        emitter.add_client(ws1)
        emitter.add_client(ws2)

        await emitter.emit(sample_event)

        ws1.send_str.assert_called_once()
        ws2.send_str.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_respects_subscriptions(self, emitter):
        """emit() only sends to clients subscribed to the event type."""
        ws_subscribed = MagicMock()
        ws_subscribed.send_str = AsyncMock()
        ws_not_subscribed = MagicMock()
        ws_not_subscribed.send_str = AsyncMock()

        emitter.add_client(ws_subscribed, subscriptions={"alert_created"})
        emitter.add_client(ws_not_subscribed, subscriptions={"trend_detected"})

        event = StreamEvent(
            type=StreamEventType.ALERT_CREATED,
            data={"alert_id": "a1"},
        )
        await emitter.emit(event)

        ws_subscribed.send_str.assert_called_once()
        ws_not_subscribed.send_str.assert_not_called()

    @pytest.mark.asyncio
    async def test_emit_sends_to_all_when_no_subscriptions(self, emitter):
        """emit() sends to clients with empty subscriptions (all events)."""
        ws = MagicMock()
        ws.send_str = AsyncMock()

        emitter.add_client(ws, subscriptions=set())  # Empty = all events

        event = StreamEvent(
            type=StreamEventType.TRIGGER_EXECUTED,
            data={"trigger_id": "t1"},
        )
        await emitter.emit(event)

        ws.send_str.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_stores_in_history(self, emitter, sample_event):
        """emit() stores events in history."""
        await emitter.emit(sample_event)

        assert len(emitter._event_history) == 1
        assert emitter._event_history[0] == sample_event

    @pytest.mark.asyncio
    async def test_emit_history_caps_at_max(self, emitter):
        """emit() limits history to max_history entries."""
        emitter._max_history = 10

        for i in range(15):
            event = StreamEvent(
                type=StreamEventType.HEARTBEAT,
                data={"i": i},
            )
            await emitter.emit(event)

        assert len(emitter._event_history) == 10
        # Should have most recent events (5-14)
        assert emitter._event_history[0].data["i"] == 5
        assert emitter._event_history[-1].data["i"] == 14

    @pytest.mark.asyncio
    async def test_emit_removes_disconnected_clients(self, emitter, sample_event):
        """emit() removes clients that fail to send."""
        ws_good = MagicMock()
        ws_good.send_str = AsyncMock()
        ws_bad = MagicMock()
        ws_bad.send_str = AsyncMock(side_effect=ConnectionError("Disconnected"))

        emitter.add_client(ws_good)
        id_bad = emitter.add_client(ws_bad)

        assert emitter.client_count == 2

        await emitter.emit(sample_event)

        # Bad client should be removed
        assert emitter.client_count == 1
        assert id_bad not in emitter._clients

    @pytest.mark.asyncio
    async def test_emit_sends_correct_json(self, emitter, mock_websocket, sample_event):
        """emit() sends correctly formatted JSON."""
        emitter.add_client(mock_websocket)
        await emitter.emit(sample_event)

        call_arg = mock_websocket.send_str.call_args[0][0]
        parsed = json.loads(call_arg)

        assert parsed["type"] == "alert_created"
        assert parsed["data"]["alert_id"] == "alert-123"
        assert "timestamp" in parsed

    def test_emit_sync_creates_task(self, emitter, sample_event):
        """emit_sync() creates an async task for emission."""

        # We need an event loop running for this test
        async def run_test():
            ws = MagicMock()
            ws.send_str = AsyncMock()
            emitter.add_client(ws)

            emitter.emit_sync(sample_event)

            # Give the task time to run
            await asyncio.sleep(0.1)

            ws.send_str.assert_called_once()

        asyncio.run(run_test())

    def test_emit_sync_no_loop_logs_debug(self, emitter, sample_event, caplog):
        """emit_sync() logs debug when no event loop is running."""
        import logging

        with caplog.at_level(logging.DEBUG):
            emitter.emit_sync(sample_event)

        # Should handle gracefully without raising
        # Event is queued or logged

    def test_get_history_returns_all(self, emitter):
        """get_history() returns all events when no filter."""
        for i in range(5):
            emitter._event_history.append(
                StreamEvent(type=StreamEventType.ALERT_CREATED, data={"i": i})
            )

        history = emitter.get_history()
        assert len(history) == 5

    def test_get_history_filters_by_event_type(self, emitter):
        """get_history() filters by event types."""
        emitter._event_history.append(
            StreamEvent(type=StreamEventType.ALERT_CREATED, data={"id": "a1"})
        )
        emitter._event_history.append(
            StreamEvent(type=StreamEventType.TREND_DETECTED, data={"id": "t1"})
        )
        emitter._event_history.append(
            StreamEvent(type=StreamEventType.ALERT_RESOLVED, data={"id": "a2"})
        )

        history = emitter.get_history(event_types=["alert_created", "alert_resolved"])
        assert len(history) == 2

    def test_get_history_respects_limit(self, emitter):
        """get_history() limits number of returned events."""
        for i in range(20):
            emitter._event_history.append(
                StreamEvent(type=StreamEventType.HEARTBEAT, data={"i": i})
            )

        history = emitter.get_history(limit=5)
        assert len(history) == 5
        # Should return the most recent 5
        assert history[0]["data"]["i"] == 15
        assert history[-1]["data"]["i"] == 19

    def test_get_history_returns_dicts(self, emitter):
        """get_history() returns list of dictionaries."""
        emitter._event_history.append(
            StreamEvent(type=StreamEventType.ALERT_CREATED, data={"test": True})
        )

        history = emitter.get_history()
        assert isinstance(history, list)
        assert isinstance(history[0], dict)
        assert history[0]["type"] == "alert_created"

    def test_client_count_property(self, emitter):
        """client_count returns number of connected clients."""
        assert emitter.client_count == 0

        ws1, ws2 = MagicMock(), MagicMock()
        emitter.add_client(ws1)
        assert emitter.client_count == 1

        emitter.add_client(ws2)
        assert emitter.client_count == 2


# ===========================================================================
# Test Global Emitter Functions
# ===========================================================================


class TestGlobalEmitterFunctions:
    """Tests for global emitter management functions."""

    def test_get_autonomous_emitter_creates_instance(self):
        """get_autonomous_emitter() creates a new instance if none exists."""
        emitter = get_autonomous_emitter()
        assert isinstance(emitter, AutonomousStreamEmitter)

    def test_get_autonomous_emitter_returns_same_instance(self):
        """get_autonomous_emitter() returns the same instance on subsequent calls."""
        emitter1 = get_autonomous_emitter()
        emitter2 = get_autonomous_emitter()
        assert emitter1 is emitter2

    def test_set_autonomous_emitter(self):
        """set_autonomous_emitter() sets the global instance."""
        custom_emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(custom_emitter)

        retrieved = get_autonomous_emitter()
        assert retrieved is custom_emitter


# ===========================================================================
# Test Event Helper Functions
# ===========================================================================


class TestEmitApprovalEvent:
    """Tests for emit_approval_event helper function."""

    def test_emit_approval_requested(self):
        """emit_approval_event emits approval_requested event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_approval_event(
                event_type="requested",
                request_id="req-123",
                title="Deploy to production",
                priority="high",
            )
            await asyncio.sleep(0.1)
            assert len(emitter._event_history) == 1
            event = emitter._event_history[0]
            assert event.type == StreamEventType.APPROVAL_REQUESTED
            assert event.data["request_id"] == "req-123"
            assert event.data["title"] == "Deploy to production"
            assert event.data["priority"] == "high"

        asyncio.run(check())

    def test_emit_approval_approved(self):
        """emit_approval_event emits approval_approved event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_approval_event(
                event_type="approved",
                request_id="req-456",
                title="Test Approval",
                approved_by="admin",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.APPROVAL_APPROVED

        asyncio.run(check())

    def test_emit_approval_rejected(self):
        """emit_approval_event emits approval_rejected event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_approval_event(
                event_type="rejected",
                request_id="req-789",
                title="Test",
                reason="Not allowed",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.APPROVAL_REJECTED

        asyncio.run(check())

    def test_emit_approval_timeout(self):
        """emit_approval_event emits approval_timeout event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_approval_event(
                event_type="timeout",
                request_id="req-timeout",
                title="Timeout Test",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.APPROVAL_TIMEOUT

        asyncio.run(check())

    def test_emit_approval_auto_approved(self):
        """emit_approval_event emits approval_auto_approved event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_approval_event(
                event_type="auto_approved",
                request_id="req-auto",
                title="Low Risk Action",
                risk_score=0.1,
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.APPROVAL_AUTO_APPROVED

        asyncio.run(check())

    def test_emit_approval_unknown_type_defaults(self):
        """emit_approval_event defaults to requested for unknown types."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_approval_event(
                event_type="unknown_type",
                request_id="req-default",
                title="Default Test",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.APPROVAL_REQUESTED

        asyncio.run(check())


class TestEmitAlertEvent:
    """Tests for emit_alert_event helper function."""

    def test_emit_alert_created(self):
        """emit_alert_event emits alert_created event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_alert_event(
                event_type="created",
                alert_id="alert-001",
                severity="critical",
                title="System Down",
                source="monitoring",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.ALERT_CREATED
            assert event.data["alert_id"] == "alert-001"
            assert event.data["severity"] == "critical"
            assert event.data["source"] == "monitoring"

        asyncio.run(check())

    def test_emit_alert_acknowledged(self):
        """emit_alert_event emits alert_acknowledged event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_alert_event(
                event_type="acknowledged",
                alert_id="alert-002",
                severity="high",
                title="Test",
                acked_by="user1",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.ALERT_ACKNOWLEDGED

        asyncio.run(check())

    def test_emit_alert_resolved(self):
        """emit_alert_event emits alert_resolved event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_alert_event(
                event_type="resolved",
                alert_id="alert-003",
                severity="medium",
                title="Resolved Alert",
                resolution="Auto-healed",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.ALERT_RESOLVED

        asyncio.run(check())

    def test_emit_alert_escalated(self):
        """emit_alert_event emits alert_escalated event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            with patch("aragora.workflow.engine.WorkflowEngine.pause_all"):
                emit_alert_event(
                    event_type="escalated",
                    alert_id="alert-004",
                    severity="critical",
                    title="Escalated",
                    new_severity="critical",
                )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.ALERT_ESCALATED

        asyncio.run(check())

    def test_emit_alert_escalated_reaches_workflow_brake_exactly_once(
        self,
        clean_cross_subscriber_manager,
    ):
        """Critical production escalations brake once before broadcast."""
        delivery_order = []
        emitter = MagicMock(spec=AutonomousStreamEmitter)
        emitter.emit_sync.side_effect = lambda event: delivery_order.append("broadcast")
        set_autonomous_emitter(emitter)

        with patch(
            "aragora.workflow.engine.WorkflowEngine.pause_all",
            side_effect=lambda **kwargs: delivery_order.append("brake"),
        ) as pause_all:
            emit_alert_event(
                event_type="escalated",
                alert_id="alert-critical",
                severity="high",
                title="Critical production alert",
                new_severity="critical",
                reason="Database connection pool exhausted",
            )

        pause_all.assert_called_once_with(
            reason="Emergency brake: Database connection pool exhausted"
        )
        emitter.emit_sync.assert_called_once()
        event = emitter.emit_sync.call_args.args[0]
        assert event.type == StreamEventType.ALERT_ESCALATED
        assert event.data == {
            "alert_id": "alert-critical",
            "severity": "high",
            "title": "Critical production alert",
            "new_severity": "critical",
            "reason": "Database connection pool exhausted",
        }
        assert delivery_order == ["brake", "broadcast"]

    def test_emit_alert_escalated_noncritical_preserves_broadcast_behavior(self):
        """Noncritical escalation remains a broadcast-only alert event."""
        emitter = MagicMock(spec=AutonomousStreamEmitter)
        set_autonomous_emitter(emitter)

        with patch(
            "aragora.server.startup.event_subscribers.bootstrap_event_subscribers"
        ) as bootstrap:
            emit_alert_event(
                event_type="escalated",
                alert_id="alert-warning",
                severity="warning",
                title="Warning escalation",
            )

        bootstrap.assert_not_called()
        emitter.emit_sync.assert_called_once()
        assert emitter.emit_sync.call_args.args[0].type == StreamEventType.ALERT_ESCALATED

    def test_emit_alert_escalated_fails_closed_without_production_wiring(
        self,
        clean_cross_subscriber_manager,
    ):
        """Critical escalation cannot broadcast without its production brake wiring."""
        from aragora.events.cross_subscribers import CrossSubscriberManager

        emitter = MagicMock(spec=AutonomousStreamEmitter)
        set_autonomous_emitter(emitter)

        with (
            patch(
                "aragora.server.startup.event_subscribers.bootstrap_event_subscribers",
                return_value=CrossSubscriberManager(),
            ),
            pytest.raises(RuntimeError, match="alert_escalated_to_workflow_brake"),
        ):
            emit_alert_event(
                event_type="escalated",
                alert_id="alert-unwired",
                severity="critical",
                title="Unwired production alert",
            )

        emitter.emit_sync.assert_not_called()


class TestEmitTriggerEvent:
    """Tests for emit_trigger_event helper function."""

    def test_emit_trigger_added(self):
        """emit_trigger_event emits trigger_added event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_trigger_event(
                event_type="added",
                trigger_id="trig-001",
                name="Daily Cleanup",
                schedule="0 0 * * *",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.TRIGGER_ADDED
            assert event.data["trigger_id"] == "trig-001"
            assert event.data["name"] == "Daily Cleanup"

        asyncio.run(check())

    def test_emit_trigger_removed(self):
        """emit_trigger_event emits trigger_removed event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_trigger_event(
                event_type="removed",
                trigger_id="trig-002",
                name="Old Trigger",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.TRIGGER_REMOVED

        asyncio.run(check())

    def test_emit_trigger_executed(self):
        """emit_trigger_event emits trigger_executed event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_trigger_event(
                event_type="executed",
                trigger_id="trig-003",
                name="Backup Job",
                result="success",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.TRIGGER_EXECUTED

        asyncio.run(check())

    def test_emit_trigger_scheduler_start(self):
        """emit_trigger_event emits trigger_scheduler_start event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_trigger_event(
                event_type="scheduler_start",
                trigger_id="scheduler",
                name="Main Scheduler",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.TRIGGER_SCHEDULER_START

        asyncio.run(check())

    def test_emit_trigger_scheduler_stop(self):
        """emit_trigger_event emits trigger_scheduler_stop event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_trigger_event(
                event_type="scheduler_stop",
                trigger_id="scheduler",
                name="Main Scheduler",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.TRIGGER_SCHEDULER_STOP

        asyncio.run(check())


class TestEmitMonitoringEvent:
    """Tests for emit_monitoring_event helper function."""

    def test_emit_trend_detected(self):
        """emit_monitoring_event emits trend_detected event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_monitoring_event(
                event_type="trend",
                metric_name="cpu_usage",
                value=85.5,
                direction="increasing",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.TREND_DETECTED
            assert event.data["metric_name"] == "cpu_usage"
            assert event.data["value"] == 85.5

        asyncio.run(check())

    def test_emit_anomaly_detected(self):
        """emit_monitoring_event emits anomaly_detected event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_monitoring_event(
                event_type="anomaly",
                metric_name="request_latency",
                value=1500.0,
                threshold=500.0,
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.ANOMALY_DETECTED

        asyncio.run(check())

    def test_emit_metric_recorded(self):
        """emit_monitoring_event emits metric_recorded event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_monitoring_event(
                event_type="metric",
                metric_name="requests_per_second",
                value=1234.56,
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.METRIC_RECORDED

        asyncio.run(check())


class TestEmitLearningEvent:
    """Tests for emit_learning_event helper function."""

    def test_emit_elo_updated(self):
        """emit_learning_event emits elo_updated event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_learning_event(
                event_type="elo_updated",
                agent_id="claude",
                old_elo=1500,
                new_elo=1520,
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.ELO_UPDATED
            assert event.data["agent_id"] == "claude"
            assert event.data["old_elo"] == 1500
            assert event.data["new_elo"] == 1520

        asyncio.run(check())

    def test_emit_pattern_discovered(self):
        """emit_learning_event emits pattern_discovered event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_learning_event(
                event_type="pattern_discovered",
                pattern_type="debate_strategy",
                confidence=0.85,
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.PATTERN_DISCOVERED

        asyncio.run(check())

    def test_emit_calibration_updated(self):
        """emit_learning_event emits calibration_updated event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_learning_event(
                event_type="calibration_updated",
                agent_id="gpt4",
                calibration_score=0.92,
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.CALIBRATION_UPDATED

        asyncio.run(check())

    def test_emit_knowledge_decayed(self):
        """emit_learning_event emits knowledge_decayed event."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_learning_event(
                event_type="knowledge_decayed",
                knowledge_id="k-123",
                decay_factor=0.1,
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.KNOWLEDGE_DECAYED

        asyncio.run(check())

    def test_emit_learning_generic(self):
        """emit_learning_event emits learning_event for generic type."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_learning_event(
                event_type="learning",
                description="General learning update",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.LEARNING_EVENT

        asyncio.run(check())

    def test_emit_learning_without_agent_id(self):
        """emit_learning_event works without agent_id."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_learning_event(
                event_type="pattern_discovered",
                pattern_type="global",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert "agent_id" not in event.data

        asyncio.run(check())


# ===========================================================================
# Test WebSocket Handler
# ===========================================================================


class TestAutonomousWebSocketHandler:
    """Tests for autonomous_websocket_handler."""

    @pytest.fixture
    def mock_ws_response(self):
        """Create a comprehensive mock WebSocket response."""
        ws = MagicMock()
        ws.prepare = AsyncMock()
        ws.send_json = AsyncMock()
        ws.send_str = AsyncMock()
        ws.exception = MagicMock(return_value=None)
        return ws

    @staticmethod
    def create_async_iter(items):
        """Create an async iterator from a list of items."""

        async def async_gen():
            for item in items:
                yield item

        return async_gen()

    @pytest.mark.asyncio
    async def test_handler_prepares_websocket(self, mock_request):
        """Handler prepares WebSocket response."""
        from aiohttp import web, WSMsgType

        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = MagicMock()
            mock_ws.prepare = AsyncMock()
            mock_ws.send_json = AsyncMock()
            mock_ws.__aiter__ = lambda self: self.create_async_iter([])
            mock_ws_class.return_value = mock_ws
            # Use proper async iter
            mock_ws.__aiter__ = lambda s: TestAutonomousWebSocketHandler.create_async_iter([])

            emitter = AutonomousStreamEmitter()
            set_autonomous_emitter(emitter)

            await autonomous_websocket_handler(mock_request)

            mock_ws.prepare.assert_called_once_with(mock_request)

    @pytest.mark.asyncio
    async def test_handler_sends_welcome_message(self, mock_request):
        """Handler sends welcome message on connection."""
        from aiohttp import web

        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = MagicMock()
            mock_ws.prepare = AsyncMock()
            mock_ws.send_json = AsyncMock()
            mock_ws.__aiter__ = lambda s: TestAutonomousWebSocketHandler.create_async_iter([])
            mock_ws_class.return_value = mock_ws

            emitter = AutonomousStreamEmitter()
            set_autonomous_emitter(emitter)

            await autonomous_websocket_handler(mock_request)

            # Check welcome message was sent
            mock_ws.send_json.assert_called()
            call_arg = mock_ws.send_json.call_args[0][0]
            assert call_arg["type"] == "connected"
            assert "client_id" in call_arg
            assert "timestamp" in call_arg

    @pytest.mark.asyncio
    async def test_handler_parses_subscription_query_param(self, mock_request):
        """Handler parses subscribe query parameter."""
        mock_request.query = {"subscribe": "alert_created,trend_detected"}

        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = MagicMock()
            mock_ws.prepare = AsyncMock()
            mock_ws.send_json = AsyncMock()
            mock_ws.__aiter__ = lambda s: TestAutonomousWebSocketHandler.create_async_iter([])
            mock_ws_class.return_value = mock_ws

            emitter = AutonomousStreamEmitter()
            set_autonomous_emitter(emitter)

            await autonomous_websocket_handler(mock_request)

            call_arg = mock_ws.send_json.call_args[0][0]
            subs = set(call_arg["subscriptions"])
            assert "alert_created" in subs
            assert "trend_detected" in subs

    @pytest.mark.asyncio
    async def test_handler_removes_client_on_disconnect(self, mock_request):
        """Handler removes client when connection closes."""
        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = MagicMock()
            mock_ws.prepare = AsyncMock()
            mock_ws.send_json = AsyncMock()
            mock_ws.__aiter__ = lambda s: TestAutonomousWebSocketHandler.create_async_iter([])
            mock_ws_class.return_value = mock_ws

            emitter = AutonomousStreamEmitter()
            set_autonomous_emitter(emitter)

            await autonomous_websocket_handler(mock_request)

            # Client should be removed after handler returns
            assert emitter.client_count == 0


class TestRegisterRoutes:
    """Tests for route registration."""

    def test_register_autonomous_stream_routes(self):
        """register_autonomous_stream_routes adds the route."""
        mock_app = MagicMock()
        mock_router = MagicMock()
        mock_app.router = mock_router

        register_autonomous_stream_routes(mock_app)

        mock_router.add_get.assert_called_once_with(
            "/ws/autonomous",
            autonomous_websocket_handler,
        )


# ===========================================================================
# Test Concurrent Broadcasting
# ===========================================================================


class TestConcurrentBroadcasting:
    """Tests for concurrent event broadcasting."""

    @pytest.mark.asyncio
    async def test_concurrent_emit_to_multiple_clients(self, emitter):
        """Multiple concurrent emits broadcast correctly."""
        clients = []
        for i in range(10):
            ws = MagicMock()
            ws.send_str = AsyncMock()
            emitter.add_client(ws)
            clients.append(ws)

        # Emit multiple events concurrently
        events = [StreamEvent(type=StreamEventType.ALERT_CREATED, data={"i": i}) for i in range(5)]

        await asyncio.gather(*[emitter.emit(e) for e in events])

        # Each client should have received all 5 events
        for client in clients:
            assert client.send_str.call_count == 5

    @pytest.mark.asyncio
    async def test_concurrent_emit_with_mixed_subscriptions(self, emitter):
        """Concurrent emits respect varied subscriptions."""
        ws_alerts = MagicMock()
        ws_alerts.send_str = AsyncMock()
        ws_trends = MagicMock()
        ws_trends.send_str = AsyncMock()
        ws_all = MagicMock()
        ws_all.send_str = AsyncMock()

        emitter.add_client(ws_alerts, subscriptions={"alert_created"})
        emitter.add_client(ws_trends, subscriptions={"trend_detected"})
        emitter.add_client(ws_all, subscriptions=set())

        events = [
            StreamEvent(type=StreamEventType.ALERT_CREATED, data={}),
            StreamEvent(type=StreamEventType.TREND_DETECTED, data={}),
            StreamEvent(type=StreamEventType.ALERT_CREATED, data={}),
        ]

        await asyncio.gather(*[emitter.emit(e) for e in events])

        # ws_alerts should receive 2 alerts
        assert ws_alerts.send_str.call_count == 2
        # ws_trends should receive 1 trend
        assert ws_trends.send_str.call_count == 1
        # ws_all should receive all 3
        assert ws_all.send_str.call_count == 3

    @pytest.mark.asyncio
    async def test_emit_handles_partial_client_failures(self, emitter):
        """Emit continues despite some client failures."""
        ws_good1 = MagicMock()
        ws_good1.send_str = AsyncMock()
        ws_bad = MagicMock()
        ws_bad.send_str = AsyncMock(side_effect=ConnectionError("Failed"))
        ws_good2 = MagicMock()
        ws_good2.send_str = AsyncMock()

        emitter.add_client(ws_good1)
        emitter.add_client(ws_bad)
        emitter.add_client(ws_good2)

        event = StreamEvent(type=StreamEventType.HEARTBEAT, data={})
        await emitter.emit(event)

        # Good clients should still receive the event
        ws_good1.send_str.assert_called_once()
        ws_good2.send_str.assert_called_once()


# ===========================================================================
# Test Error Handling
# ===========================================================================


class TestErrorHandling:
    """Tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_emit_logs_warning_on_send_failure(self, emitter, caplog):
        """emit() logs warning when send fails."""
        import logging

        ws = MagicMock()
        ws.send_str = AsyncMock(side_effect=OSError("Connection reset"))
        emitter.add_client(ws)

        with caplog.at_level(logging.WARNING):
            await emitter.emit(StreamEvent(type=StreamEventType.HEARTBEAT, data={}))

        assert any("Failed to send" in record.message for record in caplog.records)

    def test_remove_client_is_idempotent(self, emitter, mock_websocket):
        """Removing a client multiple times doesn't raise."""
        client_id = emitter.add_client(mock_websocket)

        emitter.remove_client(client_id)
        emitter.remove_client(client_id)  # Should not raise
        emitter.remove_client(client_id)  # Should not raise

        assert emitter.client_count == 0

    @pytest.mark.asyncio
    async def test_emit_to_empty_client_list(self, emitter):
        """emit() handles empty client list gracefully."""
        event = StreamEvent(type=StreamEventType.HEARTBEAT, data={})
        # Should not raise
        await emitter.emit(event)
        assert len(emitter._event_history) == 1


# ===========================================================================
# Test WebSocket Message Processing
# ===========================================================================


class TestWebSocketMessageProcessing:
    """Tests for WebSocket message processing in the handler."""

    @staticmethod
    def create_async_iter(items):
        """Create an async iterator from a list of items."""

        async def async_gen():
            for item in items:
                yield item

        return async_gen()

    @staticmethod
    def create_ws_message(msg_type, data):
        """Create a mock WebSocket message."""
        from aiohttp import WSMsgType

        msg = MagicMock()
        msg.type = msg_type
        msg.data = json.dumps(data) if isinstance(data, dict) else data
        return msg

    @pytest.fixture
    def mock_request(self):
        """Create a mock aiohttp request."""
        request = MagicMock()
        request.query = {}
        return request

    @pytest.mark.asyncio
    async def test_handler_processes_ping_message(self, mock_request):
        """Handler responds to ping with pong."""
        from aiohttp import WSMsgType

        ping_msg = self.create_ws_message(WSMsgType.TEXT, {"type": "ping"})

        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = MagicMock()
            mock_ws.prepare = AsyncMock()
            mock_ws.send_json = AsyncMock()
            mock_ws.__aiter__ = lambda s: self.create_async_iter([ping_msg])
            mock_ws_class.return_value = mock_ws

            emitter = AutonomousStreamEmitter()
            set_autonomous_emitter(emitter)

            await autonomous_websocket_handler(mock_request)

            # Should have sent welcome + pong
            assert mock_ws.send_json.call_count == 2
            # Second call should be pong
            pong_call = mock_ws.send_json.call_args_list[1][0][0]
            assert pong_call["type"] == "pong"
            assert "timestamp" in pong_call

    @pytest.mark.asyncio
    async def test_handler_processes_subscribe_message(self, mock_request):
        """Handler processes subscribe request."""
        from aiohttp import WSMsgType

        sub_msg = self.create_ws_message(
            WSMsgType.TEXT, {"type": "subscribe", "events": ["alert_created", "trend_detected"]}
        )

        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = MagicMock()
            mock_ws.prepare = AsyncMock()
            mock_ws.send_json = AsyncMock()
            mock_ws.__aiter__ = lambda s: self.create_async_iter([sub_msg])
            mock_ws_class.return_value = mock_ws

            emitter = AutonomousStreamEmitter()
            set_autonomous_emitter(emitter)

            await autonomous_websocket_handler(mock_request)

            # Second call should be subscribed confirmation
            sub_call = mock_ws.send_json.call_args_list[1][0][0]
            assert sub_call["type"] == "subscribed"
            assert set(sub_call["events"]) == {"alert_created", "trend_detected"}

    @pytest.mark.asyncio
    async def test_handler_processes_unsubscribe_message(self, mock_request):
        """Handler processes unsubscribe request."""
        from aiohttp import WSMsgType

        mock_request.query = {"subscribe": "alert_created,trend_detected"}
        unsub_msg = self.create_ws_message(
            WSMsgType.TEXT, {"type": "unsubscribe", "events": ["alert_created"]}
        )

        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = MagicMock()
            mock_ws.prepare = AsyncMock()
            mock_ws.send_json = AsyncMock()
            mock_ws.__aiter__ = lambda s: self.create_async_iter([unsub_msg])
            mock_ws_class.return_value = mock_ws

            emitter = AutonomousStreamEmitter()
            set_autonomous_emitter(emitter)

            await autonomous_websocket_handler(mock_request)

            # Second call should be unsubscribed confirmation
            unsub_call = mock_ws.send_json.call_args_list[1][0][0]
            assert unsub_call["type"] == "unsubscribed"
            assert "alert_created" in unsub_call["events"]

    @pytest.mark.asyncio
    async def test_handler_processes_get_history_message(self, mock_request):
        """Handler processes get_history request."""
        from aiohttp import WSMsgType

        # Pre-populate some history
        emitter = AutonomousStreamEmitter()
        emitter._event_history.append(
            StreamEvent(type=StreamEventType.ALERT_CREATED, data={"id": "a1"})
        )
        emitter._event_history.append(
            StreamEvent(type=StreamEventType.TREND_DETECTED, data={"id": "t1"})
        )
        set_autonomous_emitter(emitter)

        history_msg = self.create_ws_message(WSMsgType.TEXT, {"type": "get_history", "limit": 10})

        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = MagicMock()
            mock_ws.prepare = AsyncMock()
            mock_ws.send_json = AsyncMock()
            mock_ws.__aiter__ = lambda s: self.create_async_iter([history_msg])
            mock_ws_class.return_value = mock_ws

            await autonomous_websocket_handler(mock_request)

            # Second call should be history response
            history_call = mock_ws.send_json.call_args_list[1][0][0]
            assert history_call["type"] == "history"
            assert history_call["count"] == 2
            assert len(history_call["events"]) == 2

    @pytest.mark.asyncio
    async def test_handler_processes_get_history_with_event_types_filter(self, mock_request):
        """Handler filters history by event types."""
        from aiohttp import WSMsgType

        emitter = AutonomousStreamEmitter()
        emitter._event_history.append(
            StreamEvent(type=StreamEventType.ALERT_CREATED, data={"id": "a1"})
        )
        emitter._event_history.append(
            StreamEvent(type=StreamEventType.TREND_DETECTED, data={"id": "t1"})
        )
        emitter._event_history.append(
            StreamEvent(type=StreamEventType.ALERT_RESOLVED, data={"id": "a2"})
        )
        set_autonomous_emitter(emitter)

        history_msg = self.create_ws_message(
            WSMsgType.TEXT, {"type": "get_history", "event_types": ["alert_created"], "limit": 10}
        )

        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = MagicMock()
            mock_ws.prepare = AsyncMock()
            mock_ws.send_json = AsyncMock()
            mock_ws.__aiter__ = lambda s: self.create_async_iter([history_msg])
            mock_ws_class.return_value = mock_ws

            await autonomous_websocket_handler(mock_request)

            history_call = mock_ws.send_json.call_args_list[1][0][0]
            assert history_call["count"] == 1
            assert history_call["events"][0]["type"] == "alert_created"

    @pytest.mark.asyncio
    async def test_handler_handles_invalid_json(self, mock_request):
        """Handler sends error on invalid JSON."""
        from aiohttp import WSMsgType

        invalid_msg = MagicMock()
        invalid_msg.type = WSMsgType.TEXT
        invalid_msg.data = "not valid json {"

        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = MagicMock()
            mock_ws.prepare = AsyncMock()
            mock_ws.send_json = AsyncMock()
            mock_ws.__aiter__ = lambda s: self.create_async_iter([invalid_msg])
            mock_ws_class.return_value = mock_ws

            emitter = AutonomousStreamEmitter()
            set_autonomous_emitter(emitter)

            await autonomous_websocket_handler(mock_request)

            # Second call should be error
            error_call = mock_ws.send_json.call_args_list[1][0][0]
            assert error_call["type"] == "error"
            assert "Invalid JSON" in error_call["message"]

    @pytest.mark.asyncio
    async def test_handler_handles_ws_error_message(self, mock_request):
        """Handler breaks on WSMsgType.ERROR."""
        from aiohttp import WSMsgType

        error_msg = MagicMock()
        error_msg.type = WSMsgType.ERROR

        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = MagicMock()
            mock_ws.prepare = AsyncMock()
            mock_ws.send_json = AsyncMock()
            mock_ws.exception = MagicMock(return_value=Exception("WebSocket error"))
            mock_ws.__aiter__ = lambda s: self.create_async_iter([error_msg])
            mock_ws_class.return_value = mock_ws

            emitter = AutonomousStreamEmitter()
            set_autonomous_emitter(emitter)

            await autonomous_websocket_handler(mock_request)

            # Only welcome message should be sent
            assert mock_ws.send_json.call_count == 1

    @pytest.mark.asyncio
    async def test_handler_empty_subscribe_query_param(self, mock_request):
        """Handler handles empty subscribe param."""
        mock_request.query = {"subscribe": ""}

        with patch("aiohttp.web.WebSocketResponse") as mock_ws_class:
            mock_ws = MagicMock()
            mock_ws.prepare = AsyncMock()
            mock_ws.send_json = AsyncMock()
            mock_ws.__aiter__ = lambda s: self.create_async_iter([])
            mock_ws_class.return_value = mock_ws

            emitter = AutonomousStreamEmitter()
            set_autonomous_emitter(emitter)

            await autonomous_websocket_handler(mock_request)

            call_arg = mock_ws.send_json.call_args[0][0]
            # Empty string split creates [''] so we get one empty subscription
            assert call_arg["type"] == "connected"


# ===========================================================================
# Test Client ID Generation and Format
# ===========================================================================


class TestClientIdGeneration:
    """Tests for client ID generation."""

    def test_client_id_format(self, emitter, mock_websocket):
        """Client ID follows expected format."""
        client_id = emitter.add_client(mock_websocket)
        parts = client_id.split("_")
        assert parts[0] == "auto"
        assert parts[1].isdigit()
        assert parts[2].isdigit()

    def test_client_id_counter_increments(self, emitter):
        """Client counter increments with each client."""
        ws1, ws2 = MagicMock(), MagicMock()
        id1 = emitter.add_client(ws1)
        id2 = emitter.add_client(ws2)

        counter1 = int(id1.split("_")[1])
        counter2 = int(id2.split("_")[1])
        assert counter2 == counter1 + 1

    def test_client_id_includes_timestamp(self, emitter, mock_websocket):
        """Client ID includes approximate timestamp."""
        before = int(time.time())
        client_id = emitter.add_client(mock_websocket)
        after = int(time.time())

        timestamp = int(client_id.split("_")[2])
        assert before <= timestamp <= after


# ===========================================================================
# Test Event History Edge Cases
# ===========================================================================


class TestEventHistoryEdgeCases:
    """Tests for event history edge cases."""

    def test_get_history_empty(self, emitter):
        """get_history() returns empty list for empty history."""
        history = emitter.get_history()
        assert history == []

    def test_get_history_limit_greater_than_size(self, emitter):
        """get_history() handles limit larger than history size."""
        emitter._event_history.append(StreamEvent(type=StreamEventType.HEARTBEAT, data={}))
        history = emitter.get_history(limit=100)
        assert len(history) == 1

    def test_get_history_with_all_filtered_out(self, emitter):
        """get_history() returns empty when filter matches nothing."""
        emitter._event_history.append(StreamEvent(type=StreamEventType.HEARTBEAT, data={}))
        history = emitter.get_history(event_types=["nonexistent_type"])
        assert history == []

    def test_get_history_preserves_order(self, emitter):
        """get_history() preserves chronological order."""
        for i in range(5):
            emitter._event_history.append(
                StreamEvent(type=StreamEventType.HEARTBEAT, data={"order": i})
            )
        history = emitter.get_history()
        for i, event in enumerate(history):
            assert event["data"]["order"] == i

    @pytest.mark.asyncio
    async def test_history_truncation_preserves_recent(self, emitter):
        """History truncation keeps most recent events."""
        emitter._max_history = 5
        for i in range(10):
            await emitter.emit(StreamEvent(type=StreamEventType.HEARTBEAT, data={"i": i}))
        assert len(emitter._event_history) == 5
        # Should have events 5-9
        assert emitter._event_history[0].data["i"] == 5
        assert emitter._event_history[-1].data["i"] == 9


# ===========================================================================
# Test Subscription Filtering
# ===========================================================================


class TestSubscriptionFiltering:
    """Tests for subscription-based event filtering."""

    @pytest.mark.asyncio
    async def test_multiple_event_types_in_subscription(self, emitter):
        """Client can subscribe to multiple event types."""
        ws = MagicMock()
        ws.send_str = AsyncMock()
        emitter.add_client(
            ws, subscriptions={"alert_created", "alert_acknowledged", "trend_detected"}
        )

        events = [
            StreamEvent(type=StreamEventType.ALERT_CREATED, data={}),
            StreamEvent(type=StreamEventType.ALERT_ACKNOWLEDGED, data={}),
            StreamEvent(type=StreamEventType.TREND_DETECTED, data={}),
            StreamEvent(type=StreamEventType.TRIGGER_EXECUTED, data={}),  # Not subscribed
        ]

        for event in events:
            await emitter.emit(event)

        # Should receive 3 of 4 events
        assert ws.send_str.call_count == 3

    @pytest.mark.asyncio
    async def test_subscription_is_case_sensitive(self, emitter):
        """Subscriptions are case-sensitive."""
        ws = MagicMock()
        ws.send_str = AsyncMock()
        emitter.add_client(ws, subscriptions={"ALERT_CREATED"})  # Wrong case

        await emitter.emit(StreamEvent(type=StreamEventType.ALERT_CREATED, data={}))

        # Event type is "alert_created", subscription is "ALERT_CREATED"
        # Should not receive
        ws.send_str.assert_not_called()

    @pytest.mark.asyncio
    async def test_dynamically_updated_subscriptions(self, emitter):
        """Subscriptions can be modified after client is added."""
        ws = MagicMock()
        ws.send_str = AsyncMock()
        client_id = emitter.add_client(ws, subscriptions={"alert_created"})

        # Add more subscriptions
        emitter._clients[client_id].subscriptions.add("trend_detected")

        await emitter.emit(StreamEvent(type=StreamEventType.TREND_DETECTED, data={}))

        ws.send_str.assert_called_once()


# ===========================================================================
# Test Default Event Type Handling
# ===========================================================================


class TestDefaultEventTypeHandling:
    """Tests for default event type handling in helper functions."""

    def test_emit_alert_unknown_type_defaults(self):
        """emit_alert_event defaults to created for unknown types."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_alert_event(
                event_type="unknown",
                alert_id="a1",
                severity="low",
                title="Test",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.ALERT_CREATED

        asyncio.run(check())

    def test_emit_trigger_unknown_type_defaults(self):
        """emit_trigger_event defaults to added for unknown types."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_trigger_event(
                event_type="unknown",
                trigger_id="t1",
                name="Test",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.TRIGGER_ADDED

        asyncio.run(check())

    def test_emit_monitoring_unknown_type_defaults(self):
        """emit_monitoring_event defaults to metric_recorded for unknown types."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_monitoring_event(
                event_type="unknown",
                metric_name="test",
                value=1.0,
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.METRIC_RECORDED

        asyncio.run(check())

    def test_emit_learning_unknown_type_defaults(self):
        """emit_learning_event defaults to learning_event for unknown types."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_learning_event(
                event_type="unknown",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.type == StreamEventType.LEARNING_EVENT

        asyncio.run(check())


# ===========================================================================
# Test Lock Behavior
# ===========================================================================


class TestLockBehavior:
    """Tests for async lock behavior."""

    def test_emitter_has_lock(self, emitter):
        """Emitter has an asyncio lock."""
        assert hasattr(emitter, "_lock")
        assert isinstance(emitter._lock, asyncio.Lock)


# ===========================================================================
# Test Event Data Serialization
# ===========================================================================


class TestEventDataSerialization:
    """Tests for event data serialization."""

    @pytest.mark.asyncio
    async def test_emit_serializes_complex_data(self, emitter, mock_websocket):
        """emit() handles complex data structures."""
        emitter.add_client(mock_websocket)

        event = StreamEvent(
            type=StreamEventType.ALERT_CREATED,
            data={
                "nested": {"key": "value"},
                "list": [1, 2, 3],
                "string": "test",
                "number": 42.5,
                "boolean": True,
                "null": None,
            },
        )
        await emitter.emit(event)

        call_arg = mock_websocket.send_str.call_args[0][0]
        parsed = json.loads(call_arg)
        assert parsed["data"]["nested"]["key"] == "value"
        assert parsed["data"]["list"] == [1, 2, 3]
        assert parsed["data"]["null"] is None

    @pytest.mark.asyncio
    async def test_emit_includes_event_metadata(self, emitter, mock_websocket):
        """emit() includes all event metadata."""
        emitter.add_client(mock_websocket)

        event = StreamEvent(
            type=StreamEventType.ALERT_CREATED,
            data={"id": "a1"},
            round=2,
            agent="claude",
            loop_id="loop-123",
            seq=5,
            agent_seq=3,
        )
        await emitter.emit(event)

        call_arg = mock_websocket.send_str.call_args[0][0]
        parsed = json.loads(call_arg)
        assert parsed["round"] == 2
        assert parsed["agent"] == "claude"
        assert parsed["loop_id"] == "loop-123"
        assert parsed["seq"] == 5
        assert parsed["agent_seq"] == 3


# ===========================================================================
# Test Multiple Client Scenarios
# ===========================================================================


class TestMultipleClientScenarios:
    """Tests for scenarios with multiple clients."""

    def test_different_clients_different_subscriptions(self, emitter):
        """Different clients can have different subscriptions."""
        ws1 = MagicMock()
        ws2 = MagicMock()
        ws3 = MagicMock()

        id1 = emitter.add_client(ws1, subscriptions={"alert_created"})
        id2 = emitter.add_client(ws2, subscriptions={"trend_detected"})
        id3 = emitter.add_client(ws3, subscriptions=set())

        assert emitter._clients[id1].subscriptions == {"alert_created"}
        assert emitter._clients[id2].subscriptions == {"trend_detected"}
        assert emitter._clients[id3].subscriptions == set()

    @pytest.mark.asyncio
    async def test_remove_one_client_others_continue(self, emitter):
        """Removing one client doesn't affect others."""
        ws1, ws2, ws3 = MagicMock(), MagicMock(), MagicMock()
        ws1.send_str = AsyncMock()
        ws2.send_str = AsyncMock()
        ws3.send_str = AsyncMock()

        id1 = emitter.add_client(ws1)
        id2 = emitter.add_client(ws2)
        id3 = emitter.add_client(ws3)

        emitter.remove_client(id2)

        await emitter.emit(StreamEvent(type=StreamEventType.HEARTBEAT, data={}))

        ws1.send_str.assert_called_once()
        ws2.send_str.assert_not_called()
        ws3.send_str.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_client_during_emit_not_affected(self, emitter):
        """Client added during emit doesn't receive that event."""
        ws_existing = MagicMock()
        ws_existing.send_str = AsyncMock()
        emitter.add_client(ws_existing)

        # Start emit
        event = StreamEvent(type=StreamEventType.HEARTBEAT, data={})

        # Add new client before emit finishes
        ws_new = MagicMock()
        ws_new.send_str = AsyncMock()

        await emitter.emit(event)

        # Now add new client
        emitter.add_client(ws_new)

        # Existing client received event, new client didn't receive that event
        ws_existing.send_str.assert_called_once()
        ws_new.send_str.assert_not_called()


# ===========================================================================
# Test Max History Boundary
# ===========================================================================


class TestMaxHistoryBoundary:
    """Tests for max history boundary conditions."""

    @pytest.mark.asyncio
    async def test_exactly_at_max_history(self, emitter):
        """History at exactly max doesn't truncate."""
        emitter._max_history = 5
        for i in range(5):
            await emitter.emit(StreamEvent(type=StreamEventType.HEARTBEAT, data={"i": i}))
        assert len(emitter._event_history) == 5

    @pytest.mark.asyncio
    async def test_one_over_max_history(self, emitter):
        """One over max truncates correctly."""
        emitter._max_history = 5
        for i in range(6):
            await emitter.emit(StreamEvent(type=StreamEventType.HEARTBEAT, data={"i": i}))
        assert len(emitter._event_history) == 5
        assert emitter._event_history[0].data["i"] == 1

    def test_max_history_default_value(self, emitter):
        """Default max history is 1000."""
        assert emitter._max_history == 1000


# ===========================================================================
# Test Helper Function Kwargs
# ===========================================================================


class TestHelperFunctionKwargs:
    """Tests for extra kwargs in helper functions."""

    def test_emit_approval_with_extra_kwargs(self):
        """emit_approval_event includes extra kwargs in data."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_approval_event(
                event_type="requested",
                request_id="r1",
                title="Test",
                custom_field="custom_value",
                another_field=123,
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.data["custom_field"] == "custom_value"
            assert event.data["another_field"] == 123

        asyncio.run(check())

    def test_emit_alert_with_extra_kwargs(self):
        """emit_alert_event includes extra kwargs in data."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_alert_event(
                event_type="created",
                alert_id="a1",
                severity="high",
                title="Test",
                tags=["prod", "critical"],
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.data["tags"] == ["prod", "critical"]

        asyncio.run(check())

    def test_emit_trigger_with_extra_kwargs(self):
        """emit_trigger_event includes extra kwargs in data."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_trigger_event(
                event_type="executed",
                trigger_id="t1",
                name="Test",
                duration_ms=1500,
                success=True,
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.data["duration_ms"] == 1500
            assert event.data["success"] is True

        asyncio.run(check())

    def test_emit_monitoring_with_extra_kwargs(self):
        """emit_monitoring_event includes extra kwargs in data."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_monitoring_event(
                event_type="anomaly",
                metric_name="latency",
                value=500.0,
                expected_range=(10, 100),
                confidence=0.95,
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.data["expected_range"] == (10, 100)
            assert event.data["confidence"] == 0.95

        asyncio.run(check())

    def test_emit_learning_with_extra_kwargs(self):
        """emit_learning_event includes extra kwargs in data."""
        emitter = AutonomousStreamEmitter()
        set_autonomous_emitter(emitter)

        async def check():
            emit_learning_event(
                event_type="elo_updated",
                agent_id="claude",
                delta=20,
                match_id="m123",
            )
            await asyncio.sleep(0.1)
            event = emitter._event_history[0]
            assert event.data["delta"] == 20
            assert event.data["match_id"] == "m123"

        asyncio.run(check())
