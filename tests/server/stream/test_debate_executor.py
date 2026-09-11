"""
Tests for Debate Executor module.

Tests cover:
- parse_debate_request validation and parsing
- fetch_trending_topic_async functionality
- execute_debate_thread execution flow
- Agent creation and configuration
- Environment variable checking
- OpenRouter fallback behavior
- Error handling throughout the execution
- DEBATE_AVAILABLE flag behavior
"""

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from aragora.server.stream.debate_executor import (
    DEBATE_AVAILABLE,
    execute_debate_thread,
    fetch_trending_topic_async,
    parse_debate_request,
)


# =============================================================================
# parse_debate_request Tests
# =============================================================================


class TestParseDebateRequest:
    """Tests for parse_debate_request function."""

    def test_valid_minimal_request(self):
        """Parses minimal valid request."""
        data = {"question": "What is 2+2?"}

        config, error = parse_debate_request(data)

        assert error is None
        assert config is not None
        assert config["question"] == "What is 2+2?"
        assert config["agents_str"]  # Has default
        assert config["rounds"] > 0
        assert config["consensus"]

    def test_valid_full_request(self):
        """Parses full request with all fields."""
        data = {
            "question": "What is the best programming language?",
            "agents": "anthropic-api,openai-api,gemini",
            "rounds": 3,
            "consensus": "majority",
            "use_trending": True,
            "trending_category": "technology",
        }

        config, error = parse_debate_request(data)

        assert error is None
        assert config["question"] == "What is the best programming language?"
        assert "anthropic-api" in config["agents_str"]
        assert config["rounds"] == 3
        assert config["consensus"] == "majority"
        assert config["use_trending"] is True
        assert config["trending_category"] == "technology"

    def test_missing_question_returns_error(self):
        """Returns error for missing question."""
        data = {}

        config, error = parse_debate_request(data)

        assert config is None
        assert "question field is required" in error

    def test_empty_question_returns_error(self):
        """Returns error for empty question."""
        data = {"question": "   "}

        config, error = parse_debate_request(data)

        assert config is None
        assert "question field is required" in error

    def test_long_question_returns_error(self):
        """Returns error for question exceeding 10,000 characters."""
        data = {"question": "x" * 10001}

        config, error = parse_debate_request(data)

        assert config is None
        assert "10,000 characters" in error

    def test_agents_as_list(self):
        """Parses agents provided as list."""
        data = {
            "question": "Test question",
            "agents": ["anthropic-api", "openai-api", "gemini"],
        }

        config, error = parse_debate_request(data)

        assert error is None
        assert "anthropic-api" in config["agents_str"]
        assert "openai-api" in config["agents_str"]
        assert "gemini" in config["agents_str"]

    def test_agents_as_string(self):
        """Parses agents provided as comma-separated string."""
        data = {
            "question": "Test question",
            "agents": "anthropic-api,openai-api",
        }

        config, error = parse_debate_request(data)

        assert error is None
        assert "anthropic-api" in config["agents_str"]
        assert "openai-api" in config["agents_str"]

    def test_empty_agents_uses_default(self):
        """Uses default agents when agents field is empty."""
        data = {"question": "Test question", "agents": ""}

        config, error = parse_debate_request(data)

        assert error is None
        assert config["agents_str"]  # Has default value

    def test_too_few_agents_returns_error(self):
        """Returns error when less than 2 agents specified."""
        data = {"question": "Test question", "agents": "anthropic-api"}

        config, error = parse_debate_request(data)

        assert config is None
        assert "At least 2 agents" in error

    def test_too_many_agents_returns_error(self):
        """Returns error when too many agents specified."""
        # Create more agents than MAX_AGENTS_PER_DEBATE
        many_agents = ",".join([f"agent{i}" for i in range(100)])
        data = {"question": "Test question", "agents": many_agents}

        # This may fail during AgentSpec parsing or the count check
        config, error = parse_debate_request(data)

        assert config is None or "Too many agents" in (error or "")

    def test_rounds_clamped_to_valid_range(self):
        """Clamps rounds to valid range."""
        data_low = {"question": "Test", "agents": "anthropic-api,openai-api", "rounds": 0}
        data_high = {"question": "Test", "agents": "anthropic-api,openai-api", "rounds": 100}

        config_low, _ = parse_debate_request(data_low)
        config_high, _ = parse_debate_request(data_high)

        assert config_low["rounds"] >= 1
        assert config_high["rounds"] <= 20  # MAX_ROUNDS

    def test_invalid_rounds_uses_default(self):
        """Uses default rounds for invalid value."""
        data = {"question": "Test", "agents": "anthropic-api,openai-api", "rounds": "invalid"}

        config, error = parse_debate_request(data)

        assert error is None
        assert config["rounds"] > 0

    def test_default_use_trending(self):
        """use_trending defaults to False."""
        data = {"question": "Test", "agents": "anthropic-api,openai-api"}

        config, error = parse_debate_request(data)

        assert config["use_trending"] is False

    def test_default_trending_category(self):
        """trending_category defaults to None."""
        data = {"question": "Test", "agents": "anthropic-api,openai-api"}

        config, error = parse_debate_request(data)

        assert config["trending_category"] is None


