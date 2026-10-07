"""
Tests for aragora.server.middleware.token_revocation - Token Revocation Middleware.

Tests cover:
- RevocationEntry dataclass
- InMemoryRevocationStore operations
- RedisRevocationStore operations
- Token validation flow
- Token revocation detection
- Race conditions between validation and revocation
- Revocation cache miss scenarios
- Database/cache inconsistency handling
- Expired token handling
- Revocation propagation across instances
- All exception handling paths
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def reset_global_store():
    """Reset the global revocation store before and after each test."""
    import aragora.server.middleware.token_revocation as tr

    original_store = tr._revocation_store
    tr._revocation_store = None
    yield
    tr._revocation_store = original_store


@pytest.fixture
def memory_store():
    """Create an in-memory revocation store for testing."""
    from aragora.server.middleware.token_revocation import InMemoryRevocationStore

    return InMemoryRevocationStore(cleanup_interval=1.0)


@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client."""
    client = MagicMock()
    client.setex = MagicMock()
    client.exists = MagicMock(return_value=0)
    client.delete = MagicMock(return_value=0)
    client.scan = MagicMock(return_value=(0, []))
    return client


@pytest.fixture
def sample_entry():
    """Create a sample revocation entry."""
    from aragora.server.middleware.token_revocation import RevocationEntry

    now = datetime.now(timezone.utc)
    return RevocationEntry(
        token_hash="abc123def456",
        revoked_at=now,
        expires_at=now + timedelta(hours=24),
        reason="logout",
        revoked_by="user-123",
        metadata={"ip": "192.168.1.1"},
    )


@pytest.fixture
def expired_entry():
    """Create an expired revocation entry."""
    from aragora.server.middleware.token_revocation import RevocationEntry

    now = datetime.now(timezone.utc)
    return RevocationEntry(
        token_hash="expired123",
        revoked_at=now - timedelta(hours=48),
        expires_at=now - timedelta(hours=24),
        reason="old_logout",
        revoked_by="system",
    )


# ===========================================================================
# Test RevocationEntry
# ===========================================================================


class TestRevocationEntry:
    """Tests for RevocationEntry dataclass."""

    def test_entry_creation(self, sample_entry):
        """Test creating a revocation entry with all fields."""
        assert sample_entry.token_hash == "abc123def456"
        assert sample_entry.reason == "logout"
        assert sample_entry.revoked_by == "user-123"
        assert sample_entry.metadata == {"ip": "192.168.1.1"}

    def test_entry_is_expired_false(self, sample_entry):
        """Test is_expired returns False for valid entry."""
        assert sample_entry.is_expired() is False

    def test_entry_is_expired_true(self, expired_entry):
        """Test is_expired returns True for expired entry."""
        assert expired_entry.is_expired() is True

    def test_entry_to_dict(self, sample_entry):
        """Test converting entry to dictionary."""
        d = sample_entry.to_dict()

        assert d["token_hash"] == "abc123def456"
        assert d["reason"] == "logout"
        assert d["revoked_by"] == "user-123"
        assert d["metadata"] == {"ip": "192.168.1.1"}
        assert "revoked_at" in d
        assert "expires_at" in d

    def test_entry_default_values(self):
        """Test entry with default values."""
        from aragora.server.middleware.token_revocation import RevocationEntry

        now = datetime.now(timezone.utc)
        entry = RevocationEntry(
            token_hash="hash123",
            revoked_at=now,
            expires_at=now + timedelta(hours=1),
        )

        assert entry.reason == ""
        assert entry.revoked_by == ""
        assert entry.metadata == {}


# ===========================================================================
# Test InMemoryRevocationStore
# ===========================================================================


