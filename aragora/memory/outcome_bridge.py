"""
Outcome-Memory Bridge for learning from debate results.

This module connects OutcomeTracker outcomes to ContinuumMemory tier management,
enabling the memory system to learn which memories contribute to successful debates.

The bridge enables:
1. Memory usage tracking - Record which memories informed a debate
2. Outcome-based promotion - Promote memories used in successful debates
3. Failure demotion - Demote or decay memories from failed debates
4. Success rate tracking - Track individual memory performance

Usage:
    from aragora.memory.outcome_bridge import OutcomeMemoryBridge

    bridge = OutcomeMemoryBridge(outcome_tracker, continuum_memory)

    # During debate - track memory usage
    bridge.record_memory_usage("memory-123", "debate-456")

    # After debate outcome recorded
    bridge.process_outcome(outcome, used_memory_ids=["memory-123", "memory-456"])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aragora.utils.datetime_helpers import utc_now_iso_naive

if TYPE_CHECKING:
    from aragora.debate.outcome_tracker import ConsensusOutcome, OutcomeTracker
    from aragora.memory.continuum import ContinuumMemory
    from aragora.memory.tier_manager import MemoryTier

logger = logging.getLogger(__name__)


@dataclass
class MemoryUsageRecord:
    """Record of a memory item's usage in a debate."""

    memory_id: str
    debate_id: str
    used_at: str = field(default_factory=utc_now_iso_naive)


@dataclass
class PromotionResult:
    """Result of a memory promotion attempt."""

    memory_id: str
    promoted: bool
    from_tier: str | None = None
    to_tier: str | None = None
    reason: str = ""


@dataclass
class ProcessingResult:
    """Result of processing an outcome."""

    debate_id: str
    memories_updated: int
    memories_promoted: int
    memories_demoted: int
    promotions: list[PromotionResult] = field(default_factory=list)


