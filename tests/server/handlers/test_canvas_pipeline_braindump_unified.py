"""Tests for unified-orchestrator wiring in from-braindump handler."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.billing.auth.context import UserAuthContext
from aragora.pipeline.plan_store import PlanStore
from aragora.pipeline.unified_orchestrator import UnifiedOrchestrator
from aragora.server.handlers.canvas_pipeline import CanvasPipelineHandler, _pipeline_objects


def _body(result) -> dict:
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


@pytest.fixture(autouse=True)
def _clear_pipeline_objects() -> None:
    _pipeline_objects.clear()
    yield
    _pipeline_objects.clear()


@pytest.fixture
def handler() -> CanvasPipelineHandler:
    return CanvasPipelineHandler()


def _mock_pipeline_result() -> MagicMock:
    result = MagicMock()
    result.pipeline_id = "pipe-brain1234"
    result.stage_status = {"ideas": "complete", "goals": "pending"}
    result.goal_graph = None
    result.to_dict.return_value = {
        "pipeline_id": "pipe-brain1234",
        "stage_status": {"ideas": "complete", "goals": "pending"},
    }
    return result


class TestFromBraindumpUnifiedOrchestrator:
    @pytest.mark.asyncio
    async def test_enabled_orchestrator_adds_summary_and_debate_url(
        self, handler: CanvasPipelineHandler
    ):
        mock_result = _mock_pipeline_result()

        with (
            patch("aragora.pipeline.brain_dump_parser.BrainDumpParser") as MockParser,
            patch("aragora.pipeline.idea_to_execution.IdeaToExecutionPipeline") as MockPipeline,
            patch("aragora.server.handlers.canvas_pipeline._get_store") as mock_store,
            patch.object(
                CanvasPipelineHandler,
                "_run_unified_orchestrator",
                new=AsyncMock(
                    return_value=(
                        {
                            "enabled": True,
                            "run_id": "run-123",
                            "succeeded": True,
                            "stages_completed": ["research", "extend", "debate"],
                            "errors": [],
                            "debate_id": "debate-42",
                            "debate_url": "/debates/debate-42",
                        },
                        "extra context from orchestrator",
                    )
                ),
            ) as mock_orchestrator,
        ):
            MockParser.return_value.parse.return_value = ["idea 1", "idea 2"]
            MockPipeline.return_value.from_ideas.return_value = mock_result
            mock_store.return_value = MagicMock()

            result = await handler.handle_from_braindump(
                {
                    "text": "raw brain dump",
                    "use_unified_orchestrator": True,
                }
            )

            body = _body(result)
            assert body["pipeline_id"] == "pipe-brain1234"
            assert body["ideas_parsed"] == 2
            assert body["unified_orchestrator"]["run_id"] == "run-123"
            assert body["debate_id"] == "debate-42"
            assert body["debate_url"] == "/debates/debate-42"

            mock_orchestrator.assert_awaited_once()
            parse_input = MockParser.return_value.parse.call_args.args[0]
            assert "raw brain dump" in parse_input
            assert "extra context from orchestrator" in parse_input

    @pytest.mark.asyncio
    async def test_orchestrator_failure_degrades_to_pipeline_only(
        self, handler: CanvasPipelineHandler
    ):
        mock_result = _mock_pipeline_result()

        with (
            patch("aragora.pipeline.brain_dump_parser.BrainDumpParser") as MockParser,
            patch("aragora.pipeline.idea_to_execution.IdeaToExecutionPipeline") as MockPipeline,
            patch("aragora.server.handlers.canvas_pipeline._get_store") as mock_store,
            patch.object(
                CanvasPipelineHandler,
                "_run_unified_orchestrator",
                new=AsyncMock(side_effect=RuntimeError("orchestrator unavailable")),
            ),
        ):
            MockParser.return_value.parse.return_value = ["idea 1"]
            MockPipeline.return_value.from_ideas.return_value = mock_result
            mock_store.return_value = MagicMock()

            result = await handler.handle_from_braindump(
                {
                    "text": "raw brain dump",
                    "use_unified_orchestrator": True,
                }
            )

            body = _body(result)
            assert body["pipeline_id"] == "pipe-brain1234"
            assert body["ideas_parsed"] == 1
            assert body["unified_orchestrator"]["succeeded"] is False
            assert "orchestrator unavailable" in body["unified_orchestrator"]["errors"][0]

    @pytest.mark.parametrize("org_id", ["org-a", None])
    async def test_route_records_the_callers_org_on_the_backbone_run(
        self, handler: CanvasPipelineHandler, monkeypatch, tmp_path, org_id
    ):
        store = PlanStore(db_path=str(tmp_path / "runs.db"))
        monkeypatch.setattr("aragora.pipeline.plan_store.get_plan_store", lambda: store)
        user = UserAuthContext(authenticated=True, user_id="user-a1", org_id=org_id)
        monkeypatch.setattr("aragora.billing.jwt_auth.extract_user_from_request", lambda *a: user)
        # Without research/debate components: only the owner reaching the run is under test.
        bare = UnifiedOrchestrator.run
        monkeypatch.setattr(
            UnifiedOrchestrator, "run", lambda s, *a, **k: bare(UnifiedOrchestrator(), *a, **k)
        )
        body = {"text": "raw brain dump", "use_unified_orchestrator": True, "org_id": "org-b"}

        with (
            patch("aragora.pipeline.brain_dump_parser.BrainDumpParser") as MockParser,
            patch("aragora.pipeline.idea_to_execution.IdeaToExecutionPipeline") as MockPipeline,
            patch("aragora.server.handlers.canvas_pipeline._get_store"),
            patch("aragora.knowledge.mound.get_knowledge_mound", side_effect=RuntimeError),
        ):
            MockParser.return_value.parse.return_value = ["idea 1"]
            MockPipeline.return_value.from_ideas.return_value = _mock_pipeline_result()
            request = SimpleNamespace(headers={}, _body=json.dumps(body).encode())
            path = "/api/v1/canvas/pipeline/from-braindump"
            result = await handler.handle_post(path, {}, request)

        run_id = _body(result)["unified_orchestrator"]["run_id"]
        assert store.get_run(run_id) is not None
        assert [r.run_id for r in store.list_runs_for_org("org-a")] == ([run_id] if org_id else [])
        assert store.list_runs_for_org("org-b") == []
