"""Tests for CanvasPipelineHandler from-debate/from-ideas/advance/get/stage/convert endpoints."""

from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aragora.server.handlers.canvas_pipeline import (
    CanvasPipelineHandler,
    _get_store,
    _pipeline_objects,
)


def _body(result) -> dict:
    """Extract JSON body from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


class _UnreadableRfile:
    def read(self, *_args, **_kwargs):
        raise AssertionError("cached body should avoid rfile reads")


class _CompatFakeHandler:
    """Small stand-in for fastapi.compat._FakeHandler."""

    def __init__(self, body: dict[str, object] | bytes, *, include_cached_body: bool = True):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.headers = {
            "Content-Length": str(len(raw)),
            "Content-Type": "application/json",
        }
        self.command = "POST"
        self.path = ""
        if include_cached_body:
            self._body = raw
        self.rfile = BytesIO(raw)


@pytest.fixture(autouse=True)
def _clear_stores():
    """Clear in-memory stores between tests."""
    _pipeline_objects.clear()
    yield
    _pipeline_objects.clear()


@pytest.fixture
def handler():
    return CanvasPipelineHandler()


@pytest.fixture
def sample_cartographer_data():
    return {
        "nodes": [
            {
                "id": "n1",
                "type": "proposal",
                "summary": "Build rate limiter",
                "content": "Token bucket",
            },
            {
                "id": "n2",
                "type": "evidence",
                "summary": "Reduces 429 errors",
                "content": "Evidence",
            },
            {"id": "n3", "type": "critique", "summary": "Distributed?", "content": "Question"},
        ],
        "edges": [
            {"source_id": "n2", "target_id": "n1", "relation": "supports"},
            {"source_id": "n3", "target_id": "n1", "relation": "responds_to"},
        ],
    }


# =========================================================================
# Route registration
# =========================================================================


class TestRouteRegistration:
    def test_from_debate_route(self, handler):
        assert "POST /api/v1/canvas/pipeline/from-debate" in handler.ROUTES

    def test_from_ideas_route(self, handler):
        assert "POST /api/v1/canvas/pipeline/from-ideas" in handler.ROUTES

    def test_advance_route(self, handler):
        assert "POST /api/v1/canvas/pipeline/advance" in handler.ROUTES

    def test_get_pipeline_route(self, handler):
        assert "GET /api/v1/canvas/pipeline/{id}" in handler.ROUTES

    def test_get_stage_route(self, handler):
        assert "GET /api/v1/canvas/pipeline/{id}/stage/{stage}" in handler.ROUTES

    def test_convert_debate_route(self, handler):
        assert "POST /api/v1/canvas/convert/debate" in handler.ROUTES

    def test_convert_workflow_route(self, handler):
        assert "POST /api/v1/canvas/convert/workflow" in handler.ROUTES


# =========================================================================
# handle_from_debate
# =========================================================================


class TestHandleFromDebate:
    @pytest.mark.asyncio
    async def test_missing_cartographer_data(self, handler):
        result = await handler.handle_from_debate({})
        assert "error" in _body(result)

    @pytest.mark.asyncio
    async def test_empty_cartographer_data(self, handler):
        result = await handler.handle_from_debate({"cartographer_data": {}})
        assert "error" in _body(result)

    @pytest.mark.asyncio
    async def test_from_debate_returns_pipeline(self, handler, sample_cartographer_data):
        result = await handler.handle_from_debate(
            {
                "cartographer_data": sample_cartographer_data,
                "auto_advance": True,
            }
        )
        body = _body(result)
        assert "pipeline_id" in body
        assert body["pipeline_id"].startswith("pipe-")
        assert "stage_status" in body
        assert "result" in body

    @pytest.mark.asyncio
    async def test_from_debate_stores_result(self, handler, sample_cartographer_data):
        result = await handler.handle_from_debate(
            {
                "cartographer_data": sample_cartographer_data,
            }
        )
        body = _body(result)
        pid = body["pipeline_id"]
        assert _get_store().get(pid) is not None
        assert pid in _pipeline_objects

    @pytest.mark.asyncio
    async def test_from_debate_no_auto_advance(self, handler, sample_cartographer_data):
        result = await handler.handle_from_debate(
            {
                "cartographer_data": sample_cartographer_data,
                "auto_advance": False,
            }
        )
        status = _body(result)["stage_status"]
        assert status.get("ideas") == "complete"
        assert status.get("goals") == "pending"

    @pytest.mark.asyncio
    async def test_from_debate_total_nodes(self, handler, sample_cartographer_data):
        result = await handler.handle_from_debate(
            {
                "cartographer_data": sample_cartographer_data,
                "auto_advance": True,
            }
        )
        body = _body(result)
        assert "total_nodes" in body
        assert body["total_nodes"] > 0

    @pytest.mark.asyncio
    async def test_from_debate_stages_completed(self, handler, sample_cartographer_data):
        result = await handler.handle_from_debate(
            {
                "cartographer_data": sample_cartographer_data,
                "auto_advance": True,
            }
        )
        assert _body(result)["stages_completed"] == 4


# =========================================================================
# handle_from_ideas
# =========================================================================


class TestHandleFromIdeas:
    @pytest.mark.asyncio
    async def test_missing_ideas(self, handler):
        result = await handler.handle_from_ideas({})
        assert "error" in _body(result)

    @pytest.mark.asyncio
    async def test_empty_ideas(self, handler):
        result = await handler.handle_from_ideas({"ideas": []})
        assert "error" in _body(result)

    @pytest.mark.asyncio
    async def test_from_ideas_returns_pipeline(self, handler):
        result = await handler.handle_from_ideas(
            {
                "ideas": ["Build a rate limiter", "Add caching"],
            }
        )
        body = _body(result)
        assert "pipeline_id" in body
        assert body["pipeline_id"].startswith("pipe-")
        assert "stage_status" in body
        assert "result" in body

    @pytest.mark.asyncio
    async def test_from_ideas_stores_result(self, handler):
        result = await handler.handle_from_ideas(
            {
                "ideas": ["Idea one", "Idea two"],
            }
        )
        pid = _body(result)["pipeline_id"]
        assert _get_store().get(pid) is not None
        assert pid in _pipeline_objects

    @pytest.mark.asyncio
    async def test_from_ideas_goals_count(self, handler):
        result = await handler.handle_from_ideas(
            {
                "ideas": ["Build rate limiter", "Add caching layer", "Improve docs"],
                "auto_advance": True,
            }
        )
        body = _body(result)
        assert "goals_count" in body
        assert body["goals_count"] > 0

    @pytest.mark.asyncio
    async def test_from_ideas_no_auto_advance(self, handler):
        result = await handler.handle_from_ideas(
            {
                "ideas": ["Some idea"],
                "auto_advance": False,
            }
        )
        status = _body(result)["stage_status"]
        assert status.get("ideas") == "complete"
        assert status.get("goals") == "complete"
        # Actions not generated without auto_advance
        assert status.get("actions") == "pending"


# =========================================================================
# handle_advance
# =========================================================================


class TestHandleAdvance:
    @pytest.mark.asyncio
    async def test_missing_pipeline_id(self, handler):
        result = await handler.handle_advance({})
        assert "error" in _body(result)

    @pytest.mark.asyncio
    async def test_missing_target_stage(self, handler):
        result = await handler.handle_advance({"pipeline_id": "pipe-123"})
        assert "error" in _body(result)

    @pytest.mark.asyncio
    async def test_pipeline_not_found(self, handler):
        result = await handler.handle_advance(
            {
                "pipeline_id": "nonexistent",
                "target_stage": "goals",
            }
        )
        assert "error" in _body(result)

    @pytest.mark.asyncio
    async def test_invalid_stage(self, handler):
        # Create a pipeline first
        ideas_result = await handler.handle_from_ideas(
            {
                "ideas": ["Test idea"],
                "auto_advance": False,
            }
        )
        pid = _body(ideas_result)["pipeline_id"]

        result = await handler.handle_advance(
            {
                "pipeline_id": pid,
                "target_stage": "invalid_stage",
            }
        )
        assert "error" in _body(result)

    @pytest.mark.asyncio
    async def test_advance_to_actions(self, handler):
        # Create pipeline with goals
        ideas_result = await handler.handle_from_ideas(
            {
                "ideas": ["Build rate limiter", "Add caching"],
                "auto_advance": False,
            }
        )
        pid = _body(ideas_result)["pipeline_id"]

        result = await handler.handle_advance(
            {
                "pipeline_id": pid,
                "target_stage": "actions",
            }
        )
        body = _body(result)
        assert body["pipeline_id"] == pid
        assert body["advanced_to"] == "actions"
        assert body["stage_status"]["actions"] == "complete"

    @pytest.mark.asyncio
    async def test_advance_updates_stores(self, handler):
        ideas_result = await handler.handle_from_ideas(
            {
                "ideas": ["Test idea"],
                "auto_advance": False,
            }
        )
        pid = _body(ideas_result)["pipeline_id"]

        await handler.handle_advance(
            {
                "pipeline_id": pid,
                "target_stage": "actions",
            }
        )
        # Both stores should be updated
        stored = _get_store().get(pid)
        assert stored is not None
        assert stored["stage_status"]["actions"] == "complete"


# =========================================================================
# handle_get_pipeline
# =========================================================================


class TestHandleGetPipeline:
    @pytest.mark.asyncio
    async def test_not_found(self, handler):
        result = await handler.handle_get_pipeline("nonexistent")
        assert "error" in _body(result)

    @pytest.mark.asyncio
    async def test_get_existing_pipeline(self, handler):
        create_result = await handler.handle_from_ideas(
            {
                "ideas": ["Test idea"],
                "auto_advance": True,
            }
        )
        pid = _body(create_result)["pipeline_id"]

        result = await handler.handle_get_pipeline(pid)
        body = _body(result)
        assert "pipeline_id" in body
        assert "ideas" in body
        assert "goals" in body


# =========================================================================
# handle_get_stage
# =========================================================================


class TestHandleGetStage:
    @pytest.mark.asyncio
    async def test_pipeline_not_found(self, handler):
        result = await handler.handle_get_stage("nonexistent", "ideas")
        assert "error" in _body(result)

    @pytest.mark.asyncio
    async def test_invalid_stage(self, handler):
        create_result = await handler.handle_from_ideas(
            {
                "ideas": ["Test idea"],
                "auto_advance": True,
            }
        )
        pid = _body(create_result)["pipeline_id"]

        result = await handler.handle_get_stage(pid, "nonexistent")
        assert "error" in _body(result)

    @pytest.mark.asyncio
    async def test_get_ideas_stage(self, handler):
        create_result = await handler.handle_from_ideas(
            {
                "ideas": ["Rate limiter", "Caching"],
                "auto_advance": True,
            }
        )
        pid = _body(create_result)["pipeline_id"]

        result = await handler.handle_get_stage(pid, "ideas")
        body = _body(result)
        assert body["stage"] == "ideas"
        assert "data" in body

    @pytest.mark.asyncio
    async def test_get_goals_stage(self, handler):
        create_result = await handler.handle_from_ideas(
            {
                "ideas": ["Rate limiter", "Caching"],
                "auto_advance": True,
            }
        )
        pid = _body(create_result)["pipeline_id"]

        result = await handler.handle_get_stage(pid, "goals")
        body = _body(result)
        assert body["stage"] == "goals"
        assert "data" in body

    @pytest.mark.asyncio
    async def test_get_actions_stage(self, handler):
        create_result = await handler.handle_from_ideas(
            {
                "ideas": ["Rate limiter", "Caching"],
                "auto_advance": True,
            }
        )
        pid = _body(create_result)["pipeline_id"]

        result = await handler.handle_get_stage(pid, "actions")
        assert _body(result)["stage"] == "actions"

    @pytest.mark.asyncio
    async def test_get_orchestration_stage(self, handler):
        create_result = await handler.handle_from_ideas(
            {
                "ideas": ["Rate limiter", "Caching"],
                "auto_advance": True,
            }
        )
        pid = _body(create_result)["pipeline_id"]

        result = await handler.handle_get_stage(pid, "orchestration")
        assert _body(result)["stage"] == "orchestration"


# =========================================================================
# handle_convert_debate
# =========================================================================


class TestHandleConvertDebate:
    @pytest.mark.asyncio
    async def test_missing_data(self, handler):
        result = await handler.handle_convert_debate({})
        assert "error" in _body(result)

    @pytest.mark.asyncio
    async def test_convert_debate_returns_react_flow(self, handler, sample_cartographer_data):
        result = await handler.handle_convert_debate(
            {
                "cartographer_data": sample_cartographer_data,
            }
        )
        body = _body(result)
        assert "nodes" in body
        assert "edges" in body
        assert len(body["nodes"]) == 3


# =========================================================================
# handle_convert_workflow
# =========================================================================


class TestHandleConvertWorkflow:
    @pytest.mark.asyncio
    async def test_missing_data(self, handler):
        result = await handler.handle_convert_workflow({})
        assert "error" in _body(result)

    @pytest.mark.asyncio
    async def test_convert_workflow_returns_react_flow(self, handler):
        workflow_data = {
            "name": "Test Workflow",
            "steps": [
                {"id": "s1", "name": "Step 1", "type": "task"},
                {"id": "s2", "name": "Step 2", "type": "task"},
            ],
            "transitions": [
                {"from_step": "s1", "to_step": "s2"},
            ],
        }
        result = await handler.handle_convert_workflow(
            {
                "workflow_data": workflow_data,
            }
        )
        body = _body(result)
        assert "nodes" in body
        assert "edges" in body


# =========================================================================
# Route registration for new endpoints
# =========================================================================


class TestNewRouteRegistration:
    def test_list_pipelines_route(self, handler):
        assert "GET /api/v1/canvas/pipeline" in handler.ROUTES

    def test_approve_transition_root_route(self, handler):
        assert "POST /api/v1/canvas/pipeline/approve-transition" in handler.ROUTES


# =========================================================================
# handle_list_or_latest
# =========================================================================


class TestHandleListOrLatest:
    @pytest.fixture(autouse=True)
    def _fresh_db(self):
        """Delete all pipelines from the store for a clean slate."""
        store = _get_store()
        for p in store.list_pipelines(limit=1000):
            store.delete(p["id"])
        yield
        for p in store.list_pipelines(limit=1000):
            store.delete(p["id"])

    @pytest.mark.asyncio
    async def test_empty_store_returns_null(self, handler):
        """When no pipelines exist, returns null so frontend shows empty state."""
        result = await handler.handle_list_or_latest({})
        body = _body(result)
        assert body is None

    @pytest.mark.asyncio
    async def test_returns_latest_pipeline(self, handler, sample_cartographer_data):
        """After creating a pipeline, list_or_latest returns it."""
        create_result = await handler.handle_from_debate(
            {"cartographer_data": sample_cartographer_data, "auto_advance": True}
        )
        pipeline_id = _body(create_result)["pipeline_id"]

        result = await handler.handle_list_or_latest({})
        body = _body(result)
        assert body is not None
        assert body["pipeline_id"] == pipeline_id

    @pytest.mark.asyncio
    async def test_list_mode(self, handler, sample_cartographer_data):
        """?list=true returns a list of pipeline summaries."""
        await handler.handle_from_debate(
            {"cartographer_data": sample_cartographer_data, "auto_advance": True}
        )
        result = await handler.handle_list_or_latest({"list": "true"})
        body = _body(result)
        assert "pipelines" in body
        assert "count" in body
        assert body["count"] >= 1

    @pytest.mark.asyncio
    async def test_latest_has_live_state(self, handler, sample_cartographer_data):
        """Latest pipeline includes unified live state."""
        await handler.handle_from_debate(
            {"cartographer_data": sample_cartographer_data, "auto_advance": True}
        )
        result = await handler.handle_list_or_latest({})
        body = _body(result)
        assert body is not None
        assert "live_state" in body


# =========================================================================
# Request body parsing
# =========================================================================


class TestRequestBodyParsing:
    def test_get_request_body_reads_request_body_first(self, handler):
        http = _CompatFakeHandler({"ignored": True})
        http.request = SimpleNamespace(body=b'{"source": "request"}')
        http._body = b'{"source": "cached"}'
        http.rfile = _UnreadableRfile()

        assert handler._get_request_body(http) == {"source": "request"}

    def test_get_request_body_ignores_callable_request_body(self, handler):
        http = _CompatFakeHandler({"source": "cached"})
        http.request = SimpleNamespace(body=lambda: b'{"source": "callable"}')
        http.rfile = _UnreadableRfile()

        assert handler._get_request_body(http) == {"source": "cached"}

    def test_get_request_body_reads_fastapi_cached_body(self, handler):
        http = _CompatFakeHandler({"source": "cached"})
        http.rfile = _UnreadableRfile()

        assert handler._get_request_body(http) == {"source": "cached"}

    def test_get_request_body_reads_legacy_rfile_with_content_length(self, handler):
        http = _CompatFakeHandler({"source": "rfile"}, include_cached_body=False)

        assert handler._get_request_body(http) == {"source": "rfile"}

    def test_get_request_body_invalid_json_returns_empty_dict(self, handler):
        http = _CompatFakeHandler(b"not-json", include_cached_body=False)

        assert handler._get_request_body(http) == {}


# =========================================================================
# handle_approve_transition — root path with pipeline_id in body
# =========================================================================


class TestHandleApproveTransitionRootPath:
    def _save_pipeline_with_transition(self, pipeline_id: str = "pipe-transition-id") -> str:
        _get_store().save(
            pipeline_id,
            {
                "pipeline_id": pipeline_id,
                "stage_status": {"ideas": "complete", "goals": "pending"},
                "transitions": [
                    {
                        "id": "trans-ideas-goals",
                        "from_stage": "ideas",
                        "to_stage": "goals",
                        "status": "pending",
                    }
                ],
            },
        )
        return pipeline_id

    @pytest.mark.asyncio
    async def test_approve_transition_accepts_generated_transition_alias(self, handler):
        pipeline_id = self._save_pipeline_with_transition("pipe-transition-alias")

        result = await handler.handle_approve_transition(
            pipeline_id,
            {
                "transition_id": "transition-ideas-goals",
                "approved": True,
            },
        )

        body = _body(result)
        assert body["status"] == "approved"
        assert body["from_stage"] == "ideas"
        assert body["to_stage"] == "goals"
        assert body["result"]["transitions"][0]["status"] == "approved"

    @pytest.mark.asyncio
    async def test_root_approve_transition_reads_fastapi_cached_body(self, handler):
        http = _CompatFakeHandler({"pipeline_id": "pipe-fastapi-body"})

        with patch.object(CanvasPipelineHandler, "_check_permission", return_value=None):
            result = handler.handle_post(
                "/api/v1/canvas/pipeline/approve-transition",
                {},
                http,
            )
            if hasattr(result, "__await__"):
                result = await result

        assert result.status_code == 404
        assert _body(result)["error"] == "Pipeline pipe-fastapi-body not found"

    @pytest.mark.asyncio
    async def test_from_ideas_reads_fastapi_cached_body(self, handler):
        http = _CompatFakeHandler(
            {
                "ideas": ["Turn founder review into a bounded pipeline"],
                "auto_advance": False,
            }
        )

        result = handler.handle_post("/api/v1/canvas/pipeline/from-ideas", {}, http)
        if hasattr(result, "__await__"):
            result = await result

        body = _body(result)
        assert result.status_code == 201
        assert body["pipeline_id"].startswith("pipe-")
        assert body["result"]["stage_status"]["actions"] == "pending"
        assert _get_store().get_owner_org(body["pipeline_id"]) == "test-org-001"

    @pytest.mark.asyncio
    async def test_approve_transition_defaults_to_approved(self, handler, sample_cartographer_data):
        """Calling approve-transition without 'approved' field should default to True."""
        create_result = await handler.handle_from_debate(
            {"cartographer_data": sample_cartographer_data, "auto_advance": True}
        )
        pipeline_id = _body(create_result)["pipeline_id"]

        result = await handler.handle_approve_transition(
            pipeline_id,
            {
                "from_stage": "ideas",
                "to_stage": "goals",
            },
        )
        body = _body(result)
        assert body["status"] == "approved"

    @pytest.mark.asyncio
    async def test_reject_transition(self, handler, sample_cartographer_data):
        """Calling approve-transition with approved=false should reject."""
        create_result = await handler.handle_from_debate(
            {"cartographer_data": sample_cartographer_data, "auto_advance": True}
        )
        pipeline_id = _body(create_result)["pipeline_id"]

        result = await handler.handle_approve_transition(
            pipeline_id,
            {
                "from_stage": "ideas",
                "to_stage": "goals",
                "approved": False,
                "comment": "Not ready",
            },
        )
        body = _body(result)
        assert body["status"] == "rejected"
        assert body["comment"] == "Not ready"

    @pytest.mark.asyncio
    async def test_approve_transition_accepts_transition_id_payload(self, handler):
        pipeline_id = self._save_pipeline_with_transition("pipe-approve-transition-id")

        result = await handler.handle_approve_transition(
            pipeline_id,
            {
                "transition_id": "trans-ideas-goals",
                "approved": True,
            },
        )
        body = _body(result)
        assert body["status"] == "approved"
        assert body["from_stage"] == "ideas"
        assert body["to_stage"] == "goals"
        assert body["result"]["transitions"][0]["status"] == "approved"

    @pytest.mark.asyncio
    async def test_reject_transition_accepts_transition_id_and_reason(self, handler):
        pipeline_id = self._save_pipeline_with_transition("pipe-reject-transition-id")

        result = await handler.handle_approve_transition(
            pipeline_id,
            {
                "transition_id": "trans-ideas-goals",
                "approved": False,
                "reason": "Needs clearer goals",
            },
        )
        body = _body(result)
        assert body["status"] == "rejected"
        assert body["comment"] == "Needs clearer goals"
        transition = body["result"]["transitions"][0]
        assert transition["status"] == "rejected"
        assert transition["human_comment"] == "Needs clearer goals"

    @pytest.mark.asyncio
    async def test_approve_transition_returns_updated_pipeline(
        self, handler, sample_cartographer_data
    ):
        """Approve-transition should include the updated pipeline data in result."""
        create_result = await handler.handle_from_debate(
            {"cartographer_data": sample_cartographer_data, "auto_advance": True}
        )
        pipeline_id = _body(create_result)["pipeline_id"]

        result = await handler.handle_approve_transition(
            pipeline_id,
            {"from_stage": "ideas", "to_stage": "goals"},
        )
        body = _body(result)
        assert "result" in body
        assert body["result"]["pipeline_id"] == pipeline_id

    @pytest.mark.asyncio
    async def test_approve_transition_missing_pipeline(self, handler):
        """Approving a non-existent pipeline returns 404."""
        result = await handler.handle_approve_transition(
            "nonexistent-pipe",
            {"from_stage": "ideas", "to_stage": "goals"},
        )
        body = _body(result)
        assert "error" in body
