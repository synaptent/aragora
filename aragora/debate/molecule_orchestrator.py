"""
Molecule-based Debate Orchestration (Gastown-inspired).

Integrates the MoleculeTracker from debate/molecules.py with the Arena
to enable fine-grained phase tracking with:
- Per-phase work molecules with capability requirements
- Automatic agent assignment based on affinity and skills
- Failure recovery with reassignment to capable agents
- Progress tracking independent of agent failures

Key integration points:
- Arena creates molecules at phase transitions
- MoleculeTracker manages assignment and lifecycle
- Failed molecules are reassigned to other agents
- Progress is persisted for crash recovery

Usage:
    from aragora.debate.molecule_orchestrator import MoleculeOrchestrator

    # During Arena initialization
    mol_orch = MoleculeOrchestrator(protocol, agent_profiles)

    # Create molecules for a debate round
    molecules = await mol_orch.create_round_molecules(
        debate_id="debate_123",
        round_number=1,
        task="Design a rate limiter",
        agents=arena.agents,
    )

    # Track phase completion
    await mol_orch.complete_molecule(molecule_id, output)

    # Get progress
    progress = mol_orch.get_progress(debate_id)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aragora.debate.molecules import (
    AgentProfileLike,
    Molecule,
    MoleculeStatus,
    MoleculeTracker,
    MoleculeType,
)

if TYPE_CHECKING:
    from aragora.core import Agent
    from aragora.protocols.debate import DebateProtocol

logger = logging.getLogger(__name__)


@dataclass
class AgentProfileWrapper:
    """
    Wrapper to convert Agent to AgentProfile-like interface.

    The MoleculeTracker expects AgentProfile objects with specific
    attributes. This wrapper provides that interface for Arena agents.
    """

    name: str
    capabilities: set[str] = field(default_factory=set)
    elo_rating: float = 1200.0
    availability: float = 1.0

    @classmethod
    def from_agent(cls, agent: Agent) -> AgentProfileWrapper:
        """Create wrapper from Arena agent."""
        # Extract capabilities from agent attributes
        capabilities = set()

        # All agents have basic reasoning
        capabilities.add("reasoning")

        # Check for specific capabilities based on model/name
        agent_name = getattr(agent, "name", "").lower()
        agent_model = getattr(agent, "model", "").lower()

        # Claude models are strong at analysis and synthesis
        if "claude" in agent_name or "claude" in agent_model:
            capabilities.update({"analysis", "synthesis", "creativity"})

        # GPT models are strong at quality assessment
        if "gpt" in agent_name or "openai" in agent_model:
            capabilities.update({"quality_assessment", "analysis"})

        # Gemini models have research capabilities
        if "gemini" in agent_name or "google" in agent_model:
            capabilities.update({"research", "analysis"})

        # Grok has lateral thinking
        if "grok" in agent_name:
            capabilities.update({"creativity", "analysis"})

        # DeepSeek strong at coding/analysis
        if "deepseek" in agent_name or "deepseek" in agent_model:
            capabilities.update({"analysis", "synthesis"})

        # Mistral good at structured tasks
        if "mistral" in agent_name or "mistral" in agent_model:
            capabilities.update({"analysis", "coordination"})

        # Get ELO from agent if available
        elo_rating = 1200.0
        if hasattr(agent, "elo_rating"):
            elo_rating = agent.elo_rating
        elif hasattr(agent, "calibration_score"):
            # Convert calibration to approximate ELO
            elo_rating = 1000 + (agent.calibration_score * 400)

        return cls(
            name=getattr(agent, "name", str(agent)),
            capabilities=capabilities,
            elo_rating=elo_rating,
            availability=1.0,
        )


@dataclass
class MoleculeExecutionResult:
    """Result of executing a molecule."""

    molecule_id: str
    success: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    agent: str | None = None
    duration_seconds: float = 0.0


class MoleculeOrchestrator:
    """
    Orchestrates molecule-based debate execution.

    Integrates with the Arena to provide:
    - Phase-level work tracking via molecules
    - Capability-based agent assignment
    - Automatic failure recovery and reassignment
    - Progress persistence for crash recovery
    """

    def __init__(
        self,
        protocol: DebateProtocol | None = None,
        max_attempts: int = 3,
    ):
        """
        Initialize the molecule orchestrator.

        Args:
            protocol: DebateProtocol with molecule_max_attempts setting
            max_attempts: Max retry attempts (overridden by protocol if set)
        """
        self._tracker = MoleculeTracker()
        self._agent_profiles: dict[str, AgentProfileWrapper] = {}
        self._debate_molecules: dict[str, list[str]] = {}  # debate_id -> molecule_ids

        # Get max attempts from protocol or use default
        if protocol and hasattr(protocol, "molecule_max_attempts"):
            self._max_attempts = protocol.molecule_max_attempts
        else:
            self._max_attempts = max_attempts

    def register_agents(self, agents: list[Agent]) -> None:
        """
        Register agents with capability profiles.

        Args:
            agents: List of Arena agents to register
        """
        for agent in agents:
            profile = AgentProfileWrapper.from_agent(agent)
            self._agent_profiles[profile.name] = profile
            logger.debug(
                "Registered agent %s with capabilities: %s", profile.name, profile.capabilities
            )

    def get_agent_profile(self, name: str) -> AgentProfileWrapper | None:
        """Get a registered agent profile by name."""
        return self._agent_profiles.get(name)

    async def create_round_molecules(
        self,
        debate_id: str,
        round_number: int,
        task: str,
        agents: list[Agent],
        include_synthesis: bool = True,
    ) -> list[Molecule]:
        """
        Create molecules for a debate round.

        Creates:
        - One PROPOSAL molecule per agent
        - One CRITIQUE molecule per agent pair
        - One SYNTHESIS molecule (optional)

        Args:
            debate_id: Unique debate identifier
            round_number: Current round (1-indexed)
            task: Debate task description
            agents: Participating agents
            include_synthesis: Whether to include synthesis phase

        Returns:
            List of created molecules
        """
        # Ensure agents are registered
        self.register_agents(agents)

        molecules = []

        # Create proposal molecules for each agent
        proposal_ids = []
        for agent in agents:
            mol = self._tracker.create_molecule(
                debate_id=debate_id,
                molecule_type=MoleculeType.PROPOSAL,
                round_number=round_number,
                input_data={
                    "task": task,
                    "agent": agent.name,
                },
            )
            mol.max_attempts = self._max_attempts
            proposal_ids.append(mol.molecule_id)
            molecules.append(mol)

        # Create critique molecules (each agent critiques others)
        critique_ids = []
        for i, critic in enumerate(agents):
            for j, target in enumerate(agents):
                if i != j:
                    mol = self._tracker.create_molecule(
                        debate_id=debate_id,
                        molecule_type=MoleculeType.CRITIQUE,
                        round_number=round_number,
                        input_data={
                            "critic": critic.name,
                            "target": target.name,
                            "task": task,
                        },
                        depends_on=[proposal_ids[j]],  # Depends on target's proposal
                    )
                    mol.max_attempts = self._max_attempts
                    critique_ids.append(mol.molecule_id)
                    molecules.append(mol)

        # Create synthesis molecule
        if include_synthesis:
            synthesis_mol = self._tracker.create_molecule(
                debate_id=debate_id,
                molecule_type=MoleculeType.SYNTHESIS,
                round_number=round_number,
                input_data={"task": task},
                depends_on=critique_ids,
            )
            synthesis_mol.max_attempts = self._max_attempts
            molecules.append(synthesis_mol)

        # Track debate molecules
        if debate_id not in self._debate_molecules:
            self._debate_molecules[debate_id] = []
        self._debate_molecules[debate_id].extend([m.molecule_id for m in molecules])

        logger.info(
            "Created %s molecules for debate %s round %s", len(molecules), debate_id, round_number
        )

        return molecules

    async def create_vote_molecules(
        self,
        debate_id: str,
        round_number: int,
        agents: list[Agent],
        proposal_molecule_ids: list[str] | None = None,
    ) -> list[Molecule]:
        """
        Create vote molecules for consensus phase.

        Args:
            debate_id: Debate identifier
            round_number: Current round
            agents: Voting agents
            proposal_molecule_ids: Proposal molecules to depend on

        Returns:
            List of vote molecules
        """
        molecules = []
        depends_on = proposal_molecule_ids or []

        for agent in agents:
            mol = self._tracker.create_molecule(
                debate_id=debate_id,
                molecule_type=MoleculeType.VOTE,
                round_number=round_number,
                input_data={"agent": agent.name},
                depends_on=depends_on,
            )
            mol.max_attempts = self._max_attempts
            molecules.append(mol)

        # Track
        if debate_id not in self._debate_molecules:
            self._debate_molecules[debate_id] = []
        self._debate_molecules[debate_id].extend([m.molecule_id for m in molecules])

        return molecules

    async def assign_molecule(
        self,
        molecule_id: str,
        agent_name: str | None = None,
    ) -> bool:
        """
        Assign a molecule to an agent.

        If agent_name is not provided, finds the best agent
        based on capabilities and affinity.

        Args:
            molecule_id: Molecule to assign
            agent_name: Optional specific agent (auto-selects if None)

        Returns:
            True if assignment succeeded
        """
        molecule = self._tracker.get_molecule(molecule_id)
        if not molecule:
            return False

        if agent_name:
            profile = self._agent_profiles.get(agent_name)
            if profile:
                return self._tracker.assign_molecule(molecule_id, profile)
            return False

        # Find best agent
        available: list[AgentProfileLike] = list(self._agent_profiles.values())
        best = self._tracker.find_best_agent(molecule, available)

        if best:
            return self._tracker.assign_molecule(molecule_id, best)

        return False

    async def start_molecule(self, molecule_id: str) -> bool:
        """Mark a molecule as in progress."""
        return self._tracker.start_molecule(molecule_id)

    async def complete_molecule(
        self,
        molecule_id: str,
        output: dict[str, Any],
    ) -> MoleculeExecutionResult:
        """
        Mark a molecule as completed with output.

        Args:
            molecule_id: Molecule to complete
            output: Output data from execution

        Returns:
            MoleculeExecutionResult with status
        """
        molecule = self._tracker.get_molecule(molecule_id)
        if not molecule:
            return MoleculeExecutionResult(
                molecule_id=molecule_id,
                success=False,
                error="Molecule not found",
            )

        agent = molecule.assigned_agent

        # Calculate duration if started_at is set
        duration = 0.0
        if molecule.started_at:
            started = datetime.fromisoformat(molecule.started_at)
            duration = (
                datetime.now(timezone.utc) - started.replace(tzinfo=timezone.utc)
            ).total_seconds()

        success = self._tracker.complete_molecule(molecule_id, output)

        return MoleculeExecutionResult(
            molecule_id=molecule_id,
            success=success,
            output=output,
            agent=agent,
            duration_seconds=duration,
        )

    async def fail_molecule(
        self,
        molecule_id: str,
        error: str,
    ) -> MoleculeExecutionResult:
        """
        Mark a molecule as failed.

        The molecule may be retried if attempts remain.

        Args:
            molecule_id: Molecule that failed
            error: Error message

        Returns:
            MoleculeExecutionResult with status
        """
        molecule = self._tracker.get_molecule(molecule_id)
        if not molecule:
            return MoleculeExecutionResult(
                molecule_id=molecule_id,
                success=False,
                error="Molecule not found",
            )

        agent = molecule.assigned_agent
        can_retry = molecule.can_retry()

        self._tracker.fail_molecule(molecule_id, error)

        # Log retry status
        if can_retry:
            logger.info(
                "Molecule %s failed but can retry (attempt %s/%s)",
                molecule_id,
                molecule.attempts,
                molecule.max_attempts,
            )
        else:
            logger.warning("Molecule %s failed with no retries remaining", molecule_id)

        return MoleculeExecutionResult(
            molecule_id=molecule_id,
            success=False,
            error=error,
            agent=agent,
        )

    def get_pending_molecules(self, debate_id: str) -> list[Molecule]:
        """Get pending molecules that can be assigned."""
        return self._tracker.get_pending_molecules(debate_id)

    def get_progress(self, debate_id: str) -> dict[str, Any]:
        """Get progress summary for a debate."""
        return self._tracker.get_progress(debate_id)

    def get_molecule(self, molecule_id: str) -> Molecule | None:
        """Get a molecule by ID."""
        return self._tracker.get_molecule(molecule_id)

    def get_debate_molecules(self, debate_id: str) -> list[Molecule]:
        """Get all molecules for a debate."""
        return self._tracker.get_debate_molecules(debate_id)

    async def recover_failed_molecules(
        self,
        debate_id: str,
    ) -> list[tuple[str, str]]:
        """
        Attempt to reassign failed molecules to other agents.

        Returns list of (molecule_id, new_agent) tuples for
        molecules that were successfully reassigned.
        """
        molecules = self._tracker.get_debate_molecules(debate_id)
        reassigned = []

        for mol in molecules:
            if mol.status == MoleculeStatus.FAILED and mol.can_retry():
                # Find a different agent
                available: list[AgentProfileLike] = [
                    p for p in self._agent_profiles.values() if p.name not in mol.assignment_history
                ]

                best = self._tracker.find_best_agent(mol, available)
                if best:
                    # Reset to pending and reassign
                    mol.status = MoleculeStatus.PENDING
                    if self._tracker.assign_molecule(mol.molecule_id, best):
                        reassigned.append((mol.molecule_id, best.name))
                        logger.info("Reassigned molecule %s to %s", mol.molecule_id, best.name)

        return reassigned

    def clear_debate(self, debate_id: str) -> None:
        """Clear all molecules for a completed debate."""
        self._tracker.clear_debate(debate_id)
        self._debate_molecules.pop(debate_id, None)

    def to_checkpoint_state(self, debate_id: str) -> dict[str, Any]:
        """
        Export molecule state for checkpointing.

        Returns serializable state that can be persisted.
        """
        molecules = self._tracker.get_debate_molecules(debate_id)
        return {
            "debate_id": debate_id,
            "molecules": [mol.to_dict() for mol in molecules],
            "agent_profiles": {
                name: {
                    "name": p.name,
                    "capabilities": list(p.capabilities),
                    "elo_rating": p.elo_rating,
                    "availability": p.availability,
                }
                for name, p in self._agent_profiles.items()
            },
            "progress": self.get_progress(debate_id),
        }

    def restore_from_checkpoint(self, state: dict[str, Any]) -> None:
        """
        Restore molecule state from checkpoint.

        Args:
            state: State dict from to_checkpoint_state()
        """
        debate_id = state["debate_id"]

        # Restore molecules
        for mol_data in state.get("molecules", []):
            mol = Molecule.from_dict(mol_data)
            self._tracker._molecules[mol.molecule_id] = mol

            if debate_id not in self._tracker._debate_molecules:
                self._tracker._debate_molecules[debate_id] = []
            self._tracker._debate_molecules[debate_id].append(mol.molecule_id)

        # Restore agent profiles
        for name, profile_data in state.get("agent_profiles", {}).items():
            self._agent_profiles[name] = AgentProfileWrapper(
                name=profile_data["name"],
                capabilities=set(profile_data.get("capabilities", [])),
                elo_rating=profile_data.get("elo_rating", 1200.0),
                availability=profile_data.get("availability", 1.0),
            )

        # Track
        self._debate_molecules[debate_id] = [
            mol["molecule_id"] for mol in state.get("molecules", [])
        ]

        logger.info(
            "Restored %s molecules for debate %s", len(state.get("molecules", [])), debate_id
        )


# Singleton instance
_default_orchestrator: MoleculeOrchestrator | None = None


def get_molecule_orchestrator(
    protocol: DebateProtocol | None = None,
) -> MoleculeOrchestrator:
    """Get the default molecule orchestrator instance."""
    global _default_orchestrator
    if _default_orchestrator is None:
        _default_orchestrator = MoleculeOrchestrator(protocol)
    return _default_orchestrator


def reset_molecule_orchestrator() -> None:
    """Reset the default orchestrator (for testing)."""
    global _default_orchestrator
    _default_orchestrator = None


__all__ = [
    "AgentProfileWrapper",
    "MoleculeExecutionResult",
    "MoleculeOrchestrator",
    "get_molecule_orchestrator",
    "reset_molecule_orchestrator",
]
