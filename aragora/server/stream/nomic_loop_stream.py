"""
WebSocket stream server for Nomic Loop events.

Provides real-time streaming of Nomic Loop events to connected clients:
- Loop lifecycle events (started, paused, resumed, stopped)
- Phase transitions (context, debate, design, implement, verify)
- Cycle events (started, completed)
- Proposal events (generated, approved, rejected)
- Health and status updates

Usage:
    from aragora.server.stream.nomic_loop_stream import NomicLoopStreamServer

    server = NomicLoopStreamServer(port=8767)
    await server.start()

    # Emit events from the Nomic handler
    await server.emit_loop_started(cycles=3, auto_approve=False)
    await server.emit_phase_changed(old_phase="context", new_phase="debate")
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


class NomicLoopEventType(Enum):
    """Types of Nomic Loop events."""

    # Connection events
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"

    # Loop lifecycle events
    LOOP_STARTED = "loop_started"
    LOOP_PAUSED = "loop_paused"
    LOOP_RESUMED = "loop_resumed"
    LOOP_STOPPED = "loop_stopped"

    # Phase events
    PHASE_STARTED = "phase_started"
    PHASE_COMPLETED = "phase_completed"
    PHASE_SKIPPED = "phase_skipped"
    PHASE_FAILED = "phase_failed"

    # Cycle events
    CYCLE_STARTED = "cycle_started"
    CYCLE_COMPLETED = "cycle_completed"

    # Proposal events
    PROPOSAL_GENERATED = "proposal_generated"
    PROPOSAL_APPROVED = "proposal_approved"
    PROPOSAL_REJECTED = "proposal_rejected"

    # Health events
    HEALTH_UPDATE = "health_update"
    STALL_DETECTED = "stall_detected"
    STALL_RESOLVED = "stall_resolved"

    # Log events
    LOG_MESSAGE = "log_message"

    # Error events
    ERROR = "error"


@dataclass
class NomicLoopEvent:
    """Event emitted by the Nomic Loop."""

    event_type: NomicLoopEventType
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


class NomicLoopStreamServer:
    """
    WebSocket server for streaming Nomic Loop events.

    Manages WebSocket connections and broadcasts Nomic Loop events
    to all connected clients in real-time.
    """

    def __init__(self, port: int = 8767, host: str = "0.0.0.0"):  # noqa: S104 - WS server binds all interfaces by default
        """Initialize the Nomic Loop stream server.

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
        logger.info("Nomic Loop stream server started on ws://%s:%s", self.host, self.port)

    async def stop(self):
        """Stop the WebSocket server."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Nomic Loop stream server stopped")

    async def _handle_connection(self, websocket):
        """Handle a new WebSocket connection.

        Args:
            websocket: The WebSocket connection
        """
        # Get path from websocket (websockets v15+ API)
        path = getattr(websocket, "path", getattr(websocket, "request", None))
        if hasattr(path, "path"):
            path = path.path
        path = path or "/api/nomic/stream"

        # Accept connections to /api/nomic/stream or /ws/nomic
        if path not in ("/api/nomic/stream", "/ws/nomic"):
            await websocket.close(1003, "Invalid path")
            return

        await self._register_client(websocket)
        try:
            # Send connection confirmation
            await websocket.send(
                NomicLoopEvent(
                    event_type=NomicLoopEventType.CONNECTED,
                    data={"message": "Connected to Nomic Loop stream"},
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
            logger.debug("Nomic client connected. Total clients: %s", len(self._clients))

    async def _unregister_client(self, websocket):
        """Unregister a client connection."""
        async with self._lock:
            self._clients.discard(websocket)
            logger.debug("Nomic client disconnected. Total clients: %s", len(self._clients))

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

    async def broadcast(self, event: NomicLoopEvent):
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

    async def emit_loop_started(
        self,
        cycles: int = 1,
        auto_approve: bool = False,
        dry_run: bool = False,
    ):
        """Emit loop started event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.LOOP_STARTED,
                data={
                    "cycles": cycles,
                    "auto_approve": auto_approve,
                    "dry_run": dry_run,
                },
            )
        )

    async def emit_loop_paused(self, current_phase: str, current_cycle: int):
        """Emit loop paused event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.LOOP_PAUSED,
                data={
                    "current_phase": current_phase,
                    "current_cycle": current_cycle,
                },
            )
        )

    async def emit_loop_resumed(self, current_phase: str, current_cycle: int):
        """Emit loop resumed event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.LOOP_RESUMED,
                data={
                    "current_phase": current_phase,
                    "current_cycle": current_cycle,
                },
            )
        )

    async def emit_loop_stopped(self, forced: bool = False, reason: str = ""):
        """Emit loop stopped event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.LOOP_STOPPED,
                data={
                    "forced": forced,
                    "reason": reason,
                },
            )
        )

    async def emit_phase_started(
        self,
        phase: str,
        cycle: int,
        estimated_duration_sec: int | None = None,
    ):
        """Emit phase started event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.PHASE_STARTED,
                data={
                    "phase": phase,
                    "cycle": cycle,
                    "estimated_duration_sec": estimated_duration_sec,
                },
            )
        )

    async def emit_phase_completed(
        self,
        phase: str,
        cycle: int,
        duration_sec: float,
        result_summary: str | None = None,
    ):
        """Emit phase completed event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.PHASE_COMPLETED,
                data={
                    "phase": phase,
                    "cycle": cycle,
                    "duration_sec": duration_sec,
                    "result_summary": result_summary,
                },
            )
        )

    async def emit_phase_skipped(self, phase: str, cycle: int, reason: str = ""):
        """Emit phase skipped event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.PHASE_SKIPPED,
                data={
                    "phase": phase,
                    "cycle": cycle,
                    "reason": reason,
                },
            )
        )

    async def emit_phase_failed(self, phase: str, cycle: int, error: str):
        """Emit phase failed event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.PHASE_FAILED,
                data={
                    "phase": phase,
                    "cycle": cycle,
                    "error": error,
                },
            )
        )

    async def emit_cycle_started(self, cycle: int, total_cycles: int):
        """Emit cycle started event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.CYCLE_STARTED,
                data={
                    "cycle": cycle,
                    "total_cycles": total_cycles,
                },
            )
        )

    async def emit_cycle_completed(
        self,
        cycle: int,
        total_cycles: int,
        duration_sec: float,
        improvements_made: int = 0,
    ):
        """Emit cycle completed event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.CYCLE_COMPLETED,
                data={
                    "cycle": cycle,
                    "total_cycles": total_cycles,
                    "duration_sec": duration_sec,
                    "improvements_made": improvements_made,
                },
            )
        )

    async def emit_proposal_generated(
        self,
        proposal_id: str,
        title: str,
        description: str,
        phase: str,
        requires_approval: bool = True,
    ):
        """Emit proposal generated event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.PROPOSAL_GENERATED,
                data={
                    "proposal_id": proposal_id,
                    "title": title,
                    "description": description[:500],  # Truncate for broadcast
                    "phase": phase,
                    "requires_approval": requires_approval,
                },
            )
        )

    async def emit_proposal_approved(self, proposal_id: str, approved_by: str = "user"):
        """Emit proposal approved event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.PROPOSAL_APPROVED,
                data={
                    "proposal_id": proposal_id,
                    "approved_by": approved_by,
                },
            )
        )

    async def emit_proposal_rejected(
        self, proposal_id: str, rejected_by: str = "user", reason: str = ""
    ):
        """Emit proposal rejected event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.PROPOSAL_REJECTED,
                data={
                    "proposal_id": proposal_id,
                    "rejected_by": rejected_by,
                    "reason": reason,
                },
            )
        )

    async def emit_health_update(
        self,
        status: str,
        running: bool,
        paused: bool,
        current_phase: str | None = None,
        current_cycle: int | None = None,
        stalled: bool = False,
    ):
        """Emit health update event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.HEALTH_UPDATE,
                data={
                    "status": status,
                    "running": running,
                    "paused": paused,
                    "current_phase": current_phase,
                    "current_cycle": current_cycle,
                    "stalled": stalled,
                },
            )
        )

    async def emit_stall_detected(
        self,
        phase: str,
        stall_duration_sec: float,
        threshold_sec: float,
    ):
        """Emit stall detected event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.STALL_DETECTED,
                data={
                    "phase": phase,
                    "stall_duration_sec": stall_duration_sec,
                    "threshold_sec": threshold_sec,
                },
            )
        )

    async def emit_stall_resolved(self, phase: str, resolution: str = ""):
        """Emit stall resolved event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.STALL_RESOLVED,
                data={
                    "phase": phase,
                    "resolution": resolution,
                },
            )
        )

    async def emit_log_message(self, level: str, message: str, source: str = "nomic"):
        """Emit log message event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.LOG_MESSAGE,
                data={
                    "level": level,
                    "message": message[:1000],  # Truncate long messages
                    "source": source,
                },
            )
        )

    async def emit_error(self, error: str, context: dict[str, Any] | None = None):
        """Emit error event."""
        await self.broadcast(
            NomicLoopEvent(
                event_type=NomicLoopEventType.ERROR,
                data={"error": error, "context": context or {}},
            )
        )

    @property
    def client_count(self) -> int:
        """Return the number of connected clients."""
        return len(self._clients)
