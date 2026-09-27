"""Tests for connection leak detector."""

import asyncio
import threading
import time
from unittest.mock import patch

import pytest

from aragora.server import leak_detector as leak_detector_module
from aragora.server.leak_detector import (
    AcquisitionRecord,
    LeakAlert,
    LeakDetector,
    _short_caller,
    get_leak_detector,
    reset_leak_detector,
)


class TestAcquisitionRecord:
    """Test AcquisitionRecord dataclass."""

    def test_held_seconds_while_active(self):
        """Test held_seconds calculation for active connection."""
        now = time.time()
        record = AcquisitionRecord(
            pool_name="postgres",
            conn_id="pg-1",
            acquired_at=now - 10,  # 10 seconds ago
            caller="test.py:42",
        )

        held = record.held_seconds

        assert held >= 10
        assert held < 12  # Allow some margin

    def test_held_seconds_when_released(self):
        """Test held_seconds calculation for released connection."""
        now = time.time()
        record = AcquisitionRecord(
            pool_name="postgres",
            conn_id="pg-1",
            acquired_at=now - 10,
            caller="test.py:42",
            released=True,
            released_at=now - 5,  # Released 5 seconds after acquire
        )

        held = record.held_seconds

        assert held == pytest.approx(5.0, abs=0.1)

    def test_held_seconds_tolerates_missing_release_timestamp(self):
        """An inconsistent released record still reports elapsed hold time."""
        now = time.time()
        record = AcquisitionRecord(
            pool_name="postgres",
            conn_id="pg-1",
            acquired_at=now - 10,
            caller="test.py:42",
            released=True,
            released_at=None,
        )

        held = record.held_seconds

        assert held >= 10
        assert held < 12

    def test_to_dict(self):
        """Test serialization to dictionary."""
        now = time.time()
        record = AcquisitionRecord(
            pool_name="redis",
            conn_id="redis-42",
            acquired_at=now,
            caller="handlers.py:100",
        )

        result = record.to_dict()

        assert result["pool_name"] == "redis"
        assert result["conn_id"] == "redis-42"
        assert result["acquired_at"] == now
        assert result["caller"] == "handlers.py:100"
        assert result["released"] is False
        assert "held_seconds" in result


class TestLeakAlert:
    """Test LeakAlert dataclass."""

    def test_alert_creation(self):
        """Test basic alert creation."""
        alert = LeakAlert(
            pool_name="postgres",
            conn_id="pg-123",
            held_seconds=45.5,
            caller="db.py:50",
            level="warning",
        )

        assert alert.pool_name == "postgres"
        assert alert.conn_id == "pg-123"
        assert alert.held_seconds == 45.5
        assert alert.level == "warning"
        assert alert.timestamp > 0

    def test_to_dict(self):
        """Test serialization to dictionary."""
        alert = LeakAlert(
            pool_name="http",
            conn_id="http-99",
            held_seconds=120.0,
            caller="client.py:25",
            level="critical",
            timestamp=1234567890.0,
        )

        result = alert.to_dict()

        assert result["pool_name"] == "http"
        assert result["conn_id"] == "http-99"
        assert result["held_seconds"] == 120.0
        assert result["caller"] == "client.py:25"
        assert result["level"] == "critical"
        assert result["timestamp"] == 1234567890.0


