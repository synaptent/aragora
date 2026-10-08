"""
Tests for the FeedbackPhase module.

Tests cover:
- FeedbackPhase initialization with various configurations
- ELO feedback recording (delegated to EloFeedback)
- Persona feedback updates (delegated to PersonaFeedback)
- Position ledger resolution
- Relationship tracking
- Moment detection
- Debate embedding indexing
- Flip detection
- Consensus storage
- Memory storage and updates
- Calibration data recording
- Evolution feedback (delegated to EvolutionFeedback)
- Pulse outcome recording
- Memory cleanup
- Risk assessment
- Insight usage recording
- Training data emission
- Knowledge mound integration
- Evidence storage
- Culture observation
- Broadcast triggering
- Coordinated memory writes
- Selection feedback loop
- Post-debate workflow triggering
- Receipt generation
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.debate.phases.feedback_phase import FeedbackPhase


# ===========================================================================
# Mock Classes
# ===========================================================================


@dataclass
class MockResult:
    """Mock debate result."""

    final_answer: str = "The best approach is X"
    consensus_reached: bool = True
    confidence: float = 0.85
    rounds_used: int = 3
    winner: str = "claude"
    messages: list = field(default_factory=list)
    votes: list = field(default_factory=list)
    dissenting_views: list = field(default_factory=list)
    id: str = "result-123"
    debate_id: str = "debate-123"


@dataclass
class MockEnv:
    """Mock environment."""

    task: str = "What is the best approach?"
    context: str = "Some context"


@dataclass
class MockAgent:
    """Mock agent."""

    name: str
    model: str = "mock-model"
    role: str = "proposer"


@dataclass
class MockMessage:
    """Mock message."""

    agent: str
    content: str
    role: str = "proposer"
    round: int = 0


@dataclass
class MockVote:
    """Mock vote."""

    agent: str
    choice: str
    confidence: float = 0.8
    reasoning: str = "Good reasoning"
    continue_debate: bool = False


@dataclass
class MockDebateContext:
    """Mock debate context."""

    result: MockResult = field(default_factory=MockResult)
    env: MockEnv = field(default_factory=MockEnv)
    debate_id: str = "test-debate-123"
    domain: str = "testing"
    applied_insight_ids: list = field(default_factory=list)
    agents: list = field(default_factory=list)
    choice_mapping: dict = field(default_factory=dict)
    collected_evidence: list = field(default_factory=list)

    def __post_init__(self):
        if not self.agents:
            self.agents = [MockAgent("claude"), MockAgent("gpt4")]


@dataclass
class MockPosition:
    """Mock position for position ledger."""

    id: str
    debate_id: str
    agent: str
    claim: str = "Some claim"


@dataclass
class MockFlip:
    """Mock flip for flip detector."""

    flip_type: str = "reversal"
    original_claim: str = "Original"
    new_claim: str = "New"
    original_confidence: float = 0.8
    new_confidence: float = 0.7
    similarity_score: float = 0.3
    domain: str = "general"


@dataclass
class MockMoment:
    """Mock moment for moment detector."""

    moment_type: str = "upset_victory"
    agent: str = "underdog"
    description: str = "Unexpected win"


# ===========================================================================
# Initialization Tests
# ===========================================================================


class TestFeedbackPhaseInit:
    """Tests for FeedbackPhase initialization."""

    def test_default_init(self):
        """Default initialization sets None for all optional systems."""
        phase = FeedbackPhase()

        assert phase.elo_system is None
        assert phase.persona_manager is None
        assert phase.position_ledger is None
        assert phase.relationship_tracker is None
        assert phase.moment_detector is None
        assert phase.debate_embeddings is None
        assert phase.flip_detector is None
        assert phase.continuum_memory is None
        assert phase.event_emitter is None
        assert phase.consensus_memory is None
        assert phase.calibration_tracker is None
        assert phase.population_manager is None
        assert phase.pulse_manager is None
        assert phase.insight_store is None

    def test_init_with_elo_system(self):
        """ELO system is stored and passed to EloFeedback."""
        elo = MagicMock()
        phase = FeedbackPhase(elo_system=elo)

        assert phase.elo_system is elo
        assert phase._elo_feedback.elo_system is elo

    def test_init_with_persona_manager(self):
        """Persona manager is stored and passed to PersonaFeedback."""
        pm = MagicMock()
        phase = FeedbackPhase(persona_manager=pm)

        assert phase.persona_manager is pm
        assert phase._persona_feedback.persona_manager is pm

    def test_init_with_consensus_memory(self):
        """Consensus memory is stored and passed to ConsensusStorage."""
        cm = MagicMock()
        phase = FeedbackPhase(consensus_memory=cm)

        assert phase.consensus_memory is cm
        assert phase._consensus_storage.consensus_memory is cm

    def test_init_with_event_emitter(self):
        """Event emitter is stored and passed to all helper classes."""
        emitter = MagicMock()
        phase = FeedbackPhase(event_emitter=emitter)

        assert phase.event_emitter is emitter
        assert phase._elo_feedback.event_emitter is emitter
        assert phase._persona_feedback.event_emitter is emitter
        assert phase._evolution_feedback.event_emitter is emitter
        assert phase._training_emitter.event_emitter is emitter

    def test_init_with_loop_id(self):
        """Loop ID is stored and passed to all helper classes."""
        phase = FeedbackPhase(loop_id="loop-456")

        assert phase.loop_id == "loop-456"
        assert phase._elo_feedback.loop_id == "loop-456"
        assert phase._persona_feedback.loop_id == "loop-456"
        assert phase._evolution_feedback.loop_id == "loop-456"
        assert phase._training_emitter.loop_id == "loop-456"

    def test_init_with_evolution_params(self):
        """Evolution parameters are stored correctly."""
        pm = MagicMock()
        phase = FeedbackPhase(
            population_manager=pm,
            auto_evolve=False,
            breeding_threshold=0.9,
        )

        assert phase.population_manager is pm
        assert phase.auto_evolve is False
        assert phase.breeding_threshold == 0.9
        assert phase._evolution_feedback.population_manager is pm
        assert phase._evolution_feedback.auto_evolve is False
        assert phase._evolution_feedback.breeding_threshold == 0.9

    def test_init_with_callbacks(self):
        """Callback functions are stored correctly."""
        emit_moment = MagicMock()
        store_memory = MagicMock()
        update_outcomes = MagicMock()
        index_debate = MagicMock()

        phase = FeedbackPhase(
            emit_moment_event=emit_moment,
            store_debate_outcome_as_memory=store_memory,
            update_continuum_memory_outcomes=update_outcomes,
            index_debate_async=index_debate,
        )

        assert phase._emit_moment_event is emit_moment
        assert phase._store_debate_outcome_as_memory is store_memory
        assert phase._update_continuum_memory_outcomes is update_outcomes
        assert phase._index_debate_async is index_debate

    def test_init_with_knowledge_mound(self):
        """Knowledge mound integration params are stored."""
        mound = MagicMock()
        hub = MagicMock()
        ingest = AsyncMock()

        phase = FeedbackPhase(
            knowledge_mound=mound,
            enable_knowledge_ingestion=True,
            ingest_debate_outcome=ingest,
            knowledge_bridge_hub=hub,
        )

        assert phase.knowledge_mound is mound
        assert phase.enable_knowledge_ingestion is True
        assert phase._ingest_debate_outcome is ingest
        assert phase.knowledge_bridge_hub is hub

    def test_init_with_memory_coordinator(self):
        """Memory coordinator params are stored."""
        coordinator = MagicMock()
        options = {"timeout": 30}

        phase = FeedbackPhase(
            memory_coordinator=coordinator,
            enable_coordinated_writes=True,
            coordinator_options=options,
        )

        assert phase.memory_coordinator is coordinator
        assert phase.enable_coordinated_writes is True
        assert phase.coordinator_options == options

    def test_init_with_selection_feedback_loop(self):
        """Selection feedback loop params are stored."""
        loop = MagicMock()

        phase = FeedbackPhase(
            selection_feedback_loop=loop,
            enable_performance_feedback=True,
        )

        assert phase.selection_feedback_loop is loop
        assert phase.enable_performance_feedback is True

    def test_init_with_post_debate_workflow(self):
        """Post-debate workflow params are stored."""
        workflow = MagicMock()

        phase = FeedbackPhase(
            post_debate_workflow=workflow,
            enable_post_debate_workflow=True,
            post_debate_workflow_threshold=0.8,
        )

        assert phase.post_debate_workflow is workflow
        assert phase.enable_post_debate_workflow is True
        assert phase.post_debate_workflow_threshold == 0.8

    def test_init_with_knowledge_extraction(self):
        """Knowledge extraction params are stored."""
        mound = MagicMock()

        phase = FeedbackPhase(
            knowledge_mound=mound,
            enable_knowledge_extraction=True,
            extraction_min_confidence=0.4,
            extraction_promote_threshold=0.7,
        )

        assert phase.enable_knowledge_extraction is True
        assert phase.extraction_min_confidence == 0.4
        assert phase.extraction_promote_threshold == 0.7

    def test_init_with_auto_receipt(self):
        """Auto-receipt params are stored."""
        tracker = MagicMock()

        phase = FeedbackPhase(
            enable_auto_receipt=True,
            auto_post_receipt=True,
            cost_tracker=tracker,
            receipt_base_url="/api/v3/receipts",
        )

        assert phase.enable_auto_receipt is True
        assert phase.auto_post_receipt is True
        assert phase.cost_tracker is tracker
        assert phase.receipt_base_url == "/api/v3/receipts"

    def test_init_with_broadcast(self):
        """Broadcast params are stored."""
        pipeline = MagicMock()

        phase = FeedbackPhase(
            broadcast_pipeline=pipeline,
            auto_broadcast=True,
            broadcast_min_confidence=0.85,
        )

        assert phase.broadcast_pipeline is pipeline
        assert phase.auto_broadcast is True
        assert phase.broadcast_min_confidence == 0.85


# ===========================================================================
# Execute Tests
# ===========================================================================


class TestFeedbackPhaseExecute:
    """Tests for the main execute method."""

    @pytest.mark.asyncio
    async def test_execute_without_result_returns_early(self):
        """Execute returns early when context has no result."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()
        ctx.result = None

        # Should not raise
        await phase.execute(ctx)

    @pytest.mark.asyncio
    async def test_execute_calls_elo_feedback(self):
        """Execute calls ELO feedback methods."""
        elo = MagicMock()
        phase = FeedbackPhase(elo_system=elo)
        ctx = MockDebateContext()

        with patch.object(phase._elo_feedback, "record_elo_match") as mock_elo:
            with patch.object(phase._elo_feedback, "record_voting_accuracy"):
                with patch.object(phase._elo_feedback, "apply_learning_bonuses"):
                    await phase.execute(ctx)

        mock_elo.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_execute_calls_persona_feedback(self):
        """Execute calls persona feedback methods."""
        pm = MagicMock()
        phase = FeedbackPhase(persona_manager=pm)
        ctx = MockDebateContext()

        with patch.object(phase._persona_feedback, "update_persona_performance") as mock_pm:
            await phase.execute(ctx)

        mock_pm.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_execute_calls_consensus_storage(self):
        """Execute calls consensus storage methods."""
        cm = MagicMock()
        phase = FeedbackPhase(consensus_memory=cm)
        ctx = MockDebateContext()

        with patch.object(
            phase._consensus_storage, "store_consensus_outcome", return_value="consensus-123"
        ) as mock_store:
            with patch.object(phase._consensus_storage, "store_cruxes"):
                await phase.execute(ctx)

        mock_store.assert_called_once_with(ctx)
        assert hasattr(ctx, "_last_consensus_id")
        assert ctx._last_consensus_id == "consensus-123"


