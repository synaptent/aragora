"""
Debate controller management for the unified server.

This module provides the DebateControllerMixin class with methods for:
- Debate controller initialization and access (_get_debate_controller)
- Agent auto-selection (_auto_select_agents)

These methods are extracted from UnifiedHandler to improve modularity
and allow easier testing of debate management logic.
"""

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from aragora.agents.grounded import MomentDetector, PositionLedger
    from aragora.agents.personas import PersonaManager
    from aragora.agents.truth_grounding import PositionTracker
    from aragora.debate.embeddings import DebateEmbeddingsDatabase
    from aragora.insights.flip_detector import FlipDetector
    from aragora.memory.consensus import DissentRetriever
    from aragora.ranking.elo import EloSystem
    from aragora.server.debate_controller import DebateController
    from aragora.server.debate_factory import DebateFactory
    from aragora.storage.debate_storage import DebateStorage
    from aragora.server.stream import SyncEventEmitter


class DebateControllerMixin:
    """Mixin providing debate controller management methods.

    This mixin expects the following class attributes from the parent:
    - storage: DebateStorage for debate persistence
    - elo_system: EloSystem for agent rankings
    - persona_manager: PersonaManager for agent personas
    - debate_embeddings: DebateEmbeddingsDatabase for embeddings
    - position_tracker: PositionTracker for position tracking
    - position_ledger: PositionLedger for position ledger
    - flip_detector: FlipDetector for position reversals
    - dissent_retriever: DissentRetriever for minority views
    - moment_detector: MomentDetector for narrative moments
    - stream_emitter: SyncEventEmitter for streaming events
    """

    # Type stubs for attributes expected from parent class
    storage: Optional["DebateStorage"]
    elo_system: Optional["EloSystem"]
    persona_manager: Optional["PersonaManager"]
    debate_embeddings: Optional["DebateEmbeddingsDatabase"]
    position_tracker: Optional["PositionTracker"]
    position_ledger: Optional["PositionLedger"]
    flip_detector: Optional["FlipDetector"]
    dissent_retriever: Optional["DissentRetriever"]
    moment_detector: Optional["MomentDetector"]
    stream_emitter: Optional["SyncEventEmitter"]

    # Debate controller and factory (class-level, shared across instances)
    _debate_controller: Optional["DebateController"] = None
    _debate_factory: Optional["DebateFactory"] = None

    def _get_debate_controller(self) -> "DebateController":
        """Get or create the debate controller (lazy initialization).

        The debate controller provides centralized management of debate lifecycle:
        - Creating new debates
        - Managing debate state
        - Coordinating with ELO system
        - Streaming events

        The controller is shared across all handler instances (class-level).

        Returns:
            DebateController instance
        """
        from aragora.server.debate_controller import DebateController
        from aragora.server.debate_factory import DebateFactory

        # Access class-level attributes
        cls = self.__class__

        if cls._debate_controller is None:
            # Create factory with all subsystems
            factory = DebateFactory(
                elo_system=self.elo_system,
                persona_manager=self.persona_manager,
                debate_embeddings=self.debate_embeddings,
                position_tracker=self.position_tracker,
                position_ledger=self.position_ledger,
                flip_detector=self.flip_detector,
                dissent_retriever=self.dissent_retriever,
                moment_detector=self.moment_detector,
                stream_emitter=self.stream_emitter,
                document_store=getattr(self, "ctx", {}).get("document_store"),
                evidence_store=getattr(self, "ctx", {}).get("evidence_store"),
                knowledge_mound=getattr(self, "knowledge_mound", None),
            )
            cls._debate_factory = factory

            # Create controller with storage for debate persistence
            cls._debate_controller = DebateController(
                factory=factory,
                emitter=self.stream_emitter,
                elo_system=self.elo_system,
                auto_select_fn=self._auto_select_agents,
                storage=self.storage,
            )
        return cls._debate_controller

    def _auto_select_agents(self, question: str, config: dict[str, Any]) -> str:
        """Select optimal agents using question classification and AgentSelector.

        Uses the question classification and ELO system to automatically
        select the best agents for a given debate topic.

        Args:
            question: The debate question/topic
            config: Debate configuration dict (may contain agent preferences)

        Returns:
            Comma-separated string of selected agent names
        """
        from aragora.server.agent_selection import auto_select_agents

        return auto_select_agents(
            question=question,
            config=config,
            elo_system=self.elo_system,
            persona_manager=self.persona_manager,
        )


__all__ = ["DebateControllerMixin"]
