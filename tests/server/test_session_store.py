"""
Tests for session store utilities.

Tests cover:
- SessionStoreConfig dataclass
- InMemorySessionStore class
- get_session_store / reset_session_store functions
"""

import pytest
import threading
from unittest.mock import patch, MagicMock

from aragora.server.session_store import (
    SessionStoreConfig,
    InMemorySessionStore,
    get_session_store,
    reset_session_store,
)


@pytest.fixture(autouse=True)
def reset_store():
    """Reset global session store before and after each test."""
    reset_session_store()
    yield
    reset_session_store()


class TestSessionStoreConfig:
    """Tests for SessionStoreConfig dataclass."""

    def test_default_values(self):
        """Config has correct defaults."""
        config = SessionStoreConfig()

        assert config.debate_state_ttl > 0
        assert config.active_loop_ttl > 0
        assert config.auth_state_ttl > 0
        assert config.rate_limiter_ttl > 0
        assert config.max_debate_states > 0
        assert config.max_active_loops > 0
        assert config.max_auth_states > 0
        assert config.key_prefix == "aragora:session:"

    def test_custom_values(self):
        """Config accepts custom values."""
        config = SessionStoreConfig(
            debate_state_ttl=100,
            max_debate_states=10,
            key_prefix="test:",
        )

        assert config.debate_state_ttl == 100
        assert config.max_debate_states == 10
        assert config.key_prefix == "test:"


class TestInMemorySessionStore:
    """Tests for InMemorySessionStore class."""

    @pytest.fixture
    def store(self):
        """Fresh in-memory store for each test."""
        config = SessionStoreConfig(
            debate_state_ttl=1,  # 1 second for fast expiry tests
            active_loop_ttl=1,
            auth_state_ttl=1,
            max_debate_states=5,
            max_active_loops=5,
            max_auth_states=5,
        )
        return InMemorySessionStore(config)

    def test_is_not_distributed(self, store):
        """In-memory store is not distributed."""
        assert store.is_distributed is False

    # Debate state tests
    def test_set_and_get_debate_state(self, store):
        """Sets and gets debate state."""
        store.set_debate_state("loop-1", {"status": "running"})
        state = store.get_debate_state("loop-1")

        assert state is not None
        assert state["status"] == "running"

    def test_get_nonexistent_debate_state(self, store):
        """Returns None for nonexistent state."""
        assert store.get_debate_state("nonexistent") is None

    def test_debate_state_returns_copy(self, store):
        """Returns a copy, not the original."""
        original = {"status": "running"}
        store.set_debate_state("loop-1", original)
        retrieved = store.get_debate_state("loop-1")

        retrieved["status"] = "modified"
        assert store.get_debate_state("loop-1")["status"] == "running"

    def test_delete_debate_state(self, store):
        """Deletes debate state."""
        store.set_debate_state("loop-1", {"status": "running"})
        assert store.delete_debate_state("loop-1") is True
        assert store.get_debate_state("loop-1") is None

    def test_delete_nonexistent_debate_state(self, store):
        """Returns False when deleting nonexistent state."""
        assert store.delete_debate_state("nonexistent") is False

    def test_debate_state_lru_eviction(self, store):
        """Evicts oldest debate states when max reached."""
        for i in range(6):
            store.set_debate_state(f"loop-{i}", {"num": i})

        # First one should be evicted
        assert store.get_debate_state("loop-0") is None
        assert store.get_debate_state("loop-5") is not None

    # Active loop tests
    def test_set_and_get_active_loop(self, store):
        """Sets and gets active loop."""
        store.set_active_loop("loop-1", {"phase": "debate"})
        data = store.get_active_loop("loop-1")

        assert data is not None
        assert data["phase"] == "debate"

    def test_get_nonexistent_active_loop(self, store):
        """Returns None for nonexistent loop."""
        assert store.get_active_loop("nonexistent") is None

    def test_delete_active_loop(self, store):
        """Deletes active loop."""
        store.set_active_loop("loop-1", {"phase": "debate"})
        assert store.delete_active_loop("loop-1") is True
        assert store.get_active_loop("loop-1") is None

    def test_list_active_loops(self, store):
        """Lists all active loop IDs."""
        store.set_active_loop("loop-1", {})
        store.set_active_loop("loop-2", {})
        store.set_active_loop("loop-3", {})

        loops = store.list_active_loops()
        assert set(loops) == {"loop-1", "loop-2", "loop-3"}

    def test_active_loop_lru_eviction(self, store):
        """Evicts oldest active loops when max reached."""
        for i in range(6):
            store.set_active_loop(f"loop-{i}", {"num": i})

        # First one should be evicted
        assert store.get_active_loop("loop-0") is None
        assert store.get_active_loop("loop-5") is not None

    # Auth state tests
    def test_set_and_get_auth_state(self, store):
        """Sets and gets auth state."""
        store.set_auth_state("conn-1", {"user_id": "u1"})
        state = store.get_auth_state("conn-1")

        assert state is not None
        assert state["user_id"] == "u1"

    def test_get_nonexistent_auth_state(self, store):
        """Returns None for nonexistent auth state."""
        assert store.get_auth_state("nonexistent") is None

    def test_delete_auth_state(self, store):
        """Deletes auth state."""
        store.set_auth_state("conn-1", {"user_id": "u1"})
        assert store.delete_auth_state("conn-1") is True
        assert store.get_auth_state("conn-1") is None

    def test_auth_state_lru_eviction(self, store):
        """Evicts oldest auth states when max reached."""
        for i in range(6):
            store.set_auth_state(f"conn-{i}", {"num": i})

        # First one should be evicted
        assert store.get_auth_state("conn-0") is None
        assert store.get_auth_state("conn-5") is not None

    # Pub/Sub tests
    def test_publish_and_subscribe(self, store):
        """Publishes and subscribes to events."""
        received = []
        store.subscribe_events("test-channel", lambda e: received.append(e))

        store.publish_event("test-channel", {"type": "test"})

        assert len(received) == 1
        assert received[0]["type"] == "test"

    def test_multiple_subscribers(self, store):
        """Multiple subscribers receive events."""
        received1 = []
        received2 = []
        store.subscribe_events("channel", lambda e: received1.append(e))
        store.subscribe_events("channel", lambda e: received2.append(e))

        store.publish_event("channel", {"data": 1})

        assert len(received1) == 1
        assert len(received2) == 1

    def test_subscriber_error_doesnt_break_others(self, store):
        """One subscriber error doesn't affect others."""
        received = []

        def failing_handler(e):
            raise ValueError("fail")

        store.subscribe_events("channel", failing_handler)
        store.subscribe_events("channel", lambda e: received.append(e))

        store.publish_event("channel", {"data": 1})
        assert len(received) == 1

    # Cleanup tests
    def test_cleanup_expired(self, store, monkeypatch):
        """Cleans up expired entries."""
        now = 1_000_000.0
        monkeypatch.setattr("aragora.server.session_store.time.time", lambda: now)

        store.set_debate_state("loop-1", {"status": "old"})
        store.set_active_loop("loop-1", {"phase": "old"})
        store.set_auth_state("conn-1", {"user_id": "old"})

        # Advance time beyond TTL (TTL is 1 second)
        now += 2.0

        counts = store.cleanup_expired()

        assert counts["debate_states"] == 1
        assert counts["active_loops"] == 1
        assert counts["auth_states"] == 1

        assert store.get_debate_state("loop-1") is None
        assert store.get_active_loop("loop-1") is None
        assert store.get_auth_state("conn-1") is None

    def test_cleanup_preserves_fresh_entries(self, store):
        """Cleanup preserves non-expired entries."""
        store.set_debate_state("loop-1", {"status": "fresh"})

        counts = store.cleanup_expired()

        assert counts["debate_states"] == 0
        assert store.get_debate_state("loop-1") is not None


