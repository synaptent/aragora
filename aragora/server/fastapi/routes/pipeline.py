"""
Pipeline Endpoints (FastAPI v2).

Surfaces the idea-to-execution pipeline backend as REST endpoints:
- GET    /api/v2/pipeline/runs                 - List pipeline runs with pagination
- POST   /api/v2/pipeline/runs                 - Start a new pipeline run
- GET    /api/v2/pipeline/runs/{run_id}        - Get pipeline run status and details
- GET    /api/v2/pipeline/runs/{run_id}/stages - Get individual stage results
- POST   /api/v2/pipeline/runs/{run_id}/approve - Approve a stage gate
- DELETE /api/v2/pipeline/runs/{run_id}        - Cancel a pipeline run

Runs belong to the org that started them. Every route needs a signed-in caller
acting for an org; another org's run, a run with no recorded org and a missing
run all answer the same 404, checked before the permission.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from aragora.tenancy.record_scope import record_not_found_error, record_visible

from ..dependencies.auth import check_permission
from ..dependencies.pipeline_access import (
    PIPELINE_CREATE,
    PIPELINE_DELETE,
    PIPELINE_READ,
    PIPELINE_RUN,
    PipelineCaller,
    pipeline_permission,
    require_pipeline_caller,
)
from ..middleware.error_handling import NotFoundError

logger = logging.getLogger(__name__)

_RUN = "Pipeline run"

router = APIRouter(prefix="/api/v2", tags=["Pipeline"])

# =============================================================================
# Pydantic Models
# =============================================================================


class PipelineRunCreate(BaseModel):
    """Request body for POST /pipeline/runs."""

    idea: str = Field(
        ..., min_length=1, max_length=5000, description="Idea or goal text to process"
    )
    config: dict[str, Any] | None = Field(
        None, description="Optional pipeline configuration overrides"
    )


class PipelineStageResponse(BaseModel):
    """Individual pipeline stage result."""

    stage_name: str
    status: str  # pending, running, completed, failed, skipped
    output: dict[str, Any] | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration: float = 0.0
    error: str | None = None


class PipelineRunResponse(BaseModel):
    """Full pipeline run details."""

    id: str
    idea: str
    status: str  # pending, running, completed, failed, cancelled
    stages: list[PipelineStageResponse] = Field(default_factory=list)
    created_at: str
    updated_at: str
    config: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None

    model_config = {"extra": "allow"}


class PipelineRunSummary(BaseModel):
    """Summary of a pipeline run for list views."""

    id: str
    idea: str
    status: str
    created_at: str
    updated_at: str
    stage_count: int = 0
    completed_stages: int = 0


class PipelineListResponse(BaseModel):
    """Response for pipeline run listing."""

    runs: list[PipelineRunSummary]
    total: int
    limit: int
    offset: int


class PipelineApproveRequest(BaseModel):
    """Request body for POST /pipeline/runs/{run_id}/approve."""

    stage: str = Field(..., description="Stage name to approve (e.g., 'ideation', 'goals')")
    feedback: str | None = Field(None, max_length=2000, description="Optional reviewer feedback")


class PipelineApproveResponse(BaseModel):
    """Response for stage approval."""

    approved: bool
    run_id: str
    stage: str
    message: str


class PipelineDeleteResponse(BaseModel):
    """Response for DELETE /pipeline/runs/{run_id}."""

    cancelled: bool
    id: str


class PipelineStagesResponse(BaseModel):
    """Response for GET /pipeline/runs/{run_id}/stages."""

    run_id: str
    stages: list[PipelineStageResponse]
    total: int


# =============================================================================
# In-memory store (production would use persistent storage)
# =============================================================================

_pipeline_runs: dict[str, dict[str, Any]] = {}


def _get_pipeline_store() -> dict[str, dict[str, Any]]:
    """Return the pipeline run store."""
    return _pipeline_runs


# =============================================================================
# Dependencies
# =============================================================================


async def get_pipeline_store(request: Request) -> dict[str, dict[str, Any]]:
    """Dependency to get the pipeline store from app state or fallback to module store."""
    ctx = getattr(request.app.state, "context", None)
    if ctx and ctx.get("pipeline_store") is not None:
        return ctx["pipeline_store"]
    return _get_pipeline_store()


def _visible_to(run: Any, caller: PipelineCaller) -> bool:
    return isinstance(run, dict) and record_visible(run.get("org_id"), caller.scope)


@dataclass(frozen=True, slots=True)
class OwnedRun:
    """A run the caller's org owns, with the caller acting on it."""

    caller: PipelineCaller
    run: dict[str, Any]


