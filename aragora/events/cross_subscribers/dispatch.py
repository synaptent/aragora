"""
Event dispatch logic for CrossSubscriberManager.

Extracted from manager.py for maintainability.
Contains event dispatch, batching, retry with circuit breaker,
and metrics/SLO recording.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from collections.abc import Callable

from aragora.events.subscribers.config import (
    AsyncDispatchConfig,
    RetryConfig,
    SubscriberStats,
)
from aragora.events.types import StreamEvent, StreamEventType
from aragora.resilience import CircuitBreaker

# Import metrics (optional - graceful fallback if not available)
try:
    from aragora.observability.prometheus_cross_pollination import (
        record_event_dispatched as _record_event_dispatched,
        record_handler_call as _record_handler_call,
        set_circuit_breaker_state as _set_circuit_breaker_state,
    )

    METRICS_AVAILABLE = True

    def record_event_dispatched(event_type: str) -> None:
        """Record event dispatch metric."""
        _record_event_dispatched(event_type)

    def record_handler_call(handler: str, status: str, duration: float) -> None:
        """Record handler call metric."""
        _record_handler_call(handler, status, duration)

    def set_circuit_breaker_state(handler: str, is_open: bool) -> None:
        """Set circuit breaker state metric."""
        _set_circuit_breaker_state(handler, is_open)

except ImportError:
    METRICS_AVAILABLE = False

    def record_event_dispatched(event_type: str) -> None:
        """No-op fallback when prometheus metrics not available."""
        pass

    def record_handler_call(handler: str, status: str, duration: float) -> None:
        """No-op fallback when prometheus metrics not available."""
        pass

    def set_circuit_breaker_state(handler: str, is_open: bool) -> None:
        """No-op fallback when prometheus metrics not available."""
        pass


# Import SLO metrics (optional - graceful fallback)
try:
    from aragora.observability.metrics.slo import (
        check_and_record_slo as _check_and_record_slo,
    )

    SLO_METRICS_AVAILABLE = True

    def check_and_record_slo(
        operation: str, latency_ms: float, percentile: str = "p99"
    ) -> tuple[bool, str]:
        """Check and record SLO metric."""
        return _check_and_record_slo(operation, latency_ms, percentile)

except ImportError:
    SLO_METRICS_AVAILABLE = False

    def check_and_record_slo(
        operation: str, latency_ms: float, percentile: str = "p99"
    ) -> tuple[bool, str]:
        """Fallback when SLO metrics not available."""
        return True, f"SLO metrics not available for {operation}"


logger = logging.getLogger(__name__)

CrossSubscriberHandler = Callable[[StreamEvent], object]


def _default_async_event_types() -> set:
    """Default event types for async dispatch."""
    return {
        StreamEventType.MEMORY_STORED,
        StreamEventType.MEMORY_RETRIEVED,
        StreamEventType.KNOWLEDGE_QUERIED,
        StreamEventType.RLM_COMPRESSION_COMPLETE,
    }


class DispatchMixin:
    """Mixin providing event dispatch, batching, and retry logic.

    Expects the consuming class to define:
    - self._subscribers: dict[StreamEventType, list[tuple[str, Callable]]]
    - self._stats: dict[str, SubscriberStats]
    - self._filters: dict[str, Callable]
    - self._circuit_breaker: CircuitBreaker
    - self._default_retry_config: RetryConfig
    - self._async_config: AsyncDispatchConfig
    - self._event_batch: dict[StreamEventType, list[StreamEvent]]
    - self._batch_last_flush: float
    """

    # Mixin attribute declarations (provided by the composed class)
    _subscribers: dict[StreamEventType, list[tuple[str, CrossSubscriberHandler]]]
    _stats: dict[str, SubscriberStats]
    _filters: dict[str, Callable[[StreamEvent], bool]]
    _circuit_breaker: CircuitBreaker
    _default_retry_config: RetryConfig
    _async_config: AsyncDispatchConfig
    _event_batch: dict[StreamEventType, list[StreamEvent]]
    _batch_last_flush: float

    def _dispatch_event(self, event: StreamEvent) -> None:
        """Dispatch event to registered subscribers with sampling and circuit breaker support."""
        # Record event dispatch metric
        if METRICS_AVAILABLE:
            record_event_dispatched(event.type.value)

        handlers = self._subscribers.get(event.type, [])

        for name, handler in handlers:
            # Check if handler is enabled
            if name in self._stats and not self._stats[name].enabled:
                continue

            # Check circuit breaker - skip if handler circuit is open
            if not self._circuit_breaker.is_available(name):
                if name in self._stats:
                    self._stats[name].events_skipped += 1
                continue

            # Check filter
            if name in self._filters:
                filter_func = self._filters[name]
                try:
                    if not filter_func(event):
                        if name in self._stats:
                            self._stats[name].events_skipped += 1
                        continue
                except (TypeError, ValueError, AttributeError, KeyError) as e:
                    logger.warning("Filter error for %s: %s", name, e)

            # Apply sampling
            sample_rate = self._stats[name].sample_rate if name in self._stats else 1.0
            if sample_rate < 1.0 and random.random() > sample_rate:  # noqa: S311 -- probabilistic sampling
                if name in self._stats:
                    self._stats[name].events_skipped += 1
                continue

            # Get retry config
            configured_retry = self._stats[name].retry_config if name in self._stats else None
            retry_config = configured_retry or self._default_retry_config

            # Execute handler with timing, retry, and metrics
            start_time = time.time()
            success = False
            retries = 0

            while retries <= retry_config.max_retries:
                try:
                    handler(event)
                    success = True
                    break
                except Exception as e:  # noqa: BLE001 - intentional broad catch for event handler isolation
                    retries += 1
                    if retries <= retry_config.max_retries:
                        # Calculate backoff delay
                        delay_ms = min(
                            retry_config.base_delay_ms * (2 ** (retries - 1)),
                            retry_config.max_delay_ms,
                        )
                        time.sleep(delay_ms / 1000.0)
                        logger.debug(
                            "Retrying handler %s (attempt %s/%s)",
                            name,
                            retries,
                            retry_config.max_retries,
                        )
                    else:
                        logger.warning(
                            "Handler %s failed after %s retries: %s",
                            name,
                            retry_config.max_retries,
                            e,
                        )
                        self._circuit_breaker.record_failure(name)
                        if METRICS_AVAILABLE:
                            set_circuit_breaker_state(
                                name, not self._circuit_breaker.is_available(name)
                            )

            elapsed_ms = (time.time() - start_time) * 1000

            # Update stats
            if name in self._stats:
                stats = self._stats[name]
                if success:
                    stats.events_processed += 1
                    self._circuit_breaker.record_success(name)
                else:
                    stats.events_failed += 1

                if retries > 0:
                    stats.events_retried += retries

                stats.last_event_time = datetime.now()

                # Update latency stats
                stats.total_latency_ms += elapsed_ms
                stats.min_latency_ms = min(stats.min_latency_ms, elapsed_ms)
                stats.max_latency_ms = max(stats.max_latency_ms, elapsed_ms)

                # Record latency for percentile calculation
                stats.record_latency(elapsed_ms)

            # Record handler metrics
            if METRICS_AVAILABLE:
                record_handler_call(
                    name,
                    "success" if success else "failure",
                    elapsed_ms,
                )

            # Check SLO
            if SLO_METRICS_AVAILABLE:
                check_and_record_slo(
                    f"cross_subscriber_{name}",
                    elapsed_ms,
                    percentile="p99",
                )

    def dispatch_async(self, event: StreamEvent) -> None:
        """Dispatch event asynchronously (adds to batch if batching enabled).

        Args:
            event: The event to dispatch
        """
        if self._async_config.enable_batching and event.type in _default_async_event_types():
            self._add_to_batch(event)
        else:
            self._dispatch_event(event)

    def dispatch(self, event: StreamEvent) -> None:
        """Dispatch event synchronously.

        Args:
            event: The event to dispatch
        """
        self._dispatch_event(event)

    def dispatch_required(self, event: StreamEvent, handler_name: str) -> None:
        """Synchronously deliver an event once to one required named handler.

        Unlike ordinary cross-subscriber dispatch, this safety-critical path
        never samples, retries, or suppresses attempts. The named handler must
        be registered exactly once, enabled, and explicitly confirm delivery
        by returning ``True``.

        Args:
            event: The event to deliver.
            handler_name: Exact registered handler name.

        Raises:
            RuntimeError: If the handler cannot confirm one successful delivery.
        """
        if METRICS_AVAILABLE:
            record_event_dispatched(event.type.value)

        matches = [
            handler
            for name, handler in self._subscribers.get(event.type, [])
            if name == handler_name
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"Required cross-subscriber '{handler_name}' must be registered exactly once "
                f"for {event.type.value}; found {len(matches)}"
            )

        stats = self._stats.get(handler_name)
        if stats is None:
            raise RuntimeError(f"Required cross-subscriber '{handler_name}' has no runtime state")
        if not stats.enabled:
            stats.events_skipped += 1
            raise RuntimeError(f"Required cross-subscriber '{handler_name}' is disabled")

        filter_func = self._filters.get(handler_name)
        if filter_func is not None:
            try:
                accepted = filter_func(event)
            except (RuntimeError, TypeError, AttributeError, ValueError, KeyError) as exc:
                stats.events_failed += 1
                raise RuntimeError(
                    f"Required cross-subscriber '{handler_name}' filter failed"
                ) from exc
            if not accepted:
                stats.events_skipped += 1
                raise RuntimeError(f"Required cross-subscriber '{handler_name}' rejected the event")

        if stats.sample_rate != 1.0:
            stats.events_skipped += 1
            raise RuntimeError(
                f"Required cross-subscriber '{handler_name}' cannot use sampled delivery"
            )

        handler = matches[0]
        start_time = time.time()
        delivery_error: Exception | None = None
        try:
            confirmed = handler(event)
            if confirmed is not True:
                delivery_error = RuntimeError("handler did not confirm delivery")
        except Exception as exc:  # noqa: BLE001 - propagate all delivery failures
            delivery_error = exc

        elapsed_ms = (time.time() - start_time) * 1000
        stats.last_event_time = datetime.now()
        stats.total_latency_ms += elapsed_ms
        stats.min_latency_ms = min(stats.min_latency_ms, elapsed_ms)
        stats.max_latency_ms = max(stats.max_latency_ms, elapsed_ms)
        stats.record_latency(elapsed_ms)

        if delivery_error is None:
            stats.events_processed += 1
            self._circuit_breaker.record_success(handler_name)
        else:
            stats.events_failed += 1
            self._circuit_breaker.record_failure(handler_name)
            if METRICS_AVAILABLE:
                set_circuit_breaker_state(
                    handler_name,
                    not self._circuit_breaker.is_available(handler_name),
                )

        if METRICS_AVAILABLE:
            record_handler_call(
                handler_name,
                "success" if delivery_error is None else "failure",
                elapsed_ms,
            )

        if SLO_METRICS_AVAILABLE:
            check_and_record_slo(
                f"cross_subscriber_{handler_name}",
                elapsed_ms,
                percentile="p99",
            )

        if delivery_error is not None:
            raise RuntimeError(
                f"Required cross-subscriber '{handler_name}' failed to confirm delivery"
            ) from delivery_error

    def _add_to_batch(self, event: StreamEvent) -> None:
        """Add event to batch queue for later processing.

        Args:
            event: The event to batch
        """
        if event.type not in self._event_batch:
            self._event_batch[event.type] = []

        self._event_batch[event.type].append(event)

        # Check if batch should be flushed
        batch = self._event_batch[event.type]
        if len(batch) >= self._async_config.batch_size:
            self._flush_batch(event.type)
        elif time.time() - self._batch_last_flush >= self._async_config.batch_timeout_seconds:
            self._flush_batch(event.type)

    def _flush_batch(self, event_type: StreamEventType) -> None:
        """Flush a batch of events for processing.

        Args:
            event_type: The type of events to flush
        """
        if event_type not in self._event_batch:
            return

        batch = self._event_batch[event_type]
        if not batch:
            return

        # Process all events in batch
        for event in batch:
            self._dispatch_event(event)

        self._event_batch[event_type] = []
        self._batch_last_flush = time.time()

    def flush_all_batches(self) -> int:
        """Flush all pending batches.

        Returns:
            Number of events flushed
        """
        total = 0
        for event_type in list(self._event_batch.keys()):
            batch_size = len(self._event_batch.get(event_type, []))
            self._flush_batch(event_type)
            total += batch_size
        return total

    def get_batch_stats(self) -> dict:
        """Get statistics about current batch queues.

        Returns:
            Dict with batch queue statistics
        """
        return {
            "queues": {
                event_type.value: len(events) for event_type, events in self._event_batch.items()
            },
            "total_pending": sum(len(e) for e in self._event_batch.values()),
            "last_flush": self._batch_last_flush,
            "batch_size": self._async_config.batch_size,
            "timeout_seconds": self._async_config.batch_timeout_seconds,
            "batching_enabled": self._async_config.enable_batching,
            "async_event_types": [e.value for e in _default_async_event_types()],
        }
