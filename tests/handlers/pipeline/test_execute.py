"""Tests for the PipelineExecuteHandler.

Covers:
  - Route registration and can_handle logic
  - Pipeline ID extraction and validation
  - GET /api/v1/pipeline/:id/execute  (execution status)
  - POST /api/v1/pipeline/:id/execute (start execution)
  - Rate limiting
  - Dry run mode
  - Background execution lifecycle (success, failure, cancel, import error)
  - Orchestration node loading
  - Goal conversion (orch_type -> Track mapping)
  - Already-executing guard (409 Conflict)
  - Receipt generation (success path + fallback)
  - Input validation (invalid IDs, missing nodes)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.pipeline.execute import (
    PipelineExecuteHandler,
    _executions,
    _execution_tasks,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_executions():
    """Reset module-level state between tests."""
    _executions.clear()
    _execution_tasks.clear()
    yield
    _executions.clear()
    _execution_tasks.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset the rate limiter between tests."""
    from aragora.server.handlers.pipeline.execute import _execute_limiter

    _execute_limiter._buckets.clear()
    yield
    _execute_limiter._buckets.clear()


def _make_handler(ctx: dict[str, Any] | None = None) -> PipelineExecuteHandler:
    return PipelineExecuteHandler(ctx=ctx or {})


def _make_http_handler(
    body: dict[str, Any] | None = None,
    client_ip: str = "127.0.0.1",
) -> MagicMock:
    handler = MagicMock()
    handler.client_address = (client_ip, 12345)
    handler.headers = {"Content-Length": "0"}
    if body is not None:
        raw = json.dumps(body).encode()
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile.read.return_value = raw
    else:
        handler.rfile.read.return_value = b"{}"
        handler.headers = {"Content-Length": "2"}
    return handler


def _body(result) -> dict[str, Any]:
    """Extract JSON body from a HandlerResult tuple or dataclass."""
    if result is None:
        return {}
    # HandlerResult dataclass
    if hasattr(result, "body"):
        raw = result.body
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw) if raw else {}
    # Tuple format (data, status, headers)
    if isinstance(result, tuple):
        return result[0] if isinstance(result[0], dict) else json.loads(result[0])
    return {}


def _status(result) -> int:
    """Extract status code from a HandlerResult tuple or dataclass."""
    if result is None:
        return 0
    if hasattr(result, "status_code"):
        return result.status_code
    if isinstance(result, tuple):
        return result[1]
    return 0


def _mock_orch_nodes(count: int = 2) -> list[dict[str, Any]]:
    """Create mock orchestration nodes."""
    nodes = []
    for i in range(count):
        nodes.append(
            {
                "id": f"orch-node-{i}",
                "stage": "orchestration",
                "label": f"Task {i + 1}",
                "orch_type": "agent_task",
                "assigned_agent": "claude",
            }
        )
    return nodes


def _mock_plan(plan_id: str = "plan-123") -> MagicMock:
    plan = MagicMock()
    plan.id = plan_id
    return plan


def _mock_launch(
    plan_id: str = "plan-123",
    execution_id: str = "exec-123",
    correlation_id: str = "corr-123",
) -> dict[str, Any]:
    return {
        "plan_id": plan_id,
        "execution_id": execution_id,
        "correlation_id": correlation_id,
        "execution_mode": "workflow",
        "status": "queued",
    }


def _mock_outcome(
    *,
    success: bool = True,
    tasks_total: int = 1,
    tasks_completed: int | None = None,
    receipt_id: str = "rcpt-123",
    error: str | None = None,
) -> MagicMock:
    completed = tasks_completed if tasks_completed is not None else tasks_total
    outcome = MagicMock()
    outcome.success = success
    outcome.tasks_total = tasks_total
    outcome.tasks_completed = completed
    outcome.error = error
    outcome.receipt_id = receipt_id
    outcome.to_dict.return_value = {
        "success": success,
        "tasks_total": tasks_total,
        "tasks_completed": completed,
        "error": error,
        "receipt_id": receipt_id,
    }
    return outcome


# ---------------------------------------------------------------------------
# Route Registration and can_handle
# ---------------------------------------------------------------------------


