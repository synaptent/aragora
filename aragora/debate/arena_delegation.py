"""
Arena delegation methods for component coordination.

Extracted from orchestrator.py to reduce file size while maintaining
the Arena class's role as the central coordination point.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aragora.core import Agent

if TYPE_CHECKING:
    from aragora.core import DebateResult
    from aragora.debate.agent_pool import AgentPool
    from aragora.debate.audience_manager import AudienceManager
    from aragora.debate.checkpoint_ops import CheckpointOperations
    from aragora.debate.context_delegation import ContextDelegator
    from aragora.debate.grounded_operations import GroundedOperations
    from aragora.debate.knowledge_mound_ops import KnowledgeMoundOperations
    from aragora.debate.prompt_builder import PromptBuilder
    from aragora.debate.roles_manager import RolesManager
    from aragora.events.spectate.stream import SpectatorStream

logger = logging.getLogger(__name__)


class ArenaDelegation:
    """
    Handles delegation of Arena methods to component subsystems.

    This class provides a unified interface for Arena to delegate operations
    to its various component managers without cluttering the main orchestrator.
    """

    def __init__(
        self,
        checkpoint_ops: CheckpointOperations,
        context_delegator: ContextDelegator,
        audience_manager: AudienceManager,
        agent_pool: AgentPool,
        roles_manager: RolesManager,
        spectator: SpectatorStream | None = None,
        grounded_ops: GroundedOperations | None = None,
        knowledge_ops: KnowledgeMoundOperations | None = None,
        prompt_builder: PromptBuilder | None = None,
    ):
        self._checkpoint_ops = checkpoint_ops
        self._context_delegator = context_delegator
        self._audience_manager = audience_manager
        self._agent_pool = agent_pool
        self._roles_manager = roles_manager
        self._spectator = spectator
        self._grounded_ops = grounded_ops
        self._knowledge_ops = knowledge_ops
        self._prompt_builder = prompt_builder

    # ==================== Context Delegation ====================

    def get_continuum_context(self) -> str:
        """Retrieve relevant memories from ContinuumMemory for debate context."""
        return self._context_delegator.get_continuum_context()

    # ==================== Checkpoint Operations ====================

    def store_debate_outcome(
        self, result: DebateResult, task: str, belief_cruxes: list | None = None
    ) -> None:
        """Store debate outcome. Delegates to CheckpointOperations."""
        processed_cruxes = None
        if belief_cruxes:
            processed_cruxes = [str(c) for c in belief_cruxes[:10]]
        self._checkpoint_ops.store_debate_outcome(result, task, belief_cruxes=processed_cruxes)

    def store_evidence(self, evidence_snippets: list, task: str) -> None:
        """Store evidence. Delegates to CheckpointOperations."""
        self._checkpoint_ops.store_evidence(evidence_snippets, task)

    def update_memory_outcomes(self, result: DebateResult) -> None:
        """Update memory outcomes. Delegates to CheckpointOperations."""
        self._checkpoint_ops.update_memory_outcomes(result)

    # ==================== Audience Management ====================

    def handle_user_event(self, event: Any) -> None:
        """Handle user participation events. Delegates to AudienceManager."""
        self._audience_manager.handle_event(event)

    def drain_user_events(self) -> None:
        """Drain pending user events. Delegates to AudienceManager."""
        self._audience_manager.drain_events()

    # ==================== Agent Pool Operations ====================

    def get_calibration_weight(self, agent_name: str) -> float:
        """Get calibration weight. Delegates to AgentPool."""
        return self._agent_pool._get_calibration_weight(agent_name)

    def compute_composite_judge_score(self, agent_name: str, domain: str) -> float:
        """Compute composite judge score. Delegates to AgentPool."""
        return self._agent_pool._compute_composite_score(agent_name, domain)

    def select_critics_for_proposal(
        self, proposal_agent: str, all_critics: list[Agent]
    ) -> list[Agent]:
        """Select critics for proposal. Delegates to AgentPool."""
        proposer = None
        for agent in all_critics:
            if getattr(agent, "name", str(agent)) == proposal_agent:
                proposer = agent
                break
        if proposer is None:
            proposer = all_critics[0] if all_critics else None

        return self._agent_pool.select_critics(
            proposer=proposer,
            candidates=all_critics,
        )

    # ==================== Role Management ====================

    def assign_roles(self) -> None:
        """Assign roles. Delegates to RolesManager."""
        self._roles_manager.assign_roles()

    def apply_agreement_intensity(self) -> None:
        """Apply agreement intensity. Delegates to RolesManager."""
        self._roles_manager.apply_agreement_intensity()

    def assign_stances(self, round_num: int = 0) -> None:
        """Assign stances. Delegates to RolesManager."""
        self._roles_manager.assign_stances(round_num)

    def get_stance_guidance(self, agent: Agent) -> str:
        """Get stance guidance. Delegates to RolesManager."""
        return self._roles_manager.get_stance_guidance(agent)

    def get_agreement_intensity_guidance(self) -> str:
        """Get agreement intensity guidance. Delegates to RolesManager."""
        return self._roles_manager.get_agreement_intensity_guidance()

    def get_role_context(self, agent: Agent) -> str:
        """Get role context. Delegates to RolesManager."""
        return self._roles_manager.get_role_context(agent)

    def format_role_assignments_for_log(self) -> str:
        """Format role assignments for log. Delegates to RolesManager."""
        return self._roles_manager.format_role_assignments_for_log()

    def log_role_assignments(self, round_num: int) -> None:
        """Log role assignments. Delegates to RolesManager."""
        self._roles_manager.log_role_assignments(round_num)

    def update_role_assignments(self, round_num: int) -> None:
        """Update role assignments. Delegates to RolesManager."""
        self._roles_manager.update_role_assignments(round_num)

    # ==================== Spectator Notifications ====================

    def notify_spectator(self, event_type: str, **kwargs: Any) -> None:
        """Notify spectator of an event."""
        if self._spectator:
            try:
                self._spectator.emit(event_type, **kwargs)
            except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
                logger.debug("Spectator notification failed: %s", e)

    # ==================== Grounded Operations ====================

    def record_grounded_position(
        self,
        agent_name: str,
        position_text: str,
        round_num: int,
        debate_id: str = "",
        evidence_ids: list[str] | None = None,
    ) -> None:
        """Record grounded position. Delegates to GroundedOperations.

        Note: evidence_ids is accepted for API compatibility but not used
        by the underlying record_position method.
        """
        if self._grounded_ops:
            self._grounded_ops.record_position(
                agent_name=agent_name,
                content=position_text,
                debate_id=debate_id,
                round_num=round_num,
            )

    def create_grounded_verdict(self, result: DebateResult) -> Any:
        """Create grounded verdict. Delegates to GroundedOperations."""
        if self._grounded_ops:
            return self._grounded_ops.create_grounded_verdict(result)
        return None

    # ==================== Knowledge Operations ====================

    async def fetch_knowledge_context(
        self,
        task: str,
        limit: int = 10,
        auth_context: Any | None = None,
    ) -> str | None:
        """Fetch knowledge context. Delegates to KnowledgeMoundOperations."""
        if self._knowledge_ops:
            if auth_context is None:
                return await self._knowledge_ops.fetch_knowledge_context(task, limit=limit)
            return await self._knowledge_ops.fetch_knowledge_context(
                task, limit=limit, auth_context=auth_context
            )
        return None

    async def ingest_debate_outcome(self, result: DebateResult) -> None:
        """Ingest debate outcome into knowledge. Delegates to KnowledgeMoundOperations."""
        if self._knowledge_ops:
            await self._knowledge_ops.ingest_debate_outcome(result)

    # ==================== Prompt Building ====================

    def get_persona_context(self, agent: Agent) -> str:
        """Get persona context for agent. Delegates to PromptBuilder."""
        if self._prompt_builder:
            return self._prompt_builder.get_persona_context(agent)
        return ""

    def get_flip_context(self, agent: Agent) -> str:
        """Get flip context for agent. Delegates to PromptBuilder."""
        if self._prompt_builder:
            return self._prompt_builder.get_flip_context(agent)
        return ""


__all__ = ["ArenaDelegation"]