# =============================================================================
# fetch_trending_topic_async Tests
# =============================================================================


class TestFetchTrendingTopicAsync:
    """Tests for fetch_trending_topic_async function."""

    @pytest.mark.asyncio
    async def test_returns_topic_on_success(self):
        """Returns trending topic on successful fetch."""
        mock_topic = MagicMock()
        mock_topic.topic = "AI breakthrough"

        mock_manager = MagicMock()
        mock_manager.get_trending_topics = AsyncMock(return_value=[mock_topic])
        mock_manager.select_topic_for_debate = MagicMock(return_value=mock_topic)

        with patch("aragora.server.stream.debate_executor.PulseManager", return_value=mock_manager):
            with patch("aragora.server.stream.debate_executor.TwitterIngestor"):
                with patch("aragora.server.stream.debate_executor.HackerNewsIngestor"):
                    with patch("aragora.server.stream.debate_executor.RedditIngestor"):
                        result = await fetch_trending_topic_async()

        assert result is mock_topic

    @pytest.mark.asyncio
    async def test_passes_category_filter(self):
        """Passes category filter to PulseManager."""
        mock_manager = MagicMock()
        mock_manager.get_trending_topics = AsyncMock(return_value=[])
        mock_manager.select_topic_for_debate = MagicMock(return_value=None)

        with patch("aragora.server.stream.debate_executor.PulseManager", return_value=mock_manager):
            with patch("aragora.server.stream.debate_executor.TwitterIngestor"):
                with patch("aragora.server.stream.debate_executor.HackerNewsIngestor"):
                    with patch("aragora.server.stream.debate_executor.RedditIngestor"):
                        await fetch_trending_topic_async(category="technology")

        mock_manager.get_trending_topics.assert_called_once()
        call_args = mock_manager.get_trending_topics.call_args
        assert call_args[1]["filters"] == {"categories": ["technology"]}

    @pytest.mark.asyncio
    async def test_returns_none_on_no_topics(self):
        """Returns None when no topics available."""
        mock_manager = MagicMock()
        mock_manager.get_trending_topics = AsyncMock(return_value=[])
        mock_manager.select_topic_for_debate = MagicMock(return_value=None)

        with patch("aragora.server.stream.debate_executor.PulseManager", return_value=mock_manager):
            with patch("aragora.server.stream.debate_executor.TwitterIngestor"):
                with patch("aragora.server.stream.debate_executor.HackerNewsIngestor"):
                    with patch("aragora.server.stream.debate_executor.RedditIngestor"):
                        result = await fetch_trending_topic_async()

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_import_error(self):
        """Returns None when pulse module not available."""
        with patch.dict("sys.modules", {"aragora.pulse.ingestor": None}):
            with patch(
                "aragora.server.stream.debate_executor.PulseManager",
                side_effect=ImportError("Module not found"),
            ):
                result = await fetch_trending_topic_async()

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        """Returns None on any exception."""
        with patch(
            "aragora.server.stream.debate_executor.PulseManager",
            side_effect=RuntimeError("Network error"),
        ):
            result = await fetch_trending_topic_async()

        assert result is None


# =============================================================================
# execute_debate_thread Tests
# =============================================================================


