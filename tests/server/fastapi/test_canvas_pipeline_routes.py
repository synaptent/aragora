"""
Tests for FastAPI canvas pipeline route endpoints.

Covers all 31 canvas pipeline v2 endpoints including:
- Pipeline creation (from-debate, from-ideas, from-braindump, from-template, demo)
- Pipeline execution (advance, run, auto-run, execute, self-improve)
- Pipeline querying (get, status, stage, graph, receipt, templates)
- Conversion (extract-goals, extract-principles, convert debate/workflow)
- Intelligence (intelligence, beliefs, explanations, precedents)
- Agent management (list, approve, reject)
- Canvas state (save)
"""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from aragora.pipeline.backbone_errors import BackbonePersistenceError, FAIL_CLOSED_BACKBONE_MESSAGE
from aragora.server.fastapi import create_app
from aragora.server.fastapi.dependencies.pipeline_access import PipelineCaller
from aragora.server.fastapi.routes.canvas_pipeline import ExecuteRequest, execute_pipeline
from aragora.tenancy.record_scope import OrgScope, require_org_scope_fastapi

ORG = "org-test"


@pytest.fixture
def app():
    """Create a test FastAPI app."""
    return create_app()


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def _bypass_auth(app):
    """Act as an admin of ``ORG`` using FastAPI dependency overrides."""
    from aragora.rbac.models import AuthorizationContext
    from aragora.server.fastapi.dependencies.auth import require_authenticated

    mock_ctx = AuthorizationContext(
        user_id="test-user",
        user_email="test@example.com",
        org_id=ORG,
        roles={"admin"},
        permissions={"*"},
    )
    app.dependency_overrides[require_authenticated] = lambda: mock_ctx
    app.dependency_overrides[require_org_scope_fastapi] = lambda: OrgScope(
        org_id=ORG, user_id="test-user", role="admin"
    )
    yield
    app.dependency_overrides.pop(require_authenticated, None)
    app.dependency_overrides.pop(require_org_scope_fastapi, None)


def _caller() -> PipelineCaller:
    return PipelineCaller(
        auth=MagicMock(), scope=OrgScope(org_id=ORG, user_id="test-user", role="admin")
    )


@pytest.fixture
def mock_pipeline_store(monkeypatch):
    """Mock the pipeline store; every pipeline in it belongs to ``ORG``."""
    store = {}
    mock_store = MagicMock()
    mock_store.get = MagicMock(side_effect=lambda k: store.get(k))
    mock_store.get_owner_org = MagicMock(side_effect=lambda k: ORG if k in store else None)
    mock_store.save = MagicMock(side_effect=lambda k, v, **_owner: store.__setitem__(k, v))
    monkeypatch.setattr(
        "aragora.server.fastapi.routes.canvas_pipeline._get_store",
        lambda: mock_store,
    )
    return store


@pytest.fixture
def sample_pipeline_result():
    """Create a sample PipelineResult mock."""
    result = MagicMock()
    result.pipeline_id = "pipe-test1234"
    result.stage_status = {
        "ideation": "complete",
        "goals": "complete",
        "workflow": "pending",
        "orchestration": "pending",
    }
    result.ideas_canvas = MagicMock()
    result.ideas_canvas.nodes = {"n1": {}, "n2": {}}
    result.actions_canvas = MagicMock()
    result.actions_canvas.nodes = {"a1": {}}
    result.orchestration_canvas = None
    result.universal_graph = None
    result.to_dict.return_value = {
        "pipeline_id": "pipe-test1234",
        "stage_status": result.stage_status,
    }
    return result


# =============================================================================
# Template listing (no auth required)
# =============================================================================


