"""
Prometheus metrics for new Aragora features.

Provides metrics for:
- Checkpoint Bridge (unified recovery)
- Agent Channels (peer-to-peer messaging)
- Session Management (multi-channel sessions)
"""

import time
from contextlib import contextmanager

from aragora.observability.prometheus import (
    PROMETHEUS_AVAILABLE,
    _simple_metrics,
)

# Import metric definitions when prometheus is available
if PROMETHEUS_AVAILABLE:
    from aragora.observability.prometheus import (
        CHECKPOINT_BRIDGE_SAVES,
        CHECKPOINT_BRIDGE_RESTORES,
        CHECKPOINT_BRIDGE_MOLECULE_RECOVERIES,
        CHECKPOINT_BRIDGE_SAVE_DURATION,
        AGENT_CHANNEL_MESSAGES,
        AGENT_CHANNEL_SETUPS,
        AGENT_CHANNEL_TEARDOWNS,
        AGENT_CHANNEL_ACTIVE,
        AGENT_CHANNEL_HISTORY_SIZE,
        SESSION_CREATED,
        SESSION_DEBATES_LINKED,
        SESSION_HANDOFFS,
        SESSION_RESULT_ROUTES,
        SESSION_ACTIVE,
    )


# ============================================================================
# Checkpoint Bridge Metrics
# ============================================================================


def record_checkpoint_bridge_save(debate_id: str, phase: str) -> None:
    """Record a checkpoint bridge save operation.

    Args:
        debate_id: Debate identifier (truncated to 8 chars for cardinality)
        phase: Current debate phase
    """
    # Truncate debate_id to limit cardinality
    short_id = debate_id[:8] if debate_id else "unknown"

    if PROMETHEUS_AVAILABLE:
        CHECKPOINT_BRIDGE_SAVES.labels(debate_id=short_id, phase=phase).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_checkpoint_bridge_saves_total",
            {"debate_id": short_id, "phase": phase},
        )


def record_checkpoint_bridge_restore(status: str) -> None:
    """Record a checkpoint bridge restore operation.

    Args:
        status: Restore status (success, not_found, failed)
    """
    if PROMETHEUS_AVAILABLE:
        CHECKPOINT_BRIDGE_RESTORES.labels(status=status).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_checkpoint_bridge_restores_total",
            {"status": status},
        )


def record_checkpoint_bridge_molecule_recovery(status: str) -> None:
    """Record a molecule recovery from checkpoint.

    Args:
        status: Recovery status (success, not_found, no_state)
    """
    if PROMETHEUS_AVAILABLE:
        CHECKPOINT_BRIDGE_MOLECULE_RECOVERIES.labels(status=status).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_checkpoint_bridge_molecule_recoveries_total",
            {"status": status},
        )


def record_checkpoint_bridge_save_duration(duration_seconds: float) -> None:
    """Record checkpoint bridge save duration.

    Args:
        duration_seconds: Time taken to save checkpoint
    """
    if PROMETHEUS_AVAILABLE:
        CHECKPOINT_BRIDGE_SAVE_DURATION.observe(duration_seconds)
    else:
        _simple_metrics.observe_histogram(
            "aragora_checkpoint_bridge_save_duration_seconds",
            duration_seconds,
        )


@contextmanager
def track_checkpoint_bridge_save(debate_id: str, phase: str):
    """Context manager to track checkpoint bridge save operations.

    Args:
        debate_id: Debate identifier
        phase: Current debate phase

    Yields:
        None

    Example:
        with track_checkpoint_bridge_save("debate_123", "voting"):
            await bridge.save_checkpoint(...)
    """
    start = time.time()
    try:
        yield
        record_checkpoint_bridge_save(debate_id, phase)
    finally:
        duration = time.time() - start
        record_checkpoint_bridge_save_duration(duration)


# ============================================================================
# Agent Channel Metrics
# ============================================================================


def record_agent_channel_message(message_type: str, channel: str) -> None:
    """Record a message sent through agent channels.

    Args:
        message_type: Type of message (proposal, critique, query, signal)
        channel: Channel/debate identifier
    """
    # Truncate channel to limit cardinality
    short_channel = channel[:8] if channel else "unknown"

    if PROMETHEUS_AVAILABLE:
        AGENT_CHANNEL_MESSAGES.labels(message_type=message_type, channel=short_channel).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_agent_channel_messages_total",
            {"message_type": message_type, "channel": short_channel},
        )


