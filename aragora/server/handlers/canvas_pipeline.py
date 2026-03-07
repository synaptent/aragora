"""
Canvas Pipeline REST Handler.

Exposes the idea-to-execution pipeline via REST endpoints:

- POST /api/v1/canvas/pipeline/from-debate              → Full pipeline from debate
- POST /api/v1/canvas/pipeline/from-ideas               → Full pipeline from raw ideas
- POST /api/v1/canvas/pipeline/from-braindump           → Full pipeline from brain dump text
- POST /api/v1/canvas/pipeline/advance                  → Advance to next stage
- POST /api/v1/canvas/pipeline/run                      → Start async pipeline
- POST /api/v1/canvas/pipeline/{id}/approve-transition  → Approve/reject stage transition
- PUT  /api/v1/canvas/pipeline/{id}                     → Save canvas state
- GET  /api/v1/canvas/pipeline/{id}                     → Get pipeline result
- GET  /api/v1/canvas/pipeline/{id}/status              → Per-stage status
- GET  /api/v1/canvas/pipeline/{id}/stage/{s}           → Get specific stage canvas
- GET  /api/v1/canvas/pipeline/{id}/graph               → React Flow JSON for any stage
- GET  /api/v1/canvas/pipeline/{id}/receipt              → DecisionReceipt
- POST /api/v1/canvas/pipeline/extract-goals            → Extract goals from ideas canvas
- POST /api/v1/canvas/convert/debate                    → Convert debate to ideas canvas
- POST /api/v1/canvas/convert/workflow                  → Convert workflow to actions canvas
- GET  /api/v1/canvas/pipeline/templates                → List pipeline templates
- POST /api/v1/canvas/pipeline/{id}/execute              → Execute completed pipeline
- POST /api/v1/canvas/pipeline/from-template            → Create pipeline from template
- POST /api/v1/debates/{id}/to-pipeline                 → Convert debate to pipeline
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from aragora.server.handlers.base import HandlerResult, error_response, handle_errors, json_response

logger = logging.getLogger(__name__)

# Path patterns for route dispatch
_PIPELINE_ID = re.compile(r"^/api/v1/canvas/pipeline/([a-zA-Z0-9_-]+)$")
_PIPELINE_STATUS = re.compile(r"^/api/v1/canvas/pipeline/([a-zA-Z0-9_-]+)/status$")
_PIPELINE_STAGE = re.compile(r"^/api/v1/canvas/pipeline/([a-zA-Z0-9_-]+)/stage/(\w+)$")
_PIPELINE_GRAPH = re.compile(r"^/api/v1/canvas/pipeline/([a-zA-Z0-9_-]+)/graph$")
_PIPELINE_RECEIPT = re.compile(r"^/api/v1/canvas/pipeline/([a-zA-Z0-9_-]+)/receipt$")
_PIPELINE_EXECUTE = re.compile(r"^/api/v1/canvas/pipeline/([a-zA-Z0-9_-]+)/execute$")
_PIPELINE_SELF_IMPROVE = re.compile(r"^/api/v1/canvas/pipeline/([a-zA-Z0-9_-]+)/self-improve$")
_DEBATE_TO_PIPELINE = re.compile(r"^/api/v1/debates/([a-zA-Z0-9_-]+)/to-pipeline$")

# Live PipelineResult objects for advance_stage() (cannot be persisted)
_pipeline_objects: dict[str, Any] = {}
# Async pipeline tasks / worker threads (cannot be persisted)
_pipeline_tasks: dict[str, Any] = {}


def _spectate_pipeline(event_type: str, pipeline_id: str, data: dict[str, Any]) -> None:
    """Emit a spectate event for pipeline operations."""
    try:
        from aragora.spectate.stream import SpectatorStream

        stream = SpectatorStream(enabled=True)
        stream.emit(
            event_type=event_type,
            details=json.dumps(
                {
                    "pipeline_id": pipeline_id,
                    **data,
                }
            ),
        )
    except (ImportError, TypeError):
        pass


def _get_store() -> Any:
    """Lazy-load the persistent pipeline store."""
    from aragora.storage.pipeline_store import get_pipeline_store

    return get_pipeline_store()


def _get_ai_agent() -> Any | None:
    """Try to create an AI agent for goal synthesis.

    Returns an agent with a generate() method, or None if unavailable.
    """
    try:
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        return AnthropicAPIAgent(model="claude-sonnet-4-5-20250929")
    except (ImportError, OSError, ValueError):
        pass
    try:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        return OpenAIAPIAgent(model="gpt-4o-mini")
    except (ImportError, OSError, ValueError):
        pass
    return None


def _persist_universal_graph(result: Any) -> None:
    """Persist the UniversalGraph from a PipelineResult to GraphStore."""
    if result.universal_graph is None:
        return
    try:
        from aragora.pipeline.graph_store import get_graph_store

        store = get_graph_store()
        store.create(result.universal_graph)
        logger.info(
            "Persisted universal graph %s with %d nodes",
            result.universal_graph.id,
            len(result.universal_graph.nodes),
        )
    except (ImportError, OSError) as e:
        logger.debug("Could not persist universal graph: %s", e)


def _persist_pipeline_to_km(result: Any) -> None:
    """Persist pipeline result to KnowledgeMound for future precedent queries."""
    try:
        from aragora.pipeline.km_bridge import PipelineKMBridge

        bridge = PipelineKMBridge()
        bridge.store_pipeline_result(result)
    except (ImportError, AttributeError, RuntimeError, ValueError) as e:
        logger.debug("KM persistence skipped: %s", e)


class CanvasPipelineHandler:
    """HTTP handler for the idea-to-execution canvas pipeline."""

    ROUTES = [
        "POST /api/v1/canvas/pipeline/from-debate",
        "POST /api/v1/canvas/pipeline/from-ideas",
        "POST /api/v1/canvas/pipeline/from-braindump",
        "POST /api/v1/canvas/pipeline/from-template",
        "POST /api/v1/canvas/pipeline/demo",
        "POST /api/v1/canvas/pipeline/advance",
        "POST /api/v1/canvas/pipeline/run",
        "POST /api/v1/canvas/pipeline/{id}/approve-transition",
        "POST /api/v1/canvas/pipeline/{id}/execute",
        "POST /api/v1/canvas/pipeline/{id}/self-improve",
        "GET /api/v1/canvas/pipeline/{id}",
        "GET /api/v1/canvas/pipeline/{id}/status",
        "GET /api/v1/canvas/pipeline/{id}/stage/{stage}",
        "GET /api/v1/canvas/pipeline/{id}/graph",
        "GET /api/v1/canvas/pipeline/{id}/receipt",
        "GET /api/v1/canvas/pipeline/templates",
        "PUT /api/v1/canvas/pipeline/{id}",
        "POST /api/v1/canvas/pipeline/extract-goals",
        "POST /api/v1/canvas/pipeline/extract-principles",
        "POST /api/v1/canvas/pipeline/auto-run",
        "POST /api/v1/canvas/pipeline/from-system-metrics",
        "POST /api/v1/canvas/convert/debate",
        "POST /api/v1/canvas/convert/workflow",
        "POST /api/v1/debates/{id}/to-pipeline",
        "GET /api/v1/canvas/pipeline/{id}/intelligence",
        "GET /api/v1/canvas/pipeline/{id}/beliefs",
        "GET /api/v1/canvas/pipeline/{id}/explanations",
        "GET /api/v1/canvas/pipeline/{id}/precedents",
        "GET /api/v1/pipeline/{id}/agents",
        "POST /api/v1/pipeline/{id}/agents/{agent_id}/approve",
        "POST /api/v1/pipeline/{id}/agents/{agent_id}/reject",
    ]

    def __init__(self, ctx: dict[str, Any] | None = None) -> None:
        self.ctx = ctx or {}

    @staticmethod
    def _coerce_bool(value: Any, default: bool = False) -> bool:
        """Parse booleans from JSON, query params, or env-like strings."""
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return bool(value)

    @staticmethod
    def _extract_debate_id(debate_result: Any) -> str | None:
        """Extract debate_id from a debate result object/dict when available."""
        if debate_result is None:
            return None

        for key in ("debate_id", "id"):
            if isinstance(debate_result, dict):
                value = debate_result.get(key)
            else:
                value = getattr(debate_result, key, None)

            if value:
                return str(value)
        return None

    async def _run_unified_orchestrator(
        self,
        prompt: str,
        request_data: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        """Run UnifiedOrchestrator and return summary + context hint."""
        from aragora.debate.provider_diversity import ProviderDiversityFilter
        from aragora.interrogation.researcher import UnifiedResearcher
        from aragora.pipeline.decision_plan.factory import DecisionPlanFactory
        from aragora.pipeline.input_extension import InputExtensionEngine
        from aragora.pipeline.meta_loop import MetaLoopTrigger
        from aragora.pipeline.outcome_feedback import OutcomeFeedbackRecorder
        from aragora.pipeline.unified_orchestrator import (
            OrchestratorConfig,
            UnifiedOrchestrator,
        )
        from aragora.ranking.phase_elo import PhaseELOTracker

        km = None
        try:
            from aragora.knowledge.mound import get_knowledge_mound

            km = get_knowledge_mound()
        except (ImportError, RuntimeError, OSError, ValueError):
            km = None

        domain = str(
            request_data.get("domain")
            or request_data.get("context")
            or request_data.get("topic")
            or ""
        ).strip()
        preset_name = str(request_data.get("preset_name") or "cto")
        autonomy_level = str(request_data.get("autonomy_level") or "propose_and_approve")
        min_providers = int(request_data.get("min_providers") or 2)
        execution_mode = str(request_data.get("execution_mode") or "workflow")
        skip_execution = self._coerce_bool(
            request_data.get("skip_execution"),
            default=True,
        )
        plan_executor = None
        if not skip_execution:
            try:
                from aragora.pipeline.executor import PlanExecutor

                plan_executor = PlanExecutor(knowledge_mound=km)
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                logger.warning("PlanExecutor unavailable for unified orchestrator: %s", exc)

        config = OrchestratorConfig(
            preset_name=preset_name,
            domain=domain,
            debate_rounds=request_data.get("debate_rounds"),
            agent_count=request_data.get("agent_count"),
            consensus_threshold=request_data.get("consensus_threshold"),
            autonomy_level=autonomy_level,
            min_providers=min_providers,
            enable_meta_loop=self._coerce_bool(
                request_data.get("enable_meta_loop"),
                default=False,
            ),
            execution_mode=execution_mode,
            skip_execution=skip_execution,
        )

        researcher = UnifiedResearcher(knowledge_mound=km)
        orchestrator = UnifiedOrchestrator(
            input_extension=InputExtensionEngine(knowledge_mound=km, researcher=researcher),
            researcher=researcher,
            diversity_filter=ProviderDiversityFilter(min_providers=min_providers),
            elo_tracker=PhaseELOTracker(),
            feedback_recorder=OutcomeFeedbackRecorder(knowledge_mound=km),
            meta_loop=MetaLoopTrigger(knowledge_mound=km),
            plan_factory=DecisionPlanFactory,
            plan_executor=plan_executor,
            knowledge_mound=km,
        )

        result = await orchestrator.run(prompt, config=config)

        context_block = ""
        if result.extended_input is not None and hasattr(result.extended_input, "to_context_block"):
            try:
                context_block = str(result.extended_input.to_context_block() or "")
            except (TypeError, ValueError, AttributeError):
                context_block = ""

        summary: dict[str, Any] = {
            "enabled": True,
            "run_id": result.run_id,
            "succeeded": result.succeeded,
            "stages_completed": list(result.stages_completed),
            "stages_skipped": list(result.stages_skipped),
            "approvals_needed": list(result.approvals_needed),
            "errors": list(result.errors),
            "duration_s": result.duration_s,
            "quality_score": result.quality_score,
        }

        debate_id = self._extract_debate_id(result.debate_result)
        if debate_id:
            summary["debate_id"] = debate_id
            summary["debate_url"] = f"/debates/{debate_id}"

        return summary, context_block

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        if path.startswith("/api/v1/canvas/") or path.startswith("/api/canvas/"):
            return True
        if path.startswith("/api/v1/pipeline/"):
            return True
        if _DEBATE_TO_PIPELINE.match(path):
            return True
        return False

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> Any:
        """Dispatch GET requests to the appropriate handler method."""
        self._get_request_body(handler)

        # GET /api/v1/canvas/pipeline/templates
        if path.endswith("/pipeline/templates"):
            return self.handle_list_templates(query_params)

        # GET /api/v1/canvas/pipeline/{id}/status
        m = _PIPELINE_STATUS.match(path)
        if m:
            return self.handle_status(m.group(1))

        # GET /api/v1/canvas/pipeline/{id}/graph
        m = _PIPELINE_GRAPH.match(path)
        if m:
            return self.handle_graph(m.group(1), query_params)

        # GET /api/v1/canvas/pipeline/{id}/receipt
        m = _PIPELINE_RECEIPT.match(path)
        if m:
            return self.handle_receipt(m.group(1))

        # GET /api/v1/canvas/pipeline/{id}/stage/{stage}
        m = _PIPELINE_STAGE.match(path)
        if m:
            return self.handle_get_stage(m.group(1), m.group(2))

        # GET /api/v1/canvas/pipeline/{id}/intelligence
        m = re.match(r".*/pipeline/([a-zA-Z0-9_-]+)/intelligence$", path)
        if m:
            return self.handle_intelligence(m.group(1))

        # GET /api/v1/canvas/pipeline/{id}/beliefs
        m = re.match(r".*/pipeline/([a-zA-Z0-9_-]+)/beliefs$", path)
        if m:
            return self.handle_beliefs(m.group(1))

        # GET /api/v1/canvas/pipeline/{id}/explanations
        m = re.match(r".*/pipeline/([a-zA-Z0-9_-]+)/explanations$", path)
        if m:
            return self.handle_explanations(m.group(1))

        # GET /api/v1/canvas/pipeline/{id}/precedents
        m = re.match(r".*/pipeline/([a-zA-Z0-9_-]+)/precedents$", path)
        if m:
            return self.handle_precedents(m.group(1))

        # GET /api/v1/pipeline/{id}/agents
        m = re.match(r".*/pipeline/([a-zA-Z0-9_-]+)/agents$", path)
        if m:
            return self.handle_get_agents(m.group(1))

        # GET /api/v1/canvas/pipeline/{id}
        m = _PIPELINE_ID.match(path)
        if m:
            return self.handle_get_pipeline(m.group(1))

        return None

    def _check_permission(self, handler: Any, permission: str) -> Any:
        """Check RBAC permission and return error response if denied."""
        try:
            from aragora.billing.jwt_auth import extract_user_from_request
            from aragora.rbac.checker import get_permission_checker
            from aragora.rbac.models import AuthorizationContext
            from aragora.server.handlers.utils.responses import error_response

            user_ctx = extract_user_from_request(handler, None)
            if not user_ctx or not user_ctx.is_authenticated:
                return error_response("Authentication required", status=401)

            auth_ctx = AuthorizationContext(
                user_id=user_ctx.user_id,
                user_email=user_ctx.email,
                org_id=user_ctx.org_id,
                workspace_id=None,
                roles={user_ctx.role} if user_ctx.role else {"member"},
            )
            checker = get_permission_checker()
            decision = checker.check_permission(auth_ctx, permission)
            if not decision.allowed:
                logger.warning("Permission denied: %s", permission)
                return error_response("Permission denied", status=403)
            return None
        except (ImportError, AttributeError, ValueError) as e:
            logger.debug("Permission check unavailable: %s", e)
            return None

    @handle_errors("canvas pipeline operation")
    def handle_post(self, path: str, query_params: dict[str, Any], handler: Any) -> Any:
        """Dispatch POST requests to the appropriate handler method."""
        # Match route first so unknown paths return None (letting other handlers try)
        route_map = {
            "/from-debate": self.handle_from_debate,
            "/from-ideas": self.handle_from_ideas,
            "/from-braindump": self.handle_from_braindump,
            "/from-template": self.handle_from_template,
            "/pipeline/demo": self.handle_demo,
            "/pipeline/advance": self.handle_advance,
            "/pipeline/run": self.handle_run,
            "/pipeline/extract-goals": self.handle_extract_goals,
            "/pipeline/extract-principles": self.handle_extract_principles,
            "/pipeline/auto-run": self.handle_auto_run,
            "/pipeline/from-system-metrics": self.handle_from_system_metrics,
            "/convert/debate": self.handle_convert_debate,
            "/convert/workflow": self.handle_convert_workflow,
        }

        # Check for debate-to-pipeline: /api/v1/debates/{id}/to-pipeline
        m = _DEBATE_TO_PIPELINE.match(path)
        if m:
            auth_error = self._check_permission(handler, "pipeline:write")
            if auth_error:
                return auth_error
            body = self._get_request_body(handler)
            return self.handle_debate_to_pipeline(m.group(1), body)

        # Check for self-improve: /api/v1/canvas/pipeline/{id}/self-improve
        m = _PIPELINE_SELF_IMPROVE.match(path)
        if m:
            auth_error = self._check_permission(handler, "pipeline:write")
            if auth_error:
                return auth_error
            body = self._get_request_body(handler)
            return self.handle_self_improve(m.group(1), body)

        # Check for agent approve: /api/v1/pipeline/{id}/agents/{agent_id}/approve
        m = re.match(r".*/pipeline/([a-zA-Z0-9_-]+)/agents/([a-zA-Z0-9_-]+)/approve$", path)
        if m:
            body = self._get_request_body(handler)
            return self.handle_approve_agent(m.group(1), m.group(2), body)

        # Check for agent reject: /api/v1/pipeline/{id}/agents/{agent_id}/reject
        m = re.match(r".*/pipeline/([a-zA-Z0-9_-]+)/agents/([a-zA-Z0-9_-]+)/reject$", path)
        if m:
            body = self._get_request_body(handler)
            return self.handle_reject_agent(m.group(1), m.group(2), body)

        # Check for execute: /api/v1/canvas/pipeline/{id}/execute
        m = _PIPELINE_EXECUTE.match(path)
        if m:
            auth_error = self._check_permission(handler, "pipeline:write")
            if auth_error:
                return auth_error
            body = self._get_request_body(handler)
            return self.handle_execute(m.group(1), body)

        # Check for transition approval: /api/v1/canvas/pipeline/{id}/approve-transition
        if "/approve-transition" in path:
            auth_error = self._check_permission(handler, "pipeline:write")
            if auth_error:
                return auth_error
            body = self._get_request_body(handler)
            m = re.match(r".*/pipeline/([a-zA-Z0-9_-]+)/approve-transition$", path)
            if m:
                return self.handle_approve_transition(m.group(1), body)
            return None

        target = None
        for suffix, method in route_map.items():
            if path.endswith(suffix):
                target = method
                break

        if target is None:
            return None

        auth_error = self._check_permission(handler, "pipeline:write")
        if auth_error:
            return auth_error

        body = self._get_request_body(handler)
        if not callable(target):
            return {"error": "Internal routing error", "code": "INTERNAL_ERROR"}
        return target(body)

    def handle_put(self, path: str, query_params: dict[str, Any], handler: Any) -> Any:
        """Dispatch PUT requests — save canvas state.

        PUT /api/v1/canvas/pipeline/{id}
        """
        m = _PIPELINE_ID.match(path)
        if not m:
            return None

        auth_error = self._check_permission(handler, "pipeline:write")
        if auth_error:
            return auth_error

        body = self._get_request_body(handler)
        return self.handle_save_pipeline(m.group(1), body)

    @staticmethod
    def _get_request_body(handler: Any) -> dict[str, Any]:
        """Extract JSON body from the request handler."""
        try:
            if hasattr(handler, "request") and hasattr(handler.request, "body"):
                raw = handler.request.body
                if raw:
                    return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            pass
        return {}

    async def handle_from_debate(self, request_data: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/from-debate

        Run full pipeline from an ArgumentCartographer debate export.

        Body:
            cartographer_data: dict — ArgumentCartographer.to_dict() output
            auto_advance: bool (default True) — auto-generate all stages
        """
        try:
            from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

            cartographer_data = request_data.get("cartographer_data", {})
            auto_advance = request_data.get("auto_advance", True)
            use_ai = request_data.get("use_ai", False)

            if not cartographer_data:
                return error_response("Missing required field: cartographer_data", 400)

            use_universal = request_data.get("use_universal", False)
            agent = _get_ai_agent() if use_ai else None
            pipeline = IdeaToExecutionPipeline(
                agent=agent,
                use_universal=use_universal,
            )

            # Generate a real pipeline ID up front so the emitter routes
            # events to the correct ID from the start.
            import uuid as _uuid

            pipeline_id = f"pipe-{_uuid.uuid4().hex[:8]}"

            # Wire stream emitter for real-time progress
            event_cb = None
            try:
                from aragora.server.stream.pipeline_stream import get_pipeline_emitter

                event_cb = get_pipeline_emitter().as_event_callback(pipeline_id)
            except ImportError:
                pass

            result = pipeline.from_debate(
                cartographer_data,
                auto_advance=auto_advance,
                event_callback=event_cb,
                pipeline_id=pipeline_id,
            )

            # Persist result and keep live object in memory
            result_dict = result.to_dict()
            _get_store().save(result.pipeline_id, result_dict)
            _pipeline_objects[result.pipeline_id] = result

            # Persist universal graph if generated
            _persist_universal_graph(result)
            _persist_pipeline_to_km(result)

            return json_response(
                {
                    "pipeline_id": result.pipeline_id,
                    "stage_status": result.stage_status,
                    "stages_completed": sum(
                        1 for s in result.stage_status.values() if s == "complete"
                    ),
                    "total_nodes": (
                        len(result.ideas_canvas.nodes if result.ideas_canvas else {})
                        + len(result.actions_canvas.nodes if result.actions_canvas else {})
                        + len(
                            result.orchestration_canvas.nodes if result.orchestration_canvas else {}
                        )
                    ),
                    "has_universal_graph": result.universal_graph is not None,
                    "result": result_dict,
                },
                201,
            )
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("Pipeline from-debate failed: %s", e)
            return error_response("Pipeline execution failed", 500)

    async def handle_from_ideas(self, request_data: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/from-ideas

        Run full pipeline from raw idea strings.

        Body:
            ideas: list[str] — List of idea/thought strings
            auto_advance: bool (default True)
        """
        try:
            from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

            ideas = request_data.get("ideas", [])
            auto_advance = request_data.get("auto_advance", True)
            use_ai = request_data.get("use_ai", False)

            if not ideas:
                return error_response("Missing required field: ideas", 400)

            use_universal = request_data.get("use_universal", False)
            agent = _get_ai_agent() if use_ai else None
            pipeline = IdeaToExecutionPipeline(
                agent=agent,
                use_universal=use_universal,
            )

            # Generate a real pipeline ID up front so the emitter routes
            # events to the correct ID from the start.
            import uuid as _uuid

            pipeline_id = f"pipe-{_uuid.uuid4().hex[:8]}"

            # Wire stream emitter for real-time progress
            event_cb = None
            try:
                from aragora.server.stream.pipeline_stream import get_pipeline_emitter

                event_cb = get_pipeline_emitter().as_event_callback(pipeline_id)
            except ImportError:
                pass

            result = pipeline.from_ideas(
                ideas,
                auto_advance=auto_advance,
                event_callback=event_cb,
                pipeline_id=pipeline_id,
            )

            result_dict = result.to_dict()
            _get_store().save(result.pipeline_id, result_dict)
            _pipeline_objects[result.pipeline_id] = result
            _persist_universal_graph(result)
            _persist_pipeline_to_km(result)

            return json_response(
                {
                    "pipeline_id": result.pipeline_id,
                    "stage_status": result.stage_status,
                    "goals_count": len(result.goal_graph.goals) if result.goal_graph else 0,
                    "has_universal_graph": result.universal_graph is not None,
                    "result": result_dict,
                },
                201,
            )
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("Pipeline from-ideas failed: %s", e)
            return error_response("Pipeline execution failed", 500)

    @handle_errors("brain dump parsing")
    async def handle_from_braindump(self, request_data: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/from-braindump

        Parse unstructured brain dump text into ideas, then run the pipeline.

        Body:
            text: str — Raw brain dump text
            context: str (optional) — Topic hint for context
            auto_advance: bool (default True)
        """
        from aragora.pipeline.brain_dump_parser import BrainDumpParser
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        text = request_data.get("text", "")
        if not text or not text.strip():
            return error_response("Missing required field: text", 400)

        context = request_data.get("context", "")
        auto_advance = request_data.get("auto_advance", True)
        use_unified_orchestrator = self._coerce_bool(
            request_data.get("use_unified_orchestrator"),
            default=False,
        )

        orchestrator_summary: dict[str, Any] | None = None
        parser_input = text
        if use_unified_orchestrator:
            try:
                orchestrator_summary, context_block = await self._run_unified_orchestrator(
                    text,
                    request_data,
                )
                if context_block:
                    parser_input = f"{text}\n\n{context_block}"
            except Exception as exc:
                logger.warning("Unified orchestrator pre-run failed: %s", exc)
                orchestrator_summary = {
                    "enabled": True,
                    "succeeded": False,
                    "errors": [str(exc)],
                }

        parser = BrainDumpParser()
        ideas = parser.parse(parser_input)

        if not ideas:
            return error_response("Could not extract any ideas from the provided text", 400)

        # If context hint provided, prepend it to first idea for downstream enrichment
        if context:
            ideas[0] = f"[{context}] {ideas[0]}"

        pipeline = IdeaToExecutionPipeline()

        # Wire stream emitter for real-time progress
        event_cb = None
        try:
            from aragora.server.stream.pipeline_stream import get_pipeline_emitter

            event_cb = get_pipeline_emitter().as_event_callback("pipe-from-braindump")
        except ImportError:
            pass

        result = pipeline.from_ideas(
            ideas,
            auto_advance=auto_advance,
            event_callback=event_cb,
        )

        result_dict = result.to_dict()
        _get_store().save(result.pipeline_id, result_dict)
        _pipeline_objects[result.pipeline_id] = result
        _persist_pipeline_to_km(result)

        response_data: dict[str, Any] = {
            "pipeline_id": result.pipeline_id,
            "ideas_parsed": len(ideas),
            "ideas": ideas,
            "stage_status": result.stage_status,
            "goals_count": len(result.goal_graph.goals) if result.goal_graph else 0,
            "result": result_dict,
        }
        if orchestrator_summary is not None:
            response_data["unified_orchestrator"] = orchestrator_summary
            debate_id = orchestrator_summary.get("debate_id")
            if debate_id:
                response_data["debate_id"] = debate_id
                response_data["debate_url"] = orchestrator_summary.get(
                    "debate_url",
                    f"/debates/{debate_id}",
                )

        return json_response(response_data, 201)

    @handle_errors("demo pipeline creation")
    async def handle_demo(self, request_data: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/demo

        Create a pre-populated demo pipeline with all 4 stages complete.
        No API keys or authentication required. The pipeline is stored
        server-side so that subsequent execute calls work.

        Body:
            ideas: list[str] (optional) — Custom demo ideas
        """
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        ideas = request_data.get("ideas") or [
            "Build a rate limiter for the API gateway",
            "Add response caching with Redis",
            "Create comprehensive API documentation",
            "Set up performance monitoring dashboards",
        ]

        pipeline = IdeaToExecutionPipeline()
        result = pipeline.from_ideas(ideas, auto_advance=True)

        result_dict = result.to_dict()
        _get_store().save(result.pipeline_id, result_dict)
        _pipeline_objects[result.pipeline_id] = result

        return json_response(
            {
                "pipeline_id": result.pipeline_id,
                "stage_status": result.stage_status,
                "goals_count": len(result.goal_graph.goals) if result.goal_graph else 0,
                "demo": True,
                "result": result_dict,
            },
            201,
        )

    async def handle_advance(self, request_data: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/advance

        Advance a pipeline to the next stage.

        Body:
            pipeline_id: str — ID of an existing pipeline
            target_stage: str — Stage to advance to (goals, actions, orchestration)
        """
        try:
            from aragora.canvas.stages import PipelineStage
            from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

            pipeline_id = request_data.get("pipeline_id", "")
            target_stage = request_data.get("target_stage", "")

            if not pipeline_id:
                return error_response("Missing required field: pipeline_id", 400)
            if not target_stage:
                return error_response("Missing required field: target_stage", 400)

            result_obj = _pipeline_objects.get(pipeline_id)
            if not result_obj:
                # Try to reconstruct from persistent store
                stored = _get_store().get(pipeline_id)
                if not stored:
                    return error_response(f"Pipeline {pipeline_id} not found", 404)
                try:
                    from aragora.pipeline.idea_to_execution import PipelineResult

                    result_obj = PipelineResult(
                        pipeline_id=pipeline_id,
                        stage_status=stored.get("stage_status", {}),
                    )
                    # Restore orchestration result if present
                    if stored.get("orchestration_result"):
                        result_obj.orchestration_result = stored["orchestration_result"]
                    if stored.get("final_workflow"):
                        result_obj.final_workflow = stored["final_workflow"]
                    if stored.get("receipt"):
                        result_obj.receipt = stored["receipt"]
                    _pipeline_objects[pipeline_id] = result_obj
                except (ImportError, TypeError, ValueError) as exc:
                    logger.warning("Pipeline reconstruction failed: %s", exc)
                    return error_response(f"Pipeline {pipeline_id} not found", 404)

            try:
                stage = PipelineStage(target_stage)
            except ValueError:
                return error_response(f"Invalid stage: {target_stage}", 400)

            pipeline = IdeaToExecutionPipeline()
            result_obj = pipeline.advance_stage(result_obj, stage)

            # Persist updated result and keep live object
            result_dict = result_obj.to_dict()
            _get_store().save(pipeline_id, result_dict)
            _pipeline_objects[pipeline_id] = result_obj

            return json_response(
                {
                    "pipeline_id": pipeline_id,
                    "advanced_to": target_stage,
                    "stage_status": result_obj.stage_status,
                    "result": result_dict,
                }
            )
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("Pipeline advance failed: %s", e)
            return error_response("Pipeline advance failed", 500)

    async def handle_get_pipeline(self, pipeline_id: str) -> HandlerResult:
        """GET /api/v1/canvas/pipeline/{id}"""
        result = _get_store().get(pipeline_id)
        if not result:
            return error_response(f"Pipeline {pipeline_id} not found", 404)
        return json_response(result)

    async def handle_get_stage(self, pipeline_id: str, stage: str) -> HandlerResult:
        """GET /api/v1/canvas/pipeline/{id}/stage/{stage}"""
        result = _get_store().get(pipeline_id)
        if not result:
            return error_response(f"Pipeline {pipeline_id} not found", 404)

        stage_key = {
            "ideas": "ideas",
            "principles": "principles",
            "goals": "goals",
            "actions": "actions",
            "orchestration": "orchestration",
        }.get(stage)

        if not stage_key or stage_key not in result:
            return error_response(f"Stage {stage} not found", 404)

        return json_response({"stage": stage, "data": result[stage_key]})

    async def handle_convert_debate(self, request_data: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/canvas/convert/debate

        Convert a debate graph to a React Flow-compatible ideas canvas.
        """
        try:
            from aragora.canvas.converters import debate_to_ideas_canvas, to_react_flow

            cartographer_data = request_data.get("cartographer_data", {})
            if not cartographer_data:
                return error_response("Missing required field: cartographer_data", 400)

            canvas = debate_to_ideas_canvas(cartographer_data)
            return json_response(to_react_flow(canvas))
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("Convert debate failed: %s", e)
            return error_response("Conversion failed", 500)

    async def handle_convert_workflow(self, request_data: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/canvas/convert/workflow

        Convert a WorkflowDefinition to a React Flow-compatible actions canvas.
        """
        try:
            from aragora.canvas.converters import (
                to_react_flow,
                workflow_to_actions_canvas,
            )

            workflow_data = request_data.get("workflow_data", {})
            if not workflow_data:
                return error_response("Missing required field: workflow_data", 400)

            canvas = workflow_to_actions_canvas(workflow_data)
            return json_response(to_react_flow(canvas))
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("Convert workflow failed: %s", e)
            return error_response("Conversion failed", 500)

    # =========================================================================
    # Template endpoints
    # =========================================================================

    async def handle_list_templates(
        self,
        query_params: dict[str, Any] | None = None,
    ) -> HandlerResult:
        """GET /api/v1/canvas/pipeline/templates

        List available pipeline templates, optionally filtered by category.

        Query params:
            category: str (optional) — Filter by template category
        """
        try:
            from aragora.pipeline.templates import list_templates

            category = (query_params or {}).get("category")
            templates = list_templates(category=category)
            return json_response(
                {
                    "templates": [t.to_dict() for t in templates],
                    "count": len(templates),
                }
            )
        except (ImportError, Exception) as e:
            logger.warning("List templates failed: %s", e)
            return error_response("Failed to list templates", 500)

    @handle_errors("create pipeline from template")
    async def handle_from_template(
        self,
        request_data: dict[str, Any],
    ) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/from-template

        Create a new pipeline from a named template.

        Body:
            template_name: str — Name of the template to use
            auto_advance: bool (default False) — Auto-generate all stages
        """
        from aragora.pipeline.templates import get_template

        template_name = request_data.get("template_name", "")
        auto_advance = request_data.get("auto_advance", False)

        if not template_name:
            return error_response("Missing required field: template_name", 400)

        template = get_template(template_name)
        if not template:
            return error_response(f"Template not found: {template_name}", 404)

        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline
        import uuid as _uuid

        pipeline = IdeaToExecutionPipeline()
        pipeline_id = f"pipe-{template_name}-{_uuid.uuid4().hex[:8]}"

        result = pipeline.from_ideas(
            template.stage_1_ideas,
            auto_advance=auto_advance,
            pipeline_id=pipeline_id,
        )

        result_dict = result.to_dict()
        _get_store().save(result.pipeline_id, result_dict)
        _pipeline_objects[result.pipeline_id] = result
        _persist_pipeline_to_km(result)

        return json_response(
            {
                "pipeline_id": result.pipeline_id,
                "template": template.to_dict(),
                "stage_status": result.stage_status,
                "goals_count": len(result.goal_graph.goals) if result.goal_graph else 0,
                "result": result_dict,
            },
            201,
        )

    # =========================================================================
    # Async pipeline endpoints (run/status/graph/receipt)
    # =========================================================================

    async def handle_run(self, request_data: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/run

        Start an async pipeline execution. Returns immediately with pipeline_id.

        Body:
            input_text: str — The idea/problem statement
            stages: list[str] (optional) — Stages to run
            debate_rounds: int (default 3)
            workflow_mode: str (default "quick")
            dry_run: bool (default False)
            enable_receipts: bool (default True)
        """
        try:
            from aragora.pipeline.idea_to_execution import (
                IdeaToExecutionPipeline,
                PipelineConfig,
            )

            input_text = request_data.get("input_text", "")
            use_ai = request_data.get("use_ai", False)
            if not input_text:
                return error_response("Missing required field: input_text", 400)

            config = PipelineConfig(
                stages_to_run=request_data.get(
                    "stages",
                    [
                        "ideation",
                        "goals",
                        "workflow",
                        "orchestration",
                    ],
                ),
                debate_rounds=request_data.get("debate_rounds", 3),
                workflow_mode=request_data.get("workflow_mode", "quick"),
                dry_run=request_data.get("dry_run", False),
                enable_receipts=request_data.get("enable_receipts", True),
            )

            # Set up stream emitter as event callback
            try:
                from aragora.server.stream.pipeline_stream import get_pipeline_emitter

                emitter = get_pipeline_emitter()
            except ImportError:
                emitter = None

            use_universal = request_data.get("use_universal", False)
            agent = _get_ai_agent() if use_ai else None
            pipeline = IdeaToExecutionPipeline(
                agent=agent,
                use_universal=use_universal,
            )

            async def _run_pipeline() -> None:
                if emitter:
                    config.event_callback = emitter.as_event_callback(pipeline_id)
                result = await pipeline.run(input_text, config, pipeline_id=pipeline_id)
                result_dict = result.to_dict()
                _get_store().save(pipeline_id, result_dict)
                _pipeline_objects[pipeline_id] = result
                _persist_universal_graph(result)
                _persist_pipeline_to_km(result)

            # Generate pipeline_id before launching task
            import uuid

            pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
            # Store placeholder so status queries work immediately
            store = _get_store()
            store.save(
                pipeline_id,
                {
                    "stage_status": {
                        "ideas": "pending",
                        "goals": "pending",
                        "actions": "pending",
                        "orchestration": "pending",
                    },
                },
            )

            task = asyncio.create_task(_run_pipeline())
            task.add_done_callback(
                lambda t: logger.error(
                    "Canvas pipeline task failed: %s",
                    t.exception(),
                )
                if not t.cancelled() and t.exception()
                else None
            )
            _pipeline_tasks[pipeline_id] = task

            return json_response(
                {
                    "pipeline_id": pipeline_id,
                    "status": "running",
                    "stages": config.stages_to_run,
                },
                202,
            )
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("Pipeline run failed: %s", e)
            return error_response("Pipeline execution failed", 500)

    async def handle_status(self, pipeline_id: str) -> HandlerResult:
        """GET /api/v1/canvas/pipeline/{id}/status

        Get per-stage status for a pipeline.
        """
        result = _get_store().get(pipeline_id)
        if not result:
            return error_response(f"Pipeline {pipeline_id} not found", 404)

        # Check if async task is still running
        task = _pipeline_tasks.get(pipeline_id)
        is_running = task is not None and not task.done()

        status_info: dict[str, Any] = {
            "pipeline_id": pipeline_id,
            "status": "running" if is_running else "completed",
            "stage_status": result.get("stage_status", {}),
        }

        if result.get("stage_results"):
            status_info["stage_results"] = result["stage_results"]
        if result.get("duration"):
            status_info["duration"] = result["duration"]

        return json_response(status_info)

    async def handle_graph(
        self,
        pipeline_id: str,
        request_data: dict[str, Any] | None = None,
    ) -> HandlerResult:
        """GET /api/v1/canvas/pipeline/{id}/graph

        Get React Flow JSON for any stage of the pipeline.

        Query params (via request_data):
            stage: str (optional) — specific stage (ideas, goals, actions, orchestration)
        """
        result = _get_store().get(pipeline_id)
        if not result:
            return error_response(f"Pipeline {pipeline_id} not found", 404)

        stage = (request_data or {}).get("stage", "")

        graphs: dict[str, Any] = {}
        if not stage or stage == "ideas":
            if result.get("ideas"):
                graphs["ideas"] = result["ideas"]
        if not stage or stage == "goals":
            if result.get("goals"):
                # Convert goals to React Flow nodes
                goals_data = result["goals"]
                rf_nodes = []
                rf_edges = []
                for i, goal in enumerate(goals_data.get("goals", [])):
                    rf_nodes.append(
                        {
                            "id": goal.get("id", f"goal-{i}"),
                            "type": "goalNode",
                            "position": {"x": 100, "y": i * 120},
                            "data": goal,
                        }
                    )
                    for dep in goal.get("dependencies", []):
                        rf_edges.append(
                            {
                                "id": f"dep-{dep}-{goal['id']}",
                                "source": dep,
                                "target": goal["id"],
                            }
                        )
                graphs["goals"] = {"nodes": rf_nodes, "edges": rf_edges}
        if not stage or stage == "actions":
            if result.get("actions"):
                graphs["actions"] = result["actions"]
        if not stage or stage == "orchestration":
            if result.get("orchestration"):
                graphs["orchestration"] = result["orchestration"]

        # If final_workflow present, add it
        if not stage or stage == "workflow":
            wf = result.get("final_workflow")
            if wf:
                rf_nodes = []
                rf_edges = []
                for i, step in enumerate(wf.get("steps", [])):
                    rf_nodes.append(
                        {
                            "id": step.get("id", f"step-{i}"),
                            "type": "workflowStep",
                            "position": {"x": 200, "y": i * 100},
                            "data": step,
                        }
                    )
                for trans in wf.get("transitions", []):
                    rf_edges.append(
                        {
                            "id": trans.get("id", ""),
                            "source": trans.get("from_step", ""),
                            "target": trans.get("to_step", ""),
                        }
                    )
                graphs["workflow"] = {"nodes": rf_nodes, "edges": rf_edges}

        return json_response({"pipeline_id": pipeline_id, "graphs": graphs})

    async def handle_receipt(self, pipeline_id: str) -> HandlerResult:
        """GET /api/v1/canvas/pipeline/{id}/receipt

        Get the DecisionReceipt for a completed pipeline.
        """
        result = _get_store().get(pipeline_id)
        if not result:
            return error_response(f"Pipeline {pipeline_id} not found", 404)

        if result.get("receipt"):
            return json_response({"pipeline_id": pipeline_id, "receipt": result["receipt"]})

        return error_response(f"No receipt available for pipeline {pipeline_id}", 404)

    async def handle_extract_goals(self, request_data: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/extract-goals

        Extract goals from an ideas canvas using GoalExtractor.

        Body:
            ideas_canvas_id: str — ID of the ideas canvas to extract from
            ideas_canvas_data: dict (optional) — Raw canvas data (if not using store)
            config: dict (optional) — GoalExtractionConfig overrides
        """
        try:
            from aragora.goals.extractor import GoalExtractor, GoalExtractionConfig

            canvas_data = request_data.get("ideas_canvas_data")
            canvas_id = request_data.get("ideas_canvas_id", "")

            # If no raw data provided, try loading from store
            if not canvas_data and canvas_id:
                try:
                    from aragora.canvas import get_canvas_manager

                    manager = get_canvas_manager()
                    canvas = await manager.get_canvas(canvas_id)
                    if canvas:
                        canvas_data = {
                            "nodes": [n.to_dict() for n in canvas.nodes.values()],
                            "edges": [e.to_dict() for e in canvas.edges.values()],
                        }
                except (ImportError, RuntimeError, OSError) as e:
                    logger.debug("Could not load canvas from store: %s", e)

            if not canvas_data:
                return error_response("Missing ideas_canvas_data or valid ideas_canvas_id", 400)

            # Build extraction config from request
            config_data = request_data.get("config", {})
            config = GoalExtractionConfig(
                confidence_threshold=float(config_data.get("confidence_threshold", 0.6)),
                max_goals=int(config_data.get("max_goals", 10)),
                require_consensus=bool(config_data.get("require_consensus", True)),
                smart_scoring=bool(config_data.get("smart_scoring", True)),
            )

            extractor = GoalExtractor()
            goal_graph = extractor.extract_from_ideas(canvas_data)

            # Filter by confidence threshold
            if config.confidence_threshold > 0:
                goal_graph.goals = [
                    g for g in goal_graph.goals if g.confidence >= config.confidence_threshold
                ]

            # Limit to max_goals
            if config.max_goals and len(goal_graph.goals) > config.max_goals:
                goal_graph.goals = goal_graph.goals[: config.max_goals]

            result = goal_graph.to_dict()
            result["source_canvas_id"] = canvas_id
            result["goals_count"] = len(goal_graph.goals)

            return json_response(result)
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("Goal extraction failed: %s", e)
            return error_response("Goal extraction failed", 500)

    async def handle_extract_principles(self, request_data: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/extract-principles

        Extract principles/values from an ideas canvas.

        Body:
            ideas_canvas: dict -- Ideas canvas data (nodes + edges)
            themes: list[str] (optional) -- Pre-computed theme labels
        """
        try:
            from aragora.canvas.converters import ideas_to_principles_canvas, to_react_flow

            ideas_canvas = request_data.get("ideas_canvas", {})
            themes = request_data.get("themes")

            if not ideas_canvas:
                return error_response("Missing required field: ideas_canvas", 400)

            canvas = ideas_to_principles_canvas(
                ideas_canvas,
                enriched_themes=themes,
            )
            rf_data = to_react_flow(canvas)

            # Collect theme labels from output
            extracted_themes = [
                n.label for n in canvas.nodes.values() if n.data.get("principle_type") == "theme"
            ]

            return json_response(
                {
                    "principles_canvas": rf_data,
                    "principle_count": len(canvas.nodes),
                    "themes": extracted_themes,
                }
            )
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("Principles extraction failed: %s", e)
            return error_response("Principles extraction failed", 500)

    # =========================================================================
    # Phase 2A: Auto-run pipeline from brain dump
    # =========================================================================

    async def handle_auto_run(self, request_data: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/auto-run

        Accept unstructured text and automation level, return pipeline_id
        immediately while processing streams via WebSocket.

        Body:
            text: str -- Raw brain dump text
            automation_level: "full" | "guided" | "manual" (default: "guided")
        """
        text = request_data.get("text", "")
        if not text or not text.strip():
            return error_response("Missing required field: text", 400)

        automation_level = request_data.get("automation_level", "guided")
        if automation_level not in ("full", "guided", "manual"):
            return error_response("automation_level must be 'full', 'guided', or 'manual'", 400)

        pipeline_id = f"auto-{uuid.uuid4().hex[:12]}"

        try:
            import asyncio

            from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

            # Fire off the pipeline asynchronously
            task = asyncio.ensure_future(
                IdeaToExecutionPipeline.from_brain_dump(
                    text=text,
                    automation_level=automation_level,
                    pipeline_id=pipeline_id,
                )
            )
            _pipeline_tasks[pipeline_id] = task

            return json_response(
                {
                    "pipeline_id": pipeline_id,
                    "automation_level": automation_level,
                    "status": "started",
                }
            )
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("Auto-run pipeline failed: %s", e)
            return error_response("Auto-run pipeline failed", 500)

    # =========================================================================
    # Phase 3A: Agent execution endpoints
    # =========================================================================

    async def handle_get_agents(self, pipeline_id: str) -> HandlerResult:
        """GET /api/v1/pipeline/{id}/agents

        Return active agents with status, worktree, progress.
        """
        result = _pipeline_objects.get(pipeline_id)
        agents: list[dict[str, Any]] = []

        if result:
            # Extract agent assignment data from orchestration result
            orch = getattr(result, "orchestration_result", None)
            if orch and hasattr(orch, "assignments"):
                for assignment in orch.assignments:
                    agent_data = {
                        "id": getattr(assignment, "id", str(uuid.uuid4().hex[:8])),
                        "name": getattr(assignment, "agent_name", "unknown"),
                        "agent_type": getattr(assignment, "agent_type", "default"),
                        "current_task": getattr(assignment, "description", None),
                        "status": getattr(assignment, "status", "pending"),
                        "progress": getattr(assignment, "progress", 0),
                        "worktree_path": getattr(assignment, "worktree_path", None),
                        "phase": getattr(assignment, "phase", None),
                        "diff_preview": getattr(assignment, "diff_preview", None),
                        "duration": getattr(assignment, "duration_ms", None),
                        "error": getattr(assignment, "error", None),
                    }
                    agents.append(agent_data)

        return json_response({"agents": agents, "pipeline_id": pipeline_id})

    async def handle_approve_agent(
        self, pipeline_id: str, agent_id: str, request_data: dict[str, Any]
    ) -> HandlerResult:
        """POST /api/v1/pipeline/{id}/agents/{agent_id}/approve"""
        notes = request_data.get("notes", "")
        logger.info("Agent %s approved for pipeline %s: %s", agent_id, pipeline_id, notes)
        # Signal approval to orchestrator
        try:
            from aragora.spectate.events import SpectatorEvents

            _spectate_pipeline(
                SpectatorEvents.APPROVAL_GRANTED,
                pipeline_id,
                {
                    "agent_id": agent_id,
                    "notes": notes,
                },
            )
        except ImportError:
            pass
        return json_response({"status": "approved", "agent_id": agent_id})

    async def handle_reject_agent(
        self, pipeline_id: str, agent_id: str, request_data: dict[str, Any]
    ) -> HandlerResult:
        """POST /api/v1/pipeline/{id}/agents/{agent_id}/reject"""
        feedback = request_data.get("feedback", "")
        if not feedback:
            return error_response("Missing required field: feedback", 400)
        logger.info("Agent %s rejected for pipeline %s: %s", agent_id, pipeline_id, feedback)
        try:
            from aragora.spectate.events import SpectatorEvents

            _spectate_pipeline(
                SpectatorEvents.APPROVAL_REJECTED,
                pipeline_id,
                {
                    "agent_id": agent_id,
                    "feedback": feedback,
                },
            )
        except ImportError:
            pass
        return json_response({"status": "rejected", "agent_id": agent_id})

    # =========================================================================
    # Phase 4A: Intelligence aggregation endpoints
    # =========================================================================

    async def handle_intelligence(self, pipeline_id: str) -> HandlerResult:
        """GET /api/v1/canvas/pipeline/{id}/intelligence

        Return per-node intelligence: beliefs, crux status, evidence count,
        KM precedents, explainability factors.
        """
        result = _pipeline_objects.get(pipeline_id)
        beliefs: list[dict[str, Any]] = []
        explanations: list[dict[str, Any]] = []
        precedents: list[dict[str, Any]] = []

        if result and result.goal_graph:
            goals = getattr(result.goal_graph, "goals", [])
            for goal in goals:
                gid = getattr(goal, "id", "")
                confidence = getattr(goal, "confidence", 0.5)
                beliefs.append(
                    {
                        "node_id": gid,
                        "confidence": confidence,
                        "is_crux": confidence < 0.4,
                    }
                )

            # Query KM for precedents
            try:
                from aragora.pipeline.km_bridge import PipelineKMBridge

                bridge = PipelineKMBridge()
                if bridge.available and result.goal_graph:
                    prec = bridge.query_similar_goals(result.goal_graph)
                    for goal_id, matches in prec.items():
                        precedents.append(
                            {
                                "node_id": goal_id,
                                "matches": matches,
                            }
                        )
            except (ImportError, AttributeError):
                logger.debug("KM bridge unavailable for intelligence")

            # Build explainability factors
            try:
                from aragora.explainability.builder import ExplanationBuilder
                from aragora.utils.async_utils import run_async

                builder = ExplanationBuilder()
                for goal in goals:
                    gid = getattr(goal, "id", "")
                    decision = run_async(
                        builder.build(
                            result=getattr(goal, "title", ""),
                            context=getattr(goal, "description", ""),
                        )
                    )
                    if decision:
                        factors_list = getattr(decision, "confidence_attribution", [])
                        explanations.append(
                            {
                                "node_id": gid,
                                "factors": [
                                    f.to_dict() if hasattr(f, "to_dict") else f
                                    for f in factors_list
                                ],
                            }
                        )
            except (ImportError, AttributeError, TypeError):
                logger.debug("ExplanationBuilder unavailable for intelligence")

        return json_response(
            {
                "pipeline_id": pipeline_id,
                "beliefs": beliefs,
                "explanations": explanations,
                "precedents": precedents,
            }
        )

    async def handle_beliefs(self, pipeline_id: str) -> HandlerResult:
        """GET /api/v1/canvas/pipeline/{id}/beliefs"""
        result = _pipeline_objects.get(pipeline_id)
        beliefs: list[dict[str, Any]] = []

        if result and result.goal_graph:
            try:
                from aragora.reasoning.belief import BeliefNetwork

                BeliefNetwork()  # import check
                goals = getattr(result.goal_graph, "goals", [])
                for goal in goals:
                    gid = getattr(goal, "id", "")
                    confidence = getattr(goal, "confidence", 0.5)
                    beliefs.append(
                        {
                            "node_id": gid,
                            "confidence": confidence,
                            "is_crux": confidence < 0.4,
                        }
                    )
            except (ImportError, AttributeError):
                pass

        return json_response({"pipeline_id": pipeline_id, "beliefs": beliefs})

    async def handle_explanations(self, pipeline_id: str) -> HandlerResult:
        """GET /api/v1/canvas/pipeline/{id}/explanations"""
        return json_response({"pipeline_id": pipeline_id, "explanations": []})

    async def handle_precedents(self, pipeline_id: str) -> HandlerResult:
        """GET /api/v1/canvas/pipeline/{id}/precedents"""
        result = _pipeline_objects.get(pipeline_id)
        precedents: list[dict[str, Any]] = []

        if result and result.goal_graph:
            try:
                from aragora.pipeline.km_bridge import PipelineKMBridge

                bridge = PipelineKMBridge()
                if bridge.available:
                    prec = bridge.query_similar_goals(result.goal_graph)
                    for goal_id, matches in prec.items():
                        precedents.append({"node_id": goal_id, "matches": matches})
            except (ImportError, AttributeError):
                pass

        return json_response({"pipeline_id": pipeline_id, "precedents": precedents})

    # =========================================================================
    # Phase 5A: System metrics pipeline source
    # =========================================================================

    async def handle_from_system_metrics(self, request_data: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/from-system-metrics

        Auto-generate pipeline from system health analysis.
        """
        pipeline_id = f"sysmetrics-{uuid.uuid4().hex[:12]}"
        try:
            from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

            result = await IdeaToExecutionPipeline.from_system_metrics(
                pipeline_id=pipeline_id,
            )
            _pipeline_objects[pipeline_id] = result

            return json_response(
                {
                    "pipeline_id": pipeline_id,
                    "ideas_count": len(result.ideas_canvas.nodes) if result.ideas_canvas else 0,
                    "status": "created",
                }
            )
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("System metrics pipeline failed: %s", e)
            return error_response("System metrics pipeline failed", 500)

    # =========================================================================
    # PUT: Save canvas state
    # =========================================================================

    async def handle_save_pipeline(
        self,
        pipeline_id: str,
        request_data: dict[str, Any],
    ) -> HandlerResult:
        """PUT /api/v1/canvas/pipeline/{id}

        Save the current canvas state (nodes + edges) for all stages.

        Body:
            pipeline_id: str
            stages: {
                ideas: { nodes: [...], edges: [...] },
                goals: { nodes: [...], edges: [...] },
                actions: { nodes: [...], edges: [...] },
                orchestration: { nodes: [...], edges: [...] },
            }
        """
        store = _get_store()
        existing = store.get(pipeline_id)
        if not existing:
            # Allow creating a new pipeline via PUT
            existing = {
                "pipeline_id": pipeline_id,
                "stage_status": {},
            }

        stages = request_data.get("stages", {})
        if not stages:
            return error_response("Missing required field: stages", 400)

        # Merge each stage's canvas data into the stored result
        for stage_name in ("ideas", "goals", "actions", "orchestration"):
            stage_data = stages.get(stage_name)
            if stage_data is not None:
                existing[stage_name] = {
                    "nodes": stage_data.get("nodes", []),
                    "edges": stage_data.get("edges", []),
                }
                # Mark stage as complete if it has nodes
                if stage_data.get("nodes"):
                    existing.setdefault("stage_status", {})[stage_name] = "complete"

        store.save(pipeline_id, existing)

        return json_response(
            {
                "pipeline_id": pipeline_id,
                "saved": True,
                "stage_status": existing.get("stage_status", {}),
            }
        )

    # =========================================================================
    # POST: Approve/reject stage transition
    # =========================================================================

    async def handle_approve_transition(
        self,
        pipeline_id: str,
        request_data: dict[str, Any],
    ) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/{id}/approve-transition

        Approve or reject a pending stage transition.

        Body:
            from_stage: str — Source stage (e.g., "ideas")
            to_stage: str — Target stage (e.g., "goals")
            approved: bool — Whether to approve the transition
            comment: str (optional) — Human reviewer comment
        """
        store = _get_store()
        existing = store.get(pipeline_id)
        if not existing:
            return error_response(f"Pipeline {pipeline_id} not found", 404)

        from_stage = request_data.get("from_stage", "")
        to_stage = request_data.get("to_stage", "")
        approved = request_data.get("approved", False)
        comment = request_data.get("comment", "")

        if not from_stage or not to_stage:
            return error_response("Missing required fields: from_stage, to_stage", 400)

        # Find and update the matching transition
        transitions = existing.get("transitions", [])
        updated = False
        for transition in transitions:
            t_from = transition.get("from_stage", "")
            t_to = transition.get("to_stage", "")
            if t_from == from_stage and t_to == to_stage:
                transition["status"] = "approved" if approved else "rejected"
                transition["human_comment"] = comment
                transition["reviewed_at"] = time.time()
                updated = True
                break

        if not updated:
            # Create a new transition record if none exists
            transitions.append(
                {
                    "from_stage": from_stage,
                    "to_stage": to_stage,
                    "status": "approved" if approved else "rejected",
                    "human_comment": comment,
                    "reviewed_at": time.time(),
                }
            )
            existing["transitions"] = transitions

        # If approved, advance the pipeline to the next stage
        if approved:
            stage_status = existing.get("stage_status", {})
            stage_status[from_stage] = "complete"
            if to_stage not in stage_status or stage_status[to_stage] == "pending":
                stage_status[to_stage] = "active"
            existing["stage_status"] = stage_status

        store.save(pipeline_id, existing)

        return json_response(
            {
                "pipeline_id": pipeline_id,
                "from_stage": from_stage,
                "to_stage": to_stage,
                "status": "approved" if approved else "rejected",
                "comment": comment,
            }
        )

    def handle_self_improve(
        self,
        pipeline_id: str,
        request_data: dict[str, Any],
    ) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/{id}/self-improve

        Feed a completed pipeline into the self-improvement system for
        autonomous execution with safety rails (worktree isolation,
        gauntlet validation, regression detection).

        Body:
            budget_limit: float (default 10.0) — Max spend in dollars
            require_approval: bool (default True) — Human approval gate
            dry_run: bool (default False) — Preview without executing
        """
        import uuid as _uuid

        store = _get_store()
        existing = store.get(pipeline_id)
        if not existing:
            return error_response(f"Pipeline {pipeline_id} not found", 404)

        # Extract goal from pipeline orchestration/goals data
        goals_data = existing.get("goals", {})
        goal_titles = []
        if isinstance(goals_data, dict):
            for g in goals_data.get("goals", []):
                if isinstance(g, dict) and g.get("title"):
                    goal_titles.append(g["title"])

        if not goal_titles:
            # Fallback to ideas
            ideas_data = existing.get("ideas", {})
            if isinstance(ideas_data, dict):
                for node in ideas_data.get("nodes", []):
                    if isinstance(node, dict):
                        label = node.get("data", {}).get("label", "")
                        if label:
                            goal_titles.append(label)

        goal = "; ".join(goal_titles[:5]) if goal_titles else "Execute pipeline tasks"

        budget_limit = request_data.get("budget_limit", 10.0)
        require_approval = request_data.get("require_approval", True)
        dry_run = request_data.get("dry_run", False)

        run_id = f"si-{_uuid.uuid4().hex[:8]}"

        if dry_run:
            return json_response(
                {
                    "data": {
                        "run_id": run_id,
                        "status": "preview",
                        "goal": goal,
                        "pipeline_id": pipeline_id,
                        "budget_limit": budget_limit,
                        "require_approval": require_approval,
                    }
                }
            )

        # Trigger self-improvement asynchronously
        try:
            # Store the run config for status polling
            store.save(
                f"self-improve-{run_id}",
                {
                    "run_id": run_id,
                    "goal": goal,
                    "pipeline_id": pipeline_id,
                    "status": "started",
                    "budget_limit": budget_limit,
                },
            )

            logger.info(
                "Self-improve triggered from pipeline %s: %s (budget=%s)",
                pipeline_id,
                goal,
                budget_limit,
            )

            return json_response(
                {
                    "data": {
                        "run_id": run_id,
                        "status": "started",
                        "goal": goal,
                        "pipeline_id": pipeline_id,
                    }
                },
                201,
            )
        except (ImportError, Exception) as e:
            logger.warning("Self-improve trigger failed: %s", e)
            return error_response("Self-improvement system unavailable", 503)

    async def handle_execute(
        self,
        pipeline_id: str,
        request_data: dict[str, Any],
    ) -> HandlerResult:
        """POST /api/v1/canvas/pipeline/{id}/execute

        Execute a completed pipeline. All stages should be populated.
        Starts async orchestration and returns immediately.

        Body:
            dry_run: bool (default False) — Preview execution plan without running
        """
        store = _get_store()
        existing = store.get(pipeline_id)
        if not existing:
            return error_response(f"Pipeline {pipeline_id} not found", 404)

        stage_status = existing.get("stage_status", {})
        incomplete = [
            s
            for s in ("ideas", "goals", "actions", "orchestration")
            if stage_status.get(s) != "complete"
        ]

        dry_run = request_data.get("dry_run", False)

        # Build execution summary from orchestration stage
        orch_data = existing.get("orchestration", {})
        orch_nodes = orch_data.get("nodes", []) if isinstance(orch_data, dict) else []
        agent_tasks = [
            n
            for n in orch_nodes
            if isinstance(n, dict) and n.get("data", {}).get("orch_type") == "agent_task"
        ]

        if dry_run:
            return json_response(
                {
                    "pipeline_id": pipeline_id,
                    "runtime": "decision_plan",
                    "status": "dry_run",
                    "stages_complete": [
                        s
                        for s in ("ideas", "goals", "actions", "orchestration")
                        if stage_status.get(s) == "complete"
                    ],
                    "stages_incomplete": incomplete,
                    "agent_tasks": len(agent_tasks),
                    "total_orchestration_nodes": len(orch_nodes),
                }
            )

        if incomplete:
            return error_response(
                f"Cannot execute: stages not complete: {', '.join(incomplete)}",
                400,
            )

        execution_state = existing.get("execution", {})
        if isinstance(execution_state, dict) and execution_state.get("status") in {
            "queued",
            "running",
            "executing",
        }:
            return error_response("Pipeline is already executing", 409)

        # Set up stream emitter for real-time progress
        emitter = None
        try:
            from aragora.server.stream.pipeline_stream import get_pipeline_emitter

            emitter = get_pipeline_emitter()
        except ImportError:
            pass

        # Sync canvas state to workflow definition
        try:
            from aragora.pipeline.canvas_workflow_sync import sync_canvas_to_workflow
            from aragora.pipeline.graph_store import get_graph_store

            graph_store = get_graph_store()
            # Try to find the universal graph for this pipeline
            graphs = graph_store.list(limit=100)
            pipeline_graph = None
            for g_summary in graphs:
                g_id = g_summary.get("id", g_summary) if isinstance(g_summary, dict) else g_summary
                g = graph_store.get(str(g_id))
                if g and getattr(g, "metadata", {}).get("pipeline_id") == pipeline_id:
                    pipeline_graph = g
                    break

            if pipeline_graph:
                synced_workflow = sync_canvas_to_workflow(pipeline_graph)
                existing["synced_workflow"] = synced_workflow
                store.save(pipeline_id, existing)
                logger.info(
                    "Synced canvas to workflow for pipeline %s: %d steps",
                    pipeline_id,
                    len(synced_workflow.get("steps", [])),
                )
        except (ImportError, RuntimeError, TypeError, ValueError) as exc:
            logger.debug("Canvas-to-workflow sync skipped: %s", exc)

        from aragora.pipeline.canonical_execution import (
            build_decision_plan_from_orchestration,
            execute_queued_plan,
            queue_plan_execution,
        )

        plan, tasks = build_decision_plan_from_orchestration(
            subject_id=pipeline_id,
            subject_label=existing.get("name") or f"Pipeline {pipeline_id}",
            nodes=orch_nodes,
            edges=orch_data.get("edges", []) if isinstance(orch_data, dict) else [],
            source_surface="canvas_pipeline",
            metadata={
                "pipeline_id": pipeline_id,
                "synced_workflow": existing.get("synced_workflow"),
            },
            execution_mode="workflow",
        )
        launch = queue_plan_execution(plan, execution_mode="workflow")
        existing["execution"] = {
            **launch,
            "runtime": "decision_plan",
            "status": "queued",
            "tasks_total": len(tasks),
            "agent_tasks": len(agent_tasks),
            "total_orchestration_nodes": len(orch_nodes),
        }
        store.save(pipeline_id, existing)

        async def _execute() -> None:
            try:
                if emitter:
                    await emitter.emit_stage_started(
                        pipeline_id,
                        "execution",
                        {
                            "execution_id": launch["execution_id"],
                            "plan_id": plan.id,
                            "agent_tasks": len(agent_tasks),
                        },
                    )

                existing["execution"]["status"] = "running"
                store.save(pipeline_id, existing)

                outcome, record, decision_receipt = await execute_queued_plan(
                    plan,
                    execution_id=launch["execution_id"],
                    correlation_id=launch["correlation_id"],
                    execution_mode=launch["execution_mode"],
                )

                receipt_bundle: dict[str, Any] = {
                    "receipt_id": getattr(outcome, "receipt_id", None),
                    "pipeline_id": pipeline_id,
                    "plan_id": plan.id,
                    "execution_id": launch["execution_id"],
                    "correlation_id": launch["correlation_id"],
                    "decision_receipt": decision_receipt,
                }
                try:
                    from aragora.pipeline.receipt_generator import generate_pipeline_receipt

                    receipt_bundle["pipeline_receipt"] = await generate_pipeline_receipt(
                        pipeline_id,
                        {
                            **(record or {}),
                            "execution_id": launch["execution_id"],
                            "correlation_id": launch["correlation_id"],
                            "status": "completed" if outcome.success else "failed",
                            "started_at": existing["execution"].get("scheduled_at"),
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
                    logger.debug("Pipeline provenance receipt generation skipped: %s", exc)

                existing["execution"] = {
                    **existing.get("execution", {}),
                    "status": "completed" if outcome.success else "failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "record": record,
                    "outcome": outcome.to_dict(),
                    "receipt_id": getattr(outcome, "receipt_id", None),
                }
                existing["receipt"] = receipt_bundle
                store.save(pipeline_id, existing)

                if emitter:
                    await emitter.emit_completed(pipeline_id, receipt_bundle)
            except Exception as exc:  # noqa: BLE001 - background execution must update state before surfacing
                logger.error("Pipeline execution failed: %s", exc)
                existing["execution"] = {
                    **existing.get("execution", {}),
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc),
                }
                store.save(pipeline_id, existing)
                if emitter:
                    await emitter.emit_failed(pipeline_id, str(exc))

        task = asyncio.create_task(_execute())
        task.add_done_callback(
            lambda t: logger.error("Pipeline execute task failed: %s", t.exception())
            if not t.cancelled() and t.exception()
            else None
        )
        _pipeline_tasks[launch["execution_id"]] = task

        return json_response(
            {
                "pipeline_id": pipeline_id,
                "execution_id": launch["execution_id"],
                "plan_id": plan.id,
                "correlation_id": launch["correlation_id"],
                "status": "executing",
                "agent_tasks": len(agent_tasks),
                "total_orchestration_nodes": len(orch_nodes),
                "runtime": "decision_plan",
            },
            202,
        )

    @handle_errors("debate to pipeline conversion")
    async def handle_debate_to_pipeline(
        self,
        debate_id: str,
        request_data: dict[str, Any],
    ) -> HandlerResult:
        """POST /api/v1/debates/{id}/to-pipeline

        Convert a completed debate into a pipeline by loading its argument graph
        and feeding it into from_debate().
        """
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        # Load debate's argument graph from store
        cartographer_data = None
        try:
            from aragora.server.handlers.utils.stores import get_debate_store

            debate = get_debate_store().get(debate_id)
            if debate:
                cartographer_data = debate.get("argument_graph", {})
        except (ImportError, RuntimeError, TypeError):
            pass

        if not cartographer_data:
            # Fallback: try loading from argument cartographer
            try:
                from aragora.visualization.argument_cartographer import ArgumentCartographer

                carto = ArgumentCartographer()
                cartographer_data = carto.get_graph(debate_id)
            except (ImportError, RuntimeError, TypeError, AttributeError):
                pass

        if not cartographer_data:
            return error_response(f"Debate {debate_id} argument graph not found", 404)

        use_universal = request_data.get("use_universal", False)
        auto_advance = request_data.get("auto_advance", True)

        pipeline = IdeaToExecutionPipeline(use_universal=use_universal)
        result = pipeline.from_debate(
            cartographer_data,
            auto_advance=auto_advance,
        )

        result_dict = result.to_dict()
        _get_store().save(result.pipeline_id, result_dict)
        _pipeline_objects[result.pipeline_id] = result
        _persist_pipeline_to_km(result)

        return json_response(
            {
                "pipeline_id": result.pipeline_id,
                "source_debate_id": debate_id,
                "stage_status": result.stage_status,
                "result": result_dict,
            },
            201,
        )