class TestExecuteDebateThread:
    """Tests for execute_debate_thread function."""

    @pytest.fixture
    def mock_emitter(self):
        """Create a mock event emitter."""
        emitter = MagicMock()
        emitter.emit = MagicMock()
        return emitter

    @pytest.fixture
    def mock_active_debates(self):
        """Patch active debates dict."""
        debates = {}
        with patch(
            "aragora.server.stream.debate_executor._active_debates",
            debates,
        ):
            with patch(
                "aragora.server.stream.debate_executor._active_debates_lock",
                MagicMock(),
            ):
                yield debates

    @patch("aragora.server.stream.debate_executor.AgentSpec")
    def test_too_many_agents_sets_error(self, mock_spec_class, mock_emitter, mock_active_debates):
        """Sets error status for too many agents."""
        debate_id = "test-debate-1"
        mock_active_debates[debate_id] = {"status": "starting"}

        # Create agent string with more than MAX_AGENTS_PER_DEBATE
        agents_str = ",".join([f"agent{i}" for i in range(100)])
        # Mock coerce_list to return 100 fake specs
        mock_spec_class.coerce_list.return_value = [MagicMock() for _ in range(100)]

        execute_debate_thread(
            debate_id=debate_id,
            question="Test question",
            agents_str=agents_str,
            rounds=3,
            consensus="majority",
            trending_topic=None,
            emitter=mock_emitter,
        )

        assert mock_active_debates[debate_id]["status"] == "error"
        assert "Too many agents" in mock_active_debates[debate_id]["error"]

    def test_too_few_agents_sets_error(self, mock_emitter, mock_active_debates):
        """Sets error status for too few agents."""
        debate_id = "test-debate-2"
        mock_active_debates[debate_id] = {"status": "starting"}

        execute_debate_thread(
            debate_id=debate_id,
            question="Test question",
            agents_str="anthropic-api",  # Only one agent
            rounds=3,
            consensus="majority",
            trending_topic=None,
            emitter=mock_emitter,
        )

        assert mock_active_debates[debate_id]["status"] == "error"
        assert "At least 2 agents" in mock_active_debates[debate_id]["error"]

    @patch("aragora.server.stream.debate_executor.AgentSpec")
    @patch("aragora.server.stream.debate_executor.AgentRegistry")
    def test_emits_debate_start_event(
        self, mock_registry, mock_spec_class, mock_emitter, mock_active_debates
    ):
        """Emits DEBATE_START event with agent info."""
        debate_id = "test-debate-3"
        mock_active_debates[debate_id] = {"status": "starting"}

        # Setup mock specs
        mock_spec1 = MagicMock()
        mock_spec1.provider = "anthropic-api"
        mock_spec1.name = None
        mock_spec1.model = None
        mock_spec1.persona = None
        mock_spec1.role = None

        mock_spec2 = MagicMock()
        mock_spec2.provider = "openai-api"
        mock_spec2.name = None
        mock_spec2.model = None
        mock_spec2.persona = None
        mock_spec2.role = None

        mock_spec_class.coerce_list.return_value = [mock_spec1, mock_spec2]

        # Mock registry to return specs with no env vars required
        mock_registry.get_spec.return_value = MagicMock(env_vars=None)

        # Mock create_agent to fail (we just want to test the event emission)
        with patch(
            "aragora.server.stream.debate_executor.create_agent",
            side_effect=ValueError("Test stop"),
        ):
            execute_debate_thread(
                debate_id=debate_id,
                question="Test question",
                agents_str="anthropic-api,openai-api",
                rounds=3,
                consensus="majority",
                trending_topic=None,
                emitter=mock_emitter,
            )

        # Check DEBATE_START was emitted
        debate_start_calls = [
            call
            for call in mock_emitter.emit.call_args_list
            if hasattr(call[0][0], "type") and call[0][0].type.value == "debate_start"
        ]
        assert len(debate_start_calls) >= 1

    @patch("aragora.server.stream.debate_executor._openrouter_key_available")
    @patch("aragora.server.stream.debate_executor.AgentSpec")
    @patch("aragora.server.stream.debate_executor.AgentRegistry")
    @patch("aragora.server.stream.debate_executor._missing_required_env_vars")
    def test_openrouter_fallback_on_missing_key(
        self,
        mock_missing_vars,
        mock_registry,
        mock_spec_class,
        mock_openrouter_available,
        mock_emitter,
        mock_active_debates,
    ):
        """Falls back to OpenRouter when provider key missing."""
        debate_id = "test-debate-4"
        mock_active_debates[debate_id] = {"status": "starting"}

        mock_openrouter_available.return_value = True

        # Setup specs
        mock_spec = MagicMock()
        mock_spec.provider = "anthropic-api"
        mock_spec.name = None
        mock_spec.model = None
        mock_spec.persona = None
        mock_spec.role = None

        mock_spec2 = MagicMock()
        mock_spec2.provider = "openai-api"
        mock_spec2.name = None
        mock_spec2.model = None
        mock_spec2.persona = None
        mock_spec2.role = None

        mock_spec_class.coerce_list.return_value = [mock_spec, mock_spec2]
        mock_spec_class.return_value = MagicMock()  # Fallback spec

        # First provider missing key, second has key
        mock_missing_vars.side_effect = [["ANTHROPIC_API_KEY"], []]

        mock_registry.get_spec.return_value = MagicMock(env_vars="ANTHROPIC_API_KEY")

        with patch(
            "aragora.server.stream.debate_executor.create_agent",
            side_effect=ValueError("Test stop"),
        ):
            execute_debate_thread(
                debate_id=debate_id,
                question="Test question",
                agents_str="anthropic-api,openai-api",
                rounds=3,
                consensus="majority",
                trending_topic=None,
                emitter=mock_emitter,
            )

        # Check fallback event was emitted
        fallback_calls = [
            call
            for call in mock_emitter.emit.call_args_list
            if hasattr(call[0][0], "type")
            and call[0][0].type.value == "agent_error"
            and call[0][0].data.get("error_type") == "missing_env_fallback"
        ]
        assert len(fallback_calls) >= 1

    @patch("aragora.server.stream.debate_executor.AgentSpec")
    @patch("aragora.server.stream.debate_executor.AgentRegistry")
    @patch("aragora.server.stream.debate_executor.create_agent")
    @patch("aragora.server.stream.debate_executor.Environment")
    @patch("aragora.server.stream.debate_executor.DebateProtocol")
    @patch("aragora.server.stream.debate_executor.Arena")
    @patch("aragora.server.stream.debate_executor.create_arena_hooks")
    @patch("aragora.server.stream.debate_executor.wrap_agent_for_streaming")
    def test_successful_debate_execution(
        self,
        mock_wrap,
        mock_hooks,
        mock_arena_class,
        mock_protocol_class,
        mock_env_class,
        mock_create_agent,
        mock_registry,
        mock_spec_class,
        mock_emitter,
        mock_active_debates,
    ):
        """Runs complete debate and sets result."""
        debate_id = "test-debate-5"
        mock_active_debates[debate_id] = {"status": "starting"}

        # Setup specs
        mock_spec1 = MagicMock()
        mock_spec1.provider = "anthropic-api"
        mock_spec1.name = "claude"
        mock_spec1.model = None
        mock_spec1.persona = None
        mock_spec1.role = None

        mock_spec2 = MagicMock()
        mock_spec2.provider = "openai-api"
        mock_spec2.name = "gpt4"
        mock_spec2.model = None
        mock_spec2.persona = None
        mock_spec2.role = None

        mock_spec_class.coerce_list.return_value = [mock_spec1, mock_spec2]
        mock_registry.get_spec.return_value = MagicMock(env_vars=None)

        # Setup agent creation
        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        mock_create_agent.return_value = mock_agent
        mock_wrap.return_value = mock_agent

        # Setup arena
        mock_result = MagicMock()
        mock_result.final_answer = "The answer is 42"
        mock_result.consensus_reached = True
        mock_result.confidence = 0.95

        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(return_value=mock_result)
        mock_arena.protocol = MagicMock(timeout_seconds=0)
        mock_arena_class.return_value = mock_arena

        execute_debate_thread(
            debate_id=debate_id,
            question="What is the meaning of life?",
            agents_str="anthropic-api,openai-api",
            rounds=3,
            consensus="majority",
            trending_topic=None,
            emitter=mock_emitter,
        )

        assert mock_active_debates[debate_id]["status"] == "completed"
        assert mock_active_debates[debate_id]["result"]["final_answer"] == "The answer is 42"
        assert mock_active_debates[debate_id]["result"]["consensus_reached"] is True

    @patch("aragora.server.stream.debate_executor.AgentSpec")
    @patch("aragora.server.stream.debate_executor.AgentRegistry")
    @patch("aragora.server.stream.debate_executor.create_agent")
    @patch("aragora.server.stream.debate_executor.Environment")
    @patch("aragora.server.stream.debate_executor.DebateProtocol")
    @patch("aragora.server.stream.debate_executor.Arena")
    @patch("aragora.server.stream.debate_executor.create_arena_hooks")
    @patch("aragora.server.stream.debate_executor.wrap_agent_for_streaming")
    def test_debate_timeout_sets_error(
        self,
        mock_wrap,
        mock_hooks,
        mock_arena_class,
        mock_protocol_class,
        mock_env_class,
        mock_create_agent,
        mock_registry,
        mock_spec_class,
        mock_emitter,
        mock_active_debates,
    ):
        """Sets error status on debate timeout."""
        debate_id = "test-debate-6"
        mock_active_debates[debate_id] = {"status": "starting"}

        # Setup specs
        mock_spec1 = MagicMock()
        mock_spec1.provider = "anthropic-api"
        mock_spec1.name = None
        mock_spec1.model = None
        mock_spec1.persona = None
        mock_spec1.role = None

        mock_spec2 = MagicMock()
        mock_spec2.provider = "openai-api"
        mock_spec2.name = None
        mock_spec2.model = None
        mock_spec2.persona = None
        mock_spec2.role = None

        mock_spec_class.coerce_list.return_value = [mock_spec1, mock_spec2]
        mock_registry.get_spec.return_value = MagicMock(env_vars=None)

        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        mock_create_agent.return_value = mock_agent
        mock_wrap.return_value = mock_agent

        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_arena.protocol = MagicMock(timeout_seconds=0)
        mock_arena_class.return_value = mock_arena

        execute_debate_thread(
            debate_id=debate_id,
            question="Test",
            agents_str="anthropic-api,openai-api",
            rounds=3,
            consensus="majority",
            trending_topic=None,
            emitter=mock_emitter,
        )

        assert mock_active_debates[debate_id]["status"] == "error"
        assert mock_active_debates[debate_id]["error"]

    @patch("aragora.server.stream.debate_executor.AgentSpec")
    @patch("aragora.server.stream.debate_executor.AgentRegistry")
    @patch("aragora.server.stream.debate_executor.create_agent")
    def test_not_enough_agents_after_init_failures(
        self,
        mock_create_agent,
        mock_registry,
        mock_spec_class,
        mock_emitter,
        mock_active_debates,
    ):
        """Sets error when not enough agents initialize successfully."""
        debate_id = "test-debate-7"
        mock_active_debates[debate_id] = {"status": "starting"}

        mock_spec1 = MagicMock()
        mock_spec1.provider = "anthropic-api"
        mock_spec1.name = None
        mock_spec1.model = None
        mock_spec1.persona = None
        mock_spec1.role = None

        mock_spec2 = MagicMock()
        mock_spec2.provider = "openai-api"
        mock_spec2.name = None
        mock_spec2.model = None
        mock_spec2.persona = None
        mock_spec2.role = None

        mock_spec_class.coerce_list.return_value = [mock_spec1, mock_spec2]
        mock_registry.get_spec.return_value = MagicMock(env_vars=None)

        # All agent creations fail
        mock_create_agent.side_effect = ValueError("Init failed")

        execute_debate_thread(
            debate_id=debate_id,
            question="Test",
            agents_str="anthropic-api,openai-api",
            rounds=3,
            consensus="majority",
            trending_topic=None,
            emitter=mock_emitter,
        )

        assert mock_active_debates[debate_id]["status"] == "error"
        assert "Not enough agents" in mock_active_debates[debate_id]["error"]

    @patch("aragora.server.stream.debate_executor.AgentSpec")
    @patch("aragora.server.stream.debate_executor.AgentRegistry")
    @patch("aragora.server.stream.debate_executor.create_agent")
    @patch("aragora.server.stream.debate_executor.wrap_agent_for_streaming")
    @patch("aragora.server.stream.debate_executor.apply_persona_to_agent")
    def test_applies_persona_to_agent(
        self,
        mock_apply_persona,
        mock_wrap,
        mock_create_agent,
        mock_registry,
        mock_spec_class,
        mock_emitter,
        mock_active_debates,
    ):
        """Applies persona to agent when specified."""
        debate_id = "test-debate-8"
        mock_active_debates[debate_id] = {"status": "starting"}

        mock_spec = MagicMock()
        mock_spec.provider = "anthropic-api"
        mock_spec.name = None
        mock_spec.model = None
        mock_spec.persona = "skeptic"
        mock_spec.role = None

        mock_spec2 = MagicMock()
        mock_spec2.provider = "openai-api"
        mock_spec2.name = None
        mock_spec2.model = None
        mock_spec2.persona = None
        mock_spec2.role = None

        mock_spec_class.coerce_list.return_value = [mock_spec, mock_spec2]
        mock_registry.get_spec.return_value = MagicMock(env_vars=None)

        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        mock_create_agent.return_value = mock_agent
        mock_wrap.return_value = mock_agent

        # Stop after agent setup
        with patch(
            "aragora.server.stream.debate_executor.Environment",
            side_effect=ValueError("Test stop"),
        ):
            execute_debate_thread(
                debate_id=debate_id,
                question="Test",
                agents_str="anthropic-api,openai-api",
                rounds=3,
                consensus="majority",
                trending_topic=None,
                emitter=mock_emitter,
            )

        # Persona should be applied to first agent
        mock_apply_persona.assert_called()

    @patch("aragora.server.stream.debate_executor.AgentSpec")
    @patch("aragora.server.stream.debate_executor.AgentRegistry")
    @patch("aragora.server.stream.debate_executor.create_agent")
    @patch("aragora.server.stream.debate_executor.Environment")
    @patch("aragora.server.stream.debate_executor.DebateProtocol")
    @patch("aragora.server.stream.debate_executor.Arena")
    @patch("aragora.server.stream.debate_executor.create_arena_hooks")
    @patch("aragora.server.stream.debate_executor.wrap_agent_for_streaming")
    def test_uses_protocol_timeout(
        self,
        mock_wrap,
        mock_hooks,
        mock_arena_class,
        mock_protocol_class,
        mock_env_class,
        mock_create_agent,
        mock_registry,
        mock_spec_class,
        mock_emitter,
        mock_active_debates,
    ):
        """Uses protocol timeout when configured."""
        debate_id = "test-debate-9"
        mock_active_debates[debate_id] = {"status": "starting"}

        mock_spec1 = MagicMock()
        mock_spec1.provider = "anthropic-api"
        mock_spec1.name = None
        mock_spec1.model = None
        mock_spec1.persona = None
        mock_spec1.role = None

        mock_spec2 = MagicMock()
        mock_spec2.provider = "openai-api"
        mock_spec2.name = None
        mock_spec2.model = None
        mock_spec2.persona = None
        mock_spec2.role = None

        mock_spec_class.coerce_list.return_value = [mock_spec1, mock_spec2]
        mock_registry.get_spec.return_value = MagicMock(env_vars=None)

        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        mock_create_agent.return_value = mock_agent
        mock_wrap.return_value = mock_agent

        mock_result = MagicMock()
        mock_result.final_answer = "Answer"
        mock_result.consensus_reached = True
        mock_result.confidence = 0.9

        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(return_value=mock_result)
        mock_arena.protocol = MagicMock(timeout_seconds=300)  # Custom timeout
        mock_arena_class.return_value = mock_arena

        execute_debate_thread(
            debate_id=debate_id,
            question="Test",
            agents_str="anthropic-api,openai-api",
            rounds=3,
            consensus="majority",
            trending_topic=None,
            emitter=mock_emitter,
        )

        # Should complete successfully using protocol timeout
        assert mock_active_debates[debate_id]["status"] == "completed"

    @patch("aragora.server.stream.debate_executor.AgentSpec")
    @patch("aragora.server.stream.debate_executor.AgentRegistry")
    @patch("aragora.server.stream.debate_executor.create_agent")
    @patch("aragora.server.stream.debate_executor.Environment")
    @patch("aragora.server.stream.debate_executor.DebateProtocol")
    @patch("aragora.server.stream.debate_executor.Arena")
    @patch("aragora.server.stream.debate_executor.create_arena_hooks")
    @patch("aragora.server.stream.debate_executor.wrap_agent_for_streaming")
    @patch("aragora.server.stream.debate_executor.UsageTracker")
    def test_initializes_usage_tracker_with_user_id(
        self,
        mock_tracker_class,
        mock_wrap,
        mock_hooks,
        mock_arena_class,
        mock_protocol_class,
        mock_env_class,
        mock_create_agent,
        mock_registry,
        mock_spec_class,
        mock_emitter,
        mock_active_debates,
    ):
        """Initializes usage tracker when user_id provided."""
        debate_id = "test-debate-10"
        mock_active_debates[debate_id] = {"status": "starting"}

        mock_spec1 = MagicMock()
        mock_spec1.provider = "anthropic-api"
        mock_spec1.name = None
        mock_spec1.model = None
        mock_spec1.persona = None
        mock_spec1.role = None

        mock_spec2 = MagicMock()
        mock_spec2.provider = "openai-api"
        mock_spec2.name = None
        mock_spec2.model = None
        mock_spec2.persona = None
        mock_spec2.role = None

        mock_spec_class.coerce_list.return_value = [mock_spec1, mock_spec2]
        mock_registry.get_spec.return_value = MagicMock(env_vars=None)

        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        mock_create_agent.return_value = mock_agent
        mock_wrap.return_value = mock_agent

        mock_result = MagicMock()
        mock_result.final_answer = "Answer"
        mock_result.consensus_reached = True
        mock_result.confidence = 0.9

        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(return_value=mock_result)
        mock_arena.protocol = MagicMock(timeout_seconds=0)
        mock_arena_class.return_value = mock_arena

        execute_debate_thread(
            debate_id=debate_id,
            question="Test",
            agents_str="anthropic-api,openai-api",
            rounds=3,
            consensus="majority",
            trending_topic=None,
            emitter=mock_emitter,
            user_id="user-123",
            org_id="org-456",
        )

        # Usage tracker should be instantiated
        mock_tracker_class.assert_called_once()


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestMissingRequiredEnvVars:
    """Tests for _missing_required_env_vars helper."""

    def test_empty_env_vars_returns_empty(self):
        """Returns empty list for empty env_vars."""
        from aragora.server.stream.debate_executor import _missing_required_env_vars

        result = _missing_required_env_vars("")

        assert result == []

    def test_optional_returns_empty(self):
        """Returns empty list when 'optional' in spec."""
        from aragora.server.stream.debate_executor import _missing_required_env_vars

        result = _missing_required_env_vars("ANTHROPIC_API_KEY (optional)")

        assert result == []

    def test_returns_missing_vars(self):
        """Returns list of missing env vars."""
        from aragora.server.stream.debate_executor import _missing_required_env_vars

        with patch.dict(os.environ, {}, clear=True):
            with patch("aragora.server.stream.debate_executor.get_api_key", return_value=None):
                result = _missing_required_env_vars("ANTHROPIC_API_KEY")

        assert "ANTHROPIC_API_KEY" in result

    def test_returns_empty_when_var_present(self):
        """Returns empty list when env var is set."""
        from aragora.server.stream.debate_executor import _missing_required_env_vars

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            result = _missing_required_env_vars("ANTHROPIC_API_KEY")

        assert result == []