def record_agent_channel_setup(status: str) -> None:
    """Record a channel setup operation.

    Args:
        status: Setup status (success, failed, disabled)
    """
    if PROMETHEUS_AVAILABLE:
        AGENT_CHANNEL_SETUPS.labels(status=status).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_agent_channel_setups_total",
            {"status": status},
        )


def record_agent_channel_teardown() -> None:
    """Record a channel teardown operation."""
    if PROMETHEUS_AVAILABLE:
        AGENT_CHANNEL_TEARDOWNS.inc()
    else:
        _simple_metrics.inc_counter("aragora_agent_channel_teardowns_total")


def set_agent_channel_active_count(count: int) -> None:
    """Set the number of active agent channels.

    Args:
        count: Number of active channels
    """
    if PROMETHEUS_AVAILABLE:
        AGENT_CHANNEL_ACTIVE.set(count)
    else:
        _simple_metrics.set_gauge("aragora_agent_channel_active", count)


def record_agent_channel_history_size(size: int) -> None:
    """Record message history size at channel teardown.

    Args:
        size: Number of messages in history
    """
    if PROMETHEUS_AVAILABLE:
        AGENT_CHANNEL_HISTORY_SIZE.observe(size)
    else:
        _simple_metrics.observe_histogram(
            "aragora_agent_channel_history_size",
            size,
        )


# ============================================================================
# Session Management Metrics
# ============================================================================


def record_session_created(channel: str) -> None:
    """Record a session creation.

    Args:
        channel: Platform channel (slack, telegram, whatsapp, api)
    """
    if PROMETHEUS_AVAILABLE:
        SESSION_CREATED.labels(channel=channel).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_session_created_total",
            {"channel": channel},
        )


def record_session_debate_linked(channel: str) -> None:
    """Record a debate being linked to a session.

    Args:
        channel: Platform channel
    """
    if PROMETHEUS_AVAILABLE:
        SESSION_DEBATES_LINKED.labels(channel=channel).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_session_debates_linked_total",
            {"channel": channel},
        )


def record_session_handoff(from_channel: str, to_channel: str) -> None:
    """Record a session handoff between channels.

    Args:
        from_channel: Source channel
        to_channel: Target channel
    """
    if PROMETHEUS_AVAILABLE:
        SESSION_HANDOFFS.labels(from_channel=from_channel, to_channel=to_channel).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_session_handoffs_total",
            {"from_channel": from_channel, "to_channel": to_channel},
        )


def record_session_result_route(channel: str, status: str) -> None:
    """Record a debate result being routed to a session.

    Args:
        channel: Target platform channel
        status: Route status (success, failed, no_channel)
    """
    if PROMETHEUS_AVAILABLE:
        SESSION_RESULT_ROUTES.labels(channel=channel, status=status).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_session_result_routes_total",
            {"channel": channel, "status": status},
        )


def set_session_active_count(channel: str, count: int) -> None:
    """Set the number of active sessions by channel.

    Args:
        channel: Platform channel
        count: Number of active sessions
    """
    if PROMETHEUS_AVAILABLE:
        SESSION_ACTIVE.labels(channel=channel).set(count)
    else:
        _simple_metrics.set_gauge(
            "aragora_sessions_active",
            count,
            {"channel": channel},
        )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # Checkpoint Bridge
    "record_checkpoint_bridge_save",
    "record_checkpoint_bridge_restore",
    "record_checkpoint_bridge_molecule_recovery",
    "record_checkpoint_bridge_save_duration",
    "track_checkpoint_bridge_save",
    # Agent Channel
    "record_agent_channel_message",
    "record_agent_channel_setup",
    "record_agent_channel_teardown",
    "set_agent_channel_active_count",
    "record_agent_channel_history_size",
    # Session Management
    "record_session_created",
    "record_session_debate_linked",
    "record_session_handoff",
    "record_session_result_route",
    "set_session_active_count",
]
