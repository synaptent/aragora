"""
Tests for LangGraph Agent.

Tests cover:
- LangGraphConfig initialization and defaults
- LangGraphAgent creation and configuration
- Node whitelist enforcement (allowed_nodes)
- State size validation (max_state_size)
- Recursion limit configuration
- Interrupt point configuration
- invoke() method with mock HTTP responses
- stream() method with mock async iteration
- get_state() and update_state() methods
- Thread ID management
- Error handling
- Agent registry integration
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def sample_context():
    """Sample message context for testing."""
    from aragora.core import Message

    return [
        Message(
            agent="agent1",
            content="Previous context message",
            role="proposer",
            round=1,
        ),
    ]


@pytest.fixture
def mock_langgraph_response():
    """Standard LangGraph run response."""
    return {
        "run_id": "run-123",
        "thread_id": "thread-456",
        "output": {
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "LangGraph response: Task processed."},
            ]
        },
    }


@pytest.fixture
def mock_stream_events():
    """Mock streaming events for LangGraph."""
    return [
        {"node": "start", "data": {"input": "test"}},
        {"node": "agent", "data": {"thinking": "processing..."}},
        {"node": "agent", "data": {"output": "result"}},
        {"node": "end", "data": {"final": True}},
    ]


class TestLangGraphConfig:
    """Tests for LangGraphConfig dataclass."""

    def test_config_defaults(self):
        """Should have sensible default values."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphConfig

        config = LangGraphConfig(base_url="http://localhost:8123")

        assert config.graph_id is None
        assert config.checkpoint_ns is None
        assert config.recursion_limit == 50
        assert config.stream_mode == "values"
        assert config.interrupt_before == []
        assert config.interrupt_after == []
        assert config.allowed_nodes == []
        assert config.max_state_size == 1048576  # 1MB

    def test_config_post_init_sets_endpoints(self):
        """Should set LangGraph-specific endpoints."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphConfig

        config = LangGraphConfig(base_url="")
        config.__post_init__()

        assert config.generate_endpoint == "/runs/stream"
        assert config.health_endpoint == "/health"

    def test_config_post_init_reads_env_url(self, monkeypatch):
        """Should read LANGGRAPH_URL from environment."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphConfig

        monkeypatch.setenv("LANGGRAPH_URL", "http://langgraph.example.com")

        config = LangGraphConfig(base_url="")
        config.__post_init__()

        assert config.base_url == "http://langgraph.example.com"

    def test_config_preserves_explicit_base_url(self, monkeypatch):
        """Should prefer explicit base_url over environment."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphConfig

        monkeypatch.setenv("LANGGRAPH_URL", "http://from-env.com")

        config = LangGraphConfig(base_url="http://explicit.com")
        config.__post_init__()

        assert config.base_url == "http://explicit.com"

    def test_config_custom_values(self):
        """Should accept custom configuration values."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphConfig

        config = LangGraphConfig(
            base_url="https://langgraph.enterprise.com",
            graph_id="my-custom-graph",
            checkpoint_ns="production",
            recursion_limit=25,
            stream_mode="updates",
            interrupt_before=["review"],
            interrupt_after=["generate"],
            allowed_nodes=["start", "agent", "end"],
            max_state_size=2097152,  # 2MB
        )

        assert config.base_url == "https://langgraph.enterprise.com"
        assert config.graph_id == "my-custom-graph"
        assert config.checkpoint_ns == "production"
        assert config.recursion_limit == 25
        assert config.stream_mode == "updates"
        assert config.interrupt_before == ["review"]
        assert config.interrupt_after == ["generate"]
        assert config.allowed_nodes == ["start", "agent", "end"]
        assert config.max_state_size == 2097152

    def test_config_validate_stream_mode_valid(self):
        """Should accept valid stream modes."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphConfig

        for mode in ["values", "updates", "debug"]:
            config = LangGraphConfig(base_url="http://localhost", stream_mode=mode)
            config.validate_stream_mode()  # Should not raise

    def test_config_validate_stream_mode_invalid(self):
        """Should reject invalid stream modes."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphConfig

        config = LangGraphConfig(base_url="http://localhost", stream_mode="invalid")

        with pytest.raises(ValueError, match="Invalid stream_mode"):
            config.validate_stream_mode()