@dataclass
class OutcomeMemoryBridge:
    """Bridges OutcomeTracker outcomes to ContinuumMemory tier management.

    This class tracks which memory items are used in debates and adjusts
    their importance and tier placement based on debate outcomes.

    The core insight is that memories which consistently contribute to
    successful debates should be promoted to faster tiers (more accessible),
    while memories from failed debates should be deprioritized.

    Attributes:
        outcome_tracker: OutcomeTracker for debate outcomes
        continuum_memory: ContinuumMemory for tier management
        success_threshold: Minimum confidence for promotion consideration
        usage_count_threshold: Times a memory must contribute to success before promotion
        promotion_tier_jump: How many tiers to promote at once
        failure_penalty_weight: How much failure affects importance (0-1)
        min_confidence_for_update: Minimum debate confidence to affect memory
    """

    outcome_tracker: OutcomeTracker | None = None
    continuum_memory: ContinuumMemory | None = None

    # Promotion thresholds
    success_threshold: float = 0.7  # Minimum confidence for promotion
    usage_count_threshold: int = 3  # Successful uses before promotion
    promotion_tier_jump: int = 1  # Tiers to jump on promotion

    # Update weights
    failure_penalty_weight: float = 0.1  # Importance reduction on failure
    success_boost_weight: float = 0.05  # Importance increase on success
    min_confidence_for_update: float = 0.5  # Minimum confidence to update memory

    # Track usage during debates
    _usage_records: dict[str, list[MemoryUsageRecord]] = field(default_factory=dict, repr=False)
    _memory_success_counts: dict[str, int] = field(default_factory=dict, repr=False)
    _memory_failure_counts: dict[str, int] = field(default_factory=dict, repr=False)

    def record_memory_usage(self, memory_id: str, debate_id: str) -> None:
        """Track that a memory item was used in a debate.

        Call this when memory is injected into a debate context.

        Args:
            memory_id: ID of the memory item
            debate_id: ID of the debate using the memory
        """
        record = MemoryUsageRecord(memory_id=memory_id, debate_id=debate_id)

        if debate_id not in self._usage_records:
            self._usage_records[debate_id] = []

        # Avoid duplicates
        existing_ids = {r.memory_id for r in self._usage_records[debate_id]}
        if memory_id not in existing_ids:
            self._usage_records[debate_id].append(record)
            logger.debug("memory_usage_recorded memory_id=%s debate_id=%s", memory_id, debate_id)

    def get_memories_for_debate(self, debate_id: str) -> list[str]:
        """Get list of memory IDs used in a debate.

        Args:
            debate_id: ID of the debate

        Returns:
            List of memory IDs that were tracked for this debate
        """
        records = self._usage_records.get(debate_id, [])
        return [r.memory_id for r in records]

    def process_outcome(
        self,
        outcome: ConsensusOutcome,
        used_memory_ids: list[str] | None = None,
    ) -> ProcessingResult:
        """Process a debate outcome to update memory tiers and importance.

        Call this after an outcome is recorded to update the memories that
        contributed to the debate.

        Args:
            outcome: The ConsensusOutcome from the debate
            used_memory_ids: Explicit list of memory IDs used (if not tracked)

        Returns:
            ProcessingResult with update statistics
        """
        debate_id = outcome.debate_id

        # Get memories either from explicit list or tracked usage
        if used_memory_ids is None:
            used_memory_ids = self.get_memories_for_debate(debate_id)

        if not used_memory_ids:
            logger.debug("process_outcome no memories for debate_id=%s", debate_id)
            return ProcessingResult(
                debate_id=debate_id,
                memories_updated=0,
                memories_promoted=0,
                memories_demoted=0,
            )

        # Skip low-confidence debates
        if outcome.consensus_confidence < self.min_confidence_for_update:
            logger.debug(
                "process_outcome skipped low confidence debate_id=%s conf=%.2f",
                debate_id,
                outcome.consensus_confidence,
            )
            return ProcessingResult(
                debate_id=debate_id,
                memories_updated=0,
                memories_promoted=0,
                memories_demoted=0,
            )

        result = ProcessingResult(
            debate_id=debate_id,
            memories_updated=0,
            memories_promoted=0,
            memories_demoted=0,
        )

        was_successful = outcome.implementation_succeeded

        for memory_id in used_memory_ids:
            try:
                updated = self._update_memory(memory_id, outcome, was_successful)
                if updated:
                    result.memories_updated += 1

                    # Check for promotion/demotion
                    promotion = self._check_promotion(memory_id, was_successful)
                    if promotion:
                        result.promotions.append(promotion)
                        if promotion.promoted:
                            if promotion.to_tier and promotion.from_tier:
                                # Determine if it's a promotion (to faster) or demotion
                                tier_order = ["glacial", "slow", "medium", "fast"]
                                from_idx = tier_order.index(promotion.from_tier)
                                to_idx = tier_order.index(promotion.to_tier)
                                if to_idx > from_idx:
                                    result.memories_promoted += 1
                                else:
                                    result.memories_demoted += 1
            except (AttributeError, KeyError, ValueError, TypeError) as e:
                logger.warning("Failed to update memory %s: %s", memory_id, e)

        # Clean up usage records for this debate
        if debate_id in self._usage_records:
            del self._usage_records[debate_id]

        logger.info(
            "process_outcome debate_id=%s success=%s updated=%d promoted=%d demoted=%d",
            debate_id,
            was_successful,
            result.memories_updated,
            result.memories_promoted,
            result.memories_demoted,
        )

        return result

    def _update_memory(
        self,
        memory_id: str,
        outcome: ConsensusOutcome,
        was_successful: bool,
    ) -> bool:
        """Update a single memory's statistics based on outcome.

        Args:
            memory_id: ID of the memory to update
            outcome: The debate outcome
            was_successful: Whether the debate implementation succeeded

        Returns:
            True if memory was updated
        """
        if self.continuum_memory is None:
            return False

        try:
            # Get the memory entry
            entry = self.continuum_memory.get_entry(memory_id)
            if entry is None:
                logger.debug("Memory %s not found for update", memory_id)
                return False

            # Update success/failure counts
            if was_successful:
                entry.success_count += 1
                # Boost importance slightly
                entry.importance = min(1.0, entry.importance + self.success_boost_weight)

                # Track for promotion
                self._memory_success_counts[memory_id] = (
                    self._memory_success_counts.get(memory_id, 0) + 1
                )
            else:
                entry.failure_count += 1
                # Reduce importance slightly
                entry.importance = max(0.0, entry.importance - self.failure_penalty_weight)

                # Track failures
                self._memory_failure_counts[memory_id] = (
                    self._memory_failure_counts.get(memory_id, 0) + 1
                )

            # Update the entry
            entry.update_count += 1
            entry.updated_at = utc_now_iso_naive()

            # Recalculate consolidation score based on success rate
            if entry.success_count + entry.failure_count > 0:
                entry.consolidation_score = entry.success_rate

            # Save the updated entry
            self.continuum_memory.update_entry(entry)

            logger.debug(
                "memory_updated id=%s success=%s importance=%.2f success_rate=%.2f",
                memory_id,
                was_successful,
                entry.importance,
                entry.success_rate,
            )

            return True

        except (AttributeError, KeyError, ValueError, TypeError) as e:
            logger.warning("Error updating memory %s: %s", memory_id, e)
            return False

    def _check_promotion(
        self,
        memory_id: str,
        was_successful: bool,
    ) -> PromotionResult | None:
        """Check if a memory should be promoted or demoted.

        Args:
            memory_id: ID of the memory to check
            was_successful: Whether the latest debate succeeded

        Returns:
            PromotionResult if tier change occurred, None otherwise
        """
        if self.continuum_memory is None:
            return None

        try:
            entry = self.continuum_memory.get_entry(memory_id)
            if entry is None:
                return None

            current_tier = entry.tier
            success_count = self._memory_success_counts.get(memory_id, 0)
            failure_count = self._memory_failure_counts.get(memory_id, 0)

            # Check for promotion (successful usage)
            if (
                was_successful
                and success_count >= self.usage_count_threshold
                and entry.success_rate >= self.success_threshold
            ):
                # Promote to faster tier
                new_tier = self._get_faster_tier(current_tier)
                if new_tier != current_tier:
                    self.continuum_memory.promote_entry(memory_id, new_tier)

                    # Reset success counter after promotion
                    self._memory_success_counts[memory_id] = 0

                    return PromotionResult(
                        memory_id=memory_id,
                        promoted=True,
                        from_tier=(
                            current_tier.value
                            if hasattr(current_tier, "value")
                            else str(current_tier)
                        ),
                        to_tier=new_tier.value if hasattr(new_tier, "value") else str(new_tier),
                        reason=f"Promoted after {success_count} successful uses",
                    )

            # Check for demotion (repeated failures)
            elif not was_successful and failure_count >= self.usage_count_threshold:
                # Demote to slower tier if success rate is low
                if entry.success_rate < 0.3:  # Less than 30% success
                    new_tier = self._get_slower_tier(current_tier)
                    if new_tier != current_tier:
                        self.continuum_memory.demote_entry(memory_id, new_tier)

                        # Reset failure counter after demotion
                        self._memory_failure_counts[memory_id] = 0

                        return PromotionResult(
                            memory_id=memory_id,
                            promoted=True,  # Still a tier change
                            from_tier=(
                                current_tier.value
                                if hasattr(current_tier, "value")
                                else str(current_tier)
                            ),
                            to_tier=new_tier.value if hasattr(new_tier, "value") else str(new_tier),
                            reason=f"Demoted after {failure_count} failures",
                        )

            return None

        except (AttributeError, KeyError, ValueError, TypeError) as e:
            logger.warning("Error checking promotion for %s: %s", memory_id, e)
            return None

    def _get_faster_tier(self, current_tier: MemoryTier) -> MemoryTier:
        """Get the next faster tier.

        Args:
            current_tier: Current memory tier

        Returns:
            Next faster tier, or current if already fastest
        """
        from aragora.memory.tier_manager import MemoryTier

        tier_order = [MemoryTier.GLACIAL, MemoryTier.SLOW, MemoryTier.MEDIUM, MemoryTier.FAST]
        try:
            idx = tier_order.index(current_tier)
            if idx < len(tier_order) - 1:
                return tier_order[idx + 1]
        except ValueError as e:
            logger.warning("get faster tier encountered an error: %s", e)
        return current_tier

    def _get_slower_tier(self, current_tier: MemoryTier) -> MemoryTier:
        """Get the next slower tier.

        Args:
            current_tier: Current memory tier

        Returns:
            Next slower tier, or current if already slowest
        """
        from aragora.memory.tier_manager import MemoryTier

        tier_order = [MemoryTier.GLACIAL, MemoryTier.SLOW, MemoryTier.MEDIUM, MemoryTier.FAST]
        try:
            idx = tier_order.index(current_tier)
            if idx > 0:
                return tier_order[idx - 1]
        except ValueError as e:
            logger.warning("get slower tier encountered an error: %s", e)
        return current_tier

    def get_memory_stats(self, memory_id: str) -> dict[str, Any]:
        """Get outcome-related statistics for a memory item.

        Args:
            memory_id: ID of the memory

        Returns:
            Dict with success/failure counts and rates
        """
        success_count = self._memory_success_counts.get(memory_id, 0)
        failure_count = self._memory_failure_counts.get(memory_id, 0)
        total = success_count + failure_count

        return {
            "memory_id": memory_id,
            "success_count": success_count,
            "failure_count": failure_count,
            "total_uses": total,
            "success_rate": success_count / total if total > 0 else 0.0,
            "promotions_pending": success_count >= self.usage_count_threshold,
        }

    def get_top_memories(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get memories with highest success rates.

        Args:
            limit: Maximum number to return

        Returns:
            List of memory stats sorted by success rate
        """
        all_ids = set(self._memory_success_counts.keys()) | set(self._memory_failure_counts.keys())

        stats = [self.get_memory_stats(mid) for mid in all_ids]
        stats.sort(key=lambda x: (x["success_rate"], x["success_count"]), reverse=True)

        return stats[:limit]

    def clear_tracking_data(self) -> None:
        """Clear all tracked usage and counts."""
        self._usage_records.clear()
        self._memory_success_counts.clear()
        self._memory_failure_counts.clear()
        logger.debug("outcome_bridge tracking data cleared")


def create_outcome_bridge(
    outcome_tracker: OutcomeTracker | None = None,
    continuum_memory: ContinuumMemory | None = None,
    **kwargs: Any,
) -> OutcomeMemoryBridge:
    """Create an OutcomeMemoryBridge with optional configuration.

    Args:
        outcome_tracker: OutcomeTracker for debate outcomes
        continuum_memory: ContinuumMemory for tier management
        **kwargs: Additional configuration (thresholds, weights, etc.)

    Returns:
        Configured OutcomeMemoryBridge instance
    """
    return OutcomeMemoryBridge(
        outcome_tracker=outcome_tracker,
        continuum_memory=continuum_memory,
        **kwargs,
    )


__all__ = [
    "OutcomeMemoryBridge",
    "MemoryUsageRecord",
    "PromotionResult",
    "ProcessingResult",
    "create_outcome_bridge",
]
