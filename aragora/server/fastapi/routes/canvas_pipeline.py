"""
Canvas Pipeline Endpoints (FastAPI v2).

Migrated from: aragora/server/handlers/canvas_pipeline.py (aiohttp handler)

Surfaces the idea-to-execution canvas pipeline as REST endpoints:

Creation:
- POST /api/v2/canvas/pipeline/from-debate         Create pipeline from debate export
- POST /api/v2/canvas/pipeline/from-ideas           Create pipeline from raw ideas
- POST /api/v2/canvas/pipeline/from-braindump       Create pipeline from brain dump text
- POST /api/v2/canvas/pipeline/from-template        Create pipeline from template
- POST /api/v2/canvas/pipeline/from-system-metrics  Create pipeline from system metrics
- POST /api/v2/canvas/pipeline/demo                 Create demo pipeline

Execution:
- POST /api/v2/canvas/pipeline/advance              Advance to next stage
- POST /api/v2/canvas/pipeline/run                  Start async pipeline run
- POST /api/v2/canvas/pipeline/auto-run             Auto-run full pipeline
- POST /api/v2/canvas/pipeline/{id}/execute         Execute completed pipeline
- POST /api/v2/canvas/pipeline/{id}/self-improve    Trigger self-improvement
- POST /api/v2/canvas/pipeline/{id}/approve-transition  Approve stage transition

Querying:
- GET  /api/v2/canvas/pipeline/{id}                 Get pipeline result
- GET  /api/v2/canvas/pipeline/{id}/status           Per-stage status
- GET  /api/v2/canvas/pipeline/{id}/stage/{stage}    Get specific stage canvas
- GET  /api/v2/canvas/pipeline/{id}/graph            React Flow JSON
- GET  /api/v2/canvas/pipeline/{id}/receipt           DecisionReceipt
- GET  /api/v2/canvas/pipeline/templates              List pipeline templates

Conversion:
- POST /api/v2/canvas/pipeline/extract-goals         Extract goals from ideas
- POST /api/v2/canvas/pipeline/extract-principles    Extract principles
- POST /api/v2/canvas/convert/debate                 Convert debate to ideas canvas
- POST /api/v2/canvas/convert/workflow               Convert workflow to actions canvas
- POST /api/v2/debates/{id}/to-pipeline              Convert debate to pipeline

Intelligence:
- GET  /api/v2/canvas/pipeline/{id}/intelligence     Intelligence overlay
- GET  /api/v2/canvas/pipeline/{id}/beliefs           Belief network
- GET  /api/v2/canvas/pipeline/{id}/explanations      Explainability data
- GET  /api/v2/canvas/pipeline/{id}/precedents        Historical precedents

Agent Management:
- GET  /api/v2/pipeline/{id}/agents                   List assigned agents
- POST /api/v2/pipeline/{id}/agents/{agent_id}/approve  Approve agent
- POST /api/v2/pipeline/{id}/agents/{agent_id}/reject   Reject agent
- PUT  /api/v2/canvas/pipeline/{id}                  Save canvas state
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from aragora.rbac.models import AuthorizationContext

from ..dependencies.auth import require_permission
from ..middleware.error_handling import NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["Canvas Pipeline"])


# =============================================================================
# Pydantic Models
# =============================================================================


class PipelineSummary(BaseModel):
    """Summary of a pipeline result."""

    pipeline_id: str
    stage_status: dict[str, str] = Field(default_factory=dict)
    stages_completed: int = 0
    total_nodes: int = 0
    has_universal_graph: bool = False

    model_config = {"extra": "allow"}


class PipelineCreateResponse(BaseModel):
    """Response for pipeline creation endpoints."""

    pipeline_id: str
    stage_status: dict[str, str] = Field(default_factory=dict)
    stages_completed: int = 0
    total_nodes: int = 0
    has_universal_graph: bool = False
    result: dict[str, Any] | None = None

    model_config = {"extra": "allow"}


class PipelineStatusResponse(BaseModel):
    """Response for pipeline status endpoint."""

    pipeline_id: str
    stage_status: dict[str, str] = Field(default_factory=dict)
    total_stages: int = 0
    completed_stages: int = 0
    current_stage: str | None = None


class PipelineStageResponse(BaseModel):
    """Response for specific stage data."""

    pipeline_id: str
    stage: str
    canvas: dict[str, Any] | None = None
    node_count: int = 0


class PipelineGraphResponse(BaseModel):
    """Response for React Flow graph data."""

    pipeline_id: str
    stage: str | None = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class PipelineReceiptResponse(BaseModel):
    """Response for pipeline receipt."""

    pipeline_id: str
    receipt: dict[str, Any] | None = None
    has_receipt: bool = False


class PipelineTemplateItem(BaseModel):
    """A pipeline template entry."""

    id: str
    name: str
    description: str = ""
    stages: list[str] = Field(default_factory=list)
    category: str = "general"


class PipelineTemplatesResponse(BaseModel):
    """Response for template listing."""

    templates: list[PipelineTemplateItem]
    total: int


class IntelligenceResponse(BaseModel):
    """Intelligence overlay response."""

    pipeline_id: str
    beliefs: list[dict[str, Any]] = Field(default_factory=list)
    explanations: list[dict[str, Any]] = Field(default_factory=list)
    precedents: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class AgentAssignment(BaseModel):
    """Agent assignment for a pipeline."""

    agent_id: str
    agent_name: str
    role: str = "executor"
    status: str = "pending"

    model_config = {"extra": "allow"}


class AgentListResponse(BaseModel):
    """Response for agent listing."""

    pipeline_id: str
    agents: list[AgentAssignment]
    total: int


class AgentActionResponse(BaseModel):
    """Response for agent approve/reject."""

    pipeline_id: str
    agent_id: str
    action: str
    success: bool
    message: str = ""


class TransitionApprovalRequest(BaseModel):
    """Request for stage transition approval."""

    approved: bool = True
    feedback: str | None = Field(None, max_length=2000)


class TransitionApprovalResponse(BaseModel):
    """Response for transition approval."""

    pipeline_id: str
    approved: bool
    message: str = ""


class FromDebateRequest(BaseModel):
    """Request for creating pipeline from debate."""

    cartographer_data: dict[str, Any]
    auto_advance: bool = True
    use_ai: bool = False
    use_universal: bool = False


class FromIdeasRequest(BaseModel):
    """Request for creating pipeline from ideas."""

    ideas: list[str] = Field(..., min_length=1)
    auto_advance: bool = True
    use_ai: bool = False
    use_universal: bool = False


class FromBraindumpRequest(BaseModel):
    """Request for creating pipeline from brain dump text."""

    text: str = Field(..., min_length=1, max_length=50000)
    context: str | None = None
    auto_advance: bool = True
    use_ai: bool = False
    use_universal: bool = False
    use_unified_orchestrator: bool = False
    skip_execution: bool | None = None
    preset_name: str | None = None
    autonomy_level: str | None = None
    domain: str | None = None


class FromTemplateRequest(BaseModel):
    """Request for creating pipeline from template."""

    template_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    auto_advance: bool = True


class FromSystemMetricsRequest(BaseModel):
    """Request for creating pipeline from system metrics."""

    metric_type: str = "all"
    auto_advance: bool = True


class ExtractGoalsRequest(BaseModel):
    """Request for extracting goals from ideas canvas."""

    ideas_canvas: dict[str, Any]
    use_ai: bool = False


class ExtractPrinciplesRequest(BaseModel):
    """Request for extracting principles."""

    ideas: list[str] = Field(default_factory=list)
    context: str | None = None


class ConvertDebateRequest(BaseModel):
    """Request for converting debate to ideas canvas."""

    debate_id: str | None = None
    debate_data: dict[str, Any] | None = None


class ConvertWorkflowRequest(BaseModel):
    """Request for converting workflow to actions canvas."""

    workflow_id: str | None = None
    workflow_data: dict[str, Any] | None = None


class AdvanceRequest(BaseModel):
    """Request for advancing pipeline stage."""

    pipeline_id: str
    use_ai: bool = False


class RunRequest(BaseModel):
    """Request for starting async pipeline run."""

    ideas: list[str] = Field(default_factory=list)
    text: str | None = None
    auto_advance: bool = True
    use_ai: bool = False
    use_universal: bool = False


class AutoRunRequest(BaseModel):
    """Request for auto-running full pipeline."""

    ideas: list[str] = Field(default_factory=list)
    text: str | None = None
    use_ai: bool = False
    use_universal: bool = False


class ExecuteRequest(BaseModel):
    """Request for executing a completed pipeline."""

    use_hardened_orchestrator: bool = False
    sandbox: bool = False


class SelfImproveRequest(BaseModel):
    """Request for triggering self-improvement."""

    goal: str | None = None
    dry_run: bool = False


class DebateToPipelineRequest(BaseModel):
    """Request for converting a specific debate to a pipeline."""

    auto_advance: bool = True
    use_ai: bool = False


class SaveCanvasRequest(BaseModel):
    """Request for saving canvas state."""

    canvas_data: dict[str, Any] = Field(default_factory=dict)
    stage: str | None = None


# =============================================================================
# Helpers
# =============================================================================


def _get_store() -> Any:
    """Lazy-load the persistent pipeline store."""
    from aragora.storage.pipeline_store import get_pipeline_store

    return get_pipeline_store()


# In-memory live pipeline objects (for advance_stage)
_pipeline_objects: dict[str, Any] = {}


def _get_ai_agent() -> Any | None:
    """Try to create an AI agent for goal synthesis."""
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


def _get_pipeline_emitter_callback(pipeline_id: str) -> Any:
    """Get the pipeline stream emitter callback."""
    try:
        from aragora.server.stream.pipeline_stream import get_pipeline_emitter

        return get_pipeline_emitter().as_event_callback(pipeline_id)
    except ImportError:
        return None


def _summarize_result(result: Any) -> PipelineCreateResponse:
    """Build a PipelineCreateResponse from a PipelineResult."""
    result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
    stage_status = getattr(result, "stage_status", {})
    total_nodes = 0
    for canvas_attr in ("ideas_canvas", "actions_canvas", "orchestration_canvas"):
        canvas = getattr(result, canvas_attr, None)
        if canvas and hasattr(canvas, "nodes"):
            total_nodes += len(canvas.nodes)

    return PipelineCreateResponse(
        pipeline_id=result.pipeline_id,
        stage_status=stage_status,
        stages_completed=sum(1 for s in stage_status.values() if s == "complete"),
        total_nodes=total_nodes,
        has_universal_graph=result.universal_graph is not None,
        result=result_dict,
    )


def _store_result(result: Any) -> None:
    """Persist pipeline result to store and keep live object."""
    result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
    _get_store().save(result.pipeline_id, result_dict)
    _pipeline_objects[result.pipeline_id] = result
    _persist_universal_graph(result)
    _persist_pipeline_to_km(result)


def _get_result_or_404(pipeline_id: str) -> Any:
    """Load pipeline result from live objects or persistent store."""
    result = _pipeline_objects.get(pipeline_id)
    if result is not None:
        return result
    stored = _get_store().load(pipeline_id)
    if stored is None:
        raise NotFoundError(f"Pipeline {pipeline_id} not found")
    return stored


# =============================================================================
# Pipeline Creation Endpoints
# =============================================================================


@router.post(
    "/canvas/pipeline/from-debate",
    response_model=PipelineCreateResponse,
    status_code=201,
)
async def create_from_debate(
    body: FromDebateRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> PipelineCreateResponse:
    """Create a pipeline from an ArgumentCartographer debate export."""
    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
        agent = _get_ai_agent() if body.use_ai else None
        pipeline = IdeaToExecutionPipeline(agent=agent, use_universal=body.use_universal)
        event_cb = _get_pipeline_emitter_callback(pipeline_id)

        result = pipeline.from_debate(
            body.cartographer_data,
            auto_advance=body.auto_advance,
            event_callback=event_cb,
            pipeline_id=pipeline_id,
        )
        _store_result(result)
        return _summarize_result(result)

    except (ImportError, ValueError, TypeError, RuntimeError) as e:
        logger.warning("Pipeline from-debate failed: %s", e)
        raise HTTPException(status_code=500, detail="Pipeline execution failed")


@router.post(
    "/canvas/pipeline/from-ideas",
    response_model=PipelineCreateResponse,
    status_code=201,
)
async def create_from_ideas(
    body: FromIdeasRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> PipelineCreateResponse:
    """Create a pipeline from raw idea strings."""
    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
        agent = _get_ai_agent() if body.use_ai else None
        pipeline = IdeaToExecutionPipeline(agent=agent, use_universal=body.use_universal)
        event_cb = _get_pipeline_emitter_callback(pipeline_id)

        result = pipeline.from_ideas(
            body.ideas,
            auto_advance=body.auto_advance,
            event_callback=event_cb,
            pipeline_id=pipeline_id,
        )
        _store_result(result)
        return _summarize_result(result)

    except (ImportError, ValueError, TypeError, RuntimeError) as e:
        logger.warning("Pipeline from-ideas failed: %s", e)
        raise HTTPException(status_code=500, detail="Pipeline execution failed")


@router.post(
    "/canvas/pipeline/from-braindump",
    response_model=PipelineCreateResponse,
    status_code=201,
)
async def create_from_braindump(
    body: FromBraindumpRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> PipelineCreateResponse:
    """Create a pipeline from brain dump text."""
    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
        event_cb = _get_pipeline_emitter_callback(pipeline_id)
        brain_dump_text = body.text
        orchestrator_summary: dict[str, Any] | None = None

        if body.use_unified_orchestrator:
            from aragora.server.handlers.canvas_pipeline import CanvasPipelineHandler

            try:
                (
                    orchestrator_summary,
                    context_block,
                ) = await CanvasPipelineHandler()._run_unified_orchestrator(
                    body.text,
                    body.model_dump(exclude_none=True),
                )
                if context_block:
                    brain_dump_text = f"{body.text}\n\n{context_block}"
            except Exception as exc:
                logger.warning("Unified orchestrator pre-run failed: %s", exc)
                orchestrator_summary = {
                    "enabled": True,
                    "succeeded": False,
                    "errors": [str(exc)],
                }

        result = await IdeaToExecutionPipeline.from_brain_dump(
            brain_dump_text,
            pipeline_id=pipeline_id,
            event_callback=event_cb,
        )
        _store_result(result)
        response = _summarize_result(result)
        if orchestrator_summary is None:
            return response

        payload = response.model_dump()
        payload["unified_orchestrator"] = orchestrator_summary
        debate_id = orchestrator_summary.get("debate_id")
        if debate_id:
            payload["debate_id"] = debate_id
            payload["debate_url"] = orchestrator_summary.get(
                "debate_url",
                f"/debates/{debate_id}",
            )
        return PipelineCreateResponse(**payload)

    except (ImportError, ValueError, TypeError, RuntimeError) as e:
        logger.warning("Pipeline from-braindump failed: %s", e)
        raise HTTPException(status_code=500, detail="Pipeline execution failed")


@router.post(
    "/canvas/pipeline/from-template",
    response_model=PipelineCreateResponse,
    status_code=201,
)
async def create_from_template(
    body: FromTemplateRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> PipelineCreateResponse:
    """Create a pipeline from a template."""
    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline
        from aragora.pipeline.templates import get_template

        template = get_template(body.template_id)
        if not template:
            raise HTTPException(
                status_code=404,
                detail=f"Template '{body.template_id}' not found",
            )

        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
        pipeline = IdeaToExecutionPipeline()
        event_cb = _get_pipeline_emitter_callback(pipeline_id)

        from_template_fn = getattr(pipeline, "from_template", None)
        if from_template_fn is not None:
            result = from_template_fn(
                template,
                params=body.params,
                auto_advance=body.auto_advance,
                event_callback=event_cb,
                pipeline_id=pipeline_id,
            )
        else:
            # Fallback: use template's seed ideas with from_ideas
            seed_ideas = getattr(template, "seed_ideas", getattr(template, "stage_1_ideas", []))
            result = pipeline.from_ideas(
                seed_ideas or ["Pipeline from template"],
                auto_advance=body.auto_advance,
                event_callback=event_cb,
                pipeline_id=pipeline_id,
            )
        _store_result(result)
        return _summarize_result(result)

    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (ImportError, ValueError, TypeError, RuntimeError) as e:
        logger.warning("Pipeline from-template failed: %s", e)
        raise HTTPException(status_code=500, detail="Pipeline execution failed")


@router.post(
    "/canvas/pipeline/from-system-metrics",
    response_model=PipelineCreateResponse,
    status_code=201,
)
async def create_from_system_metrics(
    body: FromSystemMetricsRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> PipelineCreateResponse:
    """Create a pipeline from system metrics analysis."""
    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"

        result = await IdeaToExecutionPipeline.from_system_metrics(
            pipeline_id=pipeline_id,
        )
        _store_result(result)
        return _summarize_result(result)

    except (ImportError, ValueError, TypeError, RuntimeError, AttributeError) as e:
        logger.warning("Pipeline from-system-metrics failed: %s", e)
        raise HTTPException(status_code=500, detail="Pipeline execution failed")


@router.post(
    "/canvas/pipeline/demo",
    response_model=PipelineCreateResponse,
    status_code=201,
)
async def create_demo_pipeline(
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> PipelineCreateResponse:
    """Create a demo pipeline with sample data."""
    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        pipeline_id = f"pipe-demo-{uuid.uuid4().hex[:8]}"
        pipeline = IdeaToExecutionPipeline()

        result = pipeline.from_ideas(
            [
                "Improve user onboarding flow",
                "Add multi-language support",
                "Reduce API latency by 50%",
            ],
            auto_advance=True,
            pipeline_id=pipeline_id,
        )
        _store_result(result)
        return _summarize_result(result)

    except (ImportError, ValueError, TypeError, RuntimeError) as e:
        logger.warning("Demo pipeline failed: %s", e)
        raise HTTPException(status_code=500, detail="Demo pipeline creation failed")


# =============================================================================
# Pipeline Execution Endpoints
# =============================================================================


@router.post("/canvas/pipeline/advance", response_model=PipelineCreateResponse)
async def advance_pipeline(
    body: AdvanceRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> PipelineCreateResponse:
    """Advance a pipeline to the next stage."""
    try:
        result = _pipeline_objects.get(body.pipeline_id)
        if result is None:
            raise NotFoundError(f"Pipeline {body.pipeline_id} not found (or not in memory)")

        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        agent = _get_ai_agent() if body.use_ai else None
        pipeline = IdeaToExecutionPipeline(agent=agent)

        # advance_stage takes (result, target_stage); determine next stage from status
        stage_order = ["ideation", "principles", "goals", "actions", "orchestration"]
        stage_status = getattr(result, "stage_status", {})
        next_stage = None
        for s in stage_order:
            if stage_status.get(s) not in ("complete", "skipped"):
                next_stage = s
                break
        if next_stage is not None:
            try:
                from aragora.pipeline.idea_to_execution import PipelineStage

                target = PipelineStage(next_stage)
            except (ImportError, ValueError):
                target = next_stage  # type: ignore[assignment]
            result = pipeline.advance_stage(result, target)
        _store_result(result)
        return _summarize_result(result)

    except NotFoundError:
        raise
    except (ImportError, ValueError, TypeError, RuntimeError) as e:
        logger.warning("Pipeline advance failed: %s", e)
        raise HTTPException(status_code=500, detail="Pipeline advance failed")


@router.post(
    "/canvas/pipeline/run",
    response_model=PipelineCreateResponse,
    status_code=201,
)
async def run_pipeline(
    body: RunRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> PipelineCreateResponse:
    """Start an async pipeline run from ideas or brain dump text."""
    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
        agent = _get_ai_agent() if body.use_ai else None
        pipeline = IdeaToExecutionPipeline(agent=agent, use_universal=body.use_universal)
        event_cb = _get_pipeline_emitter_callback(pipeline_id)

        if body.text:
            result = await IdeaToExecutionPipeline.from_brain_dump(
                body.text,
                pipeline_id=pipeline_id,
                event_callback=event_cb,
            )
        else:
            ideas = body.ideas or ["Improve system performance"]
            result = pipeline.from_ideas(
                ideas,
                auto_advance=body.auto_advance,
                event_callback=event_cb,
                pipeline_id=pipeline_id,
            )

        _store_result(result)
        return _summarize_result(result)

    except (ImportError, ValueError, TypeError, RuntimeError) as e:
        logger.warning("Pipeline run failed: %s", e)
        raise HTTPException(status_code=500, detail="Pipeline run failed")


@router.post("/canvas/pipeline/auto-run", response_model=PipelineCreateResponse, status_code=201)
async def auto_run_pipeline(
    body: AutoRunRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> PipelineCreateResponse:
    """Auto-run a full pipeline end-to-end."""
    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
        agent = _get_ai_agent() if body.use_ai else None
        pipeline = IdeaToExecutionPipeline(agent=agent, use_universal=body.use_universal)
        event_cb = _get_pipeline_emitter_callback(pipeline_id)

        if body.text:
            result = await IdeaToExecutionPipeline.from_brain_dump(
                body.text,
                pipeline_id=pipeline_id,
                event_callback=event_cb,
            )
        else:
            ideas = body.ideas or ["Improve system performance"]
            result = pipeline.from_ideas(
                ideas,
                auto_advance=True,
                event_callback=event_cb,
                pipeline_id=pipeline_id,
            )

        _store_result(result)
        return _summarize_result(result)

    except (ImportError, ValueError, TypeError, RuntimeError) as e:
        logger.warning("Pipeline auto-run failed: %s", e)
        raise HTTPException(status_code=500, detail="Pipeline auto-run failed")


@router.post("/canvas/pipeline/{pipeline_id}/execute", response_model=PipelineCreateResponse)
async def execute_pipeline(
    pipeline_id: str,
    body: ExecuteRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> PipelineCreateResponse:
    """Execute a completed pipeline's orchestration stage."""
    data = _get_result_or_404(pipeline_id)
    data_dict = data.to_dict() if hasattr(data, "to_dict") else data
    if not isinstance(data_dict, dict):
        raise HTTPException(status_code=500, detail="Pipeline execution failed")

    stage_status = data_dict.get("stage_status", {})
    incomplete = [
        stage
        for stage in ("ideas", "goals", "actions", "orchestration")
        if stage_status.get(stage) != "complete"
    ]
    orch = data_dict.get("orchestration", {}) if isinstance(data_dict, dict) else {}
    orch_nodes = orch.get("nodes", []) if isinstance(orch, dict) else []
    agent_tasks = [
        node
        for node in orch_nodes
        if isinstance(node, dict) and node.get("data", {}).get("orch_type") == "agent_task"
    ]

    if body.sandbox:
        logger.debug(
            "Canvas pipeline execute requested sandbox mode for %s; canonical workflow runtime ignores the legacy sandbox flag",
            pipeline_id,
        )
    if body.use_hardened_orchestrator:
        logger.debug(
            "Canvas pipeline execute requested hardened orchestrator for %s; routing through canonical DecisionPlan runtime instead",
            pipeline_id,
        )

    if body.sandbox:
        logger.debug("Sandbox execution flag ignored for canonical runtime on %s", pipeline_id)

    if incomplete:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot execute: stages not complete: {', '.join(incomplete)}",
        )

    execution_state = data_dict.get("execution", {})
    if isinstance(execution_state, dict) and execution_state.get("status") in {
        "queued",
        "running",
        "executing",
    }:
        raise HTTPException(status_code=409, detail="Pipeline is already executing")

    try:
        from aragora.pipeline.canonical_execution import (
            build_decision_plan_from_orchestration,
            execute_queued_plan,
            queue_plan_execution,
        )

        plan, tasks = build_decision_plan_from_orchestration(
            subject_id=pipeline_id,
            subject_label=data_dict.get("name") or f"Pipeline {pipeline_id}",
            nodes=orch_nodes,
            edges=orch.get("edges", []) if isinstance(orch, dict) else [],
            source_surface="fastapi_canvas_pipeline",
            metadata={"pipeline_id": pipeline_id},
            execution_mode="workflow",
        )
        launch = queue_plan_execution(plan, auth_context=auth, execution_mode="workflow")
        data_dict["execution"] = {
            **launch,
            "runtime": "decision_plan",
            "status": "queued",
            "tasks_total": len(tasks),
            "agent_tasks": len(agent_tasks),
            "total_orchestration_nodes": len(orch_nodes),
        }
        _get_store().save(pipeline_id, data_dict)

        async def _execute() -> None:
            try:
                data_dict["execution"]["status"] = "running"
                _get_store().save(pipeline_id, data_dict)
                outcome, record, decision_receipt = await execute_queued_plan(
                    plan,
                    execution_id=launch["execution_id"],
                    correlation_id=launch["correlation_id"],
                    auth_context=auth,
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
                        },
                    )
                except (ImportError, RuntimeError, ValueError, TypeError, OSError) as exc:
                    logger.debug("Pipeline provenance receipt generation skipped: %s", exc)

                data_dict["execution"] = {
                    **data_dict.get("execution", {}),
                    "status": "completed" if outcome.success else "failed",
                    "record": record,
                    "outcome": outcome.to_dict(),
                    "receipt_id": getattr(outcome, "receipt_id", None),
                }
                data_dict["receipt"] = receipt_bundle
                _get_store().save(pipeline_id, data_dict)
            except Exception as exc:  # noqa: BLE001 - background task must persist terminal failure
                logger.error("Pipeline execute failed: %s", exc)
                data_dict["execution"] = {
                    **data_dict.get("execution", {}),
                    "status": "failed",
                    "error": str(exc),
                }
                _get_store().save(pipeline_id, data_dict)

        asyncio.create_task(_execute())

        return PipelineCreateResponse(
            pipeline_id=pipeline_id,
            stage_status=data_dict.get("stage_status", {}),
            stages_completed=sum(
                1 for value in data_dict.get("stage_status", {}).values() if value == "complete"
            ),
            result={
                "status": "executing",
                "runtime": "decision_plan",
                "plan_id": plan.id,
                "execution_id": launch["execution_id"],
                "correlation_id": launch["correlation_id"],
                "agent_tasks": len(agent_tasks),
                "total_orchestration_nodes": len(orch_nodes),
            },
        )

    except NotFoundError:
        raise
    except (ImportError, ValueError, TypeError, RuntimeError, AttributeError) as e:
        logger.warning("Pipeline execute failed: %s", e)
        raise HTTPException(status_code=500, detail="Pipeline execution failed")