class TestRouting:
    def test_can_handle_execute_path(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/pipeline/pipe-abc123/execute") is True

    def test_can_handle_without_version(self):
        h = _make_handler()
        assert h.can_handle("/api/pipeline/pipe-abc123/execute") is True

    def test_cannot_handle_unrelated_path(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/debates") is False

    def test_cannot_handle_pipeline_without_execute(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/pipeline/pipe-abc123") is False

    def test_cannot_handle_pipeline_with_wrong_suffix(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/pipeline/pipe-abc123/status") is False

    def test_can_handle_short_path(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/pipeline") is False

    def test_can_handle_empty_path(self):
        h = _make_handler()
        assert h.can_handle("") is False

    def test_routes_attribute(self):
        h = _make_handler()
        assert "/api/v1/pipeline" in h.ROUTES

    def test_can_handle_with_extra_segments(self):
        h = _make_handler()
        # Path has exactly 4 parts after api prefix: pipeline/:id/execute
        assert h.can_handle("/api/v1/pipeline/abc/execute/extra") is True

    def test_can_handle_v2_version(self):
        h = _make_handler()
        # strip_version_prefix removes /v1/ or /v2/ etc.
        assert h.can_handle("/api/v2/pipeline/abc/execute") is True


# ---------------------------------------------------------------------------
# Pipeline ID Extraction
# ---------------------------------------------------------------------------


class TestPipelineIdExtraction:
    def test_extract_valid_id(self):
        h = _make_handler()
        pid = h._extract_pipeline_id("/api/v1/pipeline/pipe-abc123/execute")
        assert pid == "pipe-abc123"

    def test_extract_id_without_version(self):
        h = _make_handler()
        pid = h._extract_pipeline_id("/api/pipeline/my-pipeline/execute")
        assert pid == "my-pipeline"

    def test_extract_id_alphanumeric(self):
        h = _make_handler()
        pid = h._extract_pipeline_id("/api/v1/pipeline/abc123/execute")
        assert pid == "abc123"

    def test_extract_id_with_underscores(self):
        h = _make_handler()
        pid = h._extract_pipeline_id("/api/v1/pipeline/my_pipeline_01/execute")
        assert pid == "my_pipeline_01"

    def test_extract_id_special_chars_returns_none(self):
        """Special chars like '%' fail SAFE_ID_PATTERN validation, returning None."""
        h = _make_handler()
        pid = h._extract_pipeline_id("/api/v1/pipeline/pipe%20id/execute")
        # '%' is not in [a-zA-Z0-9_-], so validate_path_segment returns (False, ...)
        assert pid is None

    def test_extract_id_long_returns_none(self):
        """Long IDs (>64 chars) fail SAFE_ID_PATTERN validation, returning None."""
        h = _make_handler()
        long_id = "a" * 100
        pid = h._extract_pipeline_id(f"/api/v1/pipeline/{long_id}/execute")
        # SAFE_ID_PATTERN allows max 64 chars: ^[a-zA-Z0-9_-]{1,64}$
        assert pid is None

    def test_extract_empty_id_returns_none(self):
        """Empty segment fails validate_path_segment, returning None."""
        h = _make_handler()
        pid = h._extract_pipeline_id("/api/v1/pipeline//execute")
        # Empty string fails validate_path_segment (returns (False, "Missing pipeline_id"))
        assert pid is None

    def test_extract_id_short_path(self):
        h = _make_handler()
        pid = h._extract_pipeline_id("/api/v1/pipeline")
        assert pid is None

    def test_extract_id_wrong_suffix(self):
        h = _make_handler()
        pid = h._extract_pipeline_id("/api/v1/pipeline/abc/status")
        assert pid is None

    def test_extract_id_path_traversal_blocked_at_extraction(self):
        """Path traversal chars like '%' and '.' fail SAFE_ID_PATTERN validation."""
        h = _make_handler()
        pid = h._extract_pipeline_id("/api/v1/pipeline/..%2F..%2Fetc/execute")
        # '%' and '.' are not in [a-zA-Z0-9_-], so validation fails
        assert pid is None

    def test_extract_id_with_dots_and_slashes(self):
        """Path with dots in the ID segment."""
        h = _make_handler()
        # Slashes create additional path segments, so parts[3] != "execute"
        pid = h._extract_pipeline_id("/api/v1/pipeline/../../../etc/execute")
        # parts = ['', 'api', 'pipeline', '..', '..', '..', 'etc', 'execute']
        # parts[3] = '..' != 'execute', so returns None
        assert pid is None


# ---------------------------------------------------------------------------
# GET /api/v1/pipeline/:id/execute  (status)
# ---------------------------------------------------------------------------


class TestGetExecutionStatus:
    def test_status_not_started(self):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/pipe-123/execute", {}, http)
        assert _status(result) == 200
        data = _body(result)
        assert data["pipeline_id"] == "pipe-123"
        assert data["status"] == "not_started"

    def test_status_started(self):
        _executions["pipe-123"] = {
            "pipeline_id": "pipe-123",
            "cycle_id": "pipe-abc",
            "status": "started",
            "started_at": "2026-02-20T12:00:00+00:00",
            "goal_count": 2,
            "dry_run": False,
        }
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/pipe-123/execute", {}, http)
        assert _status(result) == 200
        data = _body(result)
        assert data["status"] == "started"
        assert data["cycle_id"] == "pipe-abc"
        assert data["goal_count"] == 2

    def test_status_completed(self):
        _executions["pipe-done"] = {
            "pipeline_id": "pipe-done",
            "status": "completed",
            "total_subtasks": 5,
            "completed_subtasks": 5,
            "failed_subtasks": 0,
        }
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/pipe-done/execute", {}, http)
        data = _body(result)
        assert data["status"] == "completed"
        assert data["completed_subtasks"] == 5

    def test_status_failed(self):
        _executions["pipe-fail"] = {
            "pipeline_id": "pipe-fail",
            "status": "failed",
            "error": "Pipeline execution failed",
        }
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/pipe-fail/execute", {}, http)
        data = _body(result)
        assert data["status"] == "failed"

    def test_status_empty_pipeline_id(self):
        """Empty pipeline ID segment returns 400."""
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline//execute", {}, http)
        assert _status(result) == 400

    def test_status_preview(self):
        _executions["pipe-dry"] = {
            "pipeline_id": "pipe-dry",
            "status": "preview",
            "goals": [{"description": "Task 1", "track": "core", "priority": 1}],
            "dry_run": True,
        }
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/pipe-dry/execute", {}, http)
        data = _body(result)
        assert data["status"] == "preview"
        assert data["dry_run"] is True

    def test_status_cancelled(self):
        _executions["pipe-cancel"] = {
            "pipeline_id": "pipe-cancel",
            "status": "cancelled",
            "completed_at": "2026-02-20T13:00:00+00:00",
        }
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/pipe-cancel/execute", {}, http)
        data = _body(result)
        assert data["status"] == "cancelled"


# ---------------------------------------------------------------------------
# POST /api/v1/pipeline/:id/execute (start execution)
# ---------------------------------------------------------------------------


class TestPostExecution:
    @pytest.mark.asyncio
    async def test_start_execution_success(self):
        h = _make_handler()
        http = _make_http_handler(body={"dry_run": False})
        orch_nodes = _mock_orch_nodes(2)

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            with patch.object(h, "_execute_pipeline", new_callable=AsyncMock):
                result = await h.handle_post("/api/v1/pipeline/pipe-123/execute", {}, http)

        assert _status(result) == 202
        data = _body(result)
        assert data["status"] == "started"
        assert data["pipeline_id"] == "pipe-123"
        assert data["cycle_id"].startswith("pipe-")

    @pytest.mark.asyncio
    async def test_start_execution_stores_state(self):
        h = _make_handler()
        http = _make_http_handler(body={})
        orch_nodes = _mock_orch_nodes(3)

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            with patch(
                "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
                return_value=(_mock_plan(), [MagicMock(), MagicMock(), MagicMock()]),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.queue_plan_execution",
                    return_value=_mock_launch(),
                ):
                    with patch.object(h, "_execute_pipeline", new_callable=AsyncMock):
                        await h.handle_post("/api/v1/pipeline/pipe-123/execute", {}, http)

        assert "pipe-123" in _executions
        assert _executions["pipe-123"]["goal_count"] == 3
        assert _executions["pipe-123"]["status"] == "started"
        assert _executions["pipe-123"]["runtime"] == "decision_plan"

    @pytest.mark.asyncio
    async def test_start_execution_empty_id_segment(self):
        """Empty pipeline ID segment returns 400."""
        h = _make_handler()
        http = _make_http_handler(body={})

        result = await h.handle_post("/api/v1/pipeline//execute", {}, http)

        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_start_execution_no_orchestration_nodes(self):
        h = _make_handler()
        http = _make_http_handler(body={})

        with patch.object(h, "_load_orchestration_nodes", return_value=[]):
            result = await h.handle_post("/api/v1/pipeline/pipe-123/execute", {}, http)

        assert _status(result) == 404
        data = _body(result)
        assert "orchestration" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_already_executing_conflict(self):
        h = _make_handler()
        http = _make_http_handler(body={})
        orch_nodes = _mock_orch_nodes()

        # Simulate an active task
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.done.return_value = False
        _execution_tasks["pipe-123"] = mock_task

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            result = await h.handle_post("/api/v1/pipeline/pipe-123/execute", {}, http)

        assert _status(result) == 409
        data = _body(result)
        assert "already executing" in data.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_done_task_allows_restart(self):
        h = _make_handler()
        http = _make_http_handler(body={})
        orch_nodes = _mock_orch_nodes()

        # Simulate a completed task
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.done.return_value = True
        _execution_tasks["pipe-123"] = mock_task

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            with patch.object(h, "_execute_pipeline", new_callable=AsyncMock):
                result = await h.handle_post("/api/v1/pipeline/pipe-123/execute", {}, http)

        assert _status(result) == 202

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self):
        h = _make_handler()

        from aragora.server.handlers.pipeline.execute import _execute_limiter

        # Exhaust rate limit
        with patch.object(_execute_limiter, "is_allowed", return_value=False):
            http = _make_http_handler(body={})
            result = await h.handle_post("/api/v1/pipeline/pipe-123/execute", {}, http)

        assert _status(result) == 429

    @pytest.mark.asyncio
    async def test_budget_limit_passed(self):
        h = _make_handler()
        http = _make_http_handler(body={"budget_limit_usd": 25.0})
        orch_nodes = _mock_orch_nodes()

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            with patch.object(h, "_execute_pipeline", new_callable=AsyncMock) as mock_exec:
                await h.handle_post("/api/v1/pipeline/pipe-123/execute", {}, http)

        # Budget limit should be forwarded to _execute_pipeline
        call_args = mock_exec.call_args
        assert call_args[0][3] == 25.0  # 4th positional arg = budget_limit

    @pytest.mark.asyncio
    async def test_require_approval_passed(self):
        h = _make_handler()
        http = _make_http_handler(body={"require_approval": True})
        orch_nodes = _mock_orch_nodes()

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            with patch.object(h, "_execute_pipeline", new_callable=AsyncMock) as mock_exec:
                await h.handle_post("/api/v1/pipeline/pipe-123/execute", {}, http)

        call_args = mock_exec.call_args
        assert call_args[0][4] is True  # 5th positional arg = require_approval


# ---------------------------------------------------------------------------
# Dry Run Mode
# ---------------------------------------------------------------------------


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_preview(self):
        h = _make_handler()
        http = _make_http_handler(body={"dry_run": True})
        orch_nodes = _mock_orch_nodes(2)

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            result = await h.handle_post("/api/v1/pipeline/pipe-dry/execute", {}, http)

        assert _status(result) == 200
        data = _body(result)
        assert data["status"] == "preview"
        assert data["dry_run"] is True
        assert "goals" in data
        assert len(data["goals"]) == 2

    @pytest.mark.asyncio
    async def test_dry_run_goals_have_description_track_priority(self):
        h = _make_handler()
        http = _make_http_handler(body={"dry_run": True})
        orch_nodes = [
            {
                "id": "n1",
                "stage": "orchestration",
                "label": "Research task",
                "orch_type": "verification",
            },
        ]

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            result = await h.handle_post("/api/v1/pipeline/pipe-dry/execute", {}, http)

        data = _body(result)
        goal = data["goals"][0]
        assert "description" in goal
        assert "track" in goal
        assert "priority" in goal
        assert goal["description"] == "Research task"
        assert goal["track"] == "qa"  # verification maps to QA track

    @pytest.mark.asyncio
    async def test_dry_run_does_not_start_background_task(self):
        h = _make_handler()
        http = _make_http_handler(body={"dry_run": True})
        orch_nodes = _mock_orch_nodes()

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            with patch.object(h, "_execute_pipeline", new_callable=AsyncMock) as mock_exec:
                await h.handle_post("/api/v1/pipeline/pipe-dry/execute", {}, http)

        mock_exec.assert_not_called()
        assert "pipe-dry" not in _execution_tasks

    @pytest.mark.asyncio
    async def test_dry_run_stores_preview_state(self):
        h = _make_handler()
        http = _make_http_handler(body={"dry_run": True})
        orch_nodes = _mock_orch_nodes()

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            await h.handle_post("/api/v1/pipeline/pipe-dry/execute", {}, http)

        assert _executions["pipe-dry"]["status"] == "preview"


# ---------------------------------------------------------------------------
# Orchestration Node Loading
# ---------------------------------------------------------------------------


class TestLoadOrchestrationNodes:
    def test_load_nodes_success(self):
        h = _make_handler()
        mock_graph = MagicMock()
        mock_node = {"stage": "orchestration", "label": "Task 1"}
        mock_graph.nodes = {"n1": mock_node}

        with patch("aragora.pipeline.graph_store.get_graph_store") as mock_get_store:
            mock_store = MagicMock()
            mock_store.get.return_value = mock_graph
            mock_get_store.return_value = mock_store

            nodes = h._load_orchestration_nodes("pipe-123")

        assert len(nodes) == 1
        assert nodes[0]["id"] == "n1"
        assert nodes[0]["label"] == "Task 1"

    def test_load_nodes_filters_non_orchestration(self):
        h = _make_handler()
        mock_graph = MagicMock()
        mock_graph.nodes = {
            "n1": {"stage": "orchestration", "label": "Orch Node"},
            "n2": {"stage": "idea", "label": "Idea Node"},
            "n3": {"stage": "goal", "label": "Goal Node"},
        }

        with patch("aragora.pipeline.graph_store.get_graph_store") as mock_get_store:
            mock_store = MagicMock()
            mock_store.get.return_value = mock_graph
            mock_get_store.return_value = mock_store

            nodes = h._load_orchestration_nodes("pipe-123")

        assert len(nodes) == 1
        assert nodes[0]["stage"] == "orchestration"

    def test_load_nodes_graph_not_found(self):
        h = _make_handler()

        with patch("aragora.pipeline.graph_store.get_graph_store") as mock_get_store:
            mock_store = MagicMock()
            mock_store.get.return_value = None
            mock_get_store.return_value = mock_store

            nodes = h._load_orchestration_nodes("nonexistent")

        assert nodes == []

    def test_load_nodes_import_error(self):
        h = _make_handler()

        with patch.dict("sys.modules", {"aragora.pipeline.graph_store": None}):
            nodes = h._load_orchestration_nodes("pipe-123")

        assert nodes == []

    def test_load_nodes_runtime_error(self):
        h = _make_handler()

        with patch(
            "aragora.pipeline.graph_store.get_graph_store",
            side_effect=RuntimeError("DB connection error"),
        ):
            nodes = h._load_orchestration_nodes("pipe-123")

        assert nodes == []

    def test_load_nodes_value_error(self):
        h = _make_handler()

        with patch(
            "aragora.pipeline.graph_store.get_graph_store",
            side_effect=ValueError("Invalid graph format"),
        ):
            nodes = h._load_orchestration_nodes("pipe-123")

        assert nodes == []

    def test_load_nodes_os_error(self):
        h = _make_handler()

        with patch(
            "aragora.pipeline.graph_store.get_graph_store",
            side_effect=OSError("File not found"),
        ):
            nodes = h._load_orchestration_nodes("pipe-123")

        assert nodes == []

    def test_load_nodes_attribute_error(self):
        h = _make_handler()

        with patch(
            "aragora.pipeline.graph_store.get_graph_store",
            side_effect=AttributeError("No attribute"),
        ):
            nodes = h._load_orchestration_nodes("pipe-123")

        assert nodes == []

    def test_load_nodes_with_object_nodes(self):
        """Test loading nodes that are objects with data attributes."""
        h = _make_handler()
        mock_graph = MagicMock()

        mock_node_obj = MagicMock()
        mock_node_obj.data = {"stage": "orchestration", "label": "Object Node"}
        # Ensure it's not a dict so the handler uses getattr
        mock_graph.nodes = {"n1": mock_node_obj}

        # Need to make isinstance(node, dict) return False
        with patch("aragora.pipeline.graph_store.get_graph_store") as mock_get_store:
            mock_store = MagicMock()
            mock_store.get.return_value = mock_graph
            mock_get_store.return_value = mock_store

            nodes = h._load_orchestration_nodes("pipe-123")

        assert len(nodes) == 1

    def test_load_nodes_empty_graph(self):
        h = _make_handler()
        mock_graph = MagicMock()
        mock_graph.nodes = {}

        with patch("aragora.pipeline.graph_store.get_graph_store") as mock_get_store:
            mock_store = MagicMock()
            mock_store.get.return_value = mock_graph
            mock_get_store.return_value = mock_store

            nodes = h._load_orchestration_nodes("pipe-123")

        assert nodes == []


# ---------------------------------------------------------------------------
# Goal Conversion (orch_type -> Track mapping)
# ---------------------------------------------------------------------------


class TestConvertToGoals:
    def test_basic_conversion(self):
        h = _make_handler()
        orch_nodes = [
            {"id": "n1", "label": "Do research", "orch_type": "agent_task"},
            {"id": "n2", "label": "Run tests", "orch_type": "verification"},
        ]
        goals = h._convert_to_goals(orch_nodes, "pipe-123")

        assert len(goals) == 2
        assert goals[0].description == "Do research"
        assert goals[0].track.value == "core"  # agent_task -> CORE
        assert goals[1].description == "Run tests"
        assert goals[1].track.value == "qa"  # verification -> QA

    def test_priority_increments(self):
        h = _make_handler()
        orch_nodes = _mock_orch_nodes(3)
        goals = h._convert_to_goals(orch_nodes, "pipe-123")

        assert goals[0].priority == 1
        assert goals[1].priority == 2
        assert goals[2].priority == 3

    def test_goal_ids_contain_pipeline_id(self):
        h = _make_handler()
        orch_nodes = _mock_orch_nodes(1)
        goals = h._convert_to_goals(orch_nodes, "pipe-abc123")

        assert goals[0].id.startswith("pipe-goal-pipe-abc")

    def test_track_mapping_debate(self):
        h = _make_handler()
        orch_nodes = [{"id": "n1", "label": "Debate topic", "orch_type": "debate"}]
        goals = h._convert_to_goals(orch_nodes, "pipe-123")
        assert goals[0].track.value == "core"

    def test_track_mapping_human_gate(self):
        h = _make_handler()
        orch_nodes = [{"id": "n1", "label": "Approve changes", "orch_type": "human_gate"}]
        goals = h._convert_to_goals(orch_nodes, "pipe-123")
        assert goals[0].track.value == "core"

    def test_track_mapping_parallel_fan(self):
        h = _make_handler()
        orch_nodes = [{"id": "n1", "label": "Fan out", "orch_type": "parallel_fan"}]
        goals = h._convert_to_goals(orch_nodes, "pipe-123")
        assert goals[0].track.value == "developer"

    def test_track_mapping_merge(self):
        h = _make_handler()
        orch_nodes = [{"id": "n1", "label": "Merge results", "orch_type": "merge"}]
        goals = h._convert_to_goals(orch_nodes, "pipe-123")
        assert goals[0].track.value == "developer"

    def test_track_mapping_unknown_defaults_to_core(self):
        h = _make_handler()
        orch_nodes = [{"id": "n1", "label": "Unknown", "orch_type": "unknown_type"}]
        goals = h._convert_to_goals(orch_nodes, "pipe-123")
        assert goals[0].track.value == "core"

    def test_label_from_description_fallback(self):
        h = _make_handler()
        orch_nodes = [{"id": "n1", "description": "My description"}]
        goals = h._convert_to_goals(orch_nodes, "pipe-123")
        assert goals[0].description == "My description"

    def test_label_default_when_missing(self):
        h = _make_handler()
        orch_nodes = [{"id": "n1"}]
        goals = h._convert_to_goals(orch_nodes, "pipe-123")
        assert goals[0].description == "Task 1"

    def test_orch_type_from_orchType_camelcase(self):
        h = _make_handler()
        orch_nodes = [{"id": "n1", "label": "Test", "orchType": "verification"}]
        goals = h._convert_to_goals(orch_nodes, "pipe-123")
        assert goals[0].track.value == "qa"

    def test_focus_areas_contain_orch_type(self):
        h = _make_handler()
        orch_nodes = [{"id": "n1", "label": "Test", "orch_type": "verification"}]
        goals = h._convert_to_goals(orch_nodes, "pipe-123")
        assert "verification" in goals[0].focus_areas

    def test_rationale_references_pipeline(self):
        h = _make_handler()
        orch_nodes = [{"id": "node-42", "label": "Test"}]
        goals = h._convert_to_goals(orch_nodes, "pipe-xyz")
        assert "pipe-xyz" in goals[0].rationale
        assert "node-42" in goals[0].rationale

    def test_empty_nodes_returns_empty(self):
        h = _make_handler()
        goals = h._convert_to_goals([], "pipe-123")
        assert goals == []

    def test_assigned_agent_from_camelcase(self):
        h = _make_handler()
        orch_nodes = [
            {"id": "n1", "label": "Test", "assignedAgent": "gpt-4", "orch_type": "agent_task"}
        ]
        goals = h._convert_to_goals(orch_nodes, "pipe-123")
        # _assigned_agent is used internally but doesn't affect the goal
        assert len(goals) == 1


# ---------------------------------------------------------------------------
# Background Execution - _execute_pipeline
# ---------------------------------------------------------------------------


class TestExecutePipeline:
    @pytest.mark.asyncio
    async def test_execution_success(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description="Goal 1"), MagicMock(description="Goal 2")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock(), MagicMock(), MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(
                        return_value=(
                            _mock_outcome(success=True, tasks_total=3, tasks_completed=3),
                            {"execution_id": "exec-123"},
                            {"receipt_id": "rcpt-123"},
                        )
                    ),
                ):
                    with patch(
                        "aragora.pipeline.receipt_generator.generate_pipeline_receipt",
                        new_callable=AsyncMock,
                    ) as mock_receipt:
                        mock_receipt.return_value = {"receipt_id": "pipe-rcpt"}
                        await h._execute_pipeline("pipe-123", "cycle-1", goals, 10.0, False)

        assert _executions["pipe-123"]["status"] == "completed"
        assert _executions["pipe-123"]["total_subtasks"] == 3
        assert _executions["pipe-123"]["completed_subtasks"] == 3
        assert _executions["pipe-123"]["failed_subtasks"] == 0

    @pytest.mark.asyncio
    async def test_execution_failure_zero_subtasks(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock(), MagicMock(), MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(
                        return_value=(
                            _mock_outcome(success=False, tasks_total=3, tasks_completed=0),
                            {"execution_id": "exec-123"},
                            {"receipt_id": "rcpt-123"},
                        )
                    ),
                ):
                    with patch(
                        "aragora.pipeline.receipt_generator.generate_pipeline_receipt",
                        new_callable=AsyncMock,
                    ) as mock_receipt:
                        mock_receipt.return_value = {"receipt_id": "pipe-rcpt"}
                        await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert _executions["pipe-123"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_execution_cancelled(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(side_effect=asyncio.CancelledError()),
                ):
                    await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert _executions["pipe-123"]["status"] == "cancelled"
        assert "completed_at" in _executions["pipe-123"]

    @pytest.mark.asyncio
    async def test_execution_import_error(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            side_effect=ImportError("canonical runtime not available"),
        ):
            await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert _executions["pipe-123"]["status"] == "failed"
        assert "not available" in _executions["pipe-123"]["error"].lower()

    @pytest.mark.asyncio
    async def test_execution_runtime_error(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(side_effect=RuntimeError("Boom")),
                ):
                    await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert _executions["pipe-123"]["status"] == "failed"
        assert _executions["pipe-123"]["error"] == "Boom"

    @pytest.mark.asyncio
    async def test_execution_value_error(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(side_effect=ValueError("Bad value")),
                ):
                    await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert _executions["pipe-123"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_execution_type_error(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(side_effect=TypeError("Type mismatch")),
                ):
                    await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert _executions["pipe-123"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_execution_os_error(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(side_effect=OSError("Disk full")),
                ):
                    await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert _executions["pipe-123"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_execution_cleans_up_task(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        _execution_tasks["pipe-123"] = MagicMock()
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(
                        return_value=(
                            _mock_outcome(success=True),
                            {"execution_id": "exec-123"},
                            {"receipt_id": "rcpt-123"},
                        )
                    ),
                ):
                    with patch(
                        "aragora.pipeline.receipt_generator.generate_pipeline_receipt",
                        new_callable=AsyncMock,
                    ):
                        await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert "pipe-123" not in _execution_tasks

    @pytest.mark.asyncio
    async def test_execution_cleans_up_task_on_error(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        _execution_tasks["pipe-123"] = MagicMock()
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(side_effect=RuntimeError("Boom")),
                ):
                    await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert "pipe-123" not in _execution_tasks

    @pytest.mark.asyncio
    async def test_execution_cleans_up_task_on_cancel(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        _execution_tasks["pipe-123"] = MagicMock()
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(side_effect=asyncio.CancelledError()),
                ):
                    await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert "pipe-123" not in _execution_tasks


class TestReceiptGeneration:
    @pytest.mark.asyncio
    async def test_receipt_generated_on_success(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(
                        return_value=(
                            _mock_outcome(success=True),
                            {"execution_id": "exec-123"},
                            {"receipt_id": "rcpt-123"},
                        )
                    ),
                ):
                    with patch(
                        "aragora.pipeline.receipt_generator.generate_pipeline_receipt",
                        new_callable=AsyncMock,
                    ) as mock_receipt:
                        mock_receipt.return_value = {"receipt_id": "pipe-rcpt"}
                        await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        mock_receipt.assert_awaited_once()
        assert mock_receipt.call_args[0][0] == "pipe-123"

    @pytest.mark.asyncio
    async def test_receipt_import_error_does_not_fail(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(
                        return_value=(
                            _mock_outcome(success=True),
                            {"execution_id": "exec-123"},
                            {"receipt_id": "rcpt-123"},
                        )
                    ),
                ):
                    with patch(
                        "aragora.pipeline.receipt_generator.generate_pipeline_receipt",
                        side_effect=ImportError("receipt gen unavailable"),
                    ):
                        await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert _executions["pipe-123"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_receipt_runtime_error_does_not_fail(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(
                        return_value=(
                            _mock_outcome(success=True),
                            {"execution_id": "exec-123"},
                            {"receipt_id": "rcpt-123"},
                        )
                    ),
                ):
                    with patch(
                        "aragora.pipeline.receipt_generator.generate_pipeline_receipt",
                        side_effect=RuntimeError("receipt gen failed"),
                    ):
                        await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert _executions["pipe-123"]["status"] == "completed"


class TestCanonicalBootstrap:
    @pytest.mark.asyncio
    async def test_budget_is_forwarded_to_plan_builder(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ) as mock_build:
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(
                        return_value=(
                            _mock_outcome(success=True),
                            {"execution_id": "exec-123"},
                            {"receipt_id": "rcpt-123"},
                        )
                    ),
                ):
                    with patch(
                        "aragora.pipeline.receipt_generator.generate_pipeline_receipt",
                        new_callable=AsyncMock,
                    ) as mock_receipt:
                        mock_receipt.return_value = {"receipt_id": "pipe-rcpt"}
                        await h._execute_pipeline("pipe-123", "cycle-1", goals, 50.0, False)

        assert mock_build.call_args.kwargs["budget_limit_usd"] == 50.0

    @pytest.mark.asyncio
    async def test_require_approval_is_forwarded_to_plan_builder(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description="Goal 1")]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ) as mock_build:
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(
                        return_value=(
                            _mock_outcome(success=True),
                            {"execution_id": "exec-123"},
                            {"receipt_id": "rcpt-123"},
                        )
                    ),
                ):
                    with patch(
                        "aragora.pipeline.receipt_generator.generate_pipeline_receipt",
                        new_callable=AsyncMock,
                    ) as mock_receipt:
                        mock_receipt.return_value = {"receipt_id": "pipe-rcpt"}
                        await h._execute_pipeline("pipe-123", "cycle-1", goals, None, True)

        assert mock_build.call_args.kwargs["require_task_approval"] is True

    @pytest.mark.asyncio
    async def test_bootstrap_creates_one_synthetic_node_per_goal(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}
        goals = [MagicMock(description=f"Goal {i}") for i in range(5)]

        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock() for _ in range(5)]),
        ) as mock_build:
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(
                        return_value=(
                            _mock_outcome(success=True, tasks_total=5, tasks_completed=5),
                            {"execution_id": "exec-123"},
                            {"receipt_id": "rcpt-123"},
                        )
                    ),
                ):
                    with patch(
                        "aragora.pipeline.receipt_generator.generate_pipeline_receipt",
                        new_callable=AsyncMock,
                    ) as mock_receipt:
                        mock_receipt.return_value = {"receipt_id": "pipe-rcpt"}
                        await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert len(mock_build.call_args.kwargs["nodes"]) == 5


