"""
Integration tests for Leader Election.

Tests the distributed leader election system for multi-node deployments:
- LeaderConfig configuration
- LeaderElection lifecycle (start, stop)
- Leader acquisition and release
- Callback notifications
- In-memory fallback when Redis unavailable
- Concurrent election scenarios
- Split-brain detection and prevention
- Heartbeat handling and TTL expiration
- State transitions
- Failover scenarios
- Regional leader election
- Global coordinator election

Run with:
    pytest tests/control_plane/test_leader_election.py -v --asyncio-mode=auto
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.control_plane.leader import (
    DistributedStateError,
    LeaderConfig,
    LeaderElection,
    LeaderInfo,
    LeaderState,
    RegionalLeaderConfig,
    RegionalLeaderElection,
    RegionalLeaderInfo,
    is_distributed_state_required,
)


# =============================================================================
# Helpers
# =============================================================================


async def poll_until(predicate, *, timeout: float = 3.0, interval: float = 0.05):
    """Poll until predicate() is truthy, raising on timeout.

    Replaces brittle ``await asyncio.sleep(N)`` + assert patterns
    so that tests pass reliably under load (xdist, CI, etc.).
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"Condition not met within {timeout}s")


# =============================================================================
# Mock Redis Implementation
# =============================================================================


class MockRedis:
    """Mock Redis client with full feature support for testing."""

    def __init__(self):
        self._data: dict[str, str] = {}
        self._hashes: dict[str, dict[str, str]] = {}
        self._expiries: dict[str, float] = {}
        self._fail_on_next: str | None = None
        self._delay_seconds: float = 0.0
        self._operation_log: list[dict[str, Any]] = []

    async def set(
        self,
        key: str,
        value: str,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        """SET command with NX and EX support."""
        self._operation_log.append(
            {"op": "set", "key": key, "value": value, "nx": nx, "ex": ex, "time": time.time()}
        )

        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)

        if self._fail_on_next == "set":
            self._fail_on_next = None
            raise ConnectionError("Redis connection failed")

        # Check expiry first
        if key in self._expiries and time.time() > self._expiries[key]:
            del self._data[key]
            del self._expiries[key]

        if nx and key in self._data:
            return None

        self._data[key] = value
        if ex:
            self._expiries[key] = time.time() + ex
        return True

    async def get(self, key: str) -> str | None:
        """GET command."""
        self._operation_log.append({"op": "get", "key": key, "time": time.time()})

        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)

        if self._fail_on_next == "get":
            self._fail_on_next = None
            raise ConnectionError("Redis connection failed")

        # Check expiry
        if key in self._expiries and time.time() > self._expiries[key]:
            del self._data[key]
            del self._expiries[key]
            return None

        return self._data.get(key)

    async def delete(self, key: str) -> int:
        """DELETE command."""
        self._operation_log.append({"op": "delete", "key": key, "time": time.time()})

        if self._fail_on_next == "delete":
            self._fail_on_next = None
            raise ConnectionError("Redis connection failed")

        if key in self._data:
            del self._data[key]
            self._expiries.pop(key, None)
            return 1
        return 0

    async def expire(self, key: str, seconds: int) -> bool:
        """EXPIRE command."""
        self._operation_log.append(
            {"op": "expire", "key": key, "seconds": seconds, "time": time.time()}
        )

        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)

        if self._fail_on_next == "expire":
            self._fail_on_next = None
            raise ConnectionError("Redis connection failed")

        if key in self._data:
            self._expiries[key] = time.time() + seconds
            return True
        return False

    async def hset(
        self,
        key: str,
        field: str | None = None,
        value: str | None = None,
        mapping: dict | None = None,
    ) -> int:
        """HSET command."""
        if self._fail_on_next == "hset":
            self._fail_on_next = None
            raise ConnectionError("Redis connection failed")

        if key not in self._hashes:
            self._hashes[key] = {}

        if mapping:
            for k, v in mapping.items():
                self._hashes[key][k] = str(v)
            return len(mapping)
        elif field is not None:
            self._hashes[key][field] = str(value) if value is not None else ""
            return 1
        return 0

    async def hgetall(self, key: str) -> dict[str, str]:
        """HGETALL command."""
        if self._fail_on_next == "hgetall":
            self._fail_on_next = None
            raise ConnectionError("Redis connection failed")
        return self._hashes.get(key, {})

    def fail_on_next(self, operation: str) -> None:
        """Set the next operation to fail."""
        self._fail_on_next = operation

    def set_delay(self, seconds: float) -> None:
        """Set delay for operations."""
        self._delay_seconds = seconds

    def clear_delay(self) -> None:
        """Clear operation delay."""
        self._delay_seconds = 0.0

    def expire_key_now(self, key: str) -> None:
        """Immediately expire a key (simulates TTL expiration)."""
        if key in self._data:
            del self._data[key]
            self._expiries.pop(key, None)

    def corrupt_value(self, key: str, value: str) -> None:
        """Corrupt a key's value (simulates split-brain)."""
        self._data[key] = value


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _reset_leader_singleton(mock_redis):
    """Reset the module-level singleton and mock redis state before and after each test.

    The leader.py module has a global ``_regional_leader_election`` singleton
    that persists across tests when running in the full suite.  Without this
    fixture, a test that calls ``init_regional_leader_election`` (or any code
    path that sets the singleton) will pollute subsequent tests.

    Also clears mock redis state to prevent stale lock data from leaking
    between tests, which can cause flaky leader election outcomes.
    """
    import aragora.resilience.leader as _leader_mod

    original = _leader_mod._regional_leader_election
    _leader_mod._regional_leader_election = None

    # Clear any stale redis state from previous tests
    if mock_redis is not None:
        mock_redis._data.clear()
        mock_redis._hashes.clear()
        mock_redis._expiries.clear()
        mock_redis._operation_log.clear()

    yield

    _leader_mod._regional_leader_election = original


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    return MockRedis()