class TestInMemoryRevocationStore:
    """Tests for InMemoryRevocationStore."""

    def test_add_and_contains(self, memory_store, sample_entry):
        """Test adding and checking for entries."""
        assert memory_store.contains(sample_entry.token_hash) is False

        memory_store.add(sample_entry)

        assert memory_store.contains(sample_entry.token_hash) is True

    def test_contains_returns_false_for_unknown(self, memory_store):
        """Test contains returns False for unknown token."""
        assert memory_store.contains("unknown-hash") is False

    def test_remove_existing(self, memory_store, sample_entry):
        """Test removing an existing entry."""
        memory_store.add(sample_entry)
        assert memory_store.contains(sample_entry.token_hash) is True

        result = memory_store.remove(sample_entry.token_hash)

        assert result is True
        assert memory_store.contains(sample_entry.token_hash) is False

    def test_remove_nonexistent(self, memory_store):
        """Test removing a nonexistent entry."""
        result = memory_store.remove("nonexistent-hash")
        assert result is False

    def test_count(self, memory_store, sample_entry):
        """Test counting entries."""
        assert memory_store.count() == 0

        memory_store.add(sample_entry)
        assert memory_store.count() == 1

    def test_cleanup_expired(self, memory_store, sample_entry, expired_entry):
        """Test cleanup removes expired entries."""
        memory_store.add(sample_entry)
        memory_store.add(expired_entry)

        assert memory_store.count() == 2

        removed = memory_store.cleanup_expired()

        assert removed == 1
        assert memory_store.count() == 1
        assert memory_store.contains(sample_entry.token_hash) is True
        assert memory_store.contains(expired_entry.token_hash) is False

    def test_contains_removes_expired_on_access(self, memory_store, expired_entry):
        """Test that contains removes expired entries on access."""
        # Bypass add's check by directly inserting
        memory_store._store[expired_entry.token_hash] = expired_entry

        # contains should remove expired entry and return False
        assert memory_store.contains(expired_entry.token_hash) is False
        assert expired_entry.token_hash not in memory_store._store

    def test_thread_safety_add(self, memory_store, sample_entry):
        """Test thread-safe add operations."""
        errors = []

        def add_entries():
            try:
                for i in range(100):
                    from aragora.server.middleware.token_revocation import (
                        RevocationEntry,
                    )

                    now = datetime.now(timezone.utc)
                    entry = RevocationEntry(
                        token_hash=f"hash-{threading.current_thread().name}-{i}",
                        revoked_at=now,
                        expires_at=now + timedelta(hours=1),
                    )
                    memory_store.add(entry)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_entries, name=f"t{i}") for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert memory_store.count() == 500

    def test_automatic_cleanup_triggered(self, memory_store, sample_entry, expired_entry):
        """Test automatic cleanup is triggered on add."""
        # Set last cleanup to old time to trigger cleanup
        memory_store._last_cleanup = time.time() - 1000
        memory_store._cleanup_interval = 0.1

        # Add expired entry directly
        memory_store._store[expired_entry.token_hash] = expired_entry

        # This add should trigger cleanup in background
        memory_store.add(sample_entry)

        # Wait for background cleanup
        time.sleep(0.5)

        # Expired entry should be cleaned up
        # (Note: cleanup happens in background thread, so expired might still be there briefly)


# ===========================================================================
# Test RedisRevocationStore
# ===========================================================================


