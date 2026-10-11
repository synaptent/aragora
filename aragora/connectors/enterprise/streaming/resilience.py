"""
Streaming Connector Resilience Patterns.

Provides production-ready resilience patterns for Kafka and RabbitMQ connectors:
- Exponential backoff retry for connection failures
- Circuit breaker for broker failures
- Dead Letter Queue (DLQ) handling for failed messages
- Graceful shutdown handling
- Health monitoring

Usage:
    from aragora.connectors.enterprise.streaming.resilience import (
        StreamingResilienceConfig,
        ExponentialBackoff,
        StreamingCircuitBreaker,
        DLQHandler,
    )

    # Configure resilience
    config = StreamingResilienceConfig(
        max_retries=5,
        initial_delay_seconds=1.0,
        circuit_breaker_threshold=5,
    )

    # Use backoff for connection retry
    backoff = ExponentialBackoff(config)
    async for delay in backoff:
        try:
            await connect()
            break
        except ConnectionError:
            await asyncio.sleep(delay)

    # Use circuit breaker for broker calls
    async with circuit_breaker.call():
        await send_message(msg)

    # Handle failed messages with DLQ
    await dlq_handler.send_to_dlq(failed_message, error)
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar
from collections.abc import AsyncIterator, Awaitable, Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class StreamingResilienceConfig:
    """Configuration for streaming connector resilience."""

    # Retry settings
    max_retries: int = 5
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True  # Add randomness to prevent thundering herd

    # Circuit breaker settings
    circuit_breaker_threshold: int = 5  # Failures before opening
    circuit_breaker_recovery_seconds: float = 30.0
    circuit_breaker_half_open_calls: int = 3
    circuit_breaker_success_threshold: int = 2

    # DLQ settings
    dlq_enabled: bool = True
    dlq_max_retries: int = 3  # Retries before sending to DLQ
    dlq_include_metadata: bool = True  # Include error details in DLQ message
    dlq_topic_suffix: str = ".dlq"  # Suffix for DLQ topics/queues

    # Timeout settings
    connection_timeout_seconds: float = 30.0
    operation_timeout_seconds: float = 10.0

    # Health monitoring
    health_check_interval_seconds: float = 30.0
    unhealthy_threshold: int = 3  # Consecutive failures before unhealthy

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.initial_delay_seconds <= 0:
            raise ValueError("initial_delay_seconds must be positive")
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError("max_delay_seconds must be >= initial_delay_seconds")
        if self.circuit_breaker_threshold < 1:
            raise ValueError("circuit_breaker_threshold must be >= 1")


# =============================================================================
# Exponential Backoff
# =============================================================================


class ExponentialBackoff:
    """
    Exponential backoff with jitter for retry operations.

    Implements the "decorrelated jitter" algorithm for optimal retry distribution.

    Usage:
        backoff = ExponentialBackoff(config)

        for attempt in range(config.max_retries + 1):
            try:
                await connect()
                break
            except ConnectionError as e:
                if attempt == config.max_retries:
                    raise
                delay = backoff.get_delay(attempt)
                await asyncio.sleep(delay)
    """

    def __init__(self, config: StreamingResilienceConfig | None = None):
        """Initialize backoff with configuration."""
        self.config = config or StreamingResilienceConfig()
        self._attempt = 0
        self._last_delay = self.config.initial_delay_seconds

    def get_delay(self, attempt: int) -> float:
        """
        Calculate delay for a given attempt.

        Uses decorrelated jitter for better distribution:
        delay = min(max_delay, random_between(base, last_delay * 3))

        Args:
            attempt: Zero-based attempt number

        Returns:
            Delay in seconds
        """
        import random

        if attempt == 0:
            base_delay = self.config.initial_delay_seconds
        else:
            base_delay = self.config.initial_delay_seconds * (self.config.exponential_base**attempt)

        # Cap at max delay
        delay = min(base_delay, self.config.max_delay_seconds)

        # Add jitter (±25%)
        if self.config.jitter:
            jitter_range = delay * 0.25
            delay = delay + random.uniform(-jitter_range, jitter_range)  # noqa: S311 -- retry jitter
            delay = max(self.config.initial_delay_seconds, delay)

        self._last_delay = delay
        return delay

    def reset(self) -> None:
        """Reset backoff state."""
        self._attempt = 0
        self._last_delay = self.config.initial_delay_seconds

    async def __aiter__(self) -> AsyncIterator[float]:
        """
        Async iterator for retry delays.

        Yields delays until max_retries is reached.
        """
        for attempt in range(self.config.max_retries + 1):
            self._attempt = attempt
            yield self.get_delay(attempt)


# =============================================================================
# Circuit Breaker
# =============================================================================


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests allowed
    OPEN = "open"  # Failing, requests rejected
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and rejecting calls."""

    def __init__(self, name: str, recovery_time: float):
        self.name = name
        self.recovery_time = recovery_time
        super().__init__(
            f"Circuit breaker '{name}' is open. Recovery in {recovery_time:.1f} seconds."
        )


