"""Runs endpoints (FastAPI).

Provides read-only access to persisted backbone run ledgers:
- GET /api/runs
- GET /api/runs/{run_id}
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from aragora.rbac.models import AuthorizationContext
from aragora.server.handlers.governance.runs import handle_run_detail, handle_runs_list
from aragora.server.fastapi.dependencies.auth import require_permission

router = APIRouter(prefix="/api", tags=["Runs"])
_RUNS_READ_PERMISSION = "orchestration:read"


class RunStageSummary(BaseModel):
    """Collapsed latest status for a single stage."""

    stage: str
    status: str
    created_at: str | None = None


class RunSummary(BaseModel):
    """Compact backbone run summary."""

    run_id: str
    status: str
    stages: list[RunStageSummary] = Field(default_factory=list)
    execution_id: str | None = None
    receipt_id: str | None = None
    safety_mode: str | None = None
    created_at: str | None = None


class RunListResponse(BaseModel):
    """Response model for GET /api/runs."""

    runs: list[RunSummary] = Field(default_factory=list)


class RunDetailResponse(BaseModel):
    """Response model for GET /api/runs/{run_id}."""

    run: RunSummary


async def get_runs_store(request: Request) -> Any:
    """Resolve the plan store from app state or the module singleton."""
    ctx = getattr(request.app.state, "context", None)
    if ctx and ctx.get("plan_store") is not None:
        return ctx["plan_store"]

    from aragora.pipeline.plan_store import get_plan_store

    return get_plan_store()


def _error_detail(payload: dict[str, Any]) -> Any:
    """Normalize handler error payloads for FastAPI exceptions."""
    detail = payload.get("error", "Request failed")
    if isinstance(detail, dict):
        return detail.get("message", detail)
    return detail


def _unwrap_handler_result(result: Any) -> dict[str, Any]:
    """Convert a legacy HandlerResult into a FastAPI-friendly payload."""
    payload = result.to_dict()["body"] if hasattr(result, "to_dict") else result
    status_code = getattr(result, "status_code", 200)

    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=_error_detail(payload))

    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Invalid handler response")

    return payload


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    request: Request,
    status: str | None = Query(None, description="Optional run status filter"),
    limit: int = Query(50, ge=1, le=100, description="Maximum results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    auth: AuthorizationContext = Depends(require_permission(_RUNS_READ_PERMISSION)),
    store: Any = Depends(get_runs_store),
) -> RunListResponse:
    """List persisted backbone runs. Requires `orchestration:read`."""
    del auth, request  # request is kept for route signature parity with other route modules
    payload = _unwrap_handler_result(
        handle_runs_list(
            {"status": status, "limit": limit, "offset": offset},
            store=store,
        )
    )
    return RunListResponse(**payload)


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: str,
    auth: AuthorizationContext = Depends(require_permission(_RUNS_READ_PERMISSION)),
    store: Any = Depends(get_runs_store),
) -> RunDetailResponse:
    """Fetch one persisted backbone run. Requires `orchestration:read`."""
    del auth
    payload = _unwrap_handler_result(handle_run_detail(run_id, store=store))
    return RunDetailResponse(**payload)


__all__ = [
    "RunDetailResponse",
    "RunListResponse",
    "RunStageSummary",
    "RunSummary",
    "get_run",
    "get_runs_store",
    "list_runs",
    "router",
]
