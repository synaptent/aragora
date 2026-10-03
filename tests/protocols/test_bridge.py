"""
Tests for protocol bridge module.

Tests MCP/A2A protocol bridging functionality.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.protocol_bridge import (
    BridgeConfig,
    ExternalResource,
    Protocol,
    ProtocolBridge,
    get_protocol_bridge,
)


class TestProtocol:
    """Tests for Protocol enum."""

    def test_all_protocols_exist(self):
        """All expected protocols are defined."""
        assert Protocol.MCP.value == "mcp"
        assert Protocol.A2A.value == "a2a"

    def test_protocol_from_string(self):
        """Protocols can be created from strings."""
        assert Protocol("mcp") == Protocol.MCP
        assert Protocol("a2a") == Protocol.A2A


class TestExternalResource:
    """Tests for ExternalResource dataclass."""

    def test_resource_creation(self):
        """Resources are created correctly."""
        resource = ExternalResource(
            protocol=Protocol.A2A,
            uri="a2a://agent/tool",
            name="Test Tool",
            description="A test tool",
        )

        assert resource.protocol == Protocol.A2A
        assert resource.uri == "a2a://agent/tool"
        assert resource.name == "Test Tool"
        assert resource.mime_type == "application/json"  # Default

    def test_resource_with_metadata(self):
        """Resources can have metadata."""
        resource = ExternalResource(
            protocol=Protocol.MCP,
            uri="mcp://server/resource",
            name="Data Resource",
            metadata={"version": "1.0", "format": "json"},
        )

        assert resource.metadata["version"] == "1.0"


class TestBridgeConfig:
    """Tests for BridgeConfig dataclass."""

    def test_default_config(self):
        """Default config has correct values."""
        config = BridgeConfig()

        assert config.enable_mcp is True
        assert config.enable_a2a is True
        assert config.mcp_timeout == 60.0
        assert config.a2a_timeout == 300.0
        assert config.default_protocol == Protocol.A2A
        assert config.cache_agent_cards is True

    def test_custom_config(self):
        """Config can be customized."""
        config = BridgeConfig(
            enable_mcp=False,
            a2a_timeout=600.0,
            a2a_registries=["https://registry.example.com"],
            default_protocol=Protocol.MCP,
        )

        assert config.enable_mcp is False
        assert config.a2a_timeout == 600.0
        assert len(config.a2a_registries) == 1


class TestProtocolBridge:
    """Tests for ProtocolBridge class."""

    def test_bridge_init_default_config(self):
        """Bridge initializes with default config."""
        bridge = ProtocolBridge()
        assert bridge.config.enable_a2a is True
        assert bridge._a2a_client is None  # Not initialized until initialize() called

    def test_bridge_init_custom_config(self):
        """Bridge accepts custom config."""
        config = BridgeConfig(enable_mcp=False)
        bridge = ProtocolBridge(config)
        assert bridge.config.enable_mcp is False

    @pytest.mark.asyncio
    async def test_initialize_creates_clients(self):
        """Initialize creates protocol clients."""
        bridge = ProtocolBridge()
        await bridge.initialize()

        # A2A client should be created
        assert bridge._a2a_client is not None
        assert bridge._a2a_server is not None

    @pytest.mark.asyncio
    async def test_initialize_discovers_agents(self):
        """Initialize discovers agents from registries."""
        config = BridgeConfig(a2a_registries=["https://registry.example.com"])
        bridge = ProtocolBridge(config)

        # Mock the client
        with patch.object(bridge, "_a2a_client") as mock_client:
            mock_client.discover_agents = AsyncMock(return_value=[])
            bridge._a2a_client = mock_client

            await bridge.initialize()
            # Discovery attempted (may fail, but shouldn't crash)

    def test_detect_protocol_known_agent(self):
        """Known agents use A2A protocol."""
        bridge = ProtocolBridge()

        # Register a known agent
        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        bridge._external_agents["test-agent"] = mock_agent

        protocol = bridge._detect_protocol("test-agent")
        assert protocol == Protocol.A2A

    def test_detect_protocol_mcp_scheme(self):
        """MCP scheme URLs use MCP protocol."""
        bridge = ProtocolBridge()
        protocol = bridge._detect_protocol("mcp://server/tool")
        assert protocol == Protocol.MCP

    def test_detect_protocol_a2a_scheme(self):
        """A2A scheme URLs use A2A protocol."""
        bridge = ProtocolBridge()
        protocol = bridge._detect_protocol("a2a://registry/agent")
        assert protocol == Protocol.A2A

    def test_detect_protocol_default(self):
        """Unknown targets use default protocol."""
        config = BridgeConfig(default_protocol=Protocol.MCP)
        bridge = ProtocolBridge(config)

        protocol = bridge._detect_protocol("unknown-target")
        assert protocol == Protocol.MCP

    @pytest.mark.asyncio
    async def test_invoke_external_mcp(self):
        """MCP invocation routes to local or remote server."""
        bridge = ProtocolBridge()

        result = await bridge.invoke_external(
            target="mcp://server/tool",
            task="test task",
            protocol=Protocol.MCP,
        )

        assert result["protocol"] == "mcp"
        # With local AragoraMCPServer available, status is "success" or "error"
        assert result["status"] in ("success", "error")

    @pytest.mark.asyncio
    async def test_invoke_external_a2a_no_client(self):
        """A2A invocation fails without client."""
        bridge = ProtocolBridge()
        bridge._a2a_client = None

        with pytest.raises(RuntimeError, match="A2A client not initialized"):
            await bridge.invoke_external(
                target="test-agent",
                task="test task",
                protocol=Protocol.A2A,
            )

    @pytest.mark.asyncio
    async def test_invoke_external_a2a_with_client(self):
        """A2A invocation uses client."""
        bridge = ProtocolBridge()

        # Mock the A2A client
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"status": "success", "output": "result"}
        mock_client.invoke = AsyncMock(return_value=mock_result)
        bridge._a2a_client = mock_client

        result = await bridge.invoke_external(
            target="test-agent",
            task="test task",
            protocol=Protocol.A2A,
        )

        assert result["status"] == "success"
        mock_client.invoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_external_with_context(self):
        """Context is passed to A2A invocation."""
        bridge = ProtocolBridge()

        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"status": "success"}
        mock_client.invoke = AsyncMock(return_value=mock_result)
        bridge._a2a_client = mock_client

        context = [
            {"type": "text", "content": "Context 1"},
            {"type": "code", "content": "print('hello')"},
        ]

        await bridge.invoke_external(
            target="test-agent",
            task="test task",
            context=context,
            protocol=Protocol.A2A,
        )

        call_args = mock_client.invoke.call_args
        assert len(call_args.kwargs["context"]) == 2

    @pytest.mark.asyncio
    async def test_stream_invoke_unsupported(self):
        """Streaming returns error for unsupported targets."""
        bridge = ProtocolBridge()

        events = []
        async for event in bridge.stream_invoke(
            target="mcp://server/tool",
            task="test task",
            protocol=Protocol.MCP,
        ):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "error"

    @pytest.mark.asyncio
    async def test_stream_invoke_a2a(self):
        """Streaming works for A2A with client."""
        bridge = ProtocolBridge()

        # Mock streaming
        async def mock_stream(*args, **kwargs):
            yield {"type": "chunk", "data": "part1"}
            yield {"type": "chunk", "data": "part2"}
            yield {"type": "done"}

        mock_client = MagicMock()
        mock_client.stream_invoke = mock_stream
        bridge._a2a_client = mock_client

        events = []
        async for event in bridge.stream_invoke(
            target="test-agent",
            task="test task",
            protocol=Protocol.A2A,
        ):
            events.append(event)

        assert len(events) == 3
        assert events[0]["type"] == "chunk"
        assert events[2]["type"] == "done"

    def test_wrap_aragora_agent(self):
        """Aragora agents are wrapped as A2A cards."""
        bridge = ProtocolBridge()

        mock_agent = MagicMock()
        mock_agent.name = "claude"
        mock_agent.role = "analyst"

        card = bridge.wrap_aragora_agent(mock_agent)

        assert card.name == "aragora-claude"
        assert "analyst" in card.description
        assert "aragora" in card.tags

    def test_wrap_aragora_agent_with_capabilities(self):
        """Custom capabilities can be specified."""
        from aragora.protocols.a2a import AgentCapability

        bridge = ProtocolBridge()

        mock_agent = MagicMock()
        mock_agent.name = "codex"
        mock_agent.role = "coder"

        card = bridge.wrap_aragora_agent(
            mock_agent,
            capabilities=[AgentCapability.CODE_REVIEW, AgentCapability.REASONING],
        )

        assert AgentCapability.CODE_REVIEW in card.capabilities
        assert AgentCapability.REASONING in card.capabilities

    def test_register_external_agent(self):
        """External agents can be registered."""
        bridge = ProtocolBridge()

        mock_agent = MagicMock()
        mock_agent.name = "external-agent"

        bridge.register_external_agent(mock_agent)

        assert "external-agent" in bridge._external_agents

    def test_register_external_agent_with_client(self):
        """Registration also updates A2A client."""
        bridge = ProtocolBridge()

        mock_client = MagicMock()
        bridge._a2a_client = mock_client

        mock_agent = MagicMock()
        mock_agent.name = "external-agent"

        bridge.register_external_agent(mock_agent)

        mock_client.register_agent.assert_called_once_with(mock_agent)

    def test_list_external_agents(self):
        """External agents can be listed."""
        bridge = ProtocolBridge()

        agent1 = MagicMock()
        agent1.name = "agent1"
        agent1.supports_capability.return_value = True

        agent2 = MagicMock()
        agent2.name = "agent2"
        agent2.supports_capability.return_value = False

        bridge._external_agents = {"agent1": agent1, "agent2": agent2}

        all_agents = bridge.list_external_agents()
        assert len(all_agents) == 2

    def test_list_external_agents_by_capability(self):
        """Agents can be filtered by capability."""
        from aragora.protocols.a2a import AgentCapability

        bridge = ProtocolBridge()

        agent1 = MagicMock()
        agent1.name = "agent1"
        agent1.supports_capability.return_value = True

        agent2 = MagicMock()
        agent2.name = "agent2"
        agent2.supports_capability.return_value = False

        bridge._external_agents = {"agent1": agent1, "agent2": agent2}

        filtered = bridge.list_external_agents(capability=AgentCapability.REASONING)
        assert len(filtered) == 1

    def test_get_a2a_server(self):
        """A2A server is accessible."""
        bridge = ProtocolBridge()
        assert bridge.get_a2a_server() is None

        mock_server = MagicMock()
        bridge._a2a_server = mock_server
        assert bridge.get_a2a_server() is mock_server

    @pytest.mark.asyncio
    async def test_handle_incoming_task_no_server(self):
        """Incoming tasks fail without server."""
        from aragora.protocols.a2a import TaskRequest, TaskStatus

        bridge = ProtocolBridge()
        bridge._a2a_server = None

        request = TaskRequest(
            task_id="task1",
            instruction="test task instruction",
        )

        result = await bridge.handle_incoming_task(request)

        assert result.status == TaskStatus.FAILED
        assert "not initialized" in result.error_message

    @pytest.mark.asyncio
    async def test_handle_incoming_task_with_server(self):
        """Incoming tasks are handled by server."""
        from aragora.protocols.a2a import TaskRequest, TaskStatus

        bridge = ProtocolBridge()

        mock_server = MagicMock()
        mock_result = MagicMock()
        mock_result.status = TaskStatus.COMPLETED
        mock_server.handle_task = AsyncMock(return_value=mock_result)
        bridge._a2a_server = mock_server

        request = TaskRequest(
            task_id="task1",
            instruction="test task instruction",
        )

        result = await bridge.handle_incoming_task(request)

        assert result.status == TaskStatus.COMPLETED
        mock_server.handle_task.assert_called_once_with(request)


class TestGlobalBridge:
    """Tests for global bridge accessor."""

    def test_get_protocol_bridge_returns_instance(self):
        """get_protocol_bridge returns a bridge."""
        import aragora.server.protocol_bridge as br

        br._bridge = None

        bridge = get_protocol_bridge()
        assert isinstance(bridge, ProtocolBridge)

    def test_get_protocol_bridge_returns_singleton(self):
        """get_protocol_bridge returns same instance."""
        import aragora.server.protocol_bridge as br

        br._bridge = None

        b1 = get_protocol_bridge()
        b2 = get_protocol_bridge()
        assert b1 is b2

    def test_get_protocol_bridge_with_config(self):
        """Config is used for initial creation."""
        import aragora.server.protocol_bridge as br

        br._bridge = None

        config = BridgeConfig(enable_mcp=False)
        bridge = get_protocol_bridge(config)

        assert bridge.config.enable_mcp is False
