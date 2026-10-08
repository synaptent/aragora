"""
KM Health Metrics and Observability.

Provides metrics collection and health monitoring for the Knowledge Mound system.

Usage:
    from aragora.knowledge.mound.metrics import KMMetrics

    metrics = KMMetrics()

    # Record operations
    with metrics.measure_operation("query"):
        result = await km.query("topic")

    # Get health status
    health = metrics.get_health()

    # Get detailed metrics
    stats = metrics.get_stats()
"""

from __future__ import annotations

import logging
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Any
from collections.abc import Generator

from aragora.resilience.health import HealthStatus

logger = logging.getLogger(__name__)


class OperationType(str, Enum):
    """Types of KM operations to track."""

    QUERY = "query"
    STORE = "store"
    GET = "get"
    DELETE = "delete"
    SYNC = "sync"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    ADAPTER_FORWARD = "adapter_forward"
    ADAPTER_REVERSE = "adapter_reverse"
    EVENT_EMIT = "event_emit"


@dataclass
class OperationSample:
    """A single operation sample."""

    operation: OperationType
    latency_ms: float
    success: bool
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OperationStats:
    """Aggregated statistics for an operation type."""

    operation: OperationType
    count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    max_latency_ms: float = 0.0
    last_error: str | None = None
    last_error_at: float | None = None

    @property
    def avg_latency_ms(self) -> float:
        """Average latency in milliseconds."""
        if self.count == 0:
            return 0.0
        return self.total_latency_ms / self.count

    @property
    def success_rate(self) -> float:
        """Success rate as a percentage."""
        if self.count == 0:
            return 100.0
        return (self.success_count / self.count) * 100

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "operation": self.operation.value,
            "count": self.count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "min_latency_ms": (
                round(self.min_latency_ms, 2) if self.min_latency_ms != float("inf") else 0
            ),
            "max_latency_ms": round(self.max_latency_ms, 2),
            "success_rate": round(self.success_rate, 2),
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
        }


@dataclass
class HealthReport:
    """Health status report."""

    status: HealthStatus
    timestamp: datetime = field(default_factory=datetime.now)
    details: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, bool] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
            "checks": self.checks,
            "recommendations": self.recommendations,
        }


