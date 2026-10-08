"""
Bridge between Arena's EventBus and CrossSubscriberManager.

Enables cross-pollination by translating debate events to stream events
that cross-subsystem subscribers can process.

Usage:
    from aragora.debate.arena_bridge import ArenaEventBridge

    # In Arena initialization
    bridge = ArenaEventBridge(event_bus)
    bridge.connect_to_cross_subscribers()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aragora.events.cross_subscribers import (
    CrossSubscriberManager,
    get_cross_subscriber_manager,
)
from aragora.events.types import StreamEvent, StreamEventType

if TYPE_CHECKING:
    from aragora.debate.event_bus import DebateEvent, EventBus

logger = logging.getLogger(__name__)

# Map EventBus event type strings to StreamEventType
EVENT_TYPE_MAP: dict[str, StreamEventType] = {
    # Debate lifecycle
    "debate_start": StreamEventType.DEBATE_START,
    "debate_end": StreamEventType.DEBATE_END,
    "round_start": StreamEventType.ROUND_START,
    # Memory events
    "memory_stored": StreamEventType.MEMORY_STORED,
    "memory_retrieved": StreamEventType.MEMORY_RETRIEVED,
    "memory_recall": StreamEventType.MEMORY_RECALL,
    # Agent events
    "agent_message": StreamEventType.AGENT_MESSAGE,
    "agent_elo_updated": StreamEventType.AGENT_ELO_UPDATED,
    "agent_calibration_changed": StreamEventType.AGENT_CALIBRATION_CHANGED,
    "agent_fallback_triggered": StreamEventType.AGENT_FALLBACK_TRIGGERED,
    # Knowledge events
    "knowledge_indexed": StreamEventType.KNOWLEDGE_INDEXED,
    "knowledge_queried": StreamEventType.KNOWLEDGE_QUERIED,
    "mound_updated": StreamEventType.MOUND_UPDATED,
    # Evidence/calibration
    "evidence_found": StreamEventType.EVIDENCE_FOUND,
    "calibration_update": StreamEventType.CALIBRATION_UPDATE,
    # Consensus
    "consensus": StreamEventType.CONSENSUS,
    "vote": StreamEventType.VOTE,
}


class ArenaEventBridge:
    """
    Bridge between Arena's EventBus and CrossSubscriberManager.

    Subscribes to EventBus events, converts them to StreamEvents,
    and dispatches them to cross-subsystem subscribers.

    Example:
        bridge = ArenaEventBridge(event_bus)
        bridge.connect_to_cross_subscribers()
    """

    def __init__(
        self,
        event_bus: EventBus,
        cross_manager: CrossSubscriberManager | None = None,
    ) -> None:
        """
        Initialize the bridge.

        Args:
            event_bus: The Arena's EventBus instance
            cross_manager: Optional CrossSubscriberManager (uses global if not provided)
        """
        self._event_bus = event_bus
        self._cross_manager = (
            cross_manager if cross_manager is not None else get_cross_subscriber_manager()
        )
        self._connected = False

    def connect_to_cross_subscribers(self) -> None:
        """
        Connect the EventBus to CrossSubscriberManager.

        Subscribes to all mapped event types and forwards them
        as StreamEvents to the cross-subscriber system.
        """
        if self._connected:
            logger.debug("ArenaEventBridge already connected")
            return

        # Subscribe to all mapped event types
        for event_type_str in EVENT_TYPE_MAP:
            self._event_bus.subscribe_sync(event_type_str, self._on_event)

        self._connected = True
        logger.info("ArenaEventBridge connected: %s event types bridged", len(EVENT_TYPE_MAP))

    def _on_event(self, event: DebateEvent) -> None:
        """
        Handle incoming EventBus events.

        Converts DebateEvent to StreamEvent and dispatches
        to CrossSubscriberManager.
        """
        stream_event_type = EVENT_TYPE_MAP.get(event.event_type)
        if stream_event_type is None:
            # Unmapped event type, skip
            return

        try:
            stream_event = self._convert_to_stream_event(event, stream_event_type)
            self._cross_manager._dispatch_event(stream_event)
        except (KeyError, TypeError, AttributeError, ValueError, RuntimeError) as e:
            logger.warning("ArenaEventBridge dispatch failed: %s", e)

    def _convert_to_stream_event(
        self,
        event: DebateEvent,
        event_type: StreamEventType,
    ) -> StreamEvent:
        """
        Convert a DebateEvent to a StreamEvent.

        Args:
            event: The source DebateEvent
            event_type: The target StreamEventType

        Returns:
            StreamEvent ready for cross-subscriber dispatch
        """
        # Extract common fields
        data = dict(event.data) if event.data else {}
        data["debate_id"] = event.debate_id

        return StreamEvent(
            type=event_type,
            data=data,
            timestamp=event.timestamp.timestamp() if event.timestamp else 0,
            correlation_id=event.correlation_id or "",
        )

    def disconnect(self) -> None:
        """
        Disconnect the bridge (for cleanup).

        Note: EventBus doesn't have unsubscribe_sync, so this
        just marks the bridge as disconnected.
        """
        self._connected = False
        logger.debug("ArenaEventBridge disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if the bridge is connected."""
        return self._connected


def create_arena_bridge(event_bus: EventBus) -> ArenaEventBridge:
    """
    Factory function to create and connect an ArenaEventBridge.

    Args:
        event_bus: The Arena's EventBus instance

    Returns:
        Connected ArenaEventBridge
    """
    from aragora.debate.event_subscribers import bootstrap_debate_event_subscribers

    cross_manager = bootstrap_debate_event_subscribers()
    bridge = ArenaEventBridge(event_bus, cross_manager)
    bridge.connect_to_cross_subscribers()
    return bridge


__all__ = [
    "ArenaEventBridge",
    "create_arena_bridge",
    "EVENT_TYPE_MAP",
]