class StreamingCircuitBreaker:
    """
    Circuit breaker for streaming connector operations.

    Prevents cascading failures by stopping calls when failure rate is high.
    Transitions through states:
    - CLOSED: Normal operation, counting failures
    - OPEN: Rejecting all calls, waiting for recovery timeout
    - HALF_OPEN: Testing recovery with limited calls

    Usage:
        breaker = StreamingCircuitBreaker("kafka-broker")

        async def send_message(msg):
            async with breaker.call():
                await broker.send(msg)

        # Or check state manually
        if breaker.can_execute():
            try:
                await send_message(msg)
                await breaker.record_success()
            except (ConnectionError, OSError, RuntimeError, TimeoutError) as e:
                await breaker.record_failure(e)
    """

    def __init__(
        self,
        name: str,
        config: StreamingResilienceConfig | None = None,
    ):
        """Initialize circuit breaker."""
        self.name = name
        self.config = config or StreamingResilienceConfig()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

        # Metrics
        self._total_calls = 0
        self._total_failures = 0
        self._total_successes = 0
        self._state_changes: list[tuple[datetime, CircuitState, CircuitState]] = []

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking calls)."""
        return self._state == CircuitState.OPEN

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count

    def _time_until_recovery(self) -> float:
        """Get seconds until recovery timeout."""
        if self._last_failure_time is None:
            return 0.0
        elapsed = time.time() - self._last_failure_time
        remaining = self.config.circuit_breaker_recovery_seconds - elapsed
        return max(0.0, remaining)

    async def can_execute(self) -> bool:
        """
        Check if a call can be executed.

        Returns True if the call is allowed, False if rejected.
        Handles state transitions automatically.
        """
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has elapsed
                if self._time_until_recovery() <= 0:
                    self._transition_to(CircuitState.HALF_OPEN)
                    self._half_open_calls = 1
                    return True
                return False

            if self._state == CircuitState.HALF_OPEN:
                # Allow limited calls in half-open state
                if self._half_open_calls < self.config.circuit_breaker_half_open_calls:
                    self._half_open_calls += 1
                    return True
                return False

            return False

    async def record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            self._total_calls += 1
            self._total_successes += 1
            self._success_count += 1

            if self._state == CircuitState.HALF_OPEN:
                if self._success_count >= self.config.circuit_breaker_success_threshold:
                    self._transition_to(CircuitState.CLOSED)
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    async def record_failure(self, error: Exception | None = None) -> None:
        """Record a failed call."""
        async with self._lock:
            self._total_calls += 1
            self._total_failures += 1
            self._failure_count += 1
            self._success_count = 0
            self._last_failure_time = time.time()

            if error:
                logger.warning(
                    "[CircuitBreaker:%s] Failure #%s: %s", self.name, self._failure_count, error
                )

            if self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.circuit_breaker_threshold:
                    self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open returns to open
                self._transition_to(CircuitState.OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old_state = self._state
        self._state = new_state
        self._state_changes.append((datetime.now(timezone.utc), old_state, new_state))

        logger.info(
            "[CircuitBreaker:%s] State transition: %s -> %s",
            self.name,
            old_state.value,
            new_state.value,
        )

        # Reset counters on state change
        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._success_count = 0

    async def call(self) -> CircuitBreakerContext:
        """
        Context manager for protected calls.

        Usage:
            async with breaker.call():
                await do_operation()

        Raises:
            CircuitBreakerOpenError: If circuit is open
        """
        if not await self.can_execute():
            raise CircuitBreakerOpenError(
                self.name,
                self._time_until_recovery(),
            )
        return CircuitBreakerContext(self)

    def reset(self) -> None:
        """Reset circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time = None
        logger.info("[CircuitBreaker:%s] Reset to CLOSED", self.name)

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "time_until_recovery": (
                self._time_until_recovery() if self._state == CircuitState.OPEN else 0
            ),
            "state_changes": len(self._state_changes),
        }


