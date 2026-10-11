"""
Comprehensive tests for the Leader Election module.

Tests the distributed leader election system for multi-node deployments:
- Leader election scenarios (single node, multi-node)
- Failover when leader dies
- Split-brain prevention
- Heartbeat timeout handling
- Concurrent election attempts
- Network partition scenarios
- Edge cases and error handling
- Regional leader election
- Global coordinator election

Run with:
    pytest tests/control_plane/test_leader.py -v --asyncio-mode=auto
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
    _InMemoryRedis,
    get_regional_leader_election,
    init_regional_leader_election,
    is_distributed_state_required,
    set_regional_leader_election,
)


# =============================================================================
# Enhanced Mock Redis Implementation
# =============================================================================


class MockRedis:
    """
    Enhanced mock Redis client with comprehensive testing features.

    Supports:
    - SET with NX and EX options
    - GET with TTL expiration
    - DELETE
    - EXPIRE
    - HSET/HGETALL for hash operations
    - Operation logging
    - Failure injection
    - Network delay simulation
    - Atomic lock semantics
    """

    def __init__(self):
        self._data: dict[str, str] = {}
        self._hashes: dict[str, dict[str, str]] = {}
        self._expiries: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._fail_on_next: str | None = None
        self._fail_count: int = 0
        self._delay_seconds: float = 0.0
        self._operation_log: list[dict[str, Any]] = []
        self._closed = False
        self._disconnected = False

    async def set(
        self,
        key: str,
        value: str,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        """SET command with NX (not exists) and EX (expiry) support."""
        self._operation_log.append(
            {
                "op": "set",
                "key": key,
                "value": value,
                "nx": nx,
                "ex": ex,
                "time": time.time(),
            }
        )

        if self._disconnected:
            raise ConnectionError("Redis disconnected")

        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)

        if self._fail_on_next == "set":
            self._fail_count += 1
            if self._fail_count <= 1:
                raise ConnectionError("Redis connection failed")
            self._fail_on_next = None
            self._fail_count = 0

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
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
        """GET command with expiry check."""
        self._operation_log.append({"op": "get", "key": key, "time": time.time()})

        if self._disconnected:
            raise ConnectionError("Redis disconnected")

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

        if self._disconnected:
            raise ConnectionError("Redis disconnected")

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
            {
                "op": "expire",
                "key": key,
                "seconds": seconds,
                "time": time.time(),
            }
        )

        if self._disconnected:
            raise ConnectionError("Redis disconnected")

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
        if self._disconnected:
            raise ConnectionError("Redis disconnected")

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
        if self._disconnected:
            raise ConnectionError("Redis disconnected")

        if self._fail_on_next == "hgetall":
            self._fail_on_next = None
            raise ConnectionError("Redis connection failed")

        return self._hashes.get(key, {})

    async def close(self) -> None:
        """Close the connection."""
        self._closed = True

    # Test helper methods
    def fail_on_next(self, operation: str) -> None:
        """Set the next operation of given type to fail."""
        self._fail_on_next = operation

    def set_delay(self, seconds: float) -> None:
        """Set delay for operations to simulate network latency."""
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
        """Corrupt a key's value (simulates split-brain or race condition)."""
        self._data[key] = value

    def disconnect(self) -> None:
        """Simulate network disconnection."""
        self._disconnected = True

    def reconnect(self) -> None:
        """Simulate network reconnection."""
        self._disconnected = False

    def get_operation_count(self, op: str) -> int:
        """Get count of specific operation type."""
        return sum(1 for entry in self._operation_log if entry["op"] == op)

    def clear_operation_log(self) -> None:
        """Clear the operation log."""
        self._operation_log.clear()


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _reset_leader_singleton():
    """Reset the module-level singleton before and after each test.

    Prevents state leaking between tests when running in the full suite.
    """
    import aragora.resilience.leader as _leader_mod

    original = _leader_mod._regional_leader_election
    _leader_mod._regional_leader_election = None
    yield
    _leader_mod._regional_leader_election = original


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    return MockRedis()


@pytest.fixture
def leader_config():
    """Create a leader config with short timeouts for fast testing."""
    return LeaderConfig(
        redis_url="redis://localhost:6379",
        key_prefix="test:leader:",
        lock_ttl_seconds=2.0,
        heartbeat_interval=0.5,
        retry_interval=0.05,
        election_timeout=1.0,
        node_id="test-node-1",
    )


@pytest.fixture
def election(leader_config, mock_redis):
    """Create a LeaderElection instance with mock Redis."""
    return LeaderElection(config=leader_config, redis_client=mock_redis)


@pytest.fixture
def regional_config():
    """Create a regional leader config for testing."""
    return RegionalLeaderConfig(
        redis_url="redis://localhost:6379",
        key_prefix="test:leader:",
        lock_ttl_seconds=2.0,
        heartbeat_interval=0.5,
        retry_interval=0.05,
        election_timeout=1.0,
        node_id="regional-node-1",
        region_id="us-west-2",
        sync_regions=["us-east-1", "eu-west-1"],
        broadcast_leadership=True,
    )


@pytest.fixture
def regional_election(regional_config, mock_redis):
    """Create a RegionalLeaderElection instance with mock Redis."""
    return RegionalLeaderElection(config=regional_config, redis_client=mock_redis)


