"""
Memory feedback methods for FeedbackPhase.

Extracted from feedback_phase.py for maintainability.
Handles memory storage, outcome updates, cleanup, coordinated writes,
and epistemic graph absorption.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.debate.context import DebateContext
    from aragora.protocols import TieredMemoryProtocol

logger = logging.getLogger(__name__)


class MemoryFeedback:
    """Handles memory-related feedback operations."""

    def __init__(
        self,
        continuum_memory: TieredMemoryProtocol | None = None,
        store_debate_outcome_as_memory: Callable[[Any], None] | None = None,
        update_continuum_memory_outcomes: Callable[[Any], None] | None = None,
        memory_coordinator: Any | None = None,
        enable_coordinated_writes: bool = True,
        coordinator_options: Any | None = None,
    ):
        self.continuum_memory = continuum_memory
        self._store_debate_outcome_as_memory = store_debate_outcome_as_memory
        self._update_continuum_memory_outcomes = update_continuum_memory_outcomes
        self.memory_coordinator = memory_coordinator
        self.enable_coordinated_writes = enable_coordinated_writes
        self.coordinator_options = coordinator_options

    def store_memory(self, ctx: DebateContext) -> None:
        """Store debate outcome in ContinuumMemory."""
        if not self.continuum_memory:
            return

        result = ctx.result
        if not result.final_answer:
            return

        if self._store_debate_outcome_as_memory:
            self._store_debate_outcome_as_memory(result)

    def update_memory_outcomes(self, ctx: DebateContext) -> None:
        """Update retrieved memories based on debate outcome."""
        if not self.continuum_memory:
            return

        if self._update_continuum_memory_outcomes:
            self._update_continuum_memory_outcomes(ctx.result)

    def run_memory_cleanup(self, ctx: DebateContext) -> None:
        """Run periodic memory cleanup to prevent unbounded growth.

        Cleans up expired memories and enforces tier limits. This activates
        the previously stranded cleanup functionality in ContinuumMemory.

        Cleanup runs:
        - cleanup_expired_memories(): Every debate
        - enforce_tier_limits(): 10% of debates (probabilistic)
        """
        if not self.continuum_memory:
            return

        import random

        try:
            # Always try to clean expired memories
            cleaned = self.continuum_memory.cleanup_expired_memories()
            if cleaned > 0:
                logger.debug("[memory] Cleaned %s expired memories", cleaned)

            # Probabilistically enforce tier limits (10% of debates)
            if random.random() < 0.1:
                self.continuum_memory.enforce_tier_limits()
                logger.debug("[memory] Enforced tier limits")

        except (TypeError, ValueError, AttributeError, OSError, RuntimeError) as e:
            logger.debug("[memory] Cleanup error (non-fatal): %s", e)

    async def execute_coordinated_writes(self, ctx: DebateContext) -> None:
        """Execute coordinated atomic writes to all memory systems.

        When enabled, this provides transaction semantics for multi-system
        writes with rollback on partial failure. This is an alternative to
        the individual write operations in steps 8-11.

        Note: Individual writes still run for backward compatibility.
        The coordinator can be used for additional atomic operations.
        """
        if not self.memory_coordinator or not self.enable_coordinated_writes:
            return

        result = ctx.result
        if not result:
            return

        try:
            transaction = await self.memory_coordinator.commit_debate_outcome(
                ctx=ctx,
                options=self.coordinator_options,
            )

            if transaction.success:
                logger.info(
                    "[coordinator] Committed %d writes for debate %s",
                    len(transaction.operations),
                    ctx.debate_id,
                )
            elif transaction.partial_failure:
                failed = transaction.get_failed_operations()
                logger.warning(
                    "[coordinator] Partial failure for debate %s: %d/%d failed",
                    ctx.debate_id,
                    len(failed),
                    len(transaction.operations),
                )
                for op in failed:
                    logger.warning("[coordinator] Failed: %s - %s", op.target, op.error)

            # Store transaction reference in context for debugging
            setattr(ctx, "_memory_transaction", transaction)

        except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
            logger.error("[coordinator] Transaction failed for %s: %s", ctx.debate_id, e)

    def absorb_into_epistemic_graph(self, ctx: DebateContext) -> None:
        """Absorb consensus outcome into the cross-debate epistemic graph.

        Converts debate consensus into inherited beliefs that can seed
        future debates on related topics, enabling organizational memory.
        """
        result = ctx.result
        if not result:
            return

        final_answer = getattr(result, "final_answer", "")
        if not final_answer:
            return

        try:
            from aragora.reasoning.epistemic_graph import get_epistemic_graph

            graph = get_epistemic_graph()
            confidence = getattr(result, "confidence", 0.0)
            if confidence < 0.3:  # Don't absorb low-confidence outcomes
                return

            # Collect supporting/dissenting agents from votes
            supporting: list[str] = []
            dissenting: list[str] = []
            winner = getattr(result, "winner", None)
            for vote in getattr(result, "votes", []):
                agent_name = getattr(vote, "voter", getattr(vote, "agent", ""))
                choice = getattr(vote, "choice", "")
                if choice == winner:
                    supporting.append(agent_name)
                elif agent_name:
                    dissenting.append(agent_name)

            # Absorb main consensus
            graph.absorb_consensus(
                debate_id=ctx.debate_id,
                final_claim=final_answer[:500],  # Truncate long answers
                confidence=confidence,
                domain=ctx.domain or "",
                supporting_agents=supporting,
                dissenting_agents=dissenting,
            )

            # Absorb dissent records if available
            dissent_records = getattr(result, "dissent_records", [])
            for dissent in dissent_records:
                agent = getattr(dissent, "agent", "")
                statement = getattr(dissent, "alternative_view", "")
                severity = getattr(dissent, "severity", 0.5)
                if statement:
                    graph.absorb_dissent(
                        debate_id=ctx.debate_id,
                        dissent_statement=statement,
                        dissenting_agent=agent,
                        severity=severity,
                        domain=ctx.domain or "",
                    )

            logger.debug(
                "epistemic_graph_absorb debate=%s supporters=%d dissenters=%d",
                ctx.debate_id,
                len(supporting),
                len(dissenting),
            )
        except ImportError:
            logger.debug("EpistemicGraph not available")
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.warning("EpistemicGraph absorption failed: %s", e)


__all__ = ["MemoryFeedback"]