# ---------------------------------------------------------------------------
# Handler Constructor
# ---------------------------------------------------------------------------


class TestHandlerConstructor:
    def test_default_context(self):
        h = PipelineExecuteHandler()
        assert h.ctx == {}

    def test_custom_context(self):
        ctx = {"storage": MagicMock()}
        h = PipelineExecuteHandler(ctx=ctx)
        assert h.ctx is ctx

    def test_none_context_defaults_to_empty(self):
        h = PipelineExecuteHandler(ctx=None)
        assert h.ctx == {}


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_get_status_with_versioned_path(self):
        _executions["pipe-v1"] = {
            "pipeline_id": "pipe-v1",
            "status": "completed",
        }
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/pipe-v1/execute", {}, http)
        assert _status(result) == 200
        data = _body(result)
        assert data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_post_with_empty_body(self):
        h = _make_handler()
        http = _make_http_handler(body=None)
        orch_nodes = _mock_orch_nodes()

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            with patch.object(h, "_execute_pipeline", new_callable=AsyncMock):
                result = await h.handle_post("/api/v1/pipeline/pipe-123/execute", {}, http)

        assert _status(result) == 202

    @pytest.mark.asyncio
    async def test_post_with_null_body_defaults(self):
        h = _make_handler()
        # read_json_body returns {} for no content, so dry_run=False, require_approval=False, budget=None
        http = _make_http_handler()
        orch_nodes = _mock_orch_nodes()

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            with patch.object(h, "_execute_pipeline", new_callable=AsyncMock) as mock_exec:
                await h.handle_post("/api/v1/pipeline/pipe-123/execute", {}, http)

        # Verify defaults
        call_args = mock_exec.call_args
        assert call_args[0][3] is None  # budget_limit
        assert call_args[0][4] is False  # require_approval

    @pytest.mark.asyncio
    async def test_multiple_pipelines_independent(self):
        h = _make_handler()
        orch_nodes = _mock_orch_nodes()

        for pid in ("pipe-a", "pipe-b"):
            http = _make_http_handler(body={})
            with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
                with patch.object(h, "_execute_pipeline", new_callable=AsyncMock):
                    result = await h.handle_post(f"/api/v1/pipeline/{pid}/execute", {}, http)
                    assert _status(result) == 202

        assert "pipe-a" in _executions
        assert "pipe-b" in _executions
        assert _executions["pipe-a"]["pipeline_id"] == "pipe-a"
        assert _executions["pipe-b"]["pipeline_id"] == "pipe-b"

    def test_get_nonexistent_pipeline(self):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/no-such/execute", {}, http)
        assert _status(result) == 200
        data = _body(result)
        assert data["status"] == "not_started"

    @pytest.mark.asyncio
    async def test_execution_state_includes_started_at(self):
        h = _make_handler()
        http = _make_http_handler(body={})
        orch_nodes = _mock_orch_nodes()

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            with patch.object(h, "_execute_pipeline", new_callable=AsyncMock):
                await h.handle_post("/api/v1/pipeline/pipe-123/execute", {}, http)

        assert "started_at" in _executions["pipe-123"]

    @pytest.mark.asyncio
    async def test_cycle_id_format(self):
        h = _make_handler()
        http = _make_http_handler(body={})
        orch_nodes = _mock_orch_nodes()

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            with patch.object(h, "_execute_pipeline", new_callable=AsyncMock):
                result = await h.handle_post("/api/v1/pipeline/pipe-123/execute", {}, http)

        data = _body(result)
        assert data["cycle_id"].startswith("pipe-")
        # uuid hex portion is 12 chars
        assert len(data["cycle_id"]) == 5 + 12  # "pipe-" + 12 hex chars


