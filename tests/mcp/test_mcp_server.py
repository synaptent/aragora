"""
Tests for the Aragora MCP Server.

Tests cover:
- Server initialization
- Tool listing and schema validation
- Resource listing and templates
- Tool execution with mocked dependencies
- Error handling
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any


from mcp.types import (
    Tool,
    TextContent,
    Resource,
    ResourceTemplate,
    ListToolsRequest,
    CallToolRequest,
    CallToolRequestParams,
    ListResourcesRequest,
    ListResourceTemplatesRequest,
    ReadResourceRequest,
    ReadResourceRequestParams,
)

# Import orchestrator module to make it available for patching
# This is required because aragora.debate uses lazy imports via __getattr__
# and patch() needs the submodule to be loaded first
import aragora.debate.orchestrator  # noqa: F401

# Import MAX_ROUNDS for test assertions
from aragora.config import MAX_ROUNDS


async def _get_tools(server):
    """Helper to get tools using the correct MCP API."""
    handler = server.server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest())
    # Handle both ServerResult wrapper and direct result
    if hasattr(result, "root"):
        return result.root.tools
    return result.tools


async def _get_resources(server):
    """Helper to get resources using the correct MCP API."""
    handler = server.server.request_handlers[ListResourcesRequest]
    result = await handler(ListResourcesRequest())
    if hasattr(result, "root"):
        return result.root.resources
    return result.resources


async def _get_resource_templates(server):
    """Helper to get resource templates using the correct MCP API."""
    handler = server.server.request_handlers[ListResourceTemplatesRequest]
    result = await handler(ListResourceTemplatesRequest())
    if hasattr(result, "root"):
        return result.root.resourceTemplates
    return result.resourceTemplates


async def _read_resource(server, uri: str):
    """Helper to read a resource using the correct MCP API."""
    handler = server.server.request_handlers[ReadResourceRequest]
    result = await handler(ReadResourceRequest(params=ReadResourceRequestParams(uri=uri)))  # type: ignore[arg-type]
    if hasattr(result, "root"):
        contents = result.root.contents
    else:
        contents = result.contents
    return contents[0].text if contents else ""


async def _call_tool(server, name: str, arguments: dict):
    """Helper to call a tool using the correct MCP API."""
    handler = server.server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(params=CallToolRequestParams(name=name, arguments=arguments))
    )
    if hasattr(result, "root"):
        return result.root.content
    return result.content


class TestAragoraMCPServerInitialization:
    """Test server initialization."""

    def test_server_creation_without_mcp_raises(self):
        """Test that server raises ImportError when MCP_AVAILABLE is False."""
        from aragora.mcp import server as mcp_server

        # Store original value
        original_available = mcp_server.MCP_AVAILABLE
        mcp_server.MCP_AVAILABLE = False

        try:
            with pytest.raises(ImportError, match="MCP package not installed"):
                mcp_server.AragoraMCPServer()
        finally:
            mcp_server.MCP_AVAILABLE = original_available

    def test_server_creation_with_mcp(self):
        """Test successful server creation when MCP is available."""
        from aragora.mcp.server import AragoraMCPServer

        server = AragoraMCPServer()

        assert server.server is not None
        assert server._debates_cache == {}

    def test_server_has_correct_name(self):
        """Test server is registered with correct name."""
        from aragora.mcp.server import AragoraMCPServer

        server = AragoraMCPServer()

        # The Server class stores the name
        assert server.server.name == "aragora"


class TestMCPToolListing:
    """Test tool listing functionality."""

    @pytest.fixture
    def server(self):
        """Create an MCP server instance."""
        from aragora.mcp.server import AragoraMCPServer

        return AragoraMCPServer()

    @pytest.mark.asyncio
    async def test_list_tools_returns_expected_tools(self, server):
        """Test that list_tools returns expected core tools."""
        tools = await _get_tools(server)

        # Server exposes many tools; verify core ones exist
        tool_names = {t.name for t in tools}
        core_tools = {"run_debate", "run_gauntlet", "list_agents", "get_debate"}
        assert core_tools.issubset(tool_names), f"Missing tools: {core_tools - tool_names}"
        assert len(tools) >= 4  # At least the core tools

    @pytest.mark.asyncio
    async def test_run_debate_tool_schema(self, server):
        """Test run_debate tool has correct schema."""
        tools = await _get_tools(server)

        run_debate = next(t for t in tools if t.name == "run_debate")

        assert run_debate.inputSchema["type"] == "object"
        assert "question" in run_debate.inputSchema["properties"]
        assert "agents" in run_debate.inputSchema["properties"]
        assert "rounds" in run_debate.inputSchema["properties"]
        assert "consensus" in run_debate.inputSchema["properties"]
        assert run_debate.inputSchema["required"] == ["question"]

    @pytest.mark.asyncio
    async def test_run_gauntlet_tool_schema(self, server):
        """Test run_gauntlet tool has correct schema."""
        tools = await _get_tools(server)

        run_gauntlet = next(t for t in tools if t.name == "run_gauntlet")

        assert run_gauntlet.inputSchema["type"] == "object"
        assert "content" in run_gauntlet.inputSchema["properties"]
        assert "content_type" in run_gauntlet.inputSchema["properties"]
        assert "profile" in run_gauntlet.inputSchema["properties"]
        assert run_gauntlet.inputSchema["required"] == ["content"]

    @pytest.mark.asyncio
    async def test_list_agents_tool_schema(self, server):
        """Test list_agents tool has minimal schema."""
        tools = await _get_tools(server)

        list_agents = next(t for t in tools if t.name == "list_agents")

        assert list_agents.inputSchema["type"] == "object"
        assert list_agents.inputSchema["properties"] == {}

    @pytest.mark.asyncio
    async def test_get_debate_tool_schema(self, server):
        """Test get_debate tool has correct schema."""
        tools = await _get_tools(server)

        get_debate = next(t for t in tools if t.name == "get_debate")

        assert "debate_id" in get_debate.inputSchema["properties"]
        assert get_debate.inputSchema["required"] == ["debate_id"]


class TestMCPResourceListing:
    """Test resource listing functionality."""

    @pytest.fixture
    def server(self):
        """Create an MCP server instance."""
        from aragora.mcp.server import AragoraMCPServer

        return AragoraMCPServer()

    @pytest.mark.asyncio
    async def test_list_resources_empty_initially(self, server):
        """Test that resources list is empty initially."""
        resources = await _get_resources(server)

        assert resources == []

    @pytest.mark.asyncio
    async def test_list_resources_after_debate(self, server):
        """Test that resources include cached debates."""
        # Add a debate to the cache
        server._debates_cache["test_123"] = {
            "debate_id": "test_123",
            "task": "Test debate question",
            "timestamp": "2026-01-11 12:00:00",
        }

        resources = await _get_resources(server)

        assert len(resources) == 1
        assert str(resources[0].uri) == "debate://test_123"
        assert "Test debate" in resources[0].name

    @pytest.mark.asyncio
    async def test_list_resource_templates(self, server):
        """Test resource templates are listed."""
        templates = await _get_resource_templates(server)

        # Server exposes multiple resource templates now
        assert len(templates) >= 1
        template_uris = [t.uriTemplate for t in templates]
        assert "debate://{debate_id}" in template_uris
        assert templates[0].mimeType == "application/json"


class TestMCPResourceReading:
    """Test resource reading functionality."""

    @pytest.fixture
    def server(self):
        """Create an MCP server instance."""
        from aragora.mcp.server import AragoraMCPServer

        return AragoraMCPServer()

    @pytest.mark.asyncio
    async def test_read_cached_debate(self, server):
        """Test reading a cached debate resource."""
        debate_data = {
            "debate_id": "test_456",
            "task": "What is the meaning of life?",
            "final_answer": "42",
        }
        server._debates_cache["test_456"] = debate_data

        result = await _read_resource(server, "debate://test_456")

        parsed = json.loads(result)
        assert parsed["debate_id"] == "test_456"
        assert parsed["final_answer"] == "42"

    @pytest.mark.asyncio
    async def test_read_missing_debate(self, server):
        """Test reading a non-existent debate resource."""
        result = await _read_resource(server, "debate://missing")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "not found" in parsed["error"]

    @pytest.mark.asyncio
    async def test_read_unknown_resource_type(self, server):
        """Test reading an unknown resource type."""
        result = await _read_resource(server, "unknown://something")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "Unknown resource" in parsed["error"]


class TestMCPToolExecution:
    """Test tool execution with mocked dependencies."""

    @pytest.fixture
    def server(self):
        """Create an MCP server instance."""
        from aragora.mcp.server import AragoraMCPServer

        return AragoraMCPServer()

    @pytest.mark.asyncio
    async def test_list_agents_tool_execution(self, server):
        """Test list_agents tool returns agents list."""
        with patch("aragora.agents.base.list_available_agents") as mock_list:
            mock_list.return_value = {
                "anthropic-api": {"type": "API"},
                "openai-api": {"type": "API"},
                "gemini": {"type": "API"},
            }

            result = await server._list_agents()

            assert result["agents"] == ["anthropic-api", "openai-api", "gemini"]
            assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_list_agents_empty_on_error(self, server):
        """Test list_agents fails closed with an empty list and error when the registry errors."""
        with patch("aragora.agents.base.list_available_agents") as mock_list:
            mock_list.side_effect = Exception("Registry unavailable")

            result = await server._list_agents()

            assert "agents" in result
            assert result["agents"] == []
            assert "error" in result

    @pytest.mark.asyncio
    async def test_get_debate_from_cache(self, server):
        """Test get_debate retrieves from cache."""
        server._debates_cache["cached_123"] = {
            "debate_id": "cached_123",
            "final_answer": "Cached result",
        }

        result = await server._get_debate({"debate_id": "cached_123"})

        assert result["debate_id"] == "cached_123"
        assert result["final_answer"] == "Cached result"

    @pytest.mark.asyncio
    async def test_get_debate_missing_id(self, server):
        """Test get_debate with missing ID returns error."""
        result = await server._get_debate({})

        assert "error" in result
        assert "required" in result["error"]

    @pytest.mark.asyncio
    async def test_get_debate_not_found(self, server):
        """Test get_debate returns error for non-existent debate."""
        storage_db = MagicMock()
        storage_db.get.return_value = None
        with patch("aragora.storage.debate_storage.get_debates_db") as mock_db:
            mock_db.return_value = storage_db

            result = await server._get_debate({"debate_id": "nonexistent"})

            assert "error" in result
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_run_debate_missing_question(self, server):
        """Test run_debate with missing question returns error."""
        result = await server._run_debate({})

        assert "error" in result
        assert "Question is required" in result["error"]

    @pytest.mark.asyncio
    async def test_run_debate_no_valid_agents(self, server):
        """Test run_debate returns an error when a requested agent can't be created."""
        with patch("aragora.agents.base.create_agent") as mock_create:
            mock_create.side_effect = Exception("No API key")

            result = await server._run_debate(
                {
                    "question": "Test question",
                    "agents": "fake-agent",
                }
            )

            assert "error" in result
            assert "Invalid agent selection" in result["error"]

    @pytest.mark.asyncio
    async def test_run_gauntlet_missing_content(self, server):
        """Test run_gauntlet with missing content returns error."""
        result = await server._run_gauntlet({})

        assert "error" in result
        assert "Content is required" in result["error"]