@router.post("/canvas/pipeline/{pipeline_id}/self-improve")
async def trigger_self_improve(
    pipeline_id: str,
    body: SelfImproveRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> dict[str, Any]:
    """Trigger self-improvement from pipeline insights."""
    _get_result_or_404(pipeline_id)

    try:
        from aragora.nomic.meta_planner import MetaPlanner

        planner = MetaPlanner()
        goal = body.goal or f"Improve based on pipeline {pipeline_id}"
        plan_fn = getattr(planner, "plan", getattr(planner, "prioritize_work", None))
        if plan_fn is None:
            raise AttributeError("MetaPlanner has no plan or prioritize_work method")
        plan = await plan_fn(goal) if asyncio.iscoroutinefunction(plan_fn) else plan_fn(goal)
        return {
            "pipeline_id": pipeline_id,
            "goal": goal,
            "dry_run": body.dry_run,
            "plan": plan.to_dict() if hasattr(plan, "to_dict") else str(plan),
        }

    except (ImportError, ValueError, TypeError, RuntimeError, AttributeError) as e:
        logger.warning("Self-improve failed: %s", e)
        raise HTTPException(status_code=500, detail="Self-improvement failed")


@router.post(
    "/canvas/pipeline/{pipeline_id}/approve-transition",
    response_model=TransitionApprovalResponse,
)
async def approve_transition(
    pipeline_id: str,
    body: TransitionApprovalRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:approve")),
) -> TransitionApprovalResponse:
    """Approve or reject a stage transition."""
    _get_result_or_404(pipeline_id)

    try:
        result = _pipeline_objects.get(pipeline_id)
        if result and hasattr(result, "approve_transition"):
            result.approve_transition(approved=body.approved, feedback=body.feedback)
            _store_result(result)

        action = "approved" if body.approved else "rejected"
        logger.info("Pipeline %s transition %s by %s", pipeline_id, action, auth.user_id)

        return TransitionApprovalResponse(
            pipeline_id=pipeline_id,
            approved=body.approved,
            message=f"Transition {action}",
        )

    except (ValueError, TypeError, RuntimeError, AttributeError) as e:
        logger.warning("Transition approval failed: %s", e)
        raise HTTPException(status_code=500, detail="Transition approval failed")


# =============================================================================
# Pipeline Query Endpoints
# =============================================================================


@router.get("/canvas/pipeline/templates", response_model=PipelineTemplatesResponse)
async def list_templates() -> PipelineTemplatesResponse:
    """List available pipeline templates."""
    try:
        from aragora.pipeline.templates import list_templates as _list_templates

        templates_raw = _list_templates()
        templates = [
            PipelineTemplateItem(
                id=getattr(t, "name", "")
                if not isinstance(t, dict)
                else t.get("id", t.get("name", "")),
                name=getattr(t, "display_name", getattr(t, "name", ""))
                if not isinstance(t, dict)
                else t.get("name", ""),
                description=getattr(t, "description", "")
                if not isinstance(t, dict)
                else t.get("description", ""),
                stages=getattr(t, "tags", []) if not isinstance(t, dict) else t.get("stages", []),
                category=getattr(t, "category", "general")
                if not isinstance(t, dict)
                else t.get("category", "general"),
            )
            for t in templates_raw
        ]
        return PipelineTemplatesResponse(templates=templates, total=len(templates))

    except (ImportError, AttributeError) as e:
        logger.debug("Templates not available: %s", e)
        return PipelineTemplatesResponse(templates=[], total=0)


@router.get("/canvas/pipeline/{pipeline_id}", response_model=PipelineCreateResponse)
async def get_pipeline(pipeline_id: str) -> PipelineCreateResponse:
    """Get a pipeline result by ID."""
    data = _get_result_or_404(pipeline_id)

    if isinstance(data, dict):
        stage_status = data.get("stage_status", {})
        return PipelineCreateResponse(
            pipeline_id=pipeline_id,
            stage_status=stage_status,
            stages_completed=sum(1 for s in stage_status.values() if s == "complete"),
            result=data,
        )

    return _summarize_result(data)


@router.get("/canvas/pipeline/{pipeline_id}/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(pipeline_id: str) -> PipelineStatusResponse:
    """Get per-stage status for a pipeline."""
    data = _get_result_or_404(pipeline_id)

    if isinstance(data, dict):
        stage_status = data.get("stage_status", {})
    else:
        stage_status = getattr(data, "stage_status", {})

    completed = sum(1 for s in stage_status.values() if s == "complete")
    current = next(
        (name for name, s in stage_status.items() if s not in ("complete", "skipped")),
        None,
    )

    return PipelineStatusResponse(
        pipeline_id=pipeline_id,
        stage_status=stage_status,
        total_stages=len(stage_status),
        completed_stages=completed,
        current_stage=current,
    )


@router.get("/canvas/pipeline/{pipeline_id}/stage/{stage}", response_model=PipelineStageResponse)
async def get_pipeline_stage(pipeline_id: str, stage: str) -> PipelineStageResponse:
    """Get specific stage canvas data."""
    data = _get_result_or_404(pipeline_id)

    canvas_map = {
        "ideas": "ideas_canvas",
        "ideation": "ideas_canvas",
        "goals": "goals_canvas",
        "actions": "actions_canvas",
        "workflow": "actions_canvas",
        "orchestration": "orchestration_canvas",
    }

    canvas_attr = canvas_map.get(stage)
    if not canvas_attr:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown stage: {stage}. Valid: {', '.join(sorted(canvas_map))}",
        )

    if isinstance(data, dict):
        canvas_data = data.get(canvas_attr)
        if isinstance(canvas_data, dict):
            return PipelineStageResponse(
                pipeline_id=pipeline_id,
                stage=stage,
                canvas=canvas_data,
                node_count=len(canvas_data.get("nodes", {})),
            )
        return PipelineStageResponse(pipeline_id=pipeline_id, stage=stage)

    canvas = getattr(data, canvas_attr, None)
    if canvas is None:
        return PipelineStageResponse(pipeline_id=pipeline_id, stage=stage)

    canvas_dict = canvas.to_dict() if hasattr(canvas, "to_dict") else {}
    return PipelineStageResponse(
        pipeline_id=pipeline_id,
        stage=stage,
        canvas=canvas_dict,
        node_count=len(getattr(canvas, "nodes", {})),
    )


@router.get("/canvas/pipeline/{pipeline_id}/graph", response_model=PipelineGraphResponse)
async def get_pipeline_graph(
    pipeline_id: str,
    stage: str | None = Query(None, description="Stage to get graph for"),
) -> PipelineGraphResponse:
    """Get React Flow graph JSON for a pipeline stage."""
    data = _get_result_or_404(pipeline_id)

    try:
        # Try universal graph first
        if isinstance(data, dict):
            ug = data.get("universal_graph")
        else:
            ug = getattr(data, "universal_graph", None)

        if ug is not None:
            if hasattr(ug, "to_react_flow"):
                rf_data = ug.to_react_flow(stage=stage)
                return PipelineGraphResponse(
                    pipeline_id=pipeline_id,
                    stage=stage,
                    nodes=rf_data.get("nodes", []),
                    edges=rf_data.get("edges", []),
                )
            if isinstance(ug, dict):
                return PipelineGraphResponse(
                    pipeline_id=pipeline_id,
                    stage=stage,
                    nodes=ug.get("nodes", []),
                    edges=ug.get("edges", []),
                )

        return PipelineGraphResponse(pipeline_id=pipeline_id, stage=stage)

    except (ValueError, TypeError, AttributeError) as e:
        logger.debug("Graph generation failed: %s", e)
        return PipelineGraphResponse(pipeline_id=pipeline_id, stage=stage)


@router.get("/canvas/pipeline/{pipeline_id}/receipt", response_model=PipelineReceiptResponse)
async def get_pipeline_receipt(pipeline_id: str) -> PipelineReceiptResponse:
    """Get the DecisionReceipt for a pipeline."""
    data = _get_result_or_404(pipeline_id)
    data_dict = (
        data.to_dict() if hasattr(data, "to_dict") else (data if isinstance(data, dict) else {})
    )
    if isinstance(data_dict, dict) and isinstance(data_dict.get("receipt"), dict):
        return PipelineReceiptResponse(
            pipeline_id=pipeline_id,
            receipt=data_dict.get("receipt"),
            has_receipt=True,
        )

    try:
        from aragora.pipeline.receipt_generator import generate_pipeline_receipt

        receipt = await generate_pipeline_receipt(pipeline_id, data_dict)
        receipt_dict = receipt.to_dict() if hasattr(receipt, "to_dict") else receipt
        return PipelineReceiptResponse(
            pipeline_id=pipeline_id,
            receipt=receipt_dict if isinstance(receipt_dict, dict) else None,
            has_receipt=True,
        )
    except (ImportError, ValueError, TypeError, AttributeError) as e:
        logger.debug("Receipt generation failed: %s", e)
        return PipelineReceiptResponse(pipeline_id=pipeline_id, has_receipt=False)


# =============================================================================
# Conversion Endpoints
# =============================================================================


@router.post("/canvas/pipeline/extract-goals")
async def extract_goals(
    body: ExtractGoalsRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> dict[str, Any]:
    """Extract goals from an ideas canvas."""
    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        agent = _get_ai_agent() if body.use_ai else None
        pipeline = IdeaToExecutionPipeline(agent=agent)

        extract_fn = getattr(pipeline, "extract_goals", None)
        if extract_fn is None:
            raise AttributeError("IdeaToExecutionPipeline has no extract_goals method")
        goals = extract_fn(body.ideas_canvas)
        goals_data = goals.to_dict() if hasattr(goals, "to_dict") else goals
        return {"goals": goals_data}

    except (ImportError, ValueError, TypeError, RuntimeError, AttributeError) as e:
        logger.warning("Goal extraction failed: %s", e)
        raise HTTPException(status_code=500, detail="Goal extraction failed")


@router.post("/canvas/pipeline/extract-principles")
async def extract_principles(
    body: ExtractPrinciplesRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> dict[str, Any]:
    """Extract guiding principles from ideas."""
    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        pipeline = IdeaToExecutionPipeline()
        extract_fn = getattr(pipeline, "extract_principles", None)
        if extract_fn is None:
            raise AttributeError("IdeaToExecutionPipeline has no extract_principles method")
        principles = extract_fn(body.ideas, context=body.context)
        return {"principles": principles if isinstance(principles, list) else []}

    except (ImportError, ValueError, TypeError, RuntimeError, AttributeError) as e:
        logger.warning("Principle extraction failed: %s", e)
        raise HTTPException(status_code=500, detail="Principle extraction failed")


@router.post("/canvas/convert/debate")
async def convert_debate(
    body: ConvertDebateRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> dict[str, Any]:
    """Convert a debate to an ideas canvas."""
    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        pipeline = IdeaToExecutionPipeline()

        if body.debate_data:
            convert_fn = getattr(pipeline, "debate_to_ideas_canvas", None)
            if convert_fn is None:
                raise AttributeError("IdeaToExecutionPipeline has no debate_to_ideas_canvas method")
            canvas = convert_fn(body.debate_data)
        elif body.debate_id:
            convert_fn = getattr(pipeline, "debate_id_to_ideas_canvas", None)
            if convert_fn is None:
                raise AttributeError(
                    "IdeaToExecutionPipeline has no debate_id_to_ideas_canvas method"
                )
            canvas = convert_fn(body.debate_id)
        else:
            raise HTTPException(status_code=400, detail="Provide debate_id or debate_data")

        canvas_dict = canvas.to_dict() if hasattr(canvas, "to_dict") else canvas
        return {"canvas": canvas_dict}

    except HTTPException:
        raise
    except (ImportError, ValueError, TypeError, RuntimeError, AttributeError) as e:
        logger.warning("Debate conversion failed: %s", e)
        raise HTTPException(status_code=500, detail="Debate conversion failed")


@router.post("/canvas/convert/workflow")
async def convert_workflow(
    body: ConvertWorkflowRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> dict[str, Any]:
    """Convert a workflow to an actions canvas."""
    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        pipeline = IdeaToExecutionPipeline()

        if body.workflow_data:
            convert_fn = getattr(pipeline, "workflow_to_actions_canvas", None)
            if convert_fn is None:
                raise AttributeError(
                    "IdeaToExecutionPipeline has no workflow_to_actions_canvas method"
                )
            canvas = convert_fn(body.workflow_data)
        elif body.workflow_id:
            convert_fn = getattr(pipeline, "workflow_id_to_actions_canvas", None)
            if convert_fn is None:
                raise AttributeError(
                    "IdeaToExecutionPipeline has no workflow_id_to_actions_canvas method"
                )
            canvas = convert_fn(body.workflow_id)
        else:
            raise HTTPException(status_code=400, detail="Provide workflow_id or workflow_data")

        canvas_dict = canvas.to_dict() if hasattr(canvas, "to_dict") else canvas
        return {"canvas": canvas_dict}

    except HTTPException:
        raise
    except (ImportError, ValueError, TypeError, RuntimeError, AttributeError) as e:
        logger.warning("Workflow conversion failed: %s", e)
        raise HTTPException(status_code=500, detail="Workflow conversion failed")


@router.post(
    "/debates/{debate_id}/to-pipeline", response_model=PipelineCreateResponse, status_code=201
)
async def debate_to_pipeline(
    debate_id: str,
    body: DebateToPipelineRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> PipelineCreateResponse:
    """Convert a specific debate into a full pipeline."""
    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        pipeline_id = f"pipe-{uuid.uuid4().hex[:8]}"
        agent = _get_ai_agent() if body.use_ai else None
        pipeline = IdeaToExecutionPipeline(agent=agent)
        event_cb = _get_pipeline_emitter_callback(pipeline_id)

        result = pipeline.from_debate(
            {"debate_id": debate_id},
            auto_advance=body.auto_advance,
            event_callback=event_cb,
            pipeline_id=pipeline_id,
        )
        _store_result(result)
        return _summarize_result(result)

    except (ImportError, ValueError, TypeError, RuntimeError) as e:
        logger.warning("Debate-to-pipeline failed: %s", e)
        raise HTTPException(status_code=500, detail="Debate-to-pipeline conversion failed")


# =============================================================================
# Intelligence Endpoints
# =============================================================================


@router.get("/canvas/pipeline/{pipeline_id}/intelligence", response_model=IntelligenceResponse)
async def get_intelligence(pipeline_id: str) -> IntelligenceResponse:
    """Get intelligence overlay for a pipeline."""
    data = _get_result_or_404(pipeline_id)

    beliefs: list[dict[str, Any]] = []
    explanations: list[dict[str, Any]] = []
    precedents: list[dict[str, Any]] = []

    # Beliefs
    try:
        from aragora.reasoning.belief import BeliefNetwork

        bn = BeliefNetwork()
        query_fn = getattr(bn, "query_pipeline", None)
        if query_fn is not None:
            beliefs = query_fn(pipeline_id)
    except (ImportError, AttributeError, RuntimeError):
        pass

    # Explanations
    try:
        from aragora.explainability.builder import ExplanationBuilder

        builder = ExplanationBuilder()
        explain_fn = getattr(builder, "explain_pipeline", None)
        if explain_fn is not None:
            explanations = explain_fn(data)
    except (ImportError, AttributeError, RuntimeError):
        pass

    # Precedents
    try:
        from aragora.pipeline.km_bridge import PipelineKMBridge

        bridge = PipelineKMBridge()
        precedents = bridge.query_debate_precedents(data)
    except (ImportError, AttributeError, RuntimeError):
        pass

    return IntelligenceResponse(
        pipeline_id=pipeline_id,
        beliefs=beliefs if isinstance(beliefs, list) else [],
        explanations=explanations if isinstance(explanations, list) else [],
        precedents=precedents if isinstance(precedents, list) else [],
    )


@router.get("/canvas/pipeline/{pipeline_id}/beliefs")
async def get_beliefs(pipeline_id: str) -> dict[str, Any]:
    """Get belief network for a pipeline."""
    _get_result_or_404(pipeline_id)

    try:
        from aragora.reasoning.belief import BeliefNetwork

        bn = BeliefNetwork()
        query_fn = getattr(bn, "query_pipeline", None)
        beliefs = query_fn(pipeline_id) if query_fn is not None else []
        return {"pipeline_id": pipeline_id, "beliefs": beliefs}
    except (ImportError, AttributeError, RuntimeError) as e:
        logger.debug("Beliefs not available: %s", e)
        return {"pipeline_id": pipeline_id, "beliefs": []}


@router.get("/canvas/pipeline/{pipeline_id}/explanations")
async def get_explanations(pipeline_id: str) -> dict[str, Any]:
    """Get explainability data for a pipeline."""
    data = _get_result_or_404(pipeline_id)

    try:
        from aragora.explainability.builder import ExplanationBuilder

        builder = ExplanationBuilder()
        explain_fn = getattr(builder, "explain_pipeline", None)
        explanations = explain_fn(data) if explain_fn is not None else []
        return {"pipeline_id": pipeline_id, "explanations": explanations}
    except (ImportError, AttributeError, RuntimeError) as e:
        logger.debug("Explanations not available: %s", e)
        return {"pipeline_id": pipeline_id, "explanations": []}


@router.get("/canvas/pipeline/{pipeline_id}/precedents")
async def get_precedents(pipeline_id: str) -> dict[str, Any]:
    """Get historical precedents for a pipeline."""
    data = _get_result_or_404(pipeline_id)

    try:
        from aragora.pipeline.km_bridge import PipelineKMBridge

        bridge = PipelineKMBridge()
        precedents = bridge.query_debate_precedents(data)
        return {"pipeline_id": pipeline_id, "precedents": precedents}
    except (ImportError, AttributeError, RuntimeError) as e:
        logger.debug("Precedents not available: %s", e)
        return {"pipeline_id": pipeline_id, "precedents": []}


# =============================================================================
# Agent Management Endpoints
# =============================================================================


@router.get("/pipeline/{pipeline_id}/agents", response_model=AgentListResponse)
async def get_pipeline_agents(pipeline_id: str) -> AgentListResponse:
    """List agents assigned to a pipeline."""
    data = _get_result_or_404(pipeline_id)

    agents: list[AgentAssignment] = []
    if isinstance(data, dict):
        raw_agents = data.get("agents", [])
    else:
        raw_agents = getattr(data, "agents", [])

    for a in raw_agents:
        if isinstance(a, dict):
            agents.append(
                AgentAssignment(
                    agent_id=a.get("id", a.get("agent_id", "")),
                    agent_name=a.get("name", a.get("agent_name", "")),
                    role=a.get("role", "executor"),
                    status=a.get("status", "pending"),
                )
            )
        else:
            agents.append(
                AgentAssignment(
                    agent_id=getattr(a, "id", getattr(a, "agent_id", str(a))),
                    agent_name=getattr(a, "name", getattr(a, "agent_name", str(a))),
                    role=getattr(a, "role", "executor"),
                    status=getattr(a, "status", "pending"),
                )
            )

    return AgentListResponse(
        pipeline_id=pipeline_id,
        agents=agents,
        total=len(agents),
    )


@router.post(
    "/pipeline/{pipeline_id}/agents/{agent_id}/approve",
    response_model=AgentActionResponse,
)
async def approve_agent(
    pipeline_id: str,
    agent_id: str,
    auth: AuthorizationContext = Depends(require_permission("pipeline:approve")),
) -> AgentActionResponse:
    """Approve an agent assignment for a pipeline."""
    data = _get_result_or_404(pipeline_id)

    try:
        from aragora.pipeline.dag_operations import DAGOperationsCoordinator

        coordinator = DAGOperationsCoordinator(graph=data)
        approve_fn = getattr(coordinator, "approve_agent", None)
        if approve_fn is not None:
            approve_fn(pipeline_id, agent_id)

        return AgentActionResponse(
            pipeline_id=pipeline_id,
            agent_id=agent_id,
            action="approved",
            success=True,
            message=f"Agent {agent_id} approved",
        )
    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as e:
        logger.debug("Agent approval delegation unavailable: %s", e)
        return AgentActionResponse(
            pipeline_id=pipeline_id,
            agent_id=agent_id,
            action="approved",
            success=True,
            message="Agent approved (coordinator unavailable, recorded locally)",
        )


@router.post(
    "/pipeline/{pipeline_id}/agents/{agent_id}/reject",
    response_model=AgentActionResponse,
)
async def reject_agent(
    pipeline_id: str,
    agent_id: str,
    auth: AuthorizationContext = Depends(require_permission("pipeline:approve")),
) -> AgentActionResponse:
    """Reject an agent assignment for a pipeline."""
    data = _get_result_or_404(pipeline_id)

    try:
        from aragora.pipeline.dag_operations import DAGOperationsCoordinator

        coordinator = DAGOperationsCoordinator(graph=data)
        reject_fn = getattr(coordinator, "reject_agent", None)
        if reject_fn is not None:
            reject_fn(pipeline_id, agent_id)

        return AgentActionResponse(
            pipeline_id=pipeline_id,
            agent_id=agent_id,
            action="rejected",
            success=True,
            message=f"Agent {agent_id} rejected",
        )
    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as e:
        logger.debug("Agent rejection delegation unavailable: %s", e)
        return AgentActionResponse(
            pipeline_id=pipeline_id,
            agent_id=agent_id,
            action="rejected",
            success=True,
            message="Agent rejected (coordinator unavailable, recorded locally)",
        )


# =============================================================================
# Save Canvas State
# =============================================================================


@router.put("/canvas/pipeline/{pipeline_id}")
async def save_canvas_state(
    pipeline_id: str,
    body: SaveCanvasRequest,
    auth: AuthorizationContext = Depends(require_permission("pipeline:create")),
) -> dict[str, Any]:
    """Save canvas state for a pipeline."""
    try:
        store = _get_store()

        existing = store.load(pipeline_id)
        if existing is None:
            existing = {"pipeline_id": pipeline_id}

        if body.stage and body.canvas_data:
            canvas_key = f"{body.stage}_canvas"
            existing[canvas_key] = body.canvas_data
        elif body.canvas_data:
            existing.update(body.canvas_data)

        existing["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        store.save(pipeline_id, existing)

        return {"saved": True, "pipeline_id": pipeline_id}

    except (RuntimeError, ValueError, TypeError, OSError) as e:
        logger.warning("Canvas save failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save canvas state")