# ---------------------------------------------------------------------------
# Track Mapping Completeness
# ---------------------------------------------------------------------------


class TestTrackMappingCompleteness:
    """Ensure all documented orch_types map to the correct Track."""

    def test_all_known_orch_types_mapped(self):
        h = _make_handler()
        known_types = {
            "agent_task": "core",
            "debate": "core",
            "human_gate": "core",
            "verification": "qa",
            "parallel_fan": "developer",
            "merge": "developer",
        }
        for orch_type, expected_track in known_types.items():
            nodes = [{"id": "n1", "label": "Test", "orch_type": orch_type}]
            goals = h._convert_to_goals(nodes, "pipe-test")
            assert goals[0].track.value == expected_track, (
                f"orch_type={orch_type} should map to {expected_track}"
            )

    def test_default_track_for_empty_orch_type(self):
        h = _make_handler()
        nodes = [{"id": "n1", "label": "Test", "orch_type": ""}]
        goals = h._convert_to_goals(nodes, "pipe-test")
        assert goals[0].track.value == "core"

    def test_default_track_for_missing_orch_type(self):
        h = _make_handler()
        nodes = [{"id": "n1", "label": "Test"}]
        goals = h._convert_to_goals(nodes, "pipe-test")
        assert goals[0].track.value == "core"


