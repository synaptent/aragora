"""Consensus and crux storage for feedback phase.

This module extracts consensus memory storage from FeedbackPhase:
- Store debate outcomes in ConsensusMemory
- Store dissenting views as DissentRecords
- Extract and store belief cruxes for future seeding

Used to enable future debates to benefit from past decisions,
dissenting views, and learned patterns.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aragora.debate.phases._phase_invariant import require_phase_result

if TYPE_CHECKING:
    from aragora.debate.context import DebateContext
    from aragora.memory.consensus import ConsensusStrength
    from aragora.type_protocols import ConsensusMemoryProtocol

logger = logging.getLogger(__name__)


class ConsensusStorage:
    """Handles consensus outcome storage and crux extraction.

    Extracted from FeedbackPhase to improve modularity and enable
    reuse in other contexts (e.g., batch processing, replay).
    """

    def __init__(
        self,
        *,
        consensus_memory: ConsensusMemoryProtocol | None = None,
    ) -> None:
        """Initialize the consensus storage handler.

        Args:
            consensus_memory: ConsensusMemory for storing historical outcomes
        """
        self.consensus_memory = consensus_memory

    def store_consensus_outcome(self, ctx: DebateContext) -> str | None:
        """Store debate outcome in ConsensusMemory for historical retrieval.

        This enables future debates to benefit from past decisions,
        dissenting views, and learned patterns.

        Args:
            ctx: Debate context with result

        Returns:
            Consensus record ID if stored, None otherwise
        """
        if not self.consensus_memory:
            return None

        result = ctx.result
        if not result or not result.final_answer:
            return None

        try:
            from aragora.agents.errors import _build_error_action

            # Determine consensus strength from confidence
            strength = self._confidence_to_strength(result.confidence)

            # Determine agreeing vs dissenting agents from votes
            agreeing_agents = []
            dissenting_agents = []
            winner_agent = getattr(result, "winner", None)

            if result.votes and winner_agent:
                for vote in result.votes:
                    canonical = ctx.choice_mapping.get(vote.choice, vote.choice)
                    if canonical == winner_agent:
                        agreeing_agents.append(vote.agent)
                    else:
                        dissenting_agents.append(vote.agent)

            # Extract belief cruxes from result (set by AnalyticsPhase)
            belief_cruxes = getattr(result, "belief_cruxes", []) or []
            key_claims = [str(c) for c in belief_cruxes[:10]]  # Limit to 10

            # Store the consensus record
            consensus_record = self.consensus_memory.store_consensus(
                topic=ctx.env.task,
                conclusion=result.final_answer[:2000],
                strength=strength.value if hasattr(strength, "value") else str(strength),
                confidence=result.confidence,
                participating_agents=[a.name for a in ctx.agents],
                agreeing_agents=agreeing_agents,
                dissenting_agents=dissenting_agents,
                key_claims=key_claims,
                domain=ctx.domain,
                tags=[],
                debate_duration=getattr(result, "duration_seconds", 0.0),
                rounds=result.rounds_used,
                metadata={"belief_cruxes": key_claims} if key_claims else None,
            )

            # Store dissenting views as dissent records
            if dissenting_agents and result.votes:
                self._store_dissenting_views(ctx, consensus_record.id, dissenting_agents)

            logger.info(
                "[consensus_memory] Stored outcome for debate %s: "
                "strength=%s, confidence=%.2f, dissents=%d",
                ctx.debate_id,
                strength.value,
                result.confidence,
                len(dissenting_agents),
            )

            return consensus_record.id

        except ImportError:
            logger.debug("ConsensusMemory storage skipped: module not available")
            return None
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError, OSError) as e:
            from aragora.agents.errors import _build_error_action

            _, msg, exc_info = _build_error_action(e, "consensus_memory")
            logger.warning("ConsensusMemory storage failed: %s", msg, exc_info=exc_info)
            return None

    def _confidence_to_strength(self, confidence: float) -> ConsensusStrength:
        """Convert confidence score to ConsensusStrength enum."""
        from aragora.memory.consensus import ConsensusStrength

        if confidence >= 0.9:
            return ConsensusStrength.UNANIMOUS
        elif confidence >= 0.8:
            return ConsensusStrength.STRONG
        elif confidence >= 0.6:
            return ConsensusStrength.MODERATE
        elif confidence >= 0.5:
            return ConsensusStrength.WEAK
        else:
            return ConsensusStrength.SPLIT

    def _store_dissenting_views(
        self,
        ctx: DebateContext,
        consensus_id: str,
        dissenting_agents: list[str],
    ) -> None:
        """Store dissenting agent views as DissentRecords."""
        from aragora.memory.consensus import DissentType

        result = require_phase_result(ctx)
        consensus_memory = self.consensus_memory
        if consensus_memory is None:
            return

        # Find dissenting votes and their reasoning
        for vote in result.votes:
            if vote.agent not in dissenting_agents:
                continue

            # Get the vote's reasoning as dissent content
            reasoning = getattr(vote, "reasoning", "") or ""
            if not reasoning:
                reasoning = f"Voted for {vote.choice} instead of {result.winner}"

            try:
                consensus_memory.store_dissent(
                    debate_id=consensus_id,
                    agent_id=vote.agent,
                    dissent_type=DissentType.ALTERNATIVE_APPROACH,
                    content=reasoning[:500],
                    reasoning=f"Preferred: {vote.choice}",
                    confidence=getattr(vote, "confidence", 0.5),
                )
            except (TypeError, ValueError, AttributeError, KeyError) as e:
                logger.debug("Dissent storage failed for %s: %s", vote.agent, e)

    def store_cruxes(self, ctx: DebateContext, consensus_id: str | None = None) -> None:
        """Extract and store belief cruxes from the debate.

        Cruxes are key points of contention that drove the debate.
        These are stored with the consensus record to seed future debates
        on similar topics with known areas of disagreement.

        Args:
            ctx: Debate context with result
            consensus_id: ID of the consensus record (if not provided, uses ctx attribute)
        """
        if not self.consensus_memory:
            return

        # Get the consensus ID from parameter or context
        if not consensus_id:
            consensus_id = getattr(ctx, "_last_consensus_id", None)
        if not consensus_id:
            return

        result = ctx.result
        if not result:
            return

        # Extract cruxes from various sources
        cruxes = []

        # 1. From belief network if available
        if hasattr(ctx, "belief_network") and ctx.belief_network:
            try:
                network_cruxes = ctx.belief_network.get_cruxes(limit=3)
                for crux in network_cruxes:
                    cruxes.append(
                        {
                            "source": "belief_network",
                            "claim": crux.get("claim", ""),
                            "positions": crux.get("positions", {}),
                            "confidence_gap": crux.get("confidence_gap", 0.0),
                        }
                    )
            except (TypeError, ValueError, AttributeError, KeyError) as e:
                logger.debug("Belief network crux extraction failed: %s", e)

        # 2. From dissenting views - high-confidence dissents are cruxes
        if result.dissenting_views:
            for view in result.dissenting_views[:2]:
                if hasattr(view, "confidence") and view.confidence > 0.7:
                    cruxes.append(
                        {
                            "source": "dissent",
                            "claim": getattr(view, "content", str(view))[:200],
                            "agent": getattr(view, "agent", "unknown"),
                            "confidence": getattr(view, "confidence", 0.0),
                        }
                    )

        # 3. From votes with conflicting rationales
        if result.votes and len(result.votes) >= 2:
            vote_choices: dict[str, list[dict[str, str]]] = {}
            for vote in result.votes:
                choice = vote.choice
                if choice not in vote_choices:
                    vote_choices[choice] = []
                reasoning = getattr(vote, "reasoning", "")
                if reasoning:
                    vote_choices[choice].append(
                        {
                            "agent": vote.agent,
                            "reasoning": reasoning[:150],
                        }
                    )

            # If there are multiple choices with reasoning, that's a crux
            if len(vote_choices) > 1:
                cruxes.append(
                    {
                        "source": "vote_split",
                        "positions": {
                            choice: [v["reasoning"] for v in votes]
                            for choice, votes in vote_choices.items()
                            if votes
                        },
                    }
                )

        if not cruxes:
            return

        try:
            self.consensus_memory.update_cruxes(consensus_id, cruxes)
            logger.info(
                "[consensus_memory] Stored %d cruxes for consensus %s",
                len(cruxes),
                consensus_id[:8],
            )
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError, OSError) as e:
            logger.debug("Crux storage failed: %s", e)


__all__ = ["ConsensusStorage"]