class TestInMemorySessionStoreThreadSafety:
    """Thread safety tests for InMemorySessionStore."""

    def test_concurrent_debate_state_operations(self):
        """Handles concurrent debate state operations."""
        store = InMemorySessionStore(SessionStoreConfig(max_debate_states=100))
        errors = []

        def worker(n):
            try:
                for i in range(10):
                    store.set_debate_state(f"loop-{n}-{i}", {"n": n, "i": i})
                    store.get_debate_state(f"loop-{n}-{i}")
                    if i % 2 == 0:
                        store.delete_debate_state(f"loop-{n}-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_pubsub(self):
        """Handles concurrent pub/sub."""
        store = InMemorySessionStore()
        received = []
        lock = threading.Lock()

        def handler(e):
            with lock:
                received.append(e)

        store.subscribe_events("channel", handler)

        def publisher(n):
            for i in range(10):
                store.publish_event("channel", {"n": n, "i": i})

        threads = [threading.Thread(target=publisher, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(received) == 50


class TestGetSessionStore:
    """Tests for get_session_store function."""

    def test_returns_inmemory_store(self):
        """Returns in-memory store when Redis unavailable."""
        store = get_session_store(force_memory=True)
        assert store.is_distributed is False
        assert isinstance(store, InMemorySessionStore)

    def test_returns_singleton(self):
        """Returns same instance on multiple calls."""
        store1 = get_session_store(force_memory=True)
        store2 = get_session_store(force_memory=True)
        assert store1 is store2

    def test_force_memory_skips_redis(self):
        """force_memory=True skips Redis check."""
        # With force_memory=True, Redis is never checked
        store = get_session_store(force_memory=True)
        assert store.is_distributed is False

    def test_falls_back_to_memory_on_redis_error(self):
        """Falls back to in-memory when Redis fails."""
        reset_session_store()
        # The import of is_redis_available happens inside get_session_store
        # Patch at the source module
        with patch("aragora.utils.redis_config.is_redis_available") as mock_check:
            mock_check.side_effect = RuntimeError("Redis connection failed")

            store = get_session_store()
            assert store.is_distributed is False


class TestResetSessionStore:
    """Tests for reset_session_store function."""

    def test_clears_singleton(self):
        """Clears the singleton instance."""
        store1 = get_session_store(force_memory=True)
        reset_session_store()
        store2 = get_session_store(force_memory=True)

        # Should be different instances
        assert store1 is not store2

    def test_calls_close_if_available(self):
        """Calls close() on store if available."""
        store = get_session_store(force_memory=True)
        # Add a close method
        store.close = MagicMock()

        reset_session_store()
        store.close.assert_called_once()


class TestEdgeCases:
    """Edge case tests."""

    def test_store_with_complex_data(self):
        """Handles complex nested data."""
        store = InMemorySessionStore()
        complex_data = {
            "nested": {
                "list": [1, 2, {"deep": True}],
                "dict": {"a": 1, "b": 2},
            },
            "unicode": "🎉 café",
            "none": None,
        }

        store.set_debate_state("loop-1", complex_data)
        retrieved = store.get_debate_state("loop-1")

        assert retrieved["nested"]["list"][2]["deep"] is True
        assert retrieved["unicode"] == "🎉 café"
        assert retrieved["none"] is None

    def test_empty_data(self):
        """Handles empty data."""
        store = InMemorySessionStore()

        store.set_debate_state("loop-1", {})
        store.set_active_loop("loop-1", {})
        store.set_auth_state("conn-1", {})

        assert store.get_debate_state("loop-1") == {}
        assert store.get_active_loop("loop-1") == {}
        assert store.get_auth_state("conn-1") == {}

    def test_overwrite_existing(self):
        """Overwrites existing entries."""
        store = InMemorySessionStore()

        store.set_debate_state("loop-1", {"version": 1})
        store.set_debate_state("loop-1", {"version": 2})

        assert store.get_debate_state("loop-1")["version"] == 2

    def test_access_updates_lru_order(self):
        """Accessing an entry updates LRU order."""
        config = SessionStoreConfig(max_debate_states=3)
        store = InMemorySessionStore(config)

        store.set_debate_state("loop-1", {})
        store.set_debate_state("loop-2", {})
        store.set_debate_state("loop-3", {})

        # Access loop-1 to make it "recent"
        store.get_debate_state("loop-1")

        # Add loop-4, should evict loop-2 (oldest unused)
        store.set_debate_state("loop-4", {})

        assert store.get_debate_state("loop-1") is not None
        assert store.get_debate_state("loop-2") is None
        assert store.get_debate_state("loop-3") is not None
        assert store.get_debate_state("loop-4") is not None


# ============================================================================
# DebateSession Dataclass Tests
# ============================================================================


class TestDebateSession:
    """Tests for the DebateSession dataclass."""

    def test_create_debate_session(self):
        """Creates a debate session with required fields."""
        from aragora.server.session_store import DebateSession

        session = DebateSession(
            session_id="slack:user123:abc",
            channel="slack",
            user_id="user123",
        )

        assert session.session_id == "slack:user123:abc"
        assert session.channel == "slack"
        assert session.user_id == "user123"
        assert session.debate_id is None
        assert session.context == {}
        assert session.created_at > 0
        assert session.last_active > 0

    def test_debate_session_with_context(self):
        """Creates session with custom context."""
        from aragora.server.session_store import DebateSession

        context = {"workspace_id": "W123", "channel_id": "C456"}
        session = DebateSession(
            session_id="slack:user123:abc",
            channel="slack",
            user_id="user123",
            context=context,
        )

        assert session.context["workspace_id"] == "W123"
        assert session.context["channel_id"] == "C456"

    def test_link_debate(self):
        """Links a debate to the session."""
        from aragora.server.session_store import DebateSession

        session = DebateSession(
            session_id="slack:user123:abc",
            channel="slack",
            user_id="user123",
        )
        old_last_active = session.last_active

        import time

        time.sleep(0.01)  # Small delay to ensure timestamp changes

        session.link_debate("debate-456")

        assert session.debate_id == "debate-456"
        assert session.last_active >= old_last_active

    def test_unlink_debate(self):
        """Unlinks the debate from the session."""
        from aragora.server.session_store import DebateSession

        session = DebateSession(
            session_id="slack:user123:abc",
            channel="slack",
            user_id="user123",
            debate_id="debate-456",
        )

        session.unlink_debate()

        assert session.debate_id is None

    def test_touch_updates_last_active(self):
        """Touch updates last_active timestamp."""
        from aragora.server.session_store import DebateSession
        import time

        session = DebateSession(
            session_id="slack:user123:abc",
            channel="slack",
            user_id="user123",
        )
        old_last_active = session.last_active

        time.sleep(0.01)
        session.touch()

        assert session.last_active >= old_last_active

    def test_to_dict_serialization(self):
        """Serializes session to dictionary."""
        from aragora.server.session_store import DebateSession

        session = DebateSession(
            session_id="slack:user123:abc",
            channel="slack",
            user_id="user123",
            debate_id="debate-456",
            context={"key": "value"},
        )

        data = session.to_dict()

        assert data["session_id"] == "slack:user123:abc"
        assert data["channel"] == "slack"
        assert data["user_id"] == "user123"
        assert data["debate_id"] == "debate-456"
        assert data["context"]["key"] == "value"
        assert "created_at" in data
        assert "last_active" in data

    def test_from_dict_deserialization(self):
        """Deserializes session from dictionary."""
        from aragora.server.session_store import DebateSession

        data = {
            "session_id": "telegram:user789:xyz",
            "channel": "telegram",
            "user_id": "user789",
            "debate_id": "debate-999",
            "context": {"chat_id": "12345"},
            "created_at": 1000000.0,
            "last_active": 1000001.0,
        }

        session = DebateSession.from_dict(data)

        assert session.session_id == "telegram:user789:xyz"
        assert session.channel == "telegram"
        assert session.user_id == "user789"
        assert session.debate_id == "debate-999"
        assert session.context["chat_id"] == "12345"
        assert session.created_at == 1000000.0
        assert session.last_active == 1000001.0

    def test_from_dict_with_missing_optional_fields(self):
        """Deserializes with missing optional fields."""
        from aragora.server.session_store import DebateSession

        data = {
            "session_id": "api:user1:abc",
            "channel": "api",
            "user_id": "user1",
        }

        session = DebateSession.from_dict(data)

        assert session.debate_id is None
        assert session.context == {}
        assert session.created_at > 0
        assert session.last_active > 0


# ============================================================================
# VoiceSession Dataclass Tests
# ============================================================================


class TestVoiceSession:
    """Tests for the VoiceSession dataclass."""

    def test_create_voice_session(self):
        """Creates a voice session with required fields."""
        from aragora.server.session_store import VoiceSession

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
        )

        assert session.session_id == "voice-123"
        assert session.user_id == "user456"
        assert session.debate_id is None
        assert session.reconnect_token is None
        assert session.reconnect_expires_at is None
        assert session.is_persistent is False
        assert session.audio_format == "pcm_16khz"
        assert session.last_heartbeat > 0
        assert session.created_at > 0
        assert session.metadata == {}

    def test_voice_session_with_all_fields(self):
        """Creates session with all optional fields."""
        from aragora.server.session_store import VoiceSession

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
            debate_id="debate-789",
            reconnect_token="token-abc",
            reconnect_expires_at=9999999999.0,
            is_persistent=True,
            audio_format="opus",
            metadata={"device": "mobile"},
        )

        assert session.debate_id == "debate-789"
        assert session.reconnect_token == "token-abc"
        assert session.reconnect_expires_at == 9999999999.0
        assert session.is_persistent is True
        assert session.audio_format == "opus"
        assert session.metadata["device"] == "mobile"

    def test_is_reconnectable_with_valid_token(self):
        """Returns True when reconnect token is valid and not expired."""
        from aragora.server.session_store import VoiceSession
        import time

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
            reconnect_token="token-abc",
            reconnect_expires_at=time.time() + 300,  # 5 minutes in future
        )

        assert session.is_reconnectable is True

    def test_is_reconnectable_with_expired_token(self):
        """Returns False when reconnect token is expired."""
        from aragora.server.session_store import VoiceSession
        import time

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
            reconnect_token="token-abc",
            reconnect_expires_at=time.time() - 10,  # Already expired
        )

        assert session.is_reconnectable is False

    def test_is_reconnectable_without_token(self):
        """Returns False when no reconnect token."""
        from aragora.server.session_store import VoiceSession

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
        )

        assert session.is_reconnectable is False

    def test_heartbeat_age(self):
        """Calculates heartbeat age correctly."""
        from aragora.server.session_store import VoiceSession
        import time

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
        )

        time.sleep(0.1)
        age = session.heartbeat_age

        assert age >= 0.1

    def test_touch_heartbeat(self):
        """Updates heartbeat timestamp."""
        from aragora.server.session_store import VoiceSession
        import time

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
        )
        old_heartbeat = session.last_heartbeat

        time.sleep(0.01)
        session.touch_heartbeat()

        assert session.last_heartbeat >= old_heartbeat

    def test_set_reconnect_token(self):
        """Sets reconnect token with TTL."""
        from aragora.server.session_store import VoiceSession
        import time

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
        )

        session.set_reconnect_token("new-token", ttl_seconds=600)

        assert session.reconnect_token == "new-token"
        assert session.reconnect_expires_at > time.time()
        assert session.reconnect_expires_at < time.time() + 601

    def test_clear_reconnect_token(self):
        """Clears reconnect token."""
        from aragora.server.session_store import VoiceSession
        import time

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
            reconnect_token="token-abc",
            reconnect_expires_at=time.time() + 300,
        )

        session.clear_reconnect_token()

        assert session.reconnect_token is None
        assert session.reconnect_expires_at is None

    def test_to_dict_serialization(self):
        """Serializes voice session to dictionary."""
        from aragora.server.session_store import VoiceSession

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
            debate_id="debate-789",
            is_persistent=True,
            audio_format="opus",
            metadata={"quality": "high"},
        )

        data = session.to_dict()

        assert data["session_id"] == "voice-123"
        assert data["user_id"] == "user456"
        assert data["debate_id"] == "debate-789"
        assert data["is_persistent"] is True
        assert data["audio_format"] == "opus"
        assert data["metadata"]["quality"] == "high"

    def test_from_dict_deserialization(self):
        """Deserializes voice session from dictionary."""
        from aragora.server.session_store import VoiceSession

        data = {
            "session_id": "voice-999",
            "user_id": "user111",
            "debate_id": "debate-222",
            "reconnect_token": "tok-333",
            "reconnect_expires_at": 9999999999.0,
            "is_persistent": True,
            "audio_format": "pcm_48khz",
            "last_heartbeat": 1000000.0,
            "created_at": 999999.0,
            "metadata": {"bitrate": 128000},
        }

        session = VoiceSession.from_dict(data)

        assert session.session_id == "voice-999"
        assert session.user_id == "user111"
        assert session.debate_id == "debate-222"
        assert session.reconnect_token == "tok-333"
        assert session.is_persistent is True
        assert session.audio_format == "pcm_48khz"
        assert session.metadata["bitrate"] == 128000


