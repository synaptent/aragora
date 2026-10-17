"""Tests for the prompt engine HTTP handler."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.pipeline.backbone_errors import FAIL_CLOSED_BACKBONE_MESSAGE
from aragora.pipeline.backbone_contracts import BackboneStage, RunLedger, RunStageEvent
from aragora.pipeline.decision_plan import ApprovalMode, PlanStatus
from aragora.pipeline.execution_mode import ExecutionMode
from aragora.pipeline.plan_store import PlanStore
from aragora.prompt_engine.spec_validator import ValidationResult
from aragora.prompt_engine.types import RiskItem, SpecFile, Specification
from aragora.server.handlers.prompt_engine.handler import PromptEngineHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler_request(body: dict[str, Any] | None = None) -> MagicMock:
    """Create a mock HTTP request handler with JSON body."""
    mock = MagicMock()
    raw = json.dumps(body or {}).encode()
    mock.headers = {"Content-Length": str(len(raw))}
    mock.rfile = BytesIO(raw)
    mock.path = "/api/prompt-engine/run"
    return mock


def _parse(result: tuple[int, dict[str, str], str]) -> dict[str, Any]:
    """Parse a HandlerResult/tuple into status + data."""
    if hasattr(result, "to_dict"):
        data = result.to_dict()
        return {"status": data["status"], "data": data["body"]}

    body, status, _headers = result
    if isinstance(body, (bytes, bytearray)):
        parsed_body = json.loads(body.decode("utf-8"))
    elif isinstance(body, str):
        parsed_body = json.loads(body)
    else:
        parsed_body = body
    return {"status": status, "data": parsed_body}


class _FakeTiming:
    def __init__(self) -> None:
        self.to_dict = MagicMock(
            return_value={
                "total_duration_ms": 250.0,
                "target_duration_ms": 15_000.0,
                "tracking_coverage_pct": 98.0,
                "stage_breakdown": [
                    {"stage": "research", "duration_ms": 120.0, "share_of_total_pct": 48.0}
                ],
                "optimization_targets": [
                    {
                        "operation": "research.agent_generate",
                        "duration_ms": 120.0,
                        "share_of_total_pct": 48.0,
                        "optimization_hint": "Reduce prompt size, model latency, or round trips.",
                    }
                ],
            }
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler() -> PromptEngineHandler:
    return PromptEngineHandler({})


@pytest.fixture(autouse=True)
def isolated_plan_store(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> PlanStore:
    store = PlanStore(db_path=str(tmp_path / "prompt_engine_handler.db"))
    monkeypatch.setattr("aragora.pipeline.plan_store.get_plan_store", lambda: store)
    return store


# ---------------------------------------------------------------------------
# Route matching
# ---------------------------------------------------------------------------


class TestCanHandle:
    def test_matches_prompt_engine_post(self, handler: PromptEngineHandler) -> None:
        assert handler.can_handle("POST", "/api/prompt-engine/run")

    def test_matches_decompose(self, handler: PromptEngineHandler) -> None:
        assert handler.can_handle("POST", "/api/prompt-engine/decompose")

    def test_matches_interrogate(self, handler: PromptEngineHandler) -> None:
        assert handler.can_handle("POST", "/api/prompt-engine/interrogate")

    def test_matches_research(self, handler: PromptEngineHandler) -> None:
        assert handler.can_handle("POST", "/api/prompt-engine/research")

    def test_matches_specify(self, handler: PromptEngineHandler) -> None:
        assert handler.can_handle("POST", "/api/prompt-engine/specify")

    def test_matches_validate(self, handler: PromptEngineHandler) -> None:
        assert handler.can_handle("POST", "/api/prompt-engine/validate")

    def test_matches_runs_get(self, handler: PromptEngineHandler) -> None:
        assert handler.can_handle("GET", "/api/prompt-engine/runs")

    def test_matches_single_run_get(self, handler: PromptEngineHandler) -> None:
        assert handler.can_handle("GET", "/api/prompt-engine/runs/run-123")

    def test_rejects_get_run_pipeline(self, handler: PromptEngineHandler) -> None:
        assert not handler.can_handle("GET", "/api/prompt-engine/run")

    def test_rejects_other_paths(self, handler: PromptEngineHandler) -> None:
        assert not handler.can_handle("POST", "/api/debates")


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------


class TestBodyParsing:
    def test_missing_prompt_returns_400(self, handler: PromptEngineHandler) -> None:
        req = _make_handler_request({"not_prompt": "hello"})
        req.path = "/api/prompt-engine/run"
        result = handler.handle_POST(req)
        parsed = _parse(result)
        assert parsed["status"] == 400

    def test_empty_prompt_returns_400(self, handler: PromptEngineHandler) -> None:
        req = _make_handler_request({"prompt": "  "})
        req.path = "/api/prompt-engine/run"
        result = handler.handle_POST(req)
        parsed = _parse(result)
        assert parsed["status"] == 400

    def test_oversized_body_returns_400(self, handler: PromptEngineHandler) -> None:
        req = MagicMock()
        req.headers = {"Content-Length": str(2 * 1024 * 1024)}
        req.rfile = BytesIO(b"x")
        req.path = "/api/prompt-engine/run"
        result = handler.handle_POST(req)
        parsed = _parse(result)
        assert parsed["status"] == 400

    def test_invalid_json_returns_400(self, handler: PromptEngineHandler) -> None:
        req = MagicMock()
        raw = b"not json"
        req.headers = {"Content-Length": str(len(raw))}
        req.rfile = BytesIO(raw)
        req.path = "/api/prompt-engine/run"
        result = handler.handle_POST(req)
        parsed = _parse(result)
        assert parsed["status"] == 400


# ---------------------------------------------------------------------------
# Decompose endpoint
# ---------------------------------------------------------------------------


class TestDecompose:
    @patch("aragora.prompt_engine.PromptDecomposer")
    def test_decompose_returns_intent(
        self, mock_cls: MagicMock, handler: PromptEngineHandler
    ) -> None:
        mock_intent = MagicMock()
        mock_intent.to_dict.return_value = {
            "raw_prompt": "test",
            "intent_type": "feature",
            "domains": [],
            "ambiguities": [],
            "assumptions": [],
            "scope_estimate": "medium",
            "summary": "A test intent",
            "decomposed_at": "2026-01-01T00:00:00",
        }
        instance = mock_cls.return_value
        instance.decompose = AsyncMock(return_value=mock_intent)
        instance.last_operation_timings = []

        req = _make_handler_request({"prompt": "Build a dashboard"})
        req.path = "/api/prompt-engine/decompose"
        result = handler.handle_POST(req)
        parsed = _parse(result)

        assert parsed["status"] == 200
        assert parsed["data"]["intent"]["intent_type"] == "feature"
        assert parsed["data"]["timing"]["stage_breakdown"][0]["stage"] == "decompose"
        instance.decompose.assert_called_once()


# ---------------------------------------------------------------------------
# Validate endpoint
# ---------------------------------------------------------------------------


class TestValidate:
    def test_validate_passes_with_complete_spec(self, handler: PromptEngineHandler) -> None:
        req = _make_handler_request(
            {
                "specification": {
                    "title": "Test Spec",
                    "problem_statement": "A problem",
                    "proposed_solution": "A solution",
                    "constraints": ["Keep the API stable"],
                    "success_criteria": ["It works"],
                    "implementation_plan": ["Step 1", "Step 2"],
                    "file_changes": [
                        {
                            "path": "aragora/server/handlers/example.py",
                            "action": "modify",
                            "description": "Update handler",
                        }
                    ],
                    "risks": [
                        {
                            "description": "Regression",
                            "likelihood": "medium",
                            "impact": "medium",
                            "mitigation": "Rollback quickly",
                        }
                    ],
                    "risk_register": [],
                    "confidence": 0.9,
                }
            }
        )
        req.path = "/api/prompt-engine/validate"
        result = handler.handle_POST(req)
        parsed = _parse(result)

        assert parsed["status"] == 200
        assert parsed["data"]["validation"]["passed"] is True
        assert parsed["data"]["spec_bundle"]["missing_required_fields"] == []

    def test_validate_fails_without_problem(self, handler: PromptEngineHandler) -> None:
        req = _make_handler_request(
            {
                "specification": {
                    "title": "Incomplete Spec",
                    "problem_statement": "",
                    "proposed_solution": "",
                    "success_criteria": [],
                    "implementation_plan": [],
                    "risks": [],
                    "risk_register": [],
                    "confidence": 0.1,
                }
            }
        )
        req.path = "/api/prompt-engine/validate"
        result = handler.handle_POST(req)
        parsed = _parse(result)

        assert parsed["status"] == 200
        assert parsed["data"]["validation"]["passed"] is False
        assert "constraints" in parsed["data"]["spec_bundle"]["missing_required_fields"]

    def test_validate_missing_spec_returns_400(self, handler: PromptEngineHandler) -> None:
        req = _make_handler_request({})
        req.path = "/api/prompt-engine/validate"
        result = handler.handle_POST(req)
        parsed = _parse(result)
        assert parsed["status"] == 400


# ---------------------------------------------------------------------------
# Run endpoint (mocked)
# ---------------------------------------------------------------------------


class TestRunPipeline:
    @patch("aragora.prompt_engine.SpecValidator")
    @patch("aragora.prompt_engine.PromptConductor")
    @patch("aragora.prompt_engine.ConductorConfig")
    def test_run_returns_full_result(
        self,
        mock_config_cls: MagicMock,
        mock_conductor_cls: MagicMock,
        mock_validator_cls: MagicMock,
        handler: PromptEngineHandler,
    ) -> None:
        # Mock conductor result
        mock_spec = Specification(
            title="Test",
            problem_statement="Problem",
            proposed_solution="Solution",
            constraints=["Keep API stable"],
            success_criteria=["It works"],
            file_changes=[
                SpecFile(path="aragora/server/example.py", action="modify", description="Patch")
            ],
            risks=[
                RiskItem(
                    description="Regression risk",
                    likelihood="medium",
                    impact="medium",
                    mitigation="Rollback quickly",
                )
            ],
            confidence=0.9,
        )
        mock_intent = MagicMock()
        mock_intent.to_dict.return_value = {"raw_prompt": "test", "intent_type": "feature"}

        mock_result = MagicMock()
        mock_result.specification = mock_spec
        mock_result.intent = mock_intent
        mock_result.questions = []
        mock_result.research = None
        mock_result.auto_approved = False
        mock_result.stages_completed = ["decompose", "specify"]
        mock_timing = MagicMock()
        mock_timing.to_dict.return_value = {
            "total_duration_ms": 61.2,
            "slowest_stage": {"stage": "specify", "duration_ms": 31.0},
            "top_operations": [{"operation": "specify.agent_generate", "duration_ms": 29.5}],
        }
        mock_result.timing = mock_timing

        instance = mock_conductor_cls.return_value
        instance.run = AsyncMock(return_value=mock_result)

        # Mock validator
        mock_validation = ValidationResult(
            role_results={},
            passed=True,
            overall_confidence=0.85,
        )
        mock_validator = mock_validator_cls.return_value
        mock_validator.validate_heuristic.return_value = mock_validation
        mock_validator.last_operation_timings = []

        # Mock config
        mock_config_cls.return_value = MagicMock()
        mock_config_cls.from_profile.return_value = MagicMock()

        req = _make_handler_request({"prompt": "Build something", "profile": "founder"})
        req.path = "/api/prompt-engine/run"
        result = handler.handle_POST(req)
        parsed = _parse(result)

        assert parsed["status"] == 200
        assert parsed["data"]["specification"]["title"] == "Test"
        assert "spec_bundle" in parsed["data"]
        assert parsed["data"]["validation"]["passed"] is True
        assert "stages_completed" in parsed["data"]
        assert parsed["data"]["run"]["status"] == "spec_ready"
        assert parsed["data"]["timing"]["slowest_stage"]["stage"] == "specify"

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.plan_store.get_plan_store")
    @patch("aragora.pipeline.execution_bridge.get_execution_bridge")
    @patch("aragora.prompt_engine.SpecValidator")
    @patch("aragora.prompt_engine.PromptConductor")
    @patch("aragora.prompt_engine.ConductorConfig")
    def test_run_can_create_and_schedule_decision_plan(
        self,
        mock_config_cls: MagicMock,
        mock_conductor_cls: MagicMock,
        mock_validator_cls: MagicMock,
        mock_get_execution_bridge: MagicMock,
        mock_get_plan_store: MagicMock,
        mock_store_plan: MagicMock,
        handler: PromptEngineHandler,
    ) -> None:
        spec = Specification(
            title="Runnable spec",
            problem_statement="Problem",
            proposed_solution="Ship the change",
            success_criteria=["Criterion"],
            file_changes=[
                SpecFile(path="aragora/server/example.py", action="modify", description="Patch")
            ],
            risks=[
                RiskItem(
                    description="Regression risk",
                    likelihood="medium",
                    impact="medium",
                    mitigation="Rollback quickly",
                )
            ],
            confidence=0.95,
        )
        spec.constraints = ["Preserve API contract"]
        mock_intent = MagicMock()
        mock_intent.to_dict.return_value = {"raw_prompt": "test", "intent_type": "feature"}
        mock_result = MagicMock(
            specification=spec,
            intent=mock_intent,
            questions=[],
            research=None,
            auto_approved=False,
            stages_completed=["decompose", "specify"],
            timing=_FakeTiming(),
        )
        mock_result.timing.to_dict.return_value = {
            "total_duration_ms": 92.0,
            "slowest_stage": {"stage": "specify", "duration_ms": 44.0},
            "top_operations": [{"operation": "specify.agent_generate", "duration_ms": 41.0}],
        }
        mock_conductor_cls.return_value.run = AsyncMock(return_value=mock_result)

        validation = ValidationResult(
            role_results={},
            passed=True,
            overall_confidence=0.95,
        )
        mock_validator = mock_validator_cls.return_value
        mock_validator.validate_heuristic.return_value = validation
        mock_validator.last_operation_timings = []
        mock_config_cls.return_value = MagicMock()
        mock_config_cls.from_profile.return_value = MagicMock()
        mock_get_execution_bridge.return_value.list_execution_records.return_value = [
            {"execution_id": "exec-123", "status": "queued"}
        ]
        handler.require_permission_or_error = MagicMock(return_value=(MagicMock(), None))

        req = _make_handler_request(
            {
                "prompt": "Build something",
                "decision_plan": {
                    "create": True,
                    "schedule_execution": True,
                    "approval_mode": ApprovalMode.NEVER.value,
                    "implementation_profile": {"execution_mode": "workflow"},
                },
            }
        )
        req.path = "/api/prompt-engine/run"

        with patch(
            "aragora.server.handlers.prompt_engine.handler.BackboneRuntime.sync_plan_receipt_to_run",
            return_value=True,
        ):
            result = handler.handle_POST(req)
        parsed = _parse(result)

        assert parsed["status"] == 200
        assert parsed["data"]["decision_plan"]["status"] == PlanStatus.APPROVED.value
        assert parsed["data"]["execution"]["status"] == "scheduled"
        assert parsed["data"]["run"]["execution_id"] == "exec-123"
        assert parsed["data"]["timing"]["slowest_stage"]["stage"] == "specify"
        mock_get_plan_store.return_value.create.assert_called_once()
        mock_store_plan.assert_called_once()
        mock_get_execution_bridge.return_value.schedule_execution.assert_called_once()
        schedule_kwargs = mock_get_execution_bridge.return_value.schedule_execution.call_args.kwargs
        assert schedule_kwargs["execution_mode"] == "workflow"
        assert schedule_kwargs["safety_mode"] == ExecutionMode.INTERACTIVE

    @patch("aragora.pipeline.execution_bridge.get_execution_bridge")
    @patch("aragora.prompt_engine.SpecValidator")
    @patch("aragora.prompt_engine.PromptConductor")
    @patch("aragora.prompt_engine.ConductorConfig")
    def test_run_returns_503_when_backbone_write_fails(
        self,
        mock_config_cls: MagicMock,
        mock_conductor_cls: MagicMock,
        mock_validator_cls: MagicMock,
        mock_get_execution_bridge: MagicMock,
        handler: PromptEngineHandler,
    ) -> None:
        spec = Specification(
            title="Execution-grade spec",
            problem_statement="Problem",
            proposed_solution="Ship the change",
            constraints=["Constraint"],
            success_criteria=["Criterion"],
            file_changes=[
                SpecFile(path="aragora/server/example.py", action="modify", description="Patch")
            ],
            risks=[
                RiskItem(
                    description="Regression risk",
                    likelihood="medium",
                    impact="medium",
                    mitigation="Rollback quickly",
                )
            ],
            confidence=0.95,
        )
        mock_intent = MagicMock()
        mock_intent.to_dict.return_value = {"raw_prompt": "test", "intent_type": "feature"}
        mock_result = MagicMock(
            specification=spec,
            intent=mock_intent,
            questions=[],
            research=None,
            auto_approved=False,
            stages_completed=["decompose", "specify"],
            timing=_FakeTiming(),
        )
        mock_conductor_cls.return_value.run = AsyncMock(return_value=mock_result)

        validation = ValidationResult(role_results={}, passed=True, overall_confidence=0.95)
        mock_validator = mock_validator_cls.return_value
        mock_validator.validate_heuristic.return_value = validation
        mock_validator.last_operation_timings = []
        mock_config_cls.return_value = MagicMock()
        mock_config_cls.from_profile.return_value = MagicMock()
        handler.require_permission_or_error = MagicMock(return_value=(MagicMock(), None))

        req = _make_handler_request(
            {
                "prompt": "Build something",
                "decision_plan": {
                    "create": True,
                    "schedule_execution": True,
                    "approval_mode": ApprovalMode.NEVER.value,
                },
            }
        )
        req.path = "/api/prompt-engine/run"

        with patch(
            "aragora.server.handlers.prompt_engine.handler.BackboneRuntime.update_run",
            return_value=False,
        ):
            result = handler.handle_POST(req)

        parsed = _parse(result)
        assert parsed["status"] == 503
        assert parsed["data"]["error"] == FAIL_CLOSED_BACKBONE_MESSAGE
        mock_get_execution_bridge.return_value.schedule_execution.assert_not_called()

    @patch("aragora.pipeline.plan_store.get_plan_store")
    @patch("aragora.prompt_engine.SpecValidator")
    @patch("aragora.prompt_engine.PromptConductor")
    @patch("aragora.prompt_engine.ConductorConfig")
    def test_run_returns_422_when_decision_plan_spec_is_not_execution_grade(
        self,
        mock_config_cls: MagicMock,
        mock_conductor_cls: MagicMock,
        mock_validator_cls: MagicMock,
        mock_get_plan_store: MagicMock,
        handler: PromptEngineHandler,
    ) -> None:
        spec = Specification(
            title="Incomplete spec",
            problem_statement="Problem",
            proposed_solution="Ship the change",
            success_criteria=["Criterion"],
        )
        mock_intent = MagicMock()
        mock_intent.to_dict.return_value = {"raw_prompt": "test", "intent_type": "feature"}
        mock_result = MagicMock(
            specification=spec,
            intent=mock_intent,
            questions=[],
            research=None,
            auto_approved=False,
            stages_completed=["decompose", "specify"],
            timing=_FakeTiming(),
        )
        mock_result.timing.to_dict.return_value = {
            "total_duration_ms": 40.0,
            "slowest_stage": {"stage": "specify", "duration_ms": 19.0},
            "top_operations": [{"operation": "specify.agent_generate", "duration_ms": 18.0}],
        }
        mock_conductor_cls.return_value.run = AsyncMock(return_value=mock_result)

        validation = ValidationResult(
            role_results={},
            passed=False,
            overall_confidence=0.2,
        )
        mock_validator = mock_validator_cls.return_value
        mock_validator.validate_heuristic.return_value = validation
        mock_validator.last_operation_timings = []
        mock_config_cls.return_value = MagicMock()
        mock_config_cls.from_profile.return_value = MagicMock()
        handler.require_permission_or_error = MagicMock(return_value=(MagicMock(), None))

        req = _make_handler_request(
            {
                "prompt": "Build something",
                "decision_plan": {"create": True},
            }
        )
        req.path = "/api/prompt-engine/run"

        result = handler.handle_POST(req)
        parsed = _parse(result)

        assert parsed["status"] == 422
        assert "decision_plan_error" in parsed["data"]
        assert (
            "owner_file_scopes" in parsed["data"]["decision_plan_error"]["missing_required_fields"]
        )
        mock_get_plan_store.return_value.create.assert_not_called()

    @patch("aragora.pipeline.execution_bridge.get_execution_bridge")
    @patch("aragora.prompt_engine.SpecValidator")
    @patch("aragora.prompt_engine.PromptConductor")
    @patch("aragora.prompt_engine.ConductorConfig")
    def test_run_forces_manual_lane_when_context_is_tainted(
        self,
        mock_config_cls: MagicMock,
        mock_conductor_cls: MagicMock,
        mock_validator_cls: MagicMock,
        mock_get_execution_bridge: MagicMock,
        handler: PromptEngineHandler,
        isolated_plan_store: PlanStore,
    ) -> None:
        spec = Specification(
            title="Tainted spec",
            problem_statement="Problem",
            proposed_solution="Ship carefully",
            constraints=["Keep controls"],
            success_criteria=["Criterion"],
            file_changes=[
                SpecFile(path="aragora/server/example.py", action="modify", description="Patch")
            ],
            risks=[
                RiskItem(
                    description="Regression risk",
                    likelihood="medium",
                    impact="medium",
                    mitigation="Rollback quickly",
                )
            ],
            confidence=0.95,
        )
        mock_intent = MagicMock()
        mock_intent.to_dict.return_value = {"raw_prompt": "test", "intent_type": "feature"}
        mock_result = MagicMock(
            specification=spec,
            intent=mock_intent,
            questions=[],
            research=None,
            auto_approved=False,
            stages_completed=["decompose", "specify"],
            timing=_FakeTiming(),
        )
        mock_conductor_cls.return_value.run = AsyncMock(return_value=mock_result)
        validation = ValidationResult(role_results={}, passed=True, overall_confidence=0.95)
        mock_validator = mock_validator_cls.return_value
        mock_validator.validate_heuristic.return_value = validation
        mock_validator.last_operation_timings = []
        mock_config_cls.return_value = MagicMock()
        mock_config_cls.from_profile.return_value = MagicMock()
        user = MagicMock(org_id="org-a", user_id="user-1")
        handler.require_permission_or_error = MagicMock(return_value=(user, None))

        req = _make_handler_request(
            {
                "prompt": "Build something",
                "context": {"repo": "user supplied"},
                "decision_plan": {
                    "create": True,
                    "schedule_execution": True,
                    "approval_mode": ApprovalMode.NEVER.value,
                },
            }
        )
        req.path = "/api/prompt-engine/run"

        result = handler.handle_POST(req)
        parsed = _parse(result)

        assert parsed["status"] == 200
        assert parsed["data"]["decision_plan"]["status"] == PlanStatus.AWAITING_APPROVAL.value
        assert parsed["data"]["execution"]["status"] == "pending_approval"
        assert parsed["data"]["execution"]["requires_human_approval"] is True
        assert (
            "backbone_taint_detected"
            in parsed["data"]["execution"]["execution_gate"]["reason_codes"]
        )
        mock_get_execution_bridge.return_value.schedule_execution.assert_not_called()
        owned = isolated_plan_store.list_for_org("org-a")
        assert [(p.id, p.org_id, p.created_by) for p in owned] == [
            (parsed["data"]["decision_plan"]["id"], "org-a", "user-1")
        ]

    def test_unknown_endpoint_returns_404(self, handler: PromptEngineHandler) -> None:
        req = _make_handler_request({"prompt": "test"})
        req.path = "/api/prompt-engine/unknown"
        result = handler.handle_POST(req)
        parsed = _parse(result)
        assert parsed["status"] == 404


class TestBackboneRunEndpoints:
    def test_list_runs_returns_persisted_ledgers(
        self,
        handler: PromptEngineHandler,
        isolated_plan_store: PlanStore,
    ) -> None:
        run = RunLedger(run_id="run-1", entrypoint="prompt_engine.run", status="spec_ready")
        run.add_event(RunStageEvent.create(BackboneStage.INTAKE, status="received"))
        isolated_plan_store.create_run(run)

        req = MagicMock()
        req.path = "/api/prompt-engine/runs"
        result = handler.handle_GET(req, {"status": "spec_ready"})
        parsed = _parse(result)

        assert parsed["status"] == 200
        assert len(parsed["data"]["runs"]) == 1
        assert parsed["data"]["runs"][0]["run_id"] == "run-1"

    def test_get_run_returns_single_ledger(
        self,
        handler: PromptEngineHandler,
        isolated_plan_store: PlanStore,
    ) -> None:
        run = RunLedger(run_id="run-2", entrypoint="prompt_engine.run", status="plan_ready")
        run.add_event(RunStageEvent.create(BackboneStage.PLAN, status="completed"))
        isolated_plan_store.create_run(run)

        req = MagicMock()
        req.path = "/api/prompt-engine/runs/run-2"
        result = handler.handle_GET(req)
        parsed = _parse(result)

        assert parsed["status"] == 200
        assert parsed["data"]["run"]["run_id"] == "run-2"
        assert parsed["data"]["run"]["stage_events"][0]["stage"] == BackboneStage.PLAN.value
