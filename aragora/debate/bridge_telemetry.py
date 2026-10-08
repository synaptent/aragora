"""
Bridge Telemetry Module - Observability for Cross-Pollination Bridges.

Provides decorators and utilities for instrumenting Phase 9 bridges
with Prometheus metrics and structured logging.

Usage:
    from aragora.debate.bridge_telemetry import (
        with_bridge_telemetry,
        BridgeTelemetryContext,
        BridgeMetrics,
    )

    # Decorator for bridge methods
    @with_bridge_telemetry("performance_router", "sync")
    def sync_to_router(self):
        ...

    # Context manager for manual tracking
    with BridgeTelemetryContext("relationship_bias", "compute") as ctx:
        result = compute_echo_risk(team)
        ctx.set_result(result)
"""

from __future__ import annotations

__all__ = [
    "with_bridge_telemetry",
    "BridgeTelemetryContext",
    "BridgeMetrics",
    "record_bridge_operation",
    "get_bridge_telemetry_stats",
]

import asyncio
import functools
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar, cast
from collections.abc import Callable

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class BridgeOperation:
    """Telemetry record for a single bridge operation."""

    bridge_name: str
    operation: str  # "sync", "compute", "recommend", "detect"
    start_time: float
    end_time: float = 0.0
    duration_ms: float = 0.0
    success: bool = True
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def complete(self, success: bool = True, error: Exception | None = None) -> None:
        """Mark the operation as complete."""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.success = success
        if error:
            self.error_type = type(error).__name__
            self.error_message = str(error)[:200]