# ============================================================================
# DeviceSession Dataclass Tests
# ============================================================================


class TestDeviceSession:
    """Tests for the DeviceSession dataclass."""

    def test_create_device_session(self):
        """Creates a device session with required fields."""
        from aragora.server.session_store import DeviceSession

        session = DeviceSession(
            device_id="device-123",
            user_id="user456",
            device_type="ios",
            push_token="apns-token-xyz",
        )

        assert session.device_id == "device-123"
        assert session.user_id == "user456"
        assert session.device_type == "ios"
        assert session.push_token == "apns-token-xyz"
        assert session.device_name is None
        assert session.app_version is None
        assert session.last_notified is None
        assert session.notification_count == 0
        assert session.created_at > 0
        assert session.last_active > 0
        assert session.metadata == {}

    def test_device_session_with_all_fields(self):
        """Creates session with all optional fields."""
        from aragora.server.session_store import DeviceSession

        session = DeviceSession(
            device_id="device-123",
            user_id="user456",
            device_type="android",
            push_token="fcm-token-abc",
            device_name="Pixel 7 Pro",
            app_version="2.1.0",
            last_notified=1000000.0,
            notification_count=42,
            metadata={"os_version": "14.0", "model": "pixel7pro"},
        )

        assert session.device_name == "Pixel 7 Pro"
        assert session.app_version == "2.1.0"
        assert session.last_notified == 1000000.0
        assert session.notification_count == 42
        assert session.metadata["os_version"] == "14.0"

    def test_touch_updates_last_active(self):
        """Touch updates last_active timestamp."""
        from aragora.server.session_store import DeviceSession
        import time

        session = DeviceSession(
            device_id="device-123",
            user_id="user456",
            device_type="ios",
            push_token="token",
        )
        old_last_active = session.last_active

        time.sleep(0.01)
        session.touch()

        assert session.last_active >= old_last_active

    def test_record_notification(self):
        """Records notification sent."""
        from aragora.server.session_store import DeviceSession
        import time

        session = DeviceSession(
            device_id="device-123",
            user_id="user456",
            device_type="ios",
            push_token="token",
        )
        assert session.notification_count == 0
        assert session.last_notified is None

        session.record_notification()

        assert session.notification_count == 1
        assert session.last_notified is not None
        assert session.last_notified <= time.time()

        session.record_notification()

        assert session.notification_count == 2

    def test_to_dict_serialization(self):
        """Serializes device session to dictionary."""
        from aragora.server.session_store import DeviceSession

        session = DeviceSession(
            device_id="device-123",
            user_id="user456",
            device_type="web",
            push_token="vapid-key",
            device_name="Chrome Browser",
            app_version="1.0.0",
            notification_count=10,
            metadata={"browser": "chrome"},
        )

        data = session.to_dict()

        assert data["device_id"] == "device-123"
        assert data["user_id"] == "user456"
        assert data["device_type"] == "web"
        assert data["push_token"] == "vapid-key"
        assert data["device_name"] == "Chrome Browser"
        assert data["notification_count"] == 10
        assert data["metadata"]["browser"] == "chrome"

    def test_from_dict_deserialization(self):
        """Deserializes device session from dictionary."""
        from aragora.server.session_store import DeviceSession

        data = {
            "device_id": "device-999",
            "user_id": "user111",
            "device_type": "android",
            "push_token": "fcm-token",
            "device_name": "Samsung Galaxy",
            "app_version": "3.0.0",
            "last_notified": 1000000.0,
            "notification_count": 50,
            "created_at": 999999.0,
            "last_active": 999998.0,
            "metadata": {"manufacturer": "samsung"},
        }

        session = DeviceSession.from_dict(data)

        assert session.device_id == "device-999"
        assert session.user_id == "user111"
        assert session.device_type == "android"
        assert session.push_token == "fcm-token"
        assert session.device_name == "Samsung Galaxy"
        assert session.notification_count == 50
        assert session.metadata["manufacturer"] == "samsung"