class TestMCPToolCallHandler:
    """Test the unified tool call handler."""

    @pytest.fixture
    def server(self):
        """Create an MCP server instance."""
        from aragora.mcp.server import AragoraMCPServer

        return AragoraMCPServer()

    @pytest.mark.asyncio
    async def test_call_tool_unknown_tool(self, server):
        """Test calling unknown tool returns error."""
        result = await _call_tool(server, "unknown_tool", {})

        assert len(result) == 1
        parsed = json.loads(result[0].text)
        assert "error" in parsed
        assert "Unknown tool" in parsed["error"]

    @pytest.mark.asyncio
    async def test_call_tool_handles_exceptions(self, server):
        """Test tool call handler catches exceptions and fails closed."""
        # Mock list_available_agents to raise an exception
        # This tests that the tool properly catches errors and returns an error result
        with patch(
            "aragora.agents.base.list_available_agents",
            side_effect=RuntimeError("Test error"),
        ):
            result = await _call_tool(server, "list_agents", {})

            # When list_available_agents fails, list_agents_tool returns an empty list + error
            assert len(result) == 1
            parsed = json.loads(result[0].text)
            assert "agents" in parsed
            assert parsed["agents"] == []
            assert "error" in parsed

    @pytest.mark.asyncio
    async def test_call_tool_returns_text_content(self, server):
        """Test tool calls return TextContent objects."""
        with patch("aragora.agents.base.list_available_agents") as mock_list:
            # Return a dict since list_available_agents returns a dict
            mock_list.return_value = {"test-agent": {"type": "API"}}

            result = await _call_tool(server, "list_agents", {})

            assert len(result) == 1
            assert result[0].type == "text"
            parsed = json.loads(result[0].text)
            assert parsed["agents"] == ["test-agent"]


