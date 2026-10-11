"""
Client reconnection protocol for streaming reliability.

Provides ``ReconnectionManager`` which coordinates exponential backoff with
jitter, sequence number tracking, and connection quality scoring for
WebSocket clients reconnecting to the debate stream server.

Usage::

    from aragora.streaming.reconnection import ReconnectionManager

    mgr = ReconnectionManager()
    ctx = mgr.create_context("debate-123")

    while not ctx.exhausted:
        delay = ctx.next_delay()
        await asyncio.sleep(delay)
        try:
            ws = await connect(...)
            ctx.on_connected()
            # Send subscribe with replay
            await ws.send(json.dumps({
                "type": "subscribe",
                "debate_id": "debate-123",
                "replay_from_seq": ctx.last_seen_seq,
            }))
            break
        except ConnectionError:
            ctx.on_failure()
"""

from __future__ import annotations

import logging
import random
import time
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ReconnectionConfig:
    """Configuration for reconnection behaviour.

    Attributes:
        initial_delay: Delay before the first reconnection attempt (seconds).
        max_delay: Maximum backoff delay (seconds).
        max_attempts: Maximum reconnection attempts before giving up.
        backoff_factor: Multiplier for exponential backoff.
        jitter_factor: Random jitter as a fraction of the computed delay.
            E.g. 0.2 means +/- 20% jitter.
    """

    initial_delay: float = 1.0
    max_delay: float = 30.0
    max_attempts: int = 15
    backoff_factor: float = 2.0
    jitter_factor: float = 0.2


@dataclass
class ConnectionQualityScore:
    """Computed connection quality score for a client session.

    Score is in the range [0.0, 1.0] where 1.0 is perfect quality.
    The score degrades with more reconnects and higher latency.
    """

    score: float
    reconnect_penalty: float
    latency_penalty: float
    uptime_ratio: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON transport."""
        return {
            "score": round(self.score, 4),
            "reconnect_penalty": round(self.reconnect_penalty, 4),
            "latency_penalty": round(self.latency_penalty, 4),
            "uptime_ratio": round(self.uptime_ratio, 4),
        }


class ReconnectionContext:
    """Tracks state for a single reconnection sequence.

    Created by ``ReconnectionManager.create_context()``.  Callers should
    use ``next_delay()`` in a retry loop and call ``on_connected()`` /
    ``on_failure()`` to update state.
    """

    def __init__(
        self,
        debate_id: str,
        config: ReconnectionConfig,
    ) -> None:
        self._debate_id = debate_id
        self._config = config
        self._attempt = 0
        self._last_seen_seq: int = 0
        self._connected = False
        self._started_at = time.monotonic()
        self._connected_at: float | None = None
        self._disconnected_at: float = time.monotonic()
        self._total_connected_time: float = 0.0
        self._reconnect_count: int = 0
        self._latency_samples: list[float] = []

    @property
    def debate_id(self) -> str:
        """The debate this context tracks."""
        return self._debate_id

    @property
    def attempt(self) -> int:
        """Current attempt number (0-indexed)."""
        return self._attempt

    @property
    def exhausted(self) -> bool:
        """Whether max attempts have been reached."""
        return self._attempt >= self._config.max_attempts

    @property
    def connected(self) -> bool:
        """Whether the client is currently connected."""
        return self._connected

    @property
    def last_seen_seq(self) -> int:
        """Last sequence number received from the server."""
        return self._last_seen_seq

    @last_seen_seq.setter
    def last_seen_seq(self, value: int) -> None:
        if value > self._last_seen_seq:
            self._last_seen_seq = value

    @property
    def reconnect_count(self) -> int:
        """Total reconnections for this context."""
        return self._reconnect_count

    def next_delay(self) -> float:
        """Compute the delay for the next reconnection attempt.

        Uses exponential backoff with jitter:
            delay = min(initial * factor^attempt, max_delay) +/- jitter
        """
        if self._attempt >= self._config.max_attempts:
            return self._config.max_delay

        delay = self._config.initial_delay * (self._config.backoff_factor**self._attempt)
        delay = min(delay, self._config.max_delay)

        # Apply jitter
        if self._config.jitter_factor > 0:
            jitter_range = delay * self._config.jitter_factor
            delay += random.uniform(-jitter_range, jitter_range)
            delay = max(0.0, delay)

        self._attempt += 1
        return delay

    def on_connected(self) -> None:
        """Called when the connection is successfully established."""
        self._connected = True
        now = time.monotonic()
        self._connected_at = now
        if self._attempt > 1:
            self._reconnect_count += 1

        logger.info(
            "[Reconnect] Connected to %s after %d attempt(s)",
            self._debate_id,
            self._attempt,
        )

    def on_failure(self) -> None:
        """Called when a reconnection attempt fails."""
        self._connected = False
        logger.debug(
            "[Reconnect] Attempt %d/%d failed for %s",
            self._attempt,
            self._config.max_attempts,
            self._debate_id,
        )

    def on_disconnected(self) -> None:
        """Called when the connection is lost (before reconnection)."""
        now = time.monotonic()
        if self._connected and self._connected_at is not None:
            self._total_connected_time += now - self._connected_at
        self._connected = False
        self._disconnected_at = now
        self._attempt = 0  # Reset attempts for new reconnection cycle

    def record_latency(self, latency_ms: float) -> None:
        """Record a round-trip latency measurement."""
        self._latency_samples.append(latency_ms)
        # Keep bounded
        if len(self._latency_samples) > 100:
            self._latency_samples = self._latency_samples[-100:]

    def get_quality_score(self) -> ConnectionQualityScore:
        """Compute a connection quality score.

        The score is based on:
        - Reconnect frequency: more reconnects = lower score
        - Average latency: higher latency = lower score
        - Uptime ratio: time connected vs total time
        """
        now = time.monotonic()
        total_time = now - self._started_at
        connected_time = self._total_connected_time
        if self._connected and self._connected_at is not None:
            connected_time += now - self._connected_at

        # Uptime ratio
        uptime_ratio = connected_time / total_time if total_time > 0 else 1.0

        # Reconnect penalty: each reconnect reduces score
        # 0 reconnects = 0 penalty, 5 reconnects = 0.5 penalty, 10+ = 1.0
        reconnect_penalty = min(1.0, self._reconnect_count / 10.0)

        # Latency penalty: p95 > 200ms starts penalizing
        latency_penalty = 0.0
        if self._latency_samples:
            sorted_samples = sorted(self._latency_samples)
            p95_idx = int(len(sorted_samples) * 0.95)
            p95 = sorted_samples[min(p95_idx, len(sorted_samples) - 1)]
            if p95 > 200.0:
                # Linear penalty from 200ms to 2000ms
                latency_penalty = min(1.0, (p95 - 200.0) / 1800.0)

        # Composite score
        score = max(
            0.0,
            uptime_ratio * (1.0 - reconnect_penalty * 0.3) * (1.0 - latency_penalty * 0.3),
        )

        return ConnectionQualityScore(
            score=score,
            reconnect_penalty=reconnect_penalty,
            latency_penalty=latency_penalty,
            uptime_ratio=uptime_ratio,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize context state for diagnostics."""
        quality = self.get_quality_score()
        return {
            "debate_id": self._debate_id,
            "attempt": self._attempt,
            "max_attempts": self._config.max_attempts,
            "exhausted": self.exhausted,
            "connected": self._connected,
            "last_seen_seq": self._last_seen_seq,
            "reconnect_count": self._reconnect_count,
            "quality": quality.to_dict(),
        }