# ============================================================================
# InMemorySessionStore - Debate Session Tests
# ============================================================================


class TestInMemoryDebateSessions:
    """Tests for debate session operations in InMemorySessionStore."""

    @pytest.fixture
    def store(self):
        """Fresh in-memory store for each test."""
        return InMemorySessionStore()

    def test_set_and_get_debate_session(self, store):
        """Sets and gets a debate session."""
        from aragora.server.session_store import DebateSession

        session = DebateSession(
            session_id="slack:user1:abc",
            channel="slack",
            user_id="user1",
        )
        store.set_debate_session(session)

        retrieved = store.get_debate_session("slack:user1:abc")

        assert retrieved is not None
        assert retrieved.session_id == "slack:user1:abc"
        assert retrieved.channel == "slack"

    def test_get_nonexistent_debate_session(self, store):
        """Returns None for nonexistent debate session."""
        assert store.get_debate_session("nonexistent") is None

    def test_get_debate_session_updates_last_active(self, store):
        """Getting a session updates its last_active timestamp."""
        from aragora.server.session_store import DebateSession
        import time

        session = DebateSession(
            session_id="slack:user1:abc",
            channel="slack",
            user_id="user1",
        )
        store.set_debate_session(session)
        original_last_active = session.last_active

        time.sleep(0.01)
        retrieved = store.get_debate_session("slack:user1:abc")

        assert retrieved.last_active >= original_last_active

    def test_delete_debate_session(self, store):
        """Deletes a debate session."""
        from aragora.server.session_store import DebateSession

        session = DebateSession(
            session_id="slack:user1:abc",
            channel="slack",
            user_id="user1",
        )
        store.set_debate_session(session)

        assert store.delete_debate_session("slack:user1:abc") is True
        assert store.get_debate_session("slack:user1:abc") is None

    def test_delete_nonexistent_debate_session(self, store):
        """Returns False when deleting nonexistent session."""
        assert store.delete_debate_session("nonexistent") is False

    def test_find_sessions_by_user(self, store):
        """Finds sessions by user ID."""
        from aragora.server.session_store import DebateSession

        session1 = DebateSession(
            session_id="slack:user1:abc",
            channel="slack",
            user_id="user1",
        )
        session2 = DebateSession(
            session_id="telegram:user1:def",
            channel="telegram",
            user_id="user1",
        )
        session3 = DebateSession(
            session_id="slack:user2:ghi",
            channel="slack",
            user_id="user2",
        )

        store.set_debate_session(session1)
        store.set_debate_session(session2)
        store.set_debate_session(session3)

        user1_sessions = store.find_sessions_by_user("user1")

        assert len(user1_sessions) == 2
        session_ids = [s.session_id for s in user1_sessions]
        assert "slack:user1:abc" in session_ids
        assert "telegram:user1:def" in session_ids

    def test_find_sessions_by_user_with_channel_filter(self, store):
        """Finds sessions by user ID filtered by channel."""
        from aragora.server.session_store import DebateSession

        session1 = DebateSession(
            session_id="slack:user1:abc",
            channel="slack",
            user_id="user1",
        )
        session2 = DebateSession(
            session_id="telegram:user1:def",
            channel="telegram",
            user_id="user1",
        )

        store.set_debate_session(session1)
        store.set_debate_session(session2)

        slack_sessions = store.find_sessions_by_user("user1", channel="slack")

        assert len(slack_sessions) == 1
        assert slack_sessions[0].channel == "slack"

    def test_find_sessions_by_debate(self, store):
        """Finds sessions linked to a debate."""
        from aragora.server.session_store import DebateSession

        session1 = DebateSession(
            session_id="slack:user1:abc",
            channel="slack",
            user_id="user1",
            debate_id="debate-123",
        )
        session2 = DebateSession(
            session_id="telegram:user2:def",
            channel="telegram",
            user_id="user2",
            debate_id="debate-123",
        )
        session3 = DebateSession(
            session_id="api:user3:ghi",
            channel="api",
            user_id="user3",
            debate_id="debate-456",
        )

        store.set_debate_session(session1)
        store.set_debate_session(session2)
        store.set_debate_session(session3)

        debate_sessions = store.find_sessions_by_debate("debate-123")

        assert len(debate_sessions) == 2
        session_ids = [s.session_id for s in debate_sessions]
        assert "slack:user1:abc" in session_ids
        assert "telegram:user2:def" in session_ids


