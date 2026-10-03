"""
WebSocket stream handler for autonomous operations (Phase 5).

Provides real-time streaming of:
- Approval flow events (requested, approved, rejected)
- Alert events (created, acknowledged, resolved)
- Trigger events (added, executed, scheduler status)
- Monitoring events (trends, anomalies, metrics)
- Learning events (ELO updates, patterns, calibration)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web, WSMsgType

from aragora.events.types import StreamEvent, StreamEventType

logger = logging.getLogger(__name__)


@dataclass
class AutonomousStreamClient:
    """A connected WebSocket client for autonomous events."""

    ws: web.WebSocketResponse
    client_id: str
    connected_at: float = field(default_factory=time.time)
    subscriptions: set[str] = field(default_factory=set)  # Event type filters
    last_heartbeat: float = field(default_factory=time.time)


class AutonomousStreamEmitter:
    """
    Emitter for autonomous operation events.

    Broadcasts events to connected WebSocket clients.
    Can be used as a callback for autonomous module components.
    """

    def __init__(self):
        self._clients: dict[str, AutonomousStreamClient] = {}
        self._event_history: list[StreamEvent] = []
        self._max_history = 1000
        self._client_counter = 0
        self._lock = asyncio.Lock()

    def add_client(self, ws: web.WebSocketResponse, subscriptions: set[str] | None = None) -> str:
        """Add a new WebSocket client."""
        self._client_counter += 1
        client_id = f"auto_{self._client_counter}_{int(time.time())}"
        self._clients[client_id] = AutonomousStreamClient(
            ws=ws,
            client_id=client_id,
            subscriptions=subscriptions or set(),
        )
        logger.info("Autonomous stream client connected: %s", client_id)
        return client_id

    def remove_client(self, client_id: str) -> None:
        """Remove a WebSocket client."""
        if client_id in self._clients:
            del self._clients[client_id]
            logger.info("Autonomous stream client disconnected: %s", client_id)

    async def emit(self, event: StreamEvent) -> None:
        """
        Emit an event to all subscribed clients.

        Args:
            event: The event to broadcast
        """
        # Store in history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history :]

        # Broadcast to clients
        event_dict = event.to_dict()
        event_json = json.dumps(event_dict)
        event_type = event.type.value

        disconnected = []

        for client_id, client in self._clients.items():
            # Check subscriptions
            if client.subscriptions and event_type not in client.subscriptions:
                continue

            try:
                await client.ws.send_str(event_json)
            except (ConnectionError, OSError, RuntimeError) as e:
                logger.warning("Failed to send to client %s: %s", client_id, e)
                disconnected.append(client_id)

        # Clean up disconnected clients
        for client_id in disconnected:
            self.remove_client(client_id)

    def emit_sync(self, event: StreamEvent) -> None:
        """
        Synchronous emit wrapper for use in sync callbacks.

        Creates a task to emit the event asynchronously.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.emit(event))
        except RuntimeError:
            # No running event loop, queue for later
            logger.debug("No event loop, event queued")

    def get_history(self, event_types: list[str] | None = None, limit: int = 100) -> list[dict]:
        """Get recent event history."""
        events = self._event_history

        if event_types:
            events = [e for e in events if e.type.value in event_types]

        return [e.to_dict() for e in events[-limit:]]

    @property
    def client_count(self) -> int:
        """Get number of connected clients."""
        return len(self._clients)


# Global emitter instance
_autonomous_emitter: AutonomousStreamEmitter | None = None


def get_autonomous_emitter() -> AutonomousStreamEmitter:
    """Get or create the global autonomous stream emitter."""
    global _autonomous_emitter
    if _autonomous_emitter is None:
        _autonomous_emitter = AutonomousStreamEmitter()
    return _autonomous_emitter


def set_autonomous_emitter(emitter: AutonomousStreamEmitter) -> None:
    """Set the global autonomous stream emitter."""
    global _autonomous_emitter
    _autonomous_emitter = emitter


# Helper functions for emitting specific event types


def emit_approval_event(
    event_type: str,
    request_id: str,
    title: str,
    **kwargs: Any,
) -> None:
    """Emit an approval flow event."""
    emitter = get_autonomous_emitter()

    type_map = {
        "requested": StreamEventType.APPROVAL_REQUESTED,
        "approved": StreamEventType.APPROVAL_APPROVED,
        "rejected": StreamEventType.APPROVAL_REJECTED,
        "timeout": StreamEventType.APPROVAL_TIMEOUT,
        "auto_approved": StreamEventType.APPROVAL_AUTO_APPROVED,
    }

    event = StreamEvent(
        type=type_map.get(event_type, StreamEventType.APPROVAL_REQUESTED),
        data={
            "request_id": request_id,
            "title": title,
            **kwargs,
        },
    )
    emitter.emit_sync(event)


def emit_alert_event(
    event_type: str,
    alert_id: str,
    severity: str,
    title: str,
    **kwargs: Any,
) -> None:
    """Emit an alert event.

    Raises:
        RuntimeError: If a critical escalation cannot confirm workflow-brake delivery.
    """
    emitter = get_autonomous_emitter()

    type_map = {
        "created": StreamEventType.ALERT_CREATED,
        "acknowledged": StreamEventType.ALERT_ACKNOWLEDGED,
        "resolved": StreamEventType.ALERT_RESOLVED,
        "escalated": StreamEventType.ALERT_ESCALATED,
    }

    event = StreamEvent(
        type=type_map.get(event_type, StreamEventType.ALERT_CREATED),
        data={
            "alert_id": alert_id,
            "severity": severity,
            "title": title,
            **kwargs,
        },
    )
    brake_severity = event.data.get("new_severity", severity)
    if event_type == "escalated" and brake_severity in ("critical", "emergency", "fatal"):
        from aragora.server.startup.event_subscribers import bootstrap_event_subscribers

        manager = bootstrap_event_subscribers()
        manager.dispatch_required(event, "alert_escalated_to_workflow_brake")

    emitter.emit_sync(event)