# ---------------------------------------------------------------------------
# Module-Level State Isolation
# ---------------------------------------------------------------------------


class TestModuleStateIsolation:
    def test_executions_dict_initially_empty(self):
        """Autouse fixture should clear _executions between tests."""
        assert len(_executions) == 0

    def test_execution_tasks_initially_empty(self):
        """Autouse fixture should clear _execution_tasks between tests."""
        assert len(_execution_tasks) == 0

    def test_setting_execution_visible_in_handle(self):
        _executions["test-iso"] = {"pipeline_id": "test-iso", "status": "running"}
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/pipeline/test-iso/execute", {}, http)
        data = _body(result)
        assert data["status"] == "running"


# ---------------------------------------------------------------------------
# Rate Limiter Behavior
# ---------------------------------------------------------------------------


class TestRateLimiterBehavior:
    @pytest.mark.asyncio
    async def test_different_ips_have_separate_limits(self):
        h = _make_handler()
        orch_nodes = _mock_orch_nodes()

        from aragora.server.handlers.pipeline.execute import _execute_limiter

        with patch.object(_execute_limiter, "is_allowed", side_effect=lambda ip: ip == "10.0.0.1"):
            # First IP allowed
            http1 = _make_http_handler(body={}, client_ip="10.0.0.1")
            with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
                with patch.object(h, "_execute_pipeline", new_callable=AsyncMock):
                    result1 = await h.handle_post("/api/v1/pipeline/pipe-1/execute", {}, http1)
            assert _status(result1) == 202

            # Second IP not allowed
            http2 = _make_http_handler(body={}, client_ip="10.0.0.2")
            result2 = await h.handle_post("/api/v1/pipeline/pipe-2/execute", {}, http2)
            assert _status(result2) == 429