def owned_run(permission: str) -> Callable[..., Awaitable[OwnedRun]]:
    """Dependency for routes on ``{run_id}``: the caller's org must own the run
    (else the shared 404), then the caller needs ``permission``."""

    async def dependency(
        run_id: str,
        caller: PipelineCaller = Depends(require_pipeline_caller),
        store: dict[str, dict[str, Any]] = Depends(get_pipeline_store),
    ) -> OwnedRun:
        run = store.get(run_id)
        if run is None or not _visible_to(run, caller):
            raise record_not_found_error(_RUN)
        check_permission(caller.auth, permission)
        return OwnedRun(caller=caller, run=run)

    return dependency


# =============================================================================
# Pipeline Execution Helper
# =============================================================================


def _execute_pipeline(
    idea: str,
    run_id: str,
    stages_to_run: list[str],
    config: dict[str, Any],
) -> Any:
    """Execute the pipeline and return the result.

    Extracted as a module-level function so tests can patch it cleanly.
    Raises ImportError/RuntimeError/etc. if the pipeline backend is unavailable.
    """
    from aragora.pipeline.idea_to_execution import (
        IdeaToExecutionPipeline,
        PipelineConfig,
    )

    pipeline_config = PipelineConfig(
        stages_to_run=stages_to_run,
        dry_run=config.get("dry_run", False),
        human_approval_required=config.get("human_approval_required", False),
    )

    pipeline = IdeaToExecutionPipeline()
    return pipeline.from_ideas(
        [idea],
        auto_advance=not pipeline_config.human_approval_required,
        pipeline_id=run_id,
    )


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/pipeline/runs", response_model=PipelineListResponse)
async def list_pipeline_runs(
    request: Request,
    limit: int = Query(50, ge=1, le=100, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    status: str | None = Query(None, description="Filter by status"),
    caller: PipelineCaller = Depends(pipeline_permission(PIPELINE_READ)),
    store: dict[str, dict[str, Any]] = Depends(get_pipeline_store),
) -> PipelineListResponse:
    """
    List the caller org's pipeline runs with pagination.

    Returns a paginated list of pipeline run summaries.
    """
    try:
        all_runs = [run for run in store.values() if _visible_to(run, caller)]

        # Filter by status if provided
        if status:
            all_runs = [r for r in all_runs if r.get("status") == status]

        total = len(all_runs)

        # Sort by created_at descending (most recent first)
        all_runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)

        # Paginate
        paginated = all_runs[offset : offset + limit]

        runs = []
        for r in paginated:
            stages = r.get("stages", [])
            completed = sum(1 for s in stages if s.get("status") == "completed")
            runs.append(
                PipelineRunSummary(
                    id=r["id"],
                    idea=r.get("idea", ""),
                    status=r.get("status", "unknown"),
                    created_at=r.get("created_at", ""),
                    updated_at=r.get("updated_at", ""),
                    stage_count=len(stages),
                    completed_stages=completed,
                )
            )

        return PipelineListResponse(
            runs=runs,
            total=total,
            limit=limit,
            offset=offset,
        )

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error listing pipeline runs: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list pipeline runs")


