"""
Debate context adapter for RLM.

Extracted from bridge.py for maintainability.
Provides DebateContextAdapter for formatting debate history for RLM processing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .bridge import AragoraRLM
    from .types import RLMContext

from .compressor import HierarchicalCompressor
from .types import AbstractionLevel

logger = logging.getLogger(__name__)


class DebateContextAdapter:
    """
    Adapter for formatting debate history for RLM processing.

    Transforms Aragora debate structures into RLM-compatible format
    with programmatic access to rounds, proposals, critiques, and votes.

    Enhanced with query capabilities for drill-down access to specific
    aspects of debate history.
    """

    def __init__(self, aragora_rlm: AragoraRLM | None = None):
        """
        Initialize the adapter.

        Args:
            aragora_rlm: Optional AragoraRLM instance for queries
        """
        self._rlm = aragora_rlm
        self._cached_context: RLMContext | None = None
        self._compressor = HierarchicalCompressor()

    async def compress_debate(
        self,
        debate_result: Any,
    ) -> RLMContext:
        """
        Compress debate history into hierarchical RLM context.

        Args:
            debate_result: DebateResult from aragora.core

        Returns:
            RLMContext with hierarchical representation
        """
        text = self.to_text(debate_result)
        result = await self._compressor.compress(text, source_type="debate")
        self._cached_context = result.context
        return result.context

    async def query_debate(
        self,
        query: str,
        debate_result: Any | None = None,
        strategy: str = "auto",
    ) -> str:
        """
        Query debate history using RLM.

        Enables natural language queries about debate content:
        - "What were the main disagreements?"
        - "What did Alice argue about security?"
        - "Was consensus reached on pricing?"

        Args:
            query: Natural language query
            debate_result: Optional DebateResult (uses cached if None)
            strategy: Decomposition strategy (auto, grep, partition_map)

        Returns:
            Answer extracted from debate history
        """
        # Get or build context
        if debate_result:
            context = await self.compress_debate(debate_result)
        elif self._cached_context:
            context = self._cached_context
        else:
            return "No debate context available. Provide a debate_result."

        # Use RLM for query
        if self._rlm:
            result = await self._rlm.query(query, context, strategy)
            return result.answer
        else:
            # Fallback: search in context
            return self._simple_query(query, context)

    def _simple_query(self, query: str, context: RLMContext) -> str:
        """Simple keyword-based query fallback."""
        query_terms = query.lower().split()

        # Search in all levels, starting from summary
        for level in [AbstractionLevel.SUMMARY, AbstractionLevel.DETAILED, AbstractionLevel.FULL]:
            if level in context.levels:
                for node in context.levels[level]:
                    content_lower = node.content.lower()
                    matches = sum(1 for term in query_terms if term in content_lower)
                    if matches >= len(query_terms) // 2:
                        return f"From {level.name}:\n{node.content[:1000]}"

        return "No relevant information found in debate history."

    async def get_agent_positions(
        self,
        debate_result: Any,
        agent_name: str,
    ) -> str:
        """
        Get all positions/proposals from a specific agent.

        Args:
            debate_result: DebateResult
            agent_name: Name of agent to query

        Returns:
            Summary of agent's positions across rounds
        """
        data = self.format_for_rlm(debate_result)
        proposals = data["get_proposals_by"](agent_name)

        if not proposals:
            return f"No proposals found from agent '{agent_name}'"

        return f"## {agent_name}'s Positions ({len(proposals)} proposals)\n\n" + "\n\n---\n\n".join(
            f"**Proposal {i + 1}:**\n{p[:500]}{'...' if len(p) > 500 else ''}"
            for i, p in enumerate(proposals)
        )

    async def get_critiques_summary(
        self,
        debate_result: Any,
        target_agent: str | None = None,
    ) -> str:
        """
        Get summary of critiques, optionally filtered by target.

        Args:
            debate_result: DebateResult
            target_agent: Optional agent name to filter critiques for

        Returns:
            Summary of critiques
        """
        data = self.format_for_rlm(debate_result)

        if target_agent:
            critiques = data["get_critiques_for"](target_agent)
        else:
            critiques = data["CRITIQUES"]

        if not critiques:
            return "No critiques found."

        summary_parts = [f"## Critique Summary ({len(critiques)} total)\n"]

        for c in critiques[:10]:  # Limit to 10
            summary_parts.append(f"**{c['critic']} → {c['target']}**: {c['content'][:200]}...")

        return "\n\n".join(summary_parts)

    async def find_consensus_points(
        self,
        debate_result: Any,
    ) -> str:
        """
        Identify points of agreement across agents.

        Args:
            debate_result: DebateResult

        Returns:
            Summary of consensus points
        """
        # Use RLM to find consensus
        context = await self.compress_debate(debate_result)

        query = (
            "What points did all agents agree on? "
            "List specific areas of consensus or shared conclusions."
        )

        if self._rlm:
            result = await self._rlm.query(query, context, strategy="grep")
            return result.answer

        # Fallback: look for agreement keywords
        data = self.format_for_rlm(debate_result)
        agreement_indicators = []

        for r in data["ROUNDS"]:
            for p in r.get("proposals", []):
                content = p.get("content", "").lower()
                if any(w in content for w in ["agree", "consensus", "shared", "common ground"]):
                    agreement_indicators.append(p.get("content", "")[:200])

        if agreement_indicators:
            return "## Potential Consensus Points\n\n" + "\n---\n".join(agreement_indicators[:5])

        return "No explicit consensus points identified."

    async def find_disagreements(
        self,
        debate_result: Any,
    ) -> str:
        """
        Identify key points of disagreement.

        Args:
            debate_result: DebateResult

        Returns:
            Summary of disagreements
        """
        context = await self.compress_debate(debate_result)

        query = (
            "What were the main disagreements or conflicts between agents? "
            "List specific points where agents held opposing views."
        )

        if self._rlm:
            result = await self._rlm.query(query, context, strategy="grep")
            return result.answer

        # Fallback
        data = self.format_for_rlm(debate_result)
        disagreements = []

        for c in data["CRITIQUES"]:
            content = c.get("content", "").lower()
            if any(w in content for w in ["disagree", "incorrect", "wrong", "however", "but"]):
                disagreements.append(f"{c['critic']} → {c['target']}: {c.get('content', '')[:150]}")

        if disagreements:
            return "## Key Disagreements\n\n" + "\n\n".join(disagreements[:5])

        return "No explicit disagreements identified in critiques."

    def format_for_rlm(
        self,
        debate_result: Any,  # DebateResult from aragora.core
    ) -> dict[str, Any]:
        """
        Format debate result for RLM REPL access.

        Returns a dictionary that can be injected into REPL as variables:
        - ROUNDS: List of round data
        - PROPOSALS: Dict of agent -> proposal
        - CRITIQUES: Dict of (critic, target) -> critique
        - CONSENSUS: Final consensus if reached
        - get_round(n): Function to get specific round
        - get_critiques_for(agent): Function to get critiques targeting agent
        """
        rounds: list[dict[str, Any]] = []
        proposals: dict[str, list[str]] = {}
        critiques: list[dict[str, str]] = []

        if hasattr(debate_result, "rounds"):
            for i, r in enumerate(debate_result.rounds):
                round_proposals: list[dict[str, str]] = []
                round_critiques: list[dict[str, str]] = []

                # Extract proposals
                if hasattr(r, "proposals"):
                    for p in r.proposals:
                        agent = getattr(p, "agent", "unknown")
                        content = getattr(p, "content", str(p))
                        round_proposals.append(
                            {
                                "agent": agent,
                                "content": content,
                            }
                        )
                        proposals.setdefault(agent, []).append(content)

                # Extract critiques
                if hasattr(r, "critiques"):
                    for c in r.critiques:
                        critic = getattr(c, "critic", "unknown")
                        target = getattr(c, "target", "unknown")
                        content = getattr(c, "content", str(c))
                        critique_data = {
                            "critic": critic,
                            "target": target,
                            "content": content,
                        }
                        round_critiques.append(critique_data)
                        critiques.append(critique_data)

                round_data: dict[str, Any] = {
                    "number": i + 1,
                    "proposals": round_proposals,
                    "critiques": round_critiques,
                }
                rounds.append(round_data)

        # Extract consensus
        consensus = None
        if hasattr(debate_result, "consensus"):
            consensus = debate_result.consensus
        elif hasattr(debate_result, "final_answer"):
            consensus = debate_result.final_answer

        # Build helper functions
        def get_round(n: int) -> dict[str, Any] | None:
            if 0 < n <= len(rounds):
                return rounds[n - 1]
            return None

        def get_critiques_for(agent: str) -> list[dict[str, Any]]:
            return [c for c in critiques if c["target"] == agent]

        def get_proposals_by(agent: str) -> list[str]:
            return proposals.get(agent, [])

        return {
            "ROUNDS": rounds,
            "PROPOSALS": proposals,
            "CRITIQUES": critiques,
            "CONSENSUS": consensus,
            "ROUND_COUNT": len(rounds),
            "AGENTS": list(proposals.keys()),
            "get_round": get_round,
            "get_critiques_for": get_critiques_for,
            "get_proposals_by": get_proposals_by,
        }

    def to_text(self, debate_result: Any) -> str:
        """Convert debate result to text for compression."""
        data = self.format_for_rlm(debate_result)
        parts = []

        for r in data["ROUNDS"]:
            parts.append(f"## Round {r['number']}")

            for p in r["proposals"]:
                parts.append(f"### {p['agent']}'s Proposal")
                parts.append(p["content"])
                parts.append("")

            if r["critiques"]:
                parts.append("### Critiques")
                for c in r["critiques"]:
                    parts.append(f"**{c['critic']} → {c['target']}**: {c['content']}")
                parts.append("")

        if data["CONSENSUS"]:
            parts.append("## Consensus")
            parts.append(str(data["CONSENSUS"]))

        return "\n".join(parts)


__all__ = ["DebateContextAdapter"]
