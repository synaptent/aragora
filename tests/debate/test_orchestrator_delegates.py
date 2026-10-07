"""
Tests for orchestrator_delegates.py - Thin delegation mixin methods for Arena.

Tests cover:
- Knowledge Mound delegation methods
- BeliefNetwork setup delegation
- Hook/Bead delegation methods
- Supabase/Memory delegation methods
- Output delegation methods
- Event emission delegation methods
- Grounded operations delegation methods
- Context delegation methods
- Roles manager delegation methods
- Checkpoint delegation methods
- User participation delegation methods
- Citation helper methods
- Agent selection delegation methods
- Utility delegation methods
- Security debate integration
- Error handling when sub-objects are missing
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.core import Agent, Critique, DebateResult, Environment, Message, Vote
from aragora.debate.orchestrator_delegates import ArenaDelegatesMixin


# =============================================================================
# Test Class - Simulates Arena with Mixin
# =============================================================================


class MockArenaWithDelegates(ArenaDelegatesMixin):
    """Mock Arena class that includes the delegates mixin for testing."""

    def __init__(self):
        # Initialize all the sub-objects that delegates depend on
        self._km_manager = MagicMock()
        self._knowledge_ops = MagicMock()
        self._checkpoint_ops = MagicMock()
        self._context_delegator = MagicMock()
        self._event_emitter = MagicMock()
        self._grounded_ops = MagicMock()
        self._prompt_context = MagicMock()
        self.agent_pool = MagicMock()
        self.agents = []
        self.audience_manager = MagicMock()
        self.citation_extractor = MagicMock()
        self.debate_embeddings = MagicMock()
        self.env = MagicMock()
        self.evidence_collector = MagicMock()
        self.prompt_builder = MagicMock()
        self.protocol = MagicMock()
        self.rlm_limiter = MagicMock()
        self.roles_manager = MagicMock()
        self.termination_checker = MagicMock()
        self.use_rlm_limiter = False
        self.enable_knowledge_retrieval = False
        self.voting_phase = MagicMock()
        self.current_role_assignments = {}

        # Culture hints storage
        self._culture_consensus_hint = None
        self._culture_extra_critiques = 0
        self._culture_early_consensus = None
        self._culture_domain_patterns = {}

    def _extract_debate_domain(self) -> str:
        return "test-domain"

    def _sync_prompt_builder_state(self) -> None:
        pass


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def arena():
    """Create a mock arena with delegates for testing."""
    return MockArenaWithDelegates()


@pytest.fixture
def mock_agent():
    """Create a mock agent."""
    agent = MagicMock(spec=Agent)
    agent.name = "test-agent"
    agent.model = "test-model"
    agent.role = "proposer"
    return agent


@pytest.fixture
def mock_result():
    """Create a mock DebateResult."""
    result = MagicMock(spec=DebateResult)
    result.id = "result-123"
    result.debate_id = "debate-456"
    result.task = "Test task"
    result.final_answer = "Test answer"
    result.confidence = 0.85
    result.consensus_reached = True
    result.rounds_used = 3
    result.participants = ["agent-1", "agent-2"]
    result.winner = "agent-1"
    result.messages = []
    result.votes = []
    result.critiques = []
    result.belief_cruxes = ["crux1", "crux2"]
    return result


@pytest.fixture
def mock_context():
    """Create a mock DebateContext."""
    ctx = MagicMock()
    ctx.debate_id = "debate-456"
    ctx.result = MagicMock()
    ctx.result.messages = []
    ctx.result.critiques = []
    ctx.result.votes = []
    return ctx


# =============================================================================
# Knowledge Mound Delegation Tests
# =============================================================================


class TestKnowledgeMoundDelegates:
    """Tests for Knowledge Mound delegation methods."""

    @pytest.mark.asyncio
    async def test_init_km_context_delegates_to_manager(self, arena):
        """Test _init_km_context delegates to ArenaKnowledgeManager."""
        arena._km_manager.init_context = AsyncMock()

        await arena._init_km_context("debate-123", "test-domain")

        arena._km_manager.init_context.assert_called_once_with(
            debate_id="debate-123",
            domain="test-domain",
            env=arena.env,
            agents=arena.agents,
            protocol=arena.protocol,
        )

    def test_get_culture_hints_delegates_to_manager(self, arena):
        """Test _get_culture_hints delegates to ArenaKnowledgeManager."""
        expected_hints = {"consensus_hint": "test", "extra_critiques": 2}
        arena._km_manager.get_culture_hints.return_value = expected_hints

        result = arena._get_culture_hints("debate-123")

        arena._km_manager.get_culture_hints.assert_called_once_with("debate-123")
        assert result == expected_hints

    def test_apply_culture_hints_delegates_and_stores_values(self, arena):
        """Test _apply_culture_hints delegates and stores culture values."""
        hints = {"consensus_hint": "high_confidence", "extra_critiques": 3}
        arena._km_manager.culture_consensus_hint = "high_confidence"
        arena._km_manager.culture_extra_critiques = 3
        arena._km_manager.culture_early_consensus = 0.9
        arena._km_manager.culture_domain_patterns = {"pattern": "value"}

        arena._apply_culture_hints(hints)

        arena._km_manager.apply_culture_hints.assert_called_once_with(hints)
        assert arena._culture_consensus_hint == "high_confidence"
        assert arena._culture_extra_critiques == 3
        assert arena._culture_early_consensus == 0.9
        assert arena._culture_domain_patterns == {"pattern": "value"}

    @pytest.mark.asyncio
    async def test_fetch_knowledge_context_delegates_to_manager(self, arena):
        """Test _fetch_knowledge_context delegates to ArenaKnowledgeManager."""
        arena._km_manager.fetch_context = AsyncMock(return_value="knowledge context")

        result = await arena._fetch_knowledge_context("test task", limit=5)

        arena._km_manager.fetch_context.assert_called_once_with("test task", 5, auth_context=None)
        assert result == "knowledge context"

    @pytest.mark.asyncio
    async def test_ingest_debate_outcome_delegates_to_manager(self, arena, mock_result):
        """Test _ingest_debate_outcome delegates to ArenaKnowledgeManager."""
        arena._km_manager.ingest_outcome = AsyncMock()

        await arena._ingest_debate_outcome(mock_result)

        arena._km_manager.ingest_outcome.assert_called_once_with(mock_result, arena.env)


# =============================================================================
# BeliefNetwork Delegation Tests
# =============================================================================


class TestBeliefNetworkDelegate:
    """Tests for BeliefNetwork setup delegation."""

    def test_setup_belief_network_calls_module_function(self, arena):
        """Test _setup_belief_network delegates to orchestrator_memory module."""
        with patch("aragora.debate.orchestrator_memory.setup_belief_network") as mock_setup:
            mock_network = MagicMock()
            mock_setup.return_value = mock_network

            result = arena._setup_belief_network("debate-123", "test topic", seed_from_km=True)

            mock_setup.assert_called_once_with("debate-123", "test topic", True)
            assert result == mock_network

    def test_setup_belief_network_without_km_seeding(self, arena):
        """Test _setup_belief_network with seed_from_km=False."""
        with patch("aragora.debate.orchestrator_memory.setup_belief_network") as mock_setup:
            mock_setup.return_value = None

            result = arena._setup_belief_network("debate-123", "topic", seed_from_km=False)

            mock_setup.assert_called_once_with("debate-123", "topic", False)


# =============================================================================
# Hook/Bead Delegation Tests
# =============================================================================


class TestHookBeadDelegates:
    """Tests for Hook/Bead delegation methods."""

    @pytest.mark.asyncio
    async def test_create_debate_bead_delegates_to_hooks(self, arena, mock_result):
        """Test _create_debate_bead delegates to orchestrator_hooks."""
        with patch("aragora.debate.orchestrator_hooks.create_debate_bead") as mock_create:
            mock_create.return_value = "bead-123"

            result = await arena._create_debate_bead(mock_result)

            mock_create.assert_called_once_with(mock_result, arena.protocol, arena.env, arena)
            assert result == "bead-123"

    @pytest.mark.asyncio
    async def test_create_pending_debate_bead_delegates(self, arena):
        """Test _create_pending_debate_bead delegates to orchestrator_hooks."""
        with patch("aragora.debate.orchestrator_hooks.create_pending_debate_bead") as mock_create:
            mock_create.return_value = "pending-bead-456"

            result = await arena._create_pending_debate_bead("debate-123", "test task")

            mock_create.assert_called_once_with(
                "debate-123",
                "test task",
                arena.protocol,
                arena.env,
                arena.agents,
                arena,
            )
            assert result == "pending-bead-456"

    @pytest.mark.asyncio
    async def test_update_debate_bead_delegates(self, arena, mock_result):
        """Test _update_debate_bead delegates to orchestrator_hooks."""
        with patch("aragora.debate.orchestrator_hooks.update_debate_bead") as mock_update:
            mock_update.return_value = None

            await arena._update_debate_bead("bead-123", mock_result, success=True)

            mock_update.assert_called_once_with("bead-123", mock_result, True, arena)

    @pytest.mark.asyncio
    async def test_init_hook_tracking_delegates(self, arena):
        """Test _init_hook_tracking delegates to orchestrator_hooks."""
        with patch("aragora.debate.orchestrator_hooks.init_hook_tracking") as mock_init:
            expected = {"entry1": "hook1", "entry2": "hook2"}
            mock_init.return_value = expected

            result = await arena._init_hook_tracking("debate-123", "bead-456")

            mock_init.assert_called_once_with(
                "debate-123", "bead-456", arena.protocol, arena.agents, arena
            )
            assert result == expected

    @pytest.mark.asyncio
    async def test_complete_hook_tracking_success(self, arena):
        """Test _complete_hook_tracking delegates for success case."""
        with patch("aragora.debate.orchestrator_hooks.complete_hook_tracking") as mock_complete:
            hook_entries = {"entry1": "hook1"}

            await arena._complete_hook_tracking("bead-123", hook_entries, success=True)

            mock_complete.assert_called_once_with("bead-123", hook_entries, True, arena, "")

    @pytest.mark.asyncio
    async def test_complete_hook_tracking_failure(self, arena):
        """Test _complete_hook_tracking delegates for failure case with error message."""
        with patch("aragora.debate.orchestrator_hooks.complete_hook_tracking") as mock_complete:
            hook_entries = {"entry1": "hook1"}

            await arena._complete_hook_tracking(
                "bead-123", hook_entries, success=False, error_msg="Test error"
            )

            mock_complete.assert_called_once_with(
                "bead-123", hook_entries, False, arena, "Test error"
            )

    @pytest.mark.asyncio
    async def test_recover_pending_debates_classmethod(self):
        """Test recover_pending_debates classmethod delegates properly."""
        with patch("aragora.debate.orchestrator_hooks.recover_pending_debates") as mock_recover:
            expected = [{"debate_id": "d1"}, {"debate_id": "d2"}]
            mock_recover.return_value = expected
            mock_store = MagicMock()

            result = await MockArenaWithDelegates.recover_pending_debates(
                bead_store=mock_store, max_age_hours=48
            )

            mock_recover.assert_called_once_with(mock_store, 48)
            assert result == expected


# =============================================================================
# Supabase/Memory Delegation Tests
# =============================================================================


class TestSupabaseMemoryDelegates:
    """Tests for Supabase and memory delegation methods."""

    def test_queue_for_supabase_sync_delegates(self, arena, mock_context, mock_result):
        """Test _queue_for_supabase_sync delegates to orchestrator_memory."""
        with patch("aragora.debate.orchestrator_memory.queue_for_supabase_sync") as mock_queue:
            arena._queue_for_supabase_sync(mock_context, mock_result)

            mock_queue.assert_called_once_with(mock_context, mock_result)

    @pytest.mark.asyncio
    async def test_compress_debate_messages_delegates(self, arena):
        """Test compress_debate_messages delegates to orchestrator_memory."""
        messages = [MagicMock(spec=Message), MagicMock(spec=Message)]
        critiques = [MagicMock(spec=Critique)]

        with patch("aragora.debate.orchestrator_memory.compress_debate_messages") as mock_compress:
            compressed_messages = [messages[0]]
            compressed_critiques = []
            mock_compress.return_value = (compressed_messages, compressed_critiques)

            result = await arena.compress_debate_messages(messages, critiques)

            mock_compress.assert_called_once_with(
                messages, critiques, arena.use_rlm_limiter, arena.rlm_limiter
            )
            assert result == (compressed_messages, compressed_critiques)


# =============================================================================
# Output Delegation Tests
# =============================================================================


class TestOutputDelegates:
    """Tests for output formatting delegation methods."""

    def test_format_conclusion_delegates(self, arena, mock_result):
        """Test _format_conclusion delegates to orchestrator_setup."""
        with patch("aragora.debate.orchestrator_setup.format_conclusion") as mock_format:
            mock_format.return_value = "Formatted conclusion"

            result = arena._format_conclusion(mock_result)

            mock_format.assert_called_once_with(mock_result)
            assert result == "Formatted conclusion"

    @pytest.mark.asyncio
    async def test_translate_conclusions_delegates(self, arena, mock_result):
        """Test _translate_conclusions delegates to orchestrator_setup."""
        with patch("aragora.debate.orchestrator_setup.translate_conclusions") as mock_translate:
            mock_translate.return_value = None

            await arena._translate_conclusions(mock_result)

            mock_translate.assert_called_once_with(mock_result, arena.protocol)


# =============================================================================
# Event Emission Delegation Tests
# =============================================================================


class TestEventEmissionDelegates:
    """Tests for event emission delegation methods."""

    def test_notify_spectator_delegates_to_emitter(self, arena):
        """Test _notify_spectator delegates to EventEmitter."""
        arena._notify_spectator("test_event", data="value", count=5)

        arena._event_emitter.notify_spectator.assert_called_once_with(
            "test_event", data="value", count=5
        )

    def test_emit_moment_event_delegates_to_emitter(self, arena):
        """Test _emit_moment_event delegates to EventEmitter."""
        moment = MagicMock()

        arena._emit_moment_event(moment)

        arena._event_emitter.emit_moment.assert_called_once_with(moment)

    def test_emit_agent_preview_delegates_to_emitter(self, arena, mock_agent):
        """Test _emit_agent_preview delegates to EventEmitter."""
        arena.agents = [mock_agent]
        arena.current_role_assignments = {"test-agent": MagicMock()}

        arena._emit_agent_preview()

        arena._event_emitter.emit_agent_preview.assert_called_once_with(
            arena.agents, arena.current_role_assignments
        )


# =============================================================================
# Grounded Operations Delegation Tests
# =============================================================================


class TestGroundedOperationsDelegates:
    """Tests for grounded operations delegation methods."""

    def test_record_grounded_position_delegates(self, arena):
        """Test _record_grounded_position delegates to GroundedOperations."""
        arena._record_grounded_position(
            agent_name="test-agent",
            content="Test position content",
            debate_id="debate-123",
            round_num=2,
            confidence=0.85,
            domain="test-domain",
        )

        arena._grounded_ops.record_position.assert_called_once_with(
            agent_name="test-agent",
            content="Test position content",
            debate_id="debate-123",
            round_num=2,
            confidence=0.85,
            domain="test-domain",
        )

    def test_record_grounded_position_uses_default_confidence(self, arena):
        """Test _record_grounded_position uses default confidence value."""
        from aragora.debate.config.defaults import DEBATE_DEFAULTS

        arena._record_grounded_position(
            agent_name="agent",
            content="content",
            debate_id="d-123",
            round_num=1,
        )

        call_kwargs = arena._grounded_ops.record_position.call_args.kwargs
        assert call_kwargs["confidence"] == DEBATE_DEFAULTS.coordinator_min_confidence_for_mound

    def test_update_agent_relationships_delegates(self, arena):
        """Test _update_agent_relationships delegates to GroundedOperations."""
        votes = [MagicMock(spec=Vote), MagicMock(spec=Vote)]

        arena._update_agent_relationships(
            debate_id="debate-123",
            participants=["agent1", "agent2"],
            winner="agent1",
            votes=votes,
        )

        arena._grounded_ops.update_relationships.assert_called_once_with(
            "debate-123", ["agent1", "agent2"], "agent1", votes
        )

    def test_create_grounded_verdict_delegates(self, arena, mock_result):
        """Test _create_grounded_verdict delegates to GroundedOperations."""
        expected_verdict = {"verdict": "approved", "confidence": 0.9}
        arena._grounded_ops.create_grounded_verdict.return_value = expected_verdict

        result = arena._create_grounded_verdict(mock_result)

        arena._grounded_ops.create_grounded_verdict.assert_called_once_with(mock_result)
        assert result == expected_verdict

    @pytest.mark.asyncio
    async def test_verify_claims_formally_delegates(self, arena, mock_result):
        """Test _verify_claims_formally delegates to GroundedOperations."""
        arena._grounded_ops.verify_claims_formally = AsyncMock()

        await arena._verify_claims_formally(mock_result)

        arena._grounded_ops.verify_claims_formally.assert_called_once_with(mock_result)


# =============================================================================
# Context Delegation Tests
# =============================================================================


class TestContextDelegates:
    """Tests for context delegation methods."""

    @pytest.mark.asyncio
    async def test_fetch_historical_context_delegates(self, arena):
        """Test _fetch_historical_context delegates to ContextDelegator."""
        arena._context_delegator.fetch_historical_context = AsyncMock(
            return_value="historical context"
        )

        result = await arena._fetch_historical_context("test task", limit=5)

        arena._context_delegator.fetch_historical_context.assert_called_once_with("test task", 5)
        assert result == "historical context"

    def test_format_patterns_for_prompt_delegates(self, arena):
        """Test _format_patterns_for_prompt delegates to ContextDelegator."""
        patterns = [{"pattern": "p1"}, {"pattern": "p2"}]
        arena._context_delegator.format_patterns_for_prompt.return_value = "formatted"

        result = arena._format_patterns_for_prompt(patterns)

        arena._context_delegator.format_patterns_for_prompt.assert_called_once_with(patterns)
        assert result == "formatted"

    def test_get_successful_patterns_from_memory_delegates(self, arena):
        """Test _get_successful_patterns_from_memory delegates to ContextDelegator."""
        arena._context_delegator.get_successful_patterns.return_value = "patterns"

        result = arena._get_successful_patterns_from_memory(limit=10)

        arena._context_delegator.get_successful_patterns.assert_called_once_with(10)
        assert result == "patterns"

    @pytest.mark.asyncio
    async def test_perform_research_delegates(self, arena):
        """Test _perform_research delegates to ContextDelegator."""
        arena._context_delegator.perform_research = AsyncMock(return_value="research results")

        result = await arena._perform_research("research topic")

        arena._context_delegator.perform_research.assert_called_once_with("research topic")
        assert result == "research results"

    @pytest.mark.asyncio
    async def test_gather_aragora_context_delegates(self, arena):
        """Test _gather_aragora_context delegates to ContextDelegator."""
        arena._context_delegator.gather_aragora_context = AsyncMock(return_value="aragora docs")

        result = await arena._gather_aragora_context("aragora question")

        arena._context_delegator.gather_aragora_context.assert_called_once_with("aragora question")
        assert result == "aragora docs"

    @pytest.mark.asyncio
    async def test_gather_evidence_context_delegates(self, arena):
        """Test _gather_evidence_context delegates to ContextDelegator."""
        arena._context_delegator.gather_evidence_context = AsyncMock(return_value="evidence")

        result = await arena._gather_evidence_context("evidence query")

        arena._context_delegator.gather_evidence_context.assert_called_once_with("evidence query")
        assert result == "evidence"

    @pytest.mark.asyncio
    async def test_gather_trending_context_delegates(self, arena):
        """Test _gather_trending_context delegates to ContextDelegator."""
        arena._context_delegator.gather_trending_context = AsyncMock(return_value="trending topics")

        result = await arena._gather_trending_context()

        arena._context_delegator.gather_trending_context.assert_called_once()
        assert result == "trending topics"

    @pytest.mark.asyncio
    async def test_refresh_evidence_for_round_delegates(self, arena, mock_context):
        """Test _refresh_evidence_for_round delegates to ContextDelegator."""
        arena._context_delegator.refresh_evidence_for_round = AsyncMock(return_value=5)
        arena.env.task = "test task"

        result = await arena._refresh_evidence_for_round("combined text", mock_context, round_num=2)

        arena._context_delegator.refresh_evidence_for_round.assert_called_once()
        call_kwargs = arena._context_delegator.refresh_evidence_for_round.call_args.kwargs
        assert call_kwargs["combined_text"] == "combined text"
        assert call_kwargs["evidence_collector"] == arena.evidence_collector
        assert call_kwargs["task"] == "test task"
        assert result == 5

    @pytest.mark.asyncio
    async def test_refresh_evidence_for_round_updates_km_prompt_context(self, arena, mock_context):
        """Round refresh appends KM background evidence for revision prompts."""
        arena._context_delegator.refresh_evidence_for_round = AsyncMock(return_value=2)
        arena.enable_knowledge_retrieval = True
        arena.env.task = "Design a rate limiter"
        arena._km_manager.fetch_context = AsyncMock(
            return_value="## KNOWLEDGE MOUND CONTEXT\nRelevant knowledge from organizational memory:\n\n**[debate]** (confidence: 90%)\nPrefer shared token buckets.\n"
        )
        arena._knowledge_ops._last_km_item_ids = ["km-1", "km-2"]
        arena.prompt_builder.get_knowledge_mound_context.return_value = (
            "## KNOWLEDGE MOUND CONTEXT\nExisting baseline context"
        )
        mock_context._prompt_builder = arena.prompt_builder
        mock_context._km_item_ids_used = ["km-0"]

        result = await arena._refresh_evidence_for_round("combined text", mock_context, round_num=3)

        assert result == 2
        arena._km_manager.fetch_context.assert_awaited_once()
        set_args = arena.prompt_builder.set_knowledge_context.call_args.args
        assert "Round 3 Background Evidence" in set_args[0]
        assert "Prefer shared token buckets." in set_args[0]
        assert set_args[1] == ["km-0", "km-1", "km-2"]
        assert mock_context._km_item_ids_used == ["km-0", "km-1", "km-2"]


# =============================================================================
# Roles Manager Delegation Tests
# =============================================================================


class TestRolesManagerDelegates:
    """Tests for roles manager delegation methods."""

    def test_assign_roles_delegates(self, arena):
        """Test _assign_roles delegates to RolesManager."""
        arena._assign_roles()

        arena.roles_manager.assign_initial_roles.assert_called_once()

    def test_apply_agreement_intensity_delegates(self, arena):
        """Test _apply_agreement_intensity delegates to RolesManager."""
        arena._apply_agreement_intensity()

        arena.roles_manager.apply_agreement_intensity.assert_called_once()

    def test_assign_stances_delegates(self, arena):
        """Test _assign_stances delegates to RolesManager."""
        arena._assign_stances(round_num=3)

        arena.roles_manager.assign_stances.assert_called_once_with(3)

    def test_get_stance_guidance_delegates(self, arena, mock_agent):
        """Test _get_stance_guidance delegates to RolesManager."""
        arena.roles_manager.get_stance_guidance.return_value = "stance guidance"

        result = arena._get_stance_guidance(mock_agent)

        arena.roles_manager.get_stance_guidance.assert_called_once_with(mock_agent)
        assert result == "stance guidance"

    def test_get_agreement_intensity_guidance_delegates(self, arena):
        """Test _get_agreement_intensity_guidance delegates to RolesManager."""
        arena.roles_manager._get_agreement_intensity_guidance.return_value = "intensity"

        result = arena._get_agreement_intensity_guidance()

        arena.roles_manager._get_agreement_intensity_guidance.assert_called_once()
        assert result == "intensity"

    def test_format_role_assignments_for_log(self, arena):
        """Test _format_role_assignments_for_log formats correctly."""
        # Create mock role assignments
        role1 = MagicMock()
        role1.role.value = "proposer"
        role2 = MagicMock()
        role2.role.value = "critic"
        arena.current_role_assignments = {"agent1": role1, "agent2": role2}

        result = arena._format_role_assignments_for_log()

        assert "agent1: proposer" in result
        assert "agent2: critic" in result

    def test_log_role_assignments_logs_when_assignments_exist(self, arena):
        """Test _log_role_assignments logs when assignments exist."""
        role = MagicMock()
        role.role.value = "proposer"
        arena.current_role_assignments = {"agent1": role}

        with patch("aragora.logging_config.get_logger") as mock_logger:
            mock_log = MagicMock()
            mock_logger.return_value = mock_log

            arena._log_role_assignments(round_num=2)

            mock_log.debug.assert_called()

    def test_log_role_assignments_skips_when_no_assignments(self, arena):
        """Test _log_role_assignments skips logging when no assignments."""
        arena.current_role_assignments = {}

        with patch("aragora.logging_config.get_logger") as mock_logger:
            mock_log = MagicMock()
            mock_logger.return_value = mock_log

            arena._log_role_assignments(round_num=2)

            mock_log.debug.assert_not_called()

    def test_update_role_assignments_delegates(self, arena):
        """Test _update_role_assignments delegates to RolesManager."""
        expected_assignments = {"agent1": MagicMock()}
        arena.roles_manager.current_role_assignments = expected_assignments

        arena._update_role_assignments(round_num=2)

        arena.roles_manager.update_role_assignments.assert_called_once_with(2, "test-domain")
        assert arena.current_role_assignments == expected_assignments

    def test_get_role_context_delegates(self, arena, mock_agent):
        """Test _get_role_context delegates to RolesManager."""
        arena.roles_manager.get_role_context.return_value = "role context"

        result = arena._get_role_context(mock_agent)

        arena.roles_manager.get_role_context.assert_called_once_with(mock_agent)
        assert result == "role context"

    def test_get_persona_context_delegates(self, arena, mock_agent):
        """Test _get_persona_context delegates to PromptContextBuilder."""
        arena._prompt_context.get_persona_context.return_value = "persona"

        result = arena._get_persona_context(mock_agent)

        arena._prompt_context.get_persona_context.assert_called_once_with(mock_agent)
        assert result == "persona"

    def test_get_flip_context_delegates(self, arena, mock_agent):
        """Test _get_flip_context delegates to PromptContextBuilder."""
        arena._prompt_context.get_flip_context.return_value = "flip context"

        result = arena._get_flip_context(mock_agent)

        arena._prompt_context.get_flip_context.assert_called_once_with(mock_agent)
        assert result == "flip context"

    def test_prepare_audience_context_delegates(self, arena):
        """Test _prepare_audience_context delegates to PromptContextBuilder."""
        arena._prompt_context.prepare_audience_context.return_value = "audience ctx"

        result = arena._prepare_audience_context(emit_event=True)

        arena._prompt_context.prepare_audience_context.assert_called_once_with(emit_event=True)
        assert result == "audience ctx"

    def test_build_proposal_prompt_delegates(self, arena, mock_agent):
        """Test _build_proposal_prompt delegates to PromptContextBuilder."""
        arena._prompt_context.build_proposal_prompt.return_value = "proposal prompt"

        result = arena._build_proposal_prompt(mock_agent)

        arena._prompt_context.build_proposal_prompt.assert_called_once_with(mock_agent)
        assert result == "proposal prompt"

    def test_build_revision_prompt_delegates(self, arena, mock_agent):
        """Test _build_revision_prompt delegates to PromptContextBuilder."""
        critiques = [MagicMock(spec=Critique)]
        arena._prompt_context.build_revision_prompt.return_value = "revision prompt"

        result = arena._build_revision_prompt(
            mock_agent, "original text", critiques, round_number=2
        )

        arena._prompt_context.build_revision_prompt.assert_called_once_with(
            mock_agent, "original text", critiques, round_number=2
        )
        assert result == "revision prompt"


# =============================================================================
# Checkpoint Delegation Tests
# =============================================================================


class TestCheckpointDelegates:
    """Tests for checkpoint delegation methods."""

    def test_store_debate_outcome_as_memory_delegates(self, arena, mock_result):
        """Test _store_debate_outcome_as_memory delegates to CheckpointOperations."""
        arena.env.task = "test task"

        arena._store_debate_outcome_as_memory(mock_result)

        arena._checkpoint_ops.store_debate_outcome.assert_called_once()
        call_args = arena._checkpoint_ops.store_debate_outcome.call_args
        assert call_args[0][0] == mock_result
        assert call_args[0][1] == "test task"

    def test_store_debate_outcome_handles_belief_cruxes(self, arena, mock_result):
        """Test _store_debate_outcome_as_memory handles belief_cruxes truncation."""
        mock_result.belief_cruxes = ["crux" + str(i) for i in range(15)]
        arena.env.task = "task"

        arena._store_debate_outcome_as_memory(mock_result)

        call_kwargs = arena._checkpoint_ops.store_debate_outcome.call_args.kwargs
        assert "belief_cruxes" in call_kwargs
        assert len(call_kwargs["belief_cruxes"]) == 10  # Truncated to 10

    def test_store_debate_outcome_handles_no_cruxes(self, arena, mock_result):
        """Test _store_debate_outcome_as_memory handles missing belief_cruxes."""
        del mock_result.belief_cruxes  # Remove attribute
        arena.env.task = "task"

        arena._store_debate_outcome_as_memory(mock_result)

        arena._checkpoint_ops.store_debate_outcome.assert_called_once()

    def test_store_evidence_in_memory_delegates(self, arena):
        """Test _store_evidence_in_memory delegates to CheckpointOperations."""
        evidence = [MagicMock(), MagicMock()]

        arena._store_evidence_in_memory(evidence, "test task")

        arena._checkpoint_ops.store_evidence.assert_called_once_with(evidence, "test task")

    def test_update_continuum_memory_outcomes_delegates(self, arena, mock_result):
        """Test _update_continuum_memory_outcomes delegates to CheckpointOperations."""
        arena._update_continuum_memory_outcomes(mock_result)

        arena._checkpoint_ops.update_memory_outcomes.assert_called_once_with(mock_result)

    @pytest.mark.asyncio
    async def test_create_checkpoint_delegates(self, arena, mock_context):
        """Test _create_checkpoint delegates to CheckpointOperations."""
        arena._checkpoint_ops.create_checkpoint = AsyncMock()

        await arena._create_checkpoint(mock_context, round_num=3)

        arena._checkpoint_ops.create_checkpoint.assert_called_once_with(
            mock_context, 3, arena.env, arena.agents, arena.protocol
        )


# =============================================================================
# User Participation Delegation Tests
# =============================================================================


class TestUserParticipationDelegates:
    """Tests for user participation delegation methods."""

    def test_handle_user_event_delegates(self, arena):
        """Test _handle_user_event delegates to AudienceManager."""
        event = MagicMock()

        arena._handle_user_event(event)

        arena.audience_manager.handle_event.assert_called_once_with(event)

    def test_drain_user_events_delegates(self, arena):
        """Test _drain_user_events delegates to AudienceManager."""
        arena._drain_user_events()

        arena.audience_manager.drain_events.assert_called_once()


# =============================================================================
# Citation Helper Tests
# =============================================================================


class TestCitationHelpers:
    """Tests for citation helper methods."""

    def test_has_high_priority_needs_filters_correctly(self, arena):
        """Test _has_high_priority_needs filters to high-priority items."""
        needs = [
            {"priority": "high", "claim": "claim1"},
            {"priority": "low", "claim": "claim2"},
            {"priority": "high", "claim": "claim3"},
            {"priority": "medium", "claim": "claim4"},
        ]

        result = arena._has_high_priority_needs(needs)

        assert len(result) == 2
        assert all(n["priority"] == "high" for n in result)

    def test_has_high_priority_needs_returns_empty_for_no_high(self, arena):
        """Test _has_high_priority_needs returns empty when no high priority."""
        needs = [
            {"priority": "low", "claim": "claim1"},
            {"priority": "medium", "claim": "claim2"},
        ]

        result = arena._has_high_priority_needs(needs)

        assert result == []

    def test_log_citation_needs_logs_when_high_priority_exists(self, arena):
        """Test _log_citation_needs logs when high priority needs exist."""
        needs = [{"priority": "high", "claim": "important"}]

        with patch("aragora.logging_config.get_logger") as mock_logger:
            mock_log = MagicMock()
            mock_logger.return_value = mock_log

            arena._log_citation_needs("agent1", needs)

            mock_log.debug.assert_called()

    def test_log_citation_needs_skips_when_no_high_priority(self, arena):
        """Test _log_citation_needs skips logging when no high priority needs."""
        needs = [{"priority": "low", "claim": "unimportant"}]

        with patch("aragora.logging_config.get_logger") as mock_logger:
            mock_log = MagicMock()
            mock_logger.return_value = mock_log

            arena._log_citation_needs("agent1", needs)

            mock_log.debug.assert_not_called()

    def test_extract_citation_needs_extracts_from_proposals(self, arena):
        """Test _extract_citation_needs extracts needs from all proposals."""
        proposals = {"agent1": "Proposal 1", "agent2": "Proposal 2"}
        arena.citation_extractor.identify_citation_needs.side_effect = [
            [{"priority": "high", "claim": "c1"}],
            [{"priority": "low", "claim": "c2"}],
        ]

        result = arena._extract_citation_needs(proposals)

        assert len(result) == 2
        assert "agent1" in result
        assert "agent2" in result

    def test_extract_citation_needs_returns_empty_when_no_extractor(self, arena):
        """Test _extract_citation_needs returns empty when no extractor."""
        arena.citation_extractor = None
        proposals = {"agent1": "Proposal"}

        result = arena._extract_citation_needs(proposals)

        assert result == {}

    def test_extract_citation_needs_skips_empty_needs(self, arena):
        """Test _extract_citation_needs skips agents with no needs."""
        proposals = {"agent1": "P1", "agent2": "P2"}
        arena.citation_extractor.identify_citation_needs.side_effect = [
            [],  # agent1 has no needs
            [{"priority": "high", "claim": "c"}],  # agent2 has needs
        ]

        result = arena._extract_citation_needs(proposals)

        assert "agent1" not in result
        assert "agent2" in result


# =============================================================================
# Agent Selection Delegation Tests
# =============================================================================


class TestAgentSelectionDelegates:
    """Tests for agent selection delegation methods."""

    def test_get_calibration_weight_delegates(self, arena):
        """Test _get_calibration_weight delegates to AgentPool."""
        arena.agent_pool._get_calibration_weight.return_value = 0.85

        result = arena._get_calibration_weight("test-agent")

        arena.agent_pool._get_calibration_weight.assert_called_once_with("test-agent")
        assert result == 0.85

    def test_compute_composite_judge_score_delegates(self, arena):
        """Test _compute_composite_judge_score delegates to AgentPool."""
        arena.agent_pool._compute_composite_score.return_value = 0.92

        result = arena._compute_composite_judge_score("test-agent")

        arena.agent_pool._compute_composite_score.assert_called_once_with(
            "test-agent", "test-domain"
        )
        assert result == 0.92

    def test_select_critics_for_proposal_delegates(self, arena, mock_agent):
        """Test _select_critics_for_proposal delegates to AgentPool."""
        all_critics = [mock_agent, MagicMock(name="critic1"), MagicMock(name="critic2")]
        expected_critics = [all_critics[1], all_critics[2]]
        arena.agent_pool.select_critics.return_value = expected_critics

        result = arena._select_critics_for_proposal("test-agent", all_critics)

        arena.agent_pool.select_critics.assert_called_once()
        assert result == expected_critics

    def test_select_critics_finds_proposer_in_list(self, arena):
        """Test _select_critics_for_proposal correctly finds proposer agent."""
        agent1 = MagicMock()
        agent1.name = "proposer"
        agent2 = MagicMock()
        agent2.name = "critic"
        all_critics = [agent1, agent2]
        arena.agents = [agent1, agent2]

        arena._select_critics_for_proposal("proposer", all_critics)

        call_kwargs = arena.agent_pool.select_critics.call_args.kwargs
        assert call_kwargs["proposer"] == agent1

    def test_select_critics_preserves_missing_proposer_identity(self, arena):
        """A critic-only candidate list must not relabel its first critic."""
        critic = MagicMock()
        critic.name = "critic"

        arena._select_critics_for_proposal("proposer", [critic])

        call_kwargs = arena.agent_pool.select_critics.call_args.kwargs
        assert call_kwargs["proposer"] == "proposer"

    def test_select_critics_keeps_sole_two_agent_critic_eligible(self, arena):
        """A proposer plus one dedicated critic must produce a critique."""
        proposer = MagicMock()
        proposer.name = "claude"
        critic = MagicMock()
        critic.name = "grok-cli"
        arena.agents = [proposer, critic]

        def select_critics(*, proposer, candidates):
            proposer_name = getattr(proposer, "name", str(proposer))
            return [
                candidate
                for candidate in candidates
                if getattr(candidate, "name", str(candidate)) != proposer_name
            ]

        arena.agent_pool.select_critics.side_effect = select_critics

        result = arena._select_critics_for_proposal("claude", [critic])

        assert result == [critic]


# =============================================================================
# Utility Delegation Tests
# =============================================================================


class TestUtilityDelegates:
    """Tests for utility delegation methods."""

    @pytest.mark.asyncio
    async def test_index_debate_async_indexes_successfully(self, arena):
        """Test _index_debate_async indexes debate when embeddings available."""
        arena.debate_embeddings.index_debate = AsyncMock()
        artifact = {"debate_id": "d-123", "content": "test"}

        await arena._index_debate_async(artifact)

        arena.debate_embeddings.index_debate.assert_called_once_with(artifact)

    @pytest.mark.asyncio
    async def test_index_debate_async_handles_missing_embeddings(self, arena):
        """Test _index_debate_async handles missing embeddings gracefully."""
        arena.debate_embeddings = None
        artifact = {"debate_id": "d-123"}

        # Should not raise
        await arena._index_debate_async(artifact)

    @pytest.mark.asyncio
    async def test_index_debate_async_handles_errors(self, arena):
        """Test _index_debate_async handles indexing errors gracefully."""
        arena.debate_embeddings.index_debate = AsyncMock(
            side_effect=RuntimeError("Indexing failed")
        )
        artifact = {"debate_id": "d-123"}

        # Should not raise, just log warning
        await arena._index_debate_async(artifact)

    def test_group_similar_votes_delegates(self, arena):
        """Test _group_similar_votes delegates to VotingPhase."""
        votes = [MagicMock(spec=Vote), MagicMock(spec=Vote)]
        expected = {"choice1": ["agent1", "agent2"]}
        arena.voting_phase.group_similar_votes.return_value = expected

        result = arena._group_similar_votes(votes)

        arena.voting_phase.group_similar_votes.assert_called_once_with(votes)
        assert result == expected

    @pytest.mark.asyncio
    async def test_check_judge_termination_delegates(self, arena):
        """Test _check_judge_termination delegates to TerminationChecker."""
        arena.termination_checker.check_judge_termination = AsyncMock(
            return_value=(True, "Debate concluded")
        )
        proposals = {"agent1": "proposal"}
        context = [MagicMock(spec=Message)]

        result = await arena._check_judge_termination(2, proposals, context)

        arena.termination_checker.check_judge_termination.assert_called_once_with(
            2, proposals, context
        )
        assert result == (True, "Debate concluded")

    @pytest.mark.asyncio
    async def test_check_early_stopping_delegates(self, arena):
        """Test _check_early_stopping delegates to TerminationChecker."""
        arena.termination_checker.check_early_stopping = AsyncMock(return_value=True)
        proposals = {"agent1": "proposal"}
        context = []

        result = await arena._check_early_stopping(3, proposals, context)

        arena.termination_checker.check_early_stopping.assert_called_once_with(
            3, proposals, context
        )
        assert result is True


# =============================================================================
# Security Debate Integration Tests
# =============================================================================


class TestSecurityDebateIntegration:
    """Tests for security debate integration methods."""

    @pytest.mark.asyncio
    async def test_run_security_debate_classmethod_delegates(self):
        """Test run_security_debate classmethod delegates properly."""
        with patch("aragora.debate.security_debate.run_security_debate") as mock_run:
            mock_result = MagicMock(spec=DebateResult)
            mock_run.return_value = mock_result
            mock_event = MagicMock()
            mock_agents = [MagicMock()]

            result = await MockArenaWithDelegates.run_security_debate(
                event=mock_event,
                agents=mock_agents,
                confidence_threshold=0.9,
                timeout_seconds=600,
                org_id="test-org",
            )

            mock_run.assert_called_once_with(
                event=mock_event,
                agents=mock_agents,
                confidence_threshold=0.9,
                timeout_seconds=600,
                org_id="test-org",
            )
            assert result == mock_result

    @pytest.mark.asyncio
    async def test_run_security_debate_uses_defaults(self):
        """Test run_security_debate uses default values correctly."""
        from aragora.debate.config.defaults import DEBATE_DEFAULTS

        with patch("aragora.debate.security_debate.run_security_debate") as mock_run:
            mock_event = MagicMock()

            await MockArenaWithDelegates.run_security_debate(event=mock_event)

            call_kwargs = mock_run.call_args.kwargs
            assert (
                call_kwargs["confidence_threshold"] == DEBATE_DEFAULTS.strong_consensus_confidence
            )
            assert call_kwargs["timeout_seconds"] == 300
            assert call_kwargs["org_id"] == "default"

    @pytest.mark.asyncio
    async def test_get_security_debate_agents_staticmethod_delegates(self):
        """Test _get_security_debate_agents staticmethod delegates properly."""
        with patch("aragora.debate.security_debate.get_security_debate_agents") as mock_get:
            mock_agents = [MagicMock(), MagicMock()]
            mock_get.return_value = mock_agents

            result = await MockArenaWithDelegates._get_security_debate_agents()

            mock_get.assert_called_once()
            assert result == mock_agents


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandlingWhenSubObjectsMissing:
    """Tests for graceful handling when sub-objects are missing or None."""

    def test_citation_extraction_handles_none_extractor(self, arena):
        """Test citation extraction returns empty when extractor is None."""
        arena.citation_extractor = None
        proposals = {"agent": "proposal text"}

        result = arena._extract_citation_needs(proposals)

        assert result == {}

    @pytest.mark.asyncio
    async def test_index_debate_handles_none_embeddings(self, arena):
        """Test debate indexing handles None embeddings."""
        arena.debate_embeddings = None

        # Should not raise
        await arena._index_debate_async({"debate_id": "test"})

    @pytest.mark.asyncio
    async def test_index_debate_handles_attribute_error(self, arena):
        """Test debate indexing handles AttributeError gracefully."""
        arena.debate_embeddings = MagicMock()
        arena.debate_embeddings.index_debate = AsyncMock(side_effect=AttributeError("No method"))

        # Should not raise
        await arena._index_debate_async({"debate_id": "test"})

    @pytest.mark.asyncio
    async def test_index_debate_handles_type_error(self, arena):
        """Test debate indexing handles TypeError gracefully."""
        arena.debate_embeddings = MagicMock()
        arena.debate_embeddings.index_debate = AsyncMock(side_effect=TypeError("Bad type"))

        # Should not raise
        await arena._index_debate_async({"debate_id": "test"})

    @pytest.mark.asyncio
    async def test_index_debate_handles_value_error(self, arena):
        """Test debate indexing handles ValueError gracefully."""
        arena.debate_embeddings = MagicMock()
        arena.debate_embeddings.index_debate = AsyncMock(side_effect=ValueError("Bad value"))

        # Should not raise
        await arena._index_debate_async({"debate_id": "test"})

    @pytest.mark.asyncio
    async def test_index_debate_handles_connection_error(self, arena):
        """Test debate indexing handles ConnectionError gracefully."""
        arena.debate_embeddings = MagicMock()
        arena.debate_embeddings.index_debate = AsyncMock(
            side_effect=ConnectionError("No connection")
        )

        # Should not raise
        await arena._index_debate_async({"debate_id": "test"})


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegrationWithArena:
    """Tests for integration behavior with Arena class."""

    def test_mixin_provides_all_delegate_methods(self):
        """Test that mixin provides all expected delegation methods."""
        arena = MockArenaWithDelegates()

        # Knowledge Mound delegates
        assert hasattr(arena, "_init_km_context")
        assert hasattr(arena, "_get_culture_hints")
        assert hasattr(arena, "_apply_culture_hints")
        assert hasattr(arena, "_fetch_knowledge_context")
        assert hasattr(arena, "_ingest_debate_outcome")

        # BeliefNetwork delegate
        assert hasattr(arena, "_setup_belief_network")

        # Hook delegates
        assert hasattr(arena, "_create_debate_bead")
        assert hasattr(arena, "_create_pending_debate_bead")
        assert hasattr(arena, "_update_debate_bead")
        assert hasattr(arena, "_init_hook_tracking")
        assert hasattr(arena, "_complete_hook_tracking")
        assert hasattr(arena, "recover_pending_debates")

        # Memory delegates
        assert hasattr(arena, "_queue_for_supabase_sync")
        assert hasattr(arena, "compress_debate_messages")

        # Output delegates
        assert hasattr(arena, "_format_conclusion")
        assert hasattr(arena, "_translate_conclusions")

        # Event emission delegates
        assert hasattr(arena, "_notify_spectator")
        assert hasattr(arena, "_emit_moment_event")
        assert hasattr(arena, "_emit_agent_preview")

        # Grounded ops delegates
        assert hasattr(arena, "_record_grounded_position")
        assert hasattr(arena, "_update_agent_relationships")
        assert hasattr(arena, "_create_grounded_verdict")
        assert hasattr(arena, "_verify_claims_formally")

        # Context delegates
        assert hasattr(arena, "_fetch_historical_context")
        assert hasattr(arena, "_format_patterns_for_prompt")
        assert hasattr(arena, "_get_successful_patterns_from_memory")
        assert hasattr(arena, "_perform_research")
        assert hasattr(arena, "_gather_aragora_context")
        assert hasattr(arena, "_gather_evidence_context")
        assert hasattr(arena, "_gather_trending_context")
        assert hasattr(arena, "_refresh_evidence_for_round")

        # Roles delegates
        assert hasattr(arena, "_assign_roles")
        assert hasattr(arena, "_apply_agreement_intensity")
        assert hasattr(arena, "_assign_stances")
        assert hasattr(arena, "_get_stance_guidance")
        assert hasattr(arena, "_update_role_assignments")
        assert hasattr(arena, "_get_role_context")
        assert hasattr(arena, "_get_persona_context")
        assert hasattr(arena, "_get_flip_context")
        assert hasattr(arena, "_prepare_audience_context")
        assert hasattr(arena, "_build_proposal_prompt")
        assert hasattr(arena, "_build_revision_prompt")

        # Checkpoint delegates
        assert hasattr(arena, "_store_debate_outcome_as_memory")
        assert hasattr(arena, "_store_evidence_in_memory")
        assert hasattr(arena, "_update_continuum_memory_outcomes")
        assert hasattr(arena, "_create_checkpoint")

        # User participation delegates
        assert hasattr(arena, "_handle_user_event")
        assert hasattr(arena, "_drain_user_events")

        # Citation helpers
        assert hasattr(arena, "_has_high_priority_needs")
        assert hasattr(arena, "_log_citation_needs")
        assert hasattr(arena, "_extract_citation_needs")

        # Agent selection delegates
        assert hasattr(arena, "_get_calibration_weight")
        assert hasattr(arena, "_compute_composite_judge_score")
        assert hasattr(arena, "_select_critics_for_proposal")

        # Utility delegates
        assert hasattr(arena, "_index_debate_async")
        assert hasattr(arena, "_group_similar_votes")
        assert hasattr(arena, "_check_judge_termination")
        assert hasattr(arena, "_check_early_stopping")

        # Security debate
        assert hasattr(arena, "run_security_debate")
        assert hasattr(arena, "_get_security_debate_agents")

    def test_mixin_methods_are_bound_correctly(self):
        """Test that mixin methods are bound to the instance."""
        arena = MockArenaWithDelegates()

        # Methods should be bound to instance
        assert arena._assign_roles.__self__ == arena
        assert arena._notify_spectator.__self__ == arena

    def test_mixin_class_methods_work_correctly(self):
        """Test that class methods work correctly."""
        # recover_pending_debates is a classmethod
        method = MockArenaWithDelegates.recover_pending_debates
        assert hasattr(method, "__func__")

    def test_mixin_static_methods_work_correctly(self):
        """Test that static methods work correctly."""
        # _get_security_debate_agents is a staticmethod
        method = MockArenaWithDelegates._get_security_debate_agents
        assert callable(method)