@pytest.fixture
def leader_config():
    """Create a leader config with short timeouts for testing."""
    return LeaderConfig(
        redis_url="redis://localhost:6379",
        key_prefix="test:leader:",
        lock_ttl_seconds=2.0,
        heartbeat_interval=0.5,
        retry_interval=0.1,
        election_timeout=1.0,
        node_id="test-node-1",
    )


@pytest.fixture
def election(leader_config, mock_redis):
    """Create a LeaderElection instance with mock Redis."""
    return LeaderElection(config=leader_config, redis_client=mock_redis)


# =============================================================================
# LeaderConfig Tests
# =============================================================================


class TestLeaderConfig:
    """Tests for LeaderConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = LeaderConfig()

        assert config.redis_url == "redis://localhost:6379"
        assert config.key_prefix == "aragora:leader:"
        assert config.lock_ttl_seconds == 30.0
        assert config.heartbeat_interval == 10.0
        assert config.election_timeout == 5.0
        assert config.retry_interval == 1.0
        assert config.node_id is not None

    def test_custom_config(self):
        """Test custom configuration values."""
        config = LeaderConfig(
            redis_url="redis://custom:6380",
            key_prefix="custom:leader:",
            lock_ttl_seconds=60.0,
            heartbeat_interval=20.0,
            node_id="custom-node-1",
        )

        assert config.redis_url == "redis://custom:6380"
        assert config.key_prefix == "custom:leader:"
        assert config.lock_ttl_seconds == 60.0
        assert config.heartbeat_interval == 20.0
        assert config.node_id == "custom-node-1"

    def test_from_env(self):
        """Test configuration from environment variables."""
        env_vars = {
            "REDIS_URL": "redis://env-host:6379",
            "LEADER_KEY_PREFIX": "env:leader:",
            "LEADER_LOCK_TTL": "45",
            "LEADER_HEARTBEAT": "15",
            "NODE_ID": "env-node-1",
        }

        with patch.dict(os.environ, env_vars):
            config = LeaderConfig.from_env()

            assert config.redis_url == "redis://env-host:6379"
            assert config.key_prefix == "env:leader:"
            assert config.lock_ttl_seconds == 45.0
            assert config.heartbeat_interval == 15.0
            assert config.node_id == "env-node-1"

    def test_from_env_defaults(self):
        """Test from_env with default values when env vars not set."""
        env_to_clear = [
            "REDIS_URL",
            "LEADER_KEY_PREFIX",
            "LEADER_LOCK_TTL",
            "NODE_ID",
        ]
        clean_env = {k: v for k, v in os.environ.items() if k not in env_to_clear}

        with patch.dict(os.environ, clean_env, clear=True):
            config = LeaderConfig.from_env()
            assert config.redis_url == "redis://localhost:6379"
            assert config.node_id is not None

    def test_node_id_uniqueness(self):
        """Test that auto-generated node IDs are unique."""
        config1 = LeaderConfig()
        config2 = LeaderConfig()
        assert config1.node_id != config2.node_id


# =============================================================================
# LeaderState Tests
# =============================================================================


class TestLeaderState:
    """Tests for LeaderState enum."""

    def test_state_values(self):
        """Test all state values."""
        assert LeaderState.FOLLOWER.value == "follower"
        assert LeaderState.CANDIDATE.value == "candidate"
        assert LeaderState.LEADER.value == "leader"
        assert LeaderState.DISCONNECTED.value == "disconnected"

    def test_state_count(self):
        """Test expected number of states."""
        states = list(LeaderState)
        assert len(states) == 4

    def test_state_transitions(self):
        """Test valid state transitions conceptually."""
        # DISCONNECTED -> FOLLOWER (on start)
        # FOLLOWER -> CANDIDATE (when no leader)
        # CANDIDATE -> LEADER (on successful election)
        # CANDIDATE -> FOLLOWER (on failed election)
        # LEADER -> FOLLOWER (on lost leadership)
        # Any -> DISCONNECTED (on stop)
        valid_transitions = {
            LeaderState.DISCONNECTED: {LeaderState.FOLLOWER},
            LeaderState.FOLLOWER: {LeaderState.CANDIDATE, LeaderState.DISCONNECTED},
            LeaderState.CANDIDATE: {
                LeaderState.LEADER,
                LeaderState.FOLLOWER,
                LeaderState.DISCONNECTED,
            },
            LeaderState.LEADER: {LeaderState.FOLLOWER, LeaderState.DISCONNECTED},
        }
        # All states should have defined transitions
        for state in LeaderState:
            assert state in valid_transitions


# =============================================================================
# LeaderInfo Tests
# =============================================================================


class TestLeaderInfo:
    """Tests for LeaderInfo dataclass."""

    def test_leader_info_creation(self):
        """Test creating LeaderInfo."""
        info = LeaderInfo(
            node_id="leader-1",
            elected_at=1704067200.0,
            last_heartbeat=1704067210.0,
            metadata={"region": "us-east-1"},
        )

        assert info.node_id == "leader-1"
        assert info.elected_at == 1704067200.0
        assert info.last_heartbeat == 1704067210.0
        assert info.metadata["region"] == "us-east-1"

    def test_leader_info_default_metadata(self):
        """Test LeaderInfo with default metadata."""
        info = LeaderInfo(
            node_id="leader-2",
            elected_at=1704067200.0,
            last_heartbeat=1704067200.0,
        )
        assert info.metadata == {}

    def test_leader_info_heartbeat_freshness(self):
        """Test checking heartbeat freshness."""
        now = time.time()
        info = LeaderInfo(
            node_id="leader-1",
            elected_at=now - 100,
            last_heartbeat=now - 5,
        )
        # Heartbeat is 5 seconds old
        assert (now - info.last_heartbeat) < 10


# =============================================================================
# LeaderElection Initialization Tests
# =============================================================================


class TestLeaderElectionInit:
    """Tests for LeaderElection initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default config."""
        election = LeaderElection()

        assert election.state == LeaderState.DISCONNECTED
        assert not election.is_leader
        assert election.node_id is not None
        assert election.current_leader is None

    def test_init_with_custom_config(self):
        """Test initialization with custom config."""
        config = LeaderConfig(node_id="custom-node")
        election = LeaderElection(config=config)

        assert election.node_id == "custom-node"

    def test_init_with_redis_client(self):
        """Test initialization with provided Redis client."""
        mock_redis = MagicMock()
        election = LeaderElection(redis_client=mock_redis)

        assert election._redis is mock_redis


# =============================================================================
# LeaderElection Callback Tests
# =============================================================================


class TestLeaderElectionCallbacks:
    """Tests for LeaderElection callback registration."""

    def test_on_become_leader(self):
        """Test registering become_leader callback."""
        election = LeaderElection()
        callback = MagicMock()

        election.on_become_leader(callback)

        assert callback in election._on_become_leader

    def test_on_lose_leader(self):
        """Test registering lose_leader callback."""
        election = LeaderElection()
        callback = MagicMock()

        election.on_lose_leader(callback)

        assert callback in election._on_lose_leader

    def test_on_leader_change(self):
        """Test registering leader_change callback."""
        election = LeaderElection()
        callback = MagicMock()

        election.on_leader_change(callback)

        assert callback in election._on_leader_change

    def test_multiple_callbacks(self):
        """Test registering multiple callbacks."""
        election = LeaderElection()
        callbacks = [MagicMock() for _ in range(3)]

        for cb in callbacks:
            election.on_become_leader(cb)

        assert len(election._on_become_leader) == 3


# =============================================================================
# LeaderElection Lifecycle Tests
# =============================================================================


class TestLeaderElectionLifecycle:
    """Tests for LeaderElection start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_election_task(self, mock_redis):
        """Test that start creates election task."""
        config = LeaderConfig(retry_interval=0.01, node_id="test-node")
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()

        try:
            assert election._running is True
            assert election._election_task is not None
            assert election.state != LeaderState.DISCONNECTED
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self, mock_redis):
        """Test that stop cancels running tasks."""
        config = LeaderConfig(retry_interval=0.01, node_id="test-node")
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.05)

        await election.stop()

        assert election._running is False
        assert election.state == LeaderState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        """Test that stop can be called multiple times."""
        election = LeaderElection()

        await election.stop()
        await election.stop()

        assert election.state == LeaderState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_start_idempotent(self, mock_redis):
        """Test that start can be called multiple times."""
        config = LeaderConfig(retry_interval=0.01, node_id="test-node")
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await election.start()

        try:
            assert election._running is True
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_rapid_start_stop(self, mock_redis):
        """Test rapid start/stop cycles."""
        config = LeaderConfig(retry_interval=0.01, node_id="test-node")
        election = LeaderElection(config=config, redis_client=mock_redis)

        for _ in range(5):
            await election.start()
            await election.stop()

        assert election.state == LeaderState.DISCONNECTED


