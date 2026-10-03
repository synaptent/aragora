"""
Cost Optimization Engine.

Analyzes usage patterns and generates actionable recommendations
to reduce AI model costs while maintaining quality.

Components:
- ModelDowngradeAnalyzer: Identifies opportunities to use cheaper models
- CachingRecommender: Detects repeated queries for caching
- BatchingOptimizer: Identifies batchable operations
- CostOptimizer: Main orchestrator for all analyzers
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from aragora.billing.recommendations import (
    BatchingOpportunity,
    CachingOpportunity,
    ImplementationStep,
    ModelAlternative,
    OptimizationRecommendation,
    RecommendationPriority,
    RecommendationStatus,
    RecommendationSummary,
    RecommendationType,
)
from aragora.billing.usage import PROVIDER_PRICING

if TYPE_CHECKING:
    from aragora.billing.cost_tracker import CostTracker, TokenUsage

logger = logging.getLogger(__name__)

# Model capability tiers for downgrade analysis
MODEL_TIERS: dict[str, dict[str, Any]] = {
    # Tier 1: Most capable (complex reasoning, coding)
    "claude-fable-5": {"tier": 1, "provider": "anthropic", "quality": 1.0},
    "claude-opus-5": {"tier": 1, "provider": "anthropic", "quality": 1.0},
    "claude-opus-4-8": {"tier": 1, "provider": "anthropic", "quality": 1.0},
    "claude-opus-4-7": {"tier": 1, "provider": "anthropic", "quality": 1.0},
    "claude-opus-4.8": {"tier": 1, "provider": "anthropic", "quality": 1.0},
    "claude-opus-4.7": {"tier": 1, "provider": "anthropic", "quality": 1.0},
    "claude-opus-4": {"tier": 1, "provider": "anthropic", "quality": 1.0},
    "gpt-5.6-sol": {"tier": 1, "provider": "openai", "quality": 0.99},
    "gpt-5.5": {"tier": 1, "provider": "openai", "quality": 0.98},
    "gpt-4o": {"tier": 1, "provider": "openai", "quality": 0.95},
    # Tier 2: Balanced (most tasks)
    "claude-sonnet-4": {"tier": 2, "provider": "anthropic", "quality": 0.85},
    "gemini-pro": {"tier": 2, "provider": "google", "quality": 0.80},
    "deepseek-v4-pro": {"tier": 2, "provider": "deepseek", "quality": 0.78},
    # Tier 3: Fast/cheap (simple tasks)
    "gpt-4o-mini": {"tier": 3, "provider": "openai", "quality": 0.70},
    "claude-haiku-3": {"tier": 3, "provider": "anthropic", "quality": 0.65},
    "claude-haiku-4-5": {"tier": 3, "provider": "anthropic", "quality": 0.65},
    "claude-haiku-4.5": {"tier": 3, "provider": "anthropic", "quality": 0.65},
    "claude-haiku-4-5-20251001": {
        "tier": 3,
        "provider": "anthropic",
        "quality": 0.65,
    },
    "deepseek-v3": {"tier": 3, "provider": "deepseek", "quality": 0.75},
    "gemini-3.5-flash": {"tier": 3, "provider": "google", "quality": 0.72},
}

# Task complexity indicators
SIMPLE_TASK_INDICATORS = [
    "summarize",
    "extract",
    "classify",
    "format",
    "translate",
    "list",
    "simple",
]
COMPLEX_TASK_INDICATORS = [
    "analyze",
    "reason",
    "code",
    "debug",
    "architect",
    "design",
    "complex",
]


@dataclass
class UsagePattern:
    """Aggregated usage pattern for analysis."""

    model: str
    provider: str
    operation: str
    count: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost: Decimal = Decimal("0")
    avg_tokens_in: float = 0.0
    avg_tokens_out: float = 0.0
    avg_latency_ms: float = 0.0


@dataclass
class ModelDowngradeAnalyzer:
    """
    Analyzes usage to identify model downgrade opportunities.

    Identifies cases where expensive models are used for tasks
    that could be handled by cheaper alternatives.
    """

    min_cost_threshold: Decimal = Decimal("1.00")  # Min cost to consider
    min_sample_size: int = 10  # Min requests to analyze
    quality_threshold: float = 0.7  # Min acceptable quality

    def analyze(
        self,
        patterns: list[UsagePattern],
        workspace_id: str,
    ) -> list[OptimizationRecommendation]:
        """Analyze patterns and generate downgrade recommendations."""
        recommendations = []

        for pattern in patterns:
            if pattern.count < self.min_sample_size:
                continue
            if pattern.total_cost < self.min_cost_threshold:
                continue

            model_info = MODEL_TIERS.get(pattern.model)
            if not model_info or model_info["tier"] == 3:
                # Already using cheapest tier
                continue

            # Check if operation seems simple
            is_simple = self._is_simple_operation(pattern.operation)
            if not is_simple and model_info["tier"] == 2:
                # Complex operation on mid-tier, may be appropriate
                continue

            # Find cheaper alternatives
            alternatives = self._find_alternatives(pattern, model_info["tier"])
            if not alternatives:
                continue

            best_alt = alternatives[0]
            projected_cost = self._calculate_projected_cost(pattern, best_alt)

            rec = OptimizationRecommendation(
                type=RecommendationType.MODEL_DOWNGRADE,
                priority=self._calculate_priority(pattern.total_cost, projected_cost),
                workspace_id=workspace_id,
                current_cost_usd=pattern.total_cost,
                projected_cost_usd=projected_cost,
                confidence_score=0.75 if is_simple else 0.5,
                affected_agents=[],
                affected_operations=[pattern.operation],
                title=f"Use {best_alt.model} instead of {pattern.model}",
                description=(
                    f"The operation '{pattern.operation}' uses {pattern.model} "
                    f"({pattern.count} requests). Consider using {best_alt.model} "
                    f"which costs {(1 - best_alt.quality_score) * 100:.0f}% less "
                    f"with minimal quality impact."
                ),
                rationale=(
                    f"Analysis of {pattern.count} requests shows this operation "
                    f"has low complexity and doesn't require {pattern.model}'s "
                    f"advanced capabilities."
                ),
                model_alternative=best_alt,
                implementation_steps=[
                    ImplementationStep(
                        order=1,
                        description=f"Update agent configuration to use {best_alt.model}",
                        config_change={
                            "model": best_alt.model,
                            "provider": best_alt.provider,
                        },
                        estimated_effort="low",
                    ),
                    ImplementationStep(
                        order=2,
                        description="Monitor quality metrics for 24 hours",
                        estimated_effort="low",
                    ),
                    ImplementationStep(
                        order=3,
                        description="Roll back if quality degrades significantly",
                        estimated_effort="low",
                    ),
                ],
                auto_apply_available=True,
                quality_impact=f"Estimated {(1 - best_alt.quality_score) * 100:.0f}% quality reduction",
                quality_impact_score=1 - best_alt.quality_score,
                risk_level="low" if is_simple else "medium",
            )
            recommendations.append(rec)

        return recommendations

    def _is_simple_operation(self, operation: str) -> bool:
        """Determine if an operation is likely simple."""
        op_lower = operation.lower()
        simple_score = sum(1 for ind in SIMPLE_TASK_INDICATORS if ind in op_lower)
        complex_score = sum(1 for ind in COMPLEX_TASK_INDICATORS if ind in op_lower)
        return simple_score > complex_score

    def _find_alternatives(
        self,
        pattern: UsagePattern,
        current_tier: int,
    ) -> list[ModelAlternative]:
        """Find cheaper model alternatives."""
        alternatives = []

        for model, info in MODEL_TIERS.items():
            if info["tier"] <= current_tier:
                continue
            if info["quality"] < self.quality_threshold:
                continue

            # Get pricing
            provider_prices = PROVIDER_PRICING.get(info["provider"], PROVIDER_PRICING["openrouter"])
            input_key = model if model in provider_prices else "default"
            output_key = (
                f"{model}-output" if f"{model}-output" in provider_prices else "default-output"
            )

            input_price = provider_prices.get(input_key, Decimal("2.00"))
            output_price = provider_prices.get(output_key, Decimal("8.00"))

            alternatives.append(
                ModelAlternative(
                    provider=info["provider"],
                    model=model,
                    cost_per_1k_input=input_price / 1000,
                    cost_per_1k_output=output_price / 1000,
                    quality_score=info["quality"],
                    latency_multiplier=1.5 if info["tier"] == 3 else 1.2,
                    suitable_for=["simple_tasks", "high_volume"],
                )
            )

        # Sort by cost (cheapest first)
        alternatives.sort(key=lambda x: x.cost_per_1k_input + x.cost_per_1k_output)
        return alternatives

    def _calculate_projected_cost(
        self,
        pattern: UsagePattern,
        alternative: ModelAlternative,
    ) -> Decimal:
        """Calculate projected cost with alternative model."""
        input_cost = (
            Decimal(pattern.total_tokens_in) / Decimal("1000") * alternative.cost_per_1k_input
        )
        output_cost = (
            Decimal(pattern.total_tokens_out) / Decimal("1000") * alternative.cost_per_1k_output
        )
        return input_cost + output_cost

    def _calculate_priority(
        self,
        current_cost: Decimal,
        projected_cost: Decimal,
    ) -> RecommendationPriority:
        """Calculate recommendation priority based on savings."""
        savings = current_cost - projected_cost
        if savings >= Decimal("100"):
            return RecommendationPriority.CRITICAL
        elif savings >= Decimal("25"):
            return RecommendationPriority.HIGH
        elif savings >= Decimal("5"):
            return RecommendationPriority.MEDIUM
        return RecommendationPriority.LOW


@dataclass
class CachingRecommender:
    """
    Identifies caching opportunities from repeated queries.

    Analyzes request patterns to detect:
    - Identical prompts (exact caching)
    - Similar prompts (semantic caching)
    - Common prefixes (prefix caching)
    """

    min_repeat_count: int = 5  # Min repeats to recommend caching
    min_cost_saved: Decimal = Decimal("0.50")  # Min savings to recommend

    def analyze(
        self,
        usage_data: list[TokenUsage],
        workspace_id: str,
    ) -> list[OptimizationRecommendation]:
        """Analyze usage for caching opportunities."""
        recommendations = []

        # Group by operation type
        by_operation: dict[str, list[TokenUsage]] = defaultdict(list)
        for usage in usage_data:
            by_operation[usage.operation].append(usage)

        for operation, usages in by_operation.items():
            if len(usages) < self.min_repeat_count:
                continue

            # Estimate repeat rate (simplified - real impl would hash prompts)
            # Assume operations with same token counts are repeats
            token_signatures: dict[tuple[int, int], int] = defaultdict(int)
            for usage in usages:
                sig = (usage.tokens_in // 100, usage.tokens_out // 100)  # Bucket
                token_signatures[sig] += 1

            max_repeats = max(token_signatures.values()) if token_signatures else 0
            if max_repeats < self.min_repeat_count:
                continue

            # Calculate potential savings
            total_cost = sum(u.cost_usd for u in usages)
            repeat_ratio = max_repeats / len(usages)
            potential_savings = total_cost * Decimal(str(repeat_ratio * 0.9))  # 90% hit rate

            if potential_savings < self.min_cost_saved:
                continue

            opportunity = CachingOpportunity(
                pattern="repeated_query",
                estimated_hit_rate=repeat_ratio * 0.9,
                unique_queries=len(token_signatures),
                repeat_count=max_repeats,
                cache_strategy="exact" if repeat_ratio > 0.8 else "semantic",
            )

            rec = OptimizationRecommendation(
                type=RecommendationType.CACHING,
                priority=self._calculate_priority(potential_savings),
                workspace_id=workspace_id,
                current_cost_usd=Decimal(str(total_cost)),
                projected_cost_usd=Decimal(str(total_cost - potential_savings)),
                confidence_score=0.7,
                affected_operations=[operation],
                title=f"Enable caching for '{operation}'",
                description=(
                    f"Detected {max_repeats} repeated requests in '{operation}'. "
                    f"Enabling {opportunity.cache_strategy} caching could save "
                    f"${potential_savings:.2f} ({repeat_ratio * 100:.0f}% of costs)."
                ),
                rationale=(
                    f"Analysis shows {repeat_ratio * 100:.0f}% of requests "
                    f"have similar token patterns, indicating repeated queries."
                ),
                caching_opportunity=opportunity,
                implementation_steps=[
                    ImplementationStep(
                        order=1,
                        description="Enable prompt caching in agent configuration",
                        config_change={"enable_cache": True, "cache_ttl": 3600},
                        estimated_effort="low",
                    ),
                    ImplementationStep(
                        order=2,
                        description="Monitor cache hit rate for effectiveness",
                        estimated_effort="low",
                    ),
                ],
                auto_apply_available=True,
                quality_impact="No quality impact - responses are identical",
                quality_impact_score=0.0,
                risk_level="low",
            )
            recommendations.append(rec)

        return recommendations

    def _calculate_priority(self, savings: Decimal) -> RecommendationPriority:
        """Calculate priority based on potential savings."""
        if savings >= Decimal("50"):
            return RecommendationPriority.HIGH
        elif savings >= Decimal("10"):
            return RecommendationPriority.MEDIUM
        return RecommendationPriority.LOW


@dataclass
class BatchingOptimizer:
    """
    Identifies opportunities to batch API requests.

    Analyzes request timing to find operations that could
    be batched together for efficiency.
    """

    min_requests_per_hour: int = 20  # Min requests to consider batching
    optimal_batch_size: int = 10  # Target batch size

    def analyze(
        self,
        usage_data: list[TokenUsage],
        workspace_id: str,
    ) -> list[OptimizationRecommendation]:
        """Analyze usage for batching opportunities."""
        recommendations = []

        # Group by operation and hour
        by_operation_hour: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        total_by_operation: dict[str, int] = defaultdict(int)

        for usage in usage_data:
            hour_key = usage.timestamp.strftime("%Y-%m-%d-%H")
            by_operation_hour[usage.operation][hour_key] += 1
            total_by_operation[usage.operation] += 1

        for operation, hour_counts in by_operation_hour.items():
            if not hour_counts:
                continue

            avg_per_hour = sum(hour_counts.values()) / len(hour_counts)
            if avg_per_hour < self.min_requests_per_hour:
                continue

            # Current effective batch size is 1 (individual requests)
            # Estimate savings from batching - 15% overhead reduction
            total_requests = total_by_operation[operation]
            overhead_reduction = 0.15

            # Find sample usage for cost calculation
            sample_usages = [u for u in usage_data if u.operation == operation][:100]
            if not sample_usages:
                continue

            avg_cost_per_request = sum((u.cost_usd for u in sample_usages), Decimal("0")) / len(
                sample_usages
            )
            total_cost = avg_cost_per_request * total_requests
            savings = total_cost * Decimal(str(overhead_reduction))

            if savings < Decimal("1.00"):
                continue

            opportunity = BatchingOpportunity(
                operation_type=operation,
                current_batch_size=1,
                optimal_batch_size=self.optimal_batch_size,
                requests_per_hour=int(avg_per_hour),
                latency_impact_ms=50.0,  # Batching adds ~50ms latency
            )

            rec = OptimizationRecommendation(
                type=RecommendationType.BATCHING,
                priority=RecommendationPriority.MEDIUM,
                workspace_id=workspace_id,
                current_cost_usd=Decimal(str(total_cost)),
                projected_cost_usd=Decimal(str(total_cost - savings)),
                confidence_score=0.6,
                affected_operations=[operation],
                title=f"Batch '{operation}' requests",
                description=(
                    f"'{operation}' averages {avg_per_hour:.0f} requests/hour. "
                    f"Batching into groups of {self.optimal_batch_size} could "
                    f"reduce overhead by {overhead_reduction * 100:.0f}%."
                ),
                rationale=(
                    "High request frequency indicates opportunity for batching. "
                    "This reduces API overhead and improves throughput."
                ),
                batching_opportunity=opportunity,
                implementation_steps=[
                    ImplementationStep(
                        order=1,
                        description="Implement request queue for operation",
                        code_snippet=(
                            "# Add to agent configuration\n"
                            "batching:\n"
                            f"  {operation}:\n"
                            f"    batch_size: {self.optimal_batch_size}\n"
                            "    max_wait_ms: 100"
                        ),
                        estimated_effort="medium",
                    ),
                    ImplementationStep(
                        order=2,
                        description="Monitor latency impact",
                        estimated_effort="low",
                    ),
                ],
                auto_apply_available=False,
                quality_impact="Slight increase in latency (~50ms)",
                quality_impact_score=0.05,
                risk_level="low",
            )
            recommendations.append(rec)

        return recommendations


class CostOptimizer:
    """
    Main cost optimization engine.

    Coordinates multiple analyzers to generate comprehensive
    optimization recommendations.
    """

    def __init__(
        self,
        cost_tracker: CostTracker | None = None,
    ):
        """
        Initialize optimizer.

        Args:
            cost_tracker: CostTracker instance for data access
        """
        self._cost_tracker = cost_tracker
        self._model_analyzer = ModelDowngradeAnalyzer()
        self._caching_recommender = CachingRecommender()
        self._batching_optimizer = BatchingOptimizer()

        # In-memory recommendation storage
        self._recommendations: dict[str, OptimizationRecommendation] = {}
        self._workspace_recs: dict[str, list[str]] = defaultdict(list)

    def set_cost_tracker(self, tracker: CostTracker) -> None:
        """Set the cost tracker instance."""
        self._cost_tracker = tracker

    async def analyze_workspace(
        self,
        workspace_id: str,
        days: int = 7,
    ) -> list[OptimizationRecommendation]:
        """
        Analyze a workspace and generate recommendations.

        Args:
            workspace_id: Workspace to analyze
            days: Number of days of history to analyze

        Returns:
            List of optimization recommendations
        """
        if not self._cost_tracker:
            logger.warning("No cost tracker configured, cannot analyze")
            return []

        recommendations: list[OptimizationRecommendation] = []

        # Get usage data from tracker
        usage_data = await self._get_usage_data(workspace_id, days)
        if not usage_data:
            logger.info("No usage data for workspace %s", workspace_id)
            return []

        # Build usage patterns
        patterns = self._build_patterns(usage_data)

        # Run all analyzers
        recommendations.extend(self._model_analyzer.analyze(patterns, workspace_id))
        recommendations.extend(self._caching_recommender.analyze(usage_data, workspace_id))
        recommendations.extend(self._batching_optimizer.analyze(usage_data, workspace_id))

        # Store recommendations
        for rec in recommendations:
            self._recommendations[rec.id] = rec
            self._workspace_recs[workspace_id].append(rec.id)

        # Sort by priority and savings
        recommendations.sort(
            key=lambda r: (
                -{"critical": 4, "high": 3, "medium": 2, "low": 1}[r.priority.value],
                -r.estimated_savings_usd,
            )
        )

        logger.info(
            "Generated %s recommendations for workspace %s", len(recommendations), workspace_id
        )
        return recommendations

    async def _get_usage_data(
        self,
        workspace_id: str,
        days: int,
    ) -> list[TokenUsage]:
        """Get usage data from cost tracker."""
        if not self._cost_tracker:
            return []
        # Access the usage buffer from cost tracker
        usage_data = []
        async with self._cost_tracker._buffer_lock:
            for usage in self._cost_tracker._usage_buffer:
                if usage.workspace_id == workspace_id:
                    usage_data.append(usage)
        return usage_data

    def _build_patterns(
        self,
        usage_data: list[TokenUsage],
    ) -> list[UsagePattern]:
        """Build usage patterns from raw data."""
        pattern_map: dict[tuple[str, str, str], UsagePattern] = {}

        for usage in usage_data:
            key = (usage.model, usage.provider, usage.operation)
            if key not in pattern_map:
                pattern_map[key] = UsagePattern(
                    model=usage.model,
                    provider=usage.provider,
                    operation=usage.operation,
                )

            pattern = pattern_map[key]
            pattern.count += 1
            pattern.total_tokens_in += usage.tokens_in
            pattern.total_tokens_out += usage.tokens_out
            pattern.total_cost += usage.cost_usd

        # Calculate averages
        for pattern in pattern_map.values():
            if pattern.count > 0:
                pattern.avg_tokens_in = pattern.total_tokens_in / pattern.count
                pattern.avg_tokens_out = pattern.total_tokens_out / pattern.count

        return list(pattern_map.values())

    def get_recommendation(
        self,
        recommendation_id: str,
    ) -> OptimizationRecommendation | None:
        """Get a recommendation by ID."""
        return self._recommendations.get(recommendation_id)

    def get_workspace_recommendations(
        self,
        workspace_id: str,
        status: RecommendationStatus | None = None,
        type_filter: RecommendationType | None = None,
    ) -> list[OptimizationRecommendation]:
        """Get recommendations for a workspace."""
        rec_ids = self._workspace_recs.get(workspace_id, [])
        recs = [self._recommendations[rid] for rid in rec_ids if rid in self._recommendations]

        if status:
            recs = [r for r in recs if r.status == status]
        if type_filter:
            recs = [r for r in recs if r.type == type_filter]

        return recs

    def apply_recommendation(
        self,
        recommendation_id: str,
        user_id: str,
    ) -> bool:
        """Mark a recommendation as applied."""
        rec = self._recommendations.get(recommendation_id)
        if not rec:
            return False

        rec.apply(user_id)
        logger.info("Recommendation %s applied by %s", recommendation_id, user_id)
        return True

    def dismiss_recommendation(
        self,
        recommendation_id: str,
    ) -> bool:
        """Dismiss a recommendation."""
        rec = self._recommendations.get(recommendation_id)
        if not rec:
            return False

        rec.dismiss()
        logger.info("Recommendation %s dismissed", recommendation_id)
        return True

    def get_summary(self, workspace_id: str) -> RecommendationSummary:
        """Get recommendation summary for a workspace."""
        recs = self.get_workspace_recommendations(workspace_id)

        summary = RecommendationSummary(workspace_id=workspace_id)
        summary.total_recommendations = len(recs)

        for rec in recs:
            # Status counts
            if rec.status == RecommendationStatus.PENDING:
                summary.pending_count += 1
                summary.total_potential_savings += rec.estimated_savings_usd
            elif rec.status == RecommendationStatus.APPLIED:
                summary.applied_count += 1
                summary.realized_savings += rec.estimated_savings_usd
            elif rec.status == RecommendationStatus.DISMISSED:
                summary.dismissed_count += 1

            # Priority counts
            if rec.priority == RecommendationPriority.CRITICAL:
                summary.critical_count += 1
            elif rec.priority == RecommendationPriority.HIGH:
                summary.high_count += 1
            elif rec.priority == RecommendationPriority.MEDIUM:
                summary.medium_count += 1
            else:
                summary.low_count += 1

            # Type counts
            type_key = rec.type.value
            summary.by_type[type_key] = summary.by_type.get(type_key, 0) + 1

        return summary


# Global optimizer instance
_optimizer: CostOptimizer | None = None


def get_cost_optimizer() -> CostOptimizer:
    """Get or create the global cost optimizer."""
    global _optimizer
    if _optimizer is None:
        try:
            from aragora.billing.cost_tracker import get_cost_tracker

            tracker = get_cost_tracker()
            _optimizer = CostOptimizer(cost_tracker=tracker)
        except ImportError:
            _optimizer = CostOptimizer()
    return _optimizer


__all__ = [
    "CostOptimizer",
    "ModelDowngradeAnalyzer",
    "CachingRecommender",
    "BatchingOptimizer",
    "UsagePattern",
    "get_cost_optimizer",
]