class CircuitBreakerContext:
    """Context manager for circuit breaker protected calls."""

    def __init__(self, breaker: StreamingCircuitBreaker):
        self._breaker = breaker
        self._entered = False

    async def __aenter__(self) -> CircuitBreakerContext:
        self._entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        if exc_type is None:
            await self._breaker.record_success()
        else:
            await self._breaker.record_failure(exc_val if isinstance(exc_val, Exception) else None)
        return False  # Don't suppress exceptions


# =============================================================================
# Dead Letter Queue Handler
# =============================================================================


@dataclass
class DLQMessage:
    """A message destined for the dead letter queue."""

    original_topic: str
    original_key: str | None
    original_value: Any
    original_headers: dict[str, str]
    original_timestamp: datetime

    error_message: str
    error_type: str
    retry_count: int
    failed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "original_topic": self.original_topic,
            "original_key": self.original_key,
            "original_value": self.original_value,
            "original_headers": self.original_headers,
            "original_timestamp": self.original_timestamp.isoformat(),
            "error_message": self.error_message,
            "error_type": self.error_type,
            "retry_count": self.retry_count,
            "failed_at": self.failed_at.isoformat(),
        }

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DLQMessage:
        """Create from dictionary."""
        return cls(
            original_topic=data["original_topic"],
            original_key=data.get("original_key"),
            original_value=data["original_value"],
            original_headers=data.get("original_headers", {}),
            original_timestamp=datetime.fromisoformat(data["original_timestamp"]),
            error_message=data["error_message"],
            error_type=data["error_type"],
            retry_count=data["retry_count"],
            failed_at=datetime.fromisoformat(data["failed_at"]),
        )