class TestLangGraphAgentInitialization:
    """Tests for agent initialization."""

    def test_init_with_defaults(self, monkeypatch):
        """Should initialize with default values."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        # Clear env vars to test defaults
        monkeypatch.delenv("LANGGRAPH_URL", raising=False)
        monkeypatch.delenv("LANGGRAPH_API_KEY", raising=False)

        agent = LangGraphAgent()

        assert agent.name == "langgraph"
        assert agent.model == "langgraph"
        assert agent.agent_type == "langgraph"
        assert agent.langgraph_config is not None
        assert agent.langgraph_config.recursion_limit == 50

    def test_init_with_custom_config(self):
        """Should initialize with custom configuration."""
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="https://custom.langgraph.com",
            graph_id="my-graph",
            recursion_limit=30,
            allowed_nodes=["node1", "node2"],
        )
        config.__post_init__()

        agent = LangGraphAgent(
            name="custom-langgraph",
            config=config,
        )

        assert agent.name == "custom-langgraph"
        assert agent.base_url == "https://custom.langgraph.com"
        assert agent.langgraph_config.graph_id == "my-graph"
        assert agent.langgraph_config.recursion_limit == 30
        assert agent.langgraph_config.allowed_nodes == ["node1", "node2"]

    def test_init_with_api_key(self):
        """Should accept API key."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent(api_key="test-langgraph-key")

        assert agent.api_key == "test-langgraph-key"

    def test_init_reads_api_key_from_env(self, monkeypatch):
        """Should read API key from environment variable."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        monkeypatch.setenv("LANGGRAPH_API_KEY", "env-langgraph-key")

        agent = LangGraphAgent()

        assert agent.api_key == "env-langgraph-key"

    def test_agent_registry_registration(self):
        """Should be registered in agent registry."""
        from aragora.agents.registry import AgentRegistry

        # Import to trigger registration
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent  # noqa: F401

        spec = AgentRegistry.get_spec("langgraph")

        assert spec is not None
        assert spec.default_model == "langgraph"
        assert spec.agent_type == "API"
        assert spec.accepts_api_key is True


class TestLangGraphNodeFiltering:
    """Tests for node whitelist enforcement."""

    def test_validate_node_allowed_no_whitelist(self):
        """Should allow all nodes when no whitelist configured."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()

        assert agent._validate_node_allowed("any_node") is True
        assert agent._validate_node_allowed("another_node") is True

    def test_validate_node_allowed_with_whitelist(self):
        """Should only allow whitelisted nodes."""
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="http://localhost",
            allowed_nodes=["start", "agent", "end"],
        )
        agent = LangGraphAgent(config=config)

        assert agent._validate_node_allowed("start") is True
        assert agent._validate_node_allowed("agent") is True
        assert agent._validate_node_allowed("end") is True
        assert agent._validate_node_allowed("malicious_node") is False

    def test_filter_response_nodes_no_whitelist(self, mock_stream_events):
        """Should not filter when no whitelist configured."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()

        filtered = agent._filter_response_nodes(mock_stream_events)

        assert len(filtered) == len(mock_stream_events)

    def test_filter_response_nodes_with_whitelist(self, mock_stream_events):
        """Should filter events from disallowed nodes."""
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="http://localhost",
            allowed_nodes=["start", "end"],  # Exclude 'agent'
        )
        agent = LangGraphAgent(config=config)

        filtered = agent._filter_response_nodes(mock_stream_events)

        # Should filter out 'agent' node events
        assert len(filtered) == 2
        assert all(e.get("node") in ["start", "end"] for e in filtered)


class TestLangGraphStateSizeValidation:
    """Tests for state size limits."""

    def test_validate_state_size_within_limit(self):
        """Should accept state within size limit."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()

        # Small state should pass
        state = {"key": "value"}
        agent._validate_state_size(state)  # Should not raise

    def test_validate_state_size_exceeds_limit(self):
        """Should reject state exceeding size limit."""
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )
        from aragora.agents.api_agents.common import AgentAPIError

        config = LangGraphConfig(
            base_url="http://localhost",
            max_state_size=100,  # Very small limit for testing
        )
        agent = LangGraphAgent(config=config)

        # Large state should fail
        large_state = {"data": "x" * 200}

        with pytest.raises(AgentAPIError, match="State size .* exceeds limit"):
            agent._validate_state_size(large_state)

    def test_validate_state_size_custom_limit(self):
        """Should use custom max_state_size."""
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="http://localhost",
            max_state_size=500,
        )
        agent = LangGraphAgent(config=config)

        # 400 bytes should pass with 500 byte limit
        state = {"data": "x" * 380}
        agent._validate_state_size(state)  # Should not raise


