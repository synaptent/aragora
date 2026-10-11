"""
Meta-Learner for Knowledge Mound optimization.

Provides cross-memory optimization by tracking retrieval patterns
and adjusting tier thresholds based on actual usage.

Usage:
    from aragora.knowledge.mound.meta_learner import KnowledgeMoundMetaLearner

    meta_learner = KnowledgeMoundMetaLearner(
        semantic_store=semantic_store,
        continuum=continuum_memory,
    )

    # Record retrievals
    await meta_learner.record_retrieval(km_id, rank_position=0, was_useful=True)

    # Optimize tier thresholds
    recommendations = await meta_learner.optimize_tier_thresholds()

    # Coalesce near-duplicates
    merged_count = await meta_learner.coalesce_duplicates(similarity_threshold=0.95)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from aragora.memory.embeddings import cosine_similarity, unpack_embedding

if TYPE_CHECKING:
    from aragora.knowledge.mound.semantic_store import SemanticStore
    from aragora.memory.continuum import ContinuumMemory

logger = logging.getLogger(__name__)


@dataclass
class RetrievalMetrics:
    """Aggregated retrieval metrics for analysis."""

    total_retrievals: int = 0
    unique_items_retrieved: int = 0
    avg_rank_position: float = 0.0
    useful_retrievals: int = 0
    useless_retrievals: int = 0
    retrieval_rate: float = 0.0  # retrievals per hour
    by_domain: dict[str, int] = field(default_factory=dict)
    by_tier: dict[str, int] = field(default_factory=dict)


@dataclass
class TierOptimizationRecommendation:
    """Recommendation for tier threshold adjustment."""

    tier: str
    current_promotion_threshold: float
    recommended_promotion_threshold: float
    current_demotion_threshold: float
    recommended_demotion_threshold: float
    reasoning: str
    confidence: float


@dataclass
class CoalescenceResult:
    """Result of duplicate coalescing operation."""

    items_checked: int
    duplicates_found: int
    items_merged: int
    storage_saved_bytes: int
    merge_details: list[dict[str, Any]] = field(default_factory=list)


class KnowledgeMoundMetaLearner:
    """
    Cross-memory optimization based on usage patterns.

    The meta-learner tracks how knowledge is retrieved and used,
    then provides recommendations for:
    - Tier threshold adjustments (promote/demote thresholds)
    - Duplicate coalescing
    - Stale knowledge identification
    - Domain importance weighting
    """

    def __init__(
        self,
        semantic_store: SemanticStore,
        continuum: ContinuumMemory | None = None,
        tenant_id: str = "default",
        optimization_interval_hours: float = 24.0,
    ):
        """
        Initialize the meta-learner.

        Args:
            semantic_store: SemanticStore for retrieval metrics
            continuum: ContinuumMemory for tier optimization
            tenant_id: Tenant ID for isolation
            optimization_interval_hours: Hours between optimization runs
        """
        self._semantic_store = semantic_store
        self._continuum = continuum
        self._tenant_id = tenant_id
        self._optimization_interval = timedelta(hours=optimization_interval_hours)

        # Track optimization history
        self._last_optimization: datetime | None = None
        self._optimization_history: list[dict[str, Any]] = []

    # =========================================================================
    # Retrieval Recording
    # =========================================================================

    async def record_retrieval(
        self,
        km_id: str,
        rank_position: int,
        was_useful: bool | None = None,
        query: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Record a retrieval event for learning.

        Args:
            km_id: Knowledge Mound ID that was retrieved
            rank_position: Position in search results (0 = top)
            was_useful: User feedback on whether retrieval was useful
            query: Original query that triggered retrieval
            context: Additional context (debate_id, agent_id, etc.)
        """
        # Delegate to SemanticStore for basic tracking
        await self._semantic_store.record_retrieval(km_id, rank_position, was_useful)

        # If ContinuumMemory is connected, also record there for tier optimization
        if self._continuum:
            entry = await self._get_continuum_entry(km_id)
            if entry:
                # Recording a retrieval increases importance
                await self._record_continuum_access(entry.id, was_useful)

    async def _get_continuum_entry(self, km_id: str) -> Any | None:
        """Look up corresponding ContinuumMemory entry."""
        # Get source info from semantic index
        entry = await self._semantic_store.get_entry(km_id)
        if entry and entry.source_type == "continuum":
            # Fetch from ContinuumMemory
            if self._continuum and hasattr(self._continuum, "get_by_id"):
                return self._continuum.get_by_id(entry.source_id)
        return None

    async def _record_continuum_access(self, entry_id: str, was_useful: bool | None) -> None:
        """Record access in ContinuumMemory for tier management."""
        if not self._continuum:
            return

        # ContinuumMemory should have a method to record successful/failed access
        try:
            if was_useful is True and hasattr(self._continuum, "record_success"):
                self._continuum.record_success(entry_id)
            elif was_useful is False and hasattr(self._continuum, "record_failure"):
                self._continuum.record_failure(entry_id)
            elif hasattr(self._continuum, "record_access"):
                self._continuum.record_access(entry_id)
        except AttributeError:
            # Methods may not exist in all versions
            pass

    # =========================================================================
    # Retrieval Analysis
    # =========================================================================

    async def get_retrieval_metrics(
        self,
        since: datetime | None = None,
    ) -> RetrievalMetrics:
        """
        Get aggregated retrieval metrics.

        Args:
            since: Only count retrievals since this time

        Returns:
            RetrievalMetrics with aggregated statistics
        """
        patterns = await self._semantic_store.get_retrieval_patterns(
            tenant_id=self._tenant_id,
            min_retrievals=1,
        )

        high_domains = patterns.get("high_retrieval_domains", [])
        low_domains = patterns.get("low_retrieval_domains", [])

        total = sum(d["count"] for d in high_domains)
        unique = len(high_domains) + len(low_domains)

        # Calculate average rank for high-retrieval items
        avg_rank = 0.0
        if high_domains:
            avg_rank = sum(d.get("avg_rank", 0) * d["count"] for d in high_domains) / max(total, 1)

        return RetrievalMetrics(
            total_retrievals=total,
            unique_items_retrieved=unique,
            avg_rank_position=avg_rank,
            by_domain={d["domain"]: d["count"] for d in high_domains},
        )

    async def identify_underutilized_knowledge(
        self,
        min_age_days: int = 7,
        max_retrievals: int = 2,
    ) -> list[str]:
        """
        Identify knowledge that exists but is rarely retrieved.

        This may indicate:
        - Stale knowledge that should be archived
        - Knowledge in the wrong domain
        - Knowledge that needs better semantic representation

        Args:
            min_age_days: Only consider items older than this
            max_retrievals: Items with fewer retrievals than this

        Returns:
            List of Knowledge Mound IDs that are underutilized
        """
        patterns = await self._semantic_store.get_retrieval_patterns(
            tenant_id=self._tenant_id,
            min_retrievals=0,
        )

        # Get items from low-retrieval domains
        underutilized = []
        for domain_info in patterns.get("low_retrieval_domains", []):
            # These items have low retrieval counts
            underutilized.append(domain_info["domain"])

        return underutilized

    # =========================================================================
    # Tier Optimization
    # =========================================================================

    async def optimize_tier_thresholds(self) -> list[TierOptimizationRecommendation]:
        """
        Analyze retrieval patterns and recommend tier threshold adjustments.

        Returns:
            List of recommendations for each tier
        """
        if not self._continuum:
            logger.warning("ContinuumMemory not connected, skipping tier optimization")
            return []

        recommendations = []

        # Get current thresholds from ContinuumMemory
        try:
            hyperparams = self._continuum.hyperparams
        except AttributeError:
            return []

        # Analyze retrieval patterns per tier
        tier_metrics = await self._analyze_tier_retrieval_patterns()

        for tier, metrics in tier_metrics.items():
            current_promo = hyperparams.get(f"{tier}_promotion_threshold", 0.7)
            current_demo = hyperparams.get(f"{tier}_demotion_threshold", 0.3)

            # Calculate recommended thresholds based on retrieval patterns
            # Convert to float with type guard for dict.get() return type
            current_promo_f = (
                float(current_promo) if isinstance(current_promo, (int, float, str)) else 0.7
            )
            current_demo_f = (
                float(current_demo) if isinstance(current_demo, (int, float, str)) else 0.3
            )
            rec_promo, rec_demo, reasoning = self._calculate_tier_recommendations(
                tier,
                metrics,
                current_promo_f,
                current_demo_f,
            )

            if abs(rec_promo - current_promo_f) > 0.05 or abs(rec_demo - current_demo_f) > 0.05:
                recommendations.append(
                    TierOptimizationRecommendation(
                        tier=tier,
                        current_promotion_threshold=current_promo_f,
                        recommended_promotion_threshold=rec_promo,
                        current_demotion_threshold=current_demo_f,
                        recommended_demotion_threshold=rec_demo,
                        reasoning=reasoning,
                        confidence=metrics.get("confidence", 0.5),
                    )
                )

        # Record optimization
        self._last_optimization = datetime.now()
        self._optimization_history.append(
            {
                "timestamp": self._last_optimization.isoformat(),
                "recommendations": len(recommendations),
                "metrics": tier_metrics,
            }
        )

        return recommendations

    async def _analyze_tier_retrieval_patterns(self) -> dict[str, dict[str, Any]]:
        """Analyze retrieval patterns for each tier."""
        if not self._continuum:
            return {}

        tier_metrics: dict[str, dict[str, Any]] = {}

        for tier in ["fast", "medium", "slow", "glacial"]:
            # Get entries in this tier
            get_by_tier = getattr(self._continuum, "get_by_tier", None)
            entries = get_by_tier(tier, limit=1000) if get_by_tier else []

            if not entries:
                continue

            # For each entry, check if we have retrieval data
            retrieval_counts = []
            for entry in entries:
                # Find corresponding semantic index entry
                if self._semantic_store.has_source("continuum", entry.id, self._tenant_id):
                    # Get retrieval count from semantic store
                    se = await self._semantic_store.get_entry(f"km_{entry.id[:16]}")
                    if se:
                        retrieval_counts.append(se.retrieval_count)
                    else:
                        retrieval_counts.append(0)
                else:
                    retrieval_counts.append(0)

            if retrieval_counts:
                tier_metrics[tier] = {
                    "total_entries": len(entries),
                    "avg_retrievals": sum(retrieval_counts) / len(retrieval_counts),
                    "max_retrievals": max(retrieval_counts),
                    "zero_retrievals": sum(1 for c in retrieval_counts if c == 0),
                    "confidence": min(len(retrieval_counts) / 100, 1.0),
                }

        return tier_metrics

    def _calculate_tier_recommendations(
        self,
        tier: str,
        metrics: dict[str, Any],
        current_promo: float,
        current_demo: float,
    ) -> tuple[float, float, str]:
        """Calculate recommended thresholds based on metrics."""
        avg_retrievals = metrics.get("avg_retrievals", 0)
        zero_pct = metrics.get("zero_retrievals", 0) / max(metrics.get("total_entries", 1), 1)

        reasoning_parts = []

        # If too many items have zero retrievals, lower demotion threshold
        if zero_pct > 0.5:
            new_demo = max(current_demo - 0.1, 0.1)
            reasoning_parts.append(f"{zero_pct:.0%} items unused, lowering demotion threshold")
        else:
            new_demo = current_demo

        # If average retrievals are high, raise promotion threshold to be more selective
        if avg_retrievals > 10:
            new_promo = min(current_promo + 0.1, 0.9)
            reasoning_parts.append(
                f"High avg retrievals ({avg_retrievals:.1f}), raising promotion bar"
            )
        elif avg_retrievals < 2:
            new_promo = max(current_promo - 0.1, 0.4)
            reasoning_parts.append(
                f"Low avg retrievals ({avg_retrievals:.1f}), lowering promotion bar"
            )
        else:
            new_promo = current_promo

        reasoning = (
            "; ".join(reasoning_parts) if reasoning_parts else "No significant changes needed"
        )

        return new_promo, new_demo, reasoning

    async def apply_recommendations(
        self,
        recommendations: list[TierOptimizationRecommendation],
    ) -> bool:
        """
        Apply tier threshold recommendations to ContinuumMemory.

        Args:
            recommendations: Recommendations to apply

        Returns:
            True if applied successfully
        """
        if not self._continuum:
            return False

        try:
            hyperparams = getattr(self._continuum, "hyperparams", {})
            for rec in recommendations:
                if rec.confidence >= 0.5:  # Only apply high-confidence recommendations
                    hyperparams[f"{rec.tier}_promotion_threshold"] = (
                        rec.recommended_promotion_threshold
                    )
                    hyperparams[f"{rec.tier}_demotion_threshold"] = (
                        rec.recommended_demotion_threshold
                    )

                    logger.info(
                        "Applied tier optimization for %s: promo=%.2f, demo=%.2f",
                        rec.tier,
                        rec.recommended_promotion_threshold,
                        rec.recommended_demotion_threshold,
                    )

            return True
        except (AttributeError, KeyError, ValueError) as e:
            logger.warning("Failed to apply tier recommendations: %s", e)
            return False
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.exception("Unexpected error applying tier recommendations: %s", e)
            return False

    # =========================================================================
    # Duplicate Coalescing
    # =========================================================================

    async def coalesce_duplicates(
        self,
        similarity_threshold: float = 0.95,
        batch_size: int = 100,
        dry_run: bool = False,
    ) -> CoalescenceResult:
        """
        Merge near-duplicate knowledge items.

        Identifies semantically similar items and merges them,
        preserving the higher-importance item and creating links.

        Args:
            similarity_threshold: Minimum similarity for merging (0-1)
            batch_size: Number of items to process at once
            dry_run: If True, report but don't merge

        Returns:
            CoalescenceResult with merge details
        """
        result = CoalescenceResult(
            items_checked=0,
            duplicates_found=0,
            items_merged=0,
            storage_saved_bytes=0,
        )

        # Get all entries for this tenant
        stats = await self._semantic_store.get_stats(self._tenant_id)
        total = stats.get("total_entries", 0)

        if total < 2:
            return result

        # Process in batches to avoid memory issues
        offset = 0
        all_candidates: list[tuple[str, str, float]] = []

        while offset < total:
            batch = await self._get_entries_batch(offset, batch_size)
            result.items_checked += len(batch)

            # Compare each pair within batch
            for i in range(len(batch)):
                for j in range(i + 1, len(batch)):
                    similarity = cosine_similarity(
                        batch[i]["embedding"],
                        batch[j]["embedding"],
                    )
                    if similarity >= similarity_threshold:
                        all_candidates.append((batch[i]["id"], batch[j]["id"], similarity))
                        result.duplicates_found += 1

            offset += batch_size

        # Merge candidates (keep higher importance)
        if not dry_run and all_candidates:
            for source_id, target_id, similarity in all_candidates:
                merged = await self._merge_entries(source_id, target_id)
                if merged:
                    result.items_merged += 1
                    result.merge_details.append(
                        {
                            "kept": source_id,
                            "merged": target_id,
                            "similarity": similarity,
                        }
                    )

        return result

    async def _get_entries_batch(self, offset: int, limit: int) -> list[dict[str, Any]]:
        """Get a batch of entries with embeddings."""
        return await asyncio.to_thread(self._sync_get_entries_batch, offset, limit)

    def _sync_get_entries_batch(self, offset: int, limit: int) -> list[dict[str, Any]]:
        """Synchronous batch retrieval."""
        rows = self._semantic_store.fetch_all(
            """
            SELECT id, embedding, importance
            FROM semantic_index
            WHERE tenant_id = ?
            ORDER BY id
            LIMIT ? OFFSET ?
            """,
            (self._tenant_id, limit, offset),
        )

        return [
            {
                "id": row[0],
                "embedding": unpack_embedding(row[1]),
                "importance": row[2],
            }
            for row in rows
        ]

    async def _merge_entries(self, keep_id: str, merge_id: str) -> bool:
        """Merge two entries, keeping the first one."""
        # Get both entries
        keep_entry = await self._semantic_store.get_entry(keep_id)
        merge_entry = await self._semantic_store.get_entry(merge_id)

        if not keep_entry or not merge_entry:
            return False

        # Keep the higher importance one
        if merge_entry.importance > keep_entry.importance:
            keep_id, merge_id = merge_id, keep_id

        # Delete the merged entry (archive it)
        await self._semantic_store.delete_entry(
            merge_id, archive=True, reason=f"merged_into_{keep_id}"
        )

        logger.debug("Merged %s into %s", merge_id, keep_id)
        return True

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_learning_stats(self) -> dict[str, Any]:
        """Get meta-learning statistics."""
        retrieval_metrics = await self.get_retrieval_metrics()

        return {
            "retrieval_metrics": {
                "total": retrieval_metrics.total_retrievals,
                "unique_items": retrieval_metrics.unique_items_retrieved,
                "avg_rank": retrieval_metrics.avg_rank_position,
            },
            "optimization_history_count": len(self._optimization_history),
            "last_optimization": (
                self._last_optimization.isoformat() if self._last_optimization else None
            ),
            "continuum_connected": self._continuum is not None,
            "tenant_id": self._tenant_id,
        }


__all__ = [
    "KnowledgeMoundMetaLearner",
    "RetrievalMetrics",
    "TierOptimizationRecommendation",
    "CoalescenceResult",
]
