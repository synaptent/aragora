"""
Event emitter and audience participation classes.

Provides the SyncEventEmitter which bridges synchronous Arena code with
async WebSocket broadcasts, along with audience participation classes
for user votes and suggestions.
"""

import logging
import os
import queue
import threading
import time
from collections import deque
from typing import Any
from collections.abc import Callable

from aragora.config import MAX_EVENT_QUEUE_SIZE
from aragora.events.types import (
    AudienceMessage,
    StreamEvent,
    StreamEventType,
)
from aragora.storage.receipt_signing import (
    SignedReceipt,
    set_receipt_verification_observer,
)

logger = logging.getLogger(__name__)


def normalize_intensity(value: Any, default: int = 5, min_val: int = 1, max_val: int = 10) -> int:
    """
    Safely normalize vote intensity to a clamped integer.

    Args:
        value: Raw intensity value from user input (may be string, float, None, etc.)
        default: Default intensity if value is invalid
        min_val: Minimum allowed intensity
        max_val: Maximum allowed intensity

    Returns:
        Clamped integer intensity between min_val and max_val
    """
    if value is None:
        return default

    try:
        intensity = int(float(value))
    except (ValueError, TypeError):
        return default

    return max(min_val, min(max_val, intensity))


class TokenBucket:
    """
    Token bucket rate limiter for audience message throttling.

    Allows burst traffic up to burst_size, then limits to rate_per_minute.
    Thread-safe for concurrent access.
    """

    def __init__(self, rate_per_minute: float, burst_size: int):
        """
        Initialize token bucket.

        Args:
            rate_per_minute: Token refill rate (tokens per minute)
            burst_size: Maximum tokens (bucket capacity)
        """
        self.rate_per_minute = rate_per_minute
        self.burst_size = burst_size
        self.tokens = float(burst_size)  # Start full
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        """
        Attempt to consume tokens from the bucket.

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens were available and consumed, False otherwise
        """
        with self._lock:
            # Refill tokens based on elapsed time
            now = time.monotonic()
            elapsed_minutes = (now - self.last_refill) / 60.0
            refill_amount = elapsed_minutes * self.rate_per_minute
            self.tokens = min(self.burst_size, self.tokens + refill_amount)
            self.last_refill = now

            # Try to consume
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


