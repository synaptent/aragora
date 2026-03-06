"""Base class for Knowledge Mound adapters.

Provides shared utilities for event emission, metrics recording, SLO monitoring,
reverse flow state management, and resilience patterns that are common across
all adapters.

This consolidates ~200 lines of duplicated code from 10+ adapters.

Usage:
    from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter

    class MyAdapter(KnowledgeMoundAdapter):
        adapter_name = "my_adapter"

        def __init__(self, source_system, **kwargs):
            super().__init__(**kwargs)
            self._source = source_system

        async def my_operation(self):
            # Use resilient call wrapper for automatic circuit breaker,
            # bulkhead, timeout, and SLO monitoring
            async with self._resilient_call("my_operation"):
                return await self._do_operation()
"""

from __future__ import annotations

import logging
import time
from typing import Any
from collections.abc import Callable

from aragora.observability.tracing import get_tracer
from aragora.knowledge.mound.resilience import (
    AdapterCircuitBreakerConfig,
    ResilientAdapterMixin,
)

logger = logging.getLogger(__name__)

# Type alias for event callback
EventCallback = Callable[[str, dict[str, Any]], None]

# Per-adapter circuit breaker configurations
# These are tuned based on each adapter's characteristics:
# - Fast in-memory adapters: tight thresholds, short timeouts
# - External/IO-bound adapters: lenient thresholds, longer timeouts
# - Database-heavy adapters: moderate thresholds
ADAPTER_CIRCUIT_CONFIGS: dict[str, AdapterCircuitBreakerConfig] = {
    # Fast adapters - tight thresholds
    "elo": AdapterCircuitBreakerConfig(failure_threshold=3, timeout_seconds=15.0),
    "ranking": AdapterCircuitBreakerConfig(failure_threshold=3, timeout_seconds=15.0),
    # External/slow adapters - lenient
    "evidence": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=60.0),
    "pulse": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=45.0),
    # Database-heavy adapters
    "continuum": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=30.0),
    "consensus": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=30.0),
    "critique": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=30.0),
    # Analytics/insights adapters
    "insights": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=45.0),
    "belief": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=30.0),
    "cost": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=30.0),
    # Control plane adapters
    "control_plane": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=30.0),
    "receipt": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=30.0),
    "decision_plan": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=30.0),
    "culture": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=45.0),
    "rlm": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=45.0),
    # Blockchain adapter - external with potential network latency
    "erc8004": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=60.0),
    # Document extraction adapter - external LLM calls
    "langextract": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=60.0),
    # Pipeline adapter
    "pipeline": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=30.0),
    # Enterprise data adapters - external API calls with potential latency
    "email": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=45.0),
    "jira": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=45.0),
    "confluence": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=45.0),
    # Idea Cloud adapter - external file I/O, moderate latency
    "ideacloud": AdapterCircuitBreakerConfig(failure_threshold=5, timeout_seconds=45.0),
}