# ============================================================================
# InMemorySessionStore - Voice Session Tests
# ============================================================================


class TestInMemoryVoiceSessions:
    """Tests for voice session operations in InMemorySessionStore."""

    @pytest.fixture
    def store(self):
        """Fresh in-memory store with low limits for testing."""
        config = SessionStoreConfig(
            max_voice_sessions=3,
            voice_session_ttl=1,
        )
        return InMemorySessionStore(config)

    def test_set_and_get_voice_session(self, store):
        """Sets and gets a voice session."""
        from aragora.server.session_store import VoiceSession

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
        )
        store.set_voice_session(session)

        retrieved = store.get_voice_session("voice-123")

        assert retrieved is not None
        assert retrieved.session_id == "voice-123"
        assert retrieved.user_id == "user456"

    def test_get_nonexistent_voice_session(self, store):
        """Returns None for nonexistent voice session."""
        assert store.get_voice_session("nonexistent") is None

    def test_get_voice_session_updates_heartbeat(self, store):
        """Getting a session updates its heartbeat."""
        from aragora.server.session_store import VoiceSession
        import time

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
        )
        store.set_voice_session(session)
        original_heartbeat = session.last_heartbeat

        time.sleep(0.01)
        retrieved = store.get_voice_session("voice-123")

        assert retrieved.last_heartbeat >= original_heartbeat

    def test_delete_voice_session(self, store):
        """Deletes a voice session."""
        from aragora.server.session_store import VoiceSession

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
        )
        store.set_voice_session(session)

        assert store.delete_voice_session("voice-123") is True
        assert store.get_voice_session("voice-123") is None

    def test_delete_nonexistent_voice_session(self, store):
        """Returns False when deleting nonexistent session."""
        assert store.delete_voice_session("nonexistent") is False

    def test_find_voice_session_by_token(self, store):
        """Finds voice session by reconnection token."""
        from aragora.server.session_store import VoiceSession
        import time

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
            reconnect_token="token-abc",
            reconnect_expires_at=time.time() + 300,
        )
        store.set_voice_session(session)

        found = store.find_voice_session_by_token("token-abc")

        assert found is not None
        assert found.session_id == "voice-123"

    def test_find_voice_session_by_expired_token(self, store):
        """Returns None for expired reconnection token."""
        from aragora.server.session_store import VoiceSession
        import time

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
            reconnect_token="token-abc",
            reconnect_expires_at=time.time() - 10,  # Already expired
        )
        store.set_voice_session(session)

        found = store.find_voice_session_by_token("token-abc")

        assert found is None

    def test_find_voice_session_by_nonexistent_token(self, store):
        """Returns None for nonexistent token."""
        found = store.find_voice_session_by_token("nonexistent-token")

        assert found is None

    def test_find_voice_sessions_by_user(self, store):
        """Finds all voice sessions for a user."""
        from aragora.server.session_store import VoiceSession

        session1 = VoiceSession(session_id="voice-1", user_id="user1")
        session2 = VoiceSession(session_id="voice-2", user_id="user1")
        session3 = VoiceSession(session_id="voice-3", user_id="user2")

        store.set_voice_session(session1)
        store.set_voice_session(session2)
        store.set_voice_session(session3)

        user1_sessions = store.find_voice_sessions_by_user("user1")

        assert len(user1_sessions) == 2
        session_ids = [s.session_id for s in user1_sessions]
        assert "voice-1" in session_ids
        assert "voice-2" in session_ids

    def test_voice_session_lru_eviction(self, store):
        """Evicts oldest voice sessions when max reached."""
        from aragora.server.session_store import VoiceSession
        import time

        # Create 4 sessions (max is 3)
        for i in range(4):
            session = VoiceSession(
                session_id=f"voice-{i}",
                user_id="user1",
            )
            store.set_voice_session(session)
            time.sleep(0.01)  # Ensure different created_at

        # First one should be evicted
        assert store.get_voice_session("voice-0") is None
        assert store.get_voice_session("voice-1") is not None
        assert store.get_voice_session("voice-2") is not None
        assert store.get_voice_session("voice-3") is not None


