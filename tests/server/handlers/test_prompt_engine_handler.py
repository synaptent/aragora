"""Tests for the prompt engine HTTP handler."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.pipeline.decision_plan import ApprovalMode, PlanStatus
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler() -> PromptEngineHandler:
    return PromptEngineHandler({})


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

    def test_rejects_get(self, handler: PromptEngineHandler) -> None:
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

        req = _make_handler_request({"prompt": "Build a dashboard"})
        req.path = "/api/prompt-engine/decompose"
        result = handler.handle_POST(req)
        parsed = _parse(result)

        assert parsed["status"] == 200
        assert parsed["data"]["intent"]["intent_type"] == "feature"
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
        mock_spec = MagicMock()
        mock_spec.to_dict.return_value = {"title": "Test", "confidence": 0.9}
        mock_intent = MagicMock()
        mock_intent.to_dict.return_value = {"raw_prompt": "test", "intent_type": "feature"}

        mock_result = MagicMock()
        mock_result.specification = mock_spec
        mock_result.intent = mock_intent
        mock_result.questions = []
        mock_result.research = None
        mock_result.auto_approved = False
        mock_result.stages_completed = ["decompose", "specify"]

        instance = mock_conductor_cls.return_value
        instance.run = AsyncMock(return_value=mock_result)

        # Mock validator
        mock_validation = MagicMock()
        mock_validation.to_dict.return_value = {"passed": True, "overall_confidence": 0.85}
        mock_validator_cls.return_value.validate_heuristic.return_value = mock_validation

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
        )
        mock_conductor_cls.return_value.run = AsyncMock(return_value=mock_result)

        validation = ValidationResult(
            role_results={},
            passed=True,
            overall_confidence=0.95,
        )
        mock_validator_cls.return_value.validate_heuristic.return_value = validation
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

        result = handler.handle_POST(req)
        parsed = _parse(result)

        assert parsed["status"] == 200
        assert parsed["data"]["decision_plan"]["status"] == PlanStatus.APPROVED.value
        assert parsed["data"]["execution"]["status"] == "scheduled"
        mock_get_plan_store.return_value.create.assert_called_once()
        mock_store_plan.assert_called_once()
        mock_get_execution_bridge.return_value.schedule_execution.assert_called_once()

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
        )
        mock_conductor_cls.return_value.run = AsyncMock(return_value=mock_result)

        validation = ValidationResult(
            role_results={},
            passed=False,
            overall_confidence=0.2,
        )
        mock_validator_cls.return_value.validate_heuristic.return_value = validation
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

    def test_unknown_endpoint_returns_404(self, handler: PromptEngineHandler) -> None:
        req = _make_handler_request({"prompt": "test"})
        req.path = "/api/prompt-engine/unknown"
        result = handler.handle_POST(req)
        parsed = _parse(result)
        assert parsed["status"] == 404