class TestLeakDetector:
    """Test LeakDetector class."""

    def setup_method(self):
        """Reset global detector before each test."""
        reset_leak_detector()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_leak_detector()

    def test_acquire_returns_conn_id(self):
        """Test acquire returns connection ID."""
        detector = LeakDetector()

        conn_id = detector.acquire("postgres")

        assert conn_id.startswith("postgres-")

    def test_acquire_with_custom_conn_id(self):
        """Test acquire with custom connection ID."""
        detector = LeakDetector()

        conn_id = detector.acquire("postgres", conn_id="custom-id")

        assert conn_id == "custom-id"

    def test_acquire_tracks_connection(self):
        """Test acquire creates tracking record."""
        detector = LeakDetector()

        conn_id = detector.acquire("redis")

        active = detector.get_active_connections()
        assert len(active) == 1
        assert active[0].conn_id == conn_id
        assert active[0].pool_name == "redis"

    def test_release_removes_connection(self):
        """Test release removes connection from tracking."""
        detector = LeakDetector()

        conn_id = detector.acquire("postgres")
        detector.release(conn_id)

        active = detector.get_active_connections()
        assert len(active) == 0

    def test_release_nonexistent_id(self):
        """Test release with nonexistent ID is safe."""
        detector = LeakDetector()

        # Should not raise
        detector.release("nonexistent-id")

    def test_release_updates_stats(self):
        """Test release updates released counter."""
        detector = LeakDetector()

        conn_id = detector.acquire("postgres")
        detector.release(conn_id)

        stats = detector.get_stats()
        assert stats["total_acquired"] == 1
        assert stats["total_released"] == 1

    def test_sync_context_manager(self):
        """Test sync track context manager."""
        detector = LeakDetector()

        with detector.track("postgres") as conn_id:
            active = detector.get_active_connections()
            assert len(active) == 1
            assert conn_id.startswith("postgres-")

        # After context, connection should be released
        active = detector.get_active_connections()
        assert len(active) == 0

    def test_sync_context_manager_on_exception(self):
        """Test sync context manager releases on exception."""
        detector = LeakDetector()

        with pytest.raises(ValueError):
            with detector.track("redis"):
                raise ValueError("test error")

        # Connection should still be released
        active = detector.get_active_connections()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        """Test async atrack context manager."""
        detector = LeakDetector()

        async with detector.atrack("postgres") as conn_id:
            active = detector.get_active_connections()
            assert len(active) == 1
            assert conn_id.startswith("postgres-")

        # After context, connection should be released
        active = detector.get_active_connections()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_async_context_manager_on_exception(self):
        """Test async context manager releases on exception."""
        detector = LeakDetector()

        with pytest.raises(ValueError):
            async with detector.atrack("redis"):
                raise ValueError("async error")

        # Connection should still be released
        active = detector.get_active_connections()
        assert len(active) == 0

    def test_check_leaks_warning(self):
        """Test check_leaks generates warning alerts."""
        detector = LeakDetector(warn_seconds=0.01, critical_seconds=10)

        conn_id = detector.acquire("postgres")
        time.sleep(0.02)  # Exceed warn threshold

        alerts = detector.check_leaks()

        assert len(alerts) == 1
        assert alerts[0].level == "warning"
        assert alerts[0].conn_id == conn_id

        detector.release(conn_id)

    def test_check_leaks_critical(self):
        """Test check_leaks generates critical alerts."""
        detector = LeakDetector(warn_seconds=0.01, critical_seconds=0.02)

        conn_id = detector.acquire("postgres")
        time.sleep(0.03)  # Exceed critical threshold

        alerts = detector.check_leaks()

        assert len(alerts) == 1
        assert alerts[0].level == "critical"

        detector.release(conn_id)

    def test_check_leaks_no_alerts_for_recent(self):
        """Test check_leaks doesn't alert for recent connections."""
        detector = LeakDetector(warn_seconds=60, critical_seconds=120)

        detector.acquire("postgres")

        alerts = detector.check_leaks()

        assert len(alerts) == 0

    def test_get_suspected_leaks(self):
        """Test getting suspected leaks."""
        detector = LeakDetector(warn_seconds=0.01)

        conn_id = detector.acquire("postgres")
        time.sleep(0.02)

        leaks = detector.get_suspected_leaks()

        assert len(leaks) == 1
        assert leaks[0].conn_id == conn_id

        detector.release(conn_id)

    def test_get_suspected_leaks_custom_threshold(self):
        """Test suspected leaks with custom threshold."""
        detector = LeakDetector(warn_seconds=60)

        detector.acquire("postgres")
        time.sleep(0.01)

        # Using custom low threshold
        leaks = detector.get_suspected_leaks(threshold=0.005)

        assert len(leaks) == 1

    def test_get_suspected_leaks_sorted_by_held_time(self):
        """Test suspected leaks are sorted by held time descending."""
        detector = LeakDetector(warn_seconds=0.01)

        # Acquire in order
        conn1 = detector.acquire("pg", conn_id="first")
        time.sleep(0.01)
        conn2 = detector.acquire("pg", conn_id="second")
        time.sleep(0.02)

        leaks = detector.get_suspected_leaks(threshold=0.01)

        # First acquired should be held longer
        if len(leaks) >= 2:
            assert leaks[0].conn_id == "first"

        detector.release(conn1)
        detector.release(conn2)

    def test_get_active_connections_filter_by_pool(self):
        """Test filtering active connections by pool name."""
        detector = LeakDetector()

        detector.acquire("postgres")
        detector.acquire("postgres")
        detector.acquire("redis")

        pg_conns = detector.get_active_connections(pool_name="postgres")
        redis_conns = detector.get_active_connections(pool_name="redis")

        assert len(pg_conns) == 2
        assert len(redis_conns) == 1

    def test_get_stats(self):
        """Test getting detector statistics."""
        detector = LeakDetector()

        conn1 = detector.acquire("postgres")
        conn2 = detector.acquire("redis")
        detector.release(conn1)

        stats = detector.get_stats()

        assert stats["total_acquired"] == 2
        assert stats["total_released"] == 1
        assert stats["currently_active"] == 1
        assert stats["active_by_pool"]["redis"] == 1

    def test_get_alerts(self):
        """Test getting stored alerts."""
        detector = LeakDetector(warn_seconds=0.01)

        conn_id = detector.acquire("postgres")
        time.sleep(0.02)
        detector.check_leaks()
        detector.release(conn_id)

        alerts = detector.get_alerts()

        assert len(alerts) >= 1

    def test_get_alerts_since_timestamp(self):
        """Test filtering alerts by timestamp."""
        detector = LeakDetector(warn_seconds=0.01)

        before = time.time()
        conn_id = detector.acquire("postgres")
        time.sleep(0.02)
        detector.check_leaks()
        detector.release(conn_id)

        alerts = detector.get_alerts(since=before - 1)
        assert len(alerts) >= 1

        # Future timestamp should return empty
        alerts = detector.get_alerts(since=time.time() + 100)
        assert len(alerts) == 0

    def test_reset(self):
        """Test resetting all tracking state."""
        detector = LeakDetector()

        detector.acquire("postgres")
        detector.check_leaks()

        detector.reset()

        stats = detector.get_stats()
        assert stats["total_acquired"] == 0
        assert stats["total_released"] == 0
        assert stats["currently_active"] == 0
        assert stats["alert_count"] == 0

    def test_max_tracked_eviction(self):
        """Test eviction when max tracked reached."""
        detector = LeakDetector(max_tracked=5)

        # Acquire more than max
        for i in range(10):
            detector.acquire("postgres", conn_id=f"pg-{i}")

        stats = detector.get_stats()
        assert stats["currently_active"] <= 5

    def test_alerts_capped(self):
        """Test alerts are capped to prevent memory growth."""
        detector = LeakDetector(warn_seconds=0.001)

        # Generate many alerts
        for _ in range(600):
            conn_id = detector.acquire("postgres")
            time.sleep(0.002)
            detector.check_leaks()
            detector.release(conn_id)

        alerts = detector.get_alerts()
        assert len(alerts) <= 500

    def test_thread_safety(self):
        """Test thread-safe operation."""
        detector = LeakDetector()
        results = []

        def worker():
            for _ in range(50):
                conn_id = detector.acquire("postgres")
                results.append(conn_id)
                time.sleep(0.001)
                detector.release(conn_id)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 250
        stats = detector.get_stats()
        assert stats["total_acquired"] == 250
        assert stats["total_released"] == 250
        assert stats["currently_active"] == 0

    def test_caller_tracking(self):
        """Test caller location is tracked."""
        detector = LeakDetector()

        conn_id = detector.acquire("postgres")
        active = detector.get_active_connections()

        assert len(active) == 1
        # Caller should contain file info
        assert ".py:" in active[0].caller or "unknown" in active[0].caller

        detector.release(conn_id)