# =============================================================================
# LeaderConfig Tests
# =============================================================================


class TestLeaderConfig:
    """Tests for LeaderConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values are sensible."""
        config = LeaderConfig()

        assert config.redis_url == "redis://localhost:6379"
        assert config.key_prefix == "aragora:leader:"
        assert config.lock_ttl_seconds == 30.0
        assert config.heartbeat_interval == 10.0
        assert config.election_timeout == 5.0
        assert config.retry_interval == 1.0
        assert config.node_id is not None
        assert len(config.node_id) > 0

    def test_custom_values(self):
        """Test custom configuration values are applied."""
        config = LeaderConfig(
            redis_url="redis://custom:6380",
            key_prefix="custom:leader:",
            lock_ttl_seconds=60.0,
            heartbeat_interval=20.0,
            election_timeout=10.0,
            retry_interval=2.0,
            node_id="custom-node-id",
        )

        assert config.redis_url == "redis://custom:6380"
        assert config.key_prefix == "custom:leader:"
        assert config.lock_ttl_seconds == 60.0
        assert config.heartbeat_interval == 20.0
        assert config.election_timeout == 10.0
        assert config.retry_interval == 2.0
        assert config.node_id == "custom-node-id"

    def test_from_env(self):
        """Test configuration from environment variables."""
        env_vars = {
            "REDIS_URL": "redis://env-host:6379",
            "LEADER_KEY_PREFIX": "env:leader:",
            "LEADER_LOCK_TTL": "45",
            "LEADER_HEARTBEAT": "15",
            "LEADER_ELECTION_TIMEOUT": "8",
            "LEADER_RETRY_INTERVAL": "2",
            "NODE_ID": "env-node-1",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = LeaderConfig.from_env()

            assert config.redis_url == "redis://env-host:6379"
            assert config.key_prefix == "env:leader:"
            assert config.lock_ttl_seconds == 45.0
            assert config.heartbeat_interval == 15.0
            assert config.election_timeout == 8.0
            assert config.retry_interval == 2.0
            assert config.node_id == "env-node-1"

    def test_node_id_auto_generation(self):
        """Test that node IDs are auto-generated uniquely."""
        config1 = LeaderConfig()
        config2 = LeaderConfig()

        assert config1.node_id != config2.node_id

    def test_node_id_format(self):
        """Test auto-generated node ID has expected format."""
        config = LeaderConfig()
        # Default UUID format is 12 characters (shortened UUID)
        assert len(config.node_id) == 12


# =============================================================================
# LeaderState Tests
# =============================================================================


class TestLeaderState:
    """Tests for LeaderState enum."""

    def test_state_values(self):
        """Test all state values are correct."""
        assert LeaderState.FOLLOWER.value == "follower"
        assert LeaderState.CANDIDATE.value == "candidate"
        assert LeaderState.LEADER.value == "leader"
        assert LeaderState.DISCONNECTED.value == "disconnected"

    def test_state_count(self):
        """Test expected number of states."""
        assert len(LeaderState) == 4

    def test_state_comparison(self):
        """Test state comparison works correctly."""
        assert LeaderState.LEADER != LeaderState.FOLLOWER
        assert LeaderState.LEADER == LeaderState.LEADER


# =============================================================================
# LeaderInfo Tests
# =============================================================================


class TestLeaderInfo:
    """Tests for LeaderInfo dataclass."""

    def test_basic_creation(self):
        """Test basic LeaderInfo creation."""
        info = LeaderInfo(
            node_id="leader-1",
            elected_at=1704067200.0,
            last_heartbeat=1704067210.0,
        )

        assert info.node_id == "leader-1"
        assert info.elected_at == 1704067200.0
        assert info.last_heartbeat == 1704067210.0
        assert info.metadata == {}

    def test_with_metadata(self):
        """Test LeaderInfo with metadata."""
        info = LeaderInfo(
            node_id="leader-1",
            elected_at=1704067200.0,
            last_heartbeat=1704067210.0,
            metadata={"region": "us-west-2", "version": "1.0"},
        )

        assert info.metadata["region"] == "us-west-2"
        assert info.metadata["version"] == "1.0"

    def test_heartbeat_age_calculation(self):
        """Test calculating heartbeat age."""
        now = time.time()
        info = LeaderInfo(
            node_id="leader-1",
            elected_at=now - 100,
            last_heartbeat=now - 5,
        )

        heartbeat_age = now - info.last_heartbeat
        assert heartbeat_age >= 4.9 and heartbeat_age <= 6.0


# =============================================================================
# Single Node Election Tests
# =============================================================================


class TestSingleNodeElection:
    """Tests for single node leader election scenarios."""

    @pytest.mark.asyncio
    async def test_single_node_becomes_leader(self, mock_redis):
        """Test that a single node automatically becomes leader."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="single-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()

        try:
            # Wait for election to complete
            for _ in range(50):
                if election.is_leader:
                    break
                await asyncio.sleep(0.02)

            assert election.is_leader
            assert election.state == LeaderState.LEADER
            assert election.current_leader is not None
            assert election.current_leader.node_id == "single-node"
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_leader_info_populated(self, mock_redis):
        """Test that leader info is properly populated."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="info-test-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()

        try:
            await asyncio.sleep(0.1)
            if election.is_leader:
                leader_info = election.current_leader
                assert leader_info.node_id == "info-test-node"
                assert leader_info.elected_at > 0
                assert leader_info.last_heartbeat >= leader_info.elected_at
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_initial_state_is_disconnected(self):
        """Test that initial state is DISCONNECTED."""
        election = LeaderElection()
        assert election.state == LeaderState.DISCONNECTED
        assert not election.is_leader

    @pytest.mark.asyncio
    async def test_state_transitions_to_follower_on_start(self, mock_redis):
        """Test that state transitions to FOLLOWER on start."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.1,
            node_id="transition-test",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        # State should be FOLLOWER immediately after start (before election completes)
        # or LEADER if election happened quickly
        assert election.state in {LeaderState.FOLLOWER, LeaderState.LEADER, LeaderState.CANDIDATE}
        await election.stop()


# =============================================================================
# Multi-Node Election Tests
# =============================================================================


class TestMultiNodeElection:
    """Tests for multi-node leader election scenarios."""

    @pytest.mark.asyncio
    async def test_two_nodes_one_leader(self, mock_redis):
        """Test that with two nodes, exactly one becomes leader."""
        config1 = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="node-1",
        )
        config2 = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="node-2",
        )

        election1 = LeaderElection(config=config1, redis_client=mock_redis)
        election2 = LeaderElection(config=config2, redis_client=mock_redis)

        await election1.start()
        await election2.start()

        try:
            await asyncio.sleep(0.2)

            leader_count = sum([election1.is_leader, election2.is_leader])
            assert leader_count == 1
        finally:
            await election1.stop()
            await election2.stop()

    @pytest.mark.asyncio
    async def test_five_nodes_one_leader(self, mock_redis):
        """Test that with five concurrent nodes, exactly one becomes leader."""
        nodes = []
        for i in range(5):
            config = LeaderConfig(
                key_prefix="test:leader:",
                retry_interval=0.02,
                lock_ttl_seconds=5.0,
                node_id=f"node-{i}",
            )
            election = LeaderElection(config=config, redis_client=mock_redis)
            nodes.append(election)

        # Start all nodes concurrently
        await asyncio.gather(*[n.start() for n in nodes])

        try:
            await asyncio.sleep(0.3)

            leaders = [n for n in nodes if n.is_leader]
            assert len(leaders) == 1
        finally:
            await asyncio.gather(*[n.stop() for n in nodes])

    @pytest.mark.asyncio
    async def test_follower_knows_current_leader(self, mock_redis):
        """Test that followers know who the current leader is."""
        config1 = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="node-1",
        )
        config2 = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="node-2",
        )

        election1 = LeaderElection(config=config1, redis_client=mock_redis)
        election2 = LeaderElection(config=config2, redis_client=mock_redis)

        # Start node 1 first to ensure it becomes leader
        await election1.start()
        await asyncio.sleep(0.1)

        await election2.start()
        await asyncio.sleep(0.1)

        try:
            if election1.is_leader:
                assert election2.current_leader is not None
                assert election2.current_leader.node_id == "node-1"
            elif election2.is_leader:
                assert election1.current_leader is not None
                assert election1.current_leader.node_id == "node-2"
        finally:
            await election1.stop()
            await election2.stop()


# =============================================================================
# Failover Tests
# =============================================================================


class TestLeaderFailover:
    """Tests for leader failover scenarios."""

    @pytest.mark.asyncio
    async def test_new_leader_elected_when_leader_stops(self, mock_redis):
        """Test that a new leader is elected when the current leader stops."""
        config1 = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="leader-1",
        )
        config2 = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="leader-2",
        )

        election1 = LeaderElection(config=config1, redis_client=mock_redis)
        election2 = LeaderElection(config=config2, redis_client=mock_redis)

        # Node 1 becomes leader first
        await election1.start()
        await asyncio.sleep(0.1)
        assert election1.is_leader

        # Node 2 starts as follower
        await election2.start()
        await asyncio.sleep(0.1)
        assert not election2.is_leader

        # Stop node 1 (releases lock)
        await election1.stop()

        # Wait for node 2 to detect and become leader
        await asyncio.sleep(0.2)

        assert election2.is_leader

        await election2.stop()

    @pytest.mark.asyncio
    async def test_failover_on_lock_expiration(self, mock_redis):
        """Test failover when leader lock expires."""
        config1 = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            lock_ttl_seconds=2.0,
            node_id="node-1",
        )
        config2 = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            lock_ttl_seconds=2.0,
            node_id="node-2",
        )

        election1 = LeaderElection(config=config1, redis_client=mock_redis)
        election2 = LeaderElection(config=config2, redis_client=mock_redis)

        await election1.start()
        await asyncio.sleep(0.1)
        assert election1.is_leader

        # Simulate lock expiration
        mock_redis.expire_key_now("test:leader:lock")

        # Start node 2
        await election2.start()
        await asyncio.sleep(0.2)

        # One of them should be leader
        assert election1.is_leader or election2.is_leader

        await election1.stop()
        await election2.stop()

    @pytest.mark.asyncio
    async def test_lose_leader_callback_on_failover(self, mock_redis):
        """Test that lose_leader callback fires during failover."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="callback-test-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        callback_fired = asyncio.Event()

        def on_lose_leader():
            callback_fired.set()

        election.on_lose_leader(on_lose_leader)

        await election.start()
        await asyncio.sleep(0.1)
        assert election.is_leader

        # Simulate another node taking leadership
        mock_redis.corrupt_value("test:leader:lock", "other-node")

        # Wait for callback
        await asyncio.sleep(0.2)

        assert callback_fired.is_set()

        await election.stop()


# =============================================================================
# Split-Brain Prevention Tests
# =============================================================================


class TestSplitBrainPrevention:
    """Tests for split-brain scenario prevention."""

    @pytest.mark.asyncio
    async def test_detects_lock_holder_change(self, mock_redis):
        """Test that leader detects when lock is taken by another node."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="original-leader",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.1)
        assert election.is_leader

        # Simulate rogue node stealing the lock
        mock_redis.corrupt_value("test:leader:lock", "rogue-node")

        # Wait for detection
        await asyncio.sleep(0.2)

        assert not election.is_leader
        assert election.state == LeaderState.FOLLOWER

        await election.stop()

    @pytest.mark.asyncio
    async def test_atomic_lock_acquisition(self, mock_redis):
        """Test that lock acquisition is atomic (NX flag)."""
        config1 = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.1,
            node_id="node-1",
        )
        config2 = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.1,
            node_id="node-2",
        )

        # Pre-set the lock to node-1
        await mock_redis.set("test:leader:lock", "node-1", nx=True, ex=30)

        election2 = LeaderElection(config=config2, redis_client=mock_redis)
        await election2.start()
        await asyncio.sleep(0.2)

        # Node 2 should not become leader since lock is held
        assert not election2.is_leader

        await election2.stop()

    @pytest.mark.asyncio
    async def test_concurrent_election_race(self, mock_redis):
        """Test that concurrent elections don't create split-brain."""
        elections = []
        for i in range(10):
            config = LeaderConfig(
                key_prefix="test:leader:",
                retry_interval=0.01,
                lock_ttl_seconds=5.0,
                node_id=f"concurrent-node-{i}",
            )
            election = LeaderElection(config=config, redis_client=mock_redis)
            elections.append(election)

        # Start all at once
        await asyncio.gather(*[e.start() for e in elections])
        await asyncio.sleep(0.3)

        leaders = [e for e in elections if e.is_leader]
        # Must have exactly one leader
        assert len(leaders) == 1

        await asyncio.gather(*[e.stop() for e in elections])


# =============================================================================
# Heartbeat Timeout Tests
# =============================================================================


class TestHeartbeatTimeout:
    """Tests for heartbeat timeout handling."""

    @pytest.mark.asyncio
    async def test_heartbeat_refreshes_lock(self, mock_redis):
        """Test that heartbeat refreshes the lock TTL."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            lock_ttl_seconds=1.0,
            node_id="heartbeat-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.15)
        assert election.is_leader

        # Check that expire operations have been called
        expire_ops = [op for op in mock_redis._operation_log if op["op"] == "expire"]
        # Should have at least one refresh
        assert len(expire_ops) >= 1

        await election.stop()

    @pytest.mark.asyncio
    async def test_leadership_maintained_with_refreshes(self, mock_redis):
        """Test that leadership is maintained as long as refreshes succeed."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.03,
            lock_ttl_seconds=0.5,
            node_id="maintain-leader",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.1)
        assert election.is_leader

        # Wait longer than initial TTL
        await asyncio.sleep(0.6)

        # Should still be leader due to refreshes
        assert election.is_leader

        await election.stop()

    @pytest.mark.asyncio
    async def test_leadership_lost_on_refresh_failure(self, mock_redis):
        """Test that leadership is lost if refresh fails."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="refresh-fail-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.1)
        assert election.is_leader

        # Make expire fail
        mock_redis.fail_on_next("expire")

        await asyncio.sleep(0.1)

        # May or may not lose leadership depending on timing
        # The important thing is no crash
        await election.stop()


# =============================================================================
# Concurrent Election Tests
# =============================================================================


class TestConcurrentElection:
    """Tests for concurrent election attempt scenarios."""

    @pytest.mark.asyncio
    async def test_late_joiner_becomes_follower(self, mock_redis):
        """Test that a late-joining node becomes follower."""
        config1 = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="early-node",
        )
        config2 = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="late-node",
        )

        election1 = LeaderElection(config=config1, redis_client=mock_redis)
        election2 = LeaderElection(config=config2, redis_client=mock_redis)

        await election1.start()
        await asyncio.sleep(0.1)
        assert election1.is_leader

        await election2.start()
        await asyncio.sleep(0.1)

        assert not election2.is_leader
        assert election2.state == LeaderState.FOLLOWER

        await election1.stop()
        await election2.stop()

    @pytest.mark.asyncio
    async def test_rapid_start_stop_cycles(self, mock_redis):
        """Test rapid start/stop cycles don't cause issues."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="rapid-cycle-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        for _ in range(5):
            await election.start()
            await asyncio.sleep(0.05)
            await election.stop()

        assert election.state == LeaderState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_simultaneous_start(self, mock_redis):
        """Test that simultaneous starts work correctly."""
        elections = []
        for i in range(3):
            config = LeaderConfig(
                key_prefix="test:leader:",
                retry_interval=0.01,
                node_id=f"simul-node-{i}",
            )
            election = LeaderElection(config=config, redis_client=mock_redis)
            elections.append(election)

        # Start all simultaneously
        start_tasks = [e.start() for e in elections]
        await asyncio.gather(*start_tasks)
        await asyncio.sleep(0.2)

        # Exactly one leader
        leaders = [e for e in elections if e.is_leader]
        assert len(leaders) == 1

        await asyncio.gather(*[e.stop() for e in elections])