class TestMCPServerRun:
    """Test server run functionality."""

    @pytest.mark.asyncio
    async def test_run_server_without_mcp_exits(self):
        """Test run_server exits with error when MCP unavailable."""
        from aragora.mcp import server as mcp_server

        original_available = mcp_server.MCP_AVAILABLE
        mcp_server.MCP_AVAILABLE = False

        try:
            with pytest.raises(SystemExit) as exc_info:
                await mcp_server.run_server()
            assert exc_info.value.code == 1
        finally:
            mcp_server.MCP_AVAILABLE = original_available


class TestMCPDebateCaching:
    """Test debate caching behavior."""

    @pytest.fixture
    def server(self):
        """Create an MCP server instance."""
        from aragora.mcp.server import AragoraMCPServer

        return AragoraMCPServer()

    @pytest.mark.asyncio
    async def test_debate_cached_after_run(self, server):
        """Test that debates are cached after successful run."""
        # Create mock result
        mock_result = MagicMock()
        mock_result.final_answer = "Test answer"
        mock_result.consensus_reached = True
        mock_result.confidence = 0.9
        mock_result.rounds_used = 3

        # Create mock agent
        mock_agent = MagicMock()
        mock_agent.name = "test_agent"

        with (
            patch("aragora.agents.base.create_agent") as mock_create,
            patch("aragora.debate.orchestrator.Arena") as mock_arena,
            patch("aragora.core.Environment"),
        ):
            mock_create.return_value = mock_agent
            mock_arena_instance = MagicMock()
            mock_arena_instance.run = AsyncMock(return_value=mock_result)
            mock_arena.return_value = mock_arena_instance

            result = await server._run_debate(
                {
                    "question": "Test question?",
                    "agents": "test-agent",
                    "rounds": 3,
                }
            )

            # Verify result structure
            assert "debate_id" in result
            assert result["debate_id"].startswith("mcp_")
            assert result["final_answer"] == "Test answer"

            # Verify caching
            debate_id = result["debate_id"]
            assert debate_id in server._debates_cache
            assert server._debates_cache[debate_id]["task"] == "Test question?"

    @pytest.mark.asyncio
    async def test_debate_id_format(self, server):
        """Test debate ID has correct format."""
        mock_result = MagicMock()
        mock_result.final_answer = "Answer"
        mock_result.consensus_reached = False
        mock_result.confidence = 0.5
        mock_result.rounds_used = 1

        mock_agent = MagicMock()
        mock_agent.name = "agent"

        with (
            patch("aragora.agents.base.create_agent") as mock_create,
            patch("aragora.debate.orchestrator.Arena") as mock_arena,
            patch("aragora.core.Environment"),
        ):
            mock_create.return_value = mock_agent
            mock_arena_instance = MagicMock()
            mock_arena_instance.run = AsyncMock(return_value=mock_result)
            mock_arena.return_value = mock_arena_instance

            result = await server._run_debate({"question": "Q?"})

            assert result["debate_id"].startswith("mcp_")
            assert len(result["debate_id"]) == 12  # "mcp_" + 8 hex chars