class TestLangGraphRecursionLimit:
    """Tests for recursion limit configuration."""

    def test_recursion_limit_default(self):
        """Should have default recursion limit of 50."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()

        assert agent.langgraph_config.recursion_limit == 50

    def test_recursion_limit_custom(self):
        """Should accept custom recursion limit."""
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="http://localhost",
            recursion_limit=100,
        )
        agent = LangGraphAgent(config=config)

        assert agent.langgraph_config.recursion_limit == 100

    def test_recursion_limit_in_payload(self):
        """Should include recursion limit in run payload."""
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="http://localhost",
            recursion_limit=25,
        )
        agent = LangGraphAgent(config=config)

        payload = agent._build_run_payload("test input")

        assert payload["config"]["recursion_limit"] == 25


class TestLangGraphInterruptPoints:
    """Tests for interrupt_before and interrupt_after."""

    def test_interrupt_points_default_empty(self):
        """Should have empty interrupt lists by default."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()

        assert agent.langgraph_config.interrupt_before == []
        assert agent.langgraph_config.interrupt_after == []

    def test_interrupt_points_custom(self):
        """Should accept custom interrupt points."""
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="http://localhost",
            interrupt_before=["review", "approve"],
            interrupt_after=["generate"],
        )
        agent = LangGraphAgent(config=config)

        assert agent.langgraph_config.interrupt_before == ["review", "approve"]
        assert agent.langgraph_config.interrupt_after == ["generate"]

    def test_interrupt_points_in_payload(self):
        """Should include interrupt points in run payload."""
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="http://localhost",
            interrupt_before=["review"],
            interrupt_after=["generate"],
        )
        agent = LangGraphAgent(config=config)

        payload = agent._build_run_payload("test")

        assert payload["interrupt_before"] == ["review"]
        assert payload["interrupt_after"] == ["generate"]


class TestLangGraphGenerate:
    """Tests for generate method."""

    @pytest.mark.asyncio
    async def test_generate_returns_response(self, mock_langgraph_response):
        """Should return extracted response text."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_langgraph_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.agents.api_agents.langgraph_agent.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.generate("Process this task")

        assert "LangGraph response" in result
        assert "Task processed" in result

    @pytest.mark.asyncio
    async def test_generate_stores_thread_id(self, mock_langgraph_response):
        """Should store thread_id from response."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_langgraph_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.agents.api_agents.langgraph_agent.create_client_session",
            return_value=mock_session,
        ):
            await agent.generate("test")

        assert agent._thread_id == "thread-456"

    @pytest.mark.asyncio
    async def test_generate_handles_rate_limit(self):
        """Should raise on rate limit."""
        from aragora.agents.api_agents.common import AgentAPIError
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        # Use unique name and disable circuit breaker
        agent = LangGraphAgent(name="test-rate-limit", enable_circuit_breaker=False)

        mock_response = MagicMock()
        mock_response.status = 429
        mock_response.text = AsyncMock(return_value="Rate limit exceeded")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "aragora.agents.api_agents.langgraph_agent.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentAPIError, match="Rate limited"):
                await agent.generate("test")


