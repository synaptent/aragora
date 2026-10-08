"""
Tests for KM Health Metrics and Observability.
"""

import time
from unittest.mock import patch

import pytest

from aragora.knowledge.mound.metrics import (
    KMMetrics,
    OperationType,
    OperationStats,
    HealthStatus,
    HealthReport,
    get_prometheus_health_status,
    get_metrics,
    set_metrics,
)


class TestOperationStats:
    """Tests for OperationStats."""

    def test_default_values(self):
        """Test default values."""
        stats = OperationStats(operation=OperationType.QUERY)

        assert stats.count == 0
        assert stats.success_count == 0
        assert stats.error_count == 0
        assert stats.avg_latency_ms == 0.0
        assert stats.success_rate == 100.0

    def test_avg_latency(self):
        """Test average latency calculation."""
        stats = OperationStats(
            operation=OperationType.QUERY,
            count=10,
            total_latency_ms=500.0,
        )

        assert stats.avg_latency_ms == 50.0

    def test_success_rate(self):
        """Test success rate calculation."""
        stats = OperationStats(
            operation=OperationType.QUERY,
            count=100,
            success_count=95,
            error_count=5,
        )

        assert stats.success_rate == 95.0

    def test_to_dict(self):
        """Test dictionary conversion."""
        stats = OperationStats(
            operation=OperationType.QUERY,
            count=10,
            success_count=9,
            error_count=1,
            total_latency_ms=500.0,
            min_latency_ms=10.0,
            max_latency_ms=100.0,
        )

        result = stats.to_dict()

        assert result["operation"] == "query"
        assert result["count"] == 10
        assert result["success_rate"] == 90.0
        assert result["avg_latency_ms"] == 50.0


class TestKMMetrics:
    """Tests for KMMetrics."""

    def test_create_metrics(self):
        """Test creating metrics instance."""
        metrics = KMMetrics()

        assert metrics._window_size == 1000
        assert metrics._latency_warn_ms == 100.0

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (HealthStatus.UNKNOWN, 0),
            (HealthStatus.UNHEALTHY, 1),
            (HealthStatus.DEGRADED, 2),
            (HealthStatus.HEALTHY, 3),
        ],
    )
    def test_prometheus_health_adapter_uses_primitive_values(self, status, expected):
        """The KM side maps domain health values before crossing the boundary."""
        metrics = KMMetrics()
        original = get_metrics()
        metrics.get_health = lambda: HealthReport(status=status)  # type: ignore[method-assign]
        try:
            set_metrics(metrics)
            assert get_prometheus_health_status() == expected
        finally:
            set_metrics(original)

    def test_record_operation(self):
        """Test recording an operation."""
        metrics = KMMetrics()

        metrics.record(OperationType.QUERY, 50.0, success=True)

        stats = metrics.get_stats(OperationType.QUERY)
        assert stats["count"] == 1
        assert stats["success_count"] == 1
        assert stats["avg_latency_ms"] == 50.0

    def test_record_multiple_operations(self):
        """Test recording multiple operations."""
        metrics = KMMetrics()

        for i in range(10):
            metrics.record(OperationType.QUERY, 10.0 * (i + 1), success=True)

        stats = metrics.get_stats(OperationType.QUERY)
        assert stats["count"] == 10
        assert stats["min_latency_ms"] == 10.0
        assert stats["max_latency_ms"] == 100.0

    def test_record_error(self):
        """Test recording an error."""
        metrics = KMMetrics()

        metrics.record(
            OperationType.STORE,
            100.0,
            success=False,
            error="Connection failed",
        )

        stats = metrics.get_stats(OperationType.STORE)
        assert stats["error_count"] == 1
        assert stats["last_error"] == "Connection failed"

    def test_measure_operation_context_manager(self):
        """Test context manager for measuring operations."""
        metrics = KMMetrics()

        with metrics.measure_operation(OperationType.GET):
            time.sleep(0.01)  # 10ms

        stats = metrics.get_stats(OperationType.GET)
        assert stats["count"] == 1
        assert stats["avg_latency_ms"] >= 10.0  # At least 10ms

    def test_measure_operation_with_string(self):
        """Test context manager with string operation type."""
        metrics = KMMetrics()

        with metrics.measure_operation("query"):
            pass

        stats = metrics.get_stats(OperationType.QUERY)
        assert stats["count"] == 1

    def test_measure_operation_exception(self):
        """Test context manager handles exceptions."""
        metrics = KMMetrics()

        with pytest.raises(ValueError):
            with metrics.measure_operation(OperationType.DELETE):
                raise ValueError("Test error")

        stats = metrics.get_stats(OperationType.DELETE)
        assert stats["error_count"] == 1
        assert "Operation failed: ValueError" in stats["last_error"]

    def test_record_cache_hit(self):
        """Test recording cache hit."""
        metrics = KMMetrics()

        metrics.record_cache_access(hit=True)

        stats = metrics.get_stats(OperationType.CACHE_HIT)
        assert stats["count"] == 1

    def test_record_cache_miss(self):
        """Test recording cache miss."""
        metrics = KMMetrics()

        metrics.record_cache_access(hit=False)

        stats = metrics.get_stats(OperationType.CACHE_MISS)
        assert stats["count"] == 1

    def test_cache_hit_rate(self):
        """Test cache hit rate calculation."""
        metrics = KMMetrics()

        # 8 hits, 2 misses = 80% hit rate
        for _ in range(8):
            metrics.record_cache_access(hit=True)
        for _ in range(2):
            metrics.record_cache_access(hit=False)

        rate = metrics.get_cache_hit_rate()
        assert rate == 80.0

    def test_get_all_stats(self):
        """Test getting all stats."""
        metrics = KMMetrics()

        metrics.record(OperationType.QUERY, 50.0)
        metrics.record(OperationType.STORE, 100.0)

        all_stats = metrics.get_stats()

        assert "query" in all_stats
        assert "store" in all_stats

    def test_rolling_stats(self):
        """Test rolling statistics."""
        metrics = KMMetrics()

        # Record some operations
        for i in range(5):
            metrics.record(OperationType.QUERY, 10.0)

        rolling = metrics.get_rolling_stats(OperationType.QUERY, window_seconds=60.0)

        assert rolling["count"] == 5
        assert rolling["avg_latency_ms"] == 10.0

    def test_reset(self):
        """Test resetting metrics."""
        metrics = KMMetrics()

        metrics.record(OperationType.QUERY, 50.0)
        metrics.reset()

        stats = metrics.get_stats(OperationType.QUERY)
        assert stats["count"] == 0