class DLQHandler(Generic[T]):
    """
    Dead Letter Queue handler for failed messages.

    Provides a consistent interface for sending failed messages to a DLQ
    with error metadata for debugging and reprocessing.

    Usage:
        # Define a DLQ sender function
        async def send_to_kafka_dlq(topic: str, message: DLQMessage) -> None:
            await kafka_producer.send(topic, message.to_json())

        dlq_handler = DLQHandler(
            config=StreamingResilienceConfig(),
            dlq_sender=send_to_kafka_dlq,
        )

        try:
            await process_message(msg)
        except (ConnectionError, RuntimeError, TimeoutError, TypeError, ValueError) as e:
            await dlq_handler.handle_failure(msg, e)
    """

    def __init__(
        self,
        config: StreamingResilienceConfig | None = None,
        dlq_sender: Callable[[str, DLQMessage], Awaitable[None]] | None = None,
        on_dlq_send: Callable[[DLQMessage], Awaitable[None]] | None = None,
    ):
        """
        Initialize DLQ handler.

        Args:
            config: Resilience configuration
            dlq_sender: Async function to send messages to DLQ
            on_dlq_send: Callback when message is sent to DLQ
        """
        self.config = config or StreamingResilienceConfig()
        self._dlq_sender = dlq_sender
        self._on_dlq_send = on_dlq_send
        self._retry_counts: dict[str, int] = {}  # message_id -> retry_count

        # Metrics
        self._total_messages = 0
        self._total_retries = 0
        self._total_dlq_sends = 0

    def get_message_id(
        self,
        topic: str,
        key: str | None,
        offset: int | None = None,
        delivery_tag: int | None = None,
    ) -> str:
        """Generate a unique message ID for retry tracking."""
        parts = [topic]
        if key:
            parts.append(key)
        if offset is not None:
            parts.append(str(offset))
        if delivery_tag is not None:
            parts.append(str(delivery_tag))
        return ":".join(parts)

    def get_retry_count(self, message_id: str) -> int:
        """Get the current retry count for a message."""
        return self._retry_counts.get(message_id, 0)

    def increment_retry(self, message_id: str) -> int:
        """Increment and return the retry count for a message."""
        count = self._retry_counts.get(message_id, 0) + 1
        self._retry_counts[message_id] = count
        self._total_retries += 1
        return count

    def clear_retry(self, message_id: str) -> None:
        """Clear retry count for a successfully processed message."""
        self._retry_counts.pop(message_id, None)

    async def should_send_to_dlq(self, message_id: str) -> bool:
        """Check if a message should be sent to DLQ based on retry count."""
        if not self.config.dlq_enabled:
            return False
        return self.get_retry_count(message_id) >= self.config.dlq_max_retries

    async def handle_failure(
        self,
        topic: str,
        key: str | None,
        value: Any,
        headers: dict[str, str],
        timestamp: datetime,
        error: Exception,
        offset: int | None = None,
        delivery_tag: int | None = None,
    ) -> bool:
        """
        Handle a message processing failure.

        Returns True if message was sent to DLQ, False if it should be retried.

        Args:
            topic: Original topic/queue name
            key: Message key
            value: Message value
            headers: Message headers
            timestamp: Original message timestamp
            error: The exception that caused the failure
            offset: Kafka offset (optional)
            delivery_tag: RabbitMQ delivery tag (optional)

        Returns:
            True if sent to DLQ, False if should retry
        """
        self._total_messages += 1

        message_id = self.get_message_id(topic, key, offset, delivery_tag)
        retry_count = self.increment_retry(message_id)

        if retry_count < self.config.dlq_max_retries:
            logger.warning(
                "[DLQ] Message %s failed (attempt %s/%s): %s",
                message_id,
                retry_count,
                self.config.dlq_max_retries,
                error,
            )
            return False

        # Max retries exceeded, send to DLQ
        await self.send_to_dlq(
            topic=topic,
            key=key,
            value=value,
            headers=headers,
            timestamp=timestamp,
            error=error,
            retry_count=retry_count,
        )

        # Clear retry count after DLQ
        self.clear_retry(message_id)
        return True

    async def send_to_dlq(
        self,
        topic: str,
        key: str | None,
        value: Any,
        headers: dict[str, str],
        timestamp: datetime,
        error: Exception,
        retry_count: int = 0,
    ) -> None:
        """
        Send a message directly to the DLQ.

        Args:
            topic: Original topic/queue name
            key: Message key
            value: Message value
            headers: Message headers
            timestamp: Original message timestamp
            error: The exception that caused the failure
            retry_count: Number of retry attempts
        """
        if not self.config.dlq_enabled:
            logger.warning("[DLQ] DLQ disabled, dropping failed message from %s", topic)
            return

        dlq_topic = topic + self.config.dlq_topic_suffix

        dlq_message = DLQMessage(
            original_topic=topic,
            original_key=key,
            original_value=value,
            original_headers=headers,
            original_timestamp=timestamp,
            error_message=str(error),
            error_type=type(error).__name__,
            retry_count=retry_count,
        )

        self._total_dlq_sends += 1

        if self._dlq_sender:
            try:
                await self._dlq_sender(dlq_topic, dlq_message)
                logger.info("[DLQ] Sent message to %s", dlq_topic)
            except (OSError, RuntimeError, ConnectionError, TimeoutError) as send_error:
                logger.error("[DLQ] Failed to send to %s: %s", dlq_topic, send_error)
                raise
        else:
            logger.warning(
                "[DLQ] No sender configured, logging failed message: %s", dlq_message.to_dict()
            )

        if self._on_dlq_send:
            try:
                await self._on_dlq_send(dlq_message)
            except (RuntimeError, ValueError, TypeError) as callback_error:
                logger.warning("[DLQ] Callback error: %s", callback_error)

    def get_stats(self) -> dict[str, Any]:
        """Get DLQ handler statistics."""
        return {
            "enabled": self.config.dlq_enabled,
            "max_retries": self.config.dlq_max_retries,
            "total_messages": self._total_messages,
            "total_retries": self._total_retries,
            "total_dlq_sends": self._total_dlq_sends,
            "pending_retries": len(self._retry_counts),
        }