@dataclass
class BridgeMetrics:
    """Aggregated metrics for a bridge.

    Tracks operation counts, latencies, and error rates.
    """

    bridge_name: str
    total_operations: int = 0
    successful_operations: int = 0
    failed_operations: int = 0
    total_duration_ms: float = 0.0
    last_operation_time: datetime | None = None
    operations_by_type: dict[str, int] = field(default_factory=dict)
    errors_by_type: dict[str, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        """Calculate success rate as a fraction."""
        if self.total_operations == 0:
            return 1.0
        return self.successful_operations / self.total_operations

    @property
    def avg_duration_ms(self) -> float:
        """Calculate average operation duration."""
        if self.total_operations == 0:
            return 0.0
        return self.total_duration_ms / self.total_operations

    def record_operation(self, op: BridgeOperation) -> None:
        """Record a completed operation."""
        self.total_operations += 1
        self.total_duration_ms += op.duration_ms
        self.last_operation_time = datetime.now()

        # Track by operation type
        self.operations_by_type[op.operation] = self.operations_by_type.get(op.operation, 0) + 1

        if op.success:
            self.successful_operations += 1
        else:
            self.failed_operations += 1
            if op.error_type:
                self.errors_by_type[op.error_type] = self.errors_by_type.get(op.error_type, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "bridge_name": self.bridge_name,
            "total_operations": self.total_operations,
            "successful_operations": self.successful_operations,
            "failed_operations": self.failed_operations,
            "success_rate": self.success_rate,
            "avg_duration_ms": self.avg_duration_ms,
            "last_operation_time": (
                self.last_operation_time.isoformat() if self.last_operation_time else None
            ),
            "operations_by_type": self.operations_by_type,
            "errors_by_type": self.errors_by_type,
        }


# Global metrics store (thread-safe)
_metrics_lock = threading.Lock()
_bridge_metrics: dict[str, BridgeMetrics] = {}
_recent_operations: list[BridgeOperation] = []
_max_recent_operations = 100


def _get_or_create_metrics(bridge_name: str) -> BridgeMetrics:
    """Get or create metrics for a bridge."""
    with _metrics_lock:
        if bridge_name not in _bridge_metrics:
            _bridge_metrics[bridge_name] = BridgeMetrics(bridge_name=bridge_name)
        return _bridge_metrics[bridge_name]


def _record_operation(op: BridgeOperation) -> None:
    """Record a completed operation to metrics."""
    metrics = _get_or_create_metrics(op.bridge_name)
    metrics.record_operation(op)

    # Store recent operations for debugging
    with _metrics_lock:
        _recent_operations.append(op)
        if len(_recent_operations) > _max_recent_operations:
            _recent_operations.pop(0)

    # Emit to Prometheus metrics
    try:
        from aragora.observability.metrics import (
            record_bridge_sync,
            record_bridge_sync_latency,
            record_bridge_error,
        )

        record_bridge_sync(op.bridge_name, op.success)
        record_bridge_sync_latency(op.bridge_name, op.duration_ms / 1000)
        if not op.success and op.error_type:
            record_bridge_error(op.bridge_name, op.error_type)
    except ImportError:
        logger.debug("Bridge telemetry metrics not available: observability module not installed")


def record_bridge_operation(
    bridge_name: str,
    operation: str,
    success: bool,
    duration_ms: float,
    error: Exception | None = None,
    **metadata: Any,
) -> None:
    """Record a bridge operation manually.

    Args:
        bridge_name: Name of the bridge
        operation: Operation type
        success: Whether the operation succeeded
        duration_ms: Duration in milliseconds
        error: Optional exception if operation failed
        **metadata: Additional metadata to record
    """
    op = BridgeOperation(
        bridge_name=bridge_name,
        operation=operation,
        start_time=time.time() - duration_ms / 1000,
        metadata=metadata,
    )
    op.complete(success=success, error=error)
    _record_operation(op)

    logger.debug(
        "bridge_operation bridge=%s op=%s duration=%.1fms success=%s",
        bridge_name,
        operation,
        duration_ms,
        success,
    )


class BridgeTelemetryContext:
    """Context manager for manual bridge telemetry recording.

    Usage:
        with BridgeTelemetryContext("performance_router", "compute") as ctx:
            result = compute_routing_score(agent)
            ctx.set_metadata("agent", agent)
            ctx.set_metadata("score", result.overall_score)
    """

    def __init__(self, bridge_name: str, operation: str):
        self.operation = BridgeOperation(
            bridge_name=bridge_name,
            operation=operation,
            start_time=time.time(),
        )

    def set_metadata(self, key: str, value: Any) -> None:
        """Add metadata to the operation record."""
        self.operation.metadata[key] = value

    def set_error(self, error: Exception) -> None:
        """Record an error manually."""
        self.operation.error_type = type(error).__name__
        self.operation.error_message = str(error)[:200]

    def __enter__(self) -> BridgeTelemetryContext:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        success = exc_type is None
        if exc_val:
            self.set_error(exc_val)
        self.operation.complete(success=success)
        _record_operation(self.operation)

        logger.debug(
            "bridge_operation bridge=%s op=%s duration=%.1fms success=%s",
            self.operation.bridge_name,
            self.operation.operation,
            self.operation.duration_ms,
            self.operation.success,
        )


def with_bridge_telemetry(
    bridge_name: str,
    operation: str,
    extract_metadata: Callable[..., dict[str, Any]] | None = None,
) -> Callable[[F], F]:
    """Decorator to add telemetry to bridge methods.

    Args:
        bridge_name: Name of the bridge
        operation: Operation type (sync, compute, recommend, etc.)
        extract_metadata: Optional function to extract metadata from args

    Returns:
        Decorated function with telemetry instrumentation

    Usage:
        class PerformanceRouterBridge:
            @with_bridge_telemetry("performance_router", "sync")
            def sync_to_router(self, force: bool = False):
                ...

            @with_bridge_telemetry(
                "performance_router",
                "compute",
                extract_metadata=lambda self, agent: {"agent": agent}
            )
            def compute_routing_score(self, agent: str):
                ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            op = BridgeOperation(
                bridge_name=bridge_name,
                operation=operation,
                start_time=time.time(),
            )

            # Extract metadata if function provided
            if extract_metadata:
                try:
                    op.metadata = extract_metadata(*args, **kwargs)
                except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
                    logger.debug("bridge_telemetry_metadata_extraction_failed: %s", e)

            try:
                result = await func(*args, **kwargs)
                op.complete(success=True)
                return result
            except Exception as e:  # noqa: BLE001 - telemetry decorator: must catch all to record before re-raising
                op.complete(success=False, error=e)
                raise
            finally:
                _record_operation(op)
                logger.debug(
                    "bridge_operation bridge=%s op=%s duration=%.1fms success=%s",
                    bridge_name,
                    operation,
                    op.duration_ms,
                    op.success,
                )

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            op = BridgeOperation(
                bridge_name=bridge_name,
                operation=operation,
                start_time=time.time(),
            )

            if extract_metadata:
                try:
                    op.metadata = extract_metadata(*args, **kwargs)
                except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
                    logger.debug("bridge_telemetry_metadata_extraction_failed: %s", e)

            try:
                result = func(*args, **kwargs)
                op.complete(success=True)
                return result
            except Exception as e:  # noqa: BLE001 - telemetry decorator: must catch all to record before re-raising
                op.complete(success=False, error=e)
                raise
            finally:
                _record_operation(op)
                logger.debug(
                    "bridge_operation bridge=%s op=%s duration=%.1fms success=%s",
                    bridge_name,
                    operation,
                    op.duration_ms,
                    op.success,
                )

        if asyncio.iscoroutinefunction(func):
            return cast(F, async_wrapper)
        return cast(F, sync_wrapper)

    return decorator


def get_bridge_telemetry_stats() -> dict[str, Any]:
    """Get telemetry statistics for all bridges.

    Returns:
        Dict with metrics for each bridge and recent operations
    """
    with _metrics_lock:
        total_ops = sum(m.total_operations for m in _bridge_metrics.values())
        successful_ops = sum(m.successful_operations for m in _bridge_metrics.values())

        # When there are no operations, success rate is 1.0 (no failures)
        if total_ops == 0:
            success_rate = 1.0
        else:
            success_rate = successful_ops / total_ops

        return {
            "bridges": {name: metrics.to_dict() for name, metrics in _bridge_metrics.items()},
            "recent_operations_count": len(_recent_operations),
            "total_operations": total_ops,
            "overall_success_rate": success_rate,
        }


def get_recent_bridge_operations(limit: int = 20) -> list[dict[str, Any]]:
    """Get recent bridge operations for debugging.

    Args:
        limit: Maximum number of operations to return

    Returns:
        List of recent operation records
    """
    with _metrics_lock:
        recent = _recent_operations[-limit:]
        return [
            {
                "bridge_name": op.bridge_name,
                "operation": op.operation,
                "duration_ms": op.duration_ms,
                "success": op.success,
                "error_type": op.error_type,
                "metadata": op.metadata,
            }
            for op in recent
        ]


def reset_bridge_telemetry() -> None:
    """Reset all bridge telemetry (for testing)."""
    global _bridge_metrics, _recent_operations
    with _metrics_lock:
        _bridge_metrics = {}
        _recent_operations = []


# Convenience decorators for specific bridges


def performance_router_telemetry(
    operation: str,
) -> Callable[[F], F]:
    """Telemetry decorator for PerformanceRouterBridge methods."""
    return with_bridge_telemetry("performance_router", operation)


def relationship_bias_telemetry(
    operation: str,
) -> Callable[[F], F]:
    """Telemetry decorator for RelationshipBiasBridge methods."""
    return with_bridge_telemetry("relationship_bias", operation)


def calibration_cost_telemetry(
    operation: str,
) -> Callable[[F], F]:
    """Telemetry decorator for CalibrationCostBridge methods."""
    return with_bridge_telemetry("calibration_cost", operation)


def novelty_selection_telemetry(
    operation: str,
) -> Callable[[F], F]:
    """Telemetry decorator for NoveltySelectionBridge methods."""
    return with_bridge_telemetry("novelty_selection", operation)


def rlm_selection_telemetry(
    operation: str,
) -> Callable[[F], F]:
    """Telemetry decorator for RLMSelectionBridge methods."""
    return with_bridge_telemetry("rlm_selection", operation)


def outcome_complexity_telemetry(
    operation: str,
) -> Callable[[F], F]:
    """Telemetry decorator for OutcomeComplexityBridge methods."""
    return with_bridge_telemetry("outcome_complexity", operation)


def analytics_selection_telemetry(
    operation: str,
) -> Callable[[F], F]:
    """Telemetry decorator for AnalyticsSelectionBridge methods."""
    return with_bridge_telemetry("analytics_selection", operation)