class TestMCPRoundsValidation:
    """Test rounds parameter validation."""

    @pytest.fixture
    def server(self):
        """Create an MCP server instance."""
        from aragora.mcp.server import AragoraMCPServer

        return AragoraMCPServer()

    @pytest.mark.asyncio
    async def test_rounds_clamped_to_minimum(self, server):
        """Test rounds below 1 are clamped to 1."""
        mock_result = MagicMock()
        mock_result.final_answer = "A"
        mock_result.consensus_reached = True
        mock_result.confidence = 1.0
        mock_result.rounds_used = 1

        mock_agent = MagicMock()
        mock_agent.name = "a"

        with (
            patch("aragora.agents.base.create_agent") as mock_create,
            patch("aragora.debate.orchestrator.Arena") as mock_arena,
            patch("aragora.debate.orchestrator.DebateProtocol") as mock_protocol,
            patch("aragora.core.Environment") as mock_env,
        ):
            mock_create.return_value = mock_agent
            mock_arena_instance = MagicMock()
            mock_arena_instance.run = AsyncMock(return_value=mock_result)
            mock_arena.return_value = mock_arena_instance

            await server._run_debate({"question": "Q?", "rounds": -5})

            # Check that Environment was called with rounds=1
            mock_env.assert_called_once()
            call_kwargs = mock_env.call_args[1]
            assert call_kwargs["max_rounds"] == 1

    @pytest.mark.asyncio
    async def test_rounds_clamped_to_maximum(self, server):
        """Test rounds above 10 are clamped to 10."""
        mock_result = MagicMock()
        mock_result.final_answer = "A"
        mock_result.consensus_reached = True
        mock_result.confidence = 1.0
        mock_result.rounds_used = 10

        mock_agent = MagicMock()
        mock_agent.name = "a"

        with (
            patch("aragora.agents.base.create_agent") as mock_create,
            patch("aragora.debate.orchestrator.Arena") as mock_arena,
            patch("aragora.debate.orchestrator.DebateProtocol") as mock_protocol,
            patch("aragora.core.Environment") as mock_env,
        ):
            mock_create.return_value = mock_agent
            mock_arena_instance = MagicMock()
            mock_arena_instance.run = AsyncMock(return_value=mock_result)
            mock_arena.return_value = mock_arena_instance

            await server._run_debate({"question": "Q?", "rounds": 100})

            # Check that Environment was called with rounds clamped to MAX_ROUNDS
            mock_env.assert_called_once()
            call_kwargs = mock_env.call_args[1]
            assert call_kwargs["max_rounds"] == MAX_ROUNDS