@router.post("/pipeline/runs", response_model=PipelineRunResponse, status_code=201)
async def create_pipeline_run(
    body: PipelineRunCreate,
    caller: PipelineCaller = Depends(pipeline_permission(PIPELINE_CREATE)),
    store: dict[str, dict[str, Any]] = Depends(get_pipeline_store),
) -> PipelineRunResponse:
    """
    Start a new pipeline run owned by the caller's org.

    Creates a pipeline run from an idea/goal text and begins processing.
    Requires `canvas:create` permission.
    """
    try:
        run_id = f"pipe-{uuid.uuid4().hex[:12]}"
        now = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Build config
        config = body.config or {}

        # Default stages
        default_stages = ["ideation", "goals", "workflow", "orchestration"]
        stages_to_run = config.get("stages_to_run", default_stages)

        stages = [
            {
                "stage_name": stage,
                "status": "pending",
                "output": None,
                "started_at": None,
                "completed_at": None,
                "duration": 0.0,
                "error": None,
            }
            for stage in stages_to_run
        ]

        run_data: dict[str, Any] = {
            "id": run_id,
            "idea": body.idea,
            "status": "pending",
            "stages": stages,
            "created_at": now,
            "updated_at": now,
            "config": config,
            "result": None,
            **caller.owner_fields(),
        }

        # Try to start the pipeline
        try:
            result = _execute_pipeline(body.idea, run_id, stages_to_run, config)

            run_data["status"] = "completed"
            run_data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if result:
                run_data["result"] = result.to_dict() if hasattr(result, "to_dict") else None
                # Update stage statuses from result
                if hasattr(result, "stage_results") and result.stage_results:
                    for sr in result.stage_results:
                        for stage in run_data["stages"]:
                            if stage["stage_name"] == sr.stage_name:
                                stage["status"] = sr.status
                                stage["duration"] = sr.duration
                                if sr.error:
                                    stage["error"] = sr.error
                                if sr.output and hasattr(sr.output, "to_dict"):
                                    stage["output"] = {"type": type(sr.output).__name__}
                                break
                # Update stage statuses from result.stage_status
                if hasattr(result, "stage_status") and result.stage_status:
                    for stage in run_data["stages"]:
                        stage_key = stage["stage_name"]
                        if stage_key in result.stage_status:
                            mapped = result.stage_status[stage_key]
                            if mapped == "complete":
                                stage["status"] = "completed"
                            elif mapped != "pending":
                                stage["status"] = mapped

        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.warning("Pipeline execution failed, storing as pending: %s", e)
            run_data["status"] = "pending"

        store[run_id] = run_data

        stage_responses = [
            PipelineStageResponse(
                stage_name=s["stage_name"],
                status=s["status"],
                output=s.get("output"),
                started_at=s.get("started_at"),
                completed_at=s.get("completed_at"),
                duration=s.get("duration", 0.0),
                error=s.get("error"),
            )
            for s in run_data["stages"]
        ]

        logger.info("Pipeline run %s created for idea: %s", run_id, body.idea[:80])

        return PipelineRunResponse(
            id=run_id,
            idea=body.idea,
            status=run_data["status"],
            stages=stage_responses,
            created_at=run_data["created_at"],
            updated_at=run_data["updated_at"],
            config=config,
            result=run_data.get("result"),
        )

    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error creating pipeline run: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create pipeline run")


@router.get("/pipeline/runs/{run_id}", response_model=PipelineRunResponse)
async def get_pipeline_run(
    run_id: str,
    owned: OwnedRun = Depends(owned_run(PIPELINE_READ)),
) -> PipelineRunResponse:
    """
    Get pipeline run status and details.

    Returns full pipeline run details including all stage results.
    """
    try:
        run_data = owned.run

        stage_responses = [
            PipelineStageResponse(
                stage_name=s["stage_name"],
                status=s["status"],
                output=s.get("output"),
                started_at=s.get("started_at"),
                completed_at=s.get("completed_at"),
                duration=s.get("duration", 0.0),
                error=s.get("error"),
            )
            for s in run_data.get("stages", [])
        ]

        return PipelineRunResponse(
            id=run_data["id"],
            idea=run_data.get("idea", ""),
            status=run_data.get("status", "unknown"),
            stages=stage_responses,
            created_at=run_data.get("created_at", ""),
            updated_at=run_data.get("updated_at", ""),
            config=run_data.get("config", {}),
            result=run_data.get("result"),
        )

    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting pipeline run %s: %s", run_id, e)
        raise HTTPException(status_code=500, detail="Failed to get pipeline run")