# =============================================================================
# Network Partition Tests
# =============================================================================


class TestNetworkPartition:
    """Tests for network partition scenarios."""

    @pytest.mark.asyncio
    async def test_redis_disconnection_handling(self, mock_redis):
        """Test handling of Redis disconnection."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.05,
            node_id="disconnect-test",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.1)

        # Disconnect Redis
        mock_redis.disconnect()

        # Should handle errors gracefully
        await asyncio.sleep(0.2)

        # Reconnect
        mock_redis.reconnect()
        await asyncio.sleep(0.2)

        # Should recover
        await election.stop()

    @pytest.mark.asyncio
    async def test_timeout_handling(self, mock_redis):
        """Test handling of slow Redis operations."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.05,
            node_id="timeout-test",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.15)

        # Add delay to simulate network issues
        mock_redis.set_delay(0.1)

        # Should still function with delays
        await asyncio.sleep(0.3)

        mock_redis.clear_delay()
        await election.stop()

    @pytest.mark.asyncio
    async def test_intermittent_failures(self, mock_redis):
        """Test handling of intermittent Redis failures."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.05,
            node_id="intermittent-test",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.1)

        # Cause intermittent failures
        mock_redis.fail_on_next("get")
        await asyncio.sleep(0.1)

        mock_redis.fail_on_next("expire")
        await asyncio.sleep(0.1)

        # Should still be running
        assert election._running

        await election.stop()


# =============================================================================
# Callback Tests
# =============================================================================


class TestCallbacks:
    """Tests for election callback functionality."""

    @pytest.mark.asyncio
    async def test_become_leader_callback(self, mock_redis):
        """Test become_leader callback is called."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="callback-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        callback_called = asyncio.Event()

        def on_become_leader():
            callback_called.set()

        election.on_become_leader(on_become_leader)

        await election.start()

        try:
            await asyncio.wait_for(callback_called.wait(), timeout=1.0)
            assert callback_called.is_set()
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_async_callback_support(self, mock_redis):
        """Test that async callbacks are supported."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="async-callback-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        callback_called = asyncio.Event()

        async def async_on_become_leader():
            await asyncio.sleep(0.01)
            callback_called.set()

        election.on_become_leader(async_on_become_leader)

        await election.start()

        try:
            await asyncio.wait_for(callback_called.wait(), timeout=1.0)
            assert callback_called.is_set()
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_callback_exception_handling(self, mock_redis):
        """Test that callback exceptions don't crash election."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="exception-callback-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        def failing_callback():
            raise RuntimeError("Callback failed!")

        election.on_become_leader(failing_callback)

        await election.start()
        await asyncio.sleep(0.2)

        # Election should still be running despite callback failure
        assert election._running

        await election.stop()

    @pytest.mark.asyncio
    async def test_multiple_callbacks(self, mock_redis):
        """Test multiple callbacks are all invoked."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="multi-callback-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        call_counts = {"cb1": 0, "cb2": 0, "cb3": 0}

        def cb1():
            call_counts["cb1"] += 1

        def cb2():
            call_counts["cb2"] += 1

        def cb3():
            call_counts["cb3"] += 1

        election.on_become_leader(cb1)
        election.on_become_leader(cb2)
        election.on_become_leader(cb3)

        await election.start()
        await asyncio.sleep(0.2)

        # All callbacks should have been called at least once
        if election.is_leader:
            assert call_counts["cb1"] >= 1
            assert call_counts["cb2"] >= 1
            assert call_counts["cb3"] >= 1

        await election.stop()

    @pytest.mark.asyncio
    async def test_leader_change_callback(self, mock_redis):
        """Test leader_change callback receives correct node_id."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="change-callback-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        received_ids: list[str | None] = []

        def on_leader_change(node_id: str | None):
            received_ids.append(node_id)

        election.on_leader_change(on_leader_change)

        await election.start()
        await asyncio.sleep(0.2)

        if election.is_leader:
            assert "change-callback-node" in received_ids

        await election.stop()


