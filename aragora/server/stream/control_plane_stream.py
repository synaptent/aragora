"""
WebSocket stream server for control plane events.

Provides real-time streaming of control plane events to connected clients:
- Agent status changes (registered, unregistered, idle, busy)
- Task lifecycle events (submitted, claimed, completed, failed)
- System health updates
- Scheduler metrics

Usage:
    from aragora.server.stream.control_plane_stream import ControlPlaneStreamServer

    server = ControlPlaneStreamServer(port=8766)
    await server.start()

    # Emit events from the coordinator
    await server.emit_agent_status(agent_id, status)
    await server.emit_task_event(task_id, event_type, data)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ControlPlaneEventType(Enum):
    """Types of control plane events."""

    # Connection events
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"

    # Agent events
    AGENT_REGISTERED = "agent_registered"
    AGENT_UNREGISTERED = "agent_unregistered"
    AGENT_STATUS_CHANGED = "agent_status_changed"
    AGENT_HEARTBEAT = "agent_heartbeat"
    AGENT_TIMEOUT = "agent_timeout"

    # Task events
    TASK_SUBMITTED = "task_submitted"
    TASK_CLAIMED = "task_claimed"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    TASK_RETRYING = "task_retrying"
    TASK_DEAD_LETTERED = "task_dead_lettered"

    # System events
    HEALTH_UPDATE = "health_update"
    METRICS_UPDATE = "metrics_update"
    SCHEDULER_STATS = "scheduler_stats"

    # Deliberation events
    DELIBERATION_STARTED = "deliberation_started"
    DELIBERATION_PROGRESS = "deliberation_progress"
    DELIBERATION_ROUND = "deliberation_round"
    DELIBERATION_VOTE = "deliberation_vote"
    DELIBERATION_CONSENSUS = "deliberation_consensus"
    DELIBERATION_COMPLETED = "deliberation_completed"
    DELIBERATION_FAILED = "deliberation_failed"
    DELIBERATION_SLA_WARNING = "deliberation_sla_warning"

    # Error events
    ERROR = "error"


@dataclass
class ControlPlaneEvent:
    """Event emitted by the control plane."""

    event_type: ControlPlaneEventType
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary for JSON serialization."""
        return {
            "type": self.event_type.value,
            "timestamp": self.timestamp,
            "data": self.data,
        }

    def to_json(self) -> str:
        """Serialize event to JSON string."""
        return json.dumps(self.to_dict())