@router.get("/pipeline/runs/{run_id}/stages", response_model=PipelineStagesResponse)
async def get_pipeline_stages(
    run_id: str,
    owned: OwnedRun = Depends(owned_run(PIPELINE_READ)),
) -> PipelineStagesResponse:
    """
    Get individual stage results for a pipeline run.

    Returns detailed information about each stage in the pipeline.
    """
    try:
        run_data = owned.run

        stages = [
            PipelineStageResponse(
                stage_name=s["stage_name"],
                status=s["status"],
                output=s.get("output"),
                started_at=s.get("started_at"),
                completed_at=s.get("completed_at"),
                duration=s.get("duration", 0.0),
                error=s.get("error"),
            )
            for s in run_data.get("stages", [])
        ]

        return PipelineStagesResponse(
            run_id=run_id,
            stages=stages,
            total=len(stages),
        )

    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting stages for pipeline run %s: %s", run_id, e)
        raise HTTPException(status_code=500, detail="Failed to get pipeline stages")


_VALID_STAGE_NAMES = {"ideation", "goals", "workflow", "orchestration", "principles"}


@router.post("/pipeline/runs/{run_id}/approve", response_model=PipelineApproveResponse)
async def approve_pipeline_stage(
    run_id: str,
    body: PipelineApproveRequest,
    owned: OwnedRun = Depends(owned_run(PIPELINE_RUN)),
) -> PipelineApproveResponse:
    """
    Approve a stage gate in a pipeline run.

    Human-in-the-loop approval to advance the pipeline to the next stage.
    Requires `canvas:run` permission.
    """
    try:
        run_data = owned.run

        if run_data.get("status") == "cancelled":
            raise HTTPException(status_code=400, detail="Cannot approve a cancelled pipeline run")

        if body.stage not in _VALID_STAGE_NAMES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid stage name. Must be one of: {', '.join(sorted(_VALID_STAGE_NAMES))}",
            )

        # Find and approve the stage
        stage_found = False
        for stage in run_data.get("stages", []):
            if stage["stage_name"] == body.stage:
                stage_found = True
                if stage["status"] == "completed":
                    raise HTTPException(
                        status_code=400,
                        detail=f"Stage '{body.stage}' is already completed",
                    )
                stage["status"] = "completed"
                stage["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                break

        if not stage_found:
            raise HTTPException(
                status_code=400,
                detail=f"Stage '{body.stage}' not found in this pipeline run",
            )

        run_data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Check if all stages are completed
        all_completed = all(
            s.get("status") in ("completed", "skipped") for s in run_data.get("stages", [])
        )
        if all_completed:
            run_data["status"] = "completed"

        logger.info(
            "Pipeline run %s stage '%s' approved by %s",
            run_id,
            body.stage,
            owned.caller.scope.user_id,
        )

        return PipelineApproveResponse(
            approved=True,
            run_id=run_id,
            stage=body.stage,
            message=f"Stage '{body.stage}' approved successfully",
        )

    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error approving pipeline stage %s/%s: %s", run_id, body.stage, e)
        raise HTTPException(status_code=500, detail="Failed to approve pipeline stage")


@router.delete("/pipeline/runs/{run_id}", response_model=PipelineDeleteResponse)
async def cancel_pipeline_run(
    run_id: str,
    owned: OwnedRun = Depends(owned_run(PIPELINE_DELETE)),
) -> PipelineDeleteResponse:
    """
    Cancel a pipeline run.

    Marks the pipeline run as cancelled and stops any further processing.
    Requires `canvas:delete` permission.
    """
    try:
        run_data = owned.run

        if run_data.get("status") in ("completed", "cancelled"):
            raise HTTPException(
                status_code=400,
                detail=f"Pipeline run is already {run_data['status']}",
            )

        run_data["status"] = "cancelled"
        run_data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Mark pending stages as skipped
        for stage in run_data.get("stages", []):
            if stage.get("status") == "pending":
                stage["status"] = "skipped"

        logger.info("Pipeline run %s cancelled by %s", run_id, owned.caller.scope.user_id)

        return PipelineDeleteResponse(cancelled=True, id=run_id)

    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error cancelling pipeline run %s: %s", run_id, e)
        raise HTTPException(status_code=500, detail="Failed to cancel pipeline run")


# =============================================================================
# Execute Workflow from Pipeline
# =============================================================================


class ExecuteWorkflowResponse(BaseModel):
    """Response for POST /pipeline/runs/{run_id}/execute-workflow."""

    workflow_id: str
    pipeline_id: str
    execution_id: str | None = None
    steps_count: int
    transitions_count: int
    status: str


@router.post(
    "/pipeline/runs/{run_id}/execute-workflow",
    response_model=ExecuteWorkflowResponse,
    status_code=201,
)
async def execute_workflow_from_pipeline(
    run_id: str,
    owned: OwnedRun = Depends(owned_run(PIPELINE_RUN)),
) -> ExecuteWorkflowResponse:
    """
    Create, persist, and start a workflow from a pipeline's goal graph.

    Converts the pipeline result's goal graph into a WorkflowDefinition
    via ``canvas_to_workflow()``, stores it through the workflow subsystem,
    and starts a real execution record for the caller's org.
    Requires ``canvas:run`` permission.
    """
    run_data = owned.run
    scope = owned.caller.scope

    try:
        from aragora.pipeline.idea_to_execution import (
            PipelineResult,
            canvas_to_workflow,
        )

        # Reconstruct PipelineResult from stored data
        stored_result = run_data.get("result")
        if not stored_result:
            raise HTTPException(
                status_code=400,
                detail="Pipeline has no result yet; run the pipeline first",
            )

        # Build a minimal PipelineResult with the goal graph
        pipeline_result = PipelineResult(pipeline_id=run_id)

        # Restore the goal graph if available
        goal_graph_data = stored_result.get("goals")
        if goal_graph_data:
            from aragora.goals.extractor import GoalGraph, GoalNode
            from aragora.canvas.stages import GoalNodeType

            goal_nodes = []
            for g in goal_graph_data.get("goals", []):
                goal_nodes.append(
                    GoalNode(
                        id=g["id"],
                        title=g.get("title", ""),
                        description=g.get("description", ""),
                        goal_type=GoalNodeType(g.get("type", "goal")),
                        priority=g.get("priority", "medium"),
                        measurable=g.get("measurable", ""),
                        dependencies=g.get("dependencies", []),
                        source_idea_ids=g.get("source_idea_ids", []),
                        confidence=g.get("confidence", 0.0),
                        metadata=g.get("metadata", {}),
                    )
                )
            pipeline_result.goal_graph = GoalGraph(
                id=goal_graph_data.get("id", f"gg-{run_id}"),
                goals=goal_nodes,
                metadata=goal_graph_data.get("metadata", {}),
            )

        workflow_def = canvas_to_workflow(pipeline_result)
        if not workflow_def.steps:
            raise HTTPException(
                status_code=400,
                detail="Pipeline result has no executable workflow steps",
            )

        from aragora.server.handlers.workflows.crud import create_workflow
        from aragora.server.handlers.workflows.execution import execute_workflow

        # Not the caller's X-Workspace-ID header, which nothing validates: the
        # workflow and execution rows belong to the org that owns the run.
        tenant_id = scope.org_id
        created_workflow = await create_workflow(
            workflow_def.to_dict(),
            tenant_id=tenant_id,
            created_by=scope.user_id,
        )
        workflow_id = str(created_workflow.get("id") or workflow_def.id)

        execution_result = await execute_workflow(
            workflow_id,
            inputs={"pipeline_id": run_id},
            tenant_id=tenant_id,
            user_id=scope.user_id,
            org_id=scope.org_id,
        )
        execution_id = (
            str(execution_result.get("execution_id") or execution_result.get("id") or "") or None
        )
        workflow_status = str(execution_result.get("status") or "running")

        # Persist workflow reference in the run data
        run_data["workflow_id"] = workflow_id
        run_data["execution_id"] = execution_id
        run_data["workflow_status"] = workflow_status
        run_data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        logger.info(
            "Workflow %s created and executed from pipeline %s (%d steps, %d transitions)",
            workflow_id,
            run_id,
            len(workflow_def.steps),
            len(workflow_def.transitions),
        )

        return ExecuteWorkflowResponse(
            workflow_id=workflow_id,
            pipeline_id=run_id,
            execution_id=execution_id,
            steps_count=len(workflow_def.steps),
            transitions_count=len(workflow_def.transitions),
            status=workflow_status,
        )

    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (ImportError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
        logger.exception("Error creating workflow from pipeline %s: %s", run_id, e)
        raise HTTPException(
            status_code=500,
            detail="Failed to create workflow from pipeline",
        )