# =============================================================================
# Graceful Shutdown Handler
# =============================================================================


class GracefulShutdown:
    """
    Handler for graceful shutdown on SIGTERM/SIGINT.

    Allows connectors to cleanly disconnect and finish processing
    before the process exits.

    Usage:
        shutdown = GracefulShutdown()

        async def cleanup():
            await connector.disconnect()
            await connector.flush()

        shutdown.register_cleanup(cleanup)

        # In your main loop
        while not shutdown.is_shutting_down:
            await process_messages()
    """

    def __init__(self) -> None:
        """Initialize shutdown handler."""
        self._shutting_down = False
        self._cleanup_tasks: list[Callable[[], Awaitable[None]]] = []
        self._shutdown_event = asyncio.Event()
        self._setup_done = False

    @property
    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress."""
        return self._shutting_down

    def setup_signal_handlers(self) -> None:
        """
        Set up signal handlers for graceful shutdown.

        Call this from your main async context.
        """
        if self._setup_done:
            return

        loop = asyncio.get_running_loop()

        def signal_handler(sig: signal.Signals) -> None:
            logger.info("Received %s, initiating graceful shutdown...", sig.name)
            self._shutting_down = True
            self._shutdown_event.set()
            # Schedule cleanup
            asyncio.create_task(self._run_cleanup())

        try:
            loop.add_signal_handler(signal.SIGTERM, lambda: signal_handler(signal.SIGTERM))
            loop.add_signal_handler(signal.SIGINT, lambda: signal_handler(signal.SIGINT))
            self._setup_done = True
            logger.debug("Signal handlers registered for graceful shutdown")
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            logger.warning("Signal handlers not supported on this platform")

    def register_cleanup(self, cleanup_fn: Callable[[], Awaitable[None]]) -> None:
        """Register a cleanup function to run on shutdown."""
        self._cleanup_tasks.append(cleanup_fn)

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown signal."""
        await self._shutdown_event.wait()

    async def _run_cleanup(self) -> None:
        """Run all registered cleanup tasks."""
        logger.info("Running %s cleanup tasks...", len(self._cleanup_tasks))

        for i, cleanup_fn in enumerate(self._cleanup_tasks):
            try:
                result = asyncio.wait_for(cleanup_fn(), timeout=30.0)
                if inspect.isawaitable(result):
                    try:
                        await result
                    except TypeError:
                        # Handle mocked wait_for returning non-awaitable AsyncMock.
                        if callable(result):
                            inner = result()
                            if inspect.isawaitable(inner):
                                await inner
                logger.debug("Cleanup task %s/%s completed", i + 1, len(self._cleanup_tasks))
            except asyncio.TimeoutError:
                logger.warning("Cleanup task %s timed out", i + 1)
            except (RuntimeError, OSError, ValueError, ConnectionError) as e:
                logger.error("Cleanup task %s failed: %s", i + 1, e)

        logger.info("All cleanup tasks completed")

    def trigger_shutdown(self) -> None:
        """Manually trigger shutdown (for testing)."""
        self._shutting_down = True
        self._shutdown_event.set()


# =============================================================================
# Health Monitor
# =============================================================================


@dataclass
class HealthStatus:
    """Health status for a streaming connector."""

    healthy: bool
    last_check: datetime
    consecutive_failures: int = 0
    last_error: str | None = None
    latency_ms: float | None = None
    messages_processed: int = 0
    messages_failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "healthy": self.healthy,
            "last_check": self.last_check.isoformat(),
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "latency_ms": self.latency_ms,
            "messages_processed": self.messages_processed,
            "messages_failed": self.messages_failed,
        }