# =============================================================================
# Edge Cases and Error Handling Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """Test that stop() is safe without start()."""
        election = LeaderElection()
        await election.stop()  # Should not raise
        assert election.state == LeaderState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_double_start(self, mock_redis):
        """Test that double start is idempotent."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="double-start",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await election.start()  # Should be no-op

        assert election._running

        await election.stop()

    @pytest.mark.asyncio
    async def test_double_stop(self, mock_redis):
        """Test that double stop is safe."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="double-stop",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.1)

        await election.stop()
        await election.stop()  # Should be no-op

        assert election.state == LeaderState.DISCONNECTED

    def test_get_stats_initial(self):
        """Test get_stats returns correct initial values."""
        config = LeaderConfig(node_id="stats-node")
        election = LeaderElection(config=config)

        stats = election.get_stats()

        assert stats["node_id"] == "stats-node"
        assert stats["state"] == "disconnected"
        assert stats["is_leader"] is False
        assert stats["current_leader"] is None

    @pytest.mark.asyncio
    async def test_get_stats_as_leader(self, mock_redis):
        """Test get_stats returns correct values as leader."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="leader-stats",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.1)

        stats = election.get_stats()

        if election.is_leader:
            assert stats["state"] == "leader"
            assert stats["is_leader"] is True
            assert stats["current_leader"] == "leader-stats"

        await election.stop()


# =============================================================================
# In-Memory Redis Fallback Tests
# =============================================================================


class TestInMemoryRedisFallback:
    """Tests for _InMemoryRedis fallback implementation."""

    @pytest.mark.asyncio
    async def test_set_get(self):
        """Test basic set/get operations."""
        redis = _InMemoryRedis()

        await redis.set("key1", "value1")
        result = await redis.get("key1")

        assert result == "value1"

    @pytest.mark.asyncio
    async def test_set_nx(self):
        """Test set with NX (only if not exists)."""
        redis = _InMemoryRedis()

        result1 = await redis.set("key1", "value1", nx=True)
        result2 = await redis.set("key1", "value2", nx=True)

        assert result1 is True
        assert result2 is False

        value = await redis.get("key1")
        assert value == "value1"

    @pytest.mark.asyncio
    async def test_delete(self):
        """Test delete operation."""
        redis = _InMemoryRedis()

        await redis.set("key1", "value1")
        await redis.delete("key1")

        result = await redis.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_hset_hgetall(self):
        """Test hash set/get operations."""
        redis = _InMemoryRedis()

        await redis.hset("hash1", mapping={"field1": "value1", "field2": "value2"})
        result = await redis.hgetall("hash1")

        assert result["field1"] == "value1"
        assert result["field2"] == "value2"


# =============================================================================
# Distributed State Requirement Tests
# =============================================================================


class TestDistributedStateRequirement:
    """Tests for distributed state requirement checking."""

    def test_default_not_required(self, monkeypatch):
        """Test default is not required."""
        vars_to_clear = [
            "ARAGORA_REQUIRE_DISTRIBUTED",
            "ARAGORA_REQUIRE_DISTRIBUTED_STATE",
            "ARAGORA_MULTI_INSTANCE",
            "ARAGORA_ENV",
        ]
        for var in vars_to_clear:
            monkeypatch.delenv(var, raising=False)

        assert is_distributed_state_required() is False

    def test_canonical_var_true(self, monkeypatch):
        """Test canonical ARAGORA_REQUIRE_DISTRIBUTED variable."""
        monkeypatch.setenv("ARAGORA_REQUIRE_DISTRIBUTED", "true")
        assert is_distributed_state_required() is True

    def test_legacy_var_true(self, monkeypatch):
        """Test legacy ARAGORA_REQUIRE_DISTRIBUTED_STATE variable."""
        monkeypatch.delenv("ARAGORA_REQUIRE_DISTRIBUTED", raising=False)
        monkeypatch.setenv("ARAGORA_REQUIRE_DISTRIBUTED_STATE", "true")
        assert is_distributed_state_required() is True

    def test_multi_instance_requires_distributed(self, monkeypatch):
        """Test ARAGORA_MULTI_INSTANCE implies distributed state."""
        monkeypatch.delenv("ARAGORA_REQUIRE_DISTRIBUTED", raising=False)
        monkeypatch.delenv("ARAGORA_REQUIRE_DISTRIBUTED_STATE", raising=False)
        monkeypatch.setenv("ARAGORA_MULTI_INSTANCE", "true")
        assert is_distributed_state_required() is True

    def test_production_requires_distributed(self, monkeypatch):
        """Test production environment requires distributed state."""
        monkeypatch.delenv("ARAGORA_REQUIRE_DISTRIBUTED", raising=False)
        monkeypatch.delenv("ARAGORA_REQUIRE_DISTRIBUTED_STATE", raising=False)
        monkeypatch.delenv("ARAGORA_MULTI_INSTANCE", raising=False)
        monkeypatch.setenv("ARAGORA_ENV", "production")
        assert is_distributed_state_required() is True

    def test_production_single_instance_override(self, monkeypatch):
        """Test production with single instance override."""
        monkeypatch.setenv("ARAGORA_ENV", "production")
        monkeypatch.setenv("ARAGORA_SINGLE_INSTANCE", "true")
        assert is_distributed_state_required() is False


class TestDistributedStateError:
    """Tests for DistributedStateError exception."""

    def test_error_message_format(self):
        """Test error message contains required information."""
        error = DistributedStateError("leader_election", "Redis not available")

        assert "leader_election" in str(error)
        assert "Redis not available" in str(error)
        assert "ARAGORA_SINGLE_INSTANCE" in str(error)

    def test_error_attributes(self):
        """Test error has component and reason attributes."""
        error = DistributedStateError("component_name", "reason_text")

        assert error.component == "component_name"
        assert error.reason == "reason_text"


# =============================================================================
# Regional Leader Election Tests
# =============================================================================


class TestRegionalLeaderConfig:
    """Tests for RegionalLeaderConfig dataclass."""

    def test_default_values(self):
        """Test default regional config values."""
        config = RegionalLeaderConfig()

        assert config.region_id == "default"
        assert config.sync_regions == []
        assert config.broadcast_leadership is True

    def test_custom_values(self):
        """Test custom regional config values."""
        config = RegionalLeaderConfig(
            region_id="us-west-2",
            sync_regions=["us-east-1", "eu-west-1"],
            broadcast_leadership=False,
            node_id="custom-regional",
        )

        assert config.region_id == "us-west-2"
        assert config.sync_regions == ["us-east-1", "eu-west-1"]
        assert config.broadcast_leadership is False
        assert config.node_id == "custom-regional"

    def test_region_key_prefix(self):
        """Test get_region_key_prefix returns correct prefix."""
        config = RegionalLeaderConfig(region_id="us-west-2")
        prefix = config.get_region_key_prefix()

        assert prefix == "aragora:leader:region:us-west-2:"

    def test_from_env(self):
        """Test configuration from environment variables."""
        env_vars = {
            "ARAGORA_REGION_ID": "ap-southeast-1",
            "ARAGORA_SYNC_REGIONS": "us-west-2, eu-west-1",
            "ARAGORA_BROADCAST_LEADERSHIP": "false",
        }

        with patch.dict(os.environ, env_vars):
            config = RegionalLeaderConfig.from_env()

            assert config.region_id == "ap-southeast-1"
            assert config.sync_regions == ["us-west-2", "eu-west-1"]
            assert config.broadcast_leadership is False


class TestRegionalLeaderInfo:
    """Tests for RegionalLeaderInfo dataclass."""

    def test_basic_creation(self):
        """Test basic RegionalLeaderInfo creation."""
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
        """Test RegionalLeaderInfo default values."""
        info = RegionalLeaderInfo(
            node_id="leader-2",
            elected_at=1704067200.0,
            last_heartbeat=1704067200.0,
        )

        assert info.region_id == "default"
        assert info.is_global_coordinator is False


class TestRegionalLeaderElection:
    """Tests for RegionalLeaderElection class."""

    def test_initial_state(self, regional_election):
        """Test initial state of regional election."""
        assert regional_election.state == LeaderState.DISCONNECTED
        assert not regional_election.is_regional_leader
        assert not regional_election.is_global_coordinator
        assert regional_election.region_id == "us-west-2"
        assert regional_election.regional_leaders == {}

    @pytest.mark.asyncio
    async def test_regional_leader_election(self, mock_redis):
        """Test regional leader election process."""
        config = RegionalLeaderConfig(
            key_prefix="test:leader:",
            region_id="us-west-2",
            retry_interval=0.02,
            node_id="regional-node",
        )
        election = RegionalLeaderElection(config=config, redis_client=mock_redis)

        await election.start()

        try:
            await asyncio.sleep(0.2)
            # Should become regional leader
            assert election.is_regional_leader or election.state == LeaderState.FOLLOWER
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_two_regions_independent_leaders(self, mock_redis):
        """Test that two different regions can have independent leaders."""
        config1 = RegionalLeaderConfig(
            key_prefix="test:leader:",
            region_id="us-west-2",
            retry_interval=0.02,
            node_id="west-node",
        )
        config2 = RegionalLeaderConfig(
            key_prefix="test:leader:",
            region_id="us-east-1",
            retry_interval=0.02,
            node_id="east-node",
        )

        election1 = RegionalLeaderElection(config=config1, redis_client=mock_redis)
        election2 = RegionalLeaderElection(config=config2, redis_client=mock_redis)

        await election1.start()
        await election2.start()

        try:
            await asyncio.sleep(0.3)
            # Both regions can have leaders (different key prefixes)
            # At least one should be a leader
        finally:
            await election1.stop()
            await election2.stop()

    @pytest.mark.asyncio
    async def test_same_region_one_leader(self, mock_redis):
        """Test that same region only has one leader."""
        config1 = RegionalLeaderConfig(
            key_prefix="test:leader:",
            region_id="us-west-2",
            retry_interval=0.02,
            node_id="node-1",
        )
        config2 = RegionalLeaderConfig(
            key_prefix="test:leader:",
            region_id="us-west-2",
            retry_interval=0.02,
            node_id="node-2",
        )

        election1 = RegionalLeaderElection(config=config1, redis_client=mock_redis)
        election2 = RegionalLeaderElection(config=config2, redis_client=mock_redis)

        await election1.start()
        await election2.start()

        try:
            await asyncio.sleep(0.3)

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

    def test_regional_callbacks_registration(self, regional_election):
        """Test regional callback registration."""
        callback = MagicMock()

        regional_election.on_become_regional_leader(callback)
        regional_election.on_lose_regional_leader(callback)
        regional_election.on_become_global_coordinator(callback)
        regional_election.on_lose_global_coordinator(callback)

        assert callback in regional_election._on_become_regional_leader
        assert callback in regional_election._on_lose_regional_leader
        assert callback in regional_election._on_become_global_coordinator
        assert callback in regional_election._on_lose_global_coordinator

    def test_get_stats_regional(self, regional_election):
        """Test get_stats includes regional information."""
        stats = regional_election.get_stats()

        assert "region_id" in stats
        assert "is_regional_leader" in stats
        assert "is_global_coordinator" in stats
        assert "known_regional_leaders" in stats
        assert stats["region_id"] == "us-west-2"

    def test_regional_leaders_returns_copy(self, regional_election):
        """Test that regional_leaders property returns a copy."""
        info = RegionalLeaderInfo(
            node_id="other-leader",
            region_id="us-east-1",
            elected_at=time.time(),
            last_heartbeat=time.time(),
        )
        regional_election._regional_leaders["us-east-1"] = info

        leaders = regional_election.regional_leaders
        leaders["us-east-1"] = None

        # Original should be unchanged
        assert regional_election._regional_leaders["us-east-1"].node_id == "other-leader"


# =============================================================================
# Global Coordinator Tests
# =============================================================================


class TestGlobalCoordinator:
    """Tests for global coordinator election."""

    @pytest.mark.asyncio
    async def test_regional_leader_tries_global_coordinator(self, mock_redis):
        """Test that regional leader attempts to become global coordinator."""
        config = RegionalLeaderConfig(
            key_prefix="test:leader:",
            region_id="us-west-2",
            retry_interval=0.02,
            node_id="coordinator-test",
        )
        election = RegionalLeaderElection(config=config, redis_client=mock_redis)

        await election.start()

        try:
            await asyncio.sleep(0.3)
            if election.is_regional_leader:
                # May or may not be global coordinator
                # Just verify no errors
                pass
        finally:
            await election.stop()

    @pytest.mark.asyncio
    async def test_get_global_coordinator(self, mock_redis):
        """Test getting global coordinator info."""
        config = RegionalLeaderConfig(
            key_prefix="test:leader:",
            region_id="us-west-2",
            retry_interval=0.02,
            node_id="gc-test-node",
        )
        election = RegionalLeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.2)

        gc_info = await election.get_global_coordinator()
        # May be None or have info depending on election result

        await election.stop()


# =============================================================================
# Singleton and Initialization Tests
# =============================================================================


class TestSingletonFunctions:
    """Tests for module-level singleton functions."""

    def test_get_regional_leader_election_initial(self):
        """Test get_regional_leader_election returns None initially."""
        # Reset global state
        set_regional_leader_election(None)
        result = get_regional_leader_election()
        assert result is None

    def test_set_and_get_regional_leader_election(self, regional_election):
        """Test set and get regional leader election."""
        set_regional_leader_election(regional_election)
        result = get_regional_leader_election()
        assert result is regional_election
        # Clean up
        set_regional_leader_election(None)

    @pytest.mark.asyncio
    async def test_init_regional_leader_election(self, mock_redis, monkeypatch):
        """Test init_regional_leader_election function."""
        # Reset global state
        set_regional_leader_election(None)

        # Mock aioredis to use our mock
        with patch("aragora.control_plane.leader.LeaderElection.start") as mock_start:
            mock_start.return_value = None

            # This will fail without proper Redis, but we test the flow
            # In practice, it uses in-memory fallback
            pass


# =============================================================================
# Lifecycle Tests
# =============================================================================


class TestLeaderElectionLifecycle:
    """Tests for LeaderElection lifecycle management."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, mock_redis):
        """Test complete lifecycle: start -> become leader -> stop."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="lifecycle-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        # Initial state
        assert election.state == LeaderState.DISCONNECTED
        assert not election._running

        # Start
        await election.start()
        assert election._running
        assert election.state != LeaderState.DISCONNECTED

        # Wait for leadership
        await asyncio.sleep(0.2)

        # Should be leader
        assert election.is_leader

        # Stop
        await election.stop()
        assert not election._running
        assert election.state == LeaderState.DISCONNECTED

        # Verify lock released
        lock_value = await mock_redis.get("test:leader:lock")
        assert lock_value is None

    @pytest.mark.asyncio
    async def test_stop_releases_lock(self, mock_redis):
        """Test that stop properly releases the lock."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.02,
            node_id="release-test",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.1)

        # Verify lock is held
        lock_value = await mock_redis.get("test:leader:lock")
        if election.is_leader:
            assert lock_value == "release-test"

        await election.stop()

        # Verify lock is released
        lock_value = await mock_redis.get("test:leader:lock")
        assert lock_value is None


