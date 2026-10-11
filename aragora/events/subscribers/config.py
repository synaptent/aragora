"""
Configuration dataclasses for cross-subsystem event subscribers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RetryConfig:
    """Configuration for retry behavior on handler failures."""

    max_retries: int = 3
    base_delay_ms: float = 100.0  # Base delay between retries
    max_delay_ms: float = 5000.0  # Maximum delay cap
    exponential_base: float = 2.0  # Exponential backoff multiplier

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for a given retry attempt (0-indexed).

        Uses exponential backoff with jitter: delay = min(base * exp^attempt + jitter, max)
        """
        import random

        delay = self.base_delay_ms * (self.exponential_base**attempt)
        # Add jitter (±20%)
        jitter = delay * 0.2 * (random.random() * 2 - 1)
        delay += jitter
        return min(delay, self.max_delay_ms)


@dataclass
class SubscriberStats:
    """Statistics for a cross-subsystem subscriber."""

    name: str
    events_processed: int = 0
    events_failed: int = 0
    events_skipped: int = 0  # Skipped due to sampling/filtering
    events_retried: int = 0  # Events that required retry
    last_event_time: datetime | None = None
    enabled: bool = True
    sample_rate: float = 1.0  # 1.0 = 100% of events, 0.1 = 10% sampling
    retry_config: RetryConfig | None = None  # Per-handler retry config
    # Latency metrics (in milliseconds)
    total_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    max_latency_ms: float = 0.0
    # Latency histogram buckets (for P50, P90, P99 calculation)
    latency_samples: list = field(default_factory=list)
    max_samples: int = 1000  # Keep last N samples for percentile calculation

    @property
    def avg_latency_ms(self) -> float:
        """Average latency in milliseconds."""
        if self.events_processed == 0:
            return 0.0
        return self.total_latency_ms / self.events_processed

    def record_latency(self, latency_ms: float) -> None:
        """Record a latency sample for percentile calculation."""
        self.latency_samples.append(latency_ms)
        # Maintain bounded sample size
        if len(self.latency_samples) > self.max_samples:
            self.latency_samples = self.latency_samples[-self.max_samples :]

    def get_percentile(self, p: float) -> float | None:
        """Get latency at given percentile (0-100)."""
        if not self.latency_samples:
            return None
        sorted_samples = sorted(self.latency_samples)
        idx = int(len(sorted_samples) * p / 100)
        idx = min(idx, len(sorted_samples) - 1)
        return float(sorted_samples[idx])

    @property
    def p50_latency_ms(self) -> float | None:
        """50th percentile latency."""
        return self.get_percentile(50)

    @property
    def p90_latency_ms(self) -> float | None:
        """90th percentile latency."""
        return self.get_percentile(90)

    @property
    def p99_latency_ms(self) -> float | None:
        """99th percentile latency."""
        return self.get_percentile(99)


@dataclass
class AsyncDispatchConfig:
    """Configuration for async/batched event dispatch."""

    # Event types that should always use async dispatch
    # Note: Set to empty by default, populated at runtime with StreamEventType values
    async_event_types: set = field(default_factory=set)

    # Batch size before auto-flush (0 = no batching)
    batch_size: int = 10

    # Maximum time (seconds) to hold events before flush
    batch_timeout_seconds: float = 1.0

    # Enable batching (groups similar events)
    enable_batching: bool = True