class HealthMonitor:
    """
    Health monitor for streaming connectors.

    Tracks connection health and provides liveness probes.

    Usage:
        monitor = HealthMonitor("kafka-consumer", config)

        # Record operations
        await monitor.record_success(latency_ms=15.5)
        await monitor.record_failure(error)

        # Check health
        status = await monitor.get_status()
        if not status.healthy:
            await reconnect()
    """

    def __init__(
        self,
        name: str,
        config: StreamingResilienceConfig | None = None,
    ):
        """Initialize health monitor."""
        self.name = name
        self.config = config or StreamingResilienceConfig()

        self._healthy = True
        self._consecutive_failures = 0
        self._last_error: str | None = None
        self._last_latency_ms: float | None = None
        self._messages_processed = 0
        self._messages_failed = 0
        self._last_check = datetime.now(timezone.utc)
        self._lock = asyncio.Lock()

    async def record_success(self, latency_ms: float | None = None) -> None:
        """Record a successful operation."""
        async with self._lock:
            self._consecutive_failures = 0
            self._healthy = True
            self._last_latency_ms = latency_ms
            self._messages_processed += 1
            self._last_check = datetime.now(timezone.utc)

    async def record_failure(self, error: Exception | str) -> None:
        """Record a failed operation."""
        async with self._lock:
            self._consecutive_failures += 1
            self._messages_failed += 1
            self._last_error = str(error)
            self._last_check = datetime.now(timezone.utc)

            if self._consecutive_failures >= self.config.unhealthy_threshold:
                self._healthy = False
                logger.warning(
                    "[HealthMonitor:%s] Marked unhealthy after %s consecutive failures",
                    self.name,
                    self._consecutive_failures,
                )

    async def get_status(self) -> HealthStatus:
        """Get current health status."""
        async with self._lock:
            return HealthStatus(
                healthy=self._healthy,
                last_check=self._last_check,
                consecutive_failures=self._consecutive_failures,
                last_error=self._last_error,
                latency_ms=self._last_latency_ms,
                messages_processed=self._messages_processed,
                messages_failed=self._messages_failed,
            )

    async def reset(self) -> None:
        """Reset health monitor to healthy state."""
        async with self._lock:
            self._healthy = True
            self._consecutive_failures = 0
            self._last_error = None
            logger.info("[HealthMonitor:%s] Reset to healthy", self.name)


# =============================================================================
# Retry Decorator
# =============================================================================


def with_retry(
    config: StreamingResilienceConfig | None = None,
    retryable_exceptions: tuple[type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        OSError,
    ),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator for retrying async functions with exponential backoff.

    Usage:
        @with_retry(config=my_config)
        async def connect_to_broker():
            return await kafka.connect()
    """
    cfg = config or StreamingResilienceConfig()

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            backoff = ExponentialBackoff(cfg)
            last_error: Exception | None = None
            handled_exceptions = tuple(
                exc for exc in retryable_exceptions if exc not in (Exception, BaseException)
            )

            if not handled_exceptions:
                raise ValueError(
                    "retryable_exceptions must include at least one specific exception type"
                )

            for attempt in range(cfg.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except handled_exceptions as e:
                    last_error = e
                    if attempt == cfg.max_retries:
                        logger.error(
                            "[Retry] %s failed after %s attempts: %s", func.__name__, attempt + 1, e
                        )
                        raise

                    delay = backoff.get_delay(attempt)
                    logger.warning(
                        "[Retry] %s attempt %s/%s failed: %s. Retrying in %.2fs",
                        func.__name__,
                        attempt + 1,
                        cfg.max_retries + 1,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)

            # Should not reach here
            if last_error:
                raise last_error
            raise RuntimeError("Retry loop exited unexpectedly")

        return wrapper

    return decorator


__all__ = [
    # Configuration
    "StreamingResilienceConfig",
    # Backoff
    "ExponentialBackoff",
    # Circuit Breaker
    "CircuitState",
    "CircuitBreakerOpenError",
    "StreamingCircuitBreaker",
    "CircuitBreakerContext",
    # DLQ
    "DLQMessage",
    "DLQHandler",
    # Shutdown
    "GracefulShutdown",
    # Health
    "HealthStatus",
    "HealthMonitor",
    # Decorator
    "with_retry",
]