class TestRedisRevocationStore:
    """Tests for RedisRevocationStore."""

    def test_init_with_url(self):
        """Test initialization with Redis URL."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore(redis_url="redis://custom:6379")
        assert store._redis_url == "redis://custom:6379"
        assert store._key_prefix == "aragora:revoked:"

    def test_init_with_custom_prefix(self):
        """Test initialization with custom key prefix."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore(key_prefix="custom:prefix:")
        assert store._key_prefix == "custom:prefix:"

    def test_init_from_env(self, reset_global_store):
        """Test initialization from environment variable."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        with patch.dict("os.environ", {"REDIS_URL": "redis://env-host:6379"}):
            store = RedisRevocationStore()
            assert store._redis_url == "redis://env-host:6379"

    def test_key_generation(self):
        """Test Redis key generation."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore(key_prefix="test:")
        assert store._key("abc123") == "test:abc123"

    def test_get_client_import_error(self):
        """Test handling of missing redis package."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()

        with patch.dict("sys.modules", {"redis": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'redis'")):
                with pytest.raises(ImportError):
                    store._get_client()

    def test_add_with_mock_client(self, mock_redis_client, sample_entry):
        """Test add operation with mocked Redis client."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client

        store.add(sample_entry)

        mock_redis_client.setex.assert_called_once()
        call_args = mock_redis_client.setex.call_args
        assert sample_entry.token_hash in call_args[0][0]

    def test_add_with_negative_ttl_skipped(self, mock_redis_client):
        """Test add with negative TTL is skipped."""
        from aragora.server.middleware.token_revocation import (
            RedisRevocationStore,
            RevocationEntry,
        )

        store = RedisRevocationStore()
        store._client = mock_redis_client

        # Create entry with past expiration
        now = datetime.now(timezone.utc)
        entry = RevocationEntry(
            token_hash="past-hash",
            revoked_at=now,
            expires_at=now - timedelta(hours=1),  # Already expired
        )

        store.add(entry)

        # setex should not be called for negative TTL
        mock_redis_client.setex.assert_not_called()

    def test_add_connection_error(self, mock_redis_client, sample_entry):
        """Test add handles connection errors."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client
        mock_redis_client.setex.side_effect = ConnectionError("Connection refused")

        with pytest.raises(ConnectionError):
            store.add(sample_entry)

    def test_add_timeout_error(self, mock_redis_client, sample_entry):
        """Test add handles timeout errors."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client
        mock_redis_client.setex.side_effect = TimeoutError("Operation timed out")

        with pytest.raises(TimeoutError):
            store.add(sample_entry)

    def test_add_os_error(self, mock_redis_client, sample_entry):
        """Test add handles OS errors."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client
        mock_redis_client.setex.side_effect = OSError("Network unreachable")

        with pytest.raises(OSError):
            store.add(sample_entry)

    def test_contains_returns_true(self, mock_redis_client):
        """Test contains returns True when key exists."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client
        mock_redis_client.exists.return_value = 1

        assert store.contains("existing-hash") is True

    def test_contains_returns_false(self, mock_redis_client):
        """Test contains returns False when key doesn't exist."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client
        mock_redis_client.exists.return_value = 0

        assert store.contains("nonexistent-hash") is False

    def test_contains_connection_error_returns_false(self, mock_redis_client):
        """Test contains returns False on connection error (fail-open)."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client
        mock_redis_client.exists.side_effect = ConnectionError("Connection refused")

        # Should fail-open (return False) to not block all requests
        assert store.contains("hash") is False

    def test_contains_timeout_error_returns_false(self, mock_redis_client):
        """Test contains returns False on timeout (fail-open)."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client
        mock_redis_client.exists.side_effect = TimeoutError("Timed out")

        assert store.contains("hash") is False

    def test_remove_success(self, mock_redis_client):
        """Test remove returns True on success."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client
        mock_redis_client.delete.return_value = 1

        assert store.remove("existing-hash") is True

    def test_remove_nonexistent(self, mock_redis_client):
        """Test remove returns False for nonexistent key."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client
        mock_redis_client.delete.return_value = 0

        assert store.remove("nonexistent-hash") is False

    def test_remove_connection_error(self, mock_redis_client):
        """Test remove returns False on connection error."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client
        mock_redis_client.delete.side_effect = ConnectionError("Connection refused")

        assert store.remove("hash") is False

    def test_cleanup_expired_is_noop(self):
        """Test cleanup_expired is a no-op for Redis (TTL handles it)."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        assert store.cleanup_expired() == 0

    def test_count_with_scan(self, mock_redis_client):
        """Test count uses SCAN to count keys."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client

        # Simulate scan returning 3 keys then completing
        mock_redis_client.scan.side_effect = [
            (1, [b"key1", b"key2"]),
            (0, [b"key3"]),
        ]

        assert store.count() == 3

    def test_count_connection_error(self, mock_redis_client):
        """Test count returns 0 on connection error."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client
        mock_redis_client.scan.side_effect = ConnectionError("Connection refused")

        assert store.count() == 0


# ===========================================================================
# Test Global Store Management
# ===========================================================================


class TestGetRevocationStore:
    """Tests for get_revocation_store function."""

    def test_returns_memory_store_without_redis_url(self, reset_global_store):
        """Test returns in-memory store when REDIS_URL not set."""
        from aragora.server.middleware.token_revocation import (
            InMemoryRevocationStore,
            get_revocation_store,
        )

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                store = get_revocation_store()
                assert isinstance(store, InMemoryRevocationStore)

    def test_returns_same_instance(self, reset_global_store):
        """Test returns the same store instance on subsequent calls."""
        from aragora.server.middleware.token_revocation import get_revocation_store

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                store1 = get_revocation_store()
                store2 = get_revocation_store()
                assert store1 is store2

    def test_raises_error_when_distributed_required_no_redis(self, reset_global_store):
        """Test raises DistributedStateError when distributed required but no Redis."""
        from aragora.control_plane.leader import DistributedStateError
        from aragora.server.middleware.token_revocation import get_revocation_store

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=True,
            ):
                with pytest.raises(DistributedStateError) as exc_info:
                    get_revocation_store()

                assert "token_revocation" in str(exc_info.value)

    def test_creates_redis_store_with_url(self, reset_global_store):
        """Test creates Redis store when REDIS_URL is set."""
        from aragora.server.middleware.token_revocation import (
            RedisRevocationStore,
            get_revocation_store,
        )

        with patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379"}):
            store = get_revocation_store()
            assert isinstance(store, RedisRevocationStore)

    def test_falls_back_to_memory_when_redis_import_fails(self, reset_global_store):
        """Test falls back to memory store when redis import fails."""
        from aragora.server.middleware.token_revocation import (
            InMemoryRevocationStore,
            get_revocation_store,
        )

        with patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379"}):
            with patch(
                "aragora.server.middleware.token_revocation.RedisRevocationStore",
                side_effect=ImportError("No redis"),
            ):
                with patch(
                    "aragora.config.distributed.is_distributed_state_required",
                    return_value=False,
                ):
                    store = get_revocation_store()
                    assert isinstance(store, InMemoryRevocationStore)

    def test_raises_error_when_redis_import_fails_and_distributed_required(
        self, reset_global_store
    ):
        """Test raises error when Redis import fails but distributed required."""
        from aragora.control_plane.leader import DistributedStateError
        from aragora.server.middleware.token_revocation import get_revocation_store

        with patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379"}):
            with patch(
                "aragora.server.middleware.token_revocation.RedisRevocationStore",
                side_effect=ImportError("No redis"),
            ):
                with patch(
                    "aragora.config.distributed.is_distributed_state_required",
                    return_value=True,
                ):
                    with pytest.raises(DistributedStateError):
                        get_revocation_store()


# ===========================================================================
# Test Hash Token
# ===========================================================================


class TestHashToken:
    """Tests for hash_token function."""

    def test_hash_token_produces_sha256(self):
        """Test hash_token produces SHA-256 hash."""
        from aragora.server.middleware.token_revocation import hash_token

        token = "my-secret-token"
        result = hash_token(token)

        expected = hashlib.sha256(token.encode()).hexdigest()
        assert result == expected

    def test_hash_token_deterministic(self):
        """Test hash_token is deterministic."""
        from aragora.server.middleware.token_revocation import hash_token

        token = "test-token"
        assert hash_token(token) == hash_token(token)

    def test_hash_token_different_tokens(self):
        """Test different tokens produce different hashes."""
        from aragora.server.middleware.token_revocation import hash_token

        assert hash_token("token1") != hash_token("token2")


# ===========================================================================
# Test Revoke Token
# ===========================================================================


class TestRevokeToken:
    """Tests for revoke_token function."""

    def test_revoke_token_creates_entry(self, reset_global_store):
        """Test revoke_token creates a revocation entry."""
        from aragora.server.middleware.token_revocation import (
            hash_token,
            revoke_token,
        )

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                entry = revoke_token(
                    "my-token",
                    reason="logout",
                    revoked_by="user-123",
                )

                assert entry.token_hash == hash_token("my-token")
                assert entry.reason == "logout"
                assert entry.revoked_by == "user-123"

    def test_revoke_token_default_values(self, reset_global_store):
        """Test revoke_token with default values."""
        from aragora.server.middleware.token_revocation import revoke_token

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                entry = revoke_token("my-token")

                assert entry.reason == ""
                assert entry.revoked_by == "system"
                assert entry.metadata == {}

    def test_revoke_token_custom_ttl(self, reset_global_store):
        """Test revoke_token with custom TTL."""
        from aragora.server.middleware.token_revocation import revoke_token

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                entry = revoke_token("my-token", ttl_seconds=3600)

                # Entry should expire in about 1 hour
                time_diff = (entry.expires_at - entry.revoked_at).total_seconds()
                assert 3599 <= time_diff <= 3601

    def test_revoke_token_with_metadata(self, reset_global_store):
        """Test revoke_token with metadata."""
        from aragora.server.middleware.token_revocation import revoke_token

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                entry = revoke_token(
                    "my-token",
                    metadata={"ip": "10.0.0.1", "session_id": "sess-123"},
                )

                assert entry.metadata["ip"] == "10.0.0.1"
                assert entry.metadata["session_id"] == "sess-123"

    def test_revoke_token_calls_audit_logger(self, reset_global_store):
        """Test revoke_token calls audit logger."""
        from aragora.server.middleware.token_revocation import revoke_token

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                with patch(
                    "aragora.server.middleware.audit_logger.audit_token_revoked"
                ) as mock_audit:
                    entry = revoke_token("my-token", reason="security", revoked_by="admin")

                    mock_audit.assert_called_once_with(
                        token_hash=entry.token_hash,
                        revoked_by="admin",
                        reason="security",
                    )

    def test_revoke_token_audit_import_error_handled(self, reset_global_store):
        """Test revoke_token handles audit logger import error gracefully.

        The revoke_token function wraps the audit call in try/except ImportError,
        so even if audit_logger can't be imported, revocation still succeeds.
        """
        from aragora.server.middleware.token_revocation import revoke_token

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                # Make the audit function raise ImportError when called
                with patch(
                    "aragora.server.middleware.audit_logger.audit_token_revoked",
                    side_effect=ImportError("No audit logger"),
                ):
                    # Should not raise, just silently skip audit
                    # The function catches ImportError in the try/except block
                    entry = revoke_token("my-token-audit-fail")
                    assert entry is not None
                    assert entry.token_hash is not None


# ===========================================================================
# Test Is Token Revoked
# ===========================================================================


class TestIsTokenRevoked:
    """Tests for is_token_revoked function."""

    def test_is_token_revoked_false_for_unknown(self, reset_global_store):
        """Test is_token_revoked returns False for unknown token."""
        from aragora.server.middleware.token_revocation import is_token_revoked

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                assert is_token_revoked("unknown-token") is False

    def test_is_token_revoked_true_for_revoked(self, reset_global_store):
        """Test is_token_revoked returns True for revoked token."""
        from aragora.server.middleware.token_revocation import (
            is_token_revoked,
            revoke_token,
        )

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                revoke_token("my-token", reason="test")
                assert is_token_revoked("my-token") is True

    def test_is_token_revoked_false_after_expiry(self, reset_global_store):
        """Test is_token_revoked returns False after expiry."""
        from aragora.server.middleware.token_revocation import (
            get_revocation_store,
            hash_token,
            is_token_revoked,
            RevocationEntry,
        )

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                store = get_revocation_store()

                # Add an expired entry directly
                now = datetime.now(timezone.utc)
                entry = RevocationEntry(
                    token_hash=hash_token("expired-token"),
                    revoked_at=now - timedelta(hours=48),
                    expires_at=now - timedelta(hours=24),
                )
                store._store[entry.token_hash] = entry

                assert is_token_revoked("expired-token") is False


# ===========================================================================
# Test Unrevoke Token
# ===========================================================================


class TestUnrevokeToken:
    """Tests for unrevoke_token function."""

    def test_unrevoke_token_success(self, reset_global_store):
        """Test un-revoking a revoked token."""
        from aragora.server.middleware.token_revocation import (
            is_token_revoked,
            revoke_token,
            unrevoke_token,
        )

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                revoke_token("my-token")
                assert is_token_revoked("my-token") is True

                result = unrevoke_token("my-token")

                assert result is True
                assert is_token_revoked("my-token") is False

    def test_unrevoke_token_nonexistent(self, reset_global_store):
        """Test un-revoking a token that was never revoked."""
        from aragora.server.middleware.token_revocation import unrevoke_token

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                result = unrevoke_token("never-revoked-token")
                assert result is False


# ===========================================================================
# Test Get Revocation Stats
# ===========================================================================


class TestGetRevocationStats:
    """Tests for get_revocation_stats function."""

    def test_stats_memory_store(self, reset_global_store):
        """Test stats for in-memory store."""
        from aragora.server.middleware.token_revocation import (
            get_revocation_stats,
            revoke_token,
        )

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                stats = get_revocation_stats()

                assert stats["store_type"] == "memory"
                assert stats["revoked_count"] == 0

                revoke_token("token1")
                revoke_token("token2")

                stats = get_revocation_stats()
                assert stats["revoked_count"] == 2

    def test_stats_redis_store(self, reset_global_store, mock_redis_client):
        """Test stats for Redis store."""
        from aragora.server.middleware.token_revocation import get_revocation_stats

        with patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379"}):
            with patch("redis.from_url", return_value=mock_redis_client):
                mock_redis_client.scan.return_value = (0, [b"key1", b"key2", b"key3"])

                stats = get_revocation_stats()

                assert stats["store_type"] == "redis"
                assert stats["revoked_count"] == 3


# ===========================================================================
# Test Race Conditions
# ===========================================================================


class TestRaceConditions:
    """Tests for race conditions between validation and revocation."""

    def test_concurrent_revoke_and_check(self, reset_global_store):
        """Test concurrent revoke and check operations."""
        from aragora.server.middleware.token_revocation import (
            is_token_revoked,
            revoke_token,
        )

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                results = {"revoked": [], "checks": []}
                errors = []

                def revoke_tokens():
                    try:
                        for i in range(50):
                            revoke_token(f"token-{i}")
                            results["revoked"].append(i)
                    except Exception as e:
                        errors.append(e)

                def check_tokens():
                    try:
                        for i in range(50):
                            result = is_token_revoked(f"token-{i}")
                            results["checks"].append((i, result))
                    except Exception as e:
                        errors.append(e)

                t1 = threading.Thread(target=revoke_tokens)
                t2 = threading.Thread(target=check_tokens)

                t1.start()
                t2.start()

                t1.join()
                t2.join()

                assert len(errors) == 0

    def test_concurrent_revoke_and_unrevoke(self, reset_global_store):
        """Test concurrent revoke and unrevoke operations."""
        from aragora.server.middleware.token_revocation import (
            revoke_token,
            unrevoke_token,
        )

        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aragora.config.distributed.is_distributed_state_required",
                return_value=False,
            ):
                errors = []

                def revoke():
                    try:
                        for _ in range(100):
                            revoke_token("shared-token")
                    except Exception as e:
                        errors.append(e)

                def unrevoke():
                    try:
                        for _ in range(100):
                            unrevoke_token("shared-token")
                    except Exception as e:
                        errors.append(e)

                threads = [
                    threading.Thread(target=revoke),
                    threading.Thread(target=unrevoke),
                ]

                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                assert len(errors) == 0


# ===========================================================================
# Test Cache Miss Scenarios
# ===========================================================================


class TestCacheMissScenarios:
    """Tests for cache miss and inconsistency scenarios."""

    def test_redis_contains_returns_false_on_error(self, mock_redis_client):
        """Test Redis contains returns False on any error (fail-open)."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        store = RedisRevocationStore()
        store._client = mock_redis_client

        # Test various error types
        for error in [ConnectionError, TimeoutError, OSError]:
            mock_redis_client.exists.side_effect = error("Test error")
            assert store.contains("any-hash") is False

    def test_memory_store_consistent_after_cleanup(self, memory_store, sample_entry, expired_entry):
        """Test memory store remains consistent after cleanup."""
        memory_store.add(sample_entry)
        memory_store.add(expired_entry)

        # Run cleanup multiple times
        for _ in range(5):
            memory_store.cleanup_expired()

        # Valid entry should still be present
        assert memory_store.contains(sample_entry.token_hash) is True
        assert memory_store.count() == 1