class TestLangGraphInvoke:
    """Tests for invoke method."""

    @pytest.mark.asyncio
    async def test_invoke_returns_full_response(self, mock_langgraph_response):
        """Should return full response dictionary."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_langgraph_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.agents.api_agents.langgraph_agent.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.invoke({"messages": [{"role": "user", "content": "test"}]})

        assert result["run_id"] == "run-123"
        assert result["thread_id"] == "thread-456"

    @pytest.mark.asyncio
    async def test_invoke_validates_state_size(self):
        """Should validate input state size."""
        from aragora.agents.api_agents.common import AgentAPIError
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="http://localhost",
            max_state_size=100,
        )
        agent = LangGraphAgent(config=config)

        large_input = {"data": "x" * 200}

        with pytest.raises(AgentAPIError, match="State size .* exceeds limit"):
            await agent.invoke(large_input)


class TestLangGraphStream:
    """Tests for stream method."""

    @pytest.mark.asyncio
    async def test_stream_yields_events(self, mock_stream_events):
        """Should yield streaming events."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()

        # Build SSE response
        sse_lines = []
        for event in mock_stream_events:
            sse_lines.append(f"data: {json.dumps(event)}\n")
        sse_lines.append("data: [DONE]\n")
        sse_data = "\n".join(sse_lines).encode()

        async def mock_iter_any():
            yield sse_data

        mock_content = MagicMock()
        mock_content.iter_any = mock_iter_any

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.content = mock_content
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.agents.api_agents.langgraph_agent.create_client_session",
            return_value=mock_session,
        ):
            events = []
            async for event in agent.stream("test input"):
                events.append(event)

        assert len(events) == 4
        assert events[0]["node"] == "start"
        assert events[-1]["node"] == "end"

    @pytest.mark.asyncio
    async def test_stream_filters_disallowed_nodes(self):
        """Should filter events from disallowed nodes."""
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="http://localhost",
            allowed_nodes=["start", "end"],
        )
        agent = LangGraphAgent(config=config)

        events = [
            {"node": "start", "data": {}},
            {"node": "malicious", "data": {}},  # Should be filtered
            {"node": "end", "data": {}},
        ]

        sse_lines = []
        for event in events:
            sse_lines.append(f"data: {json.dumps(event)}\n")
        sse_lines.append("data: [DONE]\n")
        sse_data = "\n".join(sse_lines).encode()

        async def mock_iter_any():
            yield sse_data

        mock_content = MagicMock()
        mock_content.iter_any = mock_iter_any

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.content = mock_content
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.agents.api_agents.langgraph_agent.create_client_session",
            return_value=mock_session,
        ):
            events_received = []
            async for event in agent.stream("test"):
                events_received.append(event)

        assert len(events_received) == 2
        nodes = [e["node"] for e in events_received]
        assert "malicious" not in nodes

    @pytest.mark.asyncio
    async def test_stream_validates_state_size(self):
        """Should validate input state size for stream."""
        from aragora.agents.api_agents.common import AgentAPIError
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="http://localhost",
            max_state_size=100,
        )
        agent = LangGraphAgent(config=config)

        large_input = {"data": "x" * 200}

        with pytest.raises(AgentAPIError, match="State size .* exceeds limit"):
            async for _ in agent.stream(large_input):
                pass


class TestLangGraphState:
    """Tests for get_state and update_state methods."""

    @pytest.mark.asyncio
    async def test_get_state_returns_state(self):
        """Should return thread state."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()
        agent.set_thread_id("thread-123")

        mock_state = {
            "values": {"messages": [{"role": "user", "content": "test"}]},
            "next": ["agent"],
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_state)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.agents.api_agents.langgraph_agent.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.get_state()

        assert result["values"]["messages"][0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_get_state_requires_thread_id(self):
        """Should raise if no thread_id."""
        from aragora.agents.api_agents.common import AgentAPIError
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()
        # Don't set thread_id

        with pytest.raises(AgentAPIError, match="No thread_id provided"):
            await agent.get_state()

    @pytest.mark.asyncio
    async def test_update_state_success(self):
        """Should update thread state."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()
        agent.set_thread_id("thread-123")

        mock_response_data = {"values": {"updated": True}}

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "aragora.agents.api_agents.langgraph_agent.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.update_state({"new_key": "new_value"})

        assert result["values"]["updated"] is True

    @pytest.mark.asyncio
    async def test_update_state_validates_node(self):
        """Should reject update from disallowed node."""
        from aragora.agents.api_agents.common import AgentAPIError
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="http://localhost",
            allowed_nodes=["start", "end"],
        )
        agent = LangGraphAgent(config=config)
        agent.set_thread_id("thread-123")

        with pytest.raises(AgentAPIError, match="not in allowed_nodes"):
            await agent.update_state({"key": "value"}, as_node="malicious")

    @pytest.mark.asyncio
    async def test_update_state_validates_size(self):
        """Should validate state size on update."""
        from aragora.agents.api_agents.common import AgentAPIError
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="http://localhost",
            max_state_size=100,
        )
        agent = LangGraphAgent(config=config)
        agent.set_thread_id("thread-123")

        large_state = {"data": "x" * 200}

        with pytest.raises(AgentAPIError, match="State size .* exceeds limit"):
            await agent.update_state(large_state)