class AudienceInbox:
    """
    Thread-safe queue for audience messages.

    Collects votes and suggestions from WebSocket clients for processing
    by the debate arena.

    Uses a bounded deque to prevent unbounded memory growth under spam.
    Maximum size is configurable via ARAGORA_AUDIENCE_INBOX_MAX_SIZE env var.
    """

    # Maximum messages to retain (prevents memory exhaustion under spam)
    # Configurable via environment variable
    MAX_MESSAGES = int(os.environ.get("ARAGORA_AUDIENCE_INBOX_MAX_SIZE", "1000"))

    def __init__(self, max_messages: int | None = None):
        """
        Initialize audience inbox.

        Args:
            max_messages: Maximum messages to retain (defaults to MAX_MESSAGES)
        """
        max_size = max_messages if max_messages is not None else self.MAX_MESSAGES
        self._messages: deque[AudienceMessage] = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._overflow_count = 0  # Track dropped messages for monitoring

    def put(self, message: AudienceMessage) -> None:
        """Add a message to the inbox (thread-safe).

        If the inbox is at capacity, the oldest message is automatically dropped.
        """
        with self._lock:
            was_full = len(self._messages) == self._messages.maxlen
            self._messages.append(message)
            if was_full:
                self._overflow_count += 1
                if self._overflow_count % 100 == 1:  # Log every 100 drops
                    logger.warning(
                        "[audience] Inbox overflow, dropping old messages (total dropped: %s)",
                        self._overflow_count,
                    )

    def get_all(self) -> list[AudienceMessage]:
        """
        Drain all messages from the inbox (thread-safe).

        Returns:
            List of all queued messages, emptying the inbox
        """
        with self._lock:
            messages = list(self._messages)
            self._messages.clear()
            return messages

    def get_summary(self, loop_id: str | None = None) -> dict:
        """
        Get a summary of current inbox state without draining.

        Args:
            loop_id: Optional loop ID to filter messages by (multi-tenant support)

        Returns:
            Dict with vote counts, suggestions, histograms, and conviction distribution
        """
        with self._lock:
            votes: dict[str, int] = {}
            suggestions = 0
            # Per-choice intensity histograms: {choice: {intensity: count}}
            histograms: dict[str, dict[int, int]] = {}
            # Global conviction distribution: {intensity: count}
            conviction_distribution: dict[int, int] = {i: 0 for i in range(1, 11)}

            for msg in self._messages:
                # Filter by loop_id if provided
                if loop_id and msg.loop_id != loop_id:
                    continue

                if msg.type == "vote":
                    choice = msg.payload.get("choice", "unknown")
                    intensity = normalize_intensity(msg.payload.get("intensity"))

                    # Basic vote count
                    votes[choice] = votes.get(choice, 0) + 1

                    # Per-choice histogram
                    if choice not in histograms:
                        histograms[choice] = {i: 0 for i in range(1, 11)}
                    histograms[choice][intensity] = histograms[choice].get(intensity, 0) + 1

                    # Global conviction distribution
                    conviction_distribution[intensity] = (
                        conviction_distribution.get(intensity, 0) + 1
                    )

                elif msg.type == "suggestion":
                    suggestions += 1

            # Calculate weighted votes using intensity
            weighted_votes = {}
            for choice, histogram in histograms.items():
                weighted_sum = sum(
                    count * (0.5 + (intensity - 1) * 0.1667)  # Linear scale: 1->0.5, 10->2.0
                    for intensity, count in histogram.items()
                )
                weighted_votes[choice] = round(weighted_sum, 2)

            return {
                "votes": votes,
                "weighted_votes": weighted_votes,
                "suggestions": suggestions,
                "total": len(self._messages) if not loop_id else sum(votes.values()) + suggestions,
                "histograms": histograms,
                "conviction_distribution": conviction_distribution,
            }

    def drain_suggestions(self, loop_id: str | None = None) -> list[dict]:
        """
        Drain and return all suggestion messages, optionally filtered by loop_id.

        Args:
            loop_id: Optional loop ID to filter suggestions by

        Returns:
            List of suggestion payloads
        """
        with self._lock:
            suggestions = []
            remaining = []

            for msg in self._messages:
                # Filter by loop_id if provided
                if loop_id and msg.loop_id != loop_id:
                    remaining.append(msg)
                    continue

                if msg.type == "suggestion":
                    suggestions.append(msg.payload)
                else:
                    remaining.append(msg)

            # Clear and repopulate the deque to preserve maxlen
            self._messages.clear()
            self._messages.extend(remaining)
            return suggestions

    def peek_suggestions(self, loop_id: str | None = None) -> list[dict]:
        """
        Return suggestion messages without removing them from the inbox.

        Args:
            loop_id: Optional loop ID to filter suggestions by

        Returns:
            List of suggestion payloads
        """
        with self._lock:
            suggestions = []

            for msg in self._messages:
                if loop_id and msg.loop_id != loop_id:
                    continue
                if msg.type == "suggestion":
                    suggestions.append(msg.payload)

            return suggestions


