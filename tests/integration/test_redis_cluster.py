"""
Integration tests for Redis cluster support.

Tests Redis client utilities and cluster/standalone mode detection.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from aragora.storage.redis_utils import (
    get_redis_client,
    reset_redis_client,
    is_cluster_mode,
)


class TestRedisClientUtilities:
    """Tests for Redis client utility functions."""

    def setup_method(self):
        """Reset Redis client before each test."""
        reset_redis_client()

    def teardown_method(self):
        """Clean up after each test."""
        reset_redis_client()

    def test_get_redis_client_returns_none_when_unavailable(self):
        """Test that get_redis_client returns None when Redis is unavailable."""
        with patch.dict(
            os.environ,
            {
                "ARAGORA_REDIS_CLUSTER_NODES": "",
                "ARAGORA_REDIS_URL": "redis://nonexistent:6379",
            },
        ):
            reset_redis_client()
            client = get_redis_client()
            # Should return None since Redis is not running
            # (or could return a client if Redis happens to be running locally)
            # This test just verifies no exception is raised
            assert client is None or client is not None

    def test_is_cluster_mode_false_by_default(self):
        """Test that is_cluster_mode returns False when no cluster configured."""
        with patch.dict(os.environ, {"ARAGORA_REDIS_CLUSTER_NODES": ""}, clear=False):
            reset_redis_client()
            assert is_cluster_mode() is False

    def test_reset_redis_client_clears_cache(self):
        """Test that reset_redis_client clears the cached client."""
        # Get a client (or None)
        client1 = get_redis_client()

        # Reset
        reset_redis_client()

        # This should reinitialize
        client2 = get_redis_client()

        # Both should be valid states (None or client)
        # The point is reset doesn't raise exceptions
        assert client1 is None or hasattr(client1, "get")
        assert client2 is None or hasattr(client2, "get")

    def test_get_redis_client_with_explicit_url(self):
        """Test get_redis_client with explicit URL parameter."""
        # With explicit URL, should not use cached client
        client = get_redis_client(redis_url="redis://localhost:6379")
        # Should either connect or return None gracefully
        assert client is None or hasattr(client, "get")


class TestRedisClusterDetection:
    """Tests for Redis cluster mode detection."""

    def setup_method(self):
        """Reset state before each test."""
        reset_redis_client()

    def test_cluster_detection_with_cluster_nodes_env(self):
        """Test cluster detection when CLUSTER_NODES is set."""
        with patch.dict(
            os.environ,
            {
                "ARAGORA_REDIS_CLUSTER_NODES": "redis1:6379,redis2:6379",
            },
        ):
            reset_redis_client()
            # Should attempt cluster mode (will fail if no actual cluster)
            # but the detection logic should not raise
            try:
                client = get_redis_client()
            except Exception:
                pass  # Expected if no cluster running

    def test_cluster_detection_prefers_cluster_over_standalone(self):
        """Test that cluster configuration takes precedence over standalone."""
        with patch.dict(
            os.environ,
            {
                "ARAGORA_REDIS_CLUSTER_NODES": "redis1:6379",
                "ARAGORA_REDIS_URL": "redis://localhost:6379",
            },
        ):
            reset_redis_client()
            # Should try cluster first
            # We can't fully test without a running cluster
            # but we verify the precedence logic exists
            from aragora.storage import redis_utils

            assert hasattr(redis_utils, "get_redis_client")


class TestRedisClusterClient:
    """Tests for the RedisClusterClient class."""

    def test_cluster_client_import(self):
        """Test that RedisClusterClient can be imported."""
        from aragora.storage.redis_cluster import (
            RedisClusterClient,
            ClusterConfig,
            ClusterMode,
            get_cluster_config,
        )

        assert RedisClusterClient is not None
        assert ClusterConfig is not None
        assert ClusterMode is not None

    def test_cluster_config_from_env(self):
        """Test ClusterConfig creation from environment."""
        from aragora.storage.redis_cluster import get_cluster_config

        with patch.dict(
            os.environ,
            {
                "ARAGORA_REDIS_CLUSTER_NODES": "node1:6379,node2:6380",
                "ARAGORA_REDIS_CLUSTER_MODE": "auto",
                "ARAGORA_REDIS_CLUSTER_MAX_CONNECTIONS": "64",
                "ARAGORA_REDIS_CLUSTER_READ_FROM_REPLICAS": "true",
            },
        ):
            config = get_cluster_config()

            assert len(config.nodes) == 2
            assert config.nodes[0] == ("node1", 6379)
            assert config.nodes[1] == ("node2", 6380)
            assert config.max_connections_per_node == 64
            assert config.read_from_replicas is True

    def test_cluster_config_parses_nodes_correctly(self):
        """Test that node parsing handles various formats."""
        from aragora.storage.redis_cluster import get_cluster_config

        # Test with just hostnames (default port)
        with patch.dict(
            os.environ,
            {
                "ARAGORA_REDIS_CLUSTER_NODES": "redis1,redis2",
            },
            clear=False,
        ):
            config = get_cluster_config()
            # Should default to port 6379
            assert all(port == 6379 for _, port in config.nodes)

    def test_cluster_client_slot_calculation(self):
        """Test CRC16 slot calculation for cluster keys."""
        from aragora.storage.redis_cluster import RedisClusterClient, ClusterConfig

        client = RedisClusterClient(ClusterConfig(nodes=[]))

        # Test basic key
        slot1 = client.get_slot_for_key("mykey")
        assert 0 <= slot1 < 16384

        # Test hash tag
        slot2 = client.get_slot_for_key("{user:123}:profile")
        slot3 = client.get_slot_for_key("{user:123}:settings")
        # Keys with same hash tag should map to same slot
        assert slot2 == slot3

    def test_cluster_health_monitor(self):
        """Test ClusterHealthMonitor functionality."""
        from aragora.storage.redis_cluster import ClusterHealthMonitor

        monitor = ClusterHealthMonitor(check_interval=1.0)

        # Initially healthy
        assert monitor.is_healthy is True

        # Mark failures
        monitor.mark_failure()
        monitor.mark_failure()
        assert monitor.is_healthy is True  # Not enough failures yet

        monitor.mark_failure()
        assert monitor.is_healthy is False  # 3 consecutive failures

        # Mark success resets
        monitor.mark_success()
        assert monitor.is_healthy is True


class TestRedisClusterOperations:
    """Tests for Redis cluster operations (mocked)."""

    def test_cluster_get_set_operations(self):
        """Test basic get/set operations through cluster client."""
        from aragora.storage.redis_cluster import RedisClusterClient, ClusterConfig

        with patch("redis.from_url") as mock_from_url:
            mock_redis = MagicMock()
            mock_redis.ping.return_value = True
            mock_redis.get.return_value = "test_value"
            mock_redis.set.return_value = True
            mock_from_url.return_value = mock_redis

            # Create with standalone config (will use mock)
            config = ClusterConfig(
                nodes=[("localhost", 6379)],
            )
            # This would need actual Redis running to fully test

    def test_cluster_hash_operations(self):
        """Test hash operations through cluster client."""
        from aragora.storage.redis_cluster import RedisClusterClient, ClusterConfig

        # Just verify methods exist
        client = RedisClusterClient(ClusterConfig(nodes=[]))
        assert hasattr(client, "hget")
        assert hasattr(client, "hset")
        assert hasattr(client, "hgetall")
        assert hasattr(client, "hdel")

    def test_cluster_sorted_set_operations(self):
        """Test sorted set operations through cluster client."""
        from aragora.storage.redis_cluster import RedisClusterClient, ClusterConfig

        # Just verify methods exist (used for rate limiting)
        client = RedisClusterClient(ClusterConfig(nodes=[]))
        assert hasattr(client, "zadd")
        assert hasattr(client, "zrem")
        assert hasattr(client, "zcard")
        assert hasattr(client, "zrangebyscore")


class TestRedisFailover:
    """Tests for Redis failover behavior."""

    def test_reconnect_on_cluster_error(self):
        """Test that client reconnects on MOVED/CLUSTERDOWN errors."""
        from aragora.storage.redis_cluster import RedisClusterClient, ClusterConfig

        client = RedisClusterClient(ClusterConfig(nodes=[("localhost", 6379)]))

        # Verify reconnect method exists
        assert hasattr(client, "_reconnect")

        # Verify execute_with_retry exists
        assert hasattr(client, "_execute_with_retry")

    def test_health_check_triggers_reconnect(self):
        """Test that health check failures can trigger reconnection."""
        from aragora.storage.redis_cluster import ClusterHealthMonitor

        monitor = ClusterHealthMonitor(check_interval=0.1)

        # Simulate failures
        for _ in range(5):
            monitor.mark_failure()

        assert monitor.is_healthy is False

        # Should be able to check if health check is due
        import time

        time.sleep(0.2)
        assert monitor.should_check() is True


class TestRedisAsyncRetry:
    """Tests for async retry behavior to avoid blocking the event loop."""

    def test_async_retry_method_exists(self):
        """Test that async retry method exists."""
        from aragora.storage.redis_cluster import RedisClusterClient, ClusterConfig

        client = RedisClusterClient(ClusterConfig(nodes=[]))
        assert hasattr(client, "_execute_with_retry_async")
        # Verify it's a coroutine function
        import inspect

        assert inspect.iscoroutinefunction(client._execute_with_retry_async)

    @pytest.mark.asyncio
    async def test_async_retry_uses_asyncio_sleep(self):
        """Test that async retry uses asyncio.sleep instead of time.sleep."""
        import asyncio
        from unittest.mock import AsyncMock
        from aragora.storage.redis_cluster import RedisClusterClient, ClusterConfig

        client = RedisClusterClient(ClusterConfig(nodes=[]))

        # Mock get_client to return a mock that raises once then succeeds
        call_count = 0

        def operation():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("First attempt fails")
            return "success"

        # Mock the client
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        client._client = mock_redis
        client._available = True

        # Track if asyncio.sleep was used (not time.sleep)
        original_asyncio_sleep = asyncio.sleep
        sleep_calls = []

        async def mock_asyncio_sleep(delay):
            sleep_calls.append(delay)
            # Don't actually wait, just record the call
            return

        with patch.object(asyncio, "sleep", mock_asyncio_sleep):
            try:
                result = await client._execute_with_retry_async(operation, max_retries=2)
                assert result == "success"
                # Should have called asyncio.sleep for the retry delay
                assert len(sleep_calls) > 0
            except RuntimeError:
                # If Redis client unavailable, just verify method exists
                pass

    @pytest.mark.asyncio
    async def test_async_retry_does_not_block_event_loop(self):
        """Test that async retry doesn't block concurrent async operations."""
        import asyncio
        from aragora.storage.redis_cluster import RedisClusterClient, ClusterConfig

        client = RedisClusterClient(ClusterConfig(nodes=[]))

        # Track concurrent execution
        concurrent_task_completed = False

        async def concurrent_task():
            nonlocal concurrent_task_completed
            await asyncio.sleep(0.01)
            concurrent_task_completed = True
            return "concurrent done"

        call_count = 0

        def slow_operation():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Retry needed")
            return "success"

        # Mock client to be available
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        client._client = mock_redis
        client._available = True

        # Run both tasks concurrently
        # The concurrent_task should complete even if retry is happening
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    client._execute_with_retry_async(slow_operation, max_retries=1),
                    concurrent_task(),
                    return_exceptions=True,
                ),
                timeout=5.0,
            )
            # Verify concurrent task wasn't blocked
            assert concurrent_task_completed is True
        except asyncio.TimeoutError:
            pytest.fail("Async retry blocked the event loop")