class TestLangGraphThreadManagement:
    """Tests for thread ID management."""

    def test_set_thread_id(self):
        """Should set thread ID."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()
        agent.set_thread_id("my-thread-123")

        assert agent.get_thread_id() == "my-thread-123"

    def test_get_thread_id_initially_none(self):
        """Should return None when no thread set."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()

        assert agent.get_thread_id() is None

    def test_clear_thread(self):
        """Should clear thread ID."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()
        agent.set_thread_id("thread-123")
        agent.clear_thread()

        assert agent.get_thread_id() is None


class TestLangGraphConfigStatus:
    """Tests for get_config_status method."""

    def test_get_config_status(self):
        """Should return full configuration status."""
        from aragora.agents.api_agents.langgraph_agent import (
            LangGraphAgent,
            LangGraphConfig,
        )

        config = LangGraphConfig(
            base_url="http://localhost:8123",
            graph_id="my-graph",
            checkpoint_ns="prod",
            recursion_limit=30,
            stream_mode="updates",
            interrupt_before=["review"],
            interrupt_after=["generate"],
            allowed_nodes=["start", "agent", "end"],
            max_state_size=2097152,
        )
        agent = LangGraphAgent(config=config)
        agent.set_thread_id("thread-123")

        status = agent.get_config_status()

        assert status["graph_id"] == "my-graph"
        assert status["checkpoint_ns"] == "prod"
        assert status["recursion_limit"] == 30
        assert status["stream_mode"] == "updates"
        assert status["interrupt_before"] == ["review"]
        assert status["interrupt_after"] == ["generate"]
        assert status["allowed_nodes"] == ["start", "agent", "end"]
        assert status["max_state_size"] == 2097152
        assert status["thread_id"] == "thread-123"


class TestLangGraphErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_connection_error(self):
        """Should handle connection errors."""
        import aiohttp

        from aragora.agents.api_agents.common import AgentConnectionError
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        # Use unique name and disable circuit breaker
        agent = LangGraphAgent(name="test-conn-error", enable_circuit_breaker=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            side_effect=aiohttp.ClientConnectorError(MagicMock(), OSError("Connection refused"))
        )
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "aragora.agents.api_agents.langgraph_agent.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentConnectionError, match="Cannot connect"):
                await agent.generate("test")

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        """Should handle timeout errors."""
        from aragora.agents.api_agents.common import AgentTimeoutError
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        # Use unique name and disable circuit breaker
        agent = LangGraphAgent(name="test-timeout-error", enable_circuit_breaker=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=TimeoutError("Request timed out"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "aragora.agents.api_agents.langgraph_agent.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentTimeoutError, match="timed out"):
                await agent.generate("test")

    @pytest.mark.asyncio
    async def test_api_error(self):
        """Should handle API errors."""
        from aragora.agents.api_agents.common import AgentAPIError
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        # Use unique name and disable circuit breaker
        agent = LangGraphAgent(name="test-api-error", enable_circuit_breaker=False)

        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "aragora.agents.api_agents.langgraph_agent.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentAPIError, match="error 500"):
                await agent.generate("test")


class TestLangGraphInheritedBehavior:
    """Tests for behavior inherited from ExternalFrameworkAgent."""

    def test_inherits_from_external_framework_agent(self):
        """Should inherit from ExternalFrameworkAgent."""
        from aragora.agents.api_agents.external_framework import ExternalFrameworkAgent
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()

        assert isinstance(agent, ExternalFrameworkAgent)

    def test_has_circuit_breaker_support(self):
        """Should support circuit breaker configuration."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent(
            enable_circuit_breaker=True,
            circuit_breaker_threshold=5,
        )

        assert agent._circuit_breaker is not None

    def test_supports_response_sanitization(self):
        """Should inherit response sanitization."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()

        # Test sanitization method exists and works
        result = agent._sanitize_response("Test\x00with\x00nulls")
        assert "\x00" not in result

    def test_supports_generation_params(self):
        """Should support generation parameters."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        agent = LangGraphAgent()
        agent.set_generation_params(temperature=0.7, top_p=0.9)

        assert agent.temperature == 0.7
        assert agent.top_p == 0.9


class TestLangGraphModuleExports:
    """Tests for module exports."""

    def test_exports_agent_class(self):
        """Should export LangGraphAgent."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphAgent

        assert LangGraphAgent is not None

    def test_exports_config_class(self):
        """Should export LangGraphConfig."""
        from aragora.agents.api_agents.langgraph_agent import LangGraphConfig

        assert LangGraphConfig is not None

    def test_all_exports(self):
        """Should have correct __all__ exports."""
        from aragora.agents.api_agents import langgraph_agent

        assert "LangGraphAgent" in langgraph_agent.__all__
        assert "LangGraphConfig" in langgraph_agent.__all__