# ===========================================================================
# Rate Limiting Tests
# ===========================================================================


class TestMCPRateLimiting:
    """Tests for rate limiting functionality."""

    def test_rate_limiter_allows_within_limit(self):
        """Test rate limiter allows requests within limit."""
        from aragora.mcp.server import RateLimiter

        limiter = RateLimiter({"test_tool": 5})

        # First 5 requests should pass
        for _ in range(5):
            allowed, error = limiter.check("test_tool")
            assert allowed is True
            assert error is None

    def test_rate_limiter_blocks_over_limit(self):
        """Test rate limiter blocks requests over limit."""
        from aragora.mcp.server import RateLimiter

        limiter = RateLimiter({"test_tool": 3})

        # Use up the limit
        for _ in range(3):
            limiter.check("test_tool")

        # Next request should be blocked
        allowed, error = limiter.check("test_tool")
        assert allowed is False
        assert "Rate limit exceeded" in error

    def test_rate_limiter_get_remaining(self):
        """Test rate limiter returns correct remaining count."""
        from aragora.mcp.server import RateLimiter

        limiter = RateLimiter({"test_tool": 10})

        assert limiter.get_remaining("test_tool") == 10

        limiter.check("test_tool")
        assert limiter.get_remaining("test_tool") == 9

        for _ in range(5):
            limiter.check("test_tool")
        assert limiter.get_remaining("test_tool") == 4


# ===========================================================================
# Input Validation Tests
# ===========================================================================


class TestMCPInputValidation:
    """Tests for input validation."""

    @pytest.fixture
    def server(self):
        """Create an MCP server instance."""
        from aragora.mcp.server import AragoraMCPServer

        return AragoraMCPServer()

    def test_validate_question_length(self, server):
        """Test validation rejects overly long questions."""
        long_question = "x" * 15000  # Over MAX_QUESTION_LENGTH

        error = server._validate_input("run_debate", {"question": long_question})

        assert error is not None
        assert "maximum length" in error.lower()

    def test_validate_content_length(self, server):
        """Test validation rejects overly long content."""
        long_content = "x" * 150000

        # MAX_CONTENT_LENGTH is 100MB; patch it to a smaller value for this test
        with patch("aragora.mcp.server.MAX_CONTENT_LENGTH", 100000):
            error = server._validate_input("run_gauntlet", {"content": long_content})

        assert error is not None
        assert "maximum length" in error.lower()

    def test_validate_query_length(self, server):
        """Test validation rejects overly long queries."""
        long_query = "x" * 1500  # Over MAX_QUERY_LENGTH

        error = server._validate_input("search_debates", {"query": long_query})

        assert error is not None
        assert "maximum length" in error.lower()

    def test_validate_rounds_type(self, server):
        """Test validation rejects invalid rounds type."""
        error = server._validate_input("run_debate", {"question": "Q?", "rounds": "five"})

        assert error is not None
        assert "rounds" in error.lower()

    def test_validate_valid_input_passes(self, server):
        """Test validation passes for valid input."""
        error = server._validate_input("run_debate", {"question": "What is 2+2?", "rounds": 3})

        assert error is None

    def test_sanitize_strips_whitespace(self, server):
        """Test sanitization strips whitespace from strings."""
        args = {"question": "  What is 2+2?  ", "rounds": 3}

        sanitized = server._sanitize_arguments(args)

        assert sanitized["question"] == "What is 2+2?"
        assert sanitized["rounds"] == 3