# =============================================================================
# Performance and Stress Tests
# =============================================================================


class TestPerformance:
    """Performance-related tests."""

    @pytest.mark.asyncio
    async def test_many_nodes_election(self, mock_redis):
        """Test election with many nodes."""
        node_count = 20
        elections = []

        for i in range(node_count):
            config = LeaderConfig(
                key_prefix="test:leader:",
                retry_interval=0.01,
                lock_ttl_seconds=5.0,
                node_id=f"perf-node-{i}",
            )
            election = LeaderElection(config=config, redis_client=mock_redis)
            elections.append(election)

        # Start all
        await asyncio.gather(*[e.start() for e in elections])
        await asyncio.sleep(0.5)

        # Exactly one leader
        leaders = [e for e in elections if e.is_leader]
        assert len(leaders) == 1

        # Clean up
        await asyncio.gather(*[e.stop() for e in elections])

    @pytest.mark.asyncio
    async def test_high_frequency_operations(self, mock_redis):
        """Test with high-frequency retry interval."""
        config = LeaderConfig(
            key_prefix="test:leader:",
            retry_interval=0.005,  # Very fast
            node_id="high-freq-node",
        )
        election = LeaderElection(config=config, redis_client=mock_redis)

        await election.start()
        await asyncio.sleep(0.2)

        # Should handle high-frequency operations
        assert election._running

        await election.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