# ============================================================================
# InMemorySessionStore - Device Session Tests
# ============================================================================


class TestInMemoryDeviceSessions:
    """Tests for device session operations in InMemorySessionStore."""

    @pytest.fixture
    def store(self):
        """Fresh in-memory store with low limits for testing."""
        config = SessionStoreConfig(
            max_device_sessions=3,
            device_session_ttl=1,
        )
        return InMemorySessionStore(config)

    def test_set_and_get_device_session(self, store):
        """Sets and gets a device session."""
        from aragora.server.session_store import DeviceSession

        session = DeviceSession(
            device_id="device-123",
            user_id="user456",
            device_type="ios",
            push_token="apns-token",
        )
        store.set_device_session(session)

        retrieved = store.get_device_session("device-123")

        assert retrieved is not None
        assert retrieved.device_id == "device-123"
        assert retrieved.user_id == "user456"
        assert retrieved.device_type == "ios"

    def test_get_nonexistent_device_session(self, store):
        """Returns None for nonexistent device session."""
        assert store.get_device_session("nonexistent") is None

    def test_get_device_session_updates_last_active(self, store):
        """Getting a session updates its last_active."""
        from aragora.server.session_store import DeviceSession
        import time

        session = DeviceSession(
            device_id="device-123",
            user_id="user456",
            device_type="ios",
            push_token="apns-token",
        )
        store.set_device_session(session)
        original_last_active = session.last_active

        time.sleep(0.01)
        retrieved = store.get_device_session("device-123")

        assert retrieved.last_active >= original_last_active

    def test_delete_device_session(self, store):
        """Deletes a device session."""
        from aragora.server.session_store import DeviceSession

        session = DeviceSession(
            device_id="device-123",
            user_id="user456",
            device_type="ios",
            push_token="apns-token",
        )
        store.set_device_session(session)

        assert store.delete_device_session("device-123") is True
        assert store.get_device_session("device-123") is None

    def test_delete_nonexistent_device_session(self, store):
        """Returns False when deleting nonexistent session."""
        assert store.delete_device_session("nonexistent") is False

    def test_find_device_by_token(self, store):
        """Finds device session by push token."""
        from aragora.server.session_store import DeviceSession

        session = DeviceSession(
            device_id="device-123",
            user_id="user456",
            device_type="ios",
            push_token="unique-apns-token",
        )
        store.set_device_session(session)

        found = store.find_device_by_token("unique-apns-token")

        assert found is not None
        assert found.device_id == "device-123"

    def test_find_device_by_nonexistent_token(self, store):
        """Returns None for nonexistent token."""
        found = store.find_device_by_token("nonexistent-token")

        assert found is None

    def test_find_devices_by_user(self, store):
        """Finds all devices for a user."""
        from aragora.server.session_store import DeviceSession

        session1 = DeviceSession(
            device_id="device-1",
            user_id="user1",
            device_type="ios",
            push_token="token-1",
        )
        session2 = DeviceSession(
            device_id="device-2",
            user_id="user1",
            device_type="android",
            push_token="token-2",
        )
        session3 = DeviceSession(
            device_id="device-3",
            user_id="user2",
            device_type="web",
            push_token="token-3",
        )

        store.set_device_session(session1)
        store.set_device_session(session2)
        store.set_device_session(session3)

        user1_devices = store.find_devices_by_user("user1")

        assert len(user1_devices) == 2
        device_ids = [d.device_id for d in user1_devices]
        assert "device-1" in device_ids
        assert "device-2" in device_ids

    def test_device_session_lru_eviction(self, store):
        """Evicts oldest device sessions when max reached."""
        from aragora.server.session_store import DeviceSession
        import time

        # Create 4 sessions (max is 3)
        for i in range(4):
            session = DeviceSession(
                device_id=f"device-{i}",
                user_id="user1",
                device_type="ios",
                push_token=f"token-{i}",
            )
            store.set_device_session(session)
            time.sleep(0.01)  # Ensure different last_active

        # First one should be evicted
        assert store.get_device_session("device-0") is None
        assert store.get_device_session("device-1") is not None
        assert store.get_device_session("device-2") is not None
        assert store.get_device_session("device-3") is not None

    def test_update_device_token_updates_index(self, store):
        """Updating device push token updates the token index."""
        from aragora.server.session_store import DeviceSession

        session = DeviceSession(
            device_id="device-123",
            user_id="user456",
            device_type="ios",
            push_token="old-token",
        )
        store.set_device_session(session)

        # Old token should find the device
        assert store.find_device_by_token("old-token") is not None

        # Update with new token
        session.push_token = "new-token"
        store.set_device_session(session)

        # Old token should no longer work
        assert store.find_device_by_token("old-token") is None
        # New token should work
        assert store.find_device_by_token("new-token") is not None