class TestHealthChecks:
    """Tests for health check functionality."""

    def test_healthy_status(self):
        """Test healthy status."""
        metrics = KMMetrics()

        # Record some healthy operations
        for _ in range(10):
            metrics.record(OperationType.QUERY, 10.0, success=True)
            metrics.record_cache_access(hit=True)

        health = metrics.get_health()

        assert health.status == HealthStatus.HEALTHY
        assert health.checks["query_latency"] is True
        assert health.checks["success_rate"] is True

    def test_degraded_status_high_latency(self):
        """Test degraded status from high latency."""
        metrics = KMMetrics(latency_warn_ms=10.0, latency_critical_ms=100.0)

        # Record high latency operations
        for _ in range(10):
            metrics.record(OperationType.QUERY, 50.0, success=True)

        health = metrics.get_health()

        assert health.status in (HealthStatus.DEGRADED, HealthStatus.UNHEALTHY)
        assert health.checks["query_latency"] is False

    def test_unhealthy_status_low_success_rate(self):
        """Test unhealthy status from low success rate."""
        metrics = KMMetrics(success_rate_critical=90.0)

        # Record many failures
        for _ in range(50):
            metrics.record(OperationType.QUERY, 10.0, success=False, error="Failed")
        for _ in range(50):
            metrics.record(OperationType.QUERY, 10.0, success=True)

        health = metrics.get_health()

        assert health.status == HealthStatus.UNHEALTHY
        assert health.checks["success_rate"] is False

    def test_health_recommendations(self):
        """Test health recommendations."""
        metrics = KMMetrics(latency_warn_ms=10.0)

        # Record high latency
        for _ in range(10):
            metrics.record(OperationType.QUERY, 50.0, success=True)

        health = metrics.get_health()

        assert len(health.recommendations) > 0
        assert any("latency" in r.lower() for r in health.recommendations)

    def test_health_report_to_dict(self):
        """Test health report dictionary conversion."""
        metrics = KMMetrics()

        metrics.record(OperationType.QUERY, 10.0)
        health = metrics.get_health()
        result = health.to_dict()

        assert "status" in result
        assert "timestamp" in result
        assert "checks" in result
        assert "details" in result

    def test_metrics_to_dict(self):
        """Test full metrics dictionary."""
        metrics = KMMetrics()

        metrics.record(OperationType.QUERY, 50.0)
        result = metrics.to_dict()

        assert "health" in result
        assert "stats" in result
        assert "config" in result
        assert "uptime_seconds" in result


class TestGlobalMetrics:
    """Tests for global metrics instance."""

    def test_get_metrics_creates_instance(self):
        """Test getting global metrics creates instance."""
        # Reset global state
        import aragora.knowledge.mound.metrics as m

        m._global_metrics = None

        metrics = get_metrics()

        assert metrics is not None
        assert isinstance(metrics, KMMetrics)

    def test_get_metrics_does_not_import_observability_on_hot_path(self):
        """The singleton accessor does not repeat cross-layer registration."""
        import aragora.knowledge.mound.metrics as m

        m._global_metrics = None
        with patch.object(
            m,
            "_register_prometheus_health_provider",
            side_effect=AssertionError("registration should not run"),
        ):
            assert isinstance(get_metrics(), KMMetrics)

    def test_prometheus_registration_fails_soft_when_observability_unavailable(self):
        """KM metrics remain usable if the observability adapter cannot import."""
        import builtins
        import aragora.knowledge.mound.metrics as m

        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "aragora.observability.metrics.km":
                raise ImportError("observability unavailable")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded_import):
            assert m._register_prometheus_health_provider() is False

    def test_set_metrics_replaces_instance(self):
        """Test setting global metrics."""
        custom_metrics = KMMetrics(window_size=500)

        set_metrics(custom_metrics)
        result = get_metrics()

        assert result is custom_metrics
        assert result._window_size == 500

        # Reset
        set_metrics(KMMetrics())
