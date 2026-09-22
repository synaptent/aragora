"""
Base class for WebSocket/HTTP servers.

Provides common functionality shared between DebateStreamServer and AiohttpUnifiedServer:
- Client management (WebSocket connections)
- Rate limiting with TTL-based cleanup
- Debate state caching
- Active loops tracking
- Event subscription management

Usage:
    class MyServer(ServerBase):
        def __init__(self, ...):
            super().__init__(emitter)
            # Add server-specific initialization
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .emitter import AudienceInbox, SyncEventEmitter, TokenBucket
from .state_manager import LoopInstance

if TYPE_CHECKING:
    from .events import StreamEvent

logger = logging.getLogger(__name__)

# Token revalidation interval for long-lived WebSocket connections (5 minutes)
WS_TOKEN_REVALIDATION_INTERVAL = 300.0


@dataclass
class ServerConfig:
    """Configuration for server behavior."""

    # Rate limiter settings
    rate_limiter_ttl: float = 3600.0  # 1 hour TTL for rate limiters
    rate_limiter_cleanup_interval: int = 100  # Cleanup every N accesses

    # Debate state settings
    debate_states_ttl: float = 3600.0  # 1 hour TTL for ended debates
    max_debate_states: int = 500  # Max cached states

    # Active loops settings
    active_loops_ttl: float = 86400.0  # 24 hour TTL for stale loops
    max_active_loops: int = 1000  # Max concurrent loops

    # Client tracking
    max_client_ids: int = 10000  # Max tracked clients


class ServerBase:
    """
    Base class providing common server functionality.

    Lock Hierarchy (acquire in this order to prevent deadlocks):
    ---------------------------------------------------------------
    1. _rate_limiters_lock   - Protects _rate_limiters and _rate_limiter_last_access
    2. _debate_states_lock   - Protects debate_states and _debate_states_last_access
    3. _active_loops_lock    - Protects active_loops and _active_loops_last_access

    IMPORTANT: Each method should only acquire ONE lock at a time. If multiple
    locks must be acquired (e.g., in cleanup methods), acquire them sequentially
    in the order above, releasing each before acquiring the next. Never nest
    lock acquisitions to prevent deadlocks.
    """

    def __init__(
        self,
        emitter: SyncEventEmitter | None = None,
        config: ServerConfig | None = None,
    ):
        """
        Initialize the server base.

        Args:
            emitter: Event emitter for debate events. Creates new one if not provided.
            config: Server configuration. Uses defaults if not provided.
        """
        self._config = config or ServerConfig()

        # WebSocket clients and event emitter
        self.clients: set[Any] = set()
        self._emitter = emitter or SyncEventEmitter()
        self._running = False

        # Audience participation - Lock hierarchy level 1 (acquire first)
        self.audience_inbox = AudienceInbox()
        self._rate_limiters: dict[str, TokenBucket] = {}
        self._rate_limiter_last_access: dict[str, float] = {}
        self._rate_limiters_lock = threading.Lock()  # Lock #1 in hierarchy
        self._rate_limiter_cleanup_counter = 0

        # Debate state caching - Lock hierarchy level 2
        self.debate_states: dict[str, dict] = {}
        self._debate_states_lock = threading.Lock()  # Lock #2 in hierarchy
        self._debate_states_last_access: dict[str, float] = {}

        # Multi-loop tracking - Lock hierarchy level 3
        self.active_loops: dict[str, LoopInstance] = {}
        self._active_loops_lock = threading.Lock()  # Lock #3 in hierarchy
        self._active_loops_last_access: dict[str, float] = {}

        # Secure client ID mapping with LRU eviction
        self._client_ids: OrderedDict[int, str] = OrderedDict()

        # WebSocket authentication tracking - Lock hierarchy level 4 (acquire last)
        self._ws_auth_states: dict[int, dict[str, Any]] = {}  # ws_id -> auth state
        self._ws_auth_lock = threading.Lock()  # Lock #4 in hierarchy

        # Subscribe to emitter to maintain debate states
        self._emitter.subscribe(self._update_debate_state)

    @property
    def emitter(self) -> SyncEventEmitter:
        """Get the event emitter."""
        return self._emitter

    @property
    def config(self) -> ServerConfig:
        """Get the server configuration."""
        return self._config

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    def get_rate_limiter(
        self,
        client_id: str,
        rate: float = 10.0,
        capacity: float = 30.0,
    ) -> TokenBucket:
        """
        Get or create a rate limiter for a client.

        Thread-safe with cleanup of stale rate limiters.
        """
        now = time.time()

        with self._rate_limiters_lock:
            # Periodic cleanup
            self._rate_limiter_cleanup_counter += 1
            if self._rate_limiter_cleanup_counter >= self._config.rate_limiter_cleanup_interval:
                self._rate_limiter_cleanup_counter = 0
                self._cleanup_rate_limiters_unsafe(now)

            # Get or create
            self._rate_limiter_last_access[client_id] = now
            if client_id not in self._rate_limiters:
                self._rate_limiters[client_id] = TokenBucket(
                    rate_per_minute=rate, burst_size=int(capacity)
                )

            return self._rate_limiters[client_id]

    def _cleanup_rate_limiters_unsafe(self, now: float) -> int:
        """
        Clean up stale rate limiters. Must be called with _rate_limiters_lock held.

        Returns number of items removed.
        """
        cutoff = now - self._config.rate_limiter_ttl
        stale_keys = [k for k, v in self._rate_limiter_last_access.items() if v < cutoff]
        for k in stale_keys:
            self._rate_limiters.pop(k, None)
            self._rate_limiter_last_access.pop(k, None)

        if stale_keys:
            logger.debug("Cleaned up %s stale rate limiters", len(stale_keys))

        return len(stale_keys)

    def cleanup_rate_limiters(self) -> int:
        """Clean up stale rate limiters. Thread-safe."""
        with self._rate_limiters_lock:
            return self._cleanup_rate_limiters_unsafe(time.time())

    # =========================================================================
    # Debate State Caching
    # =========================================================================

    def get_debate_state(self, loop_id: str) -> dict | None:
        """Get cached debate state for a loop."""
        with self._debate_states_lock:
            self._debate_states_last_access[loop_id] = time.time()
            return self.debate_states.get(loop_id)

    def set_debate_state(self, loop_id: str, state: dict) -> None:
        """Set debate state for a loop."""
        now = time.time()

        with self._debate_states_lock:
            # Enforce max states limit
            if len(self.debate_states) >= self._config.max_debate_states:
                self._evict_oldest_debate_state_unsafe()

            self.debate_states[loop_id] = state
            self._debate_states_last_access[loop_id] = now

    def _evict_oldest_debate_state_unsafe(self) -> str | None:
        """
        Evict the oldest debate state. Must be called with _debate_states_lock held.

        Returns the evicted loop_id or None.
        """
        if not self._debate_states_last_access:
            return None

        oldest = min(
            self._debate_states_last_access,
            key=lambda k: self._debate_states_last_access.get(k, 0.0),
        )
        self.debate_states.pop(oldest, None)
        self._debate_states_last_access.pop(oldest, None)
        return oldest

    def cleanup_debate_states(self) -> int:
        """Clean up stale debate states. Thread-safe."""
        now = time.time()
        cutoff = now - self._config.debate_states_ttl

        with self._debate_states_lock:
            stale_keys = [k for k, v in self._debate_states_last_access.items() if v < cutoff]
            for k in stale_keys:
                self.debate_states.pop(k, None)
                self._debate_states_last_access.pop(k, None)

        if stale_keys:
            logger.debug("Cleaned up %s stale debate states", len(stale_keys))

        return len(stale_keys)

    def _update_debate_state(self, event: StreamEvent) -> None:
        """
        Subscriber callback to update debate state from events.

        This is called by the emitter when events are published.
        Override in subclasses for custom state handling.

        Note: The event parameter is a StreamEvent dataclass, not a dict.
        Access fields via attributes (event.loop_id) and nested data via event.data.
        """
        # Import here to avoid circular imports
        from aragora.events.types import StreamEventType

        # Handle both StreamEvent objects and dicts (for backwards compatibility)
        if isinstance(event, dict):
            loop_id = event.get("loop_id", "")
            event_type = event.get("type", "")
            event_data = event.get("data", {})
            event_agent = event.get("agent", "")
            event_round = event.get("round", 0)
        else:
            loop_id = event.loop_id
            event_type = (
                event.type.value if isinstance(event.type, StreamEventType) else str(event.type)
            )
            event_data = event.data or {}
            event_agent = event.agent
            event_round = event.round

        if not loop_id:
            return

        with self._debate_states_lock:
            if loop_id not in self.debate_states:
                self.debate_states[loop_id] = {
                    "loop_id": loop_id,
                    "status": "running",
                    "rounds": [],
                    "messages": [],
                    "current_round": 0,
                }

            state = self.debate_states[loop_id]
            self._debate_states_last_access[loop_id] = time.time()

            # Update state based on event type
            if event_type == "debate_start":
                state["task"] = event_data.get("task")
                state["agents"] = event_data.get("agents", [])
                state["status"] = "running"
            elif event_type == "round_start":
                state["current_round"] = event_round or event_data.get("round", 0)
            elif event_type == "agent_message":
                state["messages"].append(
                    {
                        "agent": event_agent,
                        "content": event_data.get("content", ""),  # Full content - never truncate
                        "role": event_data.get(
                            "role", "agent"
                        ),  # Preserve role for synthesis detection
                        "round": event_round,
                    }
                )
            elif event_type == "synthesis":
                # Add synthesis as a message with special role
                state["messages"].append(
                    {
                        "agent": event_agent or "synthesis-agent",
                        "content": event_data.get("content", ""),
                        "role": "synthesis",
                        "round": event_round,
                    }
                )
                state["synthesis"] = event_data.get("content", "")
            elif event_type in ("debate_end", "consensus_reached", "consensus"):
                state["status"] = "completed"
                state["result"] = event_data.get("result") or event_data.get("answer")
                state["ended"] = True
            elif event_type == "error":
                state["status"] = "error"
                state["error"] = event_data.get("error") or event_data.get("message")

    # =========================================================================
    # Active Loops Tracking
    # =========================================================================

    def get_active_loop(self, loop_id: str) -> LoopInstance | None:
        """Get an active loop instance."""
        with self._active_loops_lock:
            self._active_loops_last_access[loop_id] = time.time()
            return self.active_loops.get(loop_id)

    def set_active_loop(self, loop_id: str, instance: LoopInstance) -> None:
        """Set an active loop instance."""
        now = time.time()

        with self._active_loops_lock:
            # Enforce max loops limit
            if len(self.active_loops) >= self._config.max_active_loops:
                self._evict_oldest_loop_unsafe()

            self.active_loops[loop_id] = instance
            self._active_loops_last_access[loop_id] = now

    def remove_active_loop(self, loop_id: str) -> LoopInstance | None:
        """Remove an active loop instance."""
        with self._active_loops_lock:
            self._active_loops_last_access.pop(loop_id, None)
            return self.active_loops.pop(loop_id, None)

    def _evict_oldest_loop_unsafe(self) -> str | None:
        """
        Evict the oldest active loop. Must be called with _active_loops_lock held.

        Returns the evicted loop_id or None.
        """
        if not self._active_loops_last_access:
            return None

        oldest = min(
            self._active_loops_last_access, key=lambda k: self._active_loops_last_access.get(k, 0.0)
        )
        self.active_loops.pop(oldest, None)
        self._active_loops_last_access.pop(oldest, None)
        logger.warning("Evicted stale loop: %s", oldest)
        return oldest

    def cleanup_active_loops(self) -> int:
        """Clean up stale active loops. Thread-safe."""
        now = time.time()
        cutoff = now - self._config.active_loops_ttl

        with self._active_loops_lock:
            stale_keys = [k for k, v in self._active_loops_last_access.items() if v < cutoff]
            for k in stale_keys:
                self.active_loops.pop(k, None)
                self._active_loops_last_access.pop(k, None)

        if stale_keys:
            logger.info("Cleaned up %s stale active loops", len(stale_keys))

        return len(stale_keys)

    # =========================================================================
    # Client ID Management
    # =========================================================================

    def get_client_id(self, ws_id: int) -> str | None:
        """Get the secure client ID for a WebSocket connection."""
        return self._client_ids.get(ws_id)

    def set_client_id(self, ws_id: int, client_id: str) -> None:
        """Set the secure client ID for a WebSocket connection."""
        # Enforce max clients limit with LRU eviction
        while len(self._client_ids) >= self._config.max_client_ids:
            self._client_ids.popitem(last=False)

        self._client_ids[ws_id] = client_id
        # Move to end (most recently used)
        self._client_ids.move_to_end(ws_id)

    def remove_client_id(self, ws_id: int) -> str | None:
        """Remove and return the client ID for a WebSocket connection."""
        return self._client_ids.pop(ws_id, None)

    # =========================================================================
    # WebSocket Authentication Tracking
    # =========================================================================

    def set_ws_auth_state(
        self,
        ws_id: int,
        authenticated: bool,
        token: str | None = None,
        ip_address: str = "",
    ) -> None:
        """Set authentication state for a WebSocket connection.

        Args:
            ws_id: WebSocket connection ID (id(websocket))
            authenticated: Whether the connection is authenticated
            token: The authentication token (for revalidation)
            ip_address: Client IP address
        """
        with self._ws_auth_lock:
            self._ws_auth_states[ws_id] = {
                "authenticated": authenticated,
                "token": token,
                "ip_address": ip_address,
                "last_validated": time.time(),
                "created_at": time.time(),
            }

    def get_ws_auth_state(self, ws_id: int) -> dict[str, Any] | None:
        """Get authentication state for a WebSocket connection."""
        with self._ws_auth_lock:
            return self._ws_auth_states.get(ws_id)

    def is_ws_authenticated(self, ws_id: int) -> bool:
        """Check if a WebSocket connection is authenticated."""
        with self._ws_auth_lock:
            state = self._ws_auth_states.get(ws_id)
            return state.get("authenticated", False) if state else False

    def should_revalidate_ws_token(self, ws_id: int) -> bool:
        """Check if a WebSocket token should be revalidated.

        Args:
            ws_id: WebSocket connection ID

        Returns:
            True if token needs revalidation (older than WS_TOKEN_REVALIDATION_INTERVAL)
        """
        with self._ws_auth_lock:
            state = self._ws_auth_states.get(ws_id)
            if not state or not state.get("authenticated"):
                return False
            last_validated: float = state.get("last_validated", 0)
            return bool((time.time() - last_validated) > WS_TOKEN_REVALIDATION_INTERVAL)

    def mark_ws_token_validated(self, ws_id: int) -> None:
        """Mark a WebSocket token as recently validated."""
        with self._ws_auth_lock:
            if ws_id in self._ws_auth_states:
                self._ws_auth_states[ws_id]["last_validated"] = time.time()

    def revoke_ws_auth(self, ws_id: int, reason: str = "") -> bool:
        """Revoke authentication for a WebSocket connection.

        Args:
            ws_id: WebSocket connection ID
            reason: Reason for revocation (logged)

        Returns:
            True if auth was revoked
        """
        with self._ws_auth_lock:
            if ws_id in self._ws_auth_states:
                self._ws_auth_states[ws_id]["authenticated"] = False
                self._ws_auth_states[ws_id]["revoked_at"] = time.time()
                self._ws_auth_states[ws_id]["revoke_reason"] = reason
                if reason:
                    logger.info("Revoked WebSocket auth for %s: %s", ws_id, reason)
                return True
        return False

    def remove_ws_auth_state(self, ws_id: int) -> dict[str, Any] | None:
        """Remove authentication state for a WebSocket connection."""
        with self._ws_auth_lock:
            return self._ws_auth_states.pop(ws_id, None)

    def get_ws_token(self, ws_id: int) -> str | None:
        """Get the stored token for a WebSocket connection."""
        with self._ws_auth_lock:
            state = self._ws_auth_states.get(ws_id)
            return state.get("token") if state else None

    # =========================================================================
    # Cleanup All
    # =========================================================================

    def cleanup_ws_auth_states(self) -> int:
        """Clean up stale WebSocket auth states (for disconnected clients)."""
        # Auth states are cleaned up when clients disconnect via remove_ws_auth_state
        # This is a fallback for any orphaned entries
        with self._ws_auth_lock:
            # Remove entries for WebSocket IDs not in clients
            client_ws_ids = {id(c) for c in self.clients}
            stale_keys = [ws_id for ws_id in self._ws_auth_states if ws_id not in client_ws_ids]
            for ws_id in stale_keys:
                del self._ws_auth_states[ws_id]

            if stale_keys:
                logger.debug("Cleaned up %s orphaned auth states", len(stale_keys))

            return len(stale_keys)

    def cleanup_all(self) -> dict[str, int]:
        """
        Run all cleanup operations. Thread-safe.

        Returns a dict of cleanup counts.
        """
        return {
            "rate_limiters": self.cleanup_rate_limiters(),
            "debate_states": self.cleanup_debate_states(),
            "active_loops": self.cleanup_active_loops(),
            "auth_states": self.cleanup_ws_auth_states(),
        }

    def get_stats(self) -> dict[str, Any]:
        """Get server statistics."""
        with self._rate_limiters_lock:
            rate_limiter_count = len(self._rate_limiters)

        with self._debate_states_lock:
            debate_state_count = len(self.debate_states)

        with self._active_loops_lock:
            active_loop_count = len(self.active_loops)

        with self._ws_auth_lock:
            auth_states_count = len(self._ws_auth_states)
            authenticated_count = sum(
                1 for s in self._ws_auth_states.values() if s.get("authenticated", False)
            )

        return {
            "clients": len(self.clients),
            "rate_limiters": rate_limiter_count,
            "debate_states": debate_state_count,
            "active_loops": active_loop_count,
            "client_ids": len(self._client_ids),
            "auth_states": auth_states_count,
            "authenticated_clients": authenticated_count,
            "running": self._running,
        }

    # =========================================================================
    # Context Manager Support
    # =========================================================================

    def __enter__(self) -> ServerBase:
        """Enter context manager (synchronous).

        Returns:
            Self for use in with statement
        """
        self._running = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager - cleanup all resources (synchronous).

        Performs cleanup of all managed resources:
        - Rate limiters
        - Debate states
        - Active loops
        - Auth states
        - Client tracking
        """
        self._running = False
        self._cleanup_resources()

    async def __aenter__(self) -> ServerBase:
        """Enter async context manager.

        Returns:
            Self for use in async with statement
        """
        self._running = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager - cleanup all resources.

        Performs cleanup of all managed resources asynchronously.
        """
        self._running = False
        self._cleanup_resources()

    def _cleanup_resources(self) -> None:
        """Internal cleanup of all server resources."""
        # Clear all tracked state
        with self._rate_limiters_lock:
            self._rate_limiters.clear()
            self._rate_limiter_last_access.clear()

        with self._debate_states_lock:
            self.debate_states.clear()
            self._debate_states_last_access.clear()

        with self._active_loops_lock:
            self.active_loops.clear()
            self._active_loops_last_access.clear()

        with self._ws_auth_lock:
            self._ws_auth_states.clear()

        # Clear client tracking
        self._client_ids.clear()
        self.clients.clear()

        logger.debug("ServerBase resources cleaned up")