class SyncEventEmitter:
    """
    Thread-safe event emitter bridging sync Arena code with async WebSocket.

    Events are queued synchronously via emit() and consumed by async drain().
    This pattern avoids needing to rewrite Arena to be fully async.

    Sequence numbers are automatically assigned to enable:
    - Global ordering (seq) for detecting message reordering
    - Per-agent ordering (agent_seq) for token stream integrity
    """

    # Maximum queue size to prevent memory exhaustion (DoS protection)
    # Configurable via ARAGORA_MAX_EVENT_QUEUE_SIZE environment variable
    MAX_QUEUE_SIZE = MAX_EVENT_QUEUE_SIZE

    def __init__(self, loop_id: str = ""):
        # Use bounded queue - maxsize=10000 prevents unbounded memory growth
        # A bounded queue's put() can block, but we use put_nowait() which never blocks
        self._queue: queue.Queue[StreamEvent] = queue.Queue(maxsize=10000)
        self._subscribers: list[Callable[[StreamEvent], None]] = []
        self._loop_id = loop_id  # Default loop_id for all events
        self._overflow_count = 0  # Track dropped events for monitoring
        self._global_seq = 0  # Global sequence counter
        self._agent_seqs: dict[str, int] = {}  # Per-agent sequence counters
        self._seq_lock = threading.Lock()  # Thread-safe sequence assignment

    def set_loop_id(self, loop_id: str) -> None:
        """Set the loop_id to attach to all emitted events."""
        self._loop_id = loop_id

    def reset_sequences(self) -> None:
        """Reset sequence counters (call when starting a new debate)."""
        with self._seq_lock:
            self._global_seq = 0
            self._agent_seqs.clear()

    def emit(self, event: StreamEvent) -> None:
        """Emit event (safe to call from sync code).

        Automatically assigns sequence numbers for ordering:
        - seq: Global sequence across all events
        - agent_seq: Per-agent sequence for token stream integrity
        """
        # Add loop_id to event if not already set
        if self._loop_id and not event.loop_id:
            event.loop_id = self._loop_id

        # Warn on TOKEN events with empty task_id (can cause text interleaving)
        if event.type.name.startswith("TOKEN") and not event.task_id:
            logger.warning(
                "[stream] TOKEN event for %s has empty task_id. This may cause text interleaving between concurrent streams.",
                event.agent,
            )

        # Assign sequence numbers (thread-safe)
        with self._seq_lock:
            self._global_seq += 1
            event.seq = self._global_seq

            # Per-agent sequence for token events
            if event.agent:
                if event.agent not in self._agent_seqs:
                    self._agent_seqs[event.agent] = 0
                self._agent_seqs[event.agent] += 1
                event.agent_seq = self._agent_seqs[event.agent]

        # Enforce queue size limit OUTSIDE the seq_lock to minimize lock hold time
        # Use put_nowait() which NEVER blocks (critical for avoiding deadlocks)
        try:
            # Drop oldest events to make room if queue is too large
            while self._queue.qsize() >= self.MAX_QUEUE_SIZE:
                try:
                    self._queue.get_nowait()
                    self._overflow_count += 1
                    if self._overflow_count % 1000 == 1:
                        logger.warning(
                            "[stream] Queue overflow, dropping old events (total: %s)",
                            self._overflow_count,
                        )
                except queue.Empty:
                    break

            # put_nowait() never blocks - safe for debate threads
            self._queue.put_nowait(event)
        except queue.Full:
            # Should not happen with unbounded queue, but defensive
            self._overflow_count += 1
            logger.error("[stream] Unexpected queue full condition")

        # Notify subscribers outside lock (they don't need seq consistency)
        for sub in self._subscribers:
            try:
                sub(event)
            except (TypeError, ValueError, RuntimeError, AttributeError) as e:
                logger.warning("[stream] Subscriber callback error: %s", e)

    def emit_sync(
        self,
        event_type: str | StreamEventType,
        debate_id: str = "",
        correlation_id: str | None = None,
        **data: Any,
    ) -> None:
        """Adapt legacy keyword-style emissions to the stream event schema.

        Debate and memory components historically accepted an emitter with
        ``emit_sync(event_type=..., debate_id=..., **data)``. The WebSocket
        stream emitter instead exposed only ``emit(StreamEvent(...))``, so
        passing it into those components raised ``AttributeError`` on live
        intervention paths. Keep the compatibility conversion at this boundary
        so callers do not need to know which emitter implementation they were
        given.
        """
        if isinstance(event_type, StreamEventType):
            stream_type = event_type
        else:
            try:
                stream_type = StreamEventType(event_type)
            except ValueError:
                logger.warning("[stream] Unknown event type %r; event dropped", event_type)
                return

        raw_round = data.get("round", data.get("round_num", 0))
        round_num = raw_round if isinstance(raw_round, int) else 0
        raw_agent = data.get("agent", "")
        agent = raw_agent if isinstance(raw_agent, str) else ""
        self.emit(
            StreamEvent(
                type=stream_type,
                data=dict(data),
                round=round_num,
                agent=agent,
                loop_id=debate_id,
                correlation_id=correlation_id or "",
            )
        )

    def subscribe(self, callback: Callable[[StreamEvent], None]) -> None:
        """Add synchronous subscriber for immediate event handling."""
        self._subscribers.append(callback)

    def drain(self, max_batch_size: int = 100) -> list[StreamEvent]:
        """Get queued events (non-blocking) with backpressure limit."""
        events: list[StreamEvent] = []
        try:
            while len(events) < max_batch_size:
                events.append(self._queue.get_nowait())
        except queue.Empty:
            pass
        return events

    def broadcast_event(
        self,
        event_type: StreamEventType,
        data: dict,
        agent: str = "",
        round_num: int = 0,
        redactor: Callable[[dict], dict] | None = None,
    ) -> bool:
        """
        Broadcast an event with optional redaction for telemetry.

        This method respects the TelemetryConfig settings:
        - SILENT: Event is not emitted
        - DIAGNOSTIC: Event is logged but not broadcast
        - CONTROLLED: Event is emitted with redaction applied
        - SPECTACLE: Event is emitted without redaction

        Args:
            event_type: Type of event to emit
            data: Event payload data
            agent: Agent name (optional)
            round_num: Debate round number (optional)
            redactor: Optional function to redact sensitive data

        Returns:
            True if event was emitted, False if suppressed
        """
        try:
            from aragora.debate.telemetry_config import TelemetryConfig

            config = TelemetryConfig.get_instance()

            # Check if telemetry should be suppressed
            if config.is_silent():
                return False

            # Check if this is a telemetry-specific event
            is_telemetry_event = event_type.value.startswith("telemetry_")

            if is_telemetry_event:
                if config.is_diagnostic():
                    # Log only, don't broadcast
                    logger.debug("[telemetry] %s: %s", event_type.value, data)
                    return False

                # Apply redaction if in controlled mode
                if config.should_redact() and redactor is not None:
                    try:
                        data = redactor(data)
                        # Emit redaction notification
                        self.emit(
                            StreamEvent(
                                type=StreamEventType.TELEMETRY_REDACTION,
                                data={"agent": agent, "event_type": event_type.value},
                                agent=agent,
                                round=round_num,
                            )
                        )
                    except (TypeError, ValueError, KeyError, AttributeError) as e:
                        logger.warning("[telemetry] Redaction failed: %s", e)
                        # On redaction failure, suppress the event for security
                        return False

            # Emit the event
            self.emit(
                StreamEvent(
                    type=event_type,
                    data=data,
                    agent=agent,
                    round=round_num,
                )
            )
            return True

        except ImportError:
            # TelemetryConfig not available, emit without telemetry controls
            self.emit(
                StreamEvent(
                    type=event_type,
                    data=data,
                    agent=agent,
                    round=round_num,
                )
            )
            return True
        except (TypeError, ValueError, KeyError, AttributeError, RuntimeError) as e:
            logger.error("[telemetry] broadcast_event failed: %s", e)
            return False


_global_emitter: SyncEventEmitter | None = None


def get_global_emitter() -> SyncEventEmitter | None:
    """Return the module-level emitter singleton, if set."""
    return _global_emitter


def set_global_emitter(emitter: SyncEventEmitter | None) -> None:
    """Set the module-level emitter singleton."""
    global _global_emitter
    _global_emitter = emitter


def _emit_receipt_verification(signed_receipt: SignedReceipt, is_valid: bool) -> None:
    """Broadcast receipt verification through the configured server emitter."""
    emitter = get_global_emitter()
    if emitter is None:
        return
    event_type = (
        StreamEventType.RECEIPT_VERIFIED if is_valid else StreamEventType.RECEIPT_INTEGRITY_FAILED
    )
    emitter.emit(
        StreamEvent(
            type=event_type,
            data={
                "receipt_id": signed_receipt.receipt_data.get("receipt_id", "unknown"),
                "valid": is_valid,
            },
        )
    )


set_receipt_verification_observer(_emit_receipt_verification)


__all__ = [
    "TokenBucket",
    "AudienceInbox",
    "SyncEventEmitter",
    "normalize_intensity",
    "get_global_emitter",
    "set_global_emitter",
]