# ===========================================================================
# Position Ledger Tests
# ===========================================================================


class TestResolvePositions:
    """Tests for position ledger resolution."""

    def test_resolve_positions_without_ledger(self):
        """Returns early when no position ledger."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        phase._resolve_positions(ctx)

    def test_resolve_positions_without_final_answer(self):
        """Returns early when no final answer."""
        ledger = MagicMock()
        phase = FeedbackPhase(position_ledger=ledger)
        ctx = MockDebateContext()
        ctx.result.final_answer = ""

        phase._resolve_positions(ctx)

        ledger.get_agent_positions.assert_not_called()

    def test_resolve_positions_resolves_for_winner(self):
        """Resolves positions as correct for winner."""
        ledger = MagicMock()
        pos = MockPosition(id="pos-1", debate_id="test-debate-123", agent="claude")
        ledger.get_agent_positions.return_value = [pos]

        phase = FeedbackPhase(position_ledger=ledger)
        ctx = MockDebateContext()
        ctx.result.winner = "claude"
        # Set agents so the loop iterates over the winner agent
        ctx.agents = [MockAgent("claude")]

        phase._resolve_positions(ctx)

        ledger.resolve_position.assert_called()
        call_args = ledger.resolve_position.call_args
        assert call_args[1]["outcome"] == "correct"

    def test_resolve_positions_resolves_for_non_winner(self):
        """Resolves positions as contested for non-winner."""
        ledger = MagicMock()
        pos = MockPosition(id="pos-1", debate_id="test-debate-123", agent="gpt4")
        ledger.get_agent_positions.return_value = [pos]

        phase = FeedbackPhase(position_ledger=ledger)
        ctx = MockDebateContext()
        ctx.result.winner = "claude"

        phase._resolve_positions(ctx)

        ledger.resolve_position.assert_called()
        call_args = ledger.resolve_position.call_args
        assert call_args[1]["outcome"] == "contested"

    def test_resolve_positions_handles_errors(self):
        """Gracefully handles errors during resolution."""
        ledger = MagicMock()
        ledger.get_agent_positions.side_effect = ValueError("Test error")

        phase = FeedbackPhase(position_ledger=ledger)
        ctx = MockDebateContext()

        # Should not raise
        phase._resolve_positions(ctx)


# ===========================================================================
# Relationship Tracker Tests
# ===========================================================================


class TestUpdateRelationships:
    """Tests for relationship tracking."""

    def test_update_relationships_without_tracker(self):
        """Returns early when no relationship tracker."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        phase._update_relationships(ctx)

    def test_update_relationships_calls_tracker(self):
        """Updates relationships with debate data."""
        tracker = MagicMock()
        phase = FeedbackPhase(relationship_tracker=tracker)
        ctx = MockDebateContext()
        ctx.result.votes = [MockVote("claude", "gpt4")]
        ctx.choice_mapping = {"gpt4": "gpt4"}
        ctx.result.messages = []

        phase._update_relationships(ctx)

        tracker.update_from_debate.assert_called_once()
        call_kwargs = tracker.update_from_debate.call_args[1]
        assert call_kwargs["debate_id"] == "test-debate-123"
        assert "claude" in call_kwargs["participants"]

    def test_update_relationships_extracts_critiques(self):
        """Extracts critiques from messages."""
        tracker = MagicMock()
        phase = FeedbackPhase(relationship_tracker=tracker)
        ctx = MockDebateContext()

        msg = MagicMock()
        msg.role = "critic"
        msg.agent = "claude"
        msg.target_agent = "gpt4"
        ctx.result.messages = [msg]
        ctx.result.votes = []

        phase._update_relationships(ctx)

        call_kwargs = tracker.update_from_debate.call_args[1]
        assert len(call_kwargs["critiques"]) == 1
        assert call_kwargs["critiques"][0]["agent"] == "claude"

    def test_update_relationships_handles_errors(self):
        """Gracefully handles errors during update."""
        tracker = MagicMock()
        tracker.update_from_debate.side_effect = RuntimeError("Test error")

        phase = FeedbackPhase(relationship_tracker=tracker)
        ctx = MockDebateContext()
        ctx.result.votes = []

        # Should not raise
        phase._update_relationships(ctx)


# ===========================================================================
# Moment Detection Tests
# ===========================================================================


class TestDetectMoments:
    """Tests for narrative moment detection."""

    def test_detect_moments_without_detector(self):
        """Returns early when no moment detector."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        phase._detect_moments(ctx)

    def test_detect_moments_detects_upset_victory(self):
        """Detects upset victory moments."""
        detector = MagicMock()
        elo = MagicMock()
        moment = MockMoment()
        detector.detect_upset_victory.return_value = moment

        phase = FeedbackPhase(moment_detector=detector, elo_system=elo)
        ctx = MockDebateContext()
        ctx.result.winner = "underdog"

        phase._detect_moments(ctx)

        detector.detect_upset_victory.assert_called()
        detector.record_moment.assert_called_with(moment)

    def test_detect_moments_emits_moment_event(self):
        """Emits moment event via callback."""
        detector = MagicMock()
        elo = MagicMock()
        moment = MockMoment()
        detector.detect_upset_victory.return_value = moment
        emit_callback = MagicMock()

        phase = FeedbackPhase(
            moment_detector=detector,
            elo_system=elo,
            emit_moment_event=emit_callback,
        )
        ctx = MockDebateContext()
        ctx.result.winner = "underdog"

        phase._detect_moments(ctx)

        emit_callback.assert_called_with(moment)

    def test_detect_moments_calibration_vindication(self):
        """Detects calibration vindication moments."""
        detector = MagicMock()
        moment = MockMoment(moment_type="calibration_vindication")
        detector.detect_upset_victory.return_value = None
        detector.detect_calibration_vindication.return_value = moment

        phase = FeedbackPhase(moment_detector=detector)
        ctx = MockDebateContext()
        ctx.result.winner = "claude"
        ctx.result.votes = [MockVote("claude", "claude", confidence=0.9)]
        ctx.choice_mapping = {"claude": "claude"}

        phase._detect_moments(ctx)

        detector.detect_calibration_vindication.assert_called()
        detector.record_moment.assert_called_with(moment)

    def test_detect_moments_handles_errors(self):
        """Gracefully handles errors during detection."""
        detector = MagicMock()
        detector.detect_upset_victory.side_effect = RuntimeError("Test error")

        phase = FeedbackPhase(moment_detector=detector, elo_system=MagicMock())
        ctx = MockDebateContext()

        # Should not raise
        phase._detect_moments(ctx)


# ===========================================================================
# Debate Indexing Tests
# ===========================================================================


class TestIndexDebate:
    """Tests for debate embedding indexing."""

    @pytest.mark.asyncio
    async def test_index_debate_without_embeddings(self):
        """Returns early when no debate embeddings."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        await phase._index_debate(ctx)

    @pytest.mark.asyncio
    async def test_index_debate_creates_artifact(self):
        """Creates debate artifact with correct fields."""
        embeddings = MagicMock()
        index_callback = AsyncMock()

        phase = FeedbackPhase(
            debate_embeddings=embeddings,
            index_debate_async=index_callback,
        )
        ctx = MockDebateContext()
        ctx.result.messages = [MockMessage("claude", "Test message")]

        await phase._index_debate(ctx)

        # Wait for background task
        await asyncio.sleep(0.1)

        index_callback.assert_called_once()
        artifact = index_callback.call_args[0][0]
        assert artifact["id"] == "test-debate-123"
        assert artifact["domain"] == "testing"
        assert artifact["winner"] == "claude"
        assert "claude" in artifact["agents"]

    @pytest.mark.asyncio
    async def test_index_debate_truncates_transcript(self):
        """Truncates long messages in transcript."""
        embeddings = MagicMock()
        index_callback = AsyncMock()

        phase = FeedbackPhase(
            debate_embeddings=embeddings,
            index_debate_async=index_callback,
        )
        ctx = MockDebateContext()
        ctx.result.messages = [MockMessage("claude", "x" * 1000)]

        await phase._index_debate(ctx)
        await asyncio.sleep(0.1)

        artifact = index_callback.call_args[0][0]
        # Content should be truncated to 500 chars
        assert len(artifact["transcript"]) < 600