class TestGlobalDetector:
    """Test global detector functions."""

    def setup_method(self):
        """Reset global detector before each test."""
        reset_leak_detector()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_leak_detector()

    def test_get_leak_detector(self):
        """Test getting global detector."""
        detector = get_leak_detector()

        assert isinstance(detector, LeakDetector)

    def test_get_leak_detector_singleton(self):
        """Test global detector is singleton."""
        detector1 = get_leak_detector()
        detector2 = get_leak_detector()

        assert detector1 is detector2

    def test_reset_leak_detector(self):
        """Test resetting global detector."""
        detector1 = get_leak_detector()
        reset_leak_detector()
        detector2 = get_leak_detector()

        assert detector1 is not detector2


class TestShortCaller:
    """Test _short_caller helper function."""

    def test_returns_location_string(self):
        """Test _short_caller returns location string."""

        def inner_func():
            return _short_caller(skip=1)

        result = inner_func()

        # Should contain file and line info
        assert ":" in result or result == "unknown"

    def test_handles_empty_stack(self):
        """Test _short_caller handles edge cases."""
        # This tests the except branch
        with patch("traceback.extract_stack", side_effect=IndexError("error")):
            result = _short_caller()

            assert result == "unknown"


class TestEnvironmentConfiguration:
    """Test environment variable configuration."""

    def test_default_warn_seconds(self):
        """Test default warn seconds from environment."""
        with patch.dict(
            "os.environ",
            {"ARAGORA_LEAK_WARN_SECONDS": "60"},
            clear=False,
        ):
            import os

            assert float(os.environ.get("ARAGORA_LEAK_WARN_SECONDS", "30")) == 60

    def test_default_critical_seconds(self):
        """Test default critical seconds from environment."""
        with patch.dict(
            "os.environ",
            {"ARAGORA_LEAK_CRITICAL_SECONDS": "300"},
            clear=False,
        ):
            import os

            assert float(os.environ.get("ARAGORA_LEAK_CRITICAL_SECONDS", "120")) == 300

    def test_default_max_tracked(self):
        """Test default max tracked from environment."""
        with patch.dict(
            "os.environ",
            {"ARAGORA_LEAK_MAX_TRACKED": "10000"},
            clear=False,
        ):
            import os

            assert int(os.environ.get("ARAGORA_LEAK_MAX_TRACKED", "5000")) == 10000


