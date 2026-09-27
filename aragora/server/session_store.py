"""
Redis-backed session store for horizontal scaling.

Provides distributed state management for WebSocket servers:
- Debate states (cached debate progress)
- Active loops (running nomic loop instances)
- WebSocket auth states (authenticated connections)
- Rate limiter state (per-client rate limiting)

When Redis is available, state is shared across server instances.
Falls back to in-memory storage when Redis is unavailable.

Usage:
    from aragora.server.session_store import get_session_store

    store = get_session_store()

    # Store debate state
    store.set_debate_state("loop-123", {"status": "running", ...})
    state = store.get_debate_state("loop-123")

    # Check if using Redis
    if store.is_distributed:
        print("State shared across instances")
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from aragora.control_plane.leader import (
    is_distributed_state_required,
    DistributedStateError,
)

logger = logging.getLogger(__name__)


def _clamp_ttl(value: int, lower: int, upper: int, name: str) -> int:
    """Clamp a TTL value to [lower, upper] and warn if out of range."""
    clamped = max(min(value, upper), lower)
    if clamped != value:
        logger.warning(
            "Session TTL %s=%d is outside recommended range [%d, %d]; clamped to %d",
            name,
            value,
            lower,
            upper,
            clamped,
        )
    return clamped


# Additional TTL settings for extended session types
_SESSION_VOICE_TTL = int(os.getenv("ARAGORA_SESSION_VOICE_TTL", "86400"))  # 24 hours
_SESSION_DEVICE_TTL = int(os.getenv("ARAGORA_SESSION_DEVICE_TTL", "2592000"))  # 30 days
_SESSION_MAX_VOICE_SESSIONS = int(os.getenv("ARAGORA_SESSION_MAX_VOICE", "1000"))
_SESSION_MAX_DEVICE_SESSIONS = int(os.getenv("ARAGORA_SESSION_MAX_DEVICES", "10000"))

# Configurable session store limits via environment variables
# TTL values are clamped to safe ranges to prevent security issues:
#   - Auth TTL: [60, 86400] (1 min to 24 hours)
#   - Debate TTL: [300, 86400] (5 min to 24 hours)
#   - Rate limiter TTL: [60, 3600] (1 min to 1 hour)
_SESSION_DEBATE_STATE_TTL = _clamp_ttl(
    int(os.getenv("ARAGORA_SESSION_DEBATE_TTL", "3600")),
    300,
    86400,
    "ARAGORA_SESSION_DEBATE_TTL",
)
_SESSION_ACTIVE_LOOP_TTL = _clamp_ttl(
    int(os.getenv("ARAGORA_SESSION_LOOP_TTL", "86400")),
    300,
    86400,
    "ARAGORA_SESSION_LOOP_TTL",
)
_SESSION_AUTH_STATE_TTL = _clamp_ttl(
    int(os.getenv("ARAGORA_SESSION_AUTH_TTL", "3600")),
    60,
    86400,
    "ARAGORA_SESSION_AUTH_TTL",
)
_SESSION_RATE_LIMITER_TTL = _clamp_ttl(
    int(os.getenv("ARAGORA_SESSION_RATE_LIMIT_TTL", "300")),
    60,
    3600,
    "ARAGORA_SESSION_RATE_LIMIT_TTL",
)
_SESSION_MAX_DEBATE_STATES = int(os.getenv("ARAGORA_SESSION_MAX_DEBATES", "500"))
_SESSION_MAX_ACTIVE_LOOPS = int(os.getenv("ARAGORA_SESSION_MAX_LOOPS", "1000"))
_SESSION_MAX_AUTH_STATES = int(os.getenv("ARAGORA_SESSION_MAX_AUTH", "10000"))


@dataclass
class SessionStoreConfig:
    """Configuration for session store.

    All values configurable via environment variables:
    - ARAGORA_SESSION_DEBATE_TTL: Debate state TTL in seconds (default 3600)
    - ARAGORA_SESSION_LOOP_TTL: Active loop TTL in seconds (default 86400)
    - ARAGORA_SESSION_AUTH_TTL: Auth state TTL in seconds (default 3600)
    - ARAGORA_SESSION_RATE_LIMIT_TTL: Rate limiter TTL in seconds (default 300)
    - ARAGORA_SESSION_MAX_DEBATES: Max debate states in memory (default 500)
    - ARAGORA_SESSION_MAX_LOOPS: Max active loops in memory (default 1000)
    - ARAGORA_SESSION_MAX_AUTH: Max auth states in memory (default 10000)
    """

    # TTL settings (in seconds)
    debate_state_ttl: int = field(default=_SESSION_DEBATE_STATE_TTL)
    active_loop_ttl: int = field(default=_SESSION_ACTIVE_LOOP_TTL)
    auth_state_ttl: int = field(default=_SESSION_AUTH_STATE_TTL)
    rate_limiter_ttl: int = field(default=_SESSION_RATE_LIMITER_TTL)

    # Max entries (for in-memory store)
    max_debate_states: int = field(default=_SESSION_MAX_DEBATE_STATES)
    max_active_loops: int = field(default=_SESSION_MAX_ACTIVE_LOOPS)
    max_auth_states: int = field(default=_SESSION_MAX_AUTH_STATES)
    max_voice_sessions: int = field(default=_SESSION_MAX_VOICE_SESSIONS)
    max_device_sessions: int = field(default=_SESSION_MAX_DEVICE_SESSIONS)

    # Extended session TTLs
    voice_session_ttl: int = field(default=_SESSION_VOICE_TTL)
    device_session_ttl: int = field(default=_SESSION_DEVICE_TTL)

    # Redis key prefix
    key_prefix: str = "aragora:session:"


@dataclass
class DebateSession:
    """Session tracking for debates across channels.

    Enables multi-channel debate sessions (Slack, Telegram, API, WhatsApp)
    with unified session isolation and channel handoff capability.

    Attributes:
        session_id: Unique session identifier (format: {channel}:{user_id}:{random})
        channel: Source channel ("slack", "telegram", "api", "whatsapp", etc.)
        user_id: User identifier from the channel
        debate_id: Linked debate ID (None if no active debate)
        context: Additional session context (e.g., channel-specific metadata)
        created_at: Session creation timestamp (Unix epoch)
        last_active: Last activity timestamp (Unix epoch)
    """

    session_id: str
    channel: str
    user_id: str
    debate_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    def link_debate(self, debate_id: str) -> None:
        """Link a debate to this session."""
        self.debate_id = debate_id
        self.last_active = time.time()

    def unlink_debate(self) -> None:
        """Unlink the current debate."""
        self.debate_id = None
        self.last_active = time.time()

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_active = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Serialize session to dictionary."""
        return {
            "session_id": self.session_id,
            "channel": self.channel,
            "user_id": self.user_id,
            "debate_id": self.debate_id,
            "context": self.context,
            "created_at": self.created_at,
            "last_active": self.last_active,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DebateSession:
        """Deserialize session from dictionary."""
        return cls(
            session_id=data["session_id"],
            channel=data["channel"],
            user_id=data["user_id"],
            debate_id=data.get("debate_id"),
            context=data.get("context", {}),
            created_at=data.get("created_at", time.time()),
            last_active=data.get("last_active", time.time()),
        )


@dataclass
class VoiceSession:
    """Session tracking for persistent voice connections.

    Enables long-lived voice sessions (up to 24h) with reconnection support
    for always-on voice assistants and hands-free interfaces.

    Attributes:
        session_id: Unique session identifier
        user_id: User identifier
        debate_id: Optional linked debate ID
        reconnect_token: Token for reconnection after disconnect
        reconnect_expires_at: When reconnect window expires (Unix epoch)
        is_persistent: Whether this is a persistent (always-on) session
        audio_format: Audio format preference (e.g., "pcm_16khz", "opus")
        last_heartbeat: Last keepalive timestamp (Unix epoch)
        created_at: Session creation timestamp (Unix epoch)
        metadata: Additional session metadata
    """

    session_id: str
    user_id: str
    debate_id: str | None = None
    reconnect_token: str | None = None
    reconnect_expires_at: float | None = None
    is_persistent: bool = False
    audio_format: str = "pcm_16khz"
    last_heartbeat: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None  # Session expiration timestamp
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_reconnectable(self) -> bool:
        """Check if session can be reconnected."""
        if not self.reconnect_token or not self.reconnect_expires_at:
            return False
        return time.time() < self.reconnect_expires_at

    @property
    def heartbeat_age(self) -> float:
        """Get seconds since last heartbeat."""
        return time.time() - self.last_heartbeat

    def touch_heartbeat(self) -> None:
        """Update heartbeat timestamp."""
        self.last_heartbeat = time.time()

    def set_reconnect_token(self, token: str, ttl_seconds: float = 300.0) -> None:
        """Set reconnection token with TTL."""
        self.reconnect_token = token
        self.reconnect_expires_at = time.time() + ttl_seconds

    def clear_reconnect_token(self) -> None:
        """Clear reconnection token after successful reconnect."""
        self.reconnect_token = None
        self.reconnect_expires_at = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize session to dictionary."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "debate_id": self.debate_id,
            "reconnect_token": self.reconnect_token,
            "reconnect_expires_at": self.reconnect_expires_at,
            "is_persistent": self.is_persistent,
            "audio_format": self.audio_format,
            "last_heartbeat": self.last_heartbeat,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoiceSession:
        """Deserialize session from dictionary."""
        return cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            debate_id=data.get("debate_id"),
            reconnect_token=data.get("reconnect_token"),
            reconnect_expires_at=data.get("reconnect_expires_at"),
            is_persistent=data.get("is_persistent", False),
            audio_format=data.get("audio_format", "pcm_16khz"),
            last_heartbeat=data.get("last_heartbeat", time.time()),
            created_at=data.get("created_at", time.time()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class DeviceSession:
    """Session tracking for registered devices (push notifications).

    Enables device registration for push notifications across platforms:
    - iOS (APNs)
    - Android (FCM)
    - Web (Web Push / VAPID)

    Attributes:
        device_id: Unique device identifier (server-generated)
        user_id: User identifier
        device_type: Device platform ("ios", "android", "web")
        push_token: Platform-specific push token
        device_name: Optional human-readable device name
        app_version: Application version for compatibility
        last_notified: When last notification was sent (Unix epoch)
        notification_count: Total notifications sent
        created_at: Registration timestamp (Unix epoch)
        last_active: Last activity timestamp (Unix epoch)
        metadata: Additional device metadata (OS version, model, etc.)
    """

    device_id: str
    user_id: str
    device_type: str  # "ios", "android", "web"
    push_token: str
    device_name: str | None = None
    app_version: str | None = None
    last_notified: float | None = None
    notification_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_active = time.time()

    def record_notification(self) -> None:
        """Record a notification being sent."""
        self.last_notified = time.time()
        self.notification_count += 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize session to dictionary."""
        return {
            "device_id": self.device_id,
            "user_id": self.user_id,
            "device_type": self.device_type,
            "push_token": self.push_token,
            "device_name": self.device_name,
            "app_version": self.app_version,
            "last_notified": self.last_notified,
            "notification_count": self.notification_count,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceSession:
        """Deserialize session from dictionary."""
        return cls(
            device_id=data["device_id"],
            user_id=data["user_id"],
            device_type=data["device_type"],
            push_token=data["push_token"],
            device_name=data.get("device_name"),
            app_version=data.get("app_version"),
            last_notified=data.get("last_notified"),
            notification_count=data.get("notification_count", 0),
            created_at=data.get("created_at", time.time()),
            last_active=data.get("last_active", time.time()),
            metadata=data.get("metadata", {}),
        )


class SessionStore(ABC):
    """Abstract base class for session stores."""

    @property
    @abstractmethod
    def is_distributed(self) -> bool:
        """Return True if store is distributed (Redis)."""
        pass

    # Debate state methods
    @abstractmethod
    def get_debate_state(self, loop_id: str) -> dict[str, Any] | None:
        """Get cached debate state."""
        pass

    @abstractmethod
    def set_debate_state(self, loop_id: str, state: dict[str, Any]) -> None:
        """Set debate state."""
        pass

    @abstractmethod
    def delete_debate_state(self, loop_id: str) -> bool:
        """Delete debate state. Returns True if deleted."""
        pass

    # Active loop methods
    @abstractmethod
    def get_active_loop(self, loop_id: str) -> dict[str, Any] | None:
        """Get active loop data."""
        pass

    @abstractmethod
    def set_active_loop(self, loop_id: str, data: dict[str, Any]) -> None:
        """Set active loop data."""
        pass

    @abstractmethod
    def delete_active_loop(self, loop_id: str) -> bool:
        """Delete active loop. Returns True if deleted."""
        pass

    @abstractmethod
    def list_active_loops(self) -> list[str]:
        """List all active loop IDs."""
        pass

    # Auth state methods
    @abstractmethod
    def get_auth_state(self, connection_id: str) -> dict[str, Any] | None:
        """Get WebSocket auth state."""
        pass

    @abstractmethod
    def set_auth_state(self, connection_id: str, state: dict[str, Any]) -> None:
        """Set WebSocket auth state."""
        pass

    @abstractmethod
    def delete_auth_state(self, connection_id: str) -> bool:
        """Delete auth state. Returns True if deleted."""
        pass

    # Pub/Sub for cross-server messaging
    @abstractmethod
    def publish_event(self, channel: str, event: dict[str, Any]) -> None:
        """Publish event to channel for cross-server messaging."""
        pass

    @abstractmethod
    def subscribe_events(self, channel: str, callback) -> None:
        """Subscribe to events on channel."""
        pass

    # Cleanup
    @abstractmethod
    def cleanup_expired(self) -> dict[str, int]:
        """Clean up expired entries. Returns counts by type."""
        pass

    # Debate session methods (for multi-channel session tracking)
    @abstractmethod
    def get_debate_session(self, session_id: str) -> DebateSession | None:
        """Get a debate session by ID."""
        pass

    @abstractmethod
    def set_debate_session(self, session: DebateSession) -> None:
        """Store or update a debate session."""
        pass

    @abstractmethod
    def delete_debate_session(self, session_id: str) -> bool:
        """Delete a debate session. Returns True if deleted."""
        pass

    @abstractmethod
    def find_sessions_by_user(
        self, user_id: str, channel: str | None = None
    ) -> list[DebateSession]:
        """Find sessions by user ID, optionally filtered by channel."""
        pass

    @abstractmethod
    def find_sessions_by_debate(self, debate_id: str) -> list[DebateSession]:
        """Find all sessions linked to a debate."""
        pass

    # Voice session methods (for always-on voice)
    @abstractmethod
    def get_voice_session(self, session_id: str) -> VoiceSession | None:
        """Get a voice session by ID."""
        pass

    @abstractmethod
    def set_voice_session(self, session: VoiceSession) -> None:
        """Store or update a voice session."""
        pass

    @abstractmethod
    def delete_voice_session(self, session_id: str) -> bool:
        """Delete a voice session. Returns True if deleted."""
        pass

    @abstractmethod
    def find_voice_session_by_token(self, reconnect_token: str) -> VoiceSession | None:
        """Find voice session by reconnection token."""
        pass

    @abstractmethod
    def find_voice_sessions_by_user(self, user_id: str) -> list[VoiceSession]:
        """Find all voice sessions for a user."""
        pass

    # Device session methods (for push notifications)
    @abstractmethod
    def get_device_session(self, device_id: str) -> DeviceSession | None:
        """Get a device session by ID."""
        pass

    @abstractmethod
    def set_device_session(self, session: DeviceSession) -> None:
        """Store or update a device session."""
        pass

    @abstractmethod
    def delete_device_session(self, device_id: str) -> bool:
        """Delete a device session. Returns True if deleted."""
        pass

    @abstractmethod
    def find_device_by_token(self, push_token: str) -> DeviceSession | None:
        """Find device session by push token."""
        pass

    @abstractmethod
    def find_devices_by_user(self, user_id: str) -> list[DeviceSession]:
        """Find all devices for a user."""
        pass


class InMemorySessionStore(SessionStore):
    """In-memory session store for single-server deployment."""

    def __init__(self, config: SessionStoreConfig | None = None):
        self._config = config or SessionStoreConfig()

        # State storage with last-access tracking
        self._debate_states: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._debate_states_access: dict[str, float] = {}
        self._debate_lock = threading.Lock()

        self._active_loops: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._active_loops_access: dict[str, float] = {}
        self._loops_lock = threading.Lock()

        self._auth_states: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._auth_states_access: dict[str, float] = {}
        self._auth_lock = threading.Lock()

        # Event subscribers (for local pub/sub)
        self._subscribers: dict[str, list] = {}
        self._sub_lock = threading.Lock()

        # Debate sessions (for multi-channel session tracking)
        self._debate_sessions: dict[str, DebateSession] = {}
        self._debate_sessions_lock = threading.Lock()

        # Voice sessions (for always-on voice)
        self._voice_sessions: dict[str, VoiceSession] = {}
        self._voice_sessions_lock = threading.Lock()

        # Device sessions (for push notifications)
        self._device_sessions: dict[str, DeviceSession] = {}
        self._device_token_index: dict[str, str] = {}  # push_token -> device_id
        self._device_sessions_lock = threading.Lock()

    @property
    def is_distributed(self) -> bool:
        return False

    # Debate state methods
    def get_debate_state(self, loop_id: str) -> dict[str, Any] | None:
        with self._debate_lock:
            if loop_id in self._debate_states:
                self._debate_states_access[loop_id] = time.time()
                self._debate_states.move_to_end(loop_id)
                return self._debate_states[loop_id].copy()
            return None

    def set_debate_state(self, loop_id: str, state: dict[str, Any]) -> None:
        with self._debate_lock:
            # Enforce max limit with LRU eviction
            while len(self._debate_states) >= self._config.max_debate_states:
                oldest = next(iter(self._debate_states))
                del self._debate_states[oldest]
                self._debate_states_access.pop(oldest, None)

            self._debate_states[loop_id] = state.copy()
            self._debate_states_access[loop_id] = time.time()
            self._debate_states.move_to_end(loop_id)

    def delete_debate_state(self, loop_id: str) -> bool:
        with self._debate_lock:
            if loop_id in self._debate_states:
                del self._debate_states[loop_id]
                self._debate_states_access.pop(loop_id, None)
                return True
            return False

    # Active loop methods
    def get_active_loop(self, loop_id: str) -> dict[str, Any] | None:
        with self._loops_lock:
            if loop_id in self._active_loops:
                self._active_loops_access[loop_id] = time.time()
                self._active_loops.move_to_end(loop_id)
                return self._active_loops[loop_id].copy()
            return None

    def set_active_loop(self, loop_id: str, data: dict[str, Any]) -> None:
        with self._loops_lock:
            while len(self._active_loops) >= self._config.max_active_loops:
                oldest = next(iter(self._active_loops))
                del self._active_loops[oldest]
                self._active_loops_access.pop(oldest, None)

            self._active_loops[loop_id] = data.copy()
            self._active_loops_access[loop_id] = time.time()
            self._active_loops.move_to_end(loop_id)

    def delete_active_loop(self, loop_id: str) -> bool:
        with self._loops_lock:
            if loop_id in self._active_loops:
                del self._active_loops[loop_id]
                self._active_loops_access.pop(loop_id, None)
                return True
            return False

    def list_active_loops(self) -> list[str]:
        with self._loops_lock:
            return list(self._active_loops.keys())

    # Auth state methods
    def get_auth_state(self, connection_id: str) -> dict[str, Any] | None:
        with self._auth_lock:
            if connection_id in self._auth_states:
                self._auth_states_access[connection_id] = time.time()
                return self._auth_states[connection_id].copy()
            return None

    def set_auth_state(self, connection_id: str, state: dict[str, Any]) -> None:
        with self._auth_lock:
            while len(self._auth_states) >= self._config.max_auth_states:
                oldest = next(iter(self._auth_states))
                del self._auth_states[oldest]
                self._auth_states_access.pop(oldest, None)

            self._auth_states[connection_id] = state.copy()
            self._auth_states_access[connection_id] = time.time()

    def delete_auth_state(self, connection_id: str) -> bool:
        with self._auth_lock:
            if connection_id in self._auth_states:
                del self._auth_states[connection_id]
                self._auth_states_access.pop(connection_id, None)
                return True
            return False

    # Pub/Sub (local only for in-memory store)
    def publish_event(self, channel: str, event: dict[str, Any]) -> None:
        with self._sub_lock:
            callbacks = self._subscribers.get(channel, [])
        for cb in callbacks:
            try:
                cb(event)
            except (RuntimeError, ValueError, TypeError) as e:
                logger.warning("Event callback error: %s", e)

    def subscribe_events(self, channel: str, callback) -> None:
        with self._sub_lock:
            if channel not in self._subscribers:
                self._subscribers[channel] = []
            self._subscribers[channel].append(callback)

    # Debate session methods
    def get_debate_session(self, session_id: str) -> DebateSession | None:
        with self._debate_sessions_lock:
            session = self._debate_sessions.get(session_id)
            if session:
                session.touch()
            return session

    def set_debate_session(self, session: DebateSession) -> None:
        with self._debate_sessions_lock:
            session.touch()
            self._debate_sessions[session.session_id] = session

    def delete_debate_session(self, session_id: str) -> bool:
        with self._debate_sessions_lock:
            if session_id in self._debate_sessions:
                del self._debate_sessions[session_id]
                return True
            return False

    def find_sessions_by_user(
        self, user_id: str, channel: str | None = None
    ) -> list[DebateSession]:
        with self._debate_sessions_lock:
            results = []
            for session in self._debate_sessions.values():
                if session.user_id == user_id:
                    if channel is None or session.channel == channel:
                        results.append(session)
            return results

    def find_sessions_by_debate(self, debate_id: str) -> list[DebateSession]:
        with self._debate_sessions_lock:
            return [s for s in self._debate_sessions.values() if s.debate_id == debate_id]

    # Voice session methods
    def get_voice_session(self, session_id: str) -> VoiceSession | None:
        with self._voice_sessions_lock:
            session = self._voice_sessions.get(session_id)
            if session:
                session.touch_heartbeat()
            return session

    def set_voice_session(self, session: VoiceSession) -> None:
        with self._voice_sessions_lock:
            # Enforce max limit with LRU eviction (remove oldest by created_at)
            while len(self._voice_sessions) >= self._config.max_voice_sessions:
                oldest_id = min(
                    self._voice_sessions.keys(),
                    key=lambda k: self._voice_sessions[k].created_at,
                )
                del self._voice_sessions[oldest_id]

            session.touch_heartbeat()
            self._voice_sessions[session.session_id] = session

    def delete_voice_session(self, session_id: str) -> bool:
        with self._voice_sessions_lock:
            if session_id in self._voice_sessions:
                del self._voice_sessions[session_id]
                return True
            return False

    def find_voice_session_by_token(self, reconnect_token: str) -> VoiceSession | None:
        with self._voice_sessions_lock:
            for session in self._voice_sessions.values():
                if session.reconnect_token == reconnect_token and session.is_reconnectable:
                    return session
            return None

    def find_voice_sessions_by_user(self, user_id: str) -> list[VoiceSession]:
        with self._voice_sessions_lock:
            return [s for s in self._voice_sessions.values() if s.user_id == user_id]

    # Device session methods
    def get_device_session(self, device_id: str) -> DeviceSession | None:
        with self._device_sessions_lock:
            session = self._device_sessions.get(device_id)
            if session:
                session.touch()
            return session

    def set_device_session(self, session: DeviceSession) -> None:
        with self._device_sessions_lock:
            # Enforce max limit with LRU eviction
            while len(self._device_sessions) >= self._config.max_device_sessions:
                oldest_id = min(
                    self._device_sessions.keys(),
                    key=lambda k: self._device_sessions[k].last_active,
                )
                old_session = self._device_sessions[oldest_id]
                self._device_token_index.pop(old_session.push_token, None)
                del self._device_sessions[oldest_id]

            # Remove stale token index entries for this device.
            # Walk the index rather than comparing object fields, because
            # callers may mutate the session in-place before re-storing it,
            # making old_session.push_token == session.push_token even when
            # the token actually changed.
            stale_tokens = [
                tok
                for tok, did in self._device_token_index.items()
                if did == session.device_id and tok != session.push_token
            ]
            for tok in stale_tokens:
                del self._device_token_index[tok]

            session.touch()
            self._device_sessions[session.device_id] = session
            self._device_token_index[session.push_token] = session.device_id

    def delete_device_session(self, device_id: str) -> bool:
        with self._device_sessions_lock:
            if device_id in self._device_sessions:
                session = self._device_sessions[device_id]
                self._device_token_index.pop(session.push_token, None)
                del self._device_sessions[device_id]
                return True
            return False

    def find_device_by_token(self, push_token: str) -> DeviceSession | None:
        with self._device_sessions_lock:
            device_id = self._device_token_index.get(push_token)
            if device_id:
                return self._device_sessions.get(device_id)
            return None

    def find_devices_by_user(self, user_id: str) -> list[DeviceSession]:
        with self._device_sessions_lock:
            return [s for s in self._device_sessions.values() if s.user_id == user_id]

    # Cleanup
    def cleanup_expired(self) -> dict[str, int]:
        now = time.time()
        counts = {"debate_states": 0, "active_loops": 0, "auth_states": 0}

        # Cleanup debate states
        cutoff = now - self._config.debate_state_ttl
        with self._debate_lock:
            expired = [k for k, v in self._debate_states_access.items() if v < cutoff]
            for k in expired:
                self._debate_states.pop(k, None)
                self._debate_states_access.pop(k, None)
            counts["debate_states"] = len(expired)

        # Cleanup active loops
        cutoff = now - self._config.active_loop_ttl
        with self._loops_lock:
            expired = [k for k, v in self._active_loops_access.items() if v < cutoff]
            for k in expired:
                self._active_loops.pop(k, None)
                self._active_loops_access.pop(k, None)
            counts["active_loops"] = len(expired)

        # Cleanup auth states
        cutoff = now - self._config.auth_state_ttl
        with self._auth_lock:
            expired = [k for k, v in self._auth_states_access.items() if v < cutoff]
            for k in expired:
                self._auth_states.pop(k, None)
                self._auth_states_access.pop(k, None)
            counts["auth_states"] = len(expired)

        # Cleanup voice sessions (based on last_heartbeat)
        cutoff = now - self._config.voice_session_ttl
        with self._voice_sessions_lock:
            expired = [k for k, v in self._voice_sessions.items() if v.last_heartbeat < cutoff]
            for k in expired:
                del self._voice_sessions[k]
            counts["voice_sessions"] = len(expired)

        # Cleanup device sessions (based on last_active)
        cutoff = now - self._config.device_session_ttl
        with self._device_sessions_lock:
            expired = [k for k, v in self._device_sessions.items() if v.last_active < cutoff]
            for k in expired:
                session = self._device_sessions[k]
                self._device_token_index.pop(session.push_token, None)
                del self._device_sessions[k]
            counts["device_sessions"] = len(expired)

        return counts


class RedisSessionStore(SessionStore):
    """Redis-backed session store for horizontal scaling."""

    def __init__(self, config: SessionStoreConfig | None = None):
        self._config = config or SessionStoreConfig()
        self._prefix = self._config.key_prefix

        # Get Redis client
        from aragora.utils.redis_config import get_redis_client

        redis_client = get_redis_client()
        if redis_client is None:
            raise RuntimeError("Redis not available")
        self._redis = redis_client  # Type is narrowed after None check

        # Pub/Sub subscriber thread
        self._pubsub = None
        self._pubsub_thread = None
        self._callbacks: dict[str, list] = {}
        self._callbacks_lock = threading.Lock()

    @property
    def is_distributed(self) -> bool:
        return True

    def _key(self, *parts: str) -> str:
        """Build Redis key with prefix."""
        return self._prefix + ":".join(parts)

    # Debate state methods
    def get_debate_state(self, loop_id: str) -> dict[str, Any] | None:
        try:
            data = self._redis.get(self._key("debate", loop_id))
            if data:
                # Refresh TTL on access
                self._redis.expire(self._key("debate", loop_id), self._config.debate_state_ttl)
                return json.loads(data)
            return None
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
        ) as e:
            logger.warning("Redis get_debate_state error: %s", e)
            return None

    def set_debate_state(self, loop_id: str, state: dict[str, Any]) -> None:
        try:
            self._redis.setex(
                self._key("debate", loop_id),
                self._config.debate_state_ttl,
                json.dumps(state, default=str),
            )
        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
            logger.warning("Redis set_debate_state error: %s", e)

    def delete_debate_state(self, loop_id: str) -> bool:
        try:
            return self._redis.delete(self._key("debate", loop_id)) > 0
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Redis delete_debate_state error: %s", e)
            return False

    # Active loop methods
    # NOTE: Using individual keys with TTL instead of hash to support per-entry expiration
    def get_active_loop(self, loop_id: str) -> dict[str, Any] | None:
        try:
            data = self._redis.get(self._key("loop", loop_id))
            if data:
                # Refresh TTL on access
                self._redis.expire(self._key("loop", loop_id), self._config.active_loop_ttl)
                return json.loads(data)
            return None
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
        ) as e:
            logger.warning("Redis get_active_loop error: %s", e)
            return None

    def set_active_loop(self, loop_id: str, data: dict[str, Any]) -> None:
        try:
            # Use setex with TTL for automatic expiration
            self._redis.setex(
                self._key("loop", loop_id),
                self._config.active_loop_ttl,
                json.dumps(data, default=str),
            )
            # Also add to index set (for list_active_loops)
            self._redis.sadd(self._key("loop_index"), loop_id)
        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
            logger.warning("Redis set_active_loop error: %s", e)

    def delete_active_loop(self, loop_id: str) -> bool:
        try:
            deleted = self._redis.delete(self._key("loop", loop_id)) > 0
            # Remove from index set
            self._redis.srem(self._key("loop_index"), loop_id)
            return deleted
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Redis delete_active_loop error: %s", e)
            return False

    def list_active_loops(self) -> list[str]:
        """List all active loop IDs.

        Uses an index set for efficiency. Cleans up stale entries.
        """
        try:
            # Get all IDs from index
            all_ids = self._redis.smembers(self._key("loop_index"))
            if not all_ids:
                return []

            # Filter to only those that still exist (haven't expired)
            active_ids = []
            stale_ids = []

            for loop_id in all_ids:
                # Decode bytes if needed
                if isinstance(loop_id, bytes):
                    loop_id = loop_id.decode()

                # Check if key still exists
                if self._redis.exists(self._key("loop", loop_id)):
                    active_ids.append(loop_id)
                else:
                    stale_ids.append(loop_id)

            # Clean up stale index entries
            if stale_ids:
                self._redis.srem(self._key("loop_index"), *stale_ids)
                logger.debug("Cleaned up %s stale loop index entries", len(stale_ids))

            return active_ids
        except (ConnectionError, TimeoutError, OSError, UnicodeDecodeError) as e:
            logger.warning("Redis list_active_loops error: %s", e)
            return []

    # Auth state methods
    def get_auth_state(self, connection_id: str) -> dict[str, Any] | None:
        try:
            data = self._redis.get(self._key("auth", connection_id))
            if data:
                self._redis.expire(self._key("auth", connection_id), self._config.auth_state_ttl)
                return json.loads(data)
            return None
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
        ) as e:
            logger.warning("Redis get_auth_state error: %s", e)
            return None

    def set_auth_state(self, connection_id: str, state: dict[str, Any]) -> None:
        try:
            self._redis.setex(
                self._key("auth", connection_id),
                self._config.auth_state_ttl,
                json.dumps(state, default=str),
            )
        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
            logger.warning("Redis set_auth_state error: %s", e)

    def delete_auth_state(self, connection_id: str) -> bool:
        try:
            return self._redis.delete(self._key("auth", connection_id)) > 0
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Redis delete_auth_state error: %s", e)
            return False

    # Pub/Sub for cross-server messaging
    def publish_event(self, channel: str, event: dict[str, Any]) -> None:
        try:
            self._redis.publish(self._key("events", channel), json.dumps(event, default=str))
        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
            logger.warning("Redis publish error: %s", e)

    def subscribe_events(self, channel: str, callback) -> None:
        with self._callbacks_lock:
            if channel not in self._callbacks:
                self._callbacks[channel] = []
            self._callbacks[channel].append(callback)

        # Start pub/sub thread if not running
        if self._pubsub is None:
            self._start_pubsub()

    def _start_pubsub(self) -> None:
        """Start the pub/sub listener thread."""
        try:
            pubsub = self._redis.pubsub()
            self._pubsub = pubsub

            # Subscribe to all registered channels
            with self._callbacks_lock:
                patterns = [self._key("events", "*")]

            pubsub.psubscribe(**{patterns[0]: self._handle_message})
            self._pubsub_thread = pubsub.run_in_thread(sleep_time=0.1)
            logger.info("Redis pub/sub listener started")
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.warning("Failed to start Redis pub/sub: %s", e)

    def _handle_message(self, message: dict[str, Any]) -> None:
        """Handle incoming pub/sub message."""
        if message["type"] != "pmessage":
            return

        try:
            # Extract channel from pattern match
            full_channel = message["channel"]
            if isinstance(full_channel, bytes):
                full_channel = full_channel.decode()

            # Remove prefix to get logical channel
            prefix = self._key("events", "")
            channel = (
                full_channel[len(prefix) :] if full_channel.startswith(prefix) else full_channel
            )

            # Parse event data
            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode()
            event = json.loads(data)

            # Call registered callbacks
            with self._callbacks_lock:
                callbacks = self._callbacks.get(channel, [])

            for cb in callbacks:
                try:
                    cb(event)
                except (RuntimeError, ValueError, TypeError) as e:
                    logger.warning("Pub/sub callback error: %s", e)
        except (ValueError, TypeError, UnicodeDecodeError, KeyError) as e:
            logger.warning("Failed to handle pub/sub message: %s", e)

    # Debate session methods
    def get_debate_session(self, session_id: str) -> DebateSession | None:
        try:
            data = self._redis.get(self._key("dsession", session_id))
            if data:
                # Refresh TTL on access
                self._redis.expire(self._key("dsession", session_id), self._config.debate_state_ttl)
                session_dict = json.loads(data)
                return DebateSession.from_dict(session_dict)
            return None
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
            KeyError,
        ) as e:
            logger.warning("Redis get_debate_session error: %s", e)
            return None

    def set_debate_session(self, session: DebateSession) -> None:
        try:
            session.touch()
            session_dict = session.to_dict()
            # Store session with TTL
            self._redis.setex(
                self._key("dsession", session.session_id),
                self._config.debate_state_ttl,
                json.dumps(session_dict, default=str),
            )
            # Add to user index (for find_sessions_by_user)
            self._redis.sadd(self._key("dsession_user", session.user_id), session.session_id)
            # Add to debate index if linked (for find_sessions_by_debate)
            if session.debate_id:
                self._redis.sadd(
                    self._key("dsession_debate", session.debate_id), session.session_id
                )
        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
            logger.warning("Redis set_debate_session error: %s", e)

    def delete_debate_session(self, session_id: str) -> bool:
        try:
            # Get session to remove from indices
            session = self.get_debate_session(session_id)
            if session:
                # Remove from user index
                self._redis.srem(self._key("dsession_user", session.user_id), session_id)
                # Remove from debate index if linked
                if session.debate_id:
                    self._redis.srem(self._key("dsession_debate", session.debate_id), session_id)
            return self._redis.delete(self._key("dsession", session_id)) > 0
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Redis delete_debate_session error: %s", e)
            return False

    def find_sessions_by_user(
        self, user_id: str, channel: str | None = None
    ) -> list[DebateSession]:
        try:
            session_ids = self._redis.smembers(self._key("dsession_user", user_id))
            results = []
            for sid in session_ids:
                if isinstance(sid, bytes):
                    sid = sid.decode()
                session = self.get_debate_session(sid)
                if session:
                    if channel is None or session.channel == channel:
                        results.append(session)
            return results
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
            KeyError,
        ) as e:
            logger.warning("Redis find_sessions_by_user error: %s", e)
            return []

    def find_sessions_by_debate(self, debate_id: str) -> list[DebateSession]:
        try:
            session_ids = self._redis.smembers(self._key("dsession_debate", debate_id))
            results = []
            for sid in session_ids:
                if isinstance(sid, bytes):
                    sid = sid.decode()
                session = self.get_debate_session(sid)
                if session:
                    results.append(session)
            return results
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
            KeyError,
        ) as e:
            logger.warning("Redis find_sessions_by_debate error: %s", e)
            return []

    # Voice session methods
    def get_voice_session(self, session_id: str) -> VoiceSession | None:
        try:
            data = self._redis.get(self._key("vsession", session_id))
            if data:
                # Refresh TTL on access
                self._redis.expire(
                    self._key("vsession", session_id),
                    self._config.voice_session_ttl,
                )
                session_dict = json.loads(data)
                session = VoiceSession.from_dict(session_dict)
                session.touch_heartbeat()
                return session
            return None
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
            KeyError,
        ) as e:
            logger.warning("Redis get_voice_session error: %s", e)
            return None

    def set_voice_session(self, session: VoiceSession) -> None:
        try:
            session.touch_heartbeat()
            session_dict = session.to_dict()
            # Store session with TTL
            self._redis.setex(
                self._key("vsession", session.session_id),
                self._config.voice_session_ttl,
                json.dumps(session_dict, default=str),
            )
            # Add to user index
            self._redis.sadd(self._key("vsession_user", session.user_id), session.session_id)
            # Add reconnect token to index if present
            if session.reconnect_token:
                self._redis.setex(
                    self._key("vsession_token", session.reconnect_token),
                    300,  # 5-minute reconnect window
                    session.session_id,
                )
        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
            logger.warning("Redis set_voice_session error: %s", e)

    def delete_voice_session(self, session_id: str) -> bool:
        try:
            session = self.get_voice_session(session_id)
            if session:
                # Remove from user index
                self._redis.srem(self._key("vsession_user", session.user_id), session_id)
                # Remove reconnect token if present
                if session.reconnect_token:
                    self._redis.delete(self._key("vsession_token", session.reconnect_token))
            return self._redis.delete(self._key("vsession", session_id)) > 0
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Redis delete_voice_session error: %s", e)
            return False

    def find_voice_session_by_token(self, reconnect_token: str) -> VoiceSession | None:
        try:
            session_id = self._redis.get(self._key("vsession_token", reconnect_token))
            if session_id:
                if isinstance(session_id, bytes):
                    session_id = session_id.decode()
                session = self.get_voice_session(session_id)
                if session and session.is_reconnectable:
                    return session
            return None
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
            KeyError,
        ) as e:
            logger.warning("Redis find_voice_session_by_token error: %s", e)
            return None

    def find_voice_sessions_by_user(self, user_id: str) -> list[VoiceSession]:
        try:
            session_ids = self._redis.smembers(self._key("vsession_user", user_id))
            results = []
            for sid in session_ids:
                if isinstance(sid, bytes):
                    sid = sid.decode()
                session = self.get_voice_session(sid)
                if session:
                    results.append(session)
            return results
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
            KeyError,
        ) as e:
            logger.warning("Redis find_voice_sessions_by_user error: %s", e)
            return []

    # Device session methods
    def get_device_session(self, device_id: str) -> DeviceSession | None:
        try:
            data = self._redis.get(self._key("device", device_id))
            if data:
                # Refresh TTL on access
                self._redis.expire(
                    self._key("device", device_id),
                    self._config.device_session_ttl,
                )
                session_dict = json.loads(data)
                session = DeviceSession.from_dict(session_dict)
                session.touch()
                return session
            return None
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
            KeyError,
        ) as e:
            logger.warning("Redis get_device_session error: %s", e)
            return None

    def set_device_session(self, session: DeviceSession) -> None:
        try:
            # Remove old token mapping if token changed
            old_session = self.get_device_session(session.device_id)
            if old_session and old_session.push_token != session.push_token:
                self._redis.delete(self._key("device_token", old_session.push_token))

            session.touch()
            session_dict = session.to_dict()
            # Store session with TTL
            self._redis.setex(
                self._key("device", session.device_id),
                self._config.device_session_ttl,
                json.dumps(session_dict, default=str),
            )
            # Add to user index
            self._redis.sadd(self._key("device_user", session.user_id), session.device_id)
            # Add token to index
            self._redis.setex(
                self._key("device_token", session.push_token),
                self._config.device_session_ttl,
                session.device_id,
            )
        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
            logger.warning("Redis set_device_session error: %s", e)

    def delete_device_session(self, device_id: str) -> bool:
        try:
            session = self.get_device_session(device_id)
            if session:
                # Remove from user index
                self._redis.srem(self._key("device_user", session.user_id), device_id)
                # Remove token mapping
                self._redis.delete(self._key("device_token", session.push_token))
            return self._redis.delete(self._key("device", device_id)) > 0
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Redis delete_device_session error: %s", e)
            return False

    def find_device_by_token(self, push_token: str) -> DeviceSession | None:
        try:
            device_id = self._redis.get(self._key("device_token", push_token))
            if device_id:
                if isinstance(device_id, bytes):
                    device_id = device_id.decode()
                return self.get_device_session(device_id)
            return None
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
            KeyError,
        ) as e:
            logger.warning("Redis find_device_by_token error: %s", e)
            return None

    def find_devices_by_user(self, user_id: str) -> list[DeviceSession]:
        try:
            device_ids = self._redis.smembers(self._key("device_user", user_id))
            results = []
            for did in device_ids:
                if isinstance(did, bytes):
                    did = did.decode()
                session = self.get_device_session(did)
                if session:
                    results.append(session)
            return results
        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
            KeyError,
        ) as e:
            logger.warning("Redis find_devices_by_user error: %s", e)
            return []

    def cleanup_expired(self) -> dict[str, int]:
        """Redis handles expiry automatically via TTL."""
        return {"debate_states": 0, "active_loops": 0, "auth_states": 0}

    def close(self) -> None:
        """Close Redis connections."""
        if self._pubsub_thread:
            self._pubsub_thread.stop()
        if self._pubsub:
            self._pubsub.close()


# Global session store instance
_session_store: SessionStore | None = None
_store_lock = threading.Lock()


def get_session_store(force_memory: bool = False) -> SessionStore:
    """Get the session store instance.

    Uses Redis if available and configured, otherwise falls back to in-memory.

    Args:
        force_memory: Force in-memory store even if Redis available

    Returns:
        SessionStore instance
    """
    global _session_store

    if _session_store is not None:
        return _session_store

    with _store_lock:
        if _session_store is not None:
            return _session_store

        if force_memory:
            _session_store = InMemorySessionStore()
            logger.info("Using in-memory session store (forced)")
            return _session_store

        # Try Redis first
        try:
            from aragora.utils.redis_config import is_redis_available

            if is_redis_available():
                _session_store = RedisSessionStore()
                logger.info("Using Redis session store (distributed)")
                return _session_store
        except (ImportError, RuntimeError, ConnectionError, TimeoutError, OSError) as e:
            logger.debug("Redis session store unavailable: %s", e)

        # Check if distributed state is required (multi-instance or production)
        if is_distributed_state_required():
            raise DistributedStateError(
                "session_store",
                "Redis not available for distributed session management",
            )

        # Fall back to in-memory (single instance only)
        logger.warning(
            "Using in-memory session store - sessions will be lost on restart "
            "and not shared across instances. Set ARAGORA_MULTI_INSTANCE=true "
            "and configure REDIS_URL for production deployments."
        )
        _session_store = InMemorySessionStore()
        return _session_store


def reset_session_store() -> None:
    """Reset session store (for testing)."""
    global _session_store
    with _store_lock:
        if _session_store is not None and hasattr(_session_store, "close"):
            _session_store.close()
        _session_store = None


__all__ = [
    "SessionStore",
    "SessionStoreConfig",
    "DebateSession",
    "VoiceSession",
    "DeviceSession",
    "InMemorySessionStore",
    "RedisSessionStore",
    "get_session_store",
    "reset_session_store",
]