def emit_trigger_event(
    event_type: str,
    trigger_id: str,
    name: str,
    **kwargs: Any,
) -> None:
    """Emit a trigger event."""
    emitter = get_autonomous_emitter()

    type_map = {
        "added": StreamEventType.TRIGGER_ADDED,
        "removed": StreamEventType.TRIGGER_REMOVED,
        "executed": StreamEventType.TRIGGER_EXECUTED,
        "scheduler_start": StreamEventType.TRIGGER_SCHEDULER_START,
        "scheduler_stop": StreamEventType.TRIGGER_SCHEDULER_STOP,
    }

    event = StreamEvent(
        type=type_map.get(event_type, StreamEventType.TRIGGER_ADDED),
        data={
            "trigger_id": trigger_id,
            "name": name,
            **kwargs,
        },
    )
    emitter.emit_sync(event)


def emit_monitoring_event(
    event_type: str,
    metric_name: str,
    value: float,
    **kwargs: Any,
) -> None:
    """Emit a monitoring event (trend, anomaly, metric)."""
    emitter = get_autonomous_emitter()

    type_map = {
        "trend": StreamEventType.TREND_DETECTED,
        "anomaly": StreamEventType.ANOMALY_DETECTED,
        "metric": StreamEventType.METRIC_RECORDED,
    }

    event = StreamEvent(
        type=type_map.get(event_type, StreamEventType.METRIC_RECORDED),
        data={
            "metric_name": metric_name,
            "value": value,
            **kwargs,
        },
    )
    emitter.emit_sync(event)


def emit_learning_event(
    event_type: str,
    agent_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Emit a learning event (ELO, pattern, calibration, decay)."""
    emitter = get_autonomous_emitter()

    type_map = {
        "elo_updated": StreamEventType.ELO_UPDATED,
        "pattern_discovered": StreamEventType.PATTERN_DISCOVERED,
        "calibration_updated": StreamEventType.CALIBRATION_UPDATED,
        "knowledge_decayed": StreamEventType.KNOWLEDGE_DECAYED,
        "learning": StreamEventType.LEARNING_EVENT,
    }

    data = kwargs.copy()
    if agent_id:
        data["agent_id"] = agent_id

    event = StreamEvent(
        type=type_map.get(event_type, StreamEventType.LEARNING_EVENT),
        data=data,
    )
    emitter.emit_sync(event)


async def autonomous_websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """
    WebSocket handler for autonomous operation events.

    Endpoint: /ws/autonomous

    Query params:
        subscribe: Comma-separated event types to subscribe to (optional)

    Message format (incoming):
        {"type": "subscribe", "events": ["alert_created", "trend_detected"]}
        {"type": "unsubscribe", "events": ["alert_created"]}
        {"type": "ping"}
        {"type": "get_history", "event_types": [...], "limit": 100}

    Message format (outgoing):
        {"type": "event_type", "data": {...}, "timestamp": ..., ...}
        {"type": "pong"}
        {"type": "history", "events": [...]}
    """
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    # Parse subscription from query params
    subscribe_param = request.query.get("subscribe", "")
    subscriptions = set(subscribe_param.split(",")) if subscribe_param else set()

    # Add client
    emitter = get_autonomous_emitter()
    client_id = emitter.add_client(ws, subscriptions)

    # Send welcome message
    await ws.send_json(
        {
            "type": "connected",
            "client_id": client_id,
            "subscriptions": list(subscriptions),
            "timestamp": time.time(),
        }
    )

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")

                    if msg_type == "ping":
                        await ws.send_json({"type": "pong", "timestamp": time.time()})

                    elif msg_type == "subscribe":
                        events = data.get("events", [])
                        if client_id in emitter._clients:
                            emitter._clients[client_id].subscriptions.update(events)
                            await ws.send_json(
                                {
                                    "type": "subscribed",
                                    "events": events,
                                }
                            )

                    elif msg_type == "unsubscribe":
                        events = data.get("events", [])
                        if client_id in emitter._clients:
                            emitter._clients[client_id].subscriptions.difference_update(events)
                            await ws.send_json(
                                {
                                    "type": "unsubscribed",
                                    "events": events,
                                }
                            )

                    elif msg_type == "get_history":
                        event_types = data.get("event_types")
                        limit = data.get("limit", 100)
                        history = emitter.get_history(event_types, limit)
                        await ws.send_json(
                            {
                                "type": "history",
                                "events": history,
                                "count": len(history),
                            }
                        )

                except json.JSONDecodeError:
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": "Invalid JSON",
                        }
                    )

            elif msg.type == WSMsgType.ERROR:
                logger.error("WebSocket error: %s", ws.exception())
                break

    finally:
        emitter.remove_client(client_id)

    return ws


def register_autonomous_stream_routes(app: web.Application) -> None:
    """Register the autonomous stream WebSocket route."""
    app.router.add_get("/ws/autonomous", autonomous_websocket_handler)


__all__ = [
    "AutonomousStreamEmitter",
    "AutonomousStreamClient",
    "get_autonomous_emitter",
    "set_autonomous_emitter",
    "emit_approval_event",
    "emit_alert_event",
    "emit_trigger_event",
    "emit_monitoring_event",
    "emit_learning_event",
    "autonomous_websocket_handler",
    "register_autonomous_stream_routes",
]