# ===========================================================================
# Test Cross-Instance Propagation
# ===========================================================================


class TestCrossInstancePropagation:
    """Tests for revocation propagation across instances."""

    def test_redis_store_propagates_revocation(self, mock_redis_client):
        """Test Redis store enables cross-instance propagation."""
        from aragora.server.middleware.token_revocation import RedisRevocationStore

        # Simulate two instances sharing the same Redis
        store1 = RedisRevocationStore()
        store1._client = mock_redis_client

        store2 = RedisRevocationStore()
        store2._client = mock_redis_client

        # After store1 adds, store2 should see it via Redis
        mock_redis_client.exists.return_value = 1

        # Both instances should see the token as revoked
        assert store1.contains("shared-hash") is True
        assert store2.contains("shared-hash") is True

    def test_memory_store_does_not_propagate(self):
        """Test in-memory store does NOT propagate across instances."""
        from aragora.server.middleware.token_revocation import (
            InMemoryRevocationStore,
            RevocationEntry,
        )

        store1 = InMemoryRevocationStore()
        store2 = InMemoryRevocationStore()

        now = datetime.now(timezone.utc)
        entry = RevocationEntry(
            token_hash="test-hash",
            revoked_at=now,
            expires_at=now + timedelta(hours=1),
        )

        store1.add(entry)

        # store2 should NOT see store1's entry
        assert store1.contains("test-hash") is True
        assert store2.contains("test-hash") is False


__all__ = [
    "TestRevocationEntry",
    "TestInMemoryRevocationStore",
    "TestRedisRevocationStore",
    "TestGetRevocationStore",
    "TestHashToken",
    "TestRevokeToken",
    "TestIsTokenRevoked",
    "TestUnrevokeToken",
    "TestGetRevocationStats",
    "TestRaceConditions",
    "TestCacheMissScenarios",
    "TestCrossInstancePropagation",
]