class KnowledgeMoundAdapter(ResilientAdapterMixin):
    """Base class for all Knowledge Mound adapters.

    Provides:
    - Event emission with callback management
    - Prometheus metrics recording
    - SLO monitoring and alerting
    - Reverse flow state tracking
    - Circuit breaker protection (via ResilientAdapterMixin)
    - Bulkhead isolation (via ResilientAdapterMixin)
    - Automatic retry with exponential backoff (via ResilientAdapterMixin)
    - Common utility methods

    Subclasses should override:
    - adapter_name: Unique identifier for metrics/logging

    Resilience Features:
        All adapters inherit circuit breaker, bulkhead, and timeout protection.
        Use `async with self._resilient_call("operation_name"):` in async methods
        to automatically apply these patterns.
    """

    adapter_name: str = "base"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Enforce that concrete adapters define a unique adapter_name.

        This runs when a subclass is created, ensuring all adapters have
        proper identification for metrics, logging, and circuit breakers.

        Skips validation for:
        - Mixin classes (names ending with 'Mixin')
        - Private/internal classes (names starting with '_')
        - Abstract base classes
        """
        super().__init_subclass__(**kwargs)

        # Skip mixins and internal classes
        if cls.__name__.endswith("Mixin") or cls.__name__.startswith("_"):
            return

        # Check adapter_name is defined and not 'base'
        if not hasattr(cls, "adapter_name"):
            raise TypeError(f"{cls.__name__} must define 'adapter_name' class attribute")

        if cls.adapter_name == "base":
            raise TypeError(
                f"{cls.__name__} must override 'adapter_name' "
                f"(currently 'base'). Set a unique identifier like "
                f"adapter_name = '{cls.__name__.lower().replace('adapter', '')}'"
            )

    def __init__(
        self,
        enable_dual_write: bool = False,
        event_callback: EventCallback | None = None,
        enable_tracing: bool = True,
        enable_resilience: bool = True,
        resilience_timeout: float = 5.0,
    ):
        """Initialize the adapter with common configuration.

        Args:
            enable_dual_write: If True, writes go to both systems during migration.
            event_callback: Optional callback for emitting events (event_type, data).
            enable_tracing: If True, OpenTelemetry tracing is enabled for operations.
            enable_resilience: If True, enables circuit breaker, bulkhead, and
                timeout protection for adapter operations.
            resilience_timeout: Default timeout for resilient operations in seconds.
        """
        self._enable_dual_write = enable_dual_write
        self._event_callback = event_callback
        self._enable_tracing = enable_tracing
        self._enable_resilience = enable_resilience
        self._tracer = get_tracer() if enable_tracing else None
        self._last_operation_time: float = 0.0
        self._error_count: int = 0
        self._init_reverse_flow_state()

        # Initialize resilience patterns (circuit breaker, bulkhead, retry)
        if enable_resilience:
            # Use per-adapter circuit config if available
            circuit_config = ADAPTER_CIRCUIT_CONFIGS.get(self.adapter_name)
            self._init_resilience(
                adapter_name=self.adapter_name,
                circuit_config=circuit_config,
                timeout_seconds=resilience_timeout,
            )

    def _init_reverse_flow_state(self) -> None:
        """Initialize tracking state for reverse flow operations.

        Called automatically in __init__ and can be called to reset state.
        """
        if not hasattr(self, "_reverse_flow_state"):
            self._reverse_flow_state: dict[str, Any] = {}

        self._reverse_flow_state.update(
            {
                "validations_applied": 0,
                "adjustments_made": 0,
                "validations_stored": [],
                "outcome_history": {},
                "pending_validations": [],
            }
        )

    def clear_reverse_flow_state(self) -> None:
        """Clear reverse flow state for testing or reset."""
        self._init_reverse_flow_state()

    def get_reverse_flow_stats(self) -> dict[str, Any]:
        """Get statistics about reverse flow operations.

        Returns:
            Dict with validation counts, adjustment counts, and history.
        """
        self._init_reverse_flow_state()
        return {
            "validations_applied": self._reverse_flow_state.get("validations_applied", 0),
            "adjustments_made": self._reverse_flow_state.get("adjustments_made", 0),
            "pending_count": len(self._reverse_flow_state.get("pending_validations", [])),
            "history_size": len(self._reverse_flow_state.get("outcome_history", {})),
        }

    def set_event_callback(self, callback: EventCallback) -> None:
        """Set the event callback for WebSocket notifications.

        Args:
            callback: Function that receives (event_type, data) tuples.
        """
        self._event_callback = callback

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event if callback is configured.

        Events are used for real-time WebSocket notifications.

        Args:
            event_type: Type of event (e.g., "km_sync", "validation_applied").
            data: Event payload.
        """
        if not self._event_callback:
            return

        try:
            self._event_callback(event_type, data)
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:  # noqa: BLE001 - adapter isolation
            logger.warning("[%s] Failed to emit event %s: %s", self.adapter_name, event_type, e)

    def _record_metric(
        self,
        operation: str,
        success: bool,
        latency: float,
        extra_labels: dict[str, str] | None = None,
    ) -> None:
        """Record Prometheus metric for adapter operation and check SLOs.

        Args:
            operation: Operation name (search, store, sync, semantic_search).
            success: Whether operation succeeded.
            latency: Operation latency in seconds.
            extra_labels: Additional labels for the metric.
        """
        latency_ms = latency * 1000  # Convert to milliseconds

        try:
            from aragora.observability.metrics.km import (
                record_km_operation,
                record_km_adapter_sync,
            )

            record_km_operation(operation, success, latency)
            if operation in ("store", "sync", "forward_sync"):
                record_km_adapter_sync(self.adapter_name, "forward", success)
            elif operation in ("reverse_sync", "validate"):
                record_km_adapter_sync(self.adapter_name, "reverse", success)
        except ImportError:
            pass  # Metrics not available
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.debug("[%s] Failed to record metric: %s", self.adapter_name, e)

        # Check SLOs and alert on violations
        self._check_slo(operation, latency_ms)

    def _check_slo(self, operation: str, latency_ms: float) -> None:
        """Check SLO thresholds and record violations.

        Args:
            operation: Operation name.
            latency_ms: Operation latency in milliseconds.
        """
        try:
            from aragora.observability.metrics.slo import check_and_record_slo_with_recovery

            # Map operation to SLO name
            slo_mapping = {
                "search": "adapter_reverse",
                "store": "adapter_forward_sync",
                "sync": "adapter_forward_sync",
                "semantic_search": "adapter_search",
                "reverse_sync": "adapter_reverse",
                "validate": "adapter_reverse",
            }

            slo_name = slo_mapping.get(operation)
            if slo_name:
                passed, message = check_and_record_slo_with_recovery(
                    operation=slo_name,
                    latency_ms=latency_ms,
                    context={"adapter": self.adapter_name, "operation": operation},
                )
                if not passed:
                    logger.warning("[%s] SLO violation: %s", self.adapter_name, message)
        except ImportError:
            pass  # SLO monitoring not available
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.debug("[%s] Failed to check SLO: %s", self.adapter_name, e)

    def _record_validation_outcome(
        self,
        record_id: str,
        outcome: str,
        confidence: float,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record outcome of a validation for tracking.

        Args:
            record_id: ID of the validated record.
            outcome: Validation outcome (applied, skipped, failed).
            confidence: Confidence score of the validation.
            details: Additional details about the validation.
        """
        self._init_reverse_flow_state()

        self._reverse_flow_state["outcome_history"][record_id] = {
            "outcome": outcome,
            "confidence": confidence,
            "timestamp": time.time(),
            "details": details or {},
        }

        if outcome == "applied":
            self._reverse_flow_state["validations_applied"] += 1
        elif outcome == "adjusted":
            self._reverse_flow_state["adjustments_made"] += 1

    def _timed_operation(self, operation_name: str, **span_attributes: Any):
        """Context manager for timing, recording, and tracing operations.

        Usage:
            with self._timed_operation("search", query="test") as timer:
                results = self._do_search()
            # Metrics and traces automatically recorded

        Args:
            operation_name: Name of the operation for metrics/tracing.
            **span_attributes: Additional attributes to add to the trace span.

        Returns:
            Context manager that records metrics and traces on exit.
        """
        return _TimedOperation(self, operation_name, span_attributes)

    def health_check(self) -> dict[str, Any]:
        """Return adapter health status for monitoring.

        Returns:
            Dict containing health status, last operation time, error counts,
            and resilience statistics (circuit breaker state, bulkhead usage).
        """
        health = {
            "adapter": self.adapter_name,
            "healthy": self._error_count < 5,  # Unhealthy if 5+ consecutive errors
            "last_operation_time": self._last_operation_time,
            "error_count": self._error_count,
            "reverse_flow_stats": self.get_reverse_flow_stats(),
        }

        # Include resilience stats if enabled
        if getattr(self, "_enable_resilience", False) and hasattr(self, "get_resilience_stats"):
            health["resilience"] = self.get_resilience_stats()

        return health

    def reset_health_counters(self) -> None:
        """Reset health counters (e.g., after recovering from errors)."""
        self._error_count = 0


class _TimedOperation:
    """Context manager for timing and tracing adapter operations."""

    def __init__(
        self,
        adapter: KnowledgeMoundAdapter,
        operation: str,
        span_attributes: dict[str, Any] | None = None,
    ):
        self.adapter = adapter
        self.operation = operation
        self.span_attributes = span_attributes or {}
        self.start_time = 0.0
        self.success = True
        self.error: Exception | None = None
        self._span = None

    def __enter__(self) -> _TimedOperation:
        self.start_time = time.time()

        # Start trace span if tracing enabled
        if self.adapter._tracer is not None:
            span_name = f"{self.adapter.adapter_name}.{self.operation}"
            span = self.adapter._tracer.start_span(span_name)
            self._span = span
            span.set_attribute("adapter.name", self.adapter.adapter_name)
            span.set_attribute("adapter.operation", self.operation)
            for key, value in self.span_attributes.items():
                if value is not None:
                    span.set_attribute(f"adapter.{key}", str(value))

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        latency = time.time() - self.start_time
        self.success = exc_type is None
        if not self.success:
            self.error = exc_val

        # Update adapter state
        self.adapter._last_operation_time = time.time()
        if self.success:
            self.adapter._error_count = 0  # Reset on success
        else:
            self.adapter._error_count += 1

        # End trace span
        if self._span is not None:
            self._span.set_attribute("adapter.success", self.success)
            self._span.set_attribute("adapter.latency_ms", latency * 1000)
            if not self.success and exc_val is not None:
                self._span.record_exception(exc_val)
            self._span.end()

        self.adapter._record_metric(self.operation, self.success, latency)
        # Don't suppress exceptions (returning None is equivalent to False)


__all__ = [
    "KnowledgeMoundAdapter",
    "EventCallback",
]
