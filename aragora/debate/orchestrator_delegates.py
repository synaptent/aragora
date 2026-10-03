"""Thin delegation mixin methods extracted from Arena.

These methods delegate to sub-objects (GroundedOperations, ContextDelegator,
PromptContextBuilder, RolesManager, EventEmitter, etc.) and are mixed back
into the Arena class to keep its main module smaller while preserving the
public API surface.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aragora.core import Agent, Critique, DebateResult, Message, Vote
from aragora.debate.config.defaults import DEBATE_DEFAULTS
from aragora.exceptions import ExternalServiceError
from aragora.knowledge.mound.retrieval import build_debate_knowledge_query

if TYPE_CHECKING:
    import asyncio

    from aragora.debate.context import DebateContext
    from aragora.reasoning.belief import BeliefNetwork
    from aragora.events.security_events import SecurityEvent


logger = logging.getLogger(__name__)


class ArenaDelegatesMixin:
    """Mixin providing delegation methods for Arena.

    All methods in this class are bound to Arena via class inheritance.
    They delegate to composed sub-objects to keep the orchestrator module lean.
    """

    # Type stubs for attributes provided by Arena (the host class)
    _km_manager: Any
    _checkpoint_ops: Any
    _context_delegator: Any
    _event_emitter: Any
    _grounded_ops: Any
    _prompt_context: Any
    agent_pool: Any
    agents: Any
    audience_manager: Any
    citation_extractor: Any
    debate_embeddings: Any
    enable_supermemory: Any
    env: Any
    evidence_collector: Any
    prompt_builder: Any
    protocol: Any
    supermemory_adapter: Any
    supermemory_context_container_tag: Any
    supermemory_inject_on_start: Any
    supermemory_max_context_items: Any
    rlm_limiter: Any
    roles_manager: Any
    termination_checker: Any
    use_rlm_limiter: Any
    voting_phase: Any
    _extract_debate_domain: Any
    _sync_prompt_builder_state: Any

    # ------------------------------------------------------------------
    # Knowledge Mound Delegates
    # ------------------------------------------------------------------

    async def _init_km_context(self, debate_id: str, domain: str) -> "asyncio.Task[Any] | None":
        """Initialize Knowledge Mound context. Delegates to ArenaKnowledgeManager.

        Returns the in-flight culture-profile retrieval task (if one was
        scheduled) so the caller can await it before reading culture hints.
        """
        return await self._km_manager.init_context(
            debate_id=debate_id,
            domain=domain,
            env=self.env,
            agents=self.agents,
            protocol=self.protocol,
        )

    def _get_culture_hints(self, debate_id: str) -> dict[str, Any]:
        """Retrieve culture hints. Delegates to ArenaKnowledgeManager."""
        return self._km_manager.get_culture_hints(debate_id)

    def _apply_culture_hints(self, hints: dict[str, Any]) -> None:
        """Apply culture-derived hints. Delegates to ArenaKnowledgeManager."""
        self._km_manager.apply_culture_hints(hints)
        self._culture_consensus_hint = self._km_manager.culture_consensus_hint
        self._culture_extra_critiques = self._km_manager.culture_extra_critiques
        self._culture_early_consensus = self._km_manager.culture_early_consensus
        self._culture_domain_patterns = self._km_manager.culture_domain_patterns

    async def _fetch_knowledge_context(self, task: str, limit: int = 10) -> str | None:
        """Fetch relevant knowledge from Knowledge Mound for debate context.

        Delegates to ArenaKnowledgeManager.fetch_context().
        """
        return await self._km_manager.fetch_context(
            task,
            limit,
            auth_context=getattr(self, "auth_context", None),
        )

    async def _inject_supermemory_context(
        self,
        debate_id: str | None = None,
        debate_topic: str | None = None,
    ) -> None:
        """Inject external Supermemory context into PromptBuilder."""
        if not getattr(self, "enable_supermemory", False):
            return
        if not getattr(self, "supermemory_inject_on_start", True):
            return

        adapter = getattr(self, "supermemory_adapter", None)
        if not adapter or not self.prompt_builder:
            return

        try:
            if hasattr(self.prompt_builder, "set_supermemory_adapter"):
                self.prompt_builder.set_supermemory_adapter(adapter)

            await self.prompt_builder.inject_supermemory_context(
                debate_topic=debate_topic,
                debate_id=debate_id,
                container_tag=self.supermemory_context_container_tag,
                limit=self.supermemory_max_context_items,
            )
        except (RuntimeError, AttributeError, TypeError, ConnectionError, OSError) as e:
            logger = logging.getLogger(__name__)
            logger.debug("[supermemory] Context injection failed: %s", e)

    async def _ingest_debate_outcome(self, result: DebateResult) -> None:
        """Store debate outcome in Knowledge Mound for future retrieval.

        Delegates to ArenaKnowledgeManager.ingest_outcome().
        """
        await self._km_manager.ingest_outcome(result, self.env)

    # ------------------------------------------------------------------
    # BeliefNetwork Delegate
    # ------------------------------------------------------------------

    def _setup_belief_network(
        self,
        debate_id: str,
        topic: str,
        seed_from_km: bool = True,
    ) -> BeliefNetwork | None:
        """Initialize BeliefNetwork. Delegates to orchestrator_memory."""
        from aragora.debate.orchestrator_memory import setup_belief_network

        return setup_belief_network(debate_id, topic, seed_from_km)

    # ------------------------------------------------------------------
    # Hook / Bead Delegates
    # ------------------------------------------------------------------

    async def _create_debate_bead(self, result: DebateResult) -> str | None:
        """Create a Bead to track this debate decision. Delegates to orchestrator_hooks."""
        from aragora.debate.orchestrator_hooks import create_debate_bead

        return await create_debate_bead(result, self.protocol, self.env, self)

    async def _create_pending_debate_bead(self, debate_id: str, task: str) -> str | None:
        """Create a pending bead for GUPP tracking. Delegates to orchestrator_hooks."""
        from aragora.debate.orchestrator_hooks import create_pending_debate_bead

        return await create_pending_debate_bead(
            debate_id, task, self.protocol, self.env, self.agents, self
        )

    async def _update_debate_bead(self, bead_id: str, result: DebateResult, success: bool) -> None:
        """Update a pending debate bead. Delegates to orchestrator_hooks."""
        from aragora.debate.orchestrator_hooks import update_debate_bead

        await update_debate_bead(bead_id, result, success, self)

    async def _init_hook_tracking(self, debate_id: str, bead_id: str) -> dict[str, str]:
        """Initialize GUPP hook tracking. Delegates to orchestrator_hooks."""
        from aragora.debate.orchestrator_hooks import init_hook_tracking

        return await init_hook_tracking(debate_id, bead_id, self.protocol, self.agents, self)

    async def _complete_hook_tracking(
        self, bead_id: str, hook_entries: dict[str, str], success: bool, error_msg: str = ""
    ) -> None:
        """Complete or fail hook entries. Delegates to orchestrator_hooks."""
        from aragora.debate.orchestrator_hooks import complete_hook_tracking

        await complete_hook_tracking(bead_id, hook_entries, success, self, error_msg)

    @classmethod
    async def recover_pending_debates(
        cls,
        bead_store: Any = None,
        max_age_hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Recover pending debates from hook queues. Delegates to orchestrator_hooks."""
        from aragora.debate.orchestrator_hooks import recover_pending_debates

        return await recover_pending_debates(bead_store, max_age_hours)

    # ------------------------------------------------------------------
    # Supabase / Memory Delegates
    # ------------------------------------------------------------------

    def _queue_for_supabase_sync(self, ctx: DebateContext, result: DebateResult) -> None:
        """Queue debate result for background Supabase sync. Delegates to orchestrator_memory."""
        from aragora.debate.orchestrator_memory import queue_for_supabase_sync

        queue_for_supabase_sync(ctx, result)

    async def compress_debate_messages(
        self,
        messages: list[Message],
        critiques: list[Critique] | None = None,
    ) -> tuple[list[Message], list[Critique] | None]:
        """Compress debate messages using RLM cognitive load limiter.

        Delegates to orchestrator_memory.compress_debate_messages().
        """
        from aragora.debate.orchestrator_memory import compress_debate_messages

        return await compress_debate_messages(
            messages, critiques, self.use_rlm_limiter, self.rlm_limiter
        )

    # ------------------------------------------------------------------
    # Output Delegates
    # ------------------------------------------------------------------

    def _format_conclusion(self, result: DebateResult) -> str:
        """Format debate conclusion. Delegates to orchestrator_output."""
        from aragora.debate.orchestrator_setup import format_conclusion

        return format_conclusion(result)

    async def _translate_conclusions(self, result: DebateResult) -> None:
        """Translate conclusions. Delegates to orchestrator_output."""
        from aragora.debate.orchestrator_setup import translate_conclusions

        await translate_conclusions(result, self.protocol)

    # ------------------------------------------------------------------
    # Event Emission Delegates
    # ------------------------------------------------------------------

    def _notify_spectator(self, event_type: str, **kwargs: Any) -> None:
        """Notify spectator. Delegates to EventEmitter."""
        self._event_emitter.notify_spectator(event_type, **kwargs)

    def _emit_moment_event(self, moment: Any) -> None:
        """Emit moment event. Delegates to EventEmitter."""
        self._event_emitter.emit_moment(moment)

    def _emit_agent_preview(self) -> None:
        """Emit agent preview. Delegates to EventEmitter."""
        self._event_emitter.emit_agent_preview(self.agents, self.current_role_assignments)

    # ------------------------------------------------------------------
    # Grounded Operations Delegates
    # ------------------------------------------------------------------

    def _record_grounded_position(
        self,
        agent_name: str,
        content: str,
        debate_id: str,
        round_num: int,
        confidence: float = DEBATE_DEFAULTS.coordinator_min_confidence_for_mound,
        domain: str | None = None,
    ) -> None:
        """Record position. Delegates to GroundedOperations."""
        self._grounded_ops.record_position(
            agent_name=agent_name,
            content=content,
            debate_id=debate_id,
            round_num=round_num,
            confidence=confidence,
            domain=domain,
        )

    def _update_agent_relationships(
        self, debate_id: str, participants: list[str], winner: str | None, votes: list[Vote]
    ) -> None:
        """Update relationships. Delegates to GroundedOperations."""
        self._grounded_ops.update_relationships(debate_id, participants, winner, votes)

    def _create_grounded_verdict(self, result: DebateResult) -> Any:
        """Create verdict. Delegates to GroundedOperations."""
        return self._grounded_ops.create_grounded_verdict(result)

    async def _verify_claims_formally(self, result: DebateResult) -> None:
        """Verify claims with Z3. Delegates to GroundedOperations."""
        await self._grounded_ops.verify_claims_formally(result)

    # ------------------------------------------------------------------
    # Context Delegation
    # ------------------------------------------------------------------

    async def _fetch_historical_context(self, task: str, limit: int = 3) -> str:
        """Fetch similar past debates for historical context."""
        return await self._context_delegator.fetch_historical_context(task, limit)

    def _format_patterns_for_prompt(self, patterns: list[dict[str, Any]]) -> str:
        """Format learned patterns as prompt context for agents."""
        return self._context_delegator.format_patterns_for_prompt(patterns)

    def _get_successful_patterns_from_memory(self, limit: int = 5) -> str:
        """Retrieve successful patterns from CritiqueStore memory."""
        return self._context_delegator.get_successful_patterns(limit)

    async def _perform_research(self, task: str) -> str:
        """Perform multi-source research for the debate topic."""
        return await self._context_delegator.perform_research(task)

    async def _gather_aragora_context(self, task: str) -> str | None:
        """Gather Aragora-specific documentation context if relevant to task."""
        return await self._context_delegator.gather_aragora_context(task)

    async def _gather_evidence_context(self, task: str) -> str | None:
        """Gather evidence from web, GitHub, and local docs connectors."""
        return await self._context_delegator.gather_evidence_context(task)

    async def _gather_trending_context(self) -> str | None:
        """Gather pulse/trending context from social platforms."""
        return await self._context_delegator.gather_trending_context()

    async def _refresh_evidence_for_round(
        self, combined_text: str, ctx: DebateContext, round_num: int
    ) -> int:
        """Refresh evidence based on claims made during a debate round."""
        evidence_count = await self._context_delegator.refresh_evidence_for_round(
            combined_text=combined_text,
            evidence_collector=self.evidence_collector,
            task=self.env.task if self.env else "",
            evidence_store_callback=self._store_evidence_in_memory,
            prompt_builder=self.prompt_builder,
        )
        await self._refresh_knowledge_context_for_round(combined_text, ctx, round_num)
        return evidence_count

    async def _refresh_knowledge_context_for_round(
        self,
        combined_text: str,
        ctx: DebateContext,
        round_num: int,
    ) -> int:
        """Refresh KM-backed background evidence before the revision phase."""
        km_manager = getattr(self, "_km_manager", None)
        if not km_manager or not getattr(self, "enable_knowledge_retrieval", False):
            return 0

        query = build_debate_knowledge_query(self.env.task if self.env else "", combined_text)
        if not query:
            return 0

        try:
            knowledge_context = await km_manager.fetch_context(
                query,
                limit=5,
                auth_context=getattr(self, "auth_context", None),
            )
        except (
            AttributeError,
            ExternalServiceError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logger.debug("[knowledge_mound] Round refresh failed: %s", exc)
            return 0

        if not knowledge_context:
            return 0

        knowledge_ops = getattr(self, "_knowledge_ops", None)
        item_ids = list(getattr(knowledge_ops, "_last_km_item_ids", []) or [])
        tracked_item_ids = list(getattr(ctx, "_km_item_ids_used", []) or [])
        merged_item_ids = tracked_item_ids + [
            item_id for item_id in item_ids if item_id not in tracked_item_ids
        ]
        ctx._km_item_ids_used = merged_item_ids  # type: ignore[attr-defined]

        prompt_builder = getattr(ctx, "_prompt_builder", None) or getattr(
            self, "prompt_builder", None
        )
        round_context = f"### Round {round_num} Background Evidence\n{knowledge_context}"
        if prompt_builder and hasattr(prompt_builder, "set_knowledge_context"):
            existing_context = ""
            if hasattr(prompt_builder, "get_knowledge_mound_context"):
                existing_context = prompt_builder.get_knowledge_mound_context() or ""
            if round_context not in existing_context:
                merged_context = (
                    f"{existing_context}\n\n{round_context}".strip()
                    if existing_context
                    else round_context
                )
            else:
                merged_context = existing_context
            prompt_builder.set_knowledge_context(merged_context, merged_item_ids)
        else:
            if round_context not in (ctx.env.context or ""):
                if ctx.env.context:
                    ctx.env.context += "\n\n" + round_context
                else:
                    ctx.env.context = round_context

        return len(item_ids)

    # ------------------------------------------------------------------
    # Roles Manager Delegates
    # ------------------------------------------------------------------

    def _assign_roles(self) -> None:
        """Assign roles to agents based on protocol. Delegates to RolesManager."""
        self.roles_manager.assign_initial_roles()

    def _apply_agreement_intensity(self) -> None:
        """Apply agreement intensity guidance. Delegates to RolesManager."""
        self.roles_manager.apply_agreement_intensity()

    def _assign_stances(self, round_num: int = 0) -> None:
        """Assign debate stances to agents. Delegates to RolesManager."""
        self.roles_manager.assign_stances(round_num)

    def _get_stance_guidance(self, agent: Agent) -> str:
        """Get stance guidance for agent. Delegates to RolesManager."""
        return self.roles_manager.get_stance_guidance(agent)

    def _get_agreement_intensity_guidance(self) -> str:
        """Get agreement intensity guidance. Delegates to RolesManager."""
        return self.roles_manager._get_agreement_intensity_guidance()

    def _format_role_assignments_for_log(self) -> str:
        """Format current role assignments as a log-friendly string."""
        return ", ".join(
            f"{name}: {assign.role.value}" for name, assign in self.current_role_assignments.items()
        )

    def _log_role_assignments(self, round_num: int) -> None:
        """Log current role assignments if any exist."""
        from aragora.logging_config import get_logger as get_structured_logger

        _logger = get_structured_logger(__name__)
        if self.current_role_assignments:
            roles_str = self._format_role_assignments_for_log()
            _logger.debug("role_assignments round=%s roles=%s", round_num, roles_str)

    def _update_role_assignments(self, round_num: int) -> None:
        """Update cognitive role assignments for the current round."""
        debate_domain = self._extract_debate_domain()
        self.roles_manager.update_role_assignments(round_num, debate_domain)

        # Sync role assignments back to orchestrator for backward compatibility
        self.current_role_assignments = self.roles_manager.current_role_assignments
        self._log_role_assignments(round_num)

    def _get_role_context(self, agent: Agent) -> str:
        """Get cognitive role context for an agent. Delegates to RolesManager."""
        return self.roles_manager.get_role_context(agent)

    def _get_persona_context(self, agent: Agent) -> str:
        """Get persona context. Delegates to PromptContextBuilder."""
        return self._prompt_context.get_persona_context(agent)

    def _get_flip_context(self, agent: Agent) -> str:
        """Get flip/consistency context. Delegates to PromptContextBuilder."""
        return self._prompt_context.get_flip_context(agent)

    def _prepare_audience_context(self, emit_event: bool = False) -> str:
        """Prepare audience context for prompt building. Delegates to PromptContextBuilder."""
        self._sync_prompt_builder_state()
        return self._prompt_context.prepare_audience_context(emit_event=emit_event)

    def _build_proposal_prompt(self, agent: Agent) -> str:
        """Build the initial proposal prompt. Delegates to PromptContextBuilder."""
        self._sync_prompt_builder_state()
        self.prompt_builder.set_mode_for_phase("propose")
        return self._prompt_context.build_proposal_prompt(agent)

    def _build_revision_prompt(
        self, agent: Agent, original: str, critiques: list[Critique], round_number: int = 0
    ) -> str:
        """Build the revision prompt. Delegates to PromptContextBuilder."""
        self._sync_prompt_builder_state()
        self.prompt_builder.set_mode_for_phase("revise")
        return self._prompt_context.build_revision_prompt(
            agent, original, critiques, round_number=round_number
        )

    # ------------------------------------------------------------------
    # Checkpoint Delegates
    # ------------------------------------------------------------------

    def _store_debate_outcome_as_memory(self, result: DebateResult) -> None:
        """Store debate outcome. Delegates to CheckpointOperations."""
        belief_cruxes = getattr(result, "belief_cruxes", None)
        if belief_cruxes:
            belief_cruxes = [str(c) for c in belief_cruxes[:10]]
        self._checkpoint_ops.store_debate_outcome(
            result, self.env.task, belief_cruxes=belief_cruxes
        )

    def _store_evidence_in_memory(self, evidence_snippets: list[Any], task: str) -> None:
        """Store evidence. Delegates to CheckpointOperations."""
        self._checkpoint_ops.store_evidence(evidence_snippets, task)

    def _update_continuum_memory_outcomes(self, result: DebateResult) -> None:
        """Update memory outcomes. Delegates to CheckpointOperations."""
        self._checkpoint_ops.update_memory_outcomes(result)

    async def _create_checkpoint(self, ctx: DebateContext, round_num: int) -> None:
        """Create checkpoint. Delegates to CheckpointOperations."""
        await self._checkpoint_ops.create_checkpoint(
            ctx, round_num, self.env, self.agents, self.protocol
        )

    # ------------------------------------------------------------------
    # User Participation Delegates
    # ------------------------------------------------------------------

    def _handle_user_event(self, event: Any) -> None:
        """Handle user participation events. Delegates to AudienceManager."""
        self.audience_manager.handle_event(event)

    def _drain_user_events(self) -> None:
        """Drain pending user events. Delegates to AudienceManager."""
        self.audience_manager.drain_events()

    # ------------------------------------------------------------------
    # Citation Helpers
    # ------------------------------------------------------------------

    def _has_high_priority_needs(self, needs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter citation needs to high-priority items only."""
        return [n for n in needs if n["priority"] == "high"]

    def _log_citation_needs(self, agent_name: str, needs: list[dict[str, Any]]) -> None:
        """Log high-priority citation needs for an agent if any exist."""
        from aragora.logging_config import get_logger as get_structured_logger

        _logger = get_structured_logger(__name__)
        high_priority = self._has_high_priority_needs(needs)
        if high_priority:
            _logger.debug("citations_needed agent=%s count=%s", agent_name, len(high_priority))

    def _extract_citation_needs(self, proposals: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
        """Extract claims that need citations from all proposals."""
        if not self.citation_extractor:
            return {}

        citation_needs: dict[str, list[dict[str, Any]]] = {}
        for agent_name, proposal in proposals.items():
            needs = self.citation_extractor.identify_citation_needs(proposal)
            if needs:
                citation_needs[agent_name] = needs
                self._log_citation_needs(agent_name, needs)

        return citation_needs

    # ------------------------------------------------------------------
    # Agent Selection Delegates
    # ------------------------------------------------------------------

    def _get_calibration_weight(self, agent_name: str) -> float:
        """Get calibration weight. Delegates to AgentPool."""
        return self.agent_pool._get_calibration_weight(agent_name)

    def _compute_composite_judge_score(self, agent_name: str) -> float:
        """Compute composite judge score. Delegates to AgentPool."""
        return self.agent_pool._compute_composite_score(agent_name, self._extract_debate_domain())

    def _select_critics_for_proposal(
        self, proposal_agent: str, all_critics: list[Agent]
    ) -> list[Agent]:
        """Select critics for proposal. Delegates to AgentPool."""
        # Dedicated critic lists normally exclude the proposer. Resolve against
        # the full arena roster and preserve the name when only the identity is
        # available; treating the first critic as the proposer filters out the
        # sole critic in a two-agent debate.
        proposer = next(
            (
                agent
                for agent in self.agents
                if getattr(agent, "name", str(agent)) == proposal_agent
            ),
            None,
        )
        if proposer is None:
            proposer = next(
                (
                    agent
                    for agent in all_critics
                    if getattr(agent, "name", str(agent)) == proposal_agent
                ),
                proposal_agent,
            )

        return self.agent_pool.select_critics(
            proposer=proposer,
            candidates=all_critics,
        )

    # ------------------------------------------------------------------
    # Misc Utility Delegates
    # ------------------------------------------------------------------

    async def _index_debate_async(self, artifact: dict[str, Any]) -> None:
        """Index debate asynchronously to avoid blocking."""
        from aragora.logging_config import get_logger as get_structured_logger

        _logger = get_structured_logger(__name__)
        try:
            if self.debate_embeddings:
                await self.debate_embeddings.index_debate(artifact)
        except (AttributeError, TypeError, ValueError, RuntimeError, OSError, ConnectionError) as e:
            _logger.warning("Async debate indexing failed: %s", e)

    def _group_similar_votes(self, votes: list[Vote]) -> dict[str, list[str]]:
        """Group semantically similar vote choices. Delegates to VotingPhase."""
        return self.voting_phase.group_similar_votes(votes)

    async def _check_judge_termination(
        self, round_num: int, proposals: dict[str, str], context: list[Message]
    ) -> tuple[bool, str]:
        """Have a judge evaluate if the debate is conclusive. Delegates to TerminationChecker."""
        return await self.termination_checker.check_judge_termination(round_num, proposals, context)

    async def _check_early_stopping(
        self, round_num: int, proposals: dict[str, str], context: list[Message]
    ) -> bool:
        """Check if agents want to stop debate early. Delegates to TerminationChecker."""
        return await self.termination_checker.check_early_stopping(round_num, proposals, context)

    # ------------------------------------------------------------------
    # Security Debate Integration
    # ------------------------------------------------------------------

    @classmethod
    async def run_security_debate(
        cls,
        event: SecurityEvent,
        agents: list[Agent] | None = None,
        confidence_threshold: float = DEBATE_DEFAULTS.strong_consensus_confidence,
        timeout_seconds: int = 300,
        org_id: str = "default",
    ) -> DebateResult:
        """Run a security debate. Delegates to aragora.debate.security_debate."""
        from aragora.debate.security_debate import run_security_debate

        return await run_security_debate(
            event=event,
            agents=agents,
            confidence_threshold=confidence_threshold,
            timeout_seconds=timeout_seconds,
            org_id=org_id,
        )

    @staticmethod
    async def _get_security_debate_agents() -> list[Agent]:
        """Get agents suitable for security debates. Delegates to security_debate module."""
        from aragora.debate.security_debate import get_security_debate_agents

        return await get_security_debate_agents()
