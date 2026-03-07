"""Prompt Engine API Handler.

Endpoints:
- POST /api/prompt-engine/run        - Full pipeline (decompose → interrogate → research → specify)
- POST /api/prompt-engine/decompose  - Decompose a vague prompt into structured intent
- POST /api/prompt-engine/interrogate - Generate clarifying questions for an intent
- POST /api/prompt-engine/research   - Research context for an intent
- POST /api/prompt-engine/specify    - Build a specification from intent + questions + research
- POST /api/prompt-engine/validate   - Validate a specification via SpecValidator
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aragora.pipeline.backbone_contracts import SpecBundle

from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..secure import SecureHandler

logger = logging.getLogger(__name__)

_MAX_BODY = 1 * 1024 * 1024  # 1 MB


class PromptEngineHandler(SecureHandler):
    """Handler for the prompt-to-specification engine."""

    ROUTES = [
        ("POST", "/api/prompt-engine/run"),
        ("POST", "/api/prompt-engine/decompose"),
        ("POST", "/api/prompt-engine/interrogate"),
        ("POST", "/api/prompt-engine/research"),
        ("POST", "/api/prompt-engine/specify"),
        ("POST", "/api/prompt-engine/validate"),
    ]

    def can_handle(self, method: str, path: str) -> bool:
        return method == "POST" and path.startswith("/api/prompt-engine/")

    @handle_errors("prompt engine")
    def handle_POST(self, handler: Any) -> HandlerResult:
        path = getattr(handler, "path", "")

        if path.endswith("/run"):
            return self._handle_run(handler)
        if path.endswith("/decompose"):
            return self._handle_decompose(handler)
        if path.endswith("/interrogate"):
            return self._handle_interrogate(handler)
        if path.endswith("/research"):
            return self._handle_research(handler)
        if path.endswith("/specify"):
            return self._handle_specify(handler)
        if path.endswith("/validate"):
            return self._handle_validate(handler)

        return error_response("Unknown prompt-engine endpoint", 404)

    # ------------------------------------------------------------------
    # Body parsing helper
    # ------------------------------------------------------------------

    def _read_body(self, handler: Any) -> dict[str, Any] | None:
        """Read and parse JSON body from the request."""
        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > _MAX_BODY:
                return None
            body = handler.rfile.read(content_length).decode("utf-8")
            return json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
            logger.warning("Invalid request body: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Conductor / component factories (lazy imports)
    # ------------------------------------------------------------------

    def _make_conductor(self, data: dict[str, Any]) -> Any:
        from aragora.prompt_engine import ConductorConfig, PromptConductor
        from aragora.prompt_engine.types import AutonomyLevel

        profile = data.get("profile")
        if profile:
            config = ConductorConfig.from_profile(profile)
        else:
            config = ConductorConfig()

        autonomy = data.get("autonomy")
        if autonomy:
            try:
                config.autonomy = AutonomyLevel(autonomy)
            except ValueError:
                pass

        config.skip_research = data.get("skip_research", config.skip_research)
        config.skip_interrogation = data.get("skip_interrogation", config.skip_interrogation)

        return PromptConductor(config=config)

    # ------------------------------------------------------------------
    # Endpoint handlers
    # ------------------------------------------------------------------

    def _normalize_decision_plan_request(
        self,
        handler: Any,
        data: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, HandlerResult | None]:
        plan_data = data.get("decision_plan")
        if plan_data is None:
            return None, None
        if not isinstance(plan_data, dict):
            return None, error_response("decision_plan must be an object", 400)

        create_requested = bool(plan_data.get("create"))
        schedule_requested = bool(plan_data.get("schedule_execution"))
        if schedule_requested and not create_requested:
            return None, error_response(
                "decision_plan.schedule_execution requires decision_plan.create", 400
            )
        if not create_requested:
            return None, None

        from aragora.pipeline.decision_plan import ApprovalMode
        from aragora.pipeline.risk_register import RiskLevel

        approval_mode_raw = str(plan_data.get("approval_mode", ApprovalMode.RISK_BASED.value))
        try:
            approval_mode = ApprovalMode(approval_mode_raw)
        except ValueError:
            return None, error_response(
                f"Invalid decision_plan.approval_mode: {approval_mode_raw}",
                400,
            )

        max_auto_risk_raw = str(plan_data.get("max_auto_risk", RiskLevel.LOW.value))
        try:
            max_auto_risk = RiskLevel(max_auto_risk_raw)
        except ValueError:
            return None, error_response(
                f"Invalid decision_plan.max_auto_risk: {max_auto_risk_raw}",
                400,
            )

        budget_limit_usd = plan_data.get("budget_limit_usd")
        if budget_limit_usd is not None:
            try:
                budget_limit_usd = float(budget_limit_usd)
            except (TypeError, ValueError):
                return None, error_response("decision_plan.budget_limit_usd must be numeric", 400)

        metadata = plan_data.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            return None, error_response("decision_plan.metadata must be an object", 400)

        implementation_profile = plan_data.get("implementation_profile") or plan_data.get(
            "implementation"
        )
        if implementation_profile is not None and not isinstance(implementation_profile, dict):
            return None, error_response(
                "decision_plan.implementation_profile must be an object",
                400,
            )

        _, perm_err = self.require_permission_or_error(handler, "plans:write")
        if perm_err:
            return None, perm_err
        if schedule_requested:
            _, perm_err = self.require_permission_or_error(handler, "plans:approve")
            if perm_err:
                return None, perm_err

        return (
            {
                "create": True,
                "schedule_execution": schedule_requested,
                "approval_mode": approval_mode,
                "max_auto_risk": max_auto_risk,
                "budget_limit_usd": budget_limit_usd,
                "debate_id": str(plan_data.get("debate_id", "") or "").strip() or None,
                "task": str(plan_data.get("task", "") or "").strip() or None,
                "metadata": metadata,
                "implementation_profile": implementation_profile,
            },
            None,
        )

    def _handle_run(self, handler: Any) -> HandlerResult:
        """Run the full prompt-to-specification pipeline."""
        import asyncio

        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        prompt = data.get("prompt", "").strip()
        if not prompt:
            return error_response("prompt is required", 400)

        plan_request, plan_error = self._normalize_decision_plan_request(handler, data)
        if plan_error:
            return plan_error

        conductor = self._make_conductor(data)
        context = data.get("context")

        result = asyncio.run(conductor.run(prompt, context=context))

        # Run heuristic validation on the spec
        from aragora.prompt_engine import SpecValidator

        validator = SpecValidator()
        validation = validator.validate_heuristic(result.specification)
        spec_bundle = SpecBundle.from_prompt_spec(result.specification, validation=validation)

        payload = {
            "specification": result.specification.to_dict(),
            "spec_bundle": spec_bundle.to_dict(),
            "intent": result.intent.to_dict(),
            "questions": [q.to_dict() for q in result.questions],
            "research": result.research.to_dict() if result.research else None,
            "auto_approved": result.auto_approved,
            "stages_completed": result.stages_completed,
            "validation": validation.to_dict(),
        }

        if not plan_request:
            return json_response(payload)

        from aragora.pipeline.decision_plan import DecisionPlanFactory
        from aragora.pipeline.executor import store_plan
        from aragora.pipeline.execution_bridge import get_execution_bridge
        from aragora.pipeline.plan_store import get_plan_store

        try:
            plan = DecisionPlanFactory.from_specification(
                result.specification,
                debate_id=plan_request["debate_id"],
                task=plan_request["task"],
                budget_limit_usd=plan_request["budget_limit_usd"],
                approval_mode=plan_request["approval_mode"],
                max_auto_risk=plan_request["max_auto_risk"],
                metadata=plan_request["metadata"],
                implementation_profile=plan_request["implementation_profile"],
                validation_result=validation,
                fail_closed_spec_validation=True,
            )
        except ValueError as exc:
            payload["decision_plan_error"] = {
                "message": str(exc),
                "missing_required_fields": list(spec_bundle.missing_required_fields),
            }
            return json_response(payload, status=422)

        store = get_plan_store()
        store.create(plan)
        store_plan(plan)
        payload["decision_plan"] = plan.to_dict()

        if plan_request["schedule_execution"]:
            if plan.requires_human_approval and not plan.is_approved:
                payload["execution"] = {
                    "status": "pending_approval",
                    "plan_id": plan.id,
                    "requires_human_approval": True,
                }
            else:
                bridge = get_execution_bridge()
                execution_mode = (
                    plan.implementation_profile.execution_mode
                    if plan.implementation_profile
                    else None
                )
                bridge.schedule_execution(plan.id, execution_mode=execution_mode)
                record = next(iter(bridge.list_execution_records(plan_id=plan.id, limit=1)), None)
                execution_payload: dict[str, Any] = {
                    "status": "scheduled",
                    "plan_id": plan.id,
                    "execution_mode": execution_mode or "default",
                }
                if record:
                    execution_payload["record"] = record
                payload["execution"] = execution_payload

        return json_response(payload)

    def _handle_decompose(self, handler: Any) -> HandlerResult:
        """Decompose a vague prompt into structured intent."""
        import asyncio

        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        prompt = data.get("prompt", "").strip()
        if not prompt:
            return error_response("prompt is required", 400)

        from aragora.prompt_engine import PromptDecomposer

        decomposer = PromptDecomposer()
        context = data.get("context")
        intent = asyncio.run(decomposer.decompose(prompt, context))

        return json_response({"intent": intent.to_dict()})

    def _handle_interrogate(self, handler: Any) -> HandlerResult:
        """Generate clarifying questions for an intent."""
        import asyncio

        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        intent_data = data.get("intent")
        if not intent_data:
            return error_response("intent is required", 400)

        from aragora.prompt_engine import PromptInterrogator
        from aragora.prompt_engine.types import (
            IntentType,
            InterrogationDepth,
            PromptIntent,
        )

        intent = PromptIntent(
            raw_prompt=intent_data.get("raw_prompt", ""),
            intent_type=IntentType(intent_data.get("intent_type", "feature")),
            domains=intent_data.get("domains", []),
            ambiguities=intent_data.get("ambiguities", []),
            assumptions=intent_data.get("assumptions", []),
            scope_estimate=intent_data.get("scope_estimate", "medium"),
            summary=intent_data.get("summary", ""),
        )

        depth_str = data.get("depth", "thorough")
        try:
            depth = InterrogationDepth(depth_str)
        except ValueError:
            depth = InterrogationDepth.THOROUGH

        interrogator = PromptInterrogator()
        questions = asyncio.run(interrogator.interrogate(intent, depth=depth))

        return json_response(
            {
                "questions": [q.to_dict() for q in questions],
            }
        )

    def _handle_research(self, handler: Any) -> HandlerResult:
        """Research context for an intent."""
        import asyncio

        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        intent_data = data.get("intent")
        if not intent_data:
            return error_response("intent is required", 400)

        from aragora.prompt_engine import PromptResearcher
        from aragora.prompt_engine.types import IntentType, PromptIntent

        intent = PromptIntent(
            raw_prompt=intent_data.get("raw_prompt", ""),
            intent_type=IntentType(intent_data.get("intent_type", "feature")),
            domains=intent_data.get("domains", []),
            ambiguities=intent_data.get("ambiguities", []),
            assumptions=intent_data.get("assumptions", []),
            scope_estimate=intent_data.get("scope_estimate", "medium"),
            summary=intent_data.get("summary", ""),
        )

        researcher = PromptResearcher()
        context = data.get("context")
        research = asyncio.run(researcher.research(intent, context=context))

        return json_response({"research": research.to_dict()})

    def _handle_specify(self, handler: Any) -> HandlerResult:
        """Build a specification from intent + questions + research."""
        import asyncio

        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        intent_data = data.get("intent")
        if not intent_data:
            return error_response("intent is required", 400)

        from aragora.prompt_engine import SpecBuilder
        from aragora.prompt_engine.types import (
            ClarifyingQuestion,
            IntentType,
            PromptIntent,
            ResearchReport,
        )

        intent = PromptIntent(
            raw_prompt=intent_data.get("raw_prompt", ""),
            intent_type=IntentType(intent_data.get("intent_type", "feature")),
            domains=intent_data.get("domains", []),
            ambiguities=intent_data.get("ambiguities", []),
            assumptions=intent_data.get("assumptions", []),
            scope_estimate=intent_data.get("scope_estimate", "medium"),
            summary=intent_data.get("summary", ""),
        )

        questions_data = data.get("questions", [])
        questions = [
            ClarifyingQuestion(
                question=q.get("question", ""),
                why_it_matters=q.get("why_it_matters", ""),
                options=q.get("options", []),
                answer=q.get("answer"),
            )
            for q in questions_data
        ]

        research_data = data.get("research")
        research = None
        if research_data:
            research = ResearchReport(
                summary=research_data.get("summary", ""),
                current_state=research_data.get("current_state", ""),
                recommendations=research_data.get("recommendations", []),
            )

        builder = SpecBuilder()
        context = data.get("context")
        spec = asyncio.run(builder.build(intent, questions, research, context))
        spec_bundle = SpecBundle.from_prompt_spec(spec)

        return json_response(
            {"specification": spec.to_dict(), "spec_bundle": spec_bundle.to_dict()}
        )

    def _handle_validate(self, handler: Any) -> HandlerResult:
        """Validate a specification via SpecValidator."""
        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        spec_data = data.get("specification")
        if not spec_data:
            return error_response("specification is required", 400)

        from aragora.prompt_engine import SpecValidator
        from aragora.prompt_engine.types import RiskItem, SpecFile, Specification

        risks = []
        for r in spec_data.get("risks", []) + spec_data.get("risk_register", []):
            if isinstance(r, dict):
                risks.append(
                    RiskItem(
                        description=r.get("description", ""),
                        likelihood=r.get("likelihood", "medium"),
                        impact=r.get("impact", "medium"),
                        mitigation=r.get("mitigation", ""),
                    )
                )
        file_changes = []
        for item in spec_data.get("file_changes", []):
            if isinstance(item, dict):
                file_changes.append(
                    SpecFile(
                        path=item.get("path", ""),
                        action=item.get("action", "modify"),
                        description=item.get("description", ""),
                        estimated_lines=int(item.get("estimated_lines", 0) or 0),
                    )
                )

        spec = Specification(
            title=spec_data.get("title", ""),
            problem_statement=spec_data.get("problem_statement", ""),
            proposed_solution=spec_data.get("proposed_solution", ""),
            implementation_plan=spec_data.get("implementation_plan", []),
            success_criteria=spec_data.get("success_criteria", []),
            estimated_effort=spec_data.get("estimated_effort", ""),
            file_changes=file_changes,
            risks=risks,
            confidence=spec_data.get("confidence", 0.0),
        )
        spec.constraints = spec_data.get("constraints", [])

        validator = SpecValidator()
        result = validator.validate_heuristic(spec)
        spec_bundle = SpecBundle.from_prompt_spec(spec, validation=result)

        return json_response({"validation": result.to_dict(), "spec_bundle": spec_bundle.to_dict()})