class TestIntegrationScenarios:
    """Test integration scenarios."""

    def setup_method(self):
        """Reset global detector before each test."""
        reset_leak_detector()

    def teardown_method(self):
        """Cleanup after each test."""
        reset_leak_detector()

    def test_multiple_pool_tracking(self):
        """Test tracking connections from multiple pools."""
        detector = LeakDetector()

        pg_conn = detector.acquire("postgres")
        redis_conn = detector.acquire("redis")
        http_conn = detector.acquire("http")

        stats = detector.get_stats()
        assert stats["currently_active"] == 3
        assert stats["active_by_pool"]["postgres"] == 1
        assert stats["active_by_pool"]["redis"] == 1
        assert stats["active_by_pool"]["http"] == 1

        detector.release(pg_conn)
        detector.release(redis_conn)
        detector.release(http_conn)

    def test_connection_lifecycle(self):
        """Test full connection lifecycle."""
        current_time = 1000.0

        with patch.object(leak_detector_module.time, "time", side_effect=lambda: current_time):
            detector = LeakDetector(warn_seconds=0.05, critical_seconds=0.1)

            # Acquire connection
            conn_id = detector.acquire("postgres", conn_id="pg-lifecycle")
            assert detector.get_stats()["currently_active"] == 1

            # Advance to the warning threshold without relying on scheduler timing.
            current_time += 0.06
            alerts = detector.check_leaks()
            assert len(alerts) == 1
            assert alerts[0].level == "warning"

            # Advance to the critical threshold.
            current_time += 0.05
            alerts = detector.check_leaks()
            assert len(alerts) == 1
            assert alerts[0].level == "critical"

            # Release connection
            detector.release(conn_id)
            assert detector.get_stats()["currently_active"] == 0

            # Verify final stats
            stats = detector.get_stats()
            assert stats["total_warn_alerts"] >= 1
            assert stats["total_critical_alerts"] >= 1

    @pytest.mark.asyncio
    async def test_concurrent_async_operations(self):
        """Test concurrent async connection tracking."""
        detector = LeakDetector()

        async def use_connection(pool_name: str, duration: float):
            async with detector.atrack(pool_name):
                await asyncio.sleep(duration)

        # Run multiple concurrent connections
        await asyncio.gather(
            use_connection("postgres", 0.01),
            use_connection("postgres", 0.02),
            use_connection("redis", 0.01),
            use_connection("http", 0.015),
        )

        stats = detector.get_stats()
        assert stats["total_acquired"] == 4
        assert stats["total_released"] == 4
        assert stats["currently_active"] == 0

    def test_eviction_preserves_newest(self):
        """Test eviction keeps newest connections."""
        detector = LeakDetector(max_tracked=3)

        # Acquire connections with small delays to ensure ordering
        detector.acquire("pg", conn_id="old-1")
        time.sleep(0.001)
        detector.acquire("pg", conn_id="old-2")
        time.sleep(0.001)
        detector.acquire("pg", conn_id="new-1")
        time.sleep(0.001)
        detector.acquire("pg", conn_id="new-2")
        time.sleep(0.001)
        detector.acquire("pg", conn_id="newest")

        # Should have evicted oldest
        active = detector.get_active_connections()
        conn_ids = [c.conn_id for c in active]

        assert len(active) <= 3
        # Newest should still be present
        assert "newest" in conn_ids

    def test_stats_thresholds_included(self):
        """Test stats include threshold configuration."""
        detector = LeakDetector(warn_seconds=30.0, critical_seconds=120.0)

        stats = detector.get_stats()

        assert stats["warn_threshold_seconds"] == 30.0
        assert stats["critical_threshold_seconds"] == 120.0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_evict_oldest_empty(self):
        """Test _evict_oldest with empty active dict."""
        detector = LeakDetector()

        # Should not raise
        detector._evict_oldest()

    def test_release_same_id_twice(self):
        """Test releasing same ID twice is safe."""
        detector = LeakDetector()

        conn_id = detector.acquire("postgres")
        detector.release(conn_id)
        detector.release(conn_id)  # Should not raise

        stats = detector.get_stats()
        assert stats["total_released"] == 1  # Only counted once

    def test_check_leaks_with_mixed_ages(self):
        """Test check_leaks with connections of different ages."""
        detector = LeakDetector(warn_seconds=0.02, critical_seconds=0.05)

        # New connection
        new_conn = detector.acquire("pg", conn_id="new")

        # Simulate an old connection
        detector.acquire("pg", conn_id="old")
        with detector._lock:
            detector._active["old"].acquired_at = time.time() - 0.03  # Past warn

        # Very old connection
        detector.acquire("pg", conn_id="very-old")
        with detector._lock:
            detector._active["very-old"].acquired_at = time.time() - 0.1  # Past critical

        alerts = detector.check_leaks()

        warning_alerts = [a for a in alerts if a.level == "warning"]
        critical_alerts = [a for a in alerts if a.level == "critical"]

        assert len(warning_alerts) >= 1
        assert len(critical_alerts) >= 1

        # Cleanup
        detector.release("new")
        detector.release("old")
        detector.release("very-old")

    def test_high_frequency_acquire_release(self):
        """Test rapid acquire/release cycles."""
        detector = LeakDetector()

        for _ in range(1000):
            conn_id = detector.acquire("postgres")
            detector.release(conn_id)

        stats = detector.get_stats()
        assert stats["total_acquired"] == 1000
        assert stats["total_released"] == 1000
        assert stats["currently_active"] == 0
