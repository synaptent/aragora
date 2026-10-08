"""
Critique phase logic extracted from Arena.

Provides utilities for:
- Critic selection based on debate topology
- Critique collection and aggregation
- Cross-agent critique routing
"""

__all__ = [
    "CritiquePhase",
]

import hashlib
import logging
import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.core import Agent, Critique
    from aragora.protocols.debate import DebateProtocol

logger = logging.getLogger(__name__)


class CritiquePhase:
    """Handles critic selection and critique routing based on debate topology.

    Supports multiple topology patterns:
    - all-to-all: Every agent critiques every other agent
    - round-robin: Each agent critiques the next in sequence
    - ring: Agents critique their neighbors in a ring
    - star: Hub agent critiques everyone, or vice versa
    - sparse/random-graph: Random subset based on sparsity parameter
    """

    def __init__(self, protocol: "DebateProtocol", agents: list["Agent"]):
        """Initialize critique phase.

        Args:
            protocol: Debate protocol with topology configuration
            agents: List of all agents in the debate
        """
        self.protocol = protocol
        self.agents = agents

    def select_critics_for_proposal(
        self, proposal_agent: str, all_critics: list["Agent"]
    ) -> list["Agent"]:
        """Select which critics should critique the given proposal based on topology.

        Args:
            proposal_agent: Name of the agent whose proposal is being critiqued
            all_critics: List of all potential critic agents

        Returns:
            List of agents that should critique this proposal
        """
        topology = self.protocol.topology

        if topology == "all-to-all":
            return [c for c in all_critics if c.name != proposal_agent]

        elif topology == "round-robin":
            return self._select_round_robin(proposal_agent, all_critics)

        elif topology == "ring":
            return self._select_ring(proposal_agent, all_critics)

        elif topology == "star":
            return self._select_star(proposal_agent, all_critics)

        elif topology in ("sparse", "random-graph"):
            return self._select_sparse(proposal_agent, all_critics)

        else:
            # Default to all-to-all
            return [c for c in all_critics if c.name != proposal_agent]

    def _select_round_robin(self, proposal_agent: str, all_critics: list["Agent"]) -> list["Agent"]:
        """Round-robin: each critic critiques the next one in alphabetical order."""
        eligible_critics = [c for c in all_critics if c.name != proposal_agent]
        if not eligible_critics:
            return []

        # Sort for deterministic ordering
        eligible_critics_sorted = sorted(eligible_critics, key=lambda c: c.name)

        # Use stable hash for deterministic critic assignment
        proposal_hash = int(hashlib.sha256(proposal_agent.encode()).hexdigest(), 16)
        proposal_index = proposal_hash % len(eligible_critics_sorted)
        return [eligible_critics_sorted[proposal_index]]

    def _select_ring(self, proposal_agent: str, all_critics: list["Agent"]) -> list["Agent"]:
        """Ring topology: each agent critiques its neighbors."""
        agent_names = sorted([a.name for a in all_critics] + [proposal_agent])
        if proposal_agent in agent_names:
            agent_names.remove(proposal_agent)
        if not agent_names:
            return []

        # Find position of proposal_agent in the ring
        all_names = sorted([a.name for a in self.agents])
        if proposal_agent not in all_names:
            return all_critics  # fallback

        idx = all_names.index(proposal_agent)
        # Critique by left and right neighbors
        left = all_names[(idx - 1) % len(all_names)]
        right = all_names[(idx + 1) % len(all_names)]
        return [c for c in all_critics if c.name in (left, right)]

    def _select_star(self, proposal_agent: str, all_critics: list["Agent"]) -> list["Agent"]:
        """Star topology: hub critiques everyone, or everyone critiques hub."""
        hub = self.protocol.topology_hub_agent
        if not hub and self.agents:
            hub = self.agents[0].name

        if proposal_agent == hub:
            # Hub's proposal gets critiqued by all others
            return [c for c in all_critics if c.name != hub]
        else:
            # Others' proposals get critiqued only by hub
            return [c for c in all_critics if c.name == hub]

    def _select_sparse(self, proposal_agent: str, all_critics: list["Agent"]) -> list["Agent"]:
        """Sparse/random-graph: random subset based on sparsity parameter."""
        available_critics = [c for c in all_critics if c.name != proposal_agent]
        if not available_critics:
            return []

        sparsity = getattr(self.protocol, "topology_sparsity", 0.5)
        num_to_select = max(1, int(len(available_critics) * sparsity))

        # Deterministic random based on proposal_agent for reproducibility.
        # Use a local Random instance to avoid corrupting global state in concurrent debates.
        stable_seed = int(hashlib.sha256(proposal_agent.encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(stable_seed)
        selected = rng.sample(available_critics, min(num_to_select, len(available_critics)))
        return selected

    def aggregate_critiques(
        self, critiques: list["Critique"], by_target: bool = True
    ) -> dict[str, list["Critique"]]:
        """Aggregate critiques by target agent or by critic.

        Args:
            critiques: List of all critiques
            by_target: If True, group by target agent; if False, group by critic

        Returns:
            Dict mapping agent name to list of critiques
        """
        result: dict[str, list[Critique]] = {}

        for critique in critiques:
            key = critique.target if by_target else critique.agent
            if key not in result:
                result[key] = []
            result[key].append(critique)

        return result

    def get_critique_stats(self, critiques: list["Critique"]) -> dict[str, Any]:
        """Compute statistics about the critiques in a round.

        Args:
            critiques: List of critiques

        Returns:
            Dict with critique statistics
        """
        if not critiques:
            return {"count": 0, "avg_length": 0, "critics": [], "targets": []}

        critics = list(set(c.agent for c in critiques))
        targets = list(set(c.target for c in critiques))
        avg_length = sum(len(c.content) for c in critiques) / len(critiques)

        return {
            "count": len(critiques),
            "avg_length": avg_length,
            "critics": critics,
            "targets": targets,
            "by_critic": self.aggregate_critiques(critiques, by_target=False),
            "by_target": self.aggregate_critiques(critiques, by_target=True),
        }