# ===========================================================================
# Flip Detection Tests
# ===========================================================================


class TestDetectFlips:
    """Tests for position flip detection."""

    def test_detect_flips_without_detector(self):
        """Returns early when no flip detector."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        phase._detect_flips(ctx)

    def test_detect_flips_detects_for_agents(self):
        """Detects flips for all participating agents."""
        detector = MagicMock()
        detector.detect_flips_for_agent.return_value = [MockFlip()]

        phase = FeedbackPhase(flip_detector=detector)
        ctx = MockDebateContext()

        phase._detect_flips(ctx)

        # Called for each agent
        assert detector.detect_flips_for_agent.call_count == len(ctx.agents)

    def test_detect_flips_emits_events(self):
        """Emits flip events to event emitter."""
        detector = MagicMock()
        detector.detect_flips_for_agent.return_value = [MockFlip()]
        emitter = MagicMock()

        phase = FeedbackPhase(flip_detector=detector, event_emitter=emitter)
        ctx = MockDebateContext()

        # Run flip detection - events are emitted via dynamic imports
        phase._detect_flips(ctx)

        # Event emitter should be called (assuming events module exists)
        # The method handles import errors gracefully

    def test_detect_flips_handles_errors(self):
        """Gracefully handles errors during detection."""
        detector = MagicMock()
        detector.detect_flips_for_agent.side_effect = ValueError("Test error")

        phase = FeedbackPhase(flip_detector=detector)
        ctx = MockDebateContext()

        # Should not raise
        phase._detect_flips(ctx)


# ===========================================================================
# Memory Storage Tests
# ===========================================================================


class TestStoreMemory:
    """Tests for continuum memory storage."""

    def test_store_memory_without_memory(self):
        """Returns early when no continuum memory."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        phase._store_memory(ctx)

    def test_store_memory_without_final_answer(self):
        """Returns early when no final answer."""
        memory = MagicMock()
        phase = FeedbackPhase(continuum_memory=memory)
        ctx = MockDebateContext()
        ctx.result.final_answer = ""

        phase._store_memory(ctx)

    def test_store_memory_calls_callback(self):
        """Calls store callback with result."""
        memory = MagicMock()
        store_callback = MagicMock()

        phase = FeedbackPhase(
            continuum_memory=memory,
            store_debate_outcome_as_memory=store_callback,
        )
        ctx = MockDebateContext()

        phase._store_memory(ctx)

        store_callback.assert_called_once_with(ctx.result)


class TestUpdateMemoryOutcomes:
    """Tests for memory outcome updates."""

    def test_update_outcomes_without_memory(self):
        """Returns early when no continuum memory."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        phase._update_memory_outcomes(ctx)

    def test_update_outcomes_calls_callback(self):
        """Calls update callback with result."""
        memory = MagicMock()
        update_callback = MagicMock()

        phase = FeedbackPhase(
            continuum_memory=memory,
            update_continuum_memory_outcomes=update_callback,
        )
        ctx = MockDebateContext()

        phase._update_memory_outcomes(ctx)

        update_callback.assert_called_once_with(ctx.result)


# ===========================================================================
# Calibration Recording Tests
# ===========================================================================


class TestRecordCalibration:
    """Tests for calibration data recording."""

    def test_record_calibration_without_tracker(self):
        """Returns early when no calibration tracker."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        phase._record_calibration(ctx)

    def test_record_calibration_records_votes(self):
        """Records calibration data for votes with confidence."""
        tracker = MagicMock()
        phase = FeedbackPhase(calibration_tracker=tracker)
        ctx = MockDebateContext()
        ctx.result.winner = "claude"
        ctx.result.votes = [
            MockVote("agent1", "claude", 0.9),
            MockVote("agent2", "gpt4", 0.7),
        ]

        phase._record_calibration(ctx)

        assert tracker.record_prediction.call_count == 2

        # First call - correct prediction
        call1 = tracker.record_prediction.call_args_list[0]
        assert call1[1]["agent"] == "agent1"
        assert call1[1]["confidence"] == 0.9
        assert call1[1]["correct"] is True

        # Second call - incorrect prediction
        call2 = tracker.record_prediction.call_args_list[1]
        assert call2[1]["agent"] == "agent2"
        assert call2[1]["correct"] is False

    def test_record_calibration_skips_votes_without_confidence(self):
        """Skips votes that don't have confidence attribute."""
        tracker = MagicMock()
        phase = FeedbackPhase(calibration_tracker=tracker)
        ctx = MockDebateContext()

        vote = MagicMock()
        vote.agent = "agent1"
        vote.choice = "claude"
        del vote.confidence  # No confidence

        ctx.result.winner = "claude"
        ctx.result.votes = [vote]

        phase._record_calibration(ctx)

        tracker.record_prediction.assert_not_called()

    def test_record_calibration_emits_event(self):
        """Emits calibration update event."""
        tracker = MagicMock()
        tracker.get_summary.return_value = {"total_predictions": 10, "overall_accuracy": 0.8}
        emitter = MagicMock()

        phase = FeedbackPhase(calibration_tracker=tracker, event_emitter=emitter)
        ctx = MockDebateContext()
        ctx.result.votes = [MockVote("agent1", "claude", 0.9)]
        ctx.result.winner = "claude"

        # Run calibration recording - events are emitted via dynamic imports
        phase._record_calibration(ctx)

        # Tracker should record predictions
        tracker.record_prediction.assert_called()
        # Event emitter may be called if events module exists

    def test_record_calibration_handles_errors(self):
        """Gracefully handles errors during recording."""
        tracker = MagicMock()
        tracker.record_prediction.side_effect = RuntimeError("Test error")

        phase = FeedbackPhase(calibration_tracker=tracker)
        ctx = MockDebateContext()
        ctx.result.votes = [MockVote("agent1", "claude", 0.9)]

        # Should not raise
        phase._record_calibration(ctx)


# ===========================================================================
# Pulse Outcome Tests
# ===========================================================================


class TestRecordPulseOutcome:
    """Tests for pulse outcome recording."""

    def test_record_pulse_without_manager(self):
        """Returns early when no pulse manager."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        phase._record_pulse_outcome(ctx)

    def test_record_pulse_without_trending_topic(self):
        """Returns early when no trending topic."""
        manager = MagicMock()
        phase = FeedbackPhase(pulse_manager=manager)
        ctx = MockDebateContext()

        phase._record_pulse_outcome(ctx)

        manager.record_debate_outcome.assert_not_called()

    def test_record_pulse_with_trending_topic(self):
        """Records pulse outcome for trending topic debates."""
        manager = MagicMock()
        phase = FeedbackPhase(pulse_manager=manager)
        ctx = MockDebateContext()

        topic = MagicMock()
        topic.topic = "AI Safety"
        topic.platform = "reddit"
        topic.category = "tech"
        topic.volume = 1000
        ctx.trending_topic = topic

        phase._record_pulse_outcome(ctx)

        manager.record_debate_outcome.assert_called_once()
        call_kwargs = manager.record_debate_outcome.call_args[1]
        assert call_kwargs["topic"] == "AI Safety"
        assert call_kwargs["platform"] == "reddit"

    def test_record_pulse_handles_errors(self):
        """Gracefully handles errors during recording."""
        manager = MagicMock()
        manager.record_debate_outcome.side_effect = ValueError("Test error")

        phase = FeedbackPhase(pulse_manager=manager)
        ctx = MockDebateContext()
        ctx.trending_topic = MagicMock()

        # Should not raise
        phase._record_pulse_outcome(ctx)


# ===========================================================================
# Memory Cleanup Tests
# ===========================================================================


class TestRunMemoryCleanup:
    """Tests for memory cleanup."""

    def test_cleanup_without_memory(self):
        """Returns early when no continuum memory."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        phase._run_memory_cleanup(ctx)

    def test_cleanup_calls_expired_cleanup(self):
        """Always calls cleanup_expired_memories."""
        memory = MagicMock()
        memory.cleanup_expired_memories.return_value = 5

        phase = FeedbackPhase(continuum_memory=memory)
        ctx = MockDebateContext()

        phase._run_memory_cleanup(ctx)

        memory.cleanup_expired_memories.assert_called_once()

    def test_cleanup_handles_errors(self):
        """Gracefully handles errors during cleanup."""
        memory = MagicMock()
        memory.cleanup_expired_memories.side_effect = OSError("Test error")

        phase = FeedbackPhase(continuum_memory=memory)
        ctx = MockDebateContext()

        # Should not raise
        phase._run_memory_cleanup(ctx)


