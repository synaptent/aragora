"""
Arena factory for dependency injection.

Centralizes the creation of Arena instances with properly injected
dependencies, eliminating lazy imports in orchestrator.py.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aragora.core import Agent, Environment

if TYPE_CHECKING:
    from aragora.debate.orchestrator import Arena
from aragora.protocols.debate import DebateProtocol
from aragora.resilience import CircuitBreaker
from aragora.spectate.stream import SpectatorStream

logger = logging.getLogger(__name__)


class ArenaFactory:
    """
    Factory for creating Arena instances with injected dependencies.

    This factory centralizes dependency resolution, allowing Arena to
    accept Protocol-typed dependencies rather than importing concrete
    implementations directly. This breaks circular import chains.

    Usage:
        factory = ArenaFactory()
        arena = factory.create(
            environment=env,
            agents=agents,
            protocol=protocol,
            enable_insights=True,
            enable_belief_analysis=True,
        )
    """

    def __init__(self):
        """Initialize the factory with cached class references."""
        self._position_tracker_cls = None
        self._calibration_tracker_cls = None
        self._belief_network_cls = None
        self._belief_analyzer_cls = None
        self._citation_extractor_cls = None
        self._insight_extractor_cls = None
        self._insight_store_cls = None
        self._critique_store_cls = None
        self._argument_cartographer_cls = None

    def _get_position_tracker_cls(self):
        """Lazy load PositionTracker class."""
        if self._position_tracker_cls is None:
            try:
                from aragora.agents.truth_grounding import PositionTracker

                self._position_tracker_cls = PositionTracker
            except ImportError:
                logger.debug("PositionTracker not available")
        return self._position_tracker_cls

    def _get_calibration_tracker_cls(self):
        """Lazy load CalibrationTracker class."""
        if self._calibration_tracker_cls is None:
            try:
                from aragora.agents.calibration import CalibrationTracker

                self._calibration_tracker_cls = CalibrationTracker
            except ImportError:
                logger.debug("CalibrationTracker not available")
        return self._calibration_tracker_cls

    def _get_belief_classes(self):
        """Lazy load BeliefNetwork and BeliefPropagationAnalyzer."""
        if self._belief_network_cls is None:
            try:
                from aragora.reasoning.belief import (
                    BeliefNetwork,
                    BeliefPropagationAnalyzer,
                )

                self._belief_network_cls = BeliefNetwork
                self._belief_analyzer_cls = BeliefPropagationAnalyzer
            except ImportError:
                logger.debug("Belief classes not available")
        return self._belief_network_cls, self._belief_analyzer_cls

    def _get_citation_extractor_cls(self):
        """Lazy load CitationExtractor class."""
        if self._citation_extractor_cls is None:
            try:
                from aragora.reasoning.citations import CitationExtractor

                self._citation_extractor_cls = CitationExtractor
            except ImportError:
                logger.debug("CitationExtractor not available")
        return self._citation_extractor_cls

    def _get_insight_classes(self):
        """Lazy load InsightExtractor and InsightStore."""
        if self._insight_extractor_cls is None:
            try:
                from aragora.insights import InsightExtractor, InsightStore

                self._insight_extractor_cls = InsightExtractor
                self._insight_store_cls = InsightStore
            except ImportError:
                logger.debug("Insight classes not available")
        return self._insight_extractor_cls, self._insight_store_cls

    def _get_critique_store_cls(self):
        """Lazy load CritiqueStore class."""
        if self._critique_store_cls is None:
            try:
                from aragora.memory.store import CritiqueStore

                self._critique_store_cls = CritiqueStore
            except ImportError:
                logger.debug("CritiqueStore not available")
        return self._critique_store_cls

    def _get_argument_cartographer_cls(self):
        """Lazy load ArgumentCartographer class."""
        if self._argument_cartographer_cls is None:
            try:
                from aragora.visualization.mapper import ArgumentCartographer

                self._argument_cartographer_cls = ArgumentCartographer
            except ImportError:
                logger.debug("ArgumentCartographer not available")
        return self._argument_cartographer_cls

    def create_position_tracker(self, **kwargs: Any) -> Any | None:
        """Create a PositionTracker instance."""
        cls = self._get_position_tracker_cls()
        if cls:
            return cls(**kwargs)
        return None

    def create_calibration_tracker(self, **kwargs: Any) -> Any | None:
        """Create a CalibrationTracker instance."""
        cls = self._get_calibration_tracker_cls()
        if cls:
            return cls(**kwargs)
        return None

    def create_belief_network(self, **kwargs: Any) -> Any | None:
        """Create a BeliefNetwork instance."""
        cls, _ = self._get_belief_classes()
        if cls:
            return cls(**kwargs)
        return None

    def create_belief_analyzer(self, **kwargs: Any) -> Any | None:
        """Create a BeliefPropagationAnalyzer instance."""
        _, cls = self._get_belief_classes()
        if cls:
            return cls(**kwargs)
        return None

    def create_citation_extractor(self, **kwargs: Any) -> Any | None:
        """Create a CitationExtractor instance."""
        cls = self._get_citation_extractor_cls()
        if cls:
            return cls(**kwargs)
        return None

    def create_insight_extractor(self, **kwargs: Any) -> Any | None:
        """Create an InsightExtractor instance."""
        cls, _ = self._get_insight_classes()
        if cls:
            return cls(**kwargs)
        return None

    def create_insight_store(self, **kwargs: Any) -> Any | None:
        """Create an InsightStore instance."""
        _, cls = self._get_insight_classes()
        if cls:
            return cls(**kwargs)
        return None

    def create_critique_store(self, **kwargs: Any) -> Any | None:
        """Create a CritiqueStore instance."""
        cls = self._get_critique_store_cls()
        if cls:
            return cls(**kwargs)
        return None

    def create_argument_cartographer(self, **kwargs: Any) -> Any | None:
        """Create an ArgumentCartographer instance."""
        cls = self._get_argument_cartographer_cls()
        if cls:
            return cls(**kwargs)
        return None

    def create(
        self,
        environment: Environment,
        agents: list[Agent],
        protocol: DebateProtocol | None = None,
        # Optional dependencies - set to True to auto-create
        enable_position_tracking: bool = False,
        enable_calibration: bool = False,
        enable_insights: bool = False,
        enable_belief_analysis: bool = False,
        enable_critique_patterns: bool = False,
        enable_argument_mapping: bool = False,
        # Or pass explicit instances
        memory: Any | None = None,
        event_hooks: dict | None = None,
        event_emitter: Any | None = None,
        spectator: SpectatorStream | None = None,
        debate_embeddings: Any | None = None,
        insight_store: Any | None = None,
        recorder: Any | None = None,
        agent_weights: dict[str, float] | None = None,
        position_tracker: Any | None = None,
        position_ledger: Any | None = None,
        elo_system: Any | None = None,
        persona_manager: Any | None = None,
        dissent_retriever: Any | None = None,
        flip_detector: Any | None = None,
        calibration_tracker: Any | None = None,
        continuum_memory: Any | None = None,
        relationship_tracker: Any | None = None,
        moment_detector: Any | None = None,
        loop_id: str = "",
        strict_loop_scoping: bool = False,
        circuit_breaker: CircuitBreaker | None = None,
        initial_messages: list | None = None,
        trending_topic: Any | None = None,
    ) -> Arena:
        """
        Create an Arena instance with injected dependencies.

        Args:
            environment: The debate environment
            agents: List of participating agents
            protocol: Debate protocol (defaults to DebateProtocol())
            enable_*: Flags to auto-create optional components
            *: Explicit component instances (override enable_* flags)

        Returns:
            Configured Arena instance
        """
        # Import Arena here to avoid circular import
        from aragora.debate.orchestrator import Arena
        from aragora.debate.arena_config import (
            AgentConfig as _AgentConfig,
            MemoryConfig as _MemoryConfig,
            ObservabilityConfig as _ObservabilityConfig,
            StreamingConfig as _StreamingConfig,
        )

        # Auto-create components if requested and not provided
        if enable_position_tracking and position_tracker is None:
            position_tracker = self.create_position_tracker()

        if enable_calibration and calibration_tracker is None:
            calibration_tracker = self.create_calibration_tracker()

        if enable_insights and insight_store is None:
            insight_store = self.create_insight_store()

        if enable_critique_patterns and memory is None:
            memory = self.create_critique_store()

        # Use config objects to avoid deprecation warnings on individual params
        agent_cfg = _AgentConfig(
            agent_weights=agent_weights,
            position_tracker=position_tracker,
            position_ledger=position_ledger,
            elo_system=elo_system,
            persona_manager=persona_manager,
            calibration_tracker=calibration_tracker,
            relationship_tracker=relationship_tracker,
            circuit_breaker=circuit_breaker,
        )
        memory_cfg = _MemoryConfig(
            memory=memory,
            continuum_memory=continuum_memory,
            debate_embeddings=debate_embeddings,
            insight_store=insight_store,
            dissent_retriever=dissent_retriever,
            flip_detector=flip_detector,
            moment_detector=moment_detector,
        )
        streaming_cfg = _StreamingConfig(
            event_hooks=event_hooks,
            event_emitter=event_emitter,
            spectator=spectator,
            recorder=recorder,
            loop_id=loop_id,
            strict_loop_scoping=strict_loop_scoping,
        )
        observability_cfg = _ObservabilityConfig(
            trending_topic=trending_topic,
            initial_messages=initial_messages,
        )

        return Arena.create(
            environment=environment,
            agents=agents,
            protocol=protocol,
            agent_config=agent_cfg,
            memory_config=memory_cfg,
            streaming_config=streaming_cfg,
            observability_config=observability_cfg,
        )


# Singleton factory instance
_factory: ArenaFactory | None = None


def get_arena_factory() -> ArenaFactory:
    """Get the singleton ArenaFactory instance."""
    global _factory
    if _factory is None:
        _factory = ArenaFactory()
    return _factory


def create_arena(
    environment: Environment,
    agents: list[Agent],
    **kwargs: Any,
) -> Arena:
    """
    Convenience function to create an Arena with the default factory.

    This is the recommended way to create Arena instances, as it
    centralizes dependency injection.

    Example:
        arena = create_arena(
            environment=env,
            agents=agents,
            enable_insights=True,
        )
    """
    return get_arena_factory().create(environment, agents, **kwargs)
