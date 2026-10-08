"""
Tests for A2A Protocol Server.

Tests cover:
- Server initialization
- Agent registration and listing
- Task handling (no capability, unknown capability)
- Task status and cancellation
- OpenAPI spec generation
- TaskHandler creation
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.protocols.a2a.types import (
    AgentCapability,
    AgentCard,
    TaskRequest,
    TaskResult,
    TaskStatus,
)
from aragora.server.a2a_runtime import A2AServer, TaskHandler


# ============================================================================
# TaskHandler Tests
# ============================================================================


class TestTaskHandler:
    """Tests for TaskHandler."""

    def test_basic_creation(self):
        handler = TaskHandler(
            capability=AgentCapability.DEBATE,
            handler=AsyncMock(),
        )
        assert handler.capability == AgentCapability.DEBATE
        assert handler.stream_handler is None

    def test_with_stream_handler(self):
        handler = TaskHandler(
            capability=AgentCapability.DEBATE,
            handler=AsyncMock(),
            stream_handler=AsyncMock(),
        )
        assert handler.stream_handler is not None


# ============================================================================
# Server Initialization Tests
# ============================================================================


class TestServerInit:
    """Tests for A2AServer initialization."""

    def test_default_config(self):
        server = A2AServer()
        assert server._host == "0.0.0.0"
        assert server._port == 8766
        assert server._max_concurrent == 10

    def test_custom_config(self):
        server = A2AServer(host="127.0.0.1", port=9000, max_concurrent_tasks=5)
        assert server._host == "127.0.0.1"
        assert server._port == 9000
        assert server._max_concurrent == 5

    def test_registers_aragora_agents(self):
        """Built-in Aragora agents are registered on init."""
        server = A2AServer()
        agents = server.list_agents()
        assert len(agents) >= 4  # debate-orchestrator, audit, gauntlet, research

    def test_registers_built_in_handlers(self):
        """Built-in capability handlers are registered."""
        server = A2AServer()
        assert AgentCapability.DEBATE in server._handlers
        assert AgentCapability.AUDIT in server._handlers
        assert AgentCapability.CRITIQUE in server._handlers
        assert AgentCapability.RESEARCH in server._handlers


# ============================================================================
# Agent Management Tests
# ============================================================================


class TestAgentManagement:
    """Tests for agent registration and listing."""

    def test_register_custom_agent(self):
        server = A2AServer()
        agent = AgentCard(name="custom-agent", description="Custom")
        server.register_agent(agent)
        assert server.get_agent("custom-agent") is agent

    def test_get_agent_not_found(self):
        server = A2AServer()
        assert server.get_agent("nonexistent") is None

    def test_list_agents(self):
        server = A2AServer()
        agents = server.list_agents()
        assert isinstance(agents, list)
        assert all(isinstance(a, AgentCard) for a in agents)


# ============================================================================
# Handler Registration Tests
# ============================================================================


class TestHandlerRegistration:
    """Tests for handler registration."""

    def test_register_handler(self):
        server = A2AServer()
        mock_handler = AsyncMock()
        server.register_handler(AgentCapability.VERIFICATION, mock_handler)
        assert AgentCapability.VERIFICATION in server._handlers

    def test_register_handler_with_stream(self):
        server = A2AServer()
        mock_handler = AsyncMock()
        mock_stream = AsyncMock()
        server.register_handler(
            AgentCapability.VERIFICATION,
            mock_handler,
            stream_handler=mock_stream,
        )
        handler = server._handlers[AgentCapability.VERIFICATION]
        assert handler.stream_handler is not None


# ============================================================================
# Task Handling Tests
# ============================================================================


class TestTaskHandling:
    """Tests for task handling."""

    @pytest.mark.asyncio
    async def test_handle_task_no_capability_match(self):
        """Task with unknown capability uses first available handler."""
        server = A2AServer()
        request = TaskRequest(
            task_id="t_test",
            instruction="Test task",
            capability=AgentCapability.SYNTHESIS,
        )

        # SYNTHESIS has no handler - should fallback
        # The server tries to find any handler when no match
        # This test mainly checks it doesn't crash
        result = await server.handle_task(request)
        assert result.task_id == "t_test"

    @pytest.mark.asyncio
    async def test_handle_task_with_custom_handler(self):
        """Task uses custom registered handler."""
        server = A2AServer()

        async def custom_handler(req: TaskRequest) -> TaskResult:
            return TaskResult(
                task_id=req.task_id,
                agent_name="custom-agent",
                status=TaskStatus.COMPLETED,
                output="Custom result",
            )

        server.register_handler(AgentCapability.VERIFICATION, custom_handler)

        request = TaskRequest(
            task_id="t_custom",
            instruction="Verify this",
            capability=AgentCapability.VERIFICATION,
        )
        result = await server.handle_task(request)
        assert result.status == TaskStatus.COMPLETED
        assert result.output == "Custom result"

    @pytest.mark.asyncio
    async def test_handle_task_exception(self):
        """Handler exception results in FAILED status."""
        server = A2AServer()

        async def failing_handler(req: TaskRequest) -> TaskResult:
            raise RuntimeError("Handler exploded")

        server.register_handler(AgentCapability.VERIFICATION, failing_handler)

        request = TaskRequest(
            task_id="t_fail",
            instruction="This will fail",
            capability=AgentCapability.VERIFICATION,
        )
        result = await server.handle_task(request)
        assert result.status == TaskStatus.FAILED
        assert "Handler exploded" in result.error_message


# ============================================================================
# Task Status and Cancel Tests
# ============================================================================


class TestTaskStatusCancel:
    """Tests for task status and cancellation."""

    @pytest.mark.asyncio
    async def test_get_task_status(self):
        """Task status is tracked after handling."""
        server = A2AServer()

        async def handler(req: TaskRequest) -> TaskResult:
            return TaskResult(
                task_id=req.task_id,
                agent_name="test",
                status=TaskStatus.COMPLETED,
            )

        server.register_handler(AgentCapability.VERIFICATION, handler)

        request = TaskRequest(
            task_id="t_tracked",
            instruction="Track this",
            capability=AgentCapability.VERIFICATION,
        )
        await server.handle_task(request)

        status = server.get_task_status("t_tracked")
        assert status is not None
        assert status.status == TaskStatus.COMPLETED

    def test_get_task_status_not_found(self):
        """Unknown task returns None."""
        server = A2AServer()
        assert server.get_task_status("unknown") is None

    @pytest.mark.asyncio
    async def test_cancel_running_task(self):
        """Running tasks can be cancelled."""
        server = A2AServer()

        # Manually add a running task
        async with server._task_lock:
            server._tasks["t_cancel"] = TaskResult(
                task_id="t_cancel",
                agent_name="test",
                status=TaskStatus.RUNNING,
                started_at=datetime.now(),
            )

        result = await server.cancel_task("t_cancel")
        assert result is True
        assert server._tasks["t_cancel"].status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_unknown_task(self):
        """Cancelling unknown task returns False."""
        server = A2AServer()
        result = await server.cancel_task("nonexistent")
        assert result is False


# ============================================================================
# Stream Task Tests
# ============================================================================


class TestStreamTask:
    """Tests for streaming task handling."""

    @pytest.mark.asyncio
    async def test_stream_no_handler(self):
        """Stream with no handler returns error."""
        server = A2AServer()
        # Clear all handlers
        server._handlers.clear()

        request = TaskRequest(
            task_id="t_stream",
            instruction="Stream this",
            capability=AgentCapability.VERIFICATION,
        )

        events = []
        async for event in server.stream_task(request):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "error"


# ============================================================================
# OpenAPI Spec Tests
# ============================================================================


class TestOpenAPISpec:
    """Tests for OpenAPI specification generation."""

    def test_spec_structure(self):
        server = A2AServer()
        spec = server.get_openapi_spec()
        assert spec["openapi"] == "3.0.0"
        assert "info" in spec
        assert "paths" in spec

    def test_spec_paths(self):
        server = A2AServer()
        spec = server.get_openapi_spec()
        assert "/agents" in spec["paths"]
        assert "/tasks" in spec["paths"]
        assert "/tasks/{task_id}" in spec["paths"]

    def test_spec_info(self):
        server = A2AServer()
        spec = server.get_openapi_spec()
        assert "Aragora" in spec["info"]["title"]
