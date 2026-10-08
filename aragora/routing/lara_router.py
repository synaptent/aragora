"""
LaRA: Large Language Model Retrieval Augmented Router.

Based on: Hybrid retrieval routing concepts from recent research.

This module implements intelligent routing between retrieval strategies:
- RAG: Vector-based semantic retrieval for factual queries
- RLM: Recursive Language Model for complex multi-step reasoning
- Long-Context: Full document context for holistic analysis
- Graph: Relationship-based retrieval for connected knowledge
- Hybrid: Combination of strategies for complex queries

Key insight: Different query types benefit from different retrieval strategies.
Factual lookups -> RAG, Complex reasoning -> RLM, Connected concepts -> Graph.
"""

from dataclasses import dataclass, field
from statistics import fmean
from typing import Any
from enum import Enum
import logging
import re
import time

logger = logging.getLogger(__name__)


class RetrievalMode(Enum):
    """Available retrieval modes."""

    RAG = "rag"  # Vector-based semantic retrieval
    RLM = "rlm"  # Recursive Language Model with iterative refinement
    LONG_CONTEXT = "long_context"  # Full document context window
    GRAPH = "graph"  # Graph-based relationship traversal
    HYBRID = "hybrid"  # Combination of multiple strategies


@dataclass
class QueryFeatures:
    """Features extracted from a query for routing decisions."""

    is_factual: bool  # Likely a factual lookup (what, when, who)
    is_analytical: bool  # Requires analysis/reasoning (why, how, compare)
    is_multi_hop: bool  # Requires connecting multiple concepts
    requires_aggregation: bool  # Needs to aggregate from multiple sources
    length_tokens: int  # Approximate query length in tokens
    has_temporal_markers: bool  # Contains time-related terms
    entity_count: int  # Number of named entities detected
    complexity_score: float  # Overall complexity (0-1)


@dataclass
class RoutingDecision:
    """Result of routing decision."""

    selected_mode: RetrievalMode
    confidence: float  # 0.0-1.0
    fallback_mode: RetrievalMode | None  # If primary fails
    reasoning: str  # Explanation of decision
    query_features: QueryFeatures
    doc_tokens: int  # Document context size considered
    duration_ms: float = 0.0  # Time to make decision


@dataclass
class LaRAConfig:
    """Configuration for LaRA router."""

    # Document size thresholds (in tokens)
    long_context_min_tokens: int = 50000
    long_context_max_tokens: int = 200000  # Claude's context limit

    # Complexity thresholds
    multi_hop_threshold: float = 0.6
    analytical_threshold: float = 0.5

    # Feature weights for mode selection
    rag_weight_factual: float = 0.8
    rlm_weight_analytical: float = 0.7
    graph_weight_multi_hop: float = 0.75

    # Confidence thresholds
    min_confidence_for_primary: float = 0.6
    hybrid_confidence_threshold: float = 0.5  # Below this, use hybrid

    # Feature extraction settings
    factual_keywords: set[str] = field(
        default_factory=lambda: {
            "what",
            "when",
            "where",
            "who",
            "which",
            "how much",
            "how many",
            "define",
            "definition",
            "meaning",
            "is",
            "are",
            "was",
            "were",
        }
    )
    analytical_keywords: set[str] = field(
        default_factory=lambda: {
            "why",
            "how",
            "explain",
            "analyze",
            "compare",
            "contrast",
            "evaluate",
            "assess",
            "impact",
            "effect",
            "cause",
            "reason",
            "implications",
            "consequences",
            "advantages",
            "disadvantages",
        }
    )
    multi_hop_keywords: set[str] = field(
        default_factory=lambda: {
            "relationship",
            "connection",
            "related",
            "linked",
            "between",
            "leads to",
            "results in",
            "caused by",
            "depends on",
            "affects",
        }
    )


