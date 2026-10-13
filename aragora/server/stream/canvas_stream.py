"""
WebSocket stream server for Live Canvas.

Provides real-time bidirectional communication for canvas operations:
- Canvas state synchronization
- Node and edge CRUD operations
- User selections and cursors
- Action execution (debates, workflows, queries)
- Collaborative editing

Usage:
    from aragora.server.stream.canvas_stream import CanvasStreamServer

    server = CanvasStreamServer(port=8767)
    await server.start()

    # Or integrate with unified server:
    await server.handle_connection(websocket, canvas_id)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class CanvasStreamServer:
    """
    WebSocket server for Live Canvas real-time collaboration.

    Manages WebSocket connections and handles canvas operations
    with real-time broadcasting to all connected clients.
    """

    # WS server binds all interfaces by default
    def __init__(self, port: int = 8767, host: str = "0.0.0.0"):
        """
        Initialize the canvas stream server.

        Args:
            port: Port to listen on (standalone mode)
            host: Host to bind to
        """
        self.port = port
        self.host = host
        self._clients: dict[str, set[Any]] = {}  # canvas_id -> websockets
        self._user_info: dict[Any, dict[str, Any]] = {}  # websocket -> user info
        self._lock = asyncio.Lock()
        self._running = False
        self._server: Any | None = None
        self._manager: Any | None = None

    def _get_manager(self) -> Any:
        """Get or create the canvas state manager."""
        if self._manager is None:
            from aragora.canvas import get_canvas_manager

            self._manager = get_canvas_manager()
        return self._manager

    async def start(self):
        """Start the WebSocket server (standalone mode)."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed. Run: pip install websockets")
            return

        self._running = True
        self._server = await websockets.serve(
            self._handle_standalone_connection,
            self.host,
            self.port,
            ping_interval=30,
            ping_timeout=10,
        )
        logger.info("Canvas stream server started on ws://%s:%s", self.host, self.port)

    async def stop(self):
        """Stop the WebSocket server."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Canvas stream server stopped")

    async def _handle_standalone_connection(self, websocket):
        """Handle a new WebSocket connection in standalone mode."""
        # Get path from websocket
        path = getattr(websocket, "path", getattr(websocket, "request", None))
        if hasattr(path, "path"):
            path = path.path
        path = path or "/"

        # Extract canvas_id from path: /ws/canvas/{canvas_id}
        if path.startswith("/ws/canvas/"):
            canvas_id = path[len("/ws/canvas/") :]
        else:
            await websocket.close(1003, "Invalid path. Use /ws/canvas/{canvas_id}")
            return

        await self.handle_connection(websocket, canvas_id)

    async def handle_connection(
        self,
        websocket: Any,
        canvas_id: str,
        user_id: str | None = None,
    ):
        """
        Handle a WebSocket connection for a canvas.

        This can be called from the standalone server or integrated
        into the unified server's WebSocket routing.

        Args:
            websocket: The WebSocket connection
            canvas_id: ID of the canvas to connect to
            user_id: Optional user ID for the connection
        """
        manager = self._get_manager()

        # Store user info
        self._user_info[websocket] = {
            "user_id": user_id or f"anonymous_{id(websocket)}",
            "canvas_id": canvas_id,
            "connected_at": time.time(),
        }

        # Register client for this canvas
        await self._register_client(canvas_id, websocket)

        # Ensure canvas exists
        await manager.get_or_create_canvas(canvas_id)

        try:
            # Send initial state
            state = await manager.get_state(canvas_id)
            await self._send_message(
                websocket,
                {
                    "type": "canvas:state",
                    "canvas_id": canvas_id,
                    "data": state,
                    "timestamp": time.time(),
                },
            )

            # Subscribe to canvas events
            async def event_handler(event):
                await self._send_event_to_client(websocket, event)

            await manager.subscribe(canvas_id, event_handler)

            # Handle incoming messages
            async for message in websocket:
                await self._handle_message(websocket, message)

        except (ConnectionError, asyncio.CancelledError) as e:
            logger.warning("Canvas WebSocket error: %s", e)
        finally:
            # Cleanup
            await self._unregister_client(canvas_id, websocket)
            if websocket in self._user_info:
                del self._user_info[websocket]

    async def _register_client(self, canvas_id: str, websocket):
        """Register a client for a canvas."""
        async with self._lock:
            if canvas_id not in self._clients:
                self._clients[canvas_id] = set()
            self._clients[canvas_id].add(websocket)
            logger.debug(
                "Client connected to canvas %s. Total clients: %s",
                canvas_id,
                len(self._clients[canvas_id]),
            )

    async def _unregister_client(self, canvas_id: str, websocket):
        """Unregister a client from a canvas."""
        async with self._lock:
            if canvas_id in self._clients:
                self._clients[canvas_id].discard(websocket)
                if not self._clients[canvas_id]:
                    del self._clients[canvas_id]
            logger.debug("Client disconnected from canvas %s", canvas_id)

    async def _handle_message(self, websocket, message: str):
        """
        Handle an incoming message from a client.

        Args:
            websocket: The WebSocket connection
            message: The received message (JSON string)
        """
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            await self._send_error(websocket, "Invalid JSON")
            return

        msg_type = data.get("type", "")
        user_info = self._user_info.get(websocket, {})
        canvas_id = user_info.get("canvas_id")
        user_id = user_info.get("user_id")

        if not canvas_id:
            await self._send_error(websocket, "Not connected to a canvas")
            return

        if not user_id:
            await self._send_error(websocket, "User ID not available")
            return

        # Type narrowing: canvas_id and user_id are now confirmed to be strings
        canvas_id = str(canvas_id)
        user_id = str(user_id)

        manager = self._get_manager()

        # Route message to appropriate handler
        try:
            if msg_type == "ping":
                await self._send_message(
                    websocket,
                    {"type": "pong", "timestamp": time.time()},
                )

            elif msg_type == "canvas:sync":
                await manager.sync_state(canvas_id, user_id)

            elif msg_type == "canvas:node:create":
                await self._handle_node_create(manager, canvas_id, user_id, data)

            elif msg_type == "canvas:node:update":
                await self._handle_node_update(manager, canvas_id, user_id, data)

            elif msg_type == "canvas:node:move":
                await self._handle_node_move(manager, canvas_id, user_id, data)

            elif msg_type == "canvas:node:resize":
                await self._handle_node_resize(manager, canvas_id, user_id, data)

            elif msg_type == "canvas:node:delete":
                await self._handle_node_delete(manager, canvas_id, user_id, data)

            elif msg_type == "canvas:node:select":
                await self._handle_node_select(manager, canvas_id, user_id, data)

            elif msg_type == "canvas:edge:create":
                await self._handle_edge_create(manager, canvas_id, user_id, data)

            elif msg_type == "canvas:edge:update":
                await self._handle_edge_update(manager, canvas_id, user_id, data)

            elif msg_type == "canvas:edge:delete":
                await self._handle_edge_delete(manager, canvas_id, user_id, data)

            elif msg_type == "canvas:action":
                await self._handle_action(manager, canvas_id, user_id, data)

            elif msg_type == "ideas:cursor:move":
                await self._handle_idea_cursor_move(canvas_id, user_id, data)

            elif msg_type == "ideas:presence:join":
                await self._handle_idea_presence(canvas_id, user_id, "join")

            elif msg_type == "ideas:presence:leave":
                await self._handle_idea_presence(canvas_id, user_id, "leave")

            elif msg_type == "ideas:node:lock":
                await self._handle_idea_node_lock(canvas_id, user_id, data, lock=True)

            elif msg_type == "ideas:node:unlock":
                await self._handle_idea_node_lock(canvas_id, user_id, data, lock=False)

            elif msg_type == "goals:cursor:move":
                await self._handle_goal_cursor_move(canvas_id, user_id, data)

            elif msg_type == "goals:presence:join":
                await self._handle_goal_presence(canvas_id, user_id, "join")

            elif msg_type == "goals:presence:leave":
                await self._handle_goal_presence(canvas_id, user_id, "leave")

            elif msg_type == "goals:node:lock":
                await self._handle_goal_node_lock(canvas_id, user_id, data, lock=True)

            elif msg_type == "goals:node:unlock":
                await self._handle_goal_node_lock(canvas_id, user_id, data, lock=False)

            else:
                logger.debug("Unknown message type: %s", msg_type)

        except (ValueError, KeyError, TypeError) as e:
            logger.error("Error handling canvas message: %s", e)
            await self._send_error(websocket, "Failed to process canvas operation")

    async def _handle_node_create(
        self,
        manager,
        canvas_id: str,
        user_id: str,
        data: dict[str, Any],
    ):
        """Handle node creation."""
        from aragora.canvas import CanvasNodeType, Position

        node_data = data.get("node", {})
        node_type = CanvasNodeType(node_data.get("type", "text"))
        position = Position.from_dict(node_data.get("position", {}))

        await manager.add_node(
            canvas_id=canvas_id,
            node_type=node_type,
            position=position,
            label=node_data.get("label", ""),
            data=node_data.get("data", {}),
            user_id=user_id,
        )

    async def _handle_node_update(
        self,
        manager,
        canvas_id: str,
        user_id: str,
        data: dict[str, Any],
    ):
        """Handle node update."""
        node_id = data.get("node_id")
        updates = data.get("updates", {})

        if node_id:
            await manager.update_node(
                canvas_id=canvas_id,
                node_id=node_id,
                user_id=user_id,
                **updates,
            )

    async def _handle_node_move(
        self,
        manager,
        canvas_id: str,
        user_id: str,
        data: dict[str, Any],
    ):
        """Handle node move."""
        node_id = data.get("node_id")
        position = data.get("position", {})

        if node_id:
            await manager.move_node(
                canvas_id=canvas_id,
                node_id=node_id,
                x=position.get("x", 0),
                y=position.get("y", 0),
                user_id=user_id,
            )

    async def _handle_node_resize(
        self,
        manager,
        canvas_id: str,
        user_id: str,
        data: dict[str, Any],
    ):
        """Handle node resize."""
        node_id = data.get("node_id")
        size = data.get("size", {})

        if node_id:
            await manager.resize_node(
                canvas_id=canvas_id,
                node_id=node_id,
                width=size.get("width", 200),
                height=size.get("height", 100),
                user_id=user_id,
            )

    async def _handle_node_delete(
        self,
        manager,
        canvas_id: str,
        user_id: str,
        data: dict[str, Any],
    ):
        """Handle node deletion."""
        node_id = data.get("node_id")

        if node_id:
            await manager.delete_node(
                canvas_id=canvas_id,
                node_id=node_id,
                user_id=user_id,
            )

    async def _handle_node_select(
        self,
        manager,
        canvas_id: str,
        user_id: str,
        data: dict[str, Any],
    ):
        """Handle node selection."""
        node_id = data.get("node_id")
        multi_select = data.get("multi_select", False)

        if node_id:
            await manager.select_node(
                canvas_id=canvas_id,
                node_id=node_id,
                user_id=user_id,
                multi_select=multi_select,
            )

    async def _handle_edge_create(
        self,
        manager,
        canvas_id: str,
        user_id: str,
        data: dict[str, Any],
    ):
        """Handle edge creation."""
        from aragora.canvas import EdgeType

        source_id = data.get("source") or data.get("source_id")
        target_id = data.get("target") or data.get("target_id")
        edge_type = EdgeType(data.get("edge_type", "default"))

        if source_id and target_id:
            await manager.add_edge(
                canvas_id=canvas_id,
                source_id=source_id,
                target_id=target_id,
                edge_type=edge_type,
                label=data.get("label", ""),
                user_id=user_id,
            )

    async def _handle_edge_update(
        self,
        manager,
        canvas_id: str,
        user_id: str,
        data: dict[str, Any],
    ):
        """Handle edge update."""
        edge_id = data.get("edge_id")
        updates = data.get("updates", {})

        if edge_id:
            await manager.update_edge(
                canvas_id=canvas_id,
                edge_id=edge_id,
                user_id=user_id,
                **updates,
            )

    async def _handle_edge_delete(
        self,
        manager,
        canvas_id: str,
        user_id: str,
        data: dict[str, Any],
    ):
        """Handle edge deletion."""
        edge_id = data.get("edge_id")

        if edge_id:
            await manager.delete_edge(
                canvas_id=canvas_id,
                edge_id=edge_id,
                user_id=user_id,
            )

    async def _handle_action(
        self,
        manager,
        canvas_id: str,
        user_id: str,
        data: dict[str, Any],
    ):
        """Handle canvas action execution."""
        action = data.get("action")
        params = data.get("params", {})

        if action:
            await manager.execute_action(
                canvas_id=canvas_id,
                action=action,
                params=params,
                user_id=user_id,
            )

    # =========================================================================
    # Idea Canvas collaboration handlers
    # =========================================================================

    async def _handle_idea_cursor_move(self, canvas_id: str, user_id: str, data: dict[str, Any]):
        """Broadcast cursor position to other clients (fire-and-forget)."""
        await self.broadcast_to_canvas(
            canvas_id,
            {
                "type": "ideas:cursor:move",
                "canvas_id": canvas_id,
                "user_id": user_id,
                "position": data.get("position", {}),
                "timestamp": time.time(),
            },
        )

    async def _handle_idea_presence(self, canvas_id: str, user_id: str, action: str):
        """Broadcast presence join/leave events."""
        await self.broadcast_to_canvas(
            canvas_id,
            {
                "type": f"ideas:presence:{action}",
                "canvas_id": canvas_id,
                "user_id": user_id,
                "users": [u["user_id"] for u in self.get_connected_users(canvas_id)],
                "timestamp": time.time(),
            },
        )

    async def _handle_idea_node_lock(
        self,
        canvas_id: str,
        user_id: str,
        data: dict[str, Any],
        *,
        lock: bool,
    ):
        """Broadcast advisory node lock/unlock."""
        node_id = data.get("node_id")
        if not node_id:
            return
        event_type = "ideas:node:lock" if lock else "ideas:node:unlock"
        await self.broadcast_to_canvas(
            canvas_id,
            {
                "type": event_type,
                "canvas_id": canvas_id,
                "user_id": user_id,
                "node_id": node_id,
                "timestamp": time.time(),
            },
        )

    # =========================================================================
    # Goal Canvas collaboration handlers
    # =========================================================================

    async def _handle_goal_cursor_move(self, canvas_id: str, user_id: str, data: dict[str, Any]):
        """Broadcast cursor position to other clients (fire-and-forget)."""
        await self.broadcast_to_canvas(
            canvas_id,
            {
                "type": "goals:cursor:move",
                "canvas_id": canvas_id,
                "user_id": user_id,
                "position": data.get("position", {}),
                "timestamp": time.time(),
            },
        )

    async def _handle_goal_presence(self, canvas_id: str, user_id: str, action: str):
        """Broadcast presence join/leave events."""
        await self.broadcast_to_canvas(
            canvas_id,
            {
                "type": f"goals:presence:{action}",
                "canvas_id": canvas_id,
                "user_id": user_id,
                "users": [u["user_id"] for u in self.get_connected_users(canvas_id)],
                "timestamp": time.time(),
            },
        )

    async def _handle_goal_node_lock(
        self,
        canvas_id: str,
        user_id: str,
        data: dict[str, Any],
        *,
        lock: bool,
    ):
        """Broadcast advisory node lock/unlock."""
        node_id = data.get("node_id")
        if not node_id:
            return
        event_type = "goals:node:lock" if lock else "goals:node:unlock"
        await self.broadcast_to_canvas(
            canvas_id,
            {
                "type": event_type,
                "canvas_id": canvas_id,
                "user_id": user_id,
                "node_id": node_id,
                "timestamp": time.time(),
            },
        )

    async def _send_message(self, websocket, message: dict[str, Any]):
        """Send a message to a client."""
        try:
            await websocket.send(json.dumps(message))
        except (ConnectionError, OSError) as e:
            logger.debug("Failed to send message: %s", e)

    async def _send_error(self, websocket, error: str):
        """Send an error message to a client."""
        await self._send_message(
            websocket,
            {
                "type": "canvas:error",
                "error": error,
                "timestamp": time.time(),
            },
        )

    async def _send_event_to_client(self, websocket, event):
        """Send a canvas event to a client."""
        try:
            await websocket.send(json.dumps(event.to_dict()))
        except (ConnectionError, OSError) as e:
            logger.debug("Failed to send event: %s", e)

    async def broadcast_to_canvas(self, canvas_id: str, message: dict[str, Any]):
        """
        Broadcast a message to all clients connected to a canvas.

        Args:
            canvas_id: The canvas ID
            message: The message to broadcast
        """
        async with self._lock:
            clients = list(self._clients.get(canvas_id, set()))

        if clients:
            msg_json = json.dumps(message)
            await asyncio.gather(
                *[self._send_to_client(client, msg_json) for client in clients],
                return_exceptions=True,
            )

    async def _send_to_client(self, websocket, message: str):
        """Send a message string to a client."""
        try:
            await websocket.send(message)
        except (ConnectionError, OSError) as e:
            logger.debug("Failed to send to client: %s", e)

    def get_connected_users(self, canvas_id: str) -> list[dict[str, Any]]:
        """Get list of users connected to a canvas."""
        clients = self._clients.get(canvas_id, set())
        users = []
        for client in clients:
            user_info = self._user_info.get(client)
            if user_info:
                users.append(
                    {
                        "user_id": user_info.get("user_id"),
                        "connected_at": user_info.get("connected_at"),
                    }
                )
        return users


# Global server instance
_canvas_server: CanvasStreamServer | None = None


def get_canvas_stream_server() -> CanvasStreamServer:
    """Get or create the global canvas stream server."""
    global _canvas_server
    if _canvas_server is None:
        _canvas_server = CanvasStreamServer()
    return _canvas_server


__all__ = [
    "CanvasStreamServer",
    "get_canvas_stream_server",
]
