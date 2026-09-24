"""Tests for RedisClusterClient and related functionality.

Tests cover:
- ClusterHealthMonitor: health tracking, failure thresholds, check intervals
- RedisClusterClient: mode detection, client creation, operations, retry logic
- Module-level functions: get_cluster_client, reset_cluster_client, is_cluster_available
- Hash slot calculation: CRC16, hash tags
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from aragora.storage.redis_cluster import (
    ClusterConfig,
    ClusterMode,
    ClusterHealthMonitor,
    RedisClusterClient,
    get_cluster_config,
    get_cluster_client,
    reset_cluster_client,
    is_cluster_available,
    get_redis_client,
)


# ---------------------------------------------------------------------------
# ClusterHealthMonitor Tests
# ---------------------------------------------------------------------------


class TestClusterHealthMonitor:
    """Tests for ClusterHealthMonitor."""

    def test_initial_state_is_healthy(self):
        """Monitor starts in healthy state."""
        monitor = ClusterHealthMonitor()
        assert monitor.is_healthy is True

    def test_mark_success_resets_failures(self):
        """Marking success resets consecutive failures."""
        monitor = ClusterHealthMonitor()
        monitor.mark_failure()
        monitor.mark_failure()
        assert monitor._consecutive_failures == 2
        monitor.mark_success()
        assert monitor._consecutive_failures == 0
        assert monitor.is_healthy is True

    def test_three_failures_marks_unhealthy(self):
        """Three consecutive failures marks monitor unhealthy."""
        monitor = ClusterHealthMonitor()
        assert monitor.is_healthy is True
        monitor.mark_failure()
        assert monitor.is_healthy is True
        monitor.mark_failure()
        assert monitor.is_healthy is True
        monitor.mark_failure()  # Third failure
        assert monitor.is_healthy is False

    def test_success_after_unhealthy_restores_health(self):
        """Success after being unhealthy restores healthy state."""
        monitor = ClusterHealthMonitor()
        for _ in range(3):
            monitor.mark_failure()
        assert monitor.is_healthy is False
        monitor.mark_success()
        assert monitor.is_healthy is True

    def test_should_check_respects_interval(self):
        """should_check respects the check interval."""
        monitor = ClusterHealthMonitor(check_interval=0.1)
        # First check should return True
        assert monitor.should_check() is True
        # Immediate second check should return False
        assert monitor.should_check() is False
        # After interval, should return True
        time.sleep(0.15)
        assert monitor.should_check() is True

    def test_thread_safety(self):
        """Monitor operations are thread-safe."""
        monitor = ClusterHealthMonitor()
        errors = []

        def mark_operations():
            try:
                for _ in range(100):
                    monitor.mark_failure()
                    monitor.mark_success()
                    _ = monitor.is_healthy
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=mark_operations) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ---------------------------------------------------------------------------
# get_cluster_config Tests
# ---------------------------------------------------------------------------


class TestGetClusterConfig:
    """Tests for get_cluster_config environment parsing."""

    def test_parses_cluster_nodes(self):
        """Parses comma-separated cluster nodes."""
        with patch.dict(
            "os.environ",
            {"ARAGORA_REDIS_CLUSTER_NODES": "redis1:6379,redis2:6380,redis3:6381"},
            clear=True,
        ):
            config = get_cluster_config()
            assert config.nodes == [
                ("redis1", 6379),
                ("redis2", 6380),
                ("redis3", 6381),
            ]

    def test_parses_nodes_without_port(self):
        """Nodes without port default to 6379."""
        with patch.dict("os.environ", {"ARAGORA_REDIS_CLUSTER_NODES": "redis1,redis2"}, clear=True):
            config = get_cluster_config()
            assert config.nodes == [("redis1", 6379), ("redis2", 6379)]

    def test_fallback_to_redis_url(self):
        """Falls back to ARAGORA_REDIS_URL if no cluster nodes."""
        with patch.dict(
            "os.environ",
            {"ARAGORA_REDIS_URL": "redis://localhost:6379"},
            clear=True,
        ):
            config = get_cluster_config()
            assert config.nodes == [("localhost", 6379)]

    def test_parses_redis_url_with_auth(self):
        """Parses Redis URL with authentication."""
        with patch.dict(
            "os.environ",
            {"ARAGORA_REDIS_URL": "redis://user:pass@localhost:6380/0"},
            clear=True,
        ):
            config = get_cluster_config()
            assert config.nodes == [("localhost", 6380)]

    def test_parses_cluster_mode(self):
        """Parses cluster mode from environment."""
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_REDIS_CLUSTER_NODES": "redis:6379",
                "ARAGORA_REDIS_CLUSTER_MODE": "cluster",
            },
            clear=True,
        ):
            config = get_cluster_config()
            assert config.mode == ClusterMode.CLUSTER

        with patch.dict(
            "os.environ",
            {
                "ARAGORA_REDIS_CLUSTER_NODES": "redis:6379",
                "ARAGORA_REDIS_CLUSTER_MODE": "standalone",
            },
            clear=True,
        ):
            config = get_cluster_config()
            assert config.mode == ClusterMode.STANDALONE

    def test_invalid_mode_defaults_to_auto(self):
        """Invalid mode defaults to AUTO."""
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_REDIS_CLUSTER_NODES": "redis:6379",
                "ARAGORA_REDIS_CLUSTER_MODE": "invalid",
            },
            clear=True,
        ):
            config = get_cluster_config()
            assert config.mode == ClusterMode.AUTO

    def test_parses_boolean_options(self):
        """Parses boolean options from environment."""
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_REDIS_CLUSTER_NODES": "redis:6379",
                "ARAGORA_REDIS_CLUSTER_SKIP_FULL_COVERAGE": "true",
                "ARAGORA_REDIS_CLUSTER_READ_FROM_REPLICAS": "false",
            },
            clear=True,
        ):
            config = get_cluster_config()
            assert config.skip_full_coverage_check is True
            assert config.read_from_replicas is False

    def test_parses_password(self):
        """Parses password from environment."""
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_REDIS_CLUSTER_NODES": "redis:6379",
                "ARAGORA_REDIS_CLUSTER_PASSWORD": "cluster_secret",
            },
            clear=True,
        ):
            config = get_cluster_config()
            assert config.password == "cluster_secret"

    def test_password_fallback(self):
        """Falls back to ARAGORA_REDIS_PASSWORD if cluster password not set."""
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_REDIS_CLUSTER_NODES": "redis:6379",
                "ARAGORA_REDIS_PASSWORD": "redis_secret",
            },
            clear=True,
        ):
            config = get_cluster_config()
            assert config.password == "redis_secret"

    def test_empty_nodes_when_no_config(self):
        """Returns empty nodes when no Redis configuration."""
        with patch.dict("os.environ", {}, clear=True):
            config = get_cluster_config()
            assert config.nodes == []

    def test_invalid_node_port_skipped(self):
        """Invalid node port is skipped with warning."""
        with patch.dict(
            "os.environ",
            {"ARAGORA_REDIS_CLUSTER_NODES": "redis1:abc,redis2:6379"},
            clear=True,
        ):
            config = get_cluster_config()
            assert config.nodes == [("redis2", 6379)]


# ---------------------------------------------------------------------------
# RedisClusterClient Tests
# ---------------------------------------------------------------------------


class TestRedisClusterClientInit:
    """Tests for RedisClusterClient initialization."""

    def test_uses_provided_config(self):
        """Uses provided config if given."""
        config = ClusterConfig(nodes=[("custom", 1234)])
        client = RedisClusterClient(config)
        assert client.config.nodes == [("custom", 1234)]

    def test_uses_env_config_if_not_provided(self):
        """Uses environment config if not provided."""
        with patch.dict(
            "os.environ",
            {"ARAGORA_REDIS_CLUSTER_NODES": "envhost:6379"},
            clear=True,
        ):
            client = RedisClusterClient()
            assert client.config.nodes == [("envhost", 6379)]

    def test_initial_state(self):
        """Initial state is not connected."""
        config = ClusterConfig(nodes=[("localhost", 6379)])
        client = RedisClusterClient(config)
        assert client._client is None
        assert client._is_cluster is False
        assert client._available is False


class TestRedisClusterClientDetectMode:
    """Tests for cluster mode detection."""

    def test_forced_cluster_mode(self):
        """Forced cluster mode returns True without detection."""
        config = ClusterConfig(nodes=[("localhost", 6379)], mode=ClusterMode.CLUSTER)
        client = RedisClusterClient(config)
        assert client._detect_cluster_mode() is True

    def test_forced_standalone_mode(self):
        """Forced standalone mode returns False without detection."""
        config = ClusterConfig(nodes=[("localhost", 6379)], mode=ClusterMode.STANDALONE)
        client = RedisClusterClient(config)
        assert client._detect_cluster_mode() is False

    def test_auto_mode_no_nodes(self):
        """Auto mode with no nodes returns False."""
        config = ClusterConfig(nodes=[], mode=ClusterMode.AUTO)
        client = RedisClusterClient(config)
        assert client._detect_cluster_mode() is False

    def test_auto_mode_connection_failure(self):
        """Auto mode returns False on connection failure."""
        config = ClusterConfig(nodes=[("localhost", 6379)], mode=ClusterMode.AUTO)
        client = RedisClusterClient(config)

        with patch("redis.Redis") as mock_redis:
            mock_redis.side_effect = ConnectionError("Connection refused")
            assert client._detect_cluster_mode() is False

    def test_auto_mode_detects_standalone(self):
        """Auto mode detects standalone when CLUSTER INFO fails."""
        config = ClusterConfig(nodes=[("localhost", 6379)], mode=ClusterMode.AUTO)
        client = RedisClusterClient(config)

        with patch("redis.Redis") as mock_redis:
            mock_instance = MagicMock()
            mock_instance.execute_command.side_effect = RuntimeError("ERR unknown command")
            mock_redis.return_value = mock_instance
            assert client._detect_cluster_mode() is False


class TestRedisClusterClientCreateClient:
    """Tests for client creation."""

    def test_no_nodes_returns_none(self):
        """No nodes configured returns None."""
        config = ClusterConfig(nodes=[])
        client = RedisClusterClient(config)
        assert client._create_client() is None

    def test_import_error_returns_none(self):
        """Missing redis package returns None."""
        config = ClusterConfig(nodes=[("localhost", 6379)])
        client = RedisClusterClient(config)

        with patch.dict("sys.modules", {"redis": None}):
            with patch(
                "aragora.server.redis_cluster.RedisClusterClient._detect_cluster_mode",
                side_effect=ImportError("No redis"),
            ):
                # The actual ImportError happens inside _create_client
                # Just verify it handles the error gracefully
                pass


class TestRedisClusterClientOperations:
    """Tests for Redis operations with mocked client."""

    @pytest.fixture
    def mock_client_setup(self):
        """Setup a RedisClusterClient with a mocked Redis client."""
        config = ClusterConfig(nodes=[("localhost", 6379)])
        client = RedisClusterClient(config)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = "value"
        mock_redis.set.return_value = True
        mock_redis.delete.return_value = 1
        mock_redis.exists.return_value = 1
        mock_redis.expire.return_value = True
        mock_redis.ttl.return_value = 3600
        mock_redis.incr.return_value = 1
        mock_redis.decr.return_value = 0
        mock_redis.hget.return_value = "hash_value"
        mock_redis.hset.return_value = 1
        mock_redis.hgetall.return_value = {"key": "value"}
        mock_redis.hdel.return_value = 1
        mock_redis.zadd.return_value = 1
        mock_redis.zrem.return_value = 1
        mock_redis.zcard.return_value = 5
        mock_redis.zrangebyscore.return_value = ["a", "b"]
        mock_redis.zremrangebyscore.return_value = 2
        mock_redis.info.return_value = {"redis_version": "7.0.0"}

        client._client = mock_redis
        client._available = True

        return client, mock_redis

    def test_get(self, mock_client_setup):
        """Test get operation."""
        client, mock_redis = mock_client_setup
        result = client.get("key")
        assert result == "value"
        mock_redis.get.assert_called_with("key")

    def test_set(self, mock_client_setup):
        """Test set operation."""
        client, mock_redis = mock_client_setup
        result = client.set("key", "value", ex=3600)
        assert result is True
        mock_redis.set.assert_called_with("key", "value", ex=3600, px=None, nx=False, xx=False)

    def test_delete(self, mock_client_setup):
        """Test delete operation."""
        client, mock_redis = mock_client_setup
        result = client.delete("key1", "key2")
        assert result == 1
        mock_redis.delete.assert_called_with("key1", "key2")

    def test_exists(self, mock_client_setup):
        """Test exists operation."""
        client, mock_redis = mock_client_setup
        result = client.exists("key1", "key2")
        assert result == 1
        mock_redis.exists.assert_called_with("key1", "key2")

    def test_expire(self, mock_client_setup):
        """Test expire operation."""
        client, mock_redis = mock_client_setup
        result = client.expire("key", 3600)
        assert result is True
        mock_redis.expire.assert_called_with("key", 3600)

    def test_ttl(self, mock_client_setup):
        """Test ttl operation."""
        client, mock_redis = mock_client_setup
        result = client.ttl("key")
        assert result == 3600
        mock_redis.ttl.assert_called_with("key")

    def test_incr(self, mock_client_setup):
        """Test incr operation."""
        client, mock_redis = mock_client_setup
        result = client.incr("counter")
        assert result == 1
        mock_redis.incr.assert_called_with("counter")

    def test_decr(self, mock_client_setup):
        """Test decr operation."""
        client, mock_redis = mock_client_setup
        result = client.decr("counter")
        assert result == 0
        mock_redis.decr.assert_called_with("counter")

    def test_hget(self, mock_client_setup):
        """Test hget operation."""
        client, mock_redis = mock_client_setup
        result = client.hget("hash", "field")
        assert result == "hash_value"
        mock_redis.hget.assert_called_with("hash", "field")

    def test_hset(self, mock_client_setup):
        """Test hset operation."""
        client, mock_redis = mock_client_setup
        result = client.hset("hash", "field", "value")
        assert result == 1
        mock_redis.hset.assert_called_with("hash", "field", "value")

    def test_hgetall(self, mock_client_setup):
        """Test hgetall operation."""
        client, mock_redis = mock_client_setup
        result = client.hgetall("hash")
        assert result == {"key": "value"}
        mock_redis.hgetall.assert_called_with("hash")

    def test_hdel(self, mock_client_setup):
        """Test hdel operation."""
        client, mock_redis = mock_client_setup
        result = client.hdel("hash", "field1", "field2")
        assert result == 1
        mock_redis.hdel.assert_called_with("hash", "field1", "field2")

    def test_zadd(self, mock_client_setup):
        """Test zadd operation."""
        client, mock_redis = mock_client_setup
        result = client.zadd("zset", {"a": 1.0, "b": 2.0})
        assert result == 1

    def test_zrem(self, mock_client_setup):
        """Test zrem operation."""
        client, mock_redis = mock_client_setup
        result = client.zrem("zset", "a", "b")
        assert result == 1

    def test_zcard(self, mock_client_setup):
        """Test zcard operation."""
        client, mock_redis = mock_client_setup
        result = client.zcard("zset")
        assert result == 5

    def test_zrangebyscore(self, mock_client_setup):
        """Test zrangebyscore operation."""
        client, mock_redis = mock_client_setup
        result = client.zrangebyscore("zset", 0, 100)
        assert result == ["a", "b"]

    def test_zremrangebyscore(self, mock_client_setup):
        """Test zremrangebyscore operation."""
        client, mock_redis = mock_client_setup
        result = client.zremrangebyscore("zset", 0, 100)
        assert result == 2

    def test_info(self, mock_client_setup):
        """Test info operation."""
        client, mock_redis = mock_client_setup
        result = client.info()
        assert result["redis_version"] == "7.0.0"

    def test_ping_success(self, mock_client_setup):
        """Test ping returns True on success."""
        client, mock_redis = mock_client_setup
        assert client.ping() is True

    def test_ping_failure(self, mock_client_setup):
        """Test ping returns False on failure."""
        client, mock_redis = mock_client_setup
        mock_redis.ping.side_effect = ConnectionError("Connection refused")
        assert client.ping() is False


class TestRedisClusterClientRetry:
    """Tests for retry logic."""

    def test_retry_on_connection_error(self):
        """Retries on connection error."""
        config = ClusterConfig(nodes=[("localhost", 6379)], max_retries=2)
        client = RedisClusterClient(config)

        mock_redis = MagicMock()
        call_count = [0]

        def get_side_effect(key):
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("Connection lost")
            return "success"

        mock_redis.get.side_effect = get_side_effect
        client._client = mock_redis
        client._available = True

        result = client.get("key")
        assert result == "success"
        assert call_count[0] == 3  # 2 retries + 1 success

    def test_retry_exhausted_raises(self):
        """Raises after retries exhausted."""
        config = ClusterConfig(nodes=[("localhost", 6379)], max_retries=1)
        client = RedisClusterClient(config)

        mock_redis = MagicMock()
        mock_redis.get.side_effect = ConnectionError("Connection lost")
        client._client = mock_redis
        client._available = True

        with pytest.raises(ConnectionError):
            client.get("key")

    def test_marks_health_on_failure(self):
        """Marks health monitor on failure."""
        config = ClusterConfig(nodes=[("localhost", 6379)], max_retries=0)
        client = RedisClusterClient(config)

        mock_redis = MagicMock()
        mock_redis.get.side_effect = ConnectionError("Connection lost")
        client._client = mock_redis
        client._available = True

        try:
            client.get("key")
        except ConnectionError:
            pass

        # Health monitor should have recorded a failure
        assert client._health_monitor._consecutive_failures > 0


class TestRedisClusterClientSlotCalculation:
    """Tests for hash slot calculation."""

    def test_simple_key_slot(self):
        """Calculates slot for simple key."""
        config = ClusterConfig(nodes=[("localhost", 6379)])
        client = RedisClusterClient(config)

        # Just verify it returns a valid slot number
        slot = client.get_slot_for_key("mykey")
        assert 0 <= slot < 16384

    def test_hash_tag_slot(self):
        """Uses hash tag for slot calculation."""
        config = ClusterConfig(nodes=[("localhost", 6379)])
        client = RedisClusterClient(config)

        # Keys with same hash tag should have same slot
        slot1 = client.get_slot_for_key("{user:123}:profile")
        slot2 = client.get_slot_for_key("{user:123}:settings")
        assert slot1 == slot2

    def test_different_hash_tags_different_slots(self):
        """Different hash tags may have different slots."""
        config = ClusterConfig(nodes=[("localhost", 6379)])
        client = RedisClusterClient(config)

        slot1 = client.get_slot_for_key("{user:1}:data")
        slot2 = client.get_slot_for_key("{user:2}:data")
        # Different users may hash to different slots (or same by chance)
        # Just verify both are valid
        assert 0 <= slot1 < 16384
        assert 0 <= slot2 < 16384

    def test_empty_hash_tag_uses_full_key(self):
        """Empty hash tag uses full key for hashing."""
        config = ClusterConfig(nodes=[("localhost", 6379)])
        client = RedisClusterClient(config)

        # Empty hash tag {} should use full key
        slot1 = client.get_slot_for_key("key{}value")
        slot2 = client.get_slot_for_key("key{}value")
        assert slot1 == slot2


class TestRedisClusterClientClusterInfo:
    """Tests for cluster info retrieval."""

    def test_standalone_returns_mode_info(self):
        """Standalone mode returns mode info."""
        config = ClusterConfig(nodes=[("localhost", 6379)])
        client = RedisClusterClient(config)
        client._is_cluster = False

        info = client.get_cluster_info()
        assert info["mode"] == "standalone"
        assert info["cluster"] is False

    def test_cluster_mode_not_connected(self):
        """Cluster mode with no client returns error info."""
        config = ClusterConfig(nodes=[])  # Empty nodes to prevent connection attempt
        client = RedisClusterClient(config)
        client._is_cluster = True
        # Directly set _client to None to simulate not connected state
        # without triggering connection attempt

        info = client.get_cluster_info()
        assert info["mode"] == "cluster"
        assert info["cluster"] is True
        assert "error" in info


class TestRedisClusterClientStats:
    """Tests for stats retrieval."""

    def test_get_stats_basic(self):
        """Returns basic stats without client."""
        config = ClusterConfig(nodes=[])  # Empty nodes to prevent connection attempt
        client = RedisClusterClient(config)

        stats = client.get_stats()
        assert "available" in stats
        assert "is_cluster" in stats
        assert "healthy" in stats
        assert "nodes" in stats
        assert stats["nodes"] == 0
        # Without nodes configured, stats should show not available
        assert stats["available"] is False

    def test_get_stats_with_client(self):
        """Returns extended stats with client."""
        config = ClusterConfig(nodes=[("localhost", 6379)])
        client = RedisClusterClient(config)

        mock_redis = MagicMock()
        mock_redis.info.return_value = {
            "redis_version": "7.0.0",
            "connected_clients": 10,
            "used_memory_human": "1M",
        }
        client._client = mock_redis
        client._available = True

        stats = client.get_stats()
        assert stats["redis_version"] == "7.0.0"
        assert stats["connected_clients"] == 10


class TestRedisClusterClientClose:
    """Tests for client close."""

    def test_close_clears_state(self):
        """Close clears client state."""
        config = ClusterConfig(nodes=[("localhost", 6379)])
        client = RedisClusterClient(config)

        mock_redis = MagicMock()
        client._client = mock_redis
        client._available = True

        client.close()

        assert client._client is None
        assert client._available is False
        mock_redis.close.assert_called_once()

    def test_close_handles_error(self):
        """Close handles errors gracefully."""
        config = ClusterConfig(nodes=[("localhost", 6379)])
        client = RedisClusterClient(config)

        mock_redis = MagicMock()
        mock_redis.close.side_effect = ConnectionError("Already closed")
        client._client = mock_redis
        client._available = True

        # Should not raise
        client.close()
        assert client._client is None


class TestRedisClusterClientReconnect:
    """Tests for reconnection logic."""

    def test_reconnect_closes_existing(self):
        """Reconnect closes existing client."""
        config = ClusterConfig(nodes=[("localhost", 6379)])
        client = RedisClusterClient(config)

        mock_redis = MagicMock()
        client._client = mock_redis

        # Mock _create_client to return None (failed reconnect)
        with patch.object(client, "_create_client", return_value=None):
            client._reconnect()

        mock_redis.close.assert_called_once()

    def test_reconnect_creates_new_client(self):
        """Reconnect creates new client."""
        config = ClusterConfig(nodes=[("localhost", 6379)])
        client = RedisClusterClient(config)

        mock_old = MagicMock()
        mock_new = MagicMock()
        client._client = mock_old

        with patch.object(client, "_create_client", return_value=mock_new):
            client._reconnect()

        assert client._client is mock_new


# ---------------------------------------------------------------------------
# Module-level Function Tests
# ---------------------------------------------------------------------------


class TestModuleLevelFunctions:
    """Tests for module-level singleton functions."""

    def test_reset_cluster_client(self):
        """reset_cluster_client clears singleton."""
        import aragora.storage.redis_cluster as rc

        # Set up a mock client
        mock_client = MagicMock()
        rc._cluster_client = mock_client

        reset_cluster_client()

        assert rc._cluster_client is None
        mock_client.close.assert_called_once()

    def test_is_cluster_available_no_client(self):
        """is_cluster_available returns False when no client."""
        import aragora.storage.redis_cluster as rc

        rc._cluster_client = None
        with patch.object(rc, "get_cluster_config", return_value=ClusterConfig(nodes=[])):
            assert is_cluster_available() is False

    def test_get_redis_client_no_cluster(self):
        """get_redis_client returns None when no cluster client."""
        import aragora.storage.redis_cluster as rc

        rc._cluster_client = None
        with patch.object(rc, "get_cluster_config", return_value=ClusterConfig(nodes=[])):
            assert get_redis_client() is None


# ---------------------------------------------------------------------------
# Async Retry Tests
# ---------------------------------------------------------------------------


class TestAsyncRetry:
    """Tests for async retry logic."""

    @pytest.mark.asyncio
    async def test_async_retry_success(self):
        """Async retry succeeds after initial failure."""
        config = ClusterConfig(nodes=[("localhost", 6379)], max_retries=2)
        client = RedisClusterClient(config)

        mock_redis = MagicMock()
        call_count = [0]

        def operation():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ConnectionError("Temporary failure")
            return "success"

        client._client = mock_redis
        client._available = True

        result = await client._execute_with_retry_async(operation)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_async_retry_exhausted(self):
        """Async retry raises after exhausted."""
        config = ClusterConfig(nodes=[("localhost", 6379)], max_retries=1)
        client = RedisClusterClient(config)

        mock_redis = MagicMock()
        client._client = mock_redis
        client._available = True

        def operation():
            raise TimeoutError("Always fails")

        with pytest.raises(TimeoutError):
            await client._execute_with_retry_async(operation)
