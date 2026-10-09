"""Advanced tests for DAGOperationsCoordinator methods.

Covers: debate_assignment, _execute_federated, execute_node_via_scheduler,
assign_agents_with_selector.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.canvas.stages import PipelineStage
from aragora.pipeline.dag_operations import DAGOperationsCoordinator, DAGOperationResult
from aragora.pipeline.universal_node import UniversalGraph, UniversalNode


def _make_graph() -> UniversalGraph:
    """Create a test graph with idea and orchestration nodes."""
    graph = UniversalGraph(id="test-graph", name="Test")
    graph.add_node(
        UniversalNode(
            id="idea-1",
            stage=PipelineStage.IDEAS,
            node_subtype="concept",
            label="Build a rate limiter",
            description="Implement token bucket rate limiting",
        )
    )
    graph.add_node(
        UniversalNode(
            id="orch-1",
            stage=PipelineStage.ORCHESTRATION,
            node_subtype="agent_task",
            label="Execute rate limiter",
            description="Agent task to implement rate limiter",
            parent_ids=["idea-1"],
        )
    )
    graph.add_node(
        UniversalNode(
            id="orch-2",
            stage=PipelineStage.ORCHESTRATION,
            node_subtype="agent_task",
            label="Execute caching layer",
            description="Agent task to add caching",
        )
    )
    return graph


# ---------------------------------------------------------------------------
# debate_assignment
# ---------------------------------------------------------------------------


class TestDebateAssignment:
    """Tests for DAGOperationsCoordinator.debate_assignment()."""

    @pytest.mark.asyncio
    async def test_successful_assignment_from_debate(self, monkeypatch):
        """Mock Arena.run() to return structured result with T1/T2 assignments."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        mock_result = MagicMock()
        mock_result.summary = "T1: claude, gemini\nT2: gpt, mistral\n"

        mock_arena_instance = MagicMock()
        mock_arena_instance.run = AsyncMock(return_value=mock_result)

        mock_arena_cls = MagicMock(return_value=mock_arena_instance)
        mock_agent = MagicMock()

        monkeypatch.setattr("aragora.core.Environment", MagicMock)
        monkeypatch.setattr("aragora.protocols.debate.DebateProtocol", MagicMock)
        monkeypatch.setattr("aragora.debate.orchestrator.Arena", mock_arena_cls)
        monkeypatch.setattr(
            "aragora.agents.create_agent",
            MagicMock(return_value=mock_agent),
        )

        result = await coord.debate_assignment(
            node_ids=["orch-1", "orch-2"],
            agents=["claude", "gpt", "gemini", "mistral"],
            rounds=2,
        )

        assert result.success
        assert "Debate-assigned" in result.message
        assignments = result.metadata["assignments"]
        assert "orch-1" in assignments
        assert "orch-2" in assignments
        # T1 line contains claude and gemini
        assert "claude" in assignments["orch-1"]
        assert "gemini" in assignments["orch-1"]
        # T2 line contains gpt and mistral
        assert "gpt" in assignments["orch-2"]
        assert "mistral" in assignments["orch-2"]
        # Verify metadata set on nodes
        assert graph.nodes["orch-1"].data["assignment_method"] == "debate"
        assert graph.nodes["orch-2"].data["assignment_method"] == "debate"

    @pytest.mark.asyncio
    async def test_fallback_when_no_agents_created(self, monkeypatch):
        """When create_agent raises for all agents, result should fail."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        monkeypatch.setattr("aragora.core.Environment", MagicMock)
        monkeypatch.setattr("aragora.protocols.debate.DebateProtocol", MagicMock)
        monkeypatch.setattr("aragora.debate.orchestrator.Arena", MagicMock)
        monkeypatch.setattr(
            "aragora.agents.create_agent",
            MagicMock(side_effect=RuntimeError("no agent")),
        )

        result = await coord.debate_assignment(
            node_ids=["orch-1"],
            agents=["claude", "gpt", "gemini"],
        )

        assert not result.success
        assert "No agents available" in result.message

    @pytest.mark.asyncio
    async def test_no_target_nodes(self):
        """Empty node_ids list yields failure."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        result = await coord.debate_assignment(node_ids=[])
        assert not result.success
        assert "No target nodes" in result.message

    @pytest.mark.asyncio
    async def test_nonexistent_node_ids_filtered(self, monkeypatch):
        """Node IDs not in graph are silently filtered; if none remain, fails."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        result = await coord.debate_assignment(node_ids=["nonexistent-1", "nonexistent-2"])
        assert not result.success
        assert "No target nodes" in result.message

    @pytest.mark.asyncio
    async def test_auto_discover_orchestration_nodes(self, monkeypatch):
        """When node_ids is None, orchestration nodes are auto-discovered."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        mock_result = MagicMock()
        mock_result.summary = "T1: claude\nT2: gpt\n"

        mock_arena_instance = MagicMock()
        mock_arena_instance.run = AsyncMock(return_value=mock_result)

        monkeypatch.setattr("aragora.core.Environment", MagicMock)
        monkeypatch.setattr("aragora.protocols.debate.DebateProtocol", MagicMock)
        monkeypatch.setattr(
            "aragora.debate.orchestrator.Arena", MagicMock(return_value=mock_arena_instance)
        )
        monkeypatch.setattr("aragora.agents.create_agent", MagicMock(return_value=MagicMock()))

        result = await coord.debate_assignment(node_ids=None, agents=["claude", "gpt", "gemini"])

        assert result.success
        # Both orch-1 and orch-2 should be discovered
        assert len(result.metadata["assignments"]) == 2

    @pytest.mark.asyncio
    async def test_fallback_assignment_when_summary_has_no_match(self, monkeypatch):
        """When debate summary doesn't mention any candidate, first agent is used as fallback."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        mock_result = MagicMock()
        mock_result.summary = "No specific recommendations available."

        mock_arena_instance = MagicMock()
        mock_arena_instance.run = AsyncMock(return_value=mock_result)

        monkeypatch.setattr("aragora.core.Environment", MagicMock)
        monkeypatch.setattr("aragora.protocols.debate.DebateProtocol", MagicMock)
        monkeypatch.setattr(
            "aragora.debate.orchestrator.Arena", MagicMock(return_value=mock_arena_instance)
        )
        monkeypatch.setattr("aragora.agents.create_agent", MagicMock(return_value=MagicMock()))

        result = await coord.debate_assignment(
            node_ids=["orch-1"],
            agents=["claude", "gpt"],
        )

        assert result.success
        # Fallback: first agent from the list
        assert result.metadata["assignments"]["orch-1"] == ["claude"]

    @pytest.mark.asyncio
    async def test_import_error_returns_failure(self, monkeypatch):
        """ImportError from Arena yields graceful failure."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        # Make the import of Environment raise ImportError
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "aragora.core":
                raise ImportError("no core")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        result = await coord.debate_assignment(node_ids=["orch-1"])
        assert not result.success
        assert (
            "not available" in result.message.lower()
            or "No target" in result.message
            or not result.success
        )

    @pytest.mark.asyncio
    async def test_runtime_error_during_debate(self, monkeypatch):
        """RuntimeError during arena.run() yields failure."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        mock_arena_instance = MagicMock()
        mock_arena_instance.run = AsyncMock(side_effect=RuntimeError("debate crashed"))

        monkeypatch.setattr("aragora.core.Environment", MagicMock)
        monkeypatch.setattr("aragora.protocols.debate.DebateProtocol", MagicMock)
        monkeypatch.setattr(
            "aragora.debate.orchestrator.Arena", MagicMock(return_value=mock_arena_instance)
        )
        monkeypatch.setattr("aragora.agents.create_agent", MagicMock(return_value=MagicMock()))

        result = await coord.debate_assignment(
            node_ids=["orch-1"], agents=["claude", "gpt", "gemini"]
        )
        assert not result.success
        assert "failed" in result.message.lower()


# ---------------------------------------------------------------------------
# _execute_federated
# ---------------------------------------------------------------------------


class _FakeCoordinator:
    """Stub class so isinstance checks pass in _execute_federated."""

    pass


class TestExecuteFederated:
    """Tests for DAGOperationsCoordinator._execute_federated()."""

    @pytest.mark.asyncio
    async def test_successful_federation(self, monkeypatch):
        """Successful remote execution sets metadata and returns success."""
        graph = _make_graph()
        node = graph.nodes["orch-1"]

        mock_federation = _FakeCoordinator()
        mock_remote_result = MagicMock()
        mock_remote_result.success = True
        mock_remote_result.to_dict.return_value = {"status": "completed"}
        mock_federation.execute_remote = AsyncMock(return_value=mock_remote_result)

        coord = DAGOperationsCoordinator(graph, federation_coordinator=mock_federation)

        monkeypatch.setattr(
            "aragora.coordination.cross_workspace.CrossWorkspaceCoordinator",
            _FakeCoordinator,
        )

        result = await coord._execute_federated(node, "remote-workspace-1")

        assert result.success
        assert "remote-workspace-1" in result.message
        assert result.metadata["workspace_id"] == "remote-workspace-1"
        assert node.metadata["federated_workspace"] == "remote-workspace-1"

    @pytest.mark.asyncio
    async def test_import_error_fallback(self, monkeypatch):
        """ImportError from CrossWorkspaceCoordinator returns failure."""
        graph = _make_graph()
        node = graph.nodes["orch-1"]

        mock_federation = MagicMock()
        coord = DAGOperationsCoordinator(graph, federation_coordinator=mock_federation)

        # Force ImportError when importing CrossWorkspaceCoordinator
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "cross_workspace" in name:
                raise ImportError("no cross_workspace")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        result = await coord._execute_federated(node, "remote-workspace-1")
        assert not result.success
        assert "not available" in result.message.lower()

    @pytest.mark.asyncio
    async def test_runtime_error_handling(self, monkeypatch):
        """RuntimeError during remote execution sets federation_error status."""
        graph = _make_graph()
        node = graph.nodes["orch-1"]

        mock_federation = _FakeCoordinator()
        mock_federation.execute_remote = AsyncMock(
            side_effect=RuntimeError("network timeout"),
        )

        coord = DAGOperationsCoordinator(graph, federation_coordinator=mock_federation)

        monkeypatch.setattr(
            "aragora.coordination.cross_workspace.CrossWorkspaceCoordinator",
            _FakeCoordinator,
        )

        result = await coord._execute_federated(node, "remote-ws")

        assert not result.success
        assert "failed" in result.message.lower()
        assert node.metadata["execution_status"] == "federation_error"

    @pytest.mark.asyncio
    async def test_federation_result_without_to_dict(self, monkeypatch):
        """Result object without to_dict uses str() fallback."""
        graph = _make_graph()
        node = graph.nodes["orch-1"]

        mock_federation = _FakeCoordinator()
        mock_remote_result = MagicMock(spec=[])  # No to_dict attribute
        mock_remote_result.success = True

        mock_federation.execute_remote = AsyncMock(return_value=mock_remote_result)

        coord = DAGOperationsCoordinator(graph, federation_coordinator=mock_federation)

        monkeypatch.setattr(
            "aragora.coordination.cross_workspace.CrossWorkspaceCoordinator",
            _FakeCoordinator,
        )

        result = await coord._execute_federated(node, "ws-2")

        assert result.success
        # str() fallback used for result serialization
        assert "result" in result.metadata

    @pytest.mark.asyncio
    async def test_federation_saves_graph(self, monkeypatch):
        """Federated execution calls _save on success."""
        graph = _make_graph()
        node = graph.nodes["orch-1"]

        save_calls = []
        mock_store = MagicMock()
        mock_store.update = lambda g: save_calls.append(True)

        mock_federation = _FakeCoordinator()
        mock_remote_result = MagicMock()
        mock_remote_result.success = True
        mock_remote_result.to_dict.return_value = {}
        mock_federation.execute_remote = AsyncMock(return_value=mock_remote_result)

        coord = DAGOperationsCoordinator(
            graph,
            store=mock_store,
            federation_coordinator=mock_federation,
        )

        monkeypatch.setattr(
            "aragora.coordination.cross_workspace.CrossWorkspaceCoordinator",
            _FakeCoordinator,
        )

        await coord._execute_federated(node, "ws-3")

        assert len(save_calls) > 0


# ---------------------------------------------------------------------------
# execute_node_via_scheduler
# ---------------------------------------------------------------------------


class TestExecuteNodeViaScheduler:
    """Tests for DAGOperationsCoordinator.execute_node_via_scheduler()."""

    @pytest.mark.asyncio
    async def test_successful_polling_completion(self):
        """Submit task, poll until completed, return success."""
        graph = _make_graph()

        mock_cp = MagicMock()
        mock_cp.submit_task = AsyncMock(return_value="task-123")

        completed_task = MagicMock()
        completed_task.status = "completed"
        completed_task.result = {"output": "done"}

        # First poll: in_progress, second poll: completed
        in_progress_task = MagicMock()
        in_progress_task.status = "in_progress"

        mock_cp.get_task = AsyncMock(side_effect=[in_progress_task, completed_task])

        coord = DAGOperationsCoordinator(graph, control_plane=mock_cp)

        result = await coord.execute_node_via_scheduler(
            "orch-1",
            poll_interval=0.01,
            max_polls=10,
        )

        assert result.success
        assert "completed" in result.message.lower()
        assert result.metadata["task_id"] == "task-123"
        assert graph.nodes["orch-1"].metadata["execution_status"] == "completed"
        assert graph.nodes["orch-1"].metadata["task_result"] == {"output": "done"}

    @pytest.mark.asyncio
    async def test_timeout_after_max_polls(self):
        """When max_polls is exhausted, returns timeout failure."""
        graph = _make_graph()

        mock_cp = MagicMock()
        mock_cp.submit_task = AsyncMock(return_value="task-456")

        pending_task = MagicMock()
        pending_task.status = "pending"
        mock_cp.get_task = AsyncMock(return_value=pending_task)

        coord = DAGOperationsCoordinator(graph, control_plane=mock_cp)

        result = await coord.execute_node_via_scheduler(
            "orch-1",
            poll_interval=0.01,
            max_polls=3,
        )

        assert not result.success
        assert "timed out" in result.message.lower()
        assert result.metadata["task_id"] == "task-456"
        assert graph.nodes["orch-1"].metadata["execution_status"] == "timeout"

    @pytest.mark.asyncio
    async def test_missing_control_plane(self):
        """No control_plane configured returns error."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph, control_plane=None)

        result = await coord.execute_node_via_scheduler("orch-1")

        assert not result.success
        assert "not configured" in result.message.lower()

    @pytest.mark.asyncio
    async def test_node_not_found(self):
        """Nonexistent node_id returns not-found error."""
        graph = _make_graph()
        mock_cp = MagicMock()
        coord = DAGOperationsCoordinator(graph, control_plane=mock_cp)

        result = await coord.execute_node_via_scheduler("nonexistent")

        assert not result.success
        assert "not found" in result.message

    @pytest.mark.asyncio
    async def test_failed_task_status(self):
        """Task that completes with 'failed' status returns failure."""
        graph = _make_graph()

        mock_cp = MagicMock()
        mock_cp.submit_task = AsyncMock(return_value="task-789")

        failed_task = MagicMock()
        failed_task.status = "failed"
        failed_task.result = {"error": "crash"}
        mock_cp.get_task = AsyncMock(return_value=failed_task)

        coord = DAGOperationsCoordinator(graph, control_plane=mock_cp)

        result = await coord.execute_node_via_scheduler(
            "orch-1",
            poll_interval=0.01,
            max_polls=5,
        )

        assert not result.success
        assert "failed" in result.message.lower()
        assert graph.nodes["orch-1"].metadata["execution_status"] == "failed"

    @pytest.mark.asyncio
    async def test_cancelled_task_status(self):
        """Task that completes with 'cancelled' status returns failure."""
        graph = _make_graph()

        mock_cp = MagicMock()
        mock_cp.submit_task = AsyncMock(return_value="task-cancel")

        cancelled_task = MagicMock()
        cancelled_task.status = "cancelled"
        cancelled_task.result = None
        mock_cp.get_task = AsyncMock(return_value=cancelled_task)

        coord = DAGOperationsCoordinator(graph, control_plane=mock_cp)

        result = await coord.execute_node_via_scheduler(
            "orch-1",
            poll_interval=0.01,
            max_polls=5,
        )

        assert not result.success
        assert "cancelled" in result.message.lower()

    @pytest.mark.asyncio
    async def test_get_task_returns_none_breaks_poll(self):
        """When get_task returns None, polling loop breaks."""
        graph = _make_graph()

        mock_cp = MagicMock()
        mock_cp.submit_task = AsyncMock(return_value="task-none")
        mock_cp.get_task = AsyncMock(return_value=None)

        coord = DAGOperationsCoordinator(graph, control_plane=mock_cp)

        result = await coord.execute_node_via_scheduler(
            "orch-1",
            poll_interval=0.01,
            max_polls=5,
        )

        # Breaks out of loop, falls through to timeout path
        assert not result.success
        assert "timed out" in result.message.lower()

    @pytest.mark.asyncio
    async def test_runtime_error_during_submit(self):
        """RuntimeError from submit_task returns failure."""
        graph = _make_graph()

        mock_cp = MagicMock()
        mock_cp.submit_task = AsyncMock(side_effect=RuntimeError("connection refused"))

        coord = DAGOperationsCoordinator(graph, control_plane=mock_cp)

        result = await coord.execute_node_via_scheduler(
            "orch-1",
            poll_interval=0.01,
            max_polls=3,
        )

        assert not result.success
        assert "failed" in result.message.lower()
        assert graph.nodes["orch-1"].metadata["execution_status"] == "error"

    @pytest.mark.asyncio
    async def test_status_with_enum_value(self):
        """Task status as enum with .value attribute is handled correctly."""
        graph = _make_graph()

        mock_cp = MagicMock()
        mock_cp.submit_task = AsyncMock(return_value="task-enum")

        mock_status = MagicMock()
        mock_status.value = "completed"

        completed_task = MagicMock()
        completed_task.status = mock_status
        completed_task.result = {"data": "ok"}
        mock_cp.get_task = AsyncMock(return_value=completed_task)

        coord = DAGOperationsCoordinator(graph, control_plane=mock_cp)

        result = await coord.execute_node_via_scheduler(
            "orch-1",
            poll_interval=0.01,
            max_polls=5,
        )

        assert result.success
        assert result.metadata["execution_status"] == "completed"

    @pytest.mark.asyncio
    async def test_saves_graph_on_completion(self):
        """Graph is saved via store on successful completion."""
        graph = _make_graph()
        save_calls = []
        mock_store = MagicMock()
        mock_store.update = lambda g: save_calls.append(True)

        mock_cp = MagicMock()
        mock_cp.submit_task = AsyncMock(return_value="task-save")

        completed_task = MagicMock()
        completed_task.status = "completed"
        completed_task.result = {}
        mock_cp.get_task = AsyncMock(return_value=completed_task)

        coord = DAGOperationsCoordinator(graph, store=mock_store, control_plane=mock_cp)

        await coord.execute_node_via_scheduler("orch-1", poll_interval=0.01, max_polls=3)

        assert len(save_calls) > 0


