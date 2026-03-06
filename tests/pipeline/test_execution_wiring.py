"""Tests for pipeline execution wiring.

Tests the task-based execution approach in _run_orchestration,
_build_execution_plan, _execute_task, node-level events, human gates,
and dry run mode.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.pipeline.idea_to_execution import (
    IdeaToExecutionPipeline,
    PipelineConfig,
    PipelineResult,
    StageResult,
)
from aragora.canvas.stages import PipelineStage
from aragora.goals.extractor import GoalGraph, GoalNode


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def pipeline():
    """Default pipeline with no AI agent."""
    return IdeaToExecutionPipeline()


@pytest.fixture
def sample_workflow():
    """Sample workflow with mixed step types."""
    return {
        "id": "wf-test",
        "name": "Test Workflow",
        "steps": [
            {
                "id": "step-1",
                "name": "Research: API design",
                "description": "Research best API design patterns",
                "step_type": "task",
                "config": {"test_scope": ["tests/api/"]},
            },
            {
                "id": "step-2",
                "name": "Review: API design",
                "description": "Human review of design",
                "step_type": "human_checkpoint",
                "config": {},
            },
            {
                "id": "step-3",
                "name": "Implement: Rate limiter",
                "description": "Build the rate limiter",
                "step_type": "task",
                "config": {"test_scope": ["tests/rate_limit/"]},
            },
            {
                "id": "step-4",
                "name": "Test: Rate limiter",
                "description": "Verify rate limiter",
                "step_type": "verification",
                "config": {},
            },
        ],
        "transitions": [],
    }


@pytest.fixture
def sample_goal_graph():
    """Sample goal graph for testing."""
    graph = GoalGraph(id="goals-test")
    graph.goals = [
        GoalNode(
            id="goal-1",
            title="Build rate limiter",
            description="Token bucket rate limiter",
        ),
        GoalNode(
            id="goal-2",
            title="Add caching",
            description="Redis-backed caching layer",
        ),
    ]
    return graph


@pytest.fixture
def event_collector():
    """Collects events emitted during pipeline execution."""
    events: list[tuple[str, dict]] = []

    def callback(event_type: str, data: dict):
        events.append((event_type, data))

    return events, callback


# =============================================================================
# TestBuildExecutionPlan
# =============================================================================


class TestBuildExecutionPlan:
    """Test _build_execution_plan constructs plans from workflow and goal_graph."""

    def test_plan_from_workflow_steps(self, pipeline, sample_workflow):
        plan = pipeline._build_execution_plan(sample_workflow, None)

        assert "tasks" in plan
        assert len(plan["tasks"]) == 4

    def test_plan_step_ids_match_workflow(self, pipeline, sample_workflow):
        plan = pipeline._build_execution_plan(sample_workflow, None)

        ids = [t["id"] for t in plan["tasks"]]
        assert ids == ["step-1", "step-2", "step-3", "step-4"]

    def test_plan_human_checkpoint_becomes_human_gate(self, pipeline, sample_workflow):
        plan = pipeline._build_execution_plan(sample_workflow, None)

        gate_tasks = [t for t in plan["tasks"] if t["type"] == "human_gate"]
        assert len(gate_tasks) == 1
        assert gate_tasks[0]["id"] == "step-2"

    def test_plan_task_types_correct(self, pipeline, sample_workflow):
        plan = pipeline._build_execution_plan(sample_workflow, None)

        types = [t["type"] for t in plan["tasks"]]
        assert types == ["agent_task", "human_gate", "agent_task", "agent_task"]

    def test_plan_preserves_test_scope(self, pipeline, sample_workflow):
        plan = pipeline._build_execution_plan(sample_workflow, None)

        assert plan["tasks"][0]["test_scope"] == ["tests/api/"]
        assert plan["tasks"][2]["test_scope"] == ["tests/rate_limit/"]

    def test_plan_from_goal_graph(self, pipeline, sample_goal_graph):
        plan = pipeline._build_execution_plan(None, sample_goal_graph)

        assert len(plan["tasks"]) == 2
        assert plan["tasks"][0]["name"] == "Build rate limiter"
        assert plan["tasks"][1]["name"] == "Add caching"

    def test_plan_goals_are_all_agent_task(self, pipeline, sample_goal_graph):
        plan = pipeline._build_execution_plan(None, sample_goal_graph)

        for task in plan["tasks"]:
            assert task["type"] == "agent_task"

    def test_plan_goals_have_empty_test_scope(self, pipeline, sample_goal_graph):
        plan = pipeline._build_execution_plan(None, sample_goal_graph)

        for task in plan["tasks"]:
            assert task["test_scope"] == []

    def test_plan_empty_when_no_workflow_no_goals(self, pipeline):
        plan = pipeline._build_execution_plan(None, None)
        assert plan["tasks"] == []

    def test_plan_empty_workflow_no_steps(self, pipeline):
        plan = pipeline._build_execution_plan({"steps": []}, None)
        assert plan["tasks"] == []

    def test_plan_empty_goal_graph_no_goals(self, pipeline):
        graph = GoalGraph(id="empty")
        plan = pipeline._build_execution_plan(None, graph)
        assert plan["tasks"] == []

    def test_plan_workflow_preferred_over_goals(self, pipeline, sample_workflow, sample_goal_graph):
        """When both workflow and goals are provided, workflow takes precedence."""
        plan = pipeline._build_execution_plan(sample_workflow, sample_goal_graph)
        assert len(plan["tasks"]) == 4  # Workflow has 4, goals has 2

    def test_plan_preserves_descriptions(self, pipeline, sample_workflow):
        plan = pipeline._build_execution_plan(sample_workflow, None)

        assert plan["tasks"][0]["description"] == "Research best API design patterns"

    def test_plan_preserves_names(self, pipeline, sample_workflow):
        plan = pipeline._build_execution_plan(sample_workflow, None)

        assert plan["tasks"][0]["name"] == "Research: API design"


# =============================================================================
# TestExecuteTask
# =============================================================================


class TestExecuteTask:
    """Test _execute_task with various DebugLoop scenarios."""

    @pytest.fixture(autouse=True)
    def block_heavy_imports(self):
        """Block heavy import chains that hang tests.

        - pipeline_adapter: async KM calls in the feedback section
        - aragora.debate.orchestrator: weaviate import chain via Arena path
        Both fall through to their respective except blocks gracefully.
        """
        with patch.dict(
            "sys.modules",
            {
                "aragora.knowledge.mound.adapters.pipeline_adapter": None,
                "aragora.debate.orchestrator": None,
            },
        ):
            yield

    @pytest.mark.asyncio
    async def test_execute_task_success_with_debug_loop(self, pipeline):
        """DebugLoop succeeds -> task status is 'completed'."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.to_dict.return_value = {"tests_passed": 5}

        # Patch at the source module since _execute_task imports locally
        mock_loop = AsyncMock()
        mock_loop.execute_with_retry.return_value = mock_result

        with (
            patch(
                "aragora.nomic.debug_loop.DebugLoop",
                return_value=mock_loop,
            ),
            patch(
                "aragora.nomic.debug_loop.DebugLoopConfig",
            ),
        ):
            task = {"id": "t1", "name": "Test task", "description": "desc", "test_scope": []}
            cfg = PipelineConfig()
            result = await pipeline._execute_task(task, cfg)

        assert result["task_id"] == "t1"
        assert result["status"] == "completed"
        assert result["output"] == {"tests_passed": 5}

    @pytest.mark.asyncio
    async def test_execute_task_failure_with_debug_loop(self, pipeline):
        """DebugLoop runs but tests fail -> task status is 'failed'."""
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.to_dict.return_value = {"tests_passed": 2, "tests_failed": 3}

        mock_loop = AsyncMock()
        mock_loop.execute_with_retry.return_value = mock_result

        with (
            patch(
                "aragora.nomic.debug_loop.DebugLoop",
                return_value=mock_loop,
            ),
            patch(
                "aragora.nomic.debug_loop.DebugLoopConfig",
            ),
        ):
            task = {"id": "t2", "name": "Failing task", "description": "", "test_scope": []}
            cfg = PipelineConfig()
            result = await pipeline._execute_task(task, cfg)

        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_execute_task_import_error_fallback(self, pipeline):
        """When DebugLoop import fails, task falls back to 'planned'."""
        with patch.dict("sys.modules", {"aragora.nomic.debug_loop": None}):
            task = {"id": "t3", "name": "No engine", "description": "", "test_scope": []}
            cfg = PipelineConfig()
            result = await pipeline._execute_task(task, cfg)

        assert result["status"] == "planned"
        assert result["output"]["reason"] == "execution_engine_unavailable"

    @pytest.mark.asyncio
    async def test_execute_task_runtime_error(self, pipeline):
        """RuntimeError from DebugLoop -> task status is 'failed'."""
        mock_loop = AsyncMock()
        mock_loop.execute_with_retry.side_effect = RuntimeError("process crashed")

        with (
            patch(
                "aragora.nomic.debug_loop.DebugLoop",
                return_value=mock_loop,
            ),
            patch(
                "aragora.nomic.debug_loop.DebugLoopConfig",
            ),
        ):
            task = {"id": "t4", "name": "Crashing task", "description": "", "test_scope": []}
            cfg = PipelineConfig()
            result = await pipeline._execute_task(task, cfg)

        assert result["status"] == "failed"
        assert result["output"]["error"] == "Task execution failed"

    @pytest.mark.asyncio
    async def test_execute_task_uses_worktree_path(self, pipeline):
        """Task execution passes worktree_path from config."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.to_dict.return_value = {}

        mock_loop = AsyncMock()
        mock_loop.execute_with_retry.return_value = mock_result

        with (
            patch(
                "aragora.nomic.debug_loop.DebugLoop",
                return_value=mock_loop,
            ),
            patch(
                "aragora.nomic.debug_loop.DebugLoopConfig",
            ),
        ):
            task = {
                "id": "t5",
                "name": "With worktree",
                "description": "",
                "test_scope": ["tests/"],
            }
            cfg = PipelineConfig(worktree_path="/custom/worktree")
            await pipeline._execute_task(task, cfg)

        call_kwargs = mock_loop.execute_with_retry.call_args
        assert (
            call_kwargs.kwargs.get("worktree_path") == "/custom/worktree"
            or (
                call_kwargs.args[1]
                if len(call_kwargs.args) > 1
                else call_kwargs.kwargs.get("worktree_path")
            )
            == "/custom/worktree"
        )


# =============================================================================
# TestRunOrchestration
# =============================================================================


class TestRunOrchestration:
    """Test the full _run_orchestration stage with mocked execution."""

    @pytest.mark.asyncio
    async def test_orchestration_with_workflow(self, pipeline, sample_workflow, event_collector):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        # Mock _execute_task to return completed
        async def mock_execute(task, _cfg):
            return {
                "task_id": task["id"],
                "name": task["name"],
                "status": "completed",
                "output": {},
            }

        pipeline._execute_task = mock_execute

        sr = await pipeline._run_orchestration("pipe-test", sample_workflow, None, cfg)

        assert sr.status == "completed"
        orch = sr.output["orchestration"]
        assert orch["status"] == "executed"
        # 3 agent tasks completed, 1 human gate awaiting
        assert orch["tasks_completed"] == 3
        assert orch["tasks_total"] == 4
        assert orch["integration_decision"]["decision"] == "needs_human_approval"

    @pytest.mark.asyncio
    async def test_orchestration_empty_tasks(self, pipeline, event_collector):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        sr = await pipeline._run_orchestration("pipe-empty", None, None, cfg)

        assert sr.status == "completed"
        orch = sr.output["orchestration"]
        assert orch["status"] == "skipped"
        assert orch["reason"] == "no tasks"

    @pytest.mark.asyncio
    async def test_orchestration_with_goal_graph(
        self, pipeline, sample_goal_graph, event_collector
    ):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        async def mock_execute(task, _cfg):
            return {
                "task_id": task["id"],
                "name": task["name"],
                "status": "completed",
                "output": {},
            }

        pipeline._execute_task = mock_execute

        sr = await pipeline._run_orchestration("pipe-goals", None, sample_goal_graph, cfg)

        assert sr.status == "completed"
        orch = sr.output["orchestration"]
        assert orch["tasks_completed"] == 2

    @pytest.mark.asyncio
    async def test_orchestration_handles_exception(
        self, pipeline, sample_workflow, event_collector
    ):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        # Force _build_execution_plan to raise
        def raise_error(*args, **kwargs):
            raise ValueError("plan build failed")

        pipeline._build_execution_plan = raise_error

        sr = await pipeline._run_orchestration("pipe-err", sample_workflow, None, cfg)

        assert sr.status == "failed"
        assert sr.error == "Orchestration failed"

    @pytest.mark.asyncio
    async def test_orchestration_duration_recorded(self, pipeline, event_collector):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        sr = await pipeline._run_orchestration("pipe-dur", None, None, cfg)
        assert sr.duration >= 0

    @pytest.mark.asyncio
    async def test_orchestration_emits_stage_started(self, pipeline, event_collector):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        await pipeline._run_orchestration("pipe-ev", None, None, cfg)

        event_types = [e[0] for e in events]
        assert "stage_started" in event_types

    @pytest.mark.asyncio
    async def test_orchestration_results_include_all_tasks(
        self, pipeline, sample_workflow, event_collector
    ):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        async def mock_execute(task, _cfg):
            return {"task_id": task["id"], "name": task["name"], "status": "planned", "output": {}}

        pipeline._execute_task = mock_execute

        sr = await pipeline._run_orchestration("pipe-all", sample_workflow, None, cfg)

        results = sr.output["orchestration"]["results"]
        assert len(results) == 4  # 3 agent_task + 1 human_gate
        for result in results:
            assert "work_lease" in result
            assert "completion_receipt" in result
            assert result["completion_receipt"]["task_id"] == result["task_id"]


# =============================================================================
# TestNodeLevelEvents
# =============================================================================


class TestNodeLevelEvents:
    """Test node-level event emission during pipeline stages."""

    @pytest.mark.asyncio
    async def test_agent_started_events(self, pipeline, sample_workflow, event_collector):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        async def mock_execute(task, _cfg):
            return {
                "task_id": task["id"],
                "name": task["name"],
                "status": "completed",
                "output": {},
            }

        pipeline._execute_task = mock_execute

        await pipeline._run_orchestration("pipe-ev", sample_workflow, None, cfg)

        agent_started = [e for e in events if e[0] == "pipeline_agent_started"]
        # 3 agent tasks (step-1, step-3, step-4), step-2 is human_gate
        assert len(agent_started) == 3

    @pytest.mark.asyncio
    async def test_agent_completed_events(self, pipeline, sample_workflow, event_collector):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        async def mock_execute(task, _cfg):
            return {
                "task_id": task["id"],
                "name": task["name"],
                "status": "completed",
                "output": {},
            }

        pipeline._execute_task = mock_execute

        await pipeline._run_orchestration("pipe-ev", sample_workflow, None, cfg)

        agent_completed = [e for e in events if e[0] == "pipeline_agent_completed"]
        assert len(agent_completed) == 3

    @pytest.mark.asyncio
    async def test_node_added_events_for_all_tasks(
        self, pipeline, sample_workflow, event_collector
    ):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        async def mock_execute(task, _cfg):
            return {
                "task_id": task["id"],
                "name": task["name"],
                "status": "completed",
                "output": {},
            }

        pipeline._execute_task = mock_execute

        await pipeline._run_orchestration("pipe-ev", sample_workflow, None, cfg)

        node_added = [e for e in events if e[0] == "pipeline_node_added"]
        assert len(node_added) == 4  # All tasks including human_gate

    @pytest.mark.asyncio
    async def test_human_gate_node_has_correct_type(
        self, pipeline, sample_workflow, event_collector
    ):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        async def mock_execute(task, _cfg):
            return {
                "task_id": task["id"],
                "name": task["name"],
                "status": "completed",
                "output": {},
            }

        pipeline._execute_task = mock_execute

        await pipeline._run_orchestration("pipe-ev", sample_workflow, None, cfg)

        node_added = [e for e in events if e[0] == "pipeline_node_added"]
        human_gate_nodes = [n for n in node_added if n[1]["node_type"] == "human_gate"]
        assert len(human_gate_nodes) == 1
        assert human_gate_nodes[0][1]["node_id"] == "step-2"

    def test_sync_from_ideas_emits_node_events(self, pipeline):
        """from_ideas emits pipeline_node_added for each idea and goal."""
        events: list[tuple[str, dict]] = []

        def callback(event_type: str, data: dict):
            events.append((event_type, data))

        ideas = ["Build rate limiter", "Add caching"]
        pipeline.from_ideas(ideas, auto_advance=True, event_callback=callback)

        node_events = [e for e in events if e[0] == "pipeline_node_added"]
        # At least idea nodes + goal nodes + action nodes + orchestration nodes
        assert len(node_events) > 0

        # Check idea nodes are emitted
        idea_nodes = [e for e in node_events if e[1]["stage"] == "ideas"]
        assert len(idea_nodes) == 2

    def test_sync_from_debate_emits_node_events(self, pipeline):
        """from_debate emits pipeline_node_added for goals, actions, orchestration."""
        events: list[tuple[str, dict]] = []

        def callback(event_type: str, data: dict):
            events.append((event_type, data))

        cartographer_data = {
            "nodes": [
                {"id": "n1", "type": "proposal", "summary": "Rate limiter", "content": "Build it"},
                {"id": "n2", "type": "evidence", "summary": "Supports perf", "content": "Evidence"},
            ],
            "edges": [
                {"source_id": "n2", "target_id": "n1", "relation": "supports"},
            ],
        }
        pipeline.from_debate(cartographer_data, auto_advance=True, event_callback=callback)

        node_events = [e for e in events if e[0] == "pipeline_node_added"]
        assert len(node_events) > 0

        # Verify multiple stages represented
        stages = {e[1]["stage"] for e in node_events}
        assert "goals" in stages
        assert "actions" in stages
        assert "orchestration" in stages

    def test_no_events_when_no_callback(self, pipeline):
        """Pipeline runs without errors when no callback provided."""
        result = pipeline.from_ideas(
            ["Test idea"],
            auto_advance=True,
            event_callback=None,
        )
        assert result.ideas_canvas is not None


# =============================================================================
# TestHumanGates
# =============================================================================


class TestHumanGates:
    """Test human gate handling in orchestration."""

    @pytest.mark.asyncio
    async def test_human_gate_gets_awaiting_status(self, pipeline, event_collector):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        workflow = {
            "steps": [
                {
                    "id": "gate-1",
                    "name": "Approve deploy",
                    "step_type": "human_checkpoint",
                    "config": {},
                },
            ],
        }

        await pipeline._run_orchestration("pipe-gate", workflow, None, cfg)

        # The gate should not trigger _execute_task
        # Instead it should be in results with awaiting_approval status

    @pytest.mark.asyncio
    async def test_human_gate_not_counted_as_completed(self, pipeline, event_collector):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        workflow = {
            "steps": [
                {
                    "id": "gate-1",
                    "name": "Approve deploy",
                    "step_type": "human_checkpoint",
                    "config": {},
                },
            ],
        }

        sr = await pipeline._run_orchestration("pipe-gate", workflow, None, cfg)

        orch = sr.output["orchestration"]
        assert orch["tasks_completed"] == 0
        assert orch["tasks_total"] == 1
        assert orch["results"][0]["status"] == "awaiting_approval"

    @pytest.mark.asyncio
    async def test_human_gate_does_not_call_execute_task(self, pipeline, event_collector):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        execute_called = False
        original_execute = pipeline._execute_task

        async def tracking_execute(task, _cfg):
            nonlocal execute_called
            execute_called = True
            return await original_execute(task, _cfg)

        pipeline._execute_task = tracking_execute

        workflow = {
            "steps": [
                {
                    "id": "gate-1",
                    "name": "Human gate",
                    "step_type": "human_checkpoint",
                    "config": {},
                },
            ],
        }

        await pipeline._run_orchestration("pipe-gate", workflow, None, cfg)
        assert not execute_called

    @pytest.mark.asyncio
    async def test_mixed_gates_and_tasks(self, pipeline, sample_workflow, event_collector):
        events, callback = event_collector
        cfg = PipelineConfig(event_callback=callback)

        async def mock_execute(task, _cfg):
            return {
                "task_id": task["id"],
                "name": task["name"],
                "status": "completed",
                "output": {},
            }

        pipeline._execute_task = mock_execute

        sr = await pipeline._run_orchestration("pipe-mixed", sample_workflow, None, cfg)

        orch = sr.output["orchestration"]
        statuses = {r["task_id"]: r["status"] for r in orch["results"]}
        assert statuses["step-2"] == "awaiting_approval"
        assert statuses["step-1"] == "completed"
        assert statuses["step-3"] == "completed"
        assert statuses["step-4"] == "completed"


# =============================================================================
# TestDryRunMode
# =============================================================================


class TestDryRunMode:
    """Test dry run mode skips orchestration execution."""

    @pytest.mark.asyncio
    async def test_dry_run_skips_orchestration(self, pipeline):
        cfg = PipelineConfig(
            dry_run=True,
            stages_to_run=["ideation", "goals", "workflow", "orchestration"],
        )

        result = await pipeline.run("Test input for dry run", config=cfg)

        # Orchestration stage should be skipped
        orch_stages = [sr for sr in result.stage_results if sr.stage_name == "orchestration"]
        assert len(orch_stages) == 1
        assert orch_stages[0].status == "skipped"

    @pytest.mark.asyncio
    async def test_dry_run_no_receipt(self, pipeline):
        cfg = PipelineConfig(dry_run=True, enable_receipts=True)

        result = await pipeline.run("Dry run no receipt", config=cfg)

        # Receipts disabled in dry run
        assert result.receipt is None

    @pytest.mark.asyncio
    async def test_non_dry_run_runs_orchestration(self, pipeline, event_collector):
        events, callback = event_collector
        cfg = PipelineConfig(
            dry_run=False,
            event_callback=callback,
            stages_to_run=["orchestration"],
        )

        # Mock _execute_task
        async def mock_execute(task, _cfg):
            return {
                "task_id": task["id"],
                "name": task["name"],
                "status": "completed",
                "output": {},
            }

        pipeline._execute_task = mock_execute

        result = await pipeline.run("Non dry run", config=cfg)

        orch_stages = [sr for sr in result.stage_results if sr.stage_name == "orchestration"]
        assert len(orch_stages) == 1
        # Should not be "skipped"
        assert orch_stages[0].status != "skipped"