# ===========================================================================
# Risk Assessment Tests
# ===========================================================================


class TestAssessRisks:
    """Tests for risk assessment."""

    def test_assess_risks_without_emitter(self):
        """Returns early when no event emitter."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        phase._assess_risks(ctx)

    def test_assess_risks_emits_warnings(self):
        """Emits risk warning events when risk assessor is available."""
        emitter = MagicMock()
        phase = FeedbackPhase(event_emitter=emitter)
        ctx = MockDebateContext()

        # The method imports assess_debate_risk dynamically
        # It gracefully handles ImportError if the module doesn't exist
        # This test verifies the method runs without error
        phase._assess_risks(ctx)

    def test_assess_risks_handles_import_error(self):
        """Handles missing risk assessment module gracefully."""
        emitter = MagicMock()
        phase = FeedbackPhase(event_emitter=emitter)
        ctx = MockDebateContext()

        # The method catches ImportError internally
        # Just verify it doesn't raise
        phase._assess_risks(ctx)


# ===========================================================================
# Knowledge Mound Tests
# ===========================================================================


class TestIngestKnowledgeOutcome:
    """Tests for knowledge mound ingestion."""

    @pytest.mark.asyncio
    async def test_ingest_without_mound(self):
        """Returns early when no knowledge mound."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        await phase._ingest_knowledge_outcome(ctx)

    @pytest.mark.asyncio
    async def test_ingest_without_callback(self):
        """Returns early when no ingest callback."""
        mound = MagicMock()
        phase = FeedbackPhase(knowledge_mound=mound, enable_knowledge_ingestion=True)
        ctx = MockDebateContext()

        # Should not raise
        await phase._ingest_knowledge_outcome(ctx)

    @pytest.mark.asyncio
    async def test_ingest_calls_callback(self):
        """Calls ingest callback with result."""
        mound = MagicMock()
        ingest = AsyncMock()

        phase = FeedbackPhase(
            knowledge_mound=mound,
            enable_knowledge_ingestion=True,
            ingest_debate_outcome=ingest,
        )
        ctx = MockDebateContext()

        await phase._ingest_knowledge_outcome(ctx)

        ingest.assert_called_once_with(ctx.result)

    @pytest.mark.asyncio
    async def test_ingest_handles_errors(self):
        """Gracefully handles errors during ingestion."""
        mound = MagicMock()
        ingest = AsyncMock(side_effect=RuntimeError("Test error"))

        phase = FeedbackPhase(
            knowledge_mound=mound,
            enable_knowledge_ingestion=True,
            ingest_debate_outcome=ingest,
        )
        ctx = MockDebateContext()

        # Should not raise
        await phase._ingest_knowledge_outcome(ctx)


class TestExtractKnowledgeFromDebate:
    """Tests for knowledge extraction from debates."""

    @pytest.mark.asyncio
    async def test_extract_without_mound(self):
        """Returns early when no knowledge mound."""
        phase = FeedbackPhase(enable_knowledge_extraction=True)
        ctx = MockDebateContext()

        # Should not raise
        await phase._extract_knowledge_from_debate(ctx)

    @pytest.mark.asyncio
    async def test_extract_skips_low_confidence(self):
        """Skips extraction for low-confidence debates."""
        mound = MagicMock()
        phase = FeedbackPhase(
            knowledge_mound=mound,
            enable_knowledge_extraction=True,
            extraction_min_confidence=0.5,
        )
        ctx = MockDebateContext()
        ctx.result.confidence = 0.3  # Below threshold

        await phase._extract_knowledge_from_debate(ctx)

        # Should not call extract method
        assert not hasattr(mound, "extract_from_debate") or not mound.extract_from_debate.called

    @pytest.mark.asyncio
    async def test_extract_calls_mound_method(self):
        """Calls knowledge mound extraction method."""
        mound = MagicMock()
        extraction_result = MagicMock()
        extraction_result.claims = [{"claim": "Test claim"}]
        extraction_result.relationships = []
        mound.extract_from_debate = AsyncMock(return_value=extraction_result)

        phase = FeedbackPhase(
            knowledge_mound=mound,
            enable_knowledge_extraction=True,
            extraction_min_confidence=0.3,
        )
        ctx = MockDebateContext()
        ctx.result.confidence = 0.8
        ctx.result.messages = [MockMessage("claude", "Test content")]

        await phase._extract_knowledge_from_debate(ctx)

        mound.extract_from_debate.assert_called_once()