class ControlPlaneStreamServer:
    """
    WebSocket server for streaming control plane events.

    Manages WebSocket connections and broadcasts control plane events
    to all connected clients in real-time.
    """

    def __init__(self, port: int = 8766, host: str = "0.0.0.0"):  # noqa: S104 - WS server binds all interfaces by default
        """Initialize the control plane stream server.

        Args:
            port: Port to listen on
            host: Host to bind to
        """
        self.port = port
        self.host = host
        self._clients: set[Any] = set()  # websockets.WebSocketServerProtocol
        self._lock = asyncio.Lock()
        self._running = False
        self._server: Any | None = None  # websockets.WebSocketServer

    async def start(self):
        """Start the WebSocket server."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed. Run: pip install websockets")
            return

        self._running = True
        self._server = await websockets.serve(
            self._handle_connection,
            self.host,
            self.port,
            ping_interval=30,
            ping_timeout=10,
        )
        logger.info("Control plane stream server started on ws://%s:%s", self.host, self.port)

    async def stop(self):
        """Stop the WebSocket server."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Control plane stream server stopped")

    async def _handle_connection(self, websocket):
        """Handle a new WebSocket connection.

        Args:
            websocket: The WebSocket connection
        """
        # Get path from websocket (websockets v15+ API)
        path = getattr(websocket, "path", getattr(websocket, "request", None))
        if hasattr(path, "path"):
            path = path.path
        path = path or "/api/control-plane/stream"

        # Only accept connections to /api/control-plane/stream
        if path not in ("/api/control-plane/stream", "/ws/control-plane"):
            await websocket.close(1003, "Invalid path")
            return

        await self._register_client(websocket)
        try:
            # Send connection confirmation
            await websocket.send(
                ControlPlaneEvent(
                    event_type=ControlPlaneEventType.CONNECTED,
                    data={"message": "Connected to control plane stream"},
                ).to_json()
            )

            # Handle incoming messages (for subscriptions, etc.)
            async for message in websocket:
                await self._handle_message(websocket, message)

        except (ConnectionError, OSError, RuntimeError) as e:
            logger.warning("WebSocket error: %s", e)
        finally:
            await self._unregister_client(websocket)

    async def _register_client(self, websocket):
        """Register a new client connection."""
        async with self._lock:
            self._clients.add(websocket)
            logger.debug("Client connected. Total clients: %s", len(self._clients))

    async def _unregister_client(self, websocket):
        """Unregister a client connection."""
        async with self._lock:
            self._clients.discard(websocket)
            logger.debug("Client disconnected. Total clients: %s", len(self._clients))

    async def _handle_message(self, websocket, message: str):
        """Handle an incoming message from a client.

        Args:
            websocket: The WebSocket connection
            message: The received message
        """
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong", "timestamp": time.time()}))

            elif msg_type == "subscribe":
                # Future: handle selective event subscriptions
                pass

        except json.JSONDecodeError:
            logger.warning("Invalid JSON message received: %s", message[:100])

    async def broadcast(self, event: ControlPlaneEvent):
        """Broadcast an event to all connected clients.

        Args:
            event: The event to broadcast
        """
        if not self._clients:
            return

        message = event.to_json()
        async with self._lock:
            clients = list(self._clients)

        # Send to all clients concurrently
        if clients:
            await asyncio.gather(
                *[self._send_to_client(client, message) for client in clients],
                return_exceptions=True,
            )

    async def _send_to_client(self, websocket, message: str):
        """Send a message to a specific client.

        Args:
            websocket: The WebSocket connection
            message: The message to send
        """
        try:
            await websocket.send(message)
        except (ConnectionError, OSError, RuntimeError) as e:
            logger.debug("Failed to send to client: %s", e)
            await self._unregister_client(websocket)

    # =========================================================================
    # High-level event emission methods
    # =========================================================================

    async def emit_agent_registered(
        self,
        agent_id: str,
        capabilities: list,
        model: str = "unknown",
        provider: str = "unknown",
    ):
        """Emit agent registered event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.AGENT_REGISTERED,
                data={
                    "agent_id": agent_id,
                    "capabilities": capabilities,
                    "model": model,
                    "provider": provider,
                },
            )
        )

    async def emit_agent_unregistered(self, agent_id: str, reason: str = ""):
        """Emit agent unregistered event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.AGENT_UNREGISTERED,
                data={"agent_id": agent_id, "reason": reason},
            )
        )

    async def emit_agent_status_changed(self, agent_id: str, old_status: str, new_status: str):
        """Emit agent status change event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.AGENT_STATUS_CHANGED,
                data={
                    "agent_id": agent_id,
                    "old_status": old_status,
                    "new_status": new_status,
                },
            )
        )

    async def emit_task_submitted(
        self,
        task_id: str,
        task_type: str,
        priority: str = "normal",
        required_capabilities: list | None = None,
    ):
        """Emit task submitted event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.TASK_SUBMITTED,
                data={
                    "task_id": task_id,
                    "task_type": task_type,
                    "priority": priority,
                    "required_capabilities": required_capabilities or [],
                },
            )
        )

    async def emit_task_claimed(self, task_id: str, agent_id: str):
        """Emit task claimed event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.TASK_CLAIMED,
                data={"task_id": task_id, "agent_id": agent_id},
            )
        )

    async def emit_task_completed(
        self, task_id: str, agent_id: str, result: dict[str, Any] | None = None
    ):
        """Emit task completed event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.TASK_COMPLETED,
                data={
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "result_summary": str(result)[:200] if result else None,
                },
            )
        )

    async def emit_task_failed(
        self, task_id: str, agent_id: str, error: str, retries_left: int = 0
    ):
        """Emit task failed event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.TASK_FAILED,
                data={
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "error": error,
                    "retries_left": retries_left,
                },
            )
        )

    async def emit_task_dead_lettered(self, task_id: str, reason: str):
        """Emit task moved to dead letter queue event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.TASK_DEAD_LETTERED,
                data={"task_id": task_id, "reason": reason},
            )
        )

    async def emit_health_update(self, status: str, agents: dict[str, Any]):
        """Emit system health update event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.HEALTH_UPDATE,
                data={"status": status, "agents": agents},
            )
        )

    async def emit_scheduler_stats(self, stats: dict[str, Any]):
        """Emit scheduler statistics event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.SCHEDULER_STATS,
                data=stats,
            )
        )

    async def emit_error(self, error: str, context: dict[str, Any] | None = None):
        """Emit error event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.ERROR,
                data={"error": error, "context": context or {}},
            )
        )

    @property
    def client_count(self) -> int:
        """Return the number of connected clients."""
        return len(self._clients)

    # =========================================================================
    # Deliberation event emission methods
    # =========================================================================

    async def emit_deliberation_started(
        self,
        task_id: str,
        question: str,
        agents: list,
        total_rounds: int,
    ):
        """Emit deliberation started event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.DELIBERATION_STARTED,
                data={
                    "task_id": task_id,
                    "question_preview": question[:200] if question else "",
                    "agents": agents,
                    "total_rounds": total_rounds,
                },
            )
        )

    async def emit_deliberation_round(
        self,
        task_id: str,
        round_num: int,
        total_rounds: int,
        phase: str = "active",
    ):
        """Emit deliberation round progress event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.DELIBERATION_ROUND,
                data={
                    "task_id": task_id,
                    "round": round_num,
                    "total_rounds": total_rounds,
                    "phase": phase,
                    "progress_pct": (round_num / total_rounds * 100) if total_rounds > 0 else 0,
                },
            )
        )

    async def emit_deliberation_progress(
        self,
        task_id: str,
        event_type: str,
        data: dict[str, Any],
    ):
        """Emit general deliberation progress event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.DELIBERATION_PROGRESS,
                data={
                    "task_id": task_id,
                    "deliberation_event": event_type,
                    **data,
                },
            )
        )

    async def emit_deliberation_vote(
        self,
        task_id: str,
        agent: str,
        choice: str,
        confidence: float,
    ):
        """Emit deliberation vote event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.DELIBERATION_VOTE,
                data={
                    "task_id": task_id,
                    "agent": agent,
                    "choice": choice,
                    "confidence": confidence,
                },
            )
        )

    async def emit_deliberation_consensus(
        self,
        task_id: str,
        reached: bool,
        confidence: float,
        vote_distribution: dict[str, int],
    ):
        """Emit deliberation consensus event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.DELIBERATION_CONSENSUS,
                data={
                    "task_id": task_id,
                    "reached": reached,
                    "confidence": confidence,
                    "vote_distribution": vote_distribution,
                },
            )
        )

    async def emit_deliberation_completed(
        self,
        task_id: str,
        success: bool,
        consensus_reached: bool,
        confidence: float,
        duration_seconds: float,
        winner: str | None = None,
    ):
        """Emit deliberation completed event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.DELIBERATION_COMPLETED,
                data={
                    "task_id": task_id,
                    "success": success,
                    "consensus_reached": consensus_reached,
                    "confidence": confidence,
                    "duration_seconds": duration_seconds,
                    "winner": winner,
                },
            )
        )

    async def emit_deliberation_failed(
        self,
        task_id: str,
        error: str,
        duration_seconds: float,
    ):
        """Emit deliberation failed event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.DELIBERATION_FAILED,
                data={
                    "task_id": task_id,
                    "error": error,
                    "duration_seconds": duration_seconds,
                },
            )
        )

    async def emit_deliberation_sla_warning(
        self,
        task_id: str,
        elapsed_seconds: float,
        timeout_seconds: float,
        level: str = "warning",
    ):
        """Emit deliberation SLA warning event."""
        await self.broadcast(
            ControlPlaneEvent(
                event_type=ControlPlaneEventType.DELIBERATION_SLA_WARNING,
                data={
                    "task_id": task_id,
                    "elapsed_seconds": elapsed_seconds,
                    "timeout_seconds": timeout_seconds,
                    "remaining_seconds": timeout_seconds - elapsed_seconds,
                    "level": level,
                },
            )
        )