class ReconnectionManager:
    """Manages reconnection contexts for multiple debates.

    Thread-safe.  Each debate gets its own ``ReconnectionContext``
    with independent backoff state.

    Example::

        mgr = ReconnectionManager()
        ctx = mgr.create_context("debate-abc")
        # ... use ctx in reconnection loop ...
        mgr.remove_context("debate-abc")
    """

    def __init__(
        self,
        config: ReconnectionConfig | None = None,
    ) -> None:
        self._config = config or ReconnectionConfig()
        self._contexts: dict[str, ReconnectionContext] = {}
        self._lock = threading.Lock()

    @property
    def config(self) -> ReconnectionConfig:
        """Active configuration."""
        return self._config

    def create_context(self, debate_id: str) -> ReconnectionContext:
        """Create or retrieve a reconnection context for *debate_id*."""
        with self._lock:
            if debate_id not in self._contexts:
                self._contexts[debate_id] = ReconnectionContext(
                    debate_id=debate_id,
                    config=self._config,
                )
            return self._contexts[debate_id]

    def get_context(self, debate_id: str) -> ReconnectionContext | None:
        """Return existing context or ``None``."""
        with self._lock:
            return self._contexts.get(debate_id)

    def remove_context(self, debate_id: str) -> None:
        """Remove a context for a finished debate."""
        with self._lock:
            self._contexts.pop(debate_id, None)

    def get_all_quality_scores(self) -> dict[str, ConnectionQualityScore]:
        """Return quality scores for all active contexts."""
        with self._lock:
            contexts = list(self._contexts.items())
        return {did: ctx.get_quality_score() for did, ctx in contexts}

    def get_summary(self) -> dict[str, Any]:
        """Return a summary of all reconnection contexts."""
        with self._lock:
            contexts = list(self._contexts.values())
        return {
            "active_contexts": len(contexts),
            "total_reconnects": sum(c.reconnect_count for c in contexts),
            "exhausted_count": sum(1 for c in contexts if c.exhausted),
            "connected_count": sum(1 for c in contexts if c.connected),
        }

    def clear(self) -> None:
        """Remove all contexts."""
        with self._lock:
            self._contexts.clear()


__all__ = [
    "ConnectionQualityScore",
    "ReconnectionConfig",
    "ReconnectionContext",
    "ReconnectionManager",
]