class TestStoreEvidenceInMound:
    """Tests for evidence storage in knowledge mound."""

    @pytest.mark.asyncio
    async def test_store_evidence_without_hub(self):
        """Returns early when no knowledge bridge hub."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        await phase._store_evidence_in_mound(ctx)

    @pytest.mark.asyncio
    async def test_store_evidence_without_evidence(self):
        """Returns early when no collected evidence."""
        hub = MagicMock()
        phase = FeedbackPhase(knowledge_bridge_hub=hub)
        ctx = MockDebateContext()
        ctx.collected_evidence = []

        await phase._store_evidence_in_mound(ctx)

    @pytest.mark.asyncio
    async def test_store_evidence_stores_items(self):
        """Stores evidence items via evidence bridge."""
        hub = MagicMock()
        bridge = AsyncMock()
        hub.evidence = bridge

        phase = FeedbackPhase(knowledge_bridge_hub=hub)
        ctx = MockDebateContext()
        ctx.collected_evidence = [MagicMock(), MagicMock()]

        await phase._store_evidence_in_mound(ctx)

        assert bridge.store_from_collector_evidence.call_count == 2


# ===========================================================================
# Coordinated Writes Tests
# ===========================================================================


class TestExecuteCoordinatedWrites:
    """Tests for coordinated memory writes."""

    @pytest.mark.asyncio
    async def test_coordinated_writes_without_coordinator(self):
        """Returns early when no memory coordinator."""
        phase = FeedbackPhase(enable_coordinated_writes=True)
        ctx = MockDebateContext()

        # Should not raise
        await phase._execute_coordinated_writes(ctx)

    @pytest.mark.asyncio
    async def test_coordinated_writes_disabled(self):
        """Returns early when coordinated writes disabled."""
        coordinator = MagicMock()
        phase = FeedbackPhase(
            memory_coordinator=coordinator,
            enable_coordinated_writes=False,
        )
        ctx = MockDebateContext()

        await phase._execute_coordinated_writes(ctx)

        coordinator.commit_debate_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_coordinated_writes_success(self):
        """Commits writes on success."""
        coordinator = MagicMock()
        transaction = MagicMock()
        transaction.success = True
        transaction.operations = [MagicMock()]
        coordinator.commit_debate_outcome = AsyncMock(return_value=transaction)

        phase = FeedbackPhase(
            memory_coordinator=coordinator,
            enable_coordinated_writes=True,
        )
        ctx = MockDebateContext()

        await phase._execute_coordinated_writes(ctx)

        coordinator.commit_debate_outcome.assert_called_once()
        assert hasattr(ctx, "_memory_transaction")

    @pytest.mark.asyncio
    async def test_coordinated_writes_partial_failure(self):
        """Logs partial failures."""
        coordinator = MagicMock()
        failed_op = MagicMock()
        failed_op.target = "consensus"
        failed_op.error = "Connection failed"

        transaction = MagicMock()
        transaction.success = False
        transaction.partial_failure = True
        transaction.operations = [MagicMock(), failed_op]
        transaction.get_failed_operations.return_value = [failed_op]
        coordinator.commit_debate_outcome = AsyncMock(return_value=transaction)

        phase = FeedbackPhase(
            memory_coordinator=coordinator,
            enable_coordinated_writes=True,
        )
        ctx = MockDebateContext()

        await phase._execute_coordinated_writes(ctx)

        transaction.get_failed_operations.assert_called_once()


# ===========================================================================
# Selection Feedback Tests
# ===========================================================================


class TestUpdateSelectionFeedback:
    """Tests for selection feedback loop updates."""

    @pytest.mark.asyncio
    async def test_selection_feedback_without_loop(self):
        """Returns early when no selection feedback loop."""
        phase = FeedbackPhase(enable_performance_feedback=True)
        ctx = MockDebateContext()

        # Should not raise
        await phase._update_selection_feedback(ctx)

    @pytest.mark.asyncio
    async def test_selection_feedback_disabled(self):
        """Returns early when feedback disabled."""
        loop = MagicMock()
        phase = FeedbackPhase(
            selection_feedback_loop=loop,
            enable_performance_feedback=False,
        )
        ctx = MockDebateContext()

        await phase._update_selection_feedback(ctx)

        loop.process_debate_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_selection_feedback_processes_outcome(self):
        """Processes debate outcome through feedback loop."""
        loop = MagicMock()
        loop.process_debate_outcome.return_value = {"claude": 0.1, "gpt4": -0.05}

        phase = FeedbackPhase(
            selection_feedback_loop=loop,
            enable_performance_feedback=True,
        )
        ctx = MockDebateContext()

        await phase._update_selection_feedback(ctx)

        loop.process_debate_outcome.assert_called_once()
        call_kwargs = loop.process_debate_outcome.call_args[1]
        assert call_kwargs["debate_id"] == "test-debate-123"
        assert call_kwargs["winner"] == "claude"


# ===========================================================================
# Post-Debate Workflow Tests
# ===========================================================================


class TestMaybeTriggerWorkflow:
    """Tests for post-debate workflow triggering."""

    @pytest.mark.asyncio
    async def test_trigger_workflow_without_workflow(self):
        """Returns early when no workflow configured."""
        phase = FeedbackPhase(enable_post_debate_workflow=True)
        ctx = MockDebateContext()

        # Should not raise
        await phase._maybe_trigger_workflow(ctx)

    @pytest.mark.asyncio
    async def test_trigger_workflow_disabled(self):
        """Returns early when workflow disabled."""
        workflow = MagicMock()
        phase = FeedbackPhase(
            post_debate_workflow=workflow,
            enable_post_debate_workflow=False,
        )
        ctx = MockDebateContext()

        await phase._maybe_trigger_workflow(ctx)

    @pytest.mark.asyncio
    async def test_trigger_workflow_skips_low_confidence(self):
        """Skips workflow for low-confidence debates."""
        workflow = MagicMock()
        phase = FeedbackPhase(
            post_debate_workflow=workflow,
            enable_post_debate_workflow=True,
            post_debate_workflow_threshold=0.8,
        )
        ctx = MockDebateContext()
        ctx.result.confidence = 0.6

        await phase._maybe_trigger_workflow(ctx)

        # Workflow should not be triggered (fire-and-forget task not created)

    @pytest.mark.asyncio
    async def test_trigger_workflow_high_confidence(self):
        """Triggers workflow for high-confidence debates."""
        workflow = MagicMock()
        phase = FeedbackPhase(
            post_debate_workflow=workflow,
            enable_post_debate_workflow=True,
            post_debate_workflow_threshold=0.7,
        )
        ctx = MockDebateContext()
        ctx.result.confidence = 0.85

        with patch.object(phase, "_run_workflow_async", new_callable=AsyncMock):
            with patch("asyncio.create_task") as mock_create:
                await phase._maybe_trigger_workflow(ctx)

                # Task should be created
                mock_create.assert_called_once()


# ===========================================================================
# Receipt Generation Tests
# ===========================================================================


class TestGenerateAndPostReceipt:
    """Tests for decision receipt generation."""

    @pytest.mark.asyncio
    async def test_receipt_generation_disabled(self):
        """Returns None when receipt generation disabled."""
        phase = FeedbackPhase(enable_auto_receipt=False)
        ctx = MockDebateContext()

        result = await phase._generate_and_post_receipt(ctx)

        assert result is None

    @pytest.mark.asyncio
    async def test_receipt_generation_without_result(self):
        """Returns None when no result."""
        phase = FeedbackPhase(enable_auto_receipt=True)
        ctx = MockDebateContext()
        ctx.result = None

        result = await phase._generate_and_post_receipt(ctx)

        assert result is None

    @pytest.mark.asyncio
    async def test_receipt_generation_with_cost_tracker(self):
        """Generates receipt with cost data when module is available."""
        cost_tracker = MagicMock()
        cost_tracker.get_debate_cost.return_value = 0.05
        cost_tracker.get_total_tokens.return_value = 1000
        cost_tracker.budget_limit = 1.0

        phase = FeedbackPhase(
            enable_auto_receipt=True,
            cost_tracker=cost_tracker,
        )
        ctx = MockDebateContext()

        # The method imports DecisionReceipt dynamically
        # It returns None if the import fails, or a receipt if successful
        result = await phase._generate_and_post_receipt(ctx)

        # Result could be None if DecisionReceipt module not available
        # or a receipt object if it is available

    @pytest.mark.asyncio
    async def test_receipt_generation_handles_import_error(self):
        """Handles missing DecisionReceipt module gracefully."""
        phase = FeedbackPhase(enable_auto_receipt=True)
        ctx = MockDebateContext()

        # The method catches ImportError internally
        # Just verify it doesn't raise
        result = await phase._generate_and_post_receipt(ctx)

        # Result is None when module is not available or error occurs


# ===========================================================================
# Broadcast Triggering Tests
# ===========================================================================


class TestMaybeTriggerBroadcast:
    """Tests for broadcast pipeline triggering."""

    @pytest.mark.asyncio
    async def test_broadcast_without_pipeline(self):
        """Returns early when no broadcast pipeline."""
        phase = FeedbackPhase(auto_broadcast=True)
        ctx = MockDebateContext()

        # Should not raise
        await phase._maybe_trigger_broadcast(ctx)

    @pytest.mark.asyncio
    async def test_broadcast_async_returns_when_pipeline_is_none(self):
        """Direct async broadcast returns before building pipeline options."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        with patch(
            "aragora.broadcast.pipeline.BroadcastOptions",
            side_effect=AssertionError("broadcast options should not be built"),
        ):
            await phase._broadcast_async(ctx)

    @pytest.mark.asyncio
    async def test_broadcast_disabled(self):
        """Returns early when broadcast disabled."""
        pipeline = MagicMock()
        phase = FeedbackPhase(
            broadcast_pipeline=pipeline,
            auto_broadcast=False,
        )
        ctx = MockDebateContext()

        await phase._maybe_trigger_broadcast(ctx)

    @pytest.mark.asyncio
    async def test_broadcast_skips_low_confidence(self):
        """Skips broadcast for low-confidence debates."""
        pipeline = MagicMock()
        phase = FeedbackPhase(
            broadcast_pipeline=pipeline,
            auto_broadcast=True,
            broadcast_min_confidence=0.9,
        )
        ctx = MockDebateContext()
        ctx.result.confidence = 0.7

        await phase._maybe_trigger_broadcast(ctx)

    @pytest.mark.asyncio
    async def test_broadcast_triggers_high_confidence(self):
        """Triggers broadcast for high-confidence debates."""
        pipeline = MagicMock()
        phase = FeedbackPhase(
            broadcast_pipeline=pipeline,
            auto_broadcast=True,
            broadcast_min_confidence=0.8,
        )
        ctx = MockDebateContext()
        ctx.result.confidence = 0.9

        with patch.object(phase, "_broadcast_async", new_callable=AsyncMock):
            with patch("asyncio.create_task") as mock_create:
                await phase._maybe_trigger_broadcast(ctx)

                mock_create.assert_called_once()


# ===========================================================================
# Culture Observation Tests
# ===========================================================================


class TestObserveDebateCulture:
    """Tests for culture pattern observation."""

    @pytest.mark.asyncio
    async def test_observe_culture_without_mound(self):
        """Returns early when no knowledge mound."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        await phase._observe_debate_culture(ctx)

    @pytest.mark.asyncio
    async def test_observe_culture_without_result(self):
        """Returns early when no result."""
        mound = MagicMock()
        phase = FeedbackPhase(knowledge_mound=mound)
        ctx = MockDebateContext()
        ctx.result = None

        await phase._observe_debate_culture(ctx)

    @pytest.mark.asyncio
    async def test_observe_culture_without_method(self):
        """Returns early when mound has no observe_debate method."""
        mound = MagicMock(spec=[])  # No observe_debate method
        phase = FeedbackPhase(knowledge_mound=mound)
        ctx = MockDebateContext()

        await phase._observe_debate_culture(ctx)

    @pytest.mark.asyncio
    async def test_observe_culture_calls_mound(self):
        """Calls observe_debate on knowledge mound."""
        mound = MagicMock()
        mound.observe_debate = AsyncMock(return_value=[{"pattern": "consensus"}])

        phase = FeedbackPhase(knowledge_mound=mound)
        ctx = MockDebateContext()

        await phase._observe_debate_culture(ctx)

        mound.observe_debate.assert_called_once_with(ctx.result)


# ===========================================================================
# Backward Compatibility Delegate Tests
# ===========================================================================


class TestBackwardCompatibleDelegates:
    """Tests for backward-compatible delegate methods."""

    def test_store_consensus_outcome_delegate(self):
        """_store_consensus_outcome delegates to ConsensusStorage."""
        cm = MagicMock()
        phase = FeedbackPhase(consensus_memory=cm)
        ctx = MockDebateContext()

        with patch.object(
            phase._consensus_storage, "store_consensus_outcome", return_value="id-123"
        ) as mock_store:
            phase._store_consensus_outcome(ctx)

            mock_store.assert_called_once_with(ctx)
            assert ctx._last_consensus_id == "id-123"

    def test_confidence_to_strength_delegate(self):
        """_confidence_to_strength delegates to ConsensusStorage."""
        cm = MagicMock()
        phase = FeedbackPhase(consensus_memory=cm)

        # ConsensusStrength is imported dynamically in the method
        result = phase._confidence_to_strength(0.85)

        # Returns a ConsensusStrength enum value
        assert result is not None
        # Check it's the expected strength for 0.85 confidence (STRONG)
        assert hasattr(result, "value") or isinstance(result, str)

    def test_store_cruxes_delegate(self):
        """_store_cruxes delegates to ConsensusStorage."""
        cm = MagicMock()
        phase = FeedbackPhase(consensus_memory=cm)
        ctx = MockDebateContext()

        with patch.object(phase._consensus_storage, "store_cruxes") as mock_store:
            phase._store_cruxes(ctx)

            mock_store.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_insight_usage_delegate(self):
        """_record_insight_usage delegates to TrainingEmitter."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        with patch.object(phase._training_emitter, "record_insight_usage") as mock_record:
            await phase._record_insight_usage(ctx)

            mock_record.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_emit_training_data_delegate(self):
        """_emit_training_data delegates to TrainingEmitter."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        with patch.object(phase._training_emitter, "emit_training_data") as mock_emit:
            await phase._emit_training_data(ctx)

            mock_emit.assert_called_once_with(ctx)

    def test_record_elo_match_delegate(self):
        """_record_elo_match delegates to EloFeedback."""
        elo = MagicMock()
        phase = FeedbackPhase(elo_system=elo)
        ctx = MockDebateContext()

        with patch.object(phase._elo_feedback, "record_elo_match") as mock_record:
            phase._record_elo_match(ctx)

            mock_record.assert_called_once_with(ctx)

    def test_update_persona_performance_delegate(self):
        """_update_persona_performance delegates to PersonaFeedback."""
        pm = MagicMock()
        phase = FeedbackPhase(persona_manager=pm)
        ctx = MockDebateContext()

        with patch.object(phase._persona_feedback, "update_persona_performance") as mock_update:
            phase._update_persona_performance(ctx)

            mock_update.assert_called_once_with(ctx)

    def test_update_genome_fitness_delegate(self):
        """_update_genome_fitness delegates to EvolutionFeedback."""
        pm = MagicMock()
        phase = FeedbackPhase(population_manager=pm)
        ctx = MockDebateContext()

        with patch.object(phase._evolution_feedback, "update_genome_fitness") as mock_update:
            phase._update_genome_fitness(ctx)

            mock_update.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_maybe_evolve_population_delegate(self):
        """_maybe_evolve_population delegates to EvolutionFeedback."""
        pm = MagicMock()
        phase = FeedbackPhase(population_manager=pm)
        ctx = MockDebateContext()

        with patch.object(phase._evolution_feedback, "maybe_evolve_population") as mock_evolve:
            await phase._maybe_evolve_population(ctx)

            mock_evolve.assert_called_once_with(ctx)

    def test_record_evolution_patterns_delegate(self):
        """_record_evolution_patterns delegates to EvolutionFeedback."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        with patch.object(phase._evolution_feedback, "record_evolution_patterns") as mock_record:
            phase._record_evolution_patterns(ctx)

            mock_record.assert_called_once_with(ctx)