class TestOpenrouterKeyAvailable:
    """Tests for _openrouter_key_available helper."""

    @staticmethod
    def _presence(source: str):
        from aragora.config.secrets import SecretPresence

        return SecretPresence(
            name="OPENROUTER_API_KEY",
            source=source,
            critical=True,
            managed=True,
        )

    def test_returns_true_with_managed_secret(self):
        from aragora.server.stream.debate_executor import _openrouter_key_available

        with patch(
            "aragora.server.stream.debate_executor.get_secret_presence",
            return_value=self._presence("mounted_file"),
        ):
            assert _openrouter_key_available() is True

    def test_returns_true_with_allowed_env_var(self):
        from aragora.server.stream.debate_executor import _openrouter_key_available

        with patch(
            "aragora.server.stream.debate_executor.get_secret_presence",
            return_value=self._presence("env"),
        ):
            assert _openrouter_key_available() is True

    def test_returns_false_when_not_configured(self):
        from aragora.server.stream.debate_executor import _openrouter_key_available

        with patch(
            "aragora.server.stream.debate_executor.get_secret_presence",
            return_value=self._presence("missing"),
        ):
            assert _openrouter_key_available() is False

    def test_returns_false_when_strict_mode_blocks_env(self):
        from aragora.server.stream.debate_executor import _openrouter_key_available

        with patch(
            "aragora.server.stream.debate_executor.get_secret_presence",
            return_value=self._presence("blocked_by_strict_mode"),
        ):
            assert _openrouter_key_available() is False


