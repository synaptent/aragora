"""
Spectator and event emission logic extracted from Arena.

Provides a mixin class that handles:
- Spectator stream notifications (console/file)
- WebSocket event emission
- ArgumentCartographer updates
- Moment event emission
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.server.stream import SyncEventEmitter
    from aragora.events.spectate.stream import SpectatorStream
    from aragora.visualization.mapper import ArgumentCartographer

logger = logging.getLogger(__name__)


class SpectatorMixin:
    """Mixin providing spectator event emission capabilities.

    Expected attributes from the host class:
    - spectator: SpectatorStream | None
    - event_emitter: SyncEventEmitter | None
    - cartographer: ArgumentCartographer | None
    - loop_id: str
    """

    spectator: SpectatorStream | None
    event_emitter: SyncEventEmitter | None
    cartographer: ArgumentCartographer | None
    loop_id: str

    def _notify_spectator(self, event_type: str, **kwargs: Any) -> None:
        """Emit spectator events and bridge to WebSocket.

        Emits to both SpectatorStream (console/file) and SyncEventEmitter (WebSocket)
        to provide real-time updates to connected clients.

        Args:
            event_type: Type of event (e.g., "debate_start", "proposal", "vote")
            **kwargs: Event-specific data
        """
        if self.spectator:
            self.spectator.emit(event_type, **kwargs)

        # Bridge to WebSocket if event_emitter is available
        if self.event_emitter:
            self._emit_spectator_to_websocket(event_type, **kwargs)

    def _emit_spectator_to_websocket(self, event_type: str, **kwargs: Any) -> None:
        """Convert spectator event to StreamEvent and emit to WebSocket clients."""
        if not self.event_emitter:
            return

        try:
            from aragora.events.types import StreamEvent, StreamEventType

            # Map spectator event types to StreamEventType
            type_mapping = {
                "debate_start": StreamEventType.DEBATE_START,
                "debate_end": StreamEventType.DEBATE_END,
                "round": StreamEventType.ROUND_START,
                "round_start": StreamEventType.ROUND_START,
                "propose": StreamEventType.AGENT_MESSAGE,
                "proposal": StreamEventType.AGENT_MESSAGE,
                "critique": StreamEventType.CRITIQUE,
                "vote": StreamEventType.VOTE,
                "consensus": StreamEventType.CONSENSUS,
                "convergence": StreamEventType.CONSENSUS,
                "judge": StreamEventType.AGENT_MESSAGE,
                "memory_recall": StreamEventType.MEMORY_RECALL,
                "audience_drain": StreamEventType.AUDIENCE_DRAIN,
                "audience_summary": StreamEventType.AUDIENCE_SUMMARY,
                "insight_extracted": StreamEventType.INSIGHT_EXTRACTED,
                # Token streaming events
                "token_start": StreamEventType.TOKEN_START,
                "token_delta": StreamEventType.TOKEN_DELTA,
                "token_end": StreamEventType.TOKEN_END,
                # Trickster/hollow consensus events
                "hollow_consensus": StreamEventType.HOLLOW_CONSENSUS,
                "trickster_intervention": StreamEventType.TRICKSTER_INTERVENTION,
                # Rhetorical observations
                "rhetorical_observation": StreamEventType.RHETORICAL_OBSERVATION,
            }

            stream_type = type_mapping.get(event_type)
            if not stream_type:
                return  # Skip unmapped event types

            # Build event data payload
            ev_data: dict = {
                "details": kwargs.get("details", ""),
                "metric": kwargs.get("metric"),
                "event_source": "spectator",
            }
            # Enrich agent_message events with reasoning visibility fields
            if stream_type == StreamEventType.AGENT_MESSAGE:
                for _k in ("content", "role", "reasoning_phase", "thinking"):
                    if kwargs.get(_k):
                        ev_data[_k] = kwargs[_k]
                if kwargs.get("confidence_score") is not None:
                    ev_data["confidence_score"] = kwargs["confidence_score"]
            stream_event = StreamEvent(
                type=stream_type,
                data=ev_data,
                round=kwargs.get("round_number", 0),
                agent=kwargs.get("agent", ""),
                loop_id=getattr(self, "loop_id", ""),
            )
            self.event_emitter.emit(stream_event)
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.warning("Event emission error (non-fatal): %s", e)

        # Update ArgumentCartographer with this event
        self._update_cartographer(event_type, **kwargs)

    def _emit_moment_event(self, moment: Any) -> None:
        """Emit a significant moment event to WebSocket clients.

        Args:
            moment: A Moment object with to_dict() method
        """
        if not self.event_emitter:
            return
        try:
            from aragora.events.types import StreamEvent, StreamEventType

            self.event_emitter.emit(
                StreamEvent(
                    type=StreamEventType.MOMENT_DETECTED,
                    data=moment.to_dict(),
                    loop_id=self.loop_id or "unknown",
                )
            )
            logger.debug(
                "Emitted moment event: %s for %s",
                moment.moment_type,
                moment.agent_name,
            )
        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.warning("Failed to emit moment event: %s", e)

    def _update_cartographer(self, event_type: str, **kwargs: Any) -> None:
        """Update the ArgumentCartographer graph with debate events.

        Args:
            event_type: Type of event
            **kwargs: Event data including agent, details, round_number
        """
        if not self.cartographer:
            return
        try:
            agent = kwargs.get("agent", "")
            details = kwargs.get("details", "")
            round_num = kwargs.get("round_number", 0)

            if event_type in ("propose", "proposal"):
                # Record proposal/revision as a node
                self.cartographer.update_from_message(
                    agent=agent,
                    content=details,
                    role="proposer",
                    round_num=round_num,
                )
            elif event_type == "critique":
                # Extract target from details (format: "Critiqued {target}: ...")
                target = ""
                if "Critiqued " in details:
                    parts = details.split(":", 1)
                    if parts:
                        target = parts[0].replace("Critiqued ", "").strip()
                self.cartographer.update_from_message(
                    agent=agent,
                    content=details,
                    role="critic",
                    round_num=round_num,
                    metadata={"target_agent": target} if target else None,
                )
            elif event_type == "vote":
                # Record vote relationship
                choice = kwargs.get("choice", "")
                if choice:
                    self.cartographer.update_from_message(
                        agent=agent,
                        content=f"Voted for {choice}",
                        role="voter",
                        round_num=round_num,
                        metadata={"target_agent": choice},
                    )
        except (ValueError, KeyError, TypeError) as e:  # noqa: BLE001
            logger.debug("Cartographer update error: %s", e)