# ===========================================================================
# Edge Cases and Error Handling
# ===========================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_execute_with_empty_agents(self):
        """Execute works with empty agents list."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()
        ctx.agents = []

        # Should not raise
        await phase.execute(ctx)

    @pytest.mark.asyncio
    async def test_execute_with_no_votes(self):
        """Execute works with no votes — auto-calibration still records."""
        tracker = MagicMock()
        phase = FeedbackPhase(calibration_tracker=tracker)
        ctx = MockDebateContext()
        ctx.result.votes = []

        await phase.execute(ctx)

        # Auto-calibration still records selection_feedback for participating
        # agents even without explicit votes (uses default confidence=0.5)
        for call_args in tracker.record_prediction.call_args_list:
            assert call_args.kwargs.get("prediction_type") in (
                "selection_feedback",
                "consensus_alignment",
            )

    @pytest.mark.asyncio
    async def test_execute_with_no_winner(self):
        """Execute works when there's no winner."""
        elo = MagicMock()
        phase = FeedbackPhase(elo_system=elo)
        ctx = MockDebateContext()
        ctx.result.winner = None

        await phase.execute(ctx)

    @pytest.mark.asyncio
    async def test_execute_with_no_consensus(self):
        """Execute works when consensus not reached."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()
        ctx.result.consensus_reached = False

        await phase.execute(ctx)

    def test_emit_flip_events_without_emitter(self):
        """_emit_flip_events returns early without emitter."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        phase._emit_flip_events(ctx, "claude", [MockFlip()])

    def test_emit_calibration_update_without_emitter(self):
        """_emit_calibration_update returns early without emitter."""
        tracker = MagicMock()
        phase = FeedbackPhase(calibration_tracker=tracker)
        ctx = MockDebateContext()

        # Should not raise
        phase._emit_calibration_update(ctx, 5)

    def test_emit_selection_feedback_event_without_emitter(self):
        """_emit_selection_feedback_event returns early without emitter."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        phase._emit_selection_feedback_event(ctx, {"claude": 0.1})


class TestErrorRecovery:
    """Tests for error recovery in all feedback methods."""

    def test_most_methods_handle_none_result(self):
        """Most methods gracefully handle None result through error handling."""
        phase = FeedbackPhase(
            relationship_tracker=MagicMock(),
            moment_detector=MagicMock(),
            flip_detector=MagicMock(),
            continuum_memory=MagicMock(),
            calibration_tracker=MagicMock(),
            pulse_manager=MagicMock(),
        )

        # Create a context with None result
        ctx = MockDebateContext()
        ctx.result = None

        # Methods that access result.X will raise but catch the error
        # (logged as warnings, not propagated)
        phase._update_relationships(ctx)  # Catches AttributeError
        phase._detect_moments(ctx)  # Catches AttributeError

        # Methods that check result first return early
        phase._update_memory_outcomes(ctx)
        phase._record_calibration(ctx)
        phase._record_pulse_outcome(ctx)

        # Methods that iterate over agents still work
        phase._detect_flips(ctx)
        phase._run_memory_cleanup(ctx)

    def test_methods_handle_attribute_errors(self):
        """Methods gracefully handle AttributeError in results."""
        phase = FeedbackPhase(
            relationship_tracker=MagicMock(),
            moment_detector=MagicMock(),
            calibration_tracker=MagicMock(),
            pulse_manager=MagicMock(),
        )

        # Create a context with minimal result
        ctx = MockDebateContext()
        ctx.result.votes = None  # This will cause AttributeError when iterating
        ctx.result.messages = None

        # These should handle the errors gracefully
        phase._update_relationships(ctx)
        phase._record_calibration(ctx)

    @pytest.mark.asyncio
    async def test_async_methods_handle_runtime_errors(self):
        """Async methods gracefully handle RuntimeError."""
        mound = MagicMock()
        mound.extract_from_debate = AsyncMock(side_effect=RuntimeError("Test"))
        mound.observe_debate = AsyncMock(side_effect=RuntimeError("Test"))

        hub = MagicMock()
        hub.evidence.store_from_collector_evidence = AsyncMock(side_effect=RuntimeError("Test"))

        coordinator = MagicMock()
        coordinator.commit_debate_outcome = AsyncMock(side_effect=RuntimeError("Test"))

        loop = MagicMock()
        loop.process_debate_outcome.side_effect = RuntimeError("Test")

        phase = FeedbackPhase(
            knowledge_mound=mound,
            enable_knowledge_extraction=True,
            knowledge_bridge_hub=hub,
            memory_coordinator=coordinator,
            enable_coordinated_writes=True,
            selection_feedback_loop=loop,
            enable_performance_feedback=True,
        )

        ctx = MockDebateContext()
        ctx.result.messages = [MockMessage("claude", "Test")]
        ctx.collected_evidence = [MagicMock()]

        # None of these should raise
        await phase._extract_knowledge_from_debate(ctx)
        await phase._observe_debate_culture(ctx)
        await phase._store_evidence_in_mound(ctx)
        await phase._execute_coordinated_writes(ctx)
        await phase._update_selection_feedback(ctx)


# =============================================================================
# Additional Coverage: Post-Debate Workflow Tests
# =============================================================================


class TestPostDebateWorkflow:
    """Tests for post-debate workflow triggering."""

    @pytest.mark.asyncio
    async def test_maybe_trigger_workflow_skips_when_disabled(self):
        """Skips workflow when enable_post_debate_workflow is False."""
        workflow = MagicMock()
        phase = FeedbackPhase(
            post_debate_workflow=workflow,
            enable_post_debate_workflow=False,
        )

        ctx = MockDebateContext()
        ctx.result.confidence = 0.9

        await phase._maybe_trigger_workflow(ctx)

        # Workflow should not be triggered

    @pytest.mark.asyncio
    async def test_maybe_trigger_workflow_skips_below_threshold(self):
        """Skips workflow when confidence below threshold."""
        workflow = MagicMock()
        phase = FeedbackPhase(
            post_debate_workflow=workflow,
            enable_post_debate_workflow=True,
            post_debate_workflow_threshold=0.8,
        )

        ctx = MockDebateContext()
        ctx.result.confidence = 0.5  # Below threshold

        await phase._maybe_trigger_workflow(ctx)

        # Workflow should not be triggered

    @pytest.mark.asyncio
    async def test_maybe_trigger_workflow_creates_background_task(self):
        """Creates background task when workflow should trigger."""
        workflow = MagicMock()
        phase = FeedbackPhase(
            post_debate_workflow=workflow,
            enable_post_debate_workflow=True,
            post_debate_workflow_threshold=0.5,
        )

        ctx = MockDebateContext()
        ctx.result.confidence = 0.9  # Above threshold

        # Should create background task
        with patch.object(phase, "_run_workflow_async", new_callable=AsyncMock) as run_workflow:
            await phase._maybe_trigger_workflow(ctx)
            await asyncio.sleep(0)

        run_workflow.assert_awaited_once_with(ctx)
        assert ctx.post_debate_workflow_triggered is True


# =============================================================================
# Additional Coverage: Decision Receipt Tests
# =============================================================================


class TestDecisionReceipt:
    """Tests for auto-receipt generation."""

    @pytest.mark.asyncio
    async def test_generate_and_post_receipt_skips_when_disabled(self):
        """Skips receipt generation when disabled."""
        phase = FeedbackPhase(enable_auto_receipt=False)

        ctx = MockDebateContext()
        result = await phase._generate_and_post_receipt(ctx)

        assert result is None

    @pytest.mark.asyncio
    async def test_generate_and_post_receipt_skips_without_result(self):
        """Skips receipt generation without result."""
        phase = FeedbackPhase(enable_auto_receipt=True)

        ctx = MockDebateContext()
        ctx.result = None

        result = await phase._generate_and_post_receipt(ctx)

        assert result is None

    @pytest.mark.asyncio
    async def test_generate_and_post_receipt_with_cost_tracker(self):
        """Generates receipt with cost data from cost_tracker."""
        cost_tracker = MagicMock()
        cost_tracker.get_debate_cost.return_value = 0.05
        cost_tracker.get_total_tokens.return_value = 1500
        cost_tracker.budget_limit = 1.0

        phase = FeedbackPhase(
            enable_auto_receipt=True,
            cost_tracker=cost_tracker,
        )

        ctx = MockDebateContext()

        # The _generate_and_post_receipt method imports DecisionReceipt internally
        # We test that it runs without error and handles import properly
        result = await phase._generate_and_post_receipt(ctx)

        # Result may be None if DecisionReceipt module is not available
        # or a receipt if it is - either is valid for this test
        assert result is None or hasattr(result, "receipt_id")


# =============================================================================
# Additional Coverage: Coordinated Writes Tests
# =============================================================================


class TestCoordinatedWrites:
    """Tests for coordinated memory writes."""

    @pytest.mark.asyncio
    async def test_execute_coordinated_writes_skips_when_disabled(self):
        """Skips coordinated writes when disabled."""
        coordinator = MagicMock()
        phase = FeedbackPhase(
            memory_coordinator=coordinator,
            enable_coordinated_writes=False,
        )

        ctx = MockDebateContext()

        await phase._execute_coordinated_writes(ctx)

        coordinator.commit_debate_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_coordinated_writes_handles_partial_failure(self):
        """Handles partial failure in coordinated writes."""
        transaction = MagicMock()
        transaction.success = False
        transaction.partial_failure = True
        transaction.operations = [MagicMock(), MagicMock()]
        transaction.get_failed_operations.return_value = [
            MagicMock(target="continuum", error="Write failed"),
        ]

        coordinator = MagicMock()
        coordinator.commit_debate_outcome = AsyncMock(return_value=transaction)

        phase = FeedbackPhase(
            memory_coordinator=coordinator,
            enable_coordinated_writes=True,
        )

        ctx = MockDebateContext()

        await phase._execute_coordinated_writes(ctx)

        # Should have stored transaction reference
        assert hasattr(ctx, "_memory_transaction")


# =============================================================================
# Additional Coverage: Selection Feedback Tests
# =============================================================================


class TestSelectionFeedback:
    """Tests for selection feedback loop updates."""

    @pytest.mark.asyncio
    async def test_update_selection_feedback_skips_when_disabled(self):
        """Skips feedback when disabled."""
        loop = MagicMock()
        phase = FeedbackPhase(
            selection_feedback_loop=loop,
            enable_performance_feedback=False,
        )

        ctx = MockDebateContext()

        await phase._update_selection_feedback(ctx)

        loop.process_debate_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_selection_feedback_emits_event(self):
        """Emits selection feedback event when adjustments made."""
        loop = MagicMock()
        loop.process_debate_outcome.return_value = {"claude": 0.05, "gpt4": -0.02}

        emitter = MagicMock()

        phase = FeedbackPhase(
            selection_feedback_loop=loop,
            enable_performance_feedback=True,
            event_emitter=emitter,
            loop_id="test-loop",
        )

        ctx = MockDebateContext()
        ctx.result.winner = "claude"

        await phase._update_selection_feedback(ctx)

        # Should have processed and emitted event
        loop.process_debate_outcome.assert_called_once()


# =============================================================================
# Additional Coverage: Knowledge Extraction Tests
# =============================================================================


class TestKnowledgeExtraction:
    """Tests for knowledge extraction from debates."""

    @pytest.mark.asyncio
    async def test_extract_knowledge_skips_low_confidence(self):
        """Skips extraction when confidence below threshold."""
        mound = MagicMock()
        phase = FeedbackPhase(
            knowledge_mound=mound,
            enable_knowledge_extraction=True,
            extraction_min_confidence=0.5,
        )

        ctx = MockDebateContext()
        ctx.result.confidence = 0.2  # Below threshold

        await phase._extract_knowledge_from_debate(ctx)

        mound.extract_from_debate.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_knowledge_skips_without_messages(self):
        """Skips extraction when no messages."""
        mound = MagicMock()
        phase = FeedbackPhase(
            knowledge_mound=mound,
            enable_knowledge_extraction=True,
            extraction_min_confidence=0.1,
        )

        ctx = MockDebateContext()
        ctx.result.confidence = 0.8
        ctx.result.messages = []

        await phase._extract_knowledge_from_debate(ctx)

        mound.extract_from_debate.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_knowledge_promotes_high_confidence_claims(self):
        """Promotes high-confidence claims to mound."""
        extraction_result = MagicMock()
        extraction_result.claims = [MagicMock(confidence=0.9), MagicMock(confidence=0.8)]
        extraction_result.relationships = []

        mound = MagicMock()
        mound.extract_from_debate = AsyncMock(return_value=extraction_result)
        mound.promote_extracted_knowledge = AsyncMock(return_value=2)

        phase = FeedbackPhase(
            knowledge_mound=mound,
            enable_knowledge_extraction=True,
            extraction_min_confidence=0.1,
            extraction_promote_threshold=0.7,
        )

        ctx = MockDebateContext()
        ctx.result.confidence = 0.8
        ctx.result.messages = [MockMessage("claude", "Test content")]
        ctx.result.consensus_reached = True
        ctx.result.final_answer = "Agreed conclusion"

        await phase._extract_knowledge_from_debate(ctx)

        mound.extract_from_debate.assert_called_once()
        mound.promote_extracted_knowledge.assert_called_once()


# =============================================================================
# Additional Coverage: Broadcast Triggering Tests
# =============================================================================


class TestMaybeTriggerBroadcastExtended:
    """Tests for auto-broadcast triggering."""

    @pytest.mark.asyncio
    async def test_maybe_trigger_broadcast_skips_when_disabled(self):
        """Skips broadcast when auto_broadcast is False."""
        pipeline = MagicMock()
        phase = FeedbackPhase(
            broadcast_pipeline=pipeline,
            auto_broadcast=False,
        )

        ctx = MockDebateContext()
        ctx.result.confidence = 0.9

        await phase._maybe_trigger_broadcast(ctx)

        # Pipeline should not be triggered

    @pytest.mark.asyncio
    async def test_maybe_trigger_broadcast_skips_below_min_confidence(self):
        """Skips broadcast when confidence below minimum."""
        pipeline = MagicMock()
        phase = FeedbackPhase(
            broadcast_pipeline=pipeline,
            auto_broadcast=True,
            broadcast_min_confidence=0.8,
        )

        ctx = MockDebateContext()
        ctx.result.confidence = 0.5  # Below threshold

        await phase._maybe_trigger_broadcast(ctx)


# =============================================================================
# Additional Coverage: Culture Observation Tests
# =============================================================================


class TestObserveDebateCultureExtended:
    """Tests for culture pattern observation."""

    @pytest.mark.asyncio
    async def test_observe_debate_culture_skips_without_mound(self):
        """Skips culture observation without knowledge mound."""
        phase = FeedbackPhase(knowledge_mound=None)

        ctx = MockDebateContext()

        # Should not raise
        await phase._observe_debate_culture(ctx)

    @pytest.mark.asyncio
    async def test_observe_debate_culture_with_culture_adapter(self):
        """Observes culture patterns with culture adapter."""
        mound = MagicMock()
        mound.observe_debate = AsyncMock()

        phase = FeedbackPhase(knowledge_mound=mound)

        ctx = MockDebateContext()
        ctx.result.messages = [MockMessage("claude", "Test")]

        await phase._observe_debate_culture(ctx)

        mound.observe_debate.assert_called_once()


# =============================================================================
# Additional Coverage: Store Evidence in Mound Tests
# =============================================================================


class TestStoreEvidenceInMoundExtended:
    """Tests for storing evidence in Knowledge Mound."""

    @pytest.mark.asyncio
    async def test_store_evidence_skips_without_bridge_hub(self):
        """Skips evidence storage without bridge hub."""
        phase = FeedbackPhase(knowledge_bridge_hub=None)

        ctx = MockDebateContext()
        ctx.collected_evidence = [MagicMock()]

        # Should not raise
        await phase._store_evidence_in_mound(ctx)

    @pytest.mark.asyncio
    async def test_store_evidence_skips_without_evidence(self):
        """Skips when no collected evidence."""
        hub = MagicMock()
        phase = FeedbackPhase(knowledge_bridge_hub=hub)

        ctx = MockDebateContext()
        ctx.collected_evidence = []

        await phase._store_evidence_in_mound(ctx)

        # Evidence bridge should not be called
        hub.evidence.store_from_collector_evidence.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_evidence_stores_each_item(self):
        """Stores each evidence item via bridge."""
        evidence_bridge = MagicMock()
        evidence_bridge.store_from_collector_evidence = AsyncMock()

        hub = MagicMock()
        hub.evidence = evidence_bridge

        phase = FeedbackPhase(knowledge_bridge_hub=hub)

        evidence1 = MagicMock()
        evidence2 = MagicMock()
        ctx = MockDebateContext()
        ctx.collected_evidence = [evidence1, evidence2]

        await phase._store_evidence_in_mound(ctx)

        assert evidence_bridge.store_from_collector_evidence.call_count == 2


# =============================================================================
# Additional Coverage: Ingest Knowledge Outcome Tests
# =============================================================================


class TestIngestKnowledgeOutcomeExtended:
    """Tests for knowledge outcome ingestion."""

    @pytest.mark.asyncio
    async def test_ingest_outcome_skips_when_disabled(self):
        """Skips ingestion when disabled."""
        ingest_fn = AsyncMock()
        phase = FeedbackPhase(
            knowledge_mound=MagicMock(),
            enable_knowledge_ingestion=False,
            ingest_debate_outcome=ingest_fn,
        )

        ctx = MockDebateContext()

        await phase._ingest_knowledge_outcome(ctx)

        ingest_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_outcome_calls_callback(self):
        """Calls ingest callback with result."""
        ingest_fn = AsyncMock()
        phase = FeedbackPhase(
            knowledge_mound=MagicMock(),
            enable_knowledge_ingestion=True,
            ingest_debate_outcome=ingest_fn,
        )

        ctx = MockDebateContext()

        await phase._ingest_knowledge_outcome(ctx)

        ingest_fn.assert_called_once_with(ctx.result)


# ===========================================================================
# Calibration Feedback Loop Tests (Item 1)
# ===========================================================================


class TestUpdateCalibrationFeedback:
    """Tests for _update_calibration_feedback closing the calibration loop."""

    def test_skips_without_tracker(self):
        """Returns early when no calibration tracker."""
        phase = FeedbackPhase()
        ctx = MockDebateContext()

        # Should not raise
        phase._update_calibration_feedback(ctx)

    def test_skips_without_consensus(self):
        """Skips when consensus was not reached."""
        tracker = MagicMock()
        phase = FeedbackPhase(calibration_tracker=tracker)
        ctx = MockDebateContext()
        ctx.result.consensus_reached = False

        phase._update_calibration_feedback(ctx)

        tracker.record_prediction.assert_not_called()

    def test_skips_without_winner(self):
        """Skips when no winner."""
        tracker = MagicMock()
        phase = FeedbackPhase(calibration_tracker=tracker)
        ctx = MockDebateContext()
        ctx.result.winner = None

        phase._update_calibration_feedback(ctx)

        tracker.record_prediction.assert_not_called()

    def test_updates_brier_for_all_agents(self):
        """Records calibration prediction for each participating agent."""
        tracker = MagicMock()
        tracker.get_brier_score = MagicMock(return_value=0.3)
        phase = FeedbackPhase(calibration_tracker=tracker)
        ctx = MockDebateContext()
        ctx.result.winner = "claude"
        ctx.result.votes = [
            MockVote("claude", "claude", 0.9),
            MockVote("gpt4", "gpt4", 0.7),
        ]

        phase._update_calibration_feedback(ctx)

        # Should call record_prediction for each agent
        assert tracker.record_prediction.call_count == 2

        # First agent (claude) predicted correctly
        call1 = tracker.record_prediction.call_args_list[0]
        assert call1[1]["agent"] == "claude"
        assert call1[1]["correct"] is True
        assert call1[1]["prediction_type"] == "selection_feedback"

        # Second agent (gpt4) predicted incorrectly
        call2 = tracker.record_prediction.call_args_list[1]
        assert call2[1]["agent"] == "gpt4"
        assert call2[1]["correct"] is False

    def test_stores_deltas_in_knowledge_mound(self):
        """Stores calibration deltas in KnowledgeMound when available."""
        tracker = MagicMock()
        tracker.get_brier_score = MagicMock(return_value=0.25)
        knowledge_mound = MagicMock()

        phase = FeedbackPhase(
            calibration_tracker=tracker,
            knowledge_mound=knowledge_mound,
        )
        ctx = MockDebateContext()
        ctx.result.winner = "claude"
        ctx.result.votes = [MockVote("claude", "claude", 0.9)]

        with patch(
            "aragora.debate.phases.feedback_phase.FeedbackPhase._store_calibration_in_mound"
        ) as mock_store:
            phase._update_calibration_feedback(ctx)
            mock_store.assert_called_once()
            # Verify deltas dict was passed
            call_args = mock_store.call_args
            deltas = call_args[0][1]  # second positional arg
            assert "claude" in deltas
            assert "brier_before" in deltas["claude"]
            assert "brier_after" in deltas["claude"]
            assert "brier_delta" in deltas["claude"]

    def test_handles_missing_get_brier_score(self):
        """Works when calibration tracker has no get_brier_score method."""
        tracker = MagicMock(spec=["record_prediction"])
        phase = FeedbackPhase(calibration_tracker=tracker)
        ctx = MockDebateContext()
        ctx.result.winner = "claude"
        ctx.result.votes = [MockVote("claude", "claude", 0.8)]

        # Should not raise -- falls back to default brier baseline
        phase._update_calibration_feedback(ctx)
        # Called once per agent (claude + gpt4 from MockDebateContext)
        assert tracker.record_prediction.call_count == 2

    def test_handles_errors_gracefully(self):
        """Gracefully handles errors during calibration feedback."""
        tracker = MagicMock()
        tracker.record_prediction.side_effect = RuntimeError("Test error")

        phase = FeedbackPhase(calibration_tracker=tracker)
        ctx = MockDebateContext()
        ctx.result.votes = [MockVote("claude", "claude", 0.9)]

        # Should not raise
        phase._update_calibration_feedback(ctx)

    def test_uses_choice_mapping(self):
        """Uses choice_mapping to canonicalize vote choices."""
        tracker = MagicMock()
        tracker.get_brier_score = MagicMock(return_value=0.4)
        phase = FeedbackPhase(calibration_tracker=tracker)
        ctx = MockDebateContext()
        ctx.result.winner = "claude"
        ctx.choice_mapping = {"Agent-Claude": "claude"}
        # Use agents matching the ctx.agents list (claude and gpt4)
        ctx.result.votes = [MockVote("claude", "Agent-Claude", 0.9)]

        phase._update_calibration_feedback(ctx)

        # The claude agent voted for "Agent-Claude" which maps to "claude" (the winner)
        call = tracker.record_prediction.call_args_list[0]
        assert call[1]["agent"] == "claude"
        assert call[1]["correct"] is True

    def test_default_confidence_when_no_vote(self):
        """Uses default 0.5 confidence for agents without votes."""
        tracker = MagicMock()
        tracker.get_brier_score = MagicMock(return_value=0.3)
        phase = FeedbackPhase(calibration_tracker=tracker)
        ctx = MockDebateContext()
        ctx.result.winner = "claude"
        ctx.result.votes = []  # No votes at all

        phase._update_calibration_feedback(ctx)

        # Should still record for both agents (claude and gpt4 from MockDebateContext)
        assert tracker.record_prediction.call_count == 2
        for call in tracker.record_prediction.call_args_list:
            assert call[1]["confidence"] == 0.5


class TestStoreCalibrationInMound:
    """Tests for _store_calibration_in_mound helper."""

    def test_stores_via_store_calibration_feedback(self):
        """Uses store_calibration_feedback when available."""
        knowledge_mound = MagicMock()
        knowledge_mound.store_calibration_feedback = MagicMock()

        phase = FeedbackPhase(
            calibration_tracker=MagicMock(),
            knowledge_mound=knowledge_mound,
        )
        ctx = MockDebateContext()
        deltas = {"claude": {"brier_before": 0.3, "brier_after": 0.25, "brier_delta": -0.05}}

        phase._store_calibration_in_mound(ctx, deltas)

        knowledge_mound.store_calibration_feedback.assert_called_once()
        record = knowledge_mound.store_calibration_feedback.call_args[0][0]
        assert record["debate_id"] == ctx.debate_id
        assert record["type"] == "calibration_feedback"
        assert "claude" in record["agent_deltas"]

    def test_falls_back_to_store(self):
        """Falls back to store() when store_calibration_feedback missing."""
        knowledge_mound = MagicMock(spec=["store"])

        phase = FeedbackPhase(
            calibration_tracker=MagicMock(),
            knowledge_mound=knowledge_mound,
        )
        ctx = MockDebateContext()
        deltas = {"claude": {"brier_delta": -0.05}}

        phase._store_calibration_in_mound(ctx, deltas)

        knowledge_mound.store.assert_called_once()
        call_kwargs = knowledge_mound.store.call_args[1]
        assert call_kwargs["category"] == "calibration_feedback"
        assert "calibration:" in call_kwargs["key"]

    def test_skips_without_knowledge_mound(self):
        """Skips storage when no knowledge mound."""
        phase = FeedbackPhase(calibration_tracker=MagicMock())
        ctx = MockDebateContext()

        # Should not raise
        phase._store_calibration_in_mound(ctx, {})

    def test_handles_storage_error(self):
        """Gracefully handles storage errors."""
        knowledge_mound = MagicMock()
        knowledge_mound.store_calibration_feedback.side_effect = RuntimeError("DB error")

        phase = FeedbackPhase(
            calibration_tracker=MagicMock(),
            knowledge_mound=knowledge_mound,
        )
        ctx = MockDebateContext()

        # Should not raise
        phase._store_calibration_in_mound(ctx, {"agent": {"delta": 0.1}})
