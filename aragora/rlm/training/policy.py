"""
Policy interfaces for RLM training.

Provides abstract interfaces for context management policies that
can be trained with RL or supervised learning.

Usage:
    from aragora.rlm.training.policy import StrategyPolicy

    policy = StrategyPolicy(strategies=["peek", "grep", "partition_map"])
    strategy = policy.select_strategy(state)
"""

from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PolicyState:
    """
    State representation for policy decisions.

    Encapsulates the information available to the policy when
    making decisions about context management.
    """

    # Query information
    query: str = ""
    query_type: str = "general"  # general, factual, analytical, etc.

    # Context information
    context_tokens: int = 0
    abstraction_levels: int = 0
    source_type: str = "text"

    # Progress information
    iteration: int = 0
    tokens_examined: int = 0
    sub_calls_made: int = 0

    # Feedback from previous iteration
    previous_confidence: float = 0.0
    previous_ready: bool = True
    feedback: str | None = None

    # Features for ML models
    features: dict[str, float] = field(default_factory=dict)

    def to_feature_vector(self) -> list[float]:
        """Convert state to feature vector for ML models."""
        base_features = [
            self.context_tokens / 100000,  # Normalized token count
            self.abstraction_levels / 5,  # Normalized levels
            self.iteration / 10,  # Normalized iteration
            self.tokens_examined / 10000,  # Normalized tokens examined
            self.sub_calls_made / 10,  # Normalized sub-calls
            self.previous_confidence,
            1.0 if self.previous_ready else 0.0,
        ]

        # Add custom features
        extra_features = list(self.features.values())

        return base_features + extra_features


class Policy(ABC):
    """Abstract base class for RLM policies."""

    @abstractmethod
    def act(self, state: PolicyState) -> str:
        """
        Select an action given the current state.

        Args:
            state: Current policy state

        Returns:
            Action to take (strategy name, code, etc.)
        """
        pass

    @abstractmethod
    def get_action_probs(self, state: PolicyState) -> dict[str, float]:
        """
        Get probability distribution over actions.

        Args:
            state: Current policy state

        Returns:
            Dictionary mapping actions to probabilities
        """
        pass


class StrategyPolicy(Policy):
    """
    Policy for selecting decomposition strategies.

    Chooses between available strategies (peek, grep, partition_map, etc.)
    based on state features.
    """

    def __init__(
        self,
        strategies: list[str] | None = None,
        default_strategy: str = "auto",
        exploration_rate: float = 0.1,
    ):
        """
        Initialize strategy policy.

        Args:
            strategies: Available strategies
            default_strategy: Default strategy when uncertain
            exploration_rate: Probability of random exploration
        """
        self.strategies = strategies or [
            "peek",
            "grep",
            "partition_map",
            "summarize",
            "hierarchical",
        ]
        self.default_strategy = default_strategy
        self.exploration_rate = exploration_rate

        # Strategy selection weights (can be learned)
        self._weights: dict[str, dict[str, float]] = {strategy: {} for strategy in self.strategies}

    def act(self, state: PolicyState) -> str:
        """Select strategy based on state."""
        # Epsilon-greedy exploration
        if random.random() < self.exploration_rate:
            return random.choice(self.strategies)

        probs = self.get_action_probs(state)
        return max(probs.keys(), key=lambda k: probs[k])

    def get_action_probs(self, state: PolicyState) -> dict[str, float]:
        """Get probability distribution over strategies."""
        scores = {}

        for strategy in self.strategies:
            scores[strategy] = self._compute_strategy_score(strategy, state)

        # Softmax normalization
        total = sum(scores.values())
        if total == 0:
            return {s: 1.0 / len(self.strategies) for s in self.strategies}

        return {s: score / total for s, score in scores.items()}

    def _compute_strategy_score(self, strategy: str, state: PolicyState) -> float:
        """Compute score for a strategy given state."""
        score = 1.0  # Base score

        # Heuristic scoring based on state
        if strategy == "peek":
            # Good for unknown structure
            if state.iteration == 0 and state.tokens_examined == 0:
                score += 1.0
        elif strategy == "grep":
            # Good for specific lookups
            if state.query_type == "factual":
                score += 1.0
        elif strategy == "partition_map":
            # Good for large contexts
            if state.context_tokens > 50000:
                score += 1.0
        elif strategy == "summarize":
            # Good for analytical queries
            if state.query_type == "analytical":
                score += 1.0
        elif strategy == "hierarchical":
            # Good when hierarchy is available
            if state.abstraction_levels > 2:
                score += 1.0

        # Apply learned weights if available
        weights = self._weights.get(strategy, {})
        for feature, weight in weights.items():
            if feature in state.features:
                score += weight * state.features[feature]

        return max(0.01, score)  # Ensure positive

    def update_weights(
        self,
        strategy: str,
        feature: str,
        delta: float,
        learning_rate: float = 0.01,
    ) -> None:
        """Update weight for a strategy-feature pair."""
        if strategy not in self._weights:
            self._weights[strategy] = {}
        current = self._weights[strategy].get(feature, 0.0)
        self._weights[strategy][feature] = current + learning_rate * delta


