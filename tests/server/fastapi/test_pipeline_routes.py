"""
Comprehensive tests for FastAPI pipeline route endpoints.

Covers:
- GET    /api/v2/pipeline/runs                 - List pipeline runs with pagination
- POST   /api/v2/pipeline/runs                 - Start a new pipeline run
- GET    /api/v2/pipeline/runs/{run_id}        - Get pipeline run status and details
- GET    /api/v2/pipeline/runs/{run_id}/stages - Get individual stage results
- POST   /api/v2/pipeline/runs/{run_id}/approve - Approve a stage gate
- DELETE /api/v2/pipeline/runs/{run_id}        - Cancel a pipeline run
- Input validation (Pydantic 422 errors)
- Auth enforcement on write operations
- Not-found cases
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from aragora.server.fastapi import create_app
from aragora.tenancy.record_scope import OrgScope, require_org_scope_fastapi

ORG = "org-1"


@pytest.fixture
def pipeline_store():
    """Create an empty pipeline store for tests."""
    return {}


@pytest.fixture
def client(fastapi_context_builder, pipeline_store):
    """Create a test client with the standard FastAPI route harness."""
    app = create_app()
    app.state.context = fastapi_context_builder(
        decision_service=MagicMock(),
        pipeline_store=pipeline_store,
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def authed_client(client, override_fastapi_auth):
    """Client acting for org ``org-1`` with the canvas permissions pipeline runs check."""
    override_fastapi_auth(
        client,
        roles={"admin"},
        permissions={"canvas:read", "canvas:create", "canvas:run", "canvas:delete"},
    )
    client.app.dependency_overrides[require_org_scope_fastapi] = lambda: OrgScope(
        org_id=ORG, user_id="user-1", role="admin"
    )
    return client


@pytest.fixture
def sample_run(pipeline_store):
    """Insert a sample pipeline run into the store."""
    run = {
        "id": "pipe-abc123",
        "idea": "Implement Redis caching for API responses",
        "status": "running",
        "stages": [
            {
                "stage_name": "ideation",
                "status": "completed",
                "output": {"type": "Canvas"},
                "started_at": "2026-02-20T10:00:00",
                "completed_at": "2026-02-20T10:01:00",
                "duration": 1.5,
                "error": None,
            },
            {
                "stage_name": "goals",
                "status": "pending",
                "output": None,
                "started_at": None,
                "completed_at": None,
                "duration": 0.0,
                "error": None,
            },
            {
                "stage_name": "workflow",
                "status": "pending",
                "output": None,
                "started_at": None,
                "completed_at": None,
                "duration": 0.0,
                "error": None,
            },
            {
                "stage_name": "orchestration",
                "status": "pending",
                "output": None,
                "started_at": None,
                "completed_at": None,
                "duration": 0.0,
                "error": None,
            },
        ],
        "created_at": "2026-02-20T10:00:00",
        "updated_at": "2026-02-20T10:01:00",
        "config": {"dry_run": True},
        "result": None,
    }
    run["org_id"] = ORG
    pipeline_store["pipe-abc123"] = run
    return run


@pytest.fixture
def completed_run(pipeline_store):
    """Insert a completed pipeline run into the store."""
    run = {
        "id": "pipe-done999",
        "idea": "Optimize database queries",
        "status": "completed",
        "stages": [
            {
                "stage_name": "ideation",
                "status": "completed",
                "output": {"type": "Canvas"},
                "started_at": "2026-02-20T09:00:00",
                "completed_at": "2026-02-20T09:01:00",
                "duration": 1.0,
                "error": None,
            },
            {
                "stage_name": "goals",
                "status": "completed",
                "output": {"type": "GoalGraph"},
                "started_at": "2026-02-20T09:01:00",
                "completed_at": "2026-02-20T09:02:00",
                "duration": 0.8,
                "error": None,
            },
        ],
        "created_at": "2026-02-20T09:00:00",
        "updated_at": "2026-02-20T09:02:00",
        "config": {},
        "result": {"pipeline_id": "pipe-done999", "stage_status": {}},
    }
    run["org_id"] = ORG
    pipeline_store["pipe-done999"] = run
    return run


@pytest.fixture
def cancelled_run(pipeline_store):
    """Insert a cancelled pipeline run into the store."""
    run = {
        "id": "pipe-cancel1",
        "idea": "Cancelled idea",
        "status": "cancelled",
        "stages": [
            {
                "stage_name": "ideation",
                "status": "skipped",
                "output": None,
                "started_at": None,
                "completed_at": None,
                "duration": 0.0,
                "error": None,
            },
        ],
        "created_at": "2026-02-20T08:00:00",
        "updated_at": "2026-02-20T08:01:00",
        "config": {},
        "result": None,
    }
    run["org_id"] = ORG
    pipeline_store["pipe-cancel1"] = run
    return run


@pytest.fixture
def workflow_ready_run(pipeline_store):
    """Insert a completed pipeline run with a goal graph ready for workflow execution."""
    run = {
        "id": "pipe-workflow1",
        "idea": "Turn approved goals into executable work",
        "status": "completed",
        "stages": [
            {
                "stage_name": "ideation",
                "status": "completed",
                "output": {"type": "Canvas"},
                "started_at": "2026-02-20T09:00:00",
                "completed_at": "2026-02-20T09:01:00",
                "duration": 1.0,
                "error": None,
            },
            {
                "stage_name": "goals",
                "status": "completed",
                "output": {"type": "GoalGraph"},
                "started_at": "2026-02-20T09:01:00",
                "completed_at": "2026-02-20T09:02:00",
                "duration": 0.8,
                "error": None,
            },
        ],
        "created_at": "2026-02-20T09:00:00",
        "updated_at": "2026-02-20T09:02:00",
        "config": {},
        "result": {
            "pipeline_id": "pipe-workflow1",
            "goals": {
                "id": "gg-1",
                "goals": [
                    {
                        "id": "goal-1",
                        "title": "Ship the workflow handoff",
                        "description": "Execute the generated workflow from the pipeline run",
                        "type": "goal",
                        "priority": "high",
                        "measurable": "Execution record exists",
                        "dependencies": [],
                        "source_idea_ids": ["idea-1"],
                        "confidence": 0.9,
                        "metadata": {},
                    }
                ],
                "provenance": [],
                "transition": None,
                "metadata": {},
            },
            "stage_status": {"ideation": "complete", "goals": "complete"},
        },
    }
    run["org_id"] = ORG
    pipeline_store["pipe-workflow1"] = run
    return run


@pytest.fixture
def no_goal_workflow_run(pipeline_store):
    """Insert a completed pipeline run with no executable goals."""
    run = {
        "id": "pipe-no-goals1",
        "idea": "Pipeline result without executable workflow steps",
        "status": "completed",
        "stages": [],
        "created_at": "2026-02-20T09:00:00",
        "updated_at": "2026-02-20T09:02:00",
        "config": {},
        "result": {
            "pipeline_id": "pipe-no-goals1",
            "goals": {
                "id": "gg-empty",
                "goals": [],
                "provenance": [],
                "transition": None,
                "metadata": {},
            },
            "stage_status": {"ideation": "complete", "goals": "complete"},
        },
    }
    run["org_id"] = ORG
    pipeline_store["pipe-no-goals1"] = run
    return run


# =============================================================================
# GET /api/v2/pipeline/runs
# =============================================================================


class TestListPipelineRuns:
    """Tests for GET /api/v2/pipeline/runs."""

    def test_returns_200_empty_list(self, authed_client):
        """List pipeline runs returns 200 with empty list."""
        response = authed_client.get("/api/v2/pipeline/runs")
        assert response.status_code == 200
        data = response.json()
        assert data["runs"] == []
        assert data["total"] == 0
        assert data["limit"] == 50
        assert data["offset"] == 0

    def test_returns_runs_with_data(self, authed_client, sample_run):
        """List pipeline runs returns summaries from store."""
        response = authed_client.get("/api/v2/pipeline/runs")
        assert response.status_code == 200
        data = response.json()
        assert len(data["runs"]) == 1
        assert data["total"] == 1
        first = data["runs"][0]
        assert first["id"] == "pipe-abc123"
        assert first["idea"] == "Implement Redis caching for API responses"
        assert first["status"] == "running"
        assert first["stage_count"] == 4
        assert first["completed_stages"] == 1

    def test_pagination_params(self, authed_client, sample_run, completed_run):
        """List pipeline runs respects pagination params."""
        response = authed_client.get("/api/v2/pipeline/runs?limit=1&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data["runs"]) == 1
        assert data["total"] == 2
        assert data["limit"] == 1
        assert data["offset"] == 0

    def test_pagination_offset(self, authed_client, sample_run, completed_run):
        """List pipeline runs respects offset."""
        response = authed_client.get("/api/v2/pipeline/runs?limit=1&offset=1")
        assert response.status_code == 200
        data = response.json()
        assert len(data["runs"]) == 1
        assert data["total"] == 2

    def test_status_filter(self, authed_client, sample_run, completed_run):
        """List pipeline runs supports status filter."""
        response = authed_client.get("/api/v2/pipeline/runs?status=completed")
        assert response.status_code == 200
        data = response.json()
        assert len(data["runs"]) == 1
        assert data["runs"][0]["status"] == "completed"

    def test_status_filter_no_matches(self, authed_client, sample_run):
        """Status filter returns empty when no matches."""
        response = authed_client.get("/api/v2/pipeline/runs?status=failed")
        assert response.status_code == 200
        data = response.json()
        assert data["runs"] == []
        assert data["total"] == 0

    def test_limit_validation_min(self, authed_client):
        """Limit must be >= 1."""
        response = authed_client.get("/api/v2/pipeline/runs?limit=0")
        assert response.status_code == 422

    def test_limit_validation_max(self, authed_client):
        """Limit must be <= 100."""
        response = authed_client.get("/api/v2/pipeline/runs?limit=101")
        assert response.status_code == 422

    def test_offset_validation_min(self, authed_client):
        """Offset must be >= 0."""
        response = authed_client.get("/api/v2/pipeline/runs?offset=-1")
        assert response.status_code == 422


# =============================================================================
# POST /api/v2/pipeline/runs
# =============================================================================


class TestCreatePipelineRun:
    """Tests for POST /api/v2/pipeline/runs."""

    def test_requires_auth(self, client):
        """POST pipeline runs requires authentication."""
        response = client.post(
            "/api/v2/pipeline/runs",
            json={"idea": "Build a better API"},
        )
        assert response.status_code == 401

    def test_creates_run_successfully(self, authed_client, pipeline_store):
        """POST creates a new pipeline run with 201 status."""
        with patch(
            "aragora.server.fastapi.routes.pipeline._execute_pipeline",
            side_effect=ImportError("mocked"),
        ):
            response = authed_client.post(
                "/api/v2/pipeline/runs",
                json={"idea": "Improve test coverage across all modules"},
            )
        assert response.status_code == 201
        data = response.json()
        assert data["idea"] == "Improve test coverage across all modules"
        assert data["id"].startswith("pipe-")
        assert data["status"] in ("pending", "completed")
        assert len(data["stages"]) == 4
        assert data["created_at"] != ""
        assert data["updated_at"] != ""

        # Verify stored
        assert data["id"] in pipeline_store

    def test_creates_run_with_config(self, authed_client, pipeline_store):
        """POST accepts optional config overrides."""
        with patch(
            "aragora.server.fastapi.routes.pipeline._execute_pipeline",
            side_effect=ImportError("mocked"),
        ):
            response = authed_client.post(
                "/api/v2/pipeline/runs",
                json={
                    "idea": "Refactor auth module",
                    "config": {"dry_run": True, "human_approval_required": True},
                },
            )
        assert response.status_code == 201
        data = response.json()
        assert data["config"]["dry_run"] is True
        assert data["config"]["human_approval_required"] is True

    def test_creates_run_with_custom_stages(self, authed_client, pipeline_store):
        """POST respects stages_to_run in config."""
        with patch(
            "aragora.server.fastapi.routes.pipeline._execute_pipeline",
            side_effect=ImportError("mocked"),
        ):
            response = authed_client.post(
                "/api/v2/pipeline/runs",
                json={
                    "idea": "Quick ideation only",
                    "config": {"stages_to_run": ["ideation", "goals"]},
                },
            )
        assert response.status_code == 201
        data = response.json()
        assert len(data["stages"]) == 2
        assert data["stages"][0]["stage_name"] == "ideation"
        assert data["stages"][1]["stage_name"] == "goals"

    def test_validates_empty_idea(self, authed_client):
        """POST rejects empty idea string."""
        response = authed_client.post(
            "/api/v2/pipeline/runs",
            json={"idea": ""},
        )
        assert response.status_code == 422

    def test_validates_missing_idea(self, authed_client):
        """POST rejects request without idea field."""
        response = authed_client.post(
            "/api/v2/pipeline/runs",
            json={},
        )
        assert response.status_code == 422

    def test_validates_idea_too_long(self, authed_client):
        """POST rejects idea exceeding max length."""
        response = authed_client.post(
            "/api/v2/pipeline/runs",
            json={"idea": "x" * 5001},
        )
        assert response.status_code == 422

    def test_creates_run_with_pipeline_execution(self, authed_client, pipeline_store):
        """POST executes the pipeline when available."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "pipeline_id": "pipe-test",
            "stage_status": {"ideation": "complete"},
        }
        mock_result.stage_results = []
        mock_result.stage_status = {"ideation": "complete"}

        with patch(
            "aragora.server.fastapi.routes.pipeline._execute_pipeline",
            return_value=mock_result,
        ):
            response = authed_client.post(
                "/api/v2/pipeline/runs",
                json={"idea": "Build caching layer"},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "completed"
        assert data["result"] is not None

    def test_falls_back_to_pending_on_pipeline_error(self, authed_client, pipeline_store):
        """POST falls back to pending status when pipeline fails."""
        with patch(
            "aragora.server.fastapi.routes.pipeline._execute_pipeline",
            side_effect=RuntimeError("Pipeline unavailable"),
        ):
            response = authed_client.post(
                "/api/v2/pipeline/runs",
                json={"idea": "Handle pipeline failure gracefully"},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "pending"


# =============================================================================
# GET /api/v2/pipeline/runs/{run_id}
# =============================================================================


class TestGetPipelineRun:
    """Tests for GET /api/v2/pipeline/runs/{run_id}."""

    def test_returns_404_for_nonexistent(self, authed_client):
        """Get nonexistent pipeline run returns 404."""
        response = authed_client.get("/api/v2/pipeline/runs/nonexistent-id")
        assert response.status_code == 404

    def test_returns_run_details(self, authed_client, sample_run):
        """Get existing pipeline run returns full details."""
        response = authed_client.get("/api/v2/pipeline/runs/pipe-abc123")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "pipe-abc123"
        assert data["idea"] == "Implement Redis caching for API responses"
        assert data["status"] == "running"
        assert len(data["stages"]) == 4
        assert data["stages"][0]["stage_name"] == "ideation"
        assert data["stages"][0]["status"] == "completed"
        assert data["stages"][1]["stage_name"] == "goals"
        assert data["stages"][1]["status"] == "pending"
        assert data["config"]["dry_run"] is True
        assert data["created_at"] == "2026-02-20T10:00:00"

    def test_returns_completed_run(self, authed_client, completed_run):
        """Get completed pipeline run includes result."""
        response = authed_client.get("/api/v2/pipeline/runs/pipe-done999")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["result"] is not None
        assert data["result"]["pipeline_id"] == "pipe-done999"


# =============================================================================
# GET /api/v2/pipeline/runs/{run_id}/stages
# =============================================================================


class TestGetPipelineStages:
    """Tests for GET /api/v2/pipeline/runs/{run_id}/stages."""

    def test_returns_404_for_nonexistent(self, authed_client):
        """Stages endpoint returns 404 for nonexistent run."""
        response = authed_client.get("/api/v2/pipeline/runs/nonexistent/stages")
        assert response.status_code == 404

    def test_returns_all_stages(self, authed_client, sample_run):
        """Stages endpoint returns all stages for a run."""
        response = authed_client.get("/api/v2/pipeline/runs/pipe-abc123/stages")
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "pipe-abc123"
        assert data["total"] == 4
        assert len(data["stages"]) == 4

        # Check stage details
        ideation = data["stages"][0]
        assert ideation["stage_name"] == "ideation"
        assert ideation["status"] == "completed"
        assert ideation["duration"] == 1.5
        assert ideation["output"] == {"type": "Canvas"}
        assert ideation["started_at"] == "2026-02-20T10:00:00"
        assert ideation["completed_at"] == "2026-02-20T10:01:00"

        goals = data["stages"][1]
        assert goals["stage_name"] == "goals"
        assert goals["status"] == "pending"
        assert goals["output"] is None

    def test_returns_stages_for_completed_run(self, authed_client, completed_run):
        """Stages endpoint works for completed runs."""
        response = authed_client.get("/api/v2/pipeline/runs/pipe-done999/stages")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert all(s["status"] == "completed" for s in data["stages"])


# =============================================================================
# POST /api/v2/pipeline/runs/{run_id}/approve
# =============================================================================


class TestApprovePipelineStage:
    """Tests for POST /api/v2/pipeline/runs/{run_id}/approve."""

    def test_requires_auth(self, client, sample_run):
        """Approve endpoint requires authentication."""
        response = client.post(
            "/api/v2/pipeline/runs/pipe-abc123/approve",
            json={"stage": "goals"},
        )
        assert response.status_code == 401

    def test_approves_pending_stage(self, authed_client, sample_run):
        """Approve marks a pending stage as completed."""
        response = authed_client.post(
            "/api/v2/pipeline/runs/pipe-abc123/approve",
            json={"stage": "goals"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["approved"] is True
        assert data["run_id"] == "pipe-abc123"
        assert data["stage"] == "goals"

    def test_approve_with_feedback(self, authed_client, sample_run):
        """Approve accepts optional feedback."""
        response = authed_client.post(
            "/api/v2/pipeline/runs/pipe-abc123/approve",
            json={"stage": "goals", "feedback": "Looks good, proceed with workflow"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["approved"] is True

    def test_returns_404_for_nonexistent(self, authed_client):
        """Approve returns 404 for nonexistent run."""
        response = authed_client.post(
            "/api/v2/pipeline/runs/nonexistent/approve",
            json={"stage": "goals"},
        )
        assert response.status_code == 404

    def test_rejects_invalid_stage_name(self, authed_client, sample_run):
        """Approve rejects invalid stage names."""
        response = authed_client.post(
            "/api/v2/pipeline/runs/pipe-abc123/approve",
            json={"stage": "invalid_stage"},
        )
        assert response.status_code == 400

    def test_rejects_already_completed_stage(self, authed_client, sample_run):
        """Approve rejects already completed stages."""
        response = authed_client.post(
            "/api/v2/pipeline/runs/pipe-abc123/approve",
            json={"stage": "ideation"},
        )
        assert response.status_code == 400
        assert "already completed" in response.json()["detail"]

    def test_rejects_cancelled_run(self, authed_client, cancelled_run):
        """Approve rejects cancelled pipeline runs."""
        response = authed_client.post(
            "/api/v2/pipeline/runs/pipe-cancel1/approve",
            json={"stage": "ideation"},
        )
        assert response.status_code == 400
        assert "cancelled" in response.json()["detail"]

    def test_validates_missing_stage(self, authed_client, sample_run):
        """Approve rejects request without stage field."""
        response = authed_client.post(
            "/api/v2/pipeline/runs/pipe-abc123/approve",
            json={},
        )
        assert response.status_code == 422

    def test_approving_all_stages_completes_run(self, authed_client, pipeline_store):
        """Approving all stages transitions run to completed."""
        run = {
            "id": "pipe-gate1",
            "idea": "Test gate completion",
            "status": "running",
            "stages": [
                {
                    "stage_name": "ideation",
                    "status": "completed",
                    "output": None,
                    "started_at": None,
                    "completed_at": None,
                    "duration": 0.0,
                    "error": None,
                },
                {
                    "stage_name": "goals",
                    "status": "pending",
                    "output": None,
                    "started_at": None,
                    "completed_at": None,
                    "duration": 0.0,
                    "error": None,
                },
            ],
            "created_at": "2026-02-20T10:00:00",
            "updated_at": "2026-02-20T10:00:00",
            "config": {},
            "result": None,
            "org_id": ORG,
        }
        pipeline_store["pipe-gate1"] = run

        response = authed_client.post(
            "/api/v2/pipeline/runs/pipe-gate1/approve",
            json={"stage": "goals"},
        )
        assert response.status_code == 200
        assert pipeline_store["pipe-gate1"]["status"] == "completed"

    def test_approve_stage_not_in_run(self, authed_client, sample_run):
        """Approve rejects stage that exists but is not in this run."""
        response = authed_client.post(
            "/api/v2/pipeline/runs/pipe-abc123/approve",
            json={"stage": "principles"},
        )
        assert response.status_code == 400
        assert "not found in this pipeline run" in response.json()["detail"]


# =============================================================================
# DELETE /api/v2/pipeline/runs/{run_id}
# =============================================================================


class TestCancelPipelineRun:
    """Tests for DELETE /api/v2/pipeline/runs/{run_id}."""

    def test_requires_auth(self, client, sample_run):
        """DELETE pipeline runs requires authentication."""
        response = client.delete("/api/v2/pipeline/runs/pipe-abc123")
        assert response.status_code == 401

    def test_cancels_running_run(self, authed_client, sample_run, pipeline_store):
        """DELETE cancels a running pipeline run."""
        response = authed_client.delete("/api/v2/pipeline/runs/pipe-abc123")
        assert response.status_code == 200
        data = response.json()
        assert data["cancelled"] is True
        assert data["id"] == "pipe-abc123"

        # Verify state updated
        assert pipeline_store["pipe-abc123"]["status"] == "cancelled"

    def test_marks_pending_stages_as_skipped(self, authed_client, sample_run, pipeline_store):
        """DELETE marks pending stages as skipped."""
        authed_client.delete("/api/v2/pipeline/runs/pipe-abc123")

        stages = pipeline_store["pipe-abc123"]["stages"]
        # ideation was completed, should stay completed
        assert stages[0]["status"] == "completed"
        # goals, workflow, orchestration were pending, should become skipped
        assert stages[1]["status"] == "skipped"
        assert stages[2]["status"] == "skipped"
        assert stages[3]["status"] == "skipped"

    def test_returns_404_for_nonexistent(self, authed_client):
        """DELETE returns 404 for nonexistent run."""
        response = authed_client.delete("/api/v2/pipeline/runs/nonexistent")
        assert response.status_code == 404

    def test_rejects_already_completed(self, authed_client, completed_run):
        """DELETE rejects already completed runs."""
        response = authed_client.delete("/api/v2/pipeline/runs/pipe-done999")
        assert response.status_code == 400
        assert "already completed" in response.json()["detail"]

    def test_rejects_already_cancelled(self, authed_client, cancelled_run):
        """DELETE rejects already cancelled runs."""
        response = authed_client.delete("/api/v2/pipeline/runs/pipe-cancel1")
        assert response.status_code == 400
        assert "already cancelled" in response.json()["detail"]


# =============================================================================
# POST /api/v2/pipeline/runs/{run_id}/execute-workflow
# =============================================================================


class TestExecuteWorkflowFromPipeline:
    """Tests for POST /api/v2/pipeline/runs/{run_id}/execute-workflow."""

    def test_requires_auth(self, client, workflow_ready_run):
        """Execute-workflow endpoint requires authentication."""
        response = client.post("/api/v2/pipeline/runs/pipe-workflow1/execute-workflow")
        assert response.status_code == 401

    def test_uses_workflow_handlers_and_returns_execution_id(
        self,
        authed_client,
        workflow_ready_run,
        pipeline_store,
    ):
        """Execute-workflow persists and executes via the workflow subsystem."""
        with (
            patch(
                "aragora.server.handlers.workflows.crud.create_workflow",
                new_callable=AsyncMock,
            ) as mock_create_workflow,
            patch(
                "aragora.server.handlers.workflows.execution.execute_workflow",
                new_callable=AsyncMock,
            ) as mock_execute_workflow,
        ):
            mock_create_workflow.return_value = {
                "id": "wf_pipe_workflow1",
                "name": "Workflow from pipeline pipe-workflow1",
            }
            mock_execute_workflow.return_value = {
                "id": "exec_abc123",
                "workflow_id": "wf_pipe_workflow1",
                "status": "running",
            }

            response = authed_client.post("/api/v2/pipeline/runs/pipe-workflow1/execute-workflow")

        assert response.status_code == 201
        data = response.json()
        assert data["pipeline_id"] == "pipe-workflow1"
        assert data["workflow_id"] == "wf_pipe_workflow1"
        assert data["execution_id"] == "exec_abc123"
        assert data["status"] == "running"
        assert data["steps_count"] == 1
        assert data["transitions_count"] == 0

        mock_create_workflow.assert_awaited_once()
        create_args = mock_create_workflow.await_args
        # The caller's workspace is "ws-1", but the rows belong to its org.
        assert create_args.kwargs["tenant_id"] == "org-1"
        assert create_args.kwargs["created_by"] == "user-1"
        assert create_args.args[0]["id"] == "wf-pipe-workflow1"
        assert create_args.args[0]["steps"][0]["id"] == "goal-1"

        mock_execute_workflow.assert_awaited_once_with(
            "wf_pipe_workflow1",
            inputs={"pipeline_id": "pipe-workflow1"},
            tenant_id="org-1",
            user_id="user-1",
            org_id="org-1",
        )

        assert pipeline_store["pipe-workflow1"]["workflow_id"] == "wf_pipe_workflow1"
        assert pipeline_store["pipe-workflow1"]["execution_id"] == "exec_abc123"

    def test_rejects_pipeline_without_executable_goals(
        self,
        authed_client,
        no_goal_workflow_run,
    ):
        """Execute-workflow returns a helpful 400 when the goal graph is empty."""
        response = authed_client.post("/api/v2/pipeline/runs/pipe-no-goals1/execute-workflow")
        assert response.status_code == 400
        assert "no executable workflow steps" in response.json()["detail"]

    def test_returns_404_for_nonexistent(self, authed_client):
        """Execute-workflow returns 404 for nonexistent run."""
        response = authed_client.post("/api/v2/pipeline/runs/nonexistent/execute-workflow")
        assert response.status_code == 404

    def test_requires_completed_result(self, authed_client, sample_run):
        """Execute-workflow rejects runs that do not have a stored result yet."""
        response = authed_client.post("/api/v2/pipeline/runs/pipe-abc123/execute-workflow")
        assert response.status_code == 400
        assert "run the pipeline first" in response.json()["detail"]


# =============================================================================
# Edge Cases and Integration
# =============================================================================


class TestPipelineEdgeCases:
    """Edge case and integration tests."""

    def test_multiple_runs_isolation(self, authed_client, pipeline_store):
        """Multiple pipeline runs are isolated from each other."""
        with patch(
            "aragora.server.fastapi.routes.pipeline._execute_pipeline",
            side_effect=ImportError("mocked"),
        ):
            resp1 = authed_client.post(
                "/api/v2/pipeline/runs",
                json={"idea": "First idea"},
            )
            resp2 = authed_client.post(
                "/api/v2/pipeline/runs",
                json={"idea": "Second idea"},
            )

        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["id"] != resp2.json()["id"]
        assert len(pipeline_store) == 2

    def test_list_after_create(self, authed_client, pipeline_store):
        """Listing runs reflects newly created runs."""
        with patch(
            "aragora.server.fastapi.routes.pipeline._execute_pipeline",
            side_effect=ImportError("mocked"),
        ):
            authed_client.post(
                "/api/v2/pipeline/runs",
                json={"idea": "New idea"},
            )

        response = authed_client.get("/api/v2/pipeline/runs")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_get_after_cancel(self, authed_client, sample_run, pipeline_store):
        """Getting a run after cancel reflects cancelled status."""
        authed_client.delete("/api/v2/pipeline/runs/pipe-abc123")

        response = authed_client.get("/api/v2/pipeline/runs/pipe-abc123")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"

    def test_stages_after_approve(self, authed_client, sample_run, pipeline_store):
        """Getting stages after approve reflects updated status."""
        authed_client.post(
            "/api/v2/pipeline/runs/pipe-abc123/approve",
            json={"stage": "goals"},
        )

        response = authed_client.get("/api/v2/pipeline/runs/pipe-abc123/stages")
        assert response.status_code == 200
        stages = response.json()["stages"]
        goals_stage = next(s for s in stages if s["stage_name"] == "goals")
        assert goals_stage["status"] == "completed"
        assert goals_stage["completed_at"] is not None