class KMMetrics:
    """
    Knowledge Mound metrics and health monitoring.

    Tracks:
    - Operation latencies (query, store, get, etc.)
    - Success/error rates
    - Cache hit rates
    - Adapter sync status
    - Overall system health

    Health thresholds (configurable):
    - Query latency: 100ms (warn), 500ms (unhealthy)
    - Success rate: 99% (warn), 95% (unhealthy)
    - Cache hit rate: 80% (warn), 60% (unhealthy)
    """

    def __init__(
        self,
        window_size: int = 1000,
        latency_warn_ms: float = 100.0,
        latency_critical_ms: float = 500.0,
        success_rate_warn: float = 99.0,
        success_rate_critical: float = 95.0,
        cache_hit_rate_warn: float = 80.0,
        cache_hit_rate_critical: float = 60.0,
    ):
        """
        Initialize metrics collector.

        Args:
            window_size: Number of samples to keep for rolling statistics
            latency_warn_ms: Latency threshold for warning status
            latency_critical_ms: Latency threshold for unhealthy status
            success_rate_warn: Success rate threshold for warning (%)
            success_rate_critical: Success rate threshold for unhealthy (%)
            cache_hit_rate_warn: Cache hit rate threshold for warning (%)
            cache_hit_rate_critical: Cache hit rate threshold for unhealthy (%)
        """
        self._window_size = window_size
        self._latency_warn_ms = latency_warn_ms
        self._latency_critical_ms = latency_critical_ms
        self._success_rate_warn = success_rate_warn
        self._success_rate_critical = success_rate_critical
        self._cache_hit_rate_warn = cache_hit_rate_warn
        self._cache_hit_rate_critical = cache_hit_rate_critical

        # Rolling sample window per operation type
        self._samples: dict[OperationType, deque[OperationSample]] = {
            op: deque(maxlen=window_size) for op in OperationType
        }

        # Aggregate statistics (all-time)
        self._stats: dict[OperationType, OperationStats] = {
            op: OperationStats(operation=op) for op in OperationType
        }

        # Lock for thread safety
        self._lock = Lock()

        # Startup time
        self._started_at = time.time()

    def record(
        self,
        operation: OperationType,
        latency_ms: float,
        success: bool = True,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Record an operation sample.

        Args:
            operation: Type of operation
            latency_ms: Operation latency in milliseconds
            success: Whether the operation succeeded
            error: Error message if failed
            metadata: Additional metadata
        """
        sample = OperationSample(
            operation=operation,
            latency_ms=latency_ms,
            success=success,
            metadata=metadata or {},
        )

        with self._lock:
            # Add to rolling window
            self._samples[operation].append(sample)

            # Update aggregate stats
            stats = self._stats[operation]
            stats.count += 1
            stats.total_latency_ms += latency_ms

            if success:
                stats.success_count += 1
            else:
                stats.error_count += 1
                stats.last_error = error
                stats.last_error_at = time.time()

            if latency_ms < stats.min_latency_ms:
                stats.min_latency_ms = latency_ms
            if latency_ms > stats.max_latency_ms:
                stats.max_latency_ms = latency_ms

        # Export to Prometheus (if available)
        self._export_to_prometheus(operation, latency_ms, success)

    def _export_to_prometheus(
        self,
        operation: OperationType,
        latency_ms: float,
        success: bool,
    ) -> None:
        """Export operation to Prometheus metrics."""
        try:
            from aragora.observability.metrics import record_km_operation, record_km_cache_access

            # Convert ms to seconds for Prometheus
            latency_seconds = latency_ms / 1000.0

            # Handle cache operations specially
            if operation == OperationType.CACHE_HIT:
                record_km_cache_access(hit=True)
            elif operation == OperationType.CACHE_MISS:
                record_km_cache_access(hit=False)
            else:
                record_km_operation(operation.value, success, latency_seconds)
        except ImportError:
            pass  # Prometheus not available
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.debug("Failed to export to Prometheus: %s", e)

    @contextmanager
    def measure_operation(
        self,
        operation: OperationType | str,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[None, None, None]:
        """
        Context manager to measure operation latency.

        Args:
            operation: Type of operation
            metadata: Additional metadata

        Usage:
            with metrics.measure_operation(OperationType.QUERY):
                result = await km.query("topic")
        """
        if isinstance(operation, str):
            operation = OperationType(operation)

        start = time.time()
        success = True
        error = None

        try:
            yield
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            success = False
            error = f"Operation failed: {type(e).__name__}"
            raise
        finally:
            latency_ms = (time.time() - start) * 1000
            self.record(operation, latency_ms, success, error, metadata)

    def record_cache_access(self, hit: bool) -> None:
        """
        Record a cache access.

        Args:
            hit: Whether it was a cache hit
        """
        op = OperationType.CACHE_HIT if hit else OperationType.CACHE_MISS
        self.record(op, 0.0, True)

    def get_stats(self, operation: OperationType | None = None) -> dict[str, Any]:
        """
        Get statistics for operations.

        Args:
            operation: Specific operation to get stats for, or None for all

        Returns:
            Dictionary of statistics
        """
        with self._lock:
            if operation:
                return self._stats[operation].to_dict()

            return {
                op.value: self._stats[op].to_dict()
                for op in OperationType
                if self._stats[op].count > 0
            }

    def get_rolling_stats(
        self,
        operation: OperationType,
        window_seconds: float = 60.0,
    ) -> dict[str, Any]:
        """
        Get rolling statistics for a specific time window.

        Args:
            operation: Type of operation
            window_seconds: Time window in seconds

        Returns:
            Dictionary of rolling statistics
        """
        cutoff = time.time() - window_seconds

        with self._lock:
            samples = [s for s in self._samples[operation] if s.timestamp >= cutoff]

        if not samples:
            return {
                "operation": operation.value,
                "count": 0,
                "avg_latency_ms": 0,
                "success_rate": 100.0,
                "window_seconds": window_seconds,
            }

        total_latency = sum(s.latency_ms for s in samples)
        success_count = sum(1 for s in samples if s.success)

        return {
            "operation": operation.value,
            "count": len(samples),
            "avg_latency_ms": round(total_latency / len(samples), 2),
            "min_latency_ms": round(min(s.latency_ms for s in samples), 2),
            "max_latency_ms": round(max(s.latency_ms for s in samples), 2),
            "success_rate": round((success_count / len(samples)) * 100, 2),
            "window_seconds": window_seconds,
        }

    def get_cache_hit_rate(self, window_seconds: float = 60.0) -> float:
        """
        Get cache hit rate for a time window.

        Args:
            window_seconds: Time window in seconds

        Returns:
            Cache hit rate as percentage (0-100)
        """
        cutoff = time.time() - window_seconds

        with self._lock:
            hits = sum(1 for s in self._samples[OperationType.CACHE_HIT] if s.timestamp >= cutoff)
            misses = sum(
                1 for s in self._samples[OperationType.CACHE_MISS] if s.timestamp >= cutoff
            )

        total = hits + misses
        if total == 0:
            return 100.0  # No cache access = 100% (neutral)

        return (hits / total) * 100

    def get_health(self) -> HealthReport:
        """
        Get overall health status.

        Returns:
            HealthReport with status and details
        """
        checks = {}
        recommendations = []
        details = {}

        # Check query latency
        query_stats = self.get_rolling_stats(OperationType.QUERY, 60.0)
        avg_latency = query_stats["avg_latency_ms"]
        details["query_avg_latency_ms"] = avg_latency

        if avg_latency > self._latency_critical_ms:
            checks["query_latency"] = False
            recommendations.append(f"Query latency ({avg_latency}ms) exceeds critical threshold")
        elif avg_latency > self._latency_warn_ms:
            checks["query_latency"] = False
            recommendations.append(f"Query latency ({avg_latency}ms) exceeds warning threshold")
        else:
            checks["query_latency"] = True

        # Check success rate
        all_operations = 0
        all_successes = 0
        with self._lock:
            for stats in self._stats.values():
                all_operations += stats.count
                all_successes += stats.success_count

        if all_operations > 0:
            success_rate = (all_successes / all_operations) * 100
        else:
            success_rate = 100.0

        details["overall_success_rate"] = round(success_rate, 2)

        if success_rate < self._success_rate_critical:
            checks["success_rate"] = False
            recommendations.append(f"Success rate ({success_rate}%) below critical threshold")
        elif success_rate < self._success_rate_warn:
            checks["success_rate"] = False
            recommendations.append(f"Success rate ({success_rate}%) below warning threshold")
        else:
            checks["success_rate"] = True

        # Check cache hit rate
        cache_hit_rate = self.get_cache_hit_rate(60.0)
        details["cache_hit_rate"] = round(cache_hit_rate, 2)

        if cache_hit_rate < self._cache_hit_rate_critical:
            checks["cache_hit_rate"] = False
            recommendations.append(f"Cache hit rate ({cache_hit_rate}%) below critical threshold")
        elif cache_hit_rate < self._cache_hit_rate_warn:
            checks["cache_hit_rate"] = False
            recommendations.append(f"Cache hit rate ({cache_hit_rate}%) below warning threshold")
        else:
            checks["cache_hit_rate"] = True

        # Check for recent errors
        recent_errors = []
        cutoff = time.time() - 300  # Last 5 minutes
        with self._lock:
            for op, stats in self._stats.items():
                if stats.last_error_at and stats.last_error_at > cutoff:
                    recent_errors.append(
                        {
                            "operation": op.value,
                            "error": stats.last_error,
                            "at": stats.last_error_at,
                        }
                    )

        if recent_errors:
            details["recent_errors"] = recent_errors
            if len(recent_errors) > 5:
                checks["error_rate"] = False
                recommendations.append(f"{len(recent_errors)} errors in last 5 minutes")
            else:
                checks["error_rate"] = True
        else:
            checks["error_rate"] = True

        # Add uptime
        details["uptime_seconds"] = round(time.time() - self._started_at, 1)

        # Determine overall status
        if all(checks.values()):
            status = HealthStatus.HEALTHY
        elif checks.get("success_rate") is False or checks.get("query_latency") is False:
            status = HealthStatus.UNHEALTHY
        else:
            status = HealthStatus.DEGRADED

        return HealthReport(
            status=status,
            checks=checks,
            details=details,
            recommendations=recommendations,
        )

    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            for op in OperationType:
                self._samples[op] = deque(maxlen=self._window_size)
                self._stats[op] = OperationStats(operation=op)
            self._started_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Convert all metrics to dictionary."""
        health = self.get_health()

        return {
            "health": health.to_dict(),
            "stats": self.get_stats(),
            "config": {
                "window_size": self._window_size,
                "latency_warn_ms": self._latency_warn_ms,
                "latency_critical_ms": self._latency_critical_ms,
                "success_rate_warn": self._success_rate_warn,
                "success_rate_critical": self._success_rate_critical,
                "cache_hit_rate_warn": self._cache_hit_rate_warn,
                "cache_hit_rate_critical": self._cache_hit_rate_critical,
            },
            "uptime_seconds": round(time.time() - self._started_at, 1),
        }


# Global metrics instance (can be replaced per-workspace)
_global_metrics: KMMetrics | None = None


def get_metrics() -> KMMetrics:
    """Get the global metrics instance."""
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = KMMetrics()
    return _global_metrics


def set_metrics(metrics: KMMetrics) -> None:
    """Set the global metrics instance."""
    global _global_metrics
    _global_metrics = metrics
    _register_prometheus_health_provider()


def get_prometheus_health_status() -> int:
    """Return the current KM health as the observability gauge value."""
    health_map = {
        HealthStatus.UNKNOWN: 0,
        HealthStatus.UNHEALTHY: 1,
        HealthStatus.DEGRADED: 2,
        HealthStatus.HEALTHY: 3,
    }
    return health_map.get(get_metrics().get_health().status, 0)


def _register_prometheus_health_provider() -> bool:
    """Register the KM-owned health adapter with observability."""
    try:
        from aragora.observability.metrics.km import register_km_health_provider
    except ImportError as e:
        logger.debug("KM Prometheus health provider is unavailable: %s", e)
        return False

    register_km_health_provider(get_prometheus_health_status)
    return True


def register_prometheus_health_provider() -> bool:
    """Register the KM health provider at an application composition root."""
    return _register_prometheus_health_provider()


__all__ = [
    "KMMetrics",
    "OperationType",
    "OperationStats",
    "HealthStatus",
    "HealthReport",
    "get_metrics",
    "set_metrics",
    "get_prometheus_health_status",
    "register_prometheus_health_provider",
]