# ---------------------------------------------------------------------------
# Execution State Transitions
# ---------------------------------------------------------------------------


class TestExecutionStateTransitions:
    @pytest.mark.asyncio
    async def test_state_from_started_to_completed(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}

        goals = [MagicMock(description="G1")]
        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(
                        return_value=(
                            _mock_outcome(success=True, tasks_total=2, tasks_completed=2),
                            {"execution_id": "exec-123"},
                            {"receipt_id": "rcpt-123"},
                        )
                    ),
                ):
                    with patch(
                        "aragora.pipeline.receipt_generator.generate_pipeline_receipt",
                        new_callable=AsyncMock,
                    ) as mock_receipt:
                        mock_receipt.return_value = {"receipt_id": "pipe-rcpt"}
                        await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert _executions["pipe-123"]["status"] == "completed"
        assert "completed_at" in _executions["pipe-123"]

    @pytest.mark.asyncio
    async def test_state_from_started_to_failed(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}

        goals = [MagicMock(description="G1")]
        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(side_effect=RuntimeError("Oops")),
                ):
                    await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert _executions["pipe-123"]["status"] == "failed"
        assert "completed_at" in _executions["pipe-123"]
        assert _executions["pipe-123"]["error"] == "Oops"

    @pytest.mark.asyncio
    async def test_state_from_started_to_cancelled(self):
        h = _make_handler()
        _executions["pipe-123"] = {"pipeline_id": "pipe-123", "status": "started"}

        goals = [MagicMock(description="G1")]
        with patch(
            "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
            return_value=(_mock_plan(), [MagicMock()]),
        ):
            with patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=_mock_launch(),
            ):
                with patch(
                    "aragora.pipeline.canonical_execution.execute_queued_plan",
                    new=AsyncMock(side_effect=asyncio.CancelledError()),
                ):
                    await h._execute_pipeline("pipe-123", "cycle-1", goals, None, False)

        assert _executions["pipe-123"]["status"] == "cancelled"
        assert "completed_at" in _executions["pipe-123"]


# ---------------------------------------------------------------------------
# Query Params Passthrough
# ---------------------------------------------------------------------------


class TestQueryParams:
    def test_query_params_ignored_by_get(self):
        """GET handler ignores query params."""
        _executions["pipe-123"] = {
            "pipeline_id": "pipe-123",
            "status": "completed",
        }
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle(
            "/api/v1/pipeline/pipe-123/execute",
            {"extra": "param", "debug": "true"},
            http,
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_query_params_ignored_by_post(self):
        """POST handler ignores query params."""
        h = _make_handler()
        http = _make_http_handler(body={})
        orch_nodes = _mock_orch_nodes()

        with patch.object(h, "_load_orchestration_nodes", return_value=orch_nodes):
            with patch.object(h, "_execute_pipeline", new_callable=AsyncMock):
                result = await h.handle_post(
                    "/api/v1/pipeline/pipe-123/execute",
                    {"extra": "param"},
                    http,
                )

        assert _status(result) == 202