class RefinementPolicy(Policy):
    """
    Policy for deciding when to continue refinement.

    Decides whether to:
    - Continue refining (ready=False)
    - Accept current answer (ready=True)
    - Request specific feedback type
    """

    def __init__(
        self,
        confidence_threshold: float = 0.8,
        max_iterations: int = 5,
    ):
        """
        Initialize refinement policy.

        Args:
            confidence_threshold: Minimum confidence to accept answer
            max_iterations: Maximum iterations before forcing acceptance
        """
        self.confidence_threshold = confidence_threshold
        self.max_iterations = max_iterations

    def act(self, state: PolicyState) -> str:
        """Decide whether to continue refinement."""
        # Force acceptance at max iterations
        if state.iteration >= self.max_iterations - 1:
            return "accept"

        # Accept if confidence is high
        if state.previous_confidence >= self.confidence_threshold:
            return "accept"

        # Continue if low confidence
        if state.previous_confidence < 0.5:
            return "refine"

        # Borderline case - decide based on progress
        if state.tokens_examined > state.context_tokens * 0.5:
            # Already examined lots of context
            return "accept"

        return "refine"

    def get_action_probs(self, state: PolicyState) -> dict[str, float]:
        """Get probability distribution over refinement decisions."""
        if state.iteration >= self.max_iterations - 1:
            return {"accept": 1.0, "refine": 0.0}

        # Sigmoid-like probability based on confidence
        import math

        confidence = state.previous_confidence
        accept_prob = 1 / (1 + math.exp(-10 * (confidence - self.confidence_threshold)))

        return {
            "accept": accept_prob,
            "refine": 1 - accept_prob,
        }


@dataclass
class CompositePolicy(Policy):
    """
    Composite policy combining multiple sub-policies.

    Useful for hierarchical decision making (e.g., first select strategy,
    then decide refinement).
    """

    policies: dict[str, Policy] = field(default_factory=dict)
    selection_order: list[str] = field(default_factory=list)

    def add_policy(self, name: str, policy: Policy) -> None:
        """Add a sub-policy."""
        self.policies[name] = policy
        if name not in self.selection_order:
            self.selection_order.append(name)

    def act(self, state: PolicyState) -> str:
        """Execute policies in order and return combined action."""
        actions = []
        for name in self.selection_order:
            if name in self.policies:
                action = self.policies[name].act(state)
                actions.append(f"{name}:{action}")
        return "|".join(actions)

    def get_action_probs(self, state: PolicyState) -> dict[str, float]:
        """Get combined action probabilities."""
        # For composite, return first policy's probs
        if self.selection_order and self.selection_order[0] in self.policies:
            return self.policies[self.selection_order[0]].get_action_probs(state)
        return {}

    def get_policy(self, name: str) -> Policy | None:
        """Get a specific sub-policy."""
        return self.policies.get(name)


__all__ = [
    "PolicyState",
    "Policy",
    "StrategyPolicy",
    "RefinementPolicy",
    "CompositePolicy",
]
