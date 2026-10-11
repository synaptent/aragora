"""
ML Integration for Debate System.

Bridges the aragora.ml module with the debate orchestrator,
providing ML-powered agent selection, quality gates, and
consensus estimation.

Usage:
    from aragora.debate.ml_integration import (
        MLDelegationStrategy,
        QualityGate,
        ConsensusEstimator,
        create_ml_team_selector,
    )

    # Use ML-based delegation in debates
    delegation = MLDelegationStrategy()
    team_selector = create_ml_team_selector(delegation_strategy=delegation)

    # Quality gate for response filtering
    gate = QualityGate(threshold=0.6)
    high_quality = gate.filter_responses(responses)

    # Consensus estimation for early termination
    estimator = ConsensusEstimator()
    if estimator.should_terminate_early(responses, round_num=2):
        # Safe to end debate early
        pass
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from collections.abc import Sequence

from aragora.debate.delegation import DelegationStrategy

if TYPE_CHECKING:
    from aragora.core import Agent, Message
    from aragora.debate.context import DebateContext
    from aragora.debate.team_selector import TeamSelector

logger = logging.getLogger(__name__)


@dataclass
class MLIntegrationConfig:
    """Configuration for ML integration."""

    # Agent routing
    use_ml_routing: bool = True
    ml_routing_weight: float = 0.4  # Weight in hybrid scoring
    fallback_to_elo: bool = True

    # Quality gates
    enable_quality_gates: bool = True
    quality_threshold: float = 0.6
    min_confidence: float = 0.4

    # Consensus estimation
    enable_early_termination: bool = True
    early_termination_threshold: float = 0.85
    min_rounds_before_termination: int = 2

    # Performance
    cache_routing_decisions: bool = True
    cache_ttl_seconds: int = 300


class MLDelegationStrategy(DelegationStrategy):
    """ML-powered delegation strategy using AgentRouter.

    Integrates the ML module's AgentRouter with the debate
    system's delegation framework for intelligent task-based
    agent selection.

    Example:
        delegation = MLDelegationStrategy()
        selected = delegation.select_agents(
            "Implement a caching layer",
            agents,
            context,
        )
    """

    def __init__(
        self,
        config: MLIntegrationConfig | None = None,
        elo_system: Any | None = None,
        calibration_tracker: Any | None = None,
        ml_weight: float | None = None,
    ):
        """Initialize ML delegation strategy.

        Args:
            config: ML integration configuration
            elo_system: Optional ELO ranking system for hybrid scoring
            calibration_tracker: Optional calibration tracker for agent performance
            ml_weight: Weight for ML routing in hybrid scoring (0.0-1.0)
        """
        self.config = config or MLIntegrationConfig()
        self._router: Any | None = None
        self._cache: dict[str, tuple[list[str], float]] = {}

        # Hybrid scoring components
        self._elo_system = elo_system
        self._calibration_tracker = calibration_tracker
        if ml_weight is not None:
            self.config.ml_routing_weight = ml_weight

    def _get_router(self):
        """Lazy load the agent router."""
        if self._router is None:
            try:
                from aragora.ml import get_agent_router

                self._router = get_agent_router()
            except ImportError:
                logger.warning("ML module not available, using fallback scoring")
        return self._router

    def _get_cache_key(self, task: str, agent_names: list[str]) -> str:
        """Generate cache key for routing decision."""
        return f"{task[:100]}:{','.join(sorted(agent_names))}"

    def select_agents(
        self,
        task: str,
        agents: Sequence[Agent],
        context: DebateContext | None = None,
        max_agents: int | None = None,
    ) -> list[Agent]:
        """Select agents using ML-based routing.

        Args:
            task: Task description
            agents: Available agents
            context: Optional debate context
            max_agents: Maximum agents to return

        Returns:
            Agents sorted by ML routing score
        """
        if not agents:
            return []

        router = self._get_router()
        if not router:
            # Fallback: return agents as-is
            return list(agents)[:max_agents] if max_agents else list(agents)

        agent_names = [a.name for a in agents]
        team_size = max_agents or len(agents)

        # Check cache
        if self.config.cache_routing_decisions:
            cache_key = self._get_cache_key(task, agent_names)
            if cache_key in self._cache:
                cached_order, _ = self._cache[cache_key]
                return self._reorder_agents(agents, cached_order)[:team_size]

        # Get ML routing decision
        try:
            decision = router.route(
                task=task,
                available_agents=agent_names,
                team_size=team_size,
            )

            logger.info(
                "ml_routing task_type=%s confidence=%.2f selected=%s",
                decision.task_type.value,
                decision.confidence,
                decision.selected_agents[:3],
            )

            # Cache the decision
            if self.config.cache_routing_decisions:
                self._cache[cache_key] = (decision.selected_agents, decision.confidence)

            return self._reorder_agents(agents, decision.selected_agents)

        except (ValueError, TypeError, KeyError) as e:
            logger.warning("ML routing failed with data error: %s, using fallback", e)
            return list(agents)[:team_size]
        except (RuntimeError, AttributeError, ImportError, OSError, ConnectionError) as e:
            logger.exception("Unexpected ML routing error: %s, using fallback", e)
            return list(agents)[:team_size]

    def _reorder_agents(
        self,
        agents: Sequence[Agent],
        order: list[str],
    ) -> list[Agent]:
        """Reorder agents according to ML routing decision."""
        agent_map = {a.name: a for a in agents}
        result = []

        # Add agents in ML-determined order
        for name in order:
            if name in agent_map:
                result.append(agent_map[name])

        # Add any remaining agents not in the order
        for agent in agents:
            if agent not in result:
                result.append(agent)

        return result

    def score_agent(
        self,
        agent: Agent,
        task: str,
        context: DebateContext | None = None,
    ) -> float:
        """Score a single agent using ML routing.

        Args:
            agent: Agent to score
            task: Task description
            context: Optional context

        Returns:
            ML-based score (0-5 scale for delegation compatibility)
        """
        router = self._get_router()
        if not router:
            return 2.5  # Neutral fallback

        try:
            decision = router.route(
                task=task,
                available_agents=[agent.name],
                team_size=1,
            )

            # Convert confidence (0-1) to delegation scale (0-5)
            score = decision.confidence * 5.0

            # Check if agent was selected (should always be true for single agent)
            if agent.name in decision.selected_agents:
                agent_score = decision.agent_scores.get(agent.name, 0.5)
                score = agent_score * 5.0

            return score

        except (ValueError, TypeError, KeyError) as e:
            logger.debug("ML scoring failed for %s with data error: %s", agent.name, e)
            return 2.5
        except (RuntimeError, AttributeError, ImportError, OSError, ConnectionError) as e:
            logger.warning("Unexpected ML scoring error for %s: %s", agent.name, e)
            return 2.5


class QualityGate:
    """Quality gate for filtering debate responses.

    Uses the ML quality scorer to filter out low-quality
    responses before they enter consensus calculation.

    Example:
        gate = QualityGate(threshold=0.6)
        filtered = gate.filter_responses(responses, task)
    """

    def __init__(
        self,
        threshold: float = 0.6,
        min_confidence: float = 0.4,
    ):
        """Initialize quality gate.

        Args:
            threshold: Minimum quality score (0-1)
            min_confidence: Minimum confidence to trust score
        """
        self.threshold = threshold
        self.min_confidence = min_confidence
        self._scorer: Any | None = None

    def _get_scorer(self):
        """Lazy load quality scorer."""
        if self._scorer is None:
            try:
                from aragora.ml import get_quality_scorer

                self._scorer = get_quality_scorer()
            except ImportError:
                logger.warning("ML quality scorer not available")
        return self._scorer

    def score_response(
        self,
        text: str,
        context: str | None = None,
    ) -> tuple[float, float]:
        """Score a single response.

        Args:
            text: Response text
            context: Optional task context

        Returns:
            Tuple of (quality_score, confidence)
        """
        scorer = self._get_scorer()
        if not scorer:
            return (0.5, 0.0)  # Unknown quality

        try:
            score = scorer.score(text, context=context)
            return (score.overall, score.confidence)
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug("Quality scoring failed with expected error: %s", e)
            return (0.5, 0.0)
        except (RuntimeError, AttributeError, ImportError, OSError, ConnectionError) as e:
            logger.warning("Unexpected quality scoring error: %s", e)
            return (0.5, 0.0)

    def passes_gate(
        self,
        text: str,
        context: str | None = None,
    ) -> bool:
        """Check if response passes quality gate.

        Args:
            text: Response text
            context: Optional context

        Returns:
            True if response meets quality threshold
        """
        quality, confidence = self.score_response(text, context)

        # Only apply gate if we're confident in the score
        if confidence < self.min_confidence:
            return True  # Pass uncertain responses through

        return quality >= self.threshold

    def filter_responses(
        self,
        responses: Sequence[tuple[str, str]],  # (agent_id, text) pairs
        context: str | None = None,
    ) -> list[tuple[str, str, float]]:
        """Filter responses by quality.

        Args:
            responses: List of (agent_id, text) tuples
            context: Optional task context

        Returns:
            Filtered list of (agent_id, text, score) tuples
        """
        results = []

        for agent_id, text in responses:
            quality, confidence = self.score_response(text, context)

            if confidence >= self.min_confidence and quality < self.threshold:
                logger.info(
                    "quality_gate_filtered agent=%s quality=%.2f threshold=%s",
                    agent_id,
                    quality,
                    self.threshold,
                )
                continue

            results.append((agent_id, text, quality))

        return results

    def filter_messages(
        self,
        messages: Sequence[Message],
        context: str | None = None,
    ) -> list[tuple[Message, float]]:
        """Filter Message objects by quality.

        Args:
            messages: List of Message objects
            context: Optional task context

        Returns:
            Filtered list of (message, score) tuples
        """
        results = []

        for message in messages:
            quality, confidence = self.score_response(message.content, context)

            if confidence >= self.min_confidence and quality < self.threshold:
                logger.info("quality_gate_filtered agent=%s quality=%.2f", message.agent, quality)
                continue

            results.append((message, quality))

        return results


class ConsensusEstimator:
    """Estimates consensus likelihood for early termination.

    Uses ML consensus predictor to determine if agents
    are converging, allowing safe early debate termination.

    Example:
        estimator = ConsensusEstimator()
        if estimator.should_terminate_early(responses, round_num=2):
            # Safe to end debate
            pass
    """

    def __init__(
        self,
        early_termination_threshold: float = 0.85,
        min_rounds: int = 2,
        enable_stability_detection: bool = False,
        stability_threshold: float = 0.85,
        stability_min_rounds: int = 2,
        stability_agreement_threshold: float = 0.75,
        stability_conflict_confidence: float = 0.7,
    ):
        """Initialize consensus estimator.

        Args:
            early_termination_threshold: Probability threshold for early stop
            min_rounds: Minimum rounds before allowing early termination
        """
        self.threshold = early_termination_threshold
        self.min_rounds = min_rounds
        self.enable_stability_detection = enable_stability_detection
        self.stability_threshold = stability_threshold
        self.stability_min_rounds = stability_min_rounds
        self.stability_conflict_confidence = stability_conflict_confidence
        self._predictor: Any | None = None
        self._similarity_history: list[float] = []
        self._agreement_history: list[float] = []
        self._last_stability: Any | None = None
        self._stability_detector: Any | None = None

        if self.enable_stability_detection:
            try:
                from aragora.debate.stability_detector import (
                    BetaBinomialStabilityDetector,
                    StabilityConfig,
                )

                config = StabilityConfig(stability_threshold=stability_agreement_threshold)
                self._stability_detector = BetaBinomialStabilityDetector(config=config)
            except ImportError:
                logger.warning("Stability detector not available")

    def _get_predictor(self):
        """Lazy load consensus predictor."""
        if self._predictor is None:
            try:
                from aragora.ml import get_consensus_predictor

                self._predictor = get_consensus_predictor()
            except ImportError:
                logger.warning("ML consensus predictor not available")
        return self._predictor

    def estimate_consensus(
        self,
        responses: Sequence[tuple[str, str]],
        context: str | None = None,
        current_round: int = 1,
        total_rounds: int = 3,
    ) -> dict[str, Any]:
        """Estimate consensus likelihood.

        Args:
            responses: List of (agent_id, text) tuples
            context: Optional task context
            current_round: Current debate round
            total_rounds: Total planned rounds

        Returns:
            Dict with probability, confidence, trend, and recommendation
        """
        predictor = self._get_predictor()
        if not predictor:
            return {
                "probability": 0.5,
                "confidence": 0.0,
                "trend": "unknown",
                "recommendation": "continue",
            }

        try:
            prediction = predictor.predict(
                responses=responses,
                context=context,
                current_round=current_round,
                total_rounds=total_rounds,
                previous_similarities=self._similarity_history,
            )

            # Update similarity history
            if "semantic_similarity" in prediction.features:
                self._similarity_history.append(prediction.features["semantic_similarity"])

            # Determine recommendation
            if prediction.early_termination_safe and current_round >= self.min_rounds:
                recommendation = "terminate"
            elif prediction.needs_intervention:
                recommendation = "intervene"
            else:
                recommendation = "continue"

            return {
                "probability": prediction.probability,
                "confidence": prediction.confidence,
                "trend": prediction.convergence_trend,
                "estimated_rounds": prediction.estimated_rounds,
                "key_factors": prediction.key_factors,
                "recommendation": recommendation,
            }

        except (ValueError, TypeError, KeyError) as e:
            logger.debug("Consensus estimation failed with data error: %s", e)
            return {
                "probability": 0.5,
                "confidence": 0.0,
                "trend": "unknown",
                "recommendation": "continue",
            }
        except (RuntimeError, AttributeError, ImportError, OSError, ConnectionError) as e:
            logger.warning("Unexpected consensus estimation error: %s", e)
            return {
                "probability": 0.5,
                "confidence": 0.0,
                "trend": "unknown",
                "recommendation": "continue",
            }

    def should_terminate_early(
        self,
        responses: Sequence[tuple[str, str]],
        current_round: int,
        total_rounds: int = 3,
        context: str | None = None,
    ) -> bool:
        """Check if debate should terminate early.

        Args:
            responses: Current round responses
            current_round: Current round number
            total_rounds: Total planned rounds
            context: Optional task context

        Returns:
            True if safe to terminate early
        """
        if current_round < self.min_rounds:
            return False

        stability_ok = False
        if self.enable_stability_detection and current_round >= self.stability_min_rounds:
            self._last_stability = self._calculate_stability(responses)
            if self._last_stability:
                stability_ok = self._last_stability.stability >= self.stability_threshold
                try:
                    from aragora.observability.metrics.debate import record_debate_stability

                    record_debate_stability(self._last_stability.stability)
                except (ImportError, AttributeError):
                    logger.debug("Failed to record debate stability metric", exc_info=True)

        estimate = self.estimate_consensus(
            responses=responses,
            context=context,
            current_round=current_round,
            total_rounds=total_rounds,
        )
        if estimate["recommendation"] == "terminate":
            try:
                from aragora.observability.metrics.debate import record_early_termination

                record_early_termination("ml")
            except (ImportError, AttributeError):
                logger.debug("Failed to record early termination metric", exc_info=True)
            return True

        if stability_ok and current_round >= self.min_rounds:
            # If ML predictor is confident we should continue, respect it.
            if (
                estimate.get("confidence", 0.0) >= self.stability_conflict_confidence
                and estimate.get("recommendation") != "terminate"
            ):
                return False
            try:
                from aragora.observability.metrics.debate import record_early_termination

                record_early_termination("stability")
            except (ImportError, AttributeError):
                logger.debug("Failed to record early termination metric", exc_info=True)
            return True

        return False

    def record_outcome(
        self,
        debate_id: str,
        reached_consensus: bool,
    ) -> None:
        """Record actual debate outcome for calibration.

        Args:
            debate_id: Debate identifier
            reached_consensus: Whether consensus was reached
        """
        predictor = self._get_predictor()
        if predictor:
            try:
                predictor.record_outcome(debate_id, reached_consensus)
            except (ValueError, TypeError, KeyError) as e:
                logger.debug("Failed to record outcome: %s", e)
            except (RuntimeError, AttributeError, ImportError, OSError, ConnectionError) as e:
                logger.warning("Unexpected error recording outcome: %s", e)

    def reset_history(self) -> None:
        """Reset similarity history for new debate."""
        self._similarity_history = []
        self._agreement_history = []
        self._last_stability = None

    def _calculate_stability(self, responses: Sequence[tuple[str, str]]) -> Any | None:
        if not self._stability_detector:
            return None
        agreement_score = self._calculate_agreement_score(responses)
        self._agreement_history.append(agreement_score)
        return self._stability_detector.calculate_stability(self._agreement_history)

    def _calculate_agreement_score(self, responses: Sequence[tuple[str, str]]) -> float:
        texts = [text for _, text in responses if text]
        if len(texts) < 2:
            return 1.0 if texts else 0.0

        token_sets = [set(t.lower().split()) for t in texts]
        similarities: list[float] = []
        for i in range(len(token_sets)):
            for j in range(i + 1, len(token_sets)):
                union = token_sets[i] | token_sets[j]
                if not union:
                    similarities.append(0.0)
                    continue
                intersection = token_sets[i] & token_sets[j]
                similarities.append(len(intersection) / len(union))
        return sum(similarities) / len(similarities) if similarities else 0.0


class MLEnhancedTeamSelector:
    """Team selector with ML-enhanced scoring.

    Combines traditional ELO/calibration scoring with
    ML-based agent routing for improved team selection.
    """

    def __init__(
        self,
        base_selector: TeamSelector,
        ml_delegation: MLDelegationStrategy | None = None,
        ml_weight: float = 0.3,
    ):
        """Initialize ML-enhanced selector.

        Args:
            base_selector: Base TeamSelector instance
            ml_delegation: ML delegation strategy
            ml_weight: Weight for ML scores (0-1)
        """
        self.base_selector = base_selector
        self.ml_delegation = ml_delegation or MLDelegationStrategy()
        self.ml_weight = ml_weight

    def select(
        self,
        agents: list[Agent],
        domain: str = "general",
        task: str = "",
        context: DebateContext | None = None,
    ) -> list[Agent]:
        """Select agents with ML-enhanced scoring.

        Args:
            agents: Candidate agents
            domain: Task domain
            task: Task description
            context: Debate context

        Returns:
            Agents sorted by combined score
        """
        if not task:
            # No task info, use base selector only
            return self.base_selector.select(agents, domain, task, context)

        # Get ML-based ordering
        ml_ordered = self.ml_delegation.select_agents(
            task=task,
            agents=agents,
            context=context,
        )

        # Get base selector ordering
        base_ordered = self.base_selector.select(agents, domain, task, context)

        # Combine scores
        combined_scores: dict[str, float] = {}

        for i, agent in enumerate(base_ordered):
            # Base score: higher rank = lower index = higher score
            base_score = 1.0 - (i / len(base_ordered))
            combined_scores[agent.name] = (1 - self.ml_weight) * base_score

        for i, agent in enumerate(ml_ordered):
            ml_score = 1.0 - (i / len(ml_ordered))
            combined_scores[agent.name] = (
                combined_scores.get(agent.name, 0) + self.ml_weight * ml_score
            )

        # Sort by combined score
        agent_map = {a.name: a for a in agents}
        sorted_names = sorted(
            combined_scores.keys(),
            key=lambda n: combined_scores[n],
            reverse=True,
        )

        return [agent_map[name] for name in sorted_names if name in agent_map]


def create_ml_team_selector(
    elo_system=None,
    calibration_tracker=None,
    circuit_breaker=None,
    ml_weight: float = 0.3,
) -> MLEnhancedTeamSelector:
    """Factory function to create ML-enhanced team selector.

    Args:
        elo_system: Optional ELO rating system
        calibration_tracker: Optional calibration tracker
        circuit_breaker: Optional circuit breaker
        ml_weight: Weight for ML scoring (0-1)

    Returns:
        Configured MLEnhancedTeamSelector
    """
    from aragora.debate.team_selector import TeamSelector

    base_selector = TeamSelector(
        elo_system=elo_system,
        calibration_tracker=calibration_tracker,
        circuit_breaker=circuit_breaker,
    )

    return MLEnhancedTeamSelector(
        base_selector=base_selector,
        ml_weight=ml_weight,
    )


# Export training data from debates
class DebateTrainingExporter:
    """Exports debate outcomes as training data for ML fine-tuning.

    Converts debate results into TrainingData format suitable
    for PEFT/LoRA training.

    Example:
        exporter = DebateTrainingExporter()
        training_data = exporter.export_debate(debate_result)
        training_data.to_jsonl("debates_training.jsonl")
    """

    def __init__(self):
        """Initialize exporter."""
        self._training_data = None

    def _get_training_data_class(self):
        """Lazy import TrainingData."""
        if self._training_data is None:
            try:
                from aragora.ml import TrainingData, TrainingExample

                self._training_data = (TrainingData, TrainingExample)
            except ImportError:
                logger.warning("ML training module not available")
        return self._training_data

    def export_debate(
        self,
        task: str,
        consensus_response: str,
        rejected_responses: list[str] | None = None,
        context: str = "",
    ) -> Any | None:
        """Export single debate as training example.

        Args:
            task: Debate task/question
            consensus_response: Final consensus response
            rejected_responses: Optional rejected alternatives
            context: Additional context

        Returns:
            TrainingData with single example, or None if unavailable
        """
        classes = self._get_training_data_class()
        if not classes:
            return None

        TrainingData, TrainingExample = classes

        data = TrainingData()
        data.add(
            TrainingExample.from_debate(
                task=task,
                winning_response=consensus_response,
                losing_response=rejected_responses[0] if rejected_responses else "",
                context=context,
            )
        )

        return data

    def export_debates_batch(
        self,
        debates: Sequence[dict[str, Any]],
    ) -> Any | None:
        """Export multiple debates as training data.

        Args:
            debates: List of debate dicts with task, consensus, rejected

        Returns:
            TrainingData with all examples
        """
        classes = self._get_training_data_class()
        if not classes:
            return None

        TrainingData, TrainingExample = classes

        data = TrainingData()
        for debate in debates:
            task = debate.get("task", "")
            consensus = debate.get("consensus", "")
            rejected = debate.get("rejected", [])
            context = debate.get("context", "")

            if task and consensus:
                data.add(
                    TrainingExample.from_debate(
                        task=task,
                        winning_response=consensus,
                        losing_response=rejected[0] if rejected else "",
                        context=context,
                    )
                )

        return data


# Singleton instances for convenience
_ml_delegation: MLDelegationStrategy | None = None
_quality_gate: QualityGate | None = None
_consensus_estimator: ConsensusEstimator | None = None
_training_exporter: DebateTrainingExporter | None = None


def get_ml_delegation() -> MLDelegationStrategy:
    """Get or create global ML delegation strategy."""
    global _ml_delegation
    if _ml_delegation is None:
        _ml_delegation = MLDelegationStrategy()
    return _ml_delegation


def get_quality_gate(threshold: float = 0.6) -> QualityGate:
    """Get or create global quality gate."""
    global _quality_gate
    if _quality_gate is None:
        _quality_gate = QualityGate(threshold=threshold)
    return _quality_gate


def get_consensus_estimator() -> ConsensusEstimator:
    """Get or create global consensus estimator."""
    global _consensus_estimator
    if _consensus_estimator is None:
        _consensus_estimator = ConsensusEstimator()
    return _consensus_estimator


def get_training_exporter() -> DebateTrainingExporter:
    """Get or create global training exporter."""
    global _training_exporter
    if _training_exporter is None:
        _training_exporter = DebateTrainingExporter()
    return _training_exporter