# =============================================================================
# DEBATE_AVAILABLE Flag Tests
# =============================================================================


class TestDebateAvailable:
    """Tests for DEBATE_AVAILABLE flag."""

    def test_debate_available_is_boolean(self):
        """DEBATE_AVAILABLE is a boolean."""
        assert isinstance(DEBATE_AVAILABLE, bool)

    def test_can_import_when_available(self):
        """Can import debate components when available."""
        if DEBATE_AVAILABLE:
            from aragora.server.stream.debate_executor import Arena, DebateProtocol, Environment

            assert Arena is not None
            assert DebateProtocol is not None
            assert Environment is not None


# =============================================================================
# Constants Tests
# =============================================================================


class TestExecutorConstants:
    """Tests for module constants."""

    def test_fallback_models_defined(self):
        """OpenRouter fallback models are defined."""
        from aragora.server.stream.debate_executor import _OPENROUTER_FALLBACK_MODELS

        assert "anthropic-api" in _OPENROUTER_FALLBACK_MODELS
        assert "openai-api" in _OPENROUTER_FALLBACK_MODELS
        assert "gemini" in _OPENROUTER_FALLBACK_MODELS

    def test_generic_fallback_defined(self):
        """Generic fallback model is defined."""
        from aragora.server.stream.debate_executor import _OPENROUTER_GENERIC_FALLBACK_MODEL

        assert _OPENROUTER_GENERIC_FALLBACK_MODEL
        assert "/" in _OPENROUTER_GENERIC_FALLBACK_MODEL  # Format: provider/model


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling throughout execution."""

    @pytest.fixture
    def mock_emitter(self):
        emitter = MagicMock()
        emitter.emit = MagicMock()
        return emitter

    @pytest.fixture
    def mock_active_debates(self):
        debates = {}
        with patch(
            "aragora.server.stream.debate_executor._active_debates",
            debates,
        ):
            with patch(
                "aragora.server.stream.debate_executor._active_debates_lock",
                MagicMock(),
            ):
                yield debates

    @patch("aragora.server.stream.debate_executor.AgentSpec")
    @patch("aragora.server.stream.debate_executor.AgentRegistry")
    @patch("aragora.server.stream.debate_executor.create_agent")
    @patch("aragora.server.stream.debate_executor.Environment")
    @patch("aragora.server.stream.debate_executor.DebateProtocol")
    @patch("aragora.server.stream.debate_executor.Arena")
    @patch("aragora.server.stream.debate_executor.create_arena_hooks")
    @patch("aragora.server.stream.debate_executor.wrap_agent_for_streaming")
    def test_runtime_error_sets_error_status(
        self,
        mock_wrap,
        mock_hooks,
        mock_arena_class,
        mock_protocol_class,
        mock_env_class,
        mock_create_agent,
        mock_registry,
        mock_spec_class,
        mock_emitter,
        mock_active_debates,
    ):
        """Runtime error during debate sets error status."""
        debate_id = "test-debate-err-1"
        mock_active_debates[debate_id] = {"status": "starting"}

        mock_spec1 = MagicMock()
        mock_spec1.provider = "anthropic-api"
        mock_spec1.name = None
        mock_spec1.model = None
        mock_spec1.persona = None
        mock_spec1.role = None

        mock_spec2 = MagicMock()
        mock_spec2.provider = "openai-api"
        mock_spec2.name = None
        mock_spec2.model = None
        mock_spec2.persona = None
        mock_spec2.role = None

        mock_spec_class.coerce_list.return_value = [mock_spec1, mock_spec2]
        mock_registry.get_spec.return_value = MagicMock(env_vars=None)

        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        mock_create_agent.return_value = mock_agent
        mock_wrap.return_value = mock_agent

        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(side_effect=RuntimeError("Unexpected error"))
        mock_arena.protocol = MagicMock(timeout_seconds=0)
        mock_arena_class.return_value = mock_arena

        execute_debate_thread(
            debate_id=debate_id,
            question="Test",
            agents_str="anthropic-api,openai-api",
            rounds=3,
            consensus="majority",
            trending_topic=None,
            emitter=mock_emitter,
        )

        assert mock_active_debates[debate_id]["status"] == "error"
        assert mock_active_debates[debate_id]["error"]

    @patch("aragora.server.stream.debate_executor.AgentSpec")
    @patch("aragora.server.stream.debate_executor.AgentRegistry")
    @patch("aragora.server.stream.debate_executor.create_agent")
    @patch("aragora.server.stream.debate_executor.Environment")
    @patch("aragora.server.stream.debate_executor.DebateProtocol")
    @patch("aragora.server.stream.debate_executor.Arena")
    @patch("aragora.server.stream.debate_executor.create_arena_hooks")
    @patch("aragora.server.stream.debate_executor.wrap_agent_for_streaming")
    def test_emits_error_event_on_failure(
        self,
        mock_wrap,
        mock_hooks,
        mock_arena_class,
        mock_protocol_class,
        mock_env_class,
        mock_create_agent,
        mock_registry,
        mock_spec_class,
        mock_emitter,
        mock_active_debates,
    ):
        """Emits ERROR event when debate fails."""
        debate_id = "test-debate-err-2"
        mock_active_debates[debate_id] = {"status": "starting"}

        mock_spec1 = MagicMock()
        mock_spec1.provider = "anthropic-api"
        mock_spec1.name = None
        mock_spec1.model = None
        mock_spec1.persona = None
        mock_spec1.role = None

        mock_spec2 = MagicMock()
        mock_spec2.provider = "openai-api"
        mock_spec2.name = None
        mock_spec2.model = None
        mock_spec2.persona = None
        mock_spec2.role = None

        mock_spec_class.coerce_list.return_value = [mock_spec1, mock_spec2]
        mock_registry.get_spec.return_value = MagicMock(env_vars=None)

        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        mock_create_agent.return_value = mock_agent
        mock_wrap.return_value = mock_agent

        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(side_effect=ValueError("Test error"))
        mock_arena.protocol = MagicMock(timeout_seconds=0)
        mock_arena_class.return_value = mock_arena

        execute_debate_thread(
            debate_id=debate_id,
            question="Test",
            agents_str="anthropic-api,openai-api",
            rounds=3,
            consensus="majority",
            trending_topic=None,
            emitter=mock_emitter,
        )

        # Check ERROR event was emitted
        error_calls = [
            call
            for call in mock_emitter.emit.call_args_list
            if hasattr(call[0][0], "type") and call[0][0].type.value == "error"
        ]
        assert len(error_calls) >= 1