class LaRARouter:
    """
    Routes queries to optimal retrieval strategy.

    The router analyzes query characteristics and available document context
    to select the most appropriate retrieval mode.

    Example:
        router = LaRARouter()

        # Route a query
        decision = router.route(
            query="Why did World War I start and how did it affect Europe?",
            doc_tokens=75000,
            available_modes={RetrievalMode.RAG, RetrievalMode.RLM, RetrievalMode.GRAPH},
        )

        if decision.selected_mode == RetrievalMode.RLM:
            result = await rlm_retrieve(query)
        elif decision.selected_mode == RetrievalMode.RAG:
            result = await rag_retrieve(query)
        # ...
    """

    def __init__(self, config: LaRAConfig | None = None):
        """Initialize the router.

        Args:
            config: Configuration options. Uses defaults if not provided.
        """
        self.config = config or LaRAConfig()
        self._decision_history: list[RoutingDecision] = []

    def route(
        self,
        query: str,
        doc_tokens: int,
        available_modes: set[RetrievalMode] | None = None,
        override_mode: RetrievalMode | None = None,
    ) -> RoutingDecision:
        """
        Route a query to the optimal retrieval mode.

        Args:
            query: The user's query text
            doc_tokens: Size of available document context in tokens
            available_modes: Set of modes available for this query
            override_mode: Force a specific mode (for testing/auditing)

        Returns:
            RoutingDecision with selected mode and confidence
        """
        start_time = time.time()

        # Default to all modes available
        if available_modes is None:
            available_modes = set(RetrievalMode)

        # Extract query features
        features = self._extract_features(query)

        # Handle override
        if override_mode is not None:
            decision = RoutingDecision(
                selected_mode=override_mode,
                confidence=1.0,
                fallback_mode=None,
                reasoning=f"Mode override: {override_mode.value}",
                query_features=features,
                doc_tokens=doc_tokens,
                duration_ms=(time.time() - start_time) * 1000,
            )
            self._decision_history.append(decision)
            return decision

        # Calculate mode scores
        mode_scores = self._calculate_mode_scores(
            features=features,
            doc_tokens=doc_tokens,
            available_modes=available_modes,
        )

        # Select best mode
        selected_mode, confidence = self._select_best_mode(mode_scores)

        # Determine fallback
        fallback_mode = self._select_fallback(
            primary_mode=selected_mode,
            mode_scores=mode_scores,
        )

        # Generate reasoning
        reasoning = self._generate_reasoning(
            features=features,
            selected_mode=selected_mode,
            mode_scores=mode_scores,
        )

        decision = RoutingDecision(
            selected_mode=selected_mode,
            confidence=confidence,
            fallback_mode=fallback_mode,
            reasoning=reasoning,
            query_features=features,
            doc_tokens=doc_tokens,
            duration_ms=(time.time() - start_time) * 1000,
        )

        self._decision_history.append(decision)

        logger.debug(
            "routing_decision query_len=%d mode=%s conf=%.3f fallback=%s "
            "doc_tokens=%d features=[factual=%s analytical=%s multi_hop=%s]",
            len(query),
            selected_mode.value,
            confidence,
            fallback_mode.value if fallback_mode else "none",
            doc_tokens,
            features.is_factual,
            features.is_analytical,
            features.is_multi_hop,
        )

        return decision

    def _extract_features(self, query: str) -> QueryFeatures:
        """Extract routing-relevant features from query."""
        query_lower = query.lower()
        words = set(query_lower.split())

        # Check for factual query markers
        is_factual = bool(words & self.config.factual_keywords)

        # Check for analytical query markers
        is_analytical = bool(words & self.config.analytical_keywords)

        # Check for multi-hop markers
        is_multi_hop = bool(words & self.config.multi_hop_keywords)

        # Check for aggregation needs
        requires_aggregation = any(
            kw in query_lower for kw in ["all", "every", "each", "list", "enumerate", "summarize"]
        )

        # Estimate token count (rough: 1 token ≈ 4 chars)
        length_tokens = len(query) // 4

        # Check temporal markers
        has_temporal_markers = bool(
            re.search(
                r"\b(when|date|year|month|day|time|before|after|during|since|until)\b",
                query_lower,
            )
        )

        # Simple entity detection (capitalized words not at sentence start)
        entity_count = len(
            [
                w
                for w in query.split()[1:]  # Skip first word
                if w[0].isupper() and not w.isupper()  # Skip all-caps
            ]
        )

        # Calculate complexity score
        complexity_score = self._calculate_complexity(
            is_factual=is_factual,
            is_analytical=is_analytical,
            is_multi_hop=is_multi_hop,
            requires_aggregation=requires_aggregation,
            length_tokens=length_tokens,
            entity_count=entity_count,
        )

        return QueryFeatures(
            is_factual=is_factual,
            is_analytical=is_analytical,
            is_multi_hop=is_multi_hop,
            requires_aggregation=requires_aggregation,
            length_tokens=length_tokens,
            has_temporal_markers=has_temporal_markers,
            entity_count=entity_count,
            complexity_score=complexity_score,
        )

    def _calculate_complexity(
        self,
        is_factual: bool,
        is_analytical: bool,
        is_multi_hop: bool,
        requires_aggregation: bool,
        length_tokens: int,
        entity_count: int,
    ) -> float:
        """Calculate overall query complexity score."""
        score = 0.0

        # Analytical queries are more complex
        if is_analytical:
            score += 0.3

        # Multi-hop requires connecting concepts
        if is_multi_hop:
            score += 0.25

        # Aggregation adds complexity
        if requires_aggregation:
            score += 0.15

        # Longer queries tend to be more complex
        if length_tokens > 50:
            score += 0.1
        elif length_tokens > 100:
            score += 0.2

        # More entities = more complex
        if entity_count > 2:
            score += 0.1 * min(entity_count - 2, 3)

        # Factual queries are simpler
        if is_factual and not is_analytical:
            score -= 0.2

        return float(min(max(score, 0.0), 1.0))

    def _calculate_mode_scores(
        self,
        features: QueryFeatures,
        doc_tokens: int,
        available_modes: set[RetrievalMode],
    ) -> dict[RetrievalMode, float]:
        """Calculate suitability scores for each mode."""
        scores: dict[RetrievalMode, float] = {}

        for mode in available_modes:
            scores[mode] = self._score_mode(mode, features, doc_tokens)

        return scores

    def _score_mode(
        self,
        mode: RetrievalMode,
        features: QueryFeatures,
        doc_tokens: int,
    ) -> float:
        """Calculate suitability score for a specific mode."""
        score = 0.5  # Base score

        if mode == RetrievalMode.RAG:
            # RAG is good for factual lookups
            if features.is_factual:
                score += self.config.rag_weight_factual * 0.3
            # Less suitable for complex analytical queries
            if features.is_analytical:
                score -= 0.2
            if features.is_multi_hop:
                score -= 0.15

        elif mode == RetrievalMode.RLM:
            # RLM excels at analytical, multi-step reasoning
            if features.is_analytical:
                score += self.config.rlm_weight_analytical * 0.35
            if features.complexity_score > 0.5:
                score += 0.2
            # Good for longer, complex queries
            if features.length_tokens > 30:
                score += 0.1

        elif mode == RetrievalMode.LONG_CONTEXT:
            # Long context for large documents with holistic queries
            if (
                doc_tokens >= self.config.long_context_min_tokens
                and doc_tokens <= self.config.long_context_max_tokens
            ):
                score += 0.3
            else:
                score -= 0.3  # Penalize if document doesn't fit criteria

            # Good for aggregation across large docs
            if features.requires_aggregation:
                score += 0.15

        elif mode == RetrievalMode.GRAPH:
            # Graph for multi-hop, relationship queries
            if features.is_multi_hop:
                score += self.config.graph_weight_multi_hop * 0.35
            if features.entity_count > 2:
                score += 0.15  # Multiple entities suggest relationships

        elif mode == RetrievalMode.HYBRID:
            # Hybrid when single mode isn't clear winner
            # Score based on overall complexity
            score = 0.5 + features.complexity_score * 0.3

        return float(min(max(score, 0.0), 1.0))

    def _select_best_mode(
        self,
        mode_scores: dict[RetrievalMode, float],
    ) -> tuple[RetrievalMode, float]:
        """Select the best mode from scores."""
        if not mode_scores:
            return RetrievalMode.RAG, 0.5  # Default fallback

        # Sort by score
        sorted_modes = sorted(
            mode_scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        best_mode, best_score = sorted_modes[0]

        # If confidence is low, consider hybrid
        if (
            best_score < self.config.hybrid_confidence_threshold
            and RetrievalMode.HYBRID in mode_scores
        ):
            return RetrievalMode.HYBRID, best_score

        return best_mode, best_score

    def _select_fallback(
        self,
        primary_mode: RetrievalMode,
        mode_scores: dict[RetrievalMode, float],
    ) -> RetrievalMode | None:
        """Select a fallback mode if primary fails."""
        # Sort modes by score, excluding primary
        candidates = [
            (mode, score)
            for mode, score in mode_scores.items()
            if mode != primary_mode and score >= 0.4
        ]

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def _generate_reasoning(
        self,
        features: QueryFeatures,
        selected_mode: RetrievalMode,
        mode_scores: dict[RetrievalMode, float],
    ) -> str:
        """Generate human-readable reasoning for the routing decision."""
        reasons = []

        if selected_mode == RetrievalMode.RAG:
            if features.is_factual:
                reasons.append("Query appears factual (suitable for vector retrieval)")
            reasons.append("RAG provides efficient lookup for targeted information")

        elif selected_mode == RetrievalMode.RLM:
            if features.is_analytical:
                reasons.append("Query requires analysis (RLM excels at reasoning)")
            if features.complexity_score > 0.5:
                reasons.append(
                    f"High complexity ({features.complexity_score:.2f}) "
                    "benefits from iterative refinement"
                )

        elif selected_mode == RetrievalMode.LONG_CONTEXT:
            reasons.append("Document size suitable for full-context window")
            if features.requires_aggregation:
                reasons.append("Query needs aggregation across document")

        elif selected_mode == RetrievalMode.GRAPH:
            if features.is_multi_hop:
                reasons.append("Multi-hop query benefits from graph traversal")
            if features.entity_count > 2:
                reasons.append(
                    f"Multiple entities ({features.entity_count}) suggest relationship exploration"
                )

        elif selected_mode == RetrievalMode.HYBRID:
            reasons.append("No single mode is strongly preferred")
            reasons.append("Hybrid approach combines multiple strategies")

        # Add score context
        score = mode_scores.get(selected_mode, 0.0)
        reasons.append(f"Mode score: {score:.2f}")

        return "; ".join(reasons)

    def reset(self) -> None:
        """Reset router state."""
        self._decision_history.clear()

    def get_metrics(self) -> dict[str, Any]:
        """Get router metrics for telemetry."""
        if not self._decision_history:
            return {
                "total_decisions": 0,
                "mode_distribution": {},
                "avg_confidence": 0.0,
                "avg_latency_ms": 0.0,
            }

        mode_counts: dict[str, int] = {}
        for d in self._decision_history:
            mode = d.selected_mode.value
            mode_counts[mode] = mode_counts.get(mode, 0) + 1

        total = len(self._decision_history)

        return {
            "total_decisions": total,
            "mode_distribution": {mode: count / total for mode, count in mode_counts.items()},
            "mode_counts": mode_counts,
            "avg_confidence": fmean(d.confidence for d in self._decision_history),
            "avg_latency_ms": fmean(d.duration_ms for d in self._decision_history),
        }


# Convenience functions for common use cases


def create_lara_router(
    long_context_threshold: int = 50000,
    **kwargs: Any,
) -> LaRARouter:
    """Create a LaRA router with common configuration.

    Args:
        long_context_threshold: Min tokens to consider long-context mode
        **kwargs: Additional config options

    Returns:
        Configured LaRARouter
    """
    config = LaRAConfig(
        long_context_min_tokens=long_context_threshold,
        **kwargs,
    )
    return LaRARouter(config)


def quick_route(
    query: str,
    doc_tokens: int = 10000,
) -> RetrievalMode:
    """
    Quick routing decision without full configuration.

    Args:
        query: The query text
        doc_tokens: Document context size

    Returns:
        Recommended RetrievalMode
    """
    router = LaRARouter()
    decision = router.route(query=query, doc_tokens=doc_tokens)
    return decision.selected_mode