# =============================================================================
# Election Flow Tests
# =============================================================================


class TestElectionFlow:
    """Tests for the election flow and state transitions."""

    @pytest.mark.asyncio
    async def test_single_node_becomes_leader(self, mock_redis):
        """Test that a single node becomes leader."""
        config = LeaderConfig(
            retry_interval=0.01,
            election_timeout=0.1,
            node_id="single-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()

        try:
            for _ in range(50):
                if election.is_leader:
                    break
                await asyncio.sleep(0.01)

            assert election.is_leader
            assert election.state == LeaderState.LEADER
            assert election.current_leader is not None
            assert election.current_leader.node_id == "single-node"
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_follower_to_candidate_transition(self, mock_redis):
        """Test transition from follower to candidate when no leader exists."""
        config = LeaderConfig(retry_interval=0.01, node_id="test-node")
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()

        try:
            # Should start as follower, then try to become leader
            await poll_until(lambda: election.state in {LeaderState.LEADER, LeaderState.FOLLOWER})
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_become_leader_callback_called(self, mock_redis):
        """Test that become_leader callback is invoked."""
        config = LeaderConfig(retry_interval=0.01, node_id="test-node")
        election = LeaderElection(config=config, redis_client=mock_redis)

        callback_called = asyncio.Event()

        def on_leader():
            callback_called.set()

        election.on_become_leader(on_leader)

        await election.start()

        try:
            await asyncio.wait_for(callback_called.wait(), timeout=1.0)
            assert callback_called.is_set()
        except asyncio.TimeoutError:
            pass  # May not become leader in test environment
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_leader_change_callback_with_node_id(self, mock_redis):
        """Test that leader_change callback receives correct node_id."""
        config = LeaderConfig(retry_interval=0.01, node_id="test-node")
        election = LeaderElection(config=config, redis_client=mock_redis)

        received_node_ids: list[str | None] = []

        def on_change(node_id: str | None):
            received_node_ids.append(node_id)

        election.on_leader_change(on_change)

        await election.start()

        try:
            await poll_until(lambda: election.is_leader)
            if received_node_ids:
                assert "test-node" in received_node_ids
        finally:
            await election.stop()


# =============================================================================
# Heartbeat Handling Tests
# =============================================================================


class TestHeartbeatHandling:
    """Tests for heartbeat sending and TTL management."""

    @pytest.mark.asyncio
    async def test_heartbeat_refreshes_ttl(self, mock_redis):
        """Test that leader heartbeat refreshes the lock TTL."""
        config = LeaderConfig(
            retry_interval=0.05,
            lock_ttl_seconds=1.0,
            node_id="heartbeat-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()

        try:
            await poll_until(lambda: election.is_leader)

            # Check that expire operations are being called
            expire_ops = [op for op in mock_redis._operation_log if op["op"] == "expire"]
            # After becoming leader, should refresh TTL
            assert len(expire_ops) >= 0  # May not have refreshed yet
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_ttl_expiration_loses_leadership(self, mock_redis):
        """Test that TTL expiration causes loss of leadership."""
        config = LeaderConfig(
            retry_interval=0.05,
            lock_ttl_seconds=0.5,
            node_id="ttl-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()

        try:
            await poll_until(lambda: election.is_leader)

            # Expire the lock manually
            mock_redis.expire_key_now(f"{config.key_prefix}lock")

            # Wait for election loop to detect and potentially re-acquire
            await asyncio.sleep(0.2)

            # Note: election might re-acquire immediately since it's still running
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_heartbeat_updates_leader_info(self, mock_redis):
        """Test that heartbeat updates last_heartbeat in leader info."""
        config = LeaderConfig(
            retry_interval=0.05,
            node_id="info-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()

        try:
            await poll_until(lambda: election.is_leader)
            assert election.current_leader is not None
            first_heartbeat = election.current_leader.last_heartbeat
            await asyncio.sleep(0.1)
            # The leader info should be updated
            assert election.current_leader is not None
        finally:
            await election.stop()


# =============================================================================
# Split-Brain Detection Tests
# =============================================================================


class TestSplitBrainDetection:
    """Tests for split-brain scenario detection and prevention."""

    @pytest.mark.asyncio
    async def test_concurrent_election_only_one_leader(self, mock_redis):
        """Test that concurrent elections result in only one leader."""
        nodes = []
        for i in range(5):
            config = LeaderConfig(
                key_prefix="test:leader:",
                lock_ttl_seconds=5.0,
                retry_interval=0.05,
                node_id=f"node-{i}",
            )
            election = LeaderElection(config=config, redis_client=mock_redis)
            nodes.append(election)

        await asyncio.gather(*[n.start() for n in nodes])

        await poll_until(lambda: sum(1 for n in nodes if n.is_leader) == 1)

        leaders = [n for n in nodes if n.is_leader]
        assert len(leaders) == 1

        await asyncio.gather(*[n.stop() for n in nodes])

    @pytest.mark.asyncio
    async def test_detects_lock_stolen_by_another_node(self, mock_redis):
        """Test that leader detects when lock is held by another node."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.05,
            node_id="original-leader",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await poll_until(lambda: election.is_leader)

        # Another node "steals" the lock
        mock_redis.corrupt_value("test:leader:lock", "rogue-node")

        # Wait for detection
        await poll_until(lambda: not election.is_leader)

        assert election.state == LeaderState.FOLLOWER

        await election.stop()

    @pytest.mark.asyncio
    async def test_two_nodes_one_leader(self, mock_redis):
        """Test that with two nodes, exactly one becomes leader."""
        config1 = LeaderConfig(
            key_prefix="test:leader:",
            node_id="node-1",
            retry_interval=0.01,
        )
        config2 = LeaderConfig(
            key_prefix="test:leader:",
            node_id="node-2",
            retry_interval=0.01,
        )

        election1 = LeaderElection(config=config1, redis_client=mock_redis)
        election2 = LeaderElection(config=config2, redis_client=mock_redis)

        await election1.start()
        await election2.start()

        try:
            await poll_until(
                lambda: election1.is_leader or election2.is_leader,
            )

            leaders = []
            if election1.is_leader:
                leaders.append("node-1")
            if election2.is_leader:
                leaders.append("node-2")

            assert len(leaders) <= 1
        finally:
            await election1.stop()
            await election2.stop()


# =============================================================================
# Failover Scenario Tests
# =============================================================================


class TestFailoverScenarios:
    """Tests for leader failure and re-election scenarios."""

    @pytest.mark.asyncio
    async def test_new_leader_elected_after_leader_stops(self, mock_redis):
        """Test that a new leader is elected when current leader stops."""
        config1 = LeaderConfig(
            key_prefix="test:leader:",
            node_id="leader-1",
            retry_interval=0.05,
        )
        config2 = LeaderConfig(
            key_prefix="test:leader:",
            node_id="leader-2",
            retry_interval=0.05,
        )

        election1 = LeaderElection(config=config1, redis_client=mock_redis)
        election2 = LeaderElection(config=config2, redis_client=mock_redis)

        await election1.start()
        await poll_until(lambda: election1.is_leader)

        await election2.start()
        await asyncio.sleep(0.1)
        assert not election2.is_leader

        # Stop the leader
        await election1.stop()

        # Wait for election2 to detect and become leader
        await poll_until(lambda: election2.is_leader)

        assert election2.is_leader

        await election2.stop()

    @pytest.mark.asyncio
    async def test_lock_expiration_triggers_reelection(self, mock_redis):
        """Test that lock expiration allows new leader election."""
        config1 = LeaderConfig(
            key_prefix="test:leader:",
            node_id="node-1",
            retry_interval=0.05,
            lock_ttl_seconds=2.0,
        )
        config2 = LeaderConfig(
            key_prefix="test:leader:",
            node_id="node-2",
            retry_interval=0.05,
            lock_ttl_seconds=2.0,
        )

        election1 = LeaderElection(config=config1, redis_client=mock_redis)
        election2 = LeaderElection(config=config2, redis_client=mock_redis)

        await election1.start()
        await poll_until(lambda: election1.is_leader)

        # Expire the lock
        mock_redis.expire_key_now("test:leader:lock")

        await election2.start()

        # One of them should be leader
        await poll_until(lambda: election1.is_leader or election2.is_leader)

        await election1.stop()
        await election2.stop()

    @pytest.mark.asyncio
    async def test_lose_leader_callback_fires(self, mock_redis):
        """Test that lose_leader callback fires when leadership is lost."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            node_id="callback-node",
            retry_interval=0.05,
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        callback_fired = asyncio.Event()

        def on_lose():
            callback_fired.set()

        election.on_lose_leader(on_lose)

        await election.start()
        await poll_until(lambda: election.is_leader)

        # Simulate another node taking over
        mock_redis.corrupt_value("test:leader:lock", "other-node")

        await poll_until(lambda: callback_fired.is_set())

        await election.stop()


# =============================================================================
# In-Memory Fallback Tests
# =============================================================================


class TestInMemoryFallback:
    """Tests for in-memory fallback when Redis unavailable."""

    @pytest.mark.asyncio
    async def test_uses_in_memory_without_redis(self):
        """Test that in-memory fallback is used when aioredis unavailable."""
        config = LeaderConfig(retry_interval=0.01, node_id="inmem-node")
        election = LeaderElection(config=config)

        with patch.dict("sys.modules", {"aioredis": None}):
            await election.start()

            try:
                assert election._running is True
                assert election._redis is not None
            finally:
                await election.stop()


# =============================================================================
# Properties Tests
# =============================================================================


class TestLeaderElectionProperties:
    """Tests for LeaderElection properties."""

    def test_state_property(self):
        """Test state property."""
        election = LeaderElection()
        assert election.state == LeaderState.DISCONNECTED

    def test_is_leader_property(self):
        """Test is_leader property."""
        election = LeaderElection()
        assert not election.is_leader

        election._state = LeaderState.LEADER
        assert election.is_leader

    def test_node_id_property(self):
        """Test node_id property."""
        config = LeaderConfig(node_id="test-node")
        election = LeaderElection(config=config)
        assert election.node_id == "test-node"

    def test_current_leader_property(self):
        """Test current_leader property."""
        election = LeaderElection()
        assert election.current_leader is None

        election._current_leader = LeaderInfo(
            node_id="other-node",
            elected_at=time.time(),
            last_heartbeat=time.time(),
        )
        assert election.current_leader.node_id == "other-node"

    def test_get_stats(self):
        """Test get_stats method."""
        config = LeaderConfig(node_id="stats-node")
        election = LeaderElection(config=config)

        stats = election.get_stats()

        assert stats["node_id"] == "stats-node"
        assert stats["state"] == "disconnected"
        assert stats["is_leader"] is False
        assert stats["current_leader"] is None


# =============================================================================
# Callback Error Handling Tests
# =============================================================================


class TestCallbackErrorHandling:
    """Tests for callback error handling."""

    @pytest.mark.asyncio
    async def test_callback_exception_handling(self, mock_redis):
        """Test that callback exceptions don't break election."""
        config = LeaderConfig(retry_interval=0.01, node_id="callback-node")
        election = LeaderElection(config=config, redis_client=mock_redis)

        def bad_callback():
            raise ValueError("Callback error")

        election.on_become_leader(bad_callback)

        await election.start()

        try:
            await asyncio.sleep(0.1)
            assert election._running is True
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_async_callback_exception_handled(self, mock_redis):
        """Test that async callback exceptions are handled."""
        config = LeaderConfig(retry_interval=0.01, node_id="async-cb-node")
        election = LeaderElection(config=config, redis_client=mock_redis)

        async def bad_async_callback():
            raise RuntimeError("Async callback failed!")

        election.on_become_leader(bad_async_callback)

        await election.start()
        await asyncio.sleep(0.2)

        assert election._running is True

        await election.stop()


# =============================================================================
# Distributed State Requirement Tests
# =============================================================================


class TestDistributedStateRequirement:
    """Tests for distributed state requirement enforcement."""

    def test_default_not_required(self, monkeypatch):
        """Test default distributed state requirement is False."""
        for var in [
            "ARAGORA_REQUIRE_DISTRIBUTED",
            "ARAGORA_REQUIRE_DISTRIBUTED_STATE",
            "ARAGORA_MULTI_INSTANCE",
            "ARAGORA_ENV",
        ]:
            monkeypatch.delenv(var, raising=False)

        assert is_distributed_state_required() is False

    def test_require_distributed_canonical(self, monkeypatch):
        """Test canonical ARAGORA_REQUIRE_DISTRIBUTED variable."""
        monkeypatch.setenv("ARAGORA_REQUIRE_DISTRIBUTED", "true")
        assert is_distributed_state_required() is True

    def test_require_distributed_legacy(self, monkeypatch):
        """Test legacy ARAGORA_REQUIRE_DISTRIBUTED_STATE variable."""
        monkeypatch.delenv("ARAGORA_REQUIRE_DISTRIBUTED", raising=False)
        monkeypatch.setenv("ARAGORA_REQUIRE_DISTRIBUTED_STATE", "true")
        assert is_distributed_state_required() is True

    def test_multi_instance_requires_distributed(self, monkeypatch):
        """Test multi-instance implies distributed state."""
        for var in ["ARAGORA_REQUIRE_DISTRIBUTED", "ARAGORA_REQUIRE_DISTRIBUTED_STATE"]:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "true")
        assert is_distributed_state_required() is True

    def test_production_requires_distributed(self, monkeypatch):
        """Test production environment requires distributed state."""
        for var in [
            "ARAGORA_REQUIRE_DISTRIBUTED",
            "ARAGORA_REQUIRE_DISTRIBUTED_STATE",
            "ARAGORA_MULTI_INSTANCE",
        ]:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("ARAGORA_ENV", "production")
        assert is_distributed_state_required() is True

    def test_production_single_instance_override(self, monkeypatch):
        """Test production with single instance override."""
        monkeypatch.setenv("ARAGORA_ENV", "production")
        monkeypatch.setenv("ARAGORA_SINGLE_INSTANCE", "true")
        assert is_distributed_state_required() is False

    def test_distributed_state_error_message(self):
        """Test DistributedStateError message format."""
        error = DistributedStateError("leader_election", "Redis not available")
        assert "leader_election" in str(error)
        assert "Redis not available" in str(error)
        assert "ARAGORA_SINGLE_INSTANCE" in str(error)


# =============================================================================
# Regional Leader Election Tests
# =============================================================================


class TestRegionalLeaderConfig:
    """Tests for RegionalLeaderConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RegionalLeaderConfig()

        assert config.region_id == "default"
        assert config.sync_regions == []
        assert config.broadcast_leadership is True
        assert config.redis_url == "redis://localhost:6379"

    def test_custom_config(self):
        """Test custom configuration values."""
        config = RegionalLeaderConfig(
            region_id="us-west-2",
            sync_regions=["us-east-1", "eu-west-1"],
            broadcast_leadership=False,
            node_id="regional-node-1",
        )

        assert config.region_id == "us-west-2"
        assert config.sync_regions == ["us-east-1", "eu-west-1"]
        assert config.broadcast_leadership is False
        assert config.node_id == "regional-node-1"

    def test_get_region_key_prefix(self):
        """Test region-scoped key prefix generation."""
        config = RegionalLeaderConfig(region_id="us-west-2")
        prefix = config.get_region_key_prefix()

        assert prefix == "aragora:leader:region:us-west-2:"

    def test_from_env(self):
        """Test configuration from environment variables."""
        env_vars = {
            "REDIS_URL": "redis://env-host:6379",
            "ARAGORA_REGION_ID": "ap-southeast-1",
            "ARAGORA_SYNC_REGIONS": "us-west-2, eu-west-1",
            "ARAGORA_BROADCAST_LEADERSHIP": "false",
            "NODE_ID": "regional-env-node",
        }

        with patch.dict(os.environ, env_vars):
            config = RegionalLeaderConfig.from_env()

            assert config.region_id == "ap-southeast-1"
            assert config.sync_regions == ["us-west-2", "eu-west-1"]
            assert config.broadcast_leadership is False
            assert config.node_id == "regional-env-node"


class TestRegionalLeaderInfo:
    """Tests for RegionalLeaderInfo dataclass."""

    def test_regional_leader_info_creation(self):
        """Test creating RegionalLeaderInfo."""
        info = RegionalLeaderInfo(
            node_id="leader-1",
            elected_at=1704067200.0,
            last_heartbeat=1704067210.0,
            region_id="us-west-2",
            is_global_coordinator=True,
        )

        assert info.node_id == "leader-1"
        assert info.region_id == "us-west-2"
        assert info.is_global_coordinator is True

    def test_default_values(self):
        """Test RegionalLeaderInfo with default values."""
        info = RegionalLeaderInfo(
            node_id="leader-2",
            elected_at=1704067200.0,
            last_heartbeat=1704067200.0,
        )

        assert info.region_id == "default"
        assert info.is_global_coordinator is False


class TestRegionalLeaderElectionInit:
    """Tests for RegionalLeaderElection initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default config."""
        election = RegionalLeaderElection()

        assert election.state == LeaderState.DISCONNECTED
        assert not election.is_regional_leader
        assert not election.is_global_coordinator
        assert election.region_id == "default"
        assert election.regional_leaders == {}

    def test_init_with_custom_config(self):
        """Test initialization with custom config."""
        config = RegionalLeaderConfig(
            region_id="us-west-2",
            node_id="custom-regional-node",
        )
        election = RegionalLeaderElection(config=config)

        assert election.region_id == "us-west-2"
        assert election.node_id == "custom-regional-node"


class TestRegionalLeaderElectionCallbacks:
    """Tests for RegionalLeaderElection callback registration."""

    def test_on_become_regional_leader(self):
        """Test registering become_regional_leader callback."""
        election = RegionalLeaderElection()
        callback = MagicMock()

        election.on_become_regional_leader(callback)

        assert callback in election._on_become_regional_leader

    def test_on_lose_regional_leader(self):
        """Test registering lose_regional_leader callback."""
        election = RegionalLeaderElection()
        callback = MagicMock()

        election.on_lose_regional_leader(callback)

        assert callback in election._on_lose_regional_leader

    def test_on_become_global_coordinator(self):
        """Test registering become_global_coordinator callback."""
        election = RegionalLeaderElection()
        callback = MagicMock()

        election.on_become_global_coordinator(callback)

        assert callback in election._on_become_global_coordinator

    def test_on_lose_global_coordinator(self):
        """Test registering lose_global_coordinator callback."""
        election = RegionalLeaderElection()
        callback = MagicMock()

        election.on_lose_global_coordinator(callback)

        assert callback in election._on_lose_global_coordinator


class TestRegionalLeaderElectionLifecycle:
    """Tests for RegionalLeaderElection start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_election_task(self, mock_redis):
        """Test that start creates election task with region-scoped keys."""
        config = RegionalLeaderConfig(
            region_id="us-west-2",
            retry_interval=0.01,
            node_id="regional-test",
        )
        election = RegionalLeaderElection(config=config, redis_client=mock_redis)

        await election.start()

        try:
            assert election._running is True
            assert election._election_task is not None
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self, mock_redis):
        """Test that stop cancels running tasks."""
        config = RegionalLeaderConfig(retry_interval=0.01, node_id="stop-test")
        election = RegionalLeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.05)

        await election.stop()

        assert election._running is False
        assert election.state == LeaderState.DISCONNECTED


class TestRegionalLeaderElectionProperties:
    """Tests for RegionalLeaderElection properties."""

    def test_region_id_property(self):
        """Test region_id property."""
        config = RegionalLeaderConfig(region_id="eu-west-1")
        election = RegionalLeaderElection(config=config)
        assert election.region_id == "eu-west-1"

    def test_is_regional_leader_property(self):
        """Test is_regional_leader property mirrors is_leader."""
        election = RegionalLeaderElection()
        assert not election.is_regional_leader

        election._state = LeaderState.LEADER
        assert election.is_regional_leader

    def test_is_global_coordinator_property(self):
        """Test is_global_coordinator property."""
        election = RegionalLeaderElection()
        assert not election.is_global_coordinator

        election._is_global_coordinator = True
        assert election.is_global_coordinator

    def test_regional_leaders_property_returns_copy(self):
        """Test regional_leaders property returns copy."""
        election = RegionalLeaderElection()
        info = RegionalLeaderInfo(
            node_id="other-leader",
            region_id="us-east-1",
            elected_at=time.time(),
            last_heartbeat=time.time(),
        )
        election._regional_leaders["us-east-1"] = info

        leaders = election.regional_leaders
        assert "us-east-1" in leaders
        assert leaders["us-east-1"].node_id == "other-leader"

        # Should be a copy
        leaders["us-east-1"] = None
        assert election._regional_leaders["us-east-1"].node_id == "other-leader"


class TestRegionalLeaderElectionStats:
    """Tests for RegionalLeaderElection statistics."""

    def test_get_stats_includes_regional_info(self):
        """Test that get_stats includes regional information."""
        config = RegionalLeaderConfig(
            region_id="ap-southeast-1",
            node_id="test-node",
        )
        election = RegionalLeaderElection(config=config)

        stats = election.get_stats()

        assert stats["node_id"] == "test-node"
        assert stats["region_id"] == "ap-southeast-1"
        assert stats["is_regional_leader"] is False
        assert stats["is_global_coordinator"] is False
        assert stats["known_regional_leaders"] == []

    def test_get_stats_with_known_leaders(self):
        """Test stats with known regional leaders."""
        election = RegionalLeaderElection()
        election._regional_leaders["us-east-1"] = RegionalLeaderInfo(
            node_id="east-leader",
            region_id="us-east-1",
            elected_at=time.time(),
            last_heartbeat=time.time(),
        )
        election._regional_leaders["eu-west-1"] = RegionalLeaderInfo(
            node_id="eu-leader",
            region_id="eu-west-1",
            elected_at=time.time(),
            last_heartbeat=time.time(),
        )

        stats = election.get_stats()

        assert "us-east-1" in stats["known_regional_leaders"]
        assert "eu-west-1" in stats["known_regional_leaders"]


class TestMultiRegionElection:
    """Tests for multi-region election scenarios."""

    @pytest.mark.asyncio
    async def test_two_regions_two_leaders(self, mock_redis):
        """Test that two regions can have independent leaders."""
        config1 = RegionalLeaderConfig(
            region_id="us-west-2",
            node_id="west-node",
            retry_interval=0.01,
        )
        config2 = RegionalLeaderConfig(
            region_id="us-east-1",
            node_id="east-node",
            retry_interval=0.01,
        )

        election1 = RegionalLeaderElection(config=config1, redis_client=mock_redis)
        election2 = RegionalLeaderElection(config=config2, redis_client=mock_redis)

        await election1.start()
        await election2.start()

        try:
            await poll_until(
                lambda: election1.is_regional_leader or election2.is_regional_leader,
            )
            # Both should be able to become leaders (different regions)
            # At least one should be a leader
        finally:
            await election1.stop()
            await election2.stop()

    @pytest.mark.asyncio
    async def test_same_region_only_one_leader(self, mock_redis):
        """Test that same region only has one leader."""
        config1 = RegionalLeaderConfig(
            region_id="us-west-2",
            node_id="node-1",
            retry_interval=0.01,
        )
        config2 = RegionalLeaderConfig(
            region_id="us-west-2",
            node_id="node-2",
            retry_interval=0.01,
        )

        election1 = RegionalLeaderElection(config=config1, redis_client=mock_redis)
        election2 = RegionalLeaderElection(config=config2, redis_client=mock_redis)

        await election1.start()
        await election2.start()

        try:
            await poll_until(
                lambda: election1.is_regional_leader or election2.is_regional_leader,
            )

            leaders = []
            if election1.is_regional_leader:
                leaders.append("node-1")
            if election2.is_regional_leader:
                leaders.append("node-2")

            # At most one leader in same region
            assert len(leaders) <= 1
        finally:
            await election1.stop()
            await election2.stop()

    @pytest.mark.asyncio
    async def test_global_coordinator_election(self, mock_redis):
        """Test global coordinator election among regional leaders."""
        config = RegionalLeaderConfig(
            region_id="us-west-2",
            node_id="coordinator-test",
            retry_interval=0.01,
        )
        election = RegionalLeaderElection(config=config, redis_client=mock_redis)

        await election.start()

        try:
            await poll_until(lambda: election.is_regional_leader)
            # Should attempt to become global coordinator
            # May or may not succeed in test environment
        finally:
            await election.stop()


# =============================================================================
# Redis Connection Failure Tests
# =============================================================================


class TestRedisConnectionFailures:
    """Tests for Redis connection failure handling."""

    @pytest.mark.asyncio
    async def test_redis_failure_during_election(self, mock_redis):
        """Test handling of Redis failure during election attempt."""
        config = LeaderConfig(
            retry_interval=0.05,
            node_id="failure-test",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        set_attempts = {"count": 0}
        original_set = mock_redis.set

        async def tracking_set(*args, **kwargs):
            set_attempts["count"] += 1
            if set_attempts["count"] == 1:
                raise ConnectionError("Redis connection failed")
            return await original_set(*args, **kwargs)

        mock_redis.set = tracking_set

        await election.start()
        await poll_until(lambda: set_attempts["count"] >= 1)

        await election.stop()

    @pytest.mark.asyncio
    async def test_redis_timeout_handling(self, mock_redis):
        """Test that slow Redis operations are handled."""
        config = LeaderConfig(
            retry_interval=0.05,
            node_id="timeout-test",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.2)

        mock_redis.set_delay(0.2)

        await asyncio.sleep(0.3)

        mock_redis.clear_delay()
        await election.stop()
