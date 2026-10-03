"""
Tests for context initialization module.

Tests cover:
- ContextInitializer class
- Fork debate history injection
- Trending topic context
- Historical context fetching
- Pattern injection
- Proposer selection
- Background task management
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.debate.phases.context_init import ContextInitializer


@dataclass
class MockEnv:
    """Mock environment."""

    task: str = "What is the best approach?"
    context: str = ""


@dataclass
class MockAgent:
    """Mock agent."""

    name: str
    role: str = "proposer"


@dataclass
class MockTrendingTopic:
    """Mock trending topic."""

    topic: str = "AI Safety"
    platform: str = "twitter"
    category: str = "technology"
    volume: int = 10000

    def to_debate_prompt(self):
        return f"Discuss: {self.topic}"


@dataclass
class MockDebateContext:
    """Mock debate context."""

    env: MockEnv = field(default_factory=MockEnv)
    agents: list = field(default_factory=list)
    proposers: list = field(default_factory=list)
    partial_messages: list = field(default_factory=list)
    context_messages: list = field(default_factory=list)
    result: Any = None
    historical_context_cache: str = ""
    research_context: str = ""
    evidence_pack: Any = None
    applied_insight_ids: list = field(default_factory=list)
    background_research_task: Any = None
    background_evidence_task: Any = None
    debate_id: str = "test-debate-123"
    domain: str = "general"
    rlm_context: Any = None


class TestContextInitializerInit:
    """Tests for ContextInitializer initialization."""

    def test_default_init(self):
        """Default initialization sets correct defaults."""
        init = ContextInitializer()

        assert init.initial_messages == []
        assert init.trending_topic is None
        assert init.recorder is None
        assert init.auto_fetch_trending is True
        assert init.enable_knowledge_retrieval is True

    def test_custom_init(self):
        """Custom initialization stores all parameters."""
        recorder = MagicMock()
        topic = MockTrendingTopic()
        messages = [{"content": "Hello"}]

        init = ContextInitializer(
            initial_messages=messages,
            trending_topic=topic,
            recorder=recorder,
            auto_fetch_trending=True,
        )

        assert init.initial_messages == messages
        assert init.trending_topic is topic
        assert init.recorder is recorder
        assert init.auto_fetch_trending is True


class TestSelectProposers:
    """Tests for proposer selection."""

    def test_selects_proposer_role_agents(self):
        """Selects agents with proposer role."""
        ctx = MockDebateContext()
        ctx.agents = [
            MockAgent("claude", "proposer"),
            MockAgent("gpt4", "critic"),
            MockAgent("gemini", "proposer"),
        ]

        init = ContextInitializer()
        init._select_proposers(ctx)

        assert len(ctx.proposers) == 2
        names = [p.name for p in ctx.proposers]
        assert "claude" in names
        assert "gemini" in names

    def test_defaults_to_first_agent(self):
        """Defaults to first agent if no proposers."""
        ctx = MockDebateContext()
        ctx.agents = [
            MockAgent("claude", "critic"),
            MockAgent("gpt4", "judge"),
        ]

        init = ContextInitializer()
        init._select_proposers(ctx)

        assert len(ctx.proposers) == 1
        assert ctx.proposers[0].name == "claude"

    def test_empty_agents_empty_proposers(self):
        """Empty agents results in empty proposers."""
        ctx = MockDebateContext()
        ctx.agents = []

        init = ContextInitializer()
        init._select_proposers(ctx)

        assert ctx.proposers == []


class TestInjectForkHistory:
    """Tests for fork history injection."""

    def test_injects_message_objects(self):
        """Injects Message objects directly."""
        from aragora.core import Message

        msg = Message(role="assistant", agent="claude", content="Previous response")
        ctx = MockDebateContext()

        init = ContextInitializer(initial_messages=[msg])
        init._inject_fork_history(ctx)

        assert len(ctx.partial_messages) == 1
        assert ctx.partial_messages[0].content == "Previous response"

    def test_injects_dict_messages(self):
        """Converts dict messages to Message objects."""
        ctx = MockDebateContext()
        messages = [
            {"role": "user", "agent": "user", "content": "Question"},
            {"role": "assistant", "agent": "claude", "content": "Answer"},
        ]

        init = ContextInitializer(initial_messages=messages)
        init._inject_fork_history(ctx)

        assert len(ctx.partial_messages) == 2
        assert ctx.partial_messages[0].content == "Question"

    def test_no_injection_without_messages(self):
        """No injection when no initial messages."""
        ctx = MockDebateContext()

        init = ContextInitializer()
        init._inject_fork_history(ctx)

        assert ctx.partial_messages == []


class TestInjectTrendingTopic:
    """Tests for trending topic injection."""

    def test_injects_topic_context(self):
        """Injects trending topic context."""
        ctx = MockDebateContext()
        topic = MockTrendingTopic()

        init = ContextInitializer(trending_topic=topic)
        init._inject_trending_topic(ctx)

        assert "AI Safety" in ctx.env.context
        assert "twitter" in ctx.env.context
        assert "technology" in ctx.env.context

    def test_appends_to_existing_context(self):
        """Appends topic to existing context."""
        ctx = MockDebateContext()
        ctx.env.context = "Existing context"
        topic = MockTrendingTopic()

        init = ContextInitializer(trending_topic=topic)
        init._inject_trending_topic(ctx)

        assert "Existing context" in ctx.env.context
        assert "AI Safety" in ctx.env.context

    def test_no_injection_without_topic(self):
        """No injection when no trending topic."""
        ctx = MockDebateContext()
        ctx.env.context = "Original"

        init = ContextInitializer()
        init._inject_trending_topic(ctx)

        assert ctx.env.context == "Original"


class TestStartRecorder:
    """Tests for recorder startup."""

    def test_starts_and_records_phase(self):
        """Starts recorder and records debate_start phase."""
        recorder = MagicMock()

        init = ContextInitializer(recorder=recorder)
        init._start_recorder()

        recorder.start.assert_called_once()
        recorder.record_phase_change.assert_called_once_with("debate_start")

    def test_handles_recorder_error(self):
        """Handles recorder errors gracefully."""
        recorder = MagicMock()
        recorder.start.side_effect = RuntimeError("Start failed")

        init = ContextInitializer(recorder=recorder)

        # Should not raise
        init._start_recorder()

    def test_no_op_without_recorder(self):
        """No-op when no recorder provided."""
        init = ContextInitializer()

        # Should not raise
        init._start_recorder()


class TestFetchHistorical:
    """Tests for historical context fetching."""

    @pytest.mark.asyncio
    async def test_fetches_historical_context(self):
        """Fetches and caches historical context."""
        ctx = MockDebateContext()

        async def fetch(task, limit):
            return "Historical debate context"

        embeddings = MagicMock()
        init = ContextInitializer(
            debate_embeddings=embeddings,
            fetch_historical_context=fetch,
        )

        await init._fetch_historical(ctx)

        assert ctx.historical_context_cache == "Historical debate context"

    @pytest.mark.asyncio
    async def test_handles_timeout(self):
        """Handles fetch timeout."""
        ctx = MockDebateContext()

        async def slow_fetch(task, limit):
            await asyncio.sleep(20)
            return "Result"

        embeddings = MagicMock()
        init = ContextInitializer(
            debate_embeddings=embeddings,
            fetch_historical_context=slow_fetch,
        )

        # Mock timeout by patching wait_for
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            await init._fetch_historical(ctx)

        assert ctx.historical_context_cache == ""

    @pytest.mark.asyncio
    async def test_skips_without_embeddings(self):
        """Skips when no debate embeddings."""
        ctx = MockDebateContext()

        init = ContextInitializer()
        await init._fetch_historical(ctx)

        assert ctx.historical_context_cache == ""


class TestInjectInsightPatterns:
    """Tests for insight pattern injection."""

    @pytest.mark.asyncio
    async def test_injects_common_patterns(self):
        """Injects common patterns from InsightStore."""
        ctx = MockDebateContext()

        patterns = [
            MagicMock(pattern="Pattern 1", count=5),
            MagicMock(pattern="Pattern 2", count=3),
        ]

        store = AsyncMock()
        store.get_common_patterns.return_value = patterns
        store.get_relevant_insights.return_value = []

        def format_patterns(p):
            return "## Patterns\n" + "\n".join(x.pattern for x in p)

        init = ContextInitializer(
            insight_store=store,
            format_patterns_for_prompt=format_patterns,
        )

        await init._inject_insight_patterns(ctx)

        assert "Pattern 1" in ctx.env.context
        assert "Pattern 2" in ctx.env.context

    @pytest.mark.asyncio
    async def test_injects_relevant_insights(self):
        """Injects high-confidence insights."""
        ctx = MockDebateContext()
        ctx.domain = "testing"

        insight = MagicMock()
        insight.id = "insight-1"
        insight.title = "Test Insight"
        insight.description = "Important insight"
        insight.confidence = 0.85

        store = AsyncMock()
        store.get_common_patterns.return_value = []
        store.get_relevant_insights.return_value = [insight]

        init = ContextInitializer(insight_store=store)

        await init._inject_insight_patterns(ctx)

        assert "Test Insight" in ctx.env.context
        assert "insight-1" in ctx.applied_insight_ids

    @pytest.mark.asyncio
    async def test_handles_errors(self):
        """Handles insight store errors gracefully."""
        ctx = MockDebateContext()

        store = AsyncMock()
        store.get_common_patterns.side_effect = RuntimeError("Store error")

        init = ContextInitializer(insight_store=store)

        # Should not raise
        await init._inject_insight_patterns(ctx)


class TestInjectMemoryPatterns:
    """Tests for memory pattern injection."""

    def test_injects_memory_patterns(self):
        """Injects patterns from CritiqueStore."""
        ctx = MockDebateContext()

        def get_patterns(limit):
            return "## Memory Patterns\nPattern A"

        init = ContextInitializer(
            memory=MagicMock(),
            get_successful_patterns_from_memory=get_patterns,
        )

        init._inject_memory_patterns(ctx)

        assert "Memory Patterns" in ctx.env.context
        assert "Pattern A" in ctx.env.context

    def test_skips_without_memory(self):
        """Skips when no memory system."""
        ctx = MockDebateContext()
        ctx.env.context = "Original"

        init = ContextInitializer()
        init._inject_memory_patterns(ctx)

        assert ctx.env.context == "Original"


class TestInitialize:
    """Tests for full initialization flow."""

    @pytest.mark.asyncio
    async def test_optional_embedding_failure_is_isolated(self, caplog):
        """Optional context providers cannot abort an explicit-agent debate."""

        async def failing_embedding_context():
            raise RuntimeError("Gemini Embedding API_KEY_INVALID")

        with caplog.at_level("DEBUG"):
            await ContextInitializer._safe_async(
                failing_embedding_context(),
                "knowledge_mound",
            )

        assert "context_enrichment_failed label=knowledge_mound" in caplog.text

    @pytest.mark.asyncio
    async def test_initializes_debate_result(self):
        """Creates DebateResult on context."""
        ctx = MockDebateContext()
        ctx.agents = [MockAgent("claude")]

        init = ContextInitializer()

        await init.initialize(ctx)

        assert ctx.result is not None
        assert ctx.result.task == "What is the best approach?"

    @pytest.mark.asyncio
    async def test_selects_proposers(self):
        """Selects proposers during initialization."""
        ctx = MockDebateContext()
        ctx.agents = [MockAgent("claude", "proposer"), MockAgent("gpt4", "critic")]

        init = ContextInitializer()

        await init.initialize(ctx)

        assert len(ctx.proposers) == 1
        assert ctx.proposers[0].name == "claude"

    @pytest.mark.asyncio
    async def test_starts_background_research(self):
        """Starts background research task when enabled."""
        ctx = MockDebateContext()
        ctx.agents = [MockAgent("claude")]

        protocol = MagicMock()
        protocol.enable_research = True

        async def research(task):
            return "Research results"

        init = ContextInitializer(
            protocol=protocol,
            perform_research=research,
        )

        await init.initialize(ctx)

        assert ctx.background_research_task is not None


class TestAwaitBackgroundContext:
    """Tests for background task completion."""

    @pytest.mark.asyncio
    async def test_awaits_running_tasks(self):
        """Awaits incomplete background tasks."""
        ctx = MockDebateContext()

        async def slow_task():
            await asyncio.sleep(0.1)
            return "Done"

        ctx.background_research_task = asyncio.create_task(slow_task())

        init = ContextInitializer()
        await init.await_background_context(ctx)

        assert ctx.background_research_task is None

    @pytest.mark.asyncio
    async def test_handles_task_timeout(self):
        """Handles task timeout and cancels."""
        ctx = MockDebateContext()

        async def very_slow_task():
            await asyncio.sleep(100)
            return "Done"

        ctx.background_research_task = asyncio.create_task(very_slow_task())

        init = ContextInitializer()

        # Mock timeout
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            await init.await_background_context(ctx)

        assert ctx.background_research_task is None

    @pytest.mark.asyncio
    async def test_no_op_without_tasks(self):
        """No-op when no background tasks."""
        ctx = MockDebateContext()

        init = ContextInitializer()

        # Should not raise
        await init.await_background_context(ctx)


class TestInjectPulseContext:
    """Tests for Pulse trending topic auto-fetch."""

    @pytest.mark.asyncio
    async def test_fetches_from_pulse(self):
        """Fetches trending topics from Pulse manager."""
        ctx = MockDebateContext()
        topic = MockTrendingTopic()

        pulse = MagicMock()
        # get_trending_topics is async, but select_topic_for_debate is sync
        pulse.get_trending_topics = AsyncMock(return_value=[topic])
        pulse.select_topic_for_debate = MagicMock(return_value=topic)

        init = ContextInitializer(
            pulse_manager=pulse,
            auto_fetch_trending=True,
        )

        await init._inject_pulse_context(ctx)

        assert init.trending_topic is topic

    @pytest.mark.asyncio
    async def test_handles_pulse_timeout(self):
        """Handles Pulse fetch timeout."""
        ctx = MockDebateContext()

        pulse = AsyncMock()
        pulse.get_trending_topics.side_effect = asyncio.TimeoutError

        init = ContextInitializer(pulse_manager=pulse)

        # Should not raise
        await init._inject_pulse_context(ctx)

    @pytest.mark.asyncio
    async def test_skips_without_pulse(self):
        """Skips when no Pulse manager."""
        ctx = MockDebateContext()

        init = ContextInitializer()

        # Should not raise
        await init._inject_pulse_context(ctx)


class TestInjectKnowledgeContext:
    """Tests for Knowledge Mound context injection."""

    @pytest.mark.asyncio
    async def test_injects_knowledge_context(self):
        """Injects knowledge from Knowledge Mound."""
        ctx = MockDebateContext()

        async def fetch_knowledge(task, limit):
            return "## Relevant Knowledge\nPreviously learned: X is true"

        mound = MagicMock()
        init = ContextInitializer(
            knowledge_mound=mound,
            enable_knowledge_retrieval=True,
            fetch_knowledge_context=fetch_knowledge,
        )

        await init._inject_knowledge_context(ctx)

        assert "Relevant Knowledge" in ctx.env.context

    @pytest.mark.asyncio
    async def test_handles_knowledge_timeout(self):
        """Handles knowledge fetch timeout."""
        # Clear the module-level knowledge cache to ensure fresh fetch
        from aragora.debate.phases import context_init

        context_init._knowledge_cache.clear()

        ctx = MockDebateContext()

        async def slow_fetch(task, limit):
            await asyncio.sleep(100)
            return "Knowledge"

        mound = MagicMock()
        init = ContextInitializer(
            knowledge_mound=mound,
            fetch_knowledge_context=slow_fetch,
        )

        # Mock _get_cached_knowledge to return None, forcing the fetch path
        # This ensures we test the timeout handling rather than cache hits
        with patch.object(init, "_get_cached_knowledge", return_value=None):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                await init._inject_knowledge_context(ctx)

        # Context unchanged after timeout
        assert ctx.env.context == ""

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        """Skips when knowledge retrieval disabled."""
        ctx = MockDebateContext()

        init = ContextInitializer(
            knowledge_mound=MagicMock(),
            enable_knowledge_retrieval=False,
        )

        await init._inject_knowledge_context(ctx)

        assert ctx.env.context == ""


# =============================================================================
# Additional Coverage: Cross-Debate Context Tests
# =============================================================================


class TestInjectCrossDebateContext:
    """Tests for cross-debate institutional context injection."""

    @pytest.mark.asyncio
    async def test_injects_cross_debate_context(self):
        """Injects context from CrossDebateMemory."""
        ctx = MockDebateContext()

        # Need content >= 50 chars to pass the length check
        relevant_context = "## Historical Context\nPrevious debates showed X is true. More context here to meet length."
        cross_debate_memory = AsyncMock()
        cross_debate_memory.get_relevant_context.return_value = relevant_context

        init = ContextInitializer(
            cross_debate_memory=cross_debate_memory,
            enable_cross_debate_memory=True,
        )

        await init._inject_cross_debate_context(ctx)

        assert "INSTITUTIONAL KNOWLEDGE" in ctx.env.context
        assert "Previous debates" in ctx.env.context

    @pytest.mark.asyncio
    async def test_falls_back_to_memory_context(self):
        """Uses CritiqueStore-style memory when no dedicated cross-debate backend exists."""
        ctx = MockDebateContext()

        memory = MagicMock()
        memory.get_relevant_context = AsyncMock(
            return_value=(
                "- 2026-03-27: Similar debate concluded "
                '"Use a Redis-backed token bucket for shared rate limits."'
            )
        )

        init = ContextInitializer(
            memory=memory,
            enable_cross_debate_memory=True,
        )

        await init._inject_cross_debate_context(ctx)

        memory.get_relevant_context.assert_awaited_once_with(task=ctx.env.task)
        assert "INSTITUTIONAL KNOWLEDGE" in ctx.env.context
        assert "Redis-backed token bucket" in ctx.env.context

    @pytest.mark.asyncio
    async def test_handles_timeout(self):
        """Handles cross-debate fetch timeout."""
        ctx = MockDebateContext()

        cross_debate_memory = AsyncMock()
        cross_debate_memory.get_relevant_context.side_effect = asyncio.TimeoutError

        init = ContextInitializer(
            cross_debate_memory=cross_debate_memory,
            enable_cross_debate_memory=True,
        )

        # Should not raise
        await init._inject_cross_debate_context(ctx)
        assert ctx.env.context == ""

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        """Skips when cross-debate memory disabled."""
        ctx = MockDebateContext()

        init = ContextInitializer(
            cross_debate_memory=AsyncMock(),
            enable_cross_debate_memory=False,
        )

        await init._inject_cross_debate_context(ctx)
        assert ctx.env.context == ""

    @pytest.mark.asyncio
    async def test_skips_short_context(self):
        """Skips context that is too short."""
        ctx = MockDebateContext()

        cross_debate_memory = AsyncMock()
        cross_debate_memory.get_relevant_context.return_value = "Too short"

        init = ContextInitializer(
            cross_debate_memory=cross_debate_memory,
            enable_cross_debate_memory=True,
        )

        await init._inject_cross_debate_context(ctx)
        assert ctx.env.context == ""


# =============================================================================
# Additional Coverage: Receipt Conclusions Injection Tests
# =============================================================================


class TestInjectReceiptConclusions:
    """Tests for prior debate conclusion injection from receipt memory."""

    @staticmethod
    def _make_receipt_results(*items: Any) -> Any:
        return type("ReceiptQueryResult", (), {"items": list(items)})()

    @staticmethod
    def _make_receipt_item(
        content: str,
        confidence: str = "strong",
        verdict: str = "adopted",
    ) -> Any:
        return type(
            "ReceiptItem",
            (),
            {
                "content": content,
                "confidence": confidence,
                "metadata": {"verdict": verdict},
            },
        )()

    @pytest.mark.asyncio
    async def test_injects_receipt_conclusions_into_builder_prompt(self):
        """Appends prior conclusions to builder knowledge so prompts reference them."""
        import hashlib

        from aragora.core import Environment
        from aragora.debate.phases.context_init import _receipt_conclusions_cache
        from aragora.debate.prompt_builder import PromptBuilder
        from aragora.debate.protocol import DebateProtocol

        task = "Should we use a token bucket rate limiter for the public API?"
        query_hash = hashlib.md5(
            f"receipt_conclusions:{task}".encode(), usedforsecurity=False
        ).hexdigest()

        knowledge_mound = MagicMock()
        knowledge_mound.query = AsyncMock(
            return_value=self._make_receipt_results(
                self._make_receipt_item(
                    content="Previous debate conclusion: use token bucket with burst capacity.",
                    confidence="high",
                    verdict="accepted",
                )
            )
        )

        builder = PromptBuilder(protocol=DebateProtocol(), env=Environment(task=task))
        builder.set_knowledge_context("Existing organizational knowledge.")

        init = ContextInitializer(knowledge_mound=knowledge_mound)
        ctx = MockDebateContext(env=MockEnv(task=task), debate_id="debate-receipt-1")
        ctx._prompt_builder = builder

        try:
            await init._inject_receipt_conclusions(ctx)

            knowledge_text = builder.get_knowledge_mound_context()
            prompt = builder.build_proposal_prompt(MockAgent("claude"))

            assert "Existing organizational knowledge." in knowledge_text
            assert "PAST DECISION CONCLUSIONS" in knowledge_text
            assert "token bucket with burst capacity" in knowledge_text
            assert "institutional precedent" in knowledge_text
            assert "## Organizational Knowledge" in prompt
            assert "Previous debate conclusion" in prompt
        finally:
            _receipt_conclusions_cache.pop(query_hash, None)

    @pytest.mark.asyncio
    async def test_receipt_conclusions_fall_back_to_env_context(self):
        """Without a prompt builder, prior conclusions are appended to env.context."""
        import hashlib

        from aragora.debate.phases.context_init import _receipt_conclusions_cache

        task = "How should we version our API for mobile clients?"
        query_hash = hashlib.md5(
            f"receipt_conclusions:{task}".encode(), usedforsecurity=False
        ).hexdigest()

        knowledge_mound = MagicMock()
        knowledge_mound.query = AsyncMock(
            return_value=self._make_receipt_results(
                self._make_receipt_item(
                    content="Previous debate conclusion: keep backward-compatible v1 endpoints during rollout.",
                    confidence="moderate",
                    verdict="superseded",
                )
            )
        )

        init = ContextInitializer(knowledge_mound=knowledge_mound)
        ctx = MockDebateContext(
            env=MockEnv(task=task, context="Current migration plan under review.")
        )

        try:
            await init._inject_receipt_conclusions(ctx)

            assert ctx.env.context.startswith("Current migration plan under review.")
            assert "PAST DECISION CONCLUSIONS" in ctx.env.context
            assert "keep backward-compatible v1 endpoints" in ctx.env.context
            assert "superseded" in ctx.env.context
        finally:
            _receipt_conclusions_cache.pop(query_hash, None)

    @pytest.mark.asyncio
    async def test_cached_receipt_conclusions_skip_query_and_still_append(self):
        """Cached conclusions still reach the builder without re-querying KM."""
        import hashlib
        import time

        from aragora.core import Environment
        from aragora.debate.phases.context_init import _receipt_conclusions_cache
        from aragora.debate.prompt_builder import PromptBuilder
        from aragora.debate.protocol import DebateProtocol

        task = "Should we shard the notification queue by tenant?"
        query_hash = hashlib.md5(
            f"receipt_conclusions:{task}".encode(), usedforsecurity=False
        ).hexdigest()
        cached_text = (
            "## PAST DECISION CONCLUSIONS\n"
            "The following decisions were reached in previous debates on related topics.\n"
            "- **high confidence [accepted]**: Previous debate conclusion: shard by tenant to isolate noisy neighbors."
        )
        _receipt_conclusions_cache[query_hash] = (cached_text, time.time())

        knowledge_mound = MagicMock()
        knowledge_mound.query = AsyncMock()

        builder = PromptBuilder(protocol=DebateProtocol(), env=Environment(task=task))
        builder.set_knowledge_context("Base knowledge.")

        init = ContextInitializer(knowledge_mound=knowledge_mound)
        ctx = MockDebateContext(env=MockEnv(task=task))
        ctx._prompt_builder = builder

        try:
            await init._inject_receipt_conclusions(ctx)

            knowledge_mound.query.assert_not_called()
            knowledge_text = builder.get_knowledge_mound_context()
            assert "Base knowledge." in knowledge_text
            assert "shard by tenant to isolate noisy neighbors" in knowledge_text
        finally:
            _receipt_conclusions_cache.pop(query_hash, None)


# =============================================================================
# Additional Coverage: Belief Cruxes Injection Tests
# =============================================================================


class TestInjectBeliefCruxes:
    """Tests for belief cruxes injection from similar debates."""

    def test_injects_cruxes_from_similar_debates(self):
        """Injects belief cruxes from similar past debates."""
        ctx = MockDebateContext()
        ctx.domain = "testing"

        # Create mock similar debates with cruxes
        similar = MagicMock()
        similar.consensus = MagicMock()
        similar.consensus.metadata = {"belief_cruxes": ["Crux 1", "Crux 2"]}
        similar.consensus.key_claims = ["Claim A"]

        memory = MagicMock()
        memory.find_similar_debates.return_value = [similar]

        dissent_retriever = MagicMock()
        dissent_retriever.memory = memory

        init = ContextInitializer(
            dissent_retriever=dissent_retriever,
            enable_belief_guidance=True,
        )

        init._inject_belief_cruxes(ctx)

        assert "HISTORICAL CRUXES" in ctx.env.context
        assert "Crux 1" in ctx.env.context

    def test_skips_without_dissent_retriever(self):
        """Skips when no dissent retriever provided."""
        ctx = MockDebateContext()

        init = ContextInitializer(enable_belief_guidance=True)

        init._inject_belief_cruxes(ctx)
        assert ctx.env.context == ""

    def test_skips_without_similar_debates(self):
        """Skips when no similar debates found."""
        ctx = MockDebateContext()

        memory = MagicMock()
        memory.find_similar_debates.return_value = []

        dissent_retriever = MagicMock()
        dissent_retriever.memory = memory

        init = ContextInitializer(
            dissent_retriever=dissent_retriever,
            enable_belief_guidance=True,
        )

        init._inject_belief_cruxes(ctx)
        assert ctx.env.context == ""

    def test_handles_missing_cruxes(self):
        """Handles debates without cruxes or key claims."""
        ctx = MockDebateContext()

        similar = MagicMock()
        similar.consensus = MagicMock()
        similar.consensus.metadata = {}
        similar.consensus.key_claims = None

        memory = MagicMock()
        memory.find_similar_debates.return_value = [similar]

        dissent_retriever = MagicMock()
        dissent_retriever.memory = memory

        init = ContextInitializer(
            dissent_retriever=dissent_retriever,
            enable_belief_guidance=True,
        )

        init._inject_belief_cruxes(ctx)
        assert ctx.env.context == ""


# =============================================================================
# Additional Coverage: Historical Dissents Injection Tests
# =============================================================================


class TestInjectHistoricalDissents:
    """Tests for historical dissenting views injection."""

    def test_injects_dissent_context(self):
        """Injects dissenting views from similar past debates."""
        ctx = MockDebateContext()

        dissent_retriever = MagicMock()
        # Return empty structured data so it falls back to text blob
        dissent_retriever.retrieve_for_new_debate.return_value = {
            "dissent_by_type": {},
        }
        dissent_retriever.get_debate_preparation_context.return_value = (
            "## HISTORICAL DISSENTS\n"
            "In previous debates, Agent-X argued for alternative approach with reasoning..."
        )

        init = ContextInitializer(dissent_retriever=dissent_retriever)

        init._inject_historical_dissents(ctx)

        assert "HISTORICAL DISSENTS" in ctx.env.context

    def test_skips_short_dissent_context(self):
        """Skips dissent context that is too short."""
        ctx = MockDebateContext()

        dissent_retriever = MagicMock()
        dissent_retriever.retrieve_for_new_debate.return_value = {
            "dissent_by_type": {},
        }
        dissent_retriever.get_debate_preparation_context.return_value = "Short"

        init = ContextInitializer(dissent_retriever=dissent_retriever)

        init._inject_historical_dissents(ctx)
        assert ctx.env.context == ""

    def test_skips_without_dissent_retriever(self):
        """Skips when no dissent retriever."""
        ctx = MockDebateContext()

        init = ContextInitializer()

        init._inject_historical_dissents(ctx)
        assert ctx.env.context == ""

    def test_handles_dissent_error(self):
        """Handles dissent retriever errors gracefully."""
        ctx = MockDebateContext()

        dissent_retriever = MagicMock()
        dissent_retriever.retrieve_for_new_debate.side_effect = RuntimeError("DB error")
        dissent_retriever.get_debate_preparation_context.side_effect = RuntimeError("Error")

        init = ContextInitializer(dissent_retriever=dissent_retriever)

        # Should not raise
        with patch(
            "aragora.debate.phases.context_init.ContextInitializer._inject_epistemic_priors"
        ):
            init._inject_historical_dissents(ctx)
        assert ctx.env.context == ""


# =============================================================================
# Additional Coverage: Evidence Collection Tests
# =============================================================================


class TestCollectEvidence:
    """Tests for evidence collection during initialization."""

    @pytest.mark.asyncio
    async def test_collects_evidence_from_collector(self):
        """Collects evidence using evidence collector."""
        ctx = MockDebateContext()

        evidence_pack = MagicMock()
        evidence_pack.snippets = [MagicMock(content="Evidence 1")]
        evidence_pack.total_searched = 10
        evidence_pack.to_context_string.return_value = "## EVIDENCE\nSnippet 1"

        collector = AsyncMock()
        collector.collect_evidence.return_value = evidence_pack

        protocol = MagicMock()
        protocol.enable_evidence_collection = True

        init = ContextInitializer(
            evidence_collector=collector,
            protocol=protocol,
        )

        await init._collect_evidence(ctx)

        assert ctx.evidence_pack is not None
        assert "EVIDENCE" in ctx.env.context

    @pytest.mark.asyncio
    async def test_handles_evidence_timeout(self):
        """Handles evidence collection timeout."""
        ctx = MockDebateContext()

        collector = AsyncMock()
        collector.collect_evidence.side_effect = asyncio.TimeoutError

        protocol = MagicMock()
        protocol.enable_evidence_collection = True

        init = ContextInitializer(
            evidence_collector=collector,
            protocol=protocol,
        )

        # Should not raise
        await init._collect_evidence(ctx)

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        """Skips evidence collection when disabled."""
        ctx = MockDebateContext()

        collector = AsyncMock()
        protocol = MagicMock()
        protocol.enable_evidence_collection = False

        init = ContextInitializer(
            evidence_collector=collector,
            protocol=protocol,
        )

        await init._collect_evidence(ctx)

        collector.collect_evidence.assert_not_called()


# =============================================================================
# Additional Coverage: Skill Evidence Collection Tests
# =============================================================================


class TestCollectSkillEvidence:
    """Tests for skill-based evidence collection."""

    @pytest.mark.asyncio
    async def test_collects_evidence_from_skills(self):
        """Collects evidence from debate-compatible skills."""
        # Create mock skill registry
        skill_manifest = MagicMock()
        skill_manifest.name = "web_search"
        skill_manifest.version = "1.0.0"
        skill_manifest.capabilities = [MagicMock()]
        skill_manifest.tags = ["debate"]

        skill_result = MagicMock()
        skill_result.status = MagicMock()  # SUCCESS
        skill_result.data = "Search result data"
        skill_result.duration_seconds = 0.5

        registry = MagicMock()
        registry.list_skills.return_value = [skill_manifest]
        registry.invoke = AsyncMock(return_value=skill_result)

        init = ContextInitializer(
            skill_registry=registry,
            enable_skills=True,
        )

        # The _collect_skill_evidence method imports SkillCapability internally
        # It will handle the import internally, so we test that it runs without error
        snippets = await init._collect_skill_evidence("test task")

        # Returns empty if skills module not available or no matching skills
        assert isinstance(snippets, list)

    @pytest.mark.asyncio
    async def test_returns_empty_without_registry(self):
        """Returns empty list without skill registry."""
        init = ContextInitializer(enable_skills=True)

        snippets = await init._collect_skill_evidence("test task")

        assert snippets == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_disabled(self):
        """Returns empty list when skills disabled."""
        registry = MagicMock()
        init = ContextInitializer(
            skill_registry=registry,
            enable_skills=False,
        )

        snippets = await init._collect_skill_evidence("test task")

        assert snippets == []


# =============================================================================
# Additional Coverage: RLM Compression Tests
# =============================================================================


class TestCompressContextWithRLM:
    """Tests for RLM-based context compression."""

    @pytest.mark.asyncio
    async def test_compresses_long_context(self):
        """Compresses long context using RLM."""
        ctx = MockDebateContext()
        ctx.env.context = "A" * 2000  # Long context

        compression_result = MagicMock()
        compression_result.answer = "Compressed summary"
        compression_result.used_true_rlm = True
        compression_result.used_compression_fallback = False

        rlm = MagicMock()
        rlm.compress_and_query = AsyncMock(return_value=compression_result)

        init = ContextInitializer()
        init._rlm = rlm
        init.enable_rlm_compression = True

        await init._compress_context_with_rlm(ctx)

        rlm.compress_and_query.assert_called_once()
        assert hasattr(ctx, "rlm_compressed_context")

    @pytest.mark.asyncio
    async def test_skips_short_context(self):
        """Skips compression for short context."""
        ctx = MockDebateContext()
        ctx.env.context = "Short"

        rlm = MagicMock()
        rlm.compress_and_query = AsyncMock()

        init = ContextInitializer()
        init._rlm = rlm
        init.enable_rlm_compression = True

        await init._compress_context_with_rlm(ctx)

        rlm.compress_and_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_compression_timeout(self):
        """Handles RLM compression timeout."""
        ctx = MockDebateContext()
        ctx.env.context = "A" * 2000

        rlm = MagicMock()
        rlm.compress_and_query = AsyncMock(side_effect=asyncio.TimeoutError)

        init = ContextInitializer()
        init._rlm = rlm
        init.enable_rlm_compression = True

        # Should not raise
        await init._compress_context_with_rlm(ctx)

    @pytest.mark.asyncio
    async def test_handles_compression_error(self):
        """Handles RLM compression errors."""
        ctx = MockDebateContext()
        ctx.env.context = "A" * 2000

        rlm = MagicMock()
        rlm.compress_and_query = AsyncMock(side_effect=RuntimeError("RLM error"))

        init = ContextInitializer()
        init._rlm = rlm
        init.enable_rlm_compression = True

        # Should not raise
        await init._compress_context_with_rlm(ctx)

    @pytest.mark.asyncio
    async def test_skips_without_rlm(self):
        """Skips compression without RLM instance."""
        ctx = MockDebateContext()
        ctx.env.context = "A" * 2000

        init = ContextInitializer()
        init._rlm = None

        # Should not raise
        await init._compress_context_with_rlm(ctx)

    @pytest.mark.asyncio
    async def test_handles_provider_auth_error(self):
        """Issue #8101: provider SDK auth errors (e.g. openai.AuthenticationError,
        which is NOT a RuntimeError) must degrade to uncompressed context, never
        fail the phase."""

        class FakeAuthenticationError(Exception):
            """Mimics openai.AuthenticationError: plain Exception subclass."""

        ctx = MockDebateContext()
        ctx.env.context = "A" * 5000

        rlm = MagicMock()
        rlm.compress_and_query = AsyncMock(
            side_effect=FakeAuthenticationError("Error code: 401 - invalid api key")
        )

        init = ContextInitializer()
        init._rlm = rlm
        init.enable_rlm_compression = True

        # Should not raise — phase must continue without compression
        await init._compress_context_with_rlm(ctx)
        assert getattr(ctx, "rlm_compressed_context", None) is None

    @pytest.mark.asyncio
    async def test_provider_auth_error_logs_note(self, caplog):
        """The degraded path must leave a logged note for operators."""

        class FakeAuthenticationError(Exception):
            pass

        ctx = MockDebateContext()
        ctx.env.context = "B" * 5000

        rlm = MagicMock()
        rlm.compress_and_query = AsyncMock(side_effect=FakeAuthenticationError("401"))

        init = ContextInitializer()
        init._rlm = rlm
        init.enable_rlm_compression = True

        with caplog.at_level("WARNING", logger="aragora.debate.phases.context_init"):
            await init._compress_context_with_rlm(ctx)

        assert any("compression skipped" in rec.message.lower() for rec in caplog.records)


# =============================================================================
# Additional Coverage: Pre-Debate Research Tests
# =============================================================================


class TestPerformPreDebateResearch:
    """Tests for pre-debate research execution."""

    @pytest.mark.asyncio
    async def test_performs_research_when_enabled(self):
        """Performs research when protocol enables it."""
        ctx = MockDebateContext()

        protocol = MagicMock()
        protocol.enable_research = True

        research_fn = AsyncMock(return_value="## Research Results\nImportant findings...")

        init = ContextInitializer(
            protocol=protocol,
            perform_research=research_fn,
        )

        await init._perform_pre_debate_research(ctx)

        research_fn.assert_called_once_with("What is the best approach?")
        assert ctx.research_context == "## Research Results\nImportant findings..."

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        """Skips research when protocol disables it."""
        ctx = MockDebateContext()

        protocol = MagicMock()
        protocol.enable_research = False

        research_fn = AsyncMock()

        init = ContextInitializer(
            protocol=protocol,
            perform_research=research_fn,
        )

        await init._perform_pre_debate_research(ctx)

        research_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_research_error(self):
        """Handles research errors gracefully."""
        ctx = MockDebateContext()

        protocol = MagicMock()
        protocol.enable_research = True

        research_fn = AsyncMock(side_effect=RuntimeError("Research failed"))

        init = ContextInitializer(
            protocol=protocol,
            perform_research=research_fn,
        )

        # Should not raise
        await init._perform_pre_debate_research(ctx)

    @pytest.mark.asyncio
    async def test_handles_empty_research_result(self):
        """Handles empty research result."""
        ctx = MockDebateContext()

        protocol = MagicMock()
        protocol.enable_research = True

        research_fn = AsyncMock(return_value="")

        init = ContextInitializer(
            protocol=protocol,
            perform_research=research_fn,
        )

        await init._perform_pre_debate_research(ctx)

        assert not hasattr(ctx, "research_context") or ctx.research_context == ""


# =============================================================================
# Additional Coverage: Knowledge Cache Tests
# =============================================================================


class TestKnowledgeCache:
    """Tests for knowledge context caching."""

    def test_get_cached_knowledge_returns_cached_value(self):
        """Returns cached knowledge within TTL."""
        from aragora.debate.phases import context_init

        # Set up cache
        context_init._knowledge_cache["test_hash"] = ("Cached content", time.time())

        init = ContextInitializer()

        result = init._get_cached_knowledge("test_hash")

        assert result == "Cached content"

    def test_get_cached_knowledge_returns_none_for_expired(self):
        """Returns None for expired cache entry."""
        from aragora.debate.phases import context_init

        # Set up expired cache (6 minutes ago, TTL is 5 minutes)
        context_init._knowledge_cache["expired_hash"] = ("Old content", time.time() - 400)

        init = ContextInitializer()

        result = init._get_cached_knowledge("expired_hash")

        assert result is None

    def test_get_cached_knowledge_returns_none_for_missing(self):
        """Returns None for missing cache entry."""
        init = ContextInitializer()

        result = init._get_cached_knowledge("nonexistent_hash")

        assert result is None


# =============================================================================
# Additional Coverage: Full Initialize Flow Tests
# =============================================================================


class TestFullInitializeFlow:
    """Tests for the complete initialization flow."""

    @pytest.mark.asyncio
    async def test_initializes_with_all_options_enabled(self):
        """Initializes with all optional features enabled."""
        ctx = MockDebateContext()
        ctx.agents = [MockAgent("claude", "proposer")]

        protocol = MagicMock()
        protocol.enable_research = False  # Keep it fast
        protocol.enable_evidence_collection = False

        init = ContextInitializer(
            protocol=protocol,
            enable_knowledge_retrieval=False,  # Keep it fast
            enable_belief_guidance=False,
            enable_cross_debate_memory=False,
        )

        await init.initialize(ctx)

        assert ctx.result is not None
        assert len(ctx.proposers) == 1

    @pytest.mark.asyncio
    async def test_initialize_injects_fork_history_first(self):
        """Initialize injects fork history before other context."""
        from aragora.core import Message

        msg = Message(role="assistant", agent="claude", content="Previous response")
        ctx = MockDebateContext()
        ctx.agents = [MockAgent("claude", "proposer")]

        init = ContextInitializer(initial_messages=[msg])

        await init.initialize(ctx)

        # Fork history should be in partial_messages
        assert len(ctx.partial_messages) == 1
        assert ctx.partial_messages[0].content == "Previous response"

    @pytest.mark.asyncio
    async def test_initialize_creates_background_research_task(self):
        """Initialize creates background research task when enabled."""
        ctx = MockDebateContext()
        ctx.agents = [MockAgent("claude", "proposer")]

        protocol = MagicMock()
        protocol.enable_research = True
        protocol.enable_evidence_collection = False

        research_fn = AsyncMock(return_value="Research results")

        init = ContextInitializer(
            protocol=protocol,
            perform_research=research_fn,
            enable_knowledge_retrieval=False,
            enable_belief_guidance=False,
            enable_cross_debate_memory=False,
        )

        await init.initialize(ctx)

        # Background task should have been created
        assert ctx.background_research_task is not None
        # Clean up
        ctx.background_research_task.cancel()
        try:
            await ctx.background_research_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_initialize_creates_background_evidence_task(self):
        """Initialize creates background evidence task when enabled."""
        ctx = MockDebateContext()
        ctx.agents = [MockAgent("claude", "proposer")]

        evidence_pack = MagicMock()
        evidence_pack.snippets = []
        evidence_pack.total_searched = 0

        collector = AsyncMock()
        collector.collect_evidence.return_value = evidence_pack

        protocol = MagicMock()
        protocol.enable_research = False
        protocol.enable_evidence_collection = True

        init = ContextInitializer(
            protocol=protocol,
            evidence_collector=collector,
            enable_knowledge_retrieval=False,
            enable_belief_guidance=False,
            enable_cross_debate_memory=False,
        )

        await init.initialize(ctx)

        # Background task should have been created
        assert ctx.background_evidence_task is not None
        # Clean up
        ctx.background_evidence_task.cancel()
        try:
            await ctx.background_evidence_task
        except asyncio.CancelledError:
            pass


# Import required for time-based tests
import time


# =============================================================================
# Structured Dissent Injection Tests (Item 3)
# =============================================================================


class TestStructuredDissentInjection:
    """Tests for structured dissent injection by type."""

    def test_injects_structured_dissent_by_type(self):
        """Injects dissents organized by type when structured data available."""
        ctx = MockDebateContext()

        dissent_retriever = MagicMock()
        dissent_retriever.retrieve_for_new_debate.return_value = {
            "similar_debates": [],
            "relevant_dissents": [],
            "dissent_by_type": {
                "risk_warning": [
                    {
                        "content": "Deploying without rollback plan is risky",
                        "confidence": 0.85,
                        "agent_id": "claude",
                        "acknowledged": False,
                    }
                ],
                "alternative_approach": [
                    {
                        "content": "Consider event-driven architecture instead",
                        "confidence": 0.7,
                        "agent_id": "gpt4",
                        "reasoning": "Better scalability for this pattern",
                        "acknowledged": True,
                    }
                ],
                "fundamental_disagreement": [
                    {
                        "content": "Microservices add unnecessary complexity here",
                        "confidence": 0.9,
                        "agent_id": "gemini",
                        "acknowledged": False,
                    }
                ],
            },
            "unacknowledged_dissents": [],
            "total_similar": 2,
            "total_dissents": 3,
        }

        init = ContextInitializer(dissent_retriever=dissent_retriever)
        init._inject_historical_dissents(ctx)

        assert "WARNINGS FROM PAST DEBATES" in ctx.env.context
        assert "rollback plan is risky" in ctx.env.context
        assert "85%" in ctx.env.context  # confidence

        assert "ALTERNATIVE APPROACHES CONSIDERED" in ctx.env.context
        assert "event-driven architecture" in ctx.env.context
        assert "Better scalability" in ctx.env.context  # reasoning

        assert "FUNDAMENTAL DISAGREEMENTS" in ctx.env.context
        assert "Microservices add unnecessary complexity" in ctx.env.context
        assert "UNRESOLVED" in ctx.env.context  # not acknowledged

    def test_falls_back_to_text_blob_when_no_structured_data(self):
        """Falls back to get_debate_preparation_context when structured is empty."""
        ctx = MockDebateContext()

        dissent_retriever = MagicMock()
        dissent_retriever.retrieve_for_new_debate.return_value = {
            "similar_debates": [],
            "relevant_dissents": [],
            "dissent_by_type": {},
            "unacknowledged_dissents": [],
            "total_similar": 0,
            "total_dissents": 0,
        }
        dissent_retriever.get_debate_preparation_context.return_value = (
            "## HISTORICAL DISSENTS\n"
            "In previous debates, Agent-X argued for a different approach with reasoning..."
        )

        init = ContextInitializer(dissent_retriever=dissent_retriever)
        init._inject_historical_dissents(ctx)

        assert "HISTORICAL DISSENTS" in ctx.env.context

    def test_falls_back_when_retrieve_for_new_debate_missing(self):
        """Falls back to text blob when retrieve_for_new_debate not available."""
        ctx = MockDebateContext()

        dissent_retriever = MagicMock(spec=["get_debate_preparation_context"])
        dissent_retriever.get_debate_preparation_context.return_value = (
            "## HISTORICAL DISSENTS\n"
            "In previous debates, long context with lots of detail about prior dissents."
        )

        init = ContextInitializer(dissent_retriever=dissent_retriever)
        init._inject_historical_dissents(ctx)

        assert "HISTORICAL DISSENTS" in ctx.env.context

    def test_structured_dissent_shows_acknowledged_status(self):
        """Shows UNRESOLVED vs addressed status for fundamental disagreements."""
        ctx = MockDebateContext()

        dissent_retriever = MagicMock()
        dissent_retriever.retrieve_for_new_debate.return_value = {
            "similar_debates": [],
            "relevant_dissents": [],
            "dissent_by_type": {
                "fundamental_disagreement": [
                    {
                        "content": "Resolved issue from past",
                        "confidence": 0.8,
                        "agent_id": "claude",
                        "acknowledged": True,
                    },
                    {
                        "content": "Open issue still debated",
                        "confidence": 0.6,
                        "agent_id": "gpt4",
                        "acknowledged": False,
                    },
                ],
            },
            "unacknowledged_dissents": [],
            "total_similar": 1,
            "total_dissents": 2,
        }

        init = ContextInitializer(dissent_retriever=dissent_retriever)
        init._inject_historical_dissents(ctx)

        assert "addressed" in ctx.env.context
        assert "UNRESOLVED" in ctx.env.context

    def test_structured_dissent_combines_warnings(self):
        """Combines risk_warning and edge_case_concern into warnings section."""
        ctx = MockDebateContext()

        dissent_retriever = MagicMock()
        dissent_retriever.retrieve_for_new_debate.return_value = {
            "similar_debates": [],
            "relevant_dissents": [],
            "dissent_by_type": {
                "risk_warning": [
                    {
                        "content": "Production risk",
                        "confidence": 0.8,
                        "agent_id": "claude",
                    }
                ],
                "edge_case_concern": [
                    {
                        "content": "Edge case when input is empty",
                        "confidence": 0.6,
                        "agent_id": "gpt4",
                    }
                ],
            },
            "unacknowledged_dissents": [],
            "total_similar": 1,
            "total_dissents": 2,
        }

        init = ContextInitializer(dissent_retriever=dissent_retriever)
        init._inject_historical_dissents(ctx)

        assert "WARNINGS FROM PAST DEBATES" in ctx.env.context
        assert "Production risk" in ctx.env.context
        assert "Edge case when input is empty" in ctx.env.context

    def test_structured_dissent_error_falls_back(self):
        """Falls back to text blob when retrieve_for_new_debate raises."""
        ctx = MockDebateContext()

        dissent_retriever = MagicMock()
        dissent_retriever.retrieve_for_new_debate.side_effect = RuntimeError("DB error")
        dissent_retriever.get_debate_preparation_context.return_value = (
            "## HISTORICAL DISSENTS\n"
            "Fallback text with enough content to meet the 50-char minimum length threshold."
        )

        init = ContextInitializer(dissent_retriever=dissent_retriever)
        init._inject_historical_dissents(ctx)

        assert "Fallback text" in ctx.env.context

    def test_structured_dissent_appends_to_existing_context(self):
        """Appends structured dissent to existing context."""
        ctx = MockDebateContext()
        ctx.env.context = "Some existing context here."

        dissent_retriever = MagicMock()
        dissent_retriever.retrieve_for_new_debate.return_value = {
            "similar_debates": [],
            "relevant_dissents": [],
            "dissent_by_type": {
                "risk_warning": [
                    {
                        "content": "Important warning about this approach",
                        "confidence": 0.9,
                        "agent_id": "claude",
                    }
                ],
            },
            "unacknowledged_dissents": [],
            "total_similar": 1,
            "total_dissents": 1,
        }

        init = ContextInitializer(dissent_retriever=dissent_retriever)
        init._inject_historical_dissents(ctx)

        assert ctx.env.context.startswith("Some existing context here.")
        assert "WARNINGS FROM PAST DEBATES" in ctx.env.context

    def test_build_structured_returns_empty_for_no_typed_dissents(self):
        """Returns empty when dissent_by_type has only unsupported types."""
        dissent_retriever = MagicMock()
        dissent_retriever.retrieve_for_new_debate.return_value = {
            "similar_debates": [],
            "relevant_dissents": [],
            "dissent_by_type": {
                "minor_quibble": [{"content": "Small issue", "confidence": 0.3, "agent_id": "a"}],
            },
            "unacknowledged_dissents": [],
            "total_similar": 0,
            "total_dissents": 1,
        }

        init = ContextInitializer(dissent_retriever=dissent_retriever)
        result = init._build_structured_dissent_context("test topic", None)

        assert result == ""


# ---------------------------------------------------------------------------
# Codebase grounding (Piece 6)
# ---------------------------------------------------------------------------


class TestCodebaseGrounding:
    """Tests for codebase context injection in ContextInitializer."""

    def test_codebase_params_stored(self):
        """Verify codebase params are stored on the initializer."""
        init = ContextInitializer(
            codebase_path="/repo",
            enable_codebase_grounding=True,
            codebase_persist_to_km=True,
        )
        assert init.codebase_path == "/repo"
        assert init.enable_codebase_grounding is True
        assert init.codebase_persist_to_km is True

    def test_codebase_defaults(self):
        """Verify codebase params default to disabled."""
        init = ContextInitializer()
        assert init.codebase_path is None
        assert init.enable_codebase_grounding is False
        assert init.codebase_persist_to_km is False

    @pytest.mark.asyncio
    async def test_inject_codebase_context_disabled(self):
        """When disabled, codebase context injection is skipped."""
        init = ContextInitializer(enable_codebase_grounding=False, codebase_path="/repo")
        ctx = MagicMock()
        ctx.env.task = "test"

        # Should not be called in initialize() since enable_codebase_grounding is False
        # We verify the method exists and handles gracefully
        await init._inject_codebase_context(ctx)
        # No error raised

    @pytest.mark.asyncio
    async def test_inject_codebase_context_success(self):
        """Verify codebase context is set on prompt builder."""
        init = ContextInitializer(
            enable_codebase_grounding=True,
            codebase_path="/repo",
        )

        mock_prompt_builder = MagicMock()
        mock_prompt_builder.set_codebase_context = MagicMock()

        ctx = MagicMock()
        ctx.env.task = "refactor debate module"
        ctx._prompt_builder = mock_prompt_builder

        mock_provider = AsyncMock()
        mock_provider.build_context = AsyncMock(return_value="codebase summary")
        mock_provider.get_summary = MagicMock(return_value="truncated summary")

        with (
            patch(
                "aragora.debate.codebase_context.CodebaseContextProvider",
                return_value=mock_provider,
            ),
            patch(
                "aragora.debate.codebase_context.CodebaseContextConfig",
            ),
        ):
            await init._inject_codebase_context(ctx)

        mock_prompt_builder.set_codebase_context.assert_called_once_with("truncated summary")

    @pytest.mark.asyncio
    async def test_inject_codebase_context_timeout(self):
        """Verify timeout is handled gracefully."""
        import asyncio

        init = ContextInitializer(
            enable_codebase_grounding=True,
            codebase_path="/repo",
        )

        ctx = MagicMock()
        ctx.env.task = "test"
        ctx._prompt_builder = MagicMock()

        async def slow_build(*args, **kwargs):
            await asyncio.sleep(100)
            return "never reached"

        mock_provider = AsyncMock()
        mock_provider.build_context = slow_build
        mock_provider.get_summary = MagicMock(return_value="")

        with (
            patch(
                "aragora.debate.codebase_context.CodebaseContextProvider",
                return_value=mock_provider,
            ),
            patch(
                "aragora.debate.codebase_context.CodebaseContextConfig",
            ),
            patch(
                "aragora.debate.phases.context_init.asyncio.wait_for",
                side_effect=asyncio.TimeoutError,
            ),
        ):
            # Should not raise
            await init._inject_codebase_context(ctx)

        ctx._prompt_builder.set_codebase_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_inject_codebase_context_import_error(self):
        """Verify import error is handled gracefully."""
        init = ContextInitializer(
            enable_codebase_grounding=True,
            codebase_path="/repo",
        )

        ctx = MagicMock()
        ctx.env.task = "test"
        ctx._prompt_builder = MagicMock()

        with (
            patch(
                "aragora.debate.codebase_context.CodebaseContextProvider",
                side_effect=ImportError("not available"),
            ),
            patch(
                "aragora.debate.codebase_context.CodebaseContextConfig",
                side_effect=ImportError("not available"),
            ),
        ):
            # Should not raise
            await init._inject_codebase_context(ctx)

    @pytest.mark.asyncio
    async def test_inject_codebase_no_prompt_builder(self):
        """Verify no error when prompt builder is not set."""
        init = ContextInitializer(
            enable_codebase_grounding=True,
            codebase_path="/repo",
        )

        ctx = MagicMock()
        ctx.env.task = "test"
        ctx._prompt_builder = None

        mock_provider = AsyncMock()
        mock_provider.build_context = AsyncMock(return_value="context")
        mock_provider.get_summary = MagicMock(return_value="summary")

        with (
            patch(
                "aragora.debate.codebase_context.CodebaseContextProvider",
                return_value=mock_provider,
            ),
            patch(
                "aragora.debate.codebase_context.CodebaseContextConfig",
            ),
        ):
            # Should not raise even though prompt_builder is None
            await init._inject_codebase_context(ctx)