# ============================================================================
# Cleanup Tests for Extended Session Types
# ============================================================================


class TestCleanupExtendedSessions:
    """Tests for cleanup of voice and device sessions."""

    def test_cleanup_expired_voice_sessions(self, monkeypatch):
        """Cleans up expired voice sessions."""
        config = SessionStoreConfig(voice_session_ttl=1)
        store = InMemorySessionStore(config)

        from aragora.server.session_store import VoiceSession

        now = 1_000_000.0
        monkeypatch.setattr("aragora.server.session_store.time.time", lambda: now)

        session = VoiceSession(
            session_id="voice-123",
            user_id="user456",
        )
        store.set_voice_session(session)

        # Advance time beyond TTL
        now += 2.0

        counts = store.cleanup_expired()

        assert counts["voice_sessions"] == 1
        assert store.get_voice_session("voice-123") is None

    def test_cleanup_expired_device_sessions(self, monkeypatch):
        """Cleans up expired device sessions."""
        config = SessionStoreConfig(device_session_ttl=1)
        store = InMemorySessionStore(config)

        from aragora.server.session_store import DeviceSession

        now = 1_000_000.0
        monkeypatch.setattr("aragora.server.session_store.time.time", lambda: now)

        session = DeviceSession(
            device_id="device-123",
            user_id="user456",
            device_type="ios",
            push_token="token",
        )
        store.set_device_session(session)

        # Advance time beyond TTL
        now += 2.0

        counts = store.cleanup_expired()

        assert counts["device_sessions"] == 1
        assert store.get_device_session("device-123") is None
        # Token index should also be cleaned
        assert store.find_device_by_token("token") is None


# ============================================================================
# Edge Cases and Special Characters Tests
# ============================================================================


class TestSessionStoreEdgeCases:
    """Edge case tests for session store."""

    def test_session_with_unicode_data(self):
        """Handles Unicode in session data."""
        store = InMemorySessionStore()
        from aragora.server.session_store import DebateSession

        session = DebateSession(
            session_id="unicode:test",
            channel="telegram",
            user_id="user-cafe",
            context={
                "message": "Hello from Brasil",
                "emoji": "vote",
                "chinese": "debate",
                "arabic": "arabic word",
            },
        )
        store.set_debate_session(session)

        retrieved = store.get_debate_session("unicode:test")

        assert retrieved.context["emoji"] == "vote"
        assert retrieved.context["chinese"] == "debate"

    def test_session_with_special_characters_in_id(self):
        """Handles special characters in session IDs."""
        store = InMemorySessionStore()
        from aragora.server.session_store import DebateSession

        special_id = "channel:user@domain.com:abc-123_456"
        session = DebateSession(
            session_id=special_id,
            channel="email",
            user_id="user@domain.com",
        )
        store.set_debate_session(session)

        retrieved = store.get_debate_session(special_id)

        assert retrieved is not None
        assert retrieved.session_id == special_id

    def test_session_with_large_context(self):
        """Handles large context data."""
        store = InMemorySessionStore()
        from aragora.server.session_store import DebateSession

        large_context = {
            "data": "x" * 10000,  # 10KB of data
            "list": list(range(1000)),
            "nested": {"deep": {"deeper": {"deepest": "value"}}},
        }

        session = DebateSession(
            session_id="large:test",
            channel="api",
            user_id="user1",
            context=large_context,
        )
        store.set_debate_session(session)

        retrieved = store.get_debate_session("large:test")

        assert len(retrieved.context["data"]) == 10000
        assert len(retrieved.context["list"]) == 1000
        assert retrieved.context["nested"]["deep"]["deeper"]["deepest"] == "value"

    def test_session_with_empty_strings(self):
        """Handles empty strings in session fields."""
        store = InMemorySessionStore()
        from aragora.server.session_store import DebateSession

        session = DebateSession(
            session_id="empty:test",
            channel="",  # Empty channel
            user_id="",  # Empty user
            context={"key": ""},  # Empty value
        )
        store.set_debate_session(session)

        retrieved = store.get_debate_session("empty:test")

        assert retrieved.channel == ""
        assert retrieved.user_id == ""
        assert retrieved.context["key"] == ""

    def test_voice_session_with_none_metadata(self):
        """Handles None values in voice session metadata."""
        store = InMemorySessionStore()
        from aragora.server.session_store import VoiceSession

        session = VoiceSession(
            session_id="voice-none",
            user_id="user1",
            metadata={"optional_field": None},
        )
        store.set_voice_session(session)

        retrieved = store.get_voice_session("voice-none")

        assert retrieved.metadata["optional_field"] is None

    def test_device_session_token_collision(self):
        """Handles token collision when updating devices."""
        store = InMemorySessionStore()
        from aragora.server.session_store import DeviceSession

        # Create two devices with different tokens
        device1 = DeviceSession(
            device_id="device-1",
            user_id="user1",
            device_type="ios",
            push_token="shared-token",
        )
        device2 = DeviceSession(
            device_id="device-2",
            user_id="user1",
            device_type="android",
            push_token="other-token",
        )

        store.set_device_session(device1)
        store.set_device_session(device2)

        # Now update device2 to use the same token as device1
        device2.push_token = "shared-token"
        store.set_device_session(device2)

        # The token should now point to device2
        found = store.find_device_by_token("shared-token")
        assert found.device_id == "device-2"