class TestListTemplates:
    """Tests for GET /api/v2/canvas/pipeline/templates."""

    def test_list_templates_returns_200(self, client):
        """Templates endpoint returns 200 even when module unavailable."""
        resp = client.get("/api/v2/canvas/pipeline/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert "templates" in data
        assert "total" in data
        assert isinstance(data["templates"], list)


# =============================================================================
# Pipeline Creation
# =============================================================================


class TestPipelineCreation:
    """Tests for pipeline creation endpoints."""

    @pytest.mark.usefixtures("_bypass_auth")
    def test_from_ideas_requires_ideas(self, client):
        """from-ideas rejects empty ideas list."""
        resp = client.post(
            "/api/v2/canvas/pipeline/from-ideas",
            json={"ideas": []},
        )
        assert resp.status_code == 422  # Validation error: min_length=1

    @pytest.mark.usefixtures("_bypass_auth")
    def test_from_braindump_requires_text(self, client):
        """from-braindump rejects empty text."""
        resp = client.post(
            "/api/v2/canvas/pipeline/from-braindump",
            json={"text": ""},
        )
        assert resp.status_code == 422  # Validation error: min_length=1

    @pytest.mark.usefixtures("_bypass_auth")
    def test_from_braindump_with_unified_orchestrator_metadata(
        self,
        client,
        mock_pipeline_store,
    ):
        """from-braindump can include unified-orchestrator run metadata."""
        mock_result = MagicMock()
        mock_result.pipeline_id = "pipe-mock9999"
        mock_result.stage_status = {"ideas": "complete", "goals": "pending"}
        mock_result.ideas_canvas = MagicMock()
        mock_result.ideas_canvas.nodes = {"n1": {}}
        mock_result.actions_canvas = None
        mock_result.orchestration_canvas = None
        mock_result.universal_graph = None
        mock_result.to_dict.return_value = {
            "pipeline_id": "pipe-mock9999",
            "stage_status": {"ideas": "complete", "goals": "pending"},
        }

        with (
            patch(
                "aragora.pipeline.idea_to_execution.IdeaToExecutionPipeline.from_brain_dump",
                new=AsyncMock(return_value=mock_result),
            ) as mock_from_brain_dump,
            patch(
                "aragora.server.handlers.canvas_pipeline.CanvasPipelineHandler._run_unified_orchestrator",
                new=AsyncMock(
                    return_value=(
                        {
                            "enabled": True,
                            "run_id": "run-fastapi-1",
                            "succeeded": True,
                            "debate_id": "deb-fastapi-1",
                            "debate_url": "/debates/deb-fastapi-1",
                        },
                        "extra context",
                    )
                ),
            ) as mock_orchestrator,
        ):
            resp = client.post(
                "/api/v2/canvas/pipeline/from-braindump",
                json={
                    "text": "Improve onboarding",
                    "use_unified_orchestrator": True,
                },
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["pipeline_id"] == "pipe-mock9999"
        assert body["unified_orchestrator"]["run_id"] == "run-fastapi-1"
        assert body["debate_id"] == "deb-fastapi-1"
        assert body["debate_url"] == "/debates/deb-fastapi-1"
        mock_orchestrator.assert_awaited_once()
        mock_from_brain_dump.assert_awaited_once()

    @pytest.mark.usefixtures("_bypass_auth")
    def test_from_debate_requires_cartographer_data(self, client):
        """from-debate requires cartographer_data field."""
        resp = client.post(
            "/api/v2/canvas/pipeline/from-debate",
            json={},
        )
        assert resp.status_code == 422  # Missing required field

    @pytest.mark.usefixtures("_bypass_auth")
    def test_from_ideas_with_mock_pipeline(self, client, monkeypatch):
        """from-ideas succeeds with mocked pipeline backend."""
        mock_result = MagicMock()
        mock_result.pipeline_id = "pipe-mock1234"
        mock_result.stage_status = {"ideation": "complete"}
        mock_result.ideas_canvas = MagicMock()
        mock_result.ideas_canvas.nodes = {"n1": {}}
        mock_result.actions_canvas = None
        mock_result.orchestration_canvas = None
        mock_result.universal_graph = None
        mock_result.to_dict.return_value = {"pipeline_id": "pipe-mock1234"}

        mock_pipeline_cls = MagicMock()
        mock_pipeline_cls.return_value.from_ideas.return_value = mock_result

        monkeypatch.setattr(
            "aragora.server.fastapi.routes.canvas_pipeline._get_store",
            lambda: MagicMock(),
        )

        with patch(
            "aragora.pipeline.idea_to_execution.IdeaToExecutionPipeline",
            mock_pipeline_cls,
        ):
            resp = client.post(
                "/api/v2/canvas/pipeline/from-ideas",
                json={"ideas": ["Test idea 1", "Test idea 2"]},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["pipeline_id"] == "pipe-mock1234"
        assert data["stages_completed"] == 1

    @pytest.mark.usefixtures("_bypass_auth")
    def test_demo_pipeline_delegates_to_from_ideas(self, client, monkeypatch):
        """Demo endpoint creates pipeline with sample ideas."""
        mock_result = MagicMock()
        mock_result.pipeline_id = "pipe-demo-test"
        mock_result.stage_status = {"ideation": "complete"}
        mock_result.ideas_canvas = None
        mock_result.actions_canvas = None
        mock_result.orchestration_canvas = None
        mock_result.universal_graph = None
        mock_result.to_dict.return_value = {"pipeline_id": "pipe-demo-test"}

        mock_pipeline_cls = MagicMock()
        mock_pipeline_cls.return_value.from_ideas.return_value = mock_result

        monkeypatch.setattr(
            "aragora.server.fastapi.routes.canvas_pipeline._get_store",
            lambda: MagicMock(),
        )

        with patch(
            "aragora.pipeline.idea_to_execution.IdeaToExecutionPipeline",
            mock_pipeline_cls,
        ):
            resp = client.post("/api/v2/canvas/pipeline/demo")

        assert resp.status_code == 201
        data = resp.json()
        assert "pipe-demo" in data["pipeline_id"]


# =============================================================================
# Pipeline Querying
# =============================================================================


@pytest.mark.usefixtures("_bypass_auth")
class TestPipelineQuerying:
    """Tests for pipeline query endpoints."""

    def test_get_pipeline_not_found(self, client, mock_pipeline_store):
        """Get pipeline returns 404 for unknown ID."""
        resp = client.get("/api/v2/canvas/pipeline/nonexistent")
        assert resp.status_code == 404

    def test_get_pipeline_from_store(self, client, mock_pipeline_store):
        """Get pipeline returns stored data."""
        mock_pipeline_store["pipe-test"] = {
            "pipeline_id": "pipe-test",
            "stage_status": {"ideation": "complete"},
        }
        resp = client.get("/api/v2/canvas/pipeline/pipe-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pipeline_id"] == "pipe-test"

    def test_get_pipeline_includes_unified_live_state(self, client, mock_pipeline_store):
        """Get pipeline normalizes orchestration, review, repair, and merge-gate state."""
        mock_pipeline_store["pipe-live"] = {
            "pipeline_id": "pipe-live",
            "stage_status": {"orchestration": "running"},
            "orchestration": {
                "nodes": [
                    {
                        "id": "orch-1",
                        "type": "orchestrationNode",
                        "data": {
                            "label": "Apply patch",
                            "orch_type": "agent_task",
                            "status": "pending",
                            "executionStatus": "running",
                        },
                    },
                    {
                        "id": "orch-2",
                        "type": "orchestrationNode",
                        "data": {
                            "label": "Verify rollout",
                            "orch_type": "verification",
                            "status": "completed",
                        },
                    },
                ],
                "edges": [],
            },
            "transitions": [
                {
                    "id": "trans-actions-orch",
                    "from_stage": "actions",
                    "to_stage": "orchestration",
                    "status": "pending",
                    "confidence": 0.83,
                },
            ],
            "agents": [
                {"id": "agent-1", "name": "Claude", "role": "reviewer", "status": "pending"},
            ],
            "repair": {
                "status": "in_progress",
                "attempts": 2,
                "items": [{"title": "Retry flaky verification"}],
            },
            "merge_gate": {
                "checks_passed": False,
                "merge_eligible": False,
                "expected_checks": ["pytest"],
            },
            "execution": {
                "status": "running",
                "runtime": "decision_plan",
                "agent_tasks": 1,
                "total_orchestration_nodes": 2,
            },
        }

        resp = client.get("/api/v2/canvas/pipeline/pipe-live")
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["live_state"]["orchestration"]["status"] == "running"
        assert result["live_state"]["orchestration"]["active_nodes"][0]["label"] == "Apply patch"
        assert result["live_state"]["orchestration"]["counts"]["in_progress"] == 1
        assert result["live_state"]["orchestration"]["counts"]["succeeded"] == 1
        assert result["live_state"]["review"]["transition_counts"]["pending"] == 1
        assert result["live_state"]["review"]["reviewer_agents"] == 1
        assert result["live_state"]["review"]["human_gates"] == 1
        assert result["live_state"]["repair"]["status"] == "in_progress"
        assert (
            result["live_state"]["repair"]["active_items"][0]["title"] == "Retry flaky verification"
        )
        assert result["live_state"]["merge_gate"]["blocked_reasons"] == []
        assert result["live_state"]["merge_gate"]["enabled"] is False

    def test_get_pipeline_status(self, client, mock_pipeline_store):
        """Status endpoint returns stage breakdown."""
        mock_pipeline_store["pipe-s1"] = {
            "pipeline_id": "pipe-s1",
            "stage_status": {
                "ideation": "complete",
                "goals": "complete",
                "workflow": "running",
                "orchestration": "pending",
            },
        }
        resp = client.get("/api/v2/canvas/pipeline/pipe-s1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["completed_stages"] == 2
        assert data["total_stages"] == 4
        assert data["current_stage"] == "workflow"


@pytest.mark.usefixtures("_bypass_auth")
class TestPipelineExecution:
    @pytest.mark.asyncio
    async def test_execute_pipeline_background_task_updates_store(self, monkeypatch):
        pipeline = {
            "pipeline_id": "pipe-fastapi",
            "name": "Pipeline FastAPI",
            "stage_status": {
                "ideas": "complete",
                "goals": "complete",
                "actions": "complete",
                "orchestration": "complete",
            },
            "orchestration": {
                "nodes": [
                    {"id": "t1", "data": {"orch_type": "agent_task", "label": "Ship feature"}},
                ],
                "edges": [],
            },
        }
        store = MagicMock()
        monkeypatch.setattr(
            "aragora.server.fastapi.routes.canvas_pipeline._get_result_or_404",
            AsyncMock(return_value=pipeline),
        )
        monkeypatch.setattr(
            "aragora.server.fastapi.routes.canvas_pipeline._get_store",
            lambda: store,
        )

        fake_execution = types.ModuleType("aragora.pipeline.canonical_execution")
        fake_execution.build_decision_plan_from_orchestration = lambda **_: (
            types.SimpleNamespace(id="plan-fastapi"),
            [{"id": "t1"}],
        )
        fake_execution.queue_plan_execution = lambda *_, **__: {
            "execution_id": "exec-fastapi",
            "correlation_id": "corr-fastapi",
            "execution_mode": "workflow",
            "scheduled_at": "2026-03-21T00:00:00Z",
        }

        outcome = MagicMock(success=True, receipt_id="receipt-fastapi")
        outcome.to_dict.return_value = {"success": True}

        async def _execute_plan(*_, **__):
            return outcome, {"record_id": "record-fastapi"}, {"receipt_id": "decision-fastapi"}

        fake_execution.execute_queued_plan = _execute_plan

        original_create_task = asyncio.create_task
        created_tasks: list[asyncio.Task] = []

        def _capture_task(coro):
            task = original_create_task(coro)
            created_tasks.append(task)
            return task

        with (
            patch.dict(sys.modules, {"aragora.pipeline.canonical_execution": fake_execution}),
            patch(
                "aragora.server.fastapi.routes.canvas_pipeline.asyncio.create_task",
                new=_capture_task,
            ),
        ):
            response = await execute_pipeline(
                "pipe-fastapi",
                ExecuteRequest(),
                caller=_caller(),
            )

        assert response.result is not None
        assert response.result["status"] == "executing"
        assert len(created_tasks) == 1
        await created_tasks[0]
        assert created_tasks[0].exception() is None
        assert "execution" not in pipeline
        assert "receipt" not in pipeline

        saves = store.save_for_org.call_args_list
        assert {call.args[2:] for call in saves} == {(ORG, "test-user")}
        assert "live_state" not in saves[0].args[1]
        assert "live_state" not in saves[1].args[1]

        saved_pipeline = saves[-1].args[1]
        assert saved_pipeline["execution"]["status"] == "completed"
        assert saved_pipeline["execution"]["receipt_id"] == "receipt-fastapi"
        assert saved_pipeline["live_state"]["orchestration"]["status"] == "completed"
        assert (
            saved_pipeline["live_state"]["orchestration"]["active_nodes"][0]["label"]
            == "Ship feature"
        )

    @pytest.mark.asyncio
    async def test_execute_pipeline_backbone_failure_returns_503(self, monkeypatch):
        pipeline = {
            "pipeline_id": "pipe-fastapi-backbone",
            "name": "FastAPI Backbone",
            "stage_status": {
                "ideas": "complete",
                "goals": "complete",
                "actions": "complete",
                "orchestration": "complete",
            },
            "orchestration": {
                "nodes": [
                    {"id": "t1", "data": {"orch_type": "agent_task", "label": "Ship feature"}},
                ],
                "edges": [],
            },
        }
        store = MagicMock()
        monkeypatch.setattr(
            "aragora.server.fastapi.routes.canvas_pipeline._get_result_or_404",
            AsyncMock(return_value=pipeline),
        )
        monkeypatch.setattr(
            "aragora.server.fastapi.routes.canvas_pipeline._get_store",
            lambda: store,
        )

        fake_execution = types.ModuleType("aragora.pipeline.canonical_execution")
        fake_execution.build_decision_plan_from_orchestration = lambda **_: (
            types.SimpleNamespace(id="plan-fastapi"),
            [{"id": "t1"}],
        )

        def _raise_backbone(*_, **__):
            raise BackbonePersistenceError("run ledger unavailable")

        fake_execution.queue_plan_execution = _raise_backbone
        fake_execution.execute_queued_plan = AsyncMock()

        with patch.dict(sys.modules, {"aragora.pipeline.canonical_execution": fake_execution}):
            with pytest.raises(Exception) as excinfo:
                await execute_pipeline(
                    "pipe-fastapi-backbone",
                    ExecuteRequest(),
                    caller=_caller(),
                )

        assert getattr(excinfo.value, "status_code", None) == 503
        assert getattr(excinfo.value, "detail", None) == FAIL_CLOSED_BACKBONE_MESSAGE

    def test_get_pipeline_stage_invalid(self, client, mock_pipeline_store):
        """Stage endpoint rejects invalid stage name."""
        mock_pipeline_store["pipe-x"] = {"pipeline_id": "pipe-x", "stage_status": {}}
        resp = client.get("/api/v2/canvas/pipeline/pipe-x/stage/invalid")
        assert resp.status_code == 400

    def test_get_pipeline_stage_valid(self, client, mock_pipeline_store):
        """Stage endpoint returns canvas data."""
        mock_pipeline_store["pipe-y"] = {
            "pipeline_id": "pipe-y",
            "stage_status": {"ideation": "complete"},
            "ideas_canvas": {"nodes": {"n1": {}, "n2": {}}, "edges": []},
        }
        resp = client.get("/api/v2/canvas/pipeline/pipe-y/stage/ideas")
        assert resp.status_code == 200
        data = resp.json()
        assert data["stage"] == "ideas"
        assert data["node_count"] == 2

    def test_get_pipeline_graph_empty(self, client, mock_pipeline_store):
        """Graph endpoint returns empty when no universal graph."""
        mock_pipeline_store["pipe-g"] = {
            "pipeline_id": "pipe-g",
            "stage_status": {},
        }
        resp = client.get("/api/v2/canvas/pipeline/pipe-g/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []
        assert data["edges"] == []

    def test_get_pipeline_receipt_no_receipt(self, client, mock_pipeline_store):
        """Receipt endpoint returns has_receipt=False when generator unavailable."""
        mock_pipeline_store["pipe-r"] = {
            "pipeline_id": "pipe-r",
            "stage_status": {},
        }
        with patch(
            "aragora.pipeline.receipt_generator.generate_pipeline_receipt",
            side_effect=ValueError("incomplete pipeline data"),
        ):
            resp = client.get("/api/v2/canvas/pipeline/pipe-r/receipt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_receipt"] is False


# =============================================================================
# Intelligence Endpoints
# =============================================================================


@pytest.mark.usefixtures("_bypass_auth")
class TestIntelligence:
    """Tests for intelligence overlay endpoints."""

    def test_intelligence_returns_empty_when_unavailable(self, client, mock_pipeline_store):
        """Intelligence endpoint returns empty lists gracefully."""
        mock_pipeline_store["pipe-i1"] = {
            "pipeline_id": "pipe-i1",
            "stage_status": {},
        }
        resp = client.get("/api/v2/canvas/pipeline/pipe-i1/intelligence")
        assert resp.status_code == 200
        data = resp.json()
        assert data["beliefs"] == []
        assert data["explanations"] == []
        assert data["precedents"] == []

    def test_beliefs_returns_empty(self, client, mock_pipeline_store):
        """Beliefs endpoint returns empty list gracefully."""
        mock_pipeline_store["pipe-b1"] = {
            "pipeline_id": "pipe-b1",
            "stage_status": {},
        }
        resp = client.get("/api/v2/canvas/pipeline/pipe-b1/beliefs")
        assert resp.status_code == 200
        assert resp.json()["beliefs"] == []

    def test_explanations_returns_empty(self, client, mock_pipeline_store):
        """Explanations endpoint returns empty list gracefully."""
        mock_pipeline_store["pipe-e1"] = {
            "pipeline_id": "pipe-e1",
            "stage_status": {},
        }
        resp = client.get("/api/v2/canvas/pipeline/pipe-e1/explanations")
        assert resp.status_code == 200
        assert resp.json()["explanations"] == []

    def test_precedents_returns_empty(self, client, mock_pipeline_store):
        """Precedents endpoint returns empty list gracefully."""
        mock_pipeline_store["pipe-p1"] = {
            "pipeline_id": "pipe-p1",
            "stage_status": {},
        }
        resp = client.get("/api/v2/canvas/pipeline/pipe-p1/precedents")
        assert resp.status_code == 200
        assert resp.json()["precedents"] == []


# =============================================================================
# Agent Management
# =============================================================================


@pytest.mark.usefixtures("_bypass_auth")
class TestAgentManagement:
    """Tests for agent management endpoints."""

    def test_list_agents_empty(self, client, mock_pipeline_store):
        """Agents endpoint returns empty list for pipeline without agents."""
        mock_pipeline_store["pipe-a1"] = {
            "pipeline_id": "pipe-a1",
            "stage_status": {},
        }
        resp = client.get("/api/v2/pipeline/pipe-a1/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agents"] == []
        assert data["total"] == 0

    def test_list_agents_with_data(self, client, mock_pipeline_store):
        """Agents endpoint returns agent list from pipeline data."""
        mock_pipeline_store["pipe-a2"] = {
            "pipeline_id": "pipe-a2",
            "stage_status": {},
            "agents": [
                {"id": "agent-1", "name": "Claude", "role": "executor", "status": "ready"},
                {"id": "agent-2", "name": "Codex", "role": "reviewer", "status": "pending"},
            ],
        }
        resp = client.get("/api/v2/pipeline/pipe-a2/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["agents"][0]["agent_name"] == "Claude"

    @pytest.mark.usefixtures("_bypass_auth")
    def test_approve_agent(self, client, mock_pipeline_store):
        """Approve agent returns success."""
        mock_pipeline_store["pipe-a3"] = {
            "pipeline_id": "pipe-a3",
            "stage_status": {},
        }
        resp = client.post("/api/v2/pipeline/pipe-a3/agents/agent-1/approve")
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "approved"
        assert data["success"] is True

    @pytest.mark.usefixtures("_bypass_auth")
    def test_reject_agent(self, client, mock_pipeline_store):
        """Reject agent returns success."""
        mock_pipeline_store["pipe-a4"] = {
            "pipeline_id": "pipe-a4",
            "stage_status": {},
        }
        resp = client.post("/api/v2/pipeline/pipe-a4/agents/agent-1/reject")
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "rejected"
        assert data["success"] is True


# =============================================================================
# Save Canvas State
# =============================================================================


class TestSaveCanvasState:
    """Tests for PUT /api/v2/canvas/pipeline/{id}."""

    @pytest.mark.usefixtures("_bypass_auth")
    def test_save_canvas_state(self, client, mock_pipeline_store):
        """Save canvas state persists data."""
        mock_pipeline_store["pipe-sv1"] = {"pipeline_id": "pipe-sv1"}
        resp = client.put(
            "/api/v2/canvas/pipeline/pipe-sv1",
            json={"canvas_data": {"nodes": {"n1": {}}}, "stage": "ideas"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["saved"] is True

    @pytest.mark.usefixtures("_bypass_auth")
    def test_save_canvas_never_creates_a_pipeline(self, client, mock_pipeline_store):
        """A client-chosen id that no pipeline has answers 404 and stores nothing."""
        resp = client.put(
            "/api/v2/canvas/pipeline/pipe-new",
            json={"canvas_data": {"nodes": {}}, "stage": "goals"},
        )
        assert resp.status_code == 404
        assert resp.json() == {"error": "Pipeline not found", "code": "not_found"}
        assert mock_pipeline_store == {}


# =============================================================================
# Transition Approval
# =============================================================================


class TestTransitionApproval:
    """Tests for POST /api/v2/canvas/pipeline/{id}/approve-transition."""

    @pytest.mark.usefixtures("_bypass_auth")
    def test_approve_transition(self, client, mock_pipeline_store):
        """Approve transition returns success."""
        mock_pipeline_store["pipe-t1"] = {
            "pipeline_id": "pipe-t1",
            "stage_status": {"ideation": "complete"},
        }
        resp = client.post(
            "/api/v2/canvas/pipeline/pipe-t1/approve-transition",
            json={"approved": True, "feedback": "Looks good"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["approved"] is True

    @pytest.mark.usefixtures("_bypass_auth")
    def test_reject_transition(self, client, mock_pipeline_store):
        """Reject transition returns success."""
        mock_pipeline_store["pipe-t2"] = {
            "pipeline_id": "pipe-t2",
            "stage_status": {},
        }
        resp = client.post(
            "/api/v2/canvas/pipeline/pipe-t2/approve-transition",
            json={"approved": False, "feedback": "Needs revision"},
        )
        assert resp.status_code == 200
        assert resp.json()["approved"] is False


# =============================================================================
# Conversion Endpoints
# =============================================================================


class TestConversion:
    """Tests for conversion endpoints."""

    @pytest.mark.usefixtures("_bypass_auth")
    def test_convert_debate_requires_input(self, client):
        """Convert debate requires debate_id or debate_data."""
        resp = client.post(
            "/api/v2/canvas/convert/debate",
            json={},
        )
        assert resp.status_code == 400

    @pytest.mark.usefixtures("_bypass_auth")
    def test_convert_workflow_requires_input(self, client):
        """Convert workflow requires workflow_id or workflow_data."""
        resp = client.post(
            "/api/v2/canvas/convert/workflow",
            json={},
        )
        assert resp.status_code == 400