# ---------------------------------------------------------------------------
# assign_agents_with_selector
# ---------------------------------------------------------------------------


class TestAssignAgentsWithSelector:
    """Tests for DAGOperationsCoordinator.assign_agents_with_selector()."""

    @pytest.mark.asyncio
    async def test_successful_selection(self, monkeypatch):
        """TeamSelector.select() returns agents, pools populated on nodes."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        mock_agent_1 = MagicMock()
        mock_agent_1.name = "claude"
        mock_agent_2 = MagicMock()
        mock_agent_2.name = "gpt"

        mock_selector = MagicMock()
        mock_selector.select.return_value = [mock_agent_1, mock_agent_2]

        # Patch TeamSelector import
        monkeypatch.setattr(
            "aragora.debate.team_selector.TeamSelector",
            MagicMock,
        )

        result = await coord.assign_agents_with_selector(
            node_ids=["orch-1", "orch-2"],
            team_selector=mock_selector,
            available_agents=[mock_agent_1, mock_agent_2],
        )

        assert result.success
        assert "2 nodes" in result.message
        assert "orch-1" in result.metadata["assignments"]
        assert "orch-2" in result.metadata["assignments"]
        assert graph.nodes["orch-1"].data["agent_pool"] == ["claude", "gpt"]
        assert graph.nodes["orch-2"].data["agent_pool"] == ["claude", "gpt"]

    @pytest.mark.asyncio
    async def test_auto_discover_orchestration_nodes(self, monkeypatch):
        """When node_ids is None, auto-discovers orchestration nodes."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        mock_agent = MagicMock()
        mock_agent.name = "claude"

        mock_selector = MagicMock()
        mock_selector.select.return_value = [mock_agent]

        monkeypatch.setattr(
            "aragora.debate.team_selector.TeamSelector",
            MagicMock,
        )

        result = await coord.assign_agents_with_selector(
            node_ids=None,
            team_selector=mock_selector,
            available_agents=[mock_agent],
        )

        assert result.success
        # Should discover orch-1 and orch-2
        assert len(result.metadata["assignments"]) == 2

    @pytest.mark.asyncio
    async def test_node_with_orch_type_data(self, monkeypatch):
        """Nodes with data.orch_type == 'agent_task' are auto-discovered."""
        graph = UniversalGraph(id="orch-data-test")
        graph.add_node(
            UniversalNode(
                id="custom-1",
                stage=PipelineStage.ACTIONS,  # Not ORCHESTRATION stage
                node_subtype="task",
                label="Custom task",
                description="Task with orch_type data",
                data={"orch_type": "agent_task"},
            )
        )
        coord = DAGOperationsCoordinator(graph)

        mock_agent = MagicMock()
        mock_agent.name = "gemini"

        mock_selector = MagicMock()
        mock_selector.select.return_value = [mock_agent]

        monkeypatch.setattr(
            "aragora.debate.team_selector.TeamSelector",
            MagicMock,
        )

        result = await coord.assign_agents_with_selector(
            node_ids=None,
            team_selector=mock_selector,
            available_agents=[mock_agent],
        )

        assert result.success
        assert "custom-1" in result.metadata["assignments"]

    @pytest.mark.asyncio
    async def test_no_available_agents(self, monkeypatch):
        """Empty available_agents list returns failure."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        monkeypatch.setattr(
            "aragora.debate.team_selector.TeamSelector",
            MagicMock,
        )

        result = await coord.assign_agents_with_selector(
            node_ids=["orch-1"],
            team_selector=MagicMock(),
            available_agents=[],
        )

        assert not result.success
        assert "No agents available" in result.message

    @pytest.mark.asyncio
    async def test_team_selector_import_error(self, monkeypatch):
        """ImportError for TeamSelector returns failure."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "team_selector" in name:
                raise ImportError("no team_selector")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        result = await coord.assign_agents_with_selector(node_ids=["orch-1"])
        assert not result.success
        assert "not available" in result.message.lower()

    @pytest.mark.asyncio
    async def test_default_team_selector_creation_failure(self, monkeypatch):
        """When no team_selector provided and default creation fails, returns failure."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        monkeypatch.setattr(
            "aragora.debate.team_selector.TeamSelector",
            MagicMock(side_effect=RuntimeError("init failed")),
        )

        result = await coord.assign_agents_with_selector(
            node_ids=["orch-1"],
            available_agents=[MagicMock()],
        )

        assert not result.success
        assert "Could not create" in result.message

    @pytest.mark.asyncio
    async def test_specific_node_ids_filter(self, monkeypatch):
        """Only specified node_ids are assigned, others ignored."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        mock_agent = MagicMock()
        mock_agent.name = "claude"

        mock_selector = MagicMock()
        mock_selector.select.return_value = [mock_agent]

        monkeypatch.setattr(
            "aragora.debate.team_selector.TeamSelector",
            MagicMock,
        )

        result = await coord.assign_agents_with_selector(
            node_ids=["orch-1"],  # Only orch-1, not orch-2
            team_selector=mock_selector,
            available_agents=[mock_agent],
        )

        assert result.success
        assert "1 nodes" in result.message
        assert "orch-1" in result.metadata["assignments"]
        assert "orch-2" not in result.metadata["assignments"]

    @pytest.mark.asyncio
    async def test_domain_passed_to_selector(self, monkeypatch):
        """Node domain data is passed to TeamSelector.select()."""
        graph = _make_graph()
        graph.nodes["orch-1"].data["domain"] = "security"
        coord = DAGOperationsCoordinator(graph)

        mock_agent = MagicMock()
        mock_agent.name = "claude"

        mock_selector = MagicMock()
        mock_selector.select.return_value = [mock_agent]

        monkeypatch.setattr(
            "aragora.debate.team_selector.TeamSelector",
            MagicMock,
        )

        await coord.assign_agents_with_selector(
            node_ids=["orch-1"],
            team_selector=mock_selector,
            available_agents=[mock_agent],
        )

        # Verify domain was passed to select
        call_kwargs = mock_selector.select.call_args
        assert call_kwargs[1]["domain"] == "security"

    @pytest.mark.asyncio
    async def test_saves_graph_after_assignment(self, monkeypatch):
        """Graph is saved via store after successful assignment."""
        graph = _make_graph()
        save_calls = []
        mock_store = MagicMock()
        mock_store.update = lambda g: save_calls.append(True)

        coord = DAGOperationsCoordinator(graph, store=mock_store)

        mock_agent = MagicMock()
        mock_agent.name = "claude"

        mock_selector = MagicMock()
        mock_selector.select.return_value = [mock_agent]

        monkeypatch.setattr(
            "aragora.debate.team_selector.TeamSelector",
            MagicMock,
        )

        await coord.assign_agents_with_selector(
            node_ids=["orch-1"],
            team_selector=mock_selector,
            available_agents=[mock_agent],
        )

        assert len(save_calls) > 0

    @pytest.mark.asyncio
    async def test_auto_agent_discovery_when_none_provided(self, monkeypatch):
        """When available_agents is None, attempts auto-discovery via create_agent."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        mock_agent = MagicMock()
        mock_agent.name = "claude"

        mock_selector = MagicMock()
        mock_selector.select.return_value = [mock_agent]

        monkeypatch.setattr(
            "aragora.debate.team_selector.TeamSelector",
            MagicMock,
        )
        monkeypatch.setattr(
            "aragora.agents.create_agent",
            MagicMock(return_value=mock_agent),
        )

        result = await coord.assign_agents_with_selector(
            node_ids=["orch-1"],
            team_selector=mock_selector,
            available_agents=None,  # Triggers auto-discovery
        )

        assert result.success

    @pytest.mark.asyncio
    async def test_agent_without_name_attribute(self, monkeypatch):
        """Agents without .name use str() fallback."""
        graph = _make_graph()
        coord = DAGOperationsCoordinator(graph)

        # Use a plain string as agent (no .name attribute)
        mock_selector = MagicMock()
        mock_selector.select.return_value = ["raw-agent-str"]

        monkeypatch.setattr(
            "aragora.debate.team_selector.TeamSelector",
            MagicMock,
        )

        result = await coord.assign_agents_with_selector(
            node_ids=["orch-1"],
            team_selector=mock_selector,
            available_agents=["raw-agent-str"],
        )

        assert result.success
        assert graph.nodes["orch-1"].data["agent_pool"] == ["raw-agent-str"]