# ============================================================================
# Concurrent Access Tests for Extended Session Types
# ============================================================================


class TestConcurrentSessionAccess:
    """Concurrent access tests for session operations."""

    def test_concurrent_debate_session_operations(self):
        """Handles concurrent debate session operations."""
        store = InMemorySessionStore()
        from aragora.server.session_store import DebateSession

        errors = []

        def worker(n):
            try:
                for i in range(10):
                    session = DebateSession(
                        session_id=f"session-{n}-{i}",
                        channel="slack",
                        user_id=f"user-{n}",
                    )
                    store.set_debate_session(session)
                    store.get_debate_session(f"session-{n}-{i}")
                    store.find_sessions_by_user(f"user-{n}")
                    if i % 2 == 0:
                        store.delete_debate_session(f"session-{n}-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_voice_session_operations(self):
        """Handles concurrent voice session operations."""
        store = InMemorySessionStore()
        from aragora.server.session_store import VoiceSession

        errors = []

        def worker(n):
            try:
                for i in range(10):
                    session = VoiceSession(
                        session_id=f"voice-{n}-{i}",
                        user_id=f"user-{n}",
                    )
                    store.set_voice_session(session)
                    store.get_voice_session(f"voice-{n}-{i}")
                    store.find_voice_sessions_by_user(f"user-{n}")
                    if i % 2 == 0:
                        store.delete_voice_session(f"voice-{n}-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_device_session_operations(self):
        """Handles concurrent device session operations."""
        store = InMemorySessionStore()
        from aragora.server.session_store import DeviceSession

        errors = []

        def worker(n):
            try:
                for i in range(10):
                    session = DeviceSession(
                        device_id=f"device-{n}-{i}",
                        user_id=f"user-{n}",
                        device_type="ios",
                        push_token=f"token-{n}-{i}",
                    )
                    store.set_device_session(session)
                    store.get_device_session(f"device-{n}-{i}")
                    store.find_device_by_token(f"token-{n}-{i}")
                    store.find_devices_by_user(f"user-{n}")
                    if i % 2 == 0:
                        store.delete_device_session(f"device-{n}-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ============================================================================
# SessionStoreConfig Extended Tests
# ============================================================================


class TestSessionStoreConfigExtended:
    """Extended tests for SessionStoreConfig."""

    def test_voice_and_device_session_defaults(self):
        """Config has correct defaults for voice and device sessions."""
        config = SessionStoreConfig()

        assert config.max_voice_sessions > 0
        assert config.max_device_sessions > 0
        assert config.voice_session_ttl > 0
        assert config.device_session_ttl > 0

    def test_custom_voice_device_settings(self):
        """Config accepts custom voice and device settings."""
        config = SessionStoreConfig(
            max_voice_sessions=50,
            max_device_sessions=100,
            voice_session_ttl=7200,
            device_session_ttl=604800,
        )

        assert config.max_voice_sessions == 50
        assert config.max_device_sessions == 100
        assert config.voice_session_ttl == 7200
        assert config.device_session_ttl == 604800


# ============================================================================
# Integration Tests
# ============================================================================


class TestSessionStoreIntegration:
    """Integration tests for session store workflows."""

    def test_debate_session_lifecycle(self):
        """Tests complete debate session lifecycle."""
        store = InMemorySessionStore()
        from aragora.server.session_store import DebateSession

        # 1. Create session
        session = DebateSession(
            session_id="slack:user1:abc",
            channel="slack",
            user_id="user1",
        )
        store.set_debate_session(session)

        # 2. Link to debate
        retrieved = store.get_debate_session("slack:user1:abc")
        retrieved.link_debate("debate-123")
        store.set_debate_session(retrieved)

        # 3. Verify debate link
        linked = store.get_debate_session("slack:user1:abc")
        assert linked.debate_id == "debate-123"

        # 4. Find by debate
        debate_sessions = store.find_sessions_by_debate("debate-123")
        assert len(debate_sessions) == 1

        # 5. Unlink and cleanup
        linked.unlink_debate()
        store.set_debate_session(linked)
        store.delete_debate_session("slack:user1:abc")

        assert store.get_debate_session("slack:user1:abc") is None

    def test_voice_session_reconnection_flow(self):
        """Tests voice session reconnection workflow."""
        store = InMemorySessionStore()
        from aragora.server.session_store import VoiceSession

        # 1. Create persistent voice session
        session = VoiceSession(
            session_id="voice-123",
            user_id="user1",
            is_persistent=True,
        )
        store.set_voice_session(session)

        # 2. Disconnect - set reconnect token
        session = store.get_voice_session("voice-123")
        session.set_reconnect_token("reconnect-token-abc", ttl_seconds=300)
        store.set_voice_session(session)

        # 3. Reconnect using token
        reconnected = store.find_voice_session_by_token("reconnect-token-abc")
        assert reconnected is not None
        assert reconnected.session_id == "voice-123"

        # 4. Clear reconnect token after successful reconnect
        reconnected.clear_reconnect_token()
        store.set_voice_session(reconnected)

        # 5. Token should no longer work
        assert store.find_voice_session_by_token("reconnect-token-abc") is None

    def test_multi_device_push_notification_flow(self):
        """Tests multi-device push notification workflow."""
        store = InMemorySessionStore()
        from aragora.server.session_store import DeviceSession

        # 1. Register multiple devices for user
        devices = [
            DeviceSession(
                device_id=f"device-{i}",
                user_id="user1",
                device_type=["ios", "android", "web"][i % 3],
                push_token=f"token-{i}",
                device_name=f"Device {i}",
            )
            for i in range(3)
        ]

        for device in devices:
            store.set_device_session(device)

        # 2. Find all user devices
        user_devices = store.find_devices_by_user("user1")
        assert len(user_devices) == 3

        # 3. Record notification for each
        for device in user_devices:
            device.record_notification()
            store.set_device_session(device)

        # 4. Verify notification counts
        for i in range(3):
            device = store.get_device_session(f"device-{i}")
            assert device.notification_count == 1

        # 5. Remove stale device
        store.delete_device_session("device-0")
        user_devices = store.find_devices_by_user("user1")
        assert len(user_devices) == 2
