"""
Event bridge for coordinating spectator and WebSocket event emission.

Extracts event emission logic from Arena orchestrator for better modularity.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventEmitterBridge:
    """
    Bridge between SpectatorStream and WebSocket event emission.

    Coordinates event emission to:
    - SpectatorStream (console/file output)
    - SyncEventEmitter (WebSocket clients)
    - ArgumentCartographer (graph visualization)
    """

    # Map spectator event types to StreamEventType
    EVENT_TYPE_MAPPING = {
        "debate_start": "DEBATE_START",
        "debate_end": "DEBATE_END",
        "round": "ROUND_START",
        "round_start": "ROUND_START",
        "propose": "AGENT_MESSAGE",
        "proposal": "AGENT_MESSAGE",
        "critique": "CRITIQUE",
        "vote": "VOTE",
        "consensus": "CONSENSUS",
        "convergence": "CONSENSUS",
        "judge": "AGENT_MESSAGE",
        "memory_recall": "MEMORY_RECALL",
        "audience_drain": "AUDIENCE_DRAIN",
        "audience_summary": "AUDIENCE_SUMMARY",
        "insight_extracted": "INSIGHT_EXTRACTED",
        "token_start": "TOKEN_START",
        "token_delta": "TOKEN_DELTA",
        "token_end": "TOKEN_END",
        # Cartography events
        "graph_update": "GRAPH_UPDATE",
        # New event mappings for feedback loop events
        "claim_verification": "CLAIM_VERIFICATION_RESULT",
        "memory_tier_promotion": "MEMORY_TIER_PROMOTION",
        "memory_tier_demotion": "MEMORY_TIER_DEMOTION",
        "agent_elo_updated": "AGENT_ELO_UPDATED",
    }

    def __init__(
        self,
        spectator: Any | None = None,
        event_emitter: Any | None = None,
        cartographer: Any | None = None,
        loop_id: str = "",
    ):
        """
        Initialize the event bridge.

        Args:
            spectator: SpectatorStream for console/file output
            event_emitter: SyncEventEmitter for WebSocket clients
            cartographer: ArgumentCartographer for graph updates
            loop_id: Debate/loop identifier
        """
        self.spectator = spectator
        self.event_emitter = event_emitter
        self.cartographer = cartographer
        self.loop_id = loop_id

    def notify(self, event_type: str, **kwargs) -> None:
        """
        Emit event to all registered listeners.

        Emits to SpectatorStream, WebSocket, and Cartographer.

        Args:
            event_type: Type of event (e.g., "proposal", "critique", "vote")
            **kwargs: Event data (agent, details, round_number, etc.)
        """
        # Emit to spectator (console/file) - only pass supported params
        spectator_kwargs = {
            k: v for k, v in kwargs.items() if k in ("agent", "details", "metric", "round_number")
        }
        if self.spectator:
            try:
                from aragora.events.spectate.ws_bridge import bind_spectate_context

                with bind_spectate_context(
                    debate_id=kwargs.get("debate_id") or self.loop_id or None,
                    pipeline_id=kwargs.get("pipeline_id"),
                    task=kwargs.get("task"),
                    agents=kwargs.get("agents"),
                ):
                    self.spectator.emit(event_type, **spectator_kwargs)
            except ImportError:
                self.spectator.emit(event_type, **spectator_kwargs)

        # Fan out to SSE spectator clients (if any are connected)
        if self.loop_id:
            try:
                from aragora.server.handlers.debates.spectate import push_spectator_event

                push_spectator_event(self.loop_id, event_type, **spectator_kwargs)
            except ImportError:
                pass  # Server handlers not available (CLI-only usage)

        # Emit to WebSocket clients
        if self.event_emitter:
            self._emit_to_websocket(event_type, **kwargs)

    def _emit_to_websocket(self, event_type: str, **kwargs) -> None:
        """Convert spectator event to StreamEvent and emit to WebSocket."""
        if not self.event_emitter:
            return

        try:
            from aragora.events.types import StreamEvent, StreamEventType

            stream_type_name = self.EVENT_TYPE_MAPPING.get(event_type)
            if not stream_type_name:
                return  # Skip unmapped event types

            stream_type = getattr(StreamEventType, stream_type_name, None)
            if not stream_type:
                return

            ev_data: dict = {
                "details": kwargs.get("details", ""),
                "metric": kwargs.get("metric"),
                "event_source": "spectator",
            }
            # Enrich agent_message events with reasoning visibility fields
            if stream_type_name == "AGENT_MESSAGE":
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
                loop_id=self.loop_id,
            )
            self.event_emitter.emit(stream_event)
        except Exception as e:  # noqa: BLE001 - graceful degradation, event emission is non-critical
            logger.warning("Event emission error (non-fatal): %s: %s", type(e).__name__, e)

        # Update cartographer with this event
        self._update_cartographer(event_type, **kwargs)

    def _update_cartographer(self, event_type: str, **kwargs) -> None:
        """Update the ArgumentCartographer graph with debate events."""
        if not self.cartographer:
            return

        updated = False
        try:
            agent = kwargs.get("agent", "")
            details = kwargs.get("details", "")
            round_num = kwargs.get("round_number", 0)

            if event_type in ("propose", "proposal"):
                self.cartographer.update_from_message(
                    agent=agent,
                    content=details,
                    role="proposer",
                    round_num=round_num,
                )
                updated = True
            elif event_type == "critique":
                target = self._extract_critique_target(details)
                severity = kwargs.get("metric", 0.5)
                self.cartographer.update_from_critique(
                    critic_agent=agent,
                    target_agent=target,
                    severity=severity if isinstance(severity, (int, float)) else 0.5,
                    round_num=round_num,
                    critique_text=details,
                )
                updated = True
            elif event_type == "vote":
                vote_value = details.split(":")[-1].strip() if ":" in details else details
                self.cartographer.update_from_vote(
                    agent=agent,
                    vote_value=vote_value,
                    round_num=round_num,
                )
                updated = True
            elif event_type == "consensus":
                result = details.split(":")[-1].strip() if ":" in details else details
                self.cartographer.update_from_consensus(
                    result=result,
                    round_num=round_num,
                )
                updated = True

            if updated:
                self._emit_graph_update()
        except Exception as e:  # noqa: BLE001 - graceful degradation, cartographer update is non-critical
            logger.warning("Cartographer error (non-fatal): %s", e)

    def _emit_graph_update(self) -> None:
        """Emit a graph_update event with the current cartographer state."""
        if not self.event_emitter or not self.cartographer:
            return

        try:
            from aragora.events.types import StreamEvent, StreamEventType

            graph_data = self.cartographer.to_dict()
            self.event_emitter.emit(
                StreamEvent(
                    type=StreamEventType.GRAPH_UPDATE,
                    data=graph_data,
                    loop_id=self.loop_id or "",
                )
            )
        except Exception as e:  # noqa: BLE001 - graceful degradation, graph update is non-critical
            logger.warning("Graph update emission error (non-fatal): %s", e)

    @staticmethod
    def _extract_critique_target(details: str) -> str:
        """Extract target agent from critique details string."""
        if "Critiqued " in details:
            return details.split("Critiqued ")[1].split(":")[0]
        return ""

    def emit_moment(self, moment: Any) -> None:
        """Emit a significant moment event to WebSocket clients."""
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
            logger.debug("Emitted moment event: %s for %s", moment.moment_type, moment.agent_name)
        except Exception as e:  # noqa: BLE001 - graceful degradation, moment emission is non-critical
            logger.warning("Failed to emit moment event: %s", e)
