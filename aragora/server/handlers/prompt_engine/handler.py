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

    def _handle_run(self, handler: Any) -> HandlerResult:
        """Run the full prompt-to-specification pipeline."""
        import asyncio

        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        prompt = data.get("prompt", "").strip()
        if not prompt:
            return error_response("prompt is required", 400)

        conductor = self._make_conductor(data)
        context = data.get("context")

        result = asyncio.run(conductor.run(prompt, context=context))

        # Run heuristic validation on the spec
        from aragora.prompt_engine import SpecValidator

        validator = SpecValidator()
        validation = validator.validate_heuristic(result.specification)

        return json_response(
            {
                "specification": result.specification.to_dict(),
                "intent": result.intent.to_dict(),
                "questions": [q.to_dict() for q in result.questions],
                "research": result.research.to_dict() if result.research else None,
                "auto_approved": result.auto_approved,
                "stages_completed": result.stages_completed,
                "validation": validation.to_dict(),
            }
        )

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

        return json_response({"specification": spec.to_dict()})

    def _handle_validate(self, handler: Any) -> HandlerResult:
        """Validate a specification via SpecValidator."""
        data = self._read_body(handler)
        if data is None:
            return error_response("Invalid request body", 400)

        spec_data = data.get("specification")
        if not spec_data:
            return error_response("specification is required", 400)

        from aragora.prompt_engine import SpecValidator
        from aragora.prompt_engine.types import RiskItem, Specification

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

        spec = Specification(
            title=spec_data.get("title", ""),
            problem_statement=spec_data.get("problem_statement", ""),
            proposed_solution=spec_data.get("proposed_solution", ""),
            implementation_plan=spec_data.get("implementation_plan", []),
            success_criteria=spec_data.get("success_criteria", []),
            estimated_effort=spec_data.get("estimated_effort", ""),
            risks=risks,
            confidence=spec_data.get("confidence", 0.0),
        )

        validator = SpecValidator()
        result = validator.validate_heuristic(spec)

        return json_response({"validation": result.to_dict()})
